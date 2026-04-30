from __future__ import annotations

import os
from typing import Dict, Tuple

from .utils import tensor_print


def resolve_run_dirs(script_file: str, env_key: str = "TENSOR_SI_RUN_DIR") -> Tuple[str, str]:
    script_dir = os.path.dirname(os.path.abspath(script_file))
    analysis_dir = os.path.join(script_dir, "analysis")
    env = os.environ.get(env_key, "").strip()
    run_dir = os.path.abspath(env) if env else os.path.join(analysis_dir, "tensor_latest")
    return analysis_dir, run_dir


def make_run_artifact_paths(run_dir: str) -> Dict[str, str]:
    return {
        "mesh_stats_csv": os.path.join(run_dir, "mesh_stats.csv"),
    }


def prepare_run_output_and_stats(
    *,
    sst_module,
    script_file: str,
    default_stats_level: int,
    stats_output_type: str = "sst.statOutputCSV",
    stats_separator: str = ",",
    run_dir_env_key: str = "TENSOR_SI_RUN_DIR",
) -> Tuple[str, str, Dict[str, str]]:
    sst_module.setStatisticLoadLevel(default_stats_level)
    sst_module.setStatisticOutput(stats_output_type)

    analysis_dir, run_dir = resolve_run_dirs(script_file, env_key=run_dir_env_key)
    try:
        os.makedirs(analysis_dir, exist_ok=True)
    except Exception:
        pass
    os.makedirs(run_dir, exist_ok=True)
    tensor_print(f"[tensor_mesh] run output dir: {run_dir}")

    artifacts = make_run_artifact_paths(run_dir)
    sst_module.setStatisticOutputOptions(
        {
            "filepath": artifacts["mesh_stats_csv"],
            "separator": stats_separator,
        }
    )
    return analysis_dir, run_dir, artifacts

