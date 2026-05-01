// -*- c++ -*-
#include <sst/core/sst_config.h>
#include "MemKCalBench.h"
#include "MemKCalBenchConfig.h"

#include <sstream>
#include <algorithm>

using namespace SST;
using namespace SST::Interfaces;
using namespace SST::SnnDL;

MemKCalBench::MemKCalBench(ComponentId_t id, Params& params)
    : Component(id)
{
    const MemKCalBenchConfig cfg = parseMemKCalBenchConfig(params);
    out_ = new Output("MemKCalBench[@p:@l]: ", cfg.verbose, 0, Output::STDOUT);
    base_addr_  = cfg.base_addr;
    row_bytes_  = cfg.row_bytes;
    bank_bits_  = cfg.bank_bits;
    bank_shift_ = cfg.bank_shift;
    clock_      = cfg.clock;
    out_csv_    = cfg.output_csv;

    // Build tests
    for (auto L : cfg.payload_sizes) {
        for (uint32_t g = cfg.gap_start; g <= cfg.gap_end; g += cfg.gap_step) {
            if (cfg.do_row_hit)  tests_.push_back({"row_hit", L, g});
            if (cfg.do_row_switch)   tests_.push_back({"row_switch", L, g});
            if (cfg.gap_end - g < cfg.gap_step) break; // guard overflow
        }
    }

    // load StandardMem subcomponent
    mem_ = loadUserSubComponent<SST::Interfaces::StandardMem>(
        "memory", ComponentInfo::SHARE_PORTS,
        registerTimeBase("1ns"),
        new StandardMem::Handler2<MemKCalBench, &MemKCalBench::onResp_>(this));
    if (!mem_) {
        out_->fatal(CALL_INFO, -1, "MemKCalBench requires a StandardMem subcomponent in slot 'memory'\n");
    }

    // Primary component to end simulation when done
    registerAsPrimaryComponent();
    primaryComponentDoNotEndSim();
}

MemKCalBench::~MemKCalBench() {
    delete out_;
}

void MemKCalBench::init(unsigned int phase) {
    if (mem_) mem_->init(phase);
}

void MemKCalBench::setup() {
    if (mem_) mem_->setup();
    // Register clock
    registerClock(clock_, new Clock::Handler2<MemKCalBench, &MemKCalBench::clockTick>(this));
    inited_ = true;
}

void MemKCalBench::finish() {
    if (mem_) mem_->finish();
}

bool MemKCalBench::clockTick(Cycle_t) {
    if (!inited_) return false;
    if (phase_ == Phase::Idle) {
        if (test_idx_ >= tests_.size()) {
            out_->verbose(CALL_INFO, 1, 0, "All tests done; ending sim\n");
            primaryComponentOKToEndSim();
            return false;
        }
        // Start split for current test
        auto &t = tests_[test_idx_];
        uint64_t a0=0, a1=0; uint32_t L=t.L;
        if (t.scene == "row_hit") {
            // same bank,row; place A at col=0, B at col=L+gap
            a0 = makeAddr(/*bank*/0, /*row*/0, /*col*/0);
            a1 = makeAddr(/*bank*/0, /*row*/0, /*col*/L + t.gap);
        } else {
            // row_switch: second at next row, col=0
            a0 = makeAddr(0, 0, 0);
            a1 = makeAddr(0, 1, 0);
        }
        issueSplit_(a0, L, a1, L);
        phase_ = Phase::Split;
        return false;
    }
    return false;
}

void MemKCalBench::issueSplit_(uint64_t a0, uint32_t L, uint64_t a1, uint32_t L2) {
    pending_ = 2; t_split_ns_ = 0;
    start_ns_ = getCurrentSimTimeNano();
    auto* r0 = new StandardMem::Read(a0, L);
    auto* r1 = new StandardMem::Read(a1, L2);
    mem_->send(r0);
    mem_->send(r1);
}

void MemKCalBench::issueMerge_(uint64_t a0, uint32_t size) {
    pending_ = 1; start_ns_ = getCurrentSimTimeNano();
    auto* r = new StandardMem::Read(a0, size);
    mem_->send(r);
}

void MemKCalBench::onResp_(StandardMem::Request* req) {
    if (!req) return;
    if (auto* rr = dynamic_cast<StandardMem::ReadResp*>(req)) {
        if (pending_>0) pending_--;
        if (pending_==0) {
            uint64_t end_ns = getCurrentSimTimeNano();
            uint64_t dur = (end_ns >= start_ns_)? (end_ns - start_ns_) : 0;
            if (phase_ == Phase::Split) {
                t_split_ns_ = dur;
                // Now issue merge for same test
                auto &t = tests_[test_idx_];
                uint64_t base=0; uint32_t tot=0;
                if (t.scene == "row_hit") {
                    base = makeAddr(0, 0, 0);
                    tot  = t.L + t.gap + t.L;
                } else {
                    // Merge across rows: read two rows worth from col=0; minimal continuous cover
                    base = makeAddr(0, 0, 0);
                    tot  = t.L + t.gap + t.L;
                }
                issueMerge_(base, tot);
                phase_ = Phase::Merge;
            } else if (phase_ == Phase::Merge) {
                // write CSV, advance
                auto &t = tests_[test_idx_];
                writeCSV_(t.scene, t.L, t.gap, t_split_ns_, dur);
                test_idx_++;
                phase_ = Phase::Idle;
            }
        }
    }
    delete req;
}

void MemKCalBench::writeCSV_(const std::string& scene, uint32_t L, uint32_t gap, uint64_t t_split_ns, uint64_t t_merge_ns) {
    // append mode
    bool write_header = false;
    if (!csv_header_written_) {
        // test open to decide header only once per component
        write_header = true;
        csv_header_written_ = true;
    }
    std::ofstream f(out_csv_, std::ios::app);
    if (!f.good()) return;
    if (write_header) f << "scene,L,gap,split_ns,merge_ns\n";
    f << scene << "," << L << "," << gap << "," << t_split_ns << "," << t_merge_ns << "\n";
}
