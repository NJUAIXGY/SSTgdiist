// -*- c++ -*-
//
// VirtualSramLayout:
// - Deterministic virtual-address mapping for observe-only SRAM studies.
// - No functional impact: only used by BankedSramModel accounting.

#pragma once

#include <cstdint>

namespace SST { namespace SnnDL {

struct VirtualSramLayoutConfig {
    uint64_t idx_base = 0x100000000ull;
    uint64_t l0_base = 0x200000000ull;
    uint64_t state_vmem_base = 0x300000000ull;
    uint64_t state_refrac_base = 0x400000000ull;
    uint64_t state_last_spike_base = 0x500000000ull;

    // Number of virtual slots used for hashed L0 placement.
    uint64_t l0_slots = (1ull << 20);
};

class VirtualSramLayout {
public:
    VirtualSramLayout() = default;
    explicit VirtualSramLayout(const VirtualSramLayoutConfig& cfg) : cfg_(cfg) { sanitize_(); }

    void configure(const VirtualSramLayoutConfig& cfg) {
        cfg_ = cfg;
        sanitize_();
    }
    const VirtualSramLayoutConfig& config() const { return cfg_; }

    // GCSS index virtual ranges
    uint64_t idxRowBaseAddr(uint32_t row) const {
        return cfg_.idx_base + static_cast<uint64_t>(row) * 32ull;
    }
    uint64_t idxPilotAddr(uint32_t row, uint32_t bucket) const {
        return idxRowBaseAddr(row) + 8ull + static_cast<uint64_t>(bucket);
    }
    uint64_t idxLegacyLookupAddr(uint32_t pre_global, uint32_t post_local) const {
        const uint64_t key = (static_cast<uint64_t>(pre_global) << 32) ^ static_cast<uint64_t>(post_local);
        return cfg_.idx_base + 0x100000ull + hash64_(key) * 8ull;
    }

    // L0 ingress value-cache virtual ranges
    uint64_t l0SlotAddr(uint64_t key) const {
        const uint64_t slot = hash64_(key) % cfg_.l0_slots;
        return cfg_.l0_base + slot * 8ull;
    }

    // Neuron-state virtual ranges
    uint64_t stateVmemAddr(uint32_t neuron_idx) const {
        return cfg_.state_vmem_base + static_cast<uint64_t>(neuron_idx) * sizeof(float);
    }
    uint64_t stateRefracAddr(uint32_t neuron_idx) const {
        return cfg_.state_refrac_base + static_cast<uint64_t>(neuron_idx) * sizeof(uint32_t);
    }
    uint64_t stateLastSpikeAddr(uint32_t neuron_idx) const {
        return cfg_.state_last_spike_base + static_cast<uint64_t>(neuron_idx) * sizeof(uint64_t);
    }

private:
    static uint64_t hash64_(uint64_t x) {
        // SplitMix64
        x += 0x9E3779B97F4A7C15ull;
        x = (x ^ (x >> 30)) * 0xBF58476D1CE4E5B9ull;
        x = (x ^ (x >> 27)) * 0x94D049BB133111EBull;
        return x ^ (x >> 31);
    }

    void sanitize_() {
        if (cfg_.l0_slots == 0) cfg_.l0_slots = 1;
    }

    VirtualSramLayoutConfig cfg_{};
};

}} // namespace SST::SnnDL

