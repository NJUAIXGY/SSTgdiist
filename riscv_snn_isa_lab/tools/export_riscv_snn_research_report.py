#!/usr/bin/env python3
import argparse
import datetime
import json
from pathlib import Path
from typing import Any

FULL_EQUIVALENCE_VALIDATION_FIELDS = (
    "latest_summary_path",
    "latest_date",
    "entry_count",
    "all_ok_latest",
    "all_dates_ok",
    "first_fail_date",
    "latest_recovered_date",
    "history_contract",
    "excluded_entry_count",
)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _surface_label(canonical_surface: Any) -> str:
    return "canonical" if bool(canonical_surface) else "subset"


def _surface_summary(ref: dict[str, Any] | None,
                     loaded: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if not ref and not loaded:
        return None
    payload = loaded or ref or {}
    summary_path = payload.get("summary_path")
    if summary_path is None and ref:
        summary_path = ref.get("summary_path")
    canonical_surface = payload.get("canonical_surface")
    if canonical_surface is None and ref:
        canonical_surface = ref.get("canonical_surface")
    requested_group = payload.get("requested_group")
    if requested_group is None and ref:
        requested_group = ref.get("requested_group")
    count = payload.get("count")
    if count is None and ref:
        count = ref.get("count")
    return {
        "summary_path": summary_path,
        "canonical_surface": bool(canonical_surface),
        "surface": _surface_label(canonical_surface),
        "requested_group": requested_group,
        "count": count,
    }


def _rollup_summary(ref: dict[str, Any] | None,
                    loaded: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if not ref and not loaded:
        return None
    payload = loaded or ref or {}
    summary_path = payload.get("summary_path")
    if summary_path is None and ref:
        summary_path = ref.get("summary_path")
    latest_date = payload.get("latest_date")
    if latest_date is None and ref:
        latest_date = ref.get("latest_date")
    entry_count = payload.get("entry_count")
    if entry_count is None and ref:
        entry_count = ref.get("entry_count")
    all_ok_latest = payload.get("all_ok_latest")
    if all_ok_latest is None and ref:
        all_ok_latest = ref.get("all_ok_latest")
    return {
        "summary_path": summary_path,
        "latest_date": latest_date,
        "entry_count": entry_count,
        "all_ok_latest": all_ok_latest,
    }


def _observer_rollup_summary(observer_surface: dict[str, Any] | None) -> dict[str, Any] | None:
    if not observer_surface:
        return None
    return {
        "summary_path": observer_surface.get("history_path") or observer_surface.get("summary_path"),
        "latest_summary_path": observer_surface.get("latest_summary_path"),
        "latest_date": observer_surface.get("latest_date"),
        "entry_count": observer_surface.get("entry_count"),
        "all_ok_latest": observer_surface.get("all_ok_latest"),
        "all_dates_ok": observer_surface.get("all_dates_ok"),
        "first_fail_date": observer_surface.get("first_fail_date"),
        "latest_recovered_date": observer_surface.get("latest_recovered_date"),
        "history_contract": observer_surface.get("history_contract"),
        "excluded_entry_count": observer_surface.get("excluded_entry_count"),
    }


def _observer_adequacy_summary(observer_entrypoint: dict[str, Any] | None,
                               full_rollup: dict[str, Any] | None) -> dict[str, Any]:
    has_observer_entrypoint = bool(observer_entrypoint and observer_entrypoint.get("summary_path"))
    contract_ok = bool(
        has_observer_entrypoint
        and observer_entrypoint.get("artifact_role") == "stable_sidecar_observer_summary"
        and observer_entrypoint.get("authority_scope") == "observer_surface_only"
    )
    required_full_keys = (
        "summary_path",
        "latest_summary_path",
        "latest_date",
        "entry_count",
        "all_ok_latest",
        "all_dates_ok",
        "first_fail_date",
        "latest_recovered_date",
        "history_contract",
        "excluded_entry_count",
    )
    full_rollup = full_rollup or {}
    full_equivalence_markers_present = all(key in full_rollup for key in required_full_keys)
    real_fail_sample_present = full_rollup.get("first_fail_date") is not None
    real_recovery_sample_present = full_rollup.get("latest_recovered_date") is not None

    status = "incomplete_missing_observer_entrypoint"
    next_action = "export_stable_observer_summary_first"
    if has_observer_entrypoint and not contract_ok:
        status = "incomplete_invalid_observer_contract"
        next_action = "repair_observer_entrypoint_contract"
    elif contract_ok and not full_equivalence_markers_present:
        status = "incomplete_missing_full_equivalence_markers"
        next_action = "add_full_equivalence_health_markers_to_observer_surface"
    elif contract_ok and full_equivalence_markers_present:
        if real_fail_sample_present and real_recovery_sample_present:
            status = "ready_with_fail_recovery_sample"
            next_action = "validate_compact_surface_against_real_fail_recovery_sample"
        elif real_fail_sample_present:
            status = "ready_with_fail_sample_only"
            next_action = "wait_for_recovery_or_validate_fail_only_surface"
        else:
            status = "ready_waiting_for_real_sample"
            next_action = "wait_for_real_canonical_fail_recovery_sample"

    return {
        "has_observer_entrypoint": has_observer_entrypoint,
        "contract_ok": contract_ok,
        "full_equivalence_markers_present": full_equivalence_markers_present,
        "real_fail_sample_present": real_fail_sample_present,
        "real_recovery_sample_present": real_recovery_sample_present,
        "status": status,
        "next_action": next_action,
    }


def _require_stable_sidecar_report(report: dict[str, Any], sidecar_path: Path) -> None:
    if report.get("artifact_role") != "stable_top_level_gate":
        raise ValueError(f"research report requires stable sidecar authority report: {sidecar_path}")
    if report.get("authority_scope") != "experimental_gate_authority":
        raise ValueError(f"research report requires experimental_gate_authority sidecar: {sidecar_path}")


def _require_stable_observer_summary(observer: dict[str, Any], observer_path: Path) -> None:
    if observer.get("artifact_role") != "stable_sidecar_observer_summary":
        raise ValueError(f"research report requires stable observer summary: {observer_path}")
    if observer.get("authority_scope") != "observer_surface_only":
        raise ValueError(f"research report requires observer_surface_only observer summary: {observer_path}")


def _observer_entrypoint_from_summary(observer_summary: dict[str, Any], observer_path: Path) -> dict[str, Any]:
    return {
        "summary_path": str(observer_path),
        "artifact_role": observer_summary.get("artifact_role"),
        "authority_scope": observer_summary.get("authority_scope"),
        "policy": "follow_stable_observer_summary_for_compact_optional_surface_rollups",
    }


def _load_surface_from_ref(ref: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ref:
        return None
    summary_path = str(ref.get("summary_path") or "").strip()
    if not summary_path:
        return None
    return _load_json(Path(summary_path))


def _report_optional_group_surfaces(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    optional_group_surfaces = {
        str(group): dict(payload or {})
        for group, payload in dict(report.get("optional_group_surfaces", {}) or {}).items()
        if isinstance(payload, dict)
    }
    queue_equivalence = dict(report.get("queue_equivalence") or {})
    if queue_equivalence and "queue_optional" not in optional_group_surfaces:
        optional_group_surfaces["queue_optional"] = queue_equivalence
    return optional_group_surfaces


def _observer_optional_group_rollups(observer_summary: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    payload = observer_summary or {}
    optional_group_rollups = {
        str(group): dict(row or {})
        for group, row in dict(payload.get("optional_group_rollups", {}) or {}).items()
        if isinstance(row, dict)
    }
    queue_rollup = dict((((payload.get("optional_surfaces") or {}).get("queue_equivalence")) or {}))
    if queue_rollup and "queue_optional" not in optional_group_rollups:
        optional_group_rollups["queue_optional"] = queue_rollup
    return optional_group_rollups


def _optional_group_history_path(sidecar_path: Path, group: str) -> Path:
    return sidecar_path.parent / f"{group.replace('_', '-')}-equivalence-history.json"


def _resolve_validation_context(report: dict[str, Any], report_path: Path) -> dict[str, Any]:
    artifact_role = report.get("artifact_role")
    if artifact_role == "research_metrics_summary":
        observer_entrypoint = report.get("observer_entrypoint")
        full_rollup = dict((report.get("optional_surface_rollups") or {}).get("full_equivalence") or {})
        observer_adequacy = report.get("observer_adequacy") or _observer_adequacy_summary(
            observer_entrypoint,
            full_rollup,
        )
        return {
            "source": {
                "path": str(report_path),
                "artifact_role": artifact_role,
                "authority_scope": report.get("authority_scope"),
            },
            "observer_entrypoint": observer_entrypoint,
            "full_rollup": full_rollup,
            "observer_adequacy": observer_adequacy,
        }

    if artifact_role == "stable_top_level_gate":
        _require_stable_sidecar_report(report, report_path)
        observer_summary_path = report.get("observer_summary_path")
        if not observer_summary_path:
            raise ValueError(f"observer adequacy validation requires observer_summary_path: {report_path}")
        observer_path = Path(observer_summary_path)
        observer_summary = _load_json(observer_path)
        if observer_summary is None:
            raise FileNotFoundError(f"observer summary missing: {observer_path}")
        _require_stable_observer_summary(observer_summary, observer_path)

        observer_surfaces = dict(observer_summary.get("optional_surfaces", {}) or {})
        observer_entrypoint = _observer_entrypoint_from_summary(observer_summary, observer_path)
        full_rollup = (
            _observer_rollup_summary(observer_surfaces.get("full_equivalence"))
            or _rollup_summary(report.get("full_equivalence_history"))
            or {}
        )
        observer_adequacy = _observer_adequacy_summary(observer_entrypoint, full_rollup)
        return {
            "source": {
                "path": str(report_path),
                "artifact_role": artifact_role,
                "authority_scope": report.get("authority_scope"),
            },
            "observer_entrypoint": observer_entrypoint,
            "full_rollup": full_rollup,
            "observer_adequacy": observer_adequacy,
        }

    raise ValueError(
        f"observer adequacy validation requires research report or stable sidecar report: {report_path}"
    )


def validate_observer_adequacy_report(*, report_path: Path, output_path: Path) -> Path:
    report = _load_json(report_path)
    if report is None:
        raise FileNotFoundError(f"observer adequacy validation input missing: {report_path}")

    context = _resolve_validation_context(report, report_path)
    full_rollup = dict(context.get("full_rollup") or {})
    observer_adequacy = dict(context.get("observer_adequacy") or {})
    history_path_str = full_rollup.get("summary_path")
    history = _load_json(Path(history_path_str)) if history_path_str else None

    validation_required = observer_adequacy.get("status") == "ready_with_fail_recovery_sample"
    validation_executed = False
    validation_ok: bool | None = None
    matched_field_count = 0
    mismatches: list[dict[str, Any]] = []

    if validation_required:
        validation_executed = True
        if history is None:
            mismatches.append(
                {
                    "field": "summary_path",
                    "expected": history_path_str,
                    "actual": None,
                    "ok": False,
                    "reason": "history_missing",
                }
            )
        else:
            for field in FULL_EQUIVALENCE_VALIDATION_FIELDS:
                expected = full_rollup.get(field)
                actual = history.get(field)
                ok = expected == actual
                check = {
                    "field": field,
                    "expected": expected,
                    "actual": actual,
                    "ok": ok,
                }
                if ok:
                    matched_field_count += 1
                else:
                    mismatches.append(check)
        validation_ok = not mismatches

    status = "not_ready"
    next_action = observer_adequacy.get("next_action")
    if validation_executed:
        status = "pass" if validation_ok else "fail"
        if validation_ok:
            next_action = "none"
        elif history is None:
            next_action = "materialize_or_repair_canonical_full_equivalence_history"
        else:
            next_action = "repair_compact_full_equivalence_rollup_to_match_canonical_history"

    payload = {
        "schema_version": 1,
        "artifact_role": "observer_adequacy_validation_summary",
        "authority_scope": "research_validation_only",
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source": context["source"],
        "observer_entrypoint": context.get("observer_entrypoint"),
        "observer_adequacy": observer_adequacy,
        "validation_required": validation_required,
        "validation_executed": validation_executed,
        "validation_ok": validation_ok,
        "status": status,
        "next_action": next_action,
        "history_path": history_path_str,
        "history_loaded": history is not None,
        "compact_full_equivalence_rollup": full_rollup,
        "matched_field_count": matched_field_count,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "validated_fields": list(FULL_EQUIVALENCE_VALIDATION_FIELDS),
    }
    return _write_json(output_path, payload)


def generate_research_report(*, sidecar_path: Path, output_path: Path) -> Path:
    report = _load_json(sidecar_path)
    if report is None:
        raise FileNotFoundError(f"sidecar report missing: {sidecar_path}")
    _require_stable_sidecar_report(report, sidecar_path)

    equiv_ref = report.get("equivalence", {})
    equivalence = _load_surface_from_ref(equiv_ref)

    full_equiv_ref = report.get("full_equivalence", {})
    full_equivalence = _load_surface_from_ref(full_equiv_ref)

    optional_group_surface_refs = _report_optional_group_surfaces(report)
    loaded_optional_group_surfaces = {
        group: _load_surface_from_ref(ref)
        for group, ref in sorted(optional_group_surface_refs.items())
    }
    queue_equiv_ref = optional_group_surface_refs.get("queue_optional")
    queue_equivalence = loaded_optional_group_surfaces.get("queue_optional")

    artifact_isolation_ref = report.get("artifact_isolation", {})
    artifact_isolation = _load_surface_from_ref(artifact_isolation_ref)

    full_equivalence_history_ref = report.get("full_equivalence_history", {})
    full_equivalence_history = _load_surface_from_ref(full_equivalence_history_ref)

    artifact_isolation_history_ref = report.get("artifact_isolation_history", {})
    artifact_isolation_history = _load_surface_from_ref(artifact_isolation_history_ref)

    observer_summary = None
    observer_summary_path = report.get("observer_summary_path")
    if observer_summary_path:
        observer_path = Path(observer_summary_path)
        observer_summary = _load_json(observer_path)
        if observer_summary is None:
            raise FileNotFoundError(f"observer summary missing: {observer_path}")
        _require_stable_observer_summary(observer_summary, observer_path)

    metrics: dict[str, Any] = {
        "sidecar_gate_ok": bool(report.get("gate_ok")),
        "equivalence_available": bool(equivalence),
        "equivalence_family_count": len(equivalence.get("families", [])) if equivalence else 0,
        "full_equivalence_available": bool(full_equivalence),
        "full_equivalence_family_count": len(full_equivalence.get("families", [])) if full_equivalence else 0,
    }

    research_metrics: dict[str, Any] = {}
    gate_reasons = report.get("reasons") or []
    research_metrics["sidecar_reasons"] = gate_reasons

    transit_warnings: list[str] = []
    warn_families: list[str] = []
    if equivalence:
        for family in equivalence.get("families", []):
            status = family.get("status", "").upper()
            if status in {"WARN", "FAIL"}:
                warn_families.append(family.get("family"))
            for reason in family.get("gate_reasons", []):
                if "visibility" in reason or "transport" in reason:
                    transit_warnings.append(reason)
    research_metrics["equivalence_warn_families"] = warn_families
    research_metrics["visibility_gap_reasons"] = transit_warnings

    history = report.get("history_index", {})
    drift_count = len([entry for entry in history.get("entries", []) if entry.get("drift_families")])
    research_metrics["history_drift_count"] = drift_count
    research_metrics["latest_history_date"] = history.get("latest_date")

    derived_from: list[str] = []
    derived_from.append(report.get("artifact_role", "stable_top_level_gate"))
    if observer_summary and observer_summary.get("artifact_role"):
        derived_from.append(observer_summary["artifact_role"])
    if equivalence and equivalence.get("artifact_role"):
        derived_from.append(equivalence["artifact_role"])
    for payload in loaded_optional_group_surfaces.values():
        if payload and payload.get("artifact_role"):
            derived_from.append(payload["artifact_role"])
    if artifact_isolation and artifact_isolation.get("artifact_role"):
        derived_from.append(artifact_isolation["artifact_role"])
    derived_from = list(dict.fromkeys(derived_from))

    artifact_surfaces = {
        "nightly_index": _surface_summary(report.get("nightly_index")),
        "equivalence": _surface_summary(equiv_ref, equivalence),
        "full_equivalence": _surface_summary(full_equiv_ref, full_equivalence),
        "queue_equivalence": _surface_summary(queue_equiv_ref, queue_equivalence),
    }
    optional_group_surfaces = {
        group: summary
        for group, summary in (
            (
                group,
                _surface_summary(
                    optional_group_surface_refs.get(group),
                    loaded_optional_group_surfaces.get(group),
                ),
            )
            for group in sorted(optional_group_surface_refs)
        )
        if summary is not None
    }
    observer_surfaces = dict(observer_summary.get("optional_surfaces", {}) or {}) if observer_summary else {}
    observer_group_rollups = _observer_optional_group_rollups(observer_summary)
    observer_entrypoint = (
        _observer_entrypoint_from_summary(observer_summary, Path(observer_summary_path))
        if observer_summary_path and observer_summary
        else None
    )
    optional_group_rollups = {
        str(group): _observer_rollup_summary(payload)
        for group, payload in sorted(observer_group_rollups.items())
        if _observer_rollup_summary(payload) is not None
    }
    for group in sorted(optional_group_surface_refs):
        if group in optional_group_rollups:
            continue
        history_path = _optional_group_history_path(sidecar_path, group)
        history = _load_json(history_path) if history_path.exists() else None
        group_rollup = (
            _rollup_summary(
                {"summary_path": str(history_path)},
                history,
            )
            if history
            else None
        )
        if group_rollup is not None:
            optional_group_rollups[group] = group_rollup
    optional_surface_rollups = {
        "full_equivalence": (
            _observer_rollup_summary(observer_surfaces.get("full_equivalence"))
            or _rollup_summary(full_equivalence_history_ref, full_equivalence_history)
        ),
        "artifact_isolation": (
            _observer_rollup_summary(observer_surfaces.get("artifact_isolation"))
            or _rollup_summary(artifact_isolation_history_ref, artifact_isolation_history)
        ),
        "queue_equivalence": (
            optional_group_rollups.get("queue_optional")
        ),
    }
    research_summary = {
        "schema_version": 1,
        "artifact_role": "research_metrics_summary",
        "authority_scope": "research_metrics_only",
        "authority_entrypoint": {
            "summary_path": str(sidecar_path),
            "artifact_role": report.get("artifact_role"),
            "authority_scope": report.get("authority_scope"),
            "policy": "derive_optional_surfaces_from_stable_sidecar_report",
        },
        "observer_entrypoint": observer_entrypoint,
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "profile": "riscv_snn_barrier-family",
        "metrics": metrics,
        "research_metrics": research_metrics,
        "artifact_surfaces": artifact_surfaces,
        "artifact_isolation": {
            "summary_path": artifact_isolation.get("summary_path") if artifact_isolation else artifact_isolation_ref.get("summary_path"),
            "all_ok": artifact_isolation.get("all_ok") if artifact_isolation else artifact_isolation_ref.get("all_ok"),
            "surfaces": artifact_isolation.get("surfaces") if artifact_isolation else artifact_isolation_ref.get("surfaces"),
        } if artifact_isolation or artifact_isolation_ref else None,
        "supplementary_surfaces": {
            str(name): dict(payload or {})
            for name, payload in dict(report.get("supplementary_surfaces") or {}).items()
            if isinstance(payload, dict)
        },
        "optional_group_surfaces": optional_group_surfaces,
        "optional_group_rollups": optional_group_rollups,
        "optional_surface_rollups": optional_surface_rollups,
        "observer_adequacy": _observer_adequacy_summary(
            observer_entrypoint,
            optional_surface_rollups.get("full_equivalence"),
        ),
        "derived_from": derived_from,
    }

    return _write_json(output_path, research_summary)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="export_riscv_snn_research_report.py",
        description="Produce a research metrics summary for the riscv_snn experimental gate",
    )
    parser.add_argument(
        "--sidecar",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "references" / "nightly-sidecar-report.json",
        help="Stable sidecar gate report to read from",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "references" / "riscv-snn-research-report.json",
        help="Dated research report output path",
    )
    args = parser.parse_args()

    try:
        output_path = generate_research_report(sidecar_path=args.sidecar, output_path=args.output)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc))
        return 1

    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
