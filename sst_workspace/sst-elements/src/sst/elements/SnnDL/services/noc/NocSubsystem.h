// -*- c++ -*-
//
// NocSubsystem:
// - 统一收敛 NoC 输入侧（NIC 回调 / 外部端口 / mesh 方向链路）
// - 覆盖 send/recv/forward + 本地投递（跨 core ring）
//
// Phase4-A1.1：以“编排/适配层”形式落地，先通过回调复用 MultiCorePE 现有后端能力，
// 保持行为/统计口径不变，再逐步把后端实现迁出 MultiCorePE。

#pragma once

#include <cstdint>
#include <functional>
#include <queue>
#include <string>

#include "INocTransport.h"
#include "NocPacketEvent.h"

namespace SST { class Event; }
namespace SST { class Link; }
namespace SST { class Output; }
namespace SST { namespace Statistics { template <typename T> class Statistic; } }

namespace SST { namespace SnnDL {

class OptimizedInternalRing;
class SnnInterface;

class NocSubsystem final : public INocTransport {
public:
    struct Config {
        bool log_enable = false;
    };

    struct Runtime {
        SST::Output* log = nullptr;
        int node_id = 0;
        int num_cores = 1;

        // NoC backends（由 MultiCorePE 装配并保证生命周期）
        SnnInterface* nic = nullptr;
        OptimizedInternalRing* optimized_ring = nullptr;
        SST::Link* external_spike_output_link = nullptr;  // legacy fallback

        // Optional: step tagging for step-limited experiments (naive_raw "no within-step cascade").
        // When active_step_seq != nullptr and *active_step_seq != 0, and packet.step_seq==0:
        //   packet.step_seq = *active_step_seq + step_seq_offset
        const uint32_t* active_step_seq = nullptr;  // 非拥有
        uint32_t step_seq_offset = 0;

        // 投递回调（由 MultiCorePE 提供实现）：NoC 只负责把 packet 投递到目标 endpoint
        std::function<void(int /*endpoint_id*/, NocPacketEvent*)> deliver_to_endpoint;
    };

    struct Stats {
        SST::Statistics::Statistic<uint64_t>* external_spikes_received = nullptr;
        SST::Statistics::Statistic<uint64_t>* external_spikes_sent = nullptr;
        SST::Statistics::Statistic<uint64_t>* inter_core_messages = nullptr;
    };

    ~NocSubsystem();

    void configure(const Config& cfg);
    void bindRuntime(const Runtime& rt);
    void bindStats(const Stats& st);

    // === Output side ===
    void onCoreSend(NocPacketEvent* packet);

    // === INocTransport ===
    void sendFromCore(int src_core, NocPacketEvent* packet) override;
    void injectLocal(int dst_core, NocPacketEvent* packet) override;
    void sendExternal(NocPacketEvent* packet) override;

    // === Input side ===
    void onNicReceiveEvent(SST::Event* event);
    void onNicReceive(NocPacketEvent* packet);
    void onExternalPortEvent(SST::Event* event);
    void onDirectionalLinkEvent(SST::Event* event, const std::string& direction);

    // === Scheduled by MultiCorePE ===
    void drainIncomingQueue(uint64_t current_cycle);
    void tickRing(uint64_t current_cycle);

    size_t incomingQueueSize() const { return incoming_queue_.size(); }
    bool isIdle() const;
    size_t nicPendingSendCount() const;
    int ringPendingMessageCount() const;

private:
    void enqueueIncoming_(NocPacketEvent* packet);
    void sendExternalPacket_(NocPacketEvent* packet);
    void forwardExternalPacket_(NocPacketEvent* packet);
    void routeInternalPacket_(int src_core, int dst_core, NocPacketEvent* packet);
    void tickOptimizedRing_(uint64_t current_cycle);

    Config cfg_{};
    Runtime rt_{};
    Stats st_{};

    std::queue<NocPacketEvent*> incoming_queue_;
};

}} // namespace SST::SnnDL
