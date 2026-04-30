#!/usr/bin/env bash

mesh_to_lower() {
  echo "$1" | tr '[:upper:]' '[:lower:]'
}

mesh_is_truthy() {
  case "$(mesh_to_lower "${1:-}")" in
    1|true|yes|y|on) return 0 ;;
    *) return 1 ;;
  esac
}

mesh_default_library_freshness_markers_csv() {
  cat <<'EOF'
atlas_enable_state_local_storage_effective_total,atlas_control_runtime_all_zero_total,atlas_control_runtime_state_fabric_absent_total,atlas_control_runtime_state_fabric_present_idle_total,atlas_control_runtime_state_produced_without_queue_total,atlas_control_runtime_state_queued_without_consume_total,atlas_control_runtime_state_consumed_active_total
EOF
}

mesh_populate_default_sst_add_lib_path() {
  if [ -n "${SST_ADD_LIB_PATH:-}" ]; then
    return 0
  fi
  if [ -z "${REPO_ROOT:-}" ]; then
    return 0
  fi
  local libs=()
  local p
  for p in \
    "$REPO_ROOT/sst_workspace/sst-elements/src/sst/elements/SnnDL/.libs" \
    "$REPO_ROOT/sst_workspace/sst-elements/src/sst/elements/merlin/.libs" \
    "$REPO_ROOT/sst_workspace/sst-elements/src/sst/elements/memHierarchy/.libs"
  do
    if [ -d "$p" ]; then
      libs+=("$p")
    fi
  done
  if [ "${#libs[@]}" -gt 0 ]; then
    SST_ADD_LIB_PATH="$(IFS=:; echo "${libs[*]}")"
    export SST_ADD_LIB_PATH
  fi
}

mesh_resolve_sndl_library_for_freshness() {
  local explicit_path
  explicit_path="${MESH_LIBRARY_FRESHNESS_LIB:-}"
  if [ -n "$explicit_path" ]; then
    echo "$explicit_path"
    return 0
  fi

  local candidate
  if [ -n "${SST_ADD_LIB_PATH:-}" ]; then
    IFS=':' read -r -a _mesh_lib_dirs <<< "$SST_ADD_LIB_PATH"
    for candidate in "${_mesh_lib_dirs[@]}"; do
      if [ -f "$candidate/libSnnDL.so" ]; then
        echo "$candidate/libSnnDL.so"
        return 0
      fi
    done
  fi

  if [ -n "${REPO_ROOT:-}" ]; then
    candidate="$REPO_ROOT/sst_workspace/sst-elements/src/sst/elements/SnnDL/.libs/libSnnDL.so"
    if [ -f "$candidate" ]; then
      echo "$candidate"
      return 0
    fi
  fi

  return 1
}

mesh_preflight_assert_library_freshness() {
  if mesh_is_truthy "${MESH_SKIP_LIBRARY_FRESHNESS_PREFLIGHT:-}"; then
    echo "[mesh] skip library freshness preflight: MESH_SKIP_LIBRARY_FRESHNESS_PREFLIGHT=${MESH_SKIP_LIBRARY_FRESHNESS_PREFLIGHT}"
    return 0
  fi
  local sndl_lib markers_csv
  if ! sndl_lib="$(mesh_resolve_sndl_library_for_freshness)"; then
    echo "[mesh] error: library freshness preflight could not locate libSnnDL.so from SST_ADD_LIB_PATH; set MESH_LIBRARY_FRESHNESS_LIB or MESH_SKIP_LIBRARY_FRESHNESS_PREFLIGHT=1." >&2
    exit 2
  fi
  if [ ! -f "$sndl_lib" ]; then
    echo "[mesh] error: library freshness preflight target does not exist: $sndl_lib" >&2
    exit 2
  fi
  markers_csv="${MESH_LIBRARY_FRESHNESS_REQUIRED_MARKERS:-$(mesh_default_library_freshness_markers_csv)}"
  python3 - "$sndl_lib" "$markers_csv" <<'PY'
from pathlib import Path
import sys

lib_path = Path(sys.argv[1])
markers = [item.strip() for item in sys.argv[2].split(",") if item.strip()]
blob = lib_path.read_bytes()
missing = [marker for marker in markers if marker.encode("utf-8") not in blob]
if missing:
    print(
        f"[mesh] error: library freshness preflight failed for {lib_path}; missing markers: {', '.join(missing)}",
        file=sys.stderr,
    )
    raise SystemExit(2)
print(f"[mesh] library freshness OK: {lib_path}")
PY
}
