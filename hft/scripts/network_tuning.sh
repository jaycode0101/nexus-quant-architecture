#!/bin/bash
# -------------------------------------------------------------------
# Network & NIC Tuning Script
# -------------------------------------------------------------------
#
# Optimizes the Solarflare NIC for ultra-low-latency market data reception.
# Must be run as root. Designed for Solarflare SFN8522 (10GbE).

set -euo pipefail

IFACE="${1:-enp1s0f0}"

echo "-----------------------------------------------------------"
echo " NIC Tuning: $IFACE"
echo "-----------------------------------------------------------"

# --- Verify interface exists ---
if ! ip link show "$IFACE" &>/dev/null; then
    echo "[ERROR] Interface $IFACE not found"
    echo "Available interfaces:"
    ip link show | grep -E '^[0-9]+:' | awk '{print "  " $2}'
    exit 1
fi

# --- Disable interrupt coalescing ---
# With EF_VI, we poll — interrupts are not used on the hot path.
# However, some management traffic still uses interrupts.
echo "[NIC] Disabling interrupt coalescing..."
ethtool -C "$IFACE" rx-usecs 0 rx-frames 0 tx-usecs 0 tx-frames 0 2>/dev/null || true
ethtool -C "$IFACE" adaptive-rx off adaptive-tx off 2>/dev/null || true

# --- Maximize ring buffer sizes ---
echo "[NIC] Maximizing ring buffer sizes..."
ethtool -G "$IFACE" rx 4096 tx 4096 2>/dev/null || true

# --- Disable flow control ---
echo "[NIC] Disabling flow control (pause frames)..."
ethtool -A "$IFACE" rx off tx off 2>/dev/null || true

# --- Disable offload features ---
# We need per-packet visibility; offload features aggregate packets.
echo "[NIC] Disabling offload features..."
ethtool -K "$IFACE" gro off 2>/dev/null || true
ethtool -K "$IFACE" gso off 2>/dev/null || true
ethtool -K "$IFACE" tso off 2>/dev/null || true
ethtool -K "$IFACE" lro off 2>/dev/null || true
ethtool -K "$IFACE" sg off 2>/dev/null || true

# --- Set MTU (jumbo frames if exchange supports) ---
echo "[NIC] Setting MTU to 1500 (standard)..."
ip link set "$IFACE" mtu 1500

# --- Steer NIC interrupts to non-isolated core ---
echo "[NIC] Steering NIC interrupts to core 14..."
NIC_IRQS=$(grep "$IFACE" /proc/interrupts 2>/dev/null | awk '{print $1}' | tr -d ':')
for irq in $NIC_IRQS; do
    echo 14 > "/proc/irq/$irq/smp_affinity_list" 2>/dev/null || true
done

# --- Increase socket buffer sizes ---
echo "[NET] Increasing socket buffer sizes..."
sysctl -w net.core.rmem_max=16777216 2>/dev/null || true
sysctl -w net.core.wmem_max=16777216 2>/dev/null || true
sysctl -w net.core.rmem_default=1048576 2>/dev/null || true
sysctl -w net.core.netdev_max_backlog=65536 2>/dev/null || true

# --- Disable ASLR (for deterministic memory layout) ---
echo "[MEM] Disabling ASLR..."
echo 0 > /proc/sys/kernel/randomize_va_space 2>/dev/null || true

# --- Final status ---
echo ""
echo "NIC configuration for $IFACE:"
ethtool -k "$IFACE" 2>/dev/null | grep -E '(generic-receive|tcp-segmentation|generic-segmentation|large-receive)'
echo ""
ethtool -c "$IFACE" 2>/dev/null | head -10
echo "-----------------------------------------------------------"
