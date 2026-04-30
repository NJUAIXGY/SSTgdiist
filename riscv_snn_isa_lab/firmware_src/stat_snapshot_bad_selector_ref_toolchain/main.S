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
    ld x3, 8(x10)
    sd x2, 0(x8)
    sd x1, 8(x8)
    sd x3, 16(x8)
    sd x0, 24(x8)
    sd x0, 32(x8)
    sd x0, 40(x8)
    sd x0, 48(x8)
    sd x0, 56(x8)
    csrrw x0, CSR_MSNN_CMDQ_TAIL, x1
    wfi

    csrrs x4, CSR_MSNN_CMDQ_HEAD, x0
    bne x4, x1, fail
    csrrs x5, CSR_MSNN_CMPQ_TAIL, x0
    bne x5, x1, fail
    csrrs x6, CSR_MSNN_STEP, x0
    bne x6, x0, fail
    lw x7, 0(x9)
    bne x7, x1, fail
    lw x11, 4(x9)
    ld x12, 24(x10)
    bne x11, x12, fail
    lw x13, 8(x9)
    ld x14, 32(x10)
    bne x13, x14, fail
    lw x15, 12(x9)
    ld x16, 40(x10)
    bne x15, x16, fail
    csrrs x17, CSR_MSNN_FAULT, x0
    ld x18, 16(x10)
    bne x17, x18, fail
    csrrw x0, CSR_MSNN_CMPQ_HEAD, x5
    csrrwi x0, CSR_MSNN_EVENT_PENDING, 7
    addi x7, x0, 0xD1
    ebreak

fail:
    addi x7, x0, 0xD2
    ebreak

    .section .rodata, "a"
descriptor_header:
    .quad 0x0000400000005001
selector:
    .quad 0x55
expected_fault_csr:
    .quad 0x0000005500010106
expected_status:
    .quad 0x0000000000000206
expected_aux0:
    .quad 0x0000000000010106
expected_aux1:
    .quad 0x0000000000000055
