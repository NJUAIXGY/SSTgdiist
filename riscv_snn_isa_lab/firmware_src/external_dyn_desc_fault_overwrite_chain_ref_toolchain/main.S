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
    addi x22, x0, 3
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
    csrrw x0, CSR_MSNN_CMDQ_TAIL, x1
    wfi

    csrrs x3, CSR_MSNN_CMDQ_HEAD, x0
    bne x3, x1, fail
    csrrs x4, CSR_MSNN_CMPQ_TAIL, x0
    bne x4, x1, fail
    lw x6, 0(x9)
    bne x6, x1, fail
    lw x7, 4(x9)
    ld x11, 8(x10)
    bne x7, x11, fail
    lw x12, 8(x9)
    ld x13, 24(x10)
    bne x12, x13, fail
    lw x14, 12(x9)
    ld x15, 32(x10)
    bne x14, x15, fail
    csrrs x16, CSR_MSNN_FAULT, x0
    ld x17, 16(x10)
    bne x16, x17, fail

    csrrw x0, CSR_MSNN_CMPQ_HEAD, x4
    csrrwi x0, CSR_MSNN_EVENT_PENDING, 7
    csrrw x0, CSR_MSNN_FAULT, x0
    csrrs x18, CSR_MSNN_FAULT, x0
    bne x18, x0, fail

    addi x20, x8, 64
    addi x19, x9, 16
    ld x2, 40(x10)
    sd x2, 0(x20)
    sd x21, 8(x20)
    sd x0, 16(x20)
    sd x0, 24(x20)
    sd x0, 32(x20)
    sd x0, 40(x20)
    sd x0, 48(x20)
    sd x0, 56(x20)
    csrrw x0, CSR_MSNN_CMDQ_TAIL, x21
    wfi

    csrrs x3, CSR_MSNN_CMDQ_HEAD, x0
    bne x3, x21, fail
    csrrs x4, CSR_MSNN_CMPQ_TAIL, x0
    bne x4, x21, fail
    csrrs x5, CSR_MSNN_STEP, x0
    bne x5, x0, fail
    lw x6, 0(x19)
    bne x6, x21, fail
    lw x7, 4(x19)
    ld x11, 48(x10)
    bne x7, x11, fail
    lw x12, 8(x19)
    ld x13, 64(x10)
    bne x12, x13, fail
    lw x14, 12(x19)
    ld x15, 72(x10)
    bne x14, x15, fail
    csrrs x16, CSR_MSNN_FAULT, x0
    ld x17, 56(x10)
    bne x16, x17, fail

    csrrw x0, CSR_MSNN_CMPQ_HEAD, x4
    csrrwi x0, CSR_MSNN_EVENT_PENDING, 7
    csrrw x0, CSR_MSNN_FAULT, x0
    csrrs x18, CSR_MSNN_FAULT, x0
    bne x18, x0, fail

    addi x24, x8, 128
    addi x23, x9, 32
    ld x2, 80(x10)
    sd x2, 0(x24)
    sd x22, 8(x24)
    sd x0, 16(x24)
    sd x0, 24(x24)
    sd x0, 32(x24)
    sd x0, 40(x24)
    sd x0, 48(x24)
    sd x0, 56(x24)
    csrrw x0, CSR_MSNN_CMDQ_TAIL, x22
    wfi

    csrrs x3, CSR_MSNN_CMDQ_HEAD, x0
    bne x3, x22, fail
    csrrs x4, CSR_MSNN_CMPQ_TAIL, x0
    bne x4, x22, fail
    csrrs x5, CSR_MSNN_STEP, x0
    bne x5, x0, fail
    lw x6, 0(x23)
    bne x6, x22, fail
    lw x7, 4(x23)
    ld x11, 88(x10)
    bne x7, x11, fail
    lw x12, 8(x23)
    ld x13, 104(x10)
    bne x12, x13, fail
    lw x14, 12(x23)
    ld x15, 112(x10)
    bne x14, x15, fail
    csrrs x16, CSR_MSNN_FAULT, x0
    ld x17, 96(x10)
    bne x16, x17, fail

    csrrw x0, CSR_MSNN_CMPQ_HEAD, x4
    csrrwi x0, CSR_MSNN_EVENT_PENDING, 7
    addi x7, x0, 0x71
    ebreak

fail:
    addi x7, x0, 0x72
    ebreak

    .section .rodata, "a"
descriptor_header:
    .quad 0x0000400000042001
    .quad 0x0000000000000204
    .quad 0x0000000400000104
    .quad 0x0000000000000104
    .quad 0x0000000000000004
    .quad 0x0000400001002001
    .quad 0x0000000000000206
    .quad 0x0000400000010106
    .quad 0x0000000000010106
    .quad 0x0000000000004000
    .quad 0x0000400000042001
    .quad 0x0000000000000204
    .quad 0x0000000400020104
    .quad 0x0000000000020104
    .quad 0x0000000000000004
