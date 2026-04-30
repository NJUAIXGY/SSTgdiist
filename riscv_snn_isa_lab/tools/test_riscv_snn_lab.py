#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import importlib
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sst_dram_si.tools import generate_riscv_snn_firmware
from riscv_snn_isa_lab.ci import nightly_sidecar
from riscv_snn_isa_lab.architecture_model.reference_machine import ReferenceMachine
from riscv_snn_isa_lab.architecture_model import model_types, runtime_compare
from riscv_snn_isa_lab.tools import export_riscv_snn_research_report
from riscv_snn_isa_lab.tools import riscv_hart_ref
from riscv_snn_isa_lab.tools import riscv_snn_lab
from riscv_snn_isa_lab.tools import supplementary_surface_contract


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str | None]] = []

    def __call__(self, cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
        self.calls.append((cmd, cwd))
        if "--list-programs" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"samples": {}}), stderr="")
        if any(str(part).endswith("run_mesh_with_time.sh") for part in cmd):
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout="[mesh] run complete: /tmp/fake-run\n",
                stderr="",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")


class RiscvSnnLabTest(unittest.TestCase):
    def _write_runtime_bridge_spec(self, lab_root: Path, name: str = "external_dyn_desc_ref_runtime_bridge.json") -> Path:
        specs_dir = lab_root / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)
        spec_path = specs_dir / name
        spec_path.write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "platform": {
                        "mesh_size": 4,
                        "exec_mode": "gas",
                        "stop": {"mode": "time", "simulation_time": "1us"},
                    },
                    "workload": {"impl": "riscv_snn", "params": {"backend_name": "runtime_bridge"}},
                    "control": {"global_step_sync_enable": False},
                }
            ),
            encoding="utf-8",
        )
        return spec_path

    def _write_baseline_snn_spec(self, lab_root: Path, name: str = "external_dyn_desc_ref_snn_baseline.json") -> Path:
        specs_dir = lab_root / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)
        spec_path = specs_dir / name
        spec_path.write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "platform": {
                        "mesh_size": 4,
                        "exec_mode": "gas",
                        "stop": {"mode": "time", "simulation_time": "1us"},
                    },
                    "workload": {"impl": "snn", "params": {}},
                    "control": {"global_step_sync_enable": False},
                }
            ),
            encoding="utf-8",
        )
        return spec_path

    def test_write_json_replaces_file_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "references" / "stable.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("", encoding="utf-8")

            written = riscv_snn_lab._write_json(target, {"ok": True, "value": 3})

            self.assertEqual(written, target)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"ok": True, "value": 3})
            self.assertEqual(list(target.parent.glob("stable.json.tmp*")), [])

    def test_smoke_failure_reason_ids_classify_environment_failures(self) -> None:
        message = "\n".join(
            [
                "smoke failed before producing a run directory",
                "[mesh] error: parallel SST exists but is not runnable in the current environment; refusing to fall back to serial",
                "mkdir: 无法创建目录 \"/tmp/run\": 设备上没有空间",
            ]
        )
        self.assertEqual(
            riscv_snn_lab._smoke_failure_reason_ids(message),
            [
                "smoke_env_parallel_sst_unavailable",
                "smoke_env_run_dir_missing",
                "smoke_env_run_root_no_space",
            ],
        )

    def test_parallel_sst_preflight_reports_unrunnable_parallel_binary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lab_root = Path(td) / "riscv_snn_isa_lab"
            parallel_bin = lab_root.parent / "sst_install" / "bin" / "sst"
            parallel_bin.parent.mkdir(parents=True, exist_ok=True)
            parallel_bin.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            os.chmod(parallel_bin, 0o755)

            class PreflightRunner(FakeRunner):
                def __call__(self, cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
                    self.calls.append((cmd, cwd))
                    if cmd == [str(parallel_bin), "--version"]:
                        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="broken\n")
                    return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")

            runner = PreflightRunner()
            summary = riscv_snn_lab.parallel_sst_preflight(
                lab_root=lab_root,
                runner=runner,
            )

        self.assertEqual(summary["status"], "parallel_unavailable")
        self.assertEqual(summary["selected_bin"], None)
        self.assertEqual(summary["reason_ids"], ["preflight_env_parallel_sst_unavailable"])
        self.assertEqual(summary["parallel_candidates_checked"], [str(parallel_bin)])
        self.assertEqual(runner.calls, [([str(parallel_bin), "--version"], None)])

    def test_parse_run_dir_accepts_validation_summary_path(self) -> None:
        run_dir = Path("/tmp/riscv-smoke/20260403-112843")
        output = "\n".join(
            [
                "[mesh] spec-first enabled: MESH_SPEC_JSON=/tmp/spec.json",
                f"[val] SUMMARY run_dir={run_dir} fail=3 warn=0 strict=0",
            ]
        )
        self.assertEqual(riscv_snn_lab._parse_run_dir(output), run_dir)

    def test_parse_run_dir_accepts_validation_summary_run_dir(self) -> None:
        run_dir = Path("/tmp/fake-run-from-validation")
        output = "\n".join(
            [
                "[mesh] spec-first enabled: MESH_SPEC_JSON=/tmp/spec.json",
                f"[val] SUMMARY run_dir={run_dir} fail=3 warn=0 strict=0",
            ]
        )

        parsed = riscv_snn_lab._parse_run_dir(output)

        self.assertEqual(parsed, run_dir)

    def _seed_runtime_bridge_build_tree(self, lab_root: Path, *, stale: bool) -> Path:
        snndl_root = (
            lab_root.parent
            / "sst_workspace"
            / "sst-elements"
            / "src"
            / "sst"
            / "elements"
            / "SnnDL"
        )
        headers = [
            snndl_root / "services" / "synapse" / "weights" / "WeightMemorySubsystem.h",
            snndl_root / "services" / "memory" / "sram_sim" / "model" / "BankedSramModel.h",
        ]
        consumers = [
            snndl_root / "services" / "workload" / "snn" / ".libs" / "SnnWorkload.o",
            snndl_root / "control" / ".libs" / "SnnPESubComponent.o",
            snndl_root / "control" / ".libs" / "SnnPEOrchestrators.o",
            snndl_root / "control" / ".libs" / "SnnPESubComponent_spike.o",
            snndl_root / "control" / ".libs" / "SnnPESubComponent_bcsr.o",
            snndl_root / "services" / "synapse" / "stdmem" / ".libs" / "SnnPESubComponent_mem.o",
            snndl_root / "services" / "synapse" / "weights" / ".libs" / "WeightMemorySubsystem.o",
            snndl_root / "services" / "memory" / "sram_sim" / "model" / ".libs" / "BankedSramModel.o",
            snndl_root / ".libs" / "libSnnDL.so",
        ]

        for path in headers + consumers:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(path.name, encoding="utf-8")

        older_mtime = 100
        newer_mtime = 200
        for path in consumers:
            os.utime(path, (older_mtime, older_mtime))
        header_mtime = newer_mtime if stale else older_mtime
        for path in headers:
            os.utime(path, (header_mtime, header_mtime))
        return snndl_root

    def _runtime_bridge_build_guard_ok_summary(self) -> dict[str, object]:
        return {
            "enabled": True,
            "status": "ok",
            "required_action": "none",
            "lineage_status": "ok",
            "contract_key": "riscv_snn.runtime_bridge.runtime_consumers",
            "contract_version": 1,
            "dependency_paths": [],
            "required_target_paths": [],
            "stale_targets": [],
            "missing_targets": [],
            "workspace_lib_path": "/tmp/workspace-libSnnDL.so",
            "installed_lib_path": "/tmp/installed-libSnnDL.so",
            "workspace_build_fingerprint": "workspace-fp",
            "installed_build_fingerprint": "installed-fp",
            "fingerprint_match": True,
            "layout_sensitive_relpaths": [],
            "full_rebuild_reason_ids": [],
            "full_rebuild_required": False,
            "rebuild_command": "",
        }

    def _seed_runtime_bridge_installed_lib(self,
                                           lab_root: Path,
                                           *,
                                           content: str = "installed-lib") -> Path:
        installed_lib = (
            lab_root.parent
            / "sst_install"
            / "lib"
            / "sst-elements-library"
            / "libSnnDL.so"
        )
        installed_lib.parent.mkdir(parents=True, exist_ok=True)
        installed_lib.write_text(content, encoding="utf-8")
        return installed_lib

    def _write_optional_group_review(self,
                                     lab_root: Path,
                                     *,
                                     group: str = "queue_optional",
                                     reviewer: str = "lab-owner",
                                     decision: str = "retain_nonblocking_until_formal_promotion",
                                     date_str: str = "2026-03-30") -> Path:
        refs_dir = lab_root / "references"
        refs_dir.mkdir(parents=True, exist_ok=True)
        review_path = refs_dir / f"{date_str}-{group.replace('_', '-')}-review.json"
        authority = riscv_snn_lab.load_mainline_gate_authority()
        review_path.write_text(
            json.dumps(
                {
                    "artifact_role": "dated_optional_group_review",
                    "authority_scope": "research_only_nonblocking",
                    "group": group,
                    "families": authority["optional_groups"][group]["families"],
                    "review_date": date_str,
                    "reviewer": reviewer,
                    "decision": decision,
                }
            ),
            encoding="utf-8",
        )
        return review_path

    def _seed_program_evidence_authorities(self, lab_root: Path) -> Path:
        spec_dir = lab_root / "spec_authority"
        spec_dir.mkdir(parents=True, exist_ok=True)
        authority_loaders = {
            "riscv_snn_architecture_model_v1.json": riscv_snn_lab.load_architecture_model_authority(),
            "riscv_snn_runtime_gate_v1.json": riscv_snn_lab.load_runtime_gate_authority(),
            "riscv_snn_supplementary_surface_v1.json": riscv_snn_lab.load_supplementary_surface_authority(),
        }
        for name, payload in authority_loaders.items():
            (spec_dir / name).write_text(json.dumps(payload), encoding="utf-8")
        return spec_dir

    def _seed_program_evidence_run_dir(
        self,
        root: Path,
        *,
        completion_visible_count: int = 64,
        completion_consumed_count: int = 64,
        fused_step_completion_count: int = 64,
        fault_count: int = 0,
        last_completion_status: int = 0,
        last_fault_csr: int = 0,
        submitted_commands: int = 64,
        accepted_commands: int = 64,
        provider_bound: int = 64,
        validation_fail_count: int = 0,
        validation_warn_count: int = 1,
    ) -> Path:
        run_dir = root / "run"
        inputs_dir = run_dir / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "essential_summary_mesh.json").write_text(
            json.dumps(
                {
                    "model": {"workload_impl": "riscv_snn", "mesh_size": 4, "num_pes": 16},
                    "step": {"global_steps_done": 4.0, "per_step": [{"seq": 1}]},
                    "contracts": {"gas_semantic_ready_before_commit": True},
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "meta.json").write_text(
            json.dumps({"run_id": "20260416-000000", "suite": "runtime_bridge"}),
            encoding="utf-8",
        )
        (inputs_dir / "spec.json").write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "platform": {"mesh_size": 4},
                    "workload": {"impl": "riscv_snn", "params": {"backend_name": "runtime_bridge"}},
                    "control": {"global_step_sync_enable": False},
                }
            ),
            encoding="utf-8",
        )
        mesh_stats_lines = [
            "ComponentName,StatisticName,StatisticSubId,StatisticType,SimTime,Rank,Sum.u64,SumSQ.u64,Count.u64,Min.u64,Max.u64,Sum.f64,SumSQ.f64,Min.f64,Max.f64",
            f"multicore_pe_0,riscv_snn_submitted_commands,,Accumulator,1000000,0,{submitted_commands},{submitted_commands},1,{submitted_commands},{submitted_commands},0,0,0,0",
            f"multicore_pe_0,riscv_snn_accepted_commands,,Accumulator,1000000,0,{accepted_commands},{accepted_commands},1,{accepted_commands},{accepted_commands},0,0,0,0",
            f"multicore_pe_0,riscv_snn_completion_visible_count,,Accumulator,1000000,0,{completion_visible_count},{completion_visible_count},1,{completion_visible_count},{completion_visible_count},0,0,0,0",
            f"multicore_pe_0,riscv_snn_completion_consumed_count,,Accumulator,1000000,0,{completion_consumed_count},{completion_consumed_count},1,{completion_consumed_count},{completion_consumed_count},0,0,0,0",
            f"multicore_pe_0,riscv_snn_fused_step_completion_count,,Accumulator,1000000,0,{fused_step_completion_count},{fused_step_completion_count},1,{fused_step_completion_count},{fused_step_completion_count},0,0,0,0",
            f"multicore_pe_0,riscv_snn_fault_count,,Accumulator,1000000,0,{fault_count},{fault_count},1,{fault_count},{fault_count},0,0,0,0",
            f"multicore_pe_0,riscv_snn_last_completion_status,,Accumulator,1000000,0,{last_completion_status},{last_completion_status},1,{last_completion_status},{last_completion_status},0,0,0,0",
            f"multicore_pe_0,riscv_snn_last_fault_csr,,Accumulator,1000000,0,{last_fault_csr},{last_fault_csr},1,{last_fault_csr},{last_fault_csr},0,0,0,0",
            f"multicore_pe_0,riscv_snn_backend_runtime_bridge_provider_bound,,Accumulator,1000000,0,{provider_bound},{provider_bound},1,{provider_bound},{provider_bound},0,0,0,0",
        ]
        (run_dir / "mesh_stats.csv").write_text("\n".join(mesh_stats_lines) + "\n", encoding="utf-8")
        (run_dir / "validation.log").write_text(
            "\n".join(
                [
                    "[val] PASS contracts.present: contracts exported",
                    "[val] PASS snn_tx.nonzero: tx_packets=64 tx_spike=64 tx_spikekey=0 tx_spiketilekey=0",
                    (
                        f"[val] SUMMARY run_dir={run_dir} fail={validation_fail_count} "
                        f"warn={validation_warn_count} strict=0"
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return run_dir

    def test_matrix_programs_freeze_builder_and_toolchain_surface(self) -> None:
        self.assertEqual(
            riscv_snn_lab.matrix_programs("builder"),
            [
                "external_dyn_desc_ref",
                "external_dyn_desc_fault_ref",
                "external_dyn_desc_bad_policy_ref",
                "external_dyn_desc_fault_rearm_ref",
                "external_dyn_desc_fault_overwrite_chain_ref",
                "barrier_wfi_order_ref",
            ],
        )
        self.assertEqual(
            riscv_snn_lab.matrix_programs("toolchain"),
            [
                "external_dyn_desc_ref_toolchain",
                "external_dyn_desc_fault_ref_toolchain",
                "external_dyn_desc_bad_policy_ref_toolchain",
                "external_dyn_desc_fault_rearm_ref_toolchain",
                "external_dyn_desc_fault_overwrite_chain_ref_toolchain",
                "barrier_wfi_order_ref_toolchain",
            ],
        )

    def test_authority_required_families_default_surface_includes_barrier_reference(self) -> None:
        self.assertEqual(
            riscv_snn_lab.authority_required_families(),
            [
                "barrier_wfi_order_ref",
                "external_dyn_desc_bad_policy_ref",
                "external_dyn_desc_fault_overwrite_chain_ref",
                "external_dyn_desc_fault_rearm_ref",
                "external_dyn_desc_fault_ref",
                "external_dyn_desc_ref",
            ],
        )
        self.assertNotIn("queue_backpressure_ref", riscv_snn_lab.authority_required_families())

    def test_mainline_gate_authority_file_exists_and_declares_required_families(self) -> None:
        authority = riscv_snn_lab.load_mainline_gate_authority()
        self.assertEqual(
            authority["required_families"],
            [
                "barrier_wfi_order_ref",
                "external_dyn_desc_bad_policy_ref",
                "external_dyn_desc_fault_overwrite_chain_ref",
                "external_dyn_desc_fault_rearm_ref",
                "external_dyn_desc_fault_ref",
                "external_dyn_desc_ref",
            ],
        )
        self.assertEqual(authority["optional_groups"]["queue_optional"]["blocking"], False)
        self.assertEqual(
            authority["optional_groups"]["queue_optional"]["families"],
            [
                "queue_backpressure_ref",
                "completion_queue_overflow_ref",
            ],
        )
        self.assertEqual(
            authority["mainline_defaults"]["primary_optional_group"],
            "completion_overflow_optional",
        )
        self.assertEqual(
            authority["mainline_defaults"]["mainline_refresh_default_group"],
            "completion_overflow_optional",
        )

    def test_authority_required_families_reads_machine_readable_gate_authority(self) -> None:
        authority = riscv_snn_lab.load_mainline_gate_authority()
        self.assertEqual(
            riscv_snn_lab.authority_required_families(),
            authority["required_families"],
        )

    def test_runtime_gate_authority_declares_fault_and_progress_modes(self) -> None:
        authority = riscv_snn_lab.load_runtime_gate_authority()
        self.assertEqual(authority["families"]["external_dyn_desc_ref"]["fault_mode"], "quiescent")
        self.assertEqual(
            authority["families"]["external_dyn_desc_fault_ref"]["fault_mode"],
            "accepted_fault_required",
        )
        self.assertEqual(
            authority["families"]["barrier_wfi_order_ref"]["timing_mode"],
            "wfi_barrier_completion_visibility",
        )

    def test_runtime_gate_reason_ids_are_declared_in_authority(self) -> None:
        authority = riscv_snn_lab.load_runtime_gate_authority()
        self.assertIn("runtime_bridge_expected_fault_missing", authority["reason_ids"])
        self.assertIn("runtime_bridge_completion_visibility_missing", authority["reason_ids"])
        self.assertIn("provider_bound_visible", authority["check_ids"])
        self.assertIn("completion_visible", authority["check_ids"])

    def test_runtime_gate_authority_declares_reference_program_profiles(self) -> None:
        authority = riscv_snn_lab.load_runtime_gate_authority()
        self.assertEqual(
            authority["families"]["external_dyn_desc_ref"]["reference_program_profile"],
            "completed_single_step",
        )
        self.assertEqual(
            authority["families"]["external_dyn_desc_fault_ref"]["reference_program_profile"],
            "accepted_fault_single_step",
        )
        self.assertEqual(
            authority["families"]["external_dyn_desc_fault_rearm_ref"]["reference_program_profile"],
            "clear_then_refault",
        )
        self.assertEqual(
            authority["families"]["external_dyn_desc_fault_overwrite_chain_ref"]["reference_program_profile"],
            "overwrite_chain",
        )
        self.assertEqual(
            authority["families"]["barrier_wfi_order_ref"]["reference_program_profile"],
            "barrier_wait_then_completion",
        )

    def test_load_architecture_model_authority_freezes_fused_step_states(self) -> None:
        authority = riscv_snn_lab.load_architecture_model_authority()
        self.assertEqual(authority["authority_domain"], "architecture_model_only")
        self.assertEqual(authority["top_level_gate_role"], "none")
        fused_step = authority["fused_step_state_machine"]
        self.assertEqual(
            [state["name"] for state in fused_step["states"]],
            [
                "Idle",
                "Accepted",
                "Decoded",
                "ResourcesReserved",
                "Executing",
                "OutboundDraining",
                "BarrierWaiting",
                "Completed",
                "Faulted",
            ],
        )

    def test_fused_step_completion_boundary_is_machine_readable(self) -> None:
        fused_step = riscv_snn_lab.load_architecture_model_authority()["fused_step_state_machine"]
        completion_boundary = fused_step["completion_boundary"]
        self.assertEqual(completion_boundary["boundary_name"], "fused_step_completion_commit")
        self.assertEqual(
            completion_boundary["required_conditions"],
            [
                "architectural_state_committed",
                "local_outbound_handover_complete",
                "barrier_release_visible",
                "no_higher_priority_fault_pending",
            ],
        )
        self.assertEqual(
            fused_step["visibility_domains"],
            {
                "architectural_state": "software-visible state committed at completion boundary",
                "microarchitectural_progress": "execution progress before completion remains model-visible but not software-visible",
                "simulator_bookkeeping": "artifact refresh and report maintenance never redefine fused-step architectural completion",
            },
        )
        completed = next(state for state in fused_step["states"] if state["name"] == "Completed")
        self.assertTrue(completed["architecturally_visible"])
        self.assertFalse(completed["simulator_bookkeeping_only"])
        resources_reserved = next(state for state in fused_step["states"] if state["name"] == "ResourcesReserved")
        executing = next(state for state in fused_step["states"] if state["name"] == "Executing")
        outbound_draining = next(state for state in fused_step["states"] if state["name"] == "OutboundDraining")
        self.assertFalse(resources_reserved["simulator_bookkeeping_only"])
        self.assertFalse(executing["simulator_bookkeeping_only"])
        self.assertFalse(outbound_draining["simulator_bookkeeping_only"])

    def test_architecture_model_memory_taxonomy_freezes_required_domains(self) -> None:
        authority = riscv_snn_lab.load_architecture_model_authority()
        memory_taxonomy = authority["memory_taxonomy"]
        self.assertEqual(
            [domain["name"] for domain in memory_taxonomy["memory_domains"]],
            [
                "ControlMemory",
                "LocalStateMemory",
                "SynapseMemory",
                "BackingMemory",
                "TransferPath",
            ],
        )
        control_memory = next(domain for domain in memory_taxonomy["memory_domains"] if domain["name"] == "ControlMemory")
        local_state = next(domain for domain in memory_taxonomy["memory_domains"] if domain["name"] == "LocalStateMemory")
        synapse = next(domain for domain in memory_taxonomy["memory_domains"] if domain["name"] == "SynapseMemory")
        transfer_path = next(domain for domain in memory_taxonomy["memory_domains"] if domain["name"] == "TransferPath")
        self.assertTrue(control_memory["architecturally_visible"])
        self.assertIn("csr_state", control_memory["contains"])
        self.assertFalse(local_state["architecturally_visible"])
        self.assertFalse(synapse["architecturally_visible"])
        self.assertEqual(transfer_path["contention_scope"], "shared_transfer_and_memory_port_bandwidth")

    def test_architecture_model_fabric_taxonomy_freezes_stage_order_and_divergence_points(self) -> None:
        authority = riscv_snn_lab.load_architecture_model_authority()
        fabric_taxonomy = authority["fabric_taxonomy"]
        self.assertEqual(
            [stage["name"] for stage in fabric_taxonomy["stages"]],
            [
                "ingress_receive",
                "local_classify",
                "queue_merge",
                "execution_consume",
                "spike_generate",
                "egress_enqueue",
                "router_transit",
                "remote_ingress_commit",
            ],
        )
        self.assertEqual(
            fabric_taxonomy["allowed_divergence_points"],
            [
                "queue_occupancy",
                "backpressure",
                "multicast_expansion",
                "memory_service_conflict",
            ],
        )
        queue_merge = next(stage for stage in fabric_taxonomy["stages"] if stage["name"] == "queue_merge")
        router_transit = next(stage for stage in fabric_taxonomy["stages"] if stage["name"] == "router_transit")
        remote_commit = next(stage for stage in fabric_taxonomy["stages"] if stage["name"] == "remote_ingress_commit")
        self.assertFalse(queue_merge["architecturally_visible"])
        self.assertFalse(router_transit["architecturally_visible"])
        self.assertIn("router_credit_backpressure", router_transit["blocking_sources"])
        self.assertTrue(remote_commit["microarchitecturally_modeled"])

    def test_architecture_model_freezes_program_control_events_and_semantic_profiles(self) -> None:
        authority = riscv_snn_lab.load_architecture_model_authority()
        control_events = authority["program_control_event_taxonomy"]
        self.assertEqual(
            [event["name"] for event in control_events["events"]],
            [
                "completion_visible",
                "fault_snapshot_visible",
                "msnnfault_clear",
                "fault_snapshot_overwrite_visible",
                "barrier_wait_visible",
                "barrier_release_visible",
                "stat_snapshot_accepted_visible",
                "stat_snapshot_completed_count_visible",
                "stat_snapshot_provider_bound_visible",
                "stat_snapshot_bad_selector_fault_visible",
            ],
        )
        semantic_profiles = authority["program_semantic_profiles"]
        self.assertEqual(
            [profile["profile_name"] for profile in semantic_profiles["profiles"]],
            [
                "accepted_fault_single_step",
                "barrier_wait_then_completion",
                "clear_then_refault",
                "completed_single_step",
                "stat_snapshot_single_step",
                "stat_snapshot_completed_single_step",
                "stat_snapshot_provider_bound_single_step",
                "stat_snapshot_bad_selector_fault",
                "overwrite_chain",
            ],
        )
        barrier_profile = next(
            profile
            for profile in semantic_profiles["profiles"]
            if profile["profile_name"] == "barrier_wait_then_completion"
        )
        self.assertEqual(
            [step["step_name"] for step in barrier_profile["step_templates"]],
            ["barrier_wait_visible", "completion_visible_after_wfi"],
        )
        self.assertEqual(
            [step["terminal_state"] for step in barrier_profile["step_templates"]],
            ["BarrierWaiting", "Completed"],
        )
        snapshot_profile = next(
            profile
            for profile in semantic_profiles["profiles"]
            if profile["profile_name"] == "stat_snapshot_provider_bound_single_step"
        )
        self.assertEqual(
            snapshot_profile["step_templates"][0]["command_kind"],
            "stat_snapshot",
        )
        self.assertEqual(
            snapshot_profile["step_templates"][0]["snapshot_summary"]["selector_name"],
            "ProviderBound",
        )

    def test_architecture_model_declares_program_runtime_evidence_contract(self) -> None:
        authority = riscv_snn_lab.load_architecture_model_authority()
        contract = authority["program_runtime_evidence_contract"]
        self.assertEqual(contract["contract_name"], "program_runtime_evidence_contract")
        self.assertEqual(
            [row["name"] for row in contract["source_kinds"]],
            ["runtime_bridge_run_dir", "toolchain_run_dir"],
        )
        self.assertIn("essential_summary_mesh.json", contract["required_artifacts"])
        self.assertIn("mesh_stats.csv", contract["required_artifacts"])
        self.assertIn("validation.log", contract["required_artifacts"])
        self.assertIn("riscv_snn_completion_visible_count", contract["required_runtime_stats"])
        self.assertIn("completion_visible", contract["control_event_projection"])

    def test_reference_machine_skeleton_consumes_architecture_authority(self) -> None:
        authority = riscv_snn_lab.load_architecture_model_authority()

        machine = ReferenceMachine.from_lab_root()

        self.assertEqual(machine.authority_domain, "architecture_model_only")
        self.assertEqual(machine.fused_step.state_names(), [state["name"] for state in authority["fused_step_state_machine"]["states"]])
        self.assertEqual(machine.memory.domain_names(), [domain["name"] for domain in authority["memory_taxonomy"]["memory_domains"]])
        self.assertEqual(machine.fabric.stage_names(), [stage["name"] for stage in authority["fabric_taxonomy"]["stages"]])
        self.assertEqual(machine.fabric.allowed_divergence_points, tuple(authority["fabric_taxonomy"]["allowed_divergence_points"]))

    def test_reference_machine_skeleton_requires_semantic_sections(self) -> None:
        authority = riscv_snn_lab.load_architecture_model_authority()
        incomplete = dict(authority)
        incomplete.pop("fabric_taxonomy")

        with self.assertRaisesRegex(ValueError, "missing required architecture authority sections"):
            ReferenceMachine.from_authority(incomplete)

    def test_program_profile_model_requires_program_semantics_sections(self) -> None:
        module = importlib.import_module("riscv_snn_isa_lab.architecture_model.program_profile_model")
        model_cls = getattr(module, "ProgramProfileModel", None)
        self.assertIsNotNone(model_cls)

        authority = riscv_snn_lab.load_architecture_model_authority()
        incomplete = dict(authority)
        incomplete.pop("program_semantic_profiles")

        with self.assertRaisesRegex(ValueError, "missing required program authority sections"):
            model_cls.from_authority(incomplete)

    def test_program_evidence_model_requires_runtime_evidence_contract_section(self) -> None:
        module = importlib.import_module("riscv_snn_isa_lab.architecture_model.program_evidence_model")
        model_cls = getattr(module, "ProgramEvidenceModel", None)
        self.assertIsNotNone(model_cls)

        authority = riscv_snn_lab.load_architecture_model_authority()
        incomplete = dict(authority)
        incomplete.pop("program_runtime_evidence_contract")

        with self.assertRaisesRegex(ValueError, "missing required program evidence authority sections"):
            model_cls.from_authority(incomplete)

    def test_program_evidence_model_extracts_runtime_bridge_run_dir(self) -> None:
        module = importlib.import_module("riscv_snn_isa_lab.architecture_model.program_evidence_model")
        model_cls = getattr(module, "ProgramEvidenceModel", None)
        self.assertIsNotNone(model_cls)

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            run_dir = self._seed_program_evidence_run_dir(td_path)
            model = model_cls.from_authority(riscv_snn_lab.load_architecture_model_authority())

            evidence = model.extract_from_run_dir(
                family="external_dyn_desc_ref",
                profile_name="completed_single_step",
                family_policy={"reference_program_profile": "completed_single_step"},
                run_dir=run_dir,
                source_kind="runtime_bridge_run_dir",
                source_origin="runtime_bridge_equiv",
                program_name="external_dyn_desc_ref",
            )

        self.assertTrue(evidence["evidence_ok"])
        self.assertEqual(evidence["source_kind"], "runtime_bridge_run_dir")
        self.assertEqual(evidence["source_origin"], "runtime_bridge_equiv")
        self.assertEqual(evidence["runtime_program_summary"]["reference_program_profile"], "completed_single_step")
        self.assertEqual(evidence["runtime_program_summary"]["step_count"], 1)
        completion_visible = next(
            row
            for row in evidence["control_event_observations"]
            if row["event_name"] == "completion_visible"
        )
        self.assertEqual(completion_visible["evidence_mode"], "runtime_stat_nonzero")
        self.assertTrue(completion_visible["supported"])

    def test_reference_program_evidence_rows_for_family_collect_runtime_and_toolchain_sources(self) -> None:
        collector = getattr(riscv_snn_lab, "_reference_program_evidence_rows_for_family", None)
        self.assertIsNotNone(collector)

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)
            self._seed_program_evidence_authorities(lab_root)

            runtime_run_dir = self._seed_program_evidence_run_dir(
                td_path / "runtime",
                completion_visible_count=64,
                completion_consumed_count=64,
                fused_step_completion_count=64,
                fault_count=0,
            )
            toolchain_run_dir = self._seed_program_evidence_run_dir(
                td_path / "toolchain",
                completion_visible_count=64,
                completion_consumed_count=64,
                fused_step_completion_count=64,
                fault_count=0,
            )

            (refs_dir / "2026-04-16-external-dyn-desc-ref-equiv.json").write_text(
                json.dumps(
                    {
                        "family": "external_dyn_desc_ref",
                        "runtime_bridge": {"run_dir": str(runtime_run_dir)},
                    }
                ),
                encoding="utf-8",
            )
            (refs_dir / "2026-04-16-toolchain-regress-matrix.json").write_text(
                json.dumps(
                    {
                        "results": [
                            {
                                "program": "external_dyn_desc_ref_toolchain",
                                "run_dir": str(toolchain_run_dir),
                                "manifest_path": str(td_path / "manifest.md"),
                                "suite": "toolchain",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (lab_root / "firmware_src" / "external_dyn_desc_ref_toolchain").mkdir(parents=True, exist_ok=True)

            rows = collector(family="external_dyn_desc_ref", lab_root=lab_root)

        self.assertEqual([row["source_kind"] for row in rows], ["runtime_bridge_run_dir", "toolchain_run_dir"])
        self.assertTrue(all(row["evidence_ok"] for row in rows))
        self.assertEqual(
            [row["runtime_program_summary"]["reference_program_profile"] for row in rows],
            ["completed_single_step", "completed_single_step"],
        )

    def test_reference_program_evidence_rows_skip_toolchain_when_family_is_outside_official_toolchain_surface(self) -> None:
        collector = getattr(riscv_snn_lab, "_reference_program_evidence_rows_for_family", None)
        self.assertIsNotNone(collector)

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)
            self._seed_program_evidence_authorities(lab_root)

            runtime_run_dir = self._seed_program_evidence_run_dir(
                td_path / "runtime",
                completion_visible_count=64,
                completion_consumed_count=0,
                fused_step_completion_count=64,
                fault_count=64,
            )
            (refs_dir / "2026-04-16-queue-backpressure-ref-equiv.json").write_text(
                json.dumps(
                    {
                        "family": "queue_backpressure_ref",
                        "runtime_bridge": {"run_dir": str(runtime_run_dir)},
                    }
                ),
                encoding="utf-8",
            )
            (refs_dir / "2026-04-16-toolchain-regress-matrix.json").write_text(
                json.dumps(
                    {
                        "results": [
                            {
                                "program": "external_dyn_desc_ref_toolchain",
                                "run_dir": str(runtime_run_dir),
                                "manifest_path": str(td_path / "manifest.md"),
                                "suite": "toolchain",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (lab_root / "firmware_src" / "queue_backpressure_ref_toolchain").mkdir(parents=True, exist_ok=True)

            rows = collector(family="queue_backpressure_ref", lab_root=lab_root)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_kind"], "runtime_bridge_run_dir")

    def test_reference_program_evidence_rows_for_snapshot_family_collect_manifest_backed_sources(self) -> None:
        collector = getattr(riscv_snn_lab, "_reference_program_evidence_rows_for_family", None)
        self.assertIsNotNone(collector)

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            runs_dir = lab_root / "runs"
            runs_dir.mkdir(parents=True, exist_ok=True)
            self._seed_program_evidence_authorities(lab_root)

            runtime_run_dir = self._seed_program_evidence_run_dir(
                td_path / "runtime",
                completion_visible_count=1,
                completion_consumed_count=1,
                fused_step_completion_count=0,
                fault_count=0,
                provider_bound=1,
            )
            toolchain_run_dir = self._seed_program_evidence_run_dir(
                td_path / "toolchain",
                completion_visible_count=1,
                completion_consumed_count=1,
                fused_step_completion_count=0,
                fault_count=0,
                provider_bound=1,
            )

            (runs_dir / "2026-04-16-stat-snapshot-provider-bound-ref-smoke.md").write_text(
                f"- 历史 run dir：`{runtime_run_dir}`\n",
                encoding="utf-8",
            )
            (runs_dir / "2026-04-16-stat-snapshot-provider-bound-ref-toolchain-smoke.md").write_text(
                f"- 历史 run dir：`{toolchain_run_dir}`\n",
                encoding="utf-8",
            )
            (lab_root / "firmware_src" / "stat_snapshot_provider_bound_ref_toolchain").mkdir(
                parents=True,
                exist_ok=True,
            )

            rows = collector(family="stat_snapshot_provider_bound_ref", lab_root=lab_root)

        self.assertEqual(
            [row["source_kind"] for row in rows],
            ["runtime_bridge_run_dir", "toolchain_run_dir"],
        )
        self.assertEqual(
            [row["source_origin"] for row in rows],
            ["runtime_manifest", "toolchain_manifest"],
        )
        self.assertTrue(all(row["evidence_ok"] for row in rows))
        self.assertEqual(
            [row["runtime_program_summary"]["reference_program_profile"] for row in rows],
            ["stat_snapshot_provider_bound_single_step", "stat_snapshot_provider_bound_single_step"],
        )

    def test_reference_machine_executes_fused_step_to_completed_when_boundary_satisfied(self) -> None:
        machine = ReferenceMachine.from_lab_root()

        result = machine.execute_fused_step(
            condition_values={
                "architectural_state_committed": True,
                "local_outbound_handover_complete": True,
                "barrier_release_visible": True,
                "no_higher_priority_fault_pending": True,
            }
        )

        self.assertEqual(result.terminal_state, "Completed")
        self.assertEqual(
            result.visited_states,
            [
                "Accepted",
                "Decoded",
                "ResourcesReserved",
                "Executing",
                "OutboundDraining",
                "BarrierWaiting",
                "Completed",
            ],
        )
        self.assertTrue(result.completion_retired)
        self.assertFalse(result.faulted)
        self.assertEqual(result.architectural_state["visibility_domain"], "architectural_state")

    def test_reference_machine_executes_fused_step_to_faulted_when_fault_boundary_satisfied(self) -> None:
        machine = ReferenceMachine.from_lab_root()

        result = machine.execute_fused_step(
            condition_values={
                "fault_classified": True,
                "fault_csr_committed": True,
                "completion_suppressed_or_replaced_by_fault": True,
            }
        )

        self.assertEqual(result.terminal_state, "Faulted")
        self.assertEqual(result.visited_states[-1], "Faulted")
        self.assertFalse(result.completion_retired)
        self.assertTrue(result.faulted)
        self.assertEqual(result.architectural_state["visibility_domain"], "fault_boundary")

    def test_reference_machine_keeps_fused_step_waiting_when_completion_boundary_is_incomplete(self) -> None:
        machine = ReferenceMachine.from_lab_root()

        result = machine.execute_fused_step(
            condition_values={
                "architectural_state_committed": True,
                "local_outbound_handover_complete": True,
                "barrier_release_visible": False,
                "no_higher_priority_fault_pending": True,
            }
        )

        self.assertEqual(result.terminal_state, "BarrierWaiting")
        self.assertEqual(result.visited_states[-1], "BarrierWaiting")
        self.assertFalse(result.completion_retired)
        self.assertFalse(result.faulted)
        self.assertEqual(result.microarchitectural_progress["waiting_on"], ["barrier_release_visible"])

    def test_reference_machine_emits_memory_fabric_and_divergence_accounting(self) -> None:
        machine = ReferenceMachine.from_lab_root()

        result = machine.execute_fused_step(
            condition_values={
                "architectural_state_committed": True,
                "local_outbound_handover_complete": True,
                "barrier_release_visible": True,
                "no_higher_priority_fault_pending": True,
            },
            metadata={
                "memory_domains": ["ControlMemory", "LocalStateMemory"],
                "fabric_stages": ["ingress_receive", "execution_consume", "remote_ingress_commit"],
                "divergence_points": ["queue_occupancy", "backpressure"],
            },
        )

        self.assertEqual([event.domain for event in result.memory_events], ["ControlMemory", "LocalStateMemory"])
        self.assertEqual(
            [event.stage for event in result.fabric_events],
            ["ingress_receive", "execution_consume", "remote_ingress_commit"],
        )
        self.assertEqual(
            [event.kind for event in result.divergence_observations],
            ["queue_occupancy", "backpressure"],
        )
        self.assertEqual(result.microarchitectural_progress["memory_event_count"], 2)
        self.assertEqual(result.microarchitectural_progress["fabric_event_count"], 3)
        self.assertEqual(result.microarchitectural_progress["divergence_count"], 2)

    def test_reference_machine_rejects_unknown_divergence_points(self) -> None:
        machine = ReferenceMachine.from_lab_root()

        with self.assertRaisesRegex(ValueError, "unknown divergence point"):
            machine.execute_fused_step(
                condition_values={
                    "architectural_state_committed": True,
                    "local_outbound_handover_complete": True,
                    "barrier_release_visible": True,
                    "no_higher_priority_fault_pending": True,
                },
                metadata={
                    "divergence_points": ["not_in_authority"],
                },
            )

    def test_runtime_compare_classifies_allowed_divergence_when_semantics_align(self) -> None:
        machine = ReferenceMachine.from_lab_root()
        reference_result = machine.execute_fused_step(
            condition_values={
                "architectural_state_committed": True,
                "local_outbound_handover_complete": True,
                "barrier_release_visible": True,
                "no_higher_priority_fault_pending": True,
            },
            metadata={
                "memory_domains": ["ControlMemory"],
                "fabric_stages": ["ingress_receive", "execution_consume"],
                "divergence_points": ["queue_occupancy"],
            },
        )

        summary = runtime_compare.compare_reference_to_runtime(
            reference_result,
            {
                "terminal_state": "Completed",
                "memory_domains": ["ControlMemory"],
                "fabric_stages": ["ingress_receive", "execution_consume"],
                "divergence_points": ["queue_occupancy"],
            },
            allowed_divergence_points=("queue_occupancy", "backpressure"),
        )

        self.assertEqual(summary["status"], "allowed_divergence")
        self.assertTrue(summary["gate_ok"])
        self.assertEqual(summary["allowed_divergence_points"], ["queue_occupancy"])

    def test_reference_machine_executes_program_and_tracks_clear_then_refault_lifecycle(self) -> None:
        step_cls = getattr(model_types, "ReferenceProgramStep", None)
        request_cls = getattr(model_types, "ReferenceProgramRequest", None)
        self.assertIsNotNone(step_cls)
        self.assertIsNotNone(request_cls)

        machine = ReferenceMachine.from_lab_root()
        result = machine.execute_program(
            request_cls(
                family="external_dyn_desc_fault_rearm_ref",
                steps=[
                    step_cls(
                        step_name="fault_visible",
                        condition_values={
                            "fault_classified": True,
                            "fault_csr_committed": True,
                            "completion_suppressed_or_replaced_by_fault": True,
                        },
                        metadata={
                            "memory_domains": ["ControlMemory"],
                            "fabric_stages": ["ingress_receive", "execution_consume"],
                            "divergence_points": ["queue_occupancy"],
                        },
                    ),
                    step_cls(
                        step_name="fault_rearmed_visible",
                        condition_values={
                            "fault_classified": True,
                            "fault_csr_committed": True,
                            "completion_suppressed_or_replaced_by_fault": True,
                        },
                        metadata={
                            "memory_domains": ["ControlMemory"],
                            "fabric_stages": ["ingress_receive", "execution_consume"],
                            "divergence_points": ["queue_occupancy"],
                        },
                        clear_fault_before_step=True,
                    ),
                ],
            )
        )

        self.assertEqual(result.step_count, 2)
        self.assertEqual(result.terminal_state, "Faulted")
        self.assertEqual(result.terminal_states, ["Faulted", "Faulted"])
        self.assertEqual(result.fault_step_indices, [0, 1])
        self.assertEqual(result.clear_fault_before_step_indices, [1])
        self.assertEqual(result.fault_snapshot_sequence, ["fault_step_0", "fault_step_1"])
        self.assertEqual(result.divergence_point_sequences, [["queue_occupancy"], ["queue_occupancy"]])

    def test_reference_machine_executes_program_and_tracks_barrier_wait_then_completion(self) -> None:
        step_cls = getattr(model_types, "ReferenceProgramStep", None)
        request_cls = getattr(model_types, "ReferenceProgramRequest", None)
        self.assertIsNotNone(step_cls)
        self.assertIsNotNone(request_cls)

        machine = ReferenceMachine.from_lab_root()
        result = machine.execute_program(
            request_cls(
                family="barrier_wfi_order_ref",
                steps=[
                    step_cls(
                        step_name="barrier_wait_visible",
                        condition_values={
                            "architectural_state_committed": True,
                            "local_outbound_handover_complete": True,
                            "barrier_release_visible": False,
                            "no_higher_priority_fault_pending": True,
                        },
                        metadata={
                            "memory_domains": ["ControlMemory"],
                            "fabric_stages": ["ingress_receive", "execution_consume"],
                        },
                    ),
                    step_cls(
                        step_name="completion_visible_after_wfi",
                        condition_values={
                            "architectural_state_committed": True,
                            "local_outbound_handover_complete": True,
                            "barrier_release_visible": True,
                            "no_higher_priority_fault_pending": True,
                        },
                        metadata={
                            "memory_domains": ["ControlMemory"],
                            "fabric_stages": ["ingress_receive", "execution_consume"],
                            "divergence_points": ["backpressure"],
                        },
                    ),
                ],
            )
        )

        self.assertEqual(result.step_count, 2)
        self.assertEqual(result.terminal_state, "Completed")
        self.assertEqual(result.terminal_states, ["BarrierWaiting", "Completed"])
        self.assertEqual(result.barrier_wait_step_indices, [0])
        self.assertEqual(result.completion_step_indices, [1])
        self.assertEqual(result.divergence_point_sequences, [[], ["backpressure"]])

    def test_runtime_compare_classifies_reference_program_allowed_divergence_when_sequences_align(self) -> None:
        compare_program = getattr(runtime_compare, "compare_reference_program_to_runtime", None)
        step_cls = getattr(model_types, "ReferenceProgramStep", None)
        request_cls = getattr(model_types, "ReferenceProgramRequest", None)
        self.assertIsNotNone(compare_program)
        self.assertIsNotNone(step_cls)
        self.assertIsNotNone(request_cls)

        machine = ReferenceMachine.from_lab_root()
        reference_result = machine.execute_program(
            request_cls(
                family="barrier_wfi_order_ref",
                steps=[
                    step_cls(
                        step_name="barrier_wait_visible",
                        condition_values={
                            "architectural_state_committed": True,
                            "local_outbound_handover_complete": True,
                            "barrier_release_visible": False,
                            "no_higher_priority_fault_pending": True,
                        },
                        metadata={
                            "memory_domains": ["ControlMemory"],
                            "fabric_stages": ["ingress_receive", "execution_consume"],
                        },
                    ),
                    step_cls(
                        step_name="completion_visible_after_wfi",
                        condition_values={
                            "architectural_state_committed": True,
                            "local_outbound_handover_complete": True,
                            "barrier_release_visible": True,
                            "no_higher_priority_fault_pending": True,
                        },
                        metadata={
                            "memory_domains": ["ControlMemory"],
                            "fabric_stages": ["ingress_receive", "execution_consume"],
                            "divergence_points": ["backpressure"],
                        },
                    ),
                ],
            )
        )

        summary = compare_program(
            reference_result,
            {
                "family": "barrier_wfi_order_ref",
                "steps": [
                    {
                        "step_name": "barrier_wait_visible",
                        "terminal_state": "BarrierWaiting",
                        "memory_domains": ["ControlMemory"],
                        "fabric_stages": ["ingress_receive", "execution_consume"],
                        "divergence_points": [],
                    },
                    {
                        "step_name": "completion_visible_after_wfi",
                        "terminal_state": "Completed",
                        "memory_domains": ["ControlMemory"],
                        "fabric_stages": ["ingress_receive", "execution_consume"],
                        "divergence_points": ["backpressure"],
                    },
                ],
                "completion_step_indices": [1],
                "fault_step_indices": [],
                "barrier_wait_step_indices": [0],
                "clear_fault_before_step_indices": [],
                "overwrite_fault_step_indices": [],
                "fault_snapshot_sequence": [],
            },
            allowed_divergence_points=("queue_occupancy", "backpressure"),
        )

        self.assertEqual(summary["status"], "allowed_divergence")
        self.assertTrue(summary["gate_ok"])
        self.assertTrue(summary["completion_step_indices_match"])
        self.assertTrue(summary["barrier_wait_step_indices_match"])
        self.assertEqual(summary["allowed_divergence_points"], ["backpressure"])

    def test_program_profile_model_builds_reference_program_requests_for_frozen_profiles(self) -> None:
        module = importlib.import_module("riscv_snn_isa_lab.architecture_model.program_profile_model")
        model_cls = getattr(module, "ProgramProfileModel", None)
        self.assertIsNotNone(model_cls)

        runtime_authority = riscv_snn_lab.load_runtime_gate_authority()
        architecture_authority = riscv_snn_lab.load_architecture_model_authority()
        model = model_cls.from_authority(architecture_authority)
        expected = {
            "external_dyn_desc_ref": {
                "step_names": ["program_step_0"],
                "terminal_states": ["Completed"],
                "clear_steps": [],
                "overwrite_steps": [],
                "command_kinds": ["fused_step"],
                "snapshot_selector_names": [],
            },
            "external_dyn_desc_fault_ref": {
                "step_names": ["program_step_0"],
                "terminal_states": ["Faulted"],
                "clear_steps": [],
                "overwrite_steps": [],
                "command_kinds": ["fused_step"],
                "snapshot_selector_names": [],
            },
            "external_dyn_desc_fault_rearm_ref": {
                "step_names": ["fault_visible", "fault_rearmed_visible"],
                "terminal_states": ["Faulted", "Faulted"],
                "clear_steps": [1],
                "overwrite_steps": [],
                "command_kinds": ["fused_step", "fused_step"],
                "snapshot_selector_names": [],
            },
            "external_dyn_desc_fault_overwrite_chain_ref": {
                "step_names": ["fault_visible", "fault_overwrite_visible"],
                "terminal_states": ["Faulted", "Faulted"],
                "clear_steps": [],
                "overwrite_steps": [1],
                "command_kinds": ["fused_step", "fused_step"],
                "snapshot_selector_names": [],
            },
            "barrier_wfi_order_ref": {
                "step_names": ["barrier_wait_visible", "completion_visible_after_wfi"],
                "terminal_states": ["BarrierWaiting", "Completed"],
                "clear_steps": [],
                "overwrite_steps": [],
                "command_kinds": ["fused_step", "fused_step"],
                "snapshot_selector_names": [],
            },
            "stat_snapshot_ref": {
                "step_names": ["stat_snapshot_accepted_visible"],
                "terminal_states": ["Completed"],
                "clear_steps": [],
                "overwrite_steps": [],
                "command_kinds": ["stat_snapshot"],
                "snapshot_selector_names": ["AcceptedCommands"],
            },
            "stat_snapshot_completed_ref": {
                "step_names": ["stat_snapshot_completed_count_visible"],
                "terminal_states": ["Completed"],
                "clear_steps": [],
                "overwrite_steps": [],
                "command_kinds": ["stat_snapshot"],
                "snapshot_selector_names": ["CompletedCommands"],
            },
            "stat_snapshot_provider_bound_ref": {
                "step_names": ["stat_snapshot_provider_bound_visible"],
                "terminal_states": ["Completed"],
                "clear_steps": [],
                "overwrite_steps": [],
                "command_kinds": ["stat_snapshot"],
                "snapshot_selector_names": ["ProviderBound"],
            },
            "stat_snapshot_bad_selector_ref": {
                "step_names": ["stat_snapshot_bad_selector_fault_visible"],
                "terminal_states": ["Faulted"],
                "clear_steps": [],
                "overwrite_steps": [],
                "command_kinds": ["stat_snapshot"],
                "snapshot_selector_names": ["InvalidSelector"],
            },
        }

        for family, family_expected in expected.items():
            with self.subTest(family=family):
                family_policy = runtime_authority["families"][family]
                request = model.build_request(
                    family=family,
                    profile_name=family_policy["reference_program_profile"],
                    family_policy=family_policy,
                )
                self.assertEqual(request.family, family)
                self.assertEqual(
                    [step.step_name for step in request.steps],
                    family_expected["step_names"],
                )
                self.assertEqual(
                    [step.metadata["terminal_state"] for step in request.steps],
                    family_expected["terminal_states"],
                )
                self.assertEqual(
                    [step.command_kind for step in request.steps],
                    family_expected["command_kinds"],
                )
                self.assertEqual(
                    [
                        (step.metadata.get("snapshot_summary") or {}).get("selector_name")
                        for step in request.steps
                        if step.command_kind == "stat_snapshot"
                    ],
                    family_expected["snapshot_selector_names"],
                )
                self.assertEqual(
                    [
                        index
                        for index, step in enumerate(request.steps)
                        if step.clear_fault_before_step
                    ],
                    family_expected["clear_steps"],
                )
                self.assertEqual(
                    [
                        index
                        for index, step in enumerate(request.steps)
                        if step.overwrite_visible_fault_snapshot
                    ],
                    family_expected["overwrite_steps"],
                )

    def test_reference_machine_executes_program_and_tracks_stat_snapshot_signatures(self) -> None:
        step_cls = getattr(model_types, "ReferenceProgramStep", None)
        request_cls = getattr(model_types, "ReferenceProgramRequest", None)
        self.assertIsNotNone(step_cls)
        self.assertIsNotNone(request_cls)

        machine = ReferenceMachine.from_lab_root()
        result = machine.execute_program(
            request_cls(
                family="stat_snapshot_provider_bound_ref",
                steps=[
                    step_cls(
                        step_name="stat_snapshot_provider_bound_visible",
                        command_kind="stat_snapshot",
                        condition_values={
                            "architectural_state_committed": True,
                            "local_outbound_handover_complete": True,
                            "barrier_release_visible": True,
                            "no_higher_priority_fault_pending": True,
                        },
                        metadata={
                            "terminal_state": "Completed",
                            "control_events": [
                                "completion_visible",
                                "stat_snapshot_provider_bound_visible",
                            ],
                            "memory_domains": ["ControlMemory"],
                            "fabric_stages": [],
                            "snapshot_summary": {
                                "snapshot_kind": "provider_bound",
                                "selector_name": "ProviderBound",
                                "selector_value": 2,
                                "result_kind": "boolean_flag",
                                "result_field": "provider_bound",
                            },
                        },
                    )
                ],
            )
        )

        self.assertEqual(result.command_kind_sequence, ["stat_snapshot"])
        self.assertEqual(result.snapshot_step_indices, [0])
        self.assertEqual(
            result.snapshot_signature_sequence,
            ["provider_bound:ProviderBound:2:boolean_flag"],
        )
        self.assertEqual(
            result.snapshot_summary_sequence[0]["result_field"],
            "provider_bound",
        )

    def test_reference_program_profile_binding_validation_covers_all_equiv_families(self) -> None:
        validate = getattr(riscv_snn_lab, "validate_reference_program_profile_bindings", None)
        self.assertIsNotNone(validate)

        summary = validate()

        self.assertTrue(summary["all_ok"])
        self.assertEqual(
            sorted(row["family"] for row in summary["rows"]),
            sorted(riscv_snn_lab.EQUIV_FAMILY_SPECS),
        )
        self.assertEqual(summary["invalid_families"], [])

    def test_runtime_gate_family_policy_requires_declared_family(self) -> None:
        resolver = getattr(riscv_snn_lab, "_runtime_gate_family_policy", None)
        self.assertIsNotNone(resolver)

        with self.assertRaisesRegex(ValueError, "unknown runtime gate family"):
            resolver("stat_snapshot_family_that_does_not_exist")

    def test_reference_program_compare_family_catalog_adds_snapshot_families_without_expanding_equiv_specs(self) -> None:
        family_names = getattr(riscv_snn_lab, "_reference_program_compare_family_names", None)
        self.assertIsNotNone(family_names)

        names = set(family_names())

        self.assertIn("external_dyn_desc_ref", names)
        self.assertIn("stat_snapshot_ref", names)
        self.assertIn("stat_snapshot_completed_ref", names)
        self.assertIn("stat_snapshot_provider_bound_ref", names)
        self.assertIn("stat_snapshot_bad_selector_ref", names)
        self.assertNotIn("stat_snapshot_ref", riscv_snn_lab.EQUIV_FAMILY_SPECS)

    def test_reference_program_primary_input_for_snapshot_family_is_nonblocking_when_manifest_missing(self) -> None:
        loader = getattr(riscv_snn_lab, "_reference_program_primary_input_for_family", None)
        self.assertIsNotNone(loader)

        with tempfile.TemporaryDirectory() as td:
            lab_root = Path(td) / "riscv_snn_isa_lab"
            (lab_root / "runs").mkdir(parents=True, exist_ok=True)

            payload, path = loader("stat_snapshot_ref", lab_root=lab_root)

        self.assertEqual(payload["source_kind"], "runtime_manifest")
        self.assertEqual(payload["status"], "manifest_missing")
        self.assertEqual(path, riscv_snn_lab.default_manifest_path("stat_snapshot_ref", lab_root=lab_root))

    def test_run_reference_program_compare_family_uses_authority_backed_program_builder_and_evidence_rows(self) -> None:
        request = model_types.ReferenceProgramRequest(
            family="external_dyn_desc_ref",
            steps=[
                model_types.ReferenceProgramStep(
                    step_name="program_step_0",
                    condition_values={
                        "architectural_state_committed": True,
                        "local_outbound_handover_complete": True,
                        "barrier_release_visible": True,
                        "no_higher_priority_fault_pending": True,
                    },
                    metadata={
                        "terminal_state": "Completed",
                        "control_events": [],
                        "memory_domains": ["ControlMemory"],
                        "fabric_stages": ["ingress_receive", "execution_consume"],
                        "divergence_points": ["queue_occupancy"],
                    },
                )
            ],
        )
        runtime_summary = {
            "family": "external_dyn_desc_ref",
            "reference_program_profile": "completed_single_step",
            "steps": [
                {
                    "step_name": "program_step_0",
                    "terminal_state": "Completed",
                    "control_events": [],
                    "memory_domains": ["ControlMemory"],
                    "fabric_stages": ["ingress_receive", "execution_consume"],
                    "divergence_points": ["queue_occupancy"],
                }
            ],
            "completion_step_indices": [0],
            "fault_step_indices": [],
            "barrier_wait_step_indices": [],
            "clear_fault_before_step_indices": [],
            "overwrite_fault_step_indices": [],
            "fault_snapshot_sequence": [],
            "evidence_source_kind": "runtime_bridge_run_dir",
            "evidence_source_path": "/tmp/runtime-bridge-run",
            "evidence_origin": "runtime_bridge_equiv",
        }

        with tempfile.TemporaryDirectory() as td:
            summary_path = Path(td) / "reference-program-compare.json"
            with mock.patch.object(
                riscv_snn_lab,
                "_latest_reference_compare_family_input",
                return_value=({"status": "PASS"}, Path("/tmp/fake-equiv.json")),
            ):
                with mock.patch.object(
                    riscv_snn_lab,
                    "_reference_program_request_for_family",
                    return_value=request,
                    create=True,
                ) as request_builder:
                    with mock.patch.object(
                        riscv_snn_lab,
                        "_reference_program_evidence_rows_for_family",
                        return_value=[
                            {
                                "source_kind": "runtime_bridge_run_dir",
                                "source_origin": "runtime_bridge_equiv",
                                "program_name": "external_dyn_desc_ref",
                                "evidence_source_path": "/tmp/runtime-bridge-run",
                                "evidence_ok": True,
                                "evidence_gate_reasons": [],
                                "runtime_program_summary": runtime_summary,
                            }
                        ],
                        create=True,
                    ) as evidence_rows:
                        summary = riscv_snn_lab.run_reference_program_compare_family(
                            family="external_dyn_desc_ref",
                            summary_path=summary_path,
                        )

        request_builder.assert_called_once()
        evidence_rows.assert_called_once()
        self.assertEqual(summary["family"], "external_dyn_desc_ref")
        self.assertEqual(summary["runtime_program_summary"]["steps"], runtime_summary["steps"])
        self.assertEqual(summary["runtime_program_summary"]["evidence_source_kind"], "runtime_bridge_run_dir")
        self.assertEqual(summary["evidence_rows"][0]["source_kind"], "runtime_bridge_run_dir")
        self.assertEqual(summary["evidence_rows"][0]["evidence_source_path"], "/tmp/runtime-bridge-run")

    def test_run_reference_program_compare_family_accepts_manifest_backed_snapshot_primary_input(self) -> None:
        request = model_types.ReferenceProgramRequest(
            family="stat_snapshot_ref",
            steps=[
                model_types.ReferenceProgramStep(
                    step_name="snapshot_visible",
                    condition_values={
                        "architectural_state_committed": True,
                        "local_outbound_handover_complete": True,
                        "barrier_release_visible": True,
                        "no_higher_priority_fault_pending": True,
                    },
                    metadata={
                        "terminal_state": "Completed",
                        "control_events": ["completion_visible"],
                        "memory_domains": ["ControlMemory"],
                        "fabric_stages": ["ingress_receive", "execution_consume"],
                    },
                )
            ],
        )
        runtime_summary = {
            "family": "stat_snapshot_ref",
            "reference_program_profile": "stat_snapshot_single_step",
            "steps": [
                {
                    "step_name": "snapshot_visible",
                    "terminal_state": "Completed",
                    "control_events": ["completion_visible"],
                    "memory_domains": ["ControlMemory"],
                    "fabric_stages": ["ingress_receive", "execution_consume"],
                    "divergence_points": [],
                }
            ],
            "completion_step_indices": [0],
            "fault_step_indices": [],
            "barrier_wait_step_indices": [],
            "clear_fault_before_step_indices": [],
            "overwrite_fault_step_indices": [],
            "fault_snapshot_sequence": [],
            "evidence_source_kind": "runtime_bridge_run_dir",
            "evidence_source_path": "/tmp/stat-snapshot-run",
            "evidence_origin": "runtime_manifest",
        }

        with tempfile.TemporaryDirectory() as td:
            summary_path = Path(td) / "stat-snapshot-reference-program-compare.json"
            with mock.patch.object(
                riscv_snn_lab,
                "_reference_program_primary_input_for_family",
                return_value=(
                    {
                        "source_kind": "runtime_manifest",
                        "status": "manifest_present",
                        "program": "stat_snapshot_ref",
                    },
                    Path("/tmp/stat_snapshot_ref-manifest.md"),
                ),
                create=True,
            ):
                with mock.patch.object(
                    riscv_snn_lab,
                    "_reference_program_request_for_family",
                    return_value=request,
                    create=True,
                ):
                    with mock.patch.object(
                        riscv_snn_lab,
                        "_reference_program_evidence_rows_for_family",
                        return_value=[
                            {
                                "source_kind": "runtime_bridge_run_dir",
                                "source_origin": "runtime_manifest",
                                "program_name": "stat_snapshot_ref",
                                "evidence_source_path": "/tmp/stat-snapshot-run",
                                "evidence_ok": True,
                                "evidence_gate_reasons": [],
                                "runtime_program_summary": runtime_summary,
                            }
                        ],
                        create=True,
                    ):
                        summary = riscv_snn_lab.run_reference_program_compare_family(
                            family="stat_snapshot_ref",
                            summary_path=summary_path,
                        )

        self.assertEqual(summary["family"], "stat_snapshot_ref")
        self.assertEqual(summary["source_input_kind"], "runtime_manifest")
        self.assertEqual(summary["source_input_path"], "/tmp/stat_snapshot_ref-manifest.md")
        self.assertEqual(summary["source_input_status"], "manifest_present")
        self.assertEqual(summary["runtime_program_summary"]["reference_program_profile"], "stat_snapshot_single_step")

    def test_export_reference_compare_surface_persists_nonblocking_report(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)
            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "supplementary_surfaces": {},
                    }
                ),
                encoding="utf-8",
            )

            machine = ReferenceMachine.from_lab_root(lab_root=lab_root)
            reference_result = machine.execute_fused_step(
                condition_values={
                    "architectural_state_committed": True,
                    "local_outbound_handover_complete": True,
                    "barrier_release_visible": True,
                    "no_higher_priority_fault_pending": True,
                },
                metadata={
                    "memory_domains": ["ControlMemory"],
                    "fabric_stages": ["ingress_receive", "execution_consume"],
                    "divergence_points": ["queue_occupancy"],
                },
            )

            summary = riscv_snn_lab.export_reference_compare_surface(
                reference_result=reference_result,
                runtime_summary={
                    "terminal_state": "Completed",
                    "memory_domains": ["ControlMemory"],
                    "fabric_stages": ["ingress_receive", "execution_consume"],
                    "divergence_points": ["queue_occupancy"],
                },
                sidecar_path=sidecar_path,
                lab_root=lab_root,
            )
            persisted_sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))

        self.assertEqual(summary["status"], "allowed_divergence")
        self.assertTrue(Path(summary["report_path"]).exists())
        self.assertTrue(Path(summary["summary_md_path"]).exists())
        self.assertTrue(Path(summary["current_mainline_status_path"]).exists())
        self.assertIn("reference_compare", persisted_sidecar["supplementary_surfaces"])
        self.assertFalse(persisted_sidecar["supplementary_surfaces"]["reference_compare"]["blocking"])

    def test_load_reference_program_compare_supplementary_surface_reads_stable_report(self) -> None:
        loader = getattr(riscv_snn_lab, "_load_reference_program_compare_supplementary_surface", None)
        self.assertIsNotNone(loader)

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            report_path = td_path / "reference-program-compare-nightly-report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "reference_program_compare_surface_report",
                        "authority_scope": "reference_program_compare_only",
                        "gate_name": "reference_program_model_runtime_compare",
                        "gate_version": "1.0",
                        "gate_ok": True,
                        "gate_reasons": [],
                        "history": {
                            "latest_date": "2026-04-14",
                            "stale": False,
                            "freshness_mode": "reference_program_compare_latest_only",
                            "effective_all_dates_ok": True,
                        },
                        "stable_surfaces": {
                            "report_path": str(report_path),
                            "summary_md_path": str(td_path / "reference-program-compare-nightly-summary.md"),
                            "current_mainline_status_path": str(td_path / "reference-program-compare-current-status.md"),
                        },
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(
                riscv_snn_lab,
                "_reference_program_compare_stable_surface_paths",
                return_value={
                    "history_path": td_path / "reference-program-compare-history.json",
                    "report_path": report_path,
                    "summary_md_path": td_path / "reference-program-compare-nightly-summary.md",
                    "current_mainline_status_path": td_path / "reference-program-compare-current-status.md",
                },
                create=True,
            ):
                payload = loader()

        self.assertTrue(payload["present"])
        self.assertTrue(payload["gate_ok"])
        self.assertEqual(payload["surface_kind"], "reference_program_compare_surface")
        self.assertEqual(payload["freshness_mode"], "reference_program_compare_latest_only")
        self.assertEqual(payload["report_path"], str(report_path))

    def test_run_reference_program_compare_matrix_rolls_up_family_rows(self) -> None:
        run_matrix = getattr(riscv_snn_lab, "run_reference_program_compare_matrix", None)
        self.assertIsNotNone(run_matrix)

        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "reference-program-compare-matrix.json"
            with mock.patch.object(
                riscv_snn_lab,
                "run_reference_program_compare_family",
                side_effect=[
                    {
                        "family": "barrier_wfi_order_ref",
                        "status": "allowed_divergence",
                        "gate_ok": True,
                        "summary_path": str(Path(td) / "barrier_wfi_order_ref-reference-program-compare.json"),
                    },
                    {
                        "family": "external_dyn_desc_fault_rearm_ref",
                        "status": "aligned",
                        "gate_ok": True,
                        "summary_path": str(
                            Path(td) / "external_dyn_desc_fault_rearm_ref-reference-program-compare.json"
                        ),
                    },
                ],
                create=True,
                ) as run_family:
                summary = run_matrix(
                    families=["barrier_wfi_order_ref", "external_dyn_desc_fault_rearm_ref"],
                    summary_path=output_path,
                )
                self.assertEqual(run_family.call_count, 2)
                self.assertEqual(summary["count"], 2)
                self.assertTrue(summary["all_ok"])
                self.assertTrue(output_path.exists())
                self.assertEqual(summary["families"][0]["family"], "barrier_wfi_order_ref")
                self.assertEqual(summary["families"][0]["status"], "allowed_divergence")

    def test_run_reference_program_compare_matrix_accepts_stat_snapshot_family(self) -> None:
        run_matrix = getattr(riscv_snn_lab, "run_reference_program_compare_matrix", None)
        self.assertIsNotNone(run_matrix)

        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "reference-program-compare-matrix.json"
            with mock.patch.object(
                riscv_snn_lab,
                "validate_reference_program_profile_bindings",
                return_value={
                    "all_ok": True,
                    "rows": [{"family": "stat_snapshot_ref"}],
                    "invalid_families": [],
                },
            ):
                with mock.patch.object(
                    riscv_snn_lab,
                    "run_reference_program_compare_family",
                    return_value={
                        "family": "stat_snapshot_ref",
                        "status": "aligned",
                        "gate_ok": True,
                        "summary_path": str(Path(td) / "stat_snapshot_ref-reference-program-compare.json"),
                    },
                    create=True,
                ) as run_family:
                    summary = run_matrix(
                        families=["stat_snapshot_ref"],
                        summary_path=output_path,
                    )

        self.assertEqual(run_family.call_count, 1)
        self.assertEqual(summary["count"], 1)
        self.assertTrue(summary["all_ok"])
        self.assertEqual(summary["families"][0]["family"], "stat_snapshot_ref")

    def test_refresh_reference_program_compare_surface_updates_sidecar_and_runs_derived_refresh(self) -> None:
        refresh_surface = getattr(riscv_snn_lab, "refresh_reference_program_compare_surface", None)
        self.assertIsNotNone(refresh_surface)

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)
            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "supplementary_surfaces": {},
                    }
                ),
                encoding="utf-8",
            )
            stable_paths = {
                "history_path": td_path / "reference-program-compare-history.json",
                "report_path": td_path / "reference-program-compare-nightly-report.json",
                "summary_md_path": td_path / "reference-program-compare-nightly-summary.md",
                "current_mainline_status_path": td_path / "reference-program-compare-current-status.md",
            }

            with mock.patch.object(
                riscv_snn_lab,
                "_reference_program_compare_stable_surface_paths",
                return_value=stable_paths,
                create=True,
            ):
                with mock.patch.object(
                    riscv_snn_lab,
                    "run_reference_program_compare_matrix",
                    return_value={
                        "group": "all",
                        "count": 1,
                        "all_ok": True,
                        "gate_reasons": [],
                        "families": [
                            {
                                "family": "external_dyn_desc_fault_rearm_ref",
                                "status": "aligned",
                                "gate_ok": True,
                                "summary_path": str(
                                    td_path
                                    / "external_dyn_desc_fault_rearm_ref-reference-program-compare.json"
                                ),
                            }
                        ],
                        "summary_path": str(td_path / "reference-program-compare-matrix.json"),
                    },
                    create=True,
                ) as run_matrix:
                    with mock.patch.object(
                        riscv_snn_lab,
                        "_refresh_derived_stable_surfaces",
                        return_value={"summary_md_path": refs_dir / "nightly-sidecar-summary.md"},
                    ) as refresh_derived:
                        summary = refresh_surface(
                            sidecar_path=sidecar_path,
                            lab_root=lab_root,
                        )
                        persisted = json.loads(sidecar_path.read_text(encoding="utf-8"))

                        self.assertEqual(run_matrix.call_args.kwargs["group"], "all")
                        self.assertTrue(refresh_derived.called)
                        self.assertEqual(summary["status"], "pass")
                        self.assertIn("reference_program_compare", persisted["supplementary_surfaces"])
                        self.assertTrue(stable_paths["report_path"].exists())
                        self.assertTrue(stable_paths["history_path"].exists())

    def test_load_reference_compare_supplementary_surface_reads_stable_report(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            report_path = td_path / "reference-compare-nightly-report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "reference_compare_surface_report",
                        "authority_scope": "reference_compare_only",
                        "gate_name": "reference_model_runtime_compare",
                        "gate_version": "1.0",
                        "gate_ok": True,
                        "gate_reasons": [],
                        "history": {
                            "latest_date": "2026-04-10",
                            "stale": False,
                            "freshness_mode": "reference_compare_latest_only",
                            "effective_all_dates_ok": True,
                        },
                        "stable_surfaces": {
                            "report_path": str(report_path),
                            "summary_md_path": str(td_path / "reference-compare-nightly-summary.md"),
                            "current_mainline_status_path": str(td_path / "reference-compare-current-status.md"),
                        },
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(
                riscv_snn_lab,
                "_reference_compare_stable_surface_paths",
                return_value={
                    "history_path": td_path / "reference-compare-history.json",
                    "report_path": report_path,
                    "summary_md_path": td_path / "reference-compare-nightly-summary.md",
                    "current_mainline_status_path": td_path / "reference-compare-current-status.md",
                },
            ):
                payload = riscv_snn_lab._load_reference_compare_supplementary_surface()

        self.assertTrue(payload["present"])
        self.assertTrue(payload["gate_ok"])
        self.assertEqual(payload["surface_kind"], "reference_compare_surface")
        self.assertEqual(payload["freshness_mode"], "reference_compare_latest_only")
        self.assertEqual(payload["report_path"], str(report_path))

    def test_run_reference_compare_matrix_rolls_up_family_rows(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "reference-compare-matrix.json"
            with mock.patch.object(
                riscv_snn_lab,
                "run_reference_compare_family",
                side_effect=[
                    {
                        "family": "external_dyn_desc_ref",
                        "status": "aligned",
                        "gate_ok": True,
                        "summary_path": str(Path(td) / "external_dyn_desc_ref-reference-compare.json"),
                    },
                    {
                        "family": "external_dyn_desc_fault_ref",
                        "status": "allowed_divergence",
                        "gate_ok": True,
                        "summary_path": str(Path(td) / "external_dyn_desc_fault_ref-reference-compare.json"),
                    },
                ],
            ) as run_family:
                summary = riscv_snn_lab.run_reference_compare_matrix(
                    families=["external_dyn_desc_ref", "external_dyn_desc_fault_ref"],
                    summary_path=output_path,
                )
            self.assertEqual(run_family.call_count, 2)
            self.assertEqual(summary["count"], 2)
            self.assertTrue(summary["all_ok"])
            self.assertTrue(output_path.exists())
            self.assertEqual(summary["families"][0]["family"], "external_dyn_desc_ref")
            self.assertEqual(summary["families"][1]["status"], "allowed_divergence")

    def test_refresh_reference_compare_surface_updates_sidecar_and_runs_derived_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)
            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "supplementary_surfaces": {},
                    }
                ),
                encoding="utf-8",
            )
            stable_paths = {
                "history_path": td_path / "reference-compare-history.json",
                "report_path": td_path / "reference-compare-nightly-report.json",
                "summary_md_path": td_path / "reference-compare-nightly-summary.md",
                "current_mainline_status_path": td_path / "reference-compare-current-status.md",
            }

            with mock.patch.object(
                riscv_snn_lab,
                "_reference_compare_stable_surface_paths",
                return_value=stable_paths,
            ):
                with mock.patch.object(
                    riscv_snn_lab,
                    "run_reference_compare_matrix",
                    return_value={
                        "group": "all",
                        "count": 1,
                        "all_ok": True,
                        "gate_reasons": [],
                        "families": [
                            {
                                "family": "external_dyn_desc_ref",
                                "status": "aligned",
                                "gate_ok": True,
                                "summary_path": str(td_path / "external_dyn_desc_ref-reference-compare.json"),
                            }
                        ],
                        "summary_path": str(td_path / "reference-compare-matrix.json"),
                    },
                ) as run_matrix:
                    with mock.patch.object(
                        riscv_snn_lab,
                        "_refresh_derived_stable_surfaces",
                        return_value={"summary_md_path": refs_dir / "nightly-sidecar-summary.md"},
                    ) as refresh_derived:
                        summary = riscv_snn_lab.refresh_reference_compare_surface(
                            sidecar_path=sidecar_path,
                            lab_root=lab_root,
                        )

                persisted = json.loads(sidecar_path.read_text(encoding="utf-8"))

                self.assertEqual(run_matrix.call_args.kwargs["group"], "all")
                self.assertTrue(refresh_derived.called)
                self.assertEqual(summary["status"], "pass")
                self.assertIn("reference_compare", persisted["supplementary_surfaces"])
                self.assertTrue(stable_paths["report_path"].exists())
                self.assertTrue(stable_paths["history_path"].exists())

    def test_refresh_observer_surfaces_refreshes_reference_compare_before_derived_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)
            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(
                riscv_snn_lab,
                "refresh_reference_compare_surface",
                return_value={"report_path": str(td_path / "reference-compare-nightly-report.json")},
            ) as refresh_reference_compare:
                with mock.patch.object(
                    riscv_snn_lab,
                    "_refresh_derived_stable_surfaces",
                    return_value={"observer_summary_path": refs_dir / "nightly-sidecar-observer-summary.json"},
                ):
                    outputs = riscv_snn_lab.refresh_observer_surfaces(
                        sidecar_path=sidecar_path,
                        lab_root=lab_root,
                    )

        self.assertEqual(outputs["observer_summary_path"], refs_dir / "nightly-sidecar-observer-summary.json")
        self.assertEqual(refresh_reference_compare.call_count, 1)
        self.assertFalse(refresh_reference_compare.call_args.kwargs["refresh_derived_surfaces"])

    def test_refresh_observer_surfaces_refreshes_reference_program_compare_before_derived_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)
            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(
                riscv_snn_lab,
                "refresh_reference_compare_surface",
                return_value={"report_path": str(td_path / "reference-compare-nightly-report.json")},
            ):
                with mock.patch.object(
                    riscv_snn_lab,
                    "refresh_reference_program_compare_surface",
                    return_value={
                        "report_path": str(td_path / "reference-program-compare-nightly-report.json")
                    },
                    create=True,
                ) as refresh_reference_program_compare:
                    with mock.patch.object(
                        riscv_snn_lab,
                        "_refresh_derived_stable_surfaces",
                        return_value={"observer_summary_path": refs_dir / "nightly-sidecar-observer-summary.json"},
                    ):
                        outputs = riscv_snn_lab.refresh_observer_surfaces(
                            sidecar_path=sidecar_path,
                            lab_root=lab_root,
                        )

        self.assertEqual(outputs["observer_summary_path"], refs_dir / "nightly-sidecar-observer-summary.json")
        self.assertEqual(refresh_reference_program_compare.call_count, 1)
        self.assertFalse(refresh_reference_program_compare.call_args.kwargs["refresh_derived_surfaces"])

    def test_load_stat_snapshot_family_supplementary_surface_reads_stable_report(self) -> None:
        loader = getattr(riscv_snn_lab, "_load_stat_snapshot_family_supplementary_surface", None)
        self.assertIsNotNone(loader)

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            report_path = td_path / "stat-snapshot-family-nightly-report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stat_snapshot_family_surface_report",
                        "authority_scope": "stat_snapshot_family_only",
                        "gate_name": "stat_snapshot_reference_coverage",
                        "gate_version": "1.0",
                        "gate_ok": False,
                        "gate_reasons": ["selector:CompletedCommands missing reference assets"],
                        "history": {
                            "latest_date": "2026-04-16",
                            "stale": False,
                            "freshness_mode": "latest_refresh_only",
                            "effective_all_dates_ok": False,
                        },
                        "selector_count": 3,
                        "covered_selector_count": 1,
                        "selector_rows": [
                            {
                                "selector_name": "AcceptedCommands",
                                "selector_value": 0,
                                "reference_ready": True,
                            },
                            {
                                "selector_name": "CompletedCommands",
                                "selector_value": 1,
                                "reference_ready": False,
                            },
                            {
                                "selector_name": "ProviderBound",
                                "selector_value": 2,
                                "reference_ready": False,
                            },
                        ],
                        "stable_surfaces": {
                            "report_path": str(report_path),
                            "summary_md_path": str(td_path / "stat-snapshot-family-nightly-summary.md"),
                            "current_mainline_status_path": str(td_path / "stat-snapshot-family-current-status.md"),
                        },
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(
                riscv_snn_lab,
                "_stat_snapshot_family_stable_surface_paths",
                return_value={
                    "history_path": td_path / "stat-snapshot-family-history.json",
                    "report_path": report_path,
                    "summary_md_path": td_path / "stat-snapshot-family-nightly-summary.md",
                    "current_mainline_status_path": td_path / "stat-snapshot-family-current-status.md",
                    "observer_summary_path": td_path / "nightly-sidecar-observer-summary.json",
                },
                create=True,
            ):
                payload = loader(lab_root=td_path)

        self.assertTrue(payload["present"])
        self.assertFalse(payload["gate_ok"])
        self.assertEqual(payload["surface_kind"], "stat_snapshot_family_surface")
        self.assertEqual(payload["selector_count"], 3)
        self.assertEqual(payload["covered_selector_count"], 1)
        self.assertEqual(payload["selector_rows"][0]["selector_name"], "AcceptedCommands")

    def test_refresh_stat_snapshot_family_surface_updates_sidecar_and_runs_derived_refresh(self) -> None:
        refresh_surface = getattr(riscv_snn_lab, "refresh_stat_snapshot_family_surface", None)
        self.assertIsNotNone(refresh_surface)

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            specs_dir = lab_root / "specs"
            firmware_dir = lab_root / "firmware"
            firmware_src_dir = lab_root / "firmware_src"
            refs_dir.mkdir(parents=True, exist_ok=True)
            specs_dir.mkdir(parents=True, exist_ok=True)
            firmware_dir.mkdir(parents=True, exist_ok=True)
            firmware_src_dir.mkdir(parents=True, exist_ok=True)
            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "supplementary_surfaces": {},
                    }
                ),
                encoding="utf-8",
            )

            def write_stat_snapshot_family(base_program: str) -> None:
                runtime_elf = firmware_dir / f"{base_program}.elf"
                runtime_elf.write_bytes(b"runtime-elf")
                runtime_spec = specs_dir / f"{base_program}.json"
                runtime_bridge_spec = specs_dir / f"{base_program}_runtime_bridge.json"
                toolchain_program = f"{base_program}_toolchain"
                toolchain_elf = firmware_dir / f"{toolchain_program}.elf"
                toolchain_elf.write_bytes(b"toolchain-elf")
                toolchain_spec = specs_dir / f"{toolchain_program}.json"
                toolchain_dir = firmware_src_dir / toolchain_program
                toolchain_dir.mkdir(parents=True, exist_ok=True)
                (toolchain_dir / "Makefile").write_text("all:\n\t@true\n", encoding="utf-8")

                for spec_path, firmware_path in (
                    (runtime_spec, runtime_elf),
                    (runtime_bridge_spec, runtime_elf),
                    (toolchain_spec, toolchain_elf),
                ):
                    spec_path.write_text(
                        json.dumps(
                            {
                                "schema_version": 3,
                                "platform": {"mesh_size": 4, "exec_mode": "gas"},
                                "workload": {
                                    "impl": "riscv_snn",
                                    "params": {
                                        "backend_name": "runtime_bridge",
                                        "firmware_elf": str(firmware_path),
                                    },
                                },
                            }
                        ),
                        encoding="utf-8",
                    )

            for base_program in (
                "stat_snapshot_ref",
                "stat_snapshot_completed_ref",
                "stat_snapshot_provider_bound_ref",
            ):
                write_stat_snapshot_family(base_program)

            stable_paths = {
                "history_path": refs_dir / "stat-snapshot-family-history.json",
                "report_path": refs_dir / "stat-snapshot-family-nightly-report.json",
                "summary_md_path": refs_dir / "stat-snapshot-family-nightly-summary.md",
                "current_mainline_status_path": refs_dir / "stat-snapshot-family-current-status.md",
                "observer_summary_path": refs_dir / "nightly-sidecar-observer-summary.json",
            }

            with mock.patch.object(
                riscv_snn_lab,
                "_stat_snapshot_family_stable_surface_paths",
                return_value=stable_paths,
                create=True,
            ):
                with mock.patch.object(
                    riscv_snn_lab,
                    "validate_program",
                    return_value=subprocess.CompletedProcess(["validate"], 0, stdout="OK\n", stderr=""),
                ) as validate_program:
                    with mock.patch.object(
                        riscv_snn_lab,
                        "_refresh_derived_stable_surfaces",
                        return_value={"summary_md_path": refs_dir / "nightly-sidecar-summary.md"},
                    ) as refresh_derived:
                        summary = refresh_surface(
                            sidecar_path=sidecar_path,
                            lab_root=lab_root,
                        )

            persisted = json.loads(sidecar_path.read_text(encoding="utf-8"))
            self.assertTrue(stable_paths["report_path"].exists())
            self.assertTrue(stable_paths["history_path"].exists())

        self.assertEqual(validate_program.call_count, 9)
        self.assertTrue(refresh_derived.called)
        self.assertEqual(summary["status"], "pass")
        self.assertTrue(summary["gate_ok"])
        self.assertEqual(summary["selector_count"], 3)
        self.assertEqual(summary["covered_selector_count"], 3)
        self.assertEqual(len(summary["selector_rows"]), 3)
        self.assertIn("stat_snapshot_family", persisted["supplementary_surfaces"])

    def test_refresh_stat_snapshot_family_surface_records_missing_selectors_nonblocking(self) -> None:
        refresh_surface = getattr(riscv_snn_lab, "refresh_stat_snapshot_family_surface", None)
        self.assertIsNotNone(refresh_surface)

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            specs_dir = lab_root / "specs"
            firmware_dir = lab_root / "firmware"
            firmware_src_dir = lab_root / "firmware_src"
            refs_dir.mkdir(parents=True, exist_ok=True)
            specs_dir.mkdir(parents=True, exist_ok=True)
            firmware_dir.mkdir(parents=True, exist_ok=True)
            firmware_src_dir.mkdir(parents=True, exist_ok=True)
            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "supplementary_surfaces": {},
                    }
                ),
                encoding="utf-8",
            )

            runtime_elf = firmware_dir / "stat_snapshot_ref.elf"
            runtime_elf.write_bytes(b"runtime-elf")
            toolchain_elf = firmware_dir / "stat_snapshot_ref_toolchain.elf"
            toolchain_elf.write_bytes(b"toolchain-elf")
            (firmware_src_dir / "stat_snapshot_ref_toolchain").mkdir(parents=True, exist_ok=True)
            for spec_name, firmware_path in (
                ("stat_snapshot_ref.json", runtime_elf),
                ("stat_snapshot_ref_runtime_bridge.json", runtime_elf),
                ("stat_snapshot_ref_toolchain.json", toolchain_elf),
            ):
                (specs_dir / spec_name).write_text(
                    json.dumps(
                        {
                            "schema_version": 3,
                            "platform": {"mesh_size": 4, "exec_mode": "gas"},
                            "workload": {
                                "impl": "riscv_snn",
                                "params": {
                                    "backend_name": "runtime_bridge",
                                    "firmware_elf": str(firmware_path),
                                },
                            },
                        }
                    ),
                    encoding="utf-8",
                )

            stable_paths = {
                "history_path": refs_dir / "stat-snapshot-family-history.json",
                "report_path": refs_dir / "stat-snapshot-family-nightly-report.json",
                "summary_md_path": refs_dir / "stat-snapshot-family-nightly-summary.md",
                "current_mainline_status_path": refs_dir / "stat-snapshot-family-current-status.md",
                "observer_summary_path": refs_dir / "nightly-sidecar-observer-summary.json",
            }
            with mock.patch.object(
                riscv_snn_lab,
                "_stat_snapshot_family_stable_surface_paths",
                return_value=stable_paths,
                create=True,
            ):
                with mock.patch.object(
                    riscv_snn_lab,
                    "validate_program",
                    return_value=subprocess.CompletedProcess(["validate"], 0, stdout="OK\n", stderr=""),
                ):
                    summary = refresh_surface(
                        sidecar_path=sidecar_path,
                        lab_root=lab_root,
                        refresh_derived_surfaces=False,
                    )

        selector_rows = {row["selector_name"]: row for row in summary["selector_rows"]}
        self.assertEqual(summary["status"], "degraded")
        self.assertFalse(summary["gate_ok"])
        self.assertEqual(summary["selector_count"], 3)
        self.assertEqual(summary["covered_selector_count"], 1)
        self.assertTrue(selector_rows["AcceptedCommands"]["reference_ready"])
        self.assertFalse(selector_rows["CompletedCommands"]["reference_ready"])
        self.assertFalse(selector_rows["ProviderBound"]["reference_ready"])
        self.assertTrue(any("CompletedCommands" in reason for reason in summary["gate_reasons"]))
        self.assertTrue(any("ProviderBound" in reason for reason in summary["gate_reasons"]))

    def test_refresh_observer_surfaces_refreshes_stat_snapshot_family_before_derived_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)
            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(
                riscv_snn_lab,
                "refresh_stat_snapshot_family_surface",
                return_value={"report_path": str(td_path / "stat-snapshot-family-nightly-report.json")},
                create=True,
            ) as refresh_stat_snapshot_family:
                with mock.patch.object(
                    riscv_snn_lab,
                    "refresh_reference_compare_surface",
                    return_value={"report_path": str(td_path / "reference-compare-nightly-report.json")},
                ):
                    with mock.patch.object(
                        riscv_snn_lab,
                        "refresh_reference_program_compare_surface",
                        return_value={
                            "report_path": str(td_path / "reference-program-compare-nightly-report.json")
                        },
                        create=True,
                    ):
                        with mock.patch.object(
                            riscv_snn_lab,
                            "_refresh_derived_stable_surfaces",
                            return_value={"observer_summary_path": refs_dir / "nightly-sidecar-observer-summary.json"},
                        ):
                            outputs = riscv_snn_lab.refresh_observer_surfaces(
                                sidecar_path=sidecar_path,
                                lab_root=lab_root,
                            )

        self.assertEqual(outputs["observer_summary_path"], refs_dir / "nightly-sidecar-observer-summary.json")
        self.assertEqual(refresh_stat_snapshot_family.call_count, 1)
        self.assertFalse(refresh_stat_snapshot_family.call_args.kwargs["refresh_derived_surfaces"])

    def test_load_supplementary_surface_authority_prefers_lab_override(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            spec_dir = td_path / "spec_authority"
            spec_dir.mkdir(parents=True, exist_ok=True)
            (spec_dir / "riscv_snn_supplementary_surface_v1.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "contract_name": "riscv_snn_supplementary_surface",
                        "contract_version": "9.9-test",
                        "history_contract": "supplementary_surface_observer_v1",
                        "surfaces": {
                            "compare": {
                                "surface_kind": "compare_exec_mode_smoke_override",
                                "blocking": True,
                                "required_surface_fields": [],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            authority = riscv_snn_lab.load_supplementary_surface_authority(lab_root=td_path)

        self.assertEqual(authority["contract_version"], "9.9-test")
        self.assertEqual(authority["surfaces"]["compare"]["surface_kind"], "compare_exec_mode_smoke_override")
        self.assertTrue(authority["surfaces"]["compare"]["blocking"])

    def test_supplementary_surface_contract_builds_latest_only_history_payload(self) -> None:
        history = supplementary_surface_contract.build_latest_only_history_payload(
            history_contract="reference_program_compare_source_history_passthrough_v1",
            history_path="/tmp/reference-program-compare-history.json",
            latest_date="2026-04-18",
            gate_ok=True,
            freshness_mode="reference_program_compare_latest_only",
            entry_payload={
                "date": "2026-04-18",
                "group": "all",
                "count": 12,
                "all_ok": True,
            },
        )

        self.assertEqual(
            history["history_contract"],
            "reference_program_compare_source_history_passthrough_v1",
        )
        self.assertEqual(history["path"], "/tmp/reference-program-compare-history.json")
        self.assertEqual(history["latest_date"], "2026-04-18")
        self.assertEqual(history["entry_count"], 1)
        self.assertEqual(history["effective_entry_count"], 1)
        self.assertTrue(history["all_ok_latest"])
        self.assertTrue(history["all_dates_ok"])
        self.assertEqual(history["latest_recovered_date"], "2026-04-18")
        self.assertEqual(history["freshness_mode"], "reference_program_compare_latest_only")
        self.assertTrue(history["effective_all_dates_ok"])
        self.assertEqual(history["entries"][0]["group"], "all")

    def test_supplementary_surface_contract_projects_surface_payload_from_report(self) -> None:
        default_payload = {
            "surface_kind": "reference_program_compare_surface",
            "blocking": False,
            "present": False,
            "load_error": None,
            "report_path": "/tmp/default-report.json",
            "summary_md_path": "/tmp/default-summary.md",
            "current_mainline_status_path": "/tmp/default-current.md",
            "artifact_role": None,
            "authority_scope": None,
            "gate_name": None,
            "gate_version": None,
            "gate_ok": None,
            "gate_reasons": [],
            "latest_date": None,
            "stale": None,
            "freshness_mode": None,
            "effective_all_dates_ok": None,
            "selector_rows": [],
        }
        report = {
            "artifact_role": "reference_program_compare_surface_report",
            "authority_scope": "reference_program_compare_only",
            "gate_name": "reference_program_model_runtime_compare",
            "gate_version": "1.0",
            "gate_ok": True,
            "gate_reasons": ["runtime.ok"],
            "selector_rows": [{"selector_name": "AcceptedCommands", "reference_ready": True}],
            "stable_surfaces": {
                "report_path": "/tmp/report.json",
                "summary_md_path": "/tmp/summary.md",
                "current_mainline_status_path": "/tmp/current.md",
            },
            "history": {
                "latest_date": "2026-04-18",
                "stale": False,
                "freshness_mode": "latest_refresh_only",
                "effective_all_dates_ok": True,
            },
        }

        payload = supplementary_surface_contract.project_surface_payload_from_report(
            default_payload=default_payload,
            report=report,
            stable_surface_fields=("report_path", "summary_md_path", "current_mainline_status_path"),
            history_fields=("latest_date", "stale", "freshness_mode", "effective_all_dates_ok"),
            report_fields=("artifact_role", "authority_scope", "gate_name", "gate_version", "gate_ok", "selector_rows"),
            list_report_fields=("gate_reasons", "selector_rows"),
        )

        self.assertTrue(payload["present"])
        self.assertEqual(payload["report_path"], "/tmp/report.json")
        self.assertEqual(payload["summary_md_path"], "/tmp/summary.md")
        self.assertEqual(payload["current_mainline_status_path"], "/tmp/current.md")
        self.assertEqual(payload["artifact_role"], "reference_program_compare_surface_report")
        self.assertTrue(payload["gate_ok"])
        self.assertEqual(payload["gate_reasons"], ["runtime.ok"])
        self.assertEqual(payload["latest_date"], "2026-04-18")
        self.assertEqual(payload["freshness_mode"], "latest_refresh_only")
        self.assertTrue(payload["effective_all_dates_ok"])
        self.assertEqual(payload["selector_rows"][0]["selector_name"], "AcceptedCommands")

    def test_supplementary_surface_contract_builds_attachment_and_merges_sidecar(self) -> None:
        surface_payload = supplementary_surface_contract.build_surface_attachment(
            authority_surface={
                "surface_kind": "stat_snapshot_family_surface",
                "blocking": False,
            },
            stable_surfaces={
                "report_path": "/tmp/stat-report.json",
                "summary_md_path": "/tmp/stat-summary.md",
                "current_mainline_status_path": "/tmp/stat-current.md",
                "observer_summary_path": "/tmp/stat-observer.json",
            },
            report_payload={
                "artifact_role": "stat_snapshot_family_surface_report",
                "authority_scope": "stat_snapshot_family_only",
                "gate_name": "stat_snapshot_reference_coverage",
                "gate_version": "1.0",
                "gate_ok": True,
                "gate_reasons": [],
            },
            history_payload={
                "latest_date": "2026-04-18",
                "stale": False,
                "freshness_mode": "latest_refresh_only",
                "effective_all_dates_ok": True,
            },
            extra_fields={
                "selector_count": 3,
                "covered_selector_count": 3,
            },
        )
        merged = supplementary_surface_contract.merge_supplementary_surface(
            sidecar_report={
                "artifact_role": "stable_top_level_gate",
                "supplementary_surfaces": {
                    "compare": {
                        "surface_kind": "compare_exec_mode_smoke",
                        "present": True,
                    }
                },
            },
            name="stat_snapshot_family",
            surface_payload=surface_payload,
        )

        self.assertEqual(surface_payload["surface_kind"], "stat_snapshot_family_surface")
        self.assertEqual(surface_payload["observer_summary_path"], "/tmp/stat-observer.json")
        self.assertEqual(surface_payload["selector_count"], 3)
        self.assertEqual(
            merged["supplementary_surfaces"]["compare"]["surface_kind"],
            "compare_exec_mode_smoke",
        )
        self.assertEqual(
            merged["supplementary_surfaces"]["stat_snapshot_family"]["covered_selector_count"],
            3,
        )

    def test_supplementary_surface_contract_renders_summary_markdown_with_extra_lines(self) -> None:
        rendered = supplementary_surface_contract.render_surface_summary_markdown(
            title="reference_program_compare nightly summary",
            generated_utc="2026-04-18T00:00:00+00:00",
            fields=[
                ("status", "pass"),
                ("gate_ok", True),
                ("count", 12),
            ],
            extra_lines=[
                "- `selector.AcceptedCommands.reference_ready = True`",
            ],
        )

        self.assertIn("# reference_program_compare nightly summary", rendered)
        self.assertIn("- Generated UTC: `2026-04-18T00:00:00+00:00`", rendered)
        self.assertIn("- `status = pass`", rendered)
        self.assertIn("- `gate_ok = True`", rendered)
        self.assertIn("- `count = 12`", rendered)
        self.assertIn("- `selector.AcceptedCommands.reference_ready = True`", rendered)

    def test_supplementary_surface_contract_renders_current_status_markdown_with_sections(self) -> None:
        rendered = supplementary_surface_contract.render_surface_current_status_markdown(
            title="reference_compare current status",
            generated_utc="2026-04-18T00:00:00+00:00",
            role="non-blocking reference-model/runtime supplementary surface",
            fields=[
                ("status", "allowed_divergence"),
                ("gate_ok", True),
            ],
            sections=[
                (
                    "Alignment",
                    [
                        ("terminal_state_match", True),
                        ("invalid_divergence_points", ["none"]),
                    ],
                ),
            ],
            extra_lines=[
                "- `report_path = /tmp/reference-compare.json`",
            ],
        )

        self.assertIn("# reference_compare current status", rendered)
        self.assertIn("- Generated UTC: `2026-04-18T00:00:00+00:00`", rendered)
        self.assertIn("- Role: non-blocking reference-model/runtime supplementary surface", rendered)
        self.assertIn("- `status = allowed_divergence`", rendered)
        self.assertIn("- `gate_ok = True`", rendered)
        self.assertIn("## Alignment", rendered)
        self.assertIn("- `terminal_state_match = True`", rendered)
        self.assertIn("- `invalid_divergence_points = none`", rendered)
        self.assertIn("- `report_path = /tmp/reference-compare.json`", rendered)

    def test_supplementary_surface_authority_declares_reference_program_compare(self) -> None:
        authority = riscv_snn_lab.load_supplementary_surface_authority()
        self.assertIn("reference_program_compare", authority["surfaces"])
        self.assertEqual(
            authority["surfaces"]["reference_program_compare"]["surface_kind"],
            "reference_program_compare_surface",
        )
        self.assertIn("stat_snapshot_family", authority["surfaces"])
        self.assertEqual(
            authority["surfaces"]["stat_snapshot_family"]["surface_kind"],
            "stat_snapshot_family_surface",
        )

    def test_control_plane_contract_renderer_exports_doorbell_completion_and_fault_sections(self) -> None:
        authority = json.loads(
            (riscv_snn_lab.LAB_ROOT / "spec_authority" / "riscv_snn_accel_v1.json").read_text(encoding="utf-8")
        )
        text = riscv_snn_lab.render_control_plane_contract_markdown(authority)
        self.assertIn("Doorbell", text)
        self.assertIn("Accepted", text)
        self.assertIn("Completion Visibility", text)
        self.assertIn("Fault Clear And Overwrite", text)

    def test_control_plane_contract_renderer_uses_machine_readable_authority_keys(self) -> None:
        authority = json.loads(
            (riscv_snn_lab.LAB_ROOT / "spec_authority" / "riscv_snn_accel_v1.json").read_text(encoding="utf-8")
        )
        self.assertIn("doorbell_rules", authority)
        self.assertIn("ownership_rules", authority)
        self.assertIn("fault_semantics", authority)
        normalized = riscv_snn_lab.export_control_plane_contract_payload(authority)
        self.assertEqual(normalized["doorbell_rules"], authority["doorbell_rules"])
        self.assertEqual(normalized["ownership_rules"], authority["ownership_rules"])
        self.assertEqual(normalized["fault_semantics"], authority["fault_semantics"])

    def test_family_admission_audit_reports_queue_optional_as_nonblocking(self) -> None:
        summary = riscv_snn_lab.run_family_admission_audit(group="queue_optional")
        self.assertEqual(summary["group"], "queue_optional")
        self.assertEqual(summary["blocking"], False)
        self.assertIn("promotion_ready", summary)
        self.assertIn("required_contracts", summary)
        self.assertEqual(
            summary["families"],
            [
                "completion_queue_overflow_ref",
                "queue_backpressure_ref",
            ],
        )

    def test_audit_family_assets_reports_complete_family_triplet(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            specs_dir = lab_root / "specs"
            toolchain_dir = lab_root / "firmware_src" / "barrier_wfi_order_ref_toolchain"
            firmware_dir = lab_root / "firmware"
            spec_authority_dir = lab_root / "spec_authority"
            refs_dir.mkdir(parents=True, exist_ok=True)
            specs_dir.mkdir(parents=True, exist_ok=True)
            toolchain_dir.mkdir(parents=True, exist_ok=True)
            firmware_dir.mkdir(parents=True, exist_ok=True)
            spec_authority_dir.mkdir(parents=True, exist_ok=True)

            (spec_authority_dir / "riscv_snn_runtime_gate_v1.json").write_text(
                json.dumps(
                    {
                        "families": {
                            "barrier_wfi_order_ref": {
                                "fault_mode": "quiescent"
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            (specs_dir / "barrier_wfi_order_ref_snn_baseline.json").write_text(
                json.dumps(
                    {
                        "workload": {
                            "impl": "snn",
                            "params": {},
                        }
                    }
                ),
                encoding="utf-8",
            )
            (specs_dir / "barrier_wfi_order_ref_runtime_bridge.json").write_text(
                json.dumps(
                    {
                        "workload": {
                            "impl": "riscv_snn",
                            "params": {
                                "backend_name": "runtime_bridge",
                                "firmware_elf": str(firmware_dir / "barrier_wfi_order_ref_toolchain.elf"),
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            for filename in ("Makefile", "main.S", "abi.inc", "crt0.S", "linker.ld"):
                (toolchain_dir / filename).write_text("placeholder\n", encoding="utf-8")

            with mock.patch.object(
                riscv_snn_lab,
                "_load_program_manifest",
                return_value={
                    "samples": {
                        "barrier_wfi_order_ref": {
                            "canonical_sample": False,
                            "description": "barrier reference",
                        }
                    }
                },
            ):
                summary = riscv_snn_lab.audit_family_assets(
                    families=["barrier_wfi_order_ref"],
                    lab_root=lab_root,
                )

        self.assertTrue(summary["all_ok"])
        self.assertEqual(summary["count"], 1)
        row = summary["families"][0]
        self.assertEqual(row["family"], "barrier_wfi_order_ref")
        self.assertTrue(row["builder_sample_present"])
        self.assertTrue(row["toolchain_assets_ok"])
        self.assertTrue(row["baseline_spec_ok"])
        self.assertTrue(row["runtime_bridge_spec_ok"])
        self.assertEqual(row["builder_program"], "barrier_wfi_order_ref")
        self.assertEqual(row["toolchain_program"], "barrier_wfi_order_ref_toolchain")

    def test_run_family_lane_clones_and_patches_specs_before_equivalence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            specs_dir = lab_root / "specs"
            refs_dir.mkdir(parents=True, exist_ok=True)
            specs_dir.mkdir(parents=True, exist_ok=True)

            (specs_dir / "barrier_wfi_order_ref_snn_baseline.json").write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "platform": {
                            "mesh_size": 4,
                            "stop": {
                                "simulation_time": "1us",
                            },
                        },
                        "workload": {
                            "impl": "snn",
                            "params": {},
                        },
                    }
                ),
                encoding="utf-8",
            )
            (specs_dir / "barrier_wfi_order_ref_runtime_bridge.json").write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "platform": {
                            "mesh_size": 4,
                            "stop": {
                                "simulation_time": "1us",
                            },
                        },
                        "workload": {
                            "impl": "riscv_snn",
                            "params": {
                                "hart_isa": "rv64im_zicsr",
                                "local_mem_bytes": 65536,
                                "cmd_queue_entries": 64,
                                "cmp_queue_entries": 64,
                                "rx_debug_queue_entries": 16,
                                "boot_addr": 0,
                                "backend_name": "runtime_bridge",
                                "firmware_elf": "/tmp/fw.elf",
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            equiv_summary_path = refs_dir / "lane-equivalence.json"
            with mock.patch.object(
                riscv_snn_lab,
                "_run_equivalence_with_spec_paths",
                return_value={
                    "family": "barrier_wfi_order_ref",
                    "status": "PASS",
                    "gate_reasons": [],
                    "summary_path": str(equiv_summary_path),
                },
            ) as run_equiv:
                summary = riscv_snn_lab.run_family_lane(
                    family="barrier_wfi_order_ref",
                    sim_time="2us",
                    mesh_size=8,
                    cmd_queue_entries=2,
                    cmp_queue_entries=1,
                    lab_root=lab_root,
                )

            baseline_clone = Path(summary["baseline_spec_path"])
            runtime_clone = Path(summary["runtime_bridge_spec_path"])
            baseline_payload = json.loads(baseline_clone.read_text(encoding="utf-8"))
            runtime_payload = json.loads(runtime_clone.read_text(encoding="utf-8"))

        self.assertFalse(summary["canonical_surface"])
        self.assertEqual(summary["family"], "barrier_wfi_order_ref")
        self.assertEqual(summary["equivalence_summary_path"], str(equiv_summary_path))
        self.assertEqual(summary["overrides"]["sim_time"], "2us")
        self.assertEqual(summary["overrides"]["mesh_size"], 8)
        self.assertEqual(summary["overrides"]["cmd_queue_entries"], 2)
        self.assertEqual(summary["overrides"]["cmp_queue_entries"], 1)
        self.assertEqual(
            run_equiv.call_args.kwargs["baseline_spec"],
            baseline_clone,
        )
        self.assertEqual(
            run_equiv.call_args.kwargs["runtime_bridge_spec"],
            runtime_clone,
        )
        self.assertEqual(
            baseline_payload["platform"]["stop"]["simulation_time"],
            "2us",
        )
        self.assertEqual(baseline_payload["platform"]["mesh_size"], 8)
        self.assertEqual(runtime_payload["platform"]["mesh_size"], 8)
        self.assertEqual(runtime_payload["workload"]["params"]["cmd_queue_entries"], 2)
        self.assertEqual(runtime_payload["workload"]["params"]["cmp_queue_entries"], 1)

    def test_list_calls_generator_json_manifest(self) -> None:
        runner = FakeRunner()
        proc = riscv_snn_lab.list_programs(runner=runner, as_json=True)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(len(runner.calls), 1)
        self.assertIn("--list-programs", runner.calls[0][0])
        self.assertIn("--json", runner.calls[0][0])

    def test_generate_uses_lab_local_default_paths(self) -> None:
        runner = FakeRunner()
        elf_path, spec_path = riscv_snn_lab.generate_program("external_dyn_desc_ref", runner=runner)
        self.assertTrue(str(elf_path).endswith("/riscv_snn_isa_lab/firmware/external_dyn_desc_ref.elf"))
        self.assertTrue(str(spec_path).endswith("/riscv_snn_isa_lab/specs/external_dyn_desc_ref.json"))
        self.assertEqual(len(runner.calls), 1)
        self.assertIn("--program", runner.calls[0][0])
        self.assertIn("external_dyn_desc_ref", runner.calls[0][0])

    def test_generate_builder_program_reuses_checked_in_spec_shape(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            firmware_dir = lab_root / "firmware"
            specs_dir = lab_root / "specs"
            firmware_dir.mkdir(parents=True)
            specs_dir.mkdir(parents=True)
            checked_in_spec = specs_dir / "queue_backpressure_ref.json"
            checked_in_spec.write_text(
                json.dumps(
                    {
                        "platform": {
                            "mesh_size": 8,
                            "stop": {
                                "simulation_time": "2us",
                            },
                        },
                        "workload": {
                            "params": {
                                "hart_isa": "rv64im_zicsr",
                                "local_mem_bytes": 131072,
                                "cmd_queue_entries": 1,
                                "cmp_queue_entries": 8,
                                "rx_debug_queue_entries": 32,
                                "boot_addr": 4096,
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            runner = FakeRunner()
            elf_path, spec_path = riscv_snn_lab.generate_program(
                "queue_backpressure_ref",
                lab_root=lab_root,
                runner=runner,
            )

        self.assertEqual(elf_path, firmware_dir / "queue_backpressure_ref.elf")
        self.assertEqual(spec_path, checked_in_spec)
        self.assertEqual(len(runner.calls), 1)
        cmd = runner.calls[0][0]
        self.assertIn("--sim-time", cmd)
        self.assertEqual(cmd[cmd.index("--sim-time") + 1], "2us")
        self.assertIn("--mesh-size", cmd)
        self.assertEqual(cmd[cmd.index("--mesh-size") + 1], "8")
        self.assertIn("--local-mem-bytes", cmd)
        self.assertEqual(cmd[cmd.index("--local-mem-bytes") + 1], "131072")
        self.assertIn("--cmd-queue-entries", cmd)
        self.assertEqual(cmd[cmd.index("--cmd-queue-entries") + 1], "1")
        self.assertIn("--cmp-queue-entries", cmd)
        self.assertEqual(cmd[cmd.index("--cmp-queue-entries") + 1], "8")
        self.assertIn("--rx-debug-queue-entries", cmd)
        self.assertEqual(cmd[cmd.index("--rx-debug-queue-entries") + 1], "32")
        self.assertIn("--boot-addr", cmd)
        self.assertEqual(cmd[cmd.index("--boot-addr") + 1], "4096")

    def test_generate_toolchain_program_runs_make_in_toolchain_dir(self) -> None:
        runner = FakeRunner()
        elf_path, spec_path = riscv_snn_lab.generate_program(
            "external_dyn_desc_fault_rearm_ref_toolchain",
            runner=runner,
        )
        self.assertTrue(
            str(elf_path).endswith(
                "/riscv_snn_isa_lab/firmware/external_dyn_desc_fault_rearm_ref_toolchain.elf"
            )
        )
        self.assertTrue(
            str(spec_path).endswith(
                "/riscv_snn_isa_lab/specs/external_dyn_desc_fault_rearm_ref_toolchain.json"
            )
        )
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(runner.calls[0][0], ["make"])
        self.assertTrue(
            runner.calls[0][1].endswith(
                "/riscv_snn_isa_lab/firmware_src/external_dyn_desc_fault_rearm_ref_toolchain"
            )
        )

    def test_validate_resolves_program_to_lab_spec(self) -> None:
        runner = FakeRunner()
        proc = riscv_snn_lab.validate_program(program="external_dyn_desc_ref", runner=runner)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(len(runner.calls), 1)
        self.assertTrue(runner.calls[0][0][-1].endswith("/riscv_snn_isa_lab/specs/external_dyn_desc_ref.json"))

    def test_validate_toolchain_program_builds_then_validates(self) -> None:
        runner = FakeRunner()
        proc = riscv_snn_lab.validate_program(
            program="external_dyn_desc_fault_rearm_ref_toolchain",
            runner=runner,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(len(runner.calls), 2)
        self.assertEqual(runner.calls[0][0], ["make"])
        self.assertTrue(
            runner.calls[0][1].endswith(
                "/riscv_snn_isa_lab/firmware_src/external_dyn_desc_fault_rearm_ref_toolchain"
            )
        )
        self.assertEqual(runner.calls[1][0][0:3], ["python3", str(riscv_snn_lab.SPEC_CLI), "validate"])
        self.assertTrue(
            runner.calls[1][0][-1].endswith(
                "/riscv_snn_isa_lab/specs/external_dyn_desc_fault_rearm_ref_toolchain.json"
            )
        )

    def test_smoke_chains_generate_validate_and_run(self) -> None:
        runner = FakeRunner()
        with mock.patch.object(
            riscv_snn_lab,
            "ensure_runtime_bridge_build_guard",
            return_value=self._runtime_bridge_build_guard_ok_summary(),
        ) as build_guard, mock.patch.object(
            riscv_snn_lab,
            "ensure_parallel_sst_preflight",
            return_value={"status": "ok", "reason_ids": []},
        ) as parallel_preflight:
            run_dir = riscv_snn_lab.smoke_program("external_dyn_desc_ref", runner=runner)
        self.assertEqual(run_dir, Path("/tmp/fake-run"))
        self.assertEqual(len(runner.calls), 3)
        self.assertIn("--program", runner.calls[0][0])
        self.assertIn("validate", runner.calls[1][0])
        self.assertTrue(any(str(part).endswith("run_mesh_with_time.sh") for part in runner.calls[2][0]))
        build_guard.assert_called_once()
        parallel_preflight.assert_called_once()

    def test_smoke_toolchain_program_builds_then_validates_and_runs(self) -> None:
        runner = FakeRunner()
        with mock.patch.object(
            riscv_snn_lab,
            "ensure_runtime_bridge_build_guard",
            return_value=self._runtime_bridge_build_guard_ok_summary(),
        ) as build_guard, mock.patch.object(
            riscv_snn_lab,
            "ensure_parallel_sst_preflight",
            return_value={"status": "ok", "reason_ids": []},
        ) as parallel_preflight:
            run_dir = riscv_snn_lab.smoke_program(
                "external_dyn_desc_fault_rearm_ref_toolchain",
                runner=runner,
            )
        self.assertEqual(run_dir, Path("/tmp/fake-run"))
        self.assertEqual(len(runner.calls), 3)
        self.assertEqual(runner.calls[0][0], ["make"])
        self.assertTrue(
            runner.calls[0][1].endswith(
                "/riscv_snn_isa_lab/firmware_src/external_dyn_desc_fault_rearm_ref_toolchain"
            )
        )
        self.assertEqual(runner.calls[1][0][0:3], ["python3", str(riscv_snn_lab.SPEC_CLI), "validate"])
        self.assertTrue(any(str(part).endswith("run_mesh_with_time.sh") for part in runner.calls[2][0]))
        build_guard.assert_called_once()
        parallel_preflight.assert_called_once()

    def test_runtime_bridge_build_guard_skips_when_build_tree_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lab_root = Path(td) / "riscv_snn_isa_lab"
            spec_path = self._write_runtime_bridge_spec(lab_root)

            summary = riscv_snn_lab.runtime_bridge_build_guard(spec_path=spec_path, lab_root=lab_root)

        self.assertTrue(summary["enabled"])
        self.assertEqual(summary["status"], "skipped")
        self.assertEqual(summary["contract_key"], "riscv_snn.runtime_bridge.runtime_consumers")
        self.assertEqual(summary["contract_version"], 1)
        self.assertIn("WeightMemorySubsystem.h", "\n".join(summary["dependency_paths"]))
        self.assertIn("libSnnDL.so", "\n".join(summary["required_target_paths"]))
        self.assertEqual(summary["stale_targets"], [])
        self.assertEqual(summary["missing_targets"], [])
        self.assertTrue(summary["snndl_root"].endswith("/sst_workspace/sst-elements/src/sst/elements/SnnDL"))

    def test_runtime_bridge_build_guard_non_runtime_bridge_spec_has_no_contract_surface(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lab_root = Path(td) / "riscv_snn_isa_lab"
            spec_path = self._write_baseline_snn_spec(lab_root)

            summary = riscv_snn_lab.runtime_bridge_build_guard(spec_path=spec_path, lab_root=lab_root)

        self.assertFalse(summary["enabled"])
        self.assertEqual(summary["status"], "skipped")
        self.assertIsNone(summary["contract_key"])
        self.assertIsNone(summary["contract_version"])
        self.assertEqual(summary["dependency_paths"], [])
        self.assertEqual(summary["required_target_paths"], [])
        self.assertEqual(summary["rebuild_command"], "")

    def test_runtime_bridge_build_guard_reports_stale_consumers_and_rebuild_recipe(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lab_root = Path(td) / "riscv_snn_isa_lab"
            spec_path = self._write_runtime_bridge_spec(lab_root)
            snndl_root = self._seed_runtime_bridge_build_tree(lab_root, stale=True)

            summary = riscv_snn_lab.runtime_bridge_build_guard(spec_path=spec_path, lab_root=lab_root)

        self.assertTrue(summary["enabled"])
        self.assertEqual(summary["status"], "stale")
        self.assertEqual(summary["missing_targets"], [])
        self.assertIn(
            str(snndl_root / "services" / "workload" / "snn" / ".libs" / "SnnWorkload.o"),
            summary["stale_targets"],
        )
        self.assertIn(
            str(snndl_root / ".libs" / "libSnnDL.so"),
            summary["stale_targets"],
        )
        self.assertIn("WeightMemorySubsystem.lo", summary["rebuild_command"])
        self.assertIn("BankedSramModel.lo", summary["rebuild_command"])
        self.assertIn("libSnnDL.la", summary["rebuild_command"])

    def test_runtime_bridge_build_guard_requires_full_rebuild_when_installed_fingerprint_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lab_root = Path(td) / "riscv_snn_isa_lab"
            spec_path = self._write_runtime_bridge_spec(lab_root)
            snndl_root = self._seed_runtime_bridge_build_tree(lab_root, stale=False)
            workspace_lib = snndl_root / ".libs" / "libSnnDL.so"
            installed_lib = (
                lab_root.parent
                / "sst_install"
                / "lib"
                / "sst-elements-library"
                / "libSnnDL.so"
            )
            installed_lib.parent.mkdir(parents=True, exist_ok=True)
            workspace_lib.write_text("workspace-build", encoding="utf-8")
            installed_lib.write_text("installed-build-mismatch", encoding="utf-8")

            summary = riscv_snn_lab.runtime_bridge_build_guard(spec_path=spec_path, lab_root=lab_root)

        self.assertTrue(summary["enabled"])
        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["required_action"], "full_clean_rebuild")
        self.assertEqual(summary["lineage_status"], "fingerprint_mismatch")
        self.assertEqual(summary["workspace_lib_path"], str(workspace_lib))
        self.assertEqual(summary["installed_lib_path"], str(installed_lib))
        self.assertFalse(summary["fingerprint_match"])
        self.assertTrue(summary["full_rebuild_required"])
        self.assertIn("installed_library_fingerprint_mismatch", summary["full_rebuild_reason_ids"])
        self.assertNotEqual(
            summary["workspace_build_fingerprint"],
            summary["installed_build_fingerprint"],
        )

    def test_runtime_bridge_build_guard_prefers_matching_installed_library_when_multiple_prefixes_exist(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lab_root = Path(td) / "riscv_snn_isa_lab"
            spec_path = self._write_runtime_bridge_spec(lab_root)
            snndl_root = self._seed_runtime_bridge_build_tree(lab_root, stale=False)
            workspace_lib = snndl_root / ".libs" / "libSnnDL.so"
            workspace_lib.write_text("workspace-build", encoding="utf-8")

            stale_install = (
                lab_root.parent
                / "sst_install"
                / "lib"
                / "sst-elements-library"
                / "libSnnDL.so"
            )
            stale_install.parent.mkdir(parents=True, exist_ok=True)
            stale_install.write_text("stale-install", encoding="utf-8")

            matching_install = (
                lab_root.parent
                / "sst_install_mpi"
                / "lib"
                / "sst-elements-library"
                / "libSnnDL.so"
            )
            matching_install.parent.mkdir(parents=True, exist_ok=True)
            matching_install.write_text("workspace-build", encoding="utf-8")

            summary = riscv_snn_lab.runtime_bridge_build_guard(spec_path=spec_path, lab_root=lab_root)

        self.assertEqual(summary["installed_lib_path"], str(matching_install))
        self.assertTrue(summary["fingerprint_match"])
        self.assertEqual(summary["required_action"], "none")
        self.assertEqual(summary["lineage_status"], "ok")

    def test_run_smoke_with_optional_failure_fails_fast_on_runtime_bridge_stale_build(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lab_root = Path(td) / "riscv_snn_isa_lab"
            spec_path = self._write_runtime_bridge_spec(lab_root)
            self._seed_runtime_bridge_build_tree(lab_root, stale=True)
            runner = FakeRunner()

            with self.assertRaisesRegex(RuntimeError, "runtime-bridge build preflight failed"):
                riscv_snn_lab._run_smoke_with_optional_failure(
                    spec_path=spec_path,
                    lab_root=lab_root,
                    runner=runner,
                    allow_failed_run=False,
                )

        self.assertEqual(runner.calls, [])

    def test_run_equivalence_reports_preflight_failure_before_smoke_launch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            self._write_baseline_snn_spec(lab_root)
            self._write_runtime_bridge_spec(lab_root)

            class EquivRunner(FakeRunner):
                def __call__(self, cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
                    self.calls.append((cmd, cwd))
                    if any(str(part).endswith("mesh_spec_cli.py") for part in cmd):
                        return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")
                    if any(str(part).endswith("run_mesh_with_time.sh") for part in cmd):
                        raise AssertionError("smoke script should not run when preflight already failed")
                    return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")

            runner = EquivRunner()
            preflight_summary = {
                "status": "parallel_unavailable",
                "reason_ids": ["preflight_env_parallel_sst_unavailable"],
                "selected_bin": None,
                "parallel_candidates_checked": ["/tmp/sst_install/bin/sst"],
                "parallel_runnable_candidates": [],
                "reporting_scope": "research_only_nonblocking",
            }
            with mock.patch.object(
                riscv_snn_lab,
                "ensure_runtime_bridge_build_guard",
                return_value=self._runtime_bridge_build_guard_ok_summary(),
            ), mock.patch.object(
                riscv_snn_lab,
                "parallel_sst_preflight",
                return_value=preflight_summary,
            ):
                summary = riscv_snn_lab.run_equivalence(
                    "external_dyn_desc_ref",
                    lab_root=lab_root,
                    runner=runner,
                )

        self.assertEqual(summary["status"], "FAIL")
        self.assertIn("baseline_preflight_failed", summary["gate_reasons"])
        self.assertIn("runtime_bridge_preflight_failed", summary["gate_reasons"])
        self.assertIn("baseline_preflight_env_parallel_sst_unavailable", summary["gate_reasons"])
        self.assertIn("runtime_bridge_preflight_env_parallel_sst_unavailable", summary["gate_reasons"])
        self.assertEqual(summary["baseline"]["validation"], "preflight_failed")
        self.assertEqual(summary["runtime_bridge"]["validation"], "preflight_failed")
        self.assertEqual(
            summary["baseline"]["validation_detail"]["reason_ids"],
            ["preflight_env_parallel_sst_unavailable"],
        )
        self.assertEqual(
            summary["runtime_bridge"]["validation_detail"]["reason_ids"],
            ["preflight_env_parallel_sst_unavailable"],
        )
        smoke_calls = [
            cmd for cmd, _ in runner.calls if any(str(part).endswith("run_mesh_with_time.sh") for part in cmd)
        ]
        self.assertEqual(smoke_calls, [])

    def test_protocol_suite_all_runs_explicit_make_target(self) -> None:
        runner = FakeRunner()
        proc = riscv_snn_lab.run_protocol_suite(runner=runner)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(runner.calls[0][0], ["make", "test-riscv-snn-protocols"])
        self.assertEqual(runner.calls[0][1], str(riscv_snn_lab.SNNDL_ROOT))

    def test_protocol_suite_toolchain_runs_explicit_make_target(self) -> None:
        runner = FakeRunner()
        proc = riscv_snn_lab.run_protocol_suite("toolchain", runner=runner)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(
            runner.calls[0][0],
            ["make", "test-riscv-snn-toolchain-firmware-protocol"],
        )
        self.assertEqual(runner.calls[0][1], str(riscv_snn_lab.SNNDL_ROOT))

    def test_regress_runs_protocol_then_builder_smoke(self) -> None:
        runner = FakeRunner()
        with mock.patch.object(
            riscv_snn_lab,
            "ensure_runtime_bridge_build_guard",
            return_value=self._runtime_bridge_build_guard_ok_summary(),
        ) as build_guard, mock.patch.object(
            riscv_snn_lab,
            "ensure_parallel_sst_preflight",
            return_value={"status": "ok", "reason_ids": []},
        ) as parallel_preflight:
            run_dir, manifest_path = riscv_snn_lab.run_regression(
                "external_dyn_desc_ref",
                suite="builder",
                runner=runner,
            )
        self.assertEqual(run_dir, Path("/tmp/fake-run"))
        self.assertIsNone(manifest_path)
        self.assertEqual(len(runner.calls), 4)
        self.assertEqual(runner.calls[0][0], ["make", "test-riscv-snn-firmware-protocol"])
        self.assertEqual(runner.calls[0][1], str(riscv_snn_lab.SNNDL_ROOT))
        self.assertIn("--program", runner.calls[1][0])
        self.assertIn("external_dyn_desc_ref", runner.calls[1][0])
        self.assertEqual(runner.calls[2][0][0:3], ["python3", str(riscv_snn_lab.SPEC_CLI), "validate"])
        self.assertTrue(any(str(part).endswith("run_mesh_with_time.sh") for part in runner.calls[3][0]))
        build_guard.assert_called_once()
        parallel_preflight.assert_called_once()

    def test_regress_runs_protocol_then_toolchain_smoke(self) -> None:
        runner = FakeRunner()
        with mock.patch.object(
            riscv_snn_lab,
            "ensure_runtime_bridge_build_guard",
            return_value=self._runtime_bridge_build_guard_ok_summary(),
        ) as build_guard, mock.patch.object(
            riscv_snn_lab,
            "ensure_parallel_sst_preflight",
            return_value={"status": "ok", "reason_ids": []},
        ) as parallel_preflight:
            run_dir, manifest_path = riscv_snn_lab.run_regression(
                "external_dyn_desc_fault_rearm_ref_toolchain",
                suite="toolchain",
                runner=runner,
            )
        self.assertEqual(run_dir, Path("/tmp/fake-run"))
        self.assertIsNone(manifest_path)
        self.assertEqual(len(runner.calls), 4)
        self.assertEqual(
            runner.calls[0][0],
            ["make", "test-riscv-snn-toolchain-firmware-protocol"],
        )
        self.assertEqual(runner.calls[0][1], str(riscv_snn_lab.SNNDL_ROOT))
        self.assertEqual(runner.calls[1][0], ["make"])
        self.assertTrue(
            runner.calls[1][1].endswith(
                "/riscv_snn_isa_lab/firmware_src/external_dyn_desc_fault_rearm_ref_toolchain"
            )
        )
        self.assertEqual(runner.calls[2][0][0:3], ["python3", str(riscv_snn_lab.SPEC_CLI), "validate"])
        self.assertTrue(any(str(part).endswith("run_mesh_with_time.sh") for part in runner.calls[3][0]))
        build_guard.assert_called_once()
        parallel_preflight.assert_called_once()

    def test_regress_with_register_writes_manifest_draft(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            firmware_dir = lab_root / "firmware"
            specs_dir = lab_root / "specs"
            runs_dir = lab_root / "runs"
            firmware_dir.mkdir(parents=True)
            specs_dir.mkdir(parents=True)
            runs_dir.mkdir(parents=True)

            program = "external_dyn_desc_ref"
            elf_path = firmware_dir / f"{program}.elf"
            elf_path.write_bytes(b"\x7fELFstub")
            spec_path = specs_dir / f"{program}.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "platform": {
                            "mesh_size": 4,
                            "exec_mode": "gas",
                            "stop": {"simulation_time": "1us"},
                        },
                        "workload": {
                            "impl": "riscv_snn",
                            "params": {"firmware_elf": str(elf_path)},
                        },
                        "control": {"global_step_sync_enable": False},
                    }
                ),
                encoding="utf-8",
            )

            run_dir = td_path / "run"

            class RegressionRunner(FakeRunner):
                def __call__(self, cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
                    self.calls.append((cmd, cwd))
                    if "--list-programs" in cmd:
                        return subprocess.CompletedProcess(
                            cmd,
                            0,
                            stdout=json.dumps({"samples": {program: {"canonical_sample": False, "description": "ref"}}}),
                            stderr="",
                        )
                    if any(str(part).endswith("run_mesh_with_time.sh") for part in cmd):
                        (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
                        (run_dir / "meta.json").write_text(
                            json.dumps(
                                {
                                    "run": {
                                        "run_id": "20260325-000000",
                                        "created_utc": "2026-03-25T00:00:00+00:00",
                                        "hostname": "node1",
                                    }
                                }
                            ),
                            encoding="utf-8",
                        )
                        (run_dir / "inputs" / "spec.json").write_text(
                            Path(cmd[-1]).read_text(encoding="utf-8"),
                            encoding="utf-8",
                        )
                        (run_dir / "validation.log").write_text(
                            "[val] SUMMARY run_dir=/tmp/fake-run fail=0 warn=0 strict=0\n",
                            encoding="utf-8",
                        )
                        return subprocess.CompletedProcess(
                            cmd,
                            0,
                            stdout=f"[mesh] run complete: {run_dir}\n",
                            stderr="",
                        )
                    return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")

            runner = RegressionRunner()
            resolved_run_dir, manifest_path = riscv_snn_lab.run_regression(
                program,
                suite="builder",
                register=True,
                lab_root=lab_root,
                runner=runner,
            )
            self.assertEqual(resolved_run_dir, run_dir)
            self.assertIsNotNone(manifest_path)
            assert manifest_path is not None
            self.assertTrue(manifest_path.exists())
            self.assertIn(str(run_dir), manifest_path.read_text(encoding="utf-8"))

    def test_register_writes_manifest_draft(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            firmware_dir = lab_root / "firmware"
            specs_dir = lab_root / "specs"
            runs_dir = lab_root / "runs"
            firmware_dir.mkdir(parents=True)
            specs_dir.mkdir(parents=True)
            runs_dir.mkdir(parents=True)

            elf_path = firmware_dir / "external_dyn_desc_ref.elf"
            elf_path.write_bytes(b"\x7fELFstub")
            spec_path = specs_dir / "external_dyn_desc_ref.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "platform": {
                            "mesh_size": 4,
                            "exec_mode": "gas",
                            "stop": {"simulation_time": "1us"},
                        },
                        "workload": {
                            "impl": "riscv_snn",
                            "params": {"firmware_elf": str(elf_path)},
                        },
                        "control": {"global_step_sync_enable": False},
                    }
                ),
                encoding="utf-8",
            )

            run_dir = td_path / "run"
            (run_dir / "inputs").mkdir(parents=True)
            (run_dir / "meta.json").write_text(
                json.dumps(
                    {
                        "run": {
                            "run_id": "20260324-000000",
                            "created_utc": "2026-03-24T00:00:00+00:00",
                            "hostname": "node1",
                        }
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "inputs" / "spec.json").write_text(spec_path.read_text(encoding="utf-8"), encoding="utf-8")

            manifest_path = runs_dir / "draft.md"
            result = riscv_snn_lab.register_run(
                "external_dyn_desc_ref",
                run_dir,
                manifest_path=manifest_path,
                lab_root=lab_root,
            )
            self.assertEqual(result, manifest_path)
            content = manifest_path.read_text(encoding="utf-8")
            self.assertIn("external_dyn_desc_ref", content)
            self.assertIn(str(run_dir), content)
            self.assertIn(str(elf_path), content)

    def test_run_matrix_toolchain_registers_summary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            firmware_dir = lab_root / "firmware"
            specs_dir = lab_root / "specs"
            runs_dir = lab_root / "runs"
            refs_dir = lab_root / "references"
            src_root = lab_root / "firmware_src"
            for path in (firmware_dir, specs_dir, runs_dir, refs_dir, src_root):
                path.mkdir(parents=True, exist_ok=True)

            programs = [
                "external_dyn_desc_ref_toolchain",
                "external_dyn_desc_fault_ref_toolchain",
            ]
            for index, program in enumerate(programs):
                (src_root / program).mkdir(parents=True, exist_ok=True)
                (src_root / program / "main.S").write_text(
                    f"; {program}\n",
                    encoding="utf-8",
                )
                elf_path = firmware_dir / f"{program}.elf"
                elf_path.write_bytes(b"\x7fELF" + bytes([index]))
                spec_path = specs_dir / f"{program}.json"
                spec_path.write_text(
                    json.dumps(
                        {
                            "platform": {
                                "mesh_size": 4,
                                "exec_mode": "gas",
                                "stop": {"simulation_time": "1us"},
                            },
                            "workload": {
                                "impl": "riscv_snn",
                                "params": {"firmware_elf": str(elf_path)},
                            },
                            "control": {"global_step_sync_enable": False},
                        }
                    ),
                    encoding="utf-8",
                )

            class MatrixRunner(FakeRunner):
                def __call__(self, cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
                    self.calls.append((cmd, cwd))
                    if "--list-programs" in cmd:
                        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"samples": {}}), stderr="")
                    if any(str(part).endswith("run_mesh_with_time.sh") for part in cmd):
                        spec_path = Path(cmd[-1])
                        run_dir = td_path / "runs_out" / spec_path.stem
                        (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
                        (run_dir / "meta.json").write_text(
                            json.dumps(
                                {
                                    "run": {
                                        "run_id": f"run-{spec_path.stem}",
                                        "created_utc": "2026-03-25T00:00:00+00:00",
                                        "hostname": "node1",
                                    }
                                }
                            ),
                            encoding="utf-8",
                        )
                        (run_dir / "inputs" / "spec.json").write_text(
                            spec_path.read_text(encoding="utf-8"),
                            encoding="utf-8",
                        )
                        (run_dir / "validation.log").write_text(
                            "[val] SUMMARY run_dir=/tmp/fake-run fail=0 warn=0 strict=0\n",
                            encoding="utf-8",
                        )
                        return subprocess.CompletedProcess(
                            cmd,
                            0,
                            stdout=f"[mesh] run complete: {run_dir}\n",
                            stderr="",
                        )
                    return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")

            summary_path = refs_dir / "toolchain-matrix.json"
            runner = MatrixRunner()
            summary = riscv_snn_lab.run_matrix(
                "toolchain",
                programs=programs,
                register=True,
                summary_path=summary_path,
                lab_root=lab_root,
                runner=runner,
            )

            self.assertEqual(summary["group"], "toolchain")
            self.assertEqual(summary["count"], 2)
            self.assertEqual([entry["program"] for entry in summary["results"]], programs)
            self.assertTrue(all(entry["manifest_path"] for entry in summary["results"]))
            self.assertTrue(summary_path.exists())
            self.assertEqual(json.loads(summary_path.read_text(encoding="utf-8"))["count"], 2)

    def test_audit_programs_matches_latest_registered_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            firmware_dir = lab_root / "firmware"
            specs_dir = lab_root / "specs"
            runs_dir = lab_root / "runs"
            refs_dir = lab_root / "references"
            src_dir = lab_root / "firmware_src" / "external_dyn_desc_fault_ref_toolchain"
            for path in (firmware_dir, specs_dir, runs_dir, refs_dir, src_dir):
                path.mkdir(parents=True, exist_ok=True)

            program = "external_dyn_desc_fault_ref_toolchain"
            elf_path = firmware_dir / f"{program}.elf"
            elf_path.write_bytes(b"\x7fELFaudit")
            spec_path = specs_dir / f"{program}.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "platform": {
                            "mesh_size": 4,
                            "exec_mode": "gas",
                            "stop": {"simulation_time": "1us"},
                        },
                        "workload": {
                            "impl": "riscv_snn",
                            "params": {"firmware_elf": str(elf_path)},
                        },
                        "control": {"global_step_sync_enable": False},
                    }
                ),
                encoding="utf-8",
            )
            (src_dir / "main.S").write_text("addi x0, x0, 0\n", encoding="utf-8")

            run_dir = td_path / "audit-run"
            (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
            (run_dir / "meta.json").write_text(
                json.dumps(
                    {
                        "run": {
                            "run_id": "20260325-000001",
                            "created_utc": "2026-03-25T00:00:00+00:00",
                            "hostname": "node1",
                        }
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "inputs" / "spec.json").write_text(spec_path.read_text(encoding="utf-8"), encoding="utf-8")
            manifest_path = riscv_snn_lab.register_run(program, run_dir, lab_root=lab_root)

            summary_path = refs_dir / "toolchain-audit.json"
            summary = riscv_snn_lab.audit_programs(
                "toolchain",
                programs=[program],
                summary_path=summary_path,
                lab_root=lab_root,
            )

            self.assertEqual(summary["group"], "toolchain")
            self.assertEqual(summary["count"], 1)
            self.assertEqual(summary["results"][0]["latest_manifest"], str(manifest_path))
            self.assertTrue(summary["results"][0]["manifest_match"])
            self.assertTrue(summary_path.exists())
            self.assertTrue(json.loads(summary_path.read_text(encoding="utf-8"))["results"][0]["manifest_match"])

    def test_build_nightly_index_links_builder_toolchain_and_audit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            builder_summary = {
                "summary_path": str(refs_dir / "builder.json"),
                "group": "builder",
                "count": 1,
                "register": True,
                "results": [
                    {
                        "program": "external_dyn_desc_ref",
                        "suite": "builder",
                        "run_dir": "/tmp/builder-run-001",
                        "manifest_path": "/tmp/builder-manifest.md",
                    }
                ],
            }
            toolchain_summary = {
                "summary_path": str(refs_dir / "toolchain.json"),
                "group": "toolchain",
                "count": 1,
                "register": True,
                "results": [
                    {
                        "program": "external_dyn_desc_ref_toolchain",
                        "suite": "toolchain",
                        "run_dir": "/tmp/toolchain-run-001",
                        "manifest_path": "/tmp/toolchain-manifest.md",
                    }
                ],
            }
            audit_summary = {
                "summary_path": str(refs_dir / "audit.json"),
                "group": "toolchain",
                "count": 1,
                "protocol_checked": True,
                "all_ok": True,
                "results": [
                    {
                        "program": "external_dyn_desc_ref_toolchain",
                        "suite": "toolchain",
                        "latest_manifest": "/tmp/toolchain-manifest.md",
                        "manifest_run_dir": "/tmp/toolchain-run-001",
                        "manifest_match": True,
                        "ok": True,
                    }
                ],
            }

            index_path = refs_dir / "nightly-index.json"
            index = riscv_snn_lab.build_nightly_index(
                builder_summary,
                toolchain_summary,
                audit_summary,
                output_path=index_path,
                lab_root=lab_root,
            )

            self.assertEqual(index["count"], 1)
            self.assertTrue(index["all_ok"])
            self.assertEqual(index["builder_summary_path"], builder_summary["summary_path"])
            self.assertEqual(index["toolchain_summary_path"], toolchain_summary["summary_path"])
            self.assertEqual(index["toolchain_audit_summary_path"], audit_summary["summary_path"])
            self.assertEqual(index["families"][0]["family"], "external_dyn_desc_ref")
            self.assertEqual(index["families"][0]["builder"]["run_id"], "builder-run-001")
            self.assertEqual(index["families"][0]["toolchain"]["run_id"], "toolchain-run-001")
            self.assertTrue(index["families"][0]["audit"]["manifest_match"])
            self.assertTrue(index_path.exists())

    def test_run_nightly_writes_index_and_subsummaries(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            firmware_dir = lab_root / "firmware"
            specs_dir = lab_root / "specs"
            runs_dir = lab_root / "runs"
            refs_dir = lab_root / "references"
            src_root = lab_root / "firmware_src"
            for path in (firmware_dir, specs_dir, runs_dir, refs_dir, src_root):
                path.mkdir(parents=True, exist_ok=True)

            builder_program = "external_dyn_desc_ref"
            toolchain_program = "external_dyn_desc_ref_toolchain"
            (src_root / toolchain_program).mkdir(parents=True, exist_ok=True)
            (src_root / toolchain_program / "main.S").write_text("addi x0, x0, 0\n", encoding="utf-8")

            for index, program in enumerate((builder_program, toolchain_program)):
                elf_path = firmware_dir / f"{program}.elf"
                elf_path.write_bytes(b"\x7fELFnightly" + bytes([index]))
                spec_path = specs_dir / f"{program}.json"
                spec_path.write_text(
                    json.dumps(
                        {
                            "platform": {
                                "mesh_size": 4,
                                "exec_mode": "gas",
                                "stop": {"simulation_time": "1us"},
                            },
                            "workload": {
                                "impl": "riscv_snn",
                                "params": {"firmware_elf": str(elf_path)},
                            },
                            "control": {"global_step_sync_enable": False},
                        }
                    ),
                    encoding="utf-8",
                )

            class NightlyRunner(FakeRunner):
                def __call__(self, cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
                    self.calls.append((cmd, cwd))
                    if "--list-programs" in cmd:
                        return subprocess.CompletedProcess(
                            cmd,
                            0,
                            stdout=json.dumps({"samples": {builder_program: {}, toolchain_program: {}}}),
                            stderr="",
                        )
                    if any(str(part).endswith("run_mesh_with_time.sh") for part in cmd):
                        spec_path = Path(cmd[-1])
                        run_dir = td_path / "nightly-runs" / spec_path.stem
                        (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
                        (run_dir / "meta.json").write_text(
                            json.dumps(
                                {
                                    "run": {
                                        "run_id": f"nightly-{spec_path.stem}",
                                        "created_utc": "2026-03-25T00:00:00+00:00",
                                        "hostname": "node1",
                                    }
                                }
                            ),
                            encoding="utf-8",
                        )
                        (run_dir / "inputs" / "spec.json").write_text(
                            spec_path.read_text(encoding="utf-8"),
                            encoding="utf-8",
                        )
                        (run_dir / "validation.log").write_text(
                            "[val] SUMMARY run_dir=/tmp/fake-run fail=0 warn=0 strict=0\n",
                            encoding="utf-8",
                        )
                        return subprocess.CompletedProcess(
                            cmd,
                            0,
                            stdout=f"[mesh] run complete: {run_dir}\n",
                            stderr="",
                        )
                    return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")

            runner = NightlyRunner()
            index = riscv_snn_lab.run_nightly(
                builder_programs=[builder_program],
                toolchain_programs=[toolchain_program],
                lab_root=lab_root,
                runner=runner,
            )

            self.assertEqual(index["count"], 1)
            self.assertTrue(index["all_ok"])
            self.assertTrue(Path(index["summary_path"]).exists())
            self.assertTrue(Path(index["builder_summary_path"]).exists())
            self.assertTrue(Path(index["toolchain_summary_path"]).exists())
            self.assertTrue(Path(index["toolchain_audit_summary_path"]).exists())
            self.assertEqual(index["families"][0]["family"], "external_dyn_desc_ref")
            self.assertEqual(index["families"][0]["builder"]["program"], builder_program)
            self.assertEqual(index["families"][0]["toolchain"]["program"], toolchain_program)
            self.assertTrue(index["families"][0]["audit"]["manifest_match"])

    def test_run_nightly_full_surface_keeps_canonical_dated_paths(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            def fake_run_matrix(group: str = "all", **kwargs: Any) -> dict[str, Any]:
                resolved_path = kwargs.get("summary_path")
                if resolved_path is None:
                    raise AssertionError("summary_path should be pre-resolved by run_nightly")
                return {
                    "summary_path": str(resolved_path),
                    "group": group,
                    "results": [
                        {
                            "program": (
                                "external_dyn_desc_ref"
                                if group == "builder"
                                else "external_dyn_desc_ref_toolchain"
                            ),
                            "run_dir": f"/tmp/{group}-run",
                            "manifest_path": f"/tmp/{group}.md",
                        }
                    ],
                }

            def fake_audit(group: str = "all", **kwargs: Any) -> dict[str, Any]:
                resolved_path = kwargs.get("summary_path")
                if resolved_path is None:
                    raise AssertionError("summary_path should be pre-resolved by run_nightly")
                return {
                    "summary_path": str(resolved_path),
                    "group": group,
                    "all_ok": True,
                    "results": [
                        {
                            "program": "external_dyn_desc_ref_toolchain",
                            "latest_manifest": "/tmp/toolchain.md",
                            "manifest_run_dir": "/tmp/toolchain-run",
                            "manifest_match": True,
                            "ok": True,
                        }
                    ],
                }

            with mock.patch.object(riscv_snn_lab, "run_matrix", side_effect=fake_run_matrix):
                with mock.patch.object(riscv_snn_lab, "audit_programs", side_effect=fake_audit):
                    nightly = riscv_snn_lab.run_nightly(lab_root=lab_root)

            self.assertTrue(Path(nightly["summary_path"]).name.endswith("-nightly-index.json"))
            self.assertNotIn("-subset-", Path(nightly["summary_path"]).name)
            self.assertTrue(Path(nightly["builder_summary_path"]).name.endswith("-builder-regress-matrix.json"))
            self.assertTrue(Path(nightly["toolchain_summary_path"]).name.endswith("-toolchain-regress-matrix.json"))
            self.assertTrue(Path(nightly["toolchain_audit_summary_path"]).name.endswith("-toolchain-bridge-audit.json"))

    def test_run_nightly_subset_surface_avoids_canonical_dated_paths(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            builder_subset = ["external_dyn_desc_ref"]
            toolchain_subset = ["external_dyn_desc_ref_toolchain"]

            def fake_run_matrix(group: str = "all", **kwargs: Any) -> dict[str, Any]:
                resolved_path = kwargs.get("summary_path")
                if resolved_path is None:
                    raise AssertionError("summary_path should be pre-resolved by run_nightly")
                return {
                    "summary_path": str(resolved_path),
                    "group": group,
                    "results": [
                        {
                            "program": (
                                builder_subset[0]
                                if group == "builder"
                                else toolchain_subset[0]
                            ),
                            "run_dir": f"/tmp/{group}-run",
                            "manifest_path": f"/tmp/{group}.md",
                        }
                    ],
                }

            def fake_audit(group: str = "all", **kwargs: Any) -> dict[str, Any]:
                resolved_path = kwargs.get("summary_path")
                if resolved_path is None:
                    raise AssertionError("summary_path should be pre-resolved by run_nightly")
                return {
                    "summary_path": str(resolved_path),
                    "group": group,
                    "all_ok": True,
                    "results": [
                        {
                            "program": toolchain_subset[0],
                            "latest_manifest": "/tmp/toolchain.md",
                            "manifest_run_dir": "/tmp/toolchain-run",
                            "manifest_match": True,
                            "ok": True,
                        }
                    ],
                }

            with mock.patch.object(riscv_snn_lab, "run_matrix", side_effect=fake_run_matrix):
                with mock.patch.object(riscv_snn_lab, "audit_programs", side_effect=fake_audit):
                    nightly = riscv_snn_lab.run_nightly(
                        builder_programs=builder_subset,
                        toolchain_programs=toolchain_subset,
                        lab_root=lab_root,
                    )

            self.assertIn("-nightly-index-subset-", Path(nightly["summary_path"]).name)
            self.assertIn("-builder-regress-matrix-subset-", Path(nightly["builder_summary_path"]).name)
            self.assertIn("-toolchain-regress-matrix-subset-", Path(nightly["toolchain_summary_path"]).name)
            self.assertIn("-toolchain-bridge-audit-subset-", Path(nightly["toolchain_audit_summary_path"]).name)

    def test_run_matrix_subset_surface_avoids_canonical_group_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            with mock.patch.object(riscv_snn_lab, "run_protocol_suite", return_value=subprocess.CompletedProcess(["make"], 0)):
                with mock.patch.object(riscv_snn_lab, "smoke_program", return_value=Path("/tmp/fake-run")):
                    summary = riscv_snn_lab.run_matrix(
                        "builder",
                        programs=["external_dyn_desc_ref"],
                        lab_root=lab_root,
                    )

            resolved_path = Path(summary["summary_path"])
            self.assertTrue(resolved_path.exists())
            self.assertIn("-builder-regress-matrix-subset-", resolved_path.name)

    def test_audit_programs_subset_surface_avoids_canonical_group_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            with mock.patch.object(
                riscv_snn_lab,
                "_audit_program",
                return_value={
                    "program": "external_dyn_desc_ref_toolchain",
                    "suite": "toolchain",
                    "is_toolchain": True,
                    "source_dir": "/tmp/src",
                    "source_file_count": 1,
                    "source_files": [],
                    "elf": None,
                    "spec": None,
                    "latest_manifest": "/tmp/manifest.md",
                    "manifest_run_dir": "/tmp/run",
                    "manifest_elf_match": True,
                    "manifest_spec_match": True,
                    "manifest_match": True,
                    "ok": True,
                },
            ):
                summary = riscv_snn_lab.audit_programs(
                    "toolchain",
                    programs=["external_dyn_desc_ref_toolchain"],
                    lab_root=lab_root,
                )

            resolved_path = Path(summary["summary_path"])
            self.assertTrue(resolved_path.exists())
            self.assertIn("-toolchain-bridge-audit-subset-", resolved_path.name)

    def test_build_history_index_rolls_up_multiple_dates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            refs_dir = td_path / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            first = refs_dir / "2026-03-24-nightly-index.json"
            first.write_text(
                json.dumps(
                    {
                        "generated_utc": "2026-03-24T00:00:00+00:00",
                        "count": 1,
                        "all_ok": True,
                        "builder_summary_path": "/tmp/2026-03-24-builder.json",
                        "toolchain_summary_path": "/tmp/2026-03-24-toolchain.json",
                        "toolchain_audit_summary_path": "/tmp/2026-03-24-audit.json",
                        "families": [
                            {
                                "family": "external_dyn_desc_ref",
                                "builder": {"run_id": "20260324-000001", "run_dir": "/tmp/b1", "manifest_path": "/tmp/b1.md", "program": "external_dyn_desc_ref"},
                                "toolchain": {"run_id": "20260324-000002", "run_dir": "/tmp/t1", "manifest_path": "/tmp/t1.md", "program": "external_dyn_desc_ref_toolchain"},
                                "audit": {"manifest_match": True, "ok": True, "latest_manifest": "/tmp/t1.md", "manifest_run_dir": "/tmp/t1"},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            second = refs_dir / "2026-03-25-nightly-index.json"
            second.write_text(
                json.dumps(
                    {
                        "generated_utc": "2026-03-25T00:00:00+00:00",
                        "count": 1,
                        "all_ok": True,
                        "builder_summary_path": "/tmp/2026-03-25-builder.json",
                        "toolchain_summary_path": "/tmp/2026-03-25-toolchain.json",
                        "toolchain_audit_summary_path": "/tmp/2026-03-25-audit.json",
                        "families": [
                            {
                                "family": "external_dyn_desc_ref",
                                "builder": {"run_id": "20260325-000001", "run_dir": "/tmp/b2", "manifest_path": "/tmp/b2.md", "program": "external_dyn_desc_ref"},
                                "toolchain": {"run_id": "20260325-000002", "run_dir": "/tmp/t2", "manifest_path": "/tmp/t2.md", "program": "external_dyn_desc_ref_toolchain"},
                                "audit": {"manifest_match": True, "ok": True, "latest_manifest": "/tmp/t2.md", "manifest_run_dir": "/tmp/t2"},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            history_path = refs_dir / "nightly-history-index.json"
            history = riscv_snn_lab.build_history_index(
                [first, second],
                output_path=history_path,
            )

            self.assertEqual(history["count"], 2)
            self.assertEqual(history["latest_date"], "2026-03-25")
            self.assertEqual(history["entries"][0]["date"], "2026-03-25")
            self.assertEqual(history["family_history"][0]["family"], "external_dyn_desc_ref")
            self.assertEqual(len(history["family_history"][0]["days"]), 2)
            self.assertTrue(history_path.exists())

    def test_build_history_index_tracks_fail_drift_and_recovery_dates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            refs_dir = td_path / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            def write_index(date_str: str, *, all_ok: bool, manifest_match: bool, audit_ok: bool) -> Path:
                path = refs_dir / f"{date_str}-nightly-index.json"
                path.write_text(
                    json.dumps(
                        {
                            "generated_utc": f"{date_str}T00:00:00+00:00",
                            "count": 1,
                            "all_ok": all_ok,
                            "builder_summary_path": f"/tmp/{date_str}-builder.json",
                            "toolchain_summary_path": f"/tmp/{date_str}-toolchain.json",
                            "toolchain_audit_summary_path": f"/tmp/{date_str}-audit.json",
                            "families": [
                                {
                                    "family": "external_dyn_desc_ref",
                                    "builder": {
                                        "run_id": f"{date_str.replace('-', '')}-000001",
                                        "run_dir": f"/tmp/{date_str}/builder",
                                        "manifest_path": f"/tmp/{date_str}/builder.md",
                                        "program": "external_dyn_desc_ref",
                                    },
                                    "toolchain": {
                                        "run_id": f"{date_str.replace('-', '')}-000002",
                                        "run_dir": f"/tmp/{date_str}/toolchain",
                                        "manifest_path": f"/tmp/{date_str}/toolchain.md",
                                        "program": "external_dyn_desc_ref_toolchain",
                                    },
                                    "audit": {
                                        "manifest_match": manifest_match,
                                        "ok": audit_ok,
                                        "latest_manifest": f"/tmp/{date_str}/toolchain.md",
                                        "manifest_run_dir": f"/tmp/{date_str}/toolchain",
                                    },
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                return path

            history = riscv_snn_lab.build_history_index(
                [
                    write_index("2026-03-22", all_ok=True, manifest_match=True, audit_ok=True),
                    write_index("2026-03-23", all_ok=True, manifest_match=False, audit_ok=True),
                    write_index("2026-03-24", all_ok=False, manifest_match=True, audit_ok=False),
                    write_index("2026-03-25", all_ok=True, manifest_match=True, audit_ok=True),
                ],
                output_path=refs_dir / "nightly-history-index.json",
            )

            self.assertEqual(history["first_drift_date"], "2026-03-23")
            self.assertEqual(history["first_fail_date"], "2026-03-24")
            self.assertEqual(history["latest_recovered_date"], "2026-03-25")
            self.assertFalse(history["entries"][1]["healthy"])
            self.assertEqual(history["entries"][1]["drift_families"], [])
            self.assertEqual(history["entries"][2]["drift_families"], ["external_dyn_desc_ref"])
            self.assertEqual(history["family_history"][0]["first_drift_date"], "2026-03-23")
            self.assertEqual(history["family_history"][0]["first_fail_date"], "2026-03-24")
            self.assertEqual(history["family_history"][0]["latest_recovered_date"], "2026-03-25")

    def test_evaluate_nightly_gate_derives_missing_families_from_authority_surface(self) -> None:
        nightly_index = {
            "count": 1,
            "all_ok": True,
            "families": [
                {
                    "family": "external_dyn_desc_ref",
                    "audit": {"manifest_match": True, "ok": True},
                }
            ],
        }

        gate = riscv_snn_lab.evaluate_nightly_gate(
            nightly_index,
            required_families=[
                "external_dyn_desc_ref",
                "external_dyn_desc_fault_ref",
            ],
        )

        self.assertFalse(gate["gate_ok"])
        self.assertEqual(gate["gate_name"], "riscv_snn_experimental_nightly")
        self.assertEqual(gate["gate_version"], "1.1")
        self.assertEqual(
            gate["required_families"],
            ["external_dyn_desc_fault_ref", "external_dyn_desc_ref"],
        )
        self.assertEqual(gate["missing_families"], ["external_dyn_desc_fault_ref"])
        self.assertEqual(gate["min_count"], 2)
        self.assertTrue(any("missing required families" in reason for reason in gate["reasons"]))

    def test_build_nightly_index_carries_artifact_role_and_scope(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            refs_dir = td_path / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            builder_summary = {
                "summary_path": "/tmp/builder.json",
                "results": [
                    {
                        "program": "external_dyn_desc_ref",
                        "run_dir": "/tmp/builder-run",
                        "manifest_path": "/tmp/builder.md",
                    }
                ],
            }
            toolchain_summary = {
                "summary_path": "/tmp/toolchain.json",
                "results": [
                    {
                        "program": "external_dyn_desc_ref_toolchain",
                        "run_dir": "/tmp/toolchain-run",
                        "manifest_path": "/tmp/toolchain.md",
                    }
                ],
            }
            toolchain_audit = {
                "summary_path": "/tmp/audit.json",
                "all_ok": True,
                "results": [
                    {
                        "program": "external_dyn_desc_ref_toolchain",
                        "latest_manifest": "/tmp/toolchain.md",
                        "manifest_run_dir": "/tmp/toolchain-run",
                        "manifest_match": True,
                        "ok": True,
                    }
                ],
            }

            output_path = refs_dir / "nightly-index.json"
            index = riscv_snn_lab.build_nightly_index(
                builder_summary,
                toolchain_summary,
                toolchain_audit,
                output_path=output_path,
                lab_root=td_path,
            )

            self.assertEqual(index["schema_version"], 2)
            self.assertEqual(index["artifact_role"], "dated_nightly_index")
            self.assertEqual(index["authority_scope"], "builder_toolchain_audit_only")
            self.assertEqual(index["producer"], "riscv_snn_lab.build_nightly_index")
            self.assertEqual(index["summary_path"], str(output_path))
            self.assertTrue(output_path.exists())

    def test_build_history_index_carries_artifact_role_and_scope(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            refs_dir = td_path / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)
            index_path = refs_dir / "2026-03-27-nightly-index.json"
            index_path.write_text(
                json.dumps(
                    {
                        "generated_utc": "2026-03-27T00:00:00+00:00",
                        "count": 1,
                        "all_ok": True,
                        "families": [
                            {
                                "family": "external_dyn_desc_ref",
                                "builder": {"run_id": "builder-001"},
                                "toolchain": {"run_id": "toolchain-001"},
                                "audit": {"manifest_match": True, "ok": True},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            history = riscv_snn_lab.build_history_index([index_path], output_path=refs_dir / "history.json")

        self.assertEqual(history["schema_version"], 2)
        self.assertEqual(history["artifact_role"], "stable_history_rollup")
        self.assertEqual(history["authority_scope"], "historical_rollup_only")
        self.assertEqual(history["producer"], "riscv_snn_lab.build_history_index")

    def test_run_ci_sidecar_writes_gate_report_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            firmware_dir = lab_root / "firmware"
            specs_dir = lab_root / "specs"
            runs_dir = lab_root / "runs"
            refs_dir = lab_root / "references"
            src_root = lab_root / "firmware_src"
            for path in (firmware_dir, specs_dir, runs_dir, refs_dir, src_root):
                path.mkdir(parents=True, exist_ok=True)

            builder_program = "external_dyn_desc_ref"
            toolchain_program = "external_dyn_desc_ref_toolchain"
            (src_root / toolchain_program).mkdir(parents=True, exist_ok=True)
            (src_root / toolchain_program / "main.S").write_text("addi x0, x0, 0\n", encoding="utf-8")

            for index, program in enumerate((builder_program, toolchain_program)):
                elf_path = firmware_dir / f"{program}.elf"
                elf_path.write_bytes(b"\x7fELFsidecar" + bytes([index]))
                spec_path = specs_dir / f"{program}.json"
                spec_path.write_text(
                    json.dumps(
                        {
                            "platform": {
                                "mesh_size": 4,
                                "exec_mode": "gas",
                                "stop": {"simulation_time": "1us"},
                            },
                            "workload": {
                                "impl": "riscv_snn",
                                "params": {"firmware_elf": str(elf_path)},
                            },
                            "control": {"global_step_sync_enable": False},
                        }
                    ),
                    encoding="utf-8",
                )

            class SidecarRunner(FakeRunner):
                def __call__(self, cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
                    self.calls.append((cmd, cwd))
                    if "--list-programs" in cmd:
                        return subprocess.CompletedProcess(
                            cmd,
                            0,
                            stdout=json.dumps({"samples": {builder_program: {}, toolchain_program: {}}}),
                            stderr="",
                        )
                    if any(str(part).endswith("run_mesh_with_time.sh") for part in cmd):
                        spec_path = Path(cmd[-1])
                        run_dir = td_path / "sidecar-runs" / spec_path.stem
                        (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
                        (run_dir / "meta.json").write_text(
                            json.dumps(
                                {
                                    "run": {
                                        "run_id": f"sidecar-{spec_path.stem}",
                                        "created_utc": "2026-03-25T00:00:00+00:00",
                                        "hostname": "node1",
                                    }
                                }
                            ),
                            encoding="utf-8",
                        )
                        (run_dir / "inputs" / "spec.json").write_text(
                            spec_path.read_text(encoding="utf-8"),
                            encoding="utf-8",
                        )
                        (run_dir / "validation.log").write_text(
                            "[val] SUMMARY run_dir=/tmp/fake-run fail=0 warn=0 strict=0\n",
                            encoding="utf-8",
                        )
                        return subprocess.CompletedProcess(
                            cmd,
                            0,
                            stdout=f"[mesh] run complete: {run_dir}\n",
                            stderr="",
                        )
                    return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")

            runner = SidecarRunner()
            report = riscv_snn_lab.run_ci_sidecar(
                builder_programs=[builder_program],
                toolchain_programs=[toolchain_program],
                lab_root=lab_root,
                runner=runner,
            )

            self.assertTrue(report["gate_ok"])
            self.assertEqual(report["schema_version"], 2)
            self.assertEqual(report["artifact_role"], "stable_top_level_gate")
            self.assertEqual(report["authority_scope"], "experimental_gate_authority")
            self.assertEqual(
                report["derived_from"],
                ["dated_nightly_index", "stable_history_rollup"],
            )
            self.assertEqual(report["gate_name"], "riscv_snn_experimental_nightly")
            self.assertEqual(report["gate_version"], "1.1")
            self.assertEqual(report["required_families"], ["external_dyn_desc_ref"])
            self.assertEqual(report["missing_families"], [])
            self.assertEqual(report["min_count"], 1)
            self.assertTrue(report["nightly_index"]["all_ok"])
            self.assertIsNone(report["history_index"]["latest_date"])
            self.assertEqual(report["history_index"]["count"], 0)
            self.assertTrue(Path(report["report_path"]).exists())
            self.assertTrue(Path(report["history_index"]["summary_path"]).exists())
            self.assertTrue(Path(report["nightly_index"]["summary_path"]).exists())
            self.assertTrue(Path(report["summary_md_path"]).exists())

            summary_md = Path(report["summary_md_path"]).read_text(encoding="utf-8")
            self.assertIn("# riscv_snn experimental nightly sidecar", summary_md)
            self.assertIn("Gate: PASS", summary_md)
            self.assertIn("Authority scope", summary_md)
            self.assertIn("Required families (1)", summary_md)
            self.assertIn("external_dyn_desc_ref", summary_md)
            self.assertIn("Latest recovered date", summary_md)
            self.assertIn("dated nightly index is not the equivalence authority", summary_md)

    def test_run_ci_sidecar_can_attach_equiv_matrix_summary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            nightly_index = {
                "summary_path": str(refs_dir / "nightly-index.json"),
                "count": 1,
                "all_ok": True,
                "families": [
                    {
                        "family": "external_dyn_desc_ref",
                        "builder": {"run_id": "builder-run-001"},
                        "toolchain": {"run_id": "toolchain-run-001"},
                        "audit": {"manifest_match": True, "ok": True},
                    }
                ],
            }
            history_index = {
                "summary_path": str(refs_dir / "nightly-history-index.json"),
                "latest_date": "2026-03-27",
                "first_fail_date": None,
                "first_drift_date": None,
                "latest_recovered_date": "2026-03-27",
                "entries": [],
                "family_history": [],
                "all_ok_latest": True,
            }
            equiv_summary = {
                "schema_version": 1,
                "gate_name": "riscv_snn_equiv_matrix",
                "all_ok": False,
                "count": 1,
                "summary_path": str(refs_dir / "equiv-matrix.json"),
                "families": [
                    {
                        "family": "external_dyn_desc_ref",
                        "status": "FAIL",
                        "summary_path": str(refs_dir / "external-dyn-desc-ref-equiv.json"),
                        "gate_reasons": ["runtime_bridge_completion_visibility_missing"],
                    }
                ],
            }
            report_path = refs_dir / "nightly-sidecar-report.json"

            with mock.patch.object(riscv_snn_lab, "run_nightly", return_value=nightly_index):
                with mock.patch.object(riscv_snn_lab, "refresh_history_index", return_value=history_index):
                    with mock.patch.object(riscv_snn_lab, "run_equiv_matrix", return_value=equiv_summary) as run_equiv_matrix:
                        report = riscv_snn_lab.run_ci_sidecar(
                            builder_programs=["external_dyn_desc_ref"],
                            toolchain_programs=["external_dyn_desc_ref_toolchain"],
                            with_equivalence=True,
                            report_path=report_path,
                            lab_root=lab_root,
                        )

            self.assertFalse(report["gate_ok"])
            self.assertIn("equivalence matrix all_ok is false", report["reasons"])
            self.assertEqual(
                report["derived_from"],
                ["dated_nightly_index", "stable_history_rollup", "dated_equivalence_matrix"],
            )
            self.assertEqual(report["equivalence"]["gate_name"], "riscv_snn_equiv_matrix")
            self.assertFalse(report["equivalence"]["all_ok"])
            self.assertTrue(Path(report["report_path"]).exists())
            self.assertTrue(Path(report["summary_md_path"]).exists())
            summary_md = Path(report["summary_md_path"]).read_text(encoding="utf-8")
            self.assertIn("Authority scope", summary_md)
            self.assertIn("## Equivalence", summary_md)
            self.assertIn("riscv_snn_equiv_matrix", summary_md)
            self.assertIn("runtime_bridge_completion_visibility_missing", summary_md)
            self.assertIn("dated nightly index is not the equivalence authority", summary_md)
            self.assertEqual(
                run_equiv_matrix.call_args.kwargs["families"],
                ["external_dyn_desc_ref"],
            )

    def test_run_ci_sidecar_can_attach_queue_optional_equiv_matrix_nonblocking(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            nightly_index = {
                "summary_path": str(refs_dir / "nightly-index.json"),
                "count": 1,
                "all_ok": True,
                "families": [
                    {
                        "family": "external_dyn_desc_ref",
                        "builder": {"run_id": "builder-run-001"},
                        "toolchain": {"run_id": "toolchain-run-001"},
                        "audit": {"manifest_match": True, "ok": True},
                    }
                ],
            }
            history_index = {
                "summary_path": str(refs_dir / "nightly-history-index.json"),
                "latest_date": "2026-03-27",
                "first_fail_date": None,
                "first_drift_date": None,
                "latest_recovered_date": "2026-03-27",
                "entries": [],
                "family_history": [],
                "all_ok_latest": True,
            }
            queue_equiv_summary = {
                "schema_version": 2,
                "gate_name": "riscv_snn_equiv_matrix",
                "requested_group": "queue_optional",
                "all_ok": False,
                "count": 2,
                "summary_path": str(refs_dir / "equiv-matrix-queue-optional.json"),
                "families": [
                    {
                        "family": "queue_backpressure_ref",
                        "status": "PASS",
                        "summary_path": str(refs_dir / "queue-backpressure-ref-equiv.json"),
                        "gate_reasons": [],
                    },
                    {
                        "family": "completion_queue_overflow_ref",
                        "status": "FAIL",
                        "summary_path": str(refs_dir / "completion-queue-overflow-ref-equiv.json"),
                        "gate_reasons": ["completion_queue_overflow"],
                    },
                ],
            }
            report_path = refs_dir / "nightly-sidecar-report.json"

            with mock.patch.object(riscv_snn_lab, "run_nightly", return_value=nightly_index):
                with mock.patch.object(riscv_snn_lab, "refresh_history_index", return_value=history_index):
                    with mock.patch.object(
                        riscv_snn_lab,
                        "run_equiv_matrix",
                        return_value=queue_equiv_summary,
                    ) as run_equiv_matrix:
                        report = riscv_snn_lab.run_ci_sidecar(
                            builder_programs=["external_dyn_desc_ref"],
                            toolchain_programs=["external_dyn_desc_ref_toolchain"],
                            with_queue_equivalence=True,
                            report_path=report_path,
                            lab_root=lab_root,
                        )

            self.assertTrue(report["gate_ok"])
            self.assertEqual(report["reasons"], [])
            self.assertTrue(report["with_queue_equivalence"])
            self.assertFalse(report["with_equivalence"])
            self.assertEqual(report["queue_equivalence"]["requested_group"], "queue_optional")
            self.assertFalse(report["queue_equivalence"]["all_ok"])
            self.assertEqual(
                report["derived_from"],
                ["dated_nightly_index", "stable_history_rollup", "dated_equivalence_matrix"],
            )
            self.assertTrue(Path(report["report_path"]).exists())
            self.assertTrue(Path(report["summary_md_path"]).exists())
            summary_md = Path(report["summary_md_path"]).read_text(encoding="utf-8")
            self.assertIn("## Queue Optional Equivalence (Non-Blocking)", summary_md)
            self.assertIn("queue_optional", summary_md)
            self.assertIn("completion_queue_overflow", summary_md)
            self.assertEqual(run_equiv_matrix.call_args.kwargs["group"], "queue_optional")
            self.assertIsNone(run_equiv_matrix.call_args.kwargs["families"])

    def test_run_ci_sidecar_can_attach_generic_optional_group_nonblocking(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            nightly_index = {
                "summary_path": str(refs_dir / "nightly-index.json"),
                "count": 1,
                "all_ok": True,
                "families": [
                    {
                        "family": "external_dyn_desc_ref",
                        "builder": {"run_id": "builder-run-001"},
                        "toolchain": {"run_id": "toolchain-run-001"},
                        "audit": {"manifest_match": True, "ok": True},
                    }
                ],
            }
            history_index = {
                "summary_path": str(refs_dir / "nightly-history-index.json"),
                "latest_date": "2026-04-01",
                "first_fail_date": None,
                "first_drift_date": None,
                "latest_recovered_date": "2026-04-01",
                "entries": [],
                "family_history": [],
                "all_ok_latest": True,
            }
            completion_equiv_summary = {
                "schema_version": 2,
                "gate_name": "riscv_snn_equiv_matrix",
                "requested_group": "completion_overflow_optional",
                "all_ok": True,
                "count": 1,
                "summary_path": str(refs_dir / "equiv-matrix-completion-overflow-optional.json"),
                "families": [
                    {
                        "family": "completion_queue_overflow_ref",
                        "status": "PASS",
                        "summary_path": str(refs_dir / "completion-queue-overflow-ref-equiv.json"),
                        "gate_reasons": [],
                    }
                ],
            }
            report_path = refs_dir / "nightly-sidecar-report.json"

            with mock.patch.object(riscv_snn_lab, "run_nightly", return_value=nightly_index):
                with mock.patch.object(riscv_snn_lab, "refresh_history_index", return_value=history_index):
                    with mock.patch.object(
                        riscv_snn_lab,
                        "run_equiv_matrix",
                        return_value=completion_equiv_summary,
                    ) as run_equiv_matrix:
                        report = riscv_snn_lab.run_ci_sidecar(
                            builder_programs=["external_dyn_desc_ref"],
                            toolchain_programs=["external_dyn_desc_ref_toolchain"],
                            with_optional_groups=["completion_overflow_optional"],
                            report_path=report_path,
                            lab_root=lab_root,
                        )

            self.assertTrue(report["gate_ok"])
            self.assertEqual(
                report["optional_group_surfaces"]["completion_overflow_optional"]["requested_group"],
                "completion_overflow_optional",
            )
            self.assertIsNone(report["queue_equivalence"])
            summary_md = Path(report["summary_md_path"]).read_text(encoding="utf-8")
            self.assertIn("## Optional Group Equivalence (Non-Blocking)", summary_md)
            self.assertIn("- Group: `completion_overflow_optional`", summary_md)
            self.assertEqual(
                run_equiv_matrix.call_args.kwargs["group"],
                "completion_overflow_optional",
            )
            self.assertIsNone(run_equiv_matrix.call_args.kwargs["families"])

    def test_run_ci_sidecar_can_attach_nonblocking_abi_audit_summary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            nightly_index = {
                "summary_path": str(refs_dir / "nightly-index.json"),
                "count": 1,
                "all_ok": True,
                "families": [
                    {
                        "family": "external_dyn_desc_ref",
                        "builder": {"run_id": "builder-run-001"},
                        "toolchain": {"run_id": "toolchain-run-001"},
                        "audit": {"manifest_match": True, "ok": True},
                    }
                ],
            }
            history_index = {
                "summary_path": str(refs_dir / "nightly-history-index.json"),
                "latest_date": "2026-03-27",
                "first_fail_date": None,
                "first_drift_date": None,
                "latest_recovered_date": "2026-03-27",
                "entries": [],
                "family_history": [],
                "all_ok_latest": True,
            }
            abi_audit = {
                "schema_version": 2,
                "artifact_role": "dated_abi_authority_audit",
                "all_ok": False,
                "summary_path": str(refs_dir / "abi-audit.json"),
                "generated_include_matches_checked_in": False,
                "toolchain_all_ok": True,
            }
            report_path = refs_dir / "nightly-sidecar-report.json"

            with mock.patch.object(riscv_snn_lab, "run_nightly", return_value=nightly_index):
                with mock.patch.object(riscv_snn_lab, "refresh_history_index", return_value=history_index):
                    with mock.patch.object(riscv_snn_lab, "audit_abi_surface", return_value=abi_audit) as audit_abi_surface:
                        report = riscv_snn_lab.run_ci_sidecar(
                            builder_programs=["external_dyn_desc_ref"],
                            toolchain_programs=["external_dyn_desc_ref_toolchain"],
                            with_abi_audit=True,
                            report_path=report_path,
                            lab_root=lab_root,
                        )

            self.assertTrue(report["gate_ok"])
            self.assertEqual(
                report["derived_from"],
                ["dated_nightly_index", "stable_history_rollup", "dated_abi_authority_audit"],
            )
            self.assertEqual(report["abi_audit"]["summary_path"], str(refs_dir / "abi-audit.json"))
            self.assertFalse(report["abi_audit"]["all_ok"])
            self.assertEqual(report["reasons"], [])
            self.assertTrue(Path(report["report_path"]).exists())
            self.assertTrue(Path(report["summary_md_path"]).exists())
            summary_md = Path(report["summary_md_path"]).read_text(encoding="utf-8")
            self.assertIn("## ABI Audit", summary_md)
            self.assertIn("dated_abi_authority_audit", summary_md)
            self.assertIn("generated_include_matches_checked_in", summary_md)
            self.assertTrue(audit_abi_surface.called)

    def test_run_ci_sidecar_can_attach_full_equivalence_snapshot_nonblocking(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            nightly_index = {
                "summary_path": str(refs_dir / "nightly-index.json"),
                "count": 1,
                "all_ok": True,
                "families": [
                    {
                        "family": "external_dyn_desc_ref",
                        "builder": {"run_id": "builder-run-001"},
                        "toolchain": {"run_id": "toolchain-run-001"},
                        "audit": {"manifest_match": True, "ok": True},
                    }
                ],
            }
            history_index = {
                "summary_path": str(refs_dir / "nightly-history-index.json"),
                "latest_date": "2026-03-27",
                "first_fail_date": None,
                "first_drift_date": None,
                "latest_recovered_date": "2026-03-27",
                "entries": [],
                "family_history": [],
                "all_ok_latest": True,
            }
            full_equiv = {
                "schema_version": 2,
                "artifact_role": "dated_equivalence_matrix",
                "canonical_surface": True,
                "gate_name": "riscv_snn_equiv_matrix",
                "requested_group": "all",
                "all_ok": False,
                "count": 8,
                "summary_path": str(refs_dir / "equiv-matrix.json"),
                "families": [
                    {
                        "family": "external_dyn_desc_ref",
                        "status": "FAIL",
                        "summary_path": str(refs_dir / "external-dyn-desc-ref-equiv.json"),
                        "gate_reasons": ["full_all_snapshot_only"],
                    }
                ],
            }
            report_path = refs_dir / "nightly-sidecar-report.json"

            with mock.patch.object(riscv_snn_lab, "run_nightly", return_value=nightly_index):
                with mock.patch.object(riscv_snn_lab, "refresh_history_index", return_value=history_index):
                    with mock.patch.object(riscv_snn_lab, "run_equiv_matrix", return_value=full_equiv) as run_equiv_matrix:
                        report = riscv_snn_lab.run_ci_sidecar(
                            builder_programs=["external_dyn_desc_ref"],
                            toolchain_programs=["external_dyn_desc_ref_toolchain"],
                            with_full_equivalence=True,
                            report_path=report_path,
                            lab_root=lab_root,
                        )

            self.assertTrue(report["gate_ok"])
            self.assertEqual(report["reasons"], [])
            self.assertTrue(report["with_full_equivalence"])
            self.assertFalse(report["full_equivalence"]["all_ok"])
            self.assertEqual(report["full_equivalence"]["requested_group"], "all")
            self.assertEqual(
                report["derived_from"],
                ["dated_nightly_index", "stable_history_rollup", "dated_equivalence_matrix"],
            )
            summary_md = Path(report["summary_md_path"]).read_text(encoding="utf-8")
            self.assertIn("## Full All Equivalence Snapshot (Non-Blocking)", summary_md)
            self.assertIn("full_all_snapshot_only", summary_md)
            self.assertEqual(run_equiv_matrix.call_args.kwargs["group"], "all")
            self.assertIsNone(run_equiv_matrix.call_args.kwargs["families"])

    def test_run_ci_sidecar_can_attach_artifact_isolation_nonblocking(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            nightly_index = {
                "summary_path": str(refs_dir / "nightly-index.json"),
                "count": 1,
                "all_ok": True,
                "families": [
                    {
                        "family": "external_dyn_desc_ref",
                        "builder": {"run_id": "builder-run-001"},
                        "toolchain": {"run_id": "toolchain-run-001"},
                        "audit": {"manifest_match": True, "ok": True},
                    }
                ],
            }
            history_index = {
                "summary_path": str(refs_dir / "nightly-history-index.json"),
                "latest_date": "2026-03-27",
                "first_fail_date": None,
                "first_drift_date": None,
                "latest_recovered_date": "2026-03-27",
                "entries": [],
                "family_history": [],
                "all_ok_latest": True,
            }
            isolation = {
                "schema_version": 2,
                "artifact_role": "stable_artifact_isolation_check",
                "all_ok": False,
                "summary_path": str(refs_dir / "artifact-isolation-report.json"),
                "surfaces": {
                    "nightly": {
                        "canonical_unchanged": False,
                        "subset_surface": "subset",
                        "subset_summary_path": str(refs_dir / "nightly-index-subset.json"),
                    }
                },
            }
            report_path = refs_dir / "nightly-sidecar-report.json"

            with mock.patch.object(riscv_snn_lab, "run_nightly", return_value=nightly_index):
                with mock.patch.object(riscv_snn_lab, "refresh_history_index", return_value=history_index):
                    with mock.patch.object(riscv_snn_lab, "run_artifact_isolation_check", return_value=isolation) as run_artifact_isolation_check:
                        report = riscv_snn_lab.run_ci_sidecar(
                            builder_programs=["external_dyn_desc_ref"],
                            toolchain_programs=["external_dyn_desc_ref_toolchain"],
                            with_artifact_isolation=True,
                            report_path=report_path,
                            lab_root=lab_root,
                        )

            self.assertTrue(report["gate_ok"])
            self.assertEqual(report["reasons"], [])
            self.assertTrue(report["with_artifact_isolation"])
            self.assertFalse(report["artifact_isolation"]["all_ok"])
            self.assertEqual(
                report["derived_from"],
                ["dated_nightly_index", "stable_history_rollup", "stable_artifact_isolation_check"],
            )
            summary_md = Path(report["summary_md_path"]).read_text(encoding="utf-8")
            self.assertIn("## Artifact Isolation (Non-Blocking)", summary_md)
            self.assertIn("canonical_unchanged", summary_md)
            self.assertTrue(run_artifact_isolation_check.called)

    def test_run_ci_sidecar_can_attach_all_optional_surfaces_together(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            nightly_index = {
                "summary_path": str(refs_dir / "2026-03-27-nightly-index.json"),
                "count": 1,
                "all_ok": True,
                "families": [
                    {
                        "family": "external_dyn_desc_ref",
                        "builder": {"run_id": "builder-run-001"},
                        "toolchain": {"run_id": "toolchain-run-001"},
                        "audit": {"manifest_match": True, "ok": True},
                    }
                ],
            }
            history_index = {
                "summary_path": str(refs_dir / "nightly-history-index.json"),
                "latest_date": "2026-03-27",
                "first_fail_date": None,
                "first_drift_date": None,
                "latest_recovered_date": "2026-03-27",
                "entries": [],
                "family_history": [],
                "all_ok_latest": True,
            }
            full_equiv = {
                "schema_version": 2,
                "gate_name": "riscv_snn_equiv_matrix",
                "requested_group": "all",
                "all_ok": True,
                "count": 1,
                "summary_path": str(refs_dir / "equiv-matrix.json"),
                "families": [
                    {
                        "family": "external_dyn_desc_ref",
                        "status": "PASS",
                        "summary_path": str(refs_dir / "external-dyn-desc-ref-equiv.json"),
                        "gate_reasons": [],
                    }
                ],
            }
            queue_equiv = {
                "schema_version": 2,
                "gate_name": "riscv_snn_equiv_matrix",
                "requested_group": "queue_optional",
                "all_ok": True,
                "count": 2,
                "summary_path": str(refs_dir / "equiv-matrix-queue-optional.json"),
                "families": [
                    {
                        "family": "queue_backpressure_ref",
                        "status": "PASS",
                        "summary_path": str(refs_dir / "queue-backpressure-ref-equiv.json"),
                        "gate_reasons": [],
                    }
                ],
            }
            artifact_isolation = {
                "schema_version": 2,
                "artifact_role": "stable_artifact_isolation_check",
                "all_ok": True,
                "summary_path": str(refs_dir / "artifact-isolation-report.json"),
                "surfaces": {
                    "nightly": {
                        "canonical_unchanged": True,
                        "subset_surface": "subset",
                        "subset_summary_path": str(refs_dir / "nightly-index-subset.json"),
                    }
                },
            }
            abi_audit = {
                "schema_version": 2,
                "artifact_role": "dated_abi_authority_audit",
                "all_ok": True,
                "summary_path": str(refs_dir / "abi-audit.json"),
                "generated_include_matches_checked_in": True,
                "toolchain_all_ok": True,
                "toolchain_programs": [],
            }
            report_path = refs_dir / "nightly-sidecar-report.json"

            with mock.patch.object(riscv_snn_lab, "run_nightly", return_value=nightly_index):
                with mock.patch.object(riscv_snn_lab, "refresh_history_index", return_value=history_index):
                    with mock.patch.object(
                        riscv_snn_lab,
                        "run_equiv_matrix",
                        side_effect=[full_equiv, full_equiv, queue_equiv],
                    ) as run_equiv_matrix:
                        with mock.patch.object(riscv_snn_lab, "audit_abi_surface", return_value=abi_audit):
                            with mock.patch.object(riscv_snn_lab, "run_artifact_isolation_check", return_value=artifact_isolation):
                                report = riscv_snn_lab.run_ci_sidecar(
                                    builder_programs=["external_dyn_desc_ref"],
                                    toolchain_programs=["external_dyn_desc_ref_toolchain"],
                                    with_equivalence=True,
                                    with_full_equivalence=True,
                                    with_queue_equivalence=True,
                                    with_abi_audit=True,
                                    with_artifact_isolation=True,
                                    report_path=report_path,
                                    lab_root=lab_root,
                                )

            self.assertTrue(report["gate_ok"])
            self.assertEqual(
                report["derived_from"],
                [
                    "dated_nightly_index",
                    "stable_history_rollup",
                    "dated_equivalence_matrix",
                    "stable_artifact_isolation_check",
                    "dated_abi_authority_audit",
                ],
            )
            self.assertEqual(report["equivalence"]["requested_group"], "all")
            self.assertEqual(report["full_equivalence"]["requested_group"], "all")
            self.assertEqual(report["queue_equivalence"]["requested_group"], "queue_optional")
            self.assertTrue(report["with_equivalence"])
            self.assertTrue(report["with_full_equivalence"])
            self.assertTrue(report["with_queue_equivalence"])
            self.assertTrue(report["with_abi_audit"])
            self.assertTrue(report["with_artifact_isolation"])
            summary_md = Path(report["summary_md_path"]).read_text(encoding="utf-8")
            self.assertIn("## Equivalence", summary_md)
            self.assertIn("## Full All Equivalence Snapshot (Non-Blocking)", summary_md)
            self.assertIn("## Queue Optional Equivalence (Non-Blocking)", summary_md)
            self.assertIn("## Artifact Isolation (Non-Blocking)", summary_md)
            self.assertIn("## ABI Audit", summary_md)
            self.assertEqual(run_equiv_matrix.call_count, 3)

    def test_build_sidecar_summary_md_marks_canonical_and_subset_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            output_path = td_path / "nightly-sidecar-summary.md"
            report = {
                "generated_utc": "2026-03-28T00:00:00+00:00",
                "gate_ok": True,
                "gate_name": "riscv_snn_experimental_nightly",
                "gate_version": "1.1",
                "artifact_role": "stable_top_level_gate",
                "authority_scope": "experimental_gate_authority",
                "report_path": str(td_path / "nightly-sidecar-report.json"),
                "required_families": ["external_dyn_desc_ref"],
                "missing_families": [],
                "reasons": [],
                "nightly_index": {
                    "summary_path": str(td_path / "2026-03-28-nightly-index.json"),
                    "canonical_surface": True,
                    "count": 6,
                    "families": [],
                },
                "history_index": {
                    "latest_date": "2026-03-28",
                    "first_fail_date": None,
                    "first_drift_date": None,
                    "latest_recovered_date": "2026-03-28",
                    "entries": [],
                },
                "equivalence": {
                    "summary_path": str(td_path / "2026-03-28-equiv-matrix-subset-aaaa1111bbbb.json"),
                    "canonical_surface": False,
                    "requested_group": "all",
                    "all_ok": True,
                    "count": 6,
                    "families": [],
                    "gate_name": "riscv_snn_equiv_matrix",
                },
                "queue_equivalence": {
                    "summary_path": str(td_path / "2026-03-28-equiv-matrix-queue-optional.json"),
                    "canonical_surface": True,
                    "requested_group": "queue_optional",
                    "all_ok": True,
                    "count": 2,
                    "families": [],
                    "gate_name": "riscv_snn_equiv_matrix",
                },
                "full_equivalence": {
                    "summary_path": str(td_path / "2026-03-28-equiv-matrix.json"),
                    "canonical_surface": True,
                    "requested_group": "all",
                    "all_ok": True,
                    "count": 8,
                    "families": [],
                    "gate_name": "riscv_snn_equiv_matrix",
                },
                "artifact_isolation": {
                    "summary_path": str(td_path / "artifact-isolation-report.json"),
                    "all_ok": True,
                    "surfaces": {
                        "nightly": {
                            "canonical_unchanged": True,
                            "subset_surface": "subset",
                            "subset_summary_path": str(td_path / "2026-03-28-nightly-index-subset-e64390052e2e.json"),
                        }
                    },
                },
                "full_equivalence_history": {
                    "summary_path": str(td_path / "full-equivalence-history.json"),
                    "latest_date": "2026-03-28",
                    "entry_count": 2,
                },
                "artifact_isolation_history": {
                    "summary_path": str(td_path / "artifact-isolation-history.json"),
                    "latest_date": "2026-03-28",
                    "entry_count": 1,
                },
                "timing": {
                    "total_elapsed_seconds": 120.5,
                    "blocking_elapsed_seconds": 71.0,
                    "nonblocking_elapsed_seconds": 49.5,
                    "sections": {
                        "full_equivalence_elapsed_seconds": 31.0,
                        "artifact_isolation_elapsed_seconds": 18.5,
                    },
                },
                "abi_audit": None,
            }

            riscv_snn_lab.build_sidecar_summary_md(report, output_path=output_path, lab_root=td_path)
            summary_md = output_path.read_text(encoding="utf-8")

        self.assertIn("- dated family-level equivalence authority surface: `subset`", summary_md)
        self.assertIn("- dated full-all equivalence snapshot surface: `canonical`", summary_md)
        self.assertIn("- dated queue-optional equivalence surface: `canonical`", summary_md)
        self.assertIn("- dated nightly index surface: `canonical`", summary_md)
        self.assertIn("- Surface: `subset`", summary_md)
        self.assertIn("- Surface: `canonical`", summary_md)
        self.assertIn("## Full All Equivalence Snapshot (Non-Blocking)", summary_md)
        self.assertIn("## Artifact Isolation (Non-Blocking)", summary_md)
        self.assertIn("## Runtime Cost", summary_md)
        self.assertIn("- Total elapsed seconds: `120.5`", summary_md)
        self.assertIn("- Non-blocking attachment elapsed seconds: `49.5`", summary_md)
        self.assertIn("full_equivalence", summary_md)
        self.assertIn("artifact_isolation", summary_md)
        self.assertIn("- History path: `", summary_md)

    def test_build_sidecar_summary_md_lists_nonqueue_optional_group_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            output_path = td_path / "nightly-sidecar-summary.md"
            report = {
                "generated_utc": "2026-04-01T00:00:00+00:00",
                "gate_ok": True,
                "gate_name": "riscv_snn_experimental_nightly",
                "gate_version": "1.1",
                "artifact_role": "stable_top_level_gate",
                "authority_scope": "experimental_gate_authority",
                "report_path": str(td_path / "nightly-sidecar-report.json"),
                "observer_summary_path": str(td_path / "nightly-sidecar-observer-summary.json"),
                "required_families": ["external_dyn_desc_ref"],
                "missing_families": [],
                "reasons": [],
                "nightly_index": {
                    "summary_path": str(td_path / "2026-04-01-nightly-index.json"),
                    "canonical_surface": True,
                    "count": 1,
                    "families": [],
                },
                "history_index": {
                    "latest_date": "2026-04-01",
                    "first_fail_date": None,
                    "first_drift_date": None,
                    "latest_recovered_date": "2026-04-01",
                    "entries": [],
                },
                "equivalence": None,
                "queue_equivalence": None,
                "full_equivalence": None,
                "artifact_isolation": None,
                "full_equivalence_history": None,
                "artifact_isolation_history": None,
                "timing": {},
                "abi_audit": None,
                "optional_group_surfaces": {
                    "completion_overflow_optional": {
                        "summary_path": str(td_path / "2026-04-01-equiv-matrix-completion-overflow-optional.json"),
                        "canonical_surface": False,
                        "requested_group": "completion_overflow_optional",
                        "all_ok": True,
                        "count": 1,
                        "families": [],
                        "gate_name": "riscv_snn_equiv_matrix",
                    }
                },
            }

            riscv_snn_lab.build_sidecar_summary_md(report, output_path=output_path, lab_root=td_path)
            summary_md = output_path.read_text(encoding="utf-8")

        self.assertIn("## Optional Group Equivalence (Non-Blocking)", summary_md)
        self.assertIn("- Group: `completion_overflow_optional`", summary_md)
        self.assertIn(
            "- Summary path: `"
            + str(td_path / "2026-04-01-equiv-matrix-completion-overflow-optional.json")
            + "`",
            summary_md,
        )

    def test_build_sidecar_summary_md_includes_runtime_bridge_preflight_rollup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            output_path = td_path / "nightly-sidecar-summary.md"
            report = {
                "generated_utc": "2026-03-30T00:00:00+00:00",
                "stable_surface_refresh": {
                    "refreshed_utc": "2026-03-31T00:00:00+00:00",
                },
                "gate_ok": True,
                "gate_name": "riscv_snn_experimental_nightly",
                "gate_version": "1.1",
                "artifact_role": "stable_top_level_gate",
                "authority_scope": "experimental_gate_authority",
                "report_path": str(td_path / "nightly-sidecar-report.json"),
                "observer_summary_path": str(td_path / "nightly-sidecar-observer-summary.json"),
                "required_families": ["external_dyn_desc_ref"],
                "missing_families": [],
                "reasons": [],
                "nightly_index": {
                    "summary_path": str(td_path / "2026-03-30-nightly-index.json"),
                    "canonical_surface": True,
                    "count": 1,
                    "families": [],
                },
                "history_index": {
                    "latest_date": "2026-03-30",
                    "first_fail_date": None,
                    "first_drift_date": None,
                    "latest_recovered_date": "2026-03-30",
                    "entries": [],
                },
                "equivalence": {
                    "summary_path": str(td_path / "2026-03-30-equiv-matrix.json"),
                    "canonical_surface": True,
                    "requested_group": "all",
                    "all_ok": True,
                    "count": 1,
                    "families": [
                        {
                            "family": "external_dyn_desc_ref",
                            "status": "PASS",
                            "gate_reasons": [],
                            "runtime_bridge_build_preflight_rollup": {
                                "enabled": True,
                                "reporting_scope": "research_only_nonblocking",
                                "status": "ok",
                                "contract_key": "riscv_snn.runtime_bridge.runtime_consumers",
                                "contract_version": 1,
                                "dependency_count": 2,
                                "required_target_count": 9,
                                "stale_target_count": 0,
                                "missing_target_count": 0,
                            },
                        }
                    ],
                    "gate_name": "riscv_snn_equiv_matrix",
                    "runtime_bridge_build_preflight_rollup": {
                        "enabled": True,
                        "reporting_scope": "research_only_nonblocking",
                        "all_ok": True,
                        "family_count": 1,
                        "status_counts": {"ok": 1},
                        "contract_keys": ["riscv_snn.runtime_bridge.runtime_consumers"],
                        "contract_versions": [1],
                        "stale_family_count": 0,
                        "missing_family_count": 0,
                    },
                },
                "queue_equivalence": None,
                "full_equivalence": None,
                "artifact_isolation": None,
                "full_equivalence_history": None,
                "artifact_isolation_history": None,
                "timing": {},
                "abi_audit": None,
            }

            riscv_snn_lab.build_sidecar_summary_md(report, output_path=output_path, lab_root=td_path)
            summary_md = output_path.read_text(encoding="utf-8")

        self.assertIn("Runtime-bridge build preflight (research-only)", summary_md)
        self.assertIn("contract_keys=riscv_snn.runtime_bridge.runtime_consumers", summary_md)
        self.assertIn("status_counts=ok:1", summary_md)
        self.assertIn("- Generated UTC: `2026-03-31T00:00:00+00:00`", summary_md)

    def test_build_sidecar_summary_md_includes_current_mainline_status_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            output_path = td_path / "nightly-sidecar-summary.md"
            report = {
                "generated_utc": "2026-03-31T00:00:00+00:00",
                "gate_ok": True,
                "gate_name": "riscv_snn_experimental_nightly",
                "gate_version": "1.1",
                "artifact_role": "stable_top_level_gate",
                "authority_scope": "experimental_gate_authority",
                "report_path": str(td_path / "nightly-sidecar-report.json"),
                "observer_summary_path": str(td_path / "nightly-sidecar-observer-summary.json"),
                "current_mainline_status_path": str(td_path / "current-mainline-status.md"),
                "required_families": ["external_dyn_desc_ref"],
                "missing_families": [],
                "reasons": [],
                "nightly_index": {
                    "summary_path": str(td_path / "2026-03-31-nightly-index.json"),
                    "canonical_surface": True,
                    "count": 1,
                    "families": [],
                },
                "history_index": {
                    "latest_date": "2026-03-31",
                    "first_fail_date": None,
                    "first_drift_date": None,
                    "latest_recovered_date": "2026-03-31",
                    "entries": [],
                },
            }

            riscv_snn_lab.build_sidecar_summary_md(report, output_path=output_path, lab_root=td_path)
            summary_md = output_path.read_text(encoding="utf-8")

        self.assertIn("- shared current-state rollup: `", summary_md)
        self.assertIn("current-mainline-status.md", summary_md)

    def test_build_sidecar_summary_md_includes_compare_supplementary_surface(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            output_path = td_path / "nightly-sidecar-summary.md"
            report = {
                "generated_utc": "2026-04-07T00:00:00+00:00",
                "gate_ok": True,
                "gate_name": "riscv_snn_experimental_nightly",
                "gate_version": "1.1",
                "artifact_role": "stable_top_level_gate",
                "authority_scope": "experimental_gate_authority",
                "report_path": str(td_path / "nightly-sidecar-report.json"),
                "observer_summary_path": str(td_path / "nightly-sidecar-observer-summary.json"),
                "current_mainline_status_path": str(td_path / "current-mainline-status.md"),
                "required_families": ["external_dyn_desc_ref"],
                "missing_families": [],
                "reasons": [],
                "nightly_index": {
                    "summary_path": str(td_path / "2026-04-07-nightly-index.json"),
                    "canonical_surface": True,
                    "count": 1,
                    "families": [],
                },
                "history_index": {
                    "latest_date": "2026-04-07",
                    "first_fail_date": None,
                    "first_drift_date": None,
                    "latest_recovered_date": "2026-04-07",
                    "entries": [],
                },
                "supplementary_surfaces": {
                    "compare": {
                        "present": True,
                        "gate_ok": True,
                        "latest_date": "2026-04-07",
                        "stale": False,
                        "freshness_mode": "since_latest_recovery",
                        "effective_all_dates_ok": True,
                        "report_path": str(td_path / "compare-nightly-report.json"),
                        "summary_md_path": str(td_path / "compare-nightly-summary.md"),
                        "current_mainline_status_path": str(td_path / "compare-current-status.md"),
                    }
                },
            }

            riscv_snn_lab.build_sidecar_summary_md(report, output_path=output_path, lab_root=td_path)
            summary_md = output_path.read_text(encoding="utf-8")

        self.assertIn("supplementary compare smoke gate", summary_md)
        self.assertIn("## Supplementary Surfaces", summary_md)
        self.assertIn("`compare.gate_ok = True`", summary_md)
        self.assertIn("compare-current-status.md", summary_md)

    def test_build_sidecar_summary_md_includes_reference_program_compare_supplementary_surface(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            output_path = td_path / "nightly-sidecar-summary.md"
            report = {
                "generated_utc": "2026-04-14T00:00:00+00:00",
                "gate_ok": True,
                "gate_name": "riscv_snn_experimental_nightly",
                "gate_version": "1.1",
                "artifact_role": "stable_top_level_gate",
                "authority_scope": "experimental_gate_authority",
                "report_path": str(td_path / "nightly-sidecar-report.json"),
                "observer_summary_path": str(td_path / "nightly-sidecar-observer-summary.json"),
                "current_mainline_status_path": str(td_path / "current-mainline-status.md"),
                "required_families": ["external_dyn_desc_ref"],
                "missing_families": [],
                "reasons": [],
                "nightly_index": {
                    "summary_path": str(td_path / "2026-04-14-nightly-index.json"),
                    "canonical_surface": True,
                    "count": 1,
                    "families": [],
                },
                "history_index": {
                    "latest_date": "2026-04-14",
                    "first_fail_date": None,
                    "first_drift_date": None,
                    "latest_recovered_date": "2026-04-14",
                    "entries": [],
                },
                "supplementary_surfaces": {
                    "reference_program_compare": {
                        "surface_kind": "reference_program_compare_surface",
                        "blocking": False,
                        "present": True,
                        "gate_ok": True,
                        "latest_date": "2026-04-14",
                        "stale": False,
                        "freshness_mode": "reference_program_compare_latest_only",
                        "effective_all_dates_ok": True,
                        "report_path": str(td_path / "reference-program-compare-nightly-report.json"),
                        "summary_md_path": str(td_path / "reference-program-compare-nightly-summary.md"),
                        "current_mainline_status_path": str(td_path / "reference-program-compare-current-status.md"),
                    }
                },
            }

            riscv_snn_lab.build_sidecar_summary_md(report, output_path=output_path, lab_root=td_path)
            summary_md = output_path.read_text(encoding="utf-8")

        self.assertIn("supplementary reference program compare gate", summary_md)
        self.assertIn("`reference_program_compare.gate_ok = True`", summary_md)
        self.assertIn("reference-program-compare-current-status.md", summary_md)

    def test_build_sidecar_summary_md_includes_stable_surface_refresh_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            output_path = td_path / "nightly-sidecar-summary.md"
            report = {
                "generated_utc": "2026-03-31T00:00:00+00:00",
                "gate_ok": True,
                "gate_name": "riscv_snn_experimental_nightly",
                "gate_version": "1.1",
                "artifact_role": "stable_top_level_gate",
                "authority_scope": "experimental_gate_authority",
                "report_path": str(td_path / "nightly-sidecar-report.json"),
                "observer_summary_path": str(td_path / "nightly-sidecar-observer-summary.json"),
                "current_mainline_status_path": str(td_path / "current-mainline-status.md"),
                "required_families": ["external_dyn_desc_ref"],
                "missing_families": [],
                "reasons": [],
                "nightly_index": {
                    "summary_path": str(td_path / "2026-03-31-nightly-index.json"),
                    "canonical_surface": True,
                    "count": 1,
                    "families": [],
                },
                "history_index": {
                    "latest_date": "2026-03-31",
                    "first_fail_date": None,
                    "first_drift_date": None,
                    "latest_recovered_date": "2026-03-31",
                    "entries": [],
                },
                "stable_surface_refresh": {
                    "refreshed_utc": "2026-03-31T00:00:05+00:00",
                    "observer_summary_path": str(td_path / "nightly-sidecar-observer-summary.json"),
                    "current_mainline_status_path": str(td_path / "current-mainline-status.md"),
                    "optional_promotion_dossier_path": str(
                        td_path / "2026-03-31-queue-optional-promotion-dossier.json"
                    ),
                },
            }

            riscv_snn_lab.build_sidecar_summary_md(report, output_path=output_path, lab_root=td_path)
            summary_md = output_path.read_text(encoding="utf-8")

        self.assertIn("stable surface refresh UTC", summary_md)
        self.assertIn("2026-03-31T00:00:05+00:00", summary_md)
        self.assertIn("stable surface refresh current mainline", summary_md)

    def test_nightly_sidecar_main_accepts_with_equivalence(self) -> None:
        expected_report = {
            "report_path": "/tmp/nightly-sidecar-report.json",
            "gate_ok": True,
        }
        with mock.patch.object(nightly_sidecar.riscv_snn_lab, "run_ci_sidecar", return_value=expected_report) as run_ci_sidecar:
            with mock.patch("builtins.print") as print_mock:
                rc = nightly_sidecar.main(["--with-equivalence"])

        self.assertEqual(rc, 0)
        self.assertTrue(run_ci_sidecar.call_args.kwargs["with_equivalence"])
        print_mock.assert_called_once_with("/tmp/nightly-sidecar-report.json")

    def test_nightly_sidecar_main_accepts_with_full_equivalence(self) -> None:
        expected_report = {
            "report_path": "/tmp/nightly-sidecar-report.json",
            "gate_ok": True,
        }
        with mock.patch.object(nightly_sidecar.riscv_snn_lab, "run_ci_sidecar", return_value=expected_report) as run_ci_sidecar:
            with mock.patch("builtins.print") as print_mock:
                rc = nightly_sidecar.main(["--with-full-equivalence"])

        self.assertEqual(rc, 0)
        self.assertTrue(run_ci_sidecar.call_args.kwargs["with_full_equivalence"])
        print_mock.assert_called_once_with("/tmp/nightly-sidecar-report.json")

    def test_nightly_sidecar_main_accepts_with_queue_equivalence(self) -> None:
        expected_report = {
            "report_path": "/tmp/nightly-sidecar-report.json",
            "gate_ok": True,
        }
        with mock.patch.object(nightly_sidecar.riscv_snn_lab, "run_ci_sidecar", return_value=expected_report) as run_ci_sidecar:
            with mock.patch("builtins.print") as print_mock:
                rc = nightly_sidecar.main(["--with-queue-equivalence"])

        self.assertEqual(rc, 0)
        self.assertTrue(run_ci_sidecar.call_args.kwargs["with_queue_equivalence"])
        print_mock.assert_called_once_with("/tmp/nightly-sidecar-report.json")

    def test_nightly_sidecar_main_accepts_with_optional_group(self) -> None:
        expected_report = {
            "report_path": "/tmp/nightly-sidecar-report.json",
            "gate_ok": True,
        }
        with mock.patch.object(nightly_sidecar.riscv_snn_lab, "run_ci_sidecar", return_value=expected_report) as run_ci_sidecar:
            with mock.patch("builtins.print") as print_mock:
                rc = nightly_sidecar.main(["--with-optional-group", "completion_overflow_optional"])

        self.assertEqual(rc, 0)
        self.assertEqual(
            run_ci_sidecar.call_args.kwargs["with_optional_groups"],
            ["completion_overflow_optional"],
        )
        print_mock.assert_called_once_with("/tmp/nightly-sidecar-report.json")

    def test_nightly_sidecar_main_accepts_with_abi_audit(self) -> None:
        expected_report = {
            "report_path": "/tmp/nightly-sidecar-report.json",
            "gate_ok": True,
        }
        with mock.patch.object(nightly_sidecar.riscv_snn_lab, "run_ci_sidecar", return_value=expected_report) as run_ci_sidecar:
            with mock.patch("builtins.print") as print_mock:
                rc = nightly_sidecar.main(["--with-abi-audit"])

        self.assertEqual(rc, 0)
        self.assertTrue(run_ci_sidecar.call_args.kwargs["with_abi_audit"])
        print_mock.assert_called_once_with("/tmp/nightly-sidecar-report.json")

    def test_nightly_sidecar_main_accepts_with_artifact_isolation(self) -> None:
        expected_report = {
            "report_path": "/tmp/nightly-sidecar-report.json",
            "gate_ok": True,
        }
        with mock.patch.object(nightly_sidecar.riscv_snn_lab, "run_ci_sidecar", return_value=expected_report) as run_ci_sidecar:
            with mock.patch("builtins.print") as print_mock:
                rc = nightly_sidecar.main(["--with-artifact-isolation"])

        self.assertEqual(rc, 0)
        self.assertTrue(run_ci_sidecar.call_args.kwargs["with_artifact_isolation"])
        print_mock.assert_called_once_with("/tmp/nightly-sidecar-report.json")

    def test_main_sidecar_accepts_with_queue_equivalence(self) -> None:
        expected_report = {
            "report_path": "/tmp/nightly-sidecar-report.json",
            "gate_ok": True,
        }
        with mock.patch.object(riscv_snn_lab, "run_ci_sidecar", return_value=expected_report) as run_ci_sidecar:
            with mock.patch("builtins.print") as print_mock:
                rc = riscv_snn_lab.main(["sidecar", "--with-queue-equivalence"])

        self.assertEqual(rc, 0)
        self.assertTrue(run_ci_sidecar.call_args.kwargs["with_queue_equivalence"])
        print_mock.assert_called_once_with("/tmp/nightly-sidecar-report.json")

    def test_main_sidecar_accepts_with_optional_group(self) -> None:
        expected_report = {
            "report_path": "/tmp/nightly-sidecar-report.json",
            "gate_ok": True,
        }
        with mock.patch.object(riscv_snn_lab, "run_ci_sidecar", return_value=expected_report) as run_ci_sidecar:
            with mock.patch("builtins.print") as print_mock:
                rc = riscv_snn_lab.main(["sidecar", "--with-optional-group", "completion_overflow_optional"])

        self.assertEqual(rc, 0)
        self.assertEqual(
            run_ci_sidecar.call_args.kwargs["with_optional_groups"],
            ["completion_overflow_optional"],
        )
        print_mock.assert_called_once_with("/tmp/nightly-sidecar-report.json")

    def test_main_sidecar_accepts_with_full_equivalence(self) -> None:
        expected_report = {
            "report_path": "/tmp/nightly-sidecar-report.json",
            "gate_ok": True,
        }
        with mock.patch.object(riscv_snn_lab, "run_ci_sidecar", return_value=expected_report) as run_ci_sidecar:
            with mock.patch("builtins.print") as print_mock:
                rc = riscv_snn_lab.main(["sidecar", "--with-full-equivalence"])

        self.assertEqual(rc, 0)
        self.assertTrue(run_ci_sidecar.call_args.kwargs["with_full_equivalence"])
        print_mock.assert_called_once_with("/tmp/nightly-sidecar-report.json")

    def test_main_sidecar_accepts_with_artifact_isolation(self) -> None:
        expected_report = {
            "report_path": "/tmp/nightly-sidecar-report.json",
            "gate_ok": True,
        }
        with mock.patch.object(riscv_snn_lab, "run_ci_sidecar", return_value=expected_report) as run_ci_sidecar:
            with mock.patch("builtins.print") as print_mock:
                rc = riscv_snn_lab.main(["sidecar", "--with-artifact-isolation"])

        self.assertEqual(rc, 0)
        self.assertTrue(run_ci_sidecar.call_args.kwargs["with_artifact_isolation"])
        print_mock.assert_called_once_with("/tmp/nightly-sidecar-report.json")

    def test_run_artifact_isolation_check_preserves_canonical_dated_paths(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            canonical_builder = refs_dir / "2026-03-28-builder-regress-matrix.json"
            canonical_toolchain = refs_dir / "2026-03-28-toolchain-regress-matrix.json"
            canonical_audit = refs_dir / "2026-03-28-toolchain-bridge-audit.json"
            canonical_nightly = refs_dir / "2026-03-28-nightly-index.json"
            for path in (canonical_builder, canonical_toolchain, canonical_audit, canonical_nightly):
                path.write_text(json.dumps({"seed": path.name}), encoding="utf-8")

            def fake_run_matrix(group: str = "all", **kwargs: object) -> dict[str, object]:
                summary_path = Path(str(kwargs["summary_path"]))
                summary_path.write_text(json.dumps({"group": group}), encoding="utf-8")
                return {"summary_path": str(summary_path), "canonical_surface": False, "group": group}

            def fake_audit_programs(group: str = "all", **kwargs: object) -> dict[str, object]:
                summary_path = Path(str(kwargs["summary_path"]))
                summary_path.write_text(json.dumps({"group": group, "all_ok": True}), encoding="utf-8")
                return {"summary_path": str(summary_path), "canonical_surface": False, "group": group, "all_ok": True}

            def fake_run_nightly(**kwargs: object) -> dict[str, object]:
                summary_path = Path(str(kwargs["summary_path"]))
                summary_path.write_text(json.dumps({"all_ok": True, "count": 1}), encoding="utf-8")
                return {"summary_path": str(summary_path), "canonical_surface": False, "count": 1, "all_ok": True}

            with mock.patch.object(riscv_snn_lab, "run_matrix", side_effect=fake_run_matrix):
                with mock.patch.object(riscv_snn_lab, "audit_programs", side_effect=fake_audit_programs):
                    with mock.patch.object(riscv_snn_lab, "run_nightly", side_effect=fake_run_nightly):
                        report = riscv_snn_lab.run_artifact_isolation_check(lab_root=lab_root)

            self.assertTrue(report["all_ok"])
            self.assertEqual(report["artifact_role"], "stable_artifact_isolation_check")
            self.assertEqual(set(report["surfaces"]), {"builder", "toolchain", "toolchain_audit", "nightly"})
            self.assertTrue(report["surfaces"]["builder"]["canonical_unchanged"])
            self.assertTrue(report["surfaces"]["toolchain"]["canonical_unchanged"])
            self.assertTrue(report["surfaces"]["toolchain_audit"]["canonical_unchanged"])
            self.assertTrue(report["surfaces"]["nightly"]["canonical_unchanged"])
            self.assertEqual(
                report["summary_path"],
                str(refs_dir / "artifact-isolation-report.json"),
            )
            self.assertIn("-subset-", Path(report["surfaces"]["builder"]["subset_summary_path"]).name)
            self.assertIn("-subset-", Path(report["surfaces"]["toolchain"]["subset_summary_path"]).name)
            self.assertIn("-subset-", Path(report["surfaces"]["toolchain_audit"]["subset_summary_path"]).name)
            self.assertIn("-subset-", Path(report["surfaces"]["nightly"]["subset_summary_path"]).name)
            persisted = json.loads((refs_dir / "artifact-isolation-report.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary_path"], str(refs_dir / "artifact-isolation-report.json"))

    def test_refresh_full_equivalence_history_rollup_tracks_multi_date_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            (refs_dir / "2026-03-27-equiv-matrix.json").write_text(
                json.dumps(
                    {
                        "artifact_role": "dated_equivalence_matrix",
                        "canonical_surface": False,
                        "requested_group": "all",
                        "all_ok": True,
                        "count": 7,
                        "families": [
                            {"family": "barrier_wfi_order_ref"},
                            {"family": "external_dyn_desc_ref"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (refs_dir / "2026-03-28-equiv-matrix.json").write_text(
                json.dumps(
                    {
                        "artifact_role": "dated_equivalence_matrix",
                        "canonical_surface": True,
                        "requested_group": "all",
                        "all_ok": True,
                        "count": 8,
                        "families": [
                            {"family": "barrier_wfi_order_ref"},
                            {"family": "completion_queue_overflow_ref"},
                            {"family": "external_dyn_desc_ref"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            history = riscv_snn_lab.refresh_full_equivalence_history(lab_root=lab_root)

        self.assertEqual(history["artifact_role"], "stable_full_equivalence_history")
        self.assertEqual(history["history_contract"], "canonical_full_all_only")
        self.assertEqual(history["latest_date"], "2026-03-28")
        self.assertEqual(history["entry_count"], 1)
        self.assertTrue(history["all_dates_ok"])
        self.assertEqual(history["entries"][0]["added_families_vs_previous"], [])
        self.assertEqual(len(history["excluded_entries"]), 1)
        self.assertEqual(history["excluded_entries"][0]["date"], "2026-03-27")
        self.assertEqual(history["excluded_entries"][0]["reason"], "non_canonical_surface")
        self.assertEqual(
            history["summary_path"],
            str(refs_dir / "full-equivalence-history.json"),
        )

    def test_refresh_optional_equivalence_history_rollup_tracks_multi_date_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            for date_str in ("2026-03-27", "2026-03-28", "2026-03-29"):
                (refs_dir / f"{date_str}-equiv-matrix-queue-optional.json").write_text(
                    json.dumps(
                        {
                            "artifact_role": "dated_equivalence_matrix",
                            "canonical_surface": True,
                            "requested_group": "queue_optional",
                            "all_ok": True,
                            "count": 2,
                            "families": [
                                {"family": "completion_queue_overflow_ref"},
                                {"family": "queue_backpressure_ref"},
                            ],
                        }
                    ),
                    encoding="utf-8",
                )

            history = riscv_snn_lab.refresh_optional_equivalence_history(
                group="queue_optional",
                lab_root=lab_root,
            )

        self.assertEqual(history["artifact_role"], "stable_optional_equivalence_history")
        self.assertEqual(history["group"], "queue_optional")
        self.assertEqual(history["history_contract"], "canonical_queue_optional_only")
        self.assertEqual(history["latest_date"], "2026-03-29")
        self.assertEqual(history["entry_count"], 3)
        self.assertTrue(history["all_ok_latest"])
        self.assertTrue(history["all_dates_ok"])
        self.assertEqual(
            history["summary_path"],
            str(refs_dir / "queue-optional-equivalence-history.json"),
        )

    def test_refresh_optional_equivalence_history_can_compact_reset_with_curated_samples(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            history_path = refs_dir / "queue-optional-equivalence-history.json"
            history_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_optional_equivalence_history",
                        "group": "queue_optional",
                        "history_contract": "canonical_queue_optional_only",
                        "entry_count": 2,
                        "all_dates_ok": False,
                        "latest_date": "2026-04-01",
                        "latest_summary_path": str(refs_dir / "2026-04-01-equiv-matrix-queue-optional.json"),
                        "entries": [
                            {
                                "date": "2026-04-01",
                                "summary_path": str(refs_dir / "2026-04-01-equiv-matrix-queue-optional.json"),
                                "generated_utc": "2026-04-01T00:00:00+00:00",
                                "source_kind": "group_matrix",
                                "canonical_surface": True,
                                "requested_group": "queue_optional",
                                "count": 2,
                                "all_ok": False,
                                "family_names": [
                                    "completion_queue_overflow_ref",
                                    "queue_backpressure_ref",
                                ],
                            },
                            {
                                "date": "2026-03-29",
                                "summary_path": str(refs_dir / "2026-03-29-equiv-matrix-queue-optional.json"),
                                "generated_utc": "2026-03-29T00:00:00+00:00",
                                "source_kind": "group_matrix",
                                "canonical_surface": True,
                                "requested_group": "queue_optional",
                                "count": 2,
                                "all_ok": True,
                                "family_names": [
                                    "completion_queue_overflow_ref",
                                    "queue_backpressure_ref",
                                ],
                            },
                        ],
                        "excluded_entries": [],
                        "summary_path": str(history_path),
                    }
                ),
                encoding="utf-8",
            )
            sample_0329 = refs_dir / "2026-03-29-equiv-matrix-queue-optional.json"
            sample_0402 = refs_dir / "2026-04-02-equiv-matrix-queue-optional.json"
            for sample_path, generated_utc in (
                (sample_0329, "2026-03-29T00:00:00+00:00"),
                (sample_0402, "2026-04-02T00:00:00+00:00"),
            ):
                sample_path.write_text(
                    json.dumps(
                        {
                            "artifact_role": "dated_equivalence_matrix",
                            "canonical_surface": True,
                            "requested_group": "queue_optional",
                            "generated_utc": generated_utc,
                            "all_ok": True,
                            "count": 2,
                            "families": [
                                {"family": "completion_queue_overflow_ref"},
                                {"family": "queue_backpressure_ref"},
                            ],
                            "summary_path": str(sample_path),
                        }
                    ),
                    encoding="utf-8",
                )

            history = riscv_snn_lab.refresh_optional_equivalence_history(
                group="queue_optional",
                sample_paths=[sample_0329, sample_0402],
                reset_existing=True,
                lab_root=lab_root,
            )

        self.assertEqual(history["entry_count"], 2)
        self.assertTrue(history["all_dates_ok"])
        self.assertIsNone(history["first_fail_date"])
        self.assertEqual(history["latest_date"], "2026-04-02")

    def test_refresh_optional_equivalence_history_can_compact_since_latest_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            for date_str, all_ok in (
                ("2026-03-29", True),
                ("2026-04-01", False),
                ("2026-04-02", True),
                ("2026-04-03", True),
            ):
                sample_path = refs_dir / f"{date_str}-equiv-matrix-queue-optional.json"
                sample_path.write_text(
                    json.dumps(
                        {
                            "artifact_role": "dated_equivalence_matrix",
                            "canonical_surface": True,
                            "requested_group": "queue_optional",
                            "generated_utc": f"{date_str}T00:00:00+00:00",
                            "all_ok": all_ok,
                            "count": 2,
                            "families": [
                                {"family": "completion_queue_overflow_ref"},
                                {"family": "queue_backpressure_ref"},
                            ],
                            "summary_path": str(sample_path),
                        }
                    ),
                    encoding="utf-8",
                )

            history = riscv_snn_lab.refresh_optional_equivalence_history(
                group="queue_optional",
                compact_since_latest_recovery=True,
                lab_root=lab_root,
            )

        self.assertEqual(history["refresh_mode"], "compact_latest_recovery")
        self.assertEqual(history["entry_count"], 2)
        self.assertTrue(history["all_dates_ok"])
        self.assertEqual(history["latest_date"], "2026-04-03")
        self.assertEqual(
            [row["date"] for row in history["entries"]],
            ["2026-04-03", "2026-04-02"],
        )
        self.assertIsNone(history["first_fail_date"])

    def test_optional_history_surface_rebuilds_singleton_group_when_authority_requires_recovery_compaction(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            spec_dir = lab_root / "spec_authority"
            refs_dir.mkdir(parents=True, exist_ok=True)
            spec_dir.mkdir(parents=True, exist_ok=True)
            (spec_dir / "riscv_snn_mainline_gate_v1.json").write_text(
                json.dumps(
                    {
                        "required_families": ["external_dyn_desc_ref"],
                        "optional_groups": {
                            "completion_overflow_optional": {
                                "families": ["completion_queue_overflow_ref"],
                                "blocking": False,
                            }
                        },
                        "promotion_contract": {
                            "completion_overflow_optional": {
                                "requires_family_equiv_pass": True,
                                "requires_multi_date_freshness": True,
                                "multi_date_freshness_mode": "since_latest_recovery",
                                "requires_reason_taxonomy_clean": True,
                                "requires_explicit_review": True,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            sample_payloads = {
                "2026-04-02": False,
                "2026-04-03": True,
                "2026-04-04": True,
            }
            latest_family_path = None
            for date_str, all_ok in sample_payloads.items():
                sample_path = refs_dir / f"{date_str}-completion-queue-overflow-ref-equiv.json"
                sample_path.write_text(
                    json.dumps(
                        {
                            "family": "completion_queue_overflow_ref",
                            "generated_utc": f"{date_str}T00:00:00+00:00",
                            "status": "PASS" if all_ok else "FAIL",
                            "summary_path": str(sample_path),
                        }
                    ),
                    encoding="utf-8",
                )
                latest_family_path = sample_path

            history_path = refs_dir / "completion-overflow-optional-equivalence-history.json"
            history_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_optional_equivalence_history",
                        "group": "completion_overflow_optional",
                        "history_contract": "canonical_completion_overflow_optional_only",
                        "refresh_mode": "dated_scan",
                        "summary_path": str(history_path),
                        "latest_summary_path": str(latest_family_path),
                        "latest_date": "2026-04-04",
                        "entry_count": 3,
                        "all_ok_latest": True,
                        "all_dates_ok": False,
                        "first_fail_date": "2026-04-02",
                        "latest_recovered_date": "2026-04-03",
                        "entries": [
                            {
                                "date": "2026-04-04",
                                "all_ok": True,
                                "summary_path": str(refs_dir / "2026-04-04-completion-queue-overflow-ref-equiv.json"),
                            },
                            {
                                "date": "2026-04-03",
                                "all_ok": True,
                                "summary_path": str(refs_dir / "2026-04-03-completion-queue-overflow-ref-equiv.json"),
                            },
                            {
                                "date": "2026-04-02",
                                "all_ok": False,
                                "summary_path": str(refs_dir / "2026-04-02-completion-queue-overflow-ref-equiv.json"),
                            },
                        ],
                        "excluded_entries": [],
                        "excluded_entry_count": 0,
                    }
                ),
                encoding="utf-8",
            )

            history = riscv_snn_lab._optional_history_surface(
                group="completion_overflow_optional",
                lab_root=lab_root,
            )

        self.assertEqual(history["refresh_mode"], "compact_latest_recovery")
        self.assertEqual(history["entry_count"], 2)
        self.assertTrue(history["all_dates_ok"])
        self.assertEqual(
            [row["date"] for row in history["entries"]],
            ["2026-04-04", "2026-04-03"],
        )
        self.assertEqual(history["excluded_entry_count"], 1)

    def test_refresh_optional_equivalence_history_can_derive_singleton_group_from_family_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            spec_dir = lab_root / "spec_authority"
            refs_dir.mkdir(parents=True, exist_ok=True)
            spec_dir.mkdir(parents=True, exist_ok=True)
            (spec_dir / "riscv_snn_mainline_gate_v1.json").write_text(
                json.dumps(
                    {
                        "required_families": ["external_dyn_desc_ref"],
                        "optional_groups": {
                            "completion_overflow_optional": {
                                "families": ["completion_queue_overflow_ref"],
                                "blocking": False,
                            }
                        },
                        "promotion_contract": {
                            "completion_overflow_optional": {
                                "requires_family_equiv_pass": True,
                                "requires_multi_date_freshness": True,
                                "requires_reason_taxonomy_clean": True,
                                "requires_explicit_review": True,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            for date_str in ("2026-03-28", "2026-03-29"):
                (refs_dir / f"{date_str}-completion-queue-overflow-ref-equiv.json").write_text(
                    json.dumps(
                        {
                            "family": "completion_queue_overflow_ref",
                            "generated_utc": f"{date_str}T00:00:00+00:00",
                            "status": "PASS",
                            "summary_path": str(refs_dir / f"{date_str}-completion-queue-overflow-ref-equiv.json"),
                        }
                    ),
                    encoding="utf-8",
                )

            history = riscv_snn_lab.refresh_optional_equivalence_history(
                group="completion_overflow_optional",
                lab_root=lab_root,
            )

        self.assertEqual(history["group"], "completion_overflow_optional")
        self.assertEqual(history["history_contract"], "canonical_completion_overflow_optional_only")
        self.assertEqual(history["latest_date"], "2026-03-29")
        self.assertEqual(history["entry_count"], 2)
        self.assertTrue(history["all_ok_latest"])
        self.assertTrue(history["all_dates_ok"])

    def test_singleton_optional_group_prefers_newer_family_surface_over_stale_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            spec_dir = lab_root / "spec_authority"
            refs_dir.mkdir(parents=True, exist_ok=True)
            spec_dir.mkdir(parents=True, exist_ok=True)
            (spec_dir / "riscv_snn_mainline_gate_v1.json").write_text(
                json.dumps(
                    {
                        "required_families": ["external_dyn_desc_ref"],
                        "optional_groups": {
                            "completion_overflow_optional": {
                                "families": ["completion_queue_overflow_ref"],
                                "blocking": False,
                            }
                        },
                        "promotion_contract": {
                            "completion_overflow_optional": {
                                "requires_family_equiv_pass": True,
                                "requires_multi_date_freshness": True,
                                "requires_reason_taxonomy_clean": True,
                                "requires_explicit_review": True,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            matrix_path = refs_dir / "2026-04-01-equiv-matrix-completion-overflow-optional.json"
            family_path = refs_dir / "2026-04-01-completion-queue-overflow-ref-equiv.json"
            matrix_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "dated_equivalence_matrix",
                        "canonical_surface": True,
                        "requested_group": "completion_overflow_optional",
                        "generated_utc": "2026-04-01T04:00:00+00:00",
                        "all_ok": False,
                        "count": 1,
                        "families": [
                            {
                                "family": "completion_queue_overflow_ref",
                                "status": "FAIL",
                                "summary_path": str(family_path),
                            }
                        ],
                        "summary_path": str(matrix_path),
                    }
                ),
                encoding="utf-8",
            )
            family_path.write_text(
                json.dumps(
                    {
                        "family": "completion_queue_overflow_ref",
                        "generated_utc": "2026-04-01T05:00:00+00:00",
                        "status": "PASS",
                        "summary_path": str(family_path),
                    }
                ),
                encoding="utf-8",
            )

            history = riscv_snn_lab.refresh_optional_equivalence_history(
                group="completion_overflow_optional",
                lab_root=lab_root,
            )
            surface, surface_path = riscv_snn_lab._latest_optional_group_equivalence_surface(
                group="completion_overflow_optional",
                lab_root=lab_root,
            )

        self.assertEqual(history["entry_count"], 1)
        self.assertTrue(history["all_ok_latest"])
        self.assertEqual(history["latest_summary_path"], str(family_path))
        self.assertIsNotNone(surface)
        self.assertEqual(surface_path, family_path)
        self.assertTrue(surface["all_ok"])
        self.assertEqual(surface["summary_path"], str(family_path))
        self.assertEqual(surface["source_kind"], "singleton_family_equivalence")

    def test_family_admission_audit_prefers_fresher_singleton_family_over_same_day_group_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            spec_dir = lab_root / "spec_authority"
            refs_dir.mkdir(parents=True, exist_ok=True)
            spec_dir.mkdir(parents=True, exist_ok=True)
            (spec_dir / "riscv_snn_mainline_gate_v1.json").write_text(
                json.dumps(
                    {
                        "required_families": ["external_dyn_desc_ref"],
                        "optional_groups": {
                            "completion_overflow_optional": {
                                "families": ["completion_queue_overflow_ref"],
                                "blocking": False,
                            }
                        },
                        "promotion_contract": {
                            "completion_overflow_optional": {
                                "requires_family_equiv_pass": True,
                                "requires_multi_date_freshness": False,
                                "requires_reason_taxonomy_clean": True,
                                "requires_explicit_review": True,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            matrix_path = refs_dir / "2026-04-01-equiv-matrix-completion-overflow-optional.json"
            family_path = refs_dir / "2026-04-01-completion-queue-overflow-ref-equiv.json"
            matrix_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "dated_equivalence_matrix",
                        "canonical_surface": True,
                        "requested_group": "completion_overflow_optional",
                        "generated_utc": "2026-04-01T04:00:00+00:00",
                        "all_ok": False,
                        "count": 1,
                        "families": [
                            {
                                "family": "completion_queue_overflow_ref",
                                "status": "FAIL",
                                "summary_path": str(family_path),
                            }
                        ],
                        "summary_path": str(matrix_path),
                    }
                ),
                encoding="utf-8",
            )
            family_path.write_text(
                json.dumps(
                    {
                        "family": "completion_queue_overflow_ref",
                        "generated_utc": "2026-04-01T05:00:00+00:00",
                        "status": "PASS",
                        "summary_path": str(family_path),
                    }
                ),
                encoding="utf-8",
            )
            (refs_dir / "nightly-sidecar-report.json").write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "gate_ok": True,
                        "required_families": ["external_dyn_desc_ref"],
                    }
                ),
                encoding="utf-8",
            )
            (refs_dir / "nightly-history-index.json").write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_history_rollup",
                        "latest_date": "2026-04-01",
                    }
                ),
                encoding="utf-8",
            )
            review_path = refs_dir / "2026-04-01-completion-overflow-optional-review.json"
            review_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "dated_optional_group_review",
                        "group": "completion_overflow_optional",
                        "families": ["completion_queue_overflow_ref"],
                        "reviewer": "lab-owner",
                        "decision": "approved",
                        "review_date": "2026-04-01",
                    }
                ),
                encoding="utf-8",
            )

            summary = riscv_snn_lab.run_family_admission_audit(
                group="completion_overflow_optional",
                lab_root=lab_root,
            )

        self.assertTrue(summary["group_equivalence_all_ok"])
        self.assertTrue(summary["promotion_ready"])
        self.assertEqual(summary["group_equivalence_path"], str(family_path))
        self.assertEqual(summary["explicit_review_path"], str(review_path))

    def test_family_admission_audit_uses_queue_history_and_explicit_review(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            for date_str in ("2026-03-28", "2026-03-29"):
                (refs_dir / f"{date_str}-equiv-matrix-queue-optional.json").write_text(
                    json.dumps(
                        {
                            "artifact_role": "dated_equivalence_matrix",
                            "canonical_surface": True,
                            "requested_group": "queue_optional",
                            "all_ok": True,
                            "count": 2,
                            "families": [
                                {"family": "completion_queue_overflow_ref"},
                                {"family": "queue_backpressure_ref"},
                            ],
                        }
                    ),
                    encoding="utf-8",
                )

            (refs_dir / "nightly-sidecar-report.json").write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "gate_ok": True,
                        "required_families": riscv_snn_lab.authority_required_families(),
                    }
                ),
                encoding="utf-8",
            )
            (refs_dir / "nightly-history-index.json").write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_history_rollup",
                        "latest_date": "2026-03-29",
                    }
                ),
                encoding="utf-8",
            )
            review_path = refs_dir / "2026-03-30-queue-optional-review.json"
            review_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "dated_optional_group_review",
                        "group": "queue_optional",
                        "families": [
                            "completion_queue_overflow_ref",
                            "queue_backpressure_ref",
                        ],
                        "reviewer": "lab-owner",
                        "decision": "approved",
                        "review_date": "2026-03-30",
                    }
                ),
                encoding="utf-8",
            )

            summary = riscv_snn_lab.run_family_admission_audit(group="queue_optional", lab_root=lab_root)

        self.assertEqual(summary["group"], "queue_optional")
        self.assertFalse(summary["blocking"])
        self.assertTrue(summary["promotion_ready"])
        self.assertEqual(summary["reasons"], [])
        self.assertEqual(
            summary["contract_primary"],
            riscv_snn_lab.OPTIONAL_ADMISSION_PRIMARY_CONTRACT,
        )
        self.assertEqual(
            summary["primary_contract_fields"],
            list(riscv_snn_lab.OPTIONAL_ADMISSION_PRIMARY_FIELDS),
        )
        self.assertEqual(
            summary["compatibility_aliases"]["queue_optional"],
            list(riscv_snn_lab.QUEUE_OPTIONAL_ADMISSION_ALIAS_FIELDS),
        )
        self.assertTrue(summary["group_equivalence_all_ok"])
        self.assertEqual(summary["group_history_entry_count"], 2)
        self.assertTrue(summary["group_history_all_dates_ok"])
        self.assertTrue(summary["queue_history_available"])
        self.assertEqual(summary["queue_history_entry_count"], 2)
        self.assertTrue(summary["queue_history_all_dates_ok"])
        self.assertEqual(summary["queue_equivalence_path"], summary["group_equivalence_path"])
        self.assertEqual(summary["queue_history_path"], summary["group_history_path"])
        self.assertEqual(summary["explicit_review_path"], str(review_path))
        self.assertTrue(summary["explicit_review_ok"])

    def test_family_admission_audit_prefers_current_compacted_optional_history(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            spec_dir = lab_root / "spec_authority"
            refs_dir.mkdir(parents=True, exist_ok=True)
            spec_dir.mkdir(parents=True, exist_ok=True)
            (spec_dir / "riscv_snn_mainline_gate_v1.json").write_text(
                json.dumps(
                    {
                        "required_families": ["external_dyn_desc_ref"],
                        "optional_groups": {
                            "queue_optional": {
                                "families": [
                                    "completion_queue_overflow_ref",
                                    "queue_backpressure_ref",
                                ],
                                "blocking": False,
                            }
                        },
                        "promotion_contract": {
                            "queue_optional": {
                                "requires_family_equiv_pass": True,
                                "requires_multi_date_freshness": True,
                                "requires_reason_taxonomy_clean": True,
                                "requires_explicit_review": True,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            bad_matrix_path = refs_dir / "2026-04-01-equiv-matrix-queue-optional.json"
            latest_matrix_path = refs_dir / "2026-04-02-equiv-matrix-queue-optional.json"
            good_matrix_path = refs_dir / "2026-03-29-equiv-matrix-queue-optional.json"
            for path, generated_utc, all_ok in (
                (good_matrix_path, "2026-03-29T00:00:00+00:00", True),
                (bad_matrix_path, "2026-04-01T00:00:00+00:00", False),
                (latest_matrix_path, "2026-04-02T00:00:00+00:00", True),
            ):
                path.write_text(
                    json.dumps(
                        {
                            "artifact_role": "dated_equivalence_matrix",
                            "canonical_surface": True,
                            "requested_group": "queue_optional",
                            "generated_utc": generated_utc,
                            "all_ok": all_ok,
                            "count": 2,
                            "families": [
                                {"family": "completion_queue_overflow_ref"},
                                {"family": "queue_backpressure_ref"},
                            ],
                            "summary_path": str(path),
                        }
                    ),
                    encoding="utf-8",
                )
            history_path = refs_dir / "queue-optional-equivalence-history.json"
            history_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_optional_equivalence_history",
                        "group": "queue_optional",
                        "history_contract": "canonical_queue_optional_only",
                        "entry_count": 2,
                        "excluded_entry_count": 0,
                        "latest_date": "2026-04-02",
                        "latest_summary_path": str(latest_matrix_path),
                        "all_ok_latest": True,
                        "all_dates_ok": True,
                        "first_fail_date": None,
                        "latest_recovered_date": "2026-04-02",
                        "entries": [
                            {
                                "date": "2026-04-02",
                                "summary_path": str(latest_matrix_path),
                                "generated_utc": "2026-04-02T00:00:00+00:00",
                                "source_kind": "group_matrix",
                                "canonical_surface": True,
                                "requested_group": "queue_optional",
                                "count": 2,
                                "all_ok": True,
                                "family_names": [
                                    "completion_queue_overflow_ref",
                                    "queue_backpressure_ref",
                                ],
                            },
                            {
                                "date": "2026-03-29",
                                "summary_path": str(good_matrix_path),
                                "generated_utc": "2026-03-29T00:00:00+00:00",
                                "source_kind": "group_matrix",
                                "canonical_surface": True,
                                "requested_group": "queue_optional",
                                "count": 2,
                                "all_ok": True,
                                "family_names": [
                                    "completion_queue_overflow_ref",
                                    "queue_backpressure_ref",
                                ],
                            },
                        ],
                        "excluded_entries": [],
                        "summary_path": str(history_path),
                    }
                ),
                encoding="utf-8",
            )
            (refs_dir / "nightly-sidecar-report.json").write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "gate_ok": True,
                        "required_families": ["external_dyn_desc_ref"],
                    }
                ),
                encoding="utf-8",
            )
            (refs_dir / "nightly-history-index.json").write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_history_rollup",
                        "latest_date": "2026-04-02",
                    }
                ),
                encoding="utf-8",
            )
            review_path = refs_dir / "2026-04-02-queue-optional-review.json"
            review_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "dated_optional_group_review",
                        "group": "queue_optional",
                        "families": [
                            "completion_queue_overflow_ref",
                            "queue_backpressure_ref",
                        ],
                        "reviewer": "lab-owner",
                        "decision": "approved",
                        "review_date": "2026-04-02",
                    }
                ),
                encoding="utf-8",
            )

            summary = riscv_snn_lab.run_family_admission_audit(group="queue_optional", lab_root=lab_root)

        self.assertTrue(summary["promotion_ready"])
        self.assertTrue(summary["group_history_all_dates_ok"])
        self.assertEqual(summary["group_history_path"], str(history_path))
        self.assertEqual(summary["explicit_review_path"], str(review_path))

    def test_family_admission_audit_can_treat_recovered_queue_history_as_freshness_green(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            spec_dir = lab_root / "spec_authority"
            refs_dir.mkdir(parents=True, exist_ok=True)
            spec_dir.mkdir(parents=True, exist_ok=True)
            (spec_dir / "riscv_snn_mainline_gate_v1.json").write_text(
                json.dumps(
                    {
                        "required_families": ["external_dyn_desc_ref"],
                        "optional_groups": {
                            "queue_optional": {
                                "families": [
                                    "completion_queue_overflow_ref",
                                    "queue_backpressure_ref",
                                ],
                                "blocking": False,
                            }
                        },
                        "promotion_contract": {
                            "queue_optional": {
                                "requires_family_equiv_pass": True,
                                "requires_multi_date_freshness": True,
                                "multi_date_freshness_mode": "since_latest_recovery",
                                "requires_reason_taxonomy_clean": True,
                                "requires_explicit_review": True,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            dated_rows = {
                "2026-03-29": True,
                "2026-04-01": False,
                "2026-04-02": True,
            }
            for date_str, all_ok in dated_rows.items():
                (refs_dir / f"{date_str}-equiv-matrix-queue-optional.json").write_text(
                    json.dumps(
                        {
                            "artifact_role": "dated_equivalence_matrix",
                            "canonical_surface": True,
                            "requested_group": "queue_optional",
                            "generated_utc": f"{date_str}T00:00:00+00:00",
                            "all_ok": all_ok,
                            "count": 2,
                            "families": [
                                {"family": "completion_queue_overflow_ref"},
                                {"family": "queue_backpressure_ref"},
                            ],
                            "summary_path": str(refs_dir / f"{date_str}-equiv-matrix-queue-optional.json"),
                        }
                    ),
                    encoding="utf-8",
                )
            (refs_dir / "nightly-sidecar-report.json").write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "gate_ok": True,
                        "required_families": ["external_dyn_desc_ref"],
                    }
                ),
                encoding="utf-8",
            )
            (refs_dir / "nightly-history-index.json").write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_history_rollup",
                        "latest_date": "2026-04-02",
                    }
                ),
                encoding="utf-8",
            )
            review_path = refs_dir / "2026-04-02-queue-optional-review.json"
            review_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "dated_optional_group_review",
                        "group": "queue_optional",
                        "families": [
                            "completion_queue_overflow_ref",
                            "queue_backpressure_ref",
                        ],
                        "reviewer": "lab-owner",
                        "decision": "approved",
                        "review_date": "2026-04-02",
                    }
                ),
                encoding="utf-8",
            )

            summary = riscv_snn_lab.run_family_admission_audit(group="queue_optional", lab_root=lab_root)

        self.assertTrue(summary["group_equivalence_all_ok"])
        self.assertTrue(summary["group_history_all_dates_ok"])
        self.assertIsNone(summary["group_history_latest_recovered_date"])
        self.assertEqual(summary["group_history_freshness_mode"], "since_latest_recovery")
        self.assertTrue(summary["group_history_effective_all_dates_ok"])
        self.assertEqual(summary["group_history_entry_count"], 1)
        self.assertEqual(summary["group_history_effective_entry_count"], 1)
        self.assertFalse(summary["promotion_ready"])
        self.assertEqual(summary["reasons"], ["queue_optional_multi_date_freshness_insufficient"])
        self.assertEqual(summary["explicit_review_path"], str(review_path))

    def test_family_admission_audit_supports_singleton_optional_group(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            spec_dir = lab_root / "spec_authority"
            refs_dir.mkdir(parents=True, exist_ok=True)
            spec_dir.mkdir(parents=True, exist_ok=True)
            (spec_dir / "riscv_snn_mainline_gate_v1.json").write_text(
                json.dumps(
                    {
                        "required_families": ["external_dyn_desc_ref"],
                        "optional_groups": {
                            "completion_overflow_optional": {
                                "families": ["completion_queue_overflow_ref"],
                                "blocking": False,
                            }
                        },
                        "promotion_contract": {
                            "completion_overflow_optional": {
                                "requires_family_equiv_pass": True,
                                "requires_multi_date_freshness": True,
                                "requires_reason_taxonomy_clean": True,
                                "requires_explicit_review": True,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            for date_str in ("2026-03-28", "2026-03-29"):
                (refs_dir / f"{date_str}-completion-queue-overflow-ref-equiv.json").write_text(
                    json.dumps(
                        {
                            "family": "completion_queue_overflow_ref",
                            "generated_utc": f"{date_str}T00:00:00+00:00",
                            "status": "PASS",
                            "summary_path": str(refs_dir / f"{date_str}-completion-queue-overflow-ref-equiv.json"),
                        }
                    ),
                    encoding="utf-8",
                )
            (refs_dir / "nightly-sidecar-report.json").write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "gate_ok": True,
                        "required_families": ["external_dyn_desc_ref"],
                    }
                ),
                encoding="utf-8",
            )
            (refs_dir / "nightly-history-index.json").write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_history_rollup",
                        "latest_date": "2026-03-29",
                    }
                ),
                encoding="utf-8",
            )
            review_path = refs_dir / "2026-03-31-completion-overflow-optional-review.json"
            review_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "dated_optional_group_review",
                        "group": "completion_overflow_optional",
                        "families": ["completion_queue_overflow_ref"],
                        "reviewer": "lab-owner",
                        "decision": "approved",
                        "review_date": "2026-03-31",
                    }
                ),
                encoding="utf-8",
            )

            summary = riscv_snn_lab.run_family_admission_audit(
                group="completion_overflow_optional",
                lab_root=lab_root,
            )

        self.assertEqual(summary["group"], "completion_overflow_optional")
        self.assertFalse(summary["blocking"])
        self.assertTrue(summary["promotion_ready"])
        self.assertEqual(summary["reasons"], [])
        self.assertEqual(
            summary["contract_primary"],
            riscv_snn_lab.OPTIONAL_ADMISSION_PRIMARY_CONTRACT,
        )
        self.assertEqual(
            summary["primary_contract_fields"],
            list(riscv_snn_lab.OPTIONAL_ADMISSION_PRIMARY_FIELDS),
        )
        self.assertEqual(summary["compatibility_aliases"], {})
        self.assertEqual(summary["group_history_entry_count"], 2)
        self.assertTrue(summary["group_history_all_dates_ok"])
        self.assertNotIn("queue_history_entry_count", summary)
        self.assertNotIn("queue_equivalence_path", summary)
        self.assertEqual(summary["explicit_review_path"], str(review_path))
        self.assertTrue(summary["explicit_review_ok"])

    def test_family_admission_audit_exports_latest_failure_summary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            spec_dir = lab_root / "spec_authority"
            refs_dir.mkdir(parents=True, exist_ok=True)
            spec_dir.mkdir(parents=True, exist_ok=True)
            (spec_dir / "riscv_snn_mainline_gate_v1.json").write_text(
                json.dumps(
                    {
                        "required_families": ["external_dyn_desc_ref"],
                        "optional_groups": {
                            "queue_optional": {
                                "families": [
                                    "completion_queue_overflow_ref",
                                    "queue_backpressure_ref",
                                ],
                                "blocking": False,
                            }
                        },
                        "promotion_contract": {
                            "queue_optional": {
                                "requires_family_equiv_pass": True,
                                "requires_multi_date_freshness": True,
                                "requires_reason_taxonomy_clean": True,
                                "requires_explicit_review": True,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            matrix_path = refs_dir / "2026-04-03-equiv-matrix-queue-optional.json"
            matrix_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "dated_equivalence_matrix",
                        "canonical_surface": True,
                        "requested_group": "queue_optional",
                        "generated_utc": "2026-04-03T00:00:00+00:00",
                        "all_ok": False,
                        "count": 2,
                        "summary_path": str(matrix_path),
                        "families": [
                            {
                                "family": "queue_backpressure_ref",
                                "status": "FAIL",
                                "gate_reasons": ["baseline_smoke_failed", "runtime_bridge_smoke_failed"],
                                "summary_path": str(refs_dir / "2026-04-03-queue-backpressure-ref-equiv.json"),
                            },
                            {
                                "family": "completion_queue_overflow_ref",
                                "status": "FAIL",
                                "gate_reasons": ["runtime_bridge_completion_queue_fault_signature_mismatch"],
                                "summary_path": str(refs_dir / "2026-04-03-completion-queue-overflow-ref-equiv.json"),
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            history_path = refs_dir / "queue-optional-equivalence-history.json"
            history_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_optional_equivalence_history",
                        "group": "queue_optional",
                        "history_contract": "canonical_queue_optional_only",
                        "summary_path": str(history_path),
                        "latest_summary_path": str(matrix_path),
                        "latest_date": "2026-04-03",
                        "entry_count": 2,
                        "all_ok_latest": False,
                        "all_dates_ok": False,
                        "first_fail_date": "2026-04-02",
                        "latest_recovered_date": None,
                        "entries": [],
                    }
                ),
                encoding="utf-8",
            )
            (refs_dir / "nightly-sidecar-report.json").write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "gate_ok": True,
                        "required_families": ["external_dyn_desc_ref"],
                    }
                ),
                encoding="utf-8",
            )
            (refs_dir / "nightly-history-index.json").write_text(
                json.dumps({"artifact_role": "stable_history_rollup", "latest_date": "2026-04-03"}),
                encoding="utf-8",
            )
            review_path = refs_dir / "2026-04-03-queue-optional-review.json"
            review_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "dated_optional_group_review",
                        "group": "queue_optional",
                        "families": ["completion_queue_overflow_ref", "queue_backpressure_ref"],
                        "reviewer": "lab-owner",
                        "decision": "approved",
                        "review_date": "2026-04-03",
                    }
                ),
                encoding="utf-8",
            )

            summary = riscv_snn_lab.run_family_admission_audit(group="queue_optional", lab_root=lab_root)

        self.assertEqual(summary["group_equivalence_path"], str(matrix_path))
        self.assertEqual(
            summary["latest_family_surface_paths"],
            {
                "completion_queue_overflow_ref": str(refs_dir / "2026-04-03-completion-queue-overflow-ref-equiv.json"),
                "queue_backpressure_ref": str(refs_dir / "2026-04-03-queue-backpressure-ref-equiv.json"),
            },
        )
        self.assertEqual(
            summary["surface_failures"],
            {
                "completion_queue_overflow_ref": ["runtime_bridge_completion_queue_fault_signature_mismatch"],
                "queue_backpressure_ref": ["baseline_smoke_failed", "runtime_bridge_smoke_failed"],
            },
        )
        self.assertEqual(
            summary["failing_reason_ids"],
            [
                "baseline_smoke_failed",
                "runtime_bridge_completion_queue_fault_signature_mismatch",
                "runtime_bridge_smoke_failed",
            ],
        )
        self.assertEqual(summary["explicit_review_path"], str(review_path))

    def test_family_admission_audit_exports_singleton_family_failure_summary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            spec_dir = lab_root / "spec_authority"
            refs_dir.mkdir(parents=True, exist_ok=True)
            spec_dir.mkdir(parents=True, exist_ok=True)
            (spec_dir / "riscv_snn_mainline_gate_v1.json").write_text(
                json.dumps(
                    {
                        "required_families": ["external_dyn_desc_ref"],
                        "optional_groups": {
                            "completion_overflow_optional": {
                                "families": ["completion_queue_overflow_ref"],
                                "blocking": False,
                            }
                        },
                        "promotion_contract": {
                            "completion_overflow_optional": {
                                "requires_family_equiv_pass": True,
                                "requires_multi_date_freshness": True,
                                "requires_reason_taxonomy_clean": True,
                                "requires_explicit_review": True,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            family_path = refs_dir / "2026-04-03-completion-queue-overflow-ref-equiv.json"
            family_path.write_text(
                json.dumps(
                    {
                        "family": "completion_queue_overflow_ref",
                        "generated_utc": "2026-04-03T00:00:00+00:00",
                        "status": "FAIL",
                        "gate_reasons": ["runtime_bridge_completion_queue_fault_signature_mismatch"],
                        "summary_path": str(family_path),
                    }
                ),
                encoding="utf-8",
            )
            history_path = refs_dir / "completion-overflow-optional-equivalence-history.json"
            history_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_optional_equivalence_history",
                        "group": "completion_overflow_optional",
                        "history_contract": "canonical_completion_overflow_optional_only",
                        "summary_path": str(history_path),
                        "latest_summary_path": str(family_path),
                        "latest_date": "2026-04-03",
                        "entry_count": 2,
                        "all_ok_latest": False,
                        "all_dates_ok": False,
                        "first_fail_date": "2026-04-02",
                        "latest_recovered_date": None,
                        "entries": [],
                    }
                ),
                encoding="utf-8",
            )
            (refs_dir / "nightly-sidecar-report.json").write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "gate_ok": True,
                        "required_families": ["external_dyn_desc_ref"],
                    }
                ),
                encoding="utf-8",
            )
            (refs_dir / "nightly-history-index.json").write_text(
                json.dumps({"artifact_role": "stable_history_rollup", "latest_date": "2026-04-03"}),
                encoding="utf-8",
            )
            review_path = refs_dir / "2026-04-03-completion-overflow-optional-review.json"
            review_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "dated_optional_group_review",
                        "group": "completion_overflow_optional",
                        "families": ["completion_queue_overflow_ref"],
                        "reviewer": "lab-owner",
                        "decision": "approved",
                        "review_date": "2026-04-03",
                    }
                ),
                encoding="utf-8",
            )

            summary = riscv_snn_lab.run_family_admission_audit(
                group="completion_overflow_optional",
                lab_root=lab_root,
            )

        self.assertEqual(
            summary["surface_failures"],
            {
                "completion_queue_overflow_ref": [
                    "runtime_bridge_completion_queue_fault_signature_mismatch",
                ]
            },
        )
        self.assertEqual(
            summary["failing_reason_ids"],
            ["runtime_bridge_completion_queue_fault_signature_mismatch"],
        )
        self.assertEqual(
            summary["latest_family_surface_paths"],
            {"completion_queue_overflow_ref": str(family_path)},
        )
        self.assertEqual(summary["explicit_review_path"], str(review_path))

    def test_family_admission_audit_refreshes_current_mainline_status_when_sidecar_exists(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            for date_str in ("2026-03-28", "2026-03-29"):
                (refs_dir / f"{date_str}-equiv-matrix-queue-optional.json").write_text(
                    json.dumps(
                        {
                            "artifact_role": "dated_equivalence_matrix",
                            "canonical_surface": True,
                            "requested_group": "queue_optional",
                            "all_ok": True,
                            "count": 2,
                            "families": [
                                {"family": "completion_queue_overflow_ref"},
                                {"family": "queue_backpressure_ref"},
                            ],
                        }
                    ),
                    encoding="utf-8",
                )

            observer_path = refs_dir / "nightly-sidecar-observer-summary.json"
            research_path = refs_dir / "riscv-snn-research-report.json"
            validation_path = refs_dir / "observer-adequacy-validation.json"
            observer_path.write_text(
                json.dumps(
                    {
                        "optional_surfaces": {
                            "full_equivalence": {
                                "entry_count": 2,
                                "first_fail_date": "2026-03-30",
                                "latest_recovered_date": "2026-03-30",
                                "all_ok_latest": True,
                                "history_contract": "observer_sample_sequence_v1",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            research_path.write_text(
                json.dumps(
                    {
                        "observer_adequacy": {
                            "status": "ready_with_fail_recovery_sample",
                        }
                    }
                ),
                encoding="utf-8",
            )
            validation_path.write_text(
                json.dumps(
                    {
                        "status": "pass",
                        "mismatch_count": 0,
                    }
                ),
                encoding="utf-8",
            )
            (refs_dir / "nightly-sidecar-report.json").write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "generated_utc": "2026-03-31T00:00:00+00:00",
                        "gate_ok": True,
                        "with_equivalence": True,
                        "with_full_equivalence": True,
                        "required_families": riscv_snn_lab.authority_required_families(),
                        "observer_summary_path": str(observer_path),
                        "research_report_path": str(research_path),
                        "observer_adequacy_validation_path": str(validation_path),
                    }
                ),
                encoding="utf-8",
            )
            (refs_dir / "nightly-history-index.json").write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_history_rollup",
                        "latest_date": "2026-03-29",
                    }
                ),
                encoding="utf-8",
            )
            review_path = refs_dir / "2026-03-30-queue-optional-review.json"
            review_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "dated_optional_group_review",
                        "group": "queue_optional",
                        "families": [
                            "completion_queue_overflow_ref",
                            "queue_backpressure_ref",
                        ],
                        "reviewer": "lab-owner",
                        "decision": "approved",
                        "review_date": "2026-03-30",
                    }
                ),
                encoding="utf-8",
            )

            summary = riscv_snn_lab.run_family_admission_audit(group="queue_optional", lab_root=lab_root)
            current_mainline_path = Path(summary["current_mainline_status_path"])
            current_mainline_text = current_mainline_path.read_text(encoding="utf-8")
            persisted_sidecar = json.loads((refs_dir / "nightly-sidecar-report.json").read_text(encoding="utf-8"))
            self.assertTrue(current_mainline_path.exists())
            self.assertEqual(current_mainline_path, refs_dir / "current-mainline-status.md")
            self.assertEqual(
                persisted_sidecar["current_mainline_status_path"],
                str(current_mainline_path),
            )

        self.assertIn("## Optional Admission", current_mainline_text)
        self.assertIn("`promotion_ready = True`", current_mainline_text)
        self.assertIn("## Research / Validation", current_mainline_text)

    def test_render_mainline_status_markdown_renders_optional_failure_summary(self) -> None:
        sidecar_path = Path("/tmp/nightly-sidecar-report.json")
        observer_summary_path = Path("/tmp/nightly-sidecar-observer-summary.json")
        research_path = Path("/tmp/riscv-snn-research-report.json")
        validation_path = Path("/tmp/observer-adequacy-validation.json")
        rendered = riscv_snn_lab.render_mainline_status_markdown(
            {
                "generated_utc": "2026-04-03T00:00:00+00:00",
                "gate_ok": True,
                "with_equivalence": True,
                "with_full_equivalence": True,
                "required_families": ["external_dyn_desc_ref"],
                "stable_surface_refresh": {
                    "refreshed_utc": "2026-04-04T00:00:00+00:00",
                },
            },
            sidecar_path=sidecar_path,
            observer_summary={
                "optional_surfaces": {
                    "full_equivalence": {
                        "entry_count": 1,
                        "history_contract": "observer_sample_sequence_v1",
                    }
                }
            },
            observer_summary_path=observer_summary_path,
            research_report={"observer_adequacy": {"status": "ready_with_fail_recovery_sample"}},
            research_report_path=research_path,
            validation_report={"status": "pass", "mismatch_count": 0},
            validation_report_path=validation_path,
            optional_group_names=["queue_optional", "completion_overflow_optional"],
            optional_group_rollups={
                "queue_optional": {
                    "latest_date": "2026-04-03",
                    "entry_count": 2,
                    "all_dates_ok": False,
                    "history_contract": "canonical_queue_optional_only",
                },
                "completion_overflow_optional": {
                    "latest_date": "2026-04-03",
                    "entry_count": 2,
                    "all_dates_ok": False,
                    "history_contract": "canonical_completion_overflow_optional_only",
                },
            },
            optional_admission_surfaces={
                "queue_optional": {
                    "promotion_ready": False,
                    "explicit_review_ok": True,
                    "blocking": False,
                    "failing_reason_ids": [
                        "baseline_smoke_failed",
                        "runtime_bridge_smoke_failed",
                    ],
                    "surface_failures": {
                        "queue_backpressure_ref": [
                            "baseline_smoke_failed",
                            "runtime_bridge_smoke_failed",
                        ]
                    },
                },
                "completion_overflow_optional": {
                    "promotion_ready": False,
                    "explicit_review_ok": True,
                    "blocking": False,
                    "failing_reason_ids": [
                        "runtime_bridge_completion_queue_fault_signature_mismatch",
                    ],
                    "surface_failures": {
                        "completion_queue_overflow_ref": [
                            "runtime_bridge_completion_queue_fault_signature_mismatch",
                        ]
                    },
                },
            },
            optional_admission_paths={
                "queue_optional": Path("/tmp/2026-04-03-queue-optional-admission-audit.json"),
                "completion_overflow_optional": Path("/tmp/2026-04-03-completion-overflow-optional-admission-audit.json"),
            },
            runtime_gate_authority={
                "checks": {"completion_consumed_covers_visible": {"summary": "test-summary"}},
                "families": {},
            },
            runtime_gate_authority_path=Path("/tmp/riscv_snn_runtime_gate_v1.json"),
        )

        self.assertIn("- Generated UTC: `2026-04-04T00:00:00+00:00`", rendered)
        self.assertIn("## Optional Failure Summary", rendered)
        self.assertIn("`queue_optional.failing_reason_ids = baseline_smoke_failed, runtime_bridge_smoke_failed`", rendered)
        self.assertIn("`completion_overflow_optional.failing_reason_ids = runtime_bridge_completion_queue_fault_signature_mismatch`", rendered)
        self.assertIn("`queue_backpressure_ref`: `baseline_smoke_failed, runtime_bridge_smoke_failed`", rendered)
        self.assertIn("`completion_queue_overflow_ref`: `runtime_bridge_completion_queue_fault_signature_mismatch`", rendered)

    def test_refresh_artifact_isolation_history_rollup_tracks_multi_date_observer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            (refs_dir / "artifact-isolation-history.json").write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_artifact_isolation_history",
                        "entries": [
                            {
                                "date": "2026-03-27",
                                "all_ok": True,
                                "regressed_surfaces": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            report = {
                "generated_utc": "2026-03-28T05:33:45.608200+00:00",
                "summary_path": str(refs_dir / "artifact-isolation-report.json"),
                "all_ok": False,
                "surfaces": {
                    "nightly": {
                        "canonical_unchanged": True,
                        "subset_surface": "subset",
                        "subset_summary_path": str(refs_dir / "2026-03-28-nightly-index-subset-e64390052e2e.json"),
                    },
                    "toolchain": {
                        "canonical_unchanged": False,
                        "subset_surface": "subset",
                        "subset_summary_path": str(refs_dir / "2026-03-28-toolchain-regress-matrix-subset-b8cba2a66013.json"),
                    },
                },
            }

            history = riscv_snn_lab.refresh_artifact_isolation_history(report, lab_root=lab_root)

        self.assertEqual(history["artifact_role"], "stable_artifact_isolation_history")
        self.assertEqual(history["latest_date"], "2026-03-28")
        self.assertEqual(history["entry_count"], 2)
        self.assertFalse(history["all_dates_ok"])
        self.assertEqual(history["entries"][0]["regressed_surfaces"], ["toolchain"])
        self.assertEqual(
            history["summary_path"],
            str(refs_dir / "artifact-isolation-history.json"),
        )

    def test_main_artifact_isolation_prints_report_path(self) -> None:
        expected_report = {
            "summary_path": "/tmp/artifact-isolation-report.json",
            "all_ok": True,
        }
        with mock.patch.object(riscv_snn_lab, "run_artifact_isolation_check", return_value=expected_report) as run_check:
            with mock.patch("builtins.print") as print_mock:
                rc = riscv_snn_lab.main(["artifact-isolation"])

        self.assertEqual(rc, 0)
        run_check.assert_called_once_with(report_path=None)
        print_mock.assert_called_once_with("/tmp/artifact-isolation-report.json")

    def test_main_explain_sidecar_prints_authority_surface(self) -> None:
        with mock.patch("builtins.print") as print_mock:
            rc = riscv_snn_lab.main(["explain-sidecar"])

        self.assertEqual(rc, 0)
        rendered = "\n".join(str(call.args[0]) for call in print_mock.call_args_list)
        self.assertIn("stable_top_level_gate", rendered)
        self.assertIn("dated_equivalence_matrix", rendered)
        self.assertIn("dated_nightly_index", rendered)
        self.assertIn("supplementary_surface_authority", rendered)
        self.assertIn("not the equivalence authority", rendered)

    def test_explain_sidecar_surface_prefers_lab_override_for_supplementary_authority_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            spec_dir = td_path / "spec_authority"
            spec_dir.mkdir(parents=True, exist_ok=True)
            override_path = spec_dir / "riscv_snn_supplementary_surface_v1.json"
            override_path.write_text("{}", encoding="utf-8")

            rendered = riscv_snn_lab.explain_sidecar_surface(lab_root=td_path)

        self.assertIn(f"supplementary_surface_authority: {override_path}", rendered)

    def test_cli_script_entrypoint_runs_explain_sidecar(self) -> None:
        proc = subprocess.run(
            ["python3", str(riscv_snn_lab.LAB_ROOT / "tools" / "riscv_snn_lab.py"), "explain-sidecar"],
            text=True,
            capture_output=True,
            check=False,
            cwd=str(riscv_snn_lab.REPO_ROOT),
        )

        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("stable_top_level_gate", proc.stdout)

    def test_main_explain_mainline_prints_gate_authority_surface(self) -> None:
        with mock.patch("builtins.print") as print_mock:
            rc = riscv_snn_lab.main(["explain-mainline"])

        self.assertEqual(rc, 0)
        rendered = "\n".join(str(call.args[0]) for call in print_mock.call_args_list)
        self.assertIn("mainline_gate_authority", rendered)
        self.assertIn("required_families", rendered)
        self.assertIn("queue_optional", rendered)
        self.assertIn("stable_top_level_gate", rendered)

    def test_explain_mainline_surface_lists_all_optional_groups_from_authority(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            spec_dir = td_path / "spec_authority"
            spec_dir.mkdir(parents=True, exist_ok=True)
            (spec_dir / "riscv_snn_mainline_gate_v1.json").write_text(
                json.dumps(
                    {
                        "required_families": ["external_dyn_desc_ref"],
                        "optional_groups": {
                            "queue_optional": {
                                "families": ["queue_backpressure_ref"],
                                "blocking": False,
                            },
                            "latency_optional": {
                                "families": ["latency_probe_ref", "latency_tail_ref"],
                                "blocking": False,
                            },
                        },
                        "mainline_defaults": {
                            "primary_optional_group": "latency_optional",
                            "mainline_refresh_default_group": "queue_optional",
                        },
                        "promotion_contract": {
                            "queue_optional": {},
                            "latency_optional": {},
                        },
                    }
                ),
                encoding="utf-8",
            )

            rendered = riscv_snn_lab.explain_mainline_surface(lab_root=td_path)

        self.assertIn("queue_optional: queue_backpressure_ref", rendered)
        self.assertIn("latency_optional: latency_probe_ref, latency_tail_ref", rendered)
        self.assertIn("primary_optional_group: latency_optional", rendered)
        self.assertIn("mainline_refresh_default_group: queue_optional", rendered)

    def test_main_explain_runtime_gate_prints_family_surface(self) -> None:
        with mock.patch("builtins.print") as print_mock:
            rc = riscv_snn_lab.main(["explain-runtime-gate", "--family", "external_dyn_desc_fault_ref"])

        self.assertEqual(rc, 0)
        rendered = "\n".join(str(call.args[0]) for call in print_mock.call_args_list)
        self.assertIn("runtime_gate_authority", rendered)
        self.assertIn("family: external_dyn_desc_fault_ref", rendered)
        self.assertIn("fault_mode: accepted_fault_required", rendered)
        self.assertIn("stable_reason_ids", rendered)

    def test_explain_program_semantics_surface_prints_bound_profile_and_steps(self) -> None:
        renderer = getattr(riscv_snn_lab, "explain_program_semantics_surface", None)
        self.assertIsNotNone(renderer)

        rendered = renderer("external_dyn_desc_fault_rearm_ref")

        self.assertIn("architecture_model_authority", rendered)
        self.assertIn("family: external_dyn_desc_fault_rearm_ref", rendered)
        self.assertIn("reference_program_profile: clear_then_refault", rendered)
        self.assertIn("step_names: fault_visible, fault_rearmed_visible", rendered)
        self.assertIn("control_events", rendered)

    def test_main_explain_program_semantics_prints_family_surface(self) -> None:
        with mock.patch("builtins.print") as print_mock:
            rc = riscv_snn_lab.main(
                ["explain-program-semantics", "--family", "external_dyn_desc_fault_rearm_ref"]
            )

        self.assertEqual(rc, 0)
        rendered = "\n".join(str(call.args[0]) for call in print_mock.call_args_list)
        self.assertIn("family: external_dyn_desc_fault_rearm_ref", rendered)
        self.assertIn("reference_program_profile: clear_then_refault", rendered)
        self.assertIn("step_names: fault_visible, fault_rearmed_visible", rendered)

    def test_main_export_control_plane_contract_prints_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "control-plane.md"
            with mock.patch("builtins.print") as print_mock:
                rc = riscv_snn_lab.main(
                    [
                        "export-control-plane-contract",
                        "--output",
                        str(output_path),
                    ]
                )
            self.assertTrue(output_path.exists())

        self.assertEqual(rc, 0)
        print_mock.assert_called_once_with(output_path)

    def test_main_family_admission_audit_prints_summary_path(self) -> None:
        expected = {
            "summary_path": "/tmp/queue-optional-admission-audit.json",
            "promotion_ready": False,
        }
        with mock.patch.object(riscv_snn_lab, "run_family_admission_audit", return_value=expected) as run_audit:
            with mock.patch("builtins.print") as print_mock:
                rc = riscv_snn_lab.main(["family-admission-audit", "--group", "queue_optional"])

        self.assertEqual(rc, 0)
        self.assertEqual(run_audit.call_args.kwargs["group"], "queue_optional")
        print_mock.assert_called_once_with("/tmp/queue-optional-admission-audit.json")

    def test_main_family_admission_audit_accepts_completion_overflow_optional(self) -> None:
        expected = {
            "summary_path": "/tmp/completion-overflow-optional-admission-audit.json",
            "promotion_ready": True,
        }
        with mock.patch.object(riscv_snn_lab, "run_family_admission_audit", return_value=expected) as run_audit:
            with mock.patch("builtins.print") as print_mock:
                rc = riscv_snn_lab.main(["family-admission-audit", "--group", "completion_overflow_optional"])

        self.assertEqual(rc, 0)
        self.assertEqual(run_audit.call_args.kwargs["group"], "completion_overflow_optional")
        print_mock.assert_called_once_with("/tmp/completion-overflow-optional-admission-audit.json")

    def test_bit_level_abi_authority_exists_and_has_required_sections(self) -> None:
        authority = json.loads(
            (
                riscv_snn_lab.LAB_ROOT
                / "spec_authority"
                / "riscv_snn_accel_v1.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(authority["schema_version"], 1)
        self.assertEqual(authority["hart_profile"], "rv64im_zicsr")
        self.assertIn("csr_map", authority)
        self.assertIn("event_pending_bits", authority)
        self.assertIn("descriptor_layout", authority)
        self.assertIn("completion_layout", authority)
        self.assertIn("rx_debug_layout", authority)
        self.assertIn("hdr0_layout", authority)
        self.assertIn("result_surface", authority)
        self.assertIn("enum_surfaces", authority)
        self.assertIn("surface_framework", authority)
        self.assertIn("stat_snapshot_surface", authority)
        self.assertIn("fault_semantics", authority)
        self.assertIn("ownership_rules", authority)
        self.assertIn("doorbell_rules", authority)

    def _load_accel_abi_authority(self) -> dict[str, object]:
        return json.loads(
            (
                riscv_snn_lab.LAB_ROOT
                / "spec_authority"
                / "riscv_snn_accel_v1.json"
            ).read_text(encoding="utf-8")
        )

    def _read_runtime_abi_header(self) -> str:
        return (
            riscv_snn_lab.SNNDL_ROOT
            / "services"
            / "workload"
            / "riscv_snn"
            / "RiscvSnnAbi.h"
        ).read_text(encoding="utf-8")

    def _runtime_abi_constant(self, name: str) -> int:
        header_content = self._read_runtime_abi_header()
        marker = f"inline constexpr uint32_t {name} = "
        start = header_content.index(marker) + len(marker)
        end = header_content.index(";", start)
        return int(header_content[start:end], 0)

    def _runtime_struct_layout(self, struct_name: str) -> dict[str, object]:
        match = re.search(
            rf"struct {struct_name}\s*\{{(.*?)\n\}};",
            self._read_runtime_abi_header(),
            re.S,
        )
        self.assertIsNotNone(match, msg=struct_name)
        field_sizes = {
            "uint8_t": 1,
            "uint16_t": 2,
            "uint32_t": 4,
            "uint64_t": 8,
        }
        fields: list[dict[str, object]] = []
        offset = 0
        for field_type, field_name in re.findall(
            r"(uint(?:8|16|32|64)_t)\s+(\w+)\s*=\s*[^;]+;",
            match.group(1),
        ):
            size = field_sizes[field_type]
            fields.append(
                {
                    "name": field_name,
                    "offset": offset,
                    "size": size,
                }
            )
            offset += size
        return {
            "size_bytes": offset,
            "fields": fields,
        }

    def _runtime_enum_values(
        self,
        enum_name: str,
        *,
        completion_primary_values: dict[str, int] | None = None,
    ) -> dict[str, int]:
        match = re.search(
            rf"enum class {enum_name}\s*:\s*uint(?:8|32)_t\s*\{{(.*?)\n\}};",
            self._read_runtime_abi_header(),
            re.S,
        )
        self.assertIsNotNone(match, msg=enum_name)
        enum_body = re.sub(r"\s+", " ", match.group(1)).strip()
        values: dict[str, int] = {}
        for entry in enum_body.split(","):
            item = entry.strip()
            if not item:
                continue
            entry_name, entry_value = [part.strip() for part in item.split("=", 1)]
            if entry_value.startswith("static_cast<uint8_t>(CompletionPrimaryStatus::"):
                self.assertIsNotNone(completion_primary_values, msg=enum_name)
                primary_name = entry_value.removeprefix(
                    "static_cast<uint8_t>(CompletionPrimaryStatus::"
                ).removesuffix(")")
                values[entry_name] = completion_primary_values[primary_name]
            else:
                values[entry_name] = int(entry_value, 0)
        return values

    def _layout_projection(self, layout: dict[str, object]) -> dict[str, object]:
        return {
            "size_bytes": layout["size_bytes"],
            "fields": [
                {
                    "name": field["name"],
                    "offset": field["offset"],
                    "size": field["size"],
                }
                for field in layout["fields"]
            ],
        }

    def test_bit_level_abi_authority_csr_map_stays_within_12_bit_riscv_window(self) -> None:
        authority = json.loads(
            (
                riscv_snn_lab.LAB_ROOT
                / "spec_authority"
                / "riscv_snn_accel_v1.json"
            ).read_text(encoding="utf-8")
        )
        for name, value in authority["csr_map"].items():
            self.assertGreaterEqual(value, 0, msg=name)
            self.assertLessEqual(value, 0xFFF, msg=name)

    def test_bit_level_abi_authority_csr_map_matches_runtime_header_surface(self) -> None:
        authority = json.loads(
            (
                riscv_snn_lab.LAB_ROOT
                / "spec_authority"
                / "riscv_snn_accel_v1.json"
            ).read_text(encoding="utf-8")
        )
        header_content = (
            riscv_snn_lab.SNNDL_ROOT
            / "services"
            / "workload"
            / "riscv_snn"
            / "RiscvSnnAbi.h"
        ).read_text(encoding="utf-8")
        header_pairs = {
            "CSR_MSNN_CFG": "kCsrMsnnCfg",
            "CSR_MSNN_STATUS": "kCsrMsnnStatus",
            "CSR_MSNN_FEAT": "kCsrMsnnFeat",
            "CSR_MSNN_HART_ID": "kCsrMsnnHartId",
            "CSR_MSNN_CMDQ_BASE": "kCsrMsnnCmdqBase",
            "CSR_MSNN_CMDQ_SIZE": "kCsrMsnnCmdqSize",
            "CSR_MSNN_CMDQ_HEAD": "kCsrMsnnCmdqHead",
            "CSR_MSNN_CMDQ_TAIL": "kCsrMsnnCmdqTail",
            "CSR_MSNN_CMPQ_BASE": "kCsrMsnnCmpqBase",
            "CSR_MSNN_CMPQ_SIZE": "kCsrMsnnCmpqSize",
            "CSR_MSNN_CMPQ_HEAD": "kCsrMsnnCmpqHead",
            "CSR_MSNN_CMPQ_TAIL": "kCsrMsnnCmpqTail",
            "CSR_MSNN_RXQ_BASE": "kCsrMsnnRxqBase",
            "CSR_MSNN_RXQ_SIZE": "kCsrMsnnRxqSize",
            "CSR_MSNN_RXQ_HEAD": "kCsrMsnnRxqHead",
            "CSR_MSNN_RXQ_TAIL": "kCsrMsnnRxqTail",
            "CSR_MSNN_EVENT_ENABLE": "kCsrMsnnEventEnable",
            "CSR_MSNN_EVENT_PENDING": "kCsrMsnnEventPending",
            "CSR_MSNN_STEP": "kCsrMsnnStep",
            "CSR_MSNN_FAULT": "kCsrMsnnFault",
        }
        for authority_name, header_name in header_pairs.items():
            marker = f"inline constexpr uint32_t {header_name} = "
            start = header_content.index(marker) + len(marker)
            end = header_content.index(";", start)
            runtime_value = int(header_content[start:end], 16)
            self.assertEqual(authority["csr_map"][authority_name], runtime_value, msg=authority_name)

    def test_bit_level_abi_authority_live_packed_layouts_match_runtime_header_surface(self) -> None:
        authority = self._load_accel_abi_authority()
        self.assertEqual(
            self._layout_projection(authority["descriptor_layout"]),
            self._runtime_struct_layout("CommandDescriptorV1"),
        )
        self.assertEqual(
            authority["descriptor_layout"]["size_bytes"],
            self._runtime_abi_constant("kCommandDescriptorBytes"),
        )
        self.assertEqual(
            self._layout_projection(authority["completion_layout"]),
            self._runtime_struct_layout("CompletionEntryV1"),
        )
        self.assertEqual(
            authority["completion_layout"]["size_bytes"],
            self._runtime_abi_constant("kCompletionEntryBytes"),
        )
        self.assertEqual(
            self._layout_projection(authority["rx_debug_layout"]),
            self._runtime_struct_layout("RxDebugEntryV1"),
        )
        self.assertEqual(
            authority["rx_debug_layout"]["size_bytes"],
            self._runtime_abi_constant("kRxDebugEntryBytes"),
        )

    def test_bit_level_abi_authority_result_surface_bitfields_match_runtime_header_surface(self) -> None:
        authority = self._load_accel_abi_authority()
        self.assertEqual(
            authority["hdr0_layout"]["bitfields"],
            [
                {"name": "version", "lsb": 0, "msb": 7, "width_bits": 8, "helper": "descriptorVersion"},
                {"name": "opcode", "lsb": 8, "msb": 15, "width_bits": 8, "helper": "descriptorOpcodeRaw"},
                {"name": "flags", "lsb": 16, "msb": 23, "width_bits": 8, "helper": "descriptorFlags"},
                {
                    "name": "completion_policy",
                    "lsb": 24,
                    "msb": 31,
                    "width_bits": 8,
                    "helper": "descriptorCompletionPolicy",
                },
                {
                    "name": "error_policy",
                    "lsb": 32,
                    "msb": 39,
                    "width_bits": 8,
                    "helper": "descriptorErrorPolicy",
                },
                {"name": "desc_bytes", "lsb": 40, "msb": 47, "width_bits": 8, "helper": "descriptorBytes"},
                {
                    "name": "reserved_header_bits",
                    "lsb": 48,
                    "msb": 63,
                    "width_bits": 16,
                    "helper": "descriptorReservedHeaderBits",
                },
            ],
        )
        self.assertEqual(
            authority["hdr0_layout"]["derived_masks"],
            [
                {
                    "name": "reserved_flag_bits",
                    "source_field": "flags",
                    "mask": 252,
                    "helper": "descriptorReservedFlagBits",
                }
            ],
        )
        self.assertEqual(
            authority["result_surface"]["status_code_layout"]["bitfields"],
            [
                {
                    "name": "primary_status",
                    "lsb": 0,
                    "msb": 7,
                    "width_bits": 8,
                    "helper": "completionPrimaryStatus",
                },
                {
                    "name": "severity",
                    "lsb": 8,
                    "msb": 15,
                    "width_bits": 8,
                    "helper": "completionSeverity",
                },
                {
                    "name": "reserved",
                    "lsb": 16,
                    "msb": 31,
                    "width_bits": 16,
                    "helper": None,
                },
            ],
        )
        self.assertEqual(
            authority["result_surface"]["fault_csr_layout"]["bitfields"],
            [
                {"name": "fault_code", "lsb": 0, "msb": 7, "width_bits": 8, "helper": "faultCode"},
                {"name": "fault_source", "lsb": 8, "msb": 15, "width_bits": 8, "helper": "faultSource"},
                {"name": "slot", "lsb": 16, "msb": 31, "width_bits": 16, "helper": "faultSlot"},
                {"name": "aux", "lsb": 32, "msb": 63, "width_bits": 32, "helper": "faultAux"},
            ],
        )

    def test_bit_level_abi_authority_enum_surfaces_match_runtime_header_surface(self) -> None:
        authority = self._load_accel_abi_authority()
        completion_primary_values = self._runtime_enum_values("CompletionPrimaryStatus")
        self.assertEqual(
            authority["enum_surfaces"]["CommandOpcode"]["values"],
            self._runtime_enum_values("CommandOpcode"),
        )
        self.assertEqual(
            authority["enum_surfaces"]["DescriptorFlagBit"]["values"],
            self._runtime_enum_values("DescriptorFlagBit"),
        )
        self.assertEqual(
            authority["enum_surfaces"]["CompletionPrimaryStatus"]["values"],
            completion_primary_values,
        )
        self.assertEqual(
            authority["enum_surfaces"]["CompletionSeverity"]["values"],
            self._runtime_enum_values("CompletionSeverity"),
        )
        self.assertEqual(
            authority["enum_surfaces"]["FaultCode"]["values"],
            self._runtime_enum_values(
                "FaultCode",
                completion_primary_values=completion_primary_values,
            ),
        )
        self.assertEqual(
            authority["enum_surfaces"]["FaultSource"]["values"],
            self._runtime_enum_values("FaultSource"),
        )
        self.assertEqual(
            authority["enum_surfaces"]["StatSnapshotSelector"]["values"],
            self._runtime_enum_values("StatSnapshotSelector"),
        )

    def test_bit_level_abi_authority_exports_stat_snapshot_surface_from_runtime_header(self) -> None:
        authority = self._load_accel_abi_authority()
        self.assertEqual(authority["enum_surfaces"]["CommandOpcode"]["values"]["StatSnapshot"], 0x50)
        self.assertEqual(
            authority["enum_surfaces"]["StatSnapshotSelector"]["values"],
            self._runtime_enum_values("StatSnapshotSelector"),
        )
        self.assertEqual(
            authority["stat_snapshot_surface"]["selector_surface"],
            {
                "frozen": True,
                "selector_field": "arg0_low32",
                "value_type": "u64_split_aux0_aux1",
                "values": self._runtime_enum_values("StatSnapshotSelector"),
                "extensible_slots": [],
                "source_of_truth": "RiscvSnnAbi.h",
            },
        )
        self.assertEqual(
            authority["stat_snapshot_surface"]["result_surface"],
            {
                "completion_helpers": [
                    "statSnapshotResultAux0",
                    "statSnapshotResultAux1",
                    "decodeStatSnapshotResult",
                ],
                "success_completion_only": True,
                "barrier_release_forbidden": True,
            },
        )

    def test_abi_exporter_include_surface_stays_stable_when_machine_readable_schema_grows(self) -> None:
        authority = self._load_accel_abi_authority()
        baseline = riscv_snn_lab.export_riscv_snn_abi.render_include_text(authority)
        mutated = json.loads(json.dumps(authority))
        mutated["surface_framework"] = {
            "include_export": {
                "surface_kind": "shared_include_only",
                "frozen_authority_keys": ["producer", "generated_utc", "csr_map", "event_pending_bits"],
            },
            "live_packed_abi": {
                "surface_kind": "machine_readable_only",
                "new_test_only_field": "ignored-by-include-renderer",
            },
        }
        mutated["enum_surfaces"]["CommandOpcode"]["values"]["ReservedTestOnly"] = 0xFE
        self.assertEqual(
            riscv_snn_lab.export_riscv_snn_abi.render_include_text(mutated),
            baseline,
        )

    def test_reference_toolchain_sources_include_generated_abi_surface(self) -> None:
        for program in (
            "external_dyn_desc_ref_toolchain",
            "external_dyn_desc_fault_ref_toolchain",
            "external_dyn_desc_bad_policy_ref_toolchain",
            "external_dyn_desc_fault_rearm_ref_toolchain",
            "external_dyn_desc_fault_overwrite_chain_ref_toolchain",
            "barrier_wfi_order_ref_toolchain",
        ):
            toolchain_dir = riscv_snn_lab.toolchain_source_dir(program)
            content = (toolchain_dir / "main.S").read_text(encoding="utf-8")
            self.assertIn('.include "abi.inc"', content)
            self.assertTrue((toolchain_dir / "abi.inc").exists(), msg=program)

    def test_reference_toolchain_abi_bridge_resolves_to_authority_include(self) -> None:
        authority_include = (
            riscv_snn_lab.LAB_ROOT / "spec_authority" / "riscv_snn_accel_v1.inc"
        ).resolve()
        for program in (
            "external_dyn_desc_ref_toolchain",
            "external_dyn_desc_fault_ref_toolchain",
            "external_dyn_desc_bad_policy_ref_toolchain",
            "external_dyn_desc_fault_rearm_ref_toolchain",
            "external_dyn_desc_fault_overwrite_chain_ref_toolchain",
            "barrier_wfi_order_ref_toolchain",
        ):
            abi_path = riscv_snn_lab.toolchain_source_dir(program) / "abi.inc"
            include_line = abi_path.read_text(encoding="utf-8").strip()
            self.assertTrue(include_line.startswith('.include "'), msg=program)
            self.assertTrue(include_line.endswith('"'), msg=program)
            include_target = include_line[len('.include "') : -1]
            resolved_include = (abi_path.parent / include_target).resolve()
            self.assertEqual(resolved_include, authority_include, msg=program)
            self.assertTrue(resolved_include.exists(), msg=program)

    def test_checked_in_abi_include_matches_authority_export(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "riscv_snn_accel_v1.inc"
            generated_path = riscv_snn_lab.export_abi_include(output_path=output_path)

            self.assertEqual(generated_path, output_path)
            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                (
                    riscv_snn_lab.LAB_ROOT
                    / "spec_authority"
                    / "riscv_snn_accel_v1.inc"
                ).read_text(encoding="utf-8"),
            )

    def test_main_hart_ref_accepts_profile_and_summary_path(self) -> None:
        expected = {
            "summary_path": "/tmp/hart-ref.json",
            "all_ok": True,
        }
        with mock.patch.object(riscv_snn_lab, "run_hart_ref", return_value=expected) as run_hart_ref:
            with mock.patch("builtins.print") as print_mock:
                rc = riscv_snn_lab.main(["hart-ref", "--profile", "rv64im_zicsr_smoke"])

        self.assertEqual(rc, 0)
        self.assertEqual(run_hart_ref.call_args.kwargs["profile"], "rv64im_zicsr_smoke")
        print_mock.assert_called_once_with("/tmp/hart-ref.json")

    def test_hart_ref_smoke_program_build_assets_exist(self) -> None:
        program_dir = (
            riscv_snn_lab.LAB_ROOT
            / "hart_ref"
            / "programs"
            / "rv64im_zicsr_smoke"
        )
        self.assertTrue((program_dir / "rv64im_zicsr_smoke.S").exists())
        self.assertTrue((program_dir / "Makefile").exists())
        self.assertTrue((program_dir / "linker.ld").exists())

    def test_hart_ref_smoke_makefile_prefers_baremetal_clang_flow(self) -> None:
        makefile = (
            riscv_snn_lab.LAB_ROOT
            / "hart_ref"
            / "programs"
            / "rv64im_zicsr_smoke"
            / "Makefile"
        ).read_text(encoding="utf-8")
        self.assertIn("--target=riscv64-unknown-elf", makefile)
        self.assertIn("-fuse-ld=lld", makefile)

    def test_hart_ref_can_resolve_local_spike_prefix_binary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lab_root = Path(td) / "riscv_snn_isa_lab"
            local_spike = lab_root / "external" / "spike-local" / "prefix" / "bin" / "spike"
            local_spike.parent.mkdir(parents=True, exist_ok=True)
            local_spike.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

            resolved = riscv_hart_ref.resolve_spike_binary(lab_root=lab_root)

        self.assertEqual(resolved, local_spike)

    def test_hart_ref_local_spike_probe_reports_missing_dependencies(self) -> None:
        summary = riscv_hart_ref.probe_local_spike_env(
            which=lambda name: {
                "git": "/usr/bin/git",
                "make": "/usr/bin/make",
                "g++": "/usr/bin/g++",
                "cmake": "/usr/bin/cmake",
                "pkg-config": "/usr/bin/pkg-config",
            }.get(name),
            package_installed=lambda name: False,
        )

        self.assertIsNone(summary["resolved_spike"])
        self.assertIn("dtc", summary["missing_commands"])
        self.assertIn("flex", summary["missing_commands"])
        self.assertIn("bison", summary["missing_commands"])
        self.assertIn("libboost-regex-dev", summary["missing_packages"])
        self.assertIn("libboost-system-dev", summary["missing_packages"])

    def test_main_abi_export_prints_generated_include_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "abi.inc"
            with mock.patch.object(riscv_snn_lab, "export_abi_include", return_value=output_path) as export_abi_include:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(["abi-export", "--output", str(output_path)])

        self.assertEqual(rc, 0)
        self.assertEqual(export_abi_include.call_args.kwargs["output_path"], output_path)
        print_mock.assert_called_once_with(output_path)

    def test_main_abi_audit_prints_summary_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            summary_path = Path(td) / "abi-audit.json"
            expected = {
                "summary_path": str(summary_path),
                "all_ok": True,
            }
            with mock.patch.object(riscv_snn_lab, "audit_abi_surface", return_value=expected) as audit_abi_surface:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(["abi-audit", "--summary", str(summary_path)])

        self.assertEqual(rc, 0)
        self.assertEqual(audit_abi_surface.call_args.kwargs["summary_path"], summary_path)
        print_mock.assert_called_once_with(str(summary_path))

    def test_main_spike_local_prints_summary_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            summary_path = Path(td) / "spike-local.json"
            expected = {
                "summary_path": str(summary_path),
                "all_ok": False,
            }
            with mock.patch.object(riscv_snn_lab, "probe_spike_local", return_value=expected) as probe_spike_local:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(["spike-local", "--summary", str(summary_path)])

        self.assertEqual(rc, 2)
        self.assertEqual(probe_spike_local.call_args.kwargs["summary_path"], summary_path)
        print_mock.assert_called_once_with(str(summary_path))

    def test_main_runtime_bridge_preflight_prints_json_summary(self) -> None:
        expected = {
            "enabled": True,
            "status": "stale",
            "contract_key": "riscv_snn.runtime_bridge.runtime_consumers",
            "contract_version": 1,
            "required_target_paths": ["/tmp/libSnnDL.so"],
            "stale_targets": ["/tmp/SnnWorkload.o"],
            "missing_targets": [],
            "rebuild_command": "make libSnnDL.la",
            "snndl_root": "/tmp/SnnDL",
        }
        with mock.patch.object(riscv_snn_lab, "runtime_bridge_build_guard", return_value=expected) as build_guard:
            with mock.patch("builtins.print") as print_mock:
                rc = riscv_snn_lab.main(["runtime-bridge-preflight", "--spec", "/tmp/runtime-bridge.json"])

        self.assertEqual(rc, 2)
        self.assertEqual(build_guard.call_args.kwargs["spec_path"], Path("/tmp/runtime-bridge.json"))
        printed = print_mock.call_args.args[0]
        self.assertIn('"contract_key": "riscv_snn.runtime_bridge.runtime_consumers"', printed)
        self.assertIn('"status": "stale"', printed)
        self.assertIn('"rebuild_command": "make libSnnDL.la"', printed)

    def test_barrier_wfi_order_family_is_registered_with_timing_policy(self) -> None:
        self.assertEqual(
            riscv_snn_lab.EQUIV_FAMILY_SPECS["barrier_wfi_order_ref"]["snn_baseline"],
            "barrier_wfi_order_ref_snn_baseline.json",
        )
        self.assertEqual(
            riscv_snn_lab.EQUIV_FAMILY_SPECS["barrier_wfi_order_ref"]["runtime_bridge"],
            "barrier_wfi_order_ref_runtime_bridge.json",
        )
        self.assertEqual(
            riscv_snn_lab.EQUIV_FAMILY_POLICIES["barrier_wfi_order_ref"]["timing_mode"],
            "wfi_barrier_completion_visibility",
        )

    def test_queue_backpressure_family_is_registered_but_not_default_required(self) -> None:
        self.assertEqual(
            riscv_snn_lab.EQUIV_FAMILY_SPECS["queue_backpressure_ref"]["snn_baseline"],
            "queue_backpressure_ref_snn_baseline.json",
        )
        self.assertEqual(
            riscv_snn_lab.EQUIV_FAMILY_SPECS["queue_backpressure_ref"]["runtime_bridge"],
            "queue_backpressure_ref_runtime_bridge.json",
        )
        self.assertEqual(
            riscv_snn_lab.EQUIV_FAMILY_POLICIES["queue_backpressure_ref"]["fault_mode"],
            "accepted_fault_required",
        )
        self.assertEqual(
            riscv_snn_lab.EQUIV_FAMILY_POLICIES["queue_backpressure_ref"]["queue_mode"],
            "command_overdoorbell_overflow",
        )
        self.assertNotIn("queue_backpressure_ref", riscv_snn_lab.authority_required_families())
        self.assertNotIn("queue_backpressure_ref", riscv_snn_lab.matrix_programs("builder"))
        self.assertNotIn("queue_backpressure_ref_toolchain", riscv_snn_lab.matrix_programs("toolchain"))

    def test_completion_queue_overflow_family_is_registered_but_not_default_required(self) -> None:
        self.assertEqual(
            riscv_snn_lab.EQUIV_FAMILY_SPECS["completion_queue_overflow_ref"]["snn_baseline"],
            "completion_queue_overflow_ref_snn_baseline.json",
        )
        self.assertEqual(
            riscv_snn_lab.EQUIV_FAMILY_SPECS["completion_queue_overflow_ref"]["runtime_bridge"],
            "completion_queue_overflow_ref_runtime_bridge.json",
        )
        self.assertEqual(
            riscv_snn_lab.EQUIV_FAMILY_POLICIES["completion_queue_overflow_ref"]["fault_mode"],
            "accepted_fault_required",
        )
        self.assertEqual(
            riscv_snn_lab.EQUIV_FAMILY_POLICIES["completion_queue_overflow_ref"]["queue_mode"],
            "completion_queue_overflow_after_visible_completion",
        )
        self.assertNotIn("completion_queue_overflow_ref", riscv_snn_lab.authority_required_families())
        self.assertNotIn("completion_queue_overflow_ref", riscv_snn_lab.matrix_programs("builder"))
        self.assertNotIn("completion_queue_overflow_ref_toolchain", riscv_snn_lab.matrix_programs("toolchain"))

    def test_research_report_exporter_reads_sidecar_and_writes_summary(self) -> None:
        script = riscv_snn_lab.LAB_ROOT / "tools" / "export_riscv_snn_research_report.py"
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            sidecar_path = td_path / "nightly-sidecar-report.json"
            output_path = td_path / "research-report.json"
            equiv_path = td_path / "2026-03-28-equiv-matrix-subset-deadbeefcafe.json"
            full_equiv_path = td_path / "2026-03-28-equiv-matrix.json"
            queue_equiv_path = td_path / "2026-03-28-equiv-matrix-queue-optional.json"
            artifact_isolation_path = td_path / "artifact-isolation-report.json"
            full_equiv_history_path = td_path / "full-equivalence-history.json"
            artifact_isolation_history_path = td_path / "artifact-isolation-history.json"
            equiv_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "dated_equivalence_matrix",
                        "canonical_surface": False,
                        "requested_group": "all",
                        "count": 1,
                        "families": [
                            {
                                "family": "external_dyn_desc_ref",
                                "status": "PASS",
                                "gate_reasons": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            full_equiv_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "dated_equivalence_matrix",
                        "canonical_surface": True,
                        "requested_group": "all",
                        "count": 8,
                        "families": [],
                    }
                ),
                encoding="utf-8",
            )
            queue_equiv_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "dated_equivalence_matrix",
                        "canonical_surface": True,
                        "requested_group": "queue_optional",
                        "count": 2,
                        "families": [],
                    }
                ),
                encoding="utf-8",
            )
            artifact_isolation_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_artifact_isolation_check",
                        "all_ok": True,
                        "summary_path": str(artifact_isolation_path),
                        "surfaces": {
                            "nightly": {
                                "canonical_unchanged": True,
                                "subset_surface": "subset",
                                "subset_summary_path": str(td_path / "2026-03-28-nightly-index-subset-e64390052e2e.json"),
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            full_equiv_history_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_full_equivalence_history",
                        "summary_path": str(full_equiv_history_path),
                        "latest_date": "2026-03-28",
                        "entry_count": 2,
                    }
                ),
                encoding="utf-8",
            )
            artifact_isolation_history_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_artifact_isolation_history",
                        "summary_path": str(artifact_isolation_history_path),
                        "latest_date": "2026-03-28",
                        "entry_count": 1,
                    }
                ),
                encoding="utf-8",
            )
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "gate_ok": True,
                        "reasons": [],
                        "nightly_index": {
                            "summary_path": str(td_path / "2026-03-28-nightly-index.json"),
                            "canonical_surface": True,
                            "count": 6,
                        },
                        "equivalence": {
                            "summary_path": str(equiv_path),
                            "canonical_surface": False,
                            "requested_group": "all",
                        },
                        "full_equivalence": {
                            "summary_path": str(full_equiv_path),
                            "canonical_surface": True,
                            "requested_group": "all",
                        },
                        "queue_equivalence": {
                            "summary_path": str(queue_equiv_path),
                            "canonical_surface": True,
                            "requested_group": "queue_optional",
                        },
                        "artifact_isolation": {
                            "summary_path": str(artifact_isolation_path),
                            "all_ok": True,
                        },
                        "full_equivalence_history": {
                            "summary_path": str(full_equiv_history_path),
                        },
                        "artifact_isolation_history": {
                            "summary_path": str(artifact_isolation_history_path),
                        },
                        "history_index": {
                            "latest_date": "2026-03-27",
                            "entries": [],
                        },
                    }
                ),
                encoding="utf-8",
            )

            proc = subprocess.run(
                ["python3", str(script), "--sidecar", str(sidecar_path), "--output", str(output_path)],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertTrue(output_path.exists())
            report = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(report["artifact_role"], "research_metrics_summary")
            self.assertEqual(report["authority_scope"], "research_metrics_only")
            self.assertEqual(report["artifact_surfaces"]["nightly_index"]["surface"], "canonical")
            self.assertEqual(report["artifact_surfaces"]["equivalence"]["surface"], "subset")
            self.assertEqual(report["artifact_surfaces"]["full_equivalence"]["surface"], "canonical")
            self.assertEqual(report["artifact_surfaces"]["queue_equivalence"]["surface"], "canonical")
            self.assertFalse(report["artifact_surfaces"]["equivalence"]["canonical_surface"])
            self.assertTrue(report["artifact_isolation"]["all_ok"])
            self.assertEqual(report["authority_entrypoint"]["artifact_role"], "stable_top_level_gate")
            self.assertEqual(report["authority_entrypoint"]["summary_path"], str(sidecar_path))
            self.assertEqual(report["optional_surface_rollups"]["full_equivalence"]["latest_date"], "2026-03-28")
            self.assertEqual(report["optional_surface_rollups"]["artifact_isolation"]["entry_count"], 1)

    def test_research_report_exporter_passes_through_observer_entrypoint_and_prefers_observer_rollups(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            sidecar_path = td_path / "nightly-sidecar-report.json"
            observer_path = td_path / "nightly-sidecar-observer-summary.json"
            output_path = td_path / "research-report.json"

            observer_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_sidecar_observer_summary",
                        "authority_scope": "observer_surface_only",
                        "summary_path": str(observer_path),
                        "optional_group_rollups": {
                            "queue_optional": {
                                "history_path": str(td_path / "queue-optional-equivalence-history.json"),
                                "latest_date": "2026-03-29",
                                "entry_count": 3,
                                "all_ok_latest": True,
                                "all_dates_ok": True,
                                "history_contract": "canonical_queue_optional_only",
                            },
                            "latency_optional": {
                                "history_path": str(td_path / "latency-optional-equivalence-history.json"),
                                "latest_date": "2026-03-28",
                                "entry_count": 2,
                                "all_ok_latest": True,
                                "all_dates_ok": True,
                                "history_contract": "canonical_latency_optional_only",
                            },
                        },
                        "optional_surfaces": {
                            "full_equivalence": {
                                "history_path": str(td_path / "full-equivalence-history.json"),
                                "latest_date": "2026-03-28",
                                "entry_count": 4,
                                "all_ok_latest": True,
                            },
                            "artifact_isolation": {
                                "history_path": str(td_path / "artifact-isolation-history.json"),
                                "latest_date": "2026-03-28",
                                "entry_count": 2,
                                "all_ok_latest": False,
                            },
                            "queue_equivalence": {
                                "history_path": str(td_path / "queue-optional-equivalence-history.json"),
                                "latest_date": "2026-03-29",
                                "entry_count": 3,
                                "all_ok_latest": True,
                                "all_dates_ok": True,
                                "history_contract": "canonical_queue_optional_only",
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "gate_ok": True,
                        "reasons": [],
                        "observer_summary_path": str(observer_path),
                        "history_index": {
                            "latest_date": "2026-03-28",
                            "entries": [],
                        },
                    }
                ),
                encoding="utf-8",
            )

            resolved = export_riscv_snn_research_report.generate_research_report(
                sidecar_path=sidecar_path,
                output_path=output_path,
            )
            report = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(resolved, output_path)
        self.assertEqual(report["observer_entrypoint"]["summary_path"], str(observer_path))
        self.assertEqual(report["observer_entrypoint"]["artifact_role"], "stable_sidecar_observer_summary")
        self.assertEqual(report["optional_surface_rollups"]["full_equivalence"]["summary_path"], str(td_path / "full-equivalence-history.json"))
        self.assertEqual(report["optional_surface_rollups"]["full_equivalence"]["entry_count"], 4)
        self.assertEqual(report["optional_surface_rollups"]["artifact_isolation"]["entry_count"], 2)
        self.assertFalse(report["optional_surface_rollups"]["artifact_isolation"]["all_ok_latest"])
        self.assertEqual(
            report["optional_surface_rollups"]["queue_equivalence"]["summary_path"],
            str(td_path / "queue-optional-equivalence-history.json"),
        )
        self.assertEqual(report["optional_surface_rollups"]["queue_equivalence"]["entry_count"], 3)
        self.assertEqual(
            report["optional_surface_rollups"]["queue_equivalence"]["history_contract"],
            "canonical_queue_optional_only",
        )
        self.assertEqual(
            report["optional_group_rollups"]["latency_optional"]["summary_path"],
            str(td_path / "latency-optional-equivalence-history.json"),
        )
        self.assertEqual(report["optional_group_rollups"]["latency_optional"]["entry_count"], 2)

    def test_research_report_exporter_preserves_generic_optional_group_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            sidecar_path = td_path / "nightly-sidecar-report.json"
            observer_path = td_path / "nightly-sidecar-observer-summary.json"
            output_path = td_path / "research-report.json"
            completion_surface_path = td_path / "2026-04-01-equiv-matrix-completion-overflow-optional.json"

            completion_surface_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "dated_equivalence_matrix",
                        "summary_path": str(completion_surface_path),
                        "canonical_surface": False,
                        "requested_group": "completion_overflow_optional",
                        "count": 1,
                        "families": [],
                    }
                ),
                encoding="utf-8",
            )
            observer_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_sidecar_observer_summary",
                        "authority_scope": "observer_surface_only",
                        "summary_path": str(observer_path),
                        "optional_group_rollups": {
                            "completion_overflow_optional": {
                                "history_path": str(td_path / "completion-overflow-optional-equivalence-history.json"),
                                "latest_date": "2026-04-01",
                                "entry_count": 2,
                                "all_ok_latest": True,
                                "all_dates_ok": True,
                                "history_contract": "canonical_completion_overflow_optional_only",
                            }
                        },
                        "optional_surfaces": {},
                    }
                ),
                encoding="utf-8",
            )
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "gate_ok": True,
                        "reasons": [],
                        "observer_summary_path": str(observer_path),
                        "optional_group_surfaces": {
                            "completion_overflow_optional": {
                                "summary_path": str(completion_surface_path),
                                "canonical_surface": False,
                                "requested_group": "completion_overflow_optional",
                                "count": 1,
                            }
                        },
                        "history_index": {
                            "latest_date": "2026-04-01",
                            "entries": [],
                        },
                    }
                ),
                encoding="utf-8",
            )

            export_riscv_snn_research_report.generate_research_report(
                sidecar_path=sidecar_path,
                output_path=output_path,
            )
            report = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(
            report["optional_group_surfaces"]["completion_overflow_optional"]["summary_path"],
            str(completion_surface_path),
        )
        self.assertEqual(
            report["optional_group_surfaces"]["completion_overflow_optional"]["surface"],
            "subset",
        )
        self.assertEqual(
            report["optional_group_surfaces"]["completion_overflow_optional"]["requested_group"],
            "completion_overflow_optional",
        )
        self.assertEqual(
            report["optional_group_rollups"]["completion_overflow_optional"]["history_contract"],
            "canonical_completion_overflow_optional_only",
        )
        self.assertIsNone(report["artifact_surfaces"]["queue_equivalence"])

    def test_research_report_exporter_propagates_observer_fail_recovery_markers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            sidecar_path = td_path / "nightly-sidecar-report.json"
            observer_path = td_path / "nightly-sidecar-observer-summary.json"
            output_path = td_path / "research-report.json"

            observer_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_sidecar_observer_summary",
                        "authority_scope": "observer_surface_only",
                        "summary_path": str(observer_path),
                        "optional_surfaces": {
                            "full_equivalence": {
                                "history_path": str(td_path / "full-equivalence-history.json"),
                                "latest_summary_path": str(td_path / "2026-03-28-equiv-matrix.json"),
                                "latest_date": "2026-03-28",
                                "entry_count": 3,
                                "all_ok_latest": True,
                                "all_dates_ok": False,
                                "first_fail_date": "2026-03-27",
                                "latest_recovered_date": "2026-03-28",
                                "history_contract": "canonical_full_all_only",
                                "excluded_entry_count": 2,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "gate_ok": True,
                        "reasons": [],
                        "observer_summary_path": str(observer_path),
                        "history_index": {
                            "latest_date": "2026-03-28",
                            "entries": [],
                        },
                    }
                ),
                encoding="utf-8",
            )

            export_riscv_snn_research_report.generate_research_report(
                sidecar_path=sidecar_path,
                output_path=output_path,
            )
            report = json.loads(output_path.read_text(encoding="utf-8"))

        full_rollup = report["optional_surface_rollups"]["full_equivalence"]
        self.assertFalse(full_rollup["all_dates_ok"])
        self.assertEqual(full_rollup["first_fail_date"], "2026-03-27")
        self.assertEqual(full_rollup["latest_recovered_date"], "2026-03-28")
        self.assertEqual(full_rollup["excluded_entry_count"], 2)
        self.assertEqual(full_rollup["history_contract"], "canonical_full_all_only")
        self.assertEqual(full_rollup["latest_summary_path"], str(td_path / "2026-03-28-equiv-matrix.json"))

    def test_research_report_exporter_rejects_invalid_observer_entrypoint_contract(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            sidecar_path = td_path / "nightly-sidecar-report.json"
            observer_path = td_path / "nightly-sidecar-observer-summary.json"
            output_path = td_path / "research-report.json"

            observer_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "dated_equivalence_matrix",
                        "authority_scope": "family_level_equivalence_authority",
                        "summary_path": str(observer_path),
                    }
                ),
                encoding="utf-8",
            )
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "gate_ok": True,
                        "reasons": [],
                        "observer_summary_path": str(observer_path),
                        "history_index": {
                            "latest_date": "2026-03-28",
                            "entries": [],
                        },
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                export_riscv_snn_research_report.generate_research_report(
                    sidecar_path=sidecar_path,
                    output_path=output_path,
                )

    def test_research_report_exporter_marks_observer_adequacy_ready_waiting_for_real_sample(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            sidecar_path = td_path / "nightly-sidecar-report.json"
            observer_path = td_path / "nightly-sidecar-observer-summary.json"
            output_path = td_path / "research-report.json"

            observer_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_sidecar_observer_summary",
                        "authority_scope": "observer_surface_only",
                        "summary_path": str(observer_path),
                        "optional_surfaces": {
                            "full_equivalence": {
                                "history_path": str(td_path / "full-equivalence-history.json"),
                                "latest_summary_path": str(td_path / "2026-03-28-equiv-matrix.json"),
                                "latest_date": "2026-03-28",
                                "entry_count": 2,
                                "all_ok_latest": True,
                                "all_dates_ok": True,
                                "first_fail_date": None,
                                "latest_recovered_date": None,
                                "history_contract": "canonical_full_all_only",
                                "excluded_entry_count": 1,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "gate_ok": True,
                        "reasons": [],
                        "observer_summary_path": str(observer_path),
                        "history_index": {
                            "latest_date": "2026-03-28",
                            "entries": [],
                        },
                    }
                ),
                encoding="utf-8",
            )

            export_riscv_snn_research_report.generate_research_report(
                sidecar_path=sidecar_path,
                output_path=output_path,
            )
            report = json.loads(output_path.read_text(encoding="utf-8"))

        adequacy = report["observer_adequacy"]
        self.assertTrue(adequacy["has_observer_entrypoint"])
        self.assertTrue(adequacy["contract_ok"])
        self.assertTrue(adequacy["full_equivalence_markers_present"])
        self.assertFalse(adequacy["real_fail_sample_present"])
        self.assertFalse(adequacy["real_recovery_sample_present"])
        self.assertEqual(adequacy["status"], "ready_waiting_for_real_sample")
        self.assertEqual(adequacy["next_action"], "wait_for_real_canonical_fail_recovery_sample")

    def test_research_report_exporter_marks_observer_adequacy_ready_with_fail_recovery_sample(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            sidecar_path = td_path / "nightly-sidecar-report.json"
            observer_path = td_path / "nightly-sidecar-observer-summary.json"
            output_path = td_path / "research-report.json"

            observer_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_sidecar_observer_summary",
                        "authority_scope": "observer_surface_only",
                        "summary_path": str(observer_path),
                        "optional_surfaces": {
                            "full_equivalence": {
                                "history_path": str(td_path / "full-equivalence-history.json"),
                                "latest_summary_path": str(td_path / "2026-03-28-equiv-matrix.json"),
                                "latest_date": "2026-03-28",
                                "entry_count": 3,
                                "all_ok_latest": True,
                                "all_dates_ok": False,
                                "first_fail_date": "2026-03-27",
                                "latest_recovered_date": "2026-03-28",
                                "history_contract": "canonical_full_all_only",
                                "excluded_entry_count": 2,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "gate_ok": True,
                        "reasons": [],
                        "observer_summary_path": str(observer_path),
                        "history_index": {
                            "latest_date": "2026-03-28",
                            "entries": [],
                        },
                    }
                ),
                encoding="utf-8",
            )

            export_riscv_snn_research_report.generate_research_report(
                sidecar_path=sidecar_path,
                output_path=output_path,
            )
            report = json.loads(output_path.read_text(encoding="utf-8"))

        adequacy = report["observer_adequacy"]
        self.assertTrue(adequacy["has_observer_entrypoint"])
        self.assertTrue(adequacy["contract_ok"])
        self.assertTrue(adequacy["full_equivalence_markers_present"])
        self.assertTrue(adequacy["real_fail_sample_present"])
        self.assertTrue(adequacy["real_recovery_sample_present"])
        self.assertEqual(adequacy["status"], "ready_with_fail_recovery_sample")
        self.assertEqual(adequacy["next_action"], "validate_compact_surface_against_real_fail_recovery_sample")

    def test_observer_adequacy_validator_passes_for_matching_research_rollup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            history_path = td_path / "full-equivalence-history.json"
            report_path = td_path / "research-report.json"
            output_path = td_path / "observer-adequacy-validation.json"

            history_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_full_equivalence_history",
                        "authority_scope": "research_surface_rollup_only",
                        "history_contract": "canonical_full_all_only",
                        "summary_path": str(history_path),
                        "latest_summary_path": str(td_path / "2026-03-28-equiv-matrix.json"),
                        "latest_date": "2026-03-28",
                        "entry_count": 3,
                        "all_ok_latest": True,
                        "all_dates_ok": False,
                        "first_fail_date": "2026-03-27",
                        "latest_recovered_date": "2026-03-28",
                        "excluded_entry_count": 2,
                    }
                ),
                encoding="utf-8",
            )
            report_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "research_metrics_summary",
                        "authority_scope": "research_metrics_only",
                        "observer_entrypoint": {
                            "summary_path": str(td_path / "nightly-sidecar-observer-summary.json"),
                            "artifact_role": "stable_sidecar_observer_summary",
                            "authority_scope": "observer_surface_only",
                        },
                        "optional_surface_rollups": {
                            "full_equivalence": {
                                "summary_path": str(history_path),
                                "latest_summary_path": str(td_path / "2026-03-28-equiv-matrix.json"),
                                "latest_date": "2026-03-28",
                                "entry_count": 3,
                                "all_ok_latest": True,
                                "all_dates_ok": False,
                                "first_fail_date": "2026-03-27",
                                "latest_recovered_date": "2026-03-28",
                                "history_contract": "canonical_full_all_only",
                                "excluded_entry_count": 2,
                            }
                        },
                        "observer_adequacy": {
                            "has_observer_entrypoint": True,
                            "contract_ok": True,
                            "full_equivalence_markers_present": True,
                            "real_fail_sample_present": True,
                            "real_recovery_sample_present": True,
                            "status": "ready_with_fail_recovery_sample",
                            "next_action": "validate_compact_surface_against_real_fail_recovery_sample",
                        },
                    }
                ),
                encoding="utf-8",
            )

            resolved = export_riscv_snn_research_report.validate_observer_adequacy_report(
                report_path=report_path,
                output_path=output_path,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(resolved, output_path)
        self.assertEqual(payload["source"]["artifact_role"], "research_metrics_summary")
        self.assertTrue(payload["validation_required"])
        self.assertTrue(payload["validation_executed"])
        self.assertTrue(payload["validation_ok"])
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["mismatch_count"], 0)
        self.assertEqual(payload["matched_field_count"], 9)

    def test_observer_adequacy_validator_reports_structured_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            history_path = td_path / "full-equivalence-history.json"
            report_path = td_path / "research-report.json"
            output_path = td_path / "observer-adequacy-validation.json"

            history_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_full_equivalence_history",
                        "authority_scope": "research_surface_rollup_only",
                        "history_contract": "canonical_full_all_only",
                        "summary_path": str(history_path),
                        "latest_summary_path": str(td_path / "2026-03-28-equiv-matrix.json"),
                        "latest_date": "2026-03-28",
                        "entry_count": 3,
                        "all_ok_latest": True,
                        "all_dates_ok": False,
                        "first_fail_date": "2026-03-27",
                        "latest_recovered_date": "2026-03-28",
                        "excluded_entry_count": 2,
                    }
                ),
                encoding="utf-8",
            )
            report_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "research_metrics_summary",
                        "authority_scope": "research_metrics_only",
                        "observer_entrypoint": {
                            "summary_path": str(td_path / "nightly-sidecar-observer-summary.json"),
                            "artifact_role": "stable_sidecar_observer_summary",
                            "authority_scope": "observer_surface_only",
                        },
                        "optional_surface_rollups": {
                            "full_equivalence": {
                                "summary_path": str(history_path),
                                "latest_summary_path": str(td_path / "2026-03-28-equiv-matrix.json"),
                                "latest_date": "2026-03-28",
                                "entry_count": 3,
                                "all_ok_latest": True,
                                "all_dates_ok": False,
                                "first_fail_date": "2026-03-27",
                                "latest_recovered_date": "2026-03-29",
                                "history_contract": "canonical_full_all_only",
                                "excluded_entry_count": 2,
                            }
                        },
                        "observer_adequacy": {
                            "has_observer_entrypoint": True,
                            "contract_ok": True,
                            "full_equivalence_markers_present": True,
                            "real_fail_sample_present": True,
                            "real_recovery_sample_present": True,
                            "status": "ready_with_fail_recovery_sample",
                            "next_action": "validate_compact_surface_against_real_fail_recovery_sample",
                        },
                    }
                ),
                encoding="utf-8",
            )

            export_riscv_snn_research_report.validate_observer_adequacy_report(
                report_path=report_path,
                output_path=output_path,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertTrue(payload["validation_required"])
        self.assertTrue(payload["validation_executed"])
        self.assertFalse(payload["validation_ok"])
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["mismatch_count"], 1)
        self.assertEqual(payload["mismatches"][0]["field"], "latest_recovered_date")
        self.assertEqual(payload["mismatches"][0]["expected"], "2026-03-29")
        self.assertEqual(payload["mismatches"][0]["actual"], "2026-03-28")

    def test_observer_adequacy_validator_accepts_stable_sidecar_report(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            sidecar_path = td_path / "nightly-sidecar-report.json"
            observer_path = td_path / "nightly-sidecar-observer-summary.json"
            history_path = td_path / "full-equivalence-history.json"
            output_path = td_path / "observer-adequacy-validation.json"

            history_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_full_equivalence_history",
                        "authority_scope": "research_surface_rollup_only",
                        "history_contract": "canonical_full_all_only",
                        "summary_path": str(history_path),
                        "latest_summary_path": str(td_path / "2026-03-28-equiv-matrix.json"),
                        "latest_date": "2026-03-28",
                        "entry_count": 3,
                        "all_ok_latest": True,
                        "all_dates_ok": False,
                        "first_fail_date": "2026-03-27",
                        "latest_recovered_date": "2026-03-28",
                        "excluded_entry_count": 2,
                    }
                ),
                encoding="utf-8",
            )
            observer_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_sidecar_observer_summary",
                        "authority_scope": "observer_surface_only",
                        "summary_path": str(observer_path),
                        "optional_surfaces": {
                            "full_equivalence": {
                                "history_path": str(history_path),
                                "latest_summary_path": str(td_path / "2026-03-28-equiv-matrix.json"),
                                "latest_date": "2026-03-28",
                                "entry_count": 3,
                                "all_ok_latest": True,
                                "all_dates_ok": False,
                                "first_fail_date": "2026-03-27",
                                "latest_recovered_date": "2026-03-28",
                                "history_contract": "canonical_full_all_only",
                                "excluded_entry_count": 2,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "observer_summary_path": str(observer_path),
                        "history_index": {
                            "latest_date": "2026-03-28",
                            "entries": [],
                        },
                    }
                ),
                encoding="utf-8",
            )

            export_riscv_snn_research_report.validate_observer_adequacy_report(
                report_path=sidecar_path,
                output_path=output_path,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["source"]["artifact_role"], "stable_top_level_gate")
        self.assertEqual(payload["observer_adequacy"]["status"], "ready_with_fail_recovery_sample")
        self.assertTrue(payload["validation_ok"])
        self.assertEqual(payload["history_path"], str(history_path))

    def test_research_report_exporter_rejects_non_stable_sidecar_authority(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            sidecar_path = td_path / "not-a-stable-sidecar.json"
            output_path = td_path / "research-report.json"
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "dated_equivalence_matrix",
                        "authority_scope": "family_level_equivalence_authority",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                export_riscv_snn_research_report.generate_research_report(
                    sidecar_path=sidecar_path,
                    output_path=output_path,
                )

    def test_build_sidecar_observer_summary_writes_compact_machine_readable_view(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            output_path = td_path / "nightly-sidecar-observer-summary.json"
            report = {
                "generated_utc": "2026-03-28T00:00:00+00:00",
                "artifact_role": "stable_top_level_gate",
                "authority_scope": "experimental_gate_authority",
                "report_path": str(td_path / "nightly-sidecar-report.json"),
                "gate_ok": True,
                "gate_name": "riscv_snn_experimental_nightly",
                "required_families": ["external_dyn_desc_ref"],
                "history_index": {
                    "latest_date": "2026-03-28",
                },
                "timing": {
                    "total_elapsed_seconds": 120.5,
                    "blocking_elapsed_seconds": 70.0,
                    "nonblocking_elapsed_seconds": 50.5,
                    "sections": {
                        "nightly_elapsed_seconds": 40.0,
                        "full_equivalence_elapsed_seconds": 30.0,
                        "artifact_isolation_elapsed_seconds": 20.5,
                    },
                },
                "with_full_equivalence": True,
                "with_artifact_isolation": True,
                "queue_equivalence": {
                    "summary_path": str(td_path / "2026-03-28-equiv-matrix-queue-optional.json"),
                    "count": 2,
                    "canonical_surface": True,
                },
                "full_equivalence_history": {
                    "summary_path": str(td_path / "full-equivalence-history.json"),
                    "latest_date": "2026-03-28",
                    "entry_count": 2,
                    "all_ok_latest": True,
                },
                "artifact_isolation_history": {
                    "summary_path": str(td_path / "artifact-isolation-history.json"),
                    "latest_date": "2026-03-28",
                    "entry_count": 1,
                    "all_ok_latest": True,
                },
            }

            resolved = riscv_snn_lab.build_sidecar_observer_summary(report, output_path=output_path, lab_root=td_path)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(resolved, output_path)
        self.assertEqual(payload["artifact_role"], "stable_sidecar_observer_summary")
        self.assertEqual(payload["authority_entrypoint"]["summary_path"], str(td_path / "nightly-sidecar-report.json"))
        self.assertEqual(payload["timing"]["total_elapsed_seconds"], 120.5)
        self.assertEqual(payload["optional_surfaces"]["full_equivalence"]["entry_count"], 2)
        self.assertEqual(payload["optional_surfaces"]["artifact_isolation"]["entry_count"], 1)
        self.assertEqual(payload["summary_path"], str(output_path))

    def test_build_sidecar_observer_summary_carries_compare_supplementary_surface(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            output_path = td_path / "nightly-sidecar-observer-summary.json"
            report = {
                "generated_utc": "2026-04-07T00:00:00+00:00",
                "artifact_role": "stable_top_level_gate",
                "authority_scope": "experimental_gate_authority",
                "report_path": str(td_path / "nightly-sidecar-report.json"),
                "gate_ok": True,
                "gate_name": "riscv_snn_experimental_nightly",
                "required_families": ["external_dyn_desc_ref"],
                "history_index": {
                    "latest_date": "2026-04-07",
                },
                "supplementary_surfaces": {
                    "compare": {
                        "present": True,
                        "gate_ok": True,
                        "latest_date": "2026-04-07",
                        "stale": False,
                        "freshness_mode": "since_latest_recovery",
                        "effective_all_dates_ok": True,
                        "report_path": str(td_path / "compare-nightly-report.json"),
                        "summary_md_path": str(td_path / "compare-nightly-summary.md"),
                        "current_mainline_status_path": str(td_path / "compare-current-status.md"),
                    }
                },
            }

            riscv_snn_lab.build_sidecar_observer_summary(report, output_path=output_path, lab_root=td_path)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        compare_surface = payload["supplementary_surfaces"]["compare"]
        self.assertTrue(compare_surface["present"])
        self.assertEqual(compare_surface["freshness_mode"], "since_latest_recovery")
        self.assertEqual(compare_surface["current_mainline_status_path"], str(td_path / "compare-current-status.md"))

    def test_build_sidecar_observer_summary_builds_compare_supplementary_rollup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            output_path = td_path / "nightly-sidecar-observer-summary.json"
            report = {
                "generated_utc": "2026-04-07T00:00:00+00:00",
                "artifact_role": "stable_top_level_gate",
                "authority_scope": "experimental_gate_authority",
                "report_path": str(td_path / "nightly-sidecar-report.json"),
                "gate_ok": True,
                "gate_name": "riscv_snn_experimental_nightly",
                "required_families": ["external_dyn_desc_ref"],
                "history_index": {
                    "latest_date": "2026-04-07",
                },
                "supplementary_surfaces": {
                    "compare": {
                        "present": True,
                        "blocking": False,
                        "load_error": None,
                        "gate_ok": True,
                        "latest_date": "2026-04-07",
                        "stale": False,
                        "freshness_mode": "since_latest_recovery",
                        "effective_all_dates_ok": True,
                        "report_path": str(td_path / "compare-nightly-report.json"),
                    }
                },
            }

            riscv_snn_lab.build_sidecar_observer_summary(report, output_path=output_path, lab_root=td_path)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        compare_rollup = payload["supplementary_surface_rollups"]["compare"]
        self.assertEqual(compare_rollup["status"], "pass")
        self.assertFalse(compare_rollup["blocking"])
        self.assertTrue(compare_rollup["freshness_ok"])
        self.assertTrue(compare_rollup["healthy"])

    def test_build_sidecar_observer_summary_marks_compare_rollup_degraded_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            output_path = td_path / "nightly-sidecar-observer-summary.json"
            report = {
                "generated_utc": "2026-04-07T00:00:00+00:00",
                "artifact_role": "stable_top_level_gate",
                "authority_scope": "experimental_gate_authority",
                "report_path": str(td_path / "nightly-sidecar-report.json"),
                "gate_ok": True,
                "gate_name": "riscv_snn_experimental_nightly",
                "required_families": ["external_dyn_desc_ref"],
                "history_index": {
                    "latest_date": "2026-04-07",
                },
                "supplementary_surfaces": {
                    "compare": {
                        "present": True,
                        "blocking": False,
                        "load_error": "compare report unreadable",
                        "gate_ok": None,
                        "latest_date": None,
                        "stale": True,
                        "freshness_mode": "since_latest_recovery",
                        "effective_all_dates_ok": False,
                        "report_path": str(td_path / "compare-nightly-report.json"),
                    }
                },
            }

            riscv_snn_lab.build_sidecar_observer_summary(report, output_path=output_path, lab_root=td_path)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        compare_rollup = payload["supplementary_surface_rollups"]["compare"]
        self.assertEqual(compare_rollup["status"], "degraded")
        self.assertFalse(compare_rollup["blocking"])
        self.assertFalse(compare_rollup["healthy"])
        self.assertEqual(compare_rollup["load_error"], "compare report unreadable")

    def test_build_sidecar_observer_summary_carries_history_health_markers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            output_path = td_path / "nightly-sidecar-observer-summary.json"
            report = {
                "artifact_role": "stable_top_level_gate",
                "authority_scope": "experimental_gate_authority",
                "report_path": str(td_path / "nightly-sidecar-report.json"),
                "history_index": {
                    "latest_date": "2026-03-28",
                },
                "full_equivalence_history": {
                    "summary_path": str(td_path / "full-equivalence-history.json"),
                    "history_contract": "canonical_full_all_only",
                    "latest_summary_path": str(td_path / "2026-03-28-equiv-matrix.json"),
                    "latest_date": "2026-03-28",
                    "entry_count": 2,
                    "all_ok_latest": False,
                    "all_dates_ok": False,
                    "first_fail_date": "2026-03-28",
                    "latest_recovered_date": None,
                    "excluded_entry_count": 1,
                },
            }

            riscv_snn_lab.build_sidecar_observer_summary(report, output_path=output_path, lab_root=td_path)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        full_equivalence = payload["optional_surfaces"]["full_equivalence"]
        self.assertEqual(full_equivalence["history_contract"], "canonical_full_all_only")
        self.assertEqual(full_equivalence["latest_summary_path"], str(td_path / "2026-03-28-equiv-matrix.json"))
        self.assertFalse(full_equivalence["all_dates_ok"])
        self.assertEqual(full_equivalence["first_fail_date"], "2026-03-28")
        self.assertIsNone(full_equivalence["latest_recovered_date"])
        self.assertEqual(full_equivalence["excluded_entry_count"], 1)

    def test_refresh_observer_full_equivalence_history_preserves_same_day_fail_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            fail_history = riscv_snn_lab.refresh_observer_full_equivalence_history(
                full_equivalence={
                    "artifact_role": "dated_equivalence_matrix",
                    "canonical_surface": True,
                    "requested_group": "all",
                    "all_ok": False,
                    "count": 6,
                    "summary_path": str(refs_dir / "2026-03-30-equiv-matrix.json"),
                    "generated_utc": "2026-03-30T01:00:00+00:00",
                    "families": [{"family": "external_dyn_desc_ref"}],
                },
                lab_root=lab_root,
            )
            recovered_history = riscv_snn_lab.refresh_observer_full_equivalence_history(
                full_equivalence={
                    "artifact_role": "dated_equivalence_matrix",
                    "canonical_surface": True,
                    "requested_group": "all",
                    "all_ok": True,
                    "count": 6,
                    "summary_path": str(refs_dir / "2026-03-30-equiv-matrix.json"),
                    "generated_utc": "2026-03-30T02:00:00+00:00",
                    "families": [{"family": "external_dyn_desc_ref"}],
                },
                lab_root=lab_root,
            )

        self.assertEqual(fail_history["artifact_role"], "stable_observer_full_equivalence_history")
        self.assertEqual(recovered_history["history_contract"], "observer_sample_sequence_v1")
        self.assertEqual(recovered_history["entry_count"], 2)
        self.assertEqual(recovered_history["latest_date"], "2026-03-30")
        self.assertEqual(recovered_history["first_fail_date"], "2026-03-30")
        self.assertEqual(recovered_history["latest_recovered_date"], "2026-03-30")
        self.assertEqual(
            recovered_history["entries"][0]["sample_generated_utc"],
            "2026-03-30T02:00:00+00:00",
        )
        self.assertEqual(
            recovered_history["entries"][1]["sample_generated_utc"],
            "2026-03-30T01:00:00+00:00",
        )

    def test_refresh_observer_full_equivalence_history_can_compact_since_latest_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            riscv_snn_lab.refresh_observer_full_equivalence_history(
                full_equivalence={
                    "artifact_role": "dated_equivalence_matrix",
                    "canonical_surface": True,
                    "requested_group": "all",
                    "all_ok": True,
                    "count": 6,
                    "summary_path": str(refs_dir / "2026-03-29-equiv-matrix.json"),
                    "generated_utc": "2026-03-29T01:00:00+00:00",
                    "families": [{"family": "external_dyn_desc_ref"}],
                },
                lab_root=lab_root,
            )
            riscv_snn_lab.refresh_observer_full_equivalence_history(
                full_equivalence={
                    "artifact_role": "dated_equivalence_matrix",
                    "canonical_surface": True,
                    "requested_group": "all",
                    "all_ok": False,
                    "count": 6,
                    "summary_path": str(refs_dir / "2026-03-30-equiv-matrix.json"),
                    "generated_utc": "2026-03-30T01:00:00+00:00",
                    "families": [{"family": "external_dyn_desc_ref"}],
                },
                lab_root=lab_root,
            )
            compacted = riscv_snn_lab.refresh_observer_full_equivalence_history(
                full_equivalence={
                    "artifact_role": "dated_equivalence_matrix",
                    "canonical_surface": True,
                    "requested_group": "all",
                    "all_ok": True,
                    "count": 6,
                    "summary_path": str(refs_dir / "2026-03-31-equiv-matrix.json"),
                    "generated_utc": "2026-03-31T01:00:00+00:00",
                    "families": [{"family": "external_dyn_desc_ref"}],
                },
                compact_since_latest_recovery=True,
                lab_root=lab_root,
            )

        self.assertEqual(compacted["refresh_mode"], "compact_latest_recovery")
        self.assertEqual(compacted["entry_count"], 3)
        self.assertEqual(compacted["effective_entry_count"], 1)
        self.assertEqual(compacted["latest_recovered_date"], "2026-03-31")
        self.assertEqual(compacted["compacted_entry_count"], 2)
        self.assertEqual(compacted["compacted_entries"][0]["date"], "2026-03-30")

    def test_build_sidecar_observer_summary_prefers_observer_sample_history(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            output_path = td_path / "nightly-sidecar-observer-summary.json"
            report = {
                "artifact_role": "stable_top_level_gate",
                "authority_scope": "experimental_gate_authority",
                "report_path": str(td_path / "nightly-sidecar-report.json"),
                "history_index": {
                    "latest_date": "2026-03-30",
                },
                "full_equivalence_history": {
                    "summary_path": str(td_path / "full-equivalence-history.json"),
                    "history_contract": "canonical_full_all_only",
                    "latest_summary_path": str(td_path / "2026-03-30-equiv-matrix.json"),
                    "latest_date": "2026-03-30",
                    "entry_count": 1,
                    "all_ok_latest": True,
                    "all_dates_ok": True,
                    "first_fail_date": None,
                    "latest_recovered_date": None,
                    "excluded_entry_count": 0,
                },
                "observer_full_equivalence_history": {
                    "summary_path": str(td_path / "observer-full-equivalence-history.json"),
                    "history_contract": "observer_sample_sequence_v1",
                    "refresh_mode": "compact_latest_recovery",
                    "latest_summary_path": str(td_path / "2026-03-30-equiv-matrix.json"),
                    "latest_date": "2026-03-30",
                    "entry_count": 2,
                    "effective_entry_count": 1,
                    "effective_all_dates_ok": True,
                    "all_ok_latest": True,
                    "all_dates_ok": False,
                    "first_fail_date": "2026-03-30",
                    "latest_recovered_date": "2026-03-30",
                    "excluded_entry_count": 0,
                },
            }

            riscv_snn_lab.build_sidecar_observer_summary(report, output_path=output_path, lab_root=td_path)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        full_equivalence = payload["optional_surfaces"]["full_equivalence"]
        self.assertEqual(
            full_equivalence["history_path"],
            str(td_path / "observer-full-equivalence-history.json"),
        )
        self.assertEqual(full_equivalence["history_contract"], "observer_sample_sequence_v1")
        self.assertEqual(full_equivalence["refresh_mode"], "compact_latest_recovery")
        self.assertEqual(full_equivalence["effective_entry_count"], 1)
        self.assertTrue(full_equivalence["effective_all_dates_ok"])
        self.assertEqual(full_equivalence["first_fail_date"], "2026-03-30")
        self.assertEqual(full_equivalence["latest_recovered_date"], "2026-03-30")

    def test_build_sidecar_observer_summary_aligns_queue_history_and_admission_surface(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            refs_dir = td_path / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)
            output_path = refs_dir / "nightly-sidecar-observer-summary.json"
            queue_history_path = refs_dir / "queue-optional-equivalence-history.json"
            queue_history_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_optional_equivalence_history",
                        "group": "queue_optional",
                        "history_contract": "canonical_queue_optional_only",
                        "summary_path": str(queue_history_path),
                        "latest_summary_path": str(refs_dir / "2026-03-31-equiv-matrix-queue-optional.json"),
                        "latest_date": "2026-03-31",
                        "entry_count": 3,
                        "all_ok_latest": True,
                        "all_dates_ok": True,
                        "first_fail_date": None,
                        "latest_recovered_date": "2026-03-31",
                        "excluded_entry_count": 0,
                    }
                ),
                encoding="utf-8",
            )
            queue_audit_path = refs_dir / "2026-03-31-queue-optional-admission-audit.json"
            queue_audit_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "dated_family_admission_audit",
                        "group": "queue_optional",
                        "summary_path": str(queue_audit_path),
                        "promotion_ready": True,
                        "explicit_review_ok": True,
                        "blocking": False,
                        "queue_history_path": str(queue_history_path),
                        "queue_history_entry_count": 3,
                        "queue_history_all_dates_ok": True,
                    }
                ),
                encoding="utf-8",
            )
            report = {
                "generated_utc": "2026-03-31T00:00:00+00:00",
                "artifact_role": "stable_top_level_gate",
                "authority_scope": "experimental_gate_authority",
                "report_path": str(refs_dir / "nightly-sidecar-report.json"),
                "gate_ok": True,
                "gate_name": "riscv_snn_experimental_nightly",
                "gate_version": "1.1",
                "required_families": ["external_dyn_desc_ref"],
                "history_index": {"latest_date": "2026-03-31"},
            }

            riscv_snn_lab.build_sidecar_observer_summary(report, output_path=output_path, lab_root=td_path)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        queue_equivalence = payload["optional_surfaces"]["queue_equivalence"]
        self.assertTrue(queue_equivalence["enabled"])
        self.assertEqual(queue_equivalence["history_path"], str(queue_history_path))
        self.assertEqual(queue_equivalence["history_contract"], "canonical_queue_optional_only")
        self.assertEqual(queue_equivalence["entry_count"], 3)
        self.assertTrue(queue_equivalence["all_dates_ok"])
        self.assertEqual(queue_equivalence["admission_summary_path"], str(queue_audit_path))
        self.assertTrue(queue_equivalence["promotion_ready"])
        self.assertTrue(queue_equivalence["explicit_review_ok"])

    def test_build_sidecar_observer_summary_carries_effective_optional_freshness_from_admission(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            refs_dir = td_path / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)
            output_path = refs_dir / "nightly-sidecar-observer-summary.json"
            queue_history_path = refs_dir / "queue-optional-equivalence-history.json"
            queue_history_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_optional_equivalence_history",
                        "group": "queue_optional",
                        "history_contract": "canonical_queue_optional_only",
                        "summary_path": str(queue_history_path),
                        "latest_summary_path": str(refs_dir / "2026-03-31-equiv-matrix-queue-optional.json"),
                        "latest_date": "2026-03-31",
                        "entry_count": 4,
                        "all_ok_latest": True,
                        "all_dates_ok": False,
                        "first_fail_date": "2026-03-30",
                        "latest_recovered_date": "2026-03-31",
                        "excluded_entry_count": 0,
                    }
                ),
                encoding="utf-8",
            )
            queue_audit_path = refs_dir / "2026-03-31-queue-optional-admission-audit.json"
            queue_audit_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "dated_family_admission_audit",
                        "group": "queue_optional",
                        "summary_path": str(queue_audit_path),
                        "promotion_ready": True,
                        "explicit_review_ok": True,
                        "blocking": False,
                        "group_history_freshness_mode": "since_latest_recovery",
                        "group_history_effective_entry_count": 1,
                        "group_history_effective_all_dates_ok": True,
                    }
                ),
                encoding="utf-8",
            )
            report = {
                "generated_utc": "2026-03-31T00:00:00+00:00",
                "artifact_role": "stable_top_level_gate",
                "authority_scope": "experimental_gate_authority",
                "report_path": str(refs_dir / "nightly-sidecar-report.json"),
                "gate_ok": True,
                "gate_name": "riscv_snn_experimental_nightly",
                "gate_version": "1.1",
                "required_families": ["external_dyn_desc_ref"],
                "history_index": {"latest_date": "2026-03-31"},
            }

            riscv_snn_lab.build_sidecar_observer_summary(report, output_path=output_path, lab_root=td_path)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        queue_rollup = payload["optional_group_rollups"]["queue_optional"]
        self.assertEqual(queue_rollup["freshness_mode"], "since_latest_recovery")
        self.assertEqual(queue_rollup["effective_entry_count"], 1)
        self.assertTrue(queue_rollup["effective_all_dates_ok"])
        self.assertEqual(
            payload["optional_surfaces"]["queue_equivalence"]["effective_all_dates_ok"],
            True,
        )

    def test_build_sidecar_observer_summary_exports_authority_optional_group_rollups(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            refs_dir = td_path / "references"
            spec_dir = td_path / "spec_authority"
            refs_dir.mkdir(parents=True, exist_ok=True)
            spec_dir.mkdir(parents=True, exist_ok=True)
            (spec_dir / "riscv_snn_mainline_gate_v1.json").write_text(
                json.dumps(
                    {
                        "required_families": ["external_dyn_desc_ref"],
                        "optional_groups": {
                            "queue_optional": {
                                "families": ["queue_backpressure_ref"],
                                "blocking": False,
                            },
                            "latency_optional": {
                                "families": ["latency_probe_ref"],
                                "blocking": False,
                            },
                        },
                        "promotion_contract": {
                            "queue_optional": {"requires_multi_date_freshness": True},
                            "latency_optional": {"requires_multi_date_freshness": True},
                        },
                    }
                ),
                encoding="utf-8",
            )
            output_path = refs_dir / "nightly-sidecar-observer-summary.json"
            for group in ("queue_optional", "latency_optional"):
                history_path = refs_dir / f"{group.replace('_', '-')}-equivalence-history.json"
                history_path.write_text(
                    json.dumps(
                        {
                            "artifact_role": "stable_optional_equivalence_history",
                            "group": group,
                            "history_contract": f"canonical_{group}_only",
                            "summary_path": str(history_path),
                            "latest_summary_path": str(refs_dir / f"2026-03-31-equiv-matrix-{group.replace('_', '-')}.json"),
                            "latest_date": "2026-03-31",
                            "entry_count": 2,
                            "all_ok_latest": True,
                            "all_dates_ok": True,
                            "first_fail_date": None,
                            "latest_recovered_date": "2026-03-31",
                            "excluded_entry_count": 0,
                        }
                    ),
                    encoding="utf-8",
                )
                audit_path = refs_dir / f"2026-03-31-{group.replace('_', '-')}-admission-audit.json"
                audit_path.write_text(
                    json.dumps(
                        {
                            "artifact_role": "dated_family_admission_audit",
                            "group": group,
                            "summary_path": str(audit_path),
                            "promotion_ready": True,
                            "explicit_review_ok": True,
                            "blocking": False,
                        }
                    ),
                    encoding="utf-8",
                )
            report = {
                "generated_utc": "2026-03-31T00:00:00+00:00",
                "artifact_role": "stable_top_level_gate",
                "authority_scope": "experimental_gate_authority",
                "report_path": str(refs_dir / "nightly-sidecar-report.json"),
                "gate_ok": True,
                "gate_name": "riscv_snn_experimental_nightly",
                "gate_version": "1.1",
                "required_families": ["external_dyn_desc_ref"],
                "history_index": {"latest_date": "2026-03-31"},
            }

            riscv_snn_lab.build_sidecar_observer_summary(report, output_path=output_path, lab_root=td_path)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(
            payload["optional_group_rollups"]["queue_optional"]["history_contract"],
            "canonical_queue_optional_only",
        )
        self.assertEqual(
            payload["optional_group_rollups"]["latency_optional"]["history_contract"],
            "canonical_latency_optional_only",
        )
        self.assertEqual(
            payload["optional_surfaces"]["queue_equivalence"]["history_contract"],
            payload["optional_group_rollups"]["queue_optional"]["history_contract"],
        )

    def test_build_sidecar_observer_summary_exports_effective_optional_group_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            refs_dir = td_path / "references"
            spec_dir = td_path / "spec_authority"
            refs_dir.mkdir(parents=True, exist_ok=True)
            spec_dir.mkdir(parents=True, exist_ok=True)
            (spec_dir / "riscv_snn_mainline_gate_v1.json").write_text(
                json.dumps(
                    {
                        "required_families": ["external_dyn_desc_ref"],
                        "optional_groups": {
                            "queue_optional": {
                                "families": ["queue_backpressure_ref"],
                                "blocking": False,
                            }
                        },
                        "promotion_contract": {
                            "queue_optional": {
                                "requires_multi_date_freshness": True,
                                "multi_date_freshness_mode": "since_latest_recovery",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            output_path = refs_dir / "nightly-sidecar-observer-summary.json"
            history_path = refs_dir / "queue-optional-equivalence-history.json"
            history_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_optional_equivalence_history",
                        "group": "queue_optional",
                        "history_contract": "canonical_queue_optional_only",
                        "summary_path": str(history_path),
                        "latest_summary_path": str(refs_dir / "2026-04-03-equiv-matrix-queue-optional.json"),
                        "latest_date": "2026-04-03",
                        "entry_count": 3,
                        "all_ok_latest": True,
                        "all_dates_ok": False,
                        "first_fail_date": "2026-04-01",
                        "latest_recovered_date": "2026-04-03",
                        "entries": [
                            {"date": "2026-04-03", "all_ok": True},
                            {"date": "2026-04-02", "all_ok": False},
                            {"date": "2026-03-31", "all_ok": True},
                        ],
                        "excluded_entries": [],
                        "excluded_entry_count": 0,
                    }
                ),
                encoding="utf-8",
            )
            audit_path = refs_dir / "2026-04-04-queue-optional-admission-audit.json"
            audit_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "dated_family_admission_audit",
                        "group": "queue_optional",
                        "summary_path": str(audit_path),
                        "promotion_ready": True,
                        "explicit_review_ok": True,
                        "blocking": False,
                        "group_history_freshness_mode": "since_latest_recovery",
                        "group_history_effective_entry_count": 1,
                        "group_history_effective_all_dates_ok": True,
                    }
                ),
                encoding="utf-8",
            )
            report = {
                "generated_utc": "2026-04-04T00:00:00+00:00",
                "artifact_role": "stable_top_level_gate",
                "authority_scope": "experimental_gate_authority",
                "report_path": str(refs_dir / "nightly-sidecar-report.json"),
                "gate_ok": True,
                "gate_name": "riscv_snn_experimental_nightly",
                "gate_version": "1.1",
                "required_families": ["external_dyn_desc_ref"],
                "history_index": {"latest_date": "2026-04-03"},
            }

            riscv_snn_lab.build_sidecar_observer_summary(report, output_path=output_path, lab_root=td_path)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        queue_rollup = payload["optional_group_rollups"]["queue_optional"]
        self.assertEqual(queue_rollup["freshness_mode"], "since_latest_recovery")
        self.assertEqual(queue_rollup["effective_entry_count"], 1)
        self.assertTrue(queue_rollup["effective_all_dates_ok"])
        self.assertFalse(queue_rollup["all_dates_ok"])

    def test_run_ci_sidecar_records_stable_observer_summary_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            nightly_index = {
                "summary_path": str(refs_dir / "2026-03-28-nightly-index.json"),
                "canonical_surface": True,
                "count": 1,
                "all_ok": True,
                "families": [
                    {
                        "family": "external_dyn_desc_ref",
                        "builder": {"run_id": "builder-run-001"},
                        "toolchain": {"run_id": "toolchain-run-001"},
                        "audit": {"manifest_match": True, "ok": True},
                    }
                ],
            }
            history_index = {
                "summary_path": str(refs_dir / "nightly-history-index.json"),
                "latest_date": "2026-03-28",
                "first_fail_date": None,
                "first_drift_date": None,
                "latest_recovered_date": "2026-03-28",
                "entries": [],
                "family_history": [],
                "all_ok_latest": True,
            }
            full_equiv = {
                "schema_version": 2,
                "artifact_role": "dated_equivalence_matrix",
                "canonical_surface": True,
                "gate_name": "riscv_snn_equiv_matrix",
                "requested_group": "all",
                "all_ok": True,
                "count": 8,
                "summary_path": str(refs_dir / "2026-03-28-equiv-matrix.json"),
                "families": [
                    {
                        "family": "external_dyn_desc_ref",
                        "status": "PASS",
                        "summary_path": str(refs_dir / "external-dyn-desc-ref-equiv.json"),
                        "gate_reasons": [],
                    }
                ],
            }
            full_equiv_history = {
                "artifact_role": "stable_full_equivalence_history",
                "summary_path": str(refs_dir / "full-equivalence-history.json"),
                "latest_date": "2026-03-28",
                "entry_count": 1,
                "all_ok_latest": True,
                "entries": [],
                "excluded_entries": [],
            }
            artifact_isolation = {
                "schema_version": 2,
                "artifact_role": "stable_artifact_isolation_check",
                "all_ok": True,
                "summary_path": str(refs_dir / "artifact-isolation-report.json"),
                "surfaces": {
                    "nightly": {
                        "canonical_unchanged": True,
                        "subset_surface": "subset",
                        "subset_summary_path": str(refs_dir / "nightly-index-subset.json"),
                    }
                },
            }
            artifact_isolation_history = {
                "artifact_role": "stable_artifact_isolation_history",
                "summary_path": str(refs_dir / "artifact-isolation-history.json"),
                "latest_date": "2026-03-28",
                "entry_count": 1,
                "all_ok_latest": True,
                "entries": [],
            }
            report_path = refs_dir / "nightly-sidecar-report.json"

            with mock.patch.object(riscv_snn_lab, "run_nightly", return_value=nightly_index):
                with mock.patch.object(riscv_snn_lab, "refresh_history_index", return_value=history_index):
                    with mock.patch.object(riscv_snn_lab, "run_equiv_matrix", return_value=full_equiv):
                        with mock.patch.object(
                            riscv_snn_lab,
                            "refresh_full_equivalence_history",
                            return_value=full_equiv_history,
                        ):
                            with mock.patch.object(
                                riscv_snn_lab,
                                "run_artifact_isolation_check",
                                return_value=artifact_isolation,
                            ):
                                with mock.patch.object(
                                    riscv_snn_lab,
                                    "refresh_artifact_isolation_history",
                                    return_value=artifact_isolation_history,
                                ):
                                    report = riscv_snn_lab.run_ci_sidecar(
                                        builder_programs=["external_dyn_desc_ref"],
                                        toolchain_programs=["external_dyn_desc_ref_toolchain"],
                                        with_full_equivalence=True,
                                        with_artifact_isolation=True,
                                        report_path=report_path,
                                        lab_root=lab_root,
                                    )

            observer_summary_path = Path(report["observer_summary_path"])
            self.assertTrue(observer_summary_path.exists())
            observer_summary = json.loads(observer_summary_path.read_text(encoding="utf-8"))
            self.assertEqual(observer_summary["artifact_role"], "stable_sidecar_observer_summary")
            self.assertEqual(observer_summary["authority_entrypoint"]["summary_path"], str(report_path))
            self.assertEqual(observer_summary["optional_surfaces"]["full_equivalence"]["entry_count"], 1)
            self.assertEqual(observer_summary["optional_surfaces"]["artifact_isolation"]["entry_count"], 1)
            persisted_report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted_report["observer_summary_path"], str(observer_summary_path))
            self.assertEqual(
                persisted_report["research_report_path"],
                str(refs_dir / "riscv-snn-research-report.json"),
            )
            self.assertEqual(
                persisted_report["observer_adequacy_validation_path"],
                str(refs_dir / "observer-adequacy-validation.json"),
            )
            self.assertEqual(
                persisted_report["current_mainline_status_path"],
                str(refs_dir / "current-mainline-status.md"),
            )
            self.assertIn("stable_surface_refresh", persisted_report)
            self.assertEqual(
                persisted_report["stable_surface_refresh"]["observer_summary_path"],
                str(observer_summary_path),
            )
            self.assertEqual(
                persisted_report["stable_surface_refresh"]["current_mainline_status_path"],
                str(refs_dir / "current-mainline-status.md"),
            )
            self.assertTrue(Path(report["current_mainline_status_path"]).exists())
            current_mainline_status = Path(report["current_mainline_status_path"]).read_text(encoding="utf-8")
            self.assertIn("## Top-Level Gate", current_mainline_status)
            self.assertIn("## Research / Validation", current_mainline_status)

    def test_export_research_report_runs_validation_postprocess(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)
            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            report_path = refs_dir / "riscv-snn-research-report.json"
            validation_path = refs_dir / "observer-adequacy-validation.json"
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "report_path": str(sidecar_path),
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(
                export_riscv_snn_research_report,
                "generate_research_report",
                return_value=report_path,
            ) as generate_report:
                with mock.patch.object(
                    export_riscv_snn_research_report,
                    "validate_observer_adequacy_report",
                    return_value=validation_path,
                ) as validate_report:
                    resolved = riscv_snn_lab.export_research_report(
                        sidecar_path=sidecar_path,
                        output_path=report_path,
                        lab_root=lab_root,
                    )
                    persisted_sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))

        self.assertEqual(resolved, report_path)
        self.assertEqual(generate_report.call_args.kwargs["sidecar_path"], sidecar_path)
        self.assertEqual(generate_report.call_args.kwargs["output_path"], report_path)
        self.assertEqual(validate_report.call_args.kwargs["report_path"], report_path)
        self.assertEqual(validate_report.call_args.kwargs["output_path"], validation_path)
        self.assertEqual(persisted_sidecar["research_report_path"], str(report_path))
        self.assertEqual(persisted_sidecar["observer_adequacy_validation_path"], str(validation_path))

    def test_generate_research_report_carries_reference_compare_supplementary_surface(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            sidecar_path = td_path / "nightly-sidecar-report.json"
            output_path = td_path / "riscv-snn-research-report.json"
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "supplementary_surfaces": {
                            "reference_compare": {
                                "surface_kind": "reference_compare_surface",
                                "blocking": False,
                                "present": True,
                                "report_path": str(td_path / "reference-compare-nightly-report.json"),
                                "summary_md_path": str(td_path / "reference-compare-nightly-summary.md"),
                                "current_mainline_status_path": str(td_path / "reference-compare-current-status.md"),
                                "gate_ok": True,
                                "latest_date": "2026-04-09",
                                "stale": False,
                                "freshness_mode": "reference_compare_latest_only",
                                "effective_all_dates_ok": True,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            export_riscv_snn_research_report.generate_research_report(
                sidecar_path=sidecar_path,
                output_path=output_path,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertIn("reference_compare", payload["supplementary_surfaces"])
        self.assertEqual(
            payload["supplementary_surfaces"]["reference_compare"]["surface_kind"],
            "reference_compare_surface",
        )

    def test_export_mainline_status_rolls_up_shared_current_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            refs_dir = td_path / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)
            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            observer_path = refs_dir / "nightly-sidecar-observer-summary.json"
            research_path = refs_dir / "riscv-snn-research-report.json"
            validation_path = refs_dir / "observer-adequacy-validation.json"
            queue_audit_path = refs_dir / "2026-03-30-queue-optional-admission-audit.json"
            output_path = refs_dir / "current-mainline-status.md"

            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "generated_utc": "2026-03-31T00:00:00+00:00",
                        "gate_ok": True,
                        "with_equivalence": True,
                        "with_full_equivalence": True,
                        "required_families": [
                            "barrier_wfi_order_ref",
                            "external_dyn_desc_ref",
                        ],
                        "report_path": str(sidecar_path),
                        "observer_summary_path": str(observer_path),
                        "research_report_path": str(research_path),
                        "observer_adequacy_validation_path": str(validation_path),
                        "stable_surface_refresh": {
                            "refreshed_utc": "2026-04-04T00:00:00+00:00",
                        },
                    }
                ),
                encoding="utf-8",
            )
            observer_path.write_text(
                json.dumps(
                    {
                        "optional_surfaces": {
                            "full_equivalence": {
                                "entry_count": 2,
                                "refresh_mode": "compact_latest_recovery",
                                "effective_entry_count": 1,
                                "effective_all_dates_ok": True,
                                "first_fail_date": "2026-03-30",
                                "latest_recovered_date": "2026-03-30",
                                "all_ok_latest": True,
                                "history_contract": "observer_sample_sequence_v1",
                            },
                            "queue_equivalence": {
                                "latest_date": "2026-03-29",
                                "entry_count": 3,
                                "all_dates_ok": True,
                                "history_contract": "canonical_queue_optional_only",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            research_path.write_text(
                json.dumps(
                    {
                        "observer_adequacy": {
                            "status": "ready_with_fail_recovery_sample",
                        }
                    }
                ),
                encoding="utf-8",
            )
            validation_path.write_text(
                json.dumps(
                    {
                        "status": "pass",
                        "mismatch_count": 0,
                    }
                ),
                encoding="utf-8",
            )
            queue_audit_path.write_text(
                json.dumps(
                    {
                        "group": "queue_optional",
                        "promotion_ready": True,
                        "explicit_review_ok": True,
                        "blocking": False,
                    }
                ),
                encoding="utf-8",
            )

            resolved = riscv_snn_lab.export_mainline_status(
                sidecar_path=sidecar_path,
                output_path=output_path,
                lab_root=td_path,
            )
            summary_md = output_path.read_text(encoding="utf-8")

        self.assertEqual(resolved, output_path)
        self.assertIn("# riscv_snn current mainline status", summary_md)
        self.assertIn("## Top-Level Gate", summary_md)
        self.assertIn("`gate_ok = True`", summary_md)
        self.assertIn("`with_full_equivalence = True`", summary_md)
        self.assertIn("## Observer Closure", summary_md)
        self.assertIn("observer_sample_sequence_v1", summary_md)
        self.assertIn("`refresh_mode = compact_latest_recovery`", summary_md)
        self.assertIn("`effective_entry_count = 1`", summary_md)
        self.assertIn("`effective_all_dates_ok = True`", summary_md)
        self.assertIn("ready_with_fail_recovery_sample", summary_md)
        self.assertIn("`status = pass`", summary_md)
        self.assertIn("## Optional Freshness", summary_md)
        self.assertIn("`queue.latest_date = 2026-03-29`", summary_md)
        self.assertIn("`queue.history_contract = canonical_queue_optional_only`", summary_md)
        self.assertIn("- Generated UTC: `2026-04-04T00:00:00+00:00`", summary_md)
        self.assertIn("## Optional Admission", summary_md)
        self.assertIn("`promotion_ready = True`", summary_md)
        self.assertIn("accepted-fault completion progress", summary_md)

    def test_export_mainline_status_includes_compare_supplementary_surface(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            refs_dir = td_path / "references"
            spec_dir = td_path / "spec_authority"
            refs_dir.mkdir(parents=True, exist_ok=True)
            spec_dir.mkdir(parents=True, exist_ok=True)
            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            output_path = refs_dir / "current-mainline-status.md"

            (spec_dir / "riscv_snn_mainline_gate_v1.json").write_text(
                json.dumps(
                    {
                        "required_families": ["external_dyn_desc_ref"],
                        "optional_groups": {},
                        "promotion_contract": {},
                    }
                ),
                encoding="utf-8",
            )
            (spec_dir / "riscv_snn_runtime_gate_v1.json").write_text(
                json.dumps({"reason_ids": [], "checks": {}, "families": {}}),
                encoding="utf-8",
            )
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "generated_utc": "2026-04-07T00:00:00+00:00",
                        "gate_ok": True,
                        "with_equivalence": True,
                        "with_full_equivalence": False,
                        "required_families": ["external_dyn_desc_ref"],
                        "report_path": str(sidecar_path),
                        "supplementary_surfaces": {
                            "compare": {
                                "present": True,
                                "gate_ok": True,
                                "latest_date": "2026-04-07",
                                "stale": False,
                                "freshness_mode": "since_latest_recovery",
                                "effective_all_dates_ok": True,
                                "report_path": str(refs_dir / "compare-nightly-report.json"),
                                "summary_md_path": str(refs_dir / "compare-nightly-summary.md"),
                                "current_mainline_status_path": str(refs_dir / "compare-current-status.md"),
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            riscv_snn_lab.export_mainline_status(
                sidecar_path=sidecar_path,
                output_path=output_path,
                lab_root=td_path,
            )
            summary_md = output_path.read_text(encoding="utf-8")

        self.assertIn("## Supplementary Surfaces", summary_md)
        self.assertIn("`compare.gate_ok = True`", summary_md)
        self.assertIn("`compare.freshness_mode = since_latest_recovery`", summary_md)
        self.assertIn("compare-current-status.md", summary_md)

    def test_export_mainline_status_includes_reference_compare_supplementary_surface(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            refs_dir = td_path / "references"
            spec_dir = td_path / "spec_authority"
            refs_dir.mkdir(parents=True, exist_ok=True)
            spec_dir.mkdir(parents=True, exist_ok=True)
            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            output_path = refs_dir / "current-mainline-status.md"

            (spec_dir / "riscv_snn_mainline_gate_v1.json").write_text(
                json.dumps(
                    {
                        "required_families": ["external_dyn_desc_ref"],
                        "optional_groups": {},
                        "promotion_contract": {},
                    }
                ),
                encoding="utf-8",
            )
            (spec_dir / "riscv_snn_runtime_gate_v1.json").write_text(
                json.dumps({"reason_ids": [], "checks": {}, "families": {}}),
                encoding="utf-8",
            )
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "generated_utc": "2026-04-09T00:00:00+00:00",
                        "gate_ok": True,
                        "with_equivalence": True,
                        "with_full_equivalence": False,
                        "required_families": ["external_dyn_desc_ref"],
                        "report_path": str(sidecar_path),
                        "supplementary_surfaces": {
                            "reference_compare": {
                                "surface_kind": "reference_compare_surface",
                                "blocking": False,
                                "present": True,
                                "gate_ok": True,
                                "latest_date": "2026-04-09",
                                "stale": False,
                                "freshness_mode": "reference_compare_latest_only",
                                "effective_all_dates_ok": True,
                                "report_path": str(refs_dir / "reference-compare-nightly-report.json"),
                                "summary_md_path": str(refs_dir / "reference-compare-nightly-summary.md"),
                                "current_mainline_status_path": str(refs_dir / "reference-compare-current-status.md"),
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            riscv_snn_lab.export_mainline_status(
                sidecar_path=sidecar_path,
                output_path=output_path,
                lab_root=td_path,
            )
            summary_md = output_path.read_text(encoding="utf-8")

        self.assertIn("`reference_compare.gate_ok = True`", summary_md)
        self.assertIn("`reference_compare.freshness_mode = reference_compare_latest_only`", summary_md)
        self.assertIn("reference-compare-current-status.md", summary_md)

    def test_export_mainline_status_includes_reference_program_compare_supplementary_surface(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            refs_dir = td_path / "references"
            spec_dir = td_path / "spec_authority"
            refs_dir.mkdir(parents=True, exist_ok=True)
            spec_dir.mkdir(parents=True, exist_ok=True)
            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            output_path = refs_dir / "current-mainline-status.md"

            (spec_dir / "riscv_snn_mainline_gate_v1.json").write_text(
                json.dumps(
                    {
                        "required_families": ["external_dyn_desc_ref"],
                        "optional_groups": {},
                        "promotion_contract": {},
                    }
                ),
                encoding="utf-8",
            )
            (spec_dir / "riscv_snn_runtime_gate_v1.json").write_text(
                json.dumps({"reason_ids": [], "checks": {}, "families": {}}),
                encoding="utf-8",
            )
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "generated_utc": "2026-04-14T00:00:00+00:00",
                        "gate_ok": True,
                        "with_equivalence": True,
                        "with_full_equivalence": False,
                        "required_families": ["external_dyn_desc_ref"],
                        "report_path": str(sidecar_path),
                        "supplementary_surfaces": {
                            "reference_program_compare": {
                                "surface_kind": "reference_program_compare_surface",
                                "blocking": False,
                                "present": True,
                                "gate_ok": True,
                                "latest_date": "2026-04-14",
                                "stale": False,
                                "freshness_mode": "reference_program_compare_latest_only",
                                "effective_all_dates_ok": True,
                                "report_path": str(refs_dir / "reference-program-compare-nightly-report.json"),
                                "summary_md_path": str(refs_dir / "reference-program-compare-nightly-summary.md"),
                                "current_mainline_status_path": str(refs_dir / "reference-program-compare-current-status.md"),
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            riscv_snn_lab.export_mainline_status(
                sidecar_path=sidecar_path,
                output_path=output_path,
                lab_root=td_path,
            )
            summary_md = output_path.read_text(encoding="utf-8")

        self.assertIn("`reference_program_compare.gate_ok = True`", summary_md)
        self.assertIn(
            "`reference_program_compare.freshness_mode = reference_program_compare_latest_only`",
            summary_md,
        )
        self.assertIn("reference-program-compare-current-status.md", summary_md)

    def test_export_mainline_status_includes_stat_snapshot_family_supplementary_surface(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            refs_dir = td_path / "references"
            spec_dir = td_path / "spec_authority"
            refs_dir.mkdir(parents=True, exist_ok=True)
            spec_dir.mkdir(parents=True, exist_ok=True)
            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            output_path = refs_dir / "current-mainline-status.md"

            (spec_dir / "riscv_snn_mainline_gate_v1.json").write_text(
                json.dumps(
                    {
                        "required_families": ["external_dyn_desc_ref"],
                        "optional_groups": {},
                        "promotion_contract": {},
                    }
                ),
                encoding="utf-8",
            )
            (spec_dir / "riscv_snn_runtime_gate_v1.json").write_text(
                json.dumps({"reason_ids": [], "checks": {}, "families": {}}),
                encoding="utf-8",
            )
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "generated_utc": "2026-04-16T00:00:00+00:00",
                        "gate_ok": True,
                        "with_equivalence": True,
                        "with_full_equivalence": False,
                        "required_families": ["external_dyn_desc_ref"],
                        "report_path": str(sidecar_path),
                        "supplementary_surfaces": {
                            "stat_snapshot_family": {
                                "surface_kind": "stat_snapshot_family_surface",
                                "blocking": False,
                                "present": True,
                                "gate_ok": True,
                                "latest_date": "2026-04-16",
                                "stale": False,
                                "freshness_mode": "latest_refresh_only",
                                "effective_all_dates_ok": True,
                                "selector_count": 3,
                                "covered_selector_count": 3,
                                "report_path": str(refs_dir / "stat-snapshot-family-nightly-report.json"),
                                "summary_md_path": str(refs_dir / "stat-snapshot-family-nightly-summary.md"),
                                "current_mainline_status_path": str(refs_dir / "stat-snapshot-family-current-status.md"),
                                "selector_rows": [
                                    {
                                        "selector_name": "AcceptedCommands",
                                        "reference_ready": True,
                                    },
                                    {
                                        "selector_name": "CompletedCommands",
                                        "reference_ready": True,
                                    },
                                    {
                                        "selector_name": "ProviderBound",
                                        "reference_ready": True,
                                    },
                                ],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            riscv_snn_lab.export_mainline_status(
                sidecar_path=sidecar_path,
                output_path=output_path,
                lab_root=td_path,
            )
            summary_md = output_path.read_text(encoding="utf-8")

        self.assertIn("`stat_snapshot_family.gate_ok = True`", summary_md)
        self.assertIn("`stat_snapshot_family.selector_count = 3`", summary_md)
        self.assertIn("`stat_snapshot_family.CompletedCommands.reference_ready = True`", summary_md)
        self.assertIn("stat-snapshot-family-nightly-report.json", summary_md)
        self.assertIn("stat-snapshot-family-current-status.md", summary_md)

    def test_export_mainline_status_lists_authority_optional_groups(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            refs_dir = td_path / "references"
            spec_dir = td_path / "spec_authority"
            refs_dir.mkdir(parents=True, exist_ok=True)
            spec_dir.mkdir(parents=True, exist_ok=True)
            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            observer_path = refs_dir / "nightly-sidecar-observer-summary.json"
            output_path = refs_dir / "current-mainline-status.md"
            (spec_dir / "riscv_snn_mainline_gate_v1.json").write_text(
                json.dumps(
                    {
                        "required_families": ["external_dyn_desc_ref"],
                        "optional_groups": {
                            "completion_overflow_optional": {
                                "families": ["completion_queue_overflow_ref"],
                                "blocking": False,
                            },
                            "queue_optional": {
                                "families": ["queue_backpressure_ref"],
                                "blocking": False,
                            },
                        },
                        "promotion_contract": {},
                    }
                ),
                encoding="utf-8",
            )
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "generated_utc": "2026-03-31T00:00:00+00:00",
                        "gate_ok": True,
                        "report_path": str(sidecar_path),
                        "observer_summary_path": str(observer_path),
                    }
                ),
                encoding="utf-8",
            )
            observer_path.write_text(
                json.dumps(
                    {
                        "optional_group_rollups": {
                            "completion_overflow_optional": {
                                "latest_date": "2026-03-29",
                                "entry_count": 3,
                                "all_dates_ok": True,
                                "history_contract": "canonical_completion_overflow_optional_only",
                            },
                            "queue_optional": {
                                "latest_date": "2026-03-28",
                                "entry_count": 2,
                                "all_dates_ok": True,
                                "history_contract": "canonical_queue_optional_only",
                            },
                        },
                        "optional_surfaces": {
                            "queue_equivalence": {
                                "latest_date": "2026-03-28",
                                "entry_count": 2,
                                "all_dates_ok": True,
                                "history_contract": "canonical_queue_optional_only",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            (refs_dir / "2026-03-31-completion-overflow-optional-admission-audit.json").write_text(
                json.dumps(
                    {
                        "group": "completion_overflow_optional",
                        "promotion_ready": True,
                        "explicit_review_ok": True,
                        "blocking": False,
                    }
                ),
                encoding="utf-8",
            )
            (refs_dir / "2026-03-31-queue-optional-admission-audit.json").write_text(
                json.dumps(
                    {
                        "group": "queue_optional",
                        "promotion_ready": True,
                        "explicit_review_ok": True,
                        "blocking": False,
                    }
                ),
                encoding="utf-8",
            )

            riscv_snn_lab.export_mainline_status(
                sidecar_path=sidecar_path,
                output_path=output_path,
                lab_root=td_path,
            )
            summary_md = output_path.read_text(encoding="utf-8")

        self.assertIn("`completion_overflow_optional.latest_date = 2026-03-29`", summary_md)
        self.assertIn(
            "`completion_overflow_optional.history_contract = canonical_completion_overflow_optional_only`",
            summary_md,
        )
        self.assertIn("`completion_overflow_optional.promotion_ready = True`", summary_md)

    def test_export_mainline_status_prefers_authority_primary_optional_group(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            refs_dir = td_path / "references"
            spec_dir = td_path / "spec_authority"
            refs_dir.mkdir(parents=True, exist_ok=True)
            spec_dir.mkdir(parents=True, exist_ok=True)
            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            observer_path = refs_dir / "nightly-sidecar-observer-summary.json"
            output_path = refs_dir / "current-mainline-status.md"
            (spec_dir / "riscv_snn_mainline_gate_v1.json").write_text(
                json.dumps(
                    {
                        "required_families": ["external_dyn_desc_ref"],
                        "optional_groups": {
                            "completion_overflow_optional": {
                                "families": ["completion_queue_overflow_ref"],
                                "blocking": False,
                            },
                            "queue_optional": {
                                "families": ["queue_backpressure_ref"],
                                "blocking": False,
                            },
                        },
                        "mainline_defaults": {
                            "primary_optional_group": "completion_overflow_optional",
                            "mainline_refresh_default_group": "completion_overflow_optional",
                        },
                        "promotion_contract": {},
                    }
                ),
                encoding="utf-8",
            )
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "generated_utc": "2026-03-31T00:00:00+00:00",
                        "gate_ok": True,
                        "report_path": str(sidecar_path),
                        "observer_summary_path": str(observer_path),
                    }
                ),
                encoding="utf-8",
            )
            observer_path.write_text(
                json.dumps(
                    {
                        "optional_group_rollups": {
                            "completion_overflow_optional": {
                                "latest_date": "2026-03-29",
                                "entry_count": 3,
                                "all_dates_ok": True,
                                "history_contract": "canonical_completion_overflow_optional_only",
                            },
                            "queue_optional": {
                                "latest_date": "2026-03-28",
                                "entry_count": 2,
                                "all_dates_ok": True,
                                "history_contract": "canonical_queue_optional_only",
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            completion_path = refs_dir / "2026-03-31-completion-overflow-optional-admission-audit.json"
            queue_path = refs_dir / "2026-03-31-queue-optional-admission-audit.json"
            completion_path.write_text(
                json.dumps(
                    {
                        "group": "completion_overflow_optional",
                        "promotion_ready": True,
                        "explicit_review_ok": True,
                        "blocking": False,
                    }
                ),
                encoding="utf-8",
            )
            queue_path.write_text(
                json.dumps(
                    {
                        "group": "queue_optional",
                        "promotion_ready": True,
                        "explicit_review_ok": True,
                        "blocking": False,
                    }
                ),
                encoding="utf-8",
            )

            riscv_snn_lab.export_mainline_status(
                sidecar_path=sidecar_path,
                output_path=output_path,
                lab_root=td_path,
            )
            summary_md = output_path.read_text(encoding="utf-8")

        self.assertIn("`primary_optional_group = completion_overflow_optional`", summary_md)
        self.assertIn(
            f"- latest optional admission audit: `{completion_path}`",
            summary_md,
        )
        self.assertIn("`completion_overflow_optional.latest_date = 2026-03-29`", summary_md)
        self.assertIn("`queue_optional.latest_date = 2026-03-28`", summary_md)
        self.assertNotIn("`group = queue_optional`", summary_md)

    def test_export_mainline_status_renders_effective_optional_group_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            refs_dir = td_path / "references"
            spec_dir = td_path / "spec_authority"
            refs_dir.mkdir(parents=True, exist_ok=True)
            spec_dir.mkdir(parents=True, exist_ok=True)
            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            observer_path = refs_dir / "nightly-sidecar-observer-summary.json"
            output_path = refs_dir / "current-mainline-status.md"
            (spec_dir / "riscv_snn_mainline_gate_v1.json").write_text(
                json.dumps(
                    {
                        "required_families": ["external_dyn_desc_ref"],
                        "optional_groups": {
                            "queue_optional": {
                                "families": ["queue_backpressure_ref"],
                                "blocking": False,
                            }
                        },
                        "promotion_contract": {
                            "queue_optional": {
                                "requires_multi_date_freshness": True,
                                "multi_date_freshness_mode": "since_latest_recovery",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "generated_utc": "2026-03-31T00:00:00+00:00",
                        "gate_ok": True,
                        "report_path": str(sidecar_path),
                        "observer_summary_path": str(observer_path),
                    }
                ),
                encoding="utf-8",
            )
            observer_path.write_text(
                json.dumps(
                    {
                        "optional_group_rollups": {
                            "queue_optional": {
                                "latest_date": "2026-04-03",
                                "entry_count": 3,
                                "all_dates_ok": False,
                                "history_contract": "canonical_queue_optional_only",
                                "freshness_mode": "since_latest_recovery",
                                "effective_entry_count": 1,
                                "effective_all_dates_ok": True,
                            }
                        },
                        "optional_surfaces": {
                            "queue_equivalence": {
                                "latest_date": "2026-04-03",
                                "entry_count": 3,
                                "all_dates_ok": False,
                                "history_contract": "canonical_queue_optional_only",
                                "freshness_mode": "since_latest_recovery",
                                "effective_entry_count": 1,
                                "effective_all_dates_ok": True,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            (refs_dir / "2026-04-04-queue-optional-admission-audit.json").write_text(
                json.dumps(
                    {
                        "group": "queue_optional",
                        "promotion_ready": True,
                        "explicit_review_ok": True,
                        "blocking": False,
                    }
                ),
                encoding="utf-8",
            )

            riscv_snn_lab.export_mainline_status(
                sidecar_path=sidecar_path,
                output_path=output_path,
                lab_root=td_path,
            )
            summary_md = output_path.read_text(encoding="utf-8")

        self.assertIn("`queue.freshness_mode = since_latest_recovery`", summary_md)
        self.assertIn("`queue.effective_entry_count = 1`", summary_md)
        self.assertIn("`queue.effective_all_dates_ok = True`", summary_md)
        self.assertIn("`queue_optional.effective_all_dates_ok = True`", summary_md)

    def test_export_mainline_status_includes_surface_refresh_utc(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            refs_dir = td_path / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)
            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            output_path = refs_dir / "current-mainline-status.md"
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "generated_utc": "2026-03-31T00:00:00+00:00",
                        "stable_surface_refresh": {
                            "refreshed_utc": "2026-03-31T00:00:05+00:00",
                        },
                    }
                ),
                encoding="utf-8",
            )
            riscv_snn_lab.export_mainline_status(
                sidecar_path=sidecar_path,
                output_path=output_path,
                lab_root=td_path,
            )
            summary_md = output_path.read_text(encoding="utf-8")
        self.assertIn("`2026-03-31T00:00:05+00:00`", summary_md)

    def test_export_mainline_status_includes_effective_optional_freshness_markers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            refs_dir = td_path / "references"
            spec_dir = td_path / "spec_authority"
            refs_dir.mkdir(parents=True, exist_ok=True)
            spec_dir.mkdir(parents=True, exist_ok=True)
            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            observer_path = refs_dir / "nightly-sidecar-observer-summary.json"
            output_path = refs_dir / "current-mainline-status.md"
            (spec_dir / "riscv_snn_mainline_gate_v1.json").write_text(
                json.dumps(
                    {
                        "required_families": ["external_dyn_desc_ref"],
                        "optional_groups": {
                            "queue_optional": {
                                "families": ["queue_backpressure_ref"],
                                "blocking": False,
                            },
                        },
                        "promotion_contract": {},
                    }
                ),
                encoding="utf-8",
            )
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "generated_utc": "2026-03-31T00:00:00+00:00",
                        "gate_ok": True,
                        "report_path": str(sidecar_path),
                        "observer_summary_path": str(observer_path),
                    }
                ),
                encoding="utf-8",
            )
            observer_path.write_text(
                json.dumps(
                    {
                        "optional_group_rollups": {
                            "queue_optional": {
                                "latest_date": "2026-03-31",
                                "entry_count": 4,
                                "all_dates_ok": False,
                                "history_contract": "canonical_queue_optional_only",
                                "freshness_mode": "since_latest_recovery",
                                "effective_entry_count": 1,
                                "effective_all_dates_ok": True,
                            },
                        },
                        "optional_surfaces": {
                            "queue_equivalence": {
                                "latest_date": "2026-03-31",
                                "entry_count": 4,
                                "all_dates_ok": False,
                                "history_contract": "canonical_queue_optional_only",
                                "freshness_mode": "since_latest_recovery",
                                "effective_entry_count": 1,
                                "effective_all_dates_ok": True,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            (refs_dir / "2026-03-31-queue-optional-admission-audit.json").write_text(
                json.dumps(
                    {
                        "group": "queue_optional",
                        "promotion_ready": True,
                        "explicit_review_ok": True,
                        "blocking": False,
                    }
                ),
                encoding="utf-8",
            )

            riscv_snn_lab.export_mainline_status(
                sidecar_path=sidecar_path,
                output_path=output_path,
                lab_root=td_path,
            )
            summary_md = output_path.read_text(encoding="utf-8")

        self.assertIn("`queue.freshness_mode = since_latest_recovery`", summary_md)
        self.assertIn("`queue.effective_entry_count = 1`", summary_md)
        self.assertIn("`queue.effective_all_dates_ok = True`", summary_md)

    def test_refresh_observer_surfaces_ingests_samples_and_refreshes_compact_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)
            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            observer_summary_path = refs_dir / "nightly-sidecar-observer-summary.json"
            research_path = refs_dir / "riscv-snn-research-report.json"
            validation_path = refs_dir / "observer-adequacy-validation.json"
            current_mainline_path = refs_dir / "current-mainline-status.md"
            fail_path = td_path / "fail.json"
            recover_path = td_path / "recover.json"

            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "generated_utc": "2026-03-31T00:00:00+00:00",
                        "gate_name": "riscv_snn_experimental_nightly",
                        "gate_version": "1.1",
                        "gate_ok": True,
                        "required_families": ["external_dyn_desc_ref"],
                        "report_path": str(sidecar_path),
                        "observer_summary_path": str(observer_summary_path),
                        "research_report_path": str(research_path),
                        "observer_adequacy_validation_path": str(validation_path),
                        "history_index": {"latest_date": "2026-03-31"},
                    }
                ),
                encoding="utf-8",
            )
            for path, all_ok, stamp in (
                (fail_path, False, "2026-03-31T00:00:01+00:00"),
                (recover_path, True, "2026-03-31T00:00:02+00:00"),
            ):
                path.write_text(
                    json.dumps(
                        {
                            "artifact_role": "dated_equivalence_matrix",
                            "authority_scope": "family_level_equivalence_authority",
                            "generated_utc": stamp,
                            "canonical_surface": True,
                            "requested_group": "all",
                            "gate_name": "riscv_snn_equiv_matrix",
                            "count": 8,
                            "all_ok": all_ok,
                            "families": [],
                            "summary_path": str(path),
                        }
                    ),
                    encoding="utf-8",
                )
            research_path.write_text(
                json.dumps({"observer_adequacy": {"status": "ready_with_fail_recovery_sample"}}),
                encoding="utf-8",
            )
            validation_path.write_text(
                json.dumps({"status": "pass", "mismatch_count": 0}),
                encoding="utf-8",
            )
            current_mainline_path.write_text("# current\n", encoding="utf-8")

            with mock.patch.object(
                riscv_snn_lab,
                "run_research_postprocess",
                return_value={
                    "research_report_path": research_path,
                    "observer_adequacy_validation_path": validation_path,
                },
            ):
                with mock.patch.object(
                    riscv_snn_lab,
                    "_refresh_current_mainline_status",
                    return_value=current_mainline_path,
                ):
                    outputs = riscv_snn_lab.refresh_observer_surfaces(
                        sample_paths=[fail_path, recover_path],
                        lab_root=lab_root,
                    )

            observer_summary = json.loads(observer_summary_path.read_text(encoding="utf-8"))
            observer_history = json.loads((refs_dir / "observer-full-equivalence-history.json").read_text(encoding="utf-8"))
            persisted_sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))

        self.assertEqual(outputs["observer_summary_path"], observer_summary_path)
        self.assertEqual(outputs["observer_history_path"], refs_dir / "observer-full-equivalence-history.json")
        self.assertEqual(observer_history["entry_count"], 2)
        self.assertEqual(observer_history["first_fail_date"], "2026-03-31")
        self.assertEqual(observer_history["latest_recovered_date"], "2026-03-31")
        self.assertEqual(observer_summary["optional_surfaces"]["full_equivalence"]["entry_count"], 2)
        self.assertEqual(
            observer_summary["optional_surfaces"]["full_equivalence"]["history_contract"],
            "observer_sample_sequence_v1",
        )
        self.assertIn("stable_surface_refresh", persisted_sidecar)
        self.assertEqual(
            persisted_sidecar["stable_surface_refresh"]["observer_summary_path"],
            str(observer_summary_path),
        )

    def test_refresh_observer_surfaces_refreshes_sidecar_optional_group_surfaces_from_latest_refs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            spec_dir = lab_root / "spec_authority"
            refs_dir.mkdir(parents=True, exist_ok=True)
            spec_dir.mkdir(parents=True, exist_ok=True)

            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            observer_summary_path = refs_dir / "nightly-sidecar-observer-summary.json"
            research_path = refs_dir / "riscv-snn-research-report.json"
            validation_path = refs_dir / "observer-adequacy-validation.json"
            current_mainline_path = refs_dir / "current-mainline-status.md"
            summary_md_path = refs_dir / "nightly-sidecar-summary.md"

            old_queue_path = refs_dir / "2026-04-01-equiv-matrix-queue-optional.json"
            new_queue_path = refs_dir / "2026-04-02-equiv-matrix-queue-optional.json"
            old_completion_path = refs_dir / "2026-04-01-equiv-matrix-completion-overflow-optional.json"
            new_completion_path = refs_dir / "2026-04-02-equiv-matrix-completion-overflow-optional.json"

            (spec_dir / "riscv_snn_mainline_gate_v1.json").write_text(
                json.dumps(
                    {
                        "required_families": ["external_dyn_desc_ref"],
                        "optional_groups": {
                            "completion_overflow_optional": {
                                "families": ["completion_queue_overflow_ref"],
                                "blocking": False,
                            },
                            "queue_optional": {
                                "families": [
                                    "queue_backpressure_ref",
                                    "completion_queue_overflow_ref",
                                ],
                                "blocking": False,
                            },
                        },
                        "promotion_contract": {},
                    }
                ),
                encoding="utf-8",
            )

            for path, group, all_ok in (
                (old_queue_path, "queue_optional", False),
                (new_queue_path, "queue_optional", True),
                (old_completion_path, "completion_overflow_optional", False),
                (new_completion_path, "completion_overflow_optional", True),
            ):
                path.write_text(
                    json.dumps(
                        {
                            "artifact_role": "dated_equivalence_matrix",
                            "authority_scope": "family_level_equivalence_authority",
                            "generated_utc": f"{path.name[:10]}T00:00:00+00:00",
                            "canonical_surface": True,
                            "requested_group": group,
                            "gate_name": "riscv_snn_equiv_matrix",
                            "count": 1 if group == "completion_overflow_optional" else 2,
                            "all_ok": all_ok,
                            "families": [],
                            "summary_path": str(path),
                        }
                    ),
                    encoding="utf-8",
                )

            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "generated_utc": "2026-04-01T04:07:47.888229+00:00",
                        "gate_name": "riscv_snn_experimental_nightly",
                        "gate_version": "1.1",
                        "gate_ok": True,
                        "required_families": ["external_dyn_desc_ref"],
                        "report_path": str(sidecar_path),
                        "observer_summary_path": str(observer_summary_path),
                        "research_report_path": str(research_path),
                        "observer_adequacy_validation_path": str(validation_path),
                        "summary_md_path": str(summary_md_path),
                        "history_index": {"latest_date": "2026-04-01", "entries": []},
                        "with_optional_groups": [
                            "completion_overflow_optional",
                            "queue_optional",
                        ],
                        "with_queue_equivalence": True,
                        "optional_group_surfaces": {
                            "completion_overflow_optional": {
                                "requested_group": "completion_overflow_optional",
                                "summary_path": str(old_completion_path),
                                "canonical_surface": True,
                                "all_ok": False,
                                "count": 1,
                                "families": [],
                            },
                            "queue_optional": {
                                "requested_group": "queue_optional",
                                "summary_path": str(old_queue_path),
                                "canonical_surface": True,
                                "all_ok": False,
                                "count": 2,
                                "families": [],
                            },
                        },
                        "queue_equivalence": {
                            "requested_group": "queue_optional",
                            "summary_path": str(old_queue_path),
                            "canonical_surface": True,
                            "all_ok": False,
                            "count": 2,
                            "families": [],
                        },
                    }
                ),
                encoding="utf-8",
            )
            research_path.write_text(
                json.dumps({"observer_adequacy": {"status": "ready_with_fail_recovery_sample"}}),
                encoding="utf-8",
            )
            validation_path.write_text(
                json.dumps({"status": "pass", "mismatch_count": 0}),
                encoding="utf-8",
            )
            current_mainline_path.write_text("# current\n", encoding="utf-8")

            with mock.patch.object(
                riscv_snn_lab,
                "run_research_postprocess",
                return_value={
                    "research_report_path": research_path,
                    "observer_adequacy_validation_path": validation_path,
                },
            ):
                with mock.patch.object(
                    riscv_snn_lab,
                    "_refresh_current_mainline_status",
                    return_value=current_mainline_path,
                ):
                    riscv_snn_lab.refresh_observer_surfaces(
                        lab_root=lab_root,
                    )

            persisted_sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            summary_md = summary_md_path.read_text(encoding="utf-8")

        self.assertEqual(
            persisted_sidecar["optional_group_surfaces"]["completion_overflow_optional"]["summary_path"],
            str(new_completion_path),
        )
        self.assertTrue(
            persisted_sidecar["optional_group_surfaces"]["completion_overflow_optional"]["all_ok"]
        )
        self.assertEqual(
            persisted_sidecar["optional_group_surfaces"]["queue_optional"]["summary_path"],
            str(new_queue_path),
        )
        self.assertTrue(persisted_sidecar["optional_group_surfaces"]["queue_optional"]["all_ok"])
        self.assertEqual(persisted_sidecar["queue_equivalence"]["summary_path"], str(new_queue_path))
        self.assertTrue(persisted_sidecar["queue_equivalence"]["all_ok"])
        self.assertIn(str(new_completion_path), summary_md)
        self.assertIn(str(new_queue_path), summary_md)
        self.assertNotIn(str(old_completion_path), summary_md)
        self.assertNotIn(str(old_queue_path), summary_md)

    def test_consumer_tools_do_not_hardcode_dated_authority_entrypoints(self) -> None:
        tools_dir = riscv_snn_lab.LAB_ROOT / "tools"
        allowed_stable_only = {
            "export_riscv_snn_research_report.py",
        }
        forbidden_tokens = (
            "equiv-matrix.json",
            "nightly-index.json",
            "full-equivalence-history.json",
            "artifact-isolation-history.json",
        )

        for path in sorted(tools_dir.glob("*.py")):
            if path.name in {"riscv_snn_lab.py", "test_riscv_snn_lab.py"}:
                continue
            content = path.read_text(encoding="utf-8")
            dated_hits = [token for token in forbidden_tokens if token in content]
            if path.name in allowed_stable_only:
                self.assertIn("nightly-sidecar-report.json", content, msg=path.name)
                self.assertEqual(dated_hits, [], msg=path.name)
            else:
                self.assertNotIn("nightly-sidecar-report.json", content, msg=path.name)
                self.assertEqual(dated_hits, [], msg=path.name)

    def test_main_research_report_prints_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "research.json"
            with mock.patch.object(riscv_snn_lab, "export_research_report", return_value=output_path) as export_report:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(["research-report", "--output", str(output_path)])

        self.assertEqual(rc, 0)
        self.assertEqual(export_report.call_args.kwargs["output_path"], output_path)
        print_mock.assert_called_once_with(output_path)

    def test_export_optional_promotion_dossier_collects_group_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            summary = {
                "summary_path": str(refs_dir / "2026-03-31-completion-overflow-optional-admission-audit.json"),
                "group": "completion_overflow_optional",
                "promotion_ready": True,
                "group_equivalence_path": str(refs_dir / "2026-03-29-completion-queue-overflow-ref-equiv.json"),
                "group_history_path": str(refs_dir / "completion-overflow-optional-equivalence-history.json"),
                "group_history_entry_count": 3,
                "group_history_all_dates_ok": True,
                "explicit_review_ok": True,
                "explicit_review_path": str(refs_dir / "2026-03-31-completion-overflow-optional-review.json"),
            }
            with mock.patch.object(riscv_snn_lab, "run_family_admission_audit", return_value=summary):
                output_path = riscv_snn_lab.export_optional_promotion_dossier(
                    group="completion_overflow_optional",
                    output_path=refs_dir / "completion-overflow-optional-promotion-dossier.json",
                    lab_root=lab_root,
                )

            dossier = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(dossier["artifact_role"], "optional_promotion_dossier")
        self.assertEqual(
            dossier["contract_primary"],
            riscv_snn_lab.OPTIONAL_PROMOTION_DOSSIER_PRIMARY_CONTRACT,
        )
        self.assertEqual(dossier["group"], "completion_overflow_optional")
        self.assertTrue(dossier["promotion_ready"])
        self.assertEqual(dossier["admission"]["summary_path"], summary["summary_path"])
        self.assertEqual(
            dossier["admission"]["contract_primary"],
            riscv_snn_lab.OPTIONAL_ADMISSION_PRIMARY_CONTRACT,
        )
        self.assertEqual(
            dossier["admission"]["primary_contract_fields"],
            list(riscv_snn_lab.OPTIONAL_ADMISSION_PRIMARY_FIELDS),
        )
        self.assertEqual(dossier["admission"]["compatibility_aliases"], {})
        self.assertEqual(
            dossier["evidence"]["equivalence_summary_path"],
            summary["group_equivalence_path"],
        )
        self.assertEqual(dossier["evidence"]["history_entry_count"], 3)
        self.assertTrue(dossier["evidence"]["explicit_review_ok"])

    def test_main_optional_promotion_dossier_prints_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "dossier.json"
            with mock.patch.object(
                riscv_snn_lab,
                "export_optional_promotion_dossier",
                return_value=output_path,
            ) as export_dossier:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(
                        [
                            "optional-promotion-dossier",
                            "--group",
                            "completion_overflow_optional",
                            "--output",
                            str(output_path),
                        ]
                    )

        self.assertEqual(rc, 0)
        self.assertEqual(export_dossier.call_args.kwargs["group"], "completion_overflow_optional")
        self.assertEqual(export_dossier.call_args.kwargs["output_path"], output_path)
        print_mock.assert_called_once_with(output_path)

    def test_main_family_promotion_dossier_prints_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "family-dossier.json"
            with mock.patch.object(
                riscv_snn_lab,
                "export_family_promotion_dossier",
                return_value=output_path,
            ) as export_dossier:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(
                        [
                            "family-promotion-dossier",
                            "--group",
                            "completion_overflow_optional",
                            "--output",
                            str(output_path),
                        ]
                    )

        self.assertEqual(rc, 0)
        self.assertEqual(export_dossier.call_args.kwargs["group"], "completion_overflow_optional")
        self.assertEqual(export_dossier.call_args.kwargs["output_path"], output_path)
        print_mock.assert_called_once_with(output_path)

    def test_main_observer_adequacy_validate_prints_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "observer-adequacy-validation.json"
            with mock.patch.object(
                riscv_snn_lab,
                "validate_observer_adequacy",
                return_value=output_path,
            ) as validate_observer:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(
                        ["observer-adequacy-validate", "--output", str(output_path)]
                    )

        self.assertEqual(rc, 0)
        self.assertEqual(validate_observer.call_args.kwargs["output_path"], output_path)
        print_mock.assert_called_once_with(output_path)

    def test_main_export_mainline_status_prints_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "current-mainline-status.md"
            with mock.patch.object(
                riscv_snn_lab,
                "export_mainline_status",
                return_value=output_path,
            ) as export_status:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(["export-mainline-status", "--output", str(output_path)])

        self.assertEqual(rc, 0)
        self.assertEqual(export_status.call_args.kwargs["output_path"], output_path)
        print_mock.assert_called_once_with(output_path)

    def test_main_family_asset_audit_prints_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "family-asset-audit.json"
            with mock.patch.object(
                riscv_snn_lab,
                "audit_family_assets",
                return_value={"summary_path": str(output_path), "all_ok": True},
            ) as audit_assets:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(["family-asset-audit", "--output", str(output_path)])

        self.assertEqual(rc, 0)
        self.assertEqual(audit_assets.call_args.kwargs["output_path"], output_path)
        print_mock.assert_called_once_with(output_path)

    def test_main_stable_surface_audit_prints_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "stable-surface-refresh-audit.json"
            with mock.patch.object(
                riscv_snn_lab,
                "audit_stable_surface_refresh",
                return_value={"summary_path": str(output_path), "all_ok": True},
            ) as audit_surface_refresh:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(["stable-surface-audit", "--output", str(output_path)])

        self.assertEqual(rc, 0)
        self.assertEqual(audit_surface_refresh.call_args.kwargs["output_path"], output_path)
        print_mock.assert_called_once_with(output_path)

    def test_main_family_lane_prints_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "family-lane-summary.json"
            with mock.patch.object(
                riscv_snn_lab,
                "run_family_lane",
                return_value={"summary_path": str(output_path)},
            ) as run_lane:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(
                        [
                            "family-lane",
                            "--family",
                            "barrier_wfi_order_ref",
                            "--cmd-queue-entries",
                            "2",
                            "--output",
                            str(output_path),
                        ]
                    )

        self.assertEqual(rc, 0)
        self.assertEqual(run_lane.call_args.kwargs["family"], "barrier_wfi_order_ref")
        self.assertEqual(run_lane.call_args.kwargs["cmd_queue_entries"], 2)
        self.assertEqual(run_lane.call_args.kwargs["summary_path"], output_path)
        print_mock.assert_called_once_with(output_path)

    def test_main_family_lane_matrix_prints_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "family-lane-matrix-summary.json"
            with mock.patch.object(
                riscv_snn_lab,
                "run_family_lane_matrix",
                return_value={"summary_path": str(output_path), "all_ok": True},
            ) as run_lane_matrix:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(
                        [
                            "family-lane-matrix",
                            "--family",
                            "external_dyn_desc_fault_ref",
                            "--family",
                            "queue_backpressure_ref",
                            "--cmd-queue-entries",
                            "2",
                            "--cmp-queue-entries",
                            "1",
                            "--output",
                            str(output_path),
                        ]
                    )

        self.assertEqual(rc, 0)
        self.assertEqual(
            run_lane_matrix.call_args.kwargs["families"],
            ["external_dyn_desc_fault_ref", "queue_backpressure_ref"],
        )
        self.assertEqual(run_lane_matrix.call_args.kwargs["cmd_queue_entries"], 2)
        self.assertEqual(run_lane_matrix.call_args.kwargs["cmp_queue_entries"], 1)
        self.assertEqual(run_lane_matrix.call_args.kwargs["summary_path"], output_path)
        print_mock.assert_called_once_with(output_path)

    def test_main_family_lane_accepts_queue_backpressure_preset(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "family-lane-summary.json"
            with mock.patch.object(
                riscv_snn_lab,
                "run_family_lane",
                return_value={"summary_path": str(output_path), "status": "PASS"},
            ) as run_lane:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(
                        [
                            "family-lane",
                            "--preset",
                            "queue_backpressure_capacity_relief",
                            "--output",
                            str(output_path),
                        ]
                    )

        self.assertEqual(rc, 0)
        self.assertEqual(run_lane.call_args.kwargs["preset"], "queue_backpressure_capacity_relief")
        self.assertEqual(run_lane.call_args.kwargs["summary_path"], output_path)
        print_mock.assert_called_once_with(output_path)

    def test_main_family_lane_matrix_accepts_cmpq_fault_rearm_preset(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "family-lane-matrix-summary.json"
            with mock.patch.object(
                riscv_snn_lab,
                "run_family_lane_matrix",
                return_value={"summary_path": str(output_path), "all_ok": True},
            ) as run_lane_matrix:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(
                        [
                            "family-lane-matrix",
                            "--preset",
                            "cmpq_fault_rearm_default",
                            "--output",
                            str(output_path),
                        ]
                    )

        self.assertEqual(rc, 0)
        self.assertEqual(run_lane_matrix.call_args.kwargs["preset"], "cmpq_fault_rearm_default")
        self.assertEqual(run_lane_matrix.call_args.kwargs["summary_path"], output_path)
        print_mock.assert_called_once_with(output_path)

    def test_main_family_lane_preset_prints_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "family-lane-preset-summary.json"
            with mock.patch.object(
                riscv_snn_lab,
                "run_family_lane_preset",
                return_value={"summary_path": str(output_path), "status": "PASS"},
            ) as run_lane_preset:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(
                        [
                            "family-lane-preset",
                            "--preset",
                            "queue_backpressure_capacity_relief",
                            "--local-mem-bytes",
                            "0x40000",
                            "--output",
                            str(output_path),
                        ]
                    )

        self.assertEqual(rc, 0)
        self.assertEqual(run_lane_preset.call_args.kwargs["preset"], "queue_backpressure_capacity_relief")
        self.assertEqual(run_lane_preset.call_args.kwargs["local_mem_bytes"], 0x40000)
        self.assertEqual(run_lane_preset.call_args.kwargs["summary_path"], output_path)
        print_mock.assert_called_once_with(output_path)

    def test_main_family_lane_matrix_preset_prints_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "family-lane-matrix-preset-summary.json"
            with mock.patch.object(
                riscv_snn_lab,
                "run_family_lane_matrix_preset",
                return_value={"summary_path": str(output_path), "all_ok": True},
            ) as run_lane_matrix_preset:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(
                        [
                            "family-lane-matrix-preset",
                            "--preset",
                            "cmpq_fault_rearm_default",
                            "--sim-time",
                            "2us",
                            "--output",
                            str(output_path),
                        ]
                    )

        self.assertEqual(rc, 0)
        self.assertEqual(run_lane_matrix_preset.call_args.kwargs["preset"], "cmpq_fault_rearm_default")
        self.assertEqual(run_lane_matrix_preset.call_args.kwargs["sim_time"], "2us")
        self.assertEqual(run_lane_matrix_preset.call_args.kwargs["summary_path"], output_path)
        print_mock.assert_called_once_with(output_path)

    def test_main_help_lists_family_lane_commands_once(self) -> None:
        proc = subprocess.run(
            ["python3", str(Path(riscv_snn_lab.__file__)), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(proc.returncode, 0)
        command_lines = [
            line.strip().split()[0]
            for line in proc.stdout.splitlines()
            if line.startswith("    ") and not line.startswith("      ")
        ]
        self.assertEqual(command_lines.count("family-asset-audit"), 1)
        self.assertEqual(command_lines.count("family-lane"), 1)
        self.assertEqual(command_lines.count("family-lane-preset"), 1)
        self.assertEqual(command_lines.count("family-lane-matrix"), 1)
        self.assertEqual(command_lines.count("family-lane-matrix-preset"), 1)
        self.assertEqual(command_lines.count("optional-history-refresh"), 1)

    def test_main_observer_refresh_prints_observer_summary_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "nightly-sidecar-observer-summary.json"
            with mock.patch.object(
                riscv_snn_lab,
                "refresh_observer_surfaces",
                return_value={"observer_summary_path": output_path},
            ) as refresh_observer:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(["observer-refresh"])

        self.assertEqual(rc, 0)
        self.assertEqual(refresh_observer.call_args.kwargs["sample_paths"], [])
        print_mock.assert_called_once_with(output_path)

    def test_main_optional_history_refresh_prints_history_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "queue-optional-equivalence-history.json"
            sample_path = Path(td) / "2026-04-02-equiv-matrix-queue-optional.json"
            with mock.patch.object(
                riscv_snn_lab,
                "refresh_optional_equivalence_history",
                return_value={"summary_path": str(output_path)},
            ) as refresh_optional_history:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(
                        [
                            "optional-history-refresh",
                            "--group",
                            "queue_optional",
                            "--sample",
                            str(sample_path),
                            "--reset",
                        ]
                    )

        self.assertEqual(rc, 0)
        self.assertEqual(refresh_optional_history.call_args.kwargs["group"], "queue_optional")
        self.assertEqual(refresh_optional_history.call_args.kwargs["sample_paths"], [sample_path])
        self.assertTrue(refresh_optional_history.call_args.kwargs["reset_existing"])
        print_mock.assert_called_once_with(output_path)

    def test_main_optional_history_refresh_accepts_compact_since_latest_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "queue-optional-equivalence-history.json"
            with mock.patch.object(
                riscv_snn_lab,
                "refresh_optional_equivalence_history",
                return_value={"summary_path": str(output_path)},
            ) as refresh_optional_history:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(
                        [
                            "optional-history-refresh",
                            "--group",
                            "queue_optional",
                            "--compact-since-latest-recovery",
                        ]
                    )

        self.assertEqual(rc, 0)
        self.assertEqual(refresh_optional_history.call_args.kwargs["group"], "queue_optional")
        self.assertTrue(refresh_optional_history.call_args.kwargs["compact_since_latest_recovery"])
        print_mock.assert_called_once_with(output_path)

    def test_main_observer_history_refresh_prints_history_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "observer-full-equivalence-history.json"
            with mock.patch.object(
                riscv_snn_lab,
                "refresh_observer_full_equivalence_history",
                return_value={"summary_path": str(output_path)},
            ) as refresh_observer_history:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(["observer-history-refresh"])

        self.assertEqual(rc, 0)
        self.assertEqual(refresh_observer_history.call_count, 1)
        self.assertFalse(refresh_observer_history.call_args.kwargs["compact_since_latest_recovery"])
        print_mock.assert_called_once_with(output_path)

    def test_main_observer_history_refresh_accepts_compact_since_latest_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "observer-full-equivalence-history.json"
            with mock.patch.object(
                riscv_snn_lab,
                "refresh_observer_full_equivalence_history",
                return_value={"summary_path": str(output_path)},
            ) as refresh_observer_history:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(["observer-history-refresh", "--compact-since-latest-recovery"])

        self.assertEqual(rc, 0)
        self.assertEqual(refresh_observer_history.call_count, 1)
        self.assertTrue(refresh_observer_history.call_args.kwargs["compact_since_latest_recovery"])
        print_mock.assert_called_once_with(output_path)

    def test_main_observer_history_compact_refresh_prints_history_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "observer-full-equivalence-history.json"
            with mock.patch.object(
                riscv_snn_lab,
                "refresh_observer_history_surface",
                return_value={"summary_path": str(output_path)},
                create=True,
            ) as refresh_observer_history:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(["observer-history-compact-refresh"])

        self.assertEqual(rc, 0)
        self.assertEqual(refresh_observer_history.call_count, 1)
        self.assertTrue(refresh_observer_history.call_args.kwargs["compact_since_latest_recovery"])
        print_mock.assert_called_once_with(output_path)

    def test_main_mainline_refresh_prints_current_mainline_status_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "current-mainline-status.md"
            with mock.patch.object(
                riscv_snn_lab,
                "refresh_mainline_surfaces",
                return_value={"current_mainline_status_path": output_path},
            ) as refresh_mainline:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(["mainline-refresh", "--group", "completion_overflow_optional"])

        self.assertEqual(rc, 0)
        self.assertEqual(refresh_mainline.call_args.kwargs["group"], "completion_overflow_optional")
        print_mock.assert_called_once_with(output_path)

    def test_main_reference_compare_prints_family_summary_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "external_dyn_desc_ref-reference-compare.json"
            with mock.patch.object(
                riscv_snn_lab,
                "run_reference_compare_family",
                return_value={"summary_path": str(output_path), "gate_ok": True},
            ) as run_reference_compare:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(["reference-compare", "--family", "external_dyn_desc_ref"])

        self.assertEqual(rc, 0)
        self.assertEqual(run_reference_compare.call_args.kwargs["family"], "external_dyn_desc_ref")
        print_mock.assert_called_once_with(output_path)

    def test_main_reference_compare_matrix_prints_summary_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "reference-compare-matrix.json"
            with mock.patch.object(
                riscv_snn_lab,
                "run_reference_compare_matrix",
                return_value={"summary_path": str(output_path), "all_ok": True},
            ) as run_reference_compare_matrix:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(["reference-compare-matrix", "--group", "all"])

        self.assertEqual(rc, 0)
        self.assertEqual(run_reference_compare_matrix.call_args.kwargs["group"], "all")
        print_mock.assert_called_once_with(output_path)

    def test_main_reference_compare_refresh_prints_report_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "reference-compare-nightly-report.json"
            with mock.patch.object(
                riscv_snn_lab,
                "refresh_reference_compare_surface",
                return_value={"report_path": str(output_path), "gate_ok": True},
            ) as refresh_reference_compare:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(["reference-compare-refresh", "--group", "all"])

        self.assertEqual(rc, 0)
        self.assertEqual(refresh_reference_compare.call_args.kwargs["group"], "all")
        print_mock.assert_called_once_with(output_path)

    def test_main_reference_program_compare_prints_family_summary_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "external_dyn_desc_ref-reference-program-compare.json"
            with mock.patch.object(
                riscv_snn_lab,
                "run_reference_program_compare_family",
                return_value={"summary_path": str(output_path), "gate_ok": True},
                create=True,
            ) as run_reference_program_compare:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(["reference-program-compare", "--family", "external_dyn_desc_ref"])

        self.assertEqual(rc, 0)
        self.assertEqual(run_reference_program_compare.call_args.kwargs["family"], "external_dyn_desc_ref")
        print_mock.assert_called_once_with(output_path)

    def test_main_reference_program_compare_accepts_stat_snapshot_family(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "stat_snapshot_ref-reference-program-compare.json"
            with mock.patch.object(
                riscv_snn_lab,
                "run_reference_program_compare_family",
                return_value={"summary_path": str(output_path), "gate_ok": True},
                create=True,
            ) as run_reference_program_compare:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(["reference-program-compare", "--family", "stat_snapshot_ref"])

        self.assertEqual(rc, 0)
        self.assertEqual(run_reference_program_compare.call_args.kwargs["family"], "stat_snapshot_ref")
        print_mock.assert_called_once_with(output_path)

    def test_main_reference_program_compare_matrix_prints_summary_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "reference-program-compare-matrix.json"
            with mock.patch.object(
                riscv_snn_lab,
                "run_reference_program_compare_matrix",
                return_value={"summary_path": str(output_path), "all_ok": True},
                create=True,
            ) as run_reference_program_compare_matrix:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(["reference-program-compare-matrix", "--group", "all"])

        self.assertEqual(rc, 0)
        self.assertEqual(run_reference_program_compare_matrix.call_args.kwargs["group"], "all")
        print_mock.assert_called_once_with(output_path)

    def test_main_reference_program_compare_refresh_prints_report_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "reference-program-compare-nightly-report.json"
            with mock.patch.object(
                riscv_snn_lab,
                "refresh_reference_program_compare_surface",
                return_value={"report_path": str(output_path), "gate_ok": True},
                create=True,
            ) as refresh_reference_program_compare:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(["reference-program-compare-refresh", "--group", "all"])

        self.assertEqual(rc, 0)
        self.assertEqual(refresh_reference_program_compare.call_args.kwargs["group"], "all")
        print_mock.assert_called_once_with(output_path)

    def test_main_observer_fail_recovery_prints_summary_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "observer-fail-recovery-loop-summary.json"
            with mock.patch.object(
                riscv_snn_lab,
                "run_observer_fail_recovery_loop",
                return_value={"summary_path": str(output_path), "all_ok": True},
            ) as run_loop:
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(["observer-fail-recovery"])

        self.assertEqual(rc, 0)
        self.assertIsNone(run_loop.call_args.kwargs["group"])
        self.assertEqual(run_loop.call_args.kwargs["sample_paths"], None)
        print_mock.assert_called_once_with(output_path)

    def test_main_observer_fail_recovery_returns_nonzero_when_loop_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "observer-fail-recovery-loop-summary.json"
            with mock.patch.object(
                riscv_snn_lab,
                "run_observer_fail_recovery_loop",
                return_value={"summary_path": str(output_path), "all_ok": False},
            ):
                with mock.patch("builtins.print") as print_mock:
                    rc = riscv_snn_lab.main(["observer-fail-recovery"])

        self.assertEqual(rc, 2)
        print_mock.assert_called_once_with(output_path)

    def test_main_mainline_refresh_uses_authority_default_group_when_unspecified(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            output_path = td_path / "current-mainline-status.md"
            with mock.patch.object(
                riscv_snn_lab,
                "_mainline_refresh_default_group",
                return_value="queue_optional",
            ):
                with mock.patch.object(
                    riscv_snn_lab,
                    "refresh_mainline_surfaces",
                    return_value={"current_mainline_status_path": output_path},
                ) as refresh_mainline:
                    with mock.patch("builtins.print") as print_mock:
                        rc = riscv_snn_lab.main(["mainline-refresh"])

        self.assertEqual(rc, 0)
        self.assertEqual(refresh_mainline.call_args.kwargs["group"], "queue_optional")
        print_mock.assert_called_once_with(output_path)

    def test_run_observer_fail_recovery_loop_wires_optional_history_mainline_and_audit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            summary_path = td_path / "observer-fail-recovery-loop-summary.json"
            sample_path = td_path / "2026-04-08-equiv-matrix-all.json"
            sidecar_path = td_path / "nightly-sidecar-report.json"
            observer_summary_path = td_path / "nightly-sidecar-observer-summary.json"
            observer_history_path = td_path / "observer-full-equivalence-history.json"
            dossier_path = td_path / "queue-optional-promotion-dossier.json"
            optional_history_path = td_path / "queue-optional-equivalence-history.json"
            audit_path = td_path / "stable-surface-refresh-audit.json"
            current_mainline_path = td_path / "current-mainline-status.md"
            observer_history_path.write_text(
                json.dumps(
                    {
                        "summary_path": str(observer_history_path),
                        "refresh_mode": "compact_latest_recovery",
                        "latest_recovered_date": "2026-04-08",
                        "effective_entry_count": 1,
                        "effective_all_dates_ok": True,
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(
                riscv_snn_lab,
                "_mainline_refresh_default_group",
                return_value="queue_optional",
            ):
                with mock.patch.object(
                    riscv_snn_lab,
                    "_optional_history_refresh_mode",
                    return_value="compact_latest_recovery",
                ):
                    with mock.patch.object(
                        riscv_snn_lab,
                        "refresh_optional_equivalence_history",
                        return_value={
                            "summary_path": str(optional_history_path),
                            "refresh_mode": "compact_latest_recovery",
                            "latest_recovered_date": "2026-04-08",
                            "effective_entry_count": 2,
                            "effective_all_dates_ok": True,
                        },
                    ) as refresh_optional:
                        with mock.patch.object(
                            riscv_snn_lab,
                            "refresh_mainline_surfaces",
                            return_value={
                                "sidecar_path": sidecar_path,
                                "observer_history_path": observer_history_path,
                                "observer_summary_path": observer_summary_path,
                                "current_mainline_status_path": current_mainline_path,
                                "optional_promotion_dossier_path": dossier_path,
                            },
                        ) as refresh_mainline:
                            with mock.patch.object(
                                riscv_snn_lab,
                                "audit_stable_surface_refresh",
                                return_value={"summary_path": str(audit_path), "all_ok": True},
                            ) as audit_refresh:
                                summary = riscv_snn_lab.run_observer_fail_recovery_loop(
                                    group=None,
                                    sample_paths=[sample_path],
                                    sidecar_path=sidecar_path,
                                    observer_summary_path=observer_summary_path,
                                    dossier_output_path=dossier_path,
                                    optional_history_output_path=optional_history_path,
                                    stable_surface_audit_output_path=audit_path,
                                    output_path=summary_path,
                                    lab_root=td_path,
                                )

        self.assertTrue(summary["all_ok"])
        self.assertEqual(summary["group"], "queue_optional")
        self.assertEqual(summary["group_history_refresh_mode_expected"], "compact_latest_recovery")
        self.assertEqual(summary["group_history_refresh_mode"], "compact_latest_recovery")
        self.assertEqual(summary["observer_history_refresh_mode"], "compact_latest_recovery")
        self.assertEqual(summary["observer_history_latest_recovered_date"], "2026-04-08")
        self.assertEqual(summary["observer_history_effective_entry_count"], 1)
        self.assertTrue(summary["observer_history_effective_all_dates_ok"])
        self.assertEqual(summary["optional_history_summary_path"], str(optional_history_path))
        self.assertEqual(summary["stable_surface_refresh_audit_path"], str(audit_path))
        self.assertEqual(summary["summary_path"], str(summary_path))
        self.assertEqual(refresh_optional.call_args.kwargs["group"], "queue_optional")
        self.assertEqual(refresh_optional.call_args.kwargs["sample_paths"], [sample_path])
        self.assertTrue(refresh_optional.call_args.kwargs["compact_since_latest_recovery"])
        self.assertEqual(refresh_mainline.call_args.kwargs["group"], "queue_optional")
        self.assertTrue(
            refresh_mainline.call_args.kwargs["compact_observer_history_since_latest_recovery"]
        )
        self.assertEqual(audit_refresh.call_args.kwargs["sidecar_path"], sidecar_path)

    def test_refresh_mainline_surfaces_records_optional_promotion_dossier_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            observer_summary_path = refs_dir / "nightly-sidecar-observer-summary.json"
            research_path = refs_dir / "riscv-snn-research-report.json"
            validation_path = refs_dir / "observer-adequacy-validation.json"
            current_mainline_path = refs_dir / "current-mainline-status.md"
            dossier_path = refs_dir / "completion-overflow-optional-promotion-dossier.json"

            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "generated_utc": "2026-03-31T00:00:00+00:00",
                        "gate_name": "riscv_snn_experimental_nightly",
                        "gate_version": "1.1",
                        "gate_ok": True,
                        "required_families": ["external_dyn_desc_ref"],
                        "report_path": str(sidecar_path),
                        "observer_summary_path": str(observer_summary_path),
                        "research_report_path": str(research_path),
                        "observer_adequacy_validation_path": str(validation_path),
                    }
                ),
                encoding="utf-8",
            )
            observer_summary_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_sidecar_observer_summary",
                        "authority_entrypoint": {"summary_path": str(sidecar_path)},
                        "optional_surfaces": {
                            "full_equivalence": {
                                "entry_count": 1,
                                "history_contract": "observer_sample_sequence_v1",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            research_path.write_text(
                json.dumps({"observer_adequacy": {"status": "ready_with_fail_recovery_sample"}}),
                encoding="utf-8",
            )
            validation_path.write_text(
                json.dumps({"status": "pass", "mismatch_count": 0}),
                encoding="utf-8",
            )

            current_mainline_path.write_text("# current mainline\n", encoding="utf-8")

            with mock.patch.object(
                riscv_snn_lab,
                "refresh_observer_surfaces",
                return_value={
                    "observer_summary_path": observer_summary_path,
                    "observer_history_path": refs_dir / "observer-full-equivalence-history.json",
                    "research_report_path": research_path,
                    "observer_adequacy_validation_path": validation_path,
                    "current_mainline_status_path": current_mainline_path,
                    "summary_md_path": refs_dir / "nightly-sidecar-summary.md",
                },
            ) as refresh_observer:
                with mock.patch.object(
                    riscv_snn_lab,
                    "export_optional_promotion_dossier",
                    return_value=dossier_path,
                ):
                    outputs = riscv_snn_lab.refresh_mainline_surfaces(
                        group="completion_overflow_optional",
                        lab_root=lab_root,
                    )

        self.assertEqual(outputs["optional_promotion_dossier_path"], dossier_path)
        self.assertEqual(outputs["current_mainline_status_path"], current_mainline_path)
        self.assertEqual(
            refresh_observer.call_args.kwargs["optional_promotion_dossier_path"],
            dossier_path,
        )

    def test_refresh_mainline_surfaces_refreshes_all_optional_group_admissions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)
            (refs_dir / "nightly-sidecar-report.json").write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                    }
                ),
                encoding="utf-8",
            )

            observer_summary_path = refs_dir / "nightly-sidecar-observer-summary.json"
            current_mainline_path = refs_dir / "current-mainline-status.md"
            dossier_path = refs_dir / "completion-overflow-optional-promotion-dossier.json"
            selected_audit_path = refs_dir / "2026-04-04-completion-overflow-optional-admission-audit.json"

            def _fake_export_optional_promotion_dossier(**_: object) -> Path:
                selected_audit_path.write_text(
                    json.dumps(
                        {
                            "group": "completion_overflow_optional",
                            "summary_path": str(selected_audit_path),
                        }
                    ),
                    encoding="utf-8",
                )
                return dossier_path

            with mock.patch.object(
                riscv_snn_lab,
                "_mainline_optional_groups",
                return_value={
                    "completion_overflow_optional": {"families": ["completion_queue_overflow_ref"]},
                    "queue_optional": {
                        "families": ["completion_queue_overflow_ref", "queue_backpressure_ref"]
                    },
                },
            ):
                with mock.patch.object(
                    riscv_snn_lab,
                    "run_family_admission_audit",
                    side_effect=[
                        {"summary_path": str(refs_dir / "2026-04-04-queue-optional-admission-audit.json")},
                    ],
                ) as run_admission:
                    with mock.patch.object(
                        riscv_snn_lab,
                        "export_optional_promotion_dossier",
                        side_effect=_fake_export_optional_promotion_dossier,
                    ):
                        with mock.patch.object(
                            riscv_snn_lab,
                            "refresh_observer_surfaces",
                            return_value={
                                "observer_summary_path": observer_summary_path,
                                "current_mainline_status_path": current_mainline_path,
                            },
                        ):
                            outputs = riscv_snn_lab.refresh_mainline_surfaces(
                                group="completion_overflow_optional",
                                lab_root=lab_root,
                            )

        self.assertEqual(
            [call.kwargs["group"] for call in run_admission.call_args_list],
            ["queue_optional"],
        )
        self.assertEqual(
            outputs["optional_admission_paths"],
            {
                "completion_overflow_optional": selected_audit_path,
                "queue_optional": refs_dir / "2026-04-04-queue-optional-admission-audit.json",
            },
        )

    def test_refresh_report_optional_group_surfaces_prefers_latest_dated_refs_and_updates_queue_alias(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            spec_dir = lab_root / "spec_authority"
            refs_dir.mkdir(parents=True, exist_ok=True)
            spec_dir.mkdir(parents=True, exist_ok=True)

            (spec_dir / "riscv_snn_mainline_gate_v1.json").write_text(
                json.dumps(
                    {
                        "required_families": ["external_dyn_desc_ref"],
                        "optional_groups": {
                            "queue_optional": {
                                "families": [
                                    "completion_queue_overflow_ref",
                                    "queue_backpressure_ref",
                                ],
                                "blocking": False,
                            },
                            "completion_overflow_optional": {
                                "families": ["completion_queue_overflow_ref"],
                                "blocking": False,
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            stale_queue_path = refs_dir / "2026-04-01-equiv-matrix-queue-optional.json"
            fresh_queue_path = refs_dir / "2026-04-02-equiv-matrix-queue-optional.json"
            stale_completion_path = refs_dir / "2026-04-01-equiv-matrix-completion-overflow-optional.json"
            fresh_completion_path = refs_dir / "2026-04-02-equiv-matrix-completion-overflow-optional.json"
            for path, requested_group, generated_utc, all_ok, count in (
                (stale_queue_path, "queue_optional", "2026-04-01T00:00:00+00:00", False, 2),
                (fresh_queue_path, "queue_optional", "2026-04-02T00:00:00+00:00", True, 2),
                (stale_completion_path, "completion_overflow_optional", "2026-04-01T00:00:00+00:00", False, 1),
                (fresh_completion_path, "completion_overflow_optional", "2026-04-02T00:00:00+00:00", True, 1),
            ):
                path.write_text(
                    json.dumps(
                        {
                            "artifact_role": "dated_equivalence_matrix",
                            "canonical_surface": True,
                            "requested_group": requested_group,
                            "generated_utc": generated_utc,
                            "all_ok": all_ok,
                            "count": count,
                            "families": [],
                            "summary_path": str(path),
                            "source_kind": "group_matrix",
                        }
                    ),
                    encoding="utf-8",
                )

            stale_queue_surface = json.loads(stale_queue_path.read_text(encoding="utf-8"))
            stale_completion_surface = json.loads(stale_completion_path.read_text(encoding="utf-8"))
            refreshed = riscv_snn_lab._refresh_report_optional_group_surfaces(
                {
                    "optional_group_surfaces": {
                        "queue_optional": stale_queue_surface,
                        "completion_overflow_optional": stale_completion_surface,
                    },
                    "queue_equivalence": stale_queue_surface,
                },
                lab_root=lab_root,
            )

        self.assertEqual(
            refreshed["optional_group_surfaces"]["queue_optional"]["summary_path"],
            str(fresh_queue_path),
        )
        self.assertTrue(refreshed["optional_group_surfaces"]["queue_optional"]["all_ok"])
        self.assertEqual(
            refreshed["optional_group_surfaces"]["completion_overflow_optional"]["summary_path"],
            str(fresh_completion_path),
        )
        self.assertTrue(refreshed["optional_group_surfaces"]["completion_overflow_optional"]["all_ok"])
        self.assertEqual(refreshed["queue_equivalence"]["summary_path"], str(fresh_queue_path))
        self.assertTrue(refreshed["queue_equivalence"]["all_ok"])

    def test_refresh_mainline_surfaces_refreshes_dossier_before_observer_summary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            observer_summary_path = refs_dir / "nightly-sidecar-observer-summary.json"
            research_path = refs_dir / "riscv-snn-research-report.json"
            validation_path = refs_dir / "observer-adequacy-validation.json"
            current_mainline_path = refs_dir / "current-mainline-status.md"
            dossier_path = refs_dir / "completion-overflow-optional-promotion-dossier.json"
            old_audit_path = refs_dir / "2026-03-31-completion-overflow-optional-admission-audit.json"
            new_audit_path = refs_dir / "2026-04-01-completion-overflow-optional-admission-audit.json"

            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "generated_utc": "2026-04-01T00:00:00+00:00",
                        "gate_name": "riscv_snn_experimental_nightly",
                        "gate_version": "1.1",
                        "gate_ok": True,
                        "required_families": ["external_dyn_desc_ref"],
                        "report_path": str(sidecar_path),
                        "observer_summary_path": str(observer_summary_path),
                        "research_report_path": str(research_path),
                        "observer_adequacy_validation_path": str(validation_path),
                    }
                ),
                encoding="utf-8",
            )
            old_audit_path.write_text(
                json.dumps(
                    {
                        "group": "completion_overflow_optional",
                        "promotion_ready": True,
                        "explicit_review_ok": True,
                        "blocking": False,
                        "summary_path": str(old_audit_path),
                    }
                ),
                encoding="utf-8",
            )
            research_path.write_text(
                json.dumps({"observer_adequacy": {"status": "ready_with_fail_recovery_sample"}}),
                encoding="utf-8",
            )
            validation_path.write_text(
                json.dumps({"status": "pass", "mismatch_count": 0}),
                encoding="utf-8",
            )

            def _fake_refresh_observer_surfaces(**_: object) -> dict[str, Path]:
                latest_admission, latest_path = riscv_snn_lab._latest_optional_admission_audit(
                    group="completion_overflow_optional",
                    lab_root=lab_root,
                )
                observer_summary_path.write_text(
                    json.dumps(
                        {
                            "artifact_role": "stable_sidecar_observer_summary",
                            "authority_entrypoint": {"summary_path": str(sidecar_path)},
                            "optional_group_rollups": {
                                "completion_overflow_optional": {
                                    "promotion_ready": latest_admission["promotion_ready"],
                                    "admission_summary_path": str(latest_path),
                                }
                            },
                            "optional_surfaces": {
                                "full_equivalence": {
                                    "entry_count": 1,
                                    "history_contract": "observer_sample_sequence_v1",
                                }
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                return {
                    "observer_summary_path": observer_summary_path,
                    "observer_history_path": refs_dir / "observer-full-equivalence-history.json",
                    "research_report_path": research_path,
                    "observer_adequacy_validation_path": validation_path,
                    "current_mainline_status_path": current_mainline_path,
                }

            def _fake_export_optional_promotion_dossier(**_: object) -> Path:
                new_audit_path.write_text(
                    json.dumps(
                        {
                            "group": "completion_overflow_optional",
                            "promotion_ready": False,
                            "explicit_review_ok": True,
                            "blocking": False,
                            "summary_path": str(new_audit_path),
                        }
                    ),
                    encoding="utf-8",
                )
                dossier_path.write_text(
                    json.dumps(
                        {
                            "group": "completion_overflow_optional",
                            "promotion_ready": False,
                        }
                    ),
                    encoding="utf-8",
                )
                return dossier_path

            with mock.patch.object(
                riscv_snn_lab,
                "refresh_observer_surfaces",
                side_effect=_fake_refresh_observer_surfaces,
            ):
                with mock.patch.object(
                    riscv_snn_lab,
                    "export_optional_promotion_dossier",
                    side_effect=_fake_export_optional_promotion_dossier,
                ):
                    with mock.patch.object(
                        riscv_snn_lab,
                        "_refresh_current_mainline_status",
                        return_value=current_mainline_path,
                    ):
                        with mock.patch.object(riscv_snn_lab, "build_sidecar_summary_md", return_value=Path("unused")):
                            riscv_snn_lab.refresh_mainline_surfaces(
                                group="completion_overflow_optional",
                                lab_root=lab_root,
                            )

            observer_summary = json.loads(observer_summary_path.read_text(encoding="utf-8"))

        self.assertFalse(
            observer_summary["optional_group_rollups"]["completion_overflow_optional"]["promotion_ready"]
        )
        self.assertEqual(
            observer_summary["optional_group_rollups"]["completion_overflow_optional"]["admission_summary_path"],
            str(new_audit_path),
        )

    def test_refresh_derived_stable_surfaces_rerenders_current_mainline_after_refresh_metadata_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            spec_dir = lab_root / "spec_authority"
            refs_dir.mkdir(parents=True, exist_ok=True)
            spec_dir.mkdir(parents=True, exist_ok=True)

            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            observer_summary_path = refs_dir / "nightly-sidecar-observer-summary.json"
            research_path = refs_dir / "riscv-snn-research-report.json"
            validation_path = refs_dir / "observer-adequacy-validation.json"
            current_mainline_path = refs_dir / "current-mainline-status.md"
            summary_md_path = refs_dir / "nightly-sidecar-summary.md"
            dossier_path = refs_dir / "queue-optional-promotion-dossier.json"

            (spec_dir / "riscv_snn_mainline_gate_v1.json").write_text(
                json.dumps(
                    {
                        "required_families": ["external_dyn_desc_ref"],
                        "optional_groups": {
                            "queue_optional": {
                                "families": ["queue_backpressure_ref"],
                                "blocking": False,
                            },
                        },
                        "mainline_defaults": {
                            "primary_optional_group": "queue_optional",
                            "mainline_refresh_default_group": "queue_optional",
                        },
                        "promotion_contract": {},
                    }
                ),
                encoding="utf-8",
            )
            (spec_dir / "riscv_snn_runtime_gate_v1.json").write_text(
                json.dumps({"reason_ids": [], "checks": {}, "families": {}}),
                encoding="utf-8",
            )
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "generated_utc": "2026-04-03T00:00:00+00:00",
                        "gate_name": "riscv_snn_experimental_nightly",
                        "gate_version": "1.1",
                        "gate_ok": True,
                        "required_families": ["external_dyn_desc_ref"],
                        "report_path": str(sidecar_path),
                        "observer_summary_path": str(observer_summary_path),
                        "research_report_path": str(research_path),
                        "observer_adequacy_validation_path": str(validation_path),
                        "summary_md_path": str(summary_md_path),
                    }
                ),
                encoding="utf-8",
            )
            research_path.write_text(
                json.dumps({"observer_adequacy": {"status": "ready_with_fail_recovery_sample"}}),
                encoding="utf-8",
            )
            validation_path.write_text(
                json.dumps({"status": "pass", "mismatch_count": 0}),
                encoding="utf-8",
            )
            (refs_dir / "2026-04-03-queue-optional-admission-audit.json").write_text(
                json.dumps(
                    {
                        "group": "queue_optional",
                        "summary_path": str(refs_dir / "2026-04-03-queue-optional-admission-audit.json"),
                        "promotion_ready": True,
                        "explicit_review_ok": True,
                        "blocking": False,
                        "group_history_freshness_mode": "since_latest_recovery",
                        "group_history_effective_entry_count": 1,
                        "group_history_effective_all_dates_ok": True,
                    }
                ),
                encoding="utf-8",
            )
            (refs_dir / "queue-optional-equivalence-history.json").write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_optional_equivalence_history",
                        "group": "queue_optional",
                        "history_contract": "canonical_queue_optional_only",
                        "summary_path": str(refs_dir / "queue-optional-equivalence-history.json"),
                        "latest_summary_path": str(refs_dir / "2026-04-03-equiv-matrix-queue-optional.json"),
                        "latest_date": "2026-04-03",
                        "entry_count": 4,
                        "all_ok_latest": True,
                        "all_dates_ok": False,
                        "first_fail_date": "2026-04-02",
                        "latest_recovered_date": "2026-04-03",
                        "excluded_entry_count": 0,
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(
                riscv_snn_lab,
                "run_research_postprocess",
                return_value={
                    "research_report_path": research_path,
                    "observer_adequacy_validation_path": validation_path,
                },
            ):
                riscv_snn_lab._refresh_derived_stable_surfaces(
                    sidecar_path=sidecar_path,
                    optional_promotion_dossier_path=dossier_path,
                    lab_root=lab_root,
                )

            refreshed_report = json.loads(sidecar_path.read_text(encoding="utf-8"))
            current_mainline = current_mainline_path.read_text(encoding="utf-8")

        self.assertIn(
            f"`{refreshed_report['stable_surface_refresh']['refreshed_utc']}`",
            current_mainline,
        )
        self.assertIn(
            f"`{dossier_path}`",
            current_mainline,
        )

    def test_refresh_supplementary_surface_history_carries_compare_source_history(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            compare_refs_dir = td_path / "sst_dram_si" / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)
            compare_refs_dir.mkdir(parents=True, exist_ok=True)

            compare_history_path = compare_refs_dir / "compare-smoke-history.json"
            compare_report_path = compare_refs_dir / "compare-nightly-report.json"
            sidecar_path = refs_dir / "nightly-sidecar-report.json"

            compare_history_path.write_text(
                json.dumps(
                    {
                        "history_contract": "compare_smoke_observer_v1",
                        "entry_count": 2,
                        "latest_date": "2026-04-07",
                        "all_dates_ok": True,
                        "latest_recovered_date": "2026-04-07",
                        "freshness_mode": "since_latest_recovery",
                        "effective_entry_count": 2,
                        "effective_all_dates_ok": True,
                        "stale": False,
                        "entries": [
                            {"date": "2026-04-07", "all_ok": True},
                            {"date": "2026-04-06", "all_ok": True},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            compare_report_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "history": {
                            "path": str(compare_history_path),
                            "latest_date": "2026-04-07",
                            "all_dates_ok": True,
                            "latest_recovered_date": "2026-04-07",
                            "freshness_mode": "since_latest_recovery",
                            "effective_entry_count": 2,
                            "effective_all_dates_ok": True,
                            "stale": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "supplementary_surfaces": {
                            "compare": {
                                "surface_kind": "compare_exec_mode_smoke",
                                "blocking": False,
                                "present": True,
                                "load_error": None,
                                "report_path": str(compare_report_path),
                                "summary_md_path": str(compare_refs_dir / "compare-nightly-summary.md"),
                                "current_mainline_status_path": str(compare_refs_dir / "compare-current-status.md"),
                                "gate_ok": True,
                                "latest_date": "2026-04-07",
                                "stale": False,
                                "freshness_mode": "since_latest_recovery",
                                "effective_all_dates_ok": True,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            history = riscv_snn_lab.refresh_supplementary_surface_history(
                sidecar_path=sidecar_path,
                lab_root=lab_root,
            )

        compare = history["surfaces"]["compare"]
        self.assertEqual(history["history_contract"], "supplementary_surface_observer_v1")
        self.assertEqual(compare["history_contract"], "compare_smoke_observer_v1")
        self.assertEqual(compare["latest_date"], "2026-04-07")
        self.assertEqual(compare["entry_count"], 2)
        self.assertEqual(compare["latest_recovered_date"], "2026-04-07")
        self.assertEqual(compare["history_path"], str(compare_history_path))

    def test_refresh_supplementary_surface_history_uses_contract_fallback_when_source_history_contract_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            compare_refs_dir = td_path / "sst_dram_si" / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)
            compare_refs_dir.mkdir(parents=True, exist_ok=True)

            compare_report_path = compare_refs_dir / "compare-nightly-report.json"
            sidecar_path = refs_dir / "nightly-sidecar-report.json"

            compare_report_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "history": {
                            "latest_date": "2026-04-07",
                            "entry_count": 1,
                            "all_dates_ok": True,
                            "stale": False,
                            "freshness_mode": "since_latest_recovery",
                            "effective_all_dates_ok": True,
                        },
                    }
                ),
                encoding="utf-8",
            )
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "supplementary_surfaces": {
                            "compare": {
                                "surface_kind": "compare_exec_mode_smoke",
                                "blocking": False,
                                "present": True,
                                "load_error": None,
                                "report_path": str(compare_report_path),
                                "summary_md_path": str(compare_refs_dir / "compare-nightly-summary.md"),
                                "current_mainline_status_path": str(compare_refs_dir / "compare-current-status.md"),
                                "gate_ok": True,
                                "latest_date": "2026-04-07",
                                "stale": False,
                                "freshness_mode": "since_latest_recovery",
                                "effective_all_dates_ok": True,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            history = riscv_snn_lab.refresh_supplementary_surface_history(
                sidecar_path=sidecar_path,
                lab_root=lab_root,
            )

        compare = history["surfaces"]["compare"]
        self.assertEqual(history["contract_name"], "riscv_snn_supplementary_surface")
        self.assertEqual(history["contract_version"], "1.0")
        self.assertEqual(history["history_contract"], "supplementary_surface_observer_v1")
        self.assertTrue(str(history["authority_path"]).endswith("riscv_snn_supplementary_surface_v1.json"))
        self.assertEqual(compare["history_contract"], "compare_source_history_passthrough_v1")

    def test_refresh_derived_stable_surfaces_records_audit_and_supplementary_history_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            spec_dir = lab_root / "spec_authority"
            compare_refs_dir = td_path / "sst_dram_si" / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)
            spec_dir.mkdir(parents=True, exist_ok=True)
            compare_refs_dir.mkdir(parents=True, exist_ok=True)

            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            observer_summary_path = refs_dir / "nightly-sidecar-observer-summary.json"
            research_path = refs_dir / "riscv-snn-research-report.json"
            validation_path = refs_dir / "observer-adequacy-validation.json"
            current_mainline_path = refs_dir / "current-mainline-status.md"
            summary_md_path = refs_dir / "nightly-sidecar-summary.md"
            compare_history_path = compare_refs_dir / "compare-smoke-history.json"
            compare_report_path = compare_refs_dir / "compare-nightly-report.json"

            (spec_dir / "riscv_snn_mainline_gate_v1.json").write_text(
                json.dumps(
                    {
                        "required_families": ["external_dyn_desc_ref"],
                        "optional_groups": {
                            "queue_optional": {
                                "families": ["queue_backpressure_ref"],
                                "blocking": False,
                            },
                        },
                        "mainline_defaults": {
                            "primary_optional_group": "queue_optional",
                            "mainline_refresh_default_group": "queue_optional",
                        },
                        "promotion_contract": {},
                    }
                ),
                encoding="utf-8",
            )
            (spec_dir / "riscv_snn_runtime_gate_v1.json").write_text(
                json.dumps({"reason_ids": [], "checks": {}, "families": {}}),
                encoding="utf-8",
            )
            compare_history_path.write_text(
                json.dumps(
                    {
                        "history_contract": "compare_smoke_observer_v1",
                        "entry_count": 1,
                        "latest_date": "2026-04-07",
                        "all_dates_ok": True,
                        "latest_recovered_date": None,
                        "freshness_mode": "since_latest_recovery",
                        "effective_entry_count": 1,
                        "effective_all_dates_ok": True,
                        "stale": False,
                        "entries": [{"date": "2026-04-07", "all_ok": True}],
                    }
                ),
                encoding="utf-8",
            )
            compare_report_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "history": {
                            "path": str(compare_history_path),
                            "latest_date": "2026-04-07",
                            "all_dates_ok": True,
                            "latest_recovered_date": None,
                            "freshness_mode": "since_latest_recovery",
                            "effective_entry_count": 1,
                            "effective_all_dates_ok": True,
                            "stale": False,
                        },
                        "stable_surfaces": {
                            "report_path": str(compare_report_path),
                            "observer_summary_path": str(compare_refs_dir / "compare-nightly-observer-summary.json"),
                            "summary_md_path": str(compare_refs_dir / "compare-nightly-summary.md"),
                            "current_mainline_status_path": str(compare_refs_dir / "compare-current-status.md"),
                        },
                    }
                ),
                encoding="utf-8",
            )
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "generated_utc": "2026-04-03T00:00:00+00:00",
                        "gate_name": "riscv_snn_experimental_nightly",
                        "gate_version": "1.1",
                        "gate_ok": True,
                        "required_families": ["external_dyn_desc_ref"],
                        "report_path": str(sidecar_path),
                        "observer_summary_path": str(observer_summary_path),
                        "research_report_path": str(research_path),
                        "observer_adequacy_validation_path": str(validation_path),
                        "summary_md_path": str(summary_md_path),
                        "supplementary_surfaces": {
                            "compare": {
                                "surface_kind": "compare_exec_mode_smoke",
                                "blocking": False,
                                "present": True,
                                "load_error": None,
                                "report_path": str(compare_report_path),
                                "summary_md_path": str(compare_refs_dir / "compare-nightly-summary.md"),
                                "current_mainline_status_path": str(compare_refs_dir / "compare-current-status.md"),
                                "gate_ok": True,
                                "latest_date": "2026-04-07",
                                "stale": False,
                                "freshness_mode": "since_latest_recovery",
                                "effective_all_dates_ok": True,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            research_path.write_text(
                json.dumps({"observer_adequacy": {"status": "ready_with_fail_recovery_sample"}}),
                encoding="utf-8",
            )
            validation_path.write_text(
                json.dumps({"status": "pass", "mismatch_count": 0}),
                encoding="utf-8",
            )

            with mock.patch.object(
                riscv_snn_lab,
                "run_research_postprocess",
                return_value={
                    "research_report_path": research_path,
                    "observer_adequacy_validation_path": validation_path,
                },
            ):
                outputs = riscv_snn_lab._refresh_derived_stable_surfaces(
                    sidecar_path=sidecar_path,
                    lab_root=lab_root,
                )

            refreshed_report = json.loads(sidecar_path.read_text(encoding="utf-8"))
            history_exists = Path(outputs["supplementary_surface_history_path"]).exists()
            audit_exists = Path(outputs["stable_surface_refresh_audit_path"]).exists()

        self.assertIn("supplementary_surface_history_path", outputs)
        self.assertIn("stable_surface_refresh_audit_path", outputs)
        self.assertTrue(history_exists)
        self.assertTrue(audit_exists)
        self.assertEqual(
            refreshed_report["supplementary_surface_history_path"],
            str(outputs["supplementary_surface_history_path"]),
        )
        self.assertEqual(
            refreshed_report["stable_surface_refresh_audit_path"],
            str(outputs["stable_surface_refresh_audit_path"]),
        )

    def test_run_family_admission_audit_rebuilds_observer_surfaces_and_records_refresh_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            spec_dir = lab_root / "spec_authority"
            refs_dir.mkdir(parents=True, exist_ok=True)
            spec_dir.mkdir(parents=True, exist_ok=True)

            (spec_dir / "riscv_snn_mainline_gate_v1.json").write_text(
                json.dumps(
                    {
                        "required_families": ["external_dyn_desc_ref"],
                        "optional_groups": {
                            "completion_overflow_optional": {
                                "families": ["completion_queue_overflow_ref"],
                                "blocking": False,
                            }
                        },
                        "promotion_contract": {
                            "completion_overflow_optional": {}
                        },
                    }
                ),
                encoding="utf-8",
            )
            (spec_dir / "riscv_snn_runtime_gate_v1.json").write_text(
                json.dumps(
                    {
                        "reason_ids": ["runtime_bridge_provider_unbound"],
                        "check_ids": [],
                        "checks": {},
                        "families": {},
                    }
                ),
                encoding="utf-8",
            )

            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            observer_summary_path = refs_dir / "nightly-sidecar-observer-summary.json"
            research_path = refs_dir / "riscv-snn-research-report.json"
            validation_path = refs_dir / "observer-adequacy-validation.json"
            current_mainline_path = refs_dir / "current-mainline-status.md"
            summary_md_path = refs_dir / "nightly-sidecar-summary.md"

            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "generated_utc": "2026-04-03T00:00:00+00:00",
                        "gate_name": "riscv_snn_experimental_nightly",
                        "gate_version": "1.1",
                        "gate_ok": True,
                        "required_families": ["external_dyn_desc_ref"],
                        "report_path": str(sidecar_path),
                        "observer_summary_path": str(observer_summary_path),
                        "research_report_path": str(research_path),
                        "observer_adequacy_validation_path": str(validation_path),
                        "summary_md_path": str(summary_md_path),
                    }
                ),
                encoding="utf-8",
            )
            observer_summary_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_sidecar_observer_summary",
                        "authority_entrypoint": {"summary_path": str(sidecar_path)},
                        "optional_group_rollups": {
                            "completion_overflow_optional": {
                                "promotion_ready": False,
                            }
                        },
                        "optional_surfaces": {
                            "full_equivalence": {
                                "entry_count": 1,
                                "history_contract": "observer_sample_sequence_v1",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            research_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "research_metrics_summary",
                        "authority_scope": "research_metrics_only",
                        "observer_adequacy": {"status": "ready_with_fail_recovery_sample"},
                        "observer_entrypoint": {
                            "summary_path": str(observer_summary_path),
                            "artifact_role": "stable_sidecar_observer_summary",
                            "authority_scope": "observer_surface_only",
                        },
                    }
                ),
                encoding="utf-8",
            )
            validation_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "observer_adequacy_validation_summary",
                        "authority_scope": "research_validation_only",
                        "status": "pass",
                        "mismatch_count": 0,
                        "source": {
                            "path": str(research_path),
                            "artifact_role": "research_metrics_summary",
                            "authority_scope": "research_metrics_only",
                        },
                        "observer_entrypoint": {
                            "summary_path": str(observer_summary_path),
                            "artifact_role": "stable_sidecar_observer_summary",
                            "authority_scope": "observer_surface_only",
                        },
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(
                riscv_snn_lab,
                "run_research_postprocess",
                return_value={
                    "research_report_path": research_path,
                    "observer_adequacy_validation_path": validation_path,
                },
            ):
                summary = riscv_snn_lab.run_family_admission_audit(
                    group="completion_overflow_optional",
                    lab_root=lab_root,
                )

            refreshed_observer = json.loads(observer_summary_path.read_text(encoding="utf-8"))
            current_mainline_exists = current_mainline_path.exists()
            summary_md_exists = summary_md_path.exists()

        self.assertEqual(
            summary["refreshed_surfaces"]["observer_summary_path"],
            str(observer_summary_path),
        )
        self.assertEqual(
            summary["refreshed_surfaces"]["current_mainline_status_path"],
            str(current_mainline_path),
        )
        self.assertEqual(
            refreshed_observer["optional_group_rollups"]["completion_overflow_optional"]["promotion_ready"],
            True,
        )
        self.assertEqual(
            refreshed_observer["optional_group_rollups"]["completion_overflow_optional"]["admission_summary_path"],
            summary["summary_path"],
        )
        self.assertTrue(current_mainline_exists)
        self.assertTrue(summary_md_exists)

    def test_audit_stable_surface_refresh_reports_consistent_chain(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            observer_summary_path = refs_dir / "nightly-sidecar-observer-summary.json"
            research_path = refs_dir / "riscv-snn-research-report.json"
            validation_path = refs_dir / "observer-adequacy-validation.json"
            current_mainline_path = refs_dir / "current-mainline-status.md"
            summary_md_path = refs_dir / "nightly-sidecar-summary.md"
            audit_path = refs_dir / "stable-surface-refresh-audit.json"

            observer_summary_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_sidecar_observer_summary",
                        "authority_scope": "observer_surface_only",
                        "authority_entrypoint": {
                            "summary_path": str(sidecar_path),
                            "artifact_role": "stable_top_level_gate",
                            "authority_scope": "experimental_gate_authority",
                        },
                    }
                ),
                encoding="utf-8",
            )
            research_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "research_metrics_summary",
                        "authority_scope": "research_metrics_only",
                        "observer_entrypoint": {
                            "summary_path": str(observer_summary_path),
                            "artifact_role": "stable_sidecar_observer_summary",
                            "authority_scope": "observer_surface_only",
                        },
                    }
                ),
                encoding="utf-8",
            )
            validation_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "observer_adequacy_validation_summary",
                        "authority_scope": "research_validation_only",
                        "source": {
                            "path": str(research_path),
                            "artifact_role": "research_metrics_summary",
                            "authority_scope": "research_metrics_only",
                        },
                        "observer_entrypoint": {
                            "summary_path": str(observer_summary_path),
                            "artifact_role": "stable_sidecar_observer_summary",
                            "authority_scope": "observer_surface_only",
                        },
                    }
                ),
                encoding="utf-8",
            )
            current_mainline_path.write_text(
                "\n".join(
                    [
                        "# riscv_snn current mainline status",
                        f"- stable top-level gate: `{sidecar_path}`",
                        f"- stable observer summary: `{observer_summary_path}`",
                        f"- stable research report: `{research_path}`",
                        f"- stable adequacy validation: `{validation_path}`",
                        f"- stable surface refresh current mainline: `{current_mainline_path}`",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            summary_md_path.write_text(
                f"report_path: {sidecar_path}\nobserver_summary_path: {observer_summary_path}\n",
                encoding="utf-8",
            )
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "generated_utc": "2026-04-03T00:00:00+00:00",
                        "gate_name": "riscv_snn_experimental_nightly",
                        "gate_version": "1.1",
                        "gate_ok": True,
                        "required_families": ["external_dyn_desc_ref"],
                        "report_path": str(sidecar_path),
                        "observer_summary_path": str(observer_summary_path),
                        "research_report_path": str(research_path),
                        "observer_adequacy_validation_path": str(validation_path),
                        "current_mainline_status_path": str(current_mainline_path),
                        "summary_md_path": str(summary_md_path),
                        "supplementary_surface_history_path": str(
                            refs_dir / "supplementary-surface-history.json"
                        ),
                        "stable_surface_refresh_audit_path": str(audit_path),
                        "stable_surface_refresh": {
                            "refreshed_utc": "2026-04-03T12:34:56+00:00",
                            "observer_summary_path": str(observer_summary_path),
                            "research_report_path": str(research_path),
                            "observer_adequacy_validation_path": str(validation_path),
                            "current_mainline_status_path": str(current_mainline_path),
                            "supplementary_surface_history_path": str(
                                refs_dir / "supplementary-surface-history.json"
                            ),
                            "stable_surface_refresh_audit_path": str(audit_path),
                        },
                    }
                ),
                encoding="utf-8",
            )

            summary = riscv_snn_lab.audit_stable_surface_refresh(
                lab_root=lab_root,
                output_path=audit_path,
            )
            audit_exists = audit_path.exists()

        self.assertTrue(summary["all_ok"])
        self.assertEqual(summary["summary_path"], str(audit_path))
        self.assertTrue(audit_exists)
        self.assertTrue(summary["checks"]["observer_summary"]["ok"])
        self.assertTrue(summary["checks"]["research_report"]["ok"])
        self.assertTrue(summary["checks"]["observer_adequacy_validation"]["ok"])
        self.assertTrue(summary["checks"]["current_mainline_status"]["ok"])
        self.assertEqual(summary["current_mainline_status_path"], str(current_mainline_path))
        self.assertEqual(summary["observer_summary_path"], str(observer_summary_path))
        self.assertEqual(summary["summary_md_path"], str(summary_md_path))
        self.assertEqual(summary["refreshed_at_utc"], "2026-04-03T12:34:56+00:00")

    def test_audit_stable_surface_refresh_reports_compare_supplementary_consistency(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            compare_refs_dir = td_path / "sst_dram_si" / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)
            compare_refs_dir.mkdir(parents=True, exist_ok=True)

            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            observer_summary_path = refs_dir / "nightly-sidecar-observer-summary.json"
            research_path = refs_dir / "riscv-snn-research-report.json"
            validation_path = refs_dir / "observer-adequacy-validation.json"
            current_mainline_path = refs_dir / "current-mainline-status.md"
            summary_md_path = refs_dir / "nightly-sidecar-summary.md"
            compare_report_path = compare_refs_dir / "compare-nightly-report.json"
            compare_current_path = compare_refs_dir / "compare-current-status.md"
            compare_summary_path = compare_refs_dir / "compare-nightly-summary.md"

            compare_report_path.write_text(
                json.dumps({"artifact_role": "stable_top_level_gate", "gate_ok": True}),
                encoding="utf-8",
            )
            compare_current_path.write_text("# compare current mainline status\n", encoding="utf-8")
            compare_summary_path.write_text("# compare summary\n", encoding="utf-8")
            observer_summary_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_sidecar_observer_summary",
                        "authority_scope": "observer_surface_only",
                        "authority_entrypoint": {
                            "summary_path": str(sidecar_path),
                            "artifact_role": "stable_top_level_gate",
                            "authority_scope": "experimental_gate_authority",
                        },
                        "supplementary_surfaces": {
                            "compare": {
                                "present": True,
                                "blocking": False,
                                "load_error": None,
                                "report_path": str(compare_report_path),
                                "observer_summary_path": str(compare_refs_dir / "compare-nightly-observer-summary.json"),
                                "current_mainline_status_path": str(compare_current_path),
                                "summary_md_path": str(compare_summary_path),
                                "gate_ok": True,
                                "latest_date": "2026-04-07",
                                "stale": False,
                                "freshness_mode": "since_latest_recovery",
                                "effective_all_dates_ok": True,
                            }
                        },
                        "supplementary_surface_rollups": {
                            "compare": {
                                "status": "pass",
                                "blocking": False,
                                "healthy": True,
                                "freshness_ok": True,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            research_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "research_metrics_summary",
                        "authority_scope": "research_metrics_only",
                        "observer_entrypoint": {
                            "summary_path": str(observer_summary_path),
                            "artifact_role": "stable_sidecar_observer_summary",
                            "authority_scope": "observer_surface_only",
                        },
                    }
                ),
                encoding="utf-8",
            )
            validation_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "observer_adequacy_validation_summary",
                        "authority_scope": "research_validation_only",
                        "source": {
                            "path": str(research_path),
                            "artifact_role": "research_metrics_summary",
                            "authority_scope": "research_metrics_only",
                        },
                        "observer_entrypoint": {
                            "summary_path": str(observer_summary_path),
                            "artifact_role": "stable_sidecar_observer_summary",
                            "authority_scope": "observer_surface_only",
                        },
                    }
                ),
                encoding="utf-8",
            )
            current_mainline_path.write_text(
                "\n".join(
                    [
                        "# riscv_snn current mainline status",
                        f"- stable top-level gate: `{sidecar_path}`",
                        f"- stable observer summary: `{observer_summary_path}`",
                        f"- stable research report: `{research_path}`",
                        f"- stable adequacy validation: `{validation_path}`",
                        f"- `compare.report_path = {compare_report_path}`",
                        f"- `compare.current_mainline_status_path = {compare_current_path}`",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            summary_md_path.write_text(
                "\n".join(
                    [
                        f"report_path: {sidecar_path}",
                        f"observer_summary_path: {observer_summary_path}",
                        f"compare.report_path: {compare_report_path}",
                        f"compare.current_mainline_status_path: {compare_current_path}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "generated_utc": "2026-04-03T00:00:00+00:00",
                        "gate_name": "riscv_snn_experimental_nightly",
                        "gate_version": "1.1",
                        "gate_ok": True,
                        "required_families": ["external_dyn_desc_ref"],
                        "report_path": str(sidecar_path),
                        "observer_summary_path": str(observer_summary_path),
                        "research_report_path": str(research_path),
                        "observer_adequacy_validation_path": str(validation_path),
                        "current_mainline_status_path": str(current_mainline_path),
                        "summary_md_path": str(summary_md_path),
                        "supplementary_surfaces": {
                            "compare": {
                                "present": True,
                                "blocking": False,
                                "load_error": None,
                                "gate_ok": True,
                                "latest_date": "2026-04-07",
                                "stale": False,
                                "freshness_mode": "since_latest_recovery",
                                "effective_all_dates_ok": True,
                                "report_path": str(compare_report_path),
                                "current_mainline_status_path": str(compare_current_path),
                                "summary_md_path": str(compare_summary_path),
                            }
                        },
                        "stable_surface_refresh": {
                            "refreshed_utc": "2026-04-03T12:34:56+00:00",
                            "observer_summary_path": str(observer_summary_path),
                            "research_report_path": str(research_path),
                            "observer_adequacy_validation_path": str(validation_path),
                            "current_mainline_status_path": str(current_mainline_path),
                        },
                    }
                ),
                encoding="utf-8",
            )

            summary = riscv_snn_lab.audit_stable_surface_refresh(
                lab_root=lab_root,
            )

        self.assertTrue(summary["checks"]["supplementary_surfaces.compare"]["ok"])
        self.assertTrue(summary["checks"]["supplementary_surfaces.compare_chain"]["ok"])

    def test_audit_stable_surface_refresh_reports_optional_group_rollup_consistency(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            observer_summary_path = refs_dir / "nightly-sidecar-observer-summary.json"
            research_path = refs_dir / "riscv-snn-research-report.json"
            validation_path = refs_dir / "observer-adequacy-validation.json"
            current_mainline_path = refs_dir / "current-mainline-status.md"
            summary_md_path = refs_dir / "nightly-sidecar-summary.md"
            queue_surface_path = refs_dir / "2026-04-08-equiv-matrix-queue-optional.json"
            supplementary_history_path = refs_dir / "supplementary-surface-history.json"
            audit_path = refs_dir / "stable-surface-refresh-audit.json"

            queue_surface_path.write_text(json.dumps({"all_ok": True}), encoding="utf-8")
            supplementary_history_path.write_text(json.dumps({"surfaces": {}}), encoding="utf-8")
            observer_summary_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_sidecar_observer_summary",
                        "authority_scope": "observer_surface_only",
                        "authority_entrypoint": {
                            "summary_path": str(sidecar_path),
                            "artifact_role": "stable_top_level_gate",
                            "authority_scope": "experimental_gate_authority",
                        },
                        "optional_group_rollups": {
                            "queue_optional": {
                                "summary_path": str(queue_surface_path),
                                "surface": "canonical",
                                "count": 1,
                                "all_ok": True,
                                "freshness_mode": "all_dates",
                                "effective_entry_count": 1,
                                "effective_all_dates_ok": True,
                                "history_path": str(refs_dir / "queue-optional-equivalence-history.json"),
                            }
                        },
                        "optional_surfaces": {
                            "queue_equivalence": {
                                "summary_path": str(queue_surface_path),
                                "surface": "canonical",
                                "count": 1,
                                "all_ok": True,
                                "freshness_mode": "all_dates",
                                "effective_entry_count": 1,
                                "effective_all_dates_ok": True,
                                "history_path": str(refs_dir / "queue-optional-equivalence-history.json"),
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            research_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "research_metrics_summary",
                        "authority_scope": "research_metrics_only",
                        "observer_entrypoint": {
                            "summary_path": str(observer_summary_path),
                            "artifact_role": "stable_sidecar_observer_summary",
                            "authority_scope": "observer_surface_only",
                        },
                    }
                ),
                encoding="utf-8",
            )
            validation_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "observer_adequacy_validation_summary",
                        "authority_scope": "research_validation_only",
                        "source": {
                            "path": str(research_path),
                            "artifact_role": "research_metrics_summary",
                            "authority_scope": "research_metrics_only",
                        },
                        "observer_entrypoint": {
                            "summary_path": str(observer_summary_path),
                            "artifact_role": "stable_sidecar_observer_summary",
                            "authority_scope": "observer_surface_only",
                        },
                    }
                ),
                encoding="utf-8",
            )
            current_mainline_path.write_text(
                "\n".join(
                    [
                        f"- stable top-level gate: `{sidecar_path}`",
                        f"- stable observer summary: `{observer_summary_path}`",
                        f"- stable research report: `{research_path}`",
                        f"- stable adequacy validation: `{validation_path}`",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            summary_md_path.write_text(
                "\n".join(
                    [
                        f"report_path: {sidecar_path}",
                        f"observer_summary_path: {observer_summary_path}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "gate_ok": True,
                        "required_families": ["external_dyn_desc_ref"],
                        "report_path": str(sidecar_path),
                        "observer_summary_path": str(observer_summary_path),
                        "research_report_path": str(research_path),
                        "observer_adequacy_validation_path": str(validation_path),
                        "current_mainline_status_path": str(current_mainline_path),
                        "summary_md_path": str(summary_md_path),
                        "optional_group_surfaces": {
                            "queue_optional": {
                                "summary_path": str(queue_surface_path),
                                "canonical_surface": True,
                                "count": 1,
                                "all_ok": True,
                            }
                        },
                        "stable_surface_refresh": {
                            "observer_summary_path": str(observer_summary_path),
                            "research_report_path": str(research_path),
                            "observer_adequacy_validation_path": str(validation_path),
                            "current_mainline_status_path": str(current_mainline_path),
                            "supplementary_surface_history_path": str(supplementary_history_path),
                            "stable_surface_refresh_audit_path": str(audit_path),
                        },
                        "supplementary_surface_history_path": str(supplementary_history_path),
                        "stable_surface_refresh_audit_path": str(audit_path),
                    }
                ),
                encoding="utf-8",
            )

            summary = riscv_snn_lab.audit_stable_surface_refresh(
                lab_root=lab_root,
            )

        self.assertTrue(summary["checks"]["optional_group_rollups.queue_optional"]["ok"])
        self.assertTrue(summary["checks"]["optional_surfaces.queue_equivalence_chain"]["ok"])

    def test_audit_stable_surface_refresh_flags_optional_group_rollup_missing_freshness_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            observer_summary_path = refs_dir / "nightly-sidecar-observer-summary.json"
            research_path = refs_dir / "riscv-snn-research-report.json"
            validation_path = refs_dir / "observer-adequacy-validation.json"
            current_mainline_path = refs_dir / "current-mainline-status.md"
            summary_md_path = refs_dir / "nightly-sidecar-summary.md"
            queue_surface_path = refs_dir / "2026-04-08-equiv-matrix-queue-optional.json"
            supplementary_history_path = refs_dir / "supplementary-surface-history.json"
            audit_path = refs_dir / "stable-surface-refresh-audit.json"

            queue_surface_path.write_text(json.dumps({"all_ok": True}), encoding="utf-8")
            supplementary_history_path.write_text(json.dumps({"surfaces": {}}), encoding="utf-8")
            observer_summary_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_sidecar_observer_summary",
                        "authority_scope": "observer_surface_only",
                        "authority_entrypoint": {
                            "summary_path": str(sidecar_path),
                            "artifact_role": "stable_top_level_gate",
                            "authority_scope": "experimental_gate_authority",
                        },
                        "optional_group_rollups": {
                            "queue_optional": {
                                "summary_path": str(queue_surface_path),
                                "surface": "canonical",
                                "count": 1,
                                "all_ok": True,
                                "freshness_mode": "all_dates",
                                "effective_entry_count": 1,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            research_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "research_metrics_summary",
                        "authority_scope": "research_metrics_only",
                        "observer_entrypoint": {
                            "summary_path": str(observer_summary_path),
                            "artifact_role": "stable_sidecar_observer_summary",
                            "authority_scope": "observer_surface_only",
                        },
                    }
                ),
                encoding="utf-8",
            )
            validation_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "observer_adequacy_validation_summary",
                        "authority_scope": "research_validation_only",
                        "source": {
                            "path": str(research_path),
                            "artifact_role": "research_metrics_summary",
                            "authority_scope": "research_metrics_only",
                        },
                        "observer_entrypoint": {
                            "summary_path": str(observer_summary_path),
                            "artifact_role": "stable_sidecar_observer_summary",
                            "authority_scope": "observer_surface_only",
                        },
                    }
                ),
                encoding="utf-8",
            )
            current_mainline_path.write_text(
                "\n".join(
                    [
                        f"- stable top-level gate: `{sidecar_path}`",
                        f"- stable observer summary: `{observer_summary_path}`",
                        f"- stable research report: `{research_path}`",
                        f"- stable adequacy validation: `{validation_path}`",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            summary_md_path.write_text(
                "\n".join(
                    [
                        f"report_path: {sidecar_path}",
                        f"observer_summary_path: {observer_summary_path}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "gate_ok": True,
                        "required_families": ["external_dyn_desc_ref"],
                        "report_path": str(sidecar_path),
                        "observer_summary_path": str(observer_summary_path),
                        "research_report_path": str(research_path),
                        "observer_adequacy_validation_path": str(validation_path),
                        "current_mainline_status_path": str(current_mainline_path),
                        "summary_md_path": str(summary_md_path),
                        "optional_group_surfaces": {
                            "queue_optional": {
                                "summary_path": str(queue_surface_path),
                                "canonical_surface": True,
                                "count": 1,
                                "all_ok": True,
                            }
                        },
                        "stable_surface_refresh": {
                            "observer_summary_path": str(observer_summary_path),
                            "research_report_path": str(research_path),
                            "observer_adequacy_validation_path": str(validation_path),
                            "current_mainline_status_path": str(current_mainline_path),
                            "supplementary_surface_history_path": str(supplementary_history_path),
                            "stable_surface_refresh_audit_path": str(audit_path),
                        },
                        "supplementary_surface_history_path": str(supplementary_history_path),
                        "stable_surface_refresh_audit_path": str(audit_path),
                    }
                ),
                encoding="utf-8",
            )

            summary = riscv_snn_lab.audit_stable_surface_refresh(
                lab_root=lab_root,
            )

        self.assertFalse(summary["checks"]["optional_group_rollups.queue_optional"]["ok"])
        self.assertIn(
            "observer_summary.missing_effective_all_dates_ok",
            summary["checks"]["optional_group_rollups.queue_optional"]["issues"],
        )

    def test_audit_stable_surface_refresh_uses_lab_override_for_observer_supplementary_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            spec_dir = lab_root / "spec_authority"
            compare_refs_dir = td_path / "sst_dram_si" / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)
            spec_dir.mkdir(parents=True, exist_ok=True)
            compare_refs_dir.mkdir(parents=True, exist_ok=True)

            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            observer_summary_path = refs_dir / "nightly-sidecar-observer-summary.json"
            research_path = refs_dir / "riscv-snn-research-report.json"
            validation_path = refs_dir / "observer-adequacy-validation.json"
            current_mainline_path = refs_dir / "current-mainline-status.md"
            summary_md_path = refs_dir / "nightly-sidecar-summary.md"
            compare_report_path = compare_refs_dir / "compare-nightly-report.json"
            compare_current_path = compare_refs_dir / "compare-current-status.md"
            compare_summary_path = compare_refs_dir / "compare-nightly-summary.md"

            (spec_dir / "riscv_snn_supplementary_surface_v1.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "contract_name": "riscv_snn_supplementary_surface",
                        "contract_version": "1.0",
                        "history_contract": "supplementary_surface_observer_v1",
                        "surfaces": {
                            "compare": {
                                "surface_kind": "compare_exec_mode_smoke",
                                "blocking": True,
                                "required_surface_fields": [
                                    "surface_kind",
                                    "blocking",
                                    "present",
                                    "report_path",
                                    "summary_md_path",
                                    "current_mainline_status_path",
                                    "gate_ok",
                                    "latest_date",
                                    "stale",
                                    "freshness_mode",
                                    "effective_all_dates_ok",
                                ],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            compare_report_path.write_text(
                json.dumps({"artifact_role": "stable_top_level_gate", "gate_ok": True}),
                encoding="utf-8",
            )
            compare_current_path.write_text("# compare current mainline status\n", encoding="utf-8")
            compare_summary_path.write_text("# compare summary\n", encoding="utf-8")
            observer_summary_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_sidecar_observer_summary",
                        "authority_scope": "observer_surface_only",
                        "authority_entrypoint": {
                            "summary_path": str(sidecar_path),
                            "artifact_role": "stable_top_level_gate",
                            "authority_scope": "experimental_gate_authority",
                        },
                        "supplementary_surfaces": {
                            "compare": {
                                "present": True,
                                "load_error": None,
                                "report_path": str(compare_report_path),
                                "current_mainline_status_path": str(compare_current_path),
                                "summary_md_path": str(compare_summary_path),
                                "gate_ok": True,
                                "latest_date": "2026-04-07",
                                "stale": False,
                                "freshness_mode": "since_latest_recovery",
                                "effective_all_dates_ok": True,
                            }
                        },
                        "supplementary_surface_rollups": {
                            "compare": {
                                "status": "pass",
                                "blocking": True,
                                "healthy": True,
                                "freshness_ok": True,
                                "load_error": None,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            research_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "research_metrics_summary",
                        "authority_scope": "research_metrics_only",
                        "observer_entrypoint": {
                            "summary_path": str(observer_summary_path),
                            "artifact_role": "stable_sidecar_observer_summary",
                            "authority_scope": "observer_surface_only",
                        },
                    }
                ),
                encoding="utf-8",
            )
            validation_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "observer_adequacy_validation_summary",
                        "authority_scope": "research_validation_only",
                        "source": {
                            "path": str(research_path),
                            "artifact_role": "research_metrics_summary",
                            "authority_scope": "research_metrics_only",
                        },
                        "observer_entrypoint": {
                            "summary_path": str(observer_summary_path),
                            "artifact_role": "stable_sidecar_observer_summary",
                            "authority_scope": "observer_surface_only",
                        },
                    }
                ),
                encoding="utf-8",
            )
            current_mainline_path.write_text(
                "\n".join(
                    [
                        "# riscv_snn current mainline status",
                        f"- stable top-level gate: `{sidecar_path}`",
                        f"- stable observer summary: `{observer_summary_path}`",
                        f"- stable research report: `{research_path}`",
                        f"- stable adequacy validation: `{validation_path}`",
                        f"- `compare.report_path = {compare_report_path}`",
                        f"- `compare.current_mainline_status_path = {compare_current_path}`",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            summary_md_path.write_text(
                "\n".join(
                    [
                        f"report_path: {sidecar_path}",
                        f"observer_summary_path: {observer_summary_path}",
                        f"compare.report_path: {compare_report_path}",
                        f"compare.current_mainline_status_path: {compare_current_path}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "generated_utc": "2026-04-03T00:00:00+00:00",
                        "gate_name": "riscv_snn_experimental_nightly",
                        "gate_version": "1.1",
                        "gate_ok": True,
                        "required_families": ["external_dyn_desc_ref"],
                        "report_path": str(sidecar_path),
                        "observer_summary_path": str(observer_summary_path),
                        "research_report_path": str(research_path),
                        "observer_adequacy_validation_path": str(validation_path),
                        "current_mainline_status_path": str(current_mainline_path),
                        "summary_md_path": str(summary_md_path),
                        "supplementary_surfaces": {
                            "compare": {
                                "present": True,
                                "load_error": None,
                                "gate_ok": True,
                                "latest_date": "2026-04-07",
                                "stale": False,
                                "freshness_mode": "since_latest_recovery",
                                "effective_all_dates_ok": True,
                                "report_path": str(compare_report_path),
                                "current_mainline_status_path": str(compare_current_path),
                                "summary_md_path": str(compare_summary_path),
                            }
                        },
                        "stable_surface_refresh": {
                            "refreshed_utc": "2026-04-03T12:34:56+00:00",
                            "observer_summary_path": str(observer_summary_path),
                            "research_report_path": str(research_path),
                            "observer_adequacy_validation_path": str(validation_path),
                            "current_mainline_status_path": str(current_mainline_path),
                        },
                    }
                ),
                encoding="utf-8",
            )

            summary = riscv_snn_lab.audit_stable_surface_refresh(
                lab_root=lab_root,
            )

        self.assertTrue(summary["checks"]["supplementary_surfaces.compare"]["ok"])
        self.assertNotIn(
            "observer_summary.blocking",
            summary["checks"]["supplementary_surfaces.compare"]["issues"],
        )

    def test_audit_stable_surface_refresh_reports_reference_compare_supplementary_consistency(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            observer_summary_path = refs_dir / "nightly-sidecar-observer-summary.json"
            research_path = refs_dir / "riscv-snn-research-report.json"
            validation_path = refs_dir / "observer-adequacy-validation.json"
            current_mainline_path = refs_dir / "current-mainline-status.md"
            summary_md_path = refs_dir / "nightly-sidecar-summary.md"
            reference_compare_report_path = refs_dir / "reference-compare-nightly-report.json"
            reference_compare_current_path = refs_dir / "reference-compare-current-status.md"
            reference_compare_summary_path = refs_dir / "reference-compare-nightly-summary.md"

            reference_compare_report_path.write_text(
                json.dumps({"artifact_role": "reference_compare_surface_report", "gate_ok": True}),
                encoding="utf-8",
            )
            reference_compare_current_path.write_text("# reference compare current mainline status\n", encoding="utf-8")
            reference_compare_summary_path.write_text("# reference compare summary\n", encoding="utf-8")
            observer_summary_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_sidecar_observer_summary",
                        "authority_scope": "observer_surface_only",
                        "authority_entrypoint": {
                            "summary_path": str(sidecar_path),
                            "artifact_role": "stable_top_level_gate",
                            "authority_scope": "experimental_gate_authority",
                        },
                        "supplementary_surfaces": {
                            "reference_compare": {
                                "surface_kind": "reference_compare_surface",
                                "present": True,
                                "blocking": False,
                                "load_error": None,
                                "report_path": str(reference_compare_report_path),
                                "current_mainline_status_path": str(reference_compare_current_path),
                                "summary_md_path": str(reference_compare_summary_path),
                                "gate_ok": True,
                                "latest_date": "2026-04-10",
                                "stale": False,
                                "freshness_mode": "reference_compare_latest_only",
                                "effective_all_dates_ok": True,
                            }
                        },
                        "supplementary_surface_rollups": {
                            "reference_compare": {
                                "status": "pass",
                                "blocking": False,
                                "healthy": True,
                                "freshness_ok": True,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            research_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "research_metrics_summary",
                        "authority_scope": "research_metrics_only",
                        "observer_entrypoint": {
                            "summary_path": str(observer_summary_path),
                            "artifact_role": "stable_sidecar_observer_summary",
                            "authority_scope": "observer_surface_only",
                        },
                    }
                ),
                encoding="utf-8",
            )
            validation_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "observer_adequacy_validation_summary",
                        "authority_scope": "research_validation_only",
                        "source": {
                            "path": str(research_path),
                            "artifact_role": "research_metrics_summary",
                            "authority_scope": "research_metrics_only",
                        },
                        "observer_entrypoint": {
                            "summary_path": str(observer_summary_path),
                            "artifact_role": "stable_sidecar_observer_summary",
                            "authority_scope": "observer_surface_only",
                        },
                    }
                ),
                encoding="utf-8",
            )
            current_mainline_path.write_text(
                "\n".join(
                    [
                        "# riscv_snn current mainline status",
                        f"- stable top-level gate: `{sidecar_path}`",
                        f"- stable observer summary: `{observer_summary_path}`",
                        f"- stable research report: `{research_path}`",
                        f"- stable adequacy validation: `{validation_path}`",
                        f"- `reference_compare.report_path = {reference_compare_report_path}`",
                        f"- `reference_compare.current_mainline_status_path = {reference_compare_current_path}`",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            summary_md_path.write_text(
                "\n".join(
                    [
                        f"report_path: {sidecar_path}",
                        f"observer_summary_path: {observer_summary_path}",
                        str(reference_compare_report_path),
                        str(reference_compare_current_path),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "generated_utc": "2026-04-10T00:00:00+00:00",
                        "gate_name": "riscv_snn_experimental_nightly",
                        "gate_version": "1.1",
                        "gate_ok": True,
                        "required_families": ["external_dyn_desc_ref"],
                        "report_path": str(sidecar_path),
                        "observer_summary_path": str(observer_summary_path),
                        "research_report_path": str(research_path),
                        "observer_adequacy_validation_path": str(validation_path),
                        "current_mainline_status_path": str(current_mainline_path),
                        "summary_md_path": str(summary_md_path),
                        "supplementary_surfaces": {
                            "reference_compare": {
                                "surface_kind": "reference_compare_surface",
                                "present": True,
                                "blocking": False,
                                "load_error": None,
                                "report_path": str(reference_compare_report_path),
                                "current_mainline_status_path": str(reference_compare_current_path),
                                "summary_md_path": str(reference_compare_summary_path),
                                "gate_ok": True,
                                "latest_date": "2026-04-10",
                                "stale": False,
                                "freshness_mode": "reference_compare_latest_only",
                                "effective_all_dates_ok": True,
                            }
                        },
                        "stable_surface_refresh": {
                            "refreshed_utc": "2026-04-10T12:34:56+00:00",
                            "observer_summary_path": str(observer_summary_path),
                            "research_report_path": str(research_path),
                            "observer_adequacy_validation_path": str(validation_path),
                            "current_mainline_status_path": str(current_mainline_path),
                        },
                    }
                ),
                encoding="utf-8",
            )

            summary = riscv_snn_lab.audit_stable_surface_refresh(
                lab_root=lab_root,
            )

        self.assertTrue(summary["checks"]["supplementary_surfaces.reference_compare"]["ok"])
        self.assertTrue(summary["checks"]["supplementary_surfaces.reference_compare_chain"]["ok"])

    def test_audit_stable_surface_refresh_reports_compare_supplementary_degraded(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            observer_summary_path = refs_dir / "nightly-sidecar-observer-summary.json"
            research_path = refs_dir / "riscv-snn-research-report.json"
            validation_path = refs_dir / "observer-adequacy-validation.json"
            current_mainline_path = refs_dir / "current-mainline-status.md"
            summary_md_path = refs_dir / "nightly-sidecar-summary.md"

            observer_summary_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_sidecar_observer_summary",
                        "authority_scope": "observer_surface_only",
                        "authority_entrypoint": {
                            "summary_path": str(sidecar_path),
                            "artifact_role": "stable_top_level_gate",
                            "authority_scope": "experimental_gate_authority",
                        },
                    }
                ),
                encoding="utf-8",
            )
            research_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "research_metrics_summary",
                        "authority_scope": "research_metrics_only",
                        "observer_entrypoint": {
                            "summary_path": str(observer_summary_path),
                            "artifact_role": "stable_sidecar_observer_summary",
                            "authority_scope": "observer_surface_only",
                        },
                    }
                ),
                encoding="utf-8",
            )
            validation_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "observer_adequacy_validation_summary",
                        "authority_scope": "research_validation_only",
                        "source": {
                            "path": str(research_path),
                            "artifact_role": "research_metrics_summary",
                            "authority_scope": "research_metrics_only",
                        },
                        "observer_entrypoint": {
                            "summary_path": str(observer_summary_path),
                            "artifact_role": "stable_sidecar_observer_summary",
                            "authority_scope": "observer_surface_only",
                        },
                    }
                ),
                encoding="utf-8",
            )
            current_mainline_path.write_text("# current mainline\n", encoding="utf-8")
            summary_md_path.write_text("# sidecar summary\n", encoding="utf-8")
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "generated_utc": "2026-04-03T00:00:00+00:00",
                        "gate_name": "riscv_snn_experimental_nightly",
                        "gate_version": "1.1",
                        "gate_ok": True,
                        "required_families": ["external_dyn_desc_ref"],
                        "report_path": str(sidecar_path),
                        "observer_summary_path": str(observer_summary_path),
                        "research_report_path": str(research_path),
                        "observer_adequacy_validation_path": str(validation_path),
                        "current_mainline_status_path": str(current_mainline_path),
                        "summary_md_path": str(summary_md_path),
                        "supplementary_surfaces": {
                            "compare": {
                                "present": True,
                                "blocking": False,
                                "load_error": "compare report unreadable",
                                "gate_ok": None,
                                "stale": True,
                                "freshness_mode": "since_latest_recovery",
                                "effective_all_dates_ok": False,
                                "report_path": str(refs_dir / "missing-compare-report.json"),
                                "current_mainline_status_path": str(refs_dir / "missing-compare-current-status.md"),
                                "summary_md_path": str(refs_dir / "missing-compare-summary.md"),
                            }
                        },
                        "stable_surface_refresh": {
                            "refreshed_utc": "2026-04-03T12:34:56+00:00",
                            "observer_summary_path": str(observer_summary_path),
                            "research_report_path": str(research_path),
                            "observer_adequacy_validation_path": str(validation_path),
                            "current_mainline_status_path": str(current_mainline_path),
                        },
                    }
                ),
                encoding="utf-8",
            )

            summary = riscv_snn_lab.audit_stable_surface_refresh(
                lab_root=lab_root,
            )

        self.assertFalse(summary["checks"]["supplementary_surfaces.compare"]["ok"])
        self.assertFalse(summary["all_ok"])

    def test_audit_stable_surface_refresh_flags_compare_contract_violation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            compare_refs_dir = td_path / "sst_dram_si" / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)
            compare_refs_dir.mkdir(parents=True, exist_ok=True)

            sidecar_path = refs_dir / "nightly-sidecar-report.json"
            observer_summary_path = refs_dir / "nightly-sidecar-observer-summary.json"
            research_path = refs_dir / "riscv-snn-research-report.json"
            validation_path = refs_dir / "observer-adequacy-validation.json"
            current_mainline_path = refs_dir / "current-mainline-status.md"
            summary_md_path = refs_dir / "nightly-sidecar-summary.md"
            compare_report_path = compare_refs_dir / "compare-nightly-report.json"
            compare_current_path = compare_refs_dir / "compare-current-status.md"
            compare_summary_path = compare_refs_dir / "compare-nightly-summary.md"

            compare_report_path.write_text(
                json.dumps({"artifact_role": "stable_top_level_gate", "gate_ok": True}),
                encoding="utf-8",
            )
            compare_current_path.write_text("# compare current\n", encoding="utf-8")
            compare_summary_path.write_text("# compare summary\n", encoding="utf-8")

            observer_summary_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_sidecar_observer_summary",
                        "authority_scope": "observer_surface_only",
                        "authority_entrypoint": {
                            "summary_path": str(sidecar_path),
                            "artifact_role": "stable_top_level_gate",
                            "authority_scope": "experimental_gate_authority",
                        },
                        "supplementary_surfaces": {
                            "compare": {
                                "surface_kind": "wrong_compare_kind",
                                "blocking": False,
                                "present": True,
                                "load_error": None,
                                "report_path": str(compare_report_path),
                                "summary_md_path": str(compare_summary_path),
                                "current_mainline_status_path": str(compare_current_path),
                                "gate_ok": True,
                                "latest_date": "2026-04-07",
                                "stale": False,
                                "freshness_mode": "since_latest_recovery",
                                "effective_all_dates_ok": True,
                            }
                        },
                        "supplementary_surface_rollups": {
                            "compare": {
                                "status": "pass",
                                "blocking": False,
                                "healthy": True,
                                "freshness_ok": True,
                                "load_error": None,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            research_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "research_metrics_summary",
                        "authority_scope": "research_metrics_only",
                        "observer_entrypoint": {
                            "summary_path": str(observer_summary_path),
                            "artifact_role": "stable_sidecar_observer_summary",
                            "authority_scope": "observer_surface_only",
                        },
                    }
                ),
                encoding="utf-8",
            )
            validation_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "observer_adequacy_validation_summary",
                        "authority_scope": "research_validation_only",
                        "source": {
                            "path": str(research_path),
                            "artifact_role": "research_metrics_summary",
                            "authority_scope": "research_metrics_only",
                        },
                        "observer_entrypoint": {
                            "summary_path": str(observer_summary_path),
                            "artifact_role": "stable_sidecar_observer_summary",
                            "authority_scope": "observer_surface_only",
                        },
                    }
                ),
                encoding="utf-8",
            )
            current_mainline_path.write_text(
                "\n".join(
                    [
                        f"- stable top-level gate: `{sidecar_path}`",
                        f"- stable observer summary: `{observer_summary_path}`",
                        f"- stable research report: `{research_path}`",
                        f"- stable adequacy validation: `{validation_path}`",
                        f"- `compare.report_path = {compare_report_path}`",
                        f"- `compare.current_mainline_status_path = {compare_current_path}`",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            summary_md_path.write_text(
                "\n".join(
                    [
                        f"report_path: {sidecar_path}",
                        f"observer_summary_path: {observer_summary_path}",
                        f"compare.report_path: {compare_report_path}",
                        f"compare.current_mainline_status_path: {compare_current_path}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            sidecar_path.write_text(
                json.dumps(
                    {
                        "artifact_role": "stable_top_level_gate",
                        "authority_scope": "experimental_gate_authority",
                        "generated_utc": "2026-04-03T00:00:00+00:00",
                        "gate_name": "riscv_snn_experimental_nightly",
                        "gate_version": "1.1",
                        "gate_ok": True,
                        "required_families": ["external_dyn_desc_ref"],
                        "report_path": str(sidecar_path),
                        "observer_summary_path": str(observer_summary_path),
                        "research_report_path": str(research_path),
                        "observer_adequacy_validation_path": str(validation_path),
                        "current_mainline_status_path": str(current_mainline_path),
                        "summary_md_path": str(summary_md_path),
                        "supplementary_surfaces": {
                            "compare": {
                                "surface_kind": "wrong_compare_kind",
                                "blocking": False,
                                "present": True,
                                "load_error": None,
                                "report_path": str(compare_report_path),
                                "summary_md_path": str(compare_summary_path),
                                "current_mainline_status_path": str(compare_current_path),
                                "gate_ok": True,
                                "latest_date": "2026-04-07",
                                "stale": False,
                                "freshness_mode": "since_latest_recovery",
                                "effective_all_dates_ok": True,
                            }
                        },
                        "stable_surface_refresh": {
                            "refreshed_utc": "2026-04-03T12:34:56+00:00",
                            "observer_summary_path": str(observer_summary_path),
                            "research_report_path": str(research_path),
                            "observer_adequacy_validation_path": str(validation_path),
                            "current_mainline_status_path": str(current_mainline_path),
                            "supplementary_surface_history_path": str(refs_dir / "supplementary-surface-history.json"),
                            "stable_surface_refresh_audit_path": str(refs_dir / "stable-surface-refresh-audit.json"),
                        },
                        "supplementary_surface_history_path": str(refs_dir / "supplementary-surface-history.json"),
                        "stable_surface_refresh_audit_path": str(refs_dir / "stable-surface-refresh-audit.json"),
                    }
                ),
                encoding="utf-8",
            )

            summary = riscv_snn_lab.audit_stable_surface_refresh(
                lab_root=lab_root,
            )

        self.assertFalse(summary["checks"]["supplementary_surfaces.compare"]["ok"])
        self.assertIn(
            "contract.surface_kind",
            summary["checks"]["supplementary_surfaces.compare"]["issues"],
        )

    def test_audit_family_assets_reports_ok_for_toolchain_family(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            specs_dir = lab_root / "specs"
            firmware_dir = lab_root / "firmware"
            toolchain_dir = lab_root / "firmware_src" / "barrier_wfi_order_ref_toolchain"
            spec_authority_dir = lab_root / "spec_authority"
            refs_dir.mkdir(parents=True, exist_ok=True)
            specs_dir.mkdir(parents=True, exist_ok=True)
            firmware_dir.mkdir(parents=True, exist_ok=True)
            toolchain_dir.mkdir(parents=True, exist_ok=True)
            spec_authority_dir.mkdir(parents=True, exist_ok=True)

            (spec_authority_dir / "riscv_snn_runtime_gate_v1.json").write_text(
                json.dumps(
                    {
                        "families": {
                            "barrier_wfi_order_ref": {
                                "fault_mode": "quiescent",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            (specs_dir / "barrier_wfi_order_ref_snn_baseline.json").write_text(
                json.dumps(
                    {
                        "workload": {
                            "impl": "snn",
                            "params": {},
                        }
                    }
                ),
                encoding="utf-8",
            )
            runtime_bridge_spec_path = specs_dir / "barrier_wfi_order_ref_runtime_bridge.json"
            runtime_bridge_spec_path.write_text(
                json.dumps(
                    {
                        "workload": {
                            "impl": "riscv_snn",
                            "params": {
                                "backend_name": "runtime_bridge",
                                "firmware_elf": str(firmware_dir / "barrier_wfi_order_ref_toolchain.elf"),
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            (firmware_dir / "barrier_wfi_order_ref_toolchain.elf").write_text("elf", encoding="utf-8")
            for name in ("Makefile", "main.S", "abi.inc"):
                (toolchain_dir / name).write_text("x", encoding="utf-8")

            with mock.patch.dict(
                riscv_snn_lab.EQUIV_FAMILY_SPECS,
                {
                    "barrier_wfi_order_ref": {
                        "snn_baseline": "barrier_wfi_order_ref_snn_baseline.json",
                        "runtime_bridge": "barrier_wfi_order_ref_runtime_bridge.json",
                    }
                },
                clear=True,
            ):
                with mock.patch.object(
                    riscv_snn_lab,
                    "_load_program_manifest",
                    return_value={"samples": {"barrier_wfi_order_ref": {"canonical_sample": False}}},
                ):
                    summary = riscv_snn_lab.audit_family_assets(
                        family="barrier_wfi_order_ref",
                        lab_root=lab_root,
                        output_path=refs_dir / "family-asset-audit.json",
                    )

        self.assertTrue(summary["all_ok"])
        self.assertEqual(len(summary["families"]), 1)
        row = summary["families"][0]
        self.assertEqual(row["family"], "barrier_wfi_order_ref")
        self.assertTrue(row["builder_sample_exists"])
        self.assertTrue(row["runtime_gate_authority_present"])
        self.assertTrue(row["toolchain_source_exists"])
        self.assertEqual(row["issues"], [])

    def test_audit_family_assets_reports_missing_builder_sample(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            specs_dir = lab_root / "specs"
            firmware_dir = lab_root / "firmware"
            spec_authority_dir = lab_root / "spec_authority"
            refs_dir.mkdir(parents=True, exist_ok=True)
            specs_dir.mkdir(parents=True, exist_ok=True)
            firmware_dir.mkdir(parents=True, exist_ok=True)
            spec_authority_dir.mkdir(parents=True, exist_ok=True)

            (spec_authority_dir / "riscv_snn_runtime_gate_v1.json").write_text(
                json.dumps({"families": {"queue_backpressure_ref": {}}}),
                encoding="utf-8",
            )
            (specs_dir / "queue_backpressure_ref_snn_baseline.json").write_text(
                json.dumps({"workload": {"impl": "snn", "params": {}}}),
                encoding="utf-8",
            )
            (specs_dir / "queue_backpressure_ref_runtime_bridge.json").write_text(
                json.dumps(
                    {
                        "workload": {
                            "impl": "riscv_snn",
                            "params": {
                                "backend_name": "runtime_bridge",
                                "firmware_elf": str(firmware_dir / "queue_backpressure_ref.elf"),
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            (firmware_dir / "queue_backpressure_ref.elf").write_text("elf", encoding="utf-8")

            with mock.patch.dict(
                riscv_snn_lab.EQUIV_FAMILY_SPECS,
                {
                    "queue_backpressure_ref": {
                        "snn_baseline": "queue_backpressure_ref_snn_baseline.json",
                        "runtime_bridge": "queue_backpressure_ref_runtime_bridge.json",
                    }
                },
                clear=True,
            ):
                with mock.patch.object(
                    riscv_snn_lab,
                    "_load_program_manifest",
                    return_value={"samples": {}},
                ):
                    summary = riscv_snn_lab.audit_family_assets(
                        family="queue_backpressure_ref",
                        lab_root=lab_root,
                        output_path=refs_dir / "family-asset-audit.json",
                    )

        self.assertFalse(summary["all_ok"])
        row = summary["families"][0]
        self.assertIn("builder_sample_missing", row["issues"])

    def test_run_family_lane_writes_variant_specs_and_invokes_subset_equivalence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            specs_dir = lab_root / "specs"
            firmware_dir = lab_root / "firmware"
            specs_dir.mkdir(parents=True, exist_ok=True)
            firmware_dir.mkdir(parents=True, exist_ok=True)

            (specs_dir / "barrier_wfi_order_ref_snn_baseline.json").write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "platform": {
                            "mesh_size": 4,
                            "stop": {"simulation_time": "1us"},
                        },
                        "workload": {"impl": "snn", "params": {}},
                    }
                ),
                encoding="utf-8",
            )
            (specs_dir / "barrier_wfi_order_ref_runtime_bridge.json").write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "platform": {
                            "mesh_size": 4,
                            "stop": {"simulation_time": "1us"},
                        },
                        "workload": {
                            "impl": "riscv_snn",
                            "params": {
                                "hart_isa": "rv64im_zicsr",
                                "local_mem_bytes": 65536,
                                "cmd_queue_entries": 64,
                                "cmp_queue_entries": 64,
                                "rx_debug_queue_entries": 16,
                                "boot_addr": 0,
                                "backend_name": "runtime_bridge",
                                "firmware_elf": str(firmware_dir / "barrier_wfi_order_ref_toolchain.elf"),
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            (firmware_dir / "barrier_wfi_order_ref_toolchain.elf").write_text("elf", encoding="utf-8")
            expected_output_path = lab_root / "references" / "family-lane-summary.json"

            with mock.patch.dict(
                riscv_snn_lab.EQUIV_FAMILY_SPECS,
                {
                    "barrier_wfi_order_ref": {
                        "snn_baseline": "barrier_wfi_order_ref_snn_baseline.json",
                        "runtime_bridge": "barrier_wfi_order_ref_runtime_bridge.json",
                    }
                },
                clear=True,
            ):
                with mock.patch.object(
                    riscv_snn_lab,
                    "_run_equivalence_from_specs",
                    return_value={
                        "summary_path": str(expected_output_path),
                        "status": "PASS",
                    },
                ) as run_equiv:
                    summary = riscv_snn_lab.run_family_lane(
                        family="barrier_wfi_order_ref",
                        sim_time="2us",
                        cmd_queue_entries=2,
                        cmp_queue_entries=1,
                        summary_path=expected_output_path,
                        lab_root=lab_root,
                    )

            called_baseline_spec = Path(run_equiv.call_args.kwargs["baseline_spec"])
            called_runtime_spec = Path(run_equiv.call_args.kwargs["runtime_bridge_spec"])
            metadata = run_equiv.call_args.kwargs["summary_metadata"]
            baseline_payload = json.loads(called_baseline_spec.read_text(encoding="utf-8"))
            runtime_payload = json.loads(called_runtime_spec.read_text(encoding="utf-8"))

        self.assertEqual(summary["summary_path"], str(expected_output_path))
        self.assertIn("/family_lanes/barrier_wfi_order_ref/", str(called_baseline_spec))
        self.assertFalse(metadata["canonical_surface"])
        self.assertEqual(metadata["lane_overrides"]["sim_time"], "2us")
        self.assertEqual(metadata["lane_overrides"]["cmd_queue_entries"], 2)
        self.assertEqual(
            baseline_payload["platform"]["stop"]["simulation_time"],
            "2us",
        )
        self.assertEqual(
            runtime_payload["workload"]["params"]["cmd_queue_entries"],
            2,
        )
        self.assertEqual(
            runtime_payload["workload"]["params"]["cmp_queue_entries"],
            1,
        )

    def test_run_family_lane_requires_at_least_one_override(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            specs_dir = lab_root / "specs"
            specs_dir.mkdir(parents=True, exist_ok=True)
            (specs_dir / "barrier_wfi_order_ref_snn_baseline.json").write_text(
                json.dumps({"workload": {"impl": "snn", "params": {}}}),
                encoding="utf-8",
            )
            (specs_dir / "barrier_wfi_order_ref_runtime_bridge.json").write_text(
                json.dumps(
                    {
                        "workload": {
                            "impl": "riscv_snn",
                            "params": {
                                "backend_name": "runtime_bridge",
                                "firmware_elf": "/tmp/fw.elf",
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.dict(
                riscv_snn_lab.EQUIV_FAMILY_SPECS,
                {
                    "barrier_wfi_order_ref": {
                        "snn_baseline": "barrier_wfi_order_ref_snn_baseline.json",
                        "runtime_bridge": "barrier_wfi_order_ref_runtime_bridge.json",
                    }
                },
                clear=True,
            ):
                with self.assertRaises(ValueError):
                    riscv_snn_lab.run_family_lane(
                        family="barrier_wfi_order_ref",
                        lab_root=lab_root,
                    )

    def test_run_family_lane_applies_queue_backpressure_capacity_relief_preset(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            specs_dir = lab_root / "specs"
            refs_dir = lab_root / "references"
            specs_dir.mkdir(parents=True, exist_ok=True)
            refs_dir.mkdir(parents=True, exist_ok=True)
            baseline = specs_dir / "queue_backpressure_ref_snn_baseline.json"
            runtime = specs_dir / "queue_backpressure_ref_runtime_bridge.json"
            baseline.write_text(json.dumps({"workload": {"impl": "snn"}}), encoding="utf-8")
            runtime.write_text(
                json.dumps(
                    {
                        "workload": {
                            "impl": "riscv_snn",
                            "params": {"backend_name": "runtime_bridge"},
                        }
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.dict(
                riscv_snn_lab.EQUIV_FAMILY_SPECS,
                {
                    "queue_backpressure_ref": {
                        "snn_baseline": "queue_backpressure_ref_snn_baseline.json",
                        "runtime_bridge": "queue_backpressure_ref_runtime_bridge.json",
                    }
                },
                clear=True,
            ), mock.patch.dict(
                riscv_snn_lab.FAMILY_LANE_PRESETS,
                {
                    "queue_backpressure_capacity_relief": {
                        "family": "queue_backpressure_ref",
                        "overrides": {"local_mem_bytes": 131072},
                    }
                },
                clear=True,
            ):
                with mock.patch.object(
                    riscv_snn_lab,
                    "_run_equivalence_with_spec_paths",
                    return_value={"summary_path": str(refs_dir / "preset.json"), "status": "PASS"},
                ) as run_equiv:
                    summary = riscv_snn_lab.run_family_lane(
                        preset="queue_backpressure_capacity_relief",
                        lab_root=lab_root,
                    )

        self.assertEqual(summary["preset"], "queue_backpressure_capacity_relief")
        metadata = run_equiv.call_args.kwargs["summary_metadata"]
        self.assertEqual(metadata["preset"], "queue_backpressure_capacity_relief")
        self.assertEqual(
            metadata["lane_overrides"]["local_mem_bytes"],
            131072,
        )

    def test_run_family_lane_rejects_conflicting_family_and_preset(self) -> None:
        with self.assertRaises(ValueError):
            riscv_snn_lab.run_family_lane(
                family="queue_backpressure_ref",
                preset="queue_backpressure_capacity_relief",
            )

    def test_run_family_lane_matrix_writes_subset_summary_and_invokes_family_lanes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            def _fake_lane_summary(family: str) -> dict[str, object]:
                lane_id = f"lane-{family}"
                summary_path = refs_dir / f"{family}-lane.json"
                return {
                    "family": family,
                    "status": "PASS",
                    "summary_path": str(summary_path),
                    "lane_id": lane_id,
                    "lane_root": str(lab_root / "family_lanes" / family / lane_id),
                    "lane_overrides": {
                        "cmd_queue_entries": 2,
                        "cmp_queue_entries": 1,
                    },
                    "gate_reasons": [],
                    "runtime_bridge": {
                        "build_preflight_rollup": {
                            "enabled": True,
                            "status": "ok",
                            "required_action": "none",
                            "lineage_status": "ok",
                            "contract_key": "riscv_snn.runtime_bridge.runtime_consumers",
                            "contract_version": 1,
                            "full_rebuild_required": False,
                        }
                    },
                }

            expected_output = refs_dir / "family-lane-matrix.json"
            with mock.patch.object(
                riscv_snn_lab,
                "run_family_lane",
                side_effect=[
                    _fake_lane_summary("external_dyn_desc_fault_ref"),
                    _fake_lane_summary("queue_backpressure_ref"),
                ],
            ) as run_family_lane:
                summary = riscv_snn_lab.run_family_lane_matrix(
                    families=["external_dyn_desc_fault_ref", "queue_backpressure_ref"],
                    cmd_queue_entries=2,
                    cmp_queue_entries=1,
                    summary_path=expected_output,
                    lab_root=lab_root,
                )

        self.assertEqual(summary["summary_path"], str(expected_output))
        self.assertFalse(summary["canonical_surface"])
        self.assertTrue(summary["all_ok"])
        self.assertEqual(
            summary["requested_families"],
            ["external_dyn_desc_fault_ref", "queue_backpressure_ref"],
        )
        self.assertEqual(
            summary["lane_overrides"],
            {
                "cmd_queue_entries": 2,
                "cmp_queue_entries": 1,
            },
        )
        self.assertEqual(len(summary["families"]), 2)
        self.assertEqual(
            [row["family"] for row in summary["families"]],
            ["external_dyn_desc_fault_ref", "queue_backpressure_ref"],
        )
        self.assertEqual(run_family_lane.call_count, 2)
        self.assertEqual(run_family_lane.call_args_list[0].kwargs["family"], "external_dyn_desc_fault_ref")
        self.assertEqual(run_family_lane.call_args_list[1].kwargs["family"], "queue_backpressure_ref")
        self.assertEqual(run_family_lane.call_args_list[0].kwargs["cmd_queue_entries"], 2)
        self.assertEqual(run_family_lane.call_args_list[0].kwargs["cmp_queue_entries"], 1)

    def test_run_family_lane_matrix_requires_explicit_family(self) -> None:
        with self.assertRaises(ValueError):
            riscv_snn_lab.run_family_lane_matrix(
                families=[],
                cmd_queue_entries=2,
                cmp_queue_entries=1,
            )

    def test_run_family_lane_matrix_requires_at_least_one_override(self) -> None:
        with self.assertRaises(ValueError):
            riscv_snn_lab.run_family_lane_matrix(
                families=["external_dyn_desc_fault_ref", "queue_backpressure_ref"],
            )

    def test_run_family_lane_matrix_applies_cmpq_fault_rearm_default_preset(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lab_root = Path(td) / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            def _fake_lane_summary(family: str) -> dict[str, object]:
                return {
                    "family": family,
                    "status": "PASS",
                    "summary_path": str(refs_dir / f"{family}-lane.json"),
                    "lane_id": f"lane-{family}",
                    "lane_overrides": {"cmp_queue_entries": 1},
                    "gate_reasons": [],
                }

            with mock.patch.dict(
                riscv_snn_lab.FAMILY_LANE_MATRIX_PRESETS,
                {
                    "cmpq_fault_rearm_default": {
                        "families": [
                            "external_dyn_desc_fault_ref",
                            "external_dyn_desc_fault_rearm_ref",
                            "completion_queue_overflow_ref",
                        ],
                        "overrides": {"cmp_queue_entries": 1},
                    }
                },
                clear=True,
            ), mock.patch.object(
                riscv_snn_lab,
                "run_family_lane",
                side_effect=[
                    _fake_lane_summary("external_dyn_desc_fault_ref"),
                    _fake_lane_summary("external_dyn_desc_fault_rearm_ref"),
                    _fake_lane_summary("completion_queue_overflow_ref"),
                ],
            ) as run_family_lane:
                with mock.patch.object(riscv_snn_lab, "_write_json", autospec=True):
                    summary = riscv_snn_lab.run_family_lane_matrix(
                        preset="cmpq_fault_rearm_default",
                        lab_root=lab_root,
                    )

        self.assertEqual(summary["preset"], "cmpq_fault_rearm_default")
        self.assertEqual(summary["lane_overrides"]["cmp_queue_entries"], 1)
        self.assertEqual(
            [row["family"] for row in summary["families"]],
            [
                "external_dyn_desc_fault_ref",
                "external_dyn_desc_fault_rearm_ref",
                "completion_queue_overflow_ref",
            ],
        )
        self.assertEqual(run_family_lane.call_count, 3)
        self.assertEqual(
            run_family_lane.call_args_list[0].kwargs["cmp_queue_entries"],
            1,
        )
        self.assertEqual(
            run_family_lane.call_args_list[1].kwargs["cmp_queue_entries"],
            1,
        )
        self.assertEqual(
            run_family_lane.call_args_list[2].kwargs["cmp_queue_entries"],
            1,
        )
        self.assertEqual(run_family_lane.call_args_list[0].kwargs["cmp_queue_entries"], 1)
        self.assertEqual(run_family_lane.call_args_list[1].kwargs["cmp_queue_entries"], 1)
        self.assertEqual(run_family_lane.call_args_list[2].kwargs["cmp_queue_entries"], 1)

    def test_run_family_lane_matrix_rejects_preset_and_family_mix(self) -> None:
        with self.assertRaises(ValueError):
            riscv_snn_lab.run_family_lane_matrix(
                families=["external_dyn_desc_fault_ref"],
                preset="cmpq_fault_rearm_default",
            )

    def test_build_history_index_default_output_path_uses_lab_root(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            refs_dir = td_path / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)
            index_path = refs_dir / "2026-03-28-nightly-index.json"
            index_path.write_text(
                json.dumps(
                    {
                        "generated_utc": "2026-03-28T00:00:00+00:00",
                        "count": 1,
                        "all_ok": True,
                        "families": [],
                    }
                ),
                encoding="utf-8",
            )

            history = riscv_snn_lab.build_history_index([index_path], lab_root=td_path)

            self.assertEqual(history["summary_path"], str(refs_dir / "nightly-history-index.json"))
            self.assertTrue((refs_dir / "nightly-history-index.json").exists())

    def test_fault_and_bad_policy_toolchain_bridge_assets_exist(self) -> None:
        for program in (
            "external_dyn_desc_fault_ref_toolchain",
            "external_dyn_desc_bad_policy_ref_toolchain",
            "external_dyn_desc_fault_rearm_ref_toolchain",
            "external_dyn_desc_fault_overwrite_chain_ref_toolchain",
        ):
            self.assertTrue(riscv_snn_lab.toolchain_source_dir(program).exists(), msg=program)
            self.assertTrue(riscv_snn_lab.default_spec_path(program).exists(), msg=program)
            self.assertEqual(riscv_snn_lab._sample_role(program, None), "toolchain bridge")
            self.assertIn("bare-metal toolchain", riscv_snn_lab._sample_target(program, None))

    def test_barrier_toolchain_bridge_assets_exist(self) -> None:
        program = "barrier_wfi_order_ref_toolchain"
        toolchain_dir = riscv_snn_lab.toolchain_source_dir(program)
        self.assertTrue(toolchain_dir.exists(), msg=program)
        self.assertTrue((toolchain_dir / "main.S").exists(), msg=program)
        self.assertTrue((toolchain_dir / "Makefile").exists(), msg=program)
        self.assertTrue((toolchain_dir / "crt0.S").exists(), msg=program)
        self.assertTrue((toolchain_dir / "linker.ld").exists(), msg=program)
        self.assertTrue((toolchain_dir / "abi.inc").exists(), msg=program)
        self.assertTrue(riscv_snn_lab.default_spec_path(program).exists(), msg=program)
        self.assertEqual(riscv_snn_lab._sample_role(program, None), "toolchain bridge")
        self.assertIn("bare-metal toolchain", riscv_snn_lab._sample_target(program, None))

    def test_barrier_toolchain_source_includes_generated_abi_surface(self) -> None:
        program = "barrier_wfi_order_ref_toolchain"
        toolchain_dir = riscv_snn_lab.toolchain_source_dir(program)
        content = (toolchain_dir / "main.S").read_text(encoding="utf-8")
        self.assertIn('.include "abi.inc"', content)
        self.assertNotIn(".set CSR_MSNN_CMDQ_BASE", content)

    def test_queue_backpressure_toolchain_bridge_assets_exist(self) -> None:
        program = "queue_backpressure_ref_toolchain"
        toolchain_dir = riscv_snn_lab.toolchain_source_dir(program)
        self.assertTrue(toolchain_dir.exists(), msg=program)
        self.assertTrue((toolchain_dir / "main.S").exists(), msg=program)
        self.assertTrue((toolchain_dir / "Makefile").exists(), msg=program)
        self.assertTrue((toolchain_dir / "crt0.S").exists(), msg=program)
        self.assertTrue((toolchain_dir / "linker.ld").exists(), msg=program)
        self.assertTrue((toolchain_dir / "abi.inc").exists(), msg=program)
        self.assertTrue(riscv_snn_lab.default_spec_path(program).exists(), msg=program)
        self.assertEqual(riscv_snn_lab._sample_role(program, None), "toolchain bridge")
        self.assertIn("bare-metal toolchain", riscv_snn_lab._sample_target(program, None))

    def test_queue_backpressure_toolchain_source_includes_generated_abi_surface(self) -> None:
        program = "queue_backpressure_ref_toolchain"
        toolchain_dir = riscv_snn_lab.toolchain_source_dir(program)
        content = (toolchain_dir / "main.S").read_text(encoding="utf-8")
        self.assertIn('.include "abi.inc"', content)
        self.assertNotIn(".set CSR_MSNN_CMDQ_BASE", content)
        self.assertIn("addi x21, x0, 2", content)
        self.assertIn("csrrw x0, CSR_MSNN_CMDQ_TAIL, x21", content)

    def test_completion_queue_overflow_toolchain_bridge_assets_exist(self) -> None:
        program = "completion_queue_overflow_ref_toolchain"
        toolchain_dir = riscv_snn_lab.toolchain_source_dir(program)
        self.assertTrue(toolchain_dir.exists(), msg=program)
        self.assertTrue((toolchain_dir / "main.S").exists(), msg=program)
        self.assertTrue((toolchain_dir / "Makefile").exists(), msg=program)
        self.assertTrue((toolchain_dir / "crt0.S").exists(), msg=program)
        self.assertTrue((toolchain_dir / "linker.ld").exists(), msg=program)
        self.assertTrue((toolchain_dir / "abi.inc").exists(), msg=program)
        self.assertTrue(riscv_snn_lab.default_spec_path(program).exists(), msg=program)
        self.assertEqual(riscv_snn_lab._sample_role(program, None), "toolchain bridge")
        self.assertIn("bare-metal toolchain", riscv_snn_lab._sample_target(program, None))

    def test_completion_queue_overflow_toolchain_source_includes_generated_abi_surface(self) -> None:
        program = "completion_queue_overflow_ref_toolchain"
        toolchain_dir = riscv_snn_lab.toolchain_source_dir(program)
        content = (toolchain_dir / "main.S").read_text(encoding="utf-8")
        self.assertIn('.include "abi.inc"', content)
        self.assertNotIn(".set CSR_MSNN_CMDQ_BASE", content)
        self.assertIn("addi x22, x0, 2", content)
        self.assertIn("csrrw x0, CSR_MSNN_CMDQ_TAIL, x22", content)
        self.assertEqual(content.count("wfi"), 2)
        self.assertIn("csrrwi x0, CSR_MSNN_EVENT_PENDING, 7", content)

    def test_fault_toolchain_sources_do_not_keep_known_stale_constants(self) -> None:
        stale_fault_constants = (
            "0x0000000000000210",
            "0x0000000400000110",
            "0x0000000000000110",
        )
        for program in (
            "external_dyn_desc_fault_ref_toolchain",
            "external_dyn_desc_fault_rearm_ref_toolchain",
        ):
            content = (
                riscv_snn_lab.toolchain_source_dir(program) / "main.S"
            ).read_text(encoding="utf-8")
            for stale in stale_fault_constants:
                self.assertNotIn(stale, content, msg=f"{program} still contains stale constant {stale}")

        bad_policy_content = (
            riscv_snn_lab.toolchain_source_dir("external_dyn_desc_bad_policy_ref_toolchain") / "main.S"
        ).read_text(encoding="utf-8")
        for stale in (
            "0x0000000000000211",
            "0x0000400000000111",
            "0x0000000000000111",
        ):
            self.assertNotIn(
                stale,
                bad_policy_content,
                msg=f"external_dyn_desc_bad_policy_ref_toolchain still contains stale constant {stale}",
            )

    def test_fault_lifecycle_toolchain_sources_keep_explicit_clear_points(self) -> None:
        rearm_content = (
            riscv_snn_lab.toolchain_source_dir("external_dyn_desc_fault_rearm_ref_toolchain") / "main.S"
        ).read_text(encoding="utf-8")
        overwrite_content = (
            riscv_snn_lab.toolchain_source_dir("external_dyn_desc_fault_overwrite_chain_ref_toolchain") / "main.S"
        ).read_text(encoding="utf-8")

        self.assertEqual(rearm_content.count("csrrw x0, CSR_MSNN_FAULT, x0"), 1)
        self.assertEqual(overwrite_content.count("csrrw x0, CSR_MSNN_FAULT, x0"), 2)
        self.assertGreaterEqual(rearm_content.count("csrrwi x0, CSR_MSNN_EVENT_PENDING, 7"), 2)
        self.assertGreaterEqual(overwrite_content.count("csrrwi x0, CSR_MSNN_EVENT_PENDING, 7"), 3)
        self.assertIn("ld x17, 56(x10)", rearm_content)
        self.assertIn("ld x17, 96(x10)", overwrite_content)

    def test_default_equiv_summary_path_is_dated_reference(self) -> None:
        path = riscv_snn_lab.default_equiv_summary_path("external_dyn_desc_ref")
        self.assertTrue(path.name.endswith("-external-dyn-desc-ref-equiv.json"))
        self.assertIn("/references/", str(path))

    def test_run_equiv_matrix_default_summary_path_for_all_group(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            def fake_run_equivalence(family: str, **_: Any) -> dict[str, Any]:
                return {
                    "family": family,
                    "status": "PASS",
                    "summary_path": str(refs_dir / f"{family}.json"),
                    "gate_reasons": [],
                }

            with mock.patch.object(riscv_snn_lab, "run_equivalence", side_effect=fake_run_equivalence):
                summary = riscv_snn_lab.run_equiv_matrix(
                    families=None,
                    group="all",
                    lab_root=lab_root,
                )

            resolved_path = Path(summary["summary_path"])
            self.assertTrue(resolved_path.exists())
            self.assertTrue(resolved_path.name.endswith("-equiv-matrix.json"))
            self.assertTrue(summary["canonical_surface"])

    def test_run_equiv_matrix_default_summary_path_for_non_all_group(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            side_effect = [
                {
                    "family": "queue_backpressure_ref",
                    "status": "PASS",
                    "summary_path": str(refs_dir / "queue-backpressure-ref-equiv.json"),
                    "gate_reasons": [],
                },
                {
                    "family": "completion_queue_overflow_ref",
                    "status": "PASS",
                    "summary_path": str(refs_dir / "completion-queue-overflow-ref-equiv.json"),
                    "gate_reasons": [],
                },
            ]
            with mock.patch.object(riscv_snn_lab, "run_equivalence", side_effect=side_effect):
                summary = riscv_snn_lab.run_equiv_matrix(
                    families=None,
                    group="queue_optional",
                    lab_root=lab_root,
                )

            resolved_path = Path(summary["summary_path"])
            self.assertTrue(resolved_path.exists())
            self.assertTrue(resolved_path.name.endswith("-equiv-matrix-queue-optional.json"))
            self.assertEqual(summary["requested_group"], "queue_optional")

    def test_run_equiv_matrix_explicit_subset_avoids_canonical_all_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            with mock.patch.object(
                riscv_snn_lab,
                "run_equivalence",
                return_value={
                    "family": "external_dyn_desc_ref",
                    "status": "PASS",
                    "summary_path": str(refs_dir / "external-dyn-desc-ref-equiv.json"),
                    "gate_reasons": [],
                },
            ):
                summary = riscv_snn_lab.run_equiv_matrix(
                    families=["external_dyn_desc_ref"],
                    group="all",
                    lab_root=lab_root,
                )

            resolved_path = Path(summary["summary_path"])
            self.assertTrue(resolved_path.exists())
            self.assertIn("-equiv-matrix-subset-", resolved_path.name)
            self.assertEqual(summary["requested_group"], "all")

    def test_run_equiv_matrix_writes_family_summary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            summary_path = refs_dir / "equiv-matrix.json"
            side_effect = [
                {
                    "family": "external_dyn_desc_ref",
                    "status": "PASS",
                    "summary_path": str(refs_dir / "external_dyn_desc_ref-equiv.json"),
                    "gate_reasons": [],
                },
                {
                    "family": "external_dyn_desc_fault_ref",
                    "status": "WARN",
                    "summary_path": str(refs_dir / "external_dyn_desc_fault_ref-equiv.json"),
                    "gate_reasons": ["trend_visibility_gap:snn_tx.spike_packets_total"],
                },
            ]
            with mock.patch.object(riscv_snn_lab, "run_equivalence", side_effect=side_effect) as run_equivalence:
                summary = riscv_snn_lab.run_equiv_matrix(
                    families=[
                        "external_dyn_desc_ref",
                        "external_dyn_desc_fault_ref",
                    ],
                    group="all",
                    summary_path=summary_path,
                    lab_root=lab_root,
                )

            self.assertEqual(summary["schema_version"], 2)
            self.assertEqual(summary["artifact_role"], "dated_equivalence_matrix")
            self.assertEqual(summary["authority_scope"], "family_level_equivalence_authority")
            self.assertEqual(summary["producer"], "riscv_snn_lab.run_equiv_matrix")
            self.assertEqual(summary["gate_name"], "riscv_snn_equiv_matrix")
            self.assertEqual(summary["requested_group"], "all")
            self.assertEqual(summary["count"], 2)
            self.assertFalse(summary["all_ok"])
            self.assertEqual(summary["families"][0]["family"], "external_dyn_desc_ref")
            self.assertEqual(summary["families"][0]["status"], "PASS")
            self.assertEqual(summary["families"][1]["status"], "WARN")
            self.assertEqual(
                summary["families"][1]["gate_reasons"],
                ["trend_visibility_gap:snn_tx.spike_packets_total"],
            )
            self.assertEqual(run_equivalence.call_count, 2)
            self.assertTrue(summary_path.exists())
            persisted = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["gate_name"], "riscv_snn_equiv_matrix")
            self.assertEqual(len(persisted["families"]), 2)

    def test_run_equiv_matrix_rolls_up_runtime_bridge_build_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)
            summary_path = refs_dir / "equiv-matrix.json"

            def side_effect(family: str, **_: Any) -> dict[str, Any]:
                status = "ok" if family == "external_dyn_desc_ref" else "ok"
                required_action = "none" if family == "external_dyn_desc_ref" else "full_clean_rebuild"
                lineage_status = "ok" if family == "external_dyn_desc_ref" else "fingerprint_mismatch"
                fingerprint_match = family == "external_dyn_desc_ref"
                return {
                    "family": family,
                    "status": "PASS",
                    "summary_path": str(refs_dir / f"{family}.json"),
                    "gate_reasons": [],
                    "runtime_bridge": {
                        "build_preflight_rollup": {
                            "enabled": True,
                            "reporting_scope": "research_only_nonblocking",
                            "status": status,
                            "required_action": required_action,
                            "lineage_status": lineage_status,
                            "contract_key": "riscv_snn.runtime_bridge.runtime_consumers",
                            "contract_version": 1,
                            "dependency_count": 2,
                            "required_target_count": 9,
                            "stale_target_count": 0,
                            "missing_target_count": 0,
                            "fingerprint_match": fingerprint_match,
                            "full_rebuild_required": not fingerprint_match,
                        }
                    },
                }

            with mock.patch.object(riscv_snn_lab, "run_equivalence", side_effect=side_effect):
                summary = riscv_snn_lab.run_equiv_matrix(
                    families=["external_dyn_desc_ref", "external_dyn_desc_fault_ref"],
                    group="all",
                    summary_path=summary_path,
                    lab_root=lab_root,
                )

        rollup = summary["runtime_bridge_build_preflight_rollup"]
        self.assertTrue(rollup["enabled"])
        self.assertEqual(rollup["reporting_scope"], "research_only_nonblocking")
        self.assertTrue(rollup["all_ok"])
        self.assertEqual(rollup["family_count"], 2)
        self.assertEqual(rollup["status_counts"], {"ok": 2})
        self.assertEqual(rollup["required_action_counts"], {"full_clean_rebuild": 1, "none": 1})
        self.assertEqual(rollup["lineage_status_counts"], {"fingerprint_mismatch": 1, "ok": 1})
        self.assertEqual(rollup["contract_keys"], ["riscv_snn.runtime_bridge.runtime_consumers"])
        self.assertEqual(rollup["contract_versions"], [1])
        self.assertEqual(rollup["full_rebuild_required_family_count"], 1)
        self.assertEqual(rollup["fingerprint_mismatch_family_count"], 1)

    def test_main_equiv_matrix_accepts_group_all(self) -> None:
        expected_summary = {
            "summary_path": "/tmp/equiv-matrix-all.json",
            "all_ok": True,
        }
        with mock.patch.object(riscv_snn_lab, "run_equiv_matrix", return_value=expected_summary) as run_equiv_matrix:
            with mock.patch("builtins.print") as print_mock:
                rc = riscv_snn_lab.main(["equiv-matrix", "--group", "all"])

        self.assertEqual(rc, 0)
        run_equiv_matrix.assert_called_once_with(
            families=None,
            group="all",
            summary_path=None,
        )
        print_mock.assert_called_once_with("/tmp/equiv-matrix-all.json")

    def test_main_equiv_matrix_accepts_group_queue_optional(self) -> None:
        expected_summary = {
            "summary_path": "/tmp/equiv-matrix-queue-optional.json",
            "all_ok": True,
        }
        with mock.patch.object(riscv_snn_lab, "run_equiv_matrix", return_value=expected_summary) as run_equiv_matrix:
            with mock.patch("builtins.print") as print_mock:
                rc = riscv_snn_lab.main(["equiv-matrix", "--group", "queue_optional"])

        self.assertEqual(rc, 0)
        run_equiv_matrix.assert_called_once_with(
            families=None,
            group="queue_optional",
            summary_path=None,
        )
        print_mock.assert_called_once_with("/tmp/equiv-matrix-queue-optional.json")

    def test_main_equiv_matrix_accepts_group_completion_overflow_optional(self) -> None:
        expected_summary = {
            "summary_path": "/tmp/equiv-matrix-completion-overflow-optional.json",
            "all_ok": True,
        }
        with mock.patch.object(riscv_snn_lab, "run_equiv_matrix", return_value=expected_summary) as run_equiv_matrix:
            with mock.patch("builtins.print") as print_mock:
                rc = riscv_snn_lab.main(["equiv-matrix", "--group", "completion_overflow_optional"])

        self.assertEqual(rc, 0)
        run_equiv_matrix.assert_called_once_with(
            families=None,
            group="completion_overflow_optional",
            summary_path=None,
        )
        print_mock.assert_called_once_with("/tmp/equiv-matrix-completion-overflow-optional.json")

    def test_main_equiv_matrix_accepts_explicit_family(self) -> None:
        expected_summary = {
            "summary_path": "/tmp/equiv-matrix-family.json",
            "all_ok": False,
        }
        with mock.patch.object(riscv_snn_lab, "run_equiv_matrix", return_value=expected_summary) as run_equiv_matrix:
            with mock.patch("builtins.print") as print_mock:
                rc = riscv_snn_lab.main(["equiv-matrix", "--family", "external_dyn_desc_fault_ref"])

        self.assertEqual(rc, 2)
        run_equiv_matrix.assert_called_once_with(
            families=["external_dyn_desc_fault_ref"],
            group="all",
            summary_path=None,
        )
        print_mock.assert_called_once_with("/tmp/equiv-matrix-family.json")

    def test_main_equiv_matrix_explicit_family_overrides_group_selection(self) -> None:
        expected_summary = {
            "summary_path": "/tmp/equiv-matrix-family-override.json",
            "all_ok": True,
        }
        with mock.patch.object(riscv_snn_lab, "run_equiv_matrix", return_value=expected_summary) as run_equiv_matrix:
            with mock.patch("builtins.print") as print_mock:
                rc = riscv_snn_lab.main(
                    ["equiv-matrix", "--group", "queue_optional", "--family", "external_dyn_desc_ref"]
                )

        self.assertEqual(rc, 0)
        run_equiv_matrix.assert_called_once_with(
            families=["external_dyn_desc_ref"],
            group="queue_optional",
            summary_path=None,
        )
        print_mock.assert_called_once_with("/tmp/equiv-matrix-family-override.json")

    def test_resolve_equiv_families_queue_optional_group(self) -> None:
        authority = riscv_snn_lab.load_mainline_gate_authority()
        self.assertEqual(
            riscv_snn_lab._resolve_equiv_families(None, group="queue_optional"),
            authority["optional_groups"]["queue_optional"]["families"],
        )

    def test_run_equiv_matrix_queue_optional_group_uses_frozen_family_subset(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            refs_dir = lab_root / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)

            summary_path = refs_dir / "equiv-matrix-queue-optional.json"
            side_effect = [
                {
                    "family": "queue_backpressure_ref",
                    "status": "PASS",
                    "summary_path": str(refs_dir / "queue_backpressure_ref-equiv.json"),
                    "gate_reasons": [],
                },
                {
                    "family": "completion_queue_overflow_ref",
                    "status": "PASS",
                    "summary_path": str(refs_dir / "completion_queue_overflow_ref-equiv.json"),
                    "gate_reasons": [],
                },
            ]

            with mock.patch.object(riscv_snn_lab, "run_equivalence", side_effect=side_effect) as run_equivalence:
                summary = riscv_snn_lab.run_equiv_matrix(
                    families=None,
                    group="queue_optional",
                    summary_path=summary_path,
                    lab_root=lab_root,
                )

        self.assertTrue(summary["all_ok"])
        self.assertEqual(summary["count"], 2)
        self.assertEqual(summary["requested_group"], "queue_optional")
        self.assertEqual(
            summary["requested_families"],
            ["queue_backpressure_ref", "completion_queue_overflow_ref"],
        )
        self.assertEqual(run_equivalence.call_count, 2)

    def test_equiv_family_surface_freezes_fault_lifecycle_pairs(self) -> None:
        expected = {
            "external_dyn_desc_ref": {
                "snn_baseline": "external_dyn_desc_ref_snn_baseline.json",
                "runtime_bridge": "external_dyn_desc_ref_runtime_bridge.json",
            },
            "external_dyn_desc_fault_ref": {
                "snn_baseline": "external_dyn_desc_fault_ref_snn_baseline.json",
                "runtime_bridge": "external_dyn_desc_fault_ref_runtime_bridge.json",
            },
            "external_dyn_desc_bad_policy_ref": {
                "snn_baseline": "external_dyn_desc_bad_policy_ref_snn_baseline.json",
                "runtime_bridge": "external_dyn_desc_bad_policy_ref_runtime_bridge.json",
            },
            "external_dyn_desc_fault_rearm_ref": {
                "snn_baseline": "external_dyn_desc_fault_rearm_ref_snn_baseline.json",
                "runtime_bridge": "external_dyn_desc_fault_rearm_ref_runtime_bridge.json",
            },
            "external_dyn_desc_fault_overwrite_chain_ref": {
                "snn_baseline": "external_dyn_desc_fault_overwrite_chain_ref_snn_baseline.json",
                "runtime_bridge": "external_dyn_desc_fault_overwrite_chain_ref_runtime_bridge.json",
            },
            "barrier_wfi_order_ref": {
                "snn_baseline": "barrier_wfi_order_ref_snn_baseline.json",
                "runtime_bridge": "barrier_wfi_order_ref_runtime_bridge.json",
            },
            "queue_backpressure_ref": {
                "snn_baseline": "queue_backpressure_ref_snn_baseline.json",
                "runtime_bridge": "queue_backpressure_ref_runtime_bridge.json",
            },
            "completion_queue_overflow_ref": {
                "snn_baseline": "completion_queue_overflow_ref_snn_baseline.json",
                "runtime_bridge": "completion_queue_overflow_ref_runtime_bridge.json",
            },
        }

        self.assertEqual(riscv_snn_lab.EQUIV_FAMILY_SPECS, expected)
        for pair in expected.values():
            for relpath in pair.values():
                self.assertTrue((riscv_snn_lab.LAB_ROOT / "specs" / relpath).exists(), msg=relpath)

    def test_equiv_family_policies_freeze_fault_expectations(self) -> None:
        self.assertEqual(
            riscv_snn_lab.EQUIV_FAMILY_POLICIES["external_dyn_desc_ref"]["fault_mode"],
            "quiescent",
        )
        self.assertEqual(
            riscv_snn_lab.EQUIV_FAMILY_POLICIES["external_dyn_desc_fault_ref"]["fault_mode"],
            "accepted_fault_required",
        )
        self.assertEqual(
            riscv_snn_lab.EQUIV_FAMILY_POLICIES["external_dyn_desc_bad_policy_ref"]["progress_mode"],
            "no_committed_progress_allowed",
        )
        self.assertEqual(
            riscv_snn_lab.EQUIV_FAMILY_POLICIES["external_dyn_desc_fault_rearm_ref"]["fault_lifecycle_mode"],
            "clear_then_refault",
        )
        self.assertEqual(
            riscv_snn_lab.EQUIV_FAMILY_POLICIES["external_dyn_desc_fault_overwrite_chain_ref"]["fault_lifecycle_mode"],
            "overwrite_chain",
        )
        self.assertEqual(
            riscv_snn_lab.EQUIV_FAMILY_POLICIES["queue_backpressure_ref"]["queue_mode"],
            "command_overdoorbell_overflow",
        )
        self.assertEqual(
            riscv_snn_lab.EQUIV_FAMILY_POLICIES["completion_queue_overflow_ref"]["queue_mode"],
            "completion_queue_overflow_after_visible_completion",
        )

    def test_equiv_validation_waiver_surface_covers_current_snn_baselines(self) -> None:
        expected = {
            ("external_dyn_desc_ref", "snn_baseline"),
            ("external_dyn_desc_fault_ref", "snn_baseline"),
            ("external_dyn_desc_bad_policy_ref", "snn_baseline"),
            ("external_dyn_desc_fault_rearm_ref", "snn_baseline"),
            ("external_dyn_desc_fault_overwrite_chain_ref", "snn_baseline"),
            ("barrier_wfi_order_ref", "snn_baseline"),
            ("queue_backpressure_ref", "snn_baseline"),
            ("completion_queue_overflow_ref", "snn_baseline"),
        }
        self.assertTrue(expected.issubset(set(riscv_snn_lab.EQUIV_VALIDATION_FAIL_WAIVERS)))
        for key in expected:
            waiver = riscv_snn_lab.EQUIV_VALIDATION_FAIL_WAIVERS[key]
            self.assertEqual(
                waiver["allowed_fail_checks"],
                ["step_activation.invocations_vs_windows"],
            )

    def test_shipped_equiv_specs_keep_workload_boundaries(self) -> None:
        baseline = json.loads(
            (riscv_snn_lab.LAB_ROOT / "specs" / "external_dyn_desc_ref_snn_baseline.json").read_text(
                encoding="utf-8"
            )
        )
        runtime_bridge = json.loads(
            (riscv_snn_lab.LAB_ROOT / "specs" / "external_dyn_desc_ref_runtime_bridge.json").read_text(
                encoding="utf-8"
            )
        )

        baseline_params = dict(baseline.get("workload", {}).get("params", {}) or {})
        runtime_params = dict(runtime_bridge.get("workload", {}).get("params", {}) or {})
        baseline_stop = dict(baseline.get("platform", {}).get("stop", {}) or {})
        runtime_stop = dict(runtime_bridge.get("platform", {}).get("stop", {}) or {})

        self.assertEqual(baseline.get("workload", {}).get("impl"), "snn")
        self.assertEqual(baseline_params, {})
        self.assertEqual(baseline_stop.get("mode"), "time")
        self.assertEqual(baseline_stop.get("simulation_time"), "1us")
        self.assertEqual(runtime_bridge.get("workload", {}).get("impl"), "riscv_snn")
        self.assertEqual(runtime_params.get("backend_name"), "runtime_bridge")
        self.assertEqual(runtime_stop.get("mode"), "time")
        self.assertEqual(runtime_stop.get("simulation_time"), "1us")

    def test_runtime_regression_sample_specs_bind_runtime_bridge_backend(self) -> None:
        for program in (
            *riscv_snn_lab.PROGRAM_GROUPS["builder"],
            *riscv_snn_lab.PROGRAM_GROUPS["toolchain"],
        ):
            payload = json.loads(riscv_snn_lab.default_spec_path(program).read_text(encoding="utf-8"))
            self.assertEqual(payload.get("workload", {}).get("impl"), "riscv_snn")
            self.assertEqual(
                payload.get("workload", {}).get("params", {}).get("backend_name"),
                "runtime_bridge",
                msg=program,
            )

    def test_generate_spec_defaults_to_runtime_bridge_backend(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            spec_path = td_path / "generated-spec.json"
            elf_path = td_path / "firmware.elf"
            elf_path.write_bytes(b"\x7fELF")

            generate_riscv_snn_firmware._write_spec(
                spec_path,
                elf_path=elf_path,
                sim_time="1us",
                mesh_size=4,
                local_mem_bytes=64 * 1024,
                cmd_queue_entries=64,
                cmp_queue_entries=64,
                rx_debug_queue_entries=16,
                boot_addr=0,
                hart_isa="rv64im_zicsr",
            )

            payload = json.loads(spec_path.read_text(encoding="utf-8"))
            self.assertEqual(
                payload.get("workload", {}).get("params", {}).get("backend_name"),
                "runtime_bridge",
            )

    def test_run_equivalence_runs_fixed_pair_and_writes_summary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            specs_dir = lab_root / "specs"
            refs_dir = lab_root / "references"
            specs_dir.mkdir(parents=True)
            refs_dir.mkdir(parents=True)

            baseline_spec = specs_dir / "external_dyn_desc_ref_snn_baseline.json"
            runtime_bridge_spec = specs_dir / "external_dyn_desc_ref_runtime_bridge.json"
            baseline_payload = {
                "schema_version": 3,
                "platform": {"mesh_size": 4, "exec_mode": "gas", "stop": {"simulation_time": "1us"}},
                "workload": {"impl": "snn", "params": {}},
                "control": {"global_step_sync_enable": False},
            }
            runtime_bridge_payload = {
                "schema_version": 3,
                "platform": {"mesh_size": 4, "exec_mode": "gas", "stop": {"simulation_time": "1us"}},
                "workload": {"impl": "riscv_snn", "params": {"backend_name": "runtime_bridge"}},
                "control": {"global_step_sync_enable": False},
            }
            baseline_spec.write_text(json.dumps(baseline_payload), encoding="utf-8")
            runtime_bridge_spec.write_text(json.dumps(runtime_bridge_payload), encoding="utf-8")

            def write_run_dir(run_dir: Path, spec_payload: dict[str, object], *, runtime_stats: dict[str, float]) -> None:
                (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
                (run_dir / "meta.json").write_text(
                    json.dumps(
                        {
                            "run": {
                                "run_id": run_dir.name,
                                "created_utc": "2026-03-25T00:00:00+00:00",
                                "hostname": "node1",
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                (run_dir / "inputs" / "spec.json").write_text(json.dumps(spec_payload), encoding="utf-8")
                (run_dir / "essential_summary_mesh.json").write_text(
                    json.dumps(
                        {
                            "schema_version": 2,
                            "model": {"exec_mode": "gas", "mesh_size": 4},
                            "contracts": {
                                "gas_semantic_ready_before_commit": True,
                                "gas_semantic_drain_before_scatter": True,
                            },
                            "memory": {"memory_requests": 10.0, "memory_bytes": 640.0},
                            "gas": {"windows": 2, "windows_done": 2},
                            "step": {"global_steps_done": 1},
                            "snn_tx": {"spike_packets_total": 4.0},
                            "snn_rx": {"spike_packets_total": 4.0},
                        }
                    ),
                    encoding="utf-8",
                )
                (run_dir / "validation.log").write_text(
                    "[val] SUMMARY run_dir=/tmp/fake-run fail=0 warn=0 strict=0\n",
                    encoding="utf-8",
                )
                with (run_dir / "mesh_stats.csv").open("w", encoding="utf-8") as handle:
                    handle.write(
                        "ComponentName,StatisticName,StatisticSubId,StatisticType,SimTime,Rank,Sum.u64,SumSQ.u64,Count.u64,Min.u64,Max.u64,Sum.f64,SumSQ.f64,Min.f64,Max.f64\n"
                    )
                    for name, value in runtime_stats.items():
                        handle.write(
                            f"core0,{name},0,Accumulator,0 ns,0,{int(value)},0,1,{int(value)},{int(value)},0,0,0,0\n"
                        )

            baseline_run = td_path / "baseline-run"
            bridge_run = td_path / "runtime-bridge-run"
            write_run_dir(baseline_run, baseline_payload, runtime_stats={})
            write_run_dir(
                bridge_run,
                runtime_bridge_payload,
                runtime_stats={
                    "riscv_snn_backend_runtime_bridge_provider_bound": 1.0,
                    "riscv_snn_fused_step_completion_count": 1.0,
                    "riscv_snn_completion_visible_count": 1.0,
                    "riscv_snn_completion_consumed_count": 1.0,
                    "riscv_snn_fault_count": 0.0,
                    "riscv_snn_last_completion_status": 0.0,
                    "riscv_snn_last_fault_csr": 0.0,
                },
            )

            class EquivRunner(FakeRunner):
                def __init__(self) -> None:
                    super().__init__()
                    self.run_dirs = [baseline_run, bridge_run]

                def __call__(self, cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
                    self.calls.append((cmd, cwd))
                    if any(str(part).endswith("run_mesh_with_time.sh") for part in cmd):
                        run_dir = self.run_dirs.pop(0)
                        return subprocess.CompletedProcess(
                            cmd,
                            0,
                            stdout=f"[mesh] run complete: {run_dir}\n",
                            stderr="",
                        )
                    return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")

            runner = EquivRunner()
            summary = riscv_snn_lab.run_equivalence(
                "external_dyn_desc_ref",
                lab_root=lab_root,
                runner=runner,
            )

            self.assertEqual(summary["status"], "PASS")
            self.assertEqual(summary["baseline"]["workload_impl"], "snn")
            self.assertEqual(summary["runtime_bridge"]["workload_impl"], "riscv_snn")
            self.assertEqual(
                summary["runtime_bridge"]["runtime_stats"]["riscv_snn_fused_step_completion_count"],
                1.0,
            )
            self.assertEqual(
                summary["runtime_bridge"]["runtime_stats"]["riscv_snn_completion_consumed_count"],
                1.0,
            )
            self.assertTrue(summary["compare"]["strict"][0]["match"])
            self.assertEqual(len(runner.calls), 4)
            self.assertTrue(Path(summary["summary_path"]).exists())

    def test_run_equivalence_records_runtime_bridge_build_preflight_as_research_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            specs_dir = lab_root / "specs"
            refs_dir = lab_root / "references"
            specs_dir.mkdir(parents=True)
            refs_dir.mkdir(parents=True)

            baseline_spec = specs_dir / "external_dyn_desc_ref_snn_baseline.json"
            runtime_bridge_spec = specs_dir / "external_dyn_desc_ref_runtime_bridge.json"
            baseline_payload = {
                "schema_version": 3,
                "platform": {"mesh_size": 4, "exec_mode": "gas", "stop": {"simulation_time": "1us"}},
                "workload": {"impl": "snn", "params": {}},
                "control": {"global_step_sync_enable": False},
            }
            runtime_bridge_payload = {
                "schema_version": 3,
                "platform": {"mesh_size": 4, "exec_mode": "gas", "stop": {"simulation_time": "1us"}},
                "workload": {"impl": "riscv_snn", "params": {"backend_name": "runtime_bridge"}},
                "control": {"global_step_sync_enable": False},
            }
            baseline_spec.write_text(json.dumps(baseline_payload), encoding="utf-8")
            runtime_bridge_spec.write_text(json.dumps(runtime_bridge_payload), encoding="utf-8")

            def write_run_dir(run_dir: Path, spec_payload: dict[str, object], *, runtime_stats: dict[str, float]) -> None:
                (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
                (run_dir / "meta.json").write_text(
                    json.dumps(
                        {
                            "run": {
                                "run_id": run_dir.name,
                                "created_utc": "2026-03-25T00:00:00+00:00",
                                "hostname": "node1",
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                (run_dir / "inputs" / "spec.json").write_text(json.dumps(spec_payload), encoding="utf-8")
                (run_dir / "essential_summary_mesh.json").write_text(
                    json.dumps(
                        {
                            "schema_version": 2,
                            "model": {"exec_mode": "gas", "mesh_size": 4},
                            "contracts": {
                                "gas_semantic_ready_before_commit": True,
                                "gas_semantic_drain_before_scatter": True,
                            },
                            "memory": {"memory_requests": 10.0, "memory_bytes": 640.0},
                            "gas": {"windows": 2, "windows_done": 2},
                            "step": {"global_steps_done": 1},
                            "snn_tx": {"spike_packets_total": 4.0},
                            "snn_rx": {"spike_packets_total": 4.0},
                        }
                    ),
                    encoding="utf-8",
                )
                (run_dir / "validation.log").write_text(
                    "[val] SUMMARY run_dir=/tmp/fake-run fail=0 warn=0 strict=0\n",
                    encoding="utf-8",
                )
                with (run_dir / "mesh_stats.csv").open("w", encoding="utf-8") as handle:
                    handle.write(
                        "ComponentName,StatisticName,StatisticSubId,StatisticType,SimTime,Rank,Sum.u64,SumSQ.u64,Count.u64,Min.u64,Max.u64,Sum.f64,SumSQ.f64,Min.f64,Max.f64\n"
                    )
                    for name, value in runtime_stats.items():
                        handle.write(
                            f"core0,{name},0,Accumulator,0 ns,0,{int(value)},0,1,{int(value)},{int(value)},0,0,0,0\n"
                        )

            baseline_run = td_path / "baseline-run"
            bridge_run = td_path / "runtime-bridge-run"
            write_run_dir(baseline_run, baseline_payload, runtime_stats={})
            write_run_dir(
                bridge_run,
                runtime_bridge_payload,
                runtime_stats={
                    "riscv_snn_backend_runtime_bridge_provider_bound": 1.0,
                    "riscv_snn_fused_step_completion_count": 1.0,
                    "riscv_snn_completion_visible_count": 1.0,
                    "riscv_snn_completion_consumed_count": 1.0,
                    "riscv_snn_fault_count": 0.0,
                    "riscv_snn_last_completion_status": 0.0,
                    "riscv_snn_last_fault_csr": 0.0,
                },
            )

            class EquivRunner(FakeRunner):
                def __init__(self) -> None:
                    super().__init__()
                    self.run_dirs = [baseline_run, bridge_run]

                def __call__(self, cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
                    self.calls.append((cmd, cwd))
                    if any(str(part).endswith("run_mesh_with_time.sh") for part in cmd):
                        run_dir = self.run_dirs.pop(0)
                        return subprocess.CompletedProcess(
                            cmd,
                            0,
                            stdout=f"[mesh] run complete: {run_dir}\n",
                            stderr="",
                        )
                    return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")

            def fake_preflight(*, spec_path: Path, lab_root: Path = riscv_snn_lab.LAB_ROOT) -> dict[str, Any]:
                if spec_path == runtime_bridge_spec:
                    return {
                        "enabled": True,
                        "status": "ok",
                        "spec_path": str(spec_path),
                        "snndl_root": str(td_path / "sst_workspace" / "sst-elements" / "src" / "sst" / "elements" / "SnnDL"),
                        "workload_impl": "riscv_snn",
                        "backend_name": "runtime_bridge",
                        "contract_key": "riscv_snn.runtime_bridge.runtime_consumers",
                        "contract_version": 1,
                        "dependency_paths": ["/tmp/WeightMemorySubsystem.h", "/tmp/BankedSramModel.h"],
                        "required_target_paths": ["/tmp/libSnnDL.so"],
                        "stale_targets": [],
                        "missing_targets": [],
                        "rebuild_command": "make libSnnDL.la",
                    }
                return {
                    "enabled": False,
                    "status": "skipped",
                    "spec_path": str(spec_path),
                    "snndl_root": str(td_path / "sst_workspace" / "sst-elements" / "src" / "sst" / "elements" / "SnnDL"),
                    "workload_impl": "snn",
                    "backend_name": None,
                    "contract_key": None,
                    "contract_version": None,
                    "dependency_paths": [],
                    "required_target_paths": [],
                    "stale_targets": [],
                    "missing_targets": [],
                    "rebuild_command": "",
                }

            with mock.patch.object(riscv_snn_lab, "runtime_bridge_build_guard", side_effect=fake_preflight):
                summary = riscv_snn_lab.run_equivalence(
                    "external_dyn_desc_ref",
                    lab_root=lab_root,
                    runner=EquivRunner(),
                )

        self.assertEqual(
            summary["runtime_bridge"]["build_preflight"]["contract_key"],
            "riscv_snn.runtime_bridge.runtime_consumers",
        )
        self.assertEqual(summary["runtime_bridge"]["build_preflight_rollup"]["status"], "ok")
        self.assertEqual(
            summary["runtime_bridge"]["build_preflight_rollup"]["reporting_scope"],
            "research_only_nonblocking",
        )
        self.assertEqual(summary["runtime_bridge"]["build_preflight_rollup"]["required_target_count"], 1)

    def test_run_equivalence_surfaces_failed_smoke_as_fail_summary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            specs_dir = lab_root / "specs"
            refs_dir = lab_root / "references"
            specs_dir.mkdir(parents=True)
            refs_dir.mkdir(parents=True)

            baseline_spec = specs_dir / "external_dyn_desc_ref_snn_baseline.json"
            runtime_bridge_spec = specs_dir / "external_dyn_desc_ref_runtime_bridge.json"
            baseline_payload = {
                "schema_version": 3,
                "platform": {"mesh_size": 4, "exec_mode": "gas", "stop": {"mode": "time", "simulation_time": "1us"}},
                "workload": {"impl": "snn", "params": {}},
                "control": {"global_step_sync_enable": False},
            }
            runtime_bridge_payload = {
                "schema_version": 3,
                "platform": {"mesh_size": 4, "exec_mode": "gas", "stop": {"mode": "time", "simulation_time": "1us"}},
                "workload": {"impl": "riscv_snn", "params": {"backend_name": "runtime_bridge"}},
                "control": {"global_step_sync_enable": False},
            }
            baseline_spec.write_text(json.dumps(baseline_payload), encoding="utf-8")
            runtime_bridge_spec.write_text(json.dumps(runtime_bridge_payload), encoding="utf-8")

            def write_run_dir(run_dir: Path,
                              spec_payload: dict[str, object],
                              *,
                              validation_summary: str,
                              runtime_stats: dict[str, float]) -> None:
                (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
                (run_dir / "meta.json").write_text(
                    json.dumps(
                        {
                            "run": {
                                "run_id": run_dir.name,
                                "created_utc": "2026-03-25T00:00:00+00:00",
                                "hostname": "node1",
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                (run_dir / "inputs" / "spec.json").write_text(json.dumps(spec_payload), encoding="utf-8")
                (run_dir / "essential_summary_mesh.json").write_text(
                    json.dumps(
                        {
                            "schema_version": 2,
                            "model": {"exec_mode": "gas", "mesh_size": 4},
                            "contracts": {
                                "gas_semantic_ready_before_commit": True,
                                "gas_semantic_drain_before_scatter": True,
                            },
                            "memory": {"memory_requests": 10.0, "memory_bytes": 640.0},
                            "gas": {"windows": 2, "windows_done": 2},
                            "step": {"global_steps_done": 1},
                            "snn_tx": {"spike_packets_total": 4.0},
                            "snn_rx": {"spike_packets_total": 4.0},
                        }
                    ),
                    encoding="utf-8",
                )
                (run_dir / "validation.log").write_text(validation_summary, encoding="utf-8")
                with (run_dir / "mesh_stats.csv").open("w", encoding="utf-8") as handle:
                    handle.write(
                        "ComponentName,StatisticName,StatisticSubId,StatisticType,SimTime,Rank,Sum.u64,SumSQ.u64,Count.u64,Min.u64,Max.u64,Sum.f64,SumSQ.f64,Min.f64,Max.f64\n"
                    )
                    for name, value in runtime_stats.items():
                        handle.write(
                            f"core0,{name},0,Accumulator,0 ns,0,{int(value)},0,1,{int(value)},{int(value)},0,0,0,0\n"
                        )

            baseline_run = td_path / "baseline-run"
            bridge_run = td_path / "runtime-bridge-run"
            write_run_dir(
                baseline_run,
                baseline_payload,
                validation_summary="[val] SUMMARY run_dir=/tmp/fake-baseline fail=1 warn=0 strict=0\n",
                runtime_stats={},
            )
            write_run_dir(
                bridge_run,
                runtime_bridge_payload,
                validation_summary="[val] SUMMARY run_dir=/tmp/fake-bridge fail=0 warn=0 strict=0\n",
                runtime_stats={
                    "riscv_snn_fused_step_completion_count": 1.0,
                    "riscv_snn_completion_visible_count": 1.0,
                    "riscv_snn_fault_count": 0.0,
                },
            )

            class EquivRunner(FakeRunner):
                def __init__(self) -> None:
                    super().__init__()
                    self.run_dirs = [baseline_run, bridge_run]

                def __call__(self, cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
                    self.calls.append((cmd, cwd))
                    if any(str(part).endswith("run_mesh_with_time.sh") for part in cmd):
                        run_dir = self.run_dirs.pop(0)
                        if run_dir == baseline_run:
                            return subprocess.CompletedProcess(
                                cmd,
                                2,
                                stdout=f"[mesh] run complete: {run_dir}\n",
                                stderr="validator failed\n",
                            )
                        return subprocess.CompletedProcess(
                            cmd,
                            0,
                            stdout=f"[mesh] run complete: {run_dir}\n",
                            stderr="",
                        )
                    return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")

            runner = EquivRunner()
            summary = riscv_snn_lab.run_equivalence(
                "external_dyn_desc_ref",
                lab_root=lab_root,
                runner=runner,
            )

            self.assertEqual(summary["status"], "FAIL")
            self.assertEqual(summary["baseline"]["validation"], "failed")
            self.assertEqual(summary["runtime_bridge"]["validation"], "passed")
            self.assertEqual(summary["baseline"]["smoke_returncode"], 2)
            self.assertEqual(summary["runtime_bridge"]["smoke_returncode"], 0)
            self.assertTrue(Path(summary["summary_path"]).exists())

    def test_run_smoke_with_optional_failure_surfaces_environment_error_when_run_dir_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            specs_dir = lab_root / "specs"
            specs_dir.mkdir(parents=True)

            runtime_bridge_spec = specs_dir / "external_dyn_desc_ref_runtime_bridge.json"
            runtime_bridge_spec.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "platform": {
                            "mesh_size": 4,
                            "exec_mode": "gas",
                            "stop": {"mode": "time", "simulation_time": "1us"},
                        },
                        "workload": {"impl": "riscv_snn", "params": {"backend_name": "runtime_bridge"}},
                        "control": {"global_step_sync_enable": False},
                    }
                ),
                encoding="utf-8",
            )

            class FailedSmokeRunner(FakeRunner):
                def __call__(self, cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
                    self.calls.append((cmd, cwd))
                    if any(str(part).endswith("mesh_spec_cli.py") for part in cmd):
                        return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")
                    if any(str(part).endswith("run_mesh_with_time.sh") for part in cmd):
                        return subprocess.CompletedProcess(
                            cmd,
                            2,
                            stdout="[mesh] spec-first enabled: MESH_SPEC_JSON=/tmp/spec.json\n",
                            stderr=(
                                "[mesh] error: parallel SST exists but is not runnable in the current environment; "
                                "refusing to fall back to serial: /home/xgy/remote/sst_install/bin/sst\n"
                            ),
                        )
                    return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")

            runner = FailedSmokeRunner()
            with self.assertRaisesRegex(RuntimeError, "parallel SST exists but is not runnable"):
                riscv_snn_lab._run_smoke_with_optional_failure(
                    spec_path=runtime_bridge_spec,
                    lab_root=lab_root,
                    runner=runner,
                    allow_failed_run=True,
                )

    def test_run_smoke_with_optional_failure_recovers_existing_run_dir_after_post_validation_exit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            specs_dir = lab_root / "specs"
            specs_dir.mkdir(parents=True)

            runtime_bridge_spec = specs_dir / "external_dyn_desc_ref_runtime_bridge.json"
            runtime_bridge_spec.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "platform": {
                            "mesh_size": 4,
                            "exec_mode": "gas",
                            "stop": {"mode": "time", "simulation_time": "1us"},
                        },
                        "workload": {"impl": "riscv_snn", "params": {"backend_name": "runtime_bridge"}},
                        "control": {"global_step_sync_enable": False},
                    }
                ),
                encoding="utf-8",
            )

            smoke_root = lab_root / "smoke_runs" / runtime_bridge_spec.stem
            run_dir = smoke_root / "20260403-120000"
            (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
            (run_dir / "inputs" / "spec.json").write_text(runtime_bridge_spec.read_text(encoding="utf-8"), encoding="utf-8")
            (run_dir / "essential_summary_mesh.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "model": {"exec_mode": "gas", "mesh_size": 4},
                        "contracts": {
                            "gas_semantic_ready_before_commit": True,
                            "gas_semantic_drain_before_scatter": True,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "meta.json").write_text(
                json.dumps({"run": {"run_id": "20260403-120000"}}),
                encoding="utf-8",
            )
            (run_dir / "validation.log").write_text(
                "[val] SUMMARY run_dir=/tmp/fake fail=1 warn=0 strict=0\n",
                encoding="utf-8",
            )
            (run_dir / "mesh_stats.csv").write_text(
                "ComponentName,StatisticName,StatisticSubId,StatisticType,SimTime,Rank,Sum.u64,SumSQ.u64,Count.u64,Min.u64,Max.u64,Sum.f64,SumSQ.f64,Min.f64,Max.f64\n",
                encoding="utf-8",
            )

            class FailedAfterArtifactsRunner(FakeRunner):
                def __call__(self, cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
                    self.calls.append((cmd, cwd))
                    if any(str(part).endswith("mesh_spec_cli.py") for part in cmd):
                        return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")
                    if any(str(part).endswith("run_mesh_with_time.sh") for part in cmd):
                        return subprocess.CompletedProcess(
                            cmd,
                            2,
                            stdout="[mesh] spec-first enabled: MESH_SPEC_JSON=/tmp/spec.json\n",
                            stderr="validator failed after artifacts were written\n",
                        )
                    return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")

            runner = FailedAfterArtifactsRunner()
            with mock.patch.object(
                riscv_snn_lab,
                "ensure_parallel_sst_preflight",
                return_value={"status": "ok", "reason_ids": []},
            ), mock.patch.object(
                riscv_snn_lab,
                "ensure_runtime_bridge_build_guard",
                return_value=self._runtime_bridge_build_guard_ok_summary(),
            ):
                resolved_run_dir, proc = riscv_snn_lab._run_smoke_with_optional_failure(
                    spec_path=runtime_bridge_spec,
                    lab_root=lab_root,
                    runner=runner,
                    allow_failed_run=True,
                )

        self.assertEqual(resolved_run_dir, run_dir)
        self.assertEqual(proc.returncode, 2)

    def test_run_equivalence_structures_smoke_environment_failure_into_summary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            specs_dir = lab_root / "specs"
            refs_dir = lab_root / "references"
            specs_dir.mkdir(parents=True)
            refs_dir.mkdir(parents=True)

            baseline_spec = specs_dir / "external_dyn_desc_ref_snn_baseline.json"
            runtime_bridge_spec = specs_dir / "external_dyn_desc_ref_runtime_bridge.json"
            baseline_payload = {
                "schema_version": 3,
                "platform": {"mesh_size": 4, "exec_mode": "gas", "stop": {"mode": "time", "simulation_time": "1us"}},
                "workload": {"impl": "snn", "params": {}},
                "control": {"global_step_sync_enable": False},
            }
            runtime_bridge_payload = {
                "schema_version": 3,
                "platform": {"mesh_size": 4, "exec_mode": "gas", "stop": {"mode": "time", "simulation_time": "1us"}},
                "workload": {"impl": "riscv_snn", "params": {"backend_name": "runtime_bridge"}},
                "control": {"global_step_sync_enable": False},
            }
            baseline_spec.write_text(json.dumps(baseline_payload), encoding="utf-8")
            runtime_bridge_spec.write_text(json.dumps(runtime_bridge_payload), encoding="utf-8")

            bridge_run = td_path / "runtime-bridge-run"
            (bridge_run / "inputs").mkdir(parents=True, exist_ok=True)
            (bridge_run / "meta.json").write_text(
                json.dumps(
                    {
                        "run": {
                            "run_id": bridge_run.name,
                            "created_utc": "2026-03-26T00:00:00+00:00",
                            "hostname": "node1",
                        }
                    }
                ),
                encoding="utf-8",
            )
            (bridge_run / "inputs" / "spec.json").write_text(json.dumps(runtime_bridge_payload), encoding="utf-8")
            (bridge_run / "essential_summary_mesh.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "model": {"exec_mode": "gas", "mesh_size": 4},
                        "contracts": {
                            "gas_semantic_ready_before_commit": True,
                            "gas_semantic_drain_before_scatter": True,
                        },
                        "memory": {"memory_requests": 10.0, "memory_bytes": 640.0},
                        "gas": {"windows": 2, "windows_done": 2},
                        "step": {"global_steps_done": 1},
                    }
                ),
                encoding="utf-8",
            )
            (bridge_run / "validation.log").write_text(
                "[val] SUMMARY run_dir=/tmp/fake-bridge fail=0 warn=0 strict=0\n",
                encoding="utf-8",
            )
            with (bridge_run / "mesh_stats.csv").open("w", encoding="utf-8") as handle:
                handle.write(
                    "ComponentName,StatisticName,StatisticSubId,StatisticType,SimTime,Rank,Sum.u64,SumSQ.u64,Count.u64,Min.u64,Max.u64,Sum.f64,SumSQ.f64,Min.f64,Max.f64\n"
                )
                handle.write(
                    "core0,riscv_snn_fused_step_completion_count,0,Accumulator,0 ns,0,1,0,1,1,1,0,0,0,0\n"
                )

            class EquivRunner(FakeRunner):
                def __call__(self, cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
                    self.calls.append((cmd, cwd))
                    if any(str(part).endswith("mesh_spec_cli.py") for part in cmd):
                        return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")
                    if any(str(part).endswith("run_mesh_with_time.sh") for part in cmd):
                        spec_str = " ".join(str(part) for part in cmd)
                        if "external_dyn_desc_ref_snn_baseline.json" in spec_str:
                            return subprocess.CompletedProcess(
                                cmd,
                                2,
                                stdout="[mesh] spec-first enabled: MESH_SPEC_JSON=/tmp/spec.json\n",
                                stderr=(
                                    "[mesh] error: parallel SST exists but is not runnable in the current environment; "
                                    "refusing to fall back to serial: /home/xgy/remote/sst_install/bin/sst\n"
                                ),
                            )
                        return subprocess.CompletedProcess(
                            cmd,
                            0,
                            stdout=f"[mesh] run complete: {bridge_run}\n",
                            stderr="",
                        )
                    return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")

            runner = EquivRunner()
            summary = riscv_snn_lab.run_equivalence(
                "external_dyn_desc_ref",
                lab_root=lab_root,
                runner=runner,
            )

            self.assertEqual(summary["status"], "FAIL")
            self.assertIn("baseline_smoke_failed", summary["gate_reasons"])
            self.assertIn("baseline_smoke_env_parallel_sst_unavailable", summary["gate_reasons"])
            self.assertEqual(
                summary["baseline"]["validation_detail"]["reason_ids"],
                ["smoke_env_parallel_sst_unavailable", "smoke_env_run_dir_missing"],
            )
            self.assertEqual(summary["baseline"]["run_dir"], None)
            self.assertEqual(summary["baseline"]["smoke_returncode"], 2)
            self.assertEqual(summary["baseline"]["validation"], "smoke_failed")
            self.assertIn("parallel SST exists but is not runnable", summary["baseline"]["smoke_error"])
            self.assertEqual(summary["runtime_bridge"]["validation"], "passed")
            self.assertEqual(summary["runtime_bridge"]["smoke_error"], None)
            smoke_calls = [
                cmd for cmd, _ in runner.calls if any(str(part).endswith("run_mesh_with_time.sh") for part in cmd)
            ]
            self.assertTrue(smoke_calls)
            self.assertEqual(smoke_calls[0][0], "env")
            self.assertIn(
                f"MESH_RUN_ROOT={lab_root / 'smoke_runs' / 'external_dyn_desc_ref_snn_baseline'}",
                smoke_calls[0],
            )
            self.assertTrue(Path(summary["summary_path"]).exists())

    def test_run_equivalence_parses_summary_written_when_failed_smoke_exits_early(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            specs_dir = lab_root / "specs"
            refs_dir = lab_root / "references"
            specs_dir.mkdir(parents=True)
            refs_dir.mkdir(parents=True)

            baseline_spec = specs_dir / "external_dyn_desc_ref_snn_baseline.json"
            runtime_bridge_spec = specs_dir / "external_dyn_desc_ref_runtime_bridge.json"
            baseline_payload = {
                "schema_version": 3,
                "platform": {"mesh_size": 4, "exec_mode": "gas", "stop": {"mode": "time", "simulation_time": "1us"}},
                "workload": {"impl": "snn", "params": {}},
                "control": {"global_step_sync_enable": False},
            }
            runtime_bridge_payload = {
                "schema_version": 3,
                "platform": {"mesh_size": 4, "exec_mode": "gas", "stop": {"mode": "time", "simulation_time": "1us"}},
                "workload": {"impl": "riscv_snn", "params": {"backend_name": "runtime_bridge"}},
                "control": {"global_step_sync_enable": False},
            }
            baseline_spec.write_text(json.dumps(baseline_payload), encoding="utf-8")
            runtime_bridge_spec.write_text(json.dumps(runtime_bridge_payload), encoding="utf-8")

            def write_run_dir(run_dir: Path,
                              spec_payload: dict[str, object],
                              *,
                              validation_summary: str,
                              runtime_stats: dict[str, float]) -> None:
                (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
                (run_dir / "meta.json").write_text(
                    json.dumps(
                        {
                            "run": {
                                "run_id": run_dir.name,
                                "created_utc": "2026-03-25T00:00:00+00:00",
                                "hostname": "node1",
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                (run_dir / "inputs" / "spec.json").write_text(json.dumps(spec_payload), encoding="utf-8")
                (run_dir / "essential_summary_mesh.json").write_text(
                    json.dumps(
                        {
                            "schema_version": 2,
                            "model": {"exec_mode": "gas", "mesh_size": 4},
                            "contracts": {
                                "gas_semantic_ready_before_commit": True,
                                "gas_semantic_drain_before_scatter": True,
                            },
                            "memory": {"memory_requests": 10.0, "memory_bytes": 640.0},
                            "gas": {"windows": 2, "windows_done": 2},
                            "step": {"global_steps_done": 1},
                            "snn_tx": {"spike_packets_total": 4.0},
                            "snn_rx": {"spike_packets_total": 4.0},
                        }
                    ),
                    encoding="utf-8",
                )
                (run_dir / "validation.log").write_text(validation_summary, encoding="utf-8")
                with (run_dir / "mesh_stats.csv").open("w", encoding="utf-8") as handle:
                    handle.write(
                        "ComponentName,StatisticName,StatisticSubId,StatisticType,SimTime,Rank,Sum.u64,SumSQ.u64,Count.u64,Min.u64,Max.u64,Sum.f64,SumSQ.f64,Min.f64,Max.f64\n"
                    )
                    for name, value in runtime_stats.items():
                        handle.write(
                            f"core0,{name},0,Accumulator,0 ns,0,{int(value)},0,1,{int(value)},{int(value)},0,0,0,0\n"
                        )

            baseline_run = td_path / "baseline-run"
            bridge_run = td_path / "runtime-bridge-run"
            write_run_dir(
                baseline_run,
                baseline_payload,
                validation_summary="[val] SUMMARY run_dir=/tmp/fake-baseline fail=1 warn=0 strict=0\n",
                runtime_stats={},
            )
            write_run_dir(
                bridge_run,
                runtime_bridge_payload,
                validation_summary="[val] SUMMARY run_dir=/tmp/fake-bridge fail=0 warn=0 strict=0\n",
                runtime_stats={
                    "riscv_snn_fused_step_completion_count": 1.0,
                    "riscv_snn_completion_visible_count": 1.0,
                    "riscv_snn_fault_count": 0.0,
                },
            )

            class EquivRunner(FakeRunner):
                def __init__(self) -> None:
                    super().__init__()
                    self.run_dirs = [baseline_run, bridge_run]

                def __call__(self, cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
                    self.calls.append((cmd, cwd))
                    if any(str(part).endswith("run_mesh_with_time.sh") for part in cmd):
                        run_dir = self.run_dirs.pop(0)
                        if run_dir == baseline_run:
                            return subprocess.CompletedProcess(
                                cmd,
                                2,
                                stdout=f"[mesh] summary written: {run_dir / 'essential_summary_mesh.json'}\n",
                                stderr="validator failed\n",
                            )
                        return subprocess.CompletedProcess(
                            cmd,
                            0,
                            stdout=f"[mesh] run complete: {run_dir}\n",
                            stderr="",
                        )
                    return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")

            runner = EquivRunner()
            summary = riscv_snn_lab.run_equivalence(
                "external_dyn_desc_ref",
                lab_root=lab_root,
                runner=runner,
            )

            self.assertEqual(summary["status"], "FAIL")
            self.assertEqual(summary["baseline"]["validation"], "failed")
            self.assertEqual(summary["baseline"]["smoke_returncode"], 2)
            self.assertTrue(Path(summary["summary_path"]).exists())

    def test_run_equivalence_applies_compare_specific_baseline_waiver(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            specs_dir = lab_root / "specs"
            refs_dir = lab_root / "references"
            specs_dir.mkdir(parents=True)
            refs_dir.mkdir(parents=True)

            baseline_spec = specs_dir / "external_dyn_desc_ref_snn_baseline.json"
            runtime_bridge_spec = specs_dir / "external_dyn_desc_ref_runtime_bridge.json"
            baseline_payload = {
                "schema_version": 3,
                "platform": {"mesh_size": 4, "exec_mode": "gas", "stop": {"mode": "time", "simulation_time": "1us"}},
                "workload": {"impl": "snn", "params": {}},
                "control": {"global_step_sync_enable": False},
            }
            runtime_bridge_payload = {
                "schema_version": 3,
                "platform": {"mesh_size": 4, "exec_mode": "gas", "stop": {"mode": "time", "simulation_time": "1us"}},
                "workload": {"impl": "riscv_snn", "params": {"backend_name": "runtime_bridge"}},
                "control": {"global_step_sync_enable": False},
            }
            baseline_spec.write_text(json.dumps(baseline_payload), encoding="utf-8")
            runtime_bridge_spec.write_text(json.dumps(runtime_bridge_payload), encoding="utf-8")

            def write_run_dir(run_dir: Path,
                              spec_payload: dict[str, object],
                              *,
                              validation_lines: list[str],
                              runtime_stats: dict[str, float]) -> None:
                (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
                (run_dir / "meta.json").write_text(
                    json.dumps(
                        {
                            "run": {
                                "run_id": run_dir.name,
                                "created_utc": "2026-03-25T00:00:00+00:00",
                                "hostname": "node1",
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                (run_dir / "inputs" / "spec.json").write_text(json.dumps(spec_payload), encoding="utf-8")
                (run_dir / "essential_summary_mesh.json").write_text(
                    json.dumps(
                        {
                            "schema_version": 2,
                            "model": {"exec_mode": "gas", "mesh_size": 4},
                            "contracts": {
                                "gas_semantic_ready_before_commit": True,
                                "gas_semantic_drain_before_scatter": True,
                            },
                            "memory": {"memory_requests": 10.0, "memory_bytes": 640.0},
                            "gas": {"windows": 59, "windows_done": 27},
                            "step": {"global_steps_done": 1},
                            "snn_tx": {"spike_packets_total": 4.0},
                            "snn_rx": {"spike_packets_total": 4.0},
                        }
                    ),
                    encoding="utf-8",
                )
                (run_dir / "validation.log").write_text("\n".join(validation_lines) + "\n", encoding="utf-8")
                with (run_dir / "mesh_stats.csv").open("w", encoding="utf-8") as handle:
                    handle.write(
                        "ComponentName,StatisticName,StatisticSubId,StatisticType,SimTime,Rank,Sum.u64,SumSQ.u64,Count.u64,Min.u64,Max.u64,Sum.f64,SumSQ.f64,Min.f64,Max.f64\n"
                    )
                    for name, value in runtime_stats.items():
                        handle.write(
                            f"core0,{name},0,Accumulator,0 ns,0,{int(value)},0,1,{int(value)},{int(value)},0,0,0,0\n"
                        )

            baseline_run = td_path / "baseline-run"
            bridge_run = td_path / "runtime-bridge-run"
            write_run_dir(
                baseline_run,
                baseline_payload,
                validation_lines=[
                    "[val] PASS contracts.present: summary.contracts present",
                    "[val] FAIL step_activation.invocations_vs_windows: invocations=51 windows=59",
                    "[val] WARN gas.features.merge_enabled_bcsr: gap_k=0",
                    "[val] SUMMARY run_dir=/tmp/fake-baseline fail=1 warn=1 strict=0",
                ],
                runtime_stats={},
            )
            write_run_dir(
                bridge_run,
                runtime_bridge_payload,
                validation_lines=[
                    "[val] PASS contracts.present: summary.contracts present",
                    "[val] WARN gas.features.merge_enabled_bcsr: gap_k=0",
                    "[val] SUMMARY run_dir=/tmp/fake-bridge fail=0 warn=1 strict=0",
                ],
                runtime_stats={
                    "riscv_snn_backend_runtime_bridge_provider_bound": 1.0,
                    "riscv_snn_fused_step_completion_count": 1.0,
                    "riscv_snn_completion_visible_count": 1.0,
                    "riscv_snn_completion_consumed_count": 1.0,
                    "riscv_snn_fault_count": 0.0,
                    "riscv_snn_last_completion_status": 0.0,
                    "riscv_snn_last_fault_csr": 0.0,
                },
            )

            class EquivRunner(FakeRunner):
                def __init__(self) -> None:
                    super().__init__()
                    self.run_dirs = [baseline_run, bridge_run]

                def __call__(self, cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
                    self.calls.append((cmd, cwd))
                    if any(str(part).endswith("run_mesh_with_time.sh") for part in cmd):
                        run_dir = self.run_dirs.pop(0)
                        if run_dir == baseline_run:
                            return subprocess.CompletedProcess(
                                cmd,
                                2,
                                stdout=f"[mesh] run complete: {run_dir}\n",
                                stderr="validator failed\n",
                            )
                        return subprocess.CompletedProcess(
                            cmd,
                            0,
                            stdout=f"[mesh] run complete: {run_dir}\n",
                            stderr="",
                        )
                    return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")

            summary = riscv_snn_lab.run_equivalence(
                "external_dyn_desc_ref",
                lab_root=lab_root,
                runner=EquivRunner(),
            )

            self.assertEqual(summary["status"], "PASS")
            self.assertEqual(summary["baseline"]["validation"], "failed")
            self.assertEqual(summary["baseline"]["equiv_validation"]["summary"], "passed_with_waiver")
            self.assertTrue(summary["baseline"]["equiv_validation"]["waiver_applied"])
            self.assertEqual(
                summary["baseline"]["equiv_validation"]["waived_fail_checks"],
                ["step_activation.invocations_vs_windows"],
            )
            self.assertEqual(summary["baseline"]["equiv_validation"]["blocked_fail_checks"], [])
            self.assertEqual(
                summary["baseline"]["validation_detail"]["fail_checks"],
                ["step_activation.invocations_vs_windows"],
            )

    def test_run_equivalence_accepts_fault_ref_with_fault_completion_progress(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            specs_dir = lab_root / "specs"
            refs_dir = lab_root / "references"
            specs_dir.mkdir(parents=True)
            refs_dir.mkdir(parents=True)

            baseline_spec = specs_dir / "external_dyn_desc_fault_ref_snn_baseline.json"
            runtime_bridge_spec = specs_dir / "external_dyn_desc_fault_ref_runtime_bridge.json"
            baseline_payload = {
                "schema_version": 3,
                "platform": {"mesh_size": 4, "exec_mode": "gas", "stop": {"mode": "time", "simulation_time": "1us"}},
                "workload": {"impl": "snn", "params": {}},
                "control": {"global_step_sync_enable": False},
            }
            runtime_bridge_payload = {
                "schema_version": 3,
                "platform": {"mesh_size": 4, "exec_mode": "gas", "stop": {"mode": "time", "simulation_time": "1us"}},
                "workload": {"impl": "riscv_snn", "params": {"backend_name": "runtime_bridge"}},
                "control": {"global_step_sync_enable": False},
            }
            baseline_spec.write_text(json.dumps(baseline_payload), encoding="utf-8")
            runtime_bridge_spec.write_text(json.dumps(runtime_bridge_payload), encoding="utf-8")

            def write_run_dir(run_dir: Path,
                              spec_payload: dict[str, object],
                              *,
                              validation_lines: list[str],
                              runtime_stats: dict[str, float]) -> None:
                (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
                (run_dir / "meta.json").write_text(
                    json.dumps(
                        {
                            "run": {
                                "run_id": run_dir.name,
                                "created_utc": "2026-03-26T00:00:00+00:00",
                                "hostname": "node1",
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                (run_dir / "inputs" / "spec.json").write_text(json.dumps(spec_payload), encoding="utf-8")
                (run_dir / "essential_summary_mesh.json").write_text(
                    json.dumps(
                        {
                            "schema_version": 2,
                            "model": {"exec_mode": "gas", "mesh_size": 4},
                            "contracts": {
                                "gas_semantic_ready_before_commit": True,
                                "gas_semantic_drain_before_scatter": True,
                            },
                            "memory": {"memory_requests": 10.0, "memory_bytes": 640.0},
                            "gas": {"windows": 59, "windows_done": 27},
                            "step": {"global_steps_done": 0},
                            "snn_tx": {"spike_packets_total": 4.0},
                            "snn_rx": {"spike_packets_total": 4.0},
                        }
                    ),
                    encoding="utf-8",
                )
                (run_dir / "validation.log").write_text("\n".join(validation_lines) + "\n", encoding="utf-8")
                with (run_dir / "mesh_stats.csv").open("w", encoding="utf-8") as handle:
                    handle.write(
                        "ComponentName,StatisticName,StatisticSubId,StatisticType,SimTime,Rank,Sum.u64,SumSQ.u64,Count.u64,Min.u64,Max.u64,Sum.f64,SumSQ.f64,Min.f64,Max.f64\n"
                    )
                    for name, value in runtime_stats.items():
                        handle.write(
                            f"core0,{name},0,Accumulator,0 ns,0,{int(value)},0,1,{int(value)},{int(value)},0,0,0,0\n"
                        )

            baseline_run = td_path / "baseline-run"
            bridge_run = td_path / "runtime-bridge-run"
            write_run_dir(
                baseline_run,
                baseline_payload,
                validation_lines=[
                    "[val] PASS contracts.present: summary.contracts present",
                    "[val] FAIL step_activation.invocations_vs_windows: invocations=51 windows=59",
                    "[val] SUMMARY run_dir=/tmp/fake-baseline fail=1 warn=0 strict=0",
                ],
                runtime_stats={},
            )
            write_run_dir(
                bridge_run,
                runtime_bridge_payload,
                validation_lines=[
                    "[val] PASS contracts.present: summary.contracts present",
                    "[val] SUMMARY run_dir=/tmp/fake-bridge fail=0 warn=0 strict=0",
                ],
                runtime_stats={
                    "riscv_snn_backend_runtime_bridge_provider_bound": 1.0,
                    "riscv_snn_fused_step_completion_count": 0.0,
                    "riscv_snn_completion_visible_count": 1.0,
                    "riscv_snn_completion_consumed_count": 1.0,
                    "riscv_snn_fault_count": 1.0,
                    "riscv_snn_last_completion_status": 516.0,
                    "riscv_snn_last_fault_csr": 260.0,
                },
            )

            class EquivRunner(FakeRunner):
                def __init__(self) -> None:
                    super().__init__()
                    self.run_dirs = [baseline_run, bridge_run]

                def __call__(self, cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
                    self.calls.append((cmd, cwd))
                    if any(str(part).endswith("run_mesh_with_time.sh") for part in cmd):
                        run_dir = self.run_dirs.pop(0)
                        if run_dir == baseline_run:
                            return subprocess.CompletedProcess(
                                cmd,
                                2,
                                stdout=f"[mesh] run complete: {run_dir}\n",
                                stderr="validator failed\n",
                            )
                        return subprocess.CompletedProcess(
                            cmd,
                            0,
                            stdout=f"[mesh] run complete: {run_dir}\n",
                            stderr="",
                        )
                    return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")

            summary = riscv_snn_lab.run_equivalence(
                "external_dyn_desc_fault_ref",
                lab_root=lab_root,
                runner=EquivRunner(),
            )

            self.assertEqual(summary["status"], "PASS")
            self.assertEqual(summary["baseline"]["equiv_validation"]["summary"], "passed_with_waiver")
            self.assertEqual(summary["runtime_bridge"]["runtime_gate"]["summary"], "passed")
            self.assertNotIn("baseline_validation_failed", summary["gate_reasons"])
            self.assertNotIn("runtime_bridge_fused_step_completion_missing", summary["gate_reasons"])

    def test_run_equivalence_keeps_unlisted_baseline_failures_hard_failed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            specs_dir = lab_root / "specs"
            refs_dir = lab_root / "references"
            specs_dir.mkdir(parents=True)
            refs_dir.mkdir(parents=True)

            baseline_spec = specs_dir / "external_dyn_desc_ref_snn_baseline.json"
            runtime_bridge_spec = specs_dir / "external_dyn_desc_ref_runtime_bridge.json"
            baseline_payload = {
                "schema_version": 3,
                "platform": {"mesh_size": 4, "exec_mode": "gas", "stop": {"mode": "time", "simulation_time": "1us"}},
                "workload": {"impl": "snn", "params": {}},
                "control": {"global_step_sync_enable": False},
            }
            runtime_bridge_payload = {
                "schema_version": 3,
                "platform": {"mesh_size": 4, "exec_mode": "gas", "stop": {"mode": "time", "simulation_time": "1us"}},
                "workload": {"impl": "riscv_snn", "params": {"backend_name": "runtime_bridge"}},
                "control": {"global_step_sync_enable": False},
            }
            baseline_spec.write_text(json.dumps(baseline_payload), encoding="utf-8")
            runtime_bridge_spec.write_text(json.dumps(runtime_bridge_payload), encoding="utf-8")

            def write_run_dir(run_dir: Path,
                              spec_payload: dict[str, object],
                              *,
                              validation_lines: list[str],
                              runtime_stats: dict[str, float]) -> None:
                (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
                (run_dir / "meta.json").write_text(
                    json.dumps(
                        {
                            "run": {
                                "run_id": run_dir.name,
                                "created_utc": "2026-03-25T00:00:00+00:00",
                                "hostname": "node1",
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                (run_dir / "inputs" / "spec.json").write_text(json.dumps(spec_payload), encoding="utf-8")
                (run_dir / "essential_summary_mesh.json").write_text(
                    json.dumps(
                        {
                            "schema_version": 2,
                            "model": {"exec_mode": "gas", "mesh_size": 4},
                            "contracts": {
                                "gas_semantic_ready_before_commit": True,
                                "gas_semantic_drain_before_scatter": True,
                            },
                            "memory": {"memory_requests": 10.0, "memory_bytes": 640.0},
                            "gas": {"windows": 59, "windows_done": 27},
                            "step": {"global_steps_done": 1},
                            "snn_tx": {"spike_packets_total": 4.0},
                            "snn_rx": {"spike_packets_total": 4.0},
                        }
                    ),
                    encoding="utf-8",
                )
                (run_dir / "validation.log").write_text("\n".join(validation_lines) + "\n", encoding="utf-8")
                with (run_dir / "mesh_stats.csv").open("w", encoding="utf-8") as handle:
                    handle.write(
                        "ComponentName,StatisticName,StatisticSubId,StatisticType,SimTime,Rank,Sum.u64,SumSQ.u64,Count.u64,Min.u64,Max.u64,Sum.f64,SumSQ.f64,Min.f64,Max.f64\n"
                    )
                    for name, value in runtime_stats.items():
                        handle.write(
                            f"core0,{name},0,Accumulator,0 ns,0,{int(value)},0,1,{int(value)},{int(value)},0,0,0,0\n"
                        )

            baseline_run = td_path / "baseline-run"
            bridge_run = td_path / "runtime-bridge-run"
            write_run_dir(
                baseline_run,
                baseline_payload,
                validation_lines=[
                    "[val] FAIL step_activation.invocations_vs_windows: invocations=51 windows=59",
                    "[val] FAIL memory.nonzero: memory_requests=0 memory_bytes=0",
                    "[val] SUMMARY run_dir=/tmp/fake-baseline fail=2 warn=0 strict=0",
                ],
                runtime_stats={},
            )
            write_run_dir(
                bridge_run,
                runtime_bridge_payload,
                validation_lines=[
                    "[val] SUMMARY run_dir=/tmp/fake-bridge fail=0 warn=0 strict=0",
                ],
                runtime_stats={
                    "riscv_snn_fused_step_completion_count": 1.0,
                    "riscv_snn_completion_visible_count": 1.0,
                    "riscv_snn_fault_count": 0.0,
                },
            )

            class EquivRunner(FakeRunner):
                def __init__(self) -> None:
                    super().__init__()
                    self.run_dirs = [baseline_run, bridge_run]

                def __call__(self, cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
                    self.calls.append((cmd, cwd))
                    if any(str(part).endswith("run_mesh_with_time.sh") for part in cmd):
                        run_dir = self.run_dirs.pop(0)
                        if run_dir == baseline_run:
                            return subprocess.CompletedProcess(
                                cmd,
                                2,
                                stdout=f"[mesh] run complete: {run_dir}\n",
                                stderr="validator failed\n",
                            )
                        return subprocess.CompletedProcess(
                            cmd,
                            0,
                            stdout=f"[mesh] run complete: {run_dir}\n",
                            stderr="",
                        )
                    return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")

            summary = riscv_snn_lab.run_equivalence(
                "external_dyn_desc_ref",
                lab_root=lab_root,
                runner=EquivRunner(),
            )

            self.assertEqual(summary["status"], "FAIL")
            self.assertEqual(summary["baseline"]["equiv_validation"]["summary"], "failed")
            self.assertTrue(summary["baseline"]["equiv_validation"]["waiver_applied"])
            self.assertEqual(summary["baseline"]["equiv_validation"]["waived_fail_checks"], ["step_activation.invocations_vs_windows"])
            self.assertEqual(summary["baseline"]["equiv_validation"]["blocked_fail_checks"], ["memory.nonzero"])

    def test_trend_equiv_rows_add_analysis_metadata(self) -> None:
        baseline = {
            "summary": {
                "memory": {"memory_requests": 100.0, "memory_bytes": 6400.0},
                "gas": {"windows": 59, "windows_done": 27},
                "step": {"global_steps_done": 4},
                "snn_tx": {"spike_packets_total": 88.0},
                "snn_rx": {"spike_packets_total": 21.0},
            }
        }
        runtime_bridge = {
            "summary": {
                "memory": {"memory_requests": 64.0, "memory_bytes": 4096.0},
                "gas": {"windows": 64, "windows_done": 32},
                "step": {"global_steps_done": 4},
            }
        }

        rows = riscv_snn_lab._trend_equiv_rows(baseline, runtime_bridge)
        by_field = {row["field"]: row for row in rows}

        self.assertEqual(by_field["memory.memory_requests"]["classification"], "traffic_cost_delta")
        self.assertEqual(by_field["memory.memory_requests"]["gate_level"], "info")
        self.assertAlmostEqual(by_field["memory.memory_requests"]["delta_ratio"], -0.36)
        self.assertEqual(
            by_field["memory.memory_requests"]["policy"]["policy_id"],
            "memory_cost_research_surface",
        )
        self.assertEqual(
            by_field["memory.memory_requests"]["policy"]["enforcement"],
            "informational",
        )
        self.assertIn("not a PASS blocker", by_field["memory.memory_requests"]["note"])

        self.assertEqual(by_field["gas.windows"]["classification"], "window_accounting_delta")
        self.assertEqual(by_field["step.global_steps_done"]["classification"], "aligned")
        self.assertEqual(by_field["snn_tx.spike_packets_total"]["classification"], "visibility_gap")
        self.assertEqual(by_field["snn_tx.spike_packets_total"]["gate_level"], "warn")
        self.assertEqual(
            by_field["snn_tx.spike_packets_total"]["policy"]["enforcement"],
            "warn_on_visibility_gap",
        )
        self.assertIsNone(by_field["snn_tx.spike_packets_total"]["delta_ratio"])

    def test_trend_equiv_overview_promotes_transport_visibility_gap_to_warn(self) -> None:
        rows = [
            {
                "field": "memory.memory_requests",
                "classification": "traffic_cost_delta",
                "gate_level": "info",
                "policy": {
                    "policy_id": "memory_cost_research_surface",
                    "enforcement": "informational",
                },
            },
            {
                "field": "snn_tx.spike_packets_total",
                "classification": "visibility_gap",
                "gate_level": "warn",
                "policy": {
                    "policy_id": "transport_visibility_surface",
                    "enforcement": "warn_on_visibility_gap",
                },
            },
            {
                "field": "snn_rx.spike_packets_total",
                "classification": "visibility_gap",
                "gate_level": "warn",
                "policy": {
                    "policy_id": "transport_visibility_surface",
                    "enforcement": "warn_on_visibility_gap",
                },
            },
        ]

        overview = riscv_snn_lab._trend_equiv_overview(rows)

        self.assertEqual(overview["status"], "passed_with_warning")
        self.assertEqual(
            overview["gate_warnings"],
            [
                "trend_visibility_gap:snn_tx.spike_packets_total",
                "trend_visibility_gap:snn_rx.spike_packets_total",
            ],
        )
        self.assertEqual(overview["gate_failures"], [])
        self.assertIn("transport_visibility_surface", overview["policy_ids"])

    def test_runtime_bridge_gate_requires_provider_binding_and_fault_snapshot_consistency(self) -> None:
        gate = riscv_snn_lab._runtime_bridge_gate(
            {
                "riscv_snn_workload_selected": 1.0,
                "riscv_snn_backend_runtime_bridge": 1.0,
                "riscv_snn_firmware_loaded": 1.0,
                "riscv_snn_firmware_started_count": 1.0,
                "riscv_snn_fused_step_completion_count": 1.0,
                "riscv_snn_completion_visible_count": 0.0,
                "riscv_snn_completion_consumed_count": 0.0,
                "riscv_snn_fault_count": 1.0,
                "riscv_snn_last_fault_csr": 0.0,
                "riscv_snn_backend_runtime_bridge_provider_bound": 0.0,
            }
        )

        self.assertEqual(gate["summary"], "failed")
        self.assertFalse(gate["ok"])
        self.assertIn("runtime_bridge_provider_unbound", gate["hard_failures"])
        self.assertIn("runtime_bridge_fault_snapshot_missing", gate["hard_failures"])
        self.assertIn("runtime_bridge_completion_visibility_missing", gate["warnings"])

    def test_runtime_bridge_gate_requires_fault_for_fault_reference_family(self) -> None:
        gate = riscv_snn_lab._runtime_bridge_gate(
            {
                "riscv_snn_workload_selected": 1.0,
                "riscv_snn_backend_runtime_bridge": 1.0,
                "riscv_snn_firmware_loaded": 1.0,
                "riscv_snn_firmware_started_count": 1.0,
                "riscv_snn_fused_step_completion_count": 1.0,
                "riscv_snn_completion_visible_count": 1.0,
                "riscv_snn_completion_consumed_count": 1.0,
                "riscv_snn_fault_count": 0.0,
                "riscv_snn_last_fault_csr": 0.0,
                "riscv_snn_last_completion_status": 0.0,
                "riscv_snn_backend_runtime_bridge_provider_bound": 1.0,
            },
            family="external_dyn_desc_fault_ref",
        )

        self.assertEqual(gate["summary"], "failed")
        self.assertFalse(gate["ok"])
        self.assertIn("runtime_bridge_expected_fault_missing", gate["hard_failures"])

    def test_runtime_bridge_gate_allows_nonzero_completion_status_for_fault_family(self) -> None:
        gate = riscv_snn_lab._runtime_bridge_gate(
            {
                "riscv_snn_workload_selected": 1.0,
                "riscv_snn_backend_runtime_bridge": 1.0,
                "riscv_snn_firmware_loaded": 1.0,
                "riscv_snn_firmware_started_count": 1.0,
                "riscv_snn_fused_step_completion_count": 1.0,
                "riscv_snn_completion_visible_count": 1.0,
                "riscv_snn_completion_consumed_count": 1.0,
                "riscv_snn_fault_count": 1.0,
                "riscv_snn_last_fault_csr": 260.0,
                "riscv_snn_last_completion_status": 1.0,
                "riscv_snn_backend_runtime_bridge_provider_bound": 1.0,
            },
            family="external_dyn_desc_fault_ref",
        )

        self.assertEqual(gate["summary"], "passed")
        self.assertEqual(gate["warnings"], [])
        self.assertNotIn("runtime_bridge_last_completion_nonzero", gate["warnings"])

    def test_runtime_bridge_gate_accepts_fault_family_with_visible_unconsumed_completion(self) -> None:
        gate = riscv_snn_lab._runtime_bridge_gate(
            {
                "riscv_snn_workload_selected": 64.0,
                "riscv_snn_backend_runtime_bridge": 64.0,
                "riscv_snn_firmware_loaded": 64.0,
                "riscv_snn_firmware_started_count": 64.0,
                "riscv_snn_fused_step_completion_count": 64.0,
                "riscv_snn_completion_visible_count": 64.0,
                "riscv_snn_completion_consumed_count": 0.0,
                "riscv_snn_fault_count": 64.0,
                "riscv_snn_last_fault_csr": 274877940736.0,
                "riscv_snn_last_completion_status": 0.0,
                "riscv_snn_backend_runtime_bridge_provider_bound": 64.0,
            },
            family="external_dyn_desc_fault_ref",
        )

        self.assertEqual(gate["summary"], "passed")
        self.assertEqual(gate["hard_failures"], [])
        self.assertEqual(gate["warnings"], [])

    def test_runtime_bridge_gate_allows_visibility_only_progress_for_barrier_family(self) -> None:
        gate = riscv_snn_lab._runtime_bridge_gate(
            {
                "riscv_snn_workload_selected": 1.0,
                "riscv_snn_backend_runtime_bridge": 1.0,
                "riscv_snn_firmware_loaded": 1.0,
                "riscv_snn_firmware_started_count": 1.0,
                "riscv_snn_fused_step_completion_count": 0.0,
                "riscv_snn_completion_visible_count": 1.0,
                "riscv_snn_completion_consumed_count": 0.0,
                "riscv_snn_fault_count": 1.0,
                "riscv_snn_last_fault_csr": 260.0,
                "riscv_snn_last_completion_status": 1.0,
                "riscv_snn_backend_runtime_bridge_provider_bound": 1.0,
            },
            family="barrier_wfi_order_ref",
        )

        self.assertEqual(gate["summary"], "passed")
        self.assertEqual(gate["warnings"], [])
        self.assertNotIn("runtime_bridge_fused_step_completion_missing", gate["warnings"])
        self.assertNotIn("runtime_bridge_completion_not_fully_consumed", gate["warnings"])
        self.assertNotIn("runtime_bridge_last_completion_nonzero", gate["warnings"])

    def test_runtime_bridge_gate_accepts_aggregated_queue_fault_signature(self) -> None:
        single_fault_csr = 0x0000000100000210
        fault_count = 64.0
        gate = riscv_snn_lab._runtime_bridge_gate(
            {
                "riscv_snn_workload_selected": 64.0,
                "riscv_snn_backend_runtime_bridge": 64.0,
                "riscv_snn_firmware_loaded": 64.0,
                "riscv_snn_firmware_started_count": 64.0,
                "riscv_snn_fused_step_completion_count": 64.0,
                "riscv_snn_completion_visible_count": 64.0,
                "riscv_snn_completion_consumed_count": 0.0,
                "riscv_snn_fault_count": fault_count,
                "riscv_snn_last_fault_csr": float(int(fault_count) * single_fault_csr),
                "riscv_snn_last_completion_status": 0.0,
                "riscv_snn_backend_runtime_bridge_provider_bound": 64.0,
            },
            family="queue_backpressure_ref",
        )

        self.assertEqual(gate["summary"], "passed")
        self.assertEqual(gate["hard_failures"], [])
        self.assertEqual(gate["warnings"], [])

    def test_runtime_bridge_gate_accepts_aggregated_completion_queue_fault_signature(self) -> None:
        single_fault_csr = 0x0000000100000211
        fault_count = 64.0
        gate = riscv_snn_lab._runtime_bridge_gate(
            {
                "riscv_snn_workload_selected": 64.0,
                "riscv_snn_backend_runtime_bridge": 64.0,
                "riscv_snn_firmware_loaded": 64.0,
                "riscv_snn_firmware_started_count": 64.0,
                "riscv_snn_fused_step_completion_count": 64.0,
                "riscv_snn_completion_visible_count": 64.0,
                "riscv_snn_completion_consumed_count": 0.0,
                "riscv_snn_fault_count": fault_count,
                "riscv_snn_last_fault_csr": float(int(fault_count) * single_fault_csr),
                "riscv_snn_last_completion_status": 0.0,
                "riscv_snn_backend_runtime_bridge_provider_bound": 64.0,
            },
            family="completion_queue_overflow_ref",
        )

        self.assertEqual(gate["summary"], "passed")
        self.assertEqual(gate["hard_failures"], [])
        self.assertEqual(gate["warnings"], [])

    def test_run_equivalence_warns_when_completion_visibility_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            specs_dir = lab_root / "specs"
            refs_dir = lab_root / "references"
            specs_dir.mkdir(parents=True)
            refs_dir.mkdir(parents=True)

            baseline_spec = specs_dir / "external_dyn_desc_ref_snn_baseline.json"
            runtime_bridge_spec = specs_dir / "external_dyn_desc_ref_runtime_bridge.json"
            baseline_payload = {
                "schema_version": 3,
                "platform": {"mesh_size": 4, "exec_mode": "gas", "stop": {"mode": "time", "simulation_time": "1us"}},
                "workload": {"impl": "snn", "params": {}},
                "control": {"global_step_sync_enable": False},
            }
            runtime_bridge_payload = {
                "schema_version": 3,
                "platform": {"mesh_size": 4, "exec_mode": "gas", "stop": {"mode": "time", "simulation_time": "1us"}},
                "workload": {"impl": "riscv_snn", "params": {"backend_name": "runtime_bridge"}},
                "control": {"global_step_sync_enable": False},
            }
            baseline_spec.write_text(json.dumps(baseline_payload), encoding="utf-8")
            runtime_bridge_spec.write_text(json.dumps(runtime_bridge_payload), encoding="utf-8")

            def write_run_dir(run_dir: Path,
                              spec_payload: dict[str, object],
                              *,
                              runtime_stats: dict[str, float]) -> None:
                (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
                (run_dir / "meta.json").write_text(
                    json.dumps(
                        {
                            "run": {
                                "run_id": run_dir.name,
                                "created_utc": "2026-03-26T00:00:00+00:00",
                                "hostname": "node1",
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                (run_dir / "inputs" / "spec.json").write_text(json.dumps(spec_payload), encoding="utf-8")
                (run_dir / "essential_summary_mesh.json").write_text(
                    json.dumps(
                        {
                            "schema_version": 2,
                            "model": {"exec_mode": "gas", "mesh_size": 4},
                            "contracts": {
                                "gas_semantic_ready_before_commit": True,
                                "gas_semantic_drain_before_scatter": True,
                            },
                            "memory": {"memory_requests": 10.0, "memory_bytes": 640.0},
                            "gas": {"windows": 2, "windows_done": 2},
                            "step": {"global_steps_done": 1},
                            "snn_tx": {"spike_packets_total": 4.0},
                            "snn_rx": {"spike_packets_total": 4.0},
                        }
                    ),
                    encoding="utf-8",
                )
                (run_dir / "validation.log").write_text(
                    "[val] SUMMARY run_dir=/tmp/fake-run fail=0 warn=0 strict=0\n",
                    encoding="utf-8",
                )
                with (run_dir / "mesh_stats.csv").open("w", encoding="utf-8") as handle:
                    handle.write(
                        "ComponentName,StatisticName,StatisticSubId,StatisticType,SimTime,Rank,Sum.u64,SumSQ.u64,Count.u64,Min.u64,Max.u64,Sum.f64,SumSQ.f64,Min.f64,Max.f64\n"
                    )
                    for name, value in runtime_stats.items():
                        handle.write(
                            f"core0,{name},0,Accumulator,0 ns,0,{int(value)},0,1,{int(value)},{int(value)},0,0,0,0\n"
                        )

            baseline_run = td_path / "baseline-run"
            bridge_run = td_path / "runtime-bridge-run"
            write_run_dir(baseline_run, baseline_payload, runtime_stats={})
            write_run_dir(
                bridge_run,
                runtime_bridge_payload,
                runtime_stats={
                    "riscv_snn_workload_selected": 1.0,
                    "riscv_snn_backend_runtime_bridge": 1.0,
                    "riscv_snn_firmware_loaded": 1.0,
                    "riscv_snn_firmware_started_count": 1.0,
                    "riscv_snn_backend_runtime_bridge_provider_bound": 1.0,
                    "riscv_snn_fused_step_completion_count": 1.0,
                    "riscv_snn_completion_visible_count": 0.0,
                    "riscv_snn_completion_consumed_count": 0.0,
                    "riscv_snn_fault_count": 0.0,
                    "riscv_snn_last_completion_status": 0.0,
                    "riscv_snn_last_fault_csr": 0.0,
                },
            )

            class EquivRunner(FakeRunner):
                def __init__(self) -> None:
                    super().__init__()
                    self.run_dirs = [baseline_run, bridge_run]

                def __call__(self, cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
                    self.calls.append((cmd, cwd))
                    if any(str(part).endswith("run_mesh_with_time.sh") for part in cmd):
                        run_dir = self.run_dirs.pop(0)
                        return subprocess.CompletedProcess(
                            cmd,
                            0,
                            stdout=f"[mesh] run complete: {run_dir}\n",
                            stderr="",
                        )
                    return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")

            summary = riscv_snn_lab.run_equivalence(
                "external_dyn_desc_ref",
                lab_root=lab_root,
                runner=EquivRunner(),
            )

            self.assertEqual(summary["status"], "WARN")
            self.assertIn("runtime_bridge_completion_visibility_missing", summary["gate_reasons"])
            self.assertEqual(summary["runtime_bridge"]["runtime_gate"]["summary"], "passed_with_warning")

    def test_run_equivalence_allows_fault_completion_status_for_bad_policy_family(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            specs_dir = lab_root / "specs"
            refs_dir = lab_root / "references"
            specs_dir.mkdir(parents=True)
            refs_dir.mkdir(parents=True)

            baseline_spec = specs_dir / "external_dyn_desc_bad_policy_ref_snn_baseline.json"
            runtime_bridge_spec = specs_dir / "external_dyn_desc_bad_policy_ref_runtime_bridge.json"
            baseline_payload = {
                "schema_version": 3,
                "platform": {"mesh_size": 4, "exec_mode": "gas", "stop": {"mode": "time", "simulation_time": "1us"}},
                "workload": {"impl": "snn", "params": {}},
                "control": {"global_step_sync_enable": False},
            }
            runtime_bridge_payload = {
                "schema_version": 3,
                "platform": {"mesh_size": 4, "exec_mode": "gas", "stop": {"mode": "time", "simulation_time": "1us"}},
                "workload": {"impl": "riscv_snn", "params": {"backend_name": "runtime_bridge"}},
                "control": {"global_step_sync_enable": False},
            }
            baseline_spec.write_text(json.dumps(baseline_payload), encoding="utf-8")
            runtime_bridge_spec.write_text(json.dumps(runtime_bridge_payload), encoding="utf-8")

            def write_run_dir(run_dir: Path,
                              spec_payload: dict[str, object],
                              *,
                              runtime_stats: dict[str, float]) -> None:
                (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
                (run_dir / "meta.json").write_text(
                    json.dumps(
                        {
                            "run": {
                                "run_id": run_dir.name,
                                "created_utc": "2026-03-26T00:00:00+00:00",
                                "hostname": "node1",
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                (run_dir / "inputs" / "spec.json").write_text(json.dumps(spec_payload), encoding="utf-8")
                (run_dir / "essential_summary_mesh.json").write_text(
                    json.dumps(
                        {
                            "schema_version": 2,
                            "model": {"exec_mode": "gas", "mesh_size": 4},
                            "contracts": {
                                "gas_semantic_ready_before_commit": True,
                                "gas_semantic_drain_before_scatter": True,
                            },
                            "memory": {"memory_requests": 10.0, "memory_bytes": 640.0},
                            "gas": {"windows": 2, "windows_done": 2},
                            "step": {"global_steps_done": 0},
                            "snn_tx": {"spike_packets_total": 4.0},
                            "snn_rx": {"spike_packets_total": 4.0},
                        }
                    ),
                    encoding="utf-8",
                )
                (run_dir / "validation.log").write_text(
                    "[val] SUMMARY run_dir=/tmp/fake-run fail=0 warn=0 strict=0\n",
                    encoding="utf-8",
                )
                with (run_dir / "mesh_stats.csv").open("w", encoding="utf-8") as handle:
                    handle.write(
                        "ComponentName,StatisticName,StatisticSubId,StatisticType,SimTime,Rank,Sum.u64,SumSQ.u64,Count.u64,Min.u64,Max.u64,Sum.f64,SumSQ.f64,Min.f64,Max.f64\n"
                    )
                    for name, value in runtime_stats.items():
                        handle.write(
                            f"core0,{name},0,Accumulator,0 ns,0,{int(value)},0,1,{int(value)},{int(value)},0,0,0,0\n"
                        )

            baseline_run = td_path / "baseline-run"
            bridge_run = td_path / "runtime-bridge-run"
            write_run_dir(baseline_run, baseline_payload, runtime_stats={})
            write_run_dir(
                bridge_run,
                runtime_bridge_payload,
                runtime_stats={
                    "riscv_snn_workload_selected": 1.0,
                    "riscv_snn_backend_runtime_bridge": 1.0,
                    "riscv_snn_firmware_loaded": 1.0,
                    "riscv_snn_firmware_started_count": 1.0,
                    "riscv_snn_backend_runtime_bridge_provider_bound": 1.0,
                    "riscv_snn_fused_step_completion_count": 1.0,
                    "riscv_snn_completion_visible_count": 1.0,
                    "riscv_snn_completion_consumed_count": 1.0,
                    "riscv_snn_fault_count": 1.0,
                    "riscv_snn_last_completion_status": 1.0,
                    "riscv_snn_last_fault_csr": 260.0,
                },
            )

            class EquivRunner(FakeRunner):
                def __init__(self) -> None:
                    super().__init__()
                    self.run_dirs = [baseline_run, bridge_run]

                def __call__(self, cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
                    self.calls.append((cmd, cwd))
                    if any(str(part).endswith("run_mesh_with_time.sh") for part in cmd):
                        run_dir = self.run_dirs.pop(0)
                        return subprocess.CompletedProcess(
                            cmd,
                            0,
                            stdout=f"[mesh] run complete: {run_dir}\n",
                            stderr="",
                        )
                    return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")

            summary = riscv_snn_lab.run_equivalence(
                "external_dyn_desc_bad_policy_ref",
                lab_root=lab_root,
                runner=EquivRunner(),
            )

            self.assertEqual(summary["status"], "PASS")
            self.assertEqual(summary["runtime_bridge"]["runtime_gate"]["summary"], "passed")
            self.assertNotIn("runtime_bridge_last_completion_nonzero", summary["gate_reasons"])

    def test_run_equivalence_allows_visibility_only_barrier_family(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            specs_dir = lab_root / "specs"
            refs_dir = lab_root / "references"
            specs_dir.mkdir(parents=True)
            refs_dir.mkdir(parents=True)

            baseline_spec = specs_dir / "barrier_wfi_order_ref_snn_baseline.json"
            runtime_bridge_spec = specs_dir / "barrier_wfi_order_ref_runtime_bridge.json"
            baseline_payload = {
                "schema_version": 3,
                "platform": {"mesh_size": 4, "exec_mode": "gas", "stop": {"mode": "time", "simulation_time": "1us"}},
                "workload": {"impl": "snn", "params": {}},
                "control": {"global_step_sync_enable": False},
            }
            runtime_bridge_payload = {
                "schema_version": 3,
                "platform": {"mesh_size": 4, "exec_mode": "gas", "stop": {"mode": "time", "simulation_time": "1us"}},
                "workload": {"impl": "riscv_snn", "params": {"backend_name": "runtime_bridge"}},
                "control": {"global_step_sync_enable": False},
            }
            baseline_spec.write_text(json.dumps(baseline_payload), encoding="utf-8")
            runtime_bridge_spec.write_text(json.dumps(runtime_bridge_payload), encoding="utf-8")

            def write_run_dir(run_dir: Path,
                              spec_payload: dict[str, object],
                              *,
                              validation_lines: list[str],
                              runtime_stats: dict[str, float]) -> None:
                (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
                (run_dir / "meta.json").write_text(
                    json.dumps(
                        {
                            "run": {
                                "run_id": run_dir.name,
                                "created_utc": "2026-03-27T00:00:00+00:00",
                                "hostname": "node1",
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                (run_dir / "inputs" / "spec.json").write_text(json.dumps(spec_payload), encoding="utf-8")
                (run_dir / "essential_summary_mesh.json").write_text(
                    json.dumps(
                        {
                            "schema_version": 2,
                            "model": {"exec_mode": "gas", "mesh_size": 4},
                            "contracts": {
                                "gas_semantic_ready_before_commit": True,
                                "gas_semantic_drain_before_scatter": True,
                            },
                            "memory": {"memory_requests": 10.0, "memory_bytes": 640.0},
                            "gas": {"windows": 2, "windows_done": 2},
                            "step": {"global_steps_done": 0},
                            "snn_tx": {"spike_packets_total": 4.0},
                            "snn_rx": {"spike_packets_total": 4.0},
                        }
                    ),
                    encoding="utf-8",
                )
                (run_dir / "validation.log").write_text(
                    "\n".join(validation_lines) + "\n",
                    encoding="utf-8",
                )
                with (run_dir / "mesh_stats.csv").open("w", encoding="utf-8") as handle:
                    handle.write(
                        "ComponentName,StatisticName,StatisticSubId,StatisticType,SimTime,Rank,Sum.u64,SumSQ.u64,Count.u64,Min.u64,Max.u64,Sum.f64,SumSQ.f64,Min.f64,Max.f64\n"
                    )
                    for name, value in runtime_stats.items():
                        handle.write(
                            f"core0,{name},0,Accumulator,0 ns,0,{int(value)},0,1,{int(value)},{int(value)},0,0,0,0\n"
                        )

            baseline_run = td_path / "baseline-run"
            bridge_run = td_path / "runtime-bridge-run"
            write_run_dir(
                baseline_run,
                baseline_payload,
                validation_lines=[
                    "[val] FAIL step_activation.invocations_vs_windows: invocations=51 windows=59",
                    "[val] SUMMARY run_dir=/tmp/fake-run fail=1 warn=0 strict=0",
                ],
                runtime_stats={},
            )
            write_run_dir(
                bridge_run,
                runtime_bridge_payload,
                validation_lines=[
                    "[val] SUMMARY run_dir=/tmp/fake-run fail=0 warn=0 strict=0",
                ],
                runtime_stats={
                    "riscv_snn_workload_selected": 1.0,
                    "riscv_snn_backend_runtime_bridge": 1.0,
                    "riscv_snn_firmware_loaded": 1.0,
                    "riscv_snn_firmware_started_count": 1.0,
                    "riscv_snn_backend_runtime_bridge_provider_bound": 1.0,
                    "riscv_snn_fused_step_completion_count": 0.0,
                    "riscv_snn_completion_visible_count": 1.0,
                    "riscv_snn_completion_consumed_count": 0.0,
                    "riscv_snn_fault_count": 1.0,
                    "riscv_snn_last_completion_status": 1.0,
                    "riscv_snn_last_fault_csr": 260.0,
                },
            )

            class EquivRunner(FakeRunner):
                def __init__(self) -> None:
                    super().__init__()
                    self.run_dirs = [baseline_run, bridge_run]

                def __call__(self, cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
                    self.calls.append((cmd, cwd))
                    if any(str(part).endswith("run_mesh_with_time.sh") for part in cmd):
                        run_dir = self.run_dirs.pop(0)
                        return subprocess.CompletedProcess(
                            cmd,
                            0,
                            stdout=f"[mesh] run complete: {run_dir}\n",
                            stderr="",
                        )
                    return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")

            summary = riscv_snn_lab.run_equivalence(
                "barrier_wfi_order_ref",
                lab_root=lab_root,
                runner=EquivRunner(),
            )

            self.assertEqual(summary["status"], "PASS")
            self.assertEqual(summary["baseline"]["equiv_validation"]["summary"], "passed_with_waiver")
            self.assertEqual(summary["runtime_bridge"]["runtime_gate"]["summary"], "passed")
            self.assertEqual(summary["gate_reasons"], [])

    def test_run_equivalence_warns_when_transport_visibility_gap_is_present(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            lab_root = td_path / "riscv_snn_isa_lab"
            specs_dir = lab_root / "specs"
            refs_dir = lab_root / "references"
            specs_dir.mkdir(parents=True)
            refs_dir.mkdir(parents=True)

            baseline_spec = specs_dir / "external_dyn_desc_ref_snn_baseline.json"
            runtime_bridge_spec = specs_dir / "external_dyn_desc_ref_runtime_bridge.json"
            baseline_payload = {
                "schema_version": 3,
                "platform": {"mesh_size": 4, "exec_mode": "gas", "stop": {"mode": "time", "simulation_time": "1us"}},
                "workload": {"impl": "snn", "params": {}},
                "control": {"global_step_sync_enable": False},
            }
            runtime_bridge_payload = {
                "schema_version": 3,
                "platform": {"mesh_size": 4, "exec_mode": "gas", "stop": {"mode": "time", "simulation_time": "1us"}},
                "workload": {"impl": "riscv_snn", "params": {"backend_name": "runtime_bridge"}},
                "control": {"global_step_sync_enable": False},
            }
            baseline_spec.write_text(json.dumps(baseline_payload), encoding="utf-8")
            runtime_bridge_spec.write_text(json.dumps(runtime_bridge_payload), encoding="utf-8")

            def write_run_dir(run_dir: Path,
                              spec_payload: dict[str, object],
                              *,
                              summary_payload: dict[str, object],
                              runtime_stats: dict[str, float]) -> None:
                (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
                (run_dir / "meta.json").write_text(
                    json.dumps(
                        {
                            "run": {
                                "run_id": run_dir.name,
                                "created_utc": "2026-03-26T00:00:00+00:00",
                                "hostname": "node1",
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                (run_dir / "inputs" / "spec.json").write_text(json.dumps(spec_payload), encoding="utf-8")
                (run_dir / "essential_summary_mesh.json").write_text(
                    json.dumps(summary_payload),
                    encoding="utf-8",
                )
                (run_dir / "validation.log").write_text(
                    "[val] SUMMARY run_dir=/tmp/fake-run fail=0 warn=0 strict=0\n",
                    encoding="utf-8",
                )
                with (run_dir / "mesh_stats.csv").open("w", encoding="utf-8") as handle:
                    handle.write(
                        "ComponentName,StatisticName,StatisticSubId,StatisticType,SimTime,Rank,Sum.u64,SumSQ.u64,Count.u64,Min.u64,Max.u64,Sum.f64,SumSQ.f64,Min.f64,Max.f64\n"
                    )
                    for name, value in runtime_stats.items():
                        handle.write(
                            f"core0,{name},0,Accumulator,0 ns,0,{int(value)},0,1,{int(value)},{int(value)},0,0,0,0\n"
                        )

            baseline_run = td_path / "baseline-run"
            bridge_run = td_path / "runtime-bridge-run"
            baseline_summary = {
                "schema_version": 2,
                "model": {"exec_mode": "gas", "mesh_size": 4},
                "contracts": {
                    "gas_semantic_ready_before_commit": True,
                    "gas_semantic_drain_before_scatter": True,
                },
                "memory": {"memory_requests": 10.0, "memory_bytes": 640.0},
                "gas": {"windows": 2, "windows_done": 2},
                "step": {"global_steps_done": 1},
                "snn_tx": {"spike_packets_total": 7.0},
                "snn_rx": {"spike_packets_total": 5.0},
            }
            bridge_summary = {
                "schema_version": 2,
                "model": {"exec_mode": "gas", "mesh_size": 4},
                "contracts": {
                    "gas_semantic_ready_before_commit": True,
                    "gas_semantic_drain_before_scatter": True,
                },
                "memory": {"memory_requests": 10.0, "memory_bytes": 640.0},
                "gas": {"windows": 2, "windows_done": 2},
                "step": {"global_steps_done": 1},
            }
            write_run_dir(baseline_run, baseline_payload, summary_payload=baseline_summary, runtime_stats={})
            write_run_dir(
                bridge_run,
                runtime_bridge_payload,
                summary_payload=bridge_summary,
                runtime_stats={
                    "riscv_snn_workload_selected": 1.0,
                    "riscv_snn_backend_runtime_bridge": 1.0,
                    "riscv_snn_firmware_loaded": 1.0,
                    "riscv_snn_firmware_started_count": 1.0,
                    "riscv_snn_backend_runtime_bridge_provider_bound": 1.0,
                    "riscv_snn_fused_step_completion_count": 1.0,
                    "riscv_snn_completion_visible_count": 1.0,
                    "riscv_snn_completion_consumed_count": 1.0,
                    "riscv_snn_fault_count": 0.0,
                    "riscv_snn_last_completion_status": 0.0,
                    "riscv_snn_last_fault_csr": 0.0,
                },
            )

            class EquivRunner(FakeRunner):
                def __init__(self) -> None:
                    super().__init__()
                    self.run_dirs = [baseline_run, bridge_run]

                def __call__(self, cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
                    self.calls.append((cmd, cwd))
                    if any(str(part).endswith("run_mesh_with_time.sh") for part in cmd):
                        run_dir = self.run_dirs.pop(0)
                        return subprocess.CompletedProcess(
                            cmd,
                            0,
                            stdout=f"[mesh] run complete: {run_dir}\n",
                            stderr="",
                        )
                    return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")

            summary = riscv_snn_lab.run_equivalence(
                "external_dyn_desc_ref",
                lab_root=lab_root,
                runner=EquivRunner(),
            )

            self.assertEqual(summary["status"], "WARN")
            self.assertIn("trend_visibility_gap:snn_tx.spike_packets_total", summary["gate_reasons"])
            self.assertIn("trend_visibility_gap:snn_rx.spike_packets_total", summary["gate_reasons"])
            self.assertEqual(summary["compare"]["trend_overview"]["status"], "passed_with_warning")

    def test_runtime_bridge_statistics_export_contract_is_present(self) -> None:
        header_path = (
            riscv_snn_lab.REPO_ROOT
            / "sst_workspace"
            / "sst-elements"
            / "src"
            / "sst"
            / "elements"
            / "SnnDL"
            / "control"
            / "SnnPESubComponent.h"
        )
        cc_path = header_path.with_suffix(".cc")
        header = header_path.read_text(encoding="utf-8")
        cc = cc_path.read_text(encoding="utf-8")

        for stat in (
            "riscv_snn_firmware_elf_present",
            "riscv_snn_firmware_loaded",
            "riscv_snn_backend_runtime_bridge",
            "riscv_snn_firmware_started_count",
            "riscv_snn_submitted_commands",
            "riscv_snn_accepted_commands",
            "riscv_snn_completion_visible_count",
            "riscv_snn_completion_consumed_count",
            "riscv_snn_fused_step_completion_count",
            "riscv_snn_fault_count",
            "riscv_snn_last_completion_status",
            "riscv_snn_last_fault_csr",
            "riscv_snn_backend_runtime_bridge_provider_bound",
        ):
            member = f"stat_{stat}_"
            self.assertIn(f'{{"{stat}"', header, msg=f"missing statistic documentation for {stat}")
            self.assertIn(member, header, msg=f"missing statistic pointer for {stat}")
            self.assertIn(
                f'registerStatistic<uint64_t>("{stat}")',
                cc,
                msg=f"missing statistic registration for {stat}",
            )
            self.assertTrue(
                (
                    f'add_core_stat("{stat}", {member});' in cc
                    or f'add_core_stat_allow_zero("{stat}", {member});' in cc
                ),
                msg=f"missing finish-phase export for {stat}",
            )

    def test_runtime_bridge_statistics_export_contract_keeps_zero_visible(self) -> None:
        cc_path = (
            riscv_snn_lab.REPO_ROOT
            / "sst_workspace"
            / "sst-elements"
            / "src"
            / "sst"
            / "elements"
            / "SnnDL"
            / "control"
            / "SnnPESubComponent.cc"
        )
        cc = cc_path.read_text(encoding="utf-8")

        self.assertIn("add_core_stat_allow_zero", cc)
        for stat in (
            "riscv_snn_firmware_elf_present",
            "riscv_snn_firmware_loaded",
            "riscv_snn_backend_runtime_bridge",
            "riscv_snn_firmware_started_count",
            "riscv_snn_submitted_commands",
            "riscv_snn_accepted_commands",
            "riscv_snn_completion_visible_count",
            "riscv_snn_completion_consumed_count",
            "riscv_snn_fused_step_completion_count",
            "riscv_snn_fault_count",
            "riscv_snn_last_completion_status",
            "riscv_snn_last_fault_csr",
            "riscv_snn_backend_runtime_bridge_provider_bound",
        ):
            member = f"stat_{stat}_"
            self.assertIn(
                f'add_core_stat_allow_zero("{stat}", {member});',
                cc,
                msg=f"missing zero-preserving finish export for {stat}",
            )

    def test_riscv_snn_selection_stat_is_exported_directly_from_workload_choice(self) -> None:
        header_path = (
            riscv_snn_lab.REPO_ROOT
            / "sst_workspace"
            / "sst-elements"
            / "src"
            / "sst"
            / "elements"
            / "SnnDL"
            / "control"
            / "SnnPESubComponent.h"
        )
        cc_path = header_path.with_suffix(".cc")
        header = header_path.read_text(encoding="utf-8")
        cc = cc_path.read_text(encoding="utf-8")

        self.assertIn(
            '{"riscv_snn_workload_selected"',
            header,
            msg="missing statistic documentation for riscv_snn_workload_selected",
        )
        self.assertIn(
            "stat_riscv_snn_workload_selected_",
            header,
            msg="missing statistic pointer for riscv_snn_workload_selected",
        )
        self.assertIn(
            'registerStatistic<uint64_t>("riscv_snn_workload_selected")',
            cc,
            msg="missing statistic registration for riscv_snn_workload_selected",
        )
        self.assertIn(
            "const uint64_t riscv_snn_workload_selected = isRiscvSnnWorkload_() ? 1ull : 0ull;",
            cc,
            msg="selection stat should be derived directly from workload_impl_",
        )
        self.assertIn(
            "stat_riscv_snn_workload_selected_->addData(riscv_snn_workload_selected);",
            cc,
            msg="selection stat should be emitted directly, independent of workload runtime counters",
        )

    def test_runtime_bridge_statistics_export_contract_bridges_workload_stats_under_compute_core(self) -> None:
        cc_path = (
            riscv_snn_lab.REPO_ROOT
            / "sst_workspace"
            / "sst-elements"
            / "src"
            / "sst"
            / "elements"
            / "SnnDL"
            / "control"
            / "SnnPESubComponent.cc"
        )
        cc = cc_path.read_text(encoding="utf-8")

        self.assertIn("workload_->getStatistics(workload_stats);", cc)
        self.assertIn(
            'add_workload_stat_allow_zero("riscv_snn_firmware_elf_present", stat_riscv_snn_firmware_elf_present_);',
            cc,
        )
        self.assertIn(
            'add_workload_stat_allow_zero("riscv_snn_firmware_loaded", stat_riscv_snn_firmware_loaded_);',
            cc,
        )
        self.assertIn(
            'add_workload_stat_allow_zero("riscv_snn_backend_runtime_bridge", stat_riscv_snn_backend_runtime_bridge_);',
            cc,
        )
        self.assertIn(
            'add_workload_stat_allow_zero("riscv_snn_firmware_started_count", stat_riscv_snn_firmware_started_count_);',
            cc,
        )
        self.assertIn(
            'add_workload_stat_allow_zero("riscv_snn_submitted_commands", stat_riscv_snn_submitted_commands_);',
            cc,
        )
        self.assertIn(
            'add_workload_stat_allow_zero("riscv_snn_accepted_commands", stat_riscv_snn_accepted_commands_);',
            cc,
        )
        self.assertIn(
            'add_workload_stat_allow_zero("riscv_snn_completion_visible_count", stat_riscv_snn_completion_visible_count_);',
            cc,
        )
        self.assertIn(
            'add_workload_stat_allow_zero("riscv_snn_fused_step_completion_count", stat_riscv_snn_fused_step_completion_count_);',
            cc,
        )
        self.assertIn(
            'add_workload_stat_allow_zero("riscv_snn_backend_runtime_bridge_provider_bound", stat_riscv_snn_backend_runtime_bridge_provider_bound_);',
            cc,
        )

    def test_runtime_bridge_statistics_export_contract_reaches_multicore_pe_aggregation_surface(self) -> None:
        multicore_header_path = (
            riscv_snn_lab.REPO_ROOT
            / "sst_workspace"
            / "sst-elements"
            / "src"
            / "sst"
            / "elements"
            / "SnnDL"
            / "components"
            / "MultiCorePE.h"
        )
        multicore_cc_path = multicore_header_path.with_suffix(".cc")
        core_cc_path = (
            riscv_snn_lab.REPO_ROOT
            / "sst_workspace"
            / "sst-elements"
            / "src"
            / "sst"
            / "elements"
            / "SnnDL"
            / "control"
            / "SnnPESubComponent.cc"
        )
        multicore_header = multicore_header_path.read_text(encoding="utf-8")
        multicore_cc = multicore_cc_path.read_text(encoding="utf-8")
        core_cc = core_cc_path.read_text(encoding="utf-8")

        self.assertIn("void accumulateRiscvSnnRuntimeStats(", multicore_header)
        self.assertIn("void MultiCorePE::accumulateRiscvSnnRuntimeStats(", multicore_cc)
        self.assertIn("accumulateRiscvSnnRuntimeStats(", core_cc)
        self.assertGreaterEqual(
            core_cc.count("mc_pe->accumulateRiscvSnnRuntimeStats("),
            2,
            msg="riscv_snn runtime stats should aggregate through both impl_ and workload_-only finish paths",
        )

        for stat in (
            "riscv_snn_workload_selected",
            "riscv_snn_firmware_elf_present",
            "riscv_snn_firmware_loaded",
            "riscv_snn_backend_runtime_bridge",
            "riscv_snn_firmware_started_count",
            "riscv_snn_submitted_commands",
            "riscv_snn_accepted_commands",
            "riscv_snn_completion_visible_count",
            "riscv_snn_completion_consumed_count",
            "riscv_snn_fused_step_completion_count",
            "riscv_snn_fault_count",
            "riscv_snn_last_completion_status",
            "riscv_snn_last_fault_csr",
            "riscv_snn_backend_runtime_bridge_provider_bound",
        ):
            self.assertIn(f'{{"{stat}"', multicore_header, msg=f"missing PE statistic doc for {stat}")
            self.assertIn(
                f'registerStatistic<uint64_t>("{stat}")',
                multicore_cc,
                msg=f"missing PE statistic registration for {stat}",
            )
            self.assertIn(
                f"stat_{stat}_",
                multicore_header,
                msg=f"missing PE statistic pointer for {stat}",
            )

        self.assertIn(
            "uint64_t workload_selected,",
            multicore_header,
            msg="PE aggregation signature should include workload selection stat",
        )
        self.assertIn(
            "if (stat_riscv_snn_workload_selected_) {",
            multicore_cc,
            msg="PE aggregation should export workload selection stat",
        )

    def test_runtime_bridge_bringup_statistics_source_contract_is_present(self) -> None:
        workload_header_path = (
            riscv_snn_lab.REPO_ROOT
            / "sst_workspace"
            / "sst-elements"
            / "src"
            / "sst"
            / "elements"
            / "SnnDL"
            / "services"
            / "workload"
            / "riscv_snn"
            / "RiscvSnnWorkload.h"
        )
        workload_cc_path = workload_header_path.with_suffix(".cc")
        backend_cc_path = workload_header_path.with_name("RiscvSnnRuntimeBridgeBackend.cc")
        workload_header = workload_header_path.read_text(encoding="utf-8")
        workload_cc = workload_cc_path.read_text(encoding="utf-8")
        backend_cc = backend_cc_path.read_text(encoding="utf-8")

        self.assertIn("uint64_t firmware_started_count_ = 0;", workload_header)
        self.assertIn("firmware_started_count_", workload_cc)
        self.assertIn('stats["riscv_snn_firmware_elf_present"]', workload_cc)
        self.assertIn('stats["riscv_snn_firmware_loaded"]', workload_cc)
        self.assertIn('stats["riscv_snn_backend_runtime_bridge"]', workload_cc)
        self.assertIn('stats["riscv_snn_firmware_started_count"]', workload_cc)
        self.assertIn('stats["riscv_snn_submitted_commands"]', workload_cc)
        self.assertIn('stats["riscv_snn_accepted_commands"]', workload_cc)
        self.assertIn(
            'stats["riscv_snn_backend_runtime_bridge_provider_bound"]',
            backend_cc,
        )

    def test_runtime_bridge_bringup_statistics_are_visible_in_lab_summary_surface(self) -> None:
        for stat in (
            "riscv_snn_workload_selected",
            "riscv_snn_firmware_elf_present",
            "riscv_snn_firmware_loaded",
            "riscv_snn_backend_runtime_bridge",
            "riscv_snn_firmware_started_count",
            "riscv_snn_submitted_commands",
            "riscv_snn_accepted_commands",
            "riscv_snn_completion_visible_count",
            "riscv_snn_backend_runtime_bridge_provider_bound",
        ):
            self.assertIn(stat, riscv_snn_lab.RUNTIME_BRIDGE_RUNTIME_STATS)


if __name__ == "__main__":
    unittest.main()
