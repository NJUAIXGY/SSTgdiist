import json
import unittest
from pathlib import Path


class SramPhase1SpecModeContractTests(unittest.TestCase):
    def test_spec_first_cases_do_not_rely_on_sealed_weight_env(self):
        repo_root = Path(__file__).resolve().parents[2]
        exp_root = repo_root / "snndl-thing-exp"
        sealed_env_keys = {"MESH_SYNAPSE_WEIGHT_MODE", "MESH_GCSS2_DIR"}
        for case_id in ("state_sram_debug", "weight_idx_sram_debug", "weight_l0_fill_smoke", "sram_mixed_smoke"):
            case_dir = exp_root / "cases" / case_id
            case_obj = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
            spec_obj = json.loads((case_dir / "spec.json").read_text(encoding="utf-8"))
            raw_env = dict(case_obj.get("env") or {})
            self.assertFalse(
                sealed_env_keys & set(raw_env),
                msg=f"{case_id} still relies on sealed spec-first env keys: {sealed_env_keys & set(raw_env)}",
            )
            self.assertEqual(raw_env.get("MESH_EXPERIMENTAL_ENABLE"), "1")
            self.assertEqual(spec_obj.get("synapse_weight_mode"), "gcss_valueonly_dstcore_idx2")
            self.assertTrue(spec_obj.get("gcss2_dir"), msg=f"{case_id} missing gcss2_dir in spec")


if __name__ == "__main__":
    unittest.main()
