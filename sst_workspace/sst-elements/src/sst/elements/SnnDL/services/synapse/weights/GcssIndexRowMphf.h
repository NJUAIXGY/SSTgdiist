// -*- c++ -*-
//
// GcssIndexRowMphf:
// - Experimental GCSSIDX2 loader/lookup (row-major values + row-MPHF index).
// - File format is documented in exp_opt/2026-03-01-gcss-idx2-rowmphf-plan.md.

#pragma once

#include <cstdint>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

namespace SST { namespace SnnDL {

class GcssIndexRowMphf {
public:
    struct HeaderV1 {
        char magic[8];
        uint32_t version = 0;
        uint32_t rows_per_core = 0;
        uint32_t edges_total = 0;
        uint32_t bucket_target = 0;
        uint32_t pilot_bits = 0;
        uint32_t hash_kind = 0;
        uint32_t flags = 0;
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
        if (std::memcmp(hdr.magic, "GCSSIDX2", 8) != 0) {
            setErr_(err, "bad_magic");
            return false;
        }
        if (hdr.version != 1u) {
            setErr_(err, "unsupported_version");
            return false;
        }
        if (hdr.pilot_bits != 8u) {
            setErr_(err, "unsupported_pilot_bits");
            return false;
        }
        if (hdr.hash_kind != 1u) {
            setErr_(err, "unsupported_hash_kind");
            return false;
        }

        const size_t rows = static_cast<size_t>(hdr.rows_per_core);
        row_base_.assign(rows + 1, 0u);
        row_len_.assign(rows, 0u);
        row_seed_.assign(rows, 0u);
        row_bucket_count_.assign(rows, 0u);
        row_bucket_off_.assign(rows + 1, 0u);

        if (!readArray_(fin, row_base_)) {
            setErr_(err, "row_base_read_failed");
            return false;
        }
        if (!readArray_(fin, row_len_)) {
            setErr_(err, "row_len_read_failed");
            return false;
        }
        if (!readArray_(fin, row_seed_)) {
            setErr_(err, "row_seed_read_failed");
            return false;
        }
        if (!readArray_(fin, row_bucket_count_)) {
            setErr_(err, "row_bucket_count_read_failed");
            return false;
        }
        if (!readArray_(fin, row_bucket_off_)) {
            setErr_(err, "row_bucket_off_read_failed");
            return false;
        }

        if (!validateIndexArrays_(hdr, err)) {
            clear();
            return false;
        }

        const size_t pilots_total = static_cast<size_t>(row_bucket_off_.back());
        pilots_.assign(pilots_total, 0u);
        if (!readArray_(fin, pilots_)) {
            clear();
            setErr_(err, "pilots_read_failed");
            return false;
        }

        char tail = 0;
        if (fin.read(&tail, 1)) {
            clear();
            setErr_(err, "unexpected_trailing_bytes");
            return false;
        }

        rows_per_core_ = hdr.rows_per_core;
        edges_total_ = hdr.edges_total;
        bucket_target_ = hdr.bucket_target;
        flags_ = hdr.flags;
        return true;
    }

    bool lookup(uint32_t pre_global, uint32_t post_local, uint32_t& out_widx) const {
        if (post_local >= rows_per_core_) return false;
        const size_t row = static_cast<size_t>(post_local);
        const uint32_t l = static_cast<uint32_t>(row_len_[row]);
        if (l == 0u) return false;
        const uint32_t bcount = static_cast<uint32_t>(row_bucket_count_[row]);
        if (bcount == 0u) return false;
        const uint32_t seed = row_seed_[row];
        const uint32_t b = hash1_(pre_global, seed) % bcount;
        const uint32_t boff = row_bucket_off_[row];
        const size_t pidx = static_cast<size_t>(boff + b);
        if (pidx >= pilots_.size()) return false;
        const uint32_t pilot = static_cast<uint32_t>(pilots_[pidx]);
        const uint32_t pos = slotPos_(pre_global, seed, pilot, l);
        const uint32_t base = row_base_[row];
        out_widx = base + pos;
        return out_widx < edges_total_;
    }

    void clear() {
        row_base_.clear();
        row_len_.clear();
        row_seed_.clear();
        row_bucket_count_.clear();
        row_bucket_off_.clear();
        pilots_.clear();
        rows_per_core_ = 0;
        edges_total_ = 0;
        bucket_target_ = 0;
        flags_ = 0;
    }

    bool empty() const { return row_base_.empty(); }
    uint32_t rowsPerCore() const { return rows_per_core_; }
    uint32_t edgesTotal() const { return edges_total_; }
    uint32_t bucketTarget() const { return bucket_target_; }
    uint32_t flags() const { return flags_; }

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

    static uint32_t mix32_(uint32_t x) {
        x ^= (x >> 16);
        x *= 0x7FEB352Du;
        x ^= (x >> 15);
        x *= 0x846CA68Bu;
        x ^= (x >> 16);
        return x;
    }

    static uint32_t hash1_(uint32_t key, uint32_t seed) {
        return mix32_(key ^ mix32_(seed ^ 0xA24BAED5u));
    }

    static uint32_t hash2_(uint32_t key, uint32_t seed) {
        return mix32_(key ^ mix32_(seed ^ 0x9FB21C65u));
    }

    static uint32_t slotPos_(uint32_t key, uint32_t seed, uint32_t pilot, uint32_t row_len) {
        if (row_len == 0u) return 0u;
        const uint32_t pilot_seed = seed ^ static_cast<uint32_t>((pilot + 1u) * 0x9E3779B1u);
        return hash2_(key, pilot_seed) % row_len;
    }

    bool validateIndexArrays_(const HeaderV1& hdr, std::string* err) const {
        if (row_base_.empty() || row_bucket_off_.empty()) {
            setErr_(err, "empty_arrays");
            return false;
        }
        if (row_base_.front() != 0u) {
            setErr_(err, "row_base_not_zero");
            return false;
        }
        if (row_bucket_off_.front() != 0u) {
            setErr_(err, "row_bucket_off_not_zero");
            return false;
        }
        if (row_base_.back() != hdr.edges_total) {
            setErr_(err, "row_base_tail_mismatch");
            return false;
        }
        for (size_t i = 0; i + 1 < row_base_.size(); ++i) {
            if (row_base_[i + 1] < row_base_[i]) {
                setErr_(err, "row_base_not_monotonic");
                return false;
            }
        }
        for (size_t i = 0; i + 1 < row_bucket_off_.size(); ++i) {
            if (row_bucket_off_[i + 1] < row_bucket_off_[i]) {
                setErr_(err, "row_bucket_off_not_monotonic");
                return false;
            }
            const uint32_t diff = row_bucket_off_[i + 1] - row_bucket_off_[i];
            if (diff != static_cast<uint32_t>(row_bucket_count_[i])) {
                setErr_(err, "row_bucket_span_mismatch");
                return false;
            }
            const uint32_t len = static_cast<uint32_t>(row_len_[i]);
            const uint32_t bcount = static_cast<uint32_t>(row_bucket_count_[i]);
            if (len == 0u && bcount != 0u) {
                setErr_(err, "empty_row_has_buckets");
                return false;
            }
            if (len > 0u && bcount == 0u) {
                setErr_(err, "nonempty_row_has_no_buckets");
                return false;
            }
        }
        return true;
    }

    std::vector<uint32_t> row_base_;
    std::vector<uint16_t> row_len_;
    std::vector<uint32_t> row_seed_;
    std::vector<uint16_t> row_bucket_count_;
    std::vector<uint32_t> row_bucket_off_;
    std::vector<uint8_t> pilots_;
    uint32_t rows_per_core_ = 0;
    uint32_t edges_total_ = 0;
    uint32_t bucket_target_ = 0;
    uint32_t flags_ = 0;
};

}} // namespace SST::SnnDL
