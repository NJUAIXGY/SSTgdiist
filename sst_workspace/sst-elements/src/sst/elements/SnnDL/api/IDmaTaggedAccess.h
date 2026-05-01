// -*- c++ -*-
//
// Optional DMA-tagged memory read extension.
// Keeps IMemoryAccess semantics intact while allowing upper layers
// to attach opaque tags and a DMA priority hint.

#pragma once

#include <cstdint>

#include "IMemoryAccess.h"

namespace SST { namespace SnnDL {

class IDmaTaggedAccess {
public:
    using Tag = uint32_t;

    enum class Priority : uint8_t {
        P0 = 0,
        P1 = 1,
        P2 = 2,
        P3 = 3,
    };

    virtual ~IDmaTaggedAccess() = default;

    virtual IMemoryAccess::RequestId readTagged(
        uint64_t addr,
        size_t bytes,
        Tag tag,
        Priority priority,
        IMemoryAccess::ReadCallback cb) = 0;
};

}} // namespace SST::SnnDL
