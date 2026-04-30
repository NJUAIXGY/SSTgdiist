#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class GenerateRiscvSnnFirmwareCLITest(unittest.TestCase):
    def test_lists_canonical_sample_programs_with_stable_semantics(self) -> None:
        script = Path(__file__).with_name("generate_riscv_snn_firmware.py")
        if not script.exists():
            self.fail(f"missing script: {script}")

        proc = subprocess.run(
            ["python3", str(script), "--list-programs", "--json"],
            text=True,
            capture_output=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

        payload = json.loads(proc.stdout)
        self.assertEqual(payload["canonical_sample_set"], ["external_p0", "external_dyn_desc"])
        samples = payload["samples"]

        self.assertEqual(samples["external_p0"]["descriptor_source"], "prebuilt_data_segment")
        self.assertEqual(samples["external_p0"]["completion_visibility"], "wfi_then_cmpq_ack")
        self.assertEqual(samples["external_p0"]["notes"], ["legacy_prebuilt_descriptor_sample"])

        self.assertEqual(samples["external_dyn_desc"]["descriptor_source"], "runtime_store_to_ring")
        self.assertEqual(samples["external_dyn_desc"]["completion_visibility"], "wfi_then_status_load_then_cmpq_ack")
        self.assertEqual(samples["external_dyn_desc"]["notes"], ["runtime_descriptor_construction_sample"])

        self.assertIn("external_dyn_desc_ref", samples)
        self.assertEqual(samples["external_dyn_desc_ref"]["descriptor_source"], "runtime_store_to_ring")
        self.assertEqual(
            samples["external_dyn_desc_ref"]["completion_visibility"],
            "cmpq_tail_then_payload_read_then_cmpq_ack",
        )
        self.assertEqual(
            samples["external_dyn_desc_ref"]["memory_image_shape"],
            "text_at_0x8000_rodata_at_0x9000",
        )

        self.assertIn("external_dyn_desc_fault_ref", samples)
        self.assertEqual(
            samples["external_dyn_desc_fault_ref"]["descriptor_source"],
            "runtime_store_to_ring",
        )
        self.assertEqual(
            samples["external_dyn_desc_fault_ref"]["completion_visibility"],
            "cmpq_tail_then_fault_payload_then_msnnfault_then_cmpq_ack",
        )
        self.assertIn(
            "accepted_fault_alignment_reference",
            samples["external_dyn_desc_fault_ref"]["notes"],
        )

        self.assertIn("external_dyn_desc_bad_policy_ref", samples)
        self.assertEqual(
            samples["external_dyn_desc_bad_policy_ref"]["descriptor_source"],
            "runtime_store_to_ring",
        )
        self.assertEqual(
            samples["external_dyn_desc_bad_policy_ref"]["completion_visibility"],
            "cmpq_tail_then_bad_policy_payload_then_msnnstep_and_msnnfault_then_cmpq_ack",
        )
        self.assertIn(
            "bad_policy_before_progress_reference",
            samples["external_dyn_desc_bad_policy_ref"]["notes"],
        )

        self.assertIn("external_dyn_desc_fault_rearm_ref", samples)
        self.assertEqual(
            samples["external_dyn_desc_fault_rearm_ref"]["descriptor_source"],
            "runtime_store_to_ring",
        )
        self.assertEqual(
            samples["external_dyn_desc_fault_rearm_ref"]["completion_visibility"],
            "fault1_visible_then_msnnfault_clear_then_fault2_visible_then_cmpq_ack",
        )
        self.assertIn(
            "msnnfault_clear_then_refault",
            samples["external_dyn_desc_fault_rearm_ref"]["notes"],
        )

        self.assertIn("external_dyn_desc_fault_overwrite_chain_ref", samples)
        self.assertEqual(
            samples["external_dyn_desc_fault_overwrite_chain_ref"]["descriptor_source"],
            "runtime_store_to_ring",
        )
        self.assertEqual(
            samples["external_dyn_desc_fault_overwrite_chain_ref"]["completion_visibility"],
            "fault1_visible_then_msnnfault_clear_then_fault2_visible_then_msnnfault_clear_then_fault3_visible_then_cmpq_ack",
        )
        self.assertIn(
            "msnnfault_clear_twice_then_refault",
            samples["external_dyn_desc_fault_overwrite_chain_ref"]["notes"],
        )

        self.assertIn("stat_snapshot_bad_selector_ref", samples)
        self.assertEqual(
            samples["stat_snapshot_bad_selector_ref"]["descriptor_source"],
            "runtime_store_to_ring",
        )
        self.assertEqual(
            samples["stat_snapshot_bad_selector_ref"]["completion_visibility"],
            "cmpq_tail_then_fault_status_then_msnnfault_then_cmpq_ack",
        )
        self.assertEqual(
            samples["stat_snapshot_bad_selector_ref"]["memory_image_shape"],
            "text_at_0x8000_rodata_at_0x9000",
        )
        self.assertIn(
            "selector_invalid_fault",
            samples["stat_snapshot_bad_selector_ref"]["notes"],
        )
        self.assertIn(
            "expects_visible_fault_snapshot_for_bad_selector",
            samples["stat_snapshot_bad_selector_ref"]["notes"],
        )

    def _run_generate_and_validate(self, program: str) -> None:
        script = Path(__file__).with_name("generate_riscv_snn_firmware.py")
        if not script.exists():
            self.fail(f"missing script: {script}")

        spec_cli = Path(__file__).with_name("mesh_spec_cli.py")
        self.assertTrue(spec_cli.exists(), msg=f"missing spec cli: {spec_cli}")

        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            elf_path = out_dir / f"{program}.elf"
            spec_path = out_dir / f"{program}.json"

            proc = subprocess.run(
                [
                    "python3",
                    str(script),
                    "--program",
                    program,
                    "--elf",
                    str(elf_path),
                    "--spec",
                    str(spec_path),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertTrue(elf_path.exists(), msg=proc.stdout + proc.stderr)
            self.assertTrue(spec_path.exists(), msg=proc.stdout + proc.stderr)

            with elf_path.open("rb") as f:
                self.assertEqual(f.read(4), b"\x7fELF")

            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            self.assertEqual(spec.get("schema_version"), 3)
            self.assertEqual(spec.get("workload", {}).get("impl"), "riscv_snn")
            self.assertEqual(
                spec.get("workload", {}).get("params", {}).get("firmware_elf"),
                str(elf_path),
            )

            validate = subprocess.run(
                ["python3", str(spec_cli), "validate", str(spec_path)],
                text=True,
                capture_output=True,
                cwd=str(Path(__file__).resolve().parents[1]),
            )
            self.assertEqual(validate.returncode, 0, msg=validate.stdout + validate.stderr)
            self.assertIn("OK", validate.stdout)

    def test_generates_external_dyn_desc_elf_and_spec(self) -> None:
        self._run_generate_and_validate("external_dyn_desc")

    def test_generates_external_p0_elf_and_spec(self) -> None:
        self._run_generate_and_validate("external_p0")

    def test_generates_external_dyn_desc_ref_elf_and_spec(self) -> None:
        self._run_generate_and_validate("external_dyn_desc_ref")

    def test_generates_external_dyn_desc_fault_ref_elf_and_spec(self) -> None:
        self._run_generate_and_validate("external_dyn_desc_fault_ref")

    def test_generates_external_dyn_desc_bad_policy_ref_elf_and_spec(self) -> None:
        self._run_generate_and_validate("external_dyn_desc_bad_policy_ref")

    def test_generates_external_dyn_desc_fault_rearm_ref_elf_and_spec(self) -> None:
        self._run_generate_and_validate("external_dyn_desc_fault_rearm_ref")

    def test_generates_external_dyn_desc_fault_overwrite_chain_ref_elf_and_spec(self) -> None:
        self._run_generate_and_validate("external_dyn_desc_fault_overwrite_chain_ref")

    def test_generates_stat_snapshot_bad_selector_ref_elf_and_spec(self) -> None:
        self._run_generate_and_validate("stat_snapshot_bad_selector_ref")


if __name__ == "__main__":
    unittest.main()
