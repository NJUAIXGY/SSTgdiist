// -*- c++ -*-
//
// WeightCacheOps: cache helpers extracted from SnnPESubComponent
// Behavior preserved; provides accessor-based operations for LRU/clock caches.

#pragma once

#include <cstddef>
#include <cstdint>
#include <functional>
#include <list>
#include <unordered_map>
#include <vector>

namespace SST { namespace SnnDL {

struct WeightCacheOps {
    struct Config {
        uint32_t max_entries = 0;   // 0 表示不做 LRU 淘汰；clock 模式下 0 表示禁用
        bool use_clock = false;     // true 使用 clock-cache；false 使用 LRU-cache
        bool disable_cache = false; // true 时强制 miss（诊断）
    };

    WeightCacheOps() = default;

    void configure(const Config& cfg, std::function<void(uint64_t)> on_evict = {});
    void reserve(size_t hint_entries);

    bool contains(uint64_t key) const;
    size_t entryCount() const;
    bool tryGet(uint64_t key, float& out);
    void store(uint64_t key, float value);

private:
    struct CacheEntry {
        float value = 0.0f;
        std::list<uint64_t>::iterator it;
    };

    bool lruGet_(uint64_t key, float& out);
    void lruPut_(uint64_t key, float value);
    bool clockGet_(uint64_t key, float& out);
    void clockPut_(uint64_t key, float value);

    Config cfg_{};
    std::function<void(uint64_t)> on_evict_;

    // LRU cache
    std::list<uint64_t> lru_list_;
    std::unordered_map<uint64_t, CacheEntry> lru_map_;

    // Clock cache
    std::vector<uint64_t> clock_keys_;
    std::vector<float> clock_vals_;
    std::vector<uint8_t> clock_access_;
    std::unordered_map<uint64_t, uint32_t> clock_index_;
    uint32_t clock_hand_ = 0;
    uint32_t clock_size_ = 0;
    uint32_t clock_cap_ = 0;
};

}} // namespace SST::SnnDL
