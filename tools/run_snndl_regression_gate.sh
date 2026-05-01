#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

SNNDL_DIR="$REPO_ROOT/sst_workspace/sst-elements/src/sst/elements/SnnDL"
SNNDL_LIB_DIR="$SNNDL_DIR/.libs"
ELEMENTS_ROOT="$REPO_ROOT/sst_workspace/sst-elements/src/sst/elements"
SST_CORE_BIN_DEFAULT="$REPO_ROOT/sst_workspace/sst-core/src/sst/core/sst"
RAMULATOR_SO_DIR="$REPO_ROOT/sst_install/lib/sst-elements-library"

GATE_BUILD="${SNNDL_GATE_BUILD:-1}"
GATE_JOBS="${SNNDL_GATE_JOBS:-4}"

GATE_MESH_MAX_STEPS="${SNNDL_GATE_MESH_MAX_STEPS:-1}"
GATE_MESH_VALIDATE_PROFILE="${SNNDL_GATE_MESH_VALIDATE_PROFILE:-dev}"
GATE_TENSOR_SIM_TIME="${SNNDL_GATE_TENSOR_SIM_TIME:-10us}"
GATE_TENSOR_MGATES="${SNNDL_GATE_TENSOR_MGATES:-1}"
GATE_TENSOR_MGATES_SKIP_UNIT="${SNNDL_GATE_TENSOR_MGATES_SKIP_UNIT:-1}"
GATE_TENSOR_M5_DRIFT_BASELINE="${SNNDL_GATE_TENSOR_M5_DRIFT_BASELINE:-}"
GATE_TENSOR_M5_DRIFT_THRESHOLD="${SNNDL_GATE_TENSOR_M5_DRIFT_THRESHOLD:-0.30}"
GATE_TENSOR_TRACK="${SNNDL_GATE_TENSOR_TRACK:-legacy}"
GATE_TENSOR_REALISM_SKIP_UNIT="${SNNDL_GATE_TENSOR_REALISM_SKIP_UNIT:-1}"

if [ "$GATE_TENSOR_TRACK" != "legacy" ] && [ "$GATE_TENSOR_TRACK" != "realism" ] && [ "$GATE_TENSOR_TRACK" != "full" ]; then
  echo "[gate] ERROR: invalid SNNDL_GATE_TENSOR_TRACK=\"$GATE_TENSOR_TRACK\" (expected legacy|realism|full)" >&2
  exit 2
fi

echo "[gate] repo_root=\"$REPO_ROOT\""
echo "[gate] tensor_track=\"$GATE_TENSOR_TRACK\""

if [ "$GATE_BUILD" != "0" ]; then
  echo "[gate] build: \"$SNNDL_DIR\" (-j$GATE_JOBS)"
  ( cd "$SNNDL_DIR" && make -j"$GATE_JOBS" )
fi

if [ -x "$SST_CORE_BIN_DEFAULT" ]; then
  export SST_BIN="$SST_CORE_BIN_DEFAULT"
  echo "[gate] use SST_BIN=\"$SST_BIN\""
else
  echo "[gate] WARN: sst-core binary not found: \"$SST_CORE_BIN_DEFAULT\" (set SST_BIN to override)" >&2
fi

snndl_so="$SNNDL_LIB_DIR/libSnnDL.so"
merlin_so="$ELEMENTS_ROOT/merlin/.libs/libmerlin.so"
memh_so="$ELEMENTS_ROOT/memHierarchy/.libs/libmemHierarchy.so"

if [ ! -f "$snndl_so" ]; then
  echo "[gate] ERROR: missing \"$snndl_so\" (build SnnDL first)" >&2
  exit 2
fi
if [ ! -f "$merlin_so" ]; then
  echo "[gate] ERROR: missing \"$merlin_so\" (build sst-elements/merlin first)" >&2
  exit 2
fi
if [ ! -f "$memh_so" ]; then
  echo "[gate] ERROR: missing \"$memh_so\" (build sst-elements/memHierarchy first)" >&2
  exit 2
fi

export SST_ADD_LIB_PATH="$SNNDL_LIB_DIR:$ELEMENTS_ROOT/merlin/.libs:$ELEMENTS_ROOT/memHierarchy/.libs"
echo "[gate] use SST_ADD_LIB_PATH=\"$SST_ADD_LIB_PATH\""

if [ -f "$RAMULATOR_SO_DIR/libramulator.so" ]; then
  export LD_LIBRARY_PATH="$RAMULATOR_SO_DIR:${LD_LIBRARY_PATH:-}"
else
  echo "[gate] WARN: missing \"$RAMULATOR_SO_DIR/libramulator.so\" (memHierarchy may fail to load)" >&2
fi

echo "[gate] run: dram-si (MESH_MAX_STEPS=$GATE_MESH_MAX_STEPS)"
export MESH_MAX_STEPS="$GATE_MESH_MAX_STEPS"
export MESH_VALIDATE_PROFILE="$GATE_MESH_VALIDATE_PROFILE"
dram_out=""
if ! dram_out="$(cd "$REPO_ROOT/sst_dram_si" && bash "./tools/run_mesh_with_time.sh" 2>&1)"; then
  echo "$dram_out"
  echo "[gate] FAIL: dram-si run failed" >&2
  exit 21
fi
echo "$dram_out"
dram_run_dir="$(echo "$dram_out" | sed -n 's/^\[mesh\] run complete: //p' | tail -n 1)"

echo "[gate] run: tensor-si (TENSOR_SI_SIM_TIME=$GATE_TENSOR_SIM_TIME)"
export TENSOR_SI_SIM_TIME="$GATE_TENSOR_SIM_TIME"
tensor_out=""
if ! tensor_out="$(cd "$REPO_ROOT/sst_workloads/tensor_si" && bash "./tools/run_tensor_mesh_with_time.sh" 2>&1)"; then
  echo "$tensor_out"
  echo "[gate] FAIL: tensor-si run failed" >&2
  exit 22
fi
echo "$tensor_out"
tensor_run_dir="$(echo "$tensor_out" | sed -n 's/^\[tensor_mesh\] run complete: //p' | tail -n 1)"

m4_report_dir=""
m5_report_dir=""
m6_report_dir=""

if [ "$GATE_TENSOR_TRACK" = "legacy" ] || [ "$GATE_TENSOR_TRACK" = "full" ]; then
  if [ "$GATE_TENSOR_MGATES" != "0" ]; then
    echo "[gate] run: tensor m4 gate"
    m4_cmd=(bash "$REPO_ROOT/tools/run_tensor_m4_gate.sh")
    if [ "$GATE_TENSOR_MGATES_SKIP_UNIT" = "1" ]; then
      m4_cmd+=(--skip-unit)
    fi
    m4_out=""
    if ! m4_out="$("${m4_cmd[@]}" 2>&1)"; then
      echo "$m4_out"
      echo "[gate] FAIL: tensor m4 gate failed" >&2
      exit 23
    fi
    echo "$m4_out"
    m4_report_dir="$(echo "$m4_out" | sed -n 's/^\[m4\] report_dir="\([^"]*\)"/\1/p' | tail -n 1)"

    echo "[gate] run: tensor m5 gate"
    m5_cmd=(bash "$REPO_ROOT/tools/run_tensor_m5_gate.sh")
    if [ "$GATE_TENSOR_MGATES_SKIP_UNIT" = "1" ]; then
      m5_cmd+=(--skip-unit)
    fi
    if [ -n "$GATE_TENSOR_M5_DRIFT_BASELINE" ]; then
      m5_cmd+=(--drift-baseline "$GATE_TENSOR_M5_DRIFT_BASELINE" --drift-threshold "$GATE_TENSOR_M5_DRIFT_THRESHOLD")
    fi
    m5_out=""
    if ! m5_out="$("${m5_cmd[@]}" 2>&1)"; then
      echo "$m5_out"
      echo "[gate] FAIL: tensor m5 gate failed" >&2
      exit 24
    fi
    echo "$m5_out"
    m5_report_dir="$(echo "$m5_out" | sed -n 's/^\[m5\] report_dir="\([^"]*\)"/\1/p' | tail -n 1)"

    if [ "${GATE_TENSOR_MGATES:-0}" -ge "2" ]; then
      echo "[gate] run: tensor m6 gate"
      m6_cmd=(bash "$REPO_ROOT/tools/run_tensor_m6_gate.sh")
      if [ "$GATE_TENSOR_MGATES_SKIP_UNIT" = "1" ]; then
        m6_cmd+=(--skip-unit)
      fi
      m6_out=""
      if ! m6_out="$("${m6_cmd[@]}" 2>&1)"; then
        echo "$m6_out"
        echo "[gate] FAIL: tensor m6 gate failed" >&2
        exit 25
      fi
      echo "$m6_out"
      m6_report_dir="$(echo "$m6_out" | sed -n 's/^\[m6\] report_dir="\([^"]*\)"/\1/p' | tail -n 1)"
    fi
  fi
fi

m47_report_dir=""
m48_report_dir=""
m49_report_dir=""
m50_report_dir=""
m51_report_dir=""
m52_report_dir=""
m53_report_dir=""
m54_report_dir=""
m55_report_dir=""
m56_report_dir=""
m57_report_dir=""
m58_report_dir=""
m59_report_dir=""
m60_report_dir=""
m61_report_dir=""
m62_report_dir=""
m63_report_dir=""
m64_report_dir=""
m65_report_dir=""
m66_report_dir=""
m67_report_dir=""
m68_report_dir=""
m69_report_dir=""
m70_report_dir=""
m71_report_dir=""
m72_report_dir=""
m73_report_dir=""
m74_report_dir=""
m75_report_dir=""
m76_report_dir=""
m77_report_dir=""
m78_report_dir=""
m79_report_dir=""
m80_report_dir=""
m81_report_dir=""
m82_report_dir=""
m83_report_dir=""
m84_report_dir=""
m85_report_dir=""
m86_report_dir=""
m87_report_dir=""
m88_report_dir=""
m89_report_dir=""
m90_report_dir=""
m91_report_dir=""
m92_report_dir=""
m93_report_dir=""
m94_report_dir=""
m95_report_dir=""
m96_report_dir=""
m97_report_dir=""
m98_report_dir=""
m99_report_dir=""
m100_report_dir=""
m101_report_dir=""
m102_report_dir=""
m103_report_dir=""
m104_report_dir=""
m105_report_dir=""
m106_report_dir=""
m107_report_dir=""
m108_report_dir=""
m109_report_dir=""
m110_report_dir=""

run_realism_gate() {
  local gate_id="$1"
  local gate_script="$2"
  local fail_code="$3"

  local cmd=(bash "$gate_script")
  if [ "$GATE_TENSOR_REALISM_SKIP_UNIT" = "1" ]; then
    cmd+=(--skip-unit)
  fi

  local out=""
  if ! out="$("${cmd[@]}" 2>&1)"; then
    echo "$out" >&2
    echo "[gate] FAIL: tensor $gate_id gate failed" >&2
    exit "$fail_code"
  fi
  echo "$out" >&2
  local report_dir=""
  report_dir="$(echo "$out" | sed -n "s/^\\[$gate_id\\] report_dir=\"\\([^\"]*\\)\"/\\1/p" | tail -n 1)"
  if [ -z "$report_dir" ]; then
    echo "[gate] FAIL: tensor $gate_id gate missing report_dir in output" >&2
    exit "$fail_code"
  fi
  echo "$report_dir"
}

if [ "$GATE_TENSOR_TRACK" = "realism" ] || [ "$GATE_TENSOR_TRACK" = "full" ]; then
  echo "[gate] run: tensor m47 gate"
  m47_report_dir="$(run_realism_gate "m47" "$REPO_ROOT/tools/run_tensor_m47_gate.sh" 31)"

  echo "[gate] run: tensor m48 gate"
  m48_report_dir="$(run_realism_gate "m48" "$REPO_ROOT/tools/run_tensor_m48_gate.sh" 32)"

  echo "[gate] run: tensor m49 gate"
  m49_report_dir="$(run_realism_gate "m49" "$REPO_ROOT/tools/run_tensor_m49_gate.sh" 33)"

  echo "[gate] run: tensor m50 gate"
  m50_report_dir="$(run_realism_gate "m50" "$REPO_ROOT/tools/run_tensor_m50_gate.sh" 34)"

  echo "[gate] run: tensor m51 gate"
  m51_report_dir="$(run_realism_gate "m51" "$REPO_ROOT/tools/run_tensor_m51_gate.sh" 35)"

  echo "[gate] run: tensor m52 gate"
  m52_report_dir="$(run_realism_gate "m52" "$REPO_ROOT/tools/run_tensor_m52_gate.sh" 36)"

  echo "[gate] run: tensor m53 gate"
  m53_report_dir="$(run_realism_gate "m53" "$REPO_ROOT/tools/run_tensor_m53_gate.sh" 37)"

  echo "[gate] run: tensor m54 gate"
  m54_report_dir="$(run_realism_gate "m54" "$REPO_ROOT/tools/run_tensor_m54_gate.sh" 38)"

  echo "[gate] run: tensor m55 gate"
  m55_report_dir="$(run_realism_gate "m55" "$REPO_ROOT/tools/run_tensor_m55_gate.sh" 39)"

  echo "[gate] run: tensor m56 gate"
  m56_report_dir="$(run_realism_gate "m56" "$REPO_ROOT/tools/run_tensor_m56_gate.sh" 40)"

  echo "[gate] run: tensor m57 gate"
  m57_report_dir="$(run_realism_gate "m57" "$REPO_ROOT/tools/run_tensor_m57_gate.sh" 41)"

  echo "[gate] run: tensor m58 gate"
  m58_report_dir="$(run_realism_gate "m58" "$REPO_ROOT/tools/run_tensor_m58_gate.sh" 42)"

  echo "[gate] run: tensor m59 gate"
  m59_report_dir="$(run_realism_gate "m59" "$REPO_ROOT/tools/run_tensor_m59_gate.sh" 43)"

  echo "[gate] run: tensor m60 gate"
  m60_report_dir="$(run_realism_gate "m60" "$REPO_ROOT/tools/run_tensor_m60_gate.sh" 44)"

  echo "[gate] run: tensor m61 gate"
  m61_report_dir="$(run_realism_gate "m61" "$REPO_ROOT/tools/run_tensor_m61_gate.sh" 45)"

  echo "[gate] run: tensor m62 gate"
  m62_report_dir="$(run_realism_gate "m62" "$REPO_ROOT/tools/run_tensor_m62_gate.sh" 46)"

  echo "[gate] run: tensor m63 gate"
  m63_report_dir="$(run_realism_gate "m63" "$REPO_ROOT/tools/run_tensor_m63_gate.sh" 47)"

  echo "[gate] run: tensor m64 gate"
  m64_report_dir="$(run_realism_gate "m64" "$REPO_ROOT/tools/run_tensor_m64_gate.sh" 48)"

  echo "[gate] run: tensor m65 gate"
  m65_report_dir="$(run_realism_gate "m65" "$REPO_ROOT/tools/run_tensor_m65_gate.sh" 49)"

  echo "[gate] run: tensor m66 gate"
  m66_report_dir="$(run_realism_gate "m66" "$REPO_ROOT/tools/run_tensor_m66_gate.sh" 50)"

  echo "[gate] run: tensor m67 gate"
  m67_report_dir="$(run_realism_gate "m67" "$REPO_ROOT/tools/run_tensor_m67_gate.sh" 51)"

  echo "[gate] run: tensor m68 gate"
  m68_report_dir="$(run_realism_gate "m68" "$REPO_ROOT/tools/run_tensor_m68_gate.sh" 52)"

  echo "[gate] run: tensor m69 gate"
  m69_report_dir="$(run_realism_gate "m69" "$REPO_ROOT/tools/run_tensor_m69_gate.sh" 53)"

  echo "[gate] run: tensor m70 gate"
  m70_report_dir="$(run_realism_gate "m70" "$REPO_ROOT/tools/run_tensor_m70_gate.sh" 54)"

  echo "[gate] run: tensor m71 gate"
  m71_report_dir="$(run_realism_gate "m71" "$REPO_ROOT/tools/run_tensor_m71_gate.sh" 55)"

  echo "[gate] run: tensor m72 gate"
  m72_report_dir="$(run_realism_gate "m72" "$REPO_ROOT/tools/run_tensor_m72_gate.sh" 56)"

  echo "[gate] run: tensor m73 gate"
  m73_report_dir="$(run_realism_gate "m73" "$REPO_ROOT/tools/run_tensor_m73_gate.sh" 57)"

  echo "[gate] run: tensor m74 gate"
  m74_report_dir="$(run_realism_gate "m74" "$REPO_ROOT/tools/run_tensor_m74_gate.sh" 58)"

  echo "[gate] run: tensor m75 gate"
  m75_report_dir="$(run_realism_gate "m75" "$REPO_ROOT/tools/run_tensor_m75_gate.sh" 59)"

  echo "[gate] run: tensor m76 gate"
  m76_report_dir="$(run_realism_gate "m76" "$REPO_ROOT/tools/run_tensor_m76_gate.sh" 60)"

  echo "[gate] run: tensor m77 gate"
  m77_report_dir="$(run_realism_gate "m77" "$REPO_ROOT/tools/run_tensor_m77_gate.sh" 61)"

  echo "[gate] run: tensor m78 gate"
  m78_report_dir="$(run_realism_gate "m78" "$REPO_ROOT/tools/run_tensor_m78_gate.sh" 62)"

  echo "[gate] run: tensor m79 gate"
  m79_report_dir="$(run_realism_gate "m79" "$REPO_ROOT/tools/run_tensor_m79_gate.sh" 63)"

  echo "[gate] run: tensor m80 gate"
  m80_report_dir="$(run_realism_gate "m80" "$REPO_ROOT/tools/run_tensor_m80_gate.sh" 64)"

  echo "[gate] run: tensor m81 gate"
  m81_report_dir="$(run_realism_gate "m81" "$REPO_ROOT/tools/run_tensor_m81_gate.sh" 65)"

  echo "[gate] run: tensor m82 gate"
  m82_report_dir="$(run_realism_gate "m82" "$REPO_ROOT/tools/run_tensor_m82_gate.sh" 66)"

  echo "[gate] run: tensor m83 gate"
  m83_report_dir="$(run_realism_gate "m83" "$REPO_ROOT/tools/run_tensor_m83_gate.sh" 67)"

  echo "[gate] run: tensor m84 gate"
  m84_report_dir="$(run_realism_gate "m84" "$REPO_ROOT/tools/run_tensor_m84_gate.sh" 68)"

  echo "[gate] run: tensor m85 gate"
  m85_report_dir="$(run_realism_gate "m85" "$REPO_ROOT/tools/run_tensor_m85_gate.sh" 69)"

  echo "[gate] run: tensor m86 gate"
  m86_report_dir="$(run_realism_gate "m86" "$REPO_ROOT/tools/run_tensor_m86_gate.sh" 70)"

  echo "[gate] run: tensor m87 gate"
  m87_report_dir="$(run_realism_gate "m87" "$REPO_ROOT/tools/run_tensor_m87_gate.sh" 71)"

  echo "[gate] run: tensor m88 gate"
  m88_report_dir="$(run_realism_gate "m88" "$REPO_ROOT/tools/run_tensor_m88_gate.sh" 72)"

  echo "[gate] run: tensor m89 gate"
  m89_report_dir="$(run_realism_gate "m89" "$REPO_ROOT/tools/run_tensor_m89_gate.sh" 73)"

  echo "[gate] run: tensor m90 gate"
  m90_report_dir="$(run_realism_gate "m90" "$REPO_ROOT/tools/run_tensor_m90_gate.sh" 74)"

  echo "[gate] run: tensor m91 gate"
  m91_report_dir="$(run_realism_gate "m91" "$REPO_ROOT/tools/run_tensor_m91_gate.sh" 75)"

  echo "[gate] run: tensor m92 gate"
  m92_report_dir="$(run_realism_gate "m92" "$REPO_ROOT/tools/run_tensor_m92_gate.sh" 76)"

  echo "[gate] run: tensor m93 gate"
  m93_report_dir="$(run_realism_gate "m93" "$REPO_ROOT/tools/run_tensor_m93_gate.sh" 77)"

  echo "[gate] run: tensor m94 gate"
  m94_report_dir="$(run_realism_gate "m94" "$REPO_ROOT/tools/run_tensor_m94_gate.sh" 78)"

  echo "[gate] run: tensor m95 gate"
  m95_report_dir="$(run_realism_gate "m95" "$REPO_ROOT/tools/run_tensor_m95_gate.sh" 79)"

  echo "[gate] run: tensor m96 gate"
  m96_report_dir="$(run_realism_gate "m96" "$REPO_ROOT/tools/run_tensor_m96_gate.sh" 80)"

  echo "[gate] run: tensor m97 gate"
  m97_report_dir="$(run_realism_gate "m97" "$REPO_ROOT/tools/run_tensor_m97_gate.sh" 81)"

  echo "[gate] run: tensor m98 gate"
  m98_report_dir="$(run_realism_gate "m98" "$REPO_ROOT/tools/run_tensor_m98_gate.sh" 82)"

  echo "[gate] run: tensor m99 gate"
  m99_report_dir="$(run_realism_gate "m99" "$REPO_ROOT/tools/run_tensor_m99_gate.sh" 83)"

  echo "[gate] run: tensor m100 gate"
  m100_report_dir="$(run_realism_gate "m100" "$REPO_ROOT/tools/run_tensor_m100_gate.sh" 84)"

  echo "[gate] run: tensor m101 gate"
  m101_report_dir="$(run_realism_gate "m101" "$REPO_ROOT/tools/run_tensor_m101_gate.sh" 85)"

  echo "[gate] run: tensor m102 gate"
  m102_report_dir="$(run_realism_gate "m102" "$REPO_ROOT/tools/run_tensor_m102_gate.sh" 86)"

  echo "[gate] run: tensor m103 gate"
  m103_report_dir="$(run_realism_gate "m103" "$REPO_ROOT/tools/run_tensor_m103_gate.sh" 87)"

  echo "[gate] run: tensor m104 gate"
  m104_report_dir="$(run_realism_gate "m104" "$REPO_ROOT/tools/run_tensor_m104_gate.sh" 88)"

  echo "[gate] run: tensor m105 gate"
  m105_report_dir="$(run_realism_gate "m105" "$REPO_ROOT/tools/run_tensor_m105_gate.sh" 89)"

  echo "[gate] run: tensor m106 gate"
  m106_report_dir="$(run_realism_gate "m106" "$REPO_ROOT/tools/run_tensor_m106_gate.sh" 90)"

  echo "[gate] run: tensor m107 gate"
  m107_report_dir="$(run_realism_gate "m107" "$REPO_ROOT/tools/run_tensor_m107_gate.sh" 91)"

  echo "[gate] run: tensor m108 gate"
  m108_report_dir="$(run_realism_gate "m108" "$REPO_ROOT/tools/run_tensor_m108_gate.sh" 92)"

  echo "[gate] run: tensor m109 gate"
  m109_report_dir="$(run_realism_gate "m109" "$REPO_ROOT/tools/run_tensor_m109_gate.sh" 93)"

  echo "[gate] run: tensor m110 gate"
  m110_report_dir="$(run_realism_gate "m110" "$REPO_ROOT/tools/run_tensor_m110_gate.sh" 94)"
fi

echo "[gate] PASS"
echo "[gate] tensor_track=\"$GATE_TENSOR_TRACK\""
echo "[gate] dram_run_dir=\"$dram_run_dir\""
echo "[gate] tensor_run_dir=\"$tensor_run_dir\""
if [ -n "$m4_report_dir" ]; then
  echo "[gate] tensor_m4_report_dir=\"$m4_report_dir\""
fi
if [ -n "$m5_report_dir" ]; then
  echo "[gate] tensor_m5_report_dir=\"$m5_report_dir\""
fi
if [ -n "$m6_report_dir" ]; then
  echo "[gate] tensor_m6_report_dir=\"$m6_report_dir\""
fi
if [ -n "$m47_report_dir" ]; then
  echo "[gate] tensor_m47_report_dir=\"$m47_report_dir\""
fi
if [ -n "$m48_report_dir" ]; then
  echo "[gate] tensor_m48_report_dir=\"$m48_report_dir\""
fi
if [ -n "$m49_report_dir" ]; then
  echo "[gate] tensor_m49_report_dir=\"$m49_report_dir\""
fi
if [ -n "$m50_report_dir" ]; then
  echo "[gate] tensor_m50_report_dir=\"$m50_report_dir\""
fi
if [ -n "$m51_report_dir" ]; then
  echo "[gate] tensor_m51_report_dir=\"$m51_report_dir\""
fi
if [ -n "$m52_report_dir" ]; then
  echo "[gate] tensor_m52_report_dir=\"$m52_report_dir\""
fi
if [ -n "$m53_report_dir" ]; then
  echo "[gate] tensor_m53_report_dir=\"$m53_report_dir\""
fi
if [ -n "$m54_report_dir" ]; then
  echo "[gate] tensor_m54_report_dir=\"$m54_report_dir\""
fi
if [ -n "$m55_report_dir" ]; then
  echo "[gate] tensor_m55_report_dir=\"$m55_report_dir\""
fi
if [ -n "$m56_report_dir" ]; then
  echo "[gate] tensor_m56_report_dir=\"$m56_report_dir\""
fi
if [ -n "$m57_report_dir" ]; then
  echo "[gate] tensor_m57_report_dir=\"$m57_report_dir\""
fi
if [ -n "$m58_report_dir" ]; then
  echo "[gate] tensor_m58_report_dir=\"$m58_report_dir\""
fi
if [ -n "$m59_report_dir" ]; then
  echo "[gate] tensor_m59_report_dir=\"$m59_report_dir\""
fi
if [ -n "$m60_report_dir" ]; then
  echo "[gate] tensor_m60_report_dir=\"$m60_report_dir\""
fi
if [ -n "$m61_report_dir" ]; then
  echo "[gate] tensor_m61_report_dir=\"$m61_report_dir\""
fi
if [ -n "$m62_report_dir" ]; then
  echo "[gate] tensor_m62_report_dir=\"$m62_report_dir\""
fi
if [ -n "$m63_report_dir" ]; then
  echo "[gate] tensor_m63_report_dir=\"$m63_report_dir\""
fi
if [ -n "$m64_report_dir" ]; then
  echo "[gate] tensor_m64_report_dir=\"$m64_report_dir\""
fi
if [ -n "$m65_report_dir" ]; then
  echo "[gate] tensor_m65_report_dir=\"$m65_report_dir\""
fi
if [ -n "$m66_report_dir" ]; then
  echo "[gate] tensor_m66_report_dir=\"$m66_report_dir\""
fi
if [ -n "$m67_report_dir" ]; then
  echo "[gate] tensor_m67_report_dir=\"$m67_report_dir\""
fi
if [ -n "$m68_report_dir" ]; then
  echo "[gate] tensor_m68_report_dir=\"$m68_report_dir\""
fi
if [ -n "$m69_report_dir" ]; then
  echo "[gate] tensor_m69_report_dir=\"$m69_report_dir\""
fi
if [ -n "$m70_report_dir" ]; then
  echo "[gate] tensor_m70_report_dir=\"$m70_report_dir\""
fi
if [ -n "$m71_report_dir" ]; then
  echo "[gate] tensor_m71_report_dir=\"$m71_report_dir\""
fi
if [ -n "$m72_report_dir" ]; then
  echo "[gate] tensor_m72_report_dir=\"$m72_report_dir\""
fi
if [ -n "$m73_report_dir" ]; then
  echo "[gate] tensor_m73_report_dir=\"$m73_report_dir\""
fi
if [ -n "$m74_report_dir" ]; then
  echo "[gate] tensor_m74_report_dir=\"$m74_report_dir\""
fi
if [ -n "$m75_report_dir" ]; then
  echo "[gate] tensor_m75_report_dir=\"$m75_report_dir\""
fi
if [ -n "$m76_report_dir" ]; then
  echo "[gate] tensor_m76_report_dir=\"$m76_report_dir\""
fi
if [ -n "$m77_report_dir" ]; then
  echo "[gate] tensor_m77_report_dir=\"$m77_report_dir\""
fi
if [ -n "$m78_report_dir" ]; then
  echo "[gate] tensor_m78_report_dir=\"$m78_report_dir\""
fi
if [ -n "$m79_report_dir" ]; then
  echo "[gate] tensor_m79_report_dir=\"$m79_report_dir\""
fi
if [ -n "$m80_report_dir" ]; then
  echo "[gate] tensor_m80_report_dir=\"$m80_report_dir\""
fi
if [ -n "$m81_report_dir" ]; then
  echo "[gate] tensor_m81_report_dir=\"$m81_report_dir\""
fi
if [ -n "$m82_report_dir" ]; then
  echo "[gate] tensor_m82_report_dir=\"$m82_report_dir\""
fi
if [ -n "$m83_report_dir" ]; then
  echo "[gate] tensor_m83_report_dir=\"$m83_report_dir\""
fi
if [ -n "$m84_report_dir" ]; then
  echo "[gate] tensor_m84_report_dir=\"$m84_report_dir\""
fi
if [ -n "$m85_report_dir" ]; then
  echo "[gate] tensor_m85_report_dir=\"$m85_report_dir\""
fi
if [ -n "$m86_report_dir" ]; then
  echo "[gate] tensor_m86_report_dir=\"$m86_report_dir\""
fi
if [ -n "$m87_report_dir" ]; then
  echo "[gate] tensor_m87_report_dir=\"$m87_report_dir\""
fi
if [ -n "$m88_report_dir" ]; then
  echo "[gate] tensor_m88_report_dir=\"$m88_report_dir\""
fi
if [ -n "$m89_report_dir" ]; then
  echo "[gate] tensor_m89_report_dir=\"$m89_report_dir\""
fi
if [ -n "$m90_report_dir" ]; then
  echo "[gate] tensor_m90_report_dir=\"$m90_report_dir\""
fi
if [ -n "$m91_report_dir" ]; then
  echo "[gate] tensor_m91_report_dir=\"$m91_report_dir\""
fi
if [ -n "$m92_report_dir" ]; then
  echo "[gate] tensor_m92_report_dir=\"$m92_report_dir\""
fi
if [ -n "$m93_report_dir" ]; then
  echo "[gate] tensor_m93_report_dir=\"$m93_report_dir\""
fi
if [ -n "$m94_report_dir" ]; then
  echo "[gate] tensor_m94_report_dir=\"$m94_report_dir\""
fi
if [ -n "$m95_report_dir" ]; then
  echo "[gate] tensor_m95_report_dir=\"$m95_report_dir\""
fi
if [ -n "$m96_report_dir" ]; then
  echo "[gate] tensor_m96_report_dir=\"$m96_report_dir\""
fi
if [ -n "$m97_report_dir" ]; then
  echo "[gate] tensor_m97_report_dir=\"$m97_report_dir\""
fi
if [ -n "$m98_report_dir" ]; then
  echo "[gate] tensor_m98_report_dir=\"$m98_report_dir\""
fi
if [ -n "$m99_report_dir" ]; then
  echo "[gate] tensor_m99_report_dir=\"$m99_report_dir\""
fi
if [ -n "$m100_report_dir" ]; then
  echo "[gate] tensor_m100_report_dir=\"$m100_report_dir\""
fi
if [ -n "$m101_report_dir" ]; then
  echo "[gate] tensor_m101_report_dir=\"$m101_report_dir\""
fi
if [ -n "$m102_report_dir" ]; then
  echo "[gate] tensor_m102_report_dir=\"$m102_report_dir\""
fi
if [ -n "$m103_report_dir" ]; then
  echo "[gate] tensor_m103_report_dir=\"$m103_report_dir\""
fi
if [ -n "$m104_report_dir" ]; then
  echo "[gate] tensor_m104_report_dir=\"$m104_report_dir\""
fi
if [ -n "$m105_report_dir" ]; then
  echo "[gate] tensor_m105_report_dir=\"$m105_report_dir\""
fi
if [ -n "$m106_report_dir" ]; then
  echo "[gate] tensor_m106_report_dir=\"$m106_report_dir\""
fi
if [ -n "$m107_report_dir" ]; then
  echo "[gate] tensor_m107_report_dir=\"$m107_report_dir\""
fi
if [ -n "$m108_report_dir" ]; then
  echo "[gate] tensor_m108_report_dir=\"$m108_report_dir\""
fi
if [ -n "$m109_report_dir" ]; then
  echo "[gate] tensor_m109_report_dir=\"$m109_report_dir\""
fi
if [ -n "$m110_report_dir" ]; then
  echo "[gate] tensor_m110_report_dir=\"$m110_report_dir\""
fi
