// -*- c++ -*-
//
// Copyright 2025 SST Contributors
//
// SpikeEvent.h: 定义脉冲事件类，用于SNN处理单元之间的通信
//

#ifndef _SPIKEVENT_H
#define _SPIKEVENT_H

#include <sst/core/event.h>
#include <sst/core/serialization/serialize.h>

namespace SST {
namespace SnnDL {

/**
 * @brief 脉冲事件类，用于在SNN组件之间传递脉冲信息
 * 
 * 该类继承自SST::Event，包含发放脉冲的神经元ID等信息。
 * 支持SST的序列化机制，可用于并行仿真。
 */
class SpikeEvent : public SST::Event {
public:
    static constexpr uint32_t INVALID_LOCAL_INDEX = 0xffffffffu;
    /** 发放脉冲的神经元ID */
    uint32_t neuron_id;
    
    /** 脉冲发放的时间戳（可选，用于更精确的时序分析） */
    uint64_t timestamp;

    // 在SpikeEvent类中添加防止循环的字段
    uint32_t hop_count = 0;
    static constexpr uint32_t MAX_HOPS = 10;  // 最大跳数限制
    
    /**
     * @brief 默认构造函数（用于序列化）
     */
    SpikeEvent() : SST::Event(), neuron_id(0), timestamp(0), 
                   dest_neuron(0), dest_node(0), weight(0.0) {}
    
    /**
     * @brief 基本构造函数
     * @param id 发放脉冲的神经元ID
     * @param ts 时间戳（默认为0）
     */
    SpikeEvent(uint32_t id, uint64_t ts = 0) : 
        SST::Event(), neuron_id(id), timestamp(ts),
        dest_neuron(0), dest_node(0), weight(0.0) {}
    
    /**
     * @brief 网络脉冲构造函数
     * @param id 源神经元ID
     * @param dest_n 目标神经元ID
     * @param dest_node_id 目标节点ID
     * @param w 突触权重
     * @param ts 时间戳（默认为0）
     */
    SpikeEvent(uint32_t id, uint32_t dest_n, uint32_t dest_node_id, double w, uint64_t ts = 0) :
        SST::Event(), neuron_id(id), timestamp(ts),
        dest_neuron(dest_n), dest_node(dest_node_id), weight(w) {}

    // === 访问器方法 ===
    
    uint32_t getNeuronId() const { return neuron_id; }
    void setNeuronId(uint32_t id) { neuron_id = id; }
    
    uint64_t getTimestamp() const { return timestamp; }
    void setTimestamp(uint64_t ts) { timestamp = ts; }
    
    uint32_t getDestinationNeuron() const { return dest_neuron; }

    /** 获取源神经元ID */
    uint32_t getSourceNeuron() const { return neuron_id; }
    void setDestinationNeuron(uint32_t dest_n) { dest_neuron = dest_n; }
    
    uint32_t getDestinationNode() const { return dest_node; }
    void setDestinationNode(uint32_t dest_node_id) { dest_node = dest_node_id; }
    
    double getWeight() const { return weight; }
    void setWeight(double w) { weight = w; }
    
    uint64_t getSpikeTime() const { return timestamp; }
    void setSpikeTime(uint64_t spike_time) { timestamp = spike_time; }

    // 本地索引缓存（仅限单进程内部使用，不参与序列化）
    void clearLocalCache() const {
        cache_flags_ = 0;
        cached_post_local_ = INVALID_LOCAL_INDEX;
        cached_pre_local_ = INVALID_LOCAL_INDEX;
    }
    void setCachedPostLocal(uint32_t post_local) const {
        cached_post_local_ = post_local;
        cache_flags_ |= kCachePost;
    }
    bool hasCachedPostLocal() const { return (cache_flags_ & kCachePost) != 0; }
    uint32_t getCachedPostLocal() const { return cached_post_local_; }
    void setCachedPreLocal(uint32_t pre_local) const {
        cached_pre_local_ = pre_local;
        cache_flags_ |= kCachePre;
    }
    bool hasCachedPreLocal() const { return (cache_flags_ & kCachePre) != 0; }
    uint32_t getCachedPreLocal() const { return cached_pre_local_; }

    // 添加访问方法
    uint32_t getHopCount() const { return hop_count; }
    void incrementHopCount() { hop_count++; }
    bool isExpired() const { return hop_count >= MAX_HOPS; }

    /**
     * @brief 序列化函数，支持并行仿真中的事件传递
     * @param ser 序列化器对象
     */
    void serialize_order(SST::Core::Serialization::serializer &ser) override {
        Event::serialize_order(ser);  // 先序列化基类
        SST_SER(neuron_id);
        SST_SER(timestamp);
        SST_SER(hop_count);
        SST_SER(dest_neuron); 
        SST_SER(dest_node);
        SST_SER(weight);
    }

private:
    uint32_t dest_neuron;      ///< 目标神经元ID
    uint32_t dest_node;        ///< 目标节点ID
    double weight;             ///< 突触权重
    mutable uint32_t cached_post_local_ = INVALID_LOCAL_INDEX;
    mutable uint32_t cached_pre_local_ = INVALID_LOCAL_INDEX;
    mutable uint8_t cache_flags_ = 0; // bit0: post, bit1: pre
    static constexpr uint8_t kCachePost = 0x1;
    static constexpr uint8_t kCachePre  = 0x2;
    
    // 注册序列化支持
    ImplementSerializable(SST::SnnDL::SpikeEvent)
};

} // namespace SnnDL
} // namespace SST

#endif /* _SPIKEVENT_H */
