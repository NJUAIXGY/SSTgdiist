.section .text
.align 4
.global _start
_start:
  addi x10, x0, 42
  mv x11, x10
  ebreak
