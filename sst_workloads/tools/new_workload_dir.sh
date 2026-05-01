#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
WORKLOADS_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

TEMPLATE_DIR="$WORKLOADS_ROOT/tensor_si"

if [ $# -ne 1 ]; then
  echo "Usage: bash \"$0\" \"<new_workload_dir_name>\"" >&2
  echo "Example: bash \"$0\" \"mychip_si\"" >&2
  exit 2
fi

NEW_NAME="$1"
DEST_DIR="$WORKLOADS_ROOT/$NEW_NAME"

if [ ! -d "$TEMPLATE_DIR" ]; then
  echo "ERROR: template dir not found: \"$TEMPLATE_DIR\"" >&2
  exit 2
fi

if [ -e "$DEST_DIR" ]; then
  echo "ERROR: dest already exists: \"$DEST_DIR\"" >&2
  exit 1
fi

mkdir -p "$WORKLOADS_ROOT/tools"

rsync -a \
  --exclude "/outputs/" \
  --exclude "/analysis/" \
  --exclude "/__pycache__/" \
  --exclude "*.pyc" \
  "$TEMPLATE_DIR/" \
  "$DEST_DIR/"

echo "[workloads] created \"$DEST_DIR\" from \"$TEMPLATE_DIR\""
echo "[workloads] next: rename python package/scripts inside the new dir to match \"$NEW_NAME\""

