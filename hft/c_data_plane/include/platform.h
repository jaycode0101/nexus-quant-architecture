/**
 * platform.h — Platform Abstraction Layer
 *
 * Provides cross-platform shims for Linux-specific APIs used in the HFT data plane.
 * Production builds target Linux with Solarflare EF_VI; development builds compile
 * on Windows/macOS with stubbed implementations preserving identical API surface.
 *
 * Compilation: gcc -std=c11 -O3 -march=native -mavx512f -DNDEBUG
 */

#ifndef HFT_PLATFORM_H
#define HFT_PLATFORM_H

#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>

/* --- Compiler Intrinsics --- */

#ifdef _MSC_VER
    /* MSVC */
    #include <intrin.h>
    #define HFT_LIKELY(x)    (x)
    #define HFT_UNLIKELY(x)  (x)
    #define HFT_INLINE        __forceinline
    #define HFT_NOINLINE      __declspec(noinline)
    #define HFT_ALIGNED(n)    __declspec(align(n))
    #define HFT_PREFETCH_W(addr)  _mm_prefetch((const char*)(addr), _MM_HINT_T0)
    #define HFT_PREFETCH_R(addr)  _mm_prefetch((const char*)(addr), _MM_HINT_T0)
    #define HFT_PAUSE()       _mm_pause()

    static HFT_INLINE uint64_t hft_rdtsc(void) {
        return __rdtsc();
    }

    static HFT_INLINE uint32_t hft_bswap32(uint32_t x) { return _byteswap_ulong(x); }
    static HFT_INLINE uint64_t hft_bswap64(uint64_t x) { return _byteswap_uint64(x); }
    static HFT_INLINE uint16_t hft_bswap16(uint16_t x) { return _byteswap_ushort(x); }

    /* Atomic operations — MSVC intrinsics */
    #define hft_atomic_store_release(ptr, val) \
        do { _ReadWriteBarrier(); *(volatile typeof(*(ptr))*)(ptr) = (val); } while(0)
    #define hft_atomic_load_acquire(ptr) \
        (*(volatile typeof(*(ptr))*)(ptr))

    #define hft_atomic_fetch_add_relaxed(ptr, val) \
        _InterlockedExchangeAdd64((volatile long long*)(ptr), (val))

#else
    /* GCC / Clang */
    #include <x86intrin.h>

    #define HFT_LIKELY(x)    __builtin_expect(!!(x), 1)
    #define HFT_UNLIKELY(x)  __builtin_expect(!!(x), 0)
    #define HFT_INLINE        static inline __attribute__((always_inline))
    #define HFT_NOINLINE      __attribute__((noinline))
    #define HFT_ALIGNED(n)    __attribute__((aligned(n)))
    #define HFT_PREFETCH_W(addr)  __builtin_prefetch((addr), 1, 3)
    #define HFT_PREFETCH_R(addr)  __builtin_prefetch((addr), 0, 3)
    #define HFT_PAUSE()       _mm_pause()

    static inline uint64_t hft_rdtsc(void) {
        uint32_t lo, hi;
        __asm__ volatile ("rdtsc" : "=a"(lo), "=d"(hi));
        return ((uint64_t)hi << 32) | lo;
    }

    #define hft_bswap32(x)  __builtin_bswap32(x)
    #define hft_bswap64(x)  __builtin_bswap64(x)
    #define hft_bswap16(x)  __builtin_bswap16(x)

    /**
     * Memory ordering semantics for SPSC ring buffer:
     *
     * RELEASE on producer store (head index):
     *   Ensures all preceding writes to the ring data slots are visible to the
     *   consumer before the head index update becomes visible. This is the
     *   "publish" barrier.
     *
     * ACQUIRE on consumer load (head index):
     *   Ensures the consumer sees all data slot writes that preceded the head
     *   index update it just read. This is the "subscribe" barrier.
     *
     * SEQ_CST is unnecessary because:
     *   - SPSC topology has exactly one writer and one reader per index variable
     *   - No third thread observes both head and tail, so total order is irrelevant
     *   - Acquire-release provides the necessary happens-before relationship
     *     between the producer's data writes and the consumer's data reads
     */
    #define hft_atomic_store_release(ptr, val) \
        __atomic_store_n((ptr), (val), __ATOMIC_RELEASE)
    #define hft_atomic_load_acquire(ptr) \
        __atomic_load_n((ptr), __ATOMIC_ACQUIRE)
    #define hft_atomic_load_relaxed(ptr) \
        __atomic_load_n((ptr), __ATOMIC_RELAXED)
    #define hft_atomic_store_relaxed(ptr, val) \
        __atomic_store_n((ptr), (val), __ATOMIC_RELAXED)
    #define hft_atomic_fetch_add_relaxed(ptr, val) \
        __atomic_fetch_add((ptr), (val), __ATOMIC_RELAXED)
#endif

/* --- Cache Line Size --- */

#define HFT_CACHE_LINE_SIZE  64

/**
 * Cache-line padding macro. Places a field on its own cache line to prevent
 * false sharing between producer and consumer threads in lock-free structures.
 */
#define HFT_CACHE_LINE_PAD  char _pad[HFT_CACHE_LINE_SIZE]

/* --- Huge Page Allocation --- */

#ifdef __linux__
    #include <sys/mman.h>
    #include <numaif.h>
    #include <numa.h>

    /**
     * Allocate memory on huge pages (2MB) on a specific NUMA node.
     * Falls back to regular mmap if huge pages are exhausted.
     *
     * @param size_bytes  Allocation size (rounded up to 2MB boundary internally)
     * @param numa_node   Target NUMA node (-1 for any)
     * @return Pointer to mapped memory, or NULL on failure
     */
    static inline void* hft_huge_page_alloc(size_t size_bytes, int numa_node) {
        /* Round up to 2MB huge page boundary */
        size_t huge_page_size = 2 * 1024 * 1024;
        size_bytes = (size_bytes + huge_page_size - 1) & ~(huge_page_size - 1);

        void *ptr = mmap(NULL, size_bytes,
                         PROT_READ | PROT_WRITE,
                         MAP_PRIVATE | MAP_ANONYMOUS | MAP_HUGETLB,
                         -1, 0);

        if (ptr == MAP_FAILED) {
            /* Fallback: regular anonymous mmap with MADV_HUGEPAGE hint */
            ptr = mmap(NULL, size_bytes,
                       PROT_READ | PROT_WRITE,
                       MAP_PRIVATE | MAP_ANONYMOUS,
                       -1, 0);
            if (ptr != MAP_FAILED) {
                madvise(ptr, size_bytes, MADV_HUGEPAGE);
            }
        }

        if (ptr != MAP_FAILED && numa_node >= 0) {
            /* Bind to specific NUMA node */
            unsigned long nodemask = 1UL << numa_node;
            mbind(ptr, size_bytes, MPOL_BIND, &nodemask,
                  sizeof(nodemask) * 8, MPOL_MF_MOVE);
        }

        return (ptr == MAP_FAILED) ? NULL : ptr;
    }

    static inline void* hft_shared_mmap_alloc(size_t size_bytes) {
        void *ptr = mmap(NULL, size_bytes,
                         PROT_READ | PROT_WRITE,
                         MAP_SHARED | MAP_ANONYMOUS | MAP_HUGETLB,
                         -1, 0);
        if (ptr == MAP_FAILED) {
            ptr = mmap(NULL, size_bytes,
                       PROT_READ | PROT_WRITE,
                       MAP_SHARED | MAP_ANONYMOUS,
                       -1, 0);
        }
        return (ptr == MAP_FAILED) ? NULL : ptr;
    }

    static inline void hft_huge_page_free(void *ptr, size_t size_bytes) {
        if (ptr) munmap(ptr, size_bytes);
    }

#else
    /* Windows / non-Linux fallback — aligned malloc */
    static inline void* hft_huge_page_alloc(size_t size_bytes, int numa_node) {
        (void)numa_node;
        #ifdef _MSC_VER
            return _aligned_malloc(size_bytes, 4096);
        #else
            void *ptr = NULL;
            if (posix_memalign(&ptr, 4096, size_bytes) != 0) return NULL;
            return ptr;
        #endif
    }

    static inline void* hft_shared_mmap_alloc(size_t size_bytes) {
        return hft_huge_page_alloc(size_bytes, -1);
    }

    static inline void hft_huge_page_free(void *ptr, size_t size_bytes) {
        (void)size_bytes;
        #ifdef _MSC_VER
            _aligned_free(ptr);
        #else
            free(ptr);
        #endif
    }
#endif

/* --- Solarflare EF_VI Stubs --- */

#ifdef __linux__
    /* On production Linux, include the real EF_VI headers */
    /* #include <etherfabric/vi.h>        */
    /* #include <etherfabric/pd.h>        */
    /* #include <etherfabric/memreg.h>    */
    /* #include <etherfabric/ef_vi.h>     */
#endif

/*
 * For development/compilation purposes, provide the EF_VI type and function
 * signatures. In production, these are replaced by the real Solarflare SDK.
 */
#ifndef EFVI_PRODUCTION

typedef struct ef_driver_handle { int fd; } ef_driver_handle;
typedef struct ef_pd { int pd_id; } ef_pd;
typedef struct ef_vi {
    int vi_id;
    int evq_capacity;
    int rxq_capacity;
    int txq_capacity;
} ef_vi;
typedef struct ef_memreg { int mr_id; } ef_memreg;
typedef struct ef_filter_spec { int filter_id; } ef_filter_spec;

/* Event types returned by ef_eventq_poll */
#define EF_EVENT_TYPE_RX           0x01
#define EF_EVENT_TYPE_TX           0x02
#define EF_EVENT_TYPE_RX_DISCARD   0x03
#define EF_EVENT_TYPE_TX_WITH_TIMESTAMP 0x04

typedef struct ef_event {
    uint16_t type;
    uint16_t rx_id;
    uint32_t len;
    uint64_t tx_timestamp;
} ef_event;

/* Stub function signatures matching the real EF_VI API */
static inline int ef_driver_open(ef_driver_handle *h)
    { h->fd = 0; return 0; }
static inline int ef_pd_alloc(ef_pd *pd, ef_driver_handle h, int ifindex, int flags)
    { (void)h; (void)ifindex; (void)flags; pd->pd_id = 0; return 0; }
static inline int ef_vi_alloc_from_pd(ef_vi *vi, ef_driver_handle h, ef_pd *pd,
                                       ef_driver_handle evq_h, int evq_cap,
                                       int rxq_cap, int txq_cap, void *opt,
                                       int opt_len, int flags)
    { (void)h; (void)pd; (void)evq_h; vi->evq_capacity = evq_cap;
      vi->rxq_capacity = rxq_cap; vi->txq_capacity = txq_cap; return 0; }
static inline int ef_memreg_alloc(ef_memreg *mr, ef_driver_handle h,
                                   ef_pd *pd, ef_driver_handle mr_h,
                                   void *addr, size_t len)
    { (void)h; (void)pd; (void)mr_h; (void)addr; (void)len; mr->mr_id = 0; return 0; }
static inline int ef_eventq_poll(ef_vi *vi, ef_event *evts, int max_evts)
    { (void)vi; (void)evts; (void)max_evts; return 0; }
static inline const void* ef_vi_receive_get_bytes(ef_vi *vi, int pkt_id)
    { (void)vi; (void)pkt_id; return NULL; }
static inline void ef_vi_receive_post(ef_vi *vi, int pkt_id, uint64_t dma_addr)
    { (void)vi; (void)pkt_id; (void)dma_addr; }
static inline int ef_vi_transmit(ef_vi *vi, uint64_t dma_addr, int len, int dma_id)
    { (void)vi; (void)dma_addr; (void)len; (void)dma_id; return 0; }
static inline void ef_filter_spec_init(ef_filter_spec *fs, int flags)
    { (void)flags; fs->filter_id = 0; }
static inline int ef_filter_spec_set_ip4_local(ef_filter_spec *fs, int proto,
                                                uint32_t addr, uint16_t port)
    { (void)fs; (void)proto; (void)addr; (void)port; return 0; }
static inline int ef_vi_filter_add(ef_vi *vi, ef_driver_handle h,
                                    ef_filter_spec *fs, void *cookie)
    { (void)vi; (void)h; (void)fs; (void)cookie; return 0; }

#endif /* EFVI_PRODUCTION */

#endif /* HFT_PLATFORM_H */
