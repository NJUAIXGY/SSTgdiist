#ifndef SPIKEEVENTWRAPPER_H
#define SPIKEEVENTWRAPPER_H

#include <sst/core/event.h>
#include <sst/core/serialization/serializable.h>
#include "events/SpikeEvent.h"

namespace SST {
namespace SnnDL {

/**
 * @brief SST Event包装器用于SpikeEvent
 * 
 * 这个类正确地继承自SST::Event并实现序列化接口，
 * 解决了直接使用SpikeEvent时的段错误问题。
 */
class SpikeEventWrapper : public SST::Event {
public:
    /**
     * @brief 默认构造函数（序列化需要）
     */
    SpikeEventWrapper();
    
    /**
     * @brief 从SpikeEvent构造
     * @param spike 原始的SpikeEvent
     */
    explicit SpikeEventWrapper(SpikeEvent* spike);
    
    /**
     * @brief 析构函数
     */
    virtual ~SpikeEventWrapper();
    
    /**
     * @brief 获取包装的SpikeEvent
     * @return SpikeEvent指针
     */
    SpikeEvent* getSpikeEvent() const { return spike_data; }
    
    /**
     * @brief 设置包装的SpikeEvent
     * @param spike SpikeEvent指针
     */
    void setSpikeEvent(SpikeEvent* spike);
    
    /**
     * @brief 克隆事件
     * @return 新的SpikeEventWrapper副本
     */
    SST::Event* clone() override;
    
    /**
     * @brief 获取事件大小（用于统计）
     * @return 事件大小（字节）
     */
    virtual size_t size() const;
    
    // === 序列化支持 ===
    
    /**
     * @brief 序列化接口实现
     */
    void serialize_order(SST::Core::Serialization::serializer& ser) override;
    
    // SST序列化宏
    ImplementSerializable(SST::SnnDL::SpikeEventWrapper)

private:
    SpikeEvent* spike_data;  ///< 包装的SpikeEvent数据
    bool owns_spike_data_ = false;
};

} // namespace SnnDL
} // namespace SST

#endif // SPIKEEVENTWRAPPER_H
