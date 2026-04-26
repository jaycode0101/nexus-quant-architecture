package com.hft.signal;

/**
 * FeatureVector — Pre-Allocated Off-Heap Feature Container
 *
 * Holds the computed features from LOB reconstruction (micro-price, OBI)
 * and signal generation (Hawkes intensity, HMM regime posterior).
 * All fields are plain Java primitives — no allocation, no boxing.
 *
 * This object is shared between the LOBReconstructionHandler (writer)
 * and the SignalGenerationHandler (reader) via the Disruptor's
 * sequential processing guarantee.
 */
public final class FeatureVector {

    /* --- LOB Features (set by LOBReconstructionHandler) --- */

    /** Micro-price: μ = (ask × Q_bid + bid × Q_ask) / (Q_bid + Q_ask). Fixed-point 8dp. */
    private long microPrice;

    /** Order Book Imbalance: φ = (Q_bid - Q_ask) / (Q_bid + Q_ask). Fixed-point 8dp. */
    private long obi;

    /** OBI momentum: Δφ = φ(t) - φ(t-1). Fixed-point 8dp. */
    private long obiDelta;

    /** Mid-price: (bestBid + bestAsk) / 2. Fixed-point 8dp. */
    private long midPrice;

    /** Spread: bestAsk - bestBid. Fixed-point 8dp. */
    private long spread;

    /** Best bid/ask prices and quantities. */
    private long bestBidPrice;
    private long bestAskPrice;
    private long bestBidQty;
    private long bestAskQty;

    /* --- Trade Event Fields --- */

    private long lastTradeTimestampNs;
    private long lastTradePrice;
    private int  lastTradeQty;
    private boolean isTradeEvent;

    /* --- Signal Features (set by SignalGenerationHandler) --- */

    /** Hawkes conditional intensity λ(t). Double precision. */
    private double hawkesIntensity;

    /** dλ/dt — intensity rate of change (positive = accelerating). */
    private double hawkesDerivative;

    /** HMM regime posterior: P(MOMENTUM | observations). Range [0, 1]. */
    private double regimePosteriorMomentum;

    /** Composite signal: BUY (+1), SELL (-1), or HOLD (0). */
    private int signalDirection;

    /** Signal confidence: |posterior| × |OBI|. Range [0, 1]. */
    private double signalConfidence;

    /** Event timestamp. */
    private long timestampNs;

    /* --- Getters/Setters (all final for monomorphic JIT) --- */

    public final long getMicroPrice() { return microPrice; }
    public final void setMicroPrice(final long v) { microPrice = v; }

    public final long getObi() { return obi; }
    public final void setObi(final long v) { obi = v; }

    public final long getObiDelta() { return obiDelta; }
    public final void setObiDelta(final long v) { obiDelta = v; }

    public final long getMidPrice() { return midPrice; }
    public final void setMidPrice(final long v) { midPrice = v; }

    public final long getSpread() { return spread; }
    public final void setSpread(final long v) { spread = v; }

    public final long getBestBidPrice() { return bestBidPrice; }
    public final void setBestBidPrice(final long v) { bestBidPrice = v; }

    public final long getBestAskPrice() { return bestAskPrice; }
    public final void setBestAskPrice(final long v) { bestAskPrice = v; }

    public final long getBestBidQty() { return bestBidQty; }
    public final void setBestBidQty(final long v) { bestBidQty = v; }

    public final long getBestAskQty() { return bestAskQty; }
    public final void setBestAskQty(final long v) { bestAskQty = v; }

    public final long getLastTradeTimestampNs() { return lastTradeTimestampNs; }
    public final void setLastTradeTimestampNs(final long v) { lastTradeTimestampNs = v; }

    public final long getLastTradePrice() { return lastTradePrice; }
    public final void setLastTradePrice(final long v) { lastTradePrice = v; }

    public final int getLastTradeQty() { return lastTradeQty; }
    public final void setLastTradeQty(final int v) { lastTradeQty = v; }

    public final boolean isTradeEvent() { return isTradeEvent; }
    public final void setIsTradeEvent(final boolean v) { isTradeEvent = v; }

    public final double getHawkesIntensity() { return hawkesIntensity; }
    public final void setHawkesIntensity(final double v) { hawkesIntensity = v; }

    public final double getHawkesDerivative() { return hawkesDerivative; }
    public final void setHawkesDerivative(final double v) { hawkesDerivative = v; }

    public final double getRegimePosteriorMomentum() { return regimePosteriorMomentum; }
    public final void setRegimePosteriorMomentum(final double v) { regimePosteriorMomentum = v; }

    public final int getSignalDirection() { return signalDirection; }
    public final void setSignalDirection(final int v) { signalDirection = v; }

    public final double getSignalConfidence() { return signalConfidence; }
    public final void setSignalConfidence(final double v) { signalConfidence = v; }

    public final long getTimestampNs() { return timestampNs; }
    public final void setTimestampNs(final long v) { timestampNs = v; }
}
