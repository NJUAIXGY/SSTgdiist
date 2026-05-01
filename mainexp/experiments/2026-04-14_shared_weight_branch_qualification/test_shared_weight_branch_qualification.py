import json
import subprocess
import unittest
from pathlib import Path


EXPERIMENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = EXPERIMENT_DIR.parents[2]
RUN_CASE = EXPERIMENT_DIR / "run_case.sh"
CASES_JSON = EXPERIMENT_DIR / "cases.json"
EXPECTED_IDS = [
    "shared_weight_owner_off",
    "shared_weight_owner_req_on",
    "shared_weight_actual_owner_on",
]
EXPECTED_OWNER_BRANCH = {
    "shared_weight_owner_off": (0, 0),
    "shared_weight_owner_req_on": (1, 0),
    "shared_weight_actual_owner_on": (1, 1),
}


class SharedWeightBranchQualificationTest(unittest.TestCase):
    def _load_cases(self) -> dict:
        return json.loads(CASES_JSON.read_text(encoding="utf-8"))

    def _load_spec(self, spec_name: str) -> dict:
        return json.loads((EXPERIMENT_DIR / spec_name).read_text(encoding="utf-8"))

    def test_cases_json_references_existing_specs_and_latest_run_dirs(self) -> None:
        cases_doc = self._load_cases()
        cases = list(cases_doc.get("cases") or [])

        self.assertEqual(cases_doc.get("baseline_case"), "shared_weight_owner_off")
        self.assertEqual([case.get("id") for case in cases], EXPECTED_IDS)

        for case in cases:
            case_id = str(case["id"])
            spec_path = EXPERIMENT_DIR / str(case["spec"])
            run_dir = Path(str(case["run_dir"]))
            self.assertTrue(spec_path.exists(), msg=f"missing spec for {case_id}: {spec_path}")
            self.assertEqual(
                run_dir,
                EXPERIMENT_DIR / "runs" / case_id / "latest",
            )

    def test_specs_encode_expected_shared_weight_owner_branch_states(self) -> None:
        cases = list(self._load_cases().get("cases") or [])

        for case in cases:
            case_id = str(case["id"])
            spec = self._load_spec(str(case["spec"]))
            platform = dict(spec.get("platform") or {})
            pulse = dict(spec.get("pulse") or {})
            noc = dict(spec.get("noc") or {})
            noc_params = dict(noc.get("params") or {})
            pe_components = dict((spec.get("components") or {}).get("pe") or {})
            sram = dict(spec.get("sram") or {})
            sram_weight = dict(sram.get("weight") or {})
            gas = dict(spec.get("gas") or {})
            owner_enable, actual_enable = EXPECTED_OWNER_BRANCH[case_id]

            self.assertEqual(spec.get("schema_version"), 3)
            self.assertEqual(spec.get("synapse_weight_mode"), "gcss_valueonly_dstcore_vlf_premphf_plp")
            self.assertEqual(
                spec.get("gcssplp_dir"),
                "/home/xgy/remote/sst_dram_si/weights/gcss_valueonly_dstcore_vlf_premphf_plp_fanout256_10k_v7_lpblp_j8",
            )
            self.assertEqual(int(platform.get("mesh_size") or 0), 4)
            self.assertEqual(int(platform.get("node_limit") or 0), 16)
            self.assertNotIn("noc_type", spec)
            self.assertNotIn("noc_multicast", spec)
            self.assertNotIn("local_storage_enable", spec)
            self.assertEqual(str(noc.get("type") or ""), "multicast_mesh")
            self.assertEqual(int(noc_params.get("multicast_enable") or 0), 1)
            self.assertEqual(int(noc_params.get("multicast_block_w") or 0), 2)
            self.assertEqual(int(noc_params.get("multicast_block_h") or 0), 2)
            self.assertEqual(str(noc_params.get("multicast_ingress_policy") or ""), "top_left")
            self.assertEqual(str(noc_params.get("multicast_inter_policy") or ""), "xy")
            self.assertEqual(str(noc_params.get("multicast_intra_policy") or ""), "manhattan_x_first")
            self.assertEqual(int(pulse.get("enable") or 0), 0)
            self.assertEqual(int(pulse.get("osa_enable") or 0), 1)
            self.assertEqual(int(pulse.get("osa_shared_weight_owner_enable") or 0), owner_enable)
            self.assertEqual(
                int(pulse.get("osa_shared_weight_owner_actual_enable") or 0),
                actual_enable,
            )
            self.assertEqual(int(gas.get("gap_k_bytes") or 0), 2048)
            self.assertEqual(int(gas.get("row_window_bytes") or 0), 16384)
            self.assertEqual(int(gas.get("vlf_enable") or 0), 1)
            self.assertEqual(int(gas.get("vlf_run_enable") or 0), 0)
            self.assertEqual(int(pe_components.get("local_storage_enable") or 0), 1)
            self.assertEqual(int(pe_components.get("pe_internal_pod_enable") or 0), 1)
            self.assertEqual(int(sram.get("model_enable") or 0), 1)
            self.assertEqual(int(sram_weight.get("idx_enable") or 0), 1)
            self.assertEqual(int(sram_weight.get("l0_enable") or 0), 1)

    def test_run_case_dry_run_uses_repo_runner_and_case_spec(self) -> None:
        cases = list(self._load_cases().get("cases") or [])
        expected_runner = PROJECT_ROOT / "sst_dram_si" / "tools" / "run_mesh_with_time.sh"

        for case in cases:
            case_id = str(case["id"])
            expected_spec = EXPERIMENT_DIR / str(case["spec"])
            proc = subprocess.run(
                ["bash", str(RUN_CASE), "--dry-run", case_id],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertIn(str(expected_runner), proc.stdout)
            self.assertIn("--spec", proc.stdout)
            self.assertIn(str(expected_spec), proc.stdout)
            self.assertNotIn("run_snapshot.sh", proc.stdout)
            self.assertIn("MESH_MAX_STEPS=1", proc.stdout)
            self.assertIn("MESH_STEP_SEED_ONLY_MODE=1", proc.stdout)
            self.assertIn("MESH_STEP_ACTIVATION_FRACTION=0.03", proc.stdout)
            self.assertIn("MESH_MEM_BACKEND=ramulator2", proc.stdout)
            self.assertIn(
                "MESH_RAMULATOR2_CONFIG_FILE=/home/xgy/remote/sst_dram_si/configs/ramulator2_ddr5.cfg",
                proc.stdout,
            )
            self.assertIn("MESH_SYNAPSE_WEIGHT_MODE=gcss_valueonly_dstcore_vlf_premphf_plp", proc.stdout)
            self.assertIn(
                "MESH_GCSSPLP_DIR=/home/xgy/remote/sst_dram_si/weights/gcss_valueonly_dstcore_vlf_premphf_plp_fanout256_10k_v7_lpblp_j8",
                proc.stdout,
            )
            self.assertIn("MESH_GAS_VLF_ENABLE=1", proc.stdout)
            self.assertIn("MESH_GAS_VLF_RUN_ENABLE=0", proc.stdout)
            self.assertIn("MESH_NOC_TYPE=multicast_mesh", proc.stdout)
            self.assertIn("MESH_MULTICAST_ENABLE=1", proc.stdout)
            self.assertIn("MESH_MULTICAST_BLOCK_W=2", proc.stdout)
            self.assertIn("MESH_MULTICAST_BLOCK_H=2", proc.stdout)
            self.assertIn("MESH_MULTICAST_INGRESS_POLICY=top_left", proc.stdout)
            self.assertIn("MESH_MULTICAST_INTER_POLICY=xy", proc.stdout)
            self.assertIn("MESH_MULTICAST_INTRA_POLICY=manhattan_x_first", proc.stdout)
            self.assertIn("MESH_LOCAL_STORAGE_ENABLE=1", proc.stdout)
            self.assertIn("MESH_SRAM_MODEL_ENABLE=1", proc.stdout)
            self.assertIn("MESH_SRAM_WEIGHT_IDX_ENABLE=1", proc.stdout)
            self.assertIn("MESH_SRAM_WEIGHT_L0_ENABLE=1", proc.stdout)
            self.assertIn("MESH_SRAM_WEIGHT_IDX_CAPACITY_BYTES=1048576", proc.stdout)
            self.assertIn("MESH_SRAM_WEIGHT_L0_CAPACITY_BYTES=4194304", proc.stdout)
            self.assertIn("MESH_SRAM_WEIGHT_IDX_BANKS=8", proc.stdout)
            self.assertIn("MESH_SRAM_WEIGHT_L0_BANKS=8", proc.stdout)
            self.assertIn("MESH_SRAM_WEIGHT_PORTS_PER_BANK=1", proc.stdout)
            self.assertIn("MESH_PULSE_OSA_ENABLE=1", proc.stdout)

            owner_enable, actual_enable = EXPECTED_OWNER_BRANCH[case_id]
            self.assertIn(f"MESH_PULSE_OSA_SHARED_WEIGHT_OWNER_ENABLE={owner_enable}", proc.stdout)
            self.assertIn(
                f"MESH_PULSE_OSA_SHARED_WEIGHT_OWNER_ACTUAL_ENABLE={actual_enable}",
                proc.stdout,
            )


if __name__ == "__main__":
    unittest.main()
