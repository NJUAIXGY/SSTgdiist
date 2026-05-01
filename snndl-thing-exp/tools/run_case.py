#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple


class CaseContext(NamedTuple):
    repo_root: Path
    exp_root: Path
    case_id: str
    case_dir: Path
    case_json: Path
    spec_path: Path
    run_root: Path
    log_root: Path
    env: Dict[str, str]


def load_case(case_json: Path) -> Dict[str, object]:
    with case_json.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"invalid case json: expected object, got {type(payload).__name__}")
    return payload


def resolve_case_context(*, repo_root: Path, exp_root: Path, case_id: str) -> CaseContext:
    case_dir = exp_root / "cases" / case_id
    case_json = case_dir / "case.json"
    if not case_json.is_file():
        raise FileNotFoundError(f"case json not found: {case_json}")

    payload = load_case(case_json)
    spec_name = str(payload.get("spec") or "spec.json").strip() or "spec.json"
    spec_path = case_dir / spec_name
    if not spec_path.is_file():
        raise FileNotFoundError(f"spec not found: {spec_path}")

    run_root = exp_root / "runs" / case_id
    log_root = exp_root / "run_logs" / case_id

    env = dict(os.environ)
    env.setdefault("MESH_VALIDATE_PROFILE", "dev")
    env["MESH_RUN_ROOT"] = str(run_root)

    raw_env = payload.get("env") or {}
    if not isinstance(raw_env, dict):
        raise ValueError(f"invalid env in case json: expected object, got {type(raw_env).__name__}")
    for key, value in raw_env.items():
        env[str(key)] = str(value)

    return CaseContext(
        repo_root=repo_root,
        exp_root=exp_root,
        case_id=case_id,
        case_dir=case_dir,
        case_json=case_json,
        spec_path=spec_path,
        run_root=run_root,
        log_root=log_root,
        env=env,
    )


def build_command(ctx: CaseContext) -> List[str]:
    runner = ctx.repo_root / "sst_dram_si" / "tools" / "run_mesh_with_time.sh"
    return [str(runner), "--spec", str(ctx.spec_path)]


def validate_spec(ctx: CaseContext) -> None:
    cli = ctx.repo_root / "sst_dram_si" / "tools" / "mesh_spec_cli.py"
    cmd = [sys.executable, str(cli), "validate", str(ctx.spec_path)]
    subprocess.run(cmd, check=True, cwd=str(ctx.repo_root), env=ctx.env)


def render_dry_run(ctx: CaseContext) -> str:
    payload = {
        "case_id": ctx.case_id,
        "spec_path": str(ctx.spec_path),
        "run_root": str(ctx.run_root),
        "log_root": str(ctx.log_root),
        "command": build_command(ctx),
        "env": {
            "MESH_RUN_ROOT": ctx.env["MESH_RUN_ROOT"],
            "MESH_VALIDATE_PROFILE": ctx.env["MESH_VALIDATE_PROFILE"],
            **({"MESH_SST_NPROC": ctx.env["MESH_SST_NPROC"]} if "MESH_SST_NPROC" in ctx.env else {}),
        },
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run isolated SnnDL SRAM experiment cases.")
    parser.add_argument("case_id", help="case directory under snndl-thing-exp/cases/")
    parser.add_argument("--dry-run", action="store_true", help="print resolved command/env only")
    parser.add_argument("--validate-only", action="store_true", help="validate spec and exit")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    exp_root = Path(__file__).resolve().parents[1]
    repo_root = exp_root.parent
    ctx = resolve_case_context(repo_root=repo_root, exp_root=exp_root, case_id=args.case_id)

    ctx.run_root.mkdir(parents=True, exist_ok=True)
    ctx.log_root.mkdir(parents=True, exist_ok=True)

    validate_spec(ctx)
    if args.validate_only:
        print(f"OK: {ctx.spec_path}")
        return 0

    if args.dry_run:
        print(render_dry_run(ctx))
        return 0

    subprocess.run(build_command(ctx), check=True, cwd=str(ctx.repo_root), env=ctx.env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
