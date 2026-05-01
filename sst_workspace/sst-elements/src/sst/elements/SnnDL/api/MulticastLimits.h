// -*- c++ -*-
//
// MulticastLimits:
// - 原生多播（blocked multicast）相关的协议/实现上限参数。
//

#pragma once

#include <cstdint>

namespace SST { namespace SnnDL {

// SpikeKey 路由头中的 core_mask 采用固定数组长度（避免可变长 payload）。
// 约束：block_w * block_h <= kMaxMulticastBlockCells。
static constexpr uint32_t kMaxMulticastBlockCells = 64; // 支持到 8x8

// 每 PE 最多 32 个 core（由 core_mask 单个 uint32 bitset 决定）。
static constexpr uint32_t kMaxCoresPerPe = 32;

// group-level 覆盖自检的最大 endpoint 数（block_cells * cores_per_pe）。
static constexpr uint32_t kMaxSpikeKeyEndpoints = kMaxMulticastBlockCells * kMaxCoresPerPe; // 2048

}} // namespace SST::SnnDL

