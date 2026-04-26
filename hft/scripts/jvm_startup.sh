#!/bin/bash
# -------------------------------------------------------------------
# JVM Startup Script — Production HFT Java Orchestration Engine
# -------------------------------------------------------------------
#
# Prerequisites:
#   1. JDK 21+ installed at $JAVA_HOME
#   2. Huge pages pre-allocated (huge_pages.sh)
#   3. CPU cores isolated (boot parameter: isolcpus=1-8)
#   4. IRQ affinity configured (network_tuning.sh)
#   5. Chronicle Queue directory created
#   6. Shared memory ring buffer created by C feed handler
#
# Usage:
#   ./jvm_startup.sh [--dry-run]

set -euo pipefail

JAVA_HOME="${JAVA_HOME:-/opt/jdk-21}"
APP_JAR="$(dirname "$0")/../java_orchestration/target/hft-orchestration-1.0.0.jar"
DEP_DIR="$(dirname "$0")/../java_orchestration/target/dependency"

CHRONICLE_PATH="${CHRONICLE_PATH:-/data/hft/journals}"
BRIDGE_PATH="${BRIDGE_PATH:-/dev/shm/hft-ring}"
BRIDGE_CAPACITY="${BRIDGE_CAPACITY:-1048576}"

# Create journal directory
mkdir -p "$CHRONICLE_PATH"

# --- JVM Arguments ---

JVM_ARGS=(
    # -- Memory & GC --
    -Xms4g -Xmx4g                           # Fixed heap size (no resize pauses)
    -XX:+UseZGC                              # Z Garbage Collector (sub-ms pauses)
    -XX:+ZGenerational                       # Generational ZGC (JDK 21+)
    -XX:ConcGCThreads=2                      # Limit concurrent GC threads
    -XX:ParallelGCThreads=2                  # Limit parallel GC threads
    -XX:+UseLargePages                       # Use huge pages for heap
    -XX:+UseTransparentHugePages             # THP fallback
    -XX:LargePageSizeInBytes=2m              # 2MB huge pages
    -XX:+AlwaysPreTouch                      # Fault all heap pages at startup

    # -- NUMA --
    -XX:+UseNUMA                             # NUMA-aware heap allocation

    # -- JIT Compilation --
    -XX:+TieredCompilation                   # Tiered C1→C2 compilation
    -XX:CompileThreshold=1000                # Compile hot methods sooner
    -XX:-BackgroundCompilation               # Block on compilation (no OSR delay)
    -XX:MaxInlineSize=325                    # Aggressive inlining threshold
    -XX:FreqInlineSize=500                   # Inline frequently called methods
    -XX:LoopUnrollLimit=16                   # Unroll small loops

    # -- Thread Management --
    -XX:+UseThreadPriorities                 # Allow Java thread priorities
    -XX:ThreadPriorityPolicy=1               # Map to OS priorities
    -XX:-UseBiasedLocking                    # Disable biased locking

    # -- Off-Heap Access --
    -XX:MaxDirectMemorySize=256m             # Direct ByteBuffer limit
    --add-opens=java.base/sun.misc=ALL-UNNAMED
    --add-opens=java.base/jdk.internal.misc=ALL-UNNAMED
    --add-opens=java.base/java.nio=ALL-UNNAMED

    # -- Application Properties --
    -Dchronicle.path="$CHRONICLE_PATH"
    -Dbridge.path="$BRIDGE_PATH"
    -Dbridge.capacity="$BRIDGE_CAPACITY"
)

# --- CPU Affinity ---
# Pin JVM threads to:
#   Cores 4-8: isolated hot-path threads (Disruptor, LOB, Signal, Risk, Order)
#   Cores 10-13: non-isolated async threads (Tailers, Telemetry, Calibration)
#   Core 15: ZGC concurrent threads
AFFINITY_MASK="4-8,10-13,15"

# --- Launch ---

echo "-----------------------------------------------------------"
echo " HFT Java Orchestration Engine — Production Launch"
echo "-----------------------------------------------------------"
echo " Java:      $JAVA_HOME"
echo " App JAR:   $APP_JAR"
echo " Chronicle: $CHRONICLE_PATH"
echo " Bridge:    $BRIDGE_PATH ($BRIDGE_CAPACITY slots)"
echo " CPU Mask:  $AFFINITY_MASK"
echo "-----------------------------------------------------------"

if [[ "${1:-}" == "--dry-run" ]]; then
    echo "[DRY RUN] Would execute:"
    echo "  taskset -c $AFFINITY_MASK $JAVA_HOME/bin/java ${JVM_ARGS[*]} -cp $APP_JAR:$DEP_DIR/* com.hft.core.DisruptorPipeline"
    exit 0
fi

exec taskset -c "$AFFINITY_MASK" \
    "$JAVA_HOME/bin/java" \
    "${JVM_ARGS[@]}" \
    -cp "$APP_JAR:$DEP_DIR/*" \
    com.hft.core.DisruptorPipeline
