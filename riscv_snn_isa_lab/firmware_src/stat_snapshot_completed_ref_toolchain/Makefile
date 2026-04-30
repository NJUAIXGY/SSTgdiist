PROGRAM := stat_snapshot_completed_ref_toolchain
OUTPUT_ELF := ../../firmware/$(PROGRAM).elf
MAP_FILE := $(PROGRAM).map

RISCV_GCC := $(shell command -v riscv64-unknown-elf-gcc 2>/dev/null)
RISCV_GCC_ALT := $(shell command -v riscv64-elf-gcc 2>/dev/null)
CLANG := $(shell command -v clang 2>/dev/null)

ifeq ($(strip $(RISCV_GCC)),)
  ifeq ($(strip $(RISCV_GCC_ALT)),)
    ifeq ($(strip $(CLANG)),)
      $(error no supported RISC-V bare-metal toolchain found)
    endif
    CC := $(CLANG)
    TOOLCHAIN_DESC := clang --target=riscv64-unknown-elf
    COMMON_FLAGS := --target=riscv64-unknown-elf -fuse-ld=lld
  else
    CC := $(RISCV_GCC_ALT)
    TOOLCHAIN_DESC := riscv64-elf-gcc
    COMMON_FLAGS :=
  endif
else
  CC := $(RISCV_GCC)
  TOOLCHAIN_DESC := riscv64-unknown-elf-gcc
  COMMON_FLAGS :=
endif

ARCH_FLAGS := -march=rv64im_zicsr -mabi=lp64
LINK_FLAGS := -nostdlib -ffreestanding -Wl,-T,linker.ld -Wl,-Map,$(MAP_FILE)
SRC := crt0.S main.S

.PHONY: all clean info

all: $(OUTPUT_ELF)

info:
	@echo "toolchain=$(TOOLCHAIN_DESC)"

$(OUTPUT_ELF): $(SRC) linker.ld
	@mkdir -p "$(@D)"
	$(CC) $(COMMON_FLAGS) $(ARCH_FLAGS) $(LINK_FLAGS) $(SRC) -o "$@"

clean:
	rm -f "$(OUTPUT_ELF)" "$(MAP_FILE)"
