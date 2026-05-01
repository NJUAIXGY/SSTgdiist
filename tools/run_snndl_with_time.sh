#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
用法:
  run_snndl_with_time.sh --spec <spec.json>

选项:
  --spec <spec.json>   统一 spec 入口（根据 model 分发到 mesh/tensor runner）
  -h, --help           显示帮助
EOF
}

SPEC_JSON=""
while [ $# -gt 0 ]; do
  case "$1" in
    --spec)
      SPEC_JSON="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[snndl] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [ -z "$SPEC_JSON" ]; then
  echo "[snndl] --spec is required" >&2
  usage >&2
  exit 2
fi

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

SPEC_ABS=$(
  python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$SPEC_JSON"
)
if [ ! -f "$SPEC_ABS" ]; then
  echo "[snndl] spec not found: $SPEC_ABS" >&2
  exit 2
fi

if ! MODEL=$(
  python3 -c '
import json, sys
path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    obj = json.load(f)
if not isinstance(obj, dict):
    print("[snndl] spec must be a json object", file=sys.stderr)
    sys.exit(2)
model = obj.get("model")
if model is None:
    schema_version = obj.get("schema_version", 1)
    if schema_version == 3:
        print("[snndl] model is required when schema_version=3", file=sys.stderr)
        sys.exit(2)
    print("mesh")
    sys.exit(0)
value = str(model).strip().lower()
aliases = {
    "mesh": "mesh",
    "mesh_template": "mesh",
    "tensor": "tensor",
    "tensor_template": "tensor",
}
if value in aliases:
    print(aliases[value])
    sys.exit(0)
print(f"[snndl] invalid model={model!r} (expected mesh|tensor|mesh_template|tensor_template)", file=sys.stderr)
sys.exit(2)
' "$SPEC_ABS"
); then
  exit 2
fi

case "$MODEL" in
  mesh)
    bash "$REPO_ROOT/sst_dram_si/tools/run_mesh_with_time.sh" --spec "$SPEC_ABS"
    ;;
  tensor)
    bash "$REPO_ROOT/sst_workloads/tensor_si/tools/run_tensor_mesh_with_time.sh" --spec "$SPEC_ABS"
    ;;
  *)
    echo "[snndl] unsupported model: $MODEL" >&2
    exit 2
    ;;
esac
