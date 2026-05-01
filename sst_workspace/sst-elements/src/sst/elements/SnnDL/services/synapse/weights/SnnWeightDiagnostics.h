#ifndef SST_ELEMENTS_SNNDL_SNNWEIGHTDIAGNOSTICS_H
#define SST_ELEMENTS_SNNDL_SNNWEIGHTDIAGNOSTICS_H

#include <cstdint>
#include <functional>
#include <string>

#include "synapse/weights/SnnBcsrWeightManager.h"

namespace SST { namespace SnnDL {

// 将 BCSR 文件探针/诊断逻辑集中，避免主循环嵌入大量文件 I/O 分支。
// 说明：该文件属于 synapse/weights 域，仅用于诊断/离线验证。
class SnnWeightDiagnostics {
public:
    using ParseMetaFn = std::function<bool(const std::string&, uint32_t&, uint32_t&, uint32_t&, uint32_t&, uint32_t&, uint32_t&, uint64_t&, uint64_t&, uint64_t&, uint64_t&, uint32_t&)>;

    // 读取指定 post_local / pre_global 的权重（诊断路径：直接从文件）
    // br/bc：块大小；weights_mgr：提供 rowptrHost()；tmpl_resolver：生成权重文件路径
    static float readBcsrWeightFromFile(uint32_t post_local, uint32_t pre_global,
                                        uint32_t br, uint32_t bc,
                                        const BcsrWeightManager& weights_mgr,
                                        const std::function<std::string(uint32_t,uint32_t)>& tmpl_resolver,
                                        const ParseMetaFn& parse_meta);
};

} } // namespace SST::SnnDL

#endif // SST_ELEMENTS_SNNDL_SNNWEIGHTDIAGNOSTICS_H
