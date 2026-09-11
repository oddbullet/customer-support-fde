---

description: "Task list template for feature implementation"
---

# Tasks: Remove Items From Cart

**Input**: Design documents from `/specs/003-remove-cart-items/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cart-tools.md, quickstart.md

**Tests**: Included and REQUIRED — Constitution Principle I (Test-First, NON-NEGOTIABLE) mandates failing tests before implementation for this feature (see plan.md Constitution Check).

**Organization**: The spec defines a single user story (P1 — "Remove an item the customer changed their mind about"), so every task belongs to it. There is no Setup phase (no new project scaffolding, dependencies, or directories) and no Foundational phase (the feature reuses `resolve_menu_item`, `InjectedState`, `Command`, and the existing `_ORDER_TOOLS`/`ToolNode` wiring exactly as `add_items_to_cart` already does — nothing new needs to exist before User Story 1's own tasks can start).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1)
- Exact file paths are included in every task description

## Path Conventions

Single project (per plan.md Project Structure): `src/customer_support_fde/`, `tests/unit/`, `tests/integration/` at repository root.

---

## Phase 1: Setup

Not applicable — no new dependencies, directories, or project scaffolding are introduced by this feature (plan.md Technical Context: "No new third-party dependency... no new modules, no new graph nodes").

---

## Phase 2: Foundational

Not applicable — this feature has no blocking prerequisite that doesn't already exist. `resolve_menu_item` (`tools/menu_tools.py`), `InjectedState`/`Command`/`InjectedToolCallId`, and the `_ORDER_TOOLS`/`ToolNode` wiring in `nodes/order_support_agent.py` are all already in place from `002-order-support-agent` and are reused as-is (research.md §1, §2).

---

## Phase 3: User Story 1 - Remove an item the customer changed their mind about (Priority: P1) 🎯 MVP

**Goal**: A customer can ask the order/support agent to remove a previously-added item from their cart — naming it alone removes the entire entry regardless of quantity, naming it with a count decrements by that amount (capped at what's actually in the cart) — with the same fuzzy-match, tie, and not-found handling already used elsewhere, and a clear message when the item isn't in the cart at all.

**Independent Test**: Add a known menu item (twice, so its quantity is 2) to the cart, ask to remove it without a quantity and confirm the entry is deleted entirely; separately, add an item, ask to remove a smaller specific quantity, and confirm the entry remains with the reduced count; ask to remove an item never added and confirm a clear "not in your cart" outcome instead of a silent no-op.

### Tests for User Story 1 ⚠️

> **Write these tests FIRST, ensure they FAIL before implementation**

- [X] T001 [P] [US1] Write failing unit tests in `tests/unit/test_cart_tools.py` calling `remove_items_from_cart.func(items=[...], state={"menu_items": {...}}, tool_call_id="call_1")` directly (no LLM, no graph), following the file's existing `SAMPLE_MENU`/`setup_function` pattern used by `add_items_to_cart`'s tests, per `contracts/cart-tools.md`, covering: an unqualified removal deleting a quantity-1 entry and, separately, a quantity-3 entry entirely, "regardless of how many units were present" (FR-002); a stated `quantity` smaller than the current cart quantity decrementing the entry and keeping it (FR-003); a stated `quantity` that meets or exceeds the current cart quantity deleting the entry entirely and reporting the actual capped amount removed, not the requested amount (FR-007); a `found`-but-not-a-cart-key name reported as "isn't in your cart" (FR-005), distinct from a `not_found` menu-match; a `tie` name and a `not_found` name each leaving the cart unchanged and reported in the `ToolMessage` content (FR-006, FR-006a); a batch of 2+ items with mixed found-and-in-cart / not-in-cart / not-found / tie results applying only the found-and-in-cart ones independently per item (FR-008); and that the function never mutates its input `state["menu_items"]` dict in place (mirroring `test_never_mutates_input_menu_items_in_place`)
- [X] T002 [P] [US1] Write a failing unit test in `tests/unit/test_order_support_agent.py`, following the file's existing `_run_inner_loop`/`_patch_llm` pattern used for `add_items_to_cart`'s tool-call tests: with the LLM boundary faked to return an `AIMessage` with a `remove_items_from_cart` tool call (start the state's `menu_items` pre-populated, e.g. `{"Kung Pao Chicken": 2}`) followed by a final no-tool-call `AIMessage`, run the inner `call_model ⇄ order_tools` loop and assert the resulting `state["menu_items"]` reflects the removal correctly for both an unqualified removal (entry deleted) and a quantified removal (entry decremented, kept)
- [X] T003 [US1] Write a failing integration test in `tests/integration/test_order_support_trajectory.py`, following the file's existing multi-turn `Command(resume=...)` pattern (e.g. `test_repeated_adds_across_turns_accumulate_quantities`): a conversation that adds two distinct items across separate turns, then removes one of them entirely (no quantity) in a later turn, then confirms — asserting the final `menu_items` (via `graph.get_state(config).values`) reflects the removal and the eventual `order_ticket["items"]` matches what remains after the removal

### Implementation for User Story 1

- [X] T004 [US1] In `src/customer_support_fde/tools/cart_tools.py`, add a `CartRemoval(BaseModel)` with fields `name: str` and `quantity: int | None = None` (import `BaseModel` from `pydantic`, matching `nodes/router_agent.py`'s existing usage), plus a `_render_remove_result(name, match, cart, quantity) -> str` helper and the tool `remove_items_from_cart(items: list[CartRemoval], state: Annotated[SupportState, InjectedState], tool_call_id: Annotated[str, InjectedToolCallId]) -> Command`, all per `contracts/cart-tools.md` and `data-model.md`'s `CartRemoval` validation rules quoted here verbatim — `name` "MUST be resolved through `resolve_menu_item` before being used as a `menu_items` key — never the raw customer-supplied text"; `quantity`, when given, "is expected to be a positive integer; the tool's behavior is defined only for `None` or a positive `quantity`". The tool operates on a derived copy of `state["menu_items"]` (never mutating the input), resolves each `items[i].name` via `resolve_menu_item`, and for each `found` name present in the cart either deletes the entry (`quantity is None` or `quantity >= current`) or decrements it by `quantity` (otherwise) — depends on nothing new (reuses `resolve_menu_item`, `InjectedState`, `Command`, `InjectedToolCallId` already imported by `add_items_to_cart`) — makes T001 pass
- [X] T005 [US1] In `src/customer_support_fde/nodes/order_support_agent.py`, add `remove_items_from_cart` to the `tools/cart_tools` import and to the `_ORDER_TOOLS` list (alongside `get_menu`, `get_menu_item`, `add_items_to_cart`, `mark_order_confirmed`), and extend `SYSTEM_PROMPT` with a short sentence telling the model it can remove items from the cart the customer no longer wants — depends on T004, makes T002–T003 pass

**Checkpoint**: User Story 1 fully functional and independently testable — a customer can remove an entire cart entry or a partial quantity of one, with all pre-existing menu/cart behavior (Q&A, adds, confirmation) unaffected

---

## Phase 4: Polish & Cross-Cutting Concerns

**Purpose**: Final validation against `quickstart.md` and the constitution

- [X] T006 [P] Run `pytest tests/unit/test_cart_tools.py tests/unit/test_order_support_agent.py tests/integration/test_order_support_trajectory.py -v` per `quickstart.md` and confirm all tests, new and existing (including every pre-existing `add_items_to_cart`/`mark_order_confirmed`/menu-Q&A test), pass
- [X] T007 Manually validate `quickstart.md`'s CLI walkthrough and "Manual reply-quality checks" section against a live model (requires `OPENROUTER_API_KEY`): an unqualified removal of a multi-quantity item, a quantified partial removal, an over-quantity removal request, a removal of an item not in the cart, and a tied/unmatched removal name — confirm each reads correctly end-to-end, since reply wording is not covered by automated tests in this design (consistent with `specs/002-order-support-agent/research.md` §9's scope decision, which this feature follows)
- [X] T008 Confirm no new LLM call site was introduced (`call_model`'s single `.bind_tools([...])` call site simply gained one more bound tool) so existing LangSmith tracing coverage (Constitution Principle IV) extends to `remove_items_from_cart` automatically, with no custom logging layer added

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup / Foundational**: Not applicable (see Phase 1/2 above) — User Story 1 can start immediately.
- **User Story 1 (Phase 3)**: No dependency on any other phase in this feature; depends only on already-implemented `002-order-support-agent` code (`resolve_menu_item`, `_ORDER_TOOLS`, `ToolNode` wiring), which is unchanged by this feature.
- **Polish (Phase 4)**: Depends on User Story 1 being complete.

### Within User Story 1

- Tests (T001–T003) MUST be written and FAIL before implementation tasks (T004–T005)
- T004 (the tool itself) before T005 (registering it into the bound/executable tool list)
- T002 and T003 depend on T005 having registered the tool (they exercise it through the agent loop / full graph, not by calling the tool function directly)

### Parallel Opportunities

- T001 and T002 can run in parallel (different files) — T003 touches a file shared with pre-existing tests in the same module, so sequence it after confirming T001/T002's target files are stable, but it does not conflict with either at the code level
- T006, T007, and T008 can run in parallel (independent validation activities)

---

## Parallel Example: User Story 1

```bash
# Launch the two directly-parallel User Story 1 test tasks together:
Task: "Write failing unit tests in tests/unit/test_cart_tools.py for remove_items_from_cart"
Task: "Write failing unit test in tests/unit/test_order_support_agent.py for the remove_items_from_cart inner-loop tool call"
```

---

## Implementation Strategy

### MVP First (and only) — User Story 1

1. Write T001–T003 (failing tests)
2. Implement T004 (the tool) then T005 (register it) to make them pass
3. **STOP and VALIDATE**: `pytest tests/unit/test_cart_tools.py tests/unit/test_order_support_agent.py tests/integration/test_order_support_trajectory.py -v`
4. Run Phase 4 Polish (T006–T008) and demo via CLI

### Incremental Delivery

Since this feature has exactly one user story, there is no phased/incremental rollout beyond: tests → implementation → polish, as above.

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps every task to US1 — there is only one user story in this feature
- `remove_items_from_cart` deliberately does not check `order_confirmed` before mutating the cart, matching `add_items_to_cart`'s existing behavior — cart mutation after confirmation is out of scope for this feature (spec Assumptions)
- Reply *wording* around removal outcomes is not asserted by any automated test, consistent with the reply-composition scope decision already made and documented in `specs/002-order-support-agent/research.md` §9 — `quickstart.md`'s "Manual reply-quality checks" is the compensating control
- Verify tests fail before implementing
- Commit after each task or logical group
