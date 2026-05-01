#ifndef SIMPLETESTEVENT_H
#define SIMPLETESTEVENT_H

#include <sst/core/event.h>
#include <sst/core/serialization/serializable.h>

namespace SST {
namespace SnnDL {

/**
 * @brief 最简单的测试Event类，用于验证SST Link机制
 * 
 * 这个类只包含一个整数，没有任何复杂的数据结构
 */
class SimpleTestEvent : public SST::Event {
public:
    /**
     * @brief 默认构造函数（序列化需要）
     */
    SimpleTestEvent();
    
    /**
     * @brief 从整数构造
     * @param value 测试值
     */
    explicit SimpleTestEvent(int value);
    
    /**
     * @brief 析构函数
     */
    virtual ~SimpleTestEvent();
    
    /**
     * @brief 获取测试值
     * @return 测试值
     */
    int getValue() const { return test_value; }
    
    /**
     * @brief 克隆事件
     * @return 新的SimpleTestEvent副本
     */
    SST::Event* clone() override;
    
    /**
     * @brief 获取事件大小（用于统计）
     * @return 事件大小（字节）
     */
    virtual size_t size() const;
    
    /**
     * @brief 序列化接口实现
     */
    void serialize_order(SST::Core::Serialization::serializer& ser) override;
    
    // SST序列化宏
    ImplementSerializable(SST::SnnDL::SimpleTestEvent)

private:
    int test_value;  ///< 简单的测试值
};

} // namespace SnnDL
} // namespace SST

#endif // SIMPLETESTEVENT_H