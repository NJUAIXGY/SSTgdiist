// -*- c++ -*-

#include "services/local_storage/PeWeightObjectPlane.h"

namespace SST { namespace SnnDL {

namespace {

void exportAuthorityClass_(std::map<std::string, uint64_t>& stats,
                           const std::string& prefix,
                           PeWeightObjectPlane::AuthorityClass authority) {
    stats[prefix + "private_authority"] =
        authority == PeWeightObjectPlane::AuthorityClass::PrivateAuthority ? 1u : 0u;
    stats[prefix + "shared_mirror_only"] =
        authority == PeWeightObjectPlane::AuthorityClass::SharedMirrorOnly ? 1u : 0u;
    stats[prefix + "shared_authority_active"] =
        authority == PeWeightObjectPlane::AuthorityClass::SharedAuthorityActive ? 1u : 0u;
}

void exportBankedSramStats_(std::map<std::string, uint64_t>& stats,
                            const std::string& prefix,
                            const BankedSramStats& s) {
    stats[prefix + "reads_total"] = s.reads_total;
    stats[prefix + "writes_total"] = s.writes_total;
    stats[prefix + "bytes_read_total"] = s.bytes_read_total;
    stats[prefix + "bytes_write_total"] = s.bytes_write_total;
    stats[prefix + "bank_conflict_ticks_total"] = s.bank_conflict_ticks_total;
    stats[prefix + "bank_conflict_events_total"] = s.bank_conflict_events_total;
    stats[prefix + "predicted_extra_cycles_total"] = s.predicted_extra_cycles_total;
    stats[prefix + "bank_peak_accesses_per_tick"] = s.bank_peak_accesses_per_tick;
    stats[prefix + "resident_bytes_last"] = s.resident_bytes_last;
    stats[prefix + "resident_bytes_peak"] = s.resident_bytes_peak;
    stats[prefix + "capacity_exceeded_events_total"] = s.capacity_exceeded_events_total;
}

} // namespace

void PeWeightObjectPlane::exportStatsToMap(std::map<std::string, uint64_t>& stats,
                                           const std::string& prefix) const {
    const auto snap = snapshotStats();
    stats[prefix + "enabled"] = snap.enabled ? 1u : 0u;
    stats[prefix + "owner_scope_enable"] = snap.owner_scope_enable ? 1u : 0u;
    stats[prefix + "actual_owner_enable"] = snap.actual_owner_enable ? 1u : 0u;
    stats[prefix + "idx_enabled"] = snap.idx_enabled ? 1u : 0u;
    stats[prefix + "l0_enabled"] = snap.l0_enabled ? 1u : 0u;
    exportAuthorityClass_(stats, prefix + "idx_", snap.idx_authority);
    exportAuthorityClass_(stats, prefix + "l0_", snap.l0_authority);
    exportBankedSramStats_(stats, prefix + "idx_", snap.idx_sram);
    exportBankedSramStats_(stats, prefix + "l0_", snap.l0_sram);
    stats[prefix + "l0_fill_total"] = snap.l0_fill_total;
    stats[prefix + "l0_evict_total"] = snap.l0_evict_total;
}

}} // namespace SST::SnnDL
