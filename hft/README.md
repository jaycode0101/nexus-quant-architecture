# Optional Systems Track

This directory contains the lower-level systems experiments for
`nexus-quant-architecture`.

It is not required for the Python research workflow. Keep using the Python layer
if your work is backtesting, portfolio research, signal design, or paper
execution on bar data.

Use this directory when you want to study tick-level ingestion, fixed binary
layouts, lock-free handoff, event pipelines, and microstructure features.

## Current Shape

```text
hft/
  c_data_plane/
    include/
      md_event.h        - normalized event layout
      spsc_ring.h       - single-producer/single-consumer ring buffer
      itch_parser.h     - feed parser interface
    src/
      main.c            - local integration demo
      itch_parser.c     - parser implementation
      ef_vi_receiver.c  - receiver abstraction and stubs

  java_orchestration/
    src/main/java/com/hft/
      core/             - event flyweight and shared-memory bridge
      lob/              - order book reconstruction
      signal/           - Hawkes intensity and HMM regimes
      risk/             - pre-trade risk gate experiments
      benchmark/        - JMH latency harness
```

## Design Intent

The systems track models a split trading architecture:

```text
feed adapter -> C11 normalizer -> shared ring -> Java event pipeline
                                                |
                                                v
                                      Python strategy layer
```

The boundary is the point. Python should not care whether a feature came from a
CSV file, a broker feed, or the C11/Java path. It should receive normalized
market events and produce strategy decisions through the same interface.

## C11 Data Plane

The C layer is used for:

- stable binary layouts
- cache-aware event structs
- single-producer/single-consumer ring-buffer experiments
- feed-parser experiments behind adapter interfaces
- deterministic handoff into shared memory

This is where low-level mechanics belong. It is intentionally kept away from
research code.

## Java Orchestration

The Java layer is used for:

- LMAX Disruptor-style event sequencing
- order book reconstruction
- Hawkes process intensity updates
- HMM regime filtering
- pre-trade risk gate experiments
- JMH benchmarks

The Java code is the event-processing layer, not the place to write portfolio
research notebooks.

## Build

### C11

```bash
cd hft/c_data_plane
cmake -B build
cmake --build build
```

### Java

```bash
cd hft/java_orchestration
mvn test
```

### Benchmarks

```bash
cd hft/java_orchestration
mvn -DskipTests package
java -jar target/benchmarks.jar
```

Benchmark numbers should only be published with:

- commit hash
- compiler/runtime versions
- hardware summary
- warmup settings
- sample count
- p50/p95/p99 latency
- notes about what was measured

Numbers without methodology are just decoration.

## Integration Status

The goal is:

```text
C11 normalized event -> Java bridge/enrichment -> Python shared-memory reader
```

The Python strategy layer should then treat microstructure signals like any
other feature source.

Until the end-to-end bridge has tests, this systems path is experimental.

## References

- LMAX Disruptor pattern for event pipelines
- Hawkes processes for self-exciting market events
- Hidden Markov Models for regime classification
- Avellaneda-Stoikov quoting for inventory-aware market making
- SPSC ring buffers for bounded single-writer/single-reader handoff
