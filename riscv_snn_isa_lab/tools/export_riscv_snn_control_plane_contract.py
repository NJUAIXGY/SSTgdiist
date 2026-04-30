#!/usr/bin/env python3
"\"\"\"Render the frozen riscv_snn control-plane contract from the ABI authority JSON.\"\"\""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any


def normalize_authority(authority: dict[str, Any], *, authority_path: Path | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "producer": "riscv_snn_control_plane_contract",
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "authority_path": str(authority_path) if authority_path is not None else None,
        "hart_profile": authority.get("hart_profile"),
        "csr_map": dict(authority.get("csr_map", {}) or {}),
        "doorbell_rules": dict(authority.get("doorbell_rules", {}) or {}),
        "ownership_rules": dict(authority.get("ownership_rules", {}) or {}),
        "completion_layout": dict(authority.get("completion_layout", {}) or {}),
        "fault_semantics": dict(authority.get("fault_semantics", {}) or {}),
        "event_pending_bits": dict(authority.get("event_pending_bits", {}) or {}),
    }


def render_markdown(authority: dict[str, Any], *, authority_path: Path | None = None) -> str:
    payload = normalize_authority(authority, authority_path=authority_path)
    doorbell = payload["doorbell_rules"]
    ownership = payload["ownership_rules"]
    completion = payload["completion_layout"]
    fault = payload["fault_semantics"]
    event_bits = payload["event_pending_bits"]

    def _json_block(data: Any) -> str:
        return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True)

    return f"""# RISC-V SNN Control-Plane Contract

- Authority path: `{payload["authority_path"] or "inline_authority"}`
- Hart profile: `{payload["hart_profile"]}`
- Generated UTC: `{payload["generated_utc"]}`

## Doorbell

- `cmd_tail`: `{doorbell.get("cmd_tail", "none")}`
- `cmp_tail`: `{doorbell.get("cmp_tail", "none")}`
- `event_pending`: `{doorbell.get("event_pending", "none")}`

## Accepted

`Accepted` is defined by queue ownership and head/tail movement; the contract stays anchored in `ownership_rules`.

```json
{_json_block(ownership)}
```

## Completion Visibility

```json
{_json_block(completion)}
```

Software-visible completion ordering is derived from the ABI authority and remains:

1. completion payload becomes stable
2. completion tail advances
3. event pending becomes observable

## Fault Clear And Overwrite

```json
{_json_block(fault)}
```

## Event Pending Bits

```json
{_json_block(event_bits)}
```
"""


def write_markdown(authority: dict[str, Any], output_path: Path, *, authority_path: Path | None = None) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_markdown(authority, authority_path=authority_path), encoding="utf-8")
    return output_path


def write_json(authority: dict[str, Any], output_path: Path, *, authority_path: Path | None = None) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(normalize_authority(authority, authority_path=authority_path), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the riscv_snn control-plane contract from ABI authority")
    parser.add_argument(
        "--authority",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "spec_authority" / "riscv_snn_accel_v1.json",
        help="ABI authority JSON path",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "references" / "riscv-snn-control-plane-contract.md",
        help="Markdown output path",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=None,
        help="Optional normalized JSON output path",
    )
    args = parser.parse_args()

    authority = json.loads(args.authority.read_text(encoding="utf-8"))
    write_markdown(authority, args.output, authority_path=args.authority)
    if args.json_output is not None:
        write_json(authority, args.json_output, authority_path=args.authority)
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
