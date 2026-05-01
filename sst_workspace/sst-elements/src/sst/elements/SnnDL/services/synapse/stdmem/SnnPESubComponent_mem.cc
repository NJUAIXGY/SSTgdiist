// -*- c++ -*-
//
// SnnPESubComponent_mem.cc: StandardMem glue + dense read/write helpers for SnnPESubComponent.
//

#include <sst/core/sst_config.h>
#include <sst/core/componentInfo.h>
#include <sst/core/interfaces/stdMem.h>
#include "SnnPESubComponent.h"
#include "SnnPESubComponent_impl.h"
#include "IPeAggregation.h"
#include "synapse/stdmem/StdMemEndpoint.h"
#include "synapse/weights/SnnBcsrWeightManager.h"
#include "synapse/weights/WeightMemorySubsystem.h"
#include "memory/StandardMemAccess.h"
#include "SnnDLLogging.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <inttypes.h>

using namespace SST;
using namespace SST::SnnDL;

template <>
void SnnPESubComponent::handleMemoryResponse<SST::Interfaces::StandardMem::Request>(
    SST::Interfaces::StandardMem::Request* req);

uint64_t SnnPESubComponent::denseWeightAddr_(uint32_t row, uint32_t col, uint32_t width) const {
    const uint64_t bpf = sizeof(float);
    if (!dense_phys_enable_ || dense_phys_group_stride_bytes_ == 0 || dense_phys_row_stride_bytes_ == 0 ||
        dense_phys_rows_per_dram_row_ == 0) {
        return base_addr_ +
               (static_cast<uint64_t>(row) * static_cast<uint64_t>(width) + static_cast<uint64_t>(col)) * bpf;
    }
    const uint64_t group = static_cast<uint64_t>(row) / static_cast<uint64_t>(dense_phys_rows_per_dram_row_);
    const uint64_t within = static_cast<uint64_t>(row) % static_cast<uint64_t>(dense_phys_rows_per_dram_row_);
    const uint64_t off =
        group * static_cast<uint64_t>(dense_phys_group_stride_bytes_) +
        within * static_cast<uint64_t>(dense_phys_row_stride_bytes_) +
        static_cast<uint64_t>(col) * bpf;
    return base_addr_ + off;
}

void SnnPESubComponent::initStdMemPhase0_() {
    // 加载 StandardMem 接口（Python 可通过槽位提供）。
    // 注意：该逻辑放在 synapse/stdmem 域，避免 control/*.cc 出现 StandardMem::。
    auto* stdmem = loadUserSubComponent<SST::Interfaces::StandardMem>(
        "memory", ComponentInfo::SHARE_NONE,
        registerTimeBase("1ns"),
        new SST::Interfaces::StandardMem::Handler2<SnnPESubComponent,
                                                   &SnnPESubComponent::handleMemoryResponse<SST::Interfaces::StandardMem::Request>>(this));

    // bind endpoint for control-plane sends (Begin/EndGather etc.)
    // Phase6：stream/traffic_mem workload 需要“纯内存语义”，强制设置 non-cacheable（同时保留 env fallback 兼容路径）。
    {
        StdMemEndpoint::Config cfg{};
        cfg.force_noncacheable = isStreamLikeWorkload_();
        stdmem_ep_->configure(cfg);
    }
    StdMemEndpoint::Runtime rt{};
    rt.log = output_;
    rt.node_id = static_cast<uint32_t>(node_id_);
    rt.core_id = static_cast<uint32_t>(core_id_);
    // Phase4-Task6.4: GAS stage/stat events are dispatched via StdMemEndpoint to CoreShell (IGasStageSink).
    rt.gas_stage_sink = this;
    rt.now_cycle = [this]() { return static_cast<uint64_t>(total_cycles_); };
    rt.before_data_plane_dispatch = [this](uint64_t now_cycle) {
        if (weight_mem_subsystem_) weight_mem_subsystem_->setNowCycle(now_cycle);
    };
    stdmem_ep_->bindRuntime(rt);
    stdmem_ep_->bindStdMem(stdmem);

    if (stdmem_ep_ && stdmem_ep_->available()) {
        // 若已成功加载 StandardMem 子组件，则认为内存就绪（即使未显式提供 memory_link_）
        memory_ready_ = true;
    } else {
        memory_ready_ = false;
    }
}

// === Learning writeback (called by compute core) ===
bool SnnPESubComponent::applyLocalWeightUpdates_(const std::unordered_map<uint64_t, float>& grads,
                                                float learning_rate,
                                                float weight_decay) {
    if (grads.empty()) return true;
    if (!ensureMemoryReady_()) return false;
    auto* mem = stdmem_ep_ ? stdmem_ep_->memoryAccess() : nullptr;
    if (!mem) return false;
    const uint32_t width = use_post_row_pre_col_ ? weights_cols_ : num_neurons_;
    const size_t bytes_per_float = sizeof(float);
    uint64_t total_writes = 0;
    size_t skipped_uncached = 0;
    for (const auto& kv : grads) {
        uint64_t key = kv.first;
        float grad = kv.second;
        float old_w = 0.0f;
        if (!weightCacheTryGet_(key, old_w)) {
            skipped_uncached++;
            continue;
        }
        float new_w = old_w - learning_rate * grad;
        if (weight_decay != 0.0f) {
            new_w -= weight_decay * old_w;
        }
	        const uint32_t row = (width != 0) ? static_cast<uint32_t>(key / static_cast<uint64_t>(width)) : 0u;
	        const uint32_t col = (width != 0) ? static_cast<uint32_t>(key % static_cast<uint64_t>(width)) : 0u;
	        uint64_t addr = denseWeightAddr_(row, col, width);
	        std::vector<uint8_t> data(bytes_per_float);
	        std::memcpy(data.data(), &new_w, bytes_per_float);
	        if (impl_) impl_->reportMemoryIssue(data.size(), false);
	        mem->write(addr, data, nullptr);
	        total_writes++;
	        weightCacheStore_(key, new_w);
    }
    if (output_) {
        output_->verbose(CALL_INFO, 1, 0,
            "📝 学习: 写回完成 writes=%" PRIu64 ", 跳过(未缓存)=%zu\n",
            total_writes, skipped_uncached);
    }
    return true;
}

void SnnPESubComponent::requestWeight(uint32_t pre_neuron, uint32_t post_neuron,
                                     std::function<void(float)> callback) {
    if (use_bcsr_ && use_post_row_pre_col_) {
        requestWeightBCSR(pre_neuron, post_neuron, std::move(callback));
        return;
    }
    auto* mem = stdmem_ep_ ? stdmem_ep_->memoryAccess() : nullptr;
    if (!ensureMemoryReady_() || !mem) {
        if (callback) callback(init_default_weight_);
        return;
    }

    const uint32_t width = use_post_row_pre_col_ ? weights_cols_ : num_neurons_;
    const uint32_t row = use_post_row_pre_col_ ? post_neuron : pre_neuron;
    const uint32_t col = use_post_row_pre_col_ ? pre_neuron : post_neuron;
    if (width == 0 || row >= num_neurons_ || col >= width) {
        if (callback) callback(0.0f);
        return;
    }

    const uint64_t req_addr = denseWeightAddr_(row, col, width);
    const uint64_t issue_cycle = static_cast<uint64_t>(total_cycles_);

    if (window_read_debug_ && output_) {
        output_->verbose(CALL_INFO, 2, 0,
            "[diag-read] core=%d requestWeight dense row=%u col=%u addr=0x%llx size=%zu\n",
            core_id_, row, col, (unsigned long long)req_addr, sizeof(float));
    }

	    if (impl_) impl_->reportMemoryIssue(sizeof(float), /*count_weight_read*/true);
	    mem->read(req_addr, sizeof(float),
	        [this, cb = std::move(callback), issue_cycle](IMemoryAccess::RequestId, uint64_t, std::vector<uint8_t>&& data) mutable {
            float w = 0.0f;
            if (data.size() >= sizeof(float)) {
                std::memcpy(&w, data.data(), sizeof(float));
            }
            if (readresp_zero_fallback_ && w == 0.0f) w = init_default_weight_;
            if (cb) cb(w);

            const uint64_t now = static_cast<uint64_t>(total_cycles_);
            if (now >= issue_cycle) {
                const uint64_t lat = now - issue_cycle;
                accum_mem_latency_cycles_ += lat;
                count_mem_responses_++;
                if (auto* pe = parent_pe_cached_) {
                    pe->accumulateMemReadLatency(lat, /*is_weight*/true);
                }
            }
        });
}

template <>
void SnnPESubComponent::handleMemoryResponse<SST::Interfaces::StandardMem::Request>(SST::Interfaces::StandardMem::Request* req) {
#ifdef SNNDL_ENABLE_PROFILING
    if (profiler_enabled_) { SNNDL_PROFILE_FUNCTION(profiler_); }
#endif
    // Phase4-Task6.4: StdMemEndpoint 统一分发：
    // - GAS 控制面（CustomResp）→ IGasStageSink（CoreShell），再转发到 workload=snn
    // - 数据面（ReadResp/WriteResp）→ StandardMemAccess（纯内存语义）
    if (stdmem_ep_ && stdmem_ep_->available()) {
        stdmem_ep_->handleResponseOpaque(req);
        return;
    }
    delete req;
    return;

}

void SnnPESubComponent::scheme1PrefetchSlice_(uint32_t slice_idx) {
    if (!ensureMemoryReady_()) return;
    if (weights_cols_ == 0) return;
    if (!weight_mem_subsystem_) return;
    // 计算该 slice 的列区间 [beg, end)
    uint32_t width = weights_cols_;
    uint32_t seg = std::max<uint32_t>(1, (width + scheme1_slices_ - 1) / scheme1_slices_);
    uint32_t beg = std::min<uint32_t>(slice_idx * seg, width);
    uint32_t end = std::min<uint32_t>(beg + seg, width);
    if (beg >= end) return;
    const uint32_t fpl = std::max<uint32_t>(1, line_size_bytes_ / (uint32_t)sizeof(float));
    s1_is_issuing_prefetch_ = true;
    weight_mem_subsystem_->setNowCycle(static_cast<uint64_t>(total_cycles_));
    for (uint32_t row = 0; row < num_neurons_; ++row) {
        // 按 cacheline 对齐扫描该区间
        for (uint32_t c = (beg / fpl) * fpl; c < end; c += fpl) {
            uint64_t req_addr = denseWeightAddr_(row, c, width);
            size_t req_size = std::min<uint32_t>(fpl, end - c) * (uint32_t)sizeof(float);
            if (stat_s1_bytes_read_) stat_s1_bytes_read_->addData(static_cast<uint64_t>(req_size));
            const uint32_t count_floats = static_cast<uint32_t>(req_size / sizeof(float));
            const bool issued = weight_mem_subsystem_->issueDensePrefetchRaw(
                req_addr, req_size, row, c, count_floats, /*scheme1_prefetch*/true);
            if (issued) scheme1_pending_prefetch_++;
        }
    }
    s1_is_issuing_prefetch_ = false;
}
