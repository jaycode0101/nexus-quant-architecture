package com.hft.signal;

/**
 * HawkesIntensityEstimator — Self-Exciting Point Process Intensity
 *
 * Implements the exponential-kernel univariate Hawkes process for modeling
 * trade arrival intensity as a proxy for order flow toxicity.
 *
 * <p><b>Model:</b></p>
 * <pre>
 *   λ(t) = μ₀ + Σ_{t_i < t} α · exp(-β · (t - t_i))
 * </pre>
 *
 * <p><b>O(1) Recursive Update (Bacry et al., 2015):</b></p>
 * <pre>
 *   λ(t_n) = μ₀ + (λ(t_{n-1}) - μ₀) · exp(-β · Δt) + α
 * </pre>
 * where Δt = t_n - t_{n-1} in microseconds.
 *
 * <p><b>Stationarity Condition:</b></p>
 * <pre>
 *   ρ = α / β  (branching ratio, must be < 1.0)
 * </pre>
 * If ρ ≥ 1.0, the process is explosive (non-stationary) and the strategy
 * should be halted via circuit breaker.
 *
 * <p><b>Fixed-Point Exponential Approximation:</b></p>
 * Uses a pre-computed lookup table (LUT) indexed by {@code (int)(β·Δt·LUT_SCALE)}
 * with linear interpolation for sub-nanosecond evaluation of exp(-β·Δt).
 *
 * <p><b>Signal Logic:</b></p>
 * If λ(t) > λ_threshold AND dλ/dt > 0 (intensity accelerating):
 * <ul>
 *   <li>HAWKES_SIGNAL = BUY if φ > φ_threshold (OBI confirms buy pressure)</li>
 *   <li>HAWKES_SIGNAL = SELL if φ < -φ_threshold</li>
 *   <li>HAWKES_SIGNAL = HOLD otherwise</li>
 * </ul>
 */
public final class HawkesIntensityEstimator {

    /* --- Model Parameters (calibrated offline, loaded at market open) --- */

    /** Baseline intensity (events per microsecond). */
    private double mu0;

    /** Excitation magnitude — intensity jump per arrival. */
    private double alpha;

    /** Decay rate — exponential kernel parameter. */
    private double beta;

    /** Branching ratio ρ = α/β. Must be < 1.0 for stationarity. */
    private double branchingRatio;

    /** Intensity threshold for signal generation. */
    private double lambdaThreshold;

    /** OBI threshold for directional confirmation. */
    private double obiThreshold;

    /* --- State --- */

    /** Current conditional intensity λ(t). */
    private double lambda;

    /** Previous intensity for derivative computation. */
    private double prevLambda;

    /** Timestamp of the last trade event (nanoseconds since midnight). */
    private long lastTradeTimestampNs;

    /** Whether the estimator has been seeded with at least one trade. */
    private boolean initialized;

    /* --- Exponential LUT --- */

    /**
     * Pre-computed lookup table for exp(-x) where x = β·Δt·LUT_SCALE.
     *
     * LUT sizing:
     *   - Max Δt between trades: ~10 seconds = 10^7 μs
     *   - β typically in [0.01, 10.0] per μs
     *   - Max argument: β·Δt ≈ 10 × 10^7 = 10^8 → exp(-10^8) ≈ 0
     *   - For practical range: β·Δt ∈ [0, 20] → exp(-20) ≈ 2×10^-9
     *   - LUT_SIZE = 4096, LUT_SCALE = 4096/20 = 204.8
     *   - Resolution: 20/4096 ≈ 0.00488 → relative error < 0.1%
     *     with linear interpolation
     */
    private static final int LUT_SIZE = 4096;
    private static final double LUT_MAX_ARG = 20.0;
    private static final double LUT_SCALE = LUT_SIZE / LUT_MAX_ARG;
    private static final double[] EXP_LUT = new double[LUT_SIZE + 1];

    static {
        /* Pre-compute exp(-x) for x in [0, LUT_MAX_ARG] */
        for (int i = 0; i <= LUT_SIZE; i++) {
            double x = (double) i / LUT_SCALE;
            EXP_LUT[i] = Math.exp(-x);
        }
    }

    /**
     * Fast exponential approximation via LUT with linear interpolation.
     *
     * @param x Non-negative argument (β·Δt)
     * @return Approximation of exp(-x)
     */
    private static double fastExpNeg(final double x) {
        if (x <= 0.0) return 1.0;
        if (x >= LUT_MAX_ARG) return 0.0;

        double indexF = x * LUT_SCALE;
        int indexI = (int) indexF;
        double frac = indexF - indexI;

        /* Linear interpolation between adjacent LUT entries */
        return EXP_LUT[indexI] + frac * (EXP_LUT[indexI + 1] - EXP_LUT[indexI]);
    }

    /* --- Construction --- */

    /**
     * @param mu0             Baseline intensity (events/μs)
     * @param alpha           Excitation magnitude
     * @param beta            Decay rate
     * @param lambdaThreshold Signal generation threshold
     * @param obiThreshold    OBI directional confirmation threshold (fixed-point 8dp)
     */
    public HawkesIntensityEstimator(final double mu0, final double alpha,
                                     final double beta, final double lambdaThreshold,
                                     final double obiThreshold) {
        this.mu0 = mu0;
        this.alpha = alpha;
        this.beta = beta;
        this.branchingRatio = alpha / beta;
        this.lambdaThreshold = lambdaThreshold;
        this.obiThreshold = obiThreshold;
        this.lambda = mu0;
        this.prevLambda = mu0;
        this.lastTradeTimestampNs = 0;
        this.initialized = false;

        /* Assert stationarity at startup */
        if (branchingRatio >= 1.0) {
            throw new IllegalArgumentException(
                "Hawkes branching ratio ρ = α/β = " + branchingRatio +
                " ≥ 1.0 — process is explosive. Refusing to start.");
        }

        if (branchingRatio > 0.9) {
            System.err.println("[WARN] Hawkes branching ratio ρ = " + branchingRatio +
                " > 0.9 — near-explosive. Consider circuit-breaking the strategy.");
        }
    }

    /**
     * Update the intensity on a new trade arrival.
     *
     * <p><b>O(1) Recursive Update:</b></p>
     * <pre>
     *   λ(t_n) = μ₀ + (λ(t_{n-1}) - μ₀) · exp(-β · Δt) + α
     * </pre>
     *
     * This avoids the O(N) sum over all historical events by exploiting the
     * exponential kernel's memoryless property. The full sum telescopes:
     * <pre>
     *   Σ_{i<n} α·exp(-β·(t_n - t_i))
     *     = α·exp(-β·Δt) · Σ_{i<n-1} exp(-β·(t_{n-1} - t_i)) + α
     *     = exp(-β·Δt) · (λ(t_{n-1}) - μ₀) + α
     * </pre>
     *
     * @param tradeTimestampNs Nanosecond timestamp of the trade event
     */
    public final void onTrade(final long tradeTimestampNs) {
        if (!initialized) {
            lastTradeTimestampNs = tradeTimestampNs;
            lambda = mu0 + alpha;  /* First trade jumps intensity by α */
            initialized = true;
            return;
        }

        /* Δt in microseconds (Hawkes parameters are calibrated in μs) */
        double deltaT_us = (double)(tradeTimestampNs - lastTradeTimestampNs) / 1000.0;
        if (deltaT_us < 0) deltaT_us = 0;  /* Clock skew protection */

        prevLambda = lambda;

        /* Recursive update */
        double decay = fastExpNeg(beta * deltaT_us);
        lambda = mu0 + (lambda - mu0) * decay + alpha;

        lastTradeTimestampNs = tradeTimestampNs;
    }

    /**
     * Compute the current intensity without a new trade arrival.
     * Used to evaluate λ(t) at non-trade events (e.g., order book updates).
     *
     * @param currentTimestampNs Current nanosecond timestamp
     * @return Current conditional intensity
     */
    public final double getIntensityAt(final long currentTimestampNs) {
        if (!initialized) return mu0;

        double deltaT_us = (double)(currentTimestampNs - lastTradeTimestampNs) / 1000.0;
        if (deltaT_us < 0) deltaT_us = 0;

        double decay = fastExpNeg(beta * deltaT_us);
        return mu0 + (lambda - mu0) * decay;
    }

    /**
     * Generate a trading signal based on Hawkes intensity and OBI confirmation.
     *
     * @param obiFixed OBI value in fixed-point (8 decimal places)
     * @return +1 (BUY), -1 (SELL), or 0 (HOLD)
     */
    public final int generateSignal(final long obiFixed) {
        /* dλ/dt approximation: sign of (λ_current - λ_previous) */
        double dLambda = lambda - prevLambda;
        boolean intensityAccelerating = dLambda > 0;

        /* Signal trigger: intensity above threshold AND accelerating */
        if (lambda > lambdaThreshold && intensityAccelerating) {
            double obiDouble = (double) obiFixed / (double) MdEvent.PRICE_SCALE;

            if (obiDouble > obiThreshold) {
                return +1;  /* BUY: high intensity + positive OBI = buy pressure */
            } else if (obiDouble < -obiThreshold) {
                return -1;  /* SELL: high intensity + negative OBI = sell pressure */
            }
        }

        return 0;  /* HOLD */
    }

    /* --- Accessors --- */

    public final double getLambda() { return lambda; }
    public final double getPrevLambda() { return prevLambda; }
    public final double getDerivative() { return lambda - prevLambda; }
    public final double getBranchingRatio() { return branchingRatio; }
    public final double getMu0() { return mu0; }

    /**
     * Update parameters from offline calibration (via mmap config file).
     * Called at market open when new parameters are available.
     */
    public final void updateParameters(final double newMu0, final double newAlpha,
                                        final double newBeta) {
        this.mu0 = newMu0;
        this.alpha = newAlpha;
        this.beta = newBeta;
        this.branchingRatio = newAlpha / newBeta;

        if (branchingRatio >= 1.0) {
            throw new IllegalArgumentException(
                "Calibrated ρ = " + branchingRatio + " ≥ 1.0 — circuit break");
        }
    }
}
