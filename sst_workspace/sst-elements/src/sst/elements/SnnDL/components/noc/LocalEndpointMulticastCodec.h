// -*- c++ -*-
//
// LocalEndpointMulticastCodec:
// - Router local-port endpoint-fanout helper tail.
// - Keeps on-wire packet count low between MulticastRouter and MulticastNIC.
//

#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>
#include <vector>

namespace SST { namespace SnnDL {

static constexpr uint16_t kEndpointFanoutSentinel = 0xffffu;
static constexpr uint16_t kLocalEndpointMaskTailMagic = 0x4c45u; // "LE"
static constexpr uint16_t kLocalEndpointMaskTailVersion = 1u;

struct LocalEndpointMaskTailV1 final {
    uint16_t magic = kLocalEndpointMaskTailMagic;
    uint16_t version = kLocalEndpointMaskTailVersion;
    uint32_t endpoint_mask = 0;
};

inline bool appendLocalEndpointMaskTail(std::vector<uint8_t>& payload, uint32_t endpoint_mask) {
    LocalEndpointMaskTailV1 tail{};
    tail.endpoint_mask = endpoint_mask;
    const size_t off = payload.size();
    payload.resize(off + sizeof(LocalEndpointMaskTailV1));
    std::memcpy(payload.data() + off, &tail, sizeof(LocalEndpointMaskTailV1));
    return true;
}

inline bool extractLocalEndpointMaskTail(const std::vector<uint8_t>& payload,
                                         LocalEndpointMaskTailV1& out_tail,
                                         size_t& out_prefix_bytes) {
    if (payload.size() < sizeof(LocalEndpointMaskTailV1)) return false;
    out_prefix_bytes = payload.size() - sizeof(LocalEndpointMaskTailV1);
    std::memcpy(&out_tail, payload.data() + out_prefix_bytes, sizeof(LocalEndpointMaskTailV1));
    if (out_tail.magic != kLocalEndpointMaskTailMagic) return false;
    if (out_tail.version != kLocalEndpointMaskTailVersion) return false;
    return true;
}

}} // namespace SST::SnnDL

