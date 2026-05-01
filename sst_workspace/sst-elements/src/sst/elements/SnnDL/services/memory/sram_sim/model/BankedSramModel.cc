// -*- c++ -*-

#include "services/memory/sram_sim/model/BankedSramModel.h"

#include <algorithm>
#include <cctype>
#include <limits>

namespace SST { namespace SnnDL {

namespace {
static inline uint64_t satAddU64(uint64_t a, uint64_t b) {
    if (std::numeric_limits<uint64_t>::max() - a < b) return std::numeric_limits<uint64_t>::max();
    return a + b;
}
} // namespace

void BankedSramModel::configure(const BankedSramConfig& cfg) {
    cfg_ = cfg;
    if (cfg_.banks == 0) cfg_.banks = 1;
    if (cfg_.ports_per_bank == 0) cfg_.ports_per_bank = 1;
    if (cfg_.bank_interleave_bytes == 0) cfg_.bank_interleave_bytes = 4;
    if (cfg_.sample_log2 > 20) cfg_.sample_log2 = 20;
    if (cfg_.t_read_cycles == 0) cfg_.t_read_cycles = 1;
    if (cfg_.t_write_cycles == 0) cfg_.t_write_cycles = 1;

    {
        std::string model = cfg_.conflict_cost_model;
        std::transform(model.begin(), model.end(), model.begin(),
                       [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        if (model == "max" || model == "warp_max" || model == "gpu_warp" ||
            model == "gpu_sharedmem_warp" || model == "max_over_banks") {
            conflict_cost_model_ = ConflictCostModel::MaxOverBanks;
        } else {
            conflict_cost_model_ = ConflictCostModel::SumOverBanks;
        }
    }
    reset();
}

void BankedSramModel::disable() {
    cfg_.enable = false;
    stats_ = BankedSramStats{};
    cycle_valid_ = false;
    cycle_now_ = 0;
    cycle_bank_reads_.clear();
    cycle_bank_writes_.clear();
    cycle_bank_read_addrs_.clear();
    bulk_rr_bank_cursor_ = 0;
    sample_counter_ = 0;
    last_cycle_predicted_extra_cycles_ = 0;
    last_cycle_conflict_ticks_ = 0;
}

void BankedSramModel::reset() {
    stats_ = BankedSramStats{};
    cycle_valid_ = false;
    cycle_now_ = 0;
    cycle_bank_reads_.assign(cfg_.banks, 0);
    cycle_bank_writes_.assign(cfg_.banks, 0);
    cycle_bank_read_addrs_.clear();
    if (cfg_.read_broadcast_enable) {
        cycle_bank_read_addrs_.assign(cfg_.banks, {});
        for (auto& addrs : cycle_bank_read_addrs_) {
            addrs.reserve(32);
        }
    }
    bulk_rr_bank_cursor_ = 0;
    sample_counter_ = 0;
    last_cycle_predicted_extra_cycles_ = 0;
    last_cycle_conflict_ticks_ = 0;
}

uint64_t BankedSramModel::consumeLastCyclePredictedExtraCycles() {
    const uint64_t out = last_cycle_predicted_extra_cycles_;
    last_cycle_predicted_extra_cycles_ = 0;
    return out;
}

uint64_t BankedSramModel::consumeLastCycleConflictTicks() {
    const uint64_t out = last_cycle_conflict_ticks_;
    last_cycle_conflict_ticks_ = 0;
    return out;
}

void BankedSramModel::onClockTick(uint64_t now_cycle) {
    if (!cfg_.enable) return;
    rollCycleIfNeeded_(now_cycle);
}

void BankedSramModel::noteRead(uint64_t now_cycle, uint64_t addr, size_t bytes) {
    if (!cfg_.enable) return;
    rollCycleIfNeeded_(now_cycle);
    const uint64_t scale = sampleKeep_() ? (1ull << cfg_.sample_log2) : 0ull;
    if (scale == 0) return;
    addReadAccess_(addr, scale, static_cast<uint64_t>(bytes));
}

void BankedSramModel::noteWrite(uint64_t now_cycle, uint64_t addr, size_t bytes) {
    if (!cfg_.enable) return;
    rollCycleIfNeeded_(now_cycle);
    const uint64_t scale = sampleKeep_() ? (1ull << cfg_.sample_log2) : 0ull;
    if (scale == 0) return;
    addWriteAccess_(addr, scale, static_cast<uint64_t>(bytes));
}

void BankedSramModel::noteBulkUniform(uint64_t now_cycle,
                                      uint64_t reads,
                                      uint64_t writes,
                                      uint64_t bytes_read,
                                      uint64_t bytes_write) {
    if (!cfg_.enable) return;
    rollCycleIfNeeded_(now_cycle);

    if (reads > 0) {
        stats_.reads_total = satAddU64(stats_.reads_total, reads);
        stats_.bytes_read_total = satAddU64(stats_.bytes_read_total, bytes_read);
        stats_.energy_read_pj_total += static_cast<double>(reads) * cfg_.energy_read_pj;
        distributeUniform_(reads, cycle_bank_reads_);
    }
    if (writes > 0) {
        stats_.writes_total = satAddU64(stats_.writes_total, writes);
        stats_.bytes_write_total = satAddU64(stats_.bytes_write_total, bytes_write);
        stats_.energy_write_pj_total += static_cast<double>(writes) * cfg_.energy_write_pj;
        distributeUniform_(writes, cycle_bank_writes_);
    }
}

void BankedSramModel::noteResidentBytes(uint64_t resident_bytes) {
    if (!cfg_.enable) return;
    stats_.resident_bytes_last = resident_bytes;
    stats_.resident_bytes_peak = std::max(stats_.resident_bytes_peak, resident_bytes);
    if (cfg_.capacity_bytes > 0 && resident_bytes > cfg_.capacity_bytes) {
        stats_.capacity_exceeded_events_total = satAddU64(stats_.capacity_exceeded_events_total, 1);
    }
}

void BankedSramModel::rollCycleIfNeeded_(uint64_t now_cycle) {
    if (!cycle_valid_) {
        cycle_valid_ = true;
        cycle_now_ = now_cycle;
        return;
    }
    if (now_cycle == cycle_now_) return;
    flushCurrentCycle_();
    cycle_now_ = now_cycle;
    std::fill(cycle_bank_reads_.begin(), cycle_bank_reads_.end(), 0ull);
    std::fill(cycle_bank_writes_.begin(), cycle_bank_writes_.end(), 0ull);
    if (!cycle_bank_read_addrs_.empty()) {
        for (auto& addrs : cycle_bank_read_addrs_) {
            addrs.clear();
        }
    }
}

void BankedSramModel::flushCurrentCycle_() {
    if (!cycle_valid_) return;
    const uint64_t ports = static_cast<uint64_t>(cfg_.ports_per_bank);
    bool has_conflict = false;
    uint64_t cycle_extra_cycles = 0;
    if (conflict_cost_model_ == ConflictCostModel::SumOverBanks) {
        for (uint32_t bank = 0; bank < cfg_.banks; ++bank) {
            const uint64_t r = cycle_bank_reads_[bank];
            const uint64_t w = cycle_bank_writes_[bank];
            const uint64_t total = satAddU64(r, w);
            stats_.bank_peak_accesses_per_tick = std::max(stats_.bank_peak_accesses_per_tick, total);

            if (total <= ports) continue;
            has_conflict = true;

            const uint64_t over = total - ports;
            stats_.bank_conflict_events_total = satAddU64(stats_.bank_conflict_events_total, over);

            const uint64_t weighted_cost = satAddU64(
                r * static_cast<uint64_t>(cfg_.t_read_cycles),
                w * static_cast<uint64_t>(cfg_.t_write_cycles));
            const uint64_t avg_cost = (weighted_cost + total - 1ull) / total;
            const uint64_t extra_cycles = over * std::max<uint64_t>(1ull, avg_cost);
            stats_.predicted_extra_cycles_total = satAddU64(stats_.predicted_extra_cycles_total, extra_cycles);
            cycle_extra_cycles = satAddU64(cycle_extra_cycles, extra_cycles);
        }
    } else {
        uint64_t baseline_cycles = 0;
        uint64_t max_required_cycles = 0;
        uint64_t cycle_conflict_events = 0;
        for (uint32_t bank = 0; bank < cfg_.banks; ++bank) {
            const uint64_t r = cycle_bank_reads_[bank];
            const uint64_t w = cycle_bank_writes_[bank];
            const uint64_t total = satAddU64(r, w);
            stats_.bank_peak_accesses_per_tick = std::max(stats_.bank_peak_accesses_per_tick, total);
            if (total == 0) continue;

            const uint64_t weighted_cost = satAddU64(
                r * static_cast<uint64_t>(cfg_.t_read_cycles),
                w * static_cast<uint64_t>(cfg_.t_write_cycles));
            uint64_t avg_cost = (weighted_cost + total - 1ull) / total;
            avg_cost = std::max<uint64_t>(1ull, avg_cost);
            baseline_cycles = std::max<uint64_t>(baseline_cycles, avg_cost);

            const uint64_t rounds = (total + ports - 1ull) / ports;
            const uint64_t required_cycles = rounds * avg_cost;
            max_required_cycles = std::max<uint64_t>(max_required_cycles, required_cycles);

            if (total > ports) {
                has_conflict = true;
                cycle_conflict_events = satAddU64(cycle_conflict_events, total - ports);
            }
        }

        if (has_conflict) {
            stats_.bank_conflict_events_total = satAddU64(stats_.bank_conflict_events_total, cycle_conflict_events);
        }
        if (max_required_cycles > baseline_cycles) {
            cycle_extra_cycles = max_required_cycles - baseline_cycles;
            stats_.predicted_extra_cycles_total = satAddU64(stats_.predicted_extra_cycles_total, cycle_extra_cycles);
        }
    }
    if (has_conflict) {
        stats_.bank_conflict_ticks_total = satAddU64(stats_.bank_conflict_ticks_total, 1);
    }
    last_cycle_predicted_extra_cycles_ = cycle_extra_cycles;
    last_cycle_conflict_ticks_ = has_conflict ? 1ull : 0ull;
}

void BankedSramModel::addReadAccess_(uint64_t addr, uint64_t scale, uint64_t bytes) {
    const uint32_t bank = bankForAddr_(addr);
    if (cfg_.read_broadcast_enable && bank < cycle_bank_read_addrs_.size()) {
        auto& addrs = cycle_bank_read_addrs_[bank];
        if (std::find(addrs.begin(), addrs.end(), addr) != addrs.end()) {
            stats_.read_broadcast_elided_total = satAddU64(stats_.read_broadcast_elided_total, scale);
            return;
        }
        addrs.push_back(addr);
    }
    stats_.reads_total = satAddU64(stats_.reads_total, scale);
    stats_.bytes_read_total = satAddU64(stats_.bytes_read_total, bytes * scale);
    stats_.energy_read_pj_total += static_cast<double>(scale) * cfg_.energy_read_pj;
    cycle_bank_reads_[bank] = satAddU64(cycle_bank_reads_[bank], scale);
}

void BankedSramModel::addWriteAccess_(uint64_t addr, uint64_t scale, uint64_t bytes) {
    stats_.writes_total = satAddU64(stats_.writes_total, scale);
    stats_.bytes_write_total = satAddU64(stats_.bytes_write_total, bytes * scale);
    stats_.energy_write_pj_total += static_cast<double>(scale) * cfg_.energy_write_pj;
    const uint32_t bank = bankForAddr_(addr);
    cycle_bank_writes_[bank] = satAddU64(cycle_bank_writes_[bank], scale);
}

bool BankedSramModel::sampleKeep_() {
    if (cfg_.sample_log2 == 0) return true;
    const uint64_t mask = (1ull << cfg_.sample_log2) - 1ull;
    const bool keep = ((sample_counter_ & mask) == 0ull);
    sample_counter_ = satAddU64(sample_counter_, 1);
    return keep;
}

uint32_t BankedSramModel::bankForAddr_(uint64_t addr) const {
    const uint64_t interleave = std::max<uint64_t>(1ull, cfg_.bank_interleave_bytes);
    const uint64_t line = addr / interleave;
    return static_cast<uint32_t>(line % static_cast<uint64_t>(cfg_.banks));
}

void BankedSramModel::distributeUniform_(uint64_t accesses, std::vector<uint64_t>& bank_vec) {
    if (accesses == 0 || bank_vec.empty()) return;
    const uint64_t banks = static_cast<uint64_t>(bank_vec.size());
    const uint64_t q = accesses / banks;
    const uint64_t r = accesses % banks;

    if (q > 0) {
        for (uint64_t bank = 0; bank < banks; ++bank) {
            bank_vec[bank] = satAddU64(bank_vec[bank], q);
        }
    }
    for (uint64_t i = 0; i < r; ++i) {
        const uint32_t bank = static_cast<uint32_t>((static_cast<uint64_t>(bulk_rr_bank_cursor_) + i) % banks);
        bank_vec[bank] = satAddU64(bank_vec[bank], 1);
    }
    bulk_rr_bank_cursor_ = static_cast<uint32_t>((static_cast<uint64_t>(bulk_rr_bank_cursor_) + r) % banks);
}

}} // namespace SST::SnnDL
