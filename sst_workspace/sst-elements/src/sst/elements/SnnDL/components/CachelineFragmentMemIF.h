// -*- c++ -*-
// CachelineFragmentMemIF.h: StandardMem front-end that fragments variable-size reads into cacheline reads.
//
// 目的：
// - 让“naive_raw”这种不使用 GAS 的路径也能以 cacheline 作为物理事务粒度，
//   从而 memHierarchy 的 MemController GetS 统计（cacheline 事务）与上游请求字节口径可对齐。
// - 避免 memHierarchy.Cache 在处理 size>cacheline 的 Read payload 时出现越界/不确定性问题。

#pragma once

#include <cstdint>
#include <unordered_map>
#include <vector>

#include <sst/core/sst_config.h>
#include <sst/core/output.h>
#include <sst/core/interfaces/stdMem.h>

namespace SST { namespace SnnDL {

class CachelineFragmentMemIF : public SST::Interfaces::StandardMem {
public:
    SST_ELI_REGISTER_SUBCOMPONENT(
        CachelineFragmentMemIF,
        "SnnDL", "CachelineFragmentMemIF", SST_ELI_ELEMENT_VERSION(1,0,0),
        "StandardMem front-end that fragments reads into cacheline-sized reads", SST::Interfaces::StandardMem)

    SST_ELI_DOCUMENT_PARAMS(
        {"verbose", "verbosity", "0"},
        {"max_inflight_reads", "Max inflight downstream cacheline reads", "128"},
        {"port", "shared port name for downstream standardInterface when loaded anonymously"}
    )

    SST_ELI_DOCUMENT_PORTS(
        {"lowlink", "Port to memory hierarchy (shared with downstream standardInterface)", {}}
    )

    CachelineFragmentMemIF(ComponentId_t id, Params& params, TimeConverter* time, HandlerBase* handler);
    CachelineFragmentMemIF() : SST::Interfaces::StandardMem() {}
    ~CachelineFragmentMemIF() override = default;

    // StandardMem virtuals
    void sendUntimedData(Request* req) override;
    Request* recvUntimedData() override;
    void send(Request* req) override;
    Request* poll() override;
    Addr getLineSize() override;
    void setMemoryMappedAddressRegion(Addr start, Addr size) override;

    // Phases
    void init(unsigned int phase) override;
    void complete(unsigned int phase) override;
    void setup() override;
    void finish() override;

private:
    struct UpReadState {
        uint64_t up_id = 0;
        uint64_t req_addr = 0;
        uint32_t req_size = 0;
        uint64_t base = 0;     // aligned-down line base
        uint32_t off = 0;      // req_addr - base
        uint32_t lines_total = 0;
        uint32_t lines_issued = 0;
        uint32_t lines_done = 0;
        std::vector<uint8_t> buf; // full lines (lines_total * line_bytes)
    };

    struct DownFrag {
        uint64_t up_id = 0;
        uint32_t line_index = 0;
    };

    uint64_t alignDown_(uint64_t addr, uint64_t bytes) const { return (bytes ? (addr / bytes) * bytes : addr); }
    uint64_t alignUp_(uint64_t addr, uint64_t bytes) const {
        if (!bytes) return addr;
        return ((addr + bytes - 1) / bytes) * bytes;
    }

    uint64_t lineBytes_() const;
    void issueMore_(uint64_t up_id);
    void onDownstreamResp_(Request* r);

    SST::Interfaces::StandardMem* backend_ = nullptr; // downstream standardInterface
    TimeConverter* time_ = nullptr;
    HandlerBase* upstream_handler_ = nullptr;
    Output out_;

    uint32_t max_inflight_reads_ = 128;
    uint64_t inflight_total_ = 0;

    std::unordered_map<uint64_t, UpReadState> up_reads_;
    std::unordered_map<SST::Interfaces::StandardMem::Request::id_t, DownFrag> inflight_down_;
};

}} // namespace SST::SnnDL

