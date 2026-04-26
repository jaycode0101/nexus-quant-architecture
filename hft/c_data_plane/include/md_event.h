/**
 * md_event.h — Normalized Market Data Event Structure
 *
 * This is the canonical data structure that flows through the entire pipeline:
 *   C Feed Handler → SPSC Ring → Java Disruptor → LOB/Feature/Strategy
 *
 * Layout is fixed at 64 bytes (one cache line) to maximize cache utilization
 * and minimize false sharing when accessed from the ring buffer.
 *
 * The Java side accesses these fields via sun.misc.Unsafe with known offsets,
 * so this struct MUST NOT be reordered without updating MdEvent.java field offsets.
 *
 * All prices are in fixed-point: 8 decimal places (multiply by 10^8).
 * Example: $123.45 → 12345000000 (int64_t)
 *
 * Timestamps are nanoseconds since midnight UTC.
 */

#ifndef HFT_MD_EVENT_H
#define HFT_MD_EVENT_H

#include "platform.h"
#include <stdint.h>

/* --- Message Type Codes --- */

#define MD_MSG_ADD_ORDER       'A'   /* ITCH Add Order (no MPID) */
#define MD_MSG_ADD_ORDER_MPID  'F'   /* ITCH Add Order (with MPID) */
#define MD_MSG_EXECUTE_ORDER   'E'   /* ITCH Order Executed */
#define MD_MSG_CANCEL_ORDER    'X'   /* ITCH Order Cancel */
#define MD_MSG_DELETE_ORDER    'D'   /* ITCH Order Delete */
#define MD_MSG_REPLACE_ORDER   'U'   /* ITCH Order Replace */
#define MD_MSG_TRADE           'P'   /* ITCH Non-Cross Trade */
#define MD_MSG_SYSTEM          'S'   /* System Event */
#define MD_MSG_STOCK_DIR       'R'   /* Stock Directory */

/* --- Side Codes --- */

#define MD_SIDE_BUY   'B'
#define MD_SIDE_SELL   'S'

/**
 * MdEvent — Normalized market data event.
 *
 * 64 bytes = 1 cache line. Packed with explicit padding to guarantee
 * identical layout across C and Java (via Unsafe offsets).
 *
 * Java interop offsets (from base address of this struct):
 *   message_type:  0
 *   side:          1
 *   _pad0:         2-3
 *   instrument_id: 4-7
 *   order_id:      8-15
 *   price:         16-23    (fixed-point, 8 decimals)
 *   quantity:      24-27
 *   _pad1:         28-31
 *   timestamp_ns:  32-39    (nanoseconds since midnight UTC)
 *   sequence_no:   40-47
 *   exec_shares:   48-51    (for execute messages)
 *   match_number:  52-59    (for trade messages)
 *   _pad2:         60-63
 */
typedef struct HFT_ALIGNED(64) md_event {
    /* Byte 0-3 */
    uint8_t  message_type;       /* MD_MSG_* constant */
    uint8_t  side;               /* MD_SIDE_BUY / MD_SIDE_SELL */
    uint8_t  _pad0[2];

    /* Byte 4-7 */
    uint32_t instrument_id;      /* Locate code / instrument hash */

    /* Byte 8-15 */
    uint64_t order_id;           /* Exchange order reference number */

    /* Byte 16-23 */
    int64_t  price;              /* Fixed-point: price * 10^8 */

    /* Byte 24-31 */
    uint32_t quantity;           /* Order quantity in shares */
    uint32_t _pad1;

    /* Byte 32-39 */
    int64_t  timestamp_ns;       /* Nanoseconds since midnight UTC */

    /* Byte 40-47 */
    uint64_t sequence_no;        /* Feed sequence number for gap detection */

    /* Byte 48-59 */
    uint32_t exec_shares;        /* Shares executed (for EXECUTE messages) */
    uint64_t match_number;       /* Trade match number (for TRADE messages) */

    /* Byte 60-63 — padding to fill cache line */
    uint32_t _pad2;

} md_event_t;

/**
 * Compile-time assertions to guarantee struct layout matches Java Unsafe offsets.
 * If any of these fail, the C-Java shared memory bridge is broken.
 */
_Static_assert(sizeof(md_event_t) == 64,
    "md_event_t must be exactly 64 bytes (one cache line)");
_Static_assert(offsetof(md_event_t, message_type) == 0,
    "message_type must be at offset 0");
_Static_assert(offsetof(md_event_t, instrument_id) == 4,
    "instrument_id must be at offset 4");
_Static_assert(offsetof(md_event_t, order_id) == 8,
    "order_id must be at offset 8");
_Static_assert(offsetof(md_event_t, price) == 16,
    "price must be at offset 16");
_Static_assert(offsetof(md_event_t, quantity) == 24,
    "quantity must be at offset 24");
_Static_assert(offsetof(md_event_t, timestamp_ns) == 32,
    "timestamp_ns must be at offset 32");
_Static_assert(offsetof(md_event_t, sequence_no) == 40,
    "sequence_no must be at offset 40");

/* --- Fixed-Point Price Helpers --- */

#define MD_PRICE_SCALE     100000000LL   /* 10^8 */

/**
 * Convert a raw ITCH price (4 bytes, big-endian, 4 implied decimals)
 * to our fixed-point representation (8 decimals).
 */
HFT_INLINE int64_t md_itch_price_to_fixed(uint32_t itch_price_be) {
    uint32_t price_host = hft_bswap32(itch_price_be);
    /* ITCH prices have 4 implied decimals; we use 8 → multiply by 10^4 */
    return (int64_t)price_host * 10000LL;
}

/**
 * Convert fixed-point price to double (for display/logging only — NEVER in hot path).
 */
static inline double md_price_to_double(int64_t fixed_price) {
    return (double)fixed_price / (double)MD_PRICE_SCALE;
}

#endif /* HFT_MD_EVENT_H */
