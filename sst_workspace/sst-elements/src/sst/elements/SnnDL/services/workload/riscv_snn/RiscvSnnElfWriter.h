// -*- c++ -*-
//
// RiscvSnnElfWriter:
// - `riscv_snn` 私有的最小 ELF64 写出 helper。
// - 只服务 bring-up / test firmware 样例，避免把临时 ELF 拼装逻辑散落在测试与脚本里。
//

#pragma once

#include <algorithm>
#include <cstdint>
#include <fstream>
#include <limits>
#include <string>
#include <vector>

namespace SST { namespace SnnDL { namespace riscv_snn {

struct RiscvSnnElfLoadSegment {
    uint64_t vaddr = 0;
    uint32_t flags = 0;
    std::vector<uint8_t> file_data{};
    uint64_t mem_size = 0;
    uint64_t align = 0x1000;
};

namespace detail {

inline void appendLeU16(std::vector<uint8_t>& buf, uint16_t value) {
    buf.push_back(static_cast<uint8_t>(value & 0xFFu));
    buf.push_back(static_cast<uint8_t>((value >> 8) & 0xFFu));
}

inline void appendLeU32(std::vector<uint8_t>& buf, uint32_t value) {
    for (int i = 0; i < 4; ++i) {
        buf.push_back(static_cast<uint8_t>((value >> (i * 8)) & 0xFFu));
    }
}

inline void appendLeU64(std::vector<uint8_t>& buf, uint64_t value) {
    for (int i = 0; i < 8; ++i) {
        buf.push_back(static_cast<uint8_t>((value >> (i * 8)) & 0xFFu));
    }
}

inline uint64_t alignUp(uint64_t value, uint64_t alignment) {
    if (alignment == 0) return value;
    const uint64_t rem = value % alignment;
    return (rem == 0) ? value : (value + alignment - rem);
}

} // namespace detail

inline bool writeElf64Image(const std::string& path,
                            uint64_t entry_pc,
                            const std::vector<RiscvSnnElfLoadSegment>& segments,
                            std::string& error) {
    error.clear();
    if (segments.empty()) {
        error = "ELF image requires at least one PT_LOAD segment";
        return false;
    }
    if (path.empty()) {
        error = "ELF output path is empty";
        return false;
    }
    if (segments.size() > static_cast<size_t>(std::numeric_limits<uint16_t>::max())) {
        error = "ELF image has too many segments";
        return false;
    }

    const uint64_t phoff = 64;
    const uint16_t ehsize = 64;
    const uint16_t phentsize = 56;
    const uint16_t phnum = static_cast<uint16_t>(segments.size());

    std::vector<uint64_t> offsets;
    offsets.reserve(segments.size());

    uint64_t cursor = detail::alignUp(
        phoff + static_cast<uint64_t>(phentsize) * static_cast<uint64_t>(phnum),
        0x100);
    for (const auto& seg : segments) {
        const uint64_t mem_size = (seg.mem_size == 0) ? static_cast<uint64_t>(seg.file_data.size()) : seg.mem_size;
        if (static_cast<uint64_t>(seg.file_data.size()) > mem_size) {
            error = "ELF segment file size exceeds mem size";
            return false;
        }
        cursor = detail::alignUp(cursor, 0x100);
        offsets.push_back(cursor);
        cursor += static_cast<uint64_t>(seg.file_data.size());
    }

    if (cursor > static_cast<uint64_t>(std::numeric_limits<size_t>::max())) {
        error = "ELF image is too large";
        return false;
    }

    std::vector<uint8_t> bytes;
    bytes.reserve(static_cast<size_t>(cursor));

    bytes.push_back(0x7F);
    bytes.push_back('E');
    bytes.push_back('L');
    bytes.push_back('F');
    bytes.push_back(2);
    bytes.push_back(1);
    bytes.push_back(1);
    bytes.push_back(0);
    bytes.push_back(0);
    for (int i = 0; i < 7; ++i) bytes.push_back(0);

    detail::appendLeU16(bytes, 2);
    detail::appendLeU16(bytes, 243);
    detail::appendLeU32(bytes, 1);
    detail::appendLeU64(bytes, entry_pc);
    detail::appendLeU64(bytes, phoff);
    detail::appendLeU64(bytes, 0);
    detail::appendLeU32(bytes, 0);
    detail::appendLeU16(bytes, ehsize);
    detail::appendLeU16(bytes, phentsize);
    detail::appendLeU16(bytes, phnum);
    detail::appendLeU16(bytes, 0);
    detail::appendLeU16(bytes, 0);
    detail::appendLeU16(bytes, 0);

    for (size_t i = 0; i < segments.size(); ++i) {
        const auto& seg = segments[i];
        const uint64_t mem_size =
            (seg.mem_size == 0) ? static_cast<uint64_t>(seg.file_data.size()) : seg.mem_size;
        detail::appendLeU32(bytes, 1);
        detail::appendLeU32(bytes, seg.flags);
        detail::appendLeU64(bytes, offsets[i]);
        detail::appendLeU64(bytes, seg.vaddr);
        detail::appendLeU64(bytes, seg.vaddr);
        detail::appendLeU64(bytes, static_cast<uint64_t>(seg.file_data.size()));
        detail::appendLeU64(bytes, mem_size);
        detail::appendLeU64(bytes, seg.align);
    }

    for (size_t i = 0; i < segments.size(); ++i) {
        const size_t offset = static_cast<size_t>(offsets[i]);
        if (bytes.size() < offset) bytes.resize(offset, 0);
        bytes.insert(bytes.end(), segments[i].file_data.begin(), segments[i].file_data.end());
    }

    std::ofstream out(path, std::ios::binary);
    if (!out) {
        error = "failed to open ELF output path";
        return false;
    }
    out.write(reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    if (!out) {
        error = "failed to write ELF image";
        return false;
    }
    return true;
}

}}} // namespace SST::SnnDL::riscv_snn
