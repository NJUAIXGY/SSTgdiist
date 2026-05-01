// -*- c++ -*-
//
// ICoreWorkload: 通用 workload 插件接口（Phase6/Phase3）
// - 由 CoreShell（当前为 control/SnnPESubComponent）装配运行时依赖（NoC + Memory + 统计 sinks）
// - workload 本身不应假设 SNN 语义存在；SNN 将在后续 Phase 中迁为 workload=snn
//

#pragma once

#include <cstddef>
#include <cstdint>
#include <map>
#include <string>

namespace SST {
class Output;
class Params;
} // namespace SST

namespace SST { namespace Statistics {
template <class T>
class Statistic;
}} // namespace SST::Statistics

namespace SST { namespace SnnDL {

class IMemoryAccess;
class INocTransport;
class ISnnAccelRuntimeServices;
class NocPacketEvent;

class ICoreWorkload {
public:
    struct Sinks {
        // Common core-level counters/stats (owned by CoreShell)
        uint64_t* spikes_received = nullptr;
        uint64_t* spikes_generated = nullptr;
        uint64_t* neurons_fired = nullptr;
        uint64_t* synaptic_accesses = nullptr;
        uint64_t* window_spikes_all = nullptr;
        uint64_t* spikes_emitted_window = nullptr;
        SST::Statistics::Statistic<uint64_t>* stat_spikes_received_total = nullptr;
        SST::Statistics::Statistic<uint64_t>* stat_spikes_generated_total = nullptr;
        SST::Statistics::Statistic<uint64_t>* stat_neurons_fired_total = nullptr;
        SST::Statistics::Statistic<uint64_t>* stat_synaptic_accesses_total = nullptr;
        SST::Statistics::Statistic<uint64_t>* stat_compute_active_cycles_total = nullptr;
        SST::Statistics::Statistic<uint64_t>* stat_gas_scatter_spikes_emitted_total = nullptr;

        // Optional: raw counters for aggregation (owned by CoreShell)
        uint64_t* mem_verify_pass = nullptr;
        uint64_t* mem_verify_fail = nullptr;
        uint64_t* pkt_sent = nullptr;
        uint64_t* pkt_recv = nullptr;
        uint64_t* pkt_bad_crc = nullptr;
        uint64_t* pkt_bad_magic = nullptr;

        // Optional: SST stat accumulators (owned by CoreShell/component)
        SST::Statistics::Statistic<uint64_t>* stat_mem_writes_issued_total = nullptr;
        SST::Statistics::Statistic<uint64_t>* stat_mem_reads_issued_total = nullptr;
        SST::Statistics::Statistic<uint64_t>* stat_mem_bytes_written_total = nullptr;
        SST::Statistics::Statistic<uint64_t>* stat_mem_bytes_read_total = nullptr;
        SST::Statistics::Statistic<uint64_t>* stat_mem_verify_pass_total = nullptr;
        SST::Statistics::Statistic<uint64_t>* stat_mem_verify_fail_total = nullptr;
        SST::Statistics::Statistic<uint64_t>* stat_pkt_sent_total = nullptr;
        SST::Statistics::Statistic<uint64_t>* stat_pkt_recv_total = nullptr;
        SST::Statistics::Statistic<uint64_t>* stat_pkt_bad_crc_total = nullptr;
        SST::Statistics::Statistic<uint64_t>* stat_pkt_bad_magic_total = nullptr;

        // Optional: routing/comm stats sinks (owned by CoreShell).
        // Keep generic shape (counters only) so non-SNN workloads can ignore safely.
        uint64_t* route3d_native_activation_total = nullptr;
        uint64_t* route3d_native_gating_activation_total = nullptr;
        uint64_t* route3d_native_direct_activation_total = nullptr;
        uint64_t* route3d_native_unique_sources_total = nullptr;
        SST::Statistics::Statistic<uint64_t>* stat_routes_entries_total = nullptr;
        SST::Statistics::Statistic<uint64_t>* stat_fanout_per_spike_total = nullptr;
        SST::Statistics::Statistic<uint64_t>* stat_route3d_native_activation_total = nullptr;
        SST::Statistics::Statistic<uint64_t>* stat_route3d_native_gating_activation_total = nullptr;
        SST::Statistics::Statistic<uint64_t>* stat_route3d_native_direct_activation_total = nullptr;
        SST::Statistics::Statistic<uint64_t>* stat_route3d_native_unique_sources_total = nullptr;
    };

    struct Reporting {
        // Optional: report to host aggregation (e.g., memory_requests/bytes)
        void* ctx = nullptr;
        void (*report_mem_issue)(void* ctx, size_t bytes) = nullptr;
        // Optional: GAS/window apply+scatter aggregation (workload-level; core aggregates to PE-level stats).
        void (*report_apply_scatter)(void* ctx,
                                     uint64_t acc_updates,
                                     uint64_t posts_touched,
                                     uint64_t spikes_emitted,
                                     uint64_t hwm_bytes,
                                     uint64_t spill_records,
                                     uint64_t spilled_bytes) = nullptr;
        // Optional: SNN receive-side gate diagnostics aggregated per step.
        void (*report_step_rx_gate)(void* ctx,
                                    uint32_t seq,
                                    uint64_t accept_total,
                                    uint64_t reject_refractory_total,
                                    uint64_t direct_accept_total,
                                    uint64_t direct_reject_refractory_total,
                                    uint64_t fastpath_accept_total,
                                    uint64_t fastpath_reject_refractory_total) = nullptr;

        // Optional: GAS/window explicit end handshake (for global step-gate sync).
        // When provided, workload may request ending the current Gather/Scatter stage.
        void (*request_gas_end_gather)(void* ctx, uint32_t superstep) = nullptr;
        void (*request_gas_end_scatter)(void* ctx, uint32_t superstep) = nullptr;
    };

    struct TimeSource {
        void* ctx = nullptr;
        uint64_t (*now_ns)(void* ctx) = nullptr;
    };

    struct Runtime {
        SST::Output* log = nullptr;
        uint32_t node_id = 0;
        uint32_t core_id = 0;
        uint32_t total_nodes = 1;
        uint64_t base_addr = 0;

        IMemoryAccess* mem = nullptr;
        INocTransport* noc = nullptr;
        ISnnAccelRuntimeServices* accel_runtime = nullptr;

        TimeSource time{};
        Sinks sinks{};
        Reporting reporting{};
    };

    virtual ~ICoreWorkload() = default;

    virtual void configureFromParams(const SST::Params& params) = 0;
    virtual void bindRuntime(const Runtime& rt) = 0;

    // Returns true if this cycle performed any work.
    virtual bool onClockTick(uint64_t now_cycle) = 0;

    // Returns true if packet consumed (caller should not delete).
    virtual bool deliverPacket(NocPacketEvent* packet) = 0;

    // === Optional lifecycle hooks (default no-op) ===
    virtual void onInitPhase(unsigned /*phase*/) {}
    virtual void onSetup() {}
    virtual void onFinish() {}
    // Optional: global step start hook (used by step-limited experiments / platform sync).
    virtual void onGlobalStepStart(uint32_t /*seq*/) {}
    // Optional: explicit membrane reset hook (used by step_reset_mem_each_step / seed-only mode).
    virtual void resetMembraneState(float /*v_rest*/) {}

    // === Optional metrics (default empty/zero) ===
    virtual bool hasWork() const { return false; }
    virtual double getUtilization() const { return 0.0; }
    virtual void getStatistics(std::map<std::string, uint64_t>& /*stats*/) const {}
};

}} // namespace SST::SnnDL
