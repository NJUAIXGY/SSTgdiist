// -*- c++ -*-
//
// SpikePacketBridge implementation
//

#include <sst/core/sst_config.h>

#include "SpikePacketBridge.h"

#include <sst/core/output.h>

#include "GlobalNeuronLayout.h"
#include "INocTransport.h"
#include "NocPacketEvent.h"
#include "events/SpikeEvent.h"
#include "SpikeNocCodec.h"

namespace SST { namespace SnnDL {

int SpikePacketBridge::computeSourceCore_(uint64_t src_global) const {
    if (!rt_.layout || !rt_.layout->valid()) return 0;
    if (rt_.num_cores <= 0) return 0;
    if (!rt_.layout->isLocalToNode(src_global, static_cast<uint32_t>(rt_.node_id))) return 0;
    const uint32_t core = rt_.layout->coreOf(src_global);
    if (core >= static_cast<uint32_t>(rt_.num_cores)) return 0;
    return static_cast<int>(core);
}

void SpikePacketBridge::deliverPacketToEndpoint(int endpoint_id, NocPacketEvent* packet) {
    if (!packet) return;
    SpikeEvent* spike = SpikeNocCodec::decode(*packet);
    delete packet;
    if (!spike) return;
    if (!rt_.deliver_to_core) {
        delete spike;
        return;
    }
    rt_.deliver_to_core(endpoint_id, spike);
}

void SpikePacketBridge::sendFromCore(int src_core, SpikeEvent* spike) {
    if (!spike) return;
    if (!rt_.noc || !rt_.layout || !rt_.layout->valid()) {
        delete spike;
        return;
    }
    if (src_core < 0) src_core = 0;
    if (rt_.num_cores <= 0) rt_.num_cores = 1;
    if (src_core >= rt_.num_cores) src_core = rt_.num_cores - 1;

    NocPacketEvent* pkt = SpikeNocCodec::encode(*spike, *rt_.layout);
    delete spike;
    if (!pkt) return;

    pkt->src_endpoint = static_cast<uint16_t>(src_core);
    if (rt_.active_step_seq && *rt_.active_step_seq != 0) {
        pkt->step_seq = (*rt_.active_step_seq) + rt_.step_seq_offset;
    }
    rt_.noc->sendFromCore(src_core, pkt);
}

void SpikePacketBridge::sendAuto(SpikeEvent* spike) {
    if (!spike) return;
    if (!rt_.noc || !rt_.layout || !rt_.layout->valid()) {
        delete spike;
        return;
    }

    const uint64_t src_global = static_cast<uint64_t>(spike->getSourceNeuron());
    const int src_core = computeSourceCore_(src_global);

    NocPacketEvent* pkt = SpikeNocCodec::encode(*spike, *rt_.layout);
    delete spike;
    if (!pkt) return;

    // 保守：以注入端 core_id 覆盖 src_endpoint，避免上层未按 global_id 口径填充导致偏差。
    pkt->src_endpoint = static_cast<uint16_t>(src_core);
    if (rt_.active_step_seq && *rt_.active_step_seq != 0) {
        pkt->step_seq = (*rt_.active_step_seq) + rt_.step_seq_offset;
    }
    rt_.noc->sendFromCore(src_core, pkt);
}

void SpikePacketBridge::sendExternal(SpikeEvent* spike) {
    if (!spike) return;
    if (!rt_.noc || !rt_.layout || !rt_.layout->valid()) {
        delete spike;
        return;
    }
    NocPacketEvent* pkt = SpikeNocCodec::encode(*spike, *rt_.layout);
    delete spike;
    if (!pkt) return;
    if (rt_.active_step_seq && *rt_.active_step_seq != 0) {
        pkt->step_seq = (*rt_.active_step_seq) + rt_.step_seq_offset;
    }
    rt_.noc->sendExternal(pkt);
}

}} // namespace SST::SnnDL
