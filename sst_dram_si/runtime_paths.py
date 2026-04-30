from __future__ import annotations

from pathlib import Path


def parse_byte_size(size_str: str) -> int:
    if not size_str:
        return 0

    text = str(size_str).strip().lower()
    multipliers = {
        "kib": 1024,
        "kb": 1024,
        "mib": 1024 ** 2,
        "mb": 1024 ** 2,
        "gib": 1024 ** 3,
        "gb": 1024 ** 3,
        "tib": 1024 ** 4,
        "tb": 1024 ** 4,
    }
    for unit, multiplier in multipliers.items():
        if text.endswith(unit):
            return int(float(text[:-len(unit)]) * multiplier)
    return int(float(text))


def _format_binary_size(num_bytes: int) -> str:
    for suffix, unit_bytes in (("TiB", 1024 ** 4), ("GiB", 1024 ** 3), ("MiB", 1024 ** 2), ("KiB", 1024)):
        if num_bytes >= unit_bytes and num_bytes % unit_bytes == 0:
            return f"{num_bytes // unit_bytes}{suffix}"
    return str(num_bytes)


def resolve_singlepe_mc_mem_size(
    configured_mem_size: str,
    *,
    weight_stride_bytes: int,
    num_cores: int,
    base_addr_start: int = 0,
) -> tuple[str, int]:
    configured_bytes = parse_byte_size(configured_mem_size)
    required_bytes = int(base_addr_start) + max(0, int(weight_stride_bytes)) * max(0, int(num_cores))
    if required_bytes > configured_bytes:
        mib = 1024 ** 2
        effective_bytes = ((required_bytes + mib - 1) // mib) * mib
    else:
        effective_bytes = configured_bytes
    return _format_binary_size(effective_bytes), effective_bytes


def resolve_singlepe_spike_dataset(script_dir: str, dataset_override: str | None = None) -> str:
    script_path = Path(script_dir).resolve()
    repo_root = script_path.parent
    legacy_root = repo_root.parent

    if dataset_override:
        candidate = Path(dataset_override)
        if not candidate.is_absolute():
            candidate = script_path / candidate
        return str(candidate.resolve())

    relative_path = Path("spike_data") / "complex_input_pe_0_class_A.txt"
    candidates = (
        repo_root / "SnnDL_Basic" / relative_path,
        repo_root / "github_submission" / "SnnDL_Basic" / relative_path,
        legacy_root / "SnnDL_Basic" / relative_path,
    )

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return str(candidates[0])


def resolve_singlepe_ramulator2_config(script_dir: str) -> str:
    script_path = Path(script_dir).resolve()
    repo_root = script_path.parent
    legacy_root = repo_root.parent

    candidates = (
        repo_root / "sst_workspace" / "sst-elements" / "src" / "sst" / "elements" / "memHierarchy" / "tests" / "ramulator2-ddr4.cfg",
        script_path / "configs" / "ramulator2_ddr4_openrow.cfg",
        legacy_root / "sst_workspace" / "sst-elements" / "src" / "sst" / "elements" / "memHierarchy" / "tests" / "ramulator2-ddr4.cfg",
    )

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return str(candidates[0])
