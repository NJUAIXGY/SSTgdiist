#!/bin/bash
# SST Environment Setup Script

export SST_HOME=/home/xgy/remote

pick_prefix() {
  local candidates=()
  if [ -n "${SST_INSTALL_PREFIX:-}" ]; then
    candidates+=("$SST_INSTALL_PREFIX")
  fi
  candidates+=(
    "$SST_HOME/sst_install_mpi"
    "$SST_HOME/sst_install_serial"
    "$SST_HOME/sst_install"
  )
  local p
  for p in "${candidates[@]}"; do
    if [ -x "$p/bin/sst" ] && "$p/bin/sst" --version >/dev/null 2>&1; then
      printf "%s" "$p"
      return 0
    fi
  done
  return 1
}

if SST_PREFIX_SELECTED="$(pick_prefix)"; then
  export SST_INSTALL_PREFIX="$SST_PREFIX_SELECTED"
else
  # Keep the historical default for diagnosability if no runnable binary is found.
  export SST_INSTALL_PREFIX="$SST_HOME/sst_install"
  echo "WARNING: no runnable SST detected, fallback to $SST_INSTALL_PREFIX" >&2
fi

export PATH="$SST_INSTALL_PREFIX/bin:$PATH"
export LD_LIBRARY_PATH="$SST_INSTALL_PREFIX/lib:$SST_INSTALL_PREFIX/lib64:/home/xgy/miniconda3/lib:${LD_LIBRARY_PATH}"
export RAMULATOR2_DIR="$SST_HOME/externals/ramulator2"

echo "SST environment configured:"
echo "  SST_HOME: $SST_HOME"
echo "  SST_INSTALL_PREFIX: $SST_INSTALL_PREFIX"
echo "  sst command: $(which sst 2>/dev/null || echo 'not found in PATH')"
echo "  sst-info command: $(which sst-info 2>/dev/null || echo 'not found in PATH')"
