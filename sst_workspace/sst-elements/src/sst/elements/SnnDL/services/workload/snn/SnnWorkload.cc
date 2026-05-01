// -*- c++ -*-

#include <sst/core/sst_config.h>

#include "workload/snn/SnnWorkload.h"
#include "ISnnComputeCore.h"
#include "events/SpikeEvent.h"
#include "SnnWeightReader.h"
#include "synapse/gas/AccumulatorOps.h"
#include "synapse/weights/WeightAccessor.h"
#include "synapse/weights/WeightCacheOps.h"
#include "synapse/weights/SnnBcsrWeightManager.h"
#include "synapse/weights/WeightMemorySubsystem.h"
#include "synapse/weights/DenseWeightLayout.h"
#include "synapse/route/SynapseRouteSubsystem.h"
#include "synapse/route3d/SynapseRouteSubsystem3D.h"
#include "synapse/route/SpikeCommSubsystem.h"
#include "synapse/route/SpikeNocCodec.h"
#include "synapse/route/SpikeTileNocCodec.h"
#include "services/local_storage/PeLocalServiceObjectTable.h"
#include "SynapseRouteBuildConfig.h"
#include "ISpikeTransport.h"
#include "NocSpikeTransport.h"
#include "workload/stream/StreamWorkload.h"
#include "workload/layout/NormalizedNeuronLayout.h"

#include <sst/core/output.h>
#include <sst/core/params.h>
#include <sst/core/shared/sharedArray.h>
#include <sst/core/statapi/stataccumulator.h>

#include <algorithm>
#include <cstdlib>
#include <cstring>
#include <inttypes.h>
#include <iterator>
#include <limits>
#include <map>
#include <utility>

namespace SST { namespace SnnDL {

namespace {

inline void addCountStat_(SST::Statistics::Statistic<uint64_t>* st, uint64_t n) {
    if (!st || n == 0) return;
    for (uint64_t i = 0; i < n; ++i) st->addData(1);
}

bool meshShapeHasMultipleLayers_(const std::string& mesh_shape) {
    const auto p0 = mesh_shape.find('x');
    if (p0 == std::string::npos) return false;
    const auto p1 = mesh_shape.find('x', p0 + 1);
    if (p1 == std::string::npos) return false;
    char* endp = nullptr;
    const long z = std::strtol(mesh_shape.c_str() + static_cast<long>(p1 + 1), &endp, 10);
    return endp && *endp == '\0' && z > 1;
}

bool parseMeshShape3D_(const std::string& mesh_shape, uint32_t& dim_x, uint32_t& dim_y, uint32_t& dim_z) {
    dim_x = 0;
    dim_y = 0;
    dim_z = 1;
    const auto p0 = mesh_shape.find('x');
    if (p0 == std::string::npos) return false;
    const auto p1 = mesh_shape.find('x', p0 + 1);
    if (p1 == std::string::npos) return false;
    char* endp = nullptr;
    const long x = std::strtol(mesh_shape.c_str(), &endp, 10);
    if (!endp || static_cast<size_t>(endp - mesh_shape.c_str()) != p0 || x <= 0) return false;
    const long y = std::strtol(mesh_shape.c_str() + static_cast<long>(p0 + 1), &endp, 10);
    if (!endp || static_cast<size_t>(endp - mesh_shape.c_str()) != p1 || y <= 0) return false;
    const long z = std::strtol(mesh_shape.c_str() + static_cast<long>(p1 + 1), &endp, 10);
    if (!endp || *endp != '\0' || z <= 0) return false;
    dim_x = static_cast<uint32_t>(x);
    dim_y = static_cast<uint32_t>(y);
    dim_z = static_cast<uint32_t>(z);
    return true;
}

uint64_t getMapValueOrZero_(const std::map<std::string, uint64_t>& values, const char* key) {
    if (!key) return 0;
    auto it = values.find(key);
    if (it == values.end()) return 0;
    return it->second;
}

void setStatIfMissingOrZero_(std::map<std::string, uint64_t>& stats, const char* key, uint64_t value) {
    if (!key || value == 0) return;
    auto it = stats.find(key);
    if (it != stats.end() && it->second > 0) return;
    stats[key] = value;
}

std::string classifyHomeAccessForNode_(
    uint32_t node_id,
    const std::string& mesh_shape,
    int home_stack_id) {
    if (home_stack_id < 0) return "";
    uint32_t dim_x = 0;
    uint32_t dim_y = 0;
    uint32_t dim_z = 1;
    if (!parseMeshShape3D_(mesh_shape, dim_x, dim_y, dim_z)) return "";
    if (dim_x == 0 || dim_y == 0 || dim_z == 0) return "";
    const uint32_t nodes_per_layer = dim_x * dim_y;
    if (nodes_per_layer == 0) return "";
    const uint32_t local = node_id % nodes_per_layer;
    const uint32_t x = local % dim_x;
    const uint32_t y = local / dim_x;
    const uint32_t z = node_id / nodes_per_layer;
    const uint32_t sx = (x >= (dim_x / 2)) ? 1u : 0u;
    const uint32_t sy = (y >= (dim_y / 2)) ? 1u : 0u;
    const int local_stack_id = static_cast<int>(sy * 2u + sx);
    if (home_stack_id != local_stack_id) return "remote_home";
    if (z > 0) return "same_xy_cross_tier";
    return "tier_local_home";
}

std::string normalizeSynapseRouteImpl_(std::string impl) {
    for (char& ch : impl) {
        if (ch >= 'A' && ch <= 'Z') ch = static_cast<char>(ch - 'A' + 'a');
    }
    if (impl.empty()) return "legacy_2d";
    if (impl == "3d" || impl == "native3d") return "native_3d";
    if (impl == "legacy" || impl == "2d") return "legacy_2d";
    return impl;
}

std::unique_ptr<ISynapseRoute> makeSynapseRoute_(const SST::Params& params) {
    std::string impl = normalizeSynapseRouteImpl_(params.find<std::string>("synapse_route_impl", "legacy_2d"));
    if (impl == "auto") {
        const bool native_3d_enable = params.find<int>("native_3d_enable", 0) != 0;
        const std::string mesh_shape = params.find<std::string>("mesh_shape", "");
        impl = (native_3d_enable || meshShapeHasMultipleLayers_(mesh_shape)) ? "native_3d" : "legacy_2d";
    }
    if (impl == "native_3d") {
        return std::make_unique<SynapseRouteSubsystem3D>();
    }
    return std::make_unique<SynapseRouteSubsystem>();
}

std::string normalizePulseMetadataMaskToken_(std::string token) {
    for (char& ch : token) {
        ch = static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
    }
    token.erase(
        std::remove_if(
            token.begin(),
            token.end(),
            [](unsigned char ch) {
                return ch == '_' || ch == '-' || std::isspace(ch) != 0;
            }),
        token.end());
    return token;
}

uint32_t parsePulseMetadataObjectMask_(const std::string& raw_mask) {
    if (raw_mask.empty()) return 0u;

    uint32_t mask = 0u;
    size_t start = 0u;
    while (start <= raw_mask.size()) {
        const size_t end = raw_mask.find_first_of(",|+; ", start);
        const std::string token = normalizePulseMetadataMaskToken_(
            raw_mask.substr(
                start,
                (end == std::string::npos) ? std::string::npos : (end - start)));
        if (!token.empty()) {
            if (token == "all") {
                mask |= PeLocalServiceObjectTable::kMetadataKindMaskAll;
            } else if (token == "preband") {
                mask |= PeLocalServiceObjectTable::kMetadataKindMaskPreband;
            } else if (token == "prebase" || token == "base" || token == "premphfbase") {
                mask |= PeLocalServiceObjectTable::kMetadataKindMaskPreMphfBase;
            } else if (token == "band" || token == "premphfband") {
                mask |= PeLocalServiceObjectTable::kMetadataKindMaskPreMphfBand;
            } else if (token == "idx2" || token == "idx2row") {
                mask |= PeLocalServiceObjectTable::kMetadataKindMaskIdx2Row;
            } else if (token == "rowidx" || token == "rowindex") {
                mask |= PeLocalServiceObjectTable::kMetadataKindMaskRowIndex;
            } else if (token == "rowdescriptor") {
                mask |= PeLocalServiceObjectTable::kMetadataKindMaskRowDescriptor;
            }
        }
        if (end == std::string::npos) break;
        start = end + 1u;
    }
    return mask;
}

} // namespace

void SnnWorkload::markComputeActivity_() {
    compute_activity_pending_ = true;
}

SnnWorkload::SnnWorkload() = default;

SnnWorkload::~SnnWorkload() {
    while (!incoming_spikes_.empty()) {
        delete incoming_spikes_.front();
        incoming_spikes_.pop();
    }
}

void SnnWorkload::adoptWeightReader(std::unique_ptr<IWeightReader> reader) {
    if (!reader) return;
    if (weight_reader_) return;
    weight_reader_ = std::move(reader);
    weight_mem_subsystem_ = dynamic_cast<WeightMemorySubsystem*>(weight_reader_.get());
    if (weight_mem_subsystem_) {
        weight_mem_subsystem_->bindMemory(rt_.mem);
    }
}

void SnnWorkload::configureFromParams(const SST::Params& params) {
    // Phase4 Task6.1: cache params for compute core creation/config.
    params_ = std::make_unique<SST::Params>(/*copy*/params);
    compute_core_impl_ = params.find<std::string>("compute_core_impl", "default");
    // Layout params are normalized in bindRuntime() because different scripts historically
    // used different "num_neurons/global_neuron_base" conventions (per-core vs per-PE).
    num_neurons_param_ = params.find<uint32_t>("num_neurons", 64);
    global_neuron_base_param_ = params.find<uint64_t>("global_neuron_base", 0);
    neurons_per_pe_param_ = params.find<uint32_t>("neurons_per_pe", 0);
    num_neurons_ = num_neurons_param_;
    global_neuron_base_ = global_neuron_base_param_;
    node_neuron_base_ = 0;
    layout_normalized_ = false;
    total_nodes_cfg_ = params.find<uint32_t>("total_nodes", 16);
    apply_acc_enable_ = params.find<int>("apply_acc_enable", 0) != 0;
    gas_window_mode_ = params.find<int>("gas_window_mode", 0) != 0;
    window_read_enable_ = params.find<int>("window_read_enable", 0) != 0;
    window_read_debug_ = params.find<int>("window_read_debug", 0) != 0;
    scheme1_enable_ = params.find<int>("scheme1_enable", 0) != 0;
    const std::string index_mode_str = params.find<std::string>("index_mode", "pre_row_post_col");
    use_post_row_pre_col_ =
        (index_mode_str == "post_row_pre_col") ||
        (index_mode_str == "bcsr_post_row") ||
        (index_mode_str == "csr_post_row");
    use_bcsr_ = (index_mode_str == "bcsr_post_row");
    {
        std::string mode = params.find<std::string>("synapse_weight_mode", "bcsr_gas");
        for (char& ch : mode) {
            if (ch >= 'A' && ch <= 'Z') ch = static_cast<char>(ch - 'A' + 'a');
        }
        if (mode == "gscc_valueonly_dstcore") mode = "gcss_valueonly_dstcore";
        if (mode == "gscc_valueonly_dstcore_vlf_premphf") mode = "gcss_valueonly_dstcore_vlf_premphf";
        if (mode == "gscc_valueonly_dstcore_vlf_premphf_plp") mode = "gcss_valueonly_dstcore_vlf_premphf_plp";
        if (mode != "bcsr_gas" &&
            mode != "gcss_valueonly_dstcore" &&
            mode != "gcss_valueonly_dstcore_idx2" &&
            mode != "gcss_idx2_rowmphf" &&
            mode != "gcss_valueonly_dstcore_vlf_premphf" &&
            mode != "gcss_valueonly_dstcore_vlf_premphf_plp") {
            mode = "bcsr_gas";
        }
        synapse_weight_mode_ = mode;
    }
    const bool gcss_valueonly_mode =
        (synapse_weight_mode_ == "gcss_valueonly_dstcore") ||
        (synapse_weight_mode_ == "gcss_valueonly_dstcore_idx2") ||
        (synapse_weight_mode_ == "gcss_idx2_rowmphf") ||
        (synapse_weight_mode_ == "gcss_valueonly_dstcore_vlf_premphf") ||
        (synapse_weight_mode_ == "gcss_valueonly_dstcore_vlf_premphf_plp");
    if (gcss_valueonly_mode) {
        use_bcsr_ = false;
    }
    snn_edge_record_attempt_total_ = 0;
    snn_edge_record_commit_total_ = 0;
    snn_edge_record_skip_gate_total_ = 0;
    snn_edge_record_skip_stage_total_ = 0;
    snn_edge_record_skip_capacity_total_ = 0;
    snn_edge_record_skip_reject_total_ = 0;
    snn_edge_record_fastpath_handler_entry_total_ = 0;
    snn_edge_record_fastpath_wms_missing_total_ = 0;
    snn_edge_record_fastpath_backend_not_ready_total_ = 0;
    snn_edge_record_fastpath_stage_block_total_ = 0;
    snn_edge_record_process_local_handler_entry_total_ = 0;
    snn_edge_record_process_local_wms_missing_total_ = 0;
    snn_edge_record_process_local_backend_not_ready_total_ = 0;
    snn_edge_record_process_local_stage_block_total_ = 0;
    snn_edge_record_deliver_window_handler_entry_total_ = 0;
    snn_edge_record_deliver_window_wms_missing_total_ = 0;
    snn_edge_record_deliver_window_backend_not_ready_total_ = 0;
    snn_edge_record_deliver_window_stage_block_total_ = 0;
    snn_begin_apply_prev_edges_total_ = 0;
    snn_begin_apply_prev_empty_total_ = 0;
    snn_issue_from_edges_calls_total_ = 0;
    // Phase10: GAS/window 模式下默认启用 strict window-read spike input（由 workload 直接记录 edge/touch）。
    // 兼容性：某些环境可能会把未显式设置的参数默认注入为 0，此时不应“误关掉”窗口路径，因此将 0 视为 auto。
    const int wsi = params.find<int>("workload_spike_input_enable", -1);
    const bool auto_enable =
        (apply_acc_enable_ && gas_window_mode_ && window_read_enable_ && !scheme1_enable_);
    if (wsi > 0) {
        workload_spike_input_enable_ = true;
    } else if (wsi == 0) {
        workload_spike_input_enable_ = auto_enable;
    } else {
        workload_spike_input_enable_ = auto_enable;
    }

    step_seed_only_mode_ = params.find<int>("step_seed_only_mode", 0) != 0;
    experimental_spiketile_enable_ = params.find<int>("experimental_spiketile_enable", 0) != 0;
    experimental_spikekey_fastpath_enable_ = params.find<int>("experimental_spikekey_fastpath_enable", 0) != 0;
    experimental_spiketile_max_pre_bits_ = params.find<uint32_t>("experimental_spiketile_max_pre_bits", 64);
    if (experimental_spiketile_max_pre_bits_ == 0 || experimental_spiketile_max_pre_bits_ > 64) {
        experimental_spiketile_max_pre_bits_ = 64;
    }
    const uint32_t default_block_cols = params.find<uint32_t>("bcsr_block_cols", 0);
    experimental_spiketile_block_cols_ = params.find<uint32_t>("experimental_spiketile_block_cols", default_block_cols);
    experimental_compact_mask_enable_ = params.find<int>("experimental_compact_mask_enable", 0) != 0;
    experimental_inter_bundle_enable_ = params.find<int>("experimental_inter_bundle_enable", 0) != 0;
    experimental_inter_bundle_max_entries_ = params.find<uint32_t>("experimental_inter_bundle_max_entries", 64);
    if (experimental_inter_bundle_max_entries_ == 0) {
        experimental_inter_bundle_max_entries_ = 64;
    }
    experimental_inter_bundle_v2_enable_ = params.find<int>("experimental_inter_bundle_v2_enable", 0) != 0;
    enable_weight_fetch_ = params.find<int>("enable_weight_fetch", 0) != 0;
    route_semantics_ = ISynapseRoute::RouteSemanticDescriptor{};
    edge_collector_max_capacity_ = static_cast<size_t>(params.find<uint64_t>("edge_collector_max_capacity", 1'000'000));
    const int record_apply_default = (gas_window_mode_ && apply_acc_enable_) ? 1 : 0;
    record_edge_apply_enable_ = params.find<int>("record_edge_apply_enable", record_apply_default) != 0;
    record_edge_idle_enable_ = params.find<int>("record_edge_idle_enable", 0) != 0;
    record_edge_scatter_enable_ = params.find<int>("record_edge_scatter_enable", 0) != 0;

    cores_per_pe_cfg_ = params.find<uint32_t>("total_cores", 8);
    if (cores_per_pe_cfg_ == 0) cores_per_pe_cfg_ = 1;
    // Defer neurons_per_core/neurons_per_pe derivation to normalizeLayout_().
    neurons_per_core_cfg_ = 0;
    neurons_per_pe_cfg_ = neurons_per_pe_param_;

    // WeightLoader barrier (shared signal): allow memory readers to defer until loader is done.
    loader_done_key_ = params.find<std::string>("loader_done_key", "");
    wait_for_loader_done_ = !loader_done_key_.empty();
    loader_ready_latched_ = false;
    loader_ready_logged_ = false;
    if (wait_for_loader_done_) {
        loader_done_shared_ = std::make_unique<SST::Shared::SharedArray<int>>();
        loader_done_shared_->initialize(loader_done_key_, 1, 0);
    } else {
        loader_done_shared_.reset();
    }

    // Step-gate explicit end handshake knobs (optional; safe defaults).
    gather_quiesce_cycles_ = params.find<uint32_t>("gas_gather_quiesce_cycles", gather_quiesce_cycles_);
    gather_min_cycles_ = params.find<uint32_t>("gas_gather_min_cycles", gather_min_cycles_);
    if (gather_min_cycles_ == 0) gather_min_cycles_ = 1;

    // Reset window-local state.
    gather_seq_ = 0;
    gather_begin_cycle_ = 0;
    gather_last_activity_cycle_ = 0;
    gather_end_requested_ = false;
    scatter_end_requested_ = false;
}

void SnnWorkload::bindRuntime(const Runtime& rt) {
    rt_ = rt;
    normalizeLayout_();
    if (cores_per_pe_cfg_ == 0 || neurons_per_core_cfg_ == 0 || neurons_per_pe_cfg_ == 0 ||
        (neurons_per_pe_cfg_ % cores_per_pe_cfg_) != 0 ||
        static_cast<uint64_t>(neurons_per_pe_cfg_) !=
            static_cast<uint64_t>(cores_per_pe_cfg_) * static_cast<uint64_t>(neurons_per_core_cfg_)) {
        if (rt_.log) {
            rt_.log->fatal(CALL_INFO, -1,
                           "SnnWorkload fatal: 全局布局口径不一致: total_cores=%u neurons_per_core=%u neurons_per_pe=%u (raw: num_neurons=%u neurons_per_pe=%u base=0x%" PRIx64 ")\n",
                           cores_per_pe_cfg_,
                           neurons_per_core_cfg_,
                           neurons_per_pe_cfg_,
                           num_neurons_param_,
                           neurons_per_pe_param_,
                           static_cast<uint64_t>(global_neuron_base_param_));
        }
        std::abort();
    }
    if (weight_mem_subsystem_) {
        weight_mem_subsystem_->bindMemory(rt_.mem);
    }
    if (semantic_region_workload_) {
        semantic_region_workload_->bindRuntime(rt_);
    }
    // 若 route/comm 已装配，则更新 runtime 依赖（log/stat/transport 指针）
    if (synapse_route_) {
        synapse_route_->bindRuntime(rt_.log,
                                    rt_.node_id,
                                    rt_.core_id,
                                    num_neurons_,
                                    neurons_per_pe_cfg_,
                                    rt_.sinks.stat_routes_entries_total);
        synapse_route_->bindFanoutStat(rt_.sinks.stat_fanout_per_spike_total);
        ISynapseRoute::RouteRuntimeStatSinks route_runtime_stats{};
        route_runtime_stats.route3d_native_activation_total = rt_.sinks.route3d_native_activation_total;
        route_runtime_stats.route3d_native_gating_activation_total =
            rt_.sinks.route3d_native_gating_activation_total;
        route_runtime_stats.route3d_native_direct_activation_total =
            rt_.sinks.route3d_native_direct_activation_total;
        route_runtime_stats.route3d_native_unique_sources_total =
            rt_.sinks.route3d_native_unique_sources_total;
        route_runtime_stats.stat_route3d_native_activation_total = rt_.sinks.stat_route3d_native_activation_total;
        route_runtime_stats.stat_route3d_native_gating_activation_total =
            rt_.sinks.stat_route3d_native_gating_activation_total;
        route_runtime_stats.stat_route3d_native_direct_activation_total =
            rt_.sinks.stat_route3d_native_direct_activation_total;
        route_runtime_stats.stat_route3d_native_unique_sources_total =
            rt_.sinks.stat_route3d_native_unique_sources_total;
        synapse_route_->bindRouteRuntimeStats(route_runtime_stats);
    }
    if (spike_comm_) {
        ISpikeTransport* transport = nullptr;
        // Strict universal-kernel boundary: workload=snn must route via INocTransport (NocPacketEvent),
        // not via legacy parent->sendSpike(SpikeEvent*) path.
        if (!rt_.noc) {
            if (rt_.log) rt_.log->fatal(CALL_INFO, -1, "SnnWorkload requires Runtime.noc (INocTransport) for spike comm\n");
            std::abort();
        }
        if (!noc_spike_transport_) noc_spike_transport_ = std::make_unique<NocSpikeTransport>();
        noc_spike_transport_->setNocTransport(rt_.noc);
        noc_spike_transport_->setSourceCore(static_cast<int>(rt_.core_id));
        noc_spike_transport_->configureLayout(total_nodes_cfg_, cores_per_pe_cfg_, neurons_per_core_cfg_);
        transport = noc_spike_transport_.get();
        SpikeCommRuntimeConfig crt{};
        crt.log = rt_.log;
        crt.transport = transport;
        crt.noc = rt_.noc;
        crt.src_core = static_cast<int>(rt_.core_id);
        crt.node_id = static_cast<uint32_t>(rt_.node_id);
        crt.active_step_seq = &gather_seq_;
        crt.synapse_route = synapse_route_.get();
        crt.global_neuron_base = global_neuron_base_;
        crt.experimental_spiketile_enable = experimental_spiketile_enable_;
        crt.experimental_spiketile_max_pre_bits = experimental_spiketile_max_pre_bits_;
        crt.experimental_spiketile_block_cols = experimental_spiketile_block_cols_;
        crt.experimental_compact_mask_enable = experimental_compact_mask_enable_;
        crt.experimental_inter_bundle_enable = experimental_inter_bundle_enable_;
        crt.experimental_inter_bundle_max_entries = experimental_inter_bundle_max_entries_;
        crt.experimental_inter_bundle_v2_enable = experimental_inter_bundle_v2_enable_;
        spike_comm_->bindRuntime(crt);
    }
}

void SnnWorkload::normalizeLayout_() {
    if (layout_normalized_) return;
    layout_normalized_ = true;

    uint32_t weights_cols = 0;
    if (params_) weights_cols = params_->find<uint32_t>("weights_cols", 0);

    const auto n =
        normalizeNeuronLayout(static_cast<uint32_t>(rt_.node_id),
                              static_cast<uint32_t>(rt_.core_id),
                              total_nodes_cfg_,
                              cores_per_pe_cfg_,
                              num_neurons_param_,
                              neurons_per_pe_param_,
                              global_neuron_base_param_,
                              weights_cols);

    total_nodes_cfg_ = n.total_nodes;
    cores_per_pe_cfg_ = n.cores_per_pe;
    neurons_per_core_cfg_ = n.neurons_per_core;
    neurons_per_pe_cfg_ = n.neurons_per_pe;
    node_neuron_base_ = n.node_neuron_base;
    num_neurons_ = neurons_per_core_cfg_;

    const uint64_t base_param = static_cast<uint64_t>(global_neuron_base_param_);
    global_neuron_base_ = n.core_neuron_base;
    if (n.base_match_score == 0 && rt_.log) {
        rt_.log->verbose(CALL_INFO, 1, 0,
                         "⚠️ SnnWorkload layout normalize: global_neuron_base(0x%" PRIx64 ") 与推导不一致，回退到 core_base=0x%" PRIx64 " (node=%u core=%u)\n",
                         base_param,
                         static_cast<uint64_t>(global_neuron_base_),
                         static_cast<uint32_t>(rt_.node_id),
                         static_cast<uint32_t>(rt_.core_id));
    }
}

uint64_t SnnWorkload::nowNs_() const {
    if (rt_.time.now_ns) return rt_.time.now_ns(rt_.time.ctx);
    // Fallback: best-effort (legacy behavior assumes 1GHz => 1 cycle == 1ns anyway).
    return now_cycle_cached_;
}

bool SnnWorkload::isPreLocal_(uint32_t pre_global) const {
    return (pre_global >= global_neuron_base_) &&
           (pre_global < global_neuron_base_ + static_cast<uint64_t>(num_neurons_));
}

uint32_t SnnWorkload::remapPreGlobalModulo_(uint32_t pre_global) const {
    if (num_neurons_ == 0) return 0;
    const uint64_t width = static_cast<uint64_t>(num_neurons_);
    const uint64_t base =
        static_cast<uint64_t>(global_neuron_base_) - static_cast<uint64_t>(rt_.core_id) * width;
    const uint64_t diff = static_cast<uint64_t>(pre_global) - base;
    return static_cast<uint32_t>(diff % width);
}

uint32_t SnnWorkload::mapPreGlobalToLocal_(uint32_t pre_global) const {
    if (isPreLocal_(pre_global)) {
        return static_cast<uint32_t>(static_cast<uint64_t>(pre_global) - global_neuron_base_);
    }
    return remapPreGlobalModulo_(pre_global);
}

bool SnnWorkload::ensureLoaderReady_() {
    if (!wait_for_loader_done_) return true;
    if (loader_ready_latched_) return true;
    if (!loader_done_shared_) return true;
    if (loader_done_shared_->size() == 0) return false;
    const int ready = loader_done_shared_->mutex_read(0);
    if (ready != 0) {
        loader_ready_latched_ = true;
        if (window_read_debug_ && !loader_ready_logged_ && rt_.log) {
            rt_.log->verbose(CALL_INFO, 2, 0,
                             "[diag-loader] workload=snn core=%u weights_ready at cycle=%" PRIu64 "\n",
                             static_cast<uint32_t>(rt_.core_id),
                             static_cast<uint64_t>(now_cycle_cached_));
        }
        loader_ready_logged_ = true;
        return true;
    }
    return false;
}

void SnnWorkload::ensureWeightReaderOwned_() {
    normalizeLayout_();

    if (!params_) {
        if (rt_.log) rt_.log->fatal(CALL_INFO, -1, "SnnWorkload missing cached Params (configureFromParams not called?)\n");
        std::abort();
    }

    if (!weight_reader_) {
        // === Build local cache/weight accessor/BCSR manager (workload-owned) ===
        const uint32_t max_cache_entries = params_->find<uint32_t>("max_cache_entries", 65536);
        const bool use_clock_weight_cache = params_->find<int>("use_clock_weight_cache", 0) != 0;
        const bool disable_weight_cache = params_->find<int>("disable_weight_cache", 0) != 0;

        if (!weight_cache_ops_) weight_cache_ops_ = std::make_unique<WeightCacheOps>();
        {
            WeightCacheOps::Config cache_cfg{};
            cache_cfg.max_entries = max_cache_entries;
            cache_cfg.use_clock = use_clock_weight_cache;
            cache_cfg.disable_cache = disable_weight_cache;
            weight_cache_ops_->configure(cache_cfg, /*on_evict*/[](uint64_t){});
            weight_cache_ops_->reserve(cache_cfg.max_entries ? cache_cfg.max_entries : 1);
        }

        if (!weight_accessor_) weight_accessor_ = std::make_unique<WeightAccessor>();
        uint32_t weights_cols = params_->find<uint32_t>("weights_cols", 0);
        if (weights_cols == 0) weights_cols = num_neurons_;
        weight_accessor_->configure(WeightAccessorConfig{
            static_cast<uint32_t>(rt_.core_id),
            static_cast<uint64_t>(global_neuron_base_),
            static_cast<uint32_t>(num_neurons_),
            static_cast<uint32_t>(weights_cols),
            use_post_row_pre_col_
        });

        if (!bcsr_mgr_) bcsr_mgr_ = std::make_unique<BcsrWeightManager>();
        if (use_bcsr_) {
            const uint64_t base_addr = params_->find<uint64_t>("base_addr", 0);
            const uint64_t rp_off = params_->find<uint64_t>("bcsr_rowptr_offset", 0);
            const uint64_t ci_off = params_->find<uint64_t>("bcsr_colidx_offset", 0);
            const uint64_t bd_off = params_->find<uint64_t>("bcsr_blockdata_offset", 0);
            const uint64_t id_off = params_->find<uint64_t>("bcsr_blockids_offset", 0);
            const uint32_t br = params_->find<uint32_t>("bcsr_block_rows", 16);
            const uint32_t bc = params_->find<uint32_t>("bcsr_block_cols", 16);
            const uint32_t idxb = params_->find<uint32_t>("bcsr_idx_bytes", 2);
            const uint32_t valb = params_->find<uint32_t>("bcsr_val_bytes", 4);
            const std::string layout_mode = params_->find<std::string>("bcsr_layout_mode", "flat");
            const uint32_t colidx_row_stride_bytes = params_->find<uint32_t>("bcsr_colidx_row_stride_bytes", 0);
            const uint32_t blockdata_row_stride_bytes = params_->find<uint32_t>("bcsr_blockdata_row_stride_bytes", 0);
            const uint32_t blockids_row_stride_bytes = params_->find<uint32_t>("bcsr_blockids_row_stride_bytes", 0);
            const uint64_t rowptr_addr = base_addr + rp_off;
            const uint64_t colidx_addr = base_addr + ci_off;
            const uint64_t blockdata_addr = base_addr + bd_off;
            const uint64_t blockids_addr = id_off ? (base_addr + id_off) : 0;
            bcsr_mgr_->configure(rowptr_addr, colidx_addr, blockdata_addr, blockids_addr,
                                 br, bc, idxb, valb,
                                 layout_mode,
                                 colidx_row_stride_bytes,
                                 blockdata_row_stride_bytes,
                                 blockids_row_stride_bytes);
            // Row-index cache (colidx) 是 Apply 的关键路径：cap 太小会导致每窗重复 colidx burst → bursts 不降 → apply_ns 不降。
            // 默认不强制覆盖用户配置；仅当显式启用 auto_fit 时，自动扩到覆盖本 core 的全部 block rows（语义不变，仅减少重复读）。
            uint32_t row_cap = params_->find<uint32_t>("bcsr_row_index_cache_cap", 64);
            const bool row_auto_fit = params_->find<int>("bcsr_row_index_cache_auto_fit", 0) != 0;
            if (row_auto_fit && row_cap > 0) {
                const uint32_t br_eff = br ? br : 16;
                const uint32_t n_block_rows =
                    br_eff ? ((num_neurons_ + br_eff - 1u) / br_eff) : static_cast<uint32_t>(num_neurons_);
                if (n_block_rows > 0 && row_cap < n_block_rows) {
                    if (rt_.log) {
                        rt_.log->verbose(CALL_INFO, 2, 0,
                                         "[bcsr] auto-fit row_index_cache_cap %u -> %u (node=%u core=%u rows=%u br=%u)\n",
                                         row_cap,
                                         n_block_rows,
                                         static_cast<uint32_t>(rt_.node_id),
                                         static_cast<uint32_t>(rt_.core_id),
                                         static_cast<uint32_t>(num_neurons_),
                                         br_eff);
                    }
                    row_cap = n_block_rows;
                }
            }
            bcsr_mgr_->setRowIndexCacheCapacity(row_cap);
            bcsr_mgr_->setBlockCacheCapacity(params_->find<uint32_t>("bcsr_block_cache_cap", 256));
            {
                std::string pol = params_->find<std::string>("bcsr_block_cache_policy", "lru");
                for (auto& ch : pol) {
                    if (ch >= 'A' && ch <= 'Z') ch = static_cast<char>(ch - 'A' + 'a');
                }
                if (pol == "fifo") {
                    bcsr_mgr_->setBlockCachePolicy(BcsrWeightManager::BlockCachePolicy::FIFO);
                } else if (pol == "legacy_unordered" || pol == "legacy") {
                    bcsr_mgr_->setBlockCachePolicy(BcsrWeightManager::BlockCachePolicy::LegacyUnordered);
                } else {
                    bcsr_mgr_->setBlockCachePolicy(BcsrWeightManager::BlockCachePolicy::LRU);
                }
            }
        }

        // === Build WeightMemorySubsystem ===
        auto wms = std::make_unique<WeightMemorySubsystem>();
        wms->configure(
            [this](uint64_t key, float& out) -> bool {
                return weight_cache_ops_ ? weight_cache_ops_->tryGet(key, out) : false;
            },
            [this](uint64_t key, float v) {
                if (weight_cache_ops_) weight_cache_ops_->store(key, v);
            });

        const uint64_t base_addr = params_->find<uint64_t>("base_addr", 0);
        const uint32_t line_size_bytes = params_->find<uint32_t>("line_size_bytes", 64);
        std::string dense_layout_mode = params_->find<std::string>("dense_layout_mode", "row_major");
        for (auto& ch : dense_layout_mode) {
            if (ch >= 'A' && ch <= 'Z') ch = static_cast<char>(ch - 'A' + 'a');
        }
        if (dense_layout_mode.empty()) dense_layout_mode = "row_major";
        const bool dense_phys_enable = (dense_layout_mode == "phys_v1");
        const uint32_t dense_phys_dram_row_bytes = params_->find<uint32_t>("dense_phys_dram_row_bytes", 0);

        uint64_t weight_region_end = 0;
        if (dense_phys_enable) {
            const uint32_t cols = use_post_row_pre_col_ ? weights_cols : num_neurons_;
            DensePhysV1Derived d{};
            const bool ok = computeDensePhysV1Derived(num_neurons_, cols, line_size_bytes, dense_phys_dram_row_bytes, d);
            if (!ok) {
                if (rt_.log) {
                    rt_.log->fatal(CALL_INFO, -1,
                                   "SnnWorkload fatal: invalid dense phys_v1 layout rows=%u cols=%u line=%u row_bytes=%u\n",
                                   static_cast<uint32_t>(num_neurons_),
                                   cols,
                                   line_size_bytes,
                                   dense_phys_dram_row_bytes);
                }
                std::abort();
            }
            if (dense_phys_dram_row_bytes != 0 &&
                (base_addr % static_cast<uint64_t>(dense_phys_dram_row_bytes)) != 0) {
                if (rt_.log) {
                    rt_.log->fatal(CALL_INFO, -1,
                                   "SnnWorkload fatal: dense phys_v1 requires base_addr aligned to dram_row_bytes "
                                   "(base=0x%llx row_bytes=%u)\n",
                                   (unsigned long long)base_addr,
                                   dense_phys_dram_row_bytes);
                }
                std::abort();
            }
            weight_region_end = base_addr + d.total_bytes;
        } else {
            weight_region_end =
                base_addr + static_cast<uint64_t>(num_neurons_) * static_cast<uint64_t>(weights_cols) * sizeof(float);
        }

        WeightMemorySubsystem::OrchestratorConfig ocfg{};
        ocfg.accessor = weight_accessor_.get();
        ocfg.cache_try = [this](uint64_t key, float& out) -> bool {
            return weight_cache_ops_ ? weight_cache_ops_->tryGet(key, out) : false;
        };
        ocfg.cache_put = [this](uint64_t key, float v) {
            if (weight_cache_ops_) weight_cache_ops_->store(key, v);
        };
        ocfg.acc_update = [this](uint32_t post_local, float dv) {
            if (acc_ops_) acc_ops_->update(post_local, dv);
        };
        ocfg.report_mem_issue = [this](size_t bytes, bool /*count_weight_read*/) {
            if (rt_.reporting.report_mem_issue) rt_.reporting.report_mem_issue(rt_.reporting.ctx, bytes);
        };
        ocfg.ensure_loader_ready = [this]() { return ensureLoaderReady_(); };
        ocfg.bcsr_rowptr_ready = [this]() { return !use_bcsr_ || (bcsr_mgr_ && bcsr_mgr_->isRowptrReady()); };
        ocfg.ensure_rowptr_ready_or_fatal = [this](const char* reason) {
            if (rt_.log) {
                rt_.log->fatal(CALL_INFO, -1,
                               "SnnWorkload fatal: BCSR rowptr not ready (%s) node=%u core=%u\n",
                               reason ? reason : "unknown",
                               static_cast<uint32_t>(rt_.node_id),
                               static_cast<uint32_t>(rt_.core_id));
            }
            std::abort();
        };
        ocfg.resume_issue_after_rowptr_ready = [this]() {
            if (apply_acc_enable_ && gas_window_mode_ && gas_stage_ == GasStage::Apply && weight_mem_subsystem_) {
                weight_mem_subsystem_->issueFromEdges();
            }
        };
        ocfg.resolve_post_local_by_prerank = [this](uint32_t pre_global, uint32_t pre_rank, uint32_t& out_post_local) -> bool {
            const auto* posts_local = lookupPostsLocalForPre_(pre_global);
            if (!posts_local || pre_rank >= posts_local->size()) return false;
            out_post_local = (*posts_local)[pre_rank];
            return true;
        };
        ocfg.use_bcsr = use_bcsr_;
        ocfg.bcsr_prefetch_all = params_->find<int>("bcsr_prefetch_all", 0) != 0;
        ocfg.bcsr_colidx_inflight_coalesce_enable =
            params_->find<int>("bcsr_colidx_inflight_coalesce_enable", 1) != 0;
        ocfg.bcsr_block_inflight_coalesce_enable =
            params_->find<int>("bcsr_block_inflight_coalesce_enable", 1) != 0;
        ocfg.bcsr_row_index_prefetch_mode =
            params_->find<std::string>("bcsr_row_index_prefetch_mode", "auto");
        ocfg.bcsr_row_index_prefetch_all_rows_threshold =
            params_->find<uint32_t>("bcsr_row_index_prefetch_all_rows_threshold", 1024);
        ocfg.bcsr_row_index_prefetch_all_rows_max_bytes =
            params_->find<uint64_t>("bcsr_row_index_prefetch_all_rows_max_bytes", 64ull * 1024ull);
        ocfg.bcsr_block_cache_auto_tune =
            params_->find<int>("bcsr_block_cache_auto_tune", 1) != 0;
        ocfg.bcsr_block_cache_max_bytes =
            params_->find<uint64_t>("bcsr_block_cache_max_bytes", 64ull * 1024ull * 1024ull);
        ocfg.bcsr_block_cache_tune_miss_ratio =
            params_->find<float>("bcsr_block_cache_tune_miss_ratio", 0.05f);
        ocfg.bcsr_block_cache_tune_min_misses =
            params_->find<uint32_t>("bcsr_block_cache_tune_min_misses", 64);
        ocfg.bcsr_populate_weight_cache_enable =
            params_->find<int>("bcsr_populate_weight_cache_enable", 1) != 0;
        if (disable_weight_cache) ocfg.bcsr_populate_weight_cache_enable = false;
        ocfg.bcsr_force_file_read = params_->find<int>("bcsr_force_file_read", 0) != 0;
        ocfg.bcsr_rowptr_file_fallback_enable = params_->find<int>("bcsr_rowptr_file_fallback_enable", 0) != 0;
        ocfg.bcsr_weight_guard_enable = params_->find<int>("bcsr_weight_guard_enable", 1) != 0;
        ocfg.bcsr_weight_abs_max = params_->find<float>("bcsr_weight_abs_max", 10.0f);
        ocfg.bcsr_semantic_verify_enable = params_->find<int>("bcsr_semantic_verify_enable", 0) != 0;
        ocfg.bcsr_semantic_verify_max_edges = params_->find<uint32_t>("bcsr_semantic_verify_max_edges", 64);
        ocfg.bcsr_semantic_verify_max_mismatch = params_->find<uint32_t>("bcsr_semantic_verify_max_mismatch", 8);
        ocfg.bcsr_semantic_verify_abs_tol = params_->find<float>("bcsr_semantic_verify_abs_tol", 1e-6f);
        ocfg.bcsr_semantic_verify_rel_tol = params_->find<float>("bcsr_semantic_verify_rel_tol", 1e-6f);
        ocfg.readresp_zero_fallback = params_->find<int>("readresp_zero_fallback", 0) != 0;
        ocfg.init_default_weight = params_->find<float>("init_default_weight", 0.5f);
        ocfg.num_neurons = num_neurons_;
        ocfg.weights_cols = weights_cols;
        ocfg.use_post_row_pre_col = use_post_row_pre_col_;
        ocfg.base_addr = base_addr;
        ocfg.weight_region_end = weight_region_end;
        ocfg.dense_layout_mode = dense_phys_enable ? DenseLayoutMode::PhysV1 : DenseLayoutMode::RowMajor;
        ocfg.dense_phys_dram_row_bytes = dense_phys_dram_row_bytes;
        ocfg.read_force_single = params_->find<int>("read_force_single", 0) != 0;
        ocfg.merge_read_cacheline = params_->find<int>("merge_read_cacheline", 1) != 0;
        ocfg.merge_read_row = params_->find<int>("merge_read_row", 0) != 0;
        ocfg.merge_read_auto = params_->find<int>("merge_read_auto", 0) != 0;
        ocfg.line_size_bytes = params_->find<uint32_t>("line_size_bytes", 64);
        ocfg.byte_exact_verify_enable = params_->find<int>("byte_exact_verify_enable", 0) != 0;
        ocfg.byte_exact_verify_mode = params_->find<std::string>("byte_exact_verify_mode", "");
        ocfg.byte_exact_verify_row_scale = params_->find<uint32_t>("byte_exact_verify_row_scale", 1024);
        ocfg.byte_exact_verify_max_mismatch = params_->find<uint32_t>("byte_exact_verify_max_mismatch", 8);
        ocfg.memory_warmup_cycles = params_->find<uint64_t>("memory_warmup_cycles", 0);
        ocfg.loader_barrier_cycles = params_->find<uint64_t>("loader_barrier_cycles", 0);
        ocfg.node_id = rt_.node_id;
        ocfg.core_id = rt_.core_id;
        ocfg.weights_template = params_->find<std::string>("weights_template", "");
        ocfg.bcsr_mgr = bcsr_mgr_.get();
        ocfg.synapse_weight_mode = synapse_weight_mode_;
        ocfg.gcss_index_template = params_->find<std::string>("gcss_index_template", "");
        ocfg.experimental_retire_policy =
            params_->find<std::string>("experimental_retire_policy", "global_inorder");
        ocfg.experimental_retire_shadow_per_post_enable = false;
        const bool pulse_enable = params_->find<int>("pulse_enable", 0) != 0;
        const bool pulse_agenda_observe_only =
            params_->find<int>("pulse_agenda_observe_only", 1) != 0;
        const bool pulse_descriptor_actual_enable =
            params_->find<int>("pulse_descriptor_actual_enable", 0) != 0;
        ocfg.pulse_agenda_enable =
            pulse_enable &&
            (pulse_agenda_observe_only || pulse_descriptor_actual_enable);
        ocfg.pulse_descriptor_actual_enable =
            pulse_enable && pulse_descriptor_actual_enable;
        ocfg.pulse_domain_retire_enable = false;
        ocfg.pulse_domain_retire_observe_only = true;
        ocfg.pulse_frontier_observe_enable =
            pulse_enable && (params_->find<int>("pulse_frontier_observe_enable", 0) != 0);
        ocfg.pulse_frontier_top_lines =
            std::max<uint32_t>(1u, params_->find<uint32_t>("pulse_frontier_top_lines", 32));
        ocfg.pe_internal_cpe_enable =
            params_->find<int>("pe_internal_cpe_enable", 0) != 0;
        ocfg.pe_internal_pod_enable =
            ocfg.pe_internal_cpe_enable &&
            (params_->find<int>("pe_internal_pod_enable", 0) != 0);
        ocfg.pe_internal_pod_metadata_enable =
            ocfg.pe_internal_pod_enable &&
            (params_->find<int>("pe_internal_pod_metadata_enable", 0) != 0);
        ocfg.pe_internal_pod_owner_enable =
            ocfg.pe_internal_pod_enable &&
            (params_->find<int>("pe_internal_pod_owner_enable", 0) != 0);
        {
            const uint32_t configured_pod_count =
                params_->find<uint32_t>("pe_internal_pod_count", 0);
            const uint32_t configured_pod_size =
                params_->find<uint32_t>("pe_internal_pod_size", 0);
            const uint32_t total_cores = std::max<uint32_t>(1u, cores_per_pe_cfg_);
            uint32_t pod_count = 1u;
            if (ocfg.pe_internal_pod_enable) {
                if (configured_pod_count > 0u) {
                    pod_count = configured_pod_count;
                } else if (configured_pod_size > 0u) {
                    pod_count =
                        static_cast<uint32_t>((total_cores + configured_pod_size - 1u) /
                                              configured_pod_size);
                } else {
                    pod_count = total_cores;
                }
                pod_count = std::max<uint32_t>(1u, std::min<uint32_t>(pod_count, total_cores));
            }
            uint32_t pod_size = configured_pod_size;
            if (pod_size == 0u) {
                pod_size =
                    static_cast<uint32_t>((total_cores + pod_count - 1u) / pod_count);
            }
            pod_size = std::max<uint32_t>(1u, pod_size);
            ocfg.pe_internal_pod_count = pod_count;
            ocfg.pe_internal_pod_size = pod_size;
            ocfg.pe_internal_pod_id =
                std::min<uint32_t>(ocfg.core_id / pod_size, pod_count - 1u);
        }
        ocfg.pulse_domain_retire_mode = "per_post";
        std::transform(
            ocfg.pulse_domain_retire_mode.begin(),
            ocfg.pulse_domain_retire_mode.end(),
            ocfg.pulse_domain_retire_mode.begin(),
            [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        if (ocfg.pulse_domain_retire_mode != "descriptor_domain") {
            ocfg.pulse_domain_retire_mode = "per_post";
        }
        ocfg.pulse_domain_retire_release_budget = 0;
        ocfg.experimental_pre_window_profile_export_enable =
            params_->find<int>("experimental_pre_window_profile_export_enable", 0) != 0;
        ocfg.experimental_pre_window_profile_export_dir =
            params_->find<std::string>("experimental_pre_window_profile_export_dir", "");
        ocfg.pulse_osa_metadata_txn_enable = false;
        ocfg.pulse_osa_metadata_ready_lease_enable = false;
        ocfg.pulse_osa_metadata_object_mask = 0u;
        wms->configureOrchestrator(std::move(ocfg));

        const uint32_t window_read_budget = params_->find<uint32_t>("window_read_budget", 1024);
        const uint32_t max_outstanding = params_->find<uint32_t>("max_outstanding_requests", 16);
        wms->configureWindow(window_read_budget, max_outstanding);
        if (window_read_enable_) wms->reserveWindowContainers(num_neurons_);

        wms->bindMemory(rt_.mem);
        weight_mem_subsystem_ = wms.get();
        weight_reader_ = std::move(wms);
    } else {
        if (!weight_mem_subsystem_) {
            weight_mem_subsystem_ = dynamic_cast<WeightMemorySubsystem*>(weight_reader_.get());
        }
        if (weight_mem_subsystem_) {
            weight_mem_subsystem_->bindMemory(rt_.mem);
        }
    }

    if (weight_mem_subsystem_) {
        weight_mem_subsystem_->overrideResolvePostLocalByPreRank(
            [this](uint32_t pre_global, uint32_t pre_rank, uint32_t& out_post_local) -> bool {
                const auto* posts_local = lookupPostsLocalForPre_(pre_global);
                if (!posts_local || pre_rank >= posts_local->size()) return false;
                out_post_local = (*posts_local)[pre_rank];
                return true;
            });
    }

    // Phase4-Task6.4: window accumulator moved into workload=snn; bind WMS acc_update callback.
    if (apply_acc_enable_ && gas_window_mode_) {
        if (!acc_ops_) {
            const bool dense_enable = params_->find<int>("apply_dense_acc_enable", 1) != 0;
            const bool shadow_verify_enable =
                dense_enable && (params_->find<int>("acc_shadow_verify_enable", 0) != 0);
            AccumulatorOpsConfig acc_cfg{};
            acc_cfg.num_neurons = num_neurons_;
            acc_cfg.dense_enable = dense_enable;
            acc_cfg.spill_enable = params_->find<int>("acc_spill_enable", 1) != 0;
            acc_cfg.high_watermark_bytes = params_->find<uint64_t>("acc_high_watermark_bytes", 16 * 1024 * 1024);
            acc_cfg.shadow_verify_enable = shadow_verify_enable;
            acc_cfg.window_read_debug = window_read_debug_;
            acc_cfg.core_id = static_cast<int>(rt_.core_id);
            acc_cfg.verbose = rt_.log ? rt_.log->getVerboseLevel() : 0;
            acc_cfg.out = rt_.log;
            acc_cfg.updates_count = &acc_updates_count_;
            acc_cfg.posts_touched_count = &acc_posts_touched_count_;
            acc_cfg.spill_records_count = &acc_spill_records_count_;
            acc_cfg.spilled_bytes_sum = &acc_spilled_bytes_sum_;
            acc_cfg.hwm_bytes_max = &acc_hwm_bytes_max_;
            acc_ops_ = std::make_unique<AccumulatorOps>(acc_cfg);
        }
        if (weight_mem_subsystem_) {
            weight_mem_subsystem_->overrideAccUpdate([this](uint32_t post_local, float dv) {
                if (acc_ops_) acc_ops_->update(post_local, dv);
            });
        }
    }
}

void SnnWorkload::ensureComputeCoreConfigured_() {
    if (compute_configured_) return;
    normalizeLayout_();
    if (!params_) {
        if (rt_.log) {
            rt_.log->fatal(CALL_INFO, -1,
                           "SnnWorkload missing cached Params during compute configure (configureFromParams not called?)\n");
        }
        std::abort();
    }

    if (!compute_core_) {
        compute_core_ = createComputeCoreByName(compute_core_impl_);
        if (!compute_core_) {
            if (rt_.log) {
                rt_.log->verbose(CALL_INFO, 1, 0,
                                 "⚠️ 未知 compute_core_impl='%s'，回退到 default\n",
                                 compute_core_impl_.c_str());
            }
            compute_core_ = createComputeCoreByName("default");
        }
        if (!compute_core_) {
            if (rt_.log) rt_.log->fatal(CALL_INFO, -1, "createComputeCoreByName failed for both impl and default\n");
            std::abort();
        }
    }

    ComputeCoreContext ctx;
    ctx.core_id = rt_.core_id;
    ctx.node_id = rt_.node_id;
    ctx.num_neurons = num_neurons_;
    ctx.global_neuron_base = global_neuron_base_;
    ctx.neurons_per_pe_cfg = neurons_per_pe_cfg_;
    ctx.log = rt_.log;
    ensureWeightReaderOwned_();
    ctx.weight_reader = weight_reader_.get();
    // Phase10: legacy host removed. Learning writeback is optional; keep disabled unless a future workload hook is added.
    ctx.writeback_fn = [](const std::unordered_map<uint64_t, float>&, float, float) -> bool { return false; };
    compute_core_->configure(ctx, *params_);
    compute_configured_ = true;
}

void SnnWorkload::ensureSemanticRegionWorkload_() {
    if (semantic_region_workload_) {
        semantic_region_workload_->bindRuntime(rt_);
        return;
    }
    if (!params_ || !rt_.mem) return;

    const bool semantic_addressing_enable =
        params_->find<int>("memory_semantic_addressing_enable", 0) != 0;
    if (!semantic_addressing_enable) return;

    StreamWorkload::Config semantic_cfg{};
    semantic_cfg.mem_enable = true;
    semantic_cfg.mem_period_cycles = params_->find<uint64_t>("snn_semantic_region_period_cycles", 0);
    semantic_cfg.mem_req_bytes = params_->find<uint32_t>(
        "snn_semantic_region_req_bytes",
        params_->find<uint32_t>("line_size_bytes", 64));
    if (semantic_cfg.mem_req_bytes == 0) semantic_cfg.mem_req_bytes = 64;
    semantic_cfg.mem_stride_bytes = params_->find<uint32_t>(
        "snn_semantic_region_stride_bytes",
        semantic_cfg.mem_req_bytes);
    if (semantic_cfg.mem_stride_bytes == 0) semantic_cfg.mem_stride_bytes = semantic_cfg.mem_req_bytes;
    semantic_cfg.mem_max_outstanding = params_->find<uint32_t>(
        "snn_semantic_region_max_outstanding",
        params_->find<uint32_t>("max_outstanding_requests", 16));
    if (semantic_cfg.mem_max_outstanding == 0) semantic_cfg.mem_max_outstanding = 1;
    semantic_cfg.mem_region_bytes = params_->find<uint64_t>(
        "memory_semantic_slot_bytes",
        params_->find<uint64_t>("stream_region_bytes", 0));
    semantic_cfg.semantic_memory_enable = true;
    semantic_cfg.semantic_memory_demand_driven_enable = true;
    semantic_cfg.comm_enable = false;
    semantic_cfg.strict = params_->find<int>("stream_strict", 1) != 0;
    semantic_cfg.seed_base = params_->find<uint64_t>("stream_seed", 0);

    semantic_cfg.stream_region.enable = params_->find<int>(
        "stream_region_enable",
        semantic_addressing_enable ? 1 : 0) != 0;
    semantic_cfg.stream_region.base_addr =
        params_->find<uint64_t>("stream_base_addr", rt_.base_addr);
    semantic_cfg.stream_region.period_cycles = params_->find<uint64_t>(
        "stream_region_period_cycles",
        semantic_cfg.mem_period_cycles);
    semantic_cfg.stream_region.region_bytes = params_->find<uint64_t>(
        "stream_region_bytes",
        params_->find<uint64_t>("memory_semantic_slot_bytes", 0));
    semantic_cfg.stream_region.req_bytes = params_->find<uint32_t>(
        "stream_region_req_bytes",
        semantic_cfg.mem_req_bytes);
    semantic_cfg.stream_region.stride_bytes = params_->find<uint32_t>(
        "stream_region_stride_bytes",
        semantic_cfg.mem_stride_bytes);

    semantic_cfg.writeback_region.enable = params_->find<int>(
        "writeback_region_enable",
        semantic_addressing_enable ? 1 : 0) != 0;
    semantic_cfg.writeback_region.base_addr =
        params_->find<uint64_t>("writeback_base_addr", rt_.base_addr);
    semantic_cfg.writeback_region.period_cycles = params_->find<uint64_t>(
        "writeback_region_period_cycles",
        semantic_cfg.mem_period_cycles);
    semantic_cfg.writeback_region.region_bytes =
        params_->find<uint64_t>("writeback_region_bytes", params_->find<uint64_t>("memory_semantic_slot_bytes", 0));
    semantic_cfg.writeback_region.req_bytes = params_->find<uint32_t>(
        "writeback_region_req_bytes",
        semantic_cfg.mem_req_bytes);
    semantic_cfg.writeback_region.stride_bytes = params_->find<uint32_t>(
        "writeback_region_stride_bytes",
        semantic_cfg.mem_stride_bytes);

    if (!semantic_cfg.stream_region.enable &&
        !semantic_cfg.writeback_region.enable) {
        return;
    }

    semantic_region_workload_ = std::make_unique<StreamWorkload>(semantic_cfg);
    semantic_region_workload_->bindRuntime(rt_);
}

bool SnnWorkload::windowScatterModeActive_() const {
    // 在这些模式下，发放/发送闭环由 legacy control-plane 主导，workload 不再做非 window 的 drain+send：
    // - GAS window scatter 模式（apply_acc_enable + gas_window_mode）
    // - scheme1（slice/superstep 驱动的 Scatter 阶段）
    const bool scheme1_enable = params_ ? (params_->find<int>("scheme1_enable", 0) != 0) : false;
    return (apply_acc_enable_ && gas_window_mode_) || scheme1_enable;
}

bool SnnWorkload::shouldDeferScatterCommit_() const {
    if (!weight_mem_subsystem_) return false;
    if (weight_mem_subsystem_->pendingSize() > 0) return true;
    return weight_mem_subsystem_->hasDeferredWork();
}

void SnnWorkload::resetApplyScatterCounters_() {
    acc_updates_count_ = 0;
    acc_posts_touched_count_ = 0;
    acc_spill_records_count_ = 0;
    acc_spilled_bytes_sum_ = 0;
    acc_hwm_bytes_max_ = 0;
}

void SnnWorkload::resetStepRxGateCounters_() {
    step_rx_gate_accept_total_ = 0;
    step_rx_gate_reject_refractory_total_ = 0;
    step_rx_gate_direct_accept_total_ = 0;
    step_rx_gate_direct_reject_refractory_total_ = 0;
    step_rx_gate_fastpath_accept_total_ = 0;
    step_rx_gate_fastpath_reject_refractory_total_ = 0;
}

void SnnWorkload::noteStepRxGateAccept_(StepRxGatePath path) {
    noteStepRxGateAcceptN_(path, 1);
}

void SnnWorkload::noteStepRxGateAcceptN_(StepRxGatePath path, uint64_t n) {
    if (n == 0) return;
    step_rx_gate_accept_total_ += n;
    switch (path) {
        case StepRxGatePath::Direct:
            step_rx_gate_direct_accept_total_ += n;
            break;
        case StepRxGatePath::Fastpath:
            step_rx_gate_fastpath_accept_total_ += n;
            break;
    }
}

void SnnWorkload::noteStepRxGateRejectRefractory_(StepRxGatePath path) {
    noteStepRxGateRejectRefractoryN_(path, 1);
}

void SnnWorkload::noteStepRxGateRejectRefractoryN_(StepRxGatePath path, uint64_t n) {
    if (n == 0) return;
    step_rx_gate_reject_refractory_total_ += n;
    switch (path) {
        case StepRxGatePath::Direct:
            step_rx_gate_direct_reject_refractory_total_ += n;
            break;
        case StepRxGatePath::Fastpath:
            step_rx_gate_fastpath_reject_refractory_total_ += n;
            break;
    }
}

void SnnWorkload::reportStepRxGateCounters_(uint32_t seq) {
    if (seq == 0) return;
    if (!rt_.reporting.report_step_rx_gate) return;
    rt_.reporting.report_step_rx_gate(rt_.reporting.ctx,
                                      seq,
                                      step_rx_gate_accept_total_,
                                      step_rx_gate_reject_refractory_total_,
                                      step_rx_gate_direct_accept_total_,
                                      step_rx_gate_direct_reject_refractory_total_,
                                      step_rx_gate_fastpath_accept_total_,
                                      step_rx_gate_fastpath_reject_refractory_total_);
    resetStepRxGateCounters_();
}

void SnnWorkload::finalizeScatterCommit_(uint32_t superstep) {
    last_scatter_spikes_emitted_ = 0;
    bool compute_active_this_cycle = false;

    // Apply accumulated deltas deterministically (sorted by post id).
    std::vector<std::pair<uint32_t, float>> pairs;
    if (acc_ops_) acc_ops_->collectSortedPairs(pairs);
    const uint64_t acc_updates = acc_updates_count_;
    total_gas_apply_acc_updates_ += acc_updates;
    const uint64_t posts_touched = acc_posts_touched_count_;
    const uint64_t spill_records = acc_spill_records_count_;
    const uint64_t spilled_bytes = acc_spilled_bytes_sum_;
    const uint64_t hwm_bytes = acc_hwm_bytes_max_;
    for (const auto& pr : pairs) {
        const uint32_t post = pr.first;
        const float dv = pr.second;
        if (dv == 0.0f) continue;
        if (compute_core_) compute_core_->applySynapticDelta(post, dv);
        compute_active_this_cycle = true;
    }

    // End cycle + drain fired neurons, then delegate route/comm.
    if (compute_core_) {
        compute_core_->endCycle(now_cycle_cached_);
        std::vector<FireEvent> fired;
        compute_core_->drainOutputs(fired, /*clear=*/true);
        if (!fired.empty()) {
            std::vector<uint32_t> neuron_indices;
            neuron_indices.reserve(fired.size());
            for (const auto& fe : fired) neuron_indices.push_back(fe.neuron_idx);

            uint64_t emitted = 0;
            if (!step_seed_only_mode_) {
                emitted = emitNeuronFireBatch(neuron_indices, now_cycle_cached_);
            }
            last_scatter_spikes_emitted_ = step_seed_only_mode_ ? 0 : (emitted ? emitted : neuron_indices.size());

            const uint64_t fired_cnt = static_cast<uint64_t>(neuron_indices.size());
            if (rt_.sinks.neurons_fired) (*rt_.sinks.neurons_fired) += fired_cnt;
            if (rt_.sinks.spikes_generated) (*rt_.sinks.spikes_generated) += fired_cnt;
            addCountStat_(rt_.sinks.stat_neurons_fired_total, fired_cnt);
            addCountStat_(rt_.sinks.stat_spikes_generated_total, fired_cnt);
            compute_active_this_cycle = true;
        }
    }
    if (compute_active_this_cycle) {
        addCountStat_(rt_.sinks.stat_compute_active_cycles_total, 1);
    }
    if (acc_ops_) acc_ops_->reset();

    // Report scatter spikes for per-window aggregation/stats.
    if (rt_.sinks.spikes_emitted_window) (*rt_.sinks.spikes_emitted_window) = last_scatter_spikes_emitted_;
    if (rt_.sinks.window_spikes_all) (*rt_.sinks.window_spikes_all) += last_scatter_spikes_emitted_;
    total_scatter_spikes_emitted_ += last_scatter_spikes_emitted_;
    if (rt_.sinks.stat_gas_scatter_spikes_emitted_total && last_scatter_spikes_emitted_ > 0) {
        rt_.sinks.stat_gas_scatter_spikes_emitted_total->addData(last_scatter_spikes_emitted_);
    }
    if (rt_.reporting.report_apply_scatter) {
        rt_.reporting.report_apply_scatter(rt_.reporting.ctx,
                                           acc_updates,
                                           posts_touched,
                                           /*spikes_emitted=*/last_scatter_spikes_emitted_,
                                           hwm_bytes,
                                           spill_records,
                                           spilled_bytes);
    }
    ensureSemanticRegionWorkload_();
    if (semantic_region_workload_) {
        StreamWorkload::SemanticMemoryDemand semantic_demand{};
        semantic_demand.stream_region_demands = acc_updates;
        semantic_demand.writeback_region_demands = last_scatter_spikes_emitted_;
        if (!semantic_demand.empty()) {
            semantic_region_workload_->enqueueSemanticDemand(semantic_demand);
        }
    }
    resetApplyScatterCounters_();

    // Step-gate explicit end handshake: request EndScatter after finishing Scatter work.
    if (!scatter_end_requested_ && rt_.reporting.request_gas_end_scatter) {
        rt_.reporting.request_gas_end_scatter(rt_.reporting.ctx, superstep);
        scatter_end_requested_ = true;
    }
}

void SnnWorkload::completeEndScatter_(uint32_t superstep) {
    gas_stage_ = GasStage::Idle;
    if (compute_core_) compute_core_->onStageEndScatter(superstep, last_scatter_spikes_emitted_);
    if (weight_mem_subsystem_) {
        weight_mem_subsystem_->endScatterWindow(superstep);
    }
    reportStepRxGateCounters_(superstep);
    resetStepRxGateCounters_();
    end_scatter_event_pending_ = false;
    end_scatter_event_seq_ = 0;
}

void SnnWorkload::enterBeginGather_(uint32_t superstep) {
    gas_stage_ = GasStage::Gather;
    resetApplyScatterCounters_();
    gather_seq_ = superstep;
    gather_begin_cycle_ = now_cycle_cached_;
    gather_last_activity_cycle_ = now_cycle_cached_;
    gather_end_requested_ = false;
    scatter_end_requested_ = false;
    begin_gather_event_pending_ = false;
    begin_gather_event_seq_ = 0;
    if (acc_ops_) acc_ops_->reset();
    if (weight_mem_subsystem_) {
        weight_mem_subsystem_->beginGatherWindow(window_read_enable_, num_neurons_);
    }
    if (compute_core_) compute_core_->onStageBeginGather(superstep);
}

bool SnnWorkload::tryFinalizeDeferredScatter_() {
    if (!scatter_commit_pending_) return false;
    if (gas_stage_ != GasStage::Scatter) return false;
    // Keep draining residual edge-driven issue queues during Scatter defer.
    // Without another issueFromEdges() trigger, pending queue entries could
    // otherwise remain unissued and cause permanent defer.
    if (weight_mem_subsystem_) {
        weight_mem_subsystem_->issueFromEdges();
    }
    if (shouldDeferScatterCommit_()) {
        if (rt_.log &&
            now_cycle_cached_ >= scatter_defer_diag_next_cycle_ &&
            weight_mem_subsystem_ &&
            static_cast<uint32_t>(rt_.node_id) == 0u &&
            static_cast<uint32_t>(rt_.core_id) == 0u) {
            const auto d = weight_mem_subsystem_->deferredWorkBreakdown();
            rt_.log->verbose(CALL_INFO, 0, 0,
                             "[scatter-defer] node=%u core=%u seq=%u cyc=%" PRIu64
                             " pending_mem=%zu edge_retire=%zu/%zu pending_direct=%zu"
                             " pending_block=%zu pending_colidx=%zu gcss_vlf=%zu\n",
                             static_cast<uint32_t>(rt_.node_id),
                             static_cast<uint32_t>(rt_.core_id),
                             scatter_commit_seq_,
                             now_cycle_cached_,
                             weight_mem_subsystem_->pendingSize(),
                             d.edge_retire_retired,
                             d.edge_retire_total,
                             d.pending_direct_reads,
                             d.pending_block_reads,
                             d.pending_colidx_reads,
                             d.gcss_vlf_issue_queue);
        }
        // Throttle defer diagnostics to once per 10k cycles per core.
        scatter_defer_diag_next_cycle_ = now_cycle_cached_ + 10000u;
        return false;
    }
    const uint32_t seq = scatter_commit_seq_;
    scatter_commit_pending_ = false;
    scatter_commit_seq_ = 0;
    finalizeScatterCommit_(seq);
    if (end_scatter_event_pending_) {
        completeEndScatter_(end_scatter_event_seq_ ? end_scatter_event_seq_ : seq);
    }
    if (begin_gather_event_pending_) {
        enterBeginGather_(begin_gather_event_seq_ ? begin_gather_event_seq_ : seq);
    }
    return true;
}

void SnnWorkload::ensureSpikeCommConfigured_() {
    if (spike_comm_configured_) return;
    normalizeLayout_();
    if (!params_) {
        if (rt_.log) rt_.log->fatal(CALL_INFO, -1, "SnnWorkload missing cached Params for route/comm configure\n");
        std::abort();
    }

    if (!synapse_route_) synapse_route_ = makeSynapseRoute_(*params_);
    if (!spike_comm_) spike_comm_ = std::make_unique<SpikeCommSubsystem>();

    // Build routing config from Params (keep consistent with legacy CoreShell config).
    const std::string routing_mode = params_->find<std::string>("routing_mode", "fixed");
    const std::string weights_template = params_->find<std::string>("weights_template", "");
    uint32_t weights_cols = params_->find<uint32_t>("weights_cols", 0);
    if (weights_cols == 0) weights_cols = num_neurons_;
    const std::string index_mode_str = params_->find<std::string>("index_mode", "pre_row_post_col");
    const bool use_post_row_pre_col =
        (index_mode_str == "post_row_pre_col") || (index_mode_str == "bcsr_post_row") || (index_mode_str == "csr_post_row");
    const bool use_bcsr = (index_mode_str == "bcsr_post_row");

    SpikeCommRoutingConfig cfg{};
    cfg.routing_weight_driven = (routing_mode == "weight_driven");
    cfg.log_weight_details = params_->find<int>("log_weight_details", 0) != 0;
    cfg.verify_routing_weights = params_->find<int>("verify_routing_weights", 0) != 0;
    cfg.route_summary_enable = params_->find<int>("route_summary_enable", 0) != 0;
    cfg.rows = neurons_per_pe_cfg_;
    cfg.cols = weights_cols;
    cfg.total_nodes = total_nodes_cfg_;
    cfg.mesh_shape = params_->find<std::string>("mesh_shape", "");
    cfg.cores_per_pe = cores_per_pe_cfg_;
    cfg.neurons_per_pe = neurons_per_pe_cfg_;
    cfg.use_post_row_pre_col = use_post_row_pre_col;
    cfg.real_synapse_inputs_available = true;
    cfg.weights_template = weights_template;
    cfg.routing_epsilon = params_->find<float>("routing_epsilon", 1e-8f);
    cfg.routing_topk = params_->find<uint32_t>("routing_topk", 0);
    cfg.routing_topk_per_pe = params_->find<uint32_t>("routing_topk_per_pe", 0);
    cfg.route_exclude_self_pe = params_->find<int>("route_exclude_self_pe", 0) != 0;
    cfg.route_layers_mask = params_->find<std::string>("route_layers_mask", "");
    cfg.route_filter_warn = params_->find<int>("route_filter_warn", 1) != 0;
    cfg.mapping_mode = params_->find<std::string>("mapping_mode", "off");
    cfg.mapping_edges_file = params_->find<std::string>("mapping_edges_file", "");
    cfg.mapping_csv_has_header = params_->find<int>("mapping_csv_has_header", 1) != 0;
    cfg.mapping_csv_separator = params_->find<std::string>("mapping_csv_separator", ",");
    cfg.mapping_assume_block_ids = params_->find<int>("mapping_assume_block_ids", 1) != 0;

    // Native multicast routing (default off for backward compatibility)
    const uint32_t multicast_block_dim_x = params_->find<uint32_t>("multicast_block_dim_x", 0);
    const uint32_t multicast_block_dim_y = params_->find<uint32_t>("multicast_block_dim_y", 0);
    const uint32_t multicast_block_dim_z = params_->find<uint32_t>("multicast_block_dim_z", 0);
    cfg.multicast_enable = params_->find<int>("multicast_enable", 0) != 0;
    cfg.multicast_block_w =
        (multicast_block_dim_x > 0) ? multicast_block_dim_x : params_->find<uint32_t>("multicast_block_w", 2);
    cfg.multicast_block_h =
        (multicast_block_dim_y > 0) ? multicast_block_dim_y : params_->find<uint32_t>("multicast_block_h", 2);
    cfg.multicast_block_d = (multicast_block_dim_z > 0) ? multicast_block_dim_z : 1u;
    cfg.multicast_die_local_only = params_->find<int>("multicast_die_local_only", 0) != 0;
    const bool route3d_native_targets_default =
        cfg.multicast_enable &&
        normalizeSynapseRouteImpl_(params_->find<std::string>("synapse_route_impl", "legacy_2d")) == "native_3d" &&
        meshShapeHasMultipleLayers_(cfg.mesh_shape) &&
        cfg.multicast_block_d > 1 &&
        !cfg.multicast_die_local_only;
    cfg.route3d_native_targets =
        params_->find<int>("route3d_native_targets", route3d_native_targets_default ? 1 : 0) != 0;
    cfg.multicast_ingress_policy = params_->find<std::string>("multicast_ingress_policy", "top_left");
    cfg.multicast_inter_policy = params_->find<std::string>("multicast_inter_policy", "xy");
    cfg.multicast_intra_policy = params_->find<std::string>("multicast_intra_policy", "manhattan_x_first");

    cfg.use_bcsr = use_bcsr;
    cfg.base_addr = params_->find<uint64_t>("base_addr", 0);
    if (use_bcsr) {
        cfg.bcsr_br = params_->find<uint32_t>("bcsr_block_rows", 16);
        cfg.bcsr_bc = params_->find<uint32_t>("bcsr_block_cols", 16);
        cfg.bcsr_idx_bytes = params_->find<uint32_t>("bcsr_idx_bytes", 2);
        cfg.bcsr_val_bytes = params_->find<uint32_t>("bcsr_val_bytes", 4);
        const uint64_t rp_off = params_->find<uint64_t>("bcsr_rowptr_offset", 0);
        const uint64_t ci_off = params_->find<uint64_t>("bcsr_colidx_offset", 0);
        const uint64_t bd_off = params_->find<uint64_t>("bcsr_blockdata_offset", 0);
        const uint64_t id_off = params_->find<uint64_t>("bcsr_blockids_offset", 0);
        cfg.bcsr_rowptr_addr = cfg.base_addr + rp_off;
        cfg.bcsr_colidx_addr = cfg.base_addr + ci_off;
        cfg.bcsr_blockdata_addr = cfg.base_addr + bd_off;
        cfg.bcsr_blockids_addr = id_off ? (cfg.base_addr + id_off) : 0;
    }

    synapse_route_->configure(cfg);

    const std::string gating_mode = params_->find<std::string>("gating_mode", "off");
    const uint64_t gating_ttl_cycles = params_->find<uint64_t>("gating_ttl_cycles", 1000);
    const std::string gating_scope = params_->find<std::string>("gating_scope", "inputs");
    synapse_route_->configureGating(/*gating_event_mode=*/(gating_mode == "event"),
                                    /*gating_ttl_cycles=*/gating_ttl_cycles,
                                    /*gating_scope_inputs_only=*/(gating_scope != "all"));
    synapse_route_->bindRuntime(rt_.log,
                                rt_.node_id,
                                rt_.core_id,
                                num_neurons_,
                                neurons_per_pe_cfg_,
                                rt_.sinks.stat_routes_entries_total);
    synapse_route_->bindFanoutStat(rt_.sinks.stat_fanout_per_spike_total);
    ISynapseRoute::RouteRuntimeStatSinks route_runtime_stats{};
    route_runtime_stats.route3d_native_activation_total = rt_.sinks.route3d_native_activation_total;
    route_runtime_stats.route3d_native_gating_activation_total =
        rt_.sinks.route3d_native_gating_activation_total;
    route_runtime_stats.route3d_native_direct_activation_total =
        rt_.sinks.route3d_native_direct_activation_total;
    route_runtime_stats.route3d_native_unique_sources_total =
        rt_.sinks.route3d_native_unique_sources_total;
    route_runtime_stats.stat_route3d_native_activation_total = rt_.sinks.stat_route3d_native_activation_total;
    route_runtime_stats.stat_route3d_native_gating_activation_total =
        rt_.sinks.stat_route3d_native_gating_activation_total;
    route_runtime_stats.stat_route3d_native_direct_activation_total =
        rt_.sinks.stat_route3d_native_direct_activation_total;
    route_runtime_stats.stat_route3d_native_unique_sources_total =
        rt_.sinks.stat_route3d_native_unique_sources_total;
    synapse_route_->bindRouteRuntimeStats(route_runtime_stats);

    // Strict universal-kernel boundary: workload=snn must route via INocTransport (NocPacketEvent),
    // not via legacy parent->sendSpike(SpikeEvent*) path.
    if (!rt_.noc) {
        if (rt_.log) rt_.log->fatal(CALL_INFO, -1, "SnnWorkload requires Runtime.noc (INocTransport) for spike comm\n");
        std::abort();
    }
    if (!noc_spike_transport_) noc_spike_transport_ = std::make_unique<NocSpikeTransport>();
    noc_spike_transport_->setNocTransport(rt_.noc);
    noc_spike_transport_->setSourceCore(static_cast<int>(rt_.core_id));
    noc_spike_transport_->configureLayout(total_nodes_cfg_, cfg.cores_per_pe, neurons_per_core_cfg_);
    ISpikeTransport* transport = noc_spike_transport_.get();

    spike_comm_->configure();
    SpikeCommRuntimeConfig crt{};
    crt.log = rt_.log;
    crt.transport = transport;
    crt.noc = rt_.noc;
    crt.src_core = static_cast<int>(rt_.core_id);
    crt.node_id = static_cast<uint32_t>(rt_.node_id);
    crt.active_step_seq = &gather_seq_;
    crt.synapse_route = synapse_route_.get();
    crt.global_neuron_base = global_neuron_base_;
    crt.experimental_spiketile_enable = experimental_spiketile_enable_;
    crt.experimental_spiketile_max_pre_bits = experimental_spiketile_max_pre_bits_;
    crt.experimental_spiketile_block_cols = experimental_spiketile_block_cols_;
    crt.experimental_compact_mask_enable = experimental_compact_mask_enable_;
    crt.experimental_inter_bundle_enable = experimental_inter_bundle_enable_;
    crt.experimental_inter_bundle_max_entries = experimental_inter_bundle_max_entries_;
    crt.experimental_inter_bundle_v2_enable = experimental_inter_bundle_v2_enable_;
    spike_comm_->bindRuntime(crt);
    spike_comm_->initRouting();
    const auto route_semantics = synapse_route_->describeRouteSemantics();
    route_semantics_ = route_semantics;

    spike_comm_configured_ = true;
}

bool SnnWorkload::onClockTick(uint64_t now_cycle) {
    now_cycle_cached_ = now_cycle;
    bool did = false;
    // Phase4-Task6.1：compute core 的 per-tick 驱动下沉到 workload=snn。
    ensureComputeCoreConfigured_();
    if (compute_core_) {
        compute_core_->onClockTick(now_cycle);
    }
    // Phase4-Task6.2-Step2：weights/memory 子系统所有权迁入 workload=snn，tick 由 workload 直接驱动。
    if (weight_mem_subsystem_) {
        weight_mem_subsystem_->onClockTick(now_cycle);
    }
    ensureSemanticRegionWorkload_();
    if (semantic_region_workload_) {
        const bool semantic_region_did = semantic_region_workload_->onClockTick(now_cycle);
        did = semantic_region_did || did;
    }

    // Phase7-Task1/Phase10: strict window-read spike queue processing moved into workload=snn.
    bool did_spike = false;
    if (workload_spike_input_enable_ && isWindowWorkload_() && window_read_enable_ && !scheme1_enable_) {
        did_spike = processReadySpikes_(nowNs_());
    }
    did = did || did_spike;

    // Phase4-Task6.3: 非 window 模式下的 “endCycle->drain->route/comm” 闭环迁入 workload。
    if (!windowScatterModeActive_() && compute_core_) {
        compute_core_->endCycle(now_cycle);
        std::vector<FireEvent> fired;
        compute_core_->drainOutputs(fired, /*clear=*/true);
        const bool compute_active_this_cycle = compute_activity_pending_ || !fired.empty();
        if (!fired.empty()) {
            const uint64_t fired_cnt = static_cast<uint64_t>(fired.size());
            if (rt_.sinks.neurons_fired) (*rt_.sinks.neurons_fired) += fired_cnt;
            if (rt_.sinks.spikes_generated) (*rt_.sinks.spikes_generated) += fired_cnt;
            addCountStat_(rt_.sinks.stat_neurons_fired_total, fired_cnt);
            addCountStat_(rt_.sinks.stat_spikes_generated_total, fired_cnt);
            std::vector<uint32_t> neuron_indices;
            neuron_indices.reserve(fired.size());
            for (const auto& ev : fired) neuron_indices.push_back(ev.neuron_idx);
            ensureSpikeCommConfigured_();
            (void)emitNeuronFireBatch(neuron_indices, now_cycle);
            did = true;
        }
        if (compute_active_this_cycle) {
            addCountStat_(rt_.sinks.stat_compute_active_cycles_total, 1);
        }
        compute_activity_pending_ = false;
    }

    if (tryFinalizeDeferredScatter_()) {
        did = true;
    }

    // Step-gate explicit end handshake: end Gather when input has been quiescent for N cycles.
    // This is only acted on when the host provides callbacks (otherwise GatherBufferIF's legacy
    // cycle-driven windowing remains in effect).
    if (isWindowWorkload_() &&
        gas_stage_ == GasStage::Gather &&
        !gather_end_requested_ &&
        gather_seq_ != 0 &&
        rt_.reporting.request_gas_end_gather) {
        const uint64_t since_begin =
            (now_cycle_cached_ >= gather_begin_cycle_) ? (now_cycle_cached_ - gather_begin_cycle_) : 0;
        uint64_t quiet =
            (now_cycle_cached_ >= gather_last_activity_cycle_) ? (now_cycle_cached_ - gather_last_activity_cycle_) : 0;
        // In step-gated mode, spikes for this step may still be in flight even if this core
        // hasn't received any yet. Treat NoC non-idle as "activity" to avoid ending Gather
        // before the network has drained enough for inputs to arrive.
        if (rt_.noc && !rt_.noc->isIdle()) {
            gather_last_activity_cycle_ = now_cycle_cached_;
            quiet = 0;
        }
        if (since_begin >= static_cast<uint64_t>(gather_min_cycles_) &&
            quiet >= static_cast<uint64_t>(gather_quiesce_cycles_) &&
            incoming_spikes_.empty()) {
            rt_.reporting.request_gas_end_gather(rt_.reporting.ctx, gather_seq_);
            gather_end_requested_ = true;
        }
    }

    return did;
}

bool SnnWorkload::deliverPacket(NocPacketEvent* packet) {
    // CoreShell 统一以 packet 输入；Spike 的解码/语义处理完全由 workload 承担。
    // NOTE: packet ownership is transferred to this function (it will always delete packet).
    if (!packet) return true;

    const auto kind = packet->packetKind();
    if (kind == NocPacketKind::Spike) {
        ++snn_rx_spike_packets_total_;
        SpikeEvent* spike = SpikeNocCodec::decode(*packet);
        delete packet;
        if (!spike) return true;

        // Reuse the existing spike entrypoint (keeps strict window-read migration gates + legacy fallback).
        deliverSpike(spike);
        return true;
    }

    if (kind == NocPacketKind::SpikeKey || kind == NocPacketKind::SpikeTileKey) {
        if (kind == NocPacketKind::SpikeKey) {
            ++snn_rx_spikekey_total_;
        } else {
            ++snn_rx_spiketilekey_total_;
        }
        const uint64_t ts = packet->timestamp;
        const bool use_fastpath =
            experimental_spikekey_fastpath_enable_ &&
            workload_spike_input_enable_ &&
            isWindowWorkload_() &&
            window_read_enable_ &&
            !scheme1_enable_;

        if (kind == NocPacketKind::SpikeTileKey && experimental_spiketile_enable_) {
            SpikeTileNocCodec::WireSpikeTileKeyV1 tile_ws{};
            SpikeNocCodec::DecodedSpikeKeyMeta tile_meta{};
            const bool tile_ok = SpikeTileNocCodec::decode(packet->payload, tile_ws, &tile_meta);
            SpikeNocCodec::WireSpikeKeyV2 fallback_ws{};
            const bool fallback_ok = SpikeNocCodec::decodeSpikeKeyAny(packet->payload, fallback_ws);
            delete packet;
            if (tile_ok &&
                experimental_spiketile_block_cols_ > 0 &&
                experimental_spiketile_block_cols_ <= 64 &&
                experimental_spiketile_block_cols_ <= experimental_spiketile_max_pre_bits_) {
                if (tile_meta.version == 4) {
                    ++snn_rx_spikekey_v4_total_;
                    ++snn_rx_spiketilekey_v4_total_;
                }
                if (use_fastpath) ++snn_rx_fastpath_packets_total_;
                else ++snn_rx_fallback_packets_total_;
                std::vector<uint32_t> pre_globals;
                SpikeTileNocCodec::collectPreGlobals(tile_ws, experimental_spiketile_block_cols_, pre_globals);
                for (uint32_t pre_global : pre_globals) {
                    if (use_fastpath) (void)expandPreGlobalToWindowEdgesFast_(pre_global);
                    else (void)expandPreGlobalToLocalSpikes_(pre_global, ts);
                }
                return true;
            }
            if (fallback_ok &&
                (fallback_ws.version == 1 || fallback_ws.version == 2 || fallback_ws.version == 3 || fallback_ws.version == 4)) {
                if (fallback_ws.version == 4) {
                    ++snn_rx_spikekey_v4_total_;
                    ++snn_rx_spiketilekey_v4_total_;
                }
                if (use_fastpath) {
                    ++snn_rx_fastpath_packets_total_;
                    (void)expandPreGlobalToWindowEdgesFast_(fallback_ws.pre_global);
                } else {
                    ++snn_rx_fallback_packets_total_;
                    (void)expandPreGlobalToLocalSpikes_(fallback_ws.pre_global, ts);
                }
            } else {
                ++snn_rx_decode_fail_total_;
            }
            return true;
        }

        SpikeNocCodec::WireSpikeKeyV2 ws{};
        const bool ok = SpikeNocCodec::decodeSpikeKeyAny(packet->payload, ws);
        delete packet;
        if (!ok || (ws.version != 1 && ws.version != 2 && ws.version != 3 && ws.version != 4)) {
            ++snn_rx_decode_fail_total_;
            return true;
        }
        if (ws.version == 4) {
            ++snn_rx_spikekey_v4_total_;
        }
        if (use_fastpath) {
            ++snn_rx_fastpath_packets_total_;
            (void)expandPreGlobalToWindowEdgesFast_(ws.pre_global);
        } else {
            ++snn_rx_fallback_packets_total_;
            (void)expandPreGlobalToLocalSpikes_(ws.pre_global, ts);
        }
        return true;
    }

    // 非 Spike packet 由其它 workload 或上层消费；SNN workload 默认丢弃以避免语义漂移。
    delete packet;
    return true;
}

const std::vector<uint32_t>* SnnWorkload::lookupPostsLocalForPre_(uint32_t pre_global) {
    ensureSpikeCommConfigured_();
    if (!synapse_route_) return nullptr;
    auto routes = synapse_route_->routesShared();
    if (!routes) return nullptr;

    if (routes.get() != routes_shared_for_posts_cache_.get()) {
        routes_shared_for_posts_cache_ = routes;
        pre_to_posts_local_.clear();
    }

    auto itc = pre_to_posts_local_.find(pre_global);
    if (itc == pre_to_posts_local_.end()) {
        std::vector<uint32_t> posts_local;
        auto itr = routes->find(pre_global);
        if (itr != routes->end()) {
            const uint32_t denom = (neurons_per_pe_cfg_ > 0) ? neurons_per_pe_cfg_ : num_neurons_;
            if (denom > 0) {
                for (uint32_t dest_global : itr->second) {
                    const uint32_t dest_node = dest_global / denom;
                    if (dest_node != static_cast<uint32_t>(rt_.node_id)) continue;

                    const uint32_t local_in_pe = dest_global % denom;
                    const uint32_t dest_core = (num_neurons_ ? (local_in_pe / num_neurons_) : 0);
                    if (dest_core != static_cast<uint32_t>(rt_.core_id)) continue;

                    const uint32_t post_local = (num_neurons_ ? (local_in_pe % num_neurons_) : 0);
                    if (post_local < num_neurons_) posts_local.push_back(post_local);
                }
            }
        }

        if (!posts_local.empty()) {
            std::sort(posts_local.begin(), posts_local.end());
            posts_local.erase(std::unique(posts_local.begin(), posts_local.end()), posts_local.end());
        }

        itc = pre_to_posts_local_.emplace(pre_global, std::move(posts_local)).first;
    }

    return &(itc->second);
}

bool SnnWorkload::resolvePreRankForPost_(uint32_t pre_global, uint32_t post_local, uint32_t& out_rank) {
    const auto* posts_local = lookupPostsLocalForPre_(pre_global);
    if (!posts_local || posts_local->empty()) return false;
    const auto it = std::lower_bound(posts_local->begin(), posts_local->end(), post_local);
    if (it == posts_local->end() || *it != post_local) return false;
    const size_t idx = static_cast<size_t>(std::distance(posts_local->begin(), it));
    out_rank = static_cast<uint32_t>(idx);
    return true;
}

bool SnnWorkload::expandPreGlobalToWindowEdgesFast_(uint32_t pre_global) {
    if (!(workload_spike_input_enable_ && isWindowWorkload_() && window_read_enable_ && !scheme1_enable_)) {
        return false;
    }
    ++snn_edge_record_fastpath_handler_entry_total_;

    ensureComputeCoreConfigured_();
    ensureWeightReaderOwned_();

    const auto* posts_local = lookupPostsLocalForPre_(pre_global);
    if (!posts_local || posts_local->empty()) return false;
    snn_rx_fastpath_posts_total_ += static_cast<uint64_t>(posts_local->size());

    bool stage_ok = false;
    const bool premphf_mode =
        (synapse_weight_mode_ == "gcss_valueonly_dstcore_vlf_premphf") ||
        (synapse_weight_mode_ == "gcss_valueonly_dstcore_vlf_premphf_plp");
    const bool edge_record_backend_ready = enable_weight_fetch_ && rt_.mem;
    if (edge_record_backend_ready) {
        switch (gas_stage_) {
            case GasStage::Gather:
                stage_ok = true;
                break;
            case GasStage::Apply:
                stage_ok = record_edge_apply_enable_;
                break;
            case GasStage::Idle:
                stage_ok = record_edge_idle_enable_;
                break;
            case GasStage::Scatter:
                stage_ok = record_edge_scatter_enable_;
                break;
            default:
                stage_ok = false;
                break;
        }
    }

    bool did = false;
    for (size_t pre_rank = 0; pre_rank < posts_local->size(); ++pre_rank) {
        const uint32_t post_local = (*posts_local)[pre_rank];
        if (rt_.sinks.spikes_received) (*rt_.sinks.spikes_received)++;
        if (rt_.sinks.stat_spikes_received_total) rt_.sinks.stat_spikes_received_total->addData(1);

        if (apply_acc_enable_ && compute_core_) {
            if (!compute_core_->shouldAcceptSynapticInput(post_local, now_cycle_cached_)) {
                ++snn_rx_fastpath_reject_total_;
                ++snn_edge_record_skip_reject_total_;
                noteStepRxGateRejectRefractory_(StepRxGatePath::Fastpath);
                continue;
            }
        }
        ++snn_rx_fastpath_accept_total_;
        noteStepRxGateAccept_(StepRxGatePath::Fastpath);

        if (gas_stage_ == GasStage::Gather) {
            gather_last_activity_cycle_ = now_cycle_cached_;
        }

        if (weight_mem_subsystem_) {
            ++snn_edge_record_attempt_total_;
            if (!edge_record_backend_ready) {
                ++snn_edge_record_fastpath_backend_not_ready_total_;
                ++snn_edge_record_skip_gate_total_;
            } else if (stage_ok) {
                weight_mem_subsystem_->noteWindowTouch(post_local, pre_global, num_neurons_);
                bool recorded = false;
                const size_t curr_edges = weight_mem_subsystem_->edgesCurrSize();
                if (curr_edges < edge_collector_max_capacity_) {
                    if (premphf_mode) {
                        weight_mem_subsystem_->recordEdgeWithPreRank(
                            post_local,
                            pre_global,
                            std::numeric_limits<float>::quiet_NaN(),
                            static_cast<uint32_t>(pre_rank));
                    } else {
                        weight_mem_subsystem_->recordEdgeWithWeight(
                            post_local,
                            pre_global,
                            std::numeric_limits<float>::quiet_NaN());
                    }
                    recorded = true;
                }
                if (recorded) {
                    ++snn_rx_fastpath_edges_recorded_total_;
                    ++snn_edge_record_commit_total_;
                } else {
                    ++snn_edge_record_skip_capacity_total_;
                }
            } else {
                ++snn_edge_record_fastpath_stage_block_total_;
                ++snn_edge_record_skip_stage_total_;
            }
        } else {
            ++snn_edge_record_fastpath_wms_missing_total_;
            ++snn_edge_record_skip_gate_total_;
        }

        if (rt_.sinks.synaptic_accesses) (*rt_.sinks.synaptic_accesses)++;
        if (rt_.sinks.stat_synaptic_accesses_total) rt_.sinks.stat_synaptic_accesses_total->addData(1);
        did = true;
    }

    return did;
}

bool SnnWorkload::expandPreGlobalToLocalSpikes_(uint32_t pre_global, uint64_t ts) {
    const auto* posts_local = lookupPostsLocalForPre_(pre_global);
    if (!posts_local || posts_local->empty()) return false;

    for (uint32_t post_local : *posts_local) {
        const uint32_t dest_global = static_cast<uint32_t>(global_neuron_base_ + static_cast<uint64_t>(post_local));
        auto* spike = new SpikeEvent(pre_global,
                                     dest_global,
                                     static_cast<uint32_t>(rt_.node_id),
                                     /*weight=*/1.0,
                                     ts);
        deliverSpike(spike);
    }
    return true;
}

bool SnnWorkload::processReadySpikes_(uint64_t now_ns) {
    if (incoming_spikes_.empty()) return false;

    std::vector<SpikeEvent*> ready_spikes;
    ready_spikes.reserve(std::min<size_t>(incoming_spikes_.size(), 256));
    while (!incoming_spikes_.empty()) {
        SpikeEvent* spike = incoming_spikes_.front();
        if (!spike) {
            incoming_spikes_.pop();
            continue;
        }
        if (spike->getTimestamp() >= now_ns) break;
        incoming_spikes_.pop();
        ready_spikes.push_back(spike);
    }

    if (ready_spikes.size() > 1) {
        auto weightBits = [](const SpikeEvent* s) -> uint64_t {
            if (!s) return 0;
            uint64_t bits = 0;
            double w = s->getWeight();
            static_assert(sizeof(double) == sizeof(uint64_t), "double size unexpected");
            std::memcpy(&bits, &w, sizeof(uint64_t));
            return bits;
        };
        std::sort(ready_spikes.begin(), ready_spikes.end(),
                  [&](const SpikeEvent* a, const SpikeEvent* b) {
                      if (a == b) return false;
                      const uint64_t ta = a ? a->getTimestamp() : 0;
                      const uint64_t tb = b ? b->getTimestamp() : 0;
                      if (ta != tb) return ta < tb;
                      const uint32_t dna = a ? a->getDestinationNode() : 0;
                      const uint32_t dnb = b ? b->getDestinationNode() : 0;
                      if (dna != dnb) return dna < dnb;
                      const uint32_t da = a ? a->getDestinationNeuron() : 0;
                      const uint32_t db = b ? b->getDestinationNeuron() : 0;
                      if (da != db) return da < db;
                      const uint32_t sa = a ? a->getSourceNeuron() : 0;
                      const uint32_t sb = b ? b->getSourceNeuron() : 0;
                      if (sa != sb) return sa < sb;
                      const uint64_t wa = weightBits(a);
                      const uint64_t wb = weightBits(b);
                      return wa < wb;
                  });
    }

    for (auto* spike : ready_spikes) {
        processLocalSpike_(spike);
        delete spike;
    }

    return !ready_spikes.empty();
}

void SnnWorkload::processLocalSpike_(SpikeEvent* spike_event) {
    if (!spike_event) return;
    ++snn_edge_record_process_local_handler_entry_total_;
    if (!isWindowWorkload_()) return;
    if (!weight_mem_subsystem_) {
        ++snn_edge_record_process_local_wms_missing_total_;
        ++snn_edge_record_skip_gate_total_;
        return;
    }

    // Map destination to local post index (preserve legacy semantics).
    const uint32_t dest = spike_event->getDestinationNeuron();
    uint32_t post_local = dest;
    bool post_local_valid = true;
    if (spike_event->hasCachedPostLocal()) {
        post_local = spike_event->getCachedPostLocal();
    } else if (dest >= num_neurons_) {
        const uint64_t g = static_cast<uint64_t>(dest);
        if (g >= global_neuron_base_ && g < global_neuron_base_ + static_cast<uint64_t>(num_neurons_)) {
            post_local = static_cast<uint32_t>(g - global_neuron_base_);
        } else {
            post_local_valid = false;
        }
    }
    if (!post_local_valid || post_local >= num_neurons_) return;

    // Compute core gating (kept consistent with legacy: reject before recording any edge/access).
    if (apply_acc_enable_ && compute_core_) {
        if (!compute_core_->shouldAcceptSynapticInput(post_local, now_cycle_cached_)) {
            ++snn_edge_record_skip_reject_total_;
            noteStepRxGateRejectRefractory_(StepRxGatePath::Direct);
            return;
        }
    }
    noteStepRxGateAccept_(StepRxGatePath::Direct);

    if (gas_stage_ == GasStage::Gather) {
        gather_last_activity_cycle_ = now_cycle_cached_;
    }

    // Strict window-read: record edge for BeginApply issueFromEdges() (no immediate dv application here).
    const bool edge_record_backend_ready = enable_weight_fetch_ && rt_.mem;
    if (edge_record_backend_ready) {
        bool stage_ok = false;
        const bool premphf_mode =
        (synapse_weight_mode_ == "gcss_valueonly_dstcore_vlf_premphf") ||
        (synapse_weight_mode_ == "gcss_valueonly_dstcore_vlf_premphf_plp");
        switch (gas_stage_) {
            case GasStage::Gather:
                stage_ok = true;
                break;
            case GasStage::Apply:
                stage_ok = record_edge_apply_enable_;
                break;
            case GasStage::Idle:
                stage_ok = record_edge_idle_enable_;
                break;
            case GasStage::Scatter:
                stage_ok = record_edge_scatter_enable_;
                break;
            default:
                stage_ok = false;
                break;
        }
        ++snn_edge_record_attempt_total_;
        if (stage_ok) {
            bool recorded = false;
            const uint32_t pre_global = spike_event->getSourceNeuron();
            if (premphf_mode) {
                uint32_t pre_rank = 0;
                if (!resolvePreRankForPost_(pre_global, post_local, pre_rank)) {
                    if (rt_.log) {
                        rt_.log->fatal(CALL_INFO, -1,
                                       "SnnWorkload fatal: pre_rank miss in premphf mode "
                                       "(pre=%u post_local=%u node=%u core=%u)\n",
                                       pre_global, post_local,
                                       static_cast<uint32_t>(rt_.node_id),
                                       static_cast<uint32_t>(rt_.core_id));
                    }
                    std::abort();
                }
                const size_t curr_edges = weight_mem_subsystem_->edgesCurrSize();
                if (curr_edges < edge_collector_max_capacity_) {
                    weight_mem_subsystem_->recordEdgeWithPreRank(
                        post_local,
                        pre_global,
                        static_cast<float>(spike_event->getWeight()),
                        pre_rank);
                    recorded = true;
                }
            } else {
                const size_t curr_edges = weight_mem_subsystem_->edgesCurrSize();
                if (curr_edges < edge_collector_max_capacity_) {
                    weight_mem_subsystem_->recordEdgeWithWeight(
                        post_local,
                        pre_global,
                        static_cast<float>(spike_event->getWeight()));
                    recorded = true;
                }
            }
            if (recorded) {
                ++snn_edge_record_commit_total_;
            } else {
                ++snn_edge_record_skip_capacity_total_;
            }
        } else {
            ++snn_edge_record_process_local_stage_block_total_;
            ++snn_edge_record_skip_stage_total_;
        }
    } else {
        ++snn_edge_record_process_local_backend_not_ready_total_;
        ++snn_edge_record_skip_gate_total_;
    }

    // Record synaptic access counters (owned by CoreShell via runtime sinks).
    if (rt_.sinks.synaptic_accesses) (*rt_.sinks.synaptic_accesses)++;
    if (rt_.sinks.stat_synaptic_accesses_total) rt_.sinks.stat_synaptic_accesses_total->addData(1);
}

void SnnWorkload::deliverSpike(SpikeEvent* spike) {
    if (!spike) return;
    ensureComputeCoreConfigured_();

    if (rt_.sinks.spikes_received) (*rt_.sinks.spikes_received)++;
    if (rt_.sinks.stat_spikes_received_total) rt_.sinks.stat_spikes_received_total->addData(1);

    spike->clearLocalCache();
    spike->setTimestamp(nowNs_());
    if (compute_core_) compute_core_->onSpikeDelivered(spike);

    // Resolve post-local (legacy compatible).
    const uint32_t dest = spike->getDestinationNeuron();
    uint32_t post_local = dest;
    bool post_local_valid = true;
    if (dest >= num_neurons_) {
        const uint64_t g = static_cast<uint64_t>(dest);
        if (g >= global_neuron_base_ && g < global_neuron_base_ + static_cast<uint64_t>(num_neurons_)) {
            post_local = static_cast<uint32_t>(g - global_neuron_base_);
        } else {
            post_local_valid = false;
        }
    }
    if (!post_local_valid || post_local >= num_neurons_) {
        delete spike;
        return;
    }

    // Compute core gating (kept consistent with legacy: reject before recording any edge/access).
    if (apply_acc_enable_ && compute_core_) {
        if (!compute_core_->shouldAcceptSynapticInput(post_local, now_cycle_cached_)) {
            noteStepRxGateRejectRefractory_(StepRxGatePath::Direct);
            delete spike;
            return;
        }
    }
    noteStepRxGateAccept_(StepRxGatePath::Direct);

    // Window/GAS mode: record touches + edges immediately (do NOT defer to per-tick queue),
    // so BeginApply can issue reads deterministically even for same-cycle arrivals.
    if (workload_spike_input_enable_ && isWindowWorkload_() && window_read_enable_ && !scheme1_enable_) {
        ++snn_edge_record_deliver_window_handler_entry_total_;
        ensureWeightReaderOwned_();
        if (gas_stage_ == GasStage::Gather) {
            gather_last_activity_cycle_ = now_cycle_cached_;
        }
        if (weight_mem_subsystem_) {
            const bool emit_touch_debug =
                window_read_debug_ &&
                rt_.log &&
                rt_.log->getVerboseLevel() >= 2 &&
                window_touch_debug_log_count_ < 16u;
            uint64_t exp_touch_before = 0;
            uint64_t exp_enqueued_before = 0;
            if (emit_touch_debug) {
                const auto exp_before =
                    weight_mem_subsystem_->experimentalPeInternalPodPathAlignmentStats();
                exp_touch_before = exp_before.idx2row.producer_touch_events_total;
                exp_enqueued_before = exp_before.idx2row.producer_enqueued_total;
            }

            // Record edge for BeginApply issueFromEdges().
            const bool edge_record_backend_ready = enable_weight_fetch_ && rt_.mem;
            if (edge_record_backend_ready) {
                bool stage_ok = false;
                const bool premphf_mode =
        (synapse_weight_mode_ == "gcss_valueonly_dstcore_vlf_premphf") ||
        (synapse_weight_mode_ == "gcss_valueonly_dstcore_vlf_premphf_plp");
                switch (gas_stage_) {
                    case GasStage::Gather:
                        stage_ok = true;
                        break;
                    case GasStage::Apply:
                        stage_ok = record_edge_apply_enable_;
                        break;
                    case GasStage::Idle:
                        stage_ok = record_edge_idle_enable_;
                        break;
                    case GasStage::Scatter:
                        stage_ok = record_edge_scatter_enable_;
                        break;
                    default:
                        stage_ok = false;
                        break;
                }
                ++snn_edge_record_attempt_total_;
                if (stage_ok) {
                    weight_mem_subsystem_->noteWindowTouch(post_local, spike->getSourceNeuron(), num_neurons_);
                    if (emit_touch_debug) {
                        const auto exp_after =
                            weight_mem_subsystem_->experimentalPeInternalPodPathAlignmentStats();
                        rt_.log->verbose(
                            CALL_INFO, 2, 0,
                            "[idx2-touch-debug] core=%u pre=%u post=%u stage=%d mem=%d loader_ready=%d "
                            "touch_before=%" PRIu64 " touch_after=%" PRIu64
                            " enq_before=%" PRIu64 " enq_after=%" PRIu64 "\n",
                            static_cast<uint32_t>(rt_.core_id),
                            spike->getSourceNeuron(),
                            post_local,
                            static_cast<int>(gas_stage_),
                            rt_.mem ? 1 : 0,
                            ensureLoaderReady_() ? 1 : 0,
                            exp_touch_before,
                            exp_after.idx2row.producer_touch_events_total,
                            exp_enqueued_before,
                            exp_after.idx2row.producer_enqueued_total);
                        ++window_touch_debug_log_count_;
                    }
                    bool recorded = false;
                    const uint32_t pre_global = spike->getSourceNeuron();
                    if (premphf_mode) {
                        uint32_t pre_rank = 0;
                        if (!resolvePreRankForPost_(pre_global, post_local, pre_rank)) {
                            if (rt_.log) {
                                rt_.log->fatal(CALL_INFO, -1,
                                               "SnnWorkload fatal: pre_rank miss in premphf mode "
                                               "(pre=%u post_local=%u node=%u core=%u)\n",
                                               pre_global, post_local,
                                               static_cast<uint32_t>(rt_.node_id),
                                               static_cast<uint32_t>(rt_.core_id));
                            }
                            std::abort();
                        }
                        const size_t curr_edges = weight_mem_subsystem_->edgesCurrSize();
                        if (curr_edges < edge_collector_max_capacity_) {
                            weight_mem_subsystem_->recordEdgeWithPreRank(
                                post_local,
                                pre_global,
                                static_cast<float>(spike->getWeight()),
                                pre_rank);
                            recorded = true;
                        }
                    } else {
                        const size_t curr_edges = weight_mem_subsystem_->edgesCurrSize();
                        if (curr_edges < edge_collector_max_capacity_) {
                            weight_mem_subsystem_->recordEdgeWithWeight(
                                post_local,
                                pre_global,
                                static_cast<float>(spike->getWeight()));
                            recorded = true;
                        }
                    }
                    if (recorded) {
                        ++snn_edge_record_commit_total_;
                    } else {
                        ++snn_edge_record_skip_capacity_total_;
                    }
                } else {
                    ++snn_edge_record_deliver_window_stage_block_total_;
                    ++snn_edge_record_skip_stage_total_;
                }
            } else {
                ++snn_edge_record_deliver_window_backend_not_ready_total_;
                ++snn_edge_record_skip_gate_total_;
            }
        } else {
            ++snn_edge_record_deliver_window_wms_missing_total_;
            ++snn_edge_record_skip_gate_total_;
        }

        if (rt_.sinks.synaptic_accesses) (*rt_.sinks.synaptic_accesses)++;
        if (rt_.sinks.stat_synaptic_accesses_total) rt_.sinks.stat_synaptic_accesses_total->addData(1);
        delete spike;
        return;
    }

    // Non-window path: best-effort single-synapse apply.
    if (compute_core_) {
        const uint32_t pre_global = spike->getSourceNeuron();
        if (enable_weight_fetch_) {
            ensureWeightReaderOwned_();
            IWeightReader* wr = weight_reader_.get();
            if (wr) {
                // Weight fetch is async; apply when resolved.
                wr->requestDense(pre_global, post_local, [this, pre_global, post_local](float w) {
                    if (!compute_core_) return;
                    SynapticEvent ev;
                    ev.post_local = post_local;
                    ev.pre_global = pre_global;
                    ev.weight = w;
                    compute_core_->onSynapticEvent(ev);
                    markComputeActivity_();
                    if (rt_.sinks.synaptic_accesses) (*rt_.sinks.synaptic_accesses)++;
                    if (rt_.sinks.stat_synaptic_accesses_total) rt_.sinks.stat_synaptic_accesses_total->addData(1);
                });
                delete spike;
                return;
            }
        }

        SynapticEvent ev;
        ev.post_local = post_local;
        ev.pre_global = pre_global;
        ev.weight = static_cast<float>(spike->getWeight());
        compute_core_->onSynapticEvent(ev);
        markComputeActivity_();
        if (rt_.sinks.synaptic_accesses) (*rt_.sinks.synaptic_accesses)++;
        if (rt_.sinks.stat_synaptic_accesses_total) rt_.sinks.stat_synaptic_accesses_total->addData(1);
    }

    delete spike;
}

bool SnnWorkload::hasWork() const {
    if (!incoming_spikes_.empty()) return true;
    if (weight_mem_subsystem_ &&
        (weight_mem_subsystem_->pendingSize() > 0 || weight_mem_subsystem_->hasDeferredWork())) {
        return true;
    }
    if (semantic_region_workload_ && semantic_region_workload_->hasWork()) {
        return true;
    }
    // NOTE:
    // - For non-window (naive) execution, global step barrier completion uses a quiescent policy
    //   that must reflect in-flight transactions (spike/mem/noc), NOT neuron-state values.
    // - DefaultSnnComputeCore::hasWork() historically used v_mem threshold heuristics, which can
    //   remain true for long periods and would stall step completion indefinitely.
    // - Therefore, only treat compute_core_->hasWork() as "blocking" when the workload is in a
    //   window/scatter-driven mode (GAS or scheme1), where the core's stage machine defines work.
    if (compute_core_ && windowScatterModeActive_() && compute_core_->hasWork()) return true;
    return false;
}

double SnnWorkload::getUtilization() const {
    if (compute_core_) return compute_core_->getUtilization();
    return 0.0;
}

void SnnWorkload::getStatistics(std::map<std::string, uint64_t>& stats) const {
    const uint64_t spikes_received = rt_.sinks.spikes_received ? *rt_.sinks.spikes_received : 0;
    const uint64_t spikes_generated = rt_.sinks.spikes_generated ? *rt_.sinks.spikes_generated : 0;
    const uint64_t neurons_fired = rt_.sinks.neurons_fired ? *rt_.sinks.neurons_fired : 0;
    const uint64_t syn_accesses = rt_.sinks.synaptic_accesses ? *rt_.sinks.synaptic_accesses : 0;
    uint64_t snn_tx_spike_packets_total = 0;
    uint64_t snn_tx_spikekey_packets_total = 0;
    uint64_t snn_tx_spiketilekey_packets_total = 0;
    uint64_t snn_tx_spikekey_v4_packets_total = 0;
    uint64_t snn_tx_spiketilekey_v4_packets_total = 0;
    uint64_t snn_tx_bundle_v1_packets_total = 0;
    uint64_t snn_tx_bundle_v2_packets_total = 0;
    uint64_t snn_tx_bundle_v3_packets_total = 0;
    uint64_t snn_tx_cohort_packets_total = 0;
    uint64_t snn_tx_cohort_pres_total = 0;
    uint64_t snn_tx_cohort_bandcolor_switch_total = 0;
    if (spike_comm_) {
        snn_tx_spike_packets_total = spike_comm_->txSpikePacketsTotal();
        snn_tx_spikekey_packets_total = spike_comm_->txSpikeKeyPacketsTotal();
        snn_tx_spiketilekey_packets_total = spike_comm_->txSpikeTileKeyPacketsTotal();
        snn_tx_spikekey_v4_packets_total = spike_comm_->txSpikeKeyV4PacketsTotal();
        snn_tx_spiketilekey_v4_packets_total = spike_comm_->txSpikeTileKeyV4PacketsTotal();
        snn_tx_bundle_v1_packets_total = spike_comm_->txBundleV1PacketsTotal();
        snn_tx_bundle_v2_packets_total = spike_comm_->txBundleV2PacketsTotal();
        snn_tx_bundle_v3_packets_total = spike_comm_->txBundleV3PacketsTotal();
        snn_tx_cohort_packets_total = spike_comm_->txCohortPacketsTotal();
        snn_tx_cohort_pres_total = spike_comm_->txCohortPresTotal();
        snn_tx_cohort_bandcolor_switch_total = spike_comm_->txCohortBandcolorSwitchTotal();
    }
    stats["spikes_received"] = spikes_received;
    stats["spikes_generated"] = spikes_generated;
    stats["neurons_fired"] = neurons_fired;
    stats["synaptic_accesses"] = syn_accesses;
    stats["gas_scatter_spikes_emitted_total"] = total_scatter_spikes_emitted_;
    stats["snn_tx_spike_packets_total"] = snn_tx_spike_packets_total;
    stats["snn_tx_spikekey_packets_total"] = snn_tx_spikekey_packets_total;
    stats["snn_tx_spiketilekey_packets_total"] = snn_tx_spiketilekey_packets_total;
    stats["snn_tx_spikekey_v4_packets_total"] = snn_tx_spikekey_v4_packets_total;
    stats["snn_tx_spiketilekey_v4_packets_total"] = snn_tx_spiketilekey_v4_packets_total;
    stats["snn_tx_bundle_v1_packets_total"] = snn_tx_bundle_v1_packets_total;
    stats["snn_tx_bundle_v2_packets_total"] = snn_tx_bundle_v2_packets_total;
    stats["snn_tx_bundle_v3_packets_total"] = snn_tx_bundle_v3_packets_total;
    stats["snn_tx_cohort_packets_total"] = snn_tx_cohort_packets_total;
    stats["snn_tx_cohort_pres_total"] = snn_tx_cohort_pres_total;
    stats["snn_tx_cohort_bandcolor_switch_total"] = snn_tx_cohort_bandcolor_switch_total;
    stats["storm_cohort_packets_total"] = snn_tx_cohort_packets_total;
    stats["storm_cohort_pres_total"] = snn_tx_cohort_pres_total;
    stats["storm_cohort_bandcolor_switch_total"] = snn_tx_cohort_bandcolor_switch_total;
    stats["snn_rx_spike_packets_total"] = snn_rx_spike_packets_total_;
    stats["snn_rx_spikekey_total"] = snn_rx_spikekey_total_;
    stats["snn_rx_spiketilekey_total"] = snn_rx_spiketilekey_total_;
    stats["snn_rx_spikekey_v4_total"] = snn_rx_spikekey_v4_total_;
    stats["snn_rx_spiketilekey_v4_total"] = snn_rx_spiketilekey_v4_total_;
    stats["snn_rx_fastpath_packets_total"] = snn_rx_fastpath_packets_total_;
    stats["snn_rx_fallback_packets_total"] = snn_rx_fallback_packets_total_;
    stats["snn_rx_decode_fail_total"] = snn_rx_decode_fail_total_;
    stats["snn_rx_fastpath_posts_total"] = snn_rx_fastpath_posts_total_;
    stats["snn_rx_fastpath_accept_total"] = snn_rx_fastpath_accept_total_;
    stats["snn_rx_fastpath_reject_total"] = snn_rx_fastpath_reject_total_;
    stats["snn_rx_fastpath_edges_recorded_total"] = snn_rx_fastpath_edges_recorded_total_;
    stats["snn_edge_record_attempt_total"] = snn_edge_record_attempt_total_;
    stats["snn_edge_record_commit_total"] = snn_edge_record_commit_total_;
    stats["snn_edge_record_skip_gate_total"] = snn_edge_record_skip_gate_total_;
    stats["snn_edge_record_skip_stage_total"] = snn_edge_record_skip_stage_total_;
    stats["snn_edge_record_skip_capacity_total"] = snn_edge_record_skip_capacity_total_;
    stats["snn_edge_record_skip_reject_total"] = snn_edge_record_skip_reject_total_;
    stats["snn_edge_record_fastpath_handler_entry_total"] =
        snn_edge_record_fastpath_handler_entry_total_;
    stats["snn_edge_record_fastpath_wms_missing_total"] =
        snn_edge_record_fastpath_wms_missing_total_;
    stats["snn_edge_record_fastpath_backend_not_ready_total"] =
        snn_edge_record_fastpath_backend_not_ready_total_;
    stats["snn_edge_record_fastpath_stage_block_total"] =
        snn_edge_record_fastpath_stage_block_total_;
    stats["snn_edge_record_process_local_handler_entry_total"] =
        snn_edge_record_process_local_handler_entry_total_;
    stats["snn_edge_record_process_local_wms_missing_total"] =
        snn_edge_record_process_local_wms_missing_total_;
    stats["snn_edge_record_process_local_backend_not_ready_total"] =
        snn_edge_record_process_local_backend_not_ready_total_;
    stats["snn_edge_record_process_local_stage_block_total"] =
        snn_edge_record_process_local_stage_block_total_;
    stats["snn_edge_record_deliver_window_handler_entry_total"] =
        snn_edge_record_deliver_window_handler_entry_total_;
    stats["snn_edge_record_deliver_window_wms_missing_total"] =
        snn_edge_record_deliver_window_wms_missing_total_;
    stats["snn_edge_record_deliver_window_backend_not_ready_total"] =
        snn_edge_record_deliver_window_backend_not_ready_total_;
    stats["snn_edge_record_deliver_window_stage_block_total"] =
        snn_edge_record_deliver_window_stage_block_total_;
    stats["route3d_native_activation_total"] =
        rt_.sinks.route3d_native_activation_total ? *rt_.sinks.route3d_native_activation_total : 0;
    stats["route3d_native_gating_activation_total"] =
        rt_.sinks.route3d_native_gating_activation_total ? *rt_.sinks.route3d_native_gating_activation_total : 0;
    stats["route3d_native_direct_activation_total"] =
        rt_.sinks.route3d_native_direct_activation_total ? *rt_.sinks.route3d_native_direct_activation_total : 0;
    stats["route3d_native_unique_sources_total"] =
        rt_.sinks.route3d_native_unique_sources_total ? *rt_.sinks.route3d_native_unique_sources_total : 0;
    stats["route_native_source_fanout_active"] = route_semantics_.native_source_fanout_active ? 1 : 0;
    stats["route_native_target_synthesis_active"] = route_semantics_.native_target_synthesis_active ? 1 : 0;
    stats["route_bootstrap_dependency_active"] = route_semantics_.bootstrap_dependency_active ? 1 : 0;
    stats["route_real_synapse_inputs_available"] = route_semantics_.real_synapse_inputs_available ? 1 : 0;
    stats["route_native_synapse_source_candidate"] = route_semantics_.native_synapse_source_candidate ? 1 : 0;
    stats["route_source_semantics_authority_legacy_provider"] =
        route_semantics_.source_semantics_authority == "legacy_provider" ? 1 : 0;
    stats["route_source_semantics_authority_legacy_built_routes_3d"] =
        route_semantics_.source_semantics_authority == "legacy_built_routes_3d" ? 1 : 0;
    stats["route_source_semantics_authority_native_3d_route_table"] =
        route_semantics_.source_semantics_authority == "native_3d_route_table" ? 1 : 0;
    stats["route_source_primary_kind_legacy_only"] =
        route_semantics_.source_primary_kind == "legacy_only" ? 1 : 0;
    stats["route_source_primary_kind_edges_csv_bootstrap"] =
        route_semantics_.source_primary_kind == "edges_csv_bootstrap" ? 1 : 0;
    stats["route_source_primary_kind_legacy_route_tables_bootstrap"] =
        route_semantics_.source_primary_kind == "legacy_route_tables_bootstrap" ? 1 : 0;
    stats["route_source_primary_kind_legacy_route_tables_with_real_synapse_inputs"] =
        route_semantics_.source_primary_kind == "legacy_route_tables_with_real_synapse_inputs" ? 1 : 0;
    stats["route_source_primary_kind_native_3d_route_table_with_real_synapse_inputs"] =
        route_semantics_.source_primary_kind == "native_3d_route_table_with_real_synapse_inputs" ? 1 : 0;
    stats["route_source_primary_kind_real_synapse_inputs_only"] =
        route_semantics_.source_primary_kind == "real_synapse_inputs_only" ? 1 : 0;
    stats["route_native_bootstrap_source_edges_csv"] =
        route_semantics_.native_bootstrap_source == "edges_csv" ? 1 : 0;
    stats["route_native_bootstrap_source_legacy_route_tables"] =
        route_semantics_.native_bootstrap_source == "legacy_route_tables" ? 1 : 0;
    stats["route_topology_mesh_2d"] = route_semantics_.route_topology == "mesh_2d" ? 1 : 0;
    stats["route_topology_mesh_3d"] = route_semantics_.route_topology == "mesh_3d" ? 1 : 0;
    stats["route_target_semantics_authority_legacy_multicast_fallback"] =
        route_semantics_.target_semantics_authority == "legacy_multicast_fallback" ? 1 : 0;
    stats["route_target_semantics_authority_compat_3d_target_synthesis"] =
        route_semantics_.target_semantics_authority == "compat_3d_target_synthesis" ? 1 : 0;
    stats["route_target_semantics_authority_native_3d_target_synthesis"] =
        route_semantics_.target_semantics_authority == "native_3d_target_synthesis" ? 1 : 0;
    std::map<std::string, uint64_t> semantic_stats;
    if (semantic_region_workload_) {
        semantic_region_workload_->getStatistics(semantic_stats);
    }
    if (compute_core_) {
        std::map<std::string, uint64_t> core_stats;
        compute_core_->getStatistics(core_stats);
        auto copy_if = [&stats, &core_stats](const char* key) {
            if (!key) return;
            auto it = core_stats.find(key);
            if (it == core_stats.end()) return;
            stats[key] = it->second;
        };
        copy_if("core_state_sram_reads_total");
        copy_if("core_state_sram_writes_total");
        copy_if("core_state_sram_bytes_read_total");
        copy_if("core_state_sram_bytes_write_total");
        copy_if("core_state_sram_bank_conflict_ticks_total");
        copy_if("core_state_sram_predicted_extra_cycles_total");
        copy_if("core_state_sram_resident_bytes_peak");
        copy_if("core_state_sram_bank_peak_accesses_per_tick");
        copy_if("core_state_sram_energy_read_pj_total");
        copy_if("core_state_sram_energy_write_pj_total");
        copy_if("core_state_sram_stall_cycles_total");
        copy_if("gas_unique_reads_total");
        copy_if("gas_unique_bytes_total");
        copy_if("gas_frontend_staged_reads_total");
        copy_if("gas_frontend_granules_built_total");
        copy_if("gas_apply_acc_updates_total");
        copy_if("gas_acc_posts_touched_total");
        copy_if("metadata_lookup_reads_issued_total");
        copy_if("synapse_gather_reads_issued_total");
        copy_if("stream_region_writes_issued_total");
        copy_if("stream_region_reads_issued_total");
        copy_if("stream_region_bytes_written_total");
        copy_if("stream_region_bytes_read_total");
        copy_if("writeback_region_writes_issued_total");
        copy_if("writeback_region_reads_issued_total");
        copy_if("writeback_region_bytes_written_total");
        copy_if("writeback_region_bytes_read_total");
        copy_if("traffic_semantic_metadata_lookup_demands_total");
        copy_if("traffic_semantic_synapse_gather_demands_total");
        copy_if("traffic_semantic_stream_region_demands_total");
        copy_if("traffic_semantic_writeback_region_demands_total");
        copy_if("traffic_semantic_tier_local_home_gather_demands_total");
        copy_if("traffic_semantic_same_xy_cross_tier_gather_demands_total");
        copy_if("traffic_semantic_remote_home_gather_demands_total");
        copy_if("traffic_semantic_tier_local_home_stream_region_demands_total");
        copy_if("traffic_semantic_same_xy_cross_tier_stream_region_demands_total");
        copy_if("traffic_semantic_remote_home_stream_region_demands_total");
        copy_if("weight_read_dense_reqs_total");
        copy_if("weight_read_rowptr_reqs_total");
        copy_if("weight_read_colidx_reqs_total");
        copy_if("weight_read_blockdata_reqs_total");
        copy_if("weight_read_gcss_reqs_total");
        copy_if("weight_read_dense_bytes_total");
        copy_if("weight_read_rowptr_bytes_total");
        copy_if("weight_read_colidx_bytes_total");
        copy_if("weight_read_blockdata_bytes_total");
        copy_if("weight_read_gcss_bytes_total");

        if (weight_mem_subsystem_) {
            const auto read_source = weight_mem_subsystem_->readSourceStats();
            setStatIfMissingOrZero_(stats, "weight_read_dense_reqs_total", read_source.dense_reqs_total);
            setStatIfMissingOrZero_(stats, "weight_read_rowptr_reqs_total", read_source.rowptr_reqs_total);
            setStatIfMissingOrZero_(stats, "weight_read_colidx_reqs_total", read_source.colidx_reqs_total);
            setStatIfMissingOrZero_(stats, "weight_read_blockdata_reqs_total", read_source.blockdata_reqs_total);
            setStatIfMissingOrZero_(stats, "weight_read_gcss_reqs_total", read_source.gcss_reqs_total);
            setStatIfMissingOrZero_(stats, "weight_read_dense_bytes_total", read_source.dense_bytes_total);
            setStatIfMissingOrZero_(stats, "weight_read_rowptr_bytes_total", read_source.rowptr_bytes_total);
            setStatIfMissingOrZero_(stats, "weight_read_colidx_bytes_total", read_source.colidx_bytes_total);
            setStatIfMissingOrZero_(stats, "weight_read_blockdata_bytes_total", read_source.blockdata_bytes_total);
            setStatIfMissingOrZero_(stats, "weight_read_gcss_bytes_total", read_source.gcss_bytes_total);
        }

        const uint64_t metadata_requests =
            getMapValueOrZero_(stats, "weight_read_rowptr_reqs_total") +
            getMapValueOrZero_(stats, "weight_read_colidx_reqs_total");
        const uint64_t gather_requests =
            getMapValueOrZero_(stats, "weight_read_dense_reqs_total") +
            getMapValueOrZero_(stats, "weight_read_blockdata_reqs_total") +
            getMapValueOrZero_(stats, "weight_read_gcss_reqs_total");
        const uint64_t stream_demands = total_gas_apply_acc_updates_;
        const uint64_t stream_issued = getMapValueOrZero_(semantic_stats, "stream_region_writes_issued_total");
        const uint64_t stream_reads_issued = getMapValueOrZero_(semantic_stats, "stream_region_reads_issued_total");
        const uint64_t stream_bytes_written = getMapValueOrZero_(semantic_stats, "stream_region_bytes_written_total");
        const uint64_t stream_bytes_read = getMapValueOrZero_(semantic_stats, "stream_region_bytes_read_total");
        const uint64_t writeback_demands = total_scatter_spikes_emitted_;
        const uint64_t writeback_issued = getMapValueOrZero_(semantic_stats, "writeback_region_writes_issued_total");
        const uint64_t writeback_reads_issued =
            getMapValueOrZero_(semantic_stats, "writeback_region_reads_issued_total");
        const uint64_t writeback_bytes_written =
            getMapValueOrZero_(semantic_stats, "writeback_region_bytes_written_total");
        const uint64_t writeback_bytes_read =
            getMapValueOrZero_(semantic_stats, "writeback_region_bytes_read_total");

        setStatIfMissingOrZero_(stats, "metadata_lookup_reads_issued_total", metadata_requests);
        setStatIfMissingOrZero_(stats, "synapse_gather_reads_issued_total", gather_requests);
        setStatIfMissingOrZero_(stats, "stream_region_writes_issued_total", stream_issued);
        setStatIfMissingOrZero_(stats, "stream_region_reads_issued_total", stream_reads_issued);
        setStatIfMissingOrZero_(stats, "stream_region_bytes_written_total", stream_bytes_written);
        setStatIfMissingOrZero_(stats, "stream_region_bytes_read_total", stream_bytes_read);
        setStatIfMissingOrZero_(stats, "writeback_region_writes_issued_total", writeback_issued);
        setStatIfMissingOrZero_(stats, "writeback_region_reads_issued_total", writeback_reads_issued);
        setStatIfMissingOrZero_(stats, "writeback_region_bytes_written_total", writeback_bytes_written);
        setStatIfMissingOrZero_(stats, "writeback_region_bytes_read_total", writeback_bytes_read);
        setStatIfMissingOrZero_(stats, "traffic_semantic_metadata_lookup_demands_total", metadata_requests);
        setStatIfMissingOrZero_(stats, "traffic_semantic_synapse_gather_demands_total", gather_requests);
        setStatIfMissingOrZero_(stats, "traffic_semantic_stream_region_demands_total", stream_demands);
        setStatIfMissingOrZero_(stats, "traffic_semantic_writeback_region_demands_total", writeback_demands);

        const int home_stack_id = params_ ? params_->find<int>("home_stack_id", -1) : -1;
        const std::string mesh_shape = params_ ? params_->find<std::string>("mesh_shape", "") : "";
        const std::string home_access_class = classifyHomeAccessForNode_(
            static_cast<uint32_t>(rt_.node_id),
            mesh_shape,
            home_stack_id);
        if (!home_access_class.empty()) {
            const std::string gather_key =
                "traffic_semantic_" + home_access_class + "_gather_demands_total";
            const std::string stream_key =
                "traffic_semantic_" + home_access_class + "_stream_region_demands_total";
            setStatIfMissingOrZero_(stats, gather_key.c_str(), gather_requests);
            setStatIfMissingOrZero_(stats, stream_key.c_str(), stream_demands);
        }
    }
}

void SnnWorkload::onInitPhase(unsigned phase) {
    // Ensure compute core is configured before init() phases are forwarded.
    ensureComputeCoreConfigured_();
    if (compute_core_) {
        compute_core_->onInit(phase);
    }
    if (phase == 0) {
        // Ensure route/comm is ready before first firing window.
        ensureSpikeCommConfigured_();
    }
}

void SnnWorkload::onSetup() {
    ensureComputeCoreConfigured_();
    if (compute_core_) compute_core_->onSetup();
}

void SnnWorkload::resetMembraneState(float v_rest) {
    ensureComputeCoreConfigured_();
    if (compute_core_) compute_core_->resetMembraneState(v_rest);
}

void SnnWorkload::onFinish() {
    // Debug-only: if the window didn't reach EndScatter (e.g., global step barrier stops early),
    // dump the in-flight window's weight-read summary for root-cause analysis.
    if (window_read_debug_ && weight_mem_subsystem_) {
        weight_mem_subsystem_->finishWindowDiag();
    }
    if (weight_mem_subsystem_) {
        weight_mem_subsystem_->finishSemanticVerify();
    }
    if (compute_core_) compute_core_->onFinish();
}

void SnnWorkload::applyGatingDecision(uint32_t src_global,
                                      const std::vector<uint32_t>& dest_pes,
                                      uint64_t current_cycle,
                                      uint64_t ttl_cycles) {
    ensureSpikeCommConfigured_();
    if (!synapse_route_) return;
    synapse_route_->applyGatingDecision(src_global, dest_pes, current_cycle, ttl_cycles);
}

void SnnWorkload::emitNeuronFire(uint32_t neuron_idx, uint64_t now_cycle) {
    if (step_seed_only_mode_) return;
    ensureSpikeCommConfigured_();
    if (!spike_comm_) return;
    spike_comm_->emitNeuronFire(neuron_idx, now_cycle);
}

uint64_t SnnWorkload::emitNeuronFireBatch(const std::vector<uint32_t>& neuron_indices, uint64_t now_cycle) {
    if (step_seed_only_mode_) return 0;
    ensureSpikeCommConfigured_();
    if (!spike_comm_) return 0;
    return spike_comm_->emitNeuronFireBatch(neuron_indices, now_cycle);
}

bool SnnWorkload::ready() const {
    return spike_comm_ && spike_comm_configured_ && spike_comm_->ready();
}

void SnnWorkload::onGasStageEvent(const GasStageEvent& ev) {
    // Phase4-Task6.4: 仅在窗口端到端语义下接管（apply_acc_enable + gas_window_mode）。
    if (!(apply_acc_enable_ && gas_window_mode_)) return;

    ensureComputeCoreConfigured_();
    ensureSpikeCommConfigured_();
    ensureWeightReaderOwned_();

    switch (ev.op) {
        case GasOp::BeginGather:
            if (end_scatter_event_pending_ && !scatter_commit_pending_) {
                completeEndScatter_(end_scatter_event_seq_);
            }
            if (scatter_commit_pending_) {
                begin_gather_event_pending_ = true;
                begin_gather_event_seq_ = ev.superstep;
                if (rt_.log) {
                    rt_.log->verbose(CALL_INFO, 1, 0,
                                     "[snn-dma] defer BeginGather until scatter commit drains "
                                     "(core=%u seq=%u pending_scatter_seq=%u)\n",
                                     rt_.core_id,
                                     ev.superstep,
                                     scatter_commit_seq_);
                }
                break;
            }
            enterBeginGather_(ev.superstep);
            break;
        case GasOp::BeginApply:
            if (compute_core_) compute_core_->onStageBeginApply(ev.superstep);
            if (weight_mem_subsystem_) {
                weight_mem_subsystem_->beginApplyWindow(ev.superstep, window_read_debug_, rt_.log, (int)rt_.core_id);
                weight_mem_subsystem_->issueFallbackReadsIfNeeded(/*strict_gas_active=*/true);
                weight_mem_subsystem_->issueFromEdges();
            }
            gas_stage_ = GasStage::Apply;
            break;
        case GasOp::EndApply:
            gas_stage_ = GasStage::Apply;
            if (compute_core_) compute_core_->onStageEndApply(ev.superstep);
            break;
        case GasOp::BeginScatter: {
            gas_stage_ = GasStage::Scatter;
            if (compute_core_) {
                compute_core_->clearFiredWindow();
                compute_core_->onStageBeginScatter(ev.superstep);
            }

            last_scatter_spikes_emitted_ = 0;
            if (shouldDeferScatterCommit_()) {
                scatter_commit_pending_ = true;
                scatter_commit_seq_ = ev.superstep;
                break;
            }
            scatter_commit_pending_ = false;
            scatter_commit_seq_ = 0;
            scatter_defer_diag_next_cycle_ = now_cycle_cached_;
            finalizeScatterCommit_(ev.superstep);
            break;
        }
        case GasOp::EndScatter:
            if (scatter_commit_pending_) {
                end_scatter_event_pending_ = true;
                end_scatter_event_seq_ = ev.superstep;
                if (rt_.log) {
                    rt_.log->verbose(CALL_INFO, 1, 0,
                                     "[snn-dma] defer EndScatter until scatter commit drains "
                                     "(core=%u seq=%u pending_seq=%u)\n",
                                     rt_.core_id,
                                     ev.superstep,
                                     scatter_commit_seq_);
                }
                break;
            }
            completeEndScatter_(ev.superstep);
            break;
        default:
            break;
    }
}

void SnnWorkload::onGasStatEvent(const GasStatEvent& st) {
    total_gas_frontend_granules_built_ += st.frontend_granules_built;
}

}} // namespace SST::SnnDL
