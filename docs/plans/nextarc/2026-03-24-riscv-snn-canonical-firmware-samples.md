# RISC-V SNN Canonical Firmware Samples

**Status:** Experimental but frozen for the current `riscv_snn` line

**Purpose:** Freeze the minimal canonical sample set used by `riscv_snn` firmware generation, smoke specs, and protocol-level regression tests so future sample additions do not silently redefine the control-plane boundary. Metadata authority now lives in the private `riscv_snn` sample-builder path, and external tooling should query it rather than re-declaring sample semantics.

## Canonical Sample Set

### `external_p0`

- Role: legacy external firmware sample
- Descriptor source: prebuilt data segment
- Completion boundary: `wfi` wakeup followed by completion queue acknowledge
- Memory image shape:
  - one RW data segment at `vaddr=0x0`
  - one RX text segment at `vaddr=0x8000`
- Architectural intent:
  - represent the earliest external control-plane loop
  - preserve compatibility with the old “prebuilt descriptor” smoke path
- What it is good for:
  - validating firmware loading
  - validating queue doorbell / `wfi` / completion acknowledge plumbing
  - preserving backward comparability with early external-firmware experiments
- What it must not be used to claim:
  - runtime descriptor construction
  - status-load driven branch semantics

### `external_dyn_desc`

- Role: canonical runtime-descriptor external firmware sample
- Descriptor source: runtime stores into local memory ring
- Completion boundary: `wfi` wakeup, completion status load, branch on status, then completion queue acknowledge
- Memory image shape:
  - one RX text segment at `vaddr=0x8000`
- Architectural intent:
  - represent the first sample where firmware itself constructs and submits a `FUSED_STEP` descriptor
  - act as the preferred control-plane sample for current ISA bring-up
- What it is good for:
  - validating runtime descriptor construction
  - validating CSR + ring + status-load + branch control flow
  - serving as the default external smoke sample for current `riscv_snn` experiments
- What it must not be used to claim:
  - general-purpose firmware ABI completeness
  - real toolchain integration

## Additive Reference Samples

### `external_dyn_desc_ref`

- Role: additive non-canonical bit-level reference sample
- Descriptor source: runtime stores into local memory ring
- Completion boundary:
  - `wfi` wakeup
  - read `cmdq_head`
  - read `cmpq_tail`
  - read completion payload
  - acknowledge `cmpq_head`
- Memory image shape:
  - one RX text segment at `vaddr=0x8000`
  - one RO data segment at `vaddr=0x9000`
- Architectural intent:
  - encode the v1.1 control-plane ordering rules more explicitly than `external_dyn_desc`
  - act as a reference sample for bit-level queue/doorbell/completion-policy work
- What it is good for:
  - validating queue base CSR reads
  - validating `cmdq_tail` as the only architectural doorbell
  - validating `cmdq_head` / `cmpq_tail` / completion payload visibility ordering
- What it must not be used to claim:
  - promotion into canonical compatibility baseline
  - general-purpose firmware ABI completeness

### `external_dyn_desc_fault_ref`

- Role: additive non-canonical fault-alignment reference sample
- Descriptor source: runtime stores into local memory ring
- Completion boundary:
  - `wfi` wakeup
  - read `cmdq_head`
  - read `cmpq_tail`
  - read completion payload
  - read `msnnfault`
  - acknowledge `cmpq_head`
- Memory image shape:
  - one RX text segment at `vaddr=0x8000`
  - one RO data segment at `vaddr=0x9000`
- Architectural intent:
  - freeze the accepted-then-fault path for reserved descriptor flag bits
  - make completion payload and `msnnfault` alignment observable in firmware
- What it is good for:
  - validating strict reserved-flag fault handling
  - validating `aux0/aux1` and `msnnfault` consistency
  - validating fault visibility before software acknowledge
- What it must not be used to claim:
  - promotion into canonical compatibility baseline
  - general-purpose fault taxonomy completeness

### `external_dyn_desc_bad_policy_ref`

- Role: additive non-canonical bad-policy / no-progress reference sample
- Descriptor source: runtime stores into local memory ring
- Completion boundary:
  - `wfi` wakeup
  - read `cmdq_head`
  - read `cmpq_tail`
  - read completion payload
  - read `msnnstep`
  - read `msnnfault`
  - acknowledge `cmpq_head`
- Memory image shape:
  - one RX text segment at `vaddr=0x8000`
  - one RO data segment at `vaddr=0x9000`
- Architectural intent:
  - freeze the illegal policy path without silently redefining the canonical samples
  - show that bad-policy completion is visible while `msnnstep` still reports no committed progress
- What it is good for:
  - validating `completion_policy/error_policy` strictness
  - validating no-progress observation via `msnnstep==0`
  - validating `msnnfault` visibility on policy faults
- What it must not be used to claim:
  - promotion into canonical compatibility baseline
  - real toolchain integration

## Toolchain Bridge Artifact

### `external_dyn_desc_ref_toolchain`

- Role: lab-local bare-metal toolchain bridge artifact
- Source of truth:
  - `/home/xgy/remote/riscv_snn_isa_lab/firmware_src/external_dyn_desc_ref_toolchain`
- Purpose:
  - prove that a real bare-metal assembler/linker flow can target the same control-plane contract as `external_dyn_desc_ref`
- Important boundary:
  - it is **not** part of the sample-builder authority
  - it is **not** part of the canonical compatibility baseline
  - it exists to compare builder vs toolchain execution evidence without redefining sample metadata ownership

## Stability Rules

- The canonical sample set is currently exactly:
  - `external_p0`
  - `external_dyn_desc`
- `external_dyn_desc_ref`, `external_dyn_desc_fault_ref`, and `external_dyn_desc_bad_policy_ref` are intentionally additive and do not expand the canonical compatibility baseline.
- `external_dyn_desc_ref_toolchain` is a toolchain bridge artifact and also does not expand the canonical compatibility baseline.
- Any new sample must not silently replace the meaning of either canonical sample.
- If a new sample is added, it should be described as additive and given a new name.
- Byte-exact compatibility with already published smoke artifacts is desirable for canonical samples when practical.
- Sample metadata should be sourced from the private `riscv_snn` sample builder and emitter, not hand-maintained in external tooling.
- Sample generation logic must stay on the experimental path:
  - `sst_dram_si/tools/generate_riscv_snn_firmware.py`
  - `SnnDL/tools/riscv_snn_emit_sample_firmware.cc`
  - `services/workload/riscv_snn/RiscvSnnSampleFirmware.h`

## Non-Goals

- This note does not freeze a full firmware ABI.
- This note does not define real RISC-V toolchain integration.
- This note does not require the main `snn` workload path to consume any of these sample-generation utilities.
