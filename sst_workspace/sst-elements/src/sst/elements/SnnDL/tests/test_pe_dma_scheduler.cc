#include <cassert>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <utility>
#include <vector>

#include "api/IDmaTaggedAccess.h"
#include "services/memory/DmaMemAccessProxy.h"
#include "services/memory/PeDmaScheduler.h"

using SST::SnnDL::DmaMemAccessProxy;
using SST::SnnDL::IDmaTaggedAccess;
using SST::SnnDL::IMemoryAccess;
using SST::SnnDL::PeDmaScheduler;

namespace {

class FakeMemAccess final : public IMemoryAccess {
public:
    struct ReadReq {
        RequestId id = 0;
        uint64_t addr = 0;
        size_t bytes = 0;
        ReadCallback cb;
    };

    RequestId read(uint64_t addr, size_t bytes, ReadCallback cb) override {
        const RequestId id = next_id_++;
        pending_.push_back(ReadReq{id, addr, bytes, std::move(cb)});
        return id;
    }

    RequestId write(uint64_t addr, const std::vector<uint8_t>& data, WriteCallback cb) override {
        const RequestId id = next_id_++;
        writes_.push_back(std::make_pair(addr, data.size()));
        if (cb) cb(id, addr);
        return id;
    }

    size_t pendingSize() const override { return pending_.size(); }

    size_t issuedCount() const { return pending_.size(); }

    const ReadReq& front() const { return pending_.front(); }

    void respondFront() {
        assert(!pending_.empty());
        ReadReq req = std::move(pending_.front());
        pending_.pop_front();
        std::vector<uint8_t> data(req.bytes, 0xAB);
        if (req.cb) req.cb(req.id, req.addr, std::move(data));
    }

    size_t writesCount() const { return writes_.size(); }

private:
    RequestId next_id_ = 1;
    std::deque<ReadReq> pending_{};
    std::vector<std::pair<uint64_t, size_t>> writes_{};
};

void test_barrier_tick_respects_priority_across_cores() {
    PeDmaScheduler::Config cfg{};
    cfg.num_cores = 2;
    cfg.bytes_per_cycle = 64;
    cfg.read_engines = 1;

    PeDmaScheduler sched(cfg);
    FakeMemAccess mem0{};
    FakeMemAccess mem1{};
    sched.registerCoreBackend(0, &mem0);
    sched.registerCoreBackend(1, &mem1);

    bool low_done = false;
    bool hi_done = false;

    DmaMemAccessProxy core0(0, &sched, &mem0);
    DmaMemAccessProxy core1(1, &sched, &mem1);

    core0.readTagged(
        0x1000,
        32,
        8,
        IDmaTaggedAccess::Priority::P2,
        [&](IMemoryAccess::RequestId, uint64_t, std::vector<uint8_t>&& data) {
            low_done = !data.empty();
        });
    core1.readTagged(
        0x2000,
        32,
        2,
        IDmaTaggedAccess::Priority::P0,
        [&](IMemoryAccess::RequestId, uint64_t, std::vector<uint8_t>&& data) {
            hi_done = !data.empty();
        });

    sched.onCoreTickEnd(10, 0);
    assert(mem0.issuedCount() == 0);
    assert(mem1.issuedCount() == 0);

    sched.onCoreTickEnd(10, 1);
    assert(mem0.issuedCount() == 0);
    assert(mem1.issuedCount() == 1);
    assert(mem1.front().addr == 0x2000);

    mem1.respondFront();
    assert(hi_done);
    assert(!low_done);

    sched.onCoreTickEnd(11, 0);
    sched.onCoreTickEnd(11, 1);
    assert(mem0.issuedCount() == 1);
    assert(mem0.front().addr == 0x1000);

    mem0.respondFront();
    assert(low_done);
}

void test_proxy_write_passthrough_does_not_use_dma_queue() {
    PeDmaScheduler::Config cfg{};
    cfg.num_cores = 1;
    cfg.bytes_per_cycle = 64;
    cfg.read_engines = 1;

    PeDmaScheduler sched(cfg);
    FakeMemAccess mem{};
    sched.registerCoreBackend(0, &mem);

    DmaMemAccessProxy proxy(0, &sched, &mem);
    bool write_done = false;
    std::vector<uint8_t> payload(16, 0xCD);
    proxy.write(0x3000, payload, [&](IMemoryAccess::RequestId id, uint64_t addr) {
        write_done = (id != 0 && addr == 0x3000);
    });

    assert(write_done);
    assert(mem.writesCount() == 1);
    assert(proxy.pendingSize() == 0);
}

} // namespace

int main() {
    test_barrier_tick_respects_priority_across_cores();
    test_proxy_write_passthrough_does_not_use_dma_queue();
    return 0;
}
