// -*- c++ -*-
#ifndef _SNN_GATING_DECISION_EVENT_H
#define _SNN_GATING_DECISION_EVENT_H

#include <sst/core/event.h>
#include <sst/core/serialization/serializer.h>
#include <vector>

namespace SST { namespace SnnDL {

/**
 * @brief 门控决策事件（控制面）
 * 告知源PE/核心在TTL窗口内对给定源行(全局)使用Top‑k专家PE列表。
 */
class GatingDecisionEvent : public SST::Event {
public:
    uint32_t token_id{0};        // 可选：令牌ID（如无可为0）
    uint32_t src_pe{0};          // 源PE编号
    uint32_t src_row{0};         // 源行(本PE内的local row)
    uint32_t top_k{0};           // Top‑k数量
    uint64_t ttl_cycles{0};      // 决策有效窗口（周期）
    std::vector<uint32_t> dest_pes;   // 目的专家PE列表(size=top_k)
    std::vector<float>    gate_weights; // 可选：门控权重(size=top_k)

    GatingDecisionEvent() : SST::Event() {}

    void serialize_order(SST::Core::Serialization::serializer &ser) override {
        Event::serialize_order(ser);
        SST_SER(token_id);
        SST_SER(src_pe);
        SST_SER(src_row);
        SST_SER(top_k);
        SST_SER(ttl_cycles);
        SST_SER(dest_pes);
        SST_SER(gate_weights);
    }

    ImplementSerializable(GatingDecisionEvent)
};

}} // namespace

#endif

