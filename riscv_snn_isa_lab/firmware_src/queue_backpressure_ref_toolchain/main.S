    .option norvc
    .include "abi.inc"

    .section .text, "ax"
    .globl main

main:
    csrrwi x0, CSR_MSNN_EVENT_ENABLE, 7
    csrrs x8, CSR_MSNN_CMDQ_BASE, x0
    addi x1, x0, 1
    addi x21, x0, 2
    lui x10, 0x9
    ld x2, 0(x10)
    sd x2, 0(x8)
    sd x1, 8(x8)
    sd x0, 16(x8)
    sd x0, 24(x8)
    sd x0, 32(x8)
    sd x0, 40(x8)
    sd x0, 48(x8)
    sd x0, 56(x8)
    csrrw x0, CSR_MSNN_CMDQ_TAIL, x21
    wfi

    csrrs x3, CSR_MSNN_CMDQ_HEAD, x0
    bne x3, x1, fail
    csrrs x4, CSR_MSNN_CMDQ_TAIL, x0
    bne x4, x1, fail
    csrrs x5, CSR_MSNN_CMPQ_TAIL, x0
    bne x5, x0, fail
    csrrs x6, CSR_MSNN_STEP, x0
    bne x6, x0, fail
    csrrs x7, CSR_MSNN_FAULT, x0
    ld x11, 8(x10)
    bne x7, x11, fail
    csrrwi x0, CSR_MSNN_EVENT_PENDING, 7
    addi x7, x0, 0x81
    ebreak

fail:
    addi x7, x0, 0x82
    ebreak

    .section .rodata, "a"
descriptor_header:
    .quad 0x0000400000002001
    .quad 0x0000000100000210
