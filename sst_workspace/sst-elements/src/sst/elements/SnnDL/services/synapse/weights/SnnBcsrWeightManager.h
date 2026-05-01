#ifndef SST_ELEMENTS_SNNDL_SNNBCSRWEIGHTMANAGER_H
#define SST_ELEMENTS_SNNDL_SNNBCSRWEIGHTMANAGER_H

#include <cstddef>
#include <cstdint>
#include <list>
#include <string>
#include <unordered_map>
#include <vector>

namespace SST {
namespace SnnDL {

class BcsrWeightManager {
public:
    enum class BlockCachePolicy : uint8_t { LegacyUnordered = 0, FIFO = 1, LRU = 2 };
    enum class LayoutMode : uint8_t { Flat = 0, RowpackV1 = 1 };

    BcsrWeightManager() = default;

    void configure(uint64_t rowptr_addr,
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
                   uint32_t blockids_row_stride_bytes);

    void setRowIndexCacheCapacity(uint32_t cap);
    void setBlockCacheCapacity(uint32_t cap);
    void setBlockCachePolicy(BlockCachePolicy policy);
    BlockCachePolicy blockCachePolicy() const { return block_cache_policy_; }
    uint32_t rowIndexCacheCapacity() const { return row_index_cache_cap_; }
    uint32_t blockCacheCapacity() const { return block_cache_cap_; }

    void resetCaches();

    uint64_t rowptrAddr() const { return rowptr_addr_; }
    void setRowptrAddr(uint64_t addr) { rowptr_addr_ = addr; }
    uint64_t colidxAddr() const { return colidx_addr_; }
    uint64_t blockdataAddr() const { return blockdata_addr_; }
    uint64_t blockidsAddr() const { return blockids_addr_; }
    uint32_t blockRows() const { return block_rows_; }
    uint32_t blockCols() const { return block_cols_; }
    uint32_t idxBytes() const { return idx_bytes_; }
    uint32_t valBytes() const { return val_bytes_; }
    uint32_t effectiveBlockRows() const;
    uint32_t effectiveBlockCols() const;
    uint32_t effectiveIdxBytes() const;
    uint32_t effectiveValBytes() const;
    LayoutMode layoutMode() const { return layout_mode_; }
    bool usesRowpackLayout() const { return layout_mode_ == LayoutMode::RowpackV1; }
    size_t blockBytes() const;
    size_t blockRowBytes() const;
    uint64_t blockDataAddr(uint32_t global_block_index) const;
    uint64_t blockDataAddrByRow(uint32_t block_row, uint32_t idx_in_row) const;
    uint64_t colIndexAddr(uint32_t start_index) const;
    uint64_t colIndexAddrByRow(uint32_t block_row, uint32_t idx_in_row) const;
    size_t colIndexBytes(uint32_t block_count) const;
    bool rowBounds(uint32_t block_row, uint32_t& start, uint32_t& end) const;

    bool isRowptrReady() const { return rowptr_ready_; }
    void setRowptrReady(bool ready) { rowptr_ready_ = ready; }
    bool isRowptrReadPending() const { return rowptr_read_pending_; }
    void setRowptrReadPending(bool pending) { rowptr_read_pending_ = pending; }

    std::vector<uint32_t>& rowptrHost() { return bcsr_rowptr_host_; }
    const std::vector<uint32_t>& rowptrHost() const { return bcsr_rowptr_host_; }

    bool rowIndexGet(uint32_t block_row, std::vector<uint32_t>& out) const;
    void rowIndexPut(uint32_t block_row, std::vector<uint32_t>&& cols);
    bool blockGet(uint32_t block_row, uint32_t block_col, std::vector<float>& out);
    void blockPut(uint32_t block_row, uint32_t block_col, std::vector<float>&& data);
    bool hasBlock(uint32_t block_row, uint32_t block_col) const;

    size_t expectedRowptrEntries(uint32_t num_neurons) const;
    size_t expectedRowptrBytes(uint32_t num_neurons) const;
    bool installRowptrFromBytes(const uint8_t* data, size_t bytes, uint32_t num_neurons);

private:
    static uint64_t makeBlockKey(uint32_t block_row, uint32_t block_col);
    bool decodeGlobalBlockIndex(uint32_t global_block_index, uint32_t& block_row, uint32_t& idx_in_row) const;
    void evictRowIndexIfNeeded(uint32_t incoming_key);

    uint64_t rowptr_addr_ = 0;
    uint64_t colidx_addr_ = 0;
    uint64_t blockdata_addr_ = 0;
    uint64_t blockids_addr_ = 0;
    uint32_t block_rows_ = 16;
    uint32_t block_cols_ = 16;
    uint32_t idx_bytes_ = 2;
    uint32_t val_bytes_ = 4;
    LayoutMode layout_mode_ = LayoutMode::Flat;
    uint32_t colidx_row_stride_bytes_ = 0;
    uint32_t blockdata_row_stride_bytes_ = 0;
    uint32_t blockids_row_stride_bytes_ = 0;

    std::vector<uint32_t> bcsr_rowptr_host_;
    bool rowptr_ready_ = false;
    bool rowptr_read_pending_ = false;

    uint32_t row_index_cache_cap_ = 64;
    uint32_t block_cache_cap_ = 256;
    std::unordered_map<uint32_t, std::vector<uint32_t>> row_index_cache_;
    BlockCachePolicy block_cache_policy_ = BlockCachePolicy::LRU;
    struct BlockCacheEntry {
        std::vector<float> data;
        std::list<uint64_t>::iterator it;
    };
    std::list<uint64_t> block_cache_order_;
    std::unordered_map<uint64_t, BlockCacheEntry> block_cache_;
};

} // namespace SnnDL
} // namespace SST

#endif // SST_ELEMENTS_SNNDL_SNNBCSRWEIGHTMANAGER_H
