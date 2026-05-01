// -*- c++ -*-
//
// AccumulatorOps: owns GAS window accumulator state (dense/sparse + spill + shadow verify).
// Behavior is kept identical to historical SnnPESubComponent inline accUpdate_/accReset_.

#include "AccumulatorOps.h"

#include <algorithm>
#include <cmath>

#include <sst/core/output.h>
#include <sst/core/statapi/statbase.h>

namespace SST { namespace SnnDL {

AccumulatorOps::AccumulatorOps(const AccumulatorOpsConfig& cfg) {
    configure(cfg);
}

void AccumulatorOps::configure(const AccumulatorOpsConfig& cfg) {
    cfg_ = cfg;
    dense_enable_ = cfg.dense_enable;
    spill_enable_ = cfg.spill_enable;
    hwm_bytes_ = (cfg.high_watermark_bytes > 0)
        ? cfg.high_watermark_bytes
        : (16ull * 1024ull * 1024ull);
    shadow_verify_enable_ = cfg.shadow_verify_enable && dense_enable_;

    // Reset all state on reconfigure (safe before first use).
    bytes_estimate_ = 0;
    acc_delta_.clear();
    acc_spill_log_.clear();
    acc_shadow_map_.clear();
    shadow_mismatch_logged_ = false;

    if (dense_enable_) {
        acc_dense_.assign(cfg.num_neurons, 0.0f);
        acc_touched_bitmap_.assign(cfg.num_neurons, 0);
        acc_touched_list_.clear();
        acc_touched_list_.reserve(cfg.num_neurons / 10 + 8);
    } else {
        acc_dense_.clear();
        acc_touched_bitmap_.clear();
        acc_touched_list_.clear();
    }
}

void AccumulatorOps::reset() {
    acc_spill_log_.clear();
    bytes_estimate_ = 0;
    if (dense_enable_) {
        for (auto idx : acc_touched_list_) {
            if (idx < acc_dense_.size()) {
                acc_dense_[idx] = 0.0f;
                if (idx < acc_touched_bitmap_.size()) {
                    acc_touched_bitmap_[idx] = 0;
                }
            }
        }
        acc_touched_list_.clear();
        acc_shadow_map_.clear();
        shadow_mismatch_logged_ = false;
    } else {
        acc_delta_.clear();
    }
}

void AccumulatorOps::update(uint32_t post, float dv) {
#ifdef SNNDL_ENABLE_DEBUG_LOG
    if (cfg_.window_read_debug && cfg_.out && std::fabs(dv) > 1e-6f) {
        if (cfg_.out->getVerboseLevel() < 2) {
            // suppress by default
        } else {
            cfg_.out->verbose(CALL_INFO, 2, 0,
            "[diag-delta] core=%d post=%u dv=%.6f\n",
            cfg_.core_id, post, dv);
        }
    }
#endif

    // Spill when above HWM (same rough estimate semantics as legacy path).
    if (spill_enable_ && bytes_estimate_ >= hwm_bytes_) {
        acc_spill_log_.emplace_back(post, dv);
        if (cfg_.stat_spill_records_total) cfg_.stat_spill_records_total->addData(1);
        if (cfg_.stat_spilled_bytes_total) cfg_.stat_spilled_bytes_total->addData(sizeof(float));
        if (cfg_.spill_records_count) (*cfg_.spill_records_count) += 1;
        if (cfg_.spilled_bytes_sum) (*cfg_.spilled_bytes_sum) += sizeof(float);
        return;
    }

    if (dense_enable_) {
        if (post < acc_dense_.size()) {
            acc_dense_[post] += dv;
            if (shadow_verify_enable_) {
                acc_shadow_map_[post] += dv;
            }
            if (post < acc_touched_bitmap_.size() && acc_touched_bitmap_[post] == 0) {
                acc_touched_bitmap_[post] = 1;
                acc_touched_list_.push_back(post);
                if (cfg_.stat_posts_touched_total) cfg_.stat_posts_touched_total->addData(1);
                if (cfg_.posts_touched_count) (*cfg_.posts_touched_count) += 1;
                bytes_estimate_ += 16; // rough per new entry
            }
        }
    } else {
        auto it = acc_delta_.find(post);
        if (it == acc_delta_.end()) {
            acc_delta_[post] = dv;
            bytes_estimate_ += 16; // rough per new entry
            if (cfg_.stat_posts_touched_total) cfg_.stat_posts_touched_total->addData(1);
            if (cfg_.posts_touched_count) (*cfg_.posts_touched_count) += 1;
        } else {
            it->second += dv;
        }
    }

    if (cfg_.stat_apply_updates_total) cfg_.stat_apply_updates_total->addData(1);
    if (cfg_.updates_count) (*cfg_.updates_count) += 1;
    if (cfg_.stat_hwm_bytes_total) cfg_.stat_hwm_bytes_total->addData(bytes_estimate_);
    if (cfg_.hwm_bytes_max && bytes_estimate_ > *cfg_.hwm_bytes_max) {
        *cfg_.hwm_bytes_max = bytes_estimate_;
    }
}

void AccumulatorOps::mergeSpill_() {
    if (acc_spill_log_.empty()) return;
    std::vector<std::pair<uint32_t, float>> spill = std::move(acc_spill_log_);
    acc_spill_log_.clear();

    const bool prev_spill_enable = spill_enable_;
    spill_enable_ = false;

    std::sort(spill.begin(), spill.end(),
              [](const auto& a, const auto& b){ return a.first < b.first; });
    uint32_t curp = UINT32_MAX;
    float sum = 0.0f;
    for (auto& pr : spill) {
        if (pr.first != curp) {
            if (curp != UINT32_MAX) update(curp, sum);
            curp = pr.first;
            sum = pr.second;
        } else {
            sum += pr.second;
        }
    }
    if (curp != UINT32_MAX) update(curp, sum);

    spill_enable_ = prev_spill_enable;
}

void AccumulatorOps::collectSortedPairs(std::vector<std::pair<uint32_t, float>>& out) {
    mergeSpill_();
    if (dense_enable_) {
        if (acc_touched_list_.empty()) return;
        std::vector<uint32_t> posts = acc_touched_list_;
        std::sort(posts.begin(), posts.end());
        for (auto post : posts) {
            if (post < acc_dense_.size()) {
                out.emplace_back(post, acc_dense_[post]);
            }
        }
        return;
    }

    if (acc_delta_.empty()) return;
    std::vector<uint32_t> posts;
    posts.reserve(acc_delta_.size());
    for (auto& kv : acc_delta_) posts.push_back(kv.first);
    std::sort(posts.begin(), posts.end());
    for (auto post : posts) {
        out.emplace_back(post, acc_delta_[post]);
    }
}

void AccumulatorOps::verifyDense(uint32_t seq) {
    if (!(shadow_verify_enable_ && dense_enable_)) return;
    constexpr double kEps = 1e-5;

    auto log_once = [&](const char* reason, uint32_t post, double dense, double reference) {
        if (shadow_mismatch_logged_ || !cfg_.out) return;
        if (cfg_.out->getVerboseLevel() < 2) return;
        cfg_.out->verbose(CALL_INFO, 2, 0,
            "[acc-shadow] core=%u seq=%u %s post=%u dense=%.6f ref=%.6f diff=%.6g\n",
            static_cast<uint32_t>(cfg_.core_id), seq, reason ? reason : "-", post,
            dense, reference, dense - reference);
        shadow_mismatch_logged_ = true;
    };

    for (auto post : acc_touched_list_) {
        double dense = (post < acc_dense_.size()) ? (double)acc_dense_[post] : 0.0;
        double reference = 0.0;
        auto it = acc_shadow_map_.find(post);
        if (it != acc_shadow_map_.end()) {
            reference = (double)it->second;
            acc_shadow_map_.erase(it);
        }
        if (std::fabs(dense - reference) > kEps) {
            log_once("mismatch", post, dense, reference);
        }
    }
    if (!acc_shadow_map_.empty()) {
        auto kv = *acc_shadow_map_.begin();
        log_once("unused", kv.first, 0.0, kv.second);
        acc_shadow_map_.clear();
    }
    shadow_mismatch_logged_ = false;
}

}} // namespace SST::SnnDL
