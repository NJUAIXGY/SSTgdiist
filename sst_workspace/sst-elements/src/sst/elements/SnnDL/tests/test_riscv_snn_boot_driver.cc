// -*- c++ -*-

#include "workload/riscv_snn/RiscvSnnBootDriver.h"
#include "workload/riscv_snn/RiscvSnnHart.h"
#include "workload/riscv_snn/RiscvSnnQueueContract.h"

#include <cassert>

int main() {
    using namespace SST::SnnDL;
    using namespace SST::SnnDL::riscv_snn;

    RiscvSnnHart hart;
    hart.reset(0x1000);
    hart.writeCsr(
        kCsrMsnnEventEnable,
        eventMask(EventBit::CmdComplete) |
            eventMask(EventBit::BarrierRelease) |
            eventMask(EventBit::Fault));

    RiscvSnnQueueContract queues;
    assert(queues.configure(8, 8, 4));

    RiscvSnnBootDriver driver;
    driver.configureInternalSmoke();

    uint64_t next_token = 1;
    RiscvSnnBootDriver::TickResult tick0;
    assert(driver.onTick(hart, queues, next_token, tick0));
    assert(tick0.enqueued_internal_command);
    assert(driver.state() == RiscvSnnBootDriver::State::Submitted);
    assert(queues.cmdTail() == 1);
    SnnAccelCommand accepted{};
    assert(queues.peekCommand(accepted));
    assert(queues.acceptCommand(accepted.ticket));

    SnnAccelCompletion completion;
    completion.token = 1;
    completion.status_code = encodeStatusCode(
        CompletionPrimaryStatus::Success,
        CompletionSeverity::Success);
    completion.event_mask =
        eventMask(EventBit::CmdComplete) | eventMask(EventBit::BarrierRelease);
    uint32_t raised_events = 0;
    assert(queues.publishCompletion(completion, raised_events));
    hart.raiseArchitecturalEvents(raised_events);

    RiscvSnnBootDriver::TickResult tick1;
    assert(driver.onTick(hart, queues, next_token, tick1));
    assert(driver.state() == RiscvSnnBootDriver::State::WaitingForCompletion);

    RiscvSnnBootDriver::TickResult tick2;
    assert(driver.onTick(hart, queues, next_token, tick2));
    assert(driver.state() == RiscvSnnBootDriver::State::CompletionVisible);

    RiscvSnnBootDriver::TickResult tick3;
    assert(driver.onTick(hart, queues, next_token, tick3));
    assert(tick3.consumed_completion);
    assert(tick3.last_completion_status == completion.status_code);
    assert(driver.state() == RiscvSnnBootDriver::State::Done);
    assert(queues.cmpHead() == 1);
    assert(hart.pendingEvents() == 0);

    return 0;
}
