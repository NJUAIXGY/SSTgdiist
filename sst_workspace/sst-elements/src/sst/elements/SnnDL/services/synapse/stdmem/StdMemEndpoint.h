// -*- c++ -*-
//
// StdMemEndpoint: StandardMem glue (synapse 域)
// - 负责装配 StandardMem 子组件、接收回包、分发到：
//   1) services/memory/StandardMemAccess（纯数据面 read/write 回调）
//   2) api/IGasStageSink（GAS 控制面 stage/stat 事件，纯数据结构）
// - 目标：control/** 彻底不出现 StandardMem::（包括 .cc）
//

#pragma once

#include <cstdint>
#include <functional>
#include <memory>
#include <string>

#include "IGasCmdSender.h"

namespace SST { class Output; class SubComponent; }

namespace SST { namespace SnnDL {

class IGasStageSink;
class IGasStepGate;
class IGasCreditGate;
class IMemoryAccess;

// 约束：本头文件不包含 stdMem.h，也不暴露 StandardMem 类型。
class StdMemEndpoint final : public IGasCmdSender {
public:
    struct Config {
        bool log_enable = false;
        // Memory semantic only: force all StandardMemAccess requests to be non-cacheable.
        bool force_noncacheable = false;
    };

    struct Runtime {
        SST::Output* log = nullptr;
        uint32_t node_id = 0;
        uint32_t core_id = 0;

        // GAS stage/stat sink (non-owning).
        IGasStageSink* gas_stage_sink = nullptr;

        // Optional helpers for consistent cycle accounting.
        std::function<uint64_t()> now_cycle;
        std::function<void(uint64_t /*now_cycle*/)> before_data_plane_dispatch;
    };

    StdMemEndpoint();
    ~StdMemEndpoint();

    StdMemEndpoint(const StdMemEndpoint&) = delete;
    StdMemEndpoint& operator=(const StdMemEndpoint&) = delete;

    void configure(const Config& cfg);
    void bindRuntime(const Runtime& rt);
    void bindStdMem(SST::SubComponent* stdmem_subcomp);

    bool available() const { return mem_access_ != nullptr; }
    IMemoryAccess* memoryAccess() const { return mem_access_; }
    IGasStepGate* stepGate() const { return step_gate_; }
    IGasCreditGate* creditGate() const { return credit_gate_; }

    void init(unsigned int phase);
    void complete(unsigned int phase);

    // Handle a StandardMem response (opaque pointer to avoid leaking stdMem types into control/**).
    void handleResponseOpaque(void* req);

    // IGasCmdSender
    void sendGasCmd(GasOp op,
                    uint32_t superstep,
                    uint32_t slice,
                    uint32_t total_slices,
                    bool flag = false) override;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;

    Config cfg_{};
    Runtime rt_{};

    // Non-owning handles for callers (filled after bindRuntime()).
    IMemoryAccess* mem_access_ = nullptr;
    IGasStepGate* step_gate_ = nullptr;
    IGasCreditGate* credit_gate_ = nullptr;
};

}} // namespace SST::SnnDL
