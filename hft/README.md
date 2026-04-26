# Institutional-Grade High-Frequency Trading System

## Sub-Microsecond Tick-to-Trade Execution Infrastructure

[![C11](https://img.shields.io/badge/C-C11-blue)]()
[![Java](https://img.shields.io/badge/Java-21-orange)]()
[![License](https://img.shields.io/badge/License-Proprietary-red)]()

---

## Architecture Overview

A production-grade co-located HFT system designed for sub-microsecond execution at tier-1 exchange data centers (NYSE Mahwah, CME Aurora, Equinix NY4/LD4).

**Target Performance:** P50 ≤ 705ns, P99 ≤ 800ns tick-to-trade

```
Exchange Feed ─→ Solarflare NIC (EF_VI) ─→ SIMD ITCH Parser ─→ SPSC Ring
                                                                    │
    Order ←-- OEG (ef_vi TX) ←-- Risk Gate ←-- Strategy ←-- Disruptor
```

### System Components

| Component | Language | Core | Latency Budget |
|-----------|----------|------|---------------|
| Feed Handler + ITCH Parser | C11 | Core 1 (isolated) | ≤ 135ns |
| Order Entry Gateway | C11 | Core 2 (isolated) | ≤ 100ns |
| SPSC Ring Buffer | C11 | Shared mmap | ≤ 10ns |
| Disruptor Producer | Java 21 | Core 4 (isolated) | ≤ 70ns |
| LOB Reconstruction | Java 21 | Core 5 (isolated) | ≤ 80ns |
| Hawkes + HMM Signals | Java 21 | Core 6 (isolated) | ≤ 130ns |
| Risk Gateway (5 checks) | Java 21 | Core 7 (isolated) | ≤ 150ns |
| SBE Order Construction | Java 21 | Core 8 (isolated) | ≤ 40ns |

---

## Directory Structure

```
hft/
├-- README.md                          ← You are here
├-- docs/
│   ├-- architecture.md                ← Mermaid diagrams, NUMA topology
│   ├-- quantitative_models.md         ← Hawkes, HMM, OBI derivations
│   └-- calibration_ops.md             ← Calibration pipeline, latency budget
├-- c_data_plane/
│   ├-- CMakeLists.txt                 ← Build: cmake + make
│   ├-- include/
│   │   ├-- platform.h                 ← Cross-platform abstraction (EF_VI stubs)
│   │   ├-- md_event.h                 ← 64-byte cache-line-aligned MdEvent struct
│   │   ├-- spsc_ring.h               ← Lock-free SPSC ring buffer
│   │   ├-- itch_parser.h             ← ITCH 5.0 parser API
│   │   ├-- ef_vi_receiver.h          ← Kernel-bypass receiver API
│   │   └-- order_entry_gateway.h     ← OEG API
│   └-- src/
│       ├-- itch_parser.c             ← AVX2 SIMD ITCH parser
│       ├-- ef_vi_receiver.c          ← EF_VI poll loop + DMA management
│       ├-- order_entry_gateway.c     ← SBE template patch + TX
│       └-- main.c                    ← Integration demo
├-- java_orchestration/
│   ├-- pom.xml                        ← Maven (Disruptor 4.x, Chronicle Queue)
│   └-- src/main/java/com/hft/
│       ├-- core/
│       │   ├-- MdEvent.java           ← Off-heap flyweight (Unsafe)
│       │   ├-- DisruptorPipeline.java ← LMAX Disruptor wiring
│       │   └-- SharedMemoryBridge.java ← C→Java mmap bridge
│       ├-- lob/
│       │   └-- LOBReconstructionHandler.java ← Off-heap order book
│       ├-- signal/
│       │   ├-- FeatureVector.java     ← Pre-allocated feature container
│       │   ├-- HawkesIntensityEstimator.java ← O(1) recursive update
│       │   ├-- HMMRegimeFilter.java   ← Log-domain forward algorithm
│       │   └-- SignalGenerationHandler.java ← Composite signal pipeline
│       ├-- risk/
│       │   └-- PreTradeRiskGateway.java ← Lock-free atomic risk gate
│       ├-- oeg/
│       │   └-- OrderConstructor.java  ← SBE template patch (Unsafe)
│       ├-- journal/
│       │   ├-- ChronicleJournal.java  ← Zero-alloc journaling
│       │   └-- PositionRecovery.java  ← Crash recovery
│       ├-- config/
│       │   └-- SystemConfig.java      ← JVM flags, core assignments
│       └-- benchmark/
│           └-- RiskGateBenchmark.java ← JMH latency harness
└-- scripts/
    ├-- jvm_startup.sh                 ← Production JVM launch
    ├-- cpu_affinity.sh                ← Core isolation + IRQ steering
    ├-- huge_pages.sh                  ← Huge page pre-allocation
    └-- network_tuning.sh             ← NIC optimization
```

---

## Build Instructions

### C Data Plane

```bash
cd hft/c_data_plane
mkdir build && cd build

# Development (stub EF_VI, any platform)
cmake -DCMAKE_BUILD_TYPE=Release ..
make -j$(nproc)
./hft_demo

# Production (real Solarflare SDK, Linux only)
cmake -DCMAKE_BUILD_TYPE=Release -DEFVI_PRODUCTION=ON ..
make -j$(nproc)
```

### Java Orchestration

```bash
cd hft/java_orchestration

# Compile
mvn clean compile

# Package (includes dependencies)
mvn clean package -DskipTests

# Run JMH benchmarks
mvn clean install
java -jar target/benchmarks.jar
```

---

## Key Design Decisions

### Why C for the Data Plane?

The feed handler and OEG require:
- **Zero-copy packet access** via EF_VI's DMA buffer model
- **SIMD intrinsics** (AVX2/AVX-512) for ITCH parsing
- **Deterministic memory layout** — no GC, no JIT, predictable cache behavior
- **Kernel bypass** — EF_VI is a C API; JNI overhead would negate the benefit

### Why Java for Orchestration?

- **LMAX Disruptor** is a Java library (the canonical implementation)
- **Chronicle Queue** is a Java library
- **Mechanical sympathy** is achievable with `sun.misc.Unsafe` + off-heap allocation
- **JIT compilation** (C2) produces code competitive with hand-tuned C for business logic
- **Development velocity** — faster iteration on strategy/risk logic

### Why Not C++ Everywhere?

- Lock-free data structures in C++ require careful attention to object lifetimes
- `std::atomic` semantics are correct but the standard library containers (map, vector) allocate
- The Disruptor pattern is more naturally expressed in Java with its managed-but-controllable memory model
- The team's core competency spans both — we use each where it excels

### Memory Ordering: Why Acquire-Release, Not Sequential Consistency?

The SPSC ring buffer uses `acquire-release` ordering (not `seq_cst`) because:
1. **SPSC topology** — exactly one writer per index, so total store order is irrelevant
2. **No third-party observer** — no thread reads both head AND tail and requires consistency between them
3. **Performance** — `seq_cst` emits an `MFENCE` on x86 (~20-50 cycles); `release` is free (x86 stores are inherently ordered)

---

## Quantitative Models

| Model | Purpose | Complexity | Reference |
|-------|---------|-----------|-----------|
| Hawkes Process | Trade intensity / toxicity detection | O(1) per trade | Hawkes (1971), Bacry et al. (2015) |
| Order Book Imbalance | Directional pressure prediction | O(1) per LOB update | Cont et al. (2014) |
| Micro-Price | True price estimation | O(1) per LOB update | Stoikov (2010) |
| HMM Regime Filter | Momentum vs. mean-revert classification | O(1) per event | Baum-Welch (1970) |
| Avellaneda-Stoikov | Inventory-penalized quoting | Offline calibration | Avellaneda & Stoikov (2008) |

Full derivations: [`docs/quantitative_models.md`](docs/quantitative_models.md)

---

## Production Deployment

1. **Hardware:** Dual Intel Xeon Ice Lake-SP, Solarflare SFN8522, 128GB DDR4
2. **OS:** Linux 5.15+ with `isolcpus`, `nohz_full`, `rcu_nocbs`
3. **Pre-flight:**
   ```bash
   sudo ./scripts/huge_pages.sh
   sudo ./scripts/cpu_affinity.sh
   sudo ./scripts/network_tuning.sh enp1s0f0
   ```
4. **Start C feed handler** (Core 1)
5. **Start Java orchestration** (Cores 4-8, 10-13, 15):
   ```bash
   ./scripts/jvm_startup.sh
   ```
6. **Monitor:** Prometheus + Grafana dashboards via telemetry tailer

---

## References

- Hawkes, A.G. (1971). "Spectra of some self-exciting and mutually exciting point processes." *Biometrika*
- Glosten, L.R. & Milgrom, P.R. (1985). "Bid, ask and transaction prices." *Journal of Financial Economics*
- Kyle, A.S. (1985). "Continuous auctions and insider trading." *Econometrica*
- Avellaneda, M. & Stoikov, S. (2008). "High-frequency trading in a limit order book." *Quantitative Finance*
- Cont, R., Kukanov, A., & Stoikov, S. (2014). "The price impact of order book events." *Journal of Financial Econometrics*
- Almgren, R. & Chriss, N. (2001). "Optimal execution of portfolio transactions." *Journal of Risk*
- LMAX Exchange. "Disruptor: High-Performance Inter-Thread Messaging." *lmax-exchange.github.io/disruptor*
- Solarflare Communications. "EF_VI User Guide." *Xilinx/AMD*
