// -*- c++ -*-
//
// Shared lightweight logging helpers for SnnDL translation units.
//
// NOTE: This is an internal convenience header. It intentionally stays macro-based to
// avoid widening class interfaces across many translation units.
//
// Assumption: the including translation unit's class owns a member named `output_`
// of type `SST::Output*`.
//

#pragma once

#include <sst/core/output.h>

// Base log helpers
#ifndef SNNDL_LOGPTR
#define SNNDL_LOGPTR(ptr, lvl, ...) \
    do { \
        if ((ptr) != nullptr) { \
            (ptr)->verbose(CALL_INFO, (lvl), 0, __VA_ARGS__); \
        } \
    } while (0)
#endif

#ifndef SNNDL_LOG
#define SNNDL_LOG(lvl, ...) SNNDL_LOGPTR(output_, (lvl), __VA_ARGS__)
#endif

// Debug gating (compile-time)
#ifdef SNNDL_ENABLE_DEBUG_LOG
#define SNNDL_DEBUG_ENABLED 1
#define SNNDL_DEBUG_LOG(lvl, ...) SNNDL_LOG((lvl), __VA_ARGS__)
#define SNNDL_DEBUG_BLOCK(stmt) do { stmt; } while (0)
#else
#define SNNDL_DEBUG_ENABLED 0
#define SNNDL_DEBUG_LOG(lvl, ...) do {} while (0)
#define SNNDL_DEBUG_BLOCK(stmt) do {} while (0)
#endif

