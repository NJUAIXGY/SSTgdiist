// -*- c++ -*-

#include "SpikeNocCodec.h"

#include "NocPacketEvent.h"
#include "events/SpikeEvent.h"

namespace SST { namespace SnnDL {

NocPacketEvent* SpikeNocCodec::encode(const SpikeEvent& spike, const GlobalNeuronLayout& layout) {
    const uint64_t src_global = static_cast<uint64_t>(spike.getSourceNeuron());
    const uint64_t dst_global = static_cast<uint64_t>(spike.getDestinationNeuron());

    auto* pkt = new NocPacketEvent();
    pkt->src_node = layout.nodeOf(src_global);
    pkt->dst_node = layout.nodeOf(dst_global);
    pkt->src_endpoint = static_cast<uint16_t>(layout.coreOf(src_global));
    pkt->dst_endpoint = static_cast<uint16_t>(layout.coreOf(dst_global));
    pkt->kind = static_cast<uint16_t>(NocPacketKind::Spike);
    pkt->hop_count = static_cast<uint16_t>(spike.getHopCount());
    pkt->timestamp = spike.getTimestamp();

    WireSpike ws;
    ws.src_neuron = spike.getSourceNeuron();
    ws.dst_neuron = spike.getDestinationNeuron();
    ws.weight = spike.getWeight();
    ws.timestamp = spike.getTimestamp();

    pkt->payload.resize(sizeof(WireSpike));
    std::memcpy(pkt->payload.data(), &ws, sizeof(WireSpike));
    return pkt;
}

SpikeEvent* SpikeNocCodec::decode(const NocPacketEvent& pkt) {
    if (pkt.payload.size() != sizeof(WireSpike)) return nullptr;
    WireSpike ws;
    std::memcpy(&ws, pkt.payload.data(), sizeof(WireSpike));

    auto* spike = new SpikeEvent(ws.src_neuron, ws.dst_neuron, pkt.dst_node, ws.weight, ws.timestamp);
    spike->hop_count = pkt.hop_count;
    return spike;
}

}} // namespace SST::SnnDL
