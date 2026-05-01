#include <cassert>
#include <cstdint>
#include <map>
#include <string>

#include "api/IPeWeightObjectPlaneProvider.h"
#include "services/local_storage/LocalStorageHierarchyController.h"
#include "services/local_storage/PeLocalServiceObjectTable.h"
#include "services/local_storage/PodMetadataObjectPlane.h"
#include "services/local_storage/PodOwnerServiceTable.h"
#include "services/local_storage/PeWeightObjectPlane.h"

using SST::SnnDL::IPeWeightObjectPlaneProvider;
using SST::SnnDL::LocalStorageHierarchyController;
using SST::SnnDL::LocalStorageObjectConfig;
using SST::SnnDL::LocalStorageObjectKind;
using SST::SnnDL::LocalStorageScope;
using SST::SnnDL::PeLocalServiceObjectTable;
using SST::SnnDL::PeWeightObjectPlane;
using SST::SnnDL::PhaseALocalStorageRegistrationConfig;
using SST::SnnDL::PodMetadataObjectPlane;
using SST::SnnDL::PodOwnerServiceTable;
using SST::SnnDL::registerDefaultPhaseAObjects;

static void test_basic_registration_and_snapshot() {
    LocalStorageHierarchyController::Config cfg{};
    cfg.enable = true;
    cfg.num_cores = 4;

    LocalStorageHierarchyController controller(cfg);

    LocalStorageObjectConfig state{};
    state.name = "state_store.core0";
    state.kind = LocalStorageObjectKind::AddressableStore;
    state.scope = LocalStorageScope::PerCore;
    state.enable = true;
    state.capacity_bytes = 4096;
    state.banks = 4;
    state.read_ports = 1;
    state.write_ports = 1;
    state.update_ports = 1;

    assert(controller.registerObject(state));
    assert(!controller.registerObject(state));

    const auto snapshot = controller.snapshotStats();
    assert(snapshot.objects_registered_total == 1u);
    assert(snapshot.objects_enabled_total == 1u);
    assert(snapshot.capacity_bytes_total == 4096u);
    assert(snapshot.queue_slots_total == 0u);
}

static void test_disabled_object_does_not_count_as_enabled() {
    LocalStorageHierarchyController::Config cfg{};
    cfg.enable = true;

    LocalStorageHierarchyController controller(cfg);

    LocalStorageObjectConfig weight{};
    weight.name = "weight_idx_store";
    weight.kind = LocalStorageObjectKind::AddressableStore;
    weight.scope = LocalStorageScope::PerPe;
    weight.enable = true;
    weight.capacity_bytes = 0;

    assert(controller.registerObject(weight));

    const auto snapshot = controller.snapshotStats();
    assert(snapshot.objects_registered_total == 1u);
    assert(snapshot.objects_enabled_total == 0u);
    assert(snapshot.capacity_bytes_total == 0u);
}

static void test_phase_a_default_registration_layout() {
    LocalStorageHierarchyController::Config cfg{};
    cfg.enable = true;
    cfg.num_cores = 2;

    LocalStorageHierarchyController controller(cfg);

    PhaseALocalStorageRegistrationConfig phase_cfg{};
    phase_cfg.num_cores = 2;

    phase_cfg.activation_ingress.name = "activation_ingress_store";
    phase_cfg.activation_ingress.kind = LocalStorageObjectKind::QueueStore;
    phase_cfg.activation_ingress.scope = LocalStorageScope::PerPe;
    phase_cfg.activation_ingress.enable = true;
    phase_cfg.activation_ingress.queue_depth = 32;

    phase_cfg.weight_idx.name = "weight_idx_store";
    phase_cfg.weight_idx.kind = LocalStorageObjectKind::AddressableStore;
    phase_cfg.weight_idx.scope = LocalStorageScope::PerPe;
    phase_cfg.weight_idx.enable = true;
    phase_cfg.weight_idx.capacity_bytes = 128;

    phase_cfg.weight_value.name = "weight_value_store";
    phase_cfg.weight_value.kind = LocalStorageObjectKind::AddressableStore;
    phase_cfg.weight_value.scope = LocalStorageScope::PerPe;
    phase_cfg.weight_value.enable = true;
    phase_cfg.weight_value.capacity_bytes = 256;

    phase_cfg.state_template.name = "state_store";
    phase_cfg.state_template.kind = LocalStorageObjectKind::AddressableStore;
    phase_cfg.state_template.scope = LocalStorageScope::PerCore;
    phase_cfg.state_template.enable = true;
    phase_cfg.state_template.capacity_bytes = 512;

    phase_cfg.activation_core_template.name = "activation_core_queue";
    phase_cfg.activation_core_template.kind = LocalStorageObjectKind::QueueStore;
    phase_cfg.activation_core_template.scope = LocalStorageScope::PerCore;
    phase_cfg.activation_core_template.enable = true;
    phase_cfg.activation_core_template.queue_depth = 16;

    phase_cfg.acc_template.name = "accumulator_store";
    phase_cfg.acc_template.kind = LocalStorageObjectKind::AddressableStore;
    phase_cfg.acc_template.scope = LocalStorageScope::PerCore;
    phase_cfg.acc_template.enable = true;
    phase_cfg.acc_template.capacity_bytes = 1024;

    phase_cfg.rf_template.name = "register_file";
    phase_cfg.rf_template.kind = LocalStorageObjectKind::RegisterFile;
    phase_cfg.rf_template.scope = LocalStorageScope::PerCore;
    phase_cfg.rf_template.enable = true;
    phase_cfg.rf_template.entries = 8;
    phase_cfg.rf_template.entry_bytes = 4;

    assert(registerDefaultPhaseAObjects(controller, phase_cfg));
    assert(controller.findObject("activation_ingress_store") != nullptr);
    assert(controller.findObject("weight_idx_store") != nullptr);
    assert(controller.findObject("weight_value_store") != nullptr);
    assert(controller.findObject("state_store.core0") != nullptr);
    assert(controller.findObject("state_store.core1") != nullptr);
    assert(controller.findObject("activation_core_queue.core0") != nullptr);
    assert(controller.findObject("activation_core_queue.core1") != nullptr);
    assert(controller.findObject("accumulator_store.core0") != nullptr);
    assert(controller.findObject("accumulator_store.core1") != nullptr);
    assert(controller.findObject("register_file.core0") != nullptr);
    assert(controller.findObject("register_file.core1") != nullptr);

    const auto snapshot = controller.snapshotStats();
    assert(snapshot.objects_registered_total == 11u);
    assert(snapshot.objects_enabled_total == 11u);
    assert(snapshot.capacity_bytes_total == 3520u);
    assert(snapshot.queue_slots_total == 64u);
}

static void test_phase_a_registers_per_pod_objects() {
    LocalStorageHierarchyController::Config cfg{};
    cfg.enable = true;
    cfg.num_cores = 4;

    LocalStorageHierarchyController controller(cfg);

    PhaseALocalStorageRegistrationConfig phase_cfg{};
    phase_cfg.num_cores = 4;
    phase_cfg.num_pods = 2;

    phase_cfg.pod_metadata_template.name = "pod_metadata_store";
    phase_cfg.pod_metadata_template.kind = LocalStorageObjectKind::AddressableStore;
    phase_cfg.pod_metadata_template.scope = LocalStorageScope::PerPod;
    phase_cfg.pod_metadata_template.enable = true;
    phase_cfg.pod_metadata_template.capacity_bytes = 64;
    phase_cfg.pod_metadata_template.banks = 2;

    phase_cfg.pod_owner_template.name = "pod_owner_table";
    phase_cfg.pod_owner_template.kind = LocalStorageObjectKind::AddressableStore;
    phase_cfg.pod_owner_template.scope = LocalStorageScope::PerPod;
    phase_cfg.pod_owner_template.enable = true;
    phase_cfg.pod_owner_template.capacity_bytes = 128;

    phase_cfg.pod_join_template.name = "pod_join_table";
    phase_cfg.pod_join_template.kind = LocalStorageObjectKind::AddressableStore;
    phase_cfg.pod_join_template.scope = LocalStorageScope::PerPod;
    phase_cfg.pod_join_template.enable = true;
    phase_cfg.pod_join_template.capacity_bytes = 256;

    phase_cfg.pod_ready_template.name = "pod_ready_table";
    phase_cfg.pod_ready_template.kind = LocalStorageObjectKind::QueueStore;
    phase_cfg.pod_ready_template.scope = LocalStorageScope::PerPod;
    phase_cfg.pod_ready_template.enable = true;
    phase_cfg.pod_ready_template.queue_depth = 8;

    assert(registerDefaultPhaseAObjects(controller, phase_cfg));

    const auto* pod_meta0 = controller.findObject("pod_metadata_store.pod0");
    const auto* pod_meta1 = controller.findObject("pod_metadata_store.pod1");
    const auto* pod_owner0 = controller.findObject("pod_owner_table.pod0");
    const auto* pod_join1 = controller.findObject("pod_join_table.pod1");
    const auto* pod_ready1 = controller.findObject("pod_ready_table.pod1");

    assert(pod_meta0 != nullptr);
    assert(pod_meta1 != nullptr);
    assert(pod_owner0 != nullptr);
    assert(pod_join1 != nullptr);
    assert(pod_ready1 != nullptr);
    assert(pod_meta0->scope == LocalStorageScope::PerPod);
    assert(pod_ready1->scope == LocalStorageScope::PerPod);

    const auto snapshot = controller.snapshotStats();
    assert(snapshot.objects_registered_total == 8u);
    assert(snapshot.objects_enabled_total == 8u);
    assert(snapshot.capacity_bytes_total == 896u);
    assert(snapshot.queue_slots_total == 16u);
}

static void test_pod_metadata_object_plane_tracks_overlap_per_pod_object() {
    PodMetadataObjectPlane::Config cfg{};
    cfg.enable = true;
    cfg.num_pods = 2;
    cfg.capacity_entries_per_pod = 8;

    PodMetadataObjectPlane plane(cfg);

    PodMetadataObjectPlane::ObserveRequest first{};
    first.pod_id = 0;
    first.window_seq = 7u;
    first.kind = PodMetadataObjectPlane::MetadataKind::PreMphfBase;
    first.object_id = 16u;
    first.core_id = 0u;

    const auto first_result = plane.observe(first);
    assert(first_result.accepted);
    assert(first_result.prior_consumers == 0u);
    assert(first_result.total_consumers == 1u);
    assert(!first_result.duplicate_consumer);

    auto second = first;
    second.core_id = 1u;
    const auto second_result = plane.observe(second);
    assert(second_result.accepted);
    assert(second_result.prior_consumers == 1u);
    assert(second_result.total_consumers == 2u);
    assert(!second_result.duplicate_consumer);

    const auto duplicate_result = plane.observe(second);
    assert(duplicate_result.accepted);
    assert(duplicate_result.prior_consumers == 2u);
    assert(duplicate_result.total_consumers == 2u);
    assert(duplicate_result.duplicate_consumer);

    const auto stats = plane.snapshotStats();
    assert(stats.observe_total == 3u);
    assert(stats.unique_object_total == 1u);
    assert(stats.overlap_hit_total == 1u);
    assert(stats.duplicate_consumer_total == 1u);
    assert(stats.active_entries_total == 1u);
}

static void test_pod_owner_service_table_allocates_owner_then_grants_join() {
    PodOwnerServiceTable::Config cfg{};
    cfg.enable = true;
    cfg.num_pods = 2;
    cfg.owner_entries_per_pod = 8;
    cfg.join_entries_per_pod = 8;

    PodOwnerServiceTable table(cfg);

    PodOwnerServiceTable::LookupRequest first{};
    first.pod_id = 0;
    first.window_seq = 11u;
    first.object_key = 0xabc0ull;
    first.core_id = 0u;

    const auto alloc = table.lookupOrAllocate(first);
    assert(alloc.valid);
    assert(alloc.allocated_owner);
    assert(!alloc.owner_hit);
    assert(alloc.owner_core_id == 0u);
    assert(alloc.transaction_id != 0u);
    assert(alloc.consumer_bitmap == 0x1ull);

    auto second = first;
    second.core_id = 1u;
    const auto hit = table.lookupOrAllocate(second);
    assert(hit.valid);
    assert(!hit.allocated_owner);
    assert(hit.owner_hit);
    assert(hit.owner_core_id == 0u);
    assert(hit.transaction_id == alloc.transaction_id);

    PodOwnerServiceTable::JoinRequest join{};
    join.pod_id = 0;
    join.window_seq = 11u;
    join.object_key = 0xabc0ull;
    join.consumer_core_id = 1u;

    const auto join_result = table.join(join);
    assert(join_result.valid);
    assert(join_result.granted);
    assert(!join_result.duplicate_consumer);
    assert(join_result.transaction_id == alloc.transaction_id);
    assert(join_result.consumer_bitmap == 0x3ull);

    const auto stats = table.snapshotStats();
    assert(stats.lookup_total == 2u);
    assert(stats.owner_alloc_total == 1u);
    assert(stats.owner_hit_total == 1u);
    assert(stats.join_request_total == 1u);
    assert(stats.join_grant_total == 1u);
    assert(stats.active_entries_total == 1u);
}

static void test_pod_owner_service_table_keeps_entries_across_window_skew() {
    PodOwnerServiceTable::Config cfg{};
    cfg.enable = true;
    cfg.num_pods = 1;
    cfg.owner_entries_per_pod = 8;
    cfg.join_entries_per_pod = 8;

    PodOwnerServiceTable table(cfg);

    PodOwnerServiceTable::LookupRequest owner{};
    owner.pod_id = 0;
    owner.window_seq = 11u;
    owner.object_key = 0x3300ull;
    owner.core_id = 0u;

    const auto owner_result = table.lookupOrAllocate(owner);
    assert(owner_result.valid);
    assert(owner_result.allocated_owner);

    auto foreign_window = owner;
    foreign_window.window_seq = 12u;
    foreign_window.object_key = 0x4400ull;
    foreign_window.core_id = 3u;

    const auto foreign_result = table.lookupOrAllocate(foreign_window);
    assert(foreign_result.valid);
    assert(foreign_result.allocated_owner);

    PodOwnerServiceTable::JoinRequest join{};
    join.pod_id = 0;
    join.window_seq = 11u;
    join.object_key = 0x3300ull;
    join.consumer_core_id = 1u;

    const auto join_result = table.join(join);
    assert(join_result.valid);
    assert(join_result.granted);
    assert(!join_result.duplicate_consumer);
    assert(join_result.owner_core_id == 0u);

    const auto stats = table.snapshotStats();
    assert(stats.owner_alloc_total == 2u);
    assert(stats.join_grant_total == 1u);
    assert(stats.active_entries_total == 2u);
}

static void test_pod_metadata_object_plane_exports_kind_resolved_stats() {
    PodMetadataObjectPlane::Config cfg{};
    cfg.enable = true;
    cfg.num_pods = 1;
    cfg.capacity_entries_per_pod = 1;

    PodMetadataObjectPlane plane(cfg);

    PodMetadataObjectPlane::ObserveRequest prebase{};
    prebase.pod_id = 0;
    prebase.window_seq = 5u;
    prebase.kind = PodMetadataObjectPlane::MetadataKind::PreMphfBase;
    prebase.object_id = 0x10u;
    prebase.core_id = 0u;

    const auto first = plane.observe(prebase);
    assert(first.accepted);

    auto prebase_join = prebase;
    prebase_join.core_id = 1u;
    const auto second = plane.observe(prebase_join);
    assert(second.accepted);

    PodMetadataObjectPlane::ObserveRequest rowindex{};
    rowindex.pod_id = 0;
    rowindex.window_seq = 5u;
    rowindex.kind = PodMetadataObjectPlane::MetadataKind::RowIndex;
    rowindex.object_id = 0x22u;
    rowindex.core_id = 2u;

    const auto third = plane.observe(rowindex);
    assert(third.accepted);

    std::map<std::string, uint64_t> stats;
    plane.exportStatsToMap(stats, "atlas_pod_metadata_");

    assert(stats["atlas_pod_metadata_enabled"] == 1u);
    assert(stats["atlas_pod_metadata_observe_total"] == 3u);
    assert(stats["atlas_pod_metadata_unique_object_total"] == 2u);
    assert(stats["atlas_pod_metadata_overlap_hit_total"] == 1u);
    assert(stats["atlas_pod_metadata_evict_total"] == 1u);
    assert(stats["atlas_pod_metadata_active_entries_total"] == 1u);

    assert(stats["atlas_pod_metadata_premphf_base_observe_total"] == 2u);
    assert(stats["atlas_pod_metadata_premphf_base_unique_object_total"] == 1u);
    assert(stats["atlas_pod_metadata_premphf_base_overlap_hit_total"] == 1u);
    assert(stats["atlas_pod_metadata_premphf_base_evict_total"] == 1u);
    assert(stats["atlas_pod_metadata_premphf_base_active_entries_total"] == 0u);

    assert(stats["atlas_pod_metadata_rowindex_observe_total"] == 1u);
    assert(stats["atlas_pod_metadata_rowindex_unique_object_total"] == 1u);
    assert(stats["atlas_pod_metadata_rowindex_overlap_hit_total"] == 0u);
    assert(stats["atlas_pod_metadata_rowindex_evict_total"] == 0u);
    assert(stats["atlas_pod_metadata_rowindex_active_entries_total"] == 1u);
}

static void test_pod_metadata_object_plane_exports_premphf_band_stats() {
    PodMetadataObjectPlane::Config cfg{};
    cfg.enable = true;
    cfg.num_pods = 1;
    cfg.capacity_entries_per_pod = 4;

    PodMetadataObjectPlane plane(cfg);

    PodMetadataObjectPlane::ObserveRequest band{};
    band.pod_id = 0;
    band.window_seq = 7u;
    band.kind = PodMetadataObjectPlane::MetadataKind::PreMphfBand;
    band.object_id = 0x31u;
    band.core_id = 0u;

    const auto first = plane.observe(band);
    assert(first.accepted);

    auto band_overlap = band;
    band_overlap.core_id = 1u;
    const auto second = plane.observe(band_overlap);
    assert(second.accepted);

    std::map<std::string, uint64_t> stats;
    plane.exportStatsToMap(stats, "atlas_pod_metadata_");

    assert(stats["atlas_pod_metadata_premphf_band_observe_total"] == 2u);
    assert(stats["atlas_pod_metadata_premphf_band_unique_object_total"] == 1u);
    assert(stats["atlas_pod_metadata_premphf_band_overlap_hit_total"] == 1u);
    assert(stats["atlas_pod_metadata_premphf_band_evict_total"] == 0u);
    assert(stats["atlas_pod_metadata_premphf_band_active_entries_total"] == 1u);
}

static void test_pod_metadata_object_plane_exports_lifecycle_probe_stats() {
    PodMetadataObjectPlane::Config cfg{};
    cfg.enable = true;
    cfg.num_pods = 1;
    cfg.capacity_entries_per_pod = 8;

    PodMetadataObjectPlane plane(cfg);

    PodMetadataObjectPlane::ObserveRequest band{};
    band.pod_id = 0;
    band.window_seq = 21u;
    band.kind = PodMetadataObjectPlane::MetadataKind::PreMphfBand;
    band.object_id = 0x71u;
    band.core_id = 0u;

    assert(plane.observe(band).accepted);

    auto band_overlap = band;
    band_overlap.core_id = 1u;
    assert(plane.observe(band_overlap).accepted);

    const auto duplicate = plane.observe(band_overlap);
    assert(duplicate.accepted);
    assert(duplicate.duplicate_consumer);

    auto band_second_object = band;
    band_second_object.object_id = 0x72u;
    band_second_object.core_id = 2u;
    assert(plane.observe(band_second_object).accepted);

    std::map<std::string, uint64_t> stats;
    plane.exportStatsToMap(stats, "atlas_pod_metadata_");

    assert(stats["atlas_pod_metadata_active_entries_peak_total"] == 2u);
    assert(stats["atlas_pod_metadata_premphf_band_duplicate_consumer_total"] == 1u);
    assert(stats["atlas_pod_metadata_premphf_band_active_entries_peak_total"] == 2u);
}

static void test_pod_owner_service_table_exports_kind_resolved_stats() {
    PodOwnerServiceTable::Config cfg{};
    cfg.enable = true;
    cfg.num_pods = 1;
    cfg.owner_entries_per_pod = 8;
    cfg.join_entries_per_pod = 8;

    PodOwnerServiceTable table(cfg);

    PodOwnerServiceTable::LookupRequest prebase{};
    prebase.pod_id = 0;
    prebase.window_seq = 9u;
    prebase.object_key = PodMetadataObjectPlane::composeObjectKey(
        PodMetadataObjectPlane::MetadataKind::PreMphfBase,
        0x41u);
    prebase.core_id = 0u;

    const auto owner_alloc = table.lookupOrAllocate(prebase);
    assert(owner_alloc.valid);
    assert(owner_alloc.allocated_owner);

    auto prebase_hit = prebase;
    prebase_hit.core_id = 1u;
    const auto owner_hit = table.lookupOrAllocate(prebase_hit);
    assert(owner_hit.valid);
    assert(owner_hit.owner_hit);

    PodOwnerServiceTable::JoinRequest prebase_join{};
    prebase_join.pod_id = 0;
    prebase_join.window_seq = 9u;
    prebase_join.object_key = prebase.object_key;
    prebase_join.consumer_core_id = 1u;
    const auto join = table.join(prebase_join);
    assert(join.valid);
    assert(join.granted);

    PodOwnerServiceTable::LookupRequest rowdescriptor{};
    rowdescriptor.pod_id = 0;
    rowdescriptor.window_seq = 10u;
    rowdescriptor.object_key = PodMetadataObjectPlane::composeObjectKey(
        PodMetadataObjectPlane::MetadataKind::RowDescriptor,
        0x51u);
    rowdescriptor.core_id = 2u;
    const auto descriptor_alloc = table.lookupOrAllocate(rowdescriptor);
    assert(descriptor_alloc.valid);
    assert(descriptor_alloc.allocated_owner);

    std::map<std::string, uint64_t> stats;
    table.exportStatsToMap(stats, "atlas_pod_owner_");

    assert(stats["atlas_pod_owner_enabled"] == 1u);
    assert(stats["atlas_pod_owner_lookup_total"] == 3u);
    assert(stats["atlas_pod_owner_owner_alloc_total"] == 2u);
    assert(stats["atlas_pod_owner_owner_hit_total"] == 1u);
    assert(stats["atlas_pod_owner_join_request_total"] == 1u);
    assert(stats["atlas_pod_owner_join_grant_total"] == 1u);
    assert(stats["atlas_pod_owner_active_entries_total"] == 2u);

    assert(stats["atlas_pod_owner_premphf_base_owner_alloc_total"] == 1u);
    assert(stats["atlas_pod_owner_premphf_base_owner_hit_total"] == 1u);
    assert(stats["atlas_pod_owner_premphf_base_join_grant_total"] == 1u);
    assert(stats["atlas_pod_owner_premphf_base_active_entries_total"] == 1u);

    assert(stats["atlas_pod_owner_rowdescriptor_owner_alloc_total"] == 1u);
    assert(stats["atlas_pod_owner_rowdescriptor_owner_hit_total"] == 0u);
    assert(stats["atlas_pod_owner_rowdescriptor_join_grant_total"] == 0u);
    assert(stats["atlas_pod_owner_rowdescriptor_active_entries_total"] == 1u);
}

static void test_pod_owner_service_table_exports_premphf_band_stats() {
    PodOwnerServiceTable::Config cfg{};
    cfg.enable = true;
    cfg.num_pods = 1;
    cfg.owner_entries_per_pod = 8;
    cfg.join_entries_per_pod = 8;

    PodOwnerServiceTable table(cfg);

    PodOwnerServiceTable::LookupRequest band{};
    band.pod_id = 0;
    band.window_seq = 12u;
    band.object_key = PodMetadataObjectPlane::composeObjectKey(
        PodMetadataObjectPlane::MetadataKind::PreMphfBand,
        0x61u);
    band.core_id = 0u;

    const auto owner_alloc = table.lookupOrAllocate(band);
    assert(owner_alloc.valid);
    assert(owner_alloc.allocated_owner);

    auto band_hit = band;
    band_hit.core_id = 1u;
    const auto owner_hit = table.lookupOrAllocate(band_hit);
    assert(owner_hit.valid);
    assert(owner_hit.owner_hit);

    PodOwnerServiceTable::JoinRequest band_join{};
    band_join.pod_id = 0;
    band_join.window_seq = 12u;
    band_join.object_key = band.object_key;
    band_join.consumer_core_id = 1u;
    const auto join = table.join(band_join);
    assert(join.valid);
    assert(join.granted);

    std::map<std::string, uint64_t> stats;
    table.exportStatsToMap(stats, "atlas_pod_owner_");

    assert(stats["atlas_pod_owner_premphf_band_owner_alloc_total"] == 1u);
    assert(stats["atlas_pod_owner_premphf_band_owner_hit_total"] == 1u);
    assert(stats["atlas_pod_owner_premphf_band_join_grant_total"] == 1u);
    assert(stats["atlas_pod_owner_premphf_band_active_entries_total"] == 1u);
}

static void test_pod_owner_service_table_exports_lifecycle_probe_stats() {
    PodOwnerServiceTable::Config cfg{};
    cfg.enable = true;
    cfg.num_pods = 1;
    cfg.owner_entries_per_pod = 1;
    cfg.join_entries_per_pod = 1;

    PodOwnerServiceTable table(cfg);

    PodOwnerServiceTable::LookupRequest band{};
    band.pod_id = 0;
    band.window_seq = 22u;
    band.object_key = PodMetadataObjectPlane::composeObjectKey(
        PodMetadataObjectPlane::MetadataKind::PreMphfBand,
        0x81u);
    band.core_id = 0u;

    const auto alloc = table.lookupOrAllocate(band);
    assert(alloc.valid);
    assert(alloc.allocated_owner);

    auto band_reject = band;
    band_reject.object_key = PodMetadataObjectPlane::composeObjectKey(
        PodMetadataObjectPlane::MetadataKind::PreMphfBand,
        0x82u);
    band_reject.core_id = 1u;
    const auto reject = table.lookupOrAllocate(band_reject);
    assert(!reject.valid);
    assert(reject.reject_reason == PodOwnerServiceTable::RejectReason::TableFull);

    PodOwnerServiceTable::JoinRequest join{};
    join.pod_id = 0;
    join.window_seq = 22u;
    join.object_key = band.object_key;
    join.consumer_core_id = 1u;
    const auto join_grant = table.join(join);
    assert(join_grant.valid);
    assert(join_grant.granted);

    auto join_reject = join;
    join_reject.consumer_core_id = 2u;
    const auto rejected_join = table.join(join_reject);
    assert(rejected_join.valid);
    assert(!rejected_join.granted);
    assert(rejected_join.reject_reason == PodOwnerServiceTable::RejectReason::TableFull);

    std::map<std::string, uint64_t> stats;
    table.exportStatsToMap(stats, "atlas_pod_owner_");

    assert(stats["atlas_pod_owner_active_entries_peak_total"] == 1u);
    assert(stats["atlas_pod_owner_premphf_band_owner_reject_total"] == 1u);
    assert(stats["atlas_pod_owner_premphf_band_join_request_total"] == 2u);
    assert(stats["atlas_pod_owner_premphf_band_join_reject_total"] == 1u);
    assert(stats["atlas_pod_owner_premphf_band_active_entries_peak_total"] == 1u);
}

static void test_pe_local_service_object_table_tracks_live_ready_and_late_join() {
    PeLocalServiceObjectTable::Config cfg{};
    cfg.enable = true;
    cfg.num_pods = 2;
    cfg.active_entries_per_pod = 8;
    cfg.released_entries_per_pod = 8;

    PeLocalServiceObjectTable table(cfg);

    PeLocalServiceObjectTable::OwnerRequest owner{};
    owner.pod_id = 0;
    owner.window_seq = 21u;
    owner.object_key = 0x123400ull;
    owner.owner_core_id = 0u;

    const auto owner_result = table.noteOwnerForm(owner);
    assert(owner_result.valid);
    assert(owner_result.formed_owner);
    assert(!owner_result.owner_exists);

    PeLocalServiceObjectTable::JoinRequest live_join{};
    live_join.pod_id = 0;
    live_join.window_seq = 21u;
    live_join.object_key = 0x123400ull;
    live_join.consumer_core_id = 1u;

    const auto live_join_result = table.join(live_join);
    assert(live_join_result.valid);
    assert(live_join_result.joined_live);
    assert(!live_join_result.joined_ready);
    assert(!live_join_result.late_join);
    assert(!live_join_result.duplicate_consumer);

    PeLocalServiceObjectTable::ReadyRequest ready{};
    ready.pod_id = 0;
    ready.window_seq = 21u;
    ready.object_key = 0x123400ull;

    const auto ready_result = table.markReady(ready);
    assert(ready_result.valid);
    assert(ready_result.transitioned);
    assert(ready_result.ready_token != 0u);
    assert(ready_result.consumer_count == 2u);

    auto ready_join = live_join;
    ready_join.consumer_core_id = 2u;
    const auto ready_join_result = table.join(ready_join);
    assert(ready_join_result.valid);
    assert(!ready_join_result.joined_live);
    assert(ready_join_result.joined_ready);
    assert(!ready_join_result.late_join);
    assert(ready_join_result.ready_token == ready_result.ready_token);

    PeLocalServiceObjectTable::ReleaseRequest release{};
    release.pod_id = 0;
    release.window_seq = 21u;
    release.object_key = 0x123400ull;

    const auto release_result = table.release(release);
    assert(release_result.valid);
    assert(release_result.released);

    auto late_join = live_join;
    late_join.consumer_core_id = 3u;
    const auto late_join_result = table.join(late_join);
    assert(late_join_result.valid);
    assert(!late_join_result.joined_live);
    assert(!late_join_result.joined_ready);
    assert(late_join_result.late_join);

    const auto stats = table.snapshotStats();
    assert(stats.owner_form_total == 1u);
    assert(stats.join_live_total == 1u);
    assert(stats.join_ready_total == 1u);
    assert(stats.late_join_total == 1u);
    assert(stats.ready_transition_total == 1u);
    assert(stats.ready_fanout_total == 1u);
    assert(stats.ready_fanout_consumers_sum == 2u);
    assert(stats.ready_fanout_consumers_peak == 2u);
    assert(stats.released_total == 1u);
    assert(stats.potential_private_service_elide_total == 2u);
    assert(stats.active_entries_total == 0u);
}

static void test_pe_local_service_object_table_keeps_entries_across_window_skew() {
    PeLocalServiceObjectTable::Config cfg{};
    cfg.enable = true;
    cfg.num_pods = 1;
    cfg.active_entries_per_pod = 8;
    cfg.released_entries_per_pod = 8;

    PeLocalServiceObjectTable table(cfg);

    PeLocalServiceObjectTable::OwnerRequest owner{};
    owner.pod_id = 0;
    owner.window_seq = 21u;
    owner.object_key = 0x223400ull;
    owner.owner_core_id = 0u;

    const auto owner_result = table.noteOwnerForm(owner);
    assert(owner_result.valid);
    assert(owner_result.formed_owner);

    auto foreign_owner = owner;
    foreign_owner.window_seq = 22u;
    foreign_owner.object_key = 0x223500ull;
    foreign_owner.owner_core_id = 3u;

    const auto foreign_result = table.noteOwnerForm(foreign_owner);
    assert(foreign_result.valid);
    assert(foreign_result.formed_owner);

    PeLocalServiceObjectTable::JoinRequest join{};
    join.pod_id = 0;
    join.window_seq = 21u;
    join.object_key = 0x223400ull;
    join.consumer_core_id = 1u;

    const auto join_result = table.join(join);
    assert(join_result.valid);
    assert(join_result.joined_live);

    PeLocalServiceObjectTable::ReadyRequest ready{};
    ready.pod_id = 0;
    ready.window_seq = 21u;
    ready.object_key = 0x223400ull;

    const auto ready_result = table.markReady(ready);
    assert(ready_result.valid);
    assert(ready_result.transitioned);
    assert(ready_result.consumer_count == 2u);

    PeLocalServiceObjectTable::ReleaseRequest release{};
    release.pod_id = 0;
    release.window_seq = 21u;
    release.object_key = 0x223400ull;

    const auto release_result = table.release(release);
    assert(release_result.valid);
    assert(release_result.released);

    const auto stats = table.snapshotStats();
    assert(stats.owner_form_total == 2u);
    assert(stats.join_live_total == 1u);
    assert(stats.ready_transition_total == 1u);
    assert(stats.released_total == 1u);
    assert(stats.active_entries_total == 1u);
}

static void test_pe_local_service_object_table_ready_lease_hits_within_ttl() {
    PeLocalServiceObjectTable::Config cfg{};
    cfg.enable = true;
    cfg.num_pods = 1;
    cfg.active_entries_per_pod = 8;
    cfg.released_entries_per_pod = 8;
    cfg.ready_lease_enable = true;
    cfg.ready_lease_ttl = 4u;
    cfg.ready_lease_kind_mask = (1u << 5);

    PeLocalServiceObjectTable table(cfg);
    table.onClockTick(100u);

    PeLocalServiceObjectTable::OwnerRequest owner{};
    owner.pod_id = 0;
    owner.window_seq = 31u;
    owner.object_key = (5ull << 56) ^ 0x445566ull;
    owner.owner_core_id = 0u;

    const auto owner_result = table.noteOwnerForm(owner);
    assert(owner_result.valid);
    assert(owner_result.formed_owner);

    PeLocalServiceObjectTable::JoinRequest live_join{};
    live_join.pod_id = 0;
    live_join.window_seq = 31u;
    live_join.object_key = owner.object_key;
    live_join.consumer_core_id = 1u;

    const auto live_join_result = table.join(live_join);
    assert(live_join_result.valid);
    assert(live_join_result.joined_live);

    PeLocalServiceObjectTable::ReadyRequest ready{};
    ready.pod_id = 0;
    ready.window_seq = 31u;
    ready.object_key = owner.object_key;

    const auto ready_result = table.markReady(ready);
    assert(ready_result.valid);
    assert(ready_result.transitioned);

    PeLocalServiceObjectTable::ReleaseRequest release{};
    release.pod_id = 0;
    release.window_seq = 31u;
    release.object_key = owner.object_key;

    const auto release_result = table.release(release);
    assert(release_result.valid);
    assert(release_result.released);

    table.onClockTick(103u);

    auto leased_join = live_join;
    leased_join.consumer_core_id = 2u;
    const auto leased_join_result = table.join(leased_join);
    assert(leased_join_result.valid);
    assert(!leased_join_result.joined_live);
    assert(leased_join_result.joined_ready);
    assert(!leased_join_result.late_join);
    assert(leased_join_result.ready_lease_hit);
    assert(!leased_join_result.ready_lease_expired);
    assert(leased_join_result.ready_token == ready_result.ready_token);

    const auto stats = table.snapshotStats();
    assert(stats.join_ready_total == 1u);
    assert(stats.late_join_total == 0u);
    assert(stats.ready_lease_hit_total == 1u);
    assert(stats.ready_lease_expired_total == 0u);
    assert(stats.potential_private_service_elide_total == 2u);
}

static void test_pe_local_service_object_table_ready_lease_expires_after_ttl() {
    PeLocalServiceObjectTable::Config cfg{};
    cfg.enable = true;
    cfg.num_pods = 1;
    cfg.active_entries_per_pod = 8;
    cfg.released_entries_per_pod = 8;
    cfg.ready_lease_enable = true;
    cfg.ready_lease_ttl = 2u;
    cfg.ready_lease_kind_mask = (1u << 5);

    PeLocalServiceObjectTable table(cfg);
    table.onClockTick(200u);

    PeLocalServiceObjectTable::OwnerRequest owner{};
    owner.pod_id = 0;
    owner.window_seq = 32u;
    owner.object_key = (5ull << 56) ^ 0x778899ull;
    owner.owner_core_id = 0u;

    const auto owner_result = table.noteOwnerForm(owner);
    assert(owner_result.valid);
    assert(owner_result.formed_owner);

    PeLocalServiceObjectTable::ReadyRequest ready{};
    ready.pod_id = 0;
    ready.window_seq = 32u;
    ready.object_key = owner.object_key;

    const auto ready_result = table.markReady(ready);
    assert(ready_result.valid);
    assert(ready_result.transitioned);

    PeLocalServiceObjectTable::ReleaseRequest release{};
    release.pod_id = 0;
    release.window_seq = 32u;
    release.object_key = owner.object_key;

    const auto release_result = table.release(release);
    assert(release_result.valid);
    assert(release_result.released);

    table.onClockTick(203u);

    PeLocalServiceObjectTable::JoinRequest expired_join{};
    expired_join.pod_id = 0;
    expired_join.window_seq = 32u;
    expired_join.object_key = owner.object_key;
    expired_join.consumer_core_id = 2u;

    const auto expired_join_result = table.join(expired_join);
    assert(expired_join_result.valid);
    assert(!expired_join_result.joined_live);
    assert(!expired_join_result.joined_ready);
    assert(expired_join_result.late_join);
    assert(!expired_join_result.ready_lease_hit);
    assert(expired_join_result.ready_lease_expired);
    assert(expired_join_result.ready_token == ready_result.ready_token);

    const auto stats = table.snapshotStats();
    assert(stats.join_ready_total == 0u);
    assert(stats.late_join_total == 1u);
    assert(stats.ready_lease_hit_total == 0u);
    assert(stats.ready_lease_expired_total == 1u);
    assert(stats.released_total == 1u);
}

static void test_pe_local_service_object_table_tracks_atlas_object_census() {
    PeLocalServiceObjectTable::Config cfg{};
    cfg.enable = true;
    cfg.num_pods = 1;
    cfg.active_entries_per_pod = 8;
    cfg.released_entries_per_pod = 8;

    PeLocalServiceObjectTable table(cfg);

    PeLocalServiceObjectTable::OwnerRequest shared_owner{};
    shared_owner.pod_id = 0;
    shared_owner.window_seq = 41u;
    shared_owner.object_key = (5ull << 56) ^ 0x111111ull;
    shared_owner.owner_core_id = 0u;

    const auto shared_owner_result = table.noteOwnerForm(shared_owner);
    assert(shared_owner_result.valid);
    assert(shared_owner_result.formed_owner);

    PeLocalServiceObjectTable::JoinRequest shared_join{};
    shared_join.pod_id = 0;
    shared_join.window_seq = 41u;
    shared_join.object_key = shared_owner.object_key;
    shared_join.consumer_core_id = 1u;

    const auto shared_join_result = table.join(shared_join);
    assert(shared_join_result.valid);
    assert(shared_join_result.joined_live);

    PeLocalServiceObjectTable::ReadyRequest shared_ready{};
    shared_ready.pod_id = 0;
    shared_ready.window_seq = 41u;
    shared_ready.object_key = shared_owner.object_key;

    const auto shared_ready_result = table.markReady(shared_ready);
    assert(shared_ready_result.valid);
    assert(shared_ready_result.transitioned);

    PeLocalServiceObjectTable::ReleaseRequest shared_release{};
    shared_release.pod_id = 0;
    shared_release.window_seq = 41u;
    shared_release.object_key = shared_owner.object_key;

    const auto shared_release_result = table.release(shared_release);
    assert(shared_release_result.valid);
    assert(shared_release_result.released);

    PeLocalServiceObjectTable::OwnerRequest private_owner{};
    private_owner.pod_id = 0;
    private_owner.window_seq = 42u;
    private_owner.object_key = (4ull << 56) ^ 0x222222ull;
    private_owner.owner_core_id = 2u;

    const auto private_owner_result = table.noteOwnerForm(private_owner);
    assert(private_owner_result.valid);
    assert(private_owner_result.formed_owner);

    PeLocalServiceObjectTable::ReleaseRequest private_release{};
    private_release.pod_id = 0;
    private_release.window_seq = 42u;
    private_release.object_key = private_owner.object_key;

    const auto private_release_result = table.release(private_release);
    assert(private_release_result.valid);
    assert(private_release_result.released);

    const auto stats = table.snapshotStats();
    assert(stats.atlas_obj_materialize_total == 2u);
    assert(stats.atlas_obj_publicize_total == 2u);
    assert(stats.atlas_obj_owner_form_total == 2u);
    assert(stats.atlas_obj_ready_total == 1u);
    assert(stats.atlas_obj_release_total == 2u);
    assert(stats.atlas_obj_private_only_total == 1u);
}

static void test_pe_local_service_object_table_exports_atlas_prefixed_stats() {
    PeLocalServiceObjectTable::Config cfg{};
    cfg.enable = true;
    cfg.num_pods = 1;
    cfg.active_entries_per_pod = 8;
    cfg.released_entries_per_pod = 8;

    PeLocalServiceObjectTable table(cfg);

    PeLocalServiceObjectTable::OwnerRequest owner{};
    owner.pod_id = 0;
    owner.window_seq = 51u;
    owner.object_key = (5ull << 56) ^ 0x333333ull;
    owner.owner_core_id = 0u;

    const auto owner_result = table.noteOwnerForm(owner);
    assert(owner_result.valid);
    assert(owner_result.formed_owner);

    PeLocalServiceObjectTable::ReadyRequest ready{};
    ready.pod_id = 0;
    ready.window_seq = 51u;
    ready.object_key = owner.object_key;

    const auto ready_result = table.markReady(ready);
    assert(ready_result.valid);
    assert(ready_result.transitioned);

    PeLocalServiceObjectTable::ReleaseRequest release{};
    release.pod_id = 0;
    release.window_seq = 51u;
    release.object_key = owner.object_key;

    const auto release_result = table.release(release);
    assert(release_result.valid);
    assert(release_result.released);

    std::map<std::string, uint64_t> stats;
    table.exportStatsToMap(stats, "atlas_service_");

    assert(stats["atlas_service_enabled"] == 1u);
    assert(stats["atlas_service_owner_form_total"] == 1u);
    assert(stats["atlas_service_ready_transition_total"] == 1u);
    assert(stats["atlas_service_released_total"] == 1u);
    assert(stats["atlas_service_atlas_obj_materialize_total"] == 1u);
    assert(stats["atlas_service_atlas_obj_publicize_total"] == 1u);
    assert(stats["atlas_service_atlas_obj_owner_form_total"] == 1u);
    assert(stats["atlas_service_atlas_obj_ready_total"] == 1u);
    assert(stats["atlas_service_atlas_obj_release_total"] == 1u);
    assert(stats["atlas_service_atlas_obj_private_only_total"] == 1u);
}

static void test_pe_weight_object_plane_tracks_shared_idx_and_l0_pressure() {
    PeWeightObjectPlane::Config cfg{};
    cfg.enable = true;
    cfg.owner_scope_enable = true;
    cfg.idx_enable = true;
    cfg.l0_enable = true;
    cfg.idx_capacity_bytes = 1024;
    cfg.l0_capacity_bytes = 2048;
    cfg.idx_banks = 2;
    cfg.l0_banks = 2;
    cfg.ports_per_bank = 1;
    cfg.bank_interleave_bytes = 4;
    cfg.t_read_cycles = 1;
    cfg.t_write_cycles = 1;

    PeWeightObjectPlane plane(cfg);
    assert(plane.enabled());
    assert(plane.ownerScopeEnabled());

    plane.noteIdxRead(10, 0x100000000ull, 4);
    plane.noteIdxRead(10, 0x100000004ull, 4);
    plane.noteL0Write(10, 1234ull);
    plane.noteResidentIdxBytes(128);
    plane.noteResidentL0Bytes(256);
    plane.onClockTick(10);

    const auto stats = plane.snapshotStats();
    assert(stats.idx_sram.reads_total == 2u);
    assert(stats.l0_sram.writes_total == 1u);
    assert(stats.idx_sram.resident_bytes_last == 128u);
    assert(stats.l0_sram.resident_bytes_last == 256u);
}

static void test_pe_weight_object_plane_aggregates_multiple_clients() {
    PeWeightObjectPlane::Config cfg{};
    cfg.enable = true;
    cfg.owner_scope_enable = true;
    cfg.idx_enable = true;
    cfg.idx_banks = 1;
    cfg.ports_per_bank = 1;

    PeWeightObjectPlane plane(cfg);
    plane.noteIdxRead(20, 0x100000000ull, 4);
    plane.noteIdxRead(20, 0x100000008ull, 4);
    plane.onClockTick(21);

    const auto stats = plane.snapshotStats();
    assert(stats.idx_sram.reads_total == 2u);
    assert(stats.idx_sram.bank_conflict_events_total >= 1u);
}

static void test_pe_weight_object_plane_classifies_authority_state() {
    PeWeightObjectPlane::Config private_cfg{};
    private_cfg.enable = true;
    private_cfg.idx_enable = true;
    private_cfg.l0_enable = true;
    PeWeightObjectPlane private_plane(private_cfg);

    auto private_stats = private_plane.snapshotStats();
    assert(private_stats.idx_authority == PeWeightObjectPlane::AuthorityClass::PrivateAuthority);
    assert(private_stats.l0_authority == PeWeightObjectPlane::AuthorityClass::PrivateAuthority);

    PeWeightObjectPlane::Config mirror_cfg{};
    mirror_cfg.enable = true;
    mirror_cfg.owner_scope_enable = true;
    mirror_cfg.idx_enable = true;
    mirror_cfg.l0_enable = true;
    PeWeightObjectPlane mirror_plane(mirror_cfg);

    auto mirror_stats = mirror_plane.snapshotStats();
    assert(mirror_stats.idx_authority == PeWeightObjectPlane::AuthorityClass::SharedMirrorOnly);
    assert(mirror_stats.l0_authority == PeWeightObjectPlane::AuthorityClass::SharedMirrorOnly);

    PeWeightObjectPlane::Config owner_cfg{};
    owner_cfg.enable = true;
    owner_cfg.owner_scope_enable = true;
    owner_cfg.actual_owner_enable = true;
    owner_cfg.idx_enable = true;
    owner_cfg.l0_enable = true;
    PeWeightObjectPlane owner_plane(owner_cfg);

    auto owner_stats = owner_plane.snapshotStats();
    assert(owner_stats.idx_authority ==
           PeWeightObjectPlane::AuthorityClass::SharedAuthorityActive);
    assert(owner_stats.l0_authority ==
           PeWeightObjectPlane::AuthorityClass::SharedAuthorityActive);
}

static void test_weight_object_plane_provider_contract_is_narrow() {
    IPeWeightObjectPlaneProvider* provider = nullptr;
    (void)provider;
}

static void test_pe_weight_object_plane_exports_prefixed_stats() {
    PeWeightObjectPlane::Config cfg{};
    cfg.enable = true;
    cfg.owner_scope_enable = true;
    cfg.actual_owner_enable = true;
    cfg.idx_enable = true;
    cfg.l0_enable = true;
    cfg.idx_banks = 1;
    cfg.l0_banks = 1;
    cfg.ports_per_bank = 1;

    PeWeightObjectPlane plane(cfg);
    plane.noteIdxRead(30, 0x100000000ull, 4);
    plane.noteL0Fill(30, 99ull);
    plane.noteL0Evict(30, 101ull);
    plane.noteResidentIdxBytes(64);
    plane.noteResidentL0Bytes(128);
    plane.onClockTick(31);

    std::map<std::string, uint64_t> stats;
    plane.exportStatsToMap(stats, "pulse_osa_shared_weight_");

    assert(stats["pulse_osa_shared_weight_owner_scope_enable"] == 1u);
    assert(stats["pulse_osa_shared_weight_actual_owner_enable"] == 1u);
    assert(stats["pulse_osa_shared_weight_idx_reads_total"] == 1u);
    assert(stats["pulse_osa_shared_weight_idx_resident_bytes_peak"] == 64u);
    assert(stats["pulse_osa_shared_weight_l0_fill_total"] == 1u);
    assert(stats["pulse_osa_shared_weight_l0_evict_total"] == 1u);
    assert(stats["pulse_osa_shared_weight_l0_writes_total"] == 2u);
    assert(stats["pulse_osa_shared_weight_l0_resident_bytes_peak"] == 128u);
}

int main() {
    test_basic_registration_and_snapshot();
    test_disabled_object_does_not_count_as_enabled();
    test_phase_a_default_registration_layout();
    test_phase_a_registers_per_pod_objects();
    test_pod_metadata_object_plane_tracks_overlap_per_pod_object();
    test_pod_owner_service_table_allocates_owner_then_grants_join();
    test_pod_owner_service_table_keeps_entries_across_window_skew();
    test_pod_metadata_object_plane_exports_kind_resolved_stats();
    test_pod_metadata_object_plane_exports_premphf_band_stats();
    test_pod_metadata_object_plane_exports_lifecycle_probe_stats();
    test_pod_owner_service_table_exports_kind_resolved_stats();
    test_pod_owner_service_table_exports_premphf_band_stats();
    test_pod_owner_service_table_exports_lifecycle_probe_stats();
    test_pe_local_service_object_table_tracks_live_ready_and_late_join();
    test_pe_local_service_object_table_keeps_entries_across_window_skew();
    test_pe_local_service_object_table_ready_lease_hits_within_ttl();
    test_pe_local_service_object_table_ready_lease_expires_after_ttl();
    test_pe_local_service_object_table_tracks_atlas_object_census();
    test_pe_local_service_object_table_exports_atlas_prefixed_stats();
    test_pe_weight_object_plane_tracks_shared_idx_and_l0_pressure();
    test_pe_weight_object_plane_aggregates_multiple_clients();
    test_pe_weight_object_plane_classifies_authority_state();
    test_weight_object_plane_provider_contract_is_narrow();
    test_pe_weight_object_plane_exports_prefixed_stats();
    return 0;
}
