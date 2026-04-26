package com.hft.signal;

import com.hft.core.MdEvent;

/**
 * HMMRegimeFilter — 2-State Hidden Markov Model for Market Regime Detection
 *
 * <p><b>State Space:</b></p>
 * <pre>
 *   Q = {q₀ = MEAN_REVERT, q₁ = MOMENTUM}
 * </pre>
 *
 * <p><b>Transition Matrix A:</b></p>
 * <pre>
 *   A = | a₀₀  a₀₁ |    a₀₀ = P(MEAN_REVERT → MEAN_REVERT)
 *       | a₁₀  a₁₁ |    a₁₁ = P(MOMENTUM → MOMENTUM)
 * </pre>
 *
 * <p><b>Emission Model:</b></p>
 * Each state emits a bivariate observation O_t = (φ_t, log(λ_t/λ₀)):
 * <pre>
 *   b_k(O_t) = N(O_t; μ_k, Σ_k)
 * </pre>
 * with pre-calibrated parameters {μ_k, Σ_k} per state.
 *
 * <p><b>Online Forward Algorithm (Log-Domain):</b></p>
 * <pre>
 *   log α_t(j) = log b_j(O_t) + log Σ_i exp(log α_{t-1}(i) + log a_{ij})
 * </pre>
 *
 * The log-sum-exp is computed using the numerically stable identity:
 * <pre>
 *   log(e^a + e^b) = a + log(1 + e^{b-a})    when a ≥ b
 * </pre>
 *
 * For K=2 states, the forward recursion is fully unrolled — no loops,
 * no arrays, no log() calls in the hot path (the log-sum-exp reduces
 * to a single log1p() call, which HotSpot intrinsifies).
 *
 * <p><b>Execution Gating:</b></p>
 * <ul>
 *   <li>Submit orders only when P(MOMENTUM) > 0.65 (momentum regime, follow signal)</li>
 *   <li>OR P(MEAN_REVERT) > 0.70 (mean-revert regime, invert OBI signal direction)</li>
 * </ul>
 */
public final class HMMRegimeFilter {

    /* --- State Constants --- */

    public static final int STATE_MEAN_REVERT = 0;
    public static final int STATE_MOMENTUM = 1;
    private static final int NUM_STATES = 2;

    /* --- Transition Matrix (log-domain) --- */

    private double logA00;  /* log P(MR → MR) */
    private double logA01;  /* log P(MR → MOM) */
    private double logA10;  /* log P(MOM → MR) */
    private double logA11;  /* log P(MOM → MOM) */

    /* --- Emission Parameters (bivariate Gaussian, pre-calibrated) --- */

    /**
     * State 0 (MEAN_REVERT) emission: N(μ₀, Σ₀)
     * μ₀ = (mean_obi_0, mean_logLambda_0)
     * Σ₀ stored as (var_obi_0, var_logLambda_0, cov_0) — diagonal + off-diagonal
     */
    private double meanObi0, meanLogLambda0;
    private double varObi0, varLogLambda0, cov0;

    /** State 1 (MOMENTUM) emission. */
    private double meanObi1, meanLogLambda1;
    private double varObi1, varLogLambda1, cov1;

    /** Pre-computed log-determinant and inverse for each state's Σ. */
    private double logDetSigma0, logDetSigma1;
    private double invSigma0_00, invSigma0_01, invSigma0_11;
    private double invSigma1_00, invSigma1_01, invSigma1_11;

    /* --- Forward Variables (log-domain) --- */

    private double logAlpha0;  /* log α_t(MEAN_REVERT) */
    private double logAlpha1;  /* log α_t(MOMENTUM) */

    /** Whether the filter has been initialized with the first observation. */
    private boolean initialized;

    /* --- Signal Thresholds --- */

    private double momentumThreshold;
    private double meanRevertThreshold;

    /* --- Construction --- */

    /**
     * Initialize with pre-calibrated parameters.
     *
     * @param a00 P(MR → MR)
     * @param a11 P(MOM → MOM)
     * @param meanObi0 Mean OBI for MEAN_REVERT state
     * @param meanLogLambda0 Mean log(λ/λ₀) for MEAN_REVERT state
     * @param varObi0 Variance of OBI for MEAN_REVERT
     * @param varLogLambda0 Variance of log(λ/λ₀) for MEAN_REVERT
     * @param cov0 Covariance for MEAN_REVERT
     * @param meanObi1 Mean OBI for MOMENTUM state
     * @param meanLogLambda1 Mean log(λ/λ₀) for MOMENTUM state
     * @param varObi1 Variance of OBI for MOMENTUM
     * @param varLogLambda1 Variance of log(λ/λ₀) for MOMENTUM
     * @param cov1 Covariance for MOMENTUM
     */
    public HMMRegimeFilter(
            final double a00, final double a11,
            final double meanObi0, final double meanLogLambda0,
            final double varObi0, final double varLogLambda0, final double cov0,
            final double meanObi1, final double meanLogLambda1,
            final double varObi1, final double varLogLambda1, final double cov1) {

        /* Transition matrix (log-domain) */
        this.logA00 = Math.log(a00);
        this.logA01 = Math.log(1.0 - a00);
        this.logA10 = Math.log(1.0 - a11);
        this.logA11 = Math.log(a11);

        /* Emission parameters */
        this.meanObi0 = meanObi0; this.meanLogLambda0 = meanLogLambda0;
        this.varObi0 = varObi0; this.varLogLambda0 = varLogLambda0; this.cov0 = cov0;

        this.meanObi1 = meanObi1; this.meanLogLambda1 = meanLogLambda1;
        this.varObi1 = varObi1; this.varLogLambda1 = varLogLambda1; this.cov1 = cov1;

        /* Pre-compute covariance matrix inverse and log-determinant */
        precomputeSigma();

        /* Initialize forward variables with equal prior */
        this.logAlpha0 = Math.log(0.5);
        this.logAlpha1 = Math.log(0.5);
        this.initialized = false;

        /* Default thresholds */
        this.momentumThreshold = 0.65;
        this.meanRevertThreshold = 0.70;
    }

    /**
     * Pre-compute Σ⁻¹ and log|Σ| for each state's 2×2 covariance matrix.
     *
     * For a 2×2 symmetric matrix Σ = [[a, c], [c, b]]:
     *   det(Σ) = a·b - c²
     *   Σ⁻¹ = (1/det) · [[b, -c], [-c, a]]
     */
    private void precomputeSigma() {
        /* State 0 */
        double det0 = varObi0 * varLogLambda0 - cov0 * cov0;
        if (det0 <= 0) det0 = 1e-10;
        logDetSigma0 = Math.log(det0);
        double invDet0 = 1.0 / det0;
        invSigma0_00 = varLogLambda0 * invDet0;
        invSigma0_01 = -cov0 * invDet0;
        invSigma0_11 = varObi0 * invDet0;

        /* State 1 */
        double det1 = varObi1 * varLogLambda1 - cov1 * cov1;
        if (det1 <= 0) det1 = 1e-10;
        logDetSigma1 = Math.log(det1);
        double invDet1 = 1.0 / det1;
        invSigma1_00 = varLogLambda1 * invDet1;
        invSigma1_01 = -cov1 * invDet1;
        invSigma1_11 = varObi1 * invDet1;
    }

    /**
     * Compute log emission probability for a bivariate Gaussian.
     *
     * log b_k(O) = -0.5 · (2·log(2π) + log|Σ_k| + (O-μ)ᵀ Σ_k⁻¹ (O-μ))
     */
    private double logEmission(final double obi, final double logLambda,
                                final double meanObi, final double meanLogL,
                                final double invS00, final double invS01, final double invS11,
                                final double logDetSigma) {
        double d0 = obi - meanObi;
        double d1 = logLambda - meanLogL;

        /* Mahalanobis distance: (O-μ)ᵀ Σ⁻¹ (O-μ) */
        double mahal = d0 * d0 * invS00 + 2.0 * d0 * d1 * invS01 + d1 * d1 * invS11;

        /* -0.5 * (2*log(2π) + log|Σ| + mahal) */
        return -0.5 * (2.0 * 1.8378770664093453 + logDetSigma + mahal);
        /* 1.8378... = log(2π) */
    }

    /**
     * Log-sum-exp for two values: log(exp(a) + exp(b))
     *
     * Uses the numerically stable identity:
     *   log(e^a + e^b) = max(a,b) + log(1 + exp(-|a-b|))
     *
     * For K=2, this is the ONLY transcendental function call in the
     * forward recursion (via Math.log1p, which HotSpot intrinsifies
     * to a single x87 FYL2XP1 or SSE2 instruction).
     */
    private static double logSumExp(final double a, final double b) {
        if (a >= b) {
            return a + Math.log1p(Math.exp(b - a));
        } else {
            return b + Math.log1p(Math.exp(a - b));
        }
    }

    /**
     * Online forward step: update regime posterior with new observation.
     *
     * <p><b>Fully unrolled for K=2 — no loops, no array allocations.</b></p>
     *
     * @param obiDouble OBI as double in [-1, 1]
     * @param logLambdaRatio log(λ(t) / μ₀)
     */
    public final void update(final double obiDouble, final double logLambdaRatio) {

        /* --- Step 1: Compute log emission probabilities --- */

        double logB0 = logEmission(obiDouble, logLambdaRatio,
            meanObi0, meanLogLambda0, invSigma0_00, invSigma0_01, invSigma0_11, logDetSigma0);

        double logB1 = logEmission(obiDouble, logLambdaRatio,
            meanObi1, meanLogLambda1, invSigma1_00, invSigma1_01, invSigma1_11, logDetSigma1);

        /* --- Step 2: Forward recursion (fully unrolled) ---
         *
         * log α_t(j) = log b_j(O_t) + log Σ_i exp(log α_{t-1}(i) + log a_{ij})
         *
         * For j=0 (MEAN_REVERT):
         *   log α_t(0) = logB0 + logSumExp(logAlpha0 + logA00, logAlpha1 + logA10)
         *
         * For j=1 (MOMENTUM):
         *   log α_t(1) = logB1 + logSumExp(logAlpha0 + logA01, logAlpha1 + logA11)
         */

        double newLogAlpha0 = logB0 + logSumExp(logAlpha0 + logA00, logAlpha1 + logA10);
        double newLogAlpha1 = logB1 + logSumExp(logAlpha0 + logA01, logAlpha1 + logA11);

        /* --- Step 3: Normalize to prevent underflow ---
         *
         * Subtract the max to keep log-alphas in a reasonable range.
         * This doesn't affect the posterior (it cancels in normalization).
         */
        double maxLogAlpha = Math.max(newLogAlpha0, newLogAlpha1);
        logAlpha0 = newLogAlpha0 - maxLogAlpha;
        logAlpha1 = newLogAlpha1 - maxLogAlpha;

        initialized = true;
    }

    /**
     * Get the regime posterior: P(MOMENTUM | O_1..t)
     *
     * <pre>
     *   P(MOMENTUM) = exp(logAlpha1) / (exp(logAlpha0) + exp(logAlpha1))
     *               = 1 / (1 + exp(logAlpha0 - logAlpha1))    [numerically stable]
     * </pre>
     */
    public final double getMomentumPosterior() {
        if (!initialized) return 0.5;
        double diff = logAlpha0 - logAlpha1;
        return 1.0 / (1.0 + Math.exp(diff));
    }

    /**
     * Get the regime posterior: P(MEAN_REVERT | O_1..t)
     */
    public final double getMeanRevertPosterior() {
        return 1.0 - getMomentumPosterior();
    }

    /**
     * Determine if a signal should be gated through based on regime.
     *
     * @param hawkesSignal +1 (BUY) or -1 (SELL) from Hawkes estimator
     * @return Adjusted signal: +1, -1, or 0 (gated out)
     */
    public final int gateSignal(final int hawkesSignal) {
        if (hawkesSignal == 0) return 0;

        double pMomentum = getMomentumPosterior();
        double pMeanRevert = 1.0 - pMomentum;

        if (pMomentum > momentumThreshold) {
            /* Momentum regime: pass signal through unchanged */
            return hawkesSignal;
        } else if (pMeanRevert > meanRevertThreshold) {
            /* Mean-revert regime: invert signal direction */
            return -hawkesSignal;
        }

        /* No clear regime: gate the signal (hold) */
        return 0;
    }

    /**
     * Get the regime-adjusted signal confidence.
     * Used as a multiplicative weight on the final signal.
     */
    public final double getConfidence() {
        double pMomentum = getMomentumPosterior();
        return Math.max(pMomentum, 1.0 - pMomentum);
    }

    /* --- Parameter Update (Offline Calibration) --- */

    /**
     * Update HMM parameters from offline Baum-Welch calibration.
     * Called at market open when new parameters are loaded from mmap config.
     */
    public final void updateParameters(
            final double a00, final double a11,
            final double newMeanObi0, final double newMeanLogLambda0,
            final double newVarObi0, final double newVarLogLambda0, final double newCov0,
            final double newMeanObi1, final double newMeanLogLambda1,
            final double newVarObi1, final double newVarLogLambda1, final double newCov1) {

        this.logA00 = Math.log(a00);
        this.logA01 = Math.log(1.0 - a00);
        this.logA10 = Math.log(1.0 - a11);
        this.logA11 = Math.log(a11);

        this.meanObi0 = newMeanObi0; this.meanLogLambda0 = newMeanLogLambda0;
        this.varObi0 = newVarObi0; this.varLogLambda0 = newVarLogLambda0; this.cov0 = newCov0;

        this.meanObi1 = newMeanObi1; this.meanLogLambda1 = newMeanLogLambda1;
        this.varObi1 = newVarObi1; this.varLogLambda1 = newVarLogLambda1; this.cov1 = newCov1;

        precomputeSigma();

        /* Reset forward variables with equal prior */
        logAlpha0 = Math.log(0.5);
        logAlpha1 = Math.log(0.5);
    }
}
