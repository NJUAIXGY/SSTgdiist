#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    script = Path("/home/xgy/remote/mainexp/experiments/2026-03-31_atlas_service_rowindex_object_ab_v1/make_snapshot.py")
    cmd = [sys.executable, str(script), *sys.argv[1:]]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
