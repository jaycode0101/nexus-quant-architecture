/**
 * order_entry_gateway.h — Order Entry Gateway (OEG) Kernel-Bypass TX
 */

#ifndef HFT_ORDER_ENTRY_GATEWAY_H
#define HFT_ORDER_ENTRY_GATEWAY_H

#include "platform.h"
#include <stdint.h>

/**
 * SBE (Simple Binary Encoding) order frame template.
 *
 * Pre-built in NIC-registered memory at initialization. Only variable fields
 * (price, quantity, order ID, timestamp) are patched at submission time.
 *
 * SBE NewOrderSingle layout (simplified for demonstration):
 *   Offset  Size  Field              Notes
 *   0       2     MessageLength      SBE header
 *   2       2     TemplateId         NewOrderSingle = 0x0001
 *   4       2     SchemaId           Exchange-specific
 *   6       2     Version            SBE schema version
 *   8       8     ClOrdId            Client Order ID (patched)
 *   16      4     InstrumentId       Exchange instrument ID (static per template)
 *   20      8     Price              Fixed-point price (patched)
 *   28      4     Quantity           Order quantity (patched)
 *   32      1     Side               '1' = Buy, '2' = Sell
 *   33      1     OrderType          '2' = Limit
 *   34      1     TimeInForce        '0' = Day, '3' = IOC
 *   35      1     _padding
 *   36      8     TransactTime       Submission timestamp (patched)
 *   44      4     SequenceNumber     Session sequence number (patched)
 *   48      -- end --
 */

#define SBE_ORDER_FRAME_SIZE  48

/* Field offsets within the SBE frame for patching */
#define SBE_OFFSET_CLORDID       8
#define SBE_OFFSET_PRICE        20
#define SBE_OFFSET_QUANTITY     28
#define SBE_OFFSET_TRANSACT     36
#define SBE_OFFSET_SEQNO        44

typedef struct oeg_ctx {
    /* EF_VI virtual interface for TX */
    ef_vi           vi;
    ef_driver_handle driver;
    ef_pd           pd;

    /* Pre-built SBE order frame template — in NIC-registered memory */
    uint8_t         frame_template[SBE_ORDER_FRAME_SIZE] HFT_ALIGNED(64);

    /* Working frame — copy of template, patched per-order */
    uint8_t        *tx_buffer;           /* Huge-page-backed, DMA-registered */
    uint64_t        tx_buffer_dma_addr;
    size_t          tx_buffer_size;

    /* Sequence number — atomic for lock-free increment.
     *
     * Memory ordering: __ATOMIC_RELAXED is safe here because:
     *   1. This is single-producer — only the OEG thread writes sequence numbers
     *   2. No other thread reads the sequence number concurrently
     *   3. The sequence number only needs to be monotonically increasing within
     *      the TCP session; global visibility is irrelevant
     *   4. The release semantics are provided by the ef_vi_transmit() call itself,
     *      which issues a write-memory-barrier as part of the doorbell write
     */
    volatile uint64_t sequence_number;

    /* TX hardware timestamp from last transmission */
    uint64_t        last_tx_hw_timestamp;

    /* Statistics */
    uint64_t        orders_submitted;
    uint64_t        tx_errors;

} oeg_ctx_t;

/**
 * Initialize the Order Entry Gateway.
 *
 * @param ctx           OEG context to initialize
 * @param interface     Network interface name
 * @param instrument_id Exchange instrument ID for the pre-built template
 * @param side          '1' = Buy, '2' = Sell (default template side)
 * @return 0 on success, -1 on failure
 */
int oeg_init(oeg_ctx_t *ctx, const char *interface,
             uint32_t instrument_id, uint8_t side);

/**
 * Patch the pre-built SBE order frame and submit via kernel-bypass.
 *
 * This is the ORDER SUBMISSION CRITICAL PATH — the absolute hottest code
 * in the entire system. Target latency: ≤ 40ns from call to NIC doorbell write.
 *
 * Operations:
 *   1. Copy template to TX buffer (48 bytes — fits in one cache line)
 *   2. Patch 4 variable fields: price, quantity, order_id, timestamp
 *   3. Patch sequence number (atomic fetch-and-add, relaxed)
 *   4. ef_vi_transmit() — write the buffer DMA address to the NIC's TX ring
 *      doorbell, triggering immediate transmission
 *
 * @param ctx       Initialized OEG context
 * @param price     Order price in fixed-point (8 decimals)
 * @param qty       Order quantity in shares
 * @param order_id  Client order ID (unique per session)
 * @return 0 on success, -1 on TX ring full
 */
int oeg_patch_and_submit(oeg_ctx_t *ctx,
                         int64_t price,
                         uint32_t qty,
                         uint64_t order_id);

/**
 * Process TX completion events to retrieve hardware timestamps.
 * Called periodically from the OEG thread (not on the critical path).
 *
 * @param ctx  OEG context
 * @return Number of TX completions processed
 */
int oeg_poll_tx_completions(oeg_ctx_t *ctx);

/**
 * Destroy and release OEG resources.
 */
void oeg_destroy(oeg_ctx_t *ctx);

#endif /* HFT_ORDER_ENTRY_GATEWAY_H */
