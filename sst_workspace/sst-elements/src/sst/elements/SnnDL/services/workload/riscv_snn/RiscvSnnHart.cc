// -*- c++ -*-

#include <sst/core/sst_config.h>

#include <cstring>

#include "workload/riscv_snn/RiscvSnnHart.h"
#include "workload/riscv_snn/RiscvSnnAbi.h"

namespace SST { namespace SnnDL {

namespace {

bool rangeFits(uint64_t addr, size_t size, size_t capacity) {
    if (size == 0) return true;
    if (addr >= static_cast<uint64_t>(capacity)) return false;
    const uint64_t max_size = static_cast<uint64_t>(capacity) - addr;
    return static_cast<uint64_t>(size) <= max_size;
}

} // namespace

void RiscvSnnHart::reset(uint64_t boot_pc) {
    pc_ = boot_pc;
    gpr_.fill(0);
    csr_bank_.clear();
    memory_image_ = riscv_snn::RiscvSnnMemoryImage{};
    memory_capacity_bytes_ = 0;
    memory_bytes_.clear();
    pending_events_ = 0;
    waiting_for_interrupt_ = false;
    halted_ = false;
    fault_ack_requested_ = false;
    csr_bank_[riscv_snn::kCsrMsnnEventEnable] = 0;
    csr_bank_[riscv_snn::kCsrMsnnEventPending] = 0;
}

void RiscvSnnHart::setPc(uint64_t pc) {
    pc_ = pc;
}

void RiscvSnnHart::setGpr(uint32_t idx, uint64_t value) {
    if (idx == 0 || idx >= gpr_.size()) return;
    gpr_[idx] = value;
}

uint64_t RiscvSnnHart::gpr(uint32_t idx) const {
    if (idx >= gpr_.size()) return 0;
    return gpr_[idx];
}

void RiscvSnnHart::writeCsr(uint32_t addr, uint64_t value) {
    if (addr == riscv_snn::kCsrMsnnEventPending) {
        pending_events_ &= ~static_cast<uint32_t>(value & riscv_snn::architecturalEventW1cMask());
        csr_bank_[addr] = pending_events_;
        return;
    }
    if (addr == riscv_snn::kCsrMsnnFault &&
        riscv_snn::faultAckWriteClearsVisibleRecord(value)) {
        writeCsrRaw(addr, 0);
        fault_ack_requested_ = true;
        return;
    }
    writeCsrRaw(addr, value);
}

void RiscvSnnHart::writeCsrRaw(uint32_t addr, uint64_t value) {
    csr_bank_[addr] = value;
    if (addr == riscv_snn::kCsrMsnnEventEnable && hasEnabledPendingEvents()) {
        waiting_for_interrupt_ = false;
    }
}

bool RiscvSnnHart::consumeFaultAckRequest() {
    const bool requested = fault_ack_requested_;
    fault_ack_requested_ = false;
    return requested;
}

uint64_t RiscvSnnHart::readCsr(uint32_t addr) const {
    if (addr == riscv_snn::kCsrMsnnEventPending) return pending_events_;
    auto it = csr_bank_.find(addr);
    if (it == csr_bank_.end()) return 0;
    return it->second;
}

bool RiscvSnnHart::enterWfi() {
    waiting_for_interrupt_ = !hasEnabledPendingEvents();
    return waiting_for_interrupt_;
}

bool RiscvSnnHart::hasEnabledPendingEvents() const {
    return wakeEligibleEvents() != 0;
}

uint32_t RiscvSnnHart::wakeEligibleEvents() const {
    return pending_events_ & enabledEvents();
}

uint32_t RiscvSnnHart::enabledEvents() const {
    return static_cast<uint32_t>(
        readCsr(riscv_snn::kCsrMsnnEventEnable) &
        riscv_snn::architecturalEventW1cMask());
}

void RiscvSnnHart::raiseArchitecturalEvents(uint32_t event_mask) {
    pending_events_ |= (event_mask & riscv_snn::architecturalEventW1cMask());
    csr_bank_[riscv_snn::kCsrMsnnEventPending] = pending_events_;
    if (hasEnabledPendingEvents()) waiting_for_interrupt_ = false;
}

void RiscvSnnHart::wakeOnEvent(uint32_t event_mask) {
    raiseArchitecturalEvents(event_mask);
}

void RiscvSnnHart::clearEvents(uint32_t event_mask) {
    pending_events_ &= ~static_cast<uint32_t>(
        event_mask & riscv_snn::architecturalEventW1cMask());
    csr_bank_[riscv_snn::kCsrMsnnEventPending] = pending_events_;
}

void RiscvSnnHart::leaveWfi() {
    waiting_for_interrupt_ = false;
}

void RiscvSnnHart::halt() {
    halted_ = true;
    waiting_for_interrupt_ = false;
}

bool RiscvSnnHart::loadMemoryImage(const riscv_snn::RiscvSnnMemoryImage& image,
                                   uint64_t capacity_bytes,
                                   std::string& error) {
    error.clear();
    if (capacity_bytes == 0 || capacity_bytes > static_cast<uint64_t>(SIZE_MAX)) {
        error = "invalid local memory capacity";
        return false;
    }
    if (image.footprintBytes() > capacity_bytes) {
        error = "firmware image footprint exceeds local memory capacity";
        return false;
    }
    for (size_t i = 0; i < image.segments.size(); ++i) {
        if (image.segments[i].endAddressExclusive() > capacity_bytes) {
            error = "firmware image segment exceeds local memory capacity";
            return false;
        }
        for (size_t j = i + 1; j < image.segments.size(); ++j) {
            if (riscv_snn::segmentsOverlap(image.segments[i], image.segments[j])) {
                error = "firmware image segments overlap";
                return false;
            }
        }
    }
    if (image.entry_pc >= capacity_bytes) {
        error = "firmware entry pc exceeds local memory capacity";
        return false;
    }

    memory_image_ = image;
    memory_capacity_bytes_ = capacity_bytes;
    memory_bytes_.assign(static_cast<size_t>(capacity_bytes), 0);
    for (const auto& seg : image.segments) {
        if (!seg.data.empty()) {
            std::memcpy(
                memory_bytes_.data() + static_cast<size_t>(seg.vaddr),
                seg.data.data(),
                seg.data.size());
        }
    }
    if (image.entry_pc != 0) pc_ = image.entry_pc;
    return true;
}

bool RiscvSnnHart::fetchInsn32(uint64_t addr, uint32_t& value) const {
    return loadU32(addr, value);
}

bool RiscvSnnHart::loadU32(uint64_t addr, uint32_t& value) const {
    return loadBytes(addr, &value, sizeof(value));
}

bool RiscvSnnHart::storeU32(uint64_t addr, uint32_t value) {
    return storeBytes(addr, &value, sizeof(value));
}

bool RiscvSnnHart::loadBytes(uint64_t addr, void* dst, size_t size) const {
    if (!dst) return false;
    if (!rangeFits(addr, size, memory_bytes_.size())) return false;
    std::memcpy(dst, memory_bytes_.data() + static_cast<size_t>(addr), size);
    return true;
}

bool RiscvSnnHart::storeBytes(uint64_t addr, const void* src, size_t size) {
    if (!src) return false;
    if (!rangeFits(addr, size, memory_bytes_.size())) return false;
    std::memcpy(memory_bytes_.data() + static_cast<size_t>(addr), src, size);
    return true;
}

}} // namespace SST::SnnDL
