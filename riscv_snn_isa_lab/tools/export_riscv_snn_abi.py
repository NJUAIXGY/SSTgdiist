#!/usr/bin/env python3
"\"\"\"Generate shared MSNN ABI include fragments from the authority JSON.\"\"\""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path


def normalize_include_authority(authority: dict[str, object]) -> dict[str, object]:
    return {
        "producer": authority.get("producer", "riscv_snn_isa_lab"),
        "generated_utc": authority.get("generated_utc"),
        "csr_map": dict(authority.get("csr_map", {}) or {}),
        "event_pending_bits": dict(authority.get("event_pending_bits", {}) or {}),
    }


def render_include_text(authority: dict[str, object], *, generated_utc: str | None = None) -> str:
    include_authority = normalize_include_authority(authority)
    lines: list[str] = []
    header = include_authority["producer"]
    timestamp = generated_utc
    if timestamp is None:
        authority_timestamp = include_authority["generated_utc"]
        if isinstance(authority_timestamp, str) and authority_timestamp:
            timestamp = authority_timestamp
        else:
            timestamp = dt.datetime.now(dt.timezone.utc).isoformat()
    lines.append(f"# Auto-generated MSNN ABI include ({header})")
    lines.append(f"# generated {timestamp}")
    lines.append("")

    csr_map = include_authority["csr_map"]
    for name in sorted(csr_map):
        value = csr_map[name]
        if isinstance(value, int):
            lines.append(f".set {name}, 0x{value:04X}")

    event_bits = include_authority["event_pending_bits"]
    if isinstance(event_bits, dict):
        lines.append("")
        for event, bit in sorted(event_bits.items()):
            lines.append(f"# event {event} -> bit {bit}")

    return "\n".join(lines) + "\n"


def render_include(authority: dict[str, object], inc_path: Path, *, generated_utc: str | None = None) -> None:
    inc_path.write_text(render_include_text(authority, generated_utc=generated_utc), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export RISC-V SNN ABI include fragments")
    parser.add_argument(
        "--authority",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "spec_authority" / "riscv_snn_accel_v1.json",
        help="Authority JSON describing the ABI",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Include path to write (.inc)",
    )
    args = parser.parse_args()

    authority_path = args.authority
    if not authority_path.exists():
        raise FileNotFoundError(f"authority file missing: {authority_path}")
    authority_data = json.loads(authority_path.read_text(encoding="utf-8"))
    inc_path = args.output or authority_path.with_suffix(".inc")
    render_include(authority_data, inc_path)
    print(f"wrote {inc_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
