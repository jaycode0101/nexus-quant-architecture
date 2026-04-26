/**
 * ef_vi_receiver.c — EF_VI Kernel-Bypass UDP Multicast Receiver Implementation
 *
 * Complete implementation of the Solarflare EF_VI packet receive pipeline
 * for ingesting exchange multicast feeds (Nasdaq ITCH 5.0 over UDP/IP multicast).
 *
 * This runs on an isolated core (Core 1, NUMA Node 0) in a tight busy-poll loop
 * with zero system calls and zero context switches during steady-state operation.
 *
 * DMA Buffer Lifecycle:
 *   1. At init: allocate huge-page memory, register with NIC via ef_memreg_alloc()
 *   2. Post buffer descriptors to RX ring via ef_vi_receive_post()
 *   3. NIC writes incoming packets directly into our huge-page buffers via DMA
 *   4. ef_eventq_poll() returns completion events with buffer IDs
 *   5. We parse the packet in-place (zero-copy) from the DMA buffer
 *   6. After parsing, immediately repost the buffer descriptor to the RX ring
 *
 * Compilation: gcc -std=c11 -O3 -march=native ef_vi_receiver.c -letherfabric
 * (On development systems without Solarflare SDK, compile with stub EF_VI from platform.h)
 */

#include "ef_vi_receiver.h"

int ef_vi_receiver_init(ef_vi_receiver_t *recv,
                        const char *interface,
                        uint32_t mcast_addr,
                        uint16_t mcast_port,
                        spsc_ring_t *output_ring)
{
    int rc;
    memset(recv, 0, sizeof(ef_vi_receiver_t));
    recv->running = 0;

    /* Initialize ITCH parser with output ring */
    itch_parser_init(&recv->parser, output_ring);

    /* --- Step 1: Open the Solarflare driver --- */
    rc = ef_driver_open(&recv->driver_handle);
    if (rc < 0) {
        fprintf(stderr, "[EF_VI] ef_driver_open failed: %d\n", rc);
        return -1;
    }

    /* --- Step 2: Allocate a protection domain on the NIC interface ---
     *
     * The protection domain (PD) is the NIC-side security boundary.
     * All memory registered under this PD can be DMA'd to/from the
     * virtual interface associated with it.
     *
     * In production, `ifindex` is obtained from the interface name
     * via if_nametoindex(). Here we use 0 for the stub.
     */
    int ifindex = 0;  /* Production: if_nametoindex(interface) */
    (void)interface;
    rc = ef_pd_alloc(&recv->protection_domain, recv->driver_handle, ifindex, 0);
    if (rc < 0) {
        fprintf(stderr, "[EF_VI] ef_pd_alloc failed: %d\n", rc);
        return -1;
    }

    /* --- Step 3: Allocate a virtual interface with RX/TX/EVQ rings ---
     *
     * The virtual interface (VI) is the core EF_VI abstraction:
     *   - EVQ (Event Queue): completion notifications from NIC → CPU
     *   - RXQ (Receive Queue): buffer descriptors CPU → NIC
     *   - TXQ (Transmit Queue): send descriptors CPU → NIC
     *
     * We allocate only RXQ (no TX needed for the feed handler).
     * EVQ capacity must be >= RXQ capacity.
     */
    rc = ef_vi_alloc_from_pd(
        &recv->virtual_interface,
        recv->driver_handle,
        &recv->protection_domain,
        recv->driver_handle,    /* evq driver handle */
        RX_RING_SIZE,           /* evq capacity */
        RX_RING_SIZE,           /* rxq capacity */
        0,                      /* txq capacity (unused for receiver) */
        NULL, 0,                /* options */
        0                       /* flags */
    );
    if (rc < 0) {
        fprintf(stderr, "[EF_VI] ef_vi_alloc_from_pd failed: %d\n", rc);
        return -1;
    }

    /* --- Step 4: Allocate DMA receive buffers on huge pages ---
     *
     * Key requirement: the NIC writes directly into these buffers via DMA,
     * bypassing the OS network stack entirely. The buffers must be:
     *   1. Physically contiguous (huge pages ensure this for 2MB regions)
     *   2. Registered with the NIC's IOMMU (ef_memreg_alloc)
     *   3. On the NUMA node local to the NIC's PCIe root complex (node 0)
     */
    recv->rx_buffers_size = (size_t)RX_RING_SIZE * sizeof(rx_buffer_t);
    recv->rx_buffers = (rx_buffer_t*)hft_huge_page_alloc(
        recv->rx_buffers_size, 0  /* NUMA node 0 — NIC-local */
    );
    if (recv->rx_buffers == NULL) {
        fprintf(stderr, "[EF_VI] Failed to allocate %zu bytes of DMA buffer memory\n",
                recv->rx_buffers_size);
        return -1;
    }
    memset(recv->rx_buffers, 0, recv->rx_buffers_size);

    /* Initialize buffer IDs */
    for (int i = 0; i < RX_RING_SIZE; ++i) {
        recv->rx_buffers[i].buf_id = i;
        /* DMA address would be set from ef_memreg in production */
        recv->rx_buffers[i].dma_addr = (uint64_t)(uintptr_t)recv->rx_buffers[i].data;
    }

    /* --- Step 5: Register memory with the NIC for DMA ---
     *
     * ef_memreg_alloc() pins the physical pages and programs the NIC's IOMMU
     * to allow DMA access to this memory region. After this call, the NIC can
     * write received packets directly into our buffers without CPU involvement.
     */
    rc = ef_memreg_alloc(
        &recv->mem_registration,
        recv->driver_handle,
        &recv->protection_domain,
        recv->driver_handle,
        recv->rx_buffers,
        recv->rx_buffers_size
    );
    if (rc < 0) {
        fprintf(stderr, "[EF_VI] ef_memreg_alloc failed: %d\n", rc);
        hft_huge_page_free(recv->rx_buffers, recv->rx_buffers_size);
        return -1;
    }

    /* --- Step 6: Post initial RX buffer descriptors to the NIC ---
     *
     * Each ef_vi_receive_post() tells the NIC: "here's a buffer you can
     * write the next received packet into." The NIC maintains a ring of
     * these descriptors and fills them in order.
     */
    for (int i = 0; i < RX_RING_SIZE; ++i) {
        ef_vi_receive_post(
            &recv->virtual_interface,
            i,                              /* buffer ID */
            recv->rx_buffers[i].dma_addr    /* DMA address of buffer */
        );
    }

    /* --- Step 7: Set up multicast filter ---
     *
     * Configure the NIC to steer multicast traffic for the specified
     * group/port to our virtual interface.
     */
    ef_filter_spec filter;
    ef_filter_spec_init(&filter, 0);
    ef_filter_spec_set_ip4_local(&filter, 17 /* IPPROTO_UDP */,
                                  mcast_addr, mcast_port);
    rc = ef_vi_filter_add(&recv->virtual_interface, recv->driver_handle,
                           &filter, NULL);
    if (rc < 0) {
        fprintf(stderr, "[EF_VI] ef_vi_filter_add failed: %d\n", rc);
        /* Non-fatal in development; the stub always succeeds */
    }

    fprintf(stdout, "[EF_VI] Receiver initialized: %d RX buffers, %zu bytes DMA memory\n",
            RX_RING_SIZE, recv->rx_buffers_size);

    return 0;
}

void ef_vi_receiver_poll_loop(ef_vi_receiver_t *recv)
{
    ef_event events[64];  /* Batch up to 64 completion events per poll */
    recv->running = 1;

    fprintf(stdout, "[EF_VI] Entering poll loop on isolated core\n");

    /*
     * HOT PATH — This loop runs continuously on an isolated core.
     *
     * Constraints:
     *   - No system calls (no read, write, epoll, futex)
     *   - No memory allocation (no malloc, mmap)
     *   - No kernel transitions (no interrupts — NIC interrupt coalescing disabled)
     *   - No sleeping (pure busy-poll)
     *
     * The only synchronization is the atomic store to the SPSC ring buffer head
     * index (release semantics) when a parsed event is published.
     */
    while (HFT_LIKELY(recv->running)) {
        /* Poll the event queue for NIC completion events */
        int n_events = ef_eventq_poll(&recv->virtual_interface, events, 64);

        if (HFT_UNLIKELY(n_events == 0)) {
            /*
             * No events available. On a co-located system with active market
             * data, this should be rare during trading hours.
             *
             * We do NOT call _mm_pause() here because:
             *   1. This core is isolated — no other thread benefits from yielding
             *   2. PAUSE adds 140 cycles on Skylake+ which increases worst-case
             *      latency when a packet arrives immediately after
             *   3. Power consumption is irrelevant on co-lo hardware
             *
             * However, we do increment a counter for monitoring: if
             * poll_empty_cycles is consistently high, it may indicate a
             * network configuration issue.
             */
            recv->poll_empty_cycles++;
            continue;
        }

        /* Process each completion event */
        for (int i = 0; i < n_events; ++i) {
            switch (events[i].type) {

                case EF_EVENT_TYPE_RX: {
                    /*
                     * Packet received: the NIC has written a complete UDP frame
                     * into one of our DMA buffers.
                     */
                    int buf_id = events[i].rx_id;
                    uint32_t pkt_len = events[i].len;

                    recv->packets_received++;
                    recv->bytes_received += pkt_len;

                    /*
                     * Zero-copy access: ef_vi_receive_get_bytes() returns a
                     * pointer directly into the DMA buffer — no memcpy.
                     * We skip the Ethernet + IP + UDP headers (42 bytes) to
                     * get to the MoldUDP64 / ITCH payload.
                     *
                     * In production, the actual offset depends on whether
                     * VLAN tags are present (add 4 bytes for 802.1Q).
                     */
                    const uint8_t *pkt_data = recv->rx_buffers[buf_id].data;

                    if (HFT_LIKELY(pkt_len > UDP_HEADER_LEN)) {
                        const uint8_t *itch_payload = pkt_data + UDP_HEADER_LEN;
                        uint32_t itch_len = pkt_len - UDP_HEADER_LEN;

                        /* Parse ITCH messages and publish to ring buffer */
                        itch_parse_packet(&recv->parser, itch_payload, itch_len);
                    }

                    /*
                     * Recycle the buffer: immediately repost the buffer descriptor
                     * to the NIC's RX ring so it can be reused for the next packet.
                     *
                     * This must happen AFTER parsing — once we repost, the NIC
                     * may overwrite the buffer at any time.
                     */
                    ef_vi_receive_post(
                        &recv->virtual_interface,
                        buf_id,
                        recv->rx_buffers[buf_id].dma_addr
                    );
                    break;
                }

                case EF_EVENT_TYPE_RX_DISCARD: {
                    /*
                     * The NIC discarded a packet (CRC error, buffer overflow, etc.).
                     * Increment metric but never block the poll loop.
                     */
                    recv->rx_discards++;
                    recv->discard_events++;

                    /* Still recycle the buffer */
                    int buf_id = events[i].rx_id;
                    ef_vi_receive_post(
                        &recv->virtual_interface,
                        buf_id,
                        recv->rx_buffers[buf_id].dma_addr
                    );
                    break;
                }

                default:
                    /* Unexpected event type — ignore */
                    break;
            }
        }
    }

    fprintf(stdout, "[EF_VI] Poll loop exited. Stats: %lu pkts, %lu bytes, %lu discards\n",
            (unsigned long)recv->packets_received,
            (unsigned long)recv->bytes_received,
            (unsigned long)recv->rx_discards);
}

void ef_vi_receiver_stop(ef_vi_receiver_t *recv) {
    recv->running = 0;
}

void ef_vi_receiver_destroy(ef_vi_receiver_t *recv) {
    if (recv->rx_buffers) {
        hft_huge_page_free(recv->rx_buffers, recv->rx_buffers_size);
        recv->rx_buffers = NULL;
    }
}
