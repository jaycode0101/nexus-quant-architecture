# Deliverable D — Quantitative Signal Models

## Mathematical Foundations & Implementation Specifications

---

## D.1 Hawkes Self-Exciting Point Process

### D.1.1 Model Definition

Let `(Ω, F, {F_t}_{t≥0}, P)` be a filtered probability space supporting a counting process `N(t)` with conditional intensity:

```
λ(t) = μ₀ + ∫₀ᵗ α · exp(-β · (t - s)) dN(s)
     = μ₀ + Σ_{t_i < t} α · exp(-β · (t - t_i))
```

where:
- `μ₀ > 0` is the baseline (exogenous) arrival rate
- `α > 0` is the excitation magnitude (endogenous self-excitation)
- `β > 0` is the exponential decay rate
- `{t_i}` are the observed event (trade) arrival times

**Stationarity Condition:** The process is stationary if and only if the branching ratio satisfies:

```
ρ = α/β < 1
```

When `ρ < 1`, the expected intensity converges to `E[λ(t)] = μ₀ / (1 - ρ)`.

### D.1.2 Log-Likelihood Function

For `n` observed events at times `{t_1, ..., t_n}` on `[0, T]`:

```
ℒ(μ₀, α, β) = Σᵢ₌₁ⁿ log λ(tᵢ) - ∫₀ᵀ λ(s) ds
```

**Compensator (integrated intensity):**

```
Λ(T) = ∫₀ᵀ λ(s) ds = μ₀T + (α/β) Σᵢ₌₁ⁿ [1 - exp(-β(T - tᵢ))]
```

This avoids numerical integration by exploiting the closed-form integral of the exponential kernel.

**Full log-likelihood:**

```
ℒ = Σᵢ₌₁ⁿ log[μ₀ + Σⱼ<ᵢ α·exp(-β(tᵢ - tⱼ))] - μ₀T - (α/β) Σᵢ₌₁ⁿ [1 - exp(-β(T - tᵢ))]
```

### D.1.3 MLE Gradients for L-BFGS

```
∂ℒ/∂μ₀ = Σᵢ 1/λ(tᵢ) - T

∂ℒ/∂α = Σᵢ [Σⱼ<ᵢ exp(-β(tᵢ-tⱼ))] / λ(tᵢ) - (1/β) Σᵢ [1 - exp(-β(T-tᵢ))]

∂ℒ/∂β = Σᵢ [-α·Σⱼ<ᵢ (tᵢ-tⱼ)·exp(-β(tᵢ-tⱼ))] / λ(tᵢ)
         + (α/β²) Σᵢ [1 - exp(-β(T-tᵢ))]
         - (α/β) Σᵢ (T-tᵢ)·exp(-β(T-tᵢ))
```

### D.1.4 O(1) Online Recursive Update

**Key insight:** The sum `R(tₙ) = Σⱼ<ₙ exp(-β(tₙ - tⱼ))` satisfies:

```
R(tₙ) = exp(-β·Δt) · R(tₙ₋₁) + 1
```

where `Δt = tₙ - tₙ₋₁`.

Therefore the intensity update is:

```
λ(tₙ) = μ₀ + α · R(tₙ)
       = μ₀ + α · [exp(-β·Δt) · R(tₙ₋₁) + 1]
       = μ₀ + (λ(tₙ₋₁) - μ₀) · exp(-β·Δt) + α
```

This is **O(1)** per event — no summation over history required.

**Derivation:**
```
R(tₙ) = Σⱼ<ₙ exp(-β(tₙ - tⱼ))
       = Σⱼ<ₙ₋₁ exp(-β(tₙ - tⱼ)) + exp(-β(tₙ - tₙ₋₁))
       = exp(-β·Δt) · Σⱼ<ₙ₋₁ exp(-β(tₙ₋₁ - tⱼ)) + 1
       = exp(-β·Δt) · R(tₙ₋₁) + 1
```

### D.1.5 Glosten-Milgrom Adverse Selection Interpretation

In Glosten-Milgrom (1985), the market maker faces an adverse selection problem:

```
P(informed | trade) = (1-π)·δ·f(v|v>a) / [(1-π)·δ·f(v|v>a) + π·g]
```

where `π` is the fraction of noise traders, `δ` is the probability of an informed trader, and `f(v|v>a)` is the conditional asset value distribution.

**Connection to Hawkes:** Elevated `λ(t)` (high self-excitation, cluster of trades) signals a higher probability of informed trader activity. The OBI confirmation (φ > threshold) filters for the direction of the informed flow:

```
Signal = { BUY   if λ(t) > λ_thresh AND dλ/dt > 0 AND φ > φ_thresh
         { SELL  if λ(t) > λ_thresh AND dλ/dt > 0 AND φ < -φ_thresh
         { HOLD  otherwise
```

---

## D.2 Order Book Imbalance & Micro-Price

### D.2.1 Micro-Price (Stoikov, 2010)

The micro-price is a volume-weighted estimate of the "true" price:

```
μ_t = (a_t · Q^b_t + b_t · Q^a_t) / (Q^b_t + Q^a_t)
```

where `a_t, b_t` are the best ask/bid prices and `Q^a_t, Q^b_t` are the corresponding aggregate quantities.

**Interpretation:** When `Q^b >> Q^a`, the micro-price moves toward the ask (buy pressure). This predicts short-term price direction better than the mid-price.

### D.2.2 OBI Predictive Regression

The OBI predicts future returns:

```
φ_t = (Q^b_t - Q^a_t) / (Q^b_t + Q^a_t) ∈ [-1, 1]
```

**Predictive regression (Cont et al., 2014):**

```
E[r_{t+Δ} | F_t] ≈ γ · φ_t + δ · Δφ_t + ε_t
```

where `r_{t+Δ}` is the return over horizon `Δ`, `γ` captures OBI level impact, and `δ` captures OBI momentum impact.

### D.2.3 Recursive Least Squares (RLS) Calibration

The regression coefficients `θ = (γ, δ)ᵀ` are updated online via RLS with exponential forgetting:

```
K_t = P_{t-1} · x_t / (λ_f + x_t^T · P_{t-1} · x_t)
θ_t = θ_{t-1} + K_t · (r_t - x_t^T · θ_{t-1})
P_t = (1/λ_f) · (P_{t-1} - K_t · x_t^T · P_{t-1})
```

where `x_t = (φ_t, Δφ_t)^T`, `λ_f ∈ (0.99, 0.9999)` is the forgetting factor, and `P_t` is the covariance matrix.

**O(1) per update** — 2×2 matrix operations are unrolled into scalar arithmetic.

### D.2.4 Avellaneda-Stoikov Inventory Extension

The optimal quotes incorporate inventory penalty (Avellaneda & Stoikov, 2008):

```
reservation_price = s_t - q · γ · σ² · (T - t)
optimal_spread = γ · σ² · (T - t) + (2/γ) · ln(1 + γ/κ)
```

where `q` is inventory, `s_t` is mid-price, `γ` is risk aversion, `σ` is volatility, and `κ` is the fill rate parameter.

---

## D.3 Hidden Markov Model Regime Detection

### D.3.1 Complete State Space

**States:** `Q = {q₀ = MEAN_REVERT, q₁ = MOMENTUM}`

**Initial distribution:** `π = (0.5, 0.5)` (equal prior)

**Transition matrix:**
```
A = | a₀₀  a₀₁ |   where a₀₀ + a₀₁ = 1
    | a₁₀  a₁₁ |         a₁₀ + a₁₁ = 1
```

Typical values: `a₀₀ ≈ 0.95` (regimes are sticky), `a₁₁ ≈ 0.93`.

### D.3.2 Emission Distributions

Each state `k` emits bivariate observations `O_t = (φ_t, log(λ_t/μ₀))`:

```
b_k(O_t) = N(O_t; μ_k, Σ_k)
```

For 2D Gaussian:

```
b_k(O) = (2π)⁻¹ |Σ_k|⁻¹/² exp(-½ (O-μ_k)ᵀ Σ_k⁻¹ (O-μ_k))
```

**State 0 (MEAN_REVERT):**
```
μ₀ = (0.0, 0.0)     — OBI near zero, intensity near baseline
Σ₀ = [[0.04, 0.00],  — low OBI variance
       [0.00, 0.50]]  — moderate intensity variance
```

**State 1 (MOMENTUM):**
```
μ₁ = (±0.15, 1.5)   — significant OBI, elevated intensity
Σ₁ = [[0.09, 0.05],  — higher OBI variance
       [0.05, 1.00]]  — high intensity variance
```

### D.3.3 Forward Recursion (Log-Domain)

```
log α_t(j) = log b_j(O_t) + log Σᵢ exp(log α_{t-1}(i) + log a_{ij})
```

**Log-sum-exp trick (numerically stable):**

```
log(eᵃ + eᵇ) = max(a,b) + log(1 + exp(-|a-b|))
             = max(a,b) + log1p(exp(-|a-b|))
```

For K=2, this reduces to a **single `log1p()` call** per state per step — HotSpot intrinsifies `Math.log1p()` to a single x87 instruction.

**Normalization:** After each step, subtract `max(logα₀, logα₁)` to prevent underflow.

### D.3.4 Posterior Computation

```
P(MOMENTUM | O_{1:t}) = exp(logα₁) / (exp(logα₀) + exp(logα₁))
                       = 1 / (1 + exp(logα₀ - logα₁))    [sigmoid form]
```

This is a **single `Math.exp()` call** — no additional log/exp required.

### D.3.5 Offline Baum-Welch EM

**E-step (Forward-Backward):**

```
Forward:  α_t(j) = b_j(O_t) · Σᵢ α_{t-1}(i) · a_{ij}
Backward: β_t(i) = Σⱼ a_{ij} · b_j(O_{t+1}) · β_{t+1}(j)

γ_t(i) = α_t(i) · β_t(i) / Σⱼ α_t(j) · β_t(j)
ξ_t(i,j) = α_t(i) · a_{ij} · b_j(O_{t+1}) · β_{t+1}(j) / Σₖ α_T(k)
```

**M-step:**

```
â_{ij} = Σ_t ξ_t(i,j) / Σ_t γ_t(i)
μ̂_k = Σ_t γ_t(k) · O_t / Σ_t γ_t(k)
Σ̂_k = Σ_t γ_t(k) · (O_t - μ̂_k)(O_t - μ̂_k)ᵀ / Σ_t γ_t(k)
```

**Convergence:** Iterate until `|ℒ(θ^{new}) - ℒ(θ^{old})| < ε` where `ε = 10⁻⁶`.

**Model selection:** BIC = `-2ℒ + k·ln(n)` where `k = 2·(K²-K) + K·(d+d(d+1)/2)` parameters. AIC for comparison.

---

## D.4 Composite Signal Architecture

### D.4.1 Signal Flow

```
Trade Events → Hawkes λ(t) O(1) update
                    ↓
LOB Updates → OBI φ(t), Micro-price μ(t)
                    ↓
(φ(t), log(λ/μ₀)) → HMM forward step → P(regime)
                    ↓
Hawkes Signal = f(λ, dλ/dt, φ)
                    ↓
Gated Signal = HMM.gate(Hawkes Signal)
                    ↓
Confidence = max(P(MOM), P(MR)) × |φ|
                    ↓
Risk Gate → Order Submission
```

### D.4.2 Signal Interpretation

| Regime | OBI | λ(t) | dλ/dt | Signal | Interpretation |
|--------|-----|------|-------|--------|----------------|
| MOMENTUM | φ > +0.3 | > 5×μ₀ | > 0 | **BUY** | Informed buying pressure, follow the flow |
| MOMENTUM | φ < -0.3 | > 5×μ₀ | > 0 | **SELL** | Informed selling pressure, follow the flow |
| MEAN_REVERT | φ > +0.3 | > 5×μ₀ | > 0 | **SELL** | Overextended buy imbalance, fade it |
| MEAN_REVERT | φ < -0.3 | > 5×μ₀ | > 0 | **BUY** | Overextended sell imbalance, fade it |
| Any | |φ| < 0.3 | any | any | **HOLD** | No directional conviction |
| Any | any | < 5×μ₀ | any | any | **HOLD** | Low activity, no edge |
