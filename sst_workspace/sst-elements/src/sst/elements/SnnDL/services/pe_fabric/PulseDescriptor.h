// -*- c++ -*-
//
// Minimal observe-only activation descriptor for PULSE Task 3.

#pragma once

#include <cstdint>

namespace SST { namespace SnnDL {

struct PulseActivationDescriptor {
    uint32_t step_id = 0;
    uint32_t window_id = 0;
    uint32_t post_block_id = 0;
    uint32_t weight_region_id = 0;
    uint32_t retire_domain_id = 0;
    uint64_t consumer_bitmap = 0;
    uint32_t consumer_count = 0;
    uint32_t packet_count = 0;
    uint32_t slack_to_apply_close = 0;
    bool region_safe = true;
};

}} // namespace SST::SnnDL
