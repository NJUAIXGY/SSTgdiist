// -*- c++ -*-
//
// Copyright 2025 SST Contributors
//
// SnnNIC.cc: SNN网络接口控制器实现文件
//

#include "SnnNIC.h"
#include <sst/core/serialization/serialize.h>
#include <sstream>
#include <fstream>
#include <cinttypes>
#include <limits>
#include <cmath>

#include "NocPacketBatchEvent.h"
#include "NocPacketEvent.h"
#include "SnnNICConfig.h"
#include "SnnDLLogging.h"

using namespace SST;
using namespace SST::SnnDL;
using namespace SST::Interfaces;

#ifndef NIC_LOG
// Usage: NIC_LOG(level, "fmt...", args...)
// Note: Do NOT pass CALL_INFO here; SNNDL_LOGPTR injects it.
#define NIC_LOG(lvl, ...) SNNDL_LOGPTR(output, (lvl), __VA_ARGS__)
#endif

// Static member definitions
std::mutex SnnNIC::s_spike_csv_mutex_;
std::unordered_set<std::string> SnnNIC::s_spike_csv_files_;

namespace {
constexpr uint32_t kNocPacketHeaderBytes =
    sizeof(uint32_t) * 2 + sizeof(uint16_t) * 4 + sizeof(uint64_t);  // 24B
constexpr uint32_t kBatchBaseHeaderBytes =
    sizeof(uint32_t) * 2 + sizeof(uint64_t);  // 16B
constexpr uint32_t kBatchPerPacketHeaderBytes =
    sizeof(uint16_t) * 4 + sizeof(uint64_t);  // 16B
} // namespace

// ---- 调试辅助：打印门控状态快照 ----
void SnnNIC::logGatingSnapshot(const char* ctx) const {
    if (!output) return;
    int isInit = (network != nullptr) ? (int)network->isNetworkInitialized() : 0;
    std::stringstream vns;
    vns << "[";
    for (size_t i = 0; i < vn_ready_.size(); ++i) {
        vns << (vn_ready_[i] ? '1' : '0');
        if (i + 1 < vn_ready_.size()) vns << ',';
    }
    vns << "]";
    NIC_LOG(1, "GATING(%s): ready=%d, isInit=%d, link_ready=%d, eff_vns=%u, vn_ready=%s\n",
            ctx ? ctx : "?", (int)network_ready_, isInit, (int)link_ready_, effective_num_vns_, vns.str().c_str());
}

SnnNIC::SnnNIC(ComponentId_t id, Params& params)
    : SnnInterface(id, params),
      output(nullptr),
      network(nullptr),
      direct_link(nullptr),
      receive_handler_(nullptr),
      spikes_sent_count(0),
      spikes_received_count(0),
      packets_sent_count(0),
      packets_received_count(0),
      use_direct_link(false)
{
    const SnnNICConfig cfg = parseSnnNICConfig(params);

    // P2: 环境变量前端化 – 优先参数，其次回退到环境变量，保持兼容
    sentinel_enabled_ = cfg.sentinel_enable;
    if (sentinel_enabled_) {
        NIC_LOG(2, "[[sentinel-nic-ctor]] enter\n");
    }

    // 获取参数
    node_id = cfg.node_id;
    link_bw = cfg.link_bw;
    input_buf_size = cfg.input_buf_size;
    output_buf_size = cfg.output_buf_size;
    use_direct_link = cfg.use_direct_link;  // 默认禁用直连，统一走SimpleNetwork
    // 禁用direct_link实现，统一走SimpleNetwork，避免脚本依赖非标准直连模式
    if (use_direct_link) {
        NIC_LOG(1, "direct_link 模式已禁用，回退到 SimpleNetwork");
        use_direct_link = false;
    }
    
    // 新增：虚拟通道与批处理参数（默认保持兼容）
    // Merlin hr_router 默认 num_vns=2：在高并发 spike 流量下，强制单VN容易导致 credit/backpressure 不收敛。
    // 因此这里允许脚本显式配置 VN 数；若不配置则默认 2。
    virtual_channels_ = cfg.virtual_channels;
    network_num_vns_ = cfg.network_num_vns;
    auto_vn_fallback_ = cfg.auto_vn_fallback;
    effective_num_vns_ = cfg.effective_num_vns;
    if (effective_num_vns_ == 0) effective_num_vns_ = 1;
    NIC_LOG(2, "VN配置: virtual_channels=%u, network_num_vns=%u, effective_num_vns=%u\n",
                 virtual_channels_, network_num_vns_, effective_num_vns_);
    vn_spike_data_ = cfg.vn_spike_data;
    vn_batch_data_ = cfg.vn_batch_data;
    enable_batching_ = cfg.enable_batching;
    flush_on_credit_ = cfg.flush_on_credit;
    probe_vn_on_setup_ = cfg.probe_vn_on_setup;
    batch_size_local_ = cfg.batch_size_local;
    batch_size_remote_ = cfg.batch_size_remote;
    batch_flush_window_ns_ = cfg.batch_flush_window_ns;
    total_nodes_ = cfg.total_nodes;
    // 控制VN（用于门控等控制事件）
    vn_control_ = cfg.vn_control;

    // 跨Rank代理聚合参数（默认关闭）
    enable_inter_rank_batching_ = cfg.enable_inter_rank_batching;
    inter_rank_batch_window_ns_ = cfg.inter_rank_batch_window_ns;
    nodes_per_rank_ = cfg.nodes_per_rank;
    // 强制禁用跨Rank聚合
    enable_inter_rank_batching_ = false;
    inter_rank_batch_window_ns_ = 0;
    nodes_per_rank_ = 0;
    
    // 初始化日志输出
    output = new Output("SnnNIC[@p:@l]: ", cfg.verbose, 0, Output::STDOUT);
    
    // 初始化每个VN的就绪标志
    vn_ready_.assign(effective_num_vns_, false);
    if (use_direct_link) {
        // 使用直接Link模式
        direct_link = configureLink("network", 
            new Event::Handler2<SnnNIC,&SnnNIC::handleDirectSpikeEvent>(this));
        
        if (direct_link) {
        } else {
        }
    } else {
        // 使用SimpleNetwork模式 - 参考MemNIC的成功实现
        // 首先尝试加载用户定义的网络接口
        network = loadUserSubComponent<SimpleNetwork>("linkcontrol", ComponentInfo::SHARE_NONE, static_cast<int>(effective_num_vns_));
        if (!network) {
            // 创建默认的 linkcontrol
            Params net_params;
            net_params.insert("port_name", cfg.port_name);
            net_params.insert("link_bw", link_bw);
            net_params.insert("input_buf_size", input_buf_size);
            net_params.insert("output_buf_size", output_buf_size);
            // 使用一致的VN数量（与 effective_num_vns_ 对齐）
            net_params.insert("num_vns", std::to_string(effective_num_vns_));
            // 添加PortControl协议调试参数
            net_params.insert("job_id", "0");
            // job_size=总节点数
            net_params.insert("job_size", std::to_string(total_nodes_));
            net_params.insert("logical_nid", std::to_string(node_id));
            
            network = loadAnonymousSubComponent<SimpleNetwork>("merlin.linkcontrol", "linkcontrol", 0, 
                ComponentInfo::SHARE_PORTS | ComponentInfo::INSERT_STATS, net_params, static_cast<int>(effective_num_vns_));
        }
        
        if (network) {
            // 设置网络回调处理器
            network->setNotifyOnReceive(new SimpleNetwork::Handler2<SnnNIC,&SnnNIC::handleIncoming>(this));
            network->setNotifyOnSend(new SimpleNetwork::Handler2<SnnNIC,&SnnNIC::spaceAvailable>(this));
        }
    }
    
    // 注册统计信息
    stat_spikes_sent = registerStatistic<uint64_t>("spikes_sent");
    stat_spikes_received = registerStatistic<uint64_t>("spikes_received");
    stat_packets_sent = registerStatistic<uint64_t>("packets_sent");
    stat_packets_received = registerStatistic<uint64_t>("packets_received");
    stat_batches_sent = registerStatistic<uint64_t>("batches_sent");
    stat_ir_batches_sent = registerStatistic<uint64_t>("inter_rank_batches_sent");
    // P1：注册消息时延统计（纳秒）
    stat_msg_latency_ns = registerStatistic<uint64_t>("msg_latency_ns");

    // Tier 1
    stat_spikes_local_core = registerStatistic<uint64_t>("spikes_local_core");
    stat_spikes_neighbor_node = registerStatistic<uint64_t>("spikes_neighbor_node");
    stat_spikes_remote_node = registerStatistic<uint64_t>("spikes_remote_node");

    // 批处理效率
    stat_batch_total_spikes = registerStatistic<uint64_t>("batch_total_spikes");
    stat_batch_flush_timeout = registerStatistic<uint64_t>("batch_flush_timeout");
    stat_batch_flush_full = registerStatistic<uint64_t>("batch_flush_full");

    // 流量类型
    stat_payload_bytes_sent = registerStatistic<uint64_t>("payload_bytes_sent");
    stat_total_bytes_sent = registerStatistic<uint64_t>("total_bytes_sent");

    // hop count
    stat_hop_count_sum = registerStatistic<uint64_t>("hop_count_sum");
    stat_hop_count_max = registerStatistic<uint64_t>("hop_count_max");
    stat_hop_count_min = registerStatistic<uint64_t>("hop_count_min");

    // 批大小聚合
    stat_batch_size_sum = registerStatistic<uint64_t>("batch_size_sum");
    stat_batch_size_max = registerStatistic<uint64_t>("batch_size_max");
    stat_batch_size_min = registerStatistic<uint64_t>("batch_size_min");
}

SnnNIC::~SnnNIC()
{
    // 让进程退出阶段由运行时回收日志对象，避免潜在的析构次序竞态
    output = nullptr;

    // 清理待发送队列（所有权在 NIC）
    while (!pending_sends_.empty()) {
        auto& ps = pending_sends_.front();
        delete ps.payload;
        pending_sends_.pop();
    }
    // 清理批处理桶
    for (auto& kv : batch_buckets_) {
        for (auto* pkt : kv.second) delete pkt;
        kv.second.clear();
    }
    batch_earliest_ts_.clear();
}

void SnnNIC::setReceiveHandler(ReceiveHandler handler)
{
    receive_handler_ = std::move(handler);
    NIC_LOG(2, "设置接收处理器\n");
}

int SnnNIC::estimateEventBits_(const SST::Event* ev) const
{
    if (!ev) return 0;
    if (auto* pkt = dynamic_cast<const NocPacketEvent*>(ev)) {
        const uint64_t bytes = kNocPacketHeaderBytes + static_cast<uint64_t>(pkt->payload.size());
        return static_cast<int>(bytes * 8);
    }
    if (auto* batch = dynamic_cast<const NocPacketBatchEvent*>(ev)) {
        uint64_t bytes = kBatchBaseHeaderBytes;
        for (const auto& p : batch->packets) {
            bytes += kBatchPerPacketHeaderBytes + static_cast<uint64_t>(p.payload.size());
        }
        return static_cast<int>(bytes * 8);
    }
    return 256;
}

SimpleNetwork::Request* SnnNIC::createNetworkRequest_(uint32_t dest_node,
                                                      SST::Event* payload,
                                                      int vn,
                                                      int size_bits)
{
    auto* req = new SimpleNetwork::Request();
    req->dest = dest_node;
    req->src = node_id;
    req->vn = vn;
    req->size_in_bits = size_bits;
    req->head = true;
    req->tail = true;
    req->allow_adaptive = true;
    req->givePayload(payload);
    return req;
}

void SnnNIC::sendToNode(uint32_t dest_node, SST::Event* event)
{
    if (!event) return;

    // 批处理仅对 NoC 包生效
    if (enable_batching_) {
        if (auto* pkt = dynamic_cast<NocPacketEvent*>(event)) {
            tryBatchPacket_(dest_node, pkt);
            return;
        }
    }

    if (!network) {
        delete event;
        return;
    }

    int vn_use = static_cast<int>(vn_spike_data_);
    if (vn_use >= static_cast<int>(effective_num_vns_)) vn_use = 0;

    const int bits = estimateEventBits_(event);
    auto* req = createNetworkRequest_(dest_node, event, vn_use, bits);

    bool sent = false;
    if (network->spaceToSend(req->vn, req->size_in_bits)) {
        sent = network->send(req, req->vn);
    }

    if (sent) {
        packets_sent_count++;
        stat_packets_sent->addData(1);

        if (auto* pkt = dynamic_cast<NocPacketEvent*>(event)) {
            if (pkt->packetKind() == NocPacketKind::Spike) {
                spikes_sent_count++;
                stat_spikes_sent->addData(1);

                if (dest_node == node_id) {
                    if (stat_spikes_local_core) stat_spikes_local_core->addData(1);
                } else if (isNeighborNode(dest_node)) {
                    if (stat_spikes_neighbor_node) stat_spikes_neighbor_node->addData(1);
                } else {
                    if (stat_spikes_remote_node) stat_spikes_remote_node->addData(1);
                }
            }
            const uint64_t payload_bytes = static_cast<uint64_t>(pkt->payload.size());
            const uint64_t total_bytes = static_cast<uint64_t>((bits + 7) / 8);
            if (stat_payload_bytes_sent) stat_payload_bytes_sent->addData(payload_bytes);
            if (stat_total_bytes_sent) stat_total_bytes_sent->addData(total_bytes);
        }
        return;
    }

    // 失败：取回 payload 并入队
    SST::Event* payload = req->takePayload();
    delete req;
    pending_sends_.push(PendingSend{dest_node, payload});
}

void SnnNIC::setNodeId(uint32_t id)
{
    node_id = id;
}

uint32_t SnnNIC::getNodeId() const
{
    return node_id;
}

std::string SnnNIC::getNetworkStatus() const
{
    std::stringstream ss;
    ss << "SnnNIC状态[节点" << node_id << "]: ";
    ss << "发送脉冲=" << spikes_sent_count;
    ss << ", 接收脉冲=" << spikes_received_count;
    ss << ", 发送包=" << packets_sent_count;
    ss << ", 接收包=" << packets_received_count;
    ss << ", 待发送=" << pending_sends_.size();
    return ss.str();
}

size_t SnnNIC::pendingSendCount() const
{
    // 只统计 NIC 内部排队的“尚未进入网络”的事件：
    // - pending_sends_: 由于 backpressure 导致的待发送队列
    // - batch_buckets_: 批处理尚未 flush 的包
    size_t total = pending_sends_.size();
    for (const auto& kv : batch_buckets_) {
        total += kv.second.size();
    }
    return total;
}

bool SnnNIC::handleIncoming(int vn)
{
    if (!network) return true;
    // 注意：SimpleNetwork 的 receive 通知仅表示“有数据可读”，必须 drain 到 recv()==nullptr，
    // 否则会导致对端信用/缓冲无法回收，进而让发送侧永久 spaceToSend=false（并卡住全局 drain-barrier）。
    while (true) {
        SimpleNetwork::Request* req = network->recv(vn);
        if (!req) break;

        packets_received_count++;
        if (stat_packets_received) stat_packets_received->addData(1);

        const uint32_t src_node = static_cast<uint32_t>(req->src);
        const uint32_t dst_node = static_cast<uint32_t>(req->dest);

        SST::Event* ev = req->takePayload(); // 接管 payload 生命周期
        delete req;
        if (!ev) continue;

        auto deliverPacket = [&](NocPacketEvent* pkt) {
            if (!pkt) return;
            // 容错：若发送端未填 node 字段，按 Request 头补齐（不会覆盖非0值）
            if (pkt->src_node == 0 && src_node != 0) pkt->src_node = src_node;
            if (pkt->dst_node == 0 && dst_node != 0) pkt->dst_node = dst_node;

            if (pkt->packetKind() == NocPacketKind::Spike) {
                spikes_received_count++;
                if (stat_spikes_received) stat_spikes_received->addData(1);
                if (stat_msg_latency_ns) {
                    const uint64_t now_ns = getCurrentSimTimeNano();
                    if (now_ns >= pkt->timestamp) stat_msg_latency_ns->addData(now_ns - pkt->timestamp);
                }
            }

            if (receive_handler_) {
                receive_handler_(pkt); // handler 接管生命周期
            } else {
                delete pkt;
            }
        };

        // 批量包：在 NIC 内展开为单条 NocPacketEvent，保持上层逻辑不变
        if (auto* batch = dynamic_cast<NocPacketBatchEvent*>(ev)) {
            for (auto& p : batch->packets) {
                auto* pkt = new NocPacketEvent();
                pkt->src_node = batch->src_node;
                pkt->dst_node = batch->dst_node;
                pkt->src_endpoint = p.src_endpoint;
                pkt->dst_endpoint = p.dst_endpoint;
                pkt->kind = p.kind;
                pkt->hop_count = p.hop_count;
                pkt->step_seq = p.step_seq;
                pkt->timestamp = p.timestamp;
                pkt->payload = std::move(p.payload);
                deliverPacket(pkt);
            }
            delete batch;
            continue;
        }

        // 普通包
        if (auto* pkt = dynamic_cast<NocPacketEvent*>(ev)) {
            deliverPacket(pkt);
            continue;
        }

        // 非 NoC 包事件：直接透传给 handler
        if (receive_handler_) {
            receive_handler_(ev);
        } else {
            delete ev;
        }
    }
    return true;
}

bool SnnNIC::spaceAvailable(int vn)
{
    NIC_LOG(5, "网络发送空间可用：VN=%d\n", vn);
    if (vn >= 0 && vn < (int)vn_ready_.size()) vn_ready_[vn] = true;
    if (!link_ready_) {
        link_ready_ = true;
        NIC_LOG(3, "LinkControl握手完成: link_ready=1, VN=%d 标记就绪\n", vn);
    }
    if (!network_ready_ || !network || !network->isNetworkInitialized() || !link_ready_) {
        NIC_LOG(2, "回调时网络未就绪，跳过待发送队列: ready=%d, isInit=%d, link_ready=%d\n",
               (int)network_ready_, network ? (int)network->isNetworkInitialized() : 0, (int)link_ready_);
        return true;
    }
    // 批处理刷新（阈值到达时立刻打包发送）
    if (enable_batching_ && flush_on_credit_) {
        for (auto& kv : batch_buckets_) {
            const uint32_t dest = kv.first;
            const auto& vec = kv.second;
            const uint32_t threshold = isNeighborNode(dest) ? batch_size_local_ : batch_size_remote_;
            if (!vec.empty() && vec.size() >= threshold) {
                flushBatchToNode_(dest, /*is_timeout=*/false);
            }
        }
    }

    flushPendingSends_();
    return true;
}

void SnnNIC::finish()
{
    // 安全收尾：避免在finish阶段进行复杂I/O或对象释放，交由进程退出回收
    // 注：不打印“最终统计”，减少退出期竞态干扰
    if (!use_direct_link && network) network->finish();
}

void SnnNIC::handleDirectSpikeEvent(SST::Event* event)
{
    if (!event) return;
    // direct_link 模式已禁用；保留最小实现以避免配置误用时崩溃
    if (receive_handler_) {
        receive_handler_(event);
    } else {
        delete event;
    }
}

// === SST lifecycle ===
void SnnNIC::init(unsigned int phase)
{
    if (output && sentinel_enabled_ && output->getVerboseLevel() >= 2) {
        output->verbose(CALL_INFO, 2, 0, "[[sentinel-nic-init]] node=%u phase=%u enter\n", node_id, phase);
    }
    if (!use_direct_link && network) {
        network->init(phase);
    }
    // 周期性轻量刷新：确保 pending_sends_ 在某些 spaceAvailable 回调不触发的组合下仍能被推进，
    // 避免 Global step drain-based barrier 被 NIC 背压队列永久卡住。
    if (phase == 0) {
        registerClock("10ns", new Clock::Handler2<SnnNIC, &SnnNIC::flushClockTick>(this));
    }
    if (phase >= 1) init_done_ = true;
    if (output && sentinel_enabled_ && output->getVerboseLevel() >= 2) {
        output->verbose(CALL_INFO, 2, 0, "[[sentinel-nic-init]] node=%u phase=%u done\n", node_id, phase);
    }
}

void SnnNIC::setup()
{
    if (output && sentinel_enabled_ && output->getVerboseLevel() >= 2) {
        output->verbose(CALL_INFO, 2, 0, "[[sentinel-nic-setup]] node=%u enter\n", node_id);
    }
    if (!use_direct_link && network) {
        network->setup();
    }
    network_ready_ = true;
    // 仅在显式提高verbose等级或调试时打印NIC配置
    NIC_LOG(2,
        "[nic-config] node=%u mode=%s link_bw=%s in_buf=%s out_buf=%s vn=%u\n",
        node_id,
        use_direct_link ? "direct" : "SimpleNetwork",
        link_bw.c_str(), input_buf_size.c_str(), output_buf_size.c_str(),
        effective_num_vns_);
    if (output && sentinel_enabled_ && output->getVerboseLevel() >= 2) {
        output->verbose(CALL_INFO, 2, 0, "[[sentinel-nic-setup]] node=%u done\n", node_id);
    }
}

bool SnnNIC::flushClockTick(SST::Cycle_t /*currentCycle*/)
{
    // 批处理窗口刷新（轻量）
    if (enable_batching_) {
        flushAllBatches_();
    }
    // 同时刷新 pending_sends_（避免背压队列依赖 spaceAvailable 回调）
    flushPendingSends_();
    return false; // 返回 false 表示保持 handler 继续挂在时钟上
}

uint32_t SnnNIC::computeDestNode(uint32_t /*dest_neuron*/) const
{
    // NoC 层不做 neuron->node 映射；由上层构造 packet/header
    return 0;
}

uint32_t SnnNIC::manhattanDistance(uint32_t src_node, uint32_t dst_node) const
{
    if (src_node == dst_node) return 0;

    uint32_t mesh = mesh_size_;
    if (mesh == 0 && total_nodes_ > 0) {
        const double root = std::sqrt(static_cast<double>(total_nodes_));
        const uint32_t side = static_cast<uint32_t>(root + 0.5);
        if (side > 0 && side * side == total_nodes_) {
            mesh = side;
        }
    }
    if (mesh == 0) return 0;

    const uint32_t src_x = src_node % mesh;
    const uint32_t src_y = src_node / mesh;
    const uint32_t dst_x = dst_node % mesh;
    const uint32_t dst_y = dst_node / mesh;

    const int dx = static_cast<int>(src_x) - static_cast<int>(dst_x);
    const int dy = static_cast<int>(src_y) - static_cast<int>(dst_y);
    return static_cast<uint32_t>(std::abs(dx) + std::abs(dy));
}

bool SnnNIC::isNeighborNode(uint32_t dest_node) const
{
    // 邻居定义：mesh 拓扑下 Manhattan 距离为 1（不含本地节点）
    if (dest_node == node_id) return false;
    return manhattanDistance(node_id, dest_node) == 1;
}

void SnnNIC::flushPendingSends_()
{
    if (!network) return;
    int vn_use = static_cast<int>(vn_spike_data_);
    if (vn_use >= static_cast<int>(effective_num_vns_)) vn_use = 0;

    while (!pending_sends_.empty()) {
        PendingSend& ps = pending_sends_.front();
        if (!ps.payload) {
            pending_sends_.pop();
            continue;
        }

        // 先计算统计/大小，再把 payload 交给 Request
        const int bits = estimateEventBits_(ps.payload);
        const bool is_pkt = dynamic_cast<NocPacketEvent*>(ps.payload) != nullptr;
        NocPacketKind kind = NocPacketKind::Unknown;
        uint64_t payload_bytes = 0;
        if (is_pkt) {
            auto* pkt = static_cast<NocPacketEvent*>(ps.payload);
            kind = pkt->packetKind();
            payload_bytes = static_cast<uint64_t>(pkt->payload.size());
        }
        const uint64_t total_bytes = static_cast<uint64_t>((bits + 7) / 8);

        auto* req = createNetworkRequest_(ps.dest_node, ps.payload, vn_use, bits);
        bool sent = false;
        const bool space_ok = network->spaceToSend(req->vn, req->size_in_bits);
        if (space_ok) {
            sent = network->send(req, req->vn);
        }
        if (!sent) {
            ps.payload = req->takePayload();
            delete req;
            if (sentinel_enabled_ && output && output->getVerboseLevel() >= 2 &&
                (pending_send_stall_log_count_ < 32 || pending_sends_.size() <= 16)) {
                const uint32_t dst = ps.dest_node;
                const uint64_t total_bytes_u64 = static_cast<uint64_t>((bits + 7) / 8);
                const int isInit = network ? (int)network->isNetworkInitialized() : 0;

                const char* etype = "Event";
                uint32_t pkt_kind_u = 0;
                uint64_t payload_bytes_u64 = 0;
                if (auto* pkt = dynamic_cast<NocPacketEvent*>(ps.payload)) {
                    etype = "NocPacketEvent";
                    pkt_kind_u = static_cast<uint32_t>(pkt->kind);
                    payload_bytes_u64 = static_cast<uint64_t>(pkt->payload.size());
                } else if (auto* batch = dynamic_cast<NocPacketBatchEvent*>(ps.payload)) {
                    etype = "NocPacketBatchEvent";
                    pkt_kind_u = static_cast<uint32_t>(batch->packets.empty() ? 0 : batch->packets[0].kind);
                    payload_bytes_u64 = static_cast<uint64_t>(batch->packets.size());
                }

                output->verbose(
                    CALL_INFO, 2, 0,
                    "[[sentinel-nic-stall]] node=%u dst=%u vn=%d bits=%d bytes=%" PRIu64 " out_buf=%s pending=%zu ready=%d isInit=%d link_ready=%d space=%d type=%s kind=%u payload=%" PRIu64 "\n",
                    node_id,
                    dst,
                    vn_use,
                    bits,
                    (uint64_t)total_bytes_u64,
                    output_buf_size.c_str(),
                    pending_sends_.size(),
                    (int)network_ready_,
                    isInit,
                    (int)link_ready_,
                    (int)space_ok,
                    etype,
                    pkt_kind_u,
                    (uint64_t)payload_bytes_u64);
                pending_send_stall_log_count_ += 1;
            }
            break;
        }

        packets_sent_count++;
        if (stat_packets_sent) stat_packets_sent->addData(1);

        if (is_pkt && kind == NocPacketKind::Spike) {
            spikes_sent_count++;
            if (stat_spikes_sent) stat_spikes_sent->addData(1);
            if (ps.dest_node == node_id) {
                if (stat_spikes_local_core) stat_spikes_local_core->addData(1);
            } else if (isNeighborNode(ps.dest_node)) {
                if (stat_spikes_neighbor_node) stat_spikes_neighbor_node->addData(1);
            } else {
                if (stat_spikes_remote_node) stat_spikes_remote_node->addData(1);
            }
        }
        if (is_pkt) {
            if (stat_payload_bytes_sent) stat_payload_bytes_sent->addData(payload_bytes);
            if (stat_total_bytes_sent) stat_total_bytes_sent->addData(total_bytes);
        }

        ps.payload = nullptr;
        pending_sends_.pop();
    }
}

void SnnNIC::tryBatchPacket_(uint32_t dest_node, NocPacketEvent* pkt)
{
    if (!pkt) return;
    if (!network) {
        delete pkt;
        return;
    }

    auto& vec = batch_buckets_[dest_node];
    vec.push_back(pkt);
    uint64_t& earliest = batch_earliest_ts_[dest_node];
    if (earliest == 0 || pkt->timestamp < earliest) earliest = pkt->timestamp;

    const uint32_t threshold = isNeighborNode(dest_node) ? batch_size_local_ : batch_size_remote_;
    if (threshold > 0 && vec.size() >= threshold) {
        flushBatchToNode_(dest_node, /*is_timeout=*/false);
    }
}

void SnnNIC::flushBatchToNode_(uint32_t dest_node, bool is_timeout)
{
    auto it = batch_buckets_.find(dest_node);
    if (it == batch_buckets_.end()) return;
    auto& vec = it->second;
    if (vec.empty()) return;

    auto* batch = new NocPacketBatchEvent();
    batch->src_node = node_id;
    batch->dst_node = dest_node;
    batch->batch_timestamp = batch_earliest_ts_.count(dest_node) ? batch_earliest_ts_[dest_node] : 0;
    batch->packets.reserve(vec.size());

    uint64_t payload_sum = 0;
    for (auto* pkt : vec) {
        if (!pkt) continue;
        NocPacketBatchEvent::PackedPacket pp;
        pp.src_endpoint = pkt->src_endpoint;
        pp.dst_endpoint = pkt->dst_endpoint;
        pp.kind = pkt->kind;
        pp.hop_count = pkt->hop_count;
        pp.step_seq = pkt->step_seq;
        pp.timestamp = pkt->timestamp;
        pp.payload = std::move(pkt->payload);
        payload_sum += static_cast<uint64_t>(pp.payload.size());
        batch->packets.emplace_back(std::move(pp));
        delete pkt;
    }
    vec.clear();
    batch_earliest_ts_.erase(dest_node);

    if (stat_batches_sent) stat_batches_sent->addData(1);
    if (stat_batch_total_spikes) stat_batch_total_spikes->addData(batch->packets.size());
    if (is_timeout) {
        if (stat_batch_flush_timeout) stat_batch_flush_timeout->addData(1);
    } else {
        if (stat_batch_flush_full) stat_batch_flush_full->addData(1);
    }
    logSpikeMessage_(is_timeout ? "batch_timeout" : "batch_full",
                     node_id, dest_node, 0, 0,
                     static_cast<uint32_t>(batch->packets.size()),
                     static_cast<uint32_t>(payload_sum));

    // 作为一个事件发出（sendToNode 接管生命周期）
    sendToNode(dest_node, batch);
}

void SnnNIC::flushAllBatches_()
{
    if (batch_buckets_.empty()) return;
    std::vector<uint32_t> keys;
    keys.reserve(batch_buckets_.size());
    for (auto& kv : batch_buckets_) {
        if (!kv.second.empty()) keys.push_back(kv.first);
    }
    for (uint32_t dest : keys) {
        flushBatchToNode_(dest, /*is_timeout=*/true);
    }
}

bool SnnNIC::sendControl(SST::Event* ev, uint32_t dest_node)
{
    if (!network || !ev) return false;
    SimpleNetwork::Request* req = new SimpleNetwork::Request();
    req->dest = dest_node;
    req->src = node_id;
    int vn_use = static_cast<int>(vn_control_);
    if (vn_use >= static_cast<int>(effective_num_vns_)) vn_use = 0;
    req->vn = vn_use;
    req->size_in_bits = 256;
    req->head = true;
    req->tail = true;
    req->allow_adaptive = true;
    req->givePayload(ev);
    if (network->spaceToSend(req->vn, req->size_in_bits) && network->send(req, req->vn)) {
        stat_packets_sent->addData(1);
        return true;
    }
    // 失败：取回 payload，保持“失败时由调用方负责释放”的语义（避免 double free）
    (void)req->takePayload();
    delete req;
    return false;
}

void SnnNIC::logSpikeMessage_(const char* kind,
                          uint32_t src_node,
                          uint32_t dst_node,
                          uint64_t /*logical_step*/,
                          uint64_t /*start_ns*/,
                          uint32_t spike_count,
                          uint32_t payload_bytes)
{
    if (spike_trace_csv_.empty()) return;
    std::lock_guard<std::mutex> guard(s_spike_csv_mutex_);
    std::ofstream f(spike_trace_csv_, std::ios::app);
    if (!f.good()) return;
    static constexpr const char* header =
        "kind,src_tile,dst_tile,spike_count,payload_bytes\n";
    if (s_spike_csv_files_.insert(spike_trace_csv_).second) {
        f << header;
    }
    f << (kind ? kind : "spike") << ',' << src_node << ',' << dst_node << ','
      << spike_count << ',' << payload_bytes << '\n';
}
