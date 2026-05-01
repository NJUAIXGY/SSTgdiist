// -*- c++ -*-
//
// StepActivationPredictor (experimental helper):
// - Provides a lightweight, deterministic predictor that mirrors the RNG consumption
//   of StepActivationSubsystem for the default dense-microbench path:
//   * pre_pattern = BernoulliUniform
//   * use_bcsr_routes = false
//   * post selection uses uniform_int_distribution over local neurons_per_pe
//
// Rationale:
// - GlobalGasStepController updates credits for *next* step at PE_DONE(current).
// - For i.i.d. random activation, last-step telemetry is not predictive.
// - When the activation generator is deterministic (seed ^ (seq + node<<32)), the controller
//   can predict the next-step load and assign credits proactively.
//
// Limitations:
// - This is NOT a general-purpose predictor; it intentionally matches the microbench path.
// - If StepActivationSubsystem changes its RNG consumption, this predictor must be updated.
//

#pragma once

#include <cstdint>
#include <random>

namespace SST { namespace SnnDL {

struct StepActivationPredictorConfig {
    uint64_t seed = 0;
    double fraction = 0.0;
    uint32_t neurons_per_pe = 0;
    uint32_t fanout = 0;
};

inline uint64_t predictStepActivationSourcesSelected(
    uint32_t seq,
    uint32_t node_id,
    const StepActivationPredictorConfig& cfg)
{
    if (cfg.neurons_per_pe == 0) return 0;
    if (cfg.fanout == 0) return 0;
    double fraction = cfg.fraction;
    if (fraction <= 0.0) return 0;
    if (fraction > 1.0) fraction = 1.0;

    // Mirror:
    //   std::mt19937_64 rng(cfg_.seed ^ (seq + (node_id<<32)))
    std::mt19937_64 rng(cfg.seed ^ (static_cast<uint64_t>(seq) + (static_cast<uint64_t>(node_id) << 32)));
    std::uniform_int_distribution<uint64_t> post_dist(0, static_cast<uint64_t>(cfg.neurons_per_pe) - 1);
    std::bernoulli_distribution pick(fraction);
    const bool activate_all = (fraction >= 0.999999);

    uint64_t sources_selected = 0;
    // Important: StepActivationSubsystem consumes RNG for post_dist only on selected pre neurons,
    // which makes later pick(rng) dependent on earlier selections.
    // Therefore, we must mimic the post_dist draws to keep RNG state aligned.
    for (uint32_t n = 0; n < cfg.neurons_per_pe; ++n) {
        if (!activate_all && !pick(rng)) continue;
        ++sources_selected;
        for (uint32_t fan = 0; fan < cfg.fanout; ++fan) {
            (void)post_dist(rng);
        }
    }
    return sources_selected;
}

}} // namespace SST::SnnDL

