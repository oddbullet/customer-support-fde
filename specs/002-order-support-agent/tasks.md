---

description: "Task list template for feature implementation"
---

# Tasks: Order/Support Agent with Menu Tools

**Input**: Design documents from `/specs/002-order-support-agent/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/support-state.md, contracts/menu-tools.md, contracts/cart-tools.md, contracts/order-support-agent.md, contracts/confirm-and-ticket-nodes.md, quickstart.md

**Tests**: Included and REQUIRED — Constitution Principle I (Test-First, NON-NEGOTIABLE) mandates failing tests before implementation for this feature (see plan.md Constitution Check, including its scoped caveat on reply-wording).

**Revision note (2026-09-10)**: This task list was rewritten after a design review replaced the original classify-then-dispatch (`OrderIntentDecision`) approach with a native LLM tool-calling loop (`call_model` ⇄ `order_tools` as a `langgraph.prebuilt.ToolNode`, plus `await_customer`), verified against the installed `langgraph==1.2.11`. See `research.md`'s revision note and §2/§4/§5/§9 for the full rationale. Automated tests now target tool execution and resulting graph state, not model-composed reply text; reply-quality checks are manual (`quickstart.md`).

**Organization**: Tasks are grouped by user story (spec.md) to enable independent implementation and testing of each story. All three stories share the same `call_model ⇄ order_tools` loop: User Story 1 builds the loop itself (bound to `get_menu`/`get_menu_item` only) plus graph wiring to the already-Foundational `confirm_node`/`ticket_gen_node`; User Story 2 adds `add_items_to_cart` to the bound/executable tool list; User Story 3 adds `mark_order_confirmed`, which is what actually drives the hand-off `await_customer` was already built (in US1) to route on. Story independence is expressed as: each story adds its own failing tests plus the one additional tool that makes those tests pass, without altering what earlier stories already made pass.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Exact file paths are included in every task description

## Path Conventions

Single project (per plan.md Project Structure): `src/customer_support_fde/`, `tests/unit/`, `tests/integration/` at repository root.

---

## Phase 1: Setup (Package Reorganization)

**Purpose**: Reorganize the existing package into `nodes/`, `tools/`, and `menu/` subpackages (FR-010, FR-011, FR-012; research.md §1) with zero behavior change to the already-implemented `router_agent`, `clarify_intent`, and `refund_agent` (spec.md Assumptions)

- [X] T001 Create `src/customer_support_fde/nodes/__init__.py`, `src/customer_support_fde/tools/__init__.py`, and `src/customer_support_fde/menu/__init__.py` (empty packages)
- [X] T002 [P] Move `src/customer_support_fde/router_agent.py` to `src/customer_support_fde/nodes/router_agent.py` (same content, no behavior change) — depends on T001
- [X] T003 [P] Move `src/customer_support_fde/clarify_intent.py` to `src/customer_support_fde/nodes/clarify_intent.py` (same content, no behavior change) — depends on T001
- [X] T004 [P] Split `src/customer_support_fde/downstream_agents.py`: move `refund_agent` into `src/customer_support_fde/nodes/refund_agent.py` and move `order_support_agent` into `src/customer_support_fde/nodes/order_support_agent.py`, both unchanged (`return state`) for now — real order-support logic is built in User Story 1. Delete `src/customer_support_fde/downstream_agents.py` once both functions are moved — depends on T001
- [X] T005 Update `src/customer_support_fde/graph.py`'s imports to `customer_support_fde.nodes.router_agent`, `customer_support_fde.nodes.clarify_intent`, `customer_support_fde.nodes.refund_agent`, `customer_support_fde.nodes.order_support_agent` — no other change — depends on T002, T003, T004
- [X] T006 Update `src/customer_support_fde/cli.py`'s `from customer_support_fde.clarify_intent import QUESTION` to `from customer_support_fde.nodes.clarify_intent import QUESTION` — depends on T003
- [X] T007 [P] Update `tests/unit/test_router_agent.py`'s imports from `customer_support_fde.router_agent` to `customer_support_fde.nodes.router_agent` — depends on T002
- [X] T008 [P] Update `tests/unit/test_clarify_intent.py`'s imports from `customer_support_fde.clarify_intent` to `customer_support_fde.nodes.clarify_intent` — depends on T003
- [X] T009 [P] Update `tests/integration/test_router_trajectory.py`'s imports from `customer_support_fde.router_agent` to `customer_support_fde.nodes.router_agent` — depends on T002
- [X] T010 Run `pytest tests/unit/test_router_agent.py tests/unit/test_clarify_intent.py tests/integration/test_router_trajectory.py -v` and confirm every existing test still passes unchanged, verifying the reorganization introduced zero behavior change — depends on T005, T006, T007, T008, T009

**Checkpoint**: Package reorganized; all pre-existing behavior verified unchanged; ready for new development

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared state fields, menu data, the base LLM client, and the trivial/placeholder pieces every user story's graph depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T011 Extend `SupportState` in `src/customer_support_fde/state.py` per `contracts/support-state.md` / `data-model.md`: add `messages: list[AnyMessage]` ("scratch, per-turn... reset at the start of every customer turn... never accumulates across turns"), `menu_items: dict[str, int]` ("MUST only contain keys that are exact menu item names... never the customer's raw, unresolved input text"; "MUST be a positive integer, incrementing by exactly 1 per successful add"), `order_confirmed: bool` ("MUST be False on every turn except the one where mark_order_confirmed is called with a non-empty cart"), and `order_ticket: dict | None` ("MUST be None until ticket_gen_node runs"). `messages` uses `Annotated[..., add_messages]` (required for `ToolNode`'s partial-return accumulation within a turn); a test-only agentevals bug this surfaces (`IndexError` extracting a trajectory whose terminal snapshot has an empty `messages` list) is worked around in `tests/integration/_trajectory.py`, not in production code.
- [X] T012 [P] Create `src/customer_support_fde/menu/menu.json`: a JSON array of at least 5 items (FR-009), each an object with `name` (string, unique across the menu), `price` (positive number), and `ingredients` (non-empty list of strings) per `data-model.md`'s `MenuItem` schema
- [X] T013 [P] Create the base OpenRouter-backed `ChatOpenAI` client (`_build_llm()`, no tools bound yet — each user story binds its own growing tool list) in `src/customer_support_fde/nodes/order_support_agent.py`, mirroring `nodes/router_agent.py`'s existing `_build_llm()` pattern
- [X] T014 [P] Implement `confirm_node(state: SupportState) -> SupportState` in `src/customer_support_fde/nodes/confirm_node.py` per `contracts/confirm-and-ticket-nodes.md`: pure pass-through, returns `state` unchanged field-for-field
- [X] T015 [P] Implement `ticket_gen_node(state: SupportState) -> SupportState` in `src/customer_support_fde/nodes/ticket_gen_node.py` per `contracts/confirm-and-ticket-nodes.md`: returns `state` with `order_ticket` set to `{"items": dict(state["menu_items"])}`, every other field unchanged

**Checkpoint**: Foundation ready — the order-support tool-calling loop can now be built in User Story 1

---

## Phase 3: User Story 1 - Ask about the menu and specific items (Priority: P1) 🎯 MVP

**Goal**: A customer can ask what's on the menu and get full details (name, price, ingredients) for a specific dish — including a genuine recommendation if asked, since the model reasons over real tool results — with flexible name matching, a disambiguation question on a tie, and a clear "not found" response, never a fabricated answer.

**Independent Test**: Ask "What's on the menu?" and "What's in [dish name]?" (exact, partial/typo, tied, and unknown names) in a conversation and confirm the agent's tool calls resolve correctly (asserted on tool execution and state, per `research.md` §9) and the conversation pauses for the next message.

### Tests for User Story 1 ⚠️

> **Write these tests FIRST, ensure they FAIL before implementation**

- [X] T016 [P] [US1] Write failing unit tests in `tests/unit/test_menu_tools.py` against a small in-memory sample menu (include two deliberately similar names to construct a tie case): `resolve_menu_item` returns `found` for an exact and a case-insensitive name match, `found` for a partial/substring name and a minor-typo variation of exactly one item (FR-001), `not_found` when no candidate meets the match cutoff (FR-005), and `tie` with all tied candidates' names when two or more items score equally at the top (FR-005a)
- [X] T017 [P] [US1] Write failing unit tests in `tests/unit/test_order_support_agent.py`: with the LLM boundary faked (`monkeypatch` the `.bind_tools(...)`-returned object's `.invoke()`) to first return an `AIMessage` with a `get_menu` tool call, then — after `order_tools` executes it — a final `AIMessage` with no tool calls, run `call_model`/`order_tools` directly (not through the full graph/interrupt machinery) and assert the `get_menu` `ToolMessage`'s content lists every seeded (sample) menu item; repeat with a `get_menu_item` tool call for `found`/`tie`/`not_found` names and assert the `ToolMessage` content matches `contracts/menu-tools.md`'s guarantees for each case. Note: standalone `ToolNode.invoke(state, config)` requires a minimal `langgraph.runtime.Runtime` injected via `config` (installed `langgraph` version) — see `_TOOL_NODE_CONFIG` in the test file.
- [X] T018 [P] [US1] Write a failing integration test in `tests/integration/test_order_support_trajectory.py`: invoke `build_graph()` (router LLM boundary faked to `"order_support"`, order-support LLM boundary faked to return a `get_menu` tool call then a final no-tool-call `AIMessage`) with a menu question, and assert `"__interrupt__" in result` after the trajectory passes through `call_model` → `order_tools` → `call_model` → `await_customer` (mirrors the ambiguous-router-path resume pattern already used in `test_router_trajectory.py`)
- [X] T019 [US1] Update the existing `test_order_support_style_request_routes_through_order_support_agent` test in `tests/integration/test_router_trajectory.py` to reflect that the order-support flow now pauses via `interrupt()` instead of completing straight through to `END`: assert `"__interrupt__" in result` after the `router_agent -> call_model` hop (the new order-support entry node) rather than asserting a trajectory that ends cleanly at the old single `order_support_agent` node. Also updated the ambiguous-clarify and labeled-sample-set tests in the same file (previously asserting a terminal `order_support_agent` node), since routing `order_support` destinations into the real `call_model` loop means every order-support-bound scenario in this file now needs the order-support LLM boundary faked too and now legitimately pauses at `__interrupt__` instead of completing to `END` — not a regression, an intentional consequence of this feature routing real traffic through `call_model`.

### Implementation for User Story 1

- [X] T020 [US1] Implement `resolve_menu_item(name, menu) -> MenuMatch` (pure), and the LLM-callable tools `get_menu() -> str` and `get_menu_item(name: str) -> str` (thin wrappers rendering `resolve_menu_item`'s result / the full menu as tool output), in `src/customer_support_fde/tools/menu_tools.py` per `contracts/menu-tools.md` and research.md §3 (stdlib `difflib.SequenceMatcher` scoring with a 0.6 cutoff, a substring-match boost, and tie detection among candidates within a small epsilon of the top score) — makes T016 pass
- [X] T021 [US1] Implement `call_model(state) -> SupportState` and `await_customer(state) -> SupportState` in `src/customer_support_fde/nodes/order_support_agent.py` (depends on T013, T020, makes T017 pass): `call_model` resets `state["messages"]` at the start of a new turn (system prompt + brief cart summary if non-empty + current customer message) and otherwise appends nothing extra; binds `[get_menu, get_menu_item]` (later stories extend this list) via `.bind_tools(...)` and appends the resulting `AIMessage`. `await_customer` reads `state["order_confirmed"]` (always `False` in this story, since `mark_order_confirmed` doesn't exist yet): calls `interrupt()` with the last `AIMessage`'s content and, on resume, resets `state["messages"] = []` and sets `state["user_query"]` to the resumed value. Note: `messages` uses `Annotated[..., add_messages]`, so the actual reset returns `[RemoveMessage(id=REMOVE_ALL_MESSAGES)]` (a bare `[]` is a no-op under that reducer).
- [X] T022 [US1] Wire the order-support loop in `src/customer_support_fde/graph.py` (depends on T014, T015, T021, makes T018–T019 pass): register `call_model`, `order_tools = ToolNode([get_menu, get_menu_item])`, `await_customer`, `confirm_node`, `ticket_gen_node`; `add_conditional_edges("call_model", tools_condition, {"tools": "order_tools", "__end__": "await_customer"})`; `add_edge("order_tools", "call_model")`; `add_conditional_edges("await_customer", <fn reading state["order_confirmed"]>, {"continue": "call_model", "confirmed": "confirm_node"})`; `add_edge("confirm_node", "ticket_gen_node")`; `add_edge("ticket_gen_node", END)`; update `router_agent`'s and `clarify_intent`'s conditional-edge targets from `"order_support_agent"` to `"call_model"`; remove the old unconditional `order_support_agent -> END` edge

**Checkpoint**: User Story 1 fully functional and independently testable — menu and item-detail questions (including recommendations, tie, and not-found handling) work end-to-end across a paused multi-turn conversation

---

## Phase 4: User Story 2 - Add menu items to a cart (Priority: P2)

**Goal**: A customer can tell the agent to add one or more specific dishes to their cart in a single message, with quantities tracked per distinct item and unavailable items declined.

**Independent Test**: Ask the agent to add a known menu item, add a second distinct item (optionally in the same message as a batch), and add the first item again; confirm the cart reflects both items with correct quantities (2 and 1) and that adding an unavailable item is declined without mutating the cart.

### Tests for User Story 2 ⚠️

> **Write these tests FIRST, ensure they FAIL before implementation**

- [X] T023 [P] [US2] Write failing unit tests in `tests/unit/test_cart_tools.py`, calling `add_items_to_cart(names=[...], state={"menu_items": {...}})` directly (no LLM, no graph) per `contracts/cart-tools.md`: a `found` name added to an empty cart produces a `Command` whose `update["menu_items"]` has that entry at quantity 1; adding the same resolved name twice — within one `names` list, and across two separate calls — results in quantity 2, never a duplicate entry (FR-004); a `tie` or `not_found` name leaves `menu_items` unchanged in the `Command.update` (FR-005, FR-005a) while still being reported in the returned `ToolMessage` content; a batch of 2+ names with mixed found/tie/not_found results applies only the found ones; the function never mutates its input `state["menu_items"]` in place
- [X] T024 [P] [US2] Write failing unit tests in `tests/unit/test_order_support_agent.py`: with the LLM boundary faked to return an `AIMessage` with an `add_items_to_cart` tool call (single item, then separately a multi-item batch), run `call_model`/`order_tools` and assert the resulting `state["menu_items"]` reflects the add(s) correctly; assert a `not_found` or `tie` name in the batch does not appear in `menu_items`
- [X] T025 [US2] Write a failing integration test in `tests/integration/test_order_support_trajectory.py`: a multi-turn conversation (LLM boundaries faked per turn) that adds one item, then a second distinct item, then the first item again — resumed via `Command(resume=...)` each turn — asserting the final `menu_items` (read via `graph.get_state(config).values`) has two entries with quantities 2 and 1 respectively (User Story 2 Acceptance Scenarios 3 and 4)

### Implementation for User Story 2

- [X] T026 [US2] Implement `add_items_to_cart(names: list[str], state: Annotated[SupportState, InjectedState]) -> Command` in `src/customer_support_fde/tools/cart_tools.py` per `contracts/cart-tools.md` (depends on T020, makes T023 pass): resolves each name sequentially within this one call against a single derived copy of `state["menu_items"]`, returns one `Command` with the updated cart and a summary `ToolMessage`. Also takes `tool_call_id: Annotated[str, InjectedToolCallId]` (from `langchain_core.tools`) so the returned `ToolMessage.tool_call_id` correctly threads back to the originating tool call — needed in practice though not spelled out in the contract's signature.
- [X] T027 [US2] Extend `call_model`'s bound tools and `order_tools`'s tool list in `src/customer_support_fde/nodes/order_support_agent.py` and `src/customer_support_fde/graph.py` to include `add_items_to_cart` (depends on T021, T022, T026, makes T024–T025 pass). Note: `ToolNode.invoke(...)` returns a `list[Command]` (not a merged dict) whenever any invoked tool returns a `Command` — real graph execution (`langgraph.pregel`) applies each `Command.update` natively, but a test calling `order_tools` directly must merge this itself (see `_merge_tool_result` in `tests/unit/test_order_support_agent.py`).

**Checkpoint**: User Stories 1 AND 2 both work independently — the cart accumulates distinct items (including from multi-item messages) with correct quantities on top of working menu/item-detail Q&A

---

## Phase 5: User Story 3 - Produce an order ticket from the conversation (Priority: P3)

**Goal**: Once a customer has finished building their cart and explicitly confirms they're done, the flow hands off through `confirm_node` to `ticket_gen_node`, which produces a placeholder order ticket referencing exactly the items that were added.

**Independent Test**: Complete an ordering conversation that adds at least one item, then confirm that saying "done" without ever adding anything is acknowledged without generating a ticket, and that confirming with a non-empty cart produces a ticket artifact reflecting the ordered items.

### Tests for User Story 3 ⚠️

> **Write these tests FIRST, ensure they FAIL before implementation**

- [X] T028 [P] [US3] Write failing unit tests in `tests/unit/test_cart_tools.py`, calling `mark_order_confirmed(state={"menu_items": {...}})` directly (no LLM, no graph) per `contracts/cart-tools.md`: a non-empty `menu_items` produces a `Command` with `update["order_confirmed"] == True`; an empty `menu_items` produces a `Command` whose `update` omits `order_confirmed` entirely (so it stays `False`) and whose `ToolMessage` content acknowledges there's nothing to confirm (FR-006, FR-007, Edge Cases)
- [X] T029 [P] [US3] Write failing unit tests in a new file `tests/unit/test_confirm_and_ticket_nodes.py` per `contracts/confirm-and-ticket-nodes.md`: `confirm_node` returns its input state unchanged, field-for-field; `ticket_gen_node` sets `order_ticket == {"items": dict(menu_items)}` and leaves every other field unchanged
- [X] T030 [US3] Write a failing integration test in `tests/integration/test_order_support_trajectory.py`: a full conversation — add one item, add a second item, then confirm done — resumed turn by turn via `Command(resume=...)`, asserting the trajectory (via `agentevals.graph_trajectory.strict.graph_trajectory_strict_match`) expressed as **nested per-resume segments split at each `__interrupt__`** — matching the multi-`interrupt()` pattern already established in `tests/integration/test_router_trajectory.py`'s `test_ambiguous_or_mixed_signal_request_resolved_via_clarify_intent`, e.g. `{"steps": [["__start__", "router_agent", "call_model", "order_tools", "call_model", "__interrupt__"], ["call_model", "order_tools", "call_model", "__interrupt__"], ["call_model", "order_tools", "call_model", "confirm_node", "ticket_gen_node"]]}` (exact per-segment node counts depend on how many tool-calling rounds the faked model takes each turn — assert against whatever the fakes are configured to produce, not a hardcoded generic shape) — and that the final state's `order_ticket["items"]` matches the accumulated cart exactly (SC-003, SC-004). Also cover "customer says done without adding anything": assert the conversation stays in the `call_model`/`order_tools`/`await_customer` loop and never reaches `confirm_node`/`ticket_gen_node` (User Story 3 Acceptance Scenario 3, Edge Cases)

### Implementation for User Story 3

- [X] T031 [US3] Implement `mark_order_confirmed(state: Annotated[SupportState, InjectedState]) -> Command` in `src/customer_support_fde/tools/cart_tools.py` per `contracts/cart-tools.md` (depends on T026, makes T028 pass)
- [X] T032 [US3] Extend `call_model`'s bound tools and `order_tools`'s tool list to include `mark_order_confirmed` (depends on T027, T031, makes T030 pass); no change needed to `await_customer`'s routing logic itself (already built in T021 to read `state["order_confirmed"]`) — this task is what first gives that field a way to actually become `True`

**Checkpoint**: All three user stories independently functional — the full ordering conversation, from menu browsing/recommendations through multi-item cart building to a produced placeholder order ticket, works end-to-end

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation against quickstart.md and the constitution, the CLI fix this feature's design surfaced, and closing a coverage gap identified during `/speckit-analyze`

- [X] T033 [P] Write a unit test in `tests/unit/test_menu_tools.py` (or a new `tests/unit/test_menu_data.py`) that loads the **real** `src/customer_support_fde/menu/menu.json` (not the in-memory sample menu used elsewhere) via `get_menu()`/the menu-loading helper, and asserts `len(...) >= 5` and that every item has a non-empty `name`, a positive `price`, and a non-empty `ingredients` list (FR-009) — closes a coverage gap where FR-009 was otherwise only manually verified at T012
- [X] T034 [P] Fix `src/customer_support_fde/cli.py`'s resume loop (research.md §8): print the actual `interrupt()` payload (the first `Interrupt` object's `.value` from `result["__interrupt__"]`) instead of the hardcoded `QUESTION` constant, so the order-support loop's dynamic per-turn prompts display correctly; verify `clarify_intent`'s question still displays correctly too (regression)
- [X] T035 [P] Run `pytest tests/unit/test_menu_tools.py tests/unit/test_cart_tools.py tests/unit/test_order_support_agent.py tests/unit/test_confirm_and_ticket_nodes.py tests/integration/test_order_support_trajectory.py tests/unit/test_router_agent.py tests/unit/test_clarify_intent.py tests/integration/test_router_trajectory.py -v` per `quickstart.md` and confirm all tests, new and existing, pass
- [X] T036 Manually validate `quickstart.md`'s CLI walkthrough and its "Manual reply-quality checks" section against a live model (requires `OPENROUTER_API_KEY`): menu question, a recommendation question, a multi-item add in one message, a deliberately ambiguous partial name (tie), and a full add→confirm flow — confirm each reads correctly end-to-end, since reply wording is not covered by automated tests in this design. Found and fixed a real bug during this validation: `cli.py` crashed (`UnicodeEncodeError`) printing a model reply containing an em dash, because Windows' default console codec can't encode it — fixed via `sys.stdout/stderr.reconfigure(encoding="utf-8", errors="replace")` at the top of `run()`. After the fix, live-validated: full menu listing (SC-002), a genuine reasoned spicy-food recommendation (not a raw dump), a single message adding 2 Spring Rolls + 1 Kung Pao Chicken via one batched `add_items_to_cart` call, a full add→confirm→ticket flow (conversation cleanly reached `END` after "That's all, thanks"), a partial name ("kung pao" → found Kung Pao Chicken with an offer to add it), and a not-on-menu name ("pizza" → not_found, correctly declined without fabricating, then the model helpfully listed real alternatives). Note: the seeded `menu.json` has no near-duplicate item names, so a live LLM-triggered `tie` disambiguation isn't reachable through natural queries against this menu — the `tie` code path itself is already exhaustively covered deterministically by `test_menu_tools.py`/`test_cart_tools.py`, which don't depend on the live model.
- [X] T037 Confirm `src/customer_support_fde/nodes/order_support_agent.py`'s LLM calls respect the standard LangSmith tracing environment variables (`LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`, `LANGSMITH_PROJECT`) per Constitution Principle IV, with no custom logging layer added. `_build_llm()` mirrors `router_agent._build_llm()`'s plain `ChatOpenAI(...)` construction exactly (no wrapper, no custom logging) — LangChain's standard tracing callbacks pick up those env vars automatically, same as 001.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately. Verifies zero regression before any new behavior is added.
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational completion. Builds `resolve_menu_item`/`get_menu`/`get_menu_item`, the `call_model`/`await_customer` loop nodes, and the full graph wiring (including `confirm_node`/`ticket_gen_node` hookup) that every later story builds on top of
- **User Story 2 (Phase 4)**: Depends on User Story 1's `call_model`/`order_tools` (T021, T022) and `resolve_menu_item` (T020); adds `add_items_to_cart` to the bound tool list
- **User Story 3 (Phase 5)**: Depends on User Story 2's cart tool (T026, for `mark_order_confirmed` to share resolution logic and for the cart to be non-empty when testing confirmation); adds `mark_order_confirmed`, which is what first drives `await_customer`'s already-built routing to `confirm_node`
- **Polish (Phase 6)**: Depends on all three user stories being complete

### Within Each User Story

- Tests MUST be written and FAIL before implementation tasks in that story
- Tools before the node logic that calls them
- Node/loop logic before graph wiring (User Story 1 only — wiring is a one-time task)
- Story's checkpoint reached before moving to the next priority

### Parallel Opportunities

- T002, T003, and T004 can run in parallel (different files/moves), after T001
- T007, T008, and T009 can run in parallel (different test files)
- T012 and T013 can run in parallel with each other and with T011 (different files)
- T014 and T015 can run in parallel with each other and with T011–T013 (different files)
- T016, T017, and T018 can run in parallel (three different files/test-functions)
- T023 and T024 can run in parallel (different files)
- T028 and T029 can run in parallel (different files)
- T033, T034, and T035 can run in parallel (independent validation/fix activities)

---

## Parallel Example: User Story 1

```bash
# Launch all three User Story 1 test tasks together (three different files/functions):
Task: "Write failing unit tests in tests/unit/test_menu_tools.py for resolve_menu_item found/tie/not-found"
Task: "Write failing unit tests in tests/unit/test_order_support_agent.py for get_menu/get_menu_item tool execution"
Task: "Write failing integration test in tests/integration/test_order_support_trajectory.py for the menu-question trajectory"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (reorganization, zero regression)
2. Complete Phase 2: Foundational (CRITICAL — state fields, menu data, base LLM client, `confirm_node`/`ticket_gen_node` placeholders)
3. Complete Phase 3: User Story 1 (menu/item-detail Q&A and recommendations, including tie/not-found handling)
4. **STOP and VALIDATE**: `pytest tests/unit/test_menu_tools.py tests/unit/test_order_support_agent.py tests/integration/test_order_support_trajectory.py -v` — menu Q&A path green
5. Demo via CLI once Phase 6's T034 CLI fix is in place, or via direct `build_graph()` invocation before that

### Incremental Delivery

1. Setup + Foundational → reorganized package, shared state/data ready, zero regression
2. Add User Story 1 → menu/item-detail questions and recommendations work and are tested (MVP!)
3. Add User Story 2 → cart building (including multi-item messages, with quantities) works and is tested
4. Add User Story 3 → the confirm-and-ticket hand-off works end-to-end and is tested
5. Polish → FR-009 real-menu-data test added, CLI fix applied, full `quickstart.md` validation checklist satisfied

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Because all three stories share one `call_model ⇄ order_tools` loop, later stories' "implementation" tasks are narrower (extend the bound tool list by one) than a fully independent story would have — this reflects the design decision in `research.md` §2/§4, not a shortcut
- `confirm_node` and `ticket_gen_node` are built once in Foundational (Phase 2) as trivial, fully-specified placeholders (FR-008) — no story owns their implementation, but User Story 3 is the first to meaningfully exercise them via tests
- Reply *wording* (e.g. FR-006's "anything else?" question) is not asserted by any automated test in this design, since replies are model-composed rather than template-generated — see `research.md` §9 and `plan.md`'s Constitution Check Principle I caveat. This is a deliberate, called-out scope decision, not an oversight; `quickstart.md`'s "Manual reply-quality checks" section is the compensating control for this phase
- Verify tests fail before implementing
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently

---

## Phase 7: Convergence

**Purpose**: Close test-coverage gaps found by `/speckit-converge` against explicit contract guarantees that the implementation already satisfies structurally but that no automated test currently protects

- [X] T038 Add a failing-then-passing unit test in `tests/unit/test_order_support_agent.py` asserting `call_model`'s LLM-call failure (e.g. a `RuntimeError` raised from the bound LLM's `.invoke()`) propagates rather than being swallowed or returning a partial/corrupted `SupportState` — mirror `tests/unit/test_router_agent.py::test_llm_call_failure_propagates_rather_than_returning_partial_state`'s pattern per `contracts/order-support-agent.md` Guarantee 5 / `contracts/support-state.md` Guarantee 5 (partial). The guarantee already held (no code change needed) — `test_call_model_llm_failure_propagates_rather_than_returning_partial_state` passed immediately, now guarding it against regression.
- [X] T039 Add a failing-then-passing integration test in `tests/integration/test_order_support_trajectory.py` asserting `SupportState.messages` is actually reset/bounded across turns when run through the real compiled graph — e.g. assert `len(graph.get_state(config).values["messages"])` after a later resumed turn is not larger than after an earlier turn (rather than growing with every turn), proving the `RemoveMessage(id=REMOVE_ALL_MESSAGES)` reset in `await_customer` actually clears checkpointed state via the `add_messages` reducer in real graph execution, not just in a direct unit-level call — per `contracts/order-support-agent.md` Guarantee 1 / `contracts/support-state.md` Guarantee 1 / `research.md` §4 (partial). The guarantee already held — `test_messages_do_not_accumulate_across_turns` passed immediately; manually verified the actual per-turn counts (5 → 6 → 6 across three turns, not 5 → 11 → 17) to confirm the assertion is meaningful and would catch a regression, not vacuously true.
