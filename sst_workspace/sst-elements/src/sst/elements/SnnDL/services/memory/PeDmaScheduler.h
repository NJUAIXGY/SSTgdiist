// -*- c++ -*-

#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <limits>
#include <unordered_map>
#include <vector>

#include "api/IDmaTaggedAccess.h"
#include "api/IMemoryAccess.h"

namespace SST { namespace SnnDL {

class PeDmaScheduler {
public:
    using RequestId = IMemoryAccess::RequestId;
    using Priority = IDmaTaggedAccess::Priority;
    using Tag = IDmaTaggedAccess::Tag;

    enum class Stage : uint8_t {
        Gather = 0,
        Apply = 1,
        Scatter = 2,
        Idle = 3,
    };

    struct Config {
        enum class OverflowPolicy : uint8_t {
            Block = 0,
            FailFast = 1,
        };

        size_t num_cores = 1;
        uint64_t bytes_per_cycle = 0;
        uint32_t read_engines = 0;
        uint32_t max_inflight = 0;
        uint32_t queue_depth = 0;
        OverflowPolicy overflow_policy = OverflowPolicy::Block;
        uint64_t burst_bytes = 0;
        uint32_t setup_cycles = 0;
        uint32_t backend_reject_retry_cycles = 8192;
        uint64_t inflight_timeout_cycles = 50000;
        uint32_t channels = 1;
        uint64_t channel_bytes_per_cycle = 0;
        uint64_t channel_interleave_bytes = 256;
        std::array<std::array<uint16_t, 4>, 4> stage_budget_permille{};

        Config();
    };

    struct Stats {
        uint64_t issue_reqs_total = 0;
        uint64_t issue_bytes_total = 0;
        std::array<uint64_t, 4> queue_depth_cur{};
        std::array<uint64_t, 4> queue_depth_max{};
        uint64_t inflight_cur = 0;
        uint64_t inflight_max = 0;
        uint64_t stall_cycles_budget = 0;
        uint64_t stall_cycles_engine = 0;
        uint64_t stall_cycles_inflight = 0;
        uint64_t stall_cycles_stage_gate = 0;
        uint64_t stall_cycles_queue_full = 0;
        std::array<uint64_t, 4> latency_submit_to_done_cycles{};
        std::array<uint64_t, 4> latency_submit_to_done_count{};
    };

    struct Request {
        uint32_t core_id = 0;
        uint64_t addr = 0;
        size_t bytes = 0;
        Tag tag = 0;
        Priority priority = Priority::P1;
        IMemoryAccess::ReadCallback cb;
    };

    explicit PeDmaScheduler(const Config& cfg = Config{});

    void registerCoreBackend(uint32_t core_id, IMemoryAccess* backend);

    RequestId submitRead(Request req);
    void setStage(Stage stage, uint32_t seq);
    void onCoreTickEnd(uint64_t now_cycle, uint32_t core_id);

    size_t pendingSizeForCore(uint32_t core_id) const;
    Stats snapshotStats() const { return stats_; }
    const Config& config() const { return cfg_; }

private:
    struct DmaTxn {
        RequestId id = 0;
        Request req{};
        uint64_t submit_cycle = 0;
        uint64_t ready_cycle = 0;
        uint64_t issue_cycle_first = 0;
        uint64_t last_progress_cycle = 0;
        size_t bytes_issued = 0;
        size_t bytes_done = 0;
        size_t inflight_bursts = 0;
        uint32_t backend_reject_streak = 0;
        bool failed = false;
        std::vector<uint8_t> buffer{};
    };

    using QueueMatrix = std::array<std::vector<std::deque<RequestId>>, 4>;

    static size_t prioIndex_(Priority p) { return static_cast<size_t>(p); }
    static size_t stageIndex_(Stage s) { return static_cast<size_t>(s); }

    void initQueues_();
    void serviceCycle_(uint64_t now_cycle);
    void expireInflightTxns_(uint64_t now_cycle);
    void promoteOverflow_();
    bool issueOne_(uint64_t now_cycle,
                   uint64_t& bytes_left,
                   uint64_t& engines_left,
                   std::array<uint64_t, 4>& prio_budget_left,
                   std::vector<uint64_t>& channel_budget_left);
    uint64_t computeBurstBytes_(const DmaTxn& txn, uint64_t bytes_left) const;
    uint32_t channelForAddr_(uint64_t addr) const;
    void onBurstResp_(RequestId id,
                      size_t offset,
                      size_t requested_bytes,
                      uint64_t addr,
                      std::vector<uint8_t>&& data);
    void finalizeTxn_(RequestId id);
    void failTxn_(RequestId id);
    uint16_t stageScalePermille_(Priority p) const;
    void updateQueueDepthStats_();

    Config cfg_{};
    Stage stage_ = Stage::Gather;
    uint32_t stage_seq_ = 0;
    uint64_t next_req_id_ = 1;
    uint64_t barrier_cycle_ = std::numeric_limits<uint64_t>::max();
    uint64_t barrier_serviced_cycle_ = std::numeric_limits<uint64_t>::max();
    std::vector<bool> barrier_seen_{};
    size_t barrier_seen_count_ = 0;
    std::vector<IMemoryAccess*> backends_{};
    std::vector<size_t> per_core_pending_{};
    QueueMatrix queues_{};
    QueueMatrix overflow_{};
    std::array<size_t, 4> rr_cursor_{};
    size_t queued_total_ = 0;
    size_t overflow_total_ = 0;
    size_t inflight_total_ = 0;
    std::unordered_map<RequestId, DmaTxn> txns_{};
    Stats stats_{};
};

}} // namespace SST::SnnDL
