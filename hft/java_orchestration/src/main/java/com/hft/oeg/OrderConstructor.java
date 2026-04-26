package com.hft.oeg;

import com.hft.core.MdEvent;
import sun.misc.Unsafe;

/**
 * OrderConstructor — SBE Order Message Builder (Zero-Allocation)
 *
 * Builds Simple Binary Encoding (SBE) order frames by patching a pre-built
 * template stored in off-heap memory. Only the variable fields (price, qty,
 * orderId, timestamp) are written — the static header, instrument ID, and
 * side are pre-populated at initialization.
 *
 * <p><b>SBE Frame Layout (48 bytes):</b></p>
 * <pre>
 *   Offset  Size  Field              Notes
 *   0       2     MessageLength      48 (little-endian)
 *   2       2     TemplateId         0x0001 = NewOrderSingle
 *   4       2     SchemaId           Exchange-assigned
 *   6       2     Version            SBE schema version
 *   8       8     ClOrdId            Client order ID (patched)
 *   16      4     InstrumentId       Static per template
 *   20      8     Price              Fixed-point 8dp (patched)
 *   28      4     Quantity           Shares (patched)
 *   32      1     Side               '1' = Buy, '2' = Sell
 *   33      1     OrderType          '2' = Limit
 *   34      1     TimeInForce        '0' = Day, '3' = IOC
 *   35      1     Padding
 *   36      8     TransactTime       Nanosecond timestamp (patched)
 *   44      4     SequenceNumber     Session sequence (patched)
 * </pre>
 *
 * <p><b>Zero-Allocation Path:</b></p>
 * The template is stored in off-heap memory allocated once at startup.
 * Patching uses {@code Unsafe.putLong/putInt} — no byte[] allocation,
 * no ByteBuffer, no Object creation.
 */
public final class OrderConstructor {

    private static final Unsafe UNSAFE = MdEvent.UNSAFE;

    public static final int FRAME_SIZE = 48;

    /* SBE field offsets */
    private static final int OFF_MSG_LEN      = 0;
    private static final int OFF_TEMPLATE_ID   = 2;
    private static final int OFF_SCHEMA_ID     = 4;
    private static final int OFF_VERSION       = 6;
    private static final int OFF_CLORDID       = 8;
    private static final int OFF_INSTRUMENT_ID = 16;
    private static final int OFF_PRICE         = 20;
    private static final int OFF_QUANTITY      = 28;
    private static final int OFF_SIDE          = 32;
    private static final int OFF_ORDER_TYPE    = 33;
    private static final int OFF_TIF           = 34;
    private static final int OFF_TRANSACT_TIME = 36;
    private static final int OFF_SEQ_NO        = 44;

    /** Off-heap base address of the template frame. */
    private final long templateBase;

    /** Off-heap base address of the working frame (patched per order). */
    private final long workingBase;

    /** Monotonic client order ID generator. */
    private long nextClOrdId;

    /** Session sequence number. */
    private int sequenceNumber;

    /**
     * @param instrumentId Exchange instrument ID
     * @param side         '1' = Buy, '2' = Sell
     * @param schemaId     Exchange SBE schema ID
     */
    public OrderConstructor(final int instrumentId, final byte side, final short schemaId) {
        /* Allocate off-heap: template + working frame */
        templateBase = UNSAFE.allocateMemory(FRAME_SIZE);
        workingBase = UNSAFE.allocateMemory(FRAME_SIZE);
        UNSAFE.setMemory(templateBase, FRAME_SIZE, (byte) 0);

        /* Populate template with static fields */
        UNSAFE.putShort(templateBase + OFF_MSG_LEN, (short) FRAME_SIZE);
        UNSAFE.putShort(templateBase + OFF_TEMPLATE_ID, (short) 0x0001);
        UNSAFE.putShort(templateBase + OFF_SCHEMA_ID, schemaId);
        UNSAFE.putShort(templateBase + OFF_VERSION, (short) 1);
        UNSAFE.putInt(templateBase + OFF_INSTRUMENT_ID, instrumentId);
        UNSAFE.putByte(templateBase + OFF_SIDE, side);
        UNSAFE.putByte(templateBase + OFF_ORDER_TYPE, (byte) '2');  /* Limit */
        UNSAFE.putByte(templateBase + OFF_TIF, (byte) '0');         /* Day */

        this.nextClOrdId = System.nanoTime();  /* Seed with current time */
        this.sequenceNumber = 1;
    }

    /**
     * Build an order frame by patching the template.
     *
     * <p><b>Critical Path — Target ≤ 40ns:</b></p>
     * <ol>
     *   <li>Copy template to working buffer (48 bytes = 6 × 8-byte writes)</li>
     *   <li>Patch 4 variable fields via Unsafe.putLong/putInt</li>
     *   <li>Return the working buffer's off-heap address</li>
     * </ol>
     *
     * @param price    Order price (fixed-point 8dp)
     * @param quantity Order quantity in shares
     * @return Off-heap address of the completed SBE frame (valid until next call)
     */
    public final long buildOrder(final long price, final int quantity) {
        /* Step 1: Copy template (48 bytes) */
        UNSAFE.copyMemory(templateBase, workingBase, FRAME_SIZE);

        /* Step 2: Patch variable fields */
        long clOrdId = nextClOrdId++;
        UNSAFE.putLong(workingBase + OFF_CLORDID, clOrdId);
        UNSAFE.putLong(workingBase + OFF_PRICE, price);
        UNSAFE.putInt(workingBase + OFF_QUANTITY, quantity);
        UNSAFE.putLong(workingBase + OFF_TRANSACT_TIME, System.nanoTime());
        UNSAFE.putInt(workingBase + OFF_SEQ_NO, sequenceNumber++);

        return workingBase;
    }

    /**
     * Build an IOC (Immediate-Or-Cancel) order.
     */
    public final long buildIOCOrder(final long price, final int quantity) {
        long addr = buildOrder(price, quantity);
        UNSAFE.putByte(addr + OFF_TIF, (byte) '3');  /* IOC */
        return addr;
    }

    /** Get the frame size for transmission. */
    public static int getFrameSize() { return FRAME_SIZE; }

    /** Get the last generated client order ID. */
    public long getLastClOrdId() { return nextClOrdId - 1; }

    /** Release off-heap memory. */
    public void destroy() {
        UNSAFE.freeMemory(templateBase);
        UNSAFE.freeMemory(workingBase);
    }
}
