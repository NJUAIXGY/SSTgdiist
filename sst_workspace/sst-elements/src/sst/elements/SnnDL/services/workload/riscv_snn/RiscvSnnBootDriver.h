// -*- c++ -*-
//
// RiscvSnnBootDriver:
// - `riscv_snn` 实验主线的独立启动/冒烟驱动。
// - 把当前 internal smoke command 提交状态机从 workload 主壳中抽离，减少耦合。
//

#pragma once

#include <cstdint>

#include "workload/riscv_snn/RiscvSnnAbi.h"
#include "workload/riscv_snn/RiscvSnnHart.h"
#include "workload/riscv_snn/RiscvSnnQueueContract.h"

namespace SST { namespace SnnDL {

class RiscvSnnBootDriver {
public:
    enum class Mode : uint8_t {
        Idle = 0,
        InternalSmoke = 1,
        ExternalFirmware = 2,
    };

    enum class State : uint8_t {
        Idle = 0,
        Reset = 1,
        Submitted = 2,
        WaitingForCompletion = 3,
        CompletionVisible = 4,
        Done = 5,
        Faulted = 6,
    };

    struct TickResult {
        bool enqueued_internal_command = false;
        bool consumed_completion = false;
        uint32_t last_completion_status = 0;
    };

    void reset();
    void configureInternalSmoke();
    void configureExternalFirmware();

    Mode mode() const { return mode_; }
    State state() const { return state_; }
    bool active() const;

    bool onTick(RiscvSnnHart& hart,
                riscv_snn::RiscvSnnQueueContract& queues,
                uint64_t& next_token,
                TickResult& result);

private:
    bool enqueueInternalFusedStep_(riscv_snn::RiscvSnnQueueContract& queues, uint64_t& next_token);

    Mode mode_ = Mode::Idle;
    State state_ = State::Idle;
};

}} // namespace SST::SnnDL
