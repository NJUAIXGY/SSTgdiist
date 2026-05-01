// -*- c++ -*-
//
// RiscvSnnAsm:
// - `riscv_snn` 实验主线私有的最小指令编码 helper。
// - 仅覆盖当前 bring-up / test firmware 需要的 RV64I + CSR 子集，避免在测试里散落重复编码逻辑。
//

#pragma once

#include <cstdint>
#include <vector>

namespace SST { namespace SnnDL { namespace riscv_snn { namespace asmv1 {

inline uint32_t encodeIType(int32_t imm, uint32_t rs1, uint32_t funct3, uint32_t rd, uint32_t opcode) {
    const uint32_t uimm = static_cast<uint32_t>(imm) & 0xFFFu;
    return (uimm << 20) | ((rs1 & 0x1Fu) << 15) | ((funct3 & 0x7u) << 12) |
        ((rd & 0x1Fu) << 7) | (opcode & 0x7Fu);
}

inline uint32_t encodeAddi(uint32_t rd, uint32_t rs1, int32_t imm) {
    return encodeIType(imm, rs1, 0x0u, rd, 0x13u);
}

inline uint32_t encodeLui(uint32_t rd, uint32_t imm20) {
    return ((imm20 & 0xFFFFFu) << 12) | ((rd & 0x1Fu) << 7) | 0x37u;
}

inline uint32_t encodeLoad(uint32_t rd, uint32_t rs1, int32_t imm, uint32_t funct3) {
    return encodeIType(imm, rs1, funct3, rd, 0x03u);
}

inline uint32_t encodeLd(uint32_t rd, uint32_t rs1, int32_t imm) {
    return encodeLoad(rd, rs1, imm, 0x3u);
}

inline uint32_t encodeLw(uint32_t rd, uint32_t rs1, int32_t imm) {
    return encodeLoad(rd, rs1, imm, 0x2u);
}

inline uint32_t encodeStore(uint32_t rs2, uint32_t rs1, int32_t imm, uint32_t funct3) {
    const uint32_t uimm = static_cast<uint32_t>(imm) & 0xFFFu;
    const uint32_t imm_lo = uimm & 0x1Fu;
    const uint32_t imm_hi = (uimm >> 5) & 0x7Fu;
    return (imm_hi << 25) | ((rs2 & 0x1Fu) << 20) | ((rs1 & 0x1Fu) << 15) |
        ((funct3 & 0x7u) << 12) | (imm_lo << 7) | 0x23u;
}

inline uint32_t encodeSd(uint32_t rs2, uint32_t rs1, int32_t imm) {
    return encodeStore(rs2, rs1, imm, 0x3u);
}

inline uint32_t encodeSw(uint32_t rs2, uint32_t rs1, int32_t imm) {
    return encodeStore(rs2, rs1, imm, 0x2u);
}

inline uint32_t encodeBranch(uint32_t rs1, uint32_t rs2, int32_t imm, uint32_t funct3) {
    const uint32_t uimm = static_cast<uint32_t>(imm) & 0x1FFFu;
    const uint32_t bit12 = (uimm >> 12) & 0x1u;
    const uint32_t bit11 = (uimm >> 11) & 0x1u;
    const uint32_t bits10_5 = (uimm >> 5) & 0x3Fu;
    const uint32_t bits4_1 = (uimm >> 1) & 0xFu;
    return (bit12 << 31) | (bits10_5 << 25) | ((rs2 & 0x1Fu) << 20) |
        ((rs1 & 0x1Fu) << 15) | ((funct3 & 0x7u) << 12) | (bits4_1 << 8) |
        (bit11 << 7) | 0x63u;
}

inline uint32_t encodeBeq(uint32_t rs1, uint32_t rs2, int32_t imm) {
    return encodeBranch(rs1, rs2, imm, 0x0u);
}

inline uint32_t encodeBne(uint32_t rs1, uint32_t rs2, int32_t imm) {
    return encodeBranch(rs1, rs2, imm, 0x1u);
}

inline uint32_t encodeJal(uint32_t rd, int32_t imm) {
    const uint32_t uimm = static_cast<uint32_t>(imm) & 0x1FFFFFu;
    const uint32_t bit20 = (uimm >> 20) & 0x1u;
    const uint32_t bits10_1 = (uimm >> 1) & 0x3FFu;
    const uint32_t bit11 = (uimm >> 11) & 0x1u;
    const uint32_t bits19_12 = (uimm >> 12) & 0xFFu;
    return (bit20 << 31) | (bits10_1 << 21) | (bit11 << 20) |
        (bits19_12 << 12) | ((rd & 0x1Fu) << 7) | 0x6Fu;
}

inline uint32_t encodeJalr(uint32_t rd, uint32_t rs1, int32_t imm) {
    return encodeIType(imm, rs1, 0x0u, rd, 0x67u);
}

inline uint32_t encodeCsrrw(uint32_t rd, uint32_t csr, uint32_t rs1) {
    return ((csr & 0xFFFu) << 20) | ((rs1 & 0x1Fu) << 15) | (0x1u << 12) |
        ((rd & 0x1Fu) << 7) | 0x73u;
}

inline uint32_t encodeCsrrs(uint32_t rd, uint32_t csr, uint32_t rs1) {
    return ((csr & 0xFFFu) << 20) | ((rs1 & 0x1Fu) << 15) | (0x2u << 12) |
        ((rd & 0x1Fu) << 7) | 0x73u;
}

inline uint32_t encodeCsrrwi(uint32_t rd, uint32_t csr, uint32_t zimm) {
    return ((csr & 0xFFFu) << 20) | ((zimm & 0x1Fu) << 15) | (0x5u << 12) |
        ((rd & 0x1Fu) << 7) | 0x73u;
}

inline uint32_t encodeWfi() {
    return 0x10500073u;
}

inline uint32_t encodeEbreak() {
    return 0x00100073u;
}

inline void appendInsn32(std::vector<uint8_t>& bytes, uint32_t value) {
    bytes.push_back(static_cast<uint8_t>(value & 0xFFu));
    bytes.push_back(static_cast<uint8_t>((value >> 8) & 0xFFu));
    bytes.push_back(static_cast<uint8_t>((value >> 16) & 0xFFu));
    bytes.push_back(static_cast<uint8_t>((value >> 24) & 0xFFu));
}

}}}} // namespace SST::SnnDL::riscv_snn::asmv1
