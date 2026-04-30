from __future__ import annotations

import os


def align_up(value: int, alignment: int) -> int:
    if alignment <= 0:
        return value
    return ((value + alignment - 1) // alignment) * alignment


def mesh_quiet() -> bool:
    raw = os.environ.get("MESH_QUIET", "").strip().lower()
    return raw in ("1", "true", "yes", "y", "on")


def mesh_print(*args: object, **kwargs: object) -> None:
    if mesh_quiet():
        return
    print(*args, **kwargs)


def parse_time_to_ns(time_str: str) -> int:
    try:
        s = (time_str or "").strip().lower()
        if s.endswith("us"):
            return int(float(s[:-2]) * 1000.0)
        if s.endswith("ns"):
            return int(float(s[:-2]))
        if s.endswith("ms"):
            return int(float(s[:-2]) * 1000_000.0)
        if s.endswith("s"):
            return int(float(s[:-1]) * 1_000_000_000.0)
        return int(float(s))
    except Exception:
        return 0
