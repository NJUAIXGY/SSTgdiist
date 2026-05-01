// -*- c++ -*-
//
// SnnNeuronModel.h: Header-only neuron dynamics strategy for SnnDL
// - Keep external interfaces untouched (SpikeEvent/ports/stats)
// - Provide small, pluggable neuron models (default: LIF)
// - No dependency on deprecated engines/

#ifndef SST_ELEMENTS_SNNDL_SNNNEURONMODEL_H
#define SST_ELEMENTS_SNNDL_SNNNEURONMODEL_H

#include <cstdint>
#include <cmath>
#include <memory>
#include <string>
#include <vector>

#include "SnnDLStringUtil.h"

#ifndef SNNDL_PARAMS_STUB
#include <sst/core/params.h>
#else
// Minimal stub for standalone unit tests (no SST core linkage required)
#include <unordered_map>
namespace SST { class Params {
public:
    void insert(const std::string& key, const std::string& val, bool overwrite = true) {
        if (overwrite || store_.find(key) == store_.end()) store_[key] = val;
    }
    template <typename T> T find(const std::string& key, T def) const {
        auto it = store_.find(key);
        if (it == store_.end()) return def;
        try {
            if constexpr (std::is_same<T,float>::value) return std::stof(it->second);
            if constexpr (std::is_same<T,double>::value) return std::stod(it->second);
            if constexpr (std::is_same<T,int>::value) return std::stoi(it->second);
            if constexpr (std::is_same<T,uint32_t>::value) return static_cast<uint32_t>(std::stoul(it->second));
        } catch(...) { /* fallthrough */ }
        return def;
    }
private:
    std::unordered_map<std::string,std::string> store_;
}; }
#endif

namespace SST { namespace SnnDL {

// Minimal unified config carried into models.
struct ModelConfig {
    float dt_ms = 1.0f;
    float v_thresh = 1.0f;
    float v_reset  = 0.0f;
    float v_rest   = 0.0f;
    float tau_mem  = 20.0f;
    uint32_t t_ref = 2;
    // Optional: leak behavior toggle to match slight differences in existing code paths.
    bool lif_leak_only_above_rest = false; // default matches SnnPE.cc behavior (apply always when false)
};

// Enum for model selection.
enum class NeuronModelType { LIF, Izhikevich, AdEx };

// Helpers to access NeuronState-like structs without depending on their concrete type.
template <typename StateT> inline float& state_v(StateT& s) { return s.v_mem; }
template <typename StateT> inline uint32_t& state_ref(StateT& s) { return s.refractory_timer; }
template <typename StateT> inline const float& state_v(const StateT& s) { return s.v_mem; }
template <typename StateT> inline const uint32_t& state_ref(const StateT& s) { return s.refractory_timer; }

// Base interface: per-neuron scalar core operations. Templated helpers handle arrays.
class INeuronModel {
public:
    virtual ~INeuronModel() {}

    virtual void init(uint32_t N, const ModelConfig& cfg, const SST::Params& params) = 0;

    // Per-neuron scalar ops. Host can call these directly or use the array helpers below.
    virtual void tickOne(float& v_mem, uint32_t& refractory_timer) = 0;
    // Optional indexed variant (for models with per-neuron arrays). Default delegates to tickOne.
    virtual void tickIdx(uint32_t /*i*/, float& v_mem, uint32_t& refractory_timer) { tickOne(v_mem, refractory_timer); }
    virtual void onSynapticEventOne(float& v_mem, uint32_t& /*refractory_timer*/, float w) = 0;
    virtual bool shouldFireOne(float v_mem, uint32_t refractory_timer) const = 0;
    virtual void onFiredOne(float& v_mem, uint32_t& refractory_timer) = 0;
    // Optional indexed onFired.
    virtual void onFiredIdx(uint32_t /*i*/, float& v_mem, uint32_t& refractory_timer) { onFiredOne(v_mem, refractory_timer); }

    // Models that need an input accumulator can override these (default off for LIF).
    virtual bool useAccumulator() const { return false; }
    virtual void accumulateISyn(uint32_t /*i*/, float /*w*/) {}
    virtual void clearAccumulatedISyn() {}

    // Array helpers that operate on host-owned neuron states (SnnPE/SnnPESubComponent).
    template <typename StateT>
    void tickArray(std::vector<StateT>& neurons) {
        const uint32_t N = static_cast<uint32_t>(neurons.size());
        for (uint32_t i = 0; i < N; ++i) {
            auto& s = neurons[i];
            tickIdx(i, state_v(s), state_ref(s));
        }
    }

    template <typename StateT>
    inline void onSynapticEvent(uint32_t i, float w, StateT& s) {
        if (useAccumulator()) {
            accumulateISyn(i, w);
        } else {
            onSynapticEventOne(state_v(s), state_ref(s), w);
        }
    }

    template <typename StateT>
    inline bool shouldFire(uint32_t /*i*/, const StateT& s) const {
        return shouldFireOne(state_v(s), state_ref(s));
    }

    template <typename StateT>
    inline void onFired(uint32_t i, StateT& s) {
        onFiredIdx(i, state_v(s), state_ref(s));
    }
};

// LIF model: matches current implementation semantics by default.
class LIFModel final : public INeuronModel {
public:
    void init(uint32_t N, const ModelConfig& cfg, const SST::Params& /*params*/) override {
        N_ = N;
        cfg_ = cfg;
        // Precompute leak factor for dt.
        leak_factor_ = (cfg_.tau_mem > 0.0f) ? std::exp(-cfg_.dt_ms / cfg_.tau_mem) : 1.0f;
    }

    void tickOne(float& v_mem, uint32_t& refractory_timer) override {
        if (refractory_timer > 0) {
            --refractory_timer;
            return;
        }
        // Exponential leak toward v_rest. Optionally skip when below rest to mirror one code path.
        if (!cfg_.lif_leak_only_above_rest || v_mem > cfg_.v_rest) {
            v_mem = cfg_.v_rest + (v_mem - cfg_.v_rest) * leak_factor_;
        }
    }

    void onSynapticEventOne(float& v_mem, uint32_t& /*refractory_timer*/, float w) override {
        // Host may guard refractory externally; we only apply the increment.
        v_mem += w;
    }

    bool shouldFireOne(float v_mem, uint32_t refractory_timer) const override {
        return (refractory_timer == 0) && (v_mem >= cfg_.v_thresh);
    }

    void onFiredOne(float& v_mem, uint32_t& refractory_timer) override {
        v_mem = cfg_.v_reset;
        refractory_timer = cfg_.t_ref;
    }

private:
    uint32_t N_ = 0;
    ModelConfig cfg_{};
    float leak_factor_ = 1.0f;
};

// Izhikevich model with per-neuron u and I_syn accumulators.
class IzhikevichModel final : public INeuronModel {
public:
    void init(uint32_t N, const ModelConfig& cfg, const SST::Params& params) override {
        N_ = N;
        cfg_ = cfg;
        dt_ = (cfg_.dt_ms > 0.f) ? cfg_.dt_ms : 1.f;
        a_ = params.find<float>("model.a", 0.02f);
        b_ = params.find<float>("model.b", 0.2f);
        c_ = params.find<float>("model.c", -65.f);
        d_ = params.find<float>("model.d", 8.f);
        v_thresh_ = params.find<float>("v_thresh", 30.f);
        u_.assign(N_, 0.0f);
        i_syn_.assign(N_, 0.0f);
        const float u0 = b_ * cfg_.v_rest;
        for (uint32_t i = 0; i < N_; ++i) u_[i] = u0;
    }

    bool useAccumulator() const override { return true; }
    void accumulateISyn(uint32_t i, float w) override {
        if (i < i_syn_.size()) i_syn_[i] += w;
    }
    void clearAccumulatedISyn() override { std::fill(i_syn_.begin(), i_syn_.end(), 0.0f); }

    void tickOne(float& v_mem, uint32_t& refractory_timer) override {
        // Fallback: only handle refractory when indexless call is used
        if (refractory_timer > 0) --refractory_timer;
    }
    void tickIdx(uint32_t i, float& v_mem, uint32_t& refractory_timer) override {
        if (i >= N_) return;
        if (refractory_timer > 0) {
            --refractory_timer;
            i_syn_[i] = 0.0f;
            return;
        }
        float v = v_mem;
        float u = u_[i];
        const float I = i_syn_[i];
        const float dv = 0.04f * v * v + 5.0f * v + 140.0f - u + I;
        const float du = a_ * (b_ * v - u);
        v += dv * dt_;
        u += du * dt_;
        v_mem = v;
        u_[i] = u;
        i_syn_[i] = 0.0f;
    }

    void onSynapticEventOne(float& /*v_mem*/, uint32_t& /*refractory_timer*/, float /*w*/) override {}

    bool shouldFireOne(float v_mem, uint32_t refractory_timer) const override {
        return (refractory_timer == 0) && (v_mem >= v_thresh_);
    }

    void onFiredOne(float& v_mem, uint32_t& refractory_timer) override {
        v_mem = c_;
        refractory_timer = cfg_.t_ref;
    }
    void onFiredIdx(uint32_t i, float& v_mem, uint32_t& refractory_timer) override {
        if (i < u_.size()) u_[i] += d_;
        v_mem = c_;
        refractory_timer = cfg_.t_ref;
    }

private:
    uint32_t N_ = 0;
    ModelConfig cfg_{};
    float dt_ = 1.0f;
    float a_ = 0.02f, b_ = 0.2f, c_ = -65.f, d_ = 8.f;
    float v_thresh_ = 30.f;
    std::vector<float> u_;
    std::vector<float> i_syn_;
};

// Adaptive Exponential IF (AdEx) with per-neuron w and I_syn accumulators.
class AdExModel final : public INeuronModel {
public:
    void init(uint32_t N, const ModelConfig& cfg, const SST::Params& params) override {
        N_ = N;
        cfg_ = cfg;
        dt_ = (cfg_.dt_ms > 0.f) ? cfg_.dt_ms : 1.f;
        C_      = params.find<float>("model.C", 200.f);
        gL_     = params.find<float>("model.gL", 10.f);
        EL_     = params.find<float>("model.EL", -70.f);
        VT_     = params.find<float>("model.VT", -50.f);
        DeltaT_ = params.find<float>("model.DeltaT", 2.f);
        tau_w_  = params.find<float>("model.tau_w", 100.f);
        a_      = params.find<float>("model.a", 2.f);
        b_      = params.find<float>("model.b", 60.f);
        Vr_     = params.find<float>("model.Vr", -58.f);
        v_thresh_ = params.find<float>("v_thresh", -40.f);
        w_.assign(N_, 0.0f);
        i_syn_.assign(N_, 0.0f);
    }

    bool useAccumulator() const override { return true; }
    void accumulateISyn(uint32_t i, float w) override {
        if (i < i_syn_.size()) i_syn_[i] += w;
    }
    void clearAccumulatedISyn() override { std::fill(i_syn_.begin(), i_syn_.end(), 0.0f); }

    void tickOne(float& v_mem, uint32_t& refractory_timer) override {
        if (refractory_timer > 0) --refractory_timer;
    }
    void tickIdx(uint32_t i, float& v_mem, uint32_t& refractory_timer) override {
        if (i >= N_) return;
        if (refractory_timer > 0) {
            --refractory_timer;
            i_syn_[i] = 0.0f;
            return;
        }
        float v = v_mem;
        float w = w_[i];
        const float I = i_syn_[i];
        const float x = (v - VT_) / std::max(1e-6f, DeltaT_);
        const float x_clamped = (x > 50.f ? 50.f : (x < -50.f ? -50.f : x));
        const float exp_term = std::exp(x_clamped);
        const float dv = ( -gL_ * (v - EL_) + gL_ * DeltaT_ * exp_term - w + I ) / std::max(1e-6f, C_);
        const float dw = ( a_ * (v - EL_) - w ) / std::max(1e-6f, tau_w_);
        v += dv * dt_;
        w += dw * dt_;
        v_mem = v;
        w_[i] = w;
        i_syn_[i] = 0.0f;
    }

    void onSynapticEventOne(float& /*v_mem*/, uint32_t& /*refractory_timer*/, float /*w*/) override {}

    bool shouldFireOne(float v_mem, uint32_t refractory_timer) const override {
        return (refractory_timer == 0) && (v_mem >= v_thresh_);
    }

    void onFiredOne(float& v_mem, uint32_t& refractory_timer) override {
        v_mem = Vr_;
        refractory_timer = cfg_.t_ref;
    }
    void onFiredIdx(uint32_t i, float& v_mem, uint32_t& refractory_timer) override {
        if (i < w_.size()) w_[i] += b_;
        v_mem = Vr_;
        refractory_timer = cfg_.t_ref;
    }

private:
    uint32_t N_ = 0;
    ModelConfig cfg_{};
    float dt_ = 1.0f;
    float C_ = 200.f, gL_ = 10.f, EL_ = -70.f, VT_ = -50.f, DeltaT_ = 2.f;
    float tau_w_ = 100.f, a_ = 2.f, b_ = 60.f, Vr_ = -58.f;
    float v_thresh_ = -40.f;
    std::vector<float> w_;
    std::vector<float> i_syn_;
};

// Factory helpers.
inline NeuronModelType parseNeuronModel(const std::string& s_in) {
    const std::string s = toLowerCopy(s_in); // case-insensitive parse
    if (s == "lif" || s.empty()) return NeuronModelType::LIF;
    if (s == "izhikevich" || s == "izh") return NeuronModelType::Izhikevich;
    if (s == "adex" || s == "aex" || s == "adaptive_exponential") return NeuronModelType::AdEx;
    return NeuronModelType::LIF; // default fallback
}

inline std::unique_ptr<INeuronModel> createNeuronModel(NeuronModelType t) {
    switch (t) {
        case NeuronModelType::LIF: return std::unique_ptr<INeuronModel>(new LIFModel());
        case NeuronModelType::Izhikevich: return std::unique_ptr<INeuronModel>(new IzhikevichModel());
        case NeuronModelType::AdEx:       return std::unique_ptr<INeuronModel>(new AdExModel());
        default: return std::unique_ptr<INeuronModel>(new LIFModel());
    }
}

inline ModelConfig buildModelConfigFromParams(const SST::Params& params) {
    ModelConfig cfg;
    cfg.dt_ms   = params.find<float>("neuron_dt_ms", 1.0f);
    cfg.v_thresh = params.find<float>("v_thresh", 1.0f);
    cfg.v_reset  = params.find<float>("v_reset", 0.0f);
    cfg.v_rest   = params.find<float>("v_rest", 0.0f);
    cfg.tau_mem  = params.find<float>("tau_mem", 20.0f);
    cfg.t_ref    = params.find<uint32_t>("t_ref", 2);
    // Optional knob to match SnnPESubComponent's conditional leak if needed later.
    cfg.lif_leak_only_above_rest = params.find<int>("lif_leak_only_above_rest", 0) != 0;
    return cfg;
}

}} // namespace SST::SnnDL

#endif // SST_ELEMENTS_SNNDL_SNNNEURONMODEL_H
