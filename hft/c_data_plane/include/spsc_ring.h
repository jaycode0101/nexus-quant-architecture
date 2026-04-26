/**
 * spsc_ring.h — Lock-Free Single-Producer Single-Consumer Ring Buffer
 *
 * Cache-line-padded, power-of-2 capacity, huge-page-backed ring buffer for
 * passing MdEvent structs from the C feed handler to the Java strategy layer
 * via shared memory (mmap).
 *
 * Design constraints:
 *   - False-sharing elimination: producer head and consumer tail each occupy
 *     an individual 64-byte cache line with explicit padding
 *   - Memory ordering: acquire-release only (no seq_cst) — justified by SPSC topology
 *   - Capacity: compile-time parameterized, must be power of 2 for bitmask indexing
 *   - Zero-copy: data array is embedded in the shared mmap region; both C producer
 *     and Java consumer access events at the same physical addresses
 *
 * Java consumer interop:
 *   The Java side obtains the base address of this struct via mmap and reads:
 *     - head:  Unsafe.getLongVolatile(base + HEAD_OFFSET)  [acquire semantics]
 *     - tail:  Unsafe.putLongVolatile(base + TAIL_OFFSET, newTail)  [release semantics]
 *     - data:  Unsafe.getLong(base + DATA_OFFSET + slotIndex * 64 + fieldOffset)
 *
 *   HEAD_OFFSET = 0
 *   TAIL_OFFSET = 64  (next cache line)
 *   DATA_OFFSET = 128 (after the two control cache lines)
 */

#ifndef HFT_SPSC_RING_H
#define HFT_SPSC_RING_H

#include "platform.h"
#include "md_event.h"

/**
 * Ring buffer capacity. MUST be a power of 2.
 * Default: 2^20 = 1,048,576 slots × 64 bytes = 64 MB data array.
 */
#ifndef RING_CAPACITY
#define RING_CAPACITY  (1 << 20)
#endif

_Static_assert((RING_CAPACITY & (RING_CAPACITY - 1)) == 0,
    "RING_CAPACITY must be a power of 2 for bitmask indexing");

#define RING_MASK  (RING_CAPACITY - 1)

/**
 * spsc_ring_t — The ring buffer control structure.
 *
 * Memory layout (designed for shared mmap):
 *   Bytes [0, 63]:      Producer cache line (head index + padding)
 *   Bytes [64, 127]:    Consumer cache line (tail index + padding)
 *   Bytes [128, ...]:   Data array (RING_CAPACITY × 64-byte md_event_t slots)
 *
 * Total size: 128 + (RING_CAPACITY × 64) bytes
 * For default 1M capacity: 128 + 67,108,864 = ~64 MB
 *
 * False-sharing analysis:
 *   - The producer only writes to `head` (cache line 0) and data slots
 *   - The consumer only writes to `tail` (cache line 1) and reads data slots
 *   - `head` and `tail` are on separate cache lines → no false sharing
 *   - The producer reads `tail` to check available space (acquire load on consumer's line)
 *   - The consumer reads `head` to check available data (acquire load on producer's line)
 *   - These cross-cache-line reads are infrequent relative to data access and do not
 *     cause coherence traffic storms because they are read-only from the other thread's
 *     perspective
 */
typedef struct HFT_ALIGNED(64) spsc_ring {
    /* --- Cache Line 0: Producer (writer) --- */
    volatile uint64_t head;          /* Next slot to write (only producer writes) */
    uint64_t          cached_tail;   /* Producer's cached copy of tail (reduces cross-core reads) */
    char              _pad_producer[HFT_CACHE_LINE_SIZE - 2 * sizeof(uint64_t)];

    /* --- Cache Line 1: Consumer (reader) --- */
    volatile uint64_t tail;          /* Next slot to read (only consumer writes) */
    uint64_t          cached_head;   /* Consumer's cached copy of head (reduces cross-core reads) */
    char              _pad_consumer[HFT_CACHE_LINE_SIZE - 2 * sizeof(uint64_t)];

    /* --- Data Array: starts at byte 128 --- */
    md_event_t        data[RING_CAPACITY];

} spsc_ring_t;

/* Offsets for Java interop via Unsafe */
#define SPSC_HEAD_OFFSET  ((size_t)offsetof(spsc_ring_t, head))
#define SPSC_TAIL_OFFSET  ((size_t)offsetof(spsc_ring_t, tail))
#define SPSC_DATA_OFFSET  ((size_t)offsetof(spsc_ring_t, data))

/**
 * Initialize the ring buffer. Must be called before any publish/consume.
 * The ring should be allocated via hft_shared_mmap_alloc() for Java interop.
 */
static inline void spsc_ring_init(spsc_ring_t *ring) {
    memset(ring, 0, sizeof(spsc_ring_t));
    ring->head = 0;
    ring->tail = 0;
    ring->cached_tail = 0;
    ring->cached_head = 0;
}

/**
 * Allocate a ring buffer on huge pages in shared memory.
 *
 * @param numa_node  NUMA node for allocation (-1 for any)
 * @return Pointer to initialized ring, or NULL on failure
 */
static inline spsc_ring_t* spsc_ring_create(int numa_node) {
    size_t total_size = sizeof(spsc_ring_t);
    spsc_ring_t *ring = (spsc_ring_t*)hft_huge_page_alloc(total_size, numa_node);
    if (ring) {
        spsc_ring_init(ring);
    }
    return ring;
}

/**
 * Destroy and unmap the ring buffer.
 */
static inline void spsc_ring_destroy(spsc_ring_t *ring) {
    if (ring) {
        hft_huge_page_free(ring, sizeof(spsc_ring_t));
    }
}

/**
 * Get a pointer to the next writable slot for the producer.
 * Returns NULL if the ring is full.
 *
 * The producer should write data into the returned pointer, then call
 * spsc_ring_publish() to make it visible to the consumer.
 *
 * This two-phase commit (claim → write → publish) allows the producer to
 * write directly into the ring slot without an intermediate memcpy.
 */
static inline md_event_t* spsc_ring_claim(spsc_ring_t *ring) {
    uint64_t head = ring->head;
    uint64_t next = head + 1;

    /* Check if ring is full using cached tail (avoids cross-core read) */
    if (HFT_UNLIKELY(next - ring->cached_tail > RING_CAPACITY)) {
        /* Refresh cached tail with acquire load from consumer's cache line */
        ring->cached_tail = hft_atomic_load_acquire(&ring->tail);
        if (next - ring->cached_tail > RING_CAPACITY) {
            return NULL;  /* Ring is genuinely full */
        }
    }

    /* Pre-fetch the slot's cache line for write */
    md_event_t *slot = &ring->data[head & RING_MASK];
    HFT_PREFETCH_W(slot);

    return slot;
}

/**
 * Publish the previously claimed slot, making it visible to the consumer.
 *
 * Memory ordering: RELEASE store on head ensures all preceding writes to the
 * data slot are globally visible before the head index update.
 */
static inline void spsc_ring_publish(spsc_ring_t *ring) {
    hft_atomic_store_release(&ring->head, ring->head + 1);
}

/**
 * Batch publish: claim and write multiple events, then publish all at once
 * with a single release-store to the head index.
 *
 * This reduces cross-core cache-line invalidation traffic by amortizing
 * the release fence over multiple events.
 *
 * @param ring    The ring buffer
 * @param events  Array of events to publish
 * @param count   Number of events (must not exceed available space)
 * @return Number of events actually published (may be < count if ring is full)
 */
static inline uint32_t spsc_ring_try_publish_batch(
    spsc_ring_t *ring,
    const md_event_t *events,
    uint32_t count)
{
    uint64_t head = ring->head;

    /* Refresh cached tail to determine available space */
    ring->cached_tail = hft_atomic_load_acquire(&ring->tail);
    uint64_t available = RING_CAPACITY - (head - ring->cached_tail);

    if (available == 0) return 0;
    if (count > available) count = (uint32_t)available;

    /* Copy all events into ring slots */
    for (uint32_t i = 0; i < count; ++i) {
        uint64_t idx = (head + i) & RING_MASK;
        memcpy(&ring->data[idx], &events[i], sizeof(md_event_t));
    }

    /*
     * Single release-store publishes all events atomically from the
     * consumer's perspective. The consumer will see head advance by `count`
     * and all data slots will be fully written before this store is visible.
     */
    hft_atomic_store_release(&ring->head, head + count);

    return count;
}

/**
 * Consume a batch of events from the ring buffer.
 *
 * @param ring       The ring buffer
 * @param dst        Output array for consumed events
 * @param max_count  Maximum events to consume
 * @return Number of events consumed (0 if ring is empty)
 */
static inline uint32_t spsc_ring_consume_batch(
    spsc_ring_t *ring,
    md_event_t *dst,
    uint32_t max_count)
{
    uint64_t tail = ring->tail;

    /* Refresh cached head with acquire load from producer's cache line */
    ring->cached_head = hft_atomic_load_acquire(&ring->head);
    uint64_t available = ring->cached_head - tail;

    if (available == 0) return 0;
    if (max_count > available) max_count = (uint32_t)available;

    /* Copy events out of ring slots */
    for (uint32_t i = 0; i < max_count; ++i) {
        uint64_t idx = (tail + i) & RING_MASK;
        memcpy(&dst[i], &ring->data[idx], sizeof(md_event_t));
    }

    /* Release-store on tail signals to producer that slots are free */
    hft_atomic_store_release(&ring->tail, tail + max_count);

    return max_count;
}

/**
 * Spin-wait consumer: blocks until at least one event is available,
 * then consumes a batch.
 *
 * Uses _mm_pause() (Intel PAUSE instruction) in the spin loop to:
 *   1. Reduce power consumption during busy-wait
 *   2. Avoid memory-order machine-clear pipeline flushes on Intel CPUs
 *      (the PAUSE instruction hints to the CPU that this is a spin-wait loop,
 *       preventing speculative memory reads from causing costly pipeline flushes
 *       when the monitored variable changes)
 *   3. Yield execution resources to the other hyperthread (if HT is enabled —
 *      in production HT is disabled, but PAUSE is still beneficial for power)
 *
 * @param ring       The ring buffer
 * @param dst        Output array for consumed events
 * @param max_count  Maximum events to consume
 * @return Number of events consumed (always >= 1 when function returns)
 */
static inline uint32_t spsc_ring_consume_batch_spin(
    spsc_ring_t *ring,
    md_event_t *dst,
    uint32_t max_count)
{
    uint32_t consumed;
    while ((consumed = spsc_ring_consume_batch(ring, dst, max_count)) == 0) {
        HFT_PAUSE();
    }
    return consumed;
}

/**
 * Query the number of events currently in the ring (approximate — may be stale).
 * Useful for monitoring and telemetry; never used for correctness decisions.
 */
static inline uint64_t spsc_ring_size_approx(const spsc_ring_t *ring) {
    return ring->head - ring->tail;
}

#endif /* HFT_SPSC_RING_H */
