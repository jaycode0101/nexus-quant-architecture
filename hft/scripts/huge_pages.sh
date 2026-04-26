#!/bin/bash
# -------------------------------------------------------------------
# Huge Page Pre-Allocation Script
# -------------------------------------------------------------------
#
# Must be run at boot or before starting the HFT system.
# Ensures sufficient 2MB huge pages for:
#   - SPSC ring buffer: 64MB
#   - DMA receive buffers: ~32MB
#   - JVM heap (via -XX:+UseLargePages): 4GB
#   - Off-heap Disruptor: 64MB
#   Total: ~4.2GB → 2,100 huge pages (2MB each)

set -euo pipefail

HUGE_PAGES_NEEDED=2200  # Rounded up with headroom
HUGEPAGE_SIZE_KB=2048   # 2MB

echo "-----------------------------------------------------------"
echo " Huge Page Allocation"
echo "-----------------------------------------------------------"

# --- Check current state ---
CURRENT=$(cat /proc/sys/vm/nr_hugepages 2>/dev/null || echo 0)
FREE=$(grep HugePages_Free /proc/meminfo 2>/dev/null | awk '{print $2}' || echo 0)
echo "Current huge pages: $CURRENT (free: $FREE)"

# --- Allocate ---
if [ "$CURRENT" -lt "$HUGE_PAGES_NEEDED" ]; then
    echo "Allocating $HUGE_PAGES_NEEDED huge pages ($(( HUGE_PAGES_NEEDED * 2 ))MB)..."

    # Drop caches first to free contiguous memory
    echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true
    sync

    echo "$HUGE_PAGES_NEEDED" > /proc/sys/vm/nr_hugepages

    # Verify
    ALLOCATED=$(cat /proc/sys/vm/nr_hugepages)
    if [ "$ALLOCATED" -lt "$HUGE_PAGES_NEEDED" ]; then
        echo "[WARN] Only allocated $ALLOCATED of $HUGE_PAGES_NEEDED pages"
        echo "[WARN] System may not have enough contiguous free memory"
        echo "[WARN] Consider allocating at boot via kernel parameter:"
        echo "       default_hugepagesz=2M hugepagesz=2M hugepages=$HUGE_PAGES_NEEDED"
    else
        echo "Successfully allocated $ALLOCATED huge pages"
    fi
else
    echo "Sufficient huge pages already allocated"
fi

# --- Mount hugetlbfs ---
MOUNT_POINT="/mnt/huge"
if ! mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    echo "Mounting hugetlbfs at $MOUNT_POINT..."
    mkdir -p "$MOUNT_POINT"
    mount -t hugetlbfs nodev "$MOUNT_POINT" -o pagesize=2M
    echo "Mounted successfully"
else
    echo "hugetlbfs already mounted at $MOUNT_POINT"
fi

# --- Create shared memory directory ---
SHM_DIR="/dev/shm"
echo "Shared memory directory: $SHM_DIR"

# --- Final status ---
echo ""
echo "Huge page status:"
grep -i huge /proc/meminfo
echo "-----------------------------------------------------------"
