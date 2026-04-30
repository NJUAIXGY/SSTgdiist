#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict


THIS_DIR = Path(__file__).resolve().parent
SST_DRAM_SI_DIR = THIS_DIR.parent
# Allow `import mesh_template...` when running from anywhere.
sys.path.insert(0, str(SST_DRAM_SI_DIR))


from mesh_template.legacy_defaults import make_default_state  # noqa: E402
from mesh_template.spec import SpecError  # noqa: E402
from mesh_template.spec import SUPPORTED_COMPONENT_ROLES_V2  # noqa: E402
from mesh_template.spec import load_spec  # noqa: E402
from mesh_template.spec import resolve_spec  # noqa: E402


def _load_and_maybe_patch_spec(spec_path: str, *, allow_unknown_fields: bool) -> Dict[str, Any]:
    raw = load_spec(spec_path)
    if allow_unknown_fields:
        validate = raw.get("validate")
        if not isinstance(validate, dict):
            validate = {}
            raw["validate"] = validate
        validate["allow_unknown_fields"] = True
    return raw


def _cmd_validate(args: argparse.Namespace) -> int:
    raw = _load_and_maybe_patch_spec(args.spec, allow_unknown_fields=bool(args.allow_unknown_fields))
    resolve_spec(raw, defaults_state=make_default_state())
    print("OK")
    return 0


def _cmd_resolve(args: argparse.Namespace) -> int:
    raw = _load_and_maybe_patch_spec(args.spec, allow_unknown_fields=bool(args.allow_unknown_fields))
    resolved = resolve_spec(raw, defaults_state=make_default_state())
    payload = json.dumps(
        resolved,
        ensure_ascii=False,
        sort_keys=True,
        indent=2 if bool(args.pretty) else None,
        separators=None if bool(args.pretty) else (",", ":"),
    )
    sys.stdout.write(payload)
    sys.stdout.write("\n")
    return 0


def _cmd_roles(_args: argparse.Namespace) -> int:
    for role in sorted(SUPPORTED_COMPONENT_ROLES_V2):
        print(role)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mesh_spec_cli.py", description="mesh_template Spec v1/v2 utility")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_validate = sub.add_parser("validate", help="Validate a MeshSystemSpec JSON")
    p_validate.add_argument("spec", help="Path to spec.json")
    p_validate.add_argument("--allow-unknown-fields", action="store_true", help="Skip unknown-field checks")
    p_validate.set_defaults(_fn=_cmd_validate)

    p_resolve = sub.add_parser("resolve", help="Resolve spec into legacy state + overrides (prints JSON)")
    p_resolve.add_argument("spec", help="Path to spec.json")
    p_resolve.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p_resolve.add_argument("--allow-unknown-fields", action="store_true", help="Skip unknown-field checks")
    p_resolve.set_defaults(_fn=_cmd_resolve)

    p_roles = sub.add_parser("roles", help="Print supported v2 components roles")
    p_roles.set_defaults(_fn=_cmd_roles)

    args = parser.parse_args(argv)
    try:
        return int(args._fn(args))  # type: ignore[attr-defined]
    except (SpecError, ValueError) as e:
        sys.stderr.write(str(e))
        sys.stderr.write("\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
