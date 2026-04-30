from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .utils import mesh_print


def resolve_fixed_4x4_layers() -> Dict[str, List[int]]:
    """
    Legacy 4x4 mesh layer partitioning.

    Note: kept intentionally 'fixed' to preserve historical behavior even if mesh_size
    is overridden to non-4 values.
    """

    return {
        "input_layer": list(range(0, 4)),
        "hidden_layer_1": list(range(4, 8)),
        "hidden_layer_2": list(range(8, 12)),
        "output_layer": list(range(12, 16)),
    }


def resolve_default_classification_task() -> Dict[str, Any]:
    """
    Legacy 4-class input stimulus frequencies.
    """

    return {
        "num_classes": 4,
        "class_freqs": [40, 80, 120, 200],
        "class_names": ["A", "B", "C", "D"],
    }


def print_classification_banner(
    *,
    mesh_size: int,
    total_nodes: int,
    layers: Dict[str, List[int]],
    task: Dict[str, Any],
) -> None:
    input_layer = layers["input_layer"]
    hidden_layer_1 = layers["hidden_layer_1"]
    hidden_layer_2 = layers["hidden_layer_2"]
    output_layer = layers["output_layer"]

    class_freqs = list(task.get("class_freqs", [40, 80, 120, 200]))
    class_a, class_b, class_c, class_d = class_freqs[:4]

    mesh_print(f"🧠 分层神经网络分类任务: {mesh_size}x{mesh_size} = {total_nodes}个节点")
    mesh_print("📊 网络架构:")
    mesh_print(f"  输入层 (PE 0-3): {input_layer}")
    mesh_print(f"  隐藏层1 (PE 4-7): {hidden_layer_1}")
    mesh_print(f"  隐藏层2 (PE 8-11): {hidden_layer_2}")
    mesh_print(f"  输出层 (PE 12-15): {output_layer}")
    mesh_print(f"🎯 复杂分类任务: 类别A({class_a}Hz) vs 类别B({class_b}Hz) vs 类别C({class_c}Hz) vs 类别D({class_d}Hz)")
    mesh_print("⚙️  权重加载模式: 启用内存权重，使用分层设计的权重文件")


def build_layers_cfg(
    *,
    layers: Dict[str, List[int]],
    thresholds: Any,
    core_tau_mem: float,
    core_t_ref: int = 2,
    init_default_weight: float = 0.5,
) -> Dict[str, Any]:
    return {
        "input_layer": layers["input_layer"],
        "hidden_layer_1": layers["hidden_layer_1"],
        "hidden_layer_2": layers["hidden_layer_2"],
        "thresholds": thresholds,
        "core_tau_mem": float(core_tau_mem),
        "core_t_ref": int(core_t_ref),
        "init_default_weight": float(init_default_weight),
    }
