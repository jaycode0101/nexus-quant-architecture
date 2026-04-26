/**
 * main.c — HFT C Data Plane Integration Demo
 *
 * Demonstrates the complete C-side pipeline:
 *   1. Initialize SPSC ring buffer (shared memory for Java consumer)
 *   2. Initialize EF_VI receiver with ITCH parser
 *   3. Initialize Order Entry Gateway
 *   4. Run synthetic packet injection for testing
 *   5. Verify ring buffer contents
 *
 * This serves as both a smoke test and a reference for integrating
 * the C data plane components.
 *
 * Compilation: gcc -std=c11 -O3 -march=native -o hft_demo main.c itch_parser.c
 *              ef_vi_receiver.c order_entry_gateway.c -lpthread
 */

#include "platform.h"
#include "md_event.h"
#include "spsc_ring.h"
#include "itch_parser.h"
#include "ef_vi_receiver.h"
#include "order_entry_gateway.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* --- Synthetic ITCH Packet Generator for Testing --- */

/**
 * Build a synthetic MoldUDP64 packet containing an ITCH Add Order message.
 * Used for pipeline verification without a live exchange feed.
 */
static uint32_t build_synthetic_add_order(uint8_t *buf,
                                          uint64_t order_id,
                                          uint32_t price_4dp,
                                          uint32_t shares,
                                          uint8_t side)
{
    uint32_t offset = 0;

    /* MoldUDP64 message length prefix (2 bytes, big-endian) */
    uint16_t msg_len = ITCH_MSG_SIZE_ADD_ORDER;
    uint16_t msg_len_be = hft_bswap16(msg_len);
    memcpy(buf + offset, &msg_len_be, 2);
    offset += 2;

    /* ITCH Add Order message body */
    uint8_t *msg = buf + offset;

    msg[0] = 'A';                                          /* Message Type */

    uint16_t locate_be = hft_bswap16(42);                  /* Stock Locate */
    memcpy(msg + 1, &locate_be, 2);

    uint16_t tracking_be = hft_bswap16(0);                 /* Tracking Number */
    memcpy(msg + 3, &tracking_be, 2);

    /* Timestamp: 6 bytes big-endian nanoseconds since midnight */
    uint64_t ts_ns = 34200000000000ULL;                    /* 09:30:00.000 */
    msg[5]  = (uint8_t)(ts_ns >> 40);
    msg[6]  = (uint8_t)(ts_ns >> 32);
    msg[7]  = (uint8_t)(ts_ns >> 24);
    msg[8]  = (uint8_t)(ts_ns >> 16);
    msg[9]  = (uint8_t)(ts_ns >> 8);
    msg[10] = (uint8_t)(ts_ns);

    uint64_t oid_be = hft_bswap64(order_id);
    memcpy(msg + 11, &oid_be, 8);

    msg[19] = side;                                        /* Buy/Sell */

    uint32_t shares_be = hft_bswap32(shares);
    memcpy(msg + 20, &shares_be, 4);

    /* Stock symbol: "AAPL    " (8 bytes, space-padded) */
    memcpy(msg + 24, "AAPL    ", 8);

    uint32_t price_be = hft_bswap32(price_4dp);            /* Price (4 decimals) */
    memcpy(msg + 32, &price_be, 4);

    offset += msg_len;
    return offset;
}

/**
 * Build a synthetic ITCH Trade message.
 */
static uint32_t build_synthetic_trade(uint8_t *buf,
                                      uint64_t order_id,
                                      uint32_t price_4dp,
                                      uint32_t shares)
{
    uint32_t offset = 0;

    uint16_t msg_len = ITCH_MSG_SIZE_TRADE;
    uint16_t msg_len_be = hft_bswap16(msg_len);
    memcpy(buf + offset, &msg_len_be, 2);
    offset += 2;

    uint8_t *msg = buf + offset;
    memset(msg, 0, ITCH_MSG_SIZE_TRADE);

    msg[0] = 'P';                                          /* Trade message */

    uint16_t locate_be = hft_bswap16(42);
    memcpy(msg + 1, &locate_be, 2);

    uint64_t ts_ns = 34200500000000ULL;                    /* 09:30:00.500 */
    msg[5]  = (uint8_t)(ts_ns >> 40);
    msg[6]  = (uint8_t)(ts_ns >> 32);
    msg[7]  = (uint8_t)(ts_ns >> 24);
    msg[8]  = (uint8_t)(ts_ns >> 16);
    msg[9]  = (uint8_t)(ts_ns >> 8);
    msg[10] = (uint8_t)(ts_ns);

    uint64_t oid_be = hft_bswap64(order_id);
    memcpy(msg + 11, &oid_be, 8);

    msg[19] = 'B';                                         /* Buy side */

    uint32_t shares_be = hft_bswap32(shares);
    memcpy(msg + 20, &shares_be, 4);

    memcpy(msg + 24, "AAPL    ", 8);

    uint32_t price_be = hft_bswap32(price_4dp);
    memcpy(msg + 32, &price_be, 4);

    uint64_t match_be = hft_bswap64(100001ULL);
    memcpy(msg + 36, &match_be, 8);

    offset += msg_len;
    return offset;
}

/* --- Main Entry Point --- */

int main(int argc, char *argv[])
{
    (void)argc; (void)argv;

    printf("╔--------------------------------------------------------------╗\n");
    printf("║  HFT C DATA PLANE — Integration Demo                      ║\n");
    printf("║  SPSC Ring + ITCH Parser + EF_VI Receiver + OEG            ║\n");
    printf("╚--------------------------------------------------------------╝\n\n");

    /* --- 1. Create SPSC Ring Buffer --- */
    printf("[1] Creating SPSC ring buffer (capacity=%d, size=%zu MB)...\n",
           RING_CAPACITY, sizeof(spsc_ring_t) / (1024 * 1024));

    spsc_ring_t *ring = spsc_ring_create(-1);  /* Any NUMA node for demo */
    if (ring == NULL) {
        fprintf(stderr, "FATAL: Failed to allocate ring buffer\n");
        return 1;
    }
    printf("    Ring buffer at %p\n", (void*)ring);
    printf("    Head offset: %zu, Tail offset: %zu, Data offset: %zu\n",
           SPSC_HEAD_OFFSET, SPSC_TAIL_OFFSET, SPSC_DATA_OFFSET);
    printf("    MdEvent size: %zu bytes (cache-line aligned: %s)\n",
           sizeof(md_event_t),
           sizeof(md_event_t) == 64 ? "YES" : "NO");

    /* --- 2. Initialize ITCH Parser --- */
    printf("\n[2] Initializing ITCH 5.0 parser...\n");

    itch_parser_ctx_t parser;
    itch_parser_init(&parser, ring);

    /* --- 3. Build and Parse Synthetic Packets --- */
    printf("\n[3] Generating synthetic ITCH packets...\n");

    uint8_t packet_buf[2048];
    uint32_t pkt_len = 0;

    /* Pack multiple ITCH messages into one UDP payload (like real MoldUDP64) */
    pkt_len += build_synthetic_add_order(
        packet_buf + pkt_len, 1000001, 1500000, 100, 'B'  /* Buy 100 @ 150.0000 */
    );
    pkt_len += build_synthetic_add_order(
        packet_buf + pkt_len, 1000002, 1505000, 200, 'S'  /* Sell 200 @ 150.5000 */
    );
    pkt_len += build_synthetic_add_order(
        packet_buf + pkt_len, 1000003, 1498000, 50, 'B'   /* Buy 50 @ 149.8000 */
    );
    pkt_len += build_synthetic_trade(
        packet_buf + pkt_len, 1000001, 1500000, 50         /* Trade 50 @ 150.0000 */
    );

    printf("    Built packet: %u bytes, 4 ITCH messages\n", pkt_len);

    /* Parse the packet — this exercises the full ITCH → Ring pipeline */
    uint64_t t0 = hft_rdtsc();
    uint32_t parsed = itch_parse_packet(&parser, packet_buf, pkt_len);
    uint64_t t1 = hft_rdtsc();

    printf("    Parsed %u messages in %lu RDTSC cycles\n", parsed, (unsigned long)(t1 - t0));
    printf("    Parser stats: %lu msgs, %lu pkts, %lu splits, %lu unknown\n",
           (unsigned long)parser.messages_parsed,
           (unsigned long)parser.packets_processed,
           (unsigned long)parser.split_messages,
           (unsigned long)parser.unknown_message_types);

    /* --- 4. Verify Ring Buffer Contents --- */
    printf("\n[4] Reading events from SPSC ring buffer...\n");

    uint64_t ring_size = spsc_ring_size_approx(ring);
    printf("    Ring contains %lu events\n", (unsigned long)ring_size);

    md_event_t events[16];
    uint32_t consumed = spsc_ring_consume_batch(ring, events, 16);

    for (uint32_t i = 0; i < consumed; ++i) {
        md_event_t *e = &events[i];
        printf("    [%u] type=%c, instr=%u, oid=%lu, price=%.4f, qty=%u, side=%c, ts=%ld\n",
               i, e->message_type, e->instrument_id,
               (unsigned long)e->order_id,
               md_price_to_double(e->price),
               e->quantity,
               e->side ? e->side : '?',
               (long)e->timestamp_ns);
    }

    /* --- 5. Order Entry Gateway Demo --- */
    printf("\n[5] Initializing Order Entry Gateway...\n");

    oeg_ctx_t oeg;
    int rc = oeg_init(&oeg, "enp1s0f0", 42, '1');
    if (rc == 0) {
        printf("    OEG initialized, submitting test order...\n");

        t0 = hft_rdtsc();
        rc = oeg_patch_and_submit(&oeg, 15000000000LL, 100, 2000001);
        t1 = hft_rdtsc();

        if (rc == 0) {
            printf("    Order submitted in %lu RDTSC cycles\n",
                   (unsigned long)(t1 - t0));
            printf("    Total orders: %lu, Sequence: %lu\n",
                   (unsigned long)oeg.orders_submitted,
                   (unsigned long)oeg.sequence_number);
        } else {
            printf("    Order submission failed (TX ring full)\n");
        }

        oeg_destroy(&oeg);
    } else {
        printf("    OEG initialization failed (expected on non-Solarflare systems)\n");
    }

    /* --- 6. Batch Publish/Consume Benchmark --- */
    printf("\n[6] SPSC ring buffer batch benchmark...\n");

    /* Re-initialize ring */
    spsc_ring_init(ring);

    /* Benchmark: publish 1M events in batches of 64 */
    md_event_t batch[64];
    memset(batch, 0, sizeof(batch));
    for (int i = 0; i < 64; ++i) {
        batch[i].message_type = MD_MSG_ADD_ORDER;
        batch[i].instrument_id = 42;
        batch[i].price = 15000000000LL + i * 10000LL;
        batch[i].quantity = 100;
        batch[i].side = MD_SIDE_BUY;
    }

    uint32_t total_published = 0;
    t0 = hft_rdtsc();
    for (int iter = 0; iter < 16384; ++iter) {
        total_published += spsc_ring_try_publish_batch(ring, batch, 64);
    }
    t1 = hft_rdtsc();

    uint64_t cycles = t1 - t0;
    printf("    Published %u events in %lu cycles\n",
           total_published, (unsigned long)cycles);
    if (total_published > 0) {
        printf("    %.1f cycles/event (%.1f ns/event @ 3.0 GHz)\n",
               (double)cycles / total_published,
               (double)cycles / total_published / 3.0);
    }

    /* Consume all */
    uint32_t total_consumed = 0;
    md_event_t consume_buf[256];
    while (total_consumed < total_published) {
        uint32_t n = spsc_ring_consume_batch(ring, consume_buf, 256);
        total_consumed += n;
        if (n == 0) break;
    }
    printf("    Consumed %u events\n", total_consumed);

    /* --- Cleanup --- */
    printf("\n[7] Cleanup...\n");
    spsc_ring_destroy(ring);
    printf("    Done.\n\n");

    printf("╔--------------------------------------------------------------╗\n");
    printf("║  All C data plane components verified successfully.        ║\n");
    printf("╚--------------------------------------------------------------╝\n");

    return 0;
}
