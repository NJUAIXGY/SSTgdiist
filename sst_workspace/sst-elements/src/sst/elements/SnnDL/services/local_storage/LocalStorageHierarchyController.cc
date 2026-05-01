// -*- c++ -*-

#include "services/local_storage/LocalStorageHierarchyController.h"

#include <algorithm>
#include <utility>

namespace SST { namespace SnnDL {

namespace {

LocalStorageObjectConfig sanitizeObjectConfig_(LocalStorageObjectConfig cfg) {
    if (cfg.banks == 0) cfg.banks = 1;
    return cfg;
}

bool registerPerCoreTemplate_(LocalStorageHierarchyController& controller,
                              const LocalStorageObjectConfig& templ,
                              size_t num_cores) {
    for (size_t core = 0; core < std::max<size_t>(num_cores, 1u); ++core) {
        LocalStorageObjectConfig obj = templ;
        obj.scope = LocalStorageScope::PerCore;
        obj.name = templ.name + ".core" + std::to_string(core);
        if (!controller.registerObject(obj)) return false;
    }
    return true;
}

bool registerPerPodTemplate_(LocalStorageHierarchyController& controller,
                             const LocalStorageObjectConfig& templ,
                             size_t num_pods) {
    for (size_t pod = 0; pod < std::max<size_t>(num_pods, 1u); ++pod) {
        LocalStorageObjectConfig obj = templ;
        obj.scope = LocalStorageScope::PerPod;
        obj.name = templ.name + ".pod" + std::to_string(pod);
        if (!controller.registerObject(obj)) return false;
    }
    return true;
}

} // namespace

uint64_t localStorageEffectiveCapacityBytes(const LocalStorageObjectConfig& cfg) {
    if (cfg.capacity_bytes > 0) return cfg.capacity_bytes;
    if (cfg.kind == LocalStorageObjectKind::RegisterFile &&
        cfg.entries > 0 && cfg.entry_bytes > 0) {
        return static_cast<uint64_t>(cfg.entries) * static_cast<uint64_t>(cfg.entry_bytes);
    }
    return 0;
}

bool localStorageObjectEnabled(const LocalStorageObjectConfig& cfg) {
    if (!cfg.enable) return false;
    if (localStorageEffectiveCapacityBytes(cfg) > 0) return true;
    return cfg.queue_depth > 0;
}

LocalStorageHierarchyController::LocalStorageHierarchyController()
    : LocalStorageHierarchyController(Config{}) {}

LocalStorageHierarchyController::LocalStorageHierarchyController(const Config& cfg)
    : cfg_(cfg) {
    if (cfg_.num_cores == 0) cfg_.num_cores = 1;
    if (cfg_.num_pods == 0) cfg_.num_pods = 1;
}

bool LocalStorageHierarchyController::registerObject(const LocalStorageObjectConfig& cfg) {
    if (!cfg_.enable) return false;
    if (cfg.name.empty()) return false;
    if (object_index_.find(cfg.name) != object_index_.end()) return false;

    LocalStorageObjectConfig clean = sanitizeObjectConfig_(cfg);
    const size_t idx = objects_.size();
    objects_.push_back(std::move(clean));
    object_index_.emplace(objects_.back().name, idx);
    return true;
}

const LocalStorageObjectConfig* LocalStorageHierarchyController::findObject(const std::string& name) const {
    auto it = object_index_.find(name);
    if (it == object_index_.end()) return nullptr;
    return &objects_[it->second];
}

LocalStorageStatsSnapshot LocalStorageHierarchyController::snapshotStats() const {
    LocalStorageStatsSnapshot snap{};
    snap.objects_registered_total = objects_.size();
    for (const auto& obj : objects_) {
        if (localStorageObjectEnabled(obj)) {
            snap.objects_enabled_total += 1;
        }
        snap.capacity_bytes_total += localStorageEffectiveCapacityBytes(obj);
        snap.queue_slots_total += static_cast<uint64_t>(obj.queue_depth);
    }
    return snap;
}

bool registerDefaultPhaseAObjects(LocalStorageHierarchyController& controller,
                                  const PhaseALocalStorageRegistrationConfig& cfg) {
    if (!controller.enabled()) return false;
    if (!cfg.activation_ingress.name.empty() && !controller.registerObject(cfg.activation_ingress)) return false;
    if (!cfg.weight_idx.name.empty() && !controller.registerObject(cfg.weight_idx)) return false;
    if (!cfg.weight_value.name.empty() && !controller.registerObject(cfg.weight_value)) return false;
    if (!cfg.pod_metadata_template.name.empty() &&
        !registerPerPodTemplate_(controller, cfg.pod_metadata_template, cfg.num_pods)) return false;
    if (!cfg.pod_owner_template.name.empty() &&
        !registerPerPodTemplate_(controller, cfg.pod_owner_template, cfg.num_pods)) return false;
    if (!cfg.pod_join_template.name.empty() &&
        !registerPerPodTemplate_(controller, cfg.pod_join_template, cfg.num_pods)) return false;
    if (!cfg.pod_ready_template.name.empty() &&
        !registerPerPodTemplate_(controller, cfg.pod_ready_template, cfg.num_pods)) return false;
    if (!cfg.state_template.name.empty() &&
        !registerPerCoreTemplate_(controller, cfg.state_template, cfg.num_cores)) return false;
    if (!cfg.activation_core_template.name.empty() &&
        !registerPerCoreTemplate_(controller, cfg.activation_core_template, cfg.num_cores)) return false;
    if (!cfg.acc_template.name.empty() &&
        !registerPerCoreTemplate_(controller, cfg.acc_template, cfg.num_cores)) return false;
    if (!cfg.rf_template.name.empty() &&
        !registerPerCoreTemplate_(controller, cfg.rf_template, cfg.num_cores)) return false;
    return true;
}

}} // namespace SST::SnnDL
