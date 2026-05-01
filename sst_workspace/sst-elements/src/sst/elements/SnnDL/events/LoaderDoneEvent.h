// -*- c++ -*-
//
// LoaderDoneEvent:
// - WeightLoader -> MultiCorePE 的控制面事件：通知“权重写入/校验完成，可开始发起读请求/发送 PE_READY”。
// - 目的：桥接 SharedArray(loader_done_key) 在 MPI 多 rank 下不可见的问题。
//

#ifndef SNNDL_LOADER_DONE_EVENT_H
#define SNNDL_LOADER_DONE_EVENT_H

#include <cstdint>

#include <sst/core/event.h>
#include <sst/core/serialization/serialize.h>

namespace SST { namespace SnnDL {

class LoaderDoneEvent final : public SST::Event {
public:
    uint32_t src_node = 0;

    LoaderDoneEvent() = default;
    explicit LoaderDoneEvent(uint32_t src_node_) : SST::Event(), src_node(src_node_) {}

    void serialize_order(SST::Core::Serialization::serializer& ser) override {
        Event::serialize_order(ser);
        SST_SER(src_node);
    }

private:
    ImplementSerializable(SST::SnnDL::LoaderDoneEvent)
};

}} // namespace SST::SnnDL

#endif // SNNDL_LOADER_DONE_EVENT_H

