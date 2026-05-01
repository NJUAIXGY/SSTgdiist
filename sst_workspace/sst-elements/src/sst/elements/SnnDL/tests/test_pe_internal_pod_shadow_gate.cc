#include <cassert>
#include <cstdint>

#include "services/local_storage/PeInternalPodShadowGate.h"
#include "services/local_storage/PodMetadataObjectPlane.h"
#include "services/local_storage/PodOwnerServiceTable.h"
#include "services/pe_fabric/PeSharedCoreFabric.h"

using SST::SnnDL::PeInternalPodShadowGate;
using SST::SnnDL::PeInternalPodShadowGateBindings;
using SST::SnnDL::PeInternalPodShadowGateConfig;
using SST::SnnDL::PeInternalPodShadowGateCounters;
using SST::SnnDL::PodMetadataObjectPlane;
using SST::SnnDL::PodOwnerServiceTable;
using SST::SnnDL::PeSharedCoreFabric;

namespace {

void configureShadowGate(PeInternalPodShadowGateConfig& cfg,
                         uint32_t core_id,
                         uint32_t pod_id) {
    cfg = PeInternalPodShadowGateConfig{};
    cfg.core_id = core_id;
    cfg.pe_internal_cpe_enable = true;
    cfg.pe_internal_pod_enable = true;
    cfg.pe_internal_pod_metadata_enable = true;
    cfg.pe_internal_pod_owner_enable = true;
    cfg.pod_count = 1u;
    cfg.pod_id = pod_id;
    cfg.window_seq = 7u;
}

void test_shadow_gate_allocates_owner_then_records_join() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_table_cfg{};
    owner_table_cfg.enable = true;
    owner_table_cfg.num_pods = 1;
    owner_table_cfg.owner_entries_per_pod = 8;
    owner_table_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_table_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    PeInternalPodShadowGateBindings bindings{};
    bindings.metadata_plane = &metadata_plane;
    bindings.owner_table = &owner_table;
    bindings.fabric = &fabric;

    PeInternalPodShadowGateConfig owner_gate_cfg{};
    PeInternalPodShadowGateConfig joiner_cfg{};
    configureShadowGate(owner_gate_cfg, 0u, 0u);
    configureShadowGate(joiner_cfg, 1u, 0u);

    PeInternalPodShadowGateCounters owner_counters{};
    PeInternalPodShadowGateCounters joiner_counters{};

    PeInternalPodShadowGate::observe(
        owner_gate_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        16u,
        owner_counters);
    PeInternalPodShadowGate::observe(
        owner_gate_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBand,
        2u,
        owner_counters);
    PeInternalPodShadowGate::observe(
        joiner_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        16u,
        joiner_counters);
    PeInternalPodShadowGate::observe(
        joiner_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBand,
        2u,
        joiner_counters);

    const auto metadata_stats = metadata_plane.snapshotStats();
    assert(metadata_stats.observe_total == 4u);
    assert(metadata_stats.unique_object_total == 2u);
    assert(metadata_stats.overlap_hit_total == 2u);
    assert(metadata_stats.active_entries_total == 2u);

    const auto owner_stats = owner_table.snapshotStats();
    assert(owner_stats.lookup_total == 4u);
    assert(owner_stats.owner_alloc_total == 2u);
    assert(owner_stats.owner_hit_total == 2u);
    assert(owner_stats.join_request_total == 2u);
    assert(owner_stats.join_grant_total == 2u);
    assert(owner_stats.active_entries_total == 2u);

    assert(owner_counters.frontier_export_total == 2u);
    assert(owner_counters.owner_lookup_total == 2u);
    assert(owner_counters.owner_alloc_total == 2u);
    assert(owner_counters.owner_hit_total == 0u);
    assert(owner_counters.join_request_total == 0u);
    assert(owner_counters.join_before_private_issue_total == 0u);
    assert(owner_counters.useful_total == 0u);
    assert(owner_counters.useful_join_grant_total == 0u);
    assert(owner_counters.useful_duplicate_replay_elide_total == 0u);
    assert(owner_counters.attempted_total == 0u);
    assert(owner_counters.attempted_guard_total == 0u);
    assert(owner_counters.attempted_reject_total == 0u);
    assert(owner_counters.attempted_useful_total == 0u);
    assert(owner_counters.useful_base_total == 0u);
    assert(owner_counters.useful_band_total == 0u);
    assert(owner_counters.useful_other_total == 0u);
    assert(owner_counters.attempted_base_total == 0u);
    assert(owner_counters.attempted_band_total == 0u);
    assert(owner_counters.attempted_other_total == 0u);
    assert(owner_counters.duplicate_metadata_replay_elided_total == 0u);
    assert(owner_counters.fallback_private_issue_total == 2u);

    assert(joiner_counters.frontier_export_total == 2u);
    assert(joiner_counters.owner_lookup_total == 2u);
    assert(joiner_counters.owner_alloc_total == 0u);
    assert(joiner_counters.owner_hit_total == 2u);
    assert(joiner_counters.join_request_total == 2u);
    assert(joiner_counters.join_grant_total == 2u);
    assert(joiner_counters.join_before_private_issue_total == 2u);
    assert(joiner_counters.useful_total == 2u);
    assert(joiner_counters.useful_join_grant_total == 2u);
    assert(joiner_counters.useful_duplicate_replay_elide_total == 0u);
    assert(joiner_counters.attempted_total == 2u);
    assert(joiner_counters.attempted_guard_total == 0u);
    assert(joiner_counters.attempted_reject_total == 0u);
    assert(joiner_counters.attempted_useful_total == 2u);
    assert(joiner_counters.useful_base_total == 1u);
    assert(joiner_counters.useful_band_total == 1u);
    assert(joiner_counters.useful_other_total == 0u);
    assert(joiner_counters.attempted_base_total == 1u);
    assert(joiner_counters.attempted_band_total == 1u);
    assert(joiner_counters.attempted_other_total == 0u);
    assert(joiner_counters.duplicate_metadata_replay_elided_total == 0u);
    assert(joiner_counters.duplicate_metadata_issue_elided_total == 2u);
    assert(joiner_counters.fallback_private_issue_total == 2u);

    const auto fabric_stats = fabric.snapshotStats();
    assert(fabric_stats.control_messages_enqueued_total == 8u);
    assert(fabric_stats.control_frontier_export_total == 4u);
    assert(fabric_stats.control_owner_announce_total == 2u);
    assert(fabric_stats.control_join_request_total == 2u);
    assert(fabric_stats.control_join_reject_total == 0u);
}

void test_shadow_gate_elides_duplicate_metadata_before_owner_lookup() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_table_cfg{};
    owner_table_cfg.enable = true;
    owner_table_cfg.num_pods = 1;
    owner_table_cfg.owner_entries_per_pod = 8;
    owner_table_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_table_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    PeInternalPodShadowGateBindings bindings{};
    bindings.metadata_plane = &metadata_plane;
    bindings.owner_table = &owner_table;
    bindings.fabric = &fabric;

    PeInternalPodShadowGateConfig owner_gate_cfg{};
    configureShadowGate(owner_gate_cfg, 0u, 0u);

    PeInternalPodShadowGateCounters owner_counters{};

    PeInternalPodShadowGate::observe(
        owner_gate_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        16u,
        owner_counters);
    PeInternalPodShadowGate::observe(
        owner_gate_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        16u,
        owner_counters);

    const auto metadata_stats = metadata_plane.snapshotStats();
    assert(metadata_stats.observe_total == 2u);
    assert(metadata_stats.unique_object_total == 1u);
    assert(metadata_stats.duplicate_consumer_total == 1u);
    assert(metadata_stats.overlap_hit_total == 0u);

    const auto owner_stats = owner_table.snapshotStats();
    assert(owner_stats.lookup_total == 1u);
    assert(owner_stats.owner_alloc_total == 1u);
    assert(owner_stats.owner_hit_total == 0u);
    assert(owner_stats.join_request_total == 0u);
    assert(owner_stats.join_grant_total == 0u);

    assert(owner_counters.frontier_export_total == 1u);
    assert(owner_counters.owner_lookup_total == 1u);
    assert(owner_counters.owner_alloc_total == 1u);
    assert(owner_counters.owner_hit_total == 0u);
    assert(owner_counters.join_request_total == 0u);
    assert(owner_counters.join_grant_total == 0u);
    assert(owner_counters.join_reject_total == 0u);
    assert(owner_counters.duplicate_metadata_replay_elided_total == 1u);
    assert(owner_counters.useful_total == 1u);
    assert(owner_counters.useful_join_grant_total == 0u);
    assert(owner_counters.useful_duplicate_replay_elide_total == 1u);
    assert(owner_counters.attempted_total == 1u);
    assert(owner_counters.attempted_guard_total == 0u);
    assert(owner_counters.attempted_reject_total == 0u);
    assert(owner_counters.attempted_useful_total == 1u);
    assert(owner_counters.useful_base_total == 1u);
    assert(owner_counters.useful_band_total == 0u);
    assert(owner_counters.useful_other_total == 0u);
    assert(owner_counters.attempted_base_total == 1u);
    assert(owner_counters.attempted_band_total == 0u);
    assert(owner_counters.attempted_other_total == 0u);
    assert(owner_counters.duplicate_metadata_issue_elided_total == 1u);
    assert(owner_counters.fallback_private_issue_total == 1u);

    const auto fabric_stats = fabric.snapshotStats();
    assert(fabric_stats.control_messages_enqueued_total == 2u);
    assert(fabric_stats.control_frontier_export_total == 1u);
    assert(fabric_stats.control_owner_announce_total == 1u);
    assert(fabric_stats.control_join_request_total == 0u);
    assert(fabric_stats.control_join_reject_total == 0u);
}

void test_shadow_gate_elides_duplicate_joiner_metadata_before_join() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_table_cfg{};
    owner_table_cfg.enable = true;
    owner_table_cfg.num_pods = 1;
    owner_table_cfg.owner_entries_per_pod = 8;
    owner_table_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_table_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    PeInternalPodShadowGateBindings bindings{};
    bindings.metadata_plane = &metadata_plane;
    bindings.owner_table = &owner_table;
    bindings.fabric = &fabric;

    PeInternalPodShadowGateConfig owner_gate_cfg{};
    PeInternalPodShadowGateConfig joiner_cfg{};
    configureShadowGate(owner_gate_cfg, 0u, 0u);
    configureShadowGate(joiner_cfg, 1u, 0u);

    PeInternalPodShadowGateCounters owner_counters{};
    PeInternalPodShadowGateCounters joiner_counters{};

    PeInternalPodShadowGate::observe(
        owner_gate_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        16u,
        owner_counters);
    PeInternalPodShadowGate::observe(
        joiner_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        16u,
        joiner_counters);
    PeInternalPodShadowGate::observe(
        joiner_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        16u,
        joiner_counters);

    const auto metadata_stats = metadata_plane.snapshotStats();
    assert(metadata_stats.observe_total == 3u);
    assert(metadata_stats.unique_object_total == 1u);
    assert(metadata_stats.overlap_hit_total == 1u);
    assert(metadata_stats.duplicate_consumer_total == 1u);

    const auto owner_stats = owner_table.snapshotStats();
    assert(owner_stats.lookup_total == 2u);
    assert(owner_stats.owner_alloc_total == 1u);
    assert(owner_stats.owner_hit_total == 1u);
    assert(owner_stats.join_request_total == 1u);
    assert(owner_stats.join_grant_total == 1u);
    assert(owner_stats.join_reject_total == 0u);

    assert(owner_counters.frontier_export_total == 1u);
    assert(owner_counters.owner_lookup_total == 1u);
    assert(owner_counters.owner_alloc_total == 1u);
    assert(owner_counters.fallback_private_issue_total == 1u);

    assert(joiner_counters.frontier_export_total == 1u);
    assert(joiner_counters.owner_lookup_total == 1u);
    assert(joiner_counters.owner_alloc_total == 0u);
    assert(joiner_counters.owner_hit_total == 1u);
    assert(joiner_counters.join_request_total == 1u);
    assert(joiner_counters.join_grant_total == 1u);
    assert(joiner_counters.join_reject_total == 0u);
    assert(joiner_counters.join_before_private_issue_total == 1u);
    assert(joiner_counters.useful_total == 2u);
    assert(joiner_counters.useful_join_grant_total == 1u);
    assert(joiner_counters.useful_duplicate_replay_elide_total == 1u);
    assert(joiner_counters.duplicate_metadata_replay_elided_total == 1u);
    assert(joiner_counters.duplicate_metadata_issue_elided_total == 2u);
    assert(joiner_counters.fallback_private_issue_total == 1u);

    const auto fabric_stats = fabric.snapshotStats();
    assert(fabric_stats.control_messages_enqueued_total == 4u);
    assert(fabric_stats.control_frontier_export_total == 2u);
    assert(fabric_stats.control_owner_announce_total == 1u);
    assert(fabric_stats.control_join_request_total == 1u);
    assert(fabric_stats.control_join_reject_total == 0u);
}

void test_shadow_gate_tracks_row_index_as_other_shape() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_table_cfg{};
    owner_table_cfg.enable = true;
    owner_table_cfg.num_pods = 1;
    owner_table_cfg.owner_entries_per_pod = 8;
    owner_table_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_table_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    PeInternalPodShadowGateBindings bindings{};
    bindings.metadata_plane = &metadata_plane;
    bindings.owner_table = &owner_table;
    bindings.fabric = &fabric;

    PeInternalPodShadowGateConfig owner_gate_cfg{};
    PeInternalPodShadowGateConfig joiner_cfg{};
    configureShadowGate(owner_gate_cfg, 0u, 0u);
    configureShadowGate(joiner_cfg, 1u, 0u);

    PeInternalPodShadowGateCounters owner_counters{};
    PeInternalPodShadowGateCounters joiner_counters{};

    PeInternalPodShadowGate::observe(
        owner_gate_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::RowIndex,
        5u,
        owner_counters);
    PeInternalPodShadowGate::observe(
        joiner_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::RowIndex,
        5u,
        joiner_counters);

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

    assert(owner_counters.owner_alloc_total == 1u);
    assert(owner_counters.useful_total == 0u);
    assert(owner_counters.useful_other_total == 0u);
    assert(owner_counters.attempted_other_total == 0u);
    assert(owner_counters.useful_idx2row_total == 0u);
    assert(owner_counters.useful_rowindex_total == 0u);
    assert(owner_counters.useful_rowdescriptor_total == 0u);
    assert(owner_counters.attempted_idx2row_total == 0u);
    assert(owner_counters.attempted_rowindex_total == 0u);
    assert(owner_counters.attempted_rowdescriptor_total == 0u);
    assert(owner_counters.fallback_private_issue_total == 1u);

    assert(joiner_counters.owner_hit_total == 1u);
    assert(joiner_counters.join_request_total == 1u);
    assert(joiner_counters.join_grant_total == 1u);
    assert(joiner_counters.useful_total == 1u);
    assert(joiner_counters.useful_join_grant_total == 1u);
    assert(joiner_counters.useful_other_total == 1u);
    assert(joiner_counters.useful_idx2row_total == 0u);
    assert(joiner_counters.useful_rowindex_total == 1u);
    assert(joiner_counters.useful_rowdescriptor_total == 0u);
    assert(joiner_counters.attempted_total == 1u);
    assert(joiner_counters.attempted_useful_total == 1u);
    assert(joiner_counters.attempted_other_total == 1u);
    assert(joiner_counters.attempted_idx2row_total == 0u);
    assert(joiner_counters.attempted_rowindex_total == 1u);
    assert(joiner_counters.attempted_rowdescriptor_total == 0u);
    assert(joiner_counters.fallback_private_issue_total == 1u);

    const auto fabric_stats = fabric.snapshotStats();
    assert(fabric_stats.control_messages_enqueued_total == 4u);
    assert(fabric_stats.control_frontier_export_total == 2u);
    assert(fabric_stats.control_owner_announce_total == 1u);
    assert(fabric_stats.control_join_request_total == 1u);
    assert(fabric_stats.control_join_reject_total == 0u);
}

void test_shadow_gate_tracks_row_descriptor_as_other_subkind() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_table_cfg{};
    owner_table_cfg.enable = true;
    owner_table_cfg.num_pods = 1;
    owner_table_cfg.owner_entries_per_pod = 8;
    owner_table_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_table_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    PeInternalPodShadowGateBindings bindings{};
    bindings.metadata_plane = &metadata_plane;
    bindings.owner_table = &owner_table;
    bindings.fabric = &fabric;

    PeInternalPodShadowGateConfig owner_gate_cfg{};
    PeInternalPodShadowGateConfig joiner_cfg{};
    configureShadowGate(owner_gate_cfg, 0u, 0u);
    configureShadowGate(joiner_cfg, 1u, 0u);

    PeInternalPodShadowGateCounters owner_counters{};
    PeInternalPodShadowGateCounters joiner_counters{};

    PeInternalPodShadowGate::observe(
        owner_gate_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::RowDescriptor,
        9u,
        owner_counters);
    PeInternalPodShadowGate::observe(
        joiner_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::RowDescriptor,
        9u,
        joiner_counters);

    assert(owner_counters.useful_other_total == 0u);
    assert(owner_counters.useful_idx2row_total == 0u);
    assert(owner_counters.useful_rowindex_total == 0u);
    assert(owner_counters.useful_rowdescriptor_total == 0u);
    assert(owner_counters.attempted_other_total == 0u);
    assert(owner_counters.attempted_idx2row_total == 0u);
    assert(owner_counters.attempted_rowindex_total == 0u);
    assert(owner_counters.attempted_rowdescriptor_total == 0u);

    assert(joiner_counters.useful_total == 1u);
    assert(joiner_counters.useful_other_total == 1u);
    assert(joiner_counters.useful_idx2row_total == 0u);
    assert(joiner_counters.useful_rowindex_total == 0u);
    assert(joiner_counters.useful_rowdescriptor_total == 1u);
    assert(joiner_counters.attempted_total == 1u);
    assert(joiner_counters.attempted_other_total == 1u);
    assert(joiner_counters.attempted_idx2row_total == 0u);
    assert(joiner_counters.attempted_rowindex_total == 0u);
    assert(joiner_counters.attempted_rowdescriptor_total == 1u);
}

void test_shadow_gate_disabled_config_is_noop() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_table_cfg{};
    owner_table_cfg.enable = true;
    owner_table_cfg.num_pods = 1;
    owner_table_cfg.owner_entries_per_pod = 8;
    owner_table_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_table_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    PeInternalPodShadowGateBindings bindings{};
    bindings.metadata_plane = &metadata_plane;
    bindings.owner_table = &owner_table;
    bindings.fabric = &fabric;

    PeInternalPodShadowGateConfig disabled_cfg{};
    configureShadowGate(disabled_cfg, 0u, 0u);
    disabled_cfg.pe_internal_pod_owner_enable = false;

    PeInternalPodShadowGateCounters counters{};
    PeInternalPodShadowGate::observe(
        disabled_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        16u,
        counters);

    const auto metadata_stats = metadata_plane.snapshotStats();
    assert(metadata_stats.observe_total == 0u);
    assert(metadata_stats.unique_object_total == 0u);

    const auto owner_stats = owner_table.snapshotStats();
    assert(owner_stats.lookup_total == 0u);
    assert(owner_stats.owner_alloc_total == 0u);
    assert(owner_stats.owner_reject_total == 0u);

    assert(counters.frontier_export_total == 0u);
    assert(counters.guard_drop_total == 1u);
    assert(counters.guard_disabled_total == 1u);
    assert(counters.attempted_total == 1u);
    assert(counters.attempted_guard_total == 1u);
    assert(counters.attempted_reject_total == 0u);
    assert(counters.attempted_useful_total == 0u);
    assert(counters.guard_base_total == 1u);
    assert(counters.guard_band_total == 0u);
    assert(counters.guard_other_total == 0u);
    assert(counters.attempted_base_total == 1u);
    assert(counters.attempted_band_total == 0u);
    assert(counters.attempted_other_total == 0u);
    assert(counters.guard_missing_metadata_plane_total == 0u);
    assert(counters.guard_missing_owner_table_total == 0u);
    assert(counters.guard_zero_pod_count_total == 0u);
    assert(counters.guard_window_zero_total == 0u);
    assert(counters.guard_invalid_cfg_pod_total == 0u);
    assert(counters.owner_lookup_total == 0u);
    assert(counters.owner_alloc_total == 0u);
    assert(counters.owner_reject_total == 0u);
    assert(counters.owner_disabled_reject_total == 0u);
    assert(counters.owner_table_full_reject_total == 0u);
    assert(counters.join_request_total == 0u);
    assert(counters.join_reject_total == 0u);
    assert(counters.join_table_full_reject_total == 0u);
    assert(counters.duplicate_metadata_replay_elided_total == 0u);
    assert(counters.duplicate_metadata_issue_elided_total == 0u);
    assert(counters.fallback_private_issue_total == 0u);

    const auto fabric_stats = fabric.snapshotStats();
    assert(fabric_stats.control_messages_enqueued_total == 0u);
}

void test_shadow_gate_owner_table_full_falls_back_with_reject() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_table_cfg{};
    owner_table_cfg.enable = true;
    owner_table_cfg.num_pods = 1;
    owner_table_cfg.owner_entries_per_pod = 1;
    owner_table_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_table_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    PeInternalPodShadowGateBindings bindings{};
    bindings.metadata_plane = &metadata_plane;
    bindings.owner_table = &owner_table;
    bindings.fabric = &fabric;

    PeInternalPodShadowGateConfig owner0_cfg{};
    PeInternalPodShadowGateConfig owner1_cfg{};
    configureShadowGate(owner0_cfg, 0u, 0u);
    configureShadowGate(owner1_cfg, 1u, 0u);

    PeInternalPodShadowGateCounters owner0_counters{};
    PeInternalPodShadowGateCounters owner1_counters{};

    PeInternalPodShadowGate::observe(
        owner0_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        16u,
        owner0_counters);
    PeInternalPodShadowGate::observe(
        owner1_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        32u,
        owner1_counters);

    const auto metadata_stats = metadata_plane.snapshotStats();
    assert(metadata_stats.observe_total == 2u);
    assert(metadata_stats.unique_object_total == 2u);
    assert(metadata_stats.overlap_hit_total == 0u);

    const auto owner_stats = owner_table.snapshotStats();
    assert(owner_stats.lookup_total == 2u);
    assert(owner_stats.owner_alloc_total == 1u);
    assert(owner_stats.owner_hit_total == 0u);
    assert(owner_stats.owner_reject_total == 1u);
    assert(owner_stats.join_request_total == 0u);
    assert(owner_stats.join_reject_total == 0u);
    assert(owner_stats.active_entries_total == 1u);

    assert(owner0_counters.owner_alloc_total == 1u);
    assert(owner0_counters.guard_drop_total == 0u);
    assert(owner0_counters.owner_reject_total == 0u);
    assert(owner0_counters.owner_disabled_reject_total == 0u);
    assert(owner0_counters.owner_table_full_reject_total == 0u);
    assert(owner0_counters.fallback_private_issue_total == 1u);

    assert(owner1_counters.frontier_export_total == 1u);
    assert(owner1_counters.guard_drop_total == 0u);
    assert(owner1_counters.owner_lookup_total == 1u);
    assert(owner1_counters.owner_alloc_total == 0u);
    assert(owner1_counters.owner_reject_total == 1u);
    assert(owner1_counters.owner_disabled_reject_total == 0u);
    assert(owner1_counters.owner_invalid_pod_reject_total == 0u);
    assert(owner1_counters.owner_table_full_reject_total == 1u);
    assert(owner1_counters.join_request_total == 0u);
    assert(owner1_counters.join_reject_total == 0u);
    assert(owner1_counters.join_table_full_reject_total == 0u);
    assert(owner1_counters.duplicate_metadata_replay_elided_total == 0u);
    assert(owner1_counters.duplicate_metadata_issue_elided_total == 0u);
    assert(owner1_counters.fallback_private_issue_total == 1u);

    const auto fabric_stats = fabric.snapshotStats();
    assert(fabric_stats.control_messages_enqueued_total == 4u);
    assert(fabric_stats.control_frontier_export_total == 2u);
    assert(fabric_stats.control_owner_announce_total == 1u);
    assert(fabric_stats.control_join_request_total == 0u);
    assert(fabric_stats.control_join_reject_total == 1u);
}

void test_shadow_gate_join_table_full_rejects_younger_joiner() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_table_cfg{};
    owner_table_cfg.enable = true;
    owner_table_cfg.num_pods = 1;
    owner_table_cfg.owner_entries_per_pod = 8;
    owner_table_cfg.join_entries_per_pod = 1;
    PodOwnerServiceTable owner_table(owner_table_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 3;
    PeSharedCoreFabric fabric(fabric_cfg);

    PeInternalPodShadowGateBindings bindings{};
    bindings.metadata_plane = &metadata_plane;
    bindings.owner_table = &owner_table;
    bindings.fabric = &fabric;

    PeInternalPodShadowGateConfig owner_cfg{};
    PeInternalPodShadowGateConfig joiner1_cfg{};
    PeInternalPodShadowGateConfig joiner2_cfg{};
    configureShadowGate(owner_cfg, 0u, 0u);
    configureShadowGate(joiner1_cfg, 1u, 0u);
    configureShadowGate(joiner2_cfg, 2u, 0u);

    PeInternalPodShadowGateCounters owner_counters{};
    PeInternalPodShadowGateCounters joiner1_counters{};
    PeInternalPodShadowGateCounters joiner2_counters{};

    PeInternalPodShadowGate::observe(
        owner_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        16u,
        owner_counters);
    PeInternalPodShadowGate::observe(
        joiner1_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        16u,
        joiner1_counters);
    PeInternalPodShadowGate::observe(
        joiner2_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        16u,
        joiner2_counters);

    const auto metadata_stats = metadata_plane.snapshotStats();
    assert(metadata_stats.observe_total == 3u);
    assert(metadata_stats.unique_object_total == 1u);
    assert(metadata_stats.overlap_hit_total == 2u);
    assert(metadata_stats.duplicate_consumer_total == 0u);

    const auto owner_stats = owner_table.snapshotStats();
    assert(owner_stats.lookup_total == 3u);
    assert(owner_stats.owner_alloc_total == 1u);
    assert(owner_stats.owner_hit_total == 2u);
    assert(owner_stats.owner_reject_total == 0u);
    assert(owner_stats.join_request_total == 2u);
    assert(owner_stats.join_grant_total == 1u);
    assert(owner_stats.join_reject_total == 1u);

    assert(joiner1_counters.owner_hit_total == 1u);
    assert(joiner1_counters.guard_drop_total == 0u);
    assert(joiner1_counters.join_request_total == 1u);
    assert(joiner1_counters.join_grant_total == 1u);
    assert(joiner1_counters.join_reject_total == 0u);
    assert(joiner1_counters.join_duplicate_consumer_reject_total == 0u);
    assert(joiner1_counters.join_table_full_reject_total == 0u);
    assert(joiner1_counters.join_before_private_issue_total == 1u);
    assert(joiner1_counters.duplicate_metadata_replay_elided_total == 0u);
    assert(joiner1_counters.duplicate_metadata_issue_elided_total == 1u);
    assert(joiner1_counters.fallback_private_issue_total == 1u);

    assert(joiner2_counters.owner_hit_total == 1u);
    assert(joiner2_counters.guard_drop_total == 0u);
    assert(joiner2_counters.join_request_total == 1u);
    assert(joiner2_counters.join_grant_total == 0u);
    assert(joiner2_counters.join_reject_total == 1u);
    assert(joiner2_counters.join_duplicate_consumer_reject_total == 0u);
    assert(joiner2_counters.join_table_full_reject_total == 1u);
    assert(joiner2_counters.join_before_private_issue_total == 0u);
    assert(joiner2_counters.duplicate_metadata_replay_elided_total == 0u);
    assert(joiner2_counters.duplicate_metadata_issue_elided_total == 0u);
    assert(joiner2_counters.fallback_private_issue_total == 1u);

    const auto fabric_stats = fabric.snapshotStats();
    assert(fabric_stats.control_messages_enqueued_total == 7u);
    assert(fabric_stats.control_frontier_export_total == 3u);
    assert(fabric_stats.control_owner_announce_total == 1u);
    assert(fabric_stats.control_join_request_total == 2u);
    assert(fabric_stats.control_join_reject_total == 1u);
}

void test_shadow_gate_invalid_pod_does_not_clamp_into_neighbor_pod() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 2;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_table_cfg{};
    owner_table_cfg.enable = true;
    owner_table_cfg.num_pods = 2;
    owner_table_cfg.owner_entries_per_pod = 8;
    owner_table_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_table_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    PeInternalPodShadowGateBindings bindings{};
    bindings.metadata_plane = &metadata_plane;
    bindings.owner_table = &owner_table;
    bindings.fabric = &fabric;

    PeInternalPodShadowGateConfig invalid_cfg{};
    configureShadowGate(invalid_cfg, 0u, 7u);
    invalid_cfg.pod_count = 2u;

    PeInternalPodShadowGateCounters counters{};
    PeInternalPodShadowGate::observe(
        invalid_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        16u,
        counters);

    const auto metadata_stats = metadata_plane.snapshotStats();
    assert(metadata_stats.observe_total == 0u);
    assert(metadata_stats.unique_object_total == 0u);

    const auto owner_stats = owner_table.snapshotStats();
    assert(owner_stats.lookup_total == 0u);
    assert(owner_stats.owner_alloc_total == 0u);
    assert(owner_stats.owner_hit_total == 0u);
    assert(owner_stats.join_request_total == 0u);

    assert(counters.frontier_export_total == 0u);
    assert(counters.guard_drop_total == 1u);
    assert(counters.guard_disabled_total == 0u);
    assert(counters.guard_missing_metadata_plane_total == 0u);
    assert(counters.guard_missing_owner_table_total == 0u);
    assert(counters.guard_zero_pod_count_total == 0u);
    assert(counters.guard_window_zero_total == 0u);
    assert(counters.guard_invalid_cfg_pod_total == 1u);
    assert(counters.owner_lookup_total == 0u);
    assert(counters.owner_alloc_total == 0u);
    assert(counters.owner_hit_total == 0u);
    assert(counters.owner_reject_total == 0u);
    assert(counters.join_request_total == 0u);
    assert(counters.join_reject_total == 0u);
    assert(counters.duplicate_metadata_replay_elided_total == 0u);
    assert(counters.duplicate_metadata_issue_elided_total == 0u);
    assert(counters.fallback_private_issue_total == 0u);

    const auto fabric_stats = fabric.snapshotStats();
    assert(fabric_stats.control_messages_enqueued_total == 0u);
}

void test_shadow_gate_join_table_disabled_short_circuits_before_join_request() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_table_cfg{};
    owner_table_cfg.enable = true;
    owner_table_cfg.num_pods = 1;
    owner_table_cfg.owner_entries_per_pod = 8;
    owner_table_cfg.join_entries_per_pod = 0;
    PodOwnerServiceTable owner_table(owner_table_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    PeInternalPodShadowGateBindings bindings{};
    bindings.metadata_plane = &metadata_plane;
    bindings.owner_table = &owner_table;
    bindings.fabric = &fabric;

    PeInternalPodShadowGateConfig owner_cfg{};
    PeInternalPodShadowGateConfig joiner_cfg{};
    configureShadowGate(owner_cfg, 0u, 0u);
    configureShadowGate(joiner_cfg, 1u, 0u);

    PeInternalPodShadowGateCounters owner_counters{};
    PeInternalPodShadowGateCounters joiner_counters{};

    PeInternalPodShadowGate::observe(
        owner_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        16u,
        owner_counters);
    PeInternalPodShadowGate::observe(
        joiner_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        16u,
        joiner_counters);

    const auto metadata_stats = metadata_plane.snapshotStats();
    assert(metadata_stats.observe_total == 2u);
    assert(metadata_stats.unique_object_total == 1u);
    assert(metadata_stats.overlap_hit_total == 1u);
    assert(metadata_stats.duplicate_consumer_total == 0u);

    const auto owner_stats = owner_table.snapshotStats();
    assert(owner_stats.lookup_total == 2u);
    assert(owner_stats.owner_alloc_total == 1u);
    assert(owner_stats.owner_hit_total == 1u);
    assert(owner_stats.owner_reject_total == 0u);
    assert(owner_stats.join_request_total == 0u);
    assert(owner_stats.join_grant_total == 0u);
    assert(owner_stats.join_reject_total == 0u);

    assert(owner_counters.owner_alloc_total == 1u);
    assert(owner_counters.guard_drop_total == 0u);
    assert(owner_counters.owner_disabled_reject_total == 0u);
    assert(owner_counters.owner_table_full_reject_total == 0u);
    assert(owner_counters.fallback_private_issue_total == 1u);

    assert(joiner_counters.frontier_export_total == 1u);
    assert(joiner_counters.guard_drop_total == 0u);
    assert(joiner_counters.owner_lookup_total == 1u);
    assert(joiner_counters.owner_hit_total == 1u);
    assert(joiner_counters.join_request_total == 0u);
    assert(joiner_counters.join_grant_total == 0u);
    assert(joiner_counters.join_reject_total == 1u);
    assert(joiner_counters.join_duplicate_consumer_reject_total == 0u);
    assert(joiner_counters.join_table_disabled_reject_total == 1u);
    assert(joiner_counters.join_table_full_reject_total == 0u);
    assert(joiner_counters.join_before_private_issue_total == 0u);
    assert(joiner_counters.useful_total == 0u);
    assert(joiner_counters.useful_join_grant_total == 0u);
    assert(joiner_counters.useful_duplicate_replay_elide_total == 0u);
    assert(joiner_counters.attempted_total == 1u);
    assert(joiner_counters.attempted_guard_total == 0u);
    assert(joiner_counters.attempted_reject_total == 1u);
    assert(joiner_counters.attempted_useful_total == 0u);
    assert(joiner_counters.reject_base_total == 1u);
    assert(joiner_counters.reject_band_total == 0u);
    assert(joiner_counters.reject_other_total == 0u);
    assert(joiner_counters.attempted_base_total == 1u);
    assert(joiner_counters.attempted_band_total == 0u);
    assert(joiner_counters.attempted_other_total == 0u);
    assert(joiner_counters.duplicate_metadata_replay_elided_total == 0u);
    assert(joiner_counters.duplicate_metadata_issue_elided_total == 0u);
    assert(joiner_counters.fallback_private_issue_total == 1u);

    const auto fabric_stats = fabric.snapshotStats();
    assert(fabric_stats.control_messages_enqueued_total == 4u);
    assert(fabric_stats.control_frontier_export_total == 2u);
    assert(fabric_stats.control_owner_announce_total == 1u);
    assert(fabric_stats.control_join_request_total == 0u);
    assert(fabric_stats.control_join_reject_total == 1u);
}

void test_shadow_gate_window_zero_is_noop() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_table_cfg{};
    owner_table_cfg.enable = true;
    owner_table_cfg.num_pods = 1;
    owner_table_cfg.owner_entries_per_pod = 8;
    owner_table_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_table_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    PeInternalPodShadowGateBindings bindings{};
    bindings.metadata_plane = &metadata_plane;
    bindings.owner_table = &owner_table;
    bindings.fabric = &fabric;

    PeInternalPodShadowGateConfig cfg{};
    configureShadowGate(cfg, 0u, 0u);
    cfg.window_seq = 0u;

    PeInternalPodShadowGateCounters counters{};
    PeInternalPodShadowGate::observe(
        cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        16u,
        counters);

    const auto metadata_stats = metadata_plane.snapshotStats();
    assert(metadata_stats.observe_total == 0u);
    assert(metadata_stats.unique_object_total == 0u);

    const auto owner_stats = owner_table.snapshotStats();
    assert(owner_stats.lookup_total == 0u);
    assert(owner_stats.join_request_total == 0u);

    assert(counters.frontier_export_total == 0u);
    assert(counters.guard_drop_total == 1u);
    assert(counters.guard_disabled_total == 0u);
    assert(counters.guard_missing_metadata_plane_total == 0u);
    assert(counters.guard_missing_owner_table_total == 0u);
    assert(counters.guard_zero_pod_count_total == 0u);
    assert(counters.guard_window_zero_total == 1u);
    assert(counters.guard_invalid_cfg_pod_total == 0u);
    assert(counters.owner_lookup_total == 0u);
    assert(counters.join_request_total == 0u);
    assert(counters.join_reject_total == 0u);
    assert(counters.owner_disabled_reject_total == 0u);
    assert(counters.owner_table_full_reject_total == 0u);
    assert(counters.join_table_full_reject_total == 0u);
    assert(counters.fallback_private_issue_total == 0u);

    const auto fabric_stats = fabric.snapshotStats();
    assert(fabric_stats.control_messages_enqueued_total == 0u);
}

void test_shadow_gate_zero_pod_count_is_noop() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_table_cfg{};
    owner_table_cfg.enable = true;
    owner_table_cfg.num_pods = 1;
    owner_table_cfg.owner_entries_per_pod = 8;
    owner_table_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_table_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    PeInternalPodShadowGateBindings bindings{};
    bindings.metadata_plane = &metadata_plane;
    bindings.owner_table = &owner_table;
    bindings.fabric = &fabric;

    PeInternalPodShadowGateConfig cfg{};
    configureShadowGate(cfg, 0u, 0u);
    cfg.pod_count = 0u;

    PeInternalPodShadowGateCounters counters{};
    PeInternalPodShadowGate::observe(
        cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        16u,
        counters);

    const auto metadata_stats = metadata_plane.snapshotStats();
    assert(metadata_stats.observe_total == 0u);
    assert(metadata_stats.unique_object_total == 0u);

    const auto owner_stats = owner_table.snapshotStats();
    assert(owner_stats.lookup_total == 0u);
    assert(owner_stats.join_request_total == 0u);

    assert(counters.frontier_export_total == 0u);
    assert(counters.guard_drop_total == 1u);
    assert(counters.guard_disabled_total == 0u);
    assert(counters.guard_missing_metadata_plane_total == 0u);
    assert(counters.guard_missing_owner_table_total == 0u);
    assert(counters.guard_zero_pod_count_total == 1u);
    assert(counters.guard_window_zero_total == 0u);
    assert(counters.guard_invalid_cfg_pod_total == 0u);
    assert(counters.owner_lookup_total == 0u);
    assert(counters.join_request_total == 0u);
    assert(counters.join_reject_total == 0u);
    assert(counters.owner_disabled_reject_total == 0u);
    assert(counters.owner_table_full_reject_total == 0u);
    assert(counters.join_table_full_reject_total == 0u);
    assert(counters.fallback_private_issue_total == 0u);

    const auto fabric_stats = fabric.snapshotStats();
    assert(fabric_stats.control_messages_enqueued_total == 0u);
}

void test_shadow_gate_null_owner_binding_is_noop() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    PeInternalPodShadowGateBindings bindings{};
    bindings.metadata_plane = &metadata_plane;
    bindings.owner_table = nullptr;
    bindings.fabric = &fabric;

    PeInternalPodShadowGateConfig cfg{};
    configureShadowGate(cfg, 0u, 0u);

    PeInternalPodShadowGateCounters counters{};
    PeInternalPodShadowGate::observe(
        cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        16u,
        counters);

    const auto metadata_stats = metadata_plane.snapshotStats();
    assert(metadata_stats.observe_total == 0u);
    assert(metadata_stats.unique_object_total == 0u);

    assert(counters.frontier_export_total == 0u);
    assert(counters.guard_drop_total == 1u);
    assert(counters.guard_disabled_total == 0u);
    assert(counters.guard_missing_metadata_plane_total == 0u);
    assert(counters.guard_missing_owner_table_total == 1u);
    assert(counters.guard_zero_pod_count_total == 0u);
    assert(counters.guard_window_zero_total == 0u);
    assert(counters.guard_invalid_cfg_pod_total == 0u);
    assert(counters.owner_lookup_total == 0u);
    assert(counters.join_request_total == 0u);
    assert(counters.join_reject_total == 0u);
    assert(counters.owner_disabled_reject_total == 0u);
    assert(counters.owner_table_full_reject_total == 0u);
    assert(counters.join_table_full_reject_total == 0u);
    assert(counters.fallback_private_issue_total == 0u);

    const auto fabric_stats = fabric.snapshotStats();
    assert(fabric_stats.control_messages_enqueued_total == 0u);
}

void test_shadow_gate_null_metadata_binding_is_noop() {
    PodOwnerServiceTable::Config owner_table_cfg{};
    owner_table_cfg.enable = true;
    owner_table_cfg.num_pods = 1;
    owner_table_cfg.owner_entries_per_pod = 8;
    owner_table_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_table_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    PeInternalPodShadowGateBindings bindings{};
    bindings.metadata_plane = nullptr;
    bindings.owner_table = &owner_table;
    bindings.fabric = &fabric;

    PeInternalPodShadowGateConfig cfg{};
    configureShadowGate(cfg, 0u, 0u);

    PeInternalPodShadowGateCounters counters{};
    PeInternalPodShadowGate::observe(
        cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        16u,
        counters);

    const auto owner_stats = owner_table.snapshotStats();
    assert(owner_stats.lookup_total == 0u);
    assert(owner_stats.join_request_total == 0u);

    assert(counters.frontier_export_total == 0u);
    assert(counters.guard_drop_total == 1u);
    assert(counters.guard_disabled_total == 0u);
    assert(counters.guard_missing_metadata_plane_total == 1u);
    assert(counters.guard_missing_owner_table_total == 0u);
    assert(counters.guard_zero_pod_count_total == 0u);
    assert(counters.guard_window_zero_total == 0u);
    assert(counters.guard_invalid_cfg_pod_total == 0u);
    assert(counters.owner_lookup_total == 0u);
    assert(counters.join_request_total == 0u);
    assert(counters.join_reject_total == 0u);
    assert(counters.join_table_disabled_reject_total == 0u);
    assert(counters.owner_disabled_reject_total == 0u);
    assert(counters.owner_table_full_reject_total == 0u);
    assert(counters.join_table_full_reject_total == 0u);
    assert(counters.fallback_private_issue_total == 0u);

    const auto fabric_stats = fabric.snapshotStats();
    assert(fabric_stats.control_messages_enqueued_total == 0u);
}

void test_shadow_gate_null_fabric_binding_keeps_local_shadow_state() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_table_cfg{};
    owner_table_cfg.enable = true;
    owner_table_cfg.num_pods = 1;
    owner_table_cfg.owner_entries_per_pod = 8;
    owner_table_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_table_cfg);

    PeInternalPodShadowGateBindings bindings{};
    bindings.metadata_plane = &metadata_plane;
    bindings.owner_table = &owner_table;
    bindings.fabric = nullptr;

    PeInternalPodShadowGateConfig owner_cfg{};
    PeInternalPodShadowGateConfig joiner_cfg{};
    configureShadowGate(owner_cfg, 0u, 0u);
    configureShadowGate(joiner_cfg, 1u, 0u);

    PeInternalPodShadowGateCounters owner_counters{};
    PeInternalPodShadowGateCounters joiner_counters{};

    PeInternalPodShadowGate::observe(
        owner_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        16u,
        owner_counters);
    PeInternalPodShadowGate::observe(
        joiner_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        16u,
        joiner_counters);

    const auto metadata_stats = metadata_plane.snapshotStats();
    assert(metadata_stats.observe_total == 2u);
    assert(metadata_stats.unique_object_total == 1u);
    assert(metadata_stats.overlap_hit_total == 1u);

    const auto owner_stats = owner_table.snapshotStats();
    assert(owner_stats.lookup_total == 2u);
    assert(owner_stats.owner_alloc_total == 1u);
    assert(owner_stats.owner_hit_total == 1u);
    assert(owner_stats.join_request_total == 1u);
    assert(owner_stats.join_grant_total == 1u);
    assert(owner_stats.join_reject_total == 0u);

    assert(owner_counters.frontier_export_total == 1u);
    assert(owner_counters.guard_drop_total == 0u);
    assert(owner_counters.owner_alloc_total == 1u);
    assert(owner_counters.join_request_total == 0u);
    assert(owner_counters.join_table_disabled_reject_total == 0u);
    assert(owner_counters.owner_disabled_reject_total == 0u);
    assert(owner_counters.owner_table_full_reject_total == 0u);
    assert(owner_counters.join_table_full_reject_total == 0u);
    assert(owner_counters.fallback_private_issue_total == 1u);

    assert(joiner_counters.frontier_export_total == 1u);
    assert(joiner_counters.guard_drop_total == 0u);
    assert(joiner_counters.owner_hit_total == 1u);
    assert(joiner_counters.join_request_total == 1u);
    assert(joiner_counters.join_grant_total == 1u);
    assert(joiner_counters.join_reject_total == 0u);
    assert(joiner_counters.join_table_disabled_reject_total == 0u);
    assert(joiner_counters.owner_disabled_reject_total == 0u);
    assert(joiner_counters.owner_table_full_reject_total == 0u);
    assert(joiner_counters.join_table_full_reject_total == 0u);
    assert(joiner_counters.join_before_private_issue_total == 1u);
    assert(joiner_counters.duplicate_metadata_issue_elided_total == 1u);
    assert(joiner_counters.fallback_private_issue_total == 1u);
}

void test_shadow_gate_owner_table_disabled_rejects_with_reason_split() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_table_cfg{};
    owner_table_cfg.enable = false;
    owner_table_cfg.num_pods = 1;
    owner_table_cfg.owner_entries_per_pod = 8;
    owner_table_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_table_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    PeInternalPodShadowGateBindings bindings{};
    bindings.metadata_plane = &metadata_plane;
    bindings.owner_table = &owner_table;
    bindings.fabric = &fabric;

    PeInternalPodShadowGateConfig cfg{};
    configureShadowGate(cfg, 0u, 0u);

    PeInternalPodShadowGateCounters counters{};
    PeInternalPodShadowGate::observe(
        cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        16u,
        counters);

    const auto metadata_stats = metadata_plane.snapshotStats();
    assert(metadata_stats.observe_total == 1u);
    assert(metadata_stats.unique_object_total == 1u);
    assert(metadata_stats.overlap_hit_total == 0u);

    const auto owner_stats = owner_table.snapshotStats();
    assert(owner_stats.lookup_total == 1u);
    assert(owner_stats.owner_alloc_total == 0u);
    assert(owner_stats.owner_hit_total == 0u);
    assert(owner_stats.owner_reject_total == 1u);
    assert(owner_stats.join_request_total == 0u);
    assert(owner_stats.join_reject_total == 0u);

    assert(counters.frontier_export_total == 1u);
    assert(counters.guard_drop_total == 0u);
    assert(counters.owner_lookup_total == 1u);
    assert(counters.owner_alloc_total == 0u);
    assert(counters.owner_hit_total == 0u);
    assert(counters.owner_reject_total == 1u);
    assert(counters.owner_disabled_reject_total == 1u);
    assert(counters.owner_invalid_pod_reject_total == 0u);
    assert(counters.owner_table_full_reject_total == 0u);
    assert(counters.join_request_total == 0u);
    assert(counters.join_reject_total == 0u);
    assert(counters.join_table_disabled_reject_total == 0u);
    assert(counters.join_duplicate_consumer_reject_total == 0u);
    assert(counters.join_table_full_reject_total == 0u);
    assert(counters.fallback_private_issue_total == 1u);

    const auto fabric_stats = fabric.snapshotStats();
    assert(fabric_stats.control_messages_enqueued_total == 2u);
    assert(fabric_stats.control_frontier_export_total == 1u);
    assert(fabric_stats.control_owner_announce_total == 0u);
    assert(fabric_stats.control_join_request_total == 0u);
    assert(fabric_stats.control_join_reject_total == 1u);
}

void test_shadow_gate_owner_table_invalid_pod_rejects_with_reason_split() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 2;
    metadata_cfg.capacity_entries_per_pod = 8;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_table_cfg{};
    owner_table_cfg.enable = true;
    owner_table_cfg.num_pods = 1;
    owner_table_cfg.owner_entries_per_pod = 8;
    owner_table_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_table_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    PeInternalPodShadowGateBindings bindings{};
    bindings.metadata_plane = &metadata_plane;
    bindings.owner_table = &owner_table;
    bindings.fabric = &fabric;

    PeInternalPodShadowGateConfig cfg{};
    configureShadowGate(cfg, 0u, 1u);
    cfg.pod_count = 2u;

    PeInternalPodShadowGateCounters counters{};
    PeInternalPodShadowGate::observe(
        cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        16u,
        counters);

    const auto metadata_stats = metadata_plane.snapshotStats();
    assert(metadata_stats.observe_total == 1u);
    assert(metadata_stats.unique_object_total == 1u);
    assert(metadata_stats.overlap_hit_total == 0u);

    const auto owner_stats = owner_table.snapshotStats();
    assert(owner_stats.lookup_total == 1u);
    assert(owner_stats.owner_alloc_total == 0u);
    assert(owner_stats.owner_hit_total == 0u);
    assert(owner_stats.owner_reject_total == 1u);
    assert(owner_stats.join_request_total == 0u);
    assert(owner_stats.join_reject_total == 0u);

    assert(counters.frontier_export_total == 1u);
    assert(counters.guard_drop_total == 0u);
    assert(counters.owner_lookup_total == 1u);
    assert(counters.owner_alloc_total == 0u);
    assert(counters.owner_hit_total == 0u);
    assert(counters.owner_reject_total == 1u);
    assert(counters.owner_disabled_reject_total == 0u);
    assert(counters.owner_invalid_pod_reject_total == 1u);
    assert(counters.owner_table_full_reject_total == 0u);
    assert(counters.join_request_total == 0u);
    assert(counters.join_reject_total == 0u);
    assert(counters.join_duplicate_consumer_reject_total == 0u);
    assert(counters.join_table_disabled_reject_total == 0u);
    assert(counters.join_table_full_reject_total == 0u);
    assert(counters.fallback_private_issue_total == 1u);

    const auto fabric_stats = fabric.snapshotStats();
    assert(fabric_stats.control_messages_enqueued_total == 2u);
    assert(fabric_stats.control_frontier_export_total == 1u);
    assert(fabric_stats.control_owner_announce_total == 0u);
    assert(fabric_stats.control_join_request_total == 0u);
    assert(fabric_stats.control_join_reject_total == 1u);
}

void test_shadow_gate_late_duplicate_join_counts_reason_split() {
    PodMetadataObjectPlane::Config metadata_cfg{};
    metadata_cfg.enable = true;
    metadata_cfg.num_pods = 1;
    metadata_cfg.capacity_entries_per_pod = 1;
    PodMetadataObjectPlane metadata_plane(metadata_cfg);

    PodOwnerServiceTable::Config owner_table_cfg{};
    owner_table_cfg.enable = true;
    owner_table_cfg.num_pods = 1;
    owner_table_cfg.owner_entries_per_pod = 8;
    owner_table_cfg.join_entries_per_pod = 8;
    PodOwnerServiceTable owner_table(owner_table_cfg);

    PeSharedCoreFabric::Config fabric_cfg{};
    fabric_cfg.enable = true;
    fabric_cfg.observe_only = false;
    fabric_cfg.num_cores = 2;
    PeSharedCoreFabric fabric(fabric_cfg);

    PeInternalPodShadowGateBindings bindings{};
    bindings.metadata_plane = &metadata_plane;
    bindings.owner_table = &owner_table;
    bindings.fabric = &fabric;

    PeInternalPodShadowGateConfig owner_cfg{};
    PeInternalPodShadowGateConfig joiner_cfg{};
    configureShadowGate(owner_cfg, 0u, 0u);
    configureShadowGate(joiner_cfg, 1u, 0u);

    PeInternalPodShadowGateCounters owner_counters{};
    PeInternalPodShadowGateCounters joiner_counters{};

    PeInternalPodShadowGate::observe(
        owner_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        16u,
        owner_counters);
    PeInternalPodShadowGate::observe(
        joiner_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        16u,
        joiner_counters);
    PeInternalPodShadowGate::observe(
        owner_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        32u,
        owner_counters);
    PeInternalPodShadowGate::observe(
        joiner_cfg,
        bindings,
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        16u,
        joiner_counters);

    const auto metadata_stats = metadata_plane.snapshotStats();
    assert(metadata_stats.observe_total == 4u);
    assert(metadata_stats.unique_object_total == 3u);
    assert(metadata_stats.overlap_hit_total == 1u);
    assert(metadata_stats.duplicate_consumer_total == 0u);
    assert(metadata_stats.evict_total == 2u);

    const auto owner_stats = owner_table.snapshotStats();
    assert(owner_stats.lookup_total == 4u);
    assert(owner_stats.owner_alloc_total == 2u);
    assert(owner_stats.owner_hit_total == 2u);
    assert(owner_stats.owner_reject_total == 0u);
    assert(owner_stats.join_request_total == 2u);
    assert(owner_stats.join_grant_total == 1u);
    assert(owner_stats.join_reject_total == 0u);

    assert(joiner_counters.frontier_export_total == 2u);
    assert(joiner_counters.guard_drop_total == 0u);
    assert(joiner_counters.owner_lookup_total == 2u);
    assert(joiner_counters.owner_hit_total == 2u);
    assert(joiner_counters.join_request_total == 2u);
    assert(joiner_counters.join_grant_total == 1u);
    assert(joiner_counters.join_reject_total == 1u);
    assert(joiner_counters.join_duplicate_consumer_reject_total == 1u);
    assert(joiner_counters.join_table_disabled_reject_total == 0u);
    assert(joiner_counters.join_table_full_reject_total == 0u);
    assert(joiner_counters.duplicate_metadata_replay_elided_total == 0u);
    assert(joiner_counters.duplicate_metadata_issue_elided_total == 1u);
    assert(joiner_counters.fallback_private_issue_total == 2u);

    const auto fabric_stats = fabric.snapshotStats();
    assert(fabric_stats.control_messages_enqueued_total == 9u);
    assert(fabric_stats.control_frontier_export_total == 4u);
    assert(fabric_stats.control_owner_announce_total == 2u);
    assert(fabric_stats.control_join_request_total == 2u);
    assert(fabric_stats.control_join_reject_total == 1u);
}

} // namespace

int main(int argc, char** argv) {
    (void)argc;
    (void)argv;
    test_shadow_gate_allocates_owner_then_records_join();
    test_shadow_gate_elides_duplicate_metadata_before_owner_lookup();
    test_shadow_gate_elides_duplicate_joiner_metadata_before_join();
    test_shadow_gate_tracks_row_index_as_other_shape();
    test_shadow_gate_tracks_row_descriptor_as_other_subkind();
    test_shadow_gate_disabled_config_is_noop();
    test_shadow_gate_owner_table_full_falls_back_with_reject();
    test_shadow_gate_join_table_full_rejects_younger_joiner();
    test_shadow_gate_invalid_pod_does_not_clamp_into_neighbor_pod();
    test_shadow_gate_join_table_disabled_short_circuits_before_join_request();
    test_shadow_gate_window_zero_is_noop();
    test_shadow_gate_zero_pod_count_is_noop();
    test_shadow_gate_null_owner_binding_is_noop();
    test_shadow_gate_null_metadata_binding_is_noop();
    test_shadow_gate_null_fabric_binding_keeps_local_shadow_state();
    test_shadow_gate_owner_table_disabled_rejects_with_reason_split();
    test_shadow_gate_owner_table_invalid_pod_rejects_with_reason_split();
    test_shadow_gate_late_duplicate_join_counts_reason_split();
    return 0;
}
