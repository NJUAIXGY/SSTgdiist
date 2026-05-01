// -*- c++ -*-
//
// StepActivationSubsystem implementation
//

#include "StepActivationSubsystem.h"

#include <algorithm>
#include <cmath>
#include <cinttypes>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <limits>
#include <random>
#include <sstream>

#include <sst/core/output.h>
#include <sst/core/statapi/stataccumulator.h>

#include "../../api/GlobalNeuronLayout.h"
#include "INocTransport.h"
#include "NocPacketEvent.h"
#include "events/SpikeEvent.h"

#include "synapse/route/StepBcsrReachability.h"
#include "synapse/route/SpikeNocCodec.h"

namespace SST { namespace SnnDL {

#ifndef STEP_LOG
#define STEP_LOG(lvl, ...) do { if (rt_.log) rt_.log->verbose(CALL_INFO, (lvl), 0, __VA_ARGS__); } while(0)
#endif

void StepActivationSubsystem::configure(const Config& cfg) {
    cfg_ = cfg;
    injection_ready_ = false;
    pending_step_inject_ = false;
    pending_step_seq_ = 0;
    pending_step_ts_ns_ = 0;
    next_cycle_ = 0;
    fixed_seq_ = 1;
    last_injection_seq_ = std::numeric_limits<uint32_t>::max();
    last_reset_seq_ = std::numeric_limits<uint32_t>::max();
    seq_warn_count_ = 0;
    route_diag_done_ = false;
    route_ack_logged_ = false;
    route_warned_ = false;
    step_routes_map_.clear();
    pre_with_routes_.clear();
    if (cfg_.bcsr_align == 0) cfg_.bcsr_align = 64;
}

void StepActivationSubsystem::bindRuntime(const Runtime& rt) {
    rt_ = rt;

    if (!rt_.layout || !rt_.layout->valid()) {
        if (rt_.log) rt_.log->fatal(CALL_INFO, -1, "StepActivationSubsystem fatal: runtime.layout 为空或无效，无法进行全局ID映射（fail-fast）\n");
        return;
    }

    const uint64_t derived_neurons_per_pe =
        static_cast<uint64_t>(rt_.num_cores) * static_cast<uint64_t>(rt_.neurons_per_core);
    const uint64_t layout_neurons_per_pe = rt_.layout->neuronsPerPE();
    if (layout_neurons_per_pe != derived_neurons_per_pe) {
        if (rt_.log) rt_.log->fatal(
            CALL_INFO, -1,
            "StepActivationSubsystem fatal: neurons_per_pe 口径不一致（fail-fast）：layout=%" PRIu64 " derived(num_cores*neurons_per_core)=%" PRIu64 "\n",
            layout_neurons_per_pe, derived_neurons_per_pe);
        return;
    }
    if (rt_.neurons_per_pe_cfg != 0 && static_cast<uint64_t>(rt_.neurons_per_pe_cfg) != layout_neurons_per_pe) {
        if (rt_.log) rt_.log->fatal(
            CALL_INFO, -1,
            "StepActivationSubsystem fatal: neurons_per_pe_cfg(%u) 与 layout.neuronsPerPE(%" PRIu64 ") 不一致（fail-fast）\n",
            rt_.neurons_per_pe_cfg, layout_neurons_per_pe);
        return;
    }
    const uint64_t expected_base = rt_.layout->globalBaseOfNode(static_cast<uint32_t>(rt_.node_id));
    if (rt_.global_neuron_base != expected_base) {
        if (rt_.log) rt_.log->fatal(
            CALL_INFO, -1,
            "StepActivationSubsystem fatal: global_neuron_base(0x%" PRIx64 ") 与 layout.base(node=%d)=0x%" PRIx64 " 不一致（fail-fast）\n",
            rt_.global_neuron_base, rt_.node_id, expected_base);
        return;
    }

    if (cfg_.trigger_core < -1 || cfg_.trigger_core >= rt_.num_cores) {
        STEP_LOG(1, "⚠️ step_activation_trigger_core=%d 超出范围[-1,%d)，回退到0\n",
                 cfg_.trigger_core, rt_.num_cores);
        cfg_.trigger_core = 0;
    }
}

void StepActivationSubsystem::bindStats(const Stats& st) {
    st_ = st;
}

void StepActivationSubsystem::initBcsrReachabilityIfEnabled() {
    if (!(cfg_.enable && cfg_.use_bcsr_routes)) return;
    if (!loadBcsrReachability_()) {
        STEP_LOG(1, "⚠️ step_activation_use_bcsr_routes=1 但 BCSR 索引加载失败，回退到均匀采样\n");
        cfg_.use_bcsr_routes = false;
    }
}

void StepActivationSubsystem::tick(uint64_t current_cycle, uint64_t now_ns) {
    if (!cfg_.enable) return;

    // legacy: BeginGather 触发（当 period==0 时保留原始行为）
    if (cfg_.period_cycles == 0 && pending_step_inject_ && injection_ready_) {
        injectStepActivations_(pending_step_seq_, pending_step_ts_ns_);
        last_injection_seq_ = pending_step_seq_;
        pending_step_inject_ = false;
        pending_step_ts_ns_ = 0;
    }

    // 固定周期触发（去耦 BeginGather 时基漂移）
    if (cfg_.period_cycles > 0 && injection_ready_) {
        if (next_cycle_ == 0) {
            next_cycle_ = current_cycle;
            fixed_seq_ = 1;
        }
        if (current_cycle >= next_cycle_) {
            injectStepActivations_(fixed_seq_, now_ns);
            ++fixed_seq_;
            next_cycle_ += cfg_.period_cycles;
        }
    }
}

void StepActivationSubsystem::onBeginGather(uint32_t seq, uint64_t ts_ns, int core_id) {
    if (!cfg_.enable) return;
    if (cfg_.period_cycles != 0) return;

    const bool trace_step_path =
        rt_.log &&
        rt_.node_id == 0 &&
        seq <= 2 &&
        core_id >= 15;
    if (trace_step_path) {
        STEP_LOG(2,
                 "[[sentinel-step-path]] node=%d core=%d seq=%u step_activation onBeginGather enter ready=%d last=%u pending=%d trigger_core=%d\n",
                 rt_.node_id, core_id, seq, injection_ready_ ? 1 : 0,
                 last_injection_seq_, pending_step_inject_ ? 1 : 0, cfg_.trigger_core);
    }

    const bool core_ok = (cfg_.trigger_core < 0) ||
                         (core_id < 0) ||
                         (core_id == cfg_.trigger_core);
    if (!core_ok) {
        if (trace_step_path) {
            STEP_LOG(2,
                     "[[sentinel-step-path]] node=%d core=%d seq=%u step_activation onBeginGather filtered_by_trigger\n",
                     rt_.node_id, core_id, seq);
        }
        return;
    }

    const bool first_inject = (last_injection_seq_ == std::numeric_limits<uint32_t>::max());
    if (first_inject || seq > last_injection_seq_) {
        if (injection_ready_) {
            if (trace_step_path) {
                STEP_LOG(2,
                         "[[sentinel-step-path]] node=%d core=%d seq=%u step_activation before_inject\n",
                         rt_.node_id, core_id, seq);
            }
            injectStepActivations_(seq, ts_ns);
            last_injection_seq_ = seq;
            if (trace_step_path) {
                STEP_LOG(2,
                         "[[sentinel-step-path]] node=%d core=%d seq=%u step_activation after_inject\n",
                         rt_.node_id, core_id, seq);
            }
        } else {
            pending_step_inject_ = true;
            pending_step_seq_ = seq;
            pending_step_ts_ns_ = ts_ns;
            if (trace_step_path) {
                STEP_LOG(2,
                         "[[sentinel-step-path]] node=%d core=%d seq=%u step_activation deferred_pending\n",
                         rt_.node_id, core_id, seq);
            }
        }
    } else {
        // 多核/全局 step 同步场景下，同一个 seq 可能会重复触发 BeginGather（属于正常现象，静默忽略）。
        // 仅对回退 seq（seq < last）做告警。
        if (seq < last_injection_seq_) {
            if (rt_.log && seq_warn_count_ < 16) {
                STEP_LOG(1, "[step-warn] non-monotonic BeginGather ignored: node=%d core=%d seq=%u last=%u\n",
                         rt_.node_id, core_id, seq, last_injection_seq_);
                ++seq_warn_count_;
            }
        }
    }
    if (trace_step_path) {
        STEP_LOG(2,
                 "[[sentinel-step-path]] node=%d core=%d seq=%u step_activation onBeginGather exit\n",
                 rt_.node_id, core_id, seq);
    }
}

void StepActivationSubsystem::onGlobalStepStart(uint32_t seq, uint64_t ts_ns) {
    if (!cfg_.enable) return;
    if (cfg_.period_cycles != 0) return;

    const bool first_inject = (last_injection_seq_ == std::numeric_limits<uint32_t>::max());
    if (first_inject || seq > last_injection_seq_) {
        if (injection_ready_) {
            injectStepActivations_(seq, ts_ns);
            last_injection_seq_ = seq;
        } else {
            pending_step_inject_ = true;
            pending_step_seq_ = seq;
            pending_step_ts_ns_ = ts_ns;
        }
        return;
    }

    // 重复 seq 属于正常（例如 PE 侧重复收到 START_STEP），静默忽略；仅对回退 seq 报警。
    if (seq < last_injection_seq_) {
        if (rt_.log && seq_warn_count_ < 16) {
            STEP_LOG(1, "[step-warn] non-monotonic GlobalStepStart ignored: node=%d seq=%u last=%u\n",
                     rt_.node_id, seq, last_injection_seq_);
            ++seq_warn_count_;
        }
    }
}

bool StepActivationSubsystem::injectedForSeq(uint32_t seq) const {
    if (!cfg_.enable) return true;
    const uint32_t kInvalid = std::numeric_limits<uint32_t>::max();
    if (last_injection_seq_ == kInvalid) return false;
    return last_injection_seq_ >= seq;
}

void StepActivationSubsystem::onEndScatter(uint32_t seq) {
    if (!cfg_.reset_mem_each_step) return;
    if (last_reset_seq_ == seq) return;
    if (rt_.reset_membranes) rt_.reset_membranes();
    last_reset_seq_ = seq;
}

int StepActivationSubsystem::determineTargetUnit_(uint32_t neuron_id) const {
    if (!rt_.layout || !rt_.layout->valid()) return -1;
    if (!rt_.layout->inGlobalRange(static_cast<uint64_t>(neuron_id))) return -1;
    if (!rt_.layout->isLocalToNode(static_cast<uint64_t>(neuron_id), static_cast<uint32_t>(rt_.node_id))) return -1;
    const uint32_t core = rt_.layout->coreOf(static_cast<uint64_t>(neuron_id));
    return (core < static_cast<uint32_t>(rt_.num_cores)) ? static_cast<int>(core) : -1;
}

void StepActivationSubsystem::injectStepActivations_(uint32_t seq, uint64_t sim_time_ns) {
    if (!rt_.layout || !rt_.layout->valid()) return;
    const uint64_t neurons_per_pe = rt_.layout->neuronsPerPE();
    const uint64_t local_total = neurons_per_pe;
    if (!cfg_.enable || cfg_.fanout == 0 || local_total == 0) return;
    if (!rt_.noc) {
        if (rt_.log) rt_.log->fatal(CALL_INFO, -1, "StepActivationSubsystem fatal: runtime.noc is null while step is enabled\n");
        return;
    }

    double fraction = cfg_.fraction;
    if (fraction <= 0.0) return;
    if (fraction > 1.0) fraction = 1.0;

    if (st_.invocations) st_.invocations->addData(1);

    const uint64_t max_global = rt_.layout->maxGlobalNeurons();
    const uint64_t diag_cap = (rt_.step_diag_cap_cfg > 0) ? static_cast<uint64_t>(rt_.step_diag_cap_cfg) : 0ULL;
    std::mt19937_64 rng(cfg_.seed ^ (static_cast<uint64_t>(seq) + (static_cast<uint64_t>(rt_.node_id) << 32)));
    std::uniform_int_distribution<uint64_t> post_dist(0, local_total - 1);
    const uint64_t pre_global_hi = (max_global > 0) ? (max_global - 1) : 0;
    std::uniform_int_distribution<uint64_t> pre_global_dist(0, pre_global_hi);
    std::bernoulli_distribution pick(fraction);
    const bool activate_all = (fraction >= 0.999999);
    const bool clustered_pre = (cfg_.pre_pattern == Config::PrePattern::Clustered);
    uint64_t spikes_injected = 0;
    uint64_t sources_selected = 0;
    uint64_t spike_attempts = 0;
    uint64_t route_hits = 0;
    uint64_t route_misses = 0;
    uint64_t local_drops = 0;
    bool diag_cap_hit = false;

    const bool step_diag_enabled = (rt_.step_diag_enable_cfg != 0);

    if (step_diag_enabled && !route_diag_done_ && rt_.node_id == 0 && seq <= 1 && cfg_.use_bcsr_routes) {
        uint64_t with_routes = 0;
        uint64_t max_routes = 0;
        uint64_t local_edges = 0;
        uint64_t remote_edges = 0;
        for (const auto& kv : step_routes_map_) {
            const auto& v = kv.second;
            if (v.empty()) continue;
            ++with_routes;
            if (v.size() > max_routes) max_routes = static_cast<uint64_t>(v.size());
            for (auto post : v) {
                uint32_t pe_of_post = rt_.layout->nodeOf(static_cast<uint64_t>(post));
                if (pe_of_post == static_cast<uint32_t>(rt_.node_id)) ++local_edges; else ++remote_edges;
            }
        }
        if (rt_.log && rt_.log->getVerboseLevel() >= 2) {
            double denom_edges = (local_edges + remote_edges) ? static_cast<double>(local_edges + remote_edges) : 1.0;
            double local_ratio = static_cast<double>(local_edges) / denom_edges;
            double remote_ratio = static_cast<double>(remote_edges) / denom_edges;
            const uint64_t total_neurons = static_cast<uint64_t>(rt_.num_cores) * static_cast<uint64_t>(rt_.neurons_per_core);
            const uint64_t total_pre = rt_.global_neuron_base + total_neurons;
            STEP_LOG(2,
                "[step-activation-summary] node=%d routes_nonempty=%" PRIu64 " total_pre=%" PRIu64 " max_routes=%" PRIu64
                " max_global=%" PRIu64 " local=%" PRIu64 " (%.2f) remote=%" PRIu64 " (%.2f)\n",
                rt_.node_id, with_routes, total_pre, max_routes, max_global,
                local_edges, local_ratio, remote_edges, remote_ratio);
        }
        route_diag_done_ = true;
    }

    const bool single_pe_bcsr = (rt_.total_nodes == 1) && cfg_.use_bcsr_routes && !pre_with_routes_.empty();

    if (single_pe_bcsr) {
        if (clustered_pre && rt_.log && rt_.log->getVerboseLevel() >= 1) {
            STEP_LOG(1, "[step-activation] WARN: clustered pre pattern is ignored under single_pe_bcsr path; fallback to Bernoulli\n");
        }
        for (uint32_t pre_global : pre_with_routes_) {
            if (max_global > 0 && pre_global >= max_global) continue;
            if (!activate_all && !pick(rng)) continue;
            ++sources_selected;
            const auto it = step_routes_map_.find(pre_global);
            const auto* routes = (cfg_.use_bcsr_routes && it != step_routes_map_.end()) ? &it->second : nullptr;
            if (!routes || routes->empty()) continue;

            static uint64_t route_sampled = 0;
            if (step_diag_enabled && rt_.node_id == 0 && seq <= 1 && route_sampled < 16) {
                STEP_LOG(1, "[[step-diag-pre]] node=%d seq=%u pre_global=%u routes=%zu\n",
                         rt_.node_id, seq, pre_global, routes->size());
                ++route_sampled;
            }
            for (uint32_t fan = 0; fan < cfg_.fanout; ++fan) {
                ++spike_attempts;
                std::uniform_int_distribution<size_t> route_pick(0, routes->size() - 1);
                uint32_t post_global = (*routes)[route_pick(rng)];
                if (max_global > 0 && static_cast<uint64_t>(post_global) >= max_global) {
                    ++local_drops;
                    continue;
                }
                route_hits++;

                if (!rt_.layout->inGlobalRange(static_cast<uint64_t>(post_global))) {
                    ++local_drops;
                    continue;
                }
                const uint32_t dest_node = rt_.layout->nodeOf(static_cast<uint64_t>(post_global));
                SpikeEvent spike(pre_global, post_global, dest_node, 1.0f, sim_time_ns);
                NocPacketEvent* pkt = SpikeNocCodec::encode(spike, *rt_.layout);
                if (!pkt) {
                    ++local_drops;
                    continue;
                }
                // Step-limited semantics: injected spikes are processed in this step (seq).
                pkt->step_seq = seq;
                if (dest_node == static_cast<uint32_t>(rt_.node_id)) {
                    const int dst_core = determineTargetUnit_(post_global);
                    if (dst_core >= 0) {
                        rt_.noc->injectLocal(dst_core, pkt);
                        spikes_injected++;
                    } else {
                        delete pkt;
                        ++local_drops;
                    }
                } else {
                    rt_.noc->sendExternal(pkt);
                    spikes_injected++;
                }
                if (diag_cap && spikes_injected >= diag_cap) { diag_cap_hit = true; break; }
            }
            if (diag_cap_hit) break;
        }
    } else {
        const uint32_t nper = static_cast<uint32_t>(rt_.neurons_per_core > 0 ? rt_.neurons_per_core : 0);
        uint32_t cluster_len = cfg_.pre_cluster_len;
        if (cluster_len == 0) cluster_len = 64;
        if (cluster_len < 1) cluster_len = 1;
        if (nper > 0 && cluster_len > nper) cluster_len = nper;

        for (int core = 0; core < rt_.num_cores; ++core) {
            uint64_t base = rt_.global_neuron_base +
                static_cast<uint64_t>(core) * static_cast<uint64_t>(rt_.neurons_per_core);
            const bool use_routes = cfg_.use_bcsr_routes;

            // Build a pre index list when clustered, otherwise keep the legacy Bernoulli-per-neuron loop.
            std::vector<uint32_t> pre_local_indices;
            if (clustered_pre && !activate_all && nper > 0) {
                const uint32_t target = static_cast<uint32_t>(std::llround(fraction * static_cast<double>(nper)));
                if (target > 0) {
                    pre_local_indices.reserve(target);
                    std::vector<uint8_t> chosen(nper, 0);
                    auto fill_one = [&](uint32_t idx) {
                        if (idx >= nper) return;
                        if (chosen[idx]) return;
                        chosen[idx] = 1;
                        pre_local_indices.push_back(idx);
                    };

                    const uint32_t max_start = (nper > cluster_len) ? (nper - cluster_len) : 0;
                    std::uniform_int_distribution<uint32_t> start_dist(0, max_start);
                    const uint32_t max_attempts = std::max<uint32_t>(64, target * 4);
                    uint32_t attempts = 0;
                    while (pre_local_indices.size() < target && attempts < max_attempts) {
                        const uint32_t start = start_dist(rng);
                        const uint32_t end = std::min<uint32_t>(nper, start + cluster_len);
                        for (uint32_t i = start; i < end && pre_local_indices.size() < target; ++i) {
                            fill_one(i);
                        }
                        ++attempts;
                    }
                    if (pre_local_indices.size() < target) {
                        std::uniform_int_distribution<uint32_t> idx_dist(0, nper - 1);
                        while (pre_local_indices.size() < target) {
                            fill_one(idx_dist(rng));
                        }
                    }
                }
            }

            auto handle_one_pre = [&](uint32_t n) {
                ++sources_selected;
                uint32_t pre_global = 0;
                if (cfg_.pre_sample_global) {
                    if (max_global == 0) return;
                    pre_global = static_cast<uint32_t>(pre_global_dist(rng));
                } else {
                    uint64_t pre_global_64 = base + static_cast<uint64_t>(n);
                    if (max_global > 0 && pre_global_64 >= max_global) return;
                    pre_global = static_cast<uint32_t>(pre_global_64);
                }
                const auto it = step_routes_map_.find(pre_global);
                const auto* routes = (use_routes && it != step_routes_map_.end()) ? &it->second : nullptr;

                static uint64_t route_sampled = 0;
                if (step_diag_enabled && use_routes && routes && !routes->empty() &&
                    rt_.node_id == 0 && seq <= 1 && route_sampled < 16) {
                    STEP_LOG(1, "[[step-diag-pre]] node=%d seq=%u pre_global=%u routes=%zu\n",
                             rt_.node_id, seq, pre_global, routes->size());
                    ++route_sampled;
                }

                for (uint32_t fan = 0; fan < cfg_.fanout; ++fan) {
                    ++spike_attempts;
                    uint64_t post_global_64 = static_cast<uint64_t>(rt_.global_neuron_base) + post_dist(rng);
                    if (max_global > 0 && post_global_64 >= max_global) continue;
                    uint32_t post_global = static_cast<uint32_t>(post_global_64);
                    if (use_routes) {
                        if (routes && !routes->empty()) {
                            std::uniform_int_distribution<size_t> route_pick(0, routes->size() - 1);
                            post_global = (*routes)[route_pick(rng)];
                            route_hits++;
                        } else {
                            route_misses++;
                        }
                    }

                    if (!rt_.layout->inGlobalRange(static_cast<uint64_t>(post_global))) {
                        ++local_drops;
                        continue;
                    }
                    const uint32_t dest_node = rt_.layout->nodeOf(static_cast<uint64_t>(post_global));
                    SpikeEvent spike(pre_global, post_global, dest_node, 1.0f, sim_time_ns);
                    NocPacketEvent* pkt = SpikeNocCodec::encode(spike, *rt_.layout);
                    if (!pkt) {
                        ++local_drops;
                        continue;
                    }
                    // Step-limited semantics: injected spikes are processed in this step (seq).
                    pkt->step_seq = seq;
                    if (dest_node == static_cast<uint32_t>(rt_.node_id)) {
                        const int dst_core = determineTargetUnit_(post_global);
                        if (dst_core >= 0) {
                            rt_.noc->injectLocal(dst_core, pkt);
                            spikes_injected++;
                        } else {
                            delete pkt;
                            ++local_drops;
                        }
                    } else {
                        rt_.noc->sendExternal(pkt);
                        spikes_injected++;
                    }
                    if (diag_cap && spikes_injected >= diag_cap) { diag_cap_hit = true; break; }
                }
            };

            if (activate_all) {
                for (uint32_t n = 0; n < nper; ++n) {
                    handle_one_pre(n);
                    if (diag_cap_hit) break;
                }
            } else if (clustered_pre) {
                for (uint32_t n : pre_local_indices) {
                    handle_one_pre(n);
                    if (diag_cap_hit) break;
                }
            } else {
                for (uint32_t n = 0; n < nper; ++n) {
                    if (!pick(rng)) continue;
                    handle_one_pre(n);
                    if (diag_cap_hit) break;
                }
            }
            if (diag_cap_hit) break;
        }
    }

    if (st_.pre_selected && sources_selected) st_.pre_selected->addData(sources_selected);
    if (st_.spike_attempts && spike_attempts) st_.spike_attempts->addData(spike_attempts);
    if (st_.spikes_injected && spikes_injected) st_.spikes_injected->addData(spikes_injected);
    if (st_.route_hits && route_hits) st_.route_hits->addData(route_hits);
    if (st_.route_misses && route_misses) st_.route_misses->addData(route_misses);
    if (st_.local_drops && local_drops) st_.local_drops->addData(local_drops);
    if (rt_.report_injection_summary) {
        rt_.report_injection_summary(seq, sources_selected, spike_attempts, spikes_injected, route_hits, route_misses, local_drops);
    }

    if (rt_.log && rt_.log->getVerboseLevel() >= 1) {
        STEP_LOG(1,
            "[step-activation] seq=%u summary sources=%llu attempts=%llu spikes_ok=%llu route_hits=%llu route_miss=%llu local_drop=%llu fraction=%.4g fanout=%u use_routes=%d\n",
            seq,
            static_cast<unsigned long long>(sources_selected),
            static_cast<unsigned long long>(spike_attempts),
            static_cast<unsigned long long>(spikes_injected),
            static_cast<unsigned long long>(route_hits),
            static_cast<unsigned long long>(route_misses),
            static_cast<unsigned long long>(local_drops),
            fraction,
            cfg_.fanout,
            cfg_.use_bcsr_routes ? 1 : 0);
    }

    if (step_diag_enabled && rt_.node_id == 0 && seq <= 1) {
        STEP_LOG(1, "[[step-diag-stats]] node=%d seq=%u sources=%llu attempts=%llu spikes=%llu hits=%llu miss=%llu cap=%" PRIu64 " cap_hit=%d\n",
                 rt_.node_id, seq,
                 (unsigned long long)sources_selected,
                 (unsigned long long)spike_attempts,
                 (unsigned long long)spikes_injected,
                 (unsigned long long)route_hits,
                 (unsigned long long)route_misses,
                 diag_cap,
                 diag_cap_hit ? 1 : 0);
    }
}


bool StepActivationSubsystem::loadBcsrReachability_() {
    if (rt_.log && cfg_.log_enable) {
        STEP_LOG(0,
            "[step-activation] node=%d loadBcsrReachability enable=%d use_bcsr=%d template=%s build_local_only=%d rows_per_core=%u br=%u bc=%u\n",
            rt_.node_id, (int)cfg_.enable, (int)cfg_.use_bcsr_routes,
            cfg_.bcsr_template.c_str(), (int)cfg_.build_local_only,
            cfg_.bcsr_rows_per_core, cfg_.bcsr_br, cfg_.bcsr_bc);
    }
    if (cfg_.bcsr_template.empty()) {
        if (rt_.log && cfg_.log_enable) {
            STEP_LOG(0, "⚠️ 未提供 step_activation_bcsr_template，无法加载BCSR索引\n");
        }
        return false;
    }

    step_routes_map_.clear();

    StepBcsrReachabilityConfig rcfg{};
    rcfg.bcsr_template = cfg_.bcsr_template;
    rcfg.build_local_only = cfg_.build_local_only;
    rcfg.log_enable = cfg_.log_enable;
    rcfg.bcsr_rows_per_core = (cfg_.bcsr_rows_per_core > 0)
        ? cfg_.bcsr_rows_per_core
        : static_cast<uint32_t>(rt_.neurons_per_core);
    rcfg.bcsr_br = cfg_.bcsr_br;
    rcfg.bcsr_bc = cfg_.bcsr_bc;
    rcfg.bcsr_idx_bytes = cfg_.bcsr_idx_bytes;
    rcfg.bcsr_val_bytes = cfg_.bcsr_val_bytes;
    rcfg.bcsr_rowptr_offset = cfg_.bcsr_rowptr_offset;
    rcfg.bcsr_colidx_offset = cfg_.bcsr_colidx_offset;
    rcfg.bcsr_blockdata_offset = cfg_.bcsr_blockdata_offset;
    rcfg.bcsr_blockids_offset = cfg_.bcsr_blockids_offset;
    rcfg.bcsr_weight_epsilon = cfg_.bcsr_weight_epsilon;

    StepBcsrReachabilityRuntime rrt{};
    rrt.log = rt_.log;
    rrt.node_id = static_cast<uint32_t>(rt_.node_id);
    rrt.total_nodes = static_cast<uint32_t>(rt_.total_nodes > 0 ? rt_.total_nodes : 1);
    rrt.num_cores = static_cast<uint32_t>(rt_.num_cores);
    rrt.neurons_per_core = static_cast<uint32_t>(rt_.neurons_per_core);
    rrt.neurons_per_pe_cfg = rt_.neurons_per_pe_cfg;
    rrt.global_neuron_base = rt_.global_neuron_base;

    ISynapseRoute::RouteMap routes_map;
    std::vector<uint32_t> pre_with_routes;
    bool success = buildStepBcsrReachabilityRoutes(rcfg, rrt, routes_map, pre_with_routes);
    if (success) {
        step_routes_map_ = std::move(routes_map);
        if (rt_.total_nodes == 1) pre_with_routes_ = std::move(pre_with_routes);
        else pre_with_routes_.clear();
    }

    if (success) {
        size_t with_routes = 0;
        for (const auto& kv : step_routes_map_) if (!kv.second.empty()) ++with_routes;
        if (cfg_.log_enable && !route_ack_logged_) {
            STEP_LOG(1, "[step-activation] BCSR reachability loaded: pre_with_routes=%zu route_keys=%zu\n",
                     with_routes, step_routes_map_.size());
            computeRouteRatios_();
            route_ack_logged_ = true;
        }
        if (rt_.log && cfg_.log_enable && rt_.log->getVerboseLevel() >= 2) {
            STEP_LOG(2, "[step-activation] node=%d loadBcsrReachability success route_vectors=%zu\n",
                     rt_.node_id, step_routes_map_.size());
        }
        if (rt_.total_nodes == 1 && rt_.log && cfg_.log_enable) {
            STEP_LOG(1, "[step-activation] node=%d single-PE pre_with_routes_list size=%zu\n",
                     rt_.node_id, pre_with_routes_.size());
        }
    } else {
        pre_with_routes_.clear();
        if (cfg_.log_enable && !route_warned_) {
            STEP_LOG(0, "⚠️ step_activation BCSR route build failed, routes cleared; using fallback sampling\n");
            route_warned_ = true;
        }
        step_routes_map_.clear();
        if (rt_.log && cfg_.log_enable) {
            STEP_LOG(0, "[step-activation] node=%d loadBcsrReachability FAILED\n", rt_.node_id);
        }
    }
    return success;
}

void StepActivationSubsystem::computeRouteRatios_() const {
    uint64_t local_edges = 0, remote_edges = 0, total_edges = 0;
    const uint64_t neurons_per_pe = (rt_.layout && rt_.layout->valid()) ? rt_.layout->neuronsPerPE() : 0ULL;
    if (neurons_per_pe > 0) {
        for (const auto& kv : step_routes_map_) {
            const auto& vec = kv.second;
            total_edges += static_cast<uint64_t>(vec.size());
            for (auto post_global : vec) {
                const uint64_t pe_of_post = static_cast<uint64_t>(post_global) / neurons_per_pe;
                if (pe_of_post == static_cast<uint64_t>(rt_.node_id)) ++local_edges;
                else ++remote_edges;
            }
        }
    }
    double local_ratio = (total_edges ? (double)local_edges / (double)total_edges : 0.0);
    double remote_ratio = (total_edges ? (double)remote_edges / (double)total_edges : 0.0);
    if (rt_.log && cfg_.log_enable) {
        STEP_LOG(1,
            "[step-activation] route_ratio: node=%d local_edges=%" PRIu64 " remote_edges=%" PRIu64
            " total=%" PRIu64 " local_ratio=%.4f remote_ratio=%.4f\n",
            rt_.node_id, local_edges, remote_edges, total_edges, local_ratio, remote_ratio);
    }
}

}} // namespace SST::SnnDL
