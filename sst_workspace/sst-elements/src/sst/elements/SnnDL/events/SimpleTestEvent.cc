#include "SimpleTestEvent.h"

namespace SST {
namespace SnnDL {

SimpleTestEvent::SimpleTestEvent() : SST::Event(), test_value(0) 
{
    // 默认构造函数实现
}

SimpleTestEvent::SimpleTestEvent(int value) : SST::Event(), test_value(value) 
{
    // 参数构造函数实现
}

SimpleTestEvent::~SimpleTestEvent() 
{
    // 析构函数 - 没有需要清理的资源
}

SST::Event* SimpleTestEvent::clone() 
{
    return new SimpleTestEvent(test_value);
}

size_t SimpleTestEvent::size() const 
{
    return sizeof(SimpleTestEvent);
}

void SimpleTestEvent::serialize_order(SST::Core::Serialization::serializer& ser) 
{
    SST::Event::serialize_order(ser);
    
    // 序列化简单的整数值
    SST_SER(test_value);
}

} // namespace SnnDL
} // namespace SST
