#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict


THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent
SST_DRAM_SI_DIR = REPO_ROOT / "sst_dram_si"
TENSOR_SI_DIR = REPO_ROOT / "sst_workloads" / "tensor_si"

# Allow `import mesh_template...` / `import tensor_template...` when running from anywhere.
sys.path.insert(0, str(SST_DRAM_SI_DIR))
sys.path.insert(0, str(TENSOR_SI_DIR))


from mesh_template.legacy_defaults import make_default_state  # noqa: E402
from mesh_template.spec import SpecError  # noqa: E402
from mesh_template.spec import load_spec  # noqa: E402
from mesh_template.spec import resolve_spec as resolve_mesh_spec  # noqa: E402


MODEL_ALIASES = {
    "mesh": "mesh",
    "mesh_template": "mesh",
    "tensor": "tensor",
    "tensor_template": "tensor",
}


def _normalize_model(raw: Dict[str, Any]) -> str:
    schema_version = raw.get("schema_version")
    if raw.get("model") is None:
        if schema_version == 3:
            raise SpecError("model is required when schema_version=3")
        return "mesh"
    value = str(raw.get("model")).strip().lower()
    if value in MODEL_ALIASES:
        return MODEL_ALIASES[value]
    raise SpecError(
        "invalid model={!r} (expected mesh|tensor|mesh_template|tensor_template)".format(raw.get("model"))
    )


def _resolve_tensor(raw: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from tensor_template.spec import resolve_spec as resolve_tensor_spec  # type: ignore
    except Exception as exc:
        raise SpecError(
            "tensor spec resolver not available: expected sst_workloads/tensor_si/tensor_template/spec.py"
        ) from exc
    return resolve_tensor_spec(raw)


def _resolve_spec(raw: Dict[str, Any]) -> Dict[str, Any]:
    model = _normalize_model(raw)
    if model == "mesh":
        return resolve_mesh_spec(raw, defaults_state=make_default_state())
    if model == "tensor":
        return _resolve_tensor(raw)
    raise SpecError(f"unsupported model={model!r}")


def _cmd_validate(args: argparse.Namespace) -> int:
    raw = load_spec(args.spec)
    model = _normalize_model(raw)
    schema_version = raw.get("schema_version", 1)
    _resolve_spec(raw)
    print(f"OK model={model} schema_version={schema_version}")
    return 0


def _cmd_resolve(args: argparse.Namespace) -> int:
    raw = load_spec(args.spec)
    resolved = _resolve_spec(raw)
    payload = json.dumps(
        resolved,
        ensure_ascii=False,
        sort_keys=True,
        indent=2 if bool(args.pretty) else None,
        separators=None if bool(args.pretty) else (",", ":"),
    )
    if args.out:
        out_path = Path(str(args.out)).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload + "\n", encoding="utf-8")
        sys.stderr.write(f"Wrote {out_path}\n")
    sys.stdout.write(payload)
    sys.stdout.write("\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="snndl_spec_cli.py", description="Unified spec CLI for mesh/tensor")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_validate = sub.add_parser("validate", help="Validate a spec JSON")
    p_validate.add_argument("spec", help="Path to spec.json")
    p_validate.set_defaults(_fn=_cmd_validate)

    p_resolve = sub.add_parser("resolve", help="Resolve spec into legacy state (prints JSON)")
    p_resolve.add_argument("spec", help="Path to spec.json")
    p_resolve.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p_resolve.add_argument("--out", help="Write JSON to a file (also prints to stdout)")
    p_resolve.set_defaults(_fn=_cmd_resolve)

    args = parser.parse_args(argv)
    try:
        return int(args._fn(args))  # type: ignore[attr-defined]
    except (SpecError, ValueError) as e:
        sys.stderr.write(str(e))
        sys.stderr.write("\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
