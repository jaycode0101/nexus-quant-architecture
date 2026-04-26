#!/bin/bash
# -------------------------------------------------------------------
# CPU Affinity & Isolation Script
# -------------------------------------------------------------------
#
# Configures CPU core assignments for the HFT system.
# Must be run as root after boot with isolcpus=1-8 kernel parameter.
#
# Core Map:
#   Core 1:  Feed Handler (C) — ef_vi poll loop
#   Core 2:  OEG (C) — ef_vi transmit
#   Core 3:  Exec Report Handler (C)
#   Core 4:  Disruptor Producer (Java)
#   Core 5:  LOB Reconstruction (Java)
#   Core 6:  Feature/Signal Generation (Java)
#   Core 7:  Strategy + Risk Gate (Java)
#   Core 8:  Order Constructor (Java)
#   Core 10: P&L Tailer (Java)
#   Core 11: Telemetry Export (Java)
#   Core 12: Compliance Tailer (Java)
#   Core 13: Calibration Replay (Java)
#   Core 14: OS + IRQ steering
#   Core 15: ZGC threads

set -euo pipefail

echo "-----------------------------------------------------------"
echo " CPU Affinity Configuration"
echo "-----------------------------------------------------------"

# --- Verify CPU Isolation ---
ISOLATED=$(cat /sys/devices/system/cpu/isolated 2>/dev/null || echo "none")
echo "Isolated cores: $ISOLATED"

if [[ "$ISOLATED" == "none" || "$ISOLATED" == "" ]]; then
    echo "[WARN] No cores isolated! Add 'isolcpus=1-8 nohz_full=1-8 rcu_nocbs=1-8' to GRUB"
fi

# --- Move all IRQs to Core 14 ---
echo "[IRQ] Steering all IRQs to core 14"
for irq_dir in /proc/irq/[0-9]*/; do
    if [ -f "$irq_dir/smp_affinity_list" ]; then
        echo 14 > "$irq_dir/smp_affinity_list" 2>/dev/null || true
    fi
done

# --- Move kernel threads to non-isolated cores ---
echo "[KERNEL] Moving kernel threads to cores 0,9,14-15"
for pid in $(ps -eo pid,comm | grep -E '(ksoftirqd|kworker|migration)' | awk '{print $1}'); do
    taskset -pc 0,9,14-15 "$pid" 2>/dev/null || true
done

# --- Disable irqbalance ---
if systemctl is-active --quiet irqbalance 2>/dev/null; then
    echo "[IRQ] Stopping irqbalance daemon"
    systemctl stop irqbalance
    systemctl disable irqbalance
fi

# --- Set C feed handler affinity (if running) ---
FEED_PID=$(pgrep -f "hft_demo" 2>/dev/null || echo "")
if [ -n "$FEED_PID" ]; then
    echo "[FEED] Pinning feed handler (PID $FEED_PID) to core 1"
    taskset -pc 1 "$FEED_PID"
fi

# --- Disable CPU frequency scaling (performance governor) ---
echo "[POWER] Setting performance governor on all cores"
for cpu in /sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_governor; do
    echo "performance" > "$cpu" 2>/dev/null || true
done

# --- Disable C-states at runtime ---
if [ -f /dev/cpu_dma_latency ]; then
    echo "[POWER] Disabling C-states via cpu_dma_latency"
    exec 3>/dev/cpu_dma_latency
    echo -n -e '\x00\x00\x00\x00' >&3
fi

echo "-----------------------------------------------------------"
echo " CPU configuration complete"
echo "-----------------------------------------------------------"
