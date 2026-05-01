#ifndef _H_SST_SNN_PE_SUBCOMPONENT
#define _H_SST_SNN_PE_SUBCOMPONENT

#include <sst/core/subcomponent.h>
#include <sst/core/link.h>
#include <sst/core/output.h>
#include <sst/core/shared/sharedArray.h>
#include <queue>
#include <deque>
#include <map>
#include <list>
#include <unordered_map>
#include <unordered_set>
#include <memory>
#include <mutex>
#include <functional>
#include <utility>
#include <string>
#include <vector>
#include "SnnCoreAPI.h"
#include "SnnProfiler.h"  // 轻量级性能分析（条件编译）
#include "ISnnComputeCore.h"
#include "ICoreWorkload.h"
#include "ICoreControlHooks.h"
#include "ICoreMemoryLink.h"
#include "IGlobalStepHooks.h"
#include "IGlobalStepCreditHooks.h"
#include "ILoaderReadyHooks.h"
#include "IGasOrchestrator.h"
#include "IGasStageSink.h"

namespace SST { namespace SnnDL {

class SpikeEvent;
class NocSpikeTransport;
class BcsrWeightManager;
class StdMemEndpoint;
class ISnnAccelRuntimeServices;
class ISnnSpikeCommWorkload;
class IGasStageSink;
class IWeightReader;
class IMemoryAccess;

class IPeAggregation; // PE级汇聚接口（避免依赖 MultiCorePE 具体实现）
class AccumulatorOps;
class WeightCacheOps;
class RiscvSnnShadowRuntimeServices;
struct WeightAccessor;
class WeightMemorySubsystem;
class SpikeCommSubsystem;
	class SynapseRouteSubsystem;
	struct GasOpData;
	class ICoreWorkload;
    class ISpikeWorkload;

class SnnPESubComponent : public SnnCoreAPI,
                          public ICoreControlHooks,
                          public ICoreMemoryLink,
                          public IGlobalStepHooks,
                          public IGlobalStepCreditHooks,
                          public ILoaderReadyHooks,
                          public IGasOrchestrator,
                          public IGasStageSink {
public:
    SST_ELI_REGISTER_SUBCOMPONENT(
        SnnPESubComponent,
        "SnnDL",
        "SnnPESubComponent",
        SST_ELI_ELEMENT_VERSION(1, 0, 0),
        "SNN Processing Element SubComponent",
        SST::SnnDL::CoreShellAPI
    )

    SST_ELI_DOCUMENT_PARAMS(
        {"core_id", "ID of the core", ""},
        {"compute_core_impl", "Compute core implementation name (default/snn)", "default"},
        // Phase6：通用 workload（默认仍为 SNN；stream 用于通信+内存 read-after-write 验证负载）
        {"workload_impl", "Workload implementation: snn (default) / riscv_snn / stream / traffic / traffic_mem / tensor", "snn"},
        {"stream_mem_enable", "Enable stream memory read/write verify (0/1)", "1"},
        {"stream_mem_period_cycles", "Issue one stream write per N cycles (0=as fast as possible)", "100"},
        {"stream_mem_region_bytes", "Stream memory region size in bytes (0=disable mem)", "4096"},
        {"stream_mem_req_bytes", "Stream memory request size in bytes", "64"},
        {"stream_mem_stride_bytes", "Stream memory stride in bytes", "64"},
        {"stream_mem_max_outstanding", "Max outstanding stream mem requests (write+read)", "16"},
        {"stream_comm_enable", "Enable stream RawBytes NoC traffic (0/1)", "1"},
        {"stream_comm_period_cycles", "Send one stream packet per N cycles (0=disable)", "1000"},
        {"stream_comm_payload_bytes", "RawBytes payload bytes (excluding header)", "64"},
        {"stream_strict", "Fail-fast on any stream verify error (0/1)", "1"},
        {"stream_seed", "Base seed for stream pattern generation (uint64)", "0"},
        // Phase6+：tensor workload（systolic/GEMM microbench；完全非 SNN）
        {"tensor_m", "Tensor workload: GEMM M dimension", "256"},
        {"tensor_n", "Tensor workload: GEMM N dimension", "256"},
        {"tensor_k", "Tensor workload: GEMM K dimension", "256"},
        {"tensor_element_bytes", "Tensor workload: element size (bytes)", "2"},
        {"tensor_array_m", "Tensor workload: systolic array M", "32"},
        {"tensor_array_n", "Tensor workload: systolic array N", "32"},
        {"tensor_compute_efficiency", "Tensor workload: peak efficiency [0,1]", "1.0"},
        {"tensor_compute_precision", "Tensor workload: compute precision profile (fp16/bf16/fp32/tf32/int8/fp8)", "fp16"},
        {"tensor_compute_profile_override_enable", "Tensor workload: override precision profile with explicit throughput/latency (0/1)", "0"},
        {"tensor_compute_throughput_scale", "Tensor workload: explicit throughput scale when override enabled", "1.0"},
        {"tensor_compute_pipeline_latency_cycles", "Tensor workload: explicit pipeline latency cycles when override enabled", "0"},
        {"tensor_overlap_enable", "Tensor workload: overlap DMA and compute (0/1)", "1"},
        {"tensor_start_cycle", "Tensor workload: start cycle", "1"},
        {"tensor_iterations", "Tensor workload: total iterations (0=unbounded)", "0"},
        {"tensor_mem_enable", "Tensor workload: enable IMemoryAccess reads/writes (0/1)", "1"},
        {"tensor_mem_region_bytes", "Tensor workload: address region bytes (wrap-around)", "1048576"},
        {"tensor_mem_req_bytes", "Tensor workload: memory request bytes", "64"},
        {"tensor_mem_max_outstanding", "Tensor workload: max outstanding memory requests", "32"},
        {"tensor_dataflow", "Tensor workload: dataflow (os/ws/is)", "os"},
        {"tensor_tile_m", "Tensor workload: tile size M (0=use full M)", "0"},
        {"tensor_tile_n", "Tensor workload: tile size N (0=use full N)", "0"},
        {"tensor_tile_k", "Tensor workload: tile size K (0=use full K)", "0"},
        {"tensor_exec_mode", "Tensor workload: execution mode (bulk/tile/program)", "bulk"},
        {"tensor_program_dsl", "Tensor workload: program DSL (exec_mode=program)", ""},
        {"tensor_program_loop", "Tensor workload: loop the program (0/1)", "1"},
        {"tensor_program_issue_width", "Tensor workload: program issue width (ops/cycle, program mode)", "4"},
        {"tensor_program_engine_priority", "Tensor workload: program engine priority (e.g. dma>mxu>vec>coll)", "dma>mxu>vec>coll"},
        {"tensor_vector_elems_per_cycle", "Tensor workload: vector engine elems/cycle (program mode)", "64"},
        {"tensor_vector_pipeline_latency_cycles", "Tensor workload: vector engine pipeline latency cycles (program mode)", "0"},
        {"tensor_tile_schedule", "Tensor workload: tile schedule (auto/mnk/mkn/nkm)", "auto"},
        {"tensor_writeback_policy", "Tensor workload: writeback policy (at_end_of_k)", "at_end_of_k"},
        {"tensor_ub_bytes", "Tensor workload: on-chip unified buffer bytes (0=disable)", "0"},
        {"tensor_acc_bytes", "Tensor workload: on-chip accumulator bytes (0=disable)", "0"},
        {"tensor_onchip_model_enable", "Tensor workload: enable detailed on-chip capacity/port model (0/1)", "0"},
        {"tensor_ub_bank_bytes", "Tensor workload: UB bank bytes (0=inherit tensor_ub_bytes)", "0"},
        {"tensor_ub_read_ports", "Tensor workload: UB read ports per cycle (0=auto when on-chip model enabled)", "0"},
        {"tensor_ub_write_ports", "Tensor workload: UB write ports per cycle (0=auto when on-chip model enabled)", "0"},
        {"tensor_onchip_bank_model_enable", "Tensor workload: enable bank-aware on-chip arbitration/conflict model (0/1)", "0"},
        {"tensor_ub_bank_count", "Tensor workload: UB bank count (bank-aware mode)", "1"},
        {"tensor_ub_bank_select_policy", "Tensor workload: UB bank select policy (interleave/rr/hash)", "interleave"},
        {"tensor_ub_bank_conflict_mode", "Tensor workload: UB bank conflict mode (queue/block)", "queue"},
        {"tensor_acc_bank_bytes", "Tensor workload: ACC bank bytes (0=inherit tensor_acc_bytes)", "0"},
        {"tensor_acc_read_ports", "Tensor workload: ACC read ports per cycle (0=auto when on-chip model enabled)", "0"},
        {"tensor_acc_write_ports", "Tensor workload: ACC write ports per cycle (0=auto when on-chip model enabled)", "0"},
        {"tensor_acc_bank_count", "Tensor workload: ACC bank count (bank-aware mode)", "1"},
        {"tensor_acc_bank_select_policy", "Tensor workload: ACC bank select policy (interleave/rr/hash)", "interleave"},
        {"tensor_acc_bank_conflict_mode", "Tensor workload: ACC bank conflict mode (queue/block)", "queue"},
        {"tensor_bank_queue_depth", "Tensor workload: per-bank queue depth when conflict mode=queue", "16"},
        {"tensor_spill_enable", "Tensor workload: allow UB/ACC overflow spill traffic (0/1)", "0"},
        {"tensor_spill_packet_bytes", "Tensor workload: spill packet bytes", "256"},
        {"tensor_spill_share_noc_budget", "Tensor workload: spill shares noc budget when capped (0/1)", "1"},
        {"tensor_dma_bandwidth_bytes_per_cycle", "Tensor workload: DMA bandwidth (bytes/cycle, 0=disable)", "0"},
        {"tensor_double_buffer", "Tensor workload: enable double-buffer overlap (0/1)", "0"},
        {"tensor_collective_type", "Tensor workload: collective type (none/allreduce/allgather/reducescatter)", "none"},
        {"tensor_collective_blocking", "Tensor workload: treat collective as barrier between iterations (0/1)", "0"},
        {"tensor_collective_scope", "Tensor workload: collective scope (per_core/per_pe/per_system)", "per_core"},
        {"tensor_collective_bytes", "Tensor workload: collective bytes per op", "0"},
        {"tensor_collective_period_cycles", "Tensor workload: collective period cycles", "0"},
        {"tensor_collective_pattern", "Tensor workload: collective pattern (ring/mesh_x/mesh_xy)", "ring"},
        {"tensor_collective_packet_bytes", "Tensor workload: collective packet bytes", "256"},
        {"tensor_collective_algo", "Tensor workload: collective algorithm (legacy_bytes/ring_chunked)", "legacy_bytes"},
        {"tensor_collective_chunk_bytes", "Tensor workload: collective chunk bytes for ring_chunked (0=use packet bytes)", "0"},
        {"tensor_collective_reduce_overhead_cycles", "Tensor workload: per-chunk reduce-to-gather switch overhead cycles", "0"},
        {"tensor_collective_max_inflight_chunks", "Tensor workload: max collective chunks issued per cycle in ring_chunked", "1"},
        {"tensor_collective_credit_enable", "Tensor workload: enable credit-window throttling for collective chunks (0/1)", "0"},
        {"tensor_collective_credit_window_chunks", "Tensor workload: collective credit window in chunks (0=auto)", "0"},
        {"tensor_collective_credit_return_mode", "Tensor workload: credit return mode (event_on_recv/legacy_tick)", "event_on_recv"},
        {"tensor_collective_backpressure_mode", "Tensor workload: collective backpressure mode (hard/soft)", "hard"},
        {"tensor_noc_bandwidth_bytes_per_cycle", "Tensor workload: NoC issue budget (bytes/cycle, collective+comm; 0=uncapped)", "0"},
        {"tensor_collective_overlap_with_compute", "Tensor workload: allow compute/collective overlap (0/1)", "1"},
        {"tensor_collective_issue_priority", "Tensor workload: collective issue priority (control_first/payload_first)", "control_first"},
        {"tensor_comm_enable", "Tensor workload: enable RawBytes NoC traffic (0/1)", "0"},
        {"tensor_comm_period_cycles", "Tensor workload: send one RawBytes packet per N cycles", "0"},
        {"tensor_comm_payload_bytes", "Tensor workload: RawBytes payload bytes", "0"},
        {"tensor_strict", "Tensor workload: fail-fast on missing mem/noc (0/1)", "1"},
        {"tensor_seed", "Tensor workload: base seed (uint64)", "0"},
        {"total_cores", "Total number of cores in the PE", "8"},
        {"global_neuron_base", "Global base ID for neurons in this core", "0"},
        {"num_neurons", "Number of neurons in this core", "64"},
        {"v_thresh", "Neuron threshold voltage", "1.0"},
        {"v_reset", "Neuron reset voltage", "0.0"},
        {"v_rest", "Neuron resting voltage", "0.0"},
        {"tau_mem", "Membrane time constant", "20.0"},
        {"t_ref", "Refractory period in clock cycles", "2"},
        {"base_addr", "Base address for weight fetching", "0"},
        {"node_id", "Node ID of the parent PE", "0"},
        {"verbose", "Verbosity level", "0"},
        {"enable_weight_fetch", "Enable fetching weights from memory", "0"},
        {"write_weights_on_init", "Write default weights to memory on init", "1"},
        {"memory_warmup_cycles", "Cycles to wait before starting memory operations", "1000"},
        {"init_default_weight", "Default weight value to initialize memory with", "0.5"},
        {"max_outstanding_requests", "Maximum number of outstanding memory requests", "16"},
        {"max_cache_entries", "Maximum number of entries in the weight cache", "65536"},
        {"use_event_weight_fallback", "Use weight from spike event if memory fetch fails", "0"},
        {"merge_read_cacheline", "Merge memory reads to cache line size", "1"},
        {"merge_read_row", "Merge memory reads to a full row", "0"},
        {"line_size_bytes", "Cache line size in bytes", "64"},
        // Dense weights physical layout (experiment; default row_major)
        {"dense_layout_mode", "Dense weights layout: row_major (default) | phys_v1", "row_major"},
        {"dense_phys_dram_row_bytes", "Dense weights phys_v1: DRAM row bytes (must match weights_phys generator; 0 disables)", "0"},
        // BCSR physical layout + runtime fetch granularity (default keeps legacy behavior).
        {"bcsr_layout_mode", "BCSR layout mode: flat (default) | rowpack_v1", "flat"},
        {"bcsr_colidx_row_stride_bytes", "BCSR rowpack_v1: row stride bytes for colidx region (0=unused in flat)", "0"},
        {"bcsr_blockdata_row_stride_bytes", "BCSR rowpack_v1: row stride bytes for blockdata region (0=unused in flat)", "0"},
        {"bcsr_blockids_row_stride_bytes", "BCSR rowpack_v1: row stride bytes for blockids region (optional)", "0"},
        {"bcsr_block_fetch_mode", "BCSR blockdata fetch mode: full_block (default) | row_cacheline", "full_block"},
        {"experimental_noc_rowidx_prefetch_enable", "Experimental STORM-PIF: prefetch BCSR row-index metadata from Gather touches (0/1)", "0"},
        {"experimental_noc_rowidx_prefetch_budget_per_tick", "Experimental STORM-PIF: max prefetched block_rows per tick", "4"},
        {"experimental_noc_rowidx_cache_rows", "Experimental STORM-PIF: max cached BCSR row-index rows (0=unlimited)", "1024"},
        {"experimental_noc_rowidx_prefetch_gather_only", "Experimental STORM-PIF: only prefetch when not in Apply window (0/1)", "1"},
        {"experimental_noc_rowidx_prefetch_carry_to_apply_enable", "Experimental STORM-PIF: retain Gather-enqueued rowidx frontier and start detached draining in BeginApply using the current window_seq (0/1)", "0"},
        {"experimental_noc_rowidx_hot_touch_min", "Experimental STORM-PIF v8: min touches per block_row before enqueueing prefetch", "1"},
        {"experimental_noc_rowidx_budget_adapt_enable", "Experimental STORM-PIF v8: enable queue/headroom adaptive prefetch budget (0/1)", "0"},
        {"experimental_noc_rowidx_budget_adapt_max_per_tick", "Experimental STORM-PIF v8: adaptive budget upper bound per tick", "32"},
        {"experimental_noc_rowidx_budget_adapt_q_depth", "Experimental STORM-PIF v8: queue depth target used for adaptive budget scaling", "16"},
        {"experimental_idx2_ingress_prefetch_enable", "Experimental STORM-NIP: prefetch idx2 value lines from Gather ingress touches (0/1)", "0"},
        {"experimental_idx2_ingress_prefetch_budget_per_tick", "Experimental STORM-NIP: base prefetch issue budget per tick", "4"},
        {"experimental_idx2_ingress_prefetch_cache_entries", "Experimental STORM-NIP: max resident idx2 prefetched values in the private L0 cache", "4096"},
        {"experimental_idx2_ingress_prefetch_max_inflight", "Experimental STORM-NIP: per-core inflight cap for idx2 ingress prefetch (0=auto)", "0"},
        {"experimental_idx2_ingress_prefetch_gather_only", "Experimental STORM-NIP: restrict idx2 prefetch to Gather-only windows (0/1)", "1"},
        {"experimental_idx2_ingress_prefetch_carry_to_apply_enable", "Experimental STORM-NIP: retain Gather-enqueued idx2 pending work and continue draining into Apply while still blocking new Apply-stage touches (0/1)", "0"},
        {"experimental_idx2_ingress_prefetch_apply_max_inflight", "Experimental STORM-NIP: Apply-carry inflight cap for retained idx2 prefetches (0=inherit gather cap)", "0"},
        {"experimental_idx2_ingress_prefetch_apply_outstanding_reserve", "Experimental STORM-NIP: reserve this many outstanding slots for non-prefetch demand when carry-to-apply is enabled", "0"},
        {"experimental_idx2_ingress_prefetch_apply_frontier_keep_pending", "Experimental STORM-NIP: at BeginApply keep only this many retained pending idx2 prefetches after touch-rank frontier reordering (0=disable)", "0"},
        {"experimental_idx2_ingress_tail_guard_enable", "Experimental STORM-NIP: drop tail completions that have no waiters in gather-only mode (0/1)", "0"},
        {"experimental_idx2_ingress_budget_adapt_enable", "Experimental STORM-NIP: enable queue/headroom adaptive prefetch budget (0/1)", "0"},
        {"experimental_idx2_ingress_budget_adapt_max_per_tick", "Experimental STORM-NIP: adaptive budget upper bound per tick", "32"},
        {"experimental_idx2_ingress_budget_adapt_q_depth", "Experimental STORM-NIP: queue depth target used for adaptive budget scaling", "16"},
        {"weights_cols", "Number of columns in weight matrix when using global read (post_row_pre_col)", "0"},
        {"index_mode", "Indexing mode: pre_row_post_col (default) or post_row_pre_col", "pre_row_post_col"},
        {"use_soa_neuron_state", "Use Structure-of-Arrays layout for neuron state (0=AoS,1=SoA)", "0"},
        {"use_aosoa_neuron_state", "Use block-wise AoSoA iteration on top of SoA (0/1)", "0"},
        {"aosoa_block_rows", "AoSoA block row width; defaults to bcsr_block_rows when unset", "0"},
        {"state_sram_enable", "Observe-only neuron-state SRAM model enable (0/1)", "0"},
        {"state_sram_capacity_bytes", "Observe-only neuron-state SRAM capacity bytes", "0"},
        {"state_sram_banks", "Observe-only neuron-state SRAM bank count", "16"},
        {"state_sram_ports_per_bank", "Observe-only neuron-state SRAM ports per bank", "1"},
        {"state_sram_bank_interleave_bytes", "Observe-only neuron-state SRAM bank interleave bytes", "4"},
        {"state_sram_t_read_cycles", "Observe-only neuron-state SRAM read cycles", "1"},
        {"state_sram_t_write_cycles", "Observe-only neuron-state SRAM write cycles", "1"},
        {"state_sram_sample_log2", "Observe-only neuron-state SRAM sampling log2", "0"},
        {"state_sram_vmem_base", "Observe-only neuron-state SRAM virtual base for vmem", "12884901888"},
        {"state_sram_refrac_base", "Observe-only neuron-state SRAM virtual base for refrac", "17179869184"},
        {"state_sram_last_spike_base", "Observe-only neuron-state SRAM virtual base for last_spike", "21474836480"},
        {"verify_routing_weights", "Log and verify routing fanout against weight threshold (0/1)", "0"},
        {"enable_detailed_map_log", "Enable detailed logging of neuron mapping", "0"},
        {"route_summary_enable", "Enable one-shot route summary logging per core (0/1)", "0"},
        {"verify_weights", "Enable weight verification", "0"},
        {"weight_verify_samples", "Number of weight samples to verify", "16"},
        {"expected_weight_value", "Expected weight value for verification", "0.0"},
        {"verify_epsilon", "Epsilon for floating point comparison", "1e-4"},
        {"verify_log_each_sample", "Log each weight sample for verification", "0"},
        {"verify_against_file", "Verify weights by comparing memory reads against weight file (0/1)", "0"},
        {"verify_file_template", "Template for per-PE weight files used for verification (e.g., .../classification_weights_pe_{pe}.bin)", ""},
        {"quiet_finish_logs", "Suppress finish() console summaries (0/1)", "0"},
        {"loader_done_key", "SharedArray key toggled by WeightLoader upon completion", ""},
        // Profiling（可选）
        {"enable_profiler", "Enable lightweight profiling for hot functions (0/1)", "0"},
        {"profiler_csv_prefix", "CSV export prefix for profiler (e.g., outputs_large/<run>/profile_core)", ""},
        // 路由模式（默认fixed：沿用内置层间映射；weight_driven：按权重文件驱动扇出）
        {"routing_mode", "Routing mode: fixed (default) or weight_driven", "fixed"},
        {"weights_template", "Template for per-PE weight files, e.g. .../classification_weights_pe_{pe}.bin", ""},
        {"total_nodes", "Total number of PEs/nodes in the system", "16"},
        {"routing_epsilon", "Threshold to treat a weight as non-zero when building routes", "1e-8"},
        {"routing_topk", "Global top-K destinations per source (0=unlimited)", "0"},
        {"routing_topk_per_pe", "Top-K destinations per destination-PE per source (0=unlimited)", "0"},
        // 路由过滤：层间/同PE
        {"route_exclude_self_pe", "Exclude routes targeting the same PE as source (0/1)", "0"},
        {"route_layers_mask", "Allowed layer transitions, e.g. I>H1,H1>H2,H2>O", ""},
        {"route_filter_warn", "Print prominent warning when route filters are enabled (0/1)", "1"},
        {"readresp_zero_fallback", "When DRAM returns 0 for weight, fallback to init_default_weight (0/1)", "0"},
        {"synapse_weight_mode", "Synapse weight sourcing mode: bcsr_gas | gcss_valueonly_dstcore | gcss_valueonly_dstcore_idx2 | gcss_idx2_rowmphf | gcss_valueonly_dstcore_vlf_premphf | gcss_valueonly_dstcore_vlf_premphf_plp", "bcsr_gas"},
        {"gcss_index_template", "Template for per-core GCSS index files, e.g. .../pe{pe:02d}/core{core:02d}.gcss.idx.bin", ""},
        {"weight_sram_model_enable", "Observe-only weight SRAM model master enable (0/1)", "0"},
        {"weight_idx_sram_enable", "Observe-only weight index SRAM enable (0/1)", "0"},
        {"weight_l0_sram_enable", "Observe-only weight L0 SRAM enable (0/1)", "0"},
        {"weight_idx_sram_capacity_bytes", "Observe-only weight index SRAM capacity bytes", "0"},
        {"weight_l0_sram_capacity_bytes", "Observe-only weight L0 SRAM capacity bytes", "0"},
        {"weight_idx_sram_banks", "Observe-only weight index SRAM bank count", "16"},
        {"weight_l0_sram_banks", "Observe-only weight L0 SRAM bank count", "8"},
        {"weight_sram_ports_per_bank", "Observe-only weight SRAM ports per bank", "1"},
        {"weight_sram_bank_interleave_bytes", "Observe-only weight SRAM bank interleave bytes", "4"},
        {"weight_sram_t_read_cycles", "Observe-only weight SRAM read cycles", "1"},
        {"weight_sram_t_write_cycles", "Observe-only weight SRAM write cycles", "1"},
        {"weight_sram_sample_log2", "Observe-only weight SRAM sampling log2", "0"},
        {"weight_idx_sram_base", "Observe-only weight index SRAM virtual base", "4294967296"},
        {"weight_l0_sram_base", "Observe-only weight L0 SRAM virtual base", "8589934592"},
        {"weight_l0_sram_slots", "Observe-only weight L0 SRAM virtual slot count", "1048576"},
        // === GAS Apply/Scatter (Phase-1, default off) ===
        {"apply_acc_enable", "Enable Apply-side accumulation and Scatter-side fire (0/1)", "0"},
        {"acc_high_watermark_bytes", "Accumulator high-watermark in bytes before spilling", "16777216"},
        {"acc_spill_enable", "Enable spilling to per-window delta-log when HWM reached (0/1)", "1"},
        {"stage_events_csv", "Optional path to write stage events (seq, begin/end, apply/scatter)", ""},
        // === Online Gating (event-driven, default off) ===
        {"gating_mode", "Gating mode: off|event (default off)", "off"},
        {"gating_ttl_cycles", "TTL window (cycles) for gating decision validity", "1000"},
        {"gating_scope", "Scope of event gating: inputs|all", "inputs"},
        // 映射框架集成（默认关闭）
        {"mapping_mode", "Mapping-driven routes: off (default) or edges_csv", "off"},
        {"mapping_edges_file", "CSV file of edges: src_global,dst_global,weight(optional)", ""},
        {"mapping_csv_has_header", "Edges CSV has header line (0/1)", "1"},
        {"mapping_csv_separator", "Edges CSV separator (default ',')", ","},
        {"mapping_assume_block_ids", "Assume global_id=pe*rows+row for PE inference (0/1)", "1"},
        // === Supervised Learning (minimal, default off) ===
        {"learning_enabled", "Enable supervised learning features (0/1)", "0"},
        {"learn_window_cycles", "Learning window size in clock cycles", "1000"},
        {"record_membrane", "Record membrane potentials (lightweight; 0/1)", "0"},
        {"record_spike_times", "Record spike times for learning (0/1)", "1"},
        {"surrogate_type", "Surrogate gradient type: superspike|sigmoid|piecewise", "superspike"},
        {"surrogate_beta", "Surrogate gradient beta (steepness)", "5.0"},
        {"error_file", "Per-core error file template (supports {node},{core})", ""},
        {"grad_accum_limit", "Cap on gradient entries before pruning (0=unlimited)", "0"},
        // === Writeback (Phase 3, default off) ===
        {"apply_writeback", "Apply gradient updates to DRAM weights (0/1)", "0"},
        {"apply_every_n_windows", "Apply updates every N learning windows", "1"},
        {"learning_rate", "Learning rate for SGD updates", "0.001"},
        {"weight_decay", "L2 weight decay coefficient (requires cached weight)", "0.0"},
        // === Code-level memory optimizations (optional, default off) ===
        {"use_clock_weight_cache", "Use clock/second-chance policy for weight cache (0/1)", "0"},
        {"apply_dense_acc_enable", "Use dense-array accumulator for GAS Apply (0/1)", "1"},
        {"bcsr_rowptr_file_fallback_enable", "Allow loading BCSR rowptrs from weight files if DRAM read fails", "0"},
        {"enable_extended_diagnostics", "Enable extended diagnostics/logs (replaces SNNDL_DIAG_ENABLE)", "0"},
        {"acc_shadow_verify_enable", "Enable shadow accumulator verification when dense accumulator is active (diagnostic)", "0"},
        // 诊断：禁用权重缓存以强制触发内存读取
        {"disable_weight_cache", "Disable weight cache to force memory reads (diagnostic)", "0"}
        ,
        // 严格GAS：在 BeginApply/Scatter 阶段按窗发起权重读取以填充缓存（不改变ΔV语义，由Scatter统一应用）
        {"window_read_enable", "Issue window-scoped weight reads at BeginApply/Scatter (0/1)", "0"},
        {"window_read_budget", "Max number of (pre,post) single-col reads per window", "1024"},
        {"scatter_diag_limit", "Limit scatter diagnostic logs when window_read_debug=1 (0=disable)", "0"},
        // 安全保护：限制单窗边集合容量，防止极端随机发放导致内存增长
        {"edge_collector_max_capacity", "Max edges per window before overflow protection", "1000000"},
        // Experimental retire policy in WeightMemorySubsystem (default keeps historical behavior).
        {"experimental_retire_policy", "Retire policy: global_inorder | per_post", "global_inorder"},
        {"experimental_gcss_phase_breakdown_enable", "Experimental observability: enable GCSS HOL phase breakdown counters (0/1)", "0"},
        {"experimental_retire_shadow_per_post_enable", "Experimental observability: shadow per-post retire attribution in global_inorder mode (0/1)", "0"},
        {"experimental_gcss_vlf_queue_policy", "Experimental GCSS-VLF queue policy: locality_first | banded_line_fair", "locality_first"},
        {"experimental_gcss_vlf_fair_band_size", "Experimental GCSS-VLF fairness: retire-order edges per age band when queue_policy=banded_line_fair", "256"},
        {"pulse_mfb_gather_preband_enable", "Experimental PULSE-MFB gather-preband barrier enable (0/1)", "0"},
        {"pulse_mfb_gather_barrier_enable", "Experimental PULSE-MFB gather-preband PE barrier enable (0/1)", "0"},
        {"pulse_mfb_gather_top_bands", "Experimental PULSE-MFB gather-preband top bands per window", "32"},
        {"pulse_mfb_gather_lines_per_band", "Experimental PULSE-MFB gather-preband selected lines per band", "4"},
        {"pulse_mfb_gather_window_budget", "Experimental PULSE-MFB gather-preband owner launch budget per window (0=unbounded)", "0"},
        {"pulse_mfb_gather_min_consumers", "Experimental PULSE-MFB gather-preband minimum distinct consumer cores required before launching owner-first seed", "2"},
        {"pulse_osa_metadata_txn_enable", "Enable PULSE-OSA metadata transaction seam (experimental, default off)", "0"},
        {"pulse_osa_metadata_ready_lease_enable", "Enable PULSE-OSA metadata ready lease (experimental, default off)", "0"},
        {"pulse_osa_metadata_ready_lease_ttl", "PULSE-OSA metadata ready lease TTL in cycles (0=disabled)", "0"},
        {"pulse_osa_metadata_object_mask", "PULSE-OSA metadata object mask: rowdescriptor/rowidx/idx2/preband/all", "rowdescriptor"},
        {"experimental_pre_window_profile_export_enable", "Experimental GCSS-PLP: export per-window pre first-touch profile (0/1)", "0"},
        {"experimental_pre_window_profile_export_dir", "Experimental GCSS-PLP: output directory for per-core pre-window profile CSVs", ""}
    )

    SST_ELI_DOCUMENT_STATISTICS(
        {"spikes_received", "Number of spikes received by this core", "spikes", 1},
        {"spikes_generated", "Number of spikes generated by this core", "spikes", 1},
        {"neurons_fired", "Number of times neurons in this core fired", "events", 1},
        {"memory_requests", "Number of memory requests sent", "requests", 1},
        {"weight_cache_hits", "Number of weight cache hits", "hits", 1},
        {"weight_cache_misses", "Number of weight cache misses", "misses", 1},
        {"merged_reads_rows", "Number of memory reads merged to a full row", "requests", 1},
        {"merged_reads_cls", "Number of memory reads merged to a cache line", "requests", 1},
        {"weights_verify_count", "Number of weights verified", "count", 1},
        {"weights_mismatch_count", "Number of weights that failed verification", "count", 1},
        {"weights_verify_sum", "Sum of verified weights for averaging", "value", 1},
        {"routes_entries", "Total number of route entries built for weight-driven routing", "count", 1},
        {"fanout_per_spike", "Fanout size per emitted spike in weight-driven routing", "count", 1},
        {"route3d_native_activation_total", "Total successful route3d native runtime activations", "count", 1},
        {"route3d_native_gating_activation_total", "Successful route3d native runtime activations served by gating", "count", 1},
        {"route3d_native_direct_activation_total", "Successful route3d native runtime activations served directly from routes", "count", 1},
        {"route3d_native_unique_sources_total", "Unique source neurons that activated route3d native runtime fanout", "count", 1},
        {"cache_evictions", "Number of cache evictions in weight cache (LRU)", "count", 1},
        {"pending_reqs_peak", "Peak number of outstanding memory read requests", "count", 1},
        {"cycles_update_neuron", "Approximate cycles spent updating neuron states (layout-dependent)", "cycles", 1},
        {"synaptic_accesses", "Number of synaptic weight applications during spike processing", "count", 1},
        {"scheme1_bytes_read", "Total bytes read issued by Scheme-1 baseline prefetcher", "bytes", 1},
        // Batch-A detailed memory access stats (can be configured as Histogram in Python)
        {"mem_read_latency_cycles", "End-to-end memory read latency in cycles", "cycles", 1},
        {"mem_read_latency_cycles_weights", "Read latency (cycles) for weight-region accesses", "cycles", 1},
        {"mem_read_latency_cycles_state", "Read latency (cycles) for non-weight (state/other) accesses", "cycles", 1},
        {"mem_req_size_bytes", "Request size in bytes at issue time", "bytes", 1},
        {"mem_outstanding_at_issue", "Outstanding inflight requests at issue time", "count", 1},
        // GAS (windowed gather/apply/scatter): upstream totals accumulated at PE层（由 GatherBufferIF 通过 CustomResp 通知）
        {"gas_unique_reads_total", "Unique coalesced read transactions issued by GAS", "reads", 1},
        {"gas_unique_bytes_total", "Total bytes covered by unique coalesced reads (GAS)", "bytes", 1},
        {"gas_row_window_triggers_total", "Total number of row-window bursts triggered (coarse merge)", "count", 1},
        {"gas_row_window_bytes_total", "Total bytes issued by row-window bursts (including holes)", "bytes", 1},
        {"gas_bursts_total", "Total number of bursts (segments) built by GAS", "count", 1},
        {"gas_payload_bytes_total", "Total useful payload bytes requested upstream (sum of sub-reads)", "bytes", 1},
        {"gas_gap_absorbed_bytes_total", "Total gap bytes absorbed by fine-grained gap-merge", "bytes", 1},
        {"exp_noc_rowidx_prefetch_rows_total", "Experimental STORM-PIF: number of BCSR row-index rows prefetched", "rows", 1},
        {"exp_noc_rowidx_prefetch_bytes_total", "Experimental STORM-PIF: bytes issued for BCSR row-index prefetch", "bytes", 1},
        {"exp_noc_rowidx_prefetch_rows_deferred_total", "Experimental STORM-PIF: row-index prefetch rows deferred by inflight pressure", "rows", 1},
        {"exp_noc_rowidx_prefetch_rows_failed_total", "Experimental STORM-PIF: row-index prefetch rows that failed to issue", "rows", 1},
        {"exp_noc_rowidx_cache_hits_total", "Experimental STORM-PIF: row-index cache hits on BCSR requests", "hits", 1},
        {"exp_noc_rowidx_cache_misses_total", "Experimental STORM-PIF: row-index cache misses on BCSR requests", "misses", 1},
        {"exp_noc_rowidx_cache_fills_total", "Experimental STORM-PIF: row-index cache fill operations", "fills", 1},
        {"exp_noc_rowidx_cache_full_drop_total", "Experimental STORM-PIF: row-index cache insert drops due to capacity limit", "drops", 1},
        {"exp_noc_rowidx_cache_entries_final", "Experimental STORM-PIF: final row-index cache entries at finish", "entries", 1},
        {"exp_noc_rowidx_touch_rows_total", "Experimental STORM-PIF: unique touched block_rows enqueued from Gather", "rows", 1},
        {"exp_noc_rowidx_touch_events_total", "Experimental STORM-PIF v8: total Gather touch events observed", "events", 1},
        {"exp_noc_rowidx_rows_filtered_cold_total", "Experimental STORM-PIF v8: touches filtered by hot_touch_min threshold", "events", 1},
        {"exp_noc_rowidx_carry_apply_pending_rows_total", "Experimental STORM-PIF v8: pending Gather-carried rowindex rows visible at BeginApply", "rows", 1},
        {"exp_noc_rowidx_drain_skip_phase_gather_total", "Experimental STORM-PIF v8: drain ticks skipped because carry-to-apply blocks Gather-stage draining", "ticks", 1},
        {"exp_noc_rowidx_drain_skip_phase_apply_disabled_total", "Experimental STORM-PIF v8: drain ticks skipped because gather-only mode disables Apply-stage draining", "ticks", 1},
        {"exp_noc_rowidx_drain_skip_no_pending_total", "Experimental STORM-PIF v8: drain ticks skipped because no pending rowindex frontier remained", "ticks", 1},
        {"exp_noc_rowidx_drain_skip_loader_not_ready_total", "Experimental STORM-PIF v8: drain ticks skipped because loader was not ready", "ticks", 1},
        {"exp_noc_rowidx_drain_skip_rowptr_not_ready_total", "Experimental STORM-PIF v8: drain ticks skipped because BCSR rowptr was not ready", "ticks", 1},
        {"exp_noc_rowidx_drain_skip_budget_zero_total", "Experimental STORM-PIF v8: drain attempts blocked after scheduling budget resolved to zero", "ticks", 1},
        {"exp_noc_rowidx_drain_skip_cache_hit_total", "Experimental STORM-PIF v8: pending frontier rows skipped because rowindex cache was already hot", "rows", 1},
        {"exp_noc_rowidx_drain_skip_detached_inflight_total", "Experimental STORM-PIF v8: pending frontier rows skipped because a detached rowindex prefetch was already inflight", "rows", 1},
        {"exp_noc_rowidx_drain_skip_colidx_inflight_total", "Experimental STORM-PIF v8: pending frontier rows skipped because a window-scoped colidx inflight entry already existed", "rows", 1},
        {"exp_noc_rowidx_drain_skip_empty_row_total", "Experimental STORM-PIF v8: pending frontier rows skipped because rowBounds was empty/invalid", "rows", 1},
        {"exp_noc_rowidx_budget_ticks_total", "Experimental STORM-PIF v8: ticks where prefetch budget was computed", "ticks", 1},
        {"exp_noc_rowidx_budget_effective_total", "Experimental STORM-PIF v8: effective prefetch budget consumed by scheduler", "rows", 1},
        {"exp_noc_rowidx_budget_adapt_ticks_total", "Experimental STORM-PIF v8: ticks where adaptive budget deviated from base budget", "ticks", 1},
        {"exp_noc_rowidx_detached_demand_join_total", "Experimental STORM-PIF v8: demand requests that joined a detached rowindex prefetch already in flight", "joins", 1},
        {"exp_noc_rowidx_detached_demand_waiters_resolved_total", "Experimental STORM-PIF v8: detached-demand waiters resolved from detached rowindex completion", "waiters", 1},
        {"exp_noc_rowidx_detached_demand_fallback_zero_total", "Experimental STORM-PIF v8: detached-demand waiters that fell back to zero because block_col was absent", "waiters", 1},
        {"exp_noc_rowidx_detached_demand_ready_signal_total", "Experimental STORM-PIF v8: detached-demand rowindex ready signals emitted at detached completion", "signals", 1},
        {"exp_noc_rowidx_detached_demand_ready_transition_total", "Experimental STORM-PIF v8: detached-demand rowindex ready transitions emitted at detached completion", "objects", 1},
        {"pulse_metadata_txn_export_total", "PULSE-OSA metadata transaction: exported metadata objects observed by the seam", "objects", 1},
        {"pulse_metadata_txn_owner_launch_total", "PULSE-OSA metadata transaction: owner launches admitted into the seam", "objects", 1},
        {"pulse_metadata_txn_join_live_total", "PULSE-OSA metadata transaction: joins that landed on live owners", "objects", 1},
        {"pulse_metadata_txn_join_ready_total", "PULSE-OSA metadata transaction: joins that landed on ready or leased-ready owners", "objects", 1},
        {"pulse_metadata_txn_late_join_total", "PULSE-OSA metadata transaction: joins that arrived after owner release", "objects", 1},
        {"pulse_metadata_txn_ready_lease_hit_total", "PULSE-OSA metadata transaction: joins served directly from ready lease", "objects", 1},
        {"pulse_metadata_txn_ready_lease_expired_total", "PULSE-OSA metadata transaction: late joins that observed an expired ready lease", "objects", 1},
        {"pulse_metadata_txn_envelope_size_sum_total", "PULSE-OSA metadata transaction: cumulative rowdescriptor envelope size launched by gather replay", "lines", 1},
        {"pulse_metadata_frontier_observed_total", "PULSE metadata frontier: early metadata objects observed before rowdescriptor formation", "objects", 1},
        {"pulse_metadata_frontier_same_window_reobserve_total", "PULSE metadata frontier: repeated observations of the same early metadata object within one window", "objects", 1},
        {"pulse_metadata_frontier_owner_form_candidate_total", "PULSE metadata frontier: early metadata observations that advanced to owner-form candidate", "objects", 1},
        {"pulse_metadata_frontier_join_ready_candidate_total", "PULSE metadata frontier: early metadata observations that advanced to ready-join candidate", "objects", 1},
        {"pulse_metadata_frontier_premphf_base_observed_total", "PULSE metadata frontier: pre-mphf-base observations", "objects", 1},
        {"pulse_metadata_frontier_premphf_base_same_window_reobserve_total", "PULSE metadata frontier: same-window reobserves on pre-mphf-base objects", "objects", 1},
        {"pulse_metadata_frontier_premphf_base_owner_form_candidate_total", "PULSE metadata frontier: pre-mphf-base owner-form candidates", "objects", 1},
        {"pulse_metadata_frontier_premphf_base_join_ready_candidate_total", "PULSE metadata frontier: pre-mphf-base ready-join candidates", "objects", 1},
        {"pulse_metadata_frontier_premphf_band_observed_total", "PULSE metadata frontier: pre-mphf-band observations", "objects", 1},
        {"pulse_metadata_frontier_premphf_band_same_window_reobserve_total", "PULSE metadata frontier: same-window reobserves on pre-mphf-band objects", "objects", 1},
        {"pulse_metadata_frontier_premphf_band_owner_form_candidate_total", "PULSE metadata frontier: pre-mphf-band owner-form candidates", "objects", 1},
        {"pulse_metadata_frontier_premphf_band_join_ready_candidate_total", "PULSE metadata frontier: pre-mphf-band ready-join candidates", "objects", 1},
        {"pulse_metadata_frontier_idx2row_observed_total", "PULSE metadata frontier: idx2row observations", "objects", 1},
        {"pulse_metadata_frontier_idx2row_same_window_reobserve_total", "PULSE metadata frontier: same-window reobserves on idx2row objects", "objects", 1},
        {"pulse_metadata_frontier_idx2row_owner_form_candidate_total", "PULSE metadata frontier: idx2row owner-form candidates", "objects", 1},
        {"pulse_metadata_frontier_idx2row_join_ready_candidate_total", "PULSE metadata frontier: idx2row ready-join candidates", "objects", 1},
        {"pulse_metadata_frontier_rowindex_observed_total", "PULSE metadata frontier: rowindex observations", "objects", 1},
        {"pulse_metadata_frontier_rowindex_same_window_reobserve_total", "PULSE metadata frontier: same-window reobserves on rowindex objects", "objects", 1},
        {"pulse_metadata_frontier_rowindex_owner_form_candidate_total", "PULSE metadata frontier: rowindex owner-form candidates", "objects", 1},
        {"pulse_metadata_frontier_rowindex_join_ready_candidate_total", "PULSE metadata frontier: rowindex ready-join candidates", "objects", 1},
        {"atlas_census_premphf_base_frontier_events_total", "PE-Atlas census: pre-mphf-base frontier evidence totals", "events", 1},
        {"atlas_census_premphf_base_producer_events_total", "PE-Atlas census: pre-mphf-base producer evidence totals", "events", 1},
        {"atlas_census_premphf_base_gate_events_total", "PE-Atlas census: pre-mphf-base gate/proxy evidence totals", "events", 1},
        {"atlas_census_premphf_base_service_events_total", "PE-Atlas census: pre-mphf-base service evidence totals", "events", 1},
        {"atlas_census_premphf_band_frontier_events_total", "PE-Atlas census: pre-mphf-band frontier evidence totals", "events", 1},
        {"atlas_census_premphf_band_producer_events_total", "PE-Atlas census: pre-mphf-band producer evidence totals", "events", 1},
        {"atlas_census_premphf_band_gate_events_total", "PE-Atlas census: pre-mphf-band gate/proxy evidence totals", "events", 1},
        {"atlas_census_premphf_band_service_events_total", "PE-Atlas census: pre-mphf-band service evidence totals", "events", 1},
        {"atlas_census_idx2row_frontier_events_total", "PE-Atlas census: idx2row frontier evidence totals", "events", 1},
        {"atlas_census_idx2row_producer_events_total", "PE-Atlas census: idx2row producer evidence totals", "events", 1},
        {"atlas_census_idx2row_gate_events_total", "PE-Atlas census: idx2row gate/proxy evidence totals", "events", 1},
        {"atlas_census_idx2row_service_events_total", "PE-Atlas census: idx2row service evidence totals", "events", 1},
        {"atlas_census_rowindex_frontier_events_total", "PE-Atlas census: rowindex frontier evidence totals", "events", 1},
        {"atlas_census_rowindex_producer_events_total", "PE-Atlas census: rowindex producer evidence totals", "events", 1},
        {"atlas_census_rowindex_gate_events_total", "PE-Atlas census: rowindex gate/proxy evidence totals", "events", 1},
        {"atlas_census_rowindex_service_events_total", "PE-Atlas census: rowindex service evidence totals", "events", 1},
        {"atlas_census_rowdescriptor_frontier_events_total", "PE-Atlas census: rowdescriptor frontier evidence totals", "events", 1},
        {"atlas_census_rowdescriptor_producer_events_total", "PE-Atlas census: rowdescriptor producer evidence totals", "events", 1},
        {"atlas_census_rowdescriptor_gate_events_total", "PE-Atlas census: rowdescriptor gate/proxy evidence totals", "events", 1},
        {"atlas_census_rowdescriptor_service_events_total", "PE-Atlas census: rowdescriptor service evidence totals", "events", 1},
        {"atlas_proxy_rowindex_materialize_total", "PE-Atlas proxy ledger: rowindex materialize events", "events", 1},
        {"atlas_proxy_rowindex_publicize_total", "PE-Atlas proxy ledger: rowindex publicize events", "events", 1},
        {"atlas_proxy_rowindex_owner_form_total", "PE-Atlas proxy ledger: rowindex owner-form events", "events", 1},
        {"atlas_proxy_rowindex_join_live_total", "PE-Atlas proxy ledger: rowindex join-live events", "events", 1},
        {"atlas_proxy_rowindex_join_ready_total", "PE-Atlas proxy ledger: rowindex join-ready events", "events", 1},
        {"atlas_proxy_rowindex_ready_total", "PE-Atlas proxy ledger: rowindex ready transitions", "events", 1},
        {"atlas_proxy_rowindex_release_total", "PE-Atlas proxy ledger: rowindex release events", "events", 1},
        {"atlas_proxy_rowindex_release_missing_total", "PE-Atlas proxy ledger: rowindex release misses", "events", 1},
        {"atlas_proxy_rowindex_fallback_total", "PE-Atlas proxy ledger: rowindex fallback-to-private events", "events", 1},
        {"atlas_proxy_idx2row_materialize_total", "PE-Atlas proxy ledger: idx2row materialize events", "events", 1},
        {"atlas_proxy_idx2row_publicize_total", "PE-Atlas proxy ledger: idx2row publicize events", "events", 1},
        {"atlas_proxy_idx2row_owner_form_total", "PE-Atlas proxy ledger: idx2row owner-form events", "events", 1},
        {"atlas_proxy_idx2row_join_live_total", "PE-Atlas proxy ledger: idx2row join-live events", "events", 1},
        {"atlas_proxy_idx2row_join_ready_total", "PE-Atlas proxy ledger: idx2row join-ready events", "events", 1},
        {"atlas_proxy_idx2row_ready_total", "PE-Atlas proxy ledger: idx2row ready transitions", "events", 1},
        {"atlas_proxy_idx2row_release_total", "PE-Atlas proxy ledger: idx2row release events", "events", 1},
        {"atlas_proxy_idx2row_release_missing_total", "PE-Atlas proxy ledger: idx2row release misses", "events", 1},
        {"atlas_proxy_idx2row_fallback_total", "PE-Atlas proxy ledger: idx2row fallback-to-private events", "events", 1},
        {"atlas_proxy_premphf_base_materialize_total", "PE-Atlas proxy ledger: pre-mphf-base materialize events", "events", 1},
        {"atlas_proxy_premphf_base_publicize_total", "PE-Atlas proxy ledger: pre-mphf-base publicize events", "events", 1},
        {"atlas_proxy_premphf_base_owner_form_total", "PE-Atlas proxy ledger: pre-mphf-base owner-form events", "events", 1},
        {"atlas_proxy_premphf_base_shared_hit_total", "PE-Atlas proxy ledger: pre-mphf-base shared-hit events", "events", 1},
        {"atlas_proxy_premphf_base_lookup_ready_total", "PE-Atlas proxy ledger: pre-mphf-base lookup-ready events", "events", 1},
        {"atlas_proxy_premphf_base_proxy_only_gap_total", "PE-Atlas proxy ledger: pre-mphf-base proxy-only gap events", "events", 1},
        {"atlas_proxy_premphf_band_materialize_total", "PE-Atlas proxy ledger: pre-mphf-band materialize events", "events", 1},
        {"atlas_proxy_premphf_band_publicize_total", "PE-Atlas proxy ledger: pre-mphf-band publicize events", "events", 1},
        {"atlas_proxy_premphf_band_owner_form_candidate_total", "PE-Atlas proxy ledger: pre-mphf-band owner-form candidates", "events", 1},
        {"atlas_proxy_premphf_band_join_ready_candidate_total", "PE-Atlas proxy ledger: pre-mphf-band join-ready candidates", "events", 1},
        {"atlas_proxy_premphf_band_zero_service_total", "PE-Atlas proxy ledger: pre-mphf-band zero-service events", "events", 1},
        {"gcss_lookup_hit_total", "GCSS lookup hits in gcss_valueonly mode", "hits", 1},
        {"gcss_lookup_miss_total", "GCSS lookup misses in gcss_valueonly mode", "misses", 1},
        {"weight_read_dense_reqs_total", "Issued weight-read requests classified as dense", "requests", 1},
        {"weight_read_dense_bytes_total", "Issued weight-read bytes classified as dense", "bytes", 1},
        {"weight_read_rowptr_reqs_total", "Issued weight-read requests classified as BCSR rowptr", "requests", 1},
        {"weight_read_rowptr_bytes_total", "Issued weight-read bytes classified as BCSR rowptr", "bytes", 1},
        {"weight_read_colidx_reqs_total", "Issued weight-read requests classified as BCSR colidx", "requests", 1},
        {"weight_read_colidx_bytes_total", "Issued weight-read bytes classified as BCSR colidx", "bytes", 1},
        {"weight_read_blockdata_reqs_total", "Issued weight-read requests classified as BCSR blockdata", "requests", 1},
        {"weight_read_blockdata_bytes_total", "Issued weight-read bytes classified as BCSR blockdata", "bytes", 1},
        {"weight_read_gcss_reqs_total", "Issued weight-read requests classified as GCSS value-only", "requests", 1},
        {"weight_read_gcss_bytes_total", "Issued weight-read bytes classified as GCSS value-only", "bytes", 1},
        {"weight_idx_sram_reads_total", "Observe-only weight idx SRAM reads", "reads", 1},
        {"weight_idx_sram_writes_total", "Observe-only weight idx SRAM writes", "writes", 1},
        {"weight_idx_sram_bytes_read_total", "Observe-only weight idx SRAM read bytes", "bytes", 1},
        {"weight_idx_sram_bytes_write_total", "Observe-only weight idx SRAM write bytes", "bytes", 1},
        {"weight_idx_sram_bank_conflict_ticks_total", "Observe-only weight idx SRAM ticks with bank conflicts", "ticks", 1},
        {"weight_idx_sram_predicted_extra_cycles_total", "Observe-only weight idx SRAM predicted extra cycles", "cycles", 1},
        {"weight_idx_sram_resident_bytes_peak", "Observe-only weight idx SRAM resident bytes peak", "bytes", 1},
        {"weight_idx_sram_bank_peak_accesses_per_tick", "Weight idx SRAM peak accesses on any bank within a tick", "accesses", 1},
        {"weight_idx_sram_energy_read_pj_total", "Weight idx SRAM read energy total", "pJ", 1},
        {"weight_idx_sram_energy_write_pj_total", "Weight idx SRAM write energy total", "pJ", 1},
        {"weight_idx_lookup_total", "Total GCSS index lookups", "lookups", 1},
        {"weight_idx_lookup_idx2_total", "Total GCSSIDX2 lookups", "lookups", 1},
        {"weight_l0_sram_reads_total", "Observe-only weight L0 SRAM reads", "reads", 1},
        {"weight_l0_sram_writes_total", "Observe-only weight L0 SRAM writes", "writes", 1},
        {"weight_l0_sram_bytes_read_total", "Observe-only weight L0 SRAM read bytes", "bytes", 1},
        {"weight_l0_sram_bytes_write_total", "Observe-only weight L0 SRAM write bytes", "bytes", 1},
        {"weight_l0_sram_bank_conflict_ticks_total", "Observe-only weight L0 SRAM ticks with bank conflicts", "ticks", 1},
        {"weight_l0_sram_predicted_extra_cycles_total", "Observe-only weight L0 SRAM predicted extra cycles", "cycles", 1},
        {"weight_l0_sram_resident_bytes_peak", "Observe-only weight L0 SRAM resident bytes peak", "bytes", 1},
        {"weight_l0_sram_bank_peak_accesses_per_tick", "Weight L0 SRAM peak accesses on any bank within a tick", "accesses", 1},
        {"weight_l0_sram_energy_read_pj_total", "Weight L0 SRAM read energy total", "pJ", 1},
        {"weight_l0_sram_energy_write_pj_total", "Weight L0 SRAM write energy total", "pJ", 1},
        {"weight_sram_enforced_stall_cycles_total", "Weight SRAM enforced stall cycles", "cycles", 1},
        {"weight_l0_lookup_total", "Total weight L0 lookups", "lookups", 1},
        {"weight_l0_hit_total", "Total weight L0 hits", "hits", 1},
        {"weight_l0_fill_total", "Total weight L0 fills", "fills", 1},
        {"weight_l0_evict_total", "Total weight L0 evictions", "evictions", 1},
        {"core_state_sram_reads_total", "Observe-only neuron-state SRAM reads", "reads", 1},
        {"core_state_sram_writes_total", "Observe-only neuron-state SRAM writes", "writes", 1},
        {"core_state_sram_bytes_read_total", "Observe-only neuron-state SRAM read bytes", "bytes", 1},
        {"core_state_sram_bytes_write_total", "Observe-only neuron-state SRAM write bytes", "bytes", 1},
        {"core_state_sram_bank_conflict_ticks_total", "Observe-only neuron-state SRAM ticks with bank conflicts", "ticks", 1},
        {"core_state_sram_predicted_extra_cycles_total", "Observe-only neuron-state SRAM predicted extra cycles", "cycles", 1},
        {"core_state_sram_resident_bytes_peak", "Observe-only neuron-state SRAM resident bytes peak", "bytes", 1},
        {"core_state_sram_bank_peak_accesses_per_tick", "Neuron-state SRAM peak accesses on any bank within a tick", "accesses", 1},
        {"core_state_sram_energy_read_pj_total", "Neuron-state SRAM read energy total", "pJ", 1},
        {"core_state_sram_energy_write_pj_total", "Neuron-state SRAM write energy total", "pJ", 1},
        {"core_state_sram_stall_cycles_total", "Neuron-state SRAM enforced stall cycles", "cycles", 1},
        {"riscv_snn_workload_selected", "riscv_snn workload: constructor/config path selected workload_impl=riscv_snn", "count", 1},
        {"riscv_snn_firmware_elf_present", "riscv_snn workload: firmware ELF path configured and non-empty", "count", 1},
        {"riscv_snn_firmware_loaded", "riscv_snn workload: firmware ELF loaded successfully", "count", 1},
        {"riscv_snn_backend_runtime_bridge", "riscv_snn workload: backend configured as runtime_bridge", "count", 1},
        {"riscv_snn_firmware_started_count", "riscv_snn workload: firmware retired its first instruction", "count", 1},
        {"riscv_snn_submitted_commands", "riscv_snn workload: commands submitted by firmware or boot driver", "count", 1},
        {"riscv_snn_accepted_commands", "riscv_snn workload: commands accepted by accelerator backend", "count", 1},
        {"riscv_snn_completion_visible_count", "riscv_snn workload: completions made visible to firmware", "count", 1},
        {"riscv_snn_completion_consumed_count", "riscv_snn workload: completions consumed by firmware", "count", 1},
        {"riscv_snn_fused_step_completion_count", "riscv_snn workload: fused-step completions observed", "count", 1},
        {"riscv_snn_fault_count", "riscv_snn workload: faults surfaced to firmware", "count", 1},
        {"riscv_snn_last_completion_status", "riscv_snn workload: last completion status code", "value", 1},
        {"riscv_snn_last_fault_csr", "riscv_snn workload: last architectural fault CSR snapshot", "value", 1},
        {"riscv_snn_backend_runtime_bridge_provider_bound", "riscv_snn workload: runtime-bridge provider ready at bind time", "count", 1},
        // Apply/Scatter端到端统计（Phase-1）
        {"gas_apply_acc_updates_total", "Apply阶段的delta累加次数（有效子读）", "count", 1},
        {"gas_acc_posts_touched_total", "Apply阶段触达的post计数（去重）", "posts", 1},
        {"gas_scatter_spikes_emitted_total", "Scatter阶段发放的spike个数", "spikes", 1},
        {"gas_acc_high_watermark_bytes_total", "累加器峰值占用（bytes）", "bytes", 1},
        {"gas_acc_spill_records_total", "溢写到增量日志的记录条数", "records", 1},
        {"gas_acc_spilled_bytes_total", "溢写到增量日志的有效字节数（payload）", "bytes", 1},
        {"gas_retire_global_hol_cycles_total", "Global retire路径head未ready且存在ready-edge时的阻塞周期", "cycles", 1},
        {"gas_retire_ready_but_blocked_edges_total", "Global retire路径中ready但被head阻塞的edge累计量", "edge_cycles", 1},
        {"gas_retire_per_post_progress_total", "Per-post retire模式下实际退役次数", "count", 1},
        {"gas_retire_samepost_blocked_edges_total", "Global retire路径中同post ready-edge被head阻塞的累计量", "edge_cycles", 1},
        {"gas_retire_crosspost_blocked_edges_total", "Global retire路径中跨post ready-edge被head阻塞的累计量", "edge_cycles", 1},
        {"gas_retire_policy_loss_cycles_total", "Global retire路径中可由更弱contract释放的阻塞周期", "cycles", 1},
        {"gas_retire_policy_loss_edges_total", "Global retire路径中可由更弱contract释放的blocked edge累计量", "edge_cycles", 1},
        {"weight_read_requests", "Number of weight read requests issued by core", "requests", 1},
        {"gas_edge_overflow", "Number of times per-window edge collector hit capacity and stopped recording", "events", 1},
        // Phase6：stream workload 统计（默认不影响 SNN；仅在 workload_impl=stream 时有意义）
        {"stream_mem_writes_issued_total", "Stream workload: total writes issued", "requests", 1},
        {"stream_mem_reads_issued_total", "Stream workload: total reads issued", "requests", 1},
        {"stream_mem_bytes_written_total", "Stream workload: bytes written (issued)", "bytes", 1},
        {"stream_mem_bytes_read_total", "Stream workload: bytes read (issued)", "bytes", 1},
        {"stream_mem_verify_pass_total", "Stream workload: verify pass count", "count", 1},
        {"stream_mem_verify_fail_total", "Stream workload: verify fail count", "count", 1},
        {"stream_pkt_sent_total", "Stream workload: RawBytes packets sent", "packets", 1},
        {"stream_pkt_recv_total", "Stream workload: RawBytes packets received", "packets", 1},
        {"stream_pkt_bad_crc_total", "Stream workload: packets with bad CRC", "packets", 1},
        {"stream_pkt_bad_magic_total", "Stream workload: packets with bad magic/version", "packets", 1}
    )

    SnnPESubComponent(SST::ComponentId_t id, SST::Params& params);
    ~SnnPESubComponent();

    virtual void setParentInterface(IPeAggregation* parent) override;
    void setNocTransport(INocTransport* noc) override;
    void onGlobalStepStart(uint32_t seq) override;
    void onGlobalStepApplyBankCredit(uint32_t seq, uint32_t apply_bank_credit) override;
    void onLoaderReady() override;
    virtual void init(unsigned int phase) override;
    virtual void complete(unsigned int phase) override;
    virtual void setup() override;
    virtual void finish() override;

    virtual void deliverSpike(SpikeEvent* spike) override;
    virtual bool deliverPacket(NocPacketEvent* packet) override;
    virtual bool syntheticEmitNeuronFire(uint32_t neuron_idx, uint64_t now_cycle) override;
    virtual uint64_t syntheticEmitNeuronFireBatch(const std::vector<uint32_t>& neuron_indices, uint64_t now_cycle) override;
    virtual bool hasWork() const override;
    virtual double getUtilization() const override;
    virtual void getStatistics(std::map<std::string, uint64_t>& stats) const override;
    void setMemoryLink(SST::Link* link) override;
    void resetMembraneState(float v_rest) override;
    // 回退驱动：当上层无法自动触发clockTick时，由父组件每拍调用一次
    inline void driveOneCycle() override { (void)clockTick((Cycle_t)0); }
    // 手动触发：结束当前Gather窗口（仅 manual_window_drive 下有效）
    void forceEndGather() override;
    // GAS 控制镜像（cp4'：仅控制平面，数据路径保持原实现）
    void orchestrateBeginGatherWindowSetup();
    void orchestratePrepareApplyWindow() override;
    void orchestrateApplyWindowEntry() override;
    void orchestrateBeginApplyIssueFallback(bool strict_active) override;
    void orchestrateContinueIssueReads();
    void orchestrateIssueFromEdgesDirect();
    void orchestrateBeginScatterSequence() override;
    void orchestrateEndScatterSequence() override;

private:
    // Phase4-Task5: legacy host entrypoints used during cutover.
    // Phase10+: workload=snn 已自洽闭环后，这些函数不再作为“外部可依赖接口”暴露；仅保留为 CoreShell 内部实现细节（回退路径/统计口径）。
    bool legacySnnOnClockTick(uint64_t now_cycle);
    void legacySnnOnWeightsTick(uint64_t now_cycle);
    void legacySnnDeliverSpike(SpikeEvent* spike);
    void legacySnnBindComputeCore(ISnnComputeCore* core);
    IWeightReader* legacySnnGetWeightReader();
    std::unique_ptr<IWeightReader> legacySnnTakeWeightReader();
    bool legacySnnWriteback(const std::unordered_map<uint64_t, float>& grads,
                            float learning_rate,
                            float weight_decay);
    bool legacySnnHasWork() const;
    double legacySnnGetUtilization() const;
    void legacySnnGetStatistics(std::map<std::string, uint64_t>& stats) const;
    void legacySnnOnNeuronFires(const std::vector<uint32_t>& neuron_indices, uint64_t now_cycle);
    void legacySnnOnGasScatterSpikesEmitted(uint32_t seq, uint64_t spikes_emitted);

    // Helper modules extracted to standalone files; keep private access via friends.
    friend struct WeightAccessor;

    // Dense 权重地址映射（用于 naive/legacy 辅助路径；与 WeightMemorySubsystem 的配置保持一致）
    uint64_t denseWeightAddr_(uint32_t row, uint32_t col, uint32_t width) const;

    struct Impl;
    std::unique_ptr<Impl> impl_;

	    // Phase4 Task6.3: unify workload runtime binding points (init / parent / noc).
	    void bindWorkloadRuntime_();
	    void fillStreamRuntime_(ICoreWorkload::Runtime& rt);
        static uint64_t workloadNowNsThunk_(void* ctx);
        bool experimentalWorkloadSerializationEnabled_() const {
            return experimental_workload_serialization_enable_;
        }
        template <typename Fn>
        auto withExperimentalWorkloadSerialization_(Fn&& fn)
            -> decltype(fn()) {
            if (!experimentalWorkloadSerializationEnabled_()) {
                return fn();
            }
            std::lock_guard<std::recursive_mutex> lock(experimental_workload_mutex_);
            return fn();
        }

    // 学习/梯度/误差相关状态已下沉到 compute core（SnnComputeCore）

    // Compute core（动力学/发放/学习）：Phase4 Task6.1 起由 workload=snn 持有并在 init/setup 期间注入。
    // 这里仅保留 non-owning view 以兼容 legacy 控制链路（后续 Task6.x 将逐步下沉到 workload）。
    ISnnComputeCore* compute_core_ = nullptr;
	    // 权重读取适配器：将控制层的 requestWeight/cache 接口包装给 compute core
	    std::unique_ptr<IWeightReader> weight_reader_adapter_;
	    // 直接引用 WeightMemorySubsystem 以便管理窗口预算/并发计数（控制层不再持有本地计数）。
	    WeightMemorySubsystem* weight_mem_subsystem_ = nullptr;
	    // NoC 传输注入（Phase4-A1.3）：优先走 NoC 接口，避免依赖 MultiCorePE 的 send/forward 细节
	    INocTransport* noc_transport_ = nullptr;   // 非拥有；由父组件装配并保证生命周期
	    // SNN comm workload (Phase4 Task6.3): route/comm 迁入 workload=snn 后的窄接口视图（non-owning）
	    ISnnSpikeCommWorkload* snn_comm_workload_ = nullptr;
        // Phase4 Task6.4: GAS/window stage events forwarded to workload=snn (non-owning, optional).
        IGasStageSink* gas_stage_workload_ = nullptr;
        bool experimental_workload_serialization_enable_ = false;
        mutable std::recursive_mutex experimental_workload_mutex_;
    inline void applySynapticDelta_(uint32_t idx, float dv) {
        if (compute_core_) compute_core_->applySynapticDelta(idx, dv);
    }
    inline void resetMembraneState_(float v_rest_value) {
        if (compute_core_) compute_core_->resetMembraneState(v_rest_value);
    }
    inline void onStageBeginGatherCore_(uint32_t seq) {
        if (compute_core_) compute_core_->onStageBeginGather(seq);
    }
    inline void onStageBeginApplyCore_(uint32_t seq) {
        if (compute_core_) compute_core_->onStageBeginApply(seq);
    }
    inline void onStageEndApplyCore_(uint32_t seq) {
        if (compute_core_) compute_core_->onStageEndApply(seq);
    }
    inline void onStageBeginScatterCore_(uint32_t seq) {
        if (compute_core_) compute_core_->onStageBeginScatter(seq);
    }
    inline void onStageEndScatterCore_(uint32_t seq, uint64_t spikes_emitted) {
        if (compute_core_) compute_core_->onStageEndScatter(seq, spikes_emitted);
    }
    inline void clearFiredWindowCore_() {
        if (compute_core_) compute_core_->clearFiredWindow();
    }
    inline void onSpikeDeliveredCore_(SpikeEvent* spike) {
        if (compute_core_) compute_core_->onSpikeDelivered(spike);
    }
	    inline void onSynapticEventCore_(const SynapticEvent& ev) {
	        if (compute_core_) compute_core_->onSynapticEvent(ev);
	    }

    // === GAS Apply/Scatter Phase‑1 ===
    bool apply_acc_enable_ = false;           // gate for end-to-end semantics
    bool readresp_zero_fallback_ = false;     // test-only: map zero read to default weight
    // Accumulator configuration is passed to AccumulatorOps; control layer keeps no container state.
    uint64_t acc_hwm_bytes_cfg_ = 16 * 1024 * 1024; // default 16MiB
    bool acc_spill_enable_cfg_ = true;
    bool acc_dense_enable_cfg_ = false;
    bool acc_shadow_verify_enable_cfg_ = false;
	    std::string stage_events_csv_;
	    enum class GasStage { Idle=0, Gather=1, Apply=2, Scatter=3 };
	    GasStage gas_stage_ = GasStage::Idle;
	    uint32_t curr_stage_seq_ = 0;             // gather/apply/scatter sequence id
        // Global step control-plane: Apply-stage per-bank credit target for this seq (0 means "no override").
        uint32_t global_step_apply_bank_credit_seq_ = 0;
        uint32_t global_step_apply_bank_credit_target_ = 0;
	    // Extracted accumulator/cache helpers (constructed in ctor)
	    std::unique_ptr<AccumulatorOps> acc_ops_;
	    std::unique_ptr<WeightCacheOps> weight_cache_ops_;
    bool bcsr_rowptr_file_fallback_enable_ = false;
    bool enable_extended_diagnostics_ = false; // 参数化诊断开关（替代环境变量 SNNDL_DIAG_ENABLE）
    // Per-window aggregation counters (PE-level flush on stage events)
    uint64_t acc_updates_count_ = 0;
    uint64_t acc_posts_touched_count_ = 0;
    uint64_t acc_spill_records_count_ = 0;
    uint64_t acc_spilled_bytes_sum_ = 0;
    uint64_t acc_hwm_bytes_max_ = 0;
	    // Stats pointers
    Statistic<uint64_t>* stat_gas_apply_acc_updates_total_ = nullptr;
    Statistic<uint64_t>* stat_gas_acc_posts_touched_total_ = nullptr;
    Statistic<uint64_t>* stat_gas_scatter_spikes_emitted_total_ = nullptr;
    Statistic<uint64_t>* stat_gas_acc_hwm_bytes_total_ = nullptr;
    Statistic<uint64_t>* stat_gas_acc_spill_records_total_ = nullptr;
    Statistic<uint64_t>* stat_gas_acc_spilled_bytes_total_ = nullptr;
    Statistic<uint64_t>* stat_gas_retire_global_hol_cycles_total_ = nullptr;
    Statistic<uint64_t>* stat_gas_retire_ready_but_blocked_edges_total_ = nullptr;
    Statistic<uint64_t>* stat_gas_retire_per_post_progress_total_ = nullptr;
    Statistic<uint64_t>* stat_gas_retire_samepost_blocked_edges_total_ = nullptr;
    Statistic<uint64_t>* stat_gas_retire_crosspost_blocked_edges_total_ = nullptr;
    Statistic<uint64_t>* stat_gas_retire_policy_loss_cycles_total_ = nullptr;
    Statistic<uint64_t>* stat_gas_retire_policy_loss_edges_total_ = nullptr;
    // GAS superstep duration statistics (cycles)
    Statistic<uint64_t>* stat_gas_superstep_gather_cycles_  = nullptr;
    Statistic<uint64_t>* stat_gas_superstep_apply_cycles_   = nullptr;
    Statistic<uint64_t>* stat_gas_superstep_scatter_cycles_ = nullptr;
    Statistic<uint64_t>* stat_gas_superstep_total_cycles_   = nullptr;
    // Last window spikes emitted (for stage CSV EndScatter)
    uint64_t spikes_emitted_window_ = 0;
    // Accumulate all spikes fired within current GAS window (regardless of phase)
    // 每窗口发放统计（低开销）：
    // - window_spikes_all_: 窗口内由 handleNeuronFire_ 累计（仅当 apply_acc_enable_ && gas_window_mode_）。
    // - spikes_generated_base_: BeginScatter 时记录的累计发放基线；
    //   若 EndScatter 计算到 to_emit==0，则用 (count_spikes_generated_ - spikes_generated_base_) 兜底，
    //   保证窗口口径与总口径对齐，且仅在缺失时触发一次 O(1) 计算。
    uint64_t window_spikes_all_ = 0;
    uint64_t spikes_generated_base_ = 0;
    // Per-run unique firing tracker（O(N) 字节/核，统计去重口径）
    std::vector<uint8_t> fired_ever_;
    // Diagnostics: recordEdge outcome counters (per GAS window)
    uint64_t diag_edges_record_hits_ = 0;
    uint64_t diag_edges_stage_skips_ = 0;
    uint64_t diag_edges_cond_skips_ = 0;
    // Diagnostics: spike arrival counters by GAS stage (per window)
    uint64_t diag_spikes_stage_gather_ = 0;
    uint64_t diag_spikes_stage_apply_ = 0;
    uint64_t diag_spikes_stage_scatter_ = 0;
    uint64_t diag_spikes_stage_idle_ = 0;
    // Window-read edges/posts/pres 已下沉到 WeightMemorySubsystem（Phase A）
    // Helpers (phase‑1)
    void accReset_();
    void accUpdate_(uint32_t post, float dv);

    // === Learning writeback hook (called by compute core) ===
    bool applyLocalWeightUpdates_(const std::unordered_map<uint64_t, float>& grads,
                                  float learning_rate,
                                  float weight_decay);

    // === Activity f (per-window active axons ratio) ===
    bool activity_stats_enable_ = true;
    uint32_t activity_window_seq_ = 0;
    std::unordered_set<uint32_t> activity_pre_set_;
    inline void activityReset_() { activity_pre_set_.clear(); }
    inline void recordActivePre_(uint32_t pre_global) {
        if (activity_stats_enable_) activity_pre_set_.insert(pre_global);
    }
    // 容量配置与统计
    size_t edge_collector_max_capacity_ = 1000000;
    bool record_edge_cond_warned_ = false;
    bool record_edge_stage_warned_ = false;
    bool record_edge_capacity_warned_ = false;
    Statistic<uint64_t>* stat_gas_edge_overflow_ = nullptr;
    void recordEdge_(uint32_t post_local, uint32_t pre_global);
    inline bool isPreLocal_(uint32_t pre_global) const {
        return (pre_global >= global_neuron_base_) &&
               (pre_global < global_neuron_base_ + num_neurons_);
    }
    inline uint32_t remapPreGlobalModulo_(uint32_t pre_global) const {
        if (num_neurons_ == 0) return 0;
        const uint64_t width = static_cast<uint64_t>(num_neurons_);
        const uint64_t base = static_cast<uint64_t>(global_neuron_base_) -
                              static_cast<uint64_t>(static_cast<uint32_t>(core_id_)) * width;
        const uint64_t diff = static_cast<uint64_t>(pre_global) - base;
        return static_cast<uint32_t>(diff % width);
    }
    inline uint32_t mapPreGlobalToLocal_(uint32_t pre_global) const {
        if (isPreLocal_(pre_global)) {
            return static_cast<uint32_t>(pre_global - global_neuron_base_);
        }
        return remapPreGlobalModulo_(pre_global);
    }
    inline uint32_t weightMatrixWidth_() const {
        return use_post_row_pre_col_ ? weights_cols_ : num_neurons_;
    }
    std::unique_ptr<WeightAccessor> weight_accessor_;
    void activityFlush_();

    bool clockTick(Cycle_t current_cycle);
    bool legacyClockTickInternal_(Cycle_t current_cycle);
    void initializeStatistics();
    uint64_t applyAccumulatedWindowAndScatter_();
    void configureWeightReaderSubsystem_(const Params& params);
    void refreshSharedWeightObjectPlaneBinding_();
    void processLocalSpike(SpikeEvent* spike_event);
    size_t drainReadySpikes_(uint64_t now_ns);
    void requestWeight(uint32_t pre_neuron, uint32_t post_neuron, std::function<void(float)> callback);
    bool loadTextWeights(const std::string& weights_file_path);
    bool loadCSRRowptrFromFile_();
    void logCSRRowptrSummary_();
    void reserveWindowContainers_();
    // Internal helpers for robust memory access
    bool ensureLoaderReady_();
    bool ensureMemoryReady_() const;
    void initStdMemPhase0_();
    // Handle StandardMem responses via template specialization defined out-of-line (keeps StandardMem types out of headers; Phase5.3).
    template <class StdMemRequestT>
    void handleMemoryResponse(StdMemRequestT* req);

    // 方案1辅助
    inline uint32_t scheme1SliceFromPreGlobal_(uint32_t pre_g) const {
        if (scheme1_slices_ == 0) return 0;
        if (scheme1_partition_mod_) return pre_g % scheme1_slices_;
        uint32_t width = std::max<uint32_t>(1, weights_cols_);
        uint32_t seg = width / scheme1_slices_ + ((width % scheme1_slices_) ? 1 : 0);
        uint32_t idx = pre_g / std::max<uint32_t>(1, seg);
        return (idx >= scheme1_slices_) ? (scheme1_slices_ - 1) : idx;
    }
    void scheme1Reset_();
    bool scheme1Tick_(); // 返回 true 表示本周期已由方案1路径完全处理
    void scheme1PrefetchSlice_(uint32_t slice_idx);
    void verifyDenseAccumulator_(uint32_t seq);
    // 核心输出统一路由：控制层不再直接 fire，每拍/每窗调用 endCycle+drainOutputs 后集中路由
    void drainCoreOutputsAndRoute_(uint64_t now_cycle);
    uint64_t routeAndSendOutputs_(const std::vector<FireEvent>& fired);
    size_t pendingMemSize_() const;
    // === 窗口读计数下沉到 WeightMemorySubsystem ===
    void windowStateConfigure_();
    void windowStateBegin_();
    bool windowStateCanIssue_(uint32_t n = 1) const;
    void windowStateNoteIssue_(uint32_t n = 1);
    void windowStateNoteComplete_(uint32_t n = 1);
    uint32_t windowStateIssued_() const;
    uint32_t windowStateOutstanding_() const;

    // Debug/diagnostic switches (params)
    bool read_force_single_ = false; // 当为真时，强制按单元素读取（req_size=4B），用于定位对齐/切片问题

	    // === Phase6: Workload selection ===
	    enum class WorkloadImpl : uint8_t { Snn = 0, RiscvSnn = 1, Stream = 2, Traffic = 3, TrafficMem = 4, Tensor = 5 };
	    WorkloadImpl workload_impl_ = WorkloadImpl::Snn;
        inline bool isRiscvSnnWorkload_() const { return workload_impl_ == WorkloadImpl::RiscvSnn; }
	    inline bool isStreamWorkload_() const { return workload_impl_ == WorkloadImpl::Stream; }
	    inline bool isTrafficWorkload_() const { return workload_impl_ == WorkloadImpl::Traffic; }
	    inline bool isTrafficMemWorkload_() const { return workload_impl_ == WorkloadImpl::TrafficMem; }
	    inline bool isStreamLikeWorkload_() const {
	        return workload_impl_ == WorkloadImpl::Stream || workload_impl_ == WorkloadImpl::TrafficMem;
	    }
	    inline bool isTensorWorkload_() const { return workload_impl_ == WorkloadImpl::Tensor; }
	    inline bool isNonSnnWorkload_() const { return workload_impl_ != WorkloadImpl::Snn; }

	    // Phase6.3：workload 插件（Phase6/Phase3）；当前仅 stream 通过工厂创建，SNN 保持原快路径。
	    std::unique_ptr<ICoreWorkload> workload_;
        std::unique_ptr<RiscvSnnShadowRuntimeServices> riscv_snn_runtime_bridge_;
        ISnnAccelRuntimeServices* accel_runtime_services_ = nullptr;
        // Phase4（方案 B）：仅 SNN workload 需要 SpikeEvent 语义；在初始化阶段缓存指针，热路径避免 RTTI。
        ISpikeWorkload* spike_workload_ = nullptr; // non-owning; points into workload_
        // Phase7 (opt-in): allow migrating strict window-read spike input into workload=snn.
        bool workload_spike_input_enable_ = false;
	    static void reportStreamMemIssueThunk_(void* ctx, size_t bytes);
        static void reportSnnMemIssueThunk_(void* ctx, size_t bytes);
        static void reportApplyScatterThunk_(void* ctx,
                                             uint64_t acc_updates,
                                             uint64_t posts_touched,
                                             uint64_t spikes_emitted,
                                             uint64_t hwm_bytes,
                                             uint64_t spill_records,
                                             uint64_t spilled_bytes);
        static void requestGasEndGatherThunk_(void* ctx, uint32_t superstep);
        static void requestGasEndScatterThunk_(void* ctx, uint32_t superstep);

    IPeAggregation* parent_pe_cached_ = nullptr;
    Output* output_;
    std::unique_ptr<StdMemEndpoint> stdmem_ep_;
    bool clock_tick_logged_ = false;
    SST::Link* memory_link_;

    int core_id_;
    int total_cores_;
    uint64_t global_neuron_base_;
    uint32_t num_neurons_;
    uint64_t base_addr_;
    uint32_t node_id_;
    uint32_t total_nodes_cfg_ = 1;
    int verbose_;
    // 路由/目的节点计算所需：每个PE的神经元数（与 num_neurons_ 不同，后者为本core行数）
    uint32_t neurons_per_pe_cfg_ = 0;
    bool enable_weight_fetch_;
    bool write_weights_on_init_;
    uint64_t memory_warmup_cycles_;
    float init_default_weight_;
    uint32_t max_outstanding_requests_;
    bool use_event_weight_fallback_;
    bool base_addr_log_once_ = false;
    bool route_summary_enable_ = false;
    bool route_summary_logged_ = false;
    bool event_weight_fallback_warned_;
    bool merge_read_cacheline_;
    bool merge_read_row_;
    bool merge_read_auto_ = false; // auto choose best merge strategy (default off)
    uint32_t line_size_bytes_;
    // Dense microbench correctness: byte-exact validation (off by default).
    bool byte_exact_verify_enable_ = false;
    std::string byte_exact_verify_mode_;
    uint32_t byte_exact_verify_row_scale_ = 1024;
    uint32_t byte_exact_verify_max_mismatch_ = 8;
    // BCSR semantic verification (orchestrator-level; off by default).
    // 注意：这是“验证/诊断”能力，不改变正常仿真语义；仅用于实验正确性闭环。
    bool bcsr_semantic_verify_enable_ = false;
    uint32_t bcsr_semantic_verify_max_edges_ = 64;
    uint32_t bcsr_semantic_verify_max_mismatch_ = 8;
    float bcsr_semantic_verify_abs_tol_ = 1e-6f;
    float bcsr_semantic_verify_rel_tol_ = 1e-6f;
    // GAS control (component-driven phases)
    bool gas_enable_ = false; // enable GAS control-plane (v1: Begin/EndGather per tick)
    bool gas_window_mode_ = false; // 当为true时，不再每周期发送Begin/EndGather，由下游window驱动
    std::string loader_done_key_;
    bool wait_for_loader_done_ = false;
    bool loader_ready_latched_ = false;
    bool loader_ready_logged_ = false;
    SST::Shared::SharedArray<int> loader_done_shared_;
    bool loader_done_shared_initialized_ = false;

    // ===== 方案1（slice 顺序执行）开关与参数 =====
    // 说明：在一个 superstep 内，先 Gather 收集所有脉冲事件，然后按 slice=0..N-1 的顺序：
    //  1) 载入该 slice 需要的数据（预取对应的权重区间到本地缓存）
    //  2) 对该 slice 的所有脉冲执行计算（Apply）
    //  3) 在 Scatter 阶段统一触发膜电位发放与外发（可选）
    // 默认关闭；启用后将覆盖常规逐周期处理路径。
    bool scheme1_enable_ = false;
    uint32_t scheme1_slices_ = 8;              // 切片数
    uint64_t scheme1_gather_cycles_cfg_ = 100; // Gather 窗口时长（cycles）
    uint64_t scheme1_slice_gap_cycles_ = 0;    // 相邻 slice 间的间隔（cycles）
    uint64_t scheme1_scatter_cycles_ = 1;      // Scatter 持续时长（cycles）
    // 分片映射方式：按 pre_global 连续区间划分（更贴近行/列局部性）
    bool scheme1_partition_mod_ = false;       // 为 true 则按取模；默认按连续区间
    // 运行期状态
    enum class Scheme1Stage { Idle=0, Gather=1, Apply=2, Scatter=3 };
    Scheme1Stage scheme1_stage_ = Scheme1Stage::Idle;
    uint32_t scheme1_current_slice_ = 0;
    uint64_t scheme1_stage_counter_ = 0;
    bool scheme1_prefetch_issued_ = false;
    uint32_t scheme1_pending_prefetch_ = 0;    // 仍在等待的预取响应计数
    bool s1_is_issuing_prefetch_ = false;      // 诊断标签：本周期是否处于 scheme1 预取发起阶段
    std::vector<std::deque<SpikeEvent*>> scheme1_slice_queues_;
    bool scheme1_queues_inited_ = false;       // 仅首次分配队列；之后跨superstep保留
    bool scheme1_first_superstep_ = true;      // 第一次superstep用于初始化current_slice_

    // 新增：全网读取模式参数
    uint32_t weights_cols_;   // 列数（例如16x256中的256）
    // 诊断：ΔV 汇总（每窗复位）
    double diag_dv_sum_window_ = 0.0;
    uint64_t diag_dv_updates_nonzero_ = 0;
    uint64_t diag_posts_acc_nonzero_ = 0;
    bool use_post_row_pre_col_; // 索引模式：false=pre_row_post_col，true=post_row_pre_col
    bool enable_detailed_map_log_;
    bool log_weight_details_;
    bool detailed_log_emitted_ = false;
    bool verify_routing_weights_ = false;

    bool verify_weights_ = false;
    // Optional barrier cycles to allow external weight loaders to finish (default 0)
    uint64_t loader_barrier_cycles_ = 0;
    // 控制收尾阶段的控制台日志
    bool quiet_finish_logs_ = false;
    
    // 权重文件路径
    std::string weights_file_path_;
    inline void recordSynapticAccess_() {
        count_synaptic_accesses_++;
        if (stat_synaptic_accesses_) stat_synaptic_accesses_->addData(1);
    }
    void handleNeuronFire_(uint32_t neuron_idx, float v_before, float v_after);
    std::queue<SpikeEvent*> incoming_spikes_;
    bool drainIncomingSpikesDeterministic_();
    bool weightCacheTryGet_(uint64_t key, float& out);
    void weightCacheStore_(uint64_t key, float value);
    bool window_read_enable_ = false;   // 严格GAS：按窗发起权重读取
    uint32_t window_read_budget_ = 1024;
    bool window_read_debug_ = false;    // 控制窗口读相关调试日志
    uint32_t scatter_diag_limit_ = 0;   // 仅在 window_read_debug=1 时生效
    uint32_t scatter_diag_count_ = 0;
    uint32_t debug_window_log_count_ = 0;
    // Debug instrumentation
    uint32_t debug_window_idx_ = 0;
    uint32_t pending_reqs_peak_ = 0;
    uint64_t bcsr_req_edges_ = 0;
    uint64_t bcsr_req_wait_rowptr_ = 0;
    uint64_t bcsr_req_block_hit_ = 0;
    uint64_t bcsr_req_block_miss_ = 0;
    Cycle_t total_cycles_;
    Cycle_t active_cycles_;
    bool boot_read_sent_;
    bool boot_write_sent_;
    bool weights_initialized_;
    bool memory_ready_;
    bool first_cache_hit_logged_ = false;
    bool first_cache_miss_logged_ = false;

    Statistic<uint64_t>* stat_spikes_received_;
    Statistic<uint64_t>* stat_spikes_generated_;
    Statistic<uint64_t>* stat_neurons_fired_;
    Statistic<uint64_t>* stat_memory_requests_;
    Statistic<uint64_t>* stat_weight_cache_hits_;
    Statistic<uint64_t>* stat_weight_cache_misses_;
    Statistic<uint64_t>* stat_merged_reads_rows_;
    Statistic<uint64_t>* stat_merged_reads_cls_;
    Statistic<uint64_t>* stat_weights_verify_count_;
    Statistic<uint64_t>* stat_weights_mismatch_count_;
    Statistic<double>* stat_weights_verify_sum_;
    // 扩展统计
    Statistic<uint64_t>* stat_routes_entries_ = nullptr;
    Statistic<uint64_t>* stat_fanout_per_spike_ = nullptr;
    Statistic<uint64_t>* stat_route3d_native_activation_total_ = nullptr;
    Statistic<uint64_t>* stat_route3d_native_gating_activation_total_ = nullptr;
    Statistic<uint64_t>* stat_route3d_native_direct_activation_total_ = nullptr;
    Statistic<uint64_t>* stat_route3d_native_unique_sources_total_ = nullptr;
    Statistic<uint64_t>* stat_cache_evictions_ = nullptr;
    Statistic<uint64_t>* stat_pending_reqs_peak_ = nullptr;
    Statistic<uint64_t>* stat_cycles_update_neuron_ = nullptr;
    Statistic<uint64_t>* stat_synaptic_accesses_ = nullptr;
    // Scheme1 baseline bytes read (sum of issued Read sizes in scheme1PrefetchSlice_)
    Statistic<uint64_t>* stat_s1_bytes_read_ = nullptr;
    // 门控诊断：权重读请求发起计数（用于判定发起端是否触发）
    Statistic<uint64_t>* stat_weight_read_requests_ = nullptr;
    // GAS totals accumulated from GatherBufferIF via CustomResp
    Statistic<uint64_t>* stat_gas_unique_reads_total_ = nullptr;
    Statistic<uint64_t>* stat_gas_unique_bytes_total_ = nullptr;
    Statistic<uint64_t>* stat_gas_row_window_triggers_total_ = nullptr;
    Statistic<uint64_t>* stat_gas_row_window_bytes_total_ = nullptr;
    Statistic<uint64_t>* stat_gas_bursts_total_ = nullptr;
    Statistic<uint64_t>* stat_gas_payload_bytes_total_ = nullptr;
    Statistic<uint64_t>* stat_gas_gap_absorbed_bytes_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_prefetch_rows_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_prefetch_bytes_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_prefetch_rows_deferred_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_prefetch_rows_failed_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_cache_hits_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_cache_misses_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_cache_fills_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_cache_full_drop_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_cache_entries_final_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_touch_rows_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_touch_events_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_rows_filtered_cold_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_carry_apply_pending_rows_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_drain_skip_phase_gather_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_drain_skip_phase_apply_disabled_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_drain_skip_no_pending_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_drain_skip_loader_not_ready_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_drain_skip_rowptr_not_ready_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_drain_skip_budget_zero_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_drain_skip_cache_hit_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_drain_skip_detached_inflight_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_drain_skip_colidx_inflight_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_drain_skip_empty_row_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_budget_ticks_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_budget_effective_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_budget_adapt_ticks_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_detached_demand_join_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_detached_demand_waiters_resolved_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_detached_demand_fallback_zero_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_detached_demand_ready_signal_total_ = nullptr;
    Statistic<uint64_t>* stat_exp_noc_rowidx_detached_demand_ready_transition_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_txn_export_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_txn_owner_launch_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_txn_join_live_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_txn_join_ready_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_txn_late_join_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_txn_ready_lease_hit_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_txn_ready_lease_expired_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_txn_envelope_size_sum_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_frontier_observed_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_frontier_same_window_reobserve_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_frontier_owner_form_candidate_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_frontier_join_ready_candidate_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_frontier_premphf_base_observed_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_frontier_premphf_base_same_window_reobserve_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_frontier_premphf_base_owner_form_candidate_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_frontier_premphf_base_join_ready_candidate_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_frontier_premphf_band_observed_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_frontier_premphf_band_same_window_reobserve_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_frontier_premphf_band_owner_form_candidate_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_frontier_premphf_band_join_ready_candidate_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_frontier_idx2row_observed_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_frontier_idx2row_same_window_reobserve_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_frontier_idx2row_owner_form_candidate_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_frontier_idx2row_join_ready_candidate_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_frontier_rowindex_observed_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_frontier_rowindex_same_window_reobserve_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_frontier_rowindex_owner_form_candidate_total_ = nullptr;
    Statistic<uint64_t>* stat_pulse_metadata_frontier_rowindex_join_ready_candidate_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_census_premphf_base_frontier_events_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_census_premphf_base_producer_events_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_census_premphf_base_gate_events_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_census_premphf_base_service_events_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_census_premphf_band_frontier_events_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_census_premphf_band_producer_events_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_census_premphf_band_gate_events_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_census_premphf_band_service_events_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_census_idx2row_frontier_events_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_census_idx2row_producer_events_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_census_idx2row_gate_events_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_census_idx2row_service_events_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_census_rowindex_frontier_events_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_census_rowindex_producer_events_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_census_rowindex_gate_events_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_census_rowindex_service_events_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_census_rowdescriptor_frontier_events_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_census_rowdescriptor_producer_events_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_census_rowdescriptor_gate_events_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_census_rowdescriptor_service_events_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_rowindex_materialize_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_rowindex_publicize_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_rowindex_owner_form_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_rowindex_join_live_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_rowindex_join_ready_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_rowindex_ready_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_rowindex_release_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_rowindex_release_missing_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_rowindex_fallback_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_idx2row_materialize_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_idx2row_publicize_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_idx2row_owner_form_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_idx2row_join_live_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_idx2row_join_ready_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_idx2row_ready_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_idx2row_release_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_idx2row_release_missing_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_idx2row_fallback_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_premphf_base_materialize_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_premphf_base_publicize_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_premphf_base_owner_form_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_premphf_base_shared_hit_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_premphf_base_lookup_ready_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_premphf_base_proxy_only_gap_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_premphf_band_materialize_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_premphf_band_publicize_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_premphf_band_owner_form_candidate_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_premphf_band_join_ready_candidate_total_ = nullptr;
    Statistic<uint64_t>* stat_atlas_proxy_premphf_band_zero_service_total_ = nullptr;
    Statistic<uint64_t>* stat_gcss_lookup_hit_total_ = nullptr;
    Statistic<uint64_t>* stat_gcss_lookup_miss_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_read_dense_reqs_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_read_dense_bytes_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_read_rowptr_reqs_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_read_rowptr_bytes_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_read_colidx_reqs_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_read_colidx_bytes_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_read_blockdata_reqs_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_read_blockdata_bytes_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_read_gcss_reqs_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_read_gcss_bytes_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_idx_sram_reads_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_idx_sram_writes_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_idx_sram_bytes_read_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_idx_sram_bytes_write_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_idx_sram_bank_conflict_ticks_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_idx_sram_predicted_extra_cycles_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_idx_sram_resident_bytes_peak_ = nullptr;
    Statistic<uint64_t>* stat_weight_idx_sram_bank_peak_accesses_per_tick_ = nullptr;
    Statistic<uint64_t>* stat_weight_idx_sram_energy_read_pj_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_idx_sram_energy_write_pj_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_idx_lookup_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_idx_lookup_idx2_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_l0_sram_reads_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_l0_sram_writes_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_l0_sram_bytes_read_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_l0_sram_bytes_write_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_l0_sram_bank_conflict_ticks_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_l0_sram_predicted_extra_cycles_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_l0_sram_resident_bytes_peak_ = nullptr;
    Statistic<uint64_t>* stat_weight_l0_sram_bank_peak_accesses_per_tick_ = nullptr;
    Statistic<uint64_t>* stat_weight_l0_sram_energy_read_pj_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_l0_sram_energy_write_pj_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_sram_enforced_stall_cycles_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_l0_lookup_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_l0_hit_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_l0_fill_total_ = nullptr;
    Statistic<uint64_t>* stat_weight_l0_evict_total_ = nullptr;
    Statistic<uint64_t>* stat_core_state_sram_reads_total_ = nullptr;
    Statistic<uint64_t>* stat_core_state_sram_writes_total_ = nullptr;
    Statistic<uint64_t>* stat_core_state_sram_bytes_read_total_ = nullptr;
    Statistic<uint64_t>* stat_core_state_sram_bytes_write_total_ = nullptr;
    Statistic<uint64_t>* stat_core_state_sram_bank_conflict_ticks_total_ = nullptr;
    Statistic<uint64_t>* stat_core_state_sram_predicted_extra_cycles_total_ = nullptr;
    Statistic<uint64_t>* stat_core_state_sram_resident_bytes_peak_ = nullptr;
    Statistic<uint64_t>* stat_core_state_sram_bank_peak_accesses_per_tick_ = nullptr;
    Statistic<uint64_t>* stat_core_state_sram_energy_read_pj_total_ = nullptr;
    Statistic<uint64_t>* stat_core_state_sram_energy_write_pj_total_ = nullptr;
    Statistic<uint64_t>* stat_core_state_sram_stall_cycles_total_ = nullptr;
    Statistic<uint64_t>* stat_riscv_snn_workload_selected_ = nullptr;
    Statistic<uint64_t>* stat_riscv_snn_firmware_elf_present_ = nullptr;
    Statistic<uint64_t>* stat_riscv_snn_firmware_loaded_ = nullptr;
    Statistic<uint64_t>* stat_riscv_snn_backend_runtime_bridge_ = nullptr;
    Statistic<uint64_t>* stat_riscv_snn_firmware_started_count_ = nullptr;
    Statistic<uint64_t>* stat_riscv_snn_submitted_commands_ = nullptr;
    Statistic<uint64_t>* stat_riscv_snn_accepted_commands_ = nullptr;
    Statistic<uint64_t>* stat_riscv_snn_completion_visible_count_ = nullptr;
    Statistic<uint64_t>* stat_riscv_snn_completion_consumed_count_ = nullptr;
    Statistic<uint64_t>* stat_riscv_snn_fused_step_completion_count_ = nullptr;
    Statistic<uint64_t>* stat_riscv_snn_fault_count_ = nullptr;
    Statistic<uint64_t>* stat_riscv_snn_last_completion_status_ = nullptr;
    Statistic<uint64_t>* stat_riscv_snn_last_fault_csr_ = nullptr;
    Statistic<uint64_t>* stat_riscv_snn_backend_runtime_bridge_provider_bound_ = nullptr;
    
    // 内部计数器用于getStatistics()方法
    uint64_t count_spikes_received_;
    uint64_t count_spikes_generated_;
    uint64_t count_neurons_fired_;
    uint64_t count_memory_requests_;
    uint64_t count_non_spike_packets_received_ = 0;
    uint64_t count_stream_mem_verify_pass_ = 0;
    uint64_t count_stream_mem_verify_fail_ = 0;
    uint64_t count_stream_pkt_sent_ = 0;
    uint64_t count_stream_pkt_recv_ = 0;
    uint64_t count_stream_pkt_bad_crc_ = 0;
    uint64_t count_stream_pkt_bad_magic_ = 0;
    uint64_t count_route3d_native_activation_total_ = 0;
    uint64_t count_route3d_native_gating_activation_total_ = 0;
    uint64_t count_route3d_native_direct_activation_total_ = 0;
    uint64_t count_route3d_native_unique_sources_total_ = 0;
    // 内部计数：用于收尾摘要打印（不依赖SST统计聚合）
    uint64_t count_cache_hits_ = 0;
    uint64_t count_cache_misses_ = 0;
    uint64_t count_merged_reads_rows_ = 0;
    uint64_t count_merged_reads_cls_ = 0;
    uint64_t count_cache_evictions_ = 0;
    // 往返延迟测量（Cycle）
    uint64_t accum_mem_latency_cycles_ = 0;
    uint64_t count_mem_responses_ = 0;
    uint64_t count_cycles_update_neuron_ = 0;
    uint64_t count_synaptic_accesses_ = 0;

    // === Batch-A: Memory access detailed statistics (per-core) ===
    // Histogram candidates (type configured via Python):
    //  - mem_read_latency_cycles: 端到端读延迟
    //  - mem_read_latency_cycles_weights/state: 区域分组
    //  - mem_req_size_bytes: 请求字节大小
    //  - mem_outstanding_at_issue: 发起时并发请求数
    Statistic<uint64_t>* stat_mem_read_latency_cycles_ = nullptr;
    Statistic<uint64_t>* stat_mem_read_latency_cycles_weights_ = nullptr;
    Statistic<uint64_t>* stat_mem_read_latency_cycles_state_ = nullptr;
    Statistic<uint64_t>* stat_mem_req_size_bytes_ = nullptr;
    Statistic<uint64_t>* stat_mem_outstanding_at_issue_ = nullptr;

    // === Phase6: Stream workload statistics (per-core) ===
    Statistic<uint64_t>* stat_stream_mem_writes_issued_total_ = nullptr;
    Statistic<uint64_t>* stat_stream_mem_reads_issued_total_ = nullptr;
    Statistic<uint64_t>* stat_stream_mem_bytes_written_total_ = nullptr;
    Statistic<uint64_t>* stat_stream_mem_bytes_read_total_ = nullptr;
    Statistic<uint64_t>* stat_stream_mem_verify_pass_total_ = nullptr;
    Statistic<uint64_t>* stat_stream_mem_verify_fail_total_ = nullptr;
    Statistic<uint64_t>* stat_stream_pkt_sent_total_ = nullptr;
    Statistic<uint64_t>* stat_stream_pkt_recv_total_ = nullptr;
    Statistic<uint64_t>* stat_stream_pkt_bad_crc_total_ = nullptr;
    Statistic<uint64_t>* stat_stream_pkt_bad_magic_total_ = nullptr;

    // Dense 权重区域上界（用于区域分组）；BCSR 通过 bcsr_kind 判别
    uint64_t weight_region_end_ = 0; // [base_addr_, weight_region_end_) 视为权重区（dense）
    // Dense 权重“物理布局”（实验性；默认 row_major）
    std::string dense_layout_mode_ = "row_major"; // row_major|phys_v1
    uint32_t dense_phys_dram_row_bytes_ = 0;
    bool dense_phys_enable_ = false;
    uint32_t dense_phys_row_stride_bytes_ = 0;
    uint32_t dense_phys_rows_per_dram_row_ = 1;
    uint32_t dense_phys_group_stride_bytes_ = 0;

    // BCSR 布局描述（集中校验与寻址）
    struct BcsrLayout {
        uint32_t rows = 0;
        uint32_t cols = 0;
        uint32_t block_rows = 0;
        uint32_t block_cols = 0;
        uint32_t idx_bytes = 0;
        uint32_t val_bytes = 0;
        uint64_t rowptr_offset = 0;
        uint64_t colidx_offset = 0;
        uint64_t blockdata_offset = 0;
        uint64_t blockids_offset = 0;
        std::string layout_mode = "flat"; // flat|rowpack_v1
        uint32_t colidx_row_stride_bytes = 0;
        uint32_t blockdata_row_stride_bytes = 0;
        uint32_t blockids_row_stride_bytes = 0;
        uint64_t per_core_stride = 0;
        bool validate(uint64_t base, Output* out, bool debug, uint32_t core_id, uint32_t node_id) const;
        uint64_t maxOffset() const {
            return std::max(std::max(rowptr_offset, colidx_offset),
                            std::max(blockdata_offset, blockids_offset));
        }
    } bcsr_layout_;

    // ===== BCSR 读路径支持 =====
    bool use_bcsr_ = false;
    uint32_t bcsr_br_ = 16;                 // block rows
    uint32_t bcsr_bc_ = 16;                 // block cols
    uint32_t bcsr_val_bytes_ = 4;           // FP32
    uint32_t bcsr_idx_bytes_ = 2;           // uint16
    uint64_t bcsr_colidx_addr_ = 0;         // colidx 基地址
    uint64_t bcsr_blockdata_addr_ = 0;      // blockdata 基地址
    uint64_t bcsr_blockids_addr_ = 0;       // blockids 基地址（可选）
    // 读值守护（诊断/健壮性）：过滤非有限或异常大的权重，避免毒化ΔV（默认开启）
    bool bcsr_weight_guard_enable_ = true;
    float bcsr_weight_abs_max_ = 10.0f;
    uint64_t bcsr_bad_weight_count_ = 0;
    std::unique_ptr<BcsrWeightManager> bcsr_weights_;

    uint32_t bcsr_row_index_cache_cap_ = 64; // 行索引段缓存容量（行数）
    uint32_t bcsr_block_cache_cap_ = 256;    // 数据块缓存容量（块数）
    // 行索引缓存：block_row -> colidx 段
    std::unordered_map<uint32_t, std::vector<uint32_t>> bcsr_row_index_cache_;
    std::list<uint32_t> bcsr_row_index_lru_;
    // 数据块缓存：key=(block_row<<32)|block_col -> 块数据
    struct BcsrBlockEntry { std::vector<float> data; std::list<uint64_t>::iterator it; };
    std::unordered_map<uint64_t, BcsrBlockEntry> bcsr_block_cache_;
    std::list<uint64_t> bcsr_block_lru_;

    // BCSR 统计计数（收尾打印）
    uint64_t bcsr_count_row_reads_ = 0;
    uint64_t bcsr_count_colidx_reads_ = 0;
    uint64_t bcsr_count_block_reads_ = 0;
    uint64_t bcsr_count_block_hits_ = 0;
    uint64_t bcsr_count_block_misses_ = 0;
    uint64_t bcsr_count_row_index_hits_ = 0;
    uint64_t bcsr_count_row_index_fills_ = 0;
    uint64_t bcsr_bytes_idx_ = 0;
    uint64_t bcsr_bytes_val_ = 0;
    bool bcsr_prefetch_all_ = true;
    bool bcsr_prefetch_issued_ = false;

	    // BCSR 辅助
	    void requestWeightBCSR(uint32_t pre_global, uint32_t post_local, std::function<void(float)> cb);
    bool bcsrRowIndexGet_(uint32_t block_row, std::vector<uint32_t>& out);
    void bcsrRowIndexPut_(uint32_t block_row, std::vector<uint32_t>& data);
    bool bcsrBlockGet_(uint32_t block_row, uint32_t block_col, std::vector<float>& out);
    void bcsrBlockPut_(uint32_t block_row, uint32_t block_col, std::vector<float>& data);
    void bcsrPopulateWeightCache_(uint32_t block_row, uint32_t block_col, const std::vector<float>& blk);
    bool loadBcsrRowptrFromFile_();
    void ensureRowptrReadyOrFatal_(const char* reason);
    size_t expectedRowptrEntries_() const;
    size_t expectedRowptrBytes_() const;
    bool installRowptrFromBytes_(const uint8_t* data, size_t bytes, const char* source, bool count_stats);
    bool bcsr_force_file_read_ = false; // 诊断：强制从文件读取BCSR块（绕过内存）
    // 从权重文件读取单个 (post_local, pre_global) 的权重（仅诊断/验证用）
    float readBcsrWeightFromFile_(uint32_t post_local, uint32_t pre_global) const;

    // CSR 已移除

    // weights_template_ 保留：用于 BCSR 文件兜底与诊断读取
    std::string weights_template_;
    std::string gcss_index_template_;
    std::string synapse_weight_mode_ = "bcsr_gas";
    bool record_edge_apply_enable_ = false;
    bool record_edge_idle_enable_ = true;
    bool record_edge_scatter_enable_ = false;
    bool parseBcsrMeta(const std::string& meta_path, uint32_t& rows_out, uint32_t& cols_out,
                       uint32_t& br_out, uint32_t& bc_out,
                       uint32_t& idx_bytes_out, uint32_t& val_bytes_out,
                       uint64_t& rowptr_off_out, uint64_t& colidx_off_out,
                       uint64_t& blockdata_off_out, uint64_t& blockids_off_out,
                       uint32_t& total_blocks_out) const;
    std::string resolveWeightTemplate(uint32_t pe, int core) const;
    // Stage 事件 CSV 写出互斥，避免多核心重复写表头
    static std::mutex s_stage_csv_mutex_;
    void appendStageEventRow_(const char* event_name, uint64_t now_ns, uint64_t spikes_emitted);
    void handleStageEventWithoutApply_(const GasOpData* op);
    void prepareEdgeWindowForApply_();
    void diagEdgeWeight_(const char* tag, uint32_t post_local, uint32_t pre_global,
                         float weight, uint32_t count);
    void issueEdgeWeightFetches_();
    void issueFromEdges_();
    void issueFromSets_(const std::vector<uint32_t>* posts_to_use,
                        const std::unordered_set<uint32_t>* pres_to_use);
    void issueFromSetsBcsr_(const std::vector<uint32_t>* posts_to_use,
                            const std::unordered_set<uint32_t>* pres_to_use);
    void issueFallbackReadsIfNeeded_(bool strict_gas_active);
    bool canIssueMoreReads_() const;
    void logBcsrWindowStats_(const char* tag);
    void resetBcsrWindowCounters_();

public:
    // IGasStageSink (StdMemEndpoint -> CoreShell): stage/stat events are forwarded to workload=snn.
    void onGasStageEvent(const GasStageEvent& ev) override;
    void onGasStatEvent(const GasStatEvent& st) override;

    // 应用门控决策（由父级MultiCorePE调用）
    void applyGatingDecision(uint32_t src_global, const std::vector<uint32_t>& dest_pes,
                             uint64_t current_cycle, uint64_t ttl_cycles) override;
};

} // namespace SnnDL
} // namespace SST

#endif // _H_SST_SNN_PE_SUBCOMPONENT
