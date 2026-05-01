#include "SnnBcsrWeightManager.h"

#include <algorithm>
#include <cctype>
#include <cstring>
#include <utility>

using namespace SST::SnnDL;

// NOTE(Universal-core experiments):
// We globally disable all BCSR *optimizations* (rowIndex cache, block cache, etc.).
// BCSR remains as a storage format/addressing scheme only.
// This avoids accidentally mixing BCSR-level optimizations into GAS experiments.
static constexpr bool kEnableBcsrOptimizations = false;

void BcsrWeightManager::configure(uint64_t rowptr_addr,
                                  uint64_t colidx_addr,
                                  uint64_t blockdata_addr,
                                  uint64_t blockids_addr,
                                  uint32_t block_rows,
                                  uint32_t block_cols,
                                  uint32_t idx_bytes,
                                  uint32_t val_bytes,
                                  const std::string& layout_mode,
                                  uint32_t colidx_row_stride_bytes,
                                  uint32_t blockdata_row_stride_bytes,
                                  uint32_t blockids_row_stride_bytes) {
    rowptr_addr_ = rowptr_addr;
    colidx_addr_ = colidx_addr;
    blockdata_addr_ = blockdata_addr;
    blockids_addr_ = blockids_addr;
    block_rows_ = block_rows;
    block_cols_ = block_cols;
    idx_bytes_ = idx_bytes;
    val_bytes_ = val_bytes;
    layout_mode_ = LayoutMode::Flat;
    colidx_row_stride_bytes_ = colidx_row_stride_bytes;
    blockdata_row_stride_bytes_ = blockdata_row_stride_bytes;
    blockids_row_stride_bytes_ = blockids_row_stride_bytes;

    std::string mode = layout_mode;
    std::transform(mode.begin(), mode.end(), mode.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    if (mode == "rowpack_v1") {
        const uint32_t idxB = effectiveIdxBytes();
        const uint32_t blkRowB = static_cast<uint32_t>(blockRowBytes());
        const bool valid_rowpack =
            (colidx_row_stride_bytes_ >= idxB) &&
            (blockdata_row_stride_bytes_ >= blkRowB);
        if (valid_rowpack) layout_mode_ = LayoutMode::RowpackV1;
    }

    rowptr_ready_ = false;
    rowptr_read_pending_ = false;
    bcsr_rowptr_host_.clear();
    resetCaches();
}

void BcsrWeightManager::setRowIndexCacheCapacity(uint32_t cap) {
    (void)cap;
    // Global hard-disable to prevent experiments from accidentally enabling cache effects.
    row_index_cache_cap_ = kEnableBcsrOptimizations ? cap : 0;
    row_index_cache_.clear();
}

void BcsrWeightManager::setBlockCacheCapacity(uint32_t cap) {
    (void)cap;
    // Global hard-disable to prevent experiments from accidentally enabling cache effects.
    block_cache_cap_ = kEnableBcsrOptimizations ? cap : 0;
    block_cache_order_.clear();
    block_cache_.clear();
}

void BcsrWeightManager::setBlockCachePolicy(BlockCachePolicy policy) {
    if (block_cache_policy_ == policy) return;
    block_cache_policy_ = policy;
    resetCaches();
}

void BcsrWeightManager::resetCaches() {
    row_index_cache_.clear();
    block_cache_order_.clear();
    block_cache_.clear();
}

size_t BcsrWeightManager::expectedRowptrEntries(uint32_t num_neurons) const {
    uint32_t br = (block_rows_ > 0 ? block_rows_ : 16);
    uint32_t nBlockRows = (num_neurons + br - 1) / br;
    return static_cast<size_t>(nBlockRows + 1);
}

size_t BcsrWeightManager::expectedRowptrBytes(uint32_t num_neurons) const {
    return expectedRowptrEntries(num_neurons) * sizeof(uint32_t);
}

uint32_t BcsrWeightManager::effectiveBlockRows() const {
    return block_rows_ ? block_rows_ : 16;
}

uint32_t BcsrWeightManager::effectiveBlockCols() const {
    return block_cols_ ? block_cols_ : 16;
}

uint32_t BcsrWeightManager::effectiveIdxBytes() const {
    return idx_bytes_ ? idx_bytes_ : 2;
}

uint32_t BcsrWeightManager::effectiveValBytes() const {
    return val_bytes_ ? val_bytes_ : 4;
}

size_t BcsrWeightManager::blockBytes() const {
    return static_cast<size_t>(effectiveBlockRows()) *
           static_cast<size_t>(effectiveBlockCols()) *
           static_cast<size_t>(effectiveValBytes());
}

size_t BcsrWeightManager::blockRowBytes() const {
    return static_cast<size_t>(effectiveBlockCols()) *
           static_cast<size_t>(effectiveValBytes());
}

uint64_t BcsrWeightManager::blockDataAddrByRow(uint32_t block_row, uint32_t idx_in_row) const {
    if (usesRowpackLayout()) {
        return blockdata_addr_ +
               static_cast<uint64_t>(block_row) * static_cast<uint64_t>(blockdata_row_stride_bytes_) +
               static_cast<uint64_t>(idx_in_row) * static_cast<uint64_t>(blockBytes());
    }
    uint32_t start = 0;
    uint32_t end = 0;
    if (!rowBounds(block_row, start, end)) return blockdata_addr_;
    return blockdata_addr_ +
           static_cast<uint64_t>(start + idx_in_row) * static_cast<uint64_t>(blockBytes());
}

uint64_t BcsrWeightManager::blockDataAddr(uint32_t global_block_index) const {
    if (!usesRowpackLayout()) {
        return blockdata_addr_ + static_cast<uint64_t>(global_block_index) * blockBytes();
    }
    uint32_t block_row = 0;
    uint32_t idx_in_row = 0;
    if (!decodeGlobalBlockIndex(global_block_index, block_row, idx_in_row)) {
        return blockdata_addr_ + static_cast<uint64_t>(global_block_index) * blockBytes();
    }
    return blockDataAddrByRow(block_row, idx_in_row);
}

uint64_t BcsrWeightManager::colIndexAddrByRow(uint32_t block_row, uint32_t idx_in_row) const {
    if (usesRowpackLayout()) {
        return colidx_addr_ +
               static_cast<uint64_t>(block_row) * static_cast<uint64_t>(colidx_row_stride_bytes_) +
               static_cast<uint64_t>(idx_in_row) * static_cast<uint64_t>(effectiveIdxBytes());
    }
    uint32_t start = 0;
    uint32_t end = 0;
    if (!rowBounds(block_row, start, end)) return colidx_addr_;
    return colidx_addr_ +
           static_cast<uint64_t>(start + idx_in_row) * static_cast<uint64_t>(effectiveIdxBytes());
}

uint64_t BcsrWeightManager::colIndexAddr(uint32_t start_index) const {
    if (!usesRowpackLayout()) {
        return colidx_addr_ + static_cast<uint64_t>(start_index) * effectiveIdxBytes();
    }
    uint32_t block_row = 0;
    uint32_t idx_in_row = 0;
    if (!decodeGlobalBlockIndex(start_index, block_row, idx_in_row)) {
        // row start_index normally lands exactly on rowptr[block_row]. Fallback to flat if unavailable.
        return colidx_addr_ + static_cast<uint64_t>(start_index) * effectiveIdxBytes();
    }
    return colIndexAddrByRow(block_row, idx_in_row);
}

size_t BcsrWeightManager::colIndexBytes(uint32_t block_count) const {
    return static_cast<size_t>(block_count) * effectiveIdxBytes();
}

bool BcsrWeightManager::rowBounds(uint32_t block_row, uint32_t& start, uint32_t& end) const {
    if (block_row + 1 >= bcsr_rowptr_host_.size()) return false;
    start = bcsr_rowptr_host_[block_row];
    end = bcsr_rowptr_host_[block_row + 1];
    return true;
}

bool BcsrWeightManager::decodeGlobalBlockIndex(uint32_t global_block_index,
                                               uint32_t& block_row,
                                               uint32_t& idx_in_row) const {
    if (bcsr_rowptr_host_.size() < 2) return false;
    auto it = std::upper_bound(
        bcsr_rowptr_host_.begin(),
        bcsr_rowptr_host_.end(),
        global_block_index);
    if (it == bcsr_rowptr_host_.begin()) return false;
    const size_t row = static_cast<size_t>((it - bcsr_rowptr_host_.begin()) - 1);
    if (row + 1 >= bcsr_rowptr_host_.size()) return false;
    const uint32_t start = bcsr_rowptr_host_[row];
    const uint32_t end = bcsr_rowptr_host_[row + 1];
    if (global_block_index < start || global_block_index >= end) return false;
    block_row = static_cast<uint32_t>(row);
    idx_in_row = global_block_index - start;
    return true;
}

bool BcsrWeightManager::installRowptrFromBytes(const uint8_t* data, size_t bytes, uint32_t num_neurons) {
    if (!data) return false;
    const size_t expect = expectedRowptrBytes(num_neurons);
    if (bytes != expect) return false;
    bcsr_rowptr_host_.resize(expectedRowptrEntries(num_neurons));
    std::memcpy(bcsr_rowptr_host_.data(), data, bytes);
    // Require non-decreasing sequence and at least one non-zero delta
    bool non_decreasing = true;
    bool has_progress = false;
    for (size_t idx = 0; idx + 1 < bcsr_rowptr_host_.size(); ++idx) {
        uint32_t cur = bcsr_rowptr_host_[idx];
        uint32_t nxt = bcsr_rowptr_host_[idx + 1];
        if (nxt < cur) { non_decreasing = false; break; }
        if (nxt > cur) has_progress = true;
    }
    if (!non_decreasing || !has_progress) {
        bcsr_rowptr_host_.clear();
        return false;
    }
    rowptr_ready_ = true;
    rowptr_read_pending_ = false;
    return true;
}

bool BcsrWeightManager::rowIndexGet(uint32_t block_row, std::vector<uint32_t>& out) const {
    if (!kEnableBcsrOptimizations) return false;
    auto it = row_index_cache_.find(block_row);
    if (it == row_index_cache_.end()) return false;
    out = it->second;
    return true;
}

void BcsrWeightManager::rowIndexPut(uint32_t block_row, std::vector<uint32_t>&& cols) {
    if (!kEnableBcsrOptimizations) return;
    if (row_index_cache_cap_ == 0) return;
    evictRowIndexIfNeeded(block_row);
    row_index_cache_[block_row] = std::move(cols);
}

bool BcsrWeightManager::blockGet(uint32_t block_row, uint32_t block_col, std::vector<float>& out) {
    if (!kEnableBcsrOptimizations) return false;
    const uint64_t key = makeBlockKey(block_row, block_col);
    auto it = block_cache_.find(key);
    if (it == block_cache_.end()) return false;
    out = it->second.data;
    if (block_cache_policy_ == BlockCachePolicy::LRU) {
        // LRU: bump to MRU on hit.
        block_cache_order_.splice(block_cache_order_.begin(), block_cache_order_, it->second.it);
        it->second.it = block_cache_order_.begin();
    }
    return true;
}

void BcsrWeightManager::blockPut(uint32_t block_row, uint32_t block_col, std::vector<float>&& data) {
    if (!kEnableBcsrOptimizations) return;
    if (block_cache_cap_ == 0) return;
    const uint64_t key = makeBlockKey(block_row, block_col);
    auto it = block_cache_.find(key);
    if (it != block_cache_.end()) {
        it->second.data = std::move(data);
        if (block_cache_policy_ == BlockCachePolicy::LRU) {
            block_cache_order_.splice(block_cache_order_.begin(), block_cache_order_, it->second.it);
            it->second.it = block_cache_order_.begin();
        }
        return;
    }

    if (block_cache_cap_ > 0 && block_cache_.size() >= block_cache_cap_) {
        const bool evict_front =
            (block_cache_policy_ == BlockCachePolicy::FIFO) ||
            (block_cache_policy_ == BlockCachePolicy::LegacyUnordered);
        if (!block_cache_order_.empty()) {
            const uint64_t victim = evict_front ? block_cache_order_.front() : block_cache_order_.back();
            if (evict_front) block_cache_order_.pop_front();
            else block_cache_order_.pop_back();
            block_cache_.erase(victim);
        }
    }

    std::list<uint64_t>::iterator order_it;
    if (block_cache_policy_ == BlockCachePolicy::LRU) {
        block_cache_order_.push_front(key);
        order_it = block_cache_order_.begin();
    } else {
        block_cache_order_.push_back(key);
        order_it = std::prev(block_cache_order_.end());
    }
    BlockCacheEntry entry;
    entry.data = std::move(data);
    entry.it = order_it;
    block_cache_.emplace(key, std::move(entry));
}

bool BcsrWeightManager::hasBlock(uint32_t block_row, uint32_t block_col) const {
    if (!kEnableBcsrOptimizations) return false;
    const uint64_t key = makeBlockKey(block_row, block_col);
    return block_cache_.find(key) != block_cache_.end();
}

uint64_t BcsrWeightManager::makeBlockKey(uint32_t block_row, uint32_t block_col) {
    return (static_cast<uint64_t>(block_row) << 32) | block_col;
}

void BcsrWeightManager::evictRowIndexIfNeeded(uint32_t incoming_key) {
    if (row_index_cache_cap_ == 0) return;
    if (row_index_cache_.size() < row_index_cache_cap_) return;
    if (row_index_cache_.find(incoming_key) != row_index_cache_.end()) return;
    row_index_cache_.erase(row_index_cache_.begin());
}
