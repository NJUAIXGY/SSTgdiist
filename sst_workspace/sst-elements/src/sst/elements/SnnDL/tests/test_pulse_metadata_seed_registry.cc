#include <cassert>
#include <cstdint>

#include "services/synapse/weights/PulseMetadataSeedRegistry.h"

using SST::SnnDL::PulseMetadataSeedRegistry;

namespace {

void test_shared_pre_base_uses_aligned_seed_line() {
    PulseMetadataSeedRegistry::resetForTests();

    const auto first = PulseMetadataSeedRegistry::registerBaseCandidate(
        3, 9, 128, 0x1084u, 64u, 0);
    assert(!first.trigger_seed);
    assert(first.selected_line_addr == 0x1080u);

    const auto second = PulseMetadataSeedRegistry::registerBaseCandidate(
        3, 9, 128, 0x1090u, 64u, 1);
    assert(second.trigger_seed);
    assert(second.prior_consumers == 1u);
    assert(second.consumers_after == 2u);
    assert(second.selected_line_addr == 0x1080u);
}

void test_shared_pre_base_keeps_minimum_aligned_line() {
    PulseMetadataSeedRegistry::resetForTests();

    (void)PulseMetadataSeedRegistry::registerBaseCandidate(
        7, 4, 512, 0x11c4u, 64u, 2);
    const auto second = PulseMetadataSeedRegistry::registerBaseCandidate(
        7, 4, 512, 0x1188u, 64u, 3);
    assert(second.trigger_seed);
    assert(second.selected_line_addr == 0x1180u);
}

void test_shared_pre_band_triggers_single_owner_with_bounded_lines() {
    PulseMetadataSeedRegistry::resetForTests();

    const auto first = PulseMetadataSeedRegistry::registerBandCandidate(
        5, 11, 9, 0x2104u, 64u, 0, 2);
    assert(!first.trigger_seed);
    assert(first.selected_line_addrs.size() == 1u);
    assert(first.selected_line_addrs[0] == 0x2100u);

    (void)PulseMetadataSeedRegistry::registerBandCandidate(
        5, 11, 9, 0x2148u, 64u, 0, 2);
    const auto second = PulseMetadataSeedRegistry::registerBandCandidate(
        5, 11, 9, 0x2181u, 64u, 1, 2);
    assert(second.trigger_seed);
    assert(second.prior_consumers == 1u);
    assert(second.consumers_after == 2u);
    assert(second.selected_line_addrs.size() == 2u);
    assert(second.selected_line_addrs[0] == 0x2100u);
    assert(second.selected_line_addrs[1] == 0x2140u);

    const auto later = PulseMetadataSeedRegistry::registerBandCandidate(
        5, 11, 9, 0x21c8u, 64u, 2, 2);
    assert(!later.trigger_seed);
    assert(later.selected_line_addrs.size() == 2u);
    assert(later.selected_line_addrs[0] == 0x2100u);
    assert(later.selected_line_addrs[1] == 0x2140u);
}

void test_gather_preband_batch_merges_lines_once_per_core() {
    PulseMetadataSeedRegistry::resetForTests();

    std::vector<uint64_t> first_lines{0x3100u, 0x3140u};
    const auto first = PulseMetadataSeedRegistry::registerGatherBandCandidate(
        5, 11, 9, first_lines, 0, 3);
    assert(!first.trigger_seed);
    assert(first.prior_consumers == 0u);
    assert(first.consumers_after == 1u);
    assert(first.selected_line_addrs.size() == 2u);
    assert(first.selected_line_addrs[0] == 0x3100u);
    assert(first.selected_line_addrs[1] == 0x3140u);

    std::vector<uint64_t> second_lines{0x3140u, 0x3180u};
    const auto second = PulseMetadataSeedRegistry::registerGatherBandCandidate(
        5, 11, 9, second_lines, 1, 3);
    assert(second.trigger_seed);
    assert(second.prior_consumers == 1u);
    assert(second.consumers_after == 2u);
    assert(second.selected_line_addrs.size() == 3u);
    assert(second.selected_line_addrs[0] == 0x3100u);
    assert(second.selected_line_addrs[1] == 0x3140u);
    assert(second.selected_line_addrs[2] == 0x3180u);

    std::vector<uint64_t> later_lines{0x31c0u};
    const auto later = PulseMetadataSeedRegistry::registerGatherBandCandidate(
        5, 11, 9, later_lines, 1, 3);
    assert(!later.trigger_seed);
    assert(later.prior_consumers == 2u);
    assert(later.consumers_after == 2u);
    assert(later.selected_line_addrs.size() == 3u);
    assert(later.selected_line_addrs[0] == 0x3100u);
    assert(later.selected_line_addrs[1] == 0x3140u);
    assert(later.selected_line_addrs[2] == 0x3180u);
}

void test_gather_preband_batch_respects_min_consumers_threshold() {
    PulseMetadataSeedRegistry::resetForTests();

    std::vector<uint64_t> first_lines{0x4100u, 0x4140u};
    const auto first = PulseMetadataSeedRegistry::registerGatherBandCandidate(
        6, 12, 10, first_lines, 0, 3, 3);
    assert(!first.trigger_seed);
    assert(first.prior_consumers == 0u);
    assert(first.consumers_after == 1u);

    std::vector<uint64_t> second_lines{0x4140u, 0x4180u};
    const auto second = PulseMetadataSeedRegistry::registerGatherBandCandidate(
        6, 12, 10, second_lines, 1, 3, 3);
    assert(!second.trigger_seed);
    assert(second.prior_consumers == 1u);
    assert(second.consumers_after == 2u);
    assert(second.selected_line_addrs.size() == 3u);
    assert(second.selected_line_addrs[0] == 0x4100u);
    assert(second.selected_line_addrs[1] == 0x4140u);
    assert(second.selected_line_addrs[2] == 0x4180u);

    std::vector<uint64_t> third_lines{0x41c0u};
    const auto third = PulseMetadataSeedRegistry::registerGatherBandCandidate(
        6, 12, 10, third_lines, 2, 3, 3);
    assert(third.trigger_seed);
    assert(third.prior_consumers == 2u);
    assert(third.consumers_after == 3u);
    assert(third.selected_line_addrs.size() == 3u);
    assert(third.selected_line_addrs[0] == 0x4100u);
    assert(third.selected_line_addrs[1] == 0x4140u);
    assert(third.selected_line_addrs[2] == 0x4180u);
}

void test_gather_preband_probe_reflects_trigger_state_and_selected_lines() {
    PulseMetadataSeedRegistry::resetForTests();

    std::vector<uint64_t> first_lines{0x5100u, 0x5140u};
    (void)PulseMetadataSeedRegistry::registerGatherBandCandidate(
        8, 15, 21, first_lines, 0, 3, 2);

    const auto first_probe = PulseMetadataSeedRegistry::probeGatherBand(8, 15, 21);
    assert(first_probe.valid);
    assert(!first_probe.seed_triggered);
    assert(first_probe.consumer_count == 1u);
    assert(first_probe.selected_line_addrs.size() == 2u);
    assert(first_probe.selected_line_addrs[0] == 0x5100u);
    assert(first_probe.selected_line_addrs[1] == 0x5140u);

    std::vector<uint64_t> second_lines{0x5140u, 0x5180u};
    (void)PulseMetadataSeedRegistry::registerGatherBandCandidate(
        8, 15, 21, second_lines, 1, 3, 2);

    const auto second_probe = PulseMetadataSeedRegistry::probeGatherBand(8, 15, 21);
    assert(second_probe.valid);
    assert(second_probe.seed_triggered);
    assert(second_probe.consumer_count == 2u);
    assert(second_probe.selected_line_addrs.size() == 3u);
    assert(second_probe.selected_line_addrs[0] == 0x5100u);
    assert(second_probe.selected_line_addrs[1] == 0x5140u);
    assert(second_probe.selected_line_addrs[2] == 0x5180u);
}

} // namespace

int main() {
    test_shared_pre_base_uses_aligned_seed_line();
    test_shared_pre_base_keeps_minimum_aligned_line();
    test_shared_pre_band_triggers_single_owner_with_bounded_lines();
    test_gather_preband_batch_merges_lines_once_per_core();
    test_gather_preband_batch_respects_min_consumers_threshold();
    test_gather_preband_probe_reflects_trigger_state_and_selected_lines();
    return 0;
}
