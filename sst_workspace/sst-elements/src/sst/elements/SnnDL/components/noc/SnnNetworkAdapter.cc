// -*- c++ -*-
//
// Copyright 2025 SST Contributors
//
// SnnNetworkAdapter.cc: payload-agnostic network topology adapter implementation
//

#include "SnnNetworkAdapter.h"
#include "SnnNetworkAdapterConfig.h"
#include "SimpleNetworkWrapper.h"
#include "NocPacketBatchEvent.h"
#include "SnnDLLogging.h"
#include "SnnDLStringUtil.h"

#include <algorithm>
#include <inttypes.h>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <sstream>
#include <utility>

namespace SST {
namespace SnnDL {

#ifndef ADP_LOG
#define ADP_LOG(lvl, ...) SNNDL_LOGPTR(output, (lvl), __VA_ARGS__)
#endif

namespace {

constexpr uint32_t kNocPacketHeaderBytes =
    sizeof(uint32_t) * 2 + sizeof(uint16_t) * 4 + sizeof(uint64_t);  // 24B
constexpr uint32_t kBatchBaseHeaderBytes =
    sizeof(uint32_t) * 2 + sizeof(uint64_t);  // 16B
constexpr uint32_t kBatchPerPacketHeaderBytes =
    sizeof(uint16_t) * 4 + sizeof(uint64_t);  // 16B

enum RoutePort : int { PORT_NORTH = 0, PORT_SOUTH = 1, PORT_EAST = 2, PORT_WEST = 3 };

static inline const char* portToDirection_(int port)
{
    switch (port) {
        case PORT_NORTH: return "north";
        case PORT_SOUTH: return "south";
        case PORT_EAST:  return "east";
        case PORT_WEST:  return "west";
        default: return nullptr;
    }
}

static inline int estimateBitsForEvent_(const SST::Event* ev)
{
    if (!ev) return 0;
    if (auto* pkt = dynamic_cast<const NocPacketEvent*>(ev)) {
        const uint64_t bytes = kNocPacketHeaderBytes + static_cast<uint64_t>(pkt->payload.size());
        return static_cast<int>(bytes * 8);
    }
    if (auto* batch = dynamic_cast<const NocPacketBatchEvent*>(ev)) {
        uint64_t bytes = kBatchBaseHeaderBytes;
        for (const auto& p : batch->packets) {
            bytes += kBatchPerPacketHeaderBytes + static_cast<uint64_t>(p.payload.size());
        }
        return static_cast<int>(bytes * 8);
    }
    return 256;
}

static inline bool parseShape_(const std::string& s, uint32_t& w, uint32_t& h)
{
    w = 0;
    h = 0;
    size_t pos = s.find('x');
    if (pos == std::string::npos) pos = s.find('X');
    if (pos == std::string::npos) return false;
    const std::string a = s.substr(0, pos);
    const std::string b = s.substr(pos + 1);
    char* endp = nullptr;
    unsigned long ww = std::strtoul(a.c_str(), &endp, 0);
    if (!endp || *endp != '\0') return false;
    endp = nullptr;
    unsigned long hh = std::strtoul(b.c_str(), &endp, 0);
    if (!endp || *endp != '\0') return false;
    if (ww == 0 || hh == 0) return false;
    w = static_cast<uint32_t>(ww);
    h = static_cast<uint32_t>(hh);
    return true;
}

} // namespace

// ===== NetworkEventConverter 实现（通用事件）=====

SST::Interfaces::SimpleNetwork::Request* NetworkEventConverter::convertEventToRequest(
    SST::Event* event, uint32_t dest_node, uint32_t src_node)
{
    if (!event) return nullptr;
    auto* request = new SST::Interfaces::SimpleNetwork::Request();
    request->dest = static_cast<SST::Interfaces::SimpleNetwork::nid_t>(dest_node);
    request->src = static_cast<SST::Interfaces::SimpleNetwork::nid_t>(src_node);
    request->vn = 0;
    request->size_in_bits = estimateBitsForEvent_(event);
    request->head = true;
    request->tail = true;
    request->allow_adaptive = true;
    request->givePayload(event);  // 接管生命周期
    return request;
}

SST::Event* NetworkEventConverter::convertRequestToEvent(SST::Interfaces::SimpleNetwork::Request* request)
{
    if (!request) return nullptr;
    return request->takePayload();  // 接管生命周期
}

// ===== SnnNetworkAdapter 实现（payload-agnostic）=====

SnnNetworkAdapter::SnnNetworkAdapter(SST::ComponentId_t id, SST::Params& params)
    : SnnInterface(id, params)
{
    const SnnNetworkAdapterConfig cfg = parseSnnNetworkAdapterConfig(params);

    output = new SST::Output("SnnNetworkAdapter[@p:@l]: ", cfg.verbose, 0, SST::Output::STDOUT);

    node_id = cfg.node_id;
    routing_algorithm = cfg.routing_algorithm;
    link_bw = cfg.link_bw;
    packet_size = cfg.packet_size;
    input_buf_size = cfg.input_buf_size;
    output_buf_size = cfg.output_buf_size;

    enable_adaptive_routing = cfg.enable_adaptive_routing;
    congestion_threshold = cfg.congestion_threshold;
    enable_merlin_router = cfg.enable_merlin_router;
    use_direct_link = cfg.use_direct_link;
    use_multi_port = cfg.use_multi_port;
    port_name = cfg.port_name;

    topology_type = parseTopologyType(cfg.topology_type);
    topology_shape = cfg.topology_shape;

    // counters
    spikes_routed_count = 0;
    local_spikes_count = 0;
    remote_spikes_count = 0;
    xy_routes_count = 0;
    adaptive_routes_count = 0;
    congestion_events_count = 0;
    total_hops_count = 0;
    average_latency_cycles = 0;
    max_hops_observed = 0;
    bandwidth_bytes_sent = 0;
    packets_dropped = 0;
    pending_send_enqueue_total_ = 0;
    pending_send_dequeue_total_ = 0;
    pending_send_high_watermark_ = 0;
    pending_send_space_block_total_ = 0;
    pending_send_send_fail_total_ = 0;

    stat_spikes_routed = registerStatistic<uint64_t>("spikes_routed");
    stat_local_spikes = registerStatistic<uint64_t>("local_spikes");
    stat_remote_spikes = registerStatistic<uint64_t>("remote_spikes");
    stat_xy_routes = registerStatistic<uint64_t>("xy_routes");
    stat_adaptive_routes = registerStatistic<uint64_t>("adaptive_routes");
    stat_congestion_events = registerStatistic<uint64_t>("congestion_events");
    stat_total_hops = registerStatistic<uint64_t>("total_hops");
    stat_average_latency = registerStatistic<uint64_t>("average_latency");
    stat_max_hops = registerStatistic<uint64_t>("max_hops");
    stat_bandwidth_utilization = registerStatistic<uint64_t>("bandwidth_utilization");
    stat_packets_dropped = registerStatistic<uint64_t>("packets_dropped");

    simple_network_wrapper = nullptr;
    direct_link = nullptr;
    router = nullptr;

    if (enable_merlin_router) {
        router = loadUserSubComponent<SST::Interfaces::SimpleNetwork>("linkcontrol", ComponentInfo::SHARE_NONE, 1);
        if (!router) {
            SST::Params net_params;
            net_params.insert("port_name", port_name);
            net_params.insert("link_bw", link_bw);
            net_params.insert("input_buf_size", input_buf_size);
            net_params.insert("output_buf_size", output_buf_size);
            net_params.insert("num_vns", "1");
            router = loadAnonymousSubComponent<SST::Interfaces::SimpleNetwork>(
                "merlin.linkcontrol", "linkcontrol", 0,
                ComponentInfo::SHARE_PORTS | ComponentInfo::INSERT_STATS, net_params, 1);
        }
    }
}

SnnNetworkAdapter::~SnnNetworkAdapter()
{
    if (output) delete output;
    output = nullptr;

    if (simple_network_wrapper) delete simple_network_wrapper;
    simple_network_wrapper = nullptr;

    while (!pending_sends_.empty()) {
        auto& ps = pending_sends_.front();
        delete ps.payload;
        pending_sends_.pop();
    }
}

void SnnNetworkAdapter::setReceiveHandler(ReceiveHandler handler)
{
    receive_handler_ = std::move(handler);
}

void SnnNetworkAdapter::sendToNode(uint32_t dest_node, SST::Event* event)
{
    if (!event) return;
    routeEvent_(event, dest_node);
}

void SnnNetworkAdapter::setNodeId(uint32_t new_node_id)
{
    node_id = new_node_id;
    if (topology_handler) {
        SST::Params dummy;
        dummy.insert("topology_shape", topology_shape);
        topology_handler->initialize(dummy, node_id);
    }
}

uint32_t SnnNetworkAdapter::getNodeId() const
{
    return node_id;
}

std::string SnnNetworkAdapter::getNetworkStatus() const
{
    std::ostringstream status;
    status << "SnnNetworkAdapter[" << node_id << "]";
    if (topology_handler) {
        status << " topo=" << topology_handler->getTopologyDescription();
    }
    status << " routed=" << spikes_routed_count << " dropped=" << packets_dropped;
    return status.str();
}

size_t SnnNetworkAdapter::pendingSendCount() const
{
    return pending_sends_.size();
}

bool SnnNetworkAdapter::handleIncoming(int vn)
{
    if (!router) return true;
    auto* req = router->recv(vn);
    while (req) {
        const uint32_t req_src = static_cast<uint32_t>(req->src);
        const uint32_t req_dst = static_cast<uint32_t>(req->dest);
        SST::Event* ev = extractEventFromRequest(req);
        delete req;
        if (!ev) {
            req = router->recv(vn);
            continue;
        }

        if (auto* batch = dynamic_cast<NocPacketBatchEvent*>(ev)) {
            // Keep metadata consistent with SimpleNetwork envelope.
            batch->src_node = req_src;
            batch->dst_node = req_dst;
            for (auto& p : batch->packets) {
                auto* pkt = new NocPacketEvent();
                pkt->src_node = batch->src_node;
                pkt->dst_node = batch->dst_node;
                pkt->src_endpoint = p.src_endpoint;
                pkt->dst_endpoint = p.dst_endpoint;
                pkt->kind = p.kind;
                pkt->hop_count = p.hop_count;
                pkt->step_seq = p.step_seq;
                pkt->timestamp = p.timestamp;
                pkt->payload = std::move(p.payload);
                if (receive_handler_) receive_handler_(pkt);
                else delete pkt;
            }
            delete batch;
        } else if (auto* pkt = dynamic_cast<NocPacketEvent*>(ev)) {
            // Keep metadata consistent with SimpleNetwork envelope.
            pkt->src_node = req_src;
            pkt->dst_node = req_dst;
            if (receive_handler_) receive_handler_(pkt);
            else delete pkt;
        } else {
            if (receive_handler_) receive_handler_(ev);
            else delete ev;
        }

        req = router->recv(vn);
    }
    return true;
}

bool SnnNetworkAdapter::spaceAvailable(int vn)
{
    (void)vn;
    if (!router) return true;
    while (!pending_sends_.empty()) {
        auto ps = pending_sends_.front();
        auto* req = createNetworkRequest(ps.payload, ps.dest_node, 0);
        bool sent = false;
        if (router->spaceToSend(req->vn, req->size_in_bits)) {
            sent = router->send(req, req->vn);
            if (!sent) pending_send_send_fail_total_++;
        } else {
            pending_send_space_block_total_++;
        }
        if (sent) {
            pending_sends_.pop();
            pending_send_dequeue_total_++;
            continue;
        }
        SST::Event* payload = req->takePayload();
        delete req;
        pending_sends_.front().payload = payload;
        break;
    }
    return true;
}

void SnnNetworkAdapter::handleDirectEvent(SST::Event* event)
{
    if (!event) return;
    if (auto* pkt = dynamic_cast<NocPacketEvent*>(event)) {
        constexpr uint16_t kMaxHops = NocPacketEvent::kDefaultMaxHops;
        if (pkt->hop_count >= kMaxHops) { delete pkt; return; }
        pkt->hop_count += 1;
        if (pkt->dst_node == node_id) {
            if (receive_handler_) receive_handler_(pkt);
            else delete pkt;
            return;
        }
        routeEvent_(pkt, pkt->dst_node);
        return;
    }
    if (receive_handler_) receive_handler_(event);
    else delete event;
}

void SnnNetworkAdapter::injectDirectionLink(const std::string& direction, SST::Link* link)
{
    if (link) parent_direction_links[direction] = link;
}

bool SnnNetworkAdapter::sendEventToDirection(SST::Event* event, const std::string& direction)
{
    if (!event) return false;
    auto it = direction_links.find(direction);
    if (it != direction_links.end() && it->second) {
        it->second->send(event);
        return true;
    }
    auto it2 = parent_direction_links.find(direction);
    if (it2 != parent_direction_links.end() && it2->second) {
        it2->second->send(event);
        return true;
    }
    delete event;
    return false;
}

void SnnNetworkAdapter::init(unsigned int phase)
{
    if (router) router->init(phase);
    if (phase == 0) initializeTopologyHandler();
}

void SnnNetworkAdapter::setup()
{
    if (!router) return;
    router->setup();
    router->setNotifyOnReceive(
        new SST::Interfaces::SimpleNetwork::Handler2<SnnNetworkAdapter, &SnnNetworkAdapter::handleIncoming>(this));
    router->setNotifyOnSend(
        new SST::Interfaces::SimpleNetwork::Handler2<SnnNetworkAdapter, &SnnNetworkAdapter::spaceAvailable>(this));
}

void SnnNetworkAdapter::finish()
{
    output->verbose(CALL_INFO, 0, 0,
        "[snn-nic-pending] node=%u enq=%" PRIu64 " deq=%" PRIu64 " hwm=%" PRIu64
        " space_block=%" PRIu64 " send_fail=%" PRIu64 " final=%zu\n",
        node_id,
        pending_send_enqueue_total_,
        pending_send_dequeue_total_,
        pending_send_high_watermark_,
        pending_send_space_block_total_,
        pending_send_send_fail_total_,
        pending_sends_.size());
    if (router) router->finish();
}

void SnnNetworkAdapter::initializeTopologyHandler()
{
    if (topology_handler) return;
    if (topology_type == TopologyType::TORUS_2D) topology_handler = std::make_unique<Torus2DHandler>();
    else topology_handler = std::make_unique<Mesh2DHandler>();
    if (topology_handler) {
        SST::Params dummy;
        dummy.insert("topology_shape", topology_shape);
        topology_handler->initialize(dummy, node_id);
    }
}

TopologyType SnnNetworkAdapter::parseTopologyType(const std::string& type_str)
{
    const std::string t = toLowerCopy(type_str);
    if (t == "torus2d") return TopologyType::TORUS_2D;
    return TopologyType::MESH_2D;
}

void SnnNetworkAdapter::routeEvent_(SST::Event* event, uint32_t dest_node)
{
    if (!event) return;
    if (dest_node == node_id) {
        local_spikes_count++;
        if (stat_local_spikes) stat_local_spikes->addData(1);
        if (receive_handler_) receive_handler_(event);
        else delete event;
        return;
    }

    if (enable_merlin_router && router) {
        sendViaMerlinRouter_(event, dest_node, 0);
        remote_spikes_count++;
        if (stat_remote_spikes) stat_remote_spikes->addData(1);
        spikes_routed_count++;
        if (stat_spikes_routed) stat_spikes_routed->addData(1);
        return;
    }

    if (use_direct_link && topology_handler) {
        int port = topology_handler->calculateRoute(dest_node);
        const char* dir = portToDirection_(port);
        if (dir) {
            const bool sent = sendEventToDirection(event, dir);
            if (sent) {
                remote_spikes_count++;
                if (stat_remote_spikes) stat_remote_spikes->addData(1);
                spikes_routed_count++;
                if (stat_spikes_routed) stat_spikes_routed->addData(1);
            } else {
                packets_dropped++;
                if (stat_packets_dropped) stat_packets_dropped->addData(1);
            }
            return;
        }
    }

    delete event;
    packets_dropped++;
    if (stat_packets_dropped) stat_packets_dropped->addData(1);
}

void SnnNetworkAdapter::sendViaDirectLink_(SST::Event* event, uint32_t dest_node)
{
    (void)dest_node;
    delete event;
}

void SnnNetworkAdapter::sendViaMerlinRouter_(SST::Event* event, uint32_t dest_node, int /*next_port*/)
{
    if (!router || !event) { delete event; return; }
    auto* req = createNetworkRequest(event, dest_node, 0);
    bool sent = false;
    if (router->spaceToSend(req->vn, req->size_in_bits)) {
        sent = router->send(req, req->vn);
        if (!sent) pending_send_send_fail_total_++;
    } else {
        pending_send_space_block_total_++;
    }
    if (sent) return;

    SST::Event* payload = req->takePayload();
    delete req;
    pending_sends_.push(PendingSend{dest_node, payload});
    pending_send_enqueue_total_++;
    const uint64_t pending_depth = static_cast<uint64_t>(pending_sends_.size());
    if (pending_depth > pending_send_high_watermark_) pending_send_high_watermark_ = pending_depth;
}

void SnnNetworkAdapter::sendViaMultiPortLink_(SST::Event* event, uint32_t dest_node, int /*next_port*/)
{
    (void)dest_node;
    delete event;
}

SST::Interfaces::SimpleNetwork::Request* SnnNetworkAdapter::createNetworkRequest(
    SST::Event* event, uint32_t dest_node, int /*route_port*/)
{
    auto* req = new SST::Interfaces::SimpleNetwork::Request();
    req->dest = dest_node;
    req->src = node_id;
    req->vn = 0;
    req->size_in_bits = estimateBitsForEvent_(event);
    req->head = true;
    req->tail = true;
    req->allow_adaptive = true;
    req->givePayload(event);
    return req;
}

SST::Event* SnnNetworkAdapter::extractEventFromRequest(SST::Interfaces::SimpleNetwork::Request* req)
{
    if (!req) return nullptr;
    return req->takePayload();
}

double SnnNetworkAdapter::getPortCongestion(int /*port*/)
{
    return 0.0;
}

void SnnNetworkAdapter::updateLoadStatistics(int /*port*/)
{
}

SimpleNetworkWrapper* SnnNetworkAdapter::getSimpleNetworkWrapper()
{
    return simple_network_wrapper;
}

SimpleNetworkWrapper* SnnNetworkAdapter::createSimpleNetworkWrapper(SST::Params& params)
{
    if (!simple_network_wrapper) {
        ComponentId_t wrapper_id = getId();
        simple_network_wrapper = new SimpleNetworkWrapper(wrapper_id, params, 0);
        simple_network_wrapper->setNetworkAdapter(this);
    }
    return simple_network_wrapper;
}

void Mesh2DHandler::initialize(SST::Params& params, uint32_t id)
{
    node_id = id;
    std::string shape = params.find<std::string>("topology_shape", "4x4");
    if (!parseShape_(shape, width, height)) { width = 4; height = 4; }
    my_x = node_id % width;
    my_y = node_id / width;
}

std::pair<uint32_t, uint32_t> Mesh2DHandler::nodeToCoord(uint32_t nid)
{
    return {nid % width, nid / width};
}

uint32_t Mesh2DHandler::coordToNode(uint32_t x, uint32_t y)
{
    return y * width + x;
}

int Mesh2DHandler::calculateRoute(uint32_t dest_node)
{
    auto [dx, dy] = nodeToCoord(dest_node);
    if (dx > my_x) return PORT_EAST;
    if (dx < my_x) return PORT_WEST;
    if (dy > my_y) return PORT_SOUTH;
    if (dy < my_y) return PORT_NORTH;
    return -1;
}

int Mesh2DHandler::calculateHopDistance(uint32_t dest_node)
{
    auto [dx, dy] = nodeToCoord(dest_node);
    return static_cast<int>(std::abs(static_cast<int>(dx) - static_cast<int>(my_x)) +
                            std::abs(static_cast<int>(dy) - static_cast<int>(my_y)));
}

std::string Mesh2DHandler::getTopologyDescription()
{
    std::ostringstream oss;
    oss << "Mesh2D[" << width << "x" << height << "]";
    return oss.str();
}

std::vector<uint32_t> Mesh2DHandler::getNeighbors()
{
    std::vector<uint32_t> n;
    if (my_x > 0) n.push_back(coordToNode(my_x - 1, my_y));
    if (my_x + 1 < width) n.push_back(coordToNode(my_x + 1, my_y));
    if (my_y > 0) n.push_back(coordToNode(my_x, my_y - 1));
    if (my_y + 1 < height) n.push_back(coordToNode(my_x, my_y + 1));
    return n;
}

void Torus2DHandler::initialize(SST::Params& params, uint32_t id)
{
    node_id = id;
    std::string shape = params.find<std::string>("topology_shape", "4x4");
    if (!parseShape_(shape, width, height)) { width = 4; height = 4; }
    my_x = node_id % width;
    my_y = node_id / width;
}

std::pair<uint32_t, uint32_t> Torus2DHandler::nodeToCoord(uint32_t nid)
{
    return {nid % width, nid / width};
}

uint32_t Torus2DHandler::coordToNode(uint32_t x, uint32_t y)
{
    return (y % height) * width + (x % width);
}

int Torus2DHandler::calculateTorusDistance(uint32_t coord1, uint32_t coord2, uint32_t dimension_size)
{
    int d = static_cast<int>(coord2) - static_cast<int>(coord1);
    int alt = (d > 0) ? (d - static_cast<int>(dimension_size)) : (d + static_cast<int>(dimension_size));
    return (std::abs(alt) < std::abs(d)) ? alt : d;
}

int Torus2DHandler::calculateRoute(uint32_t dest_node)
{
    auto [dx, dy] = nodeToCoord(dest_node);
    int ddx = calculateTorusDistance(my_x, dx, width);
    if (ddx > 0) return PORT_EAST;
    if (ddx < 0) return PORT_WEST;
    int ddy = calculateTorusDistance(my_y, dy, height);
    if (ddy > 0) return PORT_SOUTH;
    if (ddy < 0) return PORT_NORTH;
    return -1;
}

int Torus2DHandler::calculateHopDistance(uint32_t dest_node)
{
    auto [dx, dy] = nodeToCoord(dest_node);
    int ddx = std::abs(calculateTorusDistance(my_x, dx, width));
    int ddy = std::abs(calculateTorusDistance(my_y, dy, height));
    return ddx + ddy;
}

std::string Torus2DHandler::getTopologyDescription()
{
    std::ostringstream oss;
    oss << "Torus2D[" << width << "x" << height << "]";
    return oss.str();
}

std::vector<uint32_t> Torus2DHandler::getNeighbors()
{
    std::vector<uint32_t> n;
    n.push_back(coordToNode((my_x + 1) % width, my_y));
    n.push_back(coordToNode((my_x + width - 1) % width, my_y));
    n.push_back(coordToNode(my_x, (my_y + 1) % height));
    n.push_back(coordToNode(my_x, (my_y + height - 1) % height));
    return n;
}

} // namespace SnnDL
} // namespace SST
