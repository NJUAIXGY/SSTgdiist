// -*- c++ -*-

#include "workload/riscv_snn/RiscvSnnElfWriter.h"
#include "workload/riscv_snn/RiscvSnnSampleFirmware.h"

#include <filesystem>
#include <iostream>
#include <string>

namespace {

using namespace SST::SnnDL::riscv_snn;

void printUsage(const char* argv0) {
    std::cerr << "usage:\n";
    std::cerr << "  " << argv0 << " <program> <output.elf>\n";
    std::cerr << "  " << argv0 << " --list-programs\n";
    std::cerr << "  " << argv0 << " --list-programs --json\n";
    std::cerr << "programs:\n";
    for (const auto& sample : sampleFirmwareMetadata()) {
        std::cerr << "  " << sample.program;
        std::cerr << (sample.canonical_sample ? " [canonical]" : " [reference]");
        std::cerr << " - " << sample.description << "\n";
    }
}

void printJsonEscaped(const std::string& value) {
    std::cout << '"';
    for (char ch : value) {
        switch (ch) {
        case '\\':
            std::cout << "\\\\";
            break;
        case '"':
            std::cout << "\\\"";
            break;
        case '\n':
            std::cout << "\\n";
            break;
        case '\r':
            std::cout << "\\r";
            break;
        case '\t':
            std::cout << "\\t";
            break;
        default:
            std::cout << ch;
            break;
        }
    }
    std::cout << '"';
}

void printProgramManifestJson() {
    const auto& canonical = canonicalSampleFirmwareProgramNames();
    const auto& samples = sampleFirmwareMetadata();

    std::cout << "{\n";
    std::cout << "  \"canonical_sample_set\": [\n";
    for (size_t i = 0; i < canonical.size(); ++i) {
        std::cout << "    ";
        printJsonEscaped(canonical[i]);
        std::cout << (i + 1 == canonical.size() ? "\n" : ",\n");
    }
    std::cout << "  ],\n";
    std::cout << "  \"samples\": {\n";
    for (size_t i = 0; i < samples.size(); ++i) {
        const auto& sample = samples[i];
        std::cout << "    ";
        printJsonEscaped(sample.program);
        std::cout << ": {\n";
        std::cout << "      \"canonical_sample\": " << (sample.canonical_sample ? "true" : "false") << ",\n";
        std::cout << "      \"description\": ";
        printJsonEscaped(sample.description);
        std::cout << ",\n";
        std::cout << "      \"descriptor_source\": ";
        printJsonEscaped(sample.descriptor_source);
        std::cout << ",\n";
        std::cout << "      \"completion_visibility\": ";
        printJsonEscaped(sample.completion_visibility);
        std::cout << ",\n";
        std::cout << "      \"architectural_boundary\": ";
        printJsonEscaped(sample.architectural_boundary);
        std::cout << ",\n";
        std::cout << "      \"memory_image_shape\": ";
        printJsonEscaped(sample.memory_image_shape);
        std::cout << ",\n";
        std::cout << "      \"notes\": [\n";
        for (size_t j = 0; j < sample.notes.size(); ++j) {
            std::cout << "        ";
            printJsonEscaped(sample.notes[j]);
            std::cout << (j + 1 == sample.notes.size() ? "\n" : ",\n");
        }
        std::cout << "      ]\n";
        std::cout << "    }" << (i + 1 == samples.size() ? "\n" : ",\n");
    }
    std::cout << "  }\n";
    std::cout << "}\n";
}

void printProgramList() {
    for (const auto& sample : sampleFirmwareMetadata()) {
        std::cout << sample.program << ": " << sample.description;
        if (sample.canonical_sample) {
            std::cout << " [canonical]";
        } else {
            std::cout << " [reference]";
        }
        std::cout << "\n";
    }
}

bool writeProgramElf(const std::string& program, const std::string& path, std::string& error) {
    error.clear();

    const std::filesystem::path out_path(path);
    if (out_path.empty()) {
        error = "output path is empty";
        return false;
    }
    if (out_path.has_parent_path()) {
        std::error_code ec;
        std::filesystem::create_directories(out_path.parent_path(), ec);
        if (ec) {
            error = "failed to create output directory";
            return false;
        }
    }

    RiscvSnnSampleProgram sample_program;
    if (!buildSampleFirmwareProgram(program, sample_program, error)) {
        return false;
    }
    return writeElf64Image(path, sample_program.entry_pc, sample_program.segments, error);
}

} // namespace

int main(int argc, char** argv) {
    if (argc == 2 && std::string(argv[1]) == "--list-programs") {
        printProgramList();
        return 0;
    }
    if (argc == 3 &&
        std::string(argv[1]) == "--list-programs" &&
        std::string(argv[2]) == "--json") {
        printProgramManifestJson();
        return 0;
    }

    if (argc != 3) {
        printUsage(argv[0]);
        return 2;
    }

    std::string error;
    if (!writeProgramElf(argv[1], argv[2], error)) {
        std::cerr << error << "\n";
        return 2;
    }
    return 0;
}
