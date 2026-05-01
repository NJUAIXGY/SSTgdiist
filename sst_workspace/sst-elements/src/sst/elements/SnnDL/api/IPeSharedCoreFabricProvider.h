// -*- c++ -*-
//
// Narrow provider interface for exposing a PE-shared core fabric
// without coupling callers to MultiCorePE concrete implementation.

#pragma once

namespace SST { namespace SnnDL {

class PeSharedCoreFabric;

class IPeSharedCoreFabricProvider {
public:
    virtual ~IPeSharedCoreFabricProvider() = default;
    virtual PeSharedCoreFabric* peSharedCoreFabric() = 0;
};

}} // namespace SST::SnnDL
