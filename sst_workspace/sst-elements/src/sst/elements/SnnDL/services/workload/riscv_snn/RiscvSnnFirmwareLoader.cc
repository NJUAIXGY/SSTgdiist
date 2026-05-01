// -*- c++ -*-

#include <sst/core/sst_config.h>

#include "workload/riscv_snn/RiscvSnnFirmwareLoader.h"

#include <algorithm>
#include <fstream>
#include <iterator>
#include <limits>
#include <vector>

namespace SST { namespace SnnDL { namespace riscv_snn {

namespace {

inline uint16_t readU16Le(const std::vector<uint8_t>& bytes, size_t off) {
    return static_cast<uint16_t>(bytes[off]) |
        (static_cast<uint16_t>(bytes[off + 1]) << 8);
}

inline uint32_t readU32Le(const std::vector<uint8_t>& bytes, size_t off) {
    return static_cast<uint32_t>(bytes[off]) |
        (static_cast<uint32_t>(bytes[off + 1]) << 8) |
        (static_cast<uint32_t>(bytes[off + 2]) << 16) |
        (static_cast<uint32_t>(bytes[off + 3]) << 24);
}

inline uint64_t readU64Le(const std::vector<uint8_t>& bytes, size_t off) {
    uint64_t value = 0;
    for (size_t i = 0; i < 8; ++i) {
        value |= (static_cast<uint64_t>(bytes[off + i]) << (i * 8));
    }
    return value;
}

bool addWouldOverflow(size_t base, size_t increment) {
    return increment > (std::numeric_limits<size_t>::max() - base);
}

} // namespace

bool RiscvSnnFirmwareLoader::loadElf64(const std::string& path,
                                       RiscvSnnMemoryImage& image,
                                       std::string& error) {
    image = RiscvSnnMemoryImage{};
    error.clear();

    std::ifstream in(path, std::ios::binary);
    if (!in) {
        error = "failed to open firmware ELF";
        return false;
    }

    std::vector<uint8_t> bytes((std::istreambuf_iterator<char>(in)),
                               std::istreambuf_iterator<char>());
    if (bytes.size() < 64) {
        error = "firmware ELF too small";
        return false;
    }

    if (!(bytes[0] == 0x7F && bytes[1] == 'E' && bytes[2] == 'L' && bytes[3] == 'F')) {
        error = "invalid ELF magic";
        return false;
    }
    if (bytes[4] != 2) {
        error = "only ELF64 firmware is supported";
        return false;
    }
    if (bytes[5] != 1) {
        error = "only little-endian firmware is supported";
        return false;
    }

    const uint16_t e_type = readU16Le(bytes, 16);
    const uint16_t e_machine = readU16Le(bytes, 18);
    const uint64_t e_entry = readU64Le(bytes, 24);
    const uint64_t e_phoff = readU64Le(bytes, 32);
    const uint16_t e_ehsize = readU16Le(bytes, 52);
    const uint16_t e_phentsize = readU16Le(bytes, 54);
    const uint16_t e_phnum = readU16Le(bytes, 56);

    if (e_ehsize < 64) {
        error = "ELF header is smaller than ELF64 minimum";
        return false;
    }
    if (!(e_type == 2 || e_type == 3)) {
        error = "unsupported ELF type";
        return false;
    }
    if (e_machine != 243) {
        error = "firmware ELF is not EM_RISCV";
        return false;
    }
    if (e_phentsize < 56 || e_phnum == 0) {
        error = "firmware ELF has no usable program headers";
        return false;
    }
    if (e_phoff > bytes.size()) {
        error = "program header table offset is out of range";
        return false;
    }
    if (addWouldOverflow(static_cast<size_t>(e_phoff),
                         static_cast<size_t>(e_phentsize) * static_cast<size_t>(e_phnum)) ||
        static_cast<size_t>(e_phoff) +
                static_cast<size_t>(e_phentsize) * static_cast<size_t>(e_phnum) >
            bytes.size()) {
        error = "program header table exceeds file size";
        return false;
    }

    image.entry_pc = e_entry;
    for (uint16_t idx = 0; idx < e_phnum; ++idx) {
        const size_t phoff = static_cast<size_t>(e_phoff) + static_cast<size_t>(idx) * e_phentsize;
        const uint32_t p_type = readU32Le(bytes, phoff + 0);
        const uint32_t p_flags = readU32Le(bytes, phoff + 4);
        const uint64_t p_offset = readU64Le(bytes, phoff + 8);
        const uint64_t p_vaddr = readU64Le(bytes, phoff + 16);
        const uint64_t p_filesz = readU64Le(bytes, phoff + 32);
        const uint64_t p_memsz = readU64Le(bytes, phoff + 40);

        if (p_type != 1) continue;
        if (p_filesz > p_memsz) {
            error = "PT_LOAD segment has p_filesz > p_memsz";
            return false;
        }
        if (p_memsz > static_cast<uint64_t>(std::numeric_limits<size_t>::max())) {
            error = "PT_LOAD segment mem size is too large";
            return false;
        }
        if (p_offset > bytes.size() ||
            addWouldOverflow(static_cast<size_t>(p_offset), static_cast<size_t>(p_filesz)) ||
            static_cast<size_t>(p_offset) + static_cast<size_t>(p_filesz) > bytes.size()) {
            error = "PT_LOAD segment file range exceeds image size";
            return false;
        }

        RiscvSnnMemorySegment segment;
        segment.vaddr = p_vaddr;
        segment.flags = p_flags;
        segment.data.assign(static_cast<size_t>(p_memsz), 0);
        std::copy(bytes.begin() + static_cast<std::ptrdiff_t>(p_offset),
                  bytes.begin() + static_cast<std::ptrdiff_t>(p_offset + p_filesz),
                  segment.data.begin());
        image.segments.push_back(std::move(segment));
    }

    if (image.segments.empty()) {
        error = "firmware ELF contains no PT_LOAD segment";
        return false;
    }

    std::sort(image.segments.begin(),
              image.segments.end(),
              [](const RiscvSnnMemorySegment& lhs, const RiscvSnnMemorySegment& rhs) {
                  return lhs.vaddr < rhs.vaddr;
              });
    for (size_t i = 1; i < image.segments.size(); ++i) {
        if (segmentsOverlap(image.segments[i - 1], image.segments[i])) {
            error = "PT_LOAD segments overlap in virtual address space";
            image = RiscvSnnMemoryImage{};
            return false;
        }
    }

    return true;
}

}}} // namespace SST::SnnDL::riscv_snn
