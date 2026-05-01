#include <cassert>
#include <cstdint>

#include "services/pe_fabric/PeSharedCoreFabric.h"
#include "services/pe_fabric/PulseDescriptor.h"

using SST::SnnDL::PeSharedCoreFabric;
using SST::SnnDL::PulseActivationDescriptor;

namespace {

void test_descriptor_lift_uses_packet_threshold_and_drops_singletons() {
    PeSharedCoreFabric::Config cfg{};
    cfg.enable = true;
    cfg.observe_only = true;
    cfg.harbor_enable = true;
    cfg.descriptor_enable = true;
    cfg.descriptor_packet_min = 3;
    cfg.num_cores = 2;

    PeSharedCoreFabric fabric(cfg);

    PeSharedCoreFabric::IngressObservation obs{};
    obs.kind = PeSharedCoreFabric::PacketKind::Spike;
    obs.bytes = 32;
    obs.step_seq = 5;
    obs.endpoint_id = 0;
    obs.descriptor_surrogate_valid = true;
    obs.descriptor_post_block_id = 11;
    obs.descriptor_weight_region_id = 101;
    obs.descriptor_retire_domain_id = 11;
    obs.descriptor_region_safe = true;

    fabric.observeGatherHarbor(obs);
    fabric.observeGatherHarbor(obs);
    fabric.observeGatherHarbor(obs);
    fabric.observeGatherHarbor(obs);

    obs.endpoint_id = 1;
    obs.descriptor_post_block_id = 17;
    obs.descriptor_weight_region_id = 202;
    obs.descriptor_retire_domain_id = 17;
    fabric.observeGatherHarbor(obs);

    fabric.closeGatherHarborStep(5);

    const auto stats = fabric.snapshotStats();
    assert(stats.descriptor_total == 1u);
    assert(stats.descriptor_packet_sum == 4u);
    assert(stats.descriptor_consumer_sum == 1u);
    assert(stats.descriptor_singleton_drop_total == 1u);
}

void test_descriptor_can_merge_across_harbor_endpoints_when_service_key_matches() {
    PeSharedCoreFabric::Config cfg{};
    cfg.enable = true;
    cfg.observe_only = true;
    cfg.harbor_enable = true;
    cfg.descriptor_enable = true;
    cfg.descriptor_packet_min = 8;
    cfg.num_cores = 4;

    PeSharedCoreFabric fabric(cfg);

    PeSharedCoreFabric::IngressObservation obs{};
    obs.kind = PeSharedCoreFabric::PacketKind::SpikeKey;
    obs.bytes = 64;
    obs.step_seq = 9;
    obs.descriptor_surrogate_valid = true;
    obs.descriptor_post_block_id = 3;
    obs.descriptor_weight_region_id = 77;
    obs.descriptor_retire_domain_id = 3;
    obs.descriptor_region_safe = true;

    obs.endpoint_id = 0;
    fabric.observeGatherHarbor(obs);

    obs.endpoint_id = 1;
    fabric.observeGatherHarbor(obs);

    fabric.closeGatherHarborStep(9);

    const auto stats = fabric.snapshotStats();
    assert(stats.harbor_buckets_total == 2u);
    assert(stats.harbor_packet_sum == 2u);
    assert(stats.harbor_consumer_sum == 2u);
    assert(stats.descriptor_total == 1u);
    assert(stats.descriptor_packet_sum == 2u);
    assert(stats.descriptor_consumer_sum == 2u);
    assert(stats.descriptor_singleton_drop_total == 0u);
}

void test_descriptor_header_contract_is_plain_data() {
    PulseActivationDescriptor descriptor{};
    descriptor.step_id = 1;
    descriptor.window_id = 1;
    descriptor.post_block_id = 2;
    descriptor.weight_region_id = 3;
    descriptor.retire_domain_id = 2;
    descriptor.consumer_bitmap = 1u;
    descriptor.consumer_count = 1;
    descriptor.packet_count = 8;
    descriptor.slack_to_apply_close = 0;
    descriptor.region_safe = true;

    assert(descriptor.packet_count == 8u);
    assert(descriptor.region_safe);
}

} // namespace

int main() {
    test_descriptor_lift_uses_packet_threshold_and_drops_singletons();
    test_descriptor_can_merge_across_harbor_endpoints_when_service_key_matches();
    test_descriptor_header_contract_is_plain_data();
    return 0;
}
