#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from . import build_topology_summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export SnnDL topology summaries as JSON.")
    parser.add_argument("--spec", type=str, default="", help="Path to a snn3dexp spec.json file.")
    parser.add_argument(
        "--source",
        type=str,
        default="auto",
        choices=("auto", "snn3dexp", "mesh_template"),
        help="Topology source selector.",
    )
    parser.add_argument("--case-name", type=str, default="bootstrap_smoke", help="Case name for effective config resolution.")
    parser.add_argument("--mesh-size", type=int, default=4, help="2D mesh size when exporting mesh_template topology.")
    parser.add_argument("--node-limit", type=int, default=0, help="Optional node cap for 2D mesh export.")
    parser.add_argument("--num-cores", type=int, default=1, help="Optional 2D node core count override.")
    parser.add_argument("--out", type=str, default="", help="Write JSON to this path instead of stdout.")
    parser.add_argument("--indent", type=int, default=2, help="JSON indentation level.")
    return parser


def _load_spec(path: str) -> dict[str, Any]:
    spec_path = Path(path).expanduser().resolve()
    return json.loads(spec_path.read_text(encoding="utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    raw_spec = _load_spec(args.spec) if args.spec else None
    topology = build_topology_summary(
        raw_spec=raw_spec,
        source=str(args.source),
        case_name=str(args.case_name),
        mesh_size=int(args.mesh_size),
        node_limit=(int(args.node_limit) if int(args.node_limit) > 0 else None),
        num_cores=int(args.num_cores),
    )
    payload = json.dumps(topology, ensure_ascii=False, indent=int(args.indent))

    if args.out:
        out_path = Path(str(args.out)).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload + "\n", encoding="utf-8")
    else:
        sys.stdout.write(payload + "\n")
    return 0


__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
