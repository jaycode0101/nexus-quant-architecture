/**
 * ef_vi_receiver.h — EF_VI Kernel-Bypass UDP Multicast Receiver
 */

#ifndef HFT_EF_VI_RECEIVER_H
#define HFT_EF_VI_RECEIVER_H

#include "platform.h"
#include "itch_parser.h"
#include "spsc_ring.h"

/* Number of RX packet buffers in the DMA ring */
#define RX_RING_SIZE    4096
/* Size of each packet buffer (jumbo frame capable) */
#define PKT_BUF_SIZE    2048
/* UDP header + IP header size to skip to get to ITCH payload */
#define UDP_HEADER_LEN  42

/**
 * rx_buffer_t — Pre-allocated DMA-registered receive buffer.
 */
typedef struct {
    uint8_t  data[PKT_BUF_SIZE] HFT_ALIGNED(64);
    uint64_t dma_addr;
    int      buf_id;
} rx_buffer_t;

/**
 * ef_vi_receiver_t — Kernel-bypass multicast receiver context.
 *
 * All fields are allocated on the NUMA node local to the NIC's PCIe
 * root complex (NUMA node 0) to minimize DMA latency.
 */
typedef struct {
    /* Solarflare EF_VI resources */
    ef_driver_handle  driver_handle;
    ef_pd             protection_domain;
    ef_vi             virtual_interface;
    ef_memreg         mem_registration;

    /* DMA receive buffers — huge-page-backed, NIC-registered */
    rx_buffer_t      *rx_buffers;           /* Array of RX_RING_SIZE buffers */
    size_t            rx_buffers_size;       /* Total allocation size */

    /* ITCH parser for processing received packets */
    itch_parser_ctx_t parser;

    /* Statistics */
    uint64_t          packets_received;
    uint64_t          bytes_received;
    uint64_t          rx_discards;
    uint64_t          poll_empty_cycles;

    /* Control */
    volatile int      running;               /* Atomic flag to stop the poll loop */

} ef_vi_receiver_t;

/**
 * Initialize the EF_VI receiver.
 *
 * Performs the complete EF_VI resource allocation chain:
 *   1. ef_driver_open() — open the Solarflare driver
 *   2. ef_pd_alloc() — allocate a protection domain on the NIC interface
 *   3. ef_vi_alloc_from_pd() — allocate a virtual interface with RX/TX/EVQ rings
 *   4. mmap(MAP_HUGETLB) — allocate DMA-capable receive buffers on huge pages
 *   5. ef_memreg_alloc() — register the buffers with the NIC for DMA access
 *   6. Post initial batch of RX buffer descriptors to the NIC RX ring
 *
 * @param recv         Receiver context to initialize
 * @param interface    Network interface name (e.g., "enp1s0f0")
 * @param mcast_addr   Multicast group IP address (network byte order)
 * @param mcast_port   Multicast port (network byte order)
 * @param output_ring  SPSC ring buffer for outputting parsed MdEvents
 * @return 0 on success, -1 on failure
 */
int ef_vi_receiver_init(ef_vi_receiver_t *recv,
                        const char *interface,
                        uint32_t mcast_addr,
                        uint16_t mcast_port,
                        spsc_ring_t *output_ring);

/**
 * Run the EF_VI receive poll loop.
 *
 * This is the hot-path busy-poll loop that runs on an isolated core.
 * It never sleeps, never blocks, never makes system calls.
 *
 * Loop body:
 *   1. ef_eventq_poll() — poll the event queue for completion events
 *   2. For each EF_EVENT_TYPE_RX event:
 *      a. ef_vi_receive_get_bytes() — get zero-copy pointer to packet data
 *      b. Skip UDP/IP headers (42 bytes) to get ITCH payload
 *      c. itch_parse_packet() — parse and write MdEvents to SPSC ring
 *      d. ef_vi_receive_post() — recycle the buffer descriptor back to RX ring
 *   3. For EF_EVENT_TYPE_RX_DISCARD: increment metric, recycle buffer
 *   4. If no events: continue polling (busy-wait on isolated core)
 *
 * @param recv  Initialized receiver context
 */
void ef_vi_receiver_poll_loop(ef_vi_receiver_t *recv);

/**
 * Stop the poll loop (called from a different thread).
 */
void ef_vi_receiver_stop(ef_vi_receiver_t *recv);

/**
 * Destroy and release all EF_VI resources.
 */
void ef_vi_receiver_destroy(ef_vi_receiver_t *recv);

#endif /* HFT_EF_VI_RECEIVER_H */
