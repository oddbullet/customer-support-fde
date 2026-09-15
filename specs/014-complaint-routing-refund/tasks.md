---

description: "Task list for Complaint Routing to Refund Agent"
---

# Tasks: Complaint Routing to Refund Agent

**Input**: Design documents from `/specs/014-complaint-routing-refund/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md

**Tests**: Included — Constitution Principle I (Test-First, NON-NEGOTIABLE) requires a failing-then-passing test for every implementation change in this project, regardless of whether the spec explicitly asked for tests.

**Organization**: Tasks are grouped by user story per spec.md. All stories converge on the same single file (`src/customer_support_fde/nodes/router_agent.py`'s `SYSTEM_PROMPT`) and the same two test files, so — unlike a typical multi-file feature — story phases here are independently *testable* (each has its own test task that can be run and checked in isolation) but not independently *parallelizable* across developers, since they share files. See Dependencies & Execution Order below.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Exact file paths are included in every task description

## Path Conventions

Single project (per plan.md): `src/customer_support_fde/`, `tests/unit/`, `tests/integration/` at repository root.

---

## Phase 1: Setup

**Purpose**: Establish a known-good baseline before making any change.

- [ ] T001 Run `pytest tests/unit/test_router_agent.py tests/integration/test_router_trajectory.py -v` from repo root and confirm all existing tests pass before any change in this feature is made (baseline for the red/green cycles below).

---

## Phase 2: Foundational

**Not applicable to this feature.** There is no shared infrastructure, dependency, entity, or interface to stand up before story work can begin — this feature is a wording refinement to one existing prompt string (`router_agent.SYSTEM_PROMPT`) plus test coverage of that wording, per plan.md's Constitution Check (Principle III: no invented setup for its own sake). Proceed directly to Phase 3.

---

## Phase 3: User Story 1 - Complaint without an explicit refund ask is routed to the refund agent (Priority: P1) 🎯 MVP

**Goal**: A past-order complaint (cold food, missing item, late delivery, wrong dish) routes to the refund destination even when the customer never uses refund/money-back language — and a complaint with no connection to a past order does not.

**Independent Test**: Run `tests/unit/test_router_agent.py` and confirm the new `SYSTEM_PROMPT` assertions and plumbing tests for complaint-only queries pass in isolation.

### Tests for User Story 1

> **Write these tests FIRST. Run them and confirm they FAIL against the current `SYSTEM_PROMPT` before touching `router_agent.py`.**

- [ ] T002 [US1] In `tests/unit/test_router_agent.py`, add an assertion (or assertions) on `router_agent.SYSTEM_PROMPT` confirming it explicitly instructs: (a) a customer message describing dissatisfaction with a past order (e.g., cold, late, missing, or wrong item) classifies to `"refund"` without requiring refund/money-back language (FR-001, FR-002); (b) a complaint with no connection to a past order (e.g., about hours, ambiance, or the website) does NOT classify to `"refund"` (FR-006). Tag the test `(base)`/`(edge)` per the constitution's per-test comment convention. Run it and confirm it fails against the current prompt text.
- [ ] T003 [US1] In `tests/unit/test_router_agent.py`, add mocked-`RouterDecision` plumbing test case(s) for complaint-only queries — e.g. `"My order arrived 45 minutes late and the food was cold"`, `"The spring rolls I got were missing from my bag"` — mirroring spec.md User Story 1 Acceptance Scenarios 1–3: assert `result["destination"] == "refund"` and `result["sentiment"] is not None`. Follow the existing `test_refund_query_carries_negative_sentiment` pattern. Tag `(base)`.

### Implementation for User Story 1

- [ ] T004 [US1] Update `SYSTEM_PROMPT` in `src/customer_support_fde/nodes/router_agent.py` to add the complaint-recognition guidance asserted in T002: past-order dissatisfaction (cold/late/missing/wrong item, repeated problems) classifies as `"refund"` without needing refund/money-back language, while complaints unrelated to a past order do not. Do not change `RouterDecision`, `router_agent()`'s signature, or any control flow — this is a prompt-text-only change.
- [ ] T005 [US1] Run `pytest tests/unit/test_router_agent.py -v` and confirm T002 and T003 now pass, and that all pre-existing tests in this file still pass (no regression to the order/support, explicit-refund, unclear, or error-propagation cases).

**Checkpoint**: User Story 1 is fully functional and independently testable — complaint-only messages reach the refund destination.

---

## Phase 4: User Story 2 - Complaint paired with an explicit refund request is still routed as one case (Priority: P2)

**Goal**: A message that both describes a past-order complaint and explicitly asks for a refund resolves directly to the refund destination, without being mistaken for the mixed-signal (order/support + refund) case that triggers the clarifying question.

**Independent Test**: Run `tests/unit/test_router_agent.py` and confirm the new combined-complaint-plus-refund-ask tests pass in isolation, and that the pre-existing mixed-signal (`unclear`) test for "the food I ordered was cold, and also what's in the mapo tofu?" still passes unchanged.

### Tests for User Story 2

> **Write these tests FIRST. Run them and confirm they FAIL before extending the prompt further.**

- [ ] T006 [US2] In `tests/unit/test_router_agent.py`, add an assertion on `router_agent.SYSTEM_PROMPT` confirming it explicitly instructs that a message combining a past-order complaint with an explicit refund ask is a single `"refund"` case — not the mixed-signal case reserved for messages that combine order/support intent with refund/complaint intent (FR-003). Tag `(base)`. Run it and confirm it fails against the prompt as it stands after T004.
- [ ] T007 [US2] In `tests/unit/test_router_agent.py`, add mocked-`RouterDecision` plumbing test case(s) for combined complaint+refund-ask queries — e.g. `"My order arrived cold and an hour late, I want my money back"`, `"The dish had peanuts in it even though I asked for none — can I get a refund?"` — mirroring spec.md User Story 2 Acceptance Scenarios 1–2: assert `result["destination"] == "refund"` (never `"unclear"`) with sentiment attached. Tag `(base)`.

### Implementation for User Story 2

- [ ] T008 [US2] Extend `SYSTEM_PROMPT` in `src/customer_support_fde/nodes/router_agent.py` (building on T004's edit) to add the guidance asserted in T006: a past-order complaint combined with an explicit refund request resolves directly to `"refund"`, and is distinct from the "mixes order/support and refund signals" case that stays `"unclear"`.
- [ ] T009 [US2] Run `pytest tests/unit/test_router_agent.py -v` and confirm T006 and T007 now pass, and that the pre-existing `test_ambiguous_or_mixed_signal_query_stays_unclear_and_keeps_sentiment` case (including the "cold food + mapo tofu question" mixed-signal query) still passes unchanged — confirming FR-005 (mixed order/support-and-refund signals still trigger the clarifying question) was not broken by this feature.

**Checkpoint**: User Stories 1 and 2 both work independently — complaint-only and complaint+refund-ask messages both reach the refund destination, and genuine mixed-signal messages still do not.

---

## Phase 5: User Story 3 - Complaint routing behavior is verifiable end-to-end (Priority: P2)

**Goal**: A labeled sample set demonstrates, via graph-trajectory assertions, that complaint-only and complaint+refund-ask messages consistently reach `refund_agent`, alongside the existing order/support, explicit-refund, and mixed-signal samples.

**Independent Test**: Run `tests/integration/test_router_trajectory.py` and confirm the extended `LABELED_SAMPLES` set still passes `test_labeled_sample_set_routes_to_the_expected_destination_at_least_90_percent` and that each new refund-destination entry's trajectory reaches `refund_agent`.

### Tests for User Story 3

- [ ] T010 [US3] In `tests/integration/test_router_trajectory.py`, add complaint-only and complaint+refund-ask entries to `LABELED_SAMPLES` (matching the queries used in T003 and T007, each paired with a mocked `RouterDecision(destination="refund", ...)` and expected destination `"refund"`), mirroring spec.md User Story 1/2 Acceptance Scenarios and the spec's Edge Cases. Tag the change with the file's existing `(base)` convention for this test.

### Implementation for User Story 3

- [ ] T011 [US3] Run `pytest tests/integration/test_router_trajectory.py -v` and confirm `test_labeled_sample_set_routes_to_the_expected_destination_at_least_90_percent` still passes (accuracy ≥ 90%) with the new entries included, and that `test_refund_style_request_routes_through_refund_agent` and the mixed-signal parametrized test still pass unchanged (no regression to graph wiring).

**Checkpoint**: All three user stories are independently functional and verifiable — the feature is complete per spec.md.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation and release bookkeeping across all stories.

- [ ] T012 [P] Run the full test suite (`pytest`) from repo root and confirm no regressions anywhere in the project (order/support agent, refund agent, ticket generation, cart summary, memory/account nodes — all unrelated to this feature and must remain green).
- [ ] T013 [P] Bump the package version in `pyproject.toml` from `0.8.0` to `0.8.1` per Constitution Principle IV (PATCH: this is a routing-behavior clarification/fix to already-shipped logic, not a new feature surface or breaking change).
- [ ] T014 Work through `specs/014-complaint-routing-refund/quickstart.md`'s "Validation checklist" (SC-001, SC-002, SC-003) using the automated test commands, and check off each item.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — run first.
- **Foundational (Phase 2)**: N/A — nothing blocks story work beyond Setup.
- **User Story 1 (Phase 3)**: Depends on Phase 1 only. This is the MVP slice.
- **User Story 2 (Phase 4)**: Depends on User Story 1 being complete — T008 textually extends the same `SYSTEM_PROMPT` edit T004 made, and T009's regression check assumes T004/T005 already landed. Not parallelizable with US1 (same file).
- **User Story 3 (Phase 5)**: Depends on User Story 1 and User Story 2 being complete — its labeled-sample entries (T010) reuse the exact queries and expected outcomes those stories established.
- **Polish (Phase 6)**: Depends on Phases 3–5 all being complete.

### Within Each User Story

- Tests (T002/T003, T006/T007, T010) MUST be written and confirmed failing (where applicable — T002 and T006 are the genuine red/green assertions; T003, T007, T010 mock the LLM boundary and mainly serve as regression documentation, per research.md §1) before the corresponding implementation task.
- Implementation task depends on that story's test tasks.
- Story's final test-run task depends on that story's implementation task.

### Parallel Opportunities

Because every story-phase task touches one of two shared files (`router_agent.py` or the two test files), there are no cross-task `[P]` opportunities within Phases 3–5 — tasks in those phases are listed without `[P]` and should be done in order. The only genuine parallelizable work is in Phase 6 (T012 and T013 touch unrelated files/concerns and can run together).

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001).
2. Complete Phase 3: User Story 1 (T002–T005).
3. **STOP and VALIDATE**: `pytest tests/unit/test_router_agent.py -v` — complaint-only messages now route to refund. This alone is a shippable, valuable increment (SC-001 territory).

### Incremental Delivery

1. Setup → baseline confirmed green (T001).
2. User Story 1 → complaint-only recognition lands, tested and passing (T002–T005) → MVP.
3. User Story 2 → combined complaint+refund-ask case hardened, mixed-signal case confirmed unaffected (T006–T009).
4. User Story 3 → end-to-end trajectory coverage added for both new cases (T010–T011).
5. Polish → full-suite regression check, version bump, quickstart validation (T012–T014).

Each story adds value without breaking the previous one, and each phase's checkpoint is a safe place to stop and ship.
