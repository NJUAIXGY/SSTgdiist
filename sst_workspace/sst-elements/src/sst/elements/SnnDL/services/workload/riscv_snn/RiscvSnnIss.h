// -*- c++ -*-
//
// RiscvSnnIss:
// - `riscv_snn` 实验主线的最小解释执行器。
// - 先只覆盖 firmware bring-up 所需的整数/CSR/WFI/EBREAK 子集，避免把执行语义堆回 workload 主壳。
//

#pragma once

#include <cstdint>

namespace SST { namespace SnnDL {

class RiscvSnnHart;

class RiscvSnnIss {
public:
    enum class StopReason : uint8_t {
        None = 0,
        WaitingForInterrupt = 1,
        Halted = 2,
        Fault = 3,
    };

    struct StepResult {
        bool retired = false;
        StopReason stop_reason = StopReason::None;
        uint64_t pc_before = 0;
        uint64_t pc_after = 0;
        uint32_t insn = 0;
    };

    StepResult step(RiscvSnnHart& hart) const;
};

}} // namespace SST::SnnDL
