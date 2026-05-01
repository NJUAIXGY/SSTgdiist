// -*- c++ -*-
//
// PeWeightObjectPlane:
// - Minimal PE-shared owner plane for weight idx/value storage studies.
// - Keeps object ownership and SRAM observability at PerPe scope.

#pragma once

#include <map>
#include <cstddef>
#include <cstdint>
#include <string>
#include <utility>

#include "services/memory/sram_sim/layout/VirtualSramLayout.h"
#include "services/memory/sram_sim/model/BankedSramModel.h"

namespace SST { namespace SnnDL {

class PeWeightObjectPlane {
public:
    enum class AuthorityClass : uint8_t {
        PrivateAuthority = 0,
        SharedMirrorOnly = 1,
        SharedAuthorityActive = 2,
    };

    struct Config {
        bool enable = false;
        bool owner_scope_enable = false;
        bool actual_owner_enable = false;
        bool idx_enable = false;
        bool l0_enable = false;

        uint64_t idx_capacity_bytes = 0;
        uint64_t l0_capacity_bytes = 0;
        uint32_t idx_banks = 16;
        uint32_t l0_banks = 8;
        uint32_t ports_per_bank = 1;
        uint64_t bank_interleave_bytes = 4;
        uint32_t t_read_cycles = 1;
        uint32_t t_write_cycles = 1;
        uint32_t sample_log2 = 0;

        uint64_t idx_base = 0x100000000ull;
        uint64_t l0_base = 0x200000000ull;
        uint64_t l0_slots = (1ull << 20);
    };

    struct StatsSnapshot {
        bool enabled = false;
        bool owner_scope_enable = false;
        bool actual_owner_enable = false;
        bool idx_enabled = false;
        bool l0_enabled = false;
        AuthorityClass idx_authority = AuthorityClass::PrivateAuthority;
        AuthorityClass l0_authority = AuthorityClass::PrivateAuthority;
        BankedSramStats idx_sram{};
        BankedSramStats l0_sram{};
        uint64_t l0_fill_total = 0;
        uint64_t l0_evict_total = 0;
    };

    PeWeightObjectPlane() = default;
    explicit PeWeightObjectPlane(const Config& cfg) { configure(cfg); }

    void configure(const Config& cfg) {
        cfg_ = cfg;
        VirtualSramLayoutConfig layout_cfg{};
        layout_cfg.idx_base = cfg_.idx_base;
        layout_cfg.l0_base = cfg_.l0_base;
        layout_cfg.l0_slots = cfg_.l0_slots;
        layout_.configure(layout_cfg);

        BankedSramConfig idx_cfg{};
        idx_cfg.enable = ownerScopeEnabled() && cfg_.idx_enable;
        idx_cfg.name = "pe_weight_idx_store";
        idx_cfg.capacity_bytes = cfg_.idx_capacity_bytes;
        idx_cfg.banks = cfg_.idx_banks;
        idx_cfg.ports_per_bank = cfg_.ports_per_bank;
        idx_cfg.bank_interleave_bytes = cfg_.bank_interleave_bytes;
        idx_cfg.t_read_cycles = cfg_.t_read_cycles;
        idx_cfg.t_write_cycles = cfg_.t_write_cycles;
        idx_cfg.sample_log2 = cfg_.sample_log2;
        idx_model_.configure(idx_cfg);

        BankedSramConfig l0_cfg{};
        l0_cfg.enable = ownerScopeEnabled() && cfg_.l0_enable;
        l0_cfg.name = "pe_weight_value_store";
        l0_cfg.capacity_bytes = cfg_.l0_capacity_bytes;
        l0_cfg.banks = cfg_.l0_banks;
        l0_cfg.ports_per_bank = cfg_.ports_per_bank;
        l0_cfg.bank_interleave_bytes = cfg_.bank_interleave_bytes;
        l0_cfg.t_read_cycles = cfg_.t_read_cycles;
        l0_cfg.t_write_cycles = cfg_.t_write_cycles;
        l0_cfg.sample_log2 = cfg_.sample_log2;
        l0_model_.configure(l0_cfg);
    }

    const Config& config() const { return cfg_; }
    bool enabled() const { return cfg_.enable; }
    bool ownerScopeEnabled() const { return cfg_.enable && cfg_.owner_scope_enable; }
    bool actualOwnerEnabled() const { return ownerScopeEnabled() && cfg_.actual_owner_enable; }
    bool idxEnabled() const { return ownerScopeEnabled() && cfg_.idx_enable; }
    bool l0Enabled() const { return ownerScopeEnabled() && cfg_.l0_enable; }
    AuthorityClass classifyAuthority(bool plane_enabled) const {
        if (!ownerScopeEnabled() || !plane_enabled) return AuthorityClass::PrivateAuthority;
        if (!actualOwnerEnabled()) return AuthorityClass::SharedMirrorOnly;
        return AuthorityClass::SharedAuthorityActive;
    }

    const VirtualSramLayout& layout() const { return layout_; }
    VirtualSramLayout& layout() { return layout_; }

    BankedSramModel& idxModel() { return idx_model_; }
    const BankedSramModel& idxModel() const { return idx_model_; }
    BankedSramModel& l0Model() { return l0_model_; }
    const BankedSramModel& l0Model() const { return l0_model_; }

    void onClockTick(uint64_t now_cycle) {
        if (idxEnabled()) idx_model_.onClockTick(now_cycle);
        if (l0Enabled()) l0_model_.onClockTick(now_cycle);
    }

    void noteIdxRead(uint64_t now_cycle, uint64_t addr, size_t bytes) {
        if (!idxEnabled()) return;
        idx_model_.noteRead(now_cycle, addr, bytes);
    }

    void noteIdxWrite(uint64_t now_cycle, uint64_t addr, size_t bytes) {
        if (!idxEnabled()) return;
        idx_model_.noteWrite(now_cycle, addr, bytes);
    }

    void noteL0Read(uint64_t now_cycle, uint64_t key) {
        if (!l0Enabled()) return;
        l0_model_.noteRead(now_cycle, layout_.l0SlotAddr(key), sizeof(float));
    }

    void noteL0Write(uint64_t now_cycle, uint64_t key) {
        if (!l0Enabled()) return;
        l0_model_.noteWrite(now_cycle, layout_.l0SlotAddr(key), sizeof(float));
    }

    void noteL0Fill(uint64_t now_cycle, uint64_t key) {
        if (!l0Enabled()) return;
        noteL0Write(now_cycle, key);
        l0_fill_total_ += 1u;
    }

    void noteL0Evict(uint64_t now_cycle, uint64_t key) {
        if (!l0Enabled()) return;
        noteL0Write(now_cycle, key);
        l0_evict_total_ += 1u;
    }

    void noteResidentIdxBytes(uint64_t bytes) {
        if (!idxEnabled()) return;
        idx_model_.noteResidentBytes(bytes);
    }

    void noteResidentL0Bytes(uint64_t bytes) {
        if (!l0Enabled()) return;
        l0_model_.noteResidentBytes(bytes);
    }

    StatsSnapshot snapshotStats() const {
        StatsSnapshot stats{};
        stats.enabled = enabled();
        stats.owner_scope_enable = ownerScopeEnabled();
        stats.actual_owner_enable = actualOwnerEnabled();
        stats.idx_enabled = idxEnabled();
        stats.l0_enabled = l0Enabled();
        stats.idx_authority = classifyAuthority(cfg_.idx_enable);
        stats.l0_authority = classifyAuthority(cfg_.l0_enable);
        stats.idx_sram = idx_model_.stats();
        stats.l0_sram = l0_model_.stats();
        stats.l0_fill_total = l0_fill_total_;
        stats.l0_evict_total = l0_evict_total_;
        return stats;
    }
    void exportStatsToMap(std::map<std::string, uint64_t>& stats,
                          const std::string& prefix) const;

private:
    Config cfg_{};
    VirtualSramLayout layout_{};
    BankedSramModel idx_model_{};
    BankedSramModel l0_model_{};
    uint64_t l0_fill_total_ = 0;
    uint64_t l0_evict_total_ = 0;
};

}} // namespace SST::SnnDL
