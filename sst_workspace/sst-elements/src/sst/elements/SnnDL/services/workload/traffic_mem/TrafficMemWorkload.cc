// -*- c++ -*-

#include <sst/core/sst_config.h>

#include "workload/traffic_mem/TrafficMemWorkload.h"

#include <algorithm>
#include <map>
#include <utility>

#include "NocPacketEvent.h"

namespace SST { namespace SnnDL {

TrafficMemWorkload::TrafficMemWorkload() = default;
TrafficMemWorkload::~TrafficMemWorkload() = default;

std::unique_ptr<ICoreWorkload> makeTrafficMemWorkload() {
    return std::make_unique<TrafficMemWorkload>();
}

void TrafficMemWorkload::configureFromParams(const SST::Params& params) {
    stream_.configureFromParams(params);
    traffic_.configureFromParams(params);
}

void TrafficMemWorkload::bindRuntime(const Runtime& rt) {
    stream_.bindRuntime(rt);
    traffic_.bindRuntime(rt);
}

void TrafficMemWorkload::onInitPhase(unsigned phase) {
    stream_.onInitPhase(phase);
    traffic_.onInitPhase(phase);
}

void TrafficMemWorkload::onSetup() {
    stream_.onSetup();
    traffic_.onSetup();
}

void TrafficMemWorkload::onFinish() {
    stream_.onFinish();
    traffic_.onFinish();
}

void TrafficMemWorkload::onGlobalStepStart(uint32_t seq) {
    stream_.onGlobalStepStart(seq);
    traffic_.onGlobalStepStart(seq);
}

void TrafficMemWorkload::resetMembraneState(float v_rest) {
    stream_.resetMembraneState(v_rest);
    traffic_.resetMembraneState(v_rest);
}

bool TrafficMemWorkload::onClockTick(uint64_t now_cycle) {
    const bool traffic_did = traffic_.onClockTick(now_cycle);
    const auto traffic_demand = traffic_.takeSemanticDemand();
    if (!traffic_demand.empty()) {
        StreamWorkload::SemanticMemoryDemand stream_demand{};
        stream_demand.metadata_lookup_demands = traffic_demand.metadata_lookup_demands;
        stream_demand.synapse_gather_demands = traffic_demand.synapse_gather_demands;
        stream_demand.stream_region_demands = traffic_demand.stream_region_demands;
        stream_demand.writeback_region_demands = traffic_demand.writeback_region_demands;
        stream_.enqueueSemanticDemand(stream_demand);
    }
    const bool stream_did = stream_.onClockTick(now_cycle);
    return stream_did || traffic_did;
}

bool TrafficMemWorkload::deliverPacket(NocPacketEvent* packet) {
    if (!packet) return true;
    if (packet->packetKind() == NocPacketKind::RawBytes) {
        return stream_.deliverPacket(packet);
    }
    return traffic_.deliverPacket(packet);
}

bool TrafficMemWorkload::hasWork() const {
    return stream_.hasWork() || traffic_.hasWork();
}

double TrafficMemWorkload::getUtilization() const {
    return std::max(stream_.getUtilization(), traffic_.getUtilization());
}

void TrafficMemWorkload::getStatistics(std::map<std::string, uint64_t>& stats) const {
    std::map<std::string, uint64_t> stream_stats;
    std::map<std::string, uint64_t> traffic_stats;
    stream_.getStatistics(stream_stats);
    traffic_.getStatistics(traffic_stats);
    for (const auto& kv : stream_stats) stats[kv.first] += kv.second;
    for (const auto& kv : traffic_stats) stats[kv.first] += kv.second;
}

}} // namespace SST::SnnDL
