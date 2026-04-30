    .option norvc
    .include "abi.inc"

    .section .text, "ax"
    .globl main

main:
    csrrwi x0, CSR_MSNN_EVENT_ENABLE, 7
    csrrs x8, CSR_MSNN_CMDQ_BASE, x0
    csrrs x9, CSR_MSNN_CMPQ_BASE, x0
    addi x1, x0, 1
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
    bne x3, x1, fail_head
    csrrs x4, CSR_MSNN_CMPQ_TAIL, x0
    bne x4, x1, fail_tail
    lw x5, 0(x9)
    bne x5, x1, fail_token
    lw x6, 4(x9)
    bne x6, x0, fail_status
    csrrw x0, CSR_MSNN_CMPQ_HEAD, x4
    csrrwi x0, CSR_MSNN_EVENT_PENDING, 7
    addi x7, x0, 0x33
    ebreak

fail_head:
    addi x7, x0, 0x21
    ebreak

fail_tail:
    addi x7, x0, 0x22
    ebreak

fail_token:
    addi x7, x0, 0x23
    ebreak

fail_status:
    addi x7, x0, 0x24
    ebreak

    .section .rodata, "a"
descriptor_header:
    .quad 0x0000400000002001
    .quad 0x0
