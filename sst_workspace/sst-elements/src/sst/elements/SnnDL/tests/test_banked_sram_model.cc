#include <cassert>
#include <cstdint>

#include "services/memory/sram_sim/model/BankedSramModel.h"

using SST::SnnDL::BankedSramConfig;
using SST::SnnDL::BankedSramModel;

static void test_conflict_exports_extra_cycles() {
    BankedSramConfig cfg{};
    cfg.enable = true;
    cfg.banks = 1;
    cfg.ports_per_bank = 1;
    cfg.bank_interleave_bytes = 4;
    cfg.t_read_cycles = 2;

    BankedSramModel model(cfg);
    model.noteRead(10, 0x0, 4);
    model.noteRead(10, 0x4, 4);
    model.onClockTick(11);

    const uint64_t extra = model.consumeLastCyclePredictedExtraCycles();
    assert(extra == 2);
    assert(model.consumeLastCyclePredictedExtraCycles() == 0);
}

static void test_no_conflict_exports_zero_cycles() {
    BankedSramConfig cfg{};
    cfg.enable = true;
    cfg.banks = 2;
    cfg.ports_per_bank = 1;
    cfg.bank_interleave_bytes = 4;
    cfg.t_read_cycles = 3;

    BankedSramModel model(cfg);
    model.noteRead(20, 0x0, 4);
    model.noteRead(20, 0x4, 4);
    model.onClockTick(21);

    assert(model.consumeLastCyclePredictedExtraCycles() == 0);
}

static void test_warp_max_conflict_cost_model_uses_max_over_banks() {
    BankedSramConfig cfg{};
    cfg.enable = true;
    cfg.banks = 2;
    cfg.ports_per_bank = 1;
    cfg.bank_interleave_bytes = 4;
    cfg.t_read_cycles = 1;
    cfg.conflict_cost_model = "max";

    BankedSramModel model(cfg);
    // bank0: 3 reads
    model.noteRead(30, 0x0, 4);
    model.noteRead(30, 0x8, 4);
    model.noteRead(30, 0x10, 4);
    // bank1: 3 reads
    model.noteRead(30, 0x4, 4);
    model.noteRead(30, 0xC, 4);
    model.noteRead(30, 0x14, 4);
    model.onClockTick(31);

    // GPU shared-memory warp cost: extra = (max_bank_accesses - 1)
    assert(model.consumeLastCyclePredictedExtraCycles() == 2);
}

static void test_default_sum_conflict_cost_model_adds_over_banks() {
    BankedSramConfig cfg{};
    cfg.enable = true;
    cfg.banks = 2;
    cfg.ports_per_bank = 1;
    cfg.bank_interleave_bytes = 4;
    cfg.t_read_cycles = 1;
    cfg.conflict_cost_model = "sum";

    BankedSramModel model(cfg);
    // Same pattern as warp_max test: both banks have conflicts.
    model.noteRead(40, 0x0, 4);
    model.noteRead(40, 0x8, 4);
    model.noteRead(40, 0x10, 4);
    model.noteRead(40, 0x4, 4);
    model.noteRead(40, 0xC, 4);
    model.noteRead(40, 0x14, 4);
    model.onClockTick(41);

    // Sum-over-banks: extra = (3-1) + (3-1) = 4
    assert(model.consumeLastCyclePredictedExtraCycles() == 4);
}

static void test_gpu_read_broadcast_elides_conflict() {
    BankedSramConfig cfg{};
    cfg.enable = true;
    cfg.banks = 1;
    cfg.ports_per_bank = 1;
    cfg.bank_interleave_bytes = 4;
    cfg.t_read_cycles = 1;
    cfg.conflict_cost_model = "max";
    cfg.read_broadcast_enable = true;

    BankedSramModel model(cfg);
    model.noteRead(50, 0x0, 4);
    model.noteRead(50, 0x0, 4);
    model.noteRead(50, 0x0, 4);
    model.onClockTick(51);

    assert(model.consumeLastCyclePredictedExtraCycles() == 0);
    assert(model.stats().reads_total == 1);
    assert(model.stats().read_broadcast_elided_total == 2);
}

int main() {
    test_conflict_exports_extra_cycles();
    test_no_conflict_exports_zero_cycles();
    test_warp_max_conflict_cost_model_uses_max_over_banks();
    test_default_sum_conflict_cost_model_adds_over_banks();
    test_gpu_read_broadcast_elides_conflict();
    return 0;
}
