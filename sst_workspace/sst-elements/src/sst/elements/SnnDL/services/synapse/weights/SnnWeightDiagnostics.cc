#include "synapse/weights/SnnWeightDiagnostics.h"

#include <fstream>
#include <vector>

#include "synapse/weights/SnnBcsrWeightManager.h"

namespace SST { namespace SnnDL {

float SnnWeightDiagnostics::readBcsrWeightFromFile(uint32_t post_local, uint32_t pre_global,
                                                   uint32_t br, uint32_t bc,
                                                   const BcsrWeightManager& weights_mgr,
                                                   const std::function<std::string(uint32_t,uint32_t)>& tmpl_resolver,
                                                   const ParseMetaFn& parse_meta) {
    uint32_t block_row = br ? (post_local / br) : 0;
    uint32_t intra_row = br ? (post_local % br) : 0;
    uint32_t blk_col = bc ? (pre_global / bc) : 0;
    uint32_t intra_col = bc ? (pre_global % bc) : 0;
    float resolved = 0.0f;
    do {
        const auto& rowptr = weights_mgr.rowptrHost();
        if (block_row + 1 > rowptr.size()) break;
        uint32_t start = rowptr[block_row];
        uint32_t end   = (block_row + 1 < rowptr.size() ? rowptr[block_row+1] : start);
        if (end <= start) break;
        if (!tmpl_resolver) break;
        std::string bin_path = tmpl_resolver(0 /*node*/, 0 /*core*/); // caller binds node/core
        if (bin_path.empty()) break;
        uint32_t rows=0, colsN=0, brM=0, bcM=0, idxB=0, valB=0, totalB=0;
        uint64_t rp_off=0, ci_off=0, bd_off=0, id_off=0;
        std::string meta_path = bin_path + ".meta.json";
        if (!parse_meta || !parse_meta(meta_path, rows, colsN, brM, bcM, idxB, valB, rp_off, ci_off, bd_off, id_off, totalB)) break;
        std::ifstream fin(bin_path, std::ios::binary);
        if (!fin.good()) break;
        int idx_in_row = -1;
        for (uint32_t j = 0; j < (end - start); ++j) {
            fin.seekg(static_cast<std::streamoff>(ci_off + (size_t)(start + j) * idxB), std::ios::beg);
            uint32_t colv = 0;
            if (idxB == 2) { uint16_t v=0; fin.read(reinterpret_cast<char*>(&v), 2); colv = v; }
            else { fin.read(reinterpret_cast<char*>(&colv), 4); }
            if (!fin.good()) break;
            if (colv == blk_col) { idx_in_row = (int)j; break; }
        }
        if (idx_in_row < 0) break;
        size_t blk_bytes = (size_t)(brM?brM:br) * (size_t)(bcM?bcM:bc) * (size_t)valB;
        fin.seekg(static_cast<std::streamoff>(bd_off + (uint64_t)(start + (uint32_t)idx_in_row) * blk_bytes), std::ios::beg);
        std::vector<float> blk((brM?brM:br) * (bcM?bcM:bc), 0.0f);
        if (valB == 4) fin.read(reinterpret_cast<char*>(blk.data()), blk_bytes);
        if (!fin.good()) break;
        uint32_t off = intra_row * (bcM?bcM:bc) + intra_col;
        if (off < blk.size()) resolved = blk[off];
    } while (0);
    return resolved;
}

} } // namespace SST::SnnDL
