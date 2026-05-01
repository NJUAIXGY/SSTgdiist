// -*- c++ -*-
//
// NocSpikeTransport: ISpikeTransport 的 NoC 适配器
// - 将 SpikeCommSubsystem 的 transport->send(ev) 映射为 INocTransport::sendFromCore(src_core, ev)
//

#pragma once

#include "INocTransport.h"
#include "ISpikeTransport.h"
#include "GlobalNeuronLayout.h"
#include "NocPacketEvent.h"
#include "synapse/route/SpikeNocCodec.h"

namespace SST { namespace SnnDL {

class NocSpikeTransport final : public ISpikeTransport {
public:
    NocSpikeTransport() = default;
    NocSpikeTransport(INocTransport* noc, int src_core) : noc_(noc), src_core_(src_core) {}

    void setNocTransport(INocTransport* noc) { noc_ = noc; }
    void setSourceCore(int src_core) { src_core_ = src_core; }
    void setGlobalLayout(const GlobalNeuronLayout& layout) { layout_ = layout; }
    void configureLayout(uint32_t total_nodes, uint32_t cores_per_pe, uint32_t neurons_per_core) {
        layout_ = GlobalNeuronLayout(total_nodes, cores_per_pe, neurons_per_core);
    }

    // Optional: step tagging for step-limited experiments (naive_raw "no within-step cascade").
    // When active_step_seq != nullptr and *active_step_seq != 0:
    //   pkt.step_seq = *active_step_seq + step_seq_offset
    void setActiveStepSeqPtr(const uint32_t* active_step_seq) { active_step_seq_ = active_step_seq; }
    void setStepSeqOffset(uint32_t step_seq_offset) { step_seq_offset_ = step_seq_offset; }

    void send(SpikeEvent* event) override {
        if (!event) return;
        if (!noc_ || !layout_.valid()) {
            delete event;
            return;
        }

        NocPacketEvent* pkt = SpikeNocCodec::encode(*event, layout_);
        delete event;
        if (!pkt) return;
        // 保守：以注入端 core_id 覆盖 src_endpoint，避免上层未按 global_id 口径填充导致偏差
        pkt->src_endpoint = static_cast<uint16_t>(src_core_);
        if (active_step_seq_ && *active_step_seq_ != 0) {
            pkt->step_seq = (*active_step_seq_) + step_seq_offset_;
        }
        noc_->sendFromCore(src_core_, pkt);
    }

private:
    INocTransport* noc_ = nullptr;  // 非拥有
    int src_core_ = 0;
    GlobalNeuronLayout layout_{};
    const uint32_t* active_step_seq_ = nullptr;  // 非拥有（通常指向 workload 的当前 step 序号）
    uint32_t step_seq_offset_ = 0;
};

}} // namespace SST::SnnDL
