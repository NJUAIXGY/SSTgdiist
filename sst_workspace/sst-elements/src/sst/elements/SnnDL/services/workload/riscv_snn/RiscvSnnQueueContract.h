// -*- c++ -*-
//
// RiscvSnnQueueContract:
// - `riscv_snn` v1.1 的最小 command/completion ring ownership 语义。
// - 保持为 header-only，方便在 compile-only / standalone contract test 中直接复用。
//

#pragma once

#include <cstdint>
#include <vector>

#include "workload/common/SnnAccelBackend.h"
#include "workload/riscv_snn/RiscvSnnAbi.h"

namespace SST { namespace SnnDL { namespace riscv_snn {

inline constexpr bool isPowerOfTwoEntries(uint32_t entries) {
    return entries != 0 && ((entries & (entries - 1)) == 0);
}

inline constexpr uint64_t ticketToSlot(uint64_t ticket, uint32_t entries) {
    return isPowerOfTwoEntries(entries) ? (ticket & static_cast<uint64_t>(entries - 1)) : 0;
}

inline constexpr bool queueEmpty(uint64_t head, uint64_t tail) {
    return head == tail;
}

inline constexpr bool queueFull(uint64_t head, uint64_t tail, uint32_t entries) {
    return isPowerOfTwoEntries(entries) && ((tail - head) >= static_cast<uint64_t>(entries));
}

class RiscvSnnQueueContract {
public:
    bool configure(uint32_t cmd_entries, uint32_t cmp_entries, uint32_t rx_entries) {
        if (!isPowerOfTwoEntries(cmd_entries) ||
            !isPowerOfTwoEntries(cmp_entries) ||
            !isPowerOfTwoEntries(rx_entries)) {
            return false;
        }
        cmd_entries_ = cmd_entries;
        cmp_entries_ = cmp_entries;
        rx_entries_ = rx_entries;
        cmd_ring_.assign(cmd_entries_, CommandDescriptorV1{});
        cmp_ring_.assign(cmp_entries_, CompletionEntryV1{});
        cmd_head_ = 0;
        cmd_tail_ = 0;
        cmp_head_ = 0;
        cmp_tail_ = 0;
        rx_head_ = 0;
        rx_tail_ = 0;
        last_accept_opcode_ = 0;
        return true;
    }

    bool enqueueCommand(const CommandDescriptorV1& desc, uint64_t& out_ticket) {
        if (queueFull(cmd_head_, cmd_tail_, cmd_entries_)) return false;
        out_ticket = cmd_tail_;
        cmd_ring_[ticketToSlot(cmd_tail_, cmd_entries_)] = desc;
        ++cmd_tail_;
        return true;
    }

    bool peekCommand(SnnAccelCommand& out_command) const {
        if (queueEmpty(cmd_head_, cmd_tail_)) return false;
        const uint64_t ticket = cmd_head_;
        const CommandDescriptorV1& desc = cmd_ring_[ticketToSlot(ticket, cmd_entries_)];
        out_command = decodeCommand_(ticket, desc);
        return true;
    }

    bool acceptCommand(uint64_t ticket) {
        if (queueEmpty(cmd_head_, cmd_tail_)) return false;
        if (ticket != cmd_head_) return false;
        const CommandDescriptorV1& desc = cmd_ring_[ticketToSlot(ticket, cmd_entries_)];
        last_accept_opcode_ = descriptorOpcodeRaw(desc.hdr0);
        ++cmd_head_;
        return true;
    }

    bool publishCompletion(const SnnAccelCompletion& completion, uint32_t& out_raised_events) {
        if (queueFull(cmp_head_, cmp_tail_, cmp_entries_)) return false;
        CompletionEntryV1 entry;
        entry.token = static_cast<uint32_t>(completion.token & 0xFFFFFFFFu);
        entry.status_code = completion.status_code;
        entry.aux0 = completion.aux0;
        entry.aux1 = completion.aux1;
        cmp_ring_[ticketToSlot(cmp_tail_, cmp_entries_)] = entry;
        ++cmp_tail_;
        out_raised_events = completion.event_mask;
        return true;
    }

    bool peekCompletion(CompletionEntryV1& out_completion) const {
        if (queueEmpty(cmp_head_, cmp_tail_)) return false;
        out_completion = cmp_ring_[ticketToSlot(cmp_head_, cmp_entries_)];
        return true;
    }

    bool consumeCompletion(CompletionEntryV1& out_completion) {
        if (!peekCompletion(out_completion)) return false;
        ++cmp_head_;
        return true;
    }

    uint32_t cmdEntries() const { return cmd_entries_; }
    uint32_t cmpEntries() const { return cmp_entries_; }
    uint32_t rxEntries() const { return rx_entries_; }

    uint64_t cmdHead() const { return cmd_head_; }
    uint64_t cmdTail() const { return cmd_tail_; }
    uint64_t cmpHead() const { return cmp_head_; }
    uint64_t cmpTail() const { return cmp_tail_; }
    uint64_t rxHead() const { return rx_head_; }
    uint64_t rxTail() const { return rx_tail_; }

    bool commandQueueFull() const { return queueFull(cmd_head_, cmd_tail_, cmd_entries_); }
    bool commandQueueEmpty() const { return queueEmpty(cmd_head_, cmd_tail_); }
    bool completionQueueEmpty() const { return queueEmpty(cmp_head_, cmp_tail_); }
    bool completionQueueNonEmpty() const { return !completionQueueEmpty(); }
    uint8_t lastAcceptedOpcode() const { return last_accept_opcode_; }

private:
    static SnnAccelCommand decodeCommand_(uint64_t ticket, const CommandDescriptorV1& desc) {
        SnnAccelCommand command;
        command.ticket = ticket;
        command.raw_header = desc.hdr0;
        command.version = descriptorVersion(desc.hdr0);
        command.opcode = descriptorOpcodeRaw(desc.hdr0);
        command.flags = descriptorFlags(desc.hdr0);
        command.completion_policy = descriptorCompletionPolicy(desc.hdr0);
        command.error_policy = descriptorErrorPolicy(desc.hdr0);
        command.desc_bytes = descriptorBytes(desc.hdr0);
        command.token = desc.token;
        command.arg0 = desc.arg0;
        command.arg1 = desc.arg1;
        command.src_addr = desc.src_addr;
        command.dst_addr = desc.dst_addr;
        command.len_or_count = desc.len_or_count;
        command.dep_user = desc.dep_user;
        return command;
    }

    uint32_t cmd_entries_ = 0;
    uint32_t cmp_entries_ = 0;
    uint32_t rx_entries_ = 0;
    uint64_t cmd_head_ = 0;
    uint64_t cmd_tail_ = 0;
    uint64_t cmp_head_ = 0;
    uint64_t cmp_tail_ = 0;
    uint64_t rx_head_ = 0;
    uint64_t rx_tail_ = 0;
    uint8_t last_accept_opcode_ = 0;
    std::vector<CommandDescriptorV1> cmd_ring_{};
    std::vector<CompletionEntryV1> cmp_ring_{};
};

}}} // namespace SST::SnnDL::riscv_snn
