// Minimal skeleton for GAS phase orchestration controller (mirror-only for CP4 Step2~4).
#ifndef SST_ELEMENTS_SNNDL_GAS_PHASE_CONTROLLER_H
#define SST_ELEMENTS_SNNDL_GAS_PHASE_CONTROLLER_H

#include <cstdint>
#include <inttypes.h>
#include <string>
#include <sst/core/output.h>

namespace SST { namespace SnnDL {

class IGasOrchestrator; // fwd

class GasPhaseController {
public:
    GasPhaseController() = default;

    void init(IGasOrchestrator* orchestrator, Output* out) { orchestrator_ = orchestrator; out_ = out; }
    void setDebug(bool window_read_debug, bool extended_diag) {
        window_read_debug_ = window_read_debug; extended_diag_ = extended_diag;
    }
    void setStageEventsCsv(const std::string& path) { stage_events_csv_ = path; }

    // Stage events mirror (no behavior change)
    void onBeginGather(uint32_t seq) { log_("BeginGather", seq, 0); }
    void onBeginApply(uint32_t seq)  { log_("BeginApply",  seq, 0); }
    void onBeginScatter(uint32_t seq){ log_("BeginScatter",seq, 0); }
    void onEndScatter(uint32_t seq, uint64_t spikes_emitted) {
        log_("EndScatter", seq, spikes_emitted);
    }

    // CP4 Step3/4 facades (delegate to core orchestrate wrappers)
    void beginApplyFullSequence(bool strict_active);
    void beginScatterSequence();
    void endScatterSequence();

private:
    void log_(const char* ev, uint32_t seq, uint64_t spikes) const {
        if (!out_) return;
        if (!window_read_debug_ && out_->getVerboseLevel() < 1) return;
        out_->verbose(CALL_INFO, 3, 0,
            "[gas-ctrl] ev=%s seq=%u spikes=%" PRIu64 "\n", ev?ev:"-", seq, spikes);
    }

    IGasOrchestrator* orchestrator_ = nullptr;
    Output* out_ = nullptr;
    bool window_read_debug_ = false;
    bool extended_diag_ = false;
    std::string stage_events_csv_;
};

}} // namespace

#endif
