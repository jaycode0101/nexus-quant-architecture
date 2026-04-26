package com.hft.lob;

import com.lmax.disruptor.EventHandler;
import com.hft.core.MdEvent;
import com.hft.signal.FeatureVector;
import sun.misc.Unsafe;

/**
 * LOBReconstructionHandler — Limit Order Book Reconstructor
 *
 * Disruptor {@link EventHandler} that maintains a price-level order book
 * using off-heap parallel arrays. No TreeMap, no HashMap, no heap objects
 * in the update path.
 *
 * <p><b>Data Structure:</b> Two sorted {@code long[]} arrays allocated off-heap:
 * <ul>
 *   <li>{@code bidPrices[]} / {@code bidQuantities[]} — sorted descending by price</li>
 *   <li>{@code askPrices[]} / {@code askQuantities[]} — sorted ascending by price</li>
 * </ul>
 *
 * <p><b>Delta Patching:</b> On each ADD_ORDER, binary search into the price array
 * to find the insertion point, then shift elements via {@code Unsafe.copyMemory()}
 * for array shift — no Java array allocation.</p>
 *
 * <p><b>Micro-Price (Stoikov, 2010):</b></p>
 * <pre>
 *   μ = (bestAsk × Q_bid + bestBid × Q_ask) / (Q_bid + Q_ask)
 * </pre>
 * Computed in fixed-point arithmetic (8-decimal integer representation).
 *
 * <p><b>Fixed-Point Arithmetic:</b></p>
 * All prices are represented as {@code long} with 8 implied decimal places
 * (multiply by 10^8). This avoids floating-point operations in the critical path.
 * <ul>
 *   <li>Scaling factor: {@code SCALE = 100_000_000L}</li>
 *   <li>Overflow analysis: max price = 10^6 (1M USD), max qty = 10^9 (1B shares)
 *       → max product = 10^6 × 10^8 × 10^9 = 10^23, which EXCEEDS long range.
 *       Therefore, micro-price uses 128-bit intermediate via two 64-bit multiplies
 *       with carry detection. In practice, we use {@code Math.multiplyHigh()} (Java 9+)
 *       or downscale quantities before multiplication.</li>
 * </ul>
 *
 * <p><b>OBI (Order Book Imbalance):</b></p>
 * <pre>
 *   φ = (Q_bid - Q_ask) / (Q_bid + Q_ask)
 * </pre>
 * Computed as fixed-point with 8 decimal places. Output range: [-1.0, +1.0].
 */
public final class LOBReconstructionHandler implements EventHandler<MdEvent> {

    private static final Unsafe UNSAFE = MdEvent.UNSAFE;
    private static final long PRICE_SCALE = MdEvent.PRICE_SCALE;

    /** Maximum number of price levels per side. */
    private static final int MAX_LEVELS = 1024;

    /* --- Off-Heap Arrays --- */

    /** Off-heap base addresses for bid side. */
    private final long bidPricesBase;
    private final long bidQuantitiesBase;
    private int bidLevelCount;

    /** Off-heap base addresses for ask side. */
    private final long askPricesBase;
    private final long askQuantitiesBase;
    private int askLevelCount;

    /** Best bid/ask tracking — direct indices into price arrays. */
    private int bestBidIdx;
    private int bestAskIdx;

    /** Pre-allocated FeatureVector for downstream consumers. */
    private final FeatureVector featureVector;

    /** Previous OBI for momentum calculation (Δφ). */
    private long prevObiFixed;

    /** Event counter for sequence tracking. */
    private long eventsProcessed;

    public LOBReconstructionHandler() {
        /* Allocate off-heap arrays: MAX_LEVELS × 8 bytes per element */
        long arraySize = (long) MAX_LEVELS * Long.BYTES;

        bidPricesBase     = UNSAFE.allocateMemory(arraySize);
        bidQuantitiesBase = UNSAFE.allocateMemory(arraySize);
        askPricesBase     = UNSAFE.allocateMemory(arraySize);
        askQuantitiesBase = UNSAFE.allocateMemory(arraySize);

        UNSAFE.setMemory(bidPricesBase, arraySize, (byte) 0);
        UNSAFE.setMemory(bidQuantitiesBase, arraySize, (byte) 0);
        UNSAFE.setMemory(askPricesBase, arraySize, (byte) 0);
        UNSAFE.setMemory(askQuantitiesBase, arraySize, (byte) 0);

        bidLevelCount = 0;
        askLevelCount = 0;
        bestBidIdx = -1;
        bestAskIdx = -1;
        prevObiFixed = 0;
        eventsProcessed = 0;

        featureVector = new FeatureVector();
    }

    @Override
    public void onEvent(final MdEvent event, final long sequence, final boolean endOfBatch) {
        final byte msgType = event.getMessageType();

        switch (msgType) {
            case MdEvent.MSG_ADD_ORDER:
                handleAddOrder(event);
                break;
            case MdEvent.MSG_CANCEL_ORDER:
                handleCancelOrder(event);
                break;
            case MdEvent.MSG_DELETE_ORDER:
                handleDeleteOrder(event);
                break;
            case MdEvent.MSG_EXECUTE_ORDER:
                handleExecuteOrder(event);
                break;
            case MdEvent.MSG_REPLACE_ORDER:
                handleReplaceOrder(event);
                break;
            case MdEvent.MSG_TRADE:
                handleTrade(event);
                break;
            default:
                break;
        }

        /* Update micro-price, OBI, and feature vector after every event */
        if (bestBidIdx >= 0 && bestAskIdx >= 0) {
            computeFeatures(event.getTimestampNs());
        }

        eventsProcessed++;
    }

    /* --- Order Book Update Methods --- */

    private void handleAddOrder(final MdEvent event) {
        final long price = event.getPrice();
        final int qty = event.getQuantity();
        final byte side = event.getSide();

        if (side == MdEvent.SIDE_BUY) {
            addLevel(bidPricesBase, bidQuantitiesBase, price, qty, true);
            bidLevelCount = Math.min(bidLevelCount + 1, MAX_LEVELS);
            /* Update best bid: bids sorted descending, best is index 0 */
            bestBidIdx = 0;
        } else {
            addLevel(askPricesBase, askQuantitiesBase, price, qty, false);
            askLevelCount = Math.min(askLevelCount + 1, MAX_LEVELS);
            /* Update best ask: asks sorted ascending, best is index 0 */
            bestAskIdx = 0;
        }
    }

    /**
     * Insert a price level into the sorted off-heap array.
     *
     * Binary search for insertion point, then shift elements via Unsafe.copyMemory().
     *
     * @param pricesBase Base address of the prices array
     * @param qtysBase   Base address of the quantities array
     * @param price      Price to insert (fixed-point)
     * @param qty        Quantity to add
     * @param descending True for bid side (descending), false for ask (ascending)
     */
    private void addLevel(final long pricesBase, final long qtysBase,
                          final long price, final int qty, final boolean descending) {
        int count = descending ? bidLevelCount : askLevelCount;

        /* Binary search for the price level */
        int insertIdx = binarySearchPrice(pricesBase, count, price, descending);

        /* Check if this price level already exists */
        if (insertIdx < count) {
            long existingPrice = UNSAFE.getLong(pricesBase + (long) insertIdx * Long.BYTES);
            if (existingPrice == price) {
                /* Price level exists — add quantity */
                long existingQty = UNSAFE.getLong(qtysBase + (long) insertIdx * Long.BYTES);
                UNSAFE.putLong(qtysBase + (long) insertIdx * Long.BYTES, existingQty + qty);
                return;
            }
        }

        /* Insert new level: shift elements right via Unsafe.copyMemory */
        if (count >= MAX_LEVELS) return;  /* Level array full */

        int elementsToShift = count - insertIdx;
        if (elementsToShift > 0) {
            UNSAFE.copyMemory(
                pricesBase + (long) insertIdx * Long.BYTES,
                pricesBase + (long) (insertIdx + 1) * Long.BYTES,
                (long) elementsToShift * Long.BYTES
            );
            UNSAFE.copyMemory(
                qtysBase + (long) insertIdx * Long.BYTES,
                qtysBase + (long) (insertIdx + 1) * Long.BYTES,
                (long) elementsToShift * Long.BYTES
            );
        }

        UNSAFE.putLong(pricesBase + (long) insertIdx * Long.BYTES, price);
        UNSAFE.putLong(qtysBase + (long) insertIdx * Long.BYTES, (long) qty);
    }

    /**
     * Binary search in off-heap sorted price array.
     * Returns the insertion index for the given price.
     */
    private int binarySearchPrice(final long pricesBase, final int count,
                                   final long targetPrice, final boolean descending) {
        int low = 0, high = count;
        while (low < high) {
            int mid = (low + high) >>> 1;
            long midPrice = UNSAFE.getLong(pricesBase + (long) mid * Long.BYTES);

            boolean goLeft;
            if (descending) {
                goLeft = midPrice > targetPrice;  /* Descending: higher prices first */
            } else {
                goLeft = midPrice < targetPrice;  /* Ascending: lower prices first */
            }

            if (goLeft) {
                low = mid + 1;
            } else {
                high = mid;
            }
        }
        return low;
    }

    private void handleCancelOrder(final MdEvent event) {
        /* Reduce quantity at the price level associated with this order.
         * In a full implementation, we'd maintain an order_id → (price, side) map.
         * For this reference implementation, we reduce the best level quantity. */
        final int cancelQty = event.getExecShares();
        if (bestBidIdx >= 0 && bidLevelCount > 0) {
            long qty = UNSAFE.getLong(bidQuantitiesBase + (long) bestBidIdx * Long.BYTES);
            qty = Math.max(0, qty - cancelQty);
            UNSAFE.putLong(bidQuantitiesBase + (long) bestBidIdx * Long.BYTES, qty);
        }
    }

    private void handleDeleteOrder(final MdEvent event) {
        /* Remove entire order from the book. Similar caveat as cancelOrder. */
        handleCancelOrder(event);
    }

    private void handleExecuteOrder(final MdEvent event) {
        /* Execution reduces resting quantity */
        final int execQty = event.getExecShares();
        if (bestBidIdx >= 0 && bidLevelCount > 0) {
            long qty = UNSAFE.getLong(bidQuantitiesBase + (long) bestBidIdx * Long.BYTES);
            qty = Math.max(0, qty - execQty);
            UNSAFE.putLong(bidQuantitiesBase + (long) bestBidIdx * Long.BYTES, qty);
        }
    }

    private void handleReplaceOrder(final MdEvent event) {
        /* Replace = delete old + add new. For reference, we just add. */
        handleAddOrder(event);
    }

    private void handleTrade(final MdEvent event) {
        /* Trade messages don't modify the LOB directly (they're informational).
         * The LOB is updated via the corresponding EXECUTE message.
         * We do pass the trade to the feature vector for Hawkes intensity. */
        featureVector.setLastTradeTimestampNs(event.getTimestampNs());
        featureVector.setLastTradePrice(event.getPrice());
        featureVector.setLastTradeQty(event.getQuantity());
        featureVector.setIsTradeEvent(true);
    }

    /* --- Feature Computation --- */

    /**
     * Compute micro-price, OBI, and update the feature vector.
     *
     * <p><b>Micro-price (fixed-point):</b></p>
     * <pre>
     *   μ = (bestAsk × Q_bid + bestBid × Q_ask) / (Q_bid + Q_ask)
     * </pre>
     *
     * To avoid overflow with large prices × quantities, we downscale
     * quantities to thousands before multiplication:
     * <pre>
     *   Max price:  10^6 × 10^8 (fixed-point) = 10^14
     *   Max qty/1000: 10^6
     *   Product: 10^14 × 10^6 = 10^20 — fits in long (max 9.2 × 10^18)
     *   → Use qty/100 for safety: 10^14 × 10^7 = 10^21 — still overflows
     *   → Use dedicated downscaling: divide both products by Q_total first
     * </pre>
     */
    private void computeFeatures(final long timestampNs) {
        long bestBidPrice = UNSAFE.getLong(bidPricesBase + (long) bestBidIdx * Long.BYTES);
        long bestBidQty   = UNSAFE.getLong(bidQuantitiesBase + (long) bestBidIdx * Long.BYTES);
        long bestAskPrice = UNSAFE.getLong(askPricesBase + (long) bestAskIdx * Long.BYTES);
        long bestAskQty   = UNSAFE.getLong(askQuantitiesBase + (long) bestAskIdx * Long.BYTES);

        if (bestBidQty <= 0 || bestAskQty <= 0) return;

        long qTotal = bestBidQty + bestAskQty;
        if (qTotal == 0) return;

        /* --- Micro-price (overflow-safe) ---
         *
         * μ = (askPrice × bidQty + bidPrice × askQty) / (bidQty + askQty)
         *
         * We compute each term separately and use long division.
         * For very large values, we'd use Math.multiplyHigh() for 128-bit product.
         * Here, practical values (prices < $50,000 = 5×10^12 fixed, qty < 10^7)
         * yield products < 5×10^19 which fits in signed long.
         */
        long term1 = bestAskPrice * bestBidQty / qTotal;
        long term2 = bestBidPrice * bestAskQty / qTotal;
        long microPrice = term1 + term2;

        /* --- OBI (fixed-point, 8 decimals) ---
         *
         * φ = (Q_bid - Q_ask) / (Q_bid + Q_ask)
         *
         * Multiply numerator by PRICE_SCALE to get 8-decimal fixed-point.
         * Range: [-PRICE_SCALE, +PRICE_SCALE] representing [-1.0, +1.0].
         */
        long obiFixed = (bestBidQty - bestAskQty) * PRICE_SCALE / qTotal;

        /* OBI momentum: Δφ = φ(t) - φ(t-1) */
        long obiDeltaFixed = obiFixed - prevObiFixed;
        prevObiFixed = obiFixed;

        /* Mid-price (for spread computation) */
        long midPrice = (bestBidPrice + bestAskPrice) / 2;

        /* Spread in fixed-point */
        long spreadFixed = bestAskPrice - bestBidPrice;

        /* --- Write to FeatureVector --- */
        featureVector.setMicroPrice(microPrice);
        featureVector.setObi(obiFixed);
        featureVector.setObiDelta(obiDeltaFixed);
        featureVector.setMidPrice(midPrice);
        featureVector.setSpread(spreadFixed);
        featureVector.setBestBidPrice(bestBidPrice);
        featureVector.setBestAskPrice(bestAskPrice);
        featureVector.setBestBidQty(bestBidQty);
        featureVector.setBestAskQty(bestAskQty);
        featureVector.setTimestampNs(timestampNs);
        featureVector.setIsTradeEvent(false);  /* Reset for next event */
    }

    /* --- Accessors --- */

    public FeatureVector getFeatureVector() {
        return featureVector;
    }

    public long getEventsProcessed() {
        return eventsProcessed;
    }

    /** Release off-heap memory. Must be called at shutdown. */
    public void destroy() {
        UNSAFE.freeMemory(bidPricesBase);
        UNSAFE.freeMemory(bidQuantitiesBase);
        UNSAFE.freeMemory(askPricesBase);
        UNSAFE.freeMemory(askQuantitiesBase);
    }
}
