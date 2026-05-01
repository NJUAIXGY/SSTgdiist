// -*- c++ -*-
//
// Copyright 2025 SST Contributors
//
// MultiCorePE.cc: 真正的多核脉冲神经网络处理单元实现文件
//

#include <sst/core/sst_config.h>
#include "MultiCorePE.h"
#include "noc/SnnNetworkAdapter.h"
#include "noc/OptimizedInternalRing.h"
#include "SnnNIC.h"
#include "GatingDecisionEvent.h"
#include "ICoreControlHooks.h"
#include "ICoreMemoryLink.h"
#include "IGlobalStepHooks.h"
#include "IGlobalStepCreditHooks.h"
#include "ILoaderReadyHooks.h"
#include "NocPacketEvent.h"
#include "NocPacketBatchEvent.h"
#include "GasStepBarrierEvent.h"
#include "LoaderDoneEvent.h"
#include "WorkloadConfig.h"
#include "SnnDLLogging.h"
#include "SnnCoreAPI.h"
#include "multicore/MultiCorePEConfig.h"
#include "multicore/GlobalStepDrainDecision.h"
#include "services/memory/PeDmaScheduler.h"
#include "services/local_storage/LocalStorageHierarchyController.h"
#include "services/local_storage/PeLocalServiceObjectTable.h"
#include "services/local_storage/PodMetadataObjectPlane.h"
#include "services/local_storage/PodOwnerServiceTable.h"
#include "services/local_storage/PeWeightObjectPlane.h"
#include "services/pe_fabric/PeSharedCoreFabric.h"
#include "synapse/route/SpikeNocCodec.h"
#include "synapse/route/SpikeTileNocCodec.h"
#include "workload_stats/WorkloadStatsRegistry.h"

#include <fstream>
#include <sstream>
#include <iostream>
#include <cmath>
#include <algorithm>
#include <functional>
#include <iomanip>
#include <cstdlib>
#include <cctype>
#include <random>
#include <cstdlib>
#include <climits>
#include <cinttypes>
#include <cerrno>
#include <cstring>
#include <sys/stat.h>
#include <sys/types.h>

using namespace SST;
using namespace SST::SnnDL;

#ifndef PE_LOG
#define PE_LOG(lvl, ...) SNNDL_LOGPTR(output_, (lvl), __VA_ARGS__)
#endif

// ===== MultiCorePE 主组件实现 =====

// P2: 环境变量前端化 – 不再使用TU级别的 getenv 缓存；改用构造期解析的成员 sentinel_enabled_

namespace {
inline uint8_t stepStageCodeFromName_(const std::string& ev) {
    if (ev == "BeginGather") return 1;
    if (ev == "BeginApply") return 2;
    if (ev == "EndApply") return 3;
    if (ev == "BeginScatter") return 4;
    if (ev == "EndScatter") return 5;
    return 0;
}
	inline const char* stepStageCodeName_(uint8_t code) {
	    switch (code) {
        case 1: return "BeginGather";
        case 2: return "BeginApply";
        case 3: return "EndApply";
        case 4: return "BeginScatter";
        case 5: return "EndScatter";
        default: return "None";
	    }
	}

	inline std::string defaultPeOutDir_(int node_id) {
	    char buf[32];
	    std::snprintf(buf, sizeof(buf), "pe%02d", node_id);
	    return std::string(buf);
	}

	inline bool ensureDirExists_(const std::string& dir) {
	    if (dir.empty() || dir == ".") return true;
	    struct stat st;
	    if (::stat(dir.c_str(), &st) == 0) {
	        return S_ISDIR(st.st_mode);
	    }
	    if (::mkdir(dir.c_str(), 0775) == 0) return true;
	    return (errno == EEXIST);
	}

inline uint64_t ceilDivU64_(uint64_t num, uint64_t den) {
    if (den == 0) return 0;
    return (num + den - 1ull) / den;
}

inline size_t normalizePodCount_(size_t num_cores,
                                 uint32_t configured_pod_count,
                                 uint32_t configured_pod_size) {
    const size_t cores = std::max<size_t>(num_cores, 1u);
    size_t pods = 0;
    if (configured_pod_count > 0) {
        pods = static_cast<size_t>(configured_pod_count);
    } else if (configured_pod_size > 0) {
        pods = static_cast<size_t>(ceilDivU64_(cores, configured_pod_size));
    } else {
        pods = cores;
    }
    if (pods == 0) pods = 1;
    if (pods > cores) pods = cores;
    return pods;
}

static constexpr uint32_t kPodMetadataShadowEntryBytes = 32u;

inline NocPacketEvent* buildSyntheticSpikeKeyPacket_(uint32_t src_node,
                                                     uint16_t src_endpoint,
                                                     uint32_t dst_node,
                                                     uint16_t dst_endpoint,
                                                     uint32_t pre_global,
                                                     uint64_t now_cycle) {
    auto* pkt = new NocPacketEvent();
    pkt->src_node = src_node;
    pkt->dst_node = dst_node;
    pkt->src_endpoint = src_endpoint;
    pkt->dst_endpoint = dst_endpoint;
    pkt->kind = static_cast<uint16_t>(NocPacketKind::SpikeKey);
    pkt->timestamp = now_cycle;

    SpikeNocCodec::WireSpikeKeyV2 ws{};
    ws.version = 2;
    ws.route_mode = 1; // blocked route
    ws.stage = 0;      // INTER
    ws.block_w_h = static_cast<uint16_t>((1u << 8) | 1u);
    ws.block_id = dst_node;
    ws.ingress_node = dst_node;
    ws.pre_global = pre_global;
    ws.group_id = (now_cycle << 32) | static_cast<uint64_t>(pre_global);
    ws.core_mask.fill(0u);
    if (dst_endpoint < 32u) {
        ws.core_mask[0] = static_cast<uint32_t>(1u << dst_endpoint);
    }
    SpikeNocCodec::encodeSpikeKey(ws, pkt->payload);
    return pkt;
}

inline PeSharedCoreFabric::PacketKind pulsePacketKindFromNoc_(NocPacketKind kind) {
    switch (kind) {
        case NocPacketKind::Spike:
            return PeSharedCoreFabric::PacketKind::Spike;
        case NocPacketKind::SpikeKey:
            return PeSharedCoreFabric::PacketKind::SpikeKey;
        case NocPacketKind::SpikeTileKey:
            return PeSharedCoreFabric::PacketKind::SpikeTileKey;
        default:
            return PeSharedCoreFabric::PacketKind::Other;
    }
}

struct PulseDescriptorSurrogate_ {
    bool valid = false;
    uint32_t post_block_id = 0;
    uint32_t weight_region_id = 0;
    uint32_t retire_domain_id = 0;
    bool region_safe = true;
};

inline uint32_t pulseDescriptorTaggedRegion_(uint32_t tag, uint32_t value) {
    return (tag << 28) ^ value;
}

inline std::string normalizePulseMetadataMaskToken_(std::string token) {
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

inline uint32_t parsePulseMetadataObjectMask_(const std::string& raw_mask) {
    if (raw_mask.empty()) return 0u;

    uint32_t mask = 0u;
    size_t start = 0u;
    while (start <= raw_mask.size()) {
        const size_t end = raw_mask.find_first_of(",|+; ", start);
        const std::string token = normalizePulseMetadataMaskToken_(
            raw_mask.substr(start, (end == std::string::npos) ? std::string::npos : (end - start)));
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

inline PulseDescriptorSurrogate_ buildPulseDescriptorSurrogate_(const NocPacketEvent& pkt,
                                                                const GlobalNeuronLayout& layout) {
    PulseDescriptorSurrogate_ surrogate{};

    if (pkt.packetKind() == NocPacketKind::Spike) {
        if (pkt.payload.size() < sizeof(SpikeNocCodec::WireSpike)) return surrogate;
        SpikeNocCodec::WireSpike wire{};
        std::memcpy(&wire, pkt.payload.data(), sizeof(wire));
        surrogate.valid = true;
        surrogate.post_block_id = layout.valid() ? layout.nodeOf(wire.dst_neuron) : pkt.dst_node;
        surrogate.weight_region_id = pulseDescriptorTaggedRegion_(1u, wire.src_neuron);
        surrogate.retire_domain_id = surrogate.post_block_id;
        return surrogate;
    }

    if (pkt.packetKind() == NocPacketKind::SpikeKey) {
        SpikeNocCodec::WireSpikeKeyV2 wire{};
        if (!SpikeNocCodec::decodeSpikeKeyAny(pkt.payload, wire, nullptr)) return surrogate;
        surrogate.valid = true;
        surrogate.post_block_id = wire.block_id;
        surrogate.weight_region_id = pulseDescriptorTaggedRegion_(2u, wire.pre_global);
        surrogate.retire_domain_id = surrogate.post_block_id;
        return surrogate;
    }

    if (pkt.packetKind() == NocPacketKind::SpikeTileKey) {
        SpikeTileNocCodec::WireSpikeTileKeyV1 wire{};
        if (!SpikeTileNocCodec::decode(pkt.payload, wire)) return surrogate;
        surrogate.valid = true;
        surrogate.post_block_id = wire.route.block_id;
        surrogate.weight_region_id = pulseDescriptorTaggedRegion_(3u, wire.tile.block_col);
        surrogate.retire_domain_id = surrogate.post_block_id;
        return surrogate;
    }

    return surrogate;
}
} // namespace

MultiCorePE::MultiCorePE(ComponentId_t id, Params& params) : Component(id) {
    const MultiCorePEConfig cfg = parseMultiCorePEConfig(params);

    // 初始化输出对象
    output_ = new Output("MultiCorePE[@p:@l]: ", cfg.verbose_level, 0, Output::STDOUT);

    // 读取基础配置参数（已集中解析）
    num_cores_ = cfg.num_cores;
    neurons_per_core_ = cfg.neurons_per_core;
    total_neurons_ = num_cores_ * neurons_per_core_;
    neurons_per_pe_cfg_ = cfg.neurons_per_pe;
    node_id_ = cfg.node_id;
    total_nodes_ = cfg.total_nodes;
    global_neuron_base_ = cfg.global_neuron_base;
    base_addr_ = cfg.base_addr;
    sim_stop_ns_ = cfg.sim_stop_ns;
    // NoC e2e latency histogram range (cycles) for native multicast lab.
    noc_lat_hist_max_ = cfg.noc_lat_hist_max;
    noc_lat_spike_hist_.assign(static_cast<size_t>(noc_lat_hist_max_) + 2u, 0);
    noc_lat_spikekey_hist_.assign(static_cast<size_t>(noc_lat_hist_max_) + 2u, 0);
    verbose_ = cfg.verbose_level;
    clock_freq_ = cfg.clock_freq;
    // P2: 解析 sentinel 与步级诊断参数（未设置则回退环境变量）
    {
        sentinel_enabled_ = cfg.sentinel_enabled;
        progress_log_interval_ns_ = cfg.progress_log_interval_ns;
        progress_log_node_ = cfg.progress_log_node;
        step_diag_cap_cfg_ = cfg.step_diag_cap;
        step_diag_enable_cfg_ = cfg.step_diag_enable;
    }
    weights_file_ = cfg.weights_file;
    enable_numa_ = cfg.enable_numa;

    // ===== 全局ID布局口径（fail-fast）=====
    // 统一口径：neurons_per_pe 必须等于 num_cores*neurons_per_core（禁止用其它 stride/bytes 误填）
    const uint64_t derived_neurons_per_pe =
        static_cast<uint64_t>(num_cores_) * static_cast<uint64_t>(neurons_per_core_);
    if (neurons_per_pe_cfg_ == 0) {
        neurons_per_pe_cfg_ = static_cast<uint32_t>(derived_neurons_per_pe);
    } else if (static_cast<uint64_t>(neurons_per_pe_cfg_) != derived_neurons_per_pe) {
        output_->fatal(
            CALL_INFO, -1,
            "MultiCorePE fatal: neurons_per_pe 参数口径错误：cfg=%u 但期望 num_cores*neurons_per_core=%" PRIu64 "（请检查脚本/配置是否误把 per_core_stride/base_addr 等字节量传入）\n",
            neurons_per_pe_cfg_, derived_neurons_per_pe);
    }
    if (total_nodes_ <= 0) {
        output_->fatal(CALL_INFO, -1, "MultiCorePE fatal: total_nodes 必须 > 0，当前=%d\n", total_nodes_);
    }
    if (node_id_ < 0 || node_id_ >= total_nodes_) {
        output_->fatal(CALL_INFO, -1, "MultiCorePE fatal: node_id=%d 超出 [0,%d)\n", node_id_, total_nodes_);
    }
    global_layout_ = GlobalNeuronLayout(static_cast<uint32_t>(total_nodes_),
                                        static_cast<uint32_t>(num_cores_),
                                        static_cast<uint32_t>(neurons_per_core_));
    if (!global_layout_.valid()) {
        output_->fatal(CALL_INFO, -1,
            "MultiCorePE fatal: GlobalNeuronLayout 无效：total_nodes=%d num_cores=%d neurons_per_core=%d\n",
            total_nodes_, num_cores_, neurons_per_core_);
    }
    const uint64_t expected_base = global_layout_.globalBaseOfNode(static_cast<uint32_t>(node_id_));
    if (global_neuron_base_ != expected_base) {
        output_->fatal(
            CALL_INFO, -1,
            "MultiCorePE fatal: global_neuron_base(0x%" PRIx64 ") 与 node_id=%d 推导基址(0x%" PRIx64 ") 不一致（期望 global_neuron_base=node_id*neurons_per_pe）\n",
            global_neuron_base_, node_id_, expected_base);
    }
    
    // 神经元参数
    v_thresh_ = cfg.v_thresh;
    v_reset_ = cfg.v_reset;
    v_rest_ = cfg.v_rest;
    tau_mem_ = cfg.tau_mem;
    t_ref_ = cfg.t_ref;
    
    // 测试流量参数
    enable_test_traffic_ = cfg.enable_test_traffic;
    test_traffic_packet_kind_ = cfg.test_traffic_packet_kind;
    test_target_node_ = cfg.test_target_node;
    test_period_ = cfg.test_period;
    test_spikes_per_burst_ = cfg.test_spikes_per_burst;
    test_weight_ = cfg.test_weight;
    test_max_spikes_ = cfg.test_max_spikes;
    
    // 环形网络实现选择
    use_optimized_ring_ = cfg.use_optimized_ring;
    // Phase5：冻结 legacy InternalRing 分支（use_optimized_ring=0）
    // - NoC 子系统已以 OptimizedInternalRing 为唯一片上互连后端完成闭环
    // - legacy InternalRing 会引入维护成本与语义漂移风险，故在此明确禁用
    if (!use_optimized_ring_ && num_cores_ > 1) {
        output_->fatal(CALL_INFO, -1,
            "❌ 配置错误：use_optimized_ring=0 (legacy InternalRing) 已冻结/不再支持，请设置 use_optimized_ring=1\n");
    }
    // 输出控制：是否打印节点汇总
    print_node_summary_ = cfg.print_node_summary;
    primary_keepalive_ = cfg.primary_keepalive;
    manual_core_drive_enable_ = cfg.manual_core_drive_enable;
    manual_gas_gather_cycles_ = cfg.manual_gas_gather_cycles;
    
    // 权重验证参数
    verify_weights_ = cfg.verify_weights;
    weight_verify_samples_ = cfg.weight_verify_samples;
    expected_weight_value_ = cfg.expected_weight_value;
    verify_log_each_sample_ = cfg.verify_log_each_sample;
    
    // 权重回退参数
    use_event_weight_fallback_ = cfg.use_event_weight_fallback;
    enable_memory_weights_ = cfg.enable_memory_weights;
    write_weights_on_init_ = cfg.write_weights_on_init;
    step_seed_only_mode_ = params.find<int>("step_seed_only_mode", 0) != 0;

    // 时间窗口化统计参数（默认关闭）
    window_stats_enable_ = cfg.window_stats_enable;
    window_us_ = cfg.window_us;
    window_csv_ = cfg.window_csv;
    window_metrics_csv_ = cfg.window_metrics_csv;
    window_ns_ = window_us_ * 1000ULL; // 1us = 1000ns（组件时钟1GHz，tick≈1ns）
    diag_fire_log_ = cfg.diag_fire_log;
    exec_mode_ = cfg.exec_mode;
    std::vector<std::string> unknown_modules;
    workload_stats_modules_ =
        WorkloadStatsRegistry::buildModules(cfg.workload_impl, cfg.workload_stats_modules, &unknown_modules);
    if (!unknown_modules.empty() && output_) {
        std::ostringstream oss;
        for (size_t i = 0; i < unknown_modules.size(); ++i) {
            if (i) oss << ",";
            oss << unknown_modules[i];
        }
        output_->verbose(CALL_INFO, 1, 0, "[workload_stats] unknown modules ignored: %s\n", oss.str().c_str());
    }

    pure_snn_datapath_workload_eligible_ =
        workloadAllowsPureSnnDatapathFeatures(cfg.workload_kind);

    dma_enable_ = cfg.dma_enable && pure_snn_datapath_workload_eligible_;
    if (cfg.dma_enable && !dma_enable_ && output_) {
        output_->verbose(CALL_INFO, 1, 0,
                         "[dma] ignore dma_enable for non-SNN workload_impl=%s node=%d\n",
                         cfg.workload_impl.c_str(),
                         node_id_);
    }
    if (dma_enable_) {
        PeDmaScheduler::Config dma_cfg{};
        dma_cfg.num_cores = static_cast<size_t>(std::max(1, num_cores_));
        dma_cfg.bytes_per_cycle = cfg.dma_bytes_per_cycle;
        dma_cfg.read_engines = cfg.dma_read_engines;
        dma_cfg.max_inflight = cfg.dma_max_inflight;
        dma_cfg.queue_depth = cfg.dma_queue_depth;
        dma_cfg.overflow_policy =
            (cfg.dma_overflow_policy == "fail_fast")
                ? PeDmaScheduler::Config::OverflowPolicy::FailFast
                : PeDmaScheduler::Config::OverflowPolicy::Block;
        dma_cfg.burst_bytes = cfg.dma_burst_bytes;
        dma_cfg.setup_cycles = cfg.dma_setup_cycles;
        dma_cfg.channels = cfg.dma_channels;
        dma_cfg.channel_bytes_per_cycle = cfg.dma_channel_bytes_per_cycle;
        dma_cfg.channel_interleave_bytes = cfg.dma_channel_interleave_bytes;
        dma_cfg.stage_budget_permille = cfg.dma_stage_budget_permille;
        dma_scheduler_ = std::make_unique<PeDmaScheduler>(dma_cfg);
    }

    local_storage_enable_ =
        cfg.local_storage_enable && pure_snn_datapath_workload_eligible_;
    if (cfg.local_storage_enable && !local_storage_enable_ && output_) {
        output_->verbose(CALL_INFO, 1, 0,
                         "[local-storage] ignore local_storage_enable for non-SNN workload_impl=%s node=%d\n",
                         cfg.workload_impl.c_str(),
                         node_id_);
    }
    pe_internal_pod_requested_ = cfg.pe_internal_pod_enable;
    pe_internal_pod_metadata_requested_ = cfg.pe_internal_pod_metadata_enable;
    pe_internal_pod_owner_requested_ = cfg.pe_internal_pod_owner_enable;
    pe_internal_cpe_enable_cfg_ = local_storage_enable_ && cfg.pe_internal_cpe_enable;
    pe_internal_pod_enable_cfg_ =
        pe_internal_cpe_enable_cfg_ && cfg.pe_internal_pod_enable;
    pe_internal_pod_metadata_enable_cfg_ =
        pe_internal_pod_enable_cfg_ && cfg.pe_internal_pod_metadata_enable;
    pe_internal_pod_owner_enable_cfg_ =
        pe_internal_pod_enable_cfg_ && cfg.pe_internal_pod_owner_enable;
    pulse_osa_metadata_txn_enable_ = cfg.pulse_osa_metadata_txn_enable;
    pulse_osa_metadata_ready_lease_enable_ =
        cfg.pulse_osa_metadata_ready_lease_enable;
    pulse_osa_metadata_ready_lease_ttl_ =
        cfg.pulse_osa_metadata_ready_lease_ttl;
    pulse_osa_metadata_object_mask_ = cfg.pulse_osa_metadata_object_mask;
    pulse_osa_metadata_object_mask_bits_ =
        parsePulseMetadataObjectMask_(pulse_osa_metadata_object_mask_);
    pe_internal_pod_count_cfg_ = pe_internal_pod_enable_cfg_
        ? static_cast<uint32_t>(normalizePodCount_(
              static_cast<size_t>(std::max(1, num_cores_)),
              cfg.pe_internal_pod_count,
              cfg.pe_internal_pod_size))
        : 1u;
    pe_internal_pod_size_cfg_ = cfg.pe_internal_pod_size;
    if (pe_internal_pod_size_cfg_ == 0u) {
        pe_internal_pod_size_cfg_ = static_cast<uint32_t>(ceilDivU64_(
            static_cast<uint64_t>(std::max(1, num_cores_)),
            static_cast<uint64_t>(std::max<uint32_t>(1u, pe_internal_pod_count_cfg_))));
    }
    pe_internal_pod_size_cfg_ =
        std::max<uint32_t>(1u, pe_internal_pod_size_cfg_);
    if (local_storage_enable_) {
        const bool cpe_scope_enable = cfg.pe_internal_cpe_enable;
        const bool pod_scope_enable = cpe_scope_enable && cfg.pe_internal_pod_enable;
        const size_t pod_count = pod_scope_enable
            ? normalizePodCount_(static_cast<size_t>(std::max(1, num_cores_)),
                                 cfg.pe_internal_pod_count,
                                 cfg.pe_internal_pod_size)
            : 1u;
        LocalStorageHierarchyController::Config ls_cfg{};
        ls_cfg.enable = true;
        ls_cfg.num_cores = static_cast<size_t>(std::max(1, num_cores_));
        ls_cfg.num_pods = pod_count;
        local_storage_controller_ = std::make_unique<LocalStorageHierarchyController>(ls_cfg);

        PhaseALocalStorageRegistrationConfig phase_cfg{};
        phase_cfg.num_cores = ls_cfg.num_cores;
        phase_cfg.num_pods = ls_cfg.num_pods;

        phase_cfg.activation_ingress.name = "activation_ingress_store";
        phase_cfg.activation_ingress.kind = LocalStorageObjectKind::QueueStore;
        phase_cfg.activation_ingress.scope = LocalStorageScope::PerPe;
        phase_cfg.activation_ingress.enable = cfg.ls_activation_ingress_enable;
        phase_cfg.activation_ingress.queue_depth = cfg.ls_activation_ingress_entries;

        phase_cfg.weight_idx.name = "weight_idx_store";
        phase_cfg.weight_idx.kind = LocalStorageObjectKind::AddressableStore;
        phase_cfg.weight_idx.scope = LocalStorageScope::PerPe;
        phase_cfg.weight_idx.enable = cfg.ls_weight_idx_enable;
        phase_cfg.weight_idx.capacity_bytes = cfg.ls_weight_idx_capacity_bytes;
        phase_cfg.weight_idx.banks = cfg.ls_weight_idx_banks;
        phase_cfg.weight_idx.read_ports = cfg.ls_weight_idx_read_ports;
        phase_cfg.weight_idx.write_ports = cfg.ls_weight_idx_write_ports;
        phase_cfg.weight_idx.queue_depth = cfg.ls_weight_idx_queue_depth;

        phase_cfg.weight_value.name = "weight_value_store";
        phase_cfg.weight_value.kind = LocalStorageObjectKind::AddressableStore;
        phase_cfg.weight_value.scope = LocalStorageScope::PerPe;
        phase_cfg.weight_value.enable = cfg.ls_weight_value_enable;
        phase_cfg.weight_value.capacity_bytes = cfg.ls_weight_value_capacity_bytes;
        phase_cfg.weight_value.banks = cfg.ls_weight_value_banks;
        phase_cfg.weight_value.read_ports = cfg.ls_weight_value_read_ports;
        phase_cfg.weight_value.write_ports = cfg.ls_weight_value_write_ports;
        phase_cfg.weight_value.queue_depth = cfg.ls_weight_value_queue_depth;

        if (pod_scope_enable) {
            phase_cfg.pod_metadata_template.name = "pod_metadata_store";
            phase_cfg.pod_metadata_template.kind = LocalStorageObjectKind::AddressableStore;
            phase_cfg.pod_metadata_template.scope = LocalStorageScope::PerPod;
            phase_cfg.pod_metadata_template.enable = cfg.pe_internal_pod_metadata_enable;
            phase_cfg.pod_metadata_template.capacity_bytes =
                cfg.pe_internal_pod_metadata_capacity_bytes;
            phase_cfg.pod_metadata_template.banks =
                std::max<uint32_t>(cfg.pe_internal_pod_metadata_banks, 1u);

            phase_cfg.pod_owner_template.name = "pod_owner_table";
            phase_cfg.pod_owner_template.kind = LocalStorageObjectKind::AddressableStore;
            phase_cfg.pod_owner_template.scope = LocalStorageScope::PerPod;
            phase_cfg.pod_owner_template.enable = cfg.pe_internal_pod_owner_enable;
            phase_cfg.pod_owner_template.capacity_bytes =
                static_cast<uint64_t>(cfg.pe_internal_pod_owner_entries) *
                static_cast<uint64_t>(std::max<uint32_t>(cfg.pe_internal_pod_owner_entry_bytes, 1u));

            phase_cfg.pod_join_template.name = "pod_join_table";
            phase_cfg.pod_join_template.kind = LocalStorageObjectKind::AddressableStore;
            phase_cfg.pod_join_template.scope = LocalStorageScope::PerPod;
            phase_cfg.pod_join_template.enable = cfg.pe_internal_pod_join_enable;
            phase_cfg.pod_join_template.capacity_bytes =
                static_cast<uint64_t>(cfg.pe_internal_pod_join_entries) *
                static_cast<uint64_t>(std::max<uint32_t>(cfg.pe_internal_pod_join_entry_bytes, 1u));

            phase_cfg.pod_ready_template.name = "pod_ready_table";
            phase_cfg.pod_ready_template.kind = LocalStorageObjectKind::QueueStore;
            phase_cfg.pod_ready_template.scope = LocalStorageScope::PerPod;
            phase_cfg.pod_ready_template.enable = cfg.pe_internal_pod_ready_enable;
            phase_cfg.pod_ready_template.queue_depth = cfg.pe_internal_pod_ready_entries;
        }

        phase_cfg.state_template.name = "state_store";
        phase_cfg.state_template.kind = LocalStorageObjectKind::AddressableStore;
        phase_cfg.state_template.scope = LocalStorageScope::PerCore;
        phase_cfg.state_template.enable = cfg.ls_state_enable;
        phase_cfg.state_template.capacity_bytes = cfg.ls_state_capacity_bytes;
        phase_cfg.state_template.banks = cfg.ls_state_banks;
        phase_cfg.state_template.read_ports = cfg.ls_state_read_ports;
        phase_cfg.state_template.write_ports = cfg.ls_state_write_ports;
        phase_cfg.state_template.update_ports = cfg.ls_state_update_ports;
        phase_cfg.state_template.queue_depth = cfg.ls_state_queue_depth;

        phase_cfg.activation_core_template.name = "activation_core_queue";
        phase_cfg.activation_core_template.kind = LocalStorageObjectKind::QueueStore;
        phase_cfg.activation_core_template.scope = LocalStorageScope::PerCore;
        phase_cfg.activation_core_template.enable = cfg.ls_activation_core_enable;
        phase_cfg.activation_core_template.queue_depth = cfg.ls_activation_core_entries;

        phase_cfg.acc_template.name = "accumulator_store";
        phase_cfg.acc_template.kind = LocalStorageObjectKind::AddressableStore;
        phase_cfg.acc_template.scope = LocalStorageScope::PerCore;
        phase_cfg.acc_template.enable = cfg.ls_acc_enable;
        phase_cfg.acc_template.capacity_bytes = cfg.ls_acc_capacity_bytes;
        phase_cfg.acc_template.banks = cfg.ls_acc_banks;
        phase_cfg.acc_template.read_ports = cfg.ls_acc_read_ports;
        phase_cfg.acc_template.write_ports = cfg.ls_acc_write_ports;
        phase_cfg.acc_template.update_ports = cfg.ls_acc_update_ports;
        phase_cfg.acc_template.queue_depth = cfg.ls_acc_queue_depth;

        phase_cfg.rf_template.name = "register_file";
        phase_cfg.rf_template.kind = LocalStorageObjectKind::RegisterFile;
        phase_cfg.rf_template.scope = LocalStorageScope::PerCore;
        phase_cfg.rf_template.enable = cfg.ls_rf_enable;
        phase_cfg.rf_template.entries = cfg.ls_rf_entries;
        phase_cfg.rf_template.entry_bytes = cfg.ls_rf_entry_bytes;
        phase_cfg.rf_template.read_ports = cfg.ls_rf_read_ports;
        phase_cfg.rf_template.write_ports = cfg.ls_rf_write_ports;

        if (!registerDefaultPhaseAObjects(*local_storage_controller_, phase_cfg)) {
            output_->fatal(CALL_INFO, -1,
                           "LocalStorageHierarchyController registration failed at node=%d\n",
                           node_id_);
        }

        if (pod_scope_enable && cfg.pe_internal_pod_metadata_enable) {
            PodMetadataObjectPlane::Config pod_metadata_cfg{};
            pod_metadata_cfg.enable = true;
            pod_metadata_cfg.num_pods = static_cast<uint32_t>(pod_count);
            if (cfg.pe_internal_pod_metadata_capacity_bytes > 0) {
                const uint64_t raw_entries =
                    cfg.pe_internal_pod_metadata_capacity_bytes /
                    static_cast<uint64_t>(kPodMetadataShadowEntryBytes);
                pod_metadata_cfg.capacity_entries_per_pod =
                    static_cast<uint32_t>(std::max<uint64_t>(1u, raw_entries));
            }
            pod_metadata_object_plane_ =
                std::make_unique<PodMetadataObjectPlane>(pod_metadata_cfg);
        }
        if (pod_scope_enable && cfg.pe_internal_pod_owner_enable) {
            PodOwnerServiceTable::Config pod_owner_cfg{};
            pod_owner_cfg.enable = true;
            pod_owner_cfg.num_pods = static_cast<uint32_t>(pod_count);
            pod_owner_cfg.owner_entries_per_pod = cfg.pe_internal_pod_owner_entries;
            pod_owner_cfg.join_entries_per_pod = cfg.pe_internal_pod_join_entries;
            pod_owner_service_table_ =
                std::make_unique<PodOwnerServiceTable>(pod_owner_cfg);
        }
        if (pod_scope_enable &&
            cfg.pe_internal_pod_metadata_enable &&
            cfg.pe_internal_pod_owner_enable &&
            (cfg.pe_internal_pod_join_enable || cfg.pe_internal_pod_ready_enable)) {
            PeLocalServiceObjectTable::Config service_cfg{};
            const bool pulse_osa_metadata_ready_lease_gate =
                (cfg.pulse_osa_enable &&
                 workloadAllowsPureSnnDatapathFeatures(cfg.workload_kind) &&
                 cfg.pulse_osa_metadata_txn_enable &&
                 cfg.pulse_osa_metadata_ready_lease_enable &&
                 cfg.pulse_osa_metadata_ready_lease_ttl > 0u);
            const uint32_t pulse_metadata_mask =
                parsePulseMetadataObjectMask_(cfg.pulse_osa_metadata_object_mask);
            const bool ready_lease_enable =
                pulse_osa_metadata_ready_lease_gate &&
                pulse_metadata_mask != 0u;
            service_cfg.enable = true;
            service_cfg.num_pods = static_cast<uint32_t>(pod_count);
            service_cfg.active_entries_per_pod =
                std::max(cfg.pe_internal_pod_owner_entries, cfg.pe_internal_pod_join_entries);
            service_cfg.released_entries_per_pod =
                std::max(cfg.pe_internal_pod_ready_entries, cfg.pe_internal_pod_join_entries);
            service_cfg.ready_lease_enable = ready_lease_enable;
            service_cfg.ready_lease_ttl =
                ready_lease_enable ? cfg.pulse_osa_metadata_ready_lease_ttl : 0u;
            service_cfg.ready_lease_kind_mask =
                ready_lease_enable ? pulse_metadata_mask : 0u;
            pe_local_service_object_table_ =
                std::make_unique<PeLocalServiceObjectTable>(service_cfg);
        }
    }

    pulse_osa_requested_ = cfg.pulse_osa_enable;
    pulse_osa_shared_weight_owner_requested_ = cfg.pulse_osa_shared_weight_owner_enable;
    pulse_osa_shared_weight_owner_actual_requested_ =
        cfg.pulse_osa_shared_weight_owner_actual_enable;
    pulse_osa_enable_ =
        cfg.pulse_osa_enable && pure_snn_datapath_workload_eligible_;
    pulse_osa_shared_weight_owner_enable_ =
        pulse_osa_enable_ &&
        cfg.pulse_osa_shared_weight_owner_enable &&
        local_storage_enable_;
    pulse_osa_shared_weight_owner_actual_enable_ =
        pulse_osa_shared_weight_owner_enable_ &&
        cfg.pulse_osa_shared_weight_owner_actual_enable;
    if (pulse_osa_enable_ && pulse_osa_shared_weight_owner_enable_) {
        PeWeightObjectPlane::Config osa_weight_cfg{};
        osa_weight_cfg.enable = true;
        osa_weight_cfg.owner_scope_enable = true;
        osa_weight_cfg.actual_owner_enable = pulse_osa_shared_weight_owner_actual_enable_;
        osa_weight_cfg.idx_enable = cfg.ls_weight_idx_enable;
        osa_weight_cfg.l0_enable = cfg.ls_weight_value_enable;
        osa_weight_cfg.idx_capacity_bytes = cfg.ls_weight_idx_capacity_bytes;
        osa_weight_cfg.l0_capacity_bytes = cfg.ls_weight_value_capacity_bytes;
        osa_weight_cfg.idx_banks = cfg.ls_weight_idx_banks;
        osa_weight_cfg.l0_banks = cfg.ls_weight_value_banks;
        osa_weight_cfg.ports_per_bank = std::max<uint32_t>(
            1u,
            std::max(
                std::max(cfg.ls_weight_idx_read_ports, cfg.ls_weight_idx_write_ports),
                std::max(cfg.ls_weight_value_read_ports, cfg.ls_weight_value_write_ports)));
        pe_weight_object_plane_ = std::make_unique<PeWeightObjectPlane>(osa_weight_cfg);
    }

    pulse_enable_requested_ = cfg.pulse_enable;
    pulse_descriptor_actual_requested_ = cfg.pulse_descriptor_actual_enable;
    pulse_enable_ = cfg.pulse_enable && pure_snn_datapath_workload_eligible_;
    if (cfg.pulse_enable && !pulse_enable_ && output_) {
        output_->verbose(CALL_INFO, 1, 0,
                         "[pulse] ignore pulse_enable for non-SNN workload_impl=%s node=%d\n",
                         cfg.workload_impl.c_str(),
                         node_id_);
    }
    if (pulse_enable_) {
        PeSharedCoreFabric::Config pulse_cfg{};
        pulse_cfg.enable = true;
        pulse_cfg.observe_only = cfg.pulse_observe_only;
        pulse_cfg.ingress_enable = cfg.pulse_ingress_enable;
        pulse_cfg.agenda_observe_only = cfg.pulse_agenda_observe_only;
        pulse_cfg.harbor_enable = cfg.pulse_harbor_enable;
        pulse_cfg.descriptor_enable = cfg.pulse_descriptor_enable;
        pulse_cfg.descriptor_actual_enable = cfg.pulse_descriptor_actual_enable;
        pulse_cfg.num_cores = static_cast<size_t>(std::max(1, num_cores_));
        pulse_cfg.ingress_entries = cfg.pulse_ingress_entries;
        pulse_cfg.core_queue_entries = cfg.pulse_core_queue_entries;
        pulse_cfg.descriptor_packet_min = cfg.pulse_descriptor_packet_min;
        pulse_cfg.bypass_high_watermark_pct = cfg.pulse_bypass_high_watermark_pct;
        pulse_cfg.bypass_mode =
            (cfg.pulse_bypass_mode == "high_watermark")
                ? PeSharedCoreFabric::BypassMode::HighWatermark
                : PeSharedCoreFabric::BypassMode::Disabled;
        if (!pulse_cfg.observe_only &&
            (!pulse_cfg.ingress_enable || pulse_cfg.ingress_entries == 0) &&
            output_) {
            output_->verbose(CALL_INFO, 1, 0,
                             "[pulse] disable actual ingress path without ingress store (node=%d ingress_enable=%d ingress_entries=%u)\n",
                             node_id_,
                             pulse_cfg.ingress_enable ? 1 : 0,
                             pulse_cfg.ingress_entries);
            pulse_cfg.observe_only = true;
        }
        if (!pulse_cfg.agenda_observe_only && output_) {
            output_->verbose(CALL_INFO, 1, 0,
                             "[pulse] current rollout keeps agenda observe-only semantics at node=%d\n",
                             node_id_);
            pulse_cfg.agenda_observe_only = true;
        }
        if (pulse_cfg.descriptor_actual_enable && output_) {
            output_->verbose(CALL_INFO, 1, 0,
                             "[pulse] fabric-side descriptor actual service remains disabled at node=%d; core-side WMS actual path may still be enabled\n",
                             node_id_);
            pulse_cfg.descriptor_actual_enable = false;
        }
        pulse_fabric_ = std::make_unique<PeSharedCoreFabric>(pulse_cfg);
    }

    // Global Step/GAS barrier sync (Phase-step-sync)
    global_step_sync_enable_ = cfg.global_step_sync_enable;
    {
        std::string pol = cfg.global_step_done_policy;
        if (pol == "drain" || pol == "drain_based" || pol == "drainbased") {
            global_step_done_policy_ = GlobalStepDonePolicy::Drain;
        } else if (pol == "fixed" || pol == "fixed_cycles" || pol == "timer") {
            global_step_done_policy_ = GlobalStepDonePolicy::FixedCycles;
        } else if (pol == "quiescent" || pol == "quiet") {
            global_step_done_policy_ = GlobalStepDonePolicy::Quiescent;
        } else {
            global_step_done_policy_ = GlobalStepDonePolicy::EndScatter;
        }
    }
    global_step_quiescent_min_cycles_ = cfg.global_step_quiescent_min_cycles;
    global_step_drain_min_cycles_ = cfg.global_step_drain_min_cycles;
    global_step_fixed_cycles_ = cfg.global_step_fixed_cycles;
    // Step-limited fairness: avoid starting step injection while WeightLoader/BCSR metadata is not ready.
    // In naive_* (non-window) mode, issuing BCSR reads before loader/rowptr ready can enqueue millions of waiters.
    loader_done_key_ = cfg.loader_done_key;
    global_step_ready_delay_cycles_ = cfg.global_step_ready_delay_cycles;
    loader_done_timeout_cycles_ = params.find<uint64_t>("loader_done_timeout_cycles", 0);
    wait_for_loader_done_ = (!loader_done_key_.empty());
    loader_ready_latched_ = false;
    loader_ready_cycle_ = 0;
    if (wait_for_loader_done_) {
        loader_done_shared_ = std::make_unique<SST::Shared::SharedArray<int>>();
        loader_done_shared_->initialize(loader_done_key_, 1, 0);
    }

    // Step-level random activation injection (Phase3-B): 下沉为独立子系统（MultiCorePE 仅转发 tick/阶段事件）
    {
        const bool step_seed_only_mode = params.find<int>("step_seed_only_mode", 0) != 0;
        StepActivationSubsystem::Config step_cfg;
        step_cfg.enable = cfg.step_activation_enable;
        step_cfg.fraction = cfg.step_activation_fraction;
        step_cfg.fanout = cfg.step_activation_fanout;
        step_cfg.seed = cfg.step_activation_seed;
        step_cfg.period_cycles = cfg.step_activation_period_cycles;
        step_cfg.trigger_core = cfg.step_activation_trigger_core;
        step_cfg.reset_mem_each_step = cfg.step_reset_mem_each_step || step_seed_only_mode;
        step_cfg.event_weight = cfg.step_activation_event_weight;
        {
            const std::string& pat = cfg.step_activation_pre_pattern;
            if (pat == "clustered" || pat == "cluster" || pat == "block") {
                step_cfg.pre_pattern = StepActivationSubsystem::Config::PrePattern::Clustered;
            } else {
                step_cfg.pre_pattern = StepActivationSubsystem::Config::PrePattern::BernoulliUniform;
            }
        }
        step_cfg.pre_cluster_len = cfg.step_activation_pre_cluster_len;
        step_cfg.use_bcsr_routes = cfg.step_activation_use_bcsr_routes;
        step_cfg.bcsr_template = cfg.step_activation_bcsr_template;
        step_cfg.bcsr_rows_per_core =
            (cfg.step_activation_bcsr_rows_per_core > 0)
                ? cfg.step_activation_bcsr_rows_per_core
                : static_cast<uint32_t>(neurons_per_core_);
        step_cfg.bcsr_br = cfg.step_activation_bcsr_br;
        step_cfg.bcsr_bc = cfg.step_activation_bcsr_bc;
        step_cfg.bcsr_idx_bytes = cfg.step_activation_bcsr_idx_bytes;
        step_cfg.bcsr_val_bytes = cfg.step_activation_bcsr_val_bytes;
        step_cfg.bcsr_rowptr_offset = cfg.step_activation_bcsr_rowptr_offset;
        step_cfg.bcsr_colidx_offset = cfg.step_activation_bcsr_colidx_offset;
        step_cfg.bcsr_blockdata_offset = cfg.step_activation_bcsr_blockdata_offset;
        step_cfg.bcsr_blockids_offset = cfg.step_activation_bcsr_blockids_offset;
        step_cfg.bcsr_weight_epsilon = cfg.step_activation_bcsr_weight_epsilon;
        step_cfg.log_enable = cfg.step_activation_log_enable;
        step_cfg.build_local_only = cfg.step_activation_build_local_only;
        step_cfg.bcsr_align = cfg.step_activation_bcsr_align;

        // 仅对真正的非 SNN datapath workload 禁用 step stimulus；`riscv_snn` 的 runtime_bridge
        // 仍需要 seed 注入来驱动 shadow SNN 数据面，否则 transport surface 会被静默饿死。
        if (!workloadAllowsSnnStimulus(cfg.workload_kind)) {
            step_cfg.enable = false;
            step_cfg.fraction = 0.0;
            step_cfg.fanout = 0;
            step_cfg.period_cycles = 0;
            step_cfg.use_bcsr_routes = false;
            step_cfg.bcsr_template.clear();
        }

        step_activation_subsys_.configure(step_cfg);

        StepActivationSubsystem::Runtime step_rt;
        step_rt.log = output_;
        step_rt.node_id = node_id_;
        step_rt.total_nodes = total_nodes_;
        step_rt.global_neuron_base = global_neuron_base_;
        step_rt.num_cores = num_cores_;
        step_rt.neurons_per_core = neurons_per_core_;
        step_rt.neurons_per_pe_cfg = neurons_per_pe_cfg_;
        step_rt.layout = &global_layout_;
        step_rt.sentinel_enabled = sentinel_enabled_;
        step_rt.step_diag_cap_cfg = step_diag_cap_cfg_;
        step_rt.step_diag_enable_cfg = step_diag_enable_cfg_;
        step_rt.noc = &noc_subsys_;
        step_rt.reset_membranes = [this]() { resetAllCoreMembranes(); };
        step_rt.report_injection_summary = [this](uint32_t seq,
                                                 uint64_t pre_selected,
                                                 uint64_t spike_attempts,
                                                 uint64_t spikes_injected,
                                                 uint64_t route_hits,
                                                 uint64_t route_misses,
                                                 uint64_t local_drops) {
            recordStepActivationSummary(seq, pre_selected, spike_attempts, spikes_injected,
                                        route_hits, route_misses, local_drops);
        };

        step_activation_subsys_.bindRuntime(step_rt);
        step_activation_subsys_.initBcsrReachabilityIfEnabled();
    }

    // 外部端口 SpikeEvent 直注入（仅本地投递）：收敛为 Stimulus 子系统，MultiCorePE 仅装配/转发。
    {
        ExternalSpikeInputSubsystem::Runtime ex_rt;
        ex_rt.log = output_;
        ex_rt.node_id = node_id_;
        ex_rt.layout = &global_layout_;
        ex_rt.noc = &noc_subsys_;
        ex_rt.enabled = workloadAllowsSnnStimulus(cfg.workload_kind);
        ex_rt.global_neuron_base = global_neuron_base_;
        ex_rt.num_cores = num_cores_;
        ex_rt.neurons_per_core = neurons_per_core_;
        ex_rt.total_neurons = total_neurons_;
        external_spike_input_subsys_.bindRuntime(ex_rt);
    }

    // Phase3-C：Spike 编解码与投递 glue 下沉为 synapse/route 子系统；MultiCorePE 仅装配。
    {
        SpikePacketBridge::Runtime brt;
        brt.log = output_;
        brt.node_id = node_id_;
        brt.num_cores = num_cores_;
        brt.layout = &global_layout_;
        brt.noc = &noc_subsys_;
        if (exec_mode_ == "naive_raw" && global_step_sync_enable_) {
            brt.active_step_seq = &global_step_active_seq_;
            brt.step_seq_offset = 1;
        }
        spike_packet_bridge_.bindRuntime(brt);
    }
    
    //     "🔧 多核PE配置: cores=%d, neurons_per_core=%d, total_neurons=%d, node_id=%d\n",
    //     num_cores_, neurons_per_core_, total_neurons_, node_id_);
    
    //     "🧠 神经元参数: v_thresh=%.3f, v_reset=%.3f, v_rest=%.3f, tau_mem=%.1fms, t_ref=%d\n",
    //     v_thresh_, v_reset_, v_rest_, tau_mem_, t_ref_);

    // 验证参数合理性
    if (num_cores_ <= 0 || num_cores_ > 64) {
        output_->fatal(CALL_INFO, -1, "❌ 错误: num_cores必须在1-64之间，当前值=%d\n", num_cores_);
    }
    // 放宽每核神经元上限，支持大规模单PE评估（例如 20核×50k/核 = 1M/PE）
    // 原上限为 1024，现放宽至 65536；如需更大规模，可视硬件内存与仿真需求再调高。
    if (neurons_per_core_ <= 0 || neurons_per_core_ > 65536) {
        output_->fatal(CALL_INFO, -1, "❌ 错误: neurons_per_core必须在1-65536之间，当前值=%d\n", neurons_per_core_);
    }

    // 初始化时钟计数器
    current_cycle_ = 0;
    test_cycle_counter_ = 0;
    test_spikes_sent_ = 0;
    
    // 初始化处理单元状态追踪
    unit_states_.resize(num_cores_);
    for (int i = 0; i < num_cores_; i++) {
        unit_states_[i].unit_id = i;
        unit_states_[i].neuron_id_start = i * neurons_per_core_;
        unit_states_[i].neuron_count = neurons_per_core_;
        unit_states_[i].is_active = false;
        unit_states_[i].spikes_processed = 0;
        unit_states_[i].neurons_fired = 0;
        unit_states_[i].utilization = 0.0;
    }
    
    // 初始化组件指针为空
    l2_cache_ = nullptr;
    external_nic_ = nullptr;
    optimized_ring_ = nullptr;
    controller_ = nullptr;
    
    // 初始化端口指针为空
    external_spike_input_link_ = nullptr;
    external_spike_output_link_ = nullptr;
    mem_link_ = nullptr;
    
    
    // 初始化统计收集（必须在构造函数中）
    initializeStatistics();
    {
        StepActivationSubsystem::Stats st;
        st.invocations = stat_step_activation_invocations_;
        st.pre_selected = stat_step_activation_pre_selected_;
        st.spike_attempts = stat_step_activation_spike_attempts_;
        st.spikes_injected = stat_step_activation_spikes_injected_;
        st.route_hits = stat_step_activation_route_hits_;
        st.route_misses = stat_step_activation_route_misses_;
        st.local_drops = stat_step_activation_local_drops_;
        step_activation_subsys_.bindStats(st);
    }
    {
        NocSubsystem::Config noc_cfg;
        noc_cfg.log_enable = (verbose_ >= 5);
        noc_subsys_.configure(noc_cfg);

        NocSubsystem::Stats noc_st;
        noc_st.external_spikes_received = stat_external_spikes_received_;
        noc_st.external_spikes_sent = stat_external_spikes_sent_;
        noc_st.inter_core_messages = stat_inter_core_messages_;
        noc_subsys_.bindStats(noc_st);

        NocSubsystem::Runtime noc_rt;
        noc_rt.log = output_;
        noc_rt.node_id = node_id_;
        noc_rt.num_cores = num_cores_;
        noc_rt.nic = nullptr;  // init 后再注入
        noc_rt.optimized_ring = nullptr;  // init 后再注入
        noc_rt.external_spike_output_link = nullptr;  // init(phase0) link configured 后再注入
        if (exec_mode_ == "naive_raw" && global_step_sync_enable_) {
            noc_rt.active_step_seq = &global_step_active_seq_;
            noc_rt.step_seq_offset = 1;
        }
        noc_rt.deliver_to_endpoint = [this](int endpoint_id, NocPacketEvent* pkt) {
            deliverPacketToEndpoint_(endpoint_id, pkt);
        };
        noc_subsys_.bindRuntime(noc_rt);
    }
    // 记录路径（若提供），用于派生输出目录
    stage_events_csv_path_ = cfg.stage_events_csv_path;
    stats_csv_path_ = cfg.stats_csv_path;
    
    // 关键修复：在构造函数中初始化网络接口，确保SST能在正确时机调用init()
    initializeNetworkInterface();
}

MultiCorePE::~MultiCorePE() {
    clearAllDeferredPackets_();
    clearAllPulseIngressPackets_();

    // 清理SnnPE SubComponent核心（SST会自动管理SubComponent的生命周期）
    cores_.clear();
    
    // 清理内部组件
    delete optimized_ring_;
    delete controller_;
    // 避免析构次序竞态：不手动delete日志对象
    output_ = nullptr;
}

void MultiCorePE::init(unsigned int phase) {
    if (sentinel_enabled_ && output_) { output_->verbose(CALL_INFO, 2, 0, "[[sentinel-pe-init]] node=%d phase=%u enter\n", node_id_, phase); }

    // WeightLoader -> MultiCorePE loader_done bridge uses untimed data during init/setup.
    // We must actively drain recvUntimedData(); a timed handler will not be invoked.
    if (loader_done_link_) {
        SST::Event* ev = loader_done_link_->recvUntimedData();
        while (ev) {
            handleLoaderDoneEvent(ev);
            ev = loader_done_link_->recvUntimedData();
        }
    }
    if (phase == 0) {
        if (primary_keepalive_ || sim_stop_ns_ > 0) {
            registerAsPrimaryComponent();
            primaryComponentDoNotEndSim();
        }
        // 阶段0：初始化基础组件和端口
        
        // 配置时钟
        std::string clock_freq = clock_freq_;
        // 不需要单独的clock_handler_变量
        registerClock(clock_freq, new Clock::Handler2<MultiCorePE,&MultiCorePE::clockTick>(this));
        if (sentinel_enabled_ && output_) { output_->verbose(CALL_INFO, 2, 0, "[[sentinel-pe-init]] node=%d phase=0 clock-registered\n", node_id_); }
        
        
        // 初始化统计收集
        
        // 初始化端口连接
        external_spike_input_link_ = configureLink("external_spike_input", 
            new Event::Handler2<MultiCorePE,&MultiCorePE::handleExternalSpikeEvent>(this));
        external_spike_output_link_ = configureLink("external_spike_output");
        mem_link_ = configureLink("mem_link");
        loader_done_link_ = configureLink(
            "loader_done",
            new Event::Handler2<MultiCorePE, &MultiCorePE::handleLoaderDoneEvent>(this));
        if (loader_done_link_) {
            SST::Event* ev = loader_done_link_->recvUntimedData();
            while (ev) {
                handleLoaderDoneEvent(ev);
                ev = loader_done_link_->recvUntimedData();
            }
        }
        if (global_step_sync_enable_) {
            gas_step_ctrl_link_ = configureLink(
                "gas_step_ctrl",
                new Event::Handler2<MultiCorePE, &MultiCorePE::handleGasStepCtrlEvent>(this));
            if (!gas_step_ctrl_link_) {
                output_->fatal(CALL_INFO, -1, "❌ 配置错误：global_step_sync_enable=1 但端口 gas_step_ctrl 未连接\n");
            }
        }
        if (sentinel_enabled_ && output_) { output_->verbose(CALL_INFO, 2, 0, "[[sentinel-pe-init]] node=%d phase=0 links-configured\n", node_id_); }
        
        
        // 初始化方向链路（用于端口代理机制）
        initializeDirectionLinks();
        if (sentinel_enabled_ && output_) { output_->verbose(CALL_INFO, 2, 0, "[[sentinel-pe-init]] node=%d phase=0 dir-links\n", node_id_); }
        
        // 初始化处理单元
        initializeProcessingUnits();
        if (sentinel_enabled_ && output_) { output_->verbose(CALL_INFO, 2, 0, "[[sentinel-pe-init]] node=%d phase=0 units-initialized\n", node_id_); }
        
        // 初始化内部互连
        initializeInternalRing();
        if (sentinel_enabled_ && output_) { output_->verbose(CALL_INFO, 2, 0, "[[sentinel-pe-init]] node=%d phase=0 ring-initialized\n", node_id_); }

        // Phase4-A1.2：NoC 子系统后端装配（NIC / ring / legacy link）
        {
            NocSubsystem::Runtime noc_rt;
            noc_rt.log = output_;
            noc_rt.node_id = node_id_;
            noc_rt.num_cores = num_cores_;
            noc_rt.nic = external_nic_;
            noc_rt.optimized_ring = optimized_ring_;
            noc_rt.external_spike_output_link = external_spike_output_link_;
            if (exec_mode_ == "naive_raw" && global_step_sync_enable_) {
                noc_rt.active_step_seq = &global_step_active_seq_;
                noc_rt.step_seq_offset = 1;
            }
            noc_rt.deliver_to_endpoint = [this](int endpoint_id, NocPacketEvent* pkt) {
                deliverPacketToEndpoint_(endpoint_id, pkt);
            };
            noc_subsys_.bindRuntime(noc_rt);
        }
        
        // 初始化多核控制器
        controller_ = new MultiCoreController(this, output_);
        if (sentinel_enabled_ && output_) { output_->verbose(CALL_INFO, 2, 0, "[[sentinel-pe-init]] node=%d phase=0 controller-created\n", node_id_); }
        

        // 将当前phase转发给所有子核心
        for (auto* core : cores_) {
            if (core) core->init(phase);
        }
        if (sentinel_enabled_ && output_) { output_->verbose(CALL_INFO, 2, 0, "[[sentinel-pe-init]] node=%d phase=0 cores-init-done\n", node_id_); }
        
        // 关键修复：转发init到网络接口
        if (external_nic_) {
            external_nic_->init(phase);
        }
        if (sentinel_enabled_ && output_) { output_->verbose(CALL_INFO, 2, 0, "[[sentinel-pe-init]] node=%d phase=0 nic-init-done\n", node_id_); }
        // 标记 Step 注入就绪（保证 NIC 已完成 init）
        step_activation_subsys_.setInjectionReady(true);
    }
    else if (phase == 1) {
        if (sentinel_enabled_ && output_) { output_->verbose(CALL_INFO, 2, 0, "[[sentinel-pe-init]] node=%d phase=1 enter\n", node_id_); }
        // 阶段1：加载权重和配置子组件
        loadAndDistributeWeights();
        if (sentinel_enabled_ && output_) { output_->verbose(CALL_INFO, 2, 0, "[[sentinel-pe-init]] node=%d phase=1 weights-loaded\n", node_id_); }

        // 将当前phase转发给所有子核心
        for (auto* core : cores_) {
            if (core) core->init(phase);
        }
        if (sentinel_enabled_ && output_) { output_->verbose(CALL_INFO, 2, 0, "[[sentinel-pe-init]] node=%d phase=1 cores-init-done\n", node_id_); }
        
        // 转发init到网络接口
        if (external_nic_) {
            external_nic_->init(phase);
        }
        if (sentinel_enabled_ && output_) { output_->verbose(CALL_INFO, 2, 0, "[[sentinel-pe-init]] node=%d phase=1 nic-init-done\n", node_id_); }
    }
    else {
        if (sentinel_enabled_ && output_) { output_->verbose(CALL_INFO, 2, 0, "[[sentinel-pe-init]] node=%d phase=%u forward-only\n", node_id_, phase); }
        // 其余phase同样转发
        for (auto* core : cores_) {
            if (core) core->init(phase);
        }
        
        // 转发init到网络接口
        if (external_nic_) {
            external_nic_->init(phase);
        }
        if (sentinel_enabled_ && output_) { output_->verbose(CALL_INFO, 2, 0, "[[sentinel-pe-init]] node=%d phase=%u done\n", node_id_, phase); }
    }
}

void MultiCorePE::complete(unsigned int phase) {
    // 关键：转发 complete 给所有子核心与网络接口。
    // 若核心 memory 子组件内部使用 memHierarchy.standardInterface，则 complete() 是完成
    // init 握手/地址域传播的必要阶段；缺失会导致 getTargetDestination 找不到地址域并 fatal。
    for (auto* core : cores_) {
        if (core) core->complete(phase);
    }
    if (external_nic_) {
        external_nic_->complete(phase);
    }
}

void MultiCorePE::setup() {
    if (sentinel_enabled_ && output_) { output_->verbose(CALL_INFO, 2, 0, "[[sentinel-pe-setup]] node=%d enter\n", node_id_); }

    // Drain any remaining untimed loader_done events (e.g. strict_loader_done publishes in setup).
    if (loader_done_link_) {
        SST::Event* ev = loader_done_link_->recvUntimedData();
        while (ev) {
            handleLoaderDoneEvent(ev);
            ev = loader_done_link_->recvUntimedData();
        }
    }
    
    // 验证所有组件初始化完成
    if (cores_.size() != static_cast<size_t>(num_cores_)) {
        output_->fatal(CALL_INFO, -1, "❌ 错误: 核心数量不匹配，期望%d，实际%zu\n", 
                      num_cores_, cores_.size());
    }
    
    // 检查内部互连（Phase5：仅保留 OptimizedInternalRing）
    // 单核情况下不需要内部互连
    if (num_cores_ > 1 && !optimized_ring_) {
        output_->fatal(CALL_INFO, -1, "❌ 错误: 多核配置但内部互连未初始化\n");
    }
    // 调用子核心的setup
    for (auto* core : cores_) {
        if (core) core->setup();
    }
    if (sentinel_enabled_ && output_) { output_->verbose(CALL_INFO, 2, 0, "[[sentinel-pe-setup]] node=%d cores-setup\n", node_id_); }
    
    // 调用网络接口的setup
    if (external_nic_) {
        external_nic_->setup();
    }
    if (sentinel_enabled_ && output_) { output_->verbose(CALL_INFO, 2, 0, "[[sentinel-pe-setup]] node=%d nic-setup\n", node_id_); }
    
    if (!controller_) {
        output_->fatal(CALL_INFO, -1, "❌ 错误: 多核控制器未初始化\n");
    }

    global_step_sync_ready_ = true;
    // Step barrier readiness:
    // - default: send PE_READY at setup (legacy behavior)
    // - if loader_done_key is provided: delay PE_READY until WeightLoader publishes done (prevents naive_* blowups)
    if (global_step_sync_enable_ && gas_step_ctrl_link_ && !global_step_ready_sent_) {
        if (!wait_for_loader_done_) {
            auto* ev = new GasStepBarrierEvent(GasStepBarrierOp::PeReady, /*seq*/0, static_cast<uint32_t>(node_id_));
            gas_step_ctrl_link_->send(ev);
            global_step_ready_sent_ = true;
        }
    }
    
    // 打印组件配置摘要
    
}

void MultiCorePE::finish() {
    if (pulse_fabric_) {
        pulse_fabric_->finalizeGatherHarbor();
    }
    // 更新最终统计信息
    updateStatistics();
    if (pe_local_service_object_table_) {
        const auto service_stats = pe_local_service_object_table_->snapshotStats();
        if (stat_atlas_service_enabled_) {
            stat_atlas_service_enabled_->addData(service_stats.enabled ? 1u : 0u);
        }
        if (stat_atlas_service_owner_form_total_) {
            stat_atlas_service_owner_form_total_->addData(service_stats.owner_form_total);
        }
        if (stat_atlas_service_join_live_total_) {
            stat_atlas_service_join_live_total_->addData(service_stats.join_live_total);
        }
        if (stat_atlas_service_join_ready_total_) {
            stat_atlas_service_join_ready_total_->addData(service_stats.join_ready_total);
        }
        if (stat_atlas_service_late_join_total_) {
            stat_atlas_service_late_join_total_->addData(service_stats.late_join_total);
        }
        if (stat_atlas_service_duplicate_join_total_) {
            stat_atlas_service_duplicate_join_total_->addData(service_stats.duplicate_join_total);
        }
        if (stat_atlas_service_ready_transition_total_) {
            stat_atlas_service_ready_transition_total_->addData(
                service_stats.ready_transition_total);
        }
        if (stat_atlas_service_ready_fanout_total_) {
            stat_atlas_service_ready_fanout_total_->addData(service_stats.ready_fanout_total);
        }
        if (stat_atlas_service_ready_fanout_consumers_sum_) {
            stat_atlas_service_ready_fanout_consumers_sum_->addData(
                service_stats.ready_fanout_consumers_sum);
        }
        if (stat_atlas_service_ready_fanout_consumers_peak_) {
            stat_atlas_service_ready_fanout_consumers_peak_->addData(
                service_stats.ready_fanout_consumers_peak);
        }
        if (stat_atlas_service_released_total_) {
            stat_atlas_service_released_total_->addData(service_stats.released_total);
        }
        if (stat_atlas_service_release_deferred_total_) {
            stat_atlas_service_release_deferred_total_->addData(
                service_stats.release_deferred_total);
        }
        if (stat_atlas_service_ready_release_total_) {
            stat_atlas_service_ready_release_total_->addData(
                service_stats.ready_release_total);
        }
        if (stat_atlas_service_ready_lease_hit_total_) {
            stat_atlas_service_ready_lease_hit_total_->addData(
                service_stats.ready_lease_hit_total);
        }
        if (stat_atlas_service_ready_lease_expired_total_) {
            stat_atlas_service_ready_lease_expired_total_->addData(
                service_stats.ready_lease_expired_total);
        }
        if (stat_atlas_service_potential_private_service_elide_total_) {
            stat_atlas_service_potential_private_service_elide_total_->addData(
                service_stats.potential_private_service_elide_total);
        }
        if (stat_atlas_service_active_entries_total_) {
            stat_atlas_service_active_entries_total_->addData(service_stats.active_entries_total);
        }
        if (stat_atlas_service_release_pending_active_total_) {
            stat_atlas_service_release_pending_active_total_->addData(
                service_stats.release_pending_active_total);
        }
        if (stat_atlas_service_atlas_obj_materialize_total_) {
            stat_atlas_service_atlas_obj_materialize_total_->addData(
                service_stats.atlas_obj_materialize_total);
        }
        if (stat_atlas_service_atlas_obj_publicize_total_) {
            stat_atlas_service_atlas_obj_publicize_total_->addData(
                service_stats.atlas_obj_publicize_total);
        }
        if (stat_atlas_service_atlas_obj_owner_form_total_) {
            stat_atlas_service_atlas_obj_owner_form_total_->addData(
                service_stats.atlas_obj_owner_form_total);
        }
        if (stat_atlas_service_atlas_obj_ready_total_) {
            stat_atlas_service_atlas_obj_ready_total_->addData(
                service_stats.atlas_obj_ready_total);
        }
        if (stat_atlas_service_atlas_obj_release_total_) {
            stat_atlas_service_atlas_obj_release_total_->addData(
                service_stats.atlas_obj_release_total);
        }
        if (stat_atlas_service_atlas_obj_private_only_total_) {
            stat_atlas_service_atlas_obj_private_only_total_->addData(
                service_stats.atlas_obj_private_only_total);
        }
    } else {
        if (stat_atlas_service_enabled_) stat_atlas_service_enabled_->addData(0u);
        if (stat_atlas_service_owner_form_total_) stat_atlas_service_owner_form_total_->addData(0u);
        if (stat_atlas_service_join_live_total_) stat_atlas_service_join_live_total_->addData(0u);
        if (stat_atlas_service_join_ready_total_) stat_atlas_service_join_ready_total_->addData(0u);
        if (stat_atlas_service_late_join_total_) stat_atlas_service_late_join_total_->addData(0u);
        if (stat_atlas_service_duplicate_join_total_) {
            stat_atlas_service_duplicate_join_total_->addData(0u);
        }
        if (stat_atlas_service_ready_transition_total_) {
            stat_atlas_service_ready_transition_total_->addData(0u);
        }
        if (stat_atlas_service_ready_fanout_total_) stat_atlas_service_ready_fanout_total_->addData(0u);
        if (stat_atlas_service_ready_fanout_consumers_sum_) {
            stat_atlas_service_ready_fanout_consumers_sum_->addData(0u);
        }
        if (stat_atlas_service_ready_fanout_consumers_peak_) {
            stat_atlas_service_ready_fanout_consumers_peak_->addData(0u);
        }
        if (stat_atlas_service_released_total_) stat_atlas_service_released_total_->addData(0u);
        if (stat_atlas_service_release_deferred_total_) {
            stat_atlas_service_release_deferred_total_->addData(0u);
        }
        if (stat_atlas_service_ready_release_total_) {
            stat_atlas_service_ready_release_total_->addData(0u);
        }
        if (stat_atlas_service_ready_lease_hit_total_) {
            stat_atlas_service_ready_lease_hit_total_->addData(0u);
        }
        if (stat_atlas_service_ready_lease_expired_total_) {
            stat_atlas_service_ready_lease_expired_total_->addData(0u);
        }
        if (stat_atlas_service_potential_private_service_elide_total_) {
            stat_atlas_service_potential_private_service_elide_total_->addData(0u);
        }
        if (stat_atlas_service_active_entries_total_) {
            stat_atlas_service_active_entries_total_->addData(0u);
        }
        if (stat_atlas_service_release_pending_active_total_) {
            stat_atlas_service_release_pending_active_total_->addData(0u);
        }
        if (stat_atlas_service_atlas_obj_materialize_total_) {
            stat_atlas_service_atlas_obj_materialize_total_->addData(0u);
        }
        if (stat_atlas_service_atlas_obj_publicize_total_) {
            stat_atlas_service_atlas_obj_publicize_total_->addData(0u);
        }
        if (stat_atlas_service_atlas_obj_owner_form_total_) {
            stat_atlas_service_atlas_obj_owner_form_total_->addData(0u);
        }
        if (stat_atlas_service_atlas_obj_ready_total_) {
            stat_atlas_service_atlas_obj_ready_total_->addData(0u);
        }
        if (stat_atlas_service_atlas_obj_release_total_) {
            stat_atlas_service_atlas_obj_release_total_->addData(0u);
        }
        if (stat_atlas_service_atlas_obj_private_only_total_) {
            stat_atlas_service_atlas_obj_private_only_total_->addData(0u);
        }
    }
    {
        std::map<std::string, uint64_t> object_plane_stats;
        if (pod_metadata_object_plane_) {
            pod_metadata_object_plane_->exportStatsToMap(
                object_plane_stats,
                "atlas_pod_metadata_");
        } else {
            PodMetadataObjectPlane disabled_plane;
            disabled_plane.exportStatsToMap(object_plane_stats, "atlas_pod_metadata_");
        }
        if (pod_owner_service_table_) {
            pod_owner_service_table_->exportStatsToMap(
                object_plane_stats,
                "atlas_pod_owner_");
        } else {
            PodOwnerServiceTable disabled_table;
            disabled_table.exportStatsToMap(object_plane_stats, "atlas_pod_owner_");
        }
        for (const auto& kv : object_plane_stats) {
            auto it = atlas_object_plane_stats_.find(kv.first);
            if (it == atlas_object_plane_stats_.end()) continue;
            if (!it->second) continue;
            it->second->addData(kv.second);
        }
    }
    // 报告总仿真周期（单实例）
    if (stat_sim_cycles_total_) stat_sim_cycles_total_->addData(current_cycle_);

    // Experiment observability: if global step sync is enabled but we finish mid-step,
    // record it (do not fatal; matrix scripts may mark INCONCLUSIVE).
    if (global_step_sync_enable_ && global_step_active_seq_ != 0 && !global_step_done_sent_) {
        if (stat_compat_finish_incomplete_total_) stat_compat_finish_incomplete_total_->addData(1);
    }

    // Global Step barrier：若仿真结束时本 PE 尚未完成 active step，输出每核卡点快照（仅 debug/sentinel 模式）
    if (global_step_sync_enable_ && sentinel_enabled_ && output_ &&
        global_step_active_seq_ != 0 && !global_step_done_sent_) {
        size_t done_cnt = 0;
        for (auto v : global_step_done_cores_) if (v) ++done_cnt;
        output_->verbose(CALL_INFO, 2, 0,
            "[[sentinel-step-sync]] node=%d finish_incomplete active_seq=%u done=%zu/%d\n",
            node_id_, global_step_active_seq_, done_cnt, num_cores_);
        for (int i = 0; i < num_cores_; ++i) {
            const bool done = (i >= 0 &&
                               static_cast<size_t>(i) < global_step_done_cores_.size() &&
                               global_step_done_cores_[static_cast<size_t>(i)] != 0);
            if (done) continue;
            const size_t idx = static_cast<size_t>(i);
            const uint8_t code =
                (idx < global_step_last_stage_code_.size()) ? global_step_last_stage_code_[idx] : 0;
            const uint32_t seq =
                (idx < global_step_last_stage_seq_.size()) ? global_step_last_stage_seq_[idx] : 0;
            const uint64_t ts =
                (idx < global_step_last_stage_ts_ns_.size()) ? global_step_last_stage_ts_ns_[idx] : 0;
            const uint64_t spikes =
                (idx < global_step_last_stage_spikes_.size()) ? global_step_last_stage_spikes_[idx] : 0;
            output_->verbose(CALL_INFO, 2, 0,
                "[[sentinel-step-sync]] node=%d finish_core core=%d last=%s seq=%u ts_ns=%" PRIu64 " spikes=%" PRIu64 "\n",
                node_id_, i, stepStageCodeName_(code), seq, (uint64_t)ts, (uint64_t)spikes);
        }
    }
    auto resolve_out_dir = [this]() -> std::string {
        std::string ref = stage_events_csv_path_;
        if (ref.empty()) ref = stats_csv_path_;
        if (!ref.empty()) {
            auto pos = ref.find_last_of('/');
            return (pos == std::string::npos) ? std::string(".") : ref.substr(0, pos);
        }
        // No explicit output path: avoid multi-node overwrite by defaulting to per-node dir in CWD.
        std::string dir = defaultPeOutDir_(node_id_);
        if (!ensureDirExists_(dir)) return std::string(".");
        return dir;
    };

    // 输出 PE 级 per-window 发放聚合（与 stage_events 同目录）
    if (!window_spikes_pe_.empty()) {
        std::string dir = resolve_out_dir();
        // 文件名必须保持稳定：上游分析脚本默认查找 pe*/pe_window_spikes_db.csv
        std::string path = dir + "/pe_window_spikes_db.csv";
        std::ofstream fout(path);
        if (fout.good()) {
            fout << "seq,pe_spikes_emitted\n";
            std::vector<std::pair<uint32_t,uint64_t>> rows(window_spikes_pe_.begin(), window_spikes_pe_.end());
            std::sort(rows.begin(), rows.end(), [](auto&a, auto&b){return a.first<b.first;});
            for (auto &kv : rows) fout << kv.first << "," << kv.second << "\n";
            fout.close();
        }
    }
    // 输出 PE 级阶段事件CSV（与 pe_window_spikes_db.csv 同目录）
    if (!stage_marks_.empty()) {
        std::string dir = resolve_out_dir();
        // 文件名必须保持稳定：上游分析脚本默认查找 pe*/pe_stage_events_db.csv
        std::string pathA = dir + "/pe_stage_events_db.csv";
        std::ofstream fout(pathA);
        if (fout.good()) {
            fout << "seq,bg_ns,ga_ns,ea_ns,bs_ns,es_ns,gather_ns,apply_ns,scatter_ns,total_ns\n";
            std::vector<uint32_t> keys; keys.reserve(stage_marks_.size());
            for (auto &kv : stage_marks_) keys.push_back(kv.first);
            std::sort(keys.begin(), keys.end());
            for (auto seq : keys) {
                auto &m = stage_marks_[seq];
                uint64_t g=0,a=0,s=0,t=0;
                if (m.bg && m.ga && m.ga>=m.bg) g = m.ga - m.bg;
                if (m.ga && m.bs && m.bs>=m.ga) a = m.bs - m.ga;
                if (m.bs && m.es && m.es>=m.bs) s = m.es - m.bs;
                if (m.bg && m.es && m.es>=m.bg) t = m.es - m.bg;
                fout << seq << "," << m.bg << "," << m.ga << "," << m.ea << "," << m.bs << "," << m.es
                     << "," << g << "," << a << "," << s << "," << t << "\n";
            }
            fout.close();
        }
        // 兼容原 compute 工具：另写一份 stage_events_db_<sim>.csv，包含 spikes_emitted 列
        // 由于本组件无法直接得知仿真时长字符串，这里统一使用固定文件名，供上层脚本选择最新文件回退读取。
        std::string pathB = dir + "/stage_events_db.csv";
        std::ofstream fout2(pathB);
        if (fout2.good()) {
            fout2 << "seq,event,sim_time_ns,spikes_emitted\n";
            std::vector<uint32_t> keys; keys.reserve(stage_marks_.size());
            for (auto &kv : stage_marks_) keys.push_back(kv.first);
            std::sort(keys.begin(), keys.end());
            for (auto seq : keys) {
                auto &m = stage_marks_[seq];
                if (m.bg) fout2 << seq << ",BeginGather," << m.bg << ",0\n";
                if (m.ga) fout2 << seq << ",BeginApply," << m.ga << ",0\n";
                if (m.bs) fout2 << seq << ",BeginScatter," << m.bs << ",0\n";
                if (m.es) {
                    uint64_t spikes = 0;
                    auto it = window_spikes_pe_.find(seq);
                    if (it != window_spikes_pe_.end()) spikes = it->second;
                    fout2 << seq << ",EndScatter," << m.es << "," << spikes << "\n";
                }
            }
            fout2.close();
        }
    }
    if (!core_stage_marks_.empty()) {
        std::string dir = resolve_out_dir();
        std::string pathCoreStage = dir + "/core_stage_events_db.csv";
        std::ofstream fout(pathCoreStage);
        if (fout.good()) {
            fout << "core,seq,bg_ns,ga_ns,ea_ns,bs_ns,es_ns,gather_ns,apply_ns,scatter_ns,total_ns\n";
            std::vector<CoreStepKey> keys;
            keys.reserve(core_stage_marks_.size());
            for (const auto& kv : core_stage_marks_) keys.push_back(kv.first);
            std::sort(keys.begin(), keys.end(),
                      [](const CoreStepKey& a, const CoreStepKey& b) {
                          if (a.core != b.core) return a.core < b.core;
                          return a.seq < b.seq;
                      });
            for (const auto& key : keys) {
                const auto& m = core_stage_marks_[key];
                uint64_t g = 0;
                uint64_t a = 0;
                uint64_t s = 0;
                uint64_t t = 0;
                if (m.bg && m.ga && m.ga >= m.bg) g = m.ga - m.bg;
                if (m.ga && m.bs && m.bs >= m.ga) a = m.bs - m.ga;
                if (m.bs && m.es && m.es >= m.bs) s = m.es - m.bs;
                if (m.bg && m.es && m.es >= m.bg) t = m.es - m.bg;
                fout << key.core << "," << key.seq << "," << m.bg << "," << m.ga << "," << m.ea << "," << m.bs << "," << m.es
                     << "," << g << "," << a << "," << s << "," << t << "\n";
            }
            fout.close();
        }
    }
    if (!step_perf_.empty()) {
        std::string dir = resolve_out_dir();
        std::string pathC = dir + "/pe_step_perf_db.csv";
        std::ofstream fout3(pathC);
        if (fout3.good()) {
            fout3 << "seq,seed_pre_selected,seed_spike_attempts,seed_spikes_injected,seed_route_hits,seed_route_misses,seed_local_drops,"
                  << "rx_packets_total,rx_spike_packets_total,rx_spikekey_packets_total,rx_spiketilekey_packets_total,rx_local_packets_total,rx_remote_packets_total,"
                  << "rx_packets_before_bg_total,rx_local_packets_before_bg_total,rx_remote_packets_before_bg_total,"
                  << "rx_packets_during_gather_total,rx_packets_during_apply_total,rx_packets_during_scatter_total,rx_gate_pending_peak,"
                  << "rx_gate_accept_total,rx_gate_reject_refractory_total,rx_gate_direct_accept_total,rx_gate_direct_reject_refractory_total,"
                  << "rx_gate_fastpath_accept_total,rx_gate_fastpath_reject_refractory_total,"
                  << "acc_updates,posts_touched,spill_records,spilled_bytes,hwm_bytes_max,scatter_spikes_emitted,"
                  << "unique_reads,unique_bytes,rowwin_triggers,rowwin_bytes,bursts,payload_bytes,window_inflight_peak,window_buffer_max_bytes,gap_absorbed_bytes,"
                  << "frontend_staged_reads,frontend_staged_line_touches,frontend_granules_built,unique_line_count,covered_line_count,overfetch_bytes,apply_bank_credit_effective,cmd_cost_veto,cmd_cost_veto_fine_gap,cmd_cost_veto_row_window,"
                  << "apply_issue_attempt_total,apply_issue_success_total,apply_issue_block_no_ready_total,apply_issue_block_inflight_cap_total,"
                  << "apply_issue_block_bank_credit_total,apply_issue_block_downstream_busy_total,"
                  << "apply_issue_block_retire_guard_total,apply_ready_queue_peak,apply_ready_queue_nonempty_cycles_total,"
                  << "apply_first_issue_delay_ns,apply_first_down_resp_delay_ns,apply_first_granule_done_delay_ns,apply_first_up_resp_delay_ns,"
                  << "apply_down_resp_total,apply_completed_granules_total,apply_emitted_subreads_total,"
                  << "apply_backlog_granules_residual,apply_backlog_pending_up_reads_residual,apply_backlog_inflight_residual,"
                  << "apply_backlog_granules_peak_after_due,apply_backlog_pending_up_reads_peak_after_due,apply_backlog_inflight_peak_after_due,"
                  << "retire_global_hol_cycles_total,retire_ready_but_blocked_edges_total,retire_per_post_progress_total,"
                  << "retire_wait_cycles_total,retire_wait_cycles_due_to_hol_total,retire_wait_cycles_due_to_barrier_total,"
                  << "retire_samepost_blocked_edges_total,retire_crosspost_blocked_edges_total,"
                  << "retire_policy_loss_cycles_total,retire_policy_loss_edges_total,"
                  << "retire_shadow_per_post_recoverable_cycles_total,retire_shadow_per_post_recoverable_edges_total,"
                  << "retire_shadow_per_post_ready_posts_peak,retire_shadow_per_post_committable_edges_peak,"
                  << "retire_head_hol_cycles_dense_total,retire_head_hol_cycles_cache_total,retire_head_hol_cycles_miss_total,"
                  << "retire_head_hol_cycles_bcsr_total,retire_head_hol_cycles_bcsr_file_total,retire_head_hol_cycles_gcss_total,"
                  << "retire_head_blocked_edges_dense_total,retire_head_blocked_edges_cache_total,retire_head_blocked_edges_miss_total,"
                  << "retire_head_blocked_edges_bcsr_total,retire_head_blocked_edges_bcsr_file_total,retire_head_blocked_edges_gcss_total,"
                  << "retire_gcss_head_queued_not_issued_cycles_total,retire_gcss_qni_head_wait_episodes_total,retire_gcss_qni_head_wait_cycles_max,retire_gcss_head_queued_not_issued_blocked_edges_total,"
                  << "retire_gcss_head_issued_wait_resp_cycles_total,retire_gcss_head_issued_wait_resp_blocked_edges_total,"
                  << "retire_gcss_resp_ready_but_hol_cycles_total,retire_gcss_resp_ready_but_hol_blocked_edges_total,"
                  << "retire_gcss_qni_loader_not_ready_cycles_total,retire_gcss_qni_loader_not_ready_blocked_edges_total,"
                  << "retire_gcss_qni_weight_sram_stall_cycles_total,retire_gcss_qni_weight_sram_stall_blocked_edges_total,"
                  << "retire_gcss_qni_vlf_younger_ahead_cycles_total,retire_gcss_qni_vlf_younger_ahead_blocked_edges_total,"
                  << "retire_gcss_qni_vlf_younger_ahead_depth_total,retire_gcss_qni_vlf_younger_ahead_depth_samples_total,retire_gcss_qni_vlf_younger_ahead_depth_max,"
                  << "retire_gcss_qni_issue_deferred_total,"
                  << "retire_gcss_qni_pending_direct_queue_residency_cycles_total,retire_gcss_qni_pending_direct_queue_residency_samples_total,retire_gcss_qni_pending_direct_queue_residency_cycles_max,"
                  << "retire_gcss_qni_vlf_front_inflight_full_cycles_total,retire_gcss_qni_vlf_front_inflight_full_blocked_edges_total,"
                  << "retire_gcss_qni_vlf_front_waiting_issue_cycles_total,retire_gcss_qni_vlf_front_waiting_issue_blocked_edges_total,"
                  << "retire_gcss_qni_pending_younger_ahead_cycles_total,retire_gcss_qni_pending_younger_ahead_blocked_edges_total,"
                  << "retire_gcss_qni_pending_front_inflight_full_cycles_total,retire_gcss_qni_pending_front_inflight_full_blocked_edges_total,"
                  << "retire_gcss_qni_pending_front_waiting_tick_cycles_total,retire_gcss_qni_pending_front_waiting_tick_blocked_edges_total,"
                  << "retire_gcss_qni_unknown_cycles_total,retire_gcss_qni_unknown_blocked_edges_total,"
                  << "retire_begin_apply_windows_total,retire_begin_apply_prev_edges_total,"
                  << "retire_begin_apply_outstanding_carryin_total,retire_begin_apply_outstanding_carryin_windows_total,"
                  << "retire_begin_apply_loader_not_ready_windows_total,"
                  << "retire_edge_retire_registered_total,retire_edge_retire_retired_total,"
                  << "retire_end_scatter_gcss_vlf_issue_queue_residual_total,retire_end_scatter_pending_direct_reads_residual_total,"
                  << "retire_end_scatter_outstanding_residual_total,retire_end_scatter_residual_work_windows_total,"
                  << "retire_gcss_vlf_issue_prepare_total,retire_gcss_vlf_issue_edges_total,"
                  << "retire_gcss_vlf_issue_reorder_trigger_total,retire_gcss_vlf_issue_line_groups_total,"
                  << "retire_wait_cycles_due_to_not_ready_total,retire_ready_queue_peak,retire_unblock_events_total,step_barrier_wait_ns\n";
            std::vector<uint32_t> keys; keys.reserve(step_perf_.size());
            for (auto &kv : step_perf_) keys.push_back(kv.first);
            std::sort(keys.begin(), keys.end());
            for (auto seq : keys) {
                const auto& p = step_perf_[seq];
                fout3 << seq
                      << "," << p.seed_pre_selected
                      << "," << p.seed_spike_attempts
                      << "," << p.seed_spikes_injected
                      << "," << p.seed_route_hits
                      << "," << p.seed_route_misses
                      << "," << p.seed_local_drops
                      << "," << p.rx_packets_total
                      << "," << p.rx_spike_packets_total
                      << "," << p.rx_spikekey_packets_total
                      << "," << p.rx_spiketilekey_packets_total
                      << "," << p.rx_local_packets_total
                      << "," << p.rx_remote_packets_total
                      << "," << p.rx_packets_before_bg_total
                      << "," << p.rx_local_packets_before_bg_total
                      << "," << p.rx_remote_packets_before_bg_total
                      << "," << p.rx_packets_during_gather_total
                      << "," << p.rx_packets_during_apply_total
                      << "," << p.rx_packets_during_scatter_total
                      << "," << p.rx_gate_pending_peak
                      << "," << p.rx_gate_accept_total
                      << "," << p.rx_gate_reject_refractory_total
                      << "," << p.rx_gate_direct_accept_total
                      << "," << p.rx_gate_direct_reject_refractory_total
                      << "," << p.rx_gate_fastpath_accept_total
                      << "," << p.rx_gate_fastpath_reject_refractory_total
                      << "," << p.acc_updates
                      << "," << p.posts_touched
                      << "," << p.spill_records
                      << "," << p.spilled_bytes
                      << "," << p.hwm_bytes_max
                      << "," << p.scatter_spikes_emitted
                      << "," << p.unique_reads
                      << "," << p.unique_bytes
                      << "," << p.rowwin_triggers
                      << "," << p.rowwin_bytes
                      << "," << p.bursts
                      << "," << p.payload_bytes
                      << "," << p.window_inflight_peak
                      << "," << p.window_buffer_max_bytes
                      << "," << p.gap_absorbed_bytes
                      << "," << p.frontend_staged_reads
                      << "," << p.frontend_staged_line_touches
                      << "," << p.frontend_granules_built
                      << "," << p.unique_line_count
                      << "," << p.covered_line_count
                      << "," << p.overfetch_bytes
                      << "," << p.apply_bank_credit_effective
                      << "," << p.cmd_cost_veto
                      << "," << p.cmd_cost_veto_fine_gap
                      << "," << p.cmd_cost_veto_row_window
                      << "," << p.apply_issue_attempt_total
                      << "," << p.apply_issue_success_total
                      << "," << p.apply_issue_block_no_ready_total
                      << "," << p.apply_issue_block_inflight_cap_total
                      << "," << p.apply_issue_block_bank_credit_total
                      << "," << p.apply_issue_block_downstream_busy_total
                      << "," << p.apply_issue_block_retire_guard_total
                      << "," << p.apply_ready_queue_peak
                      << "," << p.apply_ready_queue_nonempty_cycles_total
                      << "," << p.apply_first_issue_delay_ns
                      << "," << p.apply_first_down_resp_delay_ns
                      << "," << p.apply_first_granule_done_delay_ns
                      << "," << p.apply_first_up_resp_delay_ns
                      << "," << p.apply_down_resp_total
                      << "," << p.apply_completed_granules_total
                      << "," << p.apply_emitted_subreads_total
                      << "," << p.apply_backlog_granules_residual
                      << "," << p.apply_backlog_pending_up_reads_residual
                      << "," << p.apply_backlog_inflight_residual
                      << "," << p.apply_backlog_granules_peak_after_due
                      << "," << p.apply_backlog_pending_up_reads_peak_after_due
                      << "," << p.apply_backlog_inflight_peak_after_due
                      << "," << p.retire_global_hol_cycles_total
                      << "," << p.retire_ready_but_blocked_edges_total
                      << "," << p.retire_per_post_progress_total
                      << "," << p.retire_wait_cycles_total
                      << "," << p.retire_wait_cycles_due_to_hol_total
                      << "," << p.retire_wait_cycles_due_to_barrier_total
                      << "," << p.retire_samepost_blocked_edges_total
                      << "," << p.retire_crosspost_blocked_edges_total
                      << "," << p.retire_policy_loss_cycles_total
                      << "," << p.retire_policy_loss_edges_total
                      << "," << p.retire_shadow_per_post_recoverable_cycles_total
                      << "," << p.retire_shadow_per_post_recoverable_edges_total
                      << "," << p.retire_shadow_per_post_ready_posts_peak
                      << "," << p.retire_shadow_per_post_committable_edges_peak
                      << "," << p.retire_head_hol_cycles_dense_total
                      << "," << p.retire_head_hol_cycles_cache_total
                      << "," << p.retire_head_hol_cycles_miss_total
                      << "," << p.retire_head_hol_cycles_bcsr_total
                      << "," << p.retire_head_hol_cycles_bcsr_file_total
                      << "," << p.retire_head_hol_cycles_gcss_total
                      << "," << p.retire_head_blocked_edges_dense_total
                      << "," << p.retire_head_blocked_edges_cache_total
                      << "," << p.retire_head_blocked_edges_miss_total
                      << "," << p.retire_head_blocked_edges_bcsr_total
                      << "," << p.retire_head_blocked_edges_bcsr_file_total
                      << "," << p.retire_head_blocked_edges_gcss_total
                      << "," << p.retire_gcss_head_queued_not_issued_cycles_total
                      << "," << p.retire_gcss_qni_head_wait_episodes_total
                      << "," << p.retire_gcss_qni_head_wait_cycles_max
                      << "," << p.retire_gcss_head_queued_not_issued_blocked_edges_total
                      << "," << p.retire_gcss_head_issued_wait_resp_cycles_total
                      << "," << p.retire_gcss_head_issued_wait_resp_blocked_edges_total
                      << "," << p.retire_gcss_resp_ready_but_hol_cycles_total
                      << "," << p.retire_gcss_resp_ready_but_hol_blocked_edges_total
                      << "," << p.retire_gcss_qni_loader_not_ready_cycles_total
                      << "," << p.retire_gcss_qni_loader_not_ready_blocked_edges_total
                      << "," << p.retire_gcss_qni_weight_sram_stall_cycles_total
                      << "," << p.retire_gcss_qni_weight_sram_stall_blocked_edges_total
                      << "," << p.retire_gcss_qni_vlf_younger_ahead_cycles_total
                      << "," << p.retire_gcss_qni_vlf_younger_ahead_blocked_edges_total
                      << "," << p.retire_gcss_qni_vlf_younger_ahead_depth_total
                      << "," << p.retire_gcss_qni_vlf_younger_ahead_depth_samples_total
                      << "," << p.retire_gcss_qni_vlf_younger_ahead_depth_max
                      << "," << p.retire_gcss_qni_issue_deferred_total
                      << "," << p.retire_gcss_qni_pending_direct_queue_residency_cycles_total
                      << "," << p.retire_gcss_qni_pending_direct_queue_residency_samples_total
                      << "," << p.retire_gcss_qni_pending_direct_queue_residency_cycles_max
                      << "," << p.retire_gcss_qni_vlf_front_inflight_full_cycles_total
                      << "," << p.retire_gcss_qni_vlf_front_inflight_full_blocked_edges_total
                      << "," << p.retire_gcss_qni_vlf_front_waiting_issue_cycles_total
                      << "," << p.retire_gcss_qni_vlf_front_waiting_issue_blocked_edges_total
                      << "," << p.retire_gcss_qni_pending_younger_ahead_cycles_total
                      << "," << p.retire_gcss_qni_pending_younger_ahead_blocked_edges_total
                      << "," << p.retire_gcss_qni_pending_front_inflight_full_cycles_total
                      << "," << p.retire_gcss_qni_pending_front_inflight_full_blocked_edges_total
                      << "," << p.retire_gcss_qni_pending_front_waiting_tick_cycles_total
                      << "," << p.retire_gcss_qni_pending_front_waiting_tick_blocked_edges_total
                      << "," << p.retire_gcss_qni_unknown_cycles_total
                      << "," << p.retire_gcss_qni_unknown_blocked_edges_total
                      << "," << p.retire_begin_apply_windows_total
                      << "," << p.retire_begin_apply_prev_edges_total
                      << "," << p.retire_begin_apply_outstanding_carryin_total
                      << "," << p.retire_begin_apply_outstanding_carryin_windows_total
                      << "," << p.retire_begin_apply_loader_not_ready_windows_total
                      << "," << p.retire_edge_retire_registered_total
                      << "," << p.retire_edge_retire_retired_total
                      << "," << p.retire_end_scatter_gcss_vlf_issue_queue_residual_total
                      << "," << p.retire_end_scatter_pending_direct_reads_residual_total
                      << "," << p.retire_end_scatter_outstanding_residual_total
                      << "," << p.retire_end_scatter_residual_work_windows_total
                      << "," << p.retire_gcss_vlf_issue_prepare_total
                      << "," << p.retire_gcss_vlf_issue_edges_total
                      << "," << p.retire_gcss_vlf_issue_reorder_trigger_total
                      << "," << p.retire_gcss_vlf_issue_line_groups_total
                      << "," << p.retire_wait_cycles_due_to_not_ready_total
                      << "," << p.retire_ready_queue_peak
                      << "," << p.retire_unblock_events_total
                      << "," << p.step_barrier_wait_ns
                      << "\n";
            }
            fout3.close();
        }
    }
    if (!core_step_perf_.empty()) {
        std::string dir = resolve_out_dir();
        std::string pathCorePerf = dir + "/core_step_perf_db.csv";
        std::ofstream fout4(pathCorePerf);
        if (fout4.good()) {
            fout4 << "core,seq,seed_pre_selected,seed_spike_attempts,seed_spikes_injected,seed_route_hits,seed_route_misses,seed_local_drops,"
                  << "rx_packets_total,rx_spike_packets_total,rx_spikekey_packets_total,rx_spiketilekey_packets_total,rx_local_packets_total,rx_remote_packets_total,"
                  << "rx_packets_before_bg_total,rx_local_packets_before_bg_total,rx_remote_packets_before_bg_total,"
                  << "rx_packets_during_gather_total,rx_packets_during_apply_total,rx_packets_during_scatter_total,rx_gate_pending_peak,"
                  << "rx_gate_accept_total,rx_gate_reject_refractory_total,rx_gate_direct_accept_total,rx_gate_direct_reject_refractory_total,"
                  << "rx_gate_fastpath_accept_total,rx_gate_fastpath_reject_refractory_total,"
                  << "acc_updates,posts_touched,spill_records,spilled_bytes,hwm_bytes_max,scatter_spikes_emitted,"
                  << "unique_reads,unique_bytes,rowwin_triggers,rowwin_bytes,bursts,payload_bytes,window_inflight_peak,window_buffer_max_bytes,gap_absorbed_bytes,"
                  << "frontend_staged_reads,frontend_staged_line_touches,frontend_granules_built,unique_line_count,covered_line_count,overfetch_bytes,apply_bank_credit_effective,cmd_cost_veto,cmd_cost_veto_fine_gap,cmd_cost_veto_row_window,"
                  << "apply_issue_attempt_total,apply_issue_success_total,apply_issue_block_no_ready_total,apply_issue_block_inflight_cap_total,"
                  << "apply_issue_block_bank_credit_total,apply_issue_block_downstream_busy_total,"
                  << "apply_issue_block_retire_guard_total,apply_ready_queue_peak,apply_ready_queue_nonempty_cycles_total,"
                  << "apply_first_issue_delay_ns,apply_first_down_resp_delay_ns,apply_first_granule_done_delay_ns,apply_first_up_resp_delay_ns,"
                  << "apply_down_resp_total,apply_completed_granules_total,apply_emitted_subreads_total,"
                  << "apply_backlog_granules_residual,apply_backlog_pending_up_reads_residual,apply_backlog_inflight_residual,"
                  << "apply_backlog_granules_peak_after_due,apply_backlog_pending_up_reads_peak_after_due,apply_backlog_inflight_peak_after_due,"
                  << "retire_global_hol_cycles_total,retire_ready_but_blocked_edges_total,retire_per_post_progress_total,"
                  << "retire_wait_cycles_total,retire_wait_cycles_due_to_hol_total,retire_wait_cycles_due_to_barrier_total,"
                  << "retire_samepost_blocked_edges_total,retire_crosspost_blocked_edges_total,"
                  << "retire_policy_loss_cycles_total,retire_policy_loss_edges_total,"
                  << "retire_shadow_per_post_recoverable_cycles_total,retire_shadow_per_post_recoverable_edges_total,"
                  << "retire_shadow_per_post_ready_posts_peak,retire_shadow_per_post_committable_edges_peak,"
                  << "retire_head_hol_cycles_dense_total,retire_head_hol_cycles_cache_total,retire_head_hol_cycles_miss_total,"
                  << "retire_head_hol_cycles_bcsr_total,retire_head_hol_cycles_bcsr_file_total,retire_head_hol_cycles_gcss_total,"
                  << "retire_head_blocked_edges_dense_total,retire_head_blocked_edges_cache_total,retire_head_blocked_edges_miss_total,"
                  << "retire_head_blocked_edges_bcsr_total,retire_head_blocked_edges_bcsr_file_total,retire_head_blocked_edges_gcss_total,"
                  << "retire_gcss_head_queued_not_issued_cycles_total,retire_gcss_qni_head_wait_episodes_total,retire_gcss_qni_head_wait_cycles_max,retire_gcss_head_queued_not_issued_blocked_edges_total,"
                  << "retire_gcss_head_issued_wait_resp_cycles_total,retire_gcss_head_issued_wait_resp_blocked_edges_total,"
                  << "retire_gcss_resp_ready_but_hol_cycles_total,retire_gcss_resp_ready_but_hol_blocked_edges_total,"
                  << "retire_gcss_qni_loader_not_ready_cycles_total,retire_gcss_qni_loader_not_ready_blocked_edges_total,"
                  << "retire_gcss_qni_weight_sram_stall_cycles_total,retire_gcss_qni_weight_sram_stall_blocked_edges_total,"
                  << "retire_gcss_qni_vlf_younger_ahead_cycles_total,retire_gcss_qni_vlf_younger_ahead_blocked_edges_total,"
                  << "retire_gcss_qni_vlf_younger_ahead_depth_total,retire_gcss_qni_vlf_younger_ahead_depth_samples_total,retire_gcss_qni_vlf_younger_ahead_depth_max,"
                  << "retire_gcss_qni_issue_deferred_total,"
                  << "retire_gcss_qni_pending_direct_queue_residency_cycles_total,retire_gcss_qni_pending_direct_queue_residency_samples_total,retire_gcss_qni_pending_direct_queue_residency_cycles_max,"
                  << "retire_gcss_qni_vlf_front_inflight_full_cycles_total,retire_gcss_qni_vlf_front_inflight_full_blocked_edges_total,"
                  << "retire_gcss_qni_vlf_front_waiting_issue_cycles_total,retire_gcss_qni_vlf_front_waiting_issue_blocked_edges_total,"
                  << "retire_gcss_qni_pending_younger_ahead_cycles_total,retire_gcss_qni_pending_younger_ahead_blocked_edges_total,"
                  << "retire_gcss_qni_pending_front_inflight_full_cycles_total,retire_gcss_qni_pending_front_inflight_full_blocked_edges_total,"
                  << "retire_gcss_qni_pending_front_waiting_tick_cycles_total,retire_gcss_qni_pending_front_waiting_tick_blocked_edges_total,"
                  << "retire_gcss_qni_unknown_cycles_total,retire_gcss_qni_unknown_blocked_edges_total,"
                  << "retire_begin_apply_windows_total,retire_begin_apply_prev_edges_total,"
                  << "retire_begin_apply_outstanding_carryin_total,retire_begin_apply_outstanding_carryin_windows_total,"
                  << "retire_begin_apply_loader_not_ready_windows_total,"
                  << "retire_edge_retire_registered_total,retire_edge_retire_retired_total,"
                  << "retire_end_scatter_gcss_vlf_issue_queue_residual_total,retire_end_scatter_pending_direct_reads_residual_total,"
                  << "retire_end_scatter_outstanding_residual_total,retire_end_scatter_residual_work_windows_total,"
                  << "retire_gcss_vlf_issue_prepare_total,retire_gcss_vlf_issue_edges_total,"
                  << "retire_gcss_vlf_issue_reorder_trigger_total,retire_gcss_vlf_issue_line_groups_total,"
                  << "retire_wait_cycles_due_to_not_ready_total,retire_ready_queue_peak,retire_unblock_events_total,step_barrier_wait_ns\n";
            std::vector<CoreStepKey> keys;
            keys.reserve(core_step_perf_.size());
            for (const auto& kv : core_step_perf_) keys.push_back(kv.first);
            std::sort(keys.begin(), keys.end(),
                      [](const CoreStepKey& a, const CoreStepKey& b) {
                          if (a.core != b.core) return a.core < b.core;
                          return a.seq < b.seq;
                      });
            for (const auto& key : keys) {
                const auto& p = core_step_perf_[key];
                fout4 << key.core
                      << "," << key.seq
                      << "," << p.seed_pre_selected
                      << "," << p.seed_spike_attempts
                      << "," << p.seed_spikes_injected
                      << "," << p.seed_route_hits
                      << "," << p.seed_route_misses
                      << "," << p.seed_local_drops
                      << "," << p.rx_packets_total
                      << "," << p.rx_spike_packets_total
                      << "," << p.rx_spikekey_packets_total
                      << "," << p.rx_spiketilekey_packets_total
                      << "," << p.rx_local_packets_total
                      << "," << p.rx_remote_packets_total
                      << "," << p.rx_packets_before_bg_total
                      << "," << p.rx_local_packets_before_bg_total
                      << "," << p.rx_remote_packets_before_bg_total
                      << "," << p.rx_packets_during_gather_total
                      << "," << p.rx_packets_during_apply_total
                      << "," << p.rx_packets_during_scatter_total
                      << "," << p.rx_gate_pending_peak
                      << "," << p.rx_gate_accept_total
                      << "," << p.rx_gate_reject_refractory_total
                      << "," << p.rx_gate_direct_accept_total
                      << "," << p.rx_gate_direct_reject_refractory_total
                      << "," << p.rx_gate_fastpath_accept_total
                      << "," << p.rx_gate_fastpath_reject_refractory_total
                      << "," << p.acc_updates
                      << "," << p.posts_touched
                      << "," << p.spill_records
                      << "," << p.spilled_bytes
                      << "," << p.hwm_bytes_max
                      << "," << p.scatter_spikes_emitted
                      << "," << p.unique_reads
                      << "," << p.unique_bytes
                      << "," << p.rowwin_triggers
                      << "," << p.rowwin_bytes
                      << "," << p.bursts
                      << "," << p.payload_bytes
                      << "," << p.window_inflight_peak
                      << "," << p.window_buffer_max_bytes
                      << "," << p.gap_absorbed_bytes
                      << "," << p.frontend_staged_reads
                      << "," << p.frontend_staged_line_touches
                      << "," << p.frontend_granules_built
                      << "," << p.unique_line_count
                      << "," << p.covered_line_count
                      << "," << p.overfetch_bytes
                      << "," << p.apply_bank_credit_effective
                      << "," << p.cmd_cost_veto
                      << "," << p.cmd_cost_veto_fine_gap
                      << "," << p.cmd_cost_veto_row_window
                      << "," << p.apply_issue_attempt_total
                      << "," << p.apply_issue_success_total
                      << "," << p.apply_issue_block_no_ready_total
                      << "," << p.apply_issue_block_inflight_cap_total
                      << "," << p.apply_issue_block_bank_credit_total
                      << "," << p.apply_issue_block_downstream_busy_total
                      << "," << p.apply_issue_block_retire_guard_total
                      << "," << p.apply_ready_queue_peak
                      << "," << p.apply_ready_queue_nonempty_cycles_total
                      << "," << p.apply_first_issue_delay_ns
                      << "," << p.apply_first_down_resp_delay_ns
                      << "," << p.apply_first_granule_done_delay_ns
                      << "," << p.apply_first_up_resp_delay_ns
                      << "," << p.apply_down_resp_total
                      << "," << p.apply_completed_granules_total
                      << "," << p.apply_emitted_subreads_total
                      << "," << p.apply_backlog_granules_residual
                      << "," << p.apply_backlog_pending_up_reads_residual
                      << "," << p.apply_backlog_inflight_residual
                      << "," << p.apply_backlog_granules_peak_after_due
                      << "," << p.apply_backlog_pending_up_reads_peak_after_due
                      << "," << p.apply_backlog_inflight_peak_after_due
                      << "," << p.retire_global_hol_cycles_total
                      << "," << p.retire_ready_but_blocked_edges_total
                      << "," << p.retire_per_post_progress_total
                      << "," << p.retire_wait_cycles_total
                      << "," << p.retire_wait_cycles_due_to_hol_total
                      << "," << p.retire_wait_cycles_due_to_barrier_total
                      << "," << p.retire_samepost_blocked_edges_total
                      << "," << p.retire_crosspost_blocked_edges_total
                      << "," << p.retire_policy_loss_cycles_total
                      << "," << p.retire_policy_loss_edges_total
                      << "," << p.retire_shadow_per_post_recoverable_cycles_total
                      << "," << p.retire_shadow_per_post_recoverable_edges_total
                      << "," << p.retire_shadow_per_post_ready_posts_peak
                      << "," << p.retire_shadow_per_post_committable_edges_peak
                      << "," << p.retire_head_hol_cycles_dense_total
                      << "," << p.retire_head_hol_cycles_cache_total
                      << "," << p.retire_head_hol_cycles_miss_total
                      << "," << p.retire_head_hol_cycles_bcsr_total
                      << "," << p.retire_head_hol_cycles_bcsr_file_total
                      << "," << p.retire_head_hol_cycles_gcss_total
                      << "," << p.retire_head_blocked_edges_dense_total
                      << "," << p.retire_head_blocked_edges_cache_total
                      << "," << p.retire_head_blocked_edges_miss_total
                      << "," << p.retire_head_blocked_edges_bcsr_total
                      << "," << p.retire_head_blocked_edges_bcsr_file_total
                      << "," << p.retire_head_blocked_edges_gcss_total
                      << "," << p.retire_gcss_head_queued_not_issued_cycles_total
                      << "," << p.retire_gcss_qni_head_wait_episodes_total
                      << "," << p.retire_gcss_qni_head_wait_cycles_max
                      << "," << p.retire_gcss_head_queued_not_issued_blocked_edges_total
                      << "," << p.retire_gcss_head_issued_wait_resp_cycles_total
                      << "," << p.retire_gcss_head_issued_wait_resp_blocked_edges_total
                      << "," << p.retire_gcss_resp_ready_but_hol_cycles_total
                      << "," << p.retire_gcss_resp_ready_but_hol_blocked_edges_total
                      << "," << p.retire_gcss_qni_loader_not_ready_cycles_total
                      << "," << p.retire_gcss_qni_loader_not_ready_blocked_edges_total
                      << "," << p.retire_gcss_qni_weight_sram_stall_cycles_total
                      << "," << p.retire_gcss_qni_weight_sram_stall_blocked_edges_total
                      << "," << p.retire_gcss_qni_vlf_younger_ahead_cycles_total
                      << "," << p.retire_gcss_qni_vlf_younger_ahead_blocked_edges_total
                      << "," << p.retire_gcss_qni_vlf_younger_ahead_depth_total
                      << "," << p.retire_gcss_qni_vlf_younger_ahead_depth_samples_total
                      << "," << p.retire_gcss_qni_vlf_younger_ahead_depth_max
                      << "," << p.retire_gcss_qni_issue_deferred_total
                      << "," << p.retire_gcss_qni_pending_direct_queue_residency_cycles_total
                      << "," << p.retire_gcss_qni_pending_direct_queue_residency_samples_total
                      << "," << p.retire_gcss_qni_pending_direct_queue_residency_cycles_max
                      << "," << p.retire_gcss_qni_vlf_front_inflight_full_cycles_total
                      << "," << p.retire_gcss_qni_vlf_front_inflight_full_blocked_edges_total
                      << "," << p.retire_gcss_qni_vlf_front_waiting_issue_cycles_total
                      << "," << p.retire_gcss_qni_vlf_front_waiting_issue_blocked_edges_total
                      << "," << p.retire_gcss_qni_pending_younger_ahead_cycles_total
                      << "," << p.retire_gcss_qni_pending_younger_ahead_blocked_edges_total
                      << "," << p.retire_gcss_qni_pending_front_inflight_full_cycles_total
                      << "," << p.retire_gcss_qni_pending_front_inflight_full_blocked_edges_total
                      << "," << p.retire_gcss_qni_pending_front_waiting_tick_cycles_total
                      << "," << p.retire_gcss_qni_pending_front_waiting_tick_blocked_edges_total
                      << "," << p.retire_gcss_qni_unknown_cycles_total
                      << "," << p.retire_gcss_qni_unknown_blocked_edges_total
                      << "," << p.retire_begin_apply_windows_total
                      << "," << p.retire_begin_apply_prev_edges_total
                      << "," << p.retire_begin_apply_outstanding_carryin_total
                      << "," << p.retire_begin_apply_outstanding_carryin_windows_total
                      << "," << p.retire_begin_apply_loader_not_ready_windows_total
                      << "," << p.retire_edge_retire_registered_total
                      << "," << p.retire_edge_retire_retired_total
                      << "," << p.retire_end_scatter_gcss_vlf_issue_queue_residual_total
                      << "," << p.retire_end_scatter_pending_direct_reads_residual_total
                      << "," << p.retire_end_scatter_outstanding_residual_total
                      << "," << p.retire_end_scatter_residual_work_windows_total
                      << "," << p.retire_gcss_vlf_issue_prepare_total
                      << "," << p.retire_gcss_vlf_issue_edges_total
                      << "," << p.retire_gcss_vlf_issue_reorder_trigger_total
                      << "," << p.retire_gcss_vlf_issue_line_groups_total
                      << "," << p.retire_wait_cycles_due_to_not_ready_total
                      << "," << p.retire_ready_queue_peak
                      << "," << p.retire_unblock_events_total
                      << "," << p.step_barrier_wait_ns
                      << "\n";
            }
            fout4.close();
        }
    }

    // 节点结果摘要（可选）
    if (print_node_summary_) {
        uint64_t agg_spikes = 0;
        uint64_t agg_fired = 0;
        for (int i = 0; i < num_cores_; i++) {
            agg_spikes += unit_states_[i].spikes_processed;
            agg_fired  += unit_states_[i].neurons_fired;
        }
        PE_LOG(1, "NODE%d: 脉冲=%lu, 激发=%lu\n", node_id_, agg_spikes, agg_fired);
    }
    
    // 转发finish到所有子核心（确保子组件的收尾统计/摘要被打印与收集）
    for (auto* core : cores_) {
        if (core) core->finish();
    }

    // NoC e2e latency summary (cycles): printed once per node for native multicast experiments.
    {
        auto percentile = [](const auto& hist, double q) -> uint64_t {
            if (q <= 0.0) return 0;
            uint64_t total = 0;
            for (uint64_t c : hist) total += c;
            if (total == 0) return 0;
            const uint64_t need = static_cast<uint64_t>(std::ceil(q * static_cast<double>(total)));
            uint64_t acc = 0;
            for (uint64_t i = 0; i < hist.size(); ++i) {
                acc += hist[i];
                if (acc >= need) return i;
            }
            return static_cast<uint64_t>(hist.size() - 1);
        };

        const double spike_avg = (noc_lat_spike_cnt_ > 0) ? (double)noc_lat_spike_sum_ / (double)noc_lat_spike_cnt_ : 0.0;
        const double sk_avg = (noc_lat_spikekey_cnt_ > 0) ? (double)noc_lat_spikekey_sum_ / (double)noc_lat_spikekey_cnt_ : 0.0;
        const uint64_t spike_p50 = percentile(noc_lat_spike_hist_, 0.50);
        const uint64_t spike_p95 = percentile(noc_lat_spike_hist_, 0.95);
        const uint64_t spike_p99 = percentile(noc_lat_spike_hist_, 0.99);
        const uint64_t sk_p50 = percentile(noc_lat_spikekey_hist_, 0.50);
        const uint64_t sk_p95 = percentile(noc_lat_spikekey_hist_, 0.95);
        const uint64_t sk_p99 = percentile(noc_lat_spikekey_hist_, 0.99);
        const uint64_t spike_overflow = (!noc_lat_spike_hist_.empty()) ? noc_lat_spike_hist_.back() : 0;
        const uint64_t sk_overflow = (!noc_lat_spikekey_hist_.empty()) ? noc_lat_spikekey_hist_.back() : 0;

        // Noc end-to-end latency summary is a diagnostic; keep default runs quiet.
        output_->verbose(
            CALL_INFO, 1, 0,
            "[noc-lat] node=%d spike_cnt=%" PRIu64 " spike_lat_sum=%" PRIu64 " spike_lat_max=%" PRIu64
            " spike_avg=%.3f spike_p50=%" PRIu64 " spike_p95=%" PRIu64 " spike_p99=%" PRIu64
            " spikekey_cnt=%" PRIu64 " spikekey_lat_sum=%" PRIu64 " spikekey_lat_max=%" PRIu64
            " spikekey_avg=%.3f spikekey_p50=%" PRIu64 " spikekey_p95=%" PRIu64 " spikekey_p99=%" PRIu64
            " hist_max=%u spike_overflow=%" PRIu64 " spikekey_overflow=%" PRIu64 "\n",
            node_id_,
            noc_lat_spike_cnt_,
            noc_lat_spike_sum_,
            noc_lat_spike_max_,
            spike_avg,
            spike_p50,
            spike_p95,
            spike_p99,
            noc_lat_spikekey_cnt_,
            noc_lat_spikekey_sum_,
            noc_lat_spikekey_max_,
            sk_avg,
            sk_p50,
            sk_p95,
            sk_p99,
            noc_lat_hist_max_,
            spike_overflow,
            sk_overflow);
    }

    if (dma_scheduler_) {
        const auto dma_stats = dma_scheduler_->snapshotStats();
        if (stat_dma_issue_reqs_total_) stat_dma_issue_reqs_total_->addData(dma_stats.issue_reqs_total);
        if (stat_dma_issue_bytes_total_) stat_dma_issue_bytes_total_->addData(dma_stats.issue_bytes_total);
        if (stat_dma_queue_depth_max_p0_) stat_dma_queue_depth_max_p0_->addData(dma_stats.queue_depth_max[0]);
        if (stat_dma_queue_depth_max_p1_) stat_dma_queue_depth_max_p1_->addData(dma_stats.queue_depth_max[1]);
        if (stat_dma_queue_depth_max_p2_) stat_dma_queue_depth_max_p2_->addData(dma_stats.queue_depth_max[2]);
        if (stat_dma_queue_depth_max_p3_) stat_dma_queue_depth_max_p3_->addData(dma_stats.queue_depth_max[3]);
        if (stat_dma_inflight_max_) stat_dma_inflight_max_->addData(dma_stats.inflight_max);
        if (stat_dma_stall_cycles_budget_) stat_dma_stall_cycles_budget_->addData(dma_stats.stall_cycles_budget);
        if (stat_dma_stall_cycles_engine_) stat_dma_stall_cycles_engine_->addData(dma_stats.stall_cycles_engine);
        if (stat_dma_stall_cycles_inflight_) stat_dma_stall_cycles_inflight_->addData(dma_stats.stall_cycles_inflight);
        if (stat_dma_stall_cycles_stage_gate_) stat_dma_stall_cycles_stage_gate_->addData(dma_stats.stall_cycles_stage_gate);
        if (stat_dma_stall_cycles_queue_full_) stat_dma_stall_cycles_queue_full_->addData(dma_stats.stall_cycles_queue_full);
    }
    if (local_storage_controller_) {
        const auto ls_stats = local_storage_controller_->snapshotStats();
        if (stat_ls_objects_registered_total_) {
            stat_ls_objects_registered_total_->addData(static_cast<uint64_t>(ls_stats.objects_registered_total));
        }
        if (stat_ls_objects_enabled_total_) {
            stat_ls_objects_enabled_total_->addData(static_cast<uint64_t>(ls_stats.objects_enabled_total));
        }
        if (stat_ls_capacity_bytes_total_) stat_ls_capacity_bytes_total_->addData(ls_stats.capacity_bytes_total);
        if (stat_ls_queue_slots_total_) stat_ls_queue_slots_total_->addData(ls_stats.queue_slots_total);
    }
    {
        std::map<std::string, uint64_t> atlas_activation_gate_stats;
        appendAtlasActivationGateStats_(atlas_activation_gate_stats);
        for (const auto& kv : atlas_activation_gate_stats) {
            auto it = atlas_object_plane_stats_.find(kv.first);
            if (it == atlas_object_plane_stats_.end() || it->second == nullptr) continue;
            it->second->addData(kv.second);
        }
    }
    {
        std::map<std::string, uint64_t> atlas_shared_weight_census_stats;
        appendAtlasSharedWeightCensusStats_(atlas_shared_weight_census_stats);
        for (const auto& kv : atlas_shared_weight_census_stats) {
            auto it = atlas_object_plane_stats_.find(kv.first);
            if (it == atlas_object_plane_stats_.end() || it->second == nullptr) continue;
            it->second->addData(kv.second);
        }
    }
    {
        std::map<std::string, uint64_t> atlas_control_runtime_class_stats;
        appendAtlasControlRuntimeClassificationStats_(atlas_control_runtime_class_stats);
        for (const auto& kv : atlas_control_runtime_class_stats) {
            auto it = atlas_object_plane_stats_.find(kv.first);
            if (it == atlas_object_plane_stats_.end() || it->second == nullptr) continue;
            it->second->addData(kv.second);
        }
    }
    if (pe_weight_object_plane_) {
        const auto weight_plane_stats = pe_weight_object_plane_->snapshotStats();
        const auto authority_total =
            [](PeWeightObjectPlane::AuthorityClass observed,
               PeWeightObjectPlane::AuthorityClass expected) -> uint64_t {
            return observed == expected ? 1u : 0u;
        };
        const auto add_atlas_storage_stat = [this](const char* name, uint64_t value) {
            auto it = atlas_object_plane_stats_.find(name);
            if (it == atlas_object_plane_stats_.end() || it->second == nullptr) return;
            it->second->addData(value);
        };
        add_atlas_storage_stat(
            "atlas_storage_map_shared_owner_scope_enable",
            weight_plane_stats.owner_scope_enable ? 1u : 0u);
        add_atlas_storage_stat(
            "atlas_storage_map_shared_actual_owner_enable",
            weight_plane_stats.actual_owner_enable ? 1u : 0u);
        add_atlas_storage_stat(
            "atlas_storage_map_weight_idx_shared_enabled",
            weight_plane_stats.idx_enabled ? 1u : 0u);
        add_atlas_storage_stat(
            "atlas_storage_map_weight_value_shared_enabled",
            weight_plane_stats.l0_enabled ? 1u : 0u);
        add_atlas_storage_stat(
            "atlas_storage_map_weight_idx_private_authority_total",
            authority_total(
                weight_plane_stats.idx_authority,
                PeWeightObjectPlane::AuthorityClass::PrivateAuthority));
        add_atlas_storage_stat(
            "atlas_storage_map_weight_idx_shared_mirror_only_total",
            authority_total(
                weight_plane_stats.idx_authority,
                PeWeightObjectPlane::AuthorityClass::SharedMirrorOnly));
        add_atlas_storage_stat(
            "atlas_storage_map_weight_idx_shared_authority_active_total",
            authority_total(
                weight_plane_stats.idx_authority,
                PeWeightObjectPlane::AuthorityClass::SharedAuthorityActive));
        add_atlas_storage_stat(
            "atlas_storage_map_weight_value_private_authority_total",
            authority_total(
                weight_plane_stats.l0_authority,
                PeWeightObjectPlane::AuthorityClass::PrivateAuthority));
        add_atlas_storage_stat(
            "atlas_storage_map_weight_value_shared_mirror_only_total",
            authority_total(
                weight_plane_stats.l0_authority,
                PeWeightObjectPlane::AuthorityClass::SharedMirrorOnly));
        add_atlas_storage_stat(
            "atlas_storage_map_weight_value_shared_authority_active_total",
            authority_total(
                weight_plane_stats.l0_authority,
                PeWeightObjectPlane::AuthorityClass::SharedAuthorityActive));
        add_atlas_storage_stat(
            "atlas_storage_map_weight_idx_shared_reads_total",
            weight_plane_stats.idx_sram.reads_total);
        add_atlas_storage_stat(
            "atlas_storage_map_weight_idx_shared_resident_bytes_peak",
            weight_plane_stats.idx_sram.resident_bytes_peak);
        add_atlas_storage_stat(
            "atlas_storage_map_weight_value_shared_reads_total",
            weight_plane_stats.l0_sram.reads_total);
        add_atlas_storage_stat(
            "atlas_storage_map_weight_value_shared_resident_bytes_peak",
            weight_plane_stats.l0_sram.resident_bytes_peak);
        if (stat_pulse_osa_shared_weight_enabled_) {
            stat_pulse_osa_shared_weight_enabled_->addData(weight_plane_stats.enabled ? 1u : 0u);
        }
        if (stat_pulse_osa_shared_weight_owner_scope_enable_) {
            stat_pulse_osa_shared_weight_owner_scope_enable_->addData(
                weight_plane_stats.owner_scope_enable ? 1u : 0u);
        }
        if (stat_pulse_osa_shared_weight_actual_owner_enable_) {
            stat_pulse_osa_shared_weight_actual_owner_enable_->addData(
                weight_plane_stats.actual_owner_enable ? 1u : 0u);
        }
        if (stat_pulse_osa_shared_weight_idx_enabled_) {
            stat_pulse_osa_shared_weight_idx_enabled_->addData(
                weight_plane_stats.idx_enabled ? 1u : 0u);
        }
        if (stat_pulse_osa_shared_weight_idx_reads_total_) {
            stat_pulse_osa_shared_weight_idx_reads_total_->addData(
                weight_plane_stats.idx_sram.reads_total);
        }
        if (stat_pulse_osa_shared_weight_idx_writes_total_) {
            stat_pulse_osa_shared_weight_idx_writes_total_->addData(
                weight_plane_stats.idx_sram.writes_total);
        }
        if (stat_pulse_osa_shared_weight_idx_bank_conflict_ticks_total_) {
            stat_pulse_osa_shared_weight_idx_bank_conflict_ticks_total_->addData(
                weight_plane_stats.idx_sram.bank_conflict_ticks_total);
        }
        if (stat_pulse_osa_shared_weight_idx_predicted_extra_cycles_total_) {
            stat_pulse_osa_shared_weight_idx_predicted_extra_cycles_total_->addData(
                weight_plane_stats.idx_sram.predicted_extra_cycles_total);
        }
        if (stat_pulse_osa_shared_weight_idx_resident_bytes_peak_) {
            stat_pulse_osa_shared_weight_idx_resident_bytes_peak_->addData(
                weight_plane_stats.idx_sram.resident_bytes_peak);
        }
        if (stat_pulse_osa_shared_weight_l0_enabled_) {
            stat_pulse_osa_shared_weight_l0_enabled_->addData(
                weight_plane_stats.l0_enabled ? 1u : 0u);
        }
        if (stat_pulse_osa_shared_weight_l0_reads_total_) {
            stat_pulse_osa_shared_weight_l0_reads_total_->addData(
                weight_plane_stats.l0_sram.reads_total);
        }
        if (stat_pulse_osa_shared_weight_l0_writes_total_) {
            stat_pulse_osa_shared_weight_l0_writes_total_->addData(
                weight_plane_stats.l0_sram.writes_total);
        }
        if (stat_pulse_osa_shared_weight_l0_fill_total_) {
            stat_pulse_osa_shared_weight_l0_fill_total_->addData(
                weight_plane_stats.l0_fill_total);
        }
        if (stat_pulse_osa_shared_weight_l0_evict_total_) {
            stat_pulse_osa_shared_weight_l0_evict_total_->addData(
                weight_plane_stats.l0_evict_total);
        }
        if (stat_pulse_osa_shared_weight_l0_bank_conflict_ticks_total_) {
            stat_pulse_osa_shared_weight_l0_bank_conflict_ticks_total_->addData(
                weight_plane_stats.l0_sram.bank_conflict_ticks_total);
        }
        if (stat_pulse_osa_shared_weight_l0_predicted_extra_cycles_total_) {
            stat_pulse_osa_shared_weight_l0_predicted_extra_cycles_total_->addData(
                weight_plane_stats.l0_sram.predicted_extra_cycles_total);
        }
        if (stat_pulse_osa_shared_weight_l0_resident_bytes_peak_) {
            stat_pulse_osa_shared_weight_l0_resident_bytes_peak_->addData(
                weight_plane_stats.l0_sram.resident_bytes_peak);
        }
    } else {
        const auto add_atlas_storage_stat = [this](const char* name, uint64_t value) {
            auto it = atlas_object_plane_stats_.find(name);
            if (it == atlas_object_plane_stats_.end() || it->second == nullptr) return;
            it->second->addData(value);
        };
        add_atlas_storage_stat("atlas_storage_map_shared_owner_scope_enable", 0u);
        add_atlas_storage_stat("atlas_storage_map_shared_actual_owner_enable", 0u);
        add_atlas_storage_stat("atlas_storage_map_weight_idx_shared_enabled", 0u);
        add_atlas_storage_stat("atlas_storage_map_weight_value_shared_enabled", 0u);
        add_atlas_storage_stat("atlas_storage_map_weight_idx_private_authority_total", 1u);
        add_atlas_storage_stat("atlas_storage_map_weight_idx_shared_mirror_only_total", 0u);
        add_atlas_storage_stat("atlas_storage_map_weight_idx_shared_authority_active_total", 0u);
        add_atlas_storage_stat("atlas_storage_map_weight_value_private_authority_total", 1u);
        add_atlas_storage_stat("atlas_storage_map_weight_value_shared_mirror_only_total", 0u);
        add_atlas_storage_stat("atlas_storage_map_weight_value_shared_authority_active_total", 0u);
        add_atlas_storage_stat("atlas_storage_map_weight_idx_shared_reads_total", 0u);
        add_atlas_storage_stat("atlas_storage_map_weight_idx_shared_resident_bytes_peak", 0u);
        add_atlas_storage_stat("atlas_storage_map_weight_value_shared_reads_total", 0u);
        add_atlas_storage_stat("atlas_storage_map_weight_value_shared_resident_bytes_peak", 0u);
        if (stat_pulse_osa_shared_weight_enabled_) stat_pulse_osa_shared_weight_enabled_->addData(0u);
        if (stat_pulse_osa_shared_weight_owner_scope_enable_) {
            stat_pulse_osa_shared_weight_owner_scope_enable_->addData(0u);
        }
        if (stat_pulse_osa_shared_weight_actual_owner_enable_) {
            stat_pulse_osa_shared_weight_actual_owner_enable_->addData(0u);
        }
        if (stat_pulse_osa_shared_weight_idx_enabled_) {
            stat_pulse_osa_shared_weight_idx_enabled_->addData(0u);
        }
        if (stat_pulse_osa_shared_weight_l0_enabled_) {
            stat_pulse_osa_shared_weight_l0_enabled_->addData(0u);
        }
        if (stat_pulse_osa_shared_weight_l0_fill_total_) {
            stat_pulse_osa_shared_weight_l0_fill_total_->addData(0u);
        }
        if (stat_pulse_osa_shared_weight_l0_evict_total_) {
            stat_pulse_osa_shared_weight_l0_evict_total_->addData(0u);
        }
    }
    if (pulse_fabric_) {
        const auto pulse_stats = pulse_fabric_->snapshotStats();
        const auto add_atlas_control_runtime_stat = [this](const char* name, uint64_t value) {
            auto it = atlas_object_plane_stats_.find(name);
            if (it == atlas_object_plane_stats_.end() || it->second == nullptr) return;
            it->second->addData(value);
        };
        if (stat_pulse_ingress_packets_total_) {
            stat_pulse_ingress_packets_total_->addData(pulse_stats.ingress_packets_total);
        }
        if (stat_pulse_ingress_spike_packets_total_) {
            stat_pulse_ingress_spike_packets_total_->addData(pulse_stats.ingress_spike_packets_total);
        }
        if (stat_pulse_ingress_spikekey_packets_total_) {
            stat_pulse_ingress_spikekey_packets_total_->addData(pulse_stats.ingress_spikekey_packets_total);
        }
        if (stat_pulse_ingress_spiketilekey_packets_total_) {
            stat_pulse_ingress_spiketilekey_packets_total_->addData(
                pulse_stats.ingress_spiketilekey_packets_total);
        }
        if (stat_pulse_ingress_core_dispatch_total_) {
            stat_pulse_ingress_core_dispatch_total_->addData(pulse_stats.ingress_core_dispatch_total);
        }
        if (stat_pulse_ingress_shared_buffered_total_) {
            stat_pulse_ingress_shared_buffered_total_->addData(
                pulse_stats.ingress_shared_buffered_total);
        }
        if (stat_pulse_ingress_shared_dispatch_total_) {
            stat_pulse_ingress_shared_dispatch_total_->addData(
                pulse_stats.ingress_shared_dispatch_total);
        }
        if (stat_pulse_ingress_direct_deliver_total_) {
            stat_pulse_ingress_direct_deliver_total_->addData(
                pulse_stats.ingress_direct_deliver_total);
        }
        if (stat_pulse_ingress_bypass_total_) {
            stat_pulse_ingress_bypass_total_->addData(pulse_stats.ingress_bypass_total);
        }
        if (stat_pulse_ingress_pressure_bypass_total_) {
            stat_pulse_ingress_pressure_bypass_total_->addData(
                pulse_stats.ingress_pressure_bypass_total);
        }
        if (stat_pulse_ingress_singleton_bypass_total_) {
            stat_pulse_ingress_singleton_bypass_total_->addData(
                pulse_stats.ingress_singleton_bypass_total);
        }
        if (stat_pulse_ingress_deadline_bypass_total_) {
            stat_pulse_ingress_deadline_bypass_total_->addData(
                pulse_stats.ingress_deadline_bypass_total);
        }
        if (stat_pulse_ingress_pressure_cycles_total_) {
            stat_pulse_ingress_pressure_cycles_total_->addData(
                pulse_stats.ingress_pressure_cycles_total);
        }
        if (stat_pulse_ingress_entries_peak_) {
            stat_pulse_ingress_entries_peak_->addData(pulse_stats.ingress_entries_peak);
        }
        if (stat_pulse_control_entries_current_) {
            stat_pulse_control_entries_current_->addData(pulse_stats.control_entries_current);
        }
        if (stat_pulse_control_entries_peak_) {
            stat_pulse_control_entries_peak_->addData(pulse_stats.control_entries_peak);
        }
        if (stat_pulse_control_backlog_cycles_total_) {
            stat_pulse_control_backlog_cycles_total_->addData(
                pulse_stats.control_backlog_cycles_total);
        }
        if (stat_pulse_control_messages_enqueued_total_) {
            stat_pulse_control_messages_enqueued_total_->addData(
                pulse_stats.control_messages_enqueued_total);
        }
        if (stat_pulse_control_messages_dequeued_total_) {
            stat_pulse_control_messages_dequeued_total_->addData(
                pulse_stats.control_messages_dequeued_total);
        }
        if (stat_pulse_control_frontier_export_total_) {
            stat_pulse_control_frontier_export_total_->addData(
                pulse_stats.control_frontier_export_total);
        }
        if (stat_pulse_control_owner_announce_total_) {
            stat_pulse_control_owner_announce_total_->addData(
                pulse_stats.control_owner_announce_total);
        }
        if (stat_pulse_control_join_request_total_) {
            stat_pulse_control_join_request_total_->addData(
                pulse_stats.control_join_request_total);
        }
        if (stat_pulse_control_ready_fanout_total_) {
            stat_pulse_control_ready_fanout_total_->addData(
                pulse_stats.control_ready_fanout_total);
        }
        if (stat_pulse_control_join_reject_total_) {
            stat_pulse_control_join_reject_total_->addData(
                pulse_stats.control_join_reject_total);
        }
        add_atlas_control_runtime_stat(
            "atlas_control_runtime_queued_frontier_export_total",
            pulse_stats.control_frontier_export_total);
        add_atlas_control_runtime_stat(
            "atlas_control_runtime_queued_owner_announce_total",
            pulse_stats.control_owner_announce_total);
        add_atlas_control_runtime_stat(
            "atlas_control_runtime_queued_join_request_total",
            pulse_stats.control_join_request_total);
        add_atlas_control_runtime_stat(
            "atlas_control_runtime_queued_ready_fanout_total",
            pulse_stats.control_ready_fanout_total);
        add_atlas_control_runtime_stat(
            "atlas_control_runtime_queued_join_reject_total",
            pulse_stats.control_join_reject_total);
        add_atlas_control_runtime_stat(
            "atlas_control_runtime_consumed_frontier_export_total",
            pulse_stats.control_frontier_export_consumed_total);
        add_atlas_control_runtime_stat(
            "atlas_control_runtime_consumed_owner_announce_total",
            pulse_stats.control_owner_announce_consumed_total);
        add_atlas_control_runtime_stat(
            "atlas_control_runtime_consumed_join_request_total",
            pulse_stats.control_join_request_consumed_total);
        add_atlas_control_runtime_stat(
            "atlas_control_runtime_consumed_ready_fanout_total",
            pulse_stats.control_ready_fanout_consumed_total);
        add_atlas_control_runtime_stat(
            "atlas_control_runtime_consumed_join_reject_total",
            pulse_stats.control_join_reject_consumed_total);
        add_atlas_control_runtime_stat(
            "atlas_control_runtime_backlog_messages_current",
            pulse_stats.control_entries_current);
        add_atlas_control_runtime_stat(
            "atlas_control_runtime_backlog_messages_peak",
            pulse_stats.control_entries_peak);
        add_atlas_control_runtime_stat(
            "atlas_control_runtime_backlog_cycles_total",
            pulse_stats.control_backlog_cycles_total);
        if (stat_pulse_core_queue_entries_peak_) {
            stat_pulse_core_queue_entries_peak_->addData(pulse_stats.core_queue_entries_peak);
        }
        if (stat_pulse_harbor_buckets_total_) {
            stat_pulse_harbor_buckets_total_->addData(pulse_stats.harbor_buckets_total);
        }
        if (stat_pulse_harbor_packet_sum_) {
            stat_pulse_harbor_packet_sum_->addData(pulse_stats.harbor_packet_sum);
        }
        if (stat_pulse_harbor_consumer_sum_) {
            stat_pulse_harbor_consumer_sum_->addData(pulse_stats.harbor_consumer_sum);
        }
        if (stat_pulse_harbor_bucket_peak_) {
            stat_pulse_harbor_bucket_peak_->addData(pulse_stats.harbor_bucket_peak);
        }
        if (stat_pulse_harbor_singleton_buckets_total_) {
            stat_pulse_harbor_singleton_buckets_total_->addData(
                pulse_stats.harbor_singleton_buckets_total);
        }
        if (stat_pulse_descriptor_total_) {
            stat_pulse_descriptor_total_->addData(pulse_stats.descriptor_total);
        }
        if (stat_pulse_descriptor_packet_sum_) {
            stat_pulse_descriptor_packet_sum_->addData(pulse_stats.descriptor_packet_sum);
        }
        if (stat_pulse_descriptor_consumer_sum_) {
            stat_pulse_descriptor_consumer_sum_->addData(pulse_stats.descriptor_consumer_sum);
        }
        if (stat_pulse_descriptor_singleton_drop_total_) {
            stat_pulse_descriptor_singleton_drop_total_->addData(
                pulse_stats.descriptor_singleton_drop_total);
        }
    } else {
        const auto add_atlas_control_runtime_stat = [this](const char* name, uint64_t value) {
            auto it = atlas_object_plane_stats_.find(name);
            if (it == atlas_object_plane_stats_.end() || it->second == nullptr) return;
            it->second->addData(value);
        };
        add_atlas_control_runtime_stat("atlas_control_runtime_queued_frontier_export_total", 0u);
        add_atlas_control_runtime_stat("atlas_control_runtime_queued_owner_announce_total", 0u);
        add_atlas_control_runtime_stat("atlas_control_runtime_queued_join_request_total", 0u);
        add_atlas_control_runtime_stat("atlas_control_runtime_queued_ready_fanout_total", 0u);
        add_atlas_control_runtime_stat("atlas_control_runtime_queued_join_reject_total", 0u);
        add_atlas_control_runtime_stat("atlas_control_runtime_consumed_frontier_export_total", 0u);
        add_atlas_control_runtime_stat("atlas_control_runtime_consumed_owner_announce_total", 0u);
        add_atlas_control_runtime_stat("atlas_control_runtime_consumed_join_request_total", 0u);
        add_atlas_control_runtime_stat("atlas_control_runtime_consumed_ready_fanout_total", 0u);
        add_atlas_control_runtime_stat("atlas_control_runtime_consumed_join_reject_total", 0u);
        add_atlas_control_runtime_stat("atlas_control_runtime_backlog_messages_current", 0u);
        add_atlas_control_runtime_stat("atlas_control_runtime_backlog_messages_peak", 0u);
        add_atlas_control_runtime_stat("atlas_control_runtime_backlog_cycles_total", 0u);
    }

    // 输出时间窗口化统计CSV（如已启用并指定路径）
    if (window_stats_enable_ && !window_csv_.empty()) {
        writeWindowCsv_();
    }

    // 调用网络接口的finish
    if (external_nic_) {
        external_nic_->finish();
    }
    // 注意：当使用 SST 引擎 stop-at 结束仿真时，finish() 期间再次触发 OKToEndSim
    // 会导致 Exit 事件被重复调度并在引擎侧触发双重释放；组件主控停止（sim_stop_ns_>0）
    // 已由 clockTick() 在阈值处触发 OKToEndSim。
}

void MultiCorePE::maybeInjectTestTraffic_(Cycle_t current_cycle) {
    // 0b. 测试注入：在首个有效周期从 core0 向 core1 注入一个跨核脉冲（仅当启用测试流量时）
    if (!(enable_test_traffic_ && !test_injected_ && num_cores_ > 1 && current_cycle == 5000)) return;

    // 构造一个从本PE core0 -> core1 的跨核脉冲（使用全局ID口径）
    const uint32_t src_global = static_cast<uint32_t>(global_neuron_base_);
    const uint32_t dst_global =
        static_cast<uint32_t>(static_cast<uint64_t>(global_neuron_base_) + static_cast<uint64_t>(neurons_per_core_));
    SpikeEvent* test_spike = new SpikeEvent(src_global, dst_global, static_cast<uint32_t>(node_id_), 0.5f, current_cycle_);
    int src_core = determineTargetUnit(static_cast<int>(src_global));
    int dst_core = determineTargetUnit(static_cast<int>(dst_global));
    if (src_core >= 0 && dst_core >= 0 && src_core != dst_core) {
        spike_packet_bridge_.sendAuto(test_spike);
        PE_LOG(1, "🧪 注入跨核脉冲: 核心%d->核心%d\n", src_core, dst_core);
        test_injected_ = true;
    } else {
        delete test_spike;
        test_injected_ = true;
    }
}

void MultiCorePE::driveCoresManually_(Cycle_t current_cycle) {
    // 2. SubComponent时钟由SST自动管理，无需手动调用tick
    // 若子组件未被SST调度（某些环境组合下可能发生），则回退为手动驱动一拍，确保窗口推进与队列消费
    if (!manual_core_drive_enable_) return;

    for (int i = 0; i < num_cores_; i++) {
        if (cores_[i] == nullptr) continue;
        if (auto* hooks = dynamic_cast<ICoreControlHooks*>(cores_[i])) {
            hooks->driveOneCycle();
        }
    }
}

void MultiCorePE::refreshProcessingUnitStates_() {
    static const std::map<std::string, uint64_t> kEmptyStats;
    // 更新处理单元状态统计（从SnnPE SubComponent获取实际数据）
    for (int i = 0; i < num_cores_; i++) {
        if (cores_[i] != nullptr) {
            std::map<std::string, uint64_t> core_stats;
            cores_[i]->getStatistics(core_stats);
            auto it_sp = core_stats.find("spikes_received");
            auto it_nf = core_stats.find("neurons_fired");
            uint64_t old_spikes = unit_states_[i].spikes_processed;
            uint64_t new_spikes = (it_sp != core_stats.end()) ? it_sp->second : 0;
            unit_states_[i].spikes_processed = new_spikes;
            unit_states_[i].neurons_fired = (it_nf != core_stats.end()) ? it_nf->second : 0;
            unit_states_[i].utilization = cores_[i]->getUtilization();
            unit_states_[i].is_active = cores_[i]->hasWork();
            for (auto& mod : workload_stats_modules_) {
                if (mod) mod->refreshCore(static_cast<size_t>(i), core_stats);
            }

            // 调试：跟踪统计数据变化 (已禁用避免过多输出)
            // if (new_spikes != old_spikes) {
            //     printf("DEBUG: 核心%d统计更新，节点%d - 旧值:%lu -> 新值:%lu (来自getStatistics)\n",
            //            i, node_id_, old_spikes, new_spikes);
            //     fflush(stdout);
            // }
            (void)old_spikes;
        } else {
            unit_states_[i].spikes_processed = 0;
            unit_states_[i].neurons_fired = 0;
            unit_states_[i].utilization = 0.0;
            unit_states_[i].is_active = false;
            for (auto& mod : workload_stats_modules_) {
                if (mod) mod->refreshCore(static_cast<size_t>(i), kEmptyStats);
            }
        }
    }
}

bool MultiCorePE::clockTick(Cycle_t current_cycle) {
    current_cycle_ = current_cycle;
    // 当启用组件主控停止时，到达阈值立刻OKToEndSim并停止本组件时钟
    if (sim_stop_ns_ > 0 && current_cycle_ >= sim_stop_ns_) {
        if (!ok_to_end_sent_) {
            primaryComponentOKToEndSim();
            ok_to_end_sent_ = true;
        }
        return false;
    }

    if (pulse_fabric_) {
        pulse_fabric_->observeControlBacklogCycle();
    }
    
    // 详细调试信息（仅在高详细度时输出）
    if (!first_tick_logged_) {
        if (sentinel_enabled_) {
            PE_LOG(1, "[[sentinel-pe-clock]] node=%d first_tick cyc=%" PRIu64 "\n", node_id_, (uint64_t)current_cycle_);
        }
    PE_LOG(2, "[diag-PE] clockTick start node=%d\n", node_id_);
        first_tick_logged_ = true;
    }

    // 进度心跳：默认关闭，仅在调试时开启，帮助定位仿真是否在推进/卡住
    if (progress_log_interval_ns_ > 0) {
        const bool node_ok = (progress_log_node_ < 0) || (progress_log_node_ == node_id_);
        if (node_ok && current_cycle_ > 0 && (static_cast<uint64_t>(current_cycle_) % progress_log_interval_ns_ == 0)) {
            PE_LOG(0, "[progress] node=%d cyc=%" PRIu64 " extq=%zu\n",
                   node_id_, (uint64_t)current_cycle_, noc_subsys_.incomingQueueSize());
        }
    }

    // Step barrier readiness gating (loader_done_key):
    // Avoid starting step-limited injections before WeightLoader/BCSR rowptr prefetch can proceed.
    if (global_step_sync_enable_ && global_step_sync_ready_ && gas_step_ctrl_link_ && !global_step_ready_sent_ && wait_for_loader_done_) {
        // Diagnostic (targeted): if step-limited hangs under MPI partitioning, the most common cause is that
        // WeightLoader and MultiCorePE are placed on different ranks, making SharedArray-based loader_done
        // gating invisible. Keep this extremely low-noise: only PE0 prints, rate-limited.
        static uint32_t diag_wait_prints = 0;
        const uint64_t now = static_cast<uint64_t>(current_cycle_);
        if (!loader_ready_latched_) {
            if (!loader_wait_started_) {
                loader_wait_started_ = true;
                loader_wait_start_cycle_ = now;
            }
            if (output_ && node_id_ == 0 && verbose_ >= 1 && (now % 10000u) == 0u && diag_wait_prints < 16u) {
                output_->verbose(
                    CALL_INFO, 1, 0,
                    "[[sentinel-step-sync]] node=%d waiting loader_done_key=%s shared_init=%d shared_ptr=%p\n",
                    node_id_,
                    loader_done_key_.c_str(),
                    (loader_done_shared_ ? 1 : 0),
                    (void*)loader_done_shared_.get());
                diag_wait_prints += 1;
            }
        }
        if (!loader_ready_latched_) {
            if (loader_done_shared_ && loader_done_shared_->size() > 0) {
                const int ready = loader_done_shared_->mutex_read(0);
                if (ready != 0) {
                    loader_ready_latched_ = true;
                    loader_ready_cycle_ = static_cast<uint64_t>(current_cycle_);
                    if (output_ && node_id_ == 0 && verbose_ >= 1) {
                        output_->verbose(
                            CALL_INFO, 1, 0,
                            "[[sentinel-step-sync]] node=%d loader_done latched (ready=%d) at cyc=%" PRIu64 "\n",
                            node_id_, ready, (uint64_t)loader_ready_cycle_);
                    }
                }
            }
        }
        if (!loader_ready_latched_ && loader_done_timeout_cycles_ > 0 && !loader_ready_forced_) {
            if (!loader_wait_started_) {
                loader_wait_started_ = true;
                loader_wait_start_cycle_ = now;
            }
            const uint64_t waited = (now >= loader_wait_start_cycle_) ? (now - loader_wait_start_cycle_) : 0;
            if (waited >= loader_done_timeout_cycles_) {
                auto* ev = new GasStepBarrierEvent(GasStepBarrierOp::PeReady, /*seq*/0, static_cast<uint32_t>(node_id_));
                gas_step_ctrl_link_->send(ev);
                global_step_ready_sent_ = true;
                loader_ready_forced_ = true;
                if (stat_loader_done_timeout_fallback_total_) stat_loader_done_timeout_fallback_total_->addData(1);
                if (output_) {
                    output_->verbose(
                        CALL_INFO, 0, 0,
                        "WARN: node=%d loader_done_key=%s timeout waited=%" PRIu64 " cycles, send PE_READY fallback\n",
                        node_id_, loader_done_key_.c_str(), (uint64_t)waited);
                }
            }
        }
        if (loader_ready_latched_) {
            const uint64_t since = (now >= loader_ready_cycle_) ? (now - loader_ready_cycle_) : 0;
            if (global_step_ready_delay_cycles_ == 0 || since >= global_step_ready_delay_cycles_) {
                auto* ev = new GasStepBarrierEvent(GasStepBarrierOp::PeReady, /*seq*/0, static_cast<uint32_t>(node_id_));
                gas_step_ctrl_link_->send(ev);
                global_step_ready_sent_ = true;
                if (output_ && node_id_ == 0 && verbose_ >= 1) {
                    output_->verbose(
                        CALL_INFO, 1, 0,
                        "[[sentinel-step-sync]] node=%d send PE_READY after loader_done (since=%" PRIu64 " delay=%" PRIu64 ")\n",
                        node_id_, (uint64_t)since, (uint64_t)global_step_ready_delay_cycles_);
                }
            }
        }
    }

    // Global Step barrier: 当收到 START_STEP(seq) 时，在时钟边界打开所有 core 的新窗口
    if (global_step_sync_enable_ && global_step_sync_ready_ && global_step_start_pending_) {
        const bool can_start = (global_step_active_seq_ == 0) || global_step_done_sent_;
        if (can_start) {
            beginGlobalStep_(global_step_pending_seq_);
            global_step_start_pending_ = false;
        }
    }
    
    // 0a. Step 注入调度（Phase3-B 下沉为 StepActivationSubsystem）
    step_activation_subsys_.tick(static_cast<uint64_t>(current_cycle_), getCurrentSimTimeNano());

    // 0b. 测试注入：在首个有效周期从 core0 向 core1 注入一个跨核脉冲（仅当启用测试流量时）
    maybeInjectTestTraffic_(current_cycle_);
    
    // 1. 处理外部脉冲队列（Phase4-A1.1：下沉至 NoC 子系统）
    noc_subsys_.drainIncomingQueue(static_cast<uint64_t>(current_cycle_));
    drainPulseIngress_();
    
    // 2. SubComponent时钟由SST自动管理，无需手动调用tick
    // 若子组件未被SST调度（某些环境组合下可能发生），则回退为手动驱动一拍，确保窗口推进与队列消费
    driveCoresManually_(current_cycle_);
    // 更新处理单元状态统计（从SnnPE SubComponent获取实际数据）
    refreshProcessingUnitStates_();
    
    // 3. 内部互连（ring）时钟滴答（Phase4-A1.1：由 NoC 子系统编排）
    noc_subsys_.tickRing(static_cast<uint64_t>(current_cycle));
    
    // 4. 多核控制器时钟滴答
    if (controller_) {
        controller_->tick();
        
        // 每100周期进行一次负载均衡检查
        if (current_cycle % 100 == 0) {
            checkLoadBalance();
        }
    }
    
    // 5. 生成测试流量
    if (enable_test_traffic_) {
        generateTestTraffic();
    }
    
    // 6. 更新统计信息（每1000周期一次）
    if (current_cycle % 1000 == 0) {
        updateStatistics();
    }

    // Global Step barrier（PE 侧 done policy）
    // - EndScatter policy: 在 notifyStageEvent() 处由 core 的 EndScatter(seq) 聚合触发。
    // - Drain/Quiescent/FixedCycles policy: 在此处基于“本 PE 是否仍有在途事务/是否静默足够久”触发。
    if (global_step_sync_enable_ &&
        gas_step_ctrl_link_ &&
        !global_step_done_sent_ &&
        global_step_active_seq_ != 0) {
        if (global_step_done_policy_ == GlobalStepDonePolicy::FixedCycles) {
            const uint64_t now = static_cast<uint64_t>(current_cycle_);
            const uint64_t since_begin = (now >= global_step_begin_cycle_) ? (now - global_step_begin_cycle_) : 0;
            if (since_begin >= global_step_fixed_cycles_) {
                noteStepBarrierWaitNs_(global_step_active_seq_, getCurrentSimTimeNano());
                auto* ev = new GasStepBarrierEvent(GasStepBarrierOp::PeDone,
                                                   global_step_active_seq_,
                                                   static_cast<uint32_t>(node_id_));
                // Step-level telemetry (best-effort): enables GlobalGasStepController criticality-aware control.
                // total: from BeginGather to PE_DONE send time (includes drain/quiescent wait for non-EndScatter policies)
                // apply: from BeginApply to BeginScatter (pure Apply duration, excludes drain)
                {
                    auto it = stage_marks_.find(global_step_active_seq_);
                    if (it != stage_marks_.end()) {
                        const auto& m = it->second;
                        const uint64_t now_ns = getCurrentSimTimeNano();
                        if (m.bg != 0 && now_ns >= m.bg) ev->step_total_ns = now_ns - m.bg;
                        if (m.ga != 0 && m.bs != 0 && m.bs >= m.ga) ev->step_apply_ns = m.bs - m.ga;
                    }
                }
                gas_step_ctrl_link_->send(ev);
                global_step_done_sent_ = true;
                if (stat_global_steps_done_total_) stat_global_steps_done_total_->addData(1);
                if (sentinel_enabled_ && output_ && global_step_active_seq_ <= 2) {
                    output_->verbose(CALL_INFO, 2, 0,
                        "[[sentinel-step-sync]] node=%d send PE_DONE(fixed_cycles) seq=%u since_begin=%" PRIu64 "\n",
                        node_id_, global_step_active_seq_, (uint64_t)since_begin);
                }
            }
        } else if (global_step_done_policy_ == GlobalStepDonePolicy::Drain) {
            bool active = false;
            // 1) 必须等待本 step 的注入已发生，否则会在“同拍开始即完成”时误判。
            const bool injected = step_activation_subsys_.injectedForSeq(global_step_active_seq_);
            if (!injected) active = true;
            // 2) 显式检查 NoC/NIC/片上 ring 是否仍有在途包/背压排队。
            const bool noc_idle = noc_subsys_.isIdle();
            if (!noc_idle) active = true;
            if (!pulse_ingress_buffered_packets_.empty()) active = true;

            // 3) step 语义等价：
            // - 对已经进入 BeginApply/EndApply/BeginScatter/EndScatter 的 core，必须等待该 core 到达 EndScatter(seq)。
            // - 对仍停在 BeginGather 的 core，也必须继续 hold；否则会出现慢核还在旧 step Gather，
            //   但 controller 已经广播下一步 START_STEP 的 closure 漏判。
            GlobalStepDrainInputs drain_inputs{};
            drain_inputs.injected = injected;
            drain_inputs.noc_idle = noc_idle;
            drain_inputs.stage_arrays_ready =
                (global_step_last_stage_code_.size() == static_cast<size_t>(num_cores_) &&
                 global_step_last_stage_seq_.size() == static_cast<size_t>(num_cores_));
            drain_inputs.cores.reserve(static_cast<size_t>(num_cores_));
            if (drain_inputs.stage_arrays_ready) {
                for (int i = 0; i < num_cores_; ++i) {
                    const size_t idx = static_cast<size_t>(i);
                    const bool have_stage =
                        (global_step_last_stage_seq_[idx] == global_step_active_seq_) &&
                        (global_step_last_stage_code_[idx] != 0);
                    drain_inputs.cores.push_back(GlobalStepDrainCoreState{
                        have_stage ? global_step_last_stage_code_[idx] : 0,
                        cores_[i] && cores_[i]->hasWork(),
                    });
                }
            } else {
                for (int i = 0; i < num_cores_; ++i) {
                    drain_inputs.cores.push_back(GlobalStepDrainCoreState{
                        0,
                        cores_[i] && cores_[i]->hasWork(),
                    });
                }
            }
            const GlobalStepDrainDecision drain_decision =
                evaluateGlobalStepDrainDecision(drain_inputs);
            active = active || drain_decision.active;
            const bool uses_stage_events = drain_decision.uses_stage_events;
            const bool all_end_scatter = drain_decision.all_end_scatter;
            const int stage_progress_cores = drain_decision.stage_progress_cores;
            const int stage_done_cores = drain_decision.stage_done_cores;
            const int stage_bg_only_cores = drain_decision.stage_bg_only_cores;
            const int stage_begin_apply_cores = drain_decision.stage_begin_apply_cores;
            const int stage_end_apply_cores = drain_decision.stage_end_apply_cores;
            const int stage_begin_scatter_cores = drain_decision.stage_begin_scatter_cores;
            const int stage_end_scatter_cores = drain_decision.stage_end_scatter_cores;
            const int fallback_busy_cores = drain_decision.fallback_busy_cores;

            const bool hold_for_gather_completion = drain_decision.hold_for_gather_completion;
            if (hold_for_gather_completion) {
                // 仍停留在 Gather：必须等 workload 的 Gather->EndGather quiesce 规则自己推进，
                // 不能让 PE 级 Drain 先于空窗口/慢窗口的 BeginApply 收尾。
                active = true;
            }

            // Drain 卡点探针（仅 node0 / seq<=2 / sentinel 模式限量打印）：用于定位“为什么 step 不推进”。
            if (sentinel_enabled_ && output_ && node_id_ == 0 && global_step_active_seq_ <= 2) {
                const uint64_t now = static_cast<uint64_t>(current_cycle_);
                if ((now % 10000u) == 0u && global_step_drain_diag_count_ < 64u) {
                    const size_t inq = noc_subsys_.incomingQueueSize();
                    const int ring_p = noc_subsys_.ringPendingMessageCount();
                    const size_t nic_p = noc_subsys_.nicPendingSendCount();
                    const uint64_t quiet_dbg = (now >= global_step_last_activity_cycle_)
                        ? (now - global_step_last_activity_cycle_)
                        : 0;
                    output_->verbose(CALL_INFO, 2, 0,
                        "[[sentinel-step-drain]] node=%d seq=%u injected=%d stage=%d all_es=%d progressed=%d done=%d bg_only=%d ba=%d ea=%d bs=%d es=%d bg_hold=%d fallback_busy=%d noc_idle=%d inq=%zu ring=%d nic_pending=%zu quiet=%" PRIu64 " min=%" PRIu64 "\n",
                        node_id_,
                        global_step_active_seq_,
                        injected ? 1 : 0,
                        uses_stage_events ? 1 : 0,
                        all_end_scatter ? 1 : 0,
                        stage_progress_cores,
                        stage_done_cores,
                        stage_bg_only_cores,
                        stage_begin_apply_cores,
                        stage_end_apply_cores,
                        stage_begin_scatter_cores,
                        stage_end_scatter_cores,
                        hold_for_gather_completion ? 1 : 0,
                        fallback_busy_cores,
                        noc_idle ? 1 : 0,
                        inq,
                        ring_p,
                        nic_p,
                        (uint64_t)quiet_dbg,
                        (uint64_t)global_step_drain_min_cycles_);
                    global_step_drain_diag_count_ += 1;
                }
            }

            if (active) {
                global_step_last_activity_cycle_ = static_cast<uint64_t>(current_cycle_);
            } else {
                const uint64_t now = static_cast<uint64_t>(current_cycle_);
                const uint64_t last = global_step_last_activity_cycle_;
                const uint64_t quiet = (now >= last) ? (now - last) : 0;
                if (quiet >= global_step_drain_min_cycles_) {
                    noteStepBarrierWaitNs_(global_step_active_seq_, getCurrentSimTimeNano());
                    auto* ev = new GasStepBarrierEvent(GasStepBarrierOp::PeDone,
                                                       global_step_active_seq_,
                                                       static_cast<uint32_t>(node_id_));
                    // Step-level telemetry (best-effort): enables GlobalGasStepController criticality-aware control.
                    {
                        auto it = stage_marks_.find(global_step_active_seq_);
                        if (it != stage_marks_.end()) {
                            const auto& m = it->second;
                            const uint64_t now_ns = getCurrentSimTimeNano();
                            if (m.bg != 0 && now_ns >= m.bg) ev->step_total_ns = now_ns - m.bg;
                            if (m.ga != 0 && m.bs != 0 && m.bs >= m.ga) ev->step_apply_ns = m.bs - m.ga;
                        }
                    }
                    gas_step_ctrl_link_->send(ev);
                    global_step_done_sent_ = true;
                    if (stat_global_steps_done_total_) stat_global_steps_done_total_->addData(1);
                    if (sentinel_enabled_ && output_ && global_step_active_seq_ <= 2) {
                        output_->verbose(CALL_INFO, 2, 0,
                            "[[sentinel-step-sync]] node=%d send PE_DONE(drain) seq=%u quiet=%" PRIu64 " (min=%" PRIu64 ")\n",
                            node_id_, global_step_active_seq_, (uint64_t)quiet, (uint64_t)global_step_drain_min_cycles_);
                    }
                }
            }
        } else if (global_step_done_policy_ == GlobalStepDonePolicy::Quiescent) {
            bool active = false;
            if (!step_activation_subsys_.injectedForSeq(global_step_active_seq_)) active = true;
            if (!noc_subsys_.isIdle()) active = true;
            if (!pulse_ingress_buffered_packets_.empty()) active = true;
            for (int i = 0; i < num_cores_; ++i) {
                if (cores_[i] && cores_[i]->hasWork()) {
                    active = true;
                    break;
                }
            }

            if (active) {
                global_step_last_activity_cycle_ = static_cast<uint64_t>(current_cycle_);
            } else {
                const uint64_t now = static_cast<uint64_t>(current_cycle_);
                const uint64_t last = global_step_last_activity_cycle_;
                const uint64_t quiet = (now >= last) ? (now - last) : 0;
                if (quiet >= global_step_quiescent_min_cycles_) {
                    noteStepBarrierWaitNs_(global_step_active_seq_, getCurrentSimTimeNano());
                    auto* ev = new GasStepBarrierEvent(GasStepBarrierOp::PeDone,
                                                       global_step_active_seq_,
                                                       static_cast<uint32_t>(node_id_));
                    // Step-level telemetry (best-effort): enables GlobalGasStepController criticality-aware control.
                    {
                        auto it = stage_marks_.find(global_step_active_seq_);
                        if (it != stage_marks_.end()) {
                            const auto& m = it->second;
                            const uint64_t now_ns = getCurrentSimTimeNano();
                            if (m.bg != 0 && now_ns >= m.bg) ev->step_total_ns = now_ns - m.bg;
                            if (m.ga != 0 && m.bs != 0 && m.bs >= m.ga) ev->step_apply_ns = m.bs - m.ga;
                        }
                    }
                    gas_step_ctrl_link_->send(ev);
                    global_step_done_sent_ = true;
                    if (stat_global_steps_done_total_) stat_global_steps_done_total_->addData(1);
                    if (sentinel_enabled_ && output_ && global_step_active_seq_ <= 2) {
                        output_->verbose(CALL_INFO, 2, 0,
                            "[[sentinel-step-sync]] node=%d send PE_DONE(quiescent) seq=%u quiet=%" PRIu64 "\n",
                            node_id_, global_step_active_seq_, (uint64_t)quiet);
                    }
                }
            }
        }
    }
    
    // 时钟事件处理，让外部组件有机会基于周期推进
    // 继续仿真
    return false;
}

void MultiCorePE::handleExternalSpikeEvent(SST::Event* ev) {
    if (!ev) return;
    // 外部端口事件解析：NocPacketEvent 走 NoC；SpikeEvent 走 Stimulus 的直注入（仅本地投递，语义冻结）。
    if (auto* spike = dynamic_cast<SpikeEvent*>(ev)) {
        handleExternalSpike(spike);
        return;
    }
    noc_subsys_.onExternalPortEvent(ev);
}

void MultiCorePE::handleLoaderDoneEvent(SST::Event* ev) {
    if (!ev) return;
    auto* msg = dynamic_cast<LoaderDoneEvent*>(ev);
    if (msg) {
        // Cross-rank bridge:
        // - SharedArray(loader_done_key) 在 MPI 多 rank 下不具备运行期一致性；
        // - 该事件作为权重就绪的权威信号：MultiCorePE 侧先 latch，再镜像写入本 rank 的 SharedArray
        //   以复用 core/workload 现有 ensureLoaderReady_ 逻辑（避免引入新接口/破坏兼容）。
        loader_ready_latched_ = true;
        // current_cycle_ 仅在 clockTick() 里更新；init/setup 阶段可能尚未进入时钟。
        loader_ready_cycle_ = first_tick_logged_ ? static_cast<uint64_t>(current_cycle_) : 0;
        // 注意：SharedArray 仅允许在 init 阶段写入；跨 rank 运行期镜像写入会触发 SST fatal。
        // 因此：通过 ILoaderReadyHooks 将“就绪”信号下发到各 core 的本地 latch，避免依赖 SharedArray 的一致性。
        for (auto* core : cores_) {
            if (!core) continue;
            if (auto* hook = dynamic_cast<ILoaderReadyHooks*>(core)) {
                hook->onLoaderReady();
            }
        }
        if (sentinel_enabled_ && output_ && verbose_ >= 1) {
            output_->verbose(CALL_INFO, 1, 0,
                             "[[sentinel-step-sync]] node=%d recv LoaderDoneEvent(src_node=%u) latch loader_ready\n",
                             node_id_, msg->src_node);
        }
    }
    delete ev;
}

void MultiCorePE::handleGasStepCtrlEvent(SST::Event* ev) {
    if (!ev) return;
    if (auto* gd = dynamic_cast<GatingDecisionEvent*>(ev)) {
        const uint32_t src_global =
            static_cast<uint32_t>(gd->src_pe) * static_cast<uint32_t>(total_neurons_) + gd->src_row;
        std::vector<uint32_t> dpes = gd->dest_pes;
        for (auto* core : cores_) {
            if (!core) continue;
            auto* hooks = dynamic_cast<ICoreControlHooks*>(core);
            if (!hooks) continue;
            hooks->applyGatingDecision(src_global, dpes, current_cycle_, gd->ttl_cycles);
        }
        delete gd;
        return;
    }
    auto* msg = dynamic_cast<GasStepBarrierEvent*>(ev);
    if (!msg) {
        delete ev;
        return;
    }
    if (msg->operation() == GasStepBarrierOp::StartStep) {
        const uint32_t seq = msg->seq;
        const uint32_t active = global_step_active_seq_;
        const uint32_t pending = global_step_start_pending_ ? global_step_pending_seq_ : 0;
        const uint32_t last_seen = std::max(global_step_last_seen_seq_, std::max(active, pending));
        const uint32_t expected_next = (pending != 0) ? pending : ((active != 0) ? (active + 1u) : 0u);
        if (seq == 0) {
            global_step_start_stale_total_ += 1;
            if (output_) {
                output_->verbose(
                    CALL_INFO, 0, 0,
                    "WARN: node=%d recv START_STEP seq=0 ignored stale_total=%" PRIu64 "\n",
                    node_id_, (uint64_t)global_step_start_stale_total_);
            }
        } else if (seq == active || (pending != 0 && seq == pending)) {
            global_step_start_dup_total_ += 1;
            if (output_) {
                output_->verbose(
                    CALL_INFO, 0, 0,
                    "WARN: node=%d recv START_STEP dup seq=%" PRIu32 " active=%" PRIu32 " pending=%" PRIu32 " dup_total=%" PRIu64 "\n",
                    node_id_, seq, active, pending, (uint64_t)global_step_start_dup_total_);
            }
        } else if (last_seen != 0 && seq < last_seen) {
            global_step_start_stale_total_ += 1;
            if (output_) {
                output_->verbose(
                    CALL_INFO, 0, 0,
                    "WARN: node=%d recv START_STEP stale seq=%" PRIu32 " last_seen=%" PRIu32 " stale_total=%" PRIu64 "\n",
                    node_id_, seq, last_seen, (uint64_t)global_step_start_stale_total_);
            }
        } else {
            if (expected_next != 0 && seq > expected_next) {
                global_step_start_jump_total_ += 1;
                if (output_) {
                    output_->verbose(
                        CALL_INFO, 0, 0,
                        "WARN: node=%d recv START_STEP jump seq=%" PRIu32 " expected=%" PRIu32 " jump_total=%" PRIu64 "\n",
                        node_id_, seq, expected_next, (uint64_t)global_step_start_jump_total_);
                }
            }
            global_step_pending_seq_ = seq;
            global_step_pending_apply_bank_credit_target_ = msg->apply_bank_credit_target;
            global_step_start_pending_ = true;
            global_step_last_seen_seq_ = seq;
            if (sentinel_enabled_ && output_ && node_id_ == 0) {
                output_->verbose(CALL_INFO, 2, 0, "[[sentinel-step-sync]] node=%d recv START_STEP seq=%u\n", node_id_, seq);
            }
        }
    }
    delete msg;
}

void MultiCorePE::beginGlobalStep_(uint32_t seq) {
    global_step_active_seq_ = seq;
    global_step_active_apply_bank_credit_target_ = global_step_pending_apply_bank_credit_target_;
    global_step_pending_apply_bank_credit_target_ = 0;
    global_step_done_sent_ = false;
    global_step_begin_cycle_ = static_cast<uint64_t>(current_cycle_);
    global_step_last_activity_cycle_ = static_cast<uint64_t>(current_cycle_);
    if (global_step_done_cores_.size() != static_cast<size_t>(num_cores_)) {
        global_step_done_cores_.assign(static_cast<size_t>(num_cores_), 0);
    } else {
        std::fill(global_step_done_cores_.begin(), global_step_done_cores_.end(), 0);
    }
    if (global_step_last_stage_code_.size() != static_cast<size_t>(num_cores_)) {
        global_step_last_stage_code_.assign(static_cast<size_t>(num_cores_), 0);
        global_step_last_stage_seq_.assign(static_cast<size_t>(num_cores_), 0);
        global_step_last_stage_ts_ns_.assign(static_cast<size_t>(num_cores_), 0);
        global_step_last_stage_spikes_.assign(static_cast<size_t>(num_cores_), 0);
    } else {
        std::fill(global_step_last_stage_code_.begin(), global_step_last_stage_code_.end(), 0);
        std::fill(global_step_last_stage_seq_.begin(), global_step_last_stage_seq_.end(), 0);
        std::fill(global_step_last_stage_ts_ns_.begin(), global_step_last_stage_ts_ns_.end(), 0);
        std::fill(global_step_last_stage_spikes_.begin(), global_step_last_stage_spikes_.end(), 0);
    }

    // 全局 step 同步：先让所有 core 进入 step（打开 Gather/窗口门控），再注入本 step 的 stimulus。
    // 否则注入可能发生在 core 仍处于 Idle 时，导致 recordEdge 被 gate 掉（Idle 默认不记录），
    // 进而出现 GAS 未读全权重/Apply 仅发出少量读请求（microbench 会被严重低估）。
    for (int i = 0; i < num_cores_; ++i) {
        auto* core = cores_[i];
        if (!core) {
            output_->fatal(CALL_INFO, -1, "GlobalStep fatal: core%d is null\n", i);
            return;
        }
        if (global_step_active_apply_bank_credit_target_ > 0) {
            if (auto* credit = dynamic_cast<IGlobalStepCreditHooks*>(core)) {
                credit->onGlobalStepApplyBankCredit(seq, global_step_active_apply_bank_credit_target_);
            }
        }
        auto* hook = dynamic_cast<IGlobalStepHooks*>(core);
        if (!hook) {
            output_->fatal(CALL_INFO, -1, "GlobalStep fatal: core%d does not implement IGlobalStepHooks\n", i);
            return;
        }
        if (sentinel_enabled_ && output_ && seq <= 2) {
            output_->verbose(CALL_INFO, 2, 0, "[[sentinel-step-sync]] node=%d call onGlobalStepStart core=%d seq=%u\n", node_id_, i, seq);
        }
        hook->onGlobalStepStart(seq);
        if (sentinel_enabled_ && output_ && node_id_ == 0 && seq <= 2 && i >= 15) {
            output_->verbose(
                CALL_INFO, 2, 0,
                "[[sentinel-step-path]] node=%d core=%d seq=%u after_onGlobalStepStart\n",
                node_id_, i, seq);
        }
    }

    // naive_raw baseline：flush 上一 step 产生的“下一 step spike”，确保跨步传播但禁止步内级联。
    flushDeferredPacketsForSeq_(seq);

    // Step Random Activation：在全局 step 同步下，以 START_STEP(seq) 作为统一触发点（每 step 一次）。
    // 注意：必须在 core 进入 step 后再注入，确保所有触发的 spike 归属到本 step 的 Gather。
    step_activation_subsys_.onGlobalStepStart(seq, getCurrentSimTimeNano());

    if (sentinel_enabled_ && output_ && seq <= 2) {
        output_->verbose(CALL_INFO, 2, 0, "[[sentinel-step-sync]] node=%d beginGlobalStep seq=%u cores=%d\n", node_id_, seq, num_cores_);
    }
}

void MultiCorePE::noteStepBarrierWaitNs_(uint32_t seq, uint64_t now_ns) {
    if (seq == 0) return;
    uint64_t wait_ns = 0;
    auto it = stage_marks_.find(seq);
    if (it != stage_marks_.end()) {
        const auto& m = it->second;
        if (m.es != 0 && now_ns >= m.es) {
            wait_ns = now_ns - m.es;
        }
    }
    auto& perf = getOrCreateStepPerf_(seq);
    if (wait_ns > perf.step_barrier_wait_ns) {
        perf.step_barrier_wait_ns = wait_ns;
    }
}

void MultiCorePE::flushDeferredPacketsForSeq_(uint32_t seq) {
    if (deferred_packets_by_seq_.empty()) return;
    auto it = deferred_packets_by_seq_.find(seq);
    if (it == deferred_packets_by_seq_.end()) return;

    auto packets = std::move(it->second);
    deferred_packets_by_seq_.erase(it);

    for (auto& d : packets) {
        if (!d.pkt) continue;
        deliverPacketToEndpoint_(d.endpoint_id, d.pkt);
    }
}

void MultiCorePE::clearAllDeferredPackets_() {
    for (auto& kv : deferred_packets_by_seq_) {
        for (auto& d : kv.second) {
            delete d.pkt;
            d.pkt = nullptr;
        }
    }
    deferred_packets_by_seq_.clear();
}

void MultiCorePE::clearAllPulseIngressPackets_() {
    for (auto& kv : pulse_ingress_buffered_packets_) {
        auto& entry = kv.second;
        delete entry.pkt;
        entry.pkt = nullptr;
    }
    pulse_ingress_buffered_packets_.clear();
}

bool MultiCorePE::pulseActualIngressEnabled_() const {
    return pulse_fabric_ &&
           !pulse_fabric_->config().observe_only &&
           pulse_fabric_->config().ingress_enable &&
           pulse_fabric_->config().ingress_entries > 0;
}

bool MultiCorePE::pulseActualIngressEligible_(NocPacketKind kind) const {
    return kind == NocPacketKind::Spike ||
           kind == NocPacketKind::SpikeKey ||
           kind == NocPacketKind::SpikeTileKey;
}

void MultiCorePE::appendAtlasActivationGateStats_(
    std::map<std::string, uint64_t>& stats) const {
    const PeSharedCoreFabric::Config* pulse_cfg =
        pulse_fabric_ ? &pulse_fabric_->config() : nullptr;
    const bool pulse_osa_metadata_txn_effective =
        pulse_osa_enable_ && pulse_osa_metadata_txn_enable_;
    const bool rowindex_gate_pulse_osa =
        pulse_osa_enable_;
    const bool rowindex_gate_metadata_txn =
        pulse_osa_metadata_txn_enable_;
    const bool rowindex_gate_metadata_mask =
        (pulse_osa_metadata_object_mask_bits_ &
         PeLocalServiceObjectTable::kMetadataKindMaskRowIndex) != 0u;
    const bool rowindex_gate_pod_enable =
        pe_internal_pod_enable_cfg_;
    const bool rowindex_gate_pod_metadata_enable =
        pe_internal_pod_metadata_enable_cfg_;
    const bool rowindex_gate_pod_owner_enable =
        pe_internal_pod_owner_enable_cfg_;
    const bool rowindex_gate_service_table_present =
        pe_local_service_object_table_ != nullptr;
    const bool pulse_osa_metadata_ready_lease_effective =
        pulse_osa_metadata_txn_effective &&
        pulse_osa_metadata_ready_lease_enable_ &&
        pulse_osa_metadata_ready_lease_ttl_ > 0u &&
        pulse_osa_metadata_object_mask_bits_ != 0u &&
        pe_local_service_object_table_ != nullptr;
    const bool control_runtime_produce_eligible =
        pod_metadata_object_plane_ != nullptr &&
        pod_owner_service_table_ != nullptr &&
        pe_local_service_object_table_ != nullptr;
    const bool control_runtime_end_to_end_eligible =
        control_runtime_produce_eligible && pulse_fabric_ != nullptr;

    stats["atlas_enable_state_local_storage_effective_total"] =
        local_storage_enable_ ? 1u : 0u;
    stats["atlas_enable_state_pe_internal_cpe_effective_total"] =
        pe_internal_cpe_enable_cfg_ ? 1u : 0u;
    stats["atlas_enable_state_pe_internal_pod_effective_total"] =
        pe_internal_pod_enable_cfg_ ? 1u : 0u;
    stats["atlas_enable_state_pe_internal_pod_metadata_effective_total"] =
        pe_internal_pod_metadata_enable_cfg_ ? 1u : 0u;
    stats["atlas_enable_state_pe_internal_pod_owner_effective_total"] =
        pe_internal_pod_owner_enable_cfg_ ? 1u : 0u;
    stats["atlas_enable_state_pe_local_service_table_present_total"] =
        pe_local_service_object_table_ ? 1u : 0u;
    stats["atlas_enable_state_rowindex_effective_total"] =
        atlas_rowindex_effective_seen_ ? 1u : 0u;
    stats["atlas_enable_state_rowindex_gate_pulse_osa_total"] =
        rowindex_gate_pulse_osa ? 1u : 0u;
    stats["atlas_enable_state_rowindex_gate_metadata_txn_total"] =
        rowindex_gate_metadata_txn ? 1u : 0u;
    stats["atlas_enable_state_rowindex_gate_metadata_mask_total"] =
        rowindex_gate_metadata_mask ? 1u : 0u;
    stats["atlas_enable_state_rowindex_gate_pod_enable_total"] =
        rowindex_gate_pod_enable ? 1u : 0u;
    stats["atlas_enable_state_rowindex_gate_pod_metadata_enable_total"] =
        rowindex_gate_pod_metadata_enable ? 1u : 0u;
    stats["atlas_enable_state_rowindex_gate_pod_owner_enable_total"] =
        rowindex_gate_pod_owner_enable ? 1u : 0u;
    stats["atlas_enable_state_rowindex_gate_service_table_present_total"] =
        rowindex_gate_service_table_present ? 1u : 0u;
    stats["atlas_enable_state_pulse_effective_total"] =
        pulse_enable_ ? 1u : 0u;
    stats["atlas_enable_state_pulse_fabric_present_total"] =
        pulse_fabric_ ? 1u : 0u;
    stats["atlas_enable_state_pulse_observe_only_total"] =
        (pulse_cfg && pulse_cfg->observe_only) ? 1u : 0u;
    stats["atlas_enable_state_pulse_actual_ingress_effective_total"] =
        pulseActualIngressEnabled_() ? 1u : 0u;
    stats["atlas_enable_state_pulse_harbor_effective_total"] =
        (pulse_cfg && pulse_cfg->harbor_enable) ? 1u : 0u;
    stats["atlas_enable_state_pulse_descriptor_effective_total"] =
        (pulse_cfg && pulse_cfg->descriptor_enable) ? 1u : 0u;
    stats["atlas_enable_state_pulse_descriptor_actual_effective_total"] =
        (pulse_cfg && pulse_cfg->descriptor_actual_enable) ? 1u : 0u;
    stats["atlas_enable_state_pulse_osa_effective_total"] =
        pulse_osa_enable_ ? 1u : 0u;
    stats["atlas_enable_state_pulse_osa_shared_weight_owner_effective_total"] =
        pulse_osa_shared_weight_owner_enable_ ? 1u : 0u;
    stats["atlas_enable_state_pulse_osa_shared_weight_actual_effective_total"] =
        pulse_osa_shared_weight_owner_actual_enable_ ? 1u : 0u;
    stats["atlas_enable_state_pe_weight_plane_present_total"] =
        pe_weight_object_plane_ ? 1u : 0u;
    stats["atlas_enable_state_pulse_osa_metadata_txn_effective_total"] =
        pulse_osa_metadata_txn_effective ? 1u : 0u;
    stats["atlas_enable_state_pulse_osa_metadata_ready_lease_effective_total"] =
        pulse_osa_metadata_ready_lease_effective ? 1u : 0u;
    stats["atlas_enable_state_pulse_osa_metadata_mask_nonzero_total"] =
        pulse_osa_metadata_object_mask_bits_ != 0u ? 1u : 0u;
    stats["atlas_enable_state_control_runtime_produce_eligible_total"] =
        control_runtime_produce_eligible ? 1u : 0u;
    stats["atlas_enable_state_control_runtime_end_to_end_eligible_total"] =
        control_runtime_end_to_end_eligible ? 1u : 0u;

    stats["atlas_activation_gate_workload_pure_snn_datapath_eligible"] =
        pure_snn_datapath_workload_eligible_ ? 1u : 0u;
    stats["atlas_activation_gate_local_storage_enable"] =
        local_storage_enable_ ? 1u : 0u;
    stats["atlas_activation_gate_pulse_requested"] =
        pulse_enable_requested_ ? 1u : 0u;
    stats["atlas_activation_gate_pulse_effective"] =
        pulse_enable_ ? 1u : 0u;
    stats["atlas_activation_gate_pulse_fabric_constructed"] =
        pulse_fabric_ ? 1u : 0u;
    stats["atlas_activation_gate_pulse_observe_only_effective"] =
        (pulse_cfg && pulse_cfg->observe_only) ? 1u : 0u;
    stats["atlas_activation_gate_pulse_actual_ingress_eligible"] =
        pulseActualIngressEnabled_() ? 1u : 0u;
    stats["atlas_activation_gate_pulse_harbor_enable_effective"] =
        (pulse_cfg && pulse_cfg->harbor_enable) ? 1u : 0u;
    stats["atlas_activation_gate_pulse_descriptor_enable_effective"] =
        (pulse_cfg && pulse_cfg->descriptor_enable) ? 1u : 0u;
    stats["atlas_activation_gate_pulse_descriptor_actual_requested"] =
        pulse_descriptor_actual_requested_ ? 1u : 0u;
    stats["atlas_activation_gate_pulse_descriptor_actual_effective"] =
        (pulse_cfg && pulse_cfg->descriptor_actual_enable) ? 1u : 0u;
    stats["atlas_activation_gate_pulse_osa_requested"] =
        pulse_osa_requested_ ? 1u : 0u;
    stats["atlas_activation_gate_pulse_osa_effective"] =
        pulse_osa_enable_ ? 1u : 0u;
    stats["atlas_activation_gate_shared_weight_owner_requested"] =
        pulse_osa_shared_weight_owner_requested_ ? 1u : 0u;
    stats["atlas_activation_gate_shared_weight_owner_effective"] =
        pulse_osa_shared_weight_owner_enable_ ? 1u : 0u;
    stats["atlas_activation_gate_shared_weight_plane_constructed"] =
        pe_weight_object_plane_ ? 1u : 0u;
    stats["atlas_activation_gate_shared_weight_actual_owner_requested"] =
        pulse_osa_shared_weight_owner_actual_requested_ ? 1u : 0u;
    stats["atlas_activation_gate_shared_weight_actual_owner_effective"] =
        pulse_osa_shared_weight_owner_actual_enable_ ? 1u : 0u;
    stats["atlas_activation_gate_pe_internal_pod_requested"] =
        pe_internal_pod_requested_ ? 1u : 0u;
    stats["atlas_activation_gate_rowindex_requested"] =
        atlas_rowindex_requested_seen_ ? 1u : 0u;
    stats["atlas_activation_gate_pe_internal_pod_metadata_requested"] =
        pe_internal_pod_metadata_requested_ ? 1u : 0u;
    stats["atlas_activation_gate_pe_internal_pod_owner_requested"] =
        pe_internal_pod_owner_requested_ ? 1u : 0u;
    stats["atlas_activation_gate_rowindex_constructed"] =
        atlas_rowindex_constructed_seen_ ? 1u : 0u;
    stats["atlas_activation_gate_pod_metadata_plane_constructed"] =
        pod_metadata_object_plane_ ? 1u : 0u;
    stats["atlas_activation_gate_pod_owner_table_constructed"] =
        pod_owner_service_table_ ? 1u : 0u;
    stats["atlas_activation_gate_service_table_constructed"] =
        pe_local_service_object_table_ ? 1u : 0u;
}

void MultiCorePE::appendAtlasSharedWeightCensusStats_(
    std::map<std::string, uint64_t>& stats) const {
    bool state_absent = pe_weight_object_plane_ == nullptr;
    bool state_owner_scope_off = false;
    bool state_mirror_only = false;
    bool state_actual_owner = false;

    if (pe_weight_object_plane_) {
        const auto weight_plane_stats = pe_weight_object_plane_->snapshotStats();
        state_owner_scope_off = !weight_plane_stats.owner_scope_enable;
        state_actual_owner =
            weight_plane_stats.owner_scope_enable &&
            weight_plane_stats.actual_owner_enable;
        state_mirror_only =
            weight_plane_stats.owner_scope_enable &&
            !weight_plane_stats.actual_owner_enable;
    }

    const bool absent_reason_workload_ineligible =
        state_absent && !pure_snn_datapath_workload_eligible_;
    const bool absent_reason_local_storage_gate =
        state_absent &&
        pure_snn_datapath_workload_eligible_ &&
        !local_storage_enable_;
    const bool absent_reason_pulse_osa_gate =
        state_absent &&
        pure_snn_datapath_workload_eligible_ &&
        local_storage_enable_ &&
        !pulse_osa_enable_;
    const bool absent_reason_owner_request_gate =
        state_absent &&
        pure_snn_datapath_workload_eligible_ &&
        local_storage_enable_ &&
        pulse_osa_enable_ &&
        !pulse_osa_shared_weight_owner_requested_;

    stats["atlas_shared_weight_census_state_absent_total"] =
        state_absent ? 1u : 0u;
    stats["atlas_shared_weight_census_state_owner_scope_off_total"] =
        state_owner_scope_off ? 1u : 0u;
    stats["atlas_shared_weight_census_state_mirror_only_total"] =
        state_mirror_only ? 1u : 0u;
    stats["atlas_shared_weight_census_state_actual_owner_total"] =
        state_actual_owner ? 1u : 0u;
    stats["atlas_shared_weight_census_absent_reason_workload_ineligible_total"] =
        absent_reason_workload_ineligible ? 1u : 0u;
    stats["atlas_shared_weight_census_absent_reason_local_storage_gate_total"] =
        absent_reason_local_storage_gate ? 1u : 0u;
    stats["atlas_shared_weight_census_absent_reason_pulse_osa_gate_total"] =
        absent_reason_pulse_osa_gate ? 1u : 0u;
    stats["atlas_shared_weight_census_absent_reason_owner_request_gate_total"] =
        absent_reason_owner_request_gate ? 1u : 0u;
}

void MultiCorePE::appendAtlasControlRuntimeClassificationStats_(
    std::map<std::string, uint64_t>& stats) const {
    const bool fabric_present = pulse_fabric_ != nullptr;
    bool queued_nonzero = false;
    bool consumed_nonzero = false;
    bool backlog_nonzero = false;
    if (fabric_present) {
        const auto pulse_stats = pulse_fabric_->snapshotStats();
        queued_nonzero = pulse_stats.control_messages_enqueued_total > 0u;
        consumed_nonzero = pulse_stats.control_messages_dequeued_total > 0u;
        backlog_nonzero =
            pulse_stats.control_entries_current > 0u ||
            pulse_stats.control_entries_peak > 0u ||
            pulse_stats.control_backlog_cycles_total > 0u;
    }
    const bool all_zero =
        !atlas_control_runtime_produced_any_nonzero_last_ &&
        !queued_nonzero &&
        !consumed_nonzero &&
        !backlog_nonzero;
    const bool fabric_absent = !fabric_present;
    const bool fabric_present_idle = fabric_present && all_zero;
    const bool consumed_active = fabric_present && consumed_nonzero;
    const bool queued_without_consume =
        fabric_present &&
        !consumed_nonzero &&
        (queued_nonzero || backlog_nonzero);
    const bool produced_without_queue =
        fabric_present &&
        !consumed_nonzero &&
        !queued_nonzero &&
        !backlog_nonzero &&
        atlas_control_runtime_produced_any_nonzero_last_;

    stats["atlas_control_runtime_produced_any_nonzero_total"] =
        atlas_control_runtime_produced_any_nonzero_last_ ? 1u : 0u;
    stats["atlas_control_runtime_queued_any_nonzero_total"] =
        queued_nonzero ? 1u : 0u;
    stats["atlas_control_runtime_consumed_any_nonzero_total"] =
        consumed_nonzero ? 1u : 0u;
    stats["atlas_control_runtime_backlog_any_nonzero_total"] =
        backlog_nonzero ? 1u : 0u;
    stats["atlas_control_runtime_all_zero_total"] =
        all_zero ? 1u : 0u;
    stats["atlas_control_runtime_state_fabric_absent_total"] =
        fabric_absent ? 1u : 0u;
    stats["atlas_control_runtime_state_fabric_present_idle_total"] =
        fabric_present_idle ? 1u : 0u;
    stats["atlas_control_runtime_state_produced_without_queue_total"] =
        produced_without_queue ? 1u : 0u;
    stats["atlas_control_runtime_state_queued_without_consume_total"] =
        queued_without_consume ? 1u : 0u;
    stats["atlas_control_runtime_state_consumed_active_total"] =
        consumed_active ? 1u : 0u;
}

void MultiCorePE::drainPulseIngress_() {
    if (!pulseActualIngressEnabled_()) return;
    if (pulse_ingress_buffered_packets_.empty()) return;

    std::vector<PeSharedCoreFabric::DispatchTicket> batch;
    const size_t budget = static_cast<size_t>(std::max(1, num_cores_));
    const size_t dispatched = pulse_fabric_->collectDispatchBatch(budget, batch);
    if (dispatched == 0) return;

    for (const auto& ticket : batch) {
        auto it = pulse_ingress_buffered_packets_.find(ticket.token);
        if (it == pulse_ingress_buffered_packets_.end()) {
            pulse_fabric_->observeIngressDrain();
            continue;
        }
        PulseIngressBufferedPacket entry = std::move(it->second);
        pulse_ingress_buffered_packets_.erase(it);
        if (!entry.pkt) {
            pulse_fabric_->observeIngressDrain();
            continue;
        }
        pulse_fabric_->observeSharedDispatch();
        deliverPacketDirectToCore_(entry.endpoint_id, entry.pkt, /*pulse_account_delivery=*/true);
    }
}

void MultiCorePE::handleExternalSpike(SpikeEvent* spike) {
    external_spike_input_subsys_.onSpike(spike);
}

void MultiCorePE::sendExternalSpike(SpikeEvent* spike) {
    if (!spike) return;
    // Phase3-C：编解码/packet 化下沉到 SpikePacketBridge；NoC 仅做传输。
    spike_packet_bridge_.sendExternal(spike);
}

int MultiCorePE::determineTargetUnit(int neuron_id) const {
    // 使用global_neuron_base确定本节点管理的神经元范围
    int local_neuron_id = neuron_id - static_cast<int>(global_neuron_base_);
    
    if (local_neuron_id < 0 || local_neuron_id >= total_neurons_) {
        return -1;  // 非本MultiCorePE的神经元
    }
    
    int target_unit = local_neuron_id / neurons_per_core_;
    return (target_unit >= 0 && target_unit < num_cores_) ? target_unit : -1;
}

bool MultiCorePE::isLocalNeuron(int neuron_id) const {
    int start_id = static_cast<int>(global_neuron_base_);
    int end_id = start_id + total_neurons_;
    bool is_local = (neuron_id >= start_id && neuron_id < end_id);
    // printf("🔍 isLocalNeuron检查: 神经元%d, 范围[%d,%d), 节点%d, 结果:%s\n",
    //        neuron_id, start_id, end_id, node_id_, is_local ? "本地" : "非本地");
    // fflush(stdout);
    return is_local;
}

const ProcessingUnitState& MultiCorePE::getProcessingUnitState(int unit_id) const {
    static ProcessingUnitState empty_state;
    if (unit_id >= 0 && unit_id < num_cores_) {
        return unit_states_[unit_id];
    }
    return empty_state;
}

void MultiCorePE::getStatistics(std::map<std::string, uint64_t>& stats) const {
    stats["total_spikes_processed"] = stat_spikes_processed_->getCollectionCount();
    stats["inter_core_messages"] = stat_inter_core_messages_->getCollectionCount();
    stats["total_neurons_fired"] = stat_neurons_fired_->getCollectionCount();
    stats["external_spikes_sent"] = stat_external_spikes_sent_->getCollectionCount();
    stats["external_spikes_received"] = stat_external_spikes_received_->getCollectionCount();
    stats["current_cycle"] = current_cycle_;
    if (local_storage_controller_) {
        const auto ls_stats = local_storage_controller_->snapshotStats();
        stats["ls_objects_registered_total"] = static_cast<uint64_t>(ls_stats.objects_registered_total);
        stats["ls_objects_enabled_total"] = static_cast<uint64_t>(ls_stats.objects_enabled_total);
        stats["ls_capacity_bytes_total"] = ls_stats.capacity_bytes_total;
        stats["ls_queue_slots_total"] = ls_stats.queue_slots_total;
    }
    appendAtlasActivationGateStats_(stats);
    appendAtlasSharedWeightCensusStats_(stats);
    appendAtlasControlRuntimeClassificationStats_(stats);
    if (pod_metadata_object_plane_) {
        pod_metadata_object_plane_->exportStatsToMap(stats, "atlas_pod_metadata_");
    } else {
        PodMetadataObjectPlane disabled_plane;
        disabled_plane.exportStatsToMap(stats, "atlas_pod_metadata_");
    }
    if (pod_owner_service_table_) {
        pod_owner_service_table_->exportStatsToMap(stats, "atlas_pod_owner_");
    } else {
        PodOwnerServiceTable disabled_table;
        disabled_table.exportStatsToMap(stats, "atlas_pod_owner_");
    }
    if (pe_local_service_object_table_) {
        pe_local_service_object_table_->exportStatsToMap(stats, "atlas_service_");
    } else {
        stats["atlas_service_enabled"] = 0;
        stats["atlas_service_owner_form_total"] = 0;
        stats["atlas_service_join_live_total"] = 0;
        stats["atlas_service_join_ready_total"] = 0;
        stats["atlas_service_late_join_total"] = 0;
        stats["atlas_service_duplicate_join_total"] = 0;
        stats["atlas_service_ready_transition_total"] = 0;
        stats["atlas_service_ready_fanout_total"] = 0;
        stats["atlas_service_ready_fanout_consumers_sum"] = 0;
        stats["atlas_service_ready_fanout_consumers_peak"] = 0;
        stats["atlas_service_released_total"] = 0;
        stats["atlas_service_release_deferred_total"] = 0;
        stats["atlas_service_ready_release_total"] = 0;
        stats["atlas_service_ready_lease_hit_total"] = 0;
        stats["atlas_service_ready_lease_expired_total"] = 0;
        stats["atlas_service_potential_private_service_elide_total"] = 0;
        stats["atlas_service_active_entries_total"] = 0;
        stats["atlas_service_release_pending_active_total"] = 0;
        stats["atlas_service_atlas_obj_materialize_total"] = 0;
        stats["atlas_service_atlas_obj_publicize_total"] = 0;
        stats["atlas_service_atlas_obj_owner_form_total"] = 0;
        stats["atlas_service_atlas_obj_ready_total"] = 0;
        stats["atlas_service_atlas_obj_release_total"] = 0;
        stats["atlas_service_atlas_obj_private_only_total"] = 0;
    }
    if (pe_weight_object_plane_) {
        pe_weight_object_plane_->exportStatsToMap(stats, "pulse_osa_shared_weight_");
    } else {
        stats["pulse_osa_shared_weight_enabled"] = 0;
        stats["pulse_osa_shared_weight_owner_scope_enable"] = 0;
        stats["pulse_osa_shared_weight_actual_owner_enable"] = 0;
        stats["pulse_osa_shared_weight_idx_enabled"] = 0;
        stats["pulse_osa_shared_weight_l0_enabled"] = 0;
        stats["pulse_osa_shared_weight_l0_fill_total"] = 0;
        stats["pulse_osa_shared_weight_l0_evict_total"] = 0;
    }
    if (pulse_fabric_) {
        const auto pulse_stats = pulse_fabric_->snapshotStats();
        stats["pulse_ingress_packets_total"] = pulse_stats.ingress_packets_total;
        stats["pulse_ingress_spike_packets_total"] = pulse_stats.ingress_spike_packets_total;
        stats["pulse_ingress_spikekey_packets_total"] = pulse_stats.ingress_spikekey_packets_total;
        stats["pulse_ingress_spiketilekey_packets_total"] =
            pulse_stats.ingress_spiketilekey_packets_total;
        stats["pulse_ingress_core_dispatch_total"] = pulse_stats.ingress_core_dispatch_total;
        stats["pulse_ingress_shared_buffered_total"] = pulse_stats.ingress_shared_buffered_total;
        stats["pulse_ingress_shared_dispatch_total"] = pulse_stats.ingress_shared_dispatch_total;
        stats["pulse_ingress_direct_deliver_total"] = pulse_stats.ingress_direct_deliver_total;
        stats["pulse_ingress_bypass_total"] = pulse_stats.ingress_bypass_total;
        stats["pulse_ingress_pressure_bypass_total"] = pulse_stats.ingress_pressure_bypass_total;
        stats["pulse_ingress_singleton_bypass_total"] = pulse_stats.ingress_singleton_bypass_total;
        stats["pulse_ingress_deadline_bypass_total"] = pulse_stats.ingress_deadline_bypass_total;
        stats["pulse_ingress_pressure_cycles_total"] = pulse_stats.ingress_pressure_cycles_total;
        stats["pulse_ingress_entries_peak"] = pulse_stats.ingress_entries_peak;
        stats["pulse_control_entries_current"] = pulse_stats.control_entries_current;
        stats["pulse_control_entries_peak"] = pulse_stats.control_entries_peak;
        stats["pulse_control_backlog_cycles_total"] =
            pulse_stats.control_backlog_cycles_total;
        stats["pulse_core_queue_entries_peak"] = pulse_stats.core_queue_entries_peak;
        stats["pulse_harbor_buckets_total"] = pulse_stats.harbor_buckets_total;
        stats["pulse_harbor_packet_sum"] = pulse_stats.harbor_packet_sum;
        stats["pulse_harbor_consumer_sum"] = pulse_stats.harbor_consumer_sum;
        stats["pulse_harbor_bucket_peak"] = pulse_stats.harbor_bucket_peak;
        stats["pulse_harbor_singleton_buckets_total"] =
            pulse_stats.harbor_singleton_buckets_total;
        stats["pulse_descriptor_total"] = pulse_stats.descriptor_total;
        stats["pulse_descriptor_packet_sum"] = pulse_stats.descriptor_packet_sum;
        stats["pulse_descriptor_consumer_sum"] = pulse_stats.descriptor_consumer_sum;
        stats["pulse_descriptor_singleton_drop_total"] =
            pulse_stats.descriptor_singleton_drop_total;
        stats["pulse_control_messages_enqueued_total"] =
            pulse_stats.control_messages_enqueued_total;
        stats["pulse_control_messages_dequeued_total"] =
            pulse_stats.control_messages_dequeued_total;
        stats["pulse_control_frontier_export_total"] =
            pulse_stats.control_frontier_export_total;
        stats["pulse_control_owner_announce_total"] =
            pulse_stats.control_owner_announce_total;
        stats["pulse_control_join_request_total"] =
            pulse_stats.control_join_request_total;
        stats["pulse_control_ready_fanout_total"] =
            pulse_stats.control_ready_fanout_total;
        stats["pulse_control_join_reject_total"] =
            pulse_stats.control_join_reject_total;
    }
}

void MultiCorePE::initializeStatistics() {
    
    stat_spikes_processed_ = registerStatistic<uint64_t>("total_spikes_processed");
    stat_inter_core_messages_ = registerStatistic<uint64_t>("inter_core_messages");
    stat_l2_hits_ = registerStatistic<uint64_t>("l2_cache_hits");
    stat_l2_misses_ = registerStatistic<uint64_t>("l2_cache_misses");
    stat_memory_requests_ = registerStatistic<uint64_t>("memory_requests");
    stat_avg_utilization_ = registerStatistic<double>("avg_core_utilization");
    stat_neurons_fired_ = registerStatistic<uint64_t>("total_neurons_fired");
    stat_unique_neurons_fired_total_ = registerStatistic<uint64_t>("unique_neurons_fired_total");
    stat_external_spikes_sent_ = registerStatistic<uint64_t>("external_spikes_sent");
    stat_external_spikes_received_ = registerStatistic<uint64_t>("external_spikes_received");
    // Experiment profile observability counters (do not change behavior)
    stat_compat_unexpected_stream_activity_total_ = registerStatistic<uint64_t>("compat_unexpected_stream_activity_total");
    stat_compat_naive_gas_stage_events_total_ = registerStatistic<uint64_t>("compat_naive_gas_stage_events_total");
    stat_compat_finish_incomplete_total_ = registerStatistic<uint64_t>("compat_finish_incomplete_total");
    stat_loader_done_timeout_fallback_total_ = registerStatistic<uint64_t>("loader_done_timeout_fallback_total");
    stat_dma_issue_reqs_total_ = registerStatistic<uint64_t>("dma_issue_reqs_total");
    stat_dma_issue_bytes_total_ = registerStatistic<uint64_t>("dma_issue_bytes_total");
    stat_dma_queue_depth_max_p0_ = registerStatistic<uint64_t>("dma_queue_depth_max_p0");
    stat_dma_queue_depth_max_p1_ = registerStatistic<uint64_t>("dma_queue_depth_max_p1");
    stat_dma_queue_depth_max_p2_ = registerStatistic<uint64_t>("dma_queue_depth_max_p2");
    stat_dma_queue_depth_max_p3_ = registerStatistic<uint64_t>("dma_queue_depth_max_p3");
    stat_dma_inflight_max_ = registerStatistic<uint64_t>("dma_inflight_max");
    stat_dma_stall_cycles_budget_ = registerStatistic<uint64_t>("dma_stall_cycles_budget");
    stat_dma_stall_cycles_engine_ = registerStatistic<uint64_t>("dma_stall_cycles_engine");
    stat_dma_stall_cycles_inflight_ = registerStatistic<uint64_t>("dma_stall_cycles_inflight");
    stat_dma_stall_cycles_stage_gate_ = registerStatistic<uint64_t>("dma_stall_cycles_stage_gate");
    stat_dma_stall_cycles_queue_full_ = registerStatistic<uint64_t>("dma_stall_cycles_queue_full");
    stat_ls_objects_registered_total_ = registerStatistic<uint64_t>("ls_objects_registered_total");
    stat_ls_objects_enabled_total_ = registerStatistic<uint64_t>("ls_objects_enabled_total");
    stat_ls_capacity_bytes_total_ = registerStatistic<uint64_t>("ls_capacity_bytes_total");
    stat_ls_queue_slots_total_ = registerStatistic<uint64_t>("ls_queue_slots_total");
    stat_atlas_service_enabled_ =
        registerStatistic<uint64_t>("atlas_service_enabled");
    stat_atlas_service_owner_form_total_ =
        registerStatistic<uint64_t>("atlas_service_owner_form_total");
    stat_atlas_service_join_live_total_ =
        registerStatistic<uint64_t>("atlas_service_join_live_total");
    stat_atlas_service_join_ready_total_ =
        registerStatistic<uint64_t>("atlas_service_join_ready_total");
    stat_atlas_service_late_join_total_ =
        registerStatistic<uint64_t>("atlas_service_late_join_total");
    stat_atlas_service_duplicate_join_total_ =
        registerStatistic<uint64_t>("atlas_service_duplicate_join_total");
    stat_atlas_service_ready_transition_total_ =
        registerStatistic<uint64_t>("atlas_service_ready_transition_total");
    stat_atlas_service_ready_fanout_total_ =
        registerStatistic<uint64_t>("atlas_service_ready_fanout_total");
    stat_atlas_service_ready_fanout_consumers_sum_ =
        registerStatistic<uint64_t>("atlas_service_ready_fanout_consumers_sum");
    stat_atlas_service_ready_fanout_consumers_peak_ =
        registerStatistic<uint64_t>("atlas_service_ready_fanout_consumers_peak");
    stat_atlas_service_released_total_ =
        registerStatistic<uint64_t>("atlas_service_released_total");
    stat_atlas_service_release_deferred_total_ =
        registerStatistic<uint64_t>("atlas_service_release_deferred_total");
    stat_atlas_service_ready_release_total_ =
        registerStatistic<uint64_t>("atlas_service_ready_release_total");
    stat_atlas_service_ready_lease_hit_total_ =
        registerStatistic<uint64_t>("atlas_service_ready_lease_hit_total");
    stat_atlas_service_ready_lease_expired_total_ =
        registerStatistic<uint64_t>("atlas_service_ready_lease_expired_total");
    stat_atlas_service_potential_private_service_elide_total_ =
        registerStatistic<uint64_t>("atlas_service_potential_private_service_elide_total");
    stat_atlas_service_active_entries_total_ =
        registerStatistic<uint64_t>("atlas_service_active_entries_total");
    stat_atlas_service_release_pending_active_total_ =
        registerStatistic<uint64_t>("atlas_service_release_pending_active_total");
    stat_atlas_service_atlas_obj_materialize_total_ =
        registerStatistic<uint64_t>("atlas_service_atlas_obj_materialize_total");
    stat_atlas_service_atlas_obj_publicize_total_ =
        registerStatistic<uint64_t>("atlas_service_atlas_obj_publicize_total");
    stat_atlas_service_atlas_obj_owner_form_total_ =
        registerStatistic<uint64_t>("atlas_service_atlas_obj_owner_form_total");
    stat_atlas_service_atlas_obj_ready_total_ =
        registerStatistic<uint64_t>("atlas_service_atlas_obj_ready_total");
    stat_atlas_service_atlas_obj_release_total_ =
        registerStatistic<uint64_t>("atlas_service_atlas_obj_release_total");
    stat_atlas_service_atlas_obj_private_only_total_ =
        registerStatistic<uint64_t>("atlas_service_atlas_obj_private_only_total");
    atlas_object_plane_stats_["atlas_pod_metadata_enabled"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_enabled");
    atlas_object_plane_stats_["atlas_pod_metadata_observe_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_observe_total");
    atlas_object_plane_stats_["atlas_pod_metadata_unique_object_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_unique_object_total");
    atlas_object_plane_stats_["atlas_pod_metadata_overlap_hit_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_overlap_hit_total");
    atlas_object_plane_stats_["atlas_pod_metadata_duplicate_consumer_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_duplicate_consumer_total");
    atlas_object_plane_stats_["atlas_pod_metadata_evict_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_evict_total");
    atlas_object_plane_stats_["atlas_pod_metadata_active_entries_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_active_entries_total");
    atlas_object_plane_stats_["atlas_pod_metadata_active_entries_peak_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_active_entries_peak_total");
    atlas_object_plane_stats_["atlas_pod_metadata_premphf_base_observe_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_premphf_base_observe_total");
    atlas_object_plane_stats_["atlas_pod_metadata_premphf_base_unique_object_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_premphf_base_unique_object_total");
    atlas_object_plane_stats_["atlas_pod_metadata_premphf_base_overlap_hit_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_premphf_base_overlap_hit_total");
    atlas_object_plane_stats_["atlas_pod_metadata_premphf_base_duplicate_consumer_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_premphf_base_duplicate_consumer_total");
    atlas_object_plane_stats_["atlas_pod_metadata_premphf_base_evict_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_premphf_base_evict_total");
    atlas_object_plane_stats_["atlas_pod_metadata_premphf_base_active_entries_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_premphf_base_active_entries_total");
    atlas_object_plane_stats_["atlas_pod_metadata_premphf_base_active_entries_peak_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_premphf_base_active_entries_peak_total");
    atlas_object_plane_stats_["atlas_pod_metadata_premphf_band_observe_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_premphf_band_observe_total");
    atlas_object_plane_stats_["atlas_pod_metadata_premphf_band_unique_object_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_premphf_band_unique_object_total");
    atlas_object_plane_stats_["atlas_pod_metadata_premphf_band_overlap_hit_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_premphf_band_overlap_hit_total");
    atlas_object_plane_stats_["atlas_pod_metadata_premphf_band_duplicate_consumer_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_premphf_band_duplicate_consumer_total");
    atlas_object_plane_stats_["atlas_pod_metadata_premphf_band_evict_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_premphf_band_evict_total");
    atlas_object_plane_stats_["atlas_pod_metadata_premphf_band_active_entries_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_premphf_band_active_entries_total");
    atlas_object_plane_stats_["atlas_pod_metadata_premphf_band_active_entries_peak_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_premphf_band_active_entries_peak_total");
    atlas_object_plane_stats_["atlas_pod_metadata_idx2row_observe_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_idx2row_observe_total");
    atlas_object_plane_stats_["atlas_pod_metadata_idx2row_unique_object_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_idx2row_unique_object_total");
    atlas_object_plane_stats_["atlas_pod_metadata_idx2row_overlap_hit_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_idx2row_overlap_hit_total");
    atlas_object_plane_stats_["atlas_pod_metadata_idx2row_duplicate_consumer_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_idx2row_duplicate_consumer_total");
    atlas_object_plane_stats_["atlas_pod_metadata_idx2row_evict_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_idx2row_evict_total");
    atlas_object_plane_stats_["atlas_pod_metadata_idx2row_active_entries_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_idx2row_active_entries_total");
    atlas_object_plane_stats_["atlas_pod_metadata_idx2row_active_entries_peak_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_idx2row_active_entries_peak_total");
    atlas_object_plane_stats_["atlas_pod_metadata_rowindex_observe_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_rowindex_observe_total");
    atlas_object_plane_stats_["atlas_pod_metadata_rowindex_unique_object_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_rowindex_unique_object_total");
    atlas_object_plane_stats_["atlas_pod_metadata_rowindex_overlap_hit_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_rowindex_overlap_hit_total");
    atlas_object_plane_stats_["atlas_pod_metadata_rowindex_duplicate_consumer_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_rowindex_duplicate_consumer_total");
    atlas_object_plane_stats_["atlas_pod_metadata_rowindex_evict_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_rowindex_evict_total");
    atlas_object_plane_stats_["atlas_pod_metadata_rowindex_active_entries_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_rowindex_active_entries_total");
    atlas_object_plane_stats_["atlas_pod_metadata_rowindex_active_entries_peak_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_rowindex_active_entries_peak_total");
    atlas_object_plane_stats_["atlas_pod_metadata_rowdescriptor_observe_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_rowdescriptor_observe_total");
    atlas_object_plane_stats_["atlas_pod_metadata_rowdescriptor_unique_object_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_rowdescriptor_unique_object_total");
    atlas_object_plane_stats_["atlas_pod_metadata_rowdescriptor_overlap_hit_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_rowdescriptor_overlap_hit_total");
    atlas_object_plane_stats_["atlas_pod_metadata_rowdescriptor_duplicate_consumer_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_rowdescriptor_duplicate_consumer_total");
    atlas_object_plane_stats_["atlas_pod_metadata_rowdescriptor_evict_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_rowdescriptor_evict_total");
    atlas_object_plane_stats_["atlas_pod_metadata_rowdescriptor_active_entries_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_rowdescriptor_active_entries_total");
    atlas_object_plane_stats_["atlas_pod_metadata_rowdescriptor_active_entries_peak_total"] =
        registerStatistic<uint64_t>("atlas_pod_metadata_rowdescriptor_active_entries_peak_total");
    atlas_object_plane_stats_["atlas_pod_owner_enabled"] =
        registerStatistic<uint64_t>("atlas_pod_owner_enabled");
    atlas_object_plane_stats_["atlas_pod_owner_lookup_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_lookup_total");
    atlas_object_plane_stats_["atlas_pod_owner_owner_alloc_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_owner_alloc_total");
    atlas_object_plane_stats_["atlas_pod_owner_owner_hit_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_owner_hit_total");
    atlas_object_plane_stats_["atlas_pod_owner_owner_reject_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_owner_reject_total");
    atlas_object_plane_stats_["atlas_pod_owner_join_request_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_join_request_total");
    atlas_object_plane_stats_["atlas_pod_owner_join_grant_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_join_grant_total");
    atlas_object_plane_stats_["atlas_pod_owner_join_reject_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_join_reject_total");
    atlas_object_plane_stats_["atlas_pod_owner_active_entries_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_active_entries_total");
    atlas_object_plane_stats_["atlas_pod_owner_active_entries_peak_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_active_entries_peak_total");
    atlas_object_plane_stats_["atlas_pod_owner_premphf_base_owner_alloc_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_premphf_base_owner_alloc_total");
    atlas_object_plane_stats_["atlas_pod_owner_premphf_base_owner_hit_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_premphf_base_owner_hit_total");
    atlas_object_plane_stats_["atlas_pod_owner_premphf_base_owner_reject_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_premphf_base_owner_reject_total");
    atlas_object_plane_stats_["atlas_pod_owner_premphf_base_join_request_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_premphf_base_join_request_total");
    atlas_object_plane_stats_["atlas_pod_owner_premphf_base_join_grant_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_premphf_base_join_grant_total");
    atlas_object_plane_stats_["atlas_pod_owner_premphf_base_join_reject_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_premphf_base_join_reject_total");
    atlas_object_plane_stats_["atlas_pod_owner_premphf_base_active_entries_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_premphf_base_active_entries_total");
    atlas_object_plane_stats_["atlas_pod_owner_premphf_base_active_entries_peak_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_premphf_base_active_entries_peak_total");
    atlas_object_plane_stats_["atlas_pod_owner_premphf_band_owner_alloc_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_premphf_band_owner_alloc_total");
    atlas_object_plane_stats_["atlas_pod_owner_premphf_band_owner_hit_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_premphf_band_owner_hit_total");
    atlas_object_plane_stats_["atlas_pod_owner_premphf_band_owner_reject_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_premphf_band_owner_reject_total");
    atlas_object_plane_stats_["atlas_pod_owner_premphf_band_join_request_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_premphf_band_join_request_total");
    atlas_object_plane_stats_["atlas_pod_owner_premphf_band_join_grant_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_premphf_band_join_grant_total");
    atlas_object_plane_stats_["atlas_pod_owner_premphf_band_join_reject_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_premphf_band_join_reject_total");
    atlas_object_plane_stats_["atlas_pod_owner_premphf_band_active_entries_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_premphf_band_active_entries_total");
    atlas_object_plane_stats_["atlas_pod_owner_premphf_band_active_entries_peak_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_premphf_band_active_entries_peak_total");
    atlas_object_plane_stats_["atlas_pod_owner_idx2row_owner_alloc_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_idx2row_owner_alloc_total");
    atlas_object_plane_stats_["atlas_pod_owner_idx2row_owner_hit_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_idx2row_owner_hit_total");
    atlas_object_plane_stats_["atlas_pod_owner_idx2row_owner_reject_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_idx2row_owner_reject_total");
    atlas_object_plane_stats_["atlas_pod_owner_idx2row_join_request_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_idx2row_join_request_total");
    atlas_object_plane_stats_["atlas_pod_owner_idx2row_join_grant_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_idx2row_join_grant_total");
    atlas_object_plane_stats_["atlas_pod_owner_idx2row_join_reject_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_idx2row_join_reject_total");
    atlas_object_plane_stats_["atlas_pod_owner_idx2row_active_entries_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_idx2row_active_entries_total");
    atlas_object_plane_stats_["atlas_pod_owner_idx2row_active_entries_peak_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_idx2row_active_entries_peak_total");
    atlas_object_plane_stats_["atlas_pod_owner_rowindex_owner_alloc_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_rowindex_owner_alloc_total");
    atlas_object_plane_stats_["atlas_pod_owner_rowindex_owner_hit_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_rowindex_owner_hit_total");
    atlas_object_plane_stats_["atlas_pod_owner_rowindex_owner_reject_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_rowindex_owner_reject_total");
    atlas_object_plane_stats_["atlas_pod_owner_rowindex_join_request_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_rowindex_join_request_total");
    atlas_object_plane_stats_["atlas_pod_owner_rowindex_join_grant_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_rowindex_join_grant_total");
    atlas_object_plane_stats_["atlas_pod_owner_rowindex_join_reject_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_rowindex_join_reject_total");
    atlas_object_plane_stats_["atlas_pod_owner_rowindex_active_entries_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_rowindex_active_entries_total");
    atlas_object_plane_stats_["atlas_pod_owner_rowindex_active_entries_peak_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_rowindex_active_entries_peak_total");
    atlas_object_plane_stats_["atlas_pod_owner_rowdescriptor_owner_alloc_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_rowdescriptor_owner_alloc_total");
    atlas_object_plane_stats_["atlas_pod_owner_rowdescriptor_owner_hit_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_rowdescriptor_owner_hit_total");
    atlas_object_plane_stats_["atlas_pod_owner_rowdescriptor_owner_reject_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_rowdescriptor_owner_reject_total");
    atlas_object_plane_stats_["atlas_pod_owner_rowdescriptor_join_request_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_rowdescriptor_join_request_total");
    atlas_object_plane_stats_["atlas_pod_owner_rowdescriptor_join_grant_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_rowdescriptor_join_grant_total");
    atlas_object_plane_stats_["atlas_pod_owner_rowdescriptor_join_reject_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_rowdescriptor_join_reject_total");
    atlas_object_plane_stats_["atlas_pod_owner_rowdescriptor_active_entries_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_rowdescriptor_active_entries_total");
    atlas_object_plane_stats_["atlas_pod_owner_rowdescriptor_active_entries_peak_total"] =
        registerStatistic<uint64_t>("atlas_pod_owner_rowdescriptor_active_entries_peak_total");
    atlas_object_plane_stats_["atlas_census_premphf_base_frontier_events_total"] =
        registerStatistic<uint64_t>("atlas_census_premphf_base_frontier_events_total");
    atlas_object_plane_stats_["atlas_census_premphf_base_producer_events_total"] =
        registerStatistic<uint64_t>("atlas_census_premphf_base_producer_events_total");
    atlas_object_plane_stats_["atlas_census_premphf_base_gate_events_total"] =
        registerStatistic<uint64_t>("atlas_census_premphf_base_gate_events_total");
    atlas_object_plane_stats_["atlas_census_premphf_base_service_events_total"] =
        registerStatistic<uint64_t>("atlas_census_premphf_base_service_events_total");
    atlas_object_plane_stats_["atlas_census_premphf_band_frontier_events_total"] =
        registerStatistic<uint64_t>("atlas_census_premphf_band_frontier_events_total");
    atlas_object_plane_stats_["atlas_census_premphf_band_producer_events_total"] =
        registerStatistic<uint64_t>("atlas_census_premphf_band_producer_events_total");
    atlas_object_plane_stats_["atlas_census_premphf_band_gate_events_total"] =
        registerStatistic<uint64_t>("atlas_census_premphf_band_gate_events_total");
    atlas_object_plane_stats_["atlas_census_premphf_band_service_events_total"] =
        registerStatistic<uint64_t>("atlas_census_premphf_band_service_events_total");
    atlas_object_plane_stats_["atlas_census_idx2row_frontier_events_total"] =
        registerStatistic<uint64_t>("atlas_census_idx2row_frontier_events_total");
    atlas_object_plane_stats_["atlas_census_idx2row_producer_events_total"] =
        registerStatistic<uint64_t>("atlas_census_idx2row_producer_events_total");
    atlas_object_plane_stats_["atlas_census_idx2row_gate_events_total"] =
        registerStatistic<uint64_t>("atlas_census_idx2row_gate_events_total");
    atlas_object_plane_stats_["atlas_census_idx2row_service_events_total"] =
        registerStatistic<uint64_t>("atlas_census_idx2row_service_events_total");
    atlas_object_plane_stats_["atlas_census_rowindex_frontier_events_total"] =
        registerStatistic<uint64_t>("atlas_census_rowindex_frontier_events_total");
    atlas_object_plane_stats_["atlas_census_rowindex_producer_events_total"] =
        registerStatistic<uint64_t>("atlas_census_rowindex_producer_events_total");
    atlas_object_plane_stats_["atlas_census_rowindex_gate_events_total"] =
        registerStatistic<uint64_t>("atlas_census_rowindex_gate_events_total");
    atlas_object_plane_stats_["atlas_census_rowindex_service_events_total"] =
        registerStatistic<uint64_t>("atlas_census_rowindex_service_events_total");
    atlas_object_plane_stats_["atlas_census_rowdescriptor_frontier_events_total"] =
        registerStatistic<uint64_t>("atlas_census_rowdescriptor_frontier_events_total");
    atlas_object_plane_stats_["atlas_census_rowdescriptor_producer_events_total"] =
        registerStatistic<uint64_t>("atlas_census_rowdescriptor_producer_events_total");
    atlas_object_plane_stats_["atlas_census_rowdescriptor_gate_events_total"] =
        registerStatistic<uint64_t>("atlas_census_rowdescriptor_gate_events_total");
    atlas_object_plane_stats_["atlas_census_rowdescriptor_service_events_total"] =
        registerStatistic<uint64_t>("atlas_census_rowdescriptor_service_events_total");
    atlas_object_plane_stats_["atlas_proxy_idx2row_materialize_total"] =
        registerStatistic<uint64_t>("atlas_proxy_idx2row_materialize_total");
    atlas_object_plane_stats_["atlas_proxy_idx2row_publicize_total"] =
        registerStatistic<uint64_t>("atlas_proxy_idx2row_publicize_total");
    atlas_object_plane_stats_["atlas_proxy_idx2row_owner_form_total"] =
        registerStatistic<uint64_t>("atlas_proxy_idx2row_owner_form_total");
    atlas_object_plane_stats_["atlas_proxy_idx2row_join_live_total"] =
        registerStatistic<uint64_t>("atlas_proxy_idx2row_join_live_total");
    atlas_object_plane_stats_["atlas_proxy_idx2row_join_ready_total"] =
        registerStatistic<uint64_t>("atlas_proxy_idx2row_join_ready_total");
    atlas_object_plane_stats_["atlas_proxy_idx2row_ready_total"] =
        registerStatistic<uint64_t>("atlas_proxy_idx2row_ready_total");
    atlas_object_plane_stats_["atlas_proxy_idx2row_release_total"] =
        registerStatistic<uint64_t>("atlas_proxy_idx2row_release_total");
    atlas_object_plane_stats_["atlas_proxy_idx2row_release_missing_total"] =
        registerStatistic<uint64_t>("atlas_proxy_idx2row_release_missing_total");
    atlas_object_plane_stats_["atlas_proxy_idx2row_fallback_total"] =
        registerStatistic<uint64_t>("atlas_proxy_idx2row_fallback_total");
    atlas_object_plane_stats_["atlas_proxy_premphf_base_materialize_total"] =
        registerStatistic<uint64_t>("atlas_proxy_premphf_base_materialize_total");
    atlas_object_plane_stats_["atlas_proxy_premphf_base_publicize_total"] =
        registerStatistic<uint64_t>("atlas_proxy_premphf_base_publicize_total");
    atlas_object_plane_stats_["atlas_proxy_premphf_base_owner_form_total"] =
        registerStatistic<uint64_t>("atlas_proxy_premphf_base_owner_form_total");
    atlas_object_plane_stats_["atlas_proxy_premphf_base_shared_hit_total"] =
        registerStatistic<uint64_t>("atlas_proxy_premphf_base_shared_hit_total");
    atlas_object_plane_stats_["atlas_proxy_premphf_base_lookup_ready_total"] =
        registerStatistic<uint64_t>("atlas_proxy_premphf_base_lookup_ready_total");
    atlas_object_plane_stats_["atlas_proxy_premphf_base_proxy_only_gap_total"] =
        registerStatistic<uint64_t>("atlas_proxy_premphf_base_proxy_only_gap_total");
    atlas_object_plane_stats_["atlas_proxy_premphf_band_materialize_total"] =
        registerStatistic<uint64_t>("atlas_proxy_premphf_band_materialize_total");
    atlas_object_plane_stats_["atlas_proxy_premphf_band_publicize_total"] =
        registerStatistic<uint64_t>("atlas_proxy_premphf_band_publicize_total");
    atlas_object_plane_stats_["atlas_proxy_premphf_band_owner_form_candidate_total"] =
        registerStatistic<uint64_t>("atlas_proxy_premphf_band_owner_form_candidate_total");
    atlas_object_plane_stats_["atlas_proxy_premphf_band_join_ready_candidate_total"] =
        registerStatistic<uint64_t>("atlas_proxy_premphf_band_join_ready_candidate_total");
    atlas_object_plane_stats_["atlas_proxy_premphf_band_zero_service_total"] =
        registerStatistic<uint64_t>("atlas_proxy_premphf_band_zero_service_total");
    atlas_object_plane_stats_["atlas_proxy_rowindex_materialize_total"] =
        registerStatistic<uint64_t>("atlas_proxy_rowindex_materialize_total");
    atlas_object_plane_stats_["atlas_proxy_rowindex_publicize_total"] =
        registerStatistic<uint64_t>("atlas_proxy_rowindex_publicize_total");
    atlas_object_plane_stats_["atlas_proxy_rowindex_owner_form_total"] =
        registerStatistic<uint64_t>("atlas_proxy_rowindex_owner_form_total");
    atlas_object_plane_stats_["atlas_proxy_rowindex_join_live_total"] =
        registerStatistic<uint64_t>("atlas_proxy_rowindex_join_live_total");
    atlas_object_plane_stats_["atlas_proxy_rowindex_join_ready_total"] =
        registerStatistic<uint64_t>("atlas_proxy_rowindex_join_ready_total");
    atlas_object_plane_stats_["atlas_proxy_rowindex_ready_total"] =
        registerStatistic<uint64_t>("atlas_proxy_rowindex_ready_total");
    atlas_object_plane_stats_["atlas_proxy_rowindex_release_total"] =
        registerStatistic<uint64_t>("atlas_proxy_rowindex_release_total");
    atlas_object_plane_stats_["atlas_proxy_rowindex_release_missing_total"] =
        registerStatistic<uint64_t>("atlas_proxy_rowindex_release_missing_total");
    atlas_object_plane_stats_["atlas_proxy_rowindex_fallback_total"] =
        registerStatistic<uint64_t>("atlas_proxy_rowindex_fallback_total");
    atlas_object_plane_stats_["atlas_phase_local_begin_gather_total"] =
        registerStatistic<uint64_t>("atlas_phase_local_begin_gather_total");
    atlas_object_plane_stats_["atlas_phase_local_first_touch_after_gather_open_total"] =
        registerStatistic<uint64_t>("atlas_phase_local_first_touch_after_gather_open_total");
    atlas_object_plane_stats_["atlas_phase_local_touch_without_gather_open_total"] =
        registerStatistic<uint64_t>("atlas_phase_local_touch_without_gather_open_total");
    atlas_object_plane_stats_["atlas_phase_local_touch_during_apply_total"] =
        registerStatistic<uint64_t>("atlas_phase_local_touch_during_apply_total");
    atlas_object_plane_stats_["atlas_phase_local_begin_apply_total"] =
        registerStatistic<uint64_t>("atlas_phase_local_begin_apply_total");
    atlas_object_plane_stats_["atlas_phase_local_begin_apply_with_touch_total"] =
        registerStatistic<uint64_t>("atlas_phase_local_begin_apply_with_touch_total");
    atlas_object_plane_stats_["atlas_phase_local_begin_apply_with_pending_rowidx_total"] =
        registerStatistic<uint64_t>("atlas_phase_local_begin_apply_with_pending_rowidx_total");
    atlas_object_plane_stats_["atlas_phase_local_begin_apply_without_pending_rowidx_total"] =
        registerStatistic<uint64_t>("atlas_phase_local_begin_apply_without_pending_rowidx_total");
    atlas_object_plane_stats_["atlas_phase_local_end_scatter_total"] =
        registerStatistic<uint64_t>("atlas_phase_local_end_scatter_total");
    atlas_object_plane_stats_["atlas_storage_map_shared_owner_scope_enable"] =
        registerStatistic<uint64_t>("atlas_storage_map_shared_owner_scope_enable");
    atlas_object_plane_stats_["atlas_storage_map_shared_actual_owner_enable"] =
        registerStatistic<uint64_t>("atlas_storage_map_shared_actual_owner_enable");
    atlas_object_plane_stats_["atlas_storage_map_weight_idx_shared_enabled"] =
        registerStatistic<uint64_t>("atlas_storage_map_weight_idx_shared_enabled");
    atlas_object_plane_stats_["atlas_storage_map_weight_value_shared_enabled"] =
        registerStatistic<uint64_t>("atlas_storage_map_weight_value_shared_enabled");
    atlas_object_plane_stats_["atlas_storage_map_weight_idx_private_authority_total"] =
        registerStatistic<uint64_t>("atlas_storage_map_weight_idx_private_authority_total");
    atlas_object_plane_stats_["atlas_storage_map_weight_idx_shared_mirror_only_total"] =
        registerStatistic<uint64_t>("atlas_storage_map_weight_idx_shared_mirror_only_total");
    atlas_object_plane_stats_["atlas_storage_map_weight_idx_shared_authority_active_total"] =
        registerStatistic<uint64_t>("atlas_storage_map_weight_idx_shared_authority_active_total");
    atlas_object_plane_stats_["atlas_storage_map_weight_value_private_authority_total"] =
        registerStatistic<uint64_t>("atlas_storage_map_weight_value_private_authority_total");
    atlas_object_plane_stats_["atlas_storage_map_weight_value_shared_mirror_only_total"] =
        registerStatistic<uint64_t>("atlas_storage_map_weight_value_shared_mirror_only_total");
    atlas_object_plane_stats_["atlas_storage_map_weight_value_shared_authority_active_total"] =
        registerStatistic<uint64_t>("atlas_storage_map_weight_value_shared_authority_active_total");
    atlas_object_plane_stats_["atlas_storage_map_weight_idx_private_reads_total"] =
        registerStatistic<uint64_t>("atlas_storage_map_weight_idx_private_reads_total");
    atlas_object_plane_stats_["atlas_storage_map_weight_idx_shared_reads_total"] =
        registerStatistic<uint64_t>("atlas_storage_map_weight_idx_shared_reads_total");
    atlas_object_plane_stats_["atlas_storage_map_weight_idx_private_resident_bytes_peak"] =
        registerStatistic<uint64_t>("atlas_storage_map_weight_idx_private_resident_bytes_peak");
    atlas_object_plane_stats_["atlas_storage_map_weight_idx_shared_resident_bytes_peak"] =
        registerStatistic<uint64_t>("atlas_storage_map_weight_idx_shared_resident_bytes_peak");
    atlas_object_plane_stats_["atlas_storage_map_weight_value_private_reads_total"] =
        registerStatistic<uint64_t>("atlas_storage_map_weight_value_private_reads_total");
    atlas_object_plane_stats_["atlas_storage_map_weight_value_shared_reads_total"] =
        registerStatistic<uint64_t>("atlas_storage_map_weight_value_shared_reads_total");
    atlas_object_plane_stats_["atlas_storage_map_weight_value_private_resident_bytes_peak"] =
        registerStatistic<uint64_t>("atlas_storage_map_weight_value_private_resident_bytes_peak");
    atlas_object_plane_stats_["atlas_storage_map_weight_value_shared_resident_bytes_peak"] =
        registerStatistic<uint64_t>("atlas_storage_map_weight_value_shared_resident_bytes_peak");
    atlas_object_plane_stats_["atlas_shared_weight_census_state_absent_total"] =
        registerStatistic<uint64_t>("atlas_shared_weight_census_state_absent_total");
    atlas_object_plane_stats_["atlas_shared_weight_census_state_owner_scope_off_total"] =
        registerStatistic<uint64_t>("atlas_shared_weight_census_state_owner_scope_off_total");
    atlas_object_plane_stats_["atlas_shared_weight_census_state_mirror_only_total"] =
        registerStatistic<uint64_t>("atlas_shared_weight_census_state_mirror_only_total");
    atlas_object_plane_stats_["atlas_shared_weight_census_state_actual_owner_total"] =
        registerStatistic<uint64_t>("atlas_shared_weight_census_state_actual_owner_total");
    atlas_object_plane_stats_["atlas_shared_weight_census_absent_reason_workload_ineligible_total"] =
        registerStatistic<uint64_t>("atlas_shared_weight_census_absent_reason_workload_ineligible_total");
    atlas_object_plane_stats_["atlas_shared_weight_census_absent_reason_local_storage_gate_total"] =
        registerStatistic<uint64_t>("atlas_shared_weight_census_absent_reason_local_storage_gate_total");
    atlas_object_plane_stats_["atlas_shared_weight_census_absent_reason_pulse_osa_gate_total"] =
        registerStatistic<uint64_t>("atlas_shared_weight_census_absent_reason_pulse_osa_gate_total");
    atlas_object_plane_stats_["atlas_shared_weight_census_absent_reason_owner_request_gate_total"] =
        registerStatistic<uint64_t>("atlas_shared_weight_census_absent_reason_owner_request_gate_total");
    atlas_object_plane_stats_["atlas_control_runtime_produced_frontier_export_total"] =
        registerStatistic<uint64_t>("atlas_control_runtime_produced_frontier_export_total");
    atlas_object_plane_stats_["atlas_control_runtime_produced_owner_announce_total"] =
        registerStatistic<uint64_t>("atlas_control_runtime_produced_owner_announce_total");
    atlas_object_plane_stats_["atlas_control_runtime_produced_join_request_total"] =
        registerStatistic<uint64_t>("atlas_control_runtime_produced_join_request_total");
    atlas_object_plane_stats_["atlas_control_runtime_produced_ready_fanout_total"] =
        registerStatistic<uint64_t>("atlas_control_runtime_produced_ready_fanout_total");
    atlas_object_plane_stats_["atlas_control_runtime_produced_join_reject_total"] =
        registerStatistic<uint64_t>("atlas_control_runtime_produced_join_reject_total");
    atlas_object_plane_stats_["atlas_control_runtime_queued_frontier_export_total"] =
        registerStatistic<uint64_t>("atlas_control_runtime_queued_frontier_export_total");
    atlas_object_plane_stats_["atlas_control_runtime_queued_owner_announce_total"] =
        registerStatistic<uint64_t>("atlas_control_runtime_queued_owner_announce_total");
    atlas_object_plane_stats_["atlas_control_runtime_queued_join_request_total"] =
        registerStatistic<uint64_t>("atlas_control_runtime_queued_join_request_total");
    atlas_object_plane_stats_["atlas_control_runtime_queued_ready_fanout_total"] =
        registerStatistic<uint64_t>("atlas_control_runtime_queued_ready_fanout_total");
    atlas_object_plane_stats_["atlas_control_runtime_queued_join_reject_total"] =
        registerStatistic<uint64_t>("atlas_control_runtime_queued_join_reject_total");
    atlas_object_plane_stats_["atlas_control_runtime_consumed_frontier_export_total"] =
        registerStatistic<uint64_t>("atlas_control_runtime_consumed_frontier_export_total");
    atlas_object_plane_stats_["atlas_control_runtime_consumed_owner_announce_total"] =
        registerStatistic<uint64_t>("atlas_control_runtime_consumed_owner_announce_total");
    atlas_object_plane_stats_["atlas_control_runtime_consumed_join_request_total"] =
        registerStatistic<uint64_t>("atlas_control_runtime_consumed_join_request_total");
    atlas_object_plane_stats_["atlas_control_runtime_consumed_ready_fanout_total"] =
        registerStatistic<uint64_t>("atlas_control_runtime_consumed_ready_fanout_total");
    atlas_object_plane_stats_["atlas_control_runtime_consumed_join_reject_total"] =
        registerStatistic<uint64_t>("atlas_control_runtime_consumed_join_reject_total");
    atlas_object_plane_stats_["atlas_control_runtime_backlog_messages_current"] =
        registerStatistic<uint64_t>("atlas_control_runtime_backlog_messages_current");
    atlas_object_plane_stats_["atlas_control_runtime_backlog_messages_peak"] =
        registerStatistic<uint64_t>("atlas_control_runtime_backlog_messages_peak");
    atlas_object_plane_stats_["atlas_control_runtime_backlog_cycles_total"] =
        registerStatistic<uint64_t>("atlas_control_runtime_backlog_cycles_total");
    atlas_object_plane_stats_["atlas_control_runtime_produced_any_nonzero_total"] =
        registerStatistic<uint64_t>("atlas_control_runtime_produced_any_nonzero_total");
    atlas_object_plane_stats_["atlas_control_runtime_queued_any_nonzero_total"] =
        registerStatistic<uint64_t>("atlas_control_runtime_queued_any_nonzero_total");
    atlas_object_plane_stats_["atlas_control_runtime_consumed_any_nonzero_total"] =
        registerStatistic<uint64_t>("atlas_control_runtime_consumed_any_nonzero_total");
    atlas_object_plane_stats_["atlas_control_runtime_backlog_any_nonzero_total"] =
        registerStatistic<uint64_t>("atlas_control_runtime_backlog_any_nonzero_total");
    atlas_object_plane_stats_["atlas_control_runtime_all_zero_total"] =
        registerStatistic<uint64_t>("atlas_control_runtime_all_zero_total");
    atlas_object_plane_stats_["atlas_control_runtime_state_fabric_absent_total"] =
        registerStatistic<uint64_t>("atlas_control_runtime_state_fabric_absent_total");
    atlas_object_plane_stats_["atlas_control_runtime_state_fabric_present_idle_total"] =
        registerStatistic<uint64_t>("atlas_control_runtime_state_fabric_present_idle_total");
    atlas_object_plane_stats_["atlas_control_runtime_state_produced_without_queue_total"] =
        registerStatistic<uint64_t>("atlas_control_runtime_state_produced_without_queue_total");
    atlas_object_plane_stats_["atlas_control_runtime_state_queued_without_consume_total"] =
        registerStatistic<uint64_t>("atlas_control_runtime_state_queued_without_consume_total");
    atlas_object_plane_stats_["atlas_control_runtime_state_consumed_active_total"] =
        registerStatistic<uint64_t>("atlas_control_runtime_state_consumed_active_total");
    atlas_object_plane_stats_["atlas_enable_state_local_storage_effective_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_local_storage_effective_total");
    atlas_object_plane_stats_["atlas_enable_state_pe_internal_cpe_effective_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_pe_internal_cpe_effective_total");
    atlas_object_plane_stats_["atlas_enable_state_pe_internal_pod_effective_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_pe_internal_pod_effective_total");
    atlas_object_plane_stats_["atlas_enable_state_pe_internal_pod_metadata_effective_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_pe_internal_pod_metadata_effective_total");
    atlas_object_plane_stats_["atlas_enable_state_pe_internal_pod_owner_effective_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_pe_internal_pod_owner_effective_total");
    atlas_object_plane_stats_["atlas_enable_state_pe_local_service_table_present_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_pe_local_service_table_present_total");
    atlas_object_plane_stats_["atlas_enable_state_rowindex_effective_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_rowindex_effective_total");
    atlas_object_plane_stats_["atlas_enable_state_rowindex_gate_pulse_osa_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_rowindex_gate_pulse_osa_total");
    atlas_object_plane_stats_["atlas_enable_state_rowindex_gate_metadata_txn_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_rowindex_gate_metadata_txn_total");
    atlas_object_plane_stats_["atlas_enable_state_rowindex_gate_metadata_mask_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_rowindex_gate_metadata_mask_total");
    atlas_object_plane_stats_["atlas_enable_state_rowindex_gate_pod_enable_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_rowindex_gate_pod_enable_total");
    atlas_object_plane_stats_["atlas_enable_state_rowindex_gate_pod_metadata_enable_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_rowindex_gate_pod_metadata_enable_total");
    atlas_object_plane_stats_["atlas_enable_state_rowindex_gate_pod_owner_enable_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_rowindex_gate_pod_owner_enable_total");
    atlas_object_plane_stats_["atlas_enable_state_rowindex_gate_service_table_present_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_rowindex_gate_service_table_present_total");
    atlas_object_plane_stats_["atlas_enable_state_pulse_effective_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_pulse_effective_total");
    atlas_object_plane_stats_["atlas_enable_state_pulse_fabric_present_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_pulse_fabric_present_total");
    atlas_object_plane_stats_["atlas_enable_state_pulse_observe_only_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_pulse_observe_only_total");
    atlas_object_plane_stats_["atlas_enable_state_pulse_actual_ingress_effective_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_pulse_actual_ingress_effective_total");
    atlas_object_plane_stats_["atlas_enable_state_pulse_harbor_effective_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_pulse_harbor_effective_total");
    atlas_object_plane_stats_["atlas_enable_state_pulse_descriptor_effective_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_pulse_descriptor_effective_total");
    atlas_object_plane_stats_["atlas_enable_state_pulse_descriptor_actual_effective_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_pulse_descriptor_actual_effective_total");
    atlas_object_plane_stats_["atlas_enable_state_pulse_osa_effective_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_pulse_osa_effective_total");
    atlas_object_plane_stats_["atlas_enable_state_pulse_osa_shared_weight_owner_effective_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_pulse_osa_shared_weight_owner_effective_total");
    atlas_object_plane_stats_["atlas_enable_state_pulse_osa_shared_weight_actual_effective_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_pulse_osa_shared_weight_actual_effective_total");
    atlas_object_plane_stats_["atlas_enable_state_pe_weight_plane_present_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_pe_weight_plane_present_total");
    atlas_object_plane_stats_["atlas_enable_state_pulse_osa_metadata_txn_effective_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_pulse_osa_metadata_txn_effective_total");
    atlas_object_plane_stats_["atlas_enable_state_pulse_osa_metadata_ready_lease_effective_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_pulse_osa_metadata_ready_lease_effective_total");
    atlas_object_plane_stats_["atlas_enable_state_pulse_osa_metadata_mask_nonzero_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_pulse_osa_metadata_mask_nonzero_total");
    atlas_object_plane_stats_["atlas_enable_state_control_runtime_produce_eligible_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_control_runtime_produce_eligible_total");
    atlas_object_plane_stats_["atlas_enable_state_control_runtime_end_to_end_eligible_total"] =
        registerStatistic<uint64_t>("atlas_enable_state_control_runtime_end_to_end_eligible_total");
    atlas_object_plane_stats_["atlas_activation_gate_workload_pure_snn_datapath_eligible"] =
        registerStatistic<uint64_t>("atlas_activation_gate_workload_pure_snn_datapath_eligible");
    atlas_object_plane_stats_["atlas_activation_gate_local_storage_enable"] =
        registerStatistic<uint64_t>("atlas_activation_gate_local_storage_enable");
    atlas_object_plane_stats_["atlas_activation_gate_pulse_requested"] =
        registerStatistic<uint64_t>("atlas_activation_gate_pulse_requested");
    atlas_object_plane_stats_["atlas_activation_gate_pulse_effective"] =
        registerStatistic<uint64_t>("atlas_activation_gate_pulse_effective");
    atlas_object_plane_stats_["atlas_activation_gate_pulse_fabric_constructed"] =
        registerStatistic<uint64_t>("atlas_activation_gate_pulse_fabric_constructed");
    atlas_object_plane_stats_["atlas_activation_gate_pulse_observe_only_effective"] =
        registerStatistic<uint64_t>("atlas_activation_gate_pulse_observe_only_effective");
    atlas_object_plane_stats_["atlas_activation_gate_pulse_actual_ingress_eligible"] =
        registerStatistic<uint64_t>("atlas_activation_gate_pulse_actual_ingress_eligible");
    atlas_object_plane_stats_["atlas_activation_gate_pulse_harbor_enable_effective"] =
        registerStatistic<uint64_t>("atlas_activation_gate_pulse_harbor_enable_effective");
    atlas_object_plane_stats_["atlas_activation_gate_pulse_descriptor_enable_effective"] =
        registerStatistic<uint64_t>("atlas_activation_gate_pulse_descriptor_enable_effective");
    atlas_object_plane_stats_["atlas_activation_gate_pulse_descriptor_actual_requested"] =
        registerStatistic<uint64_t>("atlas_activation_gate_pulse_descriptor_actual_requested");
    atlas_object_plane_stats_["atlas_activation_gate_pulse_descriptor_actual_effective"] =
        registerStatistic<uint64_t>("atlas_activation_gate_pulse_descriptor_actual_effective");
    atlas_object_plane_stats_["atlas_activation_gate_pulse_osa_requested"] =
        registerStatistic<uint64_t>("atlas_activation_gate_pulse_osa_requested");
    atlas_object_plane_stats_["atlas_activation_gate_pulse_osa_effective"] =
        registerStatistic<uint64_t>("atlas_activation_gate_pulse_osa_effective");
    atlas_object_plane_stats_["atlas_activation_gate_shared_weight_owner_requested"] =
        registerStatistic<uint64_t>("atlas_activation_gate_shared_weight_owner_requested");
    atlas_object_plane_stats_["atlas_activation_gate_shared_weight_owner_effective"] =
        registerStatistic<uint64_t>("atlas_activation_gate_shared_weight_owner_effective");
    atlas_object_plane_stats_["atlas_activation_gate_shared_weight_plane_constructed"] =
        registerStatistic<uint64_t>("atlas_activation_gate_shared_weight_plane_constructed");
    atlas_object_plane_stats_["atlas_activation_gate_shared_weight_actual_owner_requested"] =
        registerStatistic<uint64_t>("atlas_activation_gate_shared_weight_actual_owner_requested");
    atlas_object_plane_stats_["atlas_activation_gate_shared_weight_actual_owner_effective"] =
        registerStatistic<uint64_t>("atlas_activation_gate_shared_weight_actual_owner_effective");
    atlas_object_plane_stats_["atlas_activation_gate_pe_internal_pod_requested"] =
        registerStatistic<uint64_t>("atlas_activation_gate_pe_internal_pod_requested");
    atlas_object_plane_stats_["atlas_activation_gate_rowindex_requested"] =
        registerStatistic<uint64_t>("atlas_activation_gate_rowindex_requested");
    atlas_object_plane_stats_["atlas_activation_gate_pe_internal_pod_metadata_requested"] =
        registerStatistic<uint64_t>("atlas_activation_gate_pe_internal_pod_metadata_requested");
    atlas_object_plane_stats_["atlas_activation_gate_pe_internal_pod_owner_requested"] =
        registerStatistic<uint64_t>("atlas_activation_gate_pe_internal_pod_owner_requested");
    atlas_object_plane_stats_["atlas_activation_gate_rowindex_constructed"] =
        registerStatistic<uint64_t>("atlas_activation_gate_rowindex_constructed");
    atlas_object_plane_stats_["atlas_activation_gate_pod_metadata_plane_constructed"] =
        registerStatistic<uint64_t>("atlas_activation_gate_pod_metadata_plane_constructed");
    atlas_object_plane_stats_["atlas_activation_gate_pod_owner_table_constructed"] =
        registerStatistic<uint64_t>("atlas_activation_gate_pod_owner_table_constructed");
    atlas_object_plane_stats_["atlas_activation_gate_service_table_constructed"] =
        registerStatistic<uint64_t>("atlas_activation_gate_service_table_constructed");
    stat_pulse_osa_shared_weight_enabled_ =
        registerStatistic<uint64_t>("pulse_osa_shared_weight_enabled");
    stat_pulse_osa_shared_weight_owner_scope_enable_ =
        registerStatistic<uint64_t>("pulse_osa_shared_weight_owner_scope_enable");
    stat_pulse_osa_shared_weight_actual_owner_enable_ =
        registerStatistic<uint64_t>("pulse_osa_shared_weight_actual_owner_enable");
    stat_pulse_osa_shared_weight_idx_enabled_ =
        registerStatistic<uint64_t>("pulse_osa_shared_weight_idx_enabled");
    stat_pulse_osa_shared_weight_idx_reads_total_ =
        registerStatistic<uint64_t>("pulse_osa_shared_weight_idx_reads_total");
    stat_pulse_osa_shared_weight_idx_writes_total_ =
        registerStatistic<uint64_t>("pulse_osa_shared_weight_idx_writes_total");
    stat_pulse_osa_shared_weight_idx_bank_conflict_ticks_total_ =
        registerStatistic<uint64_t>("pulse_osa_shared_weight_idx_bank_conflict_ticks_total");
    stat_pulse_osa_shared_weight_idx_predicted_extra_cycles_total_ =
        registerStatistic<uint64_t>("pulse_osa_shared_weight_idx_predicted_extra_cycles_total");
    stat_pulse_osa_shared_weight_idx_resident_bytes_peak_ =
        registerStatistic<uint64_t>("pulse_osa_shared_weight_idx_resident_bytes_peak");
    stat_pulse_osa_shared_weight_l0_enabled_ =
        registerStatistic<uint64_t>("pulse_osa_shared_weight_l0_enabled");
    stat_pulse_osa_shared_weight_l0_reads_total_ =
        registerStatistic<uint64_t>("pulse_osa_shared_weight_l0_reads_total");
    stat_pulse_osa_shared_weight_l0_writes_total_ =
        registerStatistic<uint64_t>("pulse_osa_shared_weight_l0_writes_total");
    stat_pulse_osa_shared_weight_l0_fill_total_ =
        registerStatistic<uint64_t>("pulse_osa_shared_weight_l0_fill_total");
    stat_pulse_osa_shared_weight_l0_evict_total_ =
        registerStatistic<uint64_t>("pulse_osa_shared_weight_l0_evict_total");
    stat_pulse_osa_shared_weight_l0_bank_conflict_ticks_total_ =
        registerStatistic<uint64_t>("pulse_osa_shared_weight_l0_bank_conflict_ticks_total");
    stat_pulse_osa_shared_weight_l0_predicted_extra_cycles_total_ =
        registerStatistic<uint64_t>("pulse_osa_shared_weight_l0_predicted_extra_cycles_total");
    stat_pulse_osa_shared_weight_l0_resident_bytes_peak_ =
        registerStatistic<uint64_t>("pulse_osa_shared_weight_l0_resident_bytes_peak");
    stat_pulse_ingress_packets_total_ = registerStatistic<uint64_t>("pulse_ingress_packets_total");
    stat_pulse_ingress_spike_packets_total_ =
        registerStatistic<uint64_t>("pulse_ingress_spike_packets_total");
    stat_pulse_ingress_spikekey_packets_total_ =
        registerStatistic<uint64_t>("pulse_ingress_spikekey_packets_total");
    stat_pulse_ingress_spiketilekey_packets_total_ =
        registerStatistic<uint64_t>("pulse_ingress_spiketilekey_packets_total");
    stat_pulse_ingress_core_dispatch_total_ =
        registerStatistic<uint64_t>("pulse_ingress_core_dispatch_total");
    stat_pulse_ingress_shared_buffered_total_ =
        registerStatistic<uint64_t>("pulse_ingress_shared_buffered_total");
    stat_pulse_ingress_shared_dispatch_total_ =
        registerStatistic<uint64_t>("pulse_ingress_shared_dispatch_total");
    stat_pulse_ingress_direct_deliver_total_ =
        registerStatistic<uint64_t>("pulse_ingress_direct_deliver_total");
    stat_pulse_ingress_bypass_total_ = registerStatistic<uint64_t>("pulse_ingress_bypass_total");
    stat_pulse_ingress_pressure_bypass_total_ =
        registerStatistic<uint64_t>("pulse_ingress_pressure_bypass_total");
    stat_pulse_ingress_singleton_bypass_total_ =
        registerStatistic<uint64_t>("pulse_ingress_singleton_bypass_total");
    stat_pulse_ingress_deadline_bypass_total_ =
        registerStatistic<uint64_t>("pulse_ingress_deadline_bypass_total");
    stat_pulse_ingress_pressure_cycles_total_ =
        registerStatistic<uint64_t>("pulse_ingress_pressure_cycles_total");
    stat_pulse_ingress_entries_peak_ = registerStatistic<uint64_t>("pulse_ingress_entries_peak");
    stat_pulse_control_entries_current_ =
        registerStatistic<uint64_t>("pulse_control_entries_current");
    stat_pulse_control_entries_peak_ =
        registerStatistic<uint64_t>("pulse_control_entries_peak");
    stat_pulse_control_backlog_cycles_total_ =
        registerStatistic<uint64_t>("pulse_control_backlog_cycles_total");
    stat_pulse_core_queue_entries_peak_ =
        registerStatistic<uint64_t>("pulse_core_queue_entries_peak");
    stat_pulse_harbor_buckets_total_ =
        registerStatistic<uint64_t>("pulse_harbor_buckets_total");
    stat_pulse_harbor_packet_sum_ =
        registerStatistic<uint64_t>("pulse_harbor_packet_sum");
    stat_pulse_harbor_consumer_sum_ =
        registerStatistic<uint64_t>("pulse_harbor_consumer_sum");
    stat_pulse_harbor_bucket_peak_ =
        registerStatistic<uint64_t>("pulse_harbor_bucket_peak");
    stat_pulse_harbor_singleton_buckets_total_ =
        registerStatistic<uint64_t>("pulse_harbor_singleton_buckets_total");
    stat_pulse_descriptor_total_ =
        registerStatistic<uint64_t>("pulse_descriptor_total");
    stat_pulse_descriptor_packet_sum_ =
        registerStatistic<uint64_t>("pulse_descriptor_packet_sum");
    stat_pulse_descriptor_consumer_sum_ =
        registerStatistic<uint64_t>("pulse_descriptor_consumer_sum");
    stat_pulse_descriptor_singleton_drop_total_ =
        registerStatistic<uint64_t>("pulse_descriptor_singleton_drop_total");
    stat_pulse_control_messages_enqueued_total_ =
        registerStatistic<uint64_t>("pulse_control_messages_enqueued_total");
    stat_pulse_control_messages_dequeued_total_ =
        registerStatistic<uint64_t>("pulse_control_messages_dequeued_total");
    stat_pulse_control_frontier_export_total_ =
        registerStatistic<uint64_t>("pulse_control_frontier_export_total");
    stat_pulse_control_owner_announce_total_ =
        registerStatistic<uint64_t>("pulse_control_owner_announce_total");
    stat_pulse_control_join_request_total_ =
        registerStatistic<uint64_t>("pulse_control_join_request_total");
    stat_pulse_control_ready_fanout_total_ =
        registerStatistic<uint64_t>("pulse_control_ready_fanout_total");
    stat_pulse_control_join_reject_total_ =
        registerStatistic<uint64_t>("pulse_control_join_reject_total");
    stat_pulse_agenda_candidates_total_ =
        registerStatistic<uint64_t>("pulse_agenda_candidates_total");
    stat_pulse_agenda_accepted_total_ =
        registerStatistic<uint64_t>("pulse_agenda_accepted_total");
    stat_pulse_agenda_rejected_total_ =
        registerStatistic<uint64_t>("pulse_agenda_rejected_total");
    stat_pulse_agenda_reject_gate_total_ =
        registerStatistic<uint64_t>("pulse_agenda_reject_gate_total");
    stat_pulse_correctness_ready_blocked_cycles_total_ =
        registerStatistic<uint64_t>("pulse_correctness_ready_blocked_cycles_total");
    stat_pulse_correctness_scoreboard_occupancy_peak_ =
        registerStatistic<uint64_t>("pulse_correctness_scoreboard_occupancy_peak");
    stat_pulse_shared_service_hits_total_ =
        registerStatistic<uint64_t>("pulse_shared_service_hits_total");
    stat_pulse_shared_service_misses_total_ =
        registerStatistic<uint64_t>("pulse_shared_service_misses_total");
    stat_pulse_region_service_entries_peak_ =
        registerStatistic<uint64_t>("pulse_region_service_entries_peak");
    stat_pulse_ready_fanout_total_ =
        registerStatistic<uint64_t>("pulse_ready_fanout_total");
    stat_pulse_rowdescriptor_ready_transition_total_ =
        registerStatistic<uint64_t>("pulse_rowdescriptor_ready_transition_total");
    stat_pulse_rowdescriptor_join_ready_total_ =
        registerStatistic<uint64_t>("pulse_rowdescriptor_join_ready_total");
    stat_pulse_rowdescriptor_ready_join_shortcut_candidates_total_ =
        registerStatistic<uint64_t>("pulse_rowdescriptor_ready_join_shortcut_candidates_total");
    stat_pulse_rowdescriptor_ready_join_shortcut_taken_total_ =
        registerStatistic<uint64_t>("pulse_rowdescriptor_ready_join_shortcut_taken_total");
    stat_pulse_rowdescriptor_ready_join_shortcut_late_release_taken_total_ =
        registerStatistic<uint64_t>("pulse_rowdescriptor_ready_join_shortcut_late_release_taken_total");
    stat_pulse_rowdescriptor_ready_join_shortcut_deferred_live_park_total_ =
        registerStatistic<uint64_t>("pulse_rowdescriptor_ready_join_shortcut_deferred_live_park_total");
    stat_pulse_rowdescriptor_ready_join_shortcut_deferred_live_apply_total_ =
        registerStatistic<uint64_t>("pulse_rowdescriptor_ready_join_shortcut_deferred_live_apply_total");
    stat_pulse_rowdescriptor_owner_form_deferred_park_total_ =
        registerStatistic<uint64_t>("pulse_rowdescriptor_owner_form_deferred_park_total");
    stat_pulse_rowdescriptor_owner_form_deferred_activate_total_ =
        registerStatistic<uint64_t>("pulse_rowdescriptor_owner_form_deferred_activate_total");
    stat_pulse_rowdescriptor_ready_join_shortcut_blocked_not_ready_total_ =
        registerStatistic<uint64_t>("pulse_rowdescriptor_ready_join_shortcut_blocked_not_ready_total");
    stat_pulse_rowdescriptor_ready_join_shortcut_blocked_owner_form_total_ =
        registerStatistic<uint64_t>("pulse_rowdescriptor_ready_join_shortcut_blocked_owner_form_total");
    stat_pulse_rowdescriptor_ready_join_shortcut_blocked_join_live_total_ =
        registerStatistic<uint64_t>("pulse_rowdescriptor_ready_join_shortcut_blocked_join_live_total");
    stat_pulse_rowdescriptor_ready_join_shortcut_blocked_other_total_ =
        registerStatistic<uint64_t>("pulse_rowdescriptor_ready_join_shortcut_blocked_other_total");
    stat_pulse_rowdescriptor_ready_join_shortcut_release_deferred_total_ =
        registerStatistic<uint64_t>("pulse_rowdescriptor_ready_join_shortcut_release_deferred_total");
    stat_pulse_rowdescriptor_ready_join_shortcut_apply_complete_total_ =
        registerStatistic<uint64_t>("pulse_rowdescriptor_ready_join_shortcut_apply_complete_total");
    stat_pulse_rowdescriptor_ready_join_shortcut_release_forwarded_total_ =
        registerStatistic<uint64_t>("pulse_rowdescriptor_ready_join_shortcut_release_forwarded_total");
    stat_pulse_rowdescriptor_ready_join_shortcut_release_missing_total_ =
        registerStatistic<uint64_t>("pulse_rowdescriptor_ready_join_shortcut_release_missing_total");
    stat_pulse_rowdescriptor_ready_join_descriptor_elide_total_ =
        registerStatistic<uint64_t>("pulse_rowdescriptor_ready_join_descriptor_elide_total");
    stat_pulse_rowdescriptor_ready_join_lines_elide_total_ =
        registerStatistic<uint64_t>("pulse_rowdescriptor_ready_join_lines_elide_total");
    stat_pulse_rowdescriptor_owner_first_service_elide_join_live_total_ =
        registerStatistic<uint64_t>("pulse_rowdescriptor_owner_first_service_elide_join_live_total");
    stat_pulse_rowdescriptor_owner_first_service_elide_join_ready_total_ =
        registerStatistic<uint64_t>("pulse_rowdescriptor_owner_first_service_elide_join_ready_total");
    stat_pulse_rowdescriptor_owner_first_service_elide_late_join_total_ =
        registerStatistic<uint64_t>("pulse_rowdescriptor_owner_first_service_elide_late_join_total");
    stat_pulse_pod_rowdescriptor_owner_form_total_ =
        registerStatistic<uint64_t>("pulse_pod_rowdescriptor_owner_form_total");
    stat_pulse_pod_rowdescriptor_owner_hit_total_ =
        registerStatistic<uint64_t>("pulse_pod_rowdescriptor_owner_hit_total");
    stat_pulse_pod_rowdescriptor_join_live_total_ =
        registerStatistic<uint64_t>("pulse_pod_rowdescriptor_join_live_total");
    stat_pulse_pod_rowdescriptor_join_ready_total_ =
        registerStatistic<uint64_t>("pulse_pod_rowdescriptor_join_ready_total");
    stat_pulse_pod_rowdescriptor_ready_transition_total_ =
        registerStatistic<uint64_t>("pulse_pod_rowdescriptor_ready_transition_total");
    stat_pulse_pod_rowdescriptor_late_join_total_ =
        registerStatistic<uint64_t>("pulse_pod_rowdescriptor_late_join_total");
    stat_pulse_pod_rowdescriptor_guard_total_ =
        registerStatistic<uint64_t>("pulse_pod_rowdescriptor_guard_total");
    stat_pulse_pod_rowdescriptor_guard_disabled_total_ =
        registerStatistic<uint64_t>("pulse_pod_rowdescriptor_guard_disabled_total");
    stat_pulse_pod_rowdescriptor_guard_missing_metadata_plane_total_ =
        registerStatistic<uint64_t>("pulse_pod_rowdescriptor_guard_missing_metadata_plane_total");
    stat_pulse_pod_rowdescriptor_guard_missing_owner_table_total_ =
        registerStatistic<uint64_t>("pulse_pod_rowdescriptor_guard_missing_owner_table_total");
    stat_pulse_pod_rowdescriptor_guard_zero_pod_count_total_ =
        registerStatistic<uint64_t>("pulse_pod_rowdescriptor_guard_zero_pod_count_total");
    stat_pulse_pod_rowdescriptor_guard_window_zero_total_ =
        registerStatistic<uint64_t>("pulse_pod_rowdescriptor_guard_window_zero_total");
    stat_pulse_pod_rowdescriptor_guard_invalid_cfg_pod_total_ =
        registerStatistic<uint64_t>("pulse_pod_rowdescriptor_guard_invalid_cfg_pod_total");
    stat_pulse_pod_rowdescriptor_reject_total_ =
        registerStatistic<uint64_t>("pulse_pod_rowdescriptor_reject_total");
    stat_pulse_pod_rowdescriptor_attempted_total_ =
        registerStatistic<uint64_t>("pulse_pod_rowdescriptor_attempted_total");
    stat_pulse_pod_rowdescriptor_potential_private_service_elide_total_ =
        registerStatistic<uint64_t>("pulse_pod_rowdescriptor_potential_private_service_elide_total");
    stat_pulse_pod_rowdescriptor_owner_first_issue_deferred_total_ =
        registerStatistic<uint64_t>("pulse_pod_rowdescriptor_owner_first_issue_deferred_total");
    stat_pulse_pod_rowdescriptor_owner_first_private_issue_avoided_total_ =
        registerStatistic<uint64_t>("pulse_pod_rowdescriptor_owner_first_private_issue_avoided_total");
    stat_pulse_pod_rowdescriptor_owner_first_service_elide_total_ =
        registerStatistic<uint64_t>("pulse_pod_rowdescriptor_owner_first_service_elide_total");
    stat_pulse_metadata_txn_export_total_ =
        registerStatistic<uint64_t>("pulse_metadata_txn_export_total");
    stat_pulse_metadata_txn_owner_launch_total_ =
        registerStatistic<uint64_t>("pulse_metadata_txn_owner_launch_total");
    stat_pulse_metadata_txn_join_live_total_ =
        registerStatistic<uint64_t>("pulse_metadata_txn_join_live_total");
    stat_pulse_metadata_txn_join_ready_total_ =
        registerStatistic<uint64_t>("pulse_metadata_txn_join_ready_total");
    stat_pulse_metadata_txn_late_join_total_ =
        registerStatistic<uint64_t>("pulse_metadata_txn_late_join_total");
    stat_pulse_metadata_txn_ready_lease_hit_total_ =
        registerStatistic<uint64_t>("pulse_metadata_txn_ready_lease_hit_total");
    stat_pulse_metadata_txn_ready_lease_expired_total_ =
        registerStatistic<uint64_t>("pulse_metadata_txn_ready_lease_expired_total");
    stat_pulse_metadata_txn_envelope_size_sum_total_ =
        registerStatistic<uint64_t>("pulse_metadata_txn_envelope_size_sum_total");
    stat_pulse_metadata_frontier_observed_total_ =
        registerStatistic<uint64_t>("pulse_metadata_frontier_observed_total");
    stat_pulse_metadata_frontier_same_window_reobserve_total_ =
        registerStatistic<uint64_t>("pulse_metadata_frontier_same_window_reobserve_total");
    stat_pulse_metadata_frontier_owner_form_candidate_total_ =
        registerStatistic<uint64_t>("pulse_metadata_frontier_owner_form_candidate_total");
    stat_pulse_metadata_frontier_join_ready_candidate_total_ =
        registerStatistic<uint64_t>("pulse_metadata_frontier_join_ready_candidate_total");
    stat_pulse_metadata_frontier_premphf_base_observed_total_ =
        registerStatistic<uint64_t>("pulse_metadata_frontier_premphf_base_observed_total");
    stat_pulse_metadata_frontier_premphf_base_same_window_reobserve_total_ =
        registerStatistic<uint64_t>("pulse_metadata_frontier_premphf_base_same_window_reobserve_total");
    stat_pulse_metadata_frontier_premphf_base_owner_form_candidate_total_ =
        registerStatistic<uint64_t>("pulse_metadata_frontier_premphf_base_owner_form_candidate_total");
    stat_pulse_metadata_frontier_premphf_base_join_ready_candidate_total_ =
        registerStatistic<uint64_t>("pulse_metadata_frontier_premphf_base_join_ready_candidate_total");
    stat_pulse_metadata_frontier_premphf_band_observed_total_ =
        registerStatistic<uint64_t>("pulse_metadata_frontier_premphf_band_observed_total");
    stat_pulse_metadata_frontier_premphf_band_same_window_reobserve_total_ =
        registerStatistic<uint64_t>("pulse_metadata_frontier_premphf_band_same_window_reobserve_total");
    stat_pulse_metadata_frontier_premphf_band_owner_form_candidate_total_ =
        registerStatistic<uint64_t>("pulse_metadata_frontier_premphf_band_owner_form_candidate_total");
    stat_pulse_metadata_frontier_premphf_band_join_ready_candidate_total_ =
        registerStatistic<uint64_t>("pulse_metadata_frontier_premphf_band_join_ready_candidate_total");
    stat_pulse_metadata_frontier_idx2row_observed_total_ =
        registerStatistic<uint64_t>("pulse_metadata_frontier_idx2row_observed_total");
    stat_pulse_metadata_frontier_idx2row_same_window_reobserve_total_ =
        registerStatistic<uint64_t>("pulse_metadata_frontier_idx2row_same_window_reobserve_total");
    stat_pulse_metadata_frontier_idx2row_owner_form_candidate_total_ =
        registerStatistic<uint64_t>("pulse_metadata_frontier_idx2row_owner_form_candidate_total");
    stat_pulse_metadata_frontier_idx2row_join_ready_candidate_total_ =
        registerStatistic<uint64_t>("pulse_metadata_frontier_idx2row_join_ready_candidate_total");
    stat_pulse_metadata_frontier_rowindex_observed_total_ =
        registerStatistic<uint64_t>("pulse_metadata_frontier_rowindex_observed_total");
    stat_pulse_metadata_frontier_rowindex_same_window_reobserve_total_ =
        registerStatistic<uint64_t>("pulse_metadata_frontier_rowindex_same_window_reobserve_total");
    stat_pulse_metadata_frontier_rowindex_owner_form_candidate_total_ =
        registerStatistic<uint64_t>("pulse_metadata_frontier_rowindex_owner_form_candidate_total");
    stat_pulse_metadata_frontier_rowindex_join_ready_candidate_total_ =
        registerStatistic<uint64_t>("pulse_metadata_frontier_rowindex_join_ready_candidate_total");
    stat_pulse_actual_gate_enable_false_total_ =
        registerStatistic<uint64_t>("pulse_actual_gate_enable_false_total");
    stat_pulse_actual_gate_window_zero_total_ =
        registerStatistic<uint64_t>("pulse_actual_gate_window_zero_total");
    stat_pulse_actual_gate_line_too_small_total_ =
        registerStatistic<uint64_t>("pulse_actual_gate_line_too_small_total");
    stat_pulse_actual_gate_taken_total_ =
        registerStatistic<uint64_t>("pulse_actual_gate_taken_total");
    stat_pulse_frontier_windows_total_ =
        registerStatistic<uint64_t>("pulse_frontier_windows_total");
    stat_pulse_frontier_lines_exported_total_ =
        registerStatistic<uint64_t>("pulse_frontier_lines_exported_total");
    stat_pulse_frontier_overlap_lines_total_ =
        registerStatistic<uint64_t>("pulse_frontier_overlap_lines_total");
    stat_pulse_frontier_overlap_peer_total_ =
        registerStatistic<uint64_t>("pulse_frontier_overlap_peer_total");
    stat_pulse_frontier_max_exported_per_window_ =
        registerStatistic<uint64_t>("pulse_frontier_max_exported_per_window");
    stat_pulse_prebase_lookup_owner_fill_total_ =
        registerStatistic<uint64_t>("pulse_prebase_lookup_owner_fill_total");
    stat_pulse_prebase_lookup_shared_hits_total_ =
        registerStatistic<uint64_t>("pulse_prebase_lookup_shared_hits_total");
    stat_pulse_prebase_lookup_entries_peak_ =
        registerStatistic<uint64_t>("pulse_prebase_lookup_entries_peak");
    for (auto& mod : workload_stats_modules_) {
        if (!mod) continue;
        if (std::strcmp(mod->name(), "stream") == 0) {
            mod->bindUnexpectedActivityStat(stat_compat_unexpected_stream_activity_total_);
        }
        mod->initialize(*this, static_cast<size_t>(num_cores_));
    }
    // Batch-A: 注册组件级直方图统计（具体类型由Python侧设置为Histogram）
    stat_mem_read_latency_cycles_ = registerStatistic<uint64_t>("mem_read_latency_cycles");
    stat_mem_read_latency_cycles_weights_ = registerStatistic<uint64_t>("mem_read_latency_cycles_weights");
    stat_mem_read_latency_cycles_state_ = registerStatistic<uint64_t>("mem_read_latency_cycles_state");
    stat_mem_req_size_bytes_ = registerStatistic<uint64_t>("mem_req_size_bytes");
    stat_mem_outstanding_at_issue_ = registerStatistic<uint64_t>("mem_outstanding_at_issue");
    // GAS totals (accumulated from cores)
    stat_gas_unique_reads_total_ = registerStatistic<uint64_t>("gas_unique_reads_total");
    stat_gas_unique_bytes_total_ = registerStatistic<uint64_t>("gas_unique_bytes_total");
    stat_gas_rowwin_triggers_total_ = registerStatistic<uint64_t>("gas_row_window_triggers_total");
    stat_gas_rowwin_bytes_total_ = registerStatistic<uint64_t>("gas_row_window_bytes_total");
    stat_gas_total_bursts_ = registerStatistic<uint64_t>("gas_total_bursts");
    stat_gas_total_payload_bytes_ = registerStatistic<uint64_t>("gas_total_payload_bytes");
    stat_gas_frontend_staged_reads_total_ = registerStatistic<uint64_t>("gas_frontend_staged_reads_total");
    stat_gas_frontend_staged_line_touches_total_ = registerStatistic<uint64_t>("gas_frontend_staged_line_touches_total");
    stat_gas_frontend_granules_built_total_ = registerStatistic<uint64_t>("gas_frontend_granules_built_total");
    stat_gas_unique_line_count_total_ = registerStatistic<uint64_t>("gas_unique_line_count_total");
    stat_gas_covered_line_count_total_ = registerStatistic<uint64_t>("gas_covered_line_count_total");
    stat_gas_overfetch_bytes_total_ = registerStatistic<uint64_t>("gas_overfetch_bytes_total");
    stat_gas_apply_bank_credit_effective_total_ = registerStatistic<uint64_t>("gas_apply_bank_credit_effective_total");
    stat_gas_cmd_cost_veto_total_ = registerStatistic<uint64_t>("gas_cmd_cost_veto_total");
    stat_gas_cmd_cost_veto_fine_gap_total_ = registerStatistic<uint64_t>("gas_cmd_cost_veto_fine_gap_total");
    stat_gas_cmd_cost_veto_row_window_total_ = registerStatistic<uint64_t>("gas_cmd_cost_veto_row_window_total");
    stat_gas_apply_acc_updates_total_ = registerStatistic<uint64_t>("gas_apply_acc_updates_total");
    stat_gas_acc_posts_touched_total_ = registerStatistic<uint64_t>("gas_acc_posts_touched_total");
    stat_gas_scatter_spikes_emitted_total_ = registerStatistic<uint64_t>("gas_scatter_spikes_emitted_total");
    stat_stall_on_step_gate_cycles_total_ = registerStatistic<uint64_t>("stall_on_step_gate_cycles_total");
    stat_gas_acc_hwm_bytes_total_ = registerStatistic<uint64_t>("gas_acc_high_watermark_bytes_total");
    stat_gas_acc_spill_records_total_ = registerStatistic<uint64_t>("gas_acc_spill_records_total");
    stat_gas_acc_spilled_bytes_total_ = registerStatistic<uint64_t>("gas_acc_spilled_bytes_total");
    stat_gas_retire_global_hol_cycles_total_ = registerStatistic<uint64_t>("gas_retire_global_hol_cycles_total");
    stat_gas_retire_ready_but_blocked_edges_total_ = registerStatistic<uint64_t>("gas_retire_ready_but_blocked_edges_total");
    stat_gas_retire_per_post_progress_total_ = registerStatistic<uint64_t>("gas_retire_per_post_progress_total");
    stat_gas_retire_samepost_blocked_edges_total_ = registerStatistic<uint64_t>("gas_retire_samepost_blocked_edges_total");
    stat_gas_retire_crosspost_blocked_edges_total_ = registerStatistic<uint64_t>("gas_retire_crosspost_blocked_edges_total");
    stat_gas_retire_policy_loss_cycles_total_ = registerStatistic<uint64_t>("gas_retire_policy_loss_cycles_total");
    stat_gas_retire_policy_loss_edges_total_ = registerStatistic<uint64_t>("gas_retire_policy_loss_edges_total");
    stat_gas_retire_shadow_per_post_recoverable_cycles_total_ = registerStatistic<uint64_t>("gas_retire_shadow_per_post_recoverable_cycles_total");
    stat_gas_retire_shadow_per_post_recoverable_edges_total_ = registerStatistic<uint64_t>("gas_retire_shadow_per_post_recoverable_edges_total");
    stat_gas_retire_shadow_per_post_ready_posts_peak_ = registerStatistic<uint64_t>("gas_retire_shadow_per_post_ready_posts_peak");
    stat_gas_retire_shadow_per_post_committable_edges_peak_ = registerStatistic<uint64_t>("gas_retire_shadow_per_post_committable_edges_peak");
    stat_exp_noc_rowidx_prefetch_rows_total_ = registerStatistic<uint64_t>("exp_noc_rowidx_prefetch_rows_total");
    stat_exp_noc_rowidx_prefetch_bytes_total_ = registerStatistic<uint64_t>("exp_noc_rowidx_prefetch_bytes_total");
    stat_exp_noc_rowidx_prefetch_complete_inflight_miss_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_prefetch_complete_inflight_miss_total");
    stat_exp_noc_rowidx_prefetch_complete_zero_waiters_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_prefetch_complete_zero_waiters_total");
    stat_exp_noc_rowidx_prefetch_complete_waiters_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_prefetch_complete_waiters_total");
    stat_exp_noc_rowidx_prefetch_rows_deferred_total_ = registerStatistic<uint64_t>("exp_noc_rowidx_prefetch_rows_deferred_total");
    stat_exp_noc_rowidx_prefetch_rows_failed_total_ = registerStatistic<uint64_t>("exp_noc_rowidx_prefetch_rows_failed_total");
    stat_exp_noc_rowidx_cache_hits_total_ = registerStatistic<uint64_t>("exp_noc_rowidx_cache_hits_total");
    stat_exp_noc_rowidx_cache_misses_total_ = registerStatistic<uint64_t>("exp_noc_rowidx_cache_misses_total");
    stat_exp_noc_rowidx_cache_fills_total_ = registerStatistic<uint64_t>("exp_noc_rowidx_cache_fills_total");
    stat_exp_noc_rowidx_cache_full_drop_total_ = registerStatistic<uint64_t>("exp_noc_rowidx_cache_full_drop_total");
    stat_exp_noc_rowidx_cache_entries_final_ = registerStatistic<uint64_t>("exp_noc_rowidx_cache_entries_final");
    stat_exp_noc_rowidx_bulk_fill_total_ = registerStatistic<uint64_t>("exp_noc_rowidx_bulk_fill_total");
    stat_exp_noc_rowidx_bulk_rows_cached_total_ = registerStatistic<uint64_t>("exp_noc_rowidx_bulk_rows_cached_total");
    stat_exp_noc_rowidx_bulk_waiters_resolved_total_ = registerStatistic<uint64_t>("exp_noc_rowidx_bulk_waiters_resolved_total");
    stat_exp_noc_rowidx_touch_rows_total_ = registerStatistic<uint64_t>("exp_noc_rowidx_touch_rows_total");
    stat_exp_noc_rowidx_touch_events_total_ = registerStatistic<uint64_t>("exp_noc_rowidx_touch_events_total");
    stat_exp_noc_rowidx_rows_filtered_cold_total_ = registerStatistic<uint64_t>("exp_noc_rowidx_rows_filtered_cold_total");
    stat_exp_noc_rowidx_budget_ticks_total_ = registerStatistic<uint64_t>("exp_noc_rowidx_budget_ticks_total");
    stat_exp_noc_rowidx_budget_effective_total_ = registerStatistic<uint64_t>("exp_noc_rowidx_budget_effective_total");
    stat_exp_noc_rowidx_budget_adapt_ticks_total_ = registerStatistic<uint64_t>("exp_noc_rowidx_budget_adapt_ticks_total");
    stat_exp_noc_rowidx_ready_transition_apply_promote_cached_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_ready_transition_apply_promote_cached_total");
    stat_exp_noc_rowidx_ready_signal_rowindex_response_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_ready_signal_rowindex_response_total");
    stat_exp_noc_rowidx_ready_transition_rowindex_response_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_ready_transition_rowindex_response_total");
    stat_exp_noc_rowidx_ready_signal_prefetch_response_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_ready_signal_prefetch_response_total");
    stat_exp_noc_rowidx_ready_transition_prefetch_response_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_ready_transition_prefetch_response_total");
    stat_exp_noc_rowidx_ready_signal_rowindex_response_inflight_waiters_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_ready_signal_rowindex_response_inflight_waiters_total");
    stat_exp_noc_rowidx_ready_transition_rowindex_response_inflight_waiters_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_ready_transition_rowindex_response_inflight_waiters_total");
    stat_exp_noc_rowidx_ready_signal_rowindex_response_inflight_zero_waiters_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_ready_signal_rowindex_response_inflight_zero_waiters_total");
    stat_exp_noc_rowidx_ready_transition_rowindex_response_inflight_zero_waiters_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_ready_transition_rowindex_response_inflight_zero_waiters_total");
    stat_exp_noc_rowidx_ready_signal_rowindex_response_noninflight_prefetch_only_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_ready_signal_rowindex_response_noninflight_prefetch_only_total");
    stat_exp_noc_rowidx_ready_transition_rowindex_response_noninflight_prefetch_only_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_ready_transition_rowindex_response_noninflight_prefetch_only_total");
    stat_exp_noc_rowidx_ready_signal_prefetch_response_inflight_waiters_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_ready_signal_prefetch_response_inflight_waiters_total");
    stat_exp_noc_rowidx_ready_transition_prefetch_response_inflight_waiters_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_ready_transition_prefetch_response_inflight_waiters_total");
    stat_exp_noc_rowidx_ready_signal_prefetch_response_inflight_zero_waiters_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_ready_signal_prefetch_response_inflight_zero_waiters_total");
    stat_exp_noc_rowidx_ready_transition_prefetch_response_inflight_zero_waiters_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_ready_transition_prefetch_response_inflight_zero_waiters_total");
    stat_exp_noc_rowidx_ready_signal_prefetch_response_noninflight_prefetch_only_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_ready_signal_prefetch_response_noninflight_prefetch_only_total");
    stat_exp_noc_rowidx_ready_transition_prefetch_response_noninflight_prefetch_only_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_ready_transition_prefetch_response_noninflight_prefetch_only_total");
    stat_exp_noc_rowidx_detached_demand_join_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_detached_demand_join_total");
    stat_exp_noc_rowidx_detached_demand_waiters_resolved_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_detached_demand_waiters_resolved_total");
    stat_exp_noc_rowidx_detached_demand_fallback_zero_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_detached_demand_fallback_zero_total");
    stat_exp_noc_rowidx_detached_demand_ready_signal_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_detached_demand_ready_signal_total");
    stat_exp_noc_rowidx_detached_demand_ready_transition_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_detached_demand_ready_transition_total");
    stat_exp_noc_rowidx_ready_bypass_experimental_cache_hit_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_ready_bypass_experimental_cache_hit_total");
    stat_exp_noc_rowidx_ready_bypass_rowindex_get_hit_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_ready_bypass_rowindex_get_hit_total");
    stat_exp_noc_rowidx_close_attempt_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_close_attempt_total");
    stat_exp_noc_rowidx_close_attempt_active_owner_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_close_attempt_active_owner_total");
    stat_exp_noc_rowidx_close_attempt_already_pending_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_close_attempt_already_pending_total");
    stat_exp_noc_rowidx_close_attempt_not_active_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_close_attempt_not_active_total");
    stat_exp_noc_rowidx_close_attempt_not_owner_total_ =
        registerStatistic<uint64_t>("exp_noc_rowidx_close_attempt_not_owner_total");
    stat_gcss_lookup_hit_total_ = registerStatistic<uint64_t>("gcss_lookup_hit_total");
    stat_gcss_lookup_miss_total_ = registerStatistic<uint64_t>("gcss_lookup_miss_total");
    stat_weight_read_dense_reqs_total_ = registerStatistic<uint64_t>("weight_read_dense_reqs_total");
    stat_weight_read_dense_bytes_total_ = registerStatistic<uint64_t>("weight_read_dense_bytes_total");
    stat_weight_read_rowptr_reqs_total_ = registerStatistic<uint64_t>("weight_read_rowptr_reqs_total");
    stat_weight_read_rowptr_bytes_total_ = registerStatistic<uint64_t>("weight_read_rowptr_bytes_total");
    stat_weight_read_colidx_reqs_total_ = registerStatistic<uint64_t>("weight_read_colidx_reqs_total");
    stat_weight_read_colidx_bytes_total_ = registerStatistic<uint64_t>("weight_read_colidx_bytes_total");
    stat_weight_read_blockdata_reqs_total_ = registerStatistic<uint64_t>("weight_read_blockdata_reqs_total");
    stat_weight_read_blockdata_bytes_total_ = registerStatistic<uint64_t>("weight_read_blockdata_bytes_total");
    stat_weight_read_gcss_reqs_total_ = registerStatistic<uint64_t>("weight_read_gcss_reqs_total");
    stat_weight_read_gcss_bytes_total_ = registerStatistic<uint64_t>("weight_read_gcss_bytes_total");
    stat_weight_idx_sram_reads_total_ = registerStatistic<uint64_t>("weight_idx_sram_reads_total");
    stat_weight_idx_sram_writes_total_ = registerStatistic<uint64_t>("weight_idx_sram_writes_total");
    stat_weight_idx_sram_bytes_read_total_ = registerStatistic<uint64_t>("weight_idx_sram_bytes_read_total");
    stat_weight_idx_sram_bytes_write_total_ = registerStatistic<uint64_t>("weight_idx_sram_bytes_write_total");
    stat_weight_idx_sram_bank_conflict_ticks_total_ = registerStatistic<uint64_t>("weight_idx_sram_bank_conflict_ticks_total");
    stat_weight_idx_sram_predicted_extra_cycles_total_ = registerStatistic<uint64_t>("weight_idx_sram_predicted_extra_cycles_total");
    stat_weight_idx_sram_resident_bytes_peak_ = registerStatistic<uint64_t>("weight_idx_sram_resident_bytes_peak");
    stat_weight_idx_sram_bank_peak_accesses_per_tick_ = registerStatistic<uint64_t>("weight_idx_sram_bank_peak_accesses_per_tick");
    stat_weight_idx_sram_energy_read_pj_total_ = registerStatistic<uint64_t>("weight_idx_sram_energy_read_pj_total");
    stat_weight_idx_sram_energy_write_pj_total_ = registerStatistic<uint64_t>("weight_idx_sram_energy_write_pj_total");
    stat_weight_idx_lookup_total_ = registerStatistic<uint64_t>("weight_idx_lookup_total");
    stat_weight_idx_lookup_idx2_total_ = registerStatistic<uint64_t>("weight_idx_lookup_idx2_total");
    stat_weight_l0_sram_reads_total_ = registerStatistic<uint64_t>("weight_l0_sram_reads_total");
    stat_weight_l0_sram_writes_total_ = registerStatistic<uint64_t>("weight_l0_sram_writes_total");
    stat_weight_l0_sram_bytes_read_total_ = registerStatistic<uint64_t>("weight_l0_sram_bytes_read_total");
    stat_weight_l0_sram_bytes_write_total_ = registerStatistic<uint64_t>("weight_l0_sram_bytes_write_total");
    stat_weight_l0_sram_bank_conflict_ticks_total_ = registerStatistic<uint64_t>("weight_l0_sram_bank_conflict_ticks_total");
    stat_weight_l0_sram_predicted_extra_cycles_total_ = registerStatistic<uint64_t>("weight_l0_sram_predicted_extra_cycles_total");
    stat_weight_l0_sram_resident_bytes_peak_ = registerStatistic<uint64_t>("weight_l0_sram_resident_bytes_peak");
    stat_weight_l0_sram_bank_peak_accesses_per_tick_ = registerStatistic<uint64_t>("weight_l0_sram_bank_peak_accesses_per_tick");
    stat_weight_l0_sram_energy_read_pj_total_ = registerStatistic<uint64_t>("weight_l0_sram_energy_read_pj_total");
    stat_weight_l0_sram_energy_write_pj_total_ = registerStatistic<uint64_t>("weight_l0_sram_energy_write_pj_total");
    stat_weight_sram_enforced_stall_cycles_total_ = registerStatistic<uint64_t>("weight_sram_enforced_stall_cycles_total");
    stat_weight_l0_lookup_total_ = registerStatistic<uint64_t>("weight_l0_lookup_total");
    stat_weight_l0_hit_total_ = registerStatistic<uint64_t>("weight_l0_hit_total");
    stat_weight_l0_fill_total_ = registerStatistic<uint64_t>("weight_l0_fill_total");
    stat_weight_l0_evict_total_ = registerStatistic<uint64_t>("weight_l0_evict_total");
    stat_core_state_sram_reads_total_ = registerStatistic<uint64_t>("core_state_sram_reads_total");
    stat_core_state_sram_writes_total_ = registerStatistic<uint64_t>("core_state_sram_writes_total");
    stat_core_state_sram_bytes_read_total_ = registerStatistic<uint64_t>("core_state_sram_bytes_read_total");
    stat_core_state_sram_bytes_write_total_ = registerStatistic<uint64_t>("core_state_sram_bytes_write_total");
    stat_core_state_sram_bank_conflict_ticks_total_ = registerStatistic<uint64_t>("core_state_sram_bank_conflict_ticks_total");
    stat_core_state_sram_predicted_extra_cycles_total_ = registerStatistic<uint64_t>("core_state_sram_predicted_extra_cycles_total");
    stat_core_state_sram_resident_bytes_peak_ = registerStatistic<uint64_t>("core_state_sram_resident_bytes_peak");
    stat_core_state_sram_bank_peak_accesses_per_tick_ = registerStatistic<uint64_t>("core_state_sram_bank_peak_accesses_per_tick");
    stat_core_state_sram_energy_read_pj_total_ = registerStatistic<uint64_t>("core_state_sram_energy_read_pj_total");
    stat_core_state_sram_energy_write_pj_total_ = registerStatistic<uint64_t>("core_state_sram_energy_write_pj_total");
    stat_core_state_sram_stall_cycles_total_ = registerStatistic<uint64_t>("core_state_sram_stall_cycles_total");
    stat_riscv_snn_workload_selected_ = registerStatistic<uint64_t>("riscv_snn_workload_selected");
    stat_riscv_snn_firmware_elf_present_ = registerStatistic<uint64_t>("riscv_snn_firmware_elf_present");
    stat_riscv_snn_firmware_loaded_ = registerStatistic<uint64_t>("riscv_snn_firmware_loaded");
    stat_riscv_snn_backend_runtime_bridge_ = registerStatistic<uint64_t>("riscv_snn_backend_runtime_bridge");
    stat_riscv_snn_firmware_started_count_ = registerStatistic<uint64_t>("riscv_snn_firmware_started_count");
    stat_riscv_snn_submitted_commands_ = registerStatistic<uint64_t>("riscv_snn_submitted_commands");
    stat_riscv_snn_accepted_commands_ = registerStatistic<uint64_t>("riscv_snn_accepted_commands");
    stat_riscv_snn_completion_visible_count_ = registerStatistic<uint64_t>("riscv_snn_completion_visible_count");
    stat_riscv_snn_completion_consumed_count_ = registerStatistic<uint64_t>("riscv_snn_completion_consumed_count");
    stat_riscv_snn_fused_step_completion_count_ = registerStatistic<uint64_t>("riscv_snn_fused_step_completion_count");
    stat_riscv_snn_fault_count_ = registerStatistic<uint64_t>("riscv_snn_fault_count");
    stat_riscv_snn_last_completion_status_ = registerStatistic<uint64_t>("riscv_snn_last_completion_status");
    stat_riscv_snn_last_fault_csr_ = registerStatistic<uint64_t>("riscv_snn_last_fault_csr");
    stat_riscv_snn_backend_runtime_bridge_provider_bound_ =
        registerStatistic<uint64_t>("riscv_snn_backend_runtime_bridge_provider_bound");
    stat_gas_activity_f_ = registerStatistic<double>("gas_activity_f");
    stat_sim_cycles_total_ = registerStatistic<uint64_t>("sim_cycles_total");
    stat_compute_active_cycles_total_ = registerStatistic<uint64_t>("compute_active_cycles_total");
    stat_global_steps_done_total_ = registerStatistic<uint64_t>("global_steps_done_total");
    stat_step_activation_invocations_ = registerStatistic<uint64_t>("step_activation_invocations");
    stat_step_activation_pre_selected_ = registerStatistic<uint64_t>("step_activation_pre_selected");
    stat_step_activation_spike_attempts_ = registerStatistic<uint64_t>("step_activation_spike_attempts");
    stat_step_activation_spikes_injected_ = registerStatistic<uint64_t>("step_activation_spikes_injected");
    stat_step_activation_route_hits_ = registerStatistic<uint64_t>("step_activation_route_hits");
    stat_step_activation_route_misses_ = registerStatistic<uint64_t>("step_activation_route_misses");
    stat_step_activation_local_drops_ = registerStatistic<uint64_t>("step_activation_local_drops");

}

void MultiCorePE::accumulateRiscvSnnRuntimeStats(uint64_t workload_selected,
                                                 uint64_t firmware_elf_present,
                                                 uint64_t firmware_loaded,
                                                 uint64_t backend_runtime_bridge,
                                                 uint64_t firmware_started_count,
                                                 uint64_t submitted_commands,
                                                 uint64_t accepted_commands,
                                                 uint64_t completion_visible_count,
                                                 uint64_t completion_consumed_count,
                                                 uint64_t fused_step_completion_count,
                                                 uint64_t fault_count,
                                                 uint64_t last_completion_status,
                                                 uint64_t last_fault_csr,
                                                 uint64_t backend_runtime_bridge_provider_bound) {
    if (stat_riscv_snn_workload_selected_) {
        stat_riscv_snn_workload_selected_->addData(workload_selected);
    }
    if (stat_riscv_snn_firmware_elf_present_) {
        stat_riscv_snn_firmware_elf_present_->addData(firmware_elf_present);
    }
    if (stat_riscv_snn_firmware_loaded_) {
        stat_riscv_snn_firmware_loaded_->addData(firmware_loaded);
    }
    if (stat_riscv_snn_backend_runtime_bridge_) {
        stat_riscv_snn_backend_runtime_bridge_->addData(backend_runtime_bridge);
    }
    if (stat_riscv_snn_firmware_started_count_) {
        stat_riscv_snn_firmware_started_count_->addData(firmware_started_count);
    }
    if (stat_riscv_snn_submitted_commands_) {
        stat_riscv_snn_submitted_commands_->addData(submitted_commands);
    }
    if (stat_riscv_snn_accepted_commands_) {
        stat_riscv_snn_accepted_commands_->addData(accepted_commands);
    }
    if (stat_riscv_snn_completion_visible_count_) {
        stat_riscv_snn_completion_visible_count_->addData(completion_visible_count);
    }
    if (stat_riscv_snn_completion_consumed_count_) {
        stat_riscv_snn_completion_consumed_count_->addData(completion_consumed_count);
    }
    if (stat_riscv_snn_fused_step_completion_count_) {
        stat_riscv_snn_fused_step_completion_count_->addData(fused_step_completion_count);
    }
    if (stat_riscv_snn_fault_count_) {
        stat_riscv_snn_fault_count_->addData(fault_count);
    }
    if (stat_riscv_snn_last_completion_status_) {
        stat_riscv_snn_last_completion_status_->addData(last_completion_status);
    }
    if (stat_riscv_snn_last_fault_csr_) {
        stat_riscv_snn_last_fault_csr_->addData(last_fault_csr);
    }
    if (stat_riscv_snn_backend_runtime_bridge_provider_bound_) {
        stat_riscv_snn_backend_runtime_bridge_provider_bound_->addData(
            backend_runtime_bridge_provider_bound);
    }
}

void MultiCorePE::accumulateMemReadLatency(uint64_t latency_cycles, bool is_weight) {
    if (stat_mem_read_latency_cycles_) stat_mem_read_latency_cycles_->addData(latency_cycles);
    if (is_weight) {
        if (stat_mem_read_latency_cycles_weights_) stat_mem_read_latency_cycles_weights_->addData(latency_cycles);
    } else {
        if (stat_mem_read_latency_cycles_state_) stat_mem_read_latency_cycles_state_->addData(latency_cycles);
    }
    // 窗口化：按当前仿真时间(ns)聚合响应时延
    if (window_stats_enable_) {
        uint64_t now_ns = getCurrentSimTimeNano();
        WindowAgg& w = getOrCreateWindow_(now_ns);
        w.read_count += 1;
        w.read_latency_sum += latency_cycles;
    }
}

void MultiCorePE::accumulateIssueStats(uint64_t req_size_bytes, uint64_t inflight) {
    if (stat_mem_req_size_bytes_) stat_mem_req_size_bytes_->addData(req_size_bytes);
    if (stat_mem_outstanding_at_issue_) stat_mem_outstanding_at_issue_->addData(inflight);
    if (stat_memory_requests_) stat_memory_requests_->addData(1);
    // 窗口化：按当前仿真时间(ns)聚合发起侧指标
    if (window_stats_enable_) {
        uint64_t now_ns = getCurrentSimTimeNano();
        WindowAgg& w = getOrCreateWindow_(now_ns);
        w.issue_count += 1;
        w.req_size_sum += req_size_bytes;
        w.outstanding_sum += inflight;
    }
}

void MultiCorePE::accumulateGasStats(uint64_t unique_bytes, uint64_t unique_reads) {
    if (unique_reads && stat_gas_unique_reads_total_) stat_gas_unique_reads_total_->addData(unique_reads);
    if (unique_bytes && stat_gas_unique_bytes_total_) stat_gas_unique_bytes_total_->addData(unique_bytes);
}

void MultiCorePE::accumulateGasStatsExt(uint64_t unique_bytes, uint64_t unique_reads,
                                        uint64_t rowwin_triggers, uint64_t rowwin_bytes,
                                        uint64_t bursts, uint64_t payload_bytes,
                                        uint64_t window_inflight_peak,
                                        uint64_t window_buffer_max_bytes,
                                        uint64_t frontend_staged_reads,
                                        uint64_t frontend_staged_line_touches,
                                        uint64_t frontend_granules_built,
                                        uint64_t unique_line_count,
                                        uint64_t covered_line_count,
                                        uint64_t overfetch_bytes,
                                        uint64_t apply_bank_credit_effective,
                                        uint64_t cmd_cost_veto,
                                        uint64_t cmd_cost_veto_fine_gap,
                                        uint64_t cmd_cost_veto_row_window,
                                        uint64_t stall_on_step_gate_cycles) {
    accumulateGasStats(unique_bytes, unique_reads);
    if (rowwin_triggers && stat_gas_rowwin_triggers_total_) stat_gas_rowwin_triggers_total_->addData(rowwin_triggers);
    if (rowwin_bytes && stat_gas_rowwin_bytes_total_) stat_gas_rowwin_bytes_total_->addData(rowwin_bytes);
    if (bursts && stat_gas_total_bursts_) stat_gas_total_bursts_->addData(bursts);
    if (payload_bytes && stat_gas_total_payload_bytes_) stat_gas_total_payload_bytes_->addData(payload_bytes);
    if (frontend_staged_reads && stat_gas_frontend_staged_reads_total_) stat_gas_frontend_staged_reads_total_->addData(frontend_staged_reads);
    if (frontend_staged_line_touches && stat_gas_frontend_staged_line_touches_total_) stat_gas_frontend_staged_line_touches_total_->addData(frontend_staged_line_touches);
    if (frontend_granules_built && stat_gas_frontend_granules_built_total_) stat_gas_frontend_granules_built_total_->addData(frontend_granules_built);
    if (unique_line_count && stat_gas_unique_line_count_total_) stat_gas_unique_line_count_total_->addData(unique_line_count);
    if (covered_line_count && stat_gas_covered_line_count_total_) stat_gas_covered_line_count_total_->addData(covered_line_count);
    if (overfetch_bytes && stat_gas_overfetch_bytes_total_) stat_gas_overfetch_bytes_total_->addData(overfetch_bytes);
    if (apply_bank_credit_effective && stat_gas_apply_bank_credit_effective_total_) stat_gas_apply_bank_credit_effective_total_->addData(apply_bank_credit_effective);
    if (cmd_cost_veto && stat_gas_cmd_cost_veto_total_) stat_gas_cmd_cost_veto_total_->addData(cmd_cost_veto);
    if (cmd_cost_veto_fine_gap && stat_gas_cmd_cost_veto_fine_gap_total_) stat_gas_cmd_cost_veto_fine_gap_total_->addData(cmd_cost_veto_fine_gap);
    if (cmd_cost_veto_row_window && stat_gas_cmd_cost_veto_row_window_total_) stat_gas_cmd_cost_veto_row_window_total_->addData(cmd_cost_veto_row_window);
    if (stall_on_step_gate_cycles && stat_stall_on_step_gate_cycles_total_) {
        stat_stall_on_step_gate_cycles_total_->addData(stall_on_step_gate_cycles);
    }
}

void MultiCorePE::accumulateActivityF(double f) {
    if (stat_gas_activity_f_) stat_gas_activity_f_->addData(f);
    if (window_stats_enable_) {
        uint64_t now_ns = getCurrentSimTimeNano();
        WindowAgg& w = getOrCreateWindow_(now_ns);
        w.activity_f_sum += f;
        w.activity_f_count += 1;
    }
}

void MultiCorePE::accumulateApplyScatterStats(uint64_t acc_updates, uint64_t posts_touched,
                                              uint64_t spikes_emitted, uint64_t hwm_bytes,
                                              uint64_t spill_records, uint64_t spilled_bytes) {
    if (acc_updates && stat_gas_apply_acc_updates_total_) stat_gas_apply_acc_updates_total_->addData(acc_updates);
    if (posts_touched && stat_gas_acc_posts_touched_total_) stat_gas_acc_posts_touched_total_->addData(posts_touched);
    if (spikes_emitted && stat_gas_scatter_spikes_emitted_total_) stat_gas_scatter_spikes_emitted_total_->addData(spikes_emitted);
    if (hwm_bytes && stat_gas_acc_hwm_bytes_total_) stat_gas_acc_hwm_bytes_total_->addData(hwm_bytes);
    if (spill_records && stat_gas_acc_spill_records_total_) stat_gas_acc_spill_records_total_->addData(spill_records);
    if (spilled_bytes && stat_gas_acc_spilled_bytes_total_) stat_gas_acc_spilled_bytes_total_->addData(spilled_bytes);
}

MultiCorePE::StepPerfAgg& MultiCorePE::getOrCreateStepPerf_(uint32_t seq) {
    return step_perf_[seq];
}

MultiCorePE::StepPerfAgg& MultiCorePE::getOrCreateCoreStepPerf_(int core_id, uint32_t seq) {
    return core_step_perf_[CoreStepKey{core_id, seq}];
}

MultiCorePE::StageMarks& MultiCorePE::getOrCreateCoreStageMarks_(int core_id, uint32_t seq) {
    return core_stage_marks_[CoreStepKey{core_id, seq}];
}

void MultiCorePE::recordStepActivationSummary(uint32_t seq,
                                              uint64_t pre_selected,
                                              uint64_t spike_attempts,
                                              uint64_t spikes_injected,
                                              uint64_t route_hits,
                                              uint64_t route_misses,
                                              uint64_t local_drops) {
    if (seq == 0) return;
    auto& perf = getOrCreateStepPerf_(seq);
    perf.seed_pre_selected += pre_selected;
    perf.seed_spike_attempts += spike_attempts;
    perf.seed_spikes_injected += spikes_injected;
    perf.seed_route_hits += route_hits;
    perf.seed_route_misses += route_misses;
    perf.seed_local_drops += local_drops;
}

void MultiCorePE::recordStepRxPacket(uint32_t seq, NocPacketKind kind, bool is_local, bool before_begin_gather) {
    if (seq == 0) return;
    auto& perf = getOrCreateStepPerf_(seq);
    perf.rx_packets_total += 1;
    if (is_local) perf.rx_local_packets_total += 1;
    else perf.rx_remote_packets_total += 1;
    if (before_begin_gather) {
        perf.rx_packets_before_bg_total += 1;
        if (is_local) perf.rx_local_packets_before_bg_total += 1;
        else perf.rx_remote_packets_before_bg_total += 1;
        if (perf.rx_packets_before_bg_total > perf.rx_gate_pending_peak) {
            perf.rx_gate_pending_peak = perf.rx_packets_before_bg_total;
        }
    } else {
        auto stage_it = stage_marks_.find(seq);
        int stage_code = 0;
        if (stage_it != stage_marks_.end()) {
            const auto& m = stage_it->second;
            if (m.bs != 0) stage_code = 3;
            else if (m.ga != 0) stage_code = 2;
            else if (m.bg != 0) stage_code = 1;
        }
        if (stage_code == 1) perf.rx_packets_during_gather_total += 1;
        else if (stage_code == 2) perf.rx_packets_during_apply_total += 1;
        else if (stage_code == 3) perf.rx_packets_during_scatter_total += 1;
    }
    switch (kind) {
        case NocPacketKind::Spike:
            perf.rx_spike_packets_total += 1;
            break;
        case NocPacketKind::SpikeKey:
            perf.rx_spikekey_packets_total += 1;
            break;
        case NocPacketKind::SpikeTileKey:
            perf.rx_spiketilekey_packets_total += 1;
            break;
        default:
            break;
    }
}

void MultiCorePE::recordStepRxGate(uint32_t seq,
                                   uint64_t accept_total,
                                   uint64_t reject_refractory_total,
                                   uint64_t direct_accept_total,
                                   uint64_t direct_reject_refractory_total,
                                   uint64_t fastpath_accept_total,
                                   uint64_t fastpath_reject_refractory_total) {
    if (seq == 0) return;
    auto& perf = getOrCreateStepPerf_(seq);
    perf.rx_gate_accept_total += accept_total;
    perf.rx_gate_reject_refractory_total += reject_refractory_total;
    perf.rx_gate_direct_accept_total += direct_accept_total;
    perf.rx_gate_direct_reject_refractory_total += direct_reject_refractory_total;
    perf.rx_gate_fastpath_accept_total += fastpath_accept_total;
    perf.rx_gate_fastpath_reject_refractory_total += fastpath_reject_refractory_total;
}

void MultiCorePE::recordStepGasStat(uint32_t seq, const GasStatEvent& st) {
    if (seq == 0) return;
    auto& perf = getOrCreateStepPerf_(seq);
    perf.unique_reads += st.unique_reads;
    perf.unique_bytes += st.unique_bytes;
    perf.rowwin_triggers += st.rowwin_triggers;
    perf.rowwin_bytes += st.rowwin_bytes;
    perf.bursts += st.bursts;
    perf.payload_bytes += st.payload_bytes;
    perf.window_inflight_peak = std::max<uint64_t>(perf.window_inflight_peak, st.window_inflight_peak);
    perf.window_buffer_max_bytes = std::max<uint64_t>(perf.window_buffer_max_bytes, st.window_buffer_max_bytes);
    perf.gap_absorbed_bytes += st.gap_absorbed_bytes;
    perf.frontend_staged_reads += st.frontend_staged_reads;
    perf.frontend_staged_line_touches += st.frontend_staged_line_touches;
    perf.frontend_granules_built += st.frontend_granules_built;
    perf.unique_line_count += st.unique_line_count;
    perf.covered_line_count += st.covered_line_count;
    perf.overfetch_bytes += st.overfetch_bytes;
    perf.apply_bank_credit_effective += st.apply_bank_credit_effective;
    perf.cmd_cost_veto += st.cmd_cost_veto;
    perf.cmd_cost_veto_fine_gap += st.cmd_cost_veto_fine_gap;
    perf.cmd_cost_veto_row_window += st.cmd_cost_veto_row_window;
    perf.apply_issue_attempt_total += st.apply_issue_attempt_total;
    perf.apply_issue_success_total += st.apply_issue_success_total;
    perf.apply_issue_block_no_ready_total += st.apply_issue_block_no_ready_total;
    perf.apply_issue_block_inflight_cap_total += st.apply_issue_block_inflight_cap_total;
    perf.apply_issue_block_bank_credit_total += st.apply_issue_block_bank_credit_total;
    perf.apply_issue_block_downstream_busy_total += st.apply_issue_block_downstream_busy_total;
    perf.apply_issue_block_retire_guard_total += st.apply_issue_block_retire_guard_total;
    perf.apply_ready_queue_peak = std::max<uint64_t>(perf.apply_ready_queue_peak, st.apply_ready_queue_peak);
    perf.apply_ready_queue_nonempty_cycles_total += st.apply_ready_queue_nonempty_cycles_total;
    perf.apply_first_issue_delay_ns += st.apply_first_issue_delay_ns;
    perf.apply_first_down_resp_delay_ns += st.apply_first_down_resp_delay_ns;
    perf.apply_first_granule_done_delay_ns += st.apply_first_granule_done_delay_ns;
    perf.apply_first_up_resp_delay_ns += st.apply_first_up_resp_delay_ns;
    perf.apply_down_resp_total += st.apply_down_resp_total;
    perf.apply_completed_granules_total += st.apply_completed_granules_total;
    perf.apply_emitted_subreads_total += st.apply_emitted_subreads_total;
    perf.apply_backlog_granules_residual =
        std::max<uint64_t>(perf.apply_backlog_granules_residual, st.apply_backlog_granules_residual);
    perf.apply_backlog_pending_up_reads_residual =
        std::max<uint64_t>(perf.apply_backlog_pending_up_reads_residual,
                           st.apply_backlog_pending_up_reads_residual);
    perf.apply_backlog_inflight_residual =
        std::max<uint64_t>(perf.apply_backlog_inflight_residual, st.apply_backlog_inflight_residual);
    perf.apply_backlog_granules_peak_after_due =
        std::max<uint64_t>(perf.apply_backlog_granules_peak_after_due,
                           st.apply_backlog_granules_peak_after_due);
    perf.apply_backlog_pending_up_reads_peak_after_due =
        std::max<uint64_t>(perf.apply_backlog_pending_up_reads_peak_after_due,
                           st.apply_backlog_pending_up_reads_peak_after_due);
    perf.apply_backlog_inflight_peak_after_due =
        std::max<uint64_t>(perf.apply_backlog_inflight_peak_after_due,
                           st.apply_backlog_inflight_peak_after_due);
}

void MultiCorePE::recordCoreStepGasStat(int core_id, uint32_t seq, const GasStatEvent& st) {
    if (seq == 0 || core_id < 0) return;
    auto& perf = getOrCreateCoreStepPerf_(core_id, seq);
    perf.unique_reads += st.unique_reads;
    perf.unique_bytes += st.unique_bytes;
    perf.rowwin_triggers += st.rowwin_triggers;
    perf.rowwin_bytes += st.rowwin_bytes;
    perf.bursts += st.bursts;
    perf.payload_bytes += st.payload_bytes;
    perf.window_inflight_peak = std::max<uint64_t>(perf.window_inflight_peak, st.window_inflight_peak);
    perf.window_buffer_max_bytes = std::max<uint64_t>(perf.window_buffer_max_bytes, st.window_buffer_max_bytes);
    perf.gap_absorbed_bytes += st.gap_absorbed_bytes;
    perf.frontend_staged_reads += st.frontend_staged_reads;
    perf.frontend_staged_line_touches += st.frontend_staged_line_touches;
    perf.frontend_granules_built += st.frontend_granules_built;
    perf.unique_line_count += st.unique_line_count;
    perf.covered_line_count += st.covered_line_count;
    perf.overfetch_bytes += st.overfetch_bytes;
    perf.apply_bank_credit_effective += st.apply_bank_credit_effective;
    perf.cmd_cost_veto += st.cmd_cost_veto;
    perf.cmd_cost_veto_fine_gap += st.cmd_cost_veto_fine_gap;
    perf.cmd_cost_veto_row_window += st.cmd_cost_veto_row_window;
    perf.apply_issue_attempt_total += st.apply_issue_attempt_total;
    perf.apply_issue_success_total += st.apply_issue_success_total;
    perf.apply_issue_block_no_ready_total += st.apply_issue_block_no_ready_total;
    perf.apply_issue_block_inflight_cap_total += st.apply_issue_block_inflight_cap_total;
    perf.apply_issue_block_bank_credit_total += st.apply_issue_block_bank_credit_total;
    perf.apply_issue_block_downstream_busy_total += st.apply_issue_block_downstream_busy_total;
    perf.apply_issue_block_retire_guard_total += st.apply_issue_block_retire_guard_total;
    perf.apply_ready_queue_peak = std::max<uint64_t>(perf.apply_ready_queue_peak, st.apply_ready_queue_peak);
    perf.apply_ready_queue_nonempty_cycles_total += st.apply_ready_queue_nonempty_cycles_total;
    perf.apply_first_issue_delay_ns += st.apply_first_issue_delay_ns;
    perf.apply_first_down_resp_delay_ns += st.apply_first_down_resp_delay_ns;
    perf.apply_first_granule_done_delay_ns += st.apply_first_granule_done_delay_ns;
    perf.apply_first_up_resp_delay_ns += st.apply_first_up_resp_delay_ns;
    perf.apply_down_resp_total += st.apply_down_resp_total;
    perf.apply_completed_granules_total += st.apply_completed_granules_total;
    perf.apply_emitted_subreads_total += st.apply_emitted_subreads_total;
    perf.apply_backlog_granules_residual =
        std::max<uint64_t>(perf.apply_backlog_granules_residual, st.apply_backlog_granules_residual);
    perf.apply_backlog_pending_up_reads_residual =
        std::max<uint64_t>(perf.apply_backlog_pending_up_reads_residual,
                           st.apply_backlog_pending_up_reads_residual);
    perf.apply_backlog_inflight_residual =
        std::max<uint64_t>(perf.apply_backlog_inflight_residual, st.apply_backlog_inflight_residual);
    perf.apply_backlog_granules_peak_after_due =
        std::max<uint64_t>(perf.apply_backlog_granules_peak_after_due,
                           st.apply_backlog_granules_peak_after_due);
    perf.apply_backlog_pending_up_reads_peak_after_due =
        std::max<uint64_t>(perf.apply_backlog_pending_up_reads_peak_after_due,
                           st.apply_backlog_pending_up_reads_peak_after_due);
    perf.apply_backlog_inflight_peak_after_due =
        std::max<uint64_t>(perf.apply_backlog_inflight_peak_after_due,
                           st.apply_backlog_inflight_peak_after_due);
}

void MultiCorePE::recordStepRetireStat(uint32_t seq,
                                       uint64_t retire_global_hol_cycles_total,
                                       uint64_t retire_ready_but_blocked_edges_total,
                                       uint64_t retire_per_post_progress_total,
                                       uint64_t retire_wait_cycles_total,
                                       uint64_t retire_wait_cycles_due_to_hol_total,
                                       uint64_t retire_wait_cycles_due_to_barrier_total,
                                       uint64_t retire_wait_cycles_due_to_not_ready_total,
                                       uint64_t retire_samepost_blocked_edges_total,
                                       uint64_t retire_crosspost_blocked_edges_total,
                                       uint64_t retire_policy_loss_cycles_total,
                                       uint64_t retire_policy_loss_edges_total,
                                       uint64_t retire_shadow_per_post_recoverable_cycles_total,
                                       uint64_t retire_shadow_per_post_recoverable_edges_total,
                                       uint64_t retire_shadow_per_post_ready_posts_peak,
                                       uint64_t retire_shadow_per_post_committable_edges_peak,
                                       uint64_t retire_head_hol_cycles_dense_total,
                                       uint64_t retire_head_hol_cycles_cache_total,
                                       uint64_t retire_head_hol_cycles_miss_total,
                                       uint64_t retire_head_hol_cycles_bcsr_total,
                                       uint64_t retire_head_hol_cycles_bcsr_file_total,
                                       uint64_t retire_head_hol_cycles_gcss_total,
                                       uint64_t retire_head_blocked_edges_dense_total,
                                       uint64_t retire_head_blocked_edges_cache_total,
                                       uint64_t retire_head_blocked_edges_miss_total,
                                       uint64_t retire_head_blocked_edges_bcsr_total,
                                       uint64_t retire_head_blocked_edges_bcsr_file_total,
                                       uint64_t retire_head_blocked_edges_gcss_total,
                                       uint64_t retire_gcss_head_queued_not_issued_cycles_total,
                                       uint64_t retire_gcss_qni_head_wait_episodes_total,
                                       uint64_t retire_gcss_qni_head_wait_cycles_max,
                                       uint64_t retire_gcss_head_queued_not_issued_blocked_edges_total,
                                       uint64_t retire_gcss_head_issued_wait_resp_cycles_total,
                                       uint64_t retire_gcss_head_issued_wait_resp_blocked_edges_total,
                                       uint64_t retire_gcss_resp_ready_but_hol_cycles_total,
                                       uint64_t retire_gcss_resp_ready_but_hol_blocked_edges_total,
                                       uint64_t retire_gcss_qni_loader_not_ready_cycles_total,
                                       uint64_t retire_gcss_qni_loader_not_ready_blocked_edges_total,
                                       uint64_t retire_gcss_qni_weight_sram_stall_cycles_total,
                                       uint64_t retire_gcss_qni_weight_sram_stall_blocked_edges_total,
                                       uint64_t retire_gcss_qni_vlf_younger_ahead_cycles_total,
                                       uint64_t retire_gcss_qni_vlf_younger_ahead_blocked_edges_total,
                                       uint64_t retire_gcss_qni_vlf_younger_ahead_depth_total,
                                       uint64_t retire_gcss_qni_vlf_younger_ahead_depth_samples_total,
                                       uint64_t retire_gcss_qni_vlf_younger_ahead_depth_max,
                                       uint64_t retire_gcss_qni_issue_deferred_total,
                                       uint64_t retire_gcss_qni_pending_direct_queue_residency_cycles_total,
                                       uint64_t retire_gcss_qni_pending_direct_queue_residency_samples_total,
                                       uint64_t retire_gcss_qni_pending_direct_queue_residency_cycles_max,
                                       uint64_t retire_gcss_qni_vlf_front_inflight_full_cycles_total,
                                       uint64_t retire_gcss_qni_vlf_front_inflight_full_blocked_edges_total,
                                       uint64_t retire_gcss_qni_vlf_front_waiting_issue_cycles_total,
                                       uint64_t retire_gcss_qni_vlf_front_waiting_issue_blocked_edges_total,
                                       uint64_t retire_gcss_qni_pending_younger_ahead_cycles_total,
                                       uint64_t retire_gcss_qni_pending_younger_ahead_blocked_edges_total,
                                       uint64_t retire_gcss_qni_pending_front_inflight_full_cycles_total,
                                       uint64_t retire_gcss_qni_pending_front_inflight_full_blocked_edges_total,
                                       uint64_t retire_gcss_qni_pending_front_waiting_tick_cycles_total,
                                       uint64_t retire_gcss_qni_pending_front_waiting_tick_blocked_edges_total,
                                       uint64_t retire_gcss_qni_unknown_cycles_total,
                                       uint64_t retire_gcss_qni_unknown_blocked_edges_total,
                                       uint64_t retire_begin_apply_windows_total,
                                       uint64_t retire_begin_apply_prev_edges_total,
                                       uint64_t retire_begin_apply_outstanding_carryin_total,
                                       uint64_t retire_begin_apply_outstanding_carryin_windows_total,
                                       uint64_t retire_begin_apply_loader_not_ready_windows_total,
                                       uint64_t retire_edge_retire_registered_total,
                                       uint64_t retire_edge_retire_retired_total,
                                       uint64_t retire_end_scatter_gcss_vlf_issue_queue_residual_total,
                                       uint64_t retire_end_scatter_pending_direct_reads_residual_total,
                                       uint64_t retire_end_scatter_outstanding_residual_total,
                                       uint64_t retire_end_scatter_residual_work_windows_total,
                                       uint64_t retire_gcss_vlf_issue_prepare_total,
                                       uint64_t retire_gcss_vlf_issue_edges_total,
                                       uint64_t retire_gcss_vlf_issue_reorder_trigger_total,
                                       uint64_t retire_gcss_vlf_issue_line_groups_total,
                                       uint64_t retire_ready_queue_peak,
                                       uint64_t retire_unblock_events_total) {
    if (seq == 0) return;
    auto& perf = getOrCreateStepPerf_(seq);
    perf.retire_global_hol_cycles_total += retire_global_hol_cycles_total;
    perf.retire_ready_but_blocked_edges_total += retire_ready_but_blocked_edges_total;
    perf.retire_per_post_progress_total += retire_per_post_progress_total;
    perf.retire_wait_cycles_total += retire_wait_cycles_total;
    perf.retire_wait_cycles_due_to_hol_total += retire_wait_cycles_due_to_hol_total;
    perf.retire_wait_cycles_due_to_barrier_total += retire_wait_cycles_due_to_barrier_total;
    perf.retire_wait_cycles_due_to_not_ready_total += retire_wait_cycles_due_to_not_ready_total;
    perf.retire_samepost_blocked_edges_total += retire_samepost_blocked_edges_total;
    perf.retire_crosspost_blocked_edges_total += retire_crosspost_blocked_edges_total;
    perf.retire_policy_loss_cycles_total += retire_policy_loss_cycles_total;
    perf.retire_policy_loss_edges_total += retire_policy_loss_edges_total;
    perf.retire_shadow_per_post_recoverable_cycles_total += retire_shadow_per_post_recoverable_cycles_total;
    perf.retire_shadow_per_post_recoverable_edges_total += retire_shadow_per_post_recoverable_edges_total;
    perf.retire_shadow_per_post_ready_posts_peak =
        std::max<uint64_t>(perf.retire_shadow_per_post_ready_posts_peak, retire_shadow_per_post_ready_posts_peak);
    perf.retire_shadow_per_post_committable_edges_peak =
        std::max<uint64_t>(perf.retire_shadow_per_post_committable_edges_peak, retire_shadow_per_post_committable_edges_peak);
    perf.retire_head_hol_cycles_dense_total += retire_head_hol_cycles_dense_total;
    perf.retire_head_hol_cycles_cache_total += retire_head_hol_cycles_cache_total;
    perf.retire_head_hol_cycles_miss_total += retire_head_hol_cycles_miss_total;
    perf.retire_head_hol_cycles_bcsr_total += retire_head_hol_cycles_bcsr_total;
    perf.retire_head_hol_cycles_bcsr_file_total += retire_head_hol_cycles_bcsr_file_total;
    perf.retire_head_hol_cycles_gcss_total += retire_head_hol_cycles_gcss_total;
    perf.retire_head_blocked_edges_dense_total += retire_head_blocked_edges_dense_total;
    perf.retire_head_blocked_edges_cache_total += retire_head_blocked_edges_cache_total;
    perf.retire_head_blocked_edges_miss_total += retire_head_blocked_edges_miss_total;
    perf.retire_head_blocked_edges_bcsr_total += retire_head_blocked_edges_bcsr_total;
    perf.retire_head_blocked_edges_bcsr_file_total += retire_head_blocked_edges_bcsr_file_total;
    perf.retire_head_blocked_edges_gcss_total += retire_head_blocked_edges_gcss_total;
    perf.retire_gcss_head_queued_not_issued_cycles_total += retire_gcss_head_queued_not_issued_cycles_total;
    perf.retire_gcss_qni_head_wait_episodes_total += retire_gcss_qni_head_wait_episodes_total;
    perf.retire_gcss_qni_head_wait_cycles_max = std::max<uint64_t>(
        perf.retire_gcss_qni_head_wait_cycles_max, retire_gcss_qni_head_wait_cycles_max);
    perf.retire_gcss_head_queued_not_issued_blocked_edges_total += retire_gcss_head_queued_not_issued_blocked_edges_total;
    perf.retire_gcss_head_issued_wait_resp_cycles_total += retire_gcss_head_issued_wait_resp_cycles_total;
    perf.retire_gcss_head_issued_wait_resp_blocked_edges_total += retire_gcss_head_issued_wait_resp_blocked_edges_total;
    perf.retire_gcss_resp_ready_but_hol_cycles_total += retire_gcss_resp_ready_but_hol_cycles_total;
    perf.retire_gcss_resp_ready_but_hol_blocked_edges_total += retire_gcss_resp_ready_but_hol_blocked_edges_total;
    perf.retire_gcss_qni_loader_not_ready_cycles_total += retire_gcss_qni_loader_not_ready_cycles_total;
    perf.retire_gcss_qni_loader_not_ready_blocked_edges_total += retire_gcss_qni_loader_not_ready_blocked_edges_total;
    perf.retire_gcss_qni_weight_sram_stall_cycles_total += retire_gcss_qni_weight_sram_stall_cycles_total;
    perf.retire_gcss_qni_weight_sram_stall_blocked_edges_total += retire_gcss_qni_weight_sram_stall_blocked_edges_total;
    perf.retire_gcss_qni_vlf_younger_ahead_cycles_total += retire_gcss_qni_vlf_younger_ahead_cycles_total;
    perf.retire_gcss_qni_vlf_younger_ahead_blocked_edges_total += retire_gcss_qni_vlf_younger_ahead_blocked_edges_total;
    perf.retire_gcss_qni_vlf_younger_ahead_depth_total += retire_gcss_qni_vlf_younger_ahead_depth_total;
    perf.retire_gcss_qni_vlf_younger_ahead_depth_samples_total += retire_gcss_qni_vlf_younger_ahead_depth_samples_total;
    perf.retire_gcss_qni_vlf_younger_ahead_depth_max = std::max<uint64_t>(
        perf.retire_gcss_qni_vlf_younger_ahead_depth_max,
        retire_gcss_qni_vlf_younger_ahead_depth_max);
    perf.retire_gcss_qni_issue_deferred_total += retire_gcss_qni_issue_deferred_total;
    perf.retire_gcss_qni_pending_direct_queue_residency_cycles_total +=
        retire_gcss_qni_pending_direct_queue_residency_cycles_total;
    perf.retire_gcss_qni_pending_direct_queue_residency_samples_total +=
        retire_gcss_qni_pending_direct_queue_residency_samples_total;
    perf.retire_gcss_qni_pending_direct_queue_residency_cycles_max = std::max<uint64_t>(
        perf.retire_gcss_qni_pending_direct_queue_residency_cycles_max,
        retire_gcss_qni_pending_direct_queue_residency_cycles_max);
    perf.retire_gcss_qni_vlf_front_inflight_full_cycles_total += retire_gcss_qni_vlf_front_inflight_full_cycles_total;
    perf.retire_gcss_qni_vlf_front_inflight_full_blocked_edges_total += retire_gcss_qni_vlf_front_inflight_full_blocked_edges_total;
    perf.retire_gcss_qni_vlf_front_waiting_issue_cycles_total += retire_gcss_qni_vlf_front_waiting_issue_cycles_total;
    perf.retire_gcss_qni_vlf_front_waiting_issue_blocked_edges_total += retire_gcss_qni_vlf_front_waiting_issue_blocked_edges_total;
    perf.retire_gcss_qni_pending_younger_ahead_cycles_total += retire_gcss_qni_pending_younger_ahead_cycles_total;
    perf.retire_gcss_qni_pending_younger_ahead_blocked_edges_total += retire_gcss_qni_pending_younger_ahead_blocked_edges_total;
    perf.retire_gcss_qni_pending_front_inflight_full_cycles_total += retire_gcss_qni_pending_front_inflight_full_cycles_total;
    perf.retire_gcss_qni_pending_front_inflight_full_blocked_edges_total += retire_gcss_qni_pending_front_inflight_full_blocked_edges_total;
    perf.retire_gcss_qni_pending_front_waiting_tick_cycles_total += retire_gcss_qni_pending_front_waiting_tick_cycles_total;
    perf.retire_gcss_qni_pending_front_waiting_tick_blocked_edges_total += retire_gcss_qni_pending_front_waiting_tick_blocked_edges_total;
    perf.retire_gcss_qni_unknown_cycles_total += retire_gcss_qni_unknown_cycles_total;
    perf.retire_gcss_qni_unknown_blocked_edges_total += retire_gcss_qni_unknown_blocked_edges_total;
    perf.retire_begin_apply_windows_total += retire_begin_apply_windows_total;
    perf.retire_begin_apply_prev_edges_total += retire_begin_apply_prev_edges_total;
    perf.retire_begin_apply_outstanding_carryin_total += retire_begin_apply_outstanding_carryin_total;
    perf.retire_begin_apply_outstanding_carryin_windows_total +=
        retire_begin_apply_outstanding_carryin_windows_total;
    perf.retire_begin_apply_loader_not_ready_windows_total +=
        retire_begin_apply_loader_not_ready_windows_total;
    perf.retire_edge_retire_registered_total += retire_edge_retire_registered_total;
    perf.retire_edge_retire_retired_total += retire_edge_retire_retired_total;
    perf.retire_end_scatter_gcss_vlf_issue_queue_residual_total +=
        retire_end_scatter_gcss_vlf_issue_queue_residual_total;
    perf.retire_end_scatter_pending_direct_reads_residual_total +=
        retire_end_scatter_pending_direct_reads_residual_total;
    perf.retire_end_scatter_outstanding_residual_total +=
        retire_end_scatter_outstanding_residual_total;
    perf.retire_end_scatter_residual_work_windows_total +=
        retire_end_scatter_residual_work_windows_total;
    perf.retire_gcss_vlf_issue_prepare_total += retire_gcss_vlf_issue_prepare_total;
    perf.retire_gcss_vlf_issue_edges_total += retire_gcss_vlf_issue_edges_total;
    perf.retire_gcss_vlf_issue_reorder_trigger_total += retire_gcss_vlf_issue_reorder_trigger_total;
    perf.retire_gcss_vlf_issue_line_groups_total += retire_gcss_vlf_issue_line_groups_total;
    perf.retire_ready_queue_peak = std::max<uint64_t>(perf.retire_ready_queue_peak, retire_ready_queue_peak);
    perf.retire_unblock_events_total += retire_unblock_events_total;
}

void MultiCorePE::recordPulseAgendaObservability(
    uint32_t seq,
    uint64_t candidates_total,
    uint64_t accepted_total,
    uint64_t rejected_total,
    uint64_t reject_gate_total,
    uint64_t correctness_ready_blocked_cycles_total,
    uint64_t correctness_scoreboard_occupancy_peak,
    uint64_t shared_service_hits_total,
    uint64_t shared_service_misses_total,
    uint64_t region_service_entries_peak,
    uint64_t ready_fanout_total,
    uint64_t rowdescriptor_ready_transition_total,
    uint64_t rowdescriptor_join_ready_total,
    uint64_t rowdescriptor_ready_join_shortcut_candidates_total,
    uint64_t rowdescriptor_ready_join_shortcut_taken_total,
    uint64_t rowdescriptor_ready_join_shortcut_late_release_taken_total,
    uint64_t rowdescriptor_ready_join_shortcut_deferred_live_park_total,
    uint64_t rowdescriptor_ready_join_shortcut_deferred_live_apply_total,
    uint64_t rowdescriptor_owner_form_deferred_park_total,
    uint64_t rowdescriptor_owner_form_deferred_activate_total,
    uint64_t rowdescriptor_ready_join_shortcut_blocked_not_ready_total,
    uint64_t rowdescriptor_ready_join_shortcut_blocked_owner_form_total,
    uint64_t rowdescriptor_ready_join_shortcut_blocked_join_live_total,
    uint64_t rowdescriptor_ready_join_shortcut_blocked_other_total,
    uint64_t rowdescriptor_ready_join_shortcut_release_deferred_total,
    uint64_t rowdescriptor_ready_join_shortcut_apply_complete_total,
    uint64_t rowdescriptor_ready_join_shortcut_release_forwarded_total,
    uint64_t rowdescriptor_ready_join_shortcut_release_missing_total,
    uint64_t rowdescriptor_ready_join_descriptor_elide_total,
    uint64_t rowdescriptor_ready_join_lines_elide_total,
    uint64_t rowdescriptor_owner_first_service_elide_join_live_total,
    uint64_t rowdescriptor_owner_first_service_elide_join_ready_total,
    uint64_t rowdescriptor_owner_first_service_elide_late_join_total,
    uint64_t actual_gate_enable_false_total,
    uint64_t actual_gate_window_zero_total,
    uint64_t actual_gate_line_too_small_total,
    uint64_t actual_gate_taken_total,
    uint64_t frontier_windows_total,
    uint64_t frontier_lines_exported_total,
    uint64_t frontier_overlap_lines_total,
    uint64_t frontier_overlap_peer_total,
    uint64_t frontier_max_exported_per_window,
    uint64_t prebase_lookup_owner_fill_total,
    uint64_t prebase_lookup_shared_hits_total,
    uint64_t prebase_lookup_entries_peak) {
    (void)seq;
    if (candidates_total && stat_pulse_agenda_candidates_total_) {
        stat_pulse_agenda_candidates_total_->addData(candidates_total);
    }
    if (accepted_total && stat_pulse_agenda_accepted_total_) {
        stat_pulse_agenda_accepted_total_->addData(accepted_total);
    }
    if (rejected_total && stat_pulse_agenda_rejected_total_) {
        stat_pulse_agenda_rejected_total_->addData(rejected_total);
    }
    if (reject_gate_total && stat_pulse_agenda_reject_gate_total_) {
        stat_pulse_agenda_reject_gate_total_->addData(reject_gate_total);
    }
    if (correctness_ready_blocked_cycles_total &&
        stat_pulse_correctness_ready_blocked_cycles_total_) {
        stat_pulse_correctness_ready_blocked_cycles_total_->addData(
            correctness_ready_blocked_cycles_total);
    }
    if (correctness_scoreboard_occupancy_peak &&
        stat_pulse_correctness_scoreboard_occupancy_peak_) {
        stat_pulse_correctness_scoreboard_occupancy_peak_->addData(
            correctness_scoreboard_occupancy_peak);
    }
    if (shared_service_hits_total && stat_pulse_shared_service_hits_total_) {
        stat_pulse_shared_service_hits_total_->addData(shared_service_hits_total);
    }
    if (shared_service_misses_total && stat_pulse_shared_service_misses_total_) {
        stat_pulse_shared_service_misses_total_->addData(shared_service_misses_total);
    }
    if (region_service_entries_peak && stat_pulse_region_service_entries_peak_) {
        stat_pulse_region_service_entries_peak_->addData(region_service_entries_peak);
    }
    if (ready_fanout_total && stat_pulse_ready_fanout_total_) {
        stat_pulse_ready_fanout_total_->addData(ready_fanout_total);
    }
    if (rowdescriptor_ready_transition_total &&
        stat_pulse_rowdescriptor_ready_transition_total_) {
        stat_pulse_rowdescriptor_ready_transition_total_->addData(
            rowdescriptor_ready_transition_total);
    }
    if (rowdescriptor_join_ready_total &&
        stat_pulse_rowdescriptor_join_ready_total_) {
        stat_pulse_rowdescriptor_join_ready_total_->addData(
            rowdescriptor_join_ready_total);
    }
    if (rowdescriptor_ready_join_shortcut_candidates_total &&
        stat_pulse_rowdescriptor_ready_join_shortcut_candidates_total_) {
        stat_pulse_rowdescriptor_ready_join_shortcut_candidates_total_->addData(
            rowdescriptor_ready_join_shortcut_candidates_total);
    }
    if (rowdescriptor_ready_join_shortcut_taken_total &&
        stat_pulse_rowdescriptor_ready_join_shortcut_taken_total_) {
        stat_pulse_rowdescriptor_ready_join_shortcut_taken_total_->addData(
            rowdescriptor_ready_join_shortcut_taken_total);
    }
    if (rowdescriptor_ready_join_shortcut_late_release_taken_total &&
        stat_pulse_rowdescriptor_ready_join_shortcut_late_release_taken_total_) {
        stat_pulse_rowdescriptor_ready_join_shortcut_late_release_taken_total_->addData(
            rowdescriptor_ready_join_shortcut_late_release_taken_total);
    }
    if (rowdescriptor_ready_join_shortcut_deferred_live_park_total &&
        stat_pulse_rowdescriptor_ready_join_shortcut_deferred_live_park_total_) {
        stat_pulse_rowdescriptor_ready_join_shortcut_deferred_live_park_total_->addData(
            rowdescriptor_ready_join_shortcut_deferred_live_park_total);
    }
    if (rowdescriptor_ready_join_shortcut_deferred_live_apply_total &&
        stat_pulse_rowdescriptor_ready_join_shortcut_deferred_live_apply_total_) {
        stat_pulse_rowdescriptor_ready_join_shortcut_deferred_live_apply_total_->addData(
            rowdescriptor_ready_join_shortcut_deferred_live_apply_total);
    }
    if (rowdescriptor_owner_form_deferred_park_total &&
        stat_pulse_rowdescriptor_owner_form_deferred_park_total_) {
        stat_pulse_rowdescriptor_owner_form_deferred_park_total_->addData(
            rowdescriptor_owner_form_deferred_park_total);
    }
    if (rowdescriptor_owner_form_deferred_activate_total &&
        stat_pulse_rowdescriptor_owner_form_deferred_activate_total_) {
        stat_pulse_rowdescriptor_owner_form_deferred_activate_total_->addData(
            rowdescriptor_owner_form_deferred_activate_total);
    }
    if (rowdescriptor_ready_join_shortcut_blocked_not_ready_total &&
        stat_pulse_rowdescriptor_ready_join_shortcut_blocked_not_ready_total_) {
        stat_pulse_rowdescriptor_ready_join_shortcut_blocked_not_ready_total_->addData(
            rowdescriptor_ready_join_shortcut_blocked_not_ready_total);
    }
    if (rowdescriptor_ready_join_shortcut_blocked_owner_form_total &&
        stat_pulse_rowdescriptor_ready_join_shortcut_blocked_owner_form_total_) {
        stat_pulse_rowdescriptor_ready_join_shortcut_blocked_owner_form_total_->addData(
            rowdescriptor_ready_join_shortcut_blocked_owner_form_total);
    }
    if (rowdescriptor_ready_join_shortcut_blocked_join_live_total &&
        stat_pulse_rowdescriptor_ready_join_shortcut_blocked_join_live_total_) {
        stat_pulse_rowdescriptor_ready_join_shortcut_blocked_join_live_total_->addData(
            rowdescriptor_ready_join_shortcut_blocked_join_live_total);
    }
    if (rowdescriptor_ready_join_shortcut_blocked_other_total &&
        stat_pulse_rowdescriptor_ready_join_shortcut_blocked_other_total_) {
        stat_pulse_rowdescriptor_ready_join_shortcut_blocked_other_total_->addData(
            rowdescriptor_ready_join_shortcut_blocked_other_total);
    }
    if (rowdescriptor_ready_join_shortcut_release_deferred_total &&
        stat_pulse_rowdescriptor_ready_join_shortcut_release_deferred_total_) {
        stat_pulse_rowdescriptor_ready_join_shortcut_release_deferred_total_->addData(
            rowdescriptor_ready_join_shortcut_release_deferred_total);
    }
    if (rowdescriptor_ready_join_shortcut_apply_complete_total &&
        stat_pulse_rowdescriptor_ready_join_shortcut_apply_complete_total_) {
        stat_pulse_rowdescriptor_ready_join_shortcut_apply_complete_total_->addData(
            rowdescriptor_ready_join_shortcut_apply_complete_total);
    }
    if (rowdescriptor_ready_join_shortcut_release_forwarded_total &&
        stat_pulse_rowdescriptor_ready_join_shortcut_release_forwarded_total_) {
        stat_pulse_rowdescriptor_ready_join_shortcut_release_forwarded_total_->addData(
            rowdescriptor_ready_join_shortcut_release_forwarded_total);
    }
    if (rowdescriptor_ready_join_shortcut_release_missing_total &&
        stat_pulse_rowdescriptor_ready_join_shortcut_release_missing_total_) {
        stat_pulse_rowdescriptor_ready_join_shortcut_release_missing_total_->addData(
            rowdescriptor_ready_join_shortcut_release_missing_total);
    }
    if (rowdescriptor_ready_join_descriptor_elide_total &&
        stat_pulse_rowdescriptor_ready_join_descriptor_elide_total_) {
        stat_pulse_rowdescriptor_ready_join_descriptor_elide_total_->addData(
            rowdescriptor_ready_join_descriptor_elide_total);
    }
    if (rowdescriptor_ready_join_lines_elide_total &&
        stat_pulse_rowdescriptor_ready_join_lines_elide_total_) {
        stat_pulse_rowdescriptor_ready_join_lines_elide_total_->addData(
            rowdescriptor_ready_join_lines_elide_total);
    }
    if (rowdescriptor_owner_first_service_elide_join_live_total &&
        stat_pulse_rowdescriptor_owner_first_service_elide_join_live_total_) {
        stat_pulse_rowdescriptor_owner_first_service_elide_join_live_total_->addData(
            rowdescriptor_owner_first_service_elide_join_live_total);
    }
    if (rowdescriptor_owner_first_service_elide_join_ready_total &&
        stat_pulse_rowdescriptor_owner_first_service_elide_join_ready_total_) {
        stat_pulse_rowdescriptor_owner_first_service_elide_join_ready_total_->addData(
            rowdescriptor_owner_first_service_elide_join_ready_total);
    }
    if (rowdescriptor_owner_first_service_elide_late_join_total &&
        stat_pulse_rowdescriptor_owner_first_service_elide_late_join_total_) {
        stat_pulse_rowdescriptor_owner_first_service_elide_late_join_total_->addData(
            rowdescriptor_owner_first_service_elide_late_join_total);
    }
    if (actual_gate_enable_false_total && stat_pulse_actual_gate_enable_false_total_) {
        stat_pulse_actual_gate_enable_false_total_->addData(actual_gate_enable_false_total);
    }
    if (actual_gate_window_zero_total && stat_pulse_actual_gate_window_zero_total_) {
        stat_pulse_actual_gate_window_zero_total_->addData(actual_gate_window_zero_total);
    }
    if (actual_gate_line_too_small_total && stat_pulse_actual_gate_line_too_small_total_) {
        stat_pulse_actual_gate_line_too_small_total_->addData(actual_gate_line_too_small_total);
    }
    if (actual_gate_taken_total && stat_pulse_actual_gate_taken_total_) {
        stat_pulse_actual_gate_taken_total_->addData(actual_gate_taken_total);
    }
    if (frontier_windows_total && stat_pulse_frontier_windows_total_) {
        stat_pulse_frontier_windows_total_->addData(frontier_windows_total);
    }
    if (frontier_lines_exported_total && stat_pulse_frontier_lines_exported_total_) {
        stat_pulse_frontier_lines_exported_total_->addData(frontier_lines_exported_total);
    }
    if (frontier_overlap_lines_total && stat_pulse_frontier_overlap_lines_total_) {
        stat_pulse_frontier_overlap_lines_total_->addData(frontier_overlap_lines_total);
    }
    if (frontier_overlap_peer_total && stat_pulse_frontier_overlap_peer_total_) {
        stat_pulse_frontier_overlap_peer_total_->addData(frontier_overlap_peer_total);
    }
    if (frontier_max_exported_per_window && stat_pulse_frontier_max_exported_per_window_) {
        stat_pulse_frontier_max_exported_per_window_->addData(
            frontier_max_exported_per_window);
    }
    if (prebase_lookup_owner_fill_total &&
        stat_pulse_prebase_lookup_owner_fill_total_) {
        stat_pulse_prebase_lookup_owner_fill_total_->addData(
            prebase_lookup_owner_fill_total);
    }
    if (prebase_lookup_shared_hits_total &&
        stat_pulse_prebase_lookup_shared_hits_total_) {
        stat_pulse_prebase_lookup_shared_hits_total_->addData(
            prebase_lookup_shared_hits_total);
    }
    if (prebase_lookup_entries_peak &&
        stat_pulse_prebase_lookup_entries_peak_) {
        stat_pulse_prebase_lookup_entries_peak_->addData(
            prebase_lookup_entries_peak);
    }
}

void MultiCorePE::recordPulsePodRowdescriptorObservability(
    uint32_t seq,
    uint64_t owner_form_total,
    uint64_t owner_hit_total,
    uint64_t join_live_total,
    uint64_t join_ready_total,
    uint64_t ready_transition_total,
    uint64_t late_join_total,
    uint64_t guard_total,
    uint64_t guard_disabled_total,
    uint64_t guard_missing_metadata_plane_total,
    uint64_t guard_missing_owner_table_total,
    uint64_t guard_zero_pod_count_total,
    uint64_t guard_window_zero_total,
    uint64_t guard_invalid_cfg_pod_total,
    uint64_t reject_total,
    uint64_t attempted_total,
    uint64_t potential_private_service_elide_total,
    uint64_t owner_first_issue_deferred_total,
    uint64_t owner_first_private_issue_avoided_total,
    uint64_t owner_first_service_elide_total) {
    (void)seq;
    if (owner_form_total && stat_pulse_pod_rowdescriptor_owner_form_total_) {
        stat_pulse_pod_rowdescriptor_owner_form_total_->addData(owner_form_total);
    }
    if (owner_hit_total && stat_pulse_pod_rowdescriptor_owner_hit_total_) {
        stat_pulse_pod_rowdescriptor_owner_hit_total_->addData(owner_hit_total);
    }
    if (join_live_total && stat_pulse_pod_rowdescriptor_join_live_total_) {
        stat_pulse_pod_rowdescriptor_join_live_total_->addData(join_live_total);
    }
    if (join_ready_total && stat_pulse_pod_rowdescriptor_join_ready_total_) {
        stat_pulse_pod_rowdescriptor_join_ready_total_->addData(join_ready_total);
    }
    if (ready_transition_total &&
        stat_pulse_pod_rowdescriptor_ready_transition_total_) {
        stat_pulse_pod_rowdescriptor_ready_transition_total_->addData(
            ready_transition_total);
    }
    if (late_join_total && stat_pulse_pod_rowdescriptor_late_join_total_) {
        stat_pulse_pod_rowdescriptor_late_join_total_->addData(late_join_total);
    }
    if (guard_total && stat_pulse_pod_rowdescriptor_guard_total_) {
        stat_pulse_pod_rowdescriptor_guard_total_->addData(guard_total);
    }
    if (guard_disabled_total && stat_pulse_pod_rowdescriptor_guard_disabled_total_) {
        stat_pulse_pod_rowdescriptor_guard_disabled_total_->addData(
            guard_disabled_total);
    }
    if (guard_missing_metadata_plane_total &&
        stat_pulse_pod_rowdescriptor_guard_missing_metadata_plane_total_) {
        stat_pulse_pod_rowdescriptor_guard_missing_metadata_plane_total_->addData(
            guard_missing_metadata_plane_total);
    }
    if (guard_missing_owner_table_total &&
        stat_pulse_pod_rowdescriptor_guard_missing_owner_table_total_) {
        stat_pulse_pod_rowdescriptor_guard_missing_owner_table_total_->addData(
            guard_missing_owner_table_total);
    }
    if (guard_zero_pod_count_total &&
        stat_pulse_pod_rowdescriptor_guard_zero_pod_count_total_) {
        stat_pulse_pod_rowdescriptor_guard_zero_pod_count_total_->addData(
            guard_zero_pod_count_total);
    }
    if (guard_window_zero_total &&
        stat_pulse_pod_rowdescriptor_guard_window_zero_total_) {
        stat_pulse_pod_rowdescriptor_guard_window_zero_total_->addData(
            guard_window_zero_total);
    }
    if (guard_invalid_cfg_pod_total &&
        stat_pulse_pod_rowdescriptor_guard_invalid_cfg_pod_total_) {
        stat_pulse_pod_rowdescriptor_guard_invalid_cfg_pod_total_->addData(
            guard_invalid_cfg_pod_total);
    }
    if (reject_total && stat_pulse_pod_rowdescriptor_reject_total_) {
        stat_pulse_pod_rowdescriptor_reject_total_->addData(reject_total);
    }
    if (attempted_total && stat_pulse_pod_rowdescriptor_attempted_total_) {
        stat_pulse_pod_rowdescriptor_attempted_total_->addData(attempted_total);
    }
    if (potential_private_service_elide_total &&
        stat_pulse_pod_rowdescriptor_potential_private_service_elide_total_) {
        stat_pulse_pod_rowdescriptor_potential_private_service_elide_total_->addData(
            potential_private_service_elide_total);
    }
    if (owner_first_issue_deferred_total &&
        stat_pulse_pod_rowdescriptor_owner_first_issue_deferred_total_) {
        stat_pulse_pod_rowdescriptor_owner_first_issue_deferred_total_->addData(
            owner_first_issue_deferred_total);
    }
    if (owner_first_private_issue_avoided_total &&
        stat_pulse_pod_rowdescriptor_owner_first_private_issue_avoided_total_) {
        stat_pulse_pod_rowdescriptor_owner_first_private_issue_avoided_total_->addData(
            owner_first_private_issue_avoided_total);
    }
    if (owner_first_service_elide_total &&
        stat_pulse_pod_rowdescriptor_owner_first_service_elide_total_) {
        stat_pulse_pod_rowdescriptor_owner_first_service_elide_total_->addData(
            owner_first_service_elide_total);
    }
}

void MultiCorePE::recordPulseOsaMetadataTxnObservability(
    const WeightMemorySubsystem::PulseOsaMetadataTxnStats& stats) {
    if (stats.export_total && stat_pulse_metadata_txn_export_total_) {
        stat_pulse_metadata_txn_export_total_->addData(stats.export_total);
    }
    if (stats.owner_launch_total && stat_pulse_metadata_txn_owner_launch_total_) {
        stat_pulse_metadata_txn_owner_launch_total_->addData(stats.owner_launch_total);
    }
    if (stats.join_live_total && stat_pulse_metadata_txn_join_live_total_) {
        stat_pulse_metadata_txn_join_live_total_->addData(stats.join_live_total);
    }
    if (stats.join_ready_total && stat_pulse_metadata_txn_join_ready_total_) {
        stat_pulse_metadata_txn_join_ready_total_->addData(stats.join_ready_total);
    }
    if (stats.late_join_total && stat_pulse_metadata_txn_late_join_total_) {
        stat_pulse_metadata_txn_late_join_total_->addData(stats.late_join_total);
    }
    if (stats.ready_lease_hit_total && stat_pulse_metadata_txn_ready_lease_hit_total_) {
        stat_pulse_metadata_txn_ready_lease_hit_total_->addData(stats.ready_lease_hit_total);
    }
    if (stats.ready_lease_expired_total &&
        stat_pulse_metadata_txn_ready_lease_expired_total_) {
        stat_pulse_metadata_txn_ready_lease_expired_total_->addData(
            stats.ready_lease_expired_total);
    }
    if (stats.envelope_size_sum_total &&
        stat_pulse_metadata_txn_envelope_size_sum_total_) {
        stat_pulse_metadata_txn_envelope_size_sum_total_->addData(
            stats.envelope_size_sum_total);
    }
    if (stats.frontier_observed_total &&
        stat_pulse_metadata_frontier_observed_total_) {
        stat_pulse_metadata_frontier_observed_total_->addData(
            stats.frontier_observed_total);
    }
    if (stats.frontier_same_window_reobserve_total &&
        stat_pulse_metadata_frontier_same_window_reobserve_total_) {
        stat_pulse_metadata_frontier_same_window_reobserve_total_->addData(
            stats.frontier_same_window_reobserve_total);
    }
    if (stats.frontier_owner_form_candidate_total &&
        stat_pulse_metadata_frontier_owner_form_candidate_total_) {
        stat_pulse_metadata_frontier_owner_form_candidate_total_->addData(
            stats.frontier_owner_form_candidate_total);
    }
    if (stats.frontier_join_ready_candidate_total &&
        stat_pulse_metadata_frontier_join_ready_candidate_total_) {
        stat_pulse_metadata_frontier_join_ready_candidate_total_->addData(
            stats.frontier_join_ready_candidate_total);
    }
    if (stats.frontier_premphf_base_observed_total &&
        stat_pulse_metadata_frontier_premphf_base_observed_total_) {
        stat_pulse_metadata_frontier_premphf_base_observed_total_->addData(
            stats.frontier_premphf_base_observed_total);
    }
    if (stats.frontier_premphf_base_same_window_reobserve_total &&
        stat_pulse_metadata_frontier_premphf_base_same_window_reobserve_total_) {
        stat_pulse_metadata_frontier_premphf_base_same_window_reobserve_total_->addData(
            stats.frontier_premphf_base_same_window_reobserve_total);
    }
    if (stats.frontier_premphf_base_owner_form_candidate_total &&
        stat_pulse_metadata_frontier_premphf_base_owner_form_candidate_total_) {
        stat_pulse_metadata_frontier_premphf_base_owner_form_candidate_total_->addData(
            stats.frontier_premphf_base_owner_form_candidate_total);
    }
    if (stats.frontier_premphf_base_join_ready_candidate_total &&
        stat_pulse_metadata_frontier_premphf_base_join_ready_candidate_total_) {
        stat_pulse_metadata_frontier_premphf_base_join_ready_candidate_total_->addData(
            stats.frontier_premphf_base_join_ready_candidate_total);
    }
    if (stats.frontier_premphf_band_observed_total &&
        stat_pulse_metadata_frontier_premphf_band_observed_total_) {
        stat_pulse_metadata_frontier_premphf_band_observed_total_->addData(
            stats.frontier_premphf_band_observed_total);
    }
    if (stats.frontier_premphf_band_same_window_reobserve_total &&
        stat_pulse_metadata_frontier_premphf_band_same_window_reobserve_total_) {
        stat_pulse_metadata_frontier_premphf_band_same_window_reobserve_total_->addData(
            stats.frontier_premphf_band_same_window_reobserve_total);
    }
    if (stats.frontier_premphf_band_owner_form_candidate_total &&
        stat_pulse_metadata_frontier_premphf_band_owner_form_candidate_total_) {
        stat_pulse_metadata_frontier_premphf_band_owner_form_candidate_total_->addData(
            stats.frontier_premphf_band_owner_form_candidate_total);
    }
    if (stats.frontier_premphf_band_join_ready_candidate_total &&
        stat_pulse_metadata_frontier_premphf_band_join_ready_candidate_total_) {
        stat_pulse_metadata_frontier_premphf_band_join_ready_candidate_total_->addData(
            stats.frontier_premphf_band_join_ready_candidate_total);
    }
    if (stats.frontier_idx2row_observed_total &&
        stat_pulse_metadata_frontier_idx2row_observed_total_) {
        stat_pulse_metadata_frontier_idx2row_observed_total_->addData(
            stats.frontier_idx2row_observed_total);
    }
    if (stats.frontier_idx2row_same_window_reobserve_total &&
        stat_pulse_metadata_frontier_idx2row_same_window_reobserve_total_) {
        stat_pulse_metadata_frontier_idx2row_same_window_reobserve_total_->addData(
            stats.frontier_idx2row_same_window_reobserve_total);
    }
    if (stats.frontier_idx2row_owner_form_candidate_total &&
        stat_pulse_metadata_frontier_idx2row_owner_form_candidate_total_) {
        stat_pulse_metadata_frontier_idx2row_owner_form_candidate_total_->addData(
            stats.frontier_idx2row_owner_form_candidate_total);
    }
    if (stats.frontier_idx2row_join_ready_candidate_total &&
        stat_pulse_metadata_frontier_idx2row_join_ready_candidate_total_) {
        stat_pulse_metadata_frontier_idx2row_join_ready_candidate_total_->addData(
            stats.frontier_idx2row_join_ready_candidate_total);
    }
    if (stats.frontier_rowindex_observed_total &&
        stat_pulse_metadata_frontier_rowindex_observed_total_) {
        stat_pulse_metadata_frontier_rowindex_observed_total_->addData(
            stats.frontier_rowindex_observed_total);
    }
    if (stats.frontier_rowindex_same_window_reobserve_total &&
        stat_pulse_metadata_frontier_rowindex_same_window_reobserve_total_) {
        stat_pulse_metadata_frontier_rowindex_same_window_reobserve_total_->addData(
            stats.frontier_rowindex_same_window_reobserve_total);
    }
    if (stats.frontier_rowindex_owner_form_candidate_total &&
        stat_pulse_metadata_frontier_rowindex_owner_form_candidate_total_) {
        stat_pulse_metadata_frontier_rowindex_owner_form_candidate_total_->addData(
            stats.frontier_rowindex_owner_form_candidate_total);
    }
    if (stats.frontier_rowindex_join_ready_candidate_total &&
        stat_pulse_metadata_frontier_rowindex_join_ready_candidate_total_) {
        stat_pulse_metadata_frontier_rowindex_join_ready_candidate_total_->addData(
            stats.frontier_rowindex_join_ready_candidate_total);
    }
}

void MultiCorePE::recordAtlasObjectObservability(
    const WeightMemorySubsystem::ExperimentalPeAtlasObjectCensus& census,
    const WeightMemorySubsystem::ExperimentalPeAtlasRowIndexLifecycleLedger& rowindex,
    const WeightMemorySubsystem::ExperimentalPeAtlasIdx2RowLifecycleLedger& idx2row,
    const WeightMemorySubsystem::ExperimentalPeAtlasPreMphfBaseProxyLedger& premphf_base,
    const WeightMemorySubsystem::ExperimentalPeAtlasPreMphfBandProxyLedger& premphf_band,
    const WeightMemorySubsystem::ExperimentalPeAtlasPhaseStats& phase,
    const WeightMemorySubsystem::PeInternalPodStats& pod_runtime) {
    const auto add_atlas_stat = [this](const char* name, uint64_t value) {
        auto it = atlas_object_plane_stats_.find(name);
        if (it == atlas_object_plane_stats_.end() || it->second == nullptr) return;
        if (value == 0u) return;
        it->second->addData(value);
    };
    const auto add_atlas_stat_sampled = [this](const char* name, uint64_t value) {
        auto it = atlas_object_plane_stats_.find(name);
        if (it == atlas_object_plane_stats_.end() || it->second == nullptr) return;
        it->second->addData(value);
    };

    add_atlas_stat(
        "atlas_census_premphf_base_frontier_events_total",
        census.premphf_base.frontier_events_total);
    add_atlas_stat(
        "atlas_census_premphf_base_producer_events_total",
        census.premphf_base.producer_events_total);
    add_atlas_stat(
        "atlas_census_premphf_base_gate_events_total",
        census.premphf_base.gate_events_total);
    add_atlas_stat(
        "atlas_census_premphf_base_service_events_total",
        census.premphf_base.service_events_total);
    add_atlas_stat(
        "atlas_census_premphf_band_frontier_events_total",
        census.premphf_band.frontier_events_total);
    add_atlas_stat(
        "atlas_census_premphf_band_producer_events_total",
        census.premphf_band.producer_events_total);
    add_atlas_stat(
        "atlas_census_premphf_band_gate_events_total",
        census.premphf_band.gate_events_total);
    add_atlas_stat(
        "atlas_census_premphf_band_service_events_total",
        census.premphf_band.service_events_total);
    add_atlas_stat(
        "atlas_census_idx2row_frontier_events_total",
        census.idx2row.frontier_events_total);
    add_atlas_stat(
        "atlas_census_idx2row_producer_events_total",
        census.idx2row.producer_events_total);
    add_atlas_stat(
        "atlas_census_idx2row_gate_events_total",
        census.idx2row.gate_events_total);
    add_atlas_stat(
        "atlas_census_idx2row_service_events_total",
        census.idx2row.service_events_total);
    add_atlas_stat(
        "atlas_census_rowindex_frontier_events_total",
        census.rowindex.frontier_events_total);
    add_atlas_stat(
        "atlas_census_rowindex_producer_events_total",
        census.rowindex.producer_events_total);
    add_atlas_stat(
        "atlas_census_rowindex_gate_events_total",
        census.rowindex.gate_events_total);
    add_atlas_stat(
        "atlas_census_rowindex_service_events_total",
        census.rowindex.service_events_total);
    add_atlas_stat(
        "atlas_census_rowdescriptor_frontier_events_total",
        census.rowdescriptor.frontier_events_total);
    add_atlas_stat(
        "atlas_census_rowdescriptor_producer_events_total",
        census.rowdescriptor.producer_events_total);
    add_atlas_stat(
        "atlas_census_rowdescriptor_gate_events_total",
        census.rowdescriptor.gate_events_total);
    add_atlas_stat(
        "atlas_census_rowdescriptor_service_events_total",
        census.rowdescriptor.service_events_total);

    add_atlas_stat(
        "atlas_proxy_idx2row_materialize_total",
        idx2row.materialize_total);
    add_atlas_stat(
        "atlas_proxy_idx2row_publicize_total",
        idx2row.publicize_total);
    add_atlas_stat(
        "atlas_proxy_idx2row_owner_form_total",
        idx2row.owner_form_total);
    add_atlas_stat(
        "atlas_proxy_idx2row_join_live_total",
        idx2row.join_live_total);
    add_atlas_stat(
        "atlas_proxy_idx2row_join_ready_total",
        idx2row.join_ready_total);
    add_atlas_stat(
        "atlas_proxy_idx2row_ready_total",
        idx2row.ready_total);
    add_atlas_stat(
        "atlas_proxy_idx2row_release_total",
        idx2row.release_total);
    add_atlas_stat(
        "atlas_proxy_idx2row_release_missing_total",
        idx2row.release_missing_total);
    add_atlas_stat(
        "atlas_proxy_idx2row_fallback_total",
        idx2row.fallback_total);

    add_atlas_stat(
        "atlas_proxy_premphf_base_materialize_total",
        premphf_base.materialize_total);
    add_atlas_stat(
        "atlas_proxy_premphf_base_publicize_total",
        premphf_base.publicize_total);
    add_atlas_stat(
        "atlas_proxy_premphf_base_owner_form_total",
        premphf_base.owner_form_total);
    add_atlas_stat(
        "atlas_proxy_premphf_base_shared_hit_total",
        premphf_base.shared_hit_total);
    add_atlas_stat(
        "atlas_proxy_premphf_base_lookup_ready_total",
        premphf_base.lookup_ready_total);
    add_atlas_stat(
        "atlas_proxy_premphf_base_proxy_only_gap_total",
        premphf_base.proxy_only_gap_total);

    add_atlas_stat(
        "atlas_proxy_premphf_band_materialize_total",
        premphf_band.materialize_total);
    add_atlas_stat(
        "atlas_proxy_premphf_band_publicize_total",
        premphf_band.publicize_total);
    add_atlas_stat(
        "atlas_proxy_premphf_band_owner_form_candidate_total",
        premphf_band.owner_form_candidate_total);
    add_atlas_stat(
        "atlas_proxy_premphf_band_join_ready_candidate_total",
        premphf_band.join_ready_candidate_total);
    add_atlas_stat(
        "atlas_proxy_premphf_band_zero_service_total",
        premphf_band.zero_service_total);

    add_atlas_stat(
        "atlas_proxy_rowindex_materialize_total",
        rowindex.materialize_total);
    add_atlas_stat(
        "atlas_proxy_rowindex_publicize_total",
        rowindex.publicize_total);
    add_atlas_stat(
        "atlas_proxy_rowindex_owner_form_total",
        rowindex.owner_form_total);
    add_atlas_stat(
        "atlas_proxy_rowindex_join_live_total",
        rowindex.join_live_total);
    add_atlas_stat(
        "atlas_proxy_rowindex_join_ready_total",
        rowindex.join_ready_total);
    add_atlas_stat(
        "atlas_proxy_rowindex_ready_total",
        rowindex.ready_total);
    add_atlas_stat(
        "atlas_proxy_rowindex_release_total",
        rowindex.release_total);
    add_atlas_stat(
        "atlas_proxy_rowindex_release_missing_total",
        rowindex.release_missing_total);
    add_atlas_stat(
        "atlas_proxy_rowindex_fallback_total",
        rowindex.fallback_total);

    const bool rowindex_requested =
        (census.rowindex.frontier_events_total +
         census.rowindex.producer_events_total +
         census.rowindex.gate_events_total +
         census.rowindex.service_events_total +
         rowindex.materialize_total +
         rowindex.publicize_total +
         rowindex.owner_form_total +
         rowindex.join_live_total +
         rowindex.join_ready_total +
         rowindex.ready_total +
         rowindex.release_total +
         rowindex.release_missing_total +
         rowindex.fallback_total) > 0u;
    const bool rowindex_effective =
        rowindex_requested &&
        pulse_osa_enable_ &&
        pulse_osa_metadata_txn_enable_ &&
        (pulse_osa_metadata_object_mask_bits_ &
         PeLocalServiceObjectTable::kMetadataKindMaskRowIndex) != 0u &&
        pe_internal_pod_enable_cfg_ &&
        pe_internal_pod_metadata_enable_cfg_ &&
        pe_internal_pod_owner_enable_cfg_ &&
        pe_local_service_object_table_ != nullptr;
    const bool rowindex_constructed =
        rowindex.materialize_total > 0u ||
        rowindex.publicize_total > 0u ||
        rowindex.owner_form_total > 0u ||
        rowindex.join_live_total > 0u ||
        rowindex.join_ready_total > 0u ||
        rowindex.ready_total > 0u;
    atlas_rowindex_requested_seen_ =
        atlas_rowindex_requested_seen_ || rowindex_requested;
    atlas_rowindex_effective_seen_ =
        atlas_rowindex_effective_seen_ || rowindex_effective;
    atlas_rowindex_constructed_seen_ =
        atlas_rowindex_constructed_seen_ || rowindex_constructed;

    add_atlas_stat_sampled(
        "atlas_control_runtime_produced_frontier_export_total",
        pod_runtime.frontier_export_total);
    add_atlas_stat_sampled(
        "atlas_control_runtime_produced_owner_announce_total",
        pod_runtime.owner_alloc_total);
    add_atlas_stat_sampled(
        "atlas_control_runtime_produced_join_request_total",
        pod_runtime.join_request_total);
    add_atlas_stat_sampled(
        "atlas_control_runtime_produced_ready_fanout_total",
        pod_runtime.service_ready_fanout_total);
    add_atlas_stat_sampled(
        "atlas_control_runtime_produced_join_reject_total",
        pod_runtime.owner_reject_total + pod_runtime.join_reject_total);
    atlas_control_runtime_produced_any_nonzero_last_ =
        pod_runtime.frontier_export_total > 0u ||
        pod_runtime.owner_alloc_total > 0u ||
        pod_runtime.join_request_total > 0u ||
        pod_runtime.service_ready_fanout_total > 0u ||
        (pod_runtime.owner_reject_total + pod_runtime.join_reject_total) > 0u;

    add_atlas_stat(
        "atlas_phase_local_begin_gather_total",
        phase.local_begin_gather_total);
    add_atlas_stat(
        "atlas_phase_local_first_touch_after_gather_open_total",
        phase.local_first_touch_after_gather_open_total);
    add_atlas_stat(
        "atlas_phase_local_touch_without_gather_open_total",
        phase.local_touch_without_gather_open_total);
    add_atlas_stat(
        "atlas_phase_local_touch_during_apply_total",
        phase.local_touch_during_apply_total);
    add_atlas_stat(
        "atlas_phase_local_begin_apply_total",
        phase.local_begin_apply_total);
    add_atlas_stat(
        "atlas_phase_local_begin_apply_with_touch_total",
        phase.local_begin_apply_with_touch_total);
    add_atlas_stat(
        "atlas_phase_local_begin_apply_with_pending_rowidx_total",
        phase.local_begin_apply_with_pending_rowidx_total);
    add_atlas_stat(
        "atlas_phase_local_begin_apply_without_pending_rowidx_total",
        phase.local_begin_apply_without_pending_rowidx_total);
    add_atlas_stat(
        "atlas_phase_local_end_scatter_total",
        phase.local_end_scatter_total);
}

void MultiCorePE::recordCoreStepRetireStat(int core_id,
                                           uint32_t seq,
                                           uint64_t retire_global_hol_cycles_total,
                                           uint64_t retire_ready_but_blocked_edges_total,
                                           uint64_t retire_per_post_progress_total,
                                           uint64_t retire_wait_cycles_total,
                                           uint64_t retire_wait_cycles_due_to_hol_total,
                                           uint64_t retire_wait_cycles_due_to_barrier_total,
                                           uint64_t retire_wait_cycles_due_to_not_ready_total,
                                           uint64_t retire_samepost_blocked_edges_total,
                                           uint64_t retire_crosspost_blocked_edges_total,
                                           uint64_t retire_policy_loss_cycles_total,
                                           uint64_t retire_policy_loss_edges_total,
                                           uint64_t retire_shadow_per_post_recoverable_cycles_total,
                                           uint64_t retire_shadow_per_post_recoverable_edges_total,
                                           uint64_t retire_shadow_per_post_ready_posts_peak,
                                           uint64_t retire_shadow_per_post_committable_edges_peak,
                                           uint64_t retire_head_hol_cycles_dense_total,
                                           uint64_t retire_head_hol_cycles_cache_total,
                                           uint64_t retire_head_hol_cycles_miss_total,
                                           uint64_t retire_head_hol_cycles_bcsr_total,
                                           uint64_t retire_head_hol_cycles_bcsr_file_total,
                                           uint64_t retire_head_hol_cycles_gcss_total,
                                           uint64_t retire_head_blocked_edges_dense_total,
                                           uint64_t retire_head_blocked_edges_cache_total,
                                           uint64_t retire_head_blocked_edges_miss_total,
                                           uint64_t retire_head_blocked_edges_bcsr_total,
                                           uint64_t retire_head_blocked_edges_bcsr_file_total,
                                           uint64_t retire_head_blocked_edges_gcss_total,
                                           uint64_t retire_gcss_head_queued_not_issued_cycles_total,
                                           uint64_t retire_gcss_qni_head_wait_episodes_total,
                                           uint64_t retire_gcss_qni_head_wait_cycles_max,
                                           uint64_t retire_gcss_head_queued_not_issued_blocked_edges_total,
                                           uint64_t retire_gcss_head_issued_wait_resp_cycles_total,
                                           uint64_t retire_gcss_head_issued_wait_resp_blocked_edges_total,
                                           uint64_t retire_gcss_resp_ready_but_hol_cycles_total,
                                           uint64_t retire_gcss_resp_ready_but_hol_blocked_edges_total,
                                           uint64_t retire_gcss_qni_loader_not_ready_cycles_total,
                                           uint64_t retire_gcss_qni_loader_not_ready_blocked_edges_total,
                                           uint64_t retire_gcss_qni_weight_sram_stall_cycles_total,
                                           uint64_t retire_gcss_qni_weight_sram_stall_blocked_edges_total,
                                           uint64_t retire_gcss_qni_vlf_younger_ahead_cycles_total,
                                           uint64_t retire_gcss_qni_vlf_younger_ahead_blocked_edges_total,
                                           uint64_t retire_gcss_qni_vlf_younger_ahead_depth_total,
                                           uint64_t retire_gcss_qni_vlf_younger_ahead_depth_samples_total,
                                           uint64_t retire_gcss_qni_vlf_younger_ahead_depth_max,
                                           uint64_t retire_gcss_qni_issue_deferred_total,
                                           uint64_t retire_gcss_qni_pending_direct_queue_residency_cycles_total,
                                           uint64_t retire_gcss_qni_pending_direct_queue_residency_samples_total,
                                           uint64_t retire_gcss_qni_pending_direct_queue_residency_cycles_max,
                                           uint64_t retire_gcss_qni_vlf_front_inflight_full_cycles_total,
                                           uint64_t retire_gcss_qni_vlf_front_inflight_full_blocked_edges_total,
                                           uint64_t retire_gcss_qni_vlf_front_waiting_issue_cycles_total,
                                           uint64_t retire_gcss_qni_vlf_front_waiting_issue_blocked_edges_total,
                                           uint64_t retire_gcss_qni_pending_younger_ahead_cycles_total,
                                           uint64_t retire_gcss_qni_pending_younger_ahead_blocked_edges_total,
                                           uint64_t retire_gcss_qni_pending_front_inflight_full_cycles_total,
                                           uint64_t retire_gcss_qni_pending_front_inflight_full_blocked_edges_total,
                                           uint64_t retire_gcss_qni_pending_front_waiting_tick_cycles_total,
                                           uint64_t retire_gcss_qni_pending_front_waiting_tick_blocked_edges_total,
                                           uint64_t retire_gcss_qni_unknown_cycles_total,
                                           uint64_t retire_gcss_qni_unknown_blocked_edges_total,
                                           uint64_t retire_begin_apply_windows_total,
                                           uint64_t retire_begin_apply_prev_edges_total,
                                           uint64_t retire_begin_apply_outstanding_carryin_total,
                                           uint64_t retire_begin_apply_outstanding_carryin_windows_total,
                                           uint64_t retire_begin_apply_loader_not_ready_windows_total,
                                           uint64_t retire_edge_retire_registered_total,
                                           uint64_t retire_edge_retire_retired_total,
                                           uint64_t retire_end_scatter_gcss_vlf_issue_queue_residual_total,
                                           uint64_t retire_end_scatter_pending_direct_reads_residual_total,
                                           uint64_t retire_end_scatter_outstanding_residual_total,
                                           uint64_t retire_end_scatter_residual_work_windows_total,
                                           uint64_t retire_gcss_vlf_issue_prepare_total,
                                           uint64_t retire_gcss_vlf_issue_edges_total,
                                           uint64_t retire_gcss_vlf_issue_reorder_trigger_total,
                                           uint64_t retire_gcss_vlf_issue_line_groups_total,
                                           uint64_t retire_ready_queue_peak,
                                           uint64_t retire_unblock_events_total) {
    if (seq == 0 || core_id < 0) return;
    auto& perf = getOrCreateCoreStepPerf_(core_id, seq);
    perf.retire_global_hol_cycles_total += retire_global_hol_cycles_total;
    perf.retire_ready_but_blocked_edges_total += retire_ready_but_blocked_edges_total;
    perf.retire_per_post_progress_total += retire_per_post_progress_total;
    perf.retire_wait_cycles_total += retire_wait_cycles_total;
    perf.retire_wait_cycles_due_to_hol_total += retire_wait_cycles_due_to_hol_total;
    perf.retire_wait_cycles_due_to_barrier_total += retire_wait_cycles_due_to_barrier_total;
    perf.retire_wait_cycles_due_to_not_ready_total += retire_wait_cycles_due_to_not_ready_total;
    perf.retire_samepost_blocked_edges_total += retire_samepost_blocked_edges_total;
    perf.retire_crosspost_blocked_edges_total += retire_crosspost_blocked_edges_total;
    perf.retire_policy_loss_cycles_total += retire_policy_loss_cycles_total;
    perf.retire_policy_loss_edges_total += retire_policy_loss_edges_total;
    perf.retire_shadow_per_post_recoverable_cycles_total += retire_shadow_per_post_recoverable_cycles_total;
    perf.retire_shadow_per_post_recoverable_edges_total += retire_shadow_per_post_recoverable_edges_total;
    perf.retire_shadow_per_post_ready_posts_peak =
        std::max<uint64_t>(perf.retire_shadow_per_post_ready_posts_peak, retire_shadow_per_post_ready_posts_peak);
    perf.retire_shadow_per_post_committable_edges_peak =
        std::max<uint64_t>(perf.retire_shadow_per_post_committable_edges_peak, retire_shadow_per_post_committable_edges_peak);
    perf.retire_head_hol_cycles_dense_total += retire_head_hol_cycles_dense_total;
    perf.retire_head_hol_cycles_cache_total += retire_head_hol_cycles_cache_total;
    perf.retire_head_hol_cycles_miss_total += retire_head_hol_cycles_miss_total;
    perf.retire_head_hol_cycles_bcsr_total += retire_head_hol_cycles_bcsr_total;
    perf.retire_head_hol_cycles_bcsr_file_total += retire_head_hol_cycles_bcsr_file_total;
    perf.retire_head_hol_cycles_gcss_total += retire_head_hol_cycles_gcss_total;
    perf.retire_head_blocked_edges_dense_total += retire_head_blocked_edges_dense_total;
    perf.retire_head_blocked_edges_cache_total += retire_head_blocked_edges_cache_total;
    perf.retire_head_blocked_edges_miss_total += retire_head_blocked_edges_miss_total;
    perf.retire_head_blocked_edges_bcsr_total += retire_head_blocked_edges_bcsr_total;
    perf.retire_head_blocked_edges_bcsr_file_total += retire_head_blocked_edges_bcsr_file_total;
    perf.retire_head_blocked_edges_gcss_total += retire_head_blocked_edges_gcss_total;
    perf.retire_gcss_head_queued_not_issued_cycles_total += retire_gcss_head_queued_not_issued_cycles_total;
    perf.retire_gcss_qni_head_wait_episodes_total += retire_gcss_qni_head_wait_episodes_total;
    perf.retire_gcss_qni_head_wait_cycles_max = std::max<uint64_t>(
        perf.retire_gcss_qni_head_wait_cycles_max, retire_gcss_qni_head_wait_cycles_max);
    perf.retire_gcss_head_queued_not_issued_blocked_edges_total += retire_gcss_head_queued_not_issued_blocked_edges_total;
    perf.retire_gcss_head_issued_wait_resp_cycles_total += retire_gcss_head_issued_wait_resp_cycles_total;
    perf.retire_gcss_head_issued_wait_resp_blocked_edges_total += retire_gcss_head_issued_wait_resp_blocked_edges_total;
    perf.retire_gcss_resp_ready_but_hol_cycles_total += retire_gcss_resp_ready_but_hol_cycles_total;
    perf.retire_gcss_resp_ready_but_hol_blocked_edges_total += retire_gcss_resp_ready_but_hol_blocked_edges_total;
    perf.retire_gcss_qni_loader_not_ready_cycles_total += retire_gcss_qni_loader_not_ready_cycles_total;
    perf.retire_gcss_qni_loader_not_ready_blocked_edges_total += retire_gcss_qni_loader_not_ready_blocked_edges_total;
    perf.retire_gcss_qni_weight_sram_stall_cycles_total += retire_gcss_qni_weight_sram_stall_cycles_total;
    perf.retire_gcss_qni_weight_sram_stall_blocked_edges_total += retire_gcss_qni_weight_sram_stall_blocked_edges_total;
    perf.retire_gcss_qni_vlf_younger_ahead_cycles_total += retire_gcss_qni_vlf_younger_ahead_cycles_total;
    perf.retire_gcss_qni_vlf_younger_ahead_blocked_edges_total += retire_gcss_qni_vlf_younger_ahead_blocked_edges_total;
    perf.retire_gcss_qni_vlf_younger_ahead_depth_total += retire_gcss_qni_vlf_younger_ahead_depth_total;
    perf.retire_gcss_qni_vlf_younger_ahead_depth_samples_total += retire_gcss_qni_vlf_younger_ahead_depth_samples_total;
    perf.retire_gcss_qni_vlf_younger_ahead_depth_max = std::max<uint64_t>(
        perf.retire_gcss_qni_vlf_younger_ahead_depth_max,
        retire_gcss_qni_vlf_younger_ahead_depth_max);
    perf.retire_gcss_qni_issue_deferred_total += retire_gcss_qni_issue_deferred_total;
    perf.retire_gcss_qni_pending_direct_queue_residency_cycles_total +=
        retire_gcss_qni_pending_direct_queue_residency_cycles_total;
    perf.retire_gcss_qni_pending_direct_queue_residency_samples_total +=
        retire_gcss_qni_pending_direct_queue_residency_samples_total;
    perf.retire_gcss_qni_pending_direct_queue_residency_cycles_max = std::max<uint64_t>(
        perf.retire_gcss_qni_pending_direct_queue_residency_cycles_max,
        retire_gcss_qni_pending_direct_queue_residency_cycles_max);
    perf.retire_gcss_qni_vlf_front_inflight_full_cycles_total += retire_gcss_qni_vlf_front_inflight_full_cycles_total;
    perf.retire_gcss_qni_vlf_front_inflight_full_blocked_edges_total += retire_gcss_qni_vlf_front_inflight_full_blocked_edges_total;
    perf.retire_gcss_qni_vlf_front_waiting_issue_cycles_total += retire_gcss_qni_vlf_front_waiting_issue_cycles_total;
    perf.retire_gcss_qni_vlf_front_waiting_issue_blocked_edges_total += retire_gcss_qni_vlf_front_waiting_issue_blocked_edges_total;
    perf.retire_gcss_qni_pending_younger_ahead_cycles_total += retire_gcss_qni_pending_younger_ahead_cycles_total;
    perf.retire_gcss_qni_pending_younger_ahead_blocked_edges_total += retire_gcss_qni_pending_younger_ahead_blocked_edges_total;
    perf.retire_gcss_qni_pending_front_inflight_full_cycles_total += retire_gcss_qni_pending_front_inflight_full_cycles_total;
    perf.retire_gcss_qni_pending_front_inflight_full_blocked_edges_total += retire_gcss_qni_pending_front_inflight_full_blocked_edges_total;
    perf.retire_gcss_qni_pending_front_waiting_tick_cycles_total += retire_gcss_qni_pending_front_waiting_tick_cycles_total;
    perf.retire_gcss_qni_pending_front_waiting_tick_blocked_edges_total += retire_gcss_qni_pending_front_waiting_tick_blocked_edges_total;
    perf.retire_gcss_qni_unknown_cycles_total += retire_gcss_qni_unknown_cycles_total;
    perf.retire_gcss_qni_unknown_blocked_edges_total += retire_gcss_qni_unknown_blocked_edges_total;
    perf.retire_begin_apply_windows_total += retire_begin_apply_windows_total;
    perf.retire_begin_apply_prev_edges_total += retire_begin_apply_prev_edges_total;
    perf.retire_begin_apply_outstanding_carryin_total += retire_begin_apply_outstanding_carryin_total;
    perf.retire_begin_apply_outstanding_carryin_windows_total +=
        retire_begin_apply_outstanding_carryin_windows_total;
    perf.retire_begin_apply_loader_not_ready_windows_total +=
        retire_begin_apply_loader_not_ready_windows_total;
    perf.retire_edge_retire_registered_total += retire_edge_retire_registered_total;
    perf.retire_edge_retire_retired_total += retire_edge_retire_retired_total;
    perf.retire_end_scatter_gcss_vlf_issue_queue_residual_total +=
        retire_end_scatter_gcss_vlf_issue_queue_residual_total;
    perf.retire_end_scatter_pending_direct_reads_residual_total +=
        retire_end_scatter_pending_direct_reads_residual_total;
    perf.retire_end_scatter_outstanding_residual_total +=
        retire_end_scatter_outstanding_residual_total;
    perf.retire_end_scatter_residual_work_windows_total +=
        retire_end_scatter_residual_work_windows_total;
    perf.retire_gcss_vlf_issue_prepare_total += retire_gcss_vlf_issue_prepare_total;
    perf.retire_gcss_vlf_issue_edges_total += retire_gcss_vlf_issue_edges_total;
    perf.retire_gcss_vlf_issue_reorder_trigger_total += retire_gcss_vlf_issue_reorder_trigger_total;
    perf.retire_gcss_vlf_issue_line_groups_total += retire_gcss_vlf_issue_line_groups_total;
    perf.retire_ready_queue_peak = std::max<uint64_t>(perf.retire_ready_queue_peak, retire_ready_queue_peak);
    perf.retire_unblock_events_total += retire_unblock_events_total;
}

void MultiCorePE::recordStepApplyScatter(uint32_t seq,
                                         uint64_t acc_updates,
                                         uint64_t posts_touched,
                                         uint64_t spikes_emitted,
                                         uint64_t hwm_bytes,
                                         uint64_t spill_records,
                                         uint64_t spilled_bytes) {
    if (seq == 0) return;
    auto& perf = getOrCreateStepPerf_(seq);
    perf.acc_updates += acc_updates;
    perf.posts_touched += posts_touched;
    perf.spill_records += spill_records;
    perf.spilled_bytes += spilled_bytes;
    perf.hwm_bytes_max = std::max<uint64_t>(perf.hwm_bytes_max, hwm_bytes);
    perf.scatter_spikes_emitted += spikes_emitted;
}

void MultiCorePE::recordCoreStepApplyScatter(int core_id,
                                             uint32_t seq,
                                             uint64_t acc_updates,
                                             uint64_t posts_touched,
                                             uint64_t spikes_emitted,
                                             uint64_t hwm_bytes,
                                             uint64_t spill_records,
                                             uint64_t spilled_bytes) {
    if (seq == 0 || core_id < 0) return;
    auto& perf = getOrCreateCoreStepPerf_(core_id, seq);
    perf.acc_updates += acc_updates;
    perf.posts_touched += posts_touched;
    perf.spill_records += spill_records;
    perf.spilled_bytes += spilled_bytes;
    perf.hwm_bytes_max = std::max<uint64_t>(perf.hwm_bytes_max, hwm_bytes);
    perf.scatter_spikes_emitted += spikes_emitted;
}

void MultiCorePE::accumulateExperimentalNocPrefetchStats(const ExperimentalNocRowidxPeStats& rowidx) {
#define ADD_STAT_VALUE(stat_ptr, value) \
    do { \
        if ((stat_ptr) != nullptr) (stat_ptr)->addData((value)); \
    } while (0)

    ADD_STAT_VALUE(stat_exp_noc_rowidx_prefetch_rows_total_, rowidx.prefetch_rows_total);
    ADD_STAT_VALUE(stat_exp_noc_rowidx_prefetch_bytes_total_, rowidx.prefetch_bytes_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_prefetch_complete_inflight_miss_total_,
        rowidx.prefetch_complete_inflight_miss_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_prefetch_complete_zero_waiters_total_,
        rowidx.prefetch_complete_zero_waiters_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_prefetch_complete_waiters_total_,
        rowidx.prefetch_complete_waiters_total);
    ADD_STAT_VALUE(stat_exp_noc_rowidx_prefetch_rows_deferred_total_, rowidx.prefetch_rows_deferred_total);
    ADD_STAT_VALUE(stat_exp_noc_rowidx_prefetch_rows_failed_total_, rowidx.prefetch_rows_failed_total);
    ADD_STAT_VALUE(stat_exp_noc_rowidx_cache_hits_total_, rowidx.cache_hits_total);
    ADD_STAT_VALUE(stat_exp_noc_rowidx_cache_misses_total_, rowidx.cache_misses_total);
    ADD_STAT_VALUE(stat_exp_noc_rowidx_cache_fills_total_, rowidx.cache_fills_total);
    ADD_STAT_VALUE(stat_exp_noc_rowidx_cache_full_drop_total_, rowidx.cache_full_drop_total);
    ADD_STAT_VALUE(stat_exp_noc_rowidx_cache_entries_final_, rowidx.cache_entries_final);
    ADD_STAT_VALUE(stat_exp_noc_rowidx_bulk_fill_total_, rowidx.bulk_fill_total);
    ADD_STAT_VALUE(stat_exp_noc_rowidx_bulk_rows_cached_total_, rowidx.bulk_rows_cached_total);
    ADD_STAT_VALUE(stat_exp_noc_rowidx_bulk_waiters_resolved_total_, rowidx.bulk_waiters_resolved_total);
    ADD_STAT_VALUE(stat_exp_noc_rowidx_touch_rows_total_, rowidx.touch_rows_total);
    ADD_STAT_VALUE(stat_exp_noc_rowidx_touch_events_total_, rowidx.touch_events_total);
    ADD_STAT_VALUE(stat_exp_noc_rowidx_rows_filtered_cold_total_, rowidx.rows_filtered_cold_total);
    ADD_STAT_VALUE(stat_exp_noc_rowidx_budget_ticks_total_, rowidx.budget_ticks_total);
    ADD_STAT_VALUE(stat_exp_noc_rowidx_budget_effective_total_, rowidx.budget_effective_total);
    ADD_STAT_VALUE(stat_exp_noc_rowidx_budget_adapt_ticks_total_, rowidx.budget_adapt_ticks_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_ready_transition_apply_promote_cached_total_,
        rowidx.ready_transition_apply_promote_cached_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_ready_signal_rowindex_response_total_,
        rowidx.ready_signal_rowindex_response_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_ready_transition_rowindex_response_total_,
        rowidx.ready_transition_rowindex_response_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_ready_signal_prefetch_response_total_,
        rowidx.ready_signal_prefetch_response_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_ready_transition_prefetch_response_total_,
        rowidx.ready_transition_prefetch_response_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_ready_signal_rowindex_response_inflight_waiters_total_,
        rowidx.ready_signal_rowindex_response_inflight_waiters_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_ready_transition_rowindex_response_inflight_waiters_total_,
        rowidx.ready_transition_rowindex_response_inflight_waiters_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_ready_signal_rowindex_response_inflight_zero_waiters_total_,
        rowidx.ready_signal_rowindex_response_inflight_zero_waiters_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_ready_transition_rowindex_response_inflight_zero_waiters_total_,
        rowidx.ready_transition_rowindex_response_inflight_zero_waiters_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_ready_signal_rowindex_response_noninflight_prefetch_only_total_,
        rowidx.ready_signal_rowindex_response_noninflight_prefetch_only_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_ready_transition_rowindex_response_noninflight_prefetch_only_total_,
        rowidx.ready_transition_rowindex_response_noninflight_prefetch_only_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_ready_signal_prefetch_response_inflight_waiters_total_,
        rowidx.ready_signal_prefetch_response_inflight_waiters_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_ready_transition_prefetch_response_inflight_waiters_total_,
        rowidx.ready_transition_prefetch_response_inflight_waiters_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_ready_signal_prefetch_response_inflight_zero_waiters_total_,
        rowidx.ready_signal_prefetch_response_inflight_zero_waiters_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_ready_transition_prefetch_response_inflight_zero_waiters_total_,
        rowidx.ready_transition_prefetch_response_inflight_zero_waiters_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_ready_signal_prefetch_response_noninflight_prefetch_only_total_,
        rowidx.ready_signal_prefetch_response_noninflight_prefetch_only_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_ready_transition_prefetch_response_noninflight_prefetch_only_total_,
        rowidx.ready_transition_prefetch_response_noninflight_prefetch_only_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_detached_demand_join_total_,
        rowidx.detached_demand_join_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_detached_demand_waiters_resolved_total_,
        rowidx.detached_demand_waiters_resolved_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_detached_demand_fallback_zero_total_,
        rowidx.detached_demand_fallback_zero_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_detached_demand_ready_signal_total_,
        rowidx.detached_demand_ready_signal_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_detached_demand_ready_transition_total_,
        rowidx.detached_demand_ready_transition_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_ready_bypass_experimental_cache_hit_total_,
        rowidx.ready_bypass_experimental_cache_hit_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_ready_bypass_rowindex_get_hit_total_,
        rowidx.ready_bypass_rowindex_get_hit_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_close_attempt_total_,
        rowidx.close_attempt_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_close_attempt_active_owner_total_,
        rowidx.close_attempt_active_owner_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_close_attempt_already_pending_total_,
        rowidx.close_attempt_already_pending_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_close_attempt_not_active_total_,
        rowidx.close_attempt_not_active_total);
    ADD_STAT_VALUE(
        stat_exp_noc_rowidx_close_attempt_not_owner_total_,
        rowidx.close_attempt_not_owner_total);

#undef ADD_STAT_VALUE
}

void MultiCorePE::accumulateSynapseReadStats(uint64_t gcss_lookup_hit_total,
                                             uint64_t gcss_lookup_miss_total,
                                             uint64_t dense_reqs_total,
                                             uint64_t dense_bytes_total,
                                             uint64_t rowptr_reqs_total,
                                             uint64_t rowptr_bytes_total,
                                             uint64_t colidx_reqs_total,
                                             uint64_t colidx_bytes_total,
                                             uint64_t blockdata_reqs_total,
                                             uint64_t blockdata_bytes_total,
                                             uint64_t gcss_reqs_total,
                                             uint64_t gcss_bytes_total,
                                             uint64_t weight_idx_sram_reads_total,
                                             uint64_t weight_idx_sram_writes_total,
                                             uint64_t weight_idx_sram_bytes_read_total,
                                             uint64_t weight_idx_sram_bytes_write_total,
                                             uint64_t weight_idx_sram_bank_conflict_ticks_total,
                                             uint64_t weight_idx_sram_predicted_extra_cycles_total,
                                             uint64_t weight_idx_sram_resident_bytes_peak,
                                             uint64_t weight_idx_sram_bank_peak_accesses_per_tick,
                                             uint64_t weight_idx_sram_energy_read_pj_total,
                                             uint64_t weight_idx_sram_energy_write_pj_total,
                                             uint64_t weight_idx_lookup_total,
                                             uint64_t weight_idx_lookup_idx2_total,
                                             uint64_t weight_l0_sram_reads_total,
                                             uint64_t weight_l0_sram_writes_total,
                                             uint64_t weight_l0_sram_bytes_read_total,
                                             uint64_t weight_l0_sram_bytes_write_total,
                                             uint64_t weight_l0_sram_bank_conflict_ticks_total,
                                             uint64_t weight_l0_sram_predicted_extra_cycles_total,
                                             uint64_t weight_l0_sram_resident_bytes_peak,
                                             uint64_t weight_l0_sram_bank_peak_accesses_per_tick,
                                             uint64_t weight_l0_sram_energy_read_pj_total,
                                             uint64_t weight_l0_sram_energy_write_pj_total,
                                             uint64_t weight_sram_enforced_stall_cycles_total,
                                             uint64_t weight_l0_lookup_total,
                                             uint64_t weight_l0_hit_total,
                                             uint64_t weight_l0_fill_total,
                                             uint64_t weight_l0_evict_total,
                                             uint64_t core_state_sram_reads_total,
                                             uint64_t core_state_sram_writes_total,
                                             uint64_t core_state_sram_bytes_read_total,
                                             uint64_t core_state_sram_bytes_write_total,
                                             uint64_t core_state_sram_bank_conflict_ticks_total,
                                             uint64_t core_state_sram_predicted_extra_cycles_total,
                                             uint64_t core_state_sram_resident_bytes_peak,
                                             uint64_t core_state_sram_bank_peak_accesses_per_tick,
                                             uint64_t core_state_sram_energy_read_pj_total,
                                             uint64_t core_state_sram_energy_write_pj_total,
                                             uint64_t core_state_sram_stall_cycles_total,
                                             uint64_t gas_retire_global_hol_cycles_total,
                                             uint64_t gas_retire_ready_but_blocked_edges_total,
                                             uint64_t gas_retire_per_post_progress_total,
                                             uint64_t gas_retire_samepost_blocked_edges_total,
                                             uint64_t gas_retire_crosspost_blocked_edges_total,
                                             uint64_t gas_retire_policy_loss_cycles_total,
                                             uint64_t gas_retire_policy_loss_edges_total,
                                             uint64_t gas_retire_shadow_per_post_recoverable_cycles_total,
                                             uint64_t gas_retire_shadow_per_post_recoverable_edges_total,
                                             uint64_t gas_retire_shadow_per_post_ready_posts_peak,
                                             uint64_t gas_retire_shadow_per_post_committable_edges_peak) {
    const auto add_atlas_storage_stat = [this](const char* name, uint64_t value) {
        auto it = atlas_object_plane_stats_.find(name);
        if (it == atlas_object_plane_stats_.end() || it->second == nullptr) return;
        it->second->addData(value);
    };
    if (stat_gcss_lookup_hit_total_) stat_gcss_lookup_hit_total_->addData(gcss_lookup_hit_total);
    if (stat_gcss_lookup_miss_total_) stat_gcss_lookup_miss_total_->addData(gcss_lookup_miss_total);
    if (stat_weight_read_dense_reqs_total_) stat_weight_read_dense_reqs_total_->addData(dense_reqs_total);
    if (stat_weight_read_dense_bytes_total_) stat_weight_read_dense_bytes_total_->addData(dense_bytes_total);
    if (stat_weight_read_rowptr_reqs_total_) stat_weight_read_rowptr_reqs_total_->addData(rowptr_reqs_total);
    if (stat_weight_read_rowptr_bytes_total_) stat_weight_read_rowptr_bytes_total_->addData(rowptr_bytes_total);
    if (stat_weight_read_colidx_reqs_total_) stat_weight_read_colidx_reqs_total_->addData(colidx_reqs_total);
    if (stat_weight_read_colidx_bytes_total_) stat_weight_read_colidx_bytes_total_->addData(colidx_bytes_total);
    if (stat_weight_read_blockdata_reqs_total_) stat_weight_read_blockdata_reqs_total_->addData(blockdata_reqs_total);
    if (stat_weight_read_blockdata_bytes_total_) stat_weight_read_blockdata_bytes_total_->addData(blockdata_bytes_total);
    if (stat_weight_read_gcss_reqs_total_) stat_weight_read_gcss_reqs_total_->addData(gcss_reqs_total);
    if (stat_weight_read_gcss_bytes_total_) stat_weight_read_gcss_bytes_total_->addData(gcss_bytes_total);
    if (stat_weight_idx_sram_reads_total_) stat_weight_idx_sram_reads_total_->addData(weight_idx_sram_reads_total);
    if (stat_weight_idx_sram_writes_total_) stat_weight_idx_sram_writes_total_->addData(weight_idx_sram_writes_total);
    if (stat_weight_idx_sram_bytes_read_total_) stat_weight_idx_sram_bytes_read_total_->addData(weight_idx_sram_bytes_read_total);
    if (stat_weight_idx_sram_bytes_write_total_) stat_weight_idx_sram_bytes_write_total_->addData(weight_idx_sram_bytes_write_total);
    if (stat_weight_idx_sram_bank_conflict_ticks_total_) stat_weight_idx_sram_bank_conflict_ticks_total_->addData(weight_idx_sram_bank_conflict_ticks_total);
    if (stat_weight_idx_sram_predicted_extra_cycles_total_) stat_weight_idx_sram_predicted_extra_cycles_total_->addData(weight_idx_sram_predicted_extra_cycles_total);
    if (stat_weight_idx_sram_resident_bytes_peak_) stat_weight_idx_sram_resident_bytes_peak_->addData(weight_idx_sram_resident_bytes_peak);
    if (stat_weight_idx_sram_bank_peak_accesses_per_tick_) stat_weight_idx_sram_bank_peak_accesses_per_tick_->addData(weight_idx_sram_bank_peak_accesses_per_tick);
    if (stat_weight_idx_sram_energy_read_pj_total_) stat_weight_idx_sram_energy_read_pj_total_->addData(weight_idx_sram_energy_read_pj_total);
    if (stat_weight_idx_sram_energy_write_pj_total_) stat_weight_idx_sram_energy_write_pj_total_->addData(weight_idx_sram_energy_write_pj_total);
    if (stat_weight_idx_lookup_total_) stat_weight_idx_lookup_total_->addData(weight_idx_lookup_total);
    if (stat_weight_idx_lookup_idx2_total_) stat_weight_idx_lookup_idx2_total_->addData(weight_idx_lookup_idx2_total);
    add_atlas_storage_stat(
        "atlas_storage_map_weight_idx_private_reads_total",
        weight_idx_sram_reads_total);
    add_atlas_storage_stat(
        "atlas_storage_map_weight_idx_private_resident_bytes_peak",
        weight_idx_sram_resident_bytes_peak);
    if (stat_weight_l0_sram_reads_total_) stat_weight_l0_sram_reads_total_->addData(weight_l0_sram_reads_total);
    if (stat_weight_l0_sram_writes_total_) stat_weight_l0_sram_writes_total_->addData(weight_l0_sram_writes_total);
    if (stat_weight_l0_sram_bytes_read_total_) stat_weight_l0_sram_bytes_read_total_->addData(weight_l0_sram_bytes_read_total);
    if (stat_weight_l0_sram_bytes_write_total_) stat_weight_l0_sram_bytes_write_total_->addData(weight_l0_sram_bytes_write_total);
    if (stat_weight_l0_sram_bank_conflict_ticks_total_) stat_weight_l0_sram_bank_conflict_ticks_total_->addData(weight_l0_sram_bank_conflict_ticks_total);
    if (stat_weight_l0_sram_predicted_extra_cycles_total_) stat_weight_l0_sram_predicted_extra_cycles_total_->addData(weight_l0_sram_predicted_extra_cycles_total);
    if (stat_weight_l0_sram_resident_bytes_peak_) stat_weight_l0_sram_resident_bytes_peak_->addData(weight_l0_sram_resident_bytes_peak);
    if (stat_weight_l0_sram_bank_peak_accesses_per_tick_) stat_weight_l0_sram_bank_peak_accesses_per_tick_->addData(weight_l0_sram_bank_peak_accesses_per_tick);
    if (stat_weight_l0_sram_energy_read_pj_total_) stat_weight_l0_sram_energy_read_pj_total_->addData(weight_l0_sram_energy_read_pj_total);
    if (stat_weight_l0_sram_energy_write_pj_total_) stat_weight_l0_sram_energy_write_pj_total_->addData(weight_l0_sram_energy_write_pj_total);
    if (stat_weight_sram_enforced_stall_cycles_total_) stat_weight_sram_enforced_stall_cycles_total_->addData(weight_sram_enforced_stall_cycles_total);
    if (stat_weight_l0_lookup_total_) stat_weight_l0_lookup_total_->addData(weight_l0_lookup_total);
    if (stat_weight_l0_hit_total_) stat_weight_l0_hit_total_->addData(weight_l0_hit_total);
    if (stat_weight_l0_fill_total_) stat_weight_l0_fill_total_->addData(weight_l0_fill_total);
    if (stat_weight_l0_evict_total_) stat_weight_l0_evict_total_->addData(weight_l0_evict_total);
    add_atlas_storage_stat(
        "atlas_storage_map_weight_value_private_reads_total",
        weight_l0_sram_reads_total);
    add_atlas_storage_stat(
        "atlas_storage_map_weight_value_private_resident_bytes_peak",
        weight_l0_sram_resident_bytes_peak);
    if (stat_core_state_sram_reads_total_) stat_core_state_sram_reads_total_->addData(core_state_sram_reads_total);
    if (stat_core_state_sram_writes_total_) stat_core_state_sram_writes_total_->addData(core_state_sram_writes_total);
    if (stat_core_state_sram_bytes_read_total_) stat_core_state_sram_bytes_read_total_->addData(core_state_sram_bytes_read_total);
    if (stat_core_state_sram_bytes_write_total_) stat_core_state_sram_bytes_write_total_->addData(core_state_sram_bytes_write_total);
    if (stat_core_state_sram_bank_conflict_ticks_total_) stat_core_state_sram_bank_conflict_ticks_total_->addData(core_state_sram_bank_conflict_ticks_total);
    if (stat_core_state_sram_predicted_extra_cycles_total_) stat_core_state_sram_predicted_extra_cycles_total_->addData(core_state_sram_predicted_extra_cycles_total);
    if (stat_core_state_sram_resident_bytes_peak_) stat_core_state_sram_resident_bytes_peak_->addData(core_state_sram_resident_bytes_peak);
    if (stat_core_state_sram_bank_peak_accesses_per_tick_) stat_core_state_sram_bank_peak_accesses_per_tick_->addData(core_state_sram_bank_peak_accesses_per_tick);
    if (stat_core_state_sram_energy_read_pj_total_) stat_core_state_sram_energy_read_pj_total_->addData(core_state_sram_energy_read_pj_total);
    if (stat_core_state_sram_energy_write_pj_total_) stat_core_state_sram_energy_write_pj_total_->addData(core_state_sram_energy_write_pj_total);
    if (stat_core_state_sram_stall_cycles_total_) stat_core_state_sram_stall_cycles_total_->addData(core_state_sram_stall_cycles_total);
    if (stat_gas_retire_global_hol_cycles_total_) stat_gas_retire_global_hol_cycles_total_->addData(gas_retire_global_hol_cycles_total);
    if (stat_gas_retire_ready_but_blocked_edges_total_) stat_gas_retire_ready_but_blocked_edges_total_->addData(gas_retire_ready_but_blocked_edges_total);
    if (stat_gas_retire_per_post_progress_total_) stat_gas_retire_per_post_progress_total_->addData(gas_retire_per_post_progress_total);
    if (stat_gas_retire_samepost_blocked_edges_total_) stat_gas_retire_samepost_blocked_edges_total_->addData(gas_retire_samepost_blocked_edges_total);
    if (stat_gas_retire_crosspost_blocked_edges_total_) stat_gas_retire_crosspost_blocked_edges_total_->addData(gas_retire_crosspost_blocked_edges_total);
    if (stat_gas_retire_policy_loss_cycles_total_) stat_gas_retire_policy_loss_cycles_total_->addData(gas_retire_policy_loss_cycles_total);
    if (stat_gas_retire_policy_loss_edges_total_) stat_gas_retire_policy_loss_edges_total_->addData(gas_retire_policy_loss_edges_total);
    if (stat_gas_retire_shadow_per_post_recoverable_cycles_total_) stat_gas_retire_shadow_per_post_recoverable_cycles_total_->addData(gas_retire_shadow_per_post_recoverable_cycles_total);
    if (stat_gas_retire_shadow_per_post_recoverable_edges_total_) stat_gas_retire_shadow_per_post_recoverable_edges_total_->addData(gas_retire_shadow_per_post_recoverable_edges_total);
    if (stat_gas_retire_shadow_per_post_ready_posts_peak_) stat_gas_retire_shadow_per_post_ready_posts_peak_->addData(gas_retire_shadow_per_post_ready_posts_peak);
    if (stat_gas_retire_shadow_per_post_committable_edges_peak_) stat_gas_retire_shadow_per_post_committable_edges_peak_->addData(gas_retire_shadow_per_post_committable_edges_peak);
}

void MultiCorePE::notifyStageEvent(uint32_t seq, const std::string& event, uint64_t ts_ns,
                                   uint64_t spikes_emitted, int core_id) {
    auto &m = stage_marks_[seq];
    StageMarks* core_marks = nullptr;
    if (core_id >= 0) {
        core_marks = &getOrCreateCoreStageMarks_(core_id, seq);
    }
    auto apply_stage_event = [&](StageMarks& marks) {
        if (event == "BeginGather") {
            if (marks.bg == 0 || ts_ns < marks.bg) marks.bg = ts_ns;
        } else if (event == "BeginApply") {
            if (marks.ga == 0 || ts_ns > marks.ga) marks.ga = ts_ns;
        } else if (event == "EndApply") {
            if (marks.ea == 0 || ts_ns > marks.ea) marks.ea = ts_ns;
        } else if (event == "BeginScatter") {
            if (marks.bs == 0 || ts_ns > marks.bs) marks.bs = ts_ns;
        } else if (event == "EndScatter") {
            if (marks.es == 0 || ts_ns > marks.es) marks.es = ts_ns;
        }
    };
    apply_stage_event(m);
    if (core_marks) {
        apply_stage_event(*core_marks);
    }

    // Experiment observability: naive_raw must not execute GAS Apply/Scatter stages.
    // Note: BeginGather/EndScatter may be used as generic step boundary markers in some modes;
    // only flag stages unique to GAS/window pipeline to avoid false positives.
    if (exec_mode_ == "naive_raw" &&
        (event == "BeginApply" || event == "EndApply" || event == "BeginScatter")) {
        if (stat_compat_naive_gas_stage_events_total_) stat_compat_naive_gas_stage_events_total_->addData(1);
    }

    // Global Step 诊断：记录每核在 active_seq 内的最后阶段，用于 finish() 输出卡点
    if (global_step_sync_enable_ &&
        seq == global_step_active_seq_ &&
        core_id >= 0 &&
        core_id < num_cores_ &&
        global_step_last_stage_code_.size() == static_cast<size_t>(num_cores_)) {
        const size_t idx = static_cast<size_t>(core_id);
        global_step_last_stage_code_[idx] = stepStageCodeFromName_(event);
        global_step_last_stage_seq_[idx] = seq;
        global_step_last_stage_ts_ns_[idx] = ts_ns;
        global_step_last_stage_spikes_[idx] = spikes_emitted;
    }

    if (sentinel_enabled_ && output_ && seq <= 2 &&
        global_step_sync_enable_ &&
        seq == global_step_active_seq_ &&
        (event == "BeginGather" || event == "BeginApply" || event == "EndApply" ||
         event == "BeginScatter" || event == "EndScatter")) {
        output_->verbose(CALL_INFO, 2, 0,
            "[[sentinel-step-sync]] node=%d stage=%s core=%d seq=%u ts_ns=%" PRIu64 " spikes=%" PRIu64 "\n",
            node_id_, event.c_str(), core_id, seq, (uint64_t)ts_ns, (uint64_t)spikes_emitted);
    }

    // Step 注入事件转发（Phase3-B 下沉为 StepActivationSubsystem）
    if (event == "BeginGather") {
        if (sentinel_enabled_ && output_ && node_id_ == 0 && seq <= 2 && core_id >= 15) {
            output_->verbose(
                CALL_INFO, 2, 0,
                "[[sentinel-step-path]] node=%d core=%d seq=%u notifyStageEvent before_step_activation ts_ns=%" PRIu64 "\n",
                node_id_, core_id, seq, static_cast<uint64_t>(ts_ns));
        }
        step_activation_subsys_.onBeginGather(seq, ts_ns, core_id);
        if (sentinel_enabled_ && output_ && node_id_ == 0 && seq <= 2 && core_id >= 15) {
            output_->verbose(
                CALL_INFO, 2, 0,
                "[[sentinel-step-path]] node=%d core=%d seq=%u notifyStageEvent after_step_activation\n",
                node_id_, core_id, seq);
        }
    } else if (event == "BeginApply") {
        if (pulse_fabric_) {
            pulse_fabric_->closeGatherHarborStep(seq);
        }
    } else if (event == "EndScatter") {
        if (core_id >= 0 && core_id < num_cores_) {
            auto& reset_state = step_endscatter_reset_state_[seq];
            if (reset_state.cores_seen.size() != static_cast<size_t>(num_cores_)) {
                reset_state.cores_seen.assign(static_cast<size_t>(num_cores_), 0);
                reset_state.done_count = 0;
                reset_state.reset_fired = false;
            }
            const size_t idx = static_cast<size_t>(core_id);
            if (reset_state.cores_seen[idx] == 0) {
                reset_state.cores_seen[idx] = 1;
                reset_state.done_count += 1;
            }
            // reset_mem_each_step 必须等本 PE 的所有 core 都真正结束该 step 的 Scatter 之后再触发，
            // 否则早到 core 会提前清掉状态，晚到 core 又会把旧 step 的 refractory/last_spike 写回。
            if (!reset_state.reset_fired &&
                reset_state.done_count >= static_cast<uint32_t>(num_cores_)) {
                step_activation_subsys_.onEndScatter(seq);
                reset_state.reset_fired = true;
            }
        }
    }

    // Global Step barrier: 当本 PE 的所有 core 都完成 EndScatter(seq) 后，上报给控制器（EndScatter policy）
    if (global_step_sync_enable_ &&
        gas_step_ctrl_link_ &&
        !global_step_done_sent_ &&
        global_step_done_policy_ == GlobalStepDonePolicy::EndScatter &&
        event == "EndScatter" &&
        seq == global_step_active_seq_) {
        if (core_id >= 0 && core_id < num_cores_) {
            global_step_done_cores_[static_cast<size_t>(core_id)] = 1;
            if (sentinel_enabled_ && output_ && seq <= 2) {
                size_t done_cnt = 0;
                for (auto v : global_step_done_cores_) if (v) ++done_cnt;
                output_->verbose(CALL_INFO, 2, 0,
                    "[[sentinel-step-sync]] node=%d mark EndScatter core=%d seq=%u active=%u done=%zu/%d\n",
                    node_id_, core_id, seq, global_step_active_seq_, done_cnt, num_cores_);
            }
            bool all_done = true;
            for (auto v : global_step_done_cores_) {
                if (!v) { all_done = false; break; }
            }
            if (all_done) {
                noteStepBarrierWaitNs_(seq, getCurrentSimTimeNano());
                auto* ev = new GasStepBarrierEvent(GasStepBarrierOp::PeDone, seq, static_cast<uint32_t>(node_id_));
                // Step-level telemetry: reuse PE-level stage marks aggregated in notifyStageEvent().
                // This is used by GlobalGasStepController for criticality-aware global credit control.
                if (m.bg != 0 && m.es != 0 && m.es >= m.bg) {
                    ev->step_total_ns = m.es - m.bg;
                }
                if (m.ga != 0 && m.bs != 0 && m.bs >= m.ga) {
                    ev->step_apply_ns = m.bs - m.ga;
                }
                gas_step_ctrl_link_->send(ev);
                global_step_done_sent_ = true;
                if (stat_global_steps_done_total_) stat_global_steps_done_total_->addData(1);
                if (sentinel_enabled_ && output_ && seq <= 2) {
                    output_->verbose(CALL_INFO, 2, 0, "[[sentinel-step-sync]] node=%d send PE_DONE seq=%u\n", node_id_, seq);
                }
            }
        }
    }
}

void MultiCorePE::mergeWindowMetricsFromCsv_() {
    if (!window_stats_enable_ || window_metrics_csv_.empty() || windows_.empty()) return;
    std::ifstream fin(window_metrics_csv_);
    if (!fin.good()) return;
    std::string line;
    if (!std::getline(fin, line)) return; // header
    std::vector<std::pair<uint64_t,uint64_t>> entries;
    while (std::getline(fin, line)) {
        if (line.empty()) continue;
        std::stringstream ss(line);
        std::string field;
        std::vector<std::string> cols;
        while (std::getline(ss, field, ',')) cols.push_back(field);
        if (cols.size() < 5) continue;
        uint64_t inflight = 0;
        uint64_t buffer = 0;
        try { inflight = static_cast<uint64_t>(std::stoull(cols[3])); } catch (...) {}
        try { buffer = static_cast<uint64_t>(std::stoull(cols[4])); } catch (...) {}
        entries.emplace_back(buffer, inflight);
    }
    if (entries.empty()) return;
    const size_t total_rows = entries.size();
    for (size_t i = 0; i < entries.size(); ++i) {
        size_t idx = (total_rows > 0) ? (i * windows_.size()) / total_rows : 0;
        if (idx >= windows_.size()) idx = windows_.size() - 1;
        auto& w = windows_[idx];
        uint64_t buffer = entries[i].first;
        uint64_t inflight = entries[i].second;
        if (buffer > w.sb_peak_bytes) w.sb_peak_bytes = buffer;
        if (inflight > w.inflight_peak) w.inflight_peak = inflight;
    }
}

void MultiCorePE::writeWindowCsv_() {
    std::ofstream fout(window_csv_);
    if (!fout.good()) {
        PE_LOG(1, "⚠️ 无法写入窗口统计CSV: %s\n", window_csv_.c_str());
        return;
    }
    mergeWindowMetricsFromCsv_();

    fout << "window_start_us,window_end_us,read_count,avg_read_latency_cycles,issue_count,avg_req_size_bytes,avg_outstanding,avg_activity_f,sb_peak_bytes,inflight_peak" << '\n';
    for (const auto& w : windows_) {
        if (w.end_ns == 0) continue; // 未初始化
        double start_us = static_cast<double>(w.start_ns) / 1000.0;
        double end_us   = static_cast<double>(w.end_ns) / 1000.0;
        double avg_lat  = (w.read_count > 0) ? (static_cast<double>(w.read_latency_sum) / w.read_count) : 0.0;
        double avg_size = (w.issue_count > 0) ? (static_cast<double>(w.req_size_sum) / w.issue_count) : 0.0;
        double avg_out  = (w.issue_count > 0) ? (static_cast<double>(w.outstanding_sum) / w.issue_count) : 0.0;
        double avg_f   = (w.activity_f_count > 0) ? (w.activity_f_sum / (double)w.activity_f_count) : 0.0;
        fout << start_us << ',' << end_us << ','
             << w.read_count << ',' << avg_lat << ','
             << w.issue_count << ',' << avg_size << ',' << avg_out << ',' << avg_f << ','
             << w.sb_peak_bytes << ',' << w.inflight_peak << '\n';
    }
    fout.close();
}

void MultiCorePE::initializeProcessingUnits() {
    
    cores_.reserve(num_cores_);
    
    const bool core_pe_internal_cpe_enable =
        pe_internal_cpe_enable_cfg_;
    const bool core_pe_internal_pod_enable =
        pe_internal_pod_enable_cfg_;
    const uint32_t core_pe_internal_pod_count = pe_internal_pod_count_cfg_;
    const uint32_t core_pe_internal_pod_size = pe_internal_pod_size_cfg_;

    for (int i = 0; i < num_cores_; i++) {
        int neuron_id_start = node_id_ * total_neurons_ + i * neurons_per_core_;
        
        // 创建SnnPE SubComponent参数
        Params core_params;
        core_params.insert("core_id", std::to_string(i));
        // 默认口径：每个 core 只负责自身的 neurons_per_core（global_neuron_base 由 core 偏移决定）
        core_params.insert("num_neurons", std::to_string(neurons_per_core_));
        core_params.insert("neurons_per_pe", std::to_string(neurons_per_pe_cfg_));
        core_params.insert("total_cores", std::to_string(num_cores_));
        core_params.insert("total_nodes", std::to_string(total_nodes_));
        core_params.insert(
            "global_neuron_base",
            std::to_string(static_cast<uint64_t>(global_neuron_base_) + static_cast<uint64_t>(i) * static_cast<uint64_t>(neurons_per_core_)));
        core_params.insert("v_thresh", std::to_string(v_thresh_));
        core_params.insert("v_reset", std::to_string(v_reset_));
        core_params.insert("v_rest", std::to_string(v_rest_));
        core_params.insert("tau_mem", std::to_string(tau_mem_));
        core_params.insert("t_ref", std::to_string(t_ref_));
        core_params.insert("node_id", std::to_string(node_id_));
        core_params.insert("step_seed_only_mode", std::to_string(step_seed_only_mode_ ? 1 : 0));
        // 若 Python 侧未提供 base_addr，则退回旧的简单映射；否则尊重传入值
        if (!core_params.contains("base_addr")) {
            core_params.insert("base_addr", std::to_string(neuron_id_start * 1000)); // 简单地址映射（仅兜底）
        }
        core_params.insert("verbose", std::to_string(verbose_));
        
        // 传递权重文件参数
        if (!weights_file_.empty()) {
            core_params.insert("weights_file", weights_file_);
        }
        
        // 传递权重验证参数
        core_params.insert("verify_weights", std::to_string(verify_weights_ ? 1 : 0));
        core_params.insert("weight_verify_samples", std::to_string(weight_verify_samples_));
        core_params.insert("expected_weight_value", std::to_string(expected_weight_value_));
        core_params.insert("verify_log_each_sample", std::to_string(verify_log_each_sample_ ? 1 : 0));

        // 传递权重回退参数 - 关键修复！
        core_params.insert("use_event_weight_fallback", std::to_string(use_event_weight_fallback_ ? 1 : 0));
        core_params.insert("enable_memory_weights", std::to_string(enable_memory_weights_ ? 1 : 0));
        core_params.insert("write_weights_on_init", std::to_string(write_weights_on_init_ ? 1 : 0));
        core_params.insert(
            "pe_internal_cpe_enable",
            std::to_string(core_pe_internal_cpe_enable ? 1 : 0));
        core_params.insert(
            "pe_internal_pod_enable",
            std::to_string(core_pe_internal_pod_enable ? 1 : 0));
        core_params.insert(
            "pe_internal_pod_metadata_enable",
            std::to_string(
                pe_internal_pod_metadata_enable_cfg_ ? 1 : 0));
        core_params.insert(
            "pe_internal_pod_owner_enable",
            std::to_string(
                pe_internal_pod_owner_enable_cfg_ ? 1 : 0));
        core_params.insert(
            "pe_internal_pod_count",
            std::to_string(core_pe_internal_pod_count));
        core_params.insert(
            "pe_internal_pod_size",
            std::to_string(core_pe_internal_pod_size));
        // 记录槽位可用性（Phase9：核心槽位 API 改为 CoreShellAPI）
        bool slot_api_ok = isSubComponentLoadableUsingAPI<CoreShellAPI>("core" + std::to_string(i));

        // 优先尝试通过用户在Python中配置的槽位加载
        CoreShellAPI* core = loadUserSubComponent<CoreShellAPI>(
            "core" + std::to_string(i), ComponentInfo::SHARE_NONE);
        if (core) {
        }

        if (!core) {
            // 如果用户未配置，则回退到匿名加载默认实现
            core = loadAnonymousSubComponent<CoreShellAPI>(
                "SnnDL.SnnPESubComponent", "core" + std::to_string(i), 0, ComponentInfo::SHARE_NONE, core_params);
            if (core) {
            } else {
                if (output_) {
                    output_->fatal(
                        CALL_INFO, -1,
                        "Phase9 fatal: failed to load core%d SubComponent.\n"
                        "  - slot=\"core%d\" api_ok(CoreShellAPI)=%d\n"
                        "  - attempted anonymous impl: \"SnnDL.SnnPESubComponent\"\n"
                        "请检查：SnnPESubComponent 的 ELI 注册父接口是否为 SnnCoreAPI/CoreShellAPI，以及 Python 侧是否覆写了 core%d 槽位。\n",
                        i, i, slot_api_ok ? 1 : 0, i);
                }
                // output_ == nullptr 时仍保持旧行为，避免 nullptr 解引用
                PE_LOG(1, "[core%d] 匿名加载失败（output_=nullptr）\n", i);
            }
        } else {
            // 若由用户配置，补充必要参数（若Python侧未给全量）
            // 这里不强制覆盖，参数以Python为准
        }
        
        if (core) {
            core->setParentInterface(this);
            // Phase4-A1.3：为 Control 注入 NoC 抽象接口（优先走 NocSubsystem，不依赖 MultiCorePE send/forward 细节）
            if (auto* hooks = dynamic_cast<ICoreControlHooks*>(core)) {
                hooks->setNocTransport(&noc_subsys_);
            }
            // 为每个核心配置内存Link（若用户在Python连接了对应端口则不为None）
            std::string port = "core" + std::to_string(i) + "_mem";
            Link* l = configureLink(port);
            if (l) {
                auto* ml = dynamic_cast<ICoreMemoryLink*>(core);
                if (!ml) {
                    output_->fatal(CALL_INFO, -1,
                                   "Phase9 fatal: core%d has a configured memory link (%s) but does not implement ICoreMemoryLink\n",
                                   i, port.c_str());
                }
                ml->setMemoryLink(l);
            }
            cores_.push_back(core);
        } else {
            cores_.push_back(nullptr);
        }
        
        PE_LOG(3, "   ✅ SnnPE核心%d: 神经元ID范围[%d, %d)\n",
                        i, neuron_id_start, neuron_id_start + neurons_per_core_);
    }

    // loader_done 事件可能在 init(phase0) 的 link 配置完成后、core 创建之前到达并被 drain，
    // 此时 handleLoaderDoneEvent() 无法下发到 core（cores_ 仍为空）。
    // 在 core 创建完成后，若 loader_ready 已被 latch，则补发一次本地就绪回调，确保 core 侧 latch 不丢失。
    if (loader_ready_latched_) {
        for (auto* core : cores_) {
            if (!core) continue;
            if (auto* hook = dynamic_cast<ILoaderReadyHooks*>(core)) {
                hook->onLoaderReady();
            }
        }
    }
    
    
    // 添加权重配置摘要
    // if (!weights_file_.empty()) {
    //     PE_LOG(1, "📋 节点%d权重配置摘要: %zu个核心使用权重文件 %s\n", 
    //                     node_id_, cores_.size(), weights_file_.c_str());
    // }
}

void MultiCorePE::initializeInternalRing() {
    // 单核情况下无需内部环形网络
    if (num_cores_ <= 1) {
        optimized_ring_ = nullptr;
        return;
    }
    
    // Phase5：仅保留 OptimizedInternalRing 作为片上互连后端（legacy InternalRing 已冻结/移除）
    if (!use_optimized_ring_) {
        output_->fatal(CALL_INFO, -1,
            "❌ 配置错误：use_optimized_ring=0 (legacy InternalRing) 已冻结/不再支持，请设置 use_optimized_ring=1\n");
    }

    // 使用新的 OptimizedInternalRing
    int num_vcs = 2;                // 每方向2个虚拟通道
    uint32_t credits_per_vc = 8;    // 每VC 8个信用
    optimized_ring_ = new OptimizedInternalRing(num_cores_, num_vcs, credits_per_vc, output_);
}

void MultiCorePE::loadAndDistributeWeights() {
    if (weights_file_.empty()) {
        PE_LOG(2, "⚠️ 未指定权重文件，使用默认权重\n");
        return;
    }

    // 当前架构下权重文件通过核心参数传递给各个 SnnPESubComponent，
    // 这里保持幂等 no-op，避免误导性的“未实现”行为。
    PE_LOG(2, "ℹ️ weights_file 已通过 core_params 下发至子核心，跳过PE级重复分发\n");
}

void MultiCorePE::updateStatistics() {
    // 收集处理单元统计信息
    uint64_t total_spikes = 0;
    uint64_t total_fired = 0;
    double total_utilization = 0.0;
    
    for (int i = 0; i < num_cores_; i++) {
        total_spikes += unit_states_[i].spikes_processed;
        total_fired += unit_states_[i].neurons_fired;
        total_utilization += unit_states_[i].utilization;
    }

    // 更新统计信息
    if (stat_spikes_processed_) stat_spikes_processed_->addData(total_spikes);
    if (stat_neurons_fired_) stat_neurons_fired_->addData(total_fired);
    if (stat_avg_utilization_) stat_avg_utilization_->addData(total_utilization / num_cores_);
    for (auto& mod : workload_stats_modules_) {
        if (mod) mod->emitDeltas();
    }

    if (diag_fire_log_ && output_) {
        std::ostringstream oss;
        oss << "[diag-pe-fire] node=" << node_id_
            << " cycle=" << current_cycle_
            << " total_fired=" << total_fired
            << " per_core=";
        for (int i = 0; i < num_cores_; ++i) {
            if (i) oss << ",";
            oss << i << ":" << unit_states_[i].neurons_fired;
        }
        output_->verbose(CALL_INFO, 1, 0, "%s\n", oss.str().c_str());
    }
    
    // 详细调试信息
    if (verbose_ >= 3 && current_cycle_ % 10000 == 0) {
        PE_LOG(3, "📊 周期%" PRIu64 "统计: 脉冲=%" PRIu64 ", 发放=%" PRIu64 ", 利用率=%.2f\n",
                        current_cycle_, total_spikes, total_fired, (total_utilization / num_cores_) * 100.0);
    }
}

void MultiCorePE::generateTestTraffic() {
    // 检查是否已达到最大测试脉冲数限制
    if (test_max_spikes_ > 0 && test_spikes_sent_ >= test_max_spikes_) {
        return;  // 已达到限制，停止生成测试流量
    }
    
    test_cycle_counter_++;
    
    if (test_cycle_counter_ >= static_cast<uint64_t>(test_period_)) {
        test_cycle_counter_ = 0;
        
        // 计算本次可发送的脉冲数
        int spikes_to_send = test_spikes_per_burst_;
        if (test_max_spikes_ > 0) {
            spikes_to_send = std::min(spikes_to_send, test_max_spikes_ - test_spikes_sent_);
        }
        
        if (spikes_to_send > 0) {
            PE_LOG(4, "🔥 生成测试流量: %d个脉冲 (已发送%d/%d)\n", 
                            spikes_to_send, test_spikes_sent_, test_max_spikes_);

            if (test_traffic_packet_kind_ == "spikekey_direct_v4") {
                // 走下面的逐条 per-core synthetic emit 路径，复用 workload=snn 的真实 3D route/spike-comm。
            } else if (test_traffic_packet_kind_ == "spiketile_bundle_v3") {
                std::unordered_map<int, std::vector<uint32_t>> batch_by_endpoint;
                batch_by_endpoint.reserve(static_cast<size_t>(std::max(spikes_to_send, 1)));
                for (int i = 0; i < spikes_to_send; i++) {
                    const int local_pre = (i % total_neurons_);
                    const int src_endpoint = local_pre / std::max(neurons_per_core_, 1);
                    batch_by_endpoint[src_endpoint].push_back(static_cast<uint32_t>(local_pre));
                }
                for (const auto& kv : batch_by_endpoint) {
                    const int src_endpoint = kv.first;
                    if (src_endpoint < 0 || src_endpoint >= static_cast<int>(cores_.size()) ||
                        cores_[src_endpoint] == nullptr) {
                        continue;
                    }
                    const uint64_t emitted =
                        cores_[src_endpoint]->syntheticEmitNeuronFireBatch(kv.second, current_cycle_);
                    test_spikes_sent_ += static_cast<int>(emitted);
                }
                return;
            }

            for (int i = 0; i < spikes_to_send; i++) {
                const int local_pre = (i % total_neurons_);
                const int src_neuron = node_id_ * total_neurons_ + local_pre;
                const int dst_neuron = test_target_node_ * total_neurons_ + local_pre;
                const int src_endpoint = local_pre / std::max(neurons_per_core_, 1);
                const uint16_t dst_endpoint = static_cast<uint16_t>(src_endpoint);
                bool emitted = false;

                if (test_traffic_packet_kind_ == "spikekey_direct_v4") {
                    if (src_endpoint >= 0 && src_endpoint < static_cast<int>(cores_.size()) &&
                        cores_[src_endpoint] != nullptr) {
                        emitted = cores_[src_endpoint]->syntheticEmitNeuronFire(
                            static_cast<uint32_t>(local_pre),
                            current_cycle_);
                    }
                } else if (test_traffic_packet_kind_ == "spikekey") {
                    auto* pkt = buildSyntheticSpikeKeyPacket_(
                        static_cast<uint32_t>(node_id_),
                        static_cast<uint16_t>(src_endpoint),
                        static_cast<uint32_t>(test_target_node_),
                        dst_endpoint,
                        static_cast<uint32_t>(src_neuron),
                        current_cycle_);
                    noc_subsys_.sendFromCore(src_endpoint, pkt);
                    emitted = true;
                } else {
                    // 使用配置的目标节点，避免被错误地回送到自身
                    auto* test_spike = new SpikeEvent(src_neuron,
                                                      dst_neuron,
                                                      static_cast<uint32_t>(test_target_node_),
                                                      test_weight_,
                                                      current_cycle_);
                    sendExternalSpike(test_spike);
                    emitted = true;
                }
                if (emitted) {
                    test_spikes_sent_++;
                }
            }
        }
    }
}

void MultiCorePE::checkLoadBalance() {
    if (!controller_) return;
    
    // 计算负载差异
    double max_util = 0.0, min_util = 1.0;
    for (int i = 0; i < num_cores_; i++) {
        double util = unit_states_[i].utilization;
        max_util = std::max(max_util, util);
        min_util = std::min(min_util, util);
    }
    
    double load_imbalance = max_util - min_util;
    if (load_imbalance > 0.3) {  // 30%负载差异阈值
        //                 load_imbalance * 100.0, max_util * 100.0, min_util * 100.0);
        
        controller_->balanceLoad();
    }
}

// ===== MultiCoreController 实现 =====

MultiCoreController::MultiCoreController(MultiCorePE* parent, SST::Output* output)
    : parent_pe_(parent), output_(output) {
    
    // 初始化负载均衡状态
    core_utilization_history_.resize(parent_pe_->num_cores_, 0.0);
    core_work_count_.resize(parent_pe_->num_cores_, 0);
    
    // 初始化统计变量
    total_work_distributed_ = 0;
    load_imbalance_count_ = 0;
    load_balance_threshold_ = 0.2;  // 20%负载差异阈值
    
}

MultiCoreController::~MultiCoreController() {
}

void MultiCoreController::scheduleWork() {
    // 简单的轮询调度策略
    // 实际实现中可以根据负载情况进行智能调度
    
    static int next_core = 0;
    
    // 轮询分配工作到下一个核心
    next_core = (next_core + 1) % parent_pe_->num_cores_;
    core_work_count_[next_core]++;
    total_work_distributed_++;
    
    //                 next_core, total_work_distributed_);
}

void MultiCoreController::balanceLoad() {
    
    int most_loaded = findMostLoadedCore();
    int least_loaded = findLeastLoadedCore();
    
    if (most_loaded != least_loaded && most_loaded >= 0 && least_loaded >= 0) {
        double load_diff = core_utilization_history_[most_loaded] - core_utilization_history_[least_loaded];
        
        if (load_diff > load_balance_threshold_) {
            redistributeWork();
            load_imbalance_count_++;
            
            //                most_loaded, core_utilization_history_[most_loaded] * 100.0,
            //                least_loaded, core_utilization_history_[least_loaded] * 100.0);
        }
    }
}

void MultiCoreController::tick() {
    // 每个时钟周期更新性能计数器
    updatePerformanceCounters();
}

void MultiCoreController::updatePerformanceCounters() {
    // 更新每个核心的利用率历史
    for (int i = 0; i < parent_pe_->num_cores_; i++) {
        const auto& state = parent_pe_->getProcessingUnitState(i);
        
        // 使用指数移动平均更新利用率历史
        double alpha = 0.1;  // 平滑因子
        core_utilization_history_[i] = alpha * state.utilization + 
                                      (1.0 - alpha) * core_utilization_history_[i];
    }
}

double MultiCoreController::getCoreUtilization(int core_id) const {
    if (core_id >= 0 && core_id < parent_pe_->num_cores_) {
        return core_utilization_history_[core_id];
    }
    return 0.0;
}

double MultiCoreController::getOverallUtilization() const {
    if (parent_pe_->num_cores_ == 0) return 0.0;
    
    double total_util = 0.0;
    for (int i = 0; i < parent_pe_->num_cores_; i++) {
        total_util += core_utilization_history_[i];
    }
    
    return total_util / parent_pe_->num_cores_;
}

void MultiCoreController::redistributeWork() {
    // 简化的工作重分布策略
    // 实际实现中可能需要迁移脉冲队列或调整权重分布
    
    int most_loaded = findMostLoadedCore();
    int least_loaded = findLeastLoadedCore();
    
    if (most_loaded >= 0 && least_loaded >= 0 && most_loaded != least_loaded) {
        // 将一些工作从最繁忙的核心转移到最空闲的核心
        uint64_t work_to_transfer = core_work_count_[most_loaded] / 10;  // 转移10%的工作
        
        core_work_count_[most_loaded] -= work_to_transfer;
        core_work_count_[least_loaded] += work_to_transfer;
        
        //                 most_loaded, least_loaded, work_to_transfer);
    }
}

int MultiCoreController::findLeastLoadedCore() const {
    int least_loaded = 0;
    double min_utilization = core_utilization_history_[0];
    
    for (int i = 1; i < parent_pe_->num_cores_; i++) {
        if (core_utilization_history_[i] < min_utilization) {
            min_utilization = core_utilization_history_[i];
            least_loaded = i;
        }
    }
    
    return least_loaded;
}

int MultiCoreController::findMostLoadedCore() const {
    int most_loaded = 0;
    double max_utilization = core_utilization_history_[0];
    
    for (int i = 1; i < parent_pe_->num_cores_; i++) {
        if (core_utilization_history_[i] > max_utilization) {
            max_utilization = core_utilization_history_[i];
            most_loaded = i;
        }
    }
    
    return most_loaded;
}

// ===== SnnPEParentInterface 实现 =====

void MultiCorePE::sendSpike(SpikeEvent* event) {
    if (!event) return;

    PE_LOG(4, "📤 从SubComponent接收脉冲: 源神经元%d -> 目标神经元%d\n",
                    event->getSourceNeuron(), event->getDestinationNeuron());

    // Phase3-C：MultiCorePE 不直接做 Spike 编码；委托 SpikePacketBridge 生成 packet 并走 NoC。
    spike_packet_bridge_.sendAuto(event);
}

void MultiCorePE::requestMemoryAccess(uint64_t address, size_t size, 
                                    std::function<void(const void*)> callback) {
    (void)callback;
    output_->fatal(
        CALL_INFO, -1,
        "MultiCorePE fatal: requestMemoryAccess 已废弃/禁止使用（避免引入权重语义耦合）。"
        "请改走 services/memory/StandardMemAccess + services/synapse/weights 事务链路；addr=0x%" PRIx64 " size=%zu\n",
        static_cast<uint64_t>(address), size);
}

void MultiCorePE::deliverPacketDirectToCore_(int endpoint_id,
                                             NocPacketEvent* pkt,
                                             bool pulse_account_delivery) {
    if (!pkt) return;

    if (pkt->packetKind() == NocPacketKind::Spike) {
        if (pulse_account_delivery && pulse_fabric_) {
            pulse_fabric_->observeIngressDrain();
            pulse_fabric_->observeCoreQueueEnqueue(endpoint_id);
        }
        const bool taken = cores_[endpoint_id]->deliverPacket(pkt);
        if (pulse_account_delivery && pulse_fabric_) {
            pulse_fabric_->observeCoreQueueDequeue(endpoint_id);
        }
        if (!taken) {
            output_->fatal(CALL_INFO, -1,
                           "Phase8(strict): core=%d refused Spike packet (kind=%u); legacy deliverSpike fallback is disabled\n",
                           endpoint_id, static_cast<unsigned>(pkt->kind));
        }
        return;
    }

    if (pulse_account_delivery && pulse_fabric_) {
        pulse_fabric_->observeIngressDrain();
        pulse_fabric_->observeCoreQueueEnqueue(endpoint_id);
    }
    const bool taken = cores_[endpoint_id]->deliverPacket(pkt);
    if (pulse_account_delivery && pulse_fabric_) {
        pulse_fabric_->observeCoreQueueDequeue(endpoint_id);
    }
    if (!taken) {
        PE_LOG(2, "⚠️ core=%d 未处理 packet(kind=%u)，已回收\n",
               endpoint_id, static_cast<unsigned>(pkt->kind));
        delete pkt;
    }
}

void MultiCorePE::deliverPacketToEndpoint_(int endpoint_id, NocPacketEvent* pkt) {
    if (!pkt) return;

    // step_seq 门控（naive_raw baseline）：禁用“步内级联”，将 future-step spike 暂存到对应 step 再投递。
    if (exec_mode_ == "naive_raw" &&
        global_step_sync_enable_ &&
        global_step_active_seq_ != 0 &&
        (pkt->packetKind() == NocPacketKind::Spike ||
         pkt->packetKind() == NocPacketKind::SpikeKey ||
         pkt->packetKind() == NocPacketKind::SpikeTileKey)) {
        const uint32_t target_seq = pkt->step_seq;
        if (target_seq != 0 && target_seq > global_step_active_seq_) {
            deferred_packets_by_seq_[target_seq].push_back(DeferredNocPacket{endpoint_id, pkt});
            return;
        }
    }

    // NoC e2e latency (cycles): measured at PE drain boundary (after mesh + local delivery).
    {
        const uint64_t send_ts = pkt->timestamp;
        const uint64_t now_ts = current_cycle_;
        const uint64_t lat = (now_ts >= send_ts) ? (now_ts - send_ts) : 0;
        const uint64_t bin = (lat <= static_cast<uint64_t>(noc_lat_hist_max_)) ? lat : (static_cast<uint64_t>(noc_lat_hist_max_) + 1u);
        if (pkt->packetKind() == NocPacketKind::Spike) {
            noc_lat_spike_cnt_ += 1;
            noc_lat_spike_sum_ += lat;
            noc_lat_spike_max_ = std::max<uint64_t>(noc_lat_spike_max_, lat);
            if (bin < noc_lat_spike_hist_.size()) noc_lat_spike_hist_[static_cast<size_t>(bin)] += 1;
        } else if (pkt->packetKind() == NocPacketKind::SpikeKey ||
                   pkt->packetKind() == NocPacketKind::SpikeTileKey) {
            noc_lat_spikekey_cnt_ += 1;
            noc_lat_spikekey_sum_ += lat;
            noc_lat_spikekey_max_ = std::max<uint64_t>(noc_lat_spikekey_max_, lat);
            if (bin < noc_lat_spikekey_hist_.size()) noc_lat_spikekey_hist_[static_cast<size_t>(bin)] += 1;
        }
    }
    {
        uint32_t step_seq = pkt->step_seq;
        if (step_seq == 0 && global_step_active_seq_ != 0) step_seq = global_step_active_seq_;
        if (step_seq != 0 &&
            (pkt->packetKind() == NocPacketKind::Spike ||
             pkt->packetKind() == NocPacketKind::SpikeKey ||
             pkt->packetKind() == NocPacketKind::SpikeTileKey)) {
            const bool is_local = (pkt->src_node == static_cast<uint32_t>(node_id_));
            bool before_begin_gather = true;
            auto stage_it = stage_marks_.find(step_seq);
            if (stage_it != stage_marks_.end() && stage_it->second.bg != 0) {
                before_begin_gather = false;
            }
            recordStepRxPacket(step_seq, pkt->packetKind(), is_local, before_begin_gather);
        }
    }

    if (pkt->packetKind() == NocPacketKind::Spike) {
        // Phase8 (strict): 平台层不再对 Spike packet 做任何 SpikeEvent 语义处理。
        // Spike 的编解码/处理必须由 core/workload 通过 deliverPacket() 完成；
        // 若 core 不接管，则直接 fail-fast，避免边界回退造成“看似能跑但语义漂移/非确定性”。
        if (endpoint_id < 0 || endpoint_id >= num_cores_) {
            output_->fatal(CALL_INFO, -1,
                           "Phase8(strict): invalid endpoint_id=%d for Spike packet (kind=%u) on node=%d\n",
                           endpoint_id, static_cast<unsigned>(pkt->kind), node_id_);
        }
        if (!cores_[endpoint_id]) {
            output_->fatal(CALL_INFO, -1,
                           "Phase8(strict): endpoint(core)=%d not configured for Spike packet (kind=%u) on node=%d\n",
                           endpoint_id, static_cast<unsigned>(pkt->kind), node_id_);
        }
    } else {
        if (endpoint_id < 0 || endpoint_id >= num_cores_) {
            PE_LOG(2, "⚠️ 无效 endpoint_id=%d，丢弃 packet(kind=%u)\n",
                   endpoint_id, static_cast<unsigned>(pkt->kind));
            delete pkt;
            return;
        }
        if (!cores_[endpoint_id]) {
            PE_LOG(2, "⚠️ endpoint(core)=%d 未配置，丢弃 packet(kind=%u)\n",
                   endpoint_id, static_cast<unsigned>(pkt->kind));
            delete pkt;
            return;
        }
    }

    PeSharedCoreFabric::IngressDecision pulse_decision =
        PeSharedCoreFabric::IngressDecision::ForwardToCore;
    bool pulse_account_delivery = false;
    if (pulse_fabric_) {
        PeSharedCoreFabric::IngressObservation pulse_obs{};
        pulse_obs.kind = pulsePacketKindFromNoc_(pkt->packetKind());
        pulse_obs.endpoint_id = endpoint_id;
        pulse_obs.bytes = static_cast<uint32_t>(pkt->payload.size());
        pulse_obs.step_seq = pkt->step_seq;
        const PulseDescriptorSurrogate_ pulse_descriptor =
            buildPulseDescriptorSurrogate_(*pkt, global_layout_);
        pulse_obs.descriptor_surrogate_valid = pulse_descriptor.valid;
        pulse_obs.descriptor_post_block_id = pulse_descriptor.post_block_id;
        pulse_obs.descriptor_weight_region_id = pulse_descriptor.weight_region_id;
        pulse_obs.descriptor_retire_domain_id = pulse_descriptor.retire_domain_id;
        pulse_obs.descriptor_region_safe = pulse_descriptor.region_safe;
        pulse_decision = pulse_fabric_->observeIngress(pulse_obs);
        pulse_account_delivery = true;
        if (pulse_fabric_->config().harbor_enable &&
            pulseActualIngressEligible_(pkt->packetKind())) {
            uint32_t harbor_step_seq = pkt->step_seq;
            if (harbor_step_seq == 0 && global_step_active_seq_ != 0) {
                harbor_step_seq = global_step_active_seq_;
            }
            bool gather_open = (harbor_step_seq != 0);
            if (gather_open) {
                auto stage_it = stage_marks_.find(harbor_step_seq);
                if (stage_it != stage_marks_.end() && stage_it->second.ga != 0) {
                    gather_open = false;
                }
            }
            if (gather_open) {
                pulse_obs.step_seq = harbor_step_seq;
                pulse_fabric_->observeGatherHarbor(pulse_obs);
            }
        }
    }

    if (pulseActualIngressEnabled_() &&
        pulse_decision == PeSharedCoreFabric::IngressDecision::ForwardToCore &&
        pulseActualIngressEligible_(pkt->packetKind())) {
        const uint64_t token = pulse_next_dispatch_token_++;
        if (pulse_next_dispatch_token_ == 0) pulse_next_dispatch_token_ = 1;
        if (pulse_fabric_->enqueueDispatchToken(token, endpoint_id)) {
            pulse_fabric_->observeSharedIngressBuffered();
            pulse_ingress_buffered_packets_.emplace(
                token,
                PulseIngressBufferedPacket{token, endpoint_id, pkt});
            return;
        }
    }

    if (pulse_account_delivery && pulse_fabric_) {
        pulse_fabric_->observeDirectDeliver();
    }
    deliverPacketDirectToCore_(endpoint_id, pkt, pulse_account_delivery);
}

void MultiCorePE::resetAllCoreMembranes() {
    for (auto* core : cores_) {
        if (!core) continue;
        // Legacy-only hook: resetMembraneState is not part of CoreShellAPI.
        // It is used only by StepActivationSubsystem's optional reset_mem_each_step behavior.
        if (auto* snn = dynamic_cast<SnnCoreAPI*>(core)) {
            snn->resetMembraneState(v_rest_);
        }
    }
}


void MultiCorePE::initializeDirectionLinks() {
    
    // 配置方向链路，仅在实际连接时创建处理器
    north_link_ = configureLink("north", 
        new Event::Handler2<MultiCorePE,&MultiCorePE::handleNorthLinkEvent>(this));
    south_link_ = configureLink("south", 
        new Event::Handler2<MultiCorePE,&MultiCorePE::handleSouthLinkEvent>(this));
    east_link_ = configureLink("east", 
        new Event::Handler2<MultiCorePE,&MultiCorePE::handleEastLinkEvent>(this));
    west_link_ = configureLink("west", 
        new Event::Handler2<MultiCorePE,&MultiCorePE::handleWestLinkEvent>(this));
    // 重要：当 network_interface 子组件使用 SHARE_PORTS 时，它会占用/配置父组件的 "network" 端口。
    // 若父组件在此处再次 configureLink("network")，会造成端口重复绑定/回调歧义（同一端口被多处注册 handler）。
    // 因此：当已装配 external_nic_ 时，父组件不再直接配置 "network" 方向端口，避免连接冲突。
    if (!external_nic_) {
        network_link_ = configureLink("network",
            new Event::Handler2<MultiCorePE,&MultiCorePE::handleNetworkLinkEvent>(this));
    } else {
        network_link_ = nullptr;
    }
    
    // 统计活跃的方向链路
    int active_links = 0;
    if (north_link_) active_links++;
    if (south_link_) active_links++;
    if (east_link_) active_links++;
    if (west_link_) active_links++;
    if (network_link_) active_links++;
    
}

void MultiCorePE::initializeNetworkInterface() {
    
    // 尝试加载用户配置的网络接口
    // 关键修复：使用SHARE_PORTS允许网络接口暴露端口给hr_router
    external_nic_ = loadUserSubComponent<SnnInterface>(
        "network_interface", ComponentInfo::SHARE_PORTS);
    
    if (external_nic_) {
        
        // 配置网络接口的节点ID
        external_nic_->setNodeId(node_id_);
        
        // 设置通用接收回调：NoC packet 与控制面事件在此处分流
        external_nic_->setReceiveHandler([this](SST::Event* ev) {
            if (!ev) return;
            // Phase5‑5.4：batch unpack/NoC 输入收敛到 NocSubsystem；MultiCorePE 仅做事件分流与装配。
            if (dynamic_cast<NocPacketEvent*>(ev) || dynamic_cast<NocPacketBatchEvent*>(ev)) {
                this->noc_subsys_.onNicReceiveEvent(ev);
                return;
            }
            if (auto* gd = dynamic_cast<GatingDecisionEvent*>(ev)) {
                const uint32_t src_global =
                    static_cast<uint32_t>(gd->src_pe) * static_cast<uint32_t>(total_neurons_) + gd->src_row;
                std::vector<uint32_t> dpes = gd->dest_pes;
                for (auto* core : cores_) {
                    if (!core) continue;
                    auto* hooks = dynamic_cast<ICoreControlHooks*>(core);
                    if (!hooks) continue;
                    hooks->applyGatingDecision(src_global, dpes, current_cycle_, gd->ttl_cycles);
                }
                delete gd;
                return;
            }
            delete ev;
        });

        // 注意：SST框架会自动调用SubComponent的init()和setup()方法
        // 手动调用可能导致重复初始化和时序问题，因此移除
        
        //                 external_nic_->getNetworkStatus().c_str());
        
        // === 端口代理机制：将父组件的方向链路注入给SnnNetworkAdapter ===
        
        // 尝试将SnnInterface强制转换为SnnNetworkAdapter以访问链路注入接口
        auto* network_adapter = dynamic_cast<SnnNetworkAdapter*>(external_nic_);
        if (network_adapter) {
            // 注入各个方向的链路（如果存在）
            if (north_link_) {
                // network_adapter->injectDirectionLink("north", north_link_);
            }
            if (south_link_) {
                // network_adapter->injectDirectionLink("south", south_link_);
            }
            if (east_link_) {
                // network_adapter->injectDirectionLink("east", east_link_);
            }
            if (west_link_) {
                // network_adapter->injectDirectionLink("west", west_link_);
            }
            if (network_link_) {
                // network_adapter->injectDirectionLink("network", network_link_);
            }
            
        } else {
            // 非 SnnNetworkAdapter 场景（如 SnnNIC）：无需端口注入，外部NIC自带 network 端口
            if (external_nic_) {
            }
        }
    } else {
    }
}

// === 网络端口事件处理器实现 ===

void MultiCorePE::handleNorthLinkEvent(SST::Event* event) {
    PE_LOG(3, "📡 收到北向链路事件\n");
    if (!external_nic_) {
        PE_LOG(2, "⚠️ 网络接口未配置，无法处理north方向事件\n");
        delete event;
        return;
    }
    noc_subsys_.onDirectionalLinkEvent(event, "north");
}

void MultiCorePE::handleSouthLinkEvent(SST::Event* event) {
    PE_LOG(3, "📡 收到南向链路事件\n");
    if (!external_nic_) {
        PE_LOG(2, "⚠️ 网络接口未配置，无法处理south方向事件\n");
        delete event;
        return;
    }
    noc_subsys_.onDirectionalLinkEvent(event, "south");
}

void MultiCorePE::handleEastLinkEvent(SST::Event* event) {
    PE_LOG(3, "📡 收到东向链路事件\n");
    if (!external_nic_) {
        PE_LOG(2, "⚠️ 网络接口未配置，无法处理east方向事件\n");
        delete event;
        return;
    }
    noc_subsys_.onDirectionalLinkEvent(event, "east");
}

void MultiCorePE::handleWestLinkEvent(SST::Event* event) {
    PE_LOG(3, "📡 收到西向链路事件\n");
    if (!external_nic_) {
        PE_LOG(2, "⚠️ 网络接口未配置，无法处理west方向事件\n");
        delete event;
        return;
    }
    noc_subsys_.onDirectionalLinkEvent(event, "west");
}

void MultiCorePE::handleNetworkLinkEvent(SST::Event* event) {
    PE_LOG(3, "📡 收到通用网络链路事件\n");
    if (!external_nic_) {
        PE_LOG(2, "⚠️ 网络接口未配置，无法处理network方向事件\n");
        delete event;
        return;
    }
    noc_subsys_.onDirectionalLinkEvent(event, "network");
}
