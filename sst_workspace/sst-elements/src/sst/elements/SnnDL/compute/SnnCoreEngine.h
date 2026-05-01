#ifndef SST_ELEMENTS_SNNDL_SNNCOREENGINE_H
#define SST_ELEMENTS_SNNDL_SNNCOREENGINE_H

#include <algorithm>
#include <cstdint>
#include <vector>

#include "SnnNeuronModel.h"

namespace SST {
namespace SnnDL {

struct SnnCoreNeuronState {
    float v_mem;
    uint32_t refractory_timer;
    uint64_t last_spike_time;
    explicit SnnCoreNeuronState(float v_rest = 0.0f)
        : v_mem(v_rest), refractory_timer(0), last_spike_time(0) {}
};

struct SnnCoreConfig {
    uint32_t num_neurons = 0;
    float v_thresh = 1.0f;
    float v_reset = 0.0f;
    float v_rest = 0.0f;
    float tau_mem = 20.0f;
    uint32_t t_ref = 2;
    bool use_soa_state = false;
    bool use_aosoa_state = false;
    uint32_t aosoa_block_rows = 16;
};

class SnnCoreEngine {
public:
    SnnCoreEngine() = default;
    explicit SnnCoreEngine(const SnnCoreConfig& cfg) { configure(cfg); }

    void configure(const SnnCoreConfig& cfg);
    void bindState(std::vector<SnnCoreNeuronState>* aos_state,
                   std::vector<float>* soa_v_mem,
                   std::vector<uint32_t>* soa_refrac,
                   std::vector<uint64_t>* soa_last_spike);

    inline uint32_t size() const { return cfg_.num_neurons; }

    void resetMembrane(float v_rest_value);

    float getMem(uint32_t idx) const;
    void setMem(uint32_t idx, float val);
    void addMem(uint32_t idx, float dv);
    uint32_t getRefrac(uint32_t idx) const;
    void setRefrac(uint32_t idx, uint32_t val);
    uint64_t getLastSpike(uint32_t idx) const;
    void setLastSpike(uint32_t idx, uint64_t val);

    void updateNeuronStates();

    // Returns true if fired; v_before/v_after are valid when true.
    bool fire(uint32_t idx, uint64_t now_cycles, INeuronModel* model,
              float& v_before, float& v_after);

private:
    inline bool useSoA() const { return cfg_.use_soa_state || cfg_.use_aosoa_state; }
    inline bool validIndex(uint32_t idx) const { return idx < cfg_.num_neurons; }

    SnnCoreConfig cfg_{};
    float decay_factor_ = 1.0f;
    uint32_t aosoa_lane_ = 16;

    std::vector<SnnCoreNeuronState>* aos_state_ = nullptr;
    std::vector<float>* soa_v_mem_ = nullptr;
    std::vector<uint32_t>* soa_refrac_ = nullptr;
    std::vector<uint64_t>* soa_last_spike_ = nullptr;
};

} // namespace SnnDL
} // namespace SST

#endif // SST_ELEMENTS_SNNDL_SNNCOREENGINE_H
