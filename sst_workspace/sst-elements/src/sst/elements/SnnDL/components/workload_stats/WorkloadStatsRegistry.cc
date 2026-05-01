// -*- c++ -*-
//
// WorkloadStatsRegistry.cc
//

#include "components/workload_stats/WorkloadStatsRegistry.h"

#include <cctype>

#include "components/workload_stats/SnnWorkloadStatsModule.h"
#include "api/SnnDLStringUtil.h"
#include "components/workload_stats/StreamWorkloadStatsModule.h"
#include "components/workload_stats/TensorWorkloadStatsModule.h"

namespace SST { namespace SnnDL {

namespace {
inline std::string trimCopy(std::string s) {
    size_t b = 0;
    while (b < s.size() && std::isspace(static_cast<unsigned char>(s[b]))) ++b;
    size_t e = s.size();
    while (e > b && std::isspace(static_cast<unsigned char>(s[e - 1]))) --e;
    return s.substr(b, e - b);
}

inline std::vector<std::string> splitCsv(const std::string& raw) {
    std::vector<std::string> out;
    std::string buf;
    for (char ch : raw) {
        if (ch == ',') {
            std::string item = trimCopy(buf);
            if (!item.empty()) out.push_back(item);
            buf.clear();
            continue;
        }
        buf.push_back(ch);
    }
    std::string item = trimCopy(buf);
    if (!item.empty()) out.push_back(item);
    return out;
}
} // namespace

std::vector<WorkloadStatsRegistry::ModulePtr> WorkloadStatsRegistry::buildModules(
    const std::string& workload_impl,
    const std::string& modules_csv,
    std::vector<std::string>* unknown) {
    std::vector<ModulePtr> modules;
    const std::string wl = toLowerCopy(workload_impl);
    std::vector<std::string> names;

    const std::string mod_raw = toLowerCopy(modules_csv);
    if (!mod_raw.empty()) {
        names = splitCsv(mod_raw);
    } else {
        if (wl == "stream" || wl == "traffic" || wl == "traffic_mem") {
            names.emplace_back("stream");
        } else if (wl == "tensor") {
            names.emplace_back("tensor");
        } else if (wl == "snn" || wl == "riscv_snn") {
            names.emplace_back("snn");
        }
    }

    for (const auto& name : names) {
        if (name == "snn") {
            const bool active = (wl == "snn" || wl == "riscv_snn");
            modules.emplace_back(std::make_unique<SnnWorkloadStatsModule>(active));
        } else if (name == "stream") {
            const bool active = (wl == "stream" || wl == "traffic" || wl == "traffic_mem");
            modules.emplace_back(std::make_unique<StreamWorkloadStatsModule>(active));
        } else if (name == "tensor") {
            const bool active = (wl == "tensor");
            modules.emplace_back(std::make_unique<TensorWorkloadStatsModule>(active));
        } else if (!name.empty() && unknown) {
            unknown->push_back(name);
        }
    }

    return modules;
}

}} // namespace SST::SnnDL
