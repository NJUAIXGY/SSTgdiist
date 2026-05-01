// -*- c++ -*-

#include <sst/core/sst_config.h>

#include "workload/riscv_snn/RiscvSnnIss.h"

#include "workload/riscv_snn/RiscvSnnHart.h"

namespace SST { namespace SnnDL {

namespace {

int64_t signExtend(uint32_t value, uint32_t bits) {
    const uint32_t shift = 64u - bits;
    const uint64_t widened = static_cast<uint64_t>(value) << shift;
    return static_cast<int64_t>(widened) >> shift;
}

uint32_t opcode(uint32_t insn) {
    return insn & 0x7Fu;
}

uint32_t rd(uint32_t insn) {
    return (insn >> 7) & 0x1Fu;
}

uint32_t funct3(uint32_t insn) {
    return (insn >> 12) & 0x7u;
}

uint32_t rs1(uint32_t insn) {
    return (insn >> 15) & 0x1Fu;
}

uint32_t rs2(uint32_t insn) {
    return (insn >> 20) & 0x1Fu;
}

uint32_t csr(uint32_t insn) {
    return (insn >> 20) & 0xFFFu;
}

uint32_t zimm(uint32_t insn) {
    return rs1(insn);
}

int64_t immI(uint32_t insn) {
    return signExtend((insn >> 20) & 0xFFFu, 12);
}

uint64_t immU(uint32_t insn) {
    return static_cast<uint64_t>(insn & 0xFFFFF000u);
}

int64_t immS(uint32_t insn) {
    const uint32_t value = ((insn >> 7) & 0x1Fu) | (((insn >> 25) & 0x7Fu) << 5);
    return signExtend(value, 12);
}

int64_t immB(uint32_t insn) {
    const uint32_t value = (((insn >> 8) & 0xFu) << 1) |
        (((insn >> 25) & 0x3Fu) << 5) |
        (((insn >> 7) & 0x1u) << 11) |
        (((insn >> 31) & 0x1u) << 12);
    return signExtend(value, 13);
}

int64_t immJ(uint32_t insn) {
    const uint32_t value = (((insn >> 21) & 0x3FFu) << 1) |
        (((insn >> 20) & 0x1u) << 11) |
        (((insn >> 12) & 0xFFu) << 12) |
        (((insn >> 31) & 0x1u) << 20);
    return signExtend(value, 21);
}

} // namespace

RiscvSnnIss::StepResult RiscvSnnIss::step(RiscvSnnHart& hart) const {
    StepResult result;
    result.pc_before = hart.pc();
    result.pc_after = hart.pc();

    if (hart.isHalted()) {
        result.stop_reason = StopReason::Halted;
        return result;
    }

    if (hart.isWaitingForInterrupt()) {
        if (!hart.hasEnabledPendingEvents()) {
            result.stop_reason = StopReason::WaitingForInterrupt;
            return result;
        }
        hart.leaveWfi();
    }

    uint32_t insn = 0;
    if (!hart.fetchInsn32(hart.pc(), insn)) {
        result.stop_reason = StopReason::Fault;
        return result;
    }
    result.insn = insn;

    switch (opcode(insn)) {
    case 0x13: {
        if (funct3(insn) != 0x0u) {
            result.stop_reason = StopReason::Fault;
            return result;
        }
        const uint64_t value = static_cast<uint64_t>(
            static_cast<int64_t>(hart.gpr(rs1(insn))) + immI(insn));
        hart.setGpr(rd(insn), value);
        hart.setPc(hart.pc() + 4);
        result.retired = true;
        break;
    }
    case 0x03: {
        const uint64_t addr = hart.gpr(rs1(insn)) + static_cast<uint64_t>(immI(insn));
        switch (funct3(insn)) {
        case 0x2: {
            uint32_t value = 0;
            if (!hart.loadU32(addr, value)) {
                result.stop_reason = StopReason::Fault;
                return result;
            }
            hart.setGpr(
                rd(insn),
                static_cast<uint64_t>(static_cast<int64_t>(static_cast<int32_t>(value))));
            break;
        }
        case 0x3: {
            uint64_t value = 0;
            if (!hart.loadBytes(addr, &value, sizeof(value))) {
                result.stop_reason = StopReason::Fault;
                return result;
            }
            hart.setGpr(rd(insn), value);
            break;
        }
        default:
            result.stop_reason = StopReason::Fault;
            return result;
        }
        hart.setPc(hart.pc() + 4);
        result.retired = true;
        break;
    }
    case 0x23: {
        const uint64_t addr = hart.gpr(rs1(insn)) + static_cast<uint64_t>(immS(insn));
        switch (funct3(insn)) {
        case 0x2: {
            const uint32_t value = static_cast<uint32_t>(hart.gpr(rs2(insn)) & 0xFFFFFFFFu);
            if (!hart.storeU32(addr, value)) {
                result.stop_reason = StopReason::Fault;
                return result;
            }
            break;
        }
        case 0x3: {
            const uint64_t value = hart.gpr(rs2(insn));
            if (!hart.storeBytes(addr, &value, sizeof(value))) {
                result.stop_reason = StopReason::Fault;
                return result;
            }
            break;
        }
        default:
            result.stop_reason = StopReason::Fault;
            return result;
        }
        hart.setPc(hart.pc() + 4);
        result.retired = true;
        break;
    }
    case 0x63: {
        bool take = false;
        switch (funct3(insn)) {
        case 0x0:
            take = hart.gpr(rs1(insn)) == hart.gpr(rs2(insn));
            break;
        case 0x1:
            take = hart.gpr(rs1(insn)) != hart.gpr(rs2(insn));
            break;
        default:
            result.stop_reason = StopReason::Fault;
            return result;
        }
        hart.setPc(hart.pc() + static_cast<uint64_t>(take ? immB(insn) : 4));
        result.retired = true;
        break;
    }
    case 0x67: {
        if (funct3(insn) != 0x0u) {
            result.stop_reason = StopReason::Fault;
            return result;
        }
        const uint64_t next_pc = hart.pc() + 4;
        const uint64_t target =
            (hart.gpr(rs1(insn)) + static_cast<uint64_t>(immI(insn))) & ~1ull;
        hart.setGpr(rd(insn), next_pc);
        hart.setPc(target);
        result.retired = true;
        break;
    }
    case 0x6F: {
        const uint64_t next_pc = hart.pc() + 4;
        hart.setGpr(rd(insn), next_pc);
        hart.setPc(hart.pc() + static_cast<uint64_t>(immJ(insn)));
        result.retired = true;
        break;
    }
    case 0x37:
        hart.setGpr(rd(insn), immU(insn));
        hart.setPc(hart.pc() + 4);
        result.retired = true;
        break;
    case 0x73: {
        const uint32_t f3 = funct3(insn);
        if (f3 == 0x0u) {
            if (insn == 0x10500073u) {
                hart.setPc(hart.pc() + 4);
                result.retired = true;
                if (hart.enterWfi()) {
                    result.stop_reason = StopReason::WaitingForInterrupt;
                }
                break;
            }
            if (insn == 0x00100073u) {
                hart.setPc(hart.pc() + 4);
                hart.halt();
                result.retired = true;
                result.stop_reason = StopReason::Halted;
                break;
            }
            result.stop_reason = StopReason::Fault;
            return result;
        }

        const uint32_t csr_addr = csr(insn);
        const uint64_t old_value = hart.readCsr(csr_addr);
        const uint32_t rd_idx = rd(insn);
        if (rd_idx != 0) hart.setGpr(rd_idx, old_value);

        switch (f3) {
        case 0x1:
            hart.writeCsr(csr_addr, hart.gpr(rs1(insn)));
            break;
        case 0x2:
            if (rs1(insn) != 0) {
                hart.writeCsr(csr_addr, old_value | hart.gpr(rs1(insn)));
            }
            break;
        case 0x5:
            hart.writeCsr(csr_addr, zimm(insn));
            break;
        case 0x6:
            if (zimm(insn) != 0) {
                hart.writeCsr(csr_addr, old_value | zimm(insn));
            }
            break;
        default:
            result.stop_reason = StopReason::Fault;
            return result;
        }

        hart.setPc(hart.pc() + 4);
        result.retired = true;
        break;
    }
    default:
        result.stop_reason = StopReason::Fault;
        return result;
    }

    result.pc_after = hart.pc();
    return result;
}

}} // namespace SST::SnnDL
