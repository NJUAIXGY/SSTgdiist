    .option norvc
    .include "abi.inc"

    .section .text, "ax"
    .globl main

main:
    csrrwi x0, CSR_MSNN_EVENT_ENABLE, 7
    csrrs x8, CSR_MSNN_CMDQ_BASE, x0
    csrrs x9, CSR_MSNN_CMPQ_BASE, x0
    addi x1, x0, 1
    addi x21, x0, 2
    addi x22, x0, 2
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

    addi x20, x8, 64
    sd x2, 0(x20)
    sd x21, 8(x20)
    sd x0, 16(x20)
    sd x0, 24(x20)
    sd x0, 32(x20)
    sd x0, 40(x20)
    sd x0, 48(x20)
    sd x0, 56(x20)

    csrrw x0, CSR_MSNN_CMDQ_TAIL, x22
    wfi

    csrrs x3, CSR_MSNN_CMPQ_TAIL, x0
    bne x3, x1, fail
    lw x4, 0(x9)
    bne x4, x1, fail
    lw x5, 4(x9)
    bne x5, x0, fail
    lw x6, 8(x9)
    bne x6, x0, fail
    lw x7, 12(x9)
    bne x7, x0, fail
    csrrwi x0, CSR_MSNN_EVENT_PENDING, 7

    wfi

    csrrs x11, CSR_MSNN_CMDQ_HEAD, x0
    bne x11, x22, fail
    csrrs x12, CSR_MSNN_CMDQ_TAIL, x0
    bne x12, x22, fail
    csrrs x13, CSR_MSNN_CMPQ_HEAD, x0
    bne x13, x0, fail
    csrrs x14, CSR_MSNN_CMPQ_TAIL, x0
    bne x14, x1, fail
    csrrs x15, CSR_MSNN_STEP, x0
    bne x15, x22, fail
    csrrs x16, CSR_MSNN_FAULT, x0
    ld x17, 8(x10)
    bne x16, x17, fail
    lw x18, 0(x9)
    bne x18, x1, fail
    lw x19, 4(x9)
    bne x19, x0, fail
    csrrwi x0, CSR_MSNN_EVENT_PENDING, 7
    addi x7, x0, 0x91
    ebreak

fail:
    addi x7, x0, 0x92
    ebreak

    .section .rodata, "a"
descriptor_header:
    .quad 0x0000400000002001
    .quad 0x0000000100000211
