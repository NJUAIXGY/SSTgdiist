// -*- c++ -*-
//
// IWeightReaderAdopter: 将 IWeightReader 所有权从装配方移交给 workload 的窄接口（Tier2-E）。
// - 目的：避免 CoreShell 与 workload=snn 重复装配 WeightMemorySubsystem/WeightCacheOps。
// - 约束：不修改 Python/脚本侧接口；仅用于 C++ 内部模块解耦。
//

#pragma once

#include <memory>

namespace SST { namespace SnnDL {

class IWeightReader;

class IWeightReaderAdopter {
public:
    virtual ~IWeightReaderAdopter() = default;

    // Adopt ownership of a pre-built weight reader (usually WeightMemorySubsystem).
    // Implementations should be idempotent (ignore nullptr / repeated calls).
    virtual void adoptWeightReader(std::unique_ptr<IWeightReader> reader) = 0;
};

}} // namespace SST::SnnDL

