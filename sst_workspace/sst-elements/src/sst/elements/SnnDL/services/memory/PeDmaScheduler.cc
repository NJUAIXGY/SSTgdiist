// -*- c++ -*-

#include "services/memory/PeDmaScheduler.h"

#include <algorithm>
#include <cstring>
#include <utility>

namespace SST { namespace SnnDL {

PeDmaScheduler::Config::Config() {
    for (auto& stage_scales : stage_budget_permille) {
        stage_scales.fill(1000);
    }
    stage_budget_permille[PeDmaScheduler::stageIndex_(Stage::Apply)][PeDmaScheduler::prioIndex_(Priority::P2)] = 0;
    stage_budget_permille[PeDmaScheduler::stageIndex_(Stage::Scatter)][PeDmaScheduler::prioIndex_(Priority::P2)] = 250;
    stage_budget_permille[PeDmaScheduler::stageIndex_(Stage::Idle)][PeDmaScheduler::prioIndex_(Priority::P2)] = 250;
    stage_budget_permille[PeDmaScheduler::stageIndex_(Stage::Gather)][PeDmaScheduler::prioIndex_(Priority::P3)] = 200;
    stage_budget_permille[PeDmaScheduler::stageIndex_(Stage::Apply)][PeDmaScheduler::prioIndex_(Priority::P3)] = 200;
    stage_budget_permille[PeDmaScheduler::stageIndex_(Stage::Scatter)][PeDmaScheduler::prioIndex_(Priority::P3)] = 200;
    stage_budget_permille[PeDmaScheduler::stageIndex_(Stage::Idle)][PeDmaScheduler::prioIndex_(Priority::P3)] = 200;
}

PeDmaScheduler::PeDmaScheduler(const Config& cfg) : cfg_(cfg) {
    if (cfg_.num_cores == 0) cfg_.num_cores = 1;
    if (cfg_.channels == 0) cfg_.channels = 1;
    if (cfg_.channel_interleave_bytes == 0) cfg_.channel_interleave_bytes = 1;
    backends_.assign(cfg_.num_cores, nullptr);
    per_core_pending_.assign(cfg_.num_cores, 0);
    barrier_seen_.assign(cfg_.num_cores, false);
    initQueues_();
}

void PeDmaScheduler::initQueues_() {
    for (auto& q : queues_) q.assign(cfg_.num_cores, {});
    for (auto& q : overflow_) q.assign(cfg_.num_cores, {});
    rr_cursor_.fill(0);
    updateQueueDepthStats_();
}

void PeDmaScheduler::registerCoreBackend(uint32_t core_id, IMemoryAccess* backend) {
    if (core_id >= backends_.size()) return;
    backends_[core_id] = backend;
}

PeDmaScheduler::RequestId PeDmaScheduler::submitRead(Request req) {
    if (req.bytes == 0 || req.core_id >= cfg_.num_cores) {
        if (req.cb) req.cb(0, req.addr, {});
        return 0;
    }

    const bool queue_full = (cfg_.queue_depth != 0 && queued_total_ >= cfg_.queue_depth);
    if (queue_full && cfg_.overflow_policy == Config::OverflowPolicy::FailFast) {
        stats_.stall_cycles_queue_full += 1;
        if (req.cb) req.cb(0, req.addr, {});
        return 0;
    }

    DmaTxn txn{};
    txn.id = next_req_id_++;
    txn.req = std::move(req);
    txn.buffer.resize(txn.req.bytes);
    txn.submit_cycle = barrier_cycle_ == std::numeric_limits<uint64_t>::max() ? 0 : barrier_cycle_;
    txn.ready_cycle = txn.submit_cycle + static_cast<uint64_t>(cfg_.setup_cycles);
    txn.last_progress_cycle = txn.submit_cycle;

    const size_t prio = prioIndex_(txn.req.priority);
    const uint32_t core = txn.req.core_id;
    const RequestId dma_id = txn.id;

    txns_.emplace(txn.id, std::move(txn));
    per_core_pending_[core] += 1;

    if (!queue_full) {
        queues_[prio][core].push_back(dma_id);
        queued_total_ += 1;
    } else {
        overflow_[prio][core].push_back(dma_id);
        overflow_total_ += 1;
    }

    updateQueueDepthStats_();
    return dma_id;
}

void PeDmaScheduler::setStage(Stage stage, uint32_t seq) {
    stage_ = stage;
    stage_seq_ = seq;
    (void)stage_seq_;
}

void PeDmaScheduler::onCoreTickEnd(uint64_t now_cycle, uint32_t core_id) {
    if (core_id >= cfg_.num_cores) return;
    if (barrier_cycle_ != now_cycle) {
        barrier_cycle_ = now_cycle;
        barrier_seen_.assign(cfg_.num_cores, false);
        barrier_seen_count_ = 0;
    }
    if (!barrier_seen_[core_id]) {
        barrier_seen_[core_id] = true;
        barrier_seen_count_ += 1;
    }
    if (barrier_seen_count_ == cfg_.num_cores && barrier_serviced_cycle_ != now_cycle) {
        serviceCycle_(now_cycle);
        barrier_serviced_cycle_ = now_cycle;
    }
}

size_t PeDmaScheduler::pendingSizeForCore(uint32_t core_id) const {
    if (core_id >= per_core_pending_.size()) return 0;
    return per_core_pending_[core_id];
}

void PeDmaScheduler::serviceCycle_(uint64_t now_cycle) {
    expireInflightTxns_(now_cycle);
    promoteOverflow_();

    uint64_t bytes_left =
        (cfg_.bytes_per_cycle == 0) ? std::numeric_limits<uint64_t>::max() : cfg_.bytes_per_cycle;
    uint64_t engines_left =
        (cfg_.read_engines == 0) ? std::numeric_limits<uint64_t>::max() : static_cast<uint64_t>(cfg_.read_engines);

    std::array<uint64_t, 4> prio_budget_left{};
    for (size_t p = 0; p < prio_budget_left.size(); ++p) {
        const uint16_t scale = cfg_.stage_budget_permille[stageIndex_(stage_)][p];
        if (scale == 0) {
            prio_budget_left[p] = 0;
        } else if (cfg_.bytes_per_cycle == 0 || scale >= 1000) {
            prio_budget_left[p] = std::numeric_limits<uint64_t>::max();
        } else {
            const uint64_t scaled =
                (static_cast<uint64_t>(cfg_.bytes_per_cycle) * static_cast<uint64_t>(scale)) / 1000ull;
            prio_budget_left[p] = std::max<uint64_t>(1ull, scaled);
        }
    }

    std::vector<uint64_t> channel_budget_left{};
    if (cfg_.channels > 1 && cfg_.channel_bytes_per_cycle > 0) {
        channel_budget_left.assign(static_cast<size_t>(cfg_.channels), cfg_.channel_bytes_per_cycle);
    }

    while (engines_left > 0) {
        if (cfg_.max_inflight != 0 && inflight_total_ >= static_cast<size_t>(cfg_.max_inflight)) {
            stats_.stall_cycles_inflight += 1;
            break;
        }
        if (cfg_.bytes_per_cycle != 0 && bytes_left == 0) {
            stats_.stall_cycles_budget += 1;
            break;
        }
        if (!issueOne_(now_cycle, bytes_left, engines_left, prio_budget_left, channel_budget_left)) {
            break;
        }
    }

    stats_.inflight_cur = inflight_total_;
    updateQueueDepthStats_();
}

void PeDmaScheduler::expireInflightTxns_(uint64_t now_cycle) {
    if (cfg_.inflight_timeout_cycles == 0) return;
    std::vector<RequestId> expire_ids;
    expire_ids.reserve(txns_.size());
    for (auto& kv : txns_) {
        DmaTxn& txn = kv.second;
        if (txn.failed || txn.inflight_bursts == 0) continue;
        const uint64_t base = txn.last_progress_cycle;
        if (now_cycle < base) continue;
        const uint64_t age = now_cycle - base;
        if (age < cfg_.inflight_timeout_cycles) continue;
        txn.failed = true;
        if (inflight_total_ >= txn.inflight_bursts) {
            inflight_total_ -= txn.inflight_bursts;
        } else {
            inflight_total_ = 0;
        }
        txn.inflight_bursts = 0;
        txn.bytes_issued = txn.req.bytes;
        expire_ids.push_back(txn.id);
    }
    for (const RequestId id : expire_ids) {
        finalizeTxn_(id);
    }
}

void PeDmaScheduler::promoteOverflow_() {
    if (cfg_.queue_depth == 0) return;
    while (queued_total_ < cfg_.queue_depth && overflow_total_ > 0) {
        bool moved = false;
        for (size_t p = 0; p < overflow_.size() && queued_total_ < cfg_.queue_depth; ++p) {
            for (size_t core = 0; core < overflow_[p].size() && queued_total_ < cfg_.queue_depth; ++core) {
                auto& oq = overflow_[p][core];
                if (oq.empty()) continue;
                queues_[p][core].push_back(oq.front());
                oq.pop_front();
                queued_total_ += 1;
                overflow_total_ -= 1;
                moved = true;
            }
        }
        if (!moved) break;
    }
}

bool PeDmaScheduler::issueOne_(uint64_t now_cycle,
                               uint64_t& bytes_left,
                               uint64_t& engines_left,
                               std::array<uint64_t, 4>& prio_budget_left,
                               std::vector<uint64_t>& channel_budget_left) {
    for (size_t p = 0; p < queues_.size(); ++p) {
        const Priority prio = static_cast<Priority>(p);
        if (prio_budget_left[p] == 0) {
            bool any_pending = false;
            for (const auto& q : queues_[p]) {
                if (!q.empty()) {
                    any_pending = true;
                    break;
                }
            }
            if (any_pending) stats_.stall_cycles_stage_gate += 1;
            continue;
        }

        const size_t start = rr_cursor_[p];
        for (size_t attempt = 0; attempt < cfg_.num_cores; ++attempt) {
            const size_t core = (start + attempt) % cfg_.num_cores;
            auto& q = queues_[p][core];
            if (q.empty()) continue;

            const RequestId id = q.front();
            auto it = txns_.find(id);
            if (it == txns_.end()) {
                q.pop_front();
                if (queued_total_ > 0) queued_total_ -= 1;
                continue;
            }

            DmaTxn& txn = it->second;
            if (txn.failed) {
                q.pop_front();
                if (queued_total_ > 0) queued_total_ -= 1;
                finalizeTxn_(id);
                rr_cursor_[p] = (core + 1) % cfg_.num_cores;
                return true;
            }

            if (txn.ready_cycle > now_cycle) continue;

            IMemoryAccess* backend = backends_[core];
            if (!backend) {
                q.pop_front();
                if (queued_total_ > 0) queued_total_ -= 1;
                failTxn_(id);
                rr_cursor_[p] = (core + 1) % cfg_.num_cores;
                return true;
            }

            const uint64_t burst = computeBurstBytes_(txn, bytes_left);
            if (burst == 0) {
                stats_.stall_cycles_budget += 1;
                continue;
            }
            if (prio_budget_left[p] != std::numeric_limits<uint64_t>::max() && burst > prio_budget_left[p]) {
                stats_.stall_cycles_budget += 1;
                continue;
            }

            const uint64_t issue_addr = txn.req.addr + static_cast<uint64_t>(txn.bytes_issued);
            const uint32_t channel = channelForAddr_(issue_addr);
            if (!channel_budget_left.empty()) {
                if (channel >= channel_budget_left.size() || channel_budget_left[channel] < burst) {
                    stats_.stall_cycles_budget += 1;
                    continue;
                }
            }

            const size_t offset = txn.bytes_issued;
            const RequestId backend_req = backend->read(
                issue_addr,
                static_cast<size_t>(burst),
                [this, id, offset, burst](RequestId, uint64_t addr, std::vector<uint8_t>&& data) {
                    onBurstResp_(id, offset, static_cast<size_t>(burst), addr, std::move(data));
                });
            if (backend_req == 0) {
                // Backend could be temporarily unable to accept (e.g. step-gate phase boundary).
                // Keep txn queued and retry in a later barrier cycle to avoid same-cycle fail/requeue churn.
                // Guardrail: if rejection persists for too long, fail-close the txn to avoid permanent
                // step drain stalls when memory ingress stays closed after EndScatter.
                txn.backend_reject_streak += 1;
                if (cfg_.backend_reject_retry_cycles != 0 &&
                    txn.backend_reject_streak >= cfg_.backend_reject_retry_cycles) {
                    q.pop_front();
                    if (queued_total_ > 0) queued_total_ -= 1;
                    failTxn_(id);
                    rr_cursor_[p] = (core + 1) % cfg_.num_cores;
                    return true;
                }
                stats_.stall_cycles_budget += 1;
                continue;
            }
            txn.backend_reject_streak = 0;
            txn.last_progress_cycle = now_cycle;

            if (txn.issue_cycle_first == 0) txn.issue_cycle_first = now_cycle;
            txn.bytes_issued += static_cast<size_t>(burst);
            txn.inflight_bursts += 1;
            inflight_total_ += 1;
            stats_.inflight_cur = inflight_total_;
            stats_.inflight_max = std::max<uint64_t>(stats_.inflight_max, inflight_total_);
            stats_.issue_reqs_total += 1;
            stats_.issue_bytes_total += burst;
            if (txn.bytes_issued == txn.req.bytes) {
                q.pop_front();
                if (queued_total_ > 0) queued_total_ -= 1;
            }
            if (cfg_.bytes_per_cycle != 0 && bytes_left != std::numeric_limits<uint64_t>::max()) {
                bytes_left -= burst;
            }
            if (prio_budget_left[p] != std::numeric_limits<uint64_t>::max()) {
                prio_budget_left[p] -= burst;
            }
            if (!channel_budget_left.empty()) {
                channel_budget_left[channel] -= burst;
            }
            if (engines_left != std::numeric_limits<uint64_t>::max()) {
                engines_left -= 1;
                if (engines_left == 0) stats_.stall_cycles_engine += 1;
            }
            rr_cursor_[p] = (core + 1) % cfg_.num_cores;
            return true;
        }
    }
    return false;
}

uint64_t PeDmaScheduler::computeBurstBytes_(const DmaTxn& txn, uint64_t bytes_left) const {
    const size_t remaining = txn.req.bytes - txn.bytes_issued;
    if (remaining == 0) return 0;

    uint64_t cap = static_cast<uint64_t>(remaining);
    if (cfg_.burst_bytes > 0) {
        cap = std::min<uint64_t>(cap, cfg_.burst_bytes);
    } else if (cfg_.bytes_per_cycle > 0) {
        cap = std::min<uint64_t>(cap, std::max<uint64_t>(1ull, std::min<uint64_t>(64ull, cfg_.bytes_per_cycle)));
    }
    if (cfg_.bytes_per_cycle > 0 && bytes_left != std::numeric_limits<uint64_t>::max()) {
        cap = std::min<uint64_t>(cap, bytes_left);
    }
    return cap;
}

uint32_t PeDmaScheduler::channelForAddr_(uint64_t addr) const {
    if (cfg_.channels <= 1 || cfg_.channel_bytes_per_cycle == 0) return 0;
    return static_cast<uint32_t>((addr / cfg_.channel_interleave_bytes) % cfg_.channels);
}

void PeDmaScheduler::onBurstResp_(RequestId id,
                                  size_t offset,
                                  size_t requested_bytes,
                                  uint64_t,
                                  std::vector<uint8_t>&& data) {
    auto it = txns_.find(id);
    if (it == txns_.end()) return;

    DmaTxn& txn = it->second;
    if (txn.inflight_bursts > 0) txn.inflight_bursts -= 1;
    if (inflight_total_ > 0) inflight_total_ -= 1;
    if (barrier_cycle_ != std::numeric_limits<uint64_t>::max()) {
        txn.last_progress_cycle = barrier_cycle_;
    }

    if (!txn.failed && data.size() >= requested_bytes && offset + requested_bytes <= txn.buffer.size()) {
        if (requested_bytes != 0) {
            std::memcpy(txn.buffer.data() + static_cast<ptrdiff_t>(offset), data.data(), requested_bytes);
        }
        txn.bytes_done += requested_bytes;
    } else {
        txn.failed = true;
    }

    if (txn.bytes_done == txn.req.bytes && txn.inflight_bursts == 0) {
        finalizeTxn_(id);
    } else if (txn.failed && txn.inflight_bursts == 0) {
        finalizeTxn_(id);
    }
}

void PeDmaScheduler::finalizeTxn_(RequestId id) {
    auto it = txns_.find(id);
    if (it == txns_.end()) return;

    DmaTxn txn = std::move(it->second);
    txns_.erase(it);
    if (txn.req.core_id < per_core_pending_.size() && per_core_pending_[txn.req.core_id] > 0) {
        per_core_pending_[txn.req.core_id] -= 1;
    }

    const size_t p = prioIndex_(txn.req.priority);
    if (txn.req.cb) {
        if (txn.failed || txn.bytes_done != txn.req.bytes) {
            txn.req.cb(txn.id, txn.req.addr, {});
        } else {
            txn.req.cb(txn.id, txn.req.addr, std::move(txn.buffer));
        }
    }
    if (!txn.failed && txn.bytes_done == txn.req.bytes) {
        const uint64_t latency = (txn.issue_cycle_first >= txn.submit_cycle)
                                     ? (txn.issue_cycle_first - txn.submit_cycle)
                                     : 0;
        stats_.latency_submit_to_done_cycles[p] += latency;
        stats_.latency_submit_to_done_count[p] += 1;
    }
}

void PeDmaScheduler::failTxn_(RequestId id) {
    auto it = txns_.find(id);
    if (it == txns_.end()) return;
    it->second.failed = true;
    it->second.bytes_issued = it->second.req.bytes;
    if (it->second.inflight_bursts == 0) {
        finalizeTxn_(id);
    }
}

uint16_t PeDmaScheduler::stageScalePermille_(Priority p) const {
    return cfg_.stage_budget_permille[stageIndex_(stage_)][prioIndex_(p)];
}

void PeDmaScheduler::updateQueueDepthStats_() {
    for (size_t p = 0; p < queues_.size(); ++p) {
        uint64_t depth = 0;
        for (const auto& q : queues_[p]) depth += static_cast<uint64_t>(q.size());
        for (const auto& q : overflow_[p]) depth += static_cast<uint64_t>(q.size());
        stats_.queue_depth_cur[p] = depth;
        stats_.queue_depth_max[p] = std::max<uint64_t>(stats_.queue_depth_max[p], depth);
    }
}

}} // namespace SST::SnnDL
