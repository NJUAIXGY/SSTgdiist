// -*- c++ -*-
//
// P0B Credit Policy (experimental):
// - Budgeted, step-level global apply_bank_credit redistribution across PEs.
// - Designed for "finite baseline credit" experiments:
//   * Start from base_credit for all PEs;
//   * Raise top-k critical PEs toward credit_hi;
//   * Compensate by dropping least-critical PEs toward credit_lo so that
//     sum(credits) == N * base_credit (exact, via per-credit unit adjustments).
//
// Notes:
// - This is a pure policy helper (header-only) and does not touch SST APIs.
// - Missing telemetry (0 ns) will keep that PE at base_credit.
//

#pragma once

#include <algorithm>
#include <cstdint>
#include <vector>

namespace SST { namespace SnnDL {

struct P0BCreditPolicyConfig {
    uint32_t base_credit = 1;
    uint32_t credit_lo = 1;
    uint32_t credit_hi = 2;
    uint32_t top_k = 0;
    // Only consider a PE for "raise" if apply/total >= threshold.
    // 0 means "no filter".
    uint32_t apply_ratio_min_permille = 0; // [0,1000]
    // Rank metric for criticality: 1=apply_ns, 0=total_ns.
    bool rank_by_apply = true;
};

struct P0BCreditPolicyDebug {
    std::vector<int> raised_pe_indices;
    std::vector<int> dropped_pe_indices;
    uint64_t budget_target = 0;
    uint64_t budget_actual = 0;
};

inline std::vector<uint32_t> computeP0BBudgetedCredits(
    const std::vector<uint64_t>& step_total_ns,
    const std::vector<uint64_t>& step_apply_ns,
    const P0BCreditPolicyConfig& cfg_in,
    P0BCreditPolicyDebug* dbg_out)
{
    const size_t n = step_total_ns.size();
    std::vector<uint32_t> credits(n, 1);
    if (n == 0) return credits;

    P0BCreditPolicyConfig cfg = cfg_in;
    if (cfg.base_credit == 0) cfg.base_credit = 1;
    if (cfg.credit_lo == 0) cfg.credit_lo = 1;
    if (cfg.credit_hi < cfg.base_credit) cfg.credit_hi = cfg.base_credit;
    if (cfg.credit_lo > cfg.base_credit) cfg.credit_lo = cfg.base_credit;
    if (cfg.apply_ratio_min_permille > 1000u) cfg.apply_ratio_min_permille = 1000u;

    for (size_t i = 0; i < n; ++i) credits[i] = cfg.base_credit;

    if (cfg.top_k == 0 || cfg.credit_hi == cfg.base_credit) {
        if (dbg_out) {
            dbg_out->raised_pe_indices.clear();
            dbg_out->dropped_pe_indices.clear();
            dbg_out->budget_target = static_cast<uint64_t>(n) * static_cast<uint64_t>(cfg.base_credit);
            dbg_out->budget_actual = dbg_out->budget_target;
        }
        return credits;
    }

    struct Item {
        uint64_t metric = 0;
        uint64_t total_ns = 0;
        uint64_t apply_ns = 0;
        int idx = -1;
    };

    std::vector<Item> raise_cands;
    raise_cands.reserve(n);
    for (size_t i = 0; i < n; ++i) {
        const uint64_t total = step_total_ns[i];
        const uint64_t apply = (i < step_apply_ns.size()) ? step_apply_ns[i] : 0;
        const uint64_t metric = cfg.rank_by_apply ? apply : total;
        if (metric == 0) continue;
        if (cfg.apply_ratio_min_permille > 0 && total > 0) {
            const uint64_t ratio = (apply * 1000ull) / total;
            if (ratio < static_cast<uint64_t>(cfg.apply_ratio_min_permille)) continue;
        }
        raise_cands.push_back(Item{metric, total, apply, static_cast<int>(i)});
    }
    std::sort(raise_cands.begin(), raise_cands.end(),
              [](const Item& a, const Item& b) {
                  if (a.metric != b.metric) return a.metric > b.metric;
                  return a.idx < b.idx;
              });

    const uint32_t k_raise =
        std::min<uint32_t>(cfg.top_k, static_cast<uint32_t>(raise_cands.size()));

    std::vector<uint8_t> is_raised(n, 0);
    std::vector<int> raise_list;
    raise_list.reserve(k_raise);
    for (uint32_t j = 0; j < k_raise; ++j) {
        const int idx = raise_cands[j].idx;
        if (idx < 0) continue;
        if (static_cast<size_t>(idx) >= n) continue;
        is_raised[static_cast<size_t>(idx)] = 1;
        raise_list.push_back(idx);
        credits[static_cast<size_t>(idx)] = cfg.credit_hi;
    }

    // Target budget: keep the sum equal to baseline (N * base_credit).
    const uint64_t budget_target =
        static_cast<uint64_t>(n) * static_cast<uint64_t>(cfg.base_credit);
    uint64_t budget_actual = 0;
    for (auto c : credits) budget_actual += static_cast<uint64_t>(c);

    int64_t extra = static_cast<int64_t>(budget_actual) - static_cast<int64_t>(budget_target);
    if (extra <= 0) {
        if (dbg_out) {
            dbg_out->raised_pe_indices = raise_list;
            dbg_out->dropped_pe_indices.clear();
            dbg_out->budget_target = budget_target;
            dbg_out->budget_actual = budget_actual;
        }
        return credits;
    }

    // Drop candidates: fastest (small metric) PEs excluding raised.
    std::vector<Item> drop_cands;
    drop_cands.reserve(n);
    for (size_t i = 0; i < n; ++i) {
        if (is_raised[i]) continue;
        const uint64_t total = step_total_ns[i];
        const uint64_t apply = (i < step_apply_ns.size()) ? step_apply_ns[i] : 0;
        const uint64_t metric = cfg.rank_by_apply ? apply : total;
        if (metric == 0) continue;
        drop_cands.push_back(Item{metric, total, apply, static_cast<int>(i)});
    }
    std::sort(drop_cands.begin(), drop_cands.end(),
              [](const Item& a, const Item& b) {
                  if (a.metric != b.metric) return a.metric < b.metric;
                  return a.idx < b.idx;
              });

    std::vector<int> drop_list;
    drop_list.reserve(drop_cands.size());
    for (const auto& it : drop_cands) drop_list.push_back(it.idx);

    auto apply_drop = [&](int idx, uint32_t floor) {
        if (extra <= 0) return;
        if (idx < 0 || static_cast<size_t>(idx) >= n) return;
        const uint32_t cur = credits[static_cast<size_t>(idx)];
        if (cur <= floor) return;
        const uint32_t cap = cur - floor;
        const uint32_t d = std::min<uint32_t>(cap, static_cast<uint32_t>(extra));
        credits[static_cast<size_t>(idx)] = cur - d;
        extra -= static_cast<int64_t>(d);
    };

    // 1) Prefer dropping non-raised PEs down to credit_lo.
    for (int idx : drop_list) {
        if (extra <= 0) break;
        apply_drop(idx, cfg.credit_lo);
    }
    // 2) If still extra, retract some raised credits back down toward base_credit.
    for (auto it = raise_list.rbegin(); it != raise_list.rend(); ++it) {
        if (extra <= 0) break;
        apply_drop(*it, cfg.base_credit);
    }

    if (dbg_out) {
        dbg_out->raised_pe_indices = raise_list;
        dbg_out->dropped_pe_indices = drop_list;
        dbg_out->budget_target = budget_target;
        uint64_t sum = 0;
        for (auto c : credits) sum += static_cast<uint64_t>(c);
        dbg_out->budget_actual = sum;
    }
    return credits;
}

}} // namespace SST::SnnDL

