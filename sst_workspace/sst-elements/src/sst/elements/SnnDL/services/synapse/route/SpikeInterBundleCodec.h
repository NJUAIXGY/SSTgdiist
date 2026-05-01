// -*- c++ -*-
//
// SpikeInterBundleCodec:
// - Inter-block destination-set bundle codec for SpikeKey / SpikeTileKey packets.
// - A bundle payload carries multiple per-block route payloads so routers can split by direction in-network.
//

#pragma once

#include <array>
#include <cstdint>
#include <cstring>
#include <limits>
#include <type_traits>
#include <vector>

#include "api/MulticastLimits.h"

namespace SST { namespace SnnDL {

class SpikeInterBundleCodec final {
public:
    static constexpr uint32_t kMagic = 0x53424e44u; // "SBND"
    static constexpr uint16_t kVersionV1 = 1;
    static constexpr uint16_t kVersionV2 = 2;
    static constexpr uint16_t kVersionV3 = 3;
    static constexpr uint16_t kEntryFlagCompactRouteV3 = 0x1u;

    struct WireBundlePrefixV1 final {
        uint32_t magic = kMagic;
        uint16_t version = kVersionV1;
        uint16_t reserved0 = 0;
        uint16_t packet_kind = 0; // NocPacketKind::SpikeKey / SpikeTileKey
        uint16_t reserved1 = 0;
        uint32_t entry_count = 0;
        uint64_t bundle_id = 0;
    };

    static_assert(
        std::is_trivially_copyable<WireBundlePrefixV1>::value,
        "WireBundlePrefixV1 must be trivially copyable");

    struct WireEntryPrefixV1 final {
        uint32_t payload_bytes = 0;
    };

    static_assert(
        std::is_trivially_copyable<WireEntryPrefixV1>::value,
        "WireEntryPrefixV1 must be trivially copyable");

    struct WireBundlePrefixV2 final {
        uint32_t magic = kMagic;
        uint16_t version = kVersionV2;
        uint16_t route_mode = 0; // 1=SpikeKey, 2=SpikeTileKey
        uint16_t packet_kind = 0;
        uint16_t stage = 0;      // INTER stage
        uint16_t block_w_h = 0;  // shared block shape
        uint16_t reserved0 = 0;
        uint32_t entry_count = 0;
        uint64_t bundle_id = 0;
    };

    static_assert(
        std::is_trivially_copyable<WireBundlePrefixV2>::value,
        "WireBundlePrefixV2 must be trivially copyable");

    struct WireEntryMetaV2 final {
        uint32_t block_id = 0;
        uint32_t ingress_node = 0;
        uint32_t pre_global = 0;
        uint64_t group_id = 0;
        uint16_t tile_version = 0; // 0 for SpikeKey entries
        uint16_t reserved0 = 0;
        uint32_t tile_block_col = 0;
        uint64_t tile_pre_mask = 0;
    };

    static_assert(
        std::is_trivially_copyable<WireEntryMetaV2>::value,
        "WireEntryMetaV2 must be trivially copyable");

    struct BundleEntryV2 final {
        WireEntryMetaV2 meta{};
        std::array<uint32_t, kMaxMulticastBlockCells> core_mask{};
    };

    struct WireBundlePrefixV3 final {
        uint32_t magic = kMagic;
        uint16_t version = kVersionV3;
        uint16_t route_mode = 0; // 1=SpikeKey, 2=SpikeTileKey
        uint16_t packet_kind = 0;
        uint16_t stage = 0;      // INTER/INTRA stage
        uint16_t block_w = 0;
        uint16_t block_h = 0;
        uint16_t block_d = 1;
        uint16_t reserved0 = 0;
        uint32_t entry_count = 0;
        uint64_t bundle_id = 0;
    };

    static_assert(
        std::is_trivially_copyable<WireBundlePrefixV3>::value,
        "WireBundlePrefixV3 must be trivially copyable");

    struct WireEntryMetaV3 final {
        uint32_t block_id = 0;
        uint32_t block_z = 0;
        uint32_t ingress_node = 0;
        uint32_t pre_global = 0;
        uint64_t group_id = 0;
        uint16_t tile_version = 0; // 0 for SpikeKey entries
        uint16_t reserved0 = 0;
        uint32_t tile_block_col = 0;
        uint64_t tile_pre_mask = 0;
    };

    static_assert(
        std::is_trivially_copyable<WireEntryMetaV3>::value,
        "WireEntryMetaV3 must be trivially copyable");

    struct BundleEntryV3 final {
        WireEntryMetaV3 meta{};
        std::array<uint32_t, kMaxMulticastBlockCells> core_mask{};
    };

    static uint32_t blockCellsFromBlockWH(uint16_t block_w_h) {
        const uint32_t block_w = static_cast<uint32_t>((block_w_h >> 8) & 0xffu);
        const uint32_t block_h = static_cast<uint32_t>(block_w_h & 0xffu);
        const uint32_t block_cells = block_w * block_h;
        if (block_w == 0 || block_h == 0) return 0;
        if (block_cells == 0 || block_cells > kMaxMulticastBlockCells) return 0;
        return block_cells;
    }

    static uint32_t blockCellsFromBlockShape(uint16_t block_w, uint16_t block_h, uint16_t block_d) {
        const uint64_t block_cells =
            static_cast<uint64_t>(block_w) *
            static_cast<uint64_t>(block_h) *
            static_cast<uint64_t>(block_d);
        if (block_w == 0 || block_h == 0 || block_d == 0) return 0;
        if (block_cells == 0 || block_cells > static_cast<uint64_t>(kMaxMulticastBlockCells)) return 0;
        return static_cast<uint32_t>(block_cells);
    }

    static bool decodeVersion(const std::vector<uint8_t>& payload, uint16_t& out_version) {
        out_version = 0;
        if (payload.size() < sizeof(uint32_t) + sizeof(uint16_t)) return false;
        uint32_t magic = 0;
        std::memcpy(&magic, payload.data(), sizeof(magic));
        if (magic != kMagic) return false;
        std::memcpy(&out_version, payload.data() + sizeof(uint32_t), sizeof(out_version));
        return (out_version == kVersionV1 || out_version == kVersionV2 || out_version == kVersionV3);
    }

    static bool isBundlePayload(const std::vector<uint8_t>& payload, WireBundlePrefixV1* out_prefix = nullptr) {
        uint16_t version = 0;
        if (!decodeVersion(payload, version)) return false;
        if (version == kVersionV1) {
            if (payload.size() < sizeof(WireBundlePrefixV1)) return false;
            WireBundlePrefixV1 p{};
            std::memcpy(&p, payload.data(), sizeof(WireBundlePrefixV1));
            if (out_prefix) *out_prefix = p;
            return true;
        }
        if (version == kVersionV2) {
            if (payload.size() < sizeof(WireBundlePrefixV2)) return false;
            if (out_prefix) {
                WireBundlePrefixV2 p2{};
                std::memcpy(&p2, payload.data(), sizeof(WireBundlePrefixV2));
                WireBundlePrefixV1 mapped{};
                mapped.magic = p2.magic;
                mapped.version = p2.version;
                mapped.packet_kind = p2.packet_kind;
                mapped.entry_count = p2.entry_count;
                mapped.bundle_id = p2.bundle_id;
                *out_prefix = mapped;
            }
            return true;
        }
        if (version == kVersionV3) {
            if (payload.size() < sizeof(WireBundlePrefixV3)) return false;
            if (out_prefix) {
                WireBundlePrefixV3 p3{};
                std::memcpy(&p3, payload.data(), sizeof(WireBundlePrefixV3));
                WireBundlePrefixV1 mapped{};
                mapped.magic = p3.magic;
                mapped.version = p3.version;
                mapped.packet_kind = p3.packet_kind;
                mapped.entry_count = p3.entry_count;
                mapped.bundle_id = p3.bundle_id;
                *out_prefix = mapped;
            }
            return true;
        }
        return false;
    }

    static bool encode(uint16_t packet_kind,
                       uint64_t bundle_id,
                       const std::vector<std::vector<uint8_t>>& entries,
                       std::vector<uint8_t>& out_payload) {
        if (entries.empty()) return false;
        if (entries.size() > static_cast<size_t>(std::numeric_limits<uint32_t>::max())) return false;

        size_t total = sizeof(WireBundlePrefixV1);
        for (const auto& entry_payload : entries) {
            if (entry_payload.empty()) return false;
            if (entry_payload.size() > static_cast<size_t>(std::numeric_limits<uint32_t>::max())) return false;
            total += sizeof(WireEntryPrefixV1) + entry_payload.size();
        }
        if (total > static_cast<size_t>(std::numeric_limits<uint32_t>::max())) return false;

        out_payload.resize(total);
        size_t off = 0;

        WireBundlePrefixV1 prefix{};
        prefix.packet_kind = packet_kind;
        prefix.entry_count = static_cast<uint32_t>(entries.size());
        prefix.bundle_id = bundle_id;
        std::memcpy(out_payload.data() + off, &prefix, sizeof(prefix));
        off += sizeof(prefix);

        for (const auto& entry_payload : entries) {
            WireEntryPrefixV1 ep{};
            ep.payload_bytes = static_cast<uint32_t>(entry_payload.size());
            std::memcpy(out_payload.data() + off, &ep, sizeof(ep));
            off += sizeof(ep);
            std::memcpy(out_payload.data() + off, entry_payload.data(), entry_payload.size());
            off += entry_payload.size();
        }
        return true;
    }

    static bool decode(const std::vector<uint8_t>& payload,
                       WireBundlePrefixV1& out_prefix,
                       std::vector<std::vector<uint8_t>>& out_entries) {
        out_entries.clear();
        if (!isBundlePayload(payload, &out_prefix)) return false;
        if (out_prefix.version != kVersionV1) return false;

        size_t off = sizeof(WireBundlePrefixV1);
        out_entries.reserve(static_cast<size_t>(out_prefix.entry_count));
        for (uint32_t idx = 0; idx < out_prefix.entry_count; ++idx) {
            if (off + sizeof(WireEntryPrefixV1) > payload.size()) return false;
            WireEntryPrefixV1 ep{};
            std::memcpy(&ep, payload.data() + off, sizeof(ep));
            off += sizeof(ep);
            if (ep.payload_bytes == 0) return false;
            const size_t n = static_cast<size_t>(ep.payload_bytes);
            if (off + n > payload.size()) return false;
            out_entries.emplace_back(payload.data() + off, payload.data() + off + n);
            off += n;
        }
        if (off != payload.size()) return false;
        return !out_entries.empty();
    }

    static bool encodeV2(uint16_t packet_kind,
                         uint16_t route_mode,
                         uint16_t stage,
                         uint16_t block_w_h,
                         uint64_t bundle_id,
                         const std::vector<BundleEntryV2>& entries,
                         std::vector<uint8_t>& out_payload) {
        if (entries.empty()) return false;
        if (entries.size() > static_cast<size_t>(std::numeric_limits<uint32_t>::max())) return false;
        const uint32_t block_cells = blockCellsFromBlockWH(block_w_h);
        if (block_cells == 0) return false;

        const size_t entry_bytes = sizeof(WireEntryMetaV2) + static_cast<size_t>(block_cells) * sizeof(uint32_t);
        const size_t total = sizeof(WireBundlePrefixV2) + entries.size() * entry_bytes;
        if (total > static_cast<size_t>(std::numeric_limits<uint32_t>::max())) return false;

        out_payload.resize(total);
        size_t off = 0;

        WireBundlePrefixV2 prefix{};
        prefix.packet_kind = packet_kind;
        prefix.route_mode = route_mode;
        prefix.stage = stage;
        prefix.block_w_h = block_w_h;
        prefix.entry_count = static_cast<uint32_t>(entries.size());
        prefix.bundle_id = bundle_id;
        std::memcpy(out_payload.data() + off, &prefix, sizeof(prefix));
        off += sizeof(prefix);

        const size_t mask_bytes = static_cast<size_t>(block_cells) * sizeof(uint32_t);
        for (const auto& entry : entries) {
            std::memcpy(out_payload.data() + off, &entry.meta, sizeof(WireEntryMetaV2));
            off += sizeof(WireEntryMetaV2);
            std::memcpy(out_payload.data() + off, entry.core_mask.data(), mask_bytes);
            off += mask_bytes;
        }
        return true;
    }

    static bool decodeV2(const std::vector<uint8_t>& payload,
                         WireBundlePrefixV2& out_prefix,
                         std::vector<BundleEntryV2>& out_entries) {
        out_entries.clear();
        uint16_t version = 0;
        if (!decodeVersion(payload, version)) return false;
        if (version != kVersionV2) return false;
        if (payload.size() < sizeof(WireBundlePrefixV2)) return false;
        std::memcpy(&out_prefix, payload.data(), sizeof(WireBundlePrefixV2));
        const uint32_t block_cells = blockCellsFromBlockWH(out_prefix.block_w_h);
        if (block_cells == 0) return false;
        if (out_prefix.entry_count == 0) return false;

        const size_t mask_bytes = static_cast<size_t>(block_cells) * sizeof(uint32_t);
        const size_t entry_bytes = sizeof(WireEntryMetaV2) + mask_bytes;
        size_t off = sizeof(WireBundlePrefixV2);
        out_entries.reserve(static_cast<size_t>(out_prefix.entry_count));
        for (uint32_t idx = 0; idx < out_prefix.entry_count; ++idx) {
            if (off + entry_bytes > payload.size()) return false;
            BundleEntryV2 entry{};
            std::memcpy(&entry.meta, payload.data() + off, sizeof(WireEntryMetaV2));
            off += sizeof(WireEntryMetaV2);
            std::memcpy(entry.core_mask.data(), payload.data() + off, mask_bytes);
            off += mask_bytes;
            out_entries.emplace_back(std::move(entry));
        }
        if (off != payload.size()) return false;
        return !out_entries.empty();
    }

    static bool encodeV3(uint16_t packet_kind,
                         uint16_t route_mode,
                         uint16_t stage,
                         uint16_t block_w,
                         uint16_t block_h,
                         uint16_t block_d,
                         uint64_t bundle_id,
                         const std::vector<BundleEntryV3>& entries,
                         std::vector<uint8_t>& out_payload) {
        if (entries.empty()) return false;
        if (entries.size() > static_cast<size_t>(std::numeric_limits<uint32_t>::max())) return false;
        const uint32_t block_cells = blockCellsFromBlockShape(block_w, block_h, block_d);
        if (block_cells == 0) return false;

        const size_t entry_bytes = sizeof(WireEntryMetaV3) + static_cast<size_t>(block_cells) * sizeof(uint32_t);
        const size_t total = sizeof(WireBundlePrefixV3) + entries.size() * entry_bytes;
        if (total > static_cast<size_t>(std::numeric_limits<uint32_t>::max())) return false;

        out_payload.resize(total);
        size_t off = 0;

        WireBundlePrefixV3 prefix{};
        prefix.packet_kind = packet_kind;
        prefix.route_mode = route_mode;
        prefix.stage = stage;
        prefix.block_w = block_w;
        prefix.block_h = block_h;
        prefix.block_d = block_d;
        prefix.entry_count = static_cast<uint32_t>(entries.size());
        prefix.bundle_id = bundle_id;
        std::memcpy(out_payload.data() + off, &prefix, sizeof(prefix));
        off += sizeof(prefix);

        const size_t mask_bytes = static_cast<size_t>(block_cells) * sizeof(uint32_t);
        for (const auto& entry : entries) {
            std::memcpy(out_payload.data() + off, &entry.meta, sizeof(WireEntryMetaV3));
            off += sizeof(WireEntryMetaV3);
            std::memcpy(out_payload.data() + off, entry.core_mask.data(), mask_bytes);
            off += mask_bytes;
        }
        return true;
    }

    static bool decodeV3(const std::vector<uint8_t>& payload,
                         WireBundlePrefixV3& out_prefix,
                         std::vector<BundleEntryV3>& out_entries) {
        out_entries.clear();
        uint16_t version = 0;
        if (!decodeVersion(payload, version)) return false;
        if (version != kVersionV3) return false;
        if (payload.size() < sizeof(WireBundlePrefixV3)) return false;
        std::memcpy(&out_prefix, payload.data(), sizeof(WireBundlePrefixV3));
        const uint32_t block_cells = blockCellsFromBlockShape(out_prefix.block_w, out_prefix.block_h, out_prefix.block_d);
        if (block_cells == 0) return false;
        if (out_prefix.entry_count == 0) return false;

        const size_t mask_bytes = static_cast<size_t>(block_cells) * sizeof(uint32_t);
        const size_t entry_bytes = sizeof(WireEntryMetaV3) + mask_bytes;
        size_t off = sizeof(WireBundlePrefixV3);
        out_entries.reserve(static_cast<size_t>(out_prefix.entry_count));
        for (uint32_t idx = 0; idx < out_prefix.entry_count; ++idx) {
            if (off + entry_bytes > payload.size()) return false;
            BundleEntryV3 entry{};
            std::memcpy(&entry.meta, payload.data() + off, sizeof(WireEntryMetaV3));
            off += sizeof(WireEntryMetaV3);
            std::memcpy(entry.core_mask.data(), payload.data() + off, mask_bytes);
            off += mask_bytes;
            out_entries.emplace_back(std::move(entry));
        }
        if (off != payload.size()) return false;
        return !out_entries.empty();
    }
};

}} // namespace SST::SnnDL
