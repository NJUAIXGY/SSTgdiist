#include "GasPhaseController.h"
#include "IGasOrchestrator.h"

using namespace SST::SnnDL;

void GasPhaseController::beginApplyFullSequence(bool strict_active) {
    if (!orchestrator_) return;
    orchestrator_->orchestratePrepareApplyWindow();
    orchestrator_->orchestrateApplyWindowEntry();
    orchestrator_->orchestrateBeginApplyIssueFallback(strict_active);
}

void GasPhaseController::beginScatterSequence() {
    if (!orchestrator_) return;
    orchestrator_->orchestrateBeginScatterSequence();
}

void GasPhaseController::endScatterSequence() {
    if (!orchestrator_) return;
    orchestrator_->orchestrateEndScatterSequence();
}
