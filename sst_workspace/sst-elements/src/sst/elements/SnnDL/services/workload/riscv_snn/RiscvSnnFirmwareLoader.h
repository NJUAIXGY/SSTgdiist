// -*- c++ -*-
//
// RiscvSnnFirmwareLoader:
// - `riscv_snn` 实验主线专用 firmware loader。
// - 当前只支持最小 ELF64 little-endian RISC-V PT_LOAD 装载，保持与主线 workload 隔离。
//

#pragma once

#include <string>

#include "workload/riscv_snn/RiscvSnnMemoryImage.h"

namespace SST { namespace SnnDL { namespace riscv_snn {

class RiscvSnnFirmwareLoader {
public:
    static bool loadElf64(const std::string& path,
                          RiscvSnnMemoryImage& image,
                          std::string& error);
};

}}} // namespace SST::SnnDL::riscv_snn
