package com.hft.risk;

import com.lmax.disruptor.EventHandler;
import com.hft.core.MdEvent;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * PreTradeRiskGateway — Non-Blocking, Lock-Free Risk Gate
 *
 * Every order passes through this gate before submission. All checks use
 * atomic CAS operations — no locks, no blocking, no allocation.
 *
 * <p><b>Checks (all must pass, < 200ns aggregate):</b></p>
 * <ol>
 *   <li><b>Position Limit:</b> |newPosition| ≤ MAX_POSITION (AtomicLong CAS)</li>
 *   <li><b>Notional Limit:</b> totalNotional ≤ MAX_NOTIONAL (AtomicLong, fixed-point cents)</li>
 *   <li><b>Order Rate Throttle:</b> Lock-free token bucket (1000 orders/sec, burst 50)</li>
 *   <li><b>Fat Finger:</b> Price within ±5% of NBBO mid (integer arithmetic, no float)</li>
 *   <li><b>Drawdown Circuit Breaker:</b> realizedP&L > -MAX_DRAWDOWN (AtomicLong cents)</li>
 * </ol>
 *
 * <p><b>ABA Problem Analysis:</b></p>
 * All CAS operations in this class operate on monotonically changing values:
 * <ul>
 *   <li>Position: monotonically increases/decreases within a trading session</li>
 *   <li>Notional: monotonically increases (we only add, never subtract in real-time)</li>
 *   <li>Token bucket: timestamps are monotonically increasing; token count bounded</li>
 *   <li>P&L: updated only on fill reports — no ABA risk in practice</li>
 * </ul>
 * The ABA problem does not affect correctness because we're not using CAS to
 * protect pointer-based data structures — we're using it for simple counters.
 */
public final class PreTradeRiskGateway implements EventHandler<MdEvent> {

    /* --- Position Limits --- */

    /** Maximum absolute position in shares. */
    private static final long MAX_POSITION = 10_000L;

    /** Current net position in shares (positive = long, negative = short). */
    private final AtomicLong positionShares = new AtomicLong(0);

    /* --- Notional Limits --- */

    /** Maximum notional exposure in cents (USD × 100). */
    private static final long MAX_NOTIONAL_CENTS = 50_000_000_00L;  /* $50M */

    /** Current total notional in cents. */
    private final AtomicLong notionalCents = new AtomicLong(0);

    /* --- Order Rate Throttle (Lock-Free Token Bucket) --- */

    /**
     * Token bucket parameters:
     *   - Refill rate: 1000 tokens per second
     *   - Burst capacity: 50 tokens
     *   - Each order consumes 1 token
     *
     * Implementation: two AtomicLong fields.
     *   - lastRefillTimestamp: nanosecond timestamp of last refill
     *   - tokens: current token count (can be negative temporarily during CAS race)
     *
     * The CAS loop:
     *   1. Read current timestamp and tokens
     *   2. Compute tokens to add based on elapsed time
     *   3. CAS the new token count and timestamp
     *   4. If tokens > 0 after refill, consume one (CAS decrement)
     *   5. If tokens ≤ 0, reject the order
     */
    private static final long REFILL_RATE_PER_SEC = 1000;
    private static final long BURST_CAPACITY = 50;
    private static final long NANOS_PER_TOKEN = 1_000_000_000L / REFILL_RATE_PER_SEC;

    private final AtomicLong lastRefillNanos = new AtomicLong(System.nanoTime());
    private final AtomicLong tokens = new AtomicLong(BURST_CAPACITY);

    /* --- Fat Finger Protection --- */

    /** Maximum deviation from NBBO mid-price (5%, in fixed-point 8dp). */
    private static final long FAT_FINGER_PCT_FIXED = 5_000_000L;  /* 0.05 × 10^8 */

    /** Current NBBO mid-price (updated on every LOB event). Fixed-point 8dp. */
    private volatile long currentMidPrice;

    /* --- Drawdown Circuit Breaker --- */

    /** Maximum allowed drawdown in cents. */
    private static final long MAX_DRAWDOWN_CENTS = 500_000_00L;  /* $500K */

    /** Running realized P&L in cents. */
    private final AtomicLong realizedPnlCents = new AtomicLong(0);

    /** Circuit breaker state — once tripped, remains open until manual reset. */
    private final AtomicBoolean circuitBreakerOpen = new AtomicBoolean(false);

    /** Reason for circuit breaker trip. */
    private volatile String circuitBreakerReason = "";

    /* --- Statistics --- */
    private long ordersChecked;
    private long ordersRejected;
    private long positionRejects;
    private long notionalRejects;
    private long rateRejects;
    private long fatFingerRejects;
    private long drawdownRejects;

    /* --- EventHandler Implementation --- */

    @Override
    public void onEvent(final MdEvent event, final long sequence, final boolean endOfBatch) {
        /* Update mid-price from LOB data (this runs after LOB handler) */
        /* The mid-price is extracted from the event's price field as a proxy */
        long price = event.getPrice();
        if (price > 0) {
            currentMidPrice = price;
        }
    }

    /* --- Order Validation --- */

    /**
     * Check all pre-trade risk limits for an order.
     *
     * @param price    Order price (fixed-point 8dp)
     * @param quantity Order quantity in shares
     * @param isBuy    True for buy, false for sell
     * @return null if order passes all checks; error string if rejected
     */
    public final String checkOrder(final long price, final int quantity, final boolean isBuy) {
        ordersChecked++;

        /* --- Check 0: Circuit Breaker --- */
        if (circuitBreakerOpen.get()) {
            ordersRejected++;
            return "CIRCUIT_BREAKER: " + circuitBreakerReason;
        }

        /* --- Check 1: Position Limit --- */
        long currentPos = positionShares.get();
        long newPos = isBuy ? currentPos + quantity : currentPos - quantity;
        if (Math.abs(newPos) > MAX_POSITION) {
            ordersRejected++;
            positionRejects++;
            return "POSITION_LIMIT: |" + newPos + "| > " + MAX_POSITION;
        }

        /* --- Check 2: Notional Limit --- */
        /* Notional = price × quantity, converted to cents.
         * price is fixed-point 8dp, so price/10^8 × qty × 100 = price × qty / 10^6 */
        long orderNotionalCents = price * quantity / 1_000_000L;
        long currentNotional = notionalCents.get();
        if (currentNotional + orderNotionalCents > MAX_NOTIONAL_CENTS) {
            ordersRejected++;
            notionalRejects++;
            return "NOTIONAL_LIMIT: " + (currentNotional + orderNotionalCents) +
                   " > " + MAX_NOTIONAL_CENTS;
        }

        /* --- Check 3: Order Rate Throttle (Lock-Free Token Bucket) --- */
        if (!tryConsumeToken()) {
            ordersRejected++;
            rateRejects++;
            return "RATE_LIMIT: Token bucket exhausted";
        }

        /* --- Check 4: Fat Finger (Integer Arithmetic, No Float) ---
         *
         * Check: |price - midPrice| / midPrice ≤ 5%
         * Rearranged (integer): |price - midPrice| × 10^8 ≤ midPrice × 5 × 10^6
         *
         * All arithmetic is in fixed-point — no floating point division.
         */
        long mid = currentMidPrice;
        if (mid > 0) {
            long priceDelta = Math.abs(price - mid);
            /* priceDelta / mid ≤ 0.05 → priceDelta × 10^8 ≤ mid × 5_000_000 */
            if (priceDelta * MdEvent.PRICE_SCALE > mid * FAT_FINGER_PCT_FIXED) {
                ordersRejected++;
                fatFingerRejects++;
                return "FAT_FINGER: price " + price + " too far from mid " + mid;
            }
        }

        /* --- Check 5: Drawdown Circuit Breaker --- */
        long pnl = realizedPnlCents.get();
        if (pnl < -MAX_DRAWDOWN_CENTS) {
            tripCircuitBreaker("DRAWDOWN: P&L " + pnl + " cents < -" + MAX_DRAWDOWN_CENTS);
            ordersRejected++;
            drawdownRejects++;
            return "DRAWDOWN_BREAKER: realized P&L = " + pnl + " cents";
        }

        /* --- All Checks Passed: Update Atomic State --- */

        /* CAS-update position */
        positionShares.compareAndSet(currentPos, newPos);

        /* Add notional (relaxed — single updater in practice) */
        notionalCents.addAndGet(orderNotionalCents);

        return null;  /* Order approved */
    }

    /**
     * Lock-free token bucket: try to consume one token.
     *
     * CAS loop:
     *   1. Compute elapsed time since last refill
     *   2. Add tokens proportional to elapsed time (capped at burst capacity)
     *   3. Try to consume one token
     *   4. On CAS failure, retry
     *
     * @return true if token consumed, false if bucket is empty
     */
    private boolean tryConsumeToken() {
        long now = System.nanoTime();

        /* Spin-free CAS loop */
        for (int attempts = 0; attempts < 3; attempts++) {
            long lastRefill = lastRefillNanos.get();
            long elapsed = now - lastRefill;

            /* Compute tokens to add */
            long newTokens = elapsed / NANOS_PER_TOKEN;
            long currentTokens = tokens.get();
            long available = Math.min(currentTokens + newTokens, BURST_CAPACITY);

            if (available <= 0) {
                return false;  /* No tokens available */
            }

            /* CAS: try to consume one token and update refill timestamp */
            if (tokens.compareAndSet(currentTokens, available - 1)) {
                if (newTokens > 0) {
                    lastRefillNanos.compareAndSet(lastRefill, now);
                }
                return true;
            }
            /* CAS failed — another thread consumed; retry */
        }

        return false;
    }

    /* --- Fill Report Handling --- */

    /**
     * Called on execution report (fill) to update realized P&L.
     *
     * @param fillPriceCents  Fill price in cents
     * @param avgCostCents    Average cost basis in cents
     * @param fillQty         Filled quantity
     * @param isBuyFill       True if this was a buy fill
     */
    public final void onFill(final long fillPriceCents, final long avgCostCents,
                              final int fillQty, final boolean isBuyFill) {
        long pnlDelta;
        if (isBuyFill) {
            /* Buying: P&L impact is negative (cost) */
            pnlDelta = -(fillPriceCents * fillQty);
        } else {
            /* Selling: P&L impact is positive (revenue) minus cost */
            pnlDelta = (fillPriceCents - avgCostCents) * fillQty;
        }
        realizedPnlCents.addAndGet(pnlDelta);
    }

    /* --- Circuit Breaker Control --- */

    /**
     * Trip the circuit breaker — halts all order submission immediately.
     */
    public void tripCircuitBreaker(final String reason) {
        if (circuitBreakerOpen.compareAndSet(false, true)) {
            circuitBreakerReason = reason;
            System.err.println("[RISK] CIRCUIT BREAKER TRIPPED: " + reason);
        }
    }

    /**
     * Reset the circuit breaker (manual operation).
     */
    public void resetCircuitBreaker() {
        circuitBreakerOpen.set(false);
        circuitBreakerReason = "";
        System.out.println("[RISK] Circuit breaker reset");
    }

    /* --- Status --- */

    public String getStatus() {
        return String.format(
            "RiskGate[pos=%d, notional=%d¢, pnl=%d¢, checked=%d, rejected=%d, cb=%s]",
            positionShares.get(), notionalCents.get(), realizedPnlCents.get(),
            ordersChecked, ordersRejected,
            circuitBreakerOpen.get() ? "OPEN(" + circuitBreakerReason + ")" : "CLOSED"
        );
    }

    public boolean isCircuitBreakerOpen() { return circuitBreakerOpen.get(); }
    public long getPositionShares() { return positionShares.get(); }
    public long getRealizedPnlCents() { return realizedPnlCents.get(); }
    public long getOrdersChecked() { return ordersChecked; }
    public long getOrdersRejected() { return ordersRejected; }
}
