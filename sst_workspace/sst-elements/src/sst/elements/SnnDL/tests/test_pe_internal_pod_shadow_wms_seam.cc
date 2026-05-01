#include <cassert>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

#define private public
#include "services/synapse/weights/WeightMemorySubsystem.h"
#undef private

#include <sst/core/output.h>

#include "services/synapse/weights/PulseMetadataFrontierObserveRegistry.h"
#include "services/synapse/weights/SnnBcsrWeightManager.h"
#include "services/local_storage/PeLocalServiceObjectTable.h"
#include "services/local_storage/PodMetadataObjectPlane.h"
#include "services/local_storage/PodOwnerServiceTable.h"
#include "services/pe_fabric/PeSharedCoreFabric.h"

using SST::SnnDL::PeLocalServiceObjectTable;
using SST::SnnDL::PeSharedCoreFabric;
using SST::SnnDL::PodMetadataObjectPlane;
using SST::SnnDL::PodOwnerServiceTable;
using SST::SnnDL::PulseMetadataFrontierObserveRegistry;
using SST::SnnDL::WeightMemorySubsystem;

namespace SST {

Output::Output(const std::string&, uint32_t, uint32_t, output_location_t, const std::string&) {}
Output::Output() {}
Output::~Output() {}
uint32_t Output::getVerboseLevel() const { return 0u; }
void Output::outputprintf(uint32_t,
                          const std::string&,
                          const std::string&,
                          const char*,
                          va_list) const {}
void Output::outputprintf(const char*, va_list) const {}
void Output::fatal(uint32_t,
                   const char*,
                   const char*,
                   int,
                   const char*,
                   ...) const {
    std::abort();
}

} // namespace SST

namespace {

class FakeMemoryAccess final : public SST::SnnDL::IMemoryAccess {
public:
    RequestId read(uint64_t addr, size_t bytes, ReadCallback cb) override {
        ++read_count;
        last_addr = addr;
        last_bytes = bytes;
        callbacks.push_back(std::move(cb));
        return static_cast<RequestId>(read_count);
    }

    RequestId write(uint64_t, const std::vector<uint8_t>&, WriteCallback) override {
        return 1u;
    }

    size_t pendingSize() const override { return 0u; }

    uint64_t read_count = 0u;
    uint64_t last_addr = 0u;
    size_t last_bytes = 0u;
    std::vector<ReadCallback> callbacks;
};

std::string writeMinimalRowMphfIndex(const std::string& tag,
                                     uint32_t rows_per_core,
                                     uint32_t hot_row) {
    char path_buf[256];
    std::snprintf(path_buf, sizeof(path_buf), "/tmp/%s.wms.gcss_idx2.bin", tag.c_str());
    const std::string path(path_buf);

    SST::SnnDL::GcssIndexRowMphf::HeaderV1 hdr{};
    std::memcpy(hdr.magic, "GCSSIDX2", 8);
    hdr.version = 1u;
    hdr.rows_per_core = rows_per_core;
    hdr.edges_total = 1u;
    hdr.bucket_target = 1u;
    hdr.pilot_bits = 8u;
    hdr.hash_kind = 1u;
    hdr.flags = 0u;

    std::vector<uint32_t> row_base(rows_per_core + 1u, 0u);
    std::vector<uint16_t> row_len(rows_per_core, 0u);
    std::vector<uint32_t> row_seed(rows_per_core, 0u);
    std::vector<uint16_t> row_bucket_count(rows_per_core, 0u);
    std::vector<uint32_t> row_bucket_off(rows_per_core + 1u, 0u);
    std::vector<uint8_t> pilots(1u, 0u);

    assert(hot_row < rows_per_core);
    row_len[hot_row] = 1u;
    row_bucket_count[hot_row] = 1u;
    row_base[hot_row + 1u] = 1u;
    for (size_t i = static_cast<size_t>(hot_row + 1u); i < row_base.size(); ++i) {
        row_base[i] = 1u;
    }
    for (size_t i = static_cast<size_t>(hot_row + 1u); i < row_bucket_off.size(); ++i) {
        row_bucket_off[i] = 1u;
    }

    std::ofstream fout(path, std::ios::out | std::ios::binary | std::ios::trunc);
    assert(fout.is_open());
    fout.write(reinterpret_cast<const char*>(&hdr), sizeof(hdr));
    fout.write(reinterpret_cast<const char*>(row_base.data()),
               static_cast<std::streamsize>(row_base.size() * sizeof(uint32_t)));
    fout.write(reinterpret_cast<const char*>(row_len.data()),
               static_cast<std::streamsize>(row_len.size() * sizeof(uint16_t)));
    fout.write(reinterpret_cast<const char*>(row_seed.data()),
               static_cast<std::streamsize>(row_seed.size() * sizeof(uint32_t)));
    fout.write(reinterpret_cast<const char*>(row_bucket_count.data()),
               static_cast<std::streamsize>(row_bucket_count.size() * sizeof(uint16_t)));
    fout.write(reinterpret_cast<const char*>(row_bucket_off.data()),
               static_cast<std::streamsize>(row_bucket_off.size() * sizeof(uint32_t)));
    fout.write(reinterpret_cast<const char*>(pilots.data()),
               static_cast<std::streamsize>(pilots.size() * sizeof(uint8_t)));
    fout.close();
    return path;
}

void configureShadowWms(WeightMemorySubsystem& wms,
                        uint32_t node_id,
                        uint32_t core_id,
                        uint32_t pod_id,
                        uint32_t pod_count,
                        PodMetadataObjectPlane* metadata_plane,
                        PodOwnerServiceTable* owner_table,
                        PeSharedCoreFabric* fabric) {
    wms.orch_ = WeightMemorySubsystem::OrchestratorConfig{};
    wms.orch_.node_id = node_id;
    wms.orch_.core_id = core_id;
    wms.orch_.pulse_agenda_enable = true;
    wms.orch_.pulse_metadata_frontier_observe_enable = true;
    wms.orch_.pulse_metadata_frontier_top_items = 4u;
    wms.orch_.pulse_metadata_frontier_band_slots = 8u;
    wms.orch_.pe_internal_cpe_enable = true;
    wms.orch_.pe_internal_pod_enable = true;
    wms.orch_.pe_internal_pod_metadata_enable = true;
    wms.orch_.pe_internal_pod_owner_enable = true;
    wms.orch_.pe_internal_pod_id = pod_id;
    wms.orch_.pe_internal_pod_count = pod_count;
    wms.orch_.pe_internal_pod_size = 2u;
    wms.bindPodMetadataObjectPlane(metadata_plane);
    wms.bindPodOwnerServiceTable(owner_table);
    wms.bindPeSharedCoreFabric(fabric);
}

void configureIdx2ShadowWms(WeightMemorySubsystem& wms,
                            uint32_t node_id,
                            uint32_t core_id,
                            uint32_t pod_id,
                            uint32_t pod_count,
                            const std::string& index_path,
                            FakeMemoryAccess* mem,
                            PodMetadataObjectPlane* metadata_plane,
                            PodOwnerServiceTable* owner_table,
                            PeSharedCoreFabric* fabric) {
    configureShadowWms(wms, node_id, core_id, pod_id, pod_count, metadata_plane, owner_table, fabric);
    wms.orch_.synapse_weight_mode = "gcss_idx2_rowmphf";
    wms.orch_.experimental_idx2_ingress_prefetch_enable = true;
    wms.orch_.experimental_idx2_ingress_prefetch_cache_entries = 8u;
    wms.orch_.experimental_idx2_ingress_prefetch_gather_only = false;
    wms.orch_.num_neurons = 64u;
    wms.orch_.base_addr = 0x4000u;
    wms.orch_.line_size_bytes = 64u;
    wms.bindMemory(mem);

    std::string err;
    const bool ok = wms.gcss_idx2_index_.loadFromFile(index_path, &err);
    assert(ok);
    wms.gcss_idx2_index_loaded_ = true;
    wms.gcss_idx2_index_load_failed_ = false;
    wms.gcss_idx2_index_path_ = index_path;
}

void configureRowidxShadowWms(WeightMemorySubsystem& wms,
                              uint32_t node_id,
                              uint32_t core_id,
                              uint32_t pod_id,
                              uint32_t pod_count,
                              SST::SnnDL::BcsrWeightManager* bcsr_mgr,
                              PodMetadataObjectPlane* metadata_plane,
                              PodOwnerServiceTable* owner_table,
                              PeSharedCoreFabric* fabric) {
    configureShadowWms(wms, node_id, core_id, pod_id, pod_count, metadata_plane, owner_table, fabric);
    wms.orch_.use_bcsr = true;
    wms.orch_.bcsr_mgr = bcsr_mgr;
    wms.orch_.num_neurons = 64u;
    wms.orch_.experimental_noc_rowidx_prefetch_enable = true;
    wms.orch_.experimental_noc_rowidx_prefetch_gather_only = false;
    wms.orch_.experimental_noc_rowidx_hot_touch_min = 1u;
}

void configureDetachedRowidxShadowWms(WeightMemorySubsystem& wms,
                                      uint32_t node_id,
                                      uint32_t core_id,
                                      uint32_t pod_id,
                                      uint32_t pod_count,
                                      SST::SnnDL::BcsrWeightManager* bcsr_mgr,
                                      PodMetadataObjectPlane* metadata_plane,
                                      PodOwnerServiceTable* owner_table,
                                      PeSharedCoreFabric* fabric) {
    configureRowidxShadowWms(
        wms, node_id, core_id, pod_id, pod_count, bcsr_mgr, metadata_plane, owner_table, fabric);
    wms.orch_.experimental_noc_rowidx_prefetch_detached_enable = true;
}

void configureDetachedCarryRowidxShadowWms(WeightMemorySubsystem& wms,
                                           uint32_t node_id,
                                           uint32_t core_id,
                                           uint32_t pod_id,
                                           uint32_t pod_count,
                                           SST::SnnDL::BcsrWeightManager* bcsr_mgr,
                                           PodMetadataObjectPlane* metadata_plane,
                                           PodOwnerServiceTable* owner_table,
                                           PeSharedCoreFabric* fabric) {
    configureDetachedRowidxShadowWms(
        wms, node_id, core_id, pod_id, pod_count, bcsr_mgr, metadata_plane, owner_table, fabric);
    wms.orch_.experimental_noc_rowidx_prefetch_gather_only = true;
    wms.orch_.experimental_noc_rowidx_prefetch_carry_to_apply_enable = true;
}

WeightMemorySubsystem::GcssVlfEdgeIssueEntry makeFrontierEdge(uint32_t pre_global,
                                                              uint32_t pre_base,
                                                              uint32_t pre_len,
                                                              uint64_t addr) {
    WeightMemorySubsystem::GcssVlfEdgeIssueEntry edge{};
    edge.pre_global = pre_global;
    edge.pre_base = pre_base;
    edge.pre_len = pre_len;
    edge.addr = addr;
    return edge;
}

void configureHotRowIndexManager(SST::SnnDL::BcsrWeightManager& bcsr_mgr,
                                 uint32_t hot_block_row) {
    bcsr_mgr.configure(
        0x1000u,
        0x2000u,
        0x3000u,
        0x4000u,
        16u,
        16u,
        4u,
        4u,
        "flat",
        0u,
        0u,
        0u);
    auto& rowptr = bcsr_mgr.rowptrHost();
    rowptr.assign(5u, 0u);
    assert(hot_block_row + 1u < rowptr.size());
    rowptr[hot_block_row + 1u] = 1u;
    for (size_t idx = static_cast<size_t>(hot_block_row + 2u); idx < rowptr.size(); ++idx) {
        rowptr[idx] = 1u;
    }
    bcsr_mgr.setRowptrReady(true);
}

std::vector<uint8_t> makeSingleRowIndexBytes(uint32_t value) {
    std::vector<uint8_t> bytes(sizeof(uint32_t), 0u);
    std::memcpy(bytes.data(), &value, sizeof(uint32_t));
    return bytes;
}

void test_real_wms_shadow_direct_window_zero_guard_drops() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_cfg{};
    owner_cfg.enable = true;
    owner_cfg.num_pods = 1;
    owner_cfg.owner_entries_per_pod = 8;
    owner_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    WeightMemorySubsystem owner;
    configureShadowWms(owner, 31u, 0u, 0u, 1u, &metadata_plane, &owner_table, &fabric);
    owner.window_seq_ = 0u;

    owner.observePeInternalPodMetadataObject_(
        PodMetadataObjectPlane::MetadataKind::PreMphfBase, 16u);
    owner.observePeInternalPodMetadataObject_(
        PodMetadataObjectPlane::MetadataKind::PreMphfBand, 2u);

    const auto shadow = owner.peInternalPodStats();
    assert(shadow.guard_drop_total == 2u);
    assert(shadow.guard_window_zero_total == 2u);
    assert(shadow.attempted_total == 2u);
    assert(shadow.attempted_guard_total == 2u);
    assert(shadow.attempted_reject_total == 0u);
    assert(shadow.attempted_useful_total == 0u);
    assert(shadow.guard_base_total == 1u);
    assert(shadow.guard_band_total == 1u);
    assert(shadow.guard_other_total == 0u);
    assert(shadow.attempted_base_total == 1u);
    assert(shadow.attempted_band_total == 1u);
    assert(shadow.attempted_other_total == 0u);
    assert(shadow.frontier_export_total == 0u);
    assert(shadow.owner_lookup_total == 0u);
    assert(shadow.join_request_total == 0u);

    const auto metadata_stats = metadata_plane.snapshotStats();
    assert(metadata_stats.observe_total == 0u);

    const auto owner_stats = owner_table.snapshotStats();
    assert(owner_stats.lookup_total == 0u);

    const auto fabric_stats = fabric.snapshotStats();
    assert(fabric_stats.control_messages_enqueued_total == 0u);
}

void test_real_wms_frontier_owner_join_flow() {
    PulseMetadataFrontierObserveRegistry::resetForTests();

    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_cfg{};
    owner_cfg.enable = true;
    owner_cfg.num_pods = 1;
    owner_cfg.owner_entries_per_pod = 8;
    owner_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    WeightMemorySubsystem owner;
    WeightMemorySubsystem joiner;
    configureShadowWms(owner, 32u, 0u, 0u, 1u, &metadata_plane, &owner_table, &fabric);
    configureShadowWms(joiner, 32u, 1u, 0u, 1u, &metadata_plane, &owner_table, &fabric);
    owner.setPulseOsaMetadataTxnConfig(
        true,
        true,
        PeLocalServiceObjectTable::kMetadataKindMaskAll);
    joiner.setPulseOsaMetadataTxnConfig(
        true,
        true,
        PeLocalServiceObjectTable::kMetadataKindMaskAll);
    owner.window_seq_ = 7u;
    joiner.window_seq_ = 7u;

    std::vector<WeightMemorySubsystem::GcssVlfEdgeIssueEntry> ordered;
    ordered.push_back(makeFrontierEdge(77u, 16u, 64u, 0x1040u));

    owner.observePulseMetadataFrontier_(ordered);
    joiner.observePulseMetadataFrontier_(ordered);

    const auto owner_shadow = owner.peInternalPodStats();
    assert(owner_shadow.frontier_export_total == 2u);
    assert(owner_shadow.owner_lookup_total == 2u);
    assert(owner_shadow.owner_alloc_total == 2u);
    assert(owner_shadow.join_request_total == 0u);
    assert(owner_shadow.join_reject_total == 0u);
    assert(owner_shadow.useful_total == 0u);
    assert(owner_shadow.useful_join_grant_total == 0u);
    assert(owner_shadow.useful_duplicate_replay_elide_total == 0u);
    assert(owner_shadow.frontier_base_consumer_count_sum_total == 1u);
    assert(owner_shadow.frontier_band_consumer_count_sum_total == 1u);
    assert(owner_shadow.frontier_base_overlap_strength_sum_total == 0u);
    assert(owner_shadow.frontier_band_overlap_strength_sum_total == 0u);
    assert(owner_shadow.owner_first_issue_deferred_total == 0u);
    assert(owner_shadow.owner_first_private_issue_avoided_total == 0u);
    assert(owner_shadow.attempted_total == 0u);
    assert(owner_shadow.attempted_guard_total == 0u);
    assert(owner_shadow.attempted_reject_total == 0u);
    assert(owner_shadow.attempted_useful_total == 0u);
    assert(owner_shadow.attempted_base_total == 0u);
    assert(owner_shadow.attempted_band_total == 0u);
    assert(owner_shadow.attempted_other_total == 0u);
    assert(owner_shadow.guard_drop_total == 0u);

    const auto joiner_shadow = joiner.peInternalPodStats();
    assert(joiner_shadow.frontier_export_total == 2u);
    assert(joiner_shadow.owner_lookup_total == 2u);
    assert(joiner_shadow.owner_hit_total == 2u);
    assert(joiner_shadow.join_request_total == 2u);
    assert(joiner_shadow.join_grant_total == 2u);
    assert(joiner_shadow.join_reject_total == 0u);
    assert(joiner_shadow.useful_total == 2u);
    assert(joiner_shadow.useful_join_grant_total == 2u);
    assert(joiner_shadow.useful_duplicate_replay_elide_total == 0u);
    assert(joiner_shadow.frontier_base_consumer_count_sum_total == 2u);
    assert(joiner_shadow.frontier_band_consumer_count_sum_total == 2u);
    assert(joiner_shadow.frontier_base_overlap_strength_sum_total == 1u);
    assert(joiner_shadow.frontier_band_overlap_strength_sum_total == 1u);
    assert(joiner_shadow.owner_first_issue_deferred_total == 2u);
    assert(joiner_shadow.owner_first_private_issue_avoided_total == 2u);
    assert(joiner_shadow.attempted_total == 2u);
    assert(joiner_shadow.attempted_guard_total == 0u);
    assert(joiner_shadow.attempted_reject_total == 0u);
    assert(joiner_shadow.attempted_useful_total == 2u);
    assert(joiner_shadow.useful_base_total == 1u);
    assert(joiner_shadow.useful_band_total == 1u);
    assert(joiner_shadow.useful_other_total == 0u);
    assert(joiner_shadow.attempted_base_total == 1u);
    assert(joiner_shadow.attempted_band_total == 1u);
    assert(joiner_shadow.attempted_other_total == 0u);
    assert(joiner_shadow.guard_drop_total == 0u);

    const auto metadata_stats = metadata_plane.snapshotStats();
    assert(metadata_stats.observe_total == 4u);
    assert(metadata_stats.unique_object_total == 2u);
    assert(metadata_stats.overlap_hit_total == 2u);

    const auto owner_txn = owner.pulseOsaMetadataTxnStats();
    const auto joiner_txn = joiner.pulseOsaMetadataTxnStats();
    assert(owner_txn.export_total == 2u);
    assert(owner_txn.frontier_observed_total == 4u);
    assert(owner_txn.frontier_same_window_reobserve_total == 0u);
    assert(owner_txn.owner_launch_total == 0u);
    assert(owner_txn.join_live_total == 0u);
    assert(owner_txn.frontier_premphf_base_observed_total == 1u);
    assert(owner_txn.frontier_premphf_band_observed_total == 1u);
    assert(owner_txn.frontier_idx2row_observed_total == 1u);
    assert(owner_txn.frontier_rowindex_observed_total == 1u);
    assert(owner_txn.envelope_size_sum_total == 2u);
    assert(joiner_txn.export_total == 2u);
    assert(joiner_txn.frontier_observed_total == 4u);
    assert(joiner_txn.frontier_same_window_reobserve_total == 0u);
    assert(joiner_txn.owner_launch_total == 0u);
    assert(joiner_txn.join_live_total == 0u);
    assert(joiner_txn.frontier_premphf_base_observed_total == 1u);
    assert(joiner_txn.frontier_premphf_band_observed_total == 1u);
    assert(joiner_txn.frontier_idx2row_observed_total == 1u);
    assert(joiner_txn.frontier_rowindex_observed_total == 1u);
    assert(joiner_txn.envelope_size_sum_total == 2u);

    const auto owner_stats = owner_table.snapshotStats();
    assert(owner_stats.lookup_total == 4u);
    assert(owner_stats.owner_alloc_total == 2u);
    assert(owner_stats.owner_hit_total == 2u);
    assert(owner_stats.join_request_total == 2u);
    assert(owner_stats.join_grant_total == 2u);

    const auto owner_obs = owner.pulseAgendaObservabilityStats();
    const auto joiner_obs = joiner.pulseAgendaObservabilityStats();
    assert(owner_obs.frontier_windows_total == 0u);
    assert(owner_obs.frontier_lines_exported_total == 0u);
    assert(joiner_obs.frontier_windows_total == 0u);
    assert(joiner_obs.frontier_lines_exported_total == 0u);

    const auto fabric_stats = fabric.snapshotStats();
    assert(fabric_stats.control_messages_enqueued_total == 8u);
    assert(fabric_stats.control_frontier_export_total == 4u);
    assert(fabric_stats.control_owner_announce_total == 2u);
    assert(fabric_stats.control_join_request_total == 2u);
}

void test_real_wms_direct_duplicate_replay_counts_usefulness() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_cfg{};
    owner_cfg.enable = true;
    owner_cfg.num_pods = 1;
    owner_cfg.owner_entries_per_pod = 8;
    owner_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    WeightMemorySubsystem owner;
    configureShadowWms(owner, 34u, 0u, 0u, 1u, &metadata_plane, &owner_table, &fabric);
    owner.window_seq_ = 13u;

    owner.observePeInternalPodMetadataObject_(
        PodMetadataObjectPlane::MetadataKind::PreMphfBase, 16u);
    owner.observePeInternalPodMetadataObject_(
        PodMetadataObjectPlane::MetadataKind::PreMphfBase, 16u);

    const auto shadow = owner.peInternalPodStats();
    assert(shadow.owner_alloc_total == 1u);
    assert(shadow.duplicate_metadata_replay_elided_total == 1u);
    assert(shadow.duplicate_metadata_issue_elided_total == 1u);
    assert(shadow.useful_total == 1u);
    assert(shadow.useful_join_grant_total == 0u);
    assert(shadow.useful_duplicate_replay_elide_total == 1u);
    assert(shadow.attempted_total == 1u);
    assert(shadow.attempted_guard_total == 0u);
    assert(shadow.attempted_reject_total == 0u);
    assert(shadow.attempted_useful_total == 1u);
    assert(shadow.useful_base_total == 1u);
    assert(shadow.useful_band_total == 0u);
    assert(shadow.useful_other_total == 0u);
    assert(shadow.attempted_base_total == 1u);
    assert(shadow.attempted_band_total == 0u);
    assert(shadow.attempted_other_total == 0u);
    assert(shadow.guard_drop_total == 0u);
}

void test_real_wms_frontier_join_table_disabled_reject_split() {
    PulseMetadataFrontierObserveRegistry::resetForTests();

    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_cfg{};
    owner_cfg.enable = true;
    owner_cfg.num_pods = 1;
    owner_cfg.owner_entries_per_pod = 8;
    owner_cfg.join_entries_per_pod = 0;
    PodOwnerServiceTable owner_table(owner_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    WeightMemorySubsystem owner;
    WeightMemorySubsystem joiner;
    configureShadowWms(owner, 33u, 0u, 0u, 1u, &metadata_plane, &owner_table, &fabric);
    configureShadowWms(joiner, 33u, 1u, 0u, 1u, &metadata_plane, &owner_table, &fabric);
    owner.window_seq_ = 11u;
    joiner.window_seq_ = 11u;

    std::vector<WeightMemorySubsystem::GcssVlfEdgeIssueEntry> ordered;
    ordered.push_back(makeFrontierEdge(101u, 16u, 64u, 0x1080u));

    owner.observePulseMetadataFrontier_(ordered);
    joiner.observePulseMetadataFrontier_(ordered);

    const auto owner_shadow = owner.peInternalPodStats();
    assert(owner_shadow.owner_alloc_total == 2u);
    assert(owner_shadow.join_request_total == 0u);
    assert(owner_shadow.join_reject_total == 0u);
    assert(owner_shadow.guard_drop_total == 0u);

    const auto joiner_shadow = joiner.peInternalPodStats();
    assert(joiner_shadow.owner_hit_total == 2u);
    assert(joiner_shadow.join_request_total == 0u);
    assert(joiner_shadow.join_grant_total == 0u);
    assert(joiner_shadow.join_reject_total == 2u);
    assert(joiner_shadow.join_table_disabled_reject_total == 2u);
    assert(joiner_shadow.useful_total == 0u);
    assert(joiner_shadow.useful_join_grant_total == 0u);
    assert(joiner_shadow.useful_duplicate_replay_elide_total == 0u);
    assert(joiner_shadow.attempted_total == 2u);
    assert(joiner_shadow.attempted_guard_total == 0u);
    assert(joiner_shadow.attempted_reject_total == 2u);
    assert(joiner_shadow.attempted_useful_total == 0u);
    assert(joiner_shadow.reject_base_total == 1u);
    assert(joiner_shadow.reject_band_total == 1u);
    assert(joiner_shadow.reject_other_total == 0u);
    assert(joiner_shadow.attempted_base_total == 1u);
    assert(joiner_shadow.attempted_band_total == 1u);
    assert(joiner_shadow.attempted_other_total == 0u);
    assert(joiner_shadow.guard_drop_total == 0u);

    const auto fabric_stats = fabric.snapshotStats();
    assert(fabric_stats.control_messages_enqueued_total == 8u);
    assert(fabric_stats.control_frontier_export_total == 4u);
    assert(fabric_stats.control_owner_announce_total == 2u);
    assert(fabric_stats.control_join_request_total == 0u);
    assert(fabric_stats.control_join_reject_total == 2u);
}

void test_real_wms_idx2_touch_path_tracks_other_shape() {
    const std::string index_path = writeMinimalRowMphfIndex("pod_shadow_other_idx2", 64u, 3u);

    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_cfg{};
    owner_cfg.enable = true;
    owner_cfg.num_pods = 1;
    owner_cfg.owner_entries_per_pod = 8;
    owner_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_cfg);

    PeLocalServiceObjectTable::Config service_cfg{};
    service_cfg.enable = true;
    service_cfg.num_pods = 1;
    service_cfg.active_entries_per_pod = 8;
    service_cfg.released_entries_per_pod = 8;
    PeLocalServiceObjectTable service_table(service_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    FakeMemoryAccess owner_mem;
    FakeMemoryAccess joiner_mem;

    WeightMemorySubsystem owner;
    WeightMemorySubsystem joiner;
    configureIdx2ShadowWms(
        owner, 35u, 0u, 0u, 1u, index_path, &owner_mem, &metadata_plane, &owner_table, &fabric);
    configureIdx2ShadowWms(
        joiner, 35u, 1u, 0u, 1u, index_path, &joiner_mem, &metadata_plane, &owner_table, &fabric);
    owner.bindPeLocalServiceObjectTable(&service_table);
    joiner.bindPeLocalServiceObjectTable(&service_table);

    owner.beginGatherWindow(true, 64u);
    joiner.beginGatherWindow(true, 64u);
    owner.noteWindowTouch(3u, 19u, 64u);
    joiner.noteWindowTouch(3u, 19u, 64u);
    owner.beginApplyWindow(17u, false, nullptr, 0);
    joiner.beginApplyWindow(17u, false, nullptr, 0);
    owner.onClockTick(1u);
    joiner.onClockTick(1u);

    const auto owner_shadow = owner.peInternalPodStats();
    const auto joiner_shadow = joiner.peInternalPodStats();
    assert(owner_shadow.frontier_export_total == 0u);
    assert(owner_shadow.owner_lookup_total == 0u);
    assert(owner_shadow.owner_alloc_total == 0u);
    assert(joiner_shadow.frontier_export_total == 0u);
    assert(joiner_shadow.owner_lookup_total == 0u);
    assert(joiner_shadow.owner_hit_total == 0u);
    assert(joiner_shadow.join_request_total == 0u);

    const auto metadata_stats = metadata_plane.snapshotStats();
    assert(metadata_stats.observe_total == 0u);
    assert(metadata_stats.unique_object_total == 0u);
    assert(metadata_stats.overlap_hit_total == 0u);
    assert(metadata_stats.duplicate_consumer_total == 0u);

    const auto owner_stats = owner_table.snapshotStats();
    assert(owner_stats.lookup_total == 0u);
    assert(owner_stats.owner_alloc_total == 0u);
    assert(owner_stats.owner_hit_total == 0u);
    assert(owner_stats.join_request_total == 0u);
    assert(owner_stats.join_grant_total == 0u);
    assert(owner_stats.join_reject_total == 0u);

    const auto owner_align = owner.experimentalPeInternalPodPathAlignmentStats();
    const auto joiner_align = joiner.experimentalPeInternalPodPathAlignmentStats();
    assert(owner_align.idx2row.producer_touch_events_total == 0u);
    assert(owner_align.idx2row.producer_enqueued_total == 0u);
    assert(owner_align.idx2row.seam_owner_form_total == 0u);
    assert(joiner_align.idx2row.producer_touch_events_total == 0u);
    assert(joiner_align.idx2row.producer_enqueued_total == 0u);
    assert(joiner_align.idx2row.seam_joiner_hit_total == 0u);
    assert(joiner_align.idx2row.seam_joiner_useful_total == 0u);

    const auto fabric_stats = fabric.snapshotStats();
    assert(fabric_stats.control_messages_enqueued_total == 0u);
    assert(fabric_stats.control_frontier_export_total == 0u);
    assert(fabric_stats.control_owner_announce_total == 0u);
    assert(fabric_stats.control_join_request_total == 0u);
    assert(fabric_stats.control_join_reject_total == 0u);

    const auto service_stats = service_table.snapshotStats();
    assert(service_stats.owner_form_total == 0u);
    assert(service_stats.join_live_total == 0u);
    assert(service_stats.join_ready_total == 0u);
    assert(service_stats.late_join_total == 0u);
    assert(service_stats.potential_private_service_elide_total == 0u);
}

void test_real_wms_rowidx_touch_path_tracks_rowindex_shape() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_cfg{};
    owner_cfg.enable = true;
    owner_cfg.num_pods = 1;
    owner_cfg.owner_entries_per_pod = 8;
    owner_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_cfg);

    PeLocalServiceObjectTable::Config service_cfg{};
    service_cfg.enable = true;
    service_cfg.num_pods = 1;
    service_cfg.active_entries_per_pod = 8;
    service_cfg.released_entries_per_pod = 8;
    PeLocalServiceObjectTable service_table(service_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    SST::SnnDL::BcsrWeightManager owner_bcsr_mgr;
    SST::SnnDL::BcsrWeightManager joiner_bcsr_mgr;
    configureHotRowIndexManager(owner_bcsr_mgr, 1u);
    configureHotRowIndexManager(joiner_bcsr_mgr, 1u);

    WeightMemorySubsystem owner;
    WeightMemorySubsystem joiner;
    configureRowidxShadowWms(
        owner, 36u, 0u, 0u, 1u, &owner_bcsr_mgr, &metadata_plane, &owner_table, &fabric);
    configureRowidxShadowWms(
        joiner, 36u, 1u, 0u, 1u, &joiner_bcsr_mgr, &metadata_plane, &owner_table, &fabric);
    owner.bindPeLocalServiceObjectTable(&service_table);
    joiner.bindPeLocalServiceObjectTable(&service_table);
    owner.window_seq_ = 19u;
    joiner.window_seq_ = 19u;

    owner.noteWindowTouch(19u, 23u, 64u);
    joiner.noteWindowTouch(19u, 23u, 64u);

    const auto owner_shadow = owner.peInternalPodStats();
    assert(owner_shadow.frontier_export_total == 1u);
    assert(owner_shadow.owner_lookup_total == 1u);
    assert(owner_shadow.owner_alloc_total == 1u);
    assert(owner_shadow.owner_hit_total == 0u);
    assert(owner_shadow.useful_total == 0u);
    assert(owner_shadow.useful_other_total == 0u);
    assert(owner_shadow.useful_idx2row_total == 0u);
    assert(owner_shadow.useful_rowindex_total == 0u);
    assert(owner_shadow.useful_rowdescriptor_total == 0u);
    assert(owner_shadow.attempted_other_total == 0u);
    assert(owner_shadow.attempted_idx2row_total == 0u);
    assert(owner_shadow.attempted_rowindex_total == 0u);
    assert(owner_shadow.attempted_rowdescriptor_total == 0u);

    const auto joiner_shadow = joiner.peInternalPodStats();
    assert(joiner_shadow.frontier_export_total == 1u);
    assert(joiner_shadow.owner_lookup_total == 1u);
    assert(joiner_shadow.owner_hit_total == 1u);
    assert(joiner_shadow.join_request_total == 1u);
    assert(joiner_shadow.join_grant_total == 1u);
    assert(joiner_shadow.join_reject_total == 0u);
    assert(joiner_shadow.useful_total == 1u);
    assert(joiner_shadow.useful_join_grant_total == 1u);
    assert(joiner_shadow.useful_other_total == 1u);
    assert(joiner_shadow.useful_idx2row_total == 0u);
    assert(joiner_shadow.useful_rowindex_total == 1u);
    assert(joiner_shadow.useful_rowdescriptor_total == 0u);
    assert(joiner_shadow.attempted_total == 1u);
    assert(joiner_shadow.attempted_useful_total == 1u);
    assert(joiner_shadow.attempted_other_total == 1u);
    assert(joiner_shadow.attempted_idx2row_total == 0u);
    assert(joiner_shadow.attempted_rowindex_total == 1u);
    assert(joiner_shadow.attempted_rowdescriptor_total == 0u);

    const auto metadata_stats = metadata_plane.snapshotStats();
    assert(metadata_stats.observe_total == 2u);
    assert(metadata_stats.unique_object_total == 1u);
    assert(metadata_stats.overlap_hit_total == 1u);
    assert(metadata_stats.duplicate_consumer_total == 0u);

    const auto owner_stats = owner_table.snapshotStats();
    assert(owner_stats.lookup_total == 2u);
    assert(owner_stats.owner_alloc_total == 1u);
    assert(owner_stats.owner_hit_total == 1u);
    assert(owner_stats.join_request_total == 1u);
    assert(owner_stats.join_grant_total == 1u);
    assert(owner_stats.join_reject_total == 0u);

    const auto owner_rowidx = owner.experimentalNocRowidxStats();
    const auto joiner_rowidx = joiner.experimentalNocRowidxStats();
    assert(owner_rowidx.touch_events_total == 1u);
    assert(joiner_rowidx.touch_events_total == 1u);
    assert(owner_rowidx.rows_touched_enqueued == 1u);
    assert(joiner_rowidx.rows_touched_enqueued == 1u);
    assert(owner.experimental_noc_rowidx_pending_rows_.size() == 1u);
    assert(joiner.experimental_noc_rowidx_pending_rows_.size() == 1u);

    const auto owner_align = owner.experimentalPeInternalPodPathAlignmentStats();
    const auto joiner_align = joiner.experimentalPeInternalPodPathAlignmentStats();
    assert(owner_align.idx2row.producer_touch_events_total == 0u);
    assert(owner_align.idx2row.producer_enqueued_total == 0u);
    assert(owner_align.idx2row.seam_owner_form_total == 0u);
    assert(owner_align.idx2row.seam_joiner_hit_total == 0u);
    assert(owner_align.idx2row.seam_joiner_useful_total == 0u);
    assert(owner_align.idx2row.seam_attempted_total == 0u);
    assert(owner_align.rowindex.producer_touch_events_total == 1u);
    assert(owner_align.rowindex.producer_enqueued_total == 1u);
    assert(owner_align.rowindex.seam_owner_form_total == 1u);
    assert(owner_align.rowindex.seam_joiner_hit_total == 0u);
    assert(owner_align.rowindex.seam_joiner_useful_total == 0u);
    assert(owner_align.rowindex.seam_owner_live_join_total == 0u);
    assert(owner_align.rowindex.seam_owner_ready_join_total == 0u);
    assert(owner_align.rowindex.seam_late_join_total == 0u);
    assert(owner_align.rowindex.seam_potential_private_service_elide_total == 0u);
    assert(owner_align.rowindex.seam_guard_total == 0u);
    assert(owner_align.rowindex.seam_reject_total == 0u);
    assert(owner_align.rowindex.seam_useful_total == 0u);
    assert(owner_align.rowindex.seam_attempted_total == 0u);
    assert(owner_align.rowdescriptor.producer_touch_events_total == 0u);
    assert(owner_align.rowdescriptor.producer_enqueued_total == 0u);
    assert(owner_align.rowdescriptor.seam_owner_form_total == 0u);
    assert(owner_align.rowdescriptor.seam_joiner_hit_total == 0u);
    assert(owner_align.rowdescriptor.seam_joiner_useful_total == 0u);
    assert(owner_align.rowdescriptor.seam_attempted_total == 0u);
    assert(joiner_align.idx2row.producer_touch_events_total == 0u);
    assert(joiner_align.idx2row.producer_enqueued_total == 0u);
    assert(joiner_align.idx2row.seam_owner_form_total == 0u);
    assert(joiner_align.idx2row.seam_joiner_hit_total == 0u);
    assert(joiner_align.idx2row.seam_joiner_useful_total == 0u);
    assert(joiner_align.idx2row.seam_attempted_total == 0u);
    assert(joiner_align.rowindex.producer_touch_events_total == 1u);
    assert(joiner_align.rowindex.producer_enqueued_total == 1u);
    assert(joiner_align.rowindex.seam_owner_form_total == 0u);
    assert(joiner_align.rowindex.seam_joiner_hit_total == 1u);
    assert(joiner_align.rowindex.seam_joiner_useful_total == 1u);
    assert(joiner_align.rowindex.seam_owner_live_join_total == 1u);
    assert(joiner_align.rowindex.seam_owner_ready_join_total == 0u);
    assert(joiner_align.rowindex.seam_late_join_total == 0u);
    assert(joiner_align.rowindex.seam_potential_private_service_elide_total == 1u);
    assert(joiner_align.rowindex.seam_guard_total == 0u);
    assert(joiner_align.rowindex.seam_reject_total == 0u);
    assert(joiner_align.rowindex.seam_useful_total == 1u);
    assert(joiner_align.rowindex.seam_attempted_total == 1u);
    assert(joiner_align.rowdescriptor.producer_touch_events_total == 0u);
    assert(joiner_align.rowdescriptor.producer_enqueued_total == 0u);
    assert(joiner_align.rowdescriptor.seam_owner_form_total == 0u);
    assert(joiner_align.rowdescriptor.seam_joiner_hit_total == 0u);
    assert(joiner_align.rowdescriptor.seam_joiner_useful_total == 0u);
    assert(joiner_align.rowdescriptor.seam_attempted_total == 0u);

    const auto fabric_stats = fabric.snapshotStats();
    assert(fabric_stats.control_messages_enqueued_total == 4u);
    assert(fabric_stats.control_frontier_export_total == 2u);
    assert(fabric_stats.control_owner_announce_total == 1u);
    assert(fabric_stats.control_join_request_total == 1u);
    assert(fabric_stats.control_join_reject_total == 0u);

    const auto service_stats = service_table.snapshotStats();
    assert(service_stats.owner_form_total == 1u);
    assert(service_stats.join_live_total == 1u);
    assert(service_stats.join_ready_total == 0u);
    assert(service_stats.late_join_total == 0u);
    assert(service_stats.potential_private_service_elide_total == 1u);
}

void test_real_wms_rowidx_prefetch_completion_marks_ready_and_releases_owner_entry() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_cfg{};
    owner_cfg.enable = true;
    owner_cfg.num_pods = 1;
    owner_cfg.owner_entries_per_pod = 8;
    owner_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_cfg);

    PeLocalServiceObjectTable::Config service_cfg{};
    service_cfg.enable = true;
    service_cfg.num_pods = 1;
    service_cfg.active_entries_per_pod = 8;
    service_cfg.released_entries_per_pod = 8;
    PeLocalServiceObjectTable service_table(service_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    SST::SnnDL::BcsrWeightManager owner_bcsr_mgr;
    SST::SnnDL::BcsrWeightManager joiner_bcsr_mgr;
    configureHotRowIndexManager(owner_bcsr_mgr, 1u);
    configureHotRowIndexManager(joiner_bcsr_mgr, 1u);

    FakeMemoryAccess owner_mem;

    WeightMemorySubsystem owner;
    WeightMemorySubsystem joiner;
    configureRowidxShadowWms(
        owner, 37u, 0u, 0u, 1u, &owner_bcsr_mgr, &metadata_plane, &owner_table, &fabric);
    configureRowidxShadowWms(
        joiner, 37u, 1u, 0u, 1u, &joiner_bcsr_mgr, &metadata_plane, &owner_table, &fabric);
    owner.bindMemory(&owner_mem);
    owner.bindPeLocalServiceObjectTable(&service_table);
    joiner.bindPeLocalServiceObjectTable(&service_table);
    owner.window_seq_ = 23u;
    joiner.window_seq_ = 23u;

    owner.noteWindowTouch(19u, 23u, 64u);
    joiner.noteWindowTouch(19u, 23u, 64u);

    owner.onClockTick(1u);
    assert(owner_mem.read_count == 1u);
    assert(owner_mem.callbacks.size() == 1u);

    const auto service_before = service_table.snapshotStats();
    assert(service_before.ready_transition_total == 0u);
    assert(service_before.released_total == 0u);

    owner_mem.callbacks.front()(1u, owner_mem.last_addr, makeSingleRowIndexBytes(0u));

    const auto service_after_ready = service_table.snapshotStats();
    assert(service_after_ready.ready_transition_total == 1u);
    assert(service_after_ready.ready_fanout_total == 1u);
    assert(service_after_ready.ready_fanout_consumers_sum == 2u);
    assert(service_after_ready.atlas_obj_ready_total == 1u);
    assert(service_after_ready.released_total == 0u);
    assert(service_after_ready.ready_release_total == 0u);
    const auto owner_rowidx_after_ready = owner.experimentalNocRowidxStats();
    assert(owner_rowidx_after_ready.prefetch_complete_inflight_miss_total == 0u);
    assert(owner_rowidx_after_ready.prefetch_complete_zero_waiters_total == 1u);
    assert(owner_rowidx_after_ready.prefetch_complete_waiters_total == 0u);
    assert(owner_rowidx_after_ready.ready_signal_rowindex_response_total == 1u);
    assert(owner_rowidx_after_ready.ready_transition_rowindex_response_total == 1u);
    assert(owner_rowidx_after_ready.ready_signal_prefetch_response_total == 1u);
    assert(owner_rowidx_after_ready.ready_transition_prefetch_response_total == 1u);
    assert(owner_rowidx_after_ready.ready_transition_apply_promote_cached_total == 0u);

    const auto fabric_after_ready = fabric.snapshotStats();
    assert(fabric_after_ready.control_ready_fanout_total == 1u);

    owner.endScatterWindow(23u);

    const auto service_after_release = service_table.snapshotStats();
    assert(service_after_release.released_total == 1u);
    assert(service_after_release.release_deferred_total == 0u);
    assert(service_after_release.ready_release_total == 0u);
    assert(service_after_release.atlas_obj_release_total == 1u);
    assert(service_after_release.atlas_obj_private_only_total == 0u);
    const auto owner_rowidx_after_release = owner.experimentalNocRowidxStats();
    assert(owner_rowidx_after_release.close_attempt_total == 1u);
    assert(owner_rowidx_after_release.close_attempt_active_owner_total == 1u);
    assert(owner_rowidx_after_release.close_attempt_already_pending_total == 0u);
    assert(owner_rowidx_after_release.close_attempt_not_active_total == 0u);
    assert(owner_rowidx_after_release.close_attempt_not_owner_total == 0u);

    joiner.endScatterWindow(23u);
    const auto joiner_rowidx_after_release = joiner.experimentalNocRowidxStats();
    assert(joiner_rowidx_after_release.close_attempt_total == 0u);
    assert(joiner_rowidx_after_release.close_attempt_active_owner_total == 0u);
    assert(joiner_rowidx_after_release.close_attempt_already_pending_total == 0u);
    assert(joiner_rowidx_after_release.close_attempt_not_active_total == 0u);
    assert(joiner_rowidx_after_release.close_attempt_not_owner_total == 0u);
}

void test_real_wms_rowidx_detached_prefetch_completion_records_noninflight_ready_path() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_cfg{};
    owner_cfg.enable = true;
    owner_cfg.num_pods = 1;
    owner_cfg.owner_entries_per_pod = 8;
    owner_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_cfg);

    PeLocalServiceObjectTable::Config service_cfg{};
    service_cfg.enable = true;
    service_cfg.num_pods = 1;
    service_cfg.active_entries_per_pod = 8;
    service_cfg.released_entries_per_pod = 8;
    PeLocalServiceObjectTable service_table(service_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 1;
    PeSharedCoreFabric fabric(fabric_cfg);

    SST::SnnDL::BcsrWeightManager bcsr_mgr;
    configureHotRowIndexManager(bcsr_mgr, 1u);

    FakeMemoryAccess mem;
    WeightMemorySubsystem owner;
    configureDetachedRowidxShadowWms(
        owner, 55u, 0u, 0u, 1u, &bcsr_mgr, &metadata_plane, &owner_table, &fabric);
    owner.bindMemory(&mem);
    owner.bindPeLocalServiceObjectTable(&service_table);
    owner.window_seq_ = 91u;

    owner.noteWindowTouch(19u, 91u, 64u);
    owner.onClockTick(1u);

    assert(mem.read_count == 1u);
    assert(mem.callbacks.size() == 1u);
    assert(owner.inflight_colidx_.empty());

    mem.callbacks.front()(1u, mem.last_addr, makeSingleRowIndexBytes(0u));

    const auto rowidx_after_ready = owner.experimentalNocRowidxStats();
    assert(rowidx_after_ready.ready_signal_rowindex_response_total == 1u);
    assert(rowidx_after_ready.ready_transition_rowindex_response_total == 1u);
    assert(rowidx_after_ready.ready_signal_prefetch_response_total == 1u);
    assert(rowidx_after_ready.ready_transition_prefetch_response_total == 1u);
    assert(rowidx_after_ready.ready_signal_rowindex_response_inflight_waiters_total == 0u);
    assert(rowidx_after_ready.ready_signal_rowindex_response_inflight_zero_waiters_total == 0u);
    assert(rowidx_after_ready.ready_signal_rowindex_response_noninflight_prefetch_only_total == 1u);
    assert(rowidx_after_ready.ready_transition_rowindex_response_noninflight_prefetch_only_total == 1u);
    assert(rowidx_after_ready.ready_signal_prefetch_response_noninflight_prefetch_only_total == 1u);
    assert(rowidx_after_ready.ready_transition_prefetch_response_noninflight_prefetch_only_total == 1u);
}

void test_real_wms_rowidx_detached_prefetch_demand_joins_without_legacy_inflight() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_cfg{};
    owner_cfg.enable = true;
    owner_cfg.num_pods = 1;
    owner_cfg.owner_entries_per_pod = 8;
    owner_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_cfg);

    PeLocalServiceObjectTable::Config service_cfg{};
    service_cfg.enable = true;
    service_cfg.num_pods = 1;
    service_cfg.active_entries_per_pod = 8;
    service_cfg.released_entries_per_pod = 8;
    PeLocalServiceObjectTable service_table(service_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 1;
    PeSharedCoreFabric fabric(fabric_cfg);

    SST::SnnDL::BcsrWeightManager bcsr_mgr;
    configureHotRowIndexManager(bcsr_mgr, 1u);

    FakeMemoryAccess mem;
    WeightMemorySubsystem owner;
    configureDetachedRowidxShadowWms(
        owner, 56u, 0u, 0u, 1u, &bcsr_mgr, &metadata_plane, &owner_table, &fabric);
    owner.bindMemory(&mem);
    owner.bindPeLocalServiceObjectTable(&service_table);
    owner.window_seq_ = 93u;

    owner.noteWindowTouch(19u, 93u, 64u);
    owner.onClockTick(1u);

    assert(mem.read_count == 1u);
    assert(mem.callbacks.size() == 1u);
    assert(owner.inflight_colidx_.empty());

    bool cb_called = false;
    float cb_weight = -1.0f;
    owner.requestBCSR_(0u, 16u, [&](float w) {
        cb_called = true;
        cb_weight = w;
    });

    assert(!cb_called);
    assert(owner.inflight_colidx_.empty());
    assert(owner.experimental_noc_rowidx_detached_inflight_rows_.count(1u) == 1u);

    mem.callbacks.front()(1u, mem.last_addr, makeSingleRowIndexBytes(0u));

    assert(cb_called);
    assert(cb_weight == 0.0f);

    const auto rowidx_after_ready = owner.experimentalNocRowidxStats();
    assert(rowidx_after_ready.ready_signal_rowindex_response_noninflight_prefetch_only_total == 0u);
    assert(rowidx_after_ready.detached_demand_join_total == 1u);
    assert(rowidx_after_ready.detached_demand_waiters_resolved_total == 1u);
    assert(rowidx_after_ready.detached_demand_fallback_zero_total == 1u);
}

void test_real_wms_rowidx_detached_carry_to_apply_issues_under_apply_window_seq() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_cfg{};
    owner_cfg.enable = true;
    owner_cfg.num_pods = 1;
    owner_cfg.owner_entries_per_pod = 8;
    owner_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_cfg);

    PeLocalServiceObjectTable::Config service_cfg{};
    service_cfg.enable = true;
    service_cfg.num_pods = 1;
    service_cfg.active_entries_per_pod = 8;
    service_cfg.released_entries_per_pod = 8;
    PeLocalServiceObjectTable service_table(service_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 1;
    PeSharedCoreFabric fabric(fabric_cfg);

    SST::SnnDL::BcsrWeightManager bcsr_mgr;
    configureHotRowIndexManager(bcsr_mgr, 1u);

    FakeMemoryAccess mem;
    WeightMemorySubsystem owner;
    configureDetachedCarryRowidxShadowWms(
        owner, 57u, 0u, 0u, 1u, &bcsr_mgr, &metadata_plane, &owner_table, &fabric);
    owner.bindMemory(&mem);
    owner.bindPeLocalServiceObjectTable(&service_table);

    owner.noteWindowTouch(19u, 93u, 64u);
    owner.onClockTick(1u);

    assert(mem.read_count == 0u);
    assert(mem.callbacks.empty());
    assert(owner.experimental_noc_rowidx_detached_inflight_rows_.empty());

    owner.beginApplyWindow(94u, false, nullptr, 0);
    owner.onClockTick(2u);

    assert(mem.read_count == 1u);
    assert(mem.callbacks.size() == 1u);
    assert(owner.experimental_noc_rowidx_detached_inflight_rows_.count(1u) == 1u);
    assert(owner.experimental_noc_rowidx_detached_inflight_rows_.at(1u) == 94u);

    bool cb_called = false;
    float cb_weight = -1.0f;
    owner.requestBCSR_(0u, 16u, [&](float w) {
        cb_called = true;
        cb_weight = w;
    });

    assert(!cb_called);
    mem.callbacks.front()(1u, mem.last_addr, makeSingleRowIndexBytes(0u));

    assert(cb_called);
    assert(cb_weight == 0.0f);

    const auto rowidx_after_ready = owner.experimentalNocRowidxStats();
    assert(rowidx_after_ready.detached_demand_join_total == 1u);
    assert(rowidx_after_ready.detached_demand_waiters_resolved_total == 1u);
    assert(rowidx_after_ready.detached_demand_ready_signal_total == 1u);
    assert(rowidx_after_ready.detached_demand_ready_transition_total == 1u);
}

void test_real_wms_rowidx_endscatter_before_ready_keeps_owner_active_until_late_completion() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_cfg{};
    owner_cfg.enable = true;
    owner_cfg.num_pods = 1;
    owner_cfg.owner_entries_per_pod = 8;
    owner_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_cfg);

    PeLocalServiceObjectTable::Config service_cfg{};
    service_cfg.enable = true;
    service_cfg.num_pods = 1;
    service_cfg.active_entries_per_pod = 8;
    service_cfg.released_entries_per_pod = 8;
    service_cfg.ready_lease_enable = true;
    service_cfg.ready_lease_ttl = 64u;
    service_cfg.ready_lease_kind_mask = PeLocalServiceObjectTable::kMetadataKindMaskRowIndex;
    PeLocalServiceObjectTable service_table(service_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    SST::SnnDL::BcsrWeightManager owner_bcsr_mgr;
    SST::SnnDL::BcsrWeightManager joiner_bcsr_mgr;
    configureHotRowIndexManager(owner_bcsr_mgr, 1u);
    configureHotRowIndexManager(joiner_bcsr_mgr, 1u);

    FakeMemoryAccess owner_mem;

    WeightMemorySubsystem owner;
    WeightMemorySubsystem joiner;
    configureRowidxShadowWms(
        owner, 41u, 0u, 0u, 1u, &owner_bcsr_mgr, &metadata_plane, &owner_table, &fabric);
    configureRowidxShadowWms(
        joiner, 41u, 1u, 0u, 1u, &joiner_bcsr_mgr, &metadata_plane, &owner_table, &fabric);
    owner.bindMemory(&owner_mem);
    owner.bindPeLocalServiceObjectTable(&service_table);
    joiner.bindPeLocalServiceObjectTable(&service_table);

    owner.noteWindowTouch(19u, 23u, 64u);
    joiner.noteWindowTouch(19u, 23u, 64u);

    owner.beginApplyWindow(61u, false, nullptr, 0);

    const auto service_after_owner_apply = service_table.snapshotStats();
    assert(service_after_owner_apply.owner_form_total == 1u);
    assert(service_after_owner_apply.join_live_total == 0u);
    assert(service_after_owner_apply.late_join_total == 0u);
    assert(service_after_owner_apply.ready_transition_total == 0u);
    assert(service_after_owner_apply.released_total == 0u);

    owner.onClockTick(1u);
    assert(owner_mem.read_count == 1u);
    assert(owner_mem.callbacks.size() == 1u);

    owner.endScatterWindow(61u);

    const auto service_after_owner_endscatter = service_table.snapshotStats();
    assert(service_after_owner_endscatter.released_total == 0u);
    assert(service_after_owner_endscatter.release_deferred_total == 1u);
    assert(service_after_owner_endscatter.release_pending_active_total == 1u);
    assert(service_after_owner_endscatter.ready_release_total == 0u);

    PeLocalServiceObjectTable::ProbeRequest probe{};
    probe.pod_id = 0u;
    probe.window_seq = 61u;
    probe.object_key = PodMetadataObjectPlane::composeObjectKey(
        PodMetadataObjectPlane::MetadataKind::RowIndex,
        1u);
    const auto probe_after_owner_endscatter = service_table.probe(probe);
    assert(probe_after_owner_endscatter.valid);
    assert(probe_after_owner_endscatter.active);
    assert(!probe_after_owner_endscatter.ready);
    assert(probe_after_owner_endscatter.release_pending);
    assert(probe_after_owner_endscatter.owner_core_id == 0u);
    const auto owner_rowidx_after_owner_endscatter = owner.experimentalNocRowidxStats();
    assert(owner_rowidx_after_owner_endscatter.close_attempt_total == 1u);
    assert(owner_rowidx_after_owner_endscatter.close_attempt_active_owner_total == 1u);
    assert(owner_rowidx_after_owner_endscatter.close_attempt_already_pending_total == 0u);
    assert(owner_rowidx_after_owner_endscatter.close_attempt_not_active_total == 0u);
    assert(owner_rowidx_after_owner_endscatter.close_attempt_not_owner_total == 0u);

    joiner.beginApplyWindow(61u, false, nullptr, 1);

    const auto service_after_join = service_table.snapshotStats();
    assert(service_after_join.join_live_total == 1u);
    assert(service_after_join.join_ready_total == 0u);
    assert(service_after_join.late_join_total == 0u);

    owner_mem.callbacks.front()(1u, owner_mem.last_addr, makeSingleRowIndexBytes(0u));

    const auto service_after_late_ready = service_table.snapshotStats();
    assert(service_after_late_ready.ready_transition_total == 1u);
    assert(service_after_late_ready.ready_fanout_total == 1u);
    assert(service_after_late_ready.released_total == 1u);
    assert(service_after_late_ready.release_deferred_total == 1u);
    assert(service_after_late_ready.ready_release_total == 1u);
    assert(service_after_late_ready.release_pending_active_total == 0u);
    assert(service_after_late_ready.ready_lease_hit_total == 0u);
    const auto owner_rowidx_after_late_ready = owner.experimentalNocRowidxStats();
    assert(owner_rowidx_after_late_ready.prefetch_complete_inflight_miss_total == 0u);
    assert(owner_rowidx_after_late_ready.prefetch_complete_zero_waiters_total == 0u);
    assert(owner_rowidx_after_late_ready.prefetch_complete_waiters_total == 1u);
    assert(owner_rowidx_after_late_ready.ready_signal_rowindex_response_total == 1u);
    assert(owner_rowidx_after_late_ready.ready_transition_rowindex_response_total == 1u);
    assert(owner_rowidx_after_late_ready.ready_signal_prefetch_response_total == 1u);
    assert(owner_rowidx_after_late_ready.ready_transition_prefetch_response_total == 1u);

    const auto owner_shadow_after_late_ready = owner.peInternalPodStats();
    assert(owner_shadow_after_late_ready.service_release_deferred_total == 1u);
    assert(owner_shadow_after_late_ready.service_release_deferred_rowindex_total == 1u);
    assert(owner_shadow_after_late_ready.service_ready_release_total == 1u);
    assert(owner_shadow_after_late_ready.service_ready_release_rowindex_total == 1u);

    const auto rowindex_lifecycle = owner.experimentalPeAtlasRowIndexLifecycleLedger();
    assert(rowindex_lifecycle.release_deferred_total == 1u);
    assert(rowindex_lifecycle.ready_release_total == 1u);

    const auto probe_after_late_ready = service_table.probe(probe);
    assert(probe_after_late_ready.valid);
    assert(!probe_after_late_ready.active);
    assert(probe_after_late_ready.released);
    assert(probe_after_late_ready.ready);
    assert(probe_after_late_ready.owner_core_id == 0u);
}

void test_real_wms_rowidx_joiner_late_ready_releases_owner_closed_entry() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_cfg{};
    owner_cfg.enable = true;
    owner_cfg.num_pods = 1;
    owner_cfg.owner_entries_per_pod = 8;
    owner_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_cfg);

    PeLocalServiceObjectTable::Config service_cfg{};
    service_cfg.enable = true;
    service_cfg.num_pods = 1;
    service_cfg.active_entries_per_pod = 8;
    service_cfg.released_entries_per_pod = 8;
    service_cfg.ready_lease_enable = true;
    service_cfg.ready_lease_ttl = 64u;
    service_cfg.ready_lease_kind_mask = PeLocalServiceObjectTable::kMetadataKindMaskRowIndex;
    PeLocalServiceObjectTable service_table(service_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    SST::SnnDL::BcsrWeightManager owner_bcsr_mgr;
    SST::SnnDL::BcsrWeightManager joiner_bcsr_mgr;
    configureHotRowIndexManager(owner_bcsr_mgr, 1u);
    configureHotRowIndexManager(joiner_bcsr_mgr, 1u);

    FakeMemoryAccess joiner_mem;

    WeightMemorySubsystem owner;
    WeightMemorySubsystem joiner;
    configureRowidxShadowWms(
        owner, 42u, 0u, 0u, 1u, &owner_bcsr_mgr, &metadata_plane, &owner_table, &fabric);
    configureRowidxShadowWms(
        joiner, 42u, 1u, 0u, 1u, &joiner_bcsr_mgr, &metadata_plane, &owner_table, &fabric);
    joiner.bindMemory(&joiner_mem);
    owner.bindPeLocalServiceObjectTable(&service_table);
    joiner.bindPeLocalServiceObjectTable(&service_table);

    owner.noteWindowTouch(19u, 23u, 64u);
    joiner.noteWindowTouch(19u, 23u, 64u);

    owner.beginApplyWindow(71u, false, nullptr, 0);
    owner.endScatterWindow(71u);

    joiner.beginApplyWindow(71u, false, nullptr, 1);

    const auto service_after_join = service_table.snapshotStats();
    assert(service_after_join.owner_form_total == 1u);
    assert(service_after_join.join_live_total == 1u);
    assert(service_after_join.late_join_total == 0u);
    assert(service_after_join.ready_transition_total == 0u);
    assert(service_after_join.released_total == 0u);
    assert(service_after_join.release_deferred_total == 1u);
    assert(service_after_join.release_pending_active_total == 1u);
    const auto owner_rowidx_after_join = owner.experimentalNocRowidxStats();
    assert(owner_rowidx_after_join.close_attempt_total == 1u);
    assert(owner_rowidx_after_join.close_attempt_active_owner_total == 1u);
    assert(owner_rowidx_after_join.close_attempt_already_pending_total == 0u);

    joiner.onClockTick(1u);
    assert(joiner_mem.read_count == 1u);
    assert(joiner_mem.callbacks.size() == 1u);

    joiner_mem.callbacks.front()(1u, joiner_mem.last_addr, makeSingleRowIndexBytes(0u));

    const auto service_after_joiner_ready = service_table.snapshotStats();
    assert(service_after_joiner_ready.ready_transition_total == 1u);
    assert(service_after_joiner_ready.ready_fanout_total == 1u);
    assert(service_after_joiner_ready.released_total == 1u);
    assert(service_after_joiner_ready.release_deferred_total == 1u);
    assert(service_after_joiner_ready.ready_release_total == 1u);
    assert(service_after_joiner_ready.release_pending_active_total == 0u);
    const auto joiner_rowidx_after_ready = joiner.experimentalNocRowidxStats();
    assert(joiner_rowidx_after_ready.prefetch_complete_inflight_miss_total == 0u);
    assert(joiner_rowidx_after_ready.prefetch_complete_zero_waiters_total == 0u);
    assert(joiner_rowidx_after_ready.prefetch_complete_waiters_total == 1u);
    assert(joiner_rowidx_after_ready.ready_signal_rowindex_response_total == 1u);
    assert(joiner_rowidx_after_ready.ready_transition_rowindex_response_total == 1u);
    assert(joiner_rowidx_after_ready.ready_signal_prefetch_response_total == 1u);
    assert(joiner_rowidx_after_ready.ready_transition_prefetch_response_total == 1u);

    const auto owner_shadow_after_ready = owner.peInternalPodStats();
    assert(owner_shadow_after_ready.service_release_deferred_total == 1u);
    assert(owner_shadow_after_ready.service_release_deferred_rowindex_total == 1u);
    assert(owner_shadow_after_ready.service_ready_release_total == 0u);
    assert(owner_shadow_after_ready.service_ready_release_rowindex_total == 0u);

    const auto joiner_shadow_after_ready = joiner.peInternalPodStats();
    assert(joiner_shadow_after_ready.service_release_deferred_total == 0u);
    assert(joiner_shadow_after_ready.service_release_deferred_rowindex_total == 0u);
    assert(joiner_shadow_after_ready.service_ready_release_total == 1u);
    assert(joiner_shadow_after_ready.service_ready_release_rowindex_total == 1u);

    const auto owner_rowindex_lifecycle =
        owner.experimentalPeAtlasRowIndexLifecycleLedger();
    assert(owner_rowindex_lifecycle.release_deferred_total == 1u);
    assert(owner_rowindex_lifecycle.ready_release_total == 0u);

    const auto joiner_rowindex_lifecycle =
        joiner.experimentalPeAtlasRowIndexLifecycleLedger();
    assert(joiner_rowindex_lifecycle.release_deferred_total == 0u);
    assert(joiner_rowindex_lifecycle.ready_release_total == 1u);

    PeLocalServiceObjectTable::ProbeRequest probe{};
    probe.pod_id = 0u;
    probe.window_seq = 71u;
    probe.object_key = PodMetadataObjectPlane::composeObjectKey(
        PodMetadataObjectPlane::MetadataKind::RowIndex,
        1u);
    const auto probe_after_joiner_ready = service_table.probe(probe);
    assert(probe_after_joiner_ready.valid);
    assert(!probe_after_joiner_ready.active);
    assert(probe_after_joiner_ready.released);
    assert(probe_after_joiner_ready.ready);
    assert(probe_after_joiner_ready.owner_core_id == 0u);
}

void test_real_wms_rowidx_joiner_endscatter_does_not_probe_owner_close_queue() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_cfg{};
    owner_cfg.enable = true;
    owner_cfg.num_pods = 1;
    owner_cfg.owner_entries_per_pod = 8;
    owner_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_cfg);

    PeLocalServiceObjectTable::Config service_cfg{};
    service_cfg.enable = true;
    service_cfg.num_pods = 1;
    service_cfg.active_entries_per_pod = 8;
    service_cfg.released_entries_per_pod = 8;
    PeLocalServiceObjectTable service_table(service_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    SST::SnnDL::BcsrWeightManager owner_bcsr_mgr;
    SST::SnnDL::BcsrWeightManager joiner_bcsr_mgr;
    configureHotRowIndexManager(owner_bcsr_mgr, 1u);
    configureHotRowIndexManager(joiner_bcsr_mgr, 1u);

    WeightMemorySubsystem owner;
    WeightMemorySubsystem joiner;
    configureRowidxShadowWms(
        owner, 52u, 0u, 0u, 1u, &owner_bcsr_mgr, &metadata_plane, &owner_table, &fabric);
    configureRowidxShadowWms(
        joiner, 52u, 1u, 0u, 1u, &joiner_bcsr_mgr, &metadata_plane, &owner_table, &fabric);
    owner.bindPeLocalServiceObjectTable(&service_table);
    joiner.bindPeLocalServiceObjectTable(&service_table);

    owner.noteWindowTouch(7u, 11u, 64u);
    joiner.noteWindowTouch(7u, 11u, 64u);

    owner.beginApplyWindow(91u, false, nullptr, 0);
    joiner.beginApplyWindow(91u, false, nullptr, 1);

    joiner.endScatterWindow(91u);

    const auto joiner_rowidx_after_endscatter = joiner.experimentalNocRowidxStats();
    assert(joiner_rowidx_after_endscatter.close_attempt_total == 0u);
    assert(joiner_rowidx_after_endscatter.close_attempt_active_owner_total == 0u);
    assert(joiner_rowidx_after_endscatter.close_attempt_already_pending_total == 0u);
    assert(joiner_rowidx_after_endscatter.close_attempt_not_active_total == 0u);
    assert(joiner_rowidx_after_endscatter.close_attempt_not_owner_total == 0u);

    const auto owner_rowidx_after_joiner_endscatter = owner.experimentalNocRowidxStats();
    assert(owner_rowidx_after_joiner_endscatter.close_attempt_total == 0u);
    assert(owner_rowidx_after_joiner_endscatter.close_attempt_active_owner_total == 0u);

    const auto service_after_joiner_endscatter = service_table.snapshotStats();
    assert(service_after_joiner_endscatter.owner_form_total == 1u);
    assert(service_after_joiner_endscatter.join_live_total == 1u);
    assert(service_after_joiner_endscatter.release_deferred_total == 0u);
    assert(service_after_joiner_endscatter.release_pending_active_total == 0u);
}

void test_real_wms_atlas_object_census_freezes_today_family_states() {
    using AtlasState = WeightMemorySubsystem::ExperimentalPeAtlasObjectFamilyState;

    PulseMetadataFrontierObserveRegistry::resetForTests();

    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_cfg{};
    owner_cfg.enable = true;
    owner_cfg.num_pods = 1;
    owner_cfg.owner_entries_per_pod = 8;
    owner_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    WeightMemorySubsystem frontier_owner;
    configureShadowWms(
        frontier_owner, 38u, 0u, 0u, 1u, &metadata_plane, &owner_table, &fabric);
    frontier_owner.setPulseOsaMetadataTxnConfig(
        true,
        true,
        PeLocalServiceObjectTable::kMetadataKindMaskAll);
    frontier_owner.window_seq_ = 29u;

    std::vector<WeightMemorySubsystem::GcssVlfEdgeIssueEntry> ordered;
    ordered.push_back(makeFrontierEdge(131u, 24u, 64u, 0x10c0u));
    frontier_owner.observePulseMetadataFrontier_(ordered);

    const auto frontier_census = frontier_owner.experimentalPeAtlasObjectCensus();
    assert(frontier_census.premphf_base.state == AtlasState::RegisteredButProxied);
    assert(frontier_census.premphf_base.frontier_events_total > 0u);
    assert(frontier_census.premphf_base.producer_events_total == 0u);
    assert(frontier_census.premphf_band.state == AtlasState::RegisteredButProxied);
    assert(frontier_census.premphf_band.frontier_events_total > 0u);
    assert(frontier_census.idx2row.state == AtlasState::RegisteredButProxied);
    assert(frontier_census.idx2row.frontier_events_total > 0u);
    assert(frontier_census.rowindex.state == AtlasState::ShadowOnly);
    assert(frontier_census.rowindex.frontier_events_total > 0u);
    assert(frontier_census.rowdescriptor.state == AtlasState::Missing);
    assert(frontier_census.rowdescriptor.evidenceTotal() == 0u);

    PeLocalServiceObjectTable::Config service_cfg{};
    service_cfg.enable = true;
    service_cfg.num_pods = 1;
    service_cfg.active_entries_per_pod = 8;
    service_cfg.released_entries_per_pod = 8;
    PeLocalServiceObjectTable service_table(service_cfg);

    SST::SnnDL::BcsrWeightManager owner_bcsr_mgr;
    configureHotRowIndexManager(owner_bcsr_mgr, 1u);

    WeightMemorySubsystem rowidx_owner;
    configureRowidxShadowWms(
        rowidx_owner, 39u, 0u, 0u, 1u, &owner_bcsr_mgr, &metadata_plane, &owner_table, &fabric);
    rowidx_owner.bindPeLocalServiceObjectTable(&service_table);
    rowidx_owner.window_seq_ = 31u;
    rowidx_owner.noteWindowTouch(19u, 23u, 64u);

    const auto rowidx_census = rowidx_owner.experimentalPeAtlasObjectCensus();
    assert(rowidx_census.rowindex.state == AtlasState::ShadowOnly);
    assert(rowidx_census.rowindex.producer_events_total > 0u);
    assert(rowidx_census.rowindex.gate_events_total > 0u);
    assert(rowidx_census.rowindex.service_events_total == 0u);
    assert(rowidx_census.premphf_base.state == AtlasState::Missing);
    assert(rowidx_census.rowdescriptor.state == AtlasState::Missing);
}

void test_real_wms_atlas_phase_ledger_tracks_local_window_order() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_cfg{};
    owner_cfg.enable = true;
    owner_cfg.num_pods = 1;
    owner_cfg.owner_entries_per_pod = 8;
    owner_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    SST::SnnDL::BcsrWeightManager bcsr_mgr;
    configureHotRowIndexManager(bcsr_mgr, 1u);

    WeightMemorySubsystem wms;
    configureRowidxShadowWms(
        wms, 40u, 0u, 0u, 1u, &bcsr_mgr, &metadata_plane, &owner_table, &fabric);

    wms.beginGatherWindow(true, 64u);
    wms.noteWindowTouch(19u, 23u, 64u);
    wms.beginApplyWindow(7u, false, nullptr, 0);
    wms.endScatterWindow(7u);

    const auto phase = wms.experimentalPeAtlasPhaseStats();
    assert(phase.local_begin_gather_total == 1u);
    assert(phase.local_first_touch_after_gather_open_total == 1u);
    assert(phase.local_touch_without_gather_open_total == 0u);
    assert(phase.local_touch_during_apply_total == 0u);
    assert(phase.local_begin_apply_total == 1u);
    assert(phase.local_begin_apply_with_touch_total == 1u);
    assert(phase.local_begin_apply_with_pending_rowidx_total == 1u);
    assert(phase.local_begin_apply_without_pending_rowidx_total == 0u);
    assert(phase.local_end_scatter_total == 1u);
}

void test_real_wms_atlas_phase_ledger_marks_touch_without_local_gather_open() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_cfg{};
    owner_cfg.enable = true;
    owner_cfg.num_pods = 1;
    owner_cfg.owner_entries_per_pod = 8;
    owner_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    SST::SnnDL::BcsrWeightManager bcsr_mgr;
    configureHotRowIndexManager(bcsr_mgr, 1u);

    WeightMemorySubsystem wms;
    configureRowidxShadowWms(
        wms, 41u, 0u, 0u, 1u, &bcsr_mgr, &metadata_plane, &owner_table, &fabric);

    wms.noteWindowTouch(19u, 23u, 64u);
    wms.beginApplyWindow(9u, false, nullptr, 0);

    const auto phase = wms.experimentalPeAtlasPhaseStats();
    assert(phase.local_begin_gather_total == 0u);
    assert(phase.local_first_touch_after_gather_open_total == 0u);
    assert(phase.local_touch_without_gather_open_total == 1u);
    assert(phase.local_begin_apply_total == 1u);
    assert(phase.local_begin_apply_with_touch_total == 0u);
    assert(phase.local_begin_apply_with_pending_rowidx_total == 1u);
    assert(phase.local_begin_apply_without_pending_rowidx_total == 0u);
}

void test_real_wms_rowindex_lifecycle_ledger_tracks_today_release_and_fallback() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_cfg{};
    owner_cfg.enable = true;
    owner_cfg.num_pods = 1;
    owner_cfg.owner_entries_per_pod = 8;
    owner_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_cfg);

    PeLocalServiceObjectTable::Config service_cfg{};
    service_cfg.enable = true;
    service_cfg.num_pods = 1;
    service_cfg.active_entries_per_pod = 8;
    service_cfg.released_entries_per_pod = 8;
    PeLocalServiceObjectTable service_table(service_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    SST::SnnDL::BcsrWeightManager owner_bcsr_mgr;
    SST::SnnDL::BcsrWeightManager joiner_bcsr_mgr;
    configureHotRowIndexManager(owner_bcsr_mgr, 1u);
    configureHotRowIndexManager(joiner_bcsr_mgr, 1u);

    FakeMemoryAccess owner_mem;

    WeightMemorySubsystem owner;
    WeightMemorySubsystem joiner;
    configureRowidxShadowWms(
        owner, 40u, 0u, 0u, 1u, &owner_bcsr_mgr, &metadata_plane, &owner_table, &fabric);
    configureRowidxShadowWms(
        joiner, 40u, 1u, 0u, 1u, &joiner_bcsr_mgr, &metadata_plane, &owner_table, &fabric);
    owner.bindMemory(&owner_mem);
    owner.bindPeLocalServiceObjectTable(&service_table);
    joiner.bindPeLocalServiceObjectTable(&service_table);
    owner.window_seq_ = 41u;
    joiner.window_seq_ = 41u;

    owner.noteWindowTouch(19u, 23u, 64u);
    joiner.noteWindowTouch(19u, 23u, 64u);

    const auto owner_before = owner.experimentalPeAtlasRowIndexLifecycleLedger();
    assert(owner_before.materialize_total == 1u);
    assert(owner_before.publicize_total == 1u);
    assert(owner_before.owner_form_total == 1u);
    assert(owner_before.join_live_total == 0u);
    assert(owner_before.join_ready_total == 0u);
    assert(owner_before.ready_total == 0u);
    assert(owner_before.release_total == 0u);
    assert(owner_before.release_missing_total == 0u);
    assert(owner_before.fallback_total == 1u);

    const auto joiner_before = joiner.experimentalPeAtlasRowIndexLifecycleLedger();
    assert(joiner_before.materialize_total == 1u);
    assert(joiner_before.publicize_total == 1u);
    assert(joiner_before.owner_form_total == 0u);
    assert(joiner_before.join_live_total == 1u);
    assert(joiner_before.join_ready_total == 0u);
    assert(joiner_before.ready_total == 0u);
    assert(joiner_before.release_total == 0u);
    assert(joiner_before.release_missing_total == 0u);
    assert(joiner_before.fallback_total == 1u);

    owner.onClockTick(1u);
    assert(owner_mem.read_count == 1u);
    assert(owner_mem.callbacks.size() == 1u);
    owner_mem.callbacks.front()(1u, owner_mem.last_addr, makeSingleRowIndexBytes(0u));

    const auto owner_after_ready = owner.experimentalPeAtlasRowIndexLifecycleLedger();
    assert(owner_after_ready.ready_total == 1u);
    assert(owner_after_ready.release_total == 0u);
    assert(owner_after_ready.release_missing_total == 0u);

    owner.endScatterWindow(41u);

    const auto owner_after_release = owner.experimentalPeAtlasRowIndexLifecycleLedger();
    assert(owner_after_release.ready_total == 1u);
    assert(owner_after_release.release_total == 1u);
    assert(owner_after_release.release_missing_total == 0u);
}

void test_real_wms_rowidx_gather_touch_promotes_into_apply_window_service_plane() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_cfg{};
    owner_cfg.enable = true;
    owner_cfg.num_pods = 1;
    owner_cfg.owner_entries_per_pod = 8;
    owner_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_cfg);

    PeLocalServiceObjectTable::Config service_cfg{};
    service_cfg.enable = true;
    service_cfg.num_pods = 1;
    service_cfg.active_entries_per_pod = 8;
    service_cfg.released_entries_per_pod = 8;
    PeLocalServiceObjectTable service_table(service_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    SST::SnnDL::BcsrWeightManager owner_bcsr_mgr;
    SST::SnnDL::BcsrWeightManager joiner_bcsr_mgr;
    configureHotRowIndexManager(owner_bcsr_mgr, 1u);
    configureHotRowIndexManager(joiner_bcsr_mgr, 1u);

    WeightMemorySubsystem owner;
    WeightMemorySubsystem joiner;
    configureRowidxShadowWms(
        owner, 41u, 0u, 0u, 1u, &owner_bcsr_mgr, &metadata_plane, &owner_table, &fabric);
    configureRowidxShadowWms(
        joiner, 41u, 1u, 0u, 1u, &joiner_bcsr_mgr, &metadata_plane, &owner_table, &fabric);
    owner.bindPeLocalServiceObjectTable(&service_table);
    joiner.bindPeLocalServiceObjectTable(&service_table);

    owner.noteWindowTouch(19u, 23u, 64u);
    joiner.noteWindowTouch(19u, 23u, 64u);

    const auto owner_gather = owner.experimentalPeAtlasRowIndexLifecycleLedger();
    const auto joiner_gather = joiner.experimentalPeAtlasRowIndexLifecycleLedger();
    assert(owner_gather.materialize_total == 1u);
    assert(owner_gather.publicize_total == 1u);
    assert(owner_gather.owner_form_total == 0u);
    assert(joiner_gather.join_live_total == 0u);
    assert(joiner_gather.join_ready_total == 0u);

    owner.beginApplyWindow(51u, false, nullptr, 0);
    joiner.beginApplyWindow(51u, false, nullptr, 1);

    const auto owner_apply = owner.experimentalPeAtlasRowIndexLifecycleLedger();
    const auto joiner_apply = joiner.experimentalPeAtlasRowIndexLifecycleLedger();
    const auto owner_rowidx_stats = owner.experimentalNocRowidxStats();
    const auto joiner_rowidx_stats = joiner.experimentalNocRowidxStats();
    assert(owner_apply.owner_form_total == 1u);
    assert(joiner_apply.join_live_total == 1u);
    assert(owner_rowidx_stats.apply_promote_rows_total == 1u);
    assert(owner_rowidx_stats.apply_promote_cached_ready_total == 0u);
    assert(joiner_rowidx_stats.apply_promote_rows_total == 1u);
    assert(joiner_rowidx_stats.apply_promote_cached_ready_total == 0u);
}

void test_real_wms_rowidx_apply_promote_cached_ready_transitions_once() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_cfg{};
    owner_cfg.enable = true;
    owner_cfg.num_pods = 1;
    owner_cfg.owner_entries_per_pod = 8;
    owner_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_cfg);

    PeLocalServiceObjectTable::Config service_cfg{};
    service_cfg.enable = true;
    service_cfg.num_pods = 1;
    service_cfg.active_entries_per_pod = 8;
    service_cfg.released_entries_per_pod = 8;
    PeLocalServiceObjectTable service_table(service_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    SST::SnnDL::BcsrWeightManager owner_bcsr_mgr;
    SST::SnnDL::BcsrWeightManager joiner_bcsr_mgr;
    configureHotRowIndexManager(owner_bcsr_mgr, 1u);
    configureHotRowIndexManager(joiner_bcsr_mgr, 1u);

    WeightMemorySubsystem owner;
    WeightMemorySubsystem joiner;
    configureRowidxShadowWms(
        owner, 43u, 0u, 0u, 1u, &owner_bcsr_mgr, &metadata_plane, &owner_table, &fabric);
    configureRowidxShadowWms(
        joiner, 43u, 1u, 0u, 1u, &joiner_bcsr_mgr, &metadata_plane, &owner_table, &fabric);
    owner.bindPeLocalServiceObjectTable(&service_table);
    joiner.bindPeLocalServiceObjectTable(&service_table);

    const std::vector<uint32_t> hot_cols{0u};
    owner.storeExperimentalNocRowidxCache_(1u, 0u, hot_cols);
    joiner.storeExperimentalNocRowidxCache_(1u, 0u, hot_cols);

    owner.noteWindowTouch(19u, 23u, 64u);
    joiner.noteWindowTouch(19u, 23u, 64u);

    owner.beginApplyWindow(52u, false, nullptr, 0);
    joiner.beginApplyWindow(52u, false, nullptr, 1);

    const auto service_after_apply = service_table.snapshotStats();
    assert(service_after_apply.owner_form_total == 1u);
    assert(service_after_apply.join_ready_total == 1u);
    assert(service_after_apply.ready_transition_total == 1u);
    assert(service_after_apply.ready_fanout_total == 1u);

    const auto owner_rowidx_stats = owner.experimentalNocRowidxStats();
    const auto joiner_rowidx_stats = joiner.experimentalNocRowidxStats();
    assert(owner_rowidx_stats.apply_promote_cached_ready_total == 1u);
    assert(owner_rowidx_stats.ready_transition_apply_promote_cached_total == 1u);
    assert(joiner_rowidx_stats.apply_promote_cached_ready_total == 1u);
    assert(joiner_rowidx_stats.ready_transition_apply_promote_cached_total == 0u);
}

void test_real_wms_rowidx_runtime_gate_enable_before_apply_promotes_into_pod_service_plane() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_cfg{};
    owner_cfg.enable = true;
    owner_cfg.num_pods = 1;
    owner_cfg.owner_entries_per_pod = 8;
    owner_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_cfg);

    PeLocalServiceObjectTable::Config service_cfg{};
    service_cfg.enable = true;
    service_cfg.num_pods = 1;
    service_cfg.active_entries_per_pod = 8;
    service_cfg.released_entries_per_pod = 8;
    PeLocalServiceObjectTable service_table(service_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    SST::SnnDL::BcsrWeightManager owner_bcsr_mgr;
    SST::SnnDL::BcsrWeightManager joiner_bcsr_mgr;
    configureHotRowIndexManager(owner_bcsr_mgr, 1u);
    configureHotRowIndexManager(joiner_bcsr_mgr, 1u);

    WeightMemorySubsystem owner;
    WeightMemorySubsystem joiner;
    configureRowidxShadowWms(
        owner, 41u, 0u, 0u, 1u, &owner_bcsr_mgr, &metadata_plane, &owner_table, &fabric);
    configureRowidxShadowWms(
        joiner, 41u, 1u, 0u, 1u, &joiner_bcsr_mgr, &metadata_plane, &owner_table, &fabric);
    owner.bindPeLocalServiceObjectTable(&service_table);
    joiner.bindPeLocalServiceObjectTable(&service_table);

    owner.orch_.pe_internal_cpe_enable = false;
    owner.orch_.pe_internal_pod_enable = false;
    owner.orch_.pe_internal_pod_metadata_enable = false;
    owner.orch_.pe_internal_pod_owner_enable = false;
    joiner.orch_.pe_internal_cpe_enable = false;
    joiner.orch_.pe_internal_pod_enable = false;
    joiner.orch_.pe_internal_pod_metadata_enable = false;
    joiner.orch_.pe_internal_pod_owner_enable = false;

    owner.beginGatherWindow(true, 64u);
    joiner.beginGatherWindow(true, 64u);
    owner.noteWindowTouch(19u, 23u, 64u);
    joiner.noteWindowTouch(19u, 23u, 64u);

    const auto owner_gather = owner.experimentalPeAtlasRowIndexLifecycleLedger();
    const auto joiner_gather = joiner.experimentalPeAtlasRowIndexLifecycleLedger();
    assert(owner_gather.materialize_total == 1u);
    assert(owner_gather.publicize_total == 1u);
    assert(owner_gather.owner_form_total == 0u);
    assert(joiner_gather.materialize_total == 1u);
    assert(joiner_gather.publicize_total == 1u);
    assert(joiner_gather.join_live_total == 0u);

    const auto metadata_before = metadata_plane.snapshotStats();
    const auto owner_before = owner_table.snapshotStats();
    const auto service_before = service_table.snapshotStats();
    assert(metadata_before.observe_total == 0u);
    assert(owner_before.lookup_total == 0u);
    assert(service_before.owner_form_total == 0u);
    assert(service_before.join_live_total == 0u);

    owner.setPeInternalPodRuntimeConfig(true, true, true, true, 0u, 1u, 2u, 0u);
    joiner.setPeInternalPodRuntimeConfig(true, true, true, true, 0u, 1u, 2u, 1u);

    owner.beginApplyWindow(51u, false, nullptr, 0);
    joiner.beginApplyWindow(51u, false, nullptr, 1);

    const auto owner_apply = owner.experimentalPeAtlasRowIndexLifecycleLedger();
    const auto joiner_apply = joiner.experimentalPeAtlasRowIndexLifecycleLedger();
    const auto owner_rowidx_stats = owner.experimentalNocRowidxStats();
    const auto joiner_rowidx_stats = joiner.experimentalNocRowidxStats();
    const auto owner_pod_stats = owner.peInternalPodStats();
    const auto joiner_pod_stats = joiner.peInternalPodStats();
    const auto metadata_after = metadata_plane.snapshotStats();
    const auto owner_after = owner_table.snapshotStats();
    const auto service_after = service_table.snapshotStats();

    assert(owner_apply.owner_form_total == 1u);
    assert(joiner_apply.join_live_total == 1u);
    assert(owner_rowidx_stats.apply_promote_rows_total == 1u);
    assert(owner_rowidx_stats.apply_promote_cached_ready_total == 0u);
    assert(joiner_rowidx_stats.apply_promote_rows_total == 1u);
    assert(joiner_rowidx_stats.apply_promote_cached_ready_total == 0u);

    assert(owner_pod_stats.guard_disabled_total == 0u);
    assert(joiner_pod_stats.guard_disabled_total == 0u);

    assert(metadata_after.observe_total == 2u);
    assert(metadata_after.unique_object_total == 1u);
    assert(metadata_after.overlap_hit_total == 1u);
    assert(owner_after.lookup_total == 2u);
    assert(owner_after.owner_alloc_total == 1u);
    assert(owner_after.owner_hit_total == 1u);
    assert(owner_after.join_request_total == 1u);
    assert(owner_after.join_grant_total == 1u);
    assert(service_after.owner_form_total == 1u);
    assert(service_after.join_live_total == 1u);
    assert(service_after.join_ready_total == 0u);
    assert(service_after.potential_private_service_elide_total == 1u);
}

void test_real_wms_atlas_proxy_ledgers_freeze_idx2row_prebase_and_preband_today_contract() {
    WeightMemorySubsystem wms;

    wms.pulse_metadata_frontier_idx2row_observed_total_ = 3u;
    wms.pe_internal_pod_owner_alloc_idx2row_total_ = 1u;
    wms.pe_internal_pod_service_join_live_idx2row_total_ = 2u;
    wms.pe_internal_pod_service_join_ready_idx2row_total_ = 1u;
    wms.pe_internal_pod_service_ready_transition_idx2row_total_ = 1u;
    wms.pe_internal_pod_service_released_idx2row_total_ = 1u;
    wms.pe_internal_pod_service_release_missing_idx2row_total_ = 1u;
    wms.pe_internal_pod_reject_idx2row_total_ = 2u;
    wms.pe_internal_pod_useful_idx2row_total_ = 1u;

    wms.pulse_metadata_frontier_premphf_base_observed_total_ = 9u;
    wms.pulse_prebase_lookup_owner_fill_total_ = 4u;
    wms.pulse_prebase_lookup_shared_hits_total_ = 6u;

    wms.pulse_metadata_frontier_premphf_band_observed_total_ = 7u;
    wms.pulse_metadata_frontier_premphf_band_owner_form_candidate_total_ = 2u;
    wms.pulse_metadata_frontier_premphf_band_join_ready_candidate_total_ = 1u;

    const auto idx2row = wms.experimentalPeAtlasIdx2RowLifecycleLedger();
    assert(idx2row.materialize_total == 3u);
    assert(idx2row.publicize_total == 3u);
    assert(idx2row.owner_form_total == 1u);
    assert(idx2row.join_live_total == 2u);
    assert(idx2row.join_ready_total == 1u);
    assert(idx2row.ready_total == 1u);
    assert(idx2row.release_total == 1u);
    assert(idx2row.release_missing_total == 1u);
    assert(idx2row.fallback_total == 4u);

    const auto premphf_base = wms.experimentalPeAtlasPreMphfBaseProxyLedger();
    assert(premphf_base.materialize_total == 9u);
    assert(premphf_base.publicize_total == 4u);
    assert(premphf_base.owner_form_total == 4u);
    assert(premphf_base.shared_hit_total == 6u);
    assert(premphf_base.lookup_ready_total == 6u);
    assert(premphf_base.proxy_only_gap_total == 5u);

    const auto premphf_band = wms.experimentalPeAtlasPreMphfBandProxyLedger();
    assert(premphf_band.materialize_total == 7u);
    assert(premphf_band.publicize_total == 7u);
    assert(premphf_band.owner_form_candidate_total == 2u);
    assert(premphf_band.join_ready_candidate_total == 1u);
    assert(premphf_band.zero_service_total == 7u);
}

} // namespace

int main(int argc, char** argv) {
    (void)argc;
    (void)argv;
    test_real_wms_shadow_direct_window_zero_guard_drops();
    test_real_wms_frontier_owner_join_flow();
    test_real_wms_direct_duplicate_replay_counts_usefulness();
    test_real_wms_frontier_join_table_disabled_reject_split();
    test_real_wms_idx2_touch_path_tracks_other_shape();
    test_real_wms_rowidx_touch_path_tracks_rowindex_shape();
    test_real_wms_rowidx_prefetch_completion_marks_ready_and_releases_owner_entry();
    test_real_wms_rowidx_detached_prefetch_completion_records_noninflight_ready_path();
    test_real_wms_rowidx_detached_prefetch_demand_joins_without_legacy_inflight();
    test_real_wms_rowidx_detached_carry_to_apply_issues_under_apply_window_seq();
    test_real_wms_rowidx_endscatter_before_ready_keeps_owner_active_until_late_completion();
    test_real_wms_rowidx_joiner_late_ready_releases_owner_closed_entry();
    test_real_wms_rowidx_joiner_endscatter_does_not_probe_owner_close_queue();
    test_real_wms_atlas_object_census_freezes_today_family_states();
    test_real_wms_atlas_phase_ledger_tracks_local_window_order();
    test_real_wms_atlas_phase_ledger_marks_touch_without_local_gather_open();
    test_real_wms_rowindex_lifecycle_ledger_tracks_today_release_and_fallback();
    test_real_wms_rowidx_gather_touch_promotes_into_apply_window_service_plane();
    test_real_wms_rowidx_apply_promote_cached_ready_transitions_once();
    test_real_wms_rowidx_runtime_gate_enable_before_apply_promotes_into_pod_service_plane();
    test_real_wms_atlas_proxy_ledgers_freeze_idx2row_prebase_and_preband_today_contract();
    return 0;
}
