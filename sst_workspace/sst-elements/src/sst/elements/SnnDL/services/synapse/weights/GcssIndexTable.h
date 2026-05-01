// -*- c++ -*-
//
// GcssIndexTable:
// - Experimental GCSS/GSCC value-only index table loader/lookup.
// - File format v1 is documented in exp_opt/2026-03-01-gcss-valueonly-dstcore-plan.md.

#pragma once

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

namespace SST { namespace SnnDL {

class GcssIndexTable {
public:
    struct HeaderV1 {
        char magic[8];
        uint32_t version = 0;
        uint32_t rows_per_core = 0;
        uint32_t edges_total = 0;
        uint32_t pre_entries = 0;
        uint32_t posts_total = 0;
        uint32_t flags = 0;
        uint32_t reserved0 = 0;
    };

    struct PreEntry {
        uint32_t base_widx = 0;
        uint32_t post_offset = 0;
        uint16_t post_count = 0;
    };

    bool loadFromFile(const std::string& path, std::string* err) {
        clear();
        std::ifstream fin(path, std::ios::in | std::ios::binary);
        if (!fin.is_open()) {
            setErr_(err, "open_failed");
            return false;
        }

        HeaderV1 hdr{};
        if (!readPod_(fin, hdr)) {
            setErr_(err, "header_read_failed");
            return false;
        }
        if (std::memcmp(hdr.magic, "GCSSIDX1", 8) != 0) {
            setErr_(err, "bad_magic");
            return false;
        }
        if (hdr.version != 1u) {
            setErr_(err, "unsupported_version");
            return false;
        }

        std::vector<uint32_t> pre_keys;
        std::vector<uint32_t> base_widx;
        std::vector<uint16_t> post_counts;
        std::vector<uint32_t> post_offsets;
        std::vector<uint16_t> posts;
        std::vector<uint32_t> widxs;
        pre_keys.resize(static_cast<size_t>(hdr.pre_entries));
        base_widx.resize(static_cast<size_t>(hdr.pre_entries));
        post_counts.resize(static_cast<size_t>(hdr.pre_entries));
        post_offsets.resize(static_cast<size_t>(hdr.pre_entries));
        posts.resize(static_cast<size_t>(hdr.posts_total));
        widxs.resize(static_cast<size_t>(hdr.posts_total));

        if (!readArray_(fin, pre_keys)) {
            setErr_(err, "pre_keys_read_failed");
            return false;
        }
        if (!readArray_(fin, base_widx)) {
            setErr_(err, "base_widx_read_failed");
            return false;
        }
        if (!readArray_(fin, post_counts)) {
            setErr_(err, "post_counts_read_failed");
            return false;
        }
        if (!readArray_(fin, post_offsets)) {
            setErr_(err, "post_offsets_read_failed");
            return false;
        }
        if (!readArray_(fin, posts)) {
            setErr_(err, "posts_read_failed");
            return false;
        }
        if (!readArray_(fin, widxs)) {
            setErr_(err, "widxs_read_failed");
            return false;
        }

        // Optional trailing bytes are not allowed in v1 to keep format deterministic.
        char tail = 0;
        if (fin.read(&tail, 1)) {
            setErr_(err, "unexpected_trailing_bytes");
            return false;
        }

        pre_keys_ = std::move(pre_keys);
        posts_ = std::move(posts);
        widxs_ = std::move(widxs);
        pre_entries_.resize(pre_keys_.size());
        for (size_t i = 0; i < pre_keys_.size(); ++i) {
            const uint32_t off = post_offsets[i];
            const uint16_t cnt = post_counts[i];
            if (off > posts_.size()) {
                clear();
                setErr_(err, "post_offset_oob");
                return false;
            }
            if (static_cast<size_t>(off) + static_cast<size_t>(cnt) > posts_.size()) {
                clear();
                setErr_(err, "post_span_oob");
                return false;
            }
            pre_entries_[i].base_widx = base_widx[i];
            pre_entries_[i].post_offset = off;
            pre_entries_[i].post_count = cnt;
        }

        rows_per_core_ = hdr.rows_per_core;
        edges_total_ = hdr.edges_total;
        return true;
    }

    bool lookup(uint32_t pre_global, uint32_t post_local, uint32_t& out_widx) const {
        if (pre_keys_.empty()) return false;
        auto it = std::lower_bound(pre_keys_.begin(), pre_keys_.end(), pre_global);
        if (it == pre_keys_.end() || *it != pre_global) return false;
        const size_t idx = static_cast<size_t>(it - pre_keys_.begin());
        const PreEntry& e = pre_entries_[idx];
        const uint32_t off = e.post_offset;
        const uint16_t cnt = e.post_count;
        const uint16_t post16 = static_cast<uint16_t>(post_local & 0xFFFFu);
        for (uint16_t i = 0; i < cnt; ++i) {
            const size_t p = static_cast<size_t>(off) + i;
            if (posts_[p] == post16) {
                out_widx = widxs_[p];
                return true;
            }
        }
        return false;
    }

    void clear() {
        pre_keys_.clear();
        pre_entries_.clear();
        posts_.clear();
        widxs_.clear();
        rows_per_core_ = 0;
        edges_total_ = 0;
    }

    bool empty() const { return pre_keys_.empty(); }
    uint32_t rowsPerCore() const { return rows_per_core_; }
    uint32_t edgesTotal() const { return edges_total_; }

private:
    template <class T>
    static bool readPod_(std::ifstream& fin, T& v) {
        fin.read(reinterpret_cast<char*>(&v), static_cast<std::streamsize>(sizeof(T)));
        return static_cast<size_t>(fin.gcount()) == sizeof(T);
    }

    template <class T>
    static bool readArray_(std::ifstream& fin, std::vector<T>& v) {
        if (v.empty()) return true;
        const size_t bytes = v.size() * sizeof(T);
        fin.read(reinterpret_cast<char*>(v.data()), static_cast<std::streamsize>(bytes));
        return static_cast<size_t>(fin.gcount()) == bytes;
    }

    static void setErr_(std::string* err, const char* msg) {
        if (err) *err = msg ? msg : "error";
    }

    std::vector<uint32_t> pre_keys_;
    std::vector<PreEntry> pre_entries_;
    std::vector<uint16_t> posts_;
    std::vector<uint32_t> widxs_;
    uint32_t rows_per_core_ = 0;
    uint32_t edges_total_ = 0;
};

}} // namespace SST::SnnDL
