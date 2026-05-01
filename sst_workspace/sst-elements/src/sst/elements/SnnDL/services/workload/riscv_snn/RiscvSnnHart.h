// -*- c++ -*-
//
// RiscvSnnHart:
// - `riscv_snn` 的最小 hart 状态骨架。
// - 先提供 PC/GPR/CSR/pending-event/wfi 等基础状态，后续再接完整解释器或 ISS。
//

#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <map>
#include <string>
#include <vector>

#include "workload/riscv_snn/RiscvSnnMemoryImage.h"

namespace SST { namespace SnnDL {

class RiscvSnnHart {
public:
    void reset(uint64_t boot_pc = 0);

    void setPc(uint64_t pc);
    uint64_t pc() const { return pc_; }

    void setGpr(uint32_t idx, uint64_t value);
    uint64_t gpr(uint32_t idx) const;

    void writeCsr(uint32_t addr, uint64_t value);
    void writeCsrRaw(uint32_t addr, uint64_t value);
    uint64_t readCsr(uint32_t addr) const;
    bool consumeFaultAckRequest();

    bool enterWfi();
    bool hasEnabledPendingEvents() const;
    uint32_t wakeEligibleEvents() const;
    uint32_t enabledEvents() const;
    void raiseArchitecturalEvents(uint32_t event_mask);
    void wakeOnEvent(uint32_t event_mask);
    void clearEvents(uint32_t event_mask);
    void leaveWfi();
    void halt();
    bool isHalted() const { return halted_; }

    bool loadMemoryImage(const riscv_snn::RiscvSnnMemoryImage& image,
                         uint64_t capacity_bytes,
                         std::string& error);
    bool fetchInsn32(uint64_t addr, uint32_t& value) const;
    bool loadU32(uint64_t addr, uint32_t& value) const;
    bool storeU32(uint64_t addr, uint32_t value);
    bool loadBytes(uint64_t addr, void* dst, size_t size) const;
    bool storeBytes(uint64_t addr, const void* src, size_t size);
    const riscv_snn::RiscvSnnMemoryImage& memoryImage() const { return memory_image_; }
    uint64_t memoryCapacityBytes() const { return memory_capacity_bytes_; }

    bool isWaitingForInterrupt() const { return waiting_for_interrupt_; }
    uint32_t pendingEvents() const { return pending_events_; }

private:
    uint64_t pc_ = 0;
    std::array<uint64_t, 32> gpr_{};
    std::map<uint32_t, uint64_t> csr_bank_{};
    riscv_snn::RiscvSnnMemoryImage memory_image_{};
    uint64_t memory_capacity_bytes_ = 0;
    std::vector<uint8_t> memory_bytes_{};
    uint32_t pending_events_ = 0;
    bool waiting_for_interrupt_ = false;
    bool halted_ = false;
    bool fault_ack_requested_ = false;
};

}} // namespace SST::SnnDL
