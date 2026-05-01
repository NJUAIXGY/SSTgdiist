#ifndef SST_ELEMENTS_SNNDL_ISNNCOMPUTECORE_H
#define SST_ELEMENTS_SNNDL_ISNNCOMPUTECORE_H

#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace SST {
class Output;
class Params;
} // namespace SST

namespace SST { namespace SnnDL {

class SpikeEvent;
class IWeightReader;
class INeuronModel;

struct ComputeCoreContext {
    // Optional learning writeback hook:
    // If provided, compute core may call this at learning window boundaries
    // to request weight updates. Return true on success (gradients can be cleared).
    using WritebackFn = std::function<bool(const std::unordered_map<uint64_t, float>& grads,
                                          float learning_rate,
                                          float weight_decay)>;
    uint32_t core_id = 0;
    uint32_t node_id = 0;
    uint32_t num_neurons = 0;
    uint64_t global_neuron_base = 0;
    uint32_t neurons_per_pe_cfg = 0;
    SST::Output* log = nullptr;
    IWeightReader* weight_reader = nullptr;
    WritebackFn writeback_fn;
};

struct FireEvent {
    uint32_t neuron_idx = 0;
    float v_before = 0.0f;
    float v_after = 0.0f;
};

struct SynapticEvent {
    uint32_t post_local = 0;
    uint32_t pre_global = 0;
    float weight = 0.0f;
};

struct NeuronStateSnapshot {
    float v_mem = 0.0f;
    uint32_t refractory = 0;
    uint64_t last_spike = 0;
};

// 学习/误差累加接口：可选，默认空实现；若 compute core 支持学习，可实现以下接口
struct LearningEvent {
    uint32_t pre_global = 0;
    uint32_t post_local = 0;
    float error = 0.0f;
    float v_mem = 0.0f; // 可用于 surrogate grad
};

// 可插拔核心能力描述：控制层可据此选择是否启用特性（默认保守开启）
struct ComputeCoreCapabilities {
    bool needs_weight_cache = true;      // 是否依赖控制层权重缓存/读发起
    bool supports_gating = true;         // 是否兼容事件门控（门控缓存由控制层维护）
    bool requires_window_scatter = false;// 是否要求 scatter 窗口语义才能发放
    bool supports_learning = false;      // 是否实现学习/写回路径
    bool uses_synaptic_events = false;   // 是否优先使用 onSynapticEvent 而非 applySynapticDelta
};

class ISnnComputeCore {
public:
    virtual ~ISnnComputeCore() = default;

    // 能力协商：默认返回保守配置，具体实现可覆盖
    virtual ComputeCoreCapabilities getCapabilities() const {
        return ComputeCoreCapabilities{};
    }

    virtual void configure(const ComputeCoreContext& ctx, const SST::Params& params) = 0;
    virtual void onInit(unsigned int phase) = 0;
    virtual void onSetup() = 0;
    virtual void onFinish() = 0;
    virtual void onClockTick(uint64_t now_cycle) = 0;
    virtual void onStageBeginGather(uint32_t seq) = 0;
    virtual void onStageBeginApply(uint32_t seq) = 0;
    virtual void onStageEndApply(uint32_t seq) = 0;
    virtual void onStageBeginScatter(uint32_t seq) = 0;
    virtual void onStageEndScatter(uint32_t seq, uint64_t spikes_emitted_hint) = 0;
    virtual void onSpikeDelivered(SpikeEvent* spike) = 0;
    virtual bool hasWork() const = 0;
    virtual double getUtilization() const = 0;
    virtual void getStatistics(std::map<std::string, uint64_t>& out) const = 0;
    virtual void resetMembraneState(float v_rest) = 0;
    // 统一的“周期收敛”接口：推进动力学并在内部判定发放，输出事件待 drain
    virtual void endCycle(uint64_t now_cycle) = 0;
    // 仅对候选集合进行发放判定（用于 window/scatter：避免全量扫描）
    virtual void endCycleCandidates(uint64_t now_cycle, const std::vector<uint32_t>& candidates) = 0;
    // 取出当前尚未消费的输出事件（控制层统一路由）
    virtual void drainOutputs(std::vector<FireEvent>& out, bool clear = true) = 0;
    // 窗口累加语义下，控制层在发起权重读/累加前需要复用核心侧门控（例如不应期过滤）。
    // 返回 true 表示核心接受该突触输入；false 表示应丢弃（不记录边、不发起权重读、不累加）。
    virtual bool shouldAcceptSynapticInput(uint32_t post_local, uint64_t now_cycle) const = 0;
    virtual void applySynapticDelta(uint32_t post_local, float dv) = 0;
    // 便捷接口：允许核心内部处理带有 pre_global 的完整突触事件（默认实现仅调用 applySynapticDelta）
    virtual void onSynapticEvent(const SynapticEvent& ev) = 0;
    virtual void clearFiredWindow() = 0;
    virtual void getFiredEvents(std::vector<FireEvent>& out, bool clear = true) = 0;
    virtual bool readNeuronState(uint32_t idx, NeuronStateSnapshot& out) const = 0;
    virtual void writeNeuronState(uint32_t idx, const NeuronStateSnapshot& st) = 0;
    // 可选：学习事件钩子（默认可忽略）
    virtual void onLearningEvent(const LearningEvent& ev) = 0;
    virtual void updateNeuronStates() = 0;
    virtual bool fire(uint32_t idx, uint64_t now_cycles, INeuronModel* model,
                      float& v_before, float& v_after) = 0;
    // 窗口门控（供控制层同步镜像）：core 维护 fired_this_window_，控制层可复用
    virtual bool wasFiredThisWindow(uint32_t idx) const = 0;
    virtual void markFiredThisWindow(uint32_t idx) = 0;
};

// 工厂：按名称创建 compute core（默认返回 DefaultSnnComputeCore）
// 约定：name 可取 "default" / "snn"；未知名称返回 nullptr。
std::unique_ptr<ISnnComputeCore> createComputeCoreByName(const std::string& name);

}} // namespace SST::SnnDL

#endif // SST_ELEMENTS_SNNDL_ISNNCOMPUTECORE_H
