# Deliverable A — System Architecture

## A.1 Tick-to-Trade Pipeline

```mermaid
graph TD
    subgraph "NUMA Node 0 — NIC-Local (Cores 1-3 isolated)"
        EX["Exchange Multicast Feed<br/>UDP/IP Multicast<br/>Nasdaq ITCH 5.0 / OUCH"]
        NIC["Solarflare SFN8522 NIC<br/>EF_VI Recv Ring (DMA)<br/>Huge-page-backed RX buffers"]
        FH["Zero-Copy Feed Handler (C)<br/>SIMD ITCH 5.0 Parser<br/>AVX-512 branchless dispatch<br/><b>Core 1 — isolcpus</b>"]
        RING["Lock-Free SPSC Ring Buffer (C)<br/>Cache-line-padded head/tail<br/>2MB huge-page mmap<br/>1M × 64B = 64MB"]
    end

    subgraph "NUMA Node 1 — RAM-Local (Cores 4-9 isolated)"
        MMAP["Shared Memory Bridge<br/>mmap(MAP_SHARED) region<br/>Java Unsafe.getLong() acquire"]
        DISR["LMAX Disruptor RingBuffer‹MdEvent›<br/>1 << 20 slots, off-heap<br/>BusySpinWaitStrategy<br/><b>Core 4 — Producer</b>"]
        LOB["LOB Reconstruction Thread<br/>Off-heap long[] price arrays<br/>Delta-patch + binary search<br/><b>Core 5 — isolcpus</b>"]
        FEAT["Feature Extraction Thread<br/>OBI, Microprice (fixed-point)<br/>Hawkes λ(t) O(1) recursive<br/>HMM regime posterior<br/><b>Core 6 — isolcpus</b>"]
        RISK["Pre-Trade Risk Gateway<br/>AtomicLong CAS position/notional<br/>Token bucket rate throttle<br/>Fat finger + drawdown CB<br/><b>Core 7 — isolcpus</b>"]
        STRAT["Strategy Evaluation Thread<br/>HMM regime → Hawkes signal<br/>→ OBI confirmation<br/>Composite decision engine<br/><b>Core 7 — shared</b>"]
        ORD["Order Constructor (Java)<br/>SBE message builder<br/>Zero-alloc template patch<br/><b>Core 8 — isolcpus</b>"]
    end

    subgraph "NUMA Node 0 — NIC-Local (Core 2 isolated)"
        OEG["Order Entry Gateway (C)<br/>ef_vi_transmit() kernel-bypass<br/>Pre-built SBE frame patch<br/>HW TX timestamp<br/><b>Core 2 — isolcpus</b>"]
    end

    subgraph "NUMA Node 0 — NIC-Local (Core 3 isolated)"
        ERH["Execution Report Handler<br/>Fill reconciliation<br/>Position + P&L mark<br/><b>Core 3 — isolcpus</b>"]
    end

    subgraph "Non-Isolated Cores (10-15) — Latency-Insensitive"
        CQ["Chronicle Queue<br/>Memory-mapped journaling<br/>MdEvent + FeatureVector +<br/>OrderEvent + ExecReport"]
        MON["Real-Time Risk Monitor<br/>Greeks aggregation<br/>Drawdown circuit breaker<br/>Prometheus metrics export"]
        TEL["Telemetry & Compliance<br/>Grafana dashboard feed<br/>Regulatory audit trail"]
    end

    EX -->|"Raw UDP multicast frames<br/>≤ 0ns (wire)"| NIC
    NIC -->|"DMA write → huge-page buffer<br/>Zero-copy ef_vi_receive_get_bytes()<br/>≤ 120ns | Raw Ethernet frame"| FH
    FH -->|"Parse + write to ring slot<br/>__builtin_prefetch(write_ptr)<br/>≤ 15ns/msg | MdEvent struct (64B)"| RING
    RING -->|"Shared mmap region<br/>Acquire/Release atomic semantics<br/>≤ 20ns | MdEvent (off-heap)"| MMAP
    MMAP -->|"Unsafe.getLong() acquire load<br/>≤ 10ns | base address offset read"| DISR
    DISR -->|"Disruptor sequence barrier<br/>BusySpinWaitStrategy<br/>≤ 50ns | MdEvent slot reference"| LOB
    LOB -->|"Disruptor diamond dependency<br/>Parallel consumer chain<br/>≤ 80ns | FeatureVector (off-heap)"| FEAT
    FEAT -->|"Direct off-heap write<br/>Pre-allocated FeatureVector<br/>≤ 130ns | Signal struct"| RISK
    RISK -->|"Atomic CAS gate pass/reject<br/>≤ 150ns | OrderRequest"| STRAT
    STRAT -->|"Order decision + params<br/>≤ 10ns | OrderParams struct"| ORD
    ORD -->|"SBE frame → shared memory<br/>Template patch (4 fields)<br/>≤ 40ns | SBE OrderFrame"| OEG
    OEG -->|"ef_vi_transmit() → co-lo cross-connect<br/>HW TX timestamp capture<br/>≤ 100ns | Raw TCP/SBE frame"| EX
    ERH -->|"Fill notification parse<br/>Position delta update"| MON

    LOB -.->|"Async write<br/>ExcerptAppender"| CQ
    FEAT -.->|"Async write"| CQ
    ORD -.->|"Async write"| CQ
    ERH -.->|"Async write"| CQ
    CQ -.->|"ExcerptTailer<br/>Sequential read"| MON
    CQ -.->|"ExcerptTailer"| TEL

    style EX fill:#1a1a2e,stroke:#e94560,color:#fff
    style NIC fill:#16213e,stroke:#0f3460,color:#fff
    style FH fill:#0f3460,stroke:#533483,color:#fff
    style RING fill:#533483,stroke:#e94560,color:#fff
    style MMAP fill:#2d3436,stroke:#6c5ce7,color:#fff
    style DISR fill:#6c5ce7,stroke:#a29bfe,color:#fff
    style LOB fill:#00b894,stroke:#00cec9,color:#fff
    style FEAT fill:#fdcb6e,stroke:#e17055,color:#000
    style RISK fill:#d63031,stroke:#e17055,color:#fff
    style STRAT fill:#e17055,stroke:#fab1a0,color:#fff
    style ORD fill:#0984e3,stroke:#74b9ff,color:#fff
    style OEG fill:#e94560,stroke:#ff6b6b,color:#fff
    style ERH fill:#636e72,stroke:#b2bec3,color:#fff
    style CQ fill:#2d3436,stroke:#636e72,color:#fff
    style MON fill:#2d3436,stroke:#636e72,color:#fff
    style TEL fill:#2d3436,stroke:#636e72,color:#fff
```

---

## A.2 Chronicle Queue Journaling Fan-Out (Latency-Insensitive Path)

```mermaid
graph LR
    subgraph "Hot Path — Isolated Cores"
        LOB2["LOB Handler"]
        FEAT2["Feature Extractor"]
        ORD2["Order Constructor"]
        ERH2["Exec Report Handler"]
    end

    subgraph "Chronicle Queue — Memory-Mapped Files"
        CQ_MD["chronicle-md/<br/>MdEvent journal<br/>Append: O(1) via MappedFile"]
        CQ_FV["chronicle-feat/<br/>FeatureVector journal"]
        CQ_ORD["chronicle-order/<br/>OrderEvent journal"]
        CQ_EXEC["chronicle-exec/<br/>ExecutionReport journal"]
    end

    subgraph "Async Tailers — Non-Isolated Cores 10-15"
        T_PNL["P&L Aggregation Tailer<br/>Real-time mark-to-market<br/>Greeks aggregation<br/><b>Core 10</b>"]
        T_TELEM["Telemetry Export Tailer<br/>Prometheus push gateway<br/>Latency histograms<br/><b>Core 11</b>"]
        T_COMP["Compliance Tailer<br/>Regulatory audit trail<br/>Order-to-fill reconciliation<br/><b>Core 12</b>"]
        T_CALIB["Calibration Replay Tailer<br/>Nightly Hawkes MLE<br/>HMM Baum-Welch EM<br/>OBI RLS recalibration<br/><b>Core 13</b>"]
        T_RECOV["Recovery Tailer<br/>Startup LOB reconstruction<br/>Position reconciliation<br/><b>On-demand</b>"]
    end

    subgraph "External Systems"
        GRAF["Grafana Dashboard<br/>via Prometheus"]
        ALERT["Alert System<br/>Circuit breaker notifications"]
        STORE["Long-Term Storage<br/>Compressed archive"]
    end

    LOB2 -->|"ExcerptAppender<br/>wire.write().int64()"| CQ_MD
    FEAT2 -->|"ExcerptAppender"| CQ_FV
    ORD2 -->|"ExcerptAppender"| CQ_ORD
    ERH2 -->|"ExcerptAppender"| CQ_EXEC

    CQ_MD -->|"ExcerptTailer"| T_PNL
    CQ_FV -->|"ExcerptTailer"| T_PNL
    CQ_EXEC -->|"ExcerptTailer"| T_PNL
    CQ_MD -->|"ExcerptTailer"| T_TELEM
    CQ_ORD -->|"ExcerptTailer"| T_COMP
    CQ_EXEC -->|"ExcerptTailer"| T_COMP
    CQ_MD -->|"ExcerptTailer"| T_CALIB
    CQ_FV -->|"ExcerptTailer"| T_CALIB
    CQ_MD -->|"ExcerptTailer"| T_RECOV
    CQ_EXEC -->|"ExcerptTailer"| T_RECOV

    T_PNL --> ALERT
    T_TELEM --> GRAF
    T_COMP --> STORE

    style CQ_MD fill:#2d3436,stroke:#636e72,color:#fff
    style CQ_FV fill:#2d3436,stroke:#636e72,color:#fff
    style CQ_ORD fill:#2d3436,stroke:#636e72,color:#fff
    style CQ_EXEC fill:#2d3436,stroke:#636e72,color:#fff
```

**Chronicle Queue Design Notes:**
- `MappedFile` provides `O(1)` append via memory-mapped page cache — no serialization overhead
- `ExcerptAppender.startExcerpt()` + `finish()` operates on pre-allocated mapped pages — **zero heap allocation** in the hot path
- Each journal is a separate Chronicle Queue instance to avoid contention between appenders
- Tailers are fully independent — each maintains its own read index; no coordination with appenders
- Recovery path replays from the last known good sequence number, reconstructing LOB state and open positions tick-by-tick

---

## A.3 NUMA Topology & Thread Affinity Map

```mermaid
graph TB
    subgraph "Server: Dual Intel Xeon Ice Lake-SP"
        subgraph "NUMA Node 0 — NIC-Local"
            direction TB
            PCIe["PCIe Root Complex 0"]
            NIC_HW["Solarflare SFN8522<br/>Dual-port 10GbE"]
            C1["<b>Core 1</b> (isolated)<br/>Feed Handler + ITCH Parser<br/>ef_vi poll loop"]
            C2["<b>Core 2</b> (isolated)<br/>Order Entry Gateway<br/>ef_vi transmit"]
            C3["<b>Core 3</b> (isolated)<br/>Execution Report Handler<br/>Fill reconciliation"]
            MEM0["DDR4 Local Memory<br/>Huge-page DMA buffers<br/>SPSC Ring Buffer<br/>SBE frame templates"]

            PCIe --- NIC_HW
            NIC_HW -.->|"DMA"| MEM0
            C1 ---|"reads"| MEM0
            C2 ---|"writes"| MEM0
            C3 ---|"reads"| MEM0
        end

        subgraph "NUMA Node 1 — RAM-Local"
            direction TB
            C4["<b>Core 4</b> (isolated)<br/>Disruptor Producer<br/>mmap bridge read"]
            C5["<b>Core 5</b> (isolated)<br/>LOB Reconstruction<br/>Off-heap price arrays"]
            C6["<b>Core 6</b> (isolated)<br/>Feature Extraction<br/>Hawkes + HMM"]
            C7["<b>Core 7</b> (isolated)<br/>Strategy + Risk Gate<br/>Atomic CAS checks"]
            C8["<b>Core 8</b> (isolated)<br/>Order Constructor<br/>SBE template patch"]
            MEM1["DDR4 Local Memory<br/>Disruptor Ring (64MB)<br/>LOB price arrays<br/>FeatureVector pool<br/>HMM parameter cache"]

            C4 ---|"reads/writes"| MEM1
            C5 ---|"reads/writes"| MEM1
            C6 ---|"reads/writes"| MEM1
            C7 ---|"reads/writes"| MEM1
            C8 ---|"reads/writes"| MEM1
        end

        subgraph "Non-Isolated Cores (10-15)"
            C10["Core 10: P&L Tailer"]
            C11["Core 11: Telemetry"]
            C12["Core 12: Compliance"]
            C13["Core 13: Calibration"]
            C14["Core 14: OS + IRQ"]
            C15["Core 15: JVM GC (ZGC)"]
        end

        MEM0 ===|"QPI/UPI Interconnect<br/>~80ns cross-node latency<br/>mmap(MAP_SHARED) region"| MEM1
    end

    style NIC_HW fill:#e94560,stroke:#ff6b6b,color:#fff
    style C1 fill:#0f3460,color:#fff
    style C2 fill:#e94560,color:#fff
    style C3 fill:#636e72,color:#fff
    style C4 fill:#6c5ce7,color:#fff
    style C5 fill:#00b894,color:#fff
    style C6 fill:#fdcb6e,color:#000
    style C7 fill:#d63031,color:#fff
    style C8 fill:#0984e3,color:#fff
```

**NUMA Design Rationale:**
- **Node 0 houses all NIC-touching threads** — DMA buffers are allocated on this node via `mmap(MAP_HUGETLB)` with `mbind(MPOL_BIND, node=0)`. The feed handler and OEG read/write these buffers without cross-node memory access.
- **Node 1 houses all strategy computation** — the Disruptor ring, LOB arrays, and feature vectors are allocated here. The JVM is started with `-XX:+UseNUMA` and strategy threads are pinned to node 1 cores, ensuring all Unsafe off-heap reads hit local DRAM.
- **Cross-node boundary** is the SPSC ring buffer in shared mmap — this is a single 64MB region with well-defined producer (node 0, core 1) and consumer (node 1, core 4). The acquire/release semantics on the head/tail indices ensure coherence without excessive QPI traffic; batch publication further reduces cross-node stores.
- **ZGC threads** are pinned to core 15 (non-isolated) — even though the hot path is zero-allocation, the JVM housekeeping (class loading, JIT compilation) still needs GC. ZGC's concurrent collection prevents STW pauses from reaching the isolated cores.

---

## A.4 Latency Budget Summary

| # | Stage | Transport | Budget (ns) | Data Format | Core |
|---|-------|-----------|-------------|-------------|------|
| 1 | NIC RX → DMA buffer | EF_VI poll + zero-copy | ≤ 120 | Raw Ethernet/UDP | 1 |
| 2 | ITCH parse | SIMD AVX-512 dispatch | ≤ 15/msg | MdEvent struct | 1 |
| 3 | Ring buffer write | SPSC release-store | ≤ 10 | MdEvent (64B) | 1 |
| 4 | C→Java boundary | mmap acquire-load | ≤ 20 | Off-heap base addr | 4 |
| 5 | Disruptor dispatch | BusySpinWaitStrategy | ≤ 50 | MdEvent slot ref | 4 |
| 6 | LOB reconstruction | Off-heap delta patch | ≤ 80 | Price/qty arrays | 5 |
| 7 | Feature extraction | LUT exp + fixed-point | ≤ 100 | FeatureVector | 6 |
| 8 | HMM forward step | Unrolled log-sum-exp | ≤ 30 | Regime posterior | 6 |
| 9 | Risk gate (all checks) | Atomic CAS + token bucket | ≤ 150 | Pass/reject | 7 |
| 10 | SBE order construction | Template patch + memcpy | ≤ 40 | SBE frame | 8 |
| 11 | OEG kernel-bypass TX | ef_vi_transmit() | ≤ 100 | TCP/SBE on wire | 2 |
| | **Total P50** | | **≤ 705** | | |
| | **Total P99** | | **≤ 800** | | |

**Measurement methodology:** Stages 1-3 and 10-11 measured via `RDTSC` delta on isolated cores; stages 4-9 measured via JMH `@Benchmark` with `@BenchmarkMode(Mode.SampleTime)` and `@OutputTimeUnit(TimeUnit.NANOSECONDS)`.
