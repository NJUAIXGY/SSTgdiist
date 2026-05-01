// -*- c++ -*-
//
// RiscvSnnSampleFirmware:
// - `riscv_snn` 实验主线私有的 sample firmware builder + metadata authority。
// - 统一维护 sample 列表、稳定元信息与镜像拼装语义，避免 emitter/Python/测试再分叉。
//

#pragma once

#include "workload/riscv_snn/RiscvSnnAbi.h"
#include "workload/riscv_snn/RiscvSnnAsm.h"
#include "workload/riscv_snn/RiscvSnnElfWriter.h"

#include <cstdint>
#include <string>
#include <vector>

namespace SST { namespace SnnDL { namespace riscv_snn {

struct RiscvSnnSampleProgram {
    uint64_t entry_pc = 0;
    std::vector<RiscvSnnElfLoadSegment> segments{};
};

struct RiscvSnnSampleMetadata {
    std::string program{};
    bool canonical_sample = false;
    std::string description{};
    std::string descriptor_source{};
    std::string completion_visibility{};
    std::string architectural_boundary{};
    std::string memory_image_shape{};
    std::vector<std::string> notes{};
};

namespace samplefwv1 {

constexpr uint64_t kExternalDynDescTextBase = 0x8000;
constexpr uint64_t kExternalDynDescRefTextBase = 0x8000;
constexpr uint64_t kExternalDynDescRefRodataBase = 0x9000;
constexpr uint64_t kExternalDynDescRefDescriptorToken = 1;
constexpr uint64_t kExternalDynDescRefDescriptorHeader = encodeDescriptorHeader(
    /*version=*/1,
    CommandOpcode::FusedStep,
    /*flags=*/0,
    /*completion_policy=*/0,
    /*error_policy=*/0,
    static_cast<uint8_t>(kCommandDescriptorBytes));
constexpr int32_t kExternalDynDescRefSuccessCode = 0x33;
constexpr int32_t kExternalDynDescRefFailHeadCode = 0x21;
constexpr int32_t kExternalDynDescRefFailTailCode = 0x22;
constexpr int32_t kExternalDynDescRefFailTokenCode = 0x23;
constexpr int32_t kExternalDynDescRefFailStatusCode = 0x24;
constexpr uint64_t kExternalDynDescFaultRefTextBase = 0x8000;
constexpr uint64_t kExternalDynDescFaultRefRodataBase = 0x9000;
constexpr uint64_t kExternalDynDescFaultRefDescriptorHeader = encodeDescriptorHeader(
    /*version=*/1,
    CommandOpcode::FusedStep,
    /*flags=*/0x4,
    /*completion_policy=*/0,
    /*error_policy=*/0,
    static_cast<uint8_t>(kCommandDescriptorBytes));
constexpr uint32_t kExternalDynDescFaultRefExpectedStatus = encodeStatusCode(
    CompletionPrimaryStatus::BadFlags,
    CompletionSeverity::FaultAfterAccept);
constexpr uint64_t kExternalDynDescFaultRefExpectedFaultCsr = makeFaultCsrFromStatus(
    kExternalDynDescFaultRefExpectedStatus,
    /*slot=*/0,
    /*aux=*/descriptorReservedFlagBits(kExternalDynDescFaultRefDescriptorHeader));
constexpr int32_t kExternalDynDescFaultRefSuccessCode = 0x41;
constexpr int32_t kExternalDynDescFaultRefFailCode = 0x42;
constexpr uint64_t kExternalDynDescBadPolicyRefTextBase = 0x8000;
constexpr uint64_t kExternalDynDescBadPolicyRefRodataBase = 0x9000;
constexpr uint64_t kExternalDynDescBadPolicyRefDescriptorHeader = encodeDescriptorHeader(
    /*version=*/1,
    CommandOpcode::FusedStep,
    /*flags=*/0,
    /*completion_policy=*/1,
    /*error_policy=*/0,
    static_cast<uint8_t>(kCommandDescriptorBytes));
constexpr uint32_t kExternalDynDescBadPolicyRefExpectedStatus = encodeStatusCode(
    CompletionPrimaryStatus::BadPolicy,
    CompletionSeverity::FaultAfterAccept);
constexpr uint64_t kExternalDynDescBadPolicyRefExpectedFaultCsr = makeFaultCsrFromStatus(
    kExternalDynDescBadPolicyRefExpectedStatus,
    /*slot=*/0,
    /*aux=*/static_cast<uint32_t>(kExternalDynDescBadPolicyRefDescriptorHeader >> 32));
constexpr int32_t kExternalDynDescBadPolicyRefSuccessCode = 0x51;
constexpr int32_t kExternalDynDescBadPolicyRefFailCode = 0x52;
constexpr uint64_t kExternalDynDescFaultRearmRefTextBase = 0x8000;
constexpr uint64_t kExternalDynDescFaultRearmRefRodataBase = 0x9000;
constexpr uint64_t kExternalDynDescFaultRearmRefFirstDescriptorHeader =
    kExternalDynDescFaultRefDescriptorHeader;
constexpr uint64_t kExternalDynDescFaultRearmRefSecondDescriptorHeader =
    kExternalDynDescBadPolicyRefDescriptorHeader;
constexpr uint64_t kExternalDynDescFaultRearmRefSecondExpectedFaultCsr = makeFaultCsrFromStatus(
    kExternalDynDescBadPolicyRefExpectedStatus,
    /*slot=*/1,
    /*aux=*/static_cast<uint32_t>(kExternalDynDescFaultRearmRefSecondDescriptorHeader >> 32));
constexpr int32_t kExternalDynDescFaultRearmRefSuccessCode = 0x61;
constexpr int32_t kExternalDynDescFaultRearmRefFailCode = 0x62;
constexpr uint64_t kExternalDynDescFaultOverwriteChainRefTextBase = 0x8000;
constexpr uint64_t kExternalDynDescFaultOverwriteChainRefRodataBase = 0x9000;
constexpr uint64_t kExternalDynDescFaultOverwriteChainRefFirstDescriptorHeader =
    kExternalDynDescFaultRefDescriptorHeader;
constexpr uint64_t kExternalDynDescFaultOverwriteChainRefSecondDescriptorHeader =
    kExternalDynDescBadPolicyRefDescriptorHeader;
constexpr uint64_t kExternalDynDescFaultOverwriteChainRefThirdDescriptorHeader =
    kExternalDynDescFaultRefDescriptorHeader;
constexpr uint64_t kExternalDynDescFaultOverwriteChainRefSecondExpectedFaultCsr =
    makeFaultCsrFromStatus(
        kExternalDynDescBadPolicyRefExpectedStatus,
        /*slot=*/1,
        /*aux=*/static_cast<uint32_t>(kExternalDynDescFaultOverwriteChainRefSecondDescriptorHeader >> 32));
constexpr uint64_t kExternalDynDescFaultOverwriteChainRefThirdExpectedFaultCsr =
    makeFaultCsrFromStatus(
        kExternalDynDescFaultRefExpectedStatus,
        /*slot=*/2,
        /*aux=*/descriptorReservedFlagBits(kExternalDynDescFaultOverwriteChainRefThirdDescriptorHeader));
constexpr int32_t kExternalDynDescFaultOverwriteChainRefSuccessCode = 0x71;
constexpr int32_t kExternalDynDescFaultOverwriteChainRefFailCode = 0x72;
constexpr uint64_t kBarrierWfiOrderRefTextBase = 0x8000;
constexpr uint64_t kBarrierWfiOrderRefRodataBase = 0x9000;
constexpr uint64_t kBarrierWfiOrderRefDescriptorHeader = 0x0000400001002001ULL;
constexpr uint64_t kBarrierWfiOrderRefExpectedToken = 1;
constexpr int32_t kBarrierWfiOrderRefSuccessCode = 0x51;
constexpr int32_t kBarrierWfiOrderRefFailCode = 0x52;
constexpr uint64_t kQueueBackpressureRefTextBase = 0x8000;
constexpr uint64_t kQueueBackpressureRefRodataBase = 0x9000;
constexpr uint64_t kQueueBackpressureRefDescriptorHeader = kExternalDynDescRefDescriptorHeader;
constexpr uint32_t kQueueBackpressureRefExpectedStatus = encodeStatusCode(
    CompletionPrimaryStatus::CommandQueueOverflow,
    CompletionSeverity::FaultAfterAccept);
constexpr uint64_t kQueueBackpressureRefExpectedFaultCsr = makeFaultCsrFromStatus(
    kQueueBackpressureRefExpectedStatus,
    /*slot=*/0,
    /*aux=*/1);
constexpr int32_t kQueueBackpressureRefSuccessCode = 0x81;
constexpr int32_t kQueueBackpressureRefFailCode = 0x82;
constexpr uint64_t kCompletionQueueOverflowRefTextBase = 0x8000;
constexpr uint64_t kCompletionQueueOverflowRefRodataBase = 0x9000;
constexpr uint64_t kCompletionQueueOverflowRefDescriptorHeader = kExternalDynDescRefDescriptorHeader;
constexpr uint32_t kCompletionQueueOverflowRefExpectedStatus = encodeStatusCode(
    CompletionPrimaryStatus::CompletionQueueOverflow,
    CompletionSeverity::FaultAfterAccept);
constexpr uint64_t kCompletionQueueOverflowRefExpectedFaultCsr = makeFaultCsrFromStatus(
    kCompletionQueueOverflowRefExpectedStatus,
    /*slot=*/0,
    /*aux=*/1);
constexpr int32_t kCompletionQueueOverflowRefSuccessCode = 0x91;
constexpr int32_t kCompletionQueueOverflowRefFailCode = 0x92;
constexpr uint64_t kStatSnapshotRefTextBase = 0x8000;
constexpr uint64_t kStatSnapshotRefRodataBase = 0x9000;
constexpr uint64_t kStatSnapshotRefSelector =
    static_cast<uint64_t>(kStatSnapshotSelectorAcceptedCommands);
constexpr uint64_t kStatSnapshotRefExpectedAux = 1;
constexpr uint64_t kStatSnapshotRefDescriptorHeader = encodeDescriptorHeader(
    /*version=*/1,
    CommandOpcode::StatSnapshot,
    /*flags=*/0,
    /*completion_policy=*/0,
    /*error_policy=*/0,
    static_cast<uint8_t>(kCommandDescriptorBytes));
constexpr int32_t kStatSnapshotRefSuccessCode = 0xA1;
constexpr int32_t kStatSnapshotRefFailCode = 0xA2;
constexpr uint64_t kStatSnapshotCompletedRefTextBase = 0x8000;
constexpr uint64_t kStatSnapshotCompletedRefRodataBase = 0x9000;
constexpr uint64_t kStatSnapshotCompletedRefFusedDescriptorHeader =
    kExternalDynDescRefDescriptorHeader;
constexpr uint64_t kStatSnapshotCompletedRefDescriptorHeader = kStatSnapshotRefDescriptorHeader;
constexpr uint64_t kStatSnapshotCompletedRefSelector =
    static_cast<uint64_t>(kStatSnapshotSelectorCompletedCommands);
constexpr uint64_t kStatSnapshotCompletedRefExpectedAux = 1;
constexpr int32_t kStatSnapshotCompletedRefSuccessCode = 0xB1;
constexpr int32_t kStatSnapshotCompletedRefFailCode = 0xB2;
constexpr uint64_t kStatSnapshotProviderBoundRefTextBase = 0x8000;
constexpr uint64_t kStatSnapshotProviderBoundRefRodataBase = 0x9000;
constexpr uint64_t kStatSnapshotProviderBoundRefSelector =
    static_cast<uint64_t>(kStatSnapshotSelectorProviderBound);
constexpr uint64_t kStatSnapshotProviderBoundRefExpectedAux = 1;
constexpr uint64_t kStatSnapshotProviderBoundRefDescriptorHeader = kStatSnapshotRefDescriptorHeader;
constexpr int32_t kStatSnapshotProviderBoundRefSuccessCode = 0xC1;
constexpr int32_t kStatSnapshotProviderBoundRefFailCode = 0xC2;
constexpr uint64_t kStatSnapshotBadSelectorRefTextBase = 0x8000;
constexpr uint64_t kStatSnapshotBadSelectorRefRodataBase = 0x9000;
constexpr uint64_t kStatSnapshotBadSelectorRefSelector = 0x55;
constexpr uint32_t kStatSnapshotBadSelectorRefExpectedStatus = encodeStatusCode(
    CompletionPrimaryStatus::BadPolicy,
    CompletionSeverity::FaultAfterAccept);
constexpr uint64_t kStatSnapshotBadSelectorRefExpectedFaultCsr = makeFaultCsrFromStatus(
    kStatSnapshotBadSelectorRefExpectedStatus,
    /*slot=*/1,
    /*aux=*/static_cast<uint32_t>(kStatSnapshotBadSelectorRefSelector));
constexpr uint64_t kStatSnapshotBadSelectorRefExpectedAux0 =
    static_cast<uint32_t>(kStatSnapshotBadSelectorRefExpectedFaultCsr & 0xFFFFFFFFu);
constexpr uint64_t kStatSnapshotBadSelectorRefExpectedAux1 =
    static_cast<uint32_t>(kStatSnapshotBadSelectorRefExpectedFaultCsr >> 32);
constexpr uint64_t kStatSnapshotBadSelectorRefDescriptorHeader = kStatSnapshotRefDescriptorHeader;
constexpr int32_t kStatSnapshotBadSelectorRefSuccessCode = 0xD1;
constexpr int32_t kStatSnapshotBadSelectorRefFailCode = 0xD2;
constexpr uint64_t kExternalP0DataBase = 0x0;
constexpr uint64_t kExternalP0TextBase = 0x8000;
constexpr uint64_t kExternalP0DescriptorToken = 1;

inline const std::vector<RiscvSnnSampleMetadata>& sampleFirmwareMetadata() {
    static const std::vector<RiscvSnnSampleMetadata> kMetadata = {
        {
            "external_p0",
            true,
            "Legacy external firmware sample with a prebuilt FUSED_STEP descriptor data segment.",
            "prebuilt_data_segment",
            "wfi_then_cmpq_ack",
            "submit_one_prebuilt_fused_step_and_ack_completion",
            "dual_segment:data_at_0x0_text_at_0x8000",
            {"legacy_prebuilt_descriptor_sample"},
        },
        {
            "external_dyn_desc",
            true,
            "Canonical external firmware sample that constructs a descriptor at runtime and branches on completion status.",
            "runtime_store_to_ring",
            "wfi_then_status_load_then_cmpq_ack",
            "construct_descriptor_in_local_memory_then_submit_and_branch_on_status",
            "single_text_segment_at_0x8000",
            {"runtime_descriptor_construction_sample"},
        },
        {
            "external_dyn_desc_ref",
            false,
            "Additive reference sample that reads queue CSR bases, performs the cmdq_tail doorbell, then validates cmdq_head/cmpq_tail/payload ordering before ack.",
            "runtime_store_to_ring",
            "cmpq_tail_then_payload_read_then_cmpq_ack",
            "read_queue_csr_bases_then_submit_fused_step_then_validate_head_tail_and_completion_payload",
            "text_at_0x8000_rodata_at_0x9000",
            {
                "bit_level_reference_sample",
                "reads_queue_base_csrs",
                "checks_cmdq_head_and_cmpq_tail_before_ack",
            },
        },
        {
            "external_dyn_desc_fault_ref",
            false,
            "Additive reference sample that submits a reserved-flag descriptor, then validates fault completion payload and msnnfault alignment before ack.",
            "runtime_store_to_ring",
            "cmpq_tail_then_fault_payload_then_msnnfault_then_cmpq_ack",
            "submit_reserved_flag_descriptor_then_validate_fault_completion_and_msnnfault_alignment_before_ack",
            "text_at_0x8000_rodata_at_0x9000",
            {
                "accepted_fault_alignment_reference",
                "descriptor_reserved_flag_fault",
                "checks_fault_payload_and_msnnfault_before_ack",
            },
        },
        {
            "external_dyn_desc_bad_policy_ref",
            false,
            "Additive reference sample that submits an illegal policy descriptor, then validates bad-policy completion, zero-progress msnnstep, and msnnfault visibility before ack.",
            "runtime_store_to_ring",
            "cmpq_tail_then_bad_policy_payload_then_msnnstep_and_msnnfault_then_cmpq_ack",
            "submit_bad_policy_descriptor_then_validate_no_progress_step_and_fault_visibility_before_ack",
            "text_at_0x8000_rodata_at_0x9000",
            {
                "bad_policy_before_progress_reference",
                "descriptor_policy_fault_reference",
                "checks_msnnstep_zero_before_ack",
            },
        },
        {
            "external_dyn_desc_fault_rearm_ref",
            false,
            "Additive reference sample that acks the first accepted fault, clears msnnfault, then submits a second faulting descriptor and checks that the visible fault snapshot is overwritten.",
            "runtime_store_to_ring",
            "fault1_visible_then_msnnfault_clear_then_fault2_visible_then_cmpq_ack",
            "submit_reserved_flag_fault_then_clear_msnnfault_then_submit_bad_policy_fault_and_validate_overwrite",
            "text_at_0x8000_rodata_at_0x9000",
            {
                "fault_rearm_reference",
                "msnnfault_clear_then_refault",
                "checks_second_fault_overwrites_first_snapshot",
            },
        },
        {
            "external_dyn_desc_fault_overwrite_chain_ref",
            false,
            "Additive reference sample that performs a three-fault overwrite chain with two msnnfault clears, then checks that the third accepted fault snapshot replaces the second visible value.",
            "runtime_store_to_ring",
            "fault1_visible_then_msnnfault_clear_then_fault2_visible_then_msnnfault_clear_then_fault3_visible_then_cmpq_ack",
            "submit_three_faulting_descriptors_with_two_clear_points_and_validate_visible_fault_overwrite_chain",
            "text_at_0x8000_rodata_at_0x9000",
            {
                "fault_overwrite_chain_reference",
                "msnnfault_clear_twice_then_refault",
                "checks_third_fault_overwrites_second_snapshot",
            },
        },
        {
            "barrier_wfi_order_ref",
            false,
            "Additive reference sample that submits one barrier-oriented descriptor, sleeps in wfi, then checks cmpq visibility without observable step or fault side effects.",
            "runtime_store_to_ring",
            "wfi_then_cmpq_tail_then_quiescent_step_event_fault_checks",
            "submit_barrier_descriptor_then_require_completion_visibility_before_any_step_or_fault_state_change",
            "text_at_0x8000_rodata_at_0x9000",
            {
                "barrier_completion_visibility_reference",
                "wfi_barrier_order_reference",
                "checks_msnnstep_event_pending_and_msnnfault_remain_quiescent",
            },
        },
        {
            "queue_backpressure_ref",
            false,
            "Additive reference sample that over-doorbells a one-entry cmdq, wakes on the queue overflow fault, then checks msnnfault before any cmpq visibility.",
            "runtime_store_to_ring",
            "fault_wakeup_before_cmpq_visibility",
            "submit_tail_beyond_one_visible_entry_then_require_command_queue_overflow_fault_before_completion_visibility",
            "text_at_0x8000_rodata_at_0x9000",
            {
                "queue_backpressure_reference",
                "command_overdoorbell_overflow",
                "checks_msnnfault_before_cmpq_visibility",
            },
        },
        {
            "completion_queue_overflow_ref",
            false,
            "Additive reference sample that leaves one completion visible and unacked, clears the first wake event, then requires a completion-queue overflow fault on the second publish attempt.",
            "runtime_store_to_ring",
            "cmpq_visible_then_event_clear_then_fault_wakeup_without_cmpq_ack",
            "submit_two_fused_steps_leave_first_completion_visible_then_require_completion_queue_overflow_fault_on_second_publish",
            "text_at_0x8000_rodata_at_0x9000",
            {
                "completion_queue_overflow_reference",
                "visible_completion_then_cmpq_full_fault",
                "checks_msnnstep_commits_before_local_queue_fault",
            },
        },
        {
            "stat_snapshot_ref",
            false,
            "Additive reference sample that submits one StatSnapshot descriptor for the accepted-commands selector, then validates success status, aux visibility, and cmpq ack ordering.",
            "runtime_store_to_ring",
            "cmpq_tail_then_status_then_aux_selector_then_cmpq_ack",
            "submit_one_stat_snapshot_descriptor_then_require_success_status_and_expected_aux_before_ack",
            "text_at_0x8000_rodata_at_0x9000",
            {
                "stat_snapshot_reference",
                "selector_accepted_commands",
                "expects_aux_equal_first_accepted_command_count",
            },
        },
        {
            "stat_snapshot_completed_ref",
            false,
            "Additive reference sample that first completes one FUSED_STEP, then submits a completed-commands StatSnapshot descriptor and validates the prior completion count in aux.",
            "runtime_store_to_ring",
            "completion1_ack_then_cmpq_tail_then_status_then_aux_selector_then_cmpq_ack",
            "submit_one_fused_step_then_submit_completed_commands_stat_snapshot_and_require_prior_completion_count_before_ack",
            "text_at_0x8000_rodata_at_0x9000",
            {
                "stat_snapshot_reference",
                "selector_completed_commands",
                "expects_aux_equal_prior_completed_command_count",
            },
        },
        {
            "stat_snapshot_provider_bound_ref",
            false,
            "Additive reference sample that submits one provider-bound StatSnapshot descriptor and validates success status plus provider-bound aux visibility before cmpq ack.",
            "runtime_store_to_ring",
            "cmpq_tail_then_status_then_aux_provider_bound_then_cmpq_ack",
            "submit_one_provider_bound_stat_snapshot_descriptor_then_require_ready_runtime_bridge_visibility_before_ack",
            "text_at_0x8000_rodata_at_0x9000",
            {
                "stat_snapshot_reference",
                "selector_provider_bound",
                "expects_aux_equal_runtime_bridge_provider_bound_state",
            },
        },
        {
            "stat_snapshot_bad_selector_ref",
            false,
            "Additive reference sample that submits one StatSnapshot descriptor with an invalid selector and validates the visible fault completion plus msnnfault snapshot before ack.",
            "runtime_store_to_ring",
            "cmpq_tail_then_fault_status_then_msnnfault_then_cmpq_ack",
            "submit_one_bad_selector_stat_snapshot_descriptor_then_require_fault_completion_and_visible_fault_snapshot_before_ack",
            "text_at_0x8000_rodata_at_0x9000",
            {
                "stat_snapshot_reference",
                "selector_invalid_fault",
                "expects_visible_fault_snapshot_for_bad_selector",
            },
        },
    };
    return kMetadata;
}

inline const std::vector<std::string>& sampleFirmwareProgramNames() {
    static const std::vector<std::string> kPrograms = [] {
        std::vector<std::string> names;
        for (const auto& sample : sampleFirmwareMetadata()) {
            names.push_back(sample.program);
        }
        return names;
    }();
    return kPrograms;
}

inline const std::vector<std::string>& canonicalSampleFirmwareProgramNames() {
    static const std::vector<std::string> kPrograms = [] {
        std::vector<std::string> names;
        for (const auto& sample : sampleFirmwareMetadata()) {
            if (sample.canonical_sample) names.push_back(sample.program);
        }
        return names;
    }();
    return kPrograms;
}

inline bool lookupSampleFirmwareMetadata(const std::string& program,
                                         RiscvSnnSampleMetadata& out,
                                         std::string& error) {
    for (const auto& sample : sampleFirmwareMetadata()) {
        if (sample.program == program) {
            out = sample;
            error.clear();
            return true;
        }
    }
    error = "unsupported program: " + program;
    return false;
}

namespace detail {

inline void appendProgramLeU64(std::vector<uint8_t>& bytes, uint64_t value) {
    for (int i = 0; i < 8; ++i) {
        bytes.push_back(static_cast<uint8_t>((value >> (i * 8)) & 0xFFu));
    }
}

inline void patchInsn32(std::vector<uint8_t>& bytes, size_t insn_offset, uint32_t value) {
    bytes.at(insn_offset + 0) = static_cast<uint8_t>(value & 0xFFu);
    bytes.at(insn_offset + 1) = static_cast<uint8_t>((value >> 8) & 0xFFu);
    bytes.at(insn_offset + 2) = static_cast<uint8_t>((value >> 16) & 0xFFu);
    bytes.at(insn_offset + 3) = static_cast<uint8_t>((value >> 24) & 0xFFu);
}

inline size_t appendBnePlaceholder(std::vector<uint8_t>& bytes) {
    const size_t insn_offset = bytes.size();
    asmv1::appendInsn32(bytes, 0);
    return insn_offset;
}

inline void patchBne(std::vector<uint8_t>& bytes,
                     size_t insn_offset,
                     uint32_t rs1,
                     uint32_t rs2,
                     size_t target_offset) {
    const int32_t imm =
        static_cast<int32_t>(target_offset) - static_cast<int32_t>(insn_offset);
    patchInsn32(bytes, insn_offset, asmv1::encodeBne(rs1, rs2, imm));
}

inline std::vector<uint8_t> buildExternalDynDescText() {
    using namespace SST::SnnDL::riscv_snn::asmv1;

    std::vector<uint8_t> text;
    appendInsn32(text, encodeLui(/*rd=*/9, /*imm20=*/0x1));
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventEnable, /*zimm=*/0x7));
    appendInsn32(text, encodeAddi(/*rd=*/1, /*rs1=*/0, /*imm=*/1));
    appendInsn32(text, encodeLui(/*rd=*/2, /*imm20=*/0x2));
    appendInsn32(text, encodeAddi(/*rd=*/2, /*rs1=*/2, /*imm=*/1));
    appendInsn32(text, encodeSw(/*rs2=*/2, /*rs1=*/0, /*imm=*/0));
    appendInsn32(text, encodeLui(/*rd=*/3, /*imm20=*/0x4));
    appendInsn32(text, encodeSw(/*rs2=*/3, /*rs1=*/0, /*imm=*/4));
    appendInsn32(text, encodeSw(/*rs2=*/1, /*rs1=*/0, /*imm=*/8));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmdqTail, /*rs1=*/1));
    appendInsn32(text, encodeWfi());
    appendInsn32(text, encodeLw(/*rd=*/4, /*rs1=*/9, /*imm=*/4));
    appendInsn32(text, encodeBne(/*rs1=*/4, /*rs2=*/0, /*imm=*/16));
    appendInsn32(text, encodeAddi(/*rd=*/6, /*rs1=*/0, /*imm=*/7));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmpqHead, /*rs1=*/1));
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventPending, /*zimm=*/0x7));
    appendInsn32(text, encodeEbreak());
    appendInsn32(text, encodeAddi(/*rd=*/6, /*rs1=*/0, /*imm=*/99));
    appendInsn32(text, encodeEbreak());
    return text;
}

inline std::vector<uint8_t> buildExternalP0Data() {
    std::vector<uint8_t> data;
    data.reserve(kCommandDescriptorBytes);
    appendProgramLeU64(
        data,
        encodeDescriptorHeader(
            /*version=*/1,
            CommandOpcode::FusedStep,
            /*flags=*/0,
            /*completion_policy=*/0,
            /*error_policy=*/0,
            static_cast<uint8_t>(kCommandDescriptorBytes)));
    appendProgramLeU64(data, kExternalP0DescriptorToken);
    data.resize(kCommandDescriptorBytes, 0);
    return data;
}

inline std::vector<uint8_t> buildExternalP0Text() {
    using namespace SST::SnnDL::riscv_snn::asmv1;

    std::vector<uint8_t> text;
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventEnable, /*zimm=*/0x7));
    appendInsn32(text, encodeAddi(/*rd=*/1, /*rs1=*/0, /*imm=*/1));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmdqTail, /*rs1=*/1));
    appendInsn32(text, encodeWfi());
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmpqHead, /*rs1=*/1));
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventPending, /*zimm=*/0x7));
    appendInsn32(text, encodeEbreak());
    return text;
}

inline std::vector<uint8_t> buildExternalDynDescRefRodata() {
    std::vector<uint8_t> rodata;
    rodata.reserve(16);
    appendProgramLeU64(rodata, kExternalDynDescRefDescriptorHeader);
    appendProgramLeU64(rodata, 0);
    return rodata;
}

inline std::vector<uint8_t> buildFaultReferenceRodata(uint64_t descriptor_header,
                                                      uint32_t expected_status,
                                                      uint64_t expected_fault_csr) {
    std::vector<uint8_t> rodata;
    rodata.reserve(40);
    appendProgramLeU64(rodata, descriptor_header);
    appendProgramLeU64(rodata, expected_status);
    appendProgramLeU64(rodata, expected_fault_csr);
    appendProgramLeU64(rodata, static_cast<uint32_t>(expected_fault_csr & 0xFFFFFFFFu));
    appendProgramLeU64(rodata, static_cast<uint32_t>(expected_fault_csr >> 32));
    return rodata;
}

inline std::vector<uint8_t> buildExternalDynDescRefText() {
    using namespace SST::SnnDL::riscv_snn::asmv1;

    std::vector<uint8_t> text;
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventEnable, /*zimm=*/0x7));
    appendInsn32(text, encodeCsrrs(/*rd=*/8, kCsrMsnnCmdqBase, /*rs1=*/0));
    appendInsn32(text, encodeCsrrs(/*rd=*/9, kCsrMsnnCmpqBase, /*rs1=*/0));
    appendInsn32(text, encodeAddi(/*rd=*/1, /*rs1=*/0, /*imm=*/1));
    appendInsn32(text, encodeLui(/*rd=*/10, /*imm20=*/0x9));
    appendInsn32(text, encodeLd(/*rd=*/2, /*rs1=*/10, /*imm=*/0));
    appendInsn32(text, encodeSd(/*rs2=*/2, /*rs1=*/8, /*imm=*/0));
    appendInsn32(text, encodeSd(/*rs2=*/1, /*rs1=*/8, /*imm=*/8));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/16));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/24));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/32));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/40));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/48));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/56));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmdqTail, /*rs1=*/1));
    appendInsn32(text, encodeWfi());
    appendInsn32(text, encodeCsrrs(/*rd=*/3, kCsrMsnnCmdqHead, /*rs1=*/0));
    appendInsn32(text, encodeBne(/*rs1=*/3, /*rs2=*/1, /*imm=*/44));
    appendInsn32(text, encodeCsrrs(/*rd=*/4, kCsrMsnnCmpqTail, /*rs1=*/0));
    appendInsn32(text, encodeBne(/*rs1=*/4, /*rs2=*/1, /*imm=*/44));
    appendInsn32(text, encodeLw(/*rd=*/5, /*rs1=*/9, /*imm=*/0));
    appendInsn32(text, encodeBne(/*rs1=*/5, /*rs2=*/1, /*imm=*/44));
    appendInsn32(text, encodeLw(/*rd=*/6, /*rs1=*/9, /*imm=*/4));
    appendInsn32(text, encodeBne(/*rs1=*/6, /*rs2=*/0, /*imm=*/44));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmpqHead, /*rs1=*/4));
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventPending, /*zimm=*/0x7));
    appendInsn32(text, encodeAddi(/*rd=*/7, /*rs1=*/0, /*imm=*/kExternalDynDescRefSuccessCode));
    appendInsn32(text, encodeEbreak());
    appendInsn32(text, encodeAddi(/*rd=*/7, /*rs1=*/0, /*imm=*/kExternalDynDescRefFailHeadCode));
    appendInsn32(text, encodeEbreak());
    appendInsn32(text, encodeAddi(/*rd=*/7, /*rs1=*/0, /*imm=*/kExternalDynDescRefFailTailCode));
    appendInsn32(text, encodeEbreak());
    appendInsn32(text, encodeAddi(/*rd=*/7, /*rs1=*/0, /*imm=*/kExternalDynDescRefFailTokenCode));
    appendInsn32(text, encodeEbreak());
    appendInsn32(text, encodeAddi(/*rd=*/7, /*rs1=*/0, /*imm=*/kExternalDynDescRefFailStatusCode));
    appendInsn32(text, encodeEbreak());
    return text;
}

inline std::vector<uint8_t> buildBarrierWfiOrderRefRodata() {
    std::vector<uint8_t> rodata;
    rodata.reserve(40);
    appendProgramLeU64(rodata, kBarrierWfiOrderRefDescriptorHeader);
    appendProgramLeU64(rodata, 0x0000000000000206ULL);
    appendProgramLeU64(rodata, 0x0000400000000106ULL);
    appendProgramLeU64(rodata, 0x0000000000000106ULL);
    appendProgramLeU64(rodata, 0x0000000000004000ULL);
    return rodata;
}

inline std::vector<uint8_t> buildBarrierWfiOrderRefText() {
    using namespace SST::SnnDL::riscv_snn::asmv1;

    std::vector<uint8_t> text;
    std::vector<size_t> fail_branches;
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventEnable, /*zimm=*/0x7));
    appendInsn32(text, encodeCsrrs(/*rd=*/8, kCsrMsnnCmdqBase, /*rs1=*/0));
    appendInsn32(text, encodeCsrrs(/*rd=*/9, kCsrMsnnCmpqBase, /*rs1=*/0));
    appendInsn32(text, encodeAddi(/*rd=*/1, /*rs1=*/0, /*imm=*/1));
    appendInsn32(text, encodeLui(/*rd=*/10, /*imm20=*/0x9));
    appendInsn32(text, encodeLd(/*rd=*/2, /*rs1=*/10, /*imm=*/0));
    appendInsn32(text, encodeSd(/*rs2=*/2, /*rs1=*/8, /*imm=*/0));
    appendInsn32(text, encodeSd(/*rs2=*/1, /*rs1=*/8, /*imm=*/8));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/16));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/24));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/32));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/40));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/48));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/56));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmdqTail, /*rs1=*/1));
    appendInsn32(text, encodeWfi());
    appendInsn32(text, encodeCsrrs(/*rd=*/3, kCsrMsnnCmpqTail, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/4, kCsrMsnnStep, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/5, kCsrMsnnEventPending, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/6, kCsrMsnnFault, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmpqHead, /*rs1=*/3));
    appendInsn32(text, encodeAddi(/*rd=*/7, /*rs1=*/0, /*imm=*/kBarrierWfiOrderRefSuccessCode));
    appendInsn32(text, encodeEbreak());
    const size_t fail_label = text.size();
    appendInsn32(text, encodeAddi(/*rd=*/7, /*rs1=*/0, /*imm=*/kBarrierWfiOrderRefFailCode));
    appendInsn32(text, encodeEbreak());

    patchBne(
        text,
        fail_branches[0],
        /*rs1=*/3,
        /*rs2=*/1,
        fail_label);
    patchBne(
        text,
        fail_branches[1],
        /*rs1=*/4,
        /*rs2=*/0,
        fail_label);
    patchBne(
        text,
        fail_branches[2],
        /*rs1=*/5,
        /*rs2=*/0,
        fail_label);
    patchBne(
        text,
        fail_branches[3],
        /*rs1=*/6,
        /*rs2=*/0,
        fail_label);
    return text;
}

inline std::vector<uint8_t> buildQueueBackpressureRefRodata() {
    std::vector<uint8_t> rodata;
    rodata.reserve(16);
    appendProgramLeU64(rodata, kQueueBackpressureRefDescriptorHeader);
    appendProgramLeU64(rodata, kQueueBackpressureRefExpectedFaultCsr);
    return rodata;
}

inline std::vector<uint8_t> buildQueueBackpressureRefText() {
    using namespace SST::SnnDL::riscv_snn::asmv1;

    std::vector<uint8_t> text;
    std::vector<size_t> fail_branches;
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventEnable, /*zimm=*/0x7));
    appendInsn32(text, encodeCsrrs(/*rd=*/8, kCsrMsnnCmdqBase, /*rs1=*/0));
    appendInsn32(text, encodeAddi(/*rd=*/1, /*rs1=*/0, /*imm=*/1));
    appendInsn32(text, encodeAddi(/*rd=*/21, /*rs1=*/0, /*imm=*/2));
    appendInsn32(text, encodeLui(/*rd=*/10, /*imm20=*/0x9));
    appendInsn32(text, encodeLd(/*rd=*/2, /*rs1=*/10, /*imm=*/0));
    appendInsn32(text, encodeSd(/*rs2=*/2, /*rs1=*/8, /*imm=*/0));
    appendInsn32(text, encodeSd(/*rs2=*/1, /*rs1=*/8, /*imm=*/8));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/16));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/24));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/32));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/40));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/48));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/56));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmdqTail, /*rs1=*/21));
    appendInsn32(text, encodeWfi());
    appendInsn32(text, encodeCsrrs(/*rd=*/3, kCsrMsnnCmdqHead, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/4, kCsrMsnnCmdqTail, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/5, kCsrMsnnCmpqTail, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/6, kCsrMsnnStep, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/7, kCsrMsnnFault, /*rs1=*/0));
    appendInsn32(text, encodeLd(/*rd=*/11, /*rs1=*/10, /*imm=*/8));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventPending, /*zimm=*/0x7));
    appendInsn32(text, encodeAddi(/*rd=*/7, /*rs1=*/0, /*imm=*/kQueueBackpressureRefSuccessCode));
    appendInsn32(text, encodeEbreak());
    const size_t fail_label = text.size();
    appendInsn32(text, encodeAddi(/*rd=*/7, /*rs1=*/0, /*imm=*/kQueueBackpressureRefFailCode));
    appendInsn32(text, encodeEbreak());

    patchBne(text, fail_branches[0], /*rs1=*/3, /*rs2=*/1, fail_label);
    patchBne(text, fail_branches[1], /*rs1=*/4, /*rs2=*/1, fail_label);
    patchBne(text, fail_branches[2], /*rs1=*/5, /*rs2=*/0, fail_label);
    patchBne(text, fail_branches[3], /*rs1=*/6, /*rs2=*/0, fail_label);
    patchBne(text, fail_branches[4], /*rs1=*/7, /*rs2=*/11, fail_label);
    return text;
}

inline std::vector<uint8_t> buildCompletionQueueOverflowRefRodata() {
    std::vector<uint8_t> rodata;
    rodata.reserve(16);
    appendProgramLeU64(rodata, kCompletionQueueOverflowRefDescriptorHeader);
    appendProgramLeU64(rodata, kCompletionQueueOverflowRefExpectedFaultCsr);
    return rodata;
}

inline std::vector<uint8_t> buildCompletionQueueOverflowRefText() {
    using namespace SST::SnnDL::riscv_snn::asmv1;

    std::vector<uint8_t> text;
    std::vector<size_t> fail_branches;
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventEnable, /*zimm=*/0x7));
    appendInsn32(text, encodeCsrrs(/*rd=*/8, kCsrMsnnCmdqBase, /*rs1=*/0));
    appendInsn32(text, encodeCsrrs(/*rd=*/9, kCsrMsnnCmpqBase, /*rs1=*/0));
    appendInsn32(text, encodeAddi(/*rd=*/1, /*rs1=*/0, /*imm=*/1));
    appendInsn32(text, encodeAddi(/*rd=*/21, /*rs1=*/0, /*imm=*/2));
    appendInsn32(text, encodeAddi(/*rd=*/22, /*rs1=*/0, /*imm=*/2));
    appendInsn32(text, encodeLui(/*rd=*/10, /*imm20=*/0x9));
    appendInsn32(text, encodeLd(/*rd=*/2, /*rs1=*/10, /*imm=*/0));
    appendInsn32(text, encodeSd(/*rs2=*/2, /*rs1=*/8, /*imm=*/0));
    appendInsn32(text, encodeSd(/*rs2=*/1, /*rs1=*/8, /*imm=*/8));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/16));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/24));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/32));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/40));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/48));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/56));
    appendInsn32(text, encodeAddi(/*rd=*/20, /*rs1=*/8, /*imm=*/64));
    appendInsn32(text, encodeSd(/*rs2=*/2, /*rs1=*/20, /*imm=*/0));
    appendInsn32(text, encodeSd(/*rs2=*/21, /*rs1=*/20, /*imm=*/8));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/20, /*imm=*/16));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/20, /*imm=*/24));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/20, /*imm=*/32));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/20, /*imm=*/40));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/20, /*imm=*/48));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/20, /*imm=*/56));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmdqTail, /*rs1=*/22));
    appendInsn32(text, encodeWfi());
    appendInsn32(text, encodeCsrrs(/*rd=*/3, kCsrMsnnCmpqTail, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/4, /*rs1=*/9, /*imm=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/5, /*rs1=*/9, /*imm=*/4));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/6, /*rs1=*/9, /*imm=*/8));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/7, /*rs1=*/9, /*imm=*/12));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventPending, /*zimm=*/0x7));
    appendInsn32(text, encodeWfi());
    appendInsn32(text, encodeCsrrs(/*rd=*/11, kCsrMsnnCmdqHead, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/12, kCsrMsnnCmdqTail, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/13, kCsrMsnnCmpqHead, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/14, kCsrMsnnCmpqTail, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/15, kCsrMsnnStep, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/16, kCsrMsnnFault, /*rs1=*/0));
    appendInsn32(text, encodeLd(/*rd=*/17, /*rs1=*/10, /*imm=*/8));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/18, /*rs1=*/9, /*imm=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/19, /*rs1=*/9, /*imm=*/4));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventPending, /*zimm=*/0x7));
    appendInsn32(
        text,
        encodeAddi(/*rd=*/7, /*rs1=*/0, /*imm=*/kCompletionQueueOverflowRefSuccessCode));
    appendInsn32(text, encodeEbreak());
    const size_t fail_label = text.size();
    appendInsn32(
        text,
        encodeAddi(/*rd=*/7, /*rs1=*/0, /*imm=*/kCompletionQueueOverflowRefFailCode));
    appendInsn32(text, encodeEbreak());

    patchBne(text, fail_branches[0], /*rs1=*/3, /*rs2=*/1, fail_label);
    patchBne(text, fail_branches[1], /*rs1=*/4, /*rs2=*/1, fail_label);
    patchBne(text, fail_branches[2], /*rs1=*/5, /*rs2=*/0, fail_label);
    patchBne(text, fail_branches[3], /*rs1=*/6, /*rs2=*/0, fail_label);
    patchBne(text, fail_branches[4], /*rs1=*/7, /*rs2=*/0, fail_label);
    patchBne(text, fail_branches[5], /*rs1=*/11, /*rs2=*/22, fail_label);
    patchBne(text, fail_branches[6], /*rs1=*/12, /*rs2=*/22, fail_label);
    patchBne(text, fail_branches[7], /*rs1=*/13, /*rs2=*/0, fail_label);
    patchBne(text, fail_branches[8], /*rs1=*/14, /*rs2=*/1, fail_label);
    patchBne(text, fail_branches[9], /*rs1=*/15, /*rs2=*/22, fail_label);
    patchBne(text, fail_branches[10], /*rs1=*/16, /*rs2=*/17, fail_label);
    patchBne(text, fail_branches[11], /*rs1=*/18, /*rs2=*/1, fail_label);
    patchBne(text, fail_branches[12], /*rs1=*/19, /*rs2=*/0, fail_label);
    return text;
}

inline std::vector<uint8_t> buildStatSnapshotRefRodata() {
    std::vector<uint8_t> rodata;
    rodata.reserve(24);
    appendProgramLeU64(rodata, kStatSnapshotRefDescriptorHeader);
    appendProgramLeU64(rodata, kStatSnapshotRefSelector);
    appendProgramLeU64(rodata, kStatSnapshotRefExpectedAux);
    return rodata;
}

inline std::vector<uint8_t> buildSingleStatSnapshotReferenceText(int32_t success_code,
                                                                 int32_t fail_code) {
    using namespace SST::SnnDL::riscv_snn::asmv1;

    std::vector<uint8_t> text;
    std::vector<size_t> fail_branches;
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventEnable, /*zimm=*/0x7));
    appendInsn32(text, encodeCsrrs(/*rd=*/8, kCsrMsnnCmdqBase, /*rs1=*/0));
    appendInsn32(text, encodeCsrrs(/*rd=*/9, kCsrMsnnCmpqBase, /*rs1=*/0));
    appendInsn32(text, encodeAddi(/*rd=*/1, /*rs1=*/0, /*imm=*/1));
    appendInsn32(text, encodeLui(/*rd=*/10, /*imm20=*/0x9));
    appendInsn32(text, encodeLd(/*rd=*/2, /*rs1=*/10, /*imm=*/0));
    appendInsn32(text, encodeLd(/*rd=*/3, /*rs1=*/10, /*imm=*/8));
    appendInsn32(text, encodeLd(/*rd=*/11, /*rs1=*/10, /*imm=*/16));
    appendInsn32(text, encodeSd(/*rs2=*/2, /*rs1=*/8, /*imm=*/0));
    appendInsn32(text, encodeSd(/*rs2=*/1, /*rs1=*/8, /*imm=*/8));
    appendInsn32(text, encodeSd(/*rs2=*/3, /*rs1=*/8, /*imm=*/16));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/24));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/32));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/40));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/48));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/56));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmdqTail, /*rs1=*/1));
    appendInsn32(text, encodeWfi());
    appendInsn32(text, encodeCsrrs(/*rd=*/4, kCsrMsnnCmpqTail, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/5, /*rs1=*/9, /*imm=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/6, /*rs1=*/9, /*imm=*/4));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/7, /*rs1=*/9, /*imm=*/8));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/12, /*rs1=*/9, /*imm=*/12));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmpqHead, /*rs1=*/4));
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventPending, /*zimm=*/0x7));
    appendInsn32(text, encodeAddi(/*rd=*/7, /*rs1=*/0, /*imm=*/success_code));
    appendInsn32(text, encodeEbreak());
    const size_t fail_label = text.size();
    appendInsn32(text, encodeAddi(/*rd=*/7, /*rs1=*/0, /*imm=*/fail_code));
    appendInsn32(text, encodeEbreak());

    patchBne(text, fail_branches[0], /*rs1=*/4, /*rs2=*/1, fail_label);
    patchBne(text, fail_branches[1], /*rs1=*/5, /*rs2=*/1, fail_label);
    patchBne(text, fail_branches[2], /*rs1=*/6, /*rs2=*/0, fail_label);
    patchBne(text, fail_branches[3], /*rs1=*/7, /*rs2=*/11, fail_label);
    patchBne(text, fail_branches[4], /*rs1=*/12, /*rs2=*/0, fail_label);
    return text;
}

inline std::vector<uint8_t> buildStatSnapshotRefText() {
    return buildSingleStatSnapshotReferenceText(
        kStatSnapshotRefSuccessCode,
        kStatSnapshotRefFailCode);
}

inline std::vector<uint8_t> buildStatSnapshotCompletedRefRodata() {
    std::vector<uint8_t> rodata;
    rodata.reserve(32);
    appendProgramLeU64(rodata, kStatSnapshotCompletedRefFusedDescriptorHeader);
    appendProgramLeU64(rodata, kStatSnapshotCompletedRefDescriptorHeader);
    appendProgramLeU64(rodata, kStatSnapshotCompletedRefSelector);
    appendProgramLeU64(rodata, kStatSnapshotCompletedRefExpectedAux);
    return rodata;
}

inline std::vector<uint8_t> buildStatSnapshotCompletedRefText() {
    using namespace SST::SnnDL::riscv_snn::asmv1;

    std::vector<uint8_t> text;
    std::vector<size_t> fail_branches;
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventEnable, /*zimm=*/0x7));
    appendInsn32(text, encodeCsrrs(/*rd=*/8, kCsrMsnnCmdqBase, /*rs1=*/0));
    appendInsn32(text, encodeCsrrs(/*rd=*/9, kCsrMsnnCmpqBase, /*rs1=*/0));
    appendInsn32(text, encodeAddi(/*rd=*/1, /*rs1=*/0, /*imm=*/1));
    appendInsn32(text, encodeAddi(/*rd=*/2, /*rs1=*/0, /*imm=*/2));
    appendInsn32(text, encodeLui(/*rd=*/10, /*imm20=*/0x9));
    appendInsn32(text, encodeLd(/*rd=*/3, /*rs1=*/10, /*imm=*/0));
    appendInsn32(text, encodeSd(/*rs2=*/3, /*rs1=*/8, /*imm=*/0));
    appendInsn32(text, encodeSd(/*rs2=*/1, /*rs1=*/8, /*imm=*/8));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/16));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/24));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/32));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/40));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/48));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/56));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmdqTail, /*rs1=*/1));
    appendInsn32(text, encodeWfi());
    appendInsn32(text, encodeCsrrs(/*rd=*/4, kCsrMsnnCmpqTail, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/5, /*rs1=*/9, /*imm=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/6, /*rs1=*/9, /*imm=*/4));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmpqHead, /*rs1=*/4));
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventPending, /*zimm=*/0x7));
    appendInsn32(text, encodeAddi(/*rd=*/12, /*rs1=*/8, /*imm=*/64));
    appendInsn32(text, encodeAddi(/*rd=*/13, /*rs1=*/9, /*imm=*/16));
    appendInsn32(text, encodeLd(/*rd=*/3, /*rs1=*/10, /*imm=*/8));
    appendInsn32(text, encodeLd(/*rd=*/11, /*rs1=*/10, /*imm=*/16));
    appendInsn32(text, encodeLd(/*rd=*/14, /*rs1=*/10, /*imm=*/24));
    appendInsn32(text, encodeSd(/*rs2=*/3, /*rs1=*/12, /*imm=*/0));
    appendInsn32(text, encodeSd(/*rs2=*/2, /*rs1=*/12, /*imm=*/8));
    appendInsn32(text, encodeSd(/*rs2=*/11, /*rs1=*/12, /*imm=*/16));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/12, /*imm=*/24));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/12, /*imm=*/32));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/12, /*imm=*/40));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/12, /*imm=*/48));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/12, /*imm=*/56));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmdqTail, /*rs1=*/2));
    appendInsn32(text, encodeWfi());
    appendInsn32(text, encodeCsrrs(/*rd=*/4, kCsrMsnnCmpqTail, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/5, /*rs1=*/13, /*imm=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/6, /*rs1=*/13, /*imm=*/4));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/7, /*rs1=*/13, /*imm=*/8));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/15, /*rs1=*/13, /*imm=*/12));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmpqHead, /*rs1=*/4));
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventPending, /*zimm=*/0x7));
    appendInsn32(
        text,
        encodeAddi(/*rd=*/7, /*rs1=*/0, /*imm=*/kStatSnapshotCompletedRefSuccessCode));
    appendInsn32(text, encodeEbreak());
    const size_t fail_label = text.size();
    appendInsn32(
        text,
        encodeAddi(/*rd=*/7, /*rs1=*/0, /*imm=*/kStatSnapshotCompletedRefFailCode));
    appendInsn32(text, encodeEbreak());

    patchBne(text, fail_branches[0], /*rs1=*/4, /*rs2=*/1, fail_label);
    patchBne(text, fail_branches[1], /*rs1=*/5, /*rs2=*/1, fail_label);
    patchBne(text, fail_branches[2], /*rs1=*/6, /*rs2=*/0, fail_label);
    patchBne(text, fail_branches[3], /*rs1=*/4, /*rs2=*/2, fail_label);
    patchBne(text, fail_branches[4], /*rs1=*/5, /*rs2=*/2, fail_label);
    patchBne(text, fail_branches[5], /*rs1=*/6, /*rs2=*/0, fail_label);
    patchBne(text, fail_branches[6], /*rs1=*/7, /*rs2=*/14, fail_label);
    patchBne(text, fail_branches[7], /*rs1=*/15, /*rs2=*/0, fail_label);
    return text;
}

inline std::vector<uint8_t> buildStatSnapshotProviderBoundRefRodata() {
    std::vector<uint8_t> rodata;
    rodata.reserve(24);
    appendProgramLeU64(rodata, kStatSnapshotProviderBoundRefDescriptorHeader);
    appendProgramLeU64(rodata, kStatSnapshotProviderBoundRefSelector);
    appendProgramLeU64(rodata, kStatSnapshotProviderBoundRefExpectedAux);
    return rodata;
}

inline std::vector<uint8_t> buildStatSnapshotProviderBoundRefText() {
    return buildSingleStatSnapshotReferenceText(
        kStatSnapshotProviderBoundRefSuccessCode,
        kStatSnapshotProviderBoundRefFailCode);
}

inline std::vector<uint8_t> buildStatSnapshotBadSelectorRefRodata() {
    std::vector<uint8_t> rodata;
    rodata.reserve(48);
    appendProgramLeU64(rodata, kStatSnapshotBadSelectorRefDescriptorHeader);
    appendProgramLeU64(rodata, kStatSnapshotBadSelectorRefSelector);
    appendProgramLeU64(rodata, kStatSnapshotBadSelectorRefExpectedFaultCsr);
    appendProgramLeU64(rodata, kStatSnapshotBadSelectorRefExpectedStatus);
    appendProgramLeU64(rodata, kStatSnapshotBadSelectorRefExpectedAux0);
    appendProgramLeU64(rodata, kStatSnapshotBadSelectorRefExpectedAux1);
    return rodata;
}

inline std::vector<uint8_t> buildStatSnapshotBadSelectorRefText() {
    using namespace SST::SnnDL::riscv_snn::asmv1;

    std::vector<uint8_t> text;
    std::vector<size_t> fail_branches;
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventEnable, /*zimm=*/0x7));
    appendInsn32(text, encodeCsrrs(/*rd=*/8, kCsrMsnnCmdqBase, /*rs1=*/0));
    appendInsn32(text, encodeCsrrs(/*rd=*/9, kCsrMsnnCmpqBase, /*rs1=*/0));
    appendInsn32(text, encodeAddi(/*rd=*/1, /*rs1=*/0, /*imm=*/1));
    appendInsn32(text, encodeLui(/*rd=*/10, /*imm20=*/0x9));
    appendInsn32(text, encodeLd(/*rd=*/2, /*rs1=*/10, /*imm=*/0));
    appendInsn32(text, encodeLd(/*rd=*/3, /*rs1=*/10, /*imm=*/8));
    appendInsn32(text, encodeSd(/*rs2=*/2, /*rs1=*/8, /*imm=*/0));
    appendInsn32(text, encodeSd(/*rs2=*/1, /*rs1=*/8, /*imm=*/8));
    appendInsn32(text, encodeSd(/*rs2=*/3, /*rs1=*/8, /*imm=*/16));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/24));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/32));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/40));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/48));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/56));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmdqTail, /*rs1=*/1));
    appendInsn32(text, encodeWfi());

    appendInsn32(text, encodeCsrrs(/*rd=*/4, kCsrMsnnCmdqHead, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/5, kCsrMsnnCmpqTail, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/6, kCsrMsnnStep, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/7, /*rs1=*/9, /*imm=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/11, /*rs1=*/9, /*imm=*/4));
    appendInsn32(text, encodeLd(/*rd=*/12, /*rs1=*/10, /*imm=*/24));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/13, /*rs1=*/9, /*imm=*/8));
    appendInsn32(text, encodeLd(/*rd=*/14, /*rs1=*/10, /*imm=*/32));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/15, /*rs1=*/9, /*imm=*/12));
    appendInsn32(text, encodeLd(/*rd=*/16, /*rs1=*/10, /*imm=*/40));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/17, kCsrMsnnFault, /*rs1=*/0));
    appendInsn32(text, encodeLd(/*rd=*/18, /*rs1=*/10, /*imm=*/16));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmpqHead, /*rs1=*/5));
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventPending, /*zimm=*/0x7));
    appendInsn32(
        text,
        encodeAddi(/*rd=*/7, /*rs1=*/0, /*imm=*/kStatSnapshotBadSelectorRefSuccessCode));
    appendInsn32(text, encodeEbreak());
    const size_t fail_label = text.size();
    appendInsn32(
        text,
        encodeAddi(/*rd=*/7, /*rs1=*/0, /*imm=*/kStatSnapshotBadSelectorRefFailCode));
    appendInsn32(text, encodeEbreak());

    patchBne(text, fail_branches[0], /*rs1=*/4, /*rs2=*/1, fail_label);
    patchBne(text, fail_branches[1], /*rs1=*/5, /*rs2=*/1, fail_label);
    patchBne(text, fail_branches[2], /*rs1=*/6, /*rs2=*/0, fail_label);
    patchBne(text, fail_branches[3], /*rs1=*/7, /*rs2=*/1, fail_label);
    patchBne(text, fail_branches[4], /*rs1=*/11, /*rs2=*/12, fail_label);
    patchBne(text, fail_branches[5], /*rs1=*/13, /*rs2=*/14, fail_label);
    patchBne(text, fail_branches[6], /*rs1=*/15, /*rs2=*/16, fail_label);
    patchBne(text, fail_branches[7], /*rs1=*/17, /*rs2=*/18, fail_label);
    return text;
}

inline std::vector<uint8_t> buildFaultReferenceText(int32_t success_code,
                                                    int32_t fail_code,
                                                    bool require_zero_step) {
    using namespace SST::SnnDL::riscv_snn::asmv1;

    std::vector<uint8_t> text;
    std::vector<size_t> fail_branches;
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventEnable, /*zimm=*/0x7));
    appendInsn32(text, encodeCsrrs(/*rd=*/8, kCsrMsnnCmdqBase, /*rs1=*/0));
    appendInsn32(text, encodeCsrrs(/*rd=*/9, kCsrMsnnCmpqBase, /*rs1=*/0));
    appendInsn32(text, encodeAddi(/*rd=*/1, /*rs1=*/0, /*imm=*/1));
    appendInsn32(text, encodeLui(/*rd=*/10, /*imm20=*/0x9));
    appendInsn32(text, encodeLd(/*rd=*/2, /*rs1=*/10, /*imm=*/0));
    appendInsn32(text, encodeSd(/*rs2=*/2, /*rs1=*/8, /*imm=*/0));
    appendInsn32(text, encodeSd(/*rs2=*/1, /*rs1=*/8, /*imm=*/8));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/16));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/24));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/32));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/40));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/48));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/56));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmdqTail, /*rs1=*/1));
    appendInsn32(text, encodeWfi());
    appendInsn32(text, encodeCsrrs(/*rd=*/3, kCsrMsnnCmdqHead, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/4, kCsrMsnnCmpqTail, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    if (require_zero_step) {
        appendInsn32(text, encodeCsrrs(/*rd=*/5, kCsrMsnnStep, /*rs1=*/0));
        fail_branches.push_back(appendBnePlaceholder(text));
    }
    appendInsn32(text, encodeLw(/*rd=*/6, /*rs1=*/9, /*imm=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/7, /*rs1=*/9, /*imm=*/4));
    appendInsn32(text, encodeLd(/*rd=*/11, /*rs1=*/10, /*imm=*/8));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/12, /*rs1=*/9, /*imm=*/8));
    appendInsn32(text, encodeLd(/*rd=*/13, /*rs1=*/10, /*imm=*/24));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/14, /*rs1=*/9, /*imm=*/12));
    appendInsn32(text, encodeLd(/*rd=*/15, /*rs1=*/10, /*imm=*/32));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/16, kCsrMsnnFault, /*rs1=*/0));
    appendInsn32(text, encodeLd(/*rd=*/17, /*rs1=*/10, /*imm=*/16));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmpqHead, /*rs1=*/4));
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventPending, /*zimm=*/0x7));
    appendInsn32(text, encodeAddi(/*rd=*/7, /*rs1=*/0, /*imm=*/success_code));
    appendInsn32(text, encodeEbreak());
    const size_t fail_label = text.size();
    appendInsn32(text, encodeAddi(/*rd=*/7, /*rs1=*/0, /*imm=*/fail_code));
    appendInsn32(text, encodeEbreak());

    patchBne(text, fail_branches[0], /*rs1=*/3, /*rs2=*/1, fail_label);
    patchBne(text, fail_branches[1], /*rs1=*/4, /*rs2=*/1, fail_label);
    size_t patch_index = 2;
    if (require_zero_step) {
        patchBne(text, fail_branches[patch_index], /*rs1=*/5, /*rs2=*/0, fail_label);
        ++patch_index;
    }
    patchBne(text, fail_branches[patch_index + 0], /*rs1=*/6, /*rs2=*/1, fail_label);
    patchBne(text, fail_branches[patch_index + 1], /*rs1=*/7, /*rs2=*/11, fail_label);
    patchBne(text, fail_branches[patch_index + 2], /*rs1=*/12, /*rs2=*/13, fail_label);
    patchBne(text, fail_branches[patch_index + 3], /*rs1=*/14, /*rs2=*/15, fail_label);
    patchBne(text, fail_branches[patch_index + 4], /*rs1=*/16, /*rs2=*/17, fail_label);
    return text;
}

inline std::vector<uint8_t> buildExternalDynDescFaultRefRodata() {
    return buildFaultReferenceRodata(
        kExternalDynDescFaultRefDescriptorHeader,
        kExternalDynDescFaultRefExpectedStatus,
        kExternalDynDescFaultRefExpectedFaultCsr);
}

inline std::vector<uint8_t> buildExternalDynDescFaultRefText() {
    return buildFaultReferenceText(
        kExternalDynDescFaultRefSuccessCode,
        kExternalDynDescFaultRefFailCode,
        /*require_zero_step=*/false);
}

inline std::vector<uint8_t> buildExternalDynDescBadPolicyRefRodata() {
    return buildFaultReferenceRodata(
        kExternalDynDescBadPolicyRefDescriptorHeader,
        kExternalDynDescBadPolicyRefExpectedStatus,
        kExternalDynDescBadPolicyRefExpectedFaultCsr);
}

inline std::vector<uint8_t> buildExternalDynDescBadPolicyRefText() {
    return buildFaultReferenceText(
        kExternalDynDescBadPolicyRefSuccessCode,
        kExternalDynDescBadPolicyRefFailCode,
        /*require_zero_step=*/true);
}

inline std::vector<uint8_t> buildExternalDynDescFaultRearmRefRodata() {
    std::vector<uint8_t> rodata;
    rodata.reserve(80);
    appendProgramLeU64(rodata, kExternalDynDescFaultRearmRefFirstDescriptorHeader);
    appendProgramLeU64(rodata, kExternalDynDescFaultRefExpectedStatus);
    appendProgramLeU64(rodata, kExternalDynDescFaultRefExpectedFaultCsr);
    appendProgramLeU64(
        rodata,
        static_cast<uint32_t>(kExternalDynDescFaultRefExpectedFaultCsr & 0xFFFFFFFFu));
    appendProgramLeU64(
        rodata,
        static_cast<uint32_t>(kExternalDynDescFaultRefExpectedFaultCsr >> 32));
    appendProgramLeU64(rodata, kExternalDynDescFaultRearmRefSecondDescriptorHeader);
    appendProgramLeU64(rodata, kExternalDynDescBadPolicyRefExpectedStatus);
    appendProgramLeU64(rodata, kExternalDynDescFaultRearmRefSecondExpectedFaultCsr);
    appendProgramLeU64(
        rodata,
        static_cast<uint32_t>(kExternalDynDescFaultRearmRefSecondExpectedFaultCsr & 0xFFFFFFFFu));
    appendProgramLeU64(
        rodata,
        static_cast<uint32_t>(kExternalDynDescFaultRearmRefSecondExpectedFaultCsr >> 32));
    return rodata;
}

inline std::vector<uint8_t> buildExternalDynDescFaultRearmRefText() {
    using namespace SST::SnnDL::riscv_snn::asmv1;

    std::vector<uint8_t> text;
    std::vector<size_t> fail_branches;
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventEnable, /*zimm=*/0x7));
    appendInsn32(text, encodeCsrrs(/*rd=*/8, kCsrMsnnCmdqBase, /*rs1=*/0));
    appendInsn32(text, encodeCsrrs(/*rd=*/9, kCsrMsnnCmpqBase, /*rs1=*/0));
    appendInsn32(text, encodeAddi(/*rd=*/1, /*rs1=*/0, /*imm=*/1));
    appendInsn32(text, encodeAddi(/*rd=*/21, /*rs1=*/0, /*imm=*/2));
    appendInsn32(text, encodeLui(/*rd=*/10, /*imm20=*/0x9));
    appendInsn32(text, encodeLd(/*rd=*/2, /*rs1=*/10, /*imm=*/0));
    appendInsn32(text, encodeSd(/*rs2=*/2, /*rs1=*/8, /*imm=*/0));
    appendInsn32(text, encodeSd(/*rs2=*/1, /*rs1=*/8, /*imm=*/8));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/16));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/24));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/32));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/40));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/48));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/56));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmdqTail, /*rs1=*/1));
    appendInsn32(text, encodeWfi());
    appendInsn32(text, encodeCsrrs(/*rd=*/3, kCsrMsnnCmdqHead, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/4, kCsrMsnnCmpqTail, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/6, /*rs1=*/9, /*imm=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/7, /*rs1=*/9, /*imm=*/4));
    appendInsn32(text, encodeLd(/*rd=*/11, /*rs1=*/10, /*imm=*/8));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/12, /*rs1=*/9, /*imm=*/8));
    appendInsn32(text, encodeLd(/*rd=*/13, /*rs1=*/10, /*imm=*/24));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/14, /*rs1=*/9, /*imm=*/12));
    appendInsn32(text, encodeLd(/*rd=*/15, /*rs1=*/10, /*imm=*/32));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/16, kCsrMsnnFault, /*rs1=*/0));
    appendInsn32(text, encodeLd(/*rd=*/17, /*rs1=*/10, /*imm=*/16));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmpqHead, /*rs1=*/4));
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventPending, /*zimm=*/0x7));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnFault, /*rs1=*/0));
    appendInsn32(text, encodeCsrrs(/*rd=*/18, kCsrMsnnFault, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeAddi(/*rd=*/20, /*rs1=*/8, /*imm=*/64));
    appendInsn32(text, encodeAddi(/*rd=*/19, /*rs1=*/9, /*imm=*/16));
    appendInsn32(text, encodeLd(/*rd=*/2, /*rs1=*/10, /*imm=*/40));
    appendInsn32(text, encodeSd(/*rs2=*/2, /*rs1=*/20, /*imm=*/0));
    appendInsn32(text, encodeSd(/*rs2=*/21, /*rs1=*/20, /*imm=*/8));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/20, /*imm=*/16));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/20, /*imm=*/24));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/20, /*imm=*/32));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/20, /*imm=*/40));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/20, /*imm=*/48));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/20, /*imm=*/56));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmdqTail, /*rs1=*/21));
    appendInsn32(text, encodeWfi());
    appendInsn32(text, encodeCsrrs(/*rd=*/3, kCsrMsnnCmdqHead, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/4, kCsrMsnnCmpqTail, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/5, kCsrMsnnStep, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/6, /*rs1=*/19, /*imm=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/7, /*rs1=*/19, /*imm=*/4));
    appendInsn32(text, encodeLd(/*rd=*/11, /*rs1=*/10, /*imm=*/48));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/12, /*rs1=*/19, /*imm=*/8));
    appendInsn32(text, encodeLd(/*rd=*/13, /*rs1=*/10, /*imm=*/64));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/14, /*rs1=*/19, /*imm=*/12));
    appendInsn32(text, encodeLd(/*rd=*/15, /*rs1=*/10, /*imm=*/72));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/16, kCsrMsnnFault, /*rs1=*/0));
    appendInsn32(text, encodeLd(/*rd=*/17, /*rs1=*/10, /*imm=*/56));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmpqHead, /*rs1=*/4));
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventPending, /*zimm=*/0x7));
    appendInsn32(
        text,
        encodeAddi(/*rd=*/7, /*rs1=*/0, /*imm=*/kExternalDynDescFaultRearmRefSuccessCode));
    appendInsn32(text, encodeEbreak());
    const size_t fail_label = text.size();
    appendInsn32(
        text,
        encodeAddi(/*rd=*/7, /*rs1=*/0, /*imm=*/kExternalDynDescFaultRearmRefFailCode));
    appendInsn32(text, encodeEbreak());

    patchBne(text, fail_branches[0], /*rs1=*/3, /*rs2=*/1, fail_label);
    patchBne(text, fail_branches[1], /*rs1=*/4, /*rs2=*/1, fail_label);
    patchBne(text, fail_branches[2], /*rs1=*/6, /*rs2=*/1, fail_label);
    patchBne(text, fail_branches[3], /*rs1=*/7, /*rs2=*/11, fail_label);
    patchBne(text, fail_branches[4], /*rs1=*/12, /*rs2=*/13, fail_label);
    patchBne(text, fail_branches[5], /*rs1=*/14, /*rs2=*/15, fail_label);
    patchBne(text, fail_branches[6], /*rs1=*/16, /*rs2=*/17, fail_label);
    patchBne(text, fail_branches[7], /*rs1=*/18, /*rs2=*/0, fail_label);
    patchBne(text, fail_branches[8], /*rs1=*/3, /*rs2=*/21, fail_label);
    patchBne(text, fail_branches[9], /*rs1=*/4, /*rs2=*/21, fail_label);
    patchBne(text, fail_branches[10], /*rs1=*/5, /*rs2=*/0, fail_label);
    patchBne(text, fail_branches[11], /*rs1=*/6, /*rs2=*/21, fail_label);
    patchBne(text, fail_branches[12], /*rs1=*/7, /*rs2=*/11, fail_label);
    patchBne(text, fail_branches[13], /*rs1=*/12, /*rs2=*/13, fail_label);
    patchBne(text, fail_branches[14], /*rs1=*/14, /*rs2=*/15, fail_label);
    patchBne(text, fail_branches[15], /*rs1=*/16, /*rs2=*/17, fail_label);
    return text;
}

inline std::vector<uint8_t> buildExternalDynDescFaultOverwriteChainRefRodata() {
    std::vector<uint8_t> rodata;
    rodata.reserve(120);
    appendProgramLeU64(rodata, kExternalDynDescFaultOverwriteChainRefFirstDescriptorHeader);
    appendProgramLeU64(rodata, kExternalDynDescFaultRefExpectedStatus);
    appendProgramLeU64(rodata, kExternalDynDescFaultRefExpectedFaultCsr);
    appendProgramLeU64(
        rodata,
        static_cast<uint32_t>(kExternalDynDescFaultRefExpectedFaultCsr & 0xFFFFFFFFu));
    appendProgramLeU64(
        rodata,
        static_cast<uint32_t>(kExternalDynDescFaultRefExpectedFaultCsr >> 32));
    appendProgramLeU64(rodata, kExternalDynDescFaultOverwriteChainRefSecondDescriptorHeader);
    appendProgramLeU64(rodata, kExternalDynDescBadPolicyRefExpectedStatus);
    appendProgramLeU64(rodata, kExternalDynDescFaultOverwriteChainRefSecondExpectedFaultCsr);
    appendProgramLeU64(
        rodata,
        static_cast<uint32_t>(kExternalDynDescFaultOverwriteChainRefSecondExpectedFaultCsr &
                              0xFFFFFFFFu));
    appendProgramLeU64(
        rodata,
        static_cast<uint32_t>(kExternalDynDescFaultOverwriteChainRefSecondExpectedFaultCsr >>
                              32));
    appendProgramLeU64(rodata, kExternalDynDescFaultOverwriteChainRefThirdDescriptorHeader);
    appendProgramLeU64(rodata, kExternalDynDescFaultRefExpectedStatus);
    appendProgramLeU64(rodata, kExternalDynDescFaultOverwriteChainRefThirdExpectedFaultCsr);
    appendProgramLeU64(
        rodata,
        static_cast<uint32_t>(kExternalDynDescFaultOverwriteChainRefThirdExpectedFaultCsr &
                              0xFFFFFFFFu));
    appendProgramLeU64(
        rodata,
        static_cast<uint32_t>(kExternalDynDescFaultOverwriteChainRefThirdExpectedFaultCsr >> 32));
    return rodata;
}

inline std::vector<uint8_t> buildExternalDynDescFaultOverwriteChainRefText() {
    using namespace SST::SnnDL::riscv_snn::asmv1;

    std::vector<uint8_t> text;
    std::vector<size_t> fail_branches;
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventEnable, /*zimm=*/0x7));
    appendInsn32(text, encodeCsrrs(/*rd=*/8, kCsrMsnnCmdqBase, /*rs1=*/0));
    appendInsn32(text, encodeCsrrs(/*rd=*/9, kCsrMsnnCmpqBase, /*rs1=*/0));
    appendInsn32(text, encodeAddi(/*rd=*/1, /*rs1=*/0, /*imm=*/1));
    appendInsn32(text, encodeAddi(/*rd=*/21, /*rs1=*/0, /*imm=*/2));
    appendInsn32(text, encodeAddi(/*rd=*/22, /*rs1=*/0, /*imm=*/3));
    appendInsn32(text, encodeLui(/*rd=*/10, /*imm20=*/0x9));

    appendInsn32(text, encodeLd(/*rd=*/2, /*rs1=*/10, /*imm=*/0));
    appendInsn32(text, encodeSd(/*rs2=*/2, /*rs1=*/8, /*imm=*/0));
    appendInsn32(text, encodeSd(/*rs2=*/1, /*rs1=*/8, /*imm=*/8));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/16));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/24));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/32));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/40));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/48));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/8, /*imm=*/56));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmdqTail, /*rs1=*/1));
    appendInsn32(text, encodeWfi());
    appendInsn32(text, encodeCsrrs(/*rd=*/3, kCsrMsnnCmdqHead, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/4, kCsrMsnnCmpqTail, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/6, /*rs1=*/9, /*imm=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/7, /*rs1=*/9, /*imm=*/4));
    appendInsn32(text, encodeLd(/*rd=*/11, /*rs1=*/10, /*imm=*/8));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/12, /*rs1=*/9, /*imm=*/8));
    appendInsn32(text, encodeLd(/*rd=*/13, /*rs1=*/10, /*imm=*/24));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/14, /*rs1=*/9, /*imm=*/12));
    appendInsn32(text, encodeLd(/*rd=*/15, /*rs1=*/10, /*imm=*/32));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/16, kCsrMsnnFault, /*rs1=*/0));
    appendInsn32(text, encodeLd(/*rd=*/17, /*rs1=*/10, /*imm=*/16));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmpqHead, /*rs1=*/4));
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventPending, /*zimm=*/0x7));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnFault, /*rs1=*/0));
    appendInsn32(text, encodeCsrrs(/*rd=*/18, kCsrMsnnFault, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));

    appendInsn32(text, encodeAddi(/*rd=*/20, /*rs1=*/8, /*imm=*/64));
    appendInsn32(text, encodeAddi(/*rd=*/19, /*rs1=*/9, /*imm=*/16));
    appendInsn32(text, encodeLd(/*rd=*/2, /*rs1=*/10, /*imm=*/40));
    appendInsn32(text, encodeSd(/*rs2=*/2, /*rs1=*/20, /*imm=*/0));
    appendInsn32(text, encodeSd(/*rs2=*/21, /*rs1=*/20, /*imm=*/8));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/20, /*imm=*/16));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/20, /*imm=*/24));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/20, /*imm=*/32));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/20, /*imm=*/40));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/20, /*imm=*/48));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/20, /*imm=*/56));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmdqTail, /*rs1=*/21));
    appendInsn32(text, encodeWfi());
    appendInsn32(text, encodeCsrrs(/*rd=*/3, kCsrMsnnCmdqHead, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/4, kCsrMsnnCmpqTail, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/5, kCsrMsnnStep, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/6, /*rs1=*/19, /*imm=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/7, /*rs1=*/19, /*imm=*/4));
    appendInsn32(text, encodeLd(/*rd=*/11, /*rs1=*/10, /*imm=*/48));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/12, /*rs1=*/19, /*imm=*/8));
    appendInsn32(text, encodeLd(/*rd=*/13, /*rs1=*/10, /*imm=*/64));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/14, /*rs1=*/19, /*imm=*/12));
    appendInsn32(text, encodeLd(/*rd=*/15, /*rs1=*/10, /*imm=*/72));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/16, kCsrMsnnFault, /*rs1=*/0));
    appendInsn32(text, encodeLd(/*rd=*/17, /*rs1=*/10, /*imm=*/56));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmpqHead, /*rs1=*/4));
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventPending, /*zimm=*/0x7));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnFault, /*rs1=*/0));
    appendInsn32(text, encodeCsrrs(/*rd=*/18, kCsrMsnnFault, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));

    appendInsn32(text, encodeAddi(/*rd=*/24, /*rs1=*/8, /*imm=*/128));
    appendInsn32(text, encodeAddi(/*rd=*/23, /*rs1=*/9, /*imm=*/32));
    appendInsn32(text, encodeLd(/*rd=*/2, /*rs1=*/10, /*imm=*/80));
    appendInsn32(text, encodeSd(/*rs2=*/2, /*rs1=*/24, /*imm=*/0));
    appendInsn32(text, encodeSd(/*rs2=*/22, /*rs1=*/24, /*imm=*/8));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/24, /*imm=*/16));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/24, /*imm=*/24));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/24, /*imm=*/32));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/24, /*imm=*/40));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/24, /*imm=*/48));
    appendInsn32(text, encodeSd(/*rs2=*/0, /*rs1=*/24, /*imm=*/56));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmdqTail, /*rs1=*/22));
    appendInsn32(text, encodeWfi());
    appendInsn32(text, encodeCsrrs(/*rd=*/3, kCsrMsnnCmdqHead, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/4, kCsrMsnnCmpqTail, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/5, kCsrMsnnStep, /*rs1=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/6, /*rs1=*/23, /*imm=*/0));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/7, /*rs1=*/23, /*imm=*/4));
    appendInsn32(text, encodeLd(/*rd=*/11, /*rs1=*/10, /*imm=*/88));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/12, /*rs1=*/23, /*imm=*/8));
    appendInsn32(text, encodeLd(/*rd=*/13, /*rs1=*/10, /*imm=*/104));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeLw(/*rd=*/14, /*rs1=*/23, /*imm=*/12));
    appendInsn32(text, encodeLd(/*rd=*/15, /*rs1=*/10, /*imm=*/112));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrs(/*rd=*/16, kCsrMsnnFault, /*rs1=*/0));
    appendInsn32(text, encodeLd(/*rd=*/17, /*rs1=*/10, /*imm=*/96));
    fail_branches.push_back(appendBnePlaceholder(text));
    appendInsn32(text, encodeCsrrw(/*rd=*/0, kCsrMsnnCmpqHead, /*rs1=*/4));
    appendInsn32(text, encodeCsrrwi(/*rd=*/0, kCsrMsnnEventPending, /*zimm=*/0x7));
    appendInsn32(
        text,
        encodeAddi(/*rd=*/7, /*rs1=*/0, /*imm=*/kExternalDynDescFaultOverwriteChainRefSuccessCode));
    appendInsn32(text, encodeEbreak());
    const size_t fail_label = text.size();
    appendInsn32(
        text,
        encodeAddi(/*rd=*/7, /*rs1=*/0, /*imm=*/kExternalDynDescFaultOverwriteChainRefFailCode));
    appendInsn32(text, encodeEbreak());

    patchBne(text, fail_branches[0], /*rs1=*/3, /*rs2=*/1, fail_label);
    patchBne(text, fail_branches[1], /*rs1=*/4, /*rs2=*/1, fail_label);
    patchBne(text, fail_branches[2], /*rs1=*/6, /*rs2=*/1, fail_label);
    patchBne(text, fail_branches[3], /*rs1=*/7, /*rs2=*/11, fail_label);
    patchBne(text, fail_branches[4], /*rs1=*/12, /*rs2=*/13, fail_label);
    patchBne(text, fail_branches[5], /*rs1=*/14, /*rs2=*/15, fail_label);
    patchBne(text, fail_branches[6], /*rs1=*/16, /*rs2=*/17, fail_label);
    patchBne(text, fail_branches[7], /*rs1=*/18, /*rs2=*/0, fail_label);
    patchBne(text, fail_branches[8], /*rs1=*/3, /*rs2=*/21, fail_label);
    patchBne(text, fail_branches[9], /*rs1=*/4, /*rs2=*/21, fail_label);
    patchBne(text, fail_branches[10], /*rs1=*/5, /*rs2=*/0, fail_label);
    patchBne(text, fail_branches[11], /*rs1=*/6, /*rs2=*/21, fail_label);
    patchBne(text, fail_branches[12], /*rs1=*/7, /*rs2=*/11, fail_label);
    patchBne(text, fail_branches[13], /*rs1=*/12, /*rs2=*/13, fail_label);
    patchBne(text, fail_branches[14], /*rs1=*/14, /*rs2=*/15, fail_label);
    patchBne(text, fail_branches[15], /*rs1=*/16, /*rs2=*/17, fail_label);
    patchBne(text, fail_branches[16], /*rs1=*/18, /*rs2=*/0, fail_label);
    patchBne(text, fail_branches[17], /*rs1=*/3, /*rs2=*/22, fail_label);
    patchBne(text, fail_branches[18], /*rs1=*/4, /*rs2=*/22, fail_label);
    patchBne(text, fail_branches[19], /*rs1=*/5, /*rs2=*/0, fail_label);
    patchBne(text, fail_branches[20], /*rs1=*/6, /*rs2=*/22, fail_label);
    patchBne(text, fail_branches[21], /*rs1=*/7, /*rs2=*/11, fail_label);
    patchBne(text, fail_branches[22], /*rs1=*/12, /*rs2=*/13, fail_label);
    patchBne(text, fail_branches[23], /*rs1=*/14, /*rs2=*/15, fail_label);
    patchBne(text, fail_branches[24], /*rs1=*/16, /*rs2=*/17, fail_label);
    return text;
}

} // namespace detail

inline bool buildSampleFirmwareProgram(const std::string& program,
                                       RiscvSnnSampleProgram& out,
                                       std::string& error) {
    out = RiscvSnnSampleProgram{};
    error.clear();

    if (program == "external_p0") {
        RiscvSnnElfLoadSegment data_segment{};
        data_segment.vaddr = kExternalP0DataBase;
        data_segment.flags = 0x6;
        data_segment.file_data = detail::buildExternalP0Data();
        data_segment.mem_size = static_cast<uint64_t>(data_segment.file_data.size());

        RiscvSnnElfLoadSegment text_segment{};
        text_segment.vaddr = kExternalP0TextBase;
        text_segment.flags = 0x5;
        text_segment.file_data = detail::buildExternalP0Text();
        text_segment.mem_size = static_cast<uint64_t>(text_segment.file_data.size());

        out.entry_pc = kExternalP0TextBase;
        out.segments = {data_segment, text_segment};
        return true;
    }

    if (program == "external_dyn_desc") {
        RiscvSnnElfLoadSegment text_segment{};
        text_segment.vaddr = kExternalDynDescTextBase;
        text_segment.flags = 0x5;
        text_segment.file_data = detail::buildExternalDynDescText();
        text_segment.mem_size = static_cast<uint64_t>(text_segment.file_data.size());

        out.entry_pc = kExternalDynDescTextBase;
        out.segments = {text_segment};
        return true;
    }

    if (program == "external_dyn_desc_ref") {
        RiscvSnnElfLoadSegment text_segment{};
        text_segment.vaddr = kExternalDynDescRefTextBase;
        text_segment.flags = 0x5;
        text_segment.file_data = detail::buildExternalDynDescRefText();
        text_segment.mem_size = static_cast<uint64_t>(text_segment.file_data.size());

        RiscvSnnElfLoadSegment rodata_segment{};
        rodata_segment.vaddr = kExternalDynDescRefRodataBase;
        rodata_segment.flags = 0x4;
        rodata_segment.file_data = detail::buildExternalDynDescRefRodata();
        rodata_segment.mem_size = static_cast<uint64_t>(rodata_segment.file_data.size());

        out.entry_pc = kExternalDynDescRefTextBase;
        out.segments = {text_segment, rodata_segment};
        return true;
    }

    if (program == "external_dyn_desc_fault_ref") {
        RiscvSnnElfLoadSegment text_segment{};
        text_segment.vaddr = kExternalDynDescFaultRefTextBase;
        text_segment.flags = 0x5;
        text_segment.file_data = detail::buildExternalDynDescFaultRefText();
        text_segment.mem_size = static_cast<uint64_t>(text_segment.file_data.size());

        RiscvSnnElfLoadSegment rodata_segment{};
        rodata_segment.vaddr = kExternalDynDescFaultRefRodataBase;
        rodata_segment.flags = 0x4;
        rodata_segment.file_data = detail::buildExternalDynDescFaultRefRodata();
        rodata_segment.mem_size = static_cast<uint64_t>(rodata_segment.file_data.size());

        out.entry_pc = kExternalDynDescFaultRefTextBase;
        out.segments = {text_segment, rodata_segment};
        return true;
    }

    if (program == "external_dyn_desc_bad_policy_ref") {
        RiscvSnnElfLoadSegment text_segment{};
        text_segment.vaddr = kExternalDynDescBadPolicyRefTextBase;
        text_segment.flags = 0x5;
        text_segment.file_data = detail::buildExternalDynDescBadPolicyRefText();
        text_segment.mem_size = static_cast<uint64_t>(text_segment.file_data.size());

        RiscvSnnElfLoadSegment rodata_segment{};
        rodata_segment.vaddr = kExternalDynDescBadPolicyRefRodataBase;
        rodata_segment.flags = 0x4;
        rodata_segment.file_data = detail::buildExternalDynDescBadPolicyRefRodata();
        rodata_segment.mem_size = static_cast<uint64_t>(rodata_segment.file_data.size());

        out.entry_pc = kExternalDynDescBadPolicyRefTextBase;
        out.segments = {text_segment, rodata_segment};
        return true;
    }

    if (program == "external_dyn_desc_fault_rearm_ref") {
        RiscvSnnElfLoadSegment text_segment{};
        text_segment.vaddr = kExternalDynDescFaultRearmRefTextBase;
        text_segment.flags = 0x5;
        text_segment.file_data = detail::buildExternalDynDescFaultRearmRefText();
        text_segment.mem_size = static_cast<uint64_t>(text_segment.file_data.size());

        RiscvSnnElfLoadSegment rodata_segment{};
        rodata_segment.vaddr = kExternalDynDescFaultRearmRefRodataBase;
        rodata_segment.flags = 0x4;
        rodata_segment.file_data = detail::buildExternalDynDescFaultRearmRefRodata();
        rodata_segment.mem_size = static_cast<uint64_t>(rodata_segment.file_data.size());

        out.entry_pc = kExternalDynDescFaultRearmRefTextBase;
        out.segments = {text_segment, rodata_segment};
        return true;
    }

    if (program == "external_dyn_desc_fault_overwrite_chain_ref") {
        RiscvSnnElfLoadSegment text_segment{};
        text_segment.vaddr = kExternalDynDescFaultOverwriteChainRefTextBase;
        text_segment.flags = 0x5;
        text_segment.file_data = detail::buildExternalDynDescFaultOverwriteChainRefText();
        text_segment.mem_size = static_cast<uint64_t>(text_segment.file_data.size());

        RiscvSnnElfLoadSegment rodata_segment{};
        rodata_segment.vaddr = kExternalDynDescFaultOverwriteChainRefRodataBase;
        rodata_segment.flags = 0x4;
        rodata_segment.file_data = detail::buildExternalDynDescFaultOverwriteChainRefRodata();
        rodata_segment.mem_size = static_cast<uint64_t>(rodata_segment.file_data.size());

        out.entry_pc = kExternalDynDescFaultOverwriteChainRefTextBase;
        out.segments = {text_segment, rodata_segment};
        return true;
    }

    if (program == "barrier_wfi_order_ref") {
        RiscvSnnElfLoadSegment text_segment{};
        text_segment.vaddr = kBarrierWfiOrderRefTextBase;
        text_segment.flags = 0x5;
        text_segment.file_data = detail::buildBarrierWfiOrderRefText();
        text_segment.mem_size = static_cast<uint64_t>(text_segment.file_data.size());

        RiscvSnnElfLoadSegment rodata_segment{};
        rodata_segment.vaddr = kBarrierWfiOrderRefRodataBase;
        rodata_segment.flags = 0x4;
        rodata_segment.file_data = detail::buildBarrierWfiOrderRefRodata();
        rodata_segment.mem_size = static_cast<uint64_t>(rodata_segment.file_data.size());

        out.entry_pc = kBarrierWfiOrderRefTextBase;
        out.segments = {text_segment, rodata_segment};
        return true;
    }

    if (program == "queue_backpressure_ref") {
        RiscvSnnElfLoadSegment text_segment{};
        text_segment.vaddr = kQueueBackpressureRefTextBase;
        text_segment.flags = 0x5;
        text_segment.file_data = detail::buildQueueBackpressureRefText();
        text_segment.mem_size = static_cast<uint64_t>(text_segment.file_data.size());

        RiscvSnnElfLoadSegment rodata_segment{};
        rodata_segment.vaddr = kQueueBackpressureRefRodataBase;
        rodata_segment.flags = 0x4;
        rodata_segment.file_data = detail::buildQueueBackpressureRefRodata();
        rodata_segment.mem_size = static_cast<uint64_t>(rodata_segment.file_data.size());

        out.entry_pc = kQueueBackpressureRefTextBase;
        out.segments = {text_segment, rodata_segment};
        return true;
    }

    if (program == "completion_queue_overflow_ref") {
        RiscvSnnElfLoadSegment text_segment{};
        text_segment.vaddr = kCompletionQueueOverflowRefTextBase;
        text_segment.flags = 0x5;
        text_segment.file_data = detail::buildCompletionQueueOverflowRefText();
        text_segment.mem_size = static_cast<uint64_t>(text_segment.file_data.size());

        RiscvSnnElfLoadSegment rodata_segment{};
        rodata_segment.vaddr = kCompletionQueueOverflowRefRodataBase;
        rodata_segment.flags = 0x4;
        rodata_segment.file_data = detail::buildCompletionQueueOverflowRefRodata();
        rodata_segment.mem_size = static_cast<uint64_t>(rodata_segment.file_data.size());

        out.entry_pc = kCompletionQueueOverflowRefTextBase;
        out.segments = {text_segment, rodata_segment};
        return true;
    }

    if (program == "stat_snapshot_ref") {
        RiscvSnnElfLoadSegment text_segment{};
        text_segment.vaddr = kStatSnapshotRefTextBase;
        text_segment.flags = 0x5;
        text_segment.file_data = detail::buildStatSnapshotRefText();
        text_segment.mem_size = static_cast<uint64_t>(text_segment.file_data.size());

        RiscvSnnElfLoadSegment rodata_segment{};
        rodata_segment.vaddr = kStatSnapshotRefRodataBase;
        rodata_segment.flags = 0x4;
        rodata_segment.file_data = detail::buildStatSnapshotRefRodata();
        rodata_segment.mem_size = static_cast<uint64_t>(rodata_segment.file_data.size());

        out.entry_pc = kStatSnapshotRefTextBase;
        out.segments = {text_segment, rodata_segment};
        return true;
    }

    if (program == "stat_snapshot_completed_ref") {
        RiscvSnnElfLoadSegment text_segment{};
        text_segment.vaddr = kStatSnapshotCompletedRefTextBase;
        text_segment.flags = 0x5;
        text_segment.file_data = detail::buildStatSnapshotCompletedRefText();
        text_segment.mem_size = static_cast<uint64_t>(text_segment.file_data.size());

        RiscvSnnElfLoadSegment rodata_segment{};
        rodata_segment.vaddr = kStatSnapshotCompletedRefRodataBase;
        rodata_segment.flags = 0x4;
        rodata_segment.file_data = detail::buildStatSnapshotCompletedRefRodata();
        rodata_segment.mem_size = static_cast<uint64_t>(rodata_segment.file_data.size());

        out.entry_pc = kStatSnapshotCompletedRefTextBase;
        out.segments = {text_segment, rodata_segment};
        return true;
    }

    if (program == "stat_snapshot_provider_bound_ref") {
        RiscvSnnElfLoadSegment text_segment{};
        text_segment.vaddr = kStatSnapshotProviderBoundRefTextBase;
        text_segment.flags = 0x5;
        text_segment.file_data = detail::buildStatSnapshotProviderBoundRefText();
        text_segment.mem_size = static_cast<uint64_t>(text_segment.file_data.size());

        RiscvSnnElfLoadSegment rodata_segment{};
        rodata_segment.vaddr = kStatSnapshotProviderBoundRefRodataBase;
        rodata_segment.flags = 0x4;
        rodata_segment.file_data = detail::buildStatSnapshotProviderBoundRefRodata();
        rodata_segment.mem_size = static_cast<uint64_t>(rodata_segment.file_data.size());

        out.entry_pc = kStatSnapshotProviderBoundRefTextBase;
        out.segments = {text_segment, rodata_segment};
        return true;
    }

    if (program == "stat_snapshot_bad_selector_ref") {
        RiscvSnnElfLoadSegment text_segment{};
        text_segment.vaddr = kStatSnapshotBadSelectorRefTextBase;
        text_segment.flags = 0x5;
        text_segment.file_data = detail::buildStatSnapshotBadSelectorRefText();
        text_segment.mem_size = static_cast<uint64_t>(text_segment.file_data.size());

        RiscvSnnElfLoadSegment rodata_segment{};
        rodata_segment.vaddr = kStatSnapshotBadSelectorRefRodataBase;
        rodata_segment.flags = 0x4;
        rodata_segment.file_data = detail::buildStatSnapshotBadSelectorRefRodata();
        rodata_segment.mem_size = static_cast<uint64_t>(rodata_segment.file_data.size());

        out.entry_pc = kStatSnapshotBadSelectorRefTextBase;
        out.segments = {text_segment, rodata_segment};
        return true;
    }

    error = "unsupported program: " + program;
    return false;
}

} // namespace samplefwv1

inline const std::vector<RiscvSnnSampleMetadata>& sampleFirmwareMetadata() {
    return samplefwv1::sampleFirmwareMetadata();
}

inline const std::vector<std::string>& sampleFirmwareProgramNames() {
    return samplefwv1::sampleFirmwareProgramNames();
}

inline const std::vector<std::string>& canonicalSampleFirmwareProgramNames() {
    return samplefwv1::canonicalSampleFirmwareProgramNames();
}

inline bool lookupSampleFirmwareMetadata(const std::string& program,
                                         RiscvSnnSampleMetadata& out,
                                         std::string& error) {
    return samplefwv1::lookupSampleFirmwareMetadata(program, out, error);
}

inline bool buildSampleFirmwareProgram(const std::string& program,
                                       RiscvSnnSampleProgram& out,
                                       std::string& error) {
    return samplefwv1::buildSampleFirmwareProgram(program, out, error);
}

}}} // namespace SST::SnnDL::riscv_snn
