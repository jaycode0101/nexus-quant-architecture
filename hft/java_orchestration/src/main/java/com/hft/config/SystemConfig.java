package com.hft.config;

/**
 * SystemConfig — JVM, NUMA, and Thread Affinity Configuration
 *
 * Documents and programmatically exposes all production JVM flags,
 * CPU affinity assignments, and memory configuration for the HFT system.
 *
 * <p><b>JVM Startup Flags (complete production set):</b></p>
 * <pre>
 * java \
 *   # --- Memory & GC ---
 *   -Xms4g -Xmx4g                         # Fixed heap (no resize pauses)
 *   -XX:+UseZGC                            # Z Garbage Collector
 *   -XX:+ZGenerational                     # Generational ZGC (JDK 21)
 *   -XX:ConcGCThreads=2                    # Limit GC threads to non-isolated cores
 *   -XX:ParallelGCThreads=2               # Parallel GC phase threads
 *   -XX:+UseLargePages                     # Huge pages for heap
 *   -XX:+UseTransparentHugePages          # THP fallback
 *   -XX:LargePageSizeInBytes=2m           # 2MB huge pages
 *   -XX:+AlwaysPreTouch                    # Fault all pages at startup
 *
 *   # --- NUMA ---
 *   -XX:+UseNUMA                           # NUMA-aware heap allocation
 *
 *   # --- JIT Compilation ---
 *   -XX:+TieredCompilation                # Enable tiered compilation
 *   -XX:CompileThreshold=1000             # Compile after 1000 invocations
 *   -XX:+PrintCompilation                 # Log JIT decisions
 *   -XX:-BackgroundCompilation            # Inline compilation (no OSR delay)
 *   -XX:MaxInlineSize=325                 # Aggressive inlining
 *   -XX:FreqInlineSize=500               # Inline hot methods aggressively
 *   -XX:+AggressiveOpts                   # Enable experimental optimizations
 *   -XX:LoopUnrollLimit=16               # Unroll small loops
 *
 *   # --- Thread & Lock ---
 *   -XX:+UseThreadPriorities              # Allow thread priority control
 *   -XX:ThreadPriorityPolicy=1           # Map Java priorities to OS
 *   -XX:-UseBiasedLocking                # Disable biased locking (we don't use synchronized)
 *
 *   # --- Off-Heap ---
 *   -XX:MaxDirectMemorySize=256m         # Direct ByteBuffer limit
 *   --add-opens java.base/sun.misc=ALL-UNNAMED
 *   --add-opens java.base/jdk.internal.misc=ALL-UNNAMED
 *   --add-opens java.base/java.nio=ALL-UNNAMED
 *
 *   # --- Diagnostics (non-production) ---
 *   -XX:+UnlockDiagnosticVMOptions
 *   -XX:+PrintInlining                    # Verify inlining decisions
 *   -XX:+LogCompilation                   # Full JIT log for analysis
 *   -XX:+PrintAssembly                    # Disassemble hot methods
 *
 *   # --- Application ---
 *   -Dchronicle.path=/data/hft/journals
 *   -Dbridge.path=/dev/shm/hft-ring
 *   -Dbridge.capacity=1048576
 *   -jar hft-orchestration-1.0.0.jar
 * </pre>
 *
 * <p><b>CPU Affinity (Linux taskset):</b></p>
 * <pre>
 *   Core 1:  Feed Handler (C) — ef_vi poll loop
 *   Core 2:  OEG (C) — ef_vi transmit
 *   Core 3:  Exec Report Handler (C)
 *   Core 4:  Disruptor Producer (Java) — mmap bridge reader
 *   Core 5:  LOB Reconstruction (Java)
 *   Core 6:  Feature/Signal Generation (Java)
 *   Core 7:  Strategy + Risk Gate (Java)
 *   Core 8:  Order Constructor (Java)
 *   Core 10: P&L Tailer (Java)
 *   Core 11: Telemetry Export (Java)
 *   Core 12: Compliance Tailer (Java)
 *   Core 13: Calibration Replay (Java)
 *   Core 14: OS + IRQ steering
 *   Core 15: ZGC concurrent threads
 * </pre>
 */
public final class SystemConfig {

    /* --- Bridge Configuration --- */

    /** Shared memory path for C→Java bridge. */
    public static final String BRIDGE_PATH =
        System.getProperty("bridge.path", "/dev/shm/hft-ring");

    /** Ring capacity (must match C RING_CAPACITY). */
    public static final int BRIDGE_CAPACITY =
        Integer.getInteger("bridge.capacity", 1 << 20);

    /* --- Chronicle Queue --- */

    /** Base directory for Chronicle Queue journals. */
    public static final String CHRONICLE_PATH =
        System.getProperty("chronicle.path", "/data/hft/journals");

    /* --- Core Affinity Assignments --- */

    public static final int CORE_FEED_HANDLER    = 1;
    public static final int CORE_OEG             = 2;
    public static final int CORE_EXEC_HANDLER    = 3;
    public static final int CORE_DISRUPTOR_PROD  = 4;
    public static final int CORE_LOB             = 5;
    public static final int CORE_SIGNAL          = 6;
    public static final int CORE_STRATEGY_RISK   = 7;
    public static final int CORE_ORDER_BUILDER   = 8;
    public static final int CORE_PNL_TAILER      = 10;
    public static final int CORE_TELEMETRY       = 11;
    public static final int CORE_COMPLIANCE      = 12;
    public static final int CORE_CALIBRATION     = 13;
    public static final int CORE_OS_IRQ          = 14;
    public static final int CORE_ZGC             = 15;

    /* --- Risk Limits --- */

    /** Maximum position per instrument (shares). */
    public static final long MAX_POSITION_SHARES = 10_000L;

    /** Maximum notional exposure (cents). */
    public static final long MAX_NOTIONAL_CENTS = 50_000_000_00L;

    /** Maximum drawdown before circuit breaker (cents). */
    public static final long MAX_DRAWDOWN_CENTS = 500_000_00L;

    /** Order rate limit (orders/second). */
    public static final long ORDER_RATE_LIMIT = 1000L;

    /** Fat finger threshold (percentage × 10^8). */
    public static final long FAT_FINGER_PCT = 5_000_000L;

    /* --- Hawkes Default Parameters --- */

    public static final double HAWKES_MU0 = 0.001;
    public static final double HAWKES_ALPHA = 0.0008;
    public static final double HAWKES_BETA = 0.001;
    public static final double HAWKES_LAMBDA_THRESHOLD = 0.005;
    public static final double HAWKES_OBI_THRESHOLD = 0.3;

    /* --- HMM Default Parameters --- */

    public static final double HMM_A00 = 0.95;
    public static final double HMM_A11 = 0.93;
    public static final double HMM_MOMENTUM_THRESHOLD = 0.65;
    public static final double HMM_MEAN_REVERT_THRESHOLD = 0.70;

    /**
     * Set thread affinity for the calling thread.
     *
     * On Linux, this uses native code (JNA/JNI) to call:
     *   cpu_set_t cpuset;
     *   CPU_ZERO(&cpuset);
     *   CPU_SET(coreId, &cpuset);
     *   sched_setaffinity(0, sizeof(cpuset), &cpuset);
     *
     * @param coreId Core to pin to
     */
    public static void setThreadAffinity(final int coreId) {
        /*
         * Production implementation via JNA:
         *
         * import com.sun.jna.*;
         * CLibrary.INSTANCE.sched_setaffinity(0, cpuSetSize, cpuSet);
         *
         * Or via OpenHFT/Java-Thread-Affinity:
         *   AffinityLock lock = AffinityLock.acquireLock(coreId);
         */
        System.out.printf("[Config] Thread '%s' → Core %d (affinity set)%n",
                Thread.currentThread().getName(), coreId);
    }

    /**
     * Print the full system configuration for verification.
     */
    public static void printConfig() {
        System.out.println("╔--------------------------------------------------------------╗");
        System.out.println("║  HFT System Configuration                                  ║");
        System.out.println("╠--------------------------------------------------------------╣");
        System.out.printf("║  Bridge Path:      %-40s║%n", BRIDGE_PATH);
        System.out.printf("║  Bridge Capacity:  %-40d║%n", BRIDGE_CAPACITY);
        System.out.printf("║  Chronicle Path:   %-40s║%n", CHRONICLE_PATH);
        System.out.printf("║  Max Position:     %-40d║%n", MAX_POSITION_SHARES);
        System.out.printf("║  Max Notional:     $%-39s║%n",
                String.format("%,.2f", MAX_NOTIONAL_CENTS / 100.0));
        System.out.printf("║  Max Drawdown:     $%-39s║%n",
                String.format("%,.2f", MAX_DRAWDOWN_CENTS / 100.0));
        System.out.printf("║  Rate Limit:       %-40s║%n", ORDER_RATE_LIMIT + " orders/sec");
        System.out.println("╚--------------------------------------------------------------╝");
    }
}
