// -*- c++ -*-
//
// SpikePacketBridge:
// - 将 SpikeEvent <-> NocPacketEvent 的编解码与投递 glue 下沉到 synapse/route 域；
// - 目标：MultiCorePE 不直接调用 SpikeNocCodec，仅负责装配/调度。
//
// Ownership contract:
// - deliverPacketToEndpoint(): takes ownership of NocPacketEvent*
// - sendAuto()/sendExternal(): take ownership of SpikeEvent*
//

#pragma once

#include <cstdint>
#include <functional>

namespace SST { class Output; }

namespace SST { namespace SnnDL {

class GlobalNeuronLayout;
class INocTransport;
class NocPacketEvent;
class SpikeEvent;

class SpikePacketBridge final {
public:
    struct Runtime {
        SST::Output* log = nullptr;
        int node_id = 0;
        int num_cores = 1;
        const GlobalNeuronLayout* layout = nullptr;
        INocTransport* noc = nullptr;
        std::function<void(int /*core_id*/, SpikeEvent*)> deliver_to_core;
        // Optional: step tagging for step-limited experiments (naive_raw "no within-step cascade").
        // When active_step_seq != nullptr and *active_step_seq != 0:
        //   pkt.step_seq = *active_step_seq + step_seq_offset
        const uint32_t* active_step_seq = nullptr;  // 非拥有
        uint32_t step_seq_offset = 0;
    };

    void bindRuntime(const Runtime& rt) { rt_ = rt; }

    void deliverPacketToEndpoint(int endpoint_id, NocPacketEvent* packet);

    // Explicit core injection: use caller-provided src_core to preserve legacy semantics.
    void sendFromCore(int src_core, SpikeEvent* spike);

    // Auto route: local-deliver vs external-forward decided by NoC backend (dst_node).
    void sendAuto(SpikeEvent* spike);

    // Force external send semantics (local-dst will be dropped by NoC self-loop guard).
    void sendExternal(SpikeEvent* spike);

private:
    int computeSourceCore_(uint64_t src_global) const;

    Runtime rt_{};
};

}} // namespace SST::SnnDL
