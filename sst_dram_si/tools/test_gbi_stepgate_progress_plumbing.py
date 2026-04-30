import unittest
from pathlib import Path


class GbiStepgateProgressPlumbingTest(unittest.TestCase):
    def setUp(self):
        self.repo = Path(__file__).resolve().parents[2]
        self.gbi_h = self.repo / "sst_workspace/sst-elements/src/sst/elements/SnnDL/components/GatherBufferIF.h"
        self.gbi_cc = self.repo / "sst_workspace/sst-elements/src/sst/elements/SnnDL/components/GatherBufferIF.cc"
        self.mpe_h = self.repo / "sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.h"
        self.mpe_cc = self.repo / "sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc"
        self.wms_h = self.repo / "sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h"
        self.wms_cc = self.repo / "sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc"
        self.pe_agg_h = self.repo / "sst_workspace/sst-elements/src/sst/elements/SnnDL/api/IPeAggregation.h"
        self.pe_sub_h = self.repo / "sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.h"
        self.pe_sub_cc = self.repo / "sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc"
        self.mesh_config_py = self.repo / "sst_dram_si/mesh_template/config.py"
        self.mesh_build_py = self.repo / "sst_dram_si/mesh_template/build.py"
        self.mesh_runtime_py = self.repo / "sst_dram_si/mesh_template/runtime.py"
        self.mesh_spec_py = self.repo / "sst_dram_si/mesh_template/spec.py"
        self.mesh_defaults_py = self.repo / "sst_dram_si/mesh_template/legacy_defaults.py"

    def test_progress_log_exports_issue_resp_and_oldest_age_fields(self):
        h_text = self.gbi_h.read_text(encoding="utf-8")
        cc_text = self.gbi_cc.read_text(encoding="utf-8")

        for key in [
            "apply_begin_ns_",
            "apply_first_down_issue_ns_",
            "apply_first_down_resp_ns_",
            "apply_first_granule_done_ns_",
            "apply_first_up_resp_ns_",
            "apply_down_resp_total_",
            "apply_completed_granules_total_",
            "apply_emitted_subreads_total_",
        ]:
            self.assertIn(key, h_text, msg=f"{key} missing from GatherBufferIF.h")

        for key in [
            "apply_first_issue_delay_ns",
            "apply_first_resp_delay_ns",
            "apply_first_granule_done_delay_ns",
            "apply_first_up_resp_delay_ns",
            "oldest_inflight_granule_age_ns",
            ' aid=%" PRIu64',
            ' ard=%" PRIu64',
            ' acd=%" PRIu64',
            ' aud=%" PRIu64',
            ' dr=%" PRIu64',
            ' gd=%" PRIu64',
            ' ur=%" PRIu64',
            ' oldest=%" PRIu64',
        ]:
            self.assertIn(key, cc_text, msg=f"{key} missing from GatherBufferIF.cc")

    def test_pulse_domain_retire_actual_path_is_plumbed_with_budget_gate(self):
        wms_h_text = self.wms_h.read_text(encoding="utf-8")
        wms_cc_text = self.wms_cc.read_text(encoding="utf-8")

        self.assertIn(
            "orch_.pulse_domain_retire_enable &&\n            !orch_.pulse_domain_retire_observe_only &&\n            orch_.pulse_domain_retire_mode == \"per_post\"",
            wms_h_text,
            msg="WeightMemorySubsystem should treat pulse actual per_post retire as an actual retire-policy override",
        )
        self.assertIn(
            "orch_.pulse_domain_retire_release_budget",
            wms_h_text,
            msg="WeightMemorySubsystem should consume pulse_domain_retire_release_budget",
        )
        self.assertIn(
            "release_budget == 0u || released < release_budget",
            wms_h_text,
            msg="Per-post actual retire path should honor release budget as a bounded drain gate",
        )
        self.assertIn(
            "tryRetireEdgesPerPost_();",
            wms_cc_text,
            msg="WeightMemorySubsystem clock path should keep driving actual per-post retire progress",
        )

    def test_mainline_observability_fields_are_plumbed_into_csv_and_retire_stats(self):
        gbi_h_text = self.gbi_h.read_text(encoding="utf-8")
        mpe_h_text = self.mpe_h.read_text(encoding="utf-8")
        mpe_cc_text = self.mpe_cc.read_text(encoding="utf-8")
        wms_h_text = self.wms_h.read_text(encoding="utf-8")
        pe_agg_h_text = self.pe_agg_h.read_text(encoding="utf-8")
        pe_sub_h_text = self.pe_sub_h.read_text(encoding="utf-8")
        pe_sub_cc_text = self.pe_sub_cc.read_text(encoding="utf-8")
        pe_sub_stats_block = pe_sub_h_text.split("SST_ELI_DOCUMENT_STATISTICS(", 1)[1].split("\n    )", 1)[0]

        for key in [
            "apply_issue_block_bank_credit_total_",
            "apply_issue_block_downstream_busy_total_",
        ]:
            self.assertIn(key, gbi_h_text, msg=f"{key} missing from GatherBufferIF.h")

        for key in [
            "apply_issue_block_bank_credit_total",
            "apply_issue_block_downstream_busy_total",
            "rx_packets_during_gather_total",
            "rx_packets_during_apply_total",
            "rx_packets_during_scatter_total",
            "rx_gate_pending_peak",
            "retire_wait_cycles_total",
            "retire_wait_cycles_due_to_hol_total",
            "retire_wait_cycles_due_to_barrier_total",
            "retire_wait_cycles_due_to_not_ready_total",
            "retire_samepost_blocked_edges_total",
            "retire_crosspost_blocked_edges_total",
            "retire_policy_loss_cycles_total",
            "retire_policy_loss_edges_total",
            "retire_ready_queue_peak",
            "retire_unblock_events_total",
            "step_barrier_wait_ns",
        ]:
            self.assertIn(key, mpe_h_text, msg=f"{key} missing from MultiCorePE.h")
            self.assertIn(key, mpe_cc_text, msg=f"{key} missing from MultiCorePE.cc")

        for key in [
            "wait_cycles_total",
            "wait_cycles_due_to_hol_total",
            "wait_cycles_due_to_barrier_total",
            "wait_cycles_due_to_not_ready_total",
            "samepost_blocked_edges_total",
            "crosspost_blocked_edges_total",
            "policy_loss_cycles_total",
            "policy_loss_edges_total",
            "head_hol_cycles_gcss_total",
            "head_hol_cycles_miss_total",
            "head_blocked_edges_gcss_total",
            "head_blocked_edges_miss_total",
            "gcss_head_queued_not_issued_cycles_total",
            "gcss_qni_head_wait_episodes_total",
            "gcss_qni_head_wait_cycles_max",
            "gcss_head_queued_not_issued_blocked_edges_total",
            "gcss_head_issued_wait_resp_cycles_total",
            "gcss_head_issued_wait_resp_blocked_edges_total",
            "gcss_resp_ready_but_hol_cycles_total",
            "gcss_resp_ready_but_hol_blocked_edges_total",
            "gcss_qni_vlf_younger_ahead_cycles_total",
            "gcss_qni_vlf_younger_ahead_blocked_edges_total",
            "gcss_qni_vlf_younger_ahead_depth_total",
            "gcss_qni_vlf_younger_ahead_depth_samples_total",
            "gcss_qni_vlf_younger_ahead_depth_max",
            "gcss_qni_issue_deferred_total",
            "gcss_qni_pending_direct_queue_residency_cycles_total",
            "gcss_qni_pending_direct_queue_residency_samples_total",
            "gcss_qni_pending_direct_queue_residency_cycles_max",
            "gcss_qni_pending_front_waiting_tick_cycles_total",
            "gcss_qni_pending_front_waiting_tick_blocked_edges_total",
            "begin_apply_windows_total",
            "begin_apply_prev_edges_total",
            "begin_apply_outstanding_carryin_total",
            "begin_apply_outstanding_carryin_windows_total",
            "begin_apply_loader_not_ready_windows_total",
            "edge_retire_registered_total",
            "edge_retire_retired_total",
            "end_scatter_gcss_vlf_issue_queue_residual_total",
            "end_scatter_pending_direct_reads_residual_total",
            "end_scatter_outstanding_residual_total",
            "end_scatter_residual_work_windows_total",
            "gcss_vlf_issue_prepare_total",
            "gcss_vlf_issue_edges_total",
            "gcss_vlf_issue_reorder_trigger_total",
            "gcss_vlf_issue_line_groups_total",
            "ready_queue_peak",
            "unblock_events_total",
        ]:
            self.assertIn(key, wms_h_text, msg=f"{key} missing from WeightMemorySubsystem.h")

        for key in [
            "retire_head_hol_cycles_gcss_total",
            "retire_head_hol_cycles_miss_total",
            "retire_head_blocked_edges_gcss_total",
            "retire_head_blocked_edges_miss_total",
            "retire_gcss_head_queued_not_issued_cycles_total",
            "retire_gcss_qni_head_wait_episodes_total",
            "retire_gcss_qni_head_wait_cycles_max",
            "retire_gcss_head_queued_not_issued_blocked_edges_total",
            "retire_gcss_head_issued_wait_resp_cycles_total",
            "retire_gcss_head_issued_wait_resp_blocked_edges_total",
            "retire_gcss_resp_ready_but_hol_cycles_total",
            "retire_gcss_resp_ready_but_hol_blocked_edges_total",
            "retire_gcss_qni_vlf_younger_ahead_cycles_total",
            "retire_gcss_qni_vlf_younger_ahead_blocked_edges_total",
            "retire_gcss_qni_vlf_younger_ahead_depth_total",
            "retire_gcss_qni_vlf_younger_ahead_depth_samples_total",
            "retire_gcss_qni_vlf_younger_ahead_depth_max",
            "retire_gcss_qni_issue_deferred_total",
            "retire_gcss_qni_pending_direct_queue_residency_cycles_total",
            "retire_gcss_qni_pending_direct_queue_residency_samples_total",
            "retire_gcss_qni_pending_direct_queue_residency_cycles_max",
            "retire_gcss_qni_pending_front_waiting_tick_cycles_total",
            "retire_gcss_qni_pending_front_waiting_tick_blocked_edges_total",
            "retire_begin_apply_windows_total",
            "retire_begin_apply_prev_edges_total",
            "retire_begin_apply_outstanding_carryin_total",
            "retire_begin_apply_outstanding_carryin_windows_total",
            "retire_begin_apply_loader_not_ready_windows_total",
            "retire_edge_retire_registered_total",
            "retire_edge_retire_retired_total",
            "retire_end_scatter_gcss_vlf_issue_queue_residual_total",
            "retire_end_scatter_pending_direct_reads_residual_total",
            "retire_end_scatter_outstanding_residual_total",
            "retire_end_scatter_residual_work_windows_total",
            "retire_gcss_vlf_issue_prepare_total",
            "retire_gcss_vlf_issue_edges_total",
            "retire_gcss_vlf_issue_reorder_trigger_total",
            "retire_gcss_vlf_issue_line_groups_total",
        ]:
            self.assertIn(key, mpe_h_text, msg=f"{key} missing from MultiCorePE.h")
            self.assertIn(key, mpe_cc_text, msg=f"{key} missing from MultiCorePE.cc")

        for key in [
            "retire_obs.gcss_qni_head_wait_episodes_total",
            "retire_obs.gcss_qni_head_wait_cycles_max",
            "retire_obs.gcss_qni_vlf_younger_ahead_depth_total",
            "retire_obs.gcss_qni_vlf_younger_ahead_depth_samples_total",
            "retire_obs.gcss_qni_vlf_younger_ahead_depth_max",
            "retire_obs.gcss_qni_issue_deferred_total",
            "retire_obs.gcss_qni_pending_direct_queue_residency_cycles_total",
            "retire_obs.gcss_qni_pending_direct_queue_residency_samples_total",
            "retire_obs.gcss_qni_pending_direct_queue_residency_cycles_max",
            "retire_obs.begin_apply_windows_total",
            "retire_obs.begin_apply_prev_edges_total",
            "retire_obs.begin_apply_outstanding_carryin_total",
            "retire_obs.begin_apply_outstanding_carryin_windows_total",
            "retire_obs.begin_apply_loader_not_ready_windows_total",
            "retire_obs.edge_retire_registered_total",
            "retire_obs.edge_retire_retired_total",
            "retire_obs.end_scatter_gcss_vlf_issue_queue_residual_total",
            "retire_obs.end_scatter_pending_direct_reads_residual_total",
            "retire_obs.end_scatter_outstanding_residual_total",
            "retire_obs.end_scatter_residual_work_windows_total",
            "retire_obs.gcss_vlf_issue_prepare_total",
            "retire_obs.gcss_vlf_issue_edges_total",
            "retire_obs.gcss_vlf_issue_reorder_trigger_total",
            "retire_obs.gcss_vlf_issue_line_groups_total",
        ]:
            self.assertIn(key, pe_sub_cc_text, msg=f"{key} missing from SnnPESubComponent.cc")

        for key in [
            "gas_retire_samepost_blocked_edges_total",
            "gas_retire_crosspost_blocked_edges_total",
            "gas_retire_policy_loss_cycles_total",
            "gas_retire_policy_loss_edges_total",
        ]:
            self.assertIn(key, mpe_h_text, msg=f"{key} missing from MultiCorePE.h")
            self.assertIn(key, mpe_cc_text, msg=f"{key} missing from MultiCorePE.cc")
            self.assertIn(key, pe_sub_h_text, msg=f"{key} missing from SnnPESubComponent.h")
            self.assertIn(key, pe_sub_cc_text, msg=f"{key} missing from SnnPESubComponent.cc")
            self.assertIn(key, pe_sub_stats_block, msg=f"{key} missing from SnnPESubComponent ELI stats")

        for key in [
            "gas_retire_samepost_blocked_edges_total",
            "gas_retire_crosspost_blocked_edges_total",
            "gas_retire_policy_loss_cycles_total",
            "gas_retire_policy_loss_edges_total",
        ]:
            self.assertIn(key, pe_agg_h_text, msg=f"{key} missing from IPeAggregation.h")

    def test_core_step_ledger_is_plumbed_into_multicorepe_and_subcomponent(self):
        mpe_h_text = self.mpe_h.read_text(encoding="utf-8")
        mpe_cc_text = self.mpe_cc.read_text(encoding="utf-8")
        pe_sub_cc_text = self.pe_sub_cc.read_text(encoding="utf-8")

        for key in [
            "core_stage_marks_",
            "core_step_perf_",
            "recordCoreStepGasStat",
            "recordCoreStepRetireStat",
            "recordCoreStepApplyScatter",
            "getOrCreateCoreStepPerf_",
            "core_stage_events_db.csv",
            "core_step_perf_db.csv",
            "core,seq",
        ]:
            self.assertIn(key, mpe_h_text + "\n" + mpe_cc_text, msg=f"{key} missing from MultiCorePE core ledger plumbing")

        for key in [
            "recordCoreStepGasStat",
            "recordCoreStepRetireStat",
            "recordCoreStepApplyScatter",
            "core_id_",
        ]:
            self.assertIn(key, pe_sub_cc_text, msg=f"{key} missing from SnnPESubComponent core ledger plumbing")

    def test_gcss_vlf_issue_queue_tags_retire_source_as_gcss_before_issue(self):
        wms_cc = (self.repo / "sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc").read_text(encoding="utf-8")
        self.assertIn(
            "registerEdgeRetire_(post_local, pre_global, count, EdgeSrc::GCSS)",
            wms_cc,
            msg="GCSS-VLF queue should tag retire source as GCSS at queue-build time",
        )

    def test_gcss_vlf_banded_line_fair_uses_age_banded_line_chunks(self):
        wms_cc = (self.repo / "sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc").read_text(encoding="utf-8")
        banded_section = wms_cc.split('if (queue_policy == "banded_line_fair") {', 1)[1].split("    }\n\n    bool reordered =", 1)[0]
        chunk_sort_marker = "std::stable_sort(line_chunks.begin(), line_chunks.end(),"
        self.assertIn(
            chunk_sort_marker,
            banded_section,
            msg="banded_line_fair should sort explicit line_chunks instead of only reordering entries inside a line",
        )
        chunk_sort = banded_section.split(chunk_sort_marker, 1)[1].split("});", 1)[0]
        chunk_split_key = "line_chunks.back().age_band != age_band"
        chunk_min_retire_key = "if (a.chunk_min_retire_seq != b.chunk_min_retire_seq)"

        self.assertIn(
            "line_chunks",
            banded_section,
            msg="banded_line_fair should explicitly build age-banded line chunks during queue construction",
        )
        self.assertIn(
            chunk_split_key,
            banded_section,
            msg="banded_line_fair should split a cacheline into separate chunks when age_band changes",
        )
        self.assertIn(
            "line_id",
            banded_section,
            msg="banded_line_fair should keep cacheline identity on each chunk",
        )
        self.assertIn(
            "if (a.age_band != b.age_band) return a.age_band < b.age_band;",
            chunk_sort,
            msg="banded_line_fair should order chunks by age_band first",
        )
        self.assertIn(
            "if (a.line_id != b.line_id) return a.line_id < b.line_id;",
            chunk_sort,
            msg="banded_line_fair should keep locality ordering inside each age_band by line_id",
        )
        self.assertIn(
            chunk_min_retire_key,
            chunk_sort,
            msg="banded_line_fair should use chunk_min_retire_seq as the stable tie-breaker within a band+line slot",
        )
        self.assertNotIn(
            "std::stable_sort(group.entries.begin(), group.entries.end(),",
            banded_section,
            msg="banded_line_fair should no longer be the weak intra-line-only reorder variant",
        )

    def test_weight_memory_on_clock_tick_keeps_retire_path_observe_only(self):
        wms_cc = (self.repo / "sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc").read_text(encoding="utf-8")
        on_clock_tick = wms_cc.split("void WeightMemorySubsystem::onClockTick(uint64_t now_cycle) {", 1)[1].split("\n}\n\nWeightMemorySubsystem::IssueStatus", 1)[0]

        self.assertIn(
            "updateRetireHolStatsOnTick_();",
            on_clock_tick,
            msg="onClockTick should keep per-tick retire HOL observability accounting",
        )
        self.assertNotIn(
            "tryRetireEdges_();",
            on_clock_tick,
            msg="onClockTick must not actively retire edges; retire remains event-driven to preserve baseline semantics",
        )

    def test_gcss_phase_breakdown_switch_is_plumbed_end_to_end(self):
        wms_h_text = self.wms_h.read_text(encoding="utf-8")
        pe_sub_h_text = self.pe_sub_h.read_text(encoding="utf-8")
        pe_sub_cc_text = self.pe_sub_cc.read_text(encoding="utf-8")
        mesh_config_text = self.mesh_config_py.read_text(encoding="utf-8")
        mesh_build_text = self.mesh_build_py.read_text(encoding="utf-8")

        self.assertIn(
            "experimental_gcss_phase_breakdown_enable",
            wms_h_text,
            msg="WeightMemorySubsystem should expose experimental_gcss_phase_breakdown_enable in OrchestratorConfig",
        )
        self.assertIn(
            "experimental_gcss_phase_breakdown_enable",
            pe_sub_h_text,
            msg="SnnPESubComponent params should document experimental_gcss_phase_breakdown_enable",
        )
        self.assertIn(
            "experimental_gcss_phase_breakdown_enable",
            pe_sub_cc_text,
            msg="SnnPESubComponent should forward experimental_gcss_phase_breakdown_enable into OrchestratorConfig",
        )
        self.assertIn(
            "MESH_EXPERIMENTAL_GCSS_PHASE_BREAKDOWN_ENABLE",
            mesh_config_text,
            msg="mesh config should accept MESH_EXPERIMENTAL_GCSS_PHASE_BREAKDOWN_ENABLE override",
        )
        self.assertIn(
            "experimental_gcss_phase_breakdown_enable",
            mesh_build_text,
            msg="mesh build should pass experimental_gcss_phase_breakdown_enable to core params/effective config",
        )

    def test_shadow_per_post_retire_switch_and_fields_are_plumbed_end_to_end(self):
        wms_h_text = self.wms_h.read_text(encoding="utf-8")
        mpe_h_text = self.mpe_h.read_text(encoding="utf-8")
        mpe_cc_text = self.mpe_cc.read_text(encoding="utf-8")
        pe_agg_h_text = self.pe_agg_h.read_text(encoding="utf-8")
        pe_sub_h_text = self.pe_sub_h.read_text(encoding="utf-8")
        pe_sub_cc_text = self.pe_sub_cc.read_text(encoding="utf-8")
        mesh_config_text = self.mesh_config_py.read_text(encoding="utf-8")
        mesh_build_text = self.mesh_build_py.read_text(encoding="utf-8")

        for key in [
            "experimental_retire_shadow_per_post_enable",
            "shadow_per_post_recoverable_cycles_total",
            "shadow_per_post_recoverable_edges_total",
            "shadow_per_post_ready_posts_peak",
            "shadow_per_post_committable_edges_peak",
        ]:
            self.assertIn(key, wms_h_text, msg=f"{key} missing from WeightMemorySubsystem.h")

        for key in [
            "experimental_retire_shadow_per_post_enable",
            "MESH_EXPERIMENTAL_RETIRE_SHADOW_PER_POST_ENABLE",
        ]:
            self.assertIn(key, mesh_config_text + "\n" + mesh_build_text, msg=f"{key} missing from mesh config/build plumbing")

        self.assertIn(
            "experimental_retire_shadow_per_post_enable",
            pe_sub_h_text,
            msg="SnnPESubComponent params should document experimental_retire_shadow_per_post_enable",
        )
        self.assertIn(
            "experimental_retire_shadow_per_post_enable",
            pe_sub_cc_text,
            msg="SnnPESubComponent should forward experimental_retire_shadow_per_post_enable into OrchestratorConfig",
        )

        for key in [
            "retire_shadow_per_post_recoverable_cycles_total",
            "retire_shadow_per_post_recoverable_edges_total",
            "retire_shadow_per_post_ready_posts_peak",
            "retire_shadow_per_post_committable_edges_peak",
        ]:
            self.assertIn(key, mpe_h_text, msg=f"{key} missing from MultiCorePE.h")
            self.assertIn(key, mpe_cc_text, msg=f"{key} missing from MultiCorePE.cc")
            self.assertIn(key, pe_agg_h_text, msg=f"{key} missing from IPeAggregation.h")

    def test_gcss_vlf_bounded_rescue_is_not_mixed_back_into_snndl_mainline(self):
        wms_h_text = self.wms_h.read_text(encoding="utf-8")
        pe_sub_h_text = self.pe_sub_h.read_text(encoding="utf-8")
        pe_sub_cc_text = self.pe_sub_cc.read_text(encoding="utf-8")

        for key in [
            "experimental_gcss_vlf_bounded_rescue_enable",
            "experimental_gcss_vlf_bounded_rescue_scan_limit",
            "experimental_gcss_vlf_bounded_rescue_head_wait_cycles",
            "experimental_gcss_vlf_bounded_rescue_depth_threshold",
        ]:
            self.assertNotIn(key, wms_h_text, msg=f"{key} should not remain in WeightMemorySubsystem.h")
            self.assertNotIn(key, pe_sub_h_text, msg=f"{key} should not remain in SnnPESubComponent.h")
            self.assertNotIn(key, pe_sub_cc_text, msg=f"{key} should not remain in SnnPESubComponent.cc")

        issue_from_edges = wms_h_text.split("if (gcss_mode && isGcssValueOnlyPreMphfMode_()) {", 1)[1].split(
            "            return;\n        }\n\n        while (canIssueMoreReads_()) {", 1
        )[0]
        self.assertIn(
            "popNextGcssVlfIssueEntry_(",
            issue_from_edges,
            msg="GCSS pre-MPHF issue path should still use the shared queue-pop helper after bounded rescue removal",
        )

    def test_gcss_vlf_banded_line_fair_policy_is_plumbed_end_to_end(self):
        wms_h_text = self.wms_h.read_text(encoding="utf-8")
        wms_cc_text = self.wms_cc.read_text(encoding="utf-8")
        pe_sub_h_text = self.pe_sub_h.read_text(encoding="utf-8")
        pe_sub_cc_text = self.pe_sub_cc.read_text(encoding="utf-8")
        mesh_config_text = self.mesh_config_py.read_text(encoding="utf-8")
        mesh_build_text = self.mesh_build_py.read_text(encoding="utf-8")
        mesh_runtime_text = self.mesh_runtime_py.read_text(encoding="utf-8")
        mesh_spec_text = self.mesh_spec_py.read_text(encoding="utf-8")
        mesh_defaults_text = self.mesh_defaults_py.read_text(encoding="utf-8")

        for key in [
            "experimental_gcss_vlf_queue_policy",
            "experimental_gcss_vlf_fair_band_size",
            "local_age_rank",
        ]:
            self.assertIn(key, wms_h_text, msg=f"{key} missing from WeightMemorySubsystem.h")

        for key in [
            "gcss_vlf_active_line_valid_",
            "gcss_vlf_active_line_id_",
            "popBandedLineFairIssueEntry_",
        ]:
            self.assertNotIn(key, wms_h_text, msg=f"{key} should not remain in the queue-build-only banded_line_fair path")

        for key in [
            "experimental_gcss_vlf_queue_policy",
            "experimental_gcss_vlf_fair_band_size",
        ]:
            self.assertIn(key, pe_sub_h_text, msg=f"{key} missing from SnnPESubComponent.h")
            self.assertIn(key, pe_sub_cc_text, msg=f"{key} missing from SnnPESubComponent.cc")
            self.assertIn(key, mesh_build_text, msg=f"{key} missing from mesh build plumbing")
            self.assertIn(key, mesh_runtime_text, msg=f"{key} missing from mesh runtime plumbing")
            self.assertIn(key, mesh_spec_text, msg=f"{key} missing from mesh spec plumbing")

        for key in [
            "GCSS_VLF_QUEUE_POLICY",
            "GCSS_VLF_FAIR_BAND_SIZE",
            "MESH_EXPERIMENTAL_GCSS_VLF_QUEUE_POLICY",
            "MESH_EXPERIMENTAL_GCSS_VLF_FAIR_BAND_SIZE",
        ]:
            self.assertIn(key, mesh_config_text, msg=f"{key} missing from mesh config override plumbing")

        for key in [
            "GCSS_VLF_QUEUE_POLICY",
            "GCSS_VLF_FAIR_BAND_SIZE",
        ]:
            self.assertIn(key, mesh_defaults_text, msg=f"{key} missing from legacy defaults")

        for key in [
            "banded_line_fair",
            "line_id",
            "local_age_rank",
            "line_chunks",
            "age_band",
            "chunk_min_retire_seq",
        ]:
            self.assertIn(key, wms_cc_text, msg=f"{key} missing from queue policy implementation")

    def test_banded_line_fair_keeps_issue_path_queue_build_only(self):
        wms_h_text = self.wms_h.read_text(encoding="utf-8")
        wms_cc_text = self.wms_cc.read_text(encoding="utf-8")

        self.assertIn(
            'if (queue_policy == "banded_line_fair") {',
            wms_cc_text,
            msg="banded_line_fair should still be rooted at queue-build policy selection",
        )
        self.assertNotIn(
            "shouldPauseGcssVlfIssueOnIssuedHeadHol_",
            wms_h_text,
            msg="banded_line_fair should not depend on an issued-head HOL pause helper",
        )
        self.assertNotIn(
            "gcss_vlf_active_line_valid_",
            wms_h_text,
            msg="banded_line_fair should not keep issue-time active-line scheduler state",
        )
        self.assertNotIn(
            "popBandedLineFairIssueEntry_",
            wms_cc_text,
            msg="banded_line_fair should not route issue selection through a separate issue-time scheduler",
        )
        self.assertIn(
            "out = std::move(gcss_vlf_issue_queue_.front());",
            wms_cc_text,
            msg="queue-build-only banded_line_fair should fall back to plain pop-front issue order when rescue is disabled",
        )

    def test_pulse_observe_only_pe_plumbing_is_exposed_to_mesh_template(self):
        mpe_h_text = self.mpe_h.read_text(encoding="utf-8")
        pe_sub_cc_text = self.pe_sub_cc.read_text(encoding="utf-8")
        mesh_config_text = self.mesh_config_py.read_text(encoding="utf-8")
        mesh_build_text = self.mesh_build_py.read_text(encoding="utf-8")
        mesh_runtime_text = self.mesh_runtime_py.read_text(encoding="utf-8")
        mesh_defaults_text = self.mesh_defaults_py.read_text(encoding="utf-8")

        for key in [
            "pulse_enable",
            "pulse_observe_only",
            "pulse_ingress_enable",
            "pulse_agenda_observe_only",
            "pulse_ingress_entries",
            "pulse_core_queue_entries",
            "pulse_bypass_high_watermark_pct",
            "pulse_bypass_mode",
        ]:
            self.assertIn(key, mpe_h_text, msg=f"{key} missing from MultiCorePE.h")
            self.assertIn(key, mesh_build_text, msg=f"{key} missing from mesh build plumbing")
            self.assertIn(key, mesh_runtime_text, msg=f"{key} missing from mesh runtime plumbing")

        for key in [
            "pulse_enable",
            "pulse_agenda_observe_only",
        ]:
            self.assertIn(key, pe_sub_cc_text, msg=f"{key} missing from SnnPESubComponent.cc")

        for key in [
            "PULSE_ENABLE",
            "PULSE_OBSERVE_ONLY",
            "PULSE_INGRESS_ENABLE",
            "PULSE_AGENDA_OBSERVE_ONLY",
            "PULSE_INGRESS_ENTRIES",
            "PULSE_CORE_QUEUE_ENTRIES",
            "PULSE_BYPASS_HIGH_WATERMARK_PCT",
            "PULSE_BYPASS_MODE",
        ]:
            self.assertIn(key, mesh_defaults_text, msg=f"{key} missing from legacy defaults")

        for key in [
            "MESH_PULSE_ENABLE",
            "MESH_PULSE_OBSERVE_ONLY",
            "MESH_PULSE_INGRESS_ENABLE",
            "MESH_PULSE_AGENDA_OBSERVE_ONLY",
            "MESH_PULSE_INGRESS_ENTRIES",
            "MESH_PULSE_CORE_QUEUE_ENTRIES",
            "MESH_PULSE_BYPASS_HIGH_WATERMARK_PCT",
            "MESH_PULSE_BYPASS_MODE",
        ]:
            self.assertIn(key, mesh_config_text, msg=f"{key} missing from mesh config override plumbing")

    def test_pulse_statistics_are_declared_in_multicorepe_eli(self):
        mpe_h_text = self.mpe_h.read_text(encoding="utf-8")
        mpe_cc_text = self.mpe_cc.read_text(encoding="utf-8")
        mpe_stats_block = mpe_h_text.split("SST_ELI_DOCUMENT_STATISTICS(", 1)[1].split("\n    )", 1)[0]

        for key in [
            "pulse_ingress_packets_total",
            "pulse_ingress_spike_packets_total",
            "pulse_ingress_spikekey_packets_total",
            "pulse_ingress_spiketilekey_packets_total",
            "pulse_ingress_core_dispatch_total",
            "pulse_ingress_bypass_total",
            "pulse_ingress_pressure_cycles_total",
            "pulse_ingress_entries_peak",
            "pulse_core_queue_entries_peak",
            "pulse_agenda_candidates_total",
            "pulse_agenda_accepted_total",
            "pulse_agenda_rejected_total",
            "pulse_agenda_reject_gate_total",
            "pulse_correctness_ready_blocked_cycles_total",
            "pulse_correctness_scoreboard_occupancy_peak",
            "pulse_mfb_owner_eligible_total",
            "pulse_mfb_owner_launched_total",
            "pulse_mfb_preband_candidates_total",
            "pulse_mfb_preband_lines_selected_total",
            "pulse_mfb_preband_lines_owner_total",
            "pulse_mfb_preband_lines_join_only_total",
            "pulse_mfb_head_distance_sum_total",
            "pulse_mfb_head_distance_samples_total",
            "pulse_mfb_seed_to_first_demand_cycles_total",
            "pulse_mfb_seed_to_first_demand_samples_total",
            "pulse_mfb_seed_ready_before_demand_total",
            "pulse_mfb_seed_inflight_join_total",
        ]:
            self.assertIn(key, mpe_cc_text, msg=f"{key} missing from MultiCorePE.cc statistics registration")
            self.assertIn(key, mpe_stats_block, msg=f"{key} missing from MultiCorePE.h ELI statistics declaration")

    def test_pulse_control_statistics_are_declared_in_multicorepe_eli(self):
        mpe_h_text = self.mpe_h.read_text(encoding="utf-8")
        mpe_cc_text = self.mpe_cc.read_text(encoding="utf-8")
        mpe_stats_block = mpe_h_text.split("SST_ELI_DOCUMENT_STATISTICS(", 1)[1].split("\n    )", 1)[0]

        for key in [
            "pulse_control_messages_enqueued_total",
            "pulse_control_messages_dequeued_total",
            "pulse_control_frontier_export_total",
            "pulse_control_owner_announce_total",
            "pulse_control_join_request_total",
            "pulse_control_ready_fanout_total",
            "pulse_control_join_reject_total",
        ]:
            self.assertIn(key, mpe_cc_text, msg=f"{key} missing from MultiCorePE.cc statistics registration")
            self.assertIn(key, mpe_stats_block, msg=f"{key} missing from MultiCorePE.h ELI statistics declaration")

    def test_pulse_osa_metadata_object_mask_is_parsed_as_string_in_control_plane(self):
        pe_sub_cc_text = self.pe_sub_cc.read_text(encoding="utf-8")

        self.assertIn(
            'params.find<std::string>("pulse_osa_metadata_object_mask", "rowdescriptor")',
            pe_sub_cc_text,
            msg="SnnPESubComponent should read pulse_osa_metadata_object_mask as a string param with rowdescriptor default",
        )
        self.assertIn(
            'parsePulseMetadataObjectMask_(',
            pe_sub_cc_text,
            msg="SnnPESubComponent should parse pulse_osa_metadata_object_mask from string params before passing to WMS",
        )
        self.assertNotIn(
            'params.find<uint32_t>("pulse_osa_metadata_object_mask", 0u)',
            pe_sub_cc_text,
            msg="SnnPESubComponent should not parse pulse_osa_metadata_object_mask as uint32_t",
        )

    def test_pulse_gather_preband_statistics_are_declared_and_forwarded(self):
        mpe_h_text = self.mpe_h.read_text(encoding="utf-8")
        mpe_cc_text = self.mpe_cc.read_text(encoding="utf-8")
        pe_sub_h_text = self.pe_sub_h.read_text(encoding="utf-8")
        pe_sub_cc_text = self.pe_sub_cc.read_text(encoding="utf-8")
        mpe_stats_block = mpe_h_text.split("SST_ELI_DOCUMENT_STATISTICS(", 1)[1].split("\n    )", 1)[0]

        for key in [
            "pulse_mfb_gather_preband_enable",
            "pulse_mfb_gather_top_bands",
            "pulse_mfb_gather_lines_per_band",
            "pulse_mfb_gather_window_budget",
        ]:
            self.assertIn(key, pe_sub_h_text, msg=f"{key} missing from SnnPESubComponent.h params")
            self.assertIn(key, pe_sub_cc_text, msg=f"{key} missing from SnnPESubComponent.cc forwarding")

        for key in [
            "pulse_mfb_gather_owner_eligible_total",
            "pulse_mfb_gather_owner_launched_total",
            "pulse_mfb_gather_preband_candidates_total",
            "pulse_mfb_gather_preband_lines_selected_total",
            "pulse_mfb_gather_preband_lines_owner_total",
            "pulse_mfb_gather_preband_lines_join_only_total",
            "pulse_mfb_gather_head_distance_sum_total",
            "pulse_mfb_gather_head_distance_samples_total",
            "pulse_mfb_gather_seed_to_first_demand_cycles_total",
            "pulse_mfb_gather_seed_to_first_demand_samples_total",
            "pulse_mfb_gather_seed_ready_before_demand_total",
            "pulse_mfb_gather_seed_inflight_join_total",
            "pulse_mfb_gather_owner_lines_useful_total",
            "pulse_mfb_gather_owner_lines_dead_total",
        ]:
            self.assertIn(key, mpe_cc_text, msg=f"{key} missing from MultiCorePE.cc statistics registration")
            self.assertIn(key, mpe_stats_block, msg=f"{key} missing from MultiCorePE.h ELI statistics declaration")
            self.assertIn(key, pe_sub_cc_text, msg=f"{key} missing from SnnPESubComponent.cc pulse forwarding")

    def test_pulse_agenda_observability_is_core_plumbed_and_gated_when_disabled(self):
        wms_h_text = self.wms_h.read_text(encoding="utf-8")
        mesh_build_text = self.mesh_build_py.read_text(encoding="utf-8")

        pulse_obs_block = wms_h_text.split("PulseAgendaObservabilityStats pulseAgendaObservabilityStats() const {", 1)[1].split(
            "\n    }\n    void flushSramObservability", 1
        )[0]
        min_core_block = mesh_build_text.split("core_params = {", 1)[1].split("\n                }", 1)[0]
        full_core_block = mesh_build_text.rsplit("core_params = {", 1)[1].split("\n                }", 1)[0]

        self.assertIn(
            "if (!orch_.pulse_agenda_enable) return s;",
            pulse_obs_block,
            msg="pulse agenda observability stats should collapse to zero when pulse_agenda_enable=0",
        )

        for key in [
            '"pulse_enable": int(pulse_enable)',
            '"pulse_agenda_observe_only": int(pulse_agenda_observe_only)',
        ]:
            self.assertIn(key, min_core_block, msg=f"{key} missing from minimal core params")
            self.assertIn(key, full_core_block, msg=f"{key} missing from full core params")


if __name__ == "__main__":
    unittest.main()
