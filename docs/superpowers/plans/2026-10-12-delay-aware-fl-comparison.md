# Delay-Aware FL and Paired Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement deterministic Delay-Aware client selection, paired FedAvg comparison, regression/integration tests, then validate the UI against the configured database.

**Architecture:** Keep existing Experiment/round tables and store immutable candidate/config snapshots plus a comparison UUID in `Experiment.config_json`. Extract network-time estimation and selection into pure services. Both algorithms use the same candidate partitions and stable per-client seeds; only the round selector differs.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, PyTorch, unittest, SQLite test fixture, static JavaScript/HTML.

**Spec:** `docs/superpowers/specs/2026-10-12-delay-aware-fl-comparison-design.md`

## Global Constraints

- Use selected ACTIVE participants for a scenario when present; otherwise use ACTIVE nodes from that scenario.
- Reject fewer than `client_count` eligible clients; never fall back to inactive nodes.
- The pair shares scenario, candidate snapshot, data partition, seed, model and training configuration.
- Aggregate only COMPLETED clients; record dropout and timeout consistently.
- Mark network and energy values as estimates and expose failure ratio by the correct name.
- Do not mutate topology data during real database UI verification.

## Review Focus

- Candidate count or active status changes while runs are queued: stored snapshot remains the run contract.
- Equal delay scores: node-ID tie-break is deterministic.
- All selected clients drop or timeout: attempted outcomes persist before experiment failure.
- Existing experiments only have `clients`, not `candidate_pool`: they retain legacy fixed-cohort behavior.
- Centralized/legacy rounds lack network metrics: UI shows N/A rather than fake values.

---

### Task 1: Delay estimate and deterministic schedulers

**Files:** `backend/services/delay_service.py`, `backend/services/scheduling_service.py`, `backend/algorithms/delay_aware_fl.py`, `tests/test_delay.py`, `tests/test_scheduling.py`

- [x] Add failing unit tests for profile-adjusted two-way transfer latency, deterministic FedAvg sampling, delay ranking/ties, inactive filtering and insufficient candidates.
- [x] Run the new focused tests and confirm expected failures.
- [x] Implement pure estimation and selection functions; keep DB access out of schedulers.
- [x] Re-run focused tests.

### Task 2: Per-round worker with reproducible shared candidate partitions

**Files:** `backend/services/fl_service.py`, `backend/algorithms/delay_aware_fl.py`, `tests/test_fl_runtime.py`

- [x] Add failing worker tests for Delay-Aware selection, timeout/dropout outcomes and all-client failure persistence; existing FedAvg runtime tests cover baseline behavior.
- [x] Run focused tests and confirm expected failures.
- [x] Implement round-level selection, profile snapshots, stable per-client seeds, COMPLETED-only aggregation and persisted failed-round outcomes. Preserve legacy fixed-client configs.
- [x] Run focused worker tests.

### Task 3: Paired API and auditable result payload

**Files:** `backend/schemas/fl.py`, `backend/routers/federated_learning.py`, `tests/test_fl_runtime.py`

- [x] Add failing API tests for no ACTIVE clients, paired shared config/candidate IDs, pair detail and client failure ratios.
- [x] Run focused API tests and confirm expected failures.
- [x] Implement `POST /api/fl/comparisons` and `GET /api/fl/comparisons/{id}` using config snapshots; return metrics and outcomes without hiding the candidate pool for pair views.
- [x] Run focused API tests and existing runtime tests.

### Task 4: FL Training and Results comparison UI

**Files:** `frontend/html/fl.html`, `frontend/js/fl.js`, `frontend/html/results.html`, `frontend/js/results.js`, `frontend/html/experiments.html`, `frontend/js/experiments.js`, `frontend/css/function-pages.css`

- [x] Add single-run algorithm choice plus paired-comparison action.
- [x] Poll both experiment IDs on FL Training and link to a comparison deep link.
- [x] Render shared-config audit and a round-aligned table for accuracy, completion, communication and energy, plus per-client outcomes in Results.
- [x] Show status, loading/error/empty states and unavailable metrics.
- [x] Run JavaScript syntax checks and inspect served pages.

### Task 5: Database-backed integration and project review

**Files:** `tests/test_fl_runtime.py`, `docs/sidebar-function-separation.md`, `docs/superpowers/specs/2026-10-12-delay-aware-fl-comparison-design.md`

- [x] Run the full backend unittest suite: 13 tests passed.
- [x] Check configured database connectivity without printing credentials; read scenario/node/participant state.
- [x] Start the application and inspect the main dashboard, globe, network, participants, FL Training, experiments and Results against the configured database.
- [x] Confirm the selected scenario/pool, run one small paired comparison, then verify the saved API/DB results in the UI.
- [x] Review the implementation and document remaining project limitations in the handoff.
