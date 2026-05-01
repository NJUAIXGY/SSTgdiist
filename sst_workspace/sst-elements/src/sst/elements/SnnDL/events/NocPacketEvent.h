// -*- c++ -*-
//
// NocPacketEvent:
// - NoC 传输的通用数据包事件（payload-agnostic）
// - 仅包含“路由头 + 不透明 payload 字节”，不携带任何 Spike/BCSR/权重语义
//

#ifndef SNNDL_NOC_PACKET_EVENT_H
#define SNNDL_NOC_PACKET_EVENT_H

#include <cstdint>
#include <vector>

#include <sst/core/event.h>
#include <sst/core/serialization/serialize.h>

namespace SST { namespace SnnDL {

enum class NocPacketKind : uint16_t {
    Unknown = 0,
    Spike = 1,
    Control = 2,
    RawBytes = 3,
    SpikeKey = 4,
    SpikeTileKey = 5,
};

class NocPacketEvent : public SST::Event {
public:
    static constexpr uint16_t kDefaultMaxHops = 10;

    uint32_t src_node = 0;
    uint32_t dst_node = 0;
    uint16_t src_endpoint = 0;
    uint16_t dst_endpoint = 0;
    uint16_t kind = static_cast<uint16_t>(NocPacketKind::Unknown);
    uint16_t hop_count = 0;
    // Global step sequencing (optional; 0 means "no step tag").
    // Semantics: packet should be *processed* in step_seq (not necessarily *sent* in that step).
    // Used to disable within-step cascading in step-limited experiments (naive_raw baseline).
    uint32_t step_seq = 0;
    uint64_t timestamp = 0;  // 由上层定义（ns/cycle），NoC 不解释
    std::vector<uint8_t> payload;

    NocPacketEvent() = default;

    NocPacketEvent(uint32_t src_node_,
                   uint32_t dst_node_,
                   uint16_t src_ep_,
                   uint16_t dst_ep_,
                   NocPacketKind kind_,
                   uint64_t ts)
        : SST::Event(),
          src_node(src_node_),
          dst_node(dst_node_),
          src_endpoint(src_ep_),
          dst_endpoint(dst_ep_),
          kind(static_cast<uint16_t>(kind_)),
          timestamp(ts)
    {}

    NocPacketEvent* clone() override {
        auto* ev = new NocPacketEvent();
        ev->src_node = src_node;
        ev->dst_node = dst_node;
        ev->src_endpoint = src_endpoint;
        ev->dst_endpoint = dst_endpoint;
        ev->kind = kind;
        ev->hop_count = hop_count;
        ev->step_seq = step_seq;
        ev->timestamp = timestamp;
        ev->payload = payload;
        return ev;
    }

    NocPacketKind packetKind() const { return static_cast<NocPacketKind>(kind); }

    void serialize_order(SST::Core::Serialization::serializer& ser) override {
        Event::serialize_order(ser);
        SST_SER(src_node);
        SST_SER(dst_node);
        SST_SER(src_endpoint);
        SST_SER(dst_endpoint);
        SST_SER(kind);
        SST_SER(hop_count);
        SST_SER(step_seq);
        SST_SER(timestamp);
        SST_SER(payload);
    }

private:
    ImplementSerializable(SST::SnnDL::NocPacketEvent)
};

}} // namespace SST::SnnDL

#endif // SNNDL_NOC_PACKET_EVENT_H
