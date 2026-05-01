#include <cassert>
#include <cstdint>
#include <vector>

#include "services/synapse/weights/PulseGatherPrebandCollector.h"

using SST::SnnDL::PulseGatherPrebandCollector;

namespace {

void test_deduplicates_aligned_lines_and_keeps_earliest_touch_order() {
    PulseGatherPrebandCollector collector;

    collector.noteLine(9, 0x2104u, 64u, 5u);
    collector.noteLine(9, 0x2130u, 64u, 2u);
    collector.noteLine(9, 0x2188u, 64u, 4u);
    collector.noteLine(9, 0x21c8u, 64u, 1u);

    const auto replay = collector.collect(/*top_bands=*/4u, /*lines_per_band=*/2u);
    assert(replay.size() == 1u);
    assert(replay[0].band_id == 9u);
    assert(replay[0].min_touch_rank == 1u);
    assert(replay[0].selected_line_addrs.size() == 2u);
    assert(replay[0].selected_line_addrs[0] == 0x21c0u);
    assert(replay[0].selected_line_addrs[1] == 0x2100u);
}

void test_groups_by_band_and_limits_top_bands() {
    PulseGatherPrebandCollector collector;

    collector.noteLine(7, 0x3300u, 64u, 7u);
    collector.noteLine(3, 0x3104u, 64u, 3u);
    collector.noteLine(5, 0x3208u, 64u, 1u);

    const auto replay = collector.collect(/*top_bands=*/2u, /*lines_per_band=*/1u);
    assert(replay.size() == 2u);
    assert(replay[0].band_id == 5u);
    assert(replay[0].min_touch_rank == 1u);
    assert(replay[0].selected_line_addrs.size() == 1u);
    assert(replay[0].selected_line_addrs[0] == 0x3200u);
    assert(replay[1].band_id == 3u);
    assert(replay[1].min_touch_rank == 3u);
    assert(replay[1].selected_line_addrs.size() == 1u);
    assert(replay[1].selected_line_addrs[0] == 0x3100u);
}

void test_reset_clears_previous_bands_and_allows_reuse() {
    PulseGatherPrebandCollector collector;

    collector.noteLine(4u, 0x4088u, 64u, 3u);
    collector.noteLine(5u, 0x5088u, 64u, 1u);
    collector.reset();

    collector.noteLine(4u, 0x4088u, 64u, 3u);

    const auto replay = collector.collect(/*top_bands=*/4u, /*lines_per_band=*/2u);
    assert(replay.size() == 1u);
    assert(replay[0].band_id == 4u);
    assert(replay[0].min_touch_rank == 3u);
    assert(replay[0].selected_line_addrs.size() == 1u);
    assert(replay[0].selected_line_addrs[0] == 0x4080u);
}

} // namespace

int main() {
    test_deduplicates_aligned_lines_and_keeps_earliest_touch_order();
    test_groups_by_band_and_limits_top_bands();
    test_reset_clears_previous_bands_and_allows_reuse();
    return 0;
}
