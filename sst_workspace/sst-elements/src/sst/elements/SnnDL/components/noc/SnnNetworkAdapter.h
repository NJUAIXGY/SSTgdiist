// -*- c++ -*-
//
// Copyright 2025 SST Contributors
//
// SnnNetworkAdapter.h: SNN 通用网络拓扑适配器头文件
// NOTE: Experimental/advanced use. Default recommended NIC is SnnNIC
//       (SimpleNetwork/linkcontrol based). Prefer SnnNIC unless you
//       need topology experiments via this adapter.
//

#ifndef _SNNNETWORKADAPTER_H
#define _SNNNETWORKADAPTER_H

#include <sst/core/component.h>
#include <sst/core/interfaces/simpleNetwork.h>
#include <sst/core/link.h>
#include <sst/core/output.h>
#include <sst/core/statapi/statbase.h>
#include <queue>
#include <map>
#include <memory>
#include <vector>
#include <string>
#include "SnnInterface.h"
#include "NocPacketEvent.h"
#include "SimpleTestEvent.h"

namespace SST {
namespace SnnDL {

/**
 * @brief 网络拓扑类型枚举 (当前支持Mesh和Torus)
 */
enum class TopologyType {
    MESH_2D,        ///< 2D Mesh拓扑
    TORUS_2D        ///< 2D Torus拓扑
};

/**
 * @brief 拓扑处理器抽象基类
 */
class TopologyHandler {
public:
    virtual ~TopologyHandler() = default;
    
    /**
     * @brief 计算到目标节点的路由
     * @param dest_node 目标节点ID
     * @return 下一跳端口号或路由决策
     */
    virtual int calculateRoute(uint32_t dest_node) = 0;
    
    /**
     * @brief 计算到目标节点的跳数
     * @param dest_node 目标节点ID
     * @return 最短路径跳数
     */
    virtual int calculateHopDistance(uint32_t dest_node) = 0;
    
    /**
     * @brief 获取拓扑描述信息
     * @return 拓扑描述字符串
     */
    virtual std::string getTopologyDescription() = 0;
    
    /**
     * @brief 初始化拓扑参数
     * @param params SST参数集合
     * @param node_id 本节点ID
     */
    virtual void initialize(SST::Params& params, uint32_t node_id) = 0;
    
    /**
     * @brief 获取邻居节点列表
     * @return 邻居节点ID列表
     */
    virtual std::vector<uint32_t> getNeighbors() = 0;
};

/**
 * @brief 网络事件转换器 - Event 与 SimpleNetwork::Request 之间的转换
 */
class NetworkEventConverter {
public:
    /**
     * @brief 将 Event 转换为 SimpleNetwork::Request（接管 event 生命周期）
     * @param event 输入事件
     * @param dest_node 目标节点ID
     * @param src_node 源节点ID
     * @return 转换后的网络请求
     */
    static SST::Interfaces::SimpleNetwork::Request* convertEventToRequest(
        SST::Event* event, uint32_t dest_node, uint32_t src_node);
    
    /**
     * @brief 将SimpleNetwork::Request转换为 Event（接管返回指针生命周期）
     * @param request 输入的网络请求
     * @return 转换后的事件
     */
    static SST::Event* convertRequestToEvent(SST::Interfaces::SimpleNetwork::Request* request);
};

// 前向声明
class SimpleNetworkWrapper;

/**
 * @brief SNN 通用网络拓扑适配器
 * 
 * 该组件作为 SnnPE/MultiCorePE 与 Merlin 路由器之间的通用适配器，
 * 支持多种网络拓扑：Mesh、Torus、Dragonfly、Fat-tree、HyperX等。
 * 使用组合模式集成SimpleNetwork接口以支持hr_router集成。
 */
class SnnNetworkAdapter : public SnnInterface {
public:
    // SST组件注册宏
    SST_ELI_REGISTER_SUBCOMPONENT(
        SnnNetworkAdapter,                         // 类名
        "SnnDL",                                   // 元素库名称
        "SnnNetworkAdapter",                       // 组件名称
        SST_ELI_ELEMENT_VERSION(1, 0, 0),         // 版本号
        "SNN通用网络拓扑适配器",                    // 描述
        SST::SnnDL::SnnInterface                  // 父接口
    )

    // 参数文档
    SST_ELI_DOCUMENT_PARAMS(
        {"topology_type", "网络拓扑类型 [mesh2d|torus2d]", "mesh2d"},
        {"node_id", "节点ID", "0"},
        {"routing_algorithm", "路由算法 [XY|adaptive]", "XY"},
        {"link_bw", "链路带宽", "40GiB/s"},
        {"packet_size", "数据包大小", "64B"},
        {"input_buf_size", "输入缓冲区大小", "1KiB"},
        {"output_buf_size", "输出缓冲区大小", "1KiB"},
        
        // Mesh/Torus 拓扑参数
        {"topology_shape", "拓扑形状 (如: 4x4)", "4x4"},
        {"local_ports", "每个路由器的本地端口数", "1"},
        
        // 性能参数
        {"enable_adaptive_routing", "启用自适应路由", "false"},
        {"congestion_threshold", "拥塞阈值", "0.8"},
        {"enable_merlin_router", "启用Merlin路由器集成", "false"},
        {"use_direct_link", "是否使用直接Link模式", "false"},
        {"port_name", "网络端口名称", "network"},
        {"verbose", "日志详细级别", "0"}
    )

    // 端口文档
    SST_ELI_DOCUMENT_PORTS(
        {"network", "连接到merlin.linkcontrol或路由器的端口", {"SimpleNetwork"}},
        {"north", "北向连接端口（用于网格拓扑）", {"SnnDL.NocPacketEvent"}},
        {"south", "南向连接端口（用于网格拓扑）", {"SnnDL.NocPacketEvent"}},
        {"east", "东向连接端口（用于网格拓扑）", {"SnnDL.NocPacketEvent"}},
        {"west", "西向连接端口（用于网格拓扑）", {"SnnDL.NocPacketEvent"}}
    )

    // SubComponent槽位文档
    SST_ELI_DOCUMENT_SUBCOMPONENT_SLOTS(
        {"linkcontrol", "merlin LinkControl子组件", "SST::Interfaces::SimpleNetwork"}
    )

    // 统计信息文档
    SST_ELI_DOCUMENT_STATISTICS(
        {"spikes_routed", "路由的脉冲数量", "spikes", 1},
        {"local_spikes", "本地处理的脉冲数量", "spikes", 1},
        {"remote_spikes", "远程路由的脉冲数量", "spikes", 1},
        {"xy_routes", "XY路由使用次数", "routes", 1},
        {"adaptive_routes", "自适应路由使用次数", "routes", 1},
        {"congestion_events", "拥塞事件数量", "events", 1},
        {"total_hops", "总跳数统计", "hops", 1},
        {"average_latency", "平均延迟", "cycles", 1},
        {"max_hops", "最大跳数记录", "hops", 1},
        {"bandwidth_utilization", "带宽使用统计", "bytes", 1},
        {"packets_dropped", "丢包统计", "packets", 1}
    )

    /**
     * @brief 构造函数
     * @param id 组件ID
     * @param params 配置参数
     */
    SnnNetworkAdapter(SST::ComponentId_t id, SST::Params& params);

    /**
     * @brief 析构函数
     */
    ~SnnNetworkAdapter();

    // === SnnInterface 接口实现 ===
    void setReceiveHandler(ReceiveHandler handler) override;
    void sendToNode(uint32_t dest_node, SST::Event* event) override;
    void setNodeId(uint32_t node_id) override;
    uint32_t getNodeId() const override;
    std::string getNetworkStatus() const override;
    size_t pendingSendCount() const override;

    // === 网络接口回调方法 ===
    bool handleIncoming(int vn);
    bool spaceAvailable(int vn);
    void handleDirectEvent(SST::Event* event);

    // === SimpleNetwork 适配器访问 ===
    
    /**
     * @brief 获取SimpleNetwork包装器接口
     * @return SimpleNetworkWrapper指针
     */
    SimpleNetworkWrapper* getSimpleNetworkWrapper();
    
    /**
     * @brief 创建SimpleNetwork包装器
     * @param params 配置参数
     * @return 创建的包装器指针
     */
    SimpleNetworkWrapper* createSimpleNetworkWrapper(SST::Params& params);

    // === 链路注入接口（用于父组件代理） ===
    
    /**
     * @brief 注入父组件的方向链路
     * @param direction 方向名称 (north, south, east, west)
     * @param link 父组件的链路指针
     */
    void injectDirectionLink(const std::string& direction, SST::Link* link);
    
	    /**
	     * @brief 从父组件发送事件到指定方向
	     * @param event 要发送的事件
	     * @param direction 发送方向
	     * @return true 表示已成功注入链路（send接管event生命周期），false 表示丢弃（已delete event）
	     */
	    bool sendEventToDirection(SST::Event* event, const std::string& direction);
	    
	    // === SST组件生命周期方法 ===
	    void init(unsigned int phase) override;
	    void setup() override;
	    void finish() override;

private:
    // === 内部初始化方法 ===
    
    /**
     * @brief 初始化拓扑处理器
     */
    void initializeTopologyHandler();
    
    /**
     * @brief 解析拓扑类型字符串
     * @param type_str 拓扑类型字符串
     * @return 拓扑类型枚举
     */
    TopologyType parseTopologyType(const std::string& type_str);
    
    // === 路由方法 ===
    
    /**
     * @brief 路由事件到目标节点
     * @param event 事件
     * @param dest_node 目标节点ID
     */
    void routeEvent_(SST::Event* event, uint32_t dest_node);
    
    /**
     * @brief 通过直接Link发送事件
     * @param event 事件
     * @param dest_node 目标节点ID
     */
    void sendViaDirectLink_(SST::Event* event, uint32_t dest_node);
    
    /**
     * @brief 通过Merlin路由器发送事件
     * @param event 事件
     * @param dest_node 目标节点ID
     * @param next_port 下一跳端口
     */
    void sendViaMerlinRouter_(SST::Event* event, uint32_t dest_node, int next_port);
    
    /**
     * @brief 通过多端口Link发送事件
     * @param event 事件
     * @param dest_node 目标节点ID
     * @param next_port 下一跳端口ID（对应方向）
     */
    void sendViaMultiPortLink_(SST::Event* event, uint32_t dest_node, int next_port);
    
    /**
     * @brief 处理从Merlin路由器接收的网络事件
     * @param ev 网络事件
     */
    bool handleNetworkEvent(int vn);
    
    /**
     * @brief 创建网络请求（接管 event 生命周期）
     * @param event 事件
     * @param dest_node 目标节点ID
     * @param route_port 路由端口
     * @return 网络请求对象
     */
    SST::Interfaces::SimpleNetwork::Request* createNetworkRequest(
        SST::Event* event, uint32_t dest_node, int route_port);
    
    /**
     * @brief 从网络请求中解包事件（接管返回指针生命周期）
     * @param req 网络请求
     * @return 解包的事件
     */
    SST::Event* extractEventFromRequest(SST::Interfaces::SimpleNetwork::Request* req);
    
    // === 拥塞和负载管理 ===
    
    /**
     * @brief 检查端口拥塞情况
     * @param port 端口号
     * @return 拥塞程度 [0.0, 1.0]
     */
    double getPortCongestion(int port);
    
    /**
     * @brief 更新负载统计
     * @param port 端口号
     */
    void updateLoadStatistics(int port);

    // === 成员变量 ===
    
    // SST基础设施
    SST::Output* output;                        ///< 日志输出对象
    SST::Interfaces::SimpleNetwork* router;    ///< Merlin路由器接口
    SST::Link* direct_link;                     ///< 直接链接接口
    
    // 多端口direct_link支持
    std::map<std::string, SST::Link*> direction_links; ///< 方向端口链路映射 (north, south, east, west)
    bool use_multi_port;                       ///< 是否使用多端口模式
    
    // 父组件链路注入支持
    std::map<std::string, SST::Link*> parent_direction_links; ///< 父组件注入的方向链路
    
    // 拓扑配置
    TopologyType topology_type;                ///< 拓扑类型
    std::string topology_shape;                ///< 拓扑形状 (如: 2x2, 4x4)
    std::unique_ptr<TopologyHandler> topology_handler; ///< 拓扑处理器
    uint32_t node_id;                          ///< 节点ID
    std::string routing_algorithm;             ///< 路由算法
    
    // 网络配置
    std::string link_bw;                       ///< 链路带宽
    std::string packet_size;                   ///< 数据包大小
    std::string input_buf_size;                ///< 输入缓冲区大小
    std::string output_buf_size;               ///< 输出缓冲区大小
    
    // 性能优化配置
    bool enable_adaptive_routing;              ///< 是否启用自适应路由
    double congestion_threshold;               ///< 拥塞阈值
    bool enable_merlin_router;                 ///< 是否启用Merlin路由器集成
    bool use_direct_link;                      ///< 是否使用直接Link模式
    std::string port_name;                     ///< 网络端口名称
    
    // 回调处理器（接管 event 生命周期）
    ReceiveHandler receive_handler_;
    
    // SimpleNetwork包装器
    SimpleNetworkWrapper* simple_network_wrapper; ///< SimpleNetwork包装器
    
    // 运行时状态
    std::map<int, double> port_utilization;   ///< 端口利用率
    std::map<int, uint64_t> port_counters;    ///< 端口计数器
    struct PendingSend { uint32_t dest_node = 0; SST::Event* payload = nullptr; };
    std::queue<PendingSend> pending_sends_;   ///< 待发送队列
    uint64_t pending_send_enqueue_total_;     ///< pending_sends_ 累计入队数
    uint64_t pending_send_dequeue_total_;     ///< pending_sends_ 累计出队数
    uint64_t pending_send_high_watermark_;    ///< pending_sends_ 峰值深度
    uint64_t pending_send_space_block_total_; ///< router->spaceToSend 阻塞次数
    uint64_t pending_send_send_fail_total_;   ///< router->send 失败次数
    
    // 基础统计计数器
    uint64_t spikes_routed_count;
    uint64_t local_spikes_count;
    uint64_t remote_spikes_count;
    uint64_t xy_routes_count;
    uint64_t adaptive_routes_count;
    uint64_t congestion_events_count;
    
    // 扩展性能统计计数器
    uint64_t total_hops_count;              ///< 总跳数统计
    uint64_t average_latency_cycles;        ///< 平均延迟（周期）
    uint64_t max_hops_observed;             ///< 观察到的最大跳数
    uint64_t bandwidth_bytes_sent;          ///< 发送的总字节数
    uint64_t packets_dropped;               ///< 丢包统计
    
    // 基础统计对象
    Statistic<uint64_t>* stat_spikes_routed;
    Statistic<uint64_t>* stat_local_spikes;
    Statistic<uint64_t>* stat_remote_spikes;
    Statistic<uint64_t>* stat_xy_routes;
    Statistic<uint64_t>* stat_adaptive_routes;
    Statistic<uint64_t>* stat_congestion_events;
    
    // 扩展性能统计对象
    Statistic<uint64_t>* stat_total_hops;
    Statistic<uint64_t>* stat_average_latency;
    Statistic<uint64_t>* stat_max_hops;
    Statistic<uint64_t>* stat_bandwidth_utilization;
    Statistic<uint64_t>* stat_packets_dropped;
};

// === 拓扑处理器具体实现类 ===

/**
 * @brief 2D Mesh 拓扑处理器
 */
class Mesh2DHandler : public TopologyHandler {
public:
    void initialize(SST::Params& params, uint32_t node_id) override;
    int calculateRoute(uint32_t dest_node) override;
    int calculateHopDistance(uint32_t dest_node) override;
    std::string getTopologyDescription() override;
    std::vector<uint32_t> getNeighbors() override;

private:
    uint32_t width, height;                    ///< Mesh尺寸
    uint32_t my_x, my_y;                      ///< 本节点坐标
    uint32_t node_id;                         ///< 节点ID
    
    std::pair<uint32_t, uint32_t> nodeToCoord(uint32_t node_id);
    uint32_t coordToNode(uint32_t x, uint32_t y);
};

/**
 * @brief 2D Torus 拓扑处理器
 */
class Torus2DHandler : public TopologyHandler {
public:
    void initialize(SST::Params& params, uint32_t node_id) override;
    int calculateRoute(uint32_t dest_node) override;
    int calculateHopDistance(uint32_t dest_node) override;
    std::string getTopologyDescription() override;
    std::vector<uint32_t> getNeighbors() override;

private:
    uint32_t width, height;                    ///< Torus尺寸
    uint32_t my_x, my_y;                      ///< 本节点坐标
    uint32_t node_id;                         ///< 节点ID
    
    std::pair<uint32_t, uint32_t> nodeToCoord(uint32_t node_id);
    uint32_t coordToNode(uint32_t x, uint32_t y);
    int calculateTorusDistance(uint32_t coord1, uint32_t coord2, uint32_t dimension_size);
};


} // namespace SnnDL
} // namespace SST

#endif /* _SNNNETWORKADAPTER_H */
