// -*- c++ -*-
//
// SnnDLStringUtil:
// - Small string helpers shared across SnnDL.
// - Keep behavior stable: ASCII-only normalization (A-Z -> a-z).
//

#pragma once

#include <cstdint>
#include <cstdio>
#include <string>

namespace SST { namespace SnnDL {

inline std::string toLowerCopy(std::string s) {
    for (auto& ch : s) {
        if (ch >= 'A' && ch <= 'Z') ch = static_cast<char>(ch - 'A' + 'a');
    }
    return s;
}

inline void replaceAll(std::string& s, const std::string& marker, const std::string& replacement) {
    if (marker.empty()) return;
    size_t pos = 0;
    while ((pos = s.find(marker, pos)) != std::string::npos) {
        s.replace(pos, marker.size(), replacement);
        pos += replacement.size();
    }
}

inline void replaceAllIndexed(std::string& s, const std::string& marker, uint32_t value, int width) {
    if (marker.empty()) return;
    if (width <= 0) return;
    size_t pos = 0;
    while ((pos = s.find(marker, pos)) != std::string::npos) {
        char buf[32];
        std::snprintf(buf, sizeof(buf), "%0*u", width, value);
        s.replace(pos, marker.size(), buf);
        pos += static_cast<size_t>(width);
    }
}

inline std::string resolvePeCoreTemplate(std::string path, uint32_t pe, uint32_t core) {
    replaceAllIndexed(path, "{pe:02d}", pe, 2);
    replaceAll(path, "{pe}", std::to_string(pe));
    replaceAllIndexed(path, "{core:02d}", core, 2);
    replaceAll(path, "{core}", std::to_string(core));
    return path;
}

}} // namespace SST::SnnDL
