// -*- c++ -*-
//
// BankedSramModel:
// - Observe-only SRAM model for architecture studies.
// - Never stalls or reorders requests; only records pressure/cost statistics.

#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace SST { namespace SnnDL {

struct BankedSramConfig {
    bool enable = false;
    std::string name = "sram";

    // Capacity is used for residency feasibility reporting only.
    uint64_t capacity_bytes = 0;

    // Banking/port geometry.
    uint32_t banks = 1;
    uint32_t ports_per_bank = 1;
    uint64_t bank_interleave_bytes = 4;

    // Access service time used only for predicted pressure cycles.
    uint32_t t_read_cycles = 1;
    uint32_t t_write_cycles = 1;

    // Optional energy model (pJ/access).
    double energy_read_pj = 0.0;
    double energy_write_pj = 0.0;

    // Deterministic Bernoulli-like sampling on access order.
    // 0 => no sampling; n => keep 1/(2^n) accesses and scale statistics by (2^n).
    uint32_t sample_log2 = 0;

    // Conflict cost model:
    // - "sum" (default): per-bank oversubscription costs add up.
    // - "max": cycle cost determined by the max congested bank (GPU shared-memory warp-like).
    std::string conflict_cost_model = "sum";

    // GPU shared-memory broadcast: treat multiple reads to the same address (same bank, same cycle)
    // as a single serviced transaction.
    bool read_broadcast_enable = false;
};

struct BankedSramStats {
    uint64_t reads_total = 0;
    uint64_t writes_total = 0;
    uint64_t bytes_read_total = 0;
    uint64_t bytes_write_total = 0;

    uint64_t bank_conflict_ticks_total = 0;
    uint64_t bank_conflict_events_total = 0;
    uint64_t predicted_extra_cycles_total = 0;
    uint64_t bank_peak_accesses_per_tick = 0;
    uint64_t read_broadcast_elided_total = 0;

    uint64_t resident_bytes_last = 0;
    uint64_t resident_bytes_peak = 0;
    uint64_t capacity_exceeded_events_total = 0;

    double energy_read_pj_total = 0.0;
    double energy_write_pj_total = 0.0;
};

class BankedSramModel {
public:
    BankedSramModel() = default;
    explicit BankedSramModel(const BankedSramConfig& cfg) { configure(cfg); }

    void configure(const BankedSramConfig& cfg);
    void disable();
    const BankedSramConfig& config() const { return cfg_; }

    void reset();

    // Flush current-cycle pressure bookkeeping into accumulated statistics.
    void onClockTick(uint64_t now_cycle);

    // Per-access accounting with address-based bank mapping.
    void noteRead(uint64_t now_cycle, uint64_t addr, size_t bytes);
    void noteWrite(uint64_t now_cycle, uint64_t addr, size_t bytes);

    // Aggregated accounting for bulk loops (e.g. neuron-state sweeps).
    void noteBulkUniform(uint64_t now_cycle,
                         uint64_t reads,
                         uint64_t writes,
                         uint64_t bytes_read,
                         uint64_t bytes_write);

    // Residency bookkeeping for "can this table live on SRAM" studies.
    void noteResidentBytes(uint64_t resident_bytes);

    const BankedSramStats& stats() const { return stats_; }
    uint64_t consumeLastCyclePredictedExtraCycles();
    uint64_t consumeLastCycleConflictTicks();

private:
    void rollCycleIfNeeded_(uint64_t now_cycle);
    void flushCurrentCycle_();
    void addReadAccess_(uint64_t addr, uint64_t scale, uint64_t bytes);
    void addWriteAccess_(uint64_t addr, uint64_t scale, uint64_t bytes);
    bool sampleKeep_();
    uint32_t bankForAddr_(uint64_t addr) const;
    void distributeUniform_(uint64_t accesses, std::vector<uint64_t>& bank_vec);

    BankedSramConfig cfg_{};
    BankedSramStats stats_{};

    enum class ConflictCostModel {
        SumOverBanks,
        MaxOverBanks,
    };
    ConflictCostModel conflict_cost_model_ = ConflictCostModel::SumOverBanks;

    bool cycle_valid_ = false;
    uint64_t cycle_now_ = 0;
    std::vector<uint64_t> cycle_bank_reads_;
    std::vector<uint64_t> cycle_bank_writes_;
    std::vector<std::vector<uint64_t>> cycle_bank_read_addrs_;
    uint32_t bulk_rr_bank_cursor_ = 0;
    uint64_t sample_counter_ = 0;
    uint64_t last_cycle_predicted_extra_cycles_ = 0;
    uint64_t last_cycle_conflict_ticks_ = 0;
};

}} // namespace SST::SnnDL
