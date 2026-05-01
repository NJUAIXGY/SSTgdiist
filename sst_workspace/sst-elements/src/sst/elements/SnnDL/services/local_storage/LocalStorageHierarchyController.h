// -*- c++ -*-
//
// LocalStorageHierarchyController:
// - Phase A: explicit object registry / stats snapshot / default object registration helper.
// - Runtime request scheduling will be layered on top in follow-up tasks.

#pragma once

#include <cstddef>
#include <string>
#include <unordered_map>
#include <vector>

#include "services/local_storage/LocalStorageTypes.h"

namespace SST { namespace SnnDL {

class LocalStorageHierarchyController {
public:
    struct Config {
        bool enable = false;
        size_t num_cores = 1;
        size_t num_pods = 1;
    };

    LocalStorageHierarchyController();
    explicit LocalStorageHierarchyController(const Config& cfg);

    bool enabled() const { return cfg_.enable; }
    size_t numCores() const { return cfg_.num_cores; }
    size_t numPods() const { return cfg_.num_pods; }

    bool registerObject(const LocalStorageObjectConfig& cfg);
    const LocalStorageObjectConfig* findObject(const std::string& name) const;
    LocalStorageStatsSnapshot snapshotStats() const;

private:
    Config cfg_{};
    std::vector<LocalStorageObjectConfig> objects_{};
    std::unordered_map<std::string, size_t> object_index_{};
};

bool registerDefaultPhaseAObjects(LocalStorageHierarchyController& controller,
                                  const PhaseALocalStorageRegistrationConfig& cfg);

}} // namespace SST::SnnDL
