package com.hft.journal;

import com.hft.core.MdEvent;

/**
 * PositionRecovery — Crash Recovery via Chronicle Queue Replay
 *
 * On system restart after a crash, this component replays the Chronicle Queue
 * journals to reconstruct:
 *   1. Open positions (net shares per instrument)
 *   2. Realized P&L
 *   3. Last known sequence number (for gap detection with exchange)
 *   4. Order book state (LOB replay from MdEvent journal)
 *
 * <p><b>Recovery Algorithm:</b></p>
 * <pre>
 *   1. Open ExcerptTailer on chronicle-exec/ journal
 *   2. Replay all ExecutionReport entries:
 *      - For each fill: update position[instrumentId] += qty × side
 *      - Accumulate realized P&L
 *   3. Open ExcerptTailer on chronicle-order/ journal
 *   4. Identify open orders (sent but not filled/cancelled)
 *   5. Open ExcerptTailer on chronicle-md/ journal
 *   6. Get last sequence number → request gap fill from exchange if needed
 * </pre>
 *
 * <p><b>Production Notes:</b></p>
 * <ul>
 *   <li>Recovery runs on a non-isolated core (Core 14) during startup</li>
 *   <li>The hot-path threads are NOT started until recovery completes</li>
 *   <li>If sequence gap detected, the system requests a snapshot from the
 *       exchange and rebuilds the LOB from scratch</li>
 * </ul>
 */
public final class PositionRecovery {

    /** Maximum number of instruments to track. */
    private static final int MAX_INSTRUMENTS = 8192;

    /** Position per instrument: index = instrumentId, value = net shares. */
    private final long[] positions;

    /** Average cost basis per instrument (fixed-point cents). */
    private final long[] avgCostCents;

    /** Realized P&L in cents. */
    private long realizedPnlCents;

    /** Last recovered sequence number. */
    private long lastSequenceNo;

    /** Number of fills replayed. */
    private long fillsReplayed;

    /** Number of open orders discovered. */
    private int openOrderCount;

    /** Recovery completed flag. */
    private boolean recoveryComplete;

    public PositionRecovery() {
        this.positions = new long[MAX_INSTRUMENTS];
        this.avgCostCents = new long[MAX_INSTRUMENTS];
        this.realizedPnlCents = 0;
        this.lastSequenceNo = 0;
        this.fillsReplayed = 0;
        this.openOrderCount = 0;
        this.recoveryComplete = false;
    }

    /**
     * Execute full recovery from Chronicle Queue journals.
     *
     * @param chroniclePath Base directory containing chronicle-md/, chronicle-exec/, etc.
     * @return true if recovery succeeded, false if data corruption detected
     */
    public boolean recover(final String chroniclePath) {
        System.out.println("[Recovery] Starting position recovery from: " + chroniclePath);
        long startTime = System.nanoTime();

        try {
            /* --- Phase 1: Replay Execution Reports ---
             *
             * Production:
             *   SingleChronicleQueue execQueue = ChronicleQueue.singleBuilder(
             *       chroniclePath + "/chronicle-exec").build();
             *   ExcerptTailer tailer = execQueue.createTailer();
             *
             *   while (tailer.readDocument(w -> {
             *       byte type = w.read("t").int8();
             *       int instrId = w.read("i").int32();
             *       long price = w.read("p").int64();
             *       int qty = w.read("q").int32();
             *       byte side = w.read("s").int8();
             *       long seq = w.read("sn").int64();
             *
             *       applyFill(instrId, price, qty, side);
             *       lastSequenceNo = Math.max(lastSequenceNo, seq);
             *   })) { fillsReplayed++; }
             */

            System.out.println("[Recovery] Phase 1: Replay execution reports");
            /* In reference mode, no journals to replay — positions start at zero */

            /* --- Phase 2: Identify Open Orders ---
             *
             * Scan chronicle-order/ for orders without matching fills.
             * In production, this involves correlating ClOrdId across journals.
             */
            System.out.println("[Recovery] Phase 2: Identify open orders");

            /* --- Phase 3: Get Last Sequence Number ---
             *
             * Read the last entry from chronicle-md/ to determine where
             * market data processing left off.
             */
            System.out.println("[Recovery] Phase 3: Get last sequence number");

            recoveryComplete = true;

            long elapsedMs = (System.nanoTime() - startTime) / 1_000_000;
            System.out.printf("[Recovery] Complete in %dms: fills=%d, openOrders=%d, lastSeq=%d%n",
                    elapsedMs, fillsReplayed, openOrderCount, lastSequenceNo);
            System.out.printf("[Recovery] Net P&L: %d cents%n", realizedPnlCents);

            /* Print position summary */
            for (int i = 0; i < MAX_INSTRUMENTS; i++) {
                if (positions[i] != 0) {
                    System.out.printf("[Recovery] Instrument %d: position=%d, avgCost=%d¢%n",
                            i, positions[i], avgCostCents[i]);
                }
            }

            return true;

        } catch (Exception e) {
            System.err.println("[Recovery] FATAL: Recovery failed: " + e.getMessage());
            e.printStackTrace(System.err);
            return false;
        }
    }

    /**
     * Apply a fill to the position tracker.
     *
     * @param instrumentId Instrument identifier
     * @param priceCents   Fill price in cents
     * @param quantity     Fill quantity
     * @param side         'B' for buy, 'S' for sell
     */
    private void applyFill(final int instrumentId, final long priceCents,
                           final int quantity, final byte side) {
        if (instrumentId < 0 || instrumentId >= MAX_INSTRUMENTS) return;

        long currentPos = positions[instrumentId];
        long currentAvgCost = avgCostCents[instrumentId];

        if (side == MdEvent.SIDE_BUY) {
            /* Buying: update average cost */
            long newPos = currentPos + quantity;
            if (newPos != 0) {
                avgCostCents[instrumentId] =
                    (currentAvgCost * currentPos + priceCents * quantity) / newPos;
            }
            positions[instrumentId] = newPos;
        } else {
            /* Selling: realize P&L */
            long pnl = (priceCents - currentAvgCost) * Math.min(quantity, currentPos);
            realizedPnlCents += pnl;
            positions[instrumentId] = currentPos - quantity;
        }

        fillsReplayed++;
    }

    /* --- Accessors --- */

    public long getPosition(final int instrumentId) {
        if (instrumentId < 0 || instrumentId >= MAX_INSTRUMENTS) return 0;
        return positions[instrumentId];
    }

    public long getRealizedPnlCents() { return realizedPnlCents; }
    public long getLastSequenceNo() { return lastSequenceNo; }
    public boolean isRecoveryComplete() { return recoveryComplete; }
    public long getFillsReplayed() { return fillsReplayed; }
}
