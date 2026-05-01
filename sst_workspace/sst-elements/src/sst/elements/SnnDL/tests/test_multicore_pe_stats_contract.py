import re
import unittest
from pathlib import Path


class MultiCorePEStatisticContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self._root = Path(__file__).resolve().parents[1]
        self._cc = self._root / "components" / "MultiCorePE.cc"
        self._header = self._root / "components" / "MultiCorePE.h"

    def _registered_statistics(self) -> set[str]:
        text = self._cc.read_text(encoding="utf-8")
        return set(re.findall(r'registerStatistic<[^>]+>\("([^"]+)"\)', text))

    def _eli_statistics(self) -> set[str]:
        text = self._header.read_text(encoding="utf-8")
        match = re.search(r"SST_ELI_DOCUMENT_STATISTICS\((.*?)\n\s*\)\n", text, re.S)
        self.assertIsNotNone(match, "MultiCorePE.h is missing SST_ELI_DOCUMENT_STATISTICS")
        assert match is not None
        return set(re.findall(r'\{"([^"]+)",', match.group(1)))

    def _assert_prefix_is_declared(self, prefix: str) -> None:
        registered = {name for name in self._registered_statistics() if name.startswith(prefix)}
        declared = {name for name in self._eli_statistics() if name.startswith(prefix)}
        self.assertTrue(registered, f"expected at least one registered statistic with prefix {prefix}")
        self.assertEqual(
            set(),
            registered - declared,
            f"registered statistics with prefix {prefix} must be declared in SST_ELI_DOCUMENT_STATISTICS",
        )

    def _assert_statistics_are_registered_and_declared(self, names: list[str]) -> None:
        registered = self._registered_statistics()
        declared = self._eli_statistics()
        missing_registered = sorted(set(names) - registered)
        missing_declared = sorted(set(names) - declared)
        self.assertEqual([], missing_registered, f"statistics must be registered: {missing_registered}")
        self.assertEqual([], missing_declared, f"statistics must be declared in ELI: {missing_declared}")

    def test_pulse_ingress_statistics_are_declared_in_eli(self) -> None:
        self._assert_prefix_is_declared("pulse_ingress_")

    def test_pulse_control_statistics_are_declared_in_eli(self) -> None:
        self._assert_prefix_is_declared("pulse_control_")

    def test_atlas_pod_metadata_statistics_are_declared_in_eli(self) -> None:
        self._assert_prefix_is_declared("atlas_pod_metadata_")

    def test_atlas_pod_owner_statistics_are_declared_in_eli(self) -> None:
        self._assert_prefix_is_declared("atlas_pod_owner_")

    def test_atlas_census_statistics_are_declared_in_eli(self) -> None:
        self._assert_prefix_is_declared("atlas_census_")

    def test_atlas_proxy_statistics_are_declared_in_eli(self) -> None:
        self._assert_prefix_is_declared("atlas_proxy_")

    def test_atlas_phase_statistics_are_declared_in_eli(self) -> None:
        self._assert_prefix_is_declared("atlas_phase_")

    def test_atlas_storage_map_statistics_are_declared_in_eli(self) -> None:
        self._assert_prefix_is_declared("atlas_storage_map_")

    def test_atlas_enable_state_statistics_are_registered_and_declared(self) -> None:
        self._assert_statistics_are_registered_and_declared(
            [
                "atlas_enable_state_local_storage_effective_total",
                "atlas_enable_state_pe_internal_cpe_effective_total",
                "atlas_enable_state_pe_internal_pod_effective_total",
                "atlas_enable_state_pe_internal_pod_metadata_effective_total",
                "atlas_enable_state_pe_internal_pod_owner_effective_total",
                "atlas_enable_state_pe_local_service_table_present_total",
                "atlas_enable_state_rowindex_effective_total",
                "atlas_enable_state_rowindex_gate_pulse_osa_total",
                "atlas_enable_state_rowindex_gate_metadata_txn_total",
                "atlas_enable_state_rowindex_gate_metadata_mask_total",
                "atlas_enable_state_rowindex_gate_pod_enable_total",
                "atlas_enable_state_rowindex_gate_pod_metadata_enable_total",
                "atlas_enable_state_rowindex_gate_pod_owner_enable_total",
                "atlas_enable_state_rowindex_gate_service_table_present_total",
                "atlas_enable_state_pulse_effective_total",
                "atlas_enable_state_pulse_fabric_present_total",
                "atlas_enable_state_pulse_observe_only_total",
                "atlas_enable_state_pulse_actual_ingress_effective_total",
                "atlas_enable_state_pulse_harbor_effective_total",
                "atlas_enable_state_pulse_descriptor_effective_total",
                "atlas_enable_state_pulse_descriptor_actual_effective_total",
                "atlas_enable_state_pulse_osa_effective_total",
                "atlas_enable_state_pulse_osa_shared_weight_owner_effective_total",
                "atlas_enable_state_pulse_osa_shared_weight_actual_effective_total",
                "atlas_enable_state_pe_weight_plane_present_total",
                "atlas_enable_state_pulse_osa_metadata_txn_effective_total",
                "atlas_enable_state_pulse_osa_metadata_ready_lease_effective_total",
                "atlas_enable_state_pulse_osa_metadata_mask_nonzero_total",
                "atlas_enable_state_control_runtime_produce_eligible_total",
                "atlas_enable_state_control_runtime_end_to_end_eligible_total",
            ]
        )

    def test_atlas_storage_authority_breakdown_statistics_are_registered_and_declared(self) -> None:
        self._assert_statistics_are_registered_and_declared(
            [
                "atlas_storage_map_weight_idx_private_authority_total",
                "atlas_storage_map_weight_idx_shared_mirror_only_total",
                "atlas_storage_map_weight_idx_shared_authority_active_total",
                "atlas_storage_map_weight_value_private_authority_total",
                "atlas_storage_map_weight_value_shared_mirror_only_total",
                "atlas_storage_map_weight_value_shared_authority_active_total",
            ]
        )

    def test_atlas_shared_weight_census_statistics_are_registered_and_declared(self) -> None:
        self._assert_statistics_are_registered_and_declared(
            [
                "atlas_shared_weight_census_state_absent_total",
                "atlas_shared_weight_census_state_owner_scope_off_total",
                "atlas_shared_weight_census_state_mirror_only_total",
                "atlas_shared_weight_census_state_actual_owner_total",
                "atlas_shared_weight_census_absent_reason_workload_ineligible_total",
                "atlas_shared_weight_census_absent_reason_local_storage_gate_total",
                "atlas_shared_weight_census_absent_reason_pulse_osa_gate_total",
                "atlas_shared_weight_census_absent_reason_owner_request_gate_total",
            ]
        )

    def test_atlas_control_runtime_statistics_are_registered_and_declared(self) -> None:
        self._assert_statistics_are_registered_and_declared(
            [
                "atlas_control_runtime_produced_frontier_export_total",
                "atlas_control_runtime_produced_owner_announce_total",
                "atlas_control_runtime_produced_join_request_total",
                "atlas_control_runtime_produced_ready_fanout_total",
                "atlas_control_runtime_produced_join_reject_total",
                "atlas_control_runtime_queued_frontier_export_total",
                "atlas_control_runtime_queued_owner_announce_total",
                "atlas_control_runtime_queued_join_request_total",
                "atlas_control_runtime_queued_ready_fanout_total",
                "atlas_control_runtime_queued_join_reject_total",
                "atlas_control_runtime_consumed_frontier_export_total",
                "atlas_control_runtime_consumed_owner_announce_total",
                "atlas_control_runtime_consumed_join_request_total",
                "atlas_control_runtime_consumed_ready_fanout_total",
                "atlas_control_runtime_consumed_join_reject_total",
                "atlas_control_runtime_backlog_messages_current",
                "atlas_control_runtime_backlog_messages_peak",
                "atlas_control_runtime_backlog_cycles_total",
                "atlas_control_runtime_produced_any_nonzero_total",
                "atlas_control_runtime_queued_any_nonzero_total",
                "atlas_control_runtime_consumed_any_nonzero_total",
                "atlas_control_runtime_backlog_any_nonzero_total",
                "atlas_control_runtime_all_zero_total",
                "atlas_control_runtime_state_fabric_absent_total",
                "atlas_control_runtime_state_fabric_present_idle_total",
                "atlas_control_runtime_state_produced_without_queue_total",
                "atlas_control_runtime_state_queued_without_consume_total",
                "atlas_control_runtime_state_consumed_active_total",
            ]
        )

    def test_atlas_activation_gate_statistics_are_registered_and_declared(self) -> None:
        self._assert_statistics_are_registered_and_declared(
            [
                "atlas_activation_gate_workload_pure_snn_datapath_eligible",
                "atlas_activation_gate_local_storage_enable",
                "atlas_activation_gate_pulse_requested",
                "atlas_activation_gate_pulse_effective",
                "atlas_activation_gate_pulse_fabric_constructed",
                "atlas_activation_gate_pulse_observe_only_effective",
                "atlas_activation_gate_pulse_actual_ingress_eligible",
                "atlas_activation_gate_pulse_harbor_enable_effective",
                "atlas_activation_gate_pulse_descriptor_enable_effective",
                "atlas_activation_gate_pulse_descriptor_actual_requested",
                "atlas_activation_gate_pulse_descriptor_actual_effective",
                "atlas_activation_gate_pulse_osa_requested",
                "atlas_activation_gate_pulse_osa_effective",
                "atlas_activation_gate_shared_weight_owner_requested",
                "atlas_activation_gate_shared_weight_owner_effective",
                "atlas_activation_gate_shared_weight_plane_constructed",
                "atlas_activation_gate_shared_weight_actual_owner_requested",
                "atlas_activation_gate_shared_weight_actual_owner_effective",
                "atlas_activation_gate_pe_internal_pod_requested",
                "atlas_activation_gate_rowindex_requested",
                "atlas_activation_gate_pe_internal_pod_metadata_requested",
                "atlas_activation_gate_pe_internal_pod_owner_requested",
                "atlas_activation_gate_rowindex_constructed",
                "atlas_activation_gate_pod_metadata_plane_constructed",
                "atlas_activation_gate_pod_owner_table_constructed",
                "atlas_activation_gate_service_table_constructed",
            ]
        )

    def test_snnpe_metadata_object_mask_is_parsed_from_string_param(self) -> None:
        snnpe_cc = (self._root / "control" / "SnnPESubComponent.cc").read_text(encoding="utf-8")
        self.assertIn("parsePulseMetadataObjectMask_", snnpe_cc)
        self.assertIn('params.find<std::string>("pulse_osa_metadata_object_mask"', snnpe_cc)
        self.assertNotIn('params.find<uint32_t>("pulse_osa_metadata_object_mask"', snnpe_cc)


if __name__ == "__main__":
    unittest.main()
