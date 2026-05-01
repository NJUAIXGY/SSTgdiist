// -*- c++ -*-

#pragma once

#include <cstdint>
#include <cstdlib>
#include <string>

#include "SnnDLStringUtil.h"

namespace SST { namespace SnnDL {

struct MeshShape3D final {
    uint32_t dim_x = 0;
    uint32_t dim_y = 0;
    uint32_t dim_z = 0;

    bool valid() const {
        return dim_x > 0 && dim_y > 0 && dim_z > 0;
    }

    uint32_t totalNodes() const {
        return dim_x * dim_y * dim_z;
    }
};

struct MeshCoord3D final {
    uint32_t x = 0;
    uint32_t y = 0;
    uint32_t z = 0;
};

inline bool parseMeshShape3D(const std::string& raw, MeshShape3D& out_shape) {
    out_shape = MeshShape3D{};
    if (raw.empty()) return false;

    const std::string shape = toLowerCopy(raw);
    const auto p0 = shape.find('x');
    if (p0 == std::string::npos) return false;
    const auto p1 = shape.find('x', p0 + 1);

    const std::string sx = shape.substr(0, p0);
    const std::string sy = (p1 == std::string::npos) ? shape.substr(p0 + 1) : shape.substr(p0 + 1, p1 - p0 - 1);
    const std::string sz = (p1 == std::string::npos) ? "1" : shape.substr(p1 + 1);
    if (sx.empty() || sy.empty() || sz.empty()) return false;

    char* endp = nullptr;
    const long dx = std::strtol(sx.c_str(), &endp, 10);
    if (!endp || *endp != '\0' || dx <= 0) return false;
    endp = nullptr;
    const long dy = std::strtol(sy.c_str(), &endp, 10);
    if (!endp || *endp != '\0' || dy <= 0) return false;
    endp = nullptr;
    const long dz = std::strtol(sz.c_str(), &endp, 10);
    if (!endp || *endp != '\0' || dz <= 0) return false;

    out_shape.dim_x = static_cast<uint32_t>(dx);
    out_shape.dim_y = static_cast<uint32_t>(dy);
    out_shape.dim_z = static_cast<uint32_t>(dz);
    return out_shape.valid();
}

inline bool nodeIdToCoord3D(const MeshShape3D& shape, uint32_t node_id, MeshCoord3D& coord) {
    coord = MeshCoord3D{};
    if (!shape.valid() || node_id >= shape.totalNodes()) return false;

    coord.x = node_id % shape.dim_x;
    const uint32_t yz = node_id / shape.dim_x;
    coord.y = yz % shape.dim_y;
    coord.z = yz / shape.dim_y;
    return true;
}

inline uint32_t coordToNodeId3D(const MeshShape3D& shape, uint32_t x, uint32_t y, uint32_t z) {
    return ((z * shape.dim_y) + y) * shape.dim_x + x;
}

inline uint32_t blocksPerLayer3D(const MeshShape3D& shape, uint32_t block_w, uint32_t block_h) {
    if (!shape.valid() || block_w == 0 || block_h == 0) return 0;
    if ((shape.dim_x % block_w) != 0 || (shape.dim_y % block_h) != 0) return 0;
    return (shape.dim_x / block_w) * (shape.dim_y / block_h);
}

inline uint32_t blocksPerVolume3D(const MeshShape3D& shape,
                                  uint32_t block_w,
                                  uint32_t block_h,
                                  uint32_t block_d) {
    if (!shape.valid() || block_w == 0 || block_h == 0 || block_d == 0) return 0;
    if ((shape.dim_x % block_w) != 0 || (shape.dim_y % block_h) != 0 || (shape.dim_z % block_d) != 0) return 0;
    return (shape.dim_x / block_w) * (shape.dim_y / block_h) * (shape.dim_z / block_d);
}

inline uint32_t encodeBlockId3DVolumetric(const MeshShape3D& shape,
                                          uint32_t block_w,
                                          uint32_t block_h,
                                          uint32_t block_d,
                                          uint32_t x,
                                          uint32_t y,
                                          uint32_t z) {
    const uint32_t blocks_w = shape.dim_x / block_w;
    const uint32_t blocks_h = shape.dim_y / block_h;
    const uint32_t blocks_per_plane = blocks_w * blocks_h;
    const uint32_t bx = x / block_w;
    const uint32_t by = y / block_h;
    const uint32_t bz = z / block_d;
    return bz * blocks_per_plane + by * blocks_w + bx;
}

inline uint32_t encodeBlockId3D(const MeshShape3D& shape,
                                uint32_t block_w,
                                uint32_t block_h,
                                uint32_t x,
                                uint32_t y,
                                uint32_t z) {
    return encodeBlockId3DVolumetric(shape, block_w, block_h, 1u, x, y, z);
}

inline bool decodeBlockId3DVolumetric(const MeshShape3D& shape,
                                      uint32_t block_w,
                                      uint32_t block_h,
                                      uint32_t block_d,
                                      uint32_t block_id,
                                      uint32_t& block_x0,
                                      uint32_t& block_y0,
                                      uint32_t& block_z0) {
    block_x0 = 0;
    block_y0 = 0;
    block_z0 = 0;
    const uint32_t blocks_w = (block_w > 0) ? (shape.dim_x / block_w) : 0;
    const uint32_t blocks_h = (block_h > 0) ? (shape.dim_y / block_h) : 0;
    const uint32_t blocks_d = (block_d > 0) ? (shape.dim_z / block_d) : 0;
    const uint32_t blocks_per_plane = blocks_w * blocks_h;
    const uint32_t total_blocks = blocks_per_plane * blocks_d;
    if (blocks_w == 0 || blocks_h == 0 || blocks_d == 0 || blocks_per_plane == 0 || total_blocks == 0) return false;
    if ((shape.dim_x % block_w) != 0 || (shape.dim_y % block_h) != 0 || (shape.dim_z % block_d) != 0) return false;
    if (block_id >= total_blocks) return false;

    const uint32_t bz = block_id / blocks_per_plane;
    const uint32_t plane_local = block_id % blocks_per_plane;
    const uint32_t bx = plane_local % blocks_w;
    const uint32_t by = plane_local / blocks_w;
    block_x0 = bx * block_w;
    block_y0 = by * block_h;
    block_z0 = bz * block_d;
    return true;
}

inline bool decodeBlockId3D(const MeshShape3D& shape,
                            uint32_t block_w,
                            uint32_t block_h,
                            uint32_t block_id,
                            uint32_t& block_x0,
                            uint32_t& block_y0,
                            uint32_t& block_z0) {
    return decodeBlockId3DVolumetric(shape, block_w, block_h, 1u, block_id, block_x0, block_y0, block_z0);
}

}} // namespace SST::SnnDL
