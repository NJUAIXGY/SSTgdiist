// -*- c++ -*-
//
// GasEdgeCollector: per-window edge collection helper extracted from SnnPESubComponent.

#include <algorithm>

#include "GasEdgeCollector.h"

namespace SST { namespace SnnDL {

size_t GasEdgeCollector::currSize() const { return curr.size(); }
size_t GasEdgeCollector::prevSize() const { return prev.size(); }
size_t GasEdgeCollector::prevIter() const { return prev_iter_idx; }
bool GasEdgeCollector::prevEmpty() const { return prev.empty(); }
void GasEdgeCollector::clearWarnings() { record_stage_warned = record_cond_warned = false; }

void GasEdgeCollector::flipForApply(bool debug, Output* out, int, uint32_t seq) {
    if (debug && out && out->getVerboseLevel() >= 2) {
        out->verbose(CALL_INFO, 2, 0,
            "[diag-edges] BeginApply seq=%u edges_curr=%zu\n",
            seq, curr.size());
    }
    prev.clear();
    prev.reserve(curr.size());
    for (const auto& kv : curr) {
        prev.emplace_back(kv.first, kv.second);
    }
    // Deterministic iteration order: stable across runs/threads even if unordered_map
    // insertion order differs (critical for strict-GAS reproducibility under -n multi-thread).
    std::sort(prev.begin(), prev.end(),
              [](const auto& a, const auto& b) { return a.first < b.first; });
    if (debug && out && out->getVerboseLevel() >= 2) {
        out->verbose(CALL_INFO, 2, 0,
            "[diag-edges] BeginApply seq=%u edges_prev=%zu\n",
            seq, prev.size());
    }
    curr.clear();
    prev_iter_idx = 0;
    capacity_warned = false; // 新窗复位
}

bool GasEdgeCollector::nextPrev(uint64_t& key, uint32_t& count) {
    if (prev_iter_idx >= prev.size()) {
        return false;
    }
    key = prev[prev_iter_idx].first;
    count = prev[prev_iter_idx].second;
    ++prev_iter_idx;
    return true;
}

}} // namespace SST::SnnDL
