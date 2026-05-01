// -*- c++ -*-
//
// StdMemEndpoint.cc: StandardMem glue implementation (synapse 域)
//

#include <sst/core/sst_config.h>

#include "synapse/stdmem/StdMemEndpoint.h"

#include <sst/core/interfaces/stdMem.h>
#include <sst/core/output.h>

#include "IGasStageSink.h"
#include "IGasCreditGate.h"
#include "IGasStepGate.h"
#include "memory/StandardMemAccess.h"
#include "synapse/gas/GasCustomCmd.h"

#include <inttypes.h>

namespace SST { namespace SnnDL {

struct StdMemEndpoint::Impl {
    SST::Interfaces::StandardMem* stdmem = nullptr;  // non-owning; created by SST factory
    std::unique_ptr<StandardMemAccess> stdmem_access;
};

StdMemEndpoint::StdMemEndpoint() : impl_(std::make_unique<Impl>()) {}
StdMemEndpoint::~StdMemEndpoint() = default;

void StdMemEndpoint::configure(const Config& cfg) { cfg_ = cfg; }

void StdMemEndpoint::bindRuntime(const Runtime& rt) {
    rt_ = rt;
}

void StdMemEndpoint::bindStdMem(SST::SubComponent* stdmem_subcomp) {
    // Reset previous bindings
    mem_access_ = nullptr;
    step_gate_ = nullptr;
    credit_gate_ = nullptr;
    if (impl_) {
        impl_->stdmem = nullptr;
        impl_->stdmem_access.reset();
    }

    if (!impl_) return;
    if (!stdmem_subcomp) return;

    impl_->stdmem = dynamic_cast<SST::Interfaces::StandardMem*>(stdmem_subcomp);
    if (!impl_->stdmem) return;

    impl_->stdmem_access =
        std::make_unique<StandardMemAccess>(impl_->stdmem, rt_.log, (int)rt_.node_id, (int)rt_.core_id);
    impl_->stdmem_access->setForceNoncacheable(cfg_.force_noncacheable);
    mem_access_ = impl_->stdmem_access.get();

    // Optional: query GAS step gate and manual window driver from downstream StandardMem front-end.
    step_gate_ = dynamic_cast<IGasStepGate*>(impl_->stdmem);
    credit_gate_ = dynamic_cast<IGasCreditGate*>(impl_->stdmem);
}

void StdMemEndpoint::init(unsigned int phase) {
    if (impl_ && impl_->stdmem) {
        impl_->stdmem->init(phase);
    }
}

void StdMemEndpoint::complete(unsigned int phase) {
    if (impl_ && impl_->stdmem) {
        impl_->stdmem->complete(phase);
    }
}

void StdMemEndpoint::sendGasCmd(GasOp op,
                                uint32_t superstep,
                                uint32_t slice,
                                uint32_t total_slices,
                                bool flag) {
    if (!impl_ || !impl_->stdmem) return;
    auto* req = new SST::Interfaces::StandardMem::CustomReq(new GasOpData(op, superstep, slice, total_slices, flag));
    impl_->stdmem->send(req);
}

void StdMemEndpoint::handleResponseOpaque(void* req) {
    auto* stdmem_req = reinterpret_cast<SST::Interfaces::StandardMem::Request*>(req);
    if (!stdmem_req) return;

    // === Control-plane CustomResp (GAS stage/stat) ===
    if (auto* cust = dynamic_cast<SST::Interfaces::StandardMem::CustomResp*>(stdmem_req)) {
        auto& data = cust->getData();
        if (auto* op = dynamic_cast<GasOpData*>(&data)) {
            if (rt_.gas_stage_sink) {
                GasStageEvent ev{};
                ev.op = op->op;
                ev.superstep = op->superstep;
                ev.slice = op->slice;
                ev.total_slices = op->total_slices;
                ev.flag = op->flag;
                rt_.gas_stage_sink->onGasStageEvent(ev);
            }
            delete stdmem_req;
            return;
        }
        if (auto* st = dynamic_cast<GasStatData*>(&data)) {
            if (rt_.gas_stage_sink) {
                const GasStatEvent sev = toGasStatEvent(*st);
                rt_.gas_stage_sink->onGasStatEvent(sev);
            }
            delete stdmem_req;
            return;
        }
        // Unknown CustomResp: fall-through to delete
    }

    // === Data-plane Read/Write responses ===
    uint64_t now_cycle = 0;
    if (rt_.now_cycle) now_cycle = rt_.now_cycle();
    if (rt_.before_data_plane_dispatch) rt_.before_data_plane_dispatch(now_cycle);

    if (impl_ && impl_->stdmem_access && impl_->stdmem_access->handleMemoryResponse(stdmem_req)) {
        // handled and deleted
        return;
    }

    // Untracked ReadResp indicates a broken demux/ownership boundary:
    // a Read was issued on this endpoint without being tracked by StandardMemAccess (IMemoryAccess layer),
    // which will lead to silent data loss and non-determinism. Fail-fast.
    if (auto* rr = dynamic_cast<SST::Interfaces::StandardMem::ReadResp*>(stdmem_req)) {
        const uint64_t rid = static_cast<uint64_t>(rr->getID()) + 1;
        const size_t pending = (mem_access_ ? mem_access_->pendingSize() : 0);
        if (rt_.log) {
            rt_.log->fatal(CALL_INFO, -1,
                           "[stdmem-untracked] node=%u core=%u type=ReadResp id=%" PRIu64 " addr=0x%llx bytes=%zu pending=%zu\n",
                           static_cast<uint32_t>(rt_.node_id),
                           static_cast<uint32_t>(rt_.core_id),
                           (uint64_t)rid,
                           (unsigned long long)rr->pAddr,
                           (size_t)rr->size,
                           pending);
        }
        // If no logger, still fail-fast.
        abort();
    }

    delete stdmem_req;
}

}} // namespace SST::SnnDL
