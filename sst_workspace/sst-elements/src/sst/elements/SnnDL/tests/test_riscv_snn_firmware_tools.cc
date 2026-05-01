// -*- c++ -*-

#include "workload/riscv_snn/RiscvSnnAbi.h"
#include "workload/riscv_snn/RiscvSnnAsm.h"
#include "workload/riscv_snn/RiscvSnnElfWriter.h"
#include "workload/riscv_snn/RiscvSnnFirmwareLoader.h"
#include "workload/riscv_snn/RiscvSnnSampleFirmware.h"

#include <cassert>
#include <cstdio>
#include <string>
#include <unistd.h>
#include <vector>

namespace {

uint64_t readLe64(const std::vector<uint8_t>& bytes, size_t offset) {
    assert(offset + 8 <= bytes.size());
    uint64_t value = 0;
    for (size_t i = 0; i < 8; ++i) {
        value |= static_cast<uint64_t>(bytes[offset + i]) << (i * 8);
    }
    return value;
}

} // namespace

int main() {
    using namespace SST::SnnDL::riscv_snn;

    constexpr uint64_t kExpectedStatSnapshotSelector =
        static_cast<uint64_t>(kStatSnapshotSelectorAcceptedCommands);
    constexpr uint64_t kExpectedStatSnapshotHeader = encodeDescriptorHeader(
        /*version=*/1,
        CommandOpcode::StatSnapshot,
        /*flags=*/0,
        /*completion_policy=*/0,
        /*error_policy=*/0,
        static_cast<uint8_t>(kCommandDescriptorBytes));

    assert(asmv1::encodeAddi(/*rd=*/1, /*rs1=*/0, /*imm=*/5) == 0x00500093u);
    assert(asmv1::encodeCsrrwi(/*rd=*/0, kCsrMsnnEventEnable, /*zimm=*/0x7) == 0xbd83d073u);
    assert(asmv1::encodeEbreak() == 0x00100073u);

    std::vector<uint8_t> text;
    asmv1::appendInsn32(text, asmv1::encodeAddi(/*rd=*/1, /*rs1=*/0, /*imm=*/5));
    asmv1::appendInsn32(text, asmv1::encodeEbreak());

    char path_template[] = "/tmp/riscv_snn_tools_XXXXXX";
    const int fd = mkstemp(path_template);
    assert(fd >= 0);
    close(fd);

    RiscvSnnElfLoadSegment seg;
    seg.vaddr = 0x1000;
    seg.flags = 0x5;
    seg.file_data = text;
    seg.mem_size = 12;

    std::string error;
    assert(writeElf64Image(path_template, /*entry_pc=*/0x1000, {seg}, error));
    assert(error.empty());

    RiscvSnnMemoryImage image;
    assert(RiscvSnnFirmwareLoader::loadElf64(path_template, image, error));
    assert(error.empty());
    assert(image.entry_pc == 0x1000);
    assert(image.segments.size() == 1);
    assert(image.segments[0].vaddr == 0x1000);
    assert(image.segments[0].flags == 0x5u);
    assert(image.segments[0].data.size() == 12u);
    assert(image.segments[0].data[0] == 0x93u);
    assert(image.segments[0].data[4] == 0x73u);
    assert(image.segments[0].data[8] == 0x00u);

    RiscvSnnSampleProgram sample_program;
    const auto& sample_names = sampleFirmwareProgramNames();
    assert(sample_names.size() == 14u);
    assert(std::string(sample_names[0]) == "external_p0");
    assert(std::string(sample_names[1]) == "external_dyn_desc");
    assert(std::string(sample_names[2]) == "external_dyn_desc_ref");
    assert(std::string(sample_names[3]) == "external_dyn_desc_fault_ref");
    assert(std::string(sample_names[4]) == "external_dyn_desc_bad_policy_ref");
    assert(std::string(sample_names[5]) == "external_dyn_desc_fault_rearm_ref");
    assert(std::string(sample_names[6]) == "external_dyn_desc_fault_overwrite_chain_ref");
    assert(std::string(sample_names[7]) == "barrier_wfi_order_ref");
    assert(std::string(sample_names[8]) == "queue_backpressure_ref");
    assert(std::string(sample_names[9]) == "completion_queue_overflow_ref");
    assert(std::string(sample_names[10]) == "stat_snapshot_ref");
    assert(std::string(sample_names[11]) == "stat_snapshot_completed_ref");
    assert(std::string(sample_names[12]) == "stat_snapshot_provider_bound_ref");
    assert(std::string(sample_names[13]) == "stat_snapshot_bad_selector_ref");
    std::vector<RiscvSnnSampleMetadata> metadata = sampleFirmwareMetadata();
    assert(metadata.size() == 14u);
    assert(metadata[0].canonical_sample);
    assert(metadata[1].canonical_sample);
    assert(!metadata[2].canonical_sample);
    assert(!metadata[3].canonical_sample);
    assert(!metadata[4].canonical_sample);
    assert(!metadata[5].canonical_sample);
    assert(!metadata[6].canonical_sample);
    assert(!metadata[7].canonical_sample);
    assert(!metadata[8].canonical_sample);
    assert(!metadata[9].canonical_sample);
    assert(!metadata[10].canonical_sample);
    assert(!metadata[11].canonical_sample);
    assert(!metadata[12].canonical_sample);
    assert(!metadata[13].canonical_sample);
    assert(metadata[2].program == "external_dyn_desc_ref");
    assert(metadata[2].descriptor_source == "runtime_store_to_ring");
    assert(metadata[2].completion_visibility == "cmpq_tail_then_payload_read_then_cmpq_ack");
    assert(metadata[2].memory_image_shape == "text_at_0x8000_rodata_at_0x9000");
    assert(metadata[3].program == "external_dyn_desc_fault_ref");
    assert(metadata[3].descriptor_source == "runtime_store_to_ring");
    assert(
        metadata[3].completion_visibility ==
        "cmpq_tail_then_fault_payload_then_msnnfault_then_cmpq_ack");
    assert(metadata[3].memory_image_shape == "text_at_0x8000_rodata_at_0x9000");
    assert(metadata[4].program == "external_dyn_desc_bad_policy_ref");
    assert(metadata[4].descriptor_source == "runtime_store_to_ring");
    assert(
        metadata[4].completion_visibility ==
        "cmpq_tail_then_bad_policy_payload_then_msnnstep_and_msnnfault_then_cmpq_ack");
    assert(metadata[4].memory_image_shape == "text_at_0x8000_rodata_at_0x9000");
    assert(metadata[5].program == "external_dyn_desc_fault_rearm_ref");
    assert(metadata[5].descriptor_source == "runtime_store_to_ring");
    assert(
        metadata[5].completion_visibility ==
        "fault1_visible_then_msnnfault_clear_then_fault2_visible_then_cmpq_ack");
    assert(metadata[5].memory_image_shape == "text_at_0x8000_rodata_at_0x9000");
    assert(metadata[6].program == "external_dyn_desc_fault_overwrite_chain_ref");
    assert(metadata[6].descriptor_source == "runtime_store_to_ring");
    assert(
        metadata[6].completion_visibility ==
        "fault1_visible_then_msnnfault_clear_then_fault2_visible_then_msnnfault_clear_then_fault3_visible_then_cmpq_ack");
    assert(metadata[6].memory_image_shape == "text_at_0x8000_rodata_at_0x9000");
    assert(metadata[7].program == "barrier_wfi_order_ref");
    assert(metadata[7].descriptor_source == "runtime_store_to_ring");
    assert(
        metadata[7].completion_visibility ==
        "wfi_then_cmpq_tail_then_quiescent_step_event_fault_checks");
    assert(metadata[7].memory_image_shape == "text_at_0x8000_rodata_at_0x9000");
    assert(metadata[8].program == "queue_backpressure_ref");
    assert(metadata[8].descriptor_source == "runtime_store_to_ring");
    assert(metadata[8].completion_visibility == "fault_wakeup_before_cmpq_visibility");
    assert(metadata[8].memory_image_shape == "text_at_0x8000_rodata_at_0x9000");
    assert(metadata[9].program == "completion_queue_overflow_ref");
    assert(metadata[9].descriptor_source == "runtime_store_to_ring");
    assert(
        metadata[9].completion_visibility ==
        "cmpq_visible_then_event_clear_then_fault_wakeup_without_cmpq_ack");
    assert(metadata[9].memory_image_shape == "text_at_0x8000_rodata_at_0x9000");
    assert(metadata[10].program == "stat_snapshot_ref");
    assert(metadata[10].descriptor_source == "runtime_store_to_ring");
    assert(
        metadata[10].completion_visibility ==
        "cmpq_tail_then_status_then_aux_selector_then_cmpq_ack");
    assert(metadata[10].memory_image_shape == "text_at_0x8000_rodata_at_0x9000");
    assert(metadata[11].program == "stat_snapshot_completed_ref");
    assert(metadata[11].descriptor_source == "runtime_store_to_ring");
    assert(
        metadata[11].completion_visibility ==
        "completion1_ack_then_cmpq_tail_then_status_then_aux_selector_then_cmpq_ack");
    assert(metadata[11].memory_image_shape == "text_at_0x8000_rodata_at_0x9000");
    assert(metadata[12].program == "stat_snapshot_provider_bound_ref");
    assert(metadata[12].descriptor_source == "runtime_store_to_ring");
    assert(
        metadata[12].completion_visibility ==
        "cmpq_tail_then_status_then_aux_provider_bound_then_cmpq_ack");
    assert(metadata[12].memory_image_shape == "text_at_0x8000_rodata_at_0x9000");
    assert(metadata[13].program == "stat_snapshot_bad_selector_ref");
    assert(metadata[13].descriptor_source == "runtime_store_to_ring");
    assert(
        metadata[13].completion_visibility ==
        "cmpq_tail_then_fault_status_then_msnnfault_then_cmpq_ack");
    assert(metadata[13].memory_image_shape == "text_at_0x8000_rodata_at_0x9000");
    assert(buildSampleFirmwareProgram("external_p0", sample_program, error));
    assert(error.empty());
    assert(sample_program.entry_pc == 0x8000u);
    assert(sample_program.segments.size() == 2u);
    assert(sample_program.segments[0].vaddr == 0x0u);
    assert(sample_program.segments[0].flags == 0x6u);
    assert(sample_program.segments[0].file_data.size() == kCommandDescriptorBytes);
    assert(sample_program.segments[1].vaddr == 0x8000u);
    assert(sample_program.segments[1].flags == 0x5u);

    RiscvSnnSampleProgram dyn_program;
    assert(buildSampleFirmwareProgram("external_dyn_desc", dyn_program, error));
    assert(error.empty());
    assert(dyn_program.entry_pc == 0x8000u);
    assert(dyn_program.segments.size() == 1u);
    assert(dyn_program.segments[0].vaddr == 0x8000u);
    assert(dyn_program.segments[0].flags == 0x5u);
    assert(!dyn_program.segments[0].file_data.empty());

    RiscvSnnSampleProgram ref_program;
    assert(buildSampleFirmwareProgram("external_dyn_desc_ref", ref_program, error));
    assert(error.empty());
    assert(ref_program.entry_pc == 0x8000u);
    assert(ref_program.segments.size() == 2u);
    assert(ref_program.segments[0].vaddr == 0x8000u);
    assert(ref_program.segments[0].flags == 0x5u);
    assert(ref_program.segments[1].vaddr == 0x9000u);
    assert(ref_program.segments[1].flags == 0x4u);
    assert(ref_program.segments[1].file_data.size() >= 16u);

    RiscvSnnSampleProgram fault_program;
    assert(buildSampleFirmwareProgram("external_dyn_desc_fault_ref", fault_program, error));
    assert(error.empty());
    assert(fault_program.entry_pc == 0x8000u);
    assert(fault_program.segments.size() == 2u);
    assert(fault_program.segments[0].vaddr == 0x8000u);
    assert(fault_program.segments[0].flags == 0x5u);
    assert(fault_program.segments[1].vaddr == 0x9000u);
    assert(fault_program.segments[1].flags == 0x4u);
    assert(fault_program.segments[1].file_data.size() >= 40u);

    RiscvSnnSampleProgram bad_policy_program;
    assert(buildSampleFirmwareProgram("external_dyn_desc_bad_policy_ref", bad_policy_program, error));
    assert(error.empty());
    assert(bad_policy_program.entry_pc == 0x8000u);
    assert(bad_policy_program.segments.size() == 2u);
    assert(bad_policy_program.segments[0].vaddr == 0x8000u);
    assert(bad_policy_program.segments[0].flags == 0x5u);
    assert(bad_policy_program.segments[1].vaddr == 0x9000u);
    assert(bad_policy_program.segments[1].flags == 0x4u);
    assert(bad_policy_program.segments[1].file_data.size() >= 40u);

    RiscvSnnSampleProgram stat_snapshot_bad_selector_program;
    assert(buildSampleFirmwareProgram(
        "stat_snapshot_bad_selector_ref",
        stat_snapshot_bad_selector_program,
        error));
    assert(error.empty());
    assert(stat_snapshot_bad_selector_program.entry_pc == 0x8000u);
    assert(stat_snapshot_bad_selector_program.segments.size() == 2u);
    assert(stat_snapshot_bad_selector_program.segments[0].vaddr == 0x8000u);
    assert(stat_snapshot_bad_selector_program.segments[0].flags == 0x5u);
    assert(stat_snapshot_bad_selector_program.segments[1].vaddr == 0x9000u);
    assert(stat_snapshot_bad_selector_program.segments[1].flags == 0x4u);
    assert(stat_snapshot_bad_selector_program.segments[1].file_data.size() >= 48u);

    RiscvSnnSampleProgram fault_rearm_program;
    assert(buildSampleFirmwareProgram("external_dyn_desc_fault_rearm_ref", fault_rearm_program, error));
    assert(error.empty());
    assert(fault_rearm_program.entry_pc == 0x8000u);
    assert(fault_rearm_program.segments.size() == 2u);
    assert(fault_rearm_program.segments[0].vaddr == 0x8000u);
    assert(fault_rearm_program.segments[0].flags == 0x5u);
    assert(fault_rearm_program.segments[1].vaddr == 0x9000u);
    assert(fault_rearm_program.segments[1].flags == 0x4u);
    assert(fault_rearm_program.segments[1].file_data.size() >= 80u);

    RiscvSnnSampleProgram fault_overwrite_chain_program;
    assert(buildSampleFirmwareProgram("external_dyn_desc_fault_overwrite_chain_ref", fault_overwrite_chain_program, error));
    assert(error.empty());
    assert(fault_overwrite_chain_program.entry_pc == 0x8000u);
    assert(fault_overwrite_chain_program.segments.size() == 2u);
    assert(fault_overwrite_chain_program.segments[0].vaddr == 0x8000u);
    assert(fault_overwrite_chain_program.segments[0].flags == 0x5u);
    assert(fault_overwrite_chain_program.segments[1].vaddr == 0x9000u);
    assert(fault_overwrite_chain_program.segments[1].flags == 0x4u);
    assert(fault_overwrite_chain_program.segments[1].file_data.size() >= 120u);

    RiscvSnnSampleProgram completion_queue_overflow_program;
    assert(buildSampleFirmwareProgram("completion_queue_overflow_ref", completion_queue_overflow_program, error));
    assert(error.empty());
    assert(completion_queue_overflow_program.entry_pc == 0x8000u);
    assert(completion_queue_overflow_program.segments.size() == 2u);
    assert(completion_queue_overflow_program.segments[0].vaddr == 0x8000u);
    assert(completion_queue_overflow_program.segments[0].flags == 0x5u);
    assert(completion_queue_overflow_program.segments[1].vaddr == 0x9000u);
    assert(completion_queue_overflow_program.segments[1].flags == 0x4u);
    assert(completion_queue_overflow_program.segments[1].file_data.size() >= 16u);

    RiscvSnnSampleProgram stat_snapshot_program;
    assert(buildSampleFirmwareProgram("stat_snapshot_ref", stat_snapshot_program, error));
    assert(error.empty());
    assert(stat_snapshot_program.entry_pc == 0x8000u);
    assert(stat_snapshot_program.segments.size() == 2u);
    assert(stat_snapshot_program.segments[0].vaddr == 0x8000u);
    assert(stat_snapshot_program.segments[0].flags == 0x5u);
    assert(!stat_snapshot_program.segments[0].file_data.empty());
    assert(stat_snapshot_program.segments[1].vaddr == 0x9000u);
    assert(stat_snapshot_program.segments[1].flags == 0x4u);
    assert(stat_snapshot_program.segments[1].file_data.size() == 24u);
    assert(readLe64(stat_snapshot_program.segments[1].file_data, 0) == kExpectedStatSnapshotHeader);
    assert(
        readLe64(stat_snapshot_program.segments[1].file_data, 8) ==
        kExpectedStatSnapshotSelector);
    assert(readLe64(stat_snapshot_program.segments[1].file_data, 16) == 1u);

    RiscvSnnSampleProgram stat_snapshot_completed_program;
    assert(buildSampleFirmwareProgram(
        "stat_snapshot_completed_ref",
        stat_snapshot_completed_program,
        error));
    assert(error.empty());
    assert(stat_snapshot_completed_program.entry_pc == 0x8000u);
    assert(stat_snapshot_completed_program.segments.size() == 2u);
    assert(stat_snapshot_completed_program.segments[0].vaddr == 0x8000u);
    assert(stat_snapshot_completed_program.segments[0].flags == 0x5u);
    assert(!stat_snapshot_completed_program.segments[0].file_data.empty());
    assert(stat_snapshot_completed_program.segments[1].vaddr == 0x9000u);
    assert(stat_snapshot_completed_program.segments[1].flags == 0x4u);
    assert(stat_snapshot_completed_program.segments[1].file_data.size() == 32u);
    assert(
        readLe64(stat_snapshot_completed_program.segments[1].file_data, 8) ==
        kExpectedStatSnapshotHeader);
    assert(
        readLe64(stat_snapshot_completed_program.segments[1].file_data, 16) ==
        static_cast<uint64_t>(kStatSnapshotSelectorCompletedCommands));
    assert(readLe64(stat_snapshot_completed_program.segments[1].file_data, 24) == 1u);

    RiscvSnnSampleProgram stat_snapshot_provider_bound_program;
    assert(buildSampleFirmwareProgram(
        "stat_snapshot_provider_bound_ref",
        stat_snapshot_provider_bound_program,
        error));
    assert(error.empty());
    assert(stat_snapshot_provider_bound_program.entry_pc == 0x8000u);
    assert(stat_snapshot_provider_bound_program.segments.size() == 2u);
    assert(stat_snapshot_provider_bound_program.segments[0].vaddr == 0x8000u);
    assert(stat_snapshot_provider_bound_program.segments[0].flags == 0x5u);
    assert(!stat_snapshot_provider_bound_program.segments[0].file_data.empty());
    assert(stat_snapshot_provider_bound_program.segments[1].vaddr == 0x9000u);
    assert(stat_snapshot_provider_bound_program.segments[1].flags == 0x4u);
    assert(stat_snapshot_provider_bound_program.segments[1].file_data.size() == 24u);
    assert(
        readLe64(stat_snapshot_provider_bound_program.segments[1].file_data, 0) ==
        kExpectedStatSnapshotHeader);
    assert(
        readLe64(stat_snapshot_provider_bound_program.segments[1].file_data, 8) ==
        static_cast<uint64_t>(kStatSnapshotSelectorProviderBound));
    assert(readLe64(stat_snapshot_provider_bound_program.segments[1].file_data, 16) == 1u);

    std::remove(path_template);
    return 0;
}
