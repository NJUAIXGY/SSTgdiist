    .option norvc
    .section .text.crt0, "ax"
    .globl _start

_start:
    lui sp, 0xF
    jal x0, main
