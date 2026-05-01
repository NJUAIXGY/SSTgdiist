// -*- c++ -*-
#ifndef SNNDL_MEM_KCAL_BENCH_H
#define SNNDL_MEM_KCAL_BENCH_H

#include <sst/core/component.h>
#include <sst/core/output.h>
#include <sst/core/interfaces/stdMem.h>
#include <vector>
#include <string>
#include <fstream>

namespace SST { namespace SnnDL {

class MemKCalBench : public SST::Component {
public:
    SST_ELI_REGISTER_COMPONENT(
        MemKCalBench,
        "SnnDL",
        "MemKCalBench",
        SST_ELI_ELEMENT_VERSION(1,0,0),
        "Micro-benchmark for k (gap merge threshold) calibration",
        COMPONENT_CATEGORY_UNCATEGORIZED
    )

    SST_ELI_DOCUMENT_PARAMS(
        {"verbose", "verbosity", "0"},
        {"base_addr", "base address offset for generated requests", "0"},
        {"row_bytes", "row byte size guess (bytes)", "8192"},
        {"bank_bits", "Number of bits in bank field (0=disabled)", "0"},
        {"bank_shift", "LSB bit index of bank field", "0"},
        {"payload_sizes", "Comma-separated payload sizes (bytes)", "4096,8192,16384,32768"},
        {"gap_start", "gap start (bytes)", "0"},
        {"gap_end", "gap end inclusive (bytes)", "65536"},
        {"gap_step", "gap step (bytes)", "512"},
        {"scenes", "row_hit,row_switch (comma separated)", "row_hit,row_switch"},
        {"clock", "bench clock", "1GHz"},
        {"output_csv", "output CSV path (append)", "sst_dram_si/stats/kcal/bench_results.csv"}
    )

    SST_ELI_DOCUMENT_SUBCOMPONENT_SLOTS(
        {"memory", "StandardMem interface", "SST::Interfaces::StandardMem"}
    )

    MemKCalBench(SST::ComponentId_t id, SST::Params& params);
    ~MemKCalBench() override;

    void init(unsigned int phase) override;
    void setup() override;
    void finish() override;

private:
    // clock
    bool clockTick(SST::Cycle_t);

    // helpers
    inline uint64_t rowIndex(uint64_t addr) const { return row_bytes_? (addr / row_bytes_) : 0; }
    inline uint64_t bankIndex(uint64_t addr) const { return bank_bits_ ? ((addr >> bank_shift_) & ((1ull<<bank_bits_)-1)) : 0; }
    inline uint64_t makeAddr(uint32_t bank, uint32_t row, uint32_t col) const {
        uint64_t a = base_addr_ + (uint64_t)row * (uint64_t)row_bytes_ + (uint64_t)col;
        if (bank_bits_) {
            uint64_t mask = ((1ull<<bank_bits_)-1ull);
            a &= ~(mask << bank_shift_);
            a |= ((uint64_t)bank & mask) << bank_shift_;
        }
        return a;
    }

    void issueSplit_(uint64_t a0, uint32_t L, uint64_t a1, uint32_t L2);
    void issueMerge_(uint64_t a0, uint32_t size);
    void onResp_(SST::Interfaces::StandardMem::Request* req);
    void writeCSV_(const std::string& scene, uint32_t L, uint32_t gap, uint64_t t_split_ns, uint64_t t_merge_ns);

    struct Test { std::string scene; uint32_t L; uint32_t gap; };
    std::vector<Test> tests_;
    size_t test_idx_ = 0;
    enum class Phase { Idle=0, Split, Merge };
    Phase phase_ = Phase::Idle;

    // measurement
    uint64_t start_ns_ = 0;
    uint32_t pending_ = 0;
    uint64_t t_split_ns_ = 0;

    // params
    SST::Output* out_ = nullptr;
    SST::Interfaces::StandardMem* mem_ = nullptr;
    std::string clock_ = "1GHz";
    std::string out_csv_;
    uint64_t base_addr_ = 0;
    uint32_t row_bytes_ = 8192;
    uint32_t bank_bits_ = 0;
    uint32_t bank_shift_ = 0;
    bool csv_header_written_ = false;
    bool inited_ = false;
};

}} // namespace

#endif
