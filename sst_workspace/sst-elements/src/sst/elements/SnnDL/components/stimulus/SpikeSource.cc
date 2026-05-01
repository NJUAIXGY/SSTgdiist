// -*- c++ -*-
//
// Copyright 2025 SST Contributors
//
// SpikeSource.cc: 脉冲数据源组件实现文件
//

#include <sst/core/sst_config.h>
#include "SpikeSource.h"

#include <fstream>
#include <sstream>
#include <iostream>
#include <algorithm>

#include "SpikeSourceConfig.h"

using namespace SST;
using namespace SST::SnnDL;

// ===== 构造函数 =====
SpikeSource::SpikeSource(ComponentId_t id, Params& params) : Component(id) {
    const SpikeSourceConfig cfg = parseSpikeSourceConfig(params);

    // 初始化输出对象
    output = new Output("SpikeSource[@p:@l]: ", cfg.verbose, 0, Output::STDOUT);
    
    output->verbose(CALL_INFO, 1, 0, "初始化SpikeSource组件 (ID: %" PRIu64 ")\n", id);
    
    // 读取配置参数
    dataset_path = cfg.dataset_path;
    if (dataset_path.empty()) {
        output->fatal(CALL_INFO, -1, "错误: dataset_path参数是必需的\n");
    }
    
    dataset_format = cfg.dataset_format;
    time_scale = cfg.time_scale;
    start_time_us_ = cfg.start_time_us;
    neuron_offset = cfg.neuron_offset;
    max_events = cfg.max_events;
    
    // 可选的神经元映射参数（用于推断目标节点）
    neurons_per_core = cfg.neurons_per_core;
    num_cores = cfg.num_cores;
    neurons_per_pe = cfg.neurons_per_pe;
    
    event_weight = cfg.event_weight;
    segmented_release_ = cfg.segmented_release;
    slices_per_superstep_ = cfg.slices_per_superstep;
    uint64_t slice_window_us = cfg.slice_window_us;
    uint64_t slice_gap_us    = cfg.slice_gap_us;
    slice_window_cycles_ = slice_window_us; // 1MHz -> 1us per cycle
    slice_gap_cycles_    = slice_gap_us;

    output->verbose(CALL_INFO, 2, 0, 
        "数据集参数: path=%s, format=%s, time_scale=%.3f, offset=%u, max_events=%u, event_weight=%.3f, start_us=%" PRIu64 ", seg=%d, slices=%u, win_us=%" PRIu64 ", gap_us=%" PRIu64 "\n",
        dataset_path.c_str(), dataset_format.c_str(), time_scale, neuron_offset, max_events, event_weight, start_time_us_, segmented_release_?1:0, slices_per_superstep_, slice_window_us, slice_gap_us);
    
    // 配置输出链接
    spike_output_link = configureLink("spike_output");
    if (!spike_output_link) {
        output->fatal(CALL_INFO, -1, "错误: 无法配置spike_output链接\n");
    }
    
    output->verbose(CALL_INFO, 2, 0, "配置了输出链接\n");
    
    // 注册主组件，防止多线程下无事件时立即结束
    registerAsPrimaryComponent();
    primaryComponentDoNotEndSim();

    // 注册时钟处理器（使用较高频率以确保精确的事件时序）
    registerClock("1MHz", new Clock::Handler2<SpikeSource,&SpikeSource::clockTick>(this));
    output->verbose(CALL_INFO, 2, 0, "注册了时钟处理器，频率: 1MHz\n");
    
    // 初始化状态变量
    current_sim_time = 0;
    data_loaded = false;
    finished_sending = false;
    
    // 初始化统计计数器
    events_loaded_count = 0;
    events_sent_count = 0;
    
    // 注册统计对象
    stat_events_loaded = registerStatistic<uint64_t>("events_loaded");
    stat_events_sent = registerStatistic<uint64_t>("events_sent");
    
    output->verbose(CALL_INFO, 1, 0, "SpikeSource组件构造完成\n");
}

// ===== 析构函数 =====
SpikeSource::~SpikeSource() {
    if (output) {
        delete output;
    }
}

// ===== 生命周期方法 =====
void SpikeSource::init(unsigned int phase) {
    output->verbose(CALL_INFO, 2, 0, "进入init阶段 %u\n", phase);
}

void SpikeSource::setup() {
    output->verbose(CALL_INFO, 1, 0, "进入setup阶段\n");
    
    // 加载数据集
    if (loadDataset()) {
        data_loaded = true;
        output->verbose(CALL_INFO, 1, 0, "数据集加载成功，共%zu个事件\n", spike_queue.size());
    } else {
        output->fatal(CALL_INFO, -1, "数据集加载失败\n");
    }
}

void SpikeSource::finish() {
    output->verbose(CALL_INFO, 1, 0, "进入finish阶段\n");
    
    // 注意：当仿真由 SST 引擎 stop-at 结束时，在 finish() 中调用 primaryComponentOKToEndSim()
    // 可能导致 Exit 事件在收尾阶段被调度，从而触发引擎侧退出阶段双重释放/崩溃（见 MultiCorePE 同类规避）。
    // SpikeSource 作为数据源不应在 finish() 里触发 OKToEndSim（此时仿真已在收尾流程中）。

    // 输出最终统计信息
    // 注意：避免使用 Output::output() 造成默认刷屏；统一走 verbose 门控
    output->verbose(CALL_INFO, 1, 0, "=== SpikeSource最终统计 ===\n");
    output->verbose(CALL_INFO, 1, 0, "加载事件数: %" PRIu64 "\n", events_loaded_count);
    output->verbose(CALL_INFO, 1, 0, "发送事件数: %" PRIu64 "\n", events_sent_count);
    
    // 更新统计对象
    stat_events_loaded->addData(events_loaded_count);
    stat_events_sent->addData(events_sent_count);
}

// ===== 时钟处理器 =====
bool SpikeSource::clockTick(Cycle_t current_cycle) {
    if (!data_loaded || finished_sending) {
        return false;
    }
    
    // 更新当前仿真时间（假设1MHz时钟，每个周期1微秒）
    current_sim_time = current_cycle;
    
    // 若启用分段释放，按窗口控制；否则按时间戳直接释放
    if (segmented_release_) {
        // 尚未到开始时间，直接返回
        if (current_sim_time < start_time_us_) return false;
        // 初始化窗口状态
        if (slice_counter_ == 0 && !window_open_ && !in_gap_) {
            window_open_ = true; in_gap_ = false; current_slice_idx_ = 0;
        }
        // 每个tick推进窗口/间隙计数
        slice_counter_++;
        if (window_open_) {
            // 仅在窗口内释放到期事件
            while (!spike_queue.empty() && spike_queue.top().timestamp <= current_sim_time) {
                const SpikeData& spike_data = spike_queue.top();
                uint32_t src = spike_data.neuron_id;
                uint32_t dst = spike_data.dest_neuron_id;
                SpikeEvent* spike_event = new SpikeEvent(src, spike_data.timestamp);
                spike_event->setDestinationNeuron(dst);
                spike_event->setWeight(event_weight);
                if (neurons_per_pe > 0) {
                    uint32_t dest_node = dst / neurons_per_pe;
                    spike_event->setDestinationNode(dest_node);
                }
                spike_output_link->send(spike_event);
                events_sent_count++;
                output->verbose(CALL_INFO, 1, 0, "🚀[SpikeSource] 发送脉冲: 源%u -> 目的%u (dest_node=%u), 时间%" PRIu64 "\n",
                               src, dst, (neurons_per_pe > 0 ? dst / neurons_per_pe : 0), spike_data.timestamp);
                spike_queue.pop();
            }
            if (slice_counter_ >= slice_window_cycles_) {
                // 关闭窗口，进入间隙
                window_open_ = false; in_gap_ = true; slice_counter_ = 0;
            }
        } else if (in_gap_) {
            if (slice_counter_ >= slice_gap_cycles_) {
                // 切到下一个slice窗口
                in_gap_ = false; window_open_ = true; slice_counter_ = 0; current_slice_idx_ = (current_slice_idx_ + 1) % slices_per_superstep_;
            }
        }
    } else {
        // 发送所有到期的脉冲事件（原行为）
        while (!spike_queue.empty() && spike_queue.top().timestamp <= current_sim_time) {
            const SpikeData& spike_data = spike_queue.top();
            uint32_t src = spike_data.neuron_id;
            uint32_t dst = spike_data.dest_neuron_id;
            SpikeEvent* spike_event = new SpikeEvent(src, spike_data.timestamp);
            spike_event->setDestinationNeuron(dst);
            spike_event->setWeight(event_weight);
            if (neurons_per_pe > 0) {
                uint32_t dest_node = dst / neurons_per_pe;
                spike_event->setDestinationNode(dest_node);
            }
            spike_output_link->send(spike_event);
            events_sent_count++;
            output->verbose(CALL_INFO, 1, 0, "🚀[SpikeSource] 发送脉冲: 源%u -> 目的%u (dest_node=%u), 时间%" PRIu64 "\n",
                           src, dst, (neurons_per_pe > 0 ? dst / neurons_per_pe : 0), spike_data.timestamp);
            spike_queue.pop();
        }
    }
    
    // 检查是否完成发送
    if (spike_queue.empty()) {
        finished_sending = true;
        output->verbose(CALL_INFO, 1, 0, "所有脉冲事件已发送完毕\n");
    }
    
    return false;  // 继续仿真
}

// ===== 私有辅助方法 =====
bool SpikeSource::loadDataset() {
    output->verbose(CALL_INFO, 1, 0, "开始加载数据集: %s (格式: %s)\n", 
                   dataset_path.c_str(), dataset_format.c_str());
    
    if (dataset_format == "TEXT") {
        return loadTextFormat(dataset_path);
    } else if (dataset_format == "NMNIST_AER") {
        return loadNMNISTFormat(dataset_path);
    } else if (dataset_format == "SHD_HDF5") {
        return loadSHDFormat(dataset_path);
    } else {
        output->verbose(CALL_INFO, 1, 0, "不支持的数据集格式: %s\n", dataset_format.c_str());
        return false;
    }
}

bool SpikeSource::loadTextFormat(const std::string& file_path) {
    std::ifstream file(file_path);
    if (!file.is_open()) {
        output->verbose(CALL_INFO, 1, 0, "无法打开文件: %s\n", file_path.c_str());
        return false;
    }
    
    std::string line;
    uint32_t line_count = 0;
    uint32_t events_count = 0;
    
    while (std::getline(file, line) && (max_events == 0 || events_count < max_events)) {
        line_count++;
        if (line.empty() || line[0] == '#') continue;  // 跳过空行和注释

        std::istringstream iss(line);
        // 支持两种格式：
        //  - 2列: neuron_id timestamp
        //  - 3列: src_neuron_id dest_neuron_id timestamp
        uint32_t a = 0, b = 0; uint64_t ts = 0;
        if (!(iss >> a)) { continue; }
        if (!(iss >> b)) { continue; }
        if (!(iss >> ts)) {
            // 仅两列
            uint32_t neuron_id = a;
            uint64_t timestamp = static_cast<uint64_t>(b);
            uint32_t adjusted_src = neuron_id + neuron_offset;
            uint64_t adjusted_ts = convertToSimTime(timestamp);
            spike_queue.push(SpikeData(adjusted_src, adjusted_ts));
        } else {
            // 三列
            uint32_t src = a;
            uint32_t dst = b;
            uint32_t adjusted_src = src + neuron_offset;
            uint32_t adjusted_dst = dst + neuron_offset;
            uint64_t adjusted_ts = convertToSimTime(ts);
            spike_queue.push(SpikeData(adjusted_src, adjusted_dst, adjusted_ts));
        }
        events_count++;
        events_loaded_count++;
    }
    
    file.close();
    
    output->verbose(CALL_INFO, 1, 0, "TEXT格式加载完成: %u个事件\n", events_count);
    return true;
}

bool SpikeSource::loadNMNISTFormat(const std::string& file_path) {
    // N-MNIST AER格式的实现
    // 这里提供一个简化的实现框架，实际需要根据具体的二进制格式来解析
    
    output->verbose(CALL_INFO, 1, 0, "N-MNIST AER格式暂未完全实现\n");
    output->verbose(CALL_INFO, 1, 0, "建议使用TEXT格式或实现完整的AER解析器\n");
    
    // 简化实现：假设文件已转换为文本格式 (x, y, timestamp, polarity)
    std::ifstream file(file_path);
    if (!file.is_open()) {
        return false;
    }
    
    std::string line;
    uint32_t events_count = 0;
    
    while (std::getline(file, line) && (max_events == 0 || events_count < max_events)) {
        if (line.empty() || line[0] == '#') continue;
        
        std::istringstream iss(line);
        uint32_t x, y, polarity;
        uint64_t timestamp;
        
        if (!(iss >> x >> y >> timestamp >> polarity)) {
            continue;
        }
        
        // 将(x,y)坐标转换为神经元ID (假设28x28图像)
        uint32_t neuron_id = y * 28 + x + neuron_offset;
        uint64_t adjusted_timestamp = convertToSimTime(timestamp);
        
        spike_queue.push(SpikeData(neuron_id, adjusted_timestamp));
        events_count++;
        events_loaded_count++;
    }
    
    file.close();
    
    output->verbose(CALL_INFO, 1, 0, "N-MNIST格式加载完成: %u个事件\n", events_count);
    return true;
}

bool SpikeSource::loadSHDFormat(const std::string& file_path) {
    // SHD HDF5格式的实现
    // 需要链接HDF5库，这里提供一个占位实现
    
    output->verbose(CALL_INFO, 1, 0, "SHD HDF5格式需要HDF5库支持\n");
    output->verbose(CALL_INFO, 1, 0, "请安装HDF5开发库并实现相应的解析代码\n");
    
    // 占位实现：返回false表示未实现
    return false;
}

uint64_t SpikeSource::convertToSimTime(uint64_t data_timestamp) {
    // 应用时间缩放因子
    return static_cast<uint64_t>(data_timestamp * time_scale);
}
