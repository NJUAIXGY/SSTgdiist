from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.modules.setdefault("sst", types.SimpleNamespace())

from sst_dram_si.mesh_template.runtime import _EnvPatch
from sst_dram_si.mesh_template.runtime import resolve_runtime


class _FakeSST:
    def setStatisticLoadLevel(self, _level):
        pass

    def setStatisticOutput(self, _output_type):
        pass

    def setStatisticOutputOptions(self, _opts):
        pass

    def enableAllStatisticsForComponentType(self, *_args, **_kwargs):
        pass

    def enableAllStatisticsForAllComponents(self, *_args, **_kwargs):
        pass


class RuntimePulseConfigTests(unittest.TestCase):
    def _make_script_file(self, root: Path) -> Path:
        script_dir = root / "sst_dram_si"
        script_dir.mkdir(parents=True, exist_ok=True)
        (script_dir / "weights").mkdir(parents=True, exist_ok=True)
        script_file = script_dir / "test_mesh_4x4.py"
        script_file.write_text("from __future__ import annotations\n", encoding="utf-8")
        return script_file

    def _write_spec_file(self, root: Path, payload: dict) -> Path:
        spec_path = root / "mesh_spec.json"
        spec_path.write_text(json.dumps(payload), encoding="utf-8")
        return spec_path

    def test_pulse_env_is_ignored_without_experimental_enable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            run_dir = root / "run_noexp"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_GLOBAL_STEP_SYNC": "0",
                    "MESH_PULSE_ENABLE": "1",
                    "MESH_PULSE_DOMAIN_RETIRE_ENABLE": "1",
                    "MESH_PULSE_DOMAIN_RETIRE_OBSERVE_ONLY": "1",
                    "MESH_PULSE_DOMAIN_RETIRE_MODE": "per_post",
                    "MESH_PULSE_DOMAIN_RETIRE_RELEASE_BUDGET": "16",
                    "MESH_PULSE_INGRESS_ENTRIES": "64",
                    "MESH_PULSE_CORE_QUEUE_ENTRIES": "32",
                    "MESH_PULSE_BYPASS_MODE": "high_watermark",
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            pulse = dict(rt.mesh_cfg.get("pulse", {}) or {})
            self.assertEqual(pulse.get("enable"), 0)
            self.assertEqual(pulse.get("ingress_entries"), 0)
            self.assertEqual(pulse.get("core_queue_entries"), 0)
            self.assertEqual(pulse.get("bypass_mode"), "disabled")
            self.assertEqual(pulse.get("domain_retire_enable"), 0)
            self.assertEqual(pulse.get("domain_retire_observe_only"), 1)
            self.assertEqual(pulse.get("domain_retire_mode"), "per_post")
            self.assertEqual(pulse.get("domain_retire_release_budget"), 0)

    def test_pulse_env_is_exported_when_experimental_enable_is_on(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            run_dir = root / "run_exp"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_GLOBAL_STEP_SYNC": "0",
                    "MESH_EXPERIMENTAL_ENABLE": "1",
                    "MESH_PULSE_ENABLE": "1",
                    "MESH_PULSE_OBSERVE_ONLY": "1",
                    "MESH_PULSE_INGRESS_ENABLE": "1",
                    "MESH_PULSE_AGENDA_OBSERVE_ONLY": "1",
                    "MESH_PULSE_HARBOR_ENABLE": "1",
                    "MESH_PULSE_DESCRIPTOR_ENABLE": "1",
                    "MESH_PULSE_DESCRIPTOR_PACKET_MIN": "4",
                    "MESH_PULSE_INGRESS_ENTRIES": "64",
                    "MESH_PULSE_CORE_QUEUE_ENTRIES": "32",
                    "MESH_PULSE_BYPASS_HIGH_WATERMARK_PCT": "88",
                    "MESH_PULSE_BYPASS_MODE": "high_watermark",
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            pulse = dict(rt.mesh_cfg.get("pulse", {}) or {})
            self.assertEqual(pulse.get("enable"), 1)
            self.assertEqual(pulse.get("observe_only"), 1)
            self.assertEqual(pulse.get("ingress_enable"), 1)
            self.assertEqual(pulse.get("agenda_observe_only"), 1)
            self.assertEqual(pulse.get("harbor_enable"), 1)
            self.assertEqual(pulse.get("descriptor_enable"), 1)
            self.assertEqual(pulse.get("descriptor_packet_min"), 4)
            self.assertEqual(pulse.get("ingress_entries"), 64)
            self.assertEqual(pulse.get("core_queue_entries"), 32)
            self.assertEqual(pulse.get("bypass_high_watermark_pct"), 88)
            self.assertEqual(pulse.get("bypass_mode"), "high_watermark")

    def test_pulse_actual_ingress_env_is_exported_when_observe_only_is_off(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            run_dir = root / "run_actual"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_GLOBAL_STEP_SYNC": "0",
                    "MESH_EXPERIMENTAL_ENABLE": "1",
                    "MESH_PULSE_ENABLE": "1",
                    "MESH_PULSE_OBSERVE_ONLY": "0",
                    "MESH_PULSE_INGRESS_ENABLE": "1",
                    "MESH_PULSE_AGENDA_OBSERVE_ONLY": "1",
                    "MESH_PULSE_INGRESS_ENTRIES": "32",
                    "MESH_PULSE_CORE_QUEUE_ENTRIES": "32",
                    "MESH_PULSE_BYPASS_HIGH_WATERMARK_PCT": "50",
                    "MESH_PULSE_BYPASS_MODE": "high_watermark",
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            pulse = dict(rt.mesh_cfg.get("pulse", {}) or {})
            self.assertEqual(pulse.get("enable"), 1)
            self.assertEqual(pulse.get("observe_only"), 0)
            self.assertEqual(pulse.get("ingress_enable"), 1)
            self.assertEqual(pulse.get("agenda_observe_only"), 1)
            self.assertEqual(pulse.get("ingress_entries"), 32)
            self.assertEqual(pulse.get("core_queue_entries"), 32)
            self.assertEqual(pulse.get("bypass_high_watermark_pct"), 50)
            self.assertEqual(pulse.get("bypass_mode"), "high_watermark")

    def test_pulse_domain_retire_env_is_exported_when_experimental_enable_is_on(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            run_dir = root / "run_domain_retire"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_GLOBAL_STEP_SYNC": "0",
                    "MESH_EXPERIMENTAL_ENABLE": "1",
                    "MESH_PULSE_ENABLE": "1",
                    "MESH_PULSE_DOMAIN_RETIRE_ENABLE": "1",
                    "MESH_PULSE_DOMAIN_RETIRE_OBSERVE_ONLY": "1",
                    "MESH_PULSE_DOMAIN_RETIRE_MODE": "per_post",
                    "MESH_PULSE_DOMAIN_RETIRE_RELEASE_BUDGET": "24",
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            pulse = dict(rt.mesh_cfg.get("pulse", {}) or {})
            self.assertEqual(pulse.get("enable"), 1)
            self.assertEqual(pulse.get("domain_retire_enable"), 1)
            self.assertEqual(pulse.get("domain_retire_observe_only"), 1)
            self.assertEqual(pulse.get("domain_retire_mode"), "per_post")
            self.assertEqual(pulse.get("domain_retire_release_budget"), 24)

    def test_pulse_frontier_observe_env_is_exported_when_experimental_enable_is_on(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            run_dir = root / "run_frontier"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_GLOBAL_STEP_SYNC": "0",
                    "MESH_EXPERIMENTAL_ENABLE": "1",
                    "MESH_PULSE_ENABLE": "1",
                    "MESH_PULSE_OBSERVE_ONLY": "1",
                    "MESH_PULSE_AGENDA_OBSERVE_ONLY": "1",
                    "MESH_PULSE_FRONTIER_OBSERVE_ENABLE": "1",
                    "MESH_PULSE_FRONTIER_TOP_LINES": "24",
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            pulse = dict(rt.mesh_cfg.get("pulse", {}) or {})
            self.assertEqual(pulse.get("enable"), 1)
            self.assertEqual(pulse.get("frontier_observe_enable"), 1)
            self.assertEqual(pulse.get("frontier_top_lines"), 24)

    def test_pulse_metadata_frontier_observe_env_is_exported_when_experimental_enable_is_on(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            run_dir = root / "run_metadata_frontier"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_GLOBAL_STEP_SYNC": "0",
                    "MESH_EXPERIMENTAL_ENABLE": "1",
                    "MESH_PULSE_ENABLE": "1",
                    "MESH_PULSE_OBSERVE_ONLY": "1",
                    "MESH_PULSE_AGENDA_OBSERVE_ONLY": "1",
                    "MESH_PULSE_METADATA_FRONTIER_OBSERVE_ENABLE": "1",
                    "MESH_PULSE_METADATA_FRONTIER_TOP_ITEMS": "48",
                    "MESH_PULSE_METADATA_FRONTIER_BAND_SLOTS": "256",
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            pulse = dict(rt.mesh_cfg.get("pulse", {}) or {})
            self.assertEqual(pulse.get("enable"), 1)
            self.assertEqual(pulse.get("metadata_frontier_observe_enable"), 1)
            self.assertEqual(pulse.get("metadata_frontier_top_items"), 48)
            self.assertEqual(pulse.get("metadata_frontier_band_slots"), 256)

    def test_pulse_metadata_seed_env_is_exported_when_experimental_enable_is_on(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            run_dir = root / "run_metadata_seed"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_GLOBAL_STEP_SYNC": "0",
                    "MESH_EXPERIMENTAL_ENABLE": "1",
                    "MESH_PULSE_ENABLE": "1",
                    "MESH_PULSE_OBSERVE_ONLY": "0",
                    "MESH_PULSE_DESCRIPTOR_ACTUAL_ENABLE": "1",
                    "MESH_PULSE_METADATA_SEED_ENABLE": "1",
                    "MESH_PULSE_METADATA_SEED_TOP_BASES": "24",
                    "MESH_PULSE_METADATA_SEED_WINDOW_BUDGET": "6",
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            pulse = dict(rt.mesh_cfg.get("pulse", {}) or {})
            self.assertEqual(pulse.get("enable"), 1)
            self.assertEqual(pulse.get("metadata_seed_enable"), 1)
            self.assertEqual(pulse.get("metadata_seed_top_bases"), 24)
            self.assertEqual(pulse.get("metadata_seed_window_budget"), 6)

    def test_pulse_mfb_preband_seed_env_is_exported_when_experimental_enable_is_on(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            run_dir = root / "run_mfb_preband"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_GLOBAL_STEP_SYNC": "0",
                    "MESH_EXPERIMENTAL_ENABLE": "1",
                    "MESH_PULSE_ENABLE": "1",
                    "MESH_PULSE_OBSERVE_ONLY": "0",
                    "MESH_PULSE_DESCRIPTOR_ACTUAL_ENABLE": "1",
                    "MESH_PULSE_MFB_PREBAND_SEED_ENABLE": "1",
                    "MESH_PULSE_MFB_PREBAND_TOP_BANDS": "24",
                    "MESH_PULSE_MFB_PREBAND_LINES_PER_BAND": "4",
                    "MESH_PULSE_MFB_PREBAND_WINDOW_BUDGET": "6",
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            pulse = dict(rt.mesh_cfg.get("pulse", {}) or {})
            self.assertEqual(pulse.get("enable"), 1)
            self.assertEqual(pulse.get("descriptor_actual_enable"), 1)
            self.assertEqual(pulse.get("mfb_preband_seed_enable"), 1)
            self.assertEqual(pulse.get("mfb_preband_top_bands"), 24)
            self.assertEqual(pulse.get("mfb_preband_lines_per_band"), 4)
            self.assertEqual(pulse.get("mfb_preband_window_budget"), 6)

    def test_pulse_mfb_preband_band_slots_env_is_exported_when_experimental_enable_is_on(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            run_dir = root / "run_mfb_preband_band_slots"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_GLOBAL_STEP_SYNC": "0",
                    "MESH_EXPERIMENTAL_ENABLE": "1",
                    "MESH_PULSE_ENABLE": "1",
                    "MESH_PULSE_OBSERVE_ONLY": "0",
                    "MESH_PULSE_DESCRIPTOR_ACTUAL_ENABLE": "1",
                    "MESH_PULSE_METADATA_FRONTIER_BAND_SLOTS": "128",
                    "MESH_PULSE_MFB_PREBAND_BAND_SLOTS": "80",
                    "MESH_PULSE_MFB_GATHER_PREBAND_ENABLE": "1",
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            pulse = dict(rt.mesh_cfg.get("pulse", {}) or {})
            self.assertEqual(pulse.get("enable"), 1)
            self.assertEqual(pulse.get("descriptor_actual_enable"), 1)
            self.assertEqual(pulse.get("metadata_frontier_band_slots"), 128)
            self.assertEqual(pulse.get("mfb_preband_band_slots"), 80)

    def test_pulse_mfb_gather_preband_env_is_exported_when_experimental_enable_is_on(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            run_dir = root / "run_mfb_gather_preband"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_GLOBAL_STEP_SYNC": "0",
                    "MESH_EXPERIMENTAL_ENABLE": "1",
                    "MESH_PULSE_ENABLE": "1",
                    "MESH_PULSE_OBSERVE_ONLY": "0",
                    "MESH_PULSE_DESCRIPTOR_ACTUAL_ENABLE": "1",
                    "MESH_PULSE_MFB_GATHER_PREBAND_ENABLE": "1",
                    "MESH_PULSE_MFB_GATHER_TOP_BANDS": "24",
                    "MESH_PULSE_MFB_GATHER_LINES_PER_BAND": "4",
                    "MESH_PULSE_MFB_GATHER_WINDOW_BUDGET": "6",
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            pulse = dict(rt.mesh_cfg.get("pulse", {}) or {})
            self.assertEqual(pulse.get("enable"), 1)
            self.assertEqual(pulse.get("descriptor_actual_enable"), 1)
            self.assertEqual(pulse.get("mfb_gather_preband_enable"), 1)
            self.assertEqual(pulse.get("mfb_gather_top_bands"), 24)
            self.assertEqual(pulse.get("mfb_gather_lines_per_band"), 4)
            self.assertEqual(pulse.get("mfb_gather_window_budget"), 6)

    def test_pulse_mfb_gather_barrier_env_is_exported_when_experimental_enable_is_on(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            run_dir = root / "run_mfb_gather_barrier"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_GLOBAL_STEP_SYNC": "0",
                    "MESH_EXPERIMENTAL_ENABLE": "1",
                    "MESH_PULSE_ENABLE": "1",
                    "MESH_PULSE_OBSERVE_ONLY": "0",
                    "MESH_PULSE_DESCRIPTOR_ACTUAL_ENABLE": "1",
                    "MESH_PULSE_MFB_GATHER_PREBAND_ENABLE": "1",
                    "MESH_PULSE_MFB_GATHER_BARRIER_ENABLE": "1",
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            pulse = dict(rt.mesh_cfg.get("pulse", {}) or {})
            self.assertEqual(pulse.get("enable"), 1)
            self.assertEqual(pulse.get("descriptor_actual_enable"), 1)
            self.assertEqual(pulse.get("mfb_gather_preband_enable"), 1)
            self.assertEqual(pulse.get("mfb_gather_barrier_enable"), 1)

    def test_pulse_prebase_shared_lookup_env_is_exported_when_experimental_enable_is_on(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            run_dir = root / "run_prebase_lookup"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_GLOBAL_STEP_SYNC": "0",
                    "MESH_EXPERIMENTAL_ENABLE": "1",
                    "MESH_PULSE_ENABLE": "1",
                    "MESH_PULSE_PREBASE_SHARED_LOOKUP_ENABLE": "1",
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            pulse = dict(rt.mesh_cfg.get("pulse", {}) or {})
            self.assertEqual(pulse.get("enable"), 1)
            self.assertEqual(pulse.get("prebase_shared_lookup_enable"), 1)

    def test_pulse_rowdescriptor_ready_join_dedup_env_is_exported_when_experimental_enable_is_on(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            run_dir = root / "run_ready_join_dedup"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_GLOBAL_STEP_SYNC": "0",
                    "MESH_EXPERIMENTAL_ENABLE": "1",
                    "MESH_PULSE_ENABLE": "1",
                    "MESH_PULSE_DESCRIPTOR_ACTUAL_ENABLE": "1",
                    "MESH_PULSE_EXPERIMENTAL_ROWDESCRIPTOR_READY_JOIN_DEDUP_ENABLE": "1",
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            pulse = dict(rt.mesh_cfg.get("pulse", {}) or {})
            self.assertEqual(pulse.get("enable"), 1)
            self.assertEqual(pulse.get("descriptor_actual_enable"), 1)
            self.assertEqual(pulse.get("experimental_rowdescriptor_ready_join_dedup_enable"), 1)

    def test_pulse_osa_env_is_exported_when_experimental_enable_is_on(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            run_dir = root / "run_pulse_osa"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_GLOBAL_STEP_SYNC": "0",
                    "MESH_EXPERIMENTAL_ENABLE": "1",
                    "MESH_PULSE_ENABLE": "1",
                    "MESH_PULSE_OSA_ENABLE": "1",
                    "MESH_PULSE_OSA_SHARED_WEIGHT_OWNER_ENABLE": "1",
                    "MESH_PULSE_OSA_SHARED_WEIGHT_OWNER_ACTUAL_ENABLE": "1",
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            pulse = dict(rt.mesh_cfg.get("pulse", {}) or {})
            self.assertEqual(pulse.get("enable"), 1)
            self.assertEqual(pulse.get("osa_enable"), 1)
            self.assertEqual(pulse.get("osa_shared_weight_owner_enable"), 1)
            self.assertEqual(pulse.get("osa_shared_weight_owner_actual_enable"), 1)

    def test_pulse_osa_metadata_txn_env_is_exported_when_experimental_enable_is_on(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            run_dir = root / "run_pulse_osa_metadata_txn"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_GLOBAL_STEP_SYNC": "0",
                    "MESH_EXPERIMENTAL_ENABLE": "1",
                    "MESH_PULSE_ENABLE": "1",
                    "MESH_PULSE_OSA_ENABLE": "1",
                    "MESH_PULSE_OSA_METADATA_TXN_ENABLE": "1",
                    "MESH_PULSE_OSA_METADATA_READY_LEASE_ENABLE": "1",
                    "MESH_PULSE_OSA_METADATA_READY_LEASE_TTL": "64",
                    "MESH_PULSE_OSA_METADATA_OBJECT_MASK": "idx2,rowidx,preband,rowdescriptor",
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            pulse = dict(rt.mesh_cfg.get("pulse", {}) or {})
            self.assertEqual(pulse.get("enable"), 1)
            self.assertEqual(pulse.get("osa_enable"), 1)
            self.assertEqual(pulse.get("osa_metadata_txn_enable"), 1)
            self.assertEqual(pulse.get("osa_metadata_ready_lease_enable"), 1)
            self.assertEqual(pulse.get("osa_metadata_ready_lease_ttl"), 64)
            self.assertEqual(
                pulse.get("osa_metadata_object_mask"),
                "idx2,rowidx,preband,rowdescriptor",
            )

    def test_pulse_osa_metadata_txn_defaults_object_mask_to_rowdescriptor(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            run_dir = root / "run_pulse_osa_metadata_txn_default_mask"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_GLOBAL_STEP_SYNC": "0",
                    "MESH_EXPERIMENTAL_ENABLE": "1",
                    "MESH_PULSE_ENABLE": "1",
                    "MESH_PULSE_OSA_ENABLE": "1",
                    "MESH_PULSE_OSA_METADATA_TXN_ENABLE": "1",
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            pulse = dict(rt.mesh_cfg.get("pulse", {}) or {})
            self.assertEqual(pulse.get("osa_metadata_txn_enable"), 1)
            self.assertEqual(
                pulse.get("osa_metadata_object_mask"),
                "rowdescriptor",
            )

    def test_pulse_osa_env_exports_local_storage_enable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            (root / "sst_dram_si" / "local_run_config.json").write_text("{}", encoding="utf-8")
            run_dir = root / "run_pulse_osa_local_storage"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_GLOBAL_STEP_SYNC": "0",
                    "MESH_EXPERIMENTAL_ENABLE": "1",
                    "MESH_LOCAL_STORAGE_ENABLE": "1",
                    "MESH_SRAM_WEIGHT_IDX_ENABLE": "1",
                    "MESH_SRAM_WEIGHT_L0_ENABLE": "1",
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            self.assertEqual(rt.mesh_cfg.get("local_storage_enable"), 1)
            sram = dict(rt.mesh_cfg.get("sram", {}) or {})
            weight = dict(sram.get("weight", {}) or {})
            self.assertEqual(weight.get("idx_enable"), 1)
            self.assertEqual(weight.get("l0_enable"), 1)

    def test_spec_first_uses_pulse_spec_into_runtime_mesh_cfg(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            spec_file = self._write_spec_file(
                root,
                {
                    "schema_version": 3,
                    "model": "mesh",
                    "platform": {
                        "mesh_size": 4,
                        "stop": {"mode": "time", "simulation_time": "1us"},
                    },
                    "control": {"global_step_sync_enable": False},
                    "pulse": {
                        "enable": 1,
                        "observe_only": 0,
                        "ingress_enable": 1,
                        "agenda_observe_only": 1,
                        "osa_enable": 1,
                        "osa_shared_weight_owner_enable": 1,
                        "osa_shared_weight_owner_actual_enable": 1,
                        "osa_metadata_txn_enable": 1,
                        "osa_metadata_ready_lease_enable": 1,
                        "osa_metadata_ready_lease_ttl": 64,
                        "osa_metadata_object_mask": "rowidx,rowdescriptor",
                        "ingress_entries": 32,
                        "core_queue_entries": 16,
                        "descriptor_packet_min": 4,
                        "bypass_high_watermark_pct": 75,
                        "bypass_mode": "high_watermark",
                    },
                },
            )
            run_dir = root / "run_spec_pulse"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_SPEC_JSON": str(spec_file),
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            pulse = dict(rt.mesh_cfg.get("pulse", {}) or {})
            self.assertEqual(int(pulse.get("enable") or 0), 1)
            self.assertEqual(int(pulse.get("observe_only") or 0), 0)
            self.assertEqual(int(pulse.get("ingress_enable") or 0), 1)
            self.assertEqual(int(pulse.get("agenda_observe_only") or 0), 1)
            self.assertEqual(int(pulse.get("osa_enable") or 0), 1)
            self.assertEqual(int(pulse.get("osa_shared_weight_owner_enable") or 0), 1)
            self.assertEqual(int(pulse.get("osa_shared_weight_owner_actual_enable") or 0), 1)
            self.assertEqual(int(pulse.get("osa_metadata_txn_enable") or 0), 1)
            self.assertEqual(int(pulse.get("osa_metadata_ready_lease_enable") or 0), 1)
            self.assertEqual(int(pulse.get("osa_metadata_ready_lease_ttl") or 0), 64)
            self.assertEqual(str(pulse.get("osa_metadata_object_mask") or ""), "rowidx,rowdescriptor")
            self.assertEqual(int(pulse.get("ingress_entries") or 0), 32)
            self.assertEqual(int(pulse.get("core_queue_entries") or 0), 16)
            self.assertEqual(int(pulse.get("descriptor_packet_min") or 0), 4)
            self.assertEqual(int(pulse.get("bypass_high_watermark_pct") or 0), 75)
            self.assertEqual(str(pulse.get("bypass_mode") or ""), "high_watermark")

    def test_spec_first_mirrors_pe_component_runtime_knobs_into_mesh_cfg(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            spec_file = self._write_spec_file(
                root,
                {
                    "schema_version": 3,
                    "model": "mesh",
                    "platform": {"stop": {"mode": "step_limited", "max_steps": 1}},
                    "control": {"global_step_sync_enable": False},
                    "noc": {
                        "type": "multicast_mesh",
                        "params": {
                            "multicast_enable": True,
                            "multicast_block_w": 2,
                            "multicast_block_h": 2,
                            "multicast_ingress_policy": "top_left",
                            "multicast_inter_policy": "xy",
                            "multicast_intra_policy": "manhattan_x_first",
                        },
                    },
                    "components": {
                        "pe": {
                            "local_storage_enable": 1,
                            "pe_internal_cpe_enable": 1,
                            "pe_internal_pod_enable": 1,
                            "pe_internal_pod_count": 1,
                            "pe_internal_pod_metadata_enable": 1,
                            "pe_internal_pod_owner_enable": 1,
                            "pe_internal_pod_join_enable": 1,
                            "pe_internal_pod_ready_enable": 1,
                            "pe_internal_pod_owner_entries": 256,
                            "pe_internal_pod_join_entries": 256,
                            "pe_internal_pod_ready_entries": 256,
                        }
                    },
                },
            )
            run_dir = root / "run_spec_pe_runtime"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_SPEC_JSON": str(spec_file),
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            self.assertEqual(rt.mesh_cfg.get("noc_type"), "multicast_mesh")
            self.assertEqual(int(rt.mesh_cfg.get("multicast_enable") or 0), 1)
            self.assertEqual(int(rt.mesh_cfg.get("local_storage_enable") or 0), 1)
            self.assertEqual(int(rt.mesh_cfg.get("pe_internal_cpe_enable") or 0), 1)
            self.assertEqual(int(rt.mesh_cfg.get("pe_internal_pod_enable") or 0), 1)
            self.assertEqual(int(rt.mesh_cfg.get("pe_internal_pod_count") or 0), 1)
            self.assertEqual(int(rt.mesh_cfg.get("pe_internal_pod_metadata_enable") or 0), 1)
            self.assertEqual(int(rt.mesh_cfg.get("pe_internal_pod_owner_enable") or 0), 1)
            self.assertEqual(int(rt.mesh_cfg.get("pe_internal_pod_join_enable") or 0), 1)
            self.assertEqual(int(rt.mesh_cfg.get("pe_internal_pod_ready_enable") or 0), 1)
            self.assertEqual(int(rt.mesh_cfg.get("pe_internal_pod_owner_entries") or 0), 256)
            self.assertEqual(int(rt.mesh_cfg.get("pe_internal_pod_join_entries") or 0), 256)
            self.assertEqual(int(rt.mesh_cfg.get("pe_internal_pod_ready_entries") or 0), 256)

    def test_pe_internal_pod_env_is_exported_when_experimental_enable_is_on(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            (root / "sst_dram_si" / "local_run_config.json").write_text("{}", encoding="utf-8")
            run_dir = root / "run_pe_internal_pod"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_GLOBAL_STEP_SYNC": "0",
                    "MESH_EXPERIMENTAL_ENABLE": "1",
                    "MESH_LOCAL_STORAGE_ENABLE": "1",
                    "MESH_PE_INTERNAL_CPE_ENABLE": "1",
                    "MESH_PE_INTERNAL_POD_ENABLE": "1",
                    "MESH_PE_INTERNAL_POD_COUNT": "1",
                    "MESH_PE_INTERNAL_POD_METADATA_ENABLE": "1",
                    "MESH_PE_INTERNAL_POD_OWNER_ENABLE": "1",
                    "MESH_PE_INTERNAL_POD_JOIN_ENABLE": "1",
                    "MESH_PE_INTERNAL_POD_READY_ENABLE": "1",
                    "MESH_PE_INTERNAL_POD_OWNER_ENTRIES": "4096",
                    "MESH_PE_INTERNAL_POD_JOIN_ENTRIES": "4096",
                    "MESH_PE_INTERNAL_POD_READY_ENTRIES": "4096",
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            self.assertEqual(rt.mesh_cfg.get("local_storage_enable"), 1)
            self.assertEqual(rt.mesh_cfg.get("pe_internal_cpe_enable"), 1)
            self.assertEqual(rt.mesh_cfg.get("pe_internal_pod_enable"), 1)
            self.assertEqual(rt.mesh_cfg.get("pe_internal_pod_count"), 1)
            self.assertEqual(rt.mesh_cfg.get("pe_internal_pod_metadata_enable"), 1)
            self.assertEqual(rt.mesh_cfg.get("pe_internal_pod_owner_enable"), 1)
            self.assertEqual(rt.mesh_cfg.get("pe_internal_pod_join_enable"), 1)
            self.assertEqual(rt.mesh_cfg.get("pe_internal_pod_ready_enable"), 1)
            self.assertEqual(rt.mesh_cfg.get("pe_internal_pod_owner_entries"), 4096)
            self.assertEqual(rt.mesh_cfg.get("pe_internal_pod_join_entries"), 4096)
            self.assertEqual(rt.mesh_cfg.get("pe_internal_pod_ready_entries"), 4096)

    def test_idx2_ingress_prefetch_env_is_exported_when_experimental_enable_is_on(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            (root / "sst_dram_si" / "local_run_config.json").write_text("{}", encoding="utf-8")
            bcsr_dir = root / "sst_dram_si" / "weights" / "bcsr_global_16pe_fanout256_10k" / "pe00"
            bcsr_dir.mkdir(parents=True, exist_ok=True)
            (bcsr_dir / "core00.bcsr.bin.meta.json").write_text(
                json.dumps(
                    {
                        "file_size": 4096,
                        "cols": 4096,
                        "rows": 128,
                        "rowptr_offset": 0,
                        "colidx_offset": 512,
                        "blockdata_offset": 1024,
                        "blockids_offset": 1536,
                    }
                ),
                encoding="utf-8",
            )
            run_dir = root / "run_idx2_ingress_prefetch"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_GLOBAL_STEP_SYNC": "0",
                    "MESH_EXPERIMENTAL_ENABLE": "1",
                    "MESH_SYNAPSE_WEIGHT_MODE": "gcss_idx2_rowmphf",
                    "MESH_GCSS2_DIR": str(root / "sst_dram_si" / "weights" / "gcss2"),
                    "MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_ENABLE": "1",
                    "MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_BUDGET_PER_TICK": "7",
                    "MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_CACHE_ENTRIES": "1024",
                    "MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_MAX_INFLIGHT": "21",
                    "MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_GATHER_ONLY": "0",
                    "MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_CARRY_TO_APPLY_ENABLE": "1",
                    "MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_MAX_INFLIGHT": "5",
                    "MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_OUTSTANDING_RESERVE": "17",
                    "MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_FRONTIER_KEEP_PENDING": "9",
                    "MESH_EXPERIMENTAL_IDX2_INGRESS_TAIL_GUARD_ENABLE": "1",
                    "MESH_EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_ENABLE": "1",
                    "MESH_EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_MAX_PER_TICK": "19",
                    "MESH_EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_Q_DEPTH": "11",
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            self.assertEqual(rt.mesh_cfg.get("synapse_weight_mode"), "gcss_idx2_rowmphf")
            self.assertEqual(rt.mesh_cfg.get("gcss2_dir"), str(root / "sst_dram_si" / "weights" / "gcss2"))
            self.assertEqual(rt.mesh_cfg.get("experimental_idx2_ingress_prefetch_enable"), 1)
            self.assertEqual(rt.mesh_cfg.get("experimental_idx2_ingress_prefetch_budget_per_tick"), 7)
            self.assertEqual(rt.mesh_cfg.get("experimental_idx2_ingress_prefetch_cache_entries"), 1024)
            self.assertEqual(rt.mesh_cfg.get("experimental_idx2_ingress_prefetch_max_inflight"), 21)
            self.assertEqual(rt.mesh_cfg.get("experimental_idx2_ingress_prefetch_gather_only"), 0)
            self.assertEqual(rt.mesh_cfg.get("experimental_idx2_ingress_prefetch_carry_to_apply_enable"), 1)
            self.assertEqual(rt.mesh_cfg.get("experimental_idx2_ingress_prefetch_apply_max_inflight"), 5)
            self.assertEqual(rt.mesh_cfg.get("experimental_idx2_ingress_prefetch_apply_outstanding_reserve"), 17)
            self.assertEqual(rt.mesh_cfg.get("experimental_idx2_ingress_prefetch_apply_frontier_keep_pending"), 9)
            self.assertEqual(rt.mesh_cfg.get("experimental_idx2_ingress_tail_guard_enable"), 1)
            self.assertEqual(rt.mesh_cfg.get("experimental_idx2_ingress_budget_adapt_enable"), 1)
            self.assertEqual(rt.mesh_cfg.get("experimental_idx2_ingress_budget_adapt_max_per_tick"), 19)
            self.assertEqual(rt.mesh_cfg.get("experimental_idx2_ingress_budget_adapt_q_depth"), 11)

    def test_noc_rowidx_prefetch_env_is_exported_when_experimental_enable_is_on(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            (root / "sst_dram_si" / "local_run_config.json").write_text("{}", encoding="utf-8")
            run_dir = root / "run_noc_rowidx_prefetch"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_GLOBAL_STEP_SYNC": "0",
                    "MESH_EXPERIMENTAL_ENABLE": "1",
                    "MESH_SYNAPSE_WEIGHT_MODE": "bcsr_gas",
                    "MESH_EXPERIMENTAL_NOC_ROWIDX_PREFETCH_ENABLE": "1",
                    "MESH_EXPERIMENTAL_NOC_ROWIDX_PREFETCH_BUDGET_PER_TICK": "3",
                    "MESH_EXPERIMENTAL_NOC_ROWIDX_CACHE_ROWS": "96",
                    "MESH_EXPERIMENTAL_NOC_ROWIDX_PREFETCH_GATHER_ONLY": "0",
                    "MESH_EXPERIMENTAL_NOC_ROWIDX_PREFETCH_DETACHED_ENABLE": "1",
                    "MESH_EXPERIMENTAL_NOC_ROWIDX_HOT_TOUCH_MIN": "2",
                    "MESH_EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_ENABLE": "1",
                    "MESH_EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_MAX_PER_TICK": "13",
                    "MESH_EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_Q_DEPTH": "5",
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            self.assertEqual(rt.mesh_cfg.get("synapse_weight_mode"), "bcsr_gas")
            self.assertEqual(rt.mesh_cfg.get("experimental_noc_rowidx_prefetch_enable"), 1)
            self.assertEqual(rt.mesh_cfg.get("experimental_noc_rowidx_prefetch_budget_per_tick"), 3)
            self.assertEqual(rt.mesh_cfg.get("experimental_noc_rowidx_cache_rows"), 96)
            self.assertEqual(rt.mesh_cfg.get("experimental_noc_rowidx_prefetch_gather_only"), 0)
            self.assertEqual(rt.mesh_cfg.get("experimental_noc_rowidx_prefetch_detached_enable"), 1)
            self.assertEqual(rt.mesh_cfg.get("experimental_noc_rowidx_hot_touch_min"), 2)
            self.assertEqual(rt.mesh_cfg.get("experimental_noc_rowidx_budget_adapt_enable"), 1)
            self.assertEqual(rt.mesh_cfg.get("experimental_noc_rowidx_budget_adapt_max_per_tick"), 13)
            self.assertEqual(rt.mesh_cfg.get("experimental_noc_rowidx_budget_adapt_q_depth"), 5)

    def test_runtime_discovers_nonlegacy_bcsr_root_when_legacy_default_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            (root / "sst_dram_si" / "local_run_config.json").write_text("{}", encoding="utf-8")
            bcsr_pe_dir = root / "sst_dram_si" / "weights" / "alt_bcsr_dataset" / "pe00"
            bcsr_pe_dir.mkdir(parents=True, exist_ok=True)
            (bcsr_pe_dir / "core00.bcsr.bin").write_bytes(b"\x00" * 64)
            (bcsr_pe_dir / "core00.bcsr.bin.meta.json").write_text(
                json.dumps(
                    {
                        "file_size": 64,
                        "cols": 128,
                        "rows": 4,
                        "br": 1,
                        "bc": 4,
                        "idx_bytes": 2,
                        "val_bytes": 4,
                        "rowptr_offset": 0,
                        "colidx_offset": 16,
                        "blockdata_offset": 32,
                        "blockids_offset": 48,
                    }
                ),
                encoding="utf-8",
            )
            run_dir = root / "run_bcsr_discovery"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_GLOBAL_STEP_SYNC": "0",
                    "MESH_EXPERIMENTAL_ENABLE": "1",
                    "MESH_SYNAPSE_WEIGHT_MODE": "bcsr_gas",
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            self.assertEqual(rt.mesh_cfg.get("global_bcsr_available"), True)
            self.assertEqual(
                rt.mesh_cfg.get("global_bcsr_dir"),
                str(root / "sst_dram_si" / "weights" / "alt_bcsr_dataset"),
            )


if __name__ == "__main__":
    unittest.main()
