// -*- c++ -*-
#ifndef _SNN_GATING_PE_H
#define _SNN_GATING_PE_H

#include <sst/core/component.h>
#include <sst/core/output.h>
#include <sst/core/statapi/statbase.h>
#include <sst/core/interfaces/simpleNetwork.h>
#include <fstream>
#include <string>
#include <vector>

namespace SST { namespace SnnDL {

class GatingPE : public SST::Component {
public:
    SST_ELI_REGISTER_COMPONENT(
        GatingPE,
        "SnnDL",
        "GatingPE",
        SST_ELI_ELEMENT_VERSION(1,0,0),
        "NeuroMoE Gating Component (offline edges CSV generator)",
        COMPONENT_CATEGORY_PROCESSOR
    )

    SST_ELI_DOCUMENT_PARAMS(
        {"total_nodes", "Total PEs in system", "16"},
        {"rows_per_pe", "Rows(neurons) per PE", "16"},
        {"top_k", "Top-k experts per token", "4"},
        {"transitions", "Layer transitions, e.g. 0-3:4-7,4-7:8-11,8-11:12-15", "0-3:4-7,4-7:8-11,8-11:12-15"},
        {"weight_value", "Edge weight value", "1.0"},
        {"edges_output_file", "CSV path to write edges", ""},
        {"csv_header", "Write CSV header (0/1)", "1"},
        {"selection", "Selection policy: round_robin|uniform_random|hash", "round_robin"},
        {"seed", "Random seed (for uniform_random)", "42"},
        {"verbose", "Verbosity", "0"},
        // 控制面发射参数
        {"gate_targets", "Source PEs to receive gating events (e.g. 0-3)", "0-3"},
        {"emit_period_ns", "Emit period in ns for gating events", "100000"},
        {"emit_count", "How many periods to emit (0=unlimited)", "0"},
        {"node_id", "Logical node id for NIC (optional)", "0"},
        {"link_bw", "NIC link bandwidth", "40GiB/s"},
        {"input_buf_size", "NIC input buffer size", "1KiB"},
        {"output_buf_size", "NIC output buffer size", "1KiB"},
        {"virtual_channels", "NIC num VNs", "2"},
        {"vn_control", "VN index for control events", "1"}
    )

    SST_ELI_DOCUMENT_STATISTICS(
        {"gating_tokens", "Total gating tokens (sources)", "tokens", 1},
        {"edges_generated", "Edges generated (rows)", "edges", 1},
        {"gating_events_sent", "Gating events sent", "events", 1}
    )

    // 端口 & 子组件槽位（用于NIC）
    SST_ELI_DOCUMENT_PORTS(
        {"network", "连接到merlin.hr_router的端口", {"SimpleNetwork"}}
    )
    SST_ELI_DOCUMENT_SUBCOMPONENT_SLOTS(
        {"network_interface", "SnnNIC子组件（可选，控制面）", "SST::SnnDL::SnnInterface"}
    )

    GatingPE(SST::ComponentId_t id, SST::Params& params);
    ~GatingPE() override;

    void init(unsigned int phase) override;
    void setup() override;
    void finish() override;

private:
    struct Range { uint32_t a{0}, b{0}; };
    struct Transition { Range src; Range dst; };

    bool parseTransitions(const std::string& s, std::vector<Transition>& out);
    void writeCSV();
    bool parseTargets(const std::string& s, std::vector<uint32_t>& out);
    bool onEmitTick(SST::Cycle_t);

    // params
    uint32_t total_nodes_ = 16;
    uint32_t rows_per_pe_ = 16;
    uint32_t top_k_ = 4;
    float weight_value_ = 1.0f;
    std::string transitions_;
    std::string edges_path_;
    bool csv_header_ = true;
    std::string selection_ = "round_robin";
    uint32_t seed_ = 42;
    // emit params
    std::string gate_targets_;
    uint64_t emit_period_ns_ = 100000;
    uint64_t emit_count_ = 0; // 0=unlimited
    uint64_t emit_sent_ = 0;
    uint32_t nic_node_id_ = 0;
    uint32_t nic_vns_ = 2;
    uint32_t nic_vn_control_ = 1;
    std::string nic_link_bw_ = "40GiB/s";
    std::string nic_in_buf_ = "1KiB";
    std::string nic_out_buf_ = "1KiB";

    // per-instance parse caches
    std::vector<uint32_t> parsed_targets_;
    std::vector<Transition> parsed_transitions_;

    // infra
    SST::Output* out_ = nullptr;
    class SnnInterface* nic_ = nullptr;

    // stats
    Statistic<uint64_t>* stat_tokens_ = nullptr;
    Statistic<uint64_t>* stat_edges_ = nullptr;
    Statistic<uint64_t>* stat_evt_sent_ = nullptr;
};

}} // namespace

#endif
