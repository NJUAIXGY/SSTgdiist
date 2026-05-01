// -*- c++ -*-
//
// WeightCacheOps: cache helpers extracted from SnnPESubComponent

#include "WeightCacheOps.h"

#include <utility>

namespace SST { namespace SnnDL {

void WeightCacheOps::configure(const Config& cfg, std::function<void(uint64_t)> on_evict) {
    cfg_ = cfg;
    on_evict_ = std::move(on_evict);

    lru_list_.clear();
    lru_map_.clear();

    clock_keys_.clear();
    clock_vals_.clear();
    clock_access_.clear();
    clock_index_.clear();
    clock_hand_ = 0;
    clock_size_ = 0;
    clock_cap_ = 0;

    if (cfg_.use_clock && cfg_.max_entries > 0) {
        clock_cap_ = cfg_.max_entries;
        clock_keys_.resize(clock_cap_);
        clock_vals_.resize(clock_cap_);
        clock_access_.assign(clock_cap_, 0);
        clock_index_.reserve(clock_cap_);
    } else if (!cfg_.use_clock && cfg_.max_entries > 0) {
        lru_map_.reserve(cfg_.max_entries);
    }
}

void WeightCacheOps::reserve(size_t hint_entries) {
    if (cfg_.use_clock) {
        clock_index_.reserve(hint_entries);
        return;
    }
    lru_map_.reserve(hint_entries);
}

bool WeightCacheOps::contains(uint64_t key) const {
    if (cfg_.use_clock) return clock_index_.find(key) != clock_index_.end();
    return lru_map_.find(key) != lru_map_.end();
}

size_t WeightCacheOps::entryCount() const {
    if (cfg_.use_clock) return static_cast<size_t>(clock_size_);
    return lru_map_.size();
}

bool WeightCacheOps::tryGet(uint64_t key, float& out) {
    if (cfg_.disable_cache) return false; // 诊断：强制 miss
    return cfg_.use_clock ? clockGet_(key, out) : lruGet_(key, out);
}

void WeightCacheOps::store(uint64_t key, float value) {
    if (cfg_.use_clock) {
        clockPut_(key, value);
        return;
    }
    lruPut_(key, value);
}

bool WeightCacheOps::lruGet_(uint64_t key, float& out) {
    auto it = lru_map_.find(key);
    if (it == lru_map_.end()) return false;
    lru_list_.erase(it->second.it);
    lru_list_.push_front(key);
    it->second.it = lru_list_.begin();
    out = it->second.value;
    return true;
}

void WeightCacheOps::lruPut_(uint64_t key, float value) {
    auto it = lru_map_.find(key);
    if (it != lru_map_.end()) {
        it->second.value = value;
        lru_list_.erase(it->second.it);
        lru_list_.push_front(key);
        it->second.it = lru_list_.begin();
        return;
    }

    lru_list_.push_front(key);
    CacheEntry entry;
    entry.value = value;
    entry.it = lru_list_.begin();
    lru_map_.emplace(key, entry);

    if (cfg_.max_entries > 0 && lru_map_.size() > cfg_.max_entries) {
        uint64_t victim = lru_list_.back();
        lru_list_.pop_back();
        lru_map_.erase(victim);
        if (on_evict_) on_evict_(victim);
    }
}

bool WeightCacheOps::clockGet_(uint64_t key, float& out) {
    auto it = clock_index_.find(key);
    if (it == clock_index_.end()) return false;
    uint32_t idx = it->second;
    if (idx >= clock_size_) return false;
    clock_access_[idx] = 1;
    out = clock_vals_[idx];
    return true;
}

void WeightCacheOps::clockPut_(uint64_t key, float value) {
    auto it = clock_index_.find(key);
    if (it != clock_index_.end()) {
        uint32_t idx = it->second;
        if (idx < clock_size_) {
            clock_vals_[idx] = value;
            clock_access_[idx] = 1;
            return;
        }
        clock_index_.erase(it);
    }

    if (clock_cap_ == 0) return;

    if (clock_size_ < clock_cap_) {
        uint32_t idx = clock_size_++;
        clock_keys_[idx] = key;
        clock_vals_[idx] = value;
        clock_access_[idx] = 1;
        clock_index_[key] = idx;
        return;
    }

    while (clock_access_[clock_hand_]) {
        clock_access_[clock_hand_] = 0;
        clock_hand_ = (clock_hand_ + 1) % clock_cap_;
    }

    uint32_t idx = clock_hand_;
    uint64_t victim = clock_keys_[idx];
    clock_index_.erase(victim);
    if (on_evict_) on_evict_(victim);
    clock_keys_[idx] = key;
    clock_vals_[idx] = value;
    clock_access_[idx] = 1;
    clock_index_[key] = idx;
    clock_hand_ = (clock_hand_ + 1) % clock_cap_;
}

}} // namespace SST::SnnDL
