// -*- c++ -*-
//
// GasEdgeCollector: per-window edge collection helper extracted from SnnPESubComponent.
// Behavior preserved; only structural decoupling.

#pragma once

#include <cstdint>
#include <cstddef>
#include <unordered_map>
#include <utility>
#include <vector>

#include <sst/core/output.h>

namespace SST { namespace SnnDL {

struct GasEdgeCollector {
    std::unordered_map<uint64_t, uint32_t> curr;
    std::vector<std::pair<uint64_t, uint32_t>> prev;
    size_t prev_iter_idx = 0;
    bool record_stage_warned = false;
    bool record_cond_warned = false;
    bool capacity_warned = false; // 容量溢出仅告警一次（每窗复位）

    size_t currSize() const;
    size_t prevSize() const;
    size_t prevIter() const;
    bool prevEmpty() const;
    void clearWarnings();

    void flipForApply(bool debug, Output* out, int core_id, uint32_t seq);
    bool nextPrev(uint64_t& key, uint32_t& count);
};

}} // namespace SST::SnnDL

