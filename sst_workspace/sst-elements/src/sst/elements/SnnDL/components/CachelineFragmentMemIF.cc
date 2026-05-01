// CachelineFragmentMemIF.cc

#include <sst/core/sst_config.h>
#include "CachelineFragmentMemIF.h"

#include <algorithm>
#include <cstring>

using namespace SST;
using namespace SST::Interfaces;
using namespace SST::SnnDL;

CachelineFragmentMemIF::CachelineFragmentMemIF(ComponentId_t id, Params& params, TimeConverter* time, HandlerBase* handler)
    : StandardMem(id, params, time, handler), time_(time), upstream_handler_(handler)
{
    setDefaultTimeBase(*time);

    const int verbose = params.find<int>("verbose", 0);
    max_inflight_reads_ = static_cast<uint32_t>(params.find<int>("max_inflight_reads", 128));

    out_.init("CachelineFragmentMemIF[@p:@l]: ", verbose, 0, Output::STDOUT);

    // Load downstream memHierarchy.standardInterface anonymously, sharing our 'lowlink' port.
    Params bp;
    bp.insert("port", std::string("lowlink"));
    backend_ = loadAnonymousSubComponent<SST::Interfaces::StandardMem>(
        "memHierarchy.standardInterface", "lowlink", 0,
        ComponentInfo::SHARE_PORTS | ComponentInfo::INSERT_STATS,
        bp, time_, new StandardMem::Handler2<CachelineFragmentMemIF, &CachelineFragmentMemIF::onDownstreamResp_>(this));
    if (!backend_) {
        out_.fatal(CALL_INFO, -1, "Failed to load downstream memHierarchy.standardInterface\n");
    }
}

void CachelineFragmentMemIF::init(unsigned int phase) { backend_->init(phase); }
void CachelineFragmentMemIF::complete(unsigned int phase) { backend_->complete(phase); }
void CachelineFragmentMemIF::setup() { backend_->setup(); }
void CachelineFragmentMemIF::finish() { backend_->finish(); }

void CachelineFragmentMemIF::sendUntimedData(Request* req) { backend_->sendUntimedData(req); }
StandardMem::Request* CachelineFragmentMemIF::recvUntimedData() { return backend_->recvUntimedData(); }

StandardMem::Addr CachelineFragmentMemIF::getLineSize() { return backend_->getLineSize(); }
void CachelineFragmentMemIF::setMemoryMappedAddressRegion(Addr start, Addr size) {
    backend_->setMemoryMappedAddressRegion(start, size);
}

StandardMem::Request* CachelineFragmentMemIF::poll() {
    // Upstream uses push-based handler; return nullptr.
    return nullptr;
}

uint64_t CachelineFragmentMemIF::lineBytes_() const {
    auto ls = backend_ ? backend_->getLineSize() : 64;
    if (ls == 0) ls = 64;
    // sanity clamp: we only support "reasonable" cacheline sizes
    if (ls > (1ull << 20)) ls = 64;
    return static_cast<uint64_t>(ls);
}

void CachelineFragmentMemIF::issueMore_(uint64_t up_id) {
    auto it = up_reads_.find(up_id);
    if (it == up_reads_.end()) return;
    auto& st = it->second;
    const uint64_t line = lineBytes_();

    while (st.lines_issued < st.lines_total && inflight_total_ < max_inflight_reads_) {
        const uint64_t addr = st.base + static_cast<uint64_t>(st.lines_issued) * line;
        auto* rd = new StandardMem::Read(addr, static_cast<uint32_t>(line));
        const auto down_id = rd->getID();
        inflight_down_[down_id] = DownFrag{up_id, st.lines_issued};
        ++st.lines_issued;
        ++inflight_total_;
        backend_->send(rd);
    }
}

void CachelineFragmentMemIF::send(Request* req) {
    if (auto* rd = dynamic_cast<StandardMem::Read*>(req)) {
        const uint64_t line = lineBytes_();
        const uint64_t req_addr = static_cast<uint64_t>(rd->pAddr);
        const uint32_t req_size = static_cast<uint32_t>(rd->size);

        // Zero-sized reads are rare but legal; respond immediately.
        if (req_size == 0) {
            auto* resp = new StandardMem::ReadResp(rd->getID(), req_addr, 0, std::vector<uint8_t>{});
            if (upstream_handler_) (*upstream_handler_)(resp);
            // Upstream retains ownership of req pointer; do not delete.
            return;
        }

        const uint64_t base = alignDown_(req_addr, line);
        const uint64_t end = req_addr + static_cast<uint64_t>(req_size);
        const uint64_t end_aligned = alignUp_(end, line);
        const uint64_t span = (end_aligned > base) ? (end_aligned - base) : 0;
        const uint32_t lines_total = static_cast<uint32_t>(span / line);
        const uint32_t off = static_cast<uint32_t>(req_addr - base);

        UpReadState st;
        st.up_id = rd->getID();
        st.req_addr = req_addr;
        st.req_size = req_size;
        st.base = base;
        st.off = off;
        st.lines_total = lines_total;
        st.lines_issued = 0;
        st.lines_done = 0;
        st.buf.resize(static_cast<size_t>(lines_total) * static_cast<size_t>(line), 0);

        up_reads_[st.up_id] = std::move(st);
        issueMore_(rd->getID());

        // Ownership: upstream manages the Read* lifetime; we must not delete it.
        return;
    }

    // Writes/flush/other requests: pass-through.
    backend_->send(req);
}

void CachelineFragmentMemIF::onDownstreamResp_(Request* r) {
    if (auto* rr = dynamic_cast<StandardMem::ReadResp*>(r)) {
        auto it = inflight_down_.find(rr->getID());
        if (it == inflight_down_.end()) {
            // Pass-through ReadResp (not issued by this component).
            if (upstream_handler_) (*upstream_handler_)(r);
            else delete r;
            return;
        }

        const uint64_t up_id = it->second.up_id;
        const uint32_t line_index = it->second.line_index;
        inflight_down_.erase(it);
        if (inflight_total_ > 0) --inflight_total_;

        auto up_it = up_reads_.find(up_id);
        if (up_it == up_reads_.end()) {
            // Up request already retired; drop.
            delete r;
            return;
        }

        auto& st = up_it->second;
        const uint64_t line = lineBytes_();
        const size_t dst_off = static_cast<size_t>(line_index) * static_cast<size_t>(line);

        // Defensive: downstream should return at least one cacheline payload.
        if (rr->data.size() < line) {
            out_.fatal(CALL_INFO, -1,
                       "CachelineFragmentMemIF fatal: truncated ReadResp (up_id=%" PRIu64 " down_id=%" PRIu64
                       " line=%" PRIu64 " resp_bytes=%zu)\n",
                       (uint64_t)up_id, (uint64_t)rr->getID(), (uint64_t)line, rr->data.size());
        }

        if (dst_off + line <= st.buf.size()) {
            std::memcpy(st.buf.data() + dst_off, rr->data.data(), static_cast<size_t>(line));
        }
        ++st.lines_done;
        delete r;

        // Continue issuing remaining fragments for this upstream request.
        issueMore_(up_id);

        if (st.lines_done >= st.lines_total) {
            // All lines are ready: emit a single ReadResp with the original byte range.
            auto* resp = new StandardMem::ReadResp(
                up_id,
                st.req_addr,
                static_cast<uint64_t>(st.req_size),
                std::vector<uint8_t>(st.req_size)
            );
            const size_t off = static_cast<size_t>(st.off);
            if (off + st.req_size <= st.buf.size()) {
                std::memcpy(resp->data.data(), st.buf.data() + off, st.req_size);
            }
            if (upstream_handler_) (*upstream_handler_)(resp);
            up_reads_.erase(up_it);
        }
        return;
    }

    // Pass-through for other responses.
    if (upstream_handler_) (*upstream_handler_)(r);
    else delete r;
}

