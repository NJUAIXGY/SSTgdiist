#ifndef SNNDL_SPIKE_PACKET_H
#define SNNDL_SPIKE_PACKET_H

#include <cstdint>
#include <vector>
#include "events/SpikeEvent.h"

namespace SST { namespace SnnDL {

// Basic spike packet header used by receiver/sender modules
struct SpikePacketHeader {
    uint8_t packet_type;     // 0x01 spike data, others reserved
    uint8_t version;         // protocol version
    uint16_t flags;          // control flags
    uint32_t source_node;    // source node id
    uint32_t dest_node;      // dest node id
    uint64_t sequence_num;   // sequence number
    uint64_t timestamp;      // sender timestamp
    uint32_t spike_count;    // number of spikes in payload
    uint32_t payload_size;   // payload bytes
    uint32_t checksum;       // simple checksum if used
};

struct SpikePacket {
    SpikePacketHeader header;
    std::vector<SpikeEvent> spikes;
};

}} // namespace

#endif // SNNDL_SPIKE_PACKET_H
