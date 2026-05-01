// -*- c++ -*-
//
// StreamWorkload: 非 SNN 的通用验证负载（通信 + 内存 read-after-write 校验）
// - 只依赖 IMemoryAccess(addr↔bytes) 与 INocTransport(NocPacketEvent)
// - 不触碰 Spike/GAS/权重语义
//

#pragma once

#include <cstddef>
#include <cstdint>
#include <unordered_map>
#include <vector>

#include "ICoreWorkload.h"

namespace SST { namespace SnnDL {

class IMemoryAccess;
class INocTransport;
class NocPacketEvent;

class StreamWorkload final : public ICoreWorkload {
public:
    enum class SemanticMemoryKind : uint8_t {
        Legacy = 0,
        MetadataLookup = 1,
        SynapseGather = 2,
        StreamRegion = 3,
        WritebackRegion = 4,
    };

    struct SemanticMemoryConfig {
        bool enable = false;
        uint64_t base_addr = 0;
        uint64_t period_cycles = 100;
        uint64_t region_bytes = 0;
        uint32_t req_bytes = 64;
        uint32_t stride_bytes = 64;
    };

    struct SemanticMemoryDemand {
        uint64_t metadata_lookup_demands = 0;
        uint64_t synapse_gather_demands = 0;
        uint64_t stream_region_demands = 0;
        uint64_t writeback_region_demands = 0;

        bool empty() const {
            return metadata_lookup_demands == 0 &&
                   synapse_gather_demands == 0 &&
                   stream_region_demands == 0 &&
                   writeback_region_demands == 0;
        }
    };

    struct Config {
        bool mem_enable = true;
        uint64_t mem_period_cycles = 100;
        uint64_t mem_region_bytes = 4096;
        uint32_t mem_req_bytes = 64;
        uint32_t mem_stride_bytes = 64;
        uint32_t mem_max_outstanding = 16;
        bool semantic_memory_enable = false;
        bool semantic_memory_demand_driven_enable = false;
        SemanticMemoryConfig metadata_lookup{};
        SemanticMemoryConfig synapse_gather{};
        SemanticMemoryConfig stream_region{};
        SemanticMemoryConfig writeback_region{};

        bool comm_enable = true;
        uint64_t comm_period_cycles = 1000;
        uint32_t comm_payload_bytes = 64;

        bool strict = true;
        uint64_t seed_base = 0;
    };

    StreamWorkload() = default;
    explicit StreamWorkload(const Config& cfg) : cfg_(cfg) {}

    void configureFromParams(const SST::Params& params) override;
    void bindRuntime(const Runtime& rt) override;
    void enqueueSemanticDemand(const SemanticMemoryDemand& demand);

    // Returns true if this cycle performed any work.
    bool onClockTick(uint64_t now_cycle) override;

    // Returns true if packet consumed (caller should not delete). Always consumes in stream mode.
    bool deliverPacket(NocPacketEvent* packet) override;

    bool hasWork() const override;
    double getUtilization() const override;
    void getStatistics(std::map<std::string, uint64_t>& stats) const override;

private:
    struct MemReq {
        uint64_t addr = 0;
        uint32_t seq = 0;
        uint32_t bytes = 0;
        bool is_read = false;
        SemanticMemoryKind kind = SemanticMemoryKind::Legacy;
    };

    struct SemanticMemoryState {
        uint64_t last_issue_cycle = 0;
        uint64_t next_offset = 0;
        uint32_t seq = 0;
    };

    static uint32_t crc32_ieee_(const uint8_t* data, size_t len);
    static uint64_t splitmix64_next_(uint64_t& x);
    static void write_u16_le_(std::vector<uint8_t>& out, uint16_t v);
    static void write_u32_le_(std::vector<uint8_t>& out, uint32_t v);
    static bool read_u16_le_(const std::vector<uint8_t>& buf, size_t off, uint16_t& out);
    static bool read_u32_le_(const std::vector<uint8_t>& buf, size_t off, uint32_t& out);
    static bool check_expected_bytes_(uint64_t seed_base,
                                      uint32_t node_id,
                                      uint32_t core_id,
                                      uint64_t addr,
                                      uint32_t seq,
                                      SemanticMemoryKind kind,
                                      const std::vector<uint8_t>& got);
    static const char* semanticKindKey_(SemanticMemoryKind kind);

    inline void reportMemIssue_(size_t bytes) const {
        if (rt_.reporting.report_mem_issue) {
            rt_.reporting.report_mem_issue(rt_.reporting.ctx, bytes);
        }
    }
    void noteMemoryIssue_(SemanticMemoryKind kind, size_t bytes, bool is_read);
    bool issueLegacyMemoryRequest_(uint64_t now_cycle);
    bool issueSemanticMemoryRequest_(
        uint64_t now_cycle,
        SemanticMemoryKind kind,
        const SemanticMemoryConfig& cfg,
        SemanticMemoryState& state);
    bool issueDemandDrivenSemanticMemoryRequest_(
        uint64_t now_cycle,
        SemanticMemoryKind kind,
        const SemanticMemoryConfig& cfg,
        SemanticMemoryState& state,
        uint64_t& pending_demands);
    bool hasSemanticMemoryWork_() const;
    bool hasPendingSemanticDemand_() const;

    Config cfg_{};
    Runtime rt_{};

    uint64_t last_mem_issue_cycle_ = 0;
    uint64_t last_comm_cycle_ = 0;
    uint32_t mem_seq_ = 0;
    uint32_t pkt_seq_ = 0;
    uint64_t next_offset_ = 0;
    SemanticMemoryState metadata_lookup_state_{};
    SemanticMemoryState synapse_gather_state_{};
    SemanticMemoryState stream_region_state_{};
    SemanticMemoryState writeback_region_state_{};
    uint64_t pending_metadata_lookup_demands_ = 0;
    uint64_t pending_synapse_gather_demands_ = 0;
    uint64_t pending_stream_region_demands_ = 0;
    uint64_t pending_writeback_region_demands_ = 0;

    std::unordered_map<uint64_t, MemReq> mem_inflight_;

    // Lightweight counters for utilization & activity reporting.
    uint64_t total_cycles_ = 0;
    uint64_t active_cycles_ = 0;
    uint64_t memory_requests_ = 0;

    // Stream counters exported via getStatistics() (so MultiCorePE can aggregate them to mesh_stats.csv).
    uint64_t stream_mem_writes_issued_total_ = 0;
    uint64_t stream_mem_reads_issued_total_ = 0;
    uint64_t stream_mem_bytes_written_total_ = 0;
    uint64_t stream_mem_bytes_read_total_ = 0;
    uint64_t metadata_lookup_writes_issued_total_ = 0;
    uint64_t metadata_lookup_reads_issued_total_ = 0;
    uint64_t metadata_lookup_bytes_written_total_ = 0;
    uint64_t metadata_lookup_bytes_read_total_ = 0;
    uint64_t synapse_gather_writes_issued_total_ = 0;
    uint64_t synapse_gather_reads_issued_total_ = 0;
    uint64_t synapse_gather_bytes_written_total_ = 0;
    uint64_t synapse_gather_bytes_read_total_ = 0;
    uint64_t stream_region_writes_issued_total_ = 0;
    uint64_t stream_region_reads_issued_total_ = 0;
    uint64_t stream_region_bytes_written_total_ = 0;
    uint64_t stream_region_bytes_read_total_ = 0;
    uint64_t writeback_region_writes_issued_total_ = 0;
    uint64_t writeback_region_reads_issued_total_ = 0;
    uint64_t writeback_region_bytes_written_total_ = 0;
    uint64_t writeback_region_bytes_read_total_ = 0;
};

}} // namespace SST::SnnDL
