// -*- c++ -*-

#pragma once

#include <cstddef>
#include <cstdint>

#include "api/IDmaTaggedAccess.h"
#include "api/IMemoryAccess.h"

namespace SST { namespace SnnDL {

class PeDmaScheduler;

class DmaMemAccessProxy final : public IMemoryAccess, public IDmaTaggedAccess {
public:
    DmaMemAccessProxy(uint32_t core_id, PeDmaScheduler* scheduler, IMemoryAccess* backend)
        : core_id_(core_id), scheduler_(scheduler), backend_(backend) {}

    RequestId read(uint64_t addr, size_t bytes, ReadCallback cb) override;
    RequestId readTagged(uint64_t addr,
                         size_t bytes,
                         Tag tag,
                         Priority priority,
                         ReadCallback cb) override;
    RequestId write(uint64_t addr, const std::vector<uint8_t>& data, WriteCallback cb) override;
    size_t pendingSize() const override;

private:
    uint32_t core_id_ = 0;
    PeDmaScheduler* scheduler_ = nullptr;
    IMemoryAccess* backend_ = nullptr;
    size_t direct_read_pending_ = 0;
    size_t write_pending_ = 0;
};

}} // namespace SST::SnnDL
