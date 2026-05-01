// -*- c++ -*-
//
// Copyright 2025 SST Contributors
//
// SnnPEParentInterface.h: SnnPE与父级组件的通信接口
//

#ifndef _SNNPE_PARENT_INTERFACE_H
#define _SNNPE_PARENT_INTERFACE_H

#include <functional>
#include <cstdint>

namespace SST {
namespace SnnDL {

// 前置声明
class SpikeEvent;

/**
 * @brief SnnPE与父级组件的通信接口
 * 
 * 该接口定义了SnnPE作为SubComponent与其父级MultiCorePE之间的通信协议。
 * 主要功能包括：
 * - 脉冲发送和路由
 * - 内存访问请求
 * - 状态查询和控制
 */
class SnnPEParentInterface {
public:
    virtual ~SnnPEParentInterface() = default;
    
    /**
     * @brief 向父级组件发送脉冲
     * 
     * SnnPE通过此接口将生成的脉冲发送给父级组件，由父级组件
     * 决定是路由到本地其他核心、还是发送到外部PE。
     * 
     * @param event 要发送的脉冲事件（调用后接口接管内存管理）
     */
    virtual void sendSpike(SpikeEvent* event) = 0;
    
    /**
     * @brief 向父级组件请求内存访问
     * 
     * SnnPE通过此接口请求访问共享内存（如权重数据）。
     * 父级组件将通过内存层次结构处理请求，并在完成后调用回调函数。
     * 
     * @param address 内存地址
     * @param size 访问大小（字节）
     * @param callback 内存访问完成后的回调函数
     */
    virtual void requestMemoryAccess(uint64_t address, size_t size, 
                                   std::function<void(const void*)> callback) = 0;
    
    /**
     * @brief 获取当前仿真周期
     * 
     * @return 当前时钟周期数
     */
    virtual uint64_t getCurrentCycle() const = 0;
    
    /**
     * @brief 获取本PE的节点ID
     * 
     * @return 节点ID
     */
    virtual int getNodeId() const = 0;
    
    /**
     * @brief 获取本PE管理的神经元总数
     * 
     * @return 神经元总数
     */
    virtual int getTotalNeurons() const = 0;
};

} // namespace SnnDL
} // namespace SST

#endif // _SNNPE_PARENT_INTERFACE_H