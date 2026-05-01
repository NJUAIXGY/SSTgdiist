// -*- c++ -*-
//
// WeightMemorySubsystem.cc:
// Phase E: 将 StandardMem pending/回调/解析/BCSR 缓存等数据路径收敛到内存子系统，
// 控制层仅保留 GAS/窗口编排与统计汇总。

#include <sst/core/sst_config.h>

#include "WeightMemorySubsystem.h"

#include "SnnBcsrWeightManager.h"
#include "SnnDLStringUtil.h"
#include "services/local_storage/PeInternalPodShadowGate.h"
#include "services/local_storage/PodOwnerServiceTable.h"
#include "services/pe_fabric/PeSharedCoreFabric.h"
#include "services/pe_fabric/PulseAgendaScorer.h"

#include <sst/core/output.h>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <limits>
#include <mutex>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

using namespace SST;
using namespace SST::SnnDL;

namespace {
// NOTE(Universal-core experiments):
// Keep BCSR cache/prefetch/populate optimizations disabled so GAS remains the only
// externally credited optimizer; keep in-flight coalescing available via runtime
// config for request dedup and stable window forward progress.
static constexpr bool kEnableBcsrOptimizations = false;
static constexpr bool kEnableBcsrInflightCoalescing = true;

static inline bool isPow2(uint32_t v) { return v != 0 && (v & (v - 1u)) == 0; }
static inline uint64_t alignDownU64(uint64_t v, uint64_t a) { return a ? (v & ~(a - 1u)) : v; }
static inline uint64_t alignUpU64(uint64_t v, uint64_t a) {
    if (!a) return v;
    const uint64_t m = a - 1u;
    return (v + m) & ~m;
}

static inline uint32_t pulseMetadataKindMaskBit_(
    PodMetadataObjectPlane::MetadataKind kind) {
    switch (kind) {
        case PodMetadataObjectPlane::MetadataKind::PreMphfBase:
            return PeLocalServiceObjectTable::kMetadataKindMaskPreMphfBase;
        case PodMetadataObjectPlane::MetadataKind::PreMphfBand:
            return PeLocalServiceObjectTable::kMetadataKindMaskPreMphfBand;
        case PodMetadataObjectPlane::MetadataKind::Idx2Row:
            return PeLocalServiceObjectTable::kMetadataKindMaskIdx2Row;
        case PodMetadataObjectPlane::MetadataKind::RowIndex:
            return PeLocalServiceObjectTable::kMetadataKindMaskRowIndex;
        case PodMetadataObjectPlane::MetadataKind::RowDescriptor:
            return PeLocalServiceObjectTable::kMetadataKindMaskRowDescriptor;
        default:
            return 0u;
    }
}

static inline void prepareAlignedRead(uint64_t addr, size_t size, uint32_t line_size,
                                      uint64_t& out_addr, size_t& out_size, size_t& out_slice_off) {
    out_addr = addr;
    out_size = size;
    out_slice_off = 0;
    if (size == 0) return;
    if (!isPow2(line_size)) return;
    const uint64_t ls = static_cast<uint64_t>(line_size);
    const uint64_t end = addr + static_cast<uint64_t>(size);
    const uint64_t a0 = alignDownU64(addr, ls);
    const uint64_t a1 = alignUpU64(end, ls);
    if (a1 <= a0) return;
    out_addr = a0;
    out_size = static_cast<size_t>(a1 - a0);
    out_slice_off = static_cast<size_t>(addr - a0);
}

static std::string resolveWeightsTemplatePath(const std::string& tmpl, uint32_t pe, uint32_t core) {
    if (tmpl.empty()) return "";
    return resolvePeCoreTemplate(tmpl, pe, core);
}

struct PulsePeSharedWindowKey {
    uint32_t scope_id = 0;
    uint32_t window_seq = 0;

    bool operator==(const PulsePeSharedWindowKey& other) const {
        return scope_id == other.scope_id &&
               window_seq == other.window_seq;
    }
};

struct PulsePeSharedWindowKeyHash {
    size_t operator()(const PulsePeSharedWindowKey& key) const {
        size_t seed = static_cast<size_t>(key.scope_id);
        seed ^= static_cast<size_t>(key.window_seq) + 0x9e3779b9u + (seed << 6) + (seed >> 2);
        return seed;
    }
};

struct PulseSharedGatherBandProbeEntry {
    uint64_t band_id = 0;
    uint32_t head_distance = 0;
    std::vector<uint64_t> selected_line_addrs;
};

struct PulsePeSharedWindowFinalizeEntry {
    uint64_t arrived_core_bitmap = 0;
    uint32_t arrived_cores = 0;
    uint32_t expected_cores = 1;
    std::vector<PulseSharedGatherBandProbeEntry> launched_bands;
};

struct PulsePeSharedWindowArrivalResult {
    bool final_arrival = false;
    std::vector<PulseSharedGatherBandProbeEntry> launched_bands;
};

static std::mutex& pulsePeSharedWindowFinalizeMutex_() {
    static std::mutex mutex;
    return mutex;
}

static std::unordered_map<
    PulsePeSharedWindowKey,
    PulsePeSharedWindowFinalizeEntry,
    PulsePeSharedWindowKeyHash>& pulsePeSharedWindowFinalizeEntries_() {
    static std::unordered_map<
        PulsePeSharedWindowKey,
        PulsePeSharedWindowFinalizeEntry,
        PulsePeSharedWindowKeyHash> entries;
    return entries;
}

static PulsePeSharedWindowArrivalResult registerPulsePeSharedWindowArrival_(
    uint32_t scope_id,
    uint32_t window_seq,
    uint32_t core_id,
    uint32_t total_cores,
    const std::vector<PulseSharedGatherBandProbeEntry>& local_bands) {
    std::lock_guard<std::mutex> lock(pulsePeSharedWindowFinalizeMutex_());

    PulsePeSharedWindowKey key{};
    key.scope_id = scope_id;
    key.window_seq = window_seq;

    auto& entry = pulsePeSharedWindowFinalizeEntries_()[key];
    entry.expected_cores = std::max<uint32_t>(
        entry.expected_cores,
        std::max<uint32_t>(1u, total_cores));

    const uint64_t bit = (core_id < 64u) ? (1ull << core_id) : 0ull;
    const bool already_arrived =
        (bit != 0ull) ? ((entry.arrived_core_bitmap & bit) != 0ull) : false;
    if (!already_arrived) {
        if (bit != 0ull) entry.arrived_core_bitmap |= bit;
        entry.arrived_cores += 1u;

        for (const auto& local_band : local_bands) {
            auto band_it = std::find_if(
                entry.launched_bands.begin(),
                entry.launched_bands.end(),
                [&local_band](const PulseSharedGatherBandProbeEntry& existing) {
                    return existing.band_id == local_band.band_id;
                });
            if (band_it == entry.launched_bands.end()) {
                entry.launched_bands.push_back(local_band);
                continue;
            }

            band_it->head_distance = std::min<uint32_t>(
                band_it->head_distance,
                local_band.head_distance);
            for (uint64_t line_addr : local_band.selected_line_addrs) {
                const auto existing = std::find(
                    band_it->selected_line_addrs.begin(),
                    band_it->selected_line_addrs.end(),
                    line_addr);
                if (existing == band_it->selected_line_addrs.end()) {
                    band_it->selected_line_addrs.push_back(line_addr);
                }
            }
        }
    }

    PulsePeSharedWindowArrivalResult result{};
    if (entry.arrived_cores < entry.expected_cores) {
        return result;
    }

    result.final_arrival = true;
    result.launched_bands = entry.launched_bands;
    pulsePeSharedWindowFinalizeEntries_().erase(key);
    return result;
}

static bool readFileSlice(const std::string& path, uint64_t offset, size_t bytes, std::vector<uint8_t>& out) {
    out.clear();
    if (bytes == 0) return false;
    std::ifstream f(path, std::ios::in | std::ios::binary);
    if (!f.is_open()) return false;
    f.seekg(static_cast<std::streamoff>(offset), std::ios::beg);
    if (!f.good()) return false;
    out.resize(bytes, 0);
    f.read(reinterpret_cast<char*>(out.data()), static_cast<std::streamsize>(bytes));
    return static_cast<size_t>(f.gcount()) == bytes;
}

struct RowIndexPrefetchPolicy {
    std::string mode;
    uint32_t block_rows = 0;
    uint32_t n_block_rows = 0;
    bool enabled = false;
    bool auto_all_rows = false;
};

static RowIndexPrefetchPolicy computeRowIndexPrefetchPolicy(const WeightMemorySubsystem::OrchestratorConfig& orch) {
    RowIndexPrefetchPolicy p{};
    if (!orch.use_bcsr || !orch.bcsr_mgr) return p;
    if (!orch.bcsr_mgr->isRowptrReady()) return p;

    p.mode = toLowerCopy(orch.bcsr_row_index_prefetch_mode);
    if (p.mode.empty()) p.mode = "auto";
    if (p.mode == "off") return p;

    p.block_rows = orch.bcsr_mgr->effectiveBlockRows();
    p.n_block_rows =
        p.block_rows ? ((orch.num_neurons + p.block_rows - 1u) / p.block_rows) : static_cast<uint32_t>(orch.num_neurons);
    if (p.n_block_rows == 0) return p;

    p.enabled = true;
    if (p.mode == "auto" && p.n_block_rows <= orch.bcsr_row_index_prefetch_all_rows_threshold) {
        uint32_t last_start = 0;
        uint32_t last_end = 0;
        if (orch.bcsr_mgr->rowBounds(p.n_block_rows - 1u, last_start, last_end) && last_end > 0) {
            const size_t colidx_bytes = orch.bcsr_mgr->colIndexBytes(last_end);
            p.auto_all_rows = (colidx_bytes <= orch.bcsr_row_index_prefetch_all_rows_max_bytes);
        }
    }
    return p;
}
} // namespace

void WeightMemorySubsystem::onClockTick(uint64_t now_cycle) {
    setNowCycle(now_cycle);
    if (usePerPostRetire_()) {
        tryRetireEdgesPerPost_();
    }
    noteShadowRecoverableOnTick_();
    drainShadowPerPostRetire_();
    updateRetireHolStatsOnTick_();
    if (weight_sram_enable_) {
        idx_sram_model_.onClockTick(now_cycle);
        l0_sram_model_.onClockTick(now_cycle);
        weight_sram_stall_budget_cycles_ = std::min<uint64_t>(
            std::numeric_limits<uint64_t>::max(),
            weight_sram_stall_budget_cycles_ + idx_sram_model_.consumeLastCyclePredictedExtraCycles());
        weight_sram_stall_budget_cycles_ = std::min<uint64_t>(
            std::numeric_limits<uint64_t>::max(),
            weight_sram_stall_budget_cycles_ + l0_sram_model_.consumeLastCyclePredictedExtraCycles());
    }
    if (shared_weight_object_plane_) {
        shared_weight_object_plane_->onClockTick(now_cycle);
    }
    if (pe_local_service_object_table_ && pe_local_service_object_table_->enabled()) {
        pe_local_service_object_table_->onClockTick(now_cycle);
    }
    if (weight_sram_stall_budget_cycles_ > 0) {
        --weight_sram_stall_budget_cycles_;
        weight_sram_stall_cycles_total_ = std::min<uint64_t>(
            std::numeric_limits<uint64_t>::max(),
            weight_sram_stall_cycles_total_ + 1ull);
        if (!observeOnlyWeightSramStall_()) {
            return;
        }
    }
    // BCSR rowptr 预取与后续 prefetchAll 都在内存子系统内闭环
    maybeIssueBcsrRowptrPrefetch_();
    drainExperimentalNocRowidxPrefetch_();
    drainPendingReads_();
    drainRowIndexPrefetch_();
    drainPendingDirectReads_();
    drainPendingBcsrRowptrWaiters_();
}

void WeightMemorySubsystem::noteIdxSramReadMirror_(uint64_t addr, size_t bytes) {
    if (weight_sram_enable_ && weight_idx_sram_enable_) {
        idx_sram_model_.noteRead(now_cycle_, addr, bytes);
    }
    if (shared_weight_object_plane_) {
        shared_weight_object_plane_->noteIdxRead(now_cycle_, addr, bytes);
    }
}

void WeightMemorySubsystem::noteIdxSramResidentMirror_(uint64_t bytes) {
    if (shared_weight_object_plane_ && shared_weight_object_plane_residency_authority_) {
        shared_weight_object_plane_->noteResidentIdxBytes(bytes);
        return;
    }
    if (weight_sram_enable_ && weight_idx_sram_enable_) {
        idx_sram_model_.noteResidentBytes(bytes);
    }
    if (shared_weight_object_plane_) {
        shared_weight_object_plane_->noteResidentIdxBytes(bytes);
    }
}

void WeightMemorySubsystem::noteL0SramReadMirror_(uint64_t addr) {
    if (weight_sram_enable_ && weight_l0_sram_enable_) {
        l0_sram_model_.noteRead(now_cycle_, sram_layout_.l0SlotAddr(addr), sizeof(float));
    }
    if (shared_weight_object_plane_) {
        shared_weight_object_plane_->noteL0Read(now_cycle_, addr);
    }
}

void WeightMemorySubsystem::noteL0SramWriteMirror_(uint64_t addr) {
    if (weight_sram_enable_ && weight_l0_sram_enable_) {
        l0_sram_model_.noteWrite(now_cycle_, sram_layout_.l0SlotAddr(addr), sizeof(float));
    }
    if (shared_weight_object_plane_) {
        shared_weight_object_plane_->noteL0Write(now_cycle_, addr);
    }
}

void WeightMemorySubsystem::noteL0SramResidentMirror_(uint64_t bytes) {
    if (shared_weight_object_plane_ && shared_weight_object_plane_residency_authority_) {
        shared_weight_object_plane_->noteResidentL0Bytes(bytes);
        return;
    }
    if (weight_sram_enable_ && weight_l0_sram_enable_) {
        l0_sram_model_.noteResidentBytes(bytes);
    }
    if (shared_weight_object_plane_) {
        shared_weight_object_plane_->noteResidentL0Bytes(bytes);
    }
}

WeightMemorySubsystem::IssueStatus
WeightMemorySubsystem::tryIssueRead_(PendingMeta meta, bool count_budget, bool budget_reserved) {
    if (!mem_access_ || meta.size == 0) {
        if (meta.has_single_cb && meta.single_cb) meta.single_cb(0.0f);
        if (meta.has_bytes_cb && meta.bytes_cb) { const std::vector<uint8_t> empty{}; meta.bytes_cb(empty); }
        return IssueStatus::Failed;
    }

    const bool in_window_budget = count_budget && (window_seq_ != 0);
    const bool budget_limited =
        (!budget_reserved) &&
        in_window_budget &&
        (window_.budget != 0) &&
        (window_.issued + 1u > window_.budget);
    // Semantic seal: window_read_budget is a soft scheduling hint only.
    // Correctness must not depend on whether requests were coalesced.
    (void)budget_limited;

    const bool inflight_ok =
        (window_.max_outstanding == 0u) ||
        (window_.outstanding + 1u <= window_.max_outstanding);
    if (!inflight_ok) {
        // Hard throttle remains max_outstanding.
        return IssueStatus::DeferredInflight;
    }

    // Issue now: update per-window issued counter for observability and inflight accounting.
    if (!budget_reserved && in_window_budget) {
        window_.issued += 1u;
    }
    window_.outstanding += 1u;
    if (window_.outstanding > window_.peak_outstanding) {
        window_.peak_outstanding = window_.outstanding;
    }
    if (orch_.update_pending_peak) orch_.update_pending_peak(peakOutstanding());

    const size_t tracked_retire_seq = meta.retire_seq;
    const int tracked_kind = meta.bcsr_kind;
    meta.counted_inflight = true;
    const uint64_t req = issueRead_(std::move(meta));
    if (req != 0) {
        if (tracked_kind == 4 && tracked_retire_seq != std::numeric_limits<size_t>::max()) {
            setEdgeRetireIssued_(tracked_retire_seq);
        }
        return IssueStatus::Issued;
    }

    // Roll back accounting on issue failure.
    if (!budget_reserved && in_window_budget) {
        if (window_.issued > 0) window_.issued -= 1u;
        else window_.issued = 0;
    }
    if (window_.outstanding > 0) window_.outstanding -= 1u;
    else window_.outstanding = 0;
    return IssueStatus::Failed;
}

void WeightMemorySubsystem::drainPendingReads_() {
    if (drain_pending_in_progress_) return;
    drain_pending_in_progress_ = true;

    auto fail_waiters = [](auto& waiters) {
        for (auto& ww : waiters) {
            if (ww.cb) ww.cb(0.0f);
        }
    };

    auto drain_inflight_queue =
        [this, &fail_waiters](auto& pending_queue, auto& inflight_map, auto&& make_meta, auto&& on_issued) -> bool {
        while (!pending_queue.empty()) {
            const uint64_t inflight_key = pending_queue.front();
            auto it = inflight_map.find(inflight_key);
            if (it == inflight_map.end()) {
                pending_queue.pop_front();
                continue;
            }
            auto& inflight = it->second;
            if (inflight.issued) {
                inflight.queued = false;
                pending_queue.pop_front();
                continue;
            }
            if (!orch_.use_bcsr || !orch_.bcsr_mgr) {
                auto waiters = std::move(inflight.waiters);
                inflight_map.erase(it);
                pending_queue.pop_front();
                fail_waiters(waiters);
                continue;
            }

            PendingMeta meta = make_meta(inflight);
            const IssueStatus st = tryIssueRead_(std::move(meta), inflight.count_budget, /*budget_reserved*/true);
            if (st == IssueStatus::Issued) {
                inflight.issued = true;
                inflight.queued = false;
                pending_queue.pop_front();
                on_issued();
                return true;
            }
            if (st == IssueStatus::DeferredInflight) return false;
            if (st == IssueStatus::DeferredBudget) return false;

            // Failed
            auto waiters = std::move(inflight.waiters);
            inflight_map.erase(it);
            pending_queue.pop_front();
            fail_waiters(waiters);
            return true;
        }
        return false;
    };

    auto drain_colidx = [this, &drain_inflight_queue]() -> bool {
        auto make_meta = [this](const ColidxInflight& inflight) -> PendingMeta {
            const uint32_t block_count = (inflight.row_end > inflight.row_start)
                                             ? (inflight.row_end - inflight.row_start)
                                             : 0;
            const size_t bytes = orch_.bcsr_mgr ? orch_.bcsr_mgr->colIndexBytes(block_count) : 0;
            const uint64_t addr = orch_.bcsr_mgr ? orch_.bcsr_mgr->colIndexAddr(inflight.row_start) : 0;

            PendingMeta meta{};
            meta.window_seq = inflight.window_seq;
            meta.address = addr;
            meta.size = bytes;
            meta.orig_address = addr;
            meta.orig_size = bytes;
            meta.slice_offset = 0;
            meta.issue_cycle = now_cycle_;
            meta.bcsr_kind = 2;
            meta.bcsr_block_row = inflight.block_row;
            meta.bcsr_target_block_col = UINT32_MAX;
            meta.bcsr_row_start = inflight.row_start;
            meta.bcsr_prefetch_all = false;
            meta.experimental_noc_rowidx = inflight.experimental_noc_rowidx;
            meta.has_single_cb = false;
            meta.is_weight = true;
            meta.count_weight_read = false;
            return meta;
        };

        auto on_issued = [this]() {
            if (diag_debug_ && diag_window_active_) diag_win_.rowidx_miss += 1;
        };

        return drain_inflight_queue(pending_colidx_reads_, inflight_colidx_, make_meta, on_issued);
    };

    auto drain_block = [this, &drain_inflight_queue]() -> bool {
        auto make_meta = [this](const BlockInflight& inflight) -> PendingMeta {
            const size_t block_bytes = orch_.bcsr_mgr ? orch_.bcsr_mgr->blockBytes() : 0;
            const size_t row_bytes = orch_.bcsr_mgr ? orch_.bcsr_mgr->blockRowBytes() : 0;
            uint64_t addr = 0;
            size_t req_orig_size = block_bytes;
            if (orch_.bcsr_mgr) {
                addr = orch_.bcsr_mgr->blockDataAddrByRow(inflight.block_row, inflight.idx_in_row);
                if (bcsr_block_fetch_mode_ == BcsrBlockFetchMode::RowCacheline) {
                    addr += static_cast<uint64_t>(inflight.intra_row) * static_cast<uint64_t>(row_bytes);
                    req_orig_size = row_bytes;
                }
            }
            uint64_t req_addr = addr;
            size_t req_size = req_orig_size;
            size_t slice_off = 0;
            prepareAlignedRead(addr, req_orig_size, orch_.line_size_bytes, req_addr, req_size, slice_off);

            PendingMeta meta{};
            meta.window_seq = inflight.window_seq;
            meta.address = req_addr;
            meta.size = req_size;
            meta.orig_address = addr;
            meta.orig_size = req_orig_size;
            meta.slice_offset = slice_off;
            meta.issue_cycle = now_cycle_;
            meta.bcsr_kind = 3;
            meta.bcsr_block_row = inflight.block_row;
            meta.bcsr_target_block_col = inflight.block_col;
            meta.bcsr_idx_in_row = inflight.idx_in_row;
            meta.bcsr_intra_row = inflight.intra_row;
            meta.bcsr_global_block_index = inflight.global_block_index;
            meta.bcsr_row_slice_fetch = (bcsr_block_fetch_mode_ == BcsrBlockFetchMode::RowCacheline);
            meta.bcsr_prefetch_all = false;
            meta.has_single_cb = false;
            meta.is_weight = true;
            meta.count_weight_read = true;
            return meta;
        };

        auto on_issued = [this]() {
            if (diag_debug_ && diag_window_active_) diag_win_.block_miss += 1;
        };

        return drain_inflight_queue(pending_block_reads_, inflight_block_, make_meta, on_issued);
    };

    // Priority: colidx first (unblocks many blocks), then blockdata.
    while (true) {
        bool progressed = false;
        progressed |= drain_colidx();
        progressed |= drain_block();
        if (!progressed) break;
        if (window_.max_outstanding != 0 && window_.outstanding >= window_.max_outstanding) break;
    }

    drain_pending_in_progress_ = false;
}

void WeightMemorySubsystem::drainPendingDirectReads_() {
    if (pending_direct_reads_.empty()) return;

    while (!pending_direct_reads_.empty()) {
        if (window_.max_outstanding != 0 && window_.outstanding >= window_.max_outstanding) break;

        PendingMeta meta = std::move(pending_direct_reads_.front());
        pending_direct_reads_.pop_front();

        // Direct reads can be used by naive baseline and by BCSR paths when coalescing is disabled.
        const bool count_budget = (window_seq_ != 0);
        const IssueStatus st = tryIssueRead_(meta, /*count_budget*/count_budget, /*budget_reserved*/false);
        if (st == IssueStatus::Issued) {
            if (meta.bcsr_kind == 4 &&
                meta.pending_enqueue_cycle != std::numeric_limits<uint64_t>::max() &&
                now_cycle_ >= meta.pending_enqueue_cycle) {
                const uint64_t residency_cycles = now_cycle_ - meta.pending_enqueue_cycle;
                retire_gcss_qni_pending_direct_queue_residency_cycles_total_ += residency_cycles;
                retire_gcss_qni_pending_direct_queue_residency_samples_total_ += 1;
                retire_gcss_qni_pending_direct_queue_residency_cycles_max_ = std::max<uint64_t>(
                    retire_gcss_qni_pending_direct_queue_residency_cycles_max_,
                    residency_cycles);
            }
            continue;
        }
        if (st == IssueStatus::DeferredInflight || st == IssueStatus::DeferredBudget) {
            pending_direct_reads_.push_front(std::move(meta));
            break;
        }
        // Failed: preserve forward progress by failing the request (callback returns 0.0f).
        if (meta.has_single_cb && meta.single_cb) meta.single_cb(0.0f);
        if (meta.has_bytes_cb && meta.bytes_cb) {
            const std::vector<uint8_t> empty{};
            meta.bytes_cb(empty);
        }
    }
}

void WeightMemorySubsystem::maybeExportPreWindowProfile_(uint32_t seq) {
    if (!orch_.experimental_pre_window_profile_export_enable) return;
    if (seq == 0u) return;
    if (orch_.experimental_pre_window_profile_export_dir.empty()) return;

    char path_buf[1024];
    std::snprintf(path_buf, sizeof(path_buf), "%s/pe%02u/core%02u.pre_windows.csv",
                  orch_.experimental_pre_window_profile_export_dir.c_str(),
                  static_cast<unsigned>(orch_.node_id),
                  static_cast<unsigned>(orch_.core_id));
    const std::string path(path_buf);

    bool need_header = true;
    {
        std::ifstream probe(path.c_str(), std::ios::in);
        if (probe.good()) {
            need_header = (probe.peek() == std::ifstream::traits_type::eof());
        }
    }

    std::ofstream fout(path.c_str(), std::ios::out | std::ios::app);
    if (!fout.is_open()) return;
    if (need_header) {
        fout << "window_id,pre_count,pre_touch_order\n";
    }
    fout << seq << "," << pre_touch_order_window_.size() << ",\"";
    for (size_t i = 0; i < pre_touch_order_window_.size(); ++i) {
        if (i != 0u) fout << ' ';
        fout << pre_touch_order_window_[i];
    }
    fout << "\"\n";
}

void WeightMemorySubsystem::maybeExportOfflineLayoutProfile_(
    uint32_t seq,
    const std::vector<GcssVlfEdgeIssueEntry>& raw_edges,
    const std::vector<GcssVlfEdgeIssueEntry>& ordered_edges,
    uint64_t line_size,
    const std::string& queue_policy) {
    if (!orch_.experimental_pre_window_profile_export_enable) return;
    if (seq == 0u) return;
    if (orch_.experimental_pre_window_profile_export_dir.empty()) return;
    if (raw_edges.empty() || ordered_edges.empty()) return;

    const uint64_t safe_line_size = std::max<uint64_t>(1u, line_size);
    char path_buf[1024];
    std::snprintf(path_buf, sizeof(path_buf), "%s/pe%02u/core%02u.offline_layout_profile.csv",
                  orch_.experimental_pre_window_profile_export_dir.c_str(),
                  static_cast<unsigned>(orch_.node_id),
                  static_cast<unsigned>(orch_.core_id));
    const std::string path(path_buf);

    bool need_header = true;
    {
        std::ifstream probe(path.c_str(), std::ios::in);
        if (probe.good()) {
            need_header = (probe.peek() == std::ifstream::traits_type::eof());
        }
    }

    std::ofstream fout(path.c_str(), std::ios::out | std::ios::app);
    if (!fout.is_open()) return;
    if (need_header) {
        fout << "window_id,queue_policy,retire_seq,local_age_rank,ordered_rank,younger_ahead_depth,"
                "post_local,pre_global,pre_rank,count,addr,line_id\n";
    }

    std::unordered_map<size_t, size_t> ordered_rank_by_seq;
    ordered_rank_by_seq.reserve(ordered_edges.size());
    for (size_t i = 0; i < ordered_edges.size(); ++i) {
        ordered_rank_by_seq.emplace(ordered_edges[i].retire_seq, i);
    }

    const size_t unknown_rank = std::numeric_limits<size_t>::max();
    for (const auto& e : raw_edges) {
        const auto it = ordered_rank_by_seq.find(e.retire_seq);
        const size_t ordered_rank = (it == ordered_rank_by_seq.end()) ? unknown_rank : it->second;
        uint64_t younger_ahead_depth = 0;
        if (ordered_rank != unknown_rank && ordered_rank > e.local_age_rank) {
            younger_ahead_depth = static_cast<uint64_t>(ordered_rank - e.local_age_rank);
        }
        const uint64_t line_id = e.addr / safe_line_size;

        fout << seq
             << "," << queue_policy
             << "," << e.retire_seq
             << "," << e.local_age_rank
             << "," << (ordered_rank == unknown_rank ? -1 : static_cast<long long>(ordered_rank))
             << "," << younger_ahead_depth
             << "," << e.post_local
             << "," << e.pre_global
             << "," << e.pre_rank
             << "," << e.count
             << "," << e.addr
             << "," << line_id
             << "\n";
    }
}

bool WeightMemorySubsystem::experimentalNocRowidxPrefetchEnabled_() const {
    return orch_.experimental_noc_rowidx_prefetch_enable && orch_.use_bcsr && (orch_.bcsr_mgr != nullptr);
}

void WeightMemorySubsystem::resetExperimentalNocRowidxWindow_() {
    experimental_noc_rowidx_pending_rows_.clear();
    experimental_noc_rowidx_owner_close_rows_.clear();
    if (!experimentalNocRowidxPrefetchEnabled_()) {
        experimental_noc_rowidx_touched_rows_.clear();
        experimental_noc_rowidx_touch_counts_.clear();
        experimental_noc_rowidx_owner_close_seen_.clear();
        return;
    }
    const uint32_t br = orch_.bcsr_mgr->effectiveBlockRows();
    const uint32_t n_block_rows =
        br ? ((orch_.num_neurons + br - 1u) / br) : static_cast<uint32_t>(orch_.num_neurons);
    if (experimental_noc_rowidx_touched_rows_.size() != n_block_rows) {
        experimental_noc_rowidx_touched_rows_.assign(n_block_rows, 0);
    } else {
        std::fill(experimental_noc_rowidx_touched_rows_.begin(), experimental_noc_rowidx_touched_rows_.end(), 0);
    }
    if (experimental_noc_rowidx_touch_counts_.size() != n_block_rows) {
        experimental_noc_rowidx_touch_counts_.assign(n_block_rows, 0);
    } else {
        std::fill(experimental_noc_rowidx_touch_counts_.begin(), experimental_noc_rowidx_touch_counts_.end(), 0);
    }
    if (experimental_noc_rowidx_owner_close_seen_.size() != n_block_rows) {
        experimental_noc_rowidx_owner_close_seen_.assign(n_block_rows, 0);
    } else {
        std::fill(
            experimental_noc_rowidx_owner_close_seen_.begin(),
            experimental_noc_rowidx_owner_close_seen_.end(),
            0);
    }
}

void WeightMemorySubsystem::noteExperimentalNocRowidxTouch_(uint32_t post_local) {
    if (!experimentalNocRowidxPrefetchEnabled_()) return;
    if (post_local >= orch_.num_neurons) return;
    if (orch_.experimental_noc_rowidx_prefetch_gather_only && window_seq_ != 0) return;
    const uint32_t br = orch_.bcsr_mgr->effectiveBlockRows();
    if (br == 0) return;
    const uint32_t block_row = post_local / br;
    const uint32_t n_block_rows =
        (orch_.num_neurons + br - 1u) / br;
    if (experimental_noc_rowidx_touched_rows_.size() != n_block_rows) {
        experimental_noc_rowidx_touched_rows_.assign(n_block_rows, 0);
    }
    if (experimental_noc_rowidx_touch_counts_.size() != n_block_rows) {
        experimental_noc_rowidx_touch_counts_.assign(n_block_rows, 0);
    }
    if (block_row >= experimental_noc_rowidx_touched_rows_.size()) return;

    experimental_noc_rowidx_stats_.touch_events_total += 1;

    uint16_t& touches = experimental_noc_rowidx_touch_counts_[block_row];
    if (touches < UINT16_MAX) touches = static_cast<uint16_t>(touches + 1u);
    if (experimental_noc_rowidx_touched_rows_[block_row]) return;

    const uint32_t hot_touch_min = std::max<uint32_t>(1u, orch_.experimental_noc_rowidx_hot_touch_min);
    if (touches < hot_touch_min) {
        experimental_noc_rowidx_stats_.rows_filtered_cold += 1;
        return;
    }

    experimental_noc_rowidx_touched_rows_[block_row] = 1;
    if (window_seq_ != 0u) {
        observePeInternalPodMetadataObject_(
            PodMetadataObjectPlane::MetadataKind::RowIndex,
            static_cast<uint64_t>(block_row),
            /*experimental_rowindex_owner_track=*/true);
    }
    experimental_noc_rowidx_pending_rows_.push_back(block_row);
    experimental_noc_rowidx_stats_.rows_touched_enqueued += 1;
}

void WeightMemorySubsystem::maybePromoteExperimentalNocRowidxTouchesToApplyWindow_() {
    if (window_seq_ == 0u) return;
    if (!experimentalNocRowidxPrefetchEnabled_()) return;
    if (experimental_noc_rowidx_touched_rows_.empty()) return;

    for (uint32_t block_row = 0; block_row < experimental_noc_rowidx_touched_rows_.size(); ++block_row) {
        if (!experimental_noc_rowidx_touched_rows_[block_row]) continue;

        experimental_noc_rowidx_stats_.apply_promote_rows_total += 1u;
        observePeInternalPodMetadataObject_(
            PodMetadataObjectPlane::MetadataKind::RowIndex,
            static_cast<uint64_t>(block_row),
            /*experimental_rowindex_owner_track=*/true);

        const auto cache_it = experimental_noc_rowidx_cache_.find(block_row);
        if (cache_it == experimental_noc_rowidx_cache_.end()) continue;

        experimental_noc_rowidx_stats_.apply_promote_cached_ready_total += 1u;
        if (notePeInternalPodServiceObjectReady_(
                PodMetadataObjectPlane::MetadataKind::RowIndex,
                static_cast<uint64_t>(block_row),
                window_seq_)) {
            experimental_noc_rowidx_stats_.ready_transition_apply_promote_cached_total += 1u;
        }
    }
}

uint32_t WeightMemorySubsystem::computeExperimentalNocRowidxBudget_() {
    const uint32_t queue_depth = static_cast<uint32_t>(experimental_noc_rowidx_pending_rows_.size());
    if (queue_depth == 0) return 0;

    const uint32_t base_budget = std::max<uint32_t>(1u, orch_.experimental_noc_rowidx_prefetch_budget_per_tick);
    uint32_t budget = base_budget;

    experimental_noc_rowidx_stats_.budget_ticks_total += 1;

    if (orch_.experimental_noc_rowidx_budget_adapt_enable) {
        const uint32_t max_budget =
            std::max<uint32_t>(base_budget, orch_.experimental_noc_rowidx_budget_adapt_max_per_tick);
        const uint32_t q_depth_target =
            std::max<uint32_t>(1u, orch_.experimental_noc_rowidx_budget_adapt_q_depth);

        if (max_budget > base_budget && queue_depth > q_depth_target) {
            const uint32_t extra_range = max_budget - base_budget;
            const uint64_t scaled = static_cast<uint64_t>(extra_range) *
                                    static_cast<uint64_t>(queue_depth - q_depth_target);
            const uint32_t extra = static_cast<uint32_t>(std::min<uint64_t>(
                extra_range, (scaled + q_depth_target - 1u) / q_depth_target));
            budget = std::min<uint32_t>(max_budget, base_budget + extra);
        } else {
            budget = std::min<uint32_t>(budget, max_budget);
        }

        if (window_.max_outstanding > 0) {
            uint32_t inflight_headroom = 0;
            if (window_.outstanding < window_.max_outstanding) {
                inflight_headroom = window_.max_outstanding - window_.outstanding;
            }
            budget = std::min<uint32_t>(budget, inflight_headroom);
        }
    }

    budget = std::min<uint32_t>(budget, queue_depth);
    if (orch_.experimental_noc_rowidx_budget_adapt_enable && budget != base_budget) {
        experimental_noc_rowidx_stats_.budget_adapt_ticks += 1;
    }
    experimental_noc_rowidx_stats_.budget_effective_total += budget;
    return budget;
}

bool WeightMemorySubsystem::lookupExperimentalNocRowidxCache_(uint32_t block_row,
                                                              uint32_t& row_start_out,
                                                              const std::vector<uint32_t>*& cols_out) {
    cols_out = nullptr;
    row_start_out = 0;
    if (!experimentalNocRowidxPrefetchEnabled_()) return false;
    auto it = experimental_noc_rowidx_cache_.find(block_row);
    if (it == experimental_noc_rowidx_cache_.end()) {
        experimental_noc_rowidx_stats_.cache_misses += 1;
        return false;
    }
    row_start_out = it->second.row_start;
    cols_out = &it->second.cols;
    experimental_noc_rowidx_stats_.cache_hits += 1;
    return true;
}

void WeightMemorySubsystem::storeExperimentalNocRowidxCache_(uint32_t block_row,
                                                             uint32_t row_start,
                                                             const std::vector<uint32_t>& cols) {
    if (!experimentalNocRowidxPrefetchEnabled_()) return;
    if (cols.empty()) return;
    auto it = experimental_noc_rowidx_cache_.find(block_row);
    if (it != experimental_noc_rowidx_cache_.end()) {
        it->second.row_start = row_start;
        it->second.cols = cols;
        return;
    }
    const uint32_t cap = orch_.experimental_noc_rowidx_cache_rows;
    if (cap > 0 && experimental_noc_rowidx_cache_.size() >= cap) {
        experimental_noc_rowidx_stats_.cache_full_drop += 1;
        return;
    }
    ExperimentalNocRowidxCacheEntry entry{};
    entry.row_start = row_start;
    entry.cols = cols;
    experimental_noc_rowidx_cache_.emplace(block_row, std::move(entry));
    experimental_noc_rowidx_stats_.cache_fills += 1;
}

void WeightMemorySubsystem::drainExperimentalNocRowidxPrefetch_() {
    if (!experimentalNocRowidxPrefetchEnabled_()) return;
    if (orch_.experimental_noc_rowidx_prefetch_gather_only) {
        if (orch_.experimental_noc_rowidx_prefetch_carry_to_apply_enable) {
            if (window_seq_ == 0u) {
                experimental_noc_rowidx_stats_.drain_skip_phase_gather_total += 1u;
                return;
            }
        } else if (window_seq_ != 0u) {
            experimental_noc_rowidx_stats_.drain_skip_phase_apply_disabled_total += 1u;
            return;
        }
    }
    if (experimental_noc_rowidx_pending_rows_.empty()) {
        experimental_noc_rowidx_stats_.drain_skip_no_pending_total += 1u;
        return;
    }
    if (orch_.ensure_loader_ready && !orch_.ensure_loader_ready()) {
        experimental_noc_rowidx_stats_.drain_skip_loader_not_ready_total += 1u;
        return;
    }
    if (orch_.bcsr_rowptr_ready && !orch_.bcsr_rowptr_ready()) {
        experimental_noc_rowidx_stats_.drain_skip_rowptr_not_ready_total += 1u;
        return;
    }

    uint32_t budget = computeExperimentalNocRowidxBudget_();
    if (budget == 0) {
        experimental_noc_rowidx_stats_.drain_skip_budget_zero_total += 1u;
        return;
    }
    while (budget > 0 && !experimental_noc_rowidx_pending_rows_.empty()) {
        const uint32_t block_row = experimental_noc_rowidx_pending_rows_.front();
        experimental_noc_rowidx_pending_rows_.pop_front();
        budget -= 1;

        if (experimental_noc_rowidx_cache_.find(block_row) != experimental_noc_rowidx_cache_.end()) {
            experimental_noc_rowidx_stats_.drain_skip_cache_hit_total += 1u;
            continue;
        }

        if (experimental_noc_rowidx_detached_inflight_rows_.find(block_row) !=
            experimental_noc_rowidx_detached_inflight_rows_.end()) {
            experimental_noc_rowidx_stats_.drain_skip_detached_inflight_total += 1u;
            continue;
        }

        const uint32_t inflight_window_seq = window_seq_;
        const uint64_t inflight_key = makeInflightKey_(inflight_window_seq, block_row);
        if (inflight_colidx_.find(inflight_key) != inflight_colidx_.end()) {
            experimental_noc_rowidx_stats_.drain_skip_colidx_inflight_total += 1u;
            continue;
        }

        uint32_t start = 0;
        uint32_t end = 0;
        if (!orch_.bcsr_mgr->rowBounds(block_row, start, end)) {
            experimental_noc_rowidx_stats_.drain_skip_empty_row_total += 1u;
            continue;
        }
        if (end <= start) {
            experimental_noc_rowidx_stats_.drain_skip_empty_row_total += 1u;
            continue;
        }
        const uint32_t block_count = end - start;
        const size_t bytes = orch_.bcsr_mgr->colIndexBytes(block_count);
        const uint64_t addr = orch_.bcsr_mgr->colIndexAddr(start);

        PendingMeta meta{};
        meta.window_seq = inflight_window_seq;
        meta.address = addr;
        meta.size = bytes;
        meta.orig_address = addr;
        meta.orig_size = bytes;
        meta.slice_offset = 0;
        meta.issue_cycle = now_cycle_;
        meta.bcsr_kind = 2;
        meta.bcsr_block_row = block_row;
        meta.bcsr_target_block_col = UINT32_MAX;
        meta.bcsr_row_start = start;
        meta.bcsr_prefetch_all = false;
        meta.experimental_noc_rowidx = true;
        meta.has_single_cb = false;
        meta.is_weight = true;
        meta.count_weight_read = false;

        if (orch_.experimental_noc_rowidx_prefetch_detached_enable) {
            const IssueStatus st = tryIssueRead_(std::move(meta), /*count_budget*/false, /*budget_reserved*/false);
            if (st == IssueStatus::Issued) {
                experimental_noc_rowidx_detached_inflight_rows_[block_row] = inflight_window_seq;
                experimental_noc_rowidx_stats_.prefetch_rows_issued += 1;
                experimental_noc_rowidx_stats_.prefetch_bytes_issued += static_cast<uint64_t>(bytes);
                continue;
            }
            if (st == IssueStatus::DeferredInflight) {
                experimental_noc_rowidx_pending_rows_.push_front(block_row);
                experimental_noc_rowidx_stats_.prefetch_rows_deferred += 1;
                break;
            }
            experimental_noc_rowidx_stats_.prefetch_rows_failed += 1;
            continue;
        }

        ColidxInflight inflight{};
        inflight.window_seq = inflight_window_seq;
        inflight.block_row = block_row;
        inflight.row_start = start;
        inflight.row_end = end;
        inflight.issued = false;
        inflight.queued = false;
        inflight.count_budget = false;
        inflight.experimental_noc_rowidx = true;
        inflight_colidx_.emplace(inflight_key, std::move(inflight));

        const IssueStatus st = tryIssueRead_(std::move(meta), /*count_budget*/false, /*budget_reserved*/false);
        if (st == IssueStatus::Issued) {
            auto it = inflight_colidx_.find(inflight_key);
            if (it != inflight_colidx_.end()) {
                it->second.issued = true;
                it->second.queued = false;
            }
            experimental_noc_rowidx_stats_.prefetch_rows_issued += 1;
            experimental_noc_rowidx_stats_.prefetch_bytes_issued += static_cast<uint64_t>(bytes);
            continue;
        }
        if (st == IssueStatus::DeferredInflight) {
            auto it = inflight_colidx_.find(inflight_key);
            if (it != inflight_colidx_.end()) {
                it->second.issued = false;
                it->second.queued = true;
            }
            pending_colidx_reads_.push_back(inflight_key);
            experimental_noc_rowidx_stats_.prefetch_rows_deferred += 1;
            break;
        }
        inflight_colidx_.erase(inflight_key);
        experimental_noc_rowidx_stats_.prefetch_rows_failed += 1;
    }
}

bool WeightMemorySubsystem::experimentalIdx2IngressPrefetchEnabled_() const {
    return false;
}

bool WeightMemorySubsystem::experimentalIdx2IngressAllowApplyCarry_() const {
    return false;
}

bool WeightMemorySubsystem::shouldTailGuardIdx2RespDrop_() const {
    return false;
}

bool WeightMemorySubsystem::observeOnlyWeightSramStall_() const {
    return false;
}

uint32_t WeightMemorySubsystem::computeExperimentalIdx2IngressBudget_() {
    return 0u;
}

uint32_t WeightMemorySubsystem::experimentalIdx2IngressPrefetchMaxInflight_() const {
    return 0u;
}

void WeightMemorySubsystem::maybeEnqueueRowIndexPrefetchAllRows_() {
    if (!kEnableBcsrOptimizations) return;
    const auto p = computeRowIndexPrefetchPolicy(orch_);
    if (!p.enabled) return;

    const bool do_all = (p.mode == "all_rows") || p.auto_all_rows;
    if (!do_all) return;
    if (row_index_prefetch_all_done_) return;

    // Bulk prefetch marker: drainRowIndexPrefetch_ will issue a single colidx read covering all block_rows.
    row_index_prefetch_rows_.push_back(UINT32_MAX);
    row_index_prefetch_all_done_ = true;
    row_index_prefetch_bulk_pending_ = true;
}

void WeightMemorySubsystem::maybeEnqueueRowIndexPrefetchPostsPrev_() {
    if (!kEnableBcsrOptimizations) return;
    const auto p = computeRowIndexPrefetchPolicy(orch_);
    if (!p.enabled) return;

    const bool do_posts_prev = (p.mode == "posts_prev") || (p.mode == "auto" && !p.auto_all_rows);
    if (!do_posts_prev) return;

    const auto& posts = postsPrev();
    if (posts.empty()) return;

    std::vector<uint8_t> seen(p.n_block_rows, 0);
    std::vector<uint32_t> rows;
    rows.reserve(std::min<size_t>(posts.size(), p.n_block_rows));
    for (uint32_t post_local : posts) {
        const uint32_t block_row = p.block_rows ? (post_local / p.block_rows) : post_local;
        if (block_row >= p.n_block_rows) continue;
        if (seen[block_row]) continue;
        seen[block_row] = 1;
        rows.push_back(block_row);
    }
    std::sort(rows.begin(), rows.end());
    for (uint32_t r : rows) row_index_prefetch_rows_.push_back(r);
}

void WeightMemorySubsystem::drainRowIndexPrefetch_() {
    if (!kEnableBcsrOptimizations) return;
    const auto p = computeRowIndexPrefetchPolicy(orch_);
    if (!p.enabled) return;

    while (!row_index_prefetch_rows_.empty()) {
        if (window_.max_outstanding != 0 && window_.outstanding >= window_.max_outstanding) break;
        const uint32_t block_row = row_index_prefetch_rows_.front();
        row_index_prefetch_rows_.pop_front();

        if (block_row == UINT32_MAX) {
            if (row_index_prefetch_bulk_inflight_) continue;
            uint32_t last_start = 0;
            uint32_t last_end = 0;
            if (!orch_.bcsr_mgr->rowBounds(p.n_block_rows - 1u, last_start, last_end)) continue;
            const uint32_t total_blocks = last_end;
            if (total_blocks == 0) continue;

            const size_t bytes = orch_.bcsr_mgr->colIndexBytes(total_blocks);
            const uint64_t addr = orch_.bcsr_mgr->colIndexAddr(0);

            PendingMeta meta{};
            meta.window_seq = window_seq_;
            meta.address = addr;
            meta.size = bytes;
            meta.orig_address = addr;
            meta.orig_size = bytes;
            meta.slice_offset = 0;
            meta.issue_cycle = now_cycle_;
            meta.bcsr_kind = 2;
            meta.bcsr_block_row = UINT32_MAX;
            meta.bcsr_row_start = 0;
            meta.bcsr_target_block_col = UINT32_MAX;
            meta.bcsr_prefetch_all = false;
            meta.bcsr_colidx_bulk_all_rows = true;
            meta.has_single_cb = false;
            meta.is_weight = true;
            meta.count_weight_read = false;

            const IssueStatus st = tryIssueRead_(std::move(meta), /*count_budget*/false, /*budget_reserved*/false);
            if (st == IssueStatus::Issued) {
                row_index_prefetch_bulk_pending_ = false;
                row_index_prefetch_bulk_inflight_ = true;
                continue;
            }
            if (st == IssueStatus::DeferredInflight) {
                row_index_prefetch_rows_.push_front(UINT32_MAX);
                break;
            }
            // Failed/DeferredBudget (shouldn't happen): retry later to preserve forward progress.
            row_index_prefetch_rows_.push_front(UINT32_MAX);
            break;
        }

        std::vector<uint32_t> cached_cols;
        if (orch_.bcsr_mgr->rowIndexGet(block_row, cached_cols)) continue;

        uint32_t start = 0;
        uint32_t end = 0;
        if (!orch_.bcsr_mgr->rowBounds(block_row, start, end)) continue;
        if (end <= start) continue;

        const uint32_t block_count = end - start;
        const size_t bytes = orch_.bcsr_mgr->colIndexBytes(block_count);
        const uint64_t addr = orch_.bcsr_mgr->colIndexAddr(start);

        PendingMeta meta{};
        meta.window_seq = window_seq_;
        meta.address = addr;
        meta.size = bytes;
        meta.orig_address = addr;
        meta.orig_size = bytes;
        meta.slice_offset = 0;
        meta.issue_cycle = now_cycle_;
        meta.bcsr_kind = 2;
        meta.bcsr_block_row = block_row;
        meta.bcsr_row_start = start;
        meta.bcsr_target_block_col = UINT32_MAX; // prefetch-only: do not request a specific block
        meta.bcsr_prefetch_all = false;
        meta.has_single_cb = false;
        meta.is_weight = true;
        meta.count_weight_read = false;

        const IssueStatus st = tryIssueRead_(std::move(meta), /*count_budget*/false, /*budget_reserved*/false);
        if (st == IssueStatus::Issued) continue;
        if (st == IssueStatus::DeferredInflight) {
            row_index_prefetch_rows_.push_front(block_row);
            break;
        }
        // Failed/DeferredBudget: drop this row and continue (budget should not apply to prefetch).
    }
}

void WeightMemorySubsystem::maybeAutoTuneBlockCache_() {
    if (!kEnableBcsrOptimizations) return;
    if (!orch_.use_bcsr || !orch_.bcsr_mgr) return;
    if (!orch_.bcsr_block_cache_auto_tune) return;
    if (orch_.bcsr_block_cache_max_bytes == 0) return;

    const uint32_t misses = block_miss_window_;
    const uint32_t hits = block_hit_window_;
    const uint32_t total = hits + misses;
    if (total == 0) return;
    if (misses < orch_.bcsr_block_cache_tune_min_misses) return;

    const float ratio = static_cast<float>(misses) / static_cast<float>(total);
    if (ratio < orch_.bcsr_block_cache_tune_miss_ratio) return;

    const size_t block_bytes = orch_.bcsr_mgr->blockBytes();
    if (block_bytes == 0) return;
    const uint64_t max_entries_u64 = orch_.bcsr_block_cache_max_bytes / static_cast<uint64_t>(block_bytes);
    if (max_entries_u64 == 0) return;

    uint32_t cap = orch_.bcsr_mgr->blockCacheCapacity();
    if (cap == 0) return; // respect explicit disable

    const uint32_t max_cap =
        (max_entries_u64 > static_cast<uint64_t>(UINT32_MAX))
            ? UINT32_MAX
            : static_cast<uint32_t>(max_entries_u64);
    if (cap >= max_cap) return;

    uint32_t new_cap = cap;
    const uint32_t grow2 = (cap > (UINT32_MAX / 2u)) ? UINT32_MAX : (cap * 2u);
    new_cap = std::max<uint32_t>(grow2, cap + 64u);
    if (new_cap > max_cap) new_cap = max_cap;
    if (new_cap <= cap) return;

    orch_.bcsr_mgr->setBlockCacheCapacity(new_cap);

    static int dbg_tune = 0;
    if (diag_out_ && diag_out_->getVerboseLevel() >= 2 &&
        diag_node_id_ == 0 && diag_core_id_ == 0 && dbg_tune < 32) {
        diag_out_->verbose(CALL_INFO, 2, 0,
            "[bcsr] auto-tune block_cache_cap %u -> %u (miss=%u hit=%u ratio=%.3f max_bytes=%" PRIu64 " block_bytes=%zu)\n",
            cap, new_cap, misses, hits, ratio,
            static_cast<uint64_t>(orch_.bcsr_block_cache_max_bytes),
            block_bytes);
        ++dbg_tune;
    }
}

void WeightMemorySubsystem::noteReadSourceIssue_(int bcsr_kind, size_t req_bytes) {
    const uint64_t bytes = static_cast<uint64_t>(req_bytes);
    switch (bcsr_kind) {
        case 1:
            read_src_rowptr_reqs_ += 1;
            read_src_rowptr_bytes_ += bytes;
            break;
        case 2:
            read_src_colidx_reqs_ += 1;
            read_src_colidx_bytes_ += bytes;
            break;
        case 3:
            read_src_blockdata_reqs_ += 1;
            read_src_blockdata_bytes_ += bytes;
            break;
        case 4:
        case 7:
        case 6:
        case 8:
            read_src_gcss_reqs_ += 1;
            read_src_gcss_bytes_ += bytes;
            break;
        case 5:
            // Experimental STORM-NIP ingress prefetch reads are tracked separately.
            break;
        default:
            read_src_dense_reqs_ += 1;
            read_src_dense_bytes_ += bytes;
            break;
    }
}

uint64_t WeightMemorySubsystem::issueRead_(PendingMeta meta) {
    if (!mem_access_ || meta.size == 0) {
        if (meta.has_single_cb && meta.single_cb) meta.single_cb(0.0f);
        if (meta.has_bytes_cb && meta.bytes_cb) { const std::vector<uint8_t> empty{}; meta.bytes_cb(empty); }
        return 0;
    }
    // Window diagnostic (debug-only): attribute raw issue traffic to current window.
    if (diag_debug_ && diag_window_active_ && diag_out_) {
        diag_win_.issue_cnt_total += 1;
        diag_win_.issue_bytes_total += static_cast<uint64_t>(meta.size);
        switch (meta.bcsr_kind) {
            case 0:
            case 4:
            case 8:
                diag_win_.issue_cnt_dense += 1;
                diag_win_.issue_bytes_dense += static_cast<uint64_t>(meta.size);
                break;
            case 1:
                diag_win_.issue_cnt_rowptr += 1;
                diag_win_.issue_bytes_rowptr += static_cast<uint64_t>(meta.size);
                break;
            case 2:
                diag_win_.issue_cnt_colidx += 1;
                diag_win_.issue_bytes_colidx += static_cast<uint64_t>(meta.size);
                break;
            case 3:
                diag_win_.issue_cnt_block += 1;
                diag_win_.issue_bytes_block += static_cast<uint64_t>(meta.size);
                break;
            default:
                break;
        }
        // bounded duplicate detection on request address
        if (diag_req_addrs_.size() < 65536) {
            const uint64_t key = meta.address ? meta.address : meta.orig_address;
            auto it = diag_req_addrs_.insert(key);
            if (it.second) diag_win_.issue_unique_addrs += 1;
            else diag_win_.issue_dup_addrs += 1;
        }
    }
    if (orch_.report_mem_issue) {
        const size_t report_bytes = meta.report_bytes ? meta.report_bytes : meta.size;
        orch_.report_mem_issue(report_bytes, meta.count_weight_read);
    }
    const int bcsr_kind = meta.bcsr_kind;
    const uint64_t addr = meta.address;
    const size_t bytes = meta.size;
    auto cb = [this, meta = std::move(meta)](uint64_t req_id, uint64_t resp_addr, std::vector<uint8_t>&& data) mutable {
        handleReadResp_(req_id, resp_addr, std::move(meta), std::move(data));
    };

    const uint64_t req_id = mem_access_->read(addr, bytes, std::move(cb));
    if (req_id != 0) {
        noteReadSourceIssue_(bcsr_kind, bytes);
    }
    return req_id;
}

bool WeightMemorySubsystem::prepareDenseRead_(uint32_t row, uint32_t col, uint32_t width,
                                             uint64_t& req_addr, size_t& req_size,
                                             bool& is_row, uint32_t& col_start, uint32_t& count_floats) const {
    const uint32_t bpf = sizeof(float);
    auto denseAddr = [&](uint32_t r, uint32_t c) -> uint64_t {
        if (!dense_phys_enable_) {
            return orch_.base_addr +
                   (static_cast<uint64_t>(r) * static_cast<uint64_t>(width) + static_cast<uint64_t>(c)) * bpf;
        }
        return orch_.base_addr + densePhysV1Offset(r, c, dense_phys_);
    };

    req_addr = denseAddr(row, col);
    req_size = sizeof(float);
    is_row = false;
    col_start = col;
    count_floats = 1;
    if (orch_.read_force_single) return true;

    const bool merge_row = orch_.merge_read_row;
    const bool merge_cl = orch_.merge_read_cacheline;
    const bool merge_auto = orch_.merge_read_auto;

    if (merge_auto) {
        const uint32_t fpl = std::max<uint32_t>(1, orch_.line_size_bytes / bpf);
        const size_t bytes_row = static_cast<size_t>(width) * static_cast<size_t>(bpf);
        const size_t bytes_cl = static_cast<size_t>(fpl) * static_cast<size_t>(bpf);
        const bool choose_row = merge_row && (bytes_row <= bytes_cl);
        if (choose_row) {
            is_row = true;
            col_start = 0;
            count_floats = width;
            req_addr = denseAddr(row, 0);
            req_size = static_cast<size_t>(count_floats) * bpf;
        } else if (merge_cl) {
            col_start = (col / fpl) * fpl;
            count_floats = std::min<uint32_t>(fpl, width - col_start);
            req_addr = denseAddr(row, col_start);
            req_size = static_cast<size_t>(count_floats) * bpf;
        }
        return true;
    }

    if (merge_row) {
        is_row = true;
        col_start = 0;
        count_floats = width;
        req_addr = denseAddr(row, 0);
        req_size = static_cast<size_t>(count_floats) * bpf;
        return true;
    }

    if (merge_cl) {
        const uint32_t fpl = std::max<uint32_t>(1, orch_.line_size_bytes / bpf);
        col_start = (col / fpl) * fpl;
        count_floats = std::min<uint32_t>(fpl, width - col_start);
        req_addr = denseAddr(row, col_start);
        req_size = static_cast<size_t>(count_floats) * bpf;
        return true;
    }

    return true;
}

void WeightMemorySubsystem::issueDenseResolved_(uint32_t row, uint32_t col, uint32_t cb_col,
                                               std::function<void(float)> cb) {
    if (!mem_access_) {
        if (cb) cb(orch_.init_default_weight);
        return;
    }
    const uint32_t width = orch_.use_post_row_pre_col ? orch_.weights_cols : orch_.num_neurons;
    if (width == 0) {
        if (cb) cb(orch_.init_default_weight);
        return;
    }

    uint64_t req_addr = 0;
    size_t req_size = sizeof(float);
    bool is_row = false;
    uint32_t col_start = col;
    uint32_t count_floats = 1;
    (void)prepareDenseRead_(row, col, width, req_addr, req_size, is_row, col_start, count_floats);

    PendingMeta meta{};
    meta.window_seq = 0;
    meta.address = req_addr;
    meta.size = req_size;
    meta.is_row = is_row;
    meta.pre = row;
    meta.post_start = col_start;
    meta.count_floats = count_floats;
    meta.has_single_cb = (cb != nullptr);
    meta.cb_post = cb_col;
    meta.single_cb = std::move(cb);
    meta.issue_cycle = now_cycle_;
    meta.bcsr_kind = 0;
    meta.is_weight = (req_addr >= orch_.base_addr && req_addr < orch_.weight_region_end);
    meta.count_weight_read = true;
    (void)issueRead_(std::move(meta));
}

bool WeightMemorySubsystem::issueDensePrefetchRaw(uint64_t req_addr, size_t req_size,
                                                  uint32_t row, uint32_t col_start, uint32_t count_floats,
                                                  bool scheme1_prefetch) {
    if (!mem_access_) return false;
    if (req_size == 0) return false;
    PendingMeta meta{};
    meta.window_seq = 0;
    meta.address = req_addr;
    meta.size = req_size;
    meta.is_row = false;
    meta.pre = row;
    meta.post_start = col_start;
    meta.count_floats = count_floats;
    meta.has_single_cb = false;
    meta.cb_post = 0;
    meta.issue_cycle = now_cycle_;
    meta.bcsr_kind = 0;
    meta.is_weight = (req_addr >= orch_.base_addr && req_addr < orch_.weight_region_end);
    meta.count_weight_read = true;
    meta.scheme1_prefetch = scheme1_prefetch;
    return issueRead_(std::move(meta)) != 0;
}

void WeightMemorySubsystem::requestDense_(uint32_t pre, uint32_t post, std::function<void(float)> cb) {
    // 兼容：当启用 BCSR 且仍通过 Dense 接口发起时，自动走 BCSR。
    if (orch_.use_bcsr && orch_.use_post_row_pre_col) {
        requestBCSR_(pre, post, std::move(cb));
        return;
    }
    if (!orch_.accessor) {
        if (cb) cb(orch_.init_default_weight);
        return;
    }
    uint32_t req_pre = 0;
    uint32_t req_post = 0;
    uint64_t cache_key = 0;
    if (!orch_.accessor->resolve(pre, post, req_pre, req_post, cache_key)) {
        if (cb) cb(orch_.init_default_weight);
        return;
    }
    const uint32_t row_idx = orch_.use_post_row_pre_col ? req_post : req_pre;
    const uint32_t col_idx = orch_.use_post_row_pre_col ? req_pre : req_post;
    issueDenseResolved_(row_idx, col_idx, /*cb_col*/col_idx, std::move(cb));
}

bool WeightMemorySubsystem::isGcssValueOnlyMode_() const {
    const std::string mode = toLowerCopy(orch_.synapse_weight_mode);
    return mode == "gcss_valueonly_dstcore" ||
           mode == "gscc_valueonly_dstcore" ||
           mode == "gcss_valueonly_dstcore_idx2" ||
           mode == "gcss_idx2_rowmphf" ||
           mode == "gcss_valueonly_dstcore_vlf_premphf" ||
           mode == "gscc_valueonly_dstcore_vlf_premphf" ||
           mode == "gcss_valueonly_dstcore_vlf_premphf_plp" ||
           mode == "gscc_valueonly_dstcore_vlf_premphf_plp";
}

bool WeightMemorySubsystem::isGcssValueOnlyIdx2Mode_() const {
    const std::string mode = toLowerCopy(orch_.synapse_weight_mode);
    return mode == "gcss_valueonly_dstcore_idx2" || mode == "gcss_idx2_rowmphf";
}

bool WeightMemorySubsystem::isGcssValueOnlyPreMphfMode_() const {
    const std::string mode = toLowerCopy(orch_.synapse_weight_mode);
    return mode == "gcss_valueonly_dstcore_vlf_premphf" ||
           mode == "gscc_valueonly_dstcore_vlf_premphf" ||
           mode == "gcss_valueonly_dstcore_vlf_premphf_plp" ||
           mode == "gscc_valueonly_dstcore_vlf_premphf_plp";
}

bool WeightMemorySubsystem::ensureGcssIndexLoaded_() {
    if (!isGcssValueOnlyMode_()) return false;
    const bool pre_mode = isGcssValueOnlyPreMphfMode_();
    const bool idx2_mode = isGcssValueOnlyIdx2Mode_();
    if (pre_mode) {
        if (gcss_premphf_index_loaded_) return true;
        if (gcss_premphf_index_load_failed_) return false;
    } else if (idx2_mode) {
        if (gcss_idx2_index_loaded_) return true;
        if (gcss_idx2_index_load_failed_) return false;
    } else {
        if (gcss_index_loaded_) return true;
        if (gcss_index_load_failed_) return false;
    }

    const std::string resolved = resolveWeightsTemplatePath(
        orch_.gcss_index_template, orch_.node_id, orch_.core_id);
    if (resolved.empty()) {
        if (pre_mode) gcss_premphf_index_load_failed_ = true;
        else if (idx2_mode) gcss_idx2_index_load_failed_ = true;
        else gcss_index_load_failed_ = true;
        SST::Output* out = diagOutOrFallback_();
        out->fatal(CALL_INFO, -1,
                   "WeightMemorySubsystem fatal: GCSS value-only mode requires gcss_index_template (node=%u core=%u mode=%s)\n",
                   orch_.node_id, orch_.core_id, orch_.synapse_weight_mode.c_str());
        return false;
    }

    std::string err;
    bool ok_load = false;
    if (pre_mode) ok_load = gcss_premphf_index_.loadFromFile(resolved, &err);
    else if (idx2_mode) ok_load = gcss_idx2_index_.loadFromFile(resolved, &err);
    else ok_load = gcss_index_.loadFromFile(resolved, &err);
    if (!ok_load) {
        if (pre_mode) gcss_premphf_index_load_failed_ = true;
        else if (idx2_mode) gcss_idx2_index_load_failed_ = true;
        else gcss_index_load_failed_ = true;
        SST::Output* out = diagOutOrFallback_();
        out->fatal(CALL_INFO, -1,
                   "WeightMemorySubsystem fatal: failed to load GCSS index file path=%s mode=%s err=%s\n",
                   resolved.c_str(), orch_.synapse_weight_mode.c_str(), err.c_str());
        return false;
    }

    if (pre_mode) {
        gcss_premphf_index_path_ = resolved;
        gcss_premphf_index_loaded_ = true;
    } else if (idx2_mode) {
        gcss_idx2_index_path_ = resolved;
        gcss_idx2_index_loaded_ = true;
    } else {
        gcss_index_path_ = resolved;
        gcss_index_loaded_ = true;
    }
    if ((weight_sram_enable_ && weight_idx_sram_enable_) || shared_weight_object_plane_) {
        std::ifstream fin(resolved, std::ios::in | std::ios::binary | std::ios::ate);
        if (fin.good()) {
            const std::streamoff sz = fin.tellg();
            if (sz > 0) noteIdxSramResidentMirror_(static_cast<uint64_t>(sz));
        }
    }
    return true;
}

bool WeightMemorySubsystem::lookupGcssWidx_(uint32_t pre_global, uint32_t post_local, uint32_t& out_widx) {
    if (isGcssValueOnlyPreMphfMode_()) return false;
    if (!ensureGcssIndexLoaded_()) return false;
    const bool idx2_mode = isGcssValueOnlyIdx2Mode_();
    noteIdxSramLookup_(pre_global, post_local, idx2_mode);
    bool ok = false;
    if (idx2_mode) {
        ok = gcss_idx2_index_.lookup(pre_global, post_local, out_widx);
    } else {
        if (post_local > 0xFFFFu) {
            gcss_lookup_miss_ += 1;
            return false;
        }
        ok = gcss_index_.lookup(pre_global, post_local, out_widx);
    }
    if (ok) {
        gcss_lookup_hit_ += 1;
        return true;
    }

    gcss_lookup_miss_ += 1;
    if (idx2_mode) {
        SST::Output* out = diagOutOrFallback_();
        out->fatal(
            CALL_INFO, -1,
            "WeightMemorySubsystem fatal: GCSSIDX2 strict lookup miss (mode=%s node=%u core=%u pre=%u post=%u idx_path=%s)\n",
            orch_.synapse_weight_mode.c_str(),
            orch_.node_id,
            orch_.core_id,
            pre_global,
            post_local,
            gcss_idx2_index_path_.c_str());
    }
    return ok;
}

bool WeightMemorySubsystem::lookupGcssPreBaseLen_(uint32_t pre_global,
                                                  uint32_t& out_base,
                                                  uint32_t& out_len) {
    if (!isGcssValueOnlyPreMphfMode_()) return false;
    if (!ensureGcssIndexLoaded_()) return false;
    const uint32_t lookup_scope_id = pulsePrebaseLookupScopeId_();
    if (orch_.pulse_prebase_shared_lookup_enable && window_seq_ != 0u) {
        const auto shared = PulseMetadataLookupRegistry::findPreBase(
            lookup_scope_id,
            window_seq_,
            pre_global,
            orch_.core_id);
        if (shared.hit) {
            out_base = shared.base;
            out_len = shared.len;
            pulse_prebase_lookup_shared_hits_total_ += 1u;
            pulse_prebase_lookup_entries_peak_ = std::max<uint64_t>(
                pulse_prebase_lookup_entries_peak_,
                static_cast<uint64_t>(shared.active_entries));
            return true;
        }
    }

    idx_lookup_total_ += 1;
    idx_lookup_idx2_total_ += 1;
    if ((weight_sram_enable_ && weight_idx_sram_enable_) || shared_weight_object_plane_) {
        // pre-MPHF lookup path: global seed/bucket pilot + slot {base,len}.
        const uint64_t base_addr = sram_layout_.idxLegacyLookupAddr(pre_global, 0u);
        noteIdxSramReadMirror_(base_addr + 0ull, sizeof(uint32_t));   // seed
        noteIdxSramReadMirror_(base_addr + 4ull, sizeof(uint32_t));   // bucket_count
        noteIdxSramReadMirror_(base_addr + 8ull, sizeof(uint8_t));    // pilot
        noteIdxSramReadMirror_(base_addr + 12ull, sizeof(uint32_t));  // slot_base
        noteIdxSramReadMirror_(base_addr + 16ull, sizeof(uint32_t));  // slot_len
    }
    const bool ok = gcss_premphf_index_.lookup(pre_global, out_base, out_len);
    if (ok) {
        if (orch_.pulse_prebase_shared_lookup_enable && window_seq_ != 0u) {
            const auto published = PulseMetadataLookupRegistry::publishPreBase(
                lookup_scope_id,
                window_seq_,
                pre_global,
                out_base,
                out_len,
                orch_.core_id);
            if (published.owner_fill) {
                pulse_prebase_lookup_owner_fill_total_ += 1u;
            }
            pulse_prebase_lookup_entries_peak_ = std::max<uint64_t>(
                pulse_prebase_lookup_entries_peak_,
                static_cast<uint64_t>(published.active_entries));
        }
        return true;
    }

    SST::Output* out = diagOutOrFallback_();
    out->fatal(CALL_INFO, -1,
               "WeightMemorySubsystem fatal: GCSS-VLF pre-MPHF strict lookup miss "
               "(mode=%s node=%u core=%u pre=%u idx_path=%s)\n",
               orch_.synapse_weight_mode.c_str(),
               orch_.node_id,
               orch_.core_id,
               pre_global,
               gcss_premphf_index_path_.c_str());
    return false;
}

void WeightMemorySubsystem::issueGcssByAddr_(uint64_t addr, std::function<void(float)> cb, bool count_weight_read,
                                             size_t retire_seq) {
    if (!mem_access_) {
        if (cb) cb(0.0f);
        return;
    }

    tryActivateDeferredRowdescriptorOwnerFormReplay_();

    if (pulseAnySeededResidencyEnable_() &&
        window_seq_ != 0u &&
        orch_.line_size_bytes >= sizeof(float)) {
        const uint64_t line_size = std::max<uint64_t>(
            static_cast<uint64_t>(sizeof(float)),
            static_cast<uint64_t>(orch_.line_size_bytes));
        const uint64_t line_addr = (addr / line_size) * line_size;
        const auto resident = PulseSeededLineResidency::lookupLine(
            orch_.node_id,
            window_seq_,
            line_addr);
        if (resident.hit) {
            PulseSeededLineTracker::noteResidentHit(
                orch_.node_id,
                window_seq_,
                line_addr);
            notePulseSeedFirstDemand_(line_addr, /*ready_before_demand=*/true);
            float w = 0.0f;
            const uint64_t offset = addr - line_addr;
            if (offset + sizeof(float) <= resident.line_bytes.size()) {
                std::memcpy(&w, resident.line_bytes.data() + offset, sizeof(float));
            }
            if (cb) cb(applyReadRespZeroFallback_(w));
            return;
        }
    }

    if (!orch_.pulse_descriptor_actual_enable) {
        pulse_actual_gate_enable_false_total_ += 1;
    } else if (window_seq_ == 0) {
        pulse_actual_gate_window_zero_total_ += 1;
    } else if (orch_.line_size_bytes < sizeof(float)) {
        pulse_actual_gate_line_too_small_total_ += 1;
    } else {
        pulse_actual_gate_taken_total_ += 1;
        const uint64_t line_size = std::max<uint64_t>(
            static_cast<uint64_t>(sizeof(float)),
            static_cast<uint64_t>(orch_.line_size_bytes));
        const uint64_t line_addr = (addr / line_size) * line_size;
        PulseSharedLineService::ServiceKey key{};
        key.scope_id = orch_.node_id;
        key.window_seq = window_seq_;
        key.line_addr = line_addr;

        auto join = PulseSharedLineService::joinOrRegister(
            key,
            [addr, cb = std::move(cb)](bool ok,
                                       uint64_t service_line_addr,
                                       const std::vector<uint8_t>& line_bytes) mutable {
                float w = 0.0f;
                if (ok && addr >= service_line_addr) {
                    const uint64_t offset = addr - service_line_addr;
                    if (offset + sizeof(float) <= line_bytes.size()) {
                        std::memcpy(&w, line_bytes.data() + offset, sizeof(float));
                    }
                }
                if (cb) cb(w);
            });
        pulse_region_service_entries_peak_ = std::max<uint64_t>(
            pulse_region_service_entries_peak_,
            static_cast<uint64_t>(join.active_entries));
        if (!join.owner) {
            notePulseSeedFirstDemand_(line_addr, /*ready_before_demand=*/false);
            pulse_shared_service_hits_total_ += 1;
            return;
        }
        pulse_shared_service_misses_total_ += 1;

        PendingMeta meta{};
        meta.window_seq = window_seq_;
        meta.address = line_addr;
        meta.size = static_cast<size_t>(line_size);
        meta.orig_address = line_addr;
        meta.orig_size = static_cast<size_t>(line_size);
        meta.slice_offset = 0;
        meta.issue_cycle = now_cycle_;
        meta.pending_enqueue_cycle = std::numeric_limits<uint64_t>::max();
        meta.retire_seq = retire_seq;
        meta.bcsr_kind = 7;  // PULSE GCSS shared-line demand
        meta.pulse_scope_id = orch_.node_id;
        meta.pulse_service_line_addr = line_addr;
        meta.has_single_cb = false;
        meta.is_weight = true;
        meta.count_weight_read = count_weight_read;

        const bool count_budget = (window_seq_ != 0);
        const IssueStatus st = tryIssueRead_(meta, /*count_budget*/count_budget, /*budget_reserved*/false);
        if (st == IssueStatus::Issued) return;
        if (st == IssueStatus::DeferredInflight || st == IssueStatus::DeferredBudget) {
            if (retire_seq != std::numeric_limits<size_t>::max()) {
                retire_gcss_qni_issue_deferred_total_ += 1;
            }
            meta.pending_enqueue_cycle = now_cycle_;
            pending_direct_reads_.push_back(std::move(meta));
            return;
        }
        (void)PulseSharedLineService::complete(key, false, line_addr, std::vector<uint8_t>{});
        return;
    }

    PendingMeta meta{};
    meta.window_seq = window_seq_;
    meta.address = addr;
    meta.size = sizeof(float);
    meta.orig_address = addr;
    meta.orig_size = sizeof(float);
    meta.slice_offset = 0;
    meta.issue_cycle = now_cycle_;
    meta.pending_enqueue_cycle = std::numeric_limits<uint64_t>::max();
    meta.retire_seq = retire_seq;
    meta.bcsr_kind = 4;  // GCSS value-only demand
    meta.has_single_cb = (cb != nullptr);
    meta.single_cb = std::move(cb);
    meta.is_weight = true;
    meta.count_weight_read = count_weight_read;

    const bool count_budget = (window_seq_ != 0);
    const IssueStatus st = tryIssueRead_(meta, /*count_budget*/count_budget, /*budget_reserved*/false);
    if (st == IssueStatus::Issued) return;
    if (st == IssueStatus::DeferredInflight || st == IssueStatus::DeferredBudget) {
        if (retire_seq != std::numeric_limits<size_t>::max()) {
            retire_gcss_qni_issue_deferred_total_ += 1;
        }
        meta.pending_enqueue_cycle = now_cycle_;
        pending_direct_reads_.push_back(std::move(meta));
        return;
    }
    if (meta.has_single_cb && meta.single_cb) meta.single_cb(0.0f);
}

void WeightMemorySubsystem::noteIdxSramLookup_(uint32_t pre_global, uint32_t post_local, bool idx2_mode) {
    idx_lookup_total_ += 1;
    if (idx2_mode) idx_lookup_idx2_total_ += 1;
    else idx_lookup_legacy_total_ += 1;

    if (!(weight_sram_enable_ && weight_idx_sram_enable_) && !shared_weight_object_plane_) return;

    const uint64_t row_addr = sram_layout_.idxRowBaseAddr(post_local);
    noteIdxSramReadMirror_(row_addr + 0ull, sizeof(uint32_t));   // row_base
    noteIdxSramReadMirror_(row_addr + 4ull, sizeof(uint16_t));   // row_len
    noteIdxSramReadMirror_(row_addr + 6ull, sizeof(uint16_t));   // row_bucket_count
    noteIdxSramReadMirror_(row_addr + 8ull, sizeof(uint32_t));   // row_seed
    noteIdxSramReadMirror_(row_addr + 12ull, sizeof(uint32_t));  // row_bucket_off
    if (idx2_mode) {
        const uint32_t bucket = (pre_global ^ post_local) & 0xffu;
        noteIdxSramReadMirror_(sram_layout_.idxPilotAddr(post_local, bucket), sizeof(uint8_t));
    } else {
        const uint64_t legacy_addr = sram_layout_.idxLegacyLookupAddr(pre_global, post_local);
        noteIdxSramReadMirror_(legacy_addr, sizeof(uint32_t));
        noteIdxSramReadMirror_(legacy_addr + 4ull, sizeof(uint32_t));
    }
}

void WeightMemorySubsystem::noteL0SramLookup_(uint64_t addr, bool hit) {
    l0_lookup_total_ += 1;
    if (hit) l0_hit_total_ += 1;
    else l0_miss_total_ += 1;
    if (!(weight_sram_enable_ && weight_l0_sram_enable_) && !shared_weight_object_plane_) return;
    noteL0SramReadMirror_(addr);
}

void WeightMemorySubsystem::noteL0SramFill_(uint64_t addr) {
    l0_fill_total_ += 1;
    if (!(weight_sram_enable_ && weight_l0_sram_enable_) && !shared_weight_object_plane_) return;
    if (shared_weight_object_plane_ && shared_weight_object_plane_residency_authority_) {
        if (weight_sram_enable_ && weight_l0_sram_enable_) {
            l0_sram_model_.noteWrite(now_cycle_, sram_layout_.l0SlotAddr(addr), sizeof(float));
        }
        shared_weight_object_plane_->noteL0Fill(now_cycle_, addr);
        return;
    }
    noteL0SramWriteMirror_(addr);
}

void WeightMemorySubsystem::noteL0SramEvict_(uint64_t addr) {
    l0_evict_total_ += 1;
    if (!(weight_sram_enable_ && weight_l0_sram_enable_) && !shared_weight_object_plane_) return;
    if (shared_weight_object_plane_ && shared_weight_object_plane_residency_authority_) {
        if (weight_sram_enable_ && weight_l0_sram_enable_) {
            l0_sram_model_.noteWrite(now_cycle_, sram_layout_.l0SlotAddr(addr), sizeof(float));
        }
        shared_weight_object_plane_->noteL0Evict(now_cycle_, addr);
        return;
    }
    noteL0SramWriteMirror_(addr);
}

void WeightMemorySubsystem::requestGCSS_(uint32_t widx, std::function<void(float)> cb, size_t retire_seq) {
    if (!mem_access_) {
        if (cb) cb(0.0f);
        return;
    }
    const uint64_t addr = gcssValuesBaseAddr_() + static_cast<uint64_t>(widx) * sizeof(float);
    issueGcssByAddr_(addr, std::move(cb), /*count_weight_read*/true, retire_seq);
}

void WeightMemorySubsystem::resetGcssVlfIssueQueue_() {
    gcss_vlf_issue_queue_.clear();
    gcss_vlf_issue_queue_prepared_ = false;
}

bool WeightMemorySubsystem::popNextGcssVlfIssueEntry_(GcssVlfEdgeIssueEntry& out) {
    if (gcss_vlf_issue_queue_.empty()) return false;
    out = std::move(gcss_vlf_issue_queue_.front());
    gcss_vlf_issue_queue_.pop_front();
    return true;
}

void WeightMemorySubsystem::observePulseFrontier_(
    const std::vector<GcssVlfEdgeIssueEntry>& ordered_edges,
    uint64_t line_size) {
    if (!orch_.pulse_agenda_enable ||
        !orch_.pulse_frontier_observe_enable ||
        window_seq_ == 0u ||
        ordered_edges.empty()) {
        return;
    }

    const size_t budget = std::max<size_t>(
        1u,
        static_cast<size_t>(std::max<uint32_t>(1u, orch_.pulse_frontier_top_lines)));
    std::unordered_set<uint64_t> seen_lines;
    seen_lines.reserve(std::min<size_t>(ordered_edges.size(), budget * 2u));

    uint64_t exported = 0;
    uint64_t overlap_lines = 0;
    uint64_t overlap_peers = 0;
    const uint64_t eff_line_size = std::max<uint64_t>(1u, line_size);
    for (const auto& e : ordered_edges) {
        const uint64_t line_addr = (e.addr / eff_line_size) * eff_line_size;
        if (!seen_lines.insert(line_addr).second) continue;
        const auto result = PulseFrontierObserveRegistry::observeLine(
            orch_.node_id,
            window_seq_,
            line_addr,
            orch_.core_id);
        exported += 1u;
        if (result.prior_consumers > 0u) {
            overlap_lines += 1u;
            overlap_peers += static_cast<uint64_t>(result.prior_consumers);
        }
        if (exported >= budget) break;
    }

    if (exported == 0u) return;
    pulse_frontier_windows_total_ += 1u;
    pulse_frontier_lines_exported_total_ += exported;
    pulse_frontier_overlap_lines_total_ += overlap_lines;
    pulse_frontier_overlap_peer_total_ += overlap_peers;
    pulse_frontier_max_exported_per_window_ = std::max<uint64_t>(
        pulse_frontier_max_exported_per_window_,
        exported);
}

void WeightMemorySubsystem::observePulseMetadataFrontier_(
    const std::vector<GcssVlfEdgeIssueEntry>& ordered_edges) {
    if (!orch_.pulse_agenda_enable ||
        !orch_.pulse_metadata_frontier_observe_enable ||
        window_seq_ == 0u ||
        ordered_edges.empty()) {
        return;
    }

    const size_t top_items = std::max<size_t>(
        1u,
        static_cast<size_t>(
            std::max<uint32_t>(1u, orch_.pulse_metadata_frontier_top_items)));
    const uint32_t band_slots =
        std::max<uint32_t>(1u, orch_.pulse_metadata_frontier_band_slots);
    const uint32_t block_rows =
        (orch_.use_bcsr && orch_.bcsr_mgr != nullptr)
            ? std::max<uint32_t>(1u, orch_.bcsr_mgr->effectiveBlockRows())
            : 1u;

    size_t service_items = 0u;
    size_t observe_only_items = 0u;
    for (const auto& edge : ordered_edges) {
        if (service_items < top_items &&
            pulseMetadataFrontierObserveEligible_(
                PodMetadataObjectPlane::MetadataKind::PreMphfBase)) {
            observePeInternalPodMetadataObject_(
                PodMetadataObjectPlane::MetadataKind::PreMphfBase,
                static_cast<uint64_t>(edge.pre_base));
            service_items += 1u;
        }
        if (service_items < top_items &&
            pulseMetadataFrontierObserveEligible_(
                PodMetadataObjectPlane::MetadataKind::PreMphfBand)) {
            const uint64_t band_id =
                (static_cast<uint64_t>(edge.pre_base) << 1u) ^
                0x1ull ^
                static_cast<uint64_t>(edge.pre_rank / band_slots);
            observePeInternalPodMetadataObject_(
                PodMetadataObjectPlane::MetadataKind::PreMphfBand,
                band_id);
            service_items += 1u;
        }

        if (observe_only_items < top_items &&
            pulseMetadataFrontierObserveEligible_(
                PodMetadataObjectPlane::MetadataKind::Idx2Row)) {
            notePulseMetadataFrontierObserved_(
                PodMetadataObjectPlane::MetadataKind::Idx2Row,
                PodMetadataObjectPlane::composeObjectKey(
                    PodMetadataObjectPlane::MetadataKind::Idx2Row,
                    static_cast<uint64_t>(edge.pre_global)));
            observe_only_items += 1u;
        }
        if (observe_only_items < top_items &&
            pulseMetadataFrontierObserveEligible_(
                PodMetadataObjectPlane::MetadataKind::RowIndex)) {
            const uint64_t rowindex_object =
                static_cast<uint64_t>(edge.post_local / block_rows);
            notePulseMetadataFrontierObserved_(
                PodMetadataObjectPlane::MetadataKind::RowIndex,
                PodMetadataObjectPlane::composeObjectKey(
                    PodMetadataObjectPlane::MetadataKind::RowIndex,
                    rowindex_object));
            observe_only_items += 1u;
        }

        if (service_items >= top_items && observe_only_items >= top_items) {
            break;
        }
    }
}

bool WeightMemorySubsystem::peInternalPodShadowEnabled_() const {
    PeInternalPodShadowGateConfig cfg{};
    cfg.pe_internal_cpe_enable = orch_.pe_internal_cpe_enable;
    cfg.pe_internal_pod_enable = orch_.pe_internal_pod_enable;
    cfg.pe_internal_pod_metadata_enable = orch_.pe_internal_pod_metadata_enable;
    cfg.pe_internal_pod_owner_enable = orch_.pe_internal_pod_owner_enable;
    cfg.pod_count = orch_.pe_internal_pod_count;

    PeInternalPodShadowGateBindings bindings{};
    bindings.metadata_plane = pod_metadata_object_plane_;
    bindings.owner_table = pod_owner_service_table_;
    bindings.fabric = pe_shared_core_fabric_;
    return PeInternalPodShadowGate::enabled(cfg, bindings);
}

bool WeightMemorySubsystem::pulseOsaMetadataTxnEnabledForKind_(
    PodMetadataObjectPlane::MetadataKind kind) const {
    if (!orch_.pulse_osa_metadata_txn_enable) return false;
    const uint32_t bit = pulseMetadataKindMaskBit_(kind);
    if (bit == 0u) return false;
    return (orch_.pulse_osa_metadata_object_mask & bit) != 0u;
}

bool WeightMemorySubsystem::pulseMetadataFrontierTrackedKind_(
    PodMetadataObjectPlane::MetadataKind kind) const {
    switch (kind) {
        case PodMetadataObjectPlane::MetadataKind::PreMphfBase:
        case PodMetadataObjectPlane::MetadataKind::PreMphfBand:
        case PodMetadataObjectPlane::MetadataKind::Idx2Row:
        case PodMetadataObjectPlane::MetadataKind::RowIndex:
            return true;
        default:
            return false;
    }
}

bool WeightMemorySubsystem::pulseMetadataFrontierObserveEligible_(
    PodMetadataObjectPlane::MetadataKind kind) const {
    if (!orch_.pulse_metadata_frontier_observe_enable) return false;
    if (window_seq_ == 0u) return false;
    if (!pulseMetadataFrontierTrackedKind_(kind)) return false;

    const uint32_t bit = pulseMetadataKindMaskBit_(kind);
    if (bit == 0u) return false;
    if (orch_.pulse_osa_metadata_object_mask == 0u) return true;
    return (orch_.pulse_osa_metadata_object_mask & bit) != 0u;
}

void WeightMemorySubsystem::notePulseMetadataFrontierObserved_(
    PodMetadataObjectPlane::MetadataKind kind,
    uint64_t object_key) {
    if (!pulseMetadataFrontierTrackedKind_(kind) || window_seq_ == 0u) return;

    if (pulse_metadata_frontier_seen_window_seq_ != window_seq_) {
        pulse_metadata_frontier_seen_window_seq_ = window_seq_;
        pulse_metadata_frontier_seen_keys_.clear();
    }

    const bool first_observe =
        pulse_metadata_frontier_seen_keys_.insert(object_key).second;
    if (first_observe) {
        pulse_metadata_frontier_observed_total_ += 1u;
    } else {
        pulse_metadata_frontier_same_window_reobserve_total_ += 1u;
    }

    switch (kind) {
        case PodMetadataObjectPlane::MetadataKind::PreMphfBase:
            if (first_observe) {
                pulse_metadata_frontier_premphf_base_observed_total_ += 1u;
            } else {
                pulse_metadata_frontier_premphf_base_same_window_reobserve_total_ += 1u;
            }
            break;
        case PodMetadataObjectPlane::MetadataKind::PreMphfBand:
            if (first_observe) {
                pulse_metadata_frontier_premphf_band_observed_total_ += 1u;
            } else {
                pulse_metadata_frontier_premphf_band_same_window_reobserve_total_ += 1u;
            }
            break;
        case PodMetadataObjectPlane::MetadataKind::Idx2Row:
            if (first_observe) {
                pulse_metadata_frontier_idx2row_observed_total_ += 1u;
            } else {
                pulse_metadata_frontier_idx2row_same_window_reobserve_total_ += 1u;
            }
            break;
        case PodMetadataObjectPlane::MetadataKind::RowIndex:
            if (first_observe) {
                pulse_metadata_frontier_rowindex_observed_total_ += 1u;
            } else {
                pulse_metadata_frontier_rowindex_same_window_reobserve_total_ += 1u;
            }
            break;
        default:
            break;
    }

    if (kind == PodMetadataObjectPlane::MetadataKind::PreMphfBase ||
        kind == PodMetadataObjectPlane::MetadataKind::PreMphfBand) {
        const auto reg_kind =
            (kind == PodMetadataObjectPlane::MetadataKind::PreMphfBase)
                ? PulseMetadataFrontierObserveRegistry::MetadataKind::PreMphfBase
                : PulseMetadataFrontierObserveRegistry::MetadataKind::PreMphfBand;
        const uint64_t object_id = object_key & 0x00ffffffffffffffull;
        (void)PulseMetadataFrontierObserveRegistry::observeObject(
            orch_.node_id,
            window_seq_,
            reg_kind,
            object_id,
            orch_.core_id);
    }
}

void WeightMemorySubsystem::notePulseMetadataFrontierOwnerFormCandidate_(
    PodMetadataObjectPlane::MetadataKind kind) {
    if (!pulseMetadataFrontierTrackedKind_(kind)) return;
    pulse_metadata_frontier_owner_form_candidate_total_ += 1u;
    switch (kind) {
        case PodMetadataObjectPlane::MetadataKind::PreMphfBase:
            pulse_metadata_frontier_premphf_base_owner_form_candidate_total_ += 1u;
            break;
        case PodMetadataObjectPlane::MetadataKind::PreMphfBand:
            pulse_metadata_frontier_premphf_band_owner_form_candidate_total_ += 1u;
            break;
        case PodMetadataObjectPlane::MetadataKind::Idx2Row:
            pulse_metadata_frontier_idx2row_owner_form_candidate_total_ += 1u;
            break;
        case PodMetadataObjectPlane::MetadataKind::RowIndex:
            pulse_metadata_frontier_rowindex_owner_form_candidate_total_ += 1u;
            break;
        default:
            break;
    }
}

void WeightMemorySubsystem::notePulseMetadataFrontierJoinReadyCandidate_(
    PodMetadataObjectPlane::MetadataKind kind) {
    if (!pulseMetadataFrontierTrackedKind_(kind)) return;
    pulse_metadata_frontier_join_ready_candidate_total_ += 1u;
    switch (kind) {
        case PodMetadataObjectPlane::MetadataKind::PreMphfBase:
            pulse_metadata_frontier_premphf_base_join_ready_candidate_total_ += 1u;
            break;
        case PodMetadataObjectPlane::MetadataKind::PreMphfBand:
            pulse_metadata_frontier_premphf_band_join_ready_candidate_total_ += 1u;
            break;
        case PodMetadataObjectPlane::MetadataKind::Idx2Row:
            pulse_metadata_frontier_idx2row_join_ready_candidate_total_ += 1u;
            break;
        case PodMetadataObjectPlane::MetadataKind::RowIndex:
            pulse_metadata_frontier_rowindex_join_ready_candidate_total_ += 1u;
            break;
        default:
            break;
    }
}

void WeightMemorySubsystem::notePulseOsaMetadataTxnEnvelope_(
    PodMetadataObjectPlane::MetadataKind kind,
    uint64_t envelope_size) {
    if (!pulseOsaMetadataTxnEnabledForKind_(kind)) return;
    pulse_osa_metadata_txn_envelope_size_sum_total_ += envelope_size;
}

void WeightMemorySubsystem::observePeInternalPodMetadataObject_(
    PodMetadataObjectPlane::MetadataKind kind,
    uint64_t object_id,
    bool experimental_rowindex_owner_track) {
    const uint64_t object_key =
        PodMetadataObjectPlane::composeObjectKey(kind, object_id);
    const bool pulse_frontier_track =
        pulseMetadataFrontierObserveEligible_(kind);
    if (pulse_frontier_track) {
        notePulseMetadataFrontierObserved_(kind, object_key);
    }

    PeInternalPodShadowGateConfig cfg{};
    cfg.pe_internal_cpe_enable = orch_.pe_internal_cpe_enable;
    cfg.pe_internal_pod_enable = orch_.pe_internal_pod_enable;
    cfg.pe_internal_pod_metadata_enable = orch_.pe_internal_pod_metadata_enable;
    cfg.pe_internal_pod_owner_enable = orch_.pe_internal_pod_owner_enable;
    cfg.core_id = orch_.core_id;
    cfg.pod_id = orch_.pe_internal_pod_id;
    cfg.pod_count = orch_.pe_internal_pod_count;
    cfg.window_seq = window_seq_;

    PeInternalPodShadowGateBindings bindings{};
    bindings.metadata_plane = pod_metadata_object_plane_;
    bindings.owner_table = pod_owner_service_table_;
    bindings.fabric = pe_shared_core_fabric_;

    PeInternalPodShadowGateCounters counters{};
    counters.guard_drop_total = pe_internal_pod_guard_drop_total_;
    counters.guard_disabled_total = pe_internal_pod_guard_disabled_total_;
    counters.guard_missing_metadata_plane_total =
        pe_internal_pod_guard_missing_metadata_plane_total_;
    counters.guard_missing_owner_table_total =
        pe_internal_pod_guard_missing_owner_table_total_;
    counters.guard_zero_pod_count_total =
        pe_internal_pod_guard_zero_pod_count_total_;
    counters.guard_window_zero_total =
        pe_internal_pod_guard_window_zero_total_;
    counters.guard_invalid_cfg_pod_total =
        pe_internal_pod_guard_invalid_cfg_pod_total_;
    counters.guard_rowdescriptor_disabled_total =
        pe_internal_pod_guard_rowdescriptor_disabled_total_;
    counters.guard_rowdescriptor_missing_metadata_plane_total =
        pe_internal_pod_guard_rowdescriptor_missing_metadata_plane_total_;
    counters.guard_rowdescriptor_missing_owner_table_total =
        pe_internal_pod_guard_rowdescriptor_missing_owner_table_total_;
    counters.guard_rowdescriptor_zero_pod_count_total =
        pe_internal_pod_guard_rowdescriptor_zero_pod_count_total_;
    counters.guard_rowdescriptor_window_zero_total =
        pe_internal_pod_guard_rowdescriptor_window_zero_total_;
    counters.guard_rowdescriptor_invalid_cfg_pod_total =
        pe_internal_pod_guard_rowdescriptor_invalid_cfg_pod_total_;
    counters.guard_base_total = pe_internal_pod_guard_base_total_;
    counters.guard_band_total = pe_internal_pod_guard_band_total_;
    counters.guard_other_total = pe_internal_pod_guard_other_total_;
    counters.guard_idx2row_total = pe_internal_pod_guard_idx2row_total_;
    counters.guard_rowindex_total = pe_internal_pod_guard_rowindex_total_;
    counters.guard_rowdescriptor_total = pe_internal_pod_guard_rowdescriptor_total_;
    counters.frontier_export_total = pe_internal_pod_frontier_export_total_;
    counters.frontier_consumer_count_sum_total =
        pe_internal_pod_frontier_consumer_count_sum_total_;
    counters.frontier_overlap_strength_sum_total =
        pe_internal_pod_frontier_overlap_strength_sum_total_;
    counters.frontier_base_consumer_count_sum_total =
        pe_internal_pod_frontier_base_consumer_count_sum_total_;
    counters.frontier_base_overlap_strength_sum_total =
        pe_internal_pod_frontier_base_overlap_strength_sum_total_;
    counters.frontier_band_consumer_count_sum_total =
        pe_internal_pod_frontier_band_consumer_count_sum_total_;
    counters.frontier_band_overlap_strength_sum_total =
        pe_internal_pod_frontier_band_overlap_strength_sum_total_;
    counters.owner_lookup_total = pe_internal_pod_owner_lookup_total_;
    counters.owner_alloc_total = pe_internal_pod_owner_alloc_total_;
    counters.owner_alloc_idx2row_total =
        pe_internal_pod_owner_alloc_idx2row_total_;
    counters.owner_alloc_rowindex_total =
        pe_internal_pod_owner_alloc_rowindex_total_;
    counters.owner_alloc_rowdescriptor_total =
        pe_internal_pod_owner_alloc_rowdescriptor_total_;
    counters.owner_hit_total = pe_internal_pod_owner_hit_total_;
    counters.owner_hit_idx2row_total = pe_internal_pod_owner_hit_idx2row_total_;
    counters.owner_hit_rowindex_total =
        pe_internal_pod_owner_hit_rowindex_total_;
    counters.owner_hit_rowdescriptor_total =
        pe_internal_pod_owner_hit_rowdescriptor_total_;
    counters.owner_reject_total = pe_internal_pod_owner_reject_total_;
    counters.owner_disabled_reject_total =
        pe_internal_pod_owner_disabled_reject_total_;
    counters.owner_invalid_pod_reject_total =
        pe_internal_pod_owner_invalid_pod_reject_total_;
    counters.owner_table_full_reject_total =
        pe_internal_pod_owner_table_full_reject_total_;
    counters.join_request_total = pe_internal_pod_join_request_total_;
    counters.join_grant_total = pe_internal_pod_join_grant_total_;
    counters.join_reject_total = pe_internal_pod_join_reject_total_;
    counters.join_table_disabled_reject_total =
        pe_internal_pod_join_table_disabled_reject_total_;
    counters.join_duplicate_consumer_reject_total =
        pe_internal_pod_join_duplicate_consumer_reject_total_;
    counters.join_table_full_reject_total =
        pe_internal_pod_join_table_full_reject_total_;
    counters.join_before_private_issue_total =
        pe_internal_pod_join_before_private_issue_total_;
    counters.owner_first_issue_deferred_total =
        pe_internal_pod_owner_first_issue_deferred_total_;
    counters.owner_first_issue_deferred_idx2row_total =
        pe_internal_pod_owner_first_issue_deferred_idx2row_total_;
    counters.owner_first_issue_deferred_rowindex_total =
        pe_internal_pod_owner_first_issue_deferred_rowindex_total_;
    counters.owner_first_issue_deferred_rowdescriptor_total =
        pe_internal_pod_owner_first_issue_deferred_rowdescriptor_total_;
    counters.owner_first_private_issue_avoided_total =
        pe_internal_pod_owner_first_private_issue_avoided_total_;
    counters.owner_first_private_issue_avoided_idx2row_total =
        pe_internal_pod_owner_first_private_issue_avoided_idx2row_total_;
    counters.owner_first_private_issue_avoided_rowindex_total =
        pe_internal_pod_owner_first_private_issue_avoided_rowindex_total_;
    counters.owner_first_private_issue_avoided_rowdescriptor_total =
        pe_internal_pod_owner_first_private_issue_avoided_rowdescriptor_total_;
    counters.reject_base_total = pe_internal_pod_reject_base_total_;
    counters.reject_band_total = pe_internal_pod_reject_band_total_;
    counters.reject_other_total = pe_internal_pod_reject_other_total_;
    counters.reject_idx2row_total = pe_internal_pod_reject_idx2row_total_;
    counters.reject_rowindex_total = pe_internal_pod_reject_rowindex_total_;
    counters.reject_rowdescriptor_total = pe_internal_pod_reject_rowdescriptor_total_;
    counters.useful_total = pe_internal_pod_useful_total_;
    counters.useful_join_grant_total =
        pe_internal_pod_useful_join_grant_total_;
    counters.useful_duplicate_replay_elide_total =
        pe_internal_pod_useful_duplicate_replay_elide_total_;
    counters.useful_base_total = pe_internal_pod_useful_base_total_;
    counters.useful_band_total = pe_internal_pod_useful_band_total_;
    counters.useful_other_total = pe_internal_pod_useful_other_total_;
    counters.useful_idx2row_total = pe_internal_pod_useful_idx2row_total_;
    counters.useful_rowindex_total = pe_internal_pod_useful_rowindex_total_;
    counters.useful_rowdescriptor_total = pe_internal_pod_useful_rowdescriptor_total_;
    counters.duplicate_metadata_replay_elided_total =
        pe_internal_pod_duplicate_metadata_replay_elided_total_;
    counters.duplicate_metadata_issue_elided_total =
        pe_internal_pod_duplicate_metadata_issue_elided_total_;
    counters.fallback_private_issue_total =
        pe_internal_pod_fallback_private_issue_total_;

    const uint64_t prev_owner_alloc_total = counters.owner_alloc_total;
    const uint64_t prev_join_grant_total = counters.join_grant_total;

    PeInternalPodShadowGate::observe(cfg, bindings, kind, object_id, counters);

    if (pulseOsaMetadataTxnEnabledForKind_(kind)) {
        pulse_osa_metadata_txn_export_total_ += 1u;
        notePulseOsaMetadataTxnEnvelope_(kind, 1u);
    }
    if (pulse_frontier_track &&
        counters.owner_alloc_total > prev_owner_alloc_total) {
        notePulseMetadataFrontierOwnerFormCandidate_(kind);
    }

    if (pe_local_service_object_table_ != nullptr &&
        pe_local_service_object_table_->enabled()) {
        const auto note_kind_counter =
            [&](uint64_t& idx2row_counter,
                uint64_t& rowindex_counter,
                uint64_t& rowdescriptor_counter) {
                switch (kind) {
                    case PodMetadataObjectPlane::MetadataKind::Idx2Row:
                        idx2row_counter += 1u;
                        break;
                    case PodMetadataObjectPlane::MetadataKind::RowIndex:
                        rowindex_counter += 1u;
                        break;
                    case PodMetadataObjectPlane::MetadataKind::RowDescriptor:
                        rowdescriptor_counter += 1u;
                        break;
                    default:
                        break;
                }
            };

        if (counters.owner_alloc_total > prev_owner_alloc_total) {
            PeLocalServiceObjectTable::OwnerRequest owner{};
            owner.pod_id = orch_.pe_internal_pod_id;
            owner.window_seq = window_seq_;
            owner.object_key = object_key;
            owner.owner_core_id = orch_.core_id;
            (void)pe_local_service_object_table_->noteOwnerForm(owner);
            if (kind == PodMetadataObjectPlane::MetadataKind::RowIndex &&
                experimental_rowindex_owner_track) {
                noteExperimentalNocRowidxOwnerCloseCandidate_(
                    static_cast<uint32_t>(object_id));
            }
            if (pulseOsaMetadataTxnEnabledForKind_(kind)) {
                pulse_osa_metadata_txn_owner_launch_total_ += 1u;
            }
        }

        if (counters.join_grant_total > prev_join_grant_total) {
            PeLocalServiceObjectTable::JoinRequest join{};
            join.pod_id = orch_.pe_internal_pod_id;
            join.window_seq = window_seq_;
            join.object_key = object_key;
            join.consumer_core_id = orch_.core_id;
            const auto join_result = pe_local_service_object_table_->join(join);
            if (join_result.joined_live) {
                pe_internal_pod_service_join_live_total_ += 1u;
                if (pulseOsaMetadataTxnEnabledForKind_(kind)) {
                    pulse_osa_metadata_txn_join_live_total_ += 1u;
                }
                note_kind_counter(
                    pe_internal_pod_service_join_live_idx2row_total_,
                    pe_internal_pod_service_join_live_rowindex_total_,
                    pe_internal_pod_service_join_live_rowdescriptor_total_);
            }
            if (join_result.joined_ready) {
                pe_internal_pod_service_join_ready_total_ += 1u;
                if (pulseOsaMetadataTxnEnabledForKind_(kind)) {
                    pulse_osa_metadata_txn_join_ready_total_ += 1u;
                    if (join_result.ready_lease_hit) {
                        pulse_osa_metadata_txn_ready_lease_hit_total_ += 1u;
                    }
                }
                note_kind_counter(
                    pe_internal_pod_service_join_ready_idx2row_total_,
                    pe_internal_pod_service_join_ready_rowindex_total_,
                    pe_internal_pod_service_join_ready_rowdescriptor_total_);
                if (pulse_frontier_track) {
                    notePulseMetadataFrontierJoinReadyCandidate_(kind);
                }
            }
            if (join_result.late_join) {
                pe_internal_pod_service_late_join_total_ += 1u;
                if (pulseOsaMetadataTxnEnabledForKind_(kind)) {
                    pulse_osa_metadata_txn_late_join_total_ += 1u;
                    if (join_result.ready_lease_expired) {
                        pulse_osa_metadata_txn_ready_lease_expired_total_ += 1u;
                    }
                }
                note_kind_counter(
                    pe_internal_pod_service_late_join_idx2row_total_,
                    pe_internal_pod_service_late_join_rowindex_total_,
                    pe_internal_pod_service_late_join_rowdescriptor_total_);
            }
            if (join_result.joined_live || join_result.joined_ready) {
                pe_internal_pod_service_potential_private_service_elide_total_ += 1u;
                note_kind_counter(
                    pe_internal_pod_service_potential_private_service_elide_idx2row_total_,
                    pe_internal_pod_service_potential_private_service_elide_rowindex_total_,
                    pe_internal_pod_service_potential_private_service_elide_rowdescriptor_total_);
                pe_internal_pod_owner_first_service_elide_total_ += 1u;
                note_kind_counter(
                    pe_internal_pod_owner_first_service_elide_idx2row_total_,
                    pe_internal_pod_owner_first_service_elide_rowindex_total_,
                    pe_internal_pod_owner_first_service_elide_rowdescriptor_total_);
                if (kind == PodMetadataObjectPlane::MetadataKind::RowDescriptor) {
                    if (join_result.joined_live) {
                        pulse_rowdescriptor_owner_first_service_elide_join_live_total_ += 1u;
                    }
                    if (join_result.joined_ready) {
                        pulse_rowdescriptor_owner_first_service_elide_join_ready_total_ += 1u;
                    }
                }
            }
        }
    }

    pe_internal_pod_guard_drop_total_ = counters.guard_drop_total;
    pe_internal_pod_guard_disabled_total_ = counters.guard_disabled_total;
    pe_internal_pod_guard_missing_metadata_plane_total_ =
        counters.guard_missing_metadata_plane_total;
    pe_internal_pod_guard_missing_owner_table_total_ =
        counters.guard_missing_owner_table_total;
    pe_internal_pod_guard_zero_pod_count_total_ =
        counters.guard_zero_pod_count_total;
    pe_internal_pod_guard_window_zero_total_ =
        counters.guard_window_zero_total;
    pe_internal_pod_guard_invalid_cfg_pod_total_ =
        counters.guard_invalid_cfg_pod_total;
    pe_internal_pod_guard_rowdescriptor_disabled_total_ =
        counters.guard_rowdescriptor_disabled_total;
    pe_internal_pod_guard_rowdescriptor_missing_metadata_plane_total_ =
        counters.guard_rowdescriptor_missing_metadata_plane_total;
    pe_internal_pod_guard_rowdescriptor_missing_owner_table_total_ =
        counters.guard_rowdescriptor_missing_owner_table_total;
    pe_internal_pod_guard_rowdescriptor_zero_pod_count_total_ =
        counters.guard_rowdescriptor_zero_pod_count_total;
    pe_internal_pod_guard_rowdescriptor_window_zero_total_ =
        counters.guard_rowdescriptor_window_zero_total;
    pe_internal_pod_guard_rowdescriptor_invalid_cfg_pod_total_ =
        counters.guard_rowdescriptor_invalid_cfg_pod_total;
    pe_internal_pod_guard_base_total_ = counters.guard_base_total;
    pe_internal_pod_guard_band_total_ = counters.guard_band_total;
    pe_internal_pod_guard_other_total_ = counters.guard_other_total;
    pe_internal_pod_guard_idx2row_total_ = counters.guard_idx2row_total;
    pe_internal_pod_guard_rowindex_total_ = counters.guard_rowindex_total;
    pe_internal_pod_guard_rowdescriptor_total_ = counters.guard_rowdescriptor_total;
    pe_internal_pod_frontier_export_total_ = counters.frontier_export_total;
    pe_internal_pod_frontier_consumer_count_sum_total_ =
        counters.frontier_consumer_count_sum_total;
    pe_internal_pod_frontier_overlap_strength_sum_total_ =
        counters.frontier_overlap_strength_sum_total;
    pe_internal_pod_frontier_base_consumer_count_sum_total_ =
        counters.frontier_base_consumer_count_sum_total;
    pe_internal_pod_frontier_base_overlap_strength_sum_total_ =
        counters.frontier_base_overlap_strength_sum_total;
    pe_internal_pod_frontier_band_consumer_count_sum_total_ =
        counters.frontier_band_consumer_count_sum_total;
    pe_internal_pod_frontier_band_overlap_strength_sum_total_ =
        counters.frontier_band_overlap_strength_sum_total;
    pe_internal_pod_owner_lookup_total_ = counters.owner_lookup_total;
    pe_internal_pod_owner_alloc_total_ = counters.owner_alloc_total;
    pe_internal_pod_owner_alloc_idx2row_total_ =
        counters.owner_alloc_idx2row_total;
    pe_internal_pod_owner_alloc_rowindex_total_ =
        counters.owner_alloc_rowindex_total;
    pe_internal_pod_owner_alloc_rowdescriptor_total_ =
        counters.owner_alloc_rowdescriptor_total;
    pe_internal_pod_owner_hit_total_ = counters.owner_hit_total;
    pe_internal_pod_owner_hit_idx2row_total_ =
        counters.owner_hit_idx2row_total;
    pe_internal_pod_owner_hit_rowindex_total_ =
        counters.owner_hit_rowindex_total;
    pe_internal_pod_owner_hit_rowdescriptor_total_ =
        counters.owner_hit_rowdescriptor_total;
    pe_internal_pod_owner_reject_total_ = counters.owner_reject_total;
    pe_internal_pod_owner_disabled_reject_total_ =
        counters.owner_disabled_reject_total;
    pe_internal_pod_owner_invalid_pod_reject_total_ =
        counters.owner_invalid_pod_reject_total;
    pe_internal_pod_owner_table_full_reject_total_ =
        counters.owner_table_full_reject_total;
    pe_internal_pod_join_request_total_ = counters.join_request_total;
    pe_internal_pod_join_grant_total_ = counters.join_grant_total;
    pe_internal_pod_join_reject_total_ = counters.join_reject_total;
    pe_internal_pod_join_table_disabled_reject_total_ =
        counters.join_table_disabled_reject_total;
    pe_internal_pod_join_duplicate_consumer_reject_total_ =
        counters.join_duplicate_consumer_reject_total;
    pe_internal_pod_join_table_full_reject_total_ =
        counters.join_table_full_reject_total;
    pe_internal_pod_join_before_private_issue_total_ =
        counters.join_before_private_issue_total;
    pe_internal_pod_owner_first_issue_deferred_total_ =
        counters.owner_first_issue_deferred_total;
    pe_internal_pod_owner_first_issue_deferred_idx2row_total_ =
        counters.owner_first_issue_deferred_idx2row_total;
    pe_internal_pod_owner_first_issue_deferred_rowindex_total_ =
        counters.owner_first_issue_deferred_rowindex_total;
    pe_internal_pod_owner_first_issue_deferred_rowdescriptor_total_ =
        counters.owner_first_issue_deferred_rowdescriptor_total;
    pe_internal_pod_owner_first_private_issue_avoided_total_ =
        counters.owner_first_private_issue_avoided_total;
    pe_internal_pod_owner_first_private_issue_avoided_idx2row_total_ =
        counters.owner_first_private_issue_avoided_idx2row_total;
    pe_internal_pod_owner_first_private_issue_avoided_rowindex_total_ =
        counters.owner_first_private_issue_avoided_rowindex_total;
    pe_internal_pod_owner_first_private_issue_avoided_rowdescriptor_total_ =
        counters.owner_first_private_issue_avoided_rowdescriptor_total;
    pe_internal_pod_reject_base_total_ = counters.reject_base_total;
    pe_internal_pod_reject_band_total_ = counters.reject_band_total;
    pe_internal_pod_reject_other_total_ = counters.reject_other_total;
    pe_internal_pod_reject_idx2row_total_ = counters.reject_idx2row_total;
    pe_internal_pod_reject_rowindex_total_ = counters.reject_rowindex_total;
    pe_internal_pod_reject_rowdescriptor_total_ = counters.reject_rowdescriptor_total;
    pe_internal_pod_useful_total_ = counters.useful_total;
    pe_internal_pod_useful_join_grant_total_ =
        counters.useful_join_grant_total;
    pe_internal_pod_useful_duplicate_replay_elide_total_ =
        counters.useful_duplicate_replay_elide_total;
    pe_internal_pod_useful_base_total_ = counters.useful_base_total;
    pe_internal_pod_useful_band_total_ = counters.useful_band_total;
    pe_internal_pod_useful_other_total_ = counters.useful_other_total;
    pe_internal_pod_useful_idx2row_total_ = counters.useful_idx2row_total;
    pe_internal_pod_useful_rowindex_total_ = counters.useful_rowindex_total;
    pe_internal_pod_useful_rowdescriptor_total_ = counters.useful_rowdescriptor_total;
    pe_internal_pod_duplicate_metadata_replay_elided_total_ =
        counters.duplicate_metadata_replay_elided_total;
    pe_internal_pod_duplicate_metadata_issue_elided_total_ =
        counters.duplicate_metadata_issue_elided_total;
    pe_internal_pod_fallback_private_issue_total_ =
        counters.fallback_private_issue_total;
}

bool WeightMemorySubsystem::notePeInternalPodServiceObjectReady_(
    PodMetadataObjectPlane::MetadataKind kind,
    uint64_t object_id,
    uint32_t window_seq) {
    const uint32_t effective_window_seq = (window_seq != 0u) ? window_seq : window_seq_;
    if (effective_window_seq == 0u) return false;
    if (pe_local_service_object_table_ == nullptr ||
        !pe_local_service_object_table_->enabled()) {
        return false;
    }

    PeLocalServiceObjectTable::ReadyRequest ready{};
    ready.pod_id = orch_.pe_internal_pod_id;
    ready.window_seq = effective_window_seq;
    ready.object_key = PodMetadataObjectPlane::composeObjectKey(kind, object_id);
    const auto ready_result = pe_local_service_object_table_->markReady(ready);
    if (!ready_result.valid || !ready_result.transitioned) {
        return false;
    }

    pe_internal_pod_service_ready_transition_total_ += 1u;
    pe_internal_pod_service_ready_fanout_total_ += 1u;
    pe_internal_pod_service_ready_fanout_consumers_sum_total_ +=
        static_cast<uint64_t>(ready_result.consumer_count);

    switch (kind) {
        case PodMetadataObjectPlane::MetadataKind::Idx2Row:
            pe_internal_pod_service_ready_transition_idx2row_total_ += 1u;
            pe_internal_pod_service_ready_fanout_idx2row_total_ += 1u;
            pe_internal_pod_service_ready_fanout_consumers_sum_idx2row_total_ +=
                static_cast<uint64_t>(ready_result.consumer_count);
            break;
        case PodMetadataObjectPlane::MetadataKind::RowIndex:
            pe_internal_pod_service_ready_transition_rowindex_total_ += 1u;
            pe_internal_pod_service_ready_fanout_rowindex_total_ += 1u;
            pe_internal_pod_service_ready_fanout_consumers_sum_rowindex_total_ +=
                static_cast<uint64_t>(ready_result.consumer_count);
            break;
        case PodMetadataObjectPlane::MetadataKind::RowDescriptor:
            pe_internal_pod_service_ready_transition_rowdescriptor_total_ += 1u;
            pe_internal_pod_service_ready_fanout_rowdescriptor_total_ += 1u;
            pe_internal_pod_service_ready_fanout_consumers_sum_rowdescriptor_total_ +=
                static_cast<uint64_t>(ready_result.consumer_count);
            break;
        default:
            break;
    }

    if (pe_shared_core_fabric_ != nullptr) {
        PeSharedCoreFabric::ControlMessage message{};
        message.kind = PeSharedCoreFabric::ControlMessageKind::ReadyFanout;
        message.scope_id = orch_.pe_internal_pod_id;
        message.producer_core_id = orch_.core_id;
        message.owner_core_id = orch_.core_id;
        message.window_seq = effective_window_seq;
        message.object_key = ready.object_key;
        message.consumer_bitmap = ready_result.consumer_bitmap;
        message.ready_token = ready_result.ready_token;
        pe_shared_core_fabric_->enqueueControlMessage(message);
    }

    if (ready_result.released_after_transition) {
        pe_internal_pod_service_ready_release_total_ += 1u;
        switch (kind) {
            case PodMetadataObjectPlane::MetadataKind::Idx2Row:
                pe_internal_pod_service_ready_release_idx2row_total_ += 1u;
                pe_internal_pod_service_released_idx2row_total_ += 1u;
                break;
            case PodMetadataObjectPlane::MetadataKind::RowIndex:
                pe_internal_pod_service_ready_release_rowindex_total_ += 1u;
                pe_internal_pod_service_released_rowindex_total_ += 1u;
                break;
            case PodMetadataObjectPlane::MetadataKind::RowDescriptor:
                pe_internal_pod_service_ready_release_rowdescriptor_total_ += 1u;
                pe_internal_pod_service_released_rowdescriptor_total_ += 1u;
                break;
            default:
                break;
        }
    }

    return true;
}

void WeightMemorySubsystem::notePeInternalPodServiceObjectReleased_(
    PodMetadataObjectPlane::MetadataKind kind,
    uint64_t object_id,
    uint32_t window_seq,
    bool defer_until_ready) {
    const uint32_t effective_window_seq = (window_seq != 0u) ? window_seq : window_seq_;
    if (effective_window_seq == 0u) return;
    if (pe_local_service_object_table_ == nullptr ||
        !pe_local_service_object_table_->enabled()) {
        return;
    }

    PeLocalServiceObjectTable::ReleaseRequest release{};
    release.pod_id = orch_.pe_internal_pod_id;
    release.window_seq = effective_window_seq;
    release.object_key = PodMetadataObjectPlane::composeObjectKey(kind, object_id);
    release.defer_until_ready = defer_until_ready;
    const auto release_result = pe_local_service_object_table_->release(release);
    const bool released = release_result.valid && release_result.released;
    const bool deferred = release_result.valid && release_result.deferred;
    if (deferred) {
        pe_internal_pod_service_release_deferred_total_ += 1u;
    }
    switch (kind) {
        case PodMetadataObjectPlane::MetadataKind::Idx2Row:
            if (released) {
                pe_internal_pod_service_released_idx2row_total_ += 1u;
            } else if (deferred) {
                pe_internal_pod_service_release_deferred_idx2row_total_ += 1u;
            } else if (!deferred) {
                pe_internal_pod_service_release_missing_idx2row_total_ += 1u;
            }
            break;
        case PodMetadataObjectPlane::MetadataKind::RowIndex:
            if (released) {
                pe_internal_pod_service_released_rowindex_total_ += 1u;
            } else if (deferred) {
                pe_internal_pod_service_release_deferred_rowindex_total_ += 1u;
            } else if (!deferred) {
                pe_internal_pod_service_release_missing_rowindex_total_ += 1u;
            }
            break;
        case PodMetadataObjectPlane::MetadataKind::RowDescriptor:
            if (released) {
                pe_internal_pod_service_released_rowdescriptor_total_ += 1u;
            } else if (deferred) {
                pe_internal_pod_service_release_deferred_rowdescriptor_total_ += 1u;
            } else if (!deferred) {
                pe_internal_pod_service_release_missing_rowdescriptor_total_ += 1u;
            }
            break;
        default:
            break;
    }
    if (kind == PodMetadataObjectPlane::MetadataKind::RowDescriptor &&
        orch_.experimental_rowdescriptor_ready_join_dedup_enable &&
        !released) {
        pulse_rowdescriptor_ready_join_shortcut_release_missing_total_ += 1u;
    }
}

void WeightMemorySubsystem::noteExperimentalNocRowidxOwnerCloseCandidate_(uint32_t block_row) {
    if (!experimentalNocRowidxPrefetchEnabled_()) return;
    if (experimental_noc_rowidx_owner_close_seen_.empty()) return;
    if (block_row >= experimental_noc_rowidx_owner_close_seen_.size()) return;
    if (experimental_noc_rowidx_owner_close_seen_[block_row]) return;
    experimental_noc_rowidx_owner_close_seen_[block_row] = 1u;
    experimental_noc_rowidx_owner_close_rows_.push_back(block_row);
}

void WeightMemorySubsystem::maybeReleaseExperimentalNocRowidxServiceObjects_(uint32_t seq) {
    if (seq == 0u) return;
    if (!experimentalNocRowidxPrefetchEnabled_()) return;
    if (pe_local_service_object_table_ == nullptr ||
        !pe_local_service_object_table_->enabled()) {
        return;
    }

    while (!experimental_noc_rowidx_owner_close_rows_.empty()) {
        const uint32_t block_row = experimental_noc_rowidx_owner_close_rows_.front();
        experimental_noc_rowidx_owner_close_rows_.pop_front();
        experimental_noc_rowidx_stats_.close_attempt_total += 1u;

        PeLocalServiceObjectTable::ProbeRequest probe{};
        probe.pod_id = orch_.pe_internal_pod_id;
        probe.window_seq = seq;
        probe.object_key = PodMetadataObjectPlane::composeObjectKey(
            PodMetadataObjectPlane::MetadataKind::RowIndex,
            static_cast<uint64_t>(block_row));
        const auto probe_result = pe_local_service_object_table_->probe(probe);
        if (!probe_result.valid || !probe_result.active) {
            experimental_noc_rowidx_stats_.close_attempt_not_active_total += 1u;
            continue;
        }
        if (probe_result.owner_core_id != orch_.core_id) {
            experimental_noc_rowidx_stats_.close_attempt_not_owner_total += 1u;
            continue;
        }
        experimental_noc_rowidx_stats_.close_attempt_active_owner_total += 1u;
        if (probe_result.release_pending) {
            experimental_noc_rowidx_stats_.close_attempt_already_pending_total += 1u;
        }

        notePeInternalPodServiceObjectReleased_(
            PodMetadataObjectPlane::MetadataKind::RowIndex,
            static_cast<uint64_t>(block_row),
            seq,
            /*defer_until_ready=*/true);
    }
}

void WeightMemorySubsystem::notePulseSeedFirstDemand_(uint64_t line_addr,
                                                      bool ready_before_demand) {
    (void)ready_before_demand;
    const auto tracked = PulseSeededLineTracker::noteDemand(
        orch_.node_id,
        window_seq_,
        line_addr);
    (void)tracked;
}

void WeightMemorySubsystem::issuePulseSeededLine_(uint64_t line_addr,
                                                  PulseSeedSource source,
                                                  uint32_t selection_slot) {
    if (!pulseAnySeededResidencyEnable_() ||
        !orch_.pulse_descriptor_actual_enable ||
        window_seq_ == 0u ||
        !mem_access_) {
        return;
    }

    const uint64_t line_size = std::max<uint64_t>(
        static_cast<uint64_t>(sizeof(float)),
        static_cast<uint64_t>(orch_.line_size_bytes));
    if (line_size < sizeof(float)) return;
    line_addr = (line_addr / line_size) * line_size;

    const auto resident = PulseSeededLineResidency::lookupLine(
        orch_.node_id,
        window_seq_,
        line_addr);
    if (resident.hit) return;

    PulseSharedLineService::ServiceKey key{};
    key.scope_id = orch_.node_id;
    key.window_seq = window_seq_;
    key.line_addr = line_addr;
    const auto gather_quality_bucket =
        (source == PulseSeedSource::MfbGatherPreband &&
         selection_slot != std::numeric_limits<uint32_t>::max())
            ? pulseGatherQualityBucketForSelectionIndex_(static_cast<size_t>(selection_slot))
            : PulseGatherQualityBucket::Unknown;

    auto join = PulseSharedLineService::joinOrRegister(
        key,
        [scope_id = orch_.node_id, window_seq = window_seq_, line_addr, this](
            bool ok,
            uint64_t,
            const std::vector<uint8_t>& line_bytes) {
            if (!ok || line_bytes.empty()) return;
            const size_t active_entries = PulseSeededLineResidency::storeLine(
                scope_id,
                window_seq,
                line_addr,
                line_bytes);
            PulseSeededLineTracker::markReady(
                scope_id,
                window_seq,
                line_addr,
                now_cycle_);
            (void)active_entries;
        });
    pulse_region_service_entries_peak_ = std::max<uint64_t>(
        pulse_region_service_entries_peak_,
        static_cast<uint64_t>(join.active_entries));
    if (!join.owner) return;
    PulseSeededLineTracker::registerLine(
        orch_.node_id,
        window_seq_,
        line_addr,
        now_cycle_,
        static_cast<uint8_t>(source),
        static_cast<uint8_t>(gather_quality_bucket));

    PendingMeta meta{};
    meta.window_seq = window_seq_;
    meta.address = line_addr;
    meta.size = static_cast<size_t>(line_size);
    meta.orig_address = line_addr;
    meta.orig_size = static_cast<size_t>(line_size);
    meta.slice_offset = 0;
    meta.issue_cycle = now_cycle_;
    meta.pending_enqueue_cycle = std::numeric_limits<uint64_t>::max();
    meta.retire_seq = std::numeric_limits<size_t>::max();
    meta.bcsr_kind = 8;  // PULSE metadata-seeded shared-line prefetch
    meta.pulse_scope_id = orch_.node_id;
    meta.pulse_service_line_addr = line_addr;
    meta.has_single_cb = false;
    meta.is_weight = true;
    meta.count_weight_read = true;

    const bool count_budget = (window_seq_ != 0u);
    const IssueStatus st = tryIssueRead_(meta, /*count_budget*/count_budget, /*budget_reserved*/false);
    if (st == IssueStatus::Issued) return;
    if (st == IssueStatus::DeferredInflight || st == IssueStatus::DeferredBudget) {
        meta.pending_enqueue_cycle = now_cycle_;
        pending_direct_reads_.push_back(std::move(meta));
        return;
    }
    PulseSeededLineTracker::eraseLine(orch_.node_id, window_seq_, line_addr);
    (void)PulseSharedLineService::complete(key, false, line_addr, std::vector<uint8_t>{});
}

bool WeightMemorySubsystem::finalizePulseSharedWindowIfNeeded_(uint32_t seq) {
    if (seq == 0u) return false;

    const auto arrival = registerPulsePeSharedWindowArrival_(
        orch_.node_id,
        seq,
        orch_.core_id,
        std::max<uint32_t>(1u, orch_.total_cores),
        {});
    if (!arrival.final_arrival) {
        return false;
    }

    if (orch_.pulse_frontier_observe_enable) {
        PulseFrontierObserveRegistry::closeWindow(orch_.node_id, seq);
    }
    if (orch_.pulse_metadata_frontier_observe_enable) {
        PulseMetadataFrontierObserveRegistry::closeWindow(orch_.node_id, seq);
    }
    if (orch_.pulse_metadata_seed_enable) {
        PulseMetadataSeedRegistry::closeWindow(orch_.node_id, seq);
        PulseSeededLineResidency::closeWindow(orch_.node_id, seq);
        PulseSeededLineTracker::closeWindow(orch_.node_id, seq);
    }
    if (orch_.pulse_prebase_shared_lookup_enable &&
        !gcss_premphf_index_path_.empty()) {
        PulseMetadataLookupRegistry::closeWindow(pulsePrebaseLookupScopeId_(), seq);
    }
    return true;
}

bool WeightMemorySubsystem::shouldReplayDeferredRowdescriptorOwnerFormLine_(
    uint64_t line_addr) const {
    if (window_seq_ == 0u) return false;

    const uint64_t line_size = std::max<uint64_t>(
        static_cast<uint64_t>(sizeof(float)),
        static_cast<uint64_t>(orch_.line_size_bytes));
    if (line_size < sizeof(float)) return false;
    line_addr = (line_addr / line_size) * line_size;

    if (pulseAnySeededResidencyEnable_()) {
        const auto resident = PulseSeededLineResidency::probeLine(
            orch_.node_id,
            window_seq_,
            line_addr);
        if (resident.hit) {
            return false;
        }
    }

    PulseSharedLineService::ServiceKey key{};
    key.scope_id = orch_.node_id;
    key.window_seq = window_seq_;
    key.line_addr = line_addr;
    const auto live_service = PulseSharedLineService::probe(key);
    if (live_service.active) {
        return false;
    }

    return true;
}

void WeightMemorySubsystem::tryDrainDeferredRowdescriptorReadyJoinShortcut_() {
    if (pulse_rowdescriptor_ready_join_shortcut_deferred_live_.empty()) return;
    if (window_seq_ == 0u) return;
    if (pe_local_service_object_table_ == nullptr ||
        !pe_local_service_object_table_->enabled()) {
        return;
    }

    std::vector<PulseDeferredReadyJoinShortcutEntry> pending_entries;
    pending_entries.reserve(pulse_rowdescriptor_ready_join_shortcut_deferred_live_.size());

    for (const auto& entry : pulse_rowdescriptor_ready_join_shortcut_deferred_live_) {
        PeLocalServiceObjectTable::ProbeRequest probe{};
        probe.pod_id = orch_.pe_internal_pod_id;
        probe.window_seq = window_seq_;
        probe.object_key = PodMetadataObjectPlane::composeObjectKey(
            PodMetadataObjectPlane::MetadataKind::RowDescriptor,
            entry.band_id);
        const auto probe_result = pe_local_service_object_table_->probe(probe);
        if (!probe_result.valid || (!probe_result.ready && !probe_result.released)) {
            pending_entries.push_back(entry);
            continue;
        }

        pulse_rowdescriptor_ready_join_shortcut_taken_total_ += 1u;
        pulse_rowdescriptor_ready_join_shortcut_deferred_live_apply_total_ += 1u;
        pulse_rowdescriptor_ready_join_shortcut_apply_complete_total_ += 1u;
        pulse_rowdescriptor_ready_join_shortcut_release_deferred_total_ += 1u;
        pulse_rowdescriptor_ready_join_shortcut_release_forwarded_total_ += 1u;
        pulse_rowdescriptor_ready_join_descriptor_elide_total_ += 1u;
        pulse_rowdescriptor_ready_join_lines_elide_total_ +=
            static_cast<uint64_t>(entry.selected_line_count);
    }

    pulse_rowdescriptor_ready_join_shortcut_deferred_live_.swap(pending_entries);
}

void WeightMemorySubsystem::tryActivateDeferredRowdescriptorOwnerFormReplay_() {
    if (pulse_rowdescriptor_owner_form_deferred_replays_.empty()) return;
    if (window_seq_ == 0u) return;

    std::vector<PulseDeferredOwnerFormReplayEntry> pending_entries;
    pending_entries.reserve(pulse_rowdescriptor_owner_form_deferred_replays_.size());

    for (const auto& entry : pulse_rowdescriptor_owner_form_deferred_replays_) {
        const auto probe = PulseMetadataSeedRegistry::probeGatherBand(
            orch_.node_id,
            window_seq_,
            entry.band_id);
        if (!probe.valid || !probe.seed_triggered) {
            pending_entries.push_back(entry);
            continue;
        }

        const auto& selected_line_addrs =
            !probe.selected_line_addrs.empty()
                ? probe.selected_line_addrs
                : entry.selected_line_addrs;
        if (selected_line_addrs.empty()) {
            continue;
        }

        std::vector<std::pair<uint64_t, uint32_t>> replay_lines;
        replay_lines.reserve(selected_line_addrs.size());
        for (size_t line_idx = 0; line_idx < selected_line_addrs.size(); ++line_idx) {
            const uint64_t line_addr = selected_line_addrs[line_idx];
            if (!shouldReplayDeferredRowdescriptorOwnerFormLine_(line_addr)) {
                continue;
            }
            replay_lines.push_back(std::make_pair(
                line_addr,
                static_cast<uint32_t>(line_idx)));
        }
        if (replay_lines.empty()) {
            continue;
        }

        pulse_rowdescriptor_owner_form_deferred_activate_total_ += 1u;
        for (const auto& replay_line : replay_lines) {
            issuePulseSeededLine_(
                replay_line.first,
                PulseSeedSource::MfbGatherPreband,
                replay_line.second);
        }
    }

    pulse_rowdescriptor_owner_form_deferred_replays_.swap(pending_entries);
}

void WeightMemorySubsystem::drainPendingPulseGatherPrebandReplay_() {
}

void WeightMemorySubsystem::maybeLaunchPulseMetadataSeeds_(
    const std::vector<GcssVlfEdgeIssueEntry>& ordered_edges) {
    (void)ordered_edges;
}

void WeightMemorySubsystem::maybeLaunchPulseMfbPrebandSeeds_(
    const std::vector<GcssVlfEdgeIssueEntry>& ordered_edges) {
    (void)ordered_edges;
}

void WeightMemorySubsystem::prepareGcssVlfIssueQueue_() {
    if (gcss_vlf_issue_queue_prepared_) return;
    gcss_vlf_issue_queue_prepared_ = true;
    gcss_vlf_issue_queue_.clear();
    if (!isGcssValueOnlyPreMphfMode_()) return;
    drainPendingPulseGatherPrebandReplay_();

    std::vector<GcssVlfEdgeIssueEntry> edges;
    edges.reserve(edgesPrevSize());
    const uint64_t line_size = std::max<uint64_t>(1u, static_cast<uint64_t>(orch_.line_size_bytes));
    while (true) {
        uint64_t key = 0;
        uint32_t count = 0;
        if (!nextPrevEdge(key, count)) break;

        const uint32_t post_local = static_cast<uint32_t>(key >> 32);
        const uint32_t pre_global = static_cast<uint32_t>(key & 0xffffffffu);
        if (orch_.num_neurons > 0 && post_local >= orch_.num_neurons) continue;

        const size_t seq = registerEdgeRetire_(post_local, pre_global, count, EdgeSrc::GCSS);
        auto rank_it = edge_pre_rank_prev_.find(key);
        if (rank_it == edge_pre_rank_prev_.end()) {
            SST::Output* out = diagOutOrFallback_();
            out->fatal(CALL_INFO, -1,
                       "WeightMemorySubsystem fatal: GCSS-VLF missing pre_rank (mode=%s node=%u core=%u pre=%u post=%u)\n",
                       orch_.synapse_weight_mode.c_str(),
                       orch_.node_id,
                       orch_.core_id,
                       pre_global,
                       post_local);
            return;
        }

        uint32_t base = 0;
        uint32_t len = 0;
        if (!lookupGcssPreBaseLen_(pre_global, base, len)) {
            setEdgeRetireReady_(seq, 0.0f, EdgeSrc::Dense);
            tryRetireEdges_();
            continue;
        }

        const uint32_t pre_rank = rank_it->second;
        if (pre_rank >= len) {
            SST::Output* out = diagOutOrFallback_();
            out->fatal(CALL_INFO, -1,
                       "WeightMemorySubsystem fatal: GCSS-VLF rank overflow (mode=%s node=%u core=%u pre=%u post=%u pre_rank=%u len=%u)\n",
                       orch_.synapse_weight_mode.c_str(),
                       orch_.node_id,
                       orch_.core_id,
                       pre_global,
                       post_local,
                       pre_rank,
                       len);
            return;
        }

        const uint64_t widx = static_cast<uint64_t>(base) + static_cast<uint64_t>(pre_rank);
        const uint64_t addr = gcssValuesBaseAddr_() + widx * sizeof(float);
        GcssVlfEdgeIssueEntry e{};
        e.retire_seq = seq;
        e.local_age_rank = edges.size();
        e.post_local = post_local;
        e.pre_global = pre_global;
        e.pre_rank = pre_rank;
        e.pre_base = base;
        e.pre_len = len;
        e.count = count;
        e.addr = addr;
        edges.push_back(e);
    }

    if (edges.empty()) return;

    auto sort_by_addr = [](const GcssVlfEdgeIssueEntry& a, const GcssVlfEdgeIssueEntry& b) {
        if (a.addr != b.addr) return a.addr < b.addr;
        if (a.pre_global != b.pre_global) return a.pre_global < b.pre_global;
        if (a.post_local != b.post_local) return a.post_local < b.post_local;
        return a.retire_seq < b.retire_seq;
    };

    std::vector<GcssVlfEdgeIssueEntry> sorted = edges;
    std::stable_sort(sorted.begin(), sorted.end(), sort_by_addr);

    std::string queue_policy = orch_.experimental_gcss_vlf_queue_policy;
    std::transform(queue_policy.begin(), queue_policy.end(), queue_policy.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    if (queue_policy.empty()) queue_policy = "locality_first";

    std::vector<GcssVlfEdgeIssueEntry> ordered = sorted;
    if (queue_policy == "banded_line_fair") {
        const size_t fair_band_size = std::max<size_t>(
            1u, static_cast<size_t>(orch_.experimental_gcss_vlf_fair_band_size));
        struct LineChunk {
            size_t age_band = 0;
            uint64_t line_id = 0;
            size_t chunk_min_retire_seq = 0;
            std::vector<GcssVlfEdgeIssueEntry> entries;
        };

        std::vector<LineChunk> line_chunks;
        line_chunks.reserve(sorted.size());
        for (const auto& e : sorted) {
            const uint64_t line_id = e.addr / line_size;
            const size_t age_band = e.local_age_rank / fair_band_size;
            if (line_chunks.empty() ||
                line_chunks.back().line_id != line_id ||
                line_chunks.back().age_band != age_band) {
                LineChunk chunk{};
                chunk.age_band = age_band;
                chunk.line_id = line_id;
                chunk.chunk_min_retire_seq = e.retire_seq;
                line_chunks.push_back(std::move(chunk));
            }
            line_chunks.back().chunk_min_retire_seq =
                std::min(line_chunks.back().chunk_min_retire_seq, e.retire_seq);
            line_chunks.back().entries.push_back(e);
        }

        std::stable_sort(line_chunks.begin(), line_chunks.end(),
                         [](const LineChunk& a, const LineChunk& b) {
                             if (a.age_band != b.age_band) return a.age_band < b.age_band;
                             if (a.line_id != b.line_id) return a.line_id < b.line_id;
                             if (a.chunk_min_retire_seq != b.chunk_min_retire_seq) {
                                 return a.chunk_min_retire_seq < b.chunk_min_retire_seq;
                             }
                             return a.entries.size() < b.entries.size();
                         });

        ordered.clear();
        ordered.reserve(sorted.size());
        for (const auto& chunk : line_chunks) {
            ordered.insert(ordered.end(), chunk.entries.begin(), chunk.entries.end());
        }
    }

    bool reordered = false;
    for (size_t i = 0; i < ordered.size(); ++i) {
        if (ordered[i].retire_seq != edges[i].retire_seq) {
            reordered = true;
            break;
        }
    }

    maybeExportOfflineLayoutProfile_(window_seq_, edges, ordered, line_size, queue_policy);
    observePulseFrontier_(ordered, line_size);
    observePulseMetadataFrontier_(ordered);
    maybeLaunchPulseMfbPrebandSeeds_(ordered);
    maybeLaunchPulseMetadataSeeds_(ordered);

    PulseAgendaScorer agenda_scorer{};
    auto score_line_group = [&](size_t group_size,
                                size_t group_min_retire_seq,
                                size_t group_max_retire_seq) {
        if (!orch_.pulse_agenda_enable || group_size == 0) return;

        const size_t retire_span =
            (group_max_retire_seq >= group_min_retire_seq)
                ? (group_max_retire_seq - group_min_retire_seq)
                : 0;
        PulseAgendaScorer::Candidate candidate{};
        candidate.same_line = true;
        candidate.row_safe = true;
        candidate.segment_safe = true;
        candidate.retire_span_ok = (retire_span <= 64u);
        candidate.head_pressure_ok = true;
        candidate.reuse_gain = static_cast<uint32_t>(std::min<size_t>(
            (group_size > 0) ? (group_size - 1) : 0,
            static_cast<size_t>(std::numeric_limits<uint32_t>::max())));
        candidate.residency_gain = static_cast<uint32_t>(std::min<size_t>(
            group_size,
            static_cast<size_t>(std::numeric_limits<uint32_t>::max())));
        candidate.ingress_relief = (group_size > 1) ? 1u : 0u;
        candidate.head_block_risk = static_cast<uint32_t>(std::min<size_t>(
            retire_span,
            static_cast<size_t>(std::numeric_limits<uint32_t>::max())));
        candidate.bank_conflict_risk = 0;
        candidate.split_risk = (group_size > 1) ? 0u : 1u;

        const auto result = agenda_scorer.evaluate(candidate);
        pulse_agenda_candidates_total_ += 1;
        if (result.accepted) {
            pulse_agenda_accepted_total_ += 1;
        } else {
            pulse_agenda_rejected_total_ += 1;
            if (result.reject_reason != PulseAgendaScorer::RejectReason::None) {
                pulse_agenda_reject_gate_total_ += 1;
            }
        }
    };

    uint64_t line_groups = 0;
    uint64_t last_line = std::numeric_limits<uint64_t>::max();
    size_t group_size = 0;
    size_t group_min_retire_seq = 0;
    size_t group_max_retire_seq = 0;
    for (const auto& e : ordered) {
        const uint64_t line = e.addr / line_size;
        if (line != last_line) {
            score_line_group(group_size, group_min_retire_seq, group_max_retire_seq);
            line_groups += 1;
            last_line = line;
            group_size = 0;
            group_min_retire_seq = e.retire_seq;
            group_max_retire_seq = e.retire_seq;
        }
        if (group_size == 0) {
            group_min_retire_seq = e.retire_seq;
            group_max_retire_seq = e.retire_seq;
        } else {
            group_min_retire_seq = std::min(group_min_retire_seq, e.retire_seq);
            group_max_retire_seq = std::max(group_max_retire_seq, e.retire_seq);
        }
        group_size += 1;
        gcss_vlf_issue_queue_.push_back(e);
    }
    score_line_group(group_size, group_min_retire_seq, group_max_retire_seq);
    gcss_vlf_issue_prepare_total_ += 1;
    gcss_vlf_issue_edges_total_ += static_cast<uint64_t>(ordered.size());
    if (reordered) gcss_vlf_issue_reorder_trigger_total_ += 1;
    gcss_vlf_issue_line_groups_total_ += line_groups;
    pulse_correctness_scoreboard_occupancy_peak_ = std::max<uint64_t>(
        pulse_correctness_scoreboard_occupancy_peak_,
        static_cast<uint64_t>(ordered.size()));
}

float WeightMemorySubsystem::applyWeightGuards_(float w) const {
    if (orch_.bcsr_weight_guard_enable) {
        if (!std::isfinite(w) || std::fabs(w) > orch_.bcsr_weight_abs_max) {
            return 0.0f;
        }
    }
    return applyReadRespZeroFallback_(w);
}

SST::Output* WeightMemorySubsystem::diagOutOrFallback_() const {
    static SST::Output fallback("WeightMemorySubsystem[@p:@l]: ", 0, 0, SST::Output::STDERR);
    return diag_out_ ? diag_out_ : &fallback;
}

void WeightMemorySubsystem::enqueueBcsrBlockReadCoalesced_(uint32_t win_seq,
                                                          uint32_t block_row,
                                                          uint32_t block_col,
                                                          uint32_t global_block_index,
                                                          uint32_t idx_in_row,
                                                          uint32_t intra_row,
                                                          uint32_t intra_col,
                                                          uint32_t pre_global,
                                                          uint32_t post_local,
                                                          std::function<void(float)> cb) {
    if (!orch_.use_bcsr || !orch_.bcsr_mgr || !mem_access_) {
        if (cb) cb(0.0f);
        return;
    }

    const bool row_slice_fetch = (bcsr_block_fetch_mode_ == BcsrBlockFetchMode::RowCacheline);
    const bool block_inflight_coalesce =
        kEnableBcsrInflightCoalescing && orch_.bcsr_block_inflight_coalesce_enable;

    if (!block_inflight_coalesce) {
        // Coalescing disabled: keep one-request-per-edge path (format-only BCSR behavior).
        const size_t block_bytes = orch_.bcsr_mgr->blockBytes();
        const size_t row_bytes = orch_.bcsr_mgr->blockRowBytes();
        uint64_t addr = orch_.bcsr_mgr->blockDataAddrByRow(block_row, idx_in_row);
        size_t req_orig_size = block_bytes;
        if (row_slice_fetch) {
            addr += static_cast<uint64_t>(intra_row) * static_cast<uint64_t>(row_bytes);
            req_orig_size = row_bytes;
        }
        uint64_t req_addr = addr;
        size_t req_size = req_orig_size;
        size_t slice_off = 0;
        prepareAlignedRead(addr, req_orig_size, orch_.line_size_bytes, req_addr, req_size, slice_off);

        PendingMeta meta{};
        meta.window_seq = win_seq;
        meta.address = req_addr;
        meta.size = req_size;
        meta.orig_address = addr;
        meta.orig_size = req_orig_size;
        meta.slice_offset = slice_off;
        meta.issue_cycle = now_cycle_;
        meta.bcsr_kind = 3;
        meta.bcsr_block_row = block_row;
        meta.bcsr_target_block_col = block_col;
        meta.bcsr_idx_in_row = idx_in_row;
        meta.bcsr_intra_row = intra_row;
        meta.bcsr_intra_col = intra_col;
        meta.bcsr_global_block_index = global_block_index;
        meta.bcsr_row_slice_fetch = row_slice_fetch;
        meta.bcsr_prefetch_all = false;
        meta.has_single_cb = true;
        meta.single_cb = std::move(cb);
        meta.is_weight = true;
        meta.count_weight_read = true;

        const bool count_budget = (win_seq != 0);
        const IssueStatus st = tryIssueRead_(meta, /*count_budget*/count_budget, /*budget_reserved*/false);
        if (st == IssueStatus::Issued) return;
        if (st == IssueStatus::DeferredInflight) {
            pending_direct_reads_.push_back(std::move(meta));
            return;
        }
        if (meta.has_single_cb && meta.single_cb) meta.single_cb(0.0f);
        return;
    }

    const uint32_t inflight_intra_row = row_slice_fetch ? intra_row : 0;
    const uint64_t inflight_key = makeBlockInflightKey_(win_seq, global_block_index, inflight_intra_row);
    auto& inflight = inflight_block_[inflight_key];
    if (!inflight.issued) {
        inflight.window_seq = win_seq;
        inflight.block_row = block_row;
        inflight.block_col = block_col;
        inflight.global_block_index = global_block_index;
        inflight.idx_in_row = idx_in_row;
        inflight.intra_row = intra_row;
        inflight.count_budget = (win_seq != 0);
    }

    BlockWaiter waiter{};
    waiter.pre_global = pre_global;
    waiter.post_local = post_local;
    waiter.intra_row = intra_row;
    waiter.intra_col = intra_col;
    waiter.cb = std::move(cb);
    inflight.waiters.push_back(std::move(waiter));

    if (inflight.issued) return;
    if (inflight.queued) return;
    if (inflight.waiters.size() == 1) block_miss_window_ += 1;

    const size_t block_bytes = orch_.bcsr_mgr->blockBytes();
    const size_t row_bytes = orch_.bcsr_mgr->blockRowBytes();
    uint64_t addr = orch_.bcsr_mgr->blockDataAddrByRow(block_row, idx_in_row);
    size_t req_orig_size = block_bytes;
    if (row_slice_fetch) {
        addr += static_cast<uint64_t>(intra_row) * static_cast<uint64_t>(row_bytes);
        req_orig_size = row_bytes;
    }
    uint64_t req_addr = addr;
    size_t req_size = req_orig_size;
    size_t slice_off = 0;
    prepareAlignedRead(addr, req_orig_size, orch_.line_size_bytes, req_addr, req_size, slice_off);

    PendingMeta meta{};
    meta.window_seq = win_seq;
    meta.address = req_addr;
    meta.size = req_size;
    meta.orig_address = addr;
    meta.orig_size = req_orig_size;
    meta.slice_offset = slice_off;
    meta.issue_cycle = now_cycle_;
    meta.bcsr_kind = 3;
    meta.bcsr_block_row = block_row;
    meta.bcsr_target_block_col = block_col;
    meta.bcsr_idx_in_row = idx_in_row;
    meta.bcsr_intra_row = intra_row;
    meta.bcsr_global_block_index = global_block_index;
    meta.bcsr_row_slice_fetch = row_slice_fetch;
    meta.bcsr_prefetch_all = false;
    meta.has_single_cb = false;
    meta.is_weight = true;
    meta.count_weight_read = true;

    const IssueStatus st = tryIssueRead_(std::move(meta), inflight.count_budget, /*budget_reserved*/false);
    if (st == IssueStatus::Issued) {
        inflight.issued = true;
        inflight.queued = false;
        if (diag_debug_ && diag_window_active_) diag_win_.block_miss += 1;
        return;
    }
    if (st == IssueStatus::DeferredInflight) {
        inflight.queued = true;
        pending_block_reads_.push_back(inflight_key);
        return;
    }

    auto waiters = std::move(inflight.waiters);
    inflight_block_.erase(inflight_key);
    for (auto& ww : waiters) {
        if (ww.cb) ww.cb(0.0f);
    }
}

void WeightMemorySubsystem::requestBCSR_(uint32_t pre_global, uint32_t post_local, std::function<void(float)> cb) {
    if (!orch_.use_bcsr || !orch_.bcsr_mgr) {
        if (cb) cb(0.0f);
        return;
    }
    if (!mem_access_) {
        if (cb) cb(0.0f);
        return;
    }
    if (orch_.bcsr_force_file_read && orch_.read_bcsr_from_file) {
        float w = orch_.read_bcsr_from_file(post_local, pre_global);
        if (cb) cb(applyWeightGuards_(w));
        return;
    }
    if (orch_.ensure_loader_ready && !orch_.ensure_loader_ready()) {
        // Non-window path: defer until WeightLoader completes; do not silently return 0.
        if (window_seq_ == 0) {
            PendingBcsrRowptrWaiter w{};
            w.pre_global = pre_global;
            w.post_local = post_local;
            w.cb = std::move(cb);
            pending_bcsr_rowptr_waiters_.push_back(std::move(w));
            return;
        }
        if (cb) cb(0.0f);
        return;
    }
    if (orch_.bcsr_rowptr_ready && !orch_.bcsr_rowptr_ready()) {
        // Non-window path: defer until rowptr is ready; rowptr prefetch will be issued by onClockTick().
        if (window_seq_ == 0) {
            PendingBcsrRowptrWaiter w{};
            w.pre_global = pre_global;
            w.post_local = post_local;
            w.cb = std::move(cb);
            pending_bcsr_rowptr_waiters_.push_back(std::move(w));
            maybeIssueBcsrRowptrPrefetch_();
            return;
        }
        if (cb) cb(0.0f);
        return;
    }

    const uint32_t br = orch_.bcsr_mgr->effectiveBlockRows();
    const uint32_t bc = orch_.bcsr_mgr->effectiveBlockCols();
    const uint32_t block_row = (br ? (post_local / br) : 0);
    const uint32_t intra_row = (br ? (post_local % br) : 0);
    const uint32_t block_col = (bc ? (pre_global / bc) : 0);
    const uint32_t intra_col = (bc ? (pre_global % bc) : 0);

    uint32_t start = 0;
    uint32_t end = 0;
    if (!orch_.bcsr_mgr->rowBounds(block_row, start, end)) {
        if (cb) cb(0.0f);
        return;
    }
    if (end <= start) {
        if (cb) cb(0.0f);
        return;
    }

    const std::vector<uint32_t>* experimental_cols = nullptr;
    uint32_t experimental_row_start = 0;
    if (lookupExperimentalNocRowidxCache_(block_row, experimental_row_start, experimental_cols) &&
        experimental_cols && !experimental_cols->empty()) {
        experimental_noc_rowidx_stats_.ready_bypass_experimental_cache_hit_total += 1u;
        uint32_t idx_in_row = 0;
        bool found = false;
        for (size_t i = 0; i < experimental_cols->size(); ++i) {
            if ((*experimental_cols)[i] == block_col) {
                idx_in_row = static_cast<uint32_t>(i);
                found = true;
                break;
            }
        }
        if (!found) {
            if (cb) cb(0.0f);
            return;
        }
        const uint32_t global_block_index = experimental_row_start + idx_in_row;
        enqueueBcsrBlockReadCoalesced_(window_seq_,
                                       block_row, block_col, global_block_index,
                                       idx_in_row,
                                       intra_row, intra_col,
                                       pre_global, post_local,
                                       std::move(cb));
        return;
    }

    std::vector<uint32_t> cols;
    if (!orch_.bcsr_mgr->rowIndexGet(block_row, cols)) {
        const uint32_t block_count = end - start;
        const size_t bytes = orch_.bcsr_mgr->colIndexBytes(block_count);
        const uint64_t addr = orch_.bcsr_mgr->colIndexAddr(start);

        const bool colidx_inflight_coalesce =
            kEnableBcsrInflightCoalescing && orch_.bcsr_colidx_inflight_coalesce_enable;
        if (!colidx_inflight_coalesce) {
            // Coalescing disabled: one-request-per-edge path.
            PendingMeta meta{};
            meta.window_seq = window_seq_;
            meta.address = addr;
            meta.size = bytes;
            meta.orig_address = addr;
            meta.orig_size = bytes;
            meta.slice_offset = 0;
            meta.issue_cycle = now_cycle_;
            meta.bcsr_kind = 2;
            meta.bcsr_block_row = block_row;
            meta.bcsr_target_block_col = block_col;
            meta.bcsr_intra_row = intra_row;
            meta.bcsr_intra_col = intra_col;
            meta.bcsr_row_start = start;
            meta.bcsr_prefetch_all = false;
            meta.has_single_cb = true;
            meta.single_cb = std::move(cb);
            meta.is_weight = true;
            meta.count_weight_read = false;

            const bool count_budget = (window_seq_ != 0);
            const IssueStatus st = tryIssueRead_(meta, /*count_budget*/count_budget, /*budget_reserved*/false);
            if (st == IssueStatus::Issued) {
                if (diag_debug_ && diag_window_active_) diag_win_.rowidx_miss += 1;
                return;
            }
            if (st == IssueStatus::DeferredInflight) {
                pending_direct_reads_.push_back(std::move(meta));
                return;
            }
            if (meta.has_single_cb && meta.single_cb) meta.single_cb(0.0f);
            return;
        }

        const uint32_t win_seq = window_seq_;
        const auto detached_inflight_it =
            experimental_noc_rowidx_detached_inflight_rows_.find(block_row);
        const uint64_t inflight_key = makeInflightKey_(win_seq, block_row);
        if (orch_.experimental_noc_rowidx_prefetch_detached_enable &&
            detached_inflight_it != experimental_noc_rowidx_detached_inflight_rows_.end()) {
            ColidxWaiter waiter{};
            waiter.pre_global = pre_global;
            waiter.post_local = post_local;
            waiter.target_block_col = block_col;
            waiter.intra_row = intra_row;
            waiter.intra_col = intra_col;
            waiter.cb = std::move(cb);
            const uint64_t detached_waiter_key =
                makeInflightKey_(detached_inflight_it->second, block_row);
            detached_colidx_waiters_[detached_waiter_key].push_back(std::move(waiter));
            experimental_noc_rowidx_stats_.detached_demand_join_total += 1u;
            return;
        }
        auto& inflight = inflight_colidx_[inflight_key];
        if (!inflight.issued) {
            inflight.window_seq = win_seq;
            inflight.block_row = block_row;
            inflight.row_start = start;
            inflight.row_end = end;
            inflight.count_budget = (win_seq != 0);
        }

        ColidxWaiter waiter{};
        waiter.pre_global = pre_global;
        waiter.post_local = post_local;
        waiter.target_block_col = block_col;
        waiter.intra_row = intra_row;
        waiter.intra_col = intra_col;
        waiter.cb = std::move(cb);
        inflight.waiters.push_back(std::move(waiter));

        if (inflight.issued) return;
        if (inflight.queued) return;

        PendingMeta meta{};
        meta.window_seq = win_seq;
        meta.address = addr;
        meta.size = bytes;
        meta.orig_address = addr;
        meta.orig_size = bytes;
        meta.slice_offset = 0;
        meta.issue_cycle = now_cycle_;
        meta.bcsr_kind = 2;
        meta.bcsr_block_row = block_row;
        meta.bcsr_target_block_col = UINT32_MAX;
        meta.bcsr_row_start = start;
        meta.bcsr_prefetch_all = false;
        meta.has_single_cb = false;
        meta.is_weight = true;
        meta.count_weight_read = false;

        const IssueStatus st = tryIssueRead_(std::move(meta), inflight.count_budget, /*budget_reserved*/false);
        if (st == IssueStatus::Issued) {
            inflight.issued = true;
            inflight.queued = false;
            if (diag_debug_ && diag_window_active_) diag_win_.rowidx_miss += 1;
            return;
        }
        if (st == IssueStatus::DeferredInflight) {
            inflight.queued = true;
            pending_colidx_reads_.push_back(inflight_key);
            return;
        }

        auto waiters = std::move(inflight.waiters);
        inflight_colidx_.erase(inflight_key);
        for (auto& ww : waiters) {
            if (ww.cb) ww.cb(0.0f);
        }
        return;
    }
    if (diag_debug_ && diag_window_active_) diag_win_.rowidx_hit += 1;
    experimental_noc_rowidx_stats_.ready_bypass_rowindex_get_hit_total += 1u;

    uint32_t idx_in_row = 0;
    bool found = false;
    for (size_t i = 0; i < cols.size(); ++i) {
        if (cols[i] == block_col) {
            idx_in_row = static_cast<uint32_t>(i);
            found = true;
            break;
        }
    }
    if (!found) {
        if (cb) cb(0.0f);
        return;
    }

    const uint32_t global_block_index = start + idx_in_row;
    enqueueBcsrBlockReadCoalesced_(window_seq_,
                                   block_row, block_col, global_block_index,
                                   idx_in_row,
                                   intra_row, intra_col,
                                   pre_global, post_local,
                                   std::move(cb));
    return;
}

void WeightMemorySubsystem::maybeIssueBcsrRowptrPrefetch_() {
    if (!orch_.use_bcsr || !orch_.bcsr_mgr) return;
    if (!mem_access_) return;
    if (orch_.bcsr_mgr->isRowptrReady()) return;
    if (orch_.bcsr_mgr->isRowptrReadPending()) return;
    if (orch_.ensure_loader_ready && !orch_.ensure_loader_ready()) return;
    const bool urgent = !pending_bcsr_rowptr_waiters_.empty();
    if (!urgent && now_cycle_ < orch_.memory_warmup_cycles) return;
    if (orch_.loader_barrier_cycles != 0 && now_cycle_ < orch_.loader_barrier_cycles) return;

    const uint32_t br = orch_.bcsr_mgr->effectiveBlockRows();
    const uint32_t nBlockRows = (br ? ((orch_.num_neurons + br - 1) / br) : 0);
    const size_t bytes = static_cast<size_t>(nBlockRows + 1) * sizeof(uint32_t);
    const uint64_t addr = orch_.bcsr_mgr->rowptrAddr();

    // Keep rowptr reads strictly at original addr/bytes (do NOT extend to cacheline boundaries).
    // Rationale: under some non-coherent cache configurations, extended multi-cacheline reads may
    // return all-zero payloads, while the same address range read without extension is correct.
    const uint64_t req_addr = addr;
    const size_t req_size = bytes;
    const size_t slice_off = 0;

    PendingMeta meta{};
    meta.address = req_addr;
    meta.size = req_size;
    meta.orig_address = addr;
    meta.orig_size = bytes;
    meta.slice_offset = slice_off;
    meta.issue_cycle = now_cycle_;
    meta.bcsr_kind = 1;
    meta.is_weight = true;
    meta.count_weight_read = false;
    if (diag_out_ && diag_out_->getVerboseLevel() >= 2) {
        diag_out_->verbose(CALL_INFO, 2, 0,
            "[diag-bcsr-rowptr-issue] node=%d core=%d addr=0x%llx bytes=%zu nBlockRows=%u\n",
            diag_node_id_, diag_core_id_,
            (unsigned long long)addr, bytes,
            nBlockRows);
    }
    const IssueStatus st = tryIssueRead_(std::move(meta), /*count_budget*/false, /*budget_reserved*/false);
    if (st == IssueStatus::Issued) {
        orch_.bcsr_mgr->setRowptrReadPending(true);
    }
}

void WeightMemorySubsystem::drainPendingBcsrRowptrWaiters_() {
    if (window_seq_ != 0) return; // only used by non-window workloads
    if (pending_bcsr_rowptr_waiters_.empty()) return;
    if (orch_.ensure_loader_ready && !orch_.ensure_loader_ready()) return;
    if (orch_.use_bcsr && orch_.bcsr_mgr && !orch_.bcsr_mgr->isRowptrReady()) {
        maybeIssueBcsrRowptrPrefetch_();
        return;
    }

    static constexpr size_t kMaxDrainPerTick = 1024;
    size_t drained = 0;
    while (drained < kMaxDrainPerTick && !pending_bcsr_rowptr_waiters_.empty()) {
        auto w = std::move(pending_bcsr_rowptr_waiters_.front());
        pending_bcsr_rowptr_waiters_.pop_front();
        requestBCSR_(w.pre_global, w.post_local, std::move(w.cb));
        ++drained;
    }
}

void WeightMemorySubsystem::bcsrPrefetchAll_() {
    if (!kEnableBcsrOptimizations) return;
    if (!orch_.use_bcsr || !orch_.bcsr_mgr) return;
    if (!orch_.bcsr_prefetch_all) return;
    if (bcsr_prefetch_issued_) return;
    if (!mem_access_) return;
    if (!orch_.bcsr_mgr->isRowptrReady()) return;

    const uint32_t br = orch_.bcsr_mgr->effectiveBlockRows();
    const uint32_t nBlockRows = (br ? ((orch_.num_neurons + br - 1) / br) : 0);
    for (uint32_t block_row = 0; block_row < nBlockRows; ++block_row) {
        uint32_t start = 0;
        uint32_t end = 0;
        if (!orch_.bcsr_mgr->rowBounds(block_row, start, end)) break;
        if (end <= start) continue;

        std::vector<uint32_t> cached_cols;
        if (orch_.bcsr_mgr->rowIndexGet(block_row, cached_cols)) {
            bcsrPrefetchRowBlocks_(block_row, cached_cols, start);
            continue;
        }

        const uint32_t block_count = end - start;
        const size_t bytes = orch_.bcsr_mgr->colIndexBytes(block_count);
        const uint64_t addr = orch_.bcsr_mgr->colIndexAddr(start);
        uint64_t req_addr = addr;
        size_t req_size = bytes;
        size_t slice_off = 0;
        prepareAlignedRead(addr, bytes, orch_.line_size_bytes, req_addr, req_size, slice_off);
        PendingMeta meta{};
        meta.address = req_addr;
        meta.size = req_size;
        meta.orig_address = addr;
        meta.orig_size = bytes;
        meta.slice_offset = slice_off;
        meta.issue_cycle = now_cycle_;
        meta.bcsr_kind = 2;
        meta.bcsr_block_row = block_row;
        meta.bcsr_row_start = start;
        meta.bcsr_prefetch_all = true;
        meta.bcsr_target_block_col = UINT32_MAX;
        meta.is_weight = true;
        meta.count_weight_read = false;
        (void)issueRead_(std::move(meta));
    }
    bcsr_prefetch_issued_ = true;
}

void WeightMemorySubsystem::bcsrPrefetchRowBlocks_(uint32_t block_row, const std::vector<uint32_t>& cols, uint32_t row_start) {
    if (!kEnableBcsrOptimizations) return;
    if (!orch_.use_bcsr || !orch_.bcsr_mgr) return;
    if (!mem_access_) return;
    const size_t block_bytes = orch_.bcsr_mgr->blockBytes();
    for (size_t i = 0; i < cols.size(); ++i) {
        uint32_t block_col = cols[i];
        if (orch_.bcsr_mgr->hasBlock(block_row, block_col)) continue;
        const uint32_t global_block_index = row_start + static_cast<uint32_t>(i);
        const uint64_t addr = orch_.bcsr_mgr->blockDataAddr(global_block_index);
        uint64_t req_addr = addr;
        size_t req_size = block_bytes;
        size_t slice_off = 0;
        prepareAlignedRead(addr, block_bytes, orch_.line_size_bytes, req_addr, req_size, slice_off);
        PendingMeta meta{};
        meta.address = req_addr;
        meta.size = req_size;
        meta.orig_address = addr;
        meta.orig_size = block_bytes;
        meta.slice_offset = slice_off;
        meta.issue_cycle = now_cycle_;
        meta.bcsr_kind = 3;
        meta.bcsr_block_row = block_row;
        meta.bcsr_target_block_col = block_col;
        meta.bcsr_row_start = row_start;
        meta.bcsr_idx_in_row = static_cast<uint32_t>(i);
        meta.bcsr_global_block_index = global_block_index;
        meta.bcsr_prefetch_all = true;
        meta.is_weight = true;
        meta.count_weight_read = true;
        (void)issueRead_(std::move(meta));
    }
}

void WeightMemorySubsystem::bcsrPopulateWeightCache_(uint32_t block_row, uint32_t block_col, const std::vector<float>& blk) {
    if (!kEnableBcsrOptimizations) return;
    if (!orch_.use_bcsr || !orch_.bcsr_mgr) return;
    if (!orch_.bcsr_populate_weight_cache_enable) return;
    if (blk.empty()) return;
    if (orch_.weights_cols == 0) return;
    const uint32_t br = orch_.bcsr_mgr->effectiveBlockRows();
    const uint32_t bc = orch_.bcsr_mgr->effectiveBlockCols();
    const uint32_t row_base = block_row * br;
    const uint32_t col_base = block_col * bc;
    for (uint32_t rr = 0; rr < br; ++rr) {
        const uint32_t post_local = row_base + rr;
        if (post_local >= orch_.num_neurons) break;
        for (uint32_t cc = 0; cc < bc; ++cc) {
            const uint32_t pre_global = col_base + cc;
            if (pre_global >= orch_.weights_cols) break;
            const size_t idx = static_cast<size_t>(rr) * static_cast<size_t>(bc) + cc;
            if (idx >= blk.size()) break;
            const float w = blk[idx];
            const uint64_t key = static_cast<uint64_t>(post_local) * static_cast<uint64_t>(orch_.weights_cols) +
                                 static_cast<uint64_t>(pre_global);
            if (orch_.cache_put) orch_.cache_put(key, w);
            else if (cache_put_fn_) cache_put_fn_(key, w);
        }
    }
}

void WeightMemorySubsystem::handleReadResp_(uint64_t req_id, uint64_t addr, PendingMeta meta, std::vector<uint8_t>&& data) {
    (void)req_id;
    meta.address = addr;

    // Decrement in-flight read counter once per response; always attempt to drain deferred reads on exit.
    if (meta.counted_inflight) {
        noteComplete(/*n*/1);
    }
    struct DrainGuard {
        WeightMemorySubsystem* self;
        ~DrainGuard() {
            self->drainPendingReads_();
            self->drainPendingDirectReads_();
        }
    } guard{this};

    if (orch_.report_mem_latency && now_cycle_ >= meta.issue_cycle) {
        orch_.report_mem_latency(static_cast<uint64_t>(now_cycle_ - meta.issue_cycle), meta.is_weight);
    }
    if (meta.scheme1_prefetch && orch_.on_scheme1_prefetch_resp) {
        orch_.on_scheme1_prefetch_resp();
    }

    const std::vector<uint8_t>& bytes = data;
    const size_t float_count = bytes.size() / sizeof(float);
    const float* fptr = (float_count > 0) ? reinterpret_cast<const float*>(bytes.data()) : nullptr;

    if (diag_debug_ && diag_window_active_ && diag_out_) {
        diag_win_.resp_cnt_total += 1;
        diag_win_.resp_bytes_total += static_cast<uint64_t>(bytes.size());
        if (bytes.size() < meta.size) diag_win_.resp_short_total += 1;
        switch (meta.bcsr_kind) {
            case 0:
            case 4:
            case 7:
            case 8:
                diag_win_.resp_cnt_dense += 1;
                diag_win_.resp_bytes_dense += static_cast<uint64_t>(bytes.size());
                break;
            case 1:
                diag_win_.resp_cnt_rowptr += 1;
                diag_win_.resp_bytes_rowptr += static_cast<uint64_t>(bytes.size());
                break;
            case 2:
                diag_win_.resp_cnt_colidx += 1;
                diag_win_.resp_bytes_colidx += static_cast<uint64_t>(bytes.size());
                break;
            case 3:
                diag_win_.resp_cnt_block += 1;
                diag_win_.resp_bytes_block += static_cast<uint64_t>(bytes.size());
                break;
            default:
                break;
        }
    }

    // Byte-exact correctness (dense-only): validate every returned byte before any slice/caching logic.
    if (meta.bcsr_kind == 0 && meta.is_weight && byteExactVerifyEnabled_()) {
        verifyDenseReadBytes_(addr, meta.size, bytes);
    }

    // ---- BCSR ----
    if (meta.bcsr_kind == 1) {
        // rowptr
        if (orch_.bcsr_mgr) {
            orch_.bcsr_mgr->setRowptrReadPending(false);
            const size_t slice_off = meta.slice_offset;
            const size_t slice_len = meta.orig_size ? meta.orig_size : meta.size;
            const bool slice_ok = (bytes.size() >= slice_off + slice_len);
            const uint8_t* slice_ptr = slice_ok ? (bytes.data() + slice_off) : bytes.data();
            const size_t slice_bytes = slice_ok ? slice_len : bytes.size();
            bool ok = orch_.bcsr_mgr->installRowptrFromBytes(slice_ptr, slice_bytes, orch_.num_neurons);
            if (!ok && orch_.bcsr_rowptr_file_fallback_enable && !orch_.weights_template.empty()) {
                // Fallback: load rowptr (+ optional colidx all_rows) from the BCSR file.
                // This is a robustness path for environments where stdmem multi-cacheline reads are unreliable.
                bcsr_rowptr_file_preload_attempted_ = true;
                const std::string path = resolveWeightsTemplatePath(orch_.weights_template, orch_.node_id, orch_.core_id);
                if (!path.empty() && orch_.base_addr <= orch_.bcsr_mgr->rowptrAddr()) {
                    const uint64_t rp_off = orch_.bcsr_mgr->rowptrAddr() - orch_.base_addr;
                    std::vector<uint8_t> rp_bytes;
                    const size_t expect = orch_.bcsr_mgr->expectedRowptrBytes(orch_.num_neurons);
                    if (readFileSlice(path, rp_off, expect, rp_bytes)) {
                        ok = orch_.bcsr_mgr->installRowptrFromBytes(rp_bytes.data(), rp_bytes.size(), orch_.num_neurons);
                        if (ok && diag_out_ && diag_out_->getVerboseLevel() >= 2) {
                            diag_out_->verbose(CALL_INFO, 2, 0,
                                "[diag-bcsr-rowptr-file] node=%d core=%d fallback ok path=%s bytes=%zu\n",
                                diag_node_id_, diag_core_id_, path.c_str(), rp_bytes.size());
                        }
                    }

                    // Optional: keep all row-index metadata resident (format metadata); preload all colidx once.
                    std::string mode = toLowerCopy(orch_.bcsr_row_index_prefetch_mode);
                    if (mode.empty()) mode = "auto";
                    if (ok && !bcsr_rowidx_file_preloaded_ && mode == "all_rows" && orch_.bcsr_mgr->rowIndexCacheCapacity() > 0) {
                        const uint32_t idx_bytes = orch_.bcsr_mgr->effectiveIdxBytes();
                        const uint64_t ci_base_addr = orch_.bcsr_mgr->colIndexAddr(0);
                        if (orch_.base_addr <= ci_base_addr) {
                            const uint32_t br = orch_.bcsr_mgr->effectiveBlockRows();
                            const uint32_t nBlockRows =
                                br ? ((orch_.num_neurons + br - 1u) / br) : static_cast<uint32_t>(orch_.num_neurons);
                            uint32_t last_start = 0;
                            uint32_t last_end = 0;
                            const bool bounds_ok =
                                (nBlockRows > 0) && orch_.bcsr_mgr->rowBounds(nBlockRows - 1u, last_start, last_end);
                            const uint32_t total_blocks = bounds_ok ? last_end : 0;
                            const size_t total_bytes = total_blocks ? orch_.bcsr_mgr->colIndexBytes(total_blocks) : 0;
                            const uint64_t ci_off = ci_base_addr - orch_.base_addr;
                            std::vector<uint8_t> all;
                            if (bounds_ok && total_bytes > 0 && (idx_bytes == 2 || idx_bytes == 4) &&
                                readFileSlice(path, ci_off, total_bytes, all)) {
                                for (uint32_t block_row = 0; block_row < nBlockRows; ++block_row) {
                                    uint32_t start = 0;
                                    uint32_t end = 0;
                                    if (!orch_.bcsr_mgr->rowBounds(block_row, start, end)) break;
                                    if (end <= start) continue;
                                    const uint32_t block_count = end - start;
                                    const size_t off = static_cast<size_t>(start) * static_cast<size_t>(idx_bytes);
                                    const size_t need = static_cast<size_t>(block_count) * static_cast<size_t>(idx_bytes);
                                    if (off + need > all.size()) break;

                                    std::vector<uint32_t> cols(block_count);
                                    if (idx_bytes == 2) {
                                        for (uint32_t i = 0; i < block_count; ++i) {
                                            uint16_t v = 0;
                                            std::memcpy(&v, all.data() + off + static_cast<size_t>(i) * 2u, 2u);
                                            cols[i] = v;
                                        }
                                    } else {
                                        for (uint32_t i = 0; i < block_count; ++i) {
                                            uint32_t v = 0;
                                            std::memcpy(&v, all.data() + off + static_cast<size_t>(i) * 4u, 4u);
                                            cols[i] = v;
                                        }
                                    }
                                    orch_.bcsr_mgr->rowIndexPut(block_row, std::move(cols));
                                }
                                bcsr_rowidx_file_preloaded_ = true;
                                if (diag_out_ && diag_out_->getVerboseLevel() >= 2) {
                                    diag_out_->verbose(CALL_INFO, 2, 0,
                                        "[diag-bcsr-colidx-file] node=%d core=%d preload all_rows ok bytes=%zu\n",
                                        diag_node_id_, diag_core_id_, all.size());
                                }
                            }
                        }
                    }
                }
            }
            if (!ok && orch_.ensure_rowptr_ready_or_fatal) {
                orch_.ensure_rowptr_ready_or_fatal("rowptr load failed (dram)");
            }
            if (orch_.bcsr_mgr->isRowptrReady()) {
                // Rowptr 就绪后仅恢复 Apply 阶段发起（BCSR 预取/缓存优化已全局禁用）
                if (orch_.resume_issue_after_rowptr_ready) {
                    orch_.resume_issue_after_rowptr_ready();
                }
            }
        }
        return;
    }

    if (meta.bcsr_kind == 2) {
        // colidx
        if (!orch_.bcsr_mgr) {
            if (meta.has_single_cb && meta.single_cb) meta.single_cb(0.0f);
            return;
        }
        if (bytes.size() < meta.size) {
            if (meta.has_single_cb && meta.single_cb) meta.single_cb(0.0f);
            return;
        }
        const size_t slice_off = meta.slice_offset;
        const size_t slice_len = meta.orig_size ? meta.orig_size : meta.size;
        if (bytes.size() < slice_off + slice_len) {
            if (meta.has_single_cb && meta.single_cb) meta.single_cb(0.0f);
            return;
        }
        const uint8_t* slice = bytes.data() + slice_off;
        const uint32_t idx_bytes = orch_.bcsr_mgr->effectiveIdxBytes();
        const bool rowindex_prefetch_only =
            !meta.has_single_cb &&
            meta.bcsr_target_block_col == UINT32_MAX &&
            !meta.bcsr_prefetch_all &&
            !meta.bcsr_colidx_bulk_all_rows;
        if (rowindex_prefetch_only && meta.experimental_noc_rowidx) {
            experimental_noc_rowidx_detached_inflight_rows_.erase(meta.bcsr_block_row);
        }
        enum class RowidxReadyResponseSource : uint8_t {
            InflightWaiters,
            InflightZeroWaiters,
            NonInflightPrefetchOnly,
        };
        auto noteRowidxReadyFromResponse =
            [&](RowidxReadyResponseSource source, bool experimental_prefetch) {
                experimental_noc_rowidx_stats_.ready_signal_rowindex_response_total += 1u;
                switch (source) {
                    case RowidxReadyResponseSource::InflightWaiters:
                        experimental_noc_rowidx_stats_
                            .ready_signal_rowindex_response_inflight_waiters_total += 1u;
                        break;
                    case RowidxReadyResponseSource::InflightZeroWaiters:
                        experimental_noc_rowidx_stats_
                            .ready_signal_rowindex_response_inflight_zero_waiters_total += 1u;
                        break;
                    case RowidxReadyResponseSource::NonInflightPrefetchOnly:
                        experimental_noc_rowidx_stats_
                            .ready_signal_rowindex_response_noninflight_prefetch_only_total += 1u;
                        break;
                }
                if (experimental_prefetch) {
                    experimental_noc_rowidx_stats_.ready_signal_prefetch_response_total += 1u;
                    switch (source) {
                        case RowidxReadyResponseSource::InflightWaiters:
                            experimental_noc_rowidx_stats_
                                .ready_signal_prefetch_response_inflight_waiters_total += 1u;
                            break;
                        case RowidxReadyResponseSource::InflightZeroWaiters:
                            experimental_noc_rowidx_stats_
                                .ready_signal_prefetch_response_inflight_zero_waiters_total += 1u;
                            break;
                        case RowidxReadyResponseSource::NonInflightPrefetchOnly:
                            experimental_noc_rowidx_stats_
                                .ready_signal_prefetch_response_noninflight_prefetch_only_total += 1u;
                            break;
                    }
                }

                if (!notePeInternalPodServiceObjectReady_(
                        PodMetadataObjectPlane::MetadataKind::RowIndex,
                        static_cast<uint64_t>(meta.bcsr_block_row),
                        meta.window_seq)) {
                    return;
                }

                experimental_noc_rowidx_stats_.ready_transition_rowindex_response_total += 1u;
                switch (source) {
                    case RowidxReadyResponseSource::InflightWaiters:
                        experimental_noc_rowidx_stats_
                            .ready_transition_rowindex_response_inflight_waiters_total += 1u;
                        break;
                    case RowidxReadyResponseSource::InflightZeroWaiters:
                        experimental_noc_rowidx_stats_
                            .ready_transition_rowindex_response_inflight_zero_waiters_total += 1u;
                        break;
                    case RowidxReadyResponseSource::NonInflightPrefetchOnly:
                        experimental_noc_rowidx_stats_
                            .ready_transition_rowindex_response_noninflight_prefetch_only_total += 1u;
                        break;
                }
                if (experimental_prefetch) {
                    experimental_noc_rowidx_stats_.ready_transition_prefetch_response_total += 1u;
                    switch (source) {
                        case RowidxReadyResponseSource::InflightWaiters:
                            experimental_noc_rowidx_stats_
                                .ready_transition_prefetch_response_inflight_waiters_total += 1u;
                            break;
                        case RowidxReadyResponseSource::InflightZeroWaiters:
                            experimental_noc_rowidx_stats_
                                .ready_transition_prefetch_response_inflight_zero_waiters_total += 1u;
                            break;
                        case RowidxReadyResponseSource::NonInflightPrefetchOnly:
                            experimental_noc_rowidx_stats_
                                .ready_transition_prefetch_response_noninflight_prefetch_only_total += 1u;
                            break;
                    }
                }
            };

        if (meta.bcsr_colidx_bulk_all_rows) {
            const uint32_t br = orch_.bcsr_mgr->effectiveBlockRows();
            const uint32_t nBlockRows =
                br ? ((orch_.num_neurons + br - 1u) / br) : static_cast<uint32_t>(orch_.num_neurons);
            uint32_t last_start = 0;
            uint32_t last_end = 0;
            const bool bounds_ok =
                (nBlockRows > 0) && orch_.bcsr_mgr->rowBounds(nBlockRows - 1u, last_start, last_end);
            const uint32_t total_blocks = bounds_ok ? last_end : 0;
            const size_t expect_bytes = total_blocks ? orch_.bcsr_mgr->colIndexBytes(total_blocks) : 0;

            const bool ok = bounds_ok && expect_bytes > 0 && slice_len >= expect_bytes && (idx_bytes == 2 || idx_bytes == 4);
            if (!ok) {
                row_index_prefetch_bulk_inflight_ = false;
                // Fail any waiters in this window to avoid deadlock.
                std::vector<uint64_t> keys;
                keys.reserve(inflight_colidx_.size());
                for (const auto& kv : inflight_colidx_) {
                    if (kv.second.window_seq == meta.window_seq) keys.push_back(kv.first);
                }
                for (uint64_t k : keys) {
                    auto it = inflight_colidx_.find(k);
                    if (it == inflight_colidx_.end()) continue;
                    auto waiters = std::move(it->second.waiters);
                    inflight_colidx_.erase(it);
                    for (auto& w : waiters) {
                        if (w.cb) w.cb(0.0f);
                    }
                }
                return;
            }

            experimental_noc_rowidx_stats_.bulk_fill_total += 1;
            uint64_t bulk_rows_cached_this_fill = 0;

            // Populate row_index_cache_ for all rows from a single contiguous colidx slice.
            for (uint32_t block_row = 0; block_row < nBlockRows; ++block_row) {
                uint32_t start = 0;
                uint32_t end = 0;
                if (!orch_.bcsr_mgr->rowBounds(block_row, start, end)) break;
                if (end <= start) continue;
                const uint32_t block_count = end - start;
                const size_t off = static_cast<size_t>(start) * static_cast<size_t>(idx_bytes);
                const size_t need = static_cast<size_t>(block_count) * static_cast<size_t>(idx_bytes);
                if (off + need > slice_len) break;

                std::vector<uint32_t> cols(block_count);
                if (idx_bytes == 2) {
                    for (uint32_t i = 0; i < block_count; ++i) {
                        uint16_t v = 0;
                        std::memcpy(&v, slice + off + static_cast<size_t>(i) * 2u, 2u);
                        cols[i] = v;
                    }
                } else {
                    for (uint32_t i = 0; i < block_count; ++i) {
                        uint32_t v = 0;
                        std::memcpy(&v, slice + off + static_cast<size_t>(i) * 4u, 4u);
                        cols[i] = v;
                    }
                }
                storeExperimentalNocRowidxCache_(block_row, start, cols);
                orch_.bcsr_mgr->rowIndexPut(block_row, std::move(cols));
                bulk_rows_cached_this_fill += 1;
            }

            experimental_noc_rowidx_stats_.bulk_rows_cached_total += bulk_rows_cached_this_fill;

            row_index_prefetch_bulk_inflight_ = false;

            // A: resolve any coalesced waiters for this window.
            std::vector<uint64_t> keys;
            keys.reserve(inflight_colidx_.size());
            for (const auto& kv : inflight_colidx_) {
                if (kv.second.window_seq == meta.window_seq) keys.push_back(kv.first);
            }
            uint64_t bulk_waiters_resolved_this_fill = 0;
            for (uint64_t k : keys) {
                auto inflight_it = inflight_colidx_.find(k);
                if (inflight_it == inflight_colidx_.end()) continue;
                ColidxInflight inflight = std::move(inflight_it->second);
                inflight_colidx_.erase(inflight_it);

                std::vector<uint32_t> cached_cols;
                if (!orch_.bcsr_mgr->rowIndexGet(inflight.block_row, cached_cols) || cached_cols.empty()) {
                    for (auto& w : inflight.waiters) {
                        if (w.cb) w.cb(0.0f);
                    }
                    continue;
                }

                std::unordered_map<uint32_t, uint32_t> idx_lookup;
                if (inflight.waiters.size() > 1) {
                    idx_lookup.reserve(cached_cols.size());
                    for (size_t i = 0; i < cached_cols.size(); ++i) {
                        idx_lookup[cached_cols[i]] = static_cast<uint32_t>(i);
                    }
                }
                auto findIdx = [&](uint32_t target, uint32_t& out_idx) -> bool {
                    if (!idx_lookup.empty()) {
                        auto it = idx_lookup.find(target);
                        if (it == idx_lookup.end()) return false;
                        out_idx = it->second;
                        return true;
                    }
                    for (size_t i = 0; i < cached_cols.size(); ++i) {
                        if (cached_cols[i] == target) {
                            out_idx = static_cast<uint32_t>(i);
                            return true;
                        }
                    }
                    return false;
                };

                for (auto& w : inflight.waiters) {
                    uint32_t idx_in_row = 0;
                    if (!findIdx(w.target_block_col, idx_in_row)) {
                        if (w.cb) w.cb(0.0f);
                        continue;
                    }
                    const uint32_t global_block_index = inflight.row_start + idx_in_row;
                    bulk_waiters_resolved_this_fill += 1;
                    enqueueBcsrBlockReadCoalesced_(meta.window_seq,
                                                   inflight.block_row,
                                                   w.target_block_col,
                                                   global_block_index,
                                                   idx_in_row,
                                                   w.intra_row,
                                                   w.intra_col,
                                                   w.pre_global,
                                                   w.post_local,
                                                   std::move(w.cb));
                }
            }
            experimental_noc_rowidx_stats_.bulk_waiters_resolved_total +=
                bulk_waiters_resolved_this_fill;
            return;
        }

        const size_t n = idx_bytes ? (slice_len / idx_bytes) : 0;
        std::vector<uint32_t> cols(n);
        if (idx_bytes == 2) {
            for (size_t i = 0; i < n; ++i) cols[i] = reinterpret_cast<const uint16_t*>(slice)[i];
        } else {
            for (size_t i = 0; i < n; ++i) cols[i] = reinterpret_cast<const uint32_t*>(slice)[i];
        }
        storeExperimentalNocRowidxCache_(meta.bcsr_block_row, meta.bcsr_row_start, cols);
        // 诊断：node0/core0 仅采样部分 colidx 内容，验证与文件偏移一致
        static int dbg_colidx_dump = 0;
        if (diag_debug_ && diag_out_ && diag_out_->getVerboseLevel() >= 2 &&
            diag_node_id_ == 0 && diag_core_id_ == 0 && dbg_colidx_dump < 16 && !cols.empty()) {
            const size_t dump = std::min<size_t>(cols.size(), 8);
            std::string first_vals;
            for (size_t i = 0; i < dump; ++i) {
                if (i) first_vals.push_back(',');
                first_vals += std::to_string(cols[i]);
            }
            const size_t dump_bytes = std::min<size_t>(slice_len, 16);
            std::string first_bytes;
            for (size_t i = 0; i < dump_bytes; ++i) {
                char buf[8];
                std::snprintf(buf, sizeof(buf), "%02x", slice[i]);
                if (i) first_bytes.push_back(' ');
                first_bytes += buf;
            }
            diag_out_->verbose(CALL_INFO, 2, 0,
                "[diag-bcsr-colidx-dump] node=0 core=0 block_row=%u start=%u end=%u count=%zu first=%s idx_bytes=%u bytes=[%s] slice_off=%zu\n",
                meta.bcsr_block_row, meta.bcsr_row_start, meta.bcsr_row_start + (uint32_t)cols.size(),
                cols.size(), first_vals.c_str(), idx_bytes, first_bytes.c_str(), slice_off);
            ++dbg_colidx_dump;
        }
        // 重要：
        // - 某些实验会全局关闭 BCSR 缓存（rowIndex/block cache），此时 rowIndexPut/get 为 no-op。
        // - 但 colidx 回包仍必须能定位 target_block_col；否则所有 BCSR 权重读都会退化为 0（功能错误）。
        // 因此：本次回包逻辑始终使用本地解析得到的 `cols`；仅在缓存启用时再写入 rowIndex cache。
        const uint32_t row_index_cap = orch_.bcsr_mgr->rowIndexCacheCapacity();
        if (meta.bcsr_prefetch_all) {
            bcsrPrefetchRowBlocks_(meta.bcsr_block_row, cols, meta.bcsr_row_start);
            if (row_index_cap != 0) orch_.bcsr_mgr->rowIndexPut(meta.bcsr_block_row, std::move(cols));
            return;
        }

        const uint64_t inflight_key = makeInflightKey_(meta.window_seq, meta.bcsr_block_row);
        auto detached_waiters_it = detached_colidx_waiters_.find(inflight_key);
        if (detached_waiters_it != detached_colidx_waiters_.end()) {
            auto waiters = std::move(detached_waiters_it->second);
            detached_colidx_waiters_.erase(detached_waiters_it);
            experimental_noc_rowidx_stats_.detached_demand_ready_signal_total += 1u;
            if (notePeInternalPodServiceObjectReady_(
                    PodMetadataObjectPlane::MetadataKind::RowIndex,
                    static_cast<uint64_t>(meta.bcsr_block_row),
                    meta.window_seq)) {
                experimental_noc_rowidx_stats_.detached_demand_ready_transition_total += 1u;
            }

            std::unordered_map<uint32_t, uint32_t> idx_lookup;
            if (waiters.size() > 1 && !cols.empty()) {
                idx_lookup.reserve(cols.size());
                for (size_t i = 0; i < cols.size(); ++i) {
                    idx_lookup[cols[i]] = static_cast<uint32_t>(i);
                }
            }
            auto findIdx = [&](uint32_t target, uint32_t& out_idx) -> bool {
                if (!idx_lookup.empty()) {
                    auto it = idx_lookup.find(target);
                    if (it == idx_lookup.end()) return false;
                    out_idx = it->second;
                    return true;
                }
                for (size_t i = 0; i < cols.size(); ++i) {
                    if (cols[i] == target) {
                        out_idx = static_cast<uint32_t>(i);
                        return true;
                    }
                }
                return false;
            };

            for (auto& w : waiters) {
                uint32_t idx_in_row = 0;
                if (!findIdx(w.target_block_col, idx_in_row)) {
                    experimental_noc_rowidx_stats_.detached_demand_fallback_zero_total += 1u;
                    if (w.cb) w.cb(0.0f);
                    experimental_noc_rowidx_stats_.detached_demand_waiters_resolved_total += 1u;
                    continue;
                }
                const uint32_t global_block_index = meta.bcsr_row_start + idx_in_row;
                enqueueBcsrBlockReadCoalesced_(meta.window_seq,
                                               meta.bcsr_block_row,
                                               w.target_block_col,
                                               global_block_index,
                                               idx_in_row,
                                               w.intra_row,
                                               w.intra_col,
                                               w.pre_global,
                                               w.post_local,
                                               std::move(w.cb));
                experimental_noc_rowidx_stats_.detached_demand_waiters_resolved_total += 1u;
            }
            if (row_index_cap != 0) orch_.bcsr_mgr->rowIndexPut(meta.bcsr_block_row, std::move(cols));
            return;
        }

        // A: coalesced waiters for this (window, block_row)
        auto inflight_it = inflight_colidx_.find(inflight_key);
        if (inflight_it != inflight_colidx_.end()) {
            auto waiters = std::move(inflight_it->second.waiters);
            const uint32_t row_start = inflight_it->second.row_start;
            inflight_colidx_.erase(inflight_it);
            if (rowindex_prefetch_only && meta.experimental_noc_rowidx) {
                if (waiters.empty()) {
                    experimental_noc_rowidx_stats_.prefetch_complete_zero_waiters_total += 1u;
                } else {
                    experimental_noc_rowidx_stats_.prefetch_complete_waiters_total += 1u;
                }
            }

            // Build quick index (block_col -> idx_in_row) once for this row.
            std::unordered_map<uint32_t, uint32_t> idx_lookup;
            if (waiters.size() > 1 && !cols.empty()) {
                idx_lookup.reserve(cols.size());
                for (size_t i = 0; i < cols.size(); ++i) {
                    idx_lookup[cols[i]] = static_cast<uint32_t>(i);
                }
            }
            auto findIdx = [&](uint32_t target, uint32_t& out_idx) -> bool {
                if (!idx_lookup.empty()) {
                    auto it = idx_lookup.find(target);
                    if (it == idx_lookup.end()) return false;
                    out_idx = it->second;
                    return true;
                }
                for (size_t i = 0; i < cols.size(); ++i) {
                    if (cols[i] == target) {
                        out_idx = static_cast<uint32_t>(i);
                        return true;
                    }
                }
                return false;
            };

            for (auto& w : waiters) {
                uint32_t idx_in_row = 0;
                if (!findIdx(w.target_block_col, idx_in_row)) {
                    if (w.cb) w.cb(0.0f);
                    continue;
                }
                const uint32_t global_block_index = row_start + idx_in_row;
                enqueueBcsrBlockReadCoalesced_(meta.window_seq,
                                               meta.bcsr_block_row,
                                               w.target_block_col,
                                               global_block_index,
                                               idx_in_row,
                                               w.intra_row,
                                               w.intra_col,
                                               w.pre_global,
                                               w.post_local,
                                               std::move(w.cb));
            }
            if (rowindex_prefetch_only) {
                const RowidxReadyResponseSource source =
                    waiters.empty()
                        ? RowidxReadyResponseSource::InflightZeroWaiters
                        : RowidxReadyResponseSource::InflightWaiters;
                noteRowidxReadyFromResponse(source, meta.experimental_noc_rowidx);
            }
            if (row_index_cap != 0) orch_.bcsr_mgr->rowIndexPut(meta.bcsr_block_row, std::move(cols));
            return;
        }

        uint32_t idx_in_row = 0;
        bool found = false;
        for (size_t i = 0; i < cols.size(); ++i) {
            if (cols[i] == meta.bcsr_target_block_col) {
                idx_in_row = static_cast<uint32_t>(i);
                found = true;
                break;
            }
        }
        if (!found) {
            if (rowindex_prefetch_only && meta.experimental_noc_rowidx) {
                experimental_noc_rowidx_stats_.prefetch_complete_inflight_miss_total += 1u;
                noteRowidxReadyFromResponse(
                    RowidxReadyResponseSource::NonInflightPrefetchOnly,
                    meta.experimental_noc_rowidx);
            }
            if (meta.has_single_cb && meta.single_cb) meta.single_cb(0.0f);
            if (row_index_cap != 0) orch_.bcsr_mgr->rowIndexPut(meta.bcsr_block_row, std::move(cols));
            return;
        }
        const uint32_t global_block_index = meta.bcsr_row_start + idx_in_row;
        if (row_index_cap != 0) orch_.bcsr_mgr->rowIndexPut(meta.bcsr_block_row, std::move(cols));
        if (rowindex_prefetch_only && meta.experimental_noc_rowidx) {
            experimental_noc_rowidx_stats_.prefetch_complete_inflight_miss_total += 1u;
            noteRowidxReadyFromResponse(
                RowidxReadyResponseSource::NonInflightPrefetchOnly,
                meta.experimental_noc_rowidx);
        }
        enqueueBcsrBlockReadCoalesced_(meta.window_seq,
                                       meta.bcsr_block_row,
                                       meta.bcsr_target_block_col,
                                       global_block_index,
                                       idx_in_row,
                                       meta.bcsr_intra_row,
                                       meta.bcsr_intra_col,
                                       /*pre_global=*/meta.bcsr_target_block_col * orch_.bcsr_mgr->effectiveBlockCols() + meta.bcsr_intra_col,
                                       /*post_local=*/meta.bcsr_block_row * orch_.bcsr_mgr->effectiveBlockRows() + meta.bcsr_intra_row,
                                       std::move(meta.single_cb));
        return;
    }

    if (meta.bcsr_kind == 3) {
        // block data
        if (!orch_.bcsr_mgr) {
            if (meta.has_single_cb && meta.single_cb) meta.single_cb(0.0f);
            return;
        }
        const uint32_t br = orch_.bcsr_mgr->effectiveBlockRows();
        const uint32_t bc = orch_.bcsr_mgr->effectiveBlockCols();
        const size_t slice_off = meta.slice_offset;
        const size_t slice_len = meta.orig_size ? meta.orig_size : meta.size;
        const size_t row_expect_bytes = static_cast<size_t>(bc) * sizeof(float);
        const size_t full_expect_bytes = static_cast<size_t>(br) * static_cast<size_t>(bc) * sizeof(float);
        const bool row_cacheline_fetch = meta.bcsr_row_slice_fetch;
        const size_t expect_bytes = row_cacheline_fetch ? row_expect_bytes : full_expect_bytes;
        const bool ok = (bytes.size() >= slice_off + slice_len) && (slice_len >= expect_bytes);
        if (diag_debug_ && diag_out_ && diag_out_->getVerboseLevel() >= 2 &&
            diag_node_id_ == 0 && diag_core_id_ == 0) {
            static int dbg_block_resp = 0;
            if (dbg_block_resp < 2048) {
                float f0 = 0.0f;
                if (bytes.size() >= slice_off + sizeof(float)) {
                    std::memcpy(&f0, bytes.data() + slice_off, sizeof(float));
                }
                diag_out_->verbose(CALL_INFO, 2, 0,
                    "[diag-bcsr-block-resp] node=%d core=%d block_row=%u block_col=%u gbi=%u addr=0x%llx bytes=%zu slice_off=%zu f0=%.6f ok=%d\n",
                    diag_node_id_, diag_core_id_, meta.bcsr_block_row, meta.bcsr_target_block_col,
                    meta.bcsr_global_block_index, (unsigned long long)meta.address,
                    bytes.size(), slice_off, f0, ok ? 1 : 0);
                ++dbg_block_resp;
            }
        }
        if (ok && expect_bytes > 0) {
            if (row_cacheline_fetch) {
                std::vector<float> row_vals(static_cast<size_t>(bc), 0.0f);
                std::memcpy(row_vals.data(), bytes.data() + slice_off, row_expect_bytes);

                const uint64_t inflight_key = makeBlockInflightKey_(
                    meta.window_seq, meta.bcsr_global_block_index, meta.bcsr_intra_row);
                auto inflight_it = inflight_block_.find(inflight_key);
                if (inflight_it != inflight_block_.end()) {
                    auto waiters = std::move(inflight_it->second.waiters);
                    inflight_block_.erase(inflight_it);
                    for (auto& w : waiters) {
                        float ww = 0.0f;
                        if (w.intra_row == meta.bcsr_intra_row) {
                            const uint32_t off = w.intra_col;
                            ww = (off < row_vals.size()) ? row_vals[off] : 0.0f;
                        } else if (orch_.read_bcsr_from_file) {
                            ww = orch_.read_bcsr_from_file(w.post_local, w.pre_global);
                        }
                        const float guarded = applyWeightGuards_(ww);
                        verifyBcsrEdgeWeight_(w.pre_global, w.post_local, guarded);
                        if (w.cb) w.cb(guarded);
                    }
                } else if (meta.has_single_cb && meta.single_cb) {
                    const uint32_t off = meta.bcsr_intra_col;
                    float w = (off < row_vals.size()) ? row_vals[off] : 0.0f;
                    const float guarded = applyWeightGuards_(w);
                    verifyBcsrEdgeWeight_(
                        /*pre_global=*/meta.bcsr_target_block_col * bc + meta.bcsr_intra_col,
                        /*post_local=*/meta.bcsr_block_row * br + meta.bcsr_intra_row,
                        guarded);
                    meta.single_cb(guarded);
                }
            } else {
                const size_t n = static_cast<size_t>(br) * static_cast<size_t>(bc);
                std::vector<float> blk(n, 0.0f);
                std::memcpy(blk.data(), bytes.data() + slice_off, full_expect_bytes);

                // Deliver callbacks directly from the returned block bytes to support "block_cache_cap=0"
                // (naive baseline). Caching, if enabled, is applied after callbacks.
                const uint64_t inflight_key = makeBlockInflightKey_(
                    meta.window_seq, meta.bcsr_global_block_index, /*intra_row=*/0);
                auto inflight_it = inflight_block_.find(inflight_key);
                if (inflight_it != inflight_block_.end()) {
                    auto waiters = std::move(inflight_it->second.waiters);
                    inflight_block_.erase(inflight_it);
                    for (auto& w : waiters) {
                        const uint32_t off = w.intra_row * bc + w.intra_col;
                        const float ww = (off < blk.size()) ? blk[off] : 0.0f;
                        const float guarded = applyWeightGuards_(ww);
                        verifyBcsrEdgeWeight_(w.pre_global, w.post_local, guarded);
                        if (w.cb) w.cb(guarded);
                    }
                } else if (meta.has_single_cb && meta.single_cb) {
                    const uint32_t off = meta.bcsr_intra_row * bc + meta.bcsr_intra_col;
                    float w = (off < blk.size()) ? blk[off] : 0.0f;
                    const float guarded = applyWeightGuards_(w);
                    verifyBcsrEdgeWeight_(
                        /*pre_global=*/meta.bcsr_target_block_col * bc + meta.bcsr_intra_col,
                        /*post_local=*/meta.bcsr_block_row * br + meta.bcsr_intra_row,
                        guarded);
                    meta.single_cb(guarded);
                }

                // Optional: populate dense weight cache from this returned block (optimization).
                bcsrPopulateWeightCache_(meta.bcsr_block_row, meta.bcsr_target_block_col, blk);

                // Optional: cache this block for subsequent hits.
                if (orch_.bcsr_mgr->blockCacheCapacity() != 0) {
                    orch_.bcsr_mgr->blockPut(meta.bcsr_block_row, meta.bcsr_target_block_col, std::move(blk));
                }
            }
        } else {
            const uint64_t inflight_key = makeBlockInflightKey_(
                meta.window_seq,
                meta.bcsr_global_block_index,
                row_cacheline_fetch ? meta.bcsr_intra_row : 0);
            auto inflight_it = inflight_block_.find(inflight_key);
            if (inflight_it != inflight_block_.end()) {
                auto waiters = std::move(inflight_it->second.waiters);
                inflight_block_.erase(inflight_it);
                for (auto& w : waiters) {
                    float ww = 0.0f;
                    if (orch_.read_bcsr_from_file) {
                        ww = orch_.read_bcsr_from_file(w.post_local, w.pre_global);
                    }
                    if (w.cb) w.cb(applyWeightGuards_(ww));
                }
                return;
            }

            // 兜底：仅回调单个权重（不强行回填整个块），避免破坏性能/复杂性
            if (meta.has_single_cb && meta.single_cb) {
                float w = 0.0f;
                if (orch_.read_bcsr_from_file) {
                    const uint32_t post_local = meta.bcsr_block_row * br + meta.bcsr_intra_row;
                    const uint32_t pre_global = meta.bcsr_target_block_col * bc + meta.bcsr_intra_col;
                    w = orch_.read_bcsr_from_file(post_local, pre_global);
                }
                meta.single_cb(applyWeightGuards_(w));
            }
        }
        return;
    }

    if (meta.bcsr_kind == 6) {
        if (meta.has_bytes_cb && meta.bytes_cb) {
            meta.bytes_cb(data);
        }
        return;
    }

    if (meta.bcsr_kind == 7) {
        PulseSharedLineService::ServiceKey key{};
        key.scope_id = meta.pulse_scope_id;
        key.window_seq = meta.window_seq;
        key.line_addr = meta.pulse_service_line_addr;
        const bool service_ok = (bytes.size() >= meta.size);
        const size_t fanout = PulseSharedLineService::complete(
            key, service_ok, meta.pulse_service_line_addr, bytes);
        if (service_ok) {
            pulse_ready_fanout_total_ += static_cast<uint64_t>(fanout);
        }
        return;
    }

    if (meta.bcsr_kind == 8) {
        PulseSharedLineService::ServiceKey key{};
        key.scope_id = meta.pulse_scope_id;
        key.window_seq = meta.window_seq;
        key.line_addr = meta.pulse_service_line_addr;
        const bool service_ok = (bytes.size() >= meta.size);
        const size_t fanout = PulseSharedLineService::complete(
            key, service_ok, meta.pulse_service_line_addr, bytes);
        if (service_ok && fanout > 1u) {
            pulse_ready_fanout_total_ += static_cast<uint64_t>(fanout - 1u);
        }
        return;
    }

    if (meta.bcsr_kind == 4) {
        if (meta.has_single_cb && meta.single_cb) {
            float w = 0.0f;
            const size_t need = meta.slice_offset + sizeof(float);
            if (bytes.size() >= need) {
                std::memcpy(&w, bytes.data() + meta.slice_offset, sizeof(float));
            }
            meta.single_cb(applyReadRespZeroFallback_(w));
        }
        return;
    }

    // ---- Dense ----
    const uint32_t width = orch_.use_post_row_pre_col ? orch_.weights_cols : orch_.num_neurons;
    if (width > 0 && fptr) {
        for (size_t i = 0; i < float_count; ++i) {
            const uint32_t col_idx = meta.post_start + static_cast<uint32_t>(i);
            if (col_idx >= width) break;
            float w = applyReadRespZeroFallback_(fptr[i]);
            const uint64_t key = static_cast<uint64_t>(meta.pre) * static_cast<uint64_t>(width) +
                                 static_cast<uint64_t>(col_idx);
            if (orch_.cache_put) orch_.cache_put(key, w);
            else if (cache_put_fn_) cache_put_fn_(key, w);
        }
    }
    if (meta.has_single_cb && meta.single_cb) {
        float w = 0.0f;
        const uint32_t target_col = meta.cb_post;
        if (fptr && width > 0 &&
            target_col >= meta.post_start &&
            (target_col - meta.post_start) < float_count &&
            target_col < width) {
            w = fptr[static_cast<size_t>(target_col - meta.post_start)];
        }
        meta.single_cb(applyReadRespZeroFallback_(w));
    }
}

bool WeightMemorySubsystem::byteExactVerifyEnabled_() const {
    if (!orch_.byte_exact_verify_enable) return false;
    return toLowerCopy(orch_.byte_exact_verify_mode) == "dense_rowcol_v1";
}

float WeightMemorySubsystem::expectedDenseWeight_(uint32_t row, uint32_t col) const {
    const uint64_t v =
        static_cast<uint64_t>(row) * static_cast<uint64_t>(orch_.byte_exact_verify_row_scale) +
        static_cast<uint64_t>(col);
    return static_cast<float>(v);
}

void WeightMemorySubsystem::verifyDenseReadBytes_(uint64_t addr, size_t req_size, const std::vector<uint8_t>& bytes) {
    if (!byteExactVerifyEnabled_()) return;
    // Dense-only; BCSR uses file-backed/structured format and has its own invariants.
    if (orch_.use_bcsr) return;
    if (orch_.num_neurons == 0) return;
    const uint32_t width = orch_.use_post_row_pre_col ? orch_.weights_cols : orch_.num_neurons;
    if (width == 0) return;
    if (orch_.base_addr == 0) return;
    if (addr < orch_.base_addr) return;

    SST::Output* out = diagOutOrFallback_();

    if (bytes.size() != req_size) {
        byte_exact_mismatch_count_ += 1;
        if (byte_exact_mismatch_logged_ < orch_.byte_exact_verify_max_mismatch) {
            byte_exact_mismatch_logged_ += 1;
            out->verbose(CALL_INFO, 0, 0,
                "[byte-exact] size-mismatch node=%u core=%u window=%u addr=0x%llx got=%zu req=%zu\n",
                orch_.node_id, orch_.core_id, window_seq_,
                (unsigned long long)addr, bytes.size(), req_size);
        }
    }

    const uint64_t off_bytes = addr - orch_.base_addr;
    if ((off_bytes & 0x3ull) != 0ull) {
        byte_exact_mismatch_count_ += 1;
        out->fatal(CALL_INFO, -1,
            "❌ [byte-exact] unaligned addr: node=%u core=%u window=%u base=0x%llx addr=0x%llx off=%" PRIu64 "\n",
            orch_.node_id, orch_.core_id, window_seq_,
            (unsigned long long)orch_.base_addr,
            (unsigned long long)addr,
            off_bytes);
    }

    const size_t nbytes = bytes.size();
    const size_t nfloat = nbytes / 4u;

    if (dense_phys_enable_) {
        const uint64_t phys_total_bytes = dense_phys_.total_bytes;
        const uint64_t row_bytes_logical = static_cast<uint64_t>(dense_phys_.row_bytes_logical);
        const uint64_t row_stride_bytes = static_cast<uint64_t>(dense_phys_.row_stride_bytes);
        const uint64_t group_stride_bytes = static_cast<uint64_t>(dense_phys_.group_stride_bytes);
        const uint64_t rows_per_dram_row = static_cast<uint64_t>(dense_phys_.rows_per_dram_row);
        const uint64_t rows_total = static_cast<uint64_t>(orch_.num_neurons);

        for (size_t i = 0; i < nfloat; ++i) {
            const uint64_t p = off_bytes + static_cast<uint64_t>(i) * 4ull;
            if (p >= phys_total_bytes) {
                byte_exact_mismatch_count_ += 1;
                if (byte_exact_mismatch_logged_ < orch_.byte_exact_verify_max_mismatch) {
                    byte_exact_mismatch_logged_ += 1;
                    out->verbose(CALL_INFO, 0, 0,
                        "[byte-exact] oob-phys node=%u core=%u window=%u addr=0x%llx float_i=%zu off=%" PRIu64 " phys_total=%" PRIu64 "\n",
                        orch_.node_id, orch_.core_id, window_seq_,
                        (unsigned long long)addr, i, p, phys_total_bytes);
                }
                continue;
            }

            const uint64_t group = (group_stride_bytes != 0) ? (p / group_stride_bytes) : 0;
            const uint64_t within_group = (group_stride_bytes != 0) ? (p % group_stride_bytes) : p;
            const uint64_t row_in_group = (row_stride_bytes != 0) ? (within_group / row_stride_bytes) : 0;
            const uint64_t within_row = (row_stride_bytes != 0) ? (within_group % row_stride_bytes) : within_group;
            const uint64_t row64 = group * rows_per_dram_row + row_in_group;

            uint8_t expect_b[4] = {0, 0, 0, 0};
            uint32_t row = 0;
            uint32_t col = 0;
            bool padding = true;
            if (row64 < rows_total && within_row < row_bytes_logical) {
                padding = false;
                row = static_cast<uint32_t>(row64);
                col = static_cast<uint32_t>(within_row / 4ull);
                const float expect_f = expectedDenseWeight_(row, col);
                std::memcpy(expect_b, &expect_f, sizeof(expect_b));
            }

            const uint8_t* got_b = bytes.data() + i * 4u;
            if (std::memcmp(got_b, expect_b, 4u) != 0) {
                byte_exact_mismatch_count_ += 1;
                if (byte_exact_mismatch_logged_ < orch_.byte_exact_verify_max_mismatch) {
                    byte_exact_mismatch_logged_ += 1;
                    if (padding) {
                        out->verbose(CALL_INFO, 0, 0,
                            "[byte-exact] pad-mismatch node=%u core=%u window=%u addr=0x%llx float_i=%zu off=%" PRIu64 " row=%" PRIu64 " within_row=%" PRIu64 " got=[%02x %02x %02x %02x] expect=[%02x %02x %02x %02x]\n",
                            orch_.node_id, orch_.core_id, window_seq_,
                            (unsigned long long)addr, i, p, row64, within_row,
                            got_b[0], got_b[1], got_b[2], got_b[3],
                            expect_b[0], expect_b[1], expect_b[2], expect_b[3]);
                    } else {
                        float got_f = 0.0f;
                        float expect_f = 0.0f;
                        std::memcpy(&got_f, got_b, sizeof(got_f));
                        std::memcpy(&expect_f, expect_b, sizeof(expect_f));
                        out->verbose(CALL_INFO, 0, 0,
                            "[byte-exact] mismatch node=%u core=%u window=%u addr=0x%llx float_i=%zu row=%u col=%u got_f=%.9g expect_f=%.9g got=[%02x %02x %02x %02x] expect=[%02x %02x %02x %02x]\n",
                            orch_.node_id, orch_.core_id, window_seq_,
                            (unsigned long long)addr,
                            i, row, col,
                            got_f, expect_f,
                            got_b[0], got_b[1], got_b[2], got_b[3],
                            expect_b[0], expect_b[1], expect_b[2], expect_b[3]);
                    }
                }
                if (byte_exact_mismatch_count_ >= orch_.byte_exact_verify_max_mismatch) {
                    out->fatal(CALL_INFO, -1,
                        "❌ [byte-exact] too many mismatches: node=%u core=%u window=%u mismatches=%u max=%u\n",
                        orch_.node_id, orch_.core_id, window_seq_,
                        byte_exact_mismatch_count_, orch_.byte_exact_verify_max_mismatch);
                }
            }
        }

        if (nfloat > 0) byte_exact_verified_reads_ += 1;
        return;
    }

    const uint64_t total_floats = static_cast<uint64_t>(orch_.num_neurons) * static_cast<uint64_t>(width);
    const uint64_t start_float = off_bytes / 4ull;
    for (size_t i = 0; i < nfloat; ++i) {
        const uint64_t idx = start_float + static_cast<uint64_t>(i);
        if (idx >= total_floats) {
            byte_exact_mismatch_count_ += 1;
            if (byte_exact_mismatch_logged_ < orch_.byte_exact_verify_max_mismatch) {
                byte_exact_mismatch_logged_ += 1;
                out->verbose(CALL_INFO, 0, 0,
                    "[byte-exact] oob idx node=%u core=%u window=%u addr=0x%llx float_i=%zu idx=%" PRIu64 " total=%" PRIu64 "\n",
                    orch_.node_id, orch_.core_id, window_seq_,
                    (unsigned long long)addr, i, idx, total_floats);
            }
            continue;
        }
        const uint32_t row = static_cast<uint32_t>(idx / static_cast<uint64_t>(width));
        const uint32_t col = static_cast<uint32_t>(idx % static_cast<uint64_t>(width));
        const float expect_f = expectedDenseWeight_(row, col);
        uint8_t expect_b[4];
        std::memcpy(expect_b, &expect_f, sizeof(expect_b));
        const uint8_t* got_b = bytes.data() + i * 4u;
        if (std::memcmp(got_b, expect_b, 4u) != 0) {
            byte_exact_mismatch_count_ += 1;
            if (byte_exact_mismatch_logged_ < orch_.byte_exact_verify_max_mismatch) {
                byte_exact_mismatch_logged_ += 1;
                float got_f = 0.0f;
                std::memcpy(&got_f, got_b, sizeof(got_f));
                out->verbose(CALL_INFO, 0, 0,
                    "[byte-exact] mismatch node=%u core=%u window=%u addr=0x%llx float_i=%zu row=%u col=%u got_f=%.9g expect_f=%.9g got=[%02x %02x %02x %02x] expect=[%02x %02x %02x %02x]\n",
                    orch_.node_id, orch_.core_id, window_seq_,
                    (unsigned long long)addr,
                    i, row, col,
                    got_f, expect_f,
                    got_b[0], got_b[1], got_b[2], got_b[3],
                    expect_b[0], expect_b[1], expect_b[2], expect_b[3]);
            }
            if (byte_exact_mismatch_count_ >= orch_.byte_exact_verify_max_mismatch) {
                out->fatal(CALL_INFO, -1,
                    "❌ [byte-exact] too many mismatches: node=%u core=%u window=%u mismatches=%u max=%u\n",
                    orch_.node_id, orch_.core_id, window_seq_,
                    byte_exact_mismatch_count_, orch_.byte_exact_verify_max_mismatch);
            }
        }
    }

    // Count a response as "verified" only when we could meaningfully interpret it as dense floats.
    if (nfloat > 0) byte_exact_verified_reads_ += 1;
}

void WeightMemorySubsystem::verifyDenseEdgeWeight_(uint32_t pre_global, uint32_t post_local, uint32_t count, float weight) {
    if (!byteExactVerifyEnabled_()) return;
    if (orch_.use_bcsr) return;
    if (!orch_.accessor) return;

    SST::Output* out = diagOutOrFallback_();

    uint32_t req_pre = 0;
    uint32_t req_post = 0;
    uint64_t cache_key = 0;
    if (!orch_.accessor->resolve(pre_global, post_local, req_pre, req_post, cache_key)) return;

    const uint32_t row = orch_.use_post_row_pre_col ? req_post : req_pre;
    const uint32_t col = orch_.use_post_row_pre_col ? req_pre : req_post;
    const float expect = expectedDenseWeight_(row, col);

    if (!(weight == expect)) {
        byte_exact_mismatch_count_ += 1;
        if (byte_exact_mismatch_logged_ < orch_.byte_exact_verify_max_mismatch) {
            byte_exact_mismatch_logged_ += 1;
            out->verbose(CALL_INFO, 0, 0,
                "[byte-exact] edge-mismatch node=%u core=%u window=%u pre=%u post=%u req_pre=%u req_post=%u row=%u col=%u got=%.9g expect=%.9g count=%u\n",
                orch_.node_id, orch_.core_id, window_seq_,
                pre_global, post_local, req_pre, req_post, row, col,
                weight, expect, count);
        }
        if (byte_exact_mismatch_count_ >= orch_.byte_exact_verify_max_mismatch) {
            out->fatal(CALL_INFO, -1,
                "❌ [byte-exact] too many mismatches: node=%u core=%u window=%u mismatches=%u max=%u\n",
                orch_.node_id, orch_.core_id, window_seq_,
                byte_exact_mismatch_count_, orch_.byte_exact_verify_max_mismatch);
        }
    }

    // dv correctness (should be exact under dense_rowcol_v1 range constraints).
    const float dv = weight * static_cast<float>(count);
    const float dv_expect = expect * static_cast<float>(count);
    if (!(dv == dv_expect)) {
        byte_exact_mismatch_count_ += 1;
        if (byte_exact_mismatch_logged_ < orch_.byte_exact_verify_max_mismatch) {
            byte_exact_mismatch_logged_ += 1;
            out->verbose(CALL_INFO, 0, 0,
                "[byte-exact] dv-mismatch node=%u core=%u window=%u pre=%u post=%u dv=%.9g dv_expect=%.9g count=%u\n",
                orch_.node_id, orch_.core_id, window_seq_,
                pre_global, post_local, dv, dv_expect, count);
        }
        if (byte_exact_mismatch_count_ >= orch_.byte_exact_verify_max_mismatch) {
            out->fatal(CALL_INFO, -1,
                "❌ [byte-exact] too many mismatches: node=%u core=%u window=%u mismatches=%u max=%u\n",
                orch_.node_id, orch_.core_id, window_seq_,
                byte_exact_mismatch_count_, orch_.byte_exact_verify_max_mismatch);
        }
    }

    byte_exact_verified_edges_ += 1;
}

void WeightMemorySubsystem::emitByteExactPassMarker_(const char* where, uint32_t seq) {
    if (!byteExactVerifyEnabled_()) return;
    if (byte_exact_pass_logged_) return;

    SST::Output* out = diagOutOrFallback_();

    if (byte_exact_mismatch_count_ != 0) {
        out->fatal(CALL_INFO, -1,
            "❌ BYTE_EXACT_VERIFY: mismatches=%u (expected 0) node=%u core=%u where=%s seq=%u\n",
            byte_exact_mismatch_count_,
            orch_.node_id, orch_.core_id,
            (where ? where : "?"), seq);
    }
    if (byte_exact_verified_reads_ == 0 || byte_exact_verified_edges_ == 0) {
        out->fatal(CALL_INFO, -1,
            "❌ BYTE_EXACT_VERIFY: no effective verification (reads=%" PRIu64 " edges=%" PRIu64 ") node=%u core=%u where=%s seq=%u\n",
            byte_exact_verified_reads_, byte_exact_verified_edges_,
            orch_.node_id, orch_.core_id,
            (where ? where : "?"), seq);
    }
    out->verbose(CALL_INFO, 0, 0,
        "BYTE_EXACT_VERIFY: PASS mode=%s node=%u core=%u where=%s seq=%u verified_reads=%" PRIu64 " verified_edges=%" PRIu64 "\n",
        orch_.byte_exact_verify_mode.c_str(),
        orch_.node_id, orch_.core_id,
        (where ? where : "?"), seq,
        byte_exact_verified_reads_, byte_exact_verified_edges_);
    byte_exact_pass_logged_ = true;
}

bool WeightMemorySubsystem::bcsrSemanticVerifyEnabled_() const {
    if (!orch_.bcsr_semantic_verify_enable) return false;
    if (!orch_.use_bcsr) return false;
    return true;
}

void WeightMemorySubsystem::verifyBcsrEdgeWeight_(uint32_t pre_global, uint32_t post_local, float weight) {
    if (!bcsrSemanticVerifyEnabled_()) return;
    if (bcsr_sem_pass_logged_) return;
    if (orch_.bcsr_semantic_verify_max_edges == 0) return;
    if (bcsr_sem_verified_edges_ >= static_cast<uint64_t>(orch_.bcsr_semantic_verify_max_edges)) return;

    SST::Output* out = diagOutOrFallback_();

    bool have_ref = false;
    float ref_raw = 0.0f;
    if (orch_.read_bcsr_from_file) {
        ref_raw = orch_.read_bcsr_from_file(post_local, pre_global);
        have_ref = true;
    } else if (orch_.bcsr_mgr && !orch_.weights_template.empty() && orch_.base_addr != 0) {
        // Fallback: direct file read (independent of control/workload).
        const std::string path = resolveWeightsTemplatePath(orch_.weights_template, orch_.node_id, orch_.core_id);
        if (!path.empty()) {
            std::ifstream fin(path, std::ios::in | std::ios::binary);
            if (fin.good()) {
                const uint32_t br = orch_.bcsr_mgr->effectiveBlockRows();
                const uint32_t bc = orch_.bcsr_mgr->effectiveBlockCols();
                const uint32_t idxB = orch_.bcsr_mgr->effectiveIdxBytes();
                const uint32_t valB = orch_.bcsr_mgr->effectiveValBytes();
                if (br != 0 && bc != 0 && (idxB == 2 || idxB == 4) && valB == 4) {
                    const uint32_t block_row = post_local / br;
                    const uint32_t intra_row = post_local % br;
                    const uint32_t blk_col = pre_global / bc;
                    const uint32_t intra_col = pre_global % bc;

                    const uint64_t rp_off = orch_.bcsr_mgr->rowptrAddr() - orch_.base_addr;
                    const uint64_t ci_off = orch_.bcsr_mgr->colidxAddr() - orch_.base_addr;
                    const uint64_t bd_off = orch_.bcsr_mgr->blockdataAddr() - orch_.base_addr;

                    uint32_t start = 0;
                    uint32_t end = 0;
                    fin.seekg(static_cast<std::streamoff>(rp_off + static_cast<uint64_t>(block_row) * sizeof(uint32_t)), std::ios::beg);
                    fin.read(reinterpret_cast<char*>(&start), 4);
                    fin.read(reinterpret_cast<char*>(&end), 4);
                    if (fin.good() && end > start) {
                        int idx_in_row = -1;
                        for (uint32_t j = 0; j < (end - start); ++j) {
                            fin.seekg(static_cast<std::streamoff>(ci_off + static_cast<uint64_t>(start + j) * idxB), std::ios::beg);
                            uint32_t colv = 0;
                            if (idxB == 2) {
                                uint16_t v = 0;
                                fin.read(reinterpret_cast<char*>(&v), 2);
                                colv = v;
                            } else {
                                fin.read(reinterpret_cast<char*>(&colv), 4);
                            }
                            if (!fin.good()) break;
                            if (colv == blk_col) { idx_in_row = static_cast<int>(j); break; }
                        }
                        if (fin.good() && idx_in_row >= 0) {
                            const size_t blk_bytes = static_cast<size_t>(br) * static_cast<size_t>(bc) * sizeof(float);
                            fin.seekg(static_cast<std::streamoff>(bd_off + static_cast<uint64_t>(start + static_cast<uint32_t>(idx_in_row)) * blk_bytes), std::ios::beg);
                            std::vector<float> blk(static_cast<size_t>(br) * static_cast<size_t>(bc), 0.0f);
                            fin.read(reinterpret_cast<char*>(blk.data()), static_cast<std::streamsize>(blk_bytes));
                            if (fin.good()) {
                                const uint32_t off = intra_row * bc + intra_col;
                                ref_raw = (off < blk.size()) ? blk[off] : 0.0f;
                                have_ref = true;
                            }
                        } else {
                            // Block not present -> weight is logically 0.
                            ref_raw = 0.0f;
                            have_ref = true;
                        }
                    }
                } else {
                    bcsr_sem_inconclusive_ = true;
                    if (bcsr_sem_inconclusive_reason_.empty()) bcsr_sem_inconclusive_reason_ = "unsupported_bcsr_val_or_idx_bytes";
                    return;
                }
            }
        }
    }

    if (!have_ref) {
        bcsr_sem_inconclusive_ = true;
        if (bcsr_sem_inconclusive_reason_.empty()) bcsr_sem_inconclusive_reason_ = "missing_ref_reader";
        return;
    }
    const float ref = applyWeightGuards_(ref_raw);

    const float abs_tol = orch_.bcsr_semantic_verify_abs_tol;
    const float rel_tol = orch_.bcsr_semantic_verify_rel_tol;
    const float diff = std::fabs(weight - ref);
    const float tol = abs_tol + rel_tol * std::fabs(ref);
    const bool ok = std::isfinite(weight) && std::isfinite(ref) && (diff <= tol);
    if (!ok) {
        bcsr_sem_mismatch_count_ += 1;
        if (bcsr_sem_mismatch_logged_ < orch_.bcsr_semantic_verify_max_mismatch) {
            bcsr_sem_mismatch_logged_ += 1;
            out->verbose(CALL_INFO, 0, 0,
                "BCSR_SEMANTIC_VERIFY: MISMATCH node=%u core=%u window=%u pre=%u post=%u got=%.9g ref=%.9g diff=%.9g tol=%.9g\n",
                orch_.node_id, orch_.core_id, window_seq_,
                pre_global, post_local,
                weight, ref, diff, tol);
        }
        if (bcsr_sem_mismatch_count_ >= orch_.bcsr_semantic_verify_max_mismatch) {
            out->fatal(CALL_INFO, -1,
                "❌ BCSR_SEMANTIC_VERIFY: too many mismatches node=%u core=%u mismatches=%u max=%u\n",
                orch_.node_id, orch_.core_id,
                bcsr_sem_mismatch_count_, orch_.bcsr_semantic_verify_max_mismatch);
        }
        return;
    }

    bcsr_sem_verified_edges_ += 1;
}

void WeightMemorySubsystem::emitBcsrSemanticVerifyMarker_(const char* where, uint32_t seq) {
    if (!bcsrSemanticVerifyEnabled_()) return;
    if (bcsr_sem_pass_logged_) return;

    SST::Output* out = diagOutOrFallback_();

    if (bcsr_sem_mismatch_count_ != 0) {
        out->fatal(CALL_INFO, -1,
            "❌ BCSR_SEMANTIC_VERIFY: mismatches=%u (expected 0) node=%u core=%u where=%s seq=%u\n",
            bcsr_sem_mismatch_count_,
            orch_.node_id, orch_.core_id,
            (where ? where : "?"), seq);
    }

    if (bcsr_sem_verified_edges_ == 0) {
        const char* reason = bcsr_sem_inconclusive_reason_.empty()
                                 ? (bcsr_sem_inconclusive_ ? "inconclusive" : "no_verified_edges")
                                 : bcsr_sem_inconclusive_reason_.c_str();
        out->verbose(CALL_INFO, 0, 0,
            "BCSR_SEMANTIC_VERIFY: WARN INCONCLUSIVE node=%u core=%u where=%s seq=%u verified_edges=%" PRIu64 " reason=%s\n",
            orch_.node_id, orch_.core_id,
            (where ? where : "?"), seq,
            bcsr_sem_verified_edges_,
            reason);
        bcsr_sem_pass_logged_ = true;
        return;
    }

    out->verbose(CALL_INFO, 0, 0,
        "BCSR_SEMANTIC_VERIFY: PASS node=%u core=%u where=%s seq=%u verified_edges=%" PRIu64 " max_edges=%u\n",
        orch_.node_id, orch_.core_id,
        (where ? where : "?"), seq,
        bcsr_sem_verified_edges_,
        orch_.bcsr_semantic_verify_max_edges);
    bcsr_sem_pass_logged_ = true;
}
