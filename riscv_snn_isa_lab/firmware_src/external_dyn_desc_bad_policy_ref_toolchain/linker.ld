ENTRY(_start)

SECTIONS
{
  . = 0x8000;
  .text : {
    KEEP(*(.text.crt0))
    *(.text*)
  }

  . = 0x9000;
  .rodata : {
    *(.rodata*)
  }

  /DISCARD/ : {
    *(.comment*)
    *(.note*)
    *(.eh_frame*)
  }
}
