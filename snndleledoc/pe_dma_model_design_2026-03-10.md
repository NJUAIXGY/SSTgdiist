# SnnDL Per-PE DMA Model for Runtime Weight Window Reads (Design)

Date: 2026-03-10
Owner: Fufu
Status: Draft

## 1. Background
Today, runtime SNN weight/window reads flow as:
WeightMemorySubsystem -> IMemoryAccess -> StandardMemAccess -> StandardMem (memHierarchy).
This path uses cacheline semantics and has no explicit on-chip DMA model. As a result, it cannot
explain per-PE shared bandwidth contention, engine parallelism limits, or priority effects between
critical reads and prefetch traffic.

This document proposes a per-PE shared DMA scheduler model that sits on the request issue side,
keeps cacheline semantics, and preserves the IMemoryAccess contract.

## 2. Goals
- Model a shared per-PE DMA bottleneck for runtime SNN weight/window reads.
- Provide clear, explainable knobs: bandwidth, engines, inflight, queue depth, priority, stage gating.
- Keep backward compatibility: disabled by default, no semantic changes when off.
- Maintain deterministic, testable behavior.

## 3. Non-Goals
- No init-time WeightLoader writes.
- No row-streaming semantics; keep cacheline transactions.
- No changes to memory backends (memHierarchy or ramulator2).
- No new SST component in Phase 1.

## 4. Scope and Assumptions
- Only runtime reads for SNN weight/window path: rowptr, colidx, blockdata, gcss, idx2, diag.
- Read-only DMA in Phase 1 (writes can be added later).
- All DMA scheduling happens per PE, shared across cores in that PE.

## 5. Architecture and Placement
Add a per-PE shared DMA scheduler as a SnnDL internal model class in services/memory.

Creation and wiring:
- MultiCorePE constructs one scheduler per PE.
- Each core keeps its own StandardMemAccess, but WeightMemorySubsystem uses a proxy that
  submits requests to the shared scheduler.
- Scheduler issues real IMemoryAccess::read only when budgets allow, and wraps callbacks
  to update DMA state before forwarding to the original callback.

Proposed classes:
- PeDmaScheduler: shared per-PE scheduler and budget enforcer.
- DmaMemAccessProxy: implements IMemoryAccess, forwards to scheduler.
- DmaRequest: request metadata (core, bytes, addr, tag, priority, stage, callbacks).

## 6. Interfaces
### 6.1 DmaRequest
Fields:
- core_id, addr, bytes
- tag: enum (rowptr, colidx, blockdata, dense, gcss, idx2, diag, prefetch)
- priority: enum (P0 critical, P1 normal, P2 prefetch, P3 diag)
- stage: enum (gather, apply, scatter, idle)
- window_seq (optional, for stage-linked reporting)
- submit_cycle
- callback: function(req_id, addr, data)

### 6.2 PeDmaScheduler
API:
- submitRead(DmaRequest) -> dma_req_id
- onReadResp(dma_req_id, addr, data) [internal]
- setStage(stage, seq)  (called on GAS stage events)
- tick(now_cycle)       (called by MultiCorePE each cycle)
- stats()               (for PE aggregation)

### 6.3 DmaMemAccessProxy
Implements IMemoryAccess:
- read(addr, bytes, cb): create DmaRequest and enqueue
- write(...): optional (not in Phase 1)
- pendingSize(): number of enqueued + inflight

## 7. Scheduling and Arbitration
### 7.1 Priority Queues
- Four priority queues per PE: P0, P1, P2, P3.
- Default tag -> priority mapping:
  - P0: rowptr, colidx (critical metadata)
  - P1: blockdata, dense, gcss, idx2 (critical data)
  - P2: prefetch (experimental)
  - P3: diag / verify

### 7.2 Stage Gating
Per-stage budget scaling for prefetch and non-critical traffic:
- Gather: allow prefetch (P2) at full or scaled budget.
- Apply: reduce or disable prefetch to protect critical reads.
- Scatter/Idle: optional low budget for background prefetch.

Config:
- dma_stage_budget_scale_{gather,apply,scatter,idle}_{P0..P3}
Default: P0=1.0 all stages, P1=1.0, P2=1.0 gather only, P3=0.2.

### 7.3 Core Fairness
Within a priority class, serve cores in round-robin order.
Optional weights: dma_core_weight[core_id] (default 1).

### 7.4 Budget and Engine Constraints
Per PE parameters:
- dma_bytes_per_cycle (global issue budget)
- dma_read_engines (max concurrent read issues per cycle)
- dma_max_inflight (max outstanding DMA requests)
- dma_queue_depth (max queued requests; overflow policy)
- dma_burst_bytes and dma_setup_cycles (burst segmentation + setup cost)

### 7.5 Optional Channel Budget
Optional HBM-like channel budgeting:
- dma_channels, dma_channel_bytes_per_cycle, dma_channel_interleave_bytes
Address -> channel mapping: (addr / interleave_bytes) % channels.

If enabled, requests consume both global and channel budgets.

## 8. Timing Model
The scheduler is ticked each cycle by MultiCorePE.
Per tick:
1) Refill budgets (global + per-channel).
2) Select next request by priority, then core fairness.
3) Check constraints (engines, inflight, budgets). If OK, issue:
   - If dma_burst_bytes > 0, split into bursts with optional setup cost.
   - Call underlying IMemoryAccess::read for each issued burst.
4) Track inflight and issue stats.

On response:
- Decrement inflight, update latency stats, forward callback to requester.

## 9. Stats and Observability
Per PE counters:
- dma_issue_reqs_total, dma_issue_bytes_total
- dma_queue_depth_max per priority
- dma_inflight_max
- dma_stall_cycles_{budget,engine,inflight,stage_gate,queue_full}
- dma_issue_latency_cycles (issue->resp) histograms per priority

Integration:
- Use IPeAggregation for PE-level stats.
- Optional per-core local stats for debugging (disabled by default).

## 10. Configuration
Parameters added to MultiCorePE (component params or overrides):
- dma_enable (0/1, default 0)
- dma_bytes_per_cycle (0 = unlimited)
- dma_read_engines (0 = unlimited)
- dma_max_inflight (0 = unlimited)
- dma_queue_depth (0 = unlimited)
- dma_overflow_policy (block|fail_fast, default block)
- dma_burst_bytes (0 = no burst segmentation)
- dma_setup_cycles (default 0)
- dma_channels (default 1)
- dma_channel_bytes_per_cycle (0 = disable)
- dma_channel_interleave_bytes (default 256)
- dma_stage_budget_scale_* (see 7.2)
- dma_priority_map_* (optional override mapping by tag)
- dma_core_weight_{core_id} (optional)

Example override (mesh spec):
{
  "overrides": [
    { "match": { "role": "pe" }, "params": {
        "dma_enable": 1,
        "dma_bytes_per_cycle": 256,
        "dma_read_engines": 2,
        "dma_max_inflight": 64,
        "dma_queue_depth": 1024
    }}
  ]
}

## 11. Backward Compatibility
Default dma_enable=0. When disabled, WeightMemorySubsystem uses StandardMemAccess directly,
preserving current behavior and performance.

## 12. Validation Plan
- A/B run: same mesh config with dma_enable=0 vs 1, verify correctness and stats consistency.
- Confirm no change in memHierarchy request counts when dma_enable=0.
- Validate expected throttling when dma_bytes_per_cycle is small.
- Stage gating sanity: prefetch throttled in Apply if configured.

## 13. Risks and Mitigations
- Starvation risk: use round-robin + per-priority caps.
- Queue overflow: default to block, optionally fail_fast for debug.
- Complexity creep: keep DMA model read-only in Phase 1.

## 14. Roadmap
- Phase 2: reuse scheduler for tensor and stream workloads.
- Phase 3: optional SubComponent form for broader reuse and explicit SST wiring.
