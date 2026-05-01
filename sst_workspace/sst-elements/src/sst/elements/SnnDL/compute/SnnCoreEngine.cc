#include "SnnCoreEngine.h"

#include <cmath>

namespace SST {
namespace SnnDL {

void SnnCoreEngine::configure(const SnnCoreConfig& cfg) {
    cfg_ = cfg;
    decay_factor_ = (cfg_.tau_mem > 0.0f) ? std::exp(-1.0f / cfg_.tau_mem) : 1.0f;
    aosoa_lane_ = cfg_.aosoa_block_rows > 0 ? cfg_.aosoa_block_rows : 16;
}

void SnnCoreEngine::bindState(std::vector<SnnCoreNeuronState>* aos_state,
                              std::vector<float>* soa_v_mem,
                              std::vector<uint32_t>* soa_refrac,
                              std::vector<uint64_t>* soa_last_spike) {
    aos_state_ = aos_state;
    soa_v_mem_ = soa_v_mem;
    soa_refrac_ = soa_refrac;
    soa_last_spike_ = soa_last_spike;
}

void SnnCoreEngine::resetMembrane(float v_rest_value) {
    if (useSoA()) {
        if (soa_v_mem_) std::fill(soa_v_mem_->begin(), soa_v_mem_->end(), v_rest_value);
        if (soa_refrac_) std::fill(soa_refrac_->begin(), soa_refrac_->end(), 0u);
        if (soa_last_spike_) std::fill(soa_last_spike_->begin(), soa_last_spike_->end(), 0ull);
    } else if (aos_state_) {
        for (auto& st : *aos_state_) {
            st.v_mem = v_rest_value;
            st.refractory_timer = 0;
            st.last_spike_time = 0;
        }
    }
}

float SnnCoreEngine::getMem(uint32_t idx) const {
    if (!validIndex(idx)) return 0.0f;
    if (useSoA()) {
        return (soa_v_mem_ && idx < soa_v_mem_->size()) ? (*soa_v_mem_)[idx] : 0.0f;
    }
    return (aos_state_ && idx < aos_state_->size()) ? (*aos_state_)[idx].v_mem : 0.0f;
}

void SnnCoreEngine::setMem(uint32_t idx, float val) {
    if (!validIndex(idx)) return;
    if (useSoA()) {
        if (soa_v_mem_ && idx < soa_v_mem_->size()) (*soa_v_mem_)[idx] = val;
        return;
    }
    if (aos_state_ && idx < aos_state_->size()) (*aos_state_)[idx].v_mem = val;
}

void SnnCoreEngine::addMem(uint32_t idx, float dv) {
    if (!validIndex(idx)) return;
    if (useSoA()) {
        if (soa_v_mem_ && idx < soa_v_mem_->size()) (*soa_v_mem_)[idx] += dv;
        return;
    }
    if (aos_state_ && idx < aos_state_->size()) (*aos_state_)[idx].v_mem += dv;
}

uint32_t SnnCoreEngine::getRefrac(uint32_t idx) const {
    if (!validIndex(idx)) return 0;
    if (useSoA()) {
        return (soa_refrac_ && idx < soa_refrac_->size()) ? (*soa_refrac_)[idx] : 0;
    }
    return (aos_state_ && idx < aos_state_->size()) ? (*aos_state_)[idx].refractory_timer : 0;
}

void SnnCoreEngine::setRefrac(uint32_t idx, uint32_t val) {
    if (!validIndex(idx)) return;
    if (useSoA()) {
        if (soa_refrac_ && idx < soa_refrac_->size()) (*soa_refrac_)[idx] = val;
        return;
    }
    if (aos_state_ && idx < aos_state_->size()) (*aos_state_)[idx].refractory_timer = val;
}

uint64_t SnnCoreEngine::getLastSpike(uint32_t idx) const {
    if (!validIndex(idx)) return 0;
    if (useSoA()) {
        return (soa_last_spike_ && idx < soa_last_spike_->size()) ? (*soa_last_spike_)[idx] : 0;
    }
    return (aos_state_ && idx < aos_state_->size()) ? (*aos_state_)[idx].last_spike_time : 0;
}

void SnnCoreEngine::setLastSpike(uint32_t idx, uint64_t val) {
    if (!validIndex(idx)) return;
    if (useSoA()) {
        if (soa_last_spike_ && idx < soa_last_spike_->size()) (*soa_last_spike_)[idx] = val;
        return;
    }
    if (aos_state_ && idx < aos_state_->size()) (*aos_state_)[idx].last_spike_time = val;
}

void SnnCoreEngine::updateNeuronStates() {
    if (cfg_.tau_mem <= 0.0f) return;
    if (useSoA()) {
        if (!soa_v_mem_ || !soa_refrac_) return;
        if (cfg_.use_aosoa_state) {
            const uint32_t lane = aosoa_lane_;
            for (uint32_t block = 0; block < cfg_.num_neurons; block += lane) {
                uint32_t limit = std::min(cfg_.num_neurons, block + lane);
                for (uint32_t idx = block; idx < limit; ++idx) {
                    if ((*soa_refrac_)[idx] > 0) {
                        (*soa_refrac_)[idx]--;
                        continue;
                    }
                    float v = (*soa_v_mem_)[idx];
                    if (v > cfg_.v_rest) {
                        (*soa_v_mem_)[idx] = cfg_.v_rest + (v - cfg_.v_rest) * decay_factor_;
                    }
                }
            }
        } else {
            for (uint32_t i = 0; i < cfg_.num_neurons; ++i) {
                if ((*soa_refrac_)[i] > 0) {
                    (*soa_refrac_)[i]--;
                    continue;
                }
                float v = (*soa_v_mem_)[i];
                if (v > cfg_.v_rest) {
                    (*soa_v_mem_)[i] = cfg_.v_rest + (v - cfg_.v_rest) * decay_factor_;
                }
            }
        }
    } else {
        if (!aos_state_) return;
        for (uint32_t i = 0; i < cfg_.num_neurons; i++) {
            auto& neuron = (*aos_state_)[i];
            if (neuron.refractory_timer > 0) {
                neuron.refractory_timer--;
                continue;
            }
            if (neuron.v_mem > cfg_.v_rest) {
                neuron.v_mem = cfg_.v_rest + (neuron.v_mem - cfg_.v_rest) * decay_factor_;
            }
        }
    }
}

bool SnnCoreEngine::fire(uint32_t idx, uint64_t now_cycles, INeuronModel* model,
                         float& v_before, float& v_after) {
    if (!validIndex(idx)) return false;
    if (useSoA()) {
        if (!soa_v_mem_ || !soa_refrac_) return false;
        float v = (*soa_v_mem_)[idx];
        uint32_t ref = (*soa_refrac_)[idx];
        uint64_t last = (soa_last_spike_ && idx < soa_last_spike_->size()) ? (*soa_last_spike_)[idx] : 0;
        v_before = v;
        bool will_fire = false;

        if (model) {
            SnnCoreNeuronState tmp(cfg_.v_rest);
            tmp.v_mem = v;
            tmp.refractory_timer = ref;
            tmp.last_spike_time = last;
            will_fire = model->shouldFire(idx, tmp);
            if (!will_fire) {
                (*soa_v_mem_)[idx] = tmp.v_mem;
                (*soa_refrac_)[idx] = tmp.refractory_timer;
                if (soa_last_spike_ && idx < soa_last_spike_->size()) (*soa_last_spike_)[idx] = tmp.last_spike_time;
                return false;
            }
            model->onFired(idx, tmp);
            v_after = tmp.v_mem;
            ref = tmp.refractory_timer;
            last = tmp.last_spike_time;
        } else {
            will_fire = (ref == 0 && v >= cfg_.v_thresh);
            if (!will_fire) return false;
            v_after = cfg_.v_reset;
            ref = cfg_.t_ref;
            last = now_cycles;
        }

        (*soa_v_mem_)[idx] = v_after;
        (*soa_refrac_)[idx] = ref;
        if (soa_last_spike_ && idx < soa_last_spike_->size()) (*soa_last_spike_)[idx] = last;
        return true;
    }

    if (!aos_state_) return false;
    auto& neuron = (*aos_state_)[idx];
    v_before = neuron.v_mem;
    bool will_fire = false;
    if (model) {
        will_fire = model->shouldFire(idx, neuron);
        if (!will_fire) return false;
        model->onFired(idx, neuron);
        v_after = neuron.v_mem;
        neuron.last_spike_time = now_cycles;
    } else {
        will_fire = (neuron.refractory_timer == 0 && neuron.v_mem >= cfg_.v_thresh);
        if (!will_fire) return false;
        neuron.v_mem = cfg_.v_reset;
        neuron.refractory_timer = cfg_.t_ref;
        neuron.last_spike_time = now_cycles;
        v_after = neuron.v_mem;
    }
    return true;
}

} // namespace SnnDL
} // namespace SST
