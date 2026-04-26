/**
 * itch_parser.h — SIMD-Accelerated Nasdaq ITCH 5.0 Binary Protocol Parser
 *
 * Parses raw UDP payloads containing concatenated ITCH 5.0 messages using
 * AVX-512 / AVX2 SIMD intrinsics for branchless message-type scanning and
 * boundary detection.
 *
 * Target: < 15ns average per-message parse latency on representative ITCH traffic.
 *
 * ITCH 5.0 message format:
 *   - Each message starts with a 2-byte big-endian length prefix (MoldUDP64)
 *   - Followed by a 1-byte message type character
 *   - Followed by message-type-specific fields
 *
 * Key message types handled:
 *   'A' = Add Order (no MPID):     36 bytes
 *   'F' = Add Order (with MPID):   40 bytes
 *   'E' = Order Executed:          31 bytes
 *   'X' = Order Cancel:            23 bytes
 *   'D' = Order Delete:            19 bytes
 *   'U' = Order Replace:           35 bytes
 *   'P' = Trade (non-cross):       44 bytes
 */

#ifndef HFT_ITCH_PARSER_H
#define HFT_ITCH_PARSER_H

#include "platform.h"
#include "md_event.h"
#include "spsc_ring.h"

#include <immintrin.h>
#include <string.h>

/* --- ITCH 5.0 Message Sizes (excluding 2-byte MoldUDP64 length prefix) --- */

#define ITCH_MSG_SIZE_ADD_ORDER       36
#define ITCH_MSG_SIZE_ADD_ORDER_MPID  40
#define ITCH_MSG_SIZE_EXECUTE         31
#define ITCH_MSG_SIZE_CANCEL          23
#define ITCH_MSG_SIZE_DELETE          19
#define ITCH_MSG_SIZE_REPLACE         35
#define ITCH_MSG_SIZE_TRADE           44
#define ITCH_MSG_SIZE_SYSTEM           12
#define ITCH_MSG_SIZE_STOCK_DIR       39

/**
 * Parser context — maintains state for split-message reassembly.
 *
 * When an ITCH message spans two UDP packets (the 2-byte length prefix
 * indicates more data than remains in the current packet), the parser
 * copies the partial message into this stateful reassembly buffer.
 * The next packet's data is appended, and parsing resumes.
 *
 * No heap allocation: the reassembly buffer is a fixed-size array
 * embedded in the context struct.
 */
typedef struct itch_parser_ctx {
    /* Reassembly buffer for split messages (max ITCH message = 50 bytes) */
    uint8_t  reassembly_buf[64];
    uint32_t reassembly_len;         /* Bytes currently in reassembly buffer */
    uint32_t reassembly_expected;    /* Total expected message length */

    /* Statistics */
    uint64_t messages_parsed;
    uint64_t packets_processed;
    uint64_t split_messages;
    uint64_t unknown_message_types;
    uint64_t discard_events;

    /* Output: ring buffer to write parsed MdEvents into */
    spsc_ring_t *output_ring;

} itch_parser_ctx_t;

/**
 * Initialize the parser context.
 *
 * @param ctx         Parser context to initialize
 * @param output_ring Ring buffer for outputting parsed MdEvents
 */
void itch_parser_init(itch_parser_ctx_t *ctx, spsc_ring_t *output_ring);

/**
 * Parse a complete UDP payload containing concatenated ITCH 5.0 messages.
 *
 * This is the hot-path entry point. It processes all messages in a single
 * pass, dispatching each to a specialized parser that writes directly into
 * the SPSC ring buffer.
 *
 * @param ctx     Parser context (maintains split-message state)
 * @param payload Raw UDP payload (pointer directly into DMA buffer — zero-copy)
 * @param len     Payload length in bytes
 * @return Number of messages parsed from this packet
 */
uint32_t itch_parse_packet(itch_parser_ctx_t *ctx,
                           const uint8_t *payload,
                           uint32_t len);

/**
 * Get the message size for a given ITCH message type.
 * Returns 0 for unknown message types.
 */
static inline uint32_t itch_message_size(uint8_t msg_type) {
    switch (msg_type) {
        case 'A': return ITCH_MSG_SIZE_ADD_ORDER;
        case 'F': return ITCH_MSG_SIZE_ADD_ORDER_MPID;
        case 'E': return ITCH_MSG_SIZE_EXECUTE;
        case 'X': return ITCH_MSG_SIZE_CANCEL;
        case 'D': return ITCH_MSG_SIZE_DELETE;
        case 'U': return ITCH_MSG_SIZE_REPLACE;
        case 'P': return ITCH_MSG_SIZE_TRADE;
        case 'S': return ITCH_MSG_SIZE_SYSTEM;
        case 'R': return ITCH_MSG_SIZE_STOCK_DIR;
        default:  return 0;
    }
}

#endif /* HFT_ITCH_PARSER_H */
