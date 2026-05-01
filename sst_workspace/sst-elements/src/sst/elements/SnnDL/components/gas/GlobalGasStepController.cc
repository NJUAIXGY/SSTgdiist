// -*- c++ -*-
//
// GlobalGasStepController implementation
//

#include "gas/GlobalGasStepController.h"

#include <algorithm>
#include <inttypes.h>
#include <set>
#include <string>

#include "GasStepBarrierEvent.h"
#include "GatingDecisionEvent.h"
#include "gas/experimental/P0BCreditPolicy.h"
#include "gas/experimental/StepActivationPredictor.h"
#include "gas/GlobalGasStepControllerConfig.h"

namespace SST { namespace SnnDL {

GlobalGasStepController::GlobalGasStepController(SST::ComponentId_t id, SST::Params& params)
    : SST::Component(id)
{
    const GlobalGasStepControllerConfig cfg = parseGlobalGasStepControllerConfig(params);
    verbose_ = cfg.verbose;
    out_ = new SST::Output("GlobalGasStepController[@p:@l]: ", verbose_, 0, SST::Output::STDOUT);

    clock_freq_ = params.find<std::string>("clock", "1GHz");
    start_seq_ = cfg.start_seq;
    max_steps_ = cfg.max_steps;
    require_all_ready_ = cfg.require_all_ready;
    strict_seq_check_ = cfg.strict_seq_check;
    experimental_progress_enable_ = cfg.experimental_progress_enable;
    experimental_progress_period_cycles_ = cfg.experimental_progress_period_cycles;
    experimental_progress_max_reports_ = cfg.experimental_progress_max_reports;
    experimental_progress_dump_first_n_ = cfg.experimental_progress_dump_first_n;
    credit_ctrl_enable_ = cfg.credit_ctrl_enable;
    credit_ctrl_credit_min_ = cfg.credit_ctrl_credit_min;
    credit_ctrl_credit_max_ = cfg.credit_ctrl_credit_max;
    credit_ctrl_top_k_ = cfg.credit_ctrl_top_k;
    credit_ctrl_mode_ = params.find<uint32_t>("credit_ctrl_mode", 0);
    credit_ctrl_base_credit_ = params.find<uint32_t>("credit_ctrl_base_credit", 0);
    credit_ctrl_apply_ratio_min_permille_ = params.find<uint32_t>("credit_ctrl_apply_ratio_min_permille", 0);
    credit_ctrl_rank_by_apply_ = params.find<int>("credit_ctrl_rank_by_apply", 1) != 0;
    credit_ctrl_pred_seed_ = params.find<uint64_t>("credit_ctrl_pred_seed", 0);
    credit_ctrl_pred_fraction_ = params.find<double>("credit_ctrl_pred_fraction", 0.0);
    credit_ctrl_pred_neurons_per_pe_ = params.find<uint32_t>("credit_ctrl_pred_neurons_per_pe", 0);
    credit_ctrl_pred_fanout_ = params.find<uint32_t>("credit_ctrl_pred_fanout", 0);
    gating_event_enable_ = cfg.gating_event_enable;
    gating_event_rows_per_pe_ = cfg.gating_event_rows_per_pe;
    gating_event_top_k_ = cfg.gating_event_top_k;
    gating_event_ttl_cycles_ = cfg.gating_event_ttl_cycles;
    gating_event_target_offset_ = cfg.gating_event_target_offset;
    gating_event_target_stride_ = cfg.gating_event_target_stride;
    gating_event_include_self_ = cfg.gating_event_include_self;
    if (credit_ctrl_pred_fraction_ < 0.0) credit_ctrl_pred_fraction_ = 0.0;
    if (credit_ctrl_credit_min_ == 0) credit_ctrl_credit_min_ = 1;
    if (credit_ctrl_credit_max_ < credit_ctrl_credit_min_) credit_ctrl_credit_max_ = credit_ctrl_credit_min_;
    if (!credit_ctrl_enable_) credit_ctrl_top_k_ = 0;
    if (credit_ctrl_base_credit_ == 0) credit_ctrl_base_credit_ = credit_ctrl_credit_min_;
    if (credit_ctrl_apply_ratio_min_permille_ > 1000u) credit_ctrl_apply_ratio_min_permille_ = 1000u;
    if (gating_event_target_stride_ == 0) gating_event_target_stride_ = 1;
    if (!gating_event_enable_) gating_event_top_k_ = 0;
    if (start_seq_ == 0) {
        if (strict_seq_check_) {
            if (out_) {
                out_->fatal(CALL_INFO, -1, "GlobalGasStepController fatal: start_seq=0 is invalid (expected >=1)\n");
            }
        } else {
            if (out_) {
                out_->verbose(CALL_INFO, 1, 0, "[step-warn] start_seq=0 invalid, clamp to 1\n");
            }
            ++warn_count_;
            start_seq_ = 1;
        }
    }

    // 仅在 step-limited 模式下注册为 primary，避免影响默认的 time-based stop-at 回归口径。
    primary_keepalive_ = (max_steps_ > 0);
    if (primary_keepalive_) {
        registerAsPrimaryComponent();
        primaryComponentDoNotEndSim();
    }

    // 端口向量：pe_link0, pe_link1, ...
    const std::string prefix = "pe_link";
    int idx = 0;
    std::string port = prefix + std::to_string(idx);
    while (isPortConnected(port)) {
        SST::Link* link =
            configureLink(port,
                          new SST::Event::Handler2<GlobalGasStepController, &GlobalGasStepController::handleBarrierEvent_, int>(this, idx));
        if (!link) {
            out_->fatal(CALL_INFO, -1, "GlobalGasStepController fatal: unable to configure link %s\n", port.c_str());
        }
        pe_links_.push_back(link);
        ++idx;
        port = prefix + std::to_string(idx);
    }

    const int first_gap = idx;
    if (first_gap > 0) {
        const int kGapProbe = 8;
        int found = -1;
        for (int probe = first_gap + 1; probe <= first_gap + kGapProbe; ++probe) {
            const std::string probe_port = prefix + std::to_string(probe);
            if (isPortConnected(probe_port)) {
                found = probe;
                break;
            }
        }
        if (found >= 0) {
            if (strict_seq_check_) {
                out_->fatal(CALL_INFO, -1,
                            "GlobalGasStepController fatal: port gap detected (pe_link%d missing, but pe_link%d connected)\n",
                            first_gap, found);
            } else {
                if (out_) {
                    out_->verbose(CALL_INFO, 1, 0,
                                  "[step-warn] port gap: pe_link%d missing while pe_link%d connected; higher ports ignored\n",
                                  first_gap, found);
                }
                ++warn_count_;
            }
        }
    }

    if (pe_links_.empty()) {
        out_->fatal(CALL_INFO, -1, "GlobalGasStepController fatal: no PE links connected (expected pe_link0..)\n");
    }
    pe_ready_.assign(pe_links_.size(), 0);
    pe_done_.assign(pe_links_.size(), 0);
    pe_step_total_ns_.assign(pe_links_.size(), 0);
    pe_step_apply_ns_.assign(pe_links_.size(), 0);
    pe_next_apply_bank_credit_.assign(
        pe_links_.size(),
        credit_ctrl_enable_
            ? (((credit_ctrl_mode_ == 1) || (credit_ctrl_mode_ == 2)) ? credit_ctrl_base_credit_ : credit_ctrl_credit_min_)
            : 0);
    pe_node_ids_.resize(pe_links_.size());
    for (size_t i = 0; i < pe_node_ids_.size(); ++i) {
        pe_node_ids_[i] = static_cast<uint32_t>(i);
    }

    stat_current_seq_last_ = registerStatistic<uint64_t>("current_seq_last");
    stat_steps_started_total_ = registerStatistic<uint64_t>("steps_started_total");
    stat_steps_completed_total_ = registerStatistic<uint64_t>("steps_completed_total");
    stat_pe_ready_events_total_ = registerStatistic<uint64_t>("pe_ready_events_total");
    stat_pe_done_events_total_ = registerStatistic<uint64_t>("pe_done_events_total");
    stat_warn_count_total_ = registerStatistic<uint64_t>("warn_count_total");
}

GlobalGasStepController::~GlobalGasStepController() {
    // SST 管理 Component 生命周期；Output 由 SST/进程退出统一回收（避免析构次序竞态）
    out_ = nullptr;
}

void GlobalGasStepController::init(unsigned int /*phase*/) {
    // Threading robustness:
    // - When running with multiple SST threads, this controller may be placed on a different thread than PEs.
    // - If the controller has no clock/self events, its thread can remain at time 0 and miss cross-thread barrier events.
    // - Register a lightweight clock to ensure the owning thread participates in time advancement.
    if (!clock_registered_) {
        registerClock(clock_freq_, new SST::Clock::Handler2<GlobalGasStepController, &GlobalGasStepController::clockTick_>(this));
        clock_registered_ = true;
    }
}

void GlobalGasStepController::setup() {
    // no-op
}

void GlobalGasStepController::finish() {
    if (stat_current_seq_last_) stat_current_seq_last_->addData(static_cast<uint64_t>(current_seq_));
    if (stat_steps_started_total_) stat_steps_started_total_->addData(steps_started_total_);
    if (stat_steps_completed_total_) stat_steps_completed_total_->addData(static_cast<uint64_t>(steps_completed_));
    if (stat_pe_ready_events_total_) stat_pe_ready_events_total_->addData(pe_ready_events_total_);
    if (stat_pe_done_events_total_) stat_pe_done_events_total_->addData(pe_done_events_total_);
    if (stat_warn_count_total_) stat_warn_count_total_->addData(static_cast<uint64_t>(warn_count_));
    if (!out_) return;
    size_t ready = 0;
    size_t done = 0;
    for (auto v : pe_ready_) if (v) ++ready;
    for (auto v : pe_done_) if (v) ++done;
    if (warn_count_ > 0) {
        out_->verbose(
            CALL_INFO, 0, 0,
            "[step-warn] finish: warn_count=%u started=%d current_seq=%u max_steps=%u completed=%u ready=%zu/%zu done=%zu/%zu\n",
            warn_count_,
            started_ ? 1 : 0,
            current_seq_,
            max_steps_,
            steps_completed_,
            ready,
            pe_ready_.size(),
            done,
            pe_done_.size());
        return;
    }
    out_->verbose(
        CALL_INFO, 1, 0,
        "[step-sync] finish: started=%d current_seq=%u max_steps=%u completed=%u ready=%zu/%zu done=%zu/%zu\n",
        started_ ? 1 : 0,
        current_seq_,
        max_steps_,
        steps_completed_,
        ready,
        pe_ready_.size(),
        done,
        pe_done_.size());
}

bool GlobalGasStepController::allReady_() const {
    for (auto v : pe_ready_) if (!v) return false;
    return true;
}

bool GlobalGasStepController::allDone_() const {
    for (auto v : pe_done_) if (!v) return false;
    return true;
}

void GlobalGasStepController::broadcastStart_(uint32_t seq) {
    steps_started_total_ += 1;
    for (size_t i = 0; i < pe_links_.size(); ++i) {
        auto* ev = new GasStepBarrierEvent(GasStepBarrierOp::StartStep, seq, /*src_node*/0);
        if (credit_ctrl_enable_ &&
            i < pe_next_apply_bank_credit_.size() &&
            pe_next_apply_bank_credit_[i] != 0) {
            ev->apply_bank_credit_target = pe_next_apply_bank_credit_[i];
        }
        pe_links_[i]->send(ev);
    }
    broadcastSyntheticGating_(seq);
    if (out_) {
        out_->verbose(CALL_INFO, 1, 0, "[step-sync] START_STEP seq=%u broadcast to %zu PEs\n", seq, pe_links_.size());
    }
}

void GlobalGasStepController::broadcastSyntheticGating_(uint32_t seq) {
    if (!gating_event_enable_ || gating_event_top_k_ == 0 || pe_links_.empty()) return;

    const size_t pe_count = pe_links_.size();
    const uint32_t rows_per_pe = (gating_event_rows_per_pe_ > 0) ? gating_event_rows_per_pe_ : 1u;
    const uint64_t ttl_cycles = (gating_event_ttl_cycles_ > 0) ? gating_event_ttl_cycles_ : 1ull;

    for (size_t pe_index = 0; pe_index < pe_count; ++pe_index) {
        const uint32_t src_pe =
            (pe_index < pe_node_ids_.size()) ? pe_node_ids_[pe_index] : static_cast<uint32_t>(pe_index);

        std::set<uint32_t> unique_targets;
        std::vector<uint32_t> dest_pes;
        dest_pes.reserve(static_cast<size_t>(gating_event_top_k_));
        for (size_t probe = 0; probe < pe_count && dest_pes.size() < gating_event_top_k_; ++probe) {
            const size_t candidate_index =
                (pe_index + static_cast<size_t>(gating_event_target_offset_) +
                 probe * static_cast<size_t>(gating_event_target_stride_)) % pe_count;
            if (!gating_event_include_self_ && candidate_index == pe_index) continue;
            const uint32_t candidate_pe =
                (candidate_index < pe_node_ids_.size())
                    ? pe_node_ids_[candidate_index]
                    : static_cast<uint32_t>(candidate_index);
            if (!unique_targets.insert(candidate_pe).second) continue;
            dest_pes.push_back(candidate_pe);
        }
        if (dest_pes.empty()) continue;

        for (uint32_t row = 0; row < rows_per_pe; ++row) {
            auto* ev = new GatingDecisionEvent();
            ev->token_id = (seq << 16) ^ row;
            ev->src_pe = src_pe;
            ev->src_row = row;
            ev->top_k = static_cast<uint32_t>(dest_pes.size());
            ev->ttl_cycles = ttl_cycles;
            ev->dest_pes = dest_pes;
            pe_links_[pe_index]->send(ev);
        }
    }
}

void GlobalGasStepController::handleBarrierEvent_(SST::Event* ev, int pe_index) {
    auto* msg = dynamic_cast<GasStepBarrierEvent*>(ev);
    if (!msg) {
        delete ev;
        return;
    }
    if (pe_index < 0 || static_cast<size_t>(pe_index) >= pe_links_.size()) {
        delete msg;
        return;
    }

    const GasStepBarrierOp op = msg->operation();
    const uint32_t seq = msg->seq;
    const uint32_t src_node = msg->src_node;

    if (op == GasStepBarrierOp::PeReady) {
        pe_ready_events_total_ += 1;
        pe_ready_[pe_index] = 1;
        if (static_cast<size_t>(pe_index) < pe_node_ids_.size()) {
            pe_node_ids_[static_cast<size_t>(pe_index)] = src_node;
        }
        if (out_) {
            out_->verbose(CALL_INFO, 2, 0, "[step-sync] PE_READY pe=%d src_node=%u\n", pe_index, src_node);
        }
        if (!started_ && (!require_all_ready_ || allReady_())) {
            started_ = true;
            current_seq_ = start_seq_;
            pe_done_.assign(pe_links_.size(), 0);
            broadcastStart_(current_seq_);
        }
        delete msg;
        return;
    }

    if (op == GasStepBarrierOp::PeDone) {
        pe_done_events_total_ += 1;
        if (!started_) {
            if (strict_seq_check_) {
                if (out_) out_->fatal(CALL_INFO, -1, "GlobalGasStepController fatal: PE_DONE before started (pe=%d)\n", pe_index);
            } else {
                if (out_) {
                    out_->verbose(CALL_INFO, 1, 0,
                                  "[step-warn] PE_DONE before started ignored (pe=%d src_node=%u seq=%u)\n",
                                  pe_index, src_node, seq);
                }
                ++warn_count_;
            }
            delete msg;
            return;
        }
        if (seq != current_seq_) {
            if (strict_seq_check_) {
                if (out_) out_->fatal(
                    CALL_INFO, -1,
                    "GlobalGasStepController fatal: unexpected PE_DONE seq=%u current_seq=%u (pe=%d src_node=%u)\n",
                    seq, current_seq_, pe_index, src_node);
            } else {
                if (out_) out_->verbose(
                    CALL_INFO, 1, 0,
                    "[step-warn] unexpected PE_DONE seq=%u current_seq=%u (pe=%d src_node=%u) ignored\n",
                    seq, current_seq_, pe_index, src_node);
                ++warn_count_;
            }
            delete msg;
            return;
        }
        pe_done_[pe_index] = 1;
        if (static_cast<size_t>(pe_index) < pe_node_ids_.size()) {
            pe_node_ids_[static_cast<size_t>(pe_index)] = src_node;
        }
        if (credit_ctrl_enable_) {
            if (static_cast<size_t>(pe_index) < pe_step_total_ns_.size()) pe_step_total_ns_[static_cast<size_t>(pe_index)] = msg->step_total_ns;
            if (static_cast<size_t>(pe_index) < pe_step_apply_ns_.size()) pe_step_apply_ns_[static_cast<size_t>(pe_index)] = msg->step_apply_ns;
        }
        if (out_) {
            out_->verbose(CALL_INFO, 3, 0, "[step-sync] PE_DONE seq=%u pe=%d src_node=%u\n", seq, pe_index, src_node);
        }
        if (allDone_()) {
            steps_completed_ += 1;
            if (max_steps_ > 0 && steps_completed_ >= max_steps_) {
                if (out_) {
                    out_->verbose(CALL_INFO, 1, 0,
                                  "[step-sync] reached max_steps=%u (completed=%u), stopping\n",
                                  max_steps_, steps_completed_);
                }
                if (primary_keepalive_) {
                    primaryComponentOKToEndSim();
                }
                delete msg;
                return;
            }

            if (credit_ctrl_enable_ && credit_ctrl_top_k_ > 0) {
                computeNextCredits_(current_seq_);
                std::fill(pe_step_total_ns_.begin(), pe_step_total_ns_.end(), 0);
                std::fill(pe_step_apply_ns_.begin(), pe_step_apply_ns_.end(), 0);
            }

            ++current_seq_;
            pe_done_.assign(pe_links_.size(), 0);
            broadcastStart_(current_seq_);
        }
        delete msg;
        return;
    }

    // StartStep 不应从 PE 侧回送
    if (op == GasStepBarrierOp::StartStep) {
        if (strict_seq_check_ && out_) {
            out_->fatal(CALL_INFO, -1, "GlobalGasStepController fatal: unexpected START_STEP from PE (pe=%d)\n", pe_index);
        } else {
            if (out_) {
                out_->verbose(CALL_INFO, 1, 0,
                              "[step-warn] unexpected START_STEP from PE ignored (pe=%d src_node=%u seq=%u)\n",
                              pe_index, src_node, seq);
            }
            ++warn_count_;
        }
        delete msg;
        return;
    }

    delete msg;
}

bool GlobalGasStepController::clockTick_(SST::Cycle_t cycle) {
    if (experimental_progress_enable_ &&
        experimental_progress_period_cycles_ > 0 &&
        (experimental_progress_max_reports_ == 0 || experimental_progress_reports_ < experimental_progress_max_reports_)) {
        if (cycle > 0 && (cycle % static_cast<SST::Cycle_t>(experimental_progress_period_cycles_)) == 0) {
            size_t ready = 0;
            size_t done = 0;
            for (auto v : pe_ready_) if (v) ++ready;
            for (auto v : pe_done_) if (v) ++done;

            std::string missing;
            if (started_ && done < pe_done_.size() && experimental_progress_dump_first_n_ > 0) {
                uint32_t dumped = 0;
                missing.reserve(64);
                missing.push_back('[');
                for (size_t i = 0; i < pe_done_.size() && dumped < experimental_progress_dump_first_n_; ++i) {
                    if (pe_done_[i]) continue;
                    const uint32_t node_id =
                        (i < pe_node_ids_.size()) ? pe_node_ids_[i] : static_cast<uint32_t>(i);
                    if (dumped > 0) missing.append(",");
                    missing.append(std::to_string(node_id));
                    ++dumped;
                }
                missing.push_back(']');
            }

            if (out_) {
                out_->verbose(
                    CALL_INFO, 0, 0,
                    "[exp-step-progress] cycle=%" PRIu64 " started=%d current_seq=%u max_steps=%u completed=%u ready=%zu/%zu done=%zu/%zu missing_first=%s\n",
                    (uint64_t)cycle,
                    started_ ? 1 : 0,
                    current_seq_,
                    max_steps_,
                    steps_completed_,
                    ready,
                    pe_ready_.size(),
                    done,
                    pe_done_.size(),
                    missing.empty() ? "[]" : missing.c_str());
            }
            experimental_progress_reports_++;
        }
    }
    // keep ticking
    return false;
}

void GlobalGasStepController::computeNextCredits_(uint32_t completed_seq) {
    if (!credit_ctrl_enable_ || credit_ctrl_top_k_ == 0) return;
    const size_t n = pe_links_.size();
    if (n == 0) return;

    if (credit_ctrl_mode_ == 2) {
        StepActivationPredictorConfig pcfg{};
        pcfg.seed = credit_ctrl_pred_seed_;
        pcfg.fraction = credit_ctrl_pred_fraction_;
        pcfg.neurons_per_pe = credit_ctrl_pred_neurons_per_pe_;
        pcfg.fanout = credit_ctrl_pred_fanout_;

        const uint32_t base = credit_ctrl_base_credit_ ? credit_ctrl_base_credit_ : credit_ctrl_credit_min_;
        const uint32_t lo = (credit_ctrl_credit_min_ > base) ? base : credit_ctrl_credit_min_;
        const uint32_t hi = (credit_ctrl_credit_max_ < base) ? base : credit_ctrl_credit_max_;

        if (pe_next_apply_bank_credit_.size() != n) {
            pe_next_apply_bank_credit_.assign(n, base);
        } else {
            std::fill(pe_next_apply_bank_credit_.begin(), pe_next_apply_bank_credit_.end(), base);
        }

        if (credit_ctrl_top_k_ == 0 || hi == base) {
            return;
        }

        const uint32_t next_seq = completed_seq + 1u;
        std::vector<uint64_t> pred_sources(n, 0);
        uint64_t max_pred = 0;
        uint64_t sum_pred = 0;
        for (size_t i = 0; i < n; ++i) {
            const uint32_t node_id =
                (i < pe_node_ids_.size()) ? pe_node_ids_[i] : static_cast<uint32_t>(i);
            const uint64_t s = predictStepActivationSourcesSelected(next_seq, node_id, pcfg);
            pred_sources[i] = s;
            sum_pred += s;
            if (s > max_pred) max_pred = s;
        }
        if (max_pred == 0) {
            return;
        }

        struct Item { uint64_t metric = 0; int idx = -1; };
        std::vector<Item> raise_cands;
        raise_cands.reserve(n);
        for (size_t i = 0; i < n; ++i) {
            const uint64_t m = pred_sources[i];
            if (m == 0) continue;
            raise_cands.push_back(Item{m, static_cast<int>(i)});
        }
        std::sort(raise_cands.begin(), raise_cands.end(),
                  [](const Item& a, const Item& b){
                      if (a.metric != b.metric) return a.metric > b.metric;
                      return a.idx < b.idx;
                  });

        const uint32_t k_raise =
            std::min<uint32_t>(credit_ctrl_top_k_, static_cast<uint32_t>(raise_cands.size()));

        std::vector<uint8_t> is_raised(n, 0);
        std::vector<int> raised_list;
        raised_list.reserve(k_raise);
        for (uint32_t j = 0; j < k_raise; ++j) {
            const int idx = raise_cands[j].idx;
            if (idx < 0 || static_cast<size_t>(idx) >= n) continue;
            is_raised[static_cast<size_t>(idx)] = 1;
            raised_list.push_back(idx);
            pe_next_apply_bank_credit_[static_cast<size_t>(idx)] = hi;
        }

        const uint64_t budget_target = static_cast<uint64_t>(n) * static_cast<uint64_t>(base);
        uint64_t budget_actual = 0;
        for (auto c : pe_next_apply_bank_credit_) budget_actual += static_cast<uint64_t>(c);
        int64_t extra = static_cast<int64_t>(budget_actual) - static_cast<int64_t>(budget_target);

        auto apply_drop = [&](int idx, uint32_t floor) {
            if (extra <= 0) return;
            if (idx < 0 || static_cast<size_t>(idx) >= n) return;
            const uint32_t cur = pe_next_apply_bank_credit_[static_cast<size_t>(idx)];
            if (cur <= floor) return;
            const uint32_t cap = cur - floor;
            const uint32_t d = std::min<uint32_t>(cap, static_cast<uint32_t>(extra));
            pe_next_apply_bank_credit_[static_cast<size_t>(idx)] = cur - d;
            extra -= static_cast<int64_t>(d);
        };

        if (extra > 0) {
            // Drop candidates: lowest predicted-load PEs excluding raised (metric=0 is meaningful here).
            std::vector<Item> drop_cands;
            drop_cands.reserve(n);
            for (size_t i = 0; i < n; ++i) {
                if (is_raised[i]) continue;
                drop_cands.push_back(Item{pred_sources[i], static_cast<int>(i)});
            }
            std::sort(drop_cands.begin(), drop_cands.end(),
                      [](const Item& a, const Item& b){
                          if (a.metric != b.metric) return a.metric < b.metric;
                          return a.idx < b.idx;
                      });

            for (const auto& it : drop_cands) {
                if (extra <= 0) break;
                apply_drop(it.idx, lo);
            }
            // If still over budget, retract some raised credits back toward base.
            for (auto it = raised_list.rbegin(); it != raised_list.rend(); ++it) {
                if (extra <= 0) break;
                apply_drop(*it, base);
            }
        }

        if (out_ && verbose_ >= 2) {
            uint64_t sum = 0;
            for (auto c : pe_next_apply_bank_credit_) sum += static_cast<uint64_t>(c);
            out_->verbose(
                CALL_INFO, 2, 0,
                "[credit-ctrl:p0c] completed_seq=%u next_seq=%u top_k=%u credit=(lo=%u,base=%u,hi=%u) pred=(sum=%" PRIu64 ",max=%" PRIu64 ") budget=%" PRIu64 " actual=%" PRIu64 "\n",
                completed_seq,
                next_seq,
                (unsigned)k_raise,
                (unsigned)lo,
                (unsigned)base,
                (unsigned)hi,
                (uint64_t)sum_pred,
                (uint64_t)max_pred,
                (uint64_t)budget_target,
                (uint64_t)sum);
        }
        return;
    }

    if (credit_ctrl_mode_ == 1) {
        P0BCreditPolicyConfig pcfg{};
        pcfg.base_credit = credit_ctrl_base_credit_;
        pcfg.credit_lo = credit_ctrl_credit_min_;
        pcfg.credit_hi = credit_ctrl_credit_max_;
        pcfg.top_k = credit_ctrl_top_k_;
        pcfg.apply_ratio_min_permille = credit_ctrl_apply_ratio_min_permille_;
        pcfg.rank_by_apply = credit_ctrl_rank_by_apply_;

        P0BCreditPolicyDebug dbg{};
        P0BCreditPolicyDebug* dbg_ptr = (out_ && verbose_ >= 3) ? &dbg : nullptr;
        std::vector<uint32_t> next =
            computeP0BBudgetedCredits(pe_step_total_ns_, pe_step_apply_ns_, pcfg, dbg_ptr);
        if (next.size() == n) {
            pe_next_apply_bank_credit_ = std::move(next);
        } else {
            pe_next_apply_bank_credit_.assign(n, pcfg.base_credit ? pcfg.base_credit : credit_ctrl_credit_min_);
        }
        if (out_ && verbose_ >= 2) {
            const uint64_t budget_target =
                static_cast<uint64_t>(n) * static_cast<uint64_t>(pcfg.base_credit ? pcfg.base_credit : 1u);
            uint64_t budget_actual = 0;
            for (auto c : pe_next_apply_bank_credit_) budget_actual += static_cast<uint64_t>(c);
            out_->verbose(
                CALL_INFO, 2, 0,
                "[credit-ctrl:p0b] completed_seq=%u next_seq=%u top_k=%u credit=(lo=%u,base=%u,hi=%u) budget=%" PRIu64 " actual=%" PRIu64 "\n",
                completed_seq, completed_seq + 1u,
                (unsigned)credit_ctrl_top_k_,
                (unsigned)pcfg.credit_lo,
                (unsigned)pcfg.base_credit,
                (unsigned)pcfg.credit_hi,
                (uint64_t)budget_target,
                (uint64_t)budget_actual);
            if (dbg_ptr) {
                out_->verbose(
                    CALL_INFO, 3, 0,
                    "[credit-ctrl:p0b] raised=%zu dropped_cands=%zu rank_by_apply=%u apply_ratio_min_permille=%u\n",
                    dbg.raised_pe_indices.size(),
                    dbg.dropped_pe_indices.size(),
                    (unsigned)(pcfg.rank_by_apply ? 1u : 0u),
                    (unsigned)pcfg.apply_ratio_min_permille);
            }
        }
        return;
    }

    // Default (legacy): all PEs use credit_min.
    if (pe_next_apply_bank_credit_.size() != n) {
        pe_next_apply_bank_credit_.assign(n, credit_ctrl_credit_min_);
    } else {
        std::fill(pe_next_apply_bank_credit_.begin(), pe_next_apply_bank_credit_.end(), credit_ctrl_credit_min_);
    }

    struct Item { uint64_t total_ns = 0; int idx = -1; };
    std::vector<Item> rank;
    rank.reserve(n);
    for (size_t i = 0; i < n; ++i) {
        const uint64_t t = (i < pe_step_total_ns_.size()) ? pe_step_total_ns_[i] : 0;
        if (t == 0) continue; // missing telemetry; keep credit_min
        rank.push_back(Item{t, static_cast<int>(i)});
    }
    std::sort(rank.begin(), rank.end(),
              [](const Item& a, const Item& b){
                  if (a.total_ns != b.total_ns) return a.total_ns > b.total_ns;
                  return a.idx < b.idx;
              });

    const uint32_t k = std::min<uint32_t>(credit_ctrl_top_k_, static_cast<uint32_t>(rank.size()));
    for (uint32_t j = 0; j < k; ++j) {
        const int idx = rank[j].idx;
        if (idx < 0 || static_cast<size_t>(idx) >= n) continue;
        pe_next_apply_bank_credit_[static_cast<size_t>(idx)] = credit_ctrl_credit_max_;
    }

    if (out_ && verbose_ >= 2) {
        uint64_t max_total = 0;
        if (!rank.empty()) max_total = rank.front().total_ns;
        out_->verbose(
            CALL_INFO, 2, 0,
            "[credit-ctrl] completed_seq=%u next_seq=%u top_k=%u credit=(min=%u,max=%u) max_total_ns=%" PRIu64 "\n",
            completed_seq, completed_seq + 1u,
            (unsigned)k,
            credit_ctrl_credit_min_,
            credit_ctrl_credit_max_,
            (uint64_t)max_total);
    }
}

}} // namespace SST::SnnDL
