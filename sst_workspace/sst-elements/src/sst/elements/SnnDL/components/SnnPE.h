// -*- c++ -*-
//
// Copyright 2025 SST Contributors
//
// SnnPE.h: 单核脉冲神经网络处理单元头文件
//
// DEPRECATED/COMPAT:
//   本组件为旧架构的兼容实现，推荐使用：
//     MultiCorePE + SnnPESubComponent + SnnNIC
//   若需继续使用本组件，请将日志级别调高以减少输出干扰；
//   后续功能演进将优先在新架构中进行。
//

#ifndef _SNNPE_H
#define _SNNPE_H

#include <sst/core/component.h>
#include <sst/core/link.h>
#include <sst/core/output.h>
#include <sst/core/params.h>
#include <sst/core/event.h>
#include <sst/core/clock.h>
#include <sst/core/interfaces/simpleNetwork.h>
#include <sst/core/interfaces/stdMem.h>

#include <vector>
#include <string>
#include <cstdint>
#include <map>
#include <unordered_map>
#include <memory>

#include "events/SpikeEvent.h"
#include "SnnInterface.h"
#include "SnnNeuronModel.h"

namespace SST {
namespace SnnDL {

/**
 * @brief 挂起内存请求结构体
 * 
 * 存储等待内存响应的脉冲事件上下文
 */
struct PendingRequest {
    SpikeEvent* original_spike;  ///< 原始脉冲事件
    uint32_t request_time;       ///< 请求发起时间（可选）
    
    PendingRequest() : original_spike(nullptr), request_time(0) {}
    PendingRequest(SpikeEvent* spike) : original_spike(spike), request_time(0) {}
};

/**
 * @brief 神经元状态结构体
 * 
 * 存储每个神经元的动态状态信息
 */
struct NeuronState {
    float v_mem;                    ///< 当前膜电位
    uint32_t refractory_timer;      ///< 不应期计数器
    
    /** 构造函数，初始化为静息状态 */
    NeuronState(float v_rest = 0.0f) : v_mem(v_rest), refractory_timer(0) {}
};

/**
 * @brief 单核脉冲神经网络处理单元
 * 
 * 该组件实现了一个基于LIF(Leaky Integrate-and-Fire)模型的SNN处理单元。
 * 主要功能包括：
 * - 神经元状态管理（NSU）
 * - 突触权重存储（SWM，使用CSR格式）
 * - 脉冲处理（SPU）
 * - 事件驱动和时钟驱动的混合处理模式
 */
class SnnPE : public SST::Component {
public:
    // SST组件注册宏
    SST_ELI_REGISTER_COMPONENT(
        SnnPE,                                  // 类名
        "SnnDL",                               // 元素库名称  
        "SnnPE",                               // 组件名称
        SST_ELI_ELEMENT_VERSION(1, 0, 0),      // 版本号
        "单核脉冲神经网络处理单元",              // 描述
        COMPONENT_CATEGORY_PROCESSOR           // 类别
    )

    // 参数文档
    SST_ELI_DOCUMENT_PARAMS(
        {"clock",        "PE内部时钟频率", "1GHz"},
        {"num_neurons",  "此PE模拟的神经元总数", ""},
        {"v_thresh",     "触发脉冲的膜电位阈值", "1.0"},
        {"v_reset",      "脉冲发放后膜电位重置值", "0.0"},
        {"v_rest",       "静息膜电位", "0.0"},
        {"tau_mem",      "膜电位泄漏时间常数(ms)", "20.0"},
        {"t_ref",        "不应期时长(时钟周期)", "2"},
        {"base_addr",    "此PE权重矩阵在全局内存中的基地址", "0"},
        {"weights_per_neuron", "每个突触前神经元连接的权重数量(用于地址计算)", "0"},
        {"node_id",      "网络节点ID", "0"},
        {"verbose",      "日志详细级别", "0"},
        {"enable_test_traffic", "是否启用网络测试流量", "0"},
        {"test_target_node", "测试流量的目标节点ID", "0"},
        {"test_period", "测试流量发送周期(周期数)", "100"},
        {"test_spikes_per_burst", "每次周期性发送的测试脉冲数量", "4"},
        {"test_weight", "测试脉冲权重", "0.2"}
    )

    // SubComponent槽位文档 - 参考standardCPU的设计
    SST_ELI_DOCUMENT_SUBCOMPONENT_SLOTS(
        {"memory", "接口到内存层次结构", "SST::Interfaces::StandardMem"},
        {"network_interface", "SNN网络接口插槽，类似miranda.MemNIC", "SST::SnnDL::SnnInterface"},
        {"router", "网络路由器插槽，嵌入式路由功能", "SST::Interfaces::SimpleNetwork"}
    )

    // 端口文档 (兼容性，优先使用SubComponent接口)
    SST_ELI_DOCUMENT_PORTS(
        {"spike_input",  "接收输入脉冲事件的端口(传统模式)", {"SnnDL.SpikeEvent"}},
        {"spike_output", "发送输出脉冲事件的端口(传统模式)", {"SnnDL.SpikeEvent"}},
        {"mem_link",     "连接到内存层次结构的端口", {"memHierarchy.MemEventBase"}}
    )

    // 统计信息文档
    SST_ELI_DOCUMENT_STATISTICS(
        {"spikes_received", "接收到的脉冲总数", "spikes", 1},
        {"spikes_generated", "生成的脉冲总数", "spikes", 1},
        {"neurons_fired", "发放脉冲的神经元数量", "neurons", 1},
        {"total_synaptic_ops", "突触操作总数", "operations", 1}
    )

    /**
     * @brief 构造函数
     * @param id SST组件ID
     * @param params 配置参数
     */
    SnnPE(SST::ComponentId_t id, SST::Params& params);

    /**
     * @brief 析构函数
     */
    ~SnnPE();

    // SST组件生命周期方法
    void init(unsigned int phase) override;
    void setup() override;
    void finish() override;

private:
    // ===== 事件和时钟处理器 =====
    
    /**
     * @brief 时钟滴答处理器，处理周期性更新
     * @param current_cycle 当前仿真周期
     * @return false表示继续仿真
     */
    virtual bool clockTick(SST::Cycle_t current_cycle);
    
    /**
     * @brief 脉冲事件处理器（传统Link模式）
     * @param ev 接收到的脉冲事件
     */
    void handleSpikeEvent(SST::Event* ev);
    
    /**
     * @brief 脉冲事件处理器（SubComponent接口模式）
     * @param spike_event 接收到的脉冲事件
     */
    void handleInterfaceSpike(SpikeEvent* spike_event);

    /**
     * @brief 内存响应处理器（使用StandardMem接口）
     * @param req 接收到的内存请求响应
     */
    void handleMemResponse(SST::Interfaces::StandardMem::Request *req);

    // ===== 私有辅助方法 =====
    
    /**
     * @brief 从文件加载突触权重矩阵
     * @param file_path 权重文件路径
     * @return 是否加载成功
     */
    bool loadWeights(const std::string& file_path);
    
    /**
     * @brief 应用泄漏动态到指定神经元
     * @param neuron_idx 神经元索引
     */
    void applyLeak(uint32_t neuron_idx);
    
    /**
     * @brief 检查神经元是否发放脉冲并处理
     * @param neuron_idx 神经元索引
     */
    void checkAndFireSpike(uint32_t neuron_idx);

    /**
     * @brief 路由器接收处理器（分布式模式）
     * @param vn 虚拟网络ID
     * @return 是否成功处理
     */
    bool handleRouterRequest(int vn);

    /**
     * @brief 检查路由器发送空间
     * @param vn 虚拟网络ID  
     * @return 是否有可用空间
     */
    bool routerSpaceAvailable(int vn);

    /**
     * @brief 初始化分布式网络架构
     * @return 是否初始化成功
     */
    bool initDistributedNetwork();

    /**
     * @brief 将脉冲路由到目标节点
     * @param spike_event 脉冲事件
     * @param target_node 目标节点ID
     */
    void routeSpike(SpikeEvent* spike_event, uint32_t target_node);

    /**
     * @brief 处理本地神经元脉冲
     * @param spike_event 本地脉冲事件
     */
    void processLocalSpike(SpikeEvent* spike_event);

    // ===== 成员变量 =====
    
    // SST基础设施
    SST::Output* output;                    ///< 日志输出对象
    SST::Link* spike_input_link;            ///< 输入脉冲链接（传统模式）
    SST::Link* spike_output_link;           ///< 输出脉冲链接（传统模式）
    SST::Interfaces::StandardMem* memory_;  ///< 标准内存接口（新增）
    
    // SubComponent接口（分布式架构模式）
    SnnInterface* snn_interface;            ///< SNN网络接口，类似miranda.MemNIC
    SST::Interfaces::SimpleNetwork* router; ///< 嵌入式路由器，类似miranda.hr_router
    uint32_t node_id;                       ///< 网络节点ID
    bool use_interface_mode;                ///< 是否使用SubComponent接口模式
    bool use_embedded_router;               ///< 是否使用嵌入式路由器
    
    // 内存相关参数（新增）
    uint64_t base_addr;                     ///< 权重矩阵在全局内存中的基地址
    uint32_t weights_per_neuron;            ///< 每个突触前神经元连接的权重数量
    std::unordered_map<SST::Interfaces::StandardMem::Request::id_t, PendingRequest> pending_requests; ///< 挂起的内存请求（hash查找更快）
    
    // 仿真参数
    uint32_t num_neurons;                   ///< 神经元总数
    uint32_t neuron_id_start;               ///< 本核心神经元全局ID起始值
    std::string weights_file_path;          ///< 权重文件路径
    std::string binary_weights_file_path;   ///< 二进制权重文件路径
    float v_thresh;                         ///< 发放阈值
    float v_reset;                          ///< 重置电位
    float v_rest;                           ///< 静息电位
    float tau_mem;                          ///< 膜时间常数
    uint32_t t_ref;                         ///< 不应期时长
    float leak_factor;                      ///< 预计算的泄漏因子
    
    // 神经元状态单元（NSU）
    std::vector<NeuronState> neurons;       ///< 神经元状态数组
    // 神经动力学模型（内部策略，不改变外部接口）
    std::unique_ptr<INeuronModel> neuron_model_;
    float dt_ms_ = 1.0f;                    ///< 神经动力学时间步长（ms）
    
    // 突触权重存储器（SWM）- CSR格式
    std::vector<float> csr_weights;         ///< 突触权重值
    std::vector<uint32_t> csr_col_indices;  ///< 列（突触后神经元）索引
    std::vector<uint64_t> csr_row_ptr;      ///< 行指针数组
    
    // 统计计数器
    uint64_t spikes_received_count;         ///< 接收脉冲计数
    uint64_t spikes_generated_count;        ///< 生成脉冲计数
    uint64_t neurons_fired_count;           ///< 发放神经元计数
    uint64_t synaptic_ops_count;            ///< 突触操作计数
    
    // 统计对象
    Statistic<uint64_t>* stat_spikes_received;
    Statistic<uint64_t>* stat_spikes_generated;
    Statistic<uint64_t>* stat_neurons_fired;
    Statistic<uint64_t>* stat_synaptic_ops;

    // 测试流量配置
    bool enable_test_traffic;               ///< 是否启用网络测试流量
    uint32_t test_target_node;              ///< 目标节点
    uint32_t test_period;                   ///< 周期
    uint32_t test_spikes_per_burst;         ///< 每次发送脉冲数量
    float test_weight;                      ///< 脉冲权重
};

} // namespace SnnDL
} // namespace SST

#endif /* _SNNPE_H */
