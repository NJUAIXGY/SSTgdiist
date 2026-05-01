// Minimal standalone unit test for SnnNeuronModel.h (LIF/Izhikevich/AdEx)
// - No SST runtime needed, only header includes
// - Generates CSV traces for v_mem over time under simple input schedules

#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <vector>
#include <string>
#include <iostream>
#include <fstream>

#include "SnnNeuronModel.h"

using namespace SST::SnnDL;

struct State {
    float v_mem = 0.0f;
    uint32_t refractory_timer = 0;
};

struct TracePoint { int step; float v; };

static void write_csv(const std::string& path, const std::vector<TracePoint>& tr,
                      const std::string& header) {
    std::ofstream ofs(path);
    ofs << "# " << header << "\n";
    ofs << "step,v_mem\n";
    for (auto& tp : tr) ofs << tp.step << "," << tp.v << "\n";
}

static std::vector<TracePoint> run_model(INeuronModel& model, const ModelConfig& cfg, SST::Params& params,
                                         float v0, int steps, int inject_steps, float event_w) {
    std::vector<State> neurons(1);
    neurons[0].v_mem = v0;
    model.init(1, cfg, params);

    std::vector<TracePoint> tr; tr.reserve(steps);
    for (int t = 0; t < steps; ++t) {
        if (t < inject_steps) {
            model.onSynapticEvent(0, event_w, neurons[0]);
        }
        model.tickIdx(0, neurons[0].v_mem, neurons[0].refractory_timer);
        bool fire = model.shouldFire(0, neurons[0]);
        if (fire) model.onFired(0, neurons[0]);
        tr.push_back({t, neurons[0].v_mem});
    }
    return tr;
}

int main(int argc, char** argv) {
    // Common horizons
    const int steps = 200;

    // 1) LIF: moderate threshold, modest input
    {
        LIFModel lif;
        ModelConfig cfg{}; cfg.dt_ms = 1.0f; cfg.v_thresh = 2.0f; cfg.v_reset = 0.0f; cfg.v_rest = 0.0f; cfg.tau_mem = 20.0f; cfg.t_ref = 2;
        SST::Params p; // no model.* needed
        auto tr = run_model(lif, cfg, p, /*v0*/0.0f, steps, /*inject_steps*/30, /*event_w*/0.5f);
        write_csv("lif_trace.csv", tr, "LIF dt=1ms v_thresh=2.0 v_rest=0 tau=20 ref=2; inject 0..29 w=0.5");
    }

    // 2) Izhikevich: classic RS params, strong input to ensure spiking
    {
        IzhikevichModel izh;
        ModelConfig cfg{}; cfg.dt_ms = 1.0f; cfg.v_thresh = 30.0f; cfg.v_reset = -65.0f; cfg.v_rest = -65.0f; cfg.t_ref = 2;
        SST::Params p; p.insert("model.a", "0.02"); p.insert("model.b", "0.2"); p.insert("model.c", "-65"); p.insert("model.d", "8");
        auto tr = run_model(izh, cfg, p, /*v0*/-65.0f, steps, /*inject_steps*/80, /*event_w*/10.0f);
        write_csv("izh_trace.csv", tr, "Izh dt=1ms a=0.02 b=0.2 c=-65 d=8 v_thresh=30; inject 0..79 I=10");
    }

    // 3) AdEx: moderate params, strong input
    {
        AdExModel adex;
        ModelConfig cfg{}; cfg.dt_ms = 1.0f; cfg.v_thresh = -40.0f; cfg.v_reset = -58.0f; cfg.v_rest = -70.0f; cfg.t_ref = 2;
        SST::Params p; 
        p.insert("model.C", "200"); p.insert("model.gL", "10"); p.insert("model.EL", "-70"); p.insert("model.VT", "-50");
        p.insert("model.DeltaT", "2"); p.insert("model.tau_w", "100"); p.insert("model.a", "2"); p.insert("model.b", "60"); p.insert("model.Vr", "-58");
        auto tr = run_model(adex, cfg, p, /*v0*/-70.0f, steps, /*inject_steps*/80, /*event_w*/500.0f);
        write_csv("adex_trace.csv", tr, "AdEx dt=1ms C=200 gL=10 EL=-70 VT=-50 DeltaT=2 tau_w=100 a=2 b=60 Vr=-58 v_thresh=-40; inject 0..79 I=500");
    }

    std::cout << "Generated lif_trace.csv, izh_trace.csv, adex_trace.csv" << std::endl;
    return 0;
}
