from __future__ import annotations

import os
from typing import Dict, Tuple

from .utils import mesh_print


def resolve_run_dirs(script_file: str, env_key: str = "MESH_RUN_DIR") -> Tuple[str, str]:
    script_dir = os.path.dirname(os.path.abspath(script_file))
    analysis_dir = os.path.join(os.path.dirname(script_dir), "analysis")
    env = os.environ.get(env_key, "").strip()
    run_dir = os.path.abspath(env) if env else os.path.join(analysis_dir, "mesh_latest")
    return analysis_dir, run_dir


def make_run_artifact_paths(run_dir: str) -> Dict[str, str]:
    return {
        "mesh_stats_csv": os.path.join(run_dir, "mesh_stats.csv"),
        "granules_csv": os.path.join(run_dir, "granules.csv"),
        "window_metrics_csv": os.path.join(run_dir, "window_metrics.csv"),
        "spikes_mesh_csv": os.path.join(run_dir, "spikes_mesh.csv"),
    }


def prepare_run_output_and_stats(
    *,
    sst_module,
    script_file: str,
    default_stats_level: int,
    stats_output_type: str = "sst.statOutputCSV",
    stats_separator: str = ",",
    run_dir_env_key: str = "MESH_RUN_DIR",
) -> Tuple[str, str, Dict[str, str]]:
    """
    Prepare run output directory and SST statistics output settings.

    Must be invoked before creating any SST components.
    Returns (analysis_dir, run_output_dir, artifacts).
    """

    sst_module.setStatisticLoadLevel(default_stats_level)
    sst_module.setStatisticOutput(stats_output_type)

    analysis_dir, run_dir = resolve_run_dirs(script_file, env_key=run_dir_env_key)
    try:
        os.makedirs(analysis_dir, exist_ok=True)
    except Exception:
        pass
    os.makedirs(run_dir, exist_ok=True)
    mesh_print(f"[mesh] run output dir: {run_dir}")

    artifacts = make_run_artifact_paths(run_dir)
    sst_module.setStatisticOutputOptions(
        {
            "filepath": artifacts["mesh_stats_csv"],
            "separator": stats_separator,
        }
    )
    return analysis_dir, run_dir, artifacts


def pe_output_dir(run_dir: str, pe_id: int) -> str:
    return os.path.join(run_dir, f"pe{pe_id:02d}")


def core_window_metrics_csv_path(run_dir: str, pe_id: int, core_id: int) -> str:
    return os.path.join(pe_output_dir(run_dir, pe_id), f"core{core_id:02d}_window_metrics.csv")


def resolve_spike_data_dir(script_file: str) -> str:
    script_dir = os.path.dirname(os.path.abspath(script_file))
    project_root = os.path.dirname(script_dir)
    return os.path.join(project_root, "spike_data")


def resolve_complex_spike_file(spike_dir: str, pe_id: int, class_name: str) -> str:
    return os.path.join(spike_dir, f"complex_input_pe_{pe_id}_class_{class_name}.txt")
