/**
 * order_entry_gateway.c — Order Entry Gateway Implementation
 *
 * Kernel-bypass order submission via Solarflare EF_VI / TCPDirect.
 * Pre-built SBE frames stored in NIC-registered memory; only variable
 * fields are patched at submission time.
 *
 * Compilation: gcc -std=c11 -O3 -march=native order_entry_gateway.c
 */

#include "order_entry_gateway.h"
#include <string.h>

int oeg_init(oeg_ctx_t *ctx, const char *interface,
             uint32_t instrument_id, uint8_t side)
{
    int rc;
    memset(ctx, 0, sizeof(oeg_ctx_t));

    /* --- EF_VI TX Setup --- */

    rc = ef_driver_open(&ctx->driver);
    if (rc < 0) return -1;

    int ifindex = 0;  /* Production: if_nametoindex(interface) */
    (void)interface;

    rc = ef_pd_alloc(&ctx->pd, ctx->driver, ifindex, 0);
    if (rc < 0) return -1;

    /* Allocate VI with TX ring only (no RX needed for order entry) */
    rc = ef_vi_alloc_from_pd(
        &ctx->vi, ctx->driver, &ctx->pd, ctx->driver,
        1024,   /* evq capacity */
        0,      /* rxq capacity (unused) */
        1024,   /* txq capacity */
        NULL, 0, 0
    );
    if (rc < 0) return -1;

    /* --- Allocate TX buffer on huge pages --- */

    ctx->tx_buffer_size = 4096;  /* One page — more than enough for SBE frame */
    ctx->tx_buffer = (uint8_t*)hft_huge_page_alloc(ctx->tx_buffer_size, 0);
    if (ctx->tx_buffer == NULL) return -1;
    memset(ctx->tx_buffer, 0, ctx->tx_buffer_size);

    /* Set DMA address (production: obtained from ef_memreg) */
    ctx->tx_buffer_dma_addr = (uint64_t)(uintptr_t)ctx->tx_buffer;

    /* Register TX buffer with NIC for DMA */
    ef_memreg mem_reg;
    ef_memreg_alloc(&mem_reg, ctx->driver, &ctx->pd, ctx->driver,
                    ctx->tx_buffer, ctx->tx_buffer_size);

    /* --- Build SBE Order Frame Template ---
     *
     * The template contains all static fields pre-populated.
     * At submission time, only 4 fields are patched:
     *   - ClOrdId (order ID)
     *   - Price
     *   - Quantity
     *   - TransactTime (submission timestamp)
     *   - SequenceNumber
     *
     * This minimizes the work on the critical path.
     */

    uint8_t *tmpl = ctx->frame_template;
    memset(tmpl, 0, SBE_ORDER_FRAME_SIZE);

    /* SBE Header */
    uint16_t msg_len = SBE_ORDER_FRAME_SIZE;
    memcpy(tmpl + 0, &msg_len, 2);          /* MessageLength (little-endian for SBE) */

    uint16_t template_id = 0x0001;           /* NewOrderSingle */
    memcpy(tmpl + 2, &template_id, 2);

    uint16_t schema_id = 0x0001;
    memcpy(tmpl + 4, &schema_id, 2);

    uint16_t version = 0x0001;
    memcpy(tmpl + 6, &version, 2);

    /* Static fields */
    memcpy(tmpl + 16, &instrument_id, 4);    /* InstrumentId */
    tmpl[32] = side;                          /* Side: '1' = Buy, '2' = Sell */
    tmpl[33] = '2';                           /* OrderType: Limit */
    tmpl[34] = '0';                           /* TimeInForce: Day */

    ctx->sequence_number = 1;

    fprintf(stdout, "[OEG] Initialized: instrument=%u, side=%c, template=%d bytes\n",
            instrument_id, side, SBE_ORDER_FRAME_SIZE);

    return 0;
}

int oeg_patch_and_submit(oeg_ctx_t *ctx,
                         int64_t price,
                         uint32_t qty,
                         uint64_t order_id)
{
    /*
     * -------------------------------------------------------
     * ORDER SUBMISSION CRITICAL PATH
     * Target: ≤ 40ns from function entry to ef_vi_transmit()
     * -------------------------------------------------------
     *
     * Step 1: Copy template to TX buffer (48 bytes = 3/4 of a cache line).
     * The template is in L1 cache (hot from recent submissions); the TX buffer
     * is pre-fetched by the NIC DMA engine from the previous transmission.
     */
    memcpy(ctx->tx_buffer, ctx->frame_template, SBE_ORDER_FRAME_SIZE);

    /*
     * Step 2: Patch variable fields.
     *
     * Each memcpy is ≤ 8 bytes, which the compiler optimizes to a single
     * MOV instruction (verified via -S output). No branches, no function calls.
     */
    memcpy(ctx->tx_buffer + SBE_OFFSET_CLORDID, &order_id, 8);
    memcpy(ctx->tx_buffer + SBE_OFFSET_PRICE,   &price,    8);
    memcpy(ctx->tx_buffer + SBE_OFFSET_QUANTITY, &qty,      4);

    /* Timestamp: RDTSC-based nanosecond counter for sub-microsecond precision */
    uint64_t transact_time = hft_rdtsc();
    memcpy(ctx->tx_buffer + SBE_OFFSET_TRANSACT, &transact_time, 8);

    /*
     * Step 3: Sequence number with atomic fetch-and-add.
     *
     * __ATOMIC_RELAXED is safe because:
     *   - Single producer: only this thread writes sequence numbers
     *   - No concurrent reader: the sequence number is only read by the exchange
     *     after it's been transmitted on the wire
     *   - The ef_vi_transmit() doorbell write provides the necessary ordering
     *     between the buffer content writes and the NIC's DMA read of the buffer
     */
    uint64_t seq = hft_atomic_fetch_add_relaxed(&ctx->sequence_number, 1);
    uint32_t seq32 = (uint32_t)seq;
    memcpy(ctx->tx_buffer + SBE_OFFSET_SEQNO, &seq32, 4);

    /*
     * Step 4: Submit to NIC via kernel-bypass.
     *
     * ef_vi_transmit() writes the buffer's DMA address and length to the
     * NIC's TX descriptor ring and rings the doorbell register (a PCIe
     * posted write). The NIC then DMA-reads the buffer and transmits
     * the frame on the wire.
     *
     * This is the last instruction on the critical path — after this,
     * the packet is in-flight to the matching engine via the co-lo
     * cross-connect.
     */
    int rc = ef_vi_transmit(
        &ctx->vi,
        ctx->tx_buffer_dma_addr,
        SBE_ORDER_FRAME_SIZE,
        (int)seq32   /* DMA completion ID for TX timestamp retrieval */
    );

    if (HFT_UNLIKELY(rc != 0)) {
        ctx->tx_errors++;
        return -1;
    }

    ctx->orders_submitted++;
    return 0;
}

int oeg_poll_tx_completions(oeg_ctx_t *ctx)
{
    /*
     * NON-CRITICAL PATH: Process TX completion events.
     *
     * After the NIC transmits a frame, it posts a completion event to the
     * event queue. For frames sent with EF_EVENT_TYPE_TX_WITH_TIMESTAMP,
     * the completion includes a hardware TX timestamp from the NIC's PTP
     * clock — this is the most accurate measure of when the frame hit the wire.
     *
     * We use this for:
     *   1. Precise order-to-ack latency measurement
     *   2. TX buffer recycling (though we reuse a single buffer)
     *   3. Sequence number acknowledgment tracking
     */
    ef_event events[16];
    int n = ef_eventq_poll(&ctx->vi, events, 16);

    for (int i = 0; i < n; ++i) {
        if (events[i].type == EF_EVENT_TYPE_TX_WITH_TIMESTAMP) {
            ctx->last_tx_hw_timestamp = events[i].tx_timestamp;
        }
    }

    return n;
}

void oeg_destroy(oeg_ctx_t *ctx)
{
    if (ctx->tx_buffer) {
        hft_huge_page_free(ctx->tx_buffer, ctx->tx_buffer_size);
        ctx->tx_buffer = NULL;
    }
}
