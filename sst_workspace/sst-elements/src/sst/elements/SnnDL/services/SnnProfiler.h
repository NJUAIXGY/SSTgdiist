// -*- c++ -*-
//
// Copyright 2025 SST Contributors
//
// SnnProfiler.h: 轻量级高精度性能分析工具
//
// 功能：
// - Cycle级精度计时（基于RDTSC）
// - 分层profiling（组件级 → 函数级 → 代码块级）
// - RAII自动计时（ProfileZone）
// - 最小化测量开销（<1% overhead）
// - 支持条件编译（生产环境完全删除）
//

#ifndef _SNNPROFILER_H
#define _SNNPROFILER_H

#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>
#include <algorithm>
#include <fstream>
#include <iomanip>

namespace SST {
namespace SnnDL {

// ============================================================================
// 条件编译开关：生产环境完全删除profiling代码
// ============================================================================
#ifdef SNNDL_ENABLE_PROFILING

// ============================================================================
// RDTSC cycle计时器（x86/x64）
// ============================================================================
class CycleTimer {
public:
    // 读取CPU cycle counter（序列化指令，防止乱序执行）
    static inline uint64_t rdtsc() {
#if defined(__x86_64__) || defined(__i386__)
        uint32_t lo, hi;
        __asm__ __volatile__ (
            "lfence\n\t"           // 内存栅栏（防止读取被重排）
            "rdtsc\n\t"            // 读取时间戳计数器
            : "=a"(lo), "=d"(hi)
        );
        return ((uint64_t)hi << 32) | lo;
#elif defined(__aarch64__)
        // ARM64: 使用虚拟计数器
        uint64_t val;
        __asm__ __volatile__("mrs %0, cntvct_el0" : "=r"(val));
        return val;
#else
        // 其他架构：回退到零（禁用profiling）
        return 0;
#endif
    }

    // 估算CPU频率（GHz）
    static double estimate_cpu_freq_ghz() {
        // 简化版本：假设3.0 GHz（可通过/proc/cpuinfo读取）
        // 更精确的实现可以用chrono测量1秒内的cycle数
        return 3.0;
    }
};

// ============================================================================
// ProfileZone: RAII自动计时器（在作用域结束时自动记录耗时）
// ============================================================================
class ProfileZone {
public:
    ProfileZone(const char* zone_name, class Profiler* profiler);
    ~ProfileZone();

private:
    const char* zone_name_;
    class Profiler* profiler_;
    uint64_t start_cycles_;
};

// ============================================================================
// Profiler: 性能分析器（单例或per-component）
// ============================================================================
class Profiler {
public:
    // 统计项
    struct ZoneStats {
        uint64_t total_cycles = 0;      // 总cycle数
        uint64_t call_count = 0;        // 调用次数
        uint64_t min_cycles = UINT64_MAX;
        uint64_t max_cycles = 0;
        std::string parent_zone;        // 父zone（用于层次结构）

        double avg_cycles() const {
            return call_count > 0 ? (double)total_cycles / call_count : 0.0;
        }

        double total_ms(double cpu_freq_ghz) const {
            return total_cycles / (cpu_freq_ghz * 1e6);  // cycles → ms
        }
    };

    Profiler(const std::string& component_name)
        : component_name_(component_name), current_zone_(nullptr) {}

    // 开始计时zone
    void begin_zone(const char* zone_name, uint64_t start_cycles) {
        zones_[zone_name].call_count++;
        // 记录父zone（用于层次结构）
        if (current_zone_) {
            zones_[zone_name].parent_zone = current_zone_;
        }
        current_zone_ = zone_name;
        zone_stack_.push_back({zone_name, start_cycles});
    }

    // 结束计时zone
    void end_zone(const char* zone_name, uint64_t end_cycles) {
        if (zone_stack_.empty()) return;

        auto& frame = zone_stack_.back();
        if (frame.zone_name != zone_name) {
            // 警告：zone嵌套不匹配
            return;
        }

        uint64_t elapsed = end_cycles - frame.start_cycles;
        auto& stats = zones_[zone_name];
        stats.total_cycles += elapsed;
        stats.min_cycles = std::min(stats.min_cycles, elapsed);
        stats.max_cycles = std::max(stats.max_cycles, elapsed);

        zone_stack_.pop_back();
        // 恢复父zone
        current_zone_ = zone_stack_.empty() ? nullptr : zone_stack_.back().zone_name;
    }

    // 生成性能报告
    void generate_report(std::ostream& out, double cpu_freq_ghz = 3.0) const {
        out << "\n";
        out << "================================================================================\n";
        out << "  Performance Profile Report: " << component_name_ << "\n";
        out << "  CPU Frequency: " << std::fixed << std::setprecision(2) << cpu_freq_ghz << " GHz\n";
        out << "================================================================================\n\n";

        // 计算总耗时
        uint64_t total_cycles = 0;
        for (const auto& kv : zones_) {
            if (kv.second.parent_zone.empty()) {  // 仅统计顶层zone
                total_cycles += kv.second.total_cycles;
            }
        }

        // 按耗时降序排序
        std::vector<std::pair<std::string, ZoneStats>> sorted_zones(zones_.begin(), zones_.end());
        std::sort(sorted_zones.begin(), sorted_zones.end(),
                  [](const auto& a, const auto& b) {
                      return a.second.total_cycles > b.second.total_cycles;
                  });

        // 打印表格
        out << std::left;
        out << std::setw(40) << "Zone Name"
            << std::setw(12) << "Calls"
            << std::setw(15) << "Total (ms)"
            << std::setw(12) << "Avg (us)"
            << std::setw(12) << "Min (us)"
            << std::setw(12) << "Max (us)"
            << std::setw(10) << "% Total"
            << "\n";
        out << std::string(110, '-') << "\n";

        for (const auto& kv : sorted_zones) {
            const std::string& zone_name = kv.first;
            const ZoneStats& stats = kv.second;

            double total_ms = stats.total_ms(cpu_freq_ghz);
            double avg_us = stats.avg_cycles() / (cpu_freq_ghz * 1e3);
            double min_us = stats.min_cycles / (cpu_freq_ghz * 1e3);
            double max_us = stats.max_cycles / (cpu_freq_ghz * 1e3);
            double percent = total_cycles > 0 ? 100.0 * stats.total_cycles / total_cycles : 0.0;

            // 缩进显示层次结构
            std::string display_name = zone_name;
            if (!stats.parent_zone.empty()) {
                display_name = "  └─ " + display_name;
            }

            out << std::setw(40) << display_name
                << std::setw(12) << stats.call_count
                << std::setw(15) << std::fixed << std::setprecision(3) << total_ms
                << std::setw(12) << std::fixed << std::setprecision(2) << avg_us
                << std::setw(12) << std::fixed << std::setprecision(2) << min_us
                << std::setw(12) << std::fixed << std::setprecision(2) << max_us
                << std::setw(10) << std::fixed << std::setprecision(1) << percent
                << "\n";
        }

        out << std::string(110, '-') << "\n";
        double total_ms = total_cycles / (cpu_freq_ghz * 1e6);
        out << "Total profiled time: " << std::fixed << std::setprecision(3) << total_ms << " ms\n";
        out << "================================================================================\n\n";
    }

    // 导出CSV（用于可视化分析）
    void export_csv(const std::string& filename, double cpu_freq_ghz = 3.0) const {
        std::ofstream f(filename);
        if (!f.good()) return;

        // CSV表头
        f << "component,zone_name,parent_zone,call_count,total_cycles,total_ms,avg_cycles,avg_us,min_us,max_us\n";

        for (const auto& kv : zones_) {
            const std::string& zone_name = kv.first;
            const ZoneStats& stats = kv.second;

            double total_ms = stats.total_ms(cpu_freq_ghz);
            double avg_us = stats.avg_cycles() / (cpu_freq_ghz * 1e3);
            double min_us = stats.min_cycles / (cpu_freq_ghz * 1e3);
            double max_us = stats.max_cycles / (cpu_freq_ghz * 1e3);

            f << component_name_ << ","
              << zone_name << ","
              << (stats.parent_zone.empty() ? "ROOT" : stats.parent_zone) << ","
              << stats.call_count << ","
              << stats.total_cycles << ","
              << std::fixed << std::setprecision(6) << total_ms << ","
              << std::fixed << std::setprecision(2) << stats.avg_cycles() << ","
              << std::fixed << std::setprecision(3) << avg_us << ","
              << std::fixed << std::setprecision(3) << min_us << ","
              << std::fixed << std::setprecision(3) << max_us << "\n";
        }
    }

    // 重置统计
    void reset() {
        zones_.clear();
        zone_stack_.clear();
        current_zone_ = nullptr;
    }

private:
    std::string component_name_;
    std::unordered_map<std::string, ZoneStats> zones_;

    // Zone栈（用于嵌套profiling）
    struct StackFrame {
        const char* zone_name;
        uint64_t start_cycles;
    };
    std::vector<StackFrame> zone_stack_;
    const char* current_zone_;  // 当前zone名称
};

// ============================================================================
// ProfileZone实现（内联）
// ============================================================================
inline ProfileZone::ProfileZone(const char* zone_name, Profiler* profiler)
    : zone_name_(zone_name), profiler_(profiler), start_cycles_(CycleTimer::rdtsc()) {
    if (profiler_) {
        profiler_->begin_zone(zone_name_, start_cycles_);
    }
}

inline ProfileZone::~ProfileZone() {
    if (profiler_) {
        uint64_t end_cycles = CycleTimer::rdtsc();
        profiler_->end_zone(zone_name_, end_cycles);
    }
}

// ============================================================================
// 便捷宏（自动命名zone）
// ============================================================================
#define SNNDL_PROFILE_FUNCTION(profiler) \
    SST::SnnDL::ProfileZone _profile_zone_##__LINE__(__FUNCTION__, profiler)

#define SNNDL_PROFILE_ZONE(profiler, zone_name) \
    SST::SnnDL::ProfileZone _profile_zone_##__LINE__(zone_name, profiler)

#else  // !SNNDL_ENABLE_PROFILING

// ============================================================================
// 生产环境：空实现（零开销）
// ============================================================================
class CycleTimer {
public:
    static inline uint64_t rdtsc() { return 0; }
    static double estimate_cpu_freq_ghz() { return 0.0; }
};

class ProfileZone {
public:
    ProfileZone(const char*, class Profiler*) {}
};

class Profiler {
public:
    struct ZoneStats {};
    Profiler(const std::string&) {}
    void begin_zone(const char*, uint64_t) {}
    void end_zone(const char*, uint64_t) {}
    void generate_report(std::ostream&, double = 0.0) const {}
    void export_csv(const std::string&, double = 0.0) const {}
    void reset() {}
};

#define SNNDL_PROFILE_FUNCTION(profiler) do {} while(0)
#define SNNDL_PROFILE_ZONE(profiler, zone_name) do {} while(0)

#endif  // SNNDL_ENABLE_PROFILING

} // namespace SnnDL
} // namespace SST

#endif // _SNNPROFILER_H
