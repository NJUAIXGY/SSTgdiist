from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .program_profile_model import ProgramProfileModel, runtime_summary_from_program_request


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_mesh_stat_totals(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}
    totals: dict[str, float] = {}
    with path.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            name = row.get("StatisticName", "")
            if not name:
                continue
            value = row.get("Sum.u64") or row.get("Sum.f64") or "0"
            try:
                totals[name] = totals.get(name, 0.0) + float(value)
            except ValueError:
                continue
    return totals


def _validation_summary(run_dir: Path) -> dict[str, Any]:
    log_path = run_dir / "validation.log"
    if not log_path.exists():
        return {
            "summary": "not_run",
            "pass_lines": [],
            "warn_lines": [],
            "fail_lines": [],
        }
    lines = log_path.read_text(encoding="utf-8").splitlines()
    summary = "unknown"
    passes: list[str] = []
    warns: list[str] = []
    fails: list[str] = []
    for line in lines:
        stripped = line.strip()
        if " PASS " in line:
            passes.append(stripped)
        if " WARN " in line:
            warns.append(stripped)
        if " FAIL " in line:
            fails.append(stripped)
        if " SUMMARY " in line:
            if "fail=0 warn=0" in line:
                summary = "passed"
            elif "fail=0" in line:
                summary = "passed_with_warning"
            else:
                summary = "failed"
    return {
        "summary": summary,
        "pass_lines": passes,
        "warn_lines": warns,
        "fail_lines": fails,
    }


@dataclass(frozen=True)
class ProgramEvidenceModel:
    contract_name: str
    contract_version: str
    source_kinds: tuple[str, ...]
    required_artifacts: tuple[str, ...]
    required_summary_sections: tuple[str, ...]
    required_runtime_stats: tuple[str, ...]
    control_event_projection: dict[str, dict[str, Any]]
    profile_model: ProgramProfileModel
    known_control_events: tuple[str, ...]

    @classmethod
    def from_authority(cls, authority: dict[str, Any]) -> "ProgramEvidenceModel":
        required_sections = (
            "program_runtime_evidence_contract",
            "program_control_event_taxonomy",
            "program_semantic_profiles",
            "memory_taxonomy",
            "fabric_taxonomy",
            "fused_step_state_machine",
        )
        missing_sections = [section for section in required_sections if section not in authority]
        if missing_sections:
            raise ValueError(
                "missing required program evidence authority sections: "
                + ", ".join(missing_sections)
            )

        contract = dict(authority.get("program_runtime_evidence_contract") or {})
        contract_name = str(contract.get("contract_name") or "").strip()
        contract_version = str(contract.get("contract_version") or "").strip()
        if not contract_name or not contract_version:
            raise ValueError("program_runtime_evidence_contract missing contract_name/version")

        source_kinds = tuple(
            str(row.get("name") or "").strip()
            for row in list(contract.get("source_kinds") or [])
            if str(row.get("name") or "").strip()
        )
        if not source_kinds:
            raise ValueError("program_runtime_evidence_contract.source_kinds must not be empty")

        required_artifacts = tuple(
            str(value).strip()
            for value in list(contract.get("required_artifacts") or [])
            if str(value).strip()
        )
        required_summary_sections = tuple(
            str(value).strip()
            for value in list(contract.get("required_summary_sections") or [])
            if str(value).strip()
        )
        required_runtime_stats = tuple(
            str(value).strip()
            for value in list(contract.get("required_runtime_stats") or [])
            if str(value).strip()
        )
        if not required_runtime_stats:
            raise ValueError("program_runtime_evidence_contract.required_runtime_stats must not be empty")

        known_control_events = tuple(
            str(event.get("name") or "").strip()
            for event in list(
                ((authority.get("program_control_event_taxonomy") or {}).get("events")) or []
            )
            if str(event.get("name") or "").strip()
        )
        control_event_projection = {
            str(name): dict(payload or {})
            for name, payload in dict(contract.get("control_event_projection") or {}).items()
            if str(name).strip()
        }
        for event_name in control_event_projection:
            if event_name not in set(known_control_events):
                raise ValueError(f"unknown control event in evidence contract: {event_name}")

        return cls(
            contract_name=contract_name,
            contract_version=contract_version,
            source_kinds=source_kinds,
            required_artifacts=required_artifacts,
            required_summary_sections=required_summary_sections,
            required_runtime_stats=required_runtime_stats,
            control_event_projection=control_event_projection,
            profile_model=ProgramProfileModel.from_authority(authority),
            known_control_events=known_control_events,
        )

    def extract_from_run_dir(
        self,
        *,
        family: str,
        profile_name: str,
        family_policy: dict[str, Any] | None,
        run_dir: Path,
        source_kind: str,
        source_origin: str,
        program_name: str | None = None,
    ) -> dict[str, Any]:
        resolved_source_kind = str(source_kind or "").strip()
        if resolved_source_kind not in set(self.source_kinds):
            raise ValueError(f"unknown program evidence source kind: {resolved_source_kind}")

        resolved_run_dir = Path(run_dir).resolve()
        missing_artifacts = [
            artifact for artifact in self.required_artifacts if not (resolved_run_dir / artifact).exists()
        ]
        summary = (
            _load_json(resolved_run_dir / "essential_summary_mesh.json")
            if "essential_summary_mesh.json" not in missing_artifacts
            else {}
        )
        meta = _load_json(resolved_run_dir / "meta.json") if (resolved_run_dir / "meta.json").exists() else {}
        input_spec = (
            _load_json(resolved_run_dir / "inputs" / "spec.json")
            if (resolved_run_dir / "inputs" / "spec.json").exists()
            else {}
        )
        runtime_stats = _extract_mesh_stat_totals(resolved_run_dir / "mesh_stats.csv")
        validation = _validation_summary(resolved_run_dir)

        missing_summary_sections = [
            section for section in self.required_summary_sections if section not in summary
        ]
        missing_runtime_stats = [
            stat_name for stat_name in self.required_runtime_stats if stat_name not in runtime_stats
        ]

        request = self.profile_model.build_request(
            family=family,
            profile_name=profile_name,
            family_policy=family_policy,
        )
        runtime_summary = runtime_summary_from_program_request(request)
        runtime_summary.update(
            {
                "evidence_source_kind": resolved_source_kind,
                "evidence_source_path": str(resolved_run_dir),
                "evidence_origin": str(source_origin or ""),
                "evidence_contract_name": self.contract_name,
                "evidence_contract_version": self.contract_version,
            }
        )

        control_event_observations: list[dict[str, Any]] = []
        for event_name in self.known_control_events:
            projection = dict(self.control_event_projection.get(event_name) or {})
            evidence_mode = str(projection.get("evidence_mode") or "profile_control_event")
            observation: dict[str, Any] = {
                "event_name": event_name,
                "evidence_mode": evidence_mode,
                "supported": False,
            }
            if evidence_mode == "runtime_stat_nonzero":
                stat_name = str(projection.get("runtime_stat") or "").strip()
                observed_count = int(runtime_stats.get(stat_name, 0) or 0)
                observation["runtime_stat"] = stat_name
                observation["observed_count"] = observed_count
                observation["supported"] = observed_count > 0
            else:
                projected_count = sum(
                    1
                    for step in list(runtime_summary.get("steps", []) or [])
                    if event_name in list(step.get("control_events", []) or [])
                )
                observation["projected_profile"] = profile_name
                observation["projected_count"] = projected_count
                observation["supported"] = projected_count > 0
            control_event_observations.append(observation)

        evidence_gate_reasons: list[str] = []
        evidence_gate_reasons.extend(
            f"missing_artifact:{artifact}" for artifact in missing_artifacts
        )
        evidence_gate_reasons.extend(
            f"missing_summary_section:{section}" for section in missing_summary_sections
        )
        evidence_gate_reasons.extend(
            f"missing_runtime_stat:{stat_name}" for stat_name in missing_runtime_stats
        )
        if validation.get("summary") in {"failed", "not_run", "unknown"}:
            evidence_gate_reasons.append(f"validation:{validation.get('summary')}")

        return {
            "family": family,
            "program_name": program_name or family,
            "reference_program_profile": profile_name,
            "source_kind": resolved_source_kind,
            "source_origin": str(source_origin or ""),
            "evidence_source_path": str(resolved_run_dir),
            "evidence_contract_name": self.contract_name,
            "evidence_contract_version": self.contract_version,
            "summary_sections_present": [
                section for section in self.required_summary_sections if section in summary
            ],
            "missing_artifacts": missing_artifacts,
            "missing_summary_sections": missing_summary_sections,
            "runtime_stats": {
                stat_name: runtime_stats.get(stat_name)
                for stat_name in self.required_runtime_stats
                if stat_name in runtime_stats
            },
            "missing_runtime_stats": missing_runtime_stats,
            "validation": validation,
            "meta": meta,
            "input_spec": input_spec,
            "control_event_observations": control_event_observations,
            "evidence_ok": not evidence_gate_reasons,
            "evidence_gate_reasons": evidence_gate_reasons,
            "runtime_program_summary": runtime_summary,
        }
