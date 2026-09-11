---

description: "Task list for Cart Total Lookup"
---

# Tasks: Cart Total Lookup

**Input**: Design documents from `/specs/006-cart-total-lookup/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/get_cart_total.md](./contracts/get_cart_total.md),
[quickstart.md](./quickstart.md)

**Tests**: Included and REQUIRED — this project's constitution (Principle I, Test-First,
NON-NEGOTIABLE) mandates a failing test before every implementation change, and every test
case carries a one-line `(base)`/`(edge)`/`(error)`/`(regression)` comment per the constitution.

**Organization**: Tasks are grouped by user story (from spec.md) to enable independent
implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Exact file paths are included in each description

## Path Conventions

Single project layout (existing): `src/customer_support_fde/`, `tests/unit/` at repository root.

---

## Phase 1: Setup

**Purpose**: Confirm a clean, known-good starting point. No new dependencies, directories, or
tooling are required for this feature (see [research.md](./research.md)).

- [ ] T001 On branch `006-cart-total-lookup`, run `uv run pytest` at the repository root and
      confirm the existing suite passes before any change, establishing the baseline this
      feature must not regress.

**Checkpoint**: Baseline green — safe to begin foundational work.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Extract the shared, single-source-of-truth total calculation that every user
story (and the existing order-confirmation flow) depends on. Per [research.md](./research.md),
duplicating this rounding logic instead of sharing it would violate FR-004/SC-003 and
Constitution Principle III.

**⚠️ CRITICAL**: No user story task may begin until this phase is complete.

- [ ] T002 [P] In `tests/unit/test_menu_tools.py`, add failing unit tests for a new
      `cart_total(menu_items, menu)` helper (not yet implemented): a cart with one item at
      quantity 1 returns that item's price (base); a cart with multiple distinct items and
      quantities > 1 returns `Σ price × quantity` (base); an empty `menu_items` dict returns
      `None` (edge, FR-005); a cart whose raw sum lands on a fractional cent rounds **up** to
      the nearest cent, matching `ROUND_CEILING` (edge, FR-004). Each test gets its own
      one-line `# ... (base)`/`(edge)` comment per Constitution Principle I.
- [ ] T003 [P] In `tests/unit/test_cart_summary_and_ticket_nodes.py`, add a failing regression
      test asserting that for a given `menu_items`/`menu` pair, `cart_total(menu_items, menu)`
      equals the `total` produced by `cart_summary_node.build_order_summary(menu_items, menu)`
      (regression, guards FR-004/SC-003 against the two call sites drifting apart per
      [research.md](./research.md)).
- [ ] T004 Implement `cart_total(menu_items: dict[str, int], menu: list[MenuItem]) -> float | None`
      in `src/customer_support_fde/tools/menu_tools.py`, next to the existing `price_for_item`
      helper: sum `price_for_item(name, menu) * quantity` over `menu_items` using `Decimal`,
      round up to the nearest cent with `ROUND_CEILING` (matching the logic currently inlined
      in `cart_summary_node.build_order_summary`), and return `None` when `menu_items` is
      empty. Depends on: T002.
- [ ] T005 Refactor `build_order_summary` in
      `src/customer_support_fde/nodes/cart_summary_node.py` to compute its `total` by calling
      the new `menu_tools.cart_total()` helper instead of its inline `Decimal`/`ROUND_CEILING`
      calculation, leaving the per-line `unit_price`/`line_total` computation unchanged.
      Depends on: T004, T003.
- [ ] T006 Run `uv run pytest tests/unit/test_menu_tools.py tests/unit/test_cart_summary_and_ticket_nodes.py -v`
      and confirm every test (new and pre-existing) passes. Depends on: T005.

**Checkpoint**: Shared `cart_total()` helper exists, is used by the existing order-confirmation
flow, and is proven equivalent to the prior inline logic. User story implementation can begin.

---

## Phase 3: User Story 1 - Customer asks for the running total mid-order (Priority: P1) 🎯 MVP

**Goal**: The order support agent answers "what's my total?" by calling a dedicated tool that
looks up the exact total, instead of computing or estimating it itself (FR-001, FR-002,
FR-003, FR-006).

**Independent Test**: Add a known set of items with known prices to a cart, ask "what's my
total?", and verify the reported total exactly matches the sum of the item prices.

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [ ] T007 [P] [US1] In `tests/unit/test_cart_tools.py`, add failing unit tests for a new
      `get_cart_total` tool (not yet implemented): a cart with a single item at quantity 1
      returns a rendered string stating that item's exact price (base); a cart with multiple
      distinct items at varying quantities returns a rendered string stating the correct
      combined total (base), per `contracts/get_cart_total.md` items 1-2.
- [ ] T008 [P] [US1] In `tests/unit/test_order_support_agent.py`, add a failing unit test
      asserting `get_cart_total` is present in `order_support_agent._ORDER_TOOLS` (and thus
      bound on the agent's model and included in `order_tools`) (base).

### Implementation for User Story 1

- [ ] T009 [US1] Implement `get_cart_total` in `src/customer_support_fde/tools/cart_tools.py`:
      a no-argument `@tool` (state-only, via `InjectedState`, mirroring `get_menu`'s pattern —
      not a `Command`, since it doesn't mutate state) that calls `menu_tools.cart_total(state["menu_items"], state["menu"])`
      and, when it returns a number, renders a string stating the total to two decimal places
      (e.g. `"Your current cart total is $23.50."`) per `contracts/get_cart_total.md`.
      Depends on: T007.
- [ ] T010 [US1] In `src/customer_support_fde/nodes/order_support_agent.py`, add
      `get_cart_total` to `_ORDER_TOOLS`, and update `SYSTEM_PROMPT` to instruct the agent to
      use the tool for any cart-total question rather than computing or estimating it itself
      (FR-001/FR-006). Depends on: T009, T008.
- [ ] T011 [US1] Run `uv run pytest tests/unit/test_cart_tools.py tests/unit/test_order_support_agent.py -v`
      and confirm all User Story 1 tests pass. Depends on: T010.

**Checkpoint**: User Story 1 is fully functional and independently testable — a customer with
items in the cart can ask for and receive an exact total via the new tool.

---

## Phase 4: User Story 2 - Customer updates the cart, then asks for the total again (Priority: P2)

**Goal**: A total requested after the cart changes reflects the updated cart contents, not a
stale figure (FR-007).

**Independent Test**: Add items, ask for the total, then remove or add an item and ask again —
verify the second total reflects only the updated cart contents.

### Tests for User Story 2

> **NOTE: Write this test FIRST, ensure it FAILS (or is trivially satisfied) before relying on it**

- [ ] T012 [P] [US2] In `tests/unit/test_cart_tools.py`, add a failing unit test that calls
      `get_cart_total` against one `menu_items` dict, then calls it again against a second
      `menu_items` dict representing the cart after an item was added (or removed), and
      asserts the second result reflects only the updated cart, independent of the first call
      (base, FR-007).

### Implementation for User Story 2

- [ ] T013 [US2] Run `uv run pytest tests/unit/test_cart_tools.py -v` and confirm T012 passes
      without further code changes — `get_cart_total` reads `state["menu_items"]` fresh via
      `InjectedState` on every invocation (no caching, per the alternative rejected in
      [research.md](./research.md)), so no new implementation is expected here. If it fails,
      fix `get_cart_total` in `src/customer_support_fde/tools/cart_tools.py` so it never reuses
      a previously computed total. Depends on: T012.

**Checkpoint**: User Stories 1 and 2 both work independently — totals stay accurate across
cart edits within a conversation.

---

## Phase 5: User Story 3 - Customer asks for the total with an empty cart (Priority: P3)

**Goal**: Asking for the total before adding anything returns a clear "cart is empty" message,
never a numeric total (FR-005).

**Independent Test**: With no items in the cart, ask "what's my total?" and verify the
response clearly states there's nothing in the cart yet, with no numeric total given.

### Tests for User Story 3

> **NOTE: Write this test FIRST, ensure it FAILS before implementation**

- [ ] T014 [P] [US3] In `tests/unit/test_cart_tools.py`, add a failing unit test asserting that
      calling `get_cart_total` with an empty `menu_items` dict returns a message stating the
      cart is empty, with no dollar figure present in the response (edge, FR-005), per
      `contracts/get_cart_total.md` item 3.

### Implementation for User Story 3

- [ ] T015 [US3] In `get_cart_total` (`src/customer_support_fde/tools/cart_tools.py`), add the
      branch for when `menu_tools.cart_total(...)` returns `None`: return the empty-cart
      message instead of formatting a dollar figure. Depends on: T014.
- [ ] T016 [US3] Run `uv run pytest tests/unit/test_cart_tools.py -v` and confirm all
      `get_cart_total` tests (US1, US2, US3) pass together. Depends on: T015.

**Checkpoint**: All three user stories are independently functional — the tool correctly
handles a priced cart, a cart that changed mid-conversation, and an empty cart.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Whole-suite verification and the manual/observability checks from
[quickstart.md](./quickstart.md) that don't belong to any single user story.

- [ ] T017 Run `uv run pytest` at the repository root and confirm the full suite passes with no
      regressions outside this feature's own tests.
- [ ] T018 [P] Execute the manual end-to-end scenario in
      `specs/006-cart-total-lookup/quickstart.md` (steps 1-5) against a locally running agent
      (after `customer-support-fde --init-db`), confirming SC-001 through SC-004 hold in
      practice, not just in unit tests.
- [ ] T019 [P] Per `specs/006-cart-total-lookup/quickstart.md` step 6, confirm in LangSmith that
      the `get_cart_total` tool call appears as a traced step with no additional custom logging
      needed, satisfying Constitution Principle IV (Observability).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup (T001) completion — BLOCKS all user stories.
- **User Story 1 (Phase 3)**: Depends on Foundational (Phase 2) completion. No dependency on
  US2/US3.
- **User Story 2 (Phase 4)**: Depends on Foundational (Phase 2) completion, and in practice
  exercises the tool built in Phase 3 (T009/T010) — sequence after US1 even though it adds no
  new production code.
- **User Story 3 (Phase 5)**: Depends on Foundational (Phase 2) completion; its implementation
  task (T015) edits the same function US1 created (T009), so do Phase 3 before Phase 5.
- **Polish (Phase 6)**: Depends on all of Phases 3-5 being complete.

### Within Each Phase

- Tests are written and confirmed failing before their corresponding implementation task.
- Foundational helper (T004) before anything that calls it (T005, T009).
- `cart_summary_node` refactor (T005) before its regression test is expected to pass (T006).

### Parallel Opportunities

- T002 and T003 (Foundational tests, different files) can run in parallel.
- T007 and T008 (US1 tests, different files) can run in parallel.
- T012, T014 (US2/US3 tests) can each run in parallel with other same-phase test-writing tasks
  once Phase 3 implementation (T009/T010) exists to test against.
- T018 and T019 (Polish, independent manual checks) can run in parallel.

---

## Parallel Example: Foundational Phase

```bash
# Launch both foundational tests together (different files):
Task: "Add failing tests for cart_total() in tests/unit/test_menu_tools.py"
Task: "Add failing regression test in tests/unit/test_cart_summary_and_ticket_nodes.py"
```

## Parallel Example: User Story 1

```bash
# Launch both User Story 1 tests together (different files):
Task: "Add failing tests for get_cart_total in tests/unit/test_cart_tools.py"
Task: "Add failing tool-registration test in tests/unit/test_order_support_agent.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001).
2. Complete Phase 2: Foundational (T002-T006) — CRITICAL, blocks all stories.
3. Complete Phase 3: User Story 1 (T007-T011).
4. **STOP and VALIDATE**: Run the Phase 3 checkpoint tests and manually ask a running agent for
   the total on a non-empty cart.
5. This alone satisfies the user's original request ("give it a tool for the total") for the
   common case; US2 and US3 harden it against edits mid-conversation and the empty-cart case.

### Incremental Delivery

1. Setup + Foundational → shared, correctness-guaranteed total calculation ready.
2. Add User Story 1 → test independently → MVP: agent answers total questions via the tool.
3. Add User Story 2 → test independently → totals stay correct across cart edits.
4. Add User Story 3 → test independently → empty-cart asks no longer get a numeric answer.
5. Polish → full-suite and manual/observability confirmation.

---

## Notes

- [P] tasks touch different files and have no unmet dependencies within their phase.
- [Story] labels (US1/US2/US3) map tasks to the user stories in `spec.md` for traceability.
- Every test task carries a `(base)`/`(edge)`/`(regression)` tag per Constitution Principle I —
  carry that same one-line comment convention into the actual test code, directly above each
  test function.
- Commit after each task or logical group; verify each test fails before implementing, then
  passes after.
- No `[NEEDS CLARIFICATION]` markers exist in spec.md or plan.md, and no complexity violations
  were recorded in plan.md's Complexity Tracking — this task list introduces no additional
  deviations.
