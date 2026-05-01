// -*- c++ -*-
//
// PulseSharedLineService:
// - Minimal PE-scoped shared line service registry for experimental PULSE actual path.
// - Keeps physical line service shared while leaving per-consumer callbacks/retire unchanged.

#pragma once

#include <cstddef>
#include <cstdint>
#include <functional>
#include <mutex>
#include <unordered_map>
#include <utility>
#include <vector>

namespace SST { namespace SnnDL {

class PulseSharedLineService final {
public:
    struct ServiceKey {
        uint32_t scope_id = 0;
        uint32_t window_seq = 0;
        uint64_t line_addr = 0;

        bool operator==(const ServiceKey& other) const {
            return scope_id == other.scope_id &&
                   window_seq == other.window_seq &&
                   line_addr == other.line_addr;
        }
    };

    struct JoinResult {
        bool owner = false;
        size_t waiter_count = 0;
        size_t active_entries = 0;
    };

    struct ProbeResult {
        bool active = false;
        size_t waiter_count = 0;
        size_t active_entries = 0;
    };

    using Waiter = std::function<void(bool, uint64_t, const std::vector<uint8_t>&)>;

    static JoinResult joinOrRegister(const ServiceKey& key, Waiter waiter) {
        std::lock_guard<std::mutex> lock(mutex_());
        auto& entry = entries_()[key];
        const bool owner = entry.waiters.empty();
        entry.waiters.push_back(std::move(waiter));
        peak_() = std::max<uint64_t>(peak_(), static_cast<uint64_t>(entries_().size()));

        JoinResult result{};
        result.owner = owner;
        result.waiter_count = entry.waiters.size();
        result.active_entries = entries_().size();
        return result;
    }

    static size_t complete(const ServiceKey& key,
                           bool ok,
                           uint64_t line_addr,
                           const std::vector<uint8_t>& line_bytes) {
        std::vector<Waiter> waiters;
        {
            std::lock_guard<std::mutex> lock(mutex_());
            auto it = entries_().find(key);
            if (it == entries_().end()) return 0;
            waiters = std::move(it->second.waiters);
            entries_().erase(it);
        }

        for (auto& waiter : waiters) {
            if (waiter) waiter(ok, line_addr, line_bytes);
        }
        return waiters.size();
    }

    static size_t activeEntries() {
        std::lock_guard<std::mutex> lock(mutex_());
        return entries_().size();
    }

    static ProbeResult probe(const ServiceKey& key) {
        std::lock_guard<std::mutex> lock(mutex_());
        ProbeResult result{};
        result.active_entries = entries_().size();
        const auto it = entries_().find(key);
        if (it == entries_().end()) return result;
        result.active = true;
        result.waiter_count = it->second.waiters.size();
        return result;
    }

    static uint64_t activePeak() {
        std::lock_guard<std::mutex> lock(mutex_());
        return peak_();
    }

    static void resetForTests() {
        std::lock_guard<std::mutex> lock(mutex_());
        entries_().clear();
        peak_() = 0;
    }

private:
    struct Entry {
        std::vector<Waiter> waiters;
    };

    struct ServiceKeyHash {
        size_t operator()(const ServiceKey& key) const {
            size_t seed = static_cast<size_t>(key.scope_id);
            seed ^= static_cast<size_t>(key.window_seq) + 0x9e3779b9u + (seed << 6) + (seed >> 2);
            seed ^= static_cast<size_t>(key.line_addr) + 0x9e3779b9u + (seed << 6) + (seed >> 2);
            return seed;
        }
    };

    static std::unordered_map<ServiceKey, Entry, ServiceKeyHash>& entries_() {
        static std::unordered_map<ServiceKey, Entry, ServiceKeyHash> entries;
        return entries;
    }

    static std::mutex& mutex_() {
        static std::mutex mutex;
        return mutex;
    }

    static uint64_t& peak_() {
        static uint64_t peak = 0;
        return peak;
    }
};

}} // namespace SST::SnnDL
