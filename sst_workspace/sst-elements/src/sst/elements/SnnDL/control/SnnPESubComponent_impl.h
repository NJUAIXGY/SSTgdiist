// -*- c++ -*-
//
// SnnPESubComponent_impl.h: internal implementation state for SnnPESubComponent (Phase5.2+)
// - Purpose: harden compile-time boundaries by keeping heavy state out of the public control header.
// - This header is ONLY for .cc units; do NOT include from other module public headers.
//
// Phase5.2(A1): absorb StageEventHub into Impl (no separate StageEventHub TU).
//

#pragma once

#include <memory>
#include <cstddef>
#include <cstdint>

#include "SnnPESubComponent.h"

namespace SST { namespace SnnDL {

class GasPhaseController;

struct SnnPESubComponent::Impl {
    SnnPESubComponent* core = nullptr; // non-owning
    std::unique_ptr<GasPhaseController> gas_ctrl_;

    // GAS superstep timing (ns)
    uint64_t t_begin_gather = 0;
    uint64_t t_begin_apply = 0;
    uint64_t t_begin_scatter = 0;
    bool have_begin_gather = false;
    bool have_begin_apply = false;
    bool have_begin_scatter = false;

    void init(SnnPESubComponent* owner) { core = owner; }

    // Statistics reporting (Phase5.4): moved out of public control header.
    void reportMemoryIssue(size_t bytes, bool count_weight_read) const;
    void reportApplyScatter(uint64_t acc_updates, uint64_t posts_touched,
                            uint64_t spikes_emitted, uint64_t hwm_bytes,
                            uint64_t spill_records, uint64_t spilled_bytes) const;
    void reportWindowSpikes(uint32_t seq, uint64_t spikes_emitted) const;
    void reportCacheAccess(bool hit) const;
    void updatePendingPeak(uint32_t outstanding) const;

    void markBeginGather(uint32_t seq);
    void markBeginApply(uint32_t seq);
    void markBeginScatter(uint32_t seq);
    void markEndScatter(uint32_t seq, uint64_t spikes_emitted);
};

}} // namespace SST::SnnDL
