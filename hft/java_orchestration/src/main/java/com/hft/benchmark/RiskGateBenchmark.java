package com.hft.benchmark;

import com.hft.core.MdEvent;
import com.hft.risk.PreTradeRiskGateway;
import com.hft.signal.HawkesIntensityEstimator;
import com.hft.signal.HMMRegimeFilter;
import com.hft.oeg.OrderConstructor;
import sun.misc.Unsafe;

import org.openjdk.jmh.annotations.*;
import org.openjdk.jmh.runner.Runner;
import org.openjdk.jmh.runner.options.Options;
import org.openjdk.jmh.runner.options.OptionsBuilder;
import java.util.concurrent.TimeUnit;

/**
 * JMH Benchmark Harnesses — Latency Profiling
 *
 * Benchmarks every hot-path component to verify compliance with the
 * latency budget:
 *   - Risk gate (all 5 checks): ≤ 200ns P99
 *   - Hawkes intensity update: ≤ 50ns P99
 *   - HMM forward step: ≤ 30ns P99
 *   - SBE order construction: ≤ 40ns P99
 *
 * Run: mvn clean install && java -jar target/benchmarks.jar
 * Or:  java -cp target/classes:target/test-classes org.openjdk.jmh.Main
 *
 * <p><b>JMH Configuration Rationale:</b></p>
 * <ul>
 *   <li>{@code Mode.SampleTime}: captures P50/P99/P999 latency distribution,
 *       not just throughput</li>
 *   <li>{@code TimeUnit.NANOSECONDS}: matches our latency budget units</li>
 *   <li>{@code Warmup(5, 1s)}: 5 seconds total warmup ensures JIT C2 compilation
 *       is complete (verified via -XX:+PrintCompilation)</li>
 *   <li>{@code Fork(1)}: single fork is sufficient for Unsafe-heavy code;
 *       multiple forks add no information since our code has no classloader deps</li>
 * </ul>
 */
@State(Scope.Thread)
@BenchmarkMode(Mode.SampleTime)
@OutputTimeUnit(TimeUnit.NANOSECONDS)
@Warmup(iterations = 5, time = 1, timeUnit = TimeUnit.SECONDS)
@Measurement(iterations = 10, time = 1, timeUnit = TimeUnit.SECONDS)
@Fork(1)
public class RiskGateBenchmark {

    private PreTradeRiskGateway riskGateway;
    private HawkesIntensityEstimator hawkes;
    private HMMRegimeFilter hmm;
    private OrderConstructor orderConstructor;

    /* Pre-computed test values to avoid allocation in benchmark loop */
    private long testPrice;
    private int testQuantity;
    private long testTimestampNs;
    private long testObiFixed;

    @Setup(Level.Trial)
    public void setup() {
        riskGateway = new PreTradeRiskGateway();
        hawkes = new HawkesIntensityEstimator(0.001, 0.0008, 0.001, 0.005, 0.3);
        hmm = new HMMRegimeFilter(
            0.95, 0.93,
            0.0, 0.0, 0.04, 0.5, 0.0,
            0.15, 1.5, 0.09, 1.0, 0.05
        );
        orderConstructor = new OrderConstructor(42, (byte) '1', (short) 1);

        testPrice = 15000000000L;    /* $150.00 in fixed-point 8dp */
        testQuantity = 100;
        testTimestampNs = 34200000000000L;  /* 09:30:00 */
        testObiFixed = 30000000L;    /* 0.30 OBI in fixed-point */
    }

    @TearDown(Level.Trial)
    public void teardown() {
        orderConstructor.destroy();
    }

    /**
     * Benchmark: Pre-Trade Risk Gateway (all 5 checks).
     * Target: ≤ 200ns P99
     */
    @Benchmark
    public String riskGate_allChecks() {
        return riskGateway.checkOrder(testPrice, testQuantity, true);
    }

    /**
     * Benchmark: Hawkes O(1) recursive intensity update.
     * Target: ≤ 50ns P99
     */
    @Benchmark
    public void hawkes_onTrade() {
        testTimestampNs += 1000;  /* 1μs between trades */
        hawkes.onTrade(testTimestampNs);
    }

    /**
     * Benchmark: Hawkes intensity query (no new trade).
     * Target: ≤ 20ns P99
     */
    @Benchmark
    public double hawkes_getIntensity() {
        return hawkes.getIntensityAt(testTimestampNs + 500);
    }

    /**
     * Benchmark: HMM forward step (bivariate Gaussian emission + log-sum-exp).
     * Target: ≤ 30ns P99
     */
    @Benchmark
    public void hmm_forwardStep() {
        hmm.update(0.15, 1.2);
    }

    /**
     * Benchmark: HMM regime posterior retrieval.
     * Target: ≤ 5ns P99
     */
    @Benchmark
    public double hmm_getPosterior() {
        return hmm.getMomentumPosterior();
    }

    /**
     * Benchmark: SBE order construction (template patch).
     * Target: ≤ 40ns P99
     */
    @Benchmark
    public long orderConstruct_buildOrder() {
        return orderConstructor.buildOrder(testPrice, testQuantity);
    }

    /**
     * Benchmark: Hawkes signal generation (intensity check + OBI confirmation).
     * Target: ≤ 10ns P99
     */
    @Benchmark
    public int hawkes_generateSignal() {
        return hawkes.generateSignal(testObiFixed);
    }

    /**
     * Benchmark: Combined signal pipeline (Hawkes + HMM gate).
     * Target: ≤ 80ns P99
     */
    @Benchmark
    public int combinedSignal_hawkesAndHMM() {
        testTimestampNs += 1000;
        hawkes.onTrade(testTimestampNs);
        hmm.update(0.15, Math.log(hawkes.getLambda() / hawkes.getMu0()));
        int signal = hawkes.generateSignal(testObiFixed);
        return hmm.gateSignal(signal);
    }

    /* --- Runner --- */

    public static void main(String[] args) throws Exception {
        Options opt = new OptionsBuilder()
                .include(RiskGateBenchmark.class.getSimpleName())
                .forks(1)
                .build();
        new Runner(opt).run();
    }
}
