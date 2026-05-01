// -*- c++ -*-

#include <sst/core/sst_config.h>

#include "workload/stream/StreamWorkload.h"

#include <sst/core/output.h>
#include <sst/core/params.h>
#include <sst/core/statapi/stataccumulator.h>

#include "ICoreWorkload.h"
#include "IMemoryAccess.h"
#include "INocTransport.h"
#include "NocPacketEvent.h"

#include <algorithm>
#include <cctype>
#include <cstring>

namespace SST { namespace SnnDL {

namespace {

constexpr uint8_t kStreamMagic[8] = {'S','N','N','D','L','S','T','R'};
constexpr uint16_t kStreamVersion = 1;

enum class StreamMsgType : uint16_t {
    Data = 1,
};

} // namespace

void StreamWorkload::configureFromParams(const SST::Params& params) {
    cfg_.mem_enable = params.find<int>("stream_mem_enable", cfg_.mem_enable ? 1 : 0) != 0;
    cfg_.mem_period_cycles = params.find<uint64_t>("stream_mem_period_cycles", cfg_.mem_period_cycles);
    cfg_.mem_region_bytes = params.find<uint64_t>("stream_mem_region_bytes", cfg_.mem_region_bytes);
    cfg_.mem_req_bytes = params.find<uint32_t>("stream_mem_req_bytes", cfg_.mem_req_bytes);
    cfg_.mem_stride_bytes = params.find<uint32_t>("stream_mem_stride_bytes", cfg_.mem_stride_bytes);
    cfg_.mem_max_outstanding = params.find<uint32_t>("stream_mem_max_outstanding", cfg_.mem_max_outstanding);
    cfg_.semantic_memory_enable = params.find<int>("semantic_memory_enable", cfg_.semantic_memory_enable ? 1 : 0) != 0;
    cfg_.semantic_memory_demand_driven_enable =
        params.find<int>("semantic_memory_demand_driven_enable",
                         cfg_.semantic_memory_demand_driven_enable ? 1 : 0) != 0;
    cfg_.metadata_lookup.enable = params.find<int>(
        "metadata_lookup_enable",
        (cfg_.semantic_memory_enable && cfg_.mem_enable) ? 1 : 0) != 0;
    cfg_.metadata_lookup.base_addr = params.find<uint64_t>("metadata_base_addr", 0);
    cfg_.metadata_lookup.period_cycles = params.find<uint64_t>(
        "metadata_lookup_period_cycles",
        cfg_.mem_period_cycles);
    cfg_.metadata_lookup.region_bytes = params.find<uint64_t>(
        "metadata_region_bytes",
        params.find<uint64_t>("memory_semantic_slot_bytes", cfg_.mem_region_bytes));
    cfg_.metadata_lookup.req_bytes = params.find<uint32_t>(
        "metadata_lookup_req_bytes",
        std::min<uint32_t>(cfg_.mem_req_bytes, 16u));
    cfg_.metadata_lookup.stride_bytes = params.find<uint32_t>(
        "metadata_lookup_stride_bytes",
        cfg_.metadata_lookup.req_bytes);
    cfg_.synapse_gather.enable = params.find<int>(
        "synapse_gather_enable",
        (cfg_.semantic_memory_enable && cfg_.mem_enable) ? 1 : 0) != 0;
    cfg_.synapse_gather.base_addr = params.find<uint64_t>("gather_base_addr", 0);
    cfg_.synapse_gather.period_cycles = params.find<uint64_t>(
        "synapse_gather_period_cycles",
        cfg_.mem_period_cycles);
    cfg_.synapse_gather.region_bytes = params.find<uint64_t>(
        "gather_region_bytes",
        params.find<uint64_t>("memory_semantic_slot_bytes", cfg_.mem_region_bytes));
    cfg_.synapse_gather.req_bytes = params.find<uint32_t>(
        "synapse_gather_req_bytes",
        cfg_.mem_req_bytes);
    cfg_.synapse_gather.stride_bytes = params.find<uint32_t>(
        "synapse_gather_stride_bytes",
        cfg_.mem_stride_bytes);
    cfg_.stream_region.enable = params.find<int>(
        "stream_region_enable",
        (cfg_.semantic_memory_enable && cfg_.mem_enable) ? 1 : 0) != 0;
    cfg_.stream_region.base_addr = params.find<uint64_t>("stream_base_addr", 0);
    cfg_.stream_region.period_cycles = params.find<uint64_t>(
        "stream_region_period_cycles",
        cfg_.mem_period_cycles);
    cfg_.stream_region.region_bytes = params.find<uint64_t>(
        "stream_region_bytes",
        params.find<uint64_t>("memory_semantic_slot_bytes", cfg_.mem_region_bytes));
    cfg_.stream_region.req_bytes = params.find<uint32_t>(
        "stream_region_req_bytes",
        cfg_.mem_req_bytes);
    cfg_.stream_region.stride_bytes = params.find<uint32_t>(
        "stream_region_stride_bytes",
        cfg_.mem_stride_bytes);
    cfg_.writeback_region.enable = params.find<int>(
        "writeback_region_enable",
        (cfg_.semantic_memory_enable && cfg_.mem_enable) ? 1 : 0) != 0;
    cfg_.writeback_region.base_addr = params.find<uint64_t>("writeback_base_addr", 0);
    cfg_.writeback_region.period_cycles = params.find<uint64_t>(
        "writeback_region_period_cycles",
        cfg_.mem_period_cycles);
    cfg_.writeback_region.region_bytes = params.find<uint64_t>(
        "writeback_region_bytes",
        params.find<uint64_t>("memory_semantic_slot_bytes", cfg_.mem_region_bytes));
    cfg_.writeback_region.req_bytes = params.find<uint32_t>(
        "writeback_region_req_bytes",
        cfg_.mem_req_bytes);
    cfg_.writeback_region.stride_bytes = params.find<uint32_t>(
        "writeback_region_stride_bytes",
        cfg_.mem_stride_bytes);

    cfg_.comm_enable = params.find<int>("stream_comm_enable", cfg_.comm_enable ? 1 : 0) != 0;
    cfg_.comm_period_cycles = params.find<uint64_t>("stream_comm_period_cycles", cfg_.comm_period_cycles);
    cfg_.comm_payload_bytes = params.find<uint32_t>("stream_comm_payload_bytes", cfg_.comm_payload_bytes);

    cfg_.strict = params.find<int>("stream_strict", cfg_.strict ? 1 : 0) != 0;
    cfg_.seed_base = params.find<uint64_t>("stream_seed", cfg_.seed_base);

    // Hard bounds to avoid pathological allocations
    if (cfg_.mem_req_bytes == 0) cfg_.mem_req_bytes = 64;
    if (cfg_.mem_req_bytes > (1024u * 1024u)) cfg_.mem_req_bytes = 1024u * 1024u;
    if (cfg_.mem_stride_bytes == 0) cfg_.mem_stride_bytes = 64;
    if (cfg_.mem_max_outstanding == 0) cfg_.mem_max_outstanding = 1;
    if (cfg_.metadata_lookup.req_bytes == 0) cfg_.metadata_lookup.req_bytes = 16;
    if (cfg_.metadata_lookup.stride_bytes == 0) cfg_.metadata_lookup.stride_bytes = cfg_.metadata_lookup.req_bytes;
    if (cfg_.synapse_gather.req_bytes == 0) cfg_.synapse_gather.req_bytes = cfg_.mem_req_bytes;
    if (cfg_.synapse_gather.stride_bytes == 0) cfg_.synapse_gather.stride_bytes = cfg_.synapse_gather.req_bytes;
    if (cfg_.stream_region.req_bytes == 0) cfg_.stream_region.req_bytes = cfg_.mem_req_bytes;
    if (cfg_.stream_region.stride_bytes == 0) cfg_.stream_region.stride_bytes = cfg_.stream_region.req_bytes;
    if (cfg_.writeback_region.req_bytes == 0) cfg_.writeback_region.req_bytes = cfg_.mem_req_bytes;
    if (cfg_.writeback_region.stride_bytes == 0) cfg_.writeback_region.stride_bytes = cfg_.writeback_region.req_bytes;
}

void StreamWorkload::bindRuntime(const Runtime& rt) {
    rt_ = rt;
    // Keep inflight bounded if re-bound.
    if (mem_inflight_.size() > static_cast<size_t>(cfg_.mem_max_outstanding) * 4u) {
        mem_inflight_.clear();
    }
}

void StreamWorkload::enqueueSemanticDemand(const SemanticMemoryDemand& demand) {
    pending_metadata_lookup_demands_ += demand.metadata_lookup_demands;
    pending_synapse_gather_demands_ += demand.synapse_gather_demands;
    pending_stream_region_demands_ += demand.stream_region_demands;
    pending_writeback_region_demands_ += demand.writeback_region_demands;
}

uint32_t StreamWorkload::crc32_ieee_(const uint8_t* data, size_t len) {
    uint32_t crc = 0xFFFFFFFFu;
    for (size_t i = 0; i < len; ++i) {
        crc ^= static_cast<uint32_t>(data[i]);
        for (int k = 0; k < 8; ++k) {
            const uint32_t mask = static_cast<uint32_t>(-(static_cast<int32_t>(crc & 1u)));
            crc = (crc >> 1) ^ (0xEDB88320u & mask);
        }
    }
    return ~crc;
}

uint64_t StreamWorkload::splitmix64_next_(uint64_t& x) {
    x += 0x9e3779b97f4a7c15ULL;
    uint64_t z = x;
    z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
    z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
    return z ^ (z >> 31);
}

void StreamWorkload::write_u16_le_(std::vector<uint8_t>& out, uint16_t v) {
    out.push_back(static_cast<uint8_t>(v & 0xFFu));
    out.push_back(static_cast<uint8_t>((v >> 8) & 0xFFu));
}

void StreamWorkload::write_u32_le_(std::vector<uint8_t>& out, uint32_t v) {
    out.push_back(static_cast<uint8_t>(v & 0xFFu));
    out.push_back(static_cast<uint8_t>((v >> 8) & 0xFFu));
    out.push_back(static_cast<uint8_t>((v >> 16) & 0xFFu));
    out.push_back(static_cast<uint8_t>((v >> 24) & 0xFFu));
}

bool StreamWorkload::read_u16_le_(const std::vector<uint8_t>& buf, size_t off, uint16_t& out) {
    if (off + 2 > buf.size()) return false;
    out = static_cast<uint16_t>(buf[off]) | (static_cast<uint16_t>(buf[off + 1]) << 8);
    return true;
}

bool StreamWorkload::read_u32_le_(const std::vector<uint8_t>& buf, size_t off, uint32_t& out) {
    if (off + 4 > buf.size()) return false;
    out = static_cast<uint32_t>(buf[off]) |
          (static_cast<uint32_t>(buf[off + 1]) << 8) |
          (static_cast<uint32_t>(buf[off + 2]) << 16) |
          (static_cast<uint32_t>(buf[off + 3]) << 24);
    return true;
}

bool StreamWorkload::check_expected_bytes_(uint64_t seed_base,
                                          uint32_t node_id,
                                          uint32_t core_id,
                                          uint64_t addr,
                                          uint32_t seq,
                                          SemanticMemoryKind kind,
                                          const std::vector<uint8_t>& got) {
    uint64_t rng = seed_base ^
                   (static_cast<uint64_t>(node_id) << 32) ^
                   (static_cast<uint64_t>(core_id) << 16) ^
                   addr ^
                   static_cast<uint64_t>(seq) ^
                   (static_cast<uint64_t>(kind) << 48);
    size_t pos = 0;
    while (pos < got.size()) {
        const uint64_t v = splitmix64_next_(rng);
        const size_t n = std::min<size_t>(8, got.size() - pos);
        uint8_t tmp[8];
        std::memcpy(tmp, &v, 8);
        if (std::memcmp(&got[pos], tmp, n) != 0) {
            return false;
        }
        pos += n;
    }
    return true;
}

const char* StreamWorkload::semanticKindKey_(SemanticMemoryKind kind) {
    switch (kind) {
        case SemanticMemoryKind::MetadataLookup:
            return "metadata_lookup";
        case SemanticMemoryKind::SynapseGather:
            return "synapse_gather";
        case SemanticMemoryKind::StreamRegion:
            return "stream_region";
        case SemanticMemoryKind::WritebackRegion:
            return "writeback_region";
        case SemanticMemoryKind::Legacy:
        default:
            return "stream_mem";
    }
}

void StreamWorkload::noteMemoryIssue_(SemanticMemoryKind kind, size_t bytes, bool is_read) {
    reportMemIssue_(bytes);
    memory_requests_++;
    if (is_read) {
        if (rt_.sinks.stat_mem_reads_issued_total) rt_.sinks.stat_mem_reads_issued_total->addData(1);
        if (rt_.sinks.stat_mem_bytes_read_total) rt_.sinks.stat_mem_bytes_read_total->addData(bytes);
        stream_mem_reads_issued_total_ += 1;
        stream_mem_bytes_read_total_ += static_cast<uint64_t>(bytes);
    } else {
        if (rt_.sinks.stat_mem_writes_issued_total) rt_.sinks.stat_mem_writes_issued_total->addData(1);
        if (rt_.sinks.stat_mem_bytes_written_total) rt_.sinks.stat_mem_bytes_written_total->addData(bytes);
        stream_mem_writes_issued_total_ += 1;
        stream_mem_bytes_written_total_ += static_cast<uint64_t>(bytes);
    }

    switch (kind) {
        case SemanticMemoryKind::MetadataLookup:
            if (is_read) {
                metadata_lookup_reads_issued_total_ += 1;
                metadata_lookup_bytes_read_total_ += static_cast<uint64_t>(bytes);
            } else {
                metadata_lookup_writes_issued_total_ += 1;
                metadata_lookup_bytes_written_total_ += static_cast<uint64_t>(bytes);
            }
            break;
        case SemanticMemoryKind::SynapseGather:
            if (is_read) {
                synapse_gather_reads_issued_total_ += 1;
                synapse_gather_bytes_read_total_ += static_cast<uint64_t>(bytes);
            } else {
                synapse_gather_writes_issued_total_ += 1;
                synapse_gather_bytes_written_total_ += static_cast<uint64_t>(bytes);
            }
            break;
        case SemanticMemoryKind::StreamRegion:
            if (is_read) {
                stream_region_reads_issued_total_ += 1;
                stream_region_bytes_read_total_ += static_cast<uint64_t>(bytes);
            } else {
                stream_region_writes_issued_total_ += 1;
                stream_region_bytes_written_total_ += static_cast<uint64_t>(bytes);
            }
            break;
        case SemanticMemoryKind::WritebackRegion:
            if (is_read) {
                writeback_region_reads_issued_total_ += 1;
                writeback_region_bytes_read_total_ += static_cast<uint64_t>(bytes);
            } else {
                writeback_region_writes_issued_total_ += 1;
                writeback_region_bytes_written_total_ += static_cast<uint64_t>(bytes);
            }
            break;
        case SemanticMemoryKind::Legacy:
        default:
            break;
    }
}

bool StreamWorkload::issueLegacyMemoryRequest_(uint64_t now_cycle) {
    const uint32_t max_ostd = cfg_.mem_max_outstanding;
    const bool time_ok =
        (cfg_.mem_period_cycles == 0) ||
        (now_cycle - last_mem_issue_cycle_ >= cfg_.mem_period_cycles);
    if (!time_ok || mem_inflight_.size() >= static_cast<size_t>(max_ostd)) return false;
    if (cfg_.mem_region_bytes < cfg_.mem_req_bytes) return false;

    const uint32_t req_bytes = cfg_.mem_req_bytes;
    uint64_t offset = next_offset_;
    if (offset + req_bytes > cfg_.mem_region_bytes) offset = 0;
    const uint64_t addr = rt_.base_addr + offset;
    const uint32_t seq = mem_seq_++;

    std::vector<uint8_t> data;
    data.resize(req_bytes);
    uint64_t rng = cfg_.seed_base ^
                   (static_cast<uint64_t>(rt_.node_id) << 32) ^
                   (static_cast<uint64_t>(rt_.core_id) << 16) ^
                   addr ^
                   static_cast<uint64_t>(seq);
    size_t pos = 0;
    while (pos < data.size()) {
        const uint64_t v = splitmix64_next_(rng);
        const size_t n = std::min<size_t>(8, data.size() - pos);
        std::memcpy(&data[pos], &v, n);
        pos += n;
    }

    noteMemoryIssue_(SemanticMemoryKind::Legacy, data.size(), /*is_read=*/false);
    const auto w_id = rt_.mem->write(
        addr, data,
        [this, addr, seq, req_bytes](IMemoryAccess::RequestId req_id, uint64_t /*addr_cb*/) mutable {
            if (req_id != 0) {
                mem_inflight_.erase(static_cast<uint64_t>(req_id));
            }
            if (req_id == 0) {
                if (rt_.sinks.mem_verify_fail) (*rt_.sinks.mem_verify_fail)++;
                if (rt_.sinks.stat_mem_verify_fail_total) rt_.sinks.stat_mem_verify_fail_total->addData(1);
                if (cfg_.strict && rt_.log) {
                    rt_.log->fatal(CALL_INFO, -1,
                                   "stream fatal: write failed (core=%u addr=0x%llx seq=%u bytes=%u)\n",
                                   rt_.core_id, (unsigned long long)addr, seq, req_bytes);
                }
                return;
            }

            if (!rt_.mem) return;
            noteMemoryIssue_(SemanticMemoryKind::Legacy, req_bytes, /*is_read=*/true);

            const auto r_id = rt_.mem->read(
                addr, req_bytes,
                [this, addr, seq, req_bytes](IMemoryAccess::RequestId r_id,
                                             uint64_t /*addr_cb*/,
                                             std::vector<uint8_t>&& got) mutable {
                    if (r_id != 0) {
                        mem_inflight_.erase(static_cast<uint64_t>(r_id));
                    }
                    if (r_id == 0 || got.size() != req_bytes) {
                        if (rt_.sinks.mem_verify_fail) (*rt_.sinks.mem_verify_fail)++;
                        if (rt_.sinks.stat_mem_verify_fail_total) rt_.sinks.stat_mem_verify_fail_total->addData(1);
                        if (cfg_.strict && rt_.log) {
                            rt_.log->fatal(CALL_INFO, -1,
                                           "stream fatal: read failed (core=%u addr=0x%llx seq=%u bytes=%u got=%zu)\n",
                                           rt_.core_id, (unsigned long long)addr, seq, req_bytes, got.size());
                        }
                        return;
                    }
                    if (!check_expected_bytes_(
                            cfg_.seed_base,
                            rt_.node_id,
                            rt_.core_id,
                            addr,
                            seq,
                            SemanticMemoryKind::Legacy,
                            got)) {
                        if (rt_.sinks.mem_verify_fail) (*rt_.sinks.mem_verify_fail)++;
                        if (rt_.sinks.stat_mem_verify_fail_total) rt_.sinks.stat_mem_verify_fail_total->addData(1);
                        if (cfg_.strict && rt_.log) {
                            rt_.log->fatal(CALL_INFO, -1,
                                           "stream fatal: verify mismatch (core=%u addr=0x%llx seq=%u bytes=%u)\n",
                                           rt_.core_id, (unsigned long long)addr, seq, req_bytes);
                        }
                        return;
                    }
                    if (rt_.sinks.mem_verify_pass) (*rt_.sinks.mem_verify_pass)++;
                    if (rt_.sinks.stat_mem_verify_pass_total) rt_.sinks.stat_mem_verify_pass_total->addData(1);
                });
            if (r_id != 0) {
                mem_inflight_[static_cast<uint64_t>(r_id)] = MemReq{
                    addr, seq, req_bytes, true, SemanticMemoryKind::Legacy};
            }
        });

    if (w_id != 0) {
        mem_inflight_[static_cast<uint64_t>(w_id)] = MemReq{
            addr, seq, req_bytes, false, SemanticMemoryKind::Legacy};
    }

    last_mem_issue_cycle_ = now_cycle;
    next_offset_ = offset + static_cast<uint64_t>(std::max<uint32_t>(1, cfg_.mem_stride_bytes));
    if (next_offset_ >= cfg_.mem_region_bytes) next_offset_ = 0;
    return true;
}

bool StreamWorkload::issueSemanticMemoryRequest_(
    uint64_t now_cycle,
    SemanticMemoryKind kind,
    const SemanticMemoryConfig& cfg,
    SemanticMemoryState& state) {
    if (!cfg.enable) return false;
    if (cfg.region_bytes == 0 || cfg.req_bytes == 0) return false;
    if (cfg.region_bytes < cfg.req_bytes) return false;
    if (mem_inflight_.size() >= static_cast<size_t>(cfg_.mem_max_outstanding)) return false;

    const bool time_ok =
        (cfg.period_cycles == 0) ||
        (now_cycle - state.last_issue_cycle >= cfg.period_cycles);
    if (!time_ok) return false;

    uint64_t offset = state.next_offset;
    if (offset + cfg.req_bytes > cfg.region_bytes) offset = 0;
    const uint64_t addr = cfg.base_addr + offset;
    const uint32_t seq = state.seq++;
    const uint32_t req_bytes = cfg.req_bytes;

    std::vector<uint8_t> data;
    data.resize(req_bytes);
    uint64_t rng = cfg_.seed_base ^
                   (static_cast<uint64_t>(rt_.node_id) << 32) ^
                   (static_cast<uint64_t>(rt_.core_id) << 16) ^
                   addr ^
                   static_cast<uint64_t>(seq) ^
                   (static_cast<uint64_t>(kind) << 48);
    size_t pos = 0;
    while (pos < data.size()) {
        const uint64_t v = splitmix64_next_(rng);
        const size_t n = std::min<size_t>(8, data.size() - pos);
        std::memcpy(&data[pos], &v, n);
        pos += n;
    }

    noteMemoryIssue_(kind, data.size(), /*is_read=*/false);
    const auto w_id = rt_.mem->write(
        addr, data,
        [this, kind, addr, seq, req_bytes](IMemoryAccess::RequestId req_id, uint64_t /*addr_cb*/) mutable {
            if (req_id != 0) {
                mem_inflight_.erase(static_cast<uint64_t>(req_id));
            }
            if (req_id == 0) {
                if (rt_.sinks.mem_verify_fail) (*rt_.sinks.mem_verify_fail)++;
                if (rt_.sinks.stat_mem_verify_fail_total) rt_.sinks.stat_mem_verify_fail_total->addData(1);
                if (cfg_.strict && rt_.log) {
                    rt_.log->fatal(CALL_INFO, -1,
                                   "stream fatal: semantic write failed kind=%s (core=%u addr=0x%llx seq=%u bytes=%u)\n",
                                   semanticKindKey_(kind),
                                   rt_.core_id, (unsigned long long)addr, seq, req_bytes);
                }
                return;
            }

            if (!rt_.mem) return;
            noteMemoryIssue_(kind, req_bytes, /*is_read=*/true);
            const auto r_id = rt_.mem->read(
                addr, req_bytes,
                [this, kind, addr, seq, req_bytes](IMemoryAccess::RequestId r_id,
                                                   uint64_t /*addr_cb*/,
                                                   std::vector<uint8_t>&& got) mutable {
                    if (r_id != 0) {
                        mem_inflight_.erase(static_cast<uint64_t>(r_id));
                    }
                    if (r_id == 0 || got.size() != req_bytes) {
                        if (rt_.sinks.mem_verify_fail) (*rt_.sinks.mem_verify_fail)++;
                        if (rt_.sinks.stat_mem_verify_fail_total) rt_.sinks.stat_mem_verify_fail_total->addData(1);
                        if (cfg_.strict && rt_.log) {
                            rt_.log->fatal(CALL_INFO, -1,
                                           "stream fatal: semantic read failed kind=%s (core=%u addr=0x%llx seq=%u bytes=%u got=%zu)\n",
                                           semanticKindKey_(kind),
                                           rt_.core_id, (unsigned long long)addr, seq, req_bytes, got.size());
                        }
                        return;
                    }
                    if (!check_expected_bytes_(cfg_.seed_base, rt_.node_id, rt_.core_id, addr, seq, kind, got)) {
                        if (rt_.sinks.mem_verify_fail) (*rt_.sinks.mem_verify_fail)++;
                        if (rt_.sinks.stat_mem_verify_fail_total) rt_.sinks.stat_mem_verify_fail_total->addData(1);
                        if (cfg_.strict && rt_.log) {
                            rt_.log->fatal(CALL_INFO, -1,
                                           "stream fatal: semantic verify mismatch kind=%s (core=%u addr=0x%llx seq=%u bytes=%u)\n",
                                           semanticKindKey_(kind),
                                           rt_.core_id, (unsigned long long)addr, seq, req_bytes);
                        }
                        return;
                    }
                    if (rt_.sinks.mem_verify_pass) (*rt_.sinks.mem_verify_pass)++;
                    if (rt_.sinks.stat_mem_verify_pass_total) rt_.sinks.stat_mem_verify_pass_total->addData(1);
                });
            if (r_id != 0) {
                mem_inflight_[static_cast<uint64_t>(r_id)] = MemReq{addr, seq, req_bytes, true, kind};
            }
        });

    if (w_id != 0) {
        mem_inflight_[static_cast<uint64_t>(w_id)] = MemReq{addr, seq, req_bytes, false, kind};
    }

    state.last_issue_cycle = now_cycle;
    state.next_offset = offset + static_cast<uint64_t>(std::max<uint32_t>(1, cfg.stride_bytes));
    if (state.next_offset >= cfg.region_bytes) state.next_offset = 0;
    return true;
}

bool StreamWorkload::issueDemandDrivenSemanticMemoryRequest_(
    uint64_t now_cycle,
    SemanticMemoryKind kind,
    const SemanticMemoryConfig& cfg,
    SemanticMemoryState& state,
    uint64_t& pending_demands) {
    if (pending_demands == 0) return false;
    if (!issueSemanticMemoryRequest_(now_cycle, kind, cfg, state)) return false;
    pending_demands -= 1;
    return true;
}

bool StreamWorkload::hasSemanticMemoryWork_() const {
    return cfg_.semantic_memory_enable &&
           ((cfg_.metadata_lookup.enable && cfg_.metadata_lookup.region_bytes > 0) ||
            (cfg_.synapse_gather.enable && cfg_.synapse_gather.region_bytes > 0) ||
            (cfg_.stream_region.enable && cfg_.stream_region.region_bytes > 0) ||
            (cfg_.writeback_region.enable && cfg_.writeback_region.region_bytes > 0));
}

bool StreamWorkload::hasPendingSemanticDemand_() const {
    return pending_metadata_lookup_demands_ > 0 ||
           pending_synapse_gather_demands_ > 0 ||
           pending_stream_region_demands_ > 0 ||
           pending_writeback_region_demands_ > 0;
}

bool StreamWorkload::deliverPacket(NocPacketEvent* packet) {
    if (!packet) return true;
    if (packet->packetKind() != NocPacketKind::RawBytes) {
        delete packet;
        return true;
    }
    // Header layout (LE):
    //  - magic[8] ("SNNDLSTR")
    //  - version(u16)
    //  - msg_type(u16)
    //  - seq(u32)
    //  - payload_len(u32)
    //  - crc32(u32) over payload bytes
    constexpr size_t kHdrBytes = 8 + 2 + 2 + 4 + 4 + 4;
    bool ok = true;
    if (packet->payload.size() < kHdrBytes) ok = false;
    if (ok && std::memcmp(packet->payload.data(), kStreamMagic, 8) != 0) ok = false;
    uint16_t ver = 0, msg_type = 0;
    uint32_t seq = 0, pay_len = 0, crc = 0;
    if (ok && !read_u16_le_(packet->payload, 8, ver)) ok = false;
    if (ok && !read_u16_le_(packet->payload, 10, msg_type)) ok = false;
    if (ok && !read_u32_le_(packet->payload, 12, seq)) ok = false;
    if (ok && !read_u32_le_(packet->payload, 16, pay_len)) ok = false;
    if (ok && !read_u32_le_(packet->payload, 20, crc)) ok = false;
    if (ok && ver != kStreamVersion) ok = false;
    if (ok && packet->payload.size() != kHdrBytes + static_cast<size_t>(pay_len)) ok = false;

    if (!ok) {
        if (rt_.sinks.pkt_bad_magic) (*rt_.sinks.pkt_bad_magic)++;
        if (rt_.sinks.stat_pkt_bad_magic_total) rt_.sinks.stat_pkt_bad_magic_total->addData(1);
        delete packet;
        return true;
    }

    const uint8_t* pay = packet->payload.data() + kHdrBytes;
    const uint32_t got = crc32_ieee_(pay, static_cast<size_t>(pay_len));
    if (got != crc) {
        if (rt_.sinks.pkt_bad_crc) (*rt_.sinks.pkt_bad_crc)++;
        if (rt_.sinks.stat_pkt_bad_crc_total) rt_.sinks.stat_pkt_bad_crc_total->addData(1);
        if (cfg_.strict && rt_.log) {
            rt_.log->fatal(CALL_INFO, -1,
                           "stream fatal: bad crc (core=%u seq=%u expected=0x%08x got=0x%08x len=%u src=%u:%u)\n",
                           rt_.core_id, seq, crc, got, pay_len, packet->src_node, packet->src_endpoint);
        }
        delete packet;
        return true;
    }

    (void)msg_type;
    if (rt_.sinks.pkt_recv) (*rt_.sinks.pkt_recv)++;
    if (rt_.sinks.stat_pkt_recv_total) rt_.sinks.stat_pkt_recv_total->addData(1);
    delete packet;
    return true;
}

bool StreamWorkload::onClockTick(uint64_t now_cycle) {
    total_cycles_++;
    bool did = false;

    // === Memory stream: write -> read -> verify ===
    if (cfg_.mem_enable && rt_.mem && cfg_.mem_region_bytes > 0 && cfg_.mem_req_bytes > 0) {
        if (hasSemanticMemoryWork_()) {
            bool metadata_did = false;
            bool gather_did = false;
            bool stream_region_did = false;
            bool writeback_region_did = false;
            if (cfg_.semantic_memory_demand_driven_enable) {
                metadata_did = issueDemandDrivenSemanticMemoryRequest_(
                    now_cycle,
                    SemanticMemoryKind::MetadataLookup,
                    cfg_.metadata_lookup,
                    metadata_lookup_state_,
                    pending_metadata_lookup_demands_);
                gather_did = issueDemandDrivenSemanticMemoryRequest_(
                    now_cycle,
                    SemanticMemoryKind::SynapseGather,
                    cfg_.synapse_gather,
                    synapse_gather_state_,
                    pending_synapse_gather_demands_);
                stream_region_did = issueDemandDrivenSemanticMemoryRequest_(
                    now_cycle,
                    SemanticMemoryKind::StreamRegion,
                    cfg_.stream_region,
                    stream_region_state_,
                    pending_stream_region_demands_);
                writeback_region_did = issueDemandDrivenSemanticMemoryRequest_(
                    now_cycle,
                    SemanticMemoryKind::WritebackRegion,
                    cfg_.writeback_region,
                    writeback_region_state_,
                    pending_writeback_region_demands_);
            } else {
                metadata_did = issueSemanticMemoryRequest_(
                    now_cycle,
                    SemanticMemoryKind::MetadataLookup,
                    cfg_.metadata_lookup,
                    metadata_lookup_state_);
                gather_did = issueSemanticMemoryRequest_(
                    now_cycle,
                    SemanticMemoryKind::SynapseGather,
                    cfg_.synapse_gather,
                    synapse_gather_state_);
                stream_region_did = issueSemanticMemoryRequest_(
                    now_cycle,
                    SemanticMemoryKind::StreamRegion,
                    cfg_.stream_region,
                    stream_region_state_);
                writeback_region_did = issueSemanticMemoryRequest_(
                    now_cycle,
                    SemanticMemoryKind::WritebackRegion,
                    cfg_.writeback_region,
                    writeback_region_state_);
            }
            did = metadata_did || gather_did || stream_region_did || writeback_region_did || did;
        } else {
            did = issueLegacyMemoryRequest_(now_cycle) || did;
        }

        if (mem_inflight_.size() > static_cast<size_t>(cfg_.mem_max_outstanding) * 4u) {
            mem_inflight_.clear();
        }
    }

    // === Communication stream: RawBytes packets ===
    if (cfg_.comm_enable && cfg_.comm_period_cycles > 0 && rt_.noc) {
        if (now_cycle - last_comm_cycle_ >= cfg_.comm_period_cycles) {
            const uint32_t dst_node = (rt_.total_nodes > 1) ? ((rt_.node_id + 1u) % rt_.total_nodes) : rt_.node_id;
            auto* pkt = new NocPacketEvent(rt_.node_id,
                                           dst_node,
                                           static_cast<uint16_t>(rt_.core_id),
                                           static_cast<uint16_t>(rt_.core_id),
                                           NocPacketKind::RawBytes,
                                           /*ts*/now_cycle);
            constexpr size_t kHdrBytes = 8 + 2 + 2 + 4 + 4 + 4;
            pkt->payload.reserve(kHdrBytes + cfg_.comm_payload_bytes);
            pkt->payload.insert(pkt->payload.end(), kStreamMagic, kStreamMagic + 8);
            write_u16_le_(pkt->payload, kStreamVersion);
            write_u16_le_(pkt->payload, static_cast<uint16_t>(StreamMsgType::Data));
            const uint32_t seq = pkt_seq_++;
            write_u32_le_(pkt->payload, seq);
            write_u32_le_(pkt->payload, cfg_.comm_payload_bytes);
            // CRC placeholder (u32)
            const size_t crc_off = pkt->payload.size();
            write_u32_le_(pkt->payload, 0u);
            // Payload bytes
            const size_t payload_off = pkt->payload.size();
            pkt->payload.resize(payload_off + cfg_.comm_payload_bytes);
            uint64_t rng = cfg_.seed_base ^
                           (static_cast<uint64_t>(rt_.node_id) << 32) ^
                           (static_cast<uint64_t>(rt_.core_id) << 16) ^
                           static_cast<uint64_t>(seq) ^
                           0xC0DEC0DEULL;
            size_t p = 0;
            while (p < cfg_.comm_payload_bytes) {
                const uint64_t v = splitmix64_next_(rng);
                const size_t n = std::min<size_t>(8, static_cast<size_t>(cfg_.comm_payload_bytes) - p);
                std::memcpy(pkt->payload.data() + payload_off + p, &v, n);
                p += n;
            }
            const uint32_t crc = crc32_ieee_(pkt->payload.data() + payload_off, cfg_.comm_payload_bytes);
            pkt->payload[crc_off + 0] = static_cast<uint8_t>(crc & 0xFFu);
            pkt->payload[crc_off + 1] = static_cast<uint8_t>((crc >> 8) & 0xFFu);
            pkt->payload[crc_off + 2] = static_cast<uint8_t>((crc >> 16) & 0xFFu);
            pkt->payload[crc_off + 3] = static_cast<uint8_t>((crc >> 24) & 0xFFu);

            if (rt_.sinks.stat_pkt_sent_total) rt_.sinks.stat_pkt_sent_total->addData(1);
            if (rt_.sinks.pkt_sent) (*rt_.sinks.pkt_sent)++;

            if (dst_node == rt_.node_id) {
                rt_.noc->injectLocal(static_cast<int>(rt_.core_id), pkt);
            } else {
                rt_.noc->sendFromCore(static_cast<int>(rt_.core_id), pkt);
            }
            last_comm_cycle_ = now_cycle;
            did = true;
        }
    }

    if (did) active_cycles_++;
    return did;
}

bool StreamWorkload::hasWork() const {
    if (!mem_inflight_.empty()) return true;
    if (cfg_.mem_enable && rt_.mem && hasSemanticMemoryWork_()) {
        if (!cfg_.semantic_memory_demand_driven_enable || hasPendingSemanticDemand_()) return true;
    }
    if (cfg_.mem_enable &&
        rt_.mem &&
        !hasSemanticMemoryWork_() &&
        cfg_.mem_region_bytes > 0 &&
        cfg_.mem_req_bytes > 0) {
        return true;
    }
    if (cfg_.comm_enable && rt_.noc && cfg_.comm_period_cycles > 0) return true;
    return false;
}

double StreamWorkload::getUtilization() const {
    if (total_cycles_ == 0) return 0.0;
    return static_cast<double>(active_cycles_) / static_cast<double>(total_cycles_);
}

void StreamWorkload::getStatistics(std::map<std::string, uint64_t>& stats) const {
    // Preserve legacy keys expected by MultiCorePE/analysis.
    stats["spikes_received"] = 0;
    stats["spikes_generated"] = 0;
    stats["neurons_fired"] = 0;
    stats["memory_requests"] = memory_requests_;
    stats["total_cycles"] = total_cycles_;
    stats["active_cycles"] = active_cycles_;
    stats["cycles_update_neuron"] = 0;
    stats["synaptic_accesses"] = 0;

    stats["stream_mem_verify_pass_total"] = rt_.sinks.mem_verify_pass ? *rt_.sinks.mem_verify_pass : 0;
    stats["stream_mem_verify_fail_total"] = rt_.sinks.mem_verify_fail ? *rt_.sinks.mem_verify_fail : 0;
    stats["stream_mem_writes_issued_total"] = stream_mem_writes_issued_total_;
    stats["stream_mem_reads_issued_total"] = stream_mem_reads_issued_total_;
    stats["stream_mem_bytes_written_total"] = stream_mem_bytes_written_total_;
    stats["stream_mem_bytes_read_total"] = stream_mem_bytes_read_total_;
    stats["metadata_lookup_writes_issued_total"] = metadata_lookup_writes_issued_total_;
    stats["metadata_lookup_reads_issued_total"] = metadata_lookup_reads_issued_total_;
    stats["metadata_lookup_bytes_written_total"] = metadata_lookup_bytes_written_total_;
    stats["metadata_lookup_bytes_read_total"] = metadata_lookup_bytes_read_total_;
    stats["synapse_gather_writes_issued_total"] = synapse_gather_writes_issued_total_;
    stats["synapse_gather_reads_issued_total"] = synapse_gather_reads_issued_total_;
    stats["synapse_gather_bytes_written_total"] = synapse_gather_bytes_written_total_;
    stats["synapse_gather_bytes_read_total"] = synapse_gather_bytes_read_total_;
    stats["stream_region_writes_issued_total"] = stream_region_writes_issued_total_;
    stats["stream_region_reads_issued_total"] = stream_region_reads_issued_total_;
    stats["stream_region_bytes_written_total"] = stream_region_bytes_written_total_;
    stats["stream_region_bytes_read_total"] = stream_region_bytes_read_total_;
    stats["writeback_region_writes_issued_total"] = writeback_region_writes_issued_total_;
    stats["writeback_region_reads_issued_total"] = writeback_region_reads_issued_total_;
    stats["writeback_region_bytes_written_total"] = writeback_region_bytes_written_total_;
    stats["writeback_region_bytes_read_total"] = writeback_region_bytes_read_total_;
    stats["stream_pkt_sent_total"] = rt_.sinks.pkt_sent ? *rt_.sinks.pkt_sent : 0;
    stats["stream_pkt_recv_total"] = rt_.sinks.pkt_recv ? *rt_.sinks.pkt_recv : 0;
    stats["stream_pkt_bad_crc_total"] = rt_.sinks.pkt_bad_crc ? *rt_.sinks.pkt_bad_crc : 0;
    stats["stream_pkt_bad_magic_total"] = rt_.sinks.pkt_bad_magic ? *rt_.sinks.pkt_bad_magic : 0;
}

}} // namespace SST::SnnDL
