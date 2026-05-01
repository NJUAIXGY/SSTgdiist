// -*- c++ -*-
//
// RiscvSnnMemoryImage:
// - `riscv_snn` 实验主线独立使用的本地镜像表示。
// - 仅承载 firmware/loader/hart 之间共享的镜像语义，避免把加载细节耦合进 workload 主壳。
//

#pragma once

#include <cstdint>
#include <vector>

namespace SST { namespace SnnDL { namespace riscv_snn {

struct RiscvSnnMemorySegment {
    uint64_t vaddr = 0;
    uint32_t flags = 0;
    std::vector<uint8_t> data{};

    uint64_t endAddressExclusive() const {
        return vaddr + static_cast<uint64_t>(data.size());
    }
};

struct RiscvSnnMemoryImage {
    uint64_t entry_pc = 0;
    std::vector<RiscvSnnMemorySegment> segments{};

    bool empty() const { return segments.empty(); }

    uint64_t footprintBytes() const {
        uint64_t total = 0;
        for (const auto& seg : segments) {
            total += static_cast<uint64_t>(seg.data.size());
        }
        return total;
    }
};

inline bool segmentsOverlap(const RiscvSnnMemorySegment& lhs, const RiscvSnnMemorySegment& rhs) {
    return lhs.vaddr < rhs.endAddressExclusive() && rhs.vaddr < lhs.endAddressExclusive();
}

}}} // namespace SST::SnnDL::riscv_snn
