// -*- c++ -*-

#include "workload/riscv_snn/RiscvSnnAsm.h"
#include "workload/riscv_snn/RiscvSnnElfWriter.h"
#include "workload/riscv_snn/RiscvSnnFirmwareLoader.h"
#include "workload/riscv_snn/RiscvSnnMemoryImage.h"

#include <cassert>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>
#include <unistd.h>

namespace {

std::string writeMinimalElf64() {
    using namespace SST::SnnDL::riscv_snn;

    std::vector<uint8_t> text;
    asmv1::appendInsn32(text, asmv1::encodeAddi(/*rd=*/0, /*rs1=*/0, /*imm=*/0));

    char path_template[] = "/tmp/riscv_snn_fw_XXXXXX";
    const int fd = mkstemp(path_template);
    assert(fd >= 0);
    close(fd);

    RiscvSnnElfLoadSegment segment{};
    segment.vaddr = 0x1000;
    segment.flags = 0x5;
    segment.file_data = text;
    segment.mem_size = 8;

    std::string error;
    assert(writeElf64Image(path_template, /*entry_pc=*/0x1000, {segment}, error));
    assert(error.empty());
    return std::string(path_template);
}

} // namespace

int main() {
    const std::string path = writeMinimalElf64();

    SST::SnnDL::riscv_snn::RiscvSnnMemoryImage image;
    std::string error;
    const bool ok =
        SST::SnnDL::riscv_snn::RiscvSnnFirmwareLoader::loadElf64(path, image, error);
    assert(ok);
    assert(error.empty());
    assert(image.entry_pc == 0x1000);
    assert(image.segments.size() == 1);
    assert(image.segments[0].vaddr == 0x1000);
    assert(image.segments[0].data.size() == 8);
    assert(image.segments[0].data[0] == 0x13);
    assert(image.footprintBytes() == 8);

    std::remove(path.c_str());
    return 0;
}
