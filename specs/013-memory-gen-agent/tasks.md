---

description: "Task list for Customer Memory Generation Agent"
---

# Tasks: Customer Memory Generation Agent

**Input**: Design documents from `/specs/013-memory-gen-agent/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: Test tasks are included and are **NON-NEGOTIABLE** — Constitution v1.2.1 Principle I
requires tests to be written, reviewed, and observed failing before the implementation they
cover. Every test case MUST carry a one-line comment directly above its definition (above the
outermost `@pytest.mark.parametrize`, if present) stating what it verifies and tagging its
category: `(base)`, `(edge)`, `(error)`, or `(regression)`.

**Organization**: Grouped by user story so each can be implemented, tested, and demoed
independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Exact file paths are included in every task

## Path Conventions

Single Python package at repository root: `src/customer_support_fde/`, `tests/unit/`,
`tests/integration/`.

---

## Phase 1: Setup

**Not needed for this feature.** It extends an existing project with no new dependency, no new
CLI surface, and no schema change — `accounts.preferences` already exists
(`specs/012-account-identification-node`), and the existing `tests/unit/conftest.py` fixtures
already cover it. Proceed straight to Phase 2.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The new `db.py` write function, a runnable `memory_gen_node` (guard clause only —
no extraction logic yet), and its wiring into `graph.py` as a parallel branch off
`cart_summary`. No user story can be implemented until these exist, and because the new node
is now visited on every order-support confirmation, this phase must also repair the one existing
trajectory test whose exact step sequence this wiring changes.

**⚠️ CRITICAL**: No user story work begins until this phase completes.

- [X] T001 [P] Write failing tests in `tests/unit/test_db.py` for the new `db.update_account_preferences(account_number, preferences, path=None)` function (contracts/db-account-preferences.md): updating an existing account sets its `preferences` column to the given value and returns `None` (base); an account number with different casing/spacing/confusable characters still resolves via the same normalization `get_account` uses (edge); calling it with an account number that matches no row raises `OrderStoreError` (error); a forced `sqlite3.Error` during the update raises `OrderStoreError` wrapping it (error) — mirror the existing `get_account`/`create_account` test style in this file
- [X] T002 Implement `update_account_preferences` in `src/customer_support_fde/db.py` per [contracts/db-account-preferences.md](./contracts/db-account-preferences.md): normalize `account_number` via the existing `normalize_account_number`, run `UPDATE accounts SET preferences = ? WHERE account_number = ?` inside a `with conn:` transaction (same shape as `create_account`), raise `OrderStoreError` when `rowcount == 0` or on any `sqlite3.Error`, using the existing `_resolve_path`/`_connect`/`finally` convention — depends on T001
- [X] T003 [P] Write failing tests in `tests/unit/test_memory_gen_node.py` (new file) for `memory_gen_node`'s generic guard-clause mechanics only — no extraction logic yet: calling it with `state["account_number"] = None` returns `{}` (base, FR-002); the returned dict contains no other key, i.e. no `SupportState` field is touched (edge, research.md Decision 3)
- [X] T004 Create `src/customer_support_fde/nodes/memory_gen_node.py` (new file): `memory_gen_node(state)` returns `{}` immediately when `state.get("account_number")` is falsy (FR-002); when an account is present, for now `raise NotImplementedError` as a placeholder implemented in Phase 3 — depends on T003
- [X] T005 Register `memory_gen_node` in `src/customer_support_fde/graph.py`: add the node; add a new unconditional edge `cart_summary → memory_gen_node` alongside the existing `cart_summary → ticket_gen_node`; add `memory_gen_node → END` (research.md Decisions 1–2). No conditional routing is added — the guard clause inside the node itself is what skips guests (research.md Decision 5) — depends on T004
- [X] T006 Fix the trajectory regression this wiring causes (run `uv run pytest tests/integration -v` first to see it fail): `tests/integration/test_order_support_trajectory.py::test_full_conversation_confirms_and_produces_order_ticket` asserts an exact `reference_outputs["steps"]` sequence via `graph_trajectory_strict_match`, whose final entry currently ends `[..., "await_customer", "cart_summary", "ticket_gen_node"]`. Because `memory_gen_node` now also executes from `cart_summary` in that same step (even though this test uses no account, so it only hits the guard clause), update that final entry to also include `"memory_gen_node"` alongside `"ticket_gen_node"`, matching whatever order the graph actually reports for the two parallel branches. No other trajectory test file is affected (refund and router trajectories never reach `cart_summary`) — depends on T005

**Checkpoint**: The write path, a guard-clause-only node, and its parallel graph wiring all
exist. The full pre-existing test suite is green again. No story's real extraction/merge logic is
implemented yet — the account-present branch still raises `NotImplementedError`.

---

## Phase 3: User Story 1 - Stated preferences and allergies are remembered on the customer's account (Priority: P1) 🎯 MVP

**Goal**: An account-holding customer who mentions a like, dislike, allergy, or one-off
per-order customization during ordering has that information saved to their account once they
confirm their order.

**Independent Test**: Have an account-holding customer state a clear like, dislike, and allergy
during an order conversation, confirm the order, then check that customer's account record — the
stated information should now be present, with the allergy distinguishable from the others.

### Tests for User Story 1 ⚠️

> Write these FIRST and observe them FAIL before implementing.

- [X] T007 [P] [US1] Write failing tests in `tests/unit/test_memory_gen_node.py` for the account-present branch, mocking the `ChatOpenAI` client the same way `tests/unit/test_cart_summary_and_ticket_nodes.py` mocks `ticket_gen_node`'s: no prior preferences and the mocked model finds a like/dislike/allergy → `db.update_account_preferences` is called once with the account number and the model's returned text (base, FR-001, FR-003); prior preferences exist (`state["account_preferences"]` is a string) → the request sent to the model includes a message carrying that prior text, and `update_account_preferences` is called with the model's (combined) reply (base, FR-005); the model replies exactly `"None"` (any case/surrounding whitespace) → `update_account_preferences` is NOT called (edge, FR-006); a one-off per-order customization statement in the conversation is handled by the same path — assert the system prompt text sent to the model instructs it to capture per-order customizations and to distinguish allergies from other preferences per [contracts/memory-gen-node.md](./contracts/memory-gen-node.md) (edge, FR-001, FR-010, Clarifications); the model call raises an exception → the function returns `{}` and `update_account_preferences` is never called (error, FR-008); `db.update_account_preferences` raises `OrderStoreError` → the function returns `{}` and no exception propagates out of `memory_gen_node` (error, FR-008)
- [X] T008 [P] [US1] Write a failing trajectory test in `tests/integration/test_order_support_trajectory.py`: create an account via `db.create_account()`, monkeypatch `memory_gen_node`'s `_build_llm` to return a fake model whose reply is a fixed preferences string, drive a full conversation (mocking the order-support and router LLMs the same way `test_full_conversation_confirms_and_produces_order_ticket` does) through adding an item and confirming the order, then assert `db.get_account(account_number)["preferences"]` equals that fixed string once `graph.invoke` returns with no pending interrupt (mirrors quickstart.md scenario A)

### Implementation for User Story 1

- [X] T009 [US1] Implement the account-present branch of `memory_gen_node` in `src/customer_support_fde/nodes/memory_gen_node.py` per [contracts/memory-gen-node.md](./contracts/memory-gen-node.md): build the system prompt (merge instructions, most-recent-statement-wins on contradiction, per-order-customization capture, allergy/guideline distinction, `"None"` sentinel — research.md Decision 8), assemble the request (a message with the prior preferences text when `state.get("account_preferences")` is not `None`, followed by all of `state["messages"]`), call the model via the same `_build_llm()` shape as `ticket_gen_node.py` (OpenRouter base URL, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` env var with a `DEFAULT_MODEL` fallback), interpret the reply (skip the write when it's exactly `"None"`), call `db.update_account_preferences(account_number, reply)` otherwise, wrap the model call and the database write in one `try/except Exception` logged via `_logger.warning("...", exc_info=True)`, and always return `{}` — depends on T007, T008

**Checkpoint**: User Story 1 is fully functional and independently testable — MVP.

---

## Phase 4: User Story 2 - Guest customers are never profiled (Priority: P1)

**Goal**: A customer ordering without an account never has any preference data extracted or
stored, no matter what they say during ordering.

**Independent Test**: Have a customer decline an account, state a clear allergy during ordering,
confirm the order, and verify no preference data is stored anywhere.

### Tests for User Story 2 ⚠️

- [X] T010 [P] [US2] Strengthen the Foundational guard-clause test in `tests/unit/test_memory_gen_node.py` (from T003): monkeypatch the module's LLM builder and `db.update_account_preferences` to each raise `AssertionError` if called, then confirm calling `memory_gen_node` with `state["account_number"] = None` returns `{}` without either being invoked (base, FR-002, SC-002)
- [X] T011 [P] [US2] Write a failing trajectory test in `tests/integration/test_order_support_trajectory.py`: a guest conversation (resume the account menu with `"2"`, continue without an account) states a clear allergy during ordering and confirms the order; assert `db.get_account` still returns `None` for any account number mentioned and that no new `accounts` row was created by the conversation (base, SC-002)

### Implementation for User Story 2

- [X] T012 [US2] No new production code needed — the guard clause already exists from T004. Run `uv run pytest tests/unit/test_memory_gen_node.py tests/integration/test_order_support_trajectory.py -v` and confirm T010/T011 pass against the existing implementation with zero further edits — depends on T010, T011

**Checkpoint**: User Stories 1 AND 2 both independently functional.

---

## Phase 5: User Story 3 - Memory capture never slows down the customer (Priority: P2)

**Goal**: The customer's order ticket is delivered regardless of what happens in the memory
capture branch — the two never block each other.

**Independent Test**: Time order ticket delivery for an account-holding customer before and
after this feature ships and confirm there is no noticeable added wait; confirm a failure in
memory capture never affects ticket delivery.

### Tests for User Story 3 ⚠️

- [X] T013 [US3] Write a failing trajectory test in `tests/integration/test_order_support_trajectory.py`: repeat T008's full-conversation-to-confirmation flow, but monkeypatch `memory_gen_node`'s `_build_llm` to raise an exception instead of returning a reply; assert `final_state["order_ticket"]` is still produced with the same contents as an unaffected run (mirroring `test_full_conversation_confirms_and_produces_order_ticket`'s existing assertions), proving `ticket_gen_node`'s branch is unaffected by a failure in the `memory_gen_node` branch (FR-007, FR-008, SC-003 — this is the deterministic proxy for "no added delay," since wall-clock timing isn't reliably assertable in a mocked test)

### Implementation for User Story 3

- [X] T014 [US3] No new production code needed — the parallel, non-joined graph topology already exists from T005 and FR-008's fail-silent handling already exists from T009. Run `uv run pytest tests/integration/test_order_support_trajectory.py -v` and confirm T013 passes against the existing implementation with zero further edits — depends on T013

**Checkpoint**: All three user stories independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T015 [P] Bump `version` in `pyproject.toml` from `0.7.0` to `0.8.0` (MINOR — backward-compatible feature addition, Constitution Principle IV)
- [X] T016 Run the full suite (`uv run pytest tests/unit tests/integration -v`) and confirm every pre-existing test plus all new tests pass, with no regressions in the refund, router, or order-support trajectories
- [X] T017 Walk every scenario in [quickstart.md](./quickstart.md) end to end: automated tests, manual CLI scenarios A–E, and the unregressed-order-flow check

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: None — skipped
- **Foundational (Phase 2)**: **BLOCKS all user stories**
- **US1 (Phase 3)**: Depends on Foundational
- **US2 (Phase 4)**: Depends on Foundational only — its production behavior already exists from T004
- **US3 (Phase 5)**: Depends on Foundational (T005) and on US1's fail-silent handling (T009) actually existing for T013 to have something meaningful to assert about
- **Polish (Phase 6)**: Depends on all desired stories

### Story Dependencies

Like the account-identification feature before it, these three stories share one node function,
so they are **independently testable but not independently developable**:

- **US1 (P1)**: Independent for its own Independent Test. Delivers the feature's entire
  customer-visible value.
- **US2 (P1)**: Independent — its behavior shipped in Foundational (T004); this phase only adds
  dedicated tests confirming it.
- **US3 (P2)**: Independent — its topology shipped in Foundational (T005); its fail-silent
  guarantee ships with US1 (T009); this phase only adds a dedicated test confirming the
  combination.

### Within Each Story

- Tests are written and observed failing before the implementation they cover (Principle I)
- `db.py` accessors before the node logic that calls them
- Node logic before the graph wiring and trajectory tests that exercise it
- Unit tests before trajectory tests

### Parallel Opportunities

- **Phase 2**: T001 and T003 are different files and can start together; each blocks only its
  own next task (T002, T004 respectively). T005 and T006 are sequential (graph wiring, then the
  regression fix it causes).
- **Phase 3**: T007 and T008 are different files and independent of each other; both must land
  before T009.
- **Phase 4**: T010 and T011 are different files and independent of each other.
- **Phase 5**: T013 is the only task with a file change (a test); T014 is verification only.
- **Phase 6**: T015 touches a file untouched by T016/T017.

Tasks in the same file are never marked `[P]` relative to each other: T003/T007/T010 all edit
`tests/unit/test_memory_gen_node.py` and are sequential across phases, as is
`memory_gen_node.py` across T004/T009, and `tests/integration/test_order_support_trajectory.py`
across T006/T008/T011/T013.

---

## Parallel Example: Phase 2 Foundational

```bash
# Two independent tracks once the phase starts:
Track A: T001 → T002              # db.py write function
Track B: T003 → T004              # node skeleton (guard clause only)

# T005 (graph wiring) needs T004; T006 (regression fix) needs T005.
# In practice, Polish (T016) needs both tracks complete.
```

## Parallel Example: User Story 1

```bash
# Write both failing test files together:
Task: "Extraction/merge/error-handling tests in tests/unit/test_memory_gen_node.py"   # T007
Task: "End-to-end account-preferences trajectory test in tests/integration/test_order_support_trajectory.py"  # T008

# Then the one implementation task both depend on:
Task: "Account-present branch in nodes/memory_gen_node.py"                            # T009
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 2: Foundational — T001–T006 (**critical path; blocks everything**)
2. Phase 3: User Story 1 — T007–T009
3. **STOP and VALIDATE**: run quickstart.md scenario A and confirm a stated allergy/preference
   ends up in the account record with the allergy distinguishable from the rest
4. Demo: an account-holding customer's stated preferences are captured automatically. Guests are
   already unaffected (Foundational), just without their own dedicated coverage yet, and the
   "doesn't slow down ticket delivery" property isn't dedicated-tested until US3.

### Incremental Delivery

1. Foundational → write path, guard-clause node, and parallel wiring exist; regression-free
2. + US1 → account-holding customers get their preferences captured (**MVP**)
3. + US2 → guest exclusion gets its own dedicated tests (behavior already shipped)
4. + US3 → non-blocking/fail-isolation gets its own dedicated test (behavior already shipped)
5. + Polish → version bump, full regression + quickstart walkthrough

### Notes

- `[P]` means different files with no incomplete dependencies
- Every test case needs its one-line `(base)` / `(edge)` / `(error)` / `(regression)` comment —
  Principle I is non-negotiable and reviewers check for it
- Observe each test failing before writing the implementation; a test that passes on first run is
  not testing what you think
- Commit after each task or logical group
- T006 (the trajectory regression fix) is the task most likely to need care: don't guess the
  exact order `memory_gen_node` and `ticket_gen_node` appear in the step trace — run the suite,
  read the actual failure diff, and match it exactly
