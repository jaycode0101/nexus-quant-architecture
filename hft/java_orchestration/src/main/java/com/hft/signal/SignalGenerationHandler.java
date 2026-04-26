package com.hft.signal;

import com.lmax.disruptor.EventHandler;
import com.hft.core.MdEvent;
import com.hft.lob.LOBReconstructionHandler;

/**
 * SignalGenerationHandler — Feature Extraction & Signal Pipeline
 *
 * Downstream Disruptor consumer that reads the FeatureVector (populated by
 * LOBReconstructionHandler) and computes:
 *   1. Hawkes conditional intensity (on TRADE events)
 *   2. HMM regime posterior (on every event)
 *   3. Composite trading signal
 *
 * This handler depends on LOBReconstructionHandler completing first
 * (enforced by Disruptor diamond dependency wiring).
 */
public final class SignalGenerationHandler implements EventHandler<MdEvent> {

    /* --- Signal Components --- */

    private final HawkesIntensityEstimator hawkes;
    private final HMMRegimeFilter hmm;

    /**
     * Reference to the LOB handler's feature vector.
     * Set during pipeline wiring (same Disruptor pipeline, sequential access).
     */
    private FeatureVector featureVector;

    /** Exponentially weighted running variance of mid-price changes for σ_t. */
    private double ewmaVariance;
    private long prevMidPrice;
    private boolean varianceInitialized;

    /** Exponential decay factor for running variance: λ_f = exp(-κΔt). */
    private static final double EWMA_ALPHA = 0.01;

    /* --- Signal Output --- */

    private int lastSignal;
    private double lastConfidence;

    public SignalGenerationHandler() {
        /*
         * Default Hawkes parameters (calibrated offline, updated at market open):
         *   μ₀ = 0.001 events/μs (≈ 1 trade per millisecond baseline)
         *   α  = 0.0008 (excitation per trade)
         *   β  = 0.001  (decay rate → half-life ≈ 693μs ≈ 0.7ms)
         *   ρ  = α/β = 0.8 (subcritical, stationary)
         *   λ_threshold = 0.005 (5× baseline → high activity)
         *   OBI threshold = 0.3 (30% imbalance)
         */
        this.hawkes = new HawkesIntensityEstimator(
            0.001,   /* mu0 */
            0.0008,  /* alpha */
            0.001,   /* beta */
            0.005,   /* lambda threshold */
            0.3      /* OBI threshold */
        );

        /*
         * Default HMM parameters (calibrated via Baum-Welch on historical data):
         *   Transition: P(MR→MR) = 0.95, P(MOM→MOM) = 0.93
         *   State 0 (MEAN_REVERT): low OBI variance, low intensity
         *   State 1 (MOMENTUM): high OBI magnitude, high intensity
         */
        this.hmm = new HMMRegimeFilter(
            0.95, 0.93,                                /* transition probs */
            0.0, 0.0, 0.04, 0.5, 0.0,                /* state 0: mean OBI=0, logλ=0 */
            0.15, 1.5, 0.09, 1.0, 0.05               /* state 1: mean OBI=0.15, logλ=1.5 */
        );

        this.ewmaVariance = 0.0;
        this.prevMidPrice = 0;
        this.varianceInitialized = false;
        this.lastSignal = 0;
        this.lastConfidence = 0.0;
    }

    /**
     * Set the feature vector reference (called during pipeline setup).
     */
    public void setFeatureVector(final FeatureVector fv) {
        this.featureVector = fv;
    }

    @Override
    public void onEvent(final MdEvent event, final long sequence, final boolean endOfBatch) {
        if (featureVector == null) return;

        /* --- 1. Hawkes Update (on TRADE events only) --- */
        if (featureVector.isTradeEvent()) {
            hawkes.onTrade(featureVector.getLastTradeTimestampNs());
        }

        /* --- 2. Running Realized Volatility ---
         *
         * σ²_t = (1-α)·σ²_{t-1} + α·(ΔmidPrice)²
         *
         * O(1) exponentially-weighted variance update.
         */
        long midPrice = featureVector.getMidPrice();
        if (midPrice > 0 && prevMidPrice > 0) {
            long midDelta = midPrice - prevMidPrice;
            double midDeltaDouble = (double) midDelta / (double) MdEvent.PRICE_SCALE;
            double sqReturn = midDeltaDouble * midDeltaDouble;

            if (varianceInitialized) {
                ewmaVariance = (1.0 - EWMA_ALPHA) * ewmaVariance + EWMA_ALPHA * sqReturn;
            } else {
                ewmaVariance = sqReturn;
                varianceInitialized = true;
            }
        }
        prevMidPrice = midPrice;

        /* --- 3. HMM Forward Step --- */
        double obiDouble = (double) featureVector.getObi() / (double) MdEvent.PRICE_SCALE;
        double lambda = hawkes.getIntensityAt(featureVector.getTimestampNs());
        double logLambdaRatio = (hawkes.getMu0() > 0) ?
            Math.log(lambda / hawkes.getMu0()) : 0.0;

        hmm.update(obiDouble, logLambdaRatio);

        /* --- 4. Composite Signal Generation --- */

        /* Hawkes signal with OBI confirmation */
        int hawkesSignal = hawkes.generateSignal(featureVector.getObi());

        /* Regime-gated signal */
        int gatedSignal = hmm.gateSignal(hawkesSignal);

        /* Volatility filter: suppress signal if σ is too high or too low */
        double sigma = Math.sqrt(Math.max(ewmaVariance, 1e-20));
        if (sigma > 0.01) {
            /* High volatility — reduce confidence, don't suppress entirely */
            lastConfidence = hmm.getConfidence() * 0.5;
        } else {
            lastConfidence = hmm.getConfidence();
        }

        lastSignal = gatedSignal;

        /* --- 5. Write Signal to FeatureVector --- */
        featureVector.setHawkesIntensity(lambda);
        featureVector.setHawkesDerivative(hawkes.getDerivative());
        featureVector.setRegimePosteriorMomentum(hmm.getMomentumPosterior());
        featureVector.setSignalDirection(gatedSignal);
        featureVector.setSignalConfidence(lastConfidence);
    }

    /* --- Accessors --- */

    public int getLastSignal() { return lastSignal; }
    public double getLastConfidence() { return lastConfidence; }
    public HawkesIntensityEstimator getHawkes() { return hawkes; }
    public HMMRegimeFilter getHmm() { return hmm; }
}
