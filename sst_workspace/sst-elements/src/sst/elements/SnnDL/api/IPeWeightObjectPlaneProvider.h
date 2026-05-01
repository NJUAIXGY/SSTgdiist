// -*- c++ -*-
//
// Narrow provider interface for exposing a PE-shared weight object plane
// without coupling callers to MultiCorePE concrete implementation.

#pragma once

namespace SST { namespace SnnDL {

class PeWeightObjectPlane;

class IPeWeightObjectPlaneProvider {
public:
    virtual ~IPeWeightObjectPlaneProvider() = default;
    virtual PeWeightObjectPlane* peWeightObjectPlane() = 0;
};

}} // namespace SST::SnnDL
