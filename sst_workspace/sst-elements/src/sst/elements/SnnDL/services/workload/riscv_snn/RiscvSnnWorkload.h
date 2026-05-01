// -*- c++ -*-
//
// RiscvSnnWorkload:
// - `workload_impl=riscv_snn` 的最小 skeleton。
// - 当前只搭好控制面骨架与 shared backend 接口，不在这一版承诺完整 ISA 执行。
//

#pragma once

#include <cstdint>
#include <map>
#include <memory>
#include <string>

#include "api/ICoreWorkload.h"
#include "workload/common/SnnAccelBackend.h"
#include "workload/riscv_snn/RiscvSnnBootDriver.h"
#include "workload/riscv_snn/RiscvSnnHart.h"
#include "workload/riscv_snn/RiscvSnnIss.h"
#include "workload/riscv_snn/RiscvSnnQueueContract.h"

namespace SST { namespace SnnDL {

class RiscvSnnWorkload final : public ICoreWorkload {
public:
    RiscvSnnWorkload();
    ~RiscvSnnWorkload() override = default;

    void configureFromParams(const SST::Params& params) override;
    void bindRuntime(const Runtime& rt) override;

    bool onClockTick(uint64_t now_cycle) override;
    bool deliverPacket(NocPacketEvent* packet) override;

    bool hasWork() const override;
    double getUtilization() const override;
    void getStatistics(std::map<std::string, uint64_t>& stats) const override;

private:
    void syncQueueCsrs_();
    void syncStatusCsr_();
    bool configureFirmwareControlPlane_();
    bool tickFirmware_();
    bool drainFirmwareFaultAcks_();
    bool drainFirmwareSubmittedCommands_();
    bool drainFirmwareCompletionAcks_();
    bool submitVisibleCommands_();
    bool drainBackendCompletions_();
    bool tickBootDriver_();

    Runtime rt_{};
    std::unique_ptr<SnnAccelBackend> backend_;
    RiscvSnnHart hart_;
    RiscvSnnIss iss_;
    riscv_snn::RiscvSnnQueueContract queues_;
    RiscvSnnBootDriver boot_driver_;

    std::string hart_isa_ = "rv64im_zicsr";
    std::string backend_name_ = "null";
    std::string firmware_elf_;
    uint64_t boot_addr_ = 0;
    uint64_t local_mem_bytes_ = 64 * 1024;
    uint32_t cmd_queue_entries_ = 64;
    uint32_t cmp_queue_entries_ = 64;
    uint32_t rx_debug_queue_entries_ = 16;
    uint32_t firmware_issue_budget_per_tick_ = 8;
    uint64_t cmd_queue_base_ = 0;
    uint64_t cmp_queue_base_ = 0;
    uint64_t rx_debug_queue_base_ = 0;
    uint64_t last_tick_cycle_ = 0;
    uint64_t active_cycles_ = 0;
    uint64_t firmware_retired_instructions_ = 0;
    uint64_t firmware_started_count_ = 0;
    uint64_t submitted_commands_ = 0;
    uint64_t accepted_commands_ = 0;
    uint64_t completion_visible_count_ = 0;
    uint64_t completion_consumed_count_ = 0;
    uint64_t fused_step_completion_count_ = 0;
    uint64_t fault_count_ = 0;
    uint64_t last_fault_csr_ = 0;
    uint32_t last_completion_status_ = 0;
    bool firmware_loaded_ = false;
    uint64_t firmware_loaded_bytes_ = 0;
    uint64_t next_bootstrap_token_ = 1;
};

}} // namespace SST::SnnDL
