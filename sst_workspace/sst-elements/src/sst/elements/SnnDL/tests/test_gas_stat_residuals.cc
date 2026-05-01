#include <cassert>
#include <string>

#include "api/IGasStageSink.h"
#include "services/synapse/gas/GasCustomCmd.h"

using SST::SnnDL::GasStatData;
using SST::SnnDL::GasStatEvent;
using SST::SnnDL::toGasStatEvent;

namespace {

void test_gas_stat_event_carries_apply_backlog_residuals_and_peaks() {
    GasStatData data(7u, 0u, 0u);
    data.apply_backlog_granules_residual = 57u;
    data.apply_backlog_pending_up_reads_residual = 64u;
    data.apply_backlog_inflight_residual = 51u;
    data.apply_backlog_granules_peak_after_due = 23u;
    data.apply_backlog_pending_up_reads_peak_after_due = 29u;
    data.apply_backlog_inflight_peak_after_due = 31u;

    const GasStatEvent event = toGasStatEvent(data);

    assert(event.superstep == 7u);
    assert(event.apply_backlog_granules_residual == 57u);
    assert(event.apply_backlog_pending_up_reads_residual == 64u);
    assert(event.apply_backlog_inflight_residual == 51u);
    assert(event.apply_backlog_granules_peak_after_due == 23u);
    assert(event.apply_backlog_pending_up_reads_peak_after_due == 29u);
    assert(event.apply_backlog_inflight_peak_after_due == 31u);
}

void test_gas_stat_debug_string_mentions_apply_backlog_residuals_and_peaks() {
    GasStatData data(9u, 0u, 0u);
    data.apply_backlog_granules_residual = 3u;
    data.apply_backlog_pending_up_reads_residual = 4u;
    data.apply_backlog_inflight_residual = 5u;
    data.apply_backlog_granules_peak_after_due = 6u;
    data.apply_backlog_pending_up_reads_peak_after_due = 7u;
    data.apply_backlog_inflight_peak_after_due = 8u;

    const std::string dump = data.getString();

    assert(dump.find("apply_backlog_granules_residual=3") != std::string::npos);
    assert(dump.find("apply_backlog_pending_up_reads_residual=4") != std::string::npos);
    assert(dump.find("apply_backlog_inflight_residual=5") != std::string::npos);
    assert(dump.find("apply_backlog_granules_peak_after_due=6") != std::string::npos);
    assert(dump.find("apply_backlog_pending_up_reads_peak_after_due=7") != std::string::npos);
    assert(dump.find("apply_backlog_inflight_peak_after_due=8") != std::string::npos);
}

} // namespace

int main(int argc, char** argv) {
    (void)argc;
    (void)argv;
    test_gas_stat_event_carries_apply_backlog_residuals_and_peaks();
    test_gas_stat_debug_string_mentions_apply_backlog_residuals_and_peaks();
    return 0;
}
