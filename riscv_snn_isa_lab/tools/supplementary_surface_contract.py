from __future__ import annotations

from typing import Any, Iterable


def format_markdown_value(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "none"
    return str(value)


def build_latest_only_history_payload(*,
                                      history_contract: str,
                                      history_path: str,
                                      latest_date: str,
                                      gate_ok: bool,
                                      freshness_mode: str,
                                      entry_payload: dict[str, Any],
                                      stale: bool = False,
                                      extra_fields: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "history_contract": history_contract,
        "path": history_path,
        "latest_date": latest_date,
        "entry_count": 1,
        "excluded_entry_count": 0,
        "all_ok_latest": bool(gate_ok),
        "all_dates_ok": bool(gate_ok),
        "latest_recovered_date": latest_date if gate_ok else None,
        "freshness_mode": freshness_mode,
        "effective_entry_count": 1,
        "effective_all_dates_ok": bool(gate_ok),
        "stale": stale,
        "entries": [dict(entry_payload)],
    }
    if extra_fields:
        payload.update(extra_fields)
    return payload


def project_surface_payload_from_report(*,
                                        default_payload: dict[str, Any],
                                        report: dict[str, Any],
                                        stable_surface_fields: Iterable[str],
                                        history_fields: Iterable[str],
                                        report_fields: Iterable[str] = (),
                                        list_report_fields: Iterable[str] = ()) -> dict[str, Any]:
    payload = dict(default_payload)
    payload["present"] = True
    stable_surfaces = dict(report.get("stable_surfaces") or {})
    history = dict(report.get("history") or {})

    for field in stable_surface_fields:
        value = stable_surfaces.get(field)
        if value is not None:
            payload[field] = value

    for field in list_report_fields:
        payload[field] = list(report.get(field) or [])

    list_field_names = set(list_report_fields)
    for field in report_fields:
        if field in list_field_names:
            continue
        if field in report:
            payload[field] = report.get(field)

    for field in history_fields:
        value = history.get(field)
        if value is not None:
            payload[field] = value

    return payload


def build_surface_attachment(*,
                             authority_surface: dict[str, Any],
                             stable_surfaces: dict[str, Any],
                             report_payload: dict[str, Any],
                             history_payload: dict[str, Any],
                             extra_fields: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "surface_kind": authority_surface.get("surface_kind"),
        "blocking": authority_surface.get("blocking", False),
        "present": True,
        "artifact_role": report_payload.get("artifact_role"),
        "authority_scope": report_payload.get("authority_scope"),
        "gate_name": report_payload.get("gate_name"),
        "gate_version": report_payload.get("gate_version"),
        "gate_ok": report_payload.get("gate_ok"),
        "gate_reasons": list(report_payload.get("gate_reasons") or []),
        "latest_date": history_payload.get("latest_date"),
        "stale": history_payload.get("stale"),
        "freshness_mode": history_payload.get("freshness_mode"),
        "effective_all_dates_ok": history_payload.get("effective_all_dates_ok"),
    }
    payload.update(dict(stable_surfaces))
    if extra_fields:
        payload.update(extra_fields)
    return payload


def merge_supplementary_surface(*,
                                sidecar_report: dict[str, Any],
                                name: str,
                                surface_payload: dict[str, Any]) -> dict[str, Any]:
    merged_report = dict(sidecar_report)
    supplementary_surfaces = {
        surface_name: dict(payload or {})
        for surface_name, payload in dict(sidecar_report.get("supplementary_surfaces") or {}).items()
        if isinstance(payload, dict)
    }
    supplementary_surfaces[name] = dict(surface_payload)
    merged_report["supplementary_surfaces"] = supplementary_surfaces
    return merged_report


def render_surface_summary_markdown(*,
                                    title: str,
                                    generated_utc: str,
                                    fields: Iterable[tuple[str, Any]],
                                    extra_lines: Iterable[str] = ()) -> str:
    lines = [
        f"# {title}",
        "",
        f"- Generated UTC: `{generated_utc}`",
    ]
    for key, value in fields:
        lines.append(f"- `{key} = {format_markdown_value(value)}`")
    lines.extend(str(line) for line in extra_lines)
    return "\n".join(lines) + "\n"


def render_surface_current_status_markdown(*,
                                           title: str,
                                           generated_utc: str,
                                           fields: Iterable[tuple[str, Any]] = (),
                                           role: str | None = None,
                                           sections: Iterable[tuple[str, Iterable[tuple[str, Any]]]] = (),
                                           extra_lines: Iterable[str] = ()) -> str:
    field_rows = list(fields)
    section_rows = [(heading, list(heading_fields)) for heading, heading_fields in sections]
    trailing_lines = [str(line) for line in extra_lines]
    lines = [
        f"# {title}",
        "",
        f"- Generated UTC: `{generated_utc}`",
    ]
    if role:
        lines.append(f"- Role: {role}")
    if role or field_rows or section_rows or trailing_lines:
        lines.append("")
    for key, value in field_rows:
        lines.append(f"- `{key} = {format_markdown_value(value)}`")
    for heading, heading_fields in section_rows:
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(f"## {heading}")
        for key, value in heading_fields:
            lines.append(f"- `{key} = {format_markdown_value(value)}`")
    if trailing_lines:
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(trailing_lines)
    return "\n".join(lines) + "\n"


__all__ = [
    "format_markdown_value",
    "build_latest_only_history_payload",
    "project_surface_payload_from_report",
    "build_surface_attachment",
    "merge_supplementary_surface",
    "render_surface_summary_markdown",
    "render_surface_current_status_markdown",
]
