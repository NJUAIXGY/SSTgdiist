// -*- c++ -*-
//
// SpikeNocCodec:
// - 将 SpikeEvent 编解码为 NoC 通用包（NocPacketEvent）的 payload bytes
// - 目的：让 services/noc 与 NIC 层完全不依赖 SpikeEvent（严格通用化）
//

#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <type_traits>
#include <vector>

#include "api/MulticastLimits.h"
#include "GlobalNeuronLayout.h"

namespace SST { namespace SnnDL {

class NocPacketEvent;
class SpikeEvent;

class SpikeNocCodec final {
public:
    struct WireSpike final {
        uint32_t src_neuron = 0;
        uint32_t dst_neuron = 0;
        double weight = 0.0;
        uint64_t timestamp = 0;
    };

    static_assert(std::is_trivially_copyable<WireSpike>::value, "WireSpike must be trivially copyable");

    struct WireSpikeKeyV1 final {
        uint16_t version = 1;
        uint16_t route_mode = 0;
        uint16_t stage = 0;
        uint16_t block_w_h = 0;

        uint32_t mesh_w = 0;
        uint32_t mesh_h = 0;
        uint32_t block_id = 0;
        uint32_t ingress_node = 0;

        uint32_t pre_global = 0;
        uint64_t group_id = 0;

        uint32_t core_mask[4] = {0, 0, 0, 0};
    };

    static_assert(std::is_trivially_copyable<WireSpikeKeyV1>::value, "WireSpikeKeyV1 must be trivially copyable");

    // V2: 支持可配置 block_w/block_h（由 block_w_h=(w<<8)|h 表示），并扩展 core_mask 为固定上限数组。
    // 兼容性：前缀字段保持与 V1 一致，便于 router/workload 在不引入可变长 payload 的情况下扩展。
    struct WireSpikeKeyV2 final {
        uint16_t version = 2;
        uint16_t route_mode = 0;
        uint16_t stage = 0;
        uint16_t block_w_h = 0;

        uint32_t mesh_w = 0;
        uint32_t mesh_h = 0;
        uint32_t block_id = 0;
        uint32_t ingress_node = 0;

        uint32_t pre_global = 0;
        uint64_t group_id = 0;

        std::array<uint32_t, kMaxMulticastBlockCells> core_mask{};
    };

    static_assert(std::is_trivially_copyable<WireSpikeKeyV2>::value, "WireSpikeKeyV2 must be trivially copyable");

    // V3: fixed prefix + variable-length core_mask segment.
    // Layout: WireSpikeKeyV3Prefix + core_mask[block_cells] (uint32_t each).
    // block_cells is derived from block_w_h=(w<<8)|h.
    struct WireSpikeKeyV3Prefix final {
        uint16_t version = 3;
        uint16_t route_mode = 0;
        uint16_t stage = 0;
        uint16_t block_w_h = 0;

        uint32_t mesh_w = 0;
        uint32_t mesh_h = 0;
        uint32_t block_id = 0;
        uint32_t ingress_node = 0;

        uint32_t pre_global = 0;
        uint64_t group_id = 0;
    };

    static_assert(
        std::is_trivially_copyable<WireSpikeKeyV3Prefix>::value,
        "WireSpikeKeyV3Prefix must be trivially copyable");

    struct WireSpikeKeyV4 final {
        uint16_t version = 4;
        uint16_t route_mode = 0;
        uint16_t stage = 0;
        uint16_t reserved0 = 0;

        uint16_t block_w = 0;
        uint16_t block_h = 0;
        uint16_t block_d = 1;
        uint16_t reserved1 = 0;

        uint32_t block_id = 0;
        uint32_t ingress_node = 0;

        uint32_t pre_global = 0;
        uint64_t group_id = 0;

        std::array<uint32_t, kMaxMulticastBlockCells> core_mask{};
    };

    static_assert(std::is_trivially_copyable<WireSpikeKeyV4>::value, "WireSpikeKeyV4 must be trivially copyable");

    struct DecodedSpikeKeyMeta final {
        uint16_t version = 0;
        uint32_t block_w = 0;
        uint32_t block_h = 0;
        uint32_t block_d = 1;
        uint32_t block_cells = 0;
        size_t route_bytes = 0;  // bytes consumed by route header + mask segment
        bool compact_mask = false;
    };

    static void encodeSpikeKey(const WireSpikeKeyV1& ws, std::vector<uint8_t>& out_payload) {
        out_payload.resize(sizeof(WireSpikeKeyV1));
        std::memcpy(out_payload.data(), &ws, sizeof(WireSpikeKeyV1));
    }

    static void encodeSpikeKey(const WireSpikeKeyV2& ws, std::vector<uint8_t>& out_payload) {
        out_payload.resize(sizeof(WireSpikeKeyV2));
        std::memcpy(out_payload.data(), &ws, sizeof(WireSpikeKeyV2));
    }

    static void encodeSpikeKey(const WireSpikeKeyV4& ws, std::vector<uint8_t>& out_payload) {
        out_payload.resize(sizeof(WireSpikeKeyV4));
        std::memcpy(out_payload.data(), &ws, sizeof(WireSpikeKeyV4));
    }

    // Encode compact V3 payload: fixed prefix + block_cells mask words.
    static bool encodeSpikeKeyCompactV3(const WireSpikeKeyV2& ws, std::vector<uint8_t>& out_payload) {
        const uint32_t block_w = static_cast<uint32_t>((ws.block_w_h >> 8) & 0xffu);
        const uint32_t block_h = static_cast<uint32_t>(ws.block_w_h & 0xffu);
        const uint32_t block_cells = block_w * block_h;
        if (block_w == 0 || block_h == 0 || block_cells == 0 || block_cells > kMaxMulticastBlockCells) {
            return false;
        }

        const size_t mask_bytes = static_cast<size_t>(block_cells) * sizeof(uint32_t);
        out_payload.resize(sizeof(WireSpikeKeyV3Prefix) + mask_bytes);

        WireSpikeKeyV3Prefix v3{};
        v3.version = 3;
        v3.route_mode = ws.route_mode;
        v3.stage = ws.stage;
        v3.block_w_h = ws.block_w_h;
        v3.mesh_w = ws.mesh_w;
        v3.mesh_h = ws.mesh_h;
        v3.block_id = ws.block_id;
        v3.ingress_node = ws.ingress_node;
        v3.pre_global = ws.pre_global;
        v3.group_id = ws.group_id;

        std::memcpy(out_payload.data(), &v3, sizeof(WireSpikeKeyV3Prefix));
        std::memcpy(out_payload.data() + sizeof(WireSpikeKeyV3Prefix), ws.core_mask.data(), mask_bytes);
        return true;
    }

    static bool decodeSpikeKey(const std::vector<uint8_t>& payload, WireSpikeKeyV1& out_ws) {
        if (payload.size() != sizeof(WireSpikeKeyV1)) return false;
        std::memcpy(&out_ws, payload.data(), sizeof(WireSpikeKeyV1));
        return true;
    }

    // Decode V1/V2/V3 into a V2 struct (V1/V3 fields are expanded; unused mask slots are zeroed).
    static bool decodeSpikeKeyAny(
        const std::vector<uint8_t>& payload,
        WireSpikeKeyV2& out_ws,
        DecodedSpikeKeyMeta* out_meta = nullptr) {
        if (out_meta) *out_meta = DecodedSpikeKeyMeta{};
        if (payload.size() < sizeof(uint16_t)) return false;

        uint16_t version = 0;
        std::memcpy(&version, payload.data(), sizeof(version));
        if (version == 4) {
            if (payload.size() < sizeof(WireSpikeKeyV4)) return false;
            WireSpikeKeyV4 v4{};
            std::memcpy(&v4, payload.data(), sizeof(WireSpikeKeyV4));

            const uint64_t block_cells64 =
                static_cast<uint64_t>(v4.block_w) *
                static_cast<uint64_t>(v4.block_h) *
                static_cast<uint64_t>(v4.block_d);
            if (v4.block_w == 0 || v4.block_h == 0 || v4.block_d == 0 ||
                block_cells64 == 0 || block_cells64 > static_cast<uint64_t>(kMaxMulticastBlockCells)) {
                return false;
            }

            out_ws = WireSpikeKeyV2{};
            out_ws.version = v4.version;
            out_ws.route_mode = v4.route_mode;
            out_ws.stage = v4.stage;
            out_ws.block_w_h = static_cast<uint16_t>(((static_cast<uint32_t>(v4.block_w) & 0xffu) << 8) |
                                                     (static_cast<uint32_t>(v4.block_h) & 0xffu));
            out_ws.block_id = v4.block_id;
            out_ws.ingress_node = v4.ingress_node;
            out_ws.pre_global = v4.pre_global;
            out_ws.group_id = v4.group_id;
            out_ws.core_mask = v4.core_mask;

            if (out_meta) {
                out_meta->version = 4;
                out_meta->block_w = v4.block_w;
                out_meta->block_h = v4.block_h;
                out_meta->block_d = v4.block_d;
                out_meta->block_cells = static_cast<uint32_t>(block_cells64);
                out_meta->route_bytes = sizeof(WireSpikeKeyV4);
                out_meta->compact_mask = false;
            }
            return true;
        }
        if (version == 3) {
            if (payload.size() < sizeof(WireSpikeKeyV3Prefix)) return false;
            WireSpikeKeyV3Prefix v3{};
            std::memcpy(&v3, payload.data(), sizeof(WireSpikeKeyV3Prefix));

            const uint32_t block_w = static_cast<uint32_t>((v3.block_w_h >> 8) & 0xffu);
            const uint32_t block_h = static_cast<uint32_t>(v3.block_w_h & 0xffu);
            const uint32_t block_cells = block_w * block_h;
            if (block_w == 0 || block_h == 0 || block_cells == 0 || block_cells > kMaxMulticastBlockCells) {
                return false;
            }

            const size_t mask_bytes = static_cast<size_t>(block_cells) * sizeof(uint32_t);
            const size_t route_bytes = sizeof(WireSpikeKeyV3Prefix) + mask_bytes;
            if (payload.size() < route_bytes) return false;

            out_ws = WireSpikeKeyV2{};
            out_ws.version = v3.version;
            out_ws.route_mode = v3.route_mode;
            out_ws.stage = v3.stage;
            out_ws.block_w_h = v3.block_w_h;
            out_ws.mesh_w = v3.mesh_w;
            out_ws.mesh_h = v3.mesh_h;
            out_ws.block_id = v3.block_id;
            out_ws.ingress_node = v3.ingress_node;
            out_ws.pre_global = v3.pre_global;
            out_ws.group_id = v3.group_id;
            std::memcpy(out_ws.core_mask.data(), payload.data() + sizeof(WireSpikeKeyV3Prefix), mask_bytes);

            if (out_meta) {
                out_meta->version = 3;
                out_meta->block_w = block_w;
                out_meta->block_h = block_h;
                out_meta->block_d = 1;
                out_meta->block_cells = block_cells;
                out_meta->route_bytes = route_bytes;
                out_meta->compact_mask = true;
            }
            return true;
        }

        if (payload.size() >= sizeof(WireSpikeKeyV2)) {
            std::memcpy(&out_ws, payload.data(), sizeof(WireSpikeKeyV2));
            if (out_meta) {
                const uint32_t block_w = static_cast<uint32_t>((out_ws.block_w_h >> 8) & 0xffu);
                const uint32_t block_h = static_cast<uint32_t>(out_ws.block_w_h & 0xffu);
                out_meta->version = out_ws.version;
                out_meta->block_w = block_w;
                out_meta->block_h = block_h;
                out_meta->block_d = 1;
                out_meta->block_cells = block_w * block_h;
                out_meta->route_bytes = sizeof(WireSpikeKeyV2);
                out_meta->compact_mask = false;
            }
            return true;
        }
        if (payload.size() == sizeof(WireSpikeKeyV1)) {
            WireSpikeKeyV1 v1{};
            std::memcpy(&v1, payload.data(), sizeof(WireSpikeKeyV1));
            out_ws = WireSpikeKeyV2{};
            out_ws.version = v1.version;
            out_ws.route_mode = v1.route_mode;
            out_ws.stage = v1.stage;
            out_ws.block_w_h = v1.block_w_h;
            out_ws.mesh_w = v1.mesh_w;
            out_ws.mesh_h = v1.mesh_h;
            out_ws.block_id = v1.block_id;
            out_ws.ingress_node = v1.ingress_node;
            out_ws.pre_global = v1.pre_global;
            out_ws.group_id = v1.group_id;
            for (size_t i = 0; i < 4; ++i) out_ws.core_mask[i] = v1.core_mask[i];
            if (out_meta) {
                const uint32_t block_w = static_cast<uint32_t>((out_ws.block_w_h >> 8) & 0xffu);
                const uint32_t block_h = static_cast<uint32_t>(out_ws.block_w_h & 0xffu);
                out_meta->version = 1;
                out_meta->block_w = block_w;
                out_meta->block_h = block_h;
                out_meta->block_d = 1;
                out_meta->block_cells = block_w * block_h;
                out_meta->route_bytes = sizeof(WireSpikeKeyV1);
                out_meta->compact_mask = false;
            }
            return true;
        }
        return false;
    }

    // In-place patching for INTER->INTRA stage transition.
    // Works for V1/V2 fixed payload and V3 compact payload (and payloads with optional tails).
    static bool patchStageInPayload(std::vector<uint8_t>& payload, uint16_t new_stage) {
        if (payload.size() < sizeof(uint16_t)) return false;
        uint16_t version = 0;
        std::memcpy(&version, payload.data(), sizeof(version));

        if (version == 1 && payload.size() < sizeof(WireSpikeKeyV1)) return false;
        if (version == 2 && payload.size() < sizeof(WireSpikeKeyV2)) return false;
        if (version == 3 && payload.size() < sizeof(WireSpikeKeyV3Prefix)) return false;
        if (version == 4 && payload.size() < sizeof(WireSpikeKeyV4)) return false;
        if (version != 1 && version != 2 && version != 3 && version != 4) return false;

        const size_t stage_off = offsetof(WireSpikeKeyV4, stage);
        if (payload.size() < stage_off + sizeof(uint16_t)) return false;
        std::memcpy(payload.data() + stage_off, &new_stage, sizeof(new_stage));
        return true;
    }

    static NocPacketEvent* encode(const SpikeEvent& spike, const GlobalNeuronLayout& layout);

    static SpikeEvent* decode(const NocPacketEvent& pkt);
};

}} // namespace SST::SnnDL
