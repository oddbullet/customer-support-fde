---

description: "Task list for Refund Policy Agent"
---

# Tasks: Refund Policy Agent

**Input**: Design documents from `/specs/007-refund-policy-agent/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: Test tasks are included and are **NON-NEGOTIABLE** — Constitution v1.2.0 Principle I
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

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Shared test scaffolding every later phase depends on

- [X] T001 Create `tests/unit/conftest.py` with a `refund_db` fixture returning a `tmp_path`-based initialized database, and a `seed_order(db_path, lines, age_hours=0)` helper that records an order via `db.record_order` then backdates `orders.created_at` by `age_hours` so the 48-hour window can be exercised without sleeping

**Checkpoint**: Age-controllable order seeding available to all test files

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The storage schema, conversation state, policy engine, and graph loop. No user
story can be implemented until these exist.

**⚠️ CRITICAL**: No user story work begins until this phase completes.

### Schema and state

- [X] T002 Write failing tests in `tests/unit/test_db.py` for the three new tables: that `init_database` creates `refund_requests`, `refund_request_lines`, and `complaints`; that a second insert with the same `order_id` into `refund_requests` raises `sqlite3.IntegrityError` (UNIQUE); that `return_confirmed` rejects values outside `(0, 1)`; and that a row with `return_confirmed = 0` and a non-NULL `substitute_dishes` is rejected by the CHECK constraint
- [X] T003 Append the `refund_requests`, `refund_request_lines`, and `complaints` DDL plus `idx_complaints_order_id` to `_SCHEMA` in `src/customer_support_fde/db.py`, copied verbatim from `specs/007-refund-policy-agent/contracts/sqlite-schema.sql` — all statements use `CREATE TABLE IF NOT EXISTS` so `--init-db` stays idempotent
- [X] T004 Add five fields to `SupportState` in `src/customer_support_fde/state.py`: `order_lookup: dict | None`, `refund_resolved: bool`, `refund_request: dict | None`, `complaint_ids: dict[str, int]`, `refund_ticket: dict | None`
- [X] T005 Write failing test in `tests/unit/test_cli.py` asserting the initial state dict built in `run()` contains all five new keys with initial values `None`, `False`, `None`, `{}`, `None`
- [X] T006 Seed the five new fields in the initial state dict in `run()` in `src/customer_support_fde/cli.py`

### Policy engine (the determinism guarantee)

- [X] T007 [P] Write failing tests in `tests/unit/test_refund_policy.py` covering every branch of `evaluate()`: eligible at 47h59m; eligible at exactly 48h00m (boundary is inclusive); denied `outside_window` at 48h01m; denied `item_delivered` when no line is reported undelivered alongside a quality/temperature/timing complaint; denied `return_declined` when a substitute was received and `return_confirmed` is `False`; denied `no_undelivered_items` when the undelivered list is empty; **eligible** when an item never arrived and no substitute was received even though `return_confirmed` is `False` (FR-006 waiver); and that identical inputs produce identical `PolicyDecision` values regardless of any sentiment value held elsewhere (SC-009)
- [X] T008 [P] Implement `src/customer_support_fde/refund_policy.py`: `REFUND_WINDOW_HOURS = 48`, the frozen `PolicyDecision` dataclass (`eligible: bool`, `reason: str | None`, `message: str`), and `evaluate(order, undelivered, substitute_received, return_confirmed, now)` returning one of the reason codes `outside_window`, `item_delivered`, `return_declined`, `no_undelivered_items`. Parse `orders.created_at` with `datetime.fromisoformat`; the window test is `now - created_at <= timedelta(hours=REFUND_WINDOW_HOURS)`. The function MUST be pure, MUST NOT read the clock, and MUST NOT accept a sentiment argument

### Agent loop and ticket

- [X] T009 Write failing tests in `tests/unit/test_refund_tools.py` for `lookup_order`: a found order returns a `Command` setting `order_lookup` and a `ToolMessage` rendering lines, quantities, unit prices, total, and placement time; an unknown id leaves `order_lookup` unchanged and returns a re-check message; a lowercase/dashed/`O`-for-`0` id still resolves via `db.normalize_order_id`
- [X] T010 Implement `lookup_order` in `src/customer_support_fde/tools/refund_tools.py` wrapping the existing `db.get_order`, per `contracts/refund-tools.md`
- [X] T011 Write failing tests in `tests/unit/test_refund_tools.py` for `conclude_refund_conversation` returning a `Command` that sets `refund_resolved: True`
- [X] T012 Implement `conclude_refund_conversation` in `src/customer_support_fde/tools/refund_tools.py`, mirroring `mark_order_confirmed` in `cart_tools.py`
- [X] T013 Write failing tests in `tests/unit/test_refund_agent.py`: the node seeds a system prompt plus the customer's query when `messages` is empty; it reuses the existing transcript on later turns rather than re-seeding; `refund_await_customer` appends the reply as a `HumanMessage` without clearing the transcript; and it does not interrupt once `refund_resolved` is `True`
- [X] T014 Rewrite `src/customer_support_fde/nodes/refund_agent.py`, replacing the pass-through stub with `refund_agent` (seeds messages, binds `_REFUND_TOOLS`, calls the model) and `refund_await_customer` (interrupts, appends the reply, does not clear `messages` — research.md Decision 7). Register `lookup_order` and `conclude_refund_conversation` in `_REFUND_TOOLS` for now
- [X] T015 Wire the refund loop in `src/customer_support_fde/graph.py`: add nodes `refund_tools` (a `ToolNode` over `_REFUND_TOOLS`), `refund_await_customer`, and `refund_ticket_node`; route `refund_agent` through `tools_condition` to `refund_tools` or `refund_await_customer`; edge `refund_tools → refund_agent`; conditional edge from `refund_await_customer` to `refund_ticket_node` when `refund_resolved` else `refund_agent`; edge `refund_ticket_node → END`, replacing the current `refund_agent → END` edge
- [X] T016 [P] Write failing tests in `tests/unit/test_cart_summary_and_ticket_nodes.py` for `refund_ticket_node` producing the ticket shape in data-model.md — keys `order_id`, `order`, `sentiment`, `decision`, `refund_request`, `complaint_ids` — including the case where no order was ever identified
- [X] T017 [P] Implement `refund_ticket_node` in `src/customer_support_fde/nodes/ticket_gen_node.py` alongside the existing `ticket_gen_node`, keeping both ticket types in the one ticket-summary module

**Checkpoint**: Schema, state, policy engine, and a runnable refund conversation loop exist. No refund or complaint is persisted yet.

---

## Phase 3: User Story 1 - Customer gets a refund for a wrong item on a recent order (Priority: P1) 🎯 MVP

**Goal**: A customer reporting an undelivered item on a recent order gets a stored pending
refund request covering only that line, and is told it is submitted and awaiting review.

**Independent Test**: Seed an order within 48 hours, report a wrong/missing dish, confirm the
return, and verify one `refund_requests` row exists with `status='pending'` and an amount equal
to the undelivered line's total.

### Tests for User Story 1 ⚠️

> Write these FIRST and observe them FAIL before implementing.

- [X] T018 [P] [US1] Write failing tests in `tests/unit/test_db.py` for refund request persistence: `record_refund_request` writes one `refund_requests` row plus its `refund_request_lines` and returns the new id; `status` is written as `pending`; `substitute_dishes` round-trips as a JSON array and is `NULL` when nothing arrived; `get_refund_request_for_order` returns the request with lines attached or `None`; `list_refund_requests` returns newest first; and a `sqlite3.Error` during the write surfaces as `OrderStoreError`
- [X] T019 [P] [US1] Write failing tests in `tests/unit/test_refund_tools.py` for `process_refund_request`: the eligible path writes a request and returns a message stating the amount and that it is *submitted and awaiting review* but never that it is complete (FR-016); a reported quantity greater than the ordered quantity is clamped to the ordered quantity and the reply says so; a reported name matching no order line contributes no amount and is reported as unmatched; calling with `state["order_lookup"]` as `None` writes nothing and asks for a lookup first; an order that already has a request writes nothing and reports the existing request's status (FR-011); and an `OrderStoreError` during the write yields an explicit "could not be recorded" message rather than a confirmation (FR-025)
- [X] T020 [P] [US1] Write failing test in `tests/unit/test_cli.py` asserting `_print_result` renders the refund outcome for a resolved refund conversation, and includes `refund_ticket` in the `--json` payload

### Implementation for User Story 1

- [X] T021 [US1] Implement `record_refund_request(order_id, lines, amount, substitute_dishes, return_confirmed, path=None)`, `get_refund_request_for_order(order_id, path=None)`, and `list_refund_requests(path=None)` in `src/customer_support_fde/db.py`, following the existing convention: resolve via `_resolve_path`, connect via `_connect`, close in a `finally`, wrap `sqlite3.Error` in `OrderStoreError`. Write `created_at` in the same UTC ISO-8601-with-`Z` format `record_order` uses, and serialize `substitute_dishes` as a JSON array or `NULL`
- [X] T022 [US1] Add the `UndeliveredItem` Pydantic model (`name: str`, `quantity: int`) to `src/customer_support_fde/tools/refund_tools.py`, following the `CartRemoval` precedent in `cart_tools.py`
- [X] T023 [US1] Implement `process_refund_request(undelivered_items, substitute_dishes, return_confirmed, customer_issue, state, tool_call_id)` in `src/customer_support_fde/tools/refund_tools.py`: read the order from `state["order_lookup"]` (never a model argument); match reported names against the order's lines and clamp quantities to what was ordered; compute the amount as `Decimal(str(unit_price)) * quantity` summed then converted to `float`, mirroring `build_order_summary`; call `refund_policy.evaluate(...)` with `now=datetime.now(timezone.utc)`; on eligible persist via `record_refund_request` and update `refund_request`. Denials return the policy message without persisting anything yet — complaint persistence lands in US2
- [X] T024 [US1] Register `process_refund_request` in `_REFUND_TOOLS` in `src/customer_support_fde/nodes/refund_agent.py`
- [X] T025 [US1] Write the refund system prompt in `src/customer_support_fde/nodes/refund_agent.py`: instruct the agent to obtain an order id and call `lookup_order` before anything else, to gather which ordered dishes were not received, whether a substitute arrived, and whether the customer will return it, to call `process_refund_request` rather than judging eligibility itself, to relay tool messages without restating amounts or verdicts in its own words, and to soften tone when `state["sentiment"]` is `negative` while never letting it change the outcome (FR-026, FR-027)
- [X] T026 [US1] Render the refund outcome in `_print_result` in `src/customer_support_fde/cli.py` — print the agent's closing message for a resolved refund conversation, and include `refund_ticket` in the `--json` payload
- [X] T027 [P] [US1] Write a trajectory test for the qualifying-refund conversation in `tests/integration/test_refund_trajectory.py`, following the harness in `tests/integration/_trajectory.py`

**Checkpoint**: US1 fully functional — qualifying refunds are stored; denials are explained but not yet logged.

---

## Phase 4: User Story 2 - Customer is told why their refund is denied (Priority: P2)

**Goal**: Every denial names the specific policy condition that failed and is recorded as a
complaint, with at most one complaint per conversation per order.

**Independent Test**: Run the three denial branches (order older than 48 hours, correctly
delivered item, return declined) and verify no refund request is stored, a complaint row exists
for each, and the reply names the failing condition. Then argue the same denial twice more in
one conversation and verify still exactly one complaint row.

### Tests for User Story 2 ⚠️

- [X] T028 [P] [US2] Write failing tests in `tests/unit/test_db.py` for complaint persistence: `record_complaint` writes a row and returns its id, with `order_id` NULL when none is supplied and `policy_reason` NULL for a standalone complaint; `extend_complaint` updates `description`, `policy_reason`, and `updated_at` while leaving `id` and `created_at` unchanged (FR-021); `list_complaints` returns newest first; and a `sqlite3.Error` surfaces as `OrderStoreError`
- [X] T029 [P] [US2] Write failing tests in `tests/unit/test_refund_tools.py` for the denial path of `process_refund_request`: each of the four reason codes writes a complaint carrying `customer_issue` and that code; no `refund_requests` row is created for any denial (FR-010); a second denial for the same order in the same conversation extends the complaint recorded in `state["complaint_ids"]` instead of inserting a second row (FR-020, SC-010); a denial for a *different* order creates its own row; and the returned message names the failing condition (FR-009, SC-005)

### Implementation for User Story 2

- [X] T030 [US2] Implement `record_complaint(description, order_id=None, policy_reason=None, path=None)`, `extend_complaint(complaint_id, description, policy_reason, path=None)`, and `list_complaints(path=None)` in `src/customer_support_fde/db.py`, following the same connection/error convention as T021. `extend_complaint` MUST NOT touch `created_at`
- [X] T031 [US2] Wire the denial branch of `process_refund_request` in `src/customer_support_fde/tools/refund_tools.py` to record or extend a complaint: key `state["complaint_ids"]` by the order id (or `""` when no order was identified); call `extend_complaint` when a key already exists, otherwise `record_complaint`, and return the updated `complaint_ids` in the `Command`
- [X] T032 [P] [US2] Write trajectory tests in `tests/integration/test_refund_trajectory.py` for the three denial branches, asserting each reply names its policy condition

**Checkpoint**: US1 and US2 both work independently — refunds stored, denials explained and logged exactly once per conversation per order.

---

## Phase 5: User Story 3 - Customer raises a complaint without asking for money back (Priority: P3)

**Goal**: Dissatisfaction voiced without a refund request is recorded and acknowledged.

**Independent Test**: Voice a complaint without requesting money back and verify a `complaints`
row exists with `policy_reason` NULL and no refund request.

### Tests for User Story 3 ⚠️

- [X] T033 [P] [US3] Write failing tests in `tests/unit/test_refund_tools.py` for `log_complaint`: it records a complaint with `policy_reason` NULL; it links to `state["order_lookup"]`'s order when one was retrieved and stores `order_id` NULL otherwise (FR-019); it extends rather than duplicates when `state["complaint_ids"]` already holds an id for that order (FR-020); and an `OrderStoreError` yields a "could not be recorded" message rather than a confirmation (FR-025)

### Implementation for User Story 3

- [X] T034 [US3] Implement `log_complaint(description, state, tool_call_id)` in `src/customer_support_fde/tools/refund_tools.py` per `contracts/refund-tools.md`, reusing the `complaint_ids` de-duplication helper added in T031
- [X] T035 [US3] Register `log_complaint` in `_REFUND_TOOLS` and extend the system prompt in `src/customer_support_fde/nodes/refund_agent.py` to call it when the customer voices dissatisfaction without seeking a refund
- [X] T036 [P] [US3] Write a trajectory test in `tests/integration/test_refund_trajectory.py` for a complaint-only conversation that creates no refund request

**Checkpoint**: All three user stories independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T037 [P] Update the stale docstring in `tests/integration/_trajectory.py` — it cites "a refund conversation" as an example of a flow whose `messages` stays empty, which stops being true once the refund loop keeps its transcript (research.md Decision 7). The helper's behavior is unchanged; only the example is wrong
- [X] T038 [P] Update the Setup section of `CLAUDE.md` to note that `--init-db` must be re-run on an existing database to create the refund and complaint tables
- [X] T039 [P] Bump `version` in `pyproject.toml` from `0.2.0` to `0.3.0` (MINOR — backward-compatible feature addition, Constitution Principle IV)
- [X] T040 Run the full unit suite (`uv run pytest tests/unit -v`) and confirm the pre-existing ordering tests still pass, proving the added `SupportState` keys and graph edges did not regress the order flow
- [X] T041 Walk every scenario in [quickstart.md](./quickstart.md) end to end, including the manual CLI scenarios A–F

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup — **BLOCKS all user stories**
- **US1 (Phase 3)**: Depends on Foundational
- **US2 (Phase 4)**: Depends on Foundational. Shares `process_refund_request` with US1 (T031 edits what T023 creates), so in practice it follows US1
- **US3 (Phase 5)**: Depends on Foundational. Reuses the de-duplication helper from T031, so it follows US2
- **Polish (Phase 6)**: Depends on all desired stories

### Story Dependencies

Unlike a typical feature, these three stories share one tool function and one agent prompt, so
they are **independently testable but not independently developable**. Each phase leaves the
system in a working, demoable state; they should be built in priority order:

- **US1 (P1)**: Independent. Delivers the MVP on its own.
- **US2 (P2)**: Extends `process_refund_request`'s denial branch (created in T023). Testable on its own once built.
- **US3 (P3)**: Reuses the complaint de-duplication introduced in T031.

### Within Each Story

- Tests are written and observed failing before the implementation they cover (Principle I)
- Database accessors before the tools that call them
- Tools before registration on `_REFUND_TOOLS` and before prompt changes
- Unit tests before trajectory tests

### Parallel Opportunities

- **Phase 2**: T007+T008 (policy engine) are independent of T002–T006 (schema/state) and of T016+T017 (ticket node) — three parallel tracks. Within the loop tasks, T009→T010, T011→T012, T013→T014 must each stay ordered, and T015 requires all of them.
- **Phase 3**: T018, T019, T020 touch three different test files and can be written in parallel. T027 is a separate file from all implementation tasks.
- **Phase 4**: T028 and T029 are different test files. T032 is independent of both.
- **Phase 6**: T037, T038, T039 touch three unrelated files.

Tasks in the same file are never marked `[P]`: T019/T029/T033 all edit `tests/unit/test_refund_tools.py` and are sequential across phases, as are T021/T030 in `db.py` and T023/T031 in `refund_tools.py`.

---

## Parallel Example: Phase 2 Foundational

```bash
# Three independent tracks once T001 lands:
Track A: T002 → T003 → T004 → T005 → T006      # schema and state
Track B: T007 → T008                            # policy engine (no dependency on the schema)
Track C: T016 → T017                            # refund ticket node

# Then the loop, which needs the tools and state in place:
T009 → T010, T011 → T012, T013 → T014, then T015 to wire the graph
```

## Parallel Example: User Story 1

```bash
# Write all three failing test files together:
Task: "Refund request persistence tests in tests/unit/test_db.py"           # T018
Task: "process_refund_request tests in tests/unit/test_refund_tools.py"     # T019
Task: "CLI refund output test in tests/unit/test_cli.py"                    # T020
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1: Setup — T001
2. Phase 2: Foundational — T002–T017 (**critical path; blocks everything**)
3. Phase 3: User Story 1 — T018–T027
4. **STOP and VALIDATE**: run quickstart.md scenarios A and B, and confirm a `refund_requests` row with the correct amount
5. Demo: a customer can get a qualifying refund request filed, and unqualifying ones are refused with a reason

The MVP is genuinely useful on its own: refunds are correctly granted and correctly refused.
What it lacks is the audit trail — denied customers are told why, but nothing is recorded.

### Incremental Delivery

1. Setup + Foundational → policy engine and conversation loop exist
2. \+ US1 → refunds filed correctly (**MVP**)
3. \+ US2 → denials logged, complaints de-duplicated
4. \+ US3 → complaint-only conversations captured
5. \+ Polish → version bump, docs, full quickstart walkthrough

### Notes

- `[P]` means different files with no incomplete dependencies
- Every test case needs its one-line `(base)` / `(edge)` / `(error)` / `(regression)` comment — Principle I is non-negotiable and reviewers check for it
- Observe each test failing before writing the implementation; a test that passes on first run is not testing what you think
- Commit after each task or logical group
- The policy engine (T007, T008) is where SC-001, SC-008, and SC-009 are actually proven — treat its test coverage as the highest-value work in this feature
