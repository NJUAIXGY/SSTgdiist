// -*- c++ -*-
//
// GlobalStepDrainDecision.h:
// 全局 step drain done policy 的纯逻辑判定。
// 目的：把 stage mirror + hasWork 的组合语义从 MultiCorePE::clockTick() 中抽离出来，
// 便于单测覆盖“bg_only 慢核导致 PE_DONE 早发”的回归用例。
//

#pragma once

#include <cstddef>
#include <vector>

namespace SST {
namespace SnnDL {

struct GlobalStepDrainCoreState {
    int stage_code = 0;   // 0=none, 1=BeginGather, 2=BeginApply, 3=EndApply, 4=BeginScatter, 5=EndScatter
    bool has_work = false;
};

struct GlobalStepDrainInputs {
    bool injected = false;
    bool noc_idle = true;
    bool stage_arrays_ready = false;
    std::vector<GlobalStepDrainCoreState> cores{};
};

struct GlobalStepDrainDecision {
    bool active = false;
    bool uses_stage_events = false;
    bool all_end_scatter = false;
    bool hold_for_gather_completion = false;
    int stage_progress_cores = 0;
    int stage_done_cores = 0;
    int stage_bg_only_cores = 0;
    int stage_begin_apply_cores = 0;
    int stage_end_apply_cores = 0;
    int stage_begin_scatter_cores = 0;
    int stage_end_scatter_cores = 0;
    int fallback_busy_cores = 0;
};

inline GlobalStepDrainDecision evaluateGlobalStepDrainDecision(const GlobalStepDrainInputs& in) {
    GlobalStepDrainDecision out{};
    if (!in.injected) out.active = true;
    if (!in.noc_idle) out.active = true;

    if (!in.stage_arrays_ready) {
        for (const auto& core : in.cores) {
            if (core.has_work) {
                out.fallback_busy_cores += 1;
                out.active = true;
            }
        }
        return out;
    }

    for (const auto& core : in.cores) {
        const int stage_code = core.stage_code;

        if (stage_code == 2) {
            out.stage_begin_apply_cores += 1;
        } else if (stage_code == 3) {
            out.stage_end_apply_cores += 1;
        } else if (stage_code == 4) {
            out.stage_begin_scatter_cores += 1;
        } else if (stage_code == 5) {
            out.stage_end_scatter_cores += 1;
        }

        if (stage_code >= 2) {
            out.uses_stage_events = true;
            out.stage_progress_cores += 1;
            if (stage_code == 5) {
                out.stage_done_cores += 1;
                if (core.has_work) {
                    out.fallback_busy_cores += 1;
                    out.active = true;
                }
            } else {
                out.active = true;
            }
            continue;
        }

        if (stage_code == 1) {
            out.stage_bg_only_cores += 1;
        }
        if (core.has_work) {
            out.fallback_busy_cores += 1;
            out.active = true;
        }
    }

    out.all_end_scatter =
        out.uses_stage_events && (out.stage_done_cores == out.stage_progress_cores);

    // 关键修复：
    // 只要仍有 core 停留在 BeginGather，就不能认为这个 PE 已经完成了 step。
    // 否则会出现“部分 core 迟到进入 Apply/EndScatter，但 controller 已广播下一步”的早发 PE_DONE。
    out.hold_for_gather_completion = in.stage_arrays_ready && (out.stage_bg_only_cores > 0);
    if (out.hold_for_gather_completion) {
        out.active = true;
    }

    return out;
}

} // namespace SnnDL
} // namespace SST
