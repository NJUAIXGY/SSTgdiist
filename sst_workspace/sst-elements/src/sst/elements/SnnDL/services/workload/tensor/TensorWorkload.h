// -*- c++ -*-
//
// TensorWorkload: 张量/矩阵加速器（Systolic）周期级 microbench workload
// - 完全非 SNN：不依赖 SpikeEvent / synapse/* / stimulus/*
// - 通过 IMemoryAccess(addr↔bytes) 建模 DMA/DRAM 访问，通过 INocTransport 可选建模跨节点搬运
//

#pragma once

#include <cstddef>
#include <cstdint>
#include <deque>
#include <map>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "api/ICoreWorkload.h"

namespace SST { namespace SnnDL {

class IMemoryAccess;
class INocTransport;
class NocPacketEvent;

class TensorWorkload final : public ICoreWorkload {
public:
    struct Config {
        // Microbench shape (GEMM by default): C[MxN] = A[MxK] * B[KxN]
        uint32_t m = 256;
        uint32_t n = 256;
        uint32_t k = 256;
        uint32_t element_bytes = 2; // default: fp16

        // Systolic array shape (peak MACs/cycle ~= array_m * array_n)
        uint32_t array_m = 32;
        uint32_t array_n = 32;
        float compute_efficiency = 1.0f; // [0,1], applied to peak macs/cycle
        std::string compute_precision = "fp16"; // fp16/bf16/fp32/tf32/int8/fp8
        bool compute_profile_override_enable = false;
	        float compute_throughput_scale = 1.0f;
	        uint32_t compute_pipeline_latency_cycles = 0;
	        // Optional TPU-like systolic wavefront (fill/drain) approximation.
	        // When enabled, extra cycles are added per tile-seg beyond macs/peak throughput.
	        bool mxu_wavefront_enable = false;
	        float mxu_wavefront_alpha = 1.0f;
	        // M30: optional MXU feed/drain bandwidth model (bytes/cycle). 0 = disabled/unlimited.
	        uint64_t mxu_a_bytes_per_cycle = 0;
	        uint64_t mxu_b_bytes_per_cycle = 0;
	        uint64_t mxu_c_bytes_per_cycle = 0;

        // Runtime scheduling
        bool overlap_enable = true; // overlap DMA-read with compute
        uint64_t start_cycle = 1;
        uint32_t iterations = 0; // 0 = run forever (until sim ends)

        // Memory behavior (addr↔bytes)
        bool mem_enable = true;
        uint64_t mem_region_bytes = 1ull << 20; // wrap-around region per core
        uint32_t mem_req_bytes = 64;
        uint32_t mem_max_outstanding = 32;
        // M55/M61: optional memory timing proxy model (row/bank/queue/refresh/command-bus visibility).
        std::string mem_timing_model = "off"; // off/proxy_v2/proxy_v3
        uint32_t mem_bank_groups_per_channel = 1;
        uint32_t mem_banks_per_group = 1;
        uint64_t mem_row_bytes = 8192;
        uint32_t mem_bank_queue_depth = 16;
        std::string mem_sched_policy = "fifo"; // fifo/frfcfs
        uint32_t mem_t_rcd_cycles = 0;
        uint32_t mem_t_cl_cycles = 0;
        uint32_t mem_t_rp_cycles = 0;
        uint32_t mem_t_burst_cycles = 0;
        uint32_t mem_t_ccd_s_cycles = 0;
        uint32_t mem_t_ccd_l_cycles = 0;
        uint32_t mem_refresh_interval_cycles = 0;
        uint32_t mem_refresh_block_cycles = 0;

        // Dataflow + tiling
        std::string dataflow = "os"; // os/ws/is
        uint32_t tile_m = 0; // 0 = use full M
        uint32_t tile_n = 0; // 0 = use full N
        uint32_t tile_k = 0; // 0 = use full K
        // Execution semantics
        // - bulk: legacy iteration-level model (fast; weaker dependency/backpressure semantics)
        // - tile: tile-level model with stalls/backpressure (Level-2 NPU semantics)
        std::string exec_mode = "bulk"; // bulk/tile/program
        // Program mode (M6+): optional command stream (compiled by tensor_spec into a DSL string).
        // Kept as a string so the C++ element does not need a JSON parser.
        std::string program_dsl = "";
        bool program_loop = true;
        uint32_t program_issue_width = 4; // ops/cycle
        // M18+: program-mode UB logical buffers (ping-pong prefetch). Does not change total ub_bytes;
        // it only partitions dependency/overwrite semantics by buffer index.
        uint32_t program_ub_buffers = 1;
        // M20+: allow 1 DMA read + 1 DMA write op to overlap in program mode.
        bool program_dma_dual_enable = false;
        std::string program_engine_priority = "dma>mxu>vec>coll";
        // Vector engine placeholder (for ops like softmax/eltwise) in program mode.
        uint32_t vector_elems_per_cycle = 64;
        uint32_t vector_pipeline_latency_cycles = 0;
        // Tile loop schedule (tile exec only):
        // - auto: choose a reuse-friendly schedule based on dataflow (is->mkn, ws->nkm, os->mnk)
        // - mnk/mkn/nkm: explicit loop order
        std::string tile_schedule = "auto";
        // Writeback policy (tile exec only)
        std::string writeback_policy = "at_end_of_k";

	        // On-chip buffer model (bytes)
	        uint64_t ub_bytes = 0;
	        // Optional dedicated on-chip weight pool capacity (bytes). When 0, ReadB uses the ub_bytes pool.
	        uint64_t weight_bytes = 0;
	        uint64_t acc_bytes = 0;
	        bool onchip_model_enable = false;
        uint64_t ub_bank_bytes = 0;
        uint32_t ub_read_ports = 0;
        uint32_t ub_write_ports = 0;
        bool onchip_bank_model_enable = false;
        uint32_t ub_bank_count = 1;
        std::string ub_bank_select_policy = "interleave";
        std::string ub_bank_conflict_mode = "queue";
        uint64_t acc_bank_bytes = 0;
        uint32_t acc_read_ports = 0;
        uint32_t acc_write_ports = 0;
        uint32_t acc_bank_count = 1;
        std::string acc_bank_select_policy = "interleave";
        std::string acc_bank_conflict_mode = "queue";
        uint32_t bank_queue_depth = 16;
        bool spill_enable = false;
        uint32_t spill_packet_bytes = 256;
        bool spill_share_noc_budget = true;

        // Optional analytical DMA bandwidth (bytes/cycle). 0 = disabled
        uint64_t dma_bandwidth_bytes_per_cycle = 0;
        // Optional shared DMA bandwidth budget across all cores in a PE (bytes/cycle). 0 = disabled.
        // When enabled, each core receives a per-cycle quota derived from this PE-level budget.
        uint64_t dma_shared_bandwidth_bytes_per_cycle = 0;
        // DMA microarchitecture knobs (M29, program-mode focused).
        // Defaults keep legacy behavior (0 = disabled / unlimited).
        uint64_t dma_burst_bytes = 0; // 0 = no burst segmentation
        uint32_t dma_setup_cycles = 0; // setup cost per burst (cycles)
        uint32_t dma_read_engines = 0; // 0 = unlimited issue lanes (legacy)
        uint32_t dma_write_engines = 0; // 0 = unlimited issue lanes (legacy)
        uint32_t dma_max_inflight_per_engine = 0; // 0 = no per-engine inflight cap
        // Optional HBM channel budget model (shared across cores in a PE):
        // - channels: number of independent channels
        // - channel_bandwidth: per-channel budget (bytes/cycle); 0 = disabled
        // - interleave_bytes: channel selection granularity for addr->channel mapping
        uint32_t dma_hbm_channels = 1;
        uint64_t dma_hbm_channel_bandwidth_bytes_per_cycle = 0;
        uint64_t dma_hbm_channel_interleave_bytes = 256;
        bool double_buffer = false;

        std::string collective_type = "none";
        uint64_t collective_bytes = 0;
        uint64_t collective_period_cycles = 0;
        std::string collective_pattern = "ring";
        uint32_t collective_packet_bytes = 256;
        std::string collective_algo = "legacy_bytes";
        uint32_t collective_chunk_bytes = 0;
        uint32_t collective_reduce_overhead_cycles = 0;
        uint32_t collective_max_inflight_chunks = 1;
        bool collective_credit_enable = false;
        uint32_t collective_credit_window_chunks = 0;
        std::string collective_credit_return_mode = "event_on_recv";
        std::string collective_backpressure_mode = "hard";
        uint64_t noc_bandwidth_bytes_per_cycle = 0; // 0 = uncapped (legacy behavior)
        bool collective_overlap_with_compute = true;
        std::string collective_issue_priority = "control_first";
        // 2D torus collective (M8): only used when collective_algo=torus_2d_rs_ag.
        uint32_t collective_2d_dim_x = 0;
        uint32_t collective_2d_dim_y = 0;
        bool collective_2d_row_major = true;
        // If true, treat collective as a barrier between iterations (Level-2).
        bool collective_blocking = false;
        // Collective scope (future extension; currently per_core is the only fully-defined behavior)
        std::string collective_scope = "per_core"; // per_core/per_pe/per_system

        // Optional NoC payload traffic (RawBytes)
        bool comm_enable = false;
        uint64_t comm_period_cycles = 0;
        uint32_t comm_payload_bytes = 0;

        bool strict = true; // if true, missing mem/noc fails fast
        uint64_t seed_base = 0;
    };

    TensorWorkload() = default;
    explicit TensorWorkload(const Config& cfg) : cfg_(cfg) {}

    void configureFromParams(const SST::Params& params) override;
    void bindRuntime(const Runtime& rt) override;

    bool onClockTick(uint64_t now_cycle) override;
    bool deliverPacket(NocPacketEvent* packet) override;
    void onGlobalStepStart(uint32_t seq) override;

    bool hasWork() const override;
    double getUtilization() const override;
    void getStatistics(std::map<std::string, uint64_t>& stats) const override;

private:
    enum class ReqKind : uint8_t { Read = 0, Write = 1 };

    enum class MemTag : uint8_t {
        Generic = 0,
        ReadA = 1,
        ReadB = 2,
        WriteC = 3,
        ProgramDmaRead = 4,
        ProgramDmaWrite = 5,
    };

    struct InflightReq {
        ReqKind kind = ReqKind::Read;
        MemTag tag = MemTag::Generic;
        uint64_t epoch = 0;
        uint32_t bytes = 0;
        uint64_t issue_ns = 0; // best-effort (uses runtime time source; falls back to now_cycle)
        uint64_t proxy_delay_cycles = 0; // M55 proxy delay injected at issue time.
    };

    struct MemTimingBankState {
        bool row_open = false;
        uint64_t open_row = 0;
        uint64_t busy_until_cycle = 0;
        uint64_t last_refresh_cycle = 0;
    };

    struct MemTimingChannelState {
        uint64_t cmd_bus_ready_cycle = 0;
        uint64_t last_cmd_cycle = 0;
        uint32_t last_cmd_bank_group = 0;
        bool last_cmd_valid = false;
    };

	    struct TileSegState {
        bool valid = false;
        uint64_t epoch = 0;
        uint64_t seg_index = 0;
        uint32_t mi = 0;
        uint32_t ni = 0;
        uint32_t ki = 0;

        uint64_t need_a_bytes = 0;
        uint64_t need_b_bytes = 0;
        uint64_t issued_a_bytes = 0;
        uint64_t issued_b_bytes = 0;
        uint64_t done_a_bytes = 0;
        uint64_t done_b_bytes = 0;

	        uint64_t rem_compute_math_cycles = 0;
	        uint64_t rem_compute_pipeline_cycles = 0;
	        uint64_t rem_compute_wavefront_cycles = 0;
	        uint64_t rem_compute_cycles = 0;
	        uint64_t reserved_a_bytes = 0;
	        uint64_t reserved_b_bytes = 0;
	        uint64_t reserved_b_weight_bytes = 0;
	        std::vector<std::pair<uint32_t, uint64_t>> reserved_a_bank_allocs{};
	        std::vector<std::pair<uint32_t, uint64_t>> reserved_b_bank_allocs{};
	        std::vector<std::pair<uint32_t, uint64_t>> reserved_b_weight_bank_allocs{};
	        bool acc_reserved = false;
	    };

    struct WritebackState {
        uint64_t epoch = 0;
        uint32_t mi = 0;
        uint32_t ni = 0;
        uint64_t total_bytes = 0;
        uint64_t issued_bytes = 0;
        uint64_t done_bytes = 0;
    };

    struct ComputeProfile {
        uint64_t profile_id = 0; // fp16=0,bf16=1,fp32=2,tf32=3,int8=4,fp8=5
        float throughput_scale = 1.0f;
        uint32_t pipeline_latency_cycles = 0;
    };

    struct AccTileAlloc {
        uint64_t bytes = 0;
        uint32_t bank = 0;
        uint32_t queue_slots = 0;
    };

    struct CollectiveCreditKey {
        uint32_t seq = 0;
        uint32_t chunk = 0;
        uint32_t step = 0;
        uint32_t peer_node = 0;
        uint16_t peer_core = 0;

        bool operator==(const CollectiveCreditKey& other) const noexcept {
            return seq == other.seq &&
                   chunk == other.chunk &&
                   step == other.step &&
                   peer_node == other.peer_node &&
                   peer_core == other.peer_core;
        }
    };

    struct CollectiveCreditKeyHash {
        size_t operator()(const CollectiveCreditKey& k) const noexcept {
            uint64_t h = static_cast<uint64_t>(k.seq);
            h = (h * 1315423911ull) ^ static_cast<uint64_t>(k.chunk);
            h = (h * 1315423911ull) ^ static_cast<uint64_t>(k.step);
            h = (h * 1315423911ull) ^ static_cast<uint64_t>(k.peer_node);
            h = (h * 1315423911ull) ^ static_cast<uint64_t>(k.peer_core);
            return static_cast<size_t>(h);
        }
    };

    struct CollectiveCreditState {
        uint64_t outstanding = 0;
        std::deque<uint64_t> issue_cycles{};
    };

    enum class ProgramOpKind : uint8_t {
        Gemm = 0,     // legacy (M6) tile-based GEMM
        Allreduce = 1,
        Softmax = 2,
        DmaRead = 3,  // M7: explicit DRAM -> UB
        DmaWrite = 4, // M7: explicit UB -> DRAM
        Fence = 5,    // M7: global fence (drain all engines)
        GemmUb = 6,   // M7: compute placeholder tied to UB dependencies
    };

    struct ProgramOp {
        ProgramOpKind kind = ProgramOpKind::Gemm;
        uint64_t bytes = 0;          // Allreduce/DmaRead/DmaWrite
        uint64_t elems = 0;          // Softmax
        bool blocking = true;        // Allreduce
        uint64_t cycles = 0;         // GemmUb
        uint64_t ub_read_bytes = 0;  // GemmUb
        uint64_t ub_write_bytes = 0; // GemmUb
        // M18+: UB buffer selection + reuse semantics for program ops.
        uint32_t buf = 0;     // DmaRead/DmaWrite/GemmUb
        bool reset = false;   // DmaRead: if true, discard valid bytes in buf at issue (overwrite reuse)
        bool consume = true;  // DmaWrite: if true, consume bytes from buf at issue
        // M22+: address-aware UB regions for program ops.
        bool ub_addr_present = false;       // DmaRead/DmaWrite
        uint64_t ub_addr = 0;               // DmaRead/DmaWrite
        bool ub_read_addr_present = false;  // GemmUb
        uint64_t ub_read_addr = 0;          // GemmUb
        bool ub_write_addr_present = false; // GemmUb
        uint64_t ub_write_addr = 0;         // GemmUb
        // M21+: auto-cycle estimation (when cycles=0) requires explicit op shape.
        uint32_t m = 0;
        uint32_t n = 0;
        uint32_t k = 0;
    };

    static uint64_t ceilDivU64_(uint64_t a, uint64_t b);
    static uint64_t clampNonZero_(uint64_t v, uint64_t fallback);
    static uint64_t splitmix64_next_(uint64_t& x);
    static void fillBytesDeterministic_(uint64_t seed, uint64_t addr, uint32_t seq, std::vector<uint8_t>& out);
    static uint64_t saturatingAddU64_(uint64_t a, uint64_t b);
    static uint64_t saturatingMulU64_(uint64_t a, uint64_t b);
    static uint64_t saturatingMulU64ByU32_(uint64_t a, uint32_t b);
    static uint32_t clampPipelineLatencyCycles_(uint32_t v);
    static ComputeProfile resolveComputeProfile_(const Config& cfg);

    enum class Collective2dStage : uint8_t { RowRS = 0, ColRS = 1, ColAG = 2, RowAG = 3 };

    inline uint64_t peakMacsPerCycle_() const {
        return static_cast<uint64_t>(cfg_.array_m ? cfg_.array_m : 1u) *
               static_cast<uint64_t>(cfg_.array_n ? cfg_.array_n : 1u);
    }

    inline uint64_t effectivePeakMacsPerCycle_() const {
        const uint64_t peak = peakMacsPerCycle_();
        const float eff = (cfg_.compute_efficiency < 0.0f) ? 0.0f : (cfg_.compute_efficiency > 1.0f ? 1.0f : cfg_.compute_efficiency);
        const double scaled_f =
            static_cast<double>(peak) * static_cast<double>(eff) * static_cast<double>(compute_throughput_scale_effective_);
        const uint64_t scaled = static_cast<uint64_t>(scaled_f);
        return scaled ? scaled : 1ull;
    }

    void startIteration_();
    void resetTileIteration_();
    bool generateNextTileSeg_(TileSegState& out);
    bool advanceTileIndices_(uint32_t& mi, uint32_t& ni, uint32_t& ki) const;
    uint64_t tileSegMathCycles_(uint64_t seg_index) const;
    uint64_t tileSegComputeCycles_(uint64_t seg_index) const;
    uint64_t tileNeedReadABytes_(uint32_t mi, uint32_t ni, uint32_t ki) const;
    uint64_t tileNeedReadBBytes_(uint32_t mi, uint32_t ni, uint32_t ki) const;
    void scheduleWriteback_(uint32_t mi, uint32_t ni);
    void retireCompletedWritebacks_();

    uint32_t issueMemReadTagged_(uint32_t max_bytes, MemTag tag, uint64_t epoch);
    uint32_t issueMemWriteTagged_(uint32_t max_bytes, MemTag tag, uint64_t epoch);
    void onMemResponse_(uint64_t req_id, ReqKind kind, MemTag tag, uint64_t epoch, uint32_t bytes);
    void onMemComplete_(ReqKind kind, MemTag tag, uint64_t epoch, uint32_t bytes);
    uint32_t issueMemRead_();
    uint32_t issueMemWrite_();
    bool tickCompute_();
    uint64_t emitCollectiveTraffic_(uint64_t now_cycle, uint64_t noc_budget_bytes, bool& budget_blocked);
    uint64_t emitCommTraffic_(uint64_t now_cycle, uint64_t noc_budget_bytes, bool& budget_blocked);
    void issueNocTraffic_(uint64_t now_cycle,
                          uint64_t& noc_budget,
                          bool& did,
                          bool& did_collective,
                          bool& did_comm,
                          bool& noc_budget_blocked);
    void serviceCollectiveBarrier_(uint64_t now_cycle);
    void onCollectiveControlPacket_(const std::vector<uint8_t>& payload, uint64_t now_cycle);
    void maybeNotifyCollectiveDone_(uint64_t now_cycle);
    void maybeEmitCollectiveRelease_(uint64_t now_cycle);
    void onCollectiveRelease_(uint32_t seq, uint32_t next_seq, uint64_t now_cycle);
    bool collectiveUseEventCreditReturn_() const;
    void onCollectiveCreditIssue_(uint32_t seq,
                                  uint32_t chunk,
                                  uint32_t step,
                                  uint32_t dst_node,
                                  uint16_t dst_core,
                                  uint64_t now_cycle);
    void onCollectiveCreditReturn_(uint32_t seq,
                                   uint32_t chunk,
                                   uint32_t step,
                                   uint32_t credits,
                                   uint32_t src_node,
                                   uint16_t src_core,
                                   uint64_t now_cycle);
    void maybeEmitCollectiveCreditReturn_(const NocPacketEvent* packet, uint64_t now_cycle);
    uint64_t emitCollectiveCreditReturnTraffic_(uint64_t now_cycle,
                                                uint64_t noc_budget_bytes,
                                                bool& budget_blocked);
    uint64_t collectiveRecvBytesForSeq_(uint32_t seq) const;
    bool collectivePendingActive_() const;
    bool onClockTickTile_(uint64_t now_cycle);
    bool onClockTickProgram_(uint64_t now_cycle);
    bool onClockTickProgramM7_(uint64_t now_cycle);
    bool parseProgramDsl_(const std::string& dsl, std::vector<ProgramOp>& out_ops) const;
    uint64_t estimateGemmUbCycles_(uint32_t m, uint32_t n, uint32_t k) const;
    bool startProgramCollective_(uint64_t now_cycle, uint64_t bytes, bool blocking);
    uint32_t collectiveRingStepsPerChunk_() const;
    uint32_t collectiveRingParticipantCount_() const;
    uint32_t collectiveRingChunkPayloadBytes_(uint32_t chunk_index) const;
    uint32_t collectiveRingStepPayloadBytes_(uint32_t chunk_index, uint32_t step_in_chunk) const;
    uint32_t collectiveRingNextDestNode_() const;
    Collective2dStage collective2dStageForStep_(uint32_t step_in_chunk) const;
    uint32_t collective2dNextDestNodeForStep_(uint32_t step_in_chunk) const;
	    void markCollectiveEpochDone_(uint64_t now_cycle);
	    uint32_t selectUbBank_(uint64_t tag_seed);
	    uint32_t selectWeightBank_(uint64_t tag_seed);
	    uint32_t selectAccBank_(uint64_t tag_seed);
    void updateBankQueueOccupancyMax_();
    void resetOnchipCycleState_(uint64_t now_cycle);
	    bool reserveUbBytes_(uint64_t bytes,
	                         uint64_t& spill_budget,
	                         bool& spilled,
	                         bool& spill_budget_blocked,
	                         bool& bank_conflict_blocked,
	                         std::vector<std::pair<uint32_t, uint64_t>>* bank_allocs = nullptr);
	    bool reserveWeightBytes_(uint64_t bytes,
	                             uint64_t& spill_budget,
	                             bool& spilled,
	                             bool& spill_budget_blocked,
	                             bool& bank_conflict_blocked,
	                             std::vector<std::pair<uint32_t, uint64_t>>* bank_allocs = nullptr);
	    void releaseUbBytes_(uint64_t bytes);
	    void releaseUbBankAllocs_(std::vector<std::pair<uint32_t, uint64_t>>& bank_allocs);
	    void releaseWeightBytes_(uint64_t bytes);
	    void releaseWeightBankAllocs_(std::vector<std::pair<uint32_t, uint64_t>>& bank_allocs);
    bool reserveAccTile_(uint32_t mi,
                         uint32_t ni,
                         uint64_t& spill_budget,
                         bool& spilled,
                         bool& spill_budget_blocked,
                         bool& bank_conflict_blocked);
    void releaseAccTile_(uint32_t mi, uint32_t ni);
    bool acquireOnchipReadPorts_(uint32_t ub_ports_needed, uint32_t acc_ports_needed);
    bool acquireOnchipWritePorts_(uint32_t ub_ports_needed, uint32_t acc_ports_needed);
    uint64_t dmaSharedQuotaBytesPerCycle_(uint64_t now_cycle) const;
    uint64_t dmaBudgetBytesPerCycle_(uint64_t now_cycle) const;
    bool hbmChannelBudgetEnabled_() const;
    uint32_t hbmChannelCount_() const;
    bool memTimingProxyEnabled_() const;
    uint32_t memTimingBanksPerChannel_() const;
    uint32_t memTimingBankGroupIndex_(uint64_t off) const;
    uint64_t memTimingServiceQuantumCycles_() const;
    uint32_t memTimingBankIndex_(uint64_t off) const;
    uint64_t memTimingRowIndex_(uint64_t off) const;
    uint64_t memTimingQueueDepthForReq_() const;
    uint64_t memTimingRefreshDelayCycles_(MemTimingBankState& st, uint64_t now_cycle);
    uint64_t memTimingProxyDelayCycles_(ReqKind kind, uint64_t off, uint32_t bytes, uint64_t now_cycle);
    void resetMemTimingState_();
    uint64_t peekNextMemOffset_(ReqKind kind, uint32_t bytes) const;
    uint32_t memOffsetToHbmChannel_(uint64_t off) const;
    uint64_t memOffsetToPhysicalAddr_(uint64_t off) const;
    uint64_t hbmChannelBudgetLeftBytes_(uint64_t now_cycle, uint32_t channel) const;
    void consumeHbmChannelBudget_(uint64_t now_cycle, uint32_t channel, uint32_t bytes);
    uint32_t clampBytesByHbmChannelBudget_(uint64_t now_cycle, ReqKind kind, uint32_t want, uint32_t& out_channel) const;
    uint64_t nowNs_() const;

    inline bool commReady_() const { return cfg_.comm_enable && rt_.noc && cfg_.comm_period_cycles > 0 && cfg_.comm_payload_bytes > 0; }
    inline bool collectiveReady_() const {
        if (cfg_.collective_type == "none" || !rt_.noc) return false;
        if (cfg_.exec_mode == "program") return true; // explicit collectives via program ops
        return (cfg_.collective_bytes > 0 && cfg_.collective_period_cycles > 0);
    }
	    inline bool tileModelEnabled_() const {
	        return (cfg_.tile_m > 0 || cfg_.tile_n > 0 || cfg_.tile_k > 0 ||
	                cfg_.ub_bytes > 0 || cfg_.weight_bytes > 0 || cfg_.acc_bytes > 0 ||
	                cfg_.dma_bandwidth_bytes_per_cycle > 0 || cfg_.dma_shared_bandwidth_bytes_per_cycle > 0 ||
	                cfg_.onchip_model_enable);
	    }

    Config cfg_{};
    Runtime rt_{};

    bool configured_ = false;
    bool started_ = false;
    bool step_gated_ = false; // enabled when onGlobalStepStart() is observed
    bool step_open_ = false;  // when step_gated_: allow running one iteration in current step
    uint32_t step_seq_ = 0;
    bool close_step_on_iter_done_ = true;

    // Derived per-iteration workload
    uint64_t bytes_read_per_iter_ = 0;
    uint64_t bytes_write_per_iter_ = 0;
    uint64_t mac_ops_per_iter_ = 0;
    uint64_t compute_math_cycles_per_iter_ = 0;
    uint64_t compute_pipeline_cycles_per_iter_ = 0;
    uint64_t compute_cycles_per_iter_ = 0;
    uint64_t dram_bytes_per_iter_ = 0;
    uint64_t onchip_bytes_per_iter_ = 0;
    uint64_t dma_cycles_per_iter_ = 0;
    uint64_t tile_count_per_iter_ = 0;

    // Iteration state
    uint32_t iter_done_ = 0;
    uint32_t iter_seq_ = 1;
    bool iter_active_ = false;
    uint64_t rem_read_bytes_ = 0;
    uint64_t rem_write_bytes_ = 0;
    uint64_t rem_compute_math_cycles_ = 0;
    uint64_t rem_compute_pipeline_cycles_ = 0;
    uint64_t rem_compute_cycles_ = 0;
    uint64_t rem_macs_ = 0;
    bool compute_started_ = false;

    // Tile-mode derived params (exec_mode=tile)
    std::string tile_schedule_eff_ = "mnk";
    bool tile_keep_a_ = false;
    bool tile_keep_b_ = false;
    uint32_t tile_tm_ = 1;
    uint32_t tile_tn_ = 1;
    uint32_t tile_tk_ = 1;
    uint32_t tile_mt_ = 1;
    uint32_t tile_nt_ = 1;
    uint32_t tile_kt_ = 1;
    uint64_t tile_a_bytes_ = 0;
    uint64_t tile_b_bytes_ = 0;
    uint64_t tile_c_bytes_ = 0;
    uint64_t tile_seg_math_cycles_base_ = 0;
    uint64_t tile_seg_math_cycles_remainder_ = 0;

    // Tile-mode iteration state
    bool tile_mode_active_ = false;
    uint64_t tile_seg_gen_index_ = 0;
    uint32_t tile_gen_mi_ = 0;
    uint32_t tile_gen_ni_ = 0;
    uint32_t tile_gen_ki_ = 0;
    bool tile_gen_done_ = false;
    uint64_t tile_seg_done_ = 0;
    TileSegState tile_cur_{};
    TileSegState tile_next_{};

    // Tile-mode writeback queue
    std::deque<uint64_t> tile_writeback_queue_{};
    std::unordered_map<uint64_t, WritebackState> tile_writebacks_{};

    uint64_t read_off_ = 0;
    uint64_t write_off_ = 0;

    std::unordered_map<uint64_t, InflightReq> inflight_;
    std::vector<MemTimingBankState> mem_timing_banks_{};
    std::vector<MemTimingChannelState> mem_timing_channels_{};

    // Activity & counters (per-core; MultiCorePE pulls via getStatistics())
    uint64_t total_cycles_ = 0;
    uint64_t active_cycles_ = 0;
    uint64_t memory_requests_ = 0;
    uint64_t now_cycle_cached_ = 0; // for best-effort timing when runtime time source is absent

    uint64_t tensor_mem_reads_issued_total_ = 0;
    uint64_t tensor_mem_writes_issued_total_ = 0;
    uint64_t tensor_mem_bytes_read_total_ = 0;
    uint64_t tensor_mem_bytes_write_total_ = 0;
    uint64_t tensor_mem_read_latency_cycles_total_ = 0;
    uint64_t tensor_mem_read_latency_cycles_max_ = 0;
    uint64_t tensor_mem_read_latency_samples_total_ = 0;
    uint64_t tensor_mem_write_latency_cycles_total_ = 0;
    uint64_t tensor_mem_write_latency_cycles_max_ = 0;
    uint64_t tensor_mem_write_latency_samples_total_ = 0;
    uint64_t tensor_mem_row_hit_total_ = 0;
    uint64_t tensor_mem_row_miss_total_ = 0;
    uint64_t tensor_mem_row_conflict_total_ = 0;
    uint64_t tensor_mem_bank_queue_full_total_ = 0;
    uint64_t tensor_mem_bank_queue_wait_cycles_total_ = 0;
    uint64_t tensor_mem_sched_fifo_pick_total_ = 0;
    uint64_t tensor_mem_sched_frfcfs_pick_total_ = 0;
    uint64_t tensor_mem_cmd_act_total_ = 0;
    uint64_t tensor_mem_cmd_pre_total_ = 0;
    uint64_t tensor_mem_cmd_rdwr_total_ = 0;
    uint64_t tensor_mem_row_service_cycles_total_ = 0;
    uint64_t tensor_mem_refresh_block_cycles_total_ = 0;
    uint64_t tensor_mem_proxy_delay_cycles_total_ = 0;
    uint64_t tensor_mem_proxy_delay_cycles_max_ = 0;
    uint64_t tensor_mem_bank_active_cycles_total_ = 0;
    uint64_t tensor_mem_cmd_queue_slots_total_ = 0;
    uint64_t tensor_mem_cmd_queue_depth_max_ = 0;
    uint64_t tensor_mem_cmd_bus_wait_cycles_total_ = 0;
    uint64_t tensor_mem_cmd_bus_bg_switch_total_ = 0;
    uint64_t tensor_mem_cmd_issue_total_ = 0;
    uint64_t tensor_compute_cycles_total_ = 0;
    uint64_t tensor_compute_math_cycles_total_ = 0;
    uint64_t tensor_compute_pipeline_cycles_total_ = 0;
    uint64_t tensor_mxu_wavefront_cycles_total_ = 0;
    uint64_t tensor_mxu_io_busy_cycles_total_ = 0;
    uint64_t tensor_compute_precision_profile_id_ = 0;
    uint64_t tensor_mac_ops_total_ = 0;
    uint64_t tensor_dma_stall_cycles_total_ = 0;
    uint64_t tensor_iter_cycles_total_ = 0;
    uint64_t tensor_stall_dma_budget_cycles_total_ = 0;
    uint64_t tensor_stall_dma_hbm_channel_budget_cycles_total_ = 0;
    uint64_t tensor_stall_mem_outstanding_cycles_total_ = 0;
    uint64_t tensor_stall_wait_read_cycles_total_ = 0;
    uint64_t tensor_stall_wait_write_cycles_total_ = 0;
    uint64_t tensor_stall_collective_cycles_total_ = 0;
    uint64_t tensor_stall_onchip_capacity_cycles_total_ = 0;
    uint64_t tensor_stall_onchip_port_cycles_total_ = 0;
    uint64_t tensor_stall_onchip_bank_conflict_cycles_total_ = 0;
    uint64_t tensor_stall_spill_budget_cycles_total_ = 0;
    uint64_t tensor_dma_cycles_total_ = 0;
    uint64_t tensor_dram_bytes_total_ = 0;
    uint64_t tensor_onchip_bytes_total_ = 0;
    uint64_t tensor_tile_count_total_ = 0;
    uint64_t tensor_spill_bytes_total_ = 0;
    uint64_t tensor_spill_pkts_total_ = 0;
    uint64_t tensor_collective_bytes_sent_total_ = 0;
    uint64_t tensor_collective_bytes_recv_total_ = 0;
    uint64_t tensor_collective_pkts_sent_total_ = 0;
    uint64_t tensor_collective_pkts_recv_total_ = 0;
    uint64_t tensor_collective_cycles_total_ = 0;
    uint64_t tensor_collective_pending_cycles_total_ = 0;
    uint64_t tensor_collective_issue_cycles_total_ = 0;
    uint64_t tensor_collective_chunk_groups_total_ = 0;
    uint64_t tensor_collective_ring_steps_total_ = 0;
    uint64_t tensor_collective_2d_row_rs_steps_total_ = 0;
    uint64_t tensor_collective_2d_col_rs_steps_total_ = 0;
    uint64_t tensor_collective_2d_col_ag_steps_total_ = 0;
    uint64_t tensor_collective_2d_row_ag_steps_total_ = 0;
    uint64_t tensor_collective_2d_row_rs_bytes_sent_total_ = 0;
    uint64_t tensor_collective_2d_col_rs_bytes_sent_total_ = 0;
    uint64_t tensor_collective_2d_col_ag_bytes_sent_total_ = 0;
    uint64_t tensor_collective_2d_row_ag_bytes_sent_total_ = 0;
    uint64_t tensor_collective_reduce_wait_cycles_total_ = 0;
    uint64_t tensor_collective_2d_reduce_wait_cycles_total_ = 0;
    uint64_t tensor_collective_epoch_done_total_ = 0;
    uint64_t tensor_collective_epoch_latency_cycles_total_ = 0;
    uint64_t tensor_collective_epoch_latency_cycles_max_ = 0;
    uint64_t tensor_collective_algo_id_ = 0;
    uint64_t tensor_collective_credit_stall_cycles_total_ = 0;
    uint64_t tensor_collective_backpressure_stall_cycles_total_ = 0;
    uint64_t tensor_collective_inflight_chunks_max_ = 0;
    uint64_t tensor_collective_credit_return_pkts_sent_total_ = 0;
    uint64_t tensor_collective_credit_return_pkts_recv_total_ = 0;
    uint64_t tensor_collective_credit_return_orphan_total_ = 0;
    uint64_t tensor_collective_credit_return_dup_total_ = 0;
    uint64_t tensor_collective_credit_return_latency_cycles_total_ = 0;
    uint64_t tensor_collective_credit_return_latency_cycles_max_ = 0;
    uint64_t tensor_bank_queue_occupancy_max_ = 0;
    uint64_t tensor_stall_noc_budget_cycles_total_ = 0;
    uint64_t tensor_overlap_compute_collective_cycles_total_ = 0;
    uint64_t tensor_overlap_compute_mem_cycles_total_ = 0;
    uint64_t tensor_vector_cycles_total_ = 0;
    uint64_t tensor_program_ops_total_ = 0;
    uint64_t tensor_program_iters_total_ = 0;
    uint64_t tensor_program_any_busy_cycles_total_ = 0;
    uint64_t tensor_program_dma_busy_cycles_total_ = 0;
    uint64_t tensor_program_mxu_busy_cycles_total_ = 0;
    uint64_t tensor_program_vec_busy_cycles_total_ = 0;
    uint64_t tensor_program_coll_busy_cycles_total_ = 0;
    uint64_t tensor_program_fence_count_total_ = 0;
    uint64_t tensor_program_fence_wait_cycles_total_ = 0;
    uint64_t tensor_program_ub_stall_cycles_total_ = 0;
    uint64_t tensor_program_mem_stall_cycles_total_ = 0;
    uint64_t tensor_program_ub_occupancy_bytes_max_ = 0;

    uint64_t comm_last_cycle_ = 0;
    uint64_t collective_last_cycle_ = 0;
    uint64_t collective_seq_ = 0;
    bool collective_pending_active_ = false;
    uint64_t collective_active_bytes_ = 0; // payload bytes for the currently-active collective op (program/periodic)
    uint32_t collective_pending_seq_ = 0;
    uint64_t collective_pending_total_bytes_ = 0;
    uint64_t collective_pending_sent_bytes_ = 0;
    size_t collective_pending_next_dest_ = 0;
    std::vector<uint32_t> collective_pending_dest_nodes_{};
    std::vector<uint64_t> collective_pending_dest_remaining_bytes_{};
    bool collective_epoch_active_ = false;
    uint32_t collective_epoch_seq_ = 0;
    uint64_t collective_epoch_expected_recv_bytes_ = 0;
    uint64_t collective_epoch_recv_bytes_ = 0;
    uint64_t collective_epoch_start_cycle_ = 0;
    bool collective_done_notified_ = false;
    bool collective_release_pending_ = false; // leader/root: pending broadcast of release for current seq
    uint32_t collective_release_pending_seq_ = 0;
    uint32_t total_cores_cfg_ = 1; // per-PE cores (from control param total_cores)
    uint32_t collective_barrier_done_count_ = 0;
    std::vector<uint8_t> collective_barrier_done_bitmap_{};
    std::unordered_map<uint32_t, uint64_t> collective_recv_bytes_by_seq_{};
    bool collective_ring_active_ = false;
    uint32_t collective_ring_seq_ = 0;
    uint32_t collective_ring_chunks_total_ = 0;
    uint32_t collective_ring_steps_per_chunk_ = 0;
    uint32_t collective_ring_chunk_index_ = 0;
    uint32_t collective_ring_step_index_ = 0;
    uint32_t collective_ring_step_remaining_bytes_ = 0;
    uint32_t collective_ring_max_inflight_chunks_ = 1;
    uint64_t collective_ring_reduce_wait_cycles_remaining_ = 0;
    uint64_t collective_ring_total_payload_bytes_ = 0;
    uint64_t collective_ring_sent_payload_bytes_ = 0;
    bool collective_2d_active_ = false;
    uint32_t collective_2d_dim_x_ = 0;
    uint32_t collective_2d_dim_y_ = 0;
    uint32_t collective_2d_row_hop_ = 0;
    uint32_t collective_2d_col_hop_ = 0;
    std::unordered_map<uint64_t, AccTileAlloc> acc_reserved_tiles_{};
    uint64_t collective_credit_inflight_chunks_ = 0;
    std::unordered_map<CollectiveCreditKey, CollectiveCreditState, CollectiveCreditKeyHash> collective_credit_outstanding_{};
    std::unordered_set<CollectiveCreditKey, CollectiveCreditKeyHash> collective_credit_return_seen_{};
    std::unordered_map<CollectiveCreditKey, uint64_t, CollectiveCreditKeyHash> collective_credit_return_pending_credits_{};
    std::deque<CollectiveCreditKey> collective_credit_return_pending_queue_{};

    enum class OnchipPoolKind : uint8_t { Ub = 0, Weight = 1 };
    struct ResidentTileAlloc {
        OnchipPoolKind pool = OnchipPoolKind::Ub;
        uint64_t bytes = 0;
        std::vector<std::pair<uint32_t, uint64_t>> bank_allocs{};
    };
    std::unordered_map<uint64_t, ResidentTileAlloc> a_resident_tiles_{}; // key=(mi<<32)|ki
    std::unordered_map<uint64_t, ResidentTileAlloc> b_resident_tiles_{}; // key=(ni<<32)|ki

    uint64_t onchip_ub_occupancy_bytes_ = 0;
    uint64_t onchip_weight_occupancy_bytes_ = 0;
    uint64_t onchip_acc_occupancy_bytes_ = 0;
    std::vector<uint64_t> onchip_ub_bank_occupancy_bytes_{};
    std::vector<uint64_t> onchip_weight_bank_occupancy_bytes_{};
    std::vector<uint64_t> onchip_acc_bank_occupancy_bytes_{};
    std::vector<uint32_t> onchip_ub_bank_queue_occupancy_{};
    std::vector<uint32_t> onchip_weight_bank_queue_occupancy_{};
    std::vector<uint32_t> onchip_acc_bank_queue_occupancy_{};
    uint32_t onchip_ub_bank_rr_ = 0;
    uint32_t onchip_weight_bank_rr_ = 0;
    uint32_t onchip_acc_bank_rr_ = 0;
    uint64_t onchip_cycle_tag_ = 0;
    uint32_t onchip_ub_read_ports_used_ = 0;
    uint32_t onchip_ub_write_ports_used_ = 0;
    uint32_t onchip_acc_read_ports_used_ = 0;
    uint32_t onchip_acc_write_ports_used_ = 0;
    uint64_t tensor_pkt_sent_total_ = 0;
    uint64_t tensor_pkt_recv_total_ = 0;
    uint64_t tensor_pkt_bytes_sent_total_ = 0;
    uint64_t tensor_pkt_bytes_recv_total_ = 0;
    uint64_t tensor_onchip_weight_occupancy_bytes_max_ = 0;
    uint64_t tensor_onchip_weight_bank_occupancy_bytes_max_ = 0;
    uint64_t tensor_onchip_a_resident_tiles_max_ = 0;
    uint64_t tensor_onchip_b_resident_tiles_max_ = 0;
    float compute_throughput_scale_effective_ = 1.0f;
    uint32_t compute_pipeline_latency_cycles_effective_ = 0;

    // Program mode state (M6+)
    std::vector<ProgramOp> program_ops_{};
    bool program_loop_enable_ = true;
    uint32_t program_iter_done_ = 0;
    size_t program_pc_ = 0;
    bool program_op_started_ = false;
    uint64_t program_softmax_rem_cycles_ = 0;
    bool program_gemm_started_ = false;
    bool program_collective_started_ = false;

    // Program mode state (M7): command-stream + multi-engine overlap
    struct ProgramDmaSlot {
        bool active = false;
        bool is_read = true;
        uint32_t buf = 0;
        bool ub_addr_present = false;
        uint64_t ub_addr = 0;
        uint64_t epoch = 0;
        uint64_t total_bytes = 0;
        uint64_t issued_bytes = 0;
        uint64_t done_bytes = 0;
        // M29: burst/setup and per-slot inflight tracking.
        uint32_t setup_cycles_rem = 0;
        uint64_t burst_bytes_rem = 0;
        uint32_t inflight_reqs = 0;
    };

    struct ProgramMxuSlot {
        bool active = false;
        uint32_t buf = 0;
        bool ub_write_addr_present = false;
        uint64_t ub_write_addr = 0;
        uint64_t rem_cycles = 0;
        uint64_t ub_read_bytes = 0;
        uint64_t ub_write_bytes = 0;
        uint64_t ub_write_reserved_bytes = 0;
        // M33: per-cycle IO budget tracking (split A/B) for program-mode gemm_ub.
        uint64_t ub_read_a_bytes_rem = 0;
        uint64_t ub_read_b_bytes_rem = 0;
        uint64_t ub_write_bytes_rem = 0;
    };

    struct ProgramVecSlot {
        bool active = false;
        uint64_t rem_cycles = 0;
    };

    struct ProgramCollSlot {
        bool active = false;
        uint64_t bytes = 0;
        bool blocking = true;
    };

    struct ProgramUbRegion {
        uint64_t size_bytes = 0;
        uint64_t reserved_bytes = 0;
        uint64_t valid_bytes = 0;
    };

    bool program_m7_enable_ = false;
    bool program_fence_pending_ = false;
    bool program_addr_aware_enable_ = false;
    std::vector<uint64_t> program_ub_reserved_bytes_by_buf_{};
    std::vector<uint64_t> program_ub_valid_bytes_by_buf_{};
    std::vector<std::unordered_map<uint64_t, ProgramUbRegion>> program_ub_regions_by_buf_{};
    uint64_t program_dma_epoch_next_ = 1;
    ProgramDmaSlot program_dma_read_slot_{};
    ProgramDmaSlot program_dma_write_slot_{};
    ProgramMxuSlot program_mxu_slot_{};
    ProgramVecSlot program_vec_slot_{};
    ProgramCollSlot program_coll_slot_{};
};

}} // namespace SST::SnnDL
