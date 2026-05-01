#include <cassert>
#include <cstdint>
#include <cstring>
#include <vector>

#include "services/synapse/weights/PulseSharedLineService.h"

using SST::SnnDL::PulseSharedLineService;

namespace {

void test_join_and_complete_fanout_same_line() {
    PulseSharedLineService::resetForTests();

    PulseSharedLineService::ServiceKey key{};
    key.scope_id = 7;
    key.window_seq = 3;
    key.line_addr = 0x1000;

    float got_a = 0.0f;
    float got_b = 0.0f;

    const auto join_a = PulseSharedLineService::joinOrRegister(
        key,
        [&](bool ok, uint64_t line_addr, const std::vector<uint8_t>& bytes) {
            assert(ok);
            assert(line_addr == 0x1000u);
            assert(bytes.size() >= 8u);
            std::memcpy(&got_a, bytes.data(), sizeof(float));
        });
    assert(join_a.owner);
    assert(join_a.waiter_count == 1u);
    assert(join_a.active_entries == 1u);

    const auto join_b = PulseSharedLineService::joinOrRegister(
        key,
        [&](bool ok, uint64_t line_addr, const std::vector<uint8_t>& bytes) {
            assert(ok);
            assert(line_addr == 0x1000u);
            assert(bytes.size() >= 8u);
            std::memcpy(&got_b, bytes.data() + sizeof(float), sizeof(float));
        });
    assert(!join_b.owner);
    assert(join_b.waiter_count == 2u);
    assert(join_b.active_entries == 1u);

    std::vector<uint8_t> line(64, 0);
    const float a = 1.25f;
    const float b = 2.5f;
    std::memcpy(line.data(), &a, sizeof(float));
    std::memcpy(line.data() + sizeof(float), &b, sizeof(float));

    const size_t fanout = PulseSharedLineService::complete(key, true, key.line_addr, line);
    assert(fanout == 2u);
    assert(got_a == a);
    assert(got_b == b);
    assert(PulseSharedLineService::activeEntries() == 0u);
    assert(PulseSharedLineService::activePeak() >= 1u);
}

void test_fail_notifies_all_waiters() {
    PulseSharedLineService::resetForTests();

    PulseSharedLineService::ServiceKey key{};
    key.scope_id = 9;
    key.window_seq = 11;
    key.line_addr = 0x2000;

    bool fail_a = false;
    bool fail_b = false;

    (void)PulseSharedLineService::joinOrRegister(
        key,
        [&](bool ok, uint64_t, const std::vector<uint8_t>& bytes) {
            fail_a = !ok && bytes.empty();
        });
    (void)PulseSharedLineService::joinOrRegister(
        key,
        [&](bool ok, uint64_t, const std::vector<uint8_t>& bytes) {
            fail_b = !ok && bytes.empty();
        });

    const size_t fanout = PulseSharedLineService::complete(
        key, false, key.line_addr, std::vector<uint8_t>{});
    assert(fanout == 2u);
    assert(fail_a);
    assert(fail_b);
    assert(PulseSharedLineService::activeEntries() == 0u);
}

} // namespace

int main() {
    test_join_and_complete_fanout_same_line();
    test_fail_notifies_all_waiters();
    return 0;
}
