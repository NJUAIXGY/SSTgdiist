// -*- c++ -*-
//
// Copyright 2025 SST Contributors
//
// SnnInterface.h: 通用网络接口基类（payload-agnostic）
//

#ifndef _SNNINTERFACE_H
#define _SNNINTERFACE_H

#include <sst/core/subcomponent.h>
#include <sst/core/params.h>
#include <cstddef>
#include <functional>
#include <string>

namespace SST { class Event; }

namespace SST {
namespace SnnDL {

/**
 * @brief 通用网络接口基类（不包含 Spike/BCSR/权重语义）
 * 
 * 这是一个SubComponent基类，定义了SnnPE与网络通信的标准接口。
 * 类似于miranda.BaseCPU使用memory和generator插槽的方式，
 * SnnPE可以使用这个接口插槽来实现网络通信的抽象。
 */
class SnnInterface : public SST::SubComponent {
public:
    /**
     * @brief 通用接收回调（接管 event 生命周期）
     * @param event 接收到的事件指针
     */
    typedef std::function<void(SST::Event*)> ReceiveHandler;

    /**
     * @brief 构造函数
     * @param id 组件ID
     * @param params 参数集合
     */
    SnnInterface(SST::ComponentId_t id, SST::Params& params)
        : SST::SubComponent(id)
    {
        // 基类构造器
    }

    /**
     * @brief 虚析构函数
     */
    virtual ~SnnInterface() {}

    // === ELI注册宏 ===
    SST_ELI_REGISTER_SUBCOMPONENT_API(SST::SnnDL::SnnInterface)

    // === 纯虚接口方法 ===

    /**
     * @brief 设置接收处理器（接管 event 生命周期）
     * @param handler 接收回调函数
     */
    virtual void setReceiveHandler(ReceiveHandler handler) = 0;

    /**
     * @brief 发送事件到目标节点（接管 event 生命周期）
     * @param dest_node 目标节点ID
     * @param event 要发送的事件
     */
    virtual void sendToNode(uint32_t dest_node, SST::Event* event) = 0;

    /**
     * @brief 设置网络节点ID
     * @param node_id 节点ID
     */
    virtual void setNodeId(uint32_t node_id) = 0;

    /**
     * @brief 获取网络节点ID
     * @return 当前节点ID
     */
    virtual uint32_t getNodeId() const = 0;

    /**
     * @brief 获取网络状态信息
     * @return 状态字符串
     */
    virtual std::string getNetworkStatus() const = 0;

    /**
     * @brief 平台侧可选探针：当前仍在 NIC 内部排队、尚未进入网络的待发送事件数量
     *
     * 用途：
     * - Global step drain-based barrier：避免在 NIC 背压堆积时把 step 误判为已完成。
     *
     * 说明：
     * - 默认返回 0，表示“不支持/未知”；不会影响功能正确性，但 drain 判定可能更保守或退化为基于静默周期。
     */
    virtual size_t pendingSendCount() const { return 0; }
};

} // namespace SnnDL
} // namespace SST

#endif /* _SNNINTERFACE_H */
