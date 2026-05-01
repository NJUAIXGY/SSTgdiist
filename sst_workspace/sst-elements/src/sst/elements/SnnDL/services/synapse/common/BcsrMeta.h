// -*- c++ -*-
//
// BcsrMeta:
// - 解析 BCSR .meta.json 的通用口径（rows/cols/br/bc/idx_bytes/val_bytes + offsets/total_blocks）
// - 提供基础校验（file_size/offset 区间/常见字段合法性）
//

#pragma once

#include <cctype>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iterator>
#include <string>

namespace SST { namespace SnnDL {

struct BcsrMeta {
    uint32_t rows = 0;
    uint32_t cols = 0;
    uint32_t br = 0;
    uint32_t bc = 0;
    uint32_t idx_bytes = 0;
    uint32_t val_bytes = 0;
    uint64_t rowptr_offset = 0;
    uint64_t colidx_offset = 0;
    uint64_t blockdata_offset = 0;
    uint64_t blockids_offset = 0;
    uint32_t total_blocks = 0;

    // Optional layout hints (newer datasets):
    // - layout_mode: "flat" (default) | "rowpack_v1"
    // - *_row_stride_bytes: only meaningful for rowpack_v1 (0 means "absent"/unused)
    std::string layout_mode;
    uint32_t colidx_row_stride_bytes = 0;
    uint32_t blockdata_row_stride_bytes = 0;
    uint32_t blockids_row_stride_bytes = 0;
};

inline uint32_t bcsrDefaultU32(uint32_t v, uint32_t fallback) { return v ? v : fallback; }

inline bool bcsrExtractUnsignedJson(const std::string& text, const char* key, uint64_t& value) {
    auto pos = text.find(key);
    if (pos == std::string::npos) return false;
    pos = text.find(':', pos);
    if (pos == std::string::npos) return false;
    ++pos;
    while (pos < text.size() && (std::isspace(static_cast<unsigned char>(text[pos])) || text[pos] == '"')) ++pos;
    size_t end = pos;
    while (end < text.size() &&
           (std::isdigit(static_cast<unsigned char>(text[end])) || text[end] == 'x' || text[end] == 'X')) {
        ++end;
    }
    if (end <= pos) return false;
    value = std::strtoull(text.substr(pos, end - pos).c_str(), nullptr, 0);
    return true;
}

inline bool bcsrExtractStringJson(const std::string& text, const char* key, std::string& value) {
    auto pos = text.find(key);
    if (pos == std::string::npos) return false;
    pos = text.find(':', pos);
    if (pos == std::string::npos) return false;
    ++pos;
    while (pos < text.size() && std::isspace(static_cast<unsigned char>(text[pos]))) ++pos;
    if (pos >= text.size() || text[pos] != '"') return false;
    ++pos;
    size_t end = pos;
    while (end < text.size() && text[end] != '"') ++end;
    if (end <= pos) return false;
    value = text.substr(pos, end - pos);
    return true;
}

inline bool parseBcsrMetaJsonFile(const std::string& meta_path, BcsrMeta& out) {
    std::ifstream meta(meta_path);
    if (!meta.good()) return false;
    std::string text((std::istreambuf_iterator<char>(meta)), std::istreambuf_iterator<char>());
    uint64_t value = 0;
    bool ok = false;
    if (bcsrExtractUnsignedJson(text, "\"rows\"", value)) { out.rows = static_cast<uint32_t>(value); ok = true; }
    if (bcsrExtractUnsignedJson(text, "\"cols\"", value)) { out.cols = static_cast<uint32_t>(value); ok = true; }
    if (bcsrExtractUnsignedJson(text, "\"br\"", value)) { out.br = static_cast<uint32_t>(value); ok = true; }
    if (bcsrExtractUnsignedJson(text, "\"bc\"", value)) { out.bc = static_cast<uint32_t>(value); ok = true; }
    if (bcsrExtractUnsignedJson(text, "\"idx_bytes\"", value)) { out.idx_bytes = static_cast<uint32_t>(value); ok = true; }
    if (bcsrExtractUnsignedJson(text, "\"val_bytes\"", value)) { out.val_bytes = static_cast<uint32_t>(value); ok = true; }
    if (bcsrExtractUnsignedJson(text, "\"rowptr_offset\"", value)) { out.rowptr_offset = value; ok = true; }
    if (bcsrExtractUnsignedJson(text, "\"colidx_offset\"", value)) { out.colidx_offset = value; ok = true; }
    if (bcsrExtractUnsignedJson(text, "\"blockdata_offset\"", value)) { out.blockdata_offset = value; ok = true; }
    if (bcsrExtractUnsignedJson(text, "\"blockids_offset\"", value)) { out.blockids_offset = value; ok = true; }
    if (bcsrExtractUnsignedJson(text, "\"total_blocks\"", value)) { out.total_blocks = static_cast<uint32_t>(value); ok = true; }
    if (bcsrExtractStringJson(text, "\"layout_mode\"", out.layout_mode)) { ok = true; }
    if (bcsrExtractUnsignedJson(text, "\"colidx_row_stride_bytes\"", value)) { out.colidx_row_stride_bytes = static_cast<uint32_t>(value); ok = true; }
    if (bcsrExtractUnsignedJson(text, "\"blockdata_row_stride_bytes\"", value)) { out.blockdata_row_stride_bytes = static_cast<uint32_t>(value); ok = true; }
    if (bcsrExtractUnsignedJson(text, "\"blockids_row_stride_bytes\"", value)) { out.blockids_row_stride_bytes = static_cast<uint32_t>(value); ok = true; }
    return ok;
}

inline uint32_t bcsrNumBlockRows(uint32_t rows, uint32_t br) {
    if (br == 0) return 0;
    return (rows + br - 1u) / br;
}

inline uint64_t bcsrBytesPerBlock(uint32_t br, uint32_t bc, uint32_t val_bytes) {
    return static_cast<uint64_t>(br) * static_cast<uint64_t>(bc) * static_cast<uint64_t>(val_bytes);
}

inline bool validateBcsrMetaAgainstFile(const BcsrMeta& meta,
                                       uint64_t file_size,
                                       uint32_t rows_for_rowptr,
                                       std::string* err_out) {
    auto fail = [&](const char* msg) {
        if (err_out) *err_out = msg ? std::string(msg) : std::string();
        return false;
    };

    const uint32_t br = meta.br ? meta.br : 16;
    const uint32_t bc = meta.bc ? meta.bc : 16;
    const uint32_t idxB = meta.idx_bytes ? meta.idx_bytes : 2;
    const uint32_t valB = meta.val_bytes ? meta.val_bytes : 4;
    if (br == 0 || bc == 0) return fail("invalid br/bc");
    if (!(idxB == 2 || idxB == 4)) return fail("invalid idx_bytes");
    if (valB != 4) return fail("invalid val_bytes (only fp32 supported)");

    if (meta.rowptr_offset >= file_size) return fail("rowptr_offset out of range");
    if (meta.colidx_offset >= file_size) return fail("colidx_offset out of range");
    if (meta.blockdata_offset >= file_size) return fail("blockdata_offset out of range");
    if (meta.blockids_offset >= file_size) return fail("blockids_offset out of range");

    const uint32_t n_block_rows = bcsrNumBlockRows(rows_for_rowptr, br);
    if (n_block_rows == 0) return fail("invalid rows_for_rowptr");

    const uint64_t need_rowptr = (static_cast<uint64_t>(n_block_rows) + 1ULL) * sizeof(uint32_t);
    if (meta.rowptr_offset + need_rowptr > file_size) return fail("rowptr range exceeds file");

    if (meta.total_blocks == 0) return true;

    const std::string mode = meta.layout_mode;
    if (mode == "rowpack_v1") {
        const uint64_t need_colidx_rows =
            static_cast<uint64_t>(n_block_rows) * static_cast<uint64_t>(meta.colidx_row_stride_bytes);
        const uint64_t need_blockdata_rows =
            static_cast<uint64_t>(n_block_rows) * static_cast<uint64_t>(meta.blockdata_row_stride_bytes);
        if (meta.colidx_row_stride_bytes < idxB) return fail("rowpack_v1 invalid colidx_row_stride_bytes");
        if (meta.blockdata_row_stride_bytes < bcsrBytesPerBlock(br, bc, valB)) return fail("rowpack_v1 invalid blockdata_row_stride_bytes");
        if (meta.colidx_offset + need_colidx_rows > file_size) return fail("rowpack_v1 colidx rows range exceeds file");
        if (meta.blockdata_offset + need_blockdata_rows > file_size) return fail("rowpack_v1 blockdata rows range exceeds file");
        // blockids: generator contract keeps it in legacy flat layout for compatibility.
        const uint64_t need_blockids =
            static_cast<uint64_t>(meta.total_blocks) * bcsrBytesPerBlock(br, bc, valB);
        if (meta.blockids_offset && meta.blockids_offset + need_blockids > file_size) return fail("blockids range exceeds file");
    } else {
        const uint64_t need_colidx = static_cast<uint64_t>(meta.total_blocks) * static_cast<uint64_t>(idxB);
        const uint64_t need_block = static_cast<uint64_t>(meta.total_blocks) * bcsrBytesPerBlock(br, bc, valB);

        if (meta.colidx_offset + need_colidx > file_size) return fail("colidx range exceeds file");
        if (meta.blockdata_offset + need_block > file_size) return fail("blockdata range exceeds file");
        if (meta.blockids_offset && meta.blockids_offset + need_block > file_size) return fail("blockids range exceeds file");
    }

    return true;
}

}} // namespace SST::SnnDL
