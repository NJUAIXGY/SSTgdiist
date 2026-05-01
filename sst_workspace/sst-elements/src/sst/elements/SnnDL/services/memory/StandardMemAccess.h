// -*- c++ -*-
//
// StandardMemAccess: 将 StandardMem pending 跟踪与回包分发收敛为纯内存访问实现。
// 注意：只处理“地址→字节块”，不包含任何权重/突触/路由语义。

#pragma once

#include <cstddef>
#include <cstdint>
#include <functional>
#include <unordered_map>
#include <vector>

#include <sst/core/interfaces/stdMem.h>

#include "IMemoryAccess.h"

namespace SST { class Output; }

namespace SST { namespace SnnDL {

class StandardMemAccess final : public IMemoryAccess {
public:
    explicit StandardMemAccess(SST::Interfaces::StandardMem* mem,
                               SST::Output* out,
                               int node_id,
                               int core_id)
        : mem_(mem), out_(out), node_id_(node_id), core_id_(core_id) {}

    // Memory semantic only: force all requests to be non-cacheable (e.g., streaming workload).
    void setForceNoncacheable(bool v) { force_noncacheable_ = v; }

    RequestId read(uint64_t addr, size_t bytes, ReadCallback cb) override;
    RequestId write(uint64_t addr, const std::vector<uint8_t>& data, WriteCallback cb) override;
    size_t pendingSize() const override { return pending_.size(); }

    // Handle StandardMem responses. Returns true if handled and request deleted.
    bool handleMemoryResponse(SST::Interfaces::StandardMem::Request* req);

private:
    struct FragmentGroup {
        uint64_t orig_addr = 0;
        size_t slice_off = 0;
        size_t slice_len = 0;
        uint64_t line_bytes = 0;
        size_t remaining = 0;
        std::vector<uint8_t> buf;
        ReadCallback cb;
    };

    struct PendingEntry {
        uint64_t address = 0;
        size_t bytes = 0;
        bool is_write = false;
        ReadCallback read_cb;
        WriteCallback write_cb;
    };

    uint64_t lineBytes_() const;
    uint64_t allocFragmentGroupId_();
    void onFragmentResp_(uint64_t group_id, uint64_t line_index, std::vector<uint8_t> data);

    SST::Interfaces::StandardMem* mem_ = nullptr;
    SST::Output* out_ = nullptr;
    int node_id_ = -1;
    int core_id_ = -1;
    bool force_noncacheable_ = false;
    std::unordered_map<uint64_t, PendingEntry> pending_;
    uint64_t next_group_id_ = 1;
    std::unordered_map<uint64_t, FragmentGroup> frag_groups_;
};

}} // namespace SST::SnnDL
