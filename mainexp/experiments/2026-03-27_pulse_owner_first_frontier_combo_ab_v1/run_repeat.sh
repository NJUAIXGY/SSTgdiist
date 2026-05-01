#!/usr/bin/env bash
set -euo pipefail

CASE_ID="${1:-}"
REPEAT_COUNT="${2:-}"

if [ -z "$CASE_ID" ] || [ -z "$REPEAT_COUNT" ]; then
  echo "usage: $0 <case_id> <repeat_count>" >&2
  exit 2
fi

if ! [[ "$REPEAT_COUNT" =~ ^[0-9]+$ ]] || [ "$REPEAT_COUNT" -le 0 ]; then
  echo "repeat_count must be a positive integer: $REPEAT_COUNT" >&2
  exit 2
fi

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
RUN_CASE="$SCRIPT_DIR/run_case.sh"

for idx in $(seq 1 "$REPEAT_COUNT"); do
  echo "[run_repeat] iteration $idx/$REPEAT_COUNT: $CASE_ID"
  "$RUN_CASE" "$CASE_ID"
done

echo "[run_repeat] done"
