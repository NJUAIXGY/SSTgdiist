#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict


THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parents[1]
SNNDL_DIR = REPO_ROOT / "sst_workspace" / "sst-elements" / "src" / "sst" / "elements" / "SnnDL"
EMITTER_SRC = SNNDL_DIR / "tools" / "riscv_snn_emit_sample_firmware.cc"


def _build_emitter(cxx: str) -> Path:
    if not EMITTER_SRC.exists():
        raise FileNotFoundError(f"missing emitter source: {EMITTER_SRC}")

    with tempfile.TemporaryDirectory(prefix="riscv_snn_emit_build_") as td:
        build_dir = Path(td)
        exe_path = build_dir / "riscv_snn_emit_sample_firmware"
        cmd = [
            cxx,
            "-std=c++17",
            "-I",
            str(SNNDL_DIR),
            "-I",
            str(SNNDL_DIR / "api"),
            "-I",
            str(SNNDL_DIR / "services"),
            str(EMITTER_SRC),
            "-o",
            str(exe_path),
        ]
        proc = subprocess.run(cmd, text=True, capture_output=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stdout + proc.stderr)

        # Keep the built binary alive after the temporary build directory is gone.
        cached = Path(tempfile.mkdtemp(prefix="riscv_snn_emit_exec_")) / exe_path.name
        cached.write_bytes(exe_path.read_bytes())
        cached.chmod(0o755)
        return cached


def _load_program_manifest(exe_path: Path) -> Dict[str, Any]:
    proc = subprocess.run(
        [str(exe_path), "--list-programs", "--json"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout + proc.stderr)

    payload = json.loads(proc.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("emitter returned a non-object program manifest")
    return payload


def _write_spec(path: Path, *, elf_path: Path, sim_time: str, mesh_size: int, local_mem_bytes: int,
                cmd_queue_entries: int, cmp_queue_entries: int, rx_debug_queue_entries: int,
                boot_addr: int, hart_isa: str) -> None:
    payload: Dict[str, Any] = {
        "schema_version": 3,
        "platform": {
            "mesh_size": mesh_size,
            "exec_mode": "gas",
            "stop": {
                "mode": "time",
                "simulation_time": sim_time,
            },
            "flags": {
                "enable_node_summary": True,
            },
        },
        "workload": {
            "impl": "riscv_snn",
            "params": {
                "hart_isa": hart_isa,
                "local_mem_bytes": local_mem_bytes,
                "cmd_queue_entries": cmd_queue_entries,
                "cmp_queue_entries": cmp_queue_entries,
                "rx_debug_queue_entries": rx_debug_queue_entries,
                "boot_addr": boot_addr,
                "backend_name": "runtime_bridge",
                "firmware_elf": str(elf_path.resolve()),
            },
            "spike_source": {
                "enable": False,
            },
        },
        "control": {
            "global_step_sync_enable": False,
        },
        "loader": {
            "chunk_bytes": 65536,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _print_programs(payload: Dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False))
        sys.stdout.write("\n")
        return

    samples = payload.get("samples", {})
    for name, sample in samples.items():
        role = "canonical" if bool(sample.get("canonical_sample")) else "reference"
        print(f"{name}: {sample['description']} [{role}]")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="generate_riscv_snn_firmware.py",
        description="Build an experimental riscv_snn sample firmware ELF and optional spec JSON",
    )
    parser.add_argument("--list-programs", action="store_true", help="List available sample firmware programs")
    parser.add_argument("--json", action="store_true", help="Used with --list-programs to print machine-readable JSON")
    parser.add_argument(
        "--program",
        default="",
        help="Sample firmware program",
    )
    parser.add_argument("--elf", default="", help="Output ELF path")
    parser.add_argument("--spec", default="", help="Optional output spec JSON path")
    parser.add_argument("--cxx", default="g++", help="C++ compiler used to build the private emitter")
    parser.add_argument("--sim-time", default="1us", help="Spec simulation_time value when --spec is set")
    parser.add_argument("--mesh-size", type=int, default=4, help="Spec mesh_size value when --spec is set")
    parser.add_argument("--hart-isa", default="rv64im_zicsr", help="Spec hart ISA string when --spec is set")
    parser.add_argument("--local-mem-bytes", type=int, default=64 * 1024, help="Spec local memory bytes")
    parser.add_argument("--cmd-queue-entries", type=int, default=64, help="Spec command queue entries")
    parser.add_argument("--cmp-queue-entries", type=int, default=64, help="Spec completion queue entries")
    parser.add_argument("--rx-debug-queue-entries", type=int, default=16, help="Spec rx debug queue entries")
    parser.add_argument("--boot-addr", type=int, default=0, help="Spec boot address")

    args = parser.parse_args(argv)

    exe_path = _build_emitter(args.cxx)
    try:
        manifest = _load_program_manifest(exe_path)

        if bool(args.list_programs):
            _print_programs(manifest, as_json=bool(args.json))
            return 0

        if not args.program or not args.elf:
            parser.error("the following arguments are required unless --list-programs is used: --program, --elf")

        samples = manifest.get("samples", {})
        if args.program not in samples:
            choices = ", ".join(sorted(samples.keys()))
            parser.error(f"argument --program: invalid choice: {args.program!r} (choose from {choices})")

        elf_path = Path(args.elf).resolve()
        elf_path.parent.mkdir(parents=True, exist_ok=True)

        proc = subprocess.run(
            [str(exe_path), args.program, str(elf_path)],
            text=True,
            capture_output=True,
        )
    finally:
        try:
            exe_path.unlink()
            exe_path.parent.rmdir()
        except OSError:
            pass

    if proc.returncode != 0:
        raise SystemExit(proc.stdout + proc.stderr)

    if args.spec:
        spec_path = Path(args.spec).resolve()
        _write_spec(
            spec_path,
            elf_path=elf_path,
            sim_time=args.sim_time,
            mesh_size=int(args.mesh_size),
            local_mem_bytes=int(args.local_mem_bytes),
            cmd_queue_entries=int(args.cmd_queue_entries),
            cmp_queue_entries=int(args.cmp_queue_entries),
            rx_debug_queue_entries=int(args.rx_debug_queue_entries),
            boot_addr=int(args.boot_addr),
            hart_isa=str(args.hart_isa),
        )
        print(spec_path)
    else:
        print(elf_path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, subprocess.SubprocessError) as exc:
        sys.stderr.write(str(exc))
        sys.stderr.write("\n")
        raise SystemExit(2)
