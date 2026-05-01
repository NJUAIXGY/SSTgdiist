# services/workload/layout/（Workload 布局口径归一化）

本目录用于承载 **Workload 层的 neuron layout 口径归一化**，避免 `num_neurons / neurons_per_pe / global_neuron_base` 的历史多义在不同 workload 中各自解释而产生错位。

## 默认内存语义（cacheline）

布局归一化本身与访存粒度无关，但工作负载在解释性能与 `memHierarchy` 统计时必须遵循统一的默认口径：**cacheline 粒度**作为对外搬运/统计单位。任何
row-streaming/DMA 等更强假设必须在 workload/synapse 层显式声明并在输出中标注。

## 统一口径（NormalizedNeuronLayout）

- `num_neurons`：**每 core 的 neuron 行数**（`neurons_per_core`）
- `neurons_per_pe`：**每 PE 的 neuron 总数**（`neurons_per_pe = cores_per_pe * neurons_per_core`）
- `global_neuron_base`：**本 core 的 global base**（`core_neuron_base`）

## 文件

- `NormalizedNeuronLayout.{h,cc}`
  - `normalizeNeuronLayout(node_id, core_id, total_nodes, cores_per_pe, num_neurons_param, neurons_per_pe_param, global_neuron_base_param, weights_cols)`
  - 输出：
    - `neurons_per_core / neurons_per_pe`
    - `node_neuron_base / core_neuron_base`
    - `base_match_score`（用于诊断：参数 base 与推导 base 是否一致）
