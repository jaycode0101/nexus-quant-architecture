package com.hft.core;

import sun.misc.Unsafe;

/**
 * SharedMemoryBridge — C→Java Boundary via Memory-Mapped Shared Region
 *
 * Reads MdEvent structs from the C-side SPSC ring buffer that lives in
 * a shared mmap region. The Java consumer uses {@link Unsafe} to read
 * the ring's head index with acquire semantics and access event data
 * at known offsets.
 *
 * <p><b>Memory Layout of SPSC Ring (set by C side):</b></p>
 * <pre>
 *   Offset 0:    head   (uint64 — producer writes, consumer reads with acquire)
 *   Offset 8:    cached_tail (producer-private — Java ignores)
 *   Offset 16-63: padding (cache line 0)
 *   Offset 64:   tail   (uint64 — consumer writes with release, producer reads)
 *   Offset 72:   cached_head (consumer-private)
 *   Offset 80-127: padding (cache line 1)
 *   Offset 128:  data[0] (64 bytes per MdEvent)
 *   Offset 192:  data[1]
 *   ...
 * </pre>
 *
 * <p><b>Acquire/Release Protocol:</b></p>
 * <ul>
 *   <li>Consumer reads head via {@code Unsafe.getLongVolatile()} (acquire semantics)</li>
 *   <li>Consumer reads event data via {@code Unsafe.getLong()} (plain — ordering
 *       guaranteed by the acquire load on head)</li>
 *   <li>Consumer writes tail via {@code Unsafe.putLongVolatile()} (release semantics)</li>
 * </ul>
 */
public final class SharedMemoryBridge {

    private static final Unsafe UNSAFE = MdEvent.UNSAFE;

    /* Ring control field offsets — must match C spsc_ring_t layout */
    private static final long HEAD_OFFSET = 0L;
    private static final long TAIL_OFFSET = 64L;
    private static final long DATA_OFFSET = 128L;

    /** Ring capacity — must match C RING_CAPACITY (power of 2). */
    private final int ringCapacity;
    private final int ringMask;

    /** Base address of the shared mmap region. */
    private final long baseAddress;

    /** Consumer's local copy of tail — only this thread writes tail. */
    private long localTail;

    /** Consumer's cached copy of head — reduces cross-core reads. */
    private long cachedHead;

    /**
     * @param baseAddress  Base address of the shared mmap region (from JNI or FileChannel.map)
     * @param ringCapacity Number of slots (must match C RING_CAPACITY, power of 2)
     */
    public SharedMemoryBridge(final long baseAddress, final int ringCapacity) {
        if ((ringCapacity & (ringCapacity - 1)) != 0) {
            throw new IllegalArgumentException("ringCapacity must be power of 2");
        }
        this.baseAddress = baseAddress;
        this.ringCapacity = ringCapacity;
        this.ringMask = ringCapacity - 1;
        this.localTail = 0L;
        this.cachedHead = 0L;
    }

    /**
     * Poll for available events from the C producer.
     *
     * @return Number of events available for reading (0 if ring is empty)
     */
    public final int available() {
        cachedHead = UNSAFE.getLongVolatile(null, baseAddress + HEAD_OFFSET);
        return (int) (cachedHead - localTail);
    }

    /**
     * Get the off-heap address of the event at the given ring index.
     * The caller uses this address with MdEvent.wrap() or MdEvent.copyFrom().
     *
     * @param index Absolute sequence index (will be masked internally)
     * @return Off-heap address of the event's 64-byte slot
     */
    public final long eventAddress(final long index) {
        return baseAddress + DATA_OFFSET + ((index & ringMask) * (long) MdEvent.EVENT_SIZE);
    }

    /**
     * Read the next available event's base address.
     * Returns 0 if no event is available.
     */
    public final long pollNextEventAddress() {
        if (localTail >= cachedHead) {
            cachedHead = UNSAFE.getLongVolatile(null, baseAddress + HEAD_OFFSET);
            if (localTail >= cachedHead) {
                return 0L;
            }
        }
        return eventAddress(localTail);
    }

    /**
     * Commit the consumption of one event by advancing the tail.
     * Must be called after processing the event returned by pollNextEventAddress().
     */
    public final void commitOne() {
        localTail++;
        UNSAFE.putLongVolatile(null, baseAddress + TAIL_OFFSET, localTail);
    }

    /**
     * Commit the consumption of a batch of events.
     * Single release-store to tail — reduces cross-core traffic.
     */
    public final void commitBatch(final int count) {
        localTail += count;
        UNSAFE.putLongVolatile(null, baseAddress + TAIL_OFFSET, localTail);
    }

    /** Current consumer position. */
    public final long getTail() {
        return localTail;
    }

    /** Last known producer position. */
    public final long getCachedHead() {
        return cachedHead;
    }
}
