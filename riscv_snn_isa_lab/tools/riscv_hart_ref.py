#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

LAB_ROOT = Path(__file__).resolve().parents[1]
HART_REF_ROOT = LAB_ROOT / "hart_ref"
MANIFEST_PATH = HART_REF_ROOT / "manifest.json"
SPIKE_LOCAL_ROOT = LAB_ROOT / "external" / "spike-local"
SPIKE_LOCAL_SRC_DIR = SPIKE_LOCAL_ROOT / "src" / "riscv-isa-sim"
SPIKE_LOCAL_BUILD_DIR = SPIKE_LOCAL_ROOT / "build"
SPIKE_LOCAL_PREFIX_DIR = SPIKE_LOCAL_ROOT / "prefix"


class CommandFailure(RuntimeError):
    pass


def run_command(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, cwd=cwd or LAB_ROOT)


def _dpkg_package_installed(name: str) -> bool:
    proc = subprocess.run(
        ["dpkg-query", "-W", "-f=${Status}", name],
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0 and "install ok installed" in proc.stdout


def default_local_spike_binary(*, lab_root: Path = LAB_ROOT) -> Path:
    return lab_root / "external" / "spike-local" / "prefix" / "bin" / "spike"


def resolve_spike_binary(*,
                         explicit_path: Path | None = None,
                         lab_root: Path = LAB_ROOT,
                         which: Any = shutil.which) -> Path | None:
    if explicit_path is not None and explicit_path.exists():
        return explicit_path

    env_spike = os.environ.get("RISCV_SNN_SPIKE", "").strip()
    if env_spike:
        env_path = Path(env_spike)
        if env_path.exists():
            return env_path

    local_spike = default_local_spike_binary(lab_root=lab_root)
    if local_spike.exists():
        return local_spike

    path_spike = which("spike")
    return Path(path_spike) if path_spike else None


def probe_local_spike_env(*,
                          lab_root: Path = LAB_ROOT,
                          which: Any = shutil.which,
                          package_installed: Any = _dpkg_package_installed,
                          summary_path: Path | None = None) -> dict[str, Any]:
    required_commands = ["git", "make", "g++", "cmake", "pkg-config", "dtc", "flex", "bison"]
    required_packages = ["libboost-regex-dev", "libboost-system-dev"]

    command_paths = {name: which(name) for name in required_commands}
    missing_commands = [name for name, value in command_paths.items() if not value]
    package_status = {name: bool(package_installed(name)) for name in required_packages}
    missing_packages = [name for name, value in package_status.items() if not value]

    local_spike = default_local_spike_binary(lab_root=lab_root)
    env_spike = os.environ.get("RISCV_SNN_SPIKE", "").strip() or None
    path_spike = which("spike")
    resolved_spike = resolve_spike_binary(lab_root=lab_root, which=which)
    resolved_origin = "missing"
    if resolved_spike is not None:
        if env_spike and resolved_spike == Path(env_spike):
            resolved_origin = "env"
        elif resolved_spike == local_spike:
            resolved_origin = "local_prefix"
        elif path_spike and resolved_spike == Path(path_spike):
            resolved_origin = "path"
        else:
            resolved_origin = "explicit"

    summary = {
        "artifact_role": "dated_local_spike_probe",
        "authority_scope": "local_spike_env_only",
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "local_root": str(lab_root / "external" / "spike-local"),
        "source_dir": str(lab_root / "external" / "spike-local" / "src" / "riscv-isa-sim"),
        "build_dir": str(lab_root / "external" / "spike-local" / "build"),
        "prefix_dir": str(lab_root / "external" / "spike-local" / "prefix"),
        "local_spike_candidate": str(local_spike),
        "env_spike_candidate": env_spike,
        "path_spike_candidate": path_spike,
        "resolved_spike": str(resolved_spike) if resolved_spike else None,
        "resolved_origin": resolved_origin,
        "required_commands": command_paths,
        "missing_commands": missing_commands,
        "required_packages": package_status,
        "missing_packages": missing_packages,
        "can_attempt_local_build": not missing_commands and not missing_packages,
        "bootstrap_commands": [
            f"git clone https://github.com/riscv-software-src/riscv-isa-sim \"{lab_root / 'external' / 'spike-local' / 'src' / 'riscv-isa-sim'}\"",
            f"mkdir -p \"{lab_root / 'external' / 'spike-local' / 'build'}\"",
            f"cd \"{lab_root / 'external' / 'spike-local' / 'build'}\" && \"{lab_root / 'external' / 'spike-local' / 'src' / 'riscv-isa-sim' / 'configure'}\" --prefix=\"{lab_root / 'external' / 'spike-local' / 'prefix'}\"",
            f"cd \"{lab_root / 'external' / 'spike-local' / 'build'}\" && make -j$(nproc)",
            f"cd \"{lab_root / 'external' / 'spike-local' / 'build'}\" && make install",
        ],
        "all_ok": resolved_spike is not None,
    }
    if summary_path is not None:
        write_summary(summary, summary_path)
    return summary


def load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        raise CommandFailure("hart-ref manifest missing")
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def write_summary(summary: dict[str, Any], summary_path: Path) -> Path:
    summary["summary_path"] = str(summary_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary_path


def build_summary(
    *,
    profile: str,
    program_path: Path | None,
    spike_path: str | None,
    result: subprocess.CompletedProcess[str] | None,
    status: str,
    error: str | None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "artifact_role": "dated_hart_reference_summary",
        "authority_scope": "standard_riscv_hart_semantics_only",
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "profile": profile,
        "all_ok": False,
        "status": status,
        "program": str(program_path) if program_path else None,
        "spike_command": spike_path,
        "error": error,
    }
    if result:
        summary["stdout"] = result.stdout.strip()
        summary["stderr"] = result.stderr.strip()
        summary["returncode"] = result.returncode
    return summary


def run_hart_ref(
    profile: str,
    *,
    summary_path: Path | None = None,
    spike_path: Path | None = None,
    runner: Any = run_command,
) -> dict[str, Any]:
    summary_path = summary_path or HART_REF_ROOT / "references" / f"{dt.date.today()}-{profile}-hart-ref.json"
    profile_entry: dict[str, Any] | None = None
    program_path: Path | None = None
    resolved_spike_path = resolve_spike_binary(explicit_path=spike_path)
    try:
        manifest = load_manifest()
        profile_entry = manifest.get("profiles", {}).get(profile)
        if profile_entry:
            program_path = HART_REF_ROOT / profile_entry.get("program", "")
    except CommandFailure as exc:
        summary = build_summary(
            profile=profile,
            program_path=None,
            spike_path=str(resolved_spike_path) if resolved_spike_path else None,
            result=None,
            status="env_fail",
            error=str(exc),
        )
        write_summary(summary, summary_path)
        return summary

    if not profile_entry:
        summary = build_summary(
            profile=profile,
            program_path=program_path,
            spike_path=str(resolved_spike_path) if resolved_spike_path else None,
            result=None,
            status="profile_missing",
            error="profile not found in manifest",
        )
        write_summary(summary, summary_path)
        return summary

    if not program_path or not program_path.exists():
        summary = build_summary(
            profile=profile,
            program_path=program_path,
            spike_path=str(resolved_spike_path) if resolved_spike_path else None,
            result=None,
            status="program_missing",
            error=f"{program_path} not found",
        )
        write_summary(summary, summary_path)
        return summary

    if resolved_spike_path is None:
        summary = build_summary(
            profile=profile,
            program_path=program_path,
            spike_path=None,
            result=None,
            status="env_fail",
            error="spike executable not in PATH",
        )
        write_summary(summary, summary_path)
        return summary

    cmd = [str(resolved_spike_path), str(program_path)]
    result = runner(cmd)
    if result.returncode != 0:
        status = "hart_ref_failure"
        error = result.stderr.strip() or result.stdout.strip() or "spike failed"
    else:
        status = "pass"
        error = None

    summary = build_summary(
        profile=profile,
        program_path=program_path,
        spike_path=str(resolved_spike_path),
        result=result,
        status=status,
        error=error,
    )
    if status == "pass":
        summary["all_ok"] = True
    write_summary(summary, summary_path)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hart reference bridge for riscv_snn")
    parser.add_argument("--profile", required=True, help="Profile key from hart_ref/manifest.json")
    parser.add_argument("--summary", help="Output path for the dated summary JSON")
    parser.add_argument("--spike", help="Optional explicit spike binary path")
    args = parser.parse_args(argv)

    summary_path = Path(args.summary) if args.summary else None
    spike_path = Path(args.spike) if args.spike else None
    summary = run_hart_ref(args.profile, summary_path=summary_path, spike_path=spike_path)
    print(summary.get("summary_path") or (summary_path or "summary.json"))
    return 0 if summary.get("all_ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
