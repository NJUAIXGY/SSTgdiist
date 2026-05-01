// -*- c++ -*-
//
// Copyright 2025 SST Contributors
//
// OptimizedInternalRing.h: 优化的内部环形网络实现
//

#ifndef _OPTIMIZED_INTERNAL_RING_H
#define _OPTIMIZED_INTERNAL_RING_H

#include <sst/core/output.h>
#include <vector>
#include <queue>
#include <atomic>
#include <memory>
#include <unordered_map>
#include <cstdint>

namespace SST { class Event; }

namespace SST { namespace SnnDL {

/**
 * @brief 内部互连消息类型
 */
enum class RingMessageType {
    PACKET_MESSAGE,    // 通用包消息（payload-agnostic）
    MEMORY_REQUEST,    // 内存请求  
    MEMORY_RESPONSE,   // 内存响应
    CONTROL_MESSAGE    // 控制消息
};

/**
 * @brief 内部环形网络消息
 */
struct RingMessage {
    RingMessageType type;
    int src_unit;      // 源处理单元ID
    int dst_unit;      // 目标处理单元ID  
    uint64_t timestamp;
    int priority;      // 消息优先级
    
    union {
        SST::Event* packet;
        void* mem_request;
        void* mem_response;
        void* ctrl_data;
    } payload;
    
    RingMessage() : type(RingMessageType::PACKET_MESSAGE), 
                   src_unit(-1), dst_unit(-1), timestamp(0), priority(1) {
        payload.packet = nullptr;
    }
    
    // 拷贝构造函数
    RingMessage(const RingMessage& other) 
        : type(other.type), src_unit(other.src_unit), dst_unit(other.dst_unit), 
          timestamp(other.timestamp), priority(other.priority) {
        payload = other.payload;  // 浅拷贝指针
    }
    
    // 赋值操作符
    RingMessage& operator=(const RingMessage& other) {
        if (this != &other) {
            type = other.type;
            src_unit = other.src_unit;
            dst_unit = other.dst_unit;
            timestamp = other.timestamp;
            priority = other.priority;
            payload = other.payload;  // 浅拷贝指针
        }
        return *this;
    }
    
    ~RingMessage() {
        // 注意：不在这里删除payload，由发送方负责内存管理
    }
};

/**
 * @brief 路由决策枚举
 */
enum class RouteDirection {
    CLOCKWISE,          // 顺时针
    COUNTER_CLOCKWISE,  // 逆时针  
    LOCAL,              // 本地（目标就是当前节点）
    INVALID             // 无效路由
};

/**
 * @brief 虚拟通道状态
 */
enum class VCState {
    IDLE,       // 空闲
    ROUTING,    // 路由中
    BLOCKED,    // 阻塞
    ACTIVE      // 活跃传输
};

/**
 * @brief 虚拟通道结构
 */
struct VirtualChannel {
    int vc_id;                              ///< 虚拟通道ID
    int priority;                           ///< 优先级 (0=最高)
    VCState state;                          ///< 当前状态
    std::queue<RingMessage> buffer;         ///< 消息缓冲区
    uint32_t credits;                       ///< 信用计数
    uint32_t max_credits;                   ///< 最大信用数
    uint64_t last_activity_cycle;           ///< 最后活动周期
    
    VirtualChannel(int id = 0, int prio = 0, uint32_t max_cred = 8) 
        : vc_id(id), priority(prio), state(VCState::IDLE), 
          credits(max_cred), max_credits(max_cred), last_activity_cycle(0) {}
    
    bool hasSpace() const { return credits > 0 && buffer.size() < max_credits; }
    bool hasData() const { return !buffer.empty(); }
    void consumeCredit() { if (credits > 0) credits--; }
    void returnCredit() { if (credits < max_credits) credits++; }
};

/**
 * @brief 环形网络节点
 */
struct RingNode {
    int node_id;                                        ///< 节点ID
    
    // 物理连接
    RingNode* next_cw;                                  ///< 顺时针下一个节点
    RingNode* prev_cw;                                  ///< 顺时针前一个节点
    RingNode* next_ccw;                                 ///< 逆时针下一个节点  
    RingNode* prev_ccw;                                 ///< 逆时针前一个节点
    
    // 虚拟通道 (每个方向多个VC)
    std::vector<VirtualChannel> cw_vcs;                 ///< 顺时针虚拟通道
    std::vector<VirtualChannel> ccw_vcs;                ///< 逆时针虚拟通道
    std::vector<VirtualChannel> local_vcs;              ///< 本地注入/弹出通道
    
    // 输入输出缓冲区
    std::queue<RingMessage> injection_queue;           ///< 注入队列
    std::queue<RingMessage> ejection_queue;            ///< 弹出队列
    
    // 统计信息
    uint64_t messages_forwarded;                        ///< 转发消息数
    uint64_t messages_injected;                         ///< 注入消息数
    uint64_t messages_ejected;                          ///< 弹出消息数
    uint64_t total_latency_cycles;                      ///< 总延迟周期
    
    RingNode(int id = 0) : node_id(id), next_cw(nullptr), prev_cw(nullptr),
                          next_ccw(nullptr), prev_ccw(nullptr),
                          messages_forwarded(0), messages_injected(0), 
                          messages_ejected(0), total_latency_cycles(0) {}
                          
    void initializeVCs(int num_vcs_per_direction, uint32_t credits_per_vc);
    VirtualChannel* selectOutputVC(RouteDirection direction, int priority);
    bool canAcceptMessage(RouteDirection direction, int priority) const;
};

/**
 * @brief 优化的内部环形网络
 * 
 * 主要优化特性：
 * 1. 真正的双向环形拓扑
 * 2. 多虚拟通道支持，避免死锁
 * 3. 自适应路由算法
 * 4. 基于信用的流控制
 * 5. 优先级调度
 * 6. 零拷贝消息传递
 */
class OptimizedInternalRing {
public:
    /**
     * @brief 构造函数
     * @param num_nodes 环形网络节点数量
     * @param num_vcs 每个方向的虚拟通道数量
     * @param credits_per_vc 每个虚拟通道的信用数
     * @param output 日志输出对象
     */
    OptimizedInternalRing(int num_nodes, int num_vcs = 2, 
                         uint32_t credits_per_vc = 8, SST::Output* output = nullptr);
    
    /**
     * @brief 析构函数
     */
    ~OptimizedInternalRing();
    
    // ===== 主要接口 =====
    
    /**
     * @brief 发送消息到环形网络
     * @param src_node 源节点ID
     * @param dst_node 目标节点ID  
     * @param message 消息内容
     * @param priority 消息优先级 (0=最高)
     * @return 是否成功发送
     */
    bool sendMessage(int src_node, int dst_node, const RingMessage& message, int priority = 1);
    
    /**
     * @brief 从环形网络接收消息
     * @param node_id 节点ID
     * @param message 接收到的消息
     * @return 是否成功接收
     */
    bool receiveMessage(int node_id, RingMessage& message);
    
    /**
     * @brief 时钟周期更新
     * @param current_cycle 当前仿真周期
     */
    void tick(uint64_t current_cycle);
    
    /**
     * @brief 检查节点是否有待处理消息
     * @param node_id 节点ID
     * @return 是否有消息
     */
    bool hasTrafficForNode(int node_id) const;
    
    /**
     * @brief 获取网络中待处理消息总数
     * @return 消息总数
     */
    int getPendingMessageCount() const;
    
    // ===== 路由算法 =====
    
    /**
     * @brief 选择最优路由方向
     * @param src 源节点ID
     * @param dst 目标节点ID
     * @return 路由方向
     */
    RouteDirection selectRoute(int src, int dst) const;
    
    /**
     * @brief 计算两节点间的跳数
     * @param src 源节点ID
     * @param dst 目标节点ID
     * @param direction 路由方向
     * @return 跳数
     */
    int calculateHops(int src, int dst, RouteDirection direction) const;
    
    // ===== 流控制 =====
    
    /**
     * @brief 检查信用可用性
     * @param node_id 节点ID
     * @param direction 方向
     * @param vc_id 虚拟通道ID
     * @return 是否有可用信用
     */
    bool checkCredit(int node_id, RouteDirection direction, int vc_id) const;
    
    /**
     * @brief 更新信用
     * @param node_id 节点ID
     * @param direction 方向
     * @param vc_id 虚拟通道ID
     * @param increment 是否增加信用（false为减少）
     */
    void updateCredit(int node_id, RouteDirection direction, int vc_id, bool increment);
    
    // ===== 统计信息 =====
    
    /**
     * @brief 获取总路由消息数
     */
    uint64_t getTotalMessagesRouted() const { return total_messages_routed_; }
    
    /**
     * @brief 获取平均延迟
     */
    double getAverageLatency() const;
    
    /**
     * @brief 获取网络利用率
     */
    double getNetworkUtilization() const;
    
    /**
     * @brief 获取节点统计信息
     * @param node_id 节点ID
     */
    void getNodeStatistics(int node_id, uint64_t& injected, uint64_t& ejected, 
                          uint64_t& forwarded, double& avg_latency) const;
    
    /**
     * @brief 获取虚拟通道利用率
     * @param node_id 节点ID
     * @param direction 方向
     * @param vc_id 虚拟通道ID
     */
    double getVCUtilization(int node_id, RouteDirection direction, int vc_id) const;
    
    // ===== 调试和可视化 =====
    
    /**
     * @brief 打印网络状态
     */
    void printNetworkState() const;
    
    /**
     * @brief 检查网络拓扑完整性
     */
    bool verifyTopology() const;
    
    /**
     * @brief 检测死锁
     */
    bool detectDeadlock() const;

private:
    // ===== 配置参数 =====
    int num_nodes_;                                     ///< 节点数量
    int num_vcs_;                                       ///< 每方向虚拟通道数
    uint32_t credits_per_vc_;                           ///< 每VC信用数
    SST::Output* output_;                               ///< 日志输出
    
    // ===== 网络拓扑 =====
    std::vector<std::unique_ptr<RingNode>> nodes_;      ///< 网络节点数组
    
    // ===== 统计信息 =====
    std::atomic<uint64_t> total_messages_routed_{0};    ///< 总路由消息数
    std::atomic<uint64_t> total_latency_cycles_{0};     ///< 总延迟周期
    std::atomic<uint64_t> total_cycles_{0};             ///< 总仿真周期
    uint64_t last_stats_cycle_;                         ///< 上次统计周期
    
    // ===== 性能优化 =====
    std::vector<uint32_t> route_cache_;                 ///< 路由缓存
    mutable std::unordered_map<uint64_t, RouteDirection> route_lookup_cache_; ///< 路由查找缓存
    
    // ===== 内部方法 =====
    
    /**
     * @brief 初始化环形拓扑
     */
    void initializeTopology();
    
    /**
     * @brief 处理单个节点的路由
     * @param node_id 节点ID
     * @param current_cycle 当前周期
     */
    void processNodeRouting(int node_id, uint64_t current_cycle);
    
    /**
     * @brief 处理指定方向的虚拟通道
     * @param node 节点指针
     * @param direction 方向
     * @param current_cycle 当前周期
     */
    void processDirectionVCs(RingNode* node, RouteDirection direction, uint64_t current_cycle);
    
    /**
     * @brief 处理注入队列
     * @param node 节点指针
     * @param current_cycle 当前周期
     */
    void processInjectionQueue(RingNode* node, uint64_t current_cycle);
    
    /**
     * @brief 在指定方向转发消息
     * @param node RingNode指针
     * @param message 消息
     * @param direction 转发方向
     * @return 是否成功转发
     */
    bool forwardMessage(RingNode* node, const RingMessage& message, RouteDirection direction);
    
    /**
     * @brief VC仲裁器 - 选择下一个服务的VC
     * @param vcs 虚拟通道数组
     * @return 选中的VC索引，-1表示无可用VC
     */
    int vcArbitration(const std::vector<VirtualChannel>& vcs) const;
    
    /**
     * @brief 交换机仲裁器 - 处理多个VC竞争同一输出端口
     * @param node RingNode指针
     * @param direction 输出方向
     * @return 获胜的VC ID，-1表示无获胜者
     */
    int switchArbitration(RingNode* node, RouteDirection direction) const;
    
    /**
     * @brief 更新统计信息
     * @param current_cycle 当前周期
     */
    void updateStatistics(uint64_t current_cycle);
    
    /**
     * @brief 生成路由缓存键
     * @param src 源节点
     * @param dst 目标节点
     * @return 缓存键
     */
    uint64_t generateRouteCacheKey(int src, int dst) const {
        return (static_cast<uint64_t>(src) << 32) | static_cast<uint64_t>(dst);
    }
    
    /**
     * @brief 获取节点指针（带边界检查）
     * @param node_id 节点ID
     * @return 节点指针，nullptr表示无效ID
     */
    RingNode* getNode(int node_id) const {
        if (node_id >= 0 && node_id < num_nodes_) {
            return nodes_[node_id].get();
        }
        return nullptr;
    }
    
    /**
     * @brief 获取指定方向的虚拟通道数组
     * @param node 节点指针
     * @param direction 方向
     * @return 虚拟通道数组引用
     */
    std::vector<VirtualChannel>& getVCs(RingNode* node, RouteDirection direction);
    const std::vector<VirtualChannel>& getVCs(const RingNode* node, RouteDirection direction) const;
};

}} // namespace SST::SnnDL

#endif // _OPTIMIZED_INTERNAL_RING_H
