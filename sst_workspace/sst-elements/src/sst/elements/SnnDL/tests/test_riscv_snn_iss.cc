// -*- c++ -*-

#include "workload/riscv_snn/RiscvSnnAbi.h"
#include "workload/riscv_snn/RiscvSnnAsm.h"
#include "workload/riscv_snn/RiscvSnnHart.h"
#include "workload/riscv_snn/RiscvSnnIss.h"
#include "workload/riscv_snn/RiscvSnnMemoryImage.h"

#include <cassert>
#include <cstdint>
#include <vector>

namespace {

using SST::SnnDL::riscv_snn::EventBit;
namespace asmv1 = SST::SnnDL::riscv_snn::asmv1;

} // namespace

int main() {
    using namespace SST::SnnDL;
    using namespace SST::SnnDL::riscv_snn;

    std::vector<uint8_t> text;
    asmv1::appendInsn32(text, asmv1::encodeLui(/*rd=*/8, /*imm20=*/0x2));
    asmv1::appendInsn32(text, asmv1::encodeAddi(/*rd=*/8, /*rs1=*/8, /*imm=*/0x100));
    asmv1::appendInsn32(text, asmv1::encodeCsrrwi(/*rd=*/0, kCsrMsnnEventEnable, /*zimm=*/0x7));
    asmv1::appendInsn32(text, asmv1::encodeAddi(/*rd=*/1, /*rs1=*/0, /*imm=*/5));
    asmv1::appendInsn32(text, asmv1::encodeSd(/*rs2=*/1, /*rs1=*/8, /*imm=*/0));
    asmv1::appendInsn32(text, asmv1::encodeLd(/*rd=*/5, /*rs1=*/8, /*imm=*/0));
    asmv1::appendInsn32(text, asmv1::encodeSw(/*rs2=*/1, /*rs1=*/8, /*imm=*/8));
    asmv1::appendInsn32(text, asmv1::encodeLw(/*rd=*/6, /*rs1=*/8, /*imm=*/8));
    asmv1::appendInsn32(text, asmv1::encodeBeq(/*rs1=*/5, /*rs2=*/1, /*imm=*/8));
    asmv1::appendInsn32(text, asmv1::encodeAddi(/*rd=*/7, /*rs1=*/0, /*imm=*/99));
    asmv1::appendInsn32(text, asmv1::encodeBne(/*rs1=*/6, /*rs2=*/1, /*imm=*/8));
    asmv1::appendInsn32(text, asmv1::encodeAddi(/*rd=*/7, /*rs1=*/0, /*imm=*/11));
    asmv1::appendInsn32(text, asmv1::encodeJal(/*rd=*/9, /*imm=*/8));
    asmv1::appendInsn32(text, asmv1::encodeAddi(/*rd=*/10, /*rs1=*/0, /*imm=*/77));
    asmv1::appendInsn32(text, asmv1::encodeCsrrw(/*rd=*/2, kCsrMsnnCfg, /*rs1=*/1));
    asmv1::appendInsn32(text, asmv1::encodeCsrrs(/*rd=*/3, kCsrMsnnCfg, /*rs1=*/1));
    asmv1::appendInsn32(text, asmv1::encodeWfi());
    asmv1::appendInsn32(text, asmv1::encodeAddi(/*rd=*/4, /*rs1=*/0, /*imm=*/7));
    asmv1::appendInsn32(text, asmv1::encodeEbreak());

    RiscvSnnMemoryImage image;
    image.entry_pc = 0x1000;
    image.segments.push_back({0x1000, 0, text});

    RiscvSnnHart hart;
    hart.reset(image.entry_pc);
    std::string error;
    assert(hart.loadMemoryImage(image, /*capacity_bytes=*/0x4000, error));
    assert(error.empty());

    RiscvSnnIss iss;

    auto step0 = iss.step(hart);
    assert(step0.retired);
    assert(step0.stop_reason == RiscvSnnIss::StopReason::None);
    assert(hart.gpr(8) == 0x2000u);
    assert(hart.pc() == 0x1004);

    auto step1 = iss.step(hart);
    assert(step1.retired);
    assert(step1.stop_reason == RiscvSnnIss::StopReason::None);
    assert(hart.gpr(8) == 0x2100u);
    assert(hart.pc() == 0x1008);

    auto step2 = iss.step(hart);
    assert(step2.retired);
    assert(step2.stop_reason == RiscvSnnIss::StopReason::None);
    assert(hart.readCsr(kCsrMsnnEventEnable) == 0x7);
    assert(hart.pc() == 0x100C);

    auto step3 = iss.step(hart);
    assert(step3.retired);
    assert(hart.gpr(1) == 5);
    assert(hart.pc() == 0x1010);

    auto step4 = iss.step(hart);
    assert(step4.retired);
    uint64_t stored_u64 = 0;
    assert(hart.loadBytes(0x2100, &stored_u64, sizeof(stored_u64)));
    assert(stored_u64 == 5);
    assert(hart.pc() == 0x1014);

    auto step5 = iss.step(hart);
    assert(step5.retired);
    assert(hart.gpr(5) == 5);
    assert(hart.pc() == 0x1018);

    auto step6 = iss.step(hart);
    assert(step6.retired);
    uint32_t stored_u32 = 0;
    assert(hart.loadBytes(0x2108, &stored_u32, sizeof(stored_u32)));
    assert(stored_u32 == 5u);
    assert(hart.pc() == 0x101C);

    auto step7 = iss.step(hart);
    assert(step7.retired);
    assert(hart.gpr(6) == 5);
    assert(hart.pc() == 0x1020);

    auto step8 = iss.step(hart);
    assert(step8.retired);
    assert(hart.pc() == 0x1028);
    assert(hart.gpr(7) == 0);

    auto step9 = iss.step(hart);
    assert(step9.retired);
    assert(hart.pc() == 0x102C);
    assert(hart.gpr(7) == 0);

    auto step10 = iss.step(hart);
    assert(step10.retired);
    assert(hart.gpr(7) == 11);
    assert(hart.pc() == 0x1030);

    auto step11 = iss.step(hart);
    assert(step11.retired);
    assert(hart.gpr(9) == 0x1034u);
    assert(hart.pc() == 0x1038);
    assert(hart.gpr(10) == 0);

    auto step12 = iss.step(hart);
    assert(step12.retired);
    assert(hart.gpr(2) == 0);
    assert(hart.readCsr(kCsrMsnnCfg) == 5);
    assert(hart.pc() == 0x103C);

    auto step13 = iss.step(hart);
    assert(step13.retired);
    assert(hart.gpr(3) == 5);
    assert(hart.readCsr(kCsrMsnnCfg) == 5);
    assert(hart.pc() == 0x1040);

    auto step14 = iss.step(hart);
    assert(step14.retired);
    assert(step14.stop_reason == RiscvSnnIss::StopReason::WaitingForInterrupt);
    assert(hart.isWaitingForInterrupt());
    assert(hart.pc() == 0x1044);

    auto blocked = iss.step(hart);
    assert(!blocked.retired);
    assert(blocked.stop_reason == RiscvSnnIss::StopReason::WaitingForInterrupt);
    assert(hart.pc() == 0x1044);

    hart.raiseArchitecturalEvents(eventMask(EventBit::CmdComplete));
    auto step15 = iss.step(hart);
    assert(step15.retired);
    assert(step15.stop_reason == RiscvSnnIss::StopReason::None);
    assert(!hart.isWaitingForInterrupt());
    assert(hart.gpr(4) == 7);
    assert(hart.pc() == 0x1048);

    auto step16 = iss.step(hart);
    assert(step16.retired);
    assert(step16.stop_reason == RiscvSnnIss::StopReason::Halted);
    assert(hart.isHalted());

    hart.writeCsr(kCsrMsnnFault, 0x1122334455667788ull);
    assert(hart.readCsr(kCsrMsnnFault) == 0x1122334455667788ull);
    hart.writeCsr(kCsrMsnnFault, 0xA5A50000ull);
    assert(hart.readCsr(kCsrMsnnFault) == 0);
    return 0;
}
