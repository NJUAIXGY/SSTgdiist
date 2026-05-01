// -*- c++ -*-
//
// NocPacketBatchEvent:
// - NoC 侧的通用批量包事件（payload-agnostic）
// - 仅用于 NIC/链路层的“打包优化”，不携带任何 Spike/BCSR/权重语义
//

#ifndef SNNDL_NOC_PACKET_BATCH_EVENT_H
#define SNNDL_NOC_PACKET_BATCH_EVENT_H

#include <cstdint>
#include <vector>

#include <sst/core/event.h>
#include <sst/core/serialization/serialize.h>

namespace SST { namespace SnnDL {

class NocPacketBatchEvent : public SST::Event {
public:
    struct PackedPacket {
        uint16_t src_endpoint = 0;
        uint16_t dst_endpoint = 0;
        uint16_t kind = 0;
        uint16_t hop_count = 0;
        uint32_t step_seq = 0;
        uint64_t timestamp = 0;
        std::vector<uint8_t> payload;

        void serialize_order(SST::Core::Serialization::serializer& ser) {
            SST_SER(src_endpoint);
            SST_SER(dst_endpoint);
            SST_SER(kind);
            SST_SER(hop_count);
            SST_SER(step_seq);
            SST_SER(timestamp);
            SST_SER(payload);
        }
    };

    uint32_t src_node = 0;
    uint32_t dst_node = 0;
    uint64_t batch_timestamp = 0;
    std::vector<PackedPacket> packets;

    void serialize_order(SST::Core::Serialization::serializer& ser) override {
        Event::serialize_order(ser);
        SST_SER(src_node);
        SST_SER(dst_node);
        SST_SER(batch_timestamp);
        SST_SER(packets);
    }

private:
    ImplementSerializable(SST::SnnDL::NocPacketBatchEvent)
};

}} // namespace SST::SnnDL

#endif // SNNDL_NOC_PACKET_BATCH_EVENT_H
