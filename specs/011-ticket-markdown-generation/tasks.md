---

description: "Task list template for feature implementation"
---

# Tasks: Ticket Markdown Generation

**Input**: Design documents from `specs/011-ticket-markdown-generation/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

**Tests**: Required, not optional — the project constitution's Principle I (Test-First,
NON-NEGOTIABLE) mandates a failing test before every implementation change. Every test task
below must add a test carrying a one-line comment stating what it verifies and its category
(`(base)`, `(edge)`, `(error)`, `(regression)`), per the constitution.

**Organization**: Tasks are grouped by user story (spec.md) to enable independent
implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- File paths are exact and relative to the repository root

## Path Conventions

Single project (per plan.md's Project Structure): `src/customer_support_fde/`, `tests/unit/`.

---

## Phase 1: Setup

**Purpose**: Create the new module's file so Foundational tests have something to import against.

- [X] T001 Create `src/customer_support_fde/tickets.py` as an empty module (module-level
      docstring only) so `tests/unit/test_tickets.py` can `import` it in Phase 2.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: (1) The shared file-writing plumbing both `write_order_ticket` (US1) and
`write_refund_ticket` (US3) depend on (`contracts/tickets-module.md`), and (2) collapsing the
graph's two separate terminal ticket nodes into one dispatching `ticket_gen_node`
(`research.md` Decision 1), which both stories' branches build on.

**⚠️ CRITICAL**: No user story task may begin until this phase is complete.

- [X] T002 Write failing unit tests in `tests/unit/test_tickets.py` for `tickets.py`'s shared
      infrastructure: `tickets_dir()` returns `Path("tickets")` by default and
      `Path(os.environ["CUSTOMER_SUPPORT_TICKETS_DIR"])` when that env var is set (base); the
      shared write path creates a missing tickets directory before writing (FR-007, base); and
      an `OSError` raised during directory creation or write is caught, logged, and results in
      the caller getting `None` back with no exception propagating (FR-011, SC-006, error).
- [X] T003 Implement `tickets_dir()` and a shared internal write helper
      (`mkdir(parents=True, exist_ok=True)` + `write_text` wrapped in `try/except OSError` that
      logs via `logging.getLogger(__name__)` and returns `None` on failure) in
      `src/customer_support_fde/tickets.py`. Depends on: T002 (must fail first, then pass).
- [X] T004 Update `tests/unit/test_cart_summary_and_ticket_nodes.py`'s existing
      `test_refund_ticket_node_produces_documented_shape` and
      `test_refund_ticket_node_handles_no_order_identified` to call the single `ticket_gen_node`
      (dropping the separate `refund_ticket_node` import) — both existing fixtures already set
      `"destination": "refund"`/`"destination": "order_support"`, so calling the unified entry
      point should produce the exact same results as before (regression). This will fail until
      T005 lands.
- [X] T005 In `src/customer_support_fde/nodes/ticket_gen_node.py`, rename today's `ticket_gen_node`
      body to `_order_ticket_node` and today's `refund_ticket_node` body to `_refund_ticket_node`,
      then add a public dispatcher:
      ```python
      def ticket_gen_node(state: SupportState) -> SupportState:
          if state["destination"] == "refund":
              return _refund_ticket_node(state)
          return _order_ticket_node(state)
      ```
      In `src/customer_support_fde/graph.py`, remove the `refund_ticket_node` import and its
      separate node registration/`-> END` edge; register only `ticket_gen_node` and route both
      `graph.add_edge("cart_summary", ...)` and the `refund_await_customer` "resolved" branch to
      it (`contracts/tickets-module.md`). Depends on: T004 (must fail first, then pass).

**Checkpoint**: One node, `ticket_gen_node`, handles both destinations with unchanged behavior;
`tickets.py` can resolve a folder, create it, and write/fail safely. Ready for both ticket-type
branches to gain their new markdown-writing behavior.

---

## Phase 3: User Story 1 - Order ticket produced for a confirmed order (Priority: P1) 🎯 MVP

**Goal**: When an order/support interaction concludes with a confirmed order, write a markdown
ticket (ordered items + total, nothing else) to the tickets folder.

**Independent Test**: Run a conversation that ends in a confirmed order and verify
`tickets/order-<order_id>.md` exists, listing the ordered items and the total (spec.md US1).

### Tests for User Story 1

- [X] T006 [P] [US1] Write failing unit tests in `tests/unit/test_tickets.py` for
      `write_order_ticket`: given a non-empty `order_ticket["lines"]`, it writes
      `tickets/order-<order_id>.md` containing every line's name/quantity/unit price/line total
      and the total, and returns that path (FR-001, FR-002, base); given empty `lines`, it
      writes nothing and returns `None` (FR-003, SC-002, edge); a second call for the same
      `order_id` replaces the first file — exactly one `order-<id>.md` remains (FR-008, SC-005,
      edge).
- [X] T007 [P] [US1] Write failing unit tests in
      `tests/unit/test_cart_summary_and_ticket_nodes.py` for `ticket_gen_node`'s new
      file-writing side effect on the order branch (using
      `monkeypatch.setenv("CUSTOMER_SUPPORT_TICKETS_DIR", str(tmp_path))`): a state with a
      non-empty `order_summary` (`"destination": "order_support"`) results in a ticket file on
      disk under `tmp_path` (base); a state with `order_summary=None` (the existing "nothing to
      summarize" case) results in no file being written (FR-003, edge).

### Implementation for User Story 1

- [X] T008 [US1] Implement `_render_order_ticket(order_ticket)` (plain f-string/markdown, per
      `data-model.md` § Order Ticket File: items with name/quantity/unit price/line total, then
      the total — no other content, no generated-at timestamp) and `write_order_ticket(order_ticket)`
      (gates on non-empty `lines`, builds the `order-<order_id>.md` path, delegates to the
      Phase 2 write helper) in `src/customer_support_fde/tickets.py`. Depends on: T006 (must
      fail first, then pass).
- [X] T009 [US1] In `_order_ticket_node`
      (`src/customer_support_fde/nodes/ticket_gen_node.py`), add a call to
      `tickets.write_order_ticket(order_ticket)` after building the `order_ticket` dict, before
      returning state (`contracts/tickets-module.md`). Depends on: T008, T007 (must fail first,
      then pass).

**Checkpoint**: User Story 1 is fully functional and independently testable — confirming an
order produces exactly the required ticket file.

---

## Phase 4: User Story 2 - No ticket for support-only questions (Priority: P2)

**Goal**: When an order/support interaction concludes with no confirmed order (support-only
questions, or an abandoned cart), no ticket file is written.

**Independent Test**: Run a conversation that only asks questions (or abandons a started order)
and verify no new file appears under `tickets/` (spec.md US2). This story exercises the same
`write_order_ticket` empty-`lines` gate User Story 1 already implements (`research.md`
Decision 4) — it adds explicit coverage for the negative case rather than new production code.

### Tests for User Story 2

- [X] T010 [P] [US2] Write failing* unit tests in
      `tests/unit/test_cart_summary_and_ticket_nodes.py` proving `ticket_gen_node` writes no
      ticket file (`monkeypatch.setenv("CUSTOMER_SUPPORT_TICKETS_DIR", str(tmp_path))`,
      then assert `list(tmp_path.iterdir())` is empty) for: a support-only conversation where
      `order_summary` was never built (FR-003, SC-002, edge); and a cart that was started
      (`menu_items` non-empty) but never confirmed into an `order_summary` (FR-003, spec.md edge
      case, edge). *If Phase 3 already landed, these will pass immediately — write them anyway,
      run them, and confirm they pass for the reason FR-003 requires, not by accident.

**Checkpoint**: User Stories 1 AND 2 both hold — an order always gets a ticket, a non-order
never does.

---

## Phase 5: User Story 3 - Refund ticket captures complaint outcome (Priority: P1)

**Goal**: When a refund-agent interaction concludes, always write a markdown ticket containing
the issue/complaint, the customer's sentiment, the order ID (or "Unknown"), and whether a
refund request was created. Order ID, sentiment, and refund-created status come from graph
state exactly as today; only the issue/complaint text is new, read from the conversation
transcript by a plain LLM call inside `ticket_gen_node` (`research.md` Decisions 5, 5a) — no
changes to `tools/refund_tools.py` or `state.py`.

**Independent Test**: Run a refund conversation that ends with a refund request created, and
separately one that ends with none created; verify each produces a ticket file with the
complaint, sentiment, order ID, and the correct refund-created status (spec.md US3).

### Tests for User Story 3

- [X] T011 [P] [US3] Write failing unit tests in
      `tests/unit/test_cart_summary_and_ticket_nodes.py` for the refund branch's new behavior
      (mocking `_build_llm` in `nodes/ticket_gen_node.py` the same way
      `tests/unit/test_refund_agent.py` mocks `refund_agent.py`'s, via
      `monkeypatch.setattr(ticket_gen_node_module, "_build_llm", lambda: fake_llm)`):
      `_extract_refund_issue(state)` returns the model's stripped reply when
      `refund_conversation_summary` and/or `messages` are present (`contracts/refund-issue-extraction.md`,
      base); returns `None` **without** invoking the model when both are empty/absent (edge);
      returns `None` when the model's reply is `"None"` (case-insensitive) (edge); returns
      `None` and logs a `WARNING` when the LLM call raises (error); and separately, the
      `refund_ticket` dict `_refund_ticket_node` returns has `issue` set from that helper's
      return value and `refund_created` set to `state["refund_request"] is not None`
      (`data-model.md` § Refund Ticket, base), including when `issue` resolves to `None` (edge).
- [X] T012 [P] [US3] Write failing unit tests in `tests/unit/test_tickets.py` for
      `write_refund_ticket`: a known `order_id` writes `tickets/refund-<order_id>.md` containing
      the issue, sentiment, order ID, and `Refund Request Created: Yes`/`No` (FR-004, FR-005,
      base); `order_id=None` writes `tickets/refund-unknown-<uuid4().hex>.md` with the order ID
      rendered as `Unknown` (FR-010, edge); `sentiment=None`/`issue=None` render as
      `unavailable`/`Not recorded` respectively (spec.md edge cases, edge); a second call for
      the same known `order_id` replaces the first file — exactly one `refund-<id>.md` remains
      (FR-008, SC-005, edge).

### Implementation for User Story 3

- [X] T013 [P] [US3] Implement a local `_build_llm()` (same `ChatOpenAI(base_url=..., api_key=...,
      model=...)` shape `refund_agent.py`/`router_agent.py` already use) and
      `_extract_refund_issue(state)` (builds context from `refund_conversation_summary` +
      `messages`, returns `None` on nothing-to-summarize/model-says-none/LLM-exception per
      `contracts/refund-issue-extraction.md`, logging on the exception path) in
      `src/customer_support_fde/nodes/ticket_gen_node.py`. Depends on: T011 (must fail first).
- [X] T014 [US3] Update `_refund_ticket_node`
      (`src/customer_support_fde/nodes/ticket_gen_node.py`) to call `_extract_refund_issue(state)`
      and set `issue` and `refund_created` (`state["refund_request"] is not None`) on the
      `refund_ticket` dict it returns. Depends on: T013; makes the second half of T011 pass.
- [X] T015 [P] [US3] Implement `_render_refund_ticket(refund_ticket)` (per `data-model.md` §
      Refund Ticket File, no generated-at timestamp) and `write_refund_ticket(refund_ticket)` (unknown-id
      fallback naming per `research.md` Decision 3, unconditional write, delegates to the
      Phase 2 write helper) in `src/customer_support_fde/tickets.py`. Depends on: T012 (must
      fail first, then pass).
- [X] T016 [US3] In `_refund_ticket_node`
      (`src/customer_support_fde/nodes/ticket_gen_node.py`), add a call to
      `tickets.write_refund_ticket(refund_ticket)` after building the `refund_ticket` dict,
      before returning state. Depends on: T014, T015.

**Checkpoint**: All three user stories are independently functional — order tickets, the
no-ticket case, and refund tickets (both outcomes) all behave per spec.md.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: End-to-end confirmation and release hygiene across all three stories.

- [X] T017 [P] Execute `quickstart.md` scenarios A–G against the CLI
      (`src/customer_support_fde/cli.py`) with `CUSTOMER_SUPPORT_TICKETS_DIR` pointed at a
      scratch folder, and confirm each resulting ticket file's content matches its scenario.
      Depends on: T009, T010, T016 (all story implementations complete).
- [X] T018 [P] Bump the version in `pyproject.toml` (MINOR — e.g. `0.5.0` → `0.6.0`) per the
      constitution's Principle IV, since this is a backward-compatible feature addition.
- [X] T019 Run `uv run pytest` (full suite) and confirm everything passes, including suites this
      feature doesn't touch at all — `test_refund_tools.py`, `test_refund_agent.py`,
      `test_cli.py`, `test_router_agent.py`, `test_menu_tools.py`, `test_db.py`, and both
      `tests/integration/*_trajectory.py` suites — none of which this feature modifies, so a
      pass here confirms the state/tool surface genuinely didn't change. Depends on: T017.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories. Includes the
  two-nodes-to-one consolidation (T004–T005), since both stories' branches live inside it.
- **User Story 1 (Phase 3)**: Depends on Foundational only.
- **User Story 2 (Phase 4)**: Depends on Foundational; in practice reuses User Story 1's
  implementation, so run it after Phase 3 even though it adds no new production code.
- **User Story 3 (Phase 5)**: Depends on Foundational only — independent of Phases 3/4, touches
  entirely different code within `ticket_gen_node.py` (the refund branch) and a different part
  of `tickets.py`.
- **Polish (Phase 6)**: Depends on Phases 3, 4, and 5 all being complete.

### User Story Dependencies

- **User Story 1 (P1)**: No dependency on other stories.
- **User Story 2 (P2)**: Test-only; reuses User Story 1's `write_order_ticket` gating. Sequenced
  after US1 for that reason, not a hard code dependency.
- **User Story 3 (P1)**: No dependency on User Story 1 or 2 — can be implemented in parallel by
  a different contributor once Foundational is done. Note both stories' implementation tasks
  land in the *same file* (`nodes/ticket_gen_node.py`, different functions) alongside
  `tickets.py` (different functions again), so true simultaneous editing by two people needs
  care even though the stories are logically independent.

### Within Each User Story

Tests before implementation; each implementation task lists the exact prior task(s) whose tests
it must turn green.

### Parallel Opportunities

- T006 and T007 (US1, different files) can run in parallel.
- T011 and T012 (US3, different files) can run in parallel.
- T013 and T015 (US3, different files — `nodes/ticket_gen_node.py` vs. `tickets.py`) can run in
  parallel once their respective tests (T011, T012) exist.
- Once Foundational (Phase 2) is done, User Story 1 (Phase 3) and User Story 3 (Phase 5) can
  proceed in parallel conceptually — see the file-overlap note above before assigning them to
  two different contributors at the same time.
- T017 and T018 (Phase 6) can run in parallel.

---

## Parallel Example: User Story 1

```bash
# After Phase 2 (Foundational) is complete:
Task: "Write failing unit tests for write_order_ticket in tests/unit/test_tickets.py"
Task: "Write failing unit tests for ticket_gen_node's order-branch file-writing side effect in tests/unit/test_cart_summary_and_ticket_nodes.py"
```

## Parallel Example: User Story 3

```bash
# After Phase 2 (Foundational) is complete:
Task: "Write failing unit tests for _extract_refund_issue and the refund_ticket dict's new fields in tests/unit/test_cart_summary_and_ticket_nodes.py"
Task: "Write failing unit tests for write_refund_ticket in tests/unit/test_tickets.py"
```

---

## Implementation Strategy

### MVP First (User Stories 1 + 3 — both P1)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational (blocks everything, includes the node consolidation).
3. Complete Phase 3: User Story 1 (order tickets).
4. Complete Phase 5: User Story 3 (refund tickets) — logically independent of Phase 3.
5. **STOP and VALIDATE**: both P1 stories now deliver the feature's core value end-to-end.

### Incremental Delivery

1. Setup + Foundational → one unified `ticket_gen_node`, foundation ready.
2. User Story 1 → test independently → order tickets work (MVP slice #1).
3. User Story 3 → test independently → refund tickets work (MVP slice #2).
4. User Story 2 → confirms the negative case explicitly (P2, lower urgency, no new code).
5. Polish → manual quickstart pass, version bump, full regression run.

### Parallel Team Strategy

With two contributors: one takes User Story 1 (Phase 3, then Phase 4), the other takes User
Story 3 (Phase 5). Both land changes in `nodes/ticket_gen_node.py`, so coordinate on that file
specifically even though the two branches (`_order_ticket_node` vs. `_refund_ticket_node`) don't
otherwise interact.

---

## Notes

- [P] tasks touch different files and have no unmet dependency.
- [Story] labels map every user-story-phase task to spec.md's US1/US2/US3 for traceability.
- Every test task's actual test functions must carry the constitution's one-line
  what-it-verifies-plus-category comment (`(base)`, `(edge)`, `(error)`, `(regression)`).
- Commit after each task or logical group.
- Stop at either checkpoint to validate a story independently before continuing.
