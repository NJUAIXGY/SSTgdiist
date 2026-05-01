// -*- c++ -*-
//
// ExternalSpikeInputSubsystem implementation
//

#include "ExternalSpikeInputSubsystem.h"

#include <cinttypes>

#include <sst/core/output.h>

#include "GlobalNeuronLayout.h"
#include "INocTransport.h"
#include "NocPacketEvent.h"
#include "events/SpikeEvent.h"
#include "synapse/route/SpikeNocCodec.h"

namespace SST { namespace SnnDL {

#ifndef EXT_SPIKE_LOG
#define EXT_SPIKE_LOG(lvl, ...) do { if (rt_.log) rt_.log->verbose(CALL_INFO, (lvl), 0, __VA_ARGS__); } while(0)
#endif

int ExternalSpikeInputSubsystem::determineTargetUnit_(uint32_t global_neuron_id) const {
    if (rt_.layout && rt_.layout->valid()) {
        const uint64_t gid = static_cast<uint64_t>(global_neuron_id);
        if (!rt_.layout->isLocalToNode(gid, static_cast<uint32_t>(rt_.node_id))) return -1;
        const uint32_t core = rt_.layout->coreOf(gid);
        return (core < static_cast<uint32_t>(rt_.num_cores)) ? static_cast<int>(core) : -1;
    }
    if (rt_.num_cores <= 0 || rt_.neurons_per_core <= 0 || rt_.total_neurons <= 0) return -1;

    const int64_t local_neuron_id =
        static_cast<int64_t>(global_neuron_id) - static_cast<int64_t>(rt_.global_neuron_base);
    if (local_neuron_id < 0 || local_neuron_id >= static_cast<int64_t>(rt_.total_neurons)) return -1;

    const int target_unit = static_cast<int>(local_neuron_id) / rt_.neurons_per_core;
    if (target_unit < 0 || target_unit >= rt_.num_cores) return -1;
    return target_unit;
}

void ExternalSpikeInputSubsystem::onSpike(SpikeEvent* spike) {
    if (!spike) return;
    if (!rt_.enabled) {
        delete spike;
        return;
    }

    if (!rt_.noc || !rt_.layout || !rt_.layout->valid()) {
        delete spike;
        return;
    }

    const uint32_t dst_node = spike->getDestinationNode();
    if (dst_node != static_cast<uint32_t>(rt_.node_id)) {
        delete spike;
        return;
    }

    const int dst_core = determineTargetUnit_(spike->getDestinationNeuron());
    if (dst_core < 0) {
        EXT_SPIKE_LOG(4, "[stimulus][external-spike] drop: dst_neuron=%u not local to node=%d base=0x%" PRIx64 " total=%d\n",
                      spike->getDestinationNeuron(), rt_.node_id, rt_.global_neuron_base, rt_.total_neurons);
        delete spike;
        return;
    }

    NocPacketEvent* pkt = SpikeNocCodec::encode(*spike, *rt_.layout);
    delete spike;
    if (!pkt) return;
    rt_.noc->injectLocal(dst_core, pkt);
}

}} // namespace SST::SnnDL
