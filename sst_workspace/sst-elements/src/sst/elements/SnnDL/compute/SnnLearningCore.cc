#include "SnnLearningCore.h"

#include <cmath>
#include <fstream>
#include <sstream>

namespace SST { namespace SnnDL {

void DefaultLearningCore::configure(uint32_t core_id,
                                   uint32_t node_id,
                                   uint32_t num_neurons,
                                   uint64_t global_neuron_base,
                                   uint32_t weights_cols,
                                   bool use_post_row_pre_col,
                                   float v_thresh,
                                   SST::Output* log,
                                   const SST::Params& params,
                                   LearningWritebackFn writeback_fn) {
    core_id_ = core_id;
    node_id_ = node_id;
    num_neurons_ = num_neurons;
    global_neuron_base_ = global_neuron_base;
    weights_cols_ = weights_cols ? weights_cols : num_neurons;
    use_post_row_pre_col_ = use_post_row_pre_col;
    v_thresh_ = v_thresh;
    output_ = log;
    writeback_fn_ = std::move(writeback_fn);

    learning_enabled_      = params.find<int>("learning_enabled", 0) != 0;
    learn_window_cycles_   = params.find<uint64_t>("learn_window_cycles", 1000);
    record_membrane_       = params.find<int>("record_membrane", 0) != 0;
    record_spike_times_    = params.find<int>("record_spike_times", 1) != 0;
    surrogate_type_        = params.find<std::string>("surrogate_type", "superspike");
    surrogate_beta_        = params.find<float>("surrogate_beta", 5.0f);
    error_file_template_   = params.find<std::string>("error_file", "");
    grad_accum_limit_      = static_cast<size_t>(params.find<uint32_t>("grad_accum_limit", 0));
    apply_writeback_       = params.find<int>("apply_writeback", 0) != 0;
    apply_every_n_windows_ = params.find<uint32_t>("apply_every_n_windows", 1);
    learning_rate_         = params.find<float>("learning_rate", 0.001f);
    weight_decay_          = params.find<float>("weight_decay", 0.0f);

    current_window_index_ = 0;
    error_buffer_.clear();
    local_grad_.clear();
    spike_history_.clear();

    if (learning_enabled_) {
        error_buffer_.assign(num_neurons_, 0.0f);
    }
}

void DefaultLearningCore::onClockTick(uint64_t now_cycle) {
    if (!(learning_enabled_ && learn_window_cycles_ > 0)) return;
    const uint64_t win_idx = now_cycle / learn_window_cycles_;
    if (now_cycle == 1 || win_idx != current_window_index_) {
        onWindowBoundary_(win_idx);
        current_window_index_ = win_idx;
    }
}

void DefaultLearningCore::onSynapticEvent(const LearningSynapticEvent& ev) {
    if (!learning_enabled_) return;
    if (ev.post_local >= num_neurons_) return;
    const float err = (ev.post_local < error_buffer_.size()) ? error_buffer_[ev.post_local] : 0.0f;
    if (err == 0.0f) return;

    const float sgrad = computeSurrogateGrad_(ev.v_after);
    const float contrib = err * sgrad;
    uint64_t key = 0;
    if (resolveWeightKey_(ev.pre_global, ev.post_local, key)) {
        local_grad_[key] += contrib;
    }
    if (grad_accum_limit_ > 0 && local_grad_.size() > grad_accum_limit_) {
        local_grad_.clear();
    }
}

void DefaultLearningCore::onNeuronFired(uint32_t neuron_idx, uint64_t now_cycle, float v_before) {
    if (!(learning_enabled_ && record_spike_times_)) return;
    uint32_t gid = static_cast<uint32_t>(global_neuron_base_ + static_cast<uint64_t>(neuron_idx));
    float v_fire = record_membrane_ ? v_before : 0.0f;
    spike_history_.push_back(SpikeRecord{gid, now_cycle, v_fire});
}

void DefaultLearningCore::getStatistics(std::map<std::string, uint64_t>& out) const {
    out["learning_enabled"] = learning_enabled_ ? 1ULL : 0ULL;
    out["learning_window_index"] = current_window_index_;
    out["learning_grad_entries"] = static_cast<uint64_t>(local_grad_.size());
    out["learning_spike_records"] = static_cast<uint64_t>(spike_history_.size());
}

float DefaultLearningCore::computeSurrogateGrad_(float v_mem) const {
    // Only superspike for now: 1 / (1 + |beta*(v-vth)|)^2
    const float x = surrogate_beta_ * (v_mem - v_thresh_);
    const float ax = std::fabs(x);
    const float denom = 1.0f + ax * ax;
    return 1.0f / denom;
}

bool DefaultLearningCore::resolveWeightKey_(uint32_t pre_global, uint32_t post_local, uint64_t& key) const {
    if (post_local >= num_neurons_) return false;
    if (use_post_row_pre_col_) {
        if (pre_global >= weights_cols_) return false;
        key = static_cast<uint64_t>(post_local) * static_cast<uint64_t>(weights_cols_)
            + static_cast<uint64_t>(pre_global);
        return true;
    }
    if (pre_global < global_neuron_base_ ||
        pre_global >= global_neuron_base_ + static_cast<uint64_t>(num_neurons_)) {
        return false;
    }
    uint32_t pre_local = static_cast<uint32_t>(pre_global - global_neuron_base_);
    key = static_cast<uint64_t>(pre_local) * static_cast<uint64_t>(num_neurons_)
        + static_cast<uint64_t>(post_local);
    return true;
}

std::string DefaultLearningCore::replacePlaceholders_(std::string s, uint64_t window_idx) const {
    auto repl = [&](const std::string& key, const std::string& val){
        size_t p = 0;
        while ((p = s.find(key, p)) != std::string::npos) {
            s.replace(p, key.size(), val);
            p += val.size();
        }
    };
    repl("{node}", std::to_string(node_id_));
    repl("{core}", std::to_string(core_id_));
    repl("{pe}", std::to_string(node_id_));
    repl("{win}", std::to_string(window_idx));
    return s;
}

void DefaultLearningCore::loadErrorsForWindow_(uint64_t window_idx) {
    if (!learning_enabled_) return;
    if (error_file_template_.empty()) {
        if (error_buffer_.size() != num_neurons_) {
            error_buffer_.assign(num_neurons_, 0.0f);
        } else {
            std::fill(error_buffer_.begin(), error_buffer_.end(), 0.0f);
        }
        return;
    }

    std::string path = replacePlaceholders_(error_file_template_, window_idx);
    std::ifstream fin(path);
    if (!fin.good()) {
        if (output_) {
            output_->verbose(CALL_INFO, 1, 0,
                "⚠️ 学习: 无法打开误差文件 %s, 本窗使用0误差\n", path.c_str());
        }
        if (error_buffer_.size() != num_neurons_) error_buffer_.assign(num_neurons_, 0.0f);
        else std::fill(error_buffer_.begin(), error_buffer_.end(), 0.0f);
        return;
    }

    std::vector<float> tmp(num_neurons_, 0.0f);
    std::string line;
    uint32_t line_idx = 0;
    while (std::getline(fin, line)) {
        if (line.empty() || line[0] == '#') continue;
        std::istringstream iss(line);
        uint32_t id = UINT32_MAX; float val = 0.0f;
        if ((iss >> id >> val)) {
            if (id < num_neurons_) tmp[id] = val;
        } else {
            iss.clear(); iss.str(line);
            if (iss >> val) {
                if (line_idx < num_neurons_) tmp[line_idx] = val;
                line_idx++;
            }
        }
    }
    error_buffer_.swap(tmp);
}

void DefaultLearningCore::onWindowBoundary_(uint64_t window_idx) {
    loadErrorsForWindow_(window_idx);
    if (grad_accum_limit_ > 0 && local_grad_.size() > grad_accum_limit_) {
        local_grad_.clear();
    }

    if (apply_writeback_ && apply_every_n_windows_ > 0 &&
        (window_idx % apply_every_n_windows_ == 0)) {
        if (writeback_fn_) {
            bool ok = writeback_fn_(local_grad_, learning_rate_, weight_decay_);
            if (ok) local_grad_.clear();
        } else if (output_) {
            output_->verbose(CALL_INFO, 1, 0,
                "⚠️ 学习: 写回启用但未提供 writeback_fn，跳过本窗写回\n");
        }
    }
}

}} // namespace SST::SnnDL

