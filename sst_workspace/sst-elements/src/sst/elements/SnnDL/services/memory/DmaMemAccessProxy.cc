// -*- c++ -*-

#include "services/memory/DmaMemAccessProxy.h"

#include <utility>

#include "services/memory/PeDmaScheduler.h"

namespace SST { namespace SnnDL {

IMemoryAccess::RequestId
DmaMemAccessProxy::read(uint64_t addr, size_t bytes, ReadCallback cb) {
    return readTagged(addr, bytes, 0, Priority::P1, std::move(cb));
}

IMemoryAccess::RequestId
DmaMemAccessProxy::readTagged(uint64_t addr,
                              size_t bytes,
                              Tag tag,
                              Priority priority,
                              ReadCallback cb) {
    if (scheduler_) {
        PeDmaScheduler::Request req{};
        req.core_id = core_id_;
        req.addr = addr;
        req.bytes = bytes;
        req.tag = tag;
        req.priority = priority;
        req.cb = std::move(cb);
        return scheduler_->submitRead(std::move(req));
    }

    if (!backend_) {
        if (cb) cb(0, addr, {});
        return 0;
    }

    direct_read_pending_ += 1;
    auto wrapped = [this, cb = std::move(cb)](RequestId req_id, uint64_t done_addr, std::vector<uint8_t>&& data) mutable {
        if (direct_read_pending_ > 0) direct_read_pending_ -= 1;
        if (cb) cb(req_id, done_addr, std::move(data));
    };

    const RequestId id = backend_->read(addr, bytes, std::move(wrapped));
    if (id == 0 && direct_read_pending_ > 0) {
        direct_read_pending_ -= 1;
    }
    return id;
}

IMemoryAccess::RequestId
DmaMemAccessProxy::write(uint64_t addr, const std::vector<uint8_t>& data, WriteCallback cb) {
    if (!backend_) {
        if (cb) cb(0, addr);
        return 0;
    }

    write_pending_ += 1;
    auto wrapped = [this, cb = std::move(cb)](RequestId req_id, uint64_t done_addr) mutable {
        if (write_pending_ > 0) write_pending_ -= 1;
        if (cb) cb(req_id, done_addr);
    };

    const RequestId id = backend_->write(addr, data, std::move(wrapped));
    if (id == 0 && write_pending_ > 0) {
        write_pending_ -= 1;
    }
    return id;
}

size_t DmaMemAccessProxy::pendingSize() const {
    const size_t read_pending = scheduler_ ? scheduler_->pendingSizeForCore(core_id_) : direct_read_pending_;
    return read_pending + write_pending_;
}

}} // namespace SST::SnnDL
