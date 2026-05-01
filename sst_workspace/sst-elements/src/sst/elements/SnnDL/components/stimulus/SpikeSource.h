// -*- c++ -*-
//
// Copyright 2025 SST Contributors
//
// SpikeSource.h: 脉冲数据源组件头文件
//

#ifndef _SPIKESOURCE_H
#define _SPIKESOURCE_H

#include <sst/core/component.h>
#include <sst/core/link.h>
#include <sst/core/output.h>
#include <sst/core/params.h>
#include <sst/core/event.h>
#include <sst/core/clock.h>

#include <vector>
#include <string>
#include <queue>
#include <cstdint>

#include "events/SpikeEvent.h"

namespace SST {
namespace SnnDL {

/**
 * @brief 脉冲数据结构，用于存储从文件读取的脉冲事件
 */
struct SpikeData {
    uint32_t neuron_id;        ///< 源神经元ID（source）
    uint32_t dest_neuron_id;   ///< 目标神经元ID（destination）；若未指定则与源相同
    uint64_t timestamp;        ///< 时间戳（微秒）

    SpikeData(uint32_t src, uint64_t ts)
        : neuron_id(src), dest_neuron_id(src), timestamp(ts) {}
    SpikeData(uint32_t src, uint32_t dst, uint64_t ts)
        : neuron_id(src), dest_neuron_id(dst), timestamp(ts) {}

    // 用于优先队列的比较运算符（时间戳小的优先）
    bool operator>(const SpikeData& other) const {
        return timestamp > other.timestamp;
    }
};

/**
 * @brief 脉冲数据源组件
 * 
 * 该组件负责从神经形态数据集文件中读取脉冲数据，并在仿真过程中
 * 按照正确的时序向网络注入脉冲事件。支持多种数据格式：
 * - N-MNIST (AER格式)
 * - Spiking Heidelberg Digits (HDF5格式)
 * - 简单文本格式 (neuron_id, timestamp)
 */
class SpikeSource : public SST::Component {
public:
    // SST组件注册宏
    SST_ELI_REGISTER_COMPONENT(
        SpikeSource,                           // 类名
        "SnnDL",                              // 元素库名称
        "SpikeSource",                        // 组件名称
        SST_ELI_ELEMENT_VERSION(1, 0, 0),     // 版本号
        "脉冲神经网络数据源组件",              // 描述
        COMPONENT_CATEGORY_PROCESSOR          // 类别
    )

    // 参数文档
    SST_ELI_DOCUMENT_PARAMS(
        {"dataset_path",   "数据集文件路径", ""},
        {"dataset_format", "数据集格式 (TEXT|NMNIST_AER|SHD_HDF5)", "TEXT"},
        {"time_scale",     "时间缩放因子 (仿真时间单位到数据时间单位)", "1.0"},
        {"start_time_us",  "开始发送的延迟 (微秒)", "0"},
        {"neuron_offset",  "神经元ID偏移量", "0"},
        {"max_events",     "最大事件数量限制 (0=无限制)", "0"},
        {"verbose",        "日志详细级别", "0"},
        {"neurons_per_pe", "每个PE的神经元数(用于推断目标节点)", "0"},
        {"neurons_per_core", "每核神经元数(可选，辅助计算neurons_per_pe)", "0"},
        {"num_cores",      "每PE核心数(可选，辅助计算neurons_per_pe)", "0"},
        {"event_weight",   "注入事件权重（与 use_event_weight_fallback 配合）", "1.0"},
        {"segmented_release", "是否启用分段释放(严格8-slice) (0/1)", "0"},
        {"slices_per_superstep", "每个superstep分成的slice数量", "8"},
        {"slice_window_us", "每个slice的释放窗口时长(微秒)", "5"},
        {"slice_gap_us",    "slice之间的间隔(微秒)", "5"}
    )

    // 端口文档
    SST_ELI_DOCUMENT_PORTS(
        {"spike_output", "发送脉冲事件的输出端口", {"SnnDL.SpikeEvent"}}
    )

    // 统计信息文档
    SST_ELI_DOCUMENT_STATISTICS(
        {"events_loaded", "从文件加载的事件总数", "events", 1},
        {"events_sent", "发送的事件总数", "events", 1}
    )

    /**
     * @brief 构造函数
     * @param id SST组件ID
     * @param params 配置参数
     */
    SpikeSource(SST::ComponentId_t id, SST::Params& params);

    /**
     * @brief 析构函数
     */
    ~SpikeSource();

    // SST组件生命周期方法
    void init(unsigned int phase) override;
    void setup() override;
    void finish() override;

private:
    // ===== 时钟处理器 =====
    
    /**
     * @brief 时钟滴答处理器，检查并发送到期的脉冲事件
     * @param current_cycle 当前仿真周期
     * @return false表示继续仿真
     */
    virtual bool clockTick(SST::Cycle_t current_cycle);

    // ===== 私有辅助方法 =====
    
    /**
     * @brief 加载数据集文件
     * @return 是否加载成功
     */
    bool loadDataset();
    
    /**
     * @brief 加载文本格式数据集
     * @param file_path 文件路径
     * @return 是否加载成功
     */
    bool loadTextFormat(const std::string& file_path);
    
    /**
     * @brief 加载N-MNIST AER格式数据集
     * @param file_path 文件路径
     * @return 是否加载成功
     */
    bool loadNMNISTFormat(const std::string& file_path);
    
    /**
     * @brief 加载SHD HDF5格式数据集
     * @param file_path 文件路径
     * @return 是否加载成功
     */
    bool loadSHDFormat(const std::string& file_path);
    
    /**
     * @brief 将数据时间戳转换为仿真时间
     * @param data_timestamp 数据时间戳
     * @return 仿真时间戳
     */
    uint64_t convertToSimTime(uint64_t data_timestamp);

    // ===== 成员变量 =====
    
    // SST基础设施
    SST::Output* output;                    ///< 日志输出对象
    SST::Link* spike_output_link;           ///< 输出脉冲链接
    
    // 配置参数
    std::string dataset_path;               ///< 数据集文件路径
    std::string dataset_format;             ///< 数据集格式
    float time_scale;                       ///< 时间缩放因子
    uint32_t neuron_offset;                 ///< 神经元ID偏移
    uint32_t max_events;                    ///< 最大事件数限制
    uint32_t neurons_per_core;              ///< 每个核心的神经元数（可选）
    uint32_t num_cores;                     ///< 每个PE的核心数（可选）
    uint32_t neurons_per_pe;                ///< 每个PE的神经元数（用于计算目标节点）
    float event_weight = 1.0f;              ///< 事件权重（用于回退路径）
    uint64_t start_time_us_ = 0;            ///< 启动延迟（微秒）
    // 分段释放（严格8-slice）参数
    bool segmented_release_ = false;
    uint32_t slices_per_superstep_ = 8;
    uint64_t slice_window_cycles_ = 5;      ///< 1MHz时钟下按微秒转换
    uint64_t slice_gap_cycles_ = 5;         ///< 1MHz时钟下按微秒转换
    // 分段释放状态
    bool window_open_ = false;
    uint64_t slice_counter_ = 0;            ///< 当前slice内已走的cycles
    bool in_gap_ = false;                   ///< 当前是否处于slice间隙
    uint32_t current_slice_idx_ = 0;        ///< [0, slices_per_superstep_-1]
    
    // 脉冲数据存储
    std::priority_queue<SpikeData, std::vector<SpikeData>, std::greater<SpikeData>> spike_queue;
    uint64_t current_sim_time;              ///< 当前仿真时间（微秒）
    
    // 统计计数器
    uint64_t events_loaded_count;           ///< 加载事件计数
    uint64_t events_sent_count;             ///< 发送事件计数
    
    // 统计对象
    Statistic<uint64_t>* stat_events_loaded;
    Statistic<uint64_t>* stat_events_sent;
    
    // 状态标志
    bool data_loaded;                       ///< 数据是否已加载
    bool finished_sending;                  ///< 是否完成发送
};

} // namespace SnnDL
} // namespace SST

#endif /* _SPIKESOURCE_H */
