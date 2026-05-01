// -*- c++ -*-
//
// SpikeTileNocCodec:
// - Experimental SpikeTileKey payload codec (B route):
//   route header (WireSpikeKeyV2/V4 prefix) + (block_col + pre_mask).
// - Keep router compatibility by decoding any SpikeKey route prefix first, then parse the tile tail.
//

#pragma once

#include <cstdint>
#include <cstring>
#include <type_traits>
#include <vector>

#include "SpikeNocCodec.h"

namespace SST { namespace SnnDL {

class SpikeTileNocCodec final {
public:
    // Keep route_mode in route header explicit for easy diagnostics.
    static constexpr uint16_t kRouteModeSpikeTile = 2;
    static constexpr uint16_t kTileVersionV1 = 1;
    static constexpr uint16_t kTileVersionV2 = 2; // compact-mask payload (route V3 + tail)

    struct WireSpikeTileTailV1 final {
        uint16_t tile_version = kTileVersionV1;
        uint16_t reserved = 0;
        uint32_t block_col = 0;
        uint64_t pre_mask = 0;
    };

    static_assert(std::is_trivially_copyable<WireSpikeTileTailV1>::value,
                  "WireSpikeTileTailV1 must be trivially copyable");

    struct WireSpikeTileKeyV1 final {
        // Legacy 2D/compact path: prefix remains WireSpikeKeyV2-compatible.
        SpikeNocCodec::WireSpikeKeyV2 route{};
        WireSpikeTileTailV1 tile{};
    };

    static_assert(std::is_trivially_copyable<WireSpikeTileKeyV1>::value,
                  "WireSpikeTileKeyV1 must be trivially copyable");

    struct WireSpikeTileKeyV2 final {
        // Explicit 3D path: prefix is WireSpikeKeyV4 so block_d stays native on the wire.
        SpikeNocCodec::WireSpikeKeyV4 route{};
        WireSpikeTileTailV1 tile{};
    };

    static_assert(std::is_trivially_copyable<WireSpikeTileKeyV2>::value,
                  "WireSpikeTileKeyV2 must be trivially copyable");

    static void encode(const WireSpikeTileKeyV1& ws, std::vector<uint8_t>& out_payload) {
        out_payload.resize(sizeof(WireSpikeTileKeyV1));
        std::memcpy(out_payload.data(), &ws, sizeof(WireSpikeTileKeyV1));
    }

    static void encode(const WireSpikeTileKeyV2& ws, std::vector<uint8_t>& out_payload) {
        out_payload.resize(sizeof(WireSpikeTileKeyV2));
        std::memcpy(out_payload.data(), &ws, sizeof(WireSpikeTileKeyV2));
    }

    static bool encodeCompactV2(const SpikeNocCodec::WireSpikeKeyV2& route,
                                uint32_t block_col,
                                uint64_t pre_mask,
                                std::vector<uint8_t>& out_payload) {
        std::vector<uint8_t> route_payload;
        if (!SpikeNocCodec::encodeSpikeKeyCompactV3(route, route_payload)) return false;

        WireSpikeTileTailV1 tail{};
        tail.tile_version = kTileVersionV2;
        tail.block_col = block_col;
        tail.pre_mask = pre_mask;

        out_payload.resize(route_payload.size() + sizeof(WireSpikeTileTailV1));
        std::memcpy(out_payload.data(), route_payload.data(), route_payload.size());
        std::memcpy(
            out_payload.data() + route_payload.size(),
            &tail,
            sizeof(WireSpikeTileTailV1));
        return true;
    }

    static bool encodeCompactV4(const SpikeNocCodec::WireSpikeKeyV4& route,
                                uint32_t block_col,
                                uint64_t pre_mask,
                                std::vector<uint8_t>& out_payload) {
        const uint64_t block_cells64 =
            static_cast<uint64_t>(route.block_w) *
            static_cast<uint64_t>(route.block_h) *
            static_cast<uint64_t>(route.block_d);
        if (route.version != 4 ||
            route.block_w == 0 ||
            route.block_h == 0 ||
            route.block_d == 0 ||
            block_cells64 == 0 ||
            block_cells64 > static_cast<uint64_t>(kMaxMulticastBlockCells)) {
            return false;
        }

        out_payload.resize(sizeof(SpikeNocCodec::WireSpikeKeyV4) + sizeof(WireSpikeTileTailV1));
        std::memcpy(out_payload.data(), &route, sizeof(SpikeNocCodec::WireSpikeKeyV4));

        WireSpikeTileTailV1 tail{};
        tail.tile_version = kTileVersionV2;
        tail.block_col = block_col;
        tail.pre_mask = pre_mask;
        std::memcpy(
            out_payload.data() + sizeof(SpikeNocCodec::WireSpikeKeyV4),
            &tail,
            sizeof(WireSpikeTileTailV1));
        return true;
    }

    static bool decode(const std::vector<uint8_t>& payload,
                       WireSpikeTileKeyV1& out_ws,
                       SpikeNocCodec::DecodedSpikeKeyMeta* out_route_meta = nullptr) {
        SpikeNocCodec::WireSpikeKeyV2 route{};
        SpikeNocCodec::DecodedSpikeKeyMeta meta{};
        if (!SpikeNocCodec::decodeSpikeKeyAny(payload, route, &meta)) return false;
        if (route.version != 1 && route.version != 2 && route.version != 3 && route.version != 4) return false;
        if (route.route_mode != kRouteModeSpikeTile) return false;

        size_t tail_offset = meta.route_bytes;
        if (tail_offset == 0) {
            if (payload.size() < sizeof(SpikeNocCodec::WireSpikeKeyV2)) return false;
            tail_offset = sizeof(SpikeNocCodec::WireSpikeKeyV2);
        }
        if (payload.size() < tail_offset + sizeof(WireSpikeTileTailV1)) return false;

        WireSpikeTileTailV1 tail{};
        std::memcpy(&tail, payload.data() + tail_offset, sizeof(WireSpikeTileTailV1));
        if (tail.tile_version != kTileVersionV1 && tail.tile_version != kTileVersionV2) return false;

        out_ws.route = route;
        out_ws.tile = tail;
        if (out_route_meta) *out_route_meta = meta;
        return true;
    }

    static void collectPreGlobals(const WireSpikeTileKeyV1& ws,
                                  uint32_t block_cols,
                                  std::vector<uint32_t>& out_pre_globals) {
        out_pre_globals.clear();
        if (block_cols == 0 || block_cols > 64) return;
        const uint64_t mask = ws.tile.pre_mask;
        if (mask == 0) return;

        out_pre_globals.reserve(8);
        const uint64_t base = static_cast<uint64_t>(ws.tile.block_col) * static_cast<uint64_t>(block_cols);
        for (uint32_t bit = 0; bit < block_cols; ++bit) {
            if ((mask & (1ull << bit)) == 0ull) continue;
            out_pre_globals.push_back(static_cast<uint32_t>(base + static_cast<uint64_t>(bit)));
        }
    }
};

}} // namespace SST::SnnDL
