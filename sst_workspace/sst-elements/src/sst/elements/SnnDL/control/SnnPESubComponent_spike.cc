// -*- c++ -*-
//
// Copyright 2025 SST Contributors
//
// SnnPESubComponent_spike.cc: spike input processing extracted from SnnPESubComponent.cc
//

#include <sst/core/sst_config.h>

#include "SnnPESubComponent.h"
#include "SnnPESubComponent_impl.h"
#include "ISpikeWorkload.h"
#include "events/SpikeEvent.h"
#include "synapse/weights/WeightAccessor.h"
#include "synapse/weights/WeightMemorySubsystem.h"
#include "SnnDLLogging.h"

#include <inttypes.h> // PRIu64

using namespace SST;
using namespace SST::SnnDL;

void SnnPESubComponent::deliverSpike(SpikeEvent* spike) {
    if (!spike) return;
    // Phase6：stream workload 不处理 Spike 语义（保持边界清晰：stream=纯通信+纯内存验证）。
    if (isStreamWorkload_()) {
        delete spike;
        return;
    }
    if (!spike_workload_) {
        if (output_) {
            output_->fatal(CALL_INFO, -1,
                "core=%d deliverSpike requires workload implementing ISpikeWorkload (workload_impl=snn)\n",
                core_id_);
        }
        delete spike;
        return;
    }
    // 统计/聚合仍锚定在 CoreShell：activity f 需要在 BeginGather/BeginApply 阶段做 PE 级汇聚。
    // window_read_enable=1 时按“到达本核的 spike”记录 active_pre（与 legacy deliverSpike 行为一致）。
    if (window_read_enable_) {
        uint32_t dest = spike->getDestinationNeuron();
        uint32_t post_local = dest;
        bool post_local_valid = true;
        if (dest >= num_neurons_) {
            if (dest >= global_neuron_base_ && dest < global_neuron_base_ + num_neurons_) {
                post_local = static_cast<uint32_t>(dest - global_neuron_base_);
            } else {
                post_local_valid = false;
            }
        }
        if (post_local_valid && post_local < num_neurons_) {
            recordActivePre_(spike->getSourceNeuron());
        }
    }
    spike_workload_->deliverSpike(spike);
}

void SnnPESubComponent::legacySnnDeliverSpike(SpikeEvent* spike) {
    if (!spike) return;
    // Phase7: strict window-read spike input has moved into workload=snn.
    // If this triggers, it indicates an unintended fallback to legacy control-plane queueing.
    if (workload_spike_input_enable_ &&
        apply_acc_enable_ && gas_window_mode_ && window_read_enable_ && !scheme1_enable_) {
        if (output_) {
            output_->fatal(
                CALL_INFO, -1,
                "core=%d legacySnnDeliverSpike called under strict window-read (apply_acc_enable=1, gas_window_mode=1, window_read_enable=1). "
                "Spike input should be handled by workload=snn.\n",
                core_id_);
        }
        delete spike;
        return;
    }
    onSpikeDeliveredCore_(spike);

    spike->clearLocalCache();
    // 统一以“到达本核的仿真时间”作为处理时间戳，避免跨 PE/网络延迟导致的同周期竞态。
    spike->setTimestamp(getCurrentSimTimeNano());
    output_->verbose(CALL_INFO, 4, 0, "📨 核心%d接收脉冲: 源全局ID=%u, 目标全局ID=%u, 目标神经元=%u, 权重%.3f\n",
                    core_id_, spike->getSourceNeuron(), spike->getDestinationNeuron(), spike->getDestinationNeuron(), spike->getWeight());

    // 将脉冲加入队列，在时钟周期中处理
    incoming_spikes_.push(spike);

    if (window_read_enable_) {
        uint32_t dest = spike->getDestinationNeuron();
        uint32_t post_local = dest;
        bool post_local_valid = true;
        if (dest >= num_neurons_) {
            if (dest >= global_neuron_base_ && dest < global_neuron_base_ + num_neurons_) {
                post_local = static_cast<uint32_t>(dest - global_neuron_base_);
            } else {
                post_local = UINT32_MAX;
                post_local_valid = false;
            }
        }
        if (post_local_valid) {
            spike->setCachedPostLocal(post_local);
        }
        if (!use_post_row_pre_col_) {
            spike->setCachedPreLocal(mapPreGlobalToLocal_(spike->getSourceNeuron()));
        }
        // [Critical Fix] 立即维护窗口容器，不等待 clockTick 延迟的 processLocalSpike()
        // 备份版本 (Dec 11) 在 deliverSpike 时直接填充 posts_list_window_/active_pre_window_，
        // 确保 BeginApply 到达时容器非空，issueFromEdges() 能正常发起权重读取。
        // 当前版本将此逻辑移到了 processLocalSpike()，但由于 clockTick 的时间戳延迟检查
        // (spike->getTimestamp() >= now_ns)，同周期到达的 spike 会被延迟处理，
        // 导致 BeginApply 时容器为空，神经元无法发放。
        bool stage_ok_for_window_touch = false;
        switch (gas_stage_) {
            case GasStage::Gather:
                stage_ok_for_window_touch = true;
                break;
            case GasStage::Apply:
                stage_ok_for_window_touch = record_edge_apply_enable_;
                break;
            case GasStage::Idle:
                stage_ok_for_window_touch = record_edge_idle_enable_;
                break;
            case GasStage::Scatter:
                stage_ok_for_window_touch = record_edge_scatter_enable_;
                break;
            default:
                stage_ok_for_window_touch = false;
                break;
        }
        if (weight_mem_subsystem_ &&
            post_local_valid &&
            post_local < num_neurons_ &&
            stage_ok_for_window_touch) {
            weight_mem_subsystem_->noteWindowTouch(post_local, spike->getSourceNeuron(), num_neurons_);
            recordActivePre_(spike->getSourceNeuron());
        } else if (window_read_debug_ || debug_window_log_count_ < 8) {
            // 诊断：记录条件不满足的原因
            output_->verbose(CALL_INFO, 1, 0,
                "[DeliverDiag] core=%d skip noteWindowTouch: wms=%s post_valid=%d post_l=%u num=%u stage=%d\n",
                core_id_,
                weight_mem_subsystem_ ? "set" : "null",
                post_local_valid ? 1 : 0,
                post_local, num_neurons_,
                static_cast<int>(gas_stage_));
        }
        static const uint32_t kLogLimit = 8;
        if (debug_window_log_count_ < kLogLimit) {
            output_->verbose(CALL_INFO, 1, 0,
                "[DeliverDebug] core=%d dest=%u base=%" PRIu64 " num=%u -> post_local=%u queue=%zu\n",
                core_id_, dest, (uint64_t)global_neuron_base_, num_neurons_, post_local, incoming_spikes_.size());
            debug_window_log_count_++;
        }
    }

    // 更新两种统计：SST统计对象和内部计数器
    stat_spikes_received_->addData(1);
    count_spikes_received_++;
}

void SnnPESubComponent::processLocalSpike(SpikeEvent* spike_event) {
#ifdef SNNDL_ENABLE_PROFILING
    if (profiler_enabled_) { SNNDL_PROFILE_FUNCTION(profiler_); }
#endif
    // 复用SnnPE的本地脉冲处理逻辑
    if (!spike_event) return;

    uint32_t dest = spike_event->getDestinationNeuron();
    switch (gas_stage_) {
        case GasStage::Gather: diag_spikes_stage_gather_++; break;
        case GasStage::Apply:  diag_spikes_stage_apply_++;  break;
        case GasStage::Scatter:diag_spikes_stage_scatter_++;break;
        default: diag_spikes_stage_idle_++; break;
    }
    uint32_t target_neuron = dest;
    bool used_cached_post = false;
    if (spike_event->hasCachedPostLocal()) {
        target_neuron = spike_event->getCachedPostLocal();
        used_cached_post = true;
    }
    // 全局ID → 本地ID 映射
    if (!used_cached_post && dest >= num_neurons_) {
        if (dest >= global_neuron_base_ && dest < global_neuron_base_ + num_neurons_) {
            target_neuron = static_cast<uint32_t>(dest - global_neuron_base_);
        } else {
            output_->verbose(CALL_INFO, 2, 0, "⚠️ 核心%d收到无法映射的目标神经元%d的脉冲\n", core_id_, dest);
            return;
        }
    }

#ifdef SNNDL_ENABLE_DEBUG_LOG
    if (window_read_debug_) {
        if (output_ && output_->getVerboseLevel() >= 2) {
            output_->verbose(CALL_INFO, 2, 0,
            "[diag-spike] core=%d stage=%d pre_g=%u post_g=%u dest_l=%u queue=%zu\n",
            core_id_, (int)gas_stage_, spike_event->getSourceNeuron(), spike_event->getDestinationNeuron(),
            target_neuron, incoming_spikes_.size());
        }
    }
#endif

    // 窗口累加语义 (apply_acc_enable_) 下，控制层可能会“先记录边/发起权重读，后在 Scatter 统一应用ΔV”，
    // 因此无法立刻调用 onSynapticEvent() 来复用核心侧门控。
    // 这里在任何控制面动作之前先询问 compute core 是否接受该输入（例如不应期过滤），以保持口径一致。
    if (apply_acc_enable_ && compute_core_) {
        if (!compute_core_->shouldAcceptSynapticInput(
                target_neuron, static_cast<uint64_t>(total_cycles_))) {
            output_->verbose(CALL_INFO, 4, 0,
                "⚠️ 核心%d输入被 compute core 门控丢弃: post_l=%u\n",
                core_id_, target_neuron);
            return;
        }
    }

    // 使用权重缓存/按需读取
    float weight = 0.0f;
    bool have_mem_weight = false;
    const bool logDetail = log_weight_details_ || enable_detailed_map_log_;
    // Byte-exact/GAS correctness: edge recording is a gather-side concern; do not gate it on memory readiness.
    {
        const uint32_t pre_global = spike_event->getSourceNeuron();
        const uint32_t post_global = spike_event->getDestinationNeuron();
        uint32_t post_local = target_neuron;
        if (spike_event->hasCachedPostLocal()) {
            post_local = spike_event->getCachedPostLocal();
        } else if (post_global >= global_neuron_base_ && post_global < global_neuron_base_ + num_neurons_) {
            post_local = static_cast<uint32_t>(post_global - global_neuron_base_);
        }
        recordEdge_(post_local, pre_global);
    }

    if (enable_weight_fetch_ && ensureMemoryReady_()) {
        uint32_t pre_global = spike_event->getSourceNeuron();
        uint32_t post_global = spike_event->getDestinationNeuron();
        uint32_t post_local = target_neuron;
        if (spike_event->hasCachedPostLocal()) {
            post_local = spike_event->getCachedPostLocal();
        } else if (post_global >= global_neuron_base_ && post_global < global_neuron_base_ + num_neurons_) {
            post_local = static_cast<uint32_t>(post_global - global_neuron_base_);
        }
        uint32_t req_pre_param = 0;
        uint32_t req_post_param = 0;
        uint64_t cache_key = 0;
        const bool allow_remap = !use_post_row_pre_col_;
        if (weight_accessor_ && weight_accessor_->resolve(pre_global, post_local, req_pre_param, req_post_param, cache_key, allow_remap)) {
            if (use_post_row_pre_col_) {
                recordActivePre_(pre_global);
            }
            float cached = 0.0f;
	            if (weightCacheTryGet_(cache_key, cached)) {
	                weight = cached;
	                if (readresp_zero_fallback_ && weight == 0.0f) weight = init_default_weight_;
	                have_mem_weight = true;
	                if (impl_) impl_->reportCacheAccess(true);
	                if (logDetail && !first_cache_hit_logged_) {
                    if (use_post_row_pre_col_) {
                        SNNDL_LOG(2, "🟢 首次命中(全网): row(post_l)=%u, col(pre_g)=%u, key=%" PRIu64 ", weight=%.3f\n",
                            post_local, pre_global, cache_key, weight);
                    } else {
                        uint32_t pre_local_dbg = spike_event->hasCachedPreLocal()
                            ? spike_event->getCachedPreLocal()
                            : mapPreGlobalToLocal_(pre_global);
                        SNNDL_LOG(2, "🟢 首次命中: pre_l=%u, post_l=%u, key=%" PRIu64 ", weight=%.3f\n",
                            pre_local_dbg, post_local, cache_key, weight);
                    }
                    first_cache_hit_logged_ = true;
                }
	            } else if (!window_read_enable_ && pendingMemSize_() < static_cast<size_t>(max_outstanding_requests_)) {
	                if (impl_) impl_->reportCacheAccess(false);
	                requestWeight(req_pre_param, req_post_param, [this, cache_key](float w){
	                    weightCacheStore_(cache_key, w);
	                });
                if (logDetail && !first_cache_miss_logged_) {
                    if (use_post_row_pre_col_) {
                        SNNDL_LOG(2, "🟡 首次未命中并发起读(全网): row(post_l)=%u, col(pre_g)=%u, key=%" PRIu64 "\n",
                            post_local, pre_global, cache_key);
                    } else {
                        uint32_t pre_local_dbg = spike_event->hasCachedPreLocal()
                            ? spike_event->getCachedPreLocal()
                            : mapPreGlobalToLocal_(pre_global);
                        SNNDL_LOG(2, "🟡 首次未命中并发起读: pre_l=%u, post_l=%u, key=%" PRIu64 "\n",
                            pre_local_dbg, post_local, cache_key);
                    }
                    first_cache_miss_logged_ = true;
                }
	            } else if (window_read_enable_) {
	                if (impl_) impl_->reportCacheAccess(false);
	            }
	        } else {
#if SNNDL_DEBUG_ENABLED
            if (window_read_debug_) {
                SNNDL_DEBUG_LOG(0, "[diag-edge-resolve] core=%d skipped pre=%u post=%u (resolve失败)\n",
                    core_id_, pre_global, post_local);
            }
#endif
        }
    } else {
#ifdef SNNDL_ENABLE_DEBUG_LOG
        if (window_read_debug_) {
            if (output_ && output_->getVerboseLevel() >= 2) {
                output_->verbose(CALL_INFO, 2, 0,
                "[diag-edge-gate] core=%d skip recordEdge: ewf=%d stdmem_ep=%d ready=%d stage=%d\n",
                core_id_, enable_weight_fetch_ ? 1 : 0,
                (stdmem_ep_ && stdmem_ep_->available()) ? 1 : 0,
                memory_ready_ ? 1 : 0,
                (int)gas_stage_);
            }
        }
#endif
    }
    // 记录本窗触达的post（仅用于窗口读发起；不改变语义）
    if (window_read_enable_) {
        bool stage_ok_for_window_touch = false;
        switch (gas_stage_) {
            case GasStage::Gather:
                stage_ok_for_window_touch = true;
                break;
            case GasStage::Apply:
                stage_ok_for_window_touch = record_edge_apply_enable_;
                break;
            case GasStage::Idle:
                stage_ok_for_window_touch = record_edge_idle_enable_;
                break;
            case GasStage::Scatter:
                stage_ok_for_window_touch = record_edge_scatter_enable_;
                break;
            default:
                stage_ok_for_window_touch = false;
                break;
        }
        if (weight_mem_subsystem_ &&
            target_neuron < num_neurons_ &&
            stage_ok_for_window_touch) {
            weight_mem_subsystem_->noteWindowTouch(target_neuron, spike_event->getSourceNeuron(), num_neurons_);
            recordActivePre_(spike_event->getSourceNeuron());
        }
    }
    if (!have_mem_weight) {
        // 回退策略：可选择使用事件权重，或直接使用默认初始权重（与内存一致）
        if (use_event_weight_fallback_) {
            weight = spike_event->getWeight();
            if (!event_weight_fallback_warned_) {
                output_->verbose(CALL_INFO, 1, 0, "⚠️ 核心%d启用事件权重回退，事件权重=%.3f\n", core_id_, weight);
                event_weight_fallback_warned_ = true;
            }
        } else {
            weight = 0.0f;
        }
    }
    if (apply_acc_enable_) {
        // 严格窗口读（window_read_enable_=1）下，所有 ΔV 累加应由窗口 Apply 阶段统一发起与归集，
        // 避免“同一条边既在 spike 到达时 cache-hit 累加，又在窗口 issueFromEdges 时再次累加”的双计数。
        // 非窗口读模式下保留旧行为：cache-hit 时可直接累加。
        if (!window_read_enable_ && have_mem_weight && use_post_row_pre_col_) {
            uint32_t post_local = target_neuron;
            // Debug probe (Option 2/3): cache-hit accumulation path
            if (output_) {
                output_->verbose(CALL_INFO, 2, 0,
                    "[GAS][Delta][cache-hit] core=%u post=%u dv=%.6f (key-cached)\n",
                    core_id_, post_local, weight);
            }
            // 诊断：累计ΔV
            diag_dv_sum_window_ += (double)weight;
            if (weight != 0.0f) diag_dv_updates_nonzero_++;
            accUpdate_(post_local, weight);
        }
        recordSynapticAccess_();
        return;
    }
    if (compute_core_) {
        SynapticEvent ev;
        ev.post_local = target_neuron;
        ev.pre_global = spike_event->getSourceNeuron();
        ev.weight = weight;
        onSynapticEventCore_(ev);
    }
    recordSynapticAccess_();

    // 在线梯度累加已下沉到 compute core::onSynapticEvent()

    // 一次性详细日志：打印全局/本地映射与地址
    if (logDetail && (enable_detailed_map_log_ || !detailed_log_emitted_)) {
        uint32_t pre_global = spike_event->getSourceNeuron();
        uint32_t post_global = spike_event->getDestinationNeuron();
        uint32_t pre_local_dbg = spike_event->hasCachedPreLocal()
            ? spike_event->getCachedPreLocal()
            : mapPreGlobalToLocal_(pre_global);
        uint32_t post_local_dbg = target_neuron;
        uint64_t offset_dbg = 0;
        if (use_post_row_pre_col_) {
            offset_dbg = static_cast<uint64_t>(post_local_dbg) * static_cast<uint64_t>(weights_cols_) + static_cast<uint64_t>(pre_global);
        } else {
            offset_dbg = static_cast<uint64_t>(pre_local_dbg) * static_cast<uint64_t>(num_neurons_) + post_local_dbg;
        }
        uint64_t addr_dbg = base_addr_ + offset_dbg * sizeof(float);
        output_->verbose(CALL_INFO, 1, 0,
            "🧪 详细权重调试: 事件权重=%.3f, 内存权重=%s, 最终权重=%.3f, 回退=%s\n",
            spike_event->getWeight(), have_mem_weight ? "有" : "无", weight, use_event_weight_fallback_ ? "启用" : "禁用");
        output_->verbose(CALL_INFO, 1, 0,
            "🧪 一次性详细映射: pre_g=%u->pre_l=%u, post_g=%u->post_l=%u, base=%" PRIu64 ", off=%" PRIu64 ", addr=%" PRIu64 ", weight=%.3f\n",
            pre_global, pre_local_dbg, post_global, post_local_dbg, base_addr_, offset_dbg, addr_dbg, weight);
        detailed_log_emitted_ = true;
    }
    if (logDetail) {
        output_->verbose(CALL_INFO, 5, 0,
            "[syn] core=%d post_l=%u add=%.3f\n",
            core_id_, target_neuron, weight);
    }
}
