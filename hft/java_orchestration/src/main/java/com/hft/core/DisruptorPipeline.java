package com.hft.core;

import com.lmax.disruptor.*;
import com.lmax.disruptor.dsl.Disruptor;
import com.lmax.disruptor.dsl.ProducerType;
import sun.misc.Unsafe;

import com.hft.lob.LOBReconstructionHandler;
import com.hft.signal.SignalGenerationHandler;
import com.hft.risk.PreTradeRiskGateway;
import com.hft.journal.ChronicleJournal;

import java.util.concurrent.ThreadFactory;

/**
 * DisruptorPipeline — LMAX Disruptor 4.x Ring Buffer Orchestration
 *
 * Wires the complete event processing pipeline:
 *
 * <pre>
 *   SharedMemoryBridge (C→Java)
 *     → Disruptor RingBuffer&lt;MdEvent&gt; (1M slots, off-heap)
 *       → LOBReconstructionHandler (consumer 1)
 *         → SignalGenerationHandler (consumer 2, depends on LOB)
 *           → PreTradeRiskGateway (consumer 3, depends on signal)
 *             → ChronicleJournal (async consumer, no dependency)
 * </pre>
 *
 * <p><b>Wait Strategy:</b> {@link BusySpinWaitStrategy} for sub-microsecond
 * dispatch latency. This is appropriate because:</p>
 * <ul>
 *   <li>All consumer threads run on isolated cores — no contention</li>
 *   <li>CPU cores are dedicated (isolcpus) — busy-spin doesn't steal from other work</li>
 *   <li>Target dispatch latency is ≤ 50ns — yielding would add 1-10µs</li>
 * </ul>
 *
 * <p>{@link YieldingWaitStrategy} is acceptable for latency budgets > 1µs
 * (e.g., the telemetry consumer). {@link BlockingWaitStrategy} must NEVER
 * appear in production hot paths — it uses locks and condition variables,
 * adding 5-50µs per wakeup.</p>
 *
 * <p><b>Ring Buffer Allocation:</b> 1 << 20 = 1,048,576 slots. Each slot
 * holds an MdEvent flyweight pointing to a 64-byte off-heap region.
 * Total off-heap: 1M × 64B = 64MB, allocated via Unsafe.allocateMemory().</p>
 */
public final class DisruptorPipeline {

    private static final Unsafe UNSAFE = MdEvent.UNSAFE;

    /** Ring buffer size: 2^20 = 1,048,576 slots. */
    public static final int RING_BUFFER_SIZE = 1 << 20;

    /** Off-heap memory block for all MdEvent data. */
    private final long offHeapBase;
    private final long offHeapSize;

    private final Disruptor<MdEvent> disruptor;
    private final RingBuffer<MdEvent> ringBuffer;

    private final SharedMemoryBridge bridge;
    private final LOBReconstructionHandler lobHandler;
    private final SignalGenerationHandler signalHandler;
    private final PreTradeRiskGateway riskGateway;
    private final ChronicleJournal journal;

    private volatile boolean running;

    /**
     * Construct the pipeline.
     *
     * @param bridgeBaseAddress Base address of the C SPSC ring mmap region
     * @param bridgeCapacity    Capacity of the C SPSC ring (power of 2)
     * @param chroniclePath     Directory for Chronicle Queue journals
     */
    public DisruptorPipeline(final long bridgeBaseAddress,
                             final int bridgeCapacity,
                             final String chroniclePath) {

        this.bridge = new SharedMemoryBridge(bridgeBaseAddress, bridgeCapacity);

        /* --- Allocate off-heap memory for all ring buffer slots --- */
        this.offHeapSize = (long) RING_BUFFER_SIZE * MdEvent.EVENT_SIZE;
        this.offHeapBase = UNSAFE.allocateMemory(offHeapSize);
        UNSAFE.setMemory(offHeapBase, offHeapSize, (byte) 0);

        /* --- Event Factory: pre-allocate MdEvent flyweights ---
         *
         * Each MdEvent is pointed at its own 64-byte off-heap slot.
         * The flyweight objects themselves are on the heap, but they're
         * pre-allocated once at startup and reused — no GC pressure
         * during event processing.
         */
        final long capturedBase = this.offHeapBase;
        EventFactory<MdEvent> factory = () -> {
            MdEvent event = new MdEvent();
            return event;
        };

        /* --- Thread Factory for consumer threads --- */
        ThreadFactory threadFactory = new ThreadFactory() {
            private int counter = 0;
            @Override
            public Thread newThread(Runnable r) {
                Thread t = new Thread(r, "disruptor-consumer-" + counter++);
                t.setDaemon(true);
                return t;
            }
        };

        /* --- Build Disruptor --- */
        this.disruptor = new Disruptor<>(
            factory,
            RING_BUFFER_SIZE,
            threadFactory,
            ProducerType.SINGLE,           /* Single producer from SharedMemoryBridge */
            new BusySpinWaitStrategy()     /* Sub-microsecond dispatch */
        );

        /* --- Initialize Handlers --- */
        this.lobHandler = new LOBReconstructionHandler();
        this.signalHandler = new SignalGenerationHandler();
        this.riskGateway = new PreTradeRiskGateway();
        this.journal = new ChronicleJournal(chroniclePath);

        /* --- Wire Handler Dependencies (Diamond Pattern) ---
         *
         * LOB runs first (reconstructs order book state).
         * Signal depends on LOB (needs microprice, OBI).
         * Risk depends on Signal (needs trading decision).
         * Journal runs independently (async, no dependency).
         *
         *                ┌-- LOB -- Signal -- Risk
         *   Producer ---┤
         *                └-- Journal (async)
         */
        disruptor.handleEventsWith(lobHandler)
                 .then(signalHandler)
                 .then(riskGateway);

        /* Journal runs in parallel with no dependencies */
        disruptor.handleEventsWith(journal);

        /* --- Exception Handler ---
         *
         * FatalExceptionHandler: logs to stderr and triggers circuit breaker.
         * NEVER swallows exceptions silently — any unhandled exception in the
         * hot path indicates a bug that must halt trading immediately.
         */
        disruptor.setDefaultExceptionHandler(new ExceptionHandler<MdEvent>() {
            @Override
            public void handleEventException(Throwable ex, long sequence, MdEvent event) {
                System.err.println("[FATAL] Exception in Disruptor handler at seq=" + sequence);
                ex.printStackTrace(System.err);
                riskGateway.tripCircuitBreaker("EXCEPTION: " + ex.getMessage());
            }

            @Override
            public void handleOnStartException(Throwable ex) {
                System.err.println("[FATAL] Exception during handler startup");
                ex.printStackTrace(System.err);
                throw new RuntimeException("Handler startup failed", ex);
            }

            @Override
            public void handleOnShutdownException(Throwable ex) {
                System.err.println("[WARN] Exception during handler shutdown");
                ex.printStackTrace(System.err);
            }
        });

        this.ringBuffer = disruptor.getRingBuffer();
        this.running = false;
    }

    /**
     * Start the pipeline: begin consuming from SharedMemoryBridge and
     * publishing into the Disruptor.
     */
    public void start() {
        disruptor.start();
        running = true;

        System.out.println("[DisruptorPipeline] Started with " + RING_BUFFER_SIZE + " slots");
        System.out.println("[DisruptorPipeline] Off-heap: " + (offHeapSize / (1024 * 1024)) + " MB");
        System.out.println("[DisruptorPipeline] Handlers: LOB → Signal → Risk | Journal (async)");
    }

    /**
     * Producer loop: reads events from SharedMemoryBridge and publishes
     * to the Disruptor ring buffer.
     *
     * This runs on Core 4 (NUMA Node 1, isolated).
     *
     * <p><b>Zero-allocation path:</b> The event translation reads from the
     * C shared memory region and copies 64 bytes into the Disruptor slot's
     * off-heap address. No Java objects are created.</p>
     */
    public void runProducerLoop() {
        System.out.println("[DisruptorPipeline] Producer loop started");

        while (running) {
            int available = bridge.available();

            if (available > 0) {
                /* Batch publish for throughput */
                int batchSize = Math.min(available, 64);

                for (int i = 0; i < batchSize; i++) {
                    long sourceAddr = bridge.eventAddress(bridge.getTail() + i);

                    long sequence = ringBuffer.next();
                    try {
                        MdEvent event = ringBuffer.get(sequence);
                        /* Point the flyweight at its off-heap slot */
                        long destAddr = offHeapBase + (sequence & (RING_BUFFER_SIZE - 1))
                                        * (long) MdEvent.EVENT_SIZE;
                        event.wrap(destAddr);
                        /* Copy 64 bytes from C ring → Disruptor slot (zero-alloc) */
                        event.copyFrom(sourceAddr);
                    } finally {
                        ringBuffer.publish(sequence);
                    }
                }

                bridge.commitBatch(batchSize);
            } else {
                /* No data from C side — busy-spin
                 * On isolated core, do not yield or pause — minimize latency */
                Thread.onSpinWait();
            }
        }
    }

    /**
     * Stop the pipeline gracefully.
     */
    public void stop() {
        running = false;
        disruptor.shutdown();
        journal.close();

        /* Free off-heap memory */
        if (offHeapBase != 0) {
            UNSAFE.freeMemory(offHeapBase);
        }

        System.out.println("[DisruptorPipeline] Shutdown complete");
    }

    /** Access the risk gateway for external circuit breaker control. */
    public PreTradeRiskGateway getRiskGateway() {
        return riskGateway;
    }

    /** Access the LOB handler for position tracking. */
    public LOBReconstructionHandler getLobHandler() {
        return lobHandler;
    }

    /* --- Main Entry Point (for standalone testing) --- */

    public static void main(String[] args) {
        System.out.println("╔--------------------------------------------------------------╗");
        System.out.println("║  HFT Java Orchestration Engine                              ║");
        System.out.println("║  Disruptor 4.x | Off-Heap | Zero-Allocation Hot Path        ║");
        System.out.println("╚--------------------------------------------------------------╝");

        /*
         * In production, the bridge base address comes from mmap() of the
         * shared memory file created by the C feed handler.
         * For standalone testing, we allocate a mock shared memory region.
         */
        int mockCapacity = 1 << 16;  /* 64K slots for testing */
        long mockBase = MdEvent.UNSAFE.allocateMemory(
            128L + (long) mockCapacity * MdEvent.EVENT_SIZE
        );
        MdEvent.UNSAFE.setMemory(mockBase, 128L + (long) mockCapacity * MdEvent.EVENT_SIZE, (byte) 0);

        String chroniclePath = System.getProperty("java.io.tmpdir") + "/hft-chronicle";

        DisruptorPipeline pipeline = new DisruptorPipeline(mockBase, mockCapacity, chroniclePath);
        pipeline.start();

        System.out.println("[Main] Pipeline started successfully");
        System.out.println("[Main] Risk gateway state: " + pipeline.getRiskGateway().getStatus());

        /* In production, runProducerLoop() blocks here */
        pipeline.stop();
        MdEvent.UNSAFE.freeMemory(mockBase);

        System.out.println("[Main] Clean shutdown");
    }
}
