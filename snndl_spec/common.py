from __future__ import annotations

from typing import Any, Dict, List, Type


def as_dict(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def as_list(v: Any) -> List[Any]:
    return v if isinstance(v, list) else []


def as_str(v: Any, default: str = "") -> str:
    s = str(v).strip() if v is not None else ""
    return s if s else default


def as_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return int(default)


def as_bool(v: Any, default: bool = False) -> bool:
    if v is None:
        return bool(default)
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return bool(default)


def reject_unknown_keys(
    *,
    obj: Dict[str, Any],
    allowed: set[str],
    ctx: str,
    allow_unknown_fields: bool,
    exc_type: Type[Exception] = ValueError,
) -> None:
    if allow_unknown_fields:
        return
    unknown = sorted(k for k in obj.keys() if k not in allowed)
    if unknown:
        raise exc_type(f"unknown fields in {ctx}: {unknown}")


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

