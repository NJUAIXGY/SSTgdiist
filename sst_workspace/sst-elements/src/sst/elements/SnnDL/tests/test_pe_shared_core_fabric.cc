#include <cassert>
#include <cstdint>

#include "api/IPeSharedCoreFabricProvider.h"
#include "services/pe_fabric/PeSharedCoreFabric.h"

using SST::SnnDL::IPeSharedCoreFabricProvider;
using SST::SnnDL::PeSharedCoreFabric;

namespace {

void test_observe_only_ingress_and_pressure_bypass() {
    PeSharedCoreFabric::Config cfg{};
    cfg.enable = true;
    cfg.observe_only = true;
    cfg.ingress_enable = true;
    cfg.num_cores = 4;
    cfg.ingress_entries = 8;
    cfg.core_queue_entries = 4;
    cfg.bypass_mode = PeSharedCoreFabric::BypassMode::HighWatermark;
    cfg.bypass_high_watermark_pct = 50;

    PeSharedCoreFabric fabric(cfg);

    PeSharedCoreFabric::IngressObservation obs{};
    obs.endpoint_id = 1;
    obs.bytes = 64;
    obs.kind = PeSharedCoreFabric::PacketKind::SpikeKey;

    const auto first = fabric.observeIngress(obs);
    assert(first == PeSharedCoreFabric::IngressDecision::ForwardToCore);
    fabric.observeIngressDrain();
    fabric.observeCoreQueueEnqueue(obs.endpoint_id);
    fabric.observeCoreQueueDequeue(obs.endpoint_id);

    assert(fabric.observeIngress(obs) == PeSharedCoreFabric::IngressDecision::ForwardToCore);
    assert(fabric.observeIngress(obs) == PeSharedCoreFabric::IngressDecision::ForwardToCore);
    assert(fabric.observeIngress(obs) == PeSharedCoreFabric::IngressDecision::ForwardToCore);
    assert(fabric.observeIngress(obs) == PeSharedCoreFabric::IngressDecision::ForwardToCore);
    assert(fabric.decideBypass() == PeSharedCoreFabric::IngressDecision::Bypass);

    const auto stats = fabric.snapshotStats();
    assert(stats.ingress_packets_total == 5u);
    assert(stats.ingress_bypass_total == 1u);
    assert(stats.ingress_pressure_cycles_total == 1u);
    assert(stats.ingress_entries_current == 4u);
    assert(stats.ingress_entries_peak >= 4u);
    assert(stats.core_queue_entries_peak >= 1u);
    assert(stats.has_last_observation);
    assert(stats.last_packet_kind == PeSharedCoreFabric::PacketKind::SpikeKey);
    assert(stats.last_endpoint_id == 1);
    assert(stats.last_packet_bytes == 64u);
}

void test_explicit_core_queue_mirror_tracks_peak() {
    PeSharedCoreFabric::Config cfg{};
    cfg.enable = true;
    cfg.observe_only = true;
    cfg.ingress_enable = true;
    cfg.num_cores = 2;
    cfg.ingress_entries = 4;
    cfg.core_queue_entries = 4;

    PeSharedCoreFabric fabric(cfg);

    fabric.observeCoreQueueEnqueue(0);
    fabric.observeCoreQueueEnqueue(0);

    auto stats = fabric.snapshotStats();
    assert(stats.core_queue_entries_current_max == 2u);
    assert(stats.core_queue_entries_peak == 2u);

    fabric.observeCoreQueueDequeue(0);
    fabric.observeCoreQueueDequeue(0);
    stats = fabric.snapshotStats();
    assert(stats.core_queue_entries_current_max == 0u);
}

void test_actual_ingress_dispatch_round_robin_by_endpoint() {
    PeSharedCoreFabric::Config cfg{};
    cfg.enable = true;
    cfg.observe_only = false;
    cfg.ingress_enable = true;
    cfg.num_cores = 3;
    cfg.ingress_entries = 8;
    cfg.core_queue_entries = 4;

    PeSharedCoreFabric fabric(cfg);

    PeSharedCoreFabric::IngressObservation obs{};
    obs.kind = PeSharedCoreFabric::PacketKind::SpikeKey;
    obs.bytes = 64;

    obs.endpoint_id = 0;
    assert(fabric.observeIngress(obs) == PeSharedCoreFabric::IngressDecision::ForwardToCore);
    assert(fabric.enqueueDispatchToken(11, obs.endpoint_id));
    assert(fabric.observeIngress(obs) == PeSharedCoreFabric::IngressDecision::ForwardToCore);
    assert(fabric.enqueueDispatchToken(12, obs.endpoint_id));

    obs.endpoint_id = 1;
    assert(fabric.observeIngress(obs) == PeSharedCoreFabric::IngressDecision::ForwardToCore);
    assert(fabric.enqueueDispatchToken(21, obs.endpoint_id));

    obs.endpoint_id = 2;
    assert(fabric.observeIngress(obs) == PeSharedCoreFabric::IngressDecision::ForwardToCore);
    assert(fabric.enqueueDispatchToken(31, obs.endpoint_id));

    std::vector<PeSharedCoreFabric::DispatchTicket> batch;
    const size_t dispatched = fabric.collectDispatchBatch(3, batch);
    assert(dispatched == 3u);
    assert(batch.size() == 3u);
    assert(batch[0].token == 11u && batch[0].endpoint_id == 0);
    assert(batch[1].token == 21u && batch[1].endpoint_id == 1);
    assert(batch[2].token == 31u && batch[2].endpoint_id == 2);
    assert(fabric.pendingDispatchCount() == 1u);

    batch.clear();
    const size_t dispatched_tail = fabric.collectDispatchBatch(3, batch);
    assert(dispatched_tail == 1u);
    assert(batch.size() == 1u);
    assert(batch[0].token == 12u && batch[0].endpoint_id == 0);
    assert(fabric.pendingDispatchCount() == 0u);
}

void test_actual_ingress_accounting_distinguishes_shared_and_direct_paths() {
    PeSharedCoreFabric::Config cfg{};
    cfg.enable = true;
    cfg.observe_only = false;
    cfg.ingress_enable = true;
    cfg.num_cores = 2;
    cfg.ingress_entries = 4;
    cfg.core_queue_entries = 4;
    cfg.bypass_mode = PeSharedCoreFabric::BypassMode::HighWatermark;
    cfg.bypass_high_watermark_pct = 50; // threshold = 2

    PeSharedCoreFabric fabric(cfg);

    PeSharedCoreFabric::IngressObservation obs{};
    obs.kind = PeSharedCoreFabric::PacketKind::Spike;
    obs.bytes = 32;
    obs.endpoint_id = 0;

    assert(fabric.observeIngress(obs) == PeSharedCoreFabric::IngressDecision::ForwardToCore);
    fabric.observeSharedIngressBuffered();
    assert(fabric.enqueueDispatchToken(1, obs.endpoint_id));

    obs.endpoint_id = 1;
    assert(fabric.observeIngress(obs) == PeSharedCoreFabric::IngressDecision::Bypass);
    fabric.observeDirectDeliver();

    std::vector<PeSharedCoreFabric::DispatchTicket> batch;
    assert(fabric.collectDispatchBatch(2, batch) == 1u);
    assert(batch.size() == 1u);
    fabric.observeSharedDispatch();
    fabric.observeCoreQueueEnqueue(0);
    fabric.observeCoreQueueDequeue(0);

    const auto stats = fabric.snapshotStats();
    assert(stats.ingress_packets_total == 2u);
    assert(stats.ingress_shared_buffered_total == 1u);
    assert(stats.ingress_shared_dispatch_total == 1u);
    assert(stats.ingress_direct_deliver_total == 1u);
    assert(stats.ingress_bypass_total == 1u);
    assert(stats.ingress_pressure_bypass_total == 1u);
    assert(stats.ingress_singleton_bypass_total == 0u);
    assert(stats.ingress_deadline_bypass_total == 0u);
    assert(stats.ingress_core_dispatch_total == 1u);
}

void test_observe_only_harbor_buckets_close_per_step() {
    PeSharedCoreFabric::Config cfg{};
    cfg.enable = true;
    cfg.observe_only = true;
    cfg.harbor_enable = true;
    cfg.num_cores = 4;

    PeSharedCoreFabric fabric(cfg);

    PeSharedCoreFabric::IngressObservation obs{};
    obs.kind = PeSharedCoreFabric::PacketKind::SpikeKey;
    obs.bytes = 64;
    obs.step_seq = 7;

    obs.endpoint_id = 0;
    fabric.observeGatherHarbor(obs);
    fabric.observeGatherHarbor(obs);

    obs.endpoint_id = 1;
    fabric.observeGatherHarbor(obs);

    obs.endpoint_id = 2;
    obs.step_seq = 8;
    fabric.observeGatherHarbor(obs);

    fabric.closeGatherHarborStep(7);

    const auto stats = fabric.snapshotStats();
    assert(stats.harbor_buckets_total == 2u);
    assert(stats.harbor_packet_sum == 3u);
    assert(stats.harbor_consumer_sum == 2u);
    assert(stats.harbor_bucket_peak == 3u);
    assert(stats.harbor_singleton_buckets_total == 1u);
}

void test_harbor_finalize_flushes_open_steps() {
    PeSharedCoreFabric::Config cfg{};
    cfg.enable = true;
    cfg.observe_only = true;
    cfg.harbor_enable = true;
    cfg.num_cores = 2;

    PeSharedCoreFabric fabric(cfg);

    PeSharedCoreFabric::IngressObservation obs{};
    obs.kind = PeSharedCoreFabric::PacketKind::Spike;
    obs.bytes = 32;
    obs.endpoint_id = 1;
    obs.step_seq = 11;

    fabric.observeGatherHarbor(obs);
    fabric.finalizeGatherHarbor();

    const auto stats = fabric.snapshotStats();
    assert(stats.harbor_buckets_total == 1u);
    assert(stats.harbor_packet_sum == 1u);
    assert(stats.harbor_consumer_sum == 1u);
    assert(stats.harbor_bucket_peak == 1u);
    assert(stats.harbor_singleton_buckets_total == 1u);
}

void test_control_plane_queue_preserves_message_order_and_kind_stats() {
    PeSharedCoreFabric::Config cfg{};
    cfg.enable = true;
    cfg.observe_only = false;
    cfg.num_cores = 4;

    PeSharedCoreFabric fabric(cfg);

    PeSharedCoreFabric::ControlMessage frontier{};
    frontier.kind = PeSharedCoreFabric::ControlMessageKind::FrontierExport;
    frontier.scope_id = 1;
    frontier.producer_core_id = 0;
    frontier.object_key = 0xabc0ull;
    frontier.step_seq = 11;
    frontier.window_seq = 3;

    PeSharedCoreFabric::ControlMessage owner{};
    owner.kind = PeSharedCoreFabric::ControlMessageKind::OwnerAnnounce;
    owner.scope_id = 1;
    owner.owner_core_id = 2;
    owner.transaction_id = 0x55ull;
    owner.object_key = 0xabc0ull;

    PeSharedCoreFabric::ControlMessage ready{};
    ready.kind = PeSharedCoreFabric::ControlMessageKind::ReadyFanout;
    ready.scope_id = 1;
    ready.transaction_id = 0x55ull;
    ready.consumer_bitmap = 0x6ull;
    ready.ready_token = 0x99ull;

    assert(fabric.enqueueControlMessage(frontier));
    assert(fabric.enqueueControlMessage(owner));
    assert(fabric.enqueueControlMessage(ready));
    assert(fabric.pendingControlCount() == 3u);
    fabric.observeControlBacklogCycle();
    fabric.observeControlBacklogCycle();

    std::vector<PeSharedCoreFabric::ControlMessage> batch;
    assert(fabric.collectControlBatch(2, batch) == 2u);
    assert(batch.size() == 2u);
    assert(batch[0].kind == PeSharedCoreFabric::ControlMessageKind::FrontierExport);
    assert(batch[0].object_key == 0xabc0ull);
    assert(batch[1].kind == PeSharedCoreFabric::ControlMessageKind::OwnerAnnounce);
    assert(batch[1].owner_core_id == 2);
    assert(fabric.pendingControlCount() == 1u);

    batch.clear();
    assert(fabric.collectControlBatch(4, batch) == 1u);
    assert(batch.size() == 1u);
    assert(batch[0].kind == PeSharedCoreFabric::ControlMessageKind::ReadyFanout);
    assert(batch[0].ready_token == 0x99ull);
    assert(fabric.pendingControlCount() == 0u);

    const auto stats = fabric.snapshotStats();
    assert(stats.control_messages_enqueued_total == 3u);
    assert(stats.control_messages_dequeued_total == 3u);
    assert(stats.control_entries_current == 0u);
    assert(stats.control_entries_peak == 3u);
    assert(stats.control_backlog_cycles_total == 2u);
    assert(stats.control_frontier_export_total == 1u);
    assert(stats.control_frontier_export_consumed_total == 1u);
    assert(stats.control_owner_announce_total == 1u);
    assert(stats.control_owner_announce_consumed_total == 1u);
    assert(stats.control_join_request_total == 0u);
    assert(stats.control_join_request_consumed_total == 0u);
    assert(stats.control_ready_fanout_total == 1u);
    assert(stats.control_ready_fanout_consumed_total == 1u);
    assert(stats.control_join_reject_total == 0u);
    assert(stats.control_join_reject_consumed_total == 0u);
}

void test_provider_contract_is_narrow() {
    IPeSharedCoreFabricProvider* provider = nullptr;
    (void)provider;
}

} // namespace

int main() {
    test_observe_only_ingress_and_pressure_bypass();
    test_explicit_core_queue_mirror_tracks_peak();
    test_actual_ingress_dispatch_round_robin_by_endpoint();
    test_actual_ingress_accounting_distinguishes_shared_and_direct_paths();
    test_observe_only_harbor_buckets_close_per_step();
    test_harbor_finalize_flushes_open_steps();
    test_control_plane_queue_preserves_message_order_and_kind_stats();
    test_provider_contract_is_narrow();
    return 0;
}
