// -*- c++ -*-

#include <sst/core/sst_config.h>

#include "workload/riscv_snn/RiscvSnnBootDriver.h"

namespace SST { namespace SnnDL {

void RiscvSnnBootDriver::reset() {
    mode_ = Mode::Idle;
    state_ = State::Idle;
}

void RiscvSnnBootDriver::configureInternalSmoke() {
    mode_ = Mode::InternalSmoke;
    state_ = State::Reset;
}

void RiscvSnnBootDriver::configureExternalFirmware() {
    mode_ = Mode::ExternalFirmware;
    state_ = State::Done;
}

bool RiscvSnnBootDriver::active() const {
    return mode_ == Mode::InternalSmoke &&
        state_ != State::Done &&
        state_ != State::Faulted &&
        state_ != State::Idle;
}

bool RiscvSnnBootDriver::onTick(RiscvSnnHart& hart,
                                riscv_snn::RiscvSnnQueueContract& queues,
                                uint64_t& next_token,
                                TickResult& result) {
    result = TickResult{};
    if (mode_ != Mode::InternalSmoke) return false;

    switch (state_) {
    case State::Reset:
        if (!enqueueInternalFusedStep_(queues, next_token)) return false;
        hart.enterWfi();
        state_ = State::Submitted;
        result.enqueued_internal_command = true;
        return true;
    case State::Submitted:
        if (queues.commandQueueEmpty()) {
            state_ = State::WaitingForCompletion;
            return true;
        }
        return false;
    case State::WaitingForCompletion:
        if (queues.completionQueueNonEmpty() && hart.hasEnabledPendingEvents()) {
            state_ = State::CompletionVisible;
            return true;
        }
        return false;
    case State::CompletionVisible: {
        riscv_snn::CompletionEntryV1 completion{};
        if (!queues.consumeCompletion(completion)) return false;
        result.consumed_completion = true;
        result.last_completion_status = completion.status_code;
        hart.writeCsr(
            riscv_snn::kCsrMsnnEventPending,
            riscv_snn::eventMask(riscv_snn::EventBit::CmdComplete) |
                riscv_snn::eventMask(riscv_snn::EventBit::BarrierRelease) |
                riscv_snn::eventMask(riscv_snn::EventBit::Fault));
        state_ = (completion.status_code == 0) ? State::Done : State::Faulted;
        return true;
    }
    case State::Done:
    case State::Faulted:
    case State::Idle:
    default:
        return false;
    }
}

bool RiscvSnnBootDriver::enqueueInternalFusedStep_(riscv_snn::RiscvSnnQueueContract& queues,
                                                   uint64_t& next_token) {
    riscv_snn::CommandDescriptorV1 desc;
    desc.hdr0 = riscv_snn::encodeDescriptorHeader(
        /*version=*/1,
        riscv_snn::CommandOpcode::FusedStep,
        /*flags=*/0,
        /*completion_policy=*/0,
        /*error_policy=*/0,
        riscv_snn::kCommandDescriptorBytes);
    desc.token = next_token++;

    uint64_t ticket = 0;
    return queues.enqueueCommand(desc, ticket);
}

}} // namespace SST::SnnDL
