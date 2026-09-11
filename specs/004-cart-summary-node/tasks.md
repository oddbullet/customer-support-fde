---

description: "Task list for Cart Summary at Order Confirmation"
---

# Tasks: Cart Summary at Order Confirmation

**Input**: Design documents from `/specs/004-cart-summary-node/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/cart-summary-node.md](./contracts/cart-summary-node.md)

**Tests**: REQUIRED, not optional. Constitution Principle I (Test-First) is NON-NEGOTIABLE: every test below is written and watched to fail before the implementation task that follows it, and every test case carries a one-line comment above its definition stating what it verifies plus a `(base)` / `(edge)` / `(error)` / `(regression)` category tag.

**Organization**: Tasks are grouped by user story so each story can be implemented, tested, and demoed independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

Single project: `src/customer_support_fde/`, `tests/` at repository root — unchanged from 001–003.

⚠️ **Most tasks in this feature touch one of two files** (`src/customer_support_fde/nodes/cart_summary_node.py` and `tests/unit/test_cart_summary_and_ticket_nodes.py`), so genuine `[P]` opportunities are rare. `[P]` is marked only where the files truly do not overlap — do not parallelize the rest.

---

## Phase 1: Setup (Rename — no behavior change)

**Purpose**: Perform the `confirm_node` → `cart_summary` rename the feature request asked for, as a pure move with no behavior change, so the behavioral work in later phases lands on a clean baseline.

**⚠️ Verify after this phase**: `pytest` is fully green. If it is not, the rename was not behavior-neutral — fix before continuing.

- [X] T001 Rename `src/customer_support_fde/nodes/confirm_node.py` to `src/customer_support_fde/nodes/cart_summary_node.py` using `git mv` (preserves history), and rename the function `confirm_node` to `cart_summary_node`, leaving the pass-through body (`return state`) untouched for now
- [X] T002 Update `src/customer_support_fde/graph.py`: import `cart_summary_node` from `customer_support_fde.nodes.cart_summary_node`; change `graph.add_node("confirm_node", confirm_node)` to `graph.add_node("cart_summary", cart_summary_node)`; retarget the `_route_from_await_customer` mapping to `{"continue": "call_model", "confirmed": "cart_summary"}`; retarget `graph.add_edge("confirm_node", "ticket_gen_node")` to `graph.add_edge("cart_summary", "ticket_gen_node")`
- [X] T003 Rename `tests/unit/test_confirm_and_ticket_nodes.py` to `tests/unit/test_cart_summary_and_ticket_nodes.py` using `git mv`, updating the import and the `test_confirm_node_returns_state_unchanged` test name/comment to match the new node name (this pass-through test is deleted in T014 once the node does real work)
- [X] T004 Update `tests/integration/test_order_support_trajectory.py`: change the expected trajectory node name `"confirm_node"` to `"cart_summary"` (~line 367), and rename `test_confirming_with_an_empty_cart_never_reaches_confirm_node` plus its `(edge)` comment (~lines 378–379) to reference `cart_summary`

**Checkpoint**: Rename complete, full suite green, zero behavior change.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The state field and the price lookup that every user story depends on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T005 [P] Add `order_summary: dict | None` to the `SupportState` TypedDict in `src/customer_support_fde/state.py`, declared after `order_ticket`
- [X] T006 [P] Add `"order_summary": None` to the initial state dict passed to `graph.invoke` in `src/customer_support_fde/cli.py` (inside `run`)
- [X] T007 [P] Add `"order_summary": None` to every hand-built initial state dict in `tests/integration/test_order_support_trajectory.py` (~lines 90, 142, 203, 267, 325, 411) and to `_base_state()` in `tests/unit/test_cart_summary_and_ticket_nodes.py`. Also required (not enumerated in this task's file list, but the same `SupportState` shape and needed to keep `pytest` green — LangGraph's `InjectedState` validates the full state schema): `_base_state()` in `tests/unit/test_order_support_agent.py` and `_new_order_support_initial_state()` in `tests/integration/test_router_trajectory.py`.
- [X] T008 [P] Write failing unit tests for `price_for_item` in `tests/unit/test_menu_tools.py`: exact canonical-name match returns that entry's `price` `(base)`; a name absent from the menu returns `None` `(edge)`; an empty menu list returns `None` `(edge)`; a near-miss name that `resolve_menu_item` would fuzzy-match returns `None` rather than another item's price `(regression)` — this last one guards the mispricing risk in [research.md](./research.md) §4
- [X] T009 Implement `price_for_item(name: str, menu: list[MenuItem]) -> float | None` in `src/customer_support_fde/tools/menu_tools.py`: exact match on each entry's `name` field, returning that entry's `price`, else `None`. Exact match only — no case or whitespace normalization, no fuzzy fallback, never raises (per [contracts/cart-summary-node.md](./contracts/cart-summary-node.md))

**Checkpoint**: `order_summary` exists on state, prices are lookupable, `pytest tests/unit/test_menu_tools.py` green.

---

## Phase 3: User Story 1 - Customer sees an itemized order summary with total (Priority: P1) 🎯 MVP

**Goal**: At confirmation, the customer receives a recap naming every ordered dish with its quantity, unit price, line total, and one order total.

**Independent Test**: Run an ordering conversation that adds a few items, confirm, and check the reply names every item, states a quantity for each, and states one order total that adds up. Delivers value with US2 and US3 unbuilt.

### Tests for User Story 1 ⚠️

> **Write these FIRST and watch them FAIL before T013–T016.**

- [X] T010 [US1] Add failing unit tests for `build_order_summary` happy paths in `tests/unit/test_cart_summary_and_ticket_nodes.py`, against a `SAMPLE_MENU` fixture: a two-item cart `{"Kung Pao Chicken": 2, "Hot and Sour Soup": 1}` priced `12.95`/`5.50` yields `line_total` `25.90` and `5.50` and `total` `31.40` `(base)`; a single-unit cart yields one line whose `line_total` equals the unit price `(base)`; `lines` preserve `menu_items` insertion order and carry exactly the four fields `name`/`quantity`/`unit_price`/`line_total` `(base)`
- [X] T011 [US1] Add failing unit tests for `build_order_summary` invariants in the same file: `total` equals the sum of the stored `line_total` values for a cart whose products carry fractional cents `(edge)` — this is the FR-006 rounding invariant, assert it directly rather than against a hardcoded number; and `build_order_summary` does not mutate the `menu_items` dict it is given `(regression)`
- [X] T012 [US1] Add failing unit tests in the same file for `render_order_summary` on a fully-priced summary — every item name and quantity appears in the output, each line shows unit price and line total formatted `$%.2f`, a single `Total: $31.40` line is present `(base)` — and for `cart_summary_node`, which must set `state["order_summary"]` to the built summary and return exactly one `AIMessage` in `messages` whose content is the rendered text `(base)`. Delete the T003 pass-through test in this task.

### Implementation for User Story 1

- [X] T013 [US1] Implement `build_order_summary(menu_items: dict[str, int], menu: list[MenuItem]) -> dict` in `src/customer_support_fde/nodes/cart_summary_node.py`, returning `{"lines": [...], "unpriced": [...], "total": float | None}`. Compute each `line_total` as `Decimal(str(unit_price)) * quantity` quantized to `Decimal("0.01")` with `ROUND_HALF_UP`, stored as `float`; compute `total` as the sum of the **already quantized** line totals (never a rounded sum of unrounded products — FR-006). Operate on a copy; never mutate the input. `unpriced` stays `[]` in this phase — US3 fills it.
- [X] T014 [US1] Implement `render_order_summary(summary: dict) -> str` in the same file for the fully-priced case: a `Here's your order:` header, one `- {name} x{quantity} @ ${unit_price} each = ${line_total}` line per entry in order, a blank line, then `Total: ${total}`. ASCII only — no em dashes or curly quotes (see the Windows console encoding note in `cli.py`). Every amount formatted `$%.2f`. No truncation or "and others" collapsing regardless of cart size.
- [X] T015 [US1] Implement the `cart_summary_node(state)` body in the same file: call `build_order_summary(state["menu_items"], _load_menu())` then `render_order_summary`, and return `{**state, "order_summary": summary, "messages": [AIMessage(content=rendered)]}`. Return a one-element `messages` list so the `add_messages` reducer appends rather than replaces. Make no LLM call and no tool call. Touch no other state field.
- [X] T016 [US1] Surface the summary to the customer in `src/customer_support_fde/cli.py`'s `_print_result`: in human-readable mode print the rendered summary text (from the final `AIMessage`) before the existing `Destination:`/`Query:` lines when the order was confirmed; in `--json` mode add `"order_summary": state["order_summary"]` to the payload when confirmed. Leave unconfirmed and refund conversations printing exactly what they print today. Without this the feature produces no visible output at all (FR-001).
- [X] T017 [US1] Extend the confirming scenario in `tests/integration/test_order_support_trajectory.py` (`test_full_conversation_confirms_and_produces_order_ticket`) to assert the final state's `order_summary` carries the expected lines and total, and that the last message is the rendered recap `(base)`

**Checkpoint**: A confirmed order produces a correct, visible, itemized summary. This is the MVP — stop and validate here.

---

## Phase 4: User Story 2 - Support ticket matches what the customer was told (Priority: P2)

**Goal**: `order_ticket` carries the same items, quantities, prices, and total the customer saw.

**Independent Test**: Confirm an order, capture the summary, and compare every value on the generated ticket against it — all must agree.

### Tests for User Story 2 ⚠️

> **Write these FIRST and watch them FAIL before T019.**

- [X] T018 [US2] Add failing unit tests for `ticket_gen_node` in `tests/unit/test_cart_summary_and_ticket_nodes.py`: given a state whose `order_summary` is already built, `order_ticket` carries `items` (a copy of `menu_items`) plus `lines`, `unpriced`, and `total` identical to `order_summary`'s `(base)`; the ticket's priced values are copied from `order_summary` rather than recomputed — assert by building a state whose `order_summary` holds deliberately distinctive values and checking the ticket echoes those, not a fresh calculation `(regression)`; and a state with `order_summary` absent or `None` yields `{"lines": [], "unpriced": [], "total": None}` instead of raising `(edge)`

### Implementation for User Story 2

- [X] T019 [US2] Rewrite `ticket_gen_node` in `src/customer_support_fde/nodes/ticket_gen_node.py` to build `order_ticket` as `{"items": dict(state["menu_items"]), "lines": summary["lines"], "unpriced": summary["unpriced"], "total": summary["total"]}`, where `summary` is `state.get("order_summary") or {"lines": [], "unpriced": [], "total": None}`. **Copy** the priced values — do not recompute them; that copying is what makes FR-010/SC-004 structural rather than coincidental.
- [X] T020 [US2] Update the two `order_ticket` assertions in `tests/integration/test_order_support_trajectory.py` (~line 220 `{"items": {"Spring Rolls": 1}}` and ~line 339) to the new priced ticket shape. **Backward-incompatible change** — see Constitution Principle IV callout in [plan.md](./plan.md).

**Checkpoint**: Customer-facing summary and staff-facing ticket cannot disagree.

---

## Phase 5: User Story 3 - Unpriceable or empty orders fail visibly, not silently (Priority: P3)

**Goal**: An item with no menu price is named rather than dropped or zero-priced, and an empty cart produces no total.

**Independent Test**: Build a summary for a cart containing an item absent from the menu and verify it is flagged, not omitted; separately build one for an empty cart and verify `total is None` and the empty wording.

**Note**: Both branches are defensive. `mark_order_confirmed` refuses to confirm an empty cart, so `cart_summary_node` cannot be reached with an empty `menu_items` on today's graph ([research.md](./research.md) §6). These are unit-tested guards against a future graph change producing a `$0.00` receipt — do not delete them as dead code.

### Tests for User Story 3 ⚠️

> **Write these FIRST and watch them FAIL before T023–T024.**

- [X] T021 [US3] Add failing unit tests for `build_order_summary` degraded cases in `tests/unit/test_cart_summary_and_ticket_nodes.py`: an empty cart yields `lines == []`, `unpriced == []`, and `total is None` — assert `is None`, **not** `0.0`, since a zero total reads as a free order rather than an absent one `(edge)`; a cart whose only item is absent from the menu yields `lines == []`, that name in `unpriced`, and `total is None` `(edge)`; a mixed cart prices what it can, lists the rest in `unpriced`, and totals only the priced lines `(edge)`; and across any cart, every `menu_items` key appears exactly once across `lines` + `unpriced` combined `(regression)`
- [X] T022 [US3] Add failing unit tests for `render_order_summary` degraded wording in the same file: an empty summary renders `There's nothing in your order to summarize.` with no amount line `(edge)`; a partially-priced summary names every unpriced item and labels the amount `Subtotal for priced items:` rather than `Total:` `(edge)`; an all-unpriced summary renders the unpriced notice with no amount line at all `(edge)`

### Implementation for User Story 3

- [X] T023 [US3] Extend `build_order_summary` in `src/customer_support_fde/nodes/cart_summary_node.py`: when `price_for_item` returns `None` for a cart key, append that canonical name to `unpriced` (in cart order) instead of building a line; set `total` to `None` whenever `lines` is empty, never `0.0`
- [X] T024 [US3] Extend `render_order_summary` in the same file: emit `There's nothing in your order to summarize.` when `lines` and `unpriced` are both empty; when `unpriced` is non-empty, emit `We couldn't price these items: {names}. A staff member will confirm them with you.` and use the label `Subtotal for priced items:` in place of `Total:`; emit no amount line when `lines` is empty. Exact wording in [contracts/cart-summary-node.md](./contracts/cart-summary-node.md).

**Checkpoint**: All three stories independently functional. No path produces a silently-wrong total.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T025 Run the full suite: `pytest -v` from repo root — all unit and integration tests green
- [X] T026 Verify every new test case carries its one-line what-it-verifies comment with a `(base)`/`(edge)`/`(error)`/`(regression)` tag, per Constitution Principle I
- [X] T027 Walk the manual CLI checks in [quickstart.md](./quickstart.md) with a live `OPENROUTER_API_KEY`, including the `--json` path, confirming every amount serializes cleanly
- [X] T028 Write the PR description: link the failing-then-passing tests (Principle I), name the principles touched, and **explicitly call out the three backward-incompatible changes** (graph node key `confirm_node` → `cart_summary`, module rename, `order_ticket` shape) as required by Principle IV — plus the MINOR version bump rationale from [plan.md](./plan.md)

---

## Phase 7: Simplify pricing (remove `unpriced`, round total once)

**Purpose**: Post-implementation simplification, confirmed with the user after checking
`menu.json`: every real menu price has at most 2 decimal places, and cart keys are always canonical
menu names, so an item can never actually fail to price and per-line rounding-then-summing is a
no-op on real data. Drops the `unpriced` branch as unreachable defensive code and simplifies the
total's arithmetic to a single sum-then-round-up (`ROUND_CEILING`) step. This is a requirement
removal (FR-008, part of User Story 3, part of SC-005), not just an implementation tweak, so
`spec.md` and its downstream docs are updated alongside the code.

- [X] T029 Simplify `build_order_summary` in `src/customer_support_fde/nodes/cart_summary_node.py`: drop the `unpriced` list and the `price_for_item is None` guard (treat as an impossible state — let `Decimal(str(None))` fail naturally if it ever happens); compute each line's raw `Decimal` value unrounded, sum all raw values, then round the sum up once with `ROUND_CEILING` to `Decimal("0.01")`
- [X] T030 Simplify `render_order_summary` in the same file: drop the unpriced-wording branches, back to the single fully-priced / empty-cart shape
- [X] T031 Update `ticket_gen_node` in `src/customer_support_fde/nodes/ticket_gen_node.py`: drop `unpriced` from the ticket shape and the empty-summary default (`{"lines": [], "total": None}`)
- [X] T032 Update `tests/unit/test_cart_summary_and_ticket_nodes.py`: delete the `unpriced`-specific `build_order_summary`/`render_order_summary` tests; replace the round-then-sum invariant test with a new `(regression)` test locking in the always-rounds-up behavior (e.g. a `4.321`-priced item totals `4.33`, not `4.32`); drop `unpriced` from the empty-cart and `ticket_gen_node` test assertions
- [X] T033 Update `tests/integration/test_order_support_trajectory.py`: drop `unpriced` from both `order_ticket` assertions
- [X] T034 Update spec-kit docs for consistency: narrow `spec.md`'s User Story 3/SC-005 to the empty-cart case only, remove FR-008, update the fractional-cents Edge Case and Assumptions to state menu prices always have ≤2 decimal places and the total rounds up; update `data-model.md` and `contracts/cart-summary-node.md` to drop `unpriced` and describe the sum-then-round-up rule; update `research.md` §3/§4 and `plan.md`/`quickstart.md` to match

**Checkpoint**: `pytest -q` green; live CLI spot-check confirms the printed total still adds up correctly.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately. Must leave the suite green before anything else begins.
- **Foundational (Phase 2)**: Depends on Phase 1. **BLOCKS all user stories** — `order_summary` and `price_for_item` are prerequisites for every story.
- **US1 (Phase 3)**: Depends on Phase 2. No dependency on US2 or US3.
- **US2 (Phase 4)**: Depends on Phase 2. **Also depends on US1** — `ticket_gen_node` copies the `order_summary` that `cart_summary_node` (T015) writes, so US2 cannot be validated end-to-end before US1 exists. This is an unavoidable data dependency, not a structuring choice.
- **US3 (Phase 5)**: Depends on Phase 2 and on US1's `build_order_summary`/`render_order_summary` (T013–T014), which it extends. Independent of US2.
- **Polish (Phase 6)**: Depends on all desired stories.

### Within Each User Story

- Tests are written and watched to FAIL before the implementation tasks that follow (Principle I)
- `build_order_summary` before `render_order_summary` before `cart_summary_node` before the CLI surface

### Parallel Opportunities

Genuinely limited — most tasks edit `nodes/cart_summary_node.py` or `tests/unit/test_cart_summary_and_ticket_nodes.py` and would collide.

- **Phase 2**: T005 (`state.py`), T006 (`cli.py`), T007 (test state dicts), and T008 (`test_menu_tools.py`) touch four different files and can run together
- **Phase 5**: US3 (Phase 5) can proceed in parallel with US2 (Phase 4) once US1 is done — they touch different source files (`cart_summary_node.py` vs `ticket_gen_node.py`), though both add cases to the same unit test file, so coordinate that file
- Everything else is sequential within its phase

---

## Parallel Example: Phase 2 (Foundational)

```bash
# Four different files, no shared edits — safe to run together:
Task: "Add order_summary field to src/customer_support_fde/state.py"
Task: "Add order_summary to the initial state dict in src/customer_support_fde/cli.py"
Task: "Add order_summary to hand-built state dicts in tests/integration/test_order_support_trajectory.py"
Task: "Write failing price_for_item tests in tests/unit/test_menu_tools.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1: Setup — the rename, suite stays green
2. Phase 2: Foundational — state field + price lookup (blocks everything)
3. Phase 3: User Story 1
4. **STOP and VALIDATE**: confirm an order end-to-end through the CLI and read the recap
5. Demo if ready — a customer can now see and verify their order

### Incremental Delivery

1. Setup + Foundational → baseline ready
2. US1 → customer sees a correct itemized summary → **MVP**
3. US2 → staff ticket provably matches the receipt
4. US3 → degraded cases fail loudly instead of silently
5. Polish → full suite, manual checks, PR with breaking-change callout

---

## Notes

- `[P]` = different files, no dependencies. Used sparingly here on purpose — see the Parallel Opportunities section.
- Every test case needs its `(base)`/`(edge)`/`(error)`/`(regression)` comment; T026 is the backstop check, not the first time to think about it.
- Verify tests fail before implementing — a test that passes before the code exists is testing nothing.
- The rounding invariant (T011) is asserted as a property, not against a hardcoded total, so it keeps holding when menu prices change.
- Commit after each task or logical group; stop at any checkpoint to validate a story independently.
