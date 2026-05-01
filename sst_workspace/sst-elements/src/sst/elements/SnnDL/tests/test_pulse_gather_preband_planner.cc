#include <algorithm>
#include <cassert>
#include <cstdarg>
#include <cstdint>
#include <cstdlib>
#include <string>
#include <vector>

#include "components/workload_stats/SnnWorkloadStatsModule.h"
#include "services/synapse/weights/WeightMemorySubsystem.h"

using SST::SnnDL::IWorkloadStatRegistrar;
using SST::SnnDL::SnnWorkloadStatsModule;
using SST::SnnDL::WeightMemorySubsystem;

namespace SST {

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

class RecordingRegistrar final : public IWorkloadStatRegistrar {
public:
    SST::Statistics::Statistic<uint64_t>* registerU64(const std::string& stat_name) override {
        names.push_back(stat_name);
        return nullptr;
    }

    std::vector<std::string> names;
};

bool containsRegisteredStat(const std::vector<std::string>& names, const char* key) {
    return std::find(names.begin(), names.end(), std::string(key)) != names.end();
}

uint64_t sumInactiveIdx2PathStats(
    const WeightMemorySubsystem::ExperimentalPeInternalPodPathAlignmentLane& lane) {
    return lane.producer_touch_events_total +
           lane.producer_enqueued_total +
           lane.seam_owner_form_total +
           lane.seam_joiner_hit_total +
           lane.seam_joiner_useful_total +
           lane.seam_owner_live_join_total +
           lane.seam_owner_ready_join_total +
           lane.seam_ready_transition_total +
           lane.seam_ready_fanout_total +
           lane.seam_ready_fanout_consumers_sum +
           lane.seam_late_join_total +
           lane.seam_potential_private_service_elide_total +
           lane.seam_owner_first_issue_deferred_total +
           lane.seam_owner_first_private_issue_avoided_total +
           lane.seam_owner_first_service_elide_total +
           lane.seam_guard_total +
           lane.seam_guard_disabled_total +
           lane.seam_guard_missing_metadata_plane_total +
           lane.seam_guard_missing_owner_table_total +
           lane.seam_guard_zero_pod_count_total +
           lane.seam_guard_window_zero_total +
           lane.seam_guard_invalid_cfg_pod_total +
           lane.seam_reject_total +
           lane.seam_useful_total +
           lane.seam_attempted_total;
}

uint64_t sumInactivePulseFrontierAndRowdescriptorStats(
    const WeightMemorySubsystem::PulseAgendaObservabilityStats& stats) {
    return stats.frontier_windows_total +
           stats.frontier_lines_exported_total +
           stats.frontier_overlap_lines_total +
           stats.frontier_overlap_peer_total +
           stats.frontier_max_exported_per_window +
           stats.rowdescriptor_ready_join_shortcut_candidates_total +
           stats.rowdescriptor_ready_join_shortcut_taken_total +
           stats.rowdescriptor_ready_join_shortcut_late_release_taken_total +
           stats.rowdescriptor_ready_join_shortcut_deferred_live_park_total +
           stats.rowdescriptor_ready_join_shortcut_deferred_live_apply_total +
           stats.rowdescriptor_owner_form_deferred_park_total +
           stats.rowdescriptor_owner_form_deferred_activate_total +
           stats.rowdescriptor_ready_join_shortcut_blocked_not_ready_total +
           stats.rowdescriptor_ready_join_shortcut_blocked_owner_form_total +
           stats.rowdescriptor_ready_join_shortcut_blocked_join_live_total +
           stats.rowdescriptor_ready_join_shortcut_blocked_other_total +
           stats.rowdescriptor_ready_join_shortcut_release_deferred_total +
           stats.rowdescriptor_ready_join_shortcut_apply_complete_total +
           stats.rowdescriptor_ready_join_shortcut_release_forwarded_total +
           stats.rowdescriptor_ready_join_shortcut_release_missing_total +
           stats.rowdescriptor_ready_join_descriptor_elide_total +
           stats.rowdescriptor_ready_join_lines_elide_total +
           stats.rowdescriptor_owner_first_service_elide_join_live_total +
           stats.rowdescriptor_owner_first_service_elide_join_ready_total +
           stats.rowdescriptor_owner_first_service_elide_late_join_total +
           stats.rowdescriptor_ready_transition_total +
           stats.rowdescriptor_join_ready_total;
}

void test_public_window_touch_does_not_reactivate_idx2_ingress() {
    WeightMemorySubsystem wms;
    WeightMemorySubsystem::OrchestratorConfig cfg{};
    cfg.synapse_weight_mode = "gcss_idx2_rowmphf";
    cfg.experimental_idx2_ingress_prefetch_enable = true;
    cfg.experimental_idx2_ingress_prefetch_cache_entries = 8u;
    cfg.experimental_idx2_ingress_prefetch_gather_only = false;
    cfg.num_neurons = 64u;
    cfg.base_addr = 0x4000u;
    cfg.line_size_bytes = 64u;
    wms.configureOrchestrator(cfg);

    wms.beginGatherWindow(true, 64u);
    wms.noteWindowTouch(3u, 123u, 64u);
    assert(sumInactiveIdx2PathStats(
               wms.experimentalPeInternalPodPathAlignmentStats().idx2row) == 0u);

    wms.beginApplyWindow(5u, false, nullptr, 0);
    wms.onClockTick(1u);
    assert(sumInactiveIdx2PathStats(
               wms.experimentalPeInternalPodPathAlignmentStats().idx2row) == 0u);
}

void test_public_window_lifecycle_keeps_legacy_pulse_fields_zero() {
    WeightMemorySubsystem wms;
    WeightMemorySubsystem::OrchestratorConfig cfg{};
    cfg.synapse_weight_mode = "gcss_valueonly_dstcore_vlf_premphf_plp";
    cfg.pulse_agenda_enable = true;
    cfg.pulse_metadata_frontier_observe_enable = true;
    cfg.pulse_metadata_seed_enable = true;
    cfg.pulse_mfb_preband_seed_enable = true;
    cfg.pulse_mfb_gather_preband_enable = true;
    cfg.pulse_mfb_gather_barrier_enable = true;
    cfg.pulse_prebase_shared_lookup_enable = true;
    cfg.num_neurons = 64u;
    cfg.base_addr = 0x1000u;
    cfg.line_size_bytes = 64u;
    wms.configureOrchestrator(cfg);

    wms.beginGatherWindow(true, 64u);
    wms.noteWindowTouch(4u, 77u, 64u);
    wms.recordEdgeWithPreRankCount(4u, 77u, 0.0f, 5u, 1u);
    assert(sumInactivePulseFrontierAndRowdescriptorStats(
               wms.pulseAgendaObservabilityStats()) == 0u);

    wms.beginApplyWindow(7u, false, nullptr, 0);
    wms.onClockTick(2u);
    assert(sumInactivePulseFrontierAndRowdescriptorStats(
               wms.pulseAgendaObservabilityStats()) == 0u);

    wms.endScatterWindow(7u);
    assert(sumInactivePulseFrontierAndRowdescriptorStats(
               wms.pulseAgendaObservabilityStats()) == 0u);
}

void test_snn_workload_stats_module_excludes_legacy_wms_frontier_counters() {
    SnnWorkloadStatsModule module(true);
    RecordingRegistrar registrar;
    module.initialize(registrar, 1u);

    assert(!containsRegisteredStat(
        registrar.names, "snn_wms_frontier_record_prerank_entry_total"));
    assert(!containsRegisteredStat(
        registrar.names, "snn_wms_frontier_record_prerank_premphf_mode_total"));
    assert(!containsRegisteredStat(
        registrar.names, "snn_wms_frontier_record_prerank_existing_rank_total"));
    assert(!containsRegisteredStat(
        registrar.names, "snn_wms_frontier_record_prerank_new_rank_total"));
    assert(!containsRegisteredStat(
        registrar.names, "snn_wms_frontier_record_prerank_total"));
    assert(!containsRegisteredStat(
        registrar.names, "snn_wms_frontier_collect_entry_total"));
    assert(!containsRegisteredStat(
        registrar.names, "snn_wms_frontier_lookup_attempt_total"));
    assert(!containsRegisteredStat(
        registrar.names, "snn_wms_frontier_collect_line_notes_total"));
}

} // namespace

int main(int argc, char** argv) {
    (void)argc;
    (void)argv;
    test_public_window_touch_does_not_reactivate_idx2_ingress();
    test_public_window_lifecycle_keeps_legacy_pulse_fields_zero();
    test_snn_workload_stats_module_excludes_legacy_wms_frontier_counters();
    return 0;
}
