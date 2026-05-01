// -*- c++ -*-
//
// Copyright 2025 SST Contributors
//
// SimpleNetworkWrapper.h: SimpleNetwork包装器，用于解决多重继承问题
//

#ifndef _SIMPLENETWORKWRAPPER_H
#define _SIMPLENETWORKWRAPPER_H

#include <sst/core/interfaces/simpleNetwork.h>
#include <queue>

namespace SST {
namespace SnnDL {

// 前向声明
class SnnNetworkAdapter;
class NetworkEventConverter;

/**
 * @brief SimpleNetwork包装器
 * 
 * 这个类作为SnnNetworkAdapter的SimpleNetwork接口代理，
 * 解决了多重继承导致的SST ELI系统冲突问题。
 */
class SimpleNetworkWrapper : public SST::Interfaces::SimpleNetwork {
public:
    SST_ELI_REGISTER_SUBCOMPONENT(
        SimpleNetworkWrapper,
        "SnnDL",
        "SimpleNetworkWrapper", 
        SST_ELI_ELEMENT_VERSION(1, 0, 0),
        "SimpleNetwork包装器，用于SnnNetworkAdapter的hr_router集成",
        SST::Interfaces::SimpleNetwork
    )

    SST_ELI_DOCUMENT_PARAMS(
        {"link_bw", "链路带宽", "40GiB/s"},
        {"verbose", "日志详细级别", "0"}
    )

    SST_ELI_DOCUMENT_PORTS(
        {"rtr_port", "路由器端口，连接到外部路由器", {"SimpleNetwork.Request"}}
    )

    /**
     * @brief 构造函数 - 标准SST SubComponent构造函数
     * @param id 组件ID
     * @param params 配置参数
     * @param port_number 端口号（SST要求）
     */
    SimpleNetworkWrapper(SST::ComponentId_t id, SST::Params& params, int port_number);
    
    /**
     * @brief 设置网络适配器
     * @param adapter SnnNetworkAdapter指针
     */
    void setNetworkAdapter(SnnNetworkAdapter* adapter);
    
    /**
     * @brief 析构函数
     */
    ~SimpleNetworkWrapper();

    // === SimpleNetwork 接口实现 ===
    bool send(SimpleNetwork::Request* req, int vn) override;
    SimpleNetwork::Request* recv(int vn) override;
    bool spaceToSend(int vn, int num_bits) override;
    bool requestToReceive(int vn) override;
    void setNotifyOnReceive(HandlerBase* functor) override;
    void setNotifyOnSend(HandlerBase* functor) override;
    bool isNetworkInitialized() const override;
    nid_t getEndpointID() const override;
    void sendUntimedData(SimpleNetwork::Request* req) override;
    SimpleNetwork::Request* recvUntimedData() override;
    const UnitAlgebra& getLinkBW() const override;

    // === SST组件生命周期方法 ===
    void init(unsigned int phase) override;
    void setup() override;
    void finish() override;

private:
    SST::Output* output;                      ///< 日志输出
    SnnNetworkAdapter* network_adapter;      ///< 关联的网络适配器
    UnitAlgebra link_bw_ua;                  ///< 链路带宽
    
    // SimpleNetwork状态
    bool network_initialized;                ///< 网络是否已初始化
    nid_t endpoint_id;                      ///< 端点ID
    HandlerBase* recv_notify_functor;       ///< 接收通知回调
    HandlerBase* send_notify_functor;       ///< 发送通知回调
    
    // 请求队列
    std::queue<SimpleNetwork::Request*> incoming_requests; ///< 接收请求队列
    std::queue<SimpleNetwork::Request*> outgoing_requests; ///< 发送请求队列
};

} // namespace SnnDL
} // namespace SST

#endif // _SIMPLENETWORKWRAPPER_H
