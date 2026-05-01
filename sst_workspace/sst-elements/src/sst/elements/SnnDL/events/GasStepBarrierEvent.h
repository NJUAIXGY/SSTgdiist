// -*- c++ -*-
//
// GasStepBarrierEvent:
// - 全局 Step/GAS 同步的控制面事件（不携带 Spike/BCSR/权重语义）
// - 用于 GlobalGasStepController <-> MultiCorePE 的 barrier 协议
//

#ifndef SNNDL_GAS_STEP_BARRIER_EVENT_H
#define SNNDL_GAS_STEP_BARRIER_EVENT_H

#include <cstdint>

#include <sst/core/event.h>
#include <sst/core/serialization/serialize.h>

namespace SST { namespace SnnDL {

enum class GasStepBarrierOp : uint8_t {
    Unknown   = 0,
    PeReady   = 1,
    StartStep = 2,
    PeDone    = 3,
};

class GasStepBarrierEvent : public SST::Event {
public:
    uint8_t op = static_cast<uint8_t>(GasStepBarrierOp::Unknown);
    uint32_t seq = 0;
    uint32_t src_node = 0;
    // Optional: controller-provided Apply-stage per-bank credit target for this step (0 means "no override").
    // - Used by GlobalGasStepController -> MultiCorePE control plane at START_STEP(seq).
    uint32_t apply_bank_credit_target = 0;
    // Optional: PE-provided step timing telemetry (valid when op==PeDone; 0 means "unknown").
    // - Used by GlobalGasStepController for step-level criticality-aware control.
    uint64_t step_total_ns = 0;
    uint64_t step_apply_ns = 0;

    GasStepBarrierEvent() = default;

    GasStepBarrierEvent(GasStepBarrierOp op_, uint32_t seq_, uint32_t src_node_)
        : SST::Event(),
          op(static_cast<uint8_t>(op_)),
          seq(seq_),
          src_node(src_node_)
    {}

    GasStepBarrierOp operation() const { return static_cast<GasStepBarrierOp>(op); }

    void serialize_order(SST::Core::Serialization::serializer& ser) override {
        Event::serialize_order(ser);
        SST_SER(op);
        SST_SER(seq);
        SST_SER(src_node);
        SST_SER(apply_bank_credit_target);
        SST_SER(step_total_ns);
        SST_SER(step_apply_ns);
    }

private:
    ImplementSerializable(SST::SnnDL::GasStepBarrierEvent)
};

}} // namespace SST::SnnDL

#endif // SNNDL_GAS_STEP_BARRIER_EVENT_H
