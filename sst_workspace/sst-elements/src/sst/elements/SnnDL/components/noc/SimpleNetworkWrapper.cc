// -*- c++ -*-
//
// Copyright 2025 SST Contributors
//
// SimpleNetworkWrapper.cc: SimpleNetwork包装器实现
//

#include "SimpleNetworkWrapper.h"
#include "SnnNetworkAdapter.h"
#include "SnnDLLogging.h"

#ifndef WRAP_LOG
#define WRAP_LOG(lvl, ...) SNNDL_LOGPTR(output, (lvl), __VA_ARGS__)
#endif

namespace SST {
namespace SnnDL {

SimpleNetworkWrapper::SimpleNetworkWrapper(SST::ComponentId_t id, SST::Params& params, int port_number)
    : SimpleNetwork(id), network_adapter(nullptr)
{
    // 初始化输出对象
    int verbose_level = params.find<int>("verbose", 0);
    output = new SST::Output("SimpleNetworkWrapper[@p:@l]: ", verbose_level, 0, SST::Output::STDOUT);
    
    // 解析链路带宽
    std::string link_bw = params.find<std::string>("link_bw", "40GiB/s");
    link_bw_ua = UnitAlgebra(link_bw);
    
    // 初始化状态
    network_initialized = false;
    endpoint_id = 0;
    recv_notify_functor = nullptr;
    send_notify_functor = nullptr;
    
    WRAP_LOG(1, "🔧 SimpleNetworkWrapper初始化完成\n");
}

void SimpleNetworkWrapper::setNetworkAdapter(SnnNetworkAdapter* adapter) 
{
    network_adapter = adapter;
    WRAP_LOG(1, "🔗 设置网络适配器成功\n");
}

SimpleNetworkWrapper::~SimpleNetworkWrapper() 
{
    delete output;
    
    // 清理队列中的请求
    while (!incoming_requests.empty()) {
        delete incoming_requests.front();
        incoming_requests.pop();
    }
    while (!outgoing_requests.empty()) {
        delete outgoing_requests.front();
        outgoing_requests.pop();
    }
}

void SimpleNetworkWrapper::init(unsigned int phase) 
{
    if (phase == 0) {
        network_initialized = true;
        // 从network_adapter获取endpoint_id
        if (network_adapter) {
            endpoint_id = static_cast<nid_t>(network_adapter->getNodeId());
        }
        WRAP_LOG(1, "🌐 SimpleNetworkWrapper网络初始化完成 (endpoint_id=%ld)\n", endpoint_id);
    }
}

void SimpleNetworkWrapper::setup() 
{
    WRAP_LOG(2, "🔧 SimpleNetworkWrapper setup完成\n");
}

void SimpleNetworkWrapper::finish() 
{
    WRAP_LOG(2, "🏁 SimpleNetworkWrapper finish完成\n");
}

bool SimpleNetworkWrapper::send(SimpleNetwork::Request* req, int vn) 
{
    if (!req || !network_adapter) return false;

    WRAP_LOG(2, "📤 包装器发送请求: 目标=%ld, 虚拟网络=%d\n", req->dest, vn);

    // 透传 payload（接管生命周期）
    if (!req->inspectPayload()) return false;
    SST::Event* payload = req->takePayload();
    const uint32_t dest_node = static_cast<uint32_t>(req->dest);
    delete req;
    network_adapter->sendToNode(dest_node, payload);

    // 触发发送通知
    if (send_notify_functor) {
        (*send_notify_functor)(vn);
    }
    return true;
}

SST::Interfaces::SimpleNetwork::Request* SimpleNetworkWrapper::recv(int vn) 
{
    // 检查接收队列
    if (!incoming_requests.empty()) {
        SimpleNetwork::Request* req = incoming_requests.front();
        incoming_requests.pop();
        WRAP_LOG(2, "📥 从队列接收请求\n");
        
        // 触发接收通知
        if (recv_notify_functor) {
            (*recv_notify_functor)(vn);
        }
        
        return req;
    }
    
    return nullptr;
}

bool SimpleNetworkWrapper::spaceToSend(int vn, int num_bits) 
{
    // 检查发送队列大小
    return outgoing_requests.size() < 10; // 最大缓冲10个请求
}

bool SimpleNetworkWrapper::requestToReceive(int vn) 
{
    return !incoming_requests.empty();
}

void SimpleNetworkWrapper::setNotifyOnReceive(HandlerBase* functor) 
{
    recv_notify_functor = functor;
    WRAP_LOG(1, "🔔 设置接收通知回调\n");
}

void SimpleNetworkWrapper::setNotifyOnSend(HandlerBase* functor) 
{
    send_notify_functor = functor;
    WRAP_LOG(1, "🔔 设置发送通知回调\n");
}

bool SimpleNetworkWrapper::isNetworkInitialized() const 
{
    return network_initialized;
}

SimpleNetworkWrapper::nid_t SimpleNetworkWrapper::getEndpointID() const 
{
    return endpoint_id;
}

void SimpleNetworkWrapper::sendUntimedData(SimpleNetwork::Request* req) 
{
    if (!req) {
        return;
    }
    
    WRAP_LOG(2, "📤 发送未定时数据\n");
    outgoing_requests.push(req);
}

SST::Interfaces::SimpleNetwork::Request* SimpleNetworkWrapper::recvUntimedData() 
{
    if (!incoming_requests.empty()) {
        SimpleNetwork::Request* req = incoming_requests.front();
        incoming_requests.pop();
        return req;
    }
    
    return nullptr;
}

const UnitAlgebra& SimpleNetworkWrapper::getLinkBW() const 
{
    return link_bw_ua;
}

} // namespace SnnDL
} // namespace SST
