// -*- c++ -*-
//
// Narrow provider interface for exposing a PE-shared local storage hierarchy
// without coupling callers to MultiCorePE concrete implementation.

#pragma once

namespace SST { namespace SnnDL {

class LocalStorageHierarchyController;

class ILocalStorageProvider {
public:
    virtual ~ILocalStorageProvider() = default;
    virtual LocalStorageHierarchyController* localStorageHierarchy() = 0;
};

}} // namespace SST::SnnDL
