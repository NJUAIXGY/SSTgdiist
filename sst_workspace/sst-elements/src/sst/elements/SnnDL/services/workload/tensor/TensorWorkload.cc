// -*- c++ -*-

#include <sst/core/sst_config.h>

#include "workload/tensor/TensorWorkload.h"

#include <sst/core/output.h>
#include <sst/core/params.h>

#include "IMemoryAccess.h"
#include "INocTransport.h"
#include "NocPacketEvent.h"

#include <algorithm>
#include <cmath>
#include <cctype>
#include <cstdint>
#include <cstring>
#include <limits>

namespace SST { namespace SnnDL {

namespace {

inline uint64_t clamp_u64_(uint64_t v, uint64_t lo, uint64_t hi) {
    if (v < lo) return lo;
    if (v > hi) return hi;
    return v;
}

struct DmaSharedBudgetState_ {
    uint64_t cycle_tag = 0;
    uint32_t rr_start = 0;
    bool rr_init = false;
};

// Per-rank (per-process) shared DMA budget state keyed by PE/node_id.
// This models a PE-local shared DMA/HBM bandwidth budget; no cross-rank coherence is required.
static std::unordered_map<uint64_t, DmaSharedBudgetState_> g_dma_shared_budget_state_;

struct HbmChannelBudgetState_ {
    uint64_t cycle_tag = 0;
    std::vector<uint64_t> left{};
};

// Per-rank (per-process) shared HBM channel budget state keyed by PE/node_id.
// This models per-channel bandwidth contention inside a PE; no cross-rank coherence is required.
static std::unordered_map<uint64_t, HbmChannelBudgetState_> g_hbm_channel_budget_state_;

inline std::string to_lower_copy_(const std::string& s) {
    std::string out;
    out.reserve(s.size());
    for (char ch : s) out.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(ch))));
    return out;
}

inline bool has_collective_magic_(const std::vector<uint8_t>& payload) {
    return payload.size() >= 4 &&
           payload[0] == static_cast<uint8_t>('C') &&
           payload[1] == static_cast<uint8_t>('O') &&
           payload[2] == static_cast<uint8_t>('L') &&
           payload[3] == static_cast<uint8_t>('L');
}

inline bool has_magic4_(const std::vector<uint8_t>& payload, char a, char b, char c, char d) {
    return payload.size() >= 4 &&
           payload[0] == static_cast<uint8_t>(a) &&
           payload[1] == static_cast<uint8_t>(b) &&
           payload[2] == static_cast<uint8_t>(c) &&
           payload[3] == static_cast<uint8_t>(d);
}

inline uint32_t read_u32_le_(const std::vector<uint8_t>& payload, size_t off) {
    if (off + 4 > payload.size()) return 0;
    return static_cast<uint32_t>(payload[off]) |
           (static_cast<uint32_t>(payload[off + 1]) << 8) |
           (static_cast<uint32_t>(payload[off + 2]) << 16) |
           (static_cast<uint32_t>(payload[off + 3]) << 24);
}

inline void write_u32_le_(std::vector<uint8_t>& payload, size_t off, uint32_t v) {
    if (off + 4 > payload.size()) return;
    payload[off] = static_cast<uint8_t>(v & 0xffu);
    payload[off + 1] = static_cast<uint8_t>((v >> 8) & 0xffu);
    payload[off + 2] = static_cast<uint8_t>((v >> 16) & 0xffu);
    payload[off + 3] = static_cast<uint8_t>((v >> 24) & 0xffu);
}

} // namespace

uint64_t TensorWorkload::ceilDivU64_(uint64_t a, uint64_t b) {
    if (b == 0) return a;
    return (a + b - 1) / b;
}

uint64_t TensorWorkload::clampNonZero_(uint64_t v, uint64_t fallback) {
    if (v != 0) return v;
    return fallback ? fallback : 1ull;
}

uint64_t TensorWorkload::saturatingAddU64_(uint64_t a, uint64_t b) {
    const uint64_t kMax = std::numeric_limits<uint64_t>::max();
    if (kMax - a < b) return kMax;
    return a + b;
}

uint64_t TensorWorkload::saturatingMulU64_(uint64_t a, uint64_t b) {
    if (a == 0 || b == 0) return 0;
    const uint64_t kMax = std::numeric_limits<uint64_t>::max();
    if (a > (kMax / b)) return kMax;
    return a * b;
}

uint64_t TensorWorkload::saturatingMulU64ByU32_(uint64_t a, uint32_t b) {
    return saturatingMulU64_(a, static_cast<uint64_t>(b));
}

uint32_t TensorWorkload::clampPipelineLatencyCycles_(uint32_t v) {
    constexpr uint32_t kMaxPipelineLatency = 4096u;
    return static_cast<uint32_t>(std::min<uint64_t>(v, kMaxPipelineLatency));
}

TensorWorkload::ComputeProfile TensorWorkload::resolveComputeProfile_(const Config& cfg) {
    ComputeProfile out{};
    std::string precision = to_lower_copy_(cfg.compute_precision);

    if (precision == "bf16") {
        out.profile_id = 1;
        out.throughput_scale = 1.0f;
        out.pipeline_latency_cycles = 0;
    } else if (precision == "fp32") {
        out.profile_id = 2;
        out.throughput_scale = 0.5f;
        out.pipeline_latency_cycles = 2;
    } else if (precision == "tf32") {
        out.profile_id = 3;
        out.throughput_scale = 0.75f;
        out.pipeline_latency_cycles = 1;
    } else if (precision == "int8") {
        out.profile_id = 4;
        out.throughput_scale = 2.0f;
        out.pipeline_latency_cycles = 0;
    } else if (precision == "fp8") {
        out.profile_id = 5;
        out.throughput_scale = 2.0f;
        out.pipeline_latency_cycles = 0;
    } else {
        // default/fallback: fp16
        out.profile_id = 0;
        out.throughput_scale = 1.0f;
        out.pipeline_latency_cycles = 0;
    }

    if (cfg.compute_profile_override_enable) {
        const float override_scale = cfg.compute_throughput_scale;
        out.throughput_scale = (override_scale > 0.0f) ? override_scale : 1.0f;
        out.pipeline_latency_cycles = clampPipelineLatencyCycles_(cfg.compute_pipeline_latency_cycles);
    } else {
        out.pipeline_latency_cycles = clampPipelineLatencyCycles_(out.pipeline_latency_cycles);
    }

    return out;
}

uint64_t TensorWorkload::splitmix64_next_(uint64_t& x) {
    x += 0x9e3779b97f4a7c15ULL;
    uint64_t z = x;
    z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
    z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
    return z ^ (z >> 31);
}

void TensorWorkload::fillBytesDeterministic_(uint64_t seed,
                                            uint64_t addr,
                                            uint32_t seq,
                                            std::vector<uint8_t>& out) {
    uint64_t rng = seed ^ addr ^ (static_cast<uint64_t>(seq) << 1) ^ 0x54454e534f52ULL; // "TENSOR"
    size_t pos = 0;
    while (pos < out.size()) {
        const uint64_t v = splitmix64_next_(rng);
        const size_t n = std::min<size_t>(8, out.size() - pos);
        std::memcpy(out.data() + pos, &v, n);
        pos += n;
    }
}

uint64_t TensorWorkload::nowNs_() const {
    if (rt_.time.now_ns) return rt_.time.now_ns(rt_.time.ctx);
    // Fallback: best-effort (legacy behavior assumes 1GHz => 1 cycle == 1ns anyway).
    return now_cycle_cached_;
}

void TensorWorkload::configureFromParams(const SST::Params& params) {
    cfg_.m = params.find<uint32_t>("tensor_m", cfg_.m);
    cfg_.n = params.find<uint32_t>("tensor_n", cfg_.n);
    cfg_.k = params.find<uint32_t>("tensor_k", cfg_.k);
    cfg_.element_bytes = params.find<uint32_t>("tensor_element_bytes", cfg_.element_bytes);

    cfg_.array_m = params.find<uint32_t>("tensor_array_m", cfg_.array_m);
    cfg_.array_n = params.find<uint32_t>("tensor_array_n", cfg_.array_n);
    cfg_.compute_efficiency = params.find<float>("tensor_compute_efficiency", cfg_.compute_efficiency);
    cfg_.compute_precision = to_lower_copy_(params.find<std::string>("tensor_compute_precision", cfg_.compute_precision));
    cfg_.compute_profile_override_enable =
        params.find<int>("tensor_compute_profile_override_enable", cfg_.compute_profile_override_enable ? 1 : 0) != 0;
    cfg_.compute_throughput_scale = params.find<float>("tensor_compute_throughput_scale", cfg_.compute_throughput_scale);
    cfg_.compute_pipeline_latency_cycles =
        params.find<uint32_t>("tensor_compute_pipeline_latency_cycles", cfg_.compute_pipeline_latency_cycles);
    cfg_.mxu_wavefront_enable =
        params.find<int>("tensor_mxu_wavefront_enable", cfg_.mxu_wavefront_enable ? 1 : 0) != 0;
    cfg_.mxu_wavefront_alpha = params.find<float>("tensor_mxu_wavefront_alpha", cfg_.mxu_wavefront_alpha);
    if (!(cfg_.mxu_wavefront_alpha >= 0.0f)) cfg_.mxu_wavefront_alpha = 0.0f;
    cfg_.mxu_a_bytes_per_cycle = params.find<uint64_t>("tensor_mxu_a_bytes_per_cycle", cfg_.mxu_a_bytes_per_cycle);
    cfg_.mxu_b_bytes_per_cycle = params.find<uint64_t>("tensor_mxu_b_bytes_per_cycle", cfg_.mxu_b_bytes_per_cycle);
    cfg_.mxu_c_bytes_per_cycle = params.find<uint64_t>("tensor_mxu_c_bytes_per_cycle", cfg_.mxu_c_bytes_per_cycle);

    cfg_.overlap_enable = params.find<int>("tensor_overlap_enable", cfg_.overlap_enable ? 1 : 0) != 0;
    cfg_.start_cycle = params.find<uint64_t>("tensor_start_cycle", cfg_.start_cycle);
    cfg_.iterations = params.find<uint32_t>("tensor_iterations", cfg_.iterations);

    cfg_.mem_enable = params.find<int>("tensor_mem_enable", cfg_.mem_enable ? 1 : 0) != 0;
    cfg_.mem_region_bytes = params.find<uint64_t>("tensor_mem_region_bytes", cfg_.mem_region_bytes);
    cfg_.mem_req_bytes = params.find<uint32_t>("tensor_mem_req_bytes", cfg_.mem_req_bytes);
    cfg_.mem_max_outstanding = params.find<uint32_t>("tensor_mem_max_outstanding", cfg_.mem_max_outstanding);
    cfg_.mem_timing_model = to_lower_copy_(params.find<std::string>("tensor_mem_timing_model", cfg_.mem_timing_model));
    cfg_.mem_bank_groups_per_channel =
        params.find<uint32_t>("tensor_mem_bank_groups_per_channel", cfg_.mem_bank_groups_per_channel);
    cfg_.mem_banks_per_group = params.find<uint32_t>("tensor_mem_banks_per_group", cfg_.mem_banks_per_group);
    cfg_.mem_row_bytes = params.find<uint64_t>("tensor_mem_row_bytes", cfg_.mem_row_bytes);
    cfg_.mem_bank_queue_depth = params.find<uint32_t>("tensor_mem_bank_queue_depth", cfg_.mem_bank_queue_depth);
    cfg_.mem_sched_policy = to_lower_copy_(params.find<std::string>("tensor_mem_sched_policy", cfg_.mem_sched_policy));
    cfg_.mem_t_rcd_cycles = params.find<uint32_t>("tensor_mem_t_rcd_cycles", cfg_.mem_t_rcd_cycles);
    cfg_.mem_t_cl_cycles = params.find<uint32_t>("tensor_mem_t_cl_cycles", cfg_.mem_t_cl_cycles);
    cfg_.mem_t_rp_cycles = params.find<uint32_t>("tensor_mem_t_rp_cycles", cfg_.mem_t_rp_cycles);
    cfg_.mem_t_burst_cycles = params.find<uint32_t>("tensor_mem_t_burst_cycles", cfg_.mem_t_burst_cycles);
    cfg_.mem_t_ccd_s_cycles = params.find<uint32_t>("tensor_mem_t_ccd_s_cycles", cfg_.mem_t_ccd_s_cycles);
    cfg_.mem_t_ccd_l_cycles = params.find<uint32_t>("tensor_mem_t_ccd_l_cycles", cfg_.mem_t_ccd_l_cycles);
    cfg_.mem_refresh_interval_cycles =
        params.find<uint32_t>("tensor_mem_refresh_interval_cycles", cfg_.mem_refresh_interval_cycles);
    cfg_.mem_refresh_block_cycles =
        params.find<uint32_t>("tensor_mem_refresh_block_cycles", cfg_.mem_refresh_block_cycles);

    cfg_.dataflow = to_lower_copy_(params.find<std::string>("tensor_dataflow", cfg_.dataflow));
    cfg_.tile_m = params.find<uint32_t>("tensor_tile_m", cfg_.tile_m);
    cfg_.tile_n = params.find<uint32_t>("tensor_tile_n", cfg_.tile_n);
    cfg_.tile_k = params.find<uint32_t>("tensor_tile_k", cfg_.tile_k);
    cfg_.exec_mode = to_lower_copy_(params.find<std::string>("tensor_exec_mode", cfg_.exec_mode));
    cfg_.program_dsl = params.find<std::string>("tensor_program_dsl", cfg_.program_dsl);
    cfg_.program_loop = params.find<int>("tensor_program_loop", cfg_.program_loop ? 1 : 0) != 0;
    cfg_.program_issue_width = params.find<uint32_t>("tensor_program_issue_width", cfg_.program_issue_width);
    cfg_.program_ub_buffers = std::max<uint32_t>(1u, params.find<uint32_t>("tensor_program_ub_buffers", cfg_.program_ub_buffers));
    cfg_.program_dma_dual_enable =
        params.find<int>("tensor_program_dma_dual_enable", cfg_.program_dma_dual_enable ? 1 : 0) != 0;
    cfg_.program_engine_priority =
        to_lower_copy_(params.find<std::string>("tensor_program_engine_priority", cfg_.program_engine_priority));
    cfg_.vector_elems_per_cycle =
        params.find<uint32_t>("tensor_vector_elems_per_cycle", cfg_.vector_elems_per_cycle);
    cfg_.vector_pipeline_latency_cycles =
        params.find<uint32_t>("tensor_vector_pipeline_latency_cycles", cfg_.vector_pipeline_latency_cycles);
    cfg_.tile_schedule = to_lower_copy_(params.find<std::string>("tensor_tile_schedule", cfg_.tile_schedule));
    cfg_.writeback_policy = to_lower_copy_(params.find<std::string>("tensor_writeback_policy", cfg_.writeback_policy));
    cfg_.ub_bytes = params.find<uint64_t>("tensor_ub_bytes", cfg_.ub_bytes);
    cfg_.weight_bytes = params.find<uint64_t>("tensor_weight_bytes", cfg_.weight_bytes);
    cfg_.acc_bytes = params.find<uint64_t>("tensor_acc_bytes", cfg_.acc_bytes);
    cfg_.onchip_model_enable =
        params.find<int>("tensor_onchip_model_enable", cfg_.onchip_model_enable ? 1 : 0) != 0;
    cfg_.ub_bank_bytes = params.find<uint64_t>("tensor_ub_bank_bytes", cfg_.ub_bank_bytes);
    cfg_.ub_read_ports = params.find<uint32_t>("tensor_ub_read_ports", cfg_.ub_read_ports);
    cfg_.ub_write_ports = params.find<uint32_t>("tensor_ub_write_ports", cfg_.ub_write_ports);
    cfg_.onchip_bank_model_enable =
        params.find<int>("tensor_onchip_bank_model_enable", cfg_.onchip_bank_model_enable ? 1 : 0) != 0;
    cfg_.ub_bank_count = params.find<uint32_t>("tensor_ub_bank_count", cfg_.ub_bank_count);
    cfg_.ub_bank_select_policy =
        to_lower_copy_(params.find<std::string>("tensor_ub_bank_select_policy", cfg_.ub_bank_select_policy));
    cfg_.ub_bank_conflict_mode =
        to_lower_copy_(params.find<std::string>("tensor_ub_bank_conflict_mode", cfg_.ub_bank_conflict_mode));
    cfg_.acc_bank_bytes = params.find<uint64_t>("tensor_acc_bank_bytes", cfg_.acc_bank_bytes);
    cfg_.acc_read_ports = params.find<uint32_t>("tensor_acc_read_ports", cfg_.acc_read_ports);
    cfg_.acc_write_ports = params.find<uint32_t>("tensor_acc_write_ports", cfg_.acc_write_ports);
    cfg_.acc_bank_count = params.find<uint32_t>("tensor_acc_bank_count", cfg_.acc_bank_count);
    cfg_.acc_bank_select_policy =
        to_lower_copy_(params.find<std::string>("tensor_acc_bank_select_policy", cfg_.acc_bank_select_policy));
    cfg_.acc_bank_conflict_mode =
        to_lower_copy_(params.find<std::string>("tensor_acc_bank_conflict_mode", cfg_.acc_bank_conflict_mode));
    cfg_.bank_queue_depth = params.find<uint32_t>("tensor_bank_queue_depth", cfg_.bank_queue_depth);
    cfg_.spill_enable = params.find<int>("tensor_spill_enable", cfg_.spill_enable ? 1 : 0) != 0;
    cfg_.spill_packet_bytes = params.find<uint32_t>("tensor_spill_packet_bytes", cfg_.spill_packet_bytes);
    cfg_.spill_share_noc_budget =
        params.find<int>("tensor_spill_share_noc_budget", cfg_.spill_share_noc_budget ? 1 : 0) != 0;
    cfg_.dma_bandwidth_bytes_per_cycle =
        params.find<uint64_t>("tensor_dma_bandwidth_bytes_per_cycle", cfg_.dma_bandwidth_bytes_per_cycle);
    cfg_.dma_shared_bandwidth_bytes_per_cycle =
        params.find<uint64_t>("tensor_dma_shared_bandwidth_bytes_per_cycle", cfg_.dma_shared_bandwidth_bytes_per_cycle);
    cfg_.dma_burst_bytes = params.find<uint64_t>("tensor_dma_burst_bytes", cfg_.dma_burst_bytes);
    cfg_.dma_setup_cycles = params.find<uint32_t>("tensor_dma_setup_cycles", cfg_.dma_setup_cycles);
    cfg_.dma_read_engines = params.find<uint32_t>("tensor_dma_read_engines", cfg_.dma_read_engines);
    cfg_.dma_write_engines = params.find<uint32_t>("tensor_dma_write_engines", cfg_.dma_write_engines);
    cfg_.dma_max_inflight_per_engine =
        params.find<uint32_t>("tensor_dma_max_inflight_per_engine", cfg_.dma_max_inflight_per_engine);
    cfg_.dma_hbm_channels = std::max<uint32_t>(
        1u, params.find<uint32_t>("tensor_dma_hbm_channels", cfg_.dma_hbm_channels));
    cfg_.dma_hbm_channel_bandwidth_bytes_per_cycle =
        params.find<uint64_t>(
            "tensor_dma_hbm_channel_bandwidth_bytes_per_cycle",
            cfg_.dma_hbm_channel_bandwidth_bytes_per_cycle);
    cfg_.dma_hbm_channel_interleave_bytes =
        params.find<uint64_t>(
            "tensor_dma_hbm_channel_interleave_bytes",
            cfg_.dma_hbm_channel_interleave_bytes);
    if (cfg_.dma_hbm_channel_interleave_bytes == 0) {
        cfg_.dma_hbm_channel_interleave_bytes = 1;
    }
    cfg_.double_buffer = params.find<int>("tensor_double_buffer", cfg_.double_buffer ? 1 : 0) != 0;
    if (cfg_.exec_mode != "bulk" && cfg_.exec_mode != "tile" && cfg_.exec_mode != "program") {
        cfg_.exec_mode = "bulk";
    }
    close_step_on_iter_done_ = (cfg_.exec_mode != "program");
    if (cfg_.tile_schedule != "auto" &&
        cfg_.tile_schedule != "mnk" &&
        cfg_.tile_schedule != "mkn" &&
        cfg_.tile_schedule != "nkm") {
        cfg_.tile_schedule = "auto";
    }
    if (cfg_.writeback_policy != "at_end_of_k") {
        cfg_.writeback_policy = "at_end_of_k";
    }
    if (cfg_.dataflow != "os" && cfg_.dataflow != "ws" && cfg_.dataflow != "is") {
        cfg_.dataflow = "os";
    }
    if (cfg_.mem_timing_model != "off" &&
        cfg_.mem_timing_model != "proxy_v2" &&
        cfg_.mem_timing_model != "proxy_v3") {
        cfg_.mem_timing_model = "off";
    }
    if (cfg_.mem_sched_policy != "fifo" && cfg_.mem_sched_policy != "frfcfs") {
        cfg_.mem_sched_policy = "fifo";
    }
    if (cfg_.compute_precision != "fp16" &&
        cfg_.compute_precision != "bf16" &&
        cfg_.compute_precision != "fp32" &&
        cfg_.compute_precision != "tf32" &&
        cfg_.compute_precision != "int8" &&
        cfg_.compute_precision != "fp8") {
        cfg_.compute_precision = "fp16";
    }
    if (!(cfg_.compute_throughput_scale > 0.0f)) {
        cfg_.compute_throughput_scale = 1.0f;
    }
    cfg_.compute_pipeline_latency_cycles =
        clampPipelineLatencyCycles_(cfg_.compute_pipeline_latency_cycles);

    cfg_.collective_type = to_lower_copy_(params.find<std::string>("tensor_collective_type", cfg_.collective_type));
    cfg_.collective_blocking = params.find<int>("tensor_collective_blocking", cfg_.collective_blocking ? 1 : 0) != 0;
    cfg_.collective_scope = to_lower_copy_(params.find<std::string>("tensor_collective_scope", cfg_.collective_scope));
    cfg_.collective_bytes = params.find<uint64_t>("tensor_collective_bytes", cfg_.collective_bytes);
    cfg_.collective_period_cycles = params.find<uint64_t>("tensor_collective_period_cycles", cfg_.collective_period_cycles);
    cfg_.collective_pattern = to_lower_copy_(params.find<std::string>("tensor_collective_pattern", cfg_.collective_pattern));
    cfg_.collective_packet_bytes = params.find<uint32_t>("tensor_collective_packet_bytes", cfg_.collective_packet_bytes);
    cfg_.collective_algo = to_lower_copy_(params.find<std::string>("tensor_collective_algo", cfg_.collective_algo));
    cfg_.collective_chunk_bytes = params.find<uint32_t>("tensor_collective_chunk_bytes", cfg_.collective_chunk_bytes);
    cfg_.collective_reduce_overhead_cycles =
        params.find<uint32_t>("tensor_collective_reduce_overhead_cycles", cfg_.collective_reduce_overhead_cycles);
    cfg_.collective_max_inflight_chunks =
        params.find<uint32_t>("tensor_collective_max_inflight_chunks", cfg_.collective_max_inflight_chunks);
    cfg_.collective_credit_enable =
        params.find<int>("tensor_collective_credit_enable", cfg_.collective_credit_enable ? 1 : 0) != 0;
    cfg_.collective_credit_window_chunks =
        params.find<uint32_t>("tensor_collective_credit_window_chunks", cfg_.collective_credit_window_chunks);
    cfg_.collective_credit_return_mode =
        to_lower_copy_(params.find<std::string>("tensor_collective_credit_return_mode", cfg_.collective_credit_return_mode));
    cfg_.collective_backpressure_mode =
        to_lower_copy_(params.find<std::string>("tensor_collective_backpressure_mode", cfg_.collective_backpressure_mode));
    cfg_.noc_bandwidth_bytes_per_cycle =
        params.find<uint64_t>("tensor_noc_bandwidth_bytes_per_cycle", cfg_.noc_bandwidth_bytes_per_cycle);
    cfg_.collective_overlap_with_compute =
        params.find<int>("tensor_collective_overlap_with_compute", cfg_.collective_overlap_with_compute ? 1 : 0) != 0;
    cfg_.collective_issue_priority =
        to_lower_copy_(params.find<std::string>("tensor_collective_issue_priority", cfg_.collective_issue_priority));
    cfg_.collective_2d_dim_x = params.find<uint32_t>("tensor_collective_2d_dim_x", cfg_.collective_2d_dim_x);
    cfg_.collective_2d_dim_y = params.find<uint32_t>("tensor_collective_2d_dim_y", cfg_.collective_2d_dim_y);
    cfg_.collective_2d_row_major =
        params.find<int>("tensor_collective_2d_row_major", cfg_.collective_2d_row_major ? 1 : 0) != 0;
    if (cfg_.collective_scope != "per_core" &&
        cfg_.collective_scope != "per_pe" &&
        cfg_.collective_scope != "per_system") {
        cfg_.collective_scope = "per_core";
    }
    if (cfg_.collective_type != "none" &&
        cfg_.collective_type != "allreduce" &&
        cfg_.collective_type != "allgather" &&
        cfg_.collective_type != "reducescatter") {
        cfg_.collective_type = "none";
    }
    if (cfg_.collective_pattern != "ring" &&
        cfg_.collective_pattern != "mesh_x" &&
        cfg_.collective_pattern != "mesh_xy") {
        cfg_.collective_pattern = "ring";
    }
    if (cfg_.collective_algo != "legacy_bytes" &&
        cfg_.collective_algo != "ring_chunked" &&
        cfg_.collective_algo != "torus_2d_rs_ag") {
        cfg_.collective_algo = "legacy_bytes";
    }
    if (cfg_.collective_algo == "torus_2d_rs_ag" && cfg_.collective_type != "allreduce") {
        cfg_.collective_type = "allreduce";
    }
    if (cfg_.collective_backpressure_mode != "hard" &&
        cfg_.collective_backpressure_mode != "soft") {
        cfg_.collective_backpressure_mode = "hard";
    }
    if (cfg_.collective_credit_return_mode != "event_on_recv" &&
        cfg_.collective_credit_return_mode != "legacy_tick") {
        cfg_.collective_credit_return_mode = "event_on_recv";
    }
    if (cfg_.collective_issue_priority != "control_first" &&
        cfg_.collective_issue_priority != "payload_first") {
        cfg_.collective_issue_priority = "control_first";
    }
    if (cfg_.ub_bank_select_policy != "interleave" &&
        cfg_.ub_bank_select_policy != "rr" &&
        cfg_.ub_bank_select_policy != "hash") {
        cfg_.ub_bank_select_policy = "interleave";
    }
    if (cfg_.acc_bank_select_policy != "interleave" &&
        cfg_.acc_bank_select_policy != "rr" &&
        cfg_.acc_bank_select_policy != "hash") {
        cfg_.acc_bank_select_policy = "interleave";
    }
    if (cfg_.ub_bank_conflict_mode != "queue" &&
        cfg_.ub_bank_conflict_mode != "block") {
        cfg_.ub_bank_conflict_mode = "queue";
    }
    if (cfg_.acc_bank_conflict_mode != "queue" &&
        cfg_.acc_bank_conflict_mode != "block") {
        cfg_.acc_bank_conflict_mode = "queue";
    }

    cfg_.comm_enable = params.find<int>("tensor_comm_enable", cfg_.comm_enable ? 1 : 0) != 0;
    cfg_.comm_period_cycles = params.find<uint64_t>("tensor_comm_period_cycles", cfg_.comm_period_cycles);
    cfg_.comm_payload_bytes = params.find<uint32_t>("tensor_comm_payload_bytes", cfg_.comm_payload_bytes);

    cfg_.strict = params.find<int>("tensor_strict", cfg_.strict ? 1 : 0) != 0;
    cfg_.seed_base = params.find<uint64_t>("tensor_seed", cfg_.seed_base);
    total_cores_cfg_ = params.find<uint32_t>("total_cores", total_cores_cfg_);
    if (total_cores_cfg_ == 0) total_cores_cfg_ = 1;

    // === Hard bounds (avoid pathological allocations / invalid params) ===
    if (cfg_.m == 0) cfg_.m = 1;
    if (cfg_.n == 0) cfg_.n = 1;
    if (cfg_.k == 0) cfg_.k = 1;
    cfg_.element_bytes = static_cast<uint32_t>(clamp_u64_(cfg_.element_bytes, 1, 16));
    cfg_.program_issue_width = static_cast<uint32_t>(clamp_u64_(cfg_.program_issue_width, 1, 1024ull));
    cfg_.vector_elems_per_cycle = static_cast<uint32_t>(clamp_u64_(cfg_.vector_elems_per_cycle, 1, 1024ull * 1024ull));
    cfg_.vector_pipeline_latency_cycles = static_cast<uint32_t>(clamp_u64_(cfg_.vector_pipeline_latency_cycles, 0, 4096ull));
    if (cfg_.array_m == 0) cfg_.array_m = 1;
    if (cfg_.array_n == 0) cfg_.array_n = 1;
    cfg_.mem_req_bytes = static_cast<uint32_t>(clamp_u64_(cfg_.mem_req_bytes, 1, 1024ull * 1024ull));
    cfg_.mem_max_outstanding = static_cast<uint32_t>(clamp_u64_(cfg_.mem_max_outstanding, 1, 4096));
    cfg_.mem_region_bytes = clampNonZero_(cfg_.mem_region_bytes, 4096);
    cfg_.mem_bank_groups_per_channel = static_cast<uint32_t>(clamp_u64_(cfg_.mem_bank_groups_per_channel, 1, 1024));
    cfg_.mem_banks_per_group = static_cast<uint32_t>(clamp_u64_(cfg_.mem_banks_per_group, 1, 1024));
    cfg_.mem_row_bytes = clampNonZero_(cfg_.mem_row_bytes, 256);
    cfg_.mem_bank_queue_depth = static_cast<uint32_t>(clamp_u64_(cfg_.mem_bank_queue_depth, 1, 4096));
    cfg_.mem_t_rcd_cycles = static_cast<uint32_t>(clamp_u64_(cfg_.mem_t_rcd_cycles, 0, 4096));
    cfg_.mem_t_cl_cycles = static_cast<uint32_t>(clamp_u64_(cfg_.mem_t_cl_cycles, 0, 4096));
    cfg_.mem_t_rp_cycles = static_cast<uint32_t>(clamp_u64_(cfg_.mem_t_rp_cycles, 0, 4096));
    cfg_.mem_t_burst_cycles = static_cast<uint32_t>(clamp_u64_(cfg_.mem_t_burst_cycles, 0, 4096));
    cfg_.mem_refresh_interval_cycles = static_cast<uint32_t>(clamp_u64_(cfg_.mem_refresh_interval_cycles, 0, (1ull << 20)));
    cfg_.mem_refresh_block_cycles = static_cast<uint32_t>(clamp_u64_(cfg_.mem_refresh_block_cycles, 0, 4096));
    cfg_.start_cycle = clampNonZero_(cfg_.start_cycle, 1);
    cfg_.comm_payload_bytes = static_cast<uint32_t>(clamp_u64_(cfg_.comm_payload_bytes, 0, 1024ull * 1024ull));
    cfg_.collective_packet_bytes = static_cast<uint32_t>(clamp_u64_(cfg_.collective_packet_bytes, 1, 1024ull * 1024ull));
    if (cfg_.collective_packet_bytes < 8) {
        cfg_.collective_packet_bytes = 8;
    }
    cfg_.spill_packet_bytes = static_cast<uint32_t>(clamp_u64_(cfg_.spill_packet_bytes, 1, 1024ull * 1024ull));
    if (cfg_.spill_packet_bytes < 8) {
        cfg_.spill_packet_bytes = 8;
    }
    cfg_.collective_chunk_bytes = static_cast<uint32_t>(clamp_u64_(cfg_.collective_chunk_bytes, 0, 1024ull * 1024ull));
    cfg_.collective_max_inflight_chunks = static_cast<uint32_t>(clamp_u64_(cfg_.collective_max_inflight_chunks, 1, 4096));
    cfg_.collective_credit_window_chunks = static_cast<uint32_t>(clamp_u64_(cfg_.collective_credit_window_chunks, 0, 4096));
    cfg_.ub_bank_count = static_cast<uint32_t>(clamp_u64_(cfg_.ub_bank_count, 1, 4096));
    cfg_.acc_bank_count = static_cast<uint32_t>(clamp_u64_(cfg_.acc_bank_count, 1, 4096));
    cfg_.bank_queue_depth = static_cast<uint32_t>(clamp_u64_(cfg_.bank_queue_depth, 1, 4096));
    cfg_.dma_burst_bytes = clamp_u64_(cfg_.dma_burst_bytes, 0, 1ull << 30);
    cfg_.dma_setup_cycles = static_cast<uint32_t>(clamp_u64_(cfg_.dma_setup_cycles, 0, 4096));
    cfg_.dma_read_engines = static_cast<uint32_t>(clamp_u64_(cfg_.dma_read_engines, 0, 4096));
    cfg_.dma_write_engines = static_cast<uint32_t>(clamp_u64_(cfg_.dma_write_engines, 0, 4096));
    cfg_.dma_max_inflight_per_engine = static_cast<uint32_t>(clamp_u64_(cfg_.dma_max_inflight_per_engine, 0, 4096));
    cfg_.mxu_a_bytes_per_cycle = clamp_u64_(cfg_.mxu_a_bytes_per_cycle, 0, 1ull << 30);
    cfg_.mxu_b_bytes_per_cycle = clamp_u64_(cfg_.mxu_b_bytes_per_cycle, 0, 1ull << 30);
    cfg_.mxu_c_bytes_per_cycle = clamp_u64_(cfg_.mxu_c_bytes_per_cycle, 0, 1ull << 30);
    if (cfg_.onchip_bank_model_enable) {
        cfg_.onchip_model_enable = true;
    }
    if (cfg_.onchip_model_enable) {
        if (cfg_.ub_read_ports == 0) cfg_.ub_read_ports = 2;
        if (cfg_.ub_write_ports == 0) cfg_.ub_write_ports = 1;
        if (cfg_.acc_read_ports == 0) cfg_.acc_read_ports = 1;
        if (cfg_.acc_write_ports == 0) cfg_.acc_write_ports = 1;
        if (cfg_.ub_bank_bytes == 0) {
            cfg_.ub_bank_bytes = cfg_.onchip_bank_model_enable
                                     ? ceilDivU64_(cfg_.ub_bytes, static_cast<uint64_t>(std::max<uint32_t>(cfg_.ub_bank_count, 1u)))
                                     : cfg_.ub_bytes;
        }
        if (cfg_.acc_bank_bytes == 0) {
            cfg_.acc_bank_bytes = cfg_.onchip_bank_model_enable
                                      ? ceilDivU64_(cfg_.acc_bytes, static_cast<uint64_t>(std::max<uint32_t>(cfg_.acc_bank_count, 1u)))
                                      : cfg_.acc_bytes;
        }
    }
    if (cfg_.collective_credit_enable && cfg_.collective_credit_window_chunks == 0) {
        cfg_.collective_credit_window_chunks = std::max<uint32_t>(cfg_.collective_max_inflight_chunks, 1u);
    }
    if (cfg_.collective_algo == "ring_chunked") {
        tensor_collective_algo_id_ = 1ull;
    } else if (cfg_.collective_algo == "torus_2d_rs_ag") {
        tensor_collective_algo_id_ = 2ull;
    } else {
        tensor_collective_algo_id_ = 0ull;
    }

    const ComputeProfile compute_profile = resolveComputeProfile_(cfg_);
    compute_throughput_scale_effective_ = compute_profile.throughput_scale;
    compute_pipeline_latency_cycles_effective_ = compute_profile.pipeline_latency_cycles;
    tensor_compute_precision_profile_id_ = compute_profile.profile_id;

    // Derived per-iteration sizes/ops (GEMM)
    const unsigned __int128 a_elems = static_cast<unsigned __int128>(cfg_.m) * static_cast<unsigned __int128>(cfg_.k);
    const unsigned __int128 b_elems = static_cast<unsigned __int128>(cfg_.k) * static_cast<unsigned __int128>(cfg_.n);
    const unsigned __int128 c_elems = static_cast<unsigned __int128>(cfg_.m) * static_cast<unsigned __int128>(cfg_.n);
    const unsigned __int128 eb = static_cast<unsigned __int128>(cfg_.element_bytes);
    const unsigned __int128 macs = c_elems * static_cast<unsigned __int128>(cfg_.k);
    mac_ops_per_iter_ =
        (macs > static_cast<unsigned __int128>(std::numeric_limits<uint64_t>::max()))
            ? std::numeric_limits<uint64_t>::max()
            : static_cast<uint64_t>(macs);
    compute_math_cycles_per_iter_ = ceilDivU64_(mac_ops_per_iter_, effectivePeakMacsPerCycle_());

    const uint64_t tm = clampNonZero_(std::min<uint64_t>(cfg_.tile_m ? cfg_.tile_m : cfg_.m, cfg_.m), 1);
    const uint64_t tn = clampNonZero_(std::min<uint64_t>(cfg_.tile_n ? cfg_.tile_n : cfg_.n, cfg_.n), 1);
    const uint64_t tk = clampNonZero_(std::min<uint64_t>(cfg_.tile_k ? cfg_.tile_k : cfg_.k, cfg_.k), 1);
    const uint64_t mt = ceilDivU64_(cfg_.m, tm);
    const uint64_t nt = ceilDivU64_(cfg_.n, tn);
    const uint64_t kt = ceilDivU64_(cfg_.k, tk);
    tile_count_per_iter_ = mt * nt * kt;

    const uint64_t a_tile = tm * tk * static_cast<uint64_t>(cfg_.element_bytes);
    const uint64_t b_tile = tk * tn * static_cast<uint64_t>(cfg_.element_bytes);
    const uint64_t c_tile = tm * tn * static_cast<uint64_t>(cfg_.element_bytes);

    const bool dataflow_is = (cfg_.dataflow == "is");
    const bool dataflow_ws = (cfg_.dataflow == "ws");
    const bool dataflow_os = (!dataflow_is && !dataflow_ws);

    // Persist tile-derived params for tile exec mode.
    tile_tm_ = static_cast<uint32_t>(tm);
    tile_tn_ = static_cast<uint32_t>(tn);
    tile_tk_ = static_cast<uint32_t>(tk);
    tile_mt_ = static_cast<uint32_t>(mt);
    tile_nt_ = static_cast<uint32_t>(nt);
    tile_kt_ = static_cast<uint32_t>(kt);
    tile_a_bytes_ = a_tile;
    tile_b_bytes_ = b_tile;
    tile_c_bytes_ = c_tile;

    const bool tile_like = (cfg_.exec_mode == "tile" || cfg_.exec_mode == "program");

    tile_schedule_eff_ = cfg_.tile_schedule;
    if (tile_schedule_eff_.empty()) tile_schedule_eff_ = "auto";
    if (tile_like && tile_schedule_eff_ == "auto") {
        if (dataflow_is) {
            tile_schedule_eff_ = "mkn";
        } else if (dataflow_ws) {
            tile_schedule_eff_ = "nkm";
        } else {
            tile_schedule_eff_ = "mnk";
        }
    } else if (tile_schedule_eff_ == "auto") {
        tile_schedule_eff_ = "mnk";
    }

    const bool ub_can_hold_a = (cfg_.ub_bytes > 0 && cfg_.ub_bytes >= a_tile);
    const bool ub_can_hold_a_and_b = (cfg_.ub_bytes > 0 && cfg_.ub_bytes >= saturatingAddU64_(a_tile, b_tile));
    const uint64_t b_pool_cap = (cfg_.weight_bytes > 0) ? cfg_.weight_bytes : cfg_.ub_bytes;
    const bool b_pool_can_hold_b = (b_pool_cap > 0 && b_pool_cap >= b_tile);
    const bool can_keep_a = ub_can_hold_a && (cfg_.weight_bytes > 0 ? b_pool_can_hold_b : ub_can_hold_a_and_b);
    const bool can_keep_b = b_pool_can_hold_b && (cfg_.weight_bytes > 0 ? ub_can_hold_a : ub_can_hold_a_and_b);
    tile_keep_a_ = (tile_like && dataflow_is && can_keep_a && tile_schedule_eff_ == "mkn");
    tile_keep_b_ = (tile_like && dataflow_ws && can_keep_b && tile_schedule_eff_ == "nkm");
    const bool keep_a = tile_like ? tile_keep_a_ : can_keep_a;
    const bool keep_b = tile_like ? tile_keep_b_ : can_keep_b;

    if (tile_like) {
        compute_pipeline_cycles_per_iter_ =
            saturatingMulU64ByU32_(tile_count_per_iter_, compute_pipeline_latency_cycles_effective_);
    } else {
        compute_pipeline_cycles_per_iter_ = static_cast<uint64_t>(compute_pipeline_latency_cycles_effective_);
    }
    compute_cycles_per_iter_ = saturatingAddU64_(compute_math_cycles_per_iter_, compute_pipeline_cycles_per_iter_);

    uint64_t total_a = 0;
    uint64_t total_b = 0;
    if (dataflow_is) {
        const uint64_t a_factor = keep_a ? 1 : nt;
        total_a = mt * kt * a_tile * a_factor;
        total_b = mt * nt * kt * b_tile;
    } else if (dataflow_ws) {
        const uint64_t b_factor = keep_b ? 1 : mt;
        total_a = mt * nt * kt * a_tile;
        total_b = kt * nt * b_tile * b_factor;
    } else if (dataflow_os) {
        total_a = mt * nt * kt * a_tile;
        total_b = mt * nt * kt * b_tile;
    }

    const uint64_t total_c = mt * nt * c_tile;
    bytes_read_per_iter_ = total_a + total_b;
    bytes_write_per_iter_ = total_c;
    dram_bytes_per_iter_ = bytes_read_per_iter_ + bytes_write_per_iter_;
    onchip_bytes_per_iter_ = bytes_read_per_iter_ + bytes_write_per_iter_;
    uint64_t dma_bw_eff = cfg_.dma_bandwidth_bytes_per_cycle;
    if (cfg_.dma_shared_bandwidth_bytes_per_cycle > 0) {
        const uint64_t cores = static_cast<uint64_t>(std::max<uint32_t>(total_cores_cfg_, 1u));
        const uint64_t per_core = ceilDivU64_(cfg_.dma_shared_bandwidth_bytes_per_cycle, cores);
        if (dma_bw_eff == 0) {
            dma_bw_eff = per_core;
        } else {
            dma_bw_eff = std::min<uint64_t>(dma_bw_eff, per_core);
        }
    }
    dma_cycles_per_iter_ = (dma_bw_eff > 0) ? ceilDivU64_(dram_bytes_per_iter_, dma_bw_eff) : 0;
    if (tile_count_per_iter_ > 0) {
        tile_seg_math_cycles_base_ = compute_math_cycles_per_iter_ / tile_count_per_iter_;
        tile_seg_math_cycles_remainder_ = compute_math_cycles_per_iter_ % tile_count_per_iter_;
    } else {
        tile_seg_math_cycles_base_ = 0;
        tile_seg_math_cycles_remainder_ = 0;
    }

    onchip_ub_bank_occupancy_bytes_.assign(std::max<uint32_t>(cfg_.ub_bank_count, 1u), 0ull);
    onchip_weight_bank_occupancy_bytes_.assign(std::max<uint32_t>(cfg_.ub_bank_count, 1u), 0ull);
    onchip_acc_bank_occupancy_bytes_.assign(std::max<uint32_t>(cfg_.acc_bank_count, 1u), 0ull);
    onchip_ub_bank_queue_occupancy_.assign(std::max<uint32_t>(cfg_.ub_bank_count, 1u), 0u);
    onchip_weight_bank_queue_occupancy_.assign(std::max<uint32_t>(cfg_.ub_bank_count, 1u), 0u);
    onchip_acc_bank_queue_occupancy_.assign(std::max<uint32_t>(cfg_.acc_bank_count, 1u), 0u);
    onchip_ub_bank_rr_ = 0;
    onchip_weight_bank_rr_ = 0;
    onchip_acc_bank_rr_ = 0;
    resetMemTimingState_();
    collective_credit_inflight_chunks_ = 0;
    collective_credit_outstanding_.clear();
    collective_credit_return_seen_.clear();
    collective_credit_return_pending_credits_.clear();
    collective_credit_return_pending_queue_.clear();

    configured_ = true;
}

uint64_t TensorWorkload::dmaSharedQuotaBytesPerCycle_(uint64_t now_cycle) const {
    if (cfg_.dma_shared_bandwidth_bytes_per_cycle == 0) {
        return std::numeric_limits<uint64_t>::max();
    }

    const uint32_t cores = total_cores_cfg_ ? total_cores_cfg_ : 1u;
    if (cores <= 1u) {
        return cfg_.dma_shared_bandwidth_bytes_per_cycle;
    }

    const uint64_t key = static_cast<uint64_t>(rt_.node_id);
    DmaSharedBudgetState_& st = g_dma_shared_budget_state_[key];
    if (st.cycle_tag != now_cycle) {
        st.cycle_tag = now_cycle;
        if (!st.rr_init || st.rr_start >= cores) {
            st.rr_start = 0;
            st.rr_init = true;
        } else {
            st.rr_start = (st.rr_start + 1u) % cores;
        }
    } else if (!st.rr_init || st.rr_start >= cores) {
        st.rr_start = 0;
        st.rr_init = true;
    }

    const uint64_t total = cfg_.dma_shared_bandwidth_bytes_per_cycle;
    const uint64_t base = total / static_cast<uint64_t>(cores);
    const uint64_t rem = total % static_cast<uint64_t>(cores);
    const uint32_t cid = static_cast<uint32_t>(rt_.core_id) % cores;
    const uint32_t rr = st.rr_start % cores;
    const uint32_t pos = (cid >= rr) ? (cid - rr) : (cid + cores - rr);
    return base + ((static_cast<uint64_t>(pos) < rem) ? 1ull : 0ull);
}

uint64_t TensorWorkload::dmaBudgetBytesPerCycle_(uint64_t now_cycle) const {
    const uint64_t local =
        (cfg_.dma_bandwidth_bytes_per_cycle > 0)
            ? cfg_.dma_bandwidth_bytes_per_cycle
            : std::numeric_limits<uint64_t>::max();
    const uint64_t shared = dmaSharedQuotaBytesPerCycle_(now_cycle);
    return std::min<uint64_t>(local, shared);
}

bool TensorWorkload::hbmChannelBudgetEnabled_() const {
    return cfg_.dma_hbm_channel_bandwidth_bytes_per_cycle > 0;
}

uint32_t TensorWorkload::hbmChannelCount_() const {
    return std::max<uint32_t>(cfg_.dma_hbm_channels, 1u);
}

bool TensorWorkload::memTimingProxyEnabled_() const {
    return cfg_.mem_enable &&
           (cfg_.mem_timing_model == "proxy_v2" || cfg_.mem_timing_model == "proxy_v3");
}

uint32_t TensorWorkload::memTimingBanksPerChannel_() const {
    const uint64_t groups = static_cast<uint64_t>(std::max<uint32_t>(cfg_.mem_bank_groups_per_channel, 1u));
    const uint64_t per_group = static_cast<uint64_t>(std::max<uint32_t>(cfg_.mem_banks_per_group, 1u));
    const uint64_t banks = groups * per_group;
    return static_cast<uint32_t>(std::max<uint64_t>(1ull, banks));
}

uint64_t TensorWorkload::memTimingServiceQuantumCycles_() const {
    return std::max<uint64_t>(1ull, static_cast<uint64_t>(cfg_.mem_t_burst_cycles));
}

uint32_t TensorWorkload::memTimingBankIndex_(uint64_t off) const {
    const uint64_t interleave = std::max<uint64_t>(cfg_.dma_hbm_channel_interleave_bytes, 1ull);
    const uint32_t channels = hbmChannelCount_();
    const uint64_t stripe = off / interleave;
    const uint64_t stripe_in_ch = stripe / static_cast<uint64_t>(std::max<uint32_t>(channels, 1u));
    const uint32_t banks_per_channel = memTimingBanksPerChannel_();
    if (banks_per_channel <= 1u) return 0u;
    return static_cast<uint32_t>(stripe_in_ch % static_cast<uint64_t>(banks_per_channel));
}

uint32_t TensorWorkload::memTimingBankGroupIndex_(uint64_t off) const {
    const uint32_t banks_per_group = std::max<uint32_t>(cfg_.mem_banks_per_group, 1u);
    const uint32_t groups = std::max<uint32_t>(cfg_.mem_bank_groups_per_channel, 1u);
    const uint32_t bank = memTimingBankIndex_(off);
    const uint32_t group = bank / banks_per_group;
    if (groups <= 1u) return 0u;
    return static_cast<uint32_t>(group % groups);
}

uint64_t TensorWorkload::memTimingRowIndex_(uint64_t off) const {
    const uint64_t interleave = std::max<uint64_t>(cfg_.dma_hbm_channel_interleave_bytes, 1ull);
    const uint32_t channels = hbmChannelCount_();
    const uint64_t stripe = off / interleave;
    const uint64_t stripe_off = off % interleave;
    const uint64_t stripe_in_ch = stripe / static_cast<uint64_t>(std::max<uint32_t>(channels, 1u));
    const uint64_t channel_local_off = stripe_in_ch * interleave + stripe_off;
    const uint64_t row_bytes = clampNonZero_(cfg_.mem_row_bytes, 256ull);
    return channel_local_off / row_bytes;
}

uint64_t TensorWorkload::memTimingQueueDepthForReq_() const {
    return std::max<uint64_t>(1ull, static_cast<uint64_t>(cfg_.mem_bank_queue_depth));
}

uint64_t TensorWorkload::memTimingRefreshDelayCycles_(MemTimingBankState& st, uint64_t now_cycle) {
    const uint64_t interval = static_cast<uint64_t>(cfg_.mem_refresh_interval_cycles);
    const uint64_t block = static_cast<uint64_t>(cfg_.mem_refresh_block_cycles);
    if (interval == 0 || block == 0) return 0;
    if (st.last_refresh_cycle == 0) {
        st.last_refresh_cycle = now_cycle;
        return 0;
    }
    if (now_cycle <= st.last_refresh_cycle) return 0;
    const uint64_t elapsed = now_cycle - st.last_refresh_cycle;
    const uint64_t periods = elapsed / interval;
    if (periods == 0) return 0;
    st.last_refresh_cycle = st.last_refresh_cycle + periods * interval;
    const uint64_t delay = periods * block;
    tensor_mem_refresh_block_cycles_total_ = saturatingAddU64_(tensor_mem_refresh_block_cycles_total_, delay);
    return delay;
}

uint64_t TensorWorkload::memTimingProxyDelayCycles_(ReqKind kind, uint64_t off, uint32_t bytes, uint64_t now_cycle) {
    (void)kind;
    (void)bytes;
    if (!memTimingProxyEnabled_()) return 0;
    if (mem_timing_banks_.empty()) resetMemTimingState_();
    if (mem_timing_banks_.empty()) return 0;

    const uint32_t channels = hbmChannelCount_();
    const uint32_t banks_per_channel = memTimingBanksPerChannel_();
    const uint32_t ch = memOffsetToHbmChannel_(off);
    const uint32_t bank_local = memTimingBankIndex_(off);
    const uint64_t bank_global_u64 =
        static_cast<uint64_t>(ch % std::max<uint32_t>(channels, 1u)) * static_cast<uint64_t>(banks_per_channel) +
        static_cast<uint64_t>(bank_local % std::max<uint32_t>(banks_per_channel, 1u));
    if (bank_global_u64 >= static_cast<uint64_t>(mem_timing_banks_.size())) return 0;
    MemTimingBankState& st = mem_timing_banks_[static_cast<size_t>(bank_global_u64)];

    const uint64_t burst = memTimingServiceQuantumCycles_();
    uint64_t queue_wait = (st.busy_until_cycle > now_cycle) ? (st.busy_until_cycle - now_cycle) : 0ull;
    if (cfg_.mem_sched_policy == "frfcfs" && st.row_open && st.open_row == memTimingRowIndex_(off) && queue_wait > 0) {
        const uint64_t cut = std::min<uint64_t>(queue_wait, burst);
        queue_wait -= cut;
    }

    const uint64_t depth = memTimingQueueDepthForReq_();
    uint64_t queue_slots = (burst > 0) ? ceilDivU64_(queue_wait, burst) : 0ull;
    if (queue_slots >= depth) {
        tensor_mem_bank_queue_full_total_ = saturatingAddU64_(tensor_mem_bank_queue_full_total_, 1ull);
        const uint64_t cap = (depth > 0) ? ((depth - 1ull) * burst) : 0ull;
        queue_wait = std::min<uint64_t>(queue_wait, cap);
        queue_slots = (burst > 0) ? ceilDivU64_(queue_wait, burst) : 0ull;
    }
    tensor_mem_cmd_queue_slots_total_ =
        saturatingAddU64_(tensor_mem_cmd_queue_slots_total_, queue_slots);
    if (queue_slots > tensor_mem_cmd_queue_depth_max_) {
        tensor_mem_cmd_queue_depth_max_ = queue_slots;
    }

    const uint64_t row = memTimingRowIndex_(off);
    const uint64_t t_rcd = static_cast<uint64_t>(cfg_.mem_t_rcd_cycles);
    const uint64_t t_cl = static_cast<uint64_t>(cfg_.mem_t_cl_cycles);
    const uint64_t t_rp = static_cast<uint64_t>(cfg_.mem_t_rp_cycles);
    uint64_t row_delay = 0;
    uint32_t cmd_issue_count = 0;
    if (!st.row_open) {
        tensor_mem_row_miss_total_ = saturatingAddU64_(tensor_mem_row_miss_total_, 1ull);
        tensor_mem_cmd_act_total_ = saturatingAddU64_(tensor_mem_cmd_act_total_, 1ull);
        tensor_mem_cmd_rdwr_total_ = saturatingAddU64_(tensor_mem_cmd_rdwr_total_, 1ull);
        row_delay = t_rcd + t_cl + burst;
        cmd_issue_count = 2u;
    } else if (st.open_row == row) {
        tensor_mem_row_hit_total_ = saturatingAddU64_(tensor_mem_row_hit_total_, 1ull);
        tensor_mem_cmd_rdwr_total_ = saturatingAddU64_(tensor_mem_cmd_rdwr_total_, 1ull);
        row_delay = t_cl + burst;
        cmd_issue_count = 1u;
    } else {
        tensor_mem_row_conflict_total_ = saturatingAddU64_(tensor_mem_row_conflict_total_, 1ull);
        tensor_mem_cmd_pre_total_ = saturatingAddU64_(tensor_mem_cmd_pre_total_, 1ull);
        tensor_mem_cmd_act_total_ = saturatingAddU64_(tensor_mem_cmd_act_total_, 1ull);
        tensor_mem_cmd_rdwr_total_ = saturatingAddU64_(tensor_mem_cmd_rdwr_total_, 1ull);
        row_delay = t_rp + t_rcd + t_cl + burst;
        cmd_issue_count = 3u;
    }
    tensor_mem_row_service_cycles_total_ =
        saturatingAddU64_(tensor_mem_row_service_cycles_total_, row_delay);
    tensor_mem_cmd_issue_total_ =
        saturatingAddU64_(tensor_mem_cmd_issue_total_, static_cast<uint64_t>(std::max<uint32_t>(1u, cmd_issue_count)));

    uint64_t cmd_bus_wait = 0;
    if (cfg_.mem_timing_model == "proxy_v3" && !mem_timing_channels_.empty()) {
        const uint32_t ch_idx = ch % std::max<uint32_t>(channels, 1u);
        if (ch_idx < static_cast<uint32_t>(mem_timing_channels_.size())) {
            MemTimingChannelState& ch_state = mem_timing_channels_[static_cast<size_t>(ch_idx)];
            const uint32_t bank_group = memTimingBankGroupIndex_(off);
            const uint64_t tccd_s = std::max<uint64_t>(1ull, static_cast<uint64_t>(cfg_.mem_t_ccd_s_cycles));
            const uint64_t tccd_l = std::max<uint64_t>(tccd_s, static_cast<uint64_t>(cfg_.mem_t_ccd_l_cycles));

            uint64_t cmd_cycle = std::max<uint64_t>(now_cycle, ch_state.cmd_bus_ready_cycle);
            uint64_t first_cmd_cycle = cmd_cycle;
            const uint32_t cmd_total = std::max<uint32_t>(1u, cmd_issue_count);
            for (uint32_t i = 0; i < cmd_total; ++i) {
                uint64_t issue_cycle = cmd_cycle;
                if (ch_state.last_cmd_valid) {
                    const bool same_bg = (ch_state.last_cmd_bank_group == bank_group);
                    const uint64_t tccd = same_bg ? tccd_l : tccd_s;
                    issue_cycle = std::max<uint64_t>(issue_cycle, ch_state.last_cmd_cycle + tccd);
                    if (!same_bg) {
                        tensor_mem_cmd_bus_bg_switch_total_ =
                            saturatingAddU64_(tensor_mem_cmd_bus_bg_switch_total_, 1ull);
                    }
                }
                if (i == 0u) {
                    first_cmd_cycle = issue_cycle;
                }
                ch_state.last_cmd_cycle = issue_cycle;
                ch_state.last_cmd_bank_group = bank_group;
                ch_state.last_cmd_valid = true;
                ch_state.cmd_bus_ready_cycle = issue_cycle + 1ull;
                cmd_cycle = ch_state.cmd_bus_ready_cycle;
            }
            if (first_cmd_cycle > now_cycle) {
                cmd_bus_wait = first_cmd_cycle - now_cycle;
            }
            tensor_mem_cmd_bus_wait_cycles_total_ =
                saturatingAddU64_(tensor_mem_cmd_bus_wait_cycles_total_, cmd_bus_wait);
        }
    }

    const uint64_t service_start = now_cycle + queue_wait + cmd_bus_wait;
    const uint64_t refresh_delay = memTimingRefreshDelayCycles_(st, service_start);
    const uint64_t proxy_delay = queue_wait + cmd_bus_wait + refresh_delay + row_delay;
    const uint64_t active_span = std::max<uint64_t>(burst, row_delay);
    const uint64_t ready_cycle = service_start + refresh_delay + active_span;

    st.busy_until_cycle = ready_cycle;
    st.row_open = true;
    st.open_row = row;

    tensor_mem_bank_queue_wait_cycles_total_ =
        saturatingAddU64_(tensor_mem_bank_queue_wait_cycles_total_, queue_wait);
    if (cfg_.mem_sched_policy == "frfcfs") {
        tensor_mem_sched_frfcfs_pick_total_ = saturatingAddU64_(tensor_mem_sched_frfcfs_pick_total_, 1ull);
    } else {
        tensor_mem_sched_fifo_pick_total_ = saturatingAddU64_(tensor_mem_sched_fifo_pick_total_, 1ull);
    }
    tensor_mem_proxy_delay_cycles_total_ =
        saturatingAddU64_(tensor_mem_proxy_delay_cycles_total_, proxy_delay);
    if (proxy_delay > tensor_mem_proxy_delay_cycles_max_) {
        tensor_mem_proxy_delay_cycles_max_ = proxy_delay;
    }
    tensor_mem_bank_active_cycles_total_ =
        saturatingAddU64_(tensor_mem_bank_active_cycles_total_, active_span);
    return proxy_delay;
}

void TensorWorkload::resetMemTimingState_() {
    mem_timing_banks_.clear();
    mem_timing_channels_.clear();
    if (!memTimingProxyEnabled_()) return;
    const uint64_t banks =
        static_cast<uint64_t>(hbmChannelCount_()) * static_cast<uint64_t>(memTimingBanksPerChannel_());
    const size_t count = static_cast<size_t>(std::max<uint64_t>(banks, 1ull));
    mem_timing_banks_.assign(count, MemTimingBankState{});
    const size_t channels = static_cast<size_t>(std::max<uint32_t>(hbmChannelCount_(), 1u));
    mem_timing_channels_.assign(channels, MemTimingChannelState{});
}

uint64_t TensorWorkload::peekNextMemOffset_(ReqKind kind, uint32_t bytes) const {
    const uint64_t region = clampNonZero_(cfg_.mem_region_bytes, 4096);
    uint64_t off = (kind == ReqKind::Read) ? read_off_ : write_off_;
    if (off + static_cast<uint64_t>(bytes) > region) off = 0;
    return off;
}

uint32_t TensorWorkload::memOffsetToHbmChannel_(uint64_t off) const {
    const uint64_t interleave = std::max<uint64_t>(cfg_.dma_hbm_channel_interleave_bytes, 1ull);
    const uint32_t channels = hbmChannelCount_();
    if (channels <= 1u) return 0;
    const uint64_t idx = off / interleave;
    return static_cast<uint32_t>(idx % static_cast<uint64_t>(channels));
}

uint64_t TensorWorkload::memOffsetToPhysicalAddr_(uint64_t off) const {
    const uint64_t region = clampNonZero_(cfg_.mem_region_bytes, 4096);
    const uint32_t channels = hbmChannelCount_();
    if (channels <= 1u) return rt_.base_addr + off;

    const uint64_t interleave = std::max<uint64_t>(cfg_.dma_hbm_channel_interleave_bytes, 1ull);
    const uint64_t stripe = off / interleave;
    const uint64_t stripe_off = off % interleave;
    const uint32_t ch = static_cast<uint32_t>(stripe % static_cast<uint64_t>(channels));
    const uint64_t stripe_in_ch = stripe / static_cast<uint64_t>(channels);

    // Deinterleave: map a striped (logical) address space into contiguous per-channel
    // physical partitions (as built by mem_memhierarchy.build_pe_memory_systems()).
    const uint64_t base = region / static_cast<uint64_t>(channels);
    const uint64_t rem = region % static_cast<uint64_t>(channels);
    const uint64_t ch_base =
        base * static_cast<uint64_t>(ch) + std::min<uint64_t>(static_cast<uint64_t>(ch), rem);
    const uint64_t phys_off = ch_base + stripe_in_ch * interleave + stripe_off;
    return rt_.base_addr + (region ? (phys_off % region) : phys_off);
}

uint64_t TensorWorkload::hbmChannelBudgetLeftBytes_(uint64_t now_cycle, uint32_t channel) const {
    if (!hbmChannelBudgetEnabled_()) return std::numeric_limits<uint64_t>::max();

    const uint32_t channels = hbmChannelCount_();
    const uint64_t key = static_cast<uint64_t>(rt_.node_id);
    HbmChannelBudgetState_& st = g_hbm_channel_budget_state_[key];
    if (st.cycle_tag != now_cycle || st.left.size() != static_cast<size_t>(channels)) {
        st.cycle_tag = now_cycle;
        st.left.assign(static_cast<size_t>(channels), cfg_.dma_hbm_channel_bandwidth_bytes_per_cycle);
    }
    if (st.left.empty()) return 0;
    const uint32_t ch = (channels > 0u) ? (channel % channels) : 0u;
    const size_t idx = static_cast<size_t>(ch);
    if (idx >= st.left.size()) return 0;
    return st.left[idx];
}

void TensorWorkload::consumeHbmChannelBudget_(uint64_t now_cycle, uint32_t channel, uint32_t bytes) {
    if (!hbmChannelBudgetEnabled_()) return;

    const uint32_t channels = hbmChannelCount_();
    const uint64_t key = static_cast<uint64_t>(rt_.node_id);
    HbmChannelBudgetState_& st = g_hbm_channel_budget_state_[key];
    if (st.cycle_tag != now_cycle || st.left.size() != static_cast<size_t>(channels)) {
        st.cycle_tag = now_cycle;
        st.left.assign(static_cast<size_t>(channels), cfg_.dma_hbm_channel_bandwidth_bytes_per_cycle);
    }
    if (st.left.empty()) return;
    const uint32_t ch = (channels > 0u) ? (channel % channels) : 0u;
    const size_t idx = static_cast<size_t>(ch);
    if (idx >= st.left.size()) return;
    uint64_t& left = st.left[idx];
    const uint64_t cut = std::min<uint64_t>(left, static_cast<uint64_t>(bytes));
    left -= cut;
}

uint32_t TensorWorkload::clampBytesByHbmChannelBudget_(uint64_t now_cycle,
                                                      ReqKind kind,
                                                      uint32_t want,
                                                      uint32_t& out_channel) const {
    out_channel = 0;
    if (!hbmChannelBudgetEnabled_() || want == 0) return want;

    uint32_t bytes = want;
    // The address depends on wrap-around (off+bytes>region). Clamping bytes can change
    // whether wrap-around happens, so iterate to reach a stable (addr,channel,bytes).
    for (int it = 0; it < 3; ++it) {
        if (bytes == 0) return 0;
        const uint64_t off = peekNextMemOffset_(kind, bytes);
        const uint32_t ch = memOffsetToHbmChannel_(off);
        out_channel = ch;
        const uint64_t left = hbmChannelBudgetLeftBytes_(now_cycle, ch);
        const uint32_t clamped = static_cast<uint32_t>(std::min<uint64_t>(static_cast<uint64_t>(bytes), left));
        if (clamped == bytes) return bytes;
        bytes = clamped;
    }
    return bytes;
}

void TensorWorkload::bindRuntime(const Runtime& rt) {
    rt_ = rt;
    if (inflight_.size() > static_cast<size_t>(cfg_.mem_max_outstanding) * 8u) {
        inflight_.clear();
    }
    resetMemTimingState_();

    // Program mode: parse DSL after runtime is available (for strict fatal logging).
    program_ops_.clear();
    program_loop_enable_ = cfg_.program_loop;
    program_iter_done_ = 0;
    program_pc_ = 0;
    program_op_started_ = false;
    program_softmax_rem_cycles_ = 0;
    program_gemm_started_ = false;
    program_collective_started_ = false;
    program_m7_enable_ = false;
    program_fence_pending_ = false;
    program_addr_aware_enable_ = false;
    const uint32_t ub_bufs = std::max<uint32_t>(cfg_.program_ub_buffers, 1u);
    program_ub_reserved_bytes_by_buf_.assign(ub_bufs, 0ull);
    program_ub_valid_bytes_by_buf_.assign(ub_bufs, 0ull);
    program_ub_regions_by_buf_.assign(ub_bufs, std::unordered_map<uint64_t, ProgramUbRegion>{});
    tensor_program_ub_occupancy_bytes_max_ = 0;
    program_dma_epoch_next_ = 1;
    program_dma_read_slot_ = ProgramDmaSlot{};
    program_dma_write_slot_ = ProgramDmaSlot{};
    program_mxu_slot_ = ProgramMxuSlot{};
    program_vec_slot_ = ProgramVecSlot{};
    program_coll_slot_ = ProgramCollSlot{};

    if (cfg_.exec_mode == "program") {
        std::vector<ProgramOp> ops;
        const std::string dsl = cfg_.program_dsl;
        if (!dsl.empty() && parseProgramDsl_(dsl, ops)) {
            program_ops_ = std::move(ops);
            for (const auto& op : program_ops_) {
                if (op.ub_addr_present || op.ub_read_addr_present || op.ub_write_addr_present) {
                    program_addr_aware_enable_ = true;
                }
                if (op.kind == ProgramOpKind::DmaRead ||
                    op.kind == ProgramOpKind::DmaWrite ||
                    op.kind == ProgramOpKind::Fence ||
                    op.kind == ProgramOpKind::GemmUb) {
                    program_m7_enable_ = true;
                }
            }

            if (program_addr_aware_enable_) {
                const uint64_t ub_bytes = cfg_.ub_bytes;
                if (ub_bytes == 0 || (ub_bytes % static_cast<uint64_t>(ub_bufs)) != 0) {
                    if (cfg_.strict && rt_.log) {
                        rt_.log->fatal(
                            CALL_INFO,
                            -1,
                            "tensor fatal: program address-aware mode requires tensor_ub_bytes divisible by tensor_program_ub_buffers "
                            "(core=%u ub_bytes=%llu ub_buffers=%u)\n",
                            rt_.core_id,
                            (unsigned long long)ub_bytes,
                            ub_bufs);
                    }
                    program_addr_aware_enable_ = false;
                }
            }
        } else if (cfg_.strict && rt_.log) {
            rt_.log->fatal(
                CALL_INFO,
                -1,
                "tensor fatal: exec_mode=program but tensor_program_dsl is empty or invalid (core=%u)\n",
                rt_.core_id);
        }
    }
}

bool TensorWorkload::parseProgramDsl_(const std::string& dsl, std::vector<ProgramOp>& out_ops) const {
    out_ops.clear();

    auto trim_copy = [](const std::string& s) -> std::string {
        size_t b = 0;
        while (b < s.size() && std::isspace(static_cast<unsigned char>(s[b]))) b++;
        size_t e = s.size();
        while (e > b && std::isspace(static_cast<unsigned char>(s[e - 1]))) e--;
        return s.substr(b, e - b);
    };
    auto parse_u64 = [](const std::string& s, uint64_t& out) -> bool {
        try {
            size_t idx = 0;
            const unsigned long long v = std::stoull(s, &idx, 0);
            if (idx != s.size()) return false;
            out = static_cast<uint64_t>(v);
            return true;
        } catch (...) {
            return false;
        }
    };
    auto parse_bool01 = [&](const std::string& s, bool& out) -> bool {
        const std::string v = to_lower_copy_(trim_copy(s));
        if (v == "1" || v == "true" || v == "yes" || v == "y") {
            out = true;
            return true;
        }
        if (v == "0" || v == "false" || v == "no" || v == "n") {
            out = false;
            return true;
        }
        return false;
    };

    size_t pos = 0;
    while (pos < dsl.size()) {
        const size_t next = dsl.find(';', pos);
        const size_t len = (next == std::string::npos) ? (dsl.size() - pos) : (next - pos);
        std::string token = trim_copy(dsl.substr(pos, len));
        pos = (next == std::string::npos) ? dsl.size() : (next + 1);
        if (token.empty()) continue;

        std::string op_str = token;
        std::string args_str;
        const size_t colon = token.find(':');
        if (colon != std::string::npos) {
            op_str = token.substr(0, colon);
            args_str = token.substr(colon + 1);
        }
        const std::string op = to_lower_copy_(trim_copy(op_str));
        if (op.empty()) continue;

        ProgramOp out{};
        if (op == "gemm") {
            out.kind = ProgramOpKind::Gemm;
        } else if (op == "allreduce") {
            out.kind = ProgramOpKind::Allreduce;
            out.blocking = true;
        } else if (op == "softmax") {
            out.kind = ProgramOpKind::Softmax;
        } else if (op == "dma_read") {
            out.kind = ProgramOpKind::DmaRead;
        } else if (op == "dma_write") {
            out.kind = ProgramOpKind::DmaWrite;
        } else if (op == "fence") {
            out.kind = ProgramOpKind::Fence;
        } else if (op == "gemm_ub") {
            out.kind = ProgramOpKind::GemmUb;
        } else {
            return false;
        }

        args_str = trim_copy(args_str);
        if (!args_str.empty()) {
            size_t ap = 0;
            while (ap < args_str.size()) {
                const size_t anext = args_str.find(',', ap);
                const size_t alen = (anext == std::string::npos) ? (args_str.size() - ap) : (anext - ap);
                std::string arg = trim_copy(args_str.substr(ap, alen));
                ap = (anext == std::string::npos) ? args_str.size() : (anext + 1);
                if (arg.empty()) continue;

                std::string k = arg;
                std::string v;
                const size_t eq = arg.find('=');
                if (eq != std::string::npos) {
                    k = arg.substr(0, eq);
                    v = arg.substr(eq + 1);
                } else {
                    v = "";
                }
                k = to_lower_copy_(trim_copy(k));
                v = trim_copy(v);

                if (out.kind == ProgramOpKind::Allreduce) {
                    if (k == "bytes") {
                        uint64_t bv = 0;
                        if (!parse_u64(v, bv)) return false;
                        out.bytes = bv;
                    } else if (k == "blocking") {
                        bool b = true;
                        if (v.empty()) {
                            b = true;
                        } else if (!parse_bool01(v, b)) {
                            return false;
                        }
                        out.blocking = b;
                    } else {
                        return false;
                    }
                } else if (out.kind == ProgramOpKind::Softmax) {
                    if (k == "elems") {
                        uint64_t ev = 0;
                        if (!parse_u64(v, ev) || ev == 0) return false;
                        out.elems = ev;
                    } else {
                        return false;
                    }
                } else if (out.kind == ProgramOpKind::DmaRead || out.kind == ProgramOpKind::DmaWrite) {
                    if (k == "bytes") {
                        uint64_t bv = 0;
                        if (!parse_u64(v, bv) || bv == 0) return false;
                        out.bytes = bv;
                    } else if (k == "buf") {
                        uint64_t bv = 0;
                        if (!parse_u64(v, bv)) return false;
                        if (bv > static_cast<uint64_t>(std::numeric_limits<uint32_t>::max())) return false;
                        const uint32_t buf = static_cast<uint32_t>(bv);
                        if (buf >= std::max<uint32_t>(cfg_.program_ub_buffers, 1u)) return false;
                        out.buf = buf;
                    } else if (k == "ub_addr") {
                        uint64_t av = 0;
                        if (!parse_u64(v, av)) return false;
                        out.ub_addr_present = true;
                        out.ub_addr = av;
                    } else if (out.kind == ProgramOpKind::DmaRead && k == "reset") {
                        bool b = true;
                        if (v.empty()) {
                            b = true;
                        } else if (!parse_bool01(v, b)) {
                            return false;
                        }
                        out.reset = b;
                    } else if (out.kind == ProgramOpKind::DmaWrite && k == "consume") {
                        bool b = true;
                        if (v.empty()) {
                            b = true;
                        } else if (!parse_bool01(v, b)) {
                            return false;
                        }
                        out.consume = b;
                    } else {
                        return false;
                    }
                } else if (out.kind == ProgramOpKind::GemmUb) {
                    if (k == "cycles") {
                        uint64_t cv = 0;
                        if (!parse_u64(v, cv)) return false;
                        out.cycles = cv;
                    } else if (k == "ub_read" || k == "ub_read_bytes") {
                        uint64_t bv = 0;
                        if (!parse_u64(v, bv)) return false;
                        out.ub_read_bytes = bv;
                    } else if (k == "ub_write" || k == "ub_write_bytes") {
                        uint64_t bv = 0;
                        if (!parse_u64(v, bv)) return false;
                        out.ub_write_bytes = bv;
                    } else if (k == "buf") {
                        uint64_t bv = 0;
                        if (!parse_u64(v, bv)) return false;
                        if (bv > static_cast<uint64_t>(std::numeric_limits<uint32_t>::max())) return false;
                        const uint32_t buf = static_cast<uint32_t>(bv);
                        if (buf >= std::max<uint32_t>(cfg_.program_ub_buffers, 1u)) return false;
                        out.buf = buf;
                    } else if (k == "ub_read_addr") {
                        uint64_t av = 0;
                        if (!parse_u64(v, av)) return false;
                        out.ub_read_addr_present = true;
                        out.ub_read_addr = av;
                    } else if (k == "ub_write_addr") {
                        uint64_t av = 0;
                        if (!parse_u64(v, av)) return false;
                        out.ub_write_addr_present = true;
                        out.ub_write_addr = av;
                    } else if (k == "m" || k == "tm") {
                        uint64_t mv = 0;
                        if (!parse_u64(v, mv)) return false;
                        if (mv > static_cast<uint64_t>(std::numeric_limits<uint32_t>::max())) return false;
                        out.m = static_cast<uint32_t>(mv);
                    } else if (k == "n" || k == "tn") {
                        uint64_t nv = 0;
                        if (!parse_u64(v, nv)) return false;
                        if (nv > static_cast<uint64_t>(std::numeric_limits<uint32_t>::max())) return false;
                        out.n = static_cast<uint32_t>(nv);
                    } else if (k == "k" || k == "tk") {
                        uint64_t kvv = 0;
                        if (!parse_u64(v, kvv)) return false;
                        if (kvv > static_cast<uint64_t>(std::numeric_limits<uint32_t>::max())) return false;
                        out.k = static_cast<uint32_t>(kvv);
                    } else {
                        return false;
                    }
                } else {
                    // GEMM/FENCE: no args.
                    return false;
                }
            }
        } else {
            if (out.kind == ProgramOpKind::DmaRead || out.kind == ProgramOpKind::DmaWrite) {
                return false;
            }
        }

        if ((out.kind == ProgramOpKind::DmaRead || out.kind == ProgramOpKind::DmaWrite) && out.bytes == 0) {
            return false;
        }
        if (out.kind == ProgramOpKind::Softmax && out.elems == 0) {
            return false;
        }
        if (out.kind == ProgramOpKind::GemmUb && out.cycles == 0) {
            if (out.m == 0 || out.n == 0 || out.k == 0) {
                return false;
            }
        }

        out_ops.push_back(out);
    }

    return !out_ops.empty();
}

uint64_t TensorWorkload::estimateGemmUbCycles_(uint32_t m, uint32_t n, uint32_t k) const {
    if (m == 0u || n == 0u || k == 0u) return 1ull;

    const uint64_t mm = static_cast<uint64_t>(m);
    const uint64_t nn = static_cast<uint64_t>(n);
    const uint64_t kk = static_cast<uint64_t>(k);
    const uint64_t macs = saturatingMulU64_(saturatingMulU64_(mm, nn), kk);
    const uint64_t thr = effectivePeakMacsPerCycle_();
    const uint64_t math = ceilDivU64_(std::max<uint64_t>(1ull, macs), std::max<uint64_t>(1ull, thr));
    const uint64_t pipe = static_cast<uint64_t>(compute_pipeline_latency_cycles_effective_);
    const uint64_t base_total = saturatingAddU64_(math ? math : 1ull, pipe);

    uint64_t extra = 0;
    if (cfg_.mxu_wavefront_enable && cfg_.mxu_wavefront_alpha > 0.0f) {
        const uint64_t am = clampNonZero_(static_cast<uint64_t>(cfg_.array_m), 1ull);
        const uint64_t an = clampNonZero_(static_cast<uint64_t>(cfg_.array_n), 1ull);
        const uint64_t mb = ceilDivU64_(mm, am);
        const uint64_t nb = ceilDivU64_(nn, an);
        const uint64_t m_blk = std::min<uint64_t>(mm, am);
        const uint64_t n_blk = std::min<uint64_t>(nn, an);
        const uint64_t span_blk = (m_blk > 0 && n_blk > 0 && kk > 0) ? (m_blk + n_blk + kk - 2ull) : 0ull;
        const uint64_t wf_span = saturatingMulU64_(saturatingMulU64_(mb, nb), span_blk);
        const double wf_body_d = static_cast<double>(cfg_.mxu_wavefront_alpha) * static_cast<double>(wf_span);
        const uint64_t wf_body = static_cast<uint64_t>(std::ceil(std::max(0.0, wf_body_d)));
        const uint64_t wf_total = saturatingAddU64_((wf_body ? wf_body : 1ull), pipe);
        if (wf_total > base_total) {
            extra = wf_total - base_total;
        }
    }

    const uint64_t total = saturatingAddU64_(base_total, extra);
    return total ? total : 1ull;
}

bool TensorWorkload::startProgramCollective_(uint64_t now_cycle, uint64_t bytes, bool blocking) {
    (void)blocking;
    if (collectivePendingActive_()) return true;
    if (cfg_.collective_type == "none") return false;
    if (!rt_.noc) {
        if (cfg_.strict && rt_.log) {
            rt_.log->fatal(CALL_INFO, -1, "tensor fatal: collective enabled but INocTransport is null (core=%u)\n", rt_.core_id);
        }
        return false;
    }

    const uint64_t collective_bytes = (bytes > 0) ? bytes : cfg_.collective_bytes;
    if (collective_bytes == 0) return false;

    const uint32_t seq32 = static_cast<uint32_t>(collective_seq_ & 0xffffffffu);
    collective_pending_active_ = true;
    collective_pending_seq_ = seq32;
    collective_pending_sent_bytes_ = 0;
    collective_pending_next_dest_ = 0;
    collective_pending_dest_nodes_.clear();
    collective_pending_dest_remaining_bytes_.clear();
    collective_ring_active_ = false;
    collective_ring_total_payload_bytes_ = 0;
    collective_ring_sent_payload_bytes_ = 0;
    collective_ring_reduce_wait_cycles_remaining_ = 0;
    collective_2d_active_ = false;
    collective_2d_dim_x_ = 0;
    collective_2d_dim_y_ = 0;
    collective_2d_row_hop_ = 0;
    collective_2d_col_hop_ = 0;

    if (cfg_.collective_algo == "ring_chunked" || cfg_.collective_algo == "torus_2d_rs_ag") {
        collective_active_bytes_ = collective_bytes;
        const uint32_t chunk_bytes = std::max<uint32_t>(
            cfg_.collective_chunk_bytes ? cfg_.collective_chunk_bytes : cfg_.collective_packet_bytes,
            8u);
        uint32_t steps_per_chunk = 0;
        if (cfg_.collective_algo == "torus_2d_rs_ag") {
            collective_2d_active_ = true;
            const uint32_t total_nodes = (rt_.total_nodes > 0) ? static_cast<uint32_t>(rt_.total_nodes) : 1u;
            uint32_t dim_x = cfg_.collective_2d_dim_x;
            uint32_t dim_y = cfg_.collective_2d_dim_y;
            auto fallback_dims = [&]() {
                const uint32_t sq = static_cast<uint32_t>(std::sqrt(static_cast<double>(total_nodes)));
                if (sq > 0 && sq * sq == total_nodes) {
                    dim_x = sq;
                    dim_y = sq;
                } else {
                    dim_x = total_nodes;
                    dim_y = 1u;
                }
            };
            if (dim_x == 0u || dim_y == 0u ||
                (static_cast<uint64_t>(dim_x) * static_cast<uint64_t>(dim_y) != static_cast<uint64_t>(total_nodes))) {
                fallback_dims();
            }
            if (dim_x == 0u) dim_x = 1u;
            if (dim_y == 0u) dim_y = 1u;
            collective_2d_dim_x_ = dim_x;
            collective_2d_dim_y_ = dim_y;
            collective_2d_row_hop_ = (dim_x > 1u) ? (dim_x - 1u) : 1u;
            collective_2d_col_hop_ = (dim_y > 1u) ? (dim_y - 1u) : 1u;
            steps_per_chunk = 2u * (collective_2d_row_hop_ + collective_2d_col_hop_);
        } else {
            steps_per_chunk = collectiveRingStepsPerChunk_();
        }
        steps_per_chunk = std::max<uint32_t>(steps_per_chunk, 1u);
        const uint32_t chunks_total = static_cast<uint32_t>(
            std::max<uint64_t>(1ull, ceilDivU64_(collective_active_bytes_, static_cast<uint64_t>(chunk_bytes))));

        collective_ring_active_ = true;
        collective_ring_seq_ = seq32;
        collective_ring_chunks_total_ = chunks_total;
        collective_ring_steps_per_chunk_ = steps_per_chunk;
        collective_ring_chunk_index_ = 0;
        collective_ring_step_index_ = 0;
        collective_ring_step_remaining_bytes_ = collectiveRingStepPayloadBytes_(0, 0);
        collective_ring_max_inflight_chunks_ = std::max<uint32_t>(cfg_.collective_max_inflight_chunks, 1u);

        uint64_t total_payload = 0;
        for (uint32_t chunk_idx = 0; chunk_idx < chunks_total; ++chunk_idx) {
            for (uint32_t step = 0; step < steps_per_chunk; ++step) {
                const uint64_t payload = static_cast<uint64_t>(collectiveRingStepPayloadBytes_(chunk_idx, step));
                total_payload = saturatingAddU64_(total_payload, payload);
            }
        }
        collective_ring_total_payload_bytes_ = total_payload;
        collective_pending_total_bytes_ = total_payload;
        tensor_collective_chunk_groups_total_ += static_cast<uint64_t>(chunks_total);
    } else {
        const uint32_t total_nodes = (rt_.total_nodes > 0) ? static_cast<uint32_t>(rt_.total_nodes) : 1u;
        std::vector<uint32_t> dest_nodes;
        dest_nodes.reserve(2);

        const bool use_mesh_x = (cfg_.collective_pattern == "mesh_x");
        const bool use_mesh_xy = (cfg_.collective_pattern == "mesh_xy");
        if ((use_mesh_x || use_mesh_xy) && total_nodes > 1) {
            const uint32_t mesh_size = static_cast<uint32_t>(std::sqrt(static_cast<double>(total_nodes)));
            if (mesh_size > 0 && mesh_size * mesh_size == total_nodes) {
                const uint32_t node_x = static_cast<uint32_t>(rt_.node_id) % mesh_size;
                const uint32_t node_y = static_cast<uint32_t>(rt_.node_id) / mesh_size;
                const uint32_t east = node_y * mesh_size + ((node_x + 1u) % mesh_size);
                dest_nodes.push_back(east);
                if (use_mesh_xy) {
                    const uint32_t south = ((node_y + 1u) % mesh_size) * mesh_size + node_x;
                    if (south != east) {
                        dest_nodes.push_back(south);
                    }
                }
            }
        }
        if (dest_nodes.empty()) {
            dest_nodes.push_back((static_cast<uint32_t>(rt_.node_id) + 1u) % total_nodes);
        }

        const uint64_t min_total_bytes = static_cast<uint64_t>(dest_nodes.size()) * 8ull;
        const uint64_t total_bytes = std::max<uint64_t>(collective_bytes, min_total_bytes);
        collective_active_bytes_ = total_bytes;
        const uint64_t dest_count = static_cast<uint64_t>(dest_nodes.size());
        if (dest_count == 0 || total_bytes == 0) return false;

        const uint64_t base_bytes = total_bytes / dest_count;
        const uint64_t remainder = total_bytes % dest_count;
        collective_pending_total_bytes_ = total_bytes;
        collective_pending_dest_nodes_ = dest_nodes;
        collective_pending_dest_remaining_bytes_.assign(dest_nodes.size(), 0);
        for (size_t dest_index = 0; dest_index < dest_nodes.size(); ++dest_index) {
            collective_pending_dest_remaining_bytes_[dest_index] = base_bytes + ((dest_index < remainder) ? 1u : 0u);
        }
    }

    collective_last_cycle_ = now_cycle;
    tensor_collective_cycles_total_ += 1;
    if (cfg_.collective_blocking) {
        collective_epoch_active_ = true;
        collective_epoch_seq_ = seq32;
        collective_epoch_expected_recv_bytes_ = collective_pending_total_bytes_;
        collective_epoch_recv_bytes_ = collectiveRecvBytesForSeq_(seq32);
        collective_epoch_start_cycle_ = now_cycle;
        collective_done_notified_ = false;
    }
    if (!cfg_.collective_blocking || cfg_.collective_scope == "per_core") {
        collective_seq_ += 1;
    }

    return true;
}

void TensorWorkload::onGlobalStepStart(uint32_t seq) {
    (void)seq;
    step_gated_ = true;
    step_open_ = true;
    step_seq_ = seq;
    if (cfg_.exec_mode == "program") {
        program_pc_ = 0;
        program_op_started_ = false;
        program_softmax_rem_cycles_ = 0;
        program_gemm_started_ = false;
        program_collective_started_ = false;
    }
}

void TensorWorkload::startIteration_() {
    iter_active_ = true;
    compute_started_ = (cfg_.exec_mode == "bulk") ? (cfg_.overlap_enable || cfg_.double_buffer) : false;
    rem_read_bytes_ = (cfg_.mem_enable && rt_.mem) ? bytes_read_per_iter_ : 0;
    rem_write_bytes_ = (cfg_.mem_enable && rt_.mem) ? bytes_write_per_iter_ : 0;
    rem_compute_math_cycles_ = compute_math_cycles_per_iter_;
    rem_compute_pipeline_cycles_ = compute_pipeline_cycles_per_iter_;
    rem_compute_cycles_ = compute_cycles_per_iter_;
    rem_macs_ = mac_ops_per_iter_;

    // Deterministic address offsets per-iteration (avoid trivially reusing the same cache lines).
    const uint64_t region = clampNonZero_(cfg_.mem_region_bytes, 4096);
    uint64_t rng = cfg_.seed_base ^
                   (static_cast<uint64_t>(rt_.node_id) << 32) ^
                   (static_cast<uint64_t>(rt_.core_id) << 16) ^
                   static_cast<uint64_t>(iter_seq_) ^
                   (static_cast<uint64_t>(step_seq_) << 48);
    read_off_ = (region > 0) ? (splitmix64_next_(rng) % region) : 0;
    write_off_ = (region > 0) ? ((read_off_ + (region / 2u)) % region) : 0;

    tensor_tile_count_total_ += tile_count_per_iter_;
    tensor_dram_bytes_total_ += dram_bytes_per_iter_;
    tensor_onchip_bytes_total_ += onchip_bytes_per_iter_;
    tensor_dma_cycles_total_ += dma_cycles_per_iter_;
    onchip_ub_occupancy_bytes_ = 0;
    onchip_weight_occupancy_bytes_ = 0;
    onchip_acc_occupancy_bytes_ = 0;
    std::fill(onchip_ub_bank_occupancy_bytes_.begin(), onchip_ub_bank_occupancy_bytes_.end(), 0ull);
    std::fill(onchip_weight_bank_occupancy_bytes_.begin(), onchip_weight_bank_occupancy_bytes_.end(), 0ull);
    std::fill(onchip_acc_bank_occupancy_bytes_.begin(), onchip_acc_bank_occupancy_bytes_.end(), 0ull);
    std::fill(onchip_ub_bank_queue_occupancy_.begin(), onchip_ub_bank_queue_occupancy_.end(), 0u);
    std::fill(onchip_weight_bank_queue_occupancy_.begin(), onchip_weight_bank_queue_occupancy_.end(), 0u);
    std::fill(onchip_acc_bank_queue_occupancy_.begin(), onchip_acc_bank_queue_occupancy_.end(), 0u);
    onchip_ub_bank_rr_ = 0;
    onchip_weight_bank_rr_ = 0;
    onchip_acc_bank_rr_ = 0;
    if (!collectiveUseEventCreditReturn_()) {
        collective_credit_inflight_chunks_ = 0;
        collective_credit_outstanding_.clear();
        collective_credit_return_seen_.clear();
        collective_credit_return_pending_credits_.clear();
        collective_credit_return_pending_queue_.clear();
    }
    acc_reserved_tiles_.clear();
    a_resident_tiles_.clear();
    b_resident_tiles_.clear();

    tile_mode_active_ = (cfg_.exec_mode == "tile" || cfg_.exec_mode == "program");
    if (tile_mode_active_) {
        resetTileIteration_();
    }

    iter_seq_++;
}

void TensorWorkload::resetTileIteration_() {
    tile_mode_active_ = true;

    tile_seg_gen_index_ = 0;
    tile_gen_mi_ = 0;
    tile_gen_ni_ = 0;
    tile_gen_ki_ = 0;
    tile_gen_done_ = false;
    tile_seg_done_ = 0;
    tile_cur_ = TileSegState{};
    tile_next_ = TileSegState{};
    tile_writeback_queue_.clear();
    tile_writebacks_.clear();

    (void)generateNextTileSeg_(tile_cur_);
    const bool prefetch = (cfg_.overlap_enable || cfg_.double_buffer);
    if (prefetch) {
        (void)generateNextTileSeg_(tile_next_);
    }
}

bool TensorWorkload::advanceTileIndices_(uint32_t& mi, uint32_t& ni, uint32_t& ki) const {
    if (tile_schedule_eff_ == "mkn") {
        // m outer, k middle, n inner
        ni++;
        if (ni < tile_nt_) return true;
        ni = 0;
        ki++;
        if (ki < tile_kt_) return true;
        ki = 0;
        mi++;
        return (mi < tile_mt_);
    }
    if (tile_schedule_eff_ == "nkm") {
        // n outer, k middle, m inner
        mi++;
        if (mi < tile_mt_) return true;
        mi = 0;
        ki++;
        if (ki < tile_kt_) return true;
        ki = 0;
        ni++;
        return (ni < tile_nt_);
    }
    // default: mnk (m outer, n middle, k inner)
    ki++;
    if (ki < tile_kt_) return true;
    ki = 0;
    ni++;
    if (ni < tile_nt_) return true;
    ni = 0;
    mi++;
    return (mi < tile_mt_);
}

uint64_t TensorWorkload::tileSegMathCycles_(uint64_t seg_index) const {
    const uint64_t extra = (seg_index < tile_seg_math_cycles_remainder_) ? 1ull : 0ull;
    return tile_seg_math_cycles_base_ + extra;
}

uint64_t TensorWorkload::tileSegComputeCycles_(uint64_t seg_index) const {
    const uint64_t math_cycles = tileSegMathCycles_(seg_index);
    return saturatingAddU64_(math_cycles, static_cast<uint64_t>(compute_pipeline_latency_cycles_effective_));
}

uint64_t TensorWorkload::tileNeedReadABytes_(uint32_t /*mi*/, uint32_t ni, uint32_t /*ki*/) const {
    if (!cfg_.mem_enable || !rt_.mem) return 0;
    if (cfg_.dataflow == "is" && tile_keep_a_) {
        return (ni == 0) ? tile_a_bytes_ : 0;
    }
    return tile_a_bytes_;
}

uint64_t TensorWorkload::tileNeedReadBBytes_(uint32_t mi, uint32_t /*ni*/, uint32_t /*ki*/) const {
    if (!cfg_.mem_enable || !rt_.mem) return 0;
    if (cfg_.dataflow == "ws" && tile_keep_b_) {
        return (mi == 0) ? tile_b_bytes_ : 0;
    }
    return tile_b_bytes_;
}

bool TensorWorkload::generateNextTileSeg_(TileSegState& out) {
    if (tile_gen_done_) {
        out = TileSegState{};
        return false;
    }
    if (tile_seg_gen_index_ >= tile_count_per_iter_) {
        tile_gen_done_ = true;
        out = TileSegState{};
        return false;
    }

    out = TileSegState{};
    out.valid = true;
    out.seg_index = tile_seg_gen_index_;
    out.epoch = out.seg_index + 1ull;
    out.mi = tile_gen_mi_;
    out.ni = tile_gen_ni_;
    out.ki = tile_gen_ki_;
    out.need_a_bytes = tileNeedReadABytes_(out.mi, out.ni, out.ki);
    out.need_b_bytes = tileNeedReadBBytes_(out.mi, out.ni, out.ki);
    out.rem_compute_math_cycles = tileSegMathCycles_(out.seg_index);
    out.rem_compute_pipeline_cycles = static_cast<uint64_t>(compute_pipeline_latency_cycles_effective_);
    out.rem_compute_wavefront_cycles = 0;
    const uint64_t base_total = out.rem_compute_math_cycles + out.rem_compute_pipeline_cycles;
    if (cfg_.mxu_wavefront_enable && cfg_.mxu_wavefront_alpha > 0.0f) {
        const uint64_t m0 = static_cast<uint64_t>(out.mi) * static_cast<uint64_t>(tile_tm_);
        const uint64_t n0 = static_cast<uint64_t>(out.ni) * static_cast<uint64_t>(tile_tn_);
        const uint64_t k0 = static_cast<uint64_t>(out.ki) * static_cast<uint64_t>(tile_tk_);
        const uint64_t m_eff = (m0 < cfg_.m) ? std::min<uint64_t>(tile_tm_, static_cast<uint64_t>(cfg_.m) - m0) : 0ull;
        const uint64_t n_eff = (n0 < cfg_.n) ? std::min<uint64_t>(tile_tn_, static_cast<uint64_t>(cfg_.n) - n0) : 0ull;
        const uint64_t k_eff = (k0 < cfg_.k) ? std::min<uint64_t>(tile_tk_, static_cast<uint64_t>(cfg_.k) - k0) : 0ull;
        uint64_t wf_span = 0;
        if (m_eff > 0 && n_eff > 0 && k_eff > 0) {
            // Approximate systolic fill/drain latency. If the tile exceeds the physical
            // array dimensions, model it as multiple array-sized blocks (e.g., 64x64 on
            // a 32x32 array => 2x2 blocks).
            const uint64_t am = clampNonZero_(static_cast<uint64_t>(cfg_.array_m), 1ull);
            const uint64_t an = clampNonZero_(static_cast<uint64_t>(cfg_.array_n), 1ull);
            const uint64_t mb = ceilDivU64_(m_eff, am);
            const uint64_t nb = ceilDivU64_(n_eff, an);
            const uint64_t m_blk = std::min<uint64_t>(m_eff, am);
            const uint64_t n_blk = std::min<uint64_t>(n_eff, an);
            const uint64_t span_blk = m_blk + n_blk + k_eff - 2ull;
            wf_span = saturatingMulU64_(saturatingMulU64_(mb, nb), span_blk);
        }
        const double wf_body_d = static_cast<double>(cfg_.mxu_wavefront_alpha) * static_cast<double>(wf_span);
        const uint64_t wf_body = static_cast<uint64_t>(std::ceil(std::max(0.0, wf_body_d)));
        const uint64_t wf_total = (wf_body ? wf_body : 1ull) + out.rem_compute_pipeline_cycles;
        if (wf_total > base_total) {
            out.rem_compute_wavefront_cycles = wf_total - base_total;
        }
    }
    out.rem_compute_cycles = out.rem_compute_math_cycles + out.rem_compute_pipeline_cycles + out.rem_compute_wavefront_cycles;

    tile_seg_gen_index_++;
    const bool ok = advanceTileIndices_(tile_gen_mi_, tile_gen_ni_, tile_gen_ki_);
    if (!ok) {
        tile_gen_done_ = true;
    }
    return true;
}

void TensorWorkload::scheduleWriteback_(uint32_t mi, uint32_t ni) {
    if (!cfg_.mem_enable || !rt_.mem) return;
    if (tile_c_bytes_ == 0) return;
    const uint64_t epoch = (1ull << 63) | (static_cast<uint64_t>(mi) << 32) | static_cast<uint64_t>(ni);
    if (tile_writebacks_.find(epoch) != tile_writebacks_.end()) return;

    WritebackState st;
    st.epoch = epoch;
    st.mi = mi;
    st.ni = ni;
    st.total_bytes = tile_c_bytes_;
    st.issued_bytes = 0;
    st.done_bytes = 0;
    tile_writebacks_.emplace(epoch, st);
    tile_writeback_queue_.push_back(epoch);
}

void TensorWorkload::retireCompletedWritebacks_() {
    while (!tile_writeback_queue_.empty()) {
        const uint64_t epoch = tile_writeback_queue_.front();
        auto it = tile_writebacks_.find(epoch);
        if (it == tile_writebacks_.end()) {
            tile_writeback_queue_.pop_front();
            continue;
        }
        if (it->second.done_bytes < it->second.total_bytes) break;
        releaseAccTile_(it->second.mi, it->second.ni);
        tile_writebacks_.erase(it);
        tile_writeback_queue_.pop_front();
    }
}

uint32_t TensorWorkload::issueMemReadTagged_(uint32_t max_bytes, MemTag tag, uint64_t epoch) {
    if (!cfg_.mem_enable) return 0;
    if (!rt_.mem) {
        if (cfg_.strict && rt_.log) {
            rt_.log->fatal(CALL_INFO, -1, "tensor fatal: mem_enable=1 but IMemoryAccess is null (core=%u)\n", rt_.core_id);
        }
        return 0;
    }
    if (max_bytes == 0) return 0;
    if (inflight_.size() >= static_cast<size_t>(cfg_.mem_max_outstanding)) return 0;

    uint32_t bytes = static_cast<uint32_t>(std::min<uint32_t>(max_bytes, cfg_.mem_req_bytes));
    const uint64_t region = clampNonZero_(cfg_.mem_region_bytes, 4096);
    uint64_t off = read_off_;
    const uint32_t channels = hbmChannelCount_();
    if (channels > 1u) {
        const uint64_t interleave = std::max<uint64_t>(cfg_.dma_hbm_channel_interleave_bytes, 1ull);
        const uint64_t rem = interleave - (off % interleave);
        bytes = static_cast<uint32_t>(std::min<uint64_t>(static_cast<uint64_t>(bytes), rem));
    }
    if (off + bytes > region) off = 0;
    const uint64_t proxy_delay_cycles = memTimingProxyDelayCycles_(ReqKind::Read, off, bytes, now_cycle_cached_);
    const uint64_t addr = memOffsetToPhysicalAddr_(off);
    read_off_ = off + bytes;
    if (read_off_ >= region) read_off_ = 0;

    if (rt_.reporting.report_mem_issue) {
        rt_.reporting.report_mem_issue(rt_.reporting.ctx, bytes);
    }
    memory_requests_++;
    tensor_mem_reads_issued_total_ += 1;
    tensor_mem_bytes_read_total_ += static_cast<uint64_t>(bytes);
    const uint64_t issue_ns = nowNs_();

    const auto req_id = rt_.mem->read(
        addr, bytes,
        [this, addr, bytes, tag, epoch](IMemoryAccess::RequestId cb_id, uint64_t /*addr_cb*/, std::vector<uint8_t>&& got) {
            if (cb_id == 0 || got.size() != bytes) {
                if (cfg_.strict && rt_.log) {
                    rt_.log->fatal(
                        CALL_INFO, -1,
                        "tensor fatal: read failed (core=%u addr=0x%llx bytes=%u got=%zu)\n",
                        rt_.core_id, (unsigned long long)addr, bytes, got.size());
                }
                return;
            }
            onMemResponse_(static_cast<uint64_t>(cb_id), ReqKind::Read, tag, epoch, bytes);
        });
    if (req_id != 0) {
        inflight_[static_cast<uint64_t>(req_id)] = InflightReq{
            ReqKind::Read,
            tag,
            epoch,
            bytes,
            issue_ns,
            proxy_delay_cycles,
        };
    } else if (cfg_.strict && rt_.log) {
        rt_.log->fatal(
            CALL_INFO, -1,
            "tensor fatal: read issue failed (core=%u addr=0x%llx bytes=%u)\n",
            rt_.core_id, (unsigned long long)addr, bytes);
    }

    return bytes;
}

uint32_t TensorWorkload::issueMemWriteTagged_(uint32_t max_bytes, MemTag tag, uint64_t epoch) {
    if (!cfg_.mem_enable) return 0;
    if (!rt_.mem) {
        if (cfg_.strict && rt_.log) {
            rt_.log->fatal(CALL_INFO, -1, "tensor fatal: mem_enable=1 but IMemoryAccess is null (core=%u)\n", rt_.core_id);
        }
        return 0;
    }
    if (max_bytes == 0) return 0;
    if (inflight_.size() >= static_cast<size_t>(cfg_.mem_max_outstanding)) return 0;

    uint32_t bytes = static_cast<uint32_t>(std::min<uint32_t>(max_bytes, cfg_.mem_req_bytes));
    const uint64_t region = clampNonZero_(cfg_.mem_region_bytes, 4096);
    uint64_t off = write_off_;
    const uint32_t channels = hbmChannelCount_();
    if (channels > 1u) {
        const uint64_t interleave = std::max<uint64_t>(cfg_.dma_hbm_channel_interleave_bytes, 1ull);
        const uint64_t rem = interleave - (off % interleave);
        bytes = static_cast<uint32_t>(std::min<uint64_t>(static_cast<uint64_t>(bytes), rem));
    }
    if (off + bytes > region) off = 0;
    const uint64_t proxy_delay_cycles = memTimingProxyDelayCycles_(ReqKind::Write, off, bytes, now_cycle_cached_);
    const uint64_t addr = memOffsetToPhysicalAddr_(off);
    write_off_ = off + bytes;
    if (write_off_ >= region) write_off_ = 0;

    std::vector<uint8_t> data;
    data.resize(bytes);
    fillBytesDeterministic_(cfg_.seed_base ^
                                (static_cast<uint64_t>(rt_.node_id) << 32) ^
                                (static_cast<uint64_t>(rt_.core_id) << 16),
                            addr, static_cast<uint32_t>(epoch), data);

    if (rt_.reporting.report_mem_issue) {
        rt_.reporting.report_mem_issue(rt_.reporting.ctx, bytes);
    }
    memory_requests_++;
    tensor_mem_writes_issued_total_ += 1;
    tensor_mem_bytes_write_total_ += static_cast<uint64_t>(bytes);
    const uint64_t issue_ns = nowNs_();

    const auto req_id = rt_.mem->write(
        addr, data,
        [this, addr, bytes, tag, epoch](IMemoryAccess::RequestId cb_id, uint64_t /*addr_cb*/) {
            if (cb_id == 0) {
                if (cfg_.strict && rt_.log) {
                    rt_.log->fatal(
                        CALL_INFO, -1,
                        "tensor fatal: write failed (core=%u addr=0x%llx bytes=%u)\n",
                        rt_.core_id, (unsigned long long)addr, bytes);
                }
                return;
            }
            onMemResponse_(static_cast<uint64_t>(cb_id), ReqKind::Write, tag, epoch, bytes);
        });
    if (req_id != 0) {
        inflight_[static_cast<uint64_t>(req_id)] = InflightReq{
            ReqKind::Write,
            tag,
            epoch,
            bytes,
            issue_ns,
            proxy_delay_cycles,
        };
    } else if (cfg_.strict && rt_.log) {
        rt_.log->fatal(
            CALL_INFO, -1,
            "tensor fatal: write issue failed (core=%u addr=0x%llx bytes=%u)\n",
            rt_.core_id, (unsigned long long)addr, bytes);
    }

    return bytes;
}

void TensorWorkload::onMemResponse_(uint64_t req_id, ReqKind kind, MemTag tag, uint64_t epoch, uint32_t bytes) {
    uint64_t issue_ns = 0;
    uint64_t proxy_delay_cycles = 0;
    auto it = inflight_.find(req_id);
    if (it != inflight_.end()) {
        issue_ns = it->second.issue_ns;
        proxy_delay_cycles = it->second.proxy_delay_cycles;
    }
    const uint64_t done_ns = nowNs_();
    uint64_t lat = 0;
    if (done_ns >= issue_ns) {
        lat = done_ns - issue_ns;
    }
    lat = saturatingAddU64_(lat, proxy_delay_cycles);

    if (kind == ReqKind::Read) {
        tensor_mem_read_latency_cycles_total_ = saturatingAddU64_(tensor_mem_read_latency_cycles_total_, lat);
        if (lat > tensor_mem_read_latency_cycles_max_) tensor_mem_read_latency_cycles_max_ = lat;
        tensor_mem_read_latency_samples_total_ = saturatingAddU64_(tensor_mem_read_latency_samples_total_, 1);
    } else {
        tensor_mem_write_latency_cycles_total_ = saturatingAddU64_(tensor_mem_write_latency_cycles_total_, lat);
        if (lat > tensor_mem_write_latency_cycles_max_) tensor_mem_write_latency_cycles_max_ = lat;
        tensor_mem_write_latency_samples_total_ = saturatingAddU64_(tensor_mem_write_latency_samples_total_, 1);
    }

    if (it != inflight_.end()) {
        inflight_.erase(it);
    }
    onMemComplete_(kind, tag, epoch, bytes);
}

void TensorWorkload::onMemComplete_(ReqKind kind, MemTag tag, uint64_t epoch, uint32_t bytes) {
    // Program-mode explicit DMA (M7): update slot progress even when tile model is disabled.
    if (cfg_.exec_mode == "program" && program_m7_enable_) {
        if (program_dma_read_slot_.active && program_dma_read_slot_.epoch == epoch) {
            if (kind == ReqKind::Read && tag == MemTag::ProgramDmaRead) {
                program_dma_read_slot_.done_bytes = std::min<uint64_t>(
                    program_dma_read_slot_.total_bytes,
                    program_dma_read_slot_.done_bytes + static_cast<uint64_t>(bytes));
                if (program_dma_read_slot_.inflight_reqs > 0) {
                    program_dma_read_slot_.inflight_reqs -= 1;
                }
            }
        }
        if (program_dma_write_slot_.active && program_dma_write_slot_.epoch == epoch) {
            if (kind == ReqKind::Write && tag == MemTag::ProgramDmaWrite) {
                program_dma_write_slot_.done_bytes = std::min<uint64_t>(
                    program_dma_write_slot_.total_bytes,
                    program_dma_write_slot_.done_bytes + static_cast<uint64_t>(bytes));
                if (program_dma_write_slot_.inflight_reqs > 0) {
                    program_dma_write_slot_.inflight_reqs -= 1;
                }
            }
        }
    }

    if (!tile_mode_active_) return;

    if (kind == ReqKind::Read) {
        if (tag == MemTag::ReadA) {
            if (tile_cur_.valid && tile_cur_.epoch == epoch) {
                tile_cur_.done_a_bytes += static_cast<uint64_t>(bytes);
                return;
            }
            if (tile_next_.valid && tile_next_.epoch == epoch) {
                tile_next_.done_a_bytes += static_cast<uint64_t>(bytes);
                return;
            }
        } else if (tag == MemTag::ReadB) {
            if (tile_cur_.valid && tile_cur_.epoch == epoch) {
                tile_cur_.done_b_bytes += static_cast<uint64_t>(bytes);
                return;
            }
            if (tile_next_.valid && tile_next_.epoch == epoch) {
                tile_next_.done_b_bytes += static_cast<uint64_t>(bytes);
                return;
            }
        }
        return;
    }

    if (kind == ReqKind::Write && tag == MemTag::WriteC) {
        auto it = tile_writebacks_.find(epoch);
        if (it != tile_writebacks_.end()) {
            it->second.done_bytes += static_cast<uint64_t>(bytes);
        }
        return;
    }
}

uint32_t TensorWorkload::issueMemRead_() {
    if (!cfg_.mem_enable) return 0;
    if (rem_read_bytes_ == 0) return 0;
    const uint32_t want = static_cast<uint32_t>(std::min<uint64_t>(cfg_.mem_req_bytes, rem_read_bytes_));
    const uint32_t issued = issueMemReadTagged_(want, MemTag::Generic, /*epoch*/0);
    if (issued == 0) return 0;
    rem_read_bytes_ -= issued;
    return issued;
}

uint32_t TensorWorkload::issueMemWrite_() {
    if (!cfg_.mem_enable) return 0;
    if (rem_write_bytes_ == 0) return 0;
    const uint32_t want = static_cast<uint32_t>(std::min<uint64_t>(cfg_.mem_req_bytes, rem_write_bytes_));
    const uint32_t issued = issueMemWriteTagged_(want, MemTag::Generic, /*epoch*/0);
    if (issued == 0) return 0;
    rem_write_bytes_ -= issued;
    return issued;
}

bool TensorWorkload::tickCompute_() {
    if (!compute_started_) return false;
    if (rem_compute_cycles_ == 0) return false;

    tensor_compute_cycles_total_ += 1;
    if (rem_compute_math_cycles_ > 0) {
        rem_compute_math_cycles_--;
        rem_compute_cycles_ = (rem_compute_cycles_ > 0) ? (rem_compute_cycles_ - 1) : 0;
        tensor_compute_math_cycles_total_ += 1;

        const uint64_t per = effectivePeakMacsPerCycle_();
        const uint64_t done = (rem_macs_ >= per) ? per : rem_macs_;
        tensor_mac_ops_total_ += done;
        rem_macs_ = (rem_macs_ >= done) ? (rem_macs_ - done) : 0;
        return true;
    }

    if (rem_compute_pipeline_cycles_ > 0) {
        rem_compute_pipeline_cycles_--;
        rem_compute_cycles_ = (rem_compute_cycles_ > 0) ? (rem_compute_cycles_ - 1) : 0;
        tensor_compute_pipeline_cycles_total_ += 1;
        return true;
    }

    rem_compute_cycles_ = 0;
    return false;
}

bool TensorWorkload::collectivePendingActive_() const {
    if (!collective_pending_active_) return false;
    return collective_pending_sent_bytes_ < collective_pending_total_bytes_;
}

uint32_t TensorWorkload::collectiveRingParticipantCount_() const {
    const uint32_t total_nodes = (rt_.total_nodes > 0) ? static_cast<uint32_t>(rt_.total_nodes) : 1u;
    return std::max<uint32_t>(total_nodes, 1u);
}

uint32_t TensorWorkload::collectiveRingStepsPerChunk_() const {
    const uint32_t participants = collectiveRingParticipantCount_();
    const uint32_t hop = (participants > 1) ? (participants - 1u) : 1u;
    if (cfg_.collective_type == "allreduce") {
        return hop * 2u;
    }
    if (cfg_.collective_type == "allgather" || cfg_.collective_type == "reducescatter") {
        return hop;
    }
    return hop;
}

uint32_t TensorWorkload::collectiveRingChunkPayloadBytes_(uint32_t chunk_index) const {
    const uint32_t base_chunk = (cfg_.collective_chunk_bytes > 0)
                                    ? cfg_.collective_chunk_bytes
                                    : std::max<uint32_t>(cfg_.collective_packet_bytes, 8u);
    if (base_chunk == 0) return 0;
    if (collective_ring_chunks_total_ == 0) return base_chunk;
    if (chunk_index + 1u < collective_ring_chunks_total_) return base_chunk;

    const uint64_t total = (collective_active_bytes_ != 0) ? collective_active_bytes_ : cfg_.collective_bytes;
    const uint64_t rem = (base_chunk > 0) ? (total % static_cast<uint64_t>(base_chunk)) : 0ull;
    if (rem == 0ull) return base_chunk;
    return static_cast<uint32_t>(rem);
}

uint32_t TensorWorkload::collectiveRingStepPayloadBytes_(uint32_t chunk_index, uint32_t step_in_chunk) const {
    const uint32_t chunk_payload = collectiveRingChunkPayloadBytes_(chunk_index);
    if (chunk_payload == 0) return 0;

    if (collective_2d_active_) {
        // 2D staged allreduce: split chunk payload along X (row), then split the kept row-segment along Y (col).
        const uint32_t dim_x = std::max<uint32_t>(collective_2d_dim_x_ ? collective_2d_dim_x_ : 1u, 1u);
        const uint32_t dim_y = std::max<uint32_t>(collective_2d_dim_y_ ? collective_2d_dim_y_ : 1u, 1u);
        const uint32_t row_hop = (collective_2d_row_hop_ > 0) ? collective_2d_row_hop_ : 1u;
        const uint32_t col_hop = (collective_2d_col_hop_ > 0) ? collective_2d_col_hop_ : 1u;

        const uint32_t row_base = chunk_payload / dim_x;
        const uint32_t row_rem = chunk_payload % dim_x;
        const uint32_t row_last_id = (dim_x > 0) ? (dim_x - 1u) : 0u;
        const uint32_t row_last_bytes = row_base + ((row_last_id < row_rem) ? 1u : 0u);

        const uint32_t col_base = (dim_y > 0) ? (row_last_bytes / dim_y) : row_last_bytes;
        const uint32_t col_rem = (dim_y > 0) ? (row_last_bytes % dim_y) : 0u;
        const uint32_t col_last_id = (dim_y > 0) ? (dim_y - 1u) : 0u;
        const uint32_t col_last_bytes = col_base + ((col_last_id < col_rem) ? 1u : 0u);

        const Collective2dStage stage = collective2dStageForStep_(step_in_chunk);
        if (stage == Collective2dStage::RowRS || stage == Collective2dStage::RowAG) {
            uint32_t local_step = step_in_chunk;
            if (stage == Collective2dStage::RowAG) {
                local_step = (step_in_chunk >= (row_hop + 2u * col_hop)) ? (step_in_chunk - (row_hop + 2u * col_hop)) : 0u;
            }
            const uint32_t seg_id = (row_hop > 0) ? (local_step % row_hop) : 0u;
            return row_base + ((seg_id < row_rem) ? 1u : 0u);
        }

        // ColRS / ColAG
        uint32_t local_step = 0;
        if (stage == Collective2dStage::ColRS) {
            local_step = (step_in_chunk >= row_hop) ? (step_in_chunk - row_hop) : 0u;
        } else {
            // ColAG
            local_step = (step_in_chunk >= (row_hop + col_hop)) ? (step_in_chunk - (row_hop + col_hop)) : 0u;
        }
        const uint32_t seg_id = (col_hop > 0) ? (local_step % col_hop) : 0u;
        (void)col_last_bytes; // keep for symmetry / documentation; excluded by seg_id range when dim_y>1.
        return col_base + ((seg_id < col_rem) ? 1u : 0u);
    }

    // Ring-like chunked collective: split each chunk into P segments and send one segment per step.
    const uint32_t participants = collectiveRingParticipantCount_();
    const uint32_t parts = std::max<uint32_t>(participants, 1u);
    const uint32_t base = chunk_payload / parts;
    const uint32_t rem = chunk_payload % parts;
    const uint32_t hop = (parts > 1u) ? (parts - 1u) : 1u;
    const uint32_t seg_id = (hop > 0) ? (step_in_chunk % hop) : 0u;
    return base + ((seg_id < rem) ? 1u : 0u);
}

uint32_t TensorWorkload::collectiveRingNextDestNode_() const {
    const uint32_t total_nodes = (rt_.total_nodes > 0) ? static_cast<uint32_t>(rt_.total_nodes) : 1u;
    if (total_nodes <= 1u) return static_cast<uint32_t>(rt_.node_id);

    if ((cfg_.collective_pattern == "mesh_x" || cfg_.collective_pattern == "mesh_xy") && total_nodes > 1u) {
        const uint32_t mesh_size = static_cast<uint32_t>(std::sqrt(static_cast<double>(total_nodes)));
        if (mesh_size > 0 && mesh_size * mesh_size == total_nodes) {
            const uint32_t node_x = static_cast<uint32_t>(rt_.node_id) % mesh_size;
            const uint32_t node_y = static_cast<uint32_t>(rt_.node_id) / mesh_size;
            const uint32_t east = node_y * mesh_size + ((node_x + 1u) % mesh_size);
            if (cfg_.collective_pattern == "mesh_xy" && (collective_ring_step_index_ & 1u)) {
                return ((node_y + 1u) % mesh_size) * mesh_size + node_x;
            }
            return east;
        }
    }
    return (static_cast<uint32_t>(rt_.node_id) + 1u) % total_nodes;
}

TensorWorkload::Collective2dStage TensorWorkload::collective2dStageForStep_(uint32_t step_in_chunk) const {
    const uint32_t row_hop = (collective_2d_row_hop_ > 0) ? collective_2d_row_hop_ : 1u;
    const uint32_t col_hop = (collective_2d_col_hop_ > 0) ? collective_2d_col_hop_ : 1u;
    if (step_in_chunk < row_hop) return Collective2dStage::RowRS;
    if (step_in_chunk < row_hop + col_hop) return Collective2dStage::ColRS;
    if (step_in_chunk < row_hop + 2u * col_hop) return Collective2dStage::ColAG;
    return Collective2dStage::RowAG;
}

uint32_t TensorWorkload::collective2dNextDestNodeForStep_(uint32_t step_in_chunk) const {
    const uint32_t total_nodes = (rt_.total_nodes > 0) ? static_cast<uint32_t>(rt_.total_nodes) : 1u;
    const uint32_t node = static_cast<uint32_t>(rt_.node_id);
    if (total_nodes <= 1u) return node;

    const uint32_t dim_x = (collective_2d_dim_x_ > 0) ? collective_2d_dim_x_ : total_nodes;
    const uint32_t dim_y = (collective_2d_dim_y_ > 0) ? collective_2d_dim_y_ : 1u;
    if (dim_x == 0u || dim_y == 0u) return (node + 1u) % total_nodes;
    const uint64_t prod = static_cast<uint64_t>(dim_x) * static_cast<uint64_t>(dim_y);
    if (prod != static_cast<uint64_t>(total_nodes)) {
        return (node + 1u) % total_nodes;
    }

    uint32_t x = 0;
    uint32_t y = 0;
    if (cfg_.collective_2d_row_major) {
        x = node % dim_x;
        y = node / dim_x;
    } else {
        y = node % dim_y;
        x = node / dim_y;
    }
    auto to_node = [&](uint32_t xx, uint32_t yy) -> uint32_t {
        if (cfg_.collective_2d_row_major) return yy * dim_x + xx;
        return xx * dim_y + yy;
    };

    const Collective2dStage stage = collective2dStageForStep_(step_in_chunk);
    if (stage == Collective2dStage::RowRS || stage == Collective2dStage::RowAG) {
        const uint32_t nx = (x + 1u) % dim_x;
        return to_node(nx, y);
    }
    const uint32_t ny = (y + 1u) % dim_y;
    return to_node(x, ny);
}

uint32_t TensorWorkload::selectUbBank_(uint64_t tag_seed) {
    const uint32_t banks = std::max<uint32_t>(cfg_.ub_bank_count, 1u);
    if (banks <= 1u) return 0u;

    if (cfg_.ub_bank_select_policy == "rr") {
        const uint32_t bank = onchip_ub_bank_rr_ % banks;
        onchip_ub_bank_rr_ = (bank + 1u) % banks;
        return bank;
    }
    if (cfg_.ub_bank_select_policy == "hash") {
        uint64_t x = tag_seed ^ (static_cast<uint64_t>(rt_.node_id) << 32) ^
                     (static_cast<uint64_t>(rt_.core_id) << 16) ^ cfg_.seed_base;
        return static_cast<uint32_t>(splitmix64_next_(x) % static_cast<uint64_t>(banks));
    }

    const uint64_t gran = std::max<uint64_t>(cfg_.mem_req_bytes, 1u);
    return static_cast<uint32_t>((tag_seed / gran) % static_cast<uint64_t>(banks));
}

uint32_t TensorWorkload::selectWeightBank_(uint64_t tag_seed) {
    const uint32_t banks = std::max<uint32_t>(cfg_.ub_bank_count, 1u);
    if (banks <= 1u) return 0u;

    if (cfg_.ub_bank_select_policy == "rr") {
        const uint32_t bank = onchip_weight_bank_rr_ % banks;
        onchip_weight_bank_rr_ = (bank + 1u) % banks;
        return bank;
    }
    if (cfg_.ub_bank_select_policy == "hash") {
        uint64_t x = tag_seed ^ (static_cast<uint64_t>(rt_.node_id) << 32) ^
                     (static_cast<uint64_t>(rt_.core_id) << 16) ^ cfg_.seed_base;
        return static_cast<uint32_t>(splitmix64_next_(x) % static_cast<uint64_t>(banks));
    }

    const uint64_t gran = std::max<uint64_t>(cfg_.mem_req_bytes, 1u);
    return static_cast<uint32_t>((tag_seed / gran) % static_cast<uint64_t>(banks));
}

uint32_t TensorWorkload::selectAccBank_(uint64_t tag_seed) {
    const uint32_t banks = std::max<uint32_t>(cfg_.acc_bank_count, 1u);
    if (banks <= 1u) return 0u;

    if (cfg_.acc_bank_select_policy == "rr") {
        const uint32_t bank = onchip_acc_bank_rr_ % banks;
        onchip_acc_bank_rr_ = (bank + 1u) % banks;
        return bank;
    }
    if (cfg_.acc_bank_select_policy == "hash") {
        uint64_t x = tag_seed ^ (static_cast<uint64_t>(tile_seg_done_) << 20) ^
                     (static_cast<uint64_t>(rt_.node_id) << 32) ^
                     (static_cast<uint64_t>(rt_.core_id) << 16) ^ cfg_.seed_base;
        return static_cast<uint32_t>(splitmix64_next_(x) % static_cast<uint64_t>(banks));
    }

    const uint64_t gran = std::max<uint64_t>(tile_c_bytes_, 1ull);
    return static_cast<uint32_t>((tag_seed / gran) % static_cast<uint64_t>(banks));
}

void TensorWorkload::updateBankQueueOccupancyMax_() {
    uint64_t max_occ = 0;
    for (uint32_t v : onchip_ub_bank_queue_occupancy_) {
        if (static_cast<uint64_t>(v) > max_occ) max_occ = static_cast<uint64_t>(v);
    }
    for (uint32_t v : onchip_weight_bank_queue_occupancy_) {
        if (static_cast<uint64_t>(v) > max_occ) max_occ = static_cast<uint64_t>(v);
    }
    for (uint32_t v : onchip_acc_bank_queue_occupancy_) {
        if (static_cast<uint64_t>(v) > max_occ) max_occ = static_cast<uint64_t>(v);
    }
    if (max_occ > tensor_bank_queue_occupancy_max_) {
        tensor_bank_queue_occupancy_max_ = max_occ;
    }
}

void TensorWorkload::resetOnchipCycleState_(uint64_t now_cycle) {
    if (onchip_cycle_tag_ == now_cycle) return;
    onchip_cycle_tag_ = now_cycle;
    onchip_ub_read_ports_used_ = 0;
    onchip_ub_write_ports_used_ = 0;
    onchip_acc_read_ports_used_ = 0;
    onchip_acc_write_ports_used_ = 0;
    if (cfg_.onchip_bank_model_enable) {
        for (uint32_t& v : onchip_ub_bank_queue_occupancy_) {
            if (v > 0) v -= 1;
        }
        for (uint32_t& v : onchip_weight_bank_queue_occupancy_) {
            if (v > 0) v -= 1;
        }
        for (uint32_t& v : onchip_acc_bank_queue_occupancy_) {
            if (v > 0) v -= 1;
        }
    }
}

bool TensorWorkload::acquireOnchipReadPorts_(uint32_t ub_ports_needed, uint32_t acc_ports_needed) {
    if (!cfg_.onchip_model_enable) return true;
    const uint32_t ub_limit = cfg_.ub_read_ports;
    const uint32_t acc_limit = cfg_.acc_read_ports;

    if (ub_limit > 0 && onchip_ub_read_ports_used_ + ub_ports_needed > ub_limit) return false;
    if (acc_limit > 0 && onchip_acc_read_ports_used_ + acc_ports_needed > acc_limit) return false;
    onchip_ub_read_ports_used_ += ub_ports_needed;
    onchip_acc_read_ports_used_ += acc_ports_needed;
    return true;
}

bool TensorWorkload::acquireOnchipWritePorts_(uint32_t ub_ports_needed, uint32_t acc_ports_needed) {
    if (!cfg_.onchip_model_enable) return true;
    const uint32_t ub_limit = cfg_.ub_write_ports;
    const uint32_t acc_limit = cfg_.acc_write_ports;

    if (ub_limit > 0 && onchip_ub_write_ports_used_ + ub_ports_needed > ub_limit) return false;
    if (acc_limit > 0 && onchip_acc_write_ports_used_ + acc_ports_needed > acc_limit) return false;
    onchip_ub_write_ports_used_ += ub_ports_needed;
    onchip_acc_write_ports_used_ += acc_ports_needed;
    return true;
}

bool TensorWorkload::reserveUbBytes_(uint64_t bytes,
                                     uint64_t& spill_budget,
                                     bool& spilled,
                                     bool& spill_budget_blocked,
                                     bool& bank_conflict_blocked,
                                     std::vector<std::pair<uint32_t, uint64_t>>* bank_allocs) {
    spilled = false;
    spill_budget_blocked = false;
    bank_conflict_blocked = false;
    if (bytes == 0) return true;
    if (!cfg_.onchip_model_enable || cfg_.ub_bytes == 0) return true;

    auto spill_or_fail = [&](bool bank_conflict) -> bool {
        if (!cfg_.spill_enable) {
            bank_conflict_blocked = bank_conflict;
            return false;
        }
        const bool spill_budget_capped =
            cfg_.spill_share_noc_budget &&
            cfg_.noc_bandwidth_bytes_per_cycle > 0 &&
            spill_budget != std::numeric_limits<uint64_t>::max();
        if (spill_budget_capped && spill_budget < bytes) {
            spill_budget_blocked = true;
            return false;
        }

        spilled = true;
        tensor_spill_bytes_total_ += bytes;
        tensor_spill_pkts_total_ += ceilDivU64_(bytes, std::max<uint64_t>(cfg_.spill_packet_bytes, 8ull));
        if (spill_budget_capped) {
            spill_budget -= bytes;
        }
        return true;
    };

    if (!cfg_.onchip_bank_model_enable || onchip_ub_bank_occupancy_bytes_.empty()) {
        if (onchip_ub_occupancy_bytes_ + bytes <= cfg_.ub_bytes) {
            onchip_ub_occupancy_bytes_ += bytes;
            return true;
        }
        return spill_or_fail(false);
    }

    const uint32_t bank = selectUbBank_(onchip_ub_occupancy_bytes_ + bytes + tensor_mem_reads_issued_total_);
    if (bank >= onchip_ub_bank_occupancy_bytes_.size() || bank >= onchip_ub_bank_queue_occupancy_.size()) {
        return spill_or_fail(false);
    }

    bool queue_marked = false;
    if (cfg_.ub_bank_conflict_mode == "queue") {
        if (onchip_ub_bank_queue_occupancy_[bank] >= cfg_.bank_queue_depth) {
            bank_conflict_blocked = true;
            return false;
        }
        onchip_ub_bank_queue_occupancy_[bank] += 1;
        queue_marked = true;
        updateBankQueueOccupancyMax_();
    } else {
        if (onchip_ub_bank_queue_occupancy_[bank] > 0) {
            bank_conflict_blocked = true;
            return false;
        }
        onchip_ub_bank_queue_occupancy_[bank] = 1;
        queue_marked = true;
        updateBankQueueOccupancyMax_();
    }

    const uint64_t bank_cap = (cfg_.ub_bank_bytes > 0)
                                  ? cfg_.ub_bank_bytes
                                  : ceilDivU64_(cfg_.ub_bytes, static_cast<uint64_t>(std::max<uint32_t>(cfg_.ub_bank_count, 1u)));
    const bool global_fit = onchip_ub_occupancy_bytes_ + bytes <= cfg_.ub_bytes;
    const bool bank_fit = onchip_ub_bank_occupancy_bytes_[bank] + bytes <= bank_cap;
    if (global_fit && bank_fit) {
        onchip_ub_occupancy_bytes_ += bytes;
        onchip_ub_bank_occupancy_bytes_[bank] += bytes;
        if (bank_allocs) bank_allocs->emplace_back(bank, bytes);
        return true;
    }

    if (queue_marked && onchip_ub_bank_queue_occupancy_[bank] > 0) {
        onchip_ub_bank_queue_occupancy_[bank] -= 1;
    }
    return spill_or_fail(!bank_fit);
}

bool TensorWorkload::reserveWeightBytes_(uint64_t bytes,
                                         uint64_t& spill_budget,
                                         bool& spilled,
                                         bool& spill_budget_blocked,
                                         bool& bank_conflict_blocked,
                                         std::vector<std::pair<uint32_t, uint64_t>>* bank_allocs) {
    spilled = false;
    spill_budget_blocked = false;
    bank_conflict_blocked = false;
    if (bytes == 0) return true;
    if (!cfg_.onchip_model_enable || cfg_.weight_bytes == 0) return true;

    auto spill_or_fail = [&](bool bank_conflict) -> bool {
        if (!cfg_.spill_enable) {
            bank_conflict_blocked = bank_conflict;
            return false;
        }
        const bool spill_budget_capped =
            cfg_.spill_share_noc_budget &&
            cfg_.noc_bandwidth_bytes_per_cycle > 0 &&
            spill_budget != std::numeric_limits<uint64_t>::max();
        if (spill_budget_capped && spill_budget < bytes) {
            spill_budget_blocked = true;
            return false;
        }

        spilled = true;
        tensor_spill_bytes_total_ += bytes;
        tensor_spill_pkts_total_ += ceilDivU64_(bytes, std::max<uint64_t>(cfg_.spill_packet_bytes, 8ull));
        if (spill_budget_capped) {
            spill_budget -= bytes;
        }
        return true;
    };

    if (!cfg_.onchip_bank_model_enable || onchip_weight_bank_occupancy_bytes_.empty()) {
        if (onchip_weight_occupancy_bytes_ + bytes <= cfg_.weight_bytes) {
            onchip_weight_occupancy_bytes_ += bytes;
            if (onchip_weight_occupancy_bytes_ > tensor_onchip_weight_occupancy_bytes_max_) {
                tensor_onchip_weight_occupancy_bytes_max_ = onchip_weight_occupancy_bytes_;
            }
            return true;
        }
        return spill_or_fail(false);
    }

    const uint32_t bank = selectWeightBank_(onchip_weight_occupancy_bytes_ + bytes + tensor_mem_reads_issued_total_);
    if (bank >= onchip_weight_bank_occupancy_bytes_.size() || bank >= onchip_weight_bank_queue_occupancy_.size()) {
        return spill_or_fail(false);
    }

    bool queue_marked = false;
    if (cfg_.ub_bank_conflict_mode == "queue") {
        if (onchip_weight_bank_queue_occupancy_[bank] >= cfg_.bank_queue_depth) {
            bank_conflict_blocked = true;
            return false;
        }
        onchip_weight_bank_queue_occupancy_[bank] += 1;
        queue_marked = true;
        updateBankQueueOccupancyMax_();
    } else {
        if (onchip_weight_bank_queue_occupancy_[bank] > 0) {
            bank_conflict_blocked = true;
            return false;
        }
        onchip_weight_bank_queue_occupancy_[bank] = 1;
        queue_marked = true;
        updateBankQueueOccupancyMax_();
    }

    const uint64_t bank_cap = (cfg_.ub_bank_bytes > 0)
                                  ? cfg_.ub_bank_bytes
                                  : ceilDivU64_(cfg_.weight_bytes, static_cast<uint64_t>(std::max<uint32_t>(cfg_.ub_bank_count, 1u)));
    const bool global_fit = onchip_weight_occupancy_bytes_ + bytes <= cfg_.weight_bytes;
    const bool bank_fit = onchip_weight_bank_occupancy_bytes_[bank] + bytes <= bank_cap;
    if (global_fit && bank_fit) {
        onchip_weight_occupancy_bytes_ += bytes;
        onchip_weight_bank_occupancy_bytes_[bank] += bytes;
        if (onchip_weight_occupancy_bytes_ > tensor_onchip_weight_occupancy_bytes_max_) {
            tensor_onchip_weight_occupancy_bytes_max_ = onchip_weight_occupancy_bytes_;
        }
        if (onchip_weight_bank_occupancy_bytes_[bank] > tensor_onchip_weight_bank_occupancy_bytes_max_) {
            tensor_onchip_weight_bank_occupancy_bytes_max_ = onchip_weight_bank_occupancy_bytes_[bank];
        }
        if (bank_allocs) bank_allocs->emplace_back(bank, bytes);
        return true;
    }

    if (queue_marked && onchip_weight_bank_queue_occupancy_[bank] > 0) {
        onchip_weight_bank_queue_occupancy_[bank] -= 1;
    }
    return spill_or_fail(!bank_fit);
}

void TensorWorkload::releaseUbBytes_(uint64_t bytes) {
    if (!cfg_.onchip_model_enable || cfg_.ub_bytes == 0 || bytes == 0) return;
    onchip_ub_occupancy_bytes_ = (onchip_ub_occupancy_bytes_ >= bytes) ? (onchip_ub_occupancy_bytes_ - bytes) : 0;
}

void TensorWorkload::releaseUbBankAllocs_(std::vector<std::pair<uint32_t, uint64_t>>& bank_allocs) {
    if (!cfg_.onchip_model_enable || cfg_.ub_bytes == 0) {
        bank_allocs.clear();
        return;
    }
    for (const auto& alloc : bank_allocs) {
        const uint32_t bank = alloc.first;
        const uint64_t bytes = alloc.second;
        if (bytes == 0) continue;
        onchip_ub_occupancy_bytes_ = (onchip_ub_occupancy_bytes_ >= bytes) ? (onchip_ub_occupancy_bytes_ - bytes) : 0;
        if (bank < onchip_ub_bank_occupancy_bytes_.size()) {
            uint64_t& occ = onchip_ub_bank_occupancy_bytes_[bank];
            occ = (occ >= bytes) ? (occ - bytes) : 0;
        }
    }
    bank_allocs.clear();
}

void TensorWorkload::releaseWeightBytes_(uint64_t bytes) {
    if (!cfg_.onchip_model_enable || cfg_.weight_bytes == 0 || bytes == 0) return;
    onchip_weight_occupancy_bytes_ =
        (onchip_weight_occupancy_bytes_ >= bytes) ? (onchip_weight_occupancy_bytes_ - bytes) : 0;
}

void TensorWorkload::releaseWeightBankAllocs_(std::vector<std::pair<uint32_t, uint64_t>>& bank_allocs) {
    if (!cfg_.onchip_model_enable || cfg_.weight_bytes == 0) {
        bank_allocs.clear();
        return;
    }
    for (const auto& alloc : bank_allocs) {
        const uint32_t bank = alloc.first;
        const uint64_t bytes = alloc.second;
        if (bytes == 0) continue;
        onchip_weight_occupancy_bytes_ =
            (onchip_weight_occupancy_bytes_ >= bytes) ? (onchip_weight_occupancy_bytes_ - bytes) : 0;
        if (bank < onchip_weight_bank_occupancy_bytes_.size()) {
            uint64_t& occ = onchip_weight_bank_occupancy_bytes_[bank];
            occ = (occ >= bytes) ? (occ - bytes) : 0;
        }
    }
    bank_allocs.clear();
}

bool TensorWorkload::reserveAccTile_(uint32_t mi,
                                     uint32_t ni,
                                     uint64_t& spill_budget,
                                     bool& spilled,
                                     bool& spill_budget_blocked,
                                     bool& bank_conflict_blocked) {
    spilled = false;
    spill_budget_blocked = false;
    bank_conflict_blocked = false;
    if (!cfg_.onchip_model_enable || cfg_.acc_bytes == 0 || tile_c_bytes_ == 0) {
        return true;
    }

    const uint64_t key = (static_cast<uint64_t>(mi) << 32) | static_cast<uint64_t>(ni);
    if (acc_reserved_tiles_.find(key) != acc_reserved_tiles_.end()) {
        return true;
    }

    auto spill_or_fail = [&](bool bank_conflict) -> bool {
        if (!cfg_.spill_enable) {
            bank_conflict_blocked = bank_conflict;
            return false;
        }
        const bool spill_budget_capped =
            cfg_.spill_share_noc_budget &&
            cfg_.noc_bandwidth_bytes_per_cycle > 0 &&
            spill_budget != std::numeric_limits<uint64_t>::max();
        if (spill_budget_capped && spill_budget < tile_c_bytes_) {
            spill_budget_blocked = true;
            return false;
        }

        spilled = true;
        tensor_spill_bytes_total_ += tile_c_bytes_;
        tensor_spill_pkts_total_ += ceilDivU64_(tile_c_bytes_, std::max<uint64_t>(cfg_.spill_packet_bytes, 8ull));
        if (spill_budget_capped) {
            spill_budget -= tile_c_bytes_;
        }
        return true;
    };

    if (!cfg_.onchip_bank_model_enable || onchip_acc_bank_occupancy_bytes_.empty()) {
        if (onchip_acc_occupancy_bytes_ + tile_c_bytes_ <= cfg_.acc_bytes) {
            onchip_acc_occupancy_bytes_ += tile_c_bytes_;
            acc_reserved_tiles_.emplace(key, AccTileAlloc{tile_c_bytes_, 0u, 0u});
            return true;
        }
        return spill_or_fail(false);
    }

    const uint32_t bank = selectAccBank_(key);
    if (bank >= onchip_acc_bank_occupancy_bytes_.size() || bank >= onchip_acc_bank_queue_occupancy_.size()) {
        return spill_or_fail(false);
    }

    bool queue_marked = false;
    if (cfg_.acc_bank_conflict_mode == "queue") {
        if (onchip_acc_bank_queue_occupancy_[bank] >= cfg_.bank_queue_depth) {
            bank_conflict_blocked = true;
            return false;
        }
        onchip_acc_bank_queue_occupancy_[bank] += 1;
        queue_marked = true;
        updateBankQueueOccupancyMax_();
    } else {
        if (onchip_acc_bank_queue_occupancy_[bank] > 0) {
            bank_conflict_blocked = true;
            return false;
        }
        onchip_acc_bank_queue_occupancy_[bank] = 1;
        queue_marked = true;
        updateBankQueueOccupancyMax_();
    }

    const uint64_t bank_cap = (cfg_.acc_bank_bytes > 0)
                                  ? cfg_.acc_bank_bytes
                                  : ceilDivU64_(cfg_.acc_bytes, static_cast<uint64_t>(std::max<uint32_t>(cfg_.acc_bank_count, 1u)));
    const bool global_fit = onchip_acc_occupancy_bytes_ + tile_c_bytes_ <= cfg_.acc_bytes;
    const bool bank_fit = onchip_acc_bank_occupancy_bytes_[bank] + tile_c_bytes_ <= bank_cap;
    if (global_fit && bank_fit) {
        onchip_acc_occupancy_bytes_ += tile_c_bytes_;
        onchip_acc_bank_occupancy_bytes_[bank] += tile_c_bytes_;
        acc_reserved_tiles_.emplace(key, AccTileAlloc{tile_c_bytes_, bank, queue_marked ? 1u : 0u});
        return true;
    }

    if (queue_marked && onchip_acc_bank_queue_occupancy_[bank] > 0) {
        onchip_acc_bank_queue_occupancy_[bank] -= 1;
    }
    return spill_or_fail(!bank_fit);
}

void TensorWorkload::releaseAccTile_(uint32_t mi, uint32_t ni) {
    if (!cfg_.onchip_model_enable || cfg_.acc_bytes == 0) return;
    const uint64_t key = (static_cast<uint64_t>(mi) << 32) | static_cast<uint64_t>(ni);
    auto it = acc_reserved_tiles_.find(key);
    if (it == acc_reserved_tiles_.end()) return;
    const AccTileAlloc alloc = it->second;
    const uint64_t bytes = alloc.bytes;
    onchip_acc_occupancy_bytes_ = (onchip_acc_occupancy_bytes_ >= bytes) ? (onchip_acc_occupancy_bytes_ - bytes) : 0;
    if (alloc.bank < onchip_acc_bank_occupancy_bytes_.size()) {
        uint64_t& occ = onchip_acc_bank_occupancy_bytes_[alloc.bank];
        occ = (occ >= bytes) ? (occ - bytes) : 0;
    }
    acc_reserved_tiles_.erase(it);
}

bool TensorWorkload::collectiveUseEventCreditReturn_() const {
    return cfg_.collective_credit_enable &&
           cfg_.collective_algo == "ring_chunked" &&
           cfg_.collective_credit_return_mode == "event_on_recv";
}

void TensorWorkload::onCollectiveCreditIssue_(uint32_t seq,
                                              uint32_t chunk,
                                              uint32_t step,
                                              uint32_t dst_node,
                                              uint16_t dst_core,
                                              uint64_t now_cycle) {
    if (!cfg_.collective_credit_enable) return;
    collective_credit_inflight_chunks_ = saturatingAddU64_(collective_credit_inflight_chunks_, 1ull);
    if (collective_credit_inflight_chunks_ > tensor_collective_inflight_chunks_max_) {
        tensor_collective_inflight_chunks_max_ = collective_credit_inflight_chunks_;
    }

    if (!collectiveUseEventCreditReturn_()) return;
    const CollectiveCreditKey key{seq, chunk, step, dst_node, dst_core};
    auto& state = collective_credit_outstanding_[key];
    state.outstanding = saturatingAddU64_(state.outstanding, 1ull);
    state.issue_cycles.push_back(now_cycle);
}

void TensorWorkload::onCollectiveCreditReturn_(uint32_t seq,
                                               uint32_t chunk,
                                               uint32_t step,
                                               uint32_t credits,
                                               uint32_t src_node,
                                               uint16_t src_core,
                                               uint64_t now_cycle) {
    if (!cfg_.collective_credit_enable) return;
    if (credits == 0) return;

    const CollectiveCreditKey key{seq, chunk, step, src_node, src_core};
    auto it = collective_credit_outstanding_.find(key);
    if (it == collective_credit_outstanding_.end() || it->second.outstanding == 0) {
        if (collective_credit_return_seen_.find(key) != collective_credit_return_seen_.end()) {
            tensor_collective_credit_return_dup_total_ += static_cast<uint64_t>(credits);
        } else {
            tensor_collective_credit_return_orphan_total_ += static_cast<uint64_t>(credits);
        }
        collective_credit_return_seen_.insert(key);
        return;
    }

    collective_credit_return_seen_.insert(key);
    uint64_t applied = 0;
    const uint64_t req = static_cast<uint64_t>(credits);
    while (applied < req && it->second.outstanding > 0) {
        it->second.outstanding -= 1;
        applied += 1;
        if (!it->second.issue_cycles.empty()) {
            const uint64_t issue_cycle = it->second.issue_cycles.front();
            it->second.issue_cycles.pop_front();
            const uint64_t latency = (now_cycle >= issue_cycle) ? (now_cycle - issue_cycle) : 0ull;
            tensor_collective_credit_return_latency_cycles_total_ =
                saturatingAddU64_(tensor_collective_credit_return_latency_cycles_total_, latency);
            if (latency > tensor_collective_credit_return_latency_cycles_max_) {
                tensor_collective_credit_return_latency_cycles_max_ = latency;
            }
        }
    }

    if (it->second.outstanding == 0) {
        it->second.issue_cycles.clear();
        collective_credit_outstanding_.erase(it);
        if (collective_credit_outstanding_.empty()) {
            collective_credit_return_seen_.clear();
        }
    }

    if (applied < req) {
        const uint64_t extra = req - applied;
        tensor_collective_credit_return_orphan_total_ = saturatingAddU64_(
            tensor_collective_credit_return_orphan_total_, extra);
    }

    if (collective_credit_inflight_chunks_ >= applied) {
        collective_credit_inflight_chunks_ -= applied;
    } else {
        collective_credit_inflight_chunks_ = 0;
    }
}

void TensorWorkload::maybeEmitCollectiveCreditReturn_(const NocPacketEvent* packet, uint64_t now_cycle) {
    (void)now_cycle;
    if (!packet) return;
    if (!collectiveUseEventCreditReturn_()) return;
    if (!has_collective_magic_(packet->payload)) return;
    if (packet->payload.size() < 16) return;

    const uint32_t seq = read_u32_le_(packet->payload, 4);
    const uint32_t chunk = read_u32_le_(packet->payload, 8);
    const uint32_t step = read_u32_le_(packet->payload, 12);
    const uint32_t dst_node = packet->src_node;
    const uint16_t dst_core = packet->src_endpoint;
    const uint32_t credits = 1u;

    const CollectiveCreditKey key{seq, chunk, step, dst_node, dst_core};
    auto it = collective_credit_return_pending_credits_.find(key);
    if (it == collective_credit_return_pending_credits_.end()) {
        collective_credit_return_pending_queue_.push_back(key);
        collective_credit_return_pending_credits_.emplace(key, static_cast<uint64_t>(credits));
    } else {
        it->second = saturatingAddU64_(it->second, static_cast<uint64_t>(credits));
    }
}

uint64_t TensorWorkload::emitCollectiveCreditReturnTraffic_(uint64_t now_cycle,
                                                            uint64_t noc_budget_bytes,
                                                            bool& budget_blocked) {
    budget_blocked = false;
    if (!collectiveUseEventCreditReturn_()) return 0;
    if (collective_credit_return_pending_queue_.empty()) return 0;

    constexpr uint64_t kPacketBytes = 20ull;
    const bool uncapped = (noc_budget_bytes == std::numeric_limits<uint64_t>::max());
    uint64_t budget = noc_budget_bytes;
    uint64_t sent_bytes = 0;

    size_t rounds = collective_credit_return_pending_queue_.size();
    while (rounds > 0 && !collective_credit_return_pending_queue_.empty()) {
        rounds -= 1;
        const CollectiveCreditKey key = collective_credit_return_pending_queue_.front();
        collective_credit_return_pending_queue_.pop_front();

        auto it = collective_credit_return_pending_credits_.find(key);
        if (it == collective_credit_return_pending_credits_.end() || it->second == 0) {
            if (it != collective_credit_return_pending_credits_.end()) {
                collective_credit_return_pending_credits_.erase(it);
            }
            continue;
        }

        if (!uncapped && budget < kPacketBytes) {
            budget_blocked = true;
            collective_credit_return_pending_queue_.push_front(key);
            break;
        }

        const uint32_t credits = static_cast<uint32_t>(
            std::min<uint64_t>(it->second, static_cast<uint64_t>(std::numeric_limits<uint32_t>::max())));
        if (credits == 0) {
            collective_credit_return_pending_credits_.erase(it);
            continue;
        }

        const uint32_t dst_node = key.peer_node;
        const uint16_t dst_core = key.peer_core;
        const bool self_is_dst =
            (dst_node == static_cast<uint32_t>(rt_.node_id) && dst_core == static_cast<uint16_t>(rt_.core_id));

        if (self_is_dst) {
            tensor_collective_credit_return_pkts_sent_total_ += 1;
            tensor_collective_credit_return_pkts_recv_total_ += 1;
            onCollectiveCreditReturn_(key.seq, key.chunk, key.step, credits, dst_node, dst_core, now_cycle);
        } else {
            if (!rt_.noc) {
                budget_blocked = true;
                collective_credit_return_pending_queue_.push_front(key);
                break;
            }

            std::vector<uint8_t> payload(static_cast<size_t>(kPacketBytes), 0);
            payload[0] = static_cast<uint8_t>('T');
            payload[1] = static_cast<uint8_t>('C');
            payload[2] = static_cast<uint8_t>('C');
            payload[3] = static_cast<uint8_t>('R');
            write_u32_le_(payload, 4, key.seq);
            write_u32_le_(payload, 8, key.chunk);
            write_u32_le_(payload, 12, key.step);
            write_u32_le_(payload, 16, credits);

            auto* pkt = new NocPacketEvent(rt_.node_id,
                                           dst_node,
                                           static_cast<uint16_t>(rt_.core_id),
                                           dst_core,
                                           NocPacketKind::Control,
                                           now_cycle);
            pkt->payload = payload;

            tensor_pkt_sent_total_ += 1;
            tensor_pkt_bytes_sent_total_ += static_cast<uint64_t>(pkt->payload.size());
            tensor_collective_credit_return_pkts_sent_total_ += 1;

            if (dst_node == static_cast<uint32_t>(rt_.node_id)) {
                rt_.noc->injectLocal(static_cast<int>(dst_core), pkt);
            } else {
                rt_.noc->sendFromCore(static_cast<int>(rt_.core_id), pkt);
            }
        }

        sent_bytes = saturatingAddU64_(sent_bytes, kPacketBytes);
        if (!uncapped) {
            budget = (budget >= kPacketBytes) ? (budget - kPacketBytes) : 0ull;
        }

        if (it->second > static_cast<uint64_t>(credits)) {
            it->second -= static_cast<uint64_t>(credits);
            collective_credit_return_pending_queue_.push_back(key);
        } else {
            collective_credit_return_pending_credits_.erase(it);
        }
    }

    if (!collective_credit_return_pending_queue_.empty() && !uncapped && budget < kPacketBytes) {
        budget_blocked = true;
    }

    return sent_bytes;
}

uint64_t TensorWorkload::emitCollectiveTraffic_(uint64_t now_cycle, uint64_t noc_budget_bytes, bool& budget_blocked) {
    budget_blocked = false;
    bool backpressure_stalled = false;
    const bool soft_backpressure = (cfg_.collective_backpressure_mode == "soft");
    const bool credit_enabled = cfg_.collective_credit_enable;
    const bool event_credit_return = collectiveUseEventCreditReturn_();
    const uint64_t credit_window = credit_enabled
                                       ? static_cast<uint64_t>(std::max<uint32_t>(
                                             cfg_.collective_credit_window_chunks ? cfg_.collective_credit_window_chunks
                                                                                  : cfg_.collective_max_inflight_chunks,
                                             1u))
                                       : std::numeric_limits<uint64_t>::max();
    if (credit_enabled && !event_credit_return && collective_credit_inflight_chunks_ > 0) {
        collective_credit_inflight_chunks_ -= 1;
    }
    auto try_consume_credit = [&]() -> bool {
        if (!credit_enabled) return true;
        if (collective_credit_inflight_chunks_ < credit_window) return true;
        tensor_collective_credit_stall_cycles_total_ += 1;
        backpressure_stalled = true;
        if (!soft_backpressure) {
            budget_blocked = true;
            return false;
        }
        return true;
    };
    auto on_credit_issue = [&](uint32_t seq,
                               uint32_t chunk,
                               uint32_t step,
                               uint32_t dst_node,
                               uint16_t dst_core) {
        if (!credit_enabled) return;
        onCollectiveCreditIssue_(seq, chunk, step, dst_node, dst_core, now_cycle);
    };

    if (!collectiveReady_()) {
        if (cfg_.collective_type != "none" && cfg_.strict && !rt_.noc && rt_.log) {
            rt_.log->fatal(CALL_INFO, -1, "tensor fatal: collective enabled but INocTransport is null (core=%u)\n", rt_.core_id);
        }
        return 0;
    }

    // Program mode uses explicit collective ops; never auto-start based on period.
    if (cfg_.exec_mode == "program" && !collectivePendingActive_()) {
        return 0;
    }

    if (!collectivePendingActive_()) {
        if (cfg_.collective_blocking && collective_epoch_active_) {
            if (cfg_.collective_scope == "per_core") {
                if (collective_epoch_recv_bytes_ < collective_epoch_expected_recv_bytes_) return 0;
                // Completed: allow starting a new epoch.
                markCollectiveEpochDone_(now_cycle);
                const uint32_t done_seq = collective_epoch_seq_;
                collective_epoch_active_ = false;
                collective_epoch_expected_recv_bytes_ = 0;
                collective_epoch_recv_bytes_ = 0;
                collective_recv_bytes_by_seq_.erase(done_seq);
            } else {
                // Group-scoped blocking collective: wait for explicit RELEASE (leader/root broadcast).
                return 0;
            }
        }
        if (now_cycle - collective_last_cycle_ < cfg_.collective_period_cycles) return 0;

        const uint32_t seq32 = static_cast<uint32_t>(collective_seq_ & 0xffffffffu);
        collective_pending_active_ = true;
        collective_pending_seq_ = seq32;
        collective_pending_sent_bytes_ = 0;
        collective_pending_next_dest_ = 0;
        collective_pending_dest_nodes_.clear();
        collective_pending_dest_remaining_bytes_.clear();
        collective_ring_active_ = false;
        collective_ring_total_payload_bytes_ = 0;
        collective_ring_sent_payload_bytes_ = 0;
        collective_ring_reduce_wait_cycles_remaining_ = 0;
        collective_2d_active_ = false;
        collective_2d_dim_x_ = 0;
        collective_2d_dim_y_ = 0;
        collective_2d_row_hop_ = 0;
        collective_2d_col_hop_ = 0;

        if (cfg_.collective_algo == "ring_chunked" || cfg_.collective_algo == "torus_2d_rs_ag") {
            collective_active_bytes_ = cfg_.collective_bytes;
            const uint32_t chunk_bytes = std::max<uint32_t>(
                cfg_.collective_chunk_bytes ? cfg_.collective_chunk_bytes : cfg_.collective_packet_bytes,
                8u);
            uint32_t steps_per_chunk = 0;
            if (cfg_.collective_algo == "torus_2d_rs_ag") {
                collective_2d_active_ = true;
                const uint32_t total_nodes = (rt_.total_nodes > 0) ? static_cast<uint32_t>(rt_.total_nodes) : 1u;
                uint32_t dim_x = cfg_.collective_2d_dim_x;
                uint32_t dim_y = cfg_.collective_2d_dim_y;
                auto fallback_dims = [&]() {
                    const uint32_t sq = static_cast<uint32_t>(std::sqrt(static_cast<double>(total_nodes)));
                    if (sq > 0 && sq * sq == total_nodes) {
                        dim_x = sq;
                        dim_y = sq;
                    } else {
                        dim_x = total_nodes;
                        dim_y = 1u;
                    }
                };
                if (dim_x == 0u || dim_y == 0u ||
                    (static_cast<uint64_t>(dim_x) * static_cast<uint64_t>(dim_y) != static_cast<uint64_t>(total_nodes))) {
                    fallback_dims();
                }
                if (dim_x == 0u) dim_x = 1u;
                if (dim_y == 0u) dim_y = 1u;
                collective_2d_dim_x_ = dim_x;
                collective_2d_dim_y_ = dim_y;
                collective_2d_row_hop_ = (dim_x > 1u) ? (dim_x - 1u) : 1u;
                collective_2d_col_hop_ = (dim_y > 1u) ? (dim_y - 1u) : 1u;
                steps_per_chunk = 2u * (collective_2d_row_hop_ + collective_2d_col_hop_);
            } else {
                steps_per_chunk = collectiveRingStepsPerChunk_();
            }
            steps_per_chunk = std::max<uint32_t>(steps_per_chunk, 1u);
            const uint32_t chunks_total = static_cast<uint32_t>(
                std::max<uint64_t>(1ull, ceilDivU64_(collective_active_bytes_, static_cast<uint64_t>(chunk_bytes))));

            collective_ring_active_ = true;
            collective_ring_seq_ = seq32;
            collective_ring_chunks_total_ = chunks_total;
            collective_ring_steps_per_chunk_ = steps_per_chunk;
            collective_ring_chunk_index_ = 0;
            collective_ring_step_index_ = 0;
            collective_ring_step_remaining_bytes_ = collectiveRingStepPayloadBytes_(0, 0);
            collective_ring_max_inflight_chunks_ = std::max<uint32_t>(cfg_.collective_max_inflight_chunks, 1u);

            uint64_t total_payload = 0;
            for (uint32_t chunk_idx = 0; chunk_idx < chunks_total; ++chunk_idx) {
                for (uint32_t step = 0; step < steps_per_chunk; ++step) {
                    const uint64_t payload = static_cast<uint64_t>(collectiveRingStepPayloadBytes_(chunk_idx, step));
                    total_payload = saturatingAddU64_(total_payload, payload);
                }
            }
            collective_ring_total_payload_bytes_ = total_payload;
            collective_pending_total_bytes_ = total_payload;
            tensor_collective_chunk_groups_total_ += static_cast<uint64_t>(chunks_total);
        } else {
            const uint32_t total_nodes = (rt_.total_nodes > 0) ? static_cast<uint32_t>(rt_.total_nodes) : 1u;
            std::vector<uint32_t> dest_nodes;
            dest_nodes.reserve(2);

            const bool use_mesh_x = (cfg_.collective_pattern == "mesh_x");
            const bool use_mesh_xy = (cfg_.collective_pattern == "mesh_xy");
            if ((use_mesh_x || use_mesh_xy) && total_nodes > 1) {
                const uint32_t mesh_size = static_cast<uint32_t>(std::sqrt(static_cast<double>(total_nodes)));
                if (mesh_size > 0 && mesh_size * mesh_size == total_nodes) {
                    const uint32_t node_x = static_cast<uint32_t>(rt_.node_id) % mesh_size;
                    const uint32_t node_y = static_cast<uint32_t>(rt_.node_id) / mesh_size;
                    const uint32_t east = node_y * mesh_size + ((node_x + 1u) % mesh_size);
                    dest_nodes.push_back(east);
                    if (use_mesh_xy) {
                        const uint32_t south = ((node_y + 1u) % mesh_size) * mesh_size + node_x;
                        if (south != east) {
                            dest_nodes.push_back(south);
                        }
                    }
                }
            }
            if (dest_nodes.empty()) {
                dest_nodes.push_back((static_cast<uint32_t>(rt_.node_id) + 1u) % total_nodes);
            }

            // Ensure we can embed epoch seq in every packet (payload[0..7]).
            const uint64_t min_total_bytes = static_cast<uint64_t>(dest_nodes.size()) * 8ull;
            const uint64_t total_bytes = std::max<uint64_t>(cfg_.collective_bytes, min_total_bytes);
            collective_active_bytes_ = total_bytes;
            const uint64_t dest_count = static_cast<uint64_t>(dest_nodes.size());
            if (dest_count == 0 || total_bytes == 0) return 0;

            const uint64_t base_bytes = total_bytes / dest_count;
            const uint64_t remainder = total_bytes % dest_count;
            collective_pending_total_bytes_ = total_bytes;
            collective_pending_dest_nodes_ = dest_nodes;
            collective_pending_dest_remaining_bytes_.assign(dest_nodes.size(), 0);
            for (size_t dest_index = 0; dest_index < dest_nodes.size(); ++dest_index) {
                collective_pending_dest_remaining_bytes_[dest_index] = base_bytes + ((dest_index < remainder) ? 1u : 0u);
            }
        }

        collective_last_cycle_ = now_cycle;
            tensor_collective_cycles_total_ += 1;
            if (cfg_.collective_blocking) {
                collective_epoch_active_ = true;
                collective_epoch_seq_ = seq32;
                collective_epoch_expected_recv_bytes_ = collective_pending_total_bytes_;
                collective_epoch_recv_bytes_ = collectiveRecvBytesForSeq_(seq32);
                collective_epoch_start_cycle_ = now_cycle;
                collective_done_notified_ = false;
            }
            if (!cfg_.collective_blocking || cfg_.collective_scope == "per_core") {
                collective_seq_ += 1;
            }
    }

    if (!collectivePendingActive_()) return 0;

    uint64_t budget = noc_budget_bytes;
    const bool uncapped = (noc_budget_bytes == std::numeric_limits<uint64_t>::max());
    uint64_t bytes_sent = 0;
    const uint32_t packet_bytes = cfg_.collective_packet_bytes ? cfg_.collective_packet_bytes : 256u;
    const uint32_t seq32 = collective_pending_seq_;
    if (cfg_.collective_algo == "ring_chunked" || cfg_.collective_algo == "torus_2d_rs_ag") {
        uint32_t issued_packets = 0;
        while (collectivePendingActive_()) {
            if (!uncapped && budget < 8) {
                budget_blocked = true;
                backpressure_stalled = true;
                break;
            }
            if (collective_ring_max_inflight_chunks_ > 0 && issued_packets >= collective_ring_max_inflight_chunks_) {
                break;
            }
            if (collective_ring_reduce_wait_cycles_remaining_ > 0) {
                collective_ring_reduce_wait_cycles_remaining_ -= 1;
                tensor_collective_reduce_wait_cycles_total_ += 1;
                if (collective_2d_active_) {
                    tensor_collective_2d_reduce_wait_cycles_total_ += 1;
                }
                break;
            }
            if (!collective_ring_active_ || collective_ring_step_remaining_bytes_ == 0) {
                collective_pending_sent_bytes_ = collective_pending_total_bytes_;
                break;
            }
            if (!try_consume_credit()) {
                break;
            }

            uint64_t max_payload = std::min<uint64_t>(packet_bytes, collective_ring_step_remaining_bytes_);
            if (!uncapped) {
                max_payload = std::min<uint64_t>(max_payload, budget);
            }
            const uint32_t payload_bytes = static_cast<uint32_t>(max_payload);
            if (payload_bytes == 0) {
                budget_blocked = !uncapped;
                backpressure_stalled = backpressure_stalled || !uncapped;
                break;
            }

            const uint32_t step_in_chunk = collective_ring_step_index_;
            const Collective2dStage stage =
                collective_2d_active_ ? collective2dStageForStep_(step_in_chunk) : Collective2dStage::RowRS;
            const uint32_t dest_node =
                collective_2d_active_ ? collective2dNextDestNodeForStep_(step_in_chunk) : collectiveRingNextDestNode_();
            auto* pkt = new NocPacketEvent(rt_.node_id,
                                           dest_node,
                                           static_cast<uint16_t>(rt_.core_id),
                                           static_cast<uint16_t>(rt_.core_id),
                                           NocPacketKind::RawBytes,
                                           now_cycle);
            pkt->payload.resize(payload_bytes);
            fillBytesDeterministic_(cfg_.seed_base ^
                                        (static_cast<uint64_t>(rt_.node_id) << 32) ^
                                        (static_cast<uint64_t>(rt_.core_id) << 16),
                                    0,
                                    seq32 ^ collective_ring_chunk_index_ ^ (collective_ring_step_index_ << 16),
                                    pkt->payload);
            if (pkt->payload.size() >= 4) {
                pkt->payload[0] = static_cast<uint8_t>('C');
                pkt->payload[1] = static_cast<uint8_t>('O');
                pkt->payload[2] = static_cast<uint8_t>('L');
                pkt->payload[3] = static_cast<uint8_t>('L');
            }
            if (pkt->payload.size() >= 8) {
                write_u32_le_(pkt->payload, 4, seq32);
            }
            if (pkt->payload.size() >= 12) {
                write_u32_le_(pkt->payload, 8, collective_ring_chunk_index_);
            }
            if (pkt->payload.size() >= 16) {
                write_u32_le_(pkt->payload, 12, collective_ring_step_index_);
            }

            tensor_pkt_sent_total_ += 1;
            tensor_pkt_bytes_sent_total_ += static_cast<uint64_t>(pkt->payload.size());
            tensor_collective_pkts_sent_total_ += 1;
            tensor_collective_bytes_sent_total_ += static_cast<uint64_t>(pkt->payload.size());
            if (collective_2d_active_) {
                const uint64_t sent = static_cast<uint64_t>(pkt->payload.size());
                switch (stage) {
                    case Collective2dStage::RowRS:
                        tensor_collective_2d_row_rs_bytes_sent_total_ += sent;
                        break;
                    case Collective2dStage::ColRS:
                        tensor_collective_2d_col_rs_bytes_sent_total_ += sent;
                        break;
                    case Collective2dStage::ColAG:
                        tensor_collective_2d_col_ag_bytes_sent_total_ += sent;
                        break;
                    case Collective2dStage::RowAG:
                    default:
                        tensor_collective_2d_row_ag_bytes_sent_total_ += sent;
                        break;
                }
            }
            if (dest_node == static_cast<uint32_t>(rt_.node_id)) {
                rt_.noc->injectLocal(static_cast<int>(rt_.core_id), pkt);
            } else {
                rt_.noc->sendFromCore(static_cast<int>(rt_.core_id), pkt);
            }

            issued_packets += 1;
            on_credit_issue(seq32,
                            collective_ring_chunk_index_,
                            collective_ring_step_index_,
                            dest_node,
                            static_cast<uint16_t>(rt_.core_id));
            collective_ring_step_remaining_bytes_ -= payload_bytes;
            collective_ring_sent_payload_bytes_ += static_cast<uint64_t>(payload_bytes);
            collective_pending_sent_bytes_ += static_cast<uint64_t>(payload_bytes);
            bytes_sent += static_cast<uint64_t>(payload_bytes);
            if (!uncapped) {
                budget -= static_cast<uint64_t>(payload_bytes);
            }

            if (collective_ring_step_remaining_bytes_ == 0) {
                if (collective_2d_active_) {
                    const Collective2dStage completed = collective2dStageForStep_(collective_ring_step_index_);
                    switch (completed) {
                        case Collective2dStage::RowRS:
                            tensor_collective_2d_row_rs_steps_total_ += 1;
                            break;
                        case Collective2dStage::ColRS:
                            tensor_collective_2d_col_rs_steps_total_ += 1;
                            break;
                        case Collective2dStage::ColAG:
                            tensor_collective_2d_col_ag_steps_total_ += 1;
                            break;
                        case Collective2dStage::RowAG:
                        default:
                            tensor_collective_2d_row_ag_steps_total_ += 1;
                            break;
                    }
                }
                tensor_collective_ring_steps_total_ += 1;
                collective_ring_step_index_ += 1;
                if (collective_ring_step_index_ >= collective_ring_steps_per_chunk_) {
                    collective_ring_step_index_ = 0;
                    collective_ring_chunk_index_ += 1;
                }

                if (collective_ring_chunk_index_ >= collective_ring_chunks_total_) {
                    collective_ring_active_ = false;
                    collective_pending_sent_bytes_ = collective_pending_total_bytes_;
                    break;
                }

                collective_ring_step_remaining_bytes_ =
                    collectiveRingStepPayloadBytes_(collective_ring_chunk_index_, collective_ring_step_index_);
                if (cfg_.collective_type == "allreduce" && cfg_.collective_reduce_overhead_cycles > 0) {
                    if (collective_2d_active_) {
                        const uint32_t stage2_start = collective_2d_row_hop_ + collective_2d_col_hop_;
                        if (collective_ring_step_index_ == stage2_start) {
                            collective_ring_reduce_wait_cycles_remaining_ = cfg_.collective_reduce_overhead_cycles;
                        }
                    } else {
                        const uint32_t participants = collectiveRingParticipantCount_();
                        const uint32_t rs_steps = (participants > 1) ? (participants - 1u) : 1u;
                        if (collective_ring_step_index_ == rs_steps) {
                            collective_ring_reduce_wait_cycles_remaining_ = cfg_.collective_reduce_overhead_cycles;
                        }
                    }
                }
            }
        }
    } else {
        while (collectivePendingActive_()) {
            if (!uncapped && budget < 8) {
                budget_blocked = true;
                backpressure_stalled = true;
                break;
            }
            if (!try_consume_credit()) {
                break;
            }

            bool found_dest = false;
            size_t dest_index = collective_pending_next_dest_;
            for (size_t i = 0; i < collective_pending_dest_nodes_.size(); ++i) {
                const size_t idx = (dest_index + i) % collective_pending_dest_nodes_.size();
                if (collective_pending_dest_remaining_bytes_[idx] > 0) {
                    dest_index = idx;
                    found_dest = true;
                    break;
                }
            }
            if (!found_dest) break;

            uint64_t remaining = collective_pending_dest_remaining_bytes_[dest_index];
            uint64_t max_payload = std::min<uint64_t>(packet_bytes, remaining);
            if (!uncapped) {
                if (budget == 0) {
                    budget_blocked = true;
                    backpressure_stalled = true;
                    break;
                }
                max_payload = std::min<uint64_t>(max_payload, budget);
            }
            const uint32_t payload_bytes = static_cast<uint32_t>(max_payload);
            if (payload_bytes == 0) {
                budget_blocked = !uncapped;
                backpressure_stalled = backpressure_stalled || !uncapped;
                break;
            }

            const uint32_t dest_node = collective_pending_dest_nodes_[dest_index];
            auto* pkt = new NocPacketEvent(rt_.node_id,
                                           dest_node,
                                           static_cast<uint16_t>(rt_.core_id),
                                           static_cast<uint16_t>(rt_.core_id),
                                           NocPacketKind::RawBytes,
                                           now_cycle);
            pkt->payload.resize(payload_bytes);
            fillBytesDeterministic_(cfg_.seed_base ^
                                        (static_cast<uint64_t>(rt_.node_id) << 32) ^
                                        (static_cast<uint64_t>(rt_.core_id) << 16),
                                    0,
                                    seq32,
                                    pkt->payload);
            if (pkt->payload.size() >= 4) {
                pkt->payload[0] = static_cast<uint8_t>('C');
                pkt->payload[1] = static_cast<uint8_t>('O');
                pkt->payload[2] = static_cast<uint8_t>('L');
                pkt->payload[3] = static_cast<uint8_t>('L');
            }
            if (pkt->payload.size() >= 8) {
                write_u32_le_(pkt->payload, 4, seq32);
            }

            tensor_pkt_sent_total_ += 1;
            tensor_pkt_bytes_sent_total_ += static_cast<uint64_t>(pkt->payload.size());
            tensor_collective_pkts_sent_total_ += 1;
            tensor_collective_bytes_sent_total_ += static_cast<uint64_t>(pkt->payload.size());
            if (dest_node == static_cast<uint32_t>(rt_.node_id)) {
                rt_.noc->injectLocal(static_cast<int>(rt_.core_id), pkt);
            } else {
                rt_.noc->sendFromCore(static_cast<int>(rt_.core_id), pkt);
            }

            collective_pending_dest_remaining_bytes_[dest_index] -= static_cast<uint64_t>(payload_bytes);
            on_credit_issue(seq32, 0u, 0u, dest_node, static_cast<uint16_t>(rt_.core_id));
            collective_pending_sent_bytes_ += static_cast<uint64_t>(payload_bytes);
            collective_pending_next_dest_ = (dest_index + 1) % collective_pending_dest_nodes_.size();
            bytes_sent += static_cast<uint64_t>(payload_bytes);
            if (!uncapped) {
                budget -= static_cast<uint64_t>(payload_bytes);
                if (budget == 0) break;
            }
        }
    }

    if (!collectivePendingActive_()) {
        collective_pending_active_ = false;
        collective_active_bytes_ = 0;
        collective_pending_total_bytes_ = 0;
        collective_pending_sent_bytes_ = 0;
        collective_pending_dest_nodes_.clear();
        collective_pending_dest_remaining_bytes_.clear();
        collective_pending_next_dest_ = 0;
        collective_ring_active_ = false;
        collective_ring_total_payload_bytes_ = 0;
        collective_ring_sent_payload_bytes_ = 0;
        collective_ring_reduce_wait_cycles_remaining_ = 0;
        collective_2d_active_ = false;
        collective_2d_dim_x_ = 0;
        collective_2d_dim_y_ = 0;
        collective_2d_row_hop_ = 0;
        collective_2d_col_hop_ = 0;
        if (!event_credit_return) {
            collective_credit_inflight_chunks_ = 0;
            collective_credit_outstanding_.clear();
            collective_credit_return_seen_.clear();
            collective_credit_return_pending_credits_.clear();
            collective_credit_return_pending_queue_.clear();
        } else if (collective_credit_outstanding_.empty()) {
            collective_credit_return_seen_.clear();
        }
    }

    if (backpressure_stalled) {
        tensor_collective_backpressure_stall_cycles_total_ += 1;
    }

    return bytes_sent;
}

uint64_t TensorWorkload::emitCommTraffic_(uint64_t now_cycle, uint64_t noc_budget_bytes, bool& budget_blocked) {
    budget_blocked = false;
    if (!commReady_()) {
        if (cfg_.comm_enable && cfg_.strict && !rt_.noc && rt_.log) {
            rt_.log->fatal(CALL_INFO, -1, "tensor fatal: comm_enable=1 but INocTransport is null (core=%u)\n", rt_.core_id);
        }
        return 0;
    }
    if (now_cycle - comm_last_cycle_ < cfg_.comm_period_cycles) return 0;

    if (cfg_.noc_bandwidth_bytes_per_cycle > 0 &&
        static_cast<uint64_t>(cfg_.comm_payload_bytes) > noc_budget_bytes) {
        budget_blocked = true;
        return 0;
    }

    const uint32_t dst_node =
        (rt_.total_nodes > 1) ? ((rt_.node_id + 1u) % rt_.total_nodes) : rt_.node_id;
    auto* pkt = new NocPacketEvent(rt_.node_id,
                                   dst_node,
                                   static_cast<uint16_t>(rt_.core_id),
                                   static_cast<uint16_t>(rt_.core_id),
                                   NocPacketKind::RawBytes,
                                   now_cycle);
    pkt->payload.resize(cfg_.comm_payload_bytes);
    fillBytesDeterministic_(cfg_.seed_base ^
                                (static_cast<uint64_t>(rt_.node_id) << 32) ^
                                (static_cast<uint64_t>(rt_.core_id) << 16),
                            0,
                            iter_seq_,
                            pkt->payload);
    tensor_pkt_sent_total_ += 1;
    tensor_pkt_bytes_sent_total_ += static_cast<uint64_t>(pkt->payload.size());
    if (dst_node == rt_.node_id) {
        rt_.noc->injectLocal(static_cast<int>(rt_.core_id), pkt);
    } else {
        rt_.noc->sendFromCore(static_cast<int>(rt_.core_id), pkt);
    }
    comm_last_cycle_ = now_cycle;
    return static_cast<uint64_t>(pkt->payload.size());
}

void TensorWorkload::issueNocTraffic_(uint64_t now_cycle,
                                      uint64_t& noc_budget,
                                      bool& did,
                                      bool& did_collective,
                                      bool& did_comm,
                                      bool& noc_budget_blocked) {
    const uint64_t uncapped_budget = std::numeric_limits<uint64_t>::max();
    auto consume_budget = [&](uint64_t sent_bytes) {
        if (cfg_.noc_bandwidth_bytes_per_cycle > 0 && noc_budget != uncapped_budget) {
            noc_budget = (noc_budget >= sent_bytes) ? (noc_budget - sent_bytes) : 0;
        }
    };

    auto issue_collective = [&]() {
        bool blocked_collective = false;
        const uint64_t collective_sent = emitCollectiveTraffic_(now_cycle, noc_budget, blocked_collective);
        if (collective_sent > 0) {
            did = true;
            did_collective = true;
            tensor_collective_issue_cycles_total_ += 1;
            consume_budget(collective_sent);
        }
        if (collectivePendingActive_()) {
            tensor_collective_pending_cycles_total_ += 1;
        }
        noc_budget_blocked = noc_budget_blocked || blocked_collective;
    };

    auto issue_credit_return = [&]() {
        bool blocked_credit_return = false;
        const uint64_t return_sent = emitCollectiveCreditReturnTraffic_(now_cycle, noc_budget, blocked_credit_return);
        if (return_sent > 0) {
            did = true;
            consume_budget(return_sent);
        }
        noc_budget_blocked = noc_budget_blocked || blocked_credit_return;
    };

    auto issue_comm = [&]() {
        bool blocked_comm = false;
        const uint64_t comm_sent = emitCommTraffic_(now_cycle, noc_budget, blocked_comm);
        if (comm_sent > 0) {
            did = true;
            did_comm = true;
            consume_budget(comm_sent);
        }
        noc_budget_blocked = noc_budget_blocked || blocked_comm;
    };

    issue_credit_return();

    if (cfg_.collective_issue_priority == "payload_first") {
        issue_comm();
        issue_collective();
    } else {
        issue_collective();
        issue_comm();
    }
}

uint64_t TensorWorkload::collectiveRecvBytesForSeq_(uint32_t seq) const {
    auto it = collective_recv_bytes_by_seq_.find(seq);
    if (it == collective_recv_bytes_by_seq_.end()) return 0;
    return it->second;
}

void TensorWorkload::markCollectiveEpochDone_(uint64_t now_cycle) {
    if (!cfg_.collective_blocking) return;
    if (!collective_epoch_active_) return;
    if (collective_epoch_expected_recv_bytes_ == 0) return;

    const uint64_t start = collective_epoch_start_cycle_;
    const uint64_t lat = (now_cycle >= start) ? (now_cycle - start) : 0ull;
    tensor_collective_epoch_done_total_ += 1ull;
    tensor_collective_epoch_latency_cycles_total_ = saturatingAddU64_(tensor_collective_epoch_latency_cycles_total_, lat);
    if (lat > tensor_collective_epoch_latency_cycles_max_) {
        tensor_collective_epoch_latency_cycles_max_ = lat;
    }
    collective_epoch_start_cycle_ = 0;
}

void TensorWorkload::serviceCollectiveBarrier_(uint64_t now_cycle) {
    if (!cfg_.collective_blocking) return;

    // Per-core blocking barrier: completion is purely local (no RELEASE/control traffic).
    // We service it here so program-mode workloads can observe completion without relying
    // on the bulk/tile scheduler paths.
    if (cfg_.collective_scope == "per_core") {
        if (!collective_epoch_active_) return;
        if (collective_epoch_expected_recv_bytes_ == 0) return;
        if (collective_epoch_recv_bytes_ < collective_epoch_expected_recv_bytes_) return;
        markCollectiveEpochDone_(now_cycle);
        const uint32_t done_seq = collective_epoch_seq_;
        collective_epoch_active_ = false;
        collective_epoch_expected_recv_bytes_ = 0;
        collective_epoch_recv_bytes_ = 0;
        collective_recv_bytes_by_seq_.erase(done_seq);
        return;
    }

    if (!collectiveReady_()) return;

    maybeNotifyCollectiveDone_(now_cycle);
    maybeEmitCollectiveRelease_(now_cycle);
}

void TensorWorkload::maybeNotifyCollectiveDone_(uint64_t now_cycle) {
    if (!cfg_.collective_blocking) return;
    if (cfg_.collective_scope == "per_core") return;
    if (!collective_epoch_active_) return;
    if (collective_done_notified_) return;
    if (collective_epoch_expected_recv_bytes_ == 0) return;
    if (collective_epoch_recv_bytes_ < collective_epoch_expected_recv_bytes_) return;

    // Mark notified before sending to avoid accidental duplicates.
    collective_done_notified_ = true;

    std::vector<uint8_t> payload(16, 0);
    payload[0] = static_cast<uint8_t>('T');
    payload[1] = static_cast<uint8_t>('C');
    payload[2] = static_cast<uint8_t>('D');
    payload[3] = static_cast<uint8_t>('N');
    write_u32_le_(payload, 4, collective_epoch_seq_);
    write_u32_le_(payload, 8, static_cast<uint32_t>(rt_.node_id));
    write_u32_le_(payload, 12, static_cast<uint32_t>(rt_.core_id));

    const uint32_t dst_node = (cfg_.collective_scope == "per_pe") ? static_cast<uint32_t>(rt_.node_id) : 0u;
    const uint32_t dst_core = 0u;

    const bool self_is_dst = (dst_node == static_cast<uint32_t>(rt_.node_id) && dst_core == static_cast<uint32_t>(rt_.core_id));
    if (self_is_dst) {
        onCollectiveControlPacket_(payload, now_cycle);
        return;
    }

    if (!rt_.noc) return;
    auto* pkt = new NocPacketEvent(rt_.node_id,
                                   dst_node,
                                   static_cast<uint16_t>(rt_.core_id),
                                   static_cast<uint16_t>(dst_core),
                                   NocPacketKind::Control,
                                   now_cycle);
    pkt->payload = payload;
    tensor_pkt_sent_total_ += 1;
    tensor_pkt_bytes_sent_total_ += static_cast<uint64_t>(pkt->payload.size());
    if (dst_node == static_cast<uint32_t>(rt_.node_id)) {
        rt_.noc->injectLocal(static_cast<int>(dst_core), pkt);
    } else {
        rt_.noc->sendFromCore(static_cast<int>(rt_.core_id), pkt);
    }
}

void TensorWorkload::maybeEmitCollectiveRelease_(uint64_t now_cycle) {
    if (!collective_release_pending_) return;

    const bool is_pe_leader = (cfg_.collective_scope == "per_pe" && rt_.core_id == 0u);
    const bool is_sys_root = (cfg_.collective_scope == "per_system" && rt_.node_id == 0u && rt_.core_id == 0u);
    if (!is_pe_leader && !is_sys_root) return;
    if (!rt_.noc) return;

    const uint32_t seq = collective_release_pending_seq_;
    const uint32_t next = seq + 1u;

    std::vector<uint8_t> payload(12, 0);
    payload[0] = static_cast<uint8_t>('T');
    payload[1] = static_cast<uint8_t>('C');
    payload[2] = static_cast<uint8_t>('R');
    payload[3] = static_cast<uint8_t>('L');
    write_u32_le_(payload, 4, seq);
    write_u32_le_(payload, 8, next);

    if (is_pe_leader) {
        const uint32_t node = static_cast<uint32_t>(rt_.node_id);
        const uint32_t cores = total_cores_cfg_ ? total_cores_cfg_ : 1u;
        for (uint32_t core = 0; core < cores; ++core) {
            if (core == static_cast<uint32_t>(rt_.core_id)) continue;
            auto* pkt = new NocPacketEvent(rt_.node_id,
                                           node,
                                           static_cast<uint16_t>(rt_.core_id),
                                           static_cast<uint16_t>(core),
                                           NocPacketKind::Control,
                                           now_cycle);
            pkt->payload = payload;
            tensor_pkt_sent_total_ += 1;
            tensor_pkt_bytes_sent_total_ += static_cast<uint64_t>(pkt->payload.size());
            rt_.noc->injectLocal(static_cast<int>(core), pkt);
        }
        onCollectiveRelease_(seq, next, now_cycle);
    } else {
        const uint32_t total_nodes = (rt_.total_nodes > 0) ? static_cast<uint32_t>(rt_.total_nodes) : 1u;
        const uint32_t cores = total_cores_cfg_ ? total_cores_cfg_ : 1u;
        for (uint32_t node = 0; node < total_nodes; ++node) {
            for (uint32_t core = 0; core < cores; ++core) {
                if (node == static_cast<uint32_t>(rt_.node_id) && core == static_cast<uint32_t>(rt_.core_id)) continue;
                auto* pkt = new NocPacketEvent(rt_.node_id,
                                               node,
                                               static_cast<uint16_t>(rt_.core_id),
                                               static_cast<uint16_t>(core),
                                               NocPacketKind::Control,
                                               now_cycle);
                pkt->payload = payload;
                tensor_pkt_sent_total_ += 1;
                tensor_pkt_bytes_sent_total_ += static_cast<uint64_t>(pkt->payload.size());
                if (node == static_cast<uint32_t>(rt_.node_id)) {
                    rt_.noc->injectLocal(static_cast<int>(core), pkt);
                } else {
                    rt_.noc->sendFromCore(static_cast<int>(rt_.core_id), pkt);
                }
            }
        }
        onCollectiveRelease_(seq, next, now_cycle);
    }

    collective_release_pending_ = false;
    collective_release_pending_seq_ = 0;
    collective_barrier_done_count_ = 0;
    collective_barrier_done_bitmap_.clear();
}

void TensorWorkload::onCollectiveControlPacket_(const std::vector<uint8_t>& payload, uint64_t now_cycle) {
    (void)now_cycle;
    if (!cfg_.collective_blocking) return;
    if (cfg_.collective_scope == "per_core") return;

    if (has_magic4_(payload, 'T', 'C', 'D', 'N')) {
        if (payload.size() < 16) return;
        const uint32_t seq = read_u32_le_(payload, 4);
        const uint32_t sender_node = read_u32_le_(payload, 8);
        const uint32_t sender_core = read_u32_le_(payload, 12);
        if (sender_core >= (total_cores_cfg_ ? total_cores_cfg_ : 1u)) return;

        const uint32_t cur_seq = static_cast<uint32_t>(collective_seq_ & 0xffffffffu);
        if (seq != cur_seq) return;

        size_t expected = 0;
        size_t idx = 0;
        if (cfg_.collective_scope == "per_pe") {
            if (rt_.core_id != 0u) return;
            if (sender_node != static_cast<uint32_t>(rt_.node_id)) return;
            expected = static_cast<size_t>(total_cores_cfg_ ? total_cores_cfg_ : 1u);
            idx = static_cast<size_t>(sender_core);
        } else if (cfg_.collective_scope == "per_system") {
            if (!(rt_.node_id == 0u && rt_.core_id == 0u)) return;
            const uint32_t total_nodes = (rt_.total_nodes > 0) ? static_cast<uint32_t>(rt_.total_nodes) : 1u;
            if (sender_node >= total_nodes) return;
            expected = static_cast<size_t>(total_nodes) * static_cast<size_t>(total_cores_cfg_ ? total_cores_cfg_ : 1u);
            idx = static_cast<size_t>(sender_node) * static_cast<size_t>(total_cores_cfg_ ? total_cores_cfg_ : 1u) +
                  static_cast<size_t>(sender_core);
        } else {
            return;
        }

        if (expected == 0) return;
        if (collective_barrier_done_bitmap_.size() != expected) {
            collective_barrier_done_bitmap_.assign(expected, 0);
            collective_barrier_done_count_ = 0;
        }
        if (idx >= collective_barrier_done_bitmap_.size()) return;

        if (collective_barrier_done_bitmap_[idx] == 0) {
            collective_barrier_done_bitmap_[idx] = 1;
            collective_barrier_done_count_ += 1;
        }

        if (collective_barrier_done_count_ >= expected && !collective_release_pending_) {
            collective_release_pending_ = true;
            collective_release_pending_seq_ = seq;
        }
        return;
    }

    if (has_magic4_(payload, 'T', 'C', 'R', 'L')) {
        if (payload.size() < 12) return;
        const uint32_t seq = read_u32_le_(payload, 4);
        const uint32_t next = read_u32_le_(payload, 8);
        onCollectiveRelease_(seq, next, now_cycle);
        return;
    }
}

void TensorWorkload::onCollectiveRelease_(uint32_t seq, uint32_t next_seq, uint64_t now_cycle) {
    if (!cfg_.collective_blocking) return;
    if (cfg_.collective_scope == "per_core") return;

    const uint32_t cur_seq = static_cast<uint32_t>(collective_seq_ & 0xffffffffu);
    if (seq != cur_seq) return;

    markCollectiveEpochDone_(now_cycle);
    collective_seq_ = static_cast<uint64_t>(next_seq);
    collective_epoch_active_ = false;
    collective_epoch_expected_recv_bytes_ = 0;
    collective_epoch_recv_bytes_ = 0;
    collective_done_notified_ = false;
    collective_recv_bytes_by_seq_.erase(seq);
}

bool TensorWorkload::deliverPacket(NocPacketEvent* packet) {
    if (!packet) return true;
    const NocPacketKind kind = packet->packetKind();
    if (kind == NocPacketKind::RawBytes || kind == NocPacketKind::Control) {
        tensor_pkt_recv_total_ += 1;
        tensor_pkt_bytes_recv_total_ += static_cast<uint64_t>(packet->payload.size());
    }
    if (kind == NocPacketKind::RawBytes) {
        if (has_collective_magic_(packet->payload)) {
            tensor_collective_pkts_recv_total_ += 1;
            tensor_collective_bytes_recv_total_ += static_cast<uint64_t>(packet->payload.size());
            const uint32_t seq = read_u32_le_(packet->payload, 4);
            if (cfg_.collective_blocking) {
                collective_recv_bytes_by_seq_[seq] += static_cast<uint64_t>(packet->payload.size());
                if (collective_epoch_active_ && seq == collective_epoch_seq_) {
                    collective_epoch_recv_bytes_ = collectiveRecvBytesForSeq_(collective_epoch_seq_);
                }
            }
            maybeEmitCollectiveCreditReturn_(packet, packet->timestamp);
        }
    } else if (kind == NocPacketKind::Control) {
        if (has_magic4_(packet->payload, 'T', 'C', 'C', 'R')) {
            if (packet->payload.size() >= 20) {
                const uint32_t seq = read_u32_le_(packet->payload, 4);
                const uint32_t chunk = read_u32_le_(packet->payload, 8);
                const uint32_t step = read_u32_le_(packet->payload, 12);
                const uint32_t credits = read_u32_le_(packet->payload, 16);
                tensor_collective_credit_return_pkts_recv_total_ += 1;
                onCollectiveCreditReturn_(seq,
                                          chunk,
                                          step,
                                          credits,
                                          packet->src_node,
                                          packet->src_endpoint,
                                          packet->timestamp);
            }
        } else {
            onCollectiveControlPacket_(packet->payload, packet->timestamp);
        }
    }
    delete packet;
    return true;
}

bool TensorWorkload::onClockTickTile_(uint64_t now_cycle) {
    // Start iteration when ready (and not blocked by a pending blocking-collective epoch).
    if (!iter_active_) {
        if (cfg_.exec_mode != "program" && cfg_.iterations > 0 && iter_done_ >= cfg_.iterations) return false;

        if (cfg_.collective_blocking && collective_epoch_active_) {
            if (cfg_.collective_scope == "per_core") {
                if (collective_epoch_recv_bytes_ < collective_epoch_expected_recv_bytes_) {
                    tensor_stall_collective_cycles_total_ += 1;
                    if (!inflight_.empty()) {
                        // Still allow progress due to in-flight completions; this tick itself does not do work.
                    }
                    return false;
                }
                // Epoch completed: clear barrier.
                markCollectiveEpochDone_(now_cycle);
                const uint32_t done_seq = collective_epoch_seq_;
                collective_epoch_active_ = false;
                collective_epoch_expected_recv_bytes_ = 0;
                collective_epoch_recv_bytes_ = 0;
                collective_recv_bytes_by_seq_.erase(done_seq);
            } else {
                // Group scope: explicit RELEASE drives epoch completion.
                tensor_stall_collective_cycles_total_ += 1;
                return false;
            }
        }

        if (inflight_.empty()) {
            startIteration_();
        }
    }

    bool did = false;
    bool did_mem = false;
    bool did_compute = false;
    bool did_collective = false;
    bool did_comm = false;
    bool noc_budget_blocked = false;
    uint64_t noc_budget = (cfg_.noc_bandwidth_bytes_per_cycle > 0)
                              ? cfg_.noc_bandwidth_bytes_per_cycle
                              : std::numeric_limits<uint64_t>::max();
    resetOnchipCycleState_(now_cycle);

    if (iter_active_) {
        issueNocTraffic_(now_cycle, noc_budget, did, did_collective, did_comm, noc_budget_blocked);
    }
    if (noc_budget_blocked && !did_collective && !did_comm) {
        tensor_stall_noc_budget_cycles_total_ += 1;
    }

    if (!iter_active_) {
        if (did) active_cycles_++;
        return did;
    }

    tensor_iter_cycles_total_ += 1;

    // DMA budgeting (bytes/cycle); if disabled, issue as much as possible until outstanding limit.
    const uint64_t kUncapped = std::numeric_limits<uint64_t>::max();
    uint64_t budget = dmaBudgetBytesPerCycle_(now_cycle);
    const bool dma_capped = (budget != kUncapped);
    bool blocked_budget = dma_capped && (budget == 0);
    bool blocked_hbm_channel_budget = false;
    bool blocked_outstanding = false;
    bool blocked_onchip_capacity = false;
    bool blocked_onchip_port = false;
    bool blocked_onchip_bank_conflict = false;
    bool blocked_spill_budget = false;
    uint64_t spill_budget = (cfg_.spill_share_noc_budget && cfg_.noc_bandwidth_bytes_per_cycle > 0)
                                ? noc_budget
                                : std::numeric_limits<uint64_t>::max();

    const auto max_out = static_cast<size_t>(cfg_.mem_max_outstanding);
    const bool prefetch = (cfg_.overlap_enable || cfg_.double_buffer);
    auto rollback_ub_alloc = [&](std::vector<std::pair<uint32_t, uint64_t>>& allocs, uint64_t bytes) {
        uint64_t rem = bytes;
        while (rem > 0 && !allocs.empty()) {
            std::pair<uint32_t, uint64_t>& tail = allocs.back();
            const uint64_t cut = std::min<uint64_t>(rem, tail.second);
            if (cut > 0) {
                onchip_ub_occupancy_bytes_ = (onchip_ub_occupancy_bytes_ >= cut) ? (onchip_ub_occupancy_bytes_ - cut) : 0;
                if (tail.first < onchip_ub_bank_occupancy_bytes_.size()) {
                    uint64_t& occ = onchip_ub_bank_occupancy_bytes_[tail.first];
                    occ = (occ >= cut) ? (occ - cut) : 0;
                }
                tail.second -= cut;
                rem -= cut;
            } else {
                rem = 0;
            }
            if (tail.second == 0) allocs.pop_back();
        }
    };
    auto rollback_weight_alloc = [&](std::vector<std::pair<uint32_t, uint64_t>>& allocs, uint64_t bytes) {
        uint64_t rem = bytes;
        while (rem > 0 && !allocs.empty()) {
            std::pair<uint32_t, uint64_t>& tail = allocs.back();
            const uint64_t cut = std::min<uint64_t>(rem, tail.second);
            if (cut > 0) {
                onchip_weight_occupancy_bytes_ =
                    (onchip_weight_occupancy_bytes_ >= cut) ? (onchip_weight_occupancy_bytes_ - cut) : 0;
                if (tail.first < onchip_weight_bank_occupancy_bytes_.size()) {
                    uint64_t& occ = onchip_weight_bank_occupancy_bytes_[tail.first];
                    occ = (occ >= cut) ? (occ - cut) : 0;
                }
                tail.second -= cut;
                rem -= cut;
            } else {
                rem = 0;
            }
            if (tail.second == 0) allocs.pop_back();
        }
    };

    retireCompletedWritebacks_();

    // === Mandatory reads for current tile-seg ===
    if (cfg_.mem_enable && rt_.mem && tile_cur_.valid) {
        while (budget > 0) {
            uint64_t pending = 0;
            MemTag tag = MemTag::Generic;
            if (tile_cur_.issued_a_bytes < tile_cur_.need_a_bytes) {
                pending = tile_cur_.need_a_bytes - tile_cur_.issued_a_bytes;
                tag = MemTag::ReadA;
            } else if (tile_cur_.issued_b_bytes < tile_cur_.need_b_bytes) {
                pending = tile_cur_.need_b_bytes - tile_cur_.issued_b_bytes;
                tag = MemTag::ReadB;
            } else {
                break;
            }

            if (inflight_.size() >= max_out) {
                blocked_outstanding = true;
                break;
            }

            uint32_t chunk = static_cast<uint32_t>(std::min<uint64_t>(cfg_.mem_req_bytes, pending));
            if (chunk == 0) break;
            if (chunk > budget) {
                blocked_budget = true;
                break;
            }

            uint32_t hbm_ch = 0;
            chunk = clampBytesByHbmChannelBudget_(now_cycle, ReqKind::Read, chunk, hbm_ch);
            if (chunk == 0) {
                blocked_hbm_channel_budget = true;
                break;
            }

            const bool use_weight_pool = (tag == MemTag::ReadB && cfg_.weight_bytes > 0);
            bool onchip_spilled = false;
            if (cfg_.onchip_model_enable) {
                if (!acquireOnchipWritePorts_(1, 0)) {
                    blocked_onchip_port = true;
                    break;
                }
                bool spill_budget_blocked_local = false;
                bool bank_conflict_blocked_local = false;
                std::vector<std::pair<uint32_t, uint64_t>>* bank_allocs =
                    (cfg_.onchip_bank_model_enable
                         ? ((tag == MemTag::ReadA) ? &tile_cur_.reserved_a_bank_allocs
                                                   : (use_weight_pool ? &tile_cur_.reserved_b_weight_bank_allocs
                                                                      : &tile_cur_.reserved_b_bank_allocs))
                         : nullptr);
                const bool ok = use_weight_pool
                                    ? reserveWeightBytes_(chunk,
                                                          spill_budget,
                                                          onchip_spilled,
                                                          spill_budget_blocked_local,
                                                          bank_conflict_blocked_local,
                                                          bank_allocs)
                                    : reserveUbBytes_(chunk,
                                                      spill_budget,
                                                      onchip_spilled,
                                                      spill_budget_blocked_local,
                                                      bank_conflict_blocked_local,
                                                      bank_allocs);
                if (!ok) {
                    if (spill_budget_blocked_local) {
                        blocked_spill_budget = true;
                    } else if (bank_conflict_blocked_local) {
                        blocked_onchip_bank_conflict = true;
                    } else {
                        blocked_onchip_capacity = true;
                    }
                    break;
                }
            }

            const uint32_t issued = issueMemReadTagged_(chunk, tag, tile_cur_.epoch);
            if (issued == 0) {
                if (cfg_.onchip_model_enable && !onchip_spilled) {
                    if (cfg_.onchip_bank_model_enable) {
                        if (tag == MemTag::ReadA) {
                            rollback_ub_alloc(tile_cur_.reserved_a_bank_allocs, chunk);
                        } else if (tag == MemTag::ReadB) {
                            if (use_weight_pool) {
                                rollback_weight_alloc(tile_cur_.reserved_b_weight_bank_allocs, chunk);
                            } else {
                                rollback_ub_alloc(tile_cur_.reserved_b_bank_allocs, chunk);
                            }
                        }
                    } else {
                        if (use_weight_pool) {
                            releaseWeightBytes_(chunk);
                        } else {
                            releaseUbBytes_(chunk);
                        }
                    }
                }
                if (inflight_.size() >= max_out) blocked_outstanding = true;
                break;
            }
            consumeHbmChannelBudget_(now_cycle, hbm_ch, issued);
            if (cfg_.onchip_model_enable && !onchip_spilled && issued < chunk) {
                const uint64_t rollback = static_cast<uint64_t>(chunk - issued);
                if (cfg_.onchip_bank_model_enable) {
                    if (tag == MemTag::ReadA) {
                        rollback_ub_alloc(tile_cur_.reserved_a_bank_allocs, rollback);
                    } else if (tag == MemTag::ReadB) {
                        if (use_weight_pool) {
                            rollback_weight_alloc(tile_cur_.reserved_b_weight_bank_allocs, rollback);
                        } else {
                            rollback_ub_alloc(tile_cur_.reserved_b_bank_allocs, rollback);
                        }
                    }
                } else {
                    if (use_weight_pool) {
                        releaseWeightBytes_(rollback);
                    } else {
                        releaseUbBytes_(rollback);
                    }
                }
            }
            if (tag == MemTag::ReadA) {
                tile_cur_.issued_a_bytes += issued;
                if (cfg_.onchip_model_enable && !onchip_spilled) {
                    tile_cur_.reserved_a_bytes += issued;
                }
            } else if (tag == MemTag::ReadB) {
                tile_cur_.issued_b_bytes += issued;
                if (cfg_.onchip_model_enable && !onchip_spilled) {
                    if (use_weight_pool) {
                        tile_cur_.reserved_b_weight_bytes += issued;
                    } else {
                        tile_cur_.reserved_b_bytes += issued;
                    }
                }
            }
            rem_read_bytes_ = (rem_read_bytes_ >= issued) ? (rem_read_bytes_ - issued) : 0;
            budget -= issued;
            did = true;
            did_mem = true;
        }
    }

    // === Writebacks (oldest-first) ===
    if (cfg_.mem_enable && rt_.mem) {
        while (budget > 0 && !tile_writeback_queue_.empty()) {
            const uint64_t epoch = tile_writeback_queue_.front();
            auto it = tile_writebacks_.find(epoch);
            if (it == tile_writebacks_.end()) {
                tile_writeback_queue_.pop_front();
                continue;
            }
            WritebackState& st = it->second;
            if (st.issued_bytes >= st.total_bytes) {
                // Issued all; wait for completions.
                break;
            }
            if (inflight_.size() >= max_out) {
                blocked_outstanding = true;
                break;
            }
            const uint64_t pending = st.total_bytes - st.issued_bytes;
            uint32_t chunk = static_cast<uint32_t>(std::min<uint64_t>(cfg_.mem_req_bytes, pending));
            if (chunk == 0) break;
            if (chunk > budget) {
                blocked_budget = true;
                break;
            }

            uint32_t hbm_ch = 0;
            chunk = clampBytesByHbmChannelBudget_(now_cycle, ReqKind::Write, chunk, hbm_ch);
            if (chunk == 0) {
                blocked_hbm_channel_budget = true;
                break;
            }
            if (cfg_.onchip_model_enable && cfg_.acc_bytes > 0) {
                const uint64_t acc_key = (static_cast<uint64_t>(st.mi) << 32) | static_cast<uint64_t>(st.ni);
                if (acc_reserved_tiles_.find(acc_key) != acc_reserved_tiles_.end()) {
                    if (!acquireOnchipReadPorts_(0, 1)) {
                        blocked_onchip_port = true;
                        break;
                    }
                }
            }
            const uint32_t issued = issueMemWriteTagged_(chunk, MemTag::WriteC, epoch);
            if (issued == 0) {
                if (inflight_.size() >= max_out) blocked_outstanding = true;
                break;
            }
            consumeHbmChannelBudget_(now_cycle, hbm_ch, issued);
            st.issued_bytes += issued;
            rem_write_bytes_ = (rem_write_bytes_ >= issued) ? (rem_write_bytes_ - issued) : 0;
            budget -= issued;
            did = true;
            did_mem = true;
        }
    }

    // === Prefetch reads for next tile-seg (optional) ===
    if (prefetch && cfg_.mem_enable && rt_.mem && tile_next_.valid) {
        while (budget > 0) {
            uint64_t pending = 0;
            MemTag tag = MemTag::Generic;
            if (tile_next_.issued_a_bytes < tile_next_.need_a_bytes) {
                pending = tile_next_.need_a_bytes - tile_next_.issued_a_bytes;
                tag = MemTag::ReadA;
            } else if (tile_next_.issued_b_bytes < tile_next_.need_b_bytes) {
                pending = tile_next_.need_b_bytes - tile_next_.issued_b_bytes;
                tag = MemTag::ReadB;
            } else {
                break;
            }

            if (inflight_.size() >= max_out) {
                blocked_outstanding = true;
                break;
            }

            uint32_t chunk = static_cast<uint32_t>(std::min<uint64_t>(cfg_.mem_req_bytes, pending));
            if (chunk == 0) break;
            if (chunk > budget) {
                blocked_budget = true;
                break;
            }

            uint32_t hbm_ch = 0;
            chunk = clampBytesByHbmChannelBudget_(now_cycle, ReqKind::Read, chunk, hbm_ch);
            if (chunk == 0) {
                blocked_hbm_channel_budget = true;
                break;
            }

            const bool use_weight_pool = (tag == MemTag::ReadB && cfg_.weight_bytes > 0);
            bool onchip_spilled = false;
            if (cfg_.onchip_model_enable) {
                if (!acquireOnchipWritePorts_(1, 0)) {
                    blocked_onchip_port = true;
                    break;
                }
                bool spill_budget_blocked_local = false;
                bool bank_conflict_blocked_local = false;
                std::vector<std::pair<uint32_t, uint64_t>>* bank_allocs =
                    (cfg_.onchip_bank_model_enable
                         ? ((tag == MemTag::ReadA) ? &tile_next_.reserved_a_bank_allocs
                                                   : (use_weight_pool ? &tile_next_.reserved_b_weight_bank_allocs
                                                                      : &tile_next_.reserved_b_bank_allocs))
                         : nullptr);
                const bool ok = use_weight_pool
                                    ? reserveWeightBytes_(chunk,
                                                          spill_budget,
                                                          onchip_spilled,
                                                          spill_budget_blocked_local,
                                                          bank_conflict_blocked_local,
                                                          bank_allocs)
                                    : reserveUbBytes_(chunk,
                                                      spill_budget,
                                                      onchip_spilled,
                                                      spill_budget_blocked_local,
                                                      bank_conflict_blocked_local,
                                                      bank_allocs);
                if (!ok) {
                    if (spill_budget_blocked_local) {
                        blocked_spill_budget = true;
                    } else if (bank_conflict_blocked_local) {
                        blocked_onchip_bank_conflict = true;
                    } else {
                        blocked_onchip_capacity = true;
                    }
                    break;
                }
            }

            const uint32_t issued = issueMemReadTagged_(chunk, tag, tile_next_.epoch);
            if (issued == 0) {
                if (cfg_.onchip_model_enable && !onchip_spilled) {
                    if (cfg_.onchip_bank_model_enable) {
                        if (tag == MemTag::ReadA) {
                            rollback_ub_alloc(tile_next_.reserved_a_bank_allocs, chunk);
                        } else if (tag == MemTag::ReadB) {
                            if (use_weight_pool) {
                                rollback_weight_alloc(tile_next_.reserved_b_weight_bank_allocs, chunk);
                            } else {
                                rollback_ub_alloc(tile_next_.reserved_b_bank_allocs, chunk);
                            }
                        }
                    } else {
                        if (use_weight_pool) {
                            releaseWeightBytes_(chunk);
                        } else {
                            releaseUbBytes_(chunk);
                        }
                    }
                }
                if (inflight_.size() >= max_out) blocked_outstanding = true;
                break;
            }
            consumeHbmChannelBudget_(now_cycle, hbm_ch, issued);
            if (cfg_.onchip_model_enable && !onchip_spilled && issued < chunk) {
                const uint64_t rollback = static_cast<uint64_t>(chunk - issued);
                if (cfg_.onchip_bank_model_enable) {
                    if (tag == MemTag::ReadA) {
                        rollback_ub_alloc(tile_next_.reserved_a_bank_allocs, rollback);
                    } else if (tag == MemTag::ReadB) {
                        if (use_weight_pool) {
                            rollback_weight_alloc(tile_next_.reserved_b_weight_bank_allocs, rollback);
                        } else {
                            rollback_ub_alloc(tile_next_.reserved_b_bank_allocs, rollback);
                        }
                    }
                } else {
                    if (use_weight_pool) {
                        releaseWeightBytes_(rollback);
                    } else {
                        releaseUbBytes_(rollback);
                    }
                }
            }
            if (tag == MemTag::ReadA) {
                tile_next_.issued_a_bytes += issued;
                if (cfg_.onchip_model_enable && !onchip_spilled) {
                    tile_next_.reserved_a_bytes += issued;
                }
            } else if (tag == MemTag::ReadB) {
                tile_next_.issued_b_bytes += issued;
                if (cfg_.onchip_model_enable && !onchip_spilled) {
                    if (use_weight_pool) {
                        tile_next_.reserved_b_weight_bytes += issued;
                    } else {
                        tile_next_.reserved_b_bytes += issued;
                    }
                }
            }
            rem_read_bytes_ = (rem_read_bytes_ >= issued) ? (rem_read_bytes_ - issued) : 0;
            budget -= issued;
            did = true;
            did_mem = true;
        }
    }

    // === Compute for current tile-seg (requires reads ready) ===
    const bool cur_reads_ready =
        (!tile_cur_.valid) ||
        (tile_cur_.done_a_bytes >= tile_cur_.need_a_bytes && tile_cur_.done_b_bytes >= tile_cur_.need_b_bytes);
    const bool collective_blocks_compute =
        (!cfg_.collective_overlap_with_compute && (collectivePendingActive_() || did_collective));
    bool onchip_compute_ready = true;
    if (tile_cur_.valid && cur_reads_ready && tile_cur_.rem_compute_cycles > 0 && !collective_blocks_compute && cfg_.onchip_model_enable) {
        if (!tile_cur_.acc_reserved) {
            bool acc_spilled = false;
            bool spill_budget_blocked_local = false;
            bool bank_conflict_blocked_local = false;
            if (!reserveAccTile_(tile_cur_.mi,
                                 tile_cur_.ni,
                                 spill_budget,
                                 acc_spilled,
                                 spill_budget_blocked_local,
                                 bank_conflict_blocked_local)) {
                onchip_compute_ready = false;
                if (spill_budget_blocked_local) {
                    blocked_spill_budget = true;
                } else if (bank_conflict_blocked_local) {
                    blocked_onchip_bank_conflict = true;
                } else {
                    blocked_onchip_capacity = true;
                }
            } else {
                tile_cur_.acc_reserved = true;
            }
        }
        if (onchip_compute_ready) {
            const uint32_t ub_ports_needed =
                std::max<uint32_t>(1u, ((tile_a_bytes_ > 0) ? 1u : 0u) + ((tile_b_bytes_ > 0) ? 1u : 0u));
            if (!acquireOnchipReadPorts_(ub_ports_needed, 1)) {
                onchip_compute_ready = false;
                blocked_onchip_port = true;
            }
        }
    }

    if (tile_cur_.valid &&
        cur_reads_ready &&
        tile_cur_.rem_compute_cycles > 0 &&
        !collective_blocks_compute &&
        onchip_compute_ready) {
        if (rem_compute_cycles_ > 0) rem_compute_cycles_--;
        tensor_compute_cycles_total_ += 1;
        if (tile_cur_.rem_compute_math_cycles > 0) {
            tile_cur_.rem_compute_math_cycles--;
            tensor_compute_math_cycles_total_ += 1;

            const uint64_t per = effectivePeakMacsPerCycle_();
            const uint64_t done = (rem_macs_ >= per) ? per : rem_macs_;
            tensor_mac_ops_total_ += done;
            rem_macs_ = (rem_macs_ >= done) ? (rem_macs_ - done) : 0;
        } else if (tile_cur_.rem_compute_pipeline_cycles > 0) {
            tile_cur_.rem_compute_pipeline_cycles--;
            tensor_compute_pipeline_cycles_total_ += 1;
        } else if (tile_cur_.rem_compute_wavefront_cycles > 0) {
            tile_cur_.rem_compute_wavefront_cycles--;
            tensor_mxu_wavefront_cycles_total_ += 1;
        }
        tile_cur_.rem_compute_cycles =
            tile_cur_.rem_compute_math_cycles + tile_cur_.rem_compute_pipeline_cycles + tile_cur_.rem_compute_wavefront_cycles;

        did = true;
        did_compute = true;
    } else if (tile_cur_.valid && cur_reads_ready && tile_cur_.rem_compute_cycles > 0 && collective_blocks_compute) {
        tensor_stall_collective_cycles_total_ += 1;
    }

    // === Tile-seg complete → advance ===
    if (tile_cur_.valid && cur_reads_ready && tile_cur_.rem_compute_cycles == 0) {
        tile_seg_done_ += 1;

        // M15: materialize keep-a/keep-b as real on-chip residency (not just reduced DRAM reads).
        if (cfg_.onchip_model_enable) {
            if (cfg_.dataflow == "is" && tile_keep_a_ && tile_cur_.ni == 0) {
                const uint64_t key = (static_cast<uint64_t>(tile_cur_.mi) << 32) | static_cast<uint64_t>(tile_cur_.ki);
                if (tile_cur_.reserved_a_bytes > 0 || !tile_cur_.reserved_a_bank_allocs.empty()) {
                    ResidentTileAlloc& alloc = a_resident_tiles_[key];
                    alloc.pool = OnchipPoolKind::Ub;
                    alloc.bytes += tile_cur_.reserved_a_bytes;
                    for (const auto& p : tile_cur_.reserved_a_bank_allocs) {
                        alloc.bank_allocs.emplace_back(p);
                    }
                    tile_cur_.reserved_a_bytes = 0;
                    tile_cur_.reserved_a_bank_allocs.clear();
                    if (static_cast<uint64_t>(a_resident_tiles_.size()) > tensor_onchip_a_resident_tiles_max_) {
                        tensor_onchip_a_resident_tiles_max_ = static_cast<uint64_t>(a_resident_tiles_.size());
                    }
                }
            }
            if (cfg_.dataflow == "ws" && tile_keep_b_ && tile_cur_.mi == 0) {
                const uint64_t key = (static_cast<uint64_t>(tile_cur_.ni) << 32) | static_cast<uint64_t>(tile_cur_.ki);
                const bool b_is_weight = (cfg_.weight_bytes > 0);
                const bool has_b_alloc = b_is_weight
                                            ? (tile_cur_.reserved_b_weight_bytes > 0 || !tile_cur_.reserved_b_weight_bank_allocs.empty())
                                            : (tile_cur_.reserved_b_bytes > 0 || !tile_cur_.reserved_b_bank_allocs.empty());
                if (has_b_alloc) {
                    ResidentTileAlloc& alloc = b_resident_tiles_[key];
                    alloc.pool = b_is_weight ? OnchipPoolKind::Weight : OnchipPoolKind::Ub;
                    if (b_is_weight) {
                        alloc.bytes += tile_cur_.reserved_b_weight_bytes;
                        for (const auto& p : tile_cur_.reserved_b_weight_bank_allocs) {
                            alloc.bank_allocs.emplace_back(p);
                        }
                        tile_cur_.reserved_b_weight_bytes = 0;
                        tile_cur_.reserved_b_weight_bank_allocs.clear();
                    } else {
                        alloc.bytes += tile_cur_.reserved_b_bytes;
                        for (const auto& p : tile_cur_.reserved_b_bank_allocs) {
                            alloc.bank_allocs.emplace_back(p);
                        }
                        tile_cur_.reserved_b_bytes = 0;
                        tile_cur_.reserved_b_bank_allocs.clear();
                    }
                    if (static_cast<uint64_t>(b_resident_tiles_.size()) > tensor_onchip_b_resident_tiles_max_) {
                        tensor_onchip_b_resident_tiles_max_ = static_cast<uint64_t>(b_resident_tiles_.size());
                    }
                }
            }
        }

        if (cfg_.onchip_bank_model_enable) {
            releaseUbBankAllocs_(tile_cur_.reserved_a_bank_allocs);
            releaseUbBankAllocs_(tile_cur_.reserved_b_bank_allocs);
            releaseWeightBankAllocs_(tile_cur_.reserved_b_weight_bank_allocs);
        } else {
            releaseUbBytes_(tile_cur_.reserved_a_bytes);
            releaseUbBytes_(tile_cur_.reserved_b_bytes);
            releaseWeightBytes_(tile_cur_.reserved_b_weight_bytes);
        }

        // Release resident tiles at their last reuse point.
        if (cfg_.onchip_model_enable) {
            if (cfg_.dataflow == "is" && tile_keep_a_ && (tile_cur_.ni + 1u == tile_nt_)) {
                const uint64_t key = (static_cast<uint64_t>(tile_cur_.mi) << 32) | static_cast<uint64_t>(tile_cur_.ki);
                auto it = a_resident_tiles_.find(key);
                if (it != a_resident_tiles_.end()) {
                    if (cfg_.onchip_bank_model_enable) {
                        releaseUbBankAllocs_(it->second.bank_allocs);
                    } else {
                        releaseUbBytes_(it->second.bytes);
                    }
                    a_resident_tiles_.erase(it);
                }
            }
            if (cfg_.dataflow == "ws" && tile_keep_b_ && (tile_cur_.mi + 1u == tile_mt_)) {
                const uint64_t key = (static_cast<uint64_t>(tile_cur_.ni) << 32) | static_cast<uint64_t>(tile_cur_.ki);
                auto it = b_resident_tiles_.find(key);
                if (it != b_resident_tiles_.end()) {
                    if (it->second.pool == OnchipPoolKind::Weight) {
                        if (cfg_.onchip_bank_model_enable) {
                            releaseWeightBankAllocs_(it->second.bank_allocs);
                        } else {
                            releaseWeightBytes_(it->second.bytes);
                        }
                    } else {
                        if (cfg_.onchip_bank_model_enable) {
                            releaseUbBankAllocs_(it->second.bank_allocs);
                        } else {
                            releaseUbBytes_(it->second.bytes);
                        }
                    }
                    b_resident_tiles_.erase(it);
                }
            }
        }
        if (tile_cur_.ki + 1u == tile_kt_) {
            scheduleWriteback_(tile_cur_.mi, tile_cur_.ni);
            if (!cfg_.mem_enable || !rt_.mem) {
                releaseAccTile_(tile_cur_.mi, tile_cur_.ni);
            }
        }

        // Advance current seg.
        if (tile_next_.valid) {
            tile_cur_ = tile_next_;
            tile_next_ = TileSegState{};
        } else {
            tile_cur_ = TileSegState{};
            (void)generateNextTileSeg_(tile_cur_);
        }
        // Maintain a single lookahead seg for prefetch.
        if (prefetch && !tile_next_.valid) {
            (void)generateNextTileSeg_(tile_next_);
        }
        did = true;
    }

    retireCompletedWritebacks_();

    // === Iteration complete ===
    if (iter_active_ &&
        tile_seg_done_ >= tile_count_per_iter_ &&
        rem_read_bytes_ == 0 &&
        rem_write_bytes_ == 0 &&
        rem_compute_cycles_ == 0 &&
        !collectivePendingActive_() &&
        tile_writeback_queue_.empty() &&
        inflight_.empty()) {
        iter_done_++;
        iter_active_ = false;
        compute_started_ = false;
        tile_mode_active_ = false;
        tile_cur_ = TileSegState{};
        tile_next_ = TileSegState{};
        tile_writeback_queue_.clear();
        tile_writebacks_.clear();
        acc_reserved_tiles_.clear();
        a_resident_tiles_.clear();
        b_resident_tiles_.clear();
        onchip_ub_occupancy_bytes_ = 0;
        onchip_weight_occupancy_bytes_ = 0;
        onchip_acc_occupancy_bytes_ = 0;
        std::fill(onchip_ub_bank_occupancy_bytes_.begin(), onchip_ub_bank_occupancy_bytes_.end(), 0ull);
        std::fill(onchip_weight_bank_occupancy_bytes_.begin(), onchip_weight_bank_occupancy_bytes_.end(), 0ull);
        std::fill(onchip_acc_bank_occupancy_bytes_.begin(), onchip_acc_bank_occupancy_bytes_.end(), 0ull);
        std::fill(onchip_ub_bank_queue_occupancy_.begin(), onchip_ub_bank_queue_occupancy_.end(), 0u);
        std::fill(onchip_weight_bank_queue_occupancy_.begin(), onchip_weight_bank_queue_occupancy_.end(), 0u);
        std::fill(onchip_acc_bank_queue_occupancy_.begin(), onchip_acc_bank_queue_occupancy_.end(), 0u);
        onchip_ub_bank_rr_ = 0;
        onchip_weight_bank_rr_ = 0;
        onchip_acc_bank_rr_ = 0;
        if (step_gated_ && close_step_on_iter_done_) {
            step_open_ = false;
        }
    }

    if (!did && (iter_active_ || !inflight_.empty())) {
        tensor_dma_stall_cycles_total_ += 1;
        const bool pending_mem_issue =
            (tile_cur_.valid && ((tile_cur_.issued_a_bytes < tile_cur_.need_a_bytes) || (tile_cur_.issued_b_bytes < tile_cur_.need_b_bytes))) ||
            (prefetch && tile_next_.valid &&
             ((tile_next_.issued_a_bytes < tile_next_.need_a_bytes) || (tile_next_.issued_b_bytes < tile_next_.need_b_bytes))) ||
            (!tile_writeback_queue_.empty() &&
             ([&]() -> bool {
                 const uint64_t epoch = tile_writeback_queue_.front();
                 auto it = tile_writebacks_.find(epoch);
                 return it != tile_writebacks_.end() && it->second.issued_bytes < it->second.total_bytes;
             })());

        if (blocked_onchip_port) {
            tensor_stall_onchip_port_cycles_total_ += 1;
        } else if (blocked_spill_budget) {
            tensor_stall_spill_budget_cycles_total_ += 1;
        } else if (blocked_onchip_bank_conflict) {
            tensor_stall_onchip_bank_conflict_cycles_total_ += 1;
        } else if (blocked_onchip_capacity) {
            tensor_stall_onchip_capacity_cycles_total_ += 1;
        } else if (blocked_hbm_channel_budget && pending_mem_issue) {
            tensor_stall_dma_hbm_channel_budget_cycles_total_ += 1;
        } else if (blocked_outstanding && pending_mem_issue) {
            tensor_stall_mem_outstanding_cycles_total_ += 1;
        } else if (blocked_budget && pending_mem_issue) {
            tensor_stall_dma_budget_cycles_total_ += 1;
        } else if (tile_cur_.valid && !cur_reads_ready && tile_cur_.rem_compute_cycles > 0) {
            tensor_stall_wait_read_cycles_total_ += 1;
        } else if (rem_compute_cycles_ == 0 && (!tile_writeback_queue_.empty() || !inflight_.empty())) {
            tensor_stall_wait_write_cycles_total_ += 1;
        }
    }

    if (cfg_.collective_overlap_with_compute && did_compute && did_collective) {
        tensor_overlap_compute_collective_cycles_total_ += 1;
    }
    if (did_compute && did_mem) {
        tensor_overlap_compute_mem_cycles_total_ += 1;
    }

    if (did) active_cycles_++;
    return did;
}

bool TensorWorkload::onClockTickProgramM7_(uint64_t now_cycle) {
    bool did = false;
    bool did_mem = false;
    bool did_compute = false;
    bool did_collective = false;
    bool did_comm = false;
    bool noc_budget_blocked = false;
    uint64_t noc_budget = (cfg_.noc_bandwidth_bytes_per_cycle > 0)
                              ? cfg_.noc_bandwidth_bytes_per_cycle
                              : std::numeric_limits<uint64_t>::max();
    resetOnchipCycleState_(now_cycle);

    auto issue_noc = [&]() {
        issueNocTraffic_(now_cycle, noc_budget, did, did_collective, did_comm, noc_budget_blocked);
        if (noc_budget_blocked && !did_collective && !did_comm) {
            tensor_stall_noc_budget_cycles_total_ += 1;
        }
    };

    auto program_ub_total_occupancy_bytes = [&]() -> uint64_t {
        if (!program_addr_aware_enable_) {
            uint64_t sum = 0;
            for (const uint64_t v : program_ub_reserved_bytes_by_buf_) {
                sum = saturatingAddU64_(sum, v);
            }
            for (const uint64_t v : program_ub_valid_bytes_by_buf_) {
                sum = saturatingAddU64_(sum, v);
            }
            return sum;
        }
        uint64_t sum = 0;
        for (const auto& mp : program_ub_regions_by_buf_) {
            for (const auto& kv : mp) {
                sum = saturatingAddU64_(sum, kv.second.reserved_bytes);
                sum = saturatingAddU64_(sum, kv.second.valid_bytes);
            }
        }
        return sum;
    };
    auto update_program_ub_occupancy_max = [&]() {
        const uint64_t occ = program_ub_total_occupancy_bytes();
        if (occ > tensor_program_ub_occupancy_bytes_max_) {
            tensor_program_ub_occupancy_bytes_max_ = occ;
        }
    };

    // Step-gated mode: only run when a step is open, but still flush credit-return traffic.
    if (step_gated_ && !step_open_) {
        issue_noc();
        if (did) active_cycles_++;
        return did;
    }

    if (!started_) {
        if (now_cycle < cfg_.start_cycle) {
            issue_noc();
            if (did) active_cycles_++;
            return did;
        }
        started_ = true;
    }

    serviceCollectiveBarrier_(now_cycle);

    // Stop after requested program iterations (0 = run forever).
    if (cfg_.iterations > 0 && program_iter_done_ >= cfg_.iterations) {
        issue_noc();
        if (did) active_cycles_++;
        return did;
    }

    if (program_ops_.empty()) {
        // Program mode with an empty program is allowed when strict=0 (acts like idle workload).
        issue_noc();
        if (did) active_cycles_++;
        return did;
    }

    const bool collective_blocks_compute =
        (!cfg_.collective_overlap_with_compute && (program_coll_slot_.active || collectivePendingActive_()));

    // === Execute: DMA ===
    if (program_dma_read_slot_.active || program_dma_write_slot_.active) {
        tensor_program_dma_busy_cycles_total_ += 1;
        tensor_dma_cycles_total_ += 1;

        const uint64_t kUncapped = std::numeric_limits<uint64_t>::max();
        uint64_t budget = dmaBudgetBytesPerCycle_(now_cycle);
        const bool capped = (budget != kUncapped);
        const bool budget_initially_zero = capped && (budget == 0);
        const auto max_out = static_cast<size_t>(cfg_.mem_max_outstanding);

        bool program_mem_stall_marked = false;
        bool budget_stall_marked = false;
        bool outstanding_stall_marked = false;
        bool onchip_port_stall_marked = false;
        bool onchip_bank_stall_marked = false;
        bool hbm_channel_stall_marked = false;
        auto mark_program_mem_stall = [&]() {
            if (!program_mem_stall_marked) {
                tensor_program_mem_stall_cycles_total_ += 1;
                program_mem_stall_marked = true;
            }
        };
        auto mark_budget_stall = [&]() {
            if (!budget_stall_marked) {
                tensor_stall_dma_budget_cycles_total_ += 1;
                budget_stall_marked = true;
            }
            mark_program_mem_stall();
        };
        auto mark_outstanding_stall = [&]() {
            if (!outstanding_stall_marked) {
                tensor_stall_mem_outstanding_cycles_total_ += 1;
                outstanding_stall_marked = true;
            }
            mark_program_mem_stall();
        };
        auto mark_onchip_port_stall = [&]() {
            if (!onchip_port_stall_marked) {
                tensor_stall_onchip_port_cycles_total_ += 1;
                onchip_port_stall_marked = true;
            }
            mark_program_mem_stall();
        };
        auto mark_onchip_bank_stall = [&]() {
            if (!onchip_bank_stall_marked) {
                tensor_stall_onchip_bank_conflict_cycles_total_ += 1;
                onchip_bank_stall_marked = true;
            }
            mark_program_mem_stall();
        };
        auto mark_hbm_channel_stall = [&]() {
            if (!hbm_channel_stall_marked) {
                tensor_stall_dma_hbm_channel_budget_cycles_total_ += 1;
                hbm_channel_stall_marked = true;
            }
            mark_program_mem_stall();
        };

        auto try_mark_ub_bank_access = [&](uint64_t tag_seed) -> bool {
            if (!cfg_.onchip_model_enable) return true;
            if (!cfg_.onchip_bank_model_enable) return true;
            const uint32_t bank = selectUbBank_(tag_seed);
            if (bank >= onchip_ub_bank_queue_occupancy_.size()) return true;

            if (cfg_.ub_bank_conflict_mode == "queue") {
                if (onchip_ub_bank_queue_occupancy_[bank] >= cfg_.bank_queue_depth) return false;
                onchip_ub_bank_queue_occupancy_[bank] += 1;
                updateBankQueueOccupancyMax_();
                return true;
            }

            // hard: only 1 access per bank per cycle
            if (onchip_ub_bank_queue_occupancy_[bank] > 0) return false;
            onchip_ub_bank_queue_occupancy_[bank] = 1;
            updateBankQueueOccupancyMax_();
            return true;
        };

        auto service_dma_slot = [&](ProgramDmaSlot& slot, MemTag tag) {
            if (!slot.active) return;

            // M29: optional burst/setup model. When enabled, a slot issues at most one burst at a time,
            // and pays a fixed setup cost before each burst can start issuing bytes.
            const bool burst_enable = (cfg_.dma_burst_bytes > 0);
            if (burst_enable) {
                if (slot.setup_cycles_rem > 0) {
                    slot.setup_cycles_rem -= 1;
                    return;
                }
                if (slot.burst_bytes_rem == 0 && slot.issued_bytes < slot.total_bytes) {
                    slot.burst_bytes_rem =
                        std::min<uint64_t>(cfg_.dma_burst_bytes, slot.total_bytes - slot.issued_bytes);
                    if (cfg_.dma_setup_cycles > 0) {
                        slot.setup_cycles_rem = cfg_.dma_setup_cycles;
                        // Count this cycle as setup.
                        slot.setup_cycles_rem -= 1;
                        return;
                    }
                }
            }

            // M29: optional per-cycle issue-lane and per-slot inflight limits.
            const uint32_t engines_cfg = slot.is_read ? cfg_.dma_read_engines : cfg_.dma_write_engines;
            const uint32_t engines = (engines_cfg > 0) ? engines_cfg : std::numeric_limits<uint32_t>::max();
            const uint64_t slot_inflight_cap =
                (engines_cfg > 0 && cfg_.dma_max_inflight_per_engine > 0)
                    ? (static_cast<uint64_t>(engines_cfg) * static_cast<uint64_t>(cfg_.dma_max_inflight_per_engine))
                    : 0ull;

            bool slot_issued_this_cycle = false;
            uint32_t reqs_issued_this_cycle = 0;
            while (slot.issued_bytes < slot.total_bytes && reqs_issued_this_cycle < engines) {
                const uint64_t rem = slot.total_bytes - slot.issued_bytes;
                uint32_t want = static_cast<uint32_t>(std::min<uint64_t>(cfg_.mem_req_bytes, rem));
                if (burst_enable && slot.burst_bytes_rem > 0) {
                    want = static_cast<uint32_t>(std::min<uint64_t>(want, slot.burst_bytes_rem));
                }
                if (want == 0) break;
                if (capped) {
                    if (budget == 0) {
                        if (budget_initially_zero) {
                            mark_budget_stall();
                        }
                        break;
                    }
                    want = static_cast<uint32_t>(std::min<uint64_t>(want, budget));
                    if (want == 0) {
                        if (budget_initially_zero) {
                            mark_budget_stall();
                        }
                        break;
                    }
                }
                if (inflight_.size() >= max_out) {
                    mark_outstanding_stall();
                    break;
                }
                if (slot_inflight_cap > 0 && static_cast<uint64_t>(slot.inflight_reqs) >= slot_inflight_cap) {
                    mark_outstanding_stall();
                    break;
                }

                uint32_t hbm_ch = 0;
                want = clampBytesByHbmChannelBudget_(
                    now_cycle,
                    slot.is_read ? ReqKind::Read : ReqKind::Write,
                    want,
                    hbm_ch);
                if (want == 0) {
                    // Mirror "budget_initially_zero" semantics: only count stall when this slot
                    // cannot issue any bytes in this cycle due to channel budget contention.
                    if (!slot_issued_this_cycle) {
                        mark_hbm_channel_stall();
                    }
                    break;
                }

                // M19: program-mode on-chip UB port + bank conflict modeling.
                if (cfg_.onchip_model_enable) {
                    if (slot.is_read) {
                        // DRAM -> UB: consumes UB write ports.
                        if (!acquireOnchipWritePorts_(1, 0)) {
                            mark_onchip_port_stall();
                            break;
                        }
                    } else {
                        // UB -> DRAM: consumes UB read ports.
                        if (!acquireOnchipReadPorts_(1, 0)) {
                            mark_onchip_port_stall();
                            break;
                        }
                    }
                    const uint64_t addr_seed = (slot.ub_addr_present ? slot.ub_addr : 0ull) + slot.issued_bytes;
                    const uint64_t tag_seed =
                        (static_cast<uint64_t>(slot.buf) << 48) ^ addr_seed ^ (static_cast<uint64_t>(slot.epoch) << 1);
                    if (!try_mark_ub_bank_access(tag_seed)) {
                        mark_onchip_bank_stall();
                        break;
                    }
                }

                uint32_t issued = 0;
                if (slot.is_read) {
                    issued = issueMemReadTagged_(want, tag, slot.epoch);
                } else {
                    issued = issueMemWriteTagged_(want, tag, slot.epoch);
                }
                if (issued == 0) {
                    mark_outstanding_stall();
                    break;
                }

                slot.issued_bytes += static_cast<uint64_t>(issued);
                slot.inflight_reqs += 1;
                reqs_issued_this_cycle += 1;
                if (burst_enable && slot.burst_bytes_rem > 0) {
                    slot.burst_bytes_rem = (slot.burst_bytes_rem >= issued) ? (slot.burst_bytes_rem - issued) : 0;
                }
                consumeHbmChannelBudget_(now_cycle, hbm_ch, issued);
                did = true;
                did_mem = true;
                slot_issued_this_cycle = true;
                if (capped) {
                    budget = (budget >= issued) ? (budget - issued) : 0;
                    if (budget == 0) break;
                }

                // M29: one burst at a time; next burst (with setup) begins next cycle.
                if (burst_enable && slot.burst_bytes_rem == 0 && slot.issued_bytes < slot.total_bytes) {
                    break;
                }
            }

            if (slot.done_bytes >= slot.total_bytes) {
                if (slot.is_read) {
                    const uint64_t total = slot.total_bytes;
                    const uint32_t buf = slot.buf;
                    if (!program_addr_aware_enable_) {
                        if (buf < program_ub_reserved_bytes_by_buf_.size() && buf < program_ub_valid_bytes_by_buf_.size()) {
                            auto& rsv = program_ub_reserved_bytes_by_buf_[buf];
                            auto& val = program_ub_valid_bytes_by_buf_[buf];
                            rsv = (rsv >= total) ? (rsv - total) : 0;
                            val = saturatingAddU64_(val, total);
                            update_program_ub_occupancy_max();
                        }
                    } else if (buf < program_ub_regions_by_buf_.size() && slot.ub_addr_present) {
                        auto& mp = program_ub_regions_by_buf_[buf];
                        auto it = mp.find(slot.ub_addr);
                        if (it != mp.end()) {
                            auto& reg = it->second;
                            reg.reserved_bytes = (reg.reserved_bytes >= total) ? (reg.reserved_bytes - total) : 0;
                            reg.valid_bytes = saturatingAddU64_(reg.valid_bytes, total);
                            if (reg.size_bytes > 0 && reg.valid_bytes > reg.size_bytes) {
                                reg.valid_bytes = reg.size_bytes;
                            }
                            update_program_ub_occupancy_max();
                        }
                    }
                }

                slot = ProgramDmaSlot{};
                tensor_program_ops_total_ += 1;
            }
        };

        // Shared DMA budget across read+write slots: issue reads first, then writes.
        service_dma_slot(program_dma_read_slot_, MemTag::ProgramDmaRead);
        service_dma_slot(program_dma_write_slot_, MemTag::ProgramDmaWrite);
    }

    // === Execute: MXU (compute placeholder) ===
    if (program_mxu_slot_.active) {
        if (collective_blocks_compute) {
            tensor_stall_collective_cycles_total_ += 1;
        } else if (program_mxu_slot_.rem_cycles > 0 ||
                   program_mxu_slot_.ub_read_a_bytes_rem > 0 ||
                   program_mxu_slot_.ub_read_b_bytes_rem > 0 ||
                   program_mxu_slot_.ub_write_bytes_rem > 0) {
            bool ok = true;
            bool onchip_port_stall_marked = false;
            bool onchip_bank_stall_marked = false;
            auto mark_onchip_port_stall = [&]() {
                if (!onchip_port_stall_marked) {
                    tensor_stall_onchip_port_cycles_total_ += 1;
                    onchip_port_stall_marked = true;
                }
            };
            auto mark_onchip_bank_stall = [&]() {
                if (!onchip_bank_stall_marked) {
                    tensor_stall_onchip_bank_conflict_cycles_total_ += 1;
                    onchip_bank_stall_marked = true;
                }
            };

            auto try_acquire_ub_banks2 = [&](uint64_t seed0, uint64_t seed1) -> bool {
                if (!cfg_.onchip_model_enable) return true;
                if (!cfg_.onchip_bank_model_enable) return true;
                const uint32_t bank0 = selectUbBank_(seed0);
                const uint32_t bank1 = selectUbBank_(seed1);
                if (bank0 >= onchip_ub_bank_queue_occupancy_.size()) return true;
                if (bank1 >= onchip_ub_bank_queue_occupancy_.size()) return true;
                const uint32_t depth = std::max<uint32_t>(cfg_.bank_queue_depth, 1u);

                if (cfg_.ub_bank_conflict_mode == "queue") {
                    if (bank0 == bank1) {
                        const uint32_t occ = onchip_ub_bank_queue_occupancy_[bank0];
                        if (occ + 2u > depth) return false;
                        onchip_ub_bank_queue_occupancy_[bank0] = occ + 2u;
                    } else {
                        const uint32_t occ0 = onchip_ub_bank_queue_occupancy_[bank0];
                        const uint32_t occ1 = onchip_ub_bank_queue_occupancy_[bank1];
                        if (occ0 + 1u > depth) return false;
                        if (occ1 + 1u > depth) return false;
                        onchip_ub_bank_queue_occupancy_[bank0] = occ0 + 1u;
                        onchip_ub_bank_queue_occupancy_[bank1] = occ1 + 1u;
                    }
                    updateBankQueueOccupancyMax_();
                    return true;
                }

                // hard: only 1 access per bank per cycle
                if (bank0 == bank1) return false;
                if (onchip_ub_bank_queue_occupancy_[bank0] > 0) return false;
                if (onchip_ub_bank_queue_occupancy_[bank1] > 0) return false;
                onchip_ub_bank_queue_occupancy_[bank0] = 1;
                onchip_ub_bank_queue_occupancy_[bank1] = 1;
                updateBankQueueOccupancyMax_();
                return true;
            };

            auto try_acquire_acc_bank = [&](uint64_t seed) -> bool {
                if (!cfg_.onchip_model_enable) return true;
                if (!cfg_.onchip_bank_model_enable) return true;
                const uint32_t bank = selectAccBank_(seed);
                if (bank >= onchip_acc_bank_queue_occupancy_.size()) return true;
                const uint32_t depth = std::max<uint32_t>(cfg_.bank_queue_depth, 1u);

                if (cfg_.acc_bank_conflict_mode == "queue") {
                    if (onchip_acc_bank_queue_occupancy_[bank] >= depth) return false;
                    onchip_acc_bank_queue_occupancy_[bank] += 1;
                    updateBankQueueOccupancyMax_();
                    return true;
                }

                // hard: only 1 access per bank per cycle
                if (onchip_acc_bank_queue_occupancy_[bank] > 0) return false;
                onchip_acc_bank_queue_occupancy_[bank] = 1;
                updateBankQueueOccupancyMax_();
                return true;
            };

            if (cfg_.onchip_model_enable) {
                // Conservative per-cycle demand: 2x UB read + 1x ACC write.
                if (!acquireOnchipReadPorts_(2, 0)) {
                    mark_onchip_port_stall();
                    ok = false;
                } else if (!acquireOnchipWritePorts_(0, 1)) {
                    mark_onchip_port_stall();
                    ok = false;
                }

                if (ok) {
                    const uint64_t tag_base =
                        (static_cast<uint64_t>(program_mxu_slot_.buf) << 48) ^
                        (static_cast<uint64_t>(program_pc_) << 16) ^
                        (static_cast<uint64_t>(program_iter_done_) << 1) ^
                        cfg_.seed_base;
                    if (!try_acquire_ub_banks2(tag_base ^ 0x1001ull, tag_base ^ 0x1002ull)) {
                        mark_onchip_bank_stall();
                        ok = false;
                    } else if (!try_acquire_acc_bank(tag_base ^ 0x2001ull)) {
                        mark_onchip_bank_stall();
                        ok = false;
                    }
                }
            }

            if (ok) {
                const bool have_math = (program_mxu_slot_.rem_cycles > 0);
                const bool have_io =
                    (program_mxu_slot_.ub_read_a_bytes_rem > 0) ||
                    (program_mxu_slot_.ub_read_b_bytes_rem > 0) ||
                    (program_mxu_slot_.ub_write_bytes_rem > 0);

                tensor_program_mxu_busy_cycles_total_ += 1;
                tensor_compute_cycles_total_ += 1;

                if (have_math) {
                    tensor_compute_math_cycles_total_ += 1;
                    tensor_mac_ops_total_ += effectivePeakMacsPerCycle_();
                    program_mxu_slot_.rem_cycles -= 1;
                }

                if (have_io) {
                    tensor_mxu_io_busy_cycles_total_ += 1;
                    const uint64_t a_bpc = cfg_.mxu_a_bytes_per_cycle;
                    const uint64_t b_bpc = cfg_.mxu_b_bytes_per_cycle;
                    const uint64_t c_bpc = cfg_.mxu_c_bytes_per_cycle;
                    auto consume = [&](uint64_t& rem, uint64_t bpc) {
                        if (rem == 0) return;
                        const uint64_t cut = (bpc > 0) ? std::min<uint64_t>(rem, bpc) : rem;
                        rem -= cut;
                    };
                    consume(program_mxu_slot_.ub_read_a_bytes_rem, a_bpc);
                    consume(program_mxu_slot_.ub_read_b_bytes_rem, b_bpc);
                    consume(program_mxu_slot_.ub_write_bytes_rem, c_bpc);
                }

                did = true;
                did_compute = true;
            }
        }
        if (program_mxu_slot_.active &&
            program_mxu_slot_.rem_cycles == 0 &&
            program_mxu_slot_.ub_read_a_bytes_rem == 0 &&
            program_mxu_slot_.ub_read_b_bytes_rem == 0 &&
            program_mxu_slot_.ub_write_bytes_rem == 0) {
            const uint64_t w = program_mxu_slot_.ub_write_bytes;
            const uint64_t rsv = program_mxu_slot_.ub_write_reserved_bytes;
            const uint32_t buf = program_mxu_slot_.buf;
            if (!program_addr_aware_enable_) {
                if (buf < program_ub_reserved_bytes_by_buf_.size() && buf < program_ub_valid_bytes_by_buf_.size()) {
                    auto& rsv_bytes = program_ub_reserved_bytes_by_buf_[buf];
                    auto& val_bytes = program_ub_valid_bytes_by_buf_[buf];
                    if (rsv > 0) {
                        rsv_bytes = (rsv_bytes >= rsv) ? (rsv_bytes - rsv) : 0;
                    }
                    if (w > 0) {
                        val_bytes = saturatingAddU64_(val_bytes, w);
                    }
                    update_program_ub_occupancy_max();
                }
            } else if (buf < program_ub_regions_by_buf_.size() && program_mxu_slot_.ub_write_addr_present) {
                auto& mp = program_ub_regions_by_buf_[buf];
                auto it = mp.find(program_mxu_slot_.ub_write_addr);
                if (it != mp.end()) {
                    auto& reg = it->second;
                    if (rsv > 0) {
                        reg.reserved_bytes = (reg.reserved_bytes >= rsv) ? (reg.reserved_bytes - rsv) : 0;
                    }
                    if (w > 0) {
                        reg.valid_bytes = saturatingAddU64_(reg.valid_bytes, w);
                        if (reg.size_bytes > 0 && reg.valid_bytes > reg.size_bytes) {
                            reg.valid_bytes = reg.size_bytes;
                        }
                    }
                    update_program_ub_occupancy_max();
                }
            }
            program_mxu_slot_ = ProgramMxuSlot{};
            tensor_program_ops_total_ += 1;
        }
    }

    // === Execute: Vector ===
    if (program_vec_slot_.active) {
        if (collective_blocks_compute) {
            tensor_stall_collective_cycles_total_ += 1;
        } else if (program_vec_slot_.rem_cycles > 0) {
            tensor_program_vec_busy_cycles_total_ += 1;
            tensor_vector_cycles_total_ += 1;
            program_vec_slot_.rem_cycles -= 1;
            did = true;
            did_compute = true;
        }
        if (program_vec_slot_.active && program_vec_slot_.rem_cycles == 0) {
            program_vec_slot_ = ProgramVecSlot{};
            tensor_program_ops_total_ += 1;
        }
    }

    // === Execute: Collective/Comm/credit-return ===
    issue_noc();
    if (program_coll_slot_.active) {
        tensor_program_coll_busy_cycles_total_ += 1;
        bool done = !collectivePendingActive_();
        if (done && program_coll_slot_.blocking && cfg_.collective_blocking && collective_epoch_active_) {
            tensor_stall_collective_cycles_total_ += 1;
            done = false;
        }
        if (done) {
            program_coll_slot_ = ProgramCollSlot{};
            tensor_program_ops_total_ += 1;
        }
    }

    if (cfg_.collective_overlap_with_compute && did_compute && did_collective) {
        tensor_overlap_compute_collective_cycles_total_ += 1;
    }
    if (did_compute && did_mem) {
        tensor_overlap_compute_mem_cycles_total_ += 1;
    }
    if (did_mem || did_compute || did_collective || did_comm) {
        tensor_program_any_busy_cycles_total_ += 1;
    }

    // === Fence ===
    if (program_fence_pending_) {
        bool ok = true;
        if (program_dma_read_slot_.active || program_dma_write_slot_.active || program_mxu_slot_.active || program_vec_slot_.active ||
            program_coll_slot_.active)
            ok = false;
        if (!inflight_.empty()) ok = false;
        if (collectivePendingActive_()) ok = false;
        if (ok) {
            program_fence_pending_ = false;
            tensor_program_fence_count_total_ += 1;
            tensor_program_ops_total_ += 1;
        } else {
            tensor_program_fence_wait_cycles_total_ += 1;
        }
    }

    // === Issue ===
    if (!program_fence_pending_) {
        const uint32_t ub_bufs = std::max<uint32_t>(cfg_.program_ub_buffers, 1u);
        const uint64_t ub_part =
            (program_addr_aware_enable_ && ub_bufs > 0) ? (cfg_.ub_bytes / static_cast<uint64_t>(ub_bufs)) : 0ull;
        auto clear_valid_in_buf = [&](uint32_t buf) {
            if (buf >= program_ub_regions_by_buf_.size()) return;
            auto& mp = program_ub_regions_by_buf_[buf];
            for (auto& kv : mp) {
                kv.second.valid_bytes = 0;
            }
        };
        auto get_or_create_region = [&](uint32_t buf, uint64_t addr, uint64_t size_bytes) -> ProgramUbRegion* {
            if (buf >= program_ub_regions_by_buf_.size()) return nullptr;
            auto& mp = program_ub_regions_by_buf_[buf];
            auto it = mp.find(addr);
            if (it == mp.end()) {
                auto ins = mp.emplace(addr, ProgramUbRegion{size_bytes, 0ull, 0ull});
                it = ins.first;
            } else if (it->second.size_bytes != size_bytes) {
                if (cfg_.strict && rt_.log) {
                    rt_.log->fatal(
                        CALL_INFO,
                        -1,
                        "tensor fatal: program addr-aware region size mismatch (core=%u buf=%u ub_addr=%llu expected=%llu got=%llu)\n",
                        rt_.core_id,
                        buf,
                        (unsigned long long)addr,
                        (unsigned long long)it->second.size_bytes,
                        (unsigned long long)size_bytes);
                }
                return nullptr;
            }
            return &it->second;
        };

        // M28: attribute a subset of program-mode UB stalls into the shared stall counters
        // so exec_mode=program becomes comparable with exec_mode=tile in summaries.
        bool wait_read_stall_marked = false;
        bool onchip_capacity_stall_marked = false;
        auto mark_wait_read_stall = [&]() {
            if (!wait_read_stall_marked) {
                tensor_stall_wait_read_cycles_total_ += 1;
                wait_read_stall_marked = true;
            }
            tensor_program_ub_stall_cycles_total_ += 1;
        };
        auto mark_onchip_capacity_stall = [&]() {
            if (!onchip_capacity_stall_marked) {
                tensor_stall_onchip_capacity_cycles_total_ += 1;
                onchip_capacity_stall_marked = true;
            }
            tensor_program_ub_stall_cycles_total_ += 1;
        };

        uint32_t issued = 0;
        while (issued < cfg_.program_issue_width && program_pc_ < program_ops_.size()) {
            const ProgramOp& op = program_ops_[program_pc_];
            if (op.kind == ProgramOpKind::Fence) {
                program_fence_pending_ = true;
                program_pc_ += 1;
                break;
            }

            bool ok = false;
            if (op.kind == ProgramOpKind::DmaRead) {
                const uint32_t buf = op.buf;
                const bool any_dma_active = program_dma_read_slot_.active || program_dma_write_slot_.active;
                if (program_dma_read_slot_.active || (!cfg_.program_dma_dual_enable && any_dma_active)) {
                    ok = false;
                } else {
                    if (!program_addr_aware_enable_) {
                        if (buf >= program_ub_reserved_bytes_by_buf_.size() || buf >= program_ub_valid_bytes_by_buf_.size()) {
                            ok = false;
                        } else if (cfg_.ub_bytes > 0 &&
                                   ([&]() -> bool {
                                       uint64_t occ = program_ub_total_occupancy_bytes();
                                       if (op.reset) {
                                           const uint64_t v = program_ub_valid_bytes_by_buf_[buf];
                                           occ = (occ >= v) ? (occ - v) : 0;
                                       }
                                       return saturatingAddU64_(occ, op.bytes) > cfg_.ub_bytes;
                                   })()) {
                            mark_onchip_capacity_stall();
                            ok = false;
                        } else {
                            program_dma_read_slot_.active = true;
                            program_dma_read_slot_.is_read = true;
                            program_dma_read_slot_.buf = buf;
                            program_dma_read_slot_.ub_addr_present = op.ub_addr_present;
                            program_dma_read_slot_.ub_addr = op.ub_addr;
                            program_dma_read_slot_.epoch = program_dma_epoch_next_++;
                            program_dma_read_slot_.total_bytes = op.bytes;
                            program_dma_read_slot_.issued_bytes = 0;
                            program_dma_read_slot_.done_bytes = 0;
                            if (op.reset) {
                                program_ub_valid_bytes_by_buf_[buf] = 0;
                            }
                            program_ub_reserved_bytes_by_buf_[buf] =
                                saturatingAddU64_(program_ub_reserved_bytes_by_buf_[buf], op.bytes);
                            update_program_ub_occupancy_max();
                            ok = true;
                        }
                    } else {
                        if (buf >= program_ub_regions_by_buf_.size() || !op.ub_addr_present) {
                            ok = false;
                        } else if (ub_part == 0 || op.ub_addr + op.bytes > ub_part) {
                            if (cfg_.strict && rt_.log) {
                                rt_.log->fatal(
                                    CALL_INFO,
                                    -1,
                                    "tensor fatal: program dma_read ub_addr range overflow (core=%u buf=%u ub_addr=%llu bytes=%llu ub_part=%llu)\n",
                                    rt_.core_id,
                                    buf,
                                    (unsigned long long)op.ub_addr,
                                    (unsigned long long)op.bytes,
                                    (unsigned long long)ub_part);
                            }
                            ok = false;
                        } else {
                            if (op.reset) {
                                clear_valid_in_buf(buf);
                            }
                            ProgramUbRegion* reg = get_or_create_region(buf, op.ub_addr, op.bytes);
                            if (!reg) {
                                ok = false;
                            } else if (reg->reserved_bytes > 0 || reg->valid_bytes > 0) {
                                mark_onchip_capacity_stall();
                                ok = false;
                            } else {
                                reg->reserved_bytes = saturatingAddU64_(reg->reserved_bytes, op.bytes);
                                if (reg->size_bytes > 0 && reg->reserved_bytes > reg->size_bytes) {
                                    reg->reserved_bytes = reg->size_bytes;
                                }
                                update_program_ub_occupancy_max();

                                program_dma_read_slot_.active = true;
                                program_dma_read_slot_.is_read = true;
                                program_dma_read_slot_.buf = buf;
                                program_dma_read_slot_.ub_addr_present = true;
                                program_dma_read_slot_.ub_addr = op.ub_addr;
                                program_dma_read_slot_.epoch = program_dma_epoch_next_++;
                                program_dma_read_slot_.total_bytes = op.bytes;
                                program_dma_read_slot_.issued_bytes = 0;
                                program_dma_read_slot_.done_bytes = 0;
                                ok = true;
                            }
                        }
                    }
                }
            } else if (op.kind == ProgramOpKind::DmaWrite) {
                const uint32_t buf = op.buf;
                const bool any_dma_active = program_dma_read_slot_.active || program_dma_write_slot_.active;
                if (program_dma_write_slot_.active || (!cfg_.program_dma_dual_enable && any_dma_active)) {
                    ok = false;
                } else {
                    if (!program_addr_aware_enable_) {
                        if (buf >= program_ub_valid_bytes_by_buf_.size()) {
                            ok = false;
                        } else if (program_ub_valid_bytes_by_buf_[buf] < op.bytes) {
                            mark_wait_read_stall();
                            ok = false;
                        } else {
                            if (op.consume) {
                                program_ub_valid_bytes_by_buf_[buf] -= op.bytes;
                            }
                            program_dma_write_slot_.active = true;
                            program_dma_write_slot_.is_read = false;
                            program_dma_write_slot_.buf = buf;
                            program_dma_write_slot_.ub_addr_present = op.ub_addr_present;
                            program_dma_write_slot_.ub_addr = op.ub_addr;
                            program_dma_write_slot_.epoch = program_dma_epoch_next_++;
                            program_dma_write_slot_.total_bytes = op.bytes;
                            program_dma_write_slot_.issued_bytes = 0;
                            program_dma_write_slot_.done_bytes = 0;
                            ok = true;
                        }
                    } else {
                        if (buf >= program_ub_regions_by_buf_.size() || !op.ub_addr_present) {
                            ok = false;
                        } else if (ub_part == 0 || op.ub_addr + op.bytes > ub_part) {
                            if (cfg_.strict && rt_.log) {
                                rt_.log->fatal(
                                    CALL_INFO,
                                    -1,
                                    "tensor fatal: program dma_write ub_addr range overflow (core=%u buf=%u ub_addr=%llu bytes=%llu ub_part=%llu)\n",
                                    rt_.core_id,
                                    buf,
                                    (unsigned long long)op.ub_addr,
                                    (unsigned long long)op.bytes,
                                    (unsigned long long)ub_part);
                            }
                            ok = false;
                        } else {
                            ProgramUbRegion* reg = get_or_create_region(buf, op.ub_addr, op.bytes);
                            if (!reg) {
                                ok = false;
                            } else if (reg->valid_bytes < op.bytes) {
                                mark_wait_read_stall();
                                ok = false;
                            } else {
                                if (op.consume) {
                                    reg->valid_bytes -= op.bytes;
                                }
                                update_program_ub_occupancy_max();

                                program_dma_write_slot_.active = true;
                                program_dma_write_slot_.is_read = false;
                                program_dma_write_slot_.buf = buf;
                                program_dma_write_slot_.ub_addr_present = true;
                                program_dma_write_slot_.ub_addr = op.ub_addr;
                                program_dma_write_slot_.epoch = program_dma_epoch_next_++;
                                program_dma_write_slot_.total_bytes = op.bytes;
                                program_dma_write_slot_.issued_bytes = 0;
                                program_dma_write_slot_.done_bytes = 0;
                                ok = true;
                            }
                        }
                    }
                }
            } else if (op.kind == ProgramOpKind::GemmUb) {
                const uint32_t buf = op.buf;
                if (program_mxu_slot_.active) {
                    ok = false;
                } else {
                    uint64_t cycles = op.cycles;
                    if (cycles == 0) {
                        cycles = estimateGemmUbCycles_(op.m, op.n, op.k);
                    }

                    if (!program_addr_aware_enable_) {
                        if (buf >= program_ub_reserved_bytes_by_buf_.size() || buf >= program_ub_valid_bytes_by_buf_.size()) {
                            ok = false;
                        } else if (program_ub_valid_bytes_by_buf_[buf] < op.ub_read_bytes) {
                            mark_wait_read_stall();
                            ok = false;
                        } else if (cfg_.ub_bytes > 0 &&
                                   saturatingAddU64_(program_ub_total_occupancy_bytes(), op.ub_write_bytes) > cfg_.ub_bytes) {
                            mark_onchip_capacity_stall();
                            ok = false;
                        } else {
                            if (op.ub_write_bytes > 0) {
                                program_ub_reserved_bytes_by_buf_[buf] =
                                    saturatingAddU64_(program_ub_reserved_bytes_by_buf_[buf], op.ub_write_bytes);
                                update_program_ub_occupancy_max();
                            }
                            program_mxu_slot_.active = true;
                            program_mxu_slot_.buf = buf;
                            program_mxu_slot_.ub_write_addr_present = op.ub_write_addr_present;
                            program_mxu_slot_.ub_write_addr = op.ub_write_addr;
                            program_mxu_slot_.rem_cycles = cycles;
                            program_mxu_slot_.ub_read_bytes = op.ub_read_bytes;
                            program_mxu_slot_.ub_write_bytes = op.ub_write_bytes;
                            program_mxu_slot_.ub_write_reserved_bytes = op.ub_write_bytes;
                            {
                                const uint64_t total_in = op.ub_read_bytes;
                                const uint64_t a_bytes = total_in / 2;
                                const uint64_t b_bytes = total_in - a_bytes;
                                program_mxu_slot_.ub_read_a_bytes_rem = a_bytes;
                                program_mxu_slot_.ub_read_b_bytes_rem = b_bytes;
                                program_mxu_slot_.ub_write_bytes_rem = op.ub_write_bytes;
                            }
                            ok = true;
                        }
                    } else {
                        if (buf >= program_ub_regions_by_buf_.size() || !op.ub_read_addr_present || !op.ub_write_addr_present) {
                            ok = false;
                        } else if (ub_part == 0 ||
                                   (op.ub_read_bytes > 0 && op.ub_read_addr + op.ub_read_bytes > ub_part) ||
                                   (op.ub_write_bytes > 0 && op.ub_write_addr + op.ub_write_bytes > ub_part)) {
                            if (cfg_.strict && rt_.log) {
                                rt_.log->fatal(
                                    CALL_INFO,
                                    -1,
                                    "tensor fatal: program gemm_ub ub_addr range overflow (core=%u buf=%u ub_part=%llu)\n",
                                    rt_.core_id,
                                    buf,
                                    (unsigned long long)ub_part);
                            }
                            ok = false;
                        } else {
                            ok = true;
                            if (op.ub_read_bytes > 0) {
                                ProgramUbRegion* in = get_or_create_region(buf, op.ub_read_addr, op.ub_read_bytes);
                                if (!in) {
                                    ok = false;
                                } else if (in->valid_bytes < op.ub_read_bytes) {
                                    mark_wait_read_stall();
                                    ok = false;
                                }
                            }
                            if (ok && op.ub_write_bytes > 0) {
                                ProgramUbRegion* out = get_or_create_region(buf, op.ub_write_addr, op.ub_write_bytes);
                                if (!out) {
                                    ok = false;
                                } else if (out->reserved_bytes > 0 || out->valid_bytes > 0) {
                                    mark_onchip_capacity_stall();
                                    ok = false;
                                } else {
                                    out->reserved_bytes = saturatingAddU64_(out->reserved_bytes, op.ub_write_bytes);
                                    if (out->size_bytes > 0 && out->reserved_bytes > out->size_bytes) {
                                        out->reserved_bytes = out->size_bytes;
                                    }
                                    update_program_ub_occupancy_max();
                                }
                            }
                            if (ok) {
                                program_mxu_slot_.active = true;
                                program_mxu_slot_.buf = buf;
                                program_mxu_slot_.ub_write_addr_present = op.ub_write_addr_present;
                                program_mxu_slot_.ub_write_addr = op.ub_write_addr;
                                    program_mxu_slot_.rem_cycles = cycles;
                                    program_mxu_slot_.ub_read_bytes = op.ub_read_bytes;
                                    program_mxu_slot_.ub_write_bytes = op.ub_write_bytes;
                                    program_mxu_slot_.ub_write_reserved_bytes = op.ub_write_bytes;
                                    {
                                        const uint64_t total_in = op.ub_read_bytes;
                                        const uint64_t a_bytes = total_in / 2;
                                        const uint64_t b_bytes = total_in - a_bytes;
                                        program_mxu_slot_.ub_read_a_bytes_rem = a_bytes;
                                        program_mxu_slot_.ub_read_b_bytes_rem = b_bytes;
                                        program_mxu_slot_.ub_write_bytes_rem = op.ub_write_bytes;
                                    }
                                    ok = true;
                                }
                            }
                        }
                }
            } else if (op.kind == ProgramOpKind::Softmax) {
                if (program_vec_slot_.active) {
                    ok = false;
                } else {
                    const uint64_t denom = static_cast<uint64_t>(std::max<uint32_t>(cfg_.vector_elems_per_cycle, 1u));
                    const uint64_t body = ceilDivU64_(std::max<uint64_t>(1ull, op.elems), denom);
                    const uint64_t pipe = static_cast<uint64_t>(cfg_.vector_pipeline_latency_cycles);
                    uint64_t cycles = saturatingAddU64_(body, pipe);
                    if (cycles == 0) cycles = 1;
                    program_vec_slot_.active = true;
                    program_vec_slot_.rem_cycles = cycles;
                    ok = true;
                }
            } else if (op.kind == ProgramOpKind::Allreduce) {
                if (program_coll_slot_.active) {
                    ok = false;
                } else {
                    const uint64_t bytes = (op.bytes > 0) ? op.bytes : cfg_.collective_bytes;
                    if (!startProgramCollective_(now_cycle, bytes, op.blocking)) {
                        if (cfg_.strict && rt_.log) {
                            rt_.log->fatal(CALL_INFO, -1, "tensor fatal: failed to start program allreduce (core=%u)\n", rt_.core_id);
                        }
                        ok = false;
                    } else {
                        program_coll_slot_.active = true;
                        program_coll_slot_.bytes = bytes;
                        program_coll_slot_.blocking = op.blocking;
                        ok = true;
                    }
                }
            } else {
                // Unknown / unsupported op in M7 pipeline.
                ok = false;
            }

            if (!ok) break;
            program_pc_ += 1;
            issued += 1;
        }
    }

    // === Iteration completion ===
    if (program_pc_ >= program_ops_.size() &&
        !program_fence_pending_ &&
        !program_dma_read_slot_.active &&
        !program_dma_write_slot_.active &&
        !program_mxu_slot_.active &&
        !program_vec_slot_.active &&
        !program_coll_slot_.active &&
        inflight_.empty() &&
        !collectivePendingActive_()) {
        tensor_program_iters_total_ += 1;
        program_iter_done_ += 1;
        if (step_gated_) {
            step_open_ = false;
        }
        if (program_loop_enable_ && (cfg_.iterations == 0 || program_iter_done_ < cfg_.iterations)) {
            program_pc_ = 0;
        }
    }

    if (did) active_cycles_++;
    return did;
}

bool TensorWorkload::onClockTickProgram_(uint64_t now_cycle) {
    if (program_m7_enable_) {
        return onClockTickProgramM7_(now_cycle);
    }

    // Always allow NoC control traffic (credit return) to make forward progress.
    bool did = false;
    bool did_collective = false;
    bool did_comm = false;
    bool noc_budget_blocked = false;
    uint64_t noc_budget = (cfg_.noc_bandwidth_bytes_per_cycle > 0)
                              ? cfg_.noc_bandwidth_bytes_per_cycle
                              : std::numeric_limits<uint64_t>::max();

    auto issue_noc = [&]() {
        issueNocTraffic_(now_cycle, noc_budget, did, did_collective, did_comm, noc_budget_blocked);
        if (noc_budget_blocked && !did_collective && !did_comm) {
            tensor_stall_noc_budget_cycles_total_ += 1;
        }
    };

    // Step-gated mode: only run when a step is open, but still flush credit-return traffic.
    if (step_gated_ && !step_open_) {
        issue_noc();
        if (did) active_cycles_++;
        return did;
    }

    if (!started_) {
        if (now_cycle < cfg_.start_cycle) {
            issue_noc();
            if (did) active_cycles_++;
            return did;
        }
        started_ = true;
    }

    serviceCollectiveBarrier_(now_cycle);

    // Stop after requested program iterations (0 = run forever).
    if (cfg_.iterations > 0 && program_iter_done_ >= cfg_.iterations) {
        issue_noc();
        if (did) active_cycles_++;
        return did;
    }

    if (program_ops_.empty()) {
        // Program mode with an empty program is allowed when strict=0 (acts like idle workload).
        issue_noc();
        if (did) active_cycles_++;
        return did;
    }

    if (program_pc_ >= program_ops_.size()) {
        // Program finished (or waiting for the next global step). Stay idle but keep draining NoC control traffic.
        issue_noc();
        if (did) active_cycles_++;
        return did;
    }

    auto finish_program_iter = [&]() {
        tensor_program_iters_total_ += 1;
        program_iter_done_ += 1;
        if (step_gated_) {
            step_open_ = false;
        }
        if (program_loop_enable_ && (cfg_.iterations == 0 || program_iter_done_ < cfg_.iterations)) {
            program_pc_ = 0;
        }
    };

    const ProgramOp op = program_ops_[program_pc_];
    if (op.kind == ProgramOpKind::Gemm) {
        const bool did_gemm = onClockTickTile_(now_cycle);
        if (iter_active_) {
            program_gemm_started_ = true;
        }
        if (program_gemm_started_ && !iter_active_) {
            program_gemm_started_ = false;
            program_op_started_ = false;
            program_collective_started_ = false;
            program_softmax_rem_cycles_ = 0;
            tensor_program_ops_total_ += 1;
            program_pc_ += 1;
            if (program_pc_ >= program_ops_.size()) {
                finish_program_iter();
            }
        }
        return did_gemm;
    }

    if (op.kind == ProgramOpKind::Allreduce) {
        if (!program_collective_started_) {
            const uint64_t bytes = (op.bytes > 0) ? op.bytes : cfg_.collective_bytes;
            if (!startProgramCollective_(now_cycle, bytes, op.blocking)) {
                if (cfg_.strict && rt_.log) {
                    rt_.log->fatal(CALL_INFO, -1, "tensor fatal: failed to start program allreduce (core=%u)\n", rt_.core_id);
                }
                issue_noc();
                if (did) active_cycles_++;
                return did;
            }
            program_collective_started_ = true;
            program_op_started_ = true;
        }

        issue_noc();

        bool done = program_collective_started_ && !collectivePendingActive_();
        if (done && op.blocking && cfg_.collective_blocking && collective_epoch_active_) {
            // Blocking collective: wait for recv completion when enabled.
            tensor_stall_collective_cycles_total_ += 1;
            done = false;
        }
        if (done) {
            program_collective_started_ = false;
            program_op_started_ = false;
            tensor_program_ops_total_ += 1;
            program_pc_ += 1;
            if (program_pc_ >= program_ops_.size()) {
                finish_program_iter();
            }
        }
        if (did) active_cycles_++;
        return did;
    }

    // Softmax/vector placeholder: compute-only cycles + NoC credit-return flushing.
    if (!program_op_started_) {
        const uint64_t elems = op.elems;
        const uint64_t denom = static_cast<uint64_t>(std::max<uint32_t>(cfg_.vector_elems_per_cycle, 1u));
        const uint64_t body = ceilDivU64_(std::max<uint64_t>(1ull, elems), denom);
        const uint64_t pipe = static_cast<uint64_t>(cfg_.vector_pipeline_latency_cycles);
        program_softmax_rem_cycles_ = saturatingAddU64_(body, pipe);
        if (program_softmax_rem_cycles_ == 0) program_softmax_rem_cycles_ = 1;
        program_op_started_ = true;
    }

    issue_noc();

    if (program_softmax_rem_cycles_ > 0) {
        program_softmax_rem_cycles_ -= 1;
        tensor_vector_cycles_total_ += 1;
        did = true;
    }
    if (program_op_started_ && program_softmax_rem_cycles_ == 0) {
        program_op_started_ = false;
        tensor_program_ops_total_ += 1;
        program_pc_ += 1;
        if (program_pc_ >= program_ops_.size()) {
            finish_program_iter();
        }
    }
    if (did) active_cycles_++;
    return did;
}

bool TensorWorkload::onClockTick(uint64_t now_cycle) {
    now_cycle_cached_ = now_cycle;
    total_cycles_++;
    if (!configured_) return false;

    if (cfg_.exec_mode == "program") {
        return onClockTickProgram_(now_cycle);
    }

    bool did_credit_return = false;
    if (!iter_active_) {
        bool credit_budget_blocked = false;
        const uint64_t credit_budget = (cfg_.noc_bandwidth_bytes_per_cycle > 0)
                                           ? cfg_.noc_bandwidth_bytes_per_cycle
                                           : std::numeric_limits<uint64_t>::max();
        const uint64_t credit_sent =
            emitCollectiveCreditReturnTraffic_(now_cycle, credit_budget, credit_budget_blocked);
        did_credit_return = (credit_sent > 0);
        if (credit_budget_blocked && !did_credit_return) {
            tensor_stall_noc_budget_cycles_total_ += 1;
        }
    }

    // Step-gated mode: only run when a step is open.
    if (step_gated_ && !step_open_) {
        if (did_credit_return) active_cycles_++;
        return did_credit_return;
    }

    if (!started_) {
        if (now_cycle < cfg_.start_cycle) {
            if (did_credit_return) active_cycles_++;
            return did_credit_return;
        }
        started_ = true;
    }

    serviceCollectiveBarrier_(now_cycle);

    if (cfg_.exec_mode == "tile") {
        const bool did_tile = onClockTickTile_(now_cycle);
        if (did_credit_return && !did_tile) active_cycles_++;
        return did_credit_return || did_tile;
    }

    if (!iter_active_) {
        if (cfg_.exec_mode != "program" && cfg_.iterations > 0 && iter_done_ >= cfg_.iterations) {
            if (did_credit_return) active_cycles_++;
            return did_credit_return;
        }
        if (cfg_.collective_blocking && collective_epoch_active_) {
            if (cfg_.collective_scope == "per_core") {
                if (collective_epoch_recv_bytes_ < collective_epoch_expected_recv_bytes_) {
                    tensor_stall_collective_cycles_total_ += 1;
                    if (did_credit_return) active_cycles_++;
                    return did_credit_return;
                }
                markCollectiveEpochDone_(now_cycle);
                const uint32_t done_seq = collective_epoch_seq_;
                collective_epoch_active_ = false;
                collective_epoch_expected_recv_bytes_ = 0;
                collective_epoch_recv_bytes_ = 0;
                collective_recv_bytes_by_seq_.erase(done_seq);
            } else {
                tensor_stall_collective_cycles_total_ += 1;
                if (did_credit_return) active_cycles_++;
                return did_credit_return;
            }
        }
        if (inflight_.empty()) {
            startIteration_();
        }
    }

    bool did = did_credit_return;
    bool did_mem = false;
    bool did_compute = false;
    bool did_collective = false;
    bool did_comm = false;
    bool noc_budget_blocked = false;
    uint64_t noc_budget = (cfg_.noc_bandwidth_bytes_per_cycle > 0)
                              ? cfg_.noc_bandwidth_bytes_per_cycle
                              : std::numeric_limits<uint64_t>::max();

    // === DMA reads ===
    const bool dma_shared = (cfg_.dma_shared_bandwidth_bytes_per_cycle > 0);
    uint64_t shared_budget_left = dma_shared ? dmaBudgetBytesPerCycle_(now_cycle) : std::numeric_limits<uint64_t>::max();
    if (dma_shared) {
        uint64_t& budget = shared_budget_left;
        while (rem_read_bytes_ > 0) {
            const uint32_t next_bytes = static_cast<uint32_t>(std::min<uint64_t>(cfg_.mem_req_bytes, rem_read_bytes_));
            if (next_bytes == 0 || next_bytes > budget) break;
            const uint32_t issued = issueMemRead_();
            if (issued == 0) break;
            budget -= issued;
            did = true;
            did_mem = true;
        }
    } else if (tileModelEnabled_() && cfg_.dma_bandwidth_bytes_per_cycle > 0) {
        uint64_t budget = cfg_.dma_bandwidth_bytes_per_cycle;
        while (rem_read_bytes_ > 0) {
            const uint32_t next_bytes = static_cast<uint32_t>(std::min<uint64_t>(cfg_.mem_req_bytes, rem_read_bytes_));
            if (next_bytes == 0 || next_bytes > budget) break;
            const uint32_t issued = issueMemRead_();
            if (issued == 0) break;
            budget -= issued;
            did = true;
            did_mem = true;
        }
    } else {
        while (issueMemRead_()) {
            did = true;
            did_mem = true;
        }
    }

    // === Compute ===
    if (!compute_started_) {
        // Non-overlap mode: wait for all read requests to complete.
        if (!cfg_.mem_enable || !rt_.mem) {
            compute_started_ = true;
        } else if (rem_read_bytes_ == 0) {
            bool any_read_inflight = false;
            for (const auto& kv : inflight_) {
                if (kv.second.kind == ReqKind::Read) {
                    any_read_inflight = true;
                    break;
                }
            }
            if (!any_read_inflight) compute_started_ = true;
        }
    }
    const bool collective_blocks_compute = (!cfg_.collective_overlap_with_compute && collectivePendingActive_());
    if (!collective_blocks_compute && tickCompute_()) {
        did = true;
        did_compute = true;
    } else if (collective_blocks_compute && rem_compute_cycles_ > 0) {
        tensor_stall_collective_cycles_total_ += 1;
    }

    // === DMA writes (after compute completes) ===
    if (rem_compute_cycles_ == 0) {
        if (dma_shared) {
            uint64_t& budget = shared_budget_left;
            while (rem_write_bytes_ > 0) {
                const uint32_t next_bytes = static_cast<uint32_t>(std::min<uint64_t>(cfg_.mem_req_bytes, rem_write_bytes_));
                if (next_bytes == 0 || next_bytes > budget) break;
                const uint32_t issued = issueMemWrite_();
                if (issued == 0) break;
                budget -= issued;
                did = true;
                did_mem = true;
            }
        } else if (tileModelEnabled_() && cfg_.dma_bandwidth_bytes_per_cycle > 0) {
            uint64_t budget = cfg_.dma_bandwidth_bytes_per_cycle;
            while (rem_write_bytes_ > 0) {
                const uint32_t next_bytes = static_cast<uint32_t>(std::min<uint64_t>(cfg_.mem_req_bytes, rem_write_bytes_));
                if (next_bytes == 0 || next_bytes > budget) break;
                const uint32_t issued = issueMemWrite_();
                if (issued == 0) break;
                budget -= issued;
                did = true;
                did_mem = true;
            }
        } else {
            while (issueMemWrite_()) {
                did = true;
                did_mem = true;
            }
        }
    }

    if (iter_active_) {
        issueNocTraffic_(now_cycle, noc_budget, did, did_collective, did_comm, noc_budget_blocked);
    }

    if (noc_budget_blocked && !did_collective && !did_comm) {
        tensor_stall_noc_budget_cycles_total_ += 1;
    }

    // === Iteration complete ===
    if (iter_active_ &&
        rem_read_bytes_ == 0 &&
        rem_write_bytes_ == 0 &&
        rem_compute_cycles_ == 0 &&
        !collectivePendingActive_() &&
        inflight_.empty()) {
        iter_done_++;
        iter_active_ = false;
        compute_started_ = false;
        if (step_gated_ && close_step_on_iter_done_) {
            // In barrier/step-gated runs, execute at most one iteration per step.
            step_open_ = false;
        }
    }

    if (!did && (iter_active_ || !inflight_.empty())) {
        tensor_dma_stall_cycles_total_ += 1;
    }

    if (cfg_.collective_overlap_with_compute && did_compute && did_collective) {
        tensor_overlap_compute_collective_cycles_total_ += 1;
    }
    if (did_compute && did_mem) {
        tensor_overlap_compute_mem_cycles_total_ += 1;
    }

    if (did) active_cycles_++;
    return did;
}

bool TensorWorkload::hasWork() const {
    if (!configured_) return false;
    // Before start_cycle is reached, still report "work pending" so barrier/drain policies
    // do not accidentally advance global steps without executing the workload.
    if (!started_) return true;
    if (!inflight_.empty()) return true;
    if (iter_active_) return true;
    if (cfg_.exec_mode == "program") {
        if (collectivePendingActive_()) return true;
        if (step_gated_ && !step_open_) return false;
        if (cfg_.iterations > 0 && program_iter_done_ >= cfg_.iterations) return false;
        if (program_ops_.empty()) return false;
        if (!program_loop_enable_ && program_pc_ >= program_ops_.size()) return false;
        return true;
    }
    if (step_gated_) {
        if (!step_open_) return false;
        if (cfg_.exec_mode != "program" && cfg_.iterations > 0 && iter_done_ >= cfg_.iterations) return false;
        return true;
    }
    if (cfg_.exec_mode != "program" && cfg_.iterations > 0 && iter_done_ >= cfg_.iterations) return false;
    return true;
}

double TensorWorkload::getUtilization() const {
    if (total_cycles_ == 0) return 0.0;
    return static_cast<double>(tensor_compute_cycles_total_) / static_cast<double>(total_cycles_);
}

void TensorWorkload::getStatistics(std::map<std::string, uint64_t>& stats) const {
    // Preserve legacy keys expected by MultiCorePE/analysis.
    stats["spikes_received"] = 0;
    stats["spikes_generated"] = 0;
    stats["neurons_fired"] = 0;
    stats["memory_requests"] = memory_requests_;
    stats["total_cycles"] = total_cycles_;
    stats["active_cycles"] = active_cycles_;
    stats["cycles_update_neuron"] = 0;
    stats["synaptic_accesses"] = 0;

    // Tensor workload counters (pulled by MultiCorePE for PE-level aggregation).
    stats["tensor_mem_reads_issued_total"] = tensor_mem_reads_issued_total_;
    stats["tensor_mem_writes_issued_total"] = tensor_mem_writes_issued_total_;
    stats["tensor_mem_bytes_read_total"] = tensor_mem_bytes_read_total_;
    stats["tensor_mem_bytes_write_total"] = tensor_mem_bytes_write_total_;
    stats["tensor_mem_read_latency_cycles_total"] = tensor_mem_read_latency_cycles_total_;
    stats["tensor_mem_read_latency_cycles_max"] = tensor_mem_read_latency_cycles_max_;
    stats["tensor_mem_read_latency_samples_total"] = tensor_mem_read_latency_samples_total_;
    stats["tensor_mem_write_latency_cycles_total"] = tensor_mem_write_latency_cycles_total_;
    stats["tensor_mem_write_latency_cycles_max"] = tensor_mem_write_latency_cycles_max_;
    stats["tensor_mem_write_latency_samples_total"] = tensor_mem_write_latency_samples_total_;
    stats["tensor_mem_row_hit_total"] = tensor_mem_row_hit_total_;
    stats["tensor_mem_row_miss_total"] = tensor_mem_row_miss_total_;
    stats["tensor_mem_row_conflict_total"] = tensor_mem_row_conflict_total_;
    stats["tensor_mem_bank_queue_full_total"] = tensor_mem_bank_queue_full_total_;
    stats["tensor_mem_bank_queue_wait_cycles_total"] = tensor_mem_bank_queue_wait_cycles_total_;
    stats["tensor_mem_sched_fifo_pick_total"] = tensor_mem_sched_fifo_pick_total_;
    stats["tensor_mem_sched_frfcfs_pick_total"] = tensor_mem_sched_frfcfs_pick_total_;
    stats["tensor_mem_cmd_act_total"] = tensor_mem_cmd_act_total_;
    stats["tensor_mem_cmd_pre_total"] = tensor_mem_cmd_pre_total_;
    stats["tensor_mem_cmd_rdwr_total"] = tensor_mem_cmd_rdwr_total_;
    stats["tensor_mem_row_service_cycles_total"] = tensor_mem_row_service_cycles_total_;
    stats["tensor_mem_refresh_block_cycles_total"] = tensor_mem_refresh_block_cycles_total_;
    stats["tensor_mem_proxy_delay_cycles_total"] = tensor_mem_proxy_delay_cycles_total_;
    stats["tensor_mem_proxy_delay_cycles_max"] = tensor_mem_proxy_delay_cycles_max_;
    stats["tensor_mem_bank_active_cycles_total"] = tensor_mem_bank_active_cycles_total_;
    stats["tensor_mem_cmd_queue_slots_total"] = tensor_mem_cmd_queue_slots_total_;
    stats["tensor_mem_cmd_queue_depth_max"] = tensor_mem_cmd_queue_depth_max_;
    stats["tensor_mem_cmd_bus_wait_cycles_total"] = tensor_mem_cmd_bus_wait_cycles_total_;
    stats["tensor_mem_cmd_bus_bg_switch_total"] = tensor_mem_cmd_bus_bg_switch_total_;
    stats["tensor_mem_cmd_issue_total"] = tensor_mem_cmd_issue_total_;
    stats["tensor_compute_cycles_total"] = tensor_compute_cycles_total_;
    stats["tensor_compute_math_cycles_total"] = tensor_compute_math_cycles_total_;
    stats["tensor_compute_pipeline_cycles_total"] = tensor_compute_pipeline_cycles_total_;
    stats["tensor_mxu_wavefront_cycles_total"] = tensor_mxu_wavefront_cycles_total_;
    stats["tensor_mxu_io_busy_cycles_total"] = tensor_mxu_io_busy_cycles_total_;
    stats["tensor_compute_precision_profile_id"] = tensor_compute_precision_profile_id_;
    stats["tensor_mac_ops_total"] = tensor_mac_ops_total_;
    stats["tensor_dma_stall_cycles_total"] = tensor_dma_stall_cycles_total_;
    stats["tensor_iter_cycles_total"] = tensor_iter_cycles_total_;
    stats["tensor_stall_dma_budget_cycles_total"] = tensor_stall_dma_budget_cycles_total_;
    stats["tensor_stall_dma_hbm_channel_budget_cycles_total"] = tensor_stall_dma_hbm_channel_budget_cycles_total_;
    stats["tensor_stall_mem_outstanding_cycles_total"] = tensor_stall_mem_outstanding_cycles_total_;
    stats["tensor_stall_wait_read_cycles_total"] = tensor_stall_wait_read_cycles_total_;
    stats["tensor_stall_wait_write_cycles_total"] = tensor_stall_wait_write_cycles_total_;
    stats["tensor_stall_collective_cycles_total"] = tensor_stall_collective_cycles_total_;
    stats["tensor_stall_onchip_capacity_cycles_total"] = tensor_stall_onchip_capacity_cycles_total_;
    stats["tensor_stall_onchip_port_cycles_total"] = tensor_stall_onchip_port_cycles_total_;
    stats["tensor_stall_onchip_bank_conflict_cycles_total"] = tensor_stall_onchip_bank_conflict_cycles_total_;
    stats["tensor_stall_spill_budget_cycles_total"] = tensor_stall_spill_budget_cycles_total_;
    stats["tensor_dma_cycles_total"] = tensor_dma_cycles_total_;
    stats["tensor_dram_bytes_total"] = tensor_dram_bytes_total_;
    stats["tensor_onchip_bytes_total"] = tensor_onchip_bytes_total_;
    stats["tensor_cfg_ub_bytes"] = cfg_.ub_bytes;
    stats["tensor_cfg_weight_bytes"] = cfg_.weight_bytes;
    stats["tensor_onchip_weight_occupancy_bytes_max"] = tensor_onchip_weight_occupancy_bytes_max_;
    stats["tensor_onchip_weight_bank_occupancy_bytes_max"] = tensor_onchip_weight_bank_occupancy_bytes_max_;
    stats["tensor_onchip_a_resident_tiles_max"] = tensor_onchip_a_resident_tiles_max_;
    stats["tensor_onchip_b_resident_tiles_max"] = tensor_onchip_b_resident_tiles_max_;
    stats["tensor_tile_count_total"] = tensor_tile_count_total_;
    stats["tensor_spill_bytes_total"] = tensor_spill_bytes_total_;
    stats["tensor_spill_pkts_total"] = tensor_spill_pkts_total_;
    stats["tensor_collective_bytes_sent_total"] = tensor_collective_bytes_sent_total_;
    stats["tensor_collective_bytes_recv_total"] = tensor_collective_bytes_recv_total_;
    stats["tensor_collective_pkts_sent_total"] = tensor_collective_pkts_sent_total_;
    stats["tensor_collective_pkts_recv_total"] = tensor_collective_pkts_recv_total_;
    stats["tensor_collective_cycles_total"] = tensor_collective_cycles_total_;
    stats["tensor_collective_pending_cycles_total"] = tensor_collective_pending_cycles_total_;
    stats["tensor_collective_issue_cycles_total"] = tensor_collective_issue_cycles_total_;
    stats["tensor_collective_chunk_groups_total"] = tensor_collective_chunk_groups_total_;
    stats["tensor_collective_ring_steps_total"] = tensor_collective_ring_steps_total_;
    stats["tensor_collective_2d_row_rs_steps_total"] = tensor_collective_2d_row_rs_steps_total_;
    stats["tensor_collective_2d_col_rs_steps_total"] = tensor_collective_2d_col_rs_steps_total_;
    stats["tensor_collective_2d_col_ag_steps_total"] = tensor_collective_2d_col_ag_steps_total_;
    stats["tensor_collective_2d_row_ag_steps_total"] = tensor_collective_2d_row_ag_steps_total_;
    stats["tensor_collective_2d_row_rs_bytes_sent_total"] = tensor_collective_2d_row_rs_bytes_sent_total_;
    stats["tensor_collective_2d_col_rs_bytes_sent_total"] = tensor_collective_2d_col_rs_bytes_sent_total_;
    stats["tensor_collective_2d_col_ag_bytes_sent_total"] = tensor_collective_2d_col_ag_bytes_sent_total_;
    stats["tensor_collective_2d_row_ag_bytes_sent_total"] = tensor_collective_2d_row_ag_bytes_sent_total_;
    stats["tensor_collective_reduce_wait_cycles_total"] = tensor_collective_reduce_wait_cycles_total_;
    stats["tensor_collective_2d_reduce_wait_cycles_total"] = tensor_collective_2d_reduce_wait_cycles_total_;
    stats["tensor_collective_epoch_done_total"] = tensor_collective_epoch_done_total_;
    stats["tensor_collective_epoch_latency_cycles_total"] = tensor_collective_epoch_latency_cycles_total_;
    stats["tensor_collective_epoch_latency_cycles_max"] = tensor_collective_epoch_latency_cycles_max_;
    // This is a config identifier, not a throughput/volume metric. Export it once to
    // keep summary consumers stable under PE/core aggregation (avoid scaling by core count).
    const bool is_leader_core = (rt_.node_id == 0 && rt_.core_id == 0);
    stats["tensor_collective_algo_id"] = is_leader_core ? tensor_collective_algo_id_ : 0ull;
    stats["tensor_collective_credit_stall_cycles_total"] = tensor_collective_credit_stall_cycles_total_;
    stats["tensor_collective_backpressure_stall_cycles_total"] = tensor_collective_backpressure_stall_cycles_total_;
    stats["tensor_collective_inflight_chunks_max"] = tensor_collective_inflight_chunks_max_;
    stats["tensor_collective_credit_return_pkts_sent_total"] = tensor_collective_credit_return_pkts_sent_total_;
    stats["tensor_collective_credit_return_pkts_recv_total"] = tensor_collective_credit_return_pkts_recv_total_;
    stats["tensor_collective_credit_return_orphan_total"] = tensor_collective_credit_return_orphan_total_;
    stats["tensor_collective_credit_return_dup_total"] = tensor_collective_credit_return_dup_total_;
    stats["tensor_collective_credit_return_latency_cycles_total"] = tensor_collective_credit_return_latency_cycles_total_;
    stats["tensor_collective_credit_return_latency_cycles_max"] = tensor_collective_credit_return_latency_cycles_max_;
    stats["tensor_bank_queue_occupancy_max"] = tensor_bank_queue_occupancy_max_;
    stats["tensor_stall_noc_budget_cycles_total"] = tensor_stall_noc_budget_cycles_total_;
    stats["tensor_overlap_compute_collective_cycles_total"] = tensor_overlap_compute_collective_cycles_total_;
    stats["tensor_overlap_compute_mem_cycles_total"] = tensor_overlap_compute_mem_cycles_total_;
    stats["tensor_pkt_sent_total"] = tensor_pkt_sent_total_;
    stats["tensor_pkt_recv_total"] = tensor_pkt_recv_total_;
    stats["tensor_pkt_bytes_sent_total"] = tensor_pkt_bytes_sent_total_;
    stats["tensor_pkt_bytes_recv_total"] = tensor_pkt_bytes_recv_total_;
    stats["tensor_vector_cycles_total"] = tensor_vector_cycles_total_;
    stats["tensor_program_any_busy_cycles_total"] = tensor_program_any_busy_cycles_total_;
    stats["tensor_program_dma_busy_cycles_total"] = tensor_program_dma_busy_cycles_total_;
    stats["tensor_program_mxu_busy_cycles_total"] = tensor_program_mxu_busy_cycles_total_;
    stats["tensor_program_vec_busy_cycles_total"] = tensor_program_vec_busy_cycles_total_;
    stats["tensor_program_coll_busy_cycles_total"] = tensor_program_coll_busy_cycles_total_;
    stats["tensor_program_ops_total"] = tensor_program_ops_total_;
    stats["tensor_program_iters_total"] = tensor_program_iters_total_;
    stats["tensor_program_fence_count_total"] = tensor_program_fence_count_total_;
    stats["tensor_program_fence_wait_cycles_total"] = tensor_program_fence_wait_cycles_total_;
    stats["tensor_program_ub_stall_cycles_total"] = tensor_program_ub_stall_cycles_total_;
    stats["tensor_program_mem_stall_cycles_total"] = tensor_program_mem_stall_cycles_total_;
    stats["tensor_program_ub_occupancy_bytes_max"] = tensor_program_ub_occupancy_bytes_max_;
}

}} // namespace SST::SnnDL
