// -*- c++ -*-
//
// PeInternalPodShadowGate:
// - Isolated helper for PE-internal pod metadata overlap + owner/join shadow flow.
// - Keeps the experimental Phase-1 gate testable without instantiating full WMS.

#pragma once

#include <algorithm>
#include <cstdint>

#include "services/local_storage/PodMetadataObjectPlane.h"
#include "services/local_storage/PodOwnerServiceTable.h"
#include "services/pe_fabric/PeSharedCoreFabric.h"

namespace SST { namespace SnnDL {

struct PeInternalPodShadowGateConfig {
    bool pe_internal_cpe_enable = false;
    bool pe_internal_pod_enable = false;
    bool pe_internal_pod_metadata_enable = false;
    bool pe_internal_pod_owner_enable = false;
    uint32_t core_id = 0;
    uint32_t pod_id = 0;
    uint32_t pod_count = 1;
    uint32_t window_seq = 0;
};

struct PeInternalPodShadowGateBindings {
    PodMetadataObjectPlane* metadata_plane = nullptr;
    PodOwnerServiceTable* owner_table = nullptr;
    PeSharedCoreFabric* fabric = nullptr;
};

struct PeInternalPodShadowGateCounters {
    uint64_t guard_drop_total = 0;
    uint64_t guard_disabled_total = 0;
    uint64_t guard_missing_metadata_plane_total = 0;
    uint64_t guard_missing_owner_table_total = 0;
    uint64_t guard_zero_pod_count_total = 0;
    uint64_t guard_window_zero_total = 0;
    uint64_t guard_invalid_cfg_pod_total = 0;
    uint64_t guard_rowdescriptor_disabled_total = 0;
    uint64_t guard_rowdescriptor_missing_metadata_plane_total = 0;
    uint64_t guard_rowdescriptor_missing_owner_table_total = 0;
    uint64_t guard_rowdescriptor_zero_pod_count_total = 0;
    uint64_t guard_rowdescriptor_window_zero_total = 0;
    uint64_t guard_rowdescriptor_invalid_cfg_pod_total = 0;
    uint64_t guard_base_total = 0;
    uint64_t guard_band_total = 0;
    uint64_t guard_other_total = 0;
    uint64_t guard_idx2row_total = 0;
    uint64_t guard_rowindex_total = 0;
    uint64_t guard_rowdescriptor_total = 0;
    uint64_t frontier_export_total = 0;
    uint64_t frontier_consumer_count_sum_total = 0;
    uint64_t frontier_overlap_strength_sum_total = 0;
    uint64_t frontier_base_consumer_count_sum_total = 0;
    uint64_t frontier_base_overlap_strength_sum_total = 0;
    uint64_t frontier_band_consumer_count_sum_total = 0;
    uint64_t frontier_band_overlap_strength_sum_total = 0;
    uint64_t owner_lookup_total = 0;
    uint64_t owner_alloc_total = 0;
    uint64_t owner_alloc_idx2row_total = 0;
    uint64_t owner_alloc_rowindex_total = 0;
    uint64_t owner_alloc_rowdescriptor_total = 0;
    uint64_t owner_hit_total = 0;
    uint64_t owner_hit_idx2row_total = 0;
    uint64_t owner_hit_rowindex_total = 0;
    uint64_t owner_hit_rowdescriptor_total = 0;
    uint64_t owner_reject_total = 0;
    uint64_t owner_disabled_reject_total = 0;
    uint64_t owner_invalid_pod_reject_total = 0;
    uint64_t owner_table_full_reject_total = 0;
    uint64_t join_request_total = 0;
    uint64_t join_grant_total = 0;
    uint64_t join_reject_total = 0;
    uint64_t join_table_disabled_reject_total = 0;
    uint64_t join_duplicate_consumer_reject_total = 0;
    uint64_t join_table_full_reject_total = 0;
    uint64_t join_before_private_issue_total = 0;
    uint64_t owner_first_issue_deferred_total = 0;
    uint64_t owner_first_issue_deferred_idx2row_total = 0;
    uint64_t owner_first_issue_deferred_rowindex_total = 0;
    uint64_t owner_first_issue_deferred_rowdescriptor_total = 0;
    uint64_t owner_first_private_issue_avoided_total = 0;
    uint64_t owner_first_private_issue_avoided_idx2row_total = 0;
    uint64_t owner_first_private_issue_avoided_rowindex_total = 0;
    uint64_t owner_first_private_issue_avoided_rowdescriptor_total = 0;
    uint64_t reject_base_total = 0;
    uint64_t reject_band_total = 0;
    uint64_t reject_other_total = 0;
    uint64_t reject_idx2row_total = 0;
    uint64_t reject_rowindex_total = 0;
    uint64_t reject_rowdescriptor_total = 0;
    uint64_t useful_total = 0;
    uint64_t useful_join_grant_total = 0;
    uint64_t useful_duplicate_replay_elide_total = 0;
    uint64_t useful_base_total = 0;
    uint64_t useful_band_total = 0;
    uint64_t useful_other_total = 0;
    uint64_t useful_idx2row_total = 0;
    uint64_t useful_rowindex_total = 0;
    uint64_t useful_rowdescriptor_total = 0;
    uint64_t attempted_total = 0;
    uint64_t attempted_guard_total = 0;
    uint64_t attempted_reject_total = 0;
    uint64_t attempted_useful_total = 0;
    uint64_t attempted_base_total = 0;
    uint64_t attempted_band_total = 0;
    uint64_t attempted_other_total = 0;
    uint64_t attempted_idx2row_total = 0;
    uint64_t attempted_rowindex_total = 0;
    uint64_t attempted_rowdescriptor_total = 0;
    uint64_t duplicate_metadata_replay_elided_total = 0;
    uint64_t duplicate_metadata_issue_elided_total = 0;
    uint64_t fallback_private_issue_total = 0;

    void noteGuardShape(PodMetadataObjectPlane::MetadataKind kind) {
        noteShapeCounter(kind, guard_base_total, guard_band_total, guard_other_total);
        noteOtherKindCounter(
            kind, guard_idx2row_total, guard_rowindex_total, guard_rowdescriptor_total);
    }

    void noteRejectShape(PodMetadataObjectPlane::MetadataKind kind) {
        noteShapeCounter(kind, reject_base_total, reject_band_total, reject_other_total);
        noteOtherKindCounter(
            kind, reject_idx2row_total, reject_rowindex_total, reject_rowdescriptor_total);
    }

    void noteUsefulShape(PodMetadataObjectPlane::MetadataKind kind) {
        noteShapeCounter(kind, useful_base_total, useful_band_total, useful_other_total);
        noteOtherKindCounter(
            kind, useful_idx2row_total, useful_rowindex_total, useful_rowdescriptor_total);
    }

    void noteOwnerAllocKind(PodMetadataObjectPlane::MetadataKind kind) {
        noteOtherKindCounter(
            kind,
            owner_alloc_idx2row_total,
            owner_alloc_rowindex_total,
            owner_alloc_rowdescriptor_total);
    }

    void noteOwnerHitKind(PodMetadataObjectPlane::MetadataKind kind) {
        noteOtherKindCounter(
            kind,
            owner_hit_idx2row_total,
            owner_hit_rowindex_total,
            owner_hit_rowdescriptor_total);
    }

    void noteOwnerFirstIssueDeferredKind(PodMetadataObjectPlane::MetadataKind kind) {
        noteOtherKindCounter(
            kind,
            owner_first_issue_deferred_idx2row_total,
            owner_first_issue_deferred_rowindex_total,
            owner_first_issue_deferred_rowdescriptor_total);
    }

    void noteOwnerFirstPrivateIssueAvoidedKind(PodMetadataObjectPlane::MetadataKind kind) {
        noteOtherKindCounter(
            kind,
            owner_first_private_issue_avoided_idx2row_total,
            owner_first_private_issue_avoided_rowindex_total,
            owner_first_private_issue_avoided_rowdescriptor_total);
    }

    void refreshAttemptedView() {
        attempted_guard_total = guard_drop_total;
        attempted_reject_total = owner_reject_total + join_reject_total;
        attempted_useful_total = useful_total;
        attempted_base_total = guard_base_total + reject_base_total + useful_base_total;
        attempted_band_total = guard_band_total + reject_band_total + useful_band_total;
        attempted_other_total = guard_other_total + reject_other_total + useful_other_total;
        attempted_idx2row_total =
            guard_idx2row_total + reject_idx2row_total + useful_idx2row_total;
        attempted_rowindex_total =
            guard_rowindex_total + reject_rowindex_total + useful_rowindex_total;
        attempted_rowdescriptor_total =
            guard_rowdescriptor_total + reject_rowdescriptor_total + useful_rowdescriptor_total;
        attempted_total =
            attempted_guard_total + attempted_reject_total + attempted_useful_total;
    }

private:
    static void noteShapeCounter(PodMetadataObjectPlane::MetadataKind kind,
                                 uint64_t& base,
                                 uint64_t& band,
                                 uint64_t& other) {
        switch (kind) {
        case PodMetadataObjectPlane::MetadataKind::PreMphfBase:
            base += 1u;
            return;
        case PodMetadataObjectPlane::MetadataKind::PreMphfBand:
            band += 1u;
            return;
        default:
            other += 1u;
            return;
        }
    }

    static void noteOtherKindCounter(PodMetadataObjectPlane::MetadataKind kind,
                                     uint64_t& idx2row,
                                     uint64_t& rowindex,
                                     uint64_t& rowdescriptor) {
        switch (kind) {
        case PodMetadataObjectPlane::MetadataKind::Idx2Row:
            idx2row += 1u;
            return;
        case PodMetadataObjectPlane::MetadataKind::RowIndex:
            rowindex += 1u;
            return;
        case PodMetadataObjectPlane::MetadataKind::RowDescriptor:
            rowdescriptor += 1u;
            return;
        default:
            return;
        }
    }
};

class PeInternalPodShadowGate {
public:
    static bool enabled(const PeInternalPodShadowGateConfig& cfg,
                        const PeInternalPodShadowGateBindings& bindings) {
        return cfg.pe_internal_cpe_enable &&
               cfg.pe_internal_pod_enable &&
               cfg.pe_internal_pod_metadata_enable &&
               cfg.pe_internal_pod_owner_enable &&
               bindings.metadata_plane != nullptr &&
               bindings.owner_table != nullptr &&
               cfg.pod_count > 0u;
    }

    static void observe(const PeInternalPodShadowGateConfig& cfg,
                        const PeInternalPodShadowGateBindings& bindings,
                        PodMetadataObjectPlane::MetadataKind kind,
                        uint64_t object_id,
                        PeInternalPodShadowGateCounters& counters) {
        struct AttemptedViewScopeRefresh {
            PeInternalPodShadowGateCounters& counters;

            ~AttemptedViewScopeRefresh() { counters.refreshAttemptedView(); }
        } attempted_view_scope_refresh{counters};

        auto guard_drop =
            [&counters, kind](uint64_t& reason_counter, uint64_t& rowdescriptor_reason_counter) {
            counters.guard_drop_total += 1u;
            reason_counter += 1u;
            if (kind == PodMetadataObjectPlane::MetadataKind::RowDescriptor) {
                rowdescriptor_reason_counter += 1u;
            }
        };

        if (!cfg.pe_internal_cpe_enable ||
            !cfg.pe_internal_pod_enable ||
            !cfg.pe_internal_pod_metadata_enable ||
            !cfg.pe_internal_pod_owner_enable) {
            guard_drop(
                counters.guard_disabled_total,
                counters.guard_rowdescriptor_disabled_total);
            counters.noteGuardShape(kind);
            return;
        }
        if (bindings.metadata_plane == nullptr) {
            guard_drop(
                counters.guard_missing_metadata_plane_total,
                counters.guard_rowdescriptor_missing_metadata_plane_total);
            counters.noteGuardShape(kind);
            return;
        }
        if (bindings.owner_table == nullptr) {
            guard_drop(
                counters.guard_missing_owner_table_total,
                counters.guard_rowdescriptor_missing_owner_table_total);
            counters.noteGuardShape(kind);
            return;
        }
        if (cfg.pod_count == 0u) {
            guard_drop(
                counters.guard_zero_pod_count_total,
                counters.guard_rowdescriptor_zero_pod_count_total);
            counters.noteGuardShape(kind);
            return;
        }
        if (cfg.window_seq == 0u) {
            guard_drop(
                counters.guard_window_zero_total,
                counters.guard_rowdescriptor_window_zero_total);
            counters.noteGuardShape(kind);
            return;
        }
        if (cfg.pod_id >= cfg.pod_count) {
            guard_drop(
                counters.guard_invalid_cfg_pod_total,
                counters.guard_rowdescriptor_invalid_cfg_pod_total);
            counters.noteGuardShape(kind);
            return;
        }

        const uint32_t pod_id = cfg.pod_id;

        PodMetadataObjectPlane::ObserveRequest observe{};
        observe.pod_id = pod_id;
        observe.window_seq = cfg.window_seq;
        observe.kind = kind;
        observe.object_id = object_id;
        observe.core_id = cfg.core_id;

        const auto observed = bindings.metadata_plane->observe(observe);
        if (!observed.valid || !observed.accepted) return;
        if (observed.duplicate_consumer) {
            counters.useful_total += 1u;
            counters.useful_duplicate_replay_elide_total += 1u;
            counters.noteUsefulShape(kind);
            counters.duplicate_metadata_replay_elided_total += 1u;
            counters.duplicate_metadata_issue_elided_total += 1u;
            return;
        }

        counters.frontier_export_total += 1u;
        counters.frontier_consumer_count_sum_total +=
            static_cast<uint64_t>(observed.total_consumers);
        counters.frontier_overlap_strength_sum_total +=
            static_cast<uint64_t>(observed.prior_consumers);
        switch (kind) {
        case PodMetadataObjectPlane::MetadataKind::PreMphfBase:
            counters.frontier_base_consumer_count_sum_total +=
                static_cast<uint64_t>(observed.total_consumers);
            counters.frontier_base_overlap_strength_sum_total +=
                static_cast<uint64_t>(observed.prior_consumers);
            break;
        case PodMetadataObjectPlane::MetadataKind::PreMphfBand:
            counters.frontier_band_consumer_count_sum_total +=
                static_cast<uint64_t>(observed.total_consumers);
            counters.frontier_band_overlap_strength_sum_total +=
                static_cast<uint64_t>(observed.prior_consumers);
            break;
        default:
            break;
        }
        if (bindings.fabric != nullptr) {
            PeSharedCoreFabric::ControlMessage frontier{};
            frontier.kind = PeSharedCoreFabric::ControlMessageKind::FrontierExport;
            frontier.scope_id = pod_id;
            frontier.producer_core_id = cfg.core_id;
            frontier.window_seq = cfg.window_seq;
            frontier.object_key = observed.object_key;
            frontier.consumer_bitmap = observed.consumer_bitmap;
            bindings.fabric->enqueueControlMessage(frontier);
        }

        counters.owner_lookup_total += 1u;
        PodOwnerServiceTable::LookupRequest lookup{};
        lookup.pod_id = pod_id;
        lookup.window_seq = cfg.window_seq;
        lookup.object_key = observed.object_key;
        lookup.core_id = cfg.core_id;

        const auto lookup_result = bindings.owner_table->lookupOrAllocate(lookup);
        if (!lookup_result.valid) {
            counters.owner_reject_total += 1u;
            counters.noteRejectShape(kind);
            if (lookup_result.reject_reason ==
                PodOwnerServiceTable::RejectReason::Disabled) {
                counters.owner_disabled_reject_total += 1u;
            } else if (lookup_result.reject_reason ==
                       PodOwnerServiceTable::RejectReason::InvalidPod) {
                counters.owner_invalid_pod_reject_total += 1u;
            } else if (lookup_result.reject_reason ==
                       PodOwnerServiceTable::RejectReason::TableFull) {
                counters.owner_table_full_reject_total += 1u;
            }
            counters.fallback_private_issue_total += 1u;
            if (bindings.fabric != nullptr) {
                PeSharedCoreFabric::ControlMessage reject{};
                reject.kind = PeSharedCoreFabric::ControlMessageKind::JoinReject;
                reject.scope_id = pod_id;
                reject.producer_core_id = cfg.core_id;
                reject.window_seq = cfg.window_seq;
                reject.object_key = observed.object_key;
                reject.reject_reason =
                    static_cast<uint32_t>(lookup_result.reject_reason);
                bindings.fabric->enqueueControlMessage(reject);
            }
            return;
        }

        if (lookup_result.allocated_owner) {
            counters.owner_alloc_total += 1u;
            counters.noteOwnerAllocKind(kind);
            if (bindings.fabric != nullptr) {
                PeSharedCoreFabric::ControlMessage owner{};
                owner.kind = PeSharedCoreFabric::ControlMessageKind::OwnerAnnounce;
                owner.scope_id = pod_id;
                owner.producer_core_id = cfg.core_id;
                owner.owner_core_id = lookup_result.owner_core_id;
                owner.window_seq = cfg.window_seq;
                owner.object_key = observed.object_key;
                owner.transaction_id = lookup_result.transaction_id;
                owner.consumer_bitmap = lookup_result.consumer_bitmap;
                bindings.fabric->enqueueControlMessage(owner);
            }
            counters.fallback_private_issue_total += 1u;
            return;
        }

        counters.owner_hit_total += 1u;
        counters.noteOwnerHitKind(kind);
        if (bindings.owner_table->config().join_entries_per_pod == 0u) {
            counters.join_reject_total += 1u;
            counters.noteRejectShape(kind);
            counters.join_table_disabled_reject_total += 1u;
            counters.fallback_private_issue_total += 1u;
            if (bindings.fabric != nullptr) {
                PeSharedCoreFabric::ControlMessage reject{};
                reject.kind = PeSharedCoreFabric::ControlMessageKind::JoinReject;
                reject.scope_id = pod_id;
                reject.producer_core_id = cfg.core_id;
                reject.owner_core_id = lookup_result.owner_core_id;
                reject.consumer_core_id = cfg.core_id;
                reject.window_seq = cfg.window_seq;
                reject.object_key = observed.object_key;
                reject.transaction_id = lookup_result.transaction_id;
                reject.reject_reason = static_cast<uint32_t>(
                    PodOwnerServiceTable::RejectReason::JoinTableDisabled);
                bindings.fabric->enqueueControlMessage(reject);
            }
            return;
        }

        counters.join_request_total += 1u;
        if (bindings.fabric != nullptr) {
            PeSharedCoreFabric::ControlMessage join_msg{};
            join_msg.kind = PeSharedCoreFabric::ControlMessageKind::JoinRequest;
            join_msg.scope_id = pod_id;
            join_msg.producer_core_id = cfg.core_id;
            join_msg.owner_core_id = lookup_result.owner_core_id;
            join_msg.consumer_core_id = cfg.core_id;
            join_msg.window_seq = cfg.window_seq;
            join_msg.object_key = observed.object_key;
            join_msg.transaction_id = lookup_result.transaction_id;
            join_msg.consumer_bitmap = lookup_result.consumer_bitmap;
            bindings.fabric->enqueueControlMessage(join_msg);
        }

        PodOwnerServiceTable::JoinRequest join{};
        join.pod_id = pod_id;
        join.window_seq = cfg.window_seq;
        join.object_key = observed.object_key;
        join.consumer_core_id = cfg.core_id;

        const auto join_result = bindings.owner_table->join(join);
        if (!join_result.valid || !join_result.granted || join_result.duplicate_consumer) {
            counters.join_reject_total += 1u;
            counters.noteRejectShape(kind);
            if (join_result.reject_reason ==
                PodOwnerServiceTable::RejectReason::JoinTableDisabled) {
                counters.join_table_disabled_reject_total += 1u;
            } else if (join_result.reject_reason ==
                       PodOwnerServiceTable::RejectReason::DuplicateConsumer) {
                counters.join_duplicate_consumer_reject_total += 1u;
            } else if (join_result.reject_reason ==
                       PodOwnerServiceTable::RejectReason::TableFull) {
                counters.join_table_full_reject_total += 1u;
            }
            counters.fallback_private_issue_total += 1u;
            if (bindings.fabric != nullptr) {
                PeSharedCoreFabric::ControlMessage reject{};
                reject.kind = PeSharedCoreFabric::ControlMessageKind::JoinReject;
                reject.scope_id = pod_id;
                reject.producer_core_id = cfg.core_id;
                reject.owner_core_id = lookup_result.owner_core_id;
                reject.consumer_core_id = cfg.core_id;
                reject.window_seq = cfg.window_seq;
                reject.object_key = observed.object_key;
                reject.transaction_id = lookup_result.transaction_id;
                reject.reject_reason = static_cast<uint32_t>(join_result.reject_reason);
                bindings.fabric->enqueueControlMessage(reject);
            }
            return;
        }

        counters.join_grant_total += 1u;
        counters.join_before_private_issue_total += 1u;
        counters.owner_first_issue_deferred_total += 1u;
        counters.noteOwnerFirstIssueDeferredKind(kind);
        counters.owner_first_private_issue_avoided_total += 1u;
        counters.noteOwnerFirstPrivateIssueAvoidedKind(kind);
        counters.useful_total += 1u;
        counters.useful_join_grant_total += 1u;
        counters.noteUsefulShape(kind);
        counters.duplicate_metadata_issue_elided_total += 1u;
        counters.fallback_private_issue_total += 1u;
    }
};

}} // namespace SST::SnnDL
