#include "services/synapse/weights/PulseMetadataLookupRegistry.h"

#include <cassert>
#include <cstdint>

using SST::SnnDL::PulseMetadataLookupRegistry;

int main() {
    constexpr uint32_t kScope = 7;
    constexpr uint32_t kWindow = 11;
    constexpr uint32_t kPre = 1234;

    PulseMetadataLookupRegistry::closeWindow(kScope, kWindow);

    const auto miss = PulseMetadataLookupRegistry::findPreBase(kScope, kWindow, kPre, /*core_id=*/0);
    assert(!miss.hit);

    const auto first = PulseMetadataLookupRegistry::publishPreBase(
        kScope, kWindow, kPre, /*base=*/4096, /*len=*/64, /*core_id=*/0);
    assert(first.owner_fill);
    assert(!first.shared_hit);
    assert(first.base == 4096);
    assert(first.len == 64);
    assert(first.consumer_count == 1);

    const auto second = PulseMetadataLookupRegistry::findPreBase(kScope, kWindow, kPre, /*core_id=*/1);
    assert(second.hit);
    assert(!second.owner_fill);
    assert(second.shared_hit);
    assert(second.base == 4096);
    assert(second.len == 64);
    assert(second.consumer_count == 2);

    const auto third = PulseMetadataLookupRegistry::findPreBase(kScope, kWindow, kPre, /*core_id=*/1);
    assert(third.hit);
    assert(third.shared_hit);
    assert(third.consumer_count == 3);

    PulseMetadataLookupRegistry::closeWindow(kScope, kWindow);
    const auto cleared = PulseMetadataLookupRegistry::findPreBase(kScope, kWindow, kPre, /*core_id=*/2);
    assert(!cleared.hit);

    return 0;
}
