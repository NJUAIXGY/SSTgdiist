#!/usr/bin/env bash

mesh_prepare_compare_runner_overlay() {
  local project_root="$1"
  local run_dir="$2"
  local overlay_chunk="${3:-65536}"
  local run_cfg="$run_dir/local_run_config.json"
  local model_wrapper="$run_dir/mesh_compare_runner_overlay_model.py"
  local project_weights_dir="$project_root/weights"
  local run_weights_dir="$run_dir/weights"

  python3 - "$project_root" "$run_cfg" "$overlay_chunk" <<'PY'
import json
import sys
from pathlib import Path

project_root = Path(sys.argv[1])
out_path = Path(sys.argv[2])
overlay_chunk = int(sys.argv[3])
cfg_path = project_root / "local_run_config.json"
cfg = {}
if cfg_path.exists():
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            cfg = data
    except Exception:
        cfg = {}
cfg["loader_chunk_bytes"] = overlay_chunk
out_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY

  python3 - "$project_weights_dir" "$run_weights_dir" <<'PY'
import os
import sys
from pathlib import Path

src = Path(sys.argv[1]).resolve()
dst = Path(sys.argv[2])
if not src.exists() or dst.exists():
    raise SystemExit(0)
os.symlink(src, dst, target_is_directory=True)
PY

  python3 - "$project_root" "$model_wrapper" <<'PY'
import sys
from pathlib import Path

project_root = Path(sys.argv[1]).resolve()
out_path = Path(sys.argv[2])
payload = f"""#!/usr/bin/env python3
import sys
from pathlib import Path

PROJECT_ROOT = Path(r\"{project_root}\")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import sst
from mesh_template.entry import run_mesh_4x4

run_mesh_4x4(sst_module=sst, script_file=__file__)
"""
out_path.write_text(payload, encoding="utf-8")
PY
  chmod +x "$model_wrapper"
  echo "$model_wrapper"
}
