/**
 * CMakeLists.txt — Build configuration for the HFT C Data Plane
 *
 * Targets:
 *   hft_demo    — Integration demo/test binary
 *
 * Build:
 *   mkdir build && cd build
 *   cmake -DCMAKE_BUILD_TYPE=Release ..
 *   make -j$(nproc)
 *
 * Production flags (Linux with Solarflare SDK):
 *   cmake -DCMAKE_BUILD_TYPE=Release -DEFVI_PRODUCTION=ON ..
 */

cmake_minimum_required(VERSION 3.16)
project(hft_data_plane C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

# --- Compiler Flags ---
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    set(CMAKE_C_FLAGS_RELEASE "-O3 -march=native -mavx2 -DNDEBUG")
    set(CMAKE_C_FLAGS_DEBUG "-O0 -g3 -fsanitize=address,undefined")

    # Warning flags — treat all warnings as errors in production
    add_compile_options(-Wall -Wextra -Wpedantic -Wno-unused-parameter)

    # AVX-512 support (optional — detected at runtime)
    include(CheckCCompilerFlag)
    check_c_compiler_flag("-mavx512f" HAS_AVX512)
    if(HAS_AVX512)
        add_compile_options(-mavx512f)
        add_definitions(-DHFT_HAS_AVX512)
    endif()
elseif(MSVC)
    set(CMAKE_C_FLAGS_RELEASE "/O2 /DNDEBUG")
    set(CMAKE_C_FLAGS_DEBUG "/Od /Zi")
    add_compile_options(/W4 /arch:AVX2)
endif()

# --- Include Directories ---
include_directories(${CMAKE_SOURCE_DIR}/include)

# --- Source Files ---
set(DATA_PLANE_SOURCES
    src/itch_parser.c
    src/ef_vi_receiver.c
    src/order_entry_gateway.c
)

# --- Main Demo Binary ---
add_executable(hft_demo
    src/main.c
    ${DATA_PLANE_SOURCES}
)

# --- Production EF_VI Linkage ---
option(EFVI_PRODUCTION "Link against real Solarflare EF_VI SDK" OFF)
if(EFVI_PRODUCTION)
    target_compile_definitions(hft_demo PRIVATE EFVI_PRODUCTION)
    target_link_libraries(hft_demo PRIVATE etherfabric)
endif()

# --- Linux-specific: NUMA, huge pages ---
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    target_link_libraries(hft_demo PRIVATE numa pthread)
endif()

# --- Print Build Configuration ---
message(STATUS "-------------------------------------------")
message(STATUS " HFT C Data Plane Build Configuration")
message(STATUS "-------------------------------------------")
message(STATUS " Compiler:    ${CMAKE_C_COMPILER_ID} ${CMAKE_C_COMPILER_VERSION}")
message(STATUS " Build Type:  ${CMAKE_BUILD_TYPE}")
message(STATUS " AVX-512:     ${HAS_AVX512}")
message(STATUS " EF_VI Prod:  ${EFVI_PRODUCTION}")
message(STATUS "-------------------------------------------")
