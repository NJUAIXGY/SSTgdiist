// -*- c++ -*-
//
// GcssIndexPreMphf:
// - Experimental GCSS-VLF index loader/lookup (pre-major values + pre-MPHF index).
// - Lookup API returns (base,len) for a given pre_global.
// - Runtime path is strict and assumes no out-of-set lookup in normal execution.

#pragma once

#include <cstdint>
#include <cstring>
#include <fstream>
#include <limits>
#include <string>
#include <vector>

namespace SST { namespace SnnDL {

class GcssIndexPreMphf {
public:
    struct HeaderV1 {
        char magic[8];
        uint32_t version = 0;
        uint32_t pre_count = 0;
        uint32_t edges_total = 0;
        uint32_t bucket_target = 0;
        uint32_t pilot_bits = 0;
        uint32_t hash_kind = 0;
        uint32_t flags = 0;
        uint32_t seed = 0;
        uint32_t bucket_count = 0;
    };

    struct HeaderV2Extra {
        uint32_t ef_l = 0;
        uint32_t ef_low_word_count = 0;
        uint32_t ef_high_word_count = 0;
        uint32_t ef_select_step = 0;
        uint32_t ef_select_count = 0;
    };

    struct HeaderV3Extra {
        uint32_t rank_bits = 0;
        uint32_t rank_word_count = 0;
        uint32_t ef_l = 0;
        uint32_t ef_low_word_count = 0;
        uint32_t ef_high_word_count = 0;
        uint32_t ef_select_step = 0;
        uint32_t ef_select_count = 0;
    };

    struct HeaderV4Extra {
        uint32_t bucket_size_bits = 0;
        uint32_t bucket_size_word_count = 0;
        uint32_t bucket_payload_bits = 0;
        uint32_t bucket_payload_word_count = 0;
        uint32_t local_len_bits = 0;
        uint32_t local_len_word_count = 0;
        uint32_t block_span = 0;
        uint32_t block_count = 0;
        uint32_t pilot_overflow_count = 0;
    };

    struct HeaderV5Extra {
        uint32_t block_size = 0;
        uint32_t block_count = 0;
        uint32_t block_desc_count = 0;
        uint32_t block_payload_word_count = 0;
        uint32_t ef_l = 0;
        uint32_t ef_low_word_count = 0;
        uint32_t ef_high_word_count = 0;
        uint32_t ef_select_step = 0;
        uint32_t ef_select_count = 0;
    };

    struct HeaderV6Extra {
        uint32_t key_max = 0;
        uint32_t key_ef_l = 0;
        uint32_t key_ef_low_word_count = 0;
        uint32_t key_ef_high_word_count = 0;
        uint32_t key_ef_select_step = 0;
        uint32_t key_ef_select_count = 0;
        uint32_t run_count = 0;
        uint32_t run_rank_bits = 0;
        uint32_t run_rank_word_count = 0;
        uint32_t run_ef_l = 0;
        uint32_t run_ef_low_word_count = 0;
        uint32_t run_ef_high_word_count = 0;
        uint32_t run_ef_select_step = 0;
        uint32_t run_ef_select_count = 0;
        uint32_t base_ef_l = 0;
        uint32_t base_ef_low_word_count = 0;
        uint32_t base_ef_high_word_count = 0;
        uint32_t base_ef_select_step = 0;
        uint32_t base_ef_select_count = 0;
        uint32_t reserved0 = 0;
    };

    struct HeaderV7Extra {
        uint32_t key_max = 0;
        uint32_t key_ef_l = 0;
        uint32_t key_ef_low_word_count = 0;
        uint32_t key_ef_high_word_count = 0;
        uint32_t key_ef_select_step = 0;
        uint32_t key_ef_select_count = 0;
        uint32_t run_count = 0;
        uint32_t run_rank_bits = 0;
        uint32_t run_rank_word_count = 0;
        uint32_t run_ef_l = 0;
        uint32_t run_ef_low_word_count = 0;
        uint32_t run_ef_high_word_count = 0;
        uint32_t run_ef_select_step = 0;
        uint32_t run_ef_select_count = 0;
        uint32_t len_block_size = 0;
        uint32_t len_block_count = 0;
        uint32_t len_block_base_bits = 0;
        uint32_t len_block_base_word_count = 0;
        uint32_t len_block_word_offset_bits = 0;
        uint32_t len_block_word_offset_word_count = 0;
        uint32_t len_block_mode_bits = 0;
        uint32_t len_block_mode_word_count = 0;
        uint32_t len_block_arg_bits = 0;
        uint32_t len_block_arg_word_count = 0;
        uint32_t len_payload_word_count = 0;
        uint32_t reserved0 = 0;
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
        if (std::memcmp(hdr.magic, "GCSSVLFP", 8) != 0) {
            setErr_(err, "bad_magic");
            return false;
        }
        if (hdr.version != 1u && hdr.version != 2u && hdr.version != 3u && hdr.version != 4u && hdr.version != 5u && hdr.version != 6u && hdr.version != 7u) {
            setErr_(err, "unsupported_version");
            return false;
        }
        if (hdr.version == 4u) {
            if (hdr.pilot_bits != 32u) {
                setErr_(err, "unsupported_pilot_bits");
                return false;
            }
        } else if (hdr.version == 6u || hdr.version == 7u) {
            if (hdr.pilot_bits != 0u) {
                setErr_(err, "unsupported_pilot_bits");
                return false;
            }
        } else if (hdr.pilot_bits != 8u && hdr.pilot_bits != 16u) {
            setErr_(err, "unsupported_pilot_bits");
            return false;
        }
        if (hdr.hash_kind != 1u) {
            setErr_(err, "unsupported_hash_kind");
            return false;
        }

        HeaderV2Extra hdr2{};
        HeaderV3Extra hdr3{};
        HeaderV4Extra hdr4{};
        HeaderV5Extra hdr5{};
        HeaderV6Extra hdr6{};
        HeaderV7Extra hdr7{};
        if (hdr.version == 2u) {
            if (!readPod_(fin, hdr2)) {
                setErr_(err, "header_v2_read_failed");
                clear();
                return false;
            }
        } else if (hdr.version == 3u) {
            if (!readPod_(fin, hdr3)) {
                setErr_(err, "header_v3_read_failed");
                clear();
                return false;
            }
        } else if (hdr.version == 4u) {
            if (!readPod_(fin, hdr4)) {
                setErr_(err, "header_v4_read_failed");
                clear();
                return false;
            }
        } else if (hdr.version == 5u) {
            if (!readPod_(fin, hdr5)) {
                setErr_(err, "header_v5_read_failed");
                clear();
                return false;
            }
        } else if (hdr.version == 6u) {
            if (!readPod_(fin, hdr6)) {
                setErr_(err, "header_v6_read_failed");
                clear();
                return false;
            }
        } else if (hdr.version == 7u) {
            if (!readPod_(fin, hdr7)) {
                setErr_(err, "header_v7_read_failed");
                clear();
                return false;
            }
        }

        const size_t pre_count = static_cast<size_t>(hdr.pre_count);
        pilots_.assign(static_cast<size_t>(hdr.bucket_count), 0u);
        if (hdr.version == 1u) {
            slot_base_.assign(pre_count, 0u);
            slot_len_.assign(pre_count, 0u);
            if (!readArray_(fin, slot_base_)) {
                setErr_(err, "slot_base_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, slot_len_)) {
                setErr_(err, "slot_len_read_failed");
                clear();
                return false;
            }
        } else if (hdr.version == 2u) {
            const uint32_t ef_l = hdr2.ef_l;
            const uint32_t ef_low_word_count = hdr2.ef_low_word_count;
            const uint32_t ef_high_word_count = hdr2.ef_high_word_count;
            const uint32_t ef_select_step = hdr2.ef_select_step;
            const uint32_t ef_select_count = hdr2.ef_select_count;

            ef_l_ = ef_l;
            ef_select_step_ = ef_select_step;
            ef_low_words_.assign(static_cast<size_t>(ef_low_word_count), 0ull);
            ef_high_words_.assign(static_cast<size_t>(ef_high_word_count), 0ull);
            ef_select_samples_.assign(static_cast<size_t>(ef_select_count), 0u);
            if (!readArray_(fin, ef_low_words_)) {
                setErr_(err, "ef_low_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, ef_high_words_)) {
                setErr_(err, "ef_high_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, ef_select_samples_)) {
                setErr_(err, "ef_select_read_failed");
                clear();
                return false;
            }
        } else if (hdr.version == 3u) {
            rank_bits_ = hdr3.rank_bits;
            ef_l_ = hdr3.ef_l;
            ef_select_step_ = hdr3.ef_select_step;
            rank_words_.assign(static_cast<size_t>(hdr3.rank_word_count), 0ull);
            ef_low_words_.assign(static_cast<size_t>(hdr3.ef_low_word_count), 0ull);
            ef_high_words_.assign(static_cast<size_t>(hdr3.ef_high_word_count), 0ull);
            ef_select_samples_.assign(static_cast<size_t>(hdr3.ef_select_count), 0u);
            if (!readArray_(fin, rank_words_)) {
                setErr_(err, "rank_words_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, ef_low_words_)) {
                setErr_(err, "ef_low_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, ef_high_words_)) {
                setErr_(err, "ef_high_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, ef_select_samples_)) {
                setErr_(err, "ef_select_read_failed");
                clear();
                return false;
            }
        } else if (hdr.version == 5u) {
            perm_block_size_ = hdr5.block_size;
            ef_l_ = hdr5.ef_l;
            ef_select_step_ = hdr5.ef_select_step;
            perm_block_min_rank_.assign(static_cast<size_t>(hdr5.block_desc_count), 0u);
            perm_block_bits_.assign(static_cast<size_t>(hdr5.block_desc_count), 0u);
            perm_block_word_offset_.assign(static_cast<size_t>(hdr5.block_desc_count), 0u);
            perm_payload_words_.assign(static_cast<size_t>(hdr5.block_payload_word_count), 0ull);
            ef_low_words_.assign(static_cast<size_t>(hdr5.ef_low_word_count), 0ull);
            ef_high_words_.assign(static_cast<size_t>(hdr5.ef_high_word_count), 0ull);
            ef_select_samples_.assign(static_cast<size_t>(hdr5.ef_select_count), 0u);
            for (size_t i = 0; i < perm_block_min_rank_.size(); ++i) {
                uint32_t min_rank = 0u;
                uint32_t bits = 0u;
                uint32_t word_off = 0u;
                if (!readPod_(fin, min_rank) || !readPod_(fin, bits) || !readPod_(fin, word_off)) {
                    setErr_(err, "v5_block_desc_read_failed");
                    clear();
                    return false;
                }
                perm_block_min_rank_[i] = min_rank;
                perm_block_bits_[i] = bits;
                perm_block_word_offset_[i] = word_off;
            }
            if (!readArray_(fin, perm_payload_words_)) {
                setErr_(err, "v5_block_payload_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, ef_low_words_)) {
                setErr_(err, "ef_low_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, ef_high_words_)) {
                setErr_(err, "ef_high_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, ef_select_samples_)) {
                setErr_(err, "ef_select_read_failed");
                clear();
                return false;
            }
        } else if (hdr.version == 6u) {
            key_max_ = hdr6.key_max;
            key_ef_l_ = hdr6.key_ef_l;
            key_ef_select_step_ = hdr6.key_ef_select_step;
            key_ef_low_words_.assign(static_cast<size_t>(hdr6.key_ef_low_word_count), 0ull);
            key_ef_high_words_.assign(static_cast<size_t>(hdr6.key_ef_high_word_count), 0ull);
            key_ef_select_samples_.assign(static_cast<size_t>(hdr6.key_ef_select_count), 0u);
            run_count_ = hdr6.run_count;
            run_rank_bits_ = hdr6.run_rank_bits;
            sid_run_rank_words_.assign(static_cast<size_t>(hdr6.run_rank_word_count), 0ull);
            run_ef_l_ = hdr6.run_ef_l;
            run_ef_select_step_ = hdr6.run_ef_select_step;
            run_ef_low_words_.assign(static_cast<size_t>(hdr6.run_ef_low_word_count), 0ull);
            run_ef_high_words_.assign(static_cast<size_t>(hdr6.run_ef_high_word_count), 0ull);
            run_ef_select_samples_.assign(static_cast<size_t>(hdr6.run_ef_select_count), 0u);
            ef_l_ = hdr6.base_ef_l;
            ef_select_step_ = hdr6.base_ef_select_step;
            ef_low_words_.assign(static_cast<size_t>(hdr6.base_ef_low_word_count), 0ull);
            ef_high_words_.assign(static_cast<size_t>(hdr6.base_ef_high_word_count), 0ull);
            ef_select_samples_.assign(static_cast<size_t>(hdr6.base_ef_select_count), 0u);
            if (!readArray_(fin, key_ef_low_words_)) {
                setErr_(err, "v6_key_ef_low_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, key_ef_high_words_)) {
                setErr_(err, "v6_key_ef_high_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, key_ef_select_samples_)) {
                setErr_(err, "v6_key_ef_select_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, sid_run_rank_words_)) {
                setErr_(err, "v6_run_rank_words_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, run_ef_low_words_)) {
                setErr_(err, "v6_run_ef_low_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, run_ef_high_words_)) {
                setErr_(err, "v6_run_ef_high_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, run_ef_select_samples_)) {
                setErr_(err, "v6_run_ef_select_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, ef_low_words_)) {
                setErr_(err, "v6_base_ef_low_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, ef_high_words_)) {
                setErr_(err, "v6_base_ef_high_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, ef_select_samples_)) {
                setErr_(err, "v6_base_ef_select_read_failed");
                clear();
                return false;
            }
        } else if (hdr.version == 7u) {
            key_max_ = hdr7.key_max;
            key_ef_l_ = hdr7.key_ef_l;
            key_ef_select_step_ = hdr7.key_ef_select_step;
            key_ef_low_words_.assign(static_cast<size_t>(hdr7.key_ef_low_word_count), 0ull);
            key_ef_high_words_.assign(static_cast<size_t>(hdr7.key_ef_high_word_count), 0ull);
            key_ef_select_samples_.assign(static_cast<size_t>(hdr7.key_ef_select_count), 0u);
            run_count_ = hdr7.run_count;
            run_rank_bits_ = hdr7.run_rank_bits;
            sid_run_rank_words_.assign(static_cast<size_t>(hdr7.run_rank_word_count), 0ull);
            run_ef_l_ = hdr7.run_ef_l;
            run_ef_select_step_ = hdr7.run_ef_select_step;
            run_ef_low_words_.assign(static_cast<size_t>(hdr7.run_ef_low_word_count), 0ull);
            run_ef_high_words_.assign(static_cast<size_t>(hdr7.run_ef_high_word_count), 0ull);
            run_ef_select_samples_.assign(static_cast<size_t>(hdr7.run_ef_select_count), 0u);
            lpbl_block_size_ = hdr7.len_block_size;
            lpbl_block_base_prefix_.assign(static_cast<size_t>(hdr7.len_block_count), 0u);
            lpbl_block_word_offset_.assign(static_cast<size_t>(hdr7.len_block_count), 0u);
            lpbl_block_mode_.assign(static_cast<size_t>(hdr7.len_block_count), 0u);
            lpbl_block_arg_.assign(static_cast<size_t>(hdr7.len_block_count), 0u);
            lpbl_payload_words_.assign(static_cast<size_t>(hdr7.len_payload_word_count), 0ull);
            std::vector<uint64_t> lpbl_block_base_words(static_cast<size_t>(hdr7.len_block_base_word_count), 0ull);
            std::vector<uint64_t> lpbl_block_word_offset_words(static_cast<size_t>(hdr7.len_block_word_offset_word_count), 0ull);
            std::vector<uint64_t> lpbl_block_mode_words(static_cast<size_t>(hdr7.len_block_mode_word_count), 0ull);
            std::vector<uint64_t> lpbl_block_arg_words(static_cast<size_t>(hdr7.len_block_arg_word_count), 0ull);
            if (!readArray_(fin, key_ef_low_words_)) {
                setErr_(err, "v7_key_ef_low_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, key_ef_high_words_)) {
                setErr_(err, "v7_key_ef_high_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, key_ef_select_samples_)) {
                setErr_(err, "v7_key_ef_select_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, sid_run_rank_words_)) {
                setErr_(err, "v7_run_rank_words_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, run_ef_low_words_)) {
                setErr_(err, "v7_run_ef_low_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, run_ef_high_words_)) {
                setErr_(err, "v7_run_ef_high_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, run_ef_select_samples_)) {
                setErr_(err, "v7_run_ef_select_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, lpbl_block_base_words)) {
                setErr_(err, "v7_len_block_base_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, lpbl_block_word_offset_words)) {
                setErr_(err, "v7_len_block_word_offset_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, lpbl_block_mode_words)) {
                setErr_(err, "v7_len_block_mode_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, lpbl_block_arg_words)) {
                setErr_(err, "v7_len_block_arg_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, lpbl_payload_words_)) {
                setErr_(err, "v7_len_payload_read_failed");
                clear();
                return false;
            }
            for (uint32_t i = 0u; i < hdr7.len_block_count; ++i) {
                uint32_t value = 0u;
                if (!fixedBitsAt_(lpbl_block_base_words, i, hdr7.len_block_base_bits, value)) {
                    setErr_(err, "v7_len_block_base_decode_failed");
                    clear();
                    return false;
                }
                lpbl_block_base_prefix_[static_cast<size_t>(i)] = value;
                if (!fixedBitsAt_(lpbl_block_word_offset_words, i, hdr7.len_block_word_offset_bits, value)) {
                    setErr_(err, "v7_len_block_word_offset_decode_failed");
                    clear();
                    return false;
                }
                lpbl_block_word_offset_[static_cast<size_t>(i)] = value;
                if (!fixedBitsAt_(lpbl_block_mode_words, i, hdr7.len_block_mode_bits, value)) {
                    setErr_(err, "v7_len_block_mode_decode_failed");
                    clear();
                    return false;
                }
                lpbl_block_mode_[static_cast<size_t>(i)] = value;
                if (!fixedBitsAt_(lpbl_block_arg_words, i, hdr7.len_block_arg_bits, value)) {
                    setErr_(err, "v7_len_block_arg_decode_failed");
                    clear();
                    return false;
                }
                lpbl_block_arg_[static_cast<size_t>(i)] = value;
            }
        } else {
            bucket_size_bits_ = hdr4.bucket_size_bits;
            bucket_payload_bits_ = hdr4.bucket_payload_bits;
            local_len_bits_ = hdr4.local_len_bits;
            block_span_ = hdr4.block_span;
            bucket_size_words_.assign(static_cast<size_t>(hdr4.bucket_size_word_count), 0ull);
            bucket_payload_words_.assign(static_cast<size_t>(hdr4.bucket_payload_word_count), 0ull);
            local_len_words_.assign(static_cast<size_t>(hdr4.local_len_word_count), 0ull);
            entry_block_prefix_.assign(static_cast<size_t>(hdr4.block_count), 0u);
            base_block_prefix_.assign(static_cast<size_t>(hdr4.block_count), 0u);
            if (!readArray_(fin, bucket_size_words_)) {
                setErr_(err, "bucket_size_words_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, bucket_payload_words_)) {
                setErr_(err, "bucket_payload_words_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, local_len_words_)) {
                setErr_(err, "local_len_words_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, entry_block_prefix_)) {
                setErr_(err, "entry_block_prefix_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, base_block_prefix_)) {
                setErr_(err, "base_block_prefix_read_failed");
                clear();
                return false;
            }
            std::vector<uint8_t> pilots_u8(static_cast<size_t>(hdr.bucket_count), 0u);
            if (!readArray_(fin, pilots_u8)) {
                setErr_(err, "pilots_read_failed");
                clear();
                return false;
            }
            for (size_t i = 0; i < pilots_u8.size(); ++i) {
                pilots_[i] = static_cast<uint16_t>(pilots_u8[i]);
            }
            std::vector<uint32_t> overflow_idx(static_cast<size_t>(hdr4.pilot_overflow_count), 0u);
            std::vector<uint32_t> overflow_val(static_cast<size_t>(hdr4.pilot_overflow_count), 0u);
            if (!readArray_(fin, overflow_idx)) {
                setErr_(err, "pilot_overflow_idx_read_failed");
                clear();
                return false;
            }
            if (!readArray_(fin, overflow_val)) {
                setErr_(err, "pilot_overflow_val_read_failed");
                clear();
                return false;
            }
            for (size_t i = 0; i < overflow_idx.size(); ++i) {
                const size_t idx = static_cast<size_t>(overflow_idx[i]);
                if (idx >= pilots_.size()) {
                    setErr_(err, "pilot_overflow_idx_oob");
                    clear();
                    return false;
                }
                pilots_[idx] = overflow_val[i];
            }
        }

        if (hdr.version != 4u && hdr.version != 6u) {
            if (hdr.pilot_bits == 8u) {
                std::vector<uint8_t> pilots_u8(static_cast<size_t>(hdr.bucket_count), 0u);
                if (!readArray_(fin, pilots_u8)) {
                    setErr_(err, "pilots_read_failed");
                    clear();
                    return false;
                }
                for (size_t i = 0; i < pilots_u8.size(); ++i) {
                    pilots_[i] = static_cast<uint32_t>(pilots_u8[i]);
                }
            } else {
                std::vector<uint16_t> pilots_u16(static_cast<size_t>(hdr.bucket_count), 0u);
                if (!readArray_(fin, pilots_u16)) {
                    setErr_(err, "pilots_read_failed");
                    clear();
                    return false;
                }
                for (size_t i = 0; i < pilots_u16.size(); ++i) {
                    pilots_[i] = static_cast<uint32_t>(pilots_u16[i]);
                }
            }
        }

        char tail = 0;
        if (fin.read(&tail, 1)) {
            setErr_(err, "unexpected_trailing_bytes");
            clear();
            return false;
        }

        // Set runtime fields before validate; EF decoder helpers rely on these values.
        pre_count_ = hdr.pre_count;
        edges_total_ = hdr.edges_total;
        bucket_target_ = hdr.bucket_target;
        flags_ = hdr.flags;
        seed_ = hdr.seed;
        bucket_count_ = hdr.bucket_count;
        pilot_bits_ = hdr.pilot_bits;
        version_ = hdr.version;

        bool ok = false;
        if (hdr.version == 1u) {
            ok = validateV1Arrays_(hdr, err);
            if (ok) layout_ = IndexLayout::SlotArrays;
        } else if (hdr.version == 2u) {
            ok = validateV2EliasFano_(hdr, hdr2, err);
            if (ok) layout_ = IndexLayout::EliasFano;
        } else if (hdr.version == 3u) {
            ok = validateV3RankEliasFano_(hdr, hdr3, err);
            if (ok) layout_ = IndexLayout::RankEliasFano;
        } else if (hdr.version == 4u) {
            ok = validateV4BucketBlockLocalMphf_(hdr, hdr4, err);
            if (ok) layout_ = IndexLayout::BucketBlockLocalMphf;
        } else if (hdr.version == 5u) {
            ok = validateV5BlockedRankEliasFano_(hdr, hdr5, err);
            if (ok) layout_ = IndexLayout::BlockedRankEliasFano;
        } else if (hdr.version == 6u) {
            ok = validateV6OrderedKeyRuns_(hdr, hdr6, err);
            if (ok) layout_ = IndexLayout::OrderedKeyRuns;
        } else if (hdr.version == 7u) {
            ok = validateV7OrderedKeyLenBlocks_(hdr, hdr7, err);
            if (ok) layout_ = IndexLayout::OrderedKeyRunsLenBlocks;
        }
        if (!ok) {
            clear();
            return false;
        }
        return true;
    }

    bool lookup(uint32_t pre_global, uint32_t& out_base, uint32_t& out_len) const {
        if (layout_ == IndexLayout::OrderedKeyRuns || layout_ == IndexLayout::OrderedKeyRunsLenBlocks) {
            uint32_t sid = 0u;
            uint32_t rank = 0u;
            uint32_t base = 0u;
            uint32_t len = 0u;
            if (!keyIndexAt_(pre_global, sid)) return false;
            if (!rankAtSid_(sid, rank)) return false;
            if (layout_ == IndexLayout::OrderedKeyRuns) {
                uint32_t next = 0u;
                if (!efBaseAt_(rank, base)) return false;
                if (!efBaseAt_(rank + 1u, next)) return false;
                if (next <= base) return false;
                len = next - base;
            } else {
                if (!lpblBaseLenAtRank_(rank, base, len)) return false;
            }
            if (base >= edges_total_) return false;
            if (len == 0u || len > edges_total_ - base) return false;
            out_base = base;
            out_len = len;
            return true;
        }
        if (pre_count_ == 0u || bucket_count_ == 0u) return false;
        if (pilots_.empty()) return false;
        const uint32_t b = hash1_(pre_global, seed_) % bucket_count_;
        const size_t pidx = static_cast<size_t>(b);
        if (pidx >= pilots_.size()) return false;
        const uint32_t pilot = static_cast<uint32_t>(pilots_[pidx]);
        const uint32_t slot = slotPos_(pre_global, seed_, pilot, pre_count_);
        if (slot >= pre_count_) return false;

        if (layout_ == IndexLayout::SlotArrays) {
            const size_t idx = static_cast<size_t>(slot);
            if (idx >= slot_base_.size() || idx >= slot_len_.size()) return false;
            const uint32_t base = slot_base_[idx];
            const uint32_t len = slot_len_[idx];
            if (len == 0u) return false;
            if (base >= edges_total_) return false;
            if (len > edges_total_ - base) return false;
            out_base = base;
            out_len = len;
            return true;
        }

        if (layout_ == IndexLayout::EliasFano) {
            uint32_t base = 0u;
            uint32_t next = 0u;
            if (!efBaseAt_(slot, base)) return false;
            if (!efBaseAt_(slot + 1u, next)) return false;
            if (next <= base) return false;
            uint32_t len = next - base;
            if (base >= edges_total_) return false;
            if (len > edges_total_ - base) return false;
            if (len == 0u) return false;
            out_base = base;
            out_len = len;
            return true;
        }

        if (layout_ == IndexLayout::RankEliasFano || layout_ == IndexLayout::BlockedRankEliasFano) {
            uint32_t rank = 0u;
            uint32_t base = 0u;
            uint32_t next = 0u;
            if (!rankAt_(slot, rank)) return false;
            if (!efBaseAt_(rank, base)) return false;
            if (!efBaseAt_(rank + 1u, next)) return false;
            if (next <= base) return false;
            uint32_t len = next - base;
            if (base >= edges_total_) return false;
            if (len > edges_total_ - base) return false;
            if (len == 0u) return false;
            out_base = base;
            out_len = len;
            return true;
        }

        if (layout_ == IndexLayout::BucketBlockLocalMphf) {
            uint32_t bucket_size = 0u;
            if (!bucketSizeAt_(b, bucket_size)) return false;
            if (bucket_size == 0u) return false;
            const uint32_t local_ord = localSlotPos_(pre_global, seed_, b, pilot, bucket_size);
            if (local_ord >= bucket_size) return false;
            if (block_span_ == 0u) return false;
            const uint32_t block = b / block_span_;
            const size_t block_idx = static_cast<size_t>(block);
            if (block_idx >= entry_block_prefix_.size() || block_idx >= base_block_prefix_.size()) return false;
            uint32_t entry_idx = entry_block_prefix_[block_idx];
            uint32_t base = base_block_prefix_[block_idx];
            const uint32_t block_start = block * block_span_;
            for (uint32_t cur = block_start; cur < b; ++cur) {
                uint32_t bs = 0u;
                uint32_t bp = 0u;
                if (!bucketSizeAt_(cur, bs)) return false;
                if (!bucketPayloadAt_(cur, bp)) return false;
                entry_idx += bs;
                base += bp;
            }
            for (uint32_t i = 0u; i < local_ord; ++i) {
                uint32_t l = 0u;
                if (!localLenAt_(entry_idx + i, l)) return false;
                base += l;
            }
            uint32_t len = 0u;
            if (!localLenAt_(entry_idx + local_ord, len)) return false;
            if (len == 0u) return false;
            if (base >= edges_total_) return false;
            if (len > edges_total_ - base) return false;
            out_base = base;
            out_len = len;
            return true;
        }
        return false;
    }

    void clear() {
        slot_base_.clear();
        slot_len_.clear();
        rank_words_.clear();
        ef_low_words_.clear();
        ef_high_words_.clear();
        ef_select_samples_.clear();
        bucket_size_words_.clear();
        bucket_payload_words_.clear();
        local_len_words_.clear();
        entry_block_prefix_.clear();
        base_block_prefix_.clear();
        perm_block_min_rank_.clear();
        perm_block_bits_.clear();
        perm_block_word_offset_.clear();
        perm_payload_words_.clear();
        key_ef_low_words_.clear();
        key_ef_high_words_.clear();
        key_ef_select_samples_.clear();
        run_ef_low_words_.clear();
        run_ef_high_words_.clear();
        run_ef_select_samples_.clear();
        sid_run_rank_words_.clear();
        lpbl_block_base_prefix_.clear();
        lpbl_block_word_offset_.clear();
        lpbl_block_mode_.clear();
        lpbl_block_arg_.clear();
        lpbl_payload_words_.clear();
        pilots_.clear();
        pre_count_ = 0;
        edges_total_ = 0;
        bucket_target_ = 0;
        flags_ = 0;
        seed_ = 0;
        bucket_count_ = 0;
        pilot_bits_ = 0;
        version_ = 0;
        rank_bits_ = 0;
        ef_l_ = 0;
        ef_select_step_ = 0;
        bucket_size_bits_ = 0;
        bucket_payload_bits_ = 0;
        local_len_bits_ = 0;
        block_span_ = 0;
        perm_block_size_ = 0;
        key_max_ = 0;
        key_ef_l_ = 0;
        key_ef_select_step_ = 0;
        run_count_ = 0;
        run_rank_bits_ = 0;
        run_ef_l_ = 0;
        run_ef_select_step_ = 0;
        lpbl_block_size_ = 0;
        layout_ = IndexLayout::None;
    }

    bool empty() const { return pre_count_ == 0u; }
    uint32_t preCount() const { return pre_count_; }
    uint32_t edgesTotal() const { return edges_total_; }
    uint32_t bucketTarget() const { return bucket_target_; }
    uint32_t flags() const { return flags_; }
    uint32_t version() const { return version_; }

private:
    enum class IndexLayout : uint8_t {
        None = 0,
        SlotArrays = 1,
        EliasFano = 2,
        RankEliasFano = 3,
        BucketBlockLocalMphf = 4,
        BlockedRankEliasFano = 5,
        OrderedKeyRuns = 6,
        OrderedKeyRunsLenBlocks = 7,
    };

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

    static uint32_t slotPos_(uint32_t key, uint32_t seed, uint32_t pilot, uint32_t nslots) {
        if (nslots == 0u) return 0u;
        const uint32_t pilot_seed = seed ^ static_cast<uint32_t>((pilot + 1u) * 0x9E3779B1u);
        return hash2_(key, pilot_seed) % nslots;
    }

    static uint32_t localSlotPos_(uint32_t key, uint32_t seed, uint32_t bucket, uint32_t pilot, uint32_t nslots) {
        if (nslots == 0u) return 0u;
        const uint32_t bucket_seed = mix32_(seed ^ mix32_(bucket ^ 0x6D2B79F5u));
        const uint32_t pilot_seed = bucket_seed ^ static_cast<uint32_t>((pilot + 1u) * 0x9E3779B1u);
        return hash2_(key, pilot_seed) % nslots;
    }

    static uint32_t popcount64_(uint64_t x) {
#if defined(__GNUC__) || defined(__clang__)
        return static_cast<uint32_t>(__builtin_popcountll(static_cast<unsigned long long>(x)));
#else
        uint32_t c = 0u;
        while (x) {
            x &= (x - 1u);
            ++c;
        }
        return c;
#endif
    }

    static uint32_t ctz64_(uint64_t x) {
#if defined(__GNUC__) || defined(__clang__)
        return static_cast<uint32_t>(__builtin_ctzll(static_cast<unsigned long long>(x)));
#else
        uint32_t n = 0u;
        while ((x & 1u) == 0u) {
            x >>= 1u;
            ++n;
        }
        return n;
#endif
    }

    static bool selectBitInWord_(uint64_t word, uint32_t kth_one_based, uint32_t& out_bit) {
        if (kth_one_based == 0u || word == 0u) return false;
        uint32_t k = kth_one_based;
        while (k > 1u) {
            word &= (word - 1u);
            if (word == 0u) return false;
            --k;
        }
        out_bit = ctz64_(word);
        return true;
    }

    bool validateV1Arrays_(const HeaderV1& hdr, std::string* err) const {
        if (static_cast<size_t>(hdr.pre_count) != slot_base_.size()) {
            setErr_(err, "slot_base_size_mismatch");
            return false;
        }
        if (static_cast<size_t>(hdr.pre_count) != slot_len_.size()) {
            setErr_(err, "slot_len_size_mismatch");
            return false;
        }
        if (static_cast<size_t>(hdr.bucket_count) != pilots_.size()) {
            setErr_(err, "pilots_size_mismatch");
            return false;
        }
        if (hdr.pre_count == 0u) {
            if (hdr.bucket_count != 0u) {
                setErr_(err, "empty_index_with_nonzero_bucket_count");
                return false;
            }
            return true;
        }
        if (hdr.bucket_count == 0u) {
            setErr_(err, "nonempty_index_with_zero_bucket_count");
            return false;
        }

        for (size_t i = 0; i < slot_base_.size(); ++i) {
            const uint32_t base = slot_base_[i];
            const uint32_t len = slot_len_[i];
            if (len == 0u) {
                setErr_(err, "zero_len_slot");
                return false;
            }
            if (base >= hdr.edges_total) {
                setErr_(err, "slot_base_oob");
                return false;
            }
            if (len > hdr.edges_total - base) {
                setErr_(err, "slot_span_oob");
                return false;
            }
        }
        return true;
    }

    bool rankAt_(uint32_t slot, uint32_t& out_rank) const {
        out_rank = 0u;
        if (slot >= pre_count_) return false;
        if (perm_block_size_ > 0u && !perm_block_min_rank_.empty()) {
            if (perm_block_size_ == 0u) return false;
            const uint32_t block = slot / perm_block_size_;
            const size_t block_idx = static_cast<size_t>(block);
            if (block_idx >= perm_block_min_rank_.size() || block_idx >= perm_block_bits_.size() || block_idx >= perm_block_word_offset_.size()) return false;
            const uint32_t block_start = block * perm_block_size_;
            const uint32_t slot_in_block = slot - block_start;
            const uint32_t block_len = ((block_start + perm_block_size_) < pre_count_) ? perm_block_size_ : (pre_count_ - block_start);
            if (slot_in_block >= block_len) return false;
            const uint32_t min_rank = perm_block_min_rank_[block_idx];
            const uint32_t bits = perm_block_bits_[block_idx];
            uint32_t delta = 0u;
            if (bits > 0u) {
                const uint64_t bit_pos = static_cast<uint64_t>(perm_block_word_offset_[block_idx]) * 64ull + static_cast<uint64_t>(slot_in_block) * static_cast<uint64_t>(bits);
                const size_t w = static_cast<size_t>(bit_pos >> 6);
                const uint32_t s = static_cast<uint32_t>(bit_pos & 63ull);
                if (w >= perm_payload_words_.size()) return false;
                uint64_t v = (perm_payload_words_[w] >> s);
                if ((s + bits) > 64u) {
                    if (w + 1u >= perm_payload_words_.size()) return false;
                    v |= (perm_payload_words_[w + 1u] << (64u - s));
                }
                const uint64_t mask = (bits >= 32u) ? 0xFFFFFFFFull : ((1ull << bits) - 1ull);
                delta = static_cast<uint32_t>(v & mask);
            }
            const uint64_t rank = static_cast<uint64_t>(min_rank) + static_cast<uint64_t>(delta);
            if (rank >= pre_count_) return false;
            out_rank = static_cast<uint32_t>(rank);
            return true;
        }
        if (rank_bits_ == 0u) return false;
        const uint64_t bit_pos = static_cast<uint64_t>(slot) * static_cast<uint64_t>(rank_bits_);
        const size_t w = static_cast<size_t>(bit_pos >> 6);
        const uint32_t s = static_cast<uint32_t>(bit_pos & 63ull);
        if (w >= rank_words_.size()) return false;
        uint64_t v = (rank_words_[w] >> s);
        if ((s + rank_bits_) > 64u) {
            if (w + 1u >= rank_words_.size()) return false;
            v |= (rank_words_[w + 1u] << (64u - s));
        }
        const uint64_t mask = (rank_bits_ >= 32u) ? 0xFFFFFFFFull : ((1ull << rank_bits_) - 1ull);
        const uint64_t rank = v & mask;
        if (rank >= pre_count_) return false;
        out_rank = static_cast<uint32_t>(rank);
        return true;
    }


    static bool fixedBitsAt_(const std::vector<uint64_t>& words, uint32_t idx, uint32_t bits, uint32_t& out_value) {
        out_value = 0u;
        if (bits == 0u || bits > 32u) return false;
        const uint64_t bit_pos = static_cast<uint64_t>(idx) * static_cast<uint64_t>(bits);
        const size_t w = static_cast<size_t>(bit_pos >> 6);
        const uint32_t s = static_cast<uint32_t>(bit_pos & 63ull);
        if (w >= words.size()) return false;
        uint64_t v = (words[w] >> s);
        if ((s + bits) > 64u) {
            if (w + 1u >= words.size()) return false;
            v |= (words[w + 1u] << (64u - s));
        }
        const uint64_t mask = (bits >= 32u) ? 0xFFFFFFFFull : ((1ull << bits) - 1ull);
        out_value = static_cast<uint32_t>(v & mask);
        return true;
    }

    bool bucketSizeAt_(uint32_t bucket, uint32_t& out_size) const {
        if (bucket >= bucket_count_) return false;
        return fixedBitsAt_(bucket_size_words_, bucket, bucket_size_bits_, out_size);
    }

    bool bucketPayloadAt_(uint32_t bucket, uint32_t& out_payload) const {
        if (bucket >= bucket_count_) return false;
        return fixedBitsAt_(bucket_payload_words_, bucket, bucket_payload_bits_, out_payload);
    }

    bool localLenAt_(uint32_t idx, uint32_t& out_len) const {
        if (idx >= pre_count_) return false;
        return fixedBitsAt_(local_len_words_, idx, local_len_bits_, out_len);
    }

    static bool efReadLowGeneric_(const std::vector<uint64_t>& low_words, uint32_t l, uint32_t idx, uint32_t& out_low) {
        out_low = 0u;
        if (l == 0u) return true;
        const uint64_t mask = (l == 32u) ? 0xFFFFFFFFull : ((1ull << l) - 1ull);
        const uint64_t bit_pos = static_cast<uint64_t>(idx) * static_cast<uint64_t>(l);
        const size_t w = static_cast<size_t>(bit_pos >> 6);
        const uint32_t s = static_cast<uint32_t>(bit_pos & 63ull);
        if (w >= low_words.size()) return false;
        uint64_t v = (low_words[w] >> s);
        if ((s + l) > 64u) {
            if (w + 1u >= low_words.size()) return false;
            v |= (low_words[w + 1u] << (64u - s));
        }
        out_low = static_cast<uint32_t>(v & mask);
        return true;
    }

    static bool efSelect1Generic_(const std::vector<uint64_t>& high_words, const std::vector<uint32_t>& select_samples, uint32_t select_step, uint32_t value_count, uint32_t one_idx, uint32_t& out_pos) {
        out_pos = 0u;
        if (one_idx >= value_count || select_step == 0u || value_count == 0u) return false;
        const uint32_t expected_select_count = (value_count + select_step - 1u) / select_step;
        if (select_samples.size() != static_cast<size_t>(expected_select_count)) return false;
        const uint32_t sample_idx = one_idx / select_step;
        const size_t sidx = static_cast<size_t>(sample_idx);
        if (sidx >= select_samples.size()) return false;
        uint32_t rank = sample_idx * select_step;
        uint32_t pos = select_samples[sidx];
        if (rank == one_idx) {
            out_pos = pos;
            return true;
        }
        uint32_t remain = one_idx - rank;
        uint64_t scan_pos = static_cast<uint64_t>(pos) + 1ull;
        size_t w = static_cast<size_t>(scan_pos >> 6);
        uint32_t offset = static_cast<uint32_t>(scan_pos & 63ull);
        if (w >= high_words.size()) return false;
        uint64_t word = high_words[w];
        if (offset > 0u) {
            word &= (~0ull << offset);
        }
        while (true) {
            const uint32_t pc = popcount64_(word);
            if (pc >= remain) {
                uint32_t bit = 0u;
                if (!selectBitInWord_(word, remain, bit)) return false;
                out_pos = static_cast<uint32_t>(static_cast<uint64_t>(w) * 64ull + static_cast<uint64_t>(bit));
                return true;
            }
            remain -= pc;
            ++w;
            if (w >= high_words.size()) return false;
            word = high_words[w];
        }
    }

    static bool efValueAtGeneric_(const std::vector<uint64_t>& low_words, const std::vector<uint64_t>& high_words, const std::vector<uint32_t>& select_samples, uint32_t l, uint32_t select_step, uint32_t value_count, uint32_t idx, uint32_t& out_value) {
        out_value = 0u;
        uint32_t high_pos = 0u;
        if (!efSelect1Generic_(high_words, select_samples, select_step, value_count, idx, high_pos)) return false;
        if (high_pos < idx) return false;
        const uint32_t high = high_pos - idx;
        uint32_t low = 0u;
        if (!efReadLowGeneric_(low_words, l, idx, low)) return false;
        const uint64_t v = (static_cast<uint64_t>(high) << l) | static_cast<uint64_t>(low);
        if (v > std::numeric_limits<uint32_t>::max()) return false;
        out_value = static_cast<uint32_t>(v);
        return true;
    }

    bool efBaseAt_(uint32_t idx, uint32_t& out_base) const {
        return efValueAtGeneric_(ef_low_words_, ef_high_words_, ef_select_samples_, ef_l_, ef_select_step_, pre_count_ + 1u, idx, out_base);
    }

    bool keyAtSid_(uint32_t sid, uint32_t& out_key) const {
        return efValueAtGeneric_(key_ef_low_words_, key_ef_high_words_, key_ef_select_samples_, key_ef_l_, key_ef_select_step_, pre_count_, sid, out_key);
    }

    bool runEndAt_(uint32_t run_idx, uint32_t& out_end) const {
        return efValueAtGeneric_(run_ef_low_words_, run_ef_high_words_, run_ef_select_samples_, run_ef_l_, run_ef_select_step_, run_count_, run_idx, out_end);
    }

    bool keyIndexAt_(uint32_t pre_global, uint32_t& out_sid) const {
        out_sid = 0u;
        if (pre_count_ == 0u) return false;
        uint32_t lo = 0u;
        uint32_t hi = pre_count_;
        while (lo < hi) {
            const uint32_t mid = lo + ((hi - lo) >> 1);
            uint32_t key = 0u;
            if (!keyAtSid_(mid, key)) return false;
            if (key < pre_global) lo = mid + 1u;
            else hi = mid;
        }
        if (lo >= pre_count_) return false;
        uint32_t key = 0u;
        if (!keyAtSid_(lo, key) || key != pre_global) return false;
        out_sid = lo;
        return true;
    }

    bool rankAtSid_(uint32_t sid, uint32_t& out_rank) const {
        out_rank = 0u;
        if (sid >= pre_count_ || run_count_ == 0u || run_rank_bits_ == 0u) return false;
        uint32_t lo = 0u;
        uint32_t hi = run_count_;
        while (lo < hi) {
            const uint32_t mid = lo + ((hi - lo) >> 1);
            uint32_t run_end = 0u;
            if (!runEndAt_(mid, run_end)) return false;
            if (sid < run_end) hi = mid;
            else lo = mid + 1u;
        }
        if (lo >= run_count_) return false;
        uint32_t run_end = 0u;
        if (!runEndAt_(lo, run_end)) return false;
        uint32_t run_start = 0u;
        if (lo > 0u && !runEndAt_(lo - 1u, run_start)) return false;
        if (sid < run_start || sid >= run_end) return false;
        uint32_t base_rank = 0u;
        if (!fixedBitsAt_(sid_run_rank_words_, lo, run_rank_bits_, base_rank)) return false;
        const uint64_t rank = static_cast<uint64_t>(base_rank) + static_cast<uint64_t>(sid - run_start);
        if (rank >= pre_count_) return false;
        out_rank = static_cast<uint32_t>(rank);
        return true;
    }

    static bool fixedBitsAtBitPos_(const std::vector<uint64_t>& words, uint64_t bit_pos, uint32_t bits, uint32_t& out_value) {
        out_value = 0u;
        if (bits == 0u || bits > 32u) return false;
        const size_t w = static_cast<size_t>(bit_pos >> 6);
        const uint32_t s = static_cast<uint32_t>(bit_pos & 63ull);
        if (w >= words.size()) return false;
        uint64_t v = (words[w] >> s);
        if ((s + bits) > 64u) {
            if (w + 1u >= words.size()) return false;
            v |= (words[w + 1u] << (64u - s));
        }
        const uint64_t mask = (bits >= 32u) ? 0xFFFFFFFFull : ((1ull << bits) - 1ull);
        out_value = static_cast<uint32_t>(v & mask);
        return true;
    }

    bool lpblLenAtRank_(uint32_t rank, uint32_t& out_len) const {
        out_len = 0u;
        if (rank >= pre_count_ || lpbl_block_size_ == 0u) return false;
        const uint32_t block = rank / lpbl_block_size_;
        const size_t block_idx = static_cast<size_t>(block);
        if (block_idx >= lpbl_block_base_prefix_.size() || block_idx >= lpbl_block_word_offset_.size() ||
            block_idx >= lpbl_block_mode_.size() || block_idx >= lpbl_block_arg_.size()) {
            return false;
        }
        const uint32_t block_start = block * lpbl_block_size_;
        const uint32_t block_len = ((block_start + lpbl_block_size_) < pre_count_) ? lpbl_block_size_ : (pre_count_ - block_start);
        const uint32_t off = rank - block_start;
        if (off >= block_len) return false;
        const uint32_t mode = lpbl_block_mode_[block_idx];
        const uint32_t arg = lpbl_block_arg_[block_idx];
        const uint32_t word_off = lpbl_block_word_offset_[block_idx];
        if (mode == 1u) {
            out_len = 1u;
            return true;
        }
        if (mode == 0u) {
            return fixedBitsAtBitPos_(lpbl_payload_words_, static_cast<uint64_t>(word_off) * 64ull + static_cast<uint64_t>(off) * static_cast<uint64_t>(arg), arg, out_len);
        }
        if (mode == 2u) {
            const uint32_t bitmap_words = (block_len + 63u) / 64u;
            const size_t bitmap_idx = static_cast<size_t>(word_off + (off >> 6));
            if (bitmap_idx >= lpbl_payload_words_.size()) return false;
            const uint64_t bitmap_word = lpbl_payload_words_[bitmap_idx];
            const uint32_t bit = off & 63u;
            if (((bitmap_word >> bit) & 1ull) == 0ull) {
                out_len = 1u;
                return true;
            }
            uint32_t exc_idx = 0u;
            for (uint32_t wi = 0u; wi < (off >> 6); ++wi) {
                const size_t idx = static_cast<size_t>(word_off + wi);
                if (idx >= lpbl_payload_words_.size()) return false;
                exc_idx += static_cast<uint32_t>(__builtin_popcountll(lpbl_payload_words_[idx]));
            }
            const uint64_t mask = (bit == 0u) ? 0ull : ((1ull << bit) - 1ull);
            exc_idx += static_cast<uint32_t>(__builtin_popcountll(bitmap_word & mask));
            return fixedBitsAtBitPos_(lpbl_payload_words_, static_cast<uint64_t>(word_off + bitmap_words) * 64ull + static_cast<uint64_t>(exc_idx) * static_cast<uint64_t>(arg), arg, out_len);
        }
        return false;
    }

    bool lpblBaseLenAtRank_(uint32_t rank, uint32_t& out_base, uint32_t& out_len) const {
        out_base = 0u;
        out_len = 0u;
        if (rank >= pre_count_ || lpbl_block_size_ == 0u) return false;
        const uint32_t block = rank / lpbl_block_size_;
        const size_t block_idx = static_cast<size_t>(block);
        if (block_idx >= lpbl_block_base_prefix_.size()) return false;
        const uint32_t block_start = block * lpbl_block_size_;
        const uint32_t off = rank - block_start;
        uint32_t base = lpbl_block_base_prefix_[block_idx];
        for (uint32_t i = 0u; i < off; ++i) {
            uint32_t l = 0u;
            if (!lpblLenAtRank_(block_start + i, l)) return false;
            base += l;
        }
        if (!lpblLenAtRank_(rank, out_len)) return false;
        if (out_len == 0u) return false;
        out_base = base;
        return true;
    }

    bool validateV3RankEliasFano_(const HeaderV1& hdr, const HeaderV3Extra& hdr3, std::string* err) const {
        if (hdr3.rank_bits == 0u || hdr3.rank_bits > 31u) {
            setErr_(err, "rank_bits_invalid");
            return false;
        }
        const uint64_t total_rank_bits = static_cast<uint64_t>(hdr.pre_count) * static_cast<uint64_t>(hdr3.rank_bits);
        const uint32_t expected_rank_word_count = static_cast<uint32_t>((total_rank_bits + 63ull) / 64ull);
        if (hdr3.rank_word_count != expected_rank_word_count) {
            setErr_(err, "rank_word_count_mismatch");
            return false;
        }
        if (static_cast<size_t>(hdr3.rank_word_count) != rank_words_.size()) {
            setErr_(err, "rank_words_size_mismatch");
            return false;
        }

        HeaderV2Extra fake{};
        fake.ef_l = hdr3.ef_l;
        fake.ef_low_word_count = hdr3.ef_low_word_count;
        fake.ef_high_word_count = hdr3.ef_high_word_count;
        fake.ef_select_step = hdr3.ef_select_step;
        fake.ef_select_count = hdr3.ef_select_count;
        if (!validateV2EliasFano_(hdr, fake, err)) {
            return false;
        }

        std::vector<uint8_t> seen(static_cast<size_t>(hdr.pre_count), 0u);
        for (uint32_t slot = 0u; slot < hdr.pre_count; ++slot) {
            uint32_t rank = 0u;
            if (!rankAt_(slot, rank)) {
                setErr_(err, "rank_decode_failed");
                return false;
            }
            if (rank >= hdr.pre_count) {
                setErr_(err, "rank_oob");
                return false;
            }
            if (seen[static_cast<size_t>(rank)] != 0u) {
                setErr_(err, "rank_not_permutation");
                return false;
            }
            seen[static_cast<size_t>(rank)] = 1u;
        }
        for (size_t i = 0; i < seen.size(); ++i) {
            if (seen[i] == 0u) {
                setErr_(err, "rank_not_permutation");
                return false;
            }
        }
        return true;
    }


    bool validateV5BlockedRankEliasFano_(const HeaderV1& hdr, const HeaderV5Extra& hdr5, std::string* err) const {
        if (hdr5.block_size == 0u) {
            setErr_(err, "v5_block_size_zero");
            return false;
        }
        const uint32_t expected_block_count = (hdr.pre_count + hdr5.block_size - 1u) / hdr5.block_size;
        if (hdr5.block_count != expected_block_count) {
            setErr_(err, "v5_block_count_mismatch");
            return false;
        }
        if (hdr5.block_desc_count != hdr5.block_count) {
            setErr_(err, "v5_block_desc_count_mismatch");
            return false;
        }
        if (static_cast<size_t>(hdr5.block_desc_count) != perm_block_min_rank_.size() ||
            static_cast<size_t>(hdr5.block_desc_count) != perm_block_bits_.size() ||
            static_cast<size_t>(hdr5.block_desc_count) != perm_block_word_offset_.size()) {
            setErr_(err, "v5_block_desc_size_mismatch");
            return false;
        }
        if (static_cast<size_t>(hdr5.block_payload_word_count) != perm_payload_words_.size()) {
            setErr_(err, "v5_block_payload_word_count_mismatch");
            return false;
        }
        HeaderV2Extra fake{};
        fake.ef_l = hdr5.ef_l;
        fake.ef_low_word_count = hdr5.ef_low_word_count;
        fake.ef_high_word_count = hdr5.ef_high_word_count;
        fake.ef_select_step = hdr5.ef_select_step;
        fake.ef_select_count = hdr5.ef_select_count;
        if (!validateV2EliasFano_(hdr, fake, err)) {
            return false;
        }

        uint32_t expected_word_off = 0u;
        for (uint32_t block = 0u; block < hdr5.block_count; ++block) {
            const size_t idx = static_cast<size_t>(block);
            const uint32_t block_start = block * hdr5.block_size;
            const uint32_t block_len = ((block_start + hdr5.block_size) < hdr.pre_count) ? hdr5.block_size : (hdr.pre_count - block_start);
            if (perm_block_word_offset_[idx] != expected_word_off) {
                setErr_(err, "v5_block_word_offset_mismatch");
                return false;
            }
            if (perm_block_min_rank_[idx] >= hdr.pre_count) {
                setErr_(err, "v5_block_min_rank_oob");
                return false;
            }
            const uint32_t bits = perm_block_bits_[idx];
            if (bits > 31u) {
                setErr_(err, "v5_block_bits_invalid");
                return false;
            }
            const uint32_t words = (bits == 0u) ? 0u : static_cast<uint32_t>(((static_cast<uint64_t>(block_len) * static_cast<uint64_t>(bits)) + 63ull) / 64ull);
            if (expected_word_off > hdr5.block_payload_word_count - words) {
                setErr_(err, "v5_block_payload_overflow");
                return false;
            }
            expected_word_off += words;
        }
        if (expected_word_off != hdr5.block_payload_word_count) {
            setErr_(err, "v5_block_payload_terminal_mismatch");
            return false;
        }

        std::vector<uint8_t> seen(static_cast<size_t>(hdr.pre_count), 0u);
        for (uint32_t slot = 0u; slot < hdr.pre_count; ++slot) {
            uint32_t rank = 0u;
            if (!rankAt_(slot, rank)) {
                setErr_(err, "v5_rank_decode_failed");
                return false;
            }
            if (rank >= hdr.pre_count) {
                setErr_(err, "v5_rank_oob");
                return false;
            }
            if (seen[static_cast<size_t>(rank)] != 0u) {
                setErr_(err, "v5_rank_not_permutation");
                return false;
            }
            seen[static_cast<size_t>(rank)] = 1u;
        }
        for (size_t i = 0; i < seen.size(); ++i) {
            if (seen[i] == 0u) {
                setErr_(err, "v5_rank_not_permutation");
                return false;
            }
        }
        return true;
    }

    bool validateV6OrderedKeyRuns_(const HeaderV1& hdr, const HeaderV6Extra& hdr6, std::string* err) const {
        if (hdr.bucket_count != 0u) {
            setErr_(err, "v6_bucket_count_nonzero");
            return false;
        }
        if (!pilots_.empty()) {
            setErr_(err, "v6_pilots_not_empty");
            return false;
        }
        if (static_cast<size_t>(hdr6.key_ef_low_word_count) != key_ef_low_words_.size() ||
            static_cast<size_t>(hdr6.key_ef_high_word_count) != key_ef_high_words_.size() ||
            static_cast<size_t>(hdr6.key_ef_select_count) != key_ef_select_samples_.size()) {
            setErr_(err, "v6_key_ef_size_mismatch");
            return false;
        }
        if (hdr.pre_count == 0u) {
            if (hdr6.run_count != 0u || hdr6.run_rank_bits != 0u || !sid_run_rank_words_.empty() || !run_ef_low_words_.empty() || !run_ef_high_words_.empty() || !run_ef_select_samples_.empty()) {
                setErr_(err, "v6_empty_nonempty_payload");
                return false;
            }
            if (hdr6.base_ef_select_count != 0u || !ef_low_words_.empty() || !ef_high_words_.empty() || !ef_select_samples_.empty()) {
                setErr_(err, "v6_empty_base_payload_nonzero");
                return false;
            }
            return true;
        }
        if (hdr6.key_ef_select_step == 0u) {
            setErr_(err, "v6_key_select_step_zero");
            return false;
        }
        const uint32_t expected_key_select_count = (hdr.pre_count + hdr6.key_ef_select_step - 1u) / hdr6.key_ef_select_step;
        if (hdr6.key_ef_select_count != expected_key_select_count) {
            setErr_(err, "v6_key_select_count_mismatch");
            return false;
        }
        if (hdr6.run_count == 0u) {
            setErr_(err, "v6_run_count_zero");
            return false;
        }
        if (hdr6.run_rank_bits == 0u || hdr6.run_rank_bits > 31u) {
            setErr_(err, "v6_run_rank_bits_invalid");
            return false;
        }
        const uint64_t total_run_rank_bits = static_cast<uint64_t>(hdr6.run_count) * static_cast<uint64_t>(hdr6.run_rank_bits);
        const uint32_t expected_run_rank_word_count = static_cast<uint32_t>((total_run_rank_bits + 63ull) / 64ull);
        if (hdr6.run_rank_word_count != expected_run_rank_word_count || static_cast<size_t>(hdr6.run_rank_word_count) != sid_run_rank_words_.size()) {
            setErr_(err, "v6_run_rank_word_count_mismatch");
            return false;
        }
        if (hdr6.run_ef_select_step == 0u) {
            setErr_(err, "v6_run_select_step_zero");
            return false;
        }
        const uint32_t expected_run_select_count = (hdr6.run_count + hdr6.run_ef_select_step - 1u) / hdr6.run_ef_select_step;
        if (hdr6.run_ef_select_count != expected_run_select_count) {
            setErr_(err, "v6_run_select_count_mismatch");
            return false;
        }
        if (static_cast<size_t>(hdr6.run_ef_low_word_count) != run_ef_low_words_.size() ||
            static_cast<size_t>(hdr6.run_ef_high_word_count) != run_ef_high_words_.size() ||
            static_cast<size_t>(hdr6.run_ef_select_count) != run_ef_select_samples_.size()) {
            setErr_(err, "v6_run_ef_size_mismatch");
            return false;
        }
        if (hdr6.base_ef_select_step == 0u) {
            setErr_(err, "v6_base_select_step_zero");
            return false;
        }
        const uint32_t expected_base_select_count = ((hdr.pre_count + 1u) + hdr6.base_ef_select_step - 1u) / hdr6.base_ef_select_step;
        if (hdr6.base_ef_select_count != expected_base_select_count) {
            setErr_(err, "v6_base_select_count_mismatch");
            return false;
        }
        if (static_cast<size_t>(hdr6.base_ef_low_word_count) != ef_low_words_.size() ||
            static_cast<size_t>(hdr6.base_ef_high_word_count) != ef_high_words_.size() ||
            static_cast<size_t>(hdr6.base_ef_select_count) != ef_select_samples_.size()) {
            setErr_(err, "v6_base_ef_size_mismatch");
            return false;
        }

        uint32_t prev_key = 0u;
        for (uint32_t sid = 0u; sid < hdr.pre_count; ++sid) {
            uint32_t key = 0u;
            if (!keyAtSid_(sid, key)) {
                setErr_(err, "v6_key_decode_failed");
                return false;
            }
            if (sid > 0u && key <= prev_key) {
                setErr_(err, "v6_key_not_strictly_increasing");
                return false;
            }
            prev_key = key;
        }
        if (prev_key != hdr6.key_max) {
            setErr_(err, "v6_key_max_mismatch");
            return false;
        }

        std::vector<uint8_t> seen(static_cast<size_t>(hdr.pre_count), 0u);
        uint32_t prev_end = 0u;
        for (uint32_t run = 0u; run < hdr6.run_count; ++run) {
            uint32_t run_end = 0u;
            if (!runEndAt_(run, run_end)) {
                setErr_(err, "v6_run_end_decode_failed");
                return false;
            }
            if (run_end <= prev_end || run_end > hdr.pre_count) {
                setErr_(err, "v6_run_end_invalid");
                return false;
            }
            uint32_t base_rank = 0u;
            if (!fixedBitsAt_(sid_run_rank_words_, run, hdr6.run_rank_bits, base_rank)) {
                setErr_(err, "v6_run_rank_decode_failed");
                return false;
            }
            const uint32_t len = run_end - prev_end;
            if (base_rank > hdr.pre_count - len) {
                setErr_(err, "v6_run_span_oob");
                return false;
            }
            for (uint32_t i = 0u; i < len; ++i) {
                const uint32_t rank = base_rank + i;
                if (seen[static_cast<size_t>(rank)] != 0u) {
                    setErr_(err, "v6_rank_not_permutation");
                    return false;
                }
                seen[static_cast<size_t>(rank)] = 1u;
            }
            prev_end = run_end;
        }
        if (prev_end != hdr.pre_count) {
            setErr_(err, "v6_run_terminal_mismatch");
            return false;
        }
        for (size_t i = 0; i < seen.size(); ++i) {
            if (seen[i] == 0u) {
                setErr_(err, "v6_rank_not_permutation");
                return false;
            }
        }

        uint32_t prev_base = 0u;
        for (uint32_t i = 0u; i <= hdr.pre_count; ++i) {
            uint32_t base = 0u;
            if (!efBaseAt_(i, base)) {
                setErr_(err, "v6_base_decode_failed");
                return false;
            }
            if (i == 0u && base != 0u) {
                setErr_(err, "v6_base0_not_zero");
                return false;
            }
            if (i > 0u && base < prev_base) {
                setErr_(err, "v6_base_not_monotonic");
                return false;
            }
            prev_base = base;
        }
        if (prev_base != hdr.edges_total) {
            setErr_(err, "v6_last_base_mismatch_edges_total");
            return false;
        }
        return true;
    }

    bool validateV7OrderedKeyLenBlocks_(const HeaderV1& hdr, const HeaderV7Extra& hdr7, std::string* err) const {
        if (hdr.pre_count == 0u) {
            if (hdr7.run_count != 0u || hdr7.run_rank_bits != 0u || !sid_run_rank_words_.empty() || !run_ef_low_words_.empty() || !run_ef_high_words_.empty() || !run_ef_select_samples_.empty()) {
                setErr_(err, "v7_empty_nonempty_run_payload");
                return false;
            }
            if (hdr7.len_block_count != 0u || hdr7.len_payload_word_count != 0u || !lpbl_block_base_prefix_.empty() || !lpbl_block_word_offset_.empty() || !lpbl_block_mode_.empty() || !lpbl_block_arg_.empty() || !lpbl_payload_words_.empty()) {
                setErr_(err, "v7_empty_nonempty_len_payload");
                return false;
            }
            return true;
        }
        if (hdr7.key_ef_select_step == 0u) {
            setErr_(err, "v7_key_select_step_zero");
            return false;
        }
        const uint32_t expected_key_select_count = (hdr.pre_count + hdr7.key_ef_select_step - 1u) / hdr7.key_ef_select_step;
        if (hdr7.key_ef_select_count != expected_key_select_count) {
            setErr_(err, "v7_key_select_count_mismatch");
            return false;
        }
        if (hdr7.run_count == 0u) {
            setErr_(err, "v7_run_count_zero");
            return false;
        }
        if (hdr7.run_rank_bits == 0u || hdr7.run_rank_bits > 31u) {
            setErr_(err, "v7_run_rank_bits_invalid");
            return false;
        }
        const uint64_t total_run_rank_bits = static_cast<uint64_t>(hdr7.run_count) * static_cast<uint64_t>(hdr7.run_rank_bits);
        const uint32_t expected_run_rank_word_count = static_cast<uint32_t>((total_run_rank_bits + 63ull) / 64ull);
        if (hdr7.run_rank_word_count != expected_run_rank_word_count || static_cast<size_t>(hdr7.run_rank_word_count) != sid_run_rank_words_.size()) {
            setErr_(err, "v7_run_rank_word_count_mismatch");
            return false;
        }
        if (hdr7.run_ef_select_step == 0u) {
            setErr_(err, "v7_run_select_step_zero");
            return false;
        }
        const uint32_t expected_run_select_count = (hdr7.run_count + hdr7.run_ef_select_step - 1u) / hdr7.run_ef_select_step;
        if (hdr7.run_ef_select_count != expected_run_select_count) {
            setErr_(err, "v7_run_select_count_mismatch");
            return false;
        }
        if (static_cast<size_t>(hdr7.run_ef_low_word_count) != run_ef_low_words_.size() ||
            static_cast<size_t>(hdr7.run_ef_high_word_count) != run_ef_high_words_.size() ||
            static_cast<size_t>(hdr7.run_ef_select_count) != run_ef_select_samples_.size()) {
            setErr_(err, "v7_run_ef_size_mismatch");
            return false;
        }
        if (hdr7.len_block_size == 0u) {
            setErr_(err, "v7_len_block_size_zero");
            return false;
        }
        const uint32_t expected_block_count = (hdr.pre_count + hdr7.len_block_size - 1u) / hdr7.len_block_size;
        if (hdr7.len_block_count != expected_block_count) {
            setErr_(err, "v7_len_block_count_mismatch");
            return false;
        }
        if (lpbl_block_base_prefix_.size() != static_cast<size_t>(expected_block_count) ||
            lpbl_block_word_offset_.size() != static_cast<size_t>(expected_block_count) ||
            lpbl_block_mode_.size() != static_cast<size_t>(expected_block_count) ||
            lpbl_block_arg_.size() != static_cast<size_t>(expected_block_count) ||
            lpbl_payload_words_.size() != static_cast<size_t>(hdr7.len_payload_word_count)) {
            setErr_(err, "v7_len_payload_size_mismatch");
            return false;
        }

        uint32_t prev_key = 0u;
        for (uint32_t sid = 0u; sid < hdr.pre_count; ++sid) {
            uint32_t key = 0u;
            if (!keyAtSid_(sid, key)) {
                setErr_(err, "v7_key_decode_failed");
                return false;
            }
            if (sid > 0u && key <= prev_key) {
                setErr_(err, "v7_key_not_strictly_increasing");
                return false;
            }
            prev_key = key;
        }
        if (prev_key != hdr7.key_max) {
            setErr_(err, "v7_key_max_mismatch");
            return false;
        }

        std::vector<uint8_t> seen(static_cast<size_t>(hdr.pre_count), 0u);
        uint32_t prev_end = 0u;
        for (uint32_t run = 0u; run < hdr7.run_count; ++run) {
            uint32_t run_end = 0u;
            if (!runEndAt_(run, run_end)) {
                setErr_(err, "v7_run_end_decode_failed");
                return false;
            }
            if (run_end <= prev_end || run_end > hdr.pre_count) {
                setErr_(err, "v7_run_end_invalid");
                return false;
            }
            uint32_t base_rank = 0u;
            if (!fixedBitsAt_(sid_run_rank_words_, run, hdr7.run_rank_bits, base_rank)) {
                setErr_(err, "v7_run_rank_decode_failed");
                return false;
            }
            const uint32_t len = run_end - prev_end;
            if (base_rank > hdr.pre_count - len) {
                setErr_(err, "v7_run_span_oob");
                return false;
            }
            for (uint32_t i = 0u; i < len; ++i) {
                const uint32_t rank = base_rank + i;
                if (seen[static_cast<size_t>(rank)] != 0u) {
                    setErr_(err, "v7_rank_not_permutation");
                    return false;
                }
                seen[static_cast<size_t>(rank)] = 1u;
            }
            prev_end = run_end;
        }
        if (prev_end != hdr.pre_count) {
            setErr_(err, "v7_run_terminal_mismatch");
            return false;
        }
        for (size_t i = 0; i < seen.size(); ++i) {
            if (seen[i] == 0u) {
                setErr_(err, "v7_rank_not_permutation");
                return false;
            }
        }

        uint32_t next_expected_base = 0u;
        for (uint32_t rank = 0u; rank < hdr.pre_count; ++rank) {
            uint32_t base = 0u;
            uint32_t len = 0u;
            if (!lpblBaseLenAtRank_(rank, base, len)) {
                setErr_(err, "v7_len_decode_failed");
                return false;
            }
            if (rank == 0u && base != 0u) {
                setErr_(err, "v7_base0_not_zero");
                return false;
            }
            if (base != next_expected_base) {
                setErr_(err, "v7_base_not_contiguous");
                return false;
            }
            if (len == 0u || base >= hdr.edges_total || len > hdr.edges_total - base) {
                setErr_(err, "v7_len_span_oob");
                return false;
            }
            next_expected_base = base + len;
        }
        if (next_expected_base != hdr.edges_total) {
            setErr_(err, "v7_terminal_base_mismatch");
            return false;
        }
        return true;
    }

    bool validateV4BucketBlockLocalMphf_(const HeaderV1& hdr, const HeaderV4Extra& hdr4, std::string* err) const {
        if (static_cast<size_t>(hdr.bucket_count) != pilots_.size()) {
            setErr_(err, "pilots_size_mismatch");
            return false;
        }
        if (hdr.pre_count == 0u) {
            if (hdr.bucket_count != 0u) {
                setErr_(err, "empty_index_with_nonzero_bucket_count");
                return false;
            }
            if (!bucket_size_words_.empty() || !bucket_payload_words_.empty() || !local_len_words_.empty()) {
                setErr_(err, "empty_index_with_nonempty_payload");
                return false;
            }
            if (!entry_block_prefix_.empty() || !base_block_prefix_.empty()) {
                setErr_(err, "empty_index_with_nonempty_block_prefix");
                return false;
            }
            return true;
        }
        if (hdr.bucket_count == 0u) {
            setErr_(err, "nonempty_index_with_zero_bucket_count");
            return false;
        }
        if (hdr4.bucket_size_bits == 0u || hdr4.bucket_size_bits > 32u) {
            setErr_(err, "bucket_size_bits_invalid");
            return false;
        }
        if (hdr4.bucket_payload_bits == 0u || hdr4.bucket_payload_bits > 32u) {
            setErr_(err, "bucket_payload_bits_invalid");
            return false;
        }
        if (hdr4.local_len_bits == 0u || hdr4.local_len_bits > 32u) {
            setErr_(err, "local_len_bits_invalid");
            return false;
        }
        const uint64_t bucket_size_total_bits = static_cast<uint64_t>(hdr.bucket_count) * static_cast<uint64_t>(hdr4.bucket_size_bits);
        const uint64_t bucket_payload_total_bits = static_cast<uint64_t>(hdr.bucket_count) * static_cast<uint64_t>(hdr4.bucket_payload_bits);
        const uint64_t local_len_total_bits = static_cast<uint64_t>(hdr.pre_count) * static_cast<uint64_t>(hdr4.local_len_bits);
        const uint32_t expect_bucket_size_words = static_cast<uint32_t>((bucket_size_total_bits + 63ull) / 64ull);
        const uint32_t expect_bucket_payload_words = static_cast<uint32_t>((bucket_payload_total_bits + 63ull) / 64ull);
        const uint32_t expect_local_len_words = static_cast<uint32_t>((local_len_total_bits + 63ull) / 64ull);
        if (hdr4.bucket_size_word_count != expect_bucket_size_words || static_cast<size_t>(hdr4.bucket_size_word_count) != bucket_size_words_.size()) {
            setErr_(err, "bucket_size_word_count_mismatch");
            return false;
        }
        if (hdr4.bucket_payload_word_count != expect_bucket_payload_words || static_cast<size_t>(hdr4.bucket_payload_word_count) != bucket_payload_words_.size()) {
            setErr_(err, "bucket_payload_word_count_mismatch");
            return false;
        }
        if (hdr4.local_len_word_count != expect_local_len_words || static_cast<size_t>(hdr4.local_len_word_count) != local_len_words_.size()) {
            setErr_(err, "local_len_word_count_mismatch");
            return false;
        }
        if (hdr4.block_span == 0u) {
            setErr_(err, "block_span_zero");
            return false;
        }
        const uint32_t expected_block_count = (hdr.bucket_count + hdr4.block_span - 1u) / hdr4.block_span;
        if (hdr4.block_count != expected_block_count) {
            setErr_(err, "block_count_mismatch");
            return false;
        }
        if (static_cast<size_t>(hdr4.block_count) != entry_block_prefix_.size() ||
            static_cast<size_t>(hdr4.block_count) != base_block_prefix_.size()) {
            setErr_(err, "block_prefix_size_mismatch");
            return false;
        }
        if (hdr4.pilot_overflow_count > hdr.bucket_count) {
            setErr_(err, "pilot_overflow_count_oob");
            return false;
        }

        uint32_t sum_entries = 0u;
        uint32_t sum_payload = 0u;
        for (uint32_t block = 0u; block < hdr4.block_count; ++block) {
            if (entry_block_prefix_[static_cast<size_t>(block)] != sum_entries) {
                setErr_(err, "entry_block_prefix_mismatch");
                return false;
            }
            if (base_block_prefix_[static_cast<size_t>(block)] != sum_payload) {
                setErr_(err, "base_block_prefix_mismatch");
                return false;
            }
            const uint32_t start = block * hdr4.block_span;
            const uint32_t end = (start + hdr4.block_span < hdr.bucket_count) ? (start + hdr4.block_span) : hdr.bucket_count;
            for (uint32_t b = start; b < end; ++b) {
                uint32_t bucket_size = 0u;
                uint32_t bucket_payload = 0u;
                if (!bucketSizeAt_(b, bucket_size)) {
                    setErr_(err, "bucket_size_decode_failed");
                    return false;
                }
                if (!bucketPayloadAt_(b, bucket_payload)) {
                    setErr_(err, "bucket_payload_decode_failed");
                    return false;
                }
                if (bucket_size == 0u && bucket_payload != 0u) {
                    setErr_(err, "empty_bucket_with_payload");
                    return false;
                }
                uint32_t local_payload = 0u;
                for (uint32_t i = 0u; i < bucket_size; ++i) {
                    uint32_t len = 0u;
                    if (!localLenAt_(sum_entries + i, len)) {
                        setErr_(err, "local_len_decode_failed");
                        return false;
                    }
                    if (len == 0u) {
                        setErr_(err, "local_len_zero");
                        return false;
                    }
                    if (local_payload > hdr.edges_total - len) {
                        setErr_(err, "local_payload_overflow");
                        return false;
                    }
                    local_payload += len;
                }
                if (local_payload != bucket_payload) {
                    setErr_(err, "bucket_payload_mismatch");
                    return false;
                }
                if (sum_entries > hdr.pre_count - bucket_size) {
                    setErr_(err, "bucket_entries_overflow");
                    return false;
                }
                sum_entries += bucket_size;
                if (sum_payload > hdr.edges_total - bucket_payload) {
                    setErr_(err, "bucket_payload_overflow");
                    return false;
                }
                sum_payload += bucket_payload;
            }
        }
        if (sum_entries != hdr.pre_count) {
            setErr_(err, "pre_count_mismatch");
            return false;
        }
        if (sum_payload != hdr.edges_total) {
            setErr_(err, "edges_total_mismatch");
            return false;
        }
        return true;
    }

    bool validateV2EliasFano_(const HeaderV1& hdr, const HeaderV2Extra& hdr2, std::string* err) const {
        if (hdr2.ef_l > 31u) {
            setErr_(err, "ef_l_unsupported");
            return false;
        }
        if (hdr2.ef_select_step == 0u) {
            setErr_(err, "ef_select_step_zero");
            return false;
        }
        if (hdr.pre_count > std::numeric_limits<uint32_t>::max() - 1u) {
            setErr_(err, "pre_count_overflow");
            return false;
        }
        const uint32_t base_count = hdr.pre_count + 1u;
        const uint32_t expected_select_count =
            (base_count + hdr2.ef_select_step - 1u) / hdr2.ef_select_step;
        if (expected_select_count == 0u) {
            setErr_(err, "ef_select_count_zero");
            return false;
        }
        if (hdr2.ef_select_count != expected_select_count) {
            setErr_(err, "ef_select_count_mismatch");
            return false;
        }
        if (static_cast<size_t>(hdr2.ef_low_word_count) != ef_low_words_.size()) {
            setErr_(err, "ef_low_size_mismatch");
            return false;
        }
        if (static_cast<size_t>(hdr2.ef_high_word_count) != ef_high_words_.size()) {
            setErr_(err, "ef_high_size_mismatch");
            return false;
        }
        if (static_cast<size_t>(hdr2.ef_select_count) != ef_select_samples_.size()) {
            setErr_(err, "ef_select_size_mismatch");
            return false;
        }
        if (static_cast<size_t>(hdr.bucket_count) != pilots_.size()) {
            setErr_(err, "pilots_size_mismatch");
            return false;
        }
        if (hdr.pre_count == 0u) {
            if (hdr.bucket_count != 0u) {
                setErr_(err, "empty_index_with_nonzero_bucket_count");
                return false;
            }
        } else if (hdr.bucket_count == 0u) {
            setErr_(err, "nonempty_index_with_zero_bucket_count");
            return false;
        }

        uint32_t prev = 0u;
        for (uint32_t i = 0u; i <= hdr.pre_count; ++i) {
            uint32_t b = 0u;
            if (!efBaseAt_(i, b)) {
                setErr_(err, "ef_base_decode_failed");
                return false;
            }
            if (i == 0u && b != 0u) {
                setErr_(err, "ef_base0_not_zero");
                return false;
            }
            if (i > 0u && b < prev) {
                setErr_(err, "ef_base_not_monotonic");
                return false;
            }
            prev = b;
        }
        if (prev != hdr.edges_total) {
            setErr_(err, "ef_last_base_mismatch_edges_total");
            return false;
        }

        for (uint32_t i = 0u; i < hdr.pre_count; ++i) {
            uint32_t b0 = 0u;
            uint32_t b1 = 0u;
            if (!efBaseAt_(i, b0) || !efBaseAt_(i + 1u, b1)) {
                setErr_(err, "ef_slot_decode_failed");
                return false;
            }
            if (b1 <= b0) {
                setErr_(err, "ef_zero_or_negative_len");
                return false;
            }
            if (b0 >= hdr.edges_total) {
                setErr_(err, "ef_base_oob");
                return false;
            }
            if ((b1 - b0) > (hdr.edges_total - b0)) {
                setErr_(err, "ef_span_oob");
                return false;
            }
        }
        return true;
    }

    std::vector<uint32_t> slot_base_;
    std::vector<uint32_t> slot_len_;
    std::vector<uint64_t> rank_words_;
    std::vector<uint64_t> ef_low_words_;
    std::vector<uint64_t> ef_high_words_;
    std::vector<uint32_t> ef_select_samples_;
    std::vector<uint64_t> bucket_size_words_;
    std::vector<uint64_t> bucket_payload_words_;
    std::vector<uint64_t> local_len_words_;
    std::vector<uint32_t> entry_block_prefix_;
    std::vector<uint32_t> base_block_prefix_;
    std::vector<uint32_t> perm_block_min_rank_;
    std::vector<uint32_t> perm_block_bits_;
    std::vector<uint32_t> perm_block_word_offset_;
    std::vector<uint64_t> perm_payload_words_;
    std::vector<uint64_t> key_ef_low_words_;
    std::vector<uint64_t> key_ef_high_words_;
    std::vector<uint32_t> key_ef_select_samples_;
    std::vector<uint64_t> run_ef_low_words_;
    std::vector<uint64_t> run_ef_high_words_;
    std::vector<uint32_t> run_ef_select_samples_;
    std::vector<uint64_t> sid_run_rank_words_;
    std::vector<uint32_t> lpbl_block_base_prefix_;
    std::vector<uint32_t> lpbl_block_word_offset_;
    std::vector<uint32_t> lpbl_block_mode_;
    std::vector<uint32_t> lpbl_block_arg_;
    std::vector<uint64_t> lpbl_payload_words_;
    std::vector<uint32_t> pilots_;
    uint32_t pre_count_ = 0;
    uint32_t edges_total_ = 0;
    uint32_t bucket_target_ = 0;
    uint32_t flags_ = 0;
    uint32_t seed_ = 0;
    uint32_t bucket_count_ = 0;
    uint32_t pilot_bits_ = 0;
    uint32_t version_ = 0;
    uint32_t rank_bits_ = 0;
    uint32_t ef_l_ = 0;
    uint32_t ef_select_step_ = 0;
    uint32_t bucket_size_bits_ = 0;
    uint32_t bucket_payload_bits_ = 0;
    uint32_t local_len_bits_ = 0;
    uint32_t block_span_ = 0;
    uint32_t perm_block_size_ = 0;
    uint32_t key_max_ = 0;
    uint32_t key_ef_l_ = 0;
    uint32_t key_ef_select_step_ = 0;
    uint32_t run_count_ = 0;
    uint32_t run_rank_bits_ = 0;
    uint32_t run_ef_l_ = 0;
    uint32_t run_ef_select_step_ = 0;
    uint32_t lpbl_block_size_ = 0;
    IndexLayout layout_ = IndexLayout::None;
};

}} // namespace SST::SnnDL
