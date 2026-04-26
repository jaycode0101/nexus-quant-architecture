package com.hft.core;

import sun.misc.Unsafe;
import java.lang.reflect.Field;

/**
 * MdEvent — Off-Heap Flyweight Market Data Event
 *
 * Zero-allocation value object pattern: this Java object is a thin wrapper
 * holding a single {@code long baseAddress} pointing to off-heap memory.
 * All fields are accessed via {@link sun.misc.Unsafe} with compile-time
 * constant offsets — no heap allocation, no field boxing, no GC pressure.
 *
 * The off-heap layout matches the C {@code md_event_t} struct exactly:
 *
 * <pre>
 *   Offset  Size  Field            Java Type
 *   0       1     messageType      byte
 *   1       1     side             byte
 *   2-3     2     (padding)
 *   4       4     instrumentId     int
 *   8       8     orderId          long
 *   16      8     price            long (fixed-point, 8 decimals)
 *   24      4     quantity         int
 *   28      4     (padding)
 *   32      8     timestampNs      long (nanoseconds since midnight)
 *   40      8     sequenceNo       long
 *   48      4     execShares       int
 *   52      8     matchNumber      long
 *   60      4     (padding)
 *   Total:  64 bytes (one cache line)
 * </pre>
 *
 * <p><b>Thread safety:</b> This object is NOT thread-safe. Each Disruptor
 * consumer owns its own MdEvent reference and accesses it sequentially.
 * The Disruptor sequence barrier provides the happens-before guarantee
 * between the producer's write and the consumer's read.</p>
 *
 * <p><b>JIT optimization:</b> All methods are {@code final} to ensure
 * monomorphic call sites. The Unsafe.getLong/putLong calls are intrinsified
 * by HotSpot C2 to direct memory loads/stores — no method call overhead.</p>
 */
public final class MdEvent {

    /* --- Unsafe Instance --- */

    static final Unsafe UNSAFE;
    static {
        try {
            Field f = Unsafe.class.getDeclaredField("theUnsafe");
            f.setAccessible(true);
            UNSAFE = (Unsafe) f.get(null);
        } catch (Exception e) {
            throw new ExceptionInInitializerError("Failed to obtain Unsafe instance");
        }
    }

    /* --- Field Offsets (must match C md_event_t layout) --- */

    public static final int OFFSET_MESSAGE_TYPE  = 0;
    public static final int OFFSET_SIDE          = 1;
    public static final int OFFSET_INSTRUMENT_ID = 4;
    public static final int OFFSET_ORDER_ID      = 8;
    public static final int OFFSET_PRICE         = 16;
    public static final int OFFSET_QUANTITY      = 24;
    public static final int OFFSET_TIMESTAMP_NS  = 32;
    public static final int OFFSET_SEQUENCE_NO   = 40;
    public static final int OFFSET_EXEC_SHARES   = 48;
    public static final int OFFSET_MATCH_NUMBER  = 52;

    /** Total size of one event in off-heap memory. */
    public static final int EVENT_SIZE = 64;

    /** Fixed-point price scale factor: price / PRICE_SCALE = actual price. */
    public static final long PRICE_SCALE = 100_000_000L;

    /* --- Message Type Constants --- */

    public static final byte MSG_ADD_ORDER     = (byte) 'A';
    public static final byte MSG_EXECUTE_ORDER = (byte) 'E';
    public static final byte MSG_CANCEL_ORDER  = (byte) 'X';
    public static final byte MSG_DELETE_ORDER  = (byte) 'D';
    public static final byte MSG_REPLACE_ORDER = (byte) 'U';
    public static final byte MSG_TRADE         = (byte) 'P';

    public static final byte SIDE_BUY  = (byte) 'B';
    public static final byte SIDE_SELL = (byte) 'S';

    /* --- Instance State --- */

    /**
     * Base address of this event's 64-byte slot in off-heap memory.
     * Set by the Disruptor event factory or translator — never changes
     * during the event's lifecycle within a ring buffer slot.
     */
    private long baseAddress;

    /* --- Construction --- */

    public MdEvent() {
        this.baseAddress = 0L;
    }

    /** Point this flyweight at a specific off-heap address. */
    public final void wrap(final long address) {
        this.baseAddress = address;
    }

    /** Get the current base address. */
    public final long getBaseAddress() {
        return baseAddress;
    }

    /* --- Field Accessors (all final for monomorphic JIT) --- */

    public final byte getMessageType() {
        return UNSAFE.getByte(baseAddress + OFFSET_MESSAGE_TYPE);
    }

    public final void setMessageType(final byte type) {
        UNSAFE.putByte(baseAddress + OFFSET_MESSAGE_TYPE, type);
    }

    public final byte getSide() {
        return UNSAFE.getByte(baseAddress + OFFSET_SIDE);
    }

    public final void setSide(final byte side) {
        UNSAFE.putByte(baseAddress + OFFSET_SIDE, side);
    }

    public final int getInstrumentId() {
        return UNSAFE.getInt(baseAddress + OFFSET_INSTRUMENT_ID);
    }

    public final void setInstrumentId(final int id) {
        UNSAFE.putInt(baseAddress + OFFSET_INSTRUMENT_ID, id);
    }

    public final long getOrderId() {
        return UNSAFE.getLong(baseAddress + OFFSET_ORDER_ID);
    }

    public final void setOrderId(final long orderId) {
        UNSAFE.putLong(baseAddress + OFFSET_ORDER_ID, orderId);
    }

    /**
     * Get the price in fixed-point representation (8 decimal places).
     * To convert to double (NEVER in hot path): {@code getPrice() / (double) PRICE_SCALE}
     */
    public final long getPrice() {
        return UNSAFE.getLong(baseAddress + OFFSET_PRICE);
    }

    public final void setPrice(final long price) {
        UNSAFE.putLong(baseAddress + OFFSET_PRICE, price);
    }

    public final int getQuantity() {
        return UNSAFE.getInt(baseAddress + OFFSET_QUANTITY);
    }

    public final void setQuantity(final int qty) {
        UNSAFE.putInt(baseAddress + OFFSET_QUANTITY, qty);
    }

    public final long getTimestampNs() {
        return UNSAFE.getLong(baseAddress + OFFSET_TIMESTAMP_NS);
    }

    public final void setTimestampNs(final long ts) {
        UNSAFE.putLong(baseAddress + OFFSET_TIMESTAMP_NS, ts);
    }

    public final long getSequenceNo() {
        return UNSAFE.getLong(baseAddress + OFFSET_SEQUENCE_NO);
    }

    public final void setSequenceNo(final long seq) {
        UNSAFE.putLong(baseAddress + OFFSET_SEQUENCE_NO, seq);
    }

    public final int getExecShares() {
        return UNSAFE.getInt(baseAddress + OFFSET_EXEC_SHARES);
    }

    public final void setExecShares(final int shares) {
        UNSAFE.putInt(baseAddress + OFFSET_EXEC_SHARES, shares);
    }

    public final long getMatchNumber() {
        return UNSAFE.getLong(baseAddress + OFFSET_MATCH_NUMBER);
    }

    public final void setMatchNumber(final long matchNo) {
        UNSAFE.putLong(baseAddress + OFFSET_MATCH_NUMBER, matchNo);
    }

    /* --- Convenience (NOT for hot path) --- */

    public final double getPriceAsDouble() {
        return (double) getPrice() / (double) PRICE_SCALE;
    }

    public final boolean isBuy() {
        return getSide() == SIDE_BUY;
    }

    public final boolean isTrade() {
        return getMessageType() == MSG_TRADE;
    }

    /**
     * Copy all 64 bytes from another off-heap address into this event's slot.
     * Used by the Disruptor translator to copy from the shared mmap region.
     */
    public final void copyFrom(final long sourceAddress) {
        UNSAFE.copyMemory(sourceAddress, baseAddress, EVENT_SIZE);
    }

    @Override
    public String toString() {
        return String.format("MdEvent[type=%c, instr=%d, oid=%d, price=%.4f, qty=%d, side=%c]",
                (char) getMessageType(), getInstrumentId(), getOrderId(),
                getPriceAsDouble(), getQuantity(), (char) getSide());
    }
}
