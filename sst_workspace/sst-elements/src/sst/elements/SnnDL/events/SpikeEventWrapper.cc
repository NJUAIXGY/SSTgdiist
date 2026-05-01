#include "SpikeEventWrapper.h"

namespace SST {
namespace SnnDL {

// 需要为虚函数提供实现以建立正确的vtable

SpikeEventWrapper::SpikeEventWrapper() : SST::Event(), spike_data(nullptr), owns_spike_data_(false)
{
    // 默认构造函数实现
}

SpikeEventWrapper::SpikeEventWrapper(SpikeEvent* spike) : SST::Event(), spike_data(spike), owns_spike_data_(false)
{
    // 参数构造函数实现
}

SpikeEventWrapper::~SpikeEventWrapper() 
{
    if (owns_spike_data_ && spike_data != nullptr) {
        delete spike_data;
        spike_data = nullptr;
    }
}

void SpikeEventWrapper::setSpikeEvent(SpikeEvent* spike)
{
    if (owns_spike_data_ && spike_data != nullptr && spike_data != spike) {
        delete spike_data;
    }
    spike_data = spike;
    owns_spike_data_ = false;
}

SST::Event* SpikeEventWrapper::clone() 
{
    if (spike_data) {
        // 创建SpikeEvent的副本
        SpikeEvent* cloned_spike = new SpikeEvent(
            spike_data->getNeuronId(),
            spike_data->getDestinationNeuron(),
            spike_data->getDestinationNode(),
            spike_data->getWeight(),
            spike_data->getTimestamp()
        );
        for (uint32_t i = 0; i < spike_data->getHopCount(); ++i) {
            cloned_spike->incrementHopCount();
        }
        SpikeEventWrapper* wrapped = new SpikeEventWrapper(cloned_spike);
        wrapped->owns_spike_data_ = true;
        return wrapped;
    }
    return new SpikeEventWrapper();
}

size_t SpikeEventWrapper::size() const 
{
    return sizeof(SpikeEventWrapper) + (spike_data ? sizeof(SpikeEvent) : 0);
}

void SpikeEventWrapper::serialize_order(SST::Core::Serialization::serializer& ser) 
{
    SST::Event::serialize_order(ser);
    
    // 序列化spike_data是否存在
    bool has_spike = (spike_data != nullptr);
    SST_SER(has_spike);
    
    if (has_spike) {
        if (ser.mode() == SST::Core::Serialization::serializer::PACK) {
            // 打包模式：序列化SpikeEvent的数据
            uint32_t neuron_id = spike_data->getNeuronId();
            uint32_t dest_neuron = spike_data->getDestinationNeuron();
            uint32_t dest_node = spike_data->getDestinationNode();
            double weight = spike_data->getWeight();
            SST::SimTime_t timestamp = spike_data->getTimestamp();
            uint32_t hop_count = spike_data->getHopCount();
            
            SST_SER(neuron_id);
            SST_SER(dest_neuron);
            SST_SER(dest_node);
            SST_SER(weight);
            SST_SER(timestamp);
            SST_SER(hop_count);
        } else {
            // 解包模式：反序列化并创建SpikeEvent
            uint32_t neuron_id, dest_neuron, dest_node;
            double weight;
            SST::SimTime_t timestamp;
            uint32_t hop_count = 0;
            
            SST_SER(neuron_id);
            SST_SER(dest_neuron);
            SST_SER(dest_node);
            SST_SER(weight);
            SST_SER(timestamp);
            SST_SER(hop_count);
            if (owns_spike_data_ && spike_data != nullptr) {
                delete spike_data;
                spike_data = nullptr;
            }
            
            spike_data = new SpikeEvent(neuron_id, dest_neuron, dest_node, weight, timestamp);
            for (uint32_t i = 0; i < hop_count; ++i) {
                spike_data->incrementHopCount();
            }
            owns_spike_data_ = true;
        }
    } else if (ser.mode() == SST::Core::Serialization::serializer::UNPACK) {
        if (owns_spike_data_ && spike_data != nullptr) {
            delete spike_data;
        }
        spike_data = nullptr;
        owns_spike_data_ = false;
    }
}

} // namespace SnnDL
} // namespace SST
