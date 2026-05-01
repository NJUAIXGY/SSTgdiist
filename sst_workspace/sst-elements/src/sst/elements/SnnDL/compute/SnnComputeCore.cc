#include "SnnComputeCore.h"
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <limits>
#include <sstream>

#include "SnnDLStringUtil.h"

namespace SST { namespace SnnDL {

namespace {
static inline uint64_t satAddU64Local(uint64_t a, uint64_t b) {
    if (std::numeric_limits<uint64_t>::max() - a < b) return std::numeric_limits<uint64_t>::max();
    return a + b;
}
} // namespace

std::unique_ptr<ISnnComputeCore> createComputeCoreByName(const std::string& name) {
    if (name.empty() || name == "default" || name == "snn") {
        return std::make_unique<DefaultSnnComputeCore>();
    }
    return nullptr;
}

ComputeCoreCapabilities DefaultSnnComputeCore::getCapabilities() const {
    ComputeCoreCapabilities caps;
    // Phase5.4：权重/缓存语义从 ISnnComputeCore 迁出；默认 core 不再要求控制层实现 cache 接口。
    // 权重读取通过 ComputeCoreContext.weight_reader 注入（由 synapse/weights 提供）。
    caps.needs_weight_cache = false;
    caps.supports_gating = true;
    caps.requires_window_scatter = false;
    caps.supports_learning = (learning_core_ != nullptr);
    caps.uses_synaptic_events = false;
    return caps;
}

void DefaultSnnComputeCore::configure(const ComputeCoreContext& ctx, const SST::Params& params) {
    ctx_ = ctx;
    output_ = ctx.log;
    weight_reader_ = ctx.weight_reader;
    core_engine_ = SnnCoreEngine();

    // 基础参数
    num_neurons_ = ctx.num_neurons;
    global_neuron_base_ = ctx.global_neuron_base;
    neurons_per_pe_cfg_ = ctx.neurons_per_pe_cfg ? ctx.neurons_per_pe_cfg : ctx.num_neurons;
    v_thresh_ = params.find<float>("v_thresh", 1.0f);
    v_reset_ = params.find<float>("v_reset", 0.0f);
    v_rest_ = params.find<float>("v_rest", 0.0f);
    tau_mem_ = params.find<float>("tau_mem", 20.0f);
    t_ref_ = params.find<uint32_t>("t_ref", 2);
    dt_ms_ = 1.0f;

    // 可选神经模型（与 SnnPE 行为保持一致）
    {
        std::string model_name = params.find<std::string>("neuron_model", "LIF");
        NeuronModelType model_type = parseNeuronModel(model_name);
        neuron_model_ = createNeuronModel(model_type);
        if (neuron_model_) {
            ModelConfig mcfg = buildModelConfigFromParams(params);
            dt_ms_ = mcfg.dt_ms;
            neuron_model_->init(num_neurons_, mcfg, params);
            if (output_) {
                output_->verbose(CALL_INFO, 1, 0,
                    "[core-model] core=%u model=%s dt=%.3fms\n",
                    ctx_.core_id, model_name.c_str(), (double)dt_ms_);
            }
        }
    }

    use_soa_state_ = params.find<int>("use_soa_neuron_state", 0) != 0;
    use_aosoa_state_ = params.find<int>("use_aosoa_neuron_state", 0) != 0;
    // 兼容旧默认：未显式传入时（或传0）先暂存为0，待解析 BCSR 后再回填
    aosoa_block_rows_ = params.find<uint32_t>("aosoa_block_rows", 0);
    if (use_aosoa_state_) use_soa_state_ = true;
    state_sram_enable_ = params.find<int>("state_sram_enable", 0) != 0;
    {
        VirtualSramLayoutConfig lcfg{};
        lcfg.state_vmem_base = params.find<uint64_t>("state_sram_vmem_base", 0x300000000ull);
        lcfg.state_refrac_base = params.find<uint64_t>("state_sram_refrac_base", 0x400000000ull);
        lcfg.state_last_spike_base = params.find<uint64_t>("state_sram_last_spike_base", 0x500000000ull);
        state_sram_layout_.configure(lcfg);

        BankedSramConfig scfg{};
        scfg.enable = state_sram_enable_;
        scfg.name = "core_state_sram";
        scfg.capacity_bytes = params.find<uint64_t>("state_sram_capacity_bytes", 0);
        scfg.banks = params.find<uint32_t>("state_sram_banks", 16);
        scfg.ports_per_bank = params.find<uint32_t>("state_sram_ports_per_bank", 1);
        scfg.bank_interleave_bytes = params.find<uint64_t>("state_sram_bank_interleave_bytes", 4);
        scfg.t_read_cycles = params.find<uint32_t>("state_sram_t_read_cycles", 1);
        scfg.t_write_cycles = params.find<uint32_t>("state_sram_t_write_cycles", 1);
        scfg.sample_log2 = params.find<uint32_t>("state_sram_sample_log2", 0);
        state_sram_model_.configure(scfg);
    }

    apply_acc_enable_ = params.find<int>("apply_acc_enable", 0) != 0;
    gas_window_mode_ = params.find<int>("gas_window_mode", 0) != 0;
    window_read_debug_ = params.find<int>("window_read_debug", 0) != 0;
    window_read_budget_ = params.find<uint32_t>("window_read_budget", 1024);
    max_outstanding_requests_ = params.find<uint32_t>("max_outstanding_requests", 16);
    diag_fire_log_ = params.find<int>("diag_fire_log", 0) != 0;
    line_size_bytes_ = params.find<uint32_t>("line_size_bytes", 64);
    weights_cols_ = params.find<uint32_t>("weights_cols", 0);
    if (weights_cols_ == 0) weights_cols_ = num_neurons_;
    use_post_row_pre_col_ = params.find<std::string>("index_mode", "pre_row_post_col") == "post_row_pre_col";

    init_default_weight_ = params.find<float>("init_default_weight", 0.5f);
    readresp_zero_fallback_ = params.find<int>("readresp_zero_fallback", 0) != 0;
    memory_warmup_cycles_ = params.find<uint64_t>("memory_warmup_cycles", 1000);
    loader_barrier_cycles_ = params.find<uint64_t>("loader_barrier_cycles", 0);

    // 验证参数
    verify_weights_ = params.find<int>("verify_weights", 0) != 0;
    verify_against_file_ = params.find<int>("verify_against_file", 0) != 0;
    verify_cluster_enable_ = params.find<int>("verify_cluster_enable", 0) != 0;
    verify_log_each_sample_ = params.find<int>("verify_log_each_sample", 0) != 0;
    expected_weight_value_ = params.find<float>("expected_weight_value", 0.0f);
    verify_epsilon_ = params.find<float>("verify_epsilon", 1e-4f);
    weight_verify_samples_ = params.find<uint32_t>("weight_verify_samples", 16);
    verify_file_template_ = params.find<std::string>("verify_file_template", "");

    // AoSoA 默认块行宽：若未显式指定，允许复用 bcsr_block_rows 作为提示以保持兼容。
    if (aosoa_block_rows_ == 0) {
        uint32_t hint = params.find<uint32_t>("bcsr_block_rows", 0);
        aosoa_block_rows_ = (hint > 0) ? hint : 16;
    }

    // 学习核心初始化（独立 LearningCore，便于后续替换算法）
    if (!learning_core_) {
        learning_core_ = std::make_unique<DefaultLearningCore>();
    }
    if (learning_core_) {
        learning_core_->configure(ctx_.core_id, ctx_.node_id,
                                  num_neurons_, global_neuron_base_,
                                  weights_cols_, use_post_row_pre_col_,
                                  v_thresh_, output_, params,
                                  ctx.writeback_fn);
    }

    // 初始化状态
    initCoreEngineState_();
    initVerifyFile_();
}

void DefaultSnnComputeCore::initCoreEngineState_() {
    SnnCoreConfig cfg;
    cfg.num_neurons = num_neurons_;
    cfg.v_thresh = v_thresh_;
    cfg.v_reset = v_reset_;
    cfg.v_rest = v_rest_;
    cfg.tau_mem = tau_mem_;
    cfg.t_ref = t_ref_;
    cfg.use_soa_state = use_soa_state_;
    cfg.use_aosoa_state = use_aosoa_state_;
    cfg.aosoa_block_rows = aosoa_block_rows_;
    core_engine_.configure(cfg);

    if (use_soa_state_) {
        soa_v_mem_.assign(num_neurons_, v_rest_);
        soa_refrac_.assign(num_neurons_, 0);
        soa_last_spike_.assign(num_neurons_, 0);
        neuron_states_.clear();
        core_engine_.bindState(nullptr, &soa_v_mem_, &soa_refrac_, &soa_last_spike_);
    } else {
        neuron_states_.assign(num_neurons_, SnnCoreNeuronState(v_rest_));
        soa_v_mem_.clear();
        soa_refrac_.clear();
        soa_last_spike_.clear();
        core_engine_.bindState(&neuron_states_, nullptr, nullptr, nullptr);
    }
    fired_this_window_.assign(num_neurons_, 0);
    pending_dv_.assign(num_neurons_, 0.0f);
    pending_dv_touched_.assign(num_neurons_, 0);
    pending_dv_list_.clear();
    pending_dv_list_.reserve(std::max<uint32_t>(8u, num_neurons_ / 10u));
    if (state_sram_enable_) {
        uint64_t resident_bytes = 0;
        if (use_soa_state_) {
            resident_bytes = static_cast<uint64_t>(num_neurons_) *
                             static_cast<uint64_t>(sizeof(float) + sizeof(uint32_t) + sizeof(uint64_t));
        } else {
            resident_bytes = static_cast<uint64_t>(num_neurons_) * static_cast<uint64_t>(sizeof(SnnCoreNeuronState));
        }
        state_sram_model_.noteResidentBytes(resident_bytes);
    }
}

void DefaultSnnComputeCore::initVerifyFile_() {
    verify_file_loaded_ = false;
    verify_file_buf_.clear();
    if (!(verify_against_file_ && !verify_file_template_.empty())) return;
    std::string path = verify_file_template_;
    replaceAllIndexed(path, "{pe:02d}", ctx_.node_id, 2);
    replaceAll(path, "{pe}", std::to_string(ctx_.node_id));
    std::ifstream fin(path, std::ios::binary);
    if (!fin.good()) return;
    fin.seekg(0, std::ios::end);
    std::streamsize bytes = fin.tellg();
    fin.seekg(0, std::ios::beg);
    if (bytes > 0 && (bytes % sizeof(float) == 0)) {
        size_t count = static_cast<size_t>(bytes / sizeof(float));
        verify_file_buf_.resize(count);
        fin.read(reinterpret_cast<char*>(verify_file_buf_.data()), bytes);
        verify_file_loaded_ = true;
    }
}

void DefaultSnnComputeCore::onInit(unsigned int) {}
void DefaultSnnComputeCore::onSetup() {}
void DefaultSnnComputeCore::onFinish() {
    if (state_sram_enable_) {
        state_sram_model_.onClockTick(state_sram_current_cycle_ + 1);
    }
}

void DefaultSnnComputeCore::onClockTick(uint64_t now_cycle) {
    state_sram_current_cycle_ = now_cycle;
    if (state_sram_enable_) {
        state_sram_model_.onClockTick(now_cycle);
        state_sram_stall_budget_ = satAddU64Local(
            state_sram_stall_budget_,
            state_sram_model_.consumeLastCyclePredictedExtraCycles());
        // GAS window mode: endCycle() is not invoked every tick. To avoid dropping or silently
        // ignoring the SRAM stall budget, consume it during idle gaps (post EndScatter) so the
        // global-step drain policy can observe "real" stall time before declaring PE_DONE.
        if (gas_window_mode_ && gas_stage_ == GasStage::Idle && state_sram_stall_budget_ > 0) {
            --state_sram_stall_budget_;
            state_sram_stall_cycles_total_ = satAddU64Local(state_sram_stall_cycles_total_, 1ull);
        }
    }
    total_cycles_++;
    if (hasWork()) active_cycles_++;
    performWeightVerificationTick_(now_cycle);
    if (learning_core_) learning_core_->onClockTick(now_cycle);
}

void DefaultSnnComputeCore::endCycle(uint64_t now_cycle) {
    if (state_sram_enable_ && !gas_window_mode_ && state_sram_stall_budget_ > 0) {
        --state_sram_stall_budget_;
        state_sram_stall_cycles_total_ = satAddU64Local(state_sram_stall_cycles_total_, 1ull);
        return;
    }
    // 诊断：观察 pending dv 列表与膜电位上限（限制次数）
    if (output_ && window_read_debug_ && output_->getVerboseLevel() >= 2) {
        static uint32_t diag_end_logs = 0;
        const uint32_t kLogLimit = 16;
        if (diag_end_logs < kLogLimit) {
            float v_max = -1e30f;
            uint32_t v_max_idx = 0;
            for (uint32_t i = 0; i < num_neurons_; ++i) {
                float v = core_engine_.getMem(i);
                if (v > v_max) { v_max = v; v_max_idx = i; }
            }
            output_->verbose(CALL_INFO, 2, 0,
                "[diag-endcycle] core=%u pending=%zu stage=%d apply_acc=%d gas_window=%d v_max=%.6f idx=%u v_thresh=%.6f\n",
                ctx_.core_id, pending_dv_list_.size(),
                static_cast<int>(gas_stage_), apply_acc_enable_ ? 1 : 0,
                gas_window_mode_ ? 1 : 0, v_max, v_max_idx, v_thresh_);
            ++diag_end_logs;
        }
    }

    // 推进动力学：先泄漏/不应期推进，再整合 Scatter 累计 ΔV，最后判定发放。
    updateNeuronStates();
    applyPendingDeltas_();
    // 按当前窗口/阶段门控判定发放，复用 fire() 以保持旧语义
    for (uint32_t i = 0; i < num_neurons_; ++i) {
        float v_before = 0.0f, v_after = 0.0f;
        fire(i, now_cycle, neuron_model_.get(), v_before, v_after);
    }
}

void DefaultSnnComputeCore::endCycleCandidates(uint64_t now_cycle,
                                               const std::vector<uint32_t>& candidates) {
    if (state_sram_enable_ && !gas_window_mode_ && state_sram_stall_budget_ > 0) {
        --state_sram_stall_budget_;
        state_sram_stall_cycles_total_ = satAddU64Local(state_sram_stall_cycles_total_, 1ull);
        return;
    }
    // 与 endCycle() 保持一致的“先推进动力学，再判定发放”顺序。
    // candidates 允许控制层在 window/scatter 场景下仅检查触达的 post 集合。
    updateNeuronStates();
    applyPendingDeltas_();

    if (candidates.empty()) return;

    std::vector<uint32_t> uniq = candidates;
    std::sort(uniq.begin(), uniq.end());
    uniq.erase(std::unique(uniq.begin(), uniq.end()), uniq.end());

    for (uint32_t idx : uniq) {
        if (idx >= num_neurons_) continue;
        float v_before = 0.0f, v_after = 0.0f;
        fire(idx, now_cycle, neuron_model_.get(), v_before, v_after);
    }
}

void DefaultSnnComputeCore::drainOutputs(std::vector<FireEvent>& out, bool clear) {
    out.insert(out.end(), fired_events_window_.begin(), fired_events_window_.end());
    if (clear) fired_events_window_.clear();
}

bool DefaultSnnComputeCore::shouldAcceptSynapticInput(uint32_t post_local, uint64_t now_cycle) const {
    (void)now_cycle;
    if (post_local >= num_neurons_) return false;
    // 与 onSynapticEvent() 的门控口径保持一致：不应期期间丢弃突触输入。
    return core_engine_.getRefrac(post_local) == 0;
}

void DefaultSnnComputeCore::applySynapticDelta(uint32_t post_local, float dv) {
    synaptic_accesses_count_++;
    if (apply_acc_enable_ && gas_window_mode_) {
        if (post_local >= num_neurons_) return;
        if (pending_dv_.size() != num_neurons_) {
            pending_dv_.assign(num_neurons_, 0.0f);
            pending_dv_touched_.assign(num_neurons_, 0);
            pending_dv_list_.clear();
            pending_dv_list_.reserve(std::max<uint32_t>(8u, num_neurons_ / 10u));
        }
        pending_dv_[post_local] += dv;
        if (post_local < pending_dv_touched_.size() && pending_dv_touched_[post_local] == 0) {
            pending_dv_touched_[post_local] = 1;
            pending_dv_list_.push_back(post_local);
        }
        // 诊断：确认 pending 列表被填充（限制次数，避免日志膨胀）
        if (output_ && window_read_debug_ && output_->getVerboseLevel() >= 2 && dv != 0.0f) {
            static uint32_t diag_delta_logs = 0;
            const uint32_t kLogLimit = 16;
            if (diag_delta_logs < kLogLimit) {
                output_->verbose(CALL_INFO, 2, 0,
                    "[diag-dv] core=%u post=%u dv=%.6f pending_sz=%zu num_neurons=%u\n",
                    ctx_.core_id, post_local, dv, pending_dv_list_.size(), num_neurons_);
                ++diag_delta_logs;
            }
        }
        return;
    }
    core_engine_.addMem(post_local, dv);
}

void DefaultSnnComputeCore::noteStateSramRead_(uint64_t addr, uint64_t bytes) {
    if (!state_sram_enable_) return;
    state_sram_model_.noteRead(state_sram_current_cycle_, addr, bytes);
}

void DefaultSnnComputeCore::noteStateSramWrite_(uint64_t addr, uint64_t bytes) {
    if (!state_sram_enable_) return;
    state_sram_model_.noteWrite(state_sram_current_cycle_, addr, bytes);
}

void DefaultSnnComputeCore::applyPendingDeltas_() {
    if (pending_dv_list_.empty()) return;
    for (uint32_t post_local : pending_dv_list_) {
        if (post_local >= num_neurons_) continue;
        if (state_sram_enable_) {
            noteStateSramRead_(state_sram_layout_.stateVmemAddr(post_local), sizeof(float));
            noteStateSramWrite_(state_sram_layout_.stateVmemAddr(post_local), sizeof(float));
        }
        const float dv = (post_local < pending_dv_.size()) ? pending_dv_[post_local] : 0.0f;
        if (dv != 0.0f) {
            core_engine_.addMem(post_local, dv);
        }
        if (post_local < pending_dv_.size()) pending_dv_[post_local] = 0.0f;
        if (post_local < pending_dv_touched_.size()) pending_dv_touched_[post_local] = 0;
    }
    pending_dv_list_.clear();
}

void DefaultSnnComputeCore::resetPendingDeltas_() {
    if (pending_dv_list_.empty()) return;
    for (uint32_t post_local : pending_dv_list_) {
        if (post_local < pending_dv_.size()) pending_dv_[post_local] = 0.0f;
        if (post_local < pending_dv_touched_.size()) pending_dv_touched_[post_local] = 0;
    }
    pending_dv_list_.clear();
}

void DefaultSnnComputeCore::onSynapticEvent(const SynapticEvent& ev) {
    if (ev.post_local >= num_neurons_) return;
    // 保持旧 SnnPESubComponent 语义：目标神经元处于不应期时，忽略本次突触输入。
    // 注意：Scatter 阶段的窗口累加使用 applySynapticDelta()，不受此门控影响。
    if (core_engine_.getRefrac(ev.post_local) > 0) return;
    if (neuron_model_ && neuron_model_->useAccumulator()) {
        // 累加到模型内部 I_syn，膜电位在 tickIdx 中更新
        synaptic_accesses_count_++;
        neuron_model_->accumulateISyn(ev.post_local, ev.weight);
        // accumulator 模式下不做在线梯度（保持旧行为：apply_acc_enable_ 路径不会进入此处）
        return;
    }
    // 默认实现：直接累加到膜电位
    applySynapticDelta(ev.post_local, ev.weight);

    if (learning_core_ && learning_core_->enabled()) {
        LearningSynapticEvent lev;
        lev.pre_global = ev.pre_global;
        lev.post_local = ev.post_local;
        lev.v_after = core_engine_.getMem(ev.post_local);
        learning_core_->onSynapticEvent(lev);
    }
}

void DefaultSnnComputeCore::updateNeuronStates() {
    cycles_update_neuron_count_ += num_neurons_;
    if (state_sram_enable_ && num_neurons_ > 0) {
        for (uint32_t i = 0; i < num_neurons_; ++i) {
            noteStateSramRead_(state_sram_layout_.stateVmemAddr(i), sizeof(float));
            noteStateSramRead_(state_sram_layout_.stateRefracAddr(i), sizeof(uint32_t));
            noteStateSramWrite_(state_sram_layout_.stateVmemAddr(i), sizeof(float));
            noteStateSramWrite_(state_sram_layout_.stateRefracAddr(i), sizeof(uint32_t));
        }
    }
    if (neuron_model_) {
        if (use_soa_state_) {
            for (uint32_t i = 0; i < num_neurons_; ++i) {
                neuron_model_->tickIdx(i, soa_v_mem_[i], soa_refrac_[i]);
            }
        } else {
            for (uint32_t i = 0; i < num_neurons_; ++i) {
                neuron_model_->tickIdx(i, neuron_states_[i].v_mem, neuron_states_[i].refractory_timer);
            }
        }
        return;
    }
    core_engine_.updateNeuronStates();
}

void DefaultSnnComputeCore::clearFiredWindow() {
    if (fired_this_window_.empty()) return;
    std::fill(fired_this_window_.begin(), fired_this_window_.end(), 0);
}

void DefaultSnnComputeCore::getFiredEvents(std::vector<FireEvent>& out, bool clear) {
    out.insert(out.end(), fired_events_window_.begin(), fired_events_window_.end());
    if (clear) fired_events_window_.clear();
}

bool DefaultSnnComputeCore::wasFiredThisWindow(uint32_t idx) const {
    if (idx >= fired_this_window_.size()) return false;
    return fired_this_window_[idx] != 0;
}

void DefaultSnnComputeCore::markFiredThisWindow(uint32_t idx) {
    if (idx >= fired_this_window_.size()) return;
    fired_this_window_[idx] = 1;
}

void DefaultSnnComputeCore::onLearningEvent(const LearningEvent& ev) {
    (void)ev; // 默认实现留空；学习核心可在此处理误差信号
}

bool DefaultSnnComputeCore::fire(uint32_t idx, uint64_t now_cycles, INeuronModel* model,
                                 float& v_before, float& v_after) {
    if (apply_acc_enable_ && gas_window_mode_) {
        if (gas_stage_ != GasStage::Scatter) return false;
        if (idx < fired_this_window_.size() && fired_this_window_[idx]) return false;
    }

    float state_vmem_before = 0.0f;
    uint32_t state_refrac_before = 0;
    uint64_t state_last_spike_before = 0;
    if (state_sram_enable_ && idx < num_neurons_) {
        noteStateSramRead_(state_sram_layout_.stateVmemAddr(idx), sizeof(float));
        noteStateSramRead_(state_sram_layout_.stateRefracAddr(idx), sizeof(uint32_t));
        noteStateSramRead_(state_sram_layout_.stateLastSpikeAddr(idx), sizeof(uint64_t));
        state_vmem_before = core_engine_.getMem(idx);
        state_refrac_before = core_engine_.getRefrac(idx);
        state_last_spike_before = core_engine_.getLastSpike(idx);
    }

    INeuronModel* use_model = model ? model : neuron_model_.get();
    bool fired = core_engine_.fire(idx, now_cycles, use_model, v_before, v_after);

    if (state_sram_enable_ && idx < num_neurons_) {
        const float state_vmem_after = core_engine_.getMem(idx);
        const uint32_t state_refrac_after = core_engine_.getRefrac(idx);
        const uint64_t state_last_spike_after = core_engine_.getLastSpike(idx);
        if (fired || state_vmem_after != state_vmem_before) {
            noteStateSramWrite_(state_sram_layout_.stateVmemAddr(idx), sizeof(float));
        }
        if (fired || state_refrac_after != state_refrac_before) {
            noteStateSramWrite_(state_sram_layout_.stateRefracAddr(idx), sizeof(uint32_t));
        }
        if (fired || state_last_spike_after != state_last_spike_before) {
            noteStateSramWrite_(state_sram_layout_.stateLastSpikeAddr(idx), sizeof(uint64_t));
        }
    }

    if (fired && apply_acc_enable_ && gas_window_mode_ && idx < fired_this_window_.size()) {
        fired_this_window_[idx] = 1;
    }
    if (fired) {
        neurons_fired_count_++;
        spikes_generated_count_++;
        fired_events_window_.push_back(FireEvent{idx, v_before, v_after});
        if (learning_core_ && learning_core_->enabled()) {
            learning_core_->onNeuronFired(idx, now_cycles, v_before);
        }
    }
    return fired;
}

bool DefaultSnnComputeCore::readNeuronState(uint32_t idx, NeuronStateSnapshot& out) const {
    if (idx >= num_neurons_) return false;
    out.v_mem = core_engine_.getMem(idx);
    out.refractory = core_engine_.getRefrac(idx);
    out.last_spike = core_engine_.getLastSpike(idx);
    return true;
}

void DefaultSnnComputeCore::writeNeuronState(uint32_t idx, const NeuronStateSnapshot& st) {
    if (idx >= num_neurons_) return;
    core_engine_.setMem(idx, st.v_mem);
    core_engine_.setRefrac(idx, st.refractory);
    core_engine_.setLastSpike(idx, st.last_spike);
}

bool DefaultSnnComputeCore::requestWeight(uint32_t pre, uint32_t post,
                       const std::function<void(float)>& cb) {
    if (!weight_reader_) return false;
    weight_reader_->requestDense(pre, post, [this, cb](float w){
        if (cb) cb(w);
    });
    return true;
}

bool DefaultSnnComputeCore::requestWeightBCSR(uint32_t pre, uint32_t post,
                           const std::function<void(float)>& cb) {
    if (!weight_reader_) return false;
    weight_reader_->requestBCSR(pre, post, [this, cb](float w){
        if (cb) cb(w);
    });
    return true;
}

bool DefaultSnnComputeCore::weightCacheTryGet(uint64_t key, float& out) const {
    if (!weight_reader_) return false;
    bool hit = weight_reader_->tryCache(key, out);
    if (hit) {
        const_cast<DefaultSnnComputeCore*>(this)->weight_cache_hits_++;
    } else {
        const_cast<DefaultSnnComputeCore*>(this)->weight_cache_misses_++;
    }
    return hit;
}

void DefaultSnnComputeCore::weightCacheStore(uint64_t key, float v) {
    if (!weight_reader_) return;
    weight_reader_->putCache(key, v);
}

bool DefaultSnnComputeCore::resolveWeightKey(uint32_t, uint32_t,
                          uint32_t& req_pre, uint32_t& req_post,
                          uint64_t& cache_key) const {
    // 默认实现交由上层 WeightAccessor；此处返回 false 表示沿用旧路径
    req_pre = req_post = 0;
    cache_key = 0;
    return false;
}

void DefaultSnnComputeCore::onStageBeginGather(uint32_t seq) {
    gas_stage_ = GasStage::Gather;
    curr_stage_seq_ = seq;
    std::fill(fired_this_window_.begin(), fired_this_window_.end(), 0);
    window_spikes_all_ = 0;
    fire_gate_active_ = apply_acc_enable_ && gas_window_mode_;
    resetPendingDeltas_();
}

void DefaultSnnComputeCore::onStageBeginApply(uint32_t seq) {
    gas_stage_ = GasStage::Apply;
    curr_stage_seq_ = seq;
}

void DefaultSnnComputeCore::onStageEndApply(uint32_t) {
    // stats already collected elsewhere; placeholder
}

void DefaultSnnComputeCore::onStageBeginScatter(uint32_t seq) {
    gas_stage_ = GasStage::Scatter;
    curr_stage_seq_ = seq;
    fire_gate_active_ = apply_acc_enable_ && gas_window_mode_;
    if (fired_this_window_.size() != num_neurons_) {
        fired_this_window_.assign(num_neurons_, 0);
    } else {
        std::fill(fired_this_window_.begin(), fired_this_window_.end(), 0);
    }
    fired_events_window_.clear();
    spikes_generated_base_ = 0; // caller可按需设置
    resetPendingDeltas_();
}

void DefaultSnnComputeCore::onStageEndScatter(uint32_t, uint64_t) {
    gas_stage_ = GasStage::Idle;
    fire_gate_active_ = false;
    fired_events_window_.clear();
    resetPendingDeltas_();
}

void DefaultSnnComputeCore::onSpikeDelivered(SpikeEvent* spike) {
    // 控制层已维护 window-read 集合；默认核心无需处理 spike 到达事件
    (void)spike;
}

bool DefaultSnnComputeCore::hasWork() const {
    if (gas_window_mode_) return state_sram_stall_budget_ > 0;
    if (state_sram_stall_budget_ > 0) return true;
    if (use_soa_state_) {
        return std::any_of(soa_v_mem_.begin(), soa_v_mem_.end(), [](float v){ return v > 0.1f; });
    }
    return std::any_of(neuron_states_.begin(), neuron_states_.end(),
                      [](const SnnCoreNeuronState& state) { return state.v_mem > 0.1f; });
}

double DefaultSnnComputeCore::getUtilization() const {
    if (total_cycles_ == 0) return 0.0;
    return static_cast<double>(active_cycles_) / static_cast<double>(total_cycles_);
}

void DefaultSnnComputeCore::getStatistics(std::map<std::string, uint64_t>& out) const {
    out["core_spikes_generated"] = spikes_generated_count_;
    out["core_neurons_fired"] = neurons_fired_count_;
    out["core_cycles_update_neuron"] = cycles_update_neuron_count_;
    out["core_synaptic_accesses"] = synaptic_accesses_count_;
    out["core_total_cycles"] = total_cycles_;
    out["core_active_cycles"] = active_cycles_;
    out["core_weight_cache_hits"] = weight_cache_hits_;
    out["core_weight_cache_misses"] = weight_cache_misses_;
    out["core_pending_reqs_peak"] = pending_reqs_peak_;
    // 权重验证诊断（可选）：仅用于收尾/统计显示，不改变行为
    out["core_verify_enabled"] = verify_weights_ ? 1ULL : 0ULL;
    out["core_verify_completed"] = static_cast<uint64_t>(verify_completed_);
    out["core_verify_mismatch_count"] = verify_mismatch_count_;
    const auto& sram_stats = state_sram_model_.stats();
    out["core_state_sram_reads_total"] = sram_stats.reads_total;
    out["core_state_sram_writes_total"] = sram_stats.writes_total;
    out["core_state_sram_bytes_read_total"] = sram_stats.bytes_read_total;
    out["core_state_sram_bytes_write_total"] = sram_stats.bytes_write_total;
    out["core_state_sram_bank_conflict_ticks_total"] = sram_stats.bank_conflict_ticks_total;
    out["core_state_sram_predicted_extra_cycles_total"] = sram_stats.predicted_extra_cycles_total;
    out["core_state_sram_resident_bytes_peak"] = sram_stats.resident_bytes_peak;
    out["core_state_sram_bank_peak_accesses_per_tick"] = sram_stats.bank_peak_accesses_per_tick;
    out["core_state_sram_energy_read_pj_total"] = static_cast<uint64_t>(sram_stats.energy_read_pj_total);
    out["core_state_sram_energy_write_pj_total"] = static_cast<uint64_t>(sram_stats.energy_write_pj_total);
    out["core_state_sram_stall_cycles_total"] = state_sram_stall_cycles_total_;
    if (learning_core_) {
        learning_core_->getStatistics(out);
    }
    if (diag_fire_log_ && output_) {
        output_->verbose(CALL_INFO, 1, 0,
            "[diag-core-fire] node=%u core=%u fired=%" PRIu64 " spikes=%" PRIu64 " window_events=%zu\n",
            ctx_.node_id, ctx_.core_id,
            neurons_fired_count_, spikes_generated_count_,
            static_cast<size_t>(fired_events_window_.size()));
    }
}

void DefaultSnnComputeCore::resetMembraneState(float v_rest_value) {
    core_engine_.resetMembrane(v_rest_value);
    if (!fired_this_window_.empty()) {
        std::fill(fired_this_window_.begin(), fired_this_window_.end(), 0);
    }
    resetPendingDeltas_();
}

void DefaultSnnComputeCore::performWeightVerificationTick_(uint64_t now_cycle) {
    if (!(verify_weights_ && now_cycle >= memory_warmup_cycles_ &&
          (loader_barrier_cycles_ == 0 || now_cycle >= loader_barrier_cycles_))) {
        return;
    }
    if (!verify_started_) {
        verify_started_ = true;
        if (output_) output_->verbose(CALL_INFO, 3, 0, "🎯 核心%d权重验证启动: cycle=%" PRIu64 "\n", ctx_.core_id, now_cycle);
    }
    if (verify_completed_ >= weight_verify_samples_) return;
    if (verify_requested_ - verify_completed_ >= max_outstanding_requests_) return;

    uint32_t sample_idx = verify_requested_;
    uint32_t row;
    uint32_t col;
    if (verify_cluster_enable_) {
        uint32_t fpl = std::max<uint32_t>(1, line_size_bytes_ / (uint32_t)sizeof(float));
        row = 0;
        col = (sample_idx % fpl);
    } else {
        row = (sample_idx * 13) % num_neurons_;
        col = use_post_row_pre_col_ ? ((sample_idx * 7) % std::max<uint32_t>(1, weights_cols_))
                                     : ((sample_idx * 7) % num_neurons_);
    }
    uint32_t arg0 = use_post_row_pre_col_ ? col : row;
    uint32_t arg1 = use_post_row_pre_col_ ? row : col;
    if (!weight_reader_) return;
    weight_reader_->requestDense(arg0, arg1, [this, row, col](float w){
        verify_completed_++;
        verify_sum_ += static_cast<double>(w);
        bool mismatch = false;
        if (verify_against_file_ && verify_file_loaded_) {
            uint64_t idx = static_cast<uint64_t>(row) * static_cast<uint64_t>(weights_cols_) + static_cast<uint64_t>(col);
            float expected = 0.0f;
            if (idx < verify_file_buf_.size()) expected = verify_file_buf_[idx];
            mismatch = (std::fabs(w - expected) > verify_epsilon_);
        } else {
            mismatch = (std::fabs(w - expected_weight_value_) > verify_epsilon_);
        }
        if (mismatch) verify_mismatch_count_++;
    });
    verify_requested_++;
}

} } // namespace SST::SnnDL
