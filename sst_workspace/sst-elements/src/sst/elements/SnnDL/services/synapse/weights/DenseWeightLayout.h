// -*- c++ -*-
//
// DenseWeightLayout: dense 权重的“物理布局”寻址辅助（实验性；默认关闭）
// - RowMajor：与历史行为一致（base + (row*cols+col)*4）
// - PhysV1：将 row stride 对齐到 cacheline，并按 DRAM row_bytes 打包（cacheline 语义默认）
//
// 重要：
// - 该布局只改变“地址映射”，不改变权重语义/索引语义；
// - 需要 WeightLoader(raw) 将对应的 weights_phys.bin 写入到 base_addr 起始地址。

#pragma once

#include <algorithm>
#include <cstdint>

namespace SST { namespace SnnDL {

enum class DenseLayoutMode : uint8_t {
    RowMajor = 0,
    PhysV1   = 1,
};

struct DensePhysV1Derived {
    uint32_t bytes_per_weight = 4;
    uint32_t line_bytes = 64;
    uint32_t dram_row_bytes = 0;
    uint32_t cols = 0;

    uint32_t row_bytes_logical = 0;     // cols * bytes_per_weight
    uint32_t row_stride_bytes = 0;      // align_up(row_bytes_logical, line_bytes)
    uint32_t rows_per_dram_row = 1;     // max(1, dram_row_bytes / row_stride_bytes)
    uint32_t group_stride_bytes = 0;    // dram_row_bytes (or align_up(row_stride_bytes, dram_row_bytes) when row_stride>row)

    uint64_t total_bytes = 0;           // ceil(rows/rows_per_dram_row) * group_stride_bytes
};

static inline bool isPow2U32(uint32_t v) { return v != 0 && (v & (v - 1u)) == 0; }

static inline uint64_t alignUpU64(uint64_t v, uint64_t a) {
    if (a == 0) return v;
    const uint64_t m = a - 1u;
    return (v + m) & ~m;
}

// Compute PhysV1 derived layout for a dense matrix (rows x cols).
// Returns false if parameters are invalid (e.g., cols=0 or dram_row_bytes=0).
static inline bool computeDensePhysV1Derived(uint32_t rows,
                                             uint32_t cols,
                                             uint32_t line_bytes,
                                             uint32_t dram_row_bytes,
                                             DensePhysV1Derived& out) {
    out = DensePhysV1Derived{};
    if (rows == 0 || cols == 0) return false;
    if (line_bytes == 0) line_bytes = 64;
    if (dram_row_bytes == 0) return false;
    if (!isPow2U32(line_bytes)) return false;
    if (!isPow2U32(dram_row_bytes)) return false;

    out.line_bytes = line_bytes;
    out.dram_row_bytes = dram_row_bytes;
    out.cols = cols;

    const uint64_t row_bytes_logical = static_cast<uint64_t>(cols) * static_cast<uint64_t>(out.bytes_per_weight);
    if (row_bytes_logical == 0 || row_bytes_logical > static_cast<uint64_t>(UINT32_MAX)) return false;
    out.row_bytes_logical = static_cast<uint32_t>(row_bytes_logical);

    const uint64_t row_stride = alignUpU64(row_bytes_logical, static_cast<uint64_t>(line_bytes));
    if (row_stride == 0 || row_stride > static_cast<uint64_t>(UINT32_MAX)) return false;
    out.row_stride_bytes = static_cast<uint32_t>(row_stride);

    const uint32_t rp = (out.row_stride_bytes <= dram_row_bytes)
                            ? std::max<uint32_t>(1u, dram_row_bytes / out.row_stride_bytes)
                            : 1u;
    out.rows_per_dram_row = rp;

    const uint64_t group_stride =
        (out.row_stride_bytes <= dram_row_bytes)
            ? static_cast<uint64_t>(dram_row_bytes)
            : alignUpU64(static_cast<uint64_t>(out.row_stride_bytes), static_cast<uint64_t>(dram_row_bytes));
    if (group_stride == 0 || group_stride > static_cast<uint64_t>(UINT32_MAX)) return false;
    out.group_stride_bytes = static_cast<uint32_t>(group_stride);

    const uint64_t groups = (static_cast<uint64_t>(rows) + static_cast<uint64_t>(out.rows_per_dram_row) - 1u) /
                            static_cast<uint64_t>(out.rows_per_dram_row);
    const uint64_t total = groups * group_stride;
    out.total_bytes = total;
    return true;
}

// Compute offset (bytes) from base for PhysV1.
// Caller must ensure (row < rows) and (col < cols); no bounds checks here.
static inline uint64_t densePhysV1Offset(uint32_t row, uint32_t col, const DensePhysV1Derived& d) {
    const uint64_t group = (d.rows_per_dram_row != 0) ? (static_cast<uint64_t>(row) / d.rows_per_dram_row) : 0;
    const uint64_t within = (d.rows_per_dram_row != 0) ? (static_cast<uint64_t>(row) % d.rows_per_dram_row) : 0;
    return group * static_cast<uint64_t>(d.group_stride_bytes) +
           within * static_cast<uint64_t>(d.row_stride_bytes) +
           static_cast<uint64_t>(col) * static_cast<uint64_t>(d.bytes_per_weight);
}

}} // namespace SST::SnnDL
