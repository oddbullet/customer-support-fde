---

description: "Task list for the Tool Call Limit feature"
---

# Tasks: Tool Call Limit

**Input**: Design documents from `specs/017-tool-call-limit/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/tool-limit.md, contracts/print-warning.md, quickstart.md

**Tests**: REQUIRED. Constitution Principle I (Test-First) and the project workflow require strict TDD, done in separate passes:
1. Write or modify the tests.
2. Run them and confirm they fail (red).
3. Implement.
4. Run them and confirm they pass (green).

Every new test gets a one-line comment directly above it (above the outermost `@pytest.mark.parametrize` if there is one). The comment says what the test checks and ends with a category tag: `(base)`, `(edge)`, `(error)`, or `(regression)`.

**Organization**: Tasks are grouped by user story (spec.md US1–US4).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: The user story the task belongs to (US1–US4)

## Path Conventions

This is a single project. Source is in `src/customer_support_fde/` and tests are in `tests/unit/` and `tests/integration/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm a green baseline before any change.

- [ ] T001 Run `uv run pytest` from the repo root and record that the current suite passes. This is the baseline for SC-003. Stop and report if anything already fails.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Add the state field and the generic red warning display. US1's CLI path needs both.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### Tests first (red)

- [ ] T002 [P] In `tests/unit/test_state.py` (new file), add a test that `initial_state("hi")["tool_limit_reached"] is None` `(base)`. Mock `db.load_menu` with `monkeypatch.setattr(state.db, "load_menu", lambda: [])` so it doesn't touch a database.
- [ ] T003 [P] In `tests/unit/test_interactive.py`, add a test that `interactive.print_warning("System issue", console)` prints the text in red `(base)`.
  - Build the console as `Console(file=io.StringIO(), force_terminal=True, color_system="standard")`.
  - Assert the output contains `"System issue"` and the red SGR code `"\x1b[31m"`.
- [ ] T004 Run `uv run pytest tests/unit/test_state.py tests/unit/test_interactive.py` and confirm T002 and T003 FAIL: missing key or `AttributeError: print_warning`. Don't implement until you've seen them fail.

### Implementation (green)

- [ ] T005 [P] In `src/customer_support_fde/state.py`, add `tool_limit_reached: dict | None` to `SupportState`, and `"tool_limit_reached": None` to `initial_state()`. Per data-model.md, the field is "`None` while the conversation is within the limit. Otherwise `{"agent": "order_support" | "refund", "tool": str}`."
- [ ] T006 [P] In `src/customer_support_fde/interactive.py`, add `print_warning(message: str, console: Console | None = None) -> None`, next to `_print_turn`.
  - It prints `Text(message, style="red")`, which uses the existing `rich.text.Text` import and treats the message as literal text, not markup.
  - It falls back to `_make_console()` when `console` is `None`.
  - Follow contracts/print-warning.md.
- [ ] T007 Run `uv run pytest tests/unit/test_state.py tests/unit/test_interactive.py` and confirm they pass.

**Checkpoint**: The state field exists and `print_warning` prints red.

---

## Phase 3: User Story 1 - Stop a runaway tool loop and warn the customer (Priority: P1) 🎯 MVP

**Goal**: The 4th consecutive same-tool step in a customer turn doesn't run. The graph ends with `tool_limit_reached` set, and the CLI shows the red warning and waits for Enter before clearing the screen.

**Independent Test**: A scripted order or refund LLM that requests the same tool on every step runs that tool exactly 3 times. The graph then ends with `tool_limit_reached` set, and no ticket is written. When the interactive loop gets that result, it shows `TOOL_LIMIT_WARNING` in red and waits for Enter before `console.clear()`.

### Tests for User Story 1 (write first, confirm red)

- [ ] T008 [P] [US1] Create `tests/unit/test_tool_limit.py` with tests for `find_repeated_tool` from `customer_support_fde.nodes.tool_limit`.
  - Build steps as `AIMessage(content="", tool_calls=[{"name": ..., "args": {}, "id": ...}])`, each followed by a matching `ToolMessage(content="ok", tool_call_id=...)`.
  - Start each history with a `HumanMessage`.
  - Cover these trip rows from contracts/tool-limit.md:
    - `get_menu` ×4 → `"get_menu"` `(base)`
    - `get_menu` ×3, then `[get_menu, get_cart]` in one step → `"get_menu"` `(edge)`
    - Several tools over the limit in the newest step → the first one in `tool_calls` order `(edge)`
  - Add a test that `MAX_CONSECUTIVE_TOOL_CALLS == 3` `(base)`.
- [ ] T009 [P] [US1] In `tests/unit/test_tool_limit.py`, add tests for `route_after_agent`:
  - Returns `"tool_limit"` when `find_repeated_tool` would return a name `(base)`.
  - Returns `"tools"` for a first tool call `(base)`.
  - Returns `"__end__"` when the newest `AIMessage` has no tool calls `(base)`.
  - Add tests for `tool_limit_node`: it returns `{"tool_limit_reached": {"agent": "order_support", "tool": "get_menu"}}` for a `get_menu` ×4 history with `destination="order_support"` `(base)`.
- [ ] T010 [P] [US1] In `tests/integration/test_order_support_trajectory.py`, add a test for the order path, reusing `_fake_router_llm`, `_fake_order_llm`, and the tmp-db and ticket-dir fixtures. `(base)`
  - Script the order LLM to return `get_menu` tool-call `AIMessage`s with unique ids on every call (give 6 responses).
  - Invoke `build_graph(checkpointer=MemorySaver())`.
  - Assert:
    - `"__interrupt__" not in result`
    - `result["tool_limit_reached"] == {"agent": "order_support", "tool": "get_menu"}`
    - Exactly 3 `ToolMessage`s are in `result["messages"]`
    - `result["order_confirmed"] is False`
    - `result.get("order_ticket") is None`
    - No file was written to the isolated `tickets/` directory
- [ ] T011 [P] [US1] In `tests/integration/test_refund_trajectory.py`, add a matching test for the refund path using `_mock_router`, `_fake_refund_llm`, `_use_tmp_db`, `_seed_order`, and `_tool_call`. `(base)`
  - Script `lookup_order` tool calls on every step.
  - Assert:
    - `result["tool_limit_reached"] == {"agent": "refund", "tool": "lookup_order"}`
    - Exactly 3 `ToolMessage`s
    - `result["refund_resolved"] is False`
    - `result.get("refund_ticket") is None`
- [ ] T012 [P] [US1] In `tests/unit/test_interactive.py`, add tests for the limit path of `run_interactive`:
  - Patch `build_graph`, and patch `_run_conversation` to return a state with `"tool_limit_reached": {"agent": "order_support", "tool": "get_menu"}` and `messages=[AIMessage(content="", tool_calls=[...])]`.
  - Set stdin to `"hi\n\n/exit\n"`.
  - Record the order of events by monkeypatching `interactive.print_warning` and `Console.clear`.
  - Assert:
    - `print_warning` was called with `interactive.TOOL_LIMIT_WARNING` before `clear` `(base)`
    - The output contains `"Press Enter to start a new conversation."` `(base)`
    - The output doesn't contain `"Error:"` and the exit code is `0` `(edge)`
  - Add a test that `TOOL_LIMIT_WARNING == "Sorry, our system is having some issues right now. Please try again later."` `(base)`.
- [ ] T013 [US1] Run `uv run pytest tests/unit/test_tool_limit.py tests/unit/test_interactive.py tests/integration/test_order_support_trajectory.py tests/integration/test_refund_trajectory.py` and confirm the new tests from T008–T012 FAIL. Expected failures:
  - `ModuleNotFoundError` for `customer_support_fde.nodes.tool_limit`
  - The integration loops end by `GraphRecursionError` or by running more than 3 tools
  - `AttributeError: TOOL_LIMIT_WARNING`

  Don't implement until you've seen them fail.

### Implementation for User Story 1

- [ ] T014 [US1] Create `src/customer_support_fde/nodes/tool_limit.py`, following contracts/tool-limit.md and research R1–R3.
  - `MAX_CONSECUTIVE_TOOL_CALLS = 3`
  - `find_repeated_tool(messages)`:
    - Look only at messages after the last `HumanMessage`.
    - Take the `AIMessage`s with non-empty `tool_calls`, turn each into a set of tool names, and ignore `ToolMessage`s.
    - For each name in the newest step, in `tool_calls` order, count the consecutive steps (ending at the newest) whose set contains it.
    - Return the first name whose count is greater than `MAX_CONSECUTIVE_TOOL_CALLS`. Return `None` if the newest message is not an `AIMessage` with tool calls.
  - `route_after_agent(state)` returns `"__end__"`, `"tool_limit"`, or `"tools"`, as described in the contract.
  - `tool_limit_node(state)` returns `{"tool_limit_reached": {"agent": state["destination"], "tool": find_repeated_tool(state["messages"])}}`.
- [ ] T015 [US1] Update `src/customer_support_fde/graph.py`:
  - Import `route_after_agent` and `tool_limit_node` from `customer_support_fde.nodes.tool_limit`.
  - Add the node `"tool_limit_node"`.
  - Replace `tools_condition` on the `call_model` edge with `route_after_agent`, mapping `{"tools": "order_tools", "tool_limit": "tool_limit_node", "__end__": "await_customer"}`.
  - Replace it on the `refund_agent` edge, mapping `{"tools": "refund_tools", "tool_limit": "tool_limit_node", "__end__": "refund_await_customer"}`.
  - Add `graph.add_edge("tool_limit_node", END)`.
  - Remove the now-unused `tools_condition` import.
- [ ] T016 [US1] Update `src/customer_support_fde/interactive.py`:
  - Add `TOOL_LIMIT_WARNING = "Sorry, our system is having some issues right now. Please try again later."`.
  - In `run_interactive`, after `_run_conversation` returns, check `result.get("tool_limit_reached")`. If it's set:
    - Call `print_warning(TOOL_LIMIT_WARNING, console)`.
    - Then print `"Press Enter to start a new conversation."` and read one line with `sys.stdin.readline()`.
  - If it's not set, keep the existing `_print_turn(console, "ai", content)` path unchanged.
  - Both paths then reach the existing `console.clear()`.
- [ ] T017 [US1] Run the T013 command again and confirm all tests pass.

**Checkpoint**: A same-tool loop on either agent stops at 3 runs, and the customer sees the red warning. This is the MVP.

---

## Phase 4: User Story 2 - Normal conversations are unaffected (Priority: P1)

**Goal**: Legitimate tool use never trips the limit, and existing conversations behave exactly as before (FR-013, SC-003).

**Independent Test**: The non-trip rows of the contract table return `None`, a parallel multi-add and a cross-turn repeat don't trip the limit, and the full existing suite still passes.

### Tests for User Story 2 (write first, confirm red)

- [ ] T018 [P] [US2] In `tests/unit/test_tool_limit.py`, add parameterized tests for the non-trip rows of contracts/tool-limit.md. Each should return `None`:
  - The newest message is not a tool-calling `AIMessage` `(base)`
  - `get_menu` ×3 `(edge)`
  - `get_menu` ×3, then `get_cart`, then `get_menu` `(edge)`
  - One step with 4 `add_items_to_cart` calls `(edge)`
  - `lookup_order` ×3, then a `HumanMessage`, then `lookup_order` `(edge)`
  - Also add a test that `ToolMessage`s between steps don't change the result `(edge)`.
- [ ] T019 [P] [US2] In `tests/integration/test_order_support_trajectory.py`, add a test where the scripted order LLM does 3 consecutive `get_menu` steps and then replies with plain text. `(regression)`
  - Assert the graph pauses at `await_customer` (`"__interrupt__" in result`) and `tool_limit_reached` is not set.
  - Resume with `Command(resume=...)`, script 3 more `get_menu` steps and a text reply, and assert it still doesn't trip, which shows the count resets on the customer's reply.
- [ ] T020 [US2] Run `uv run pytest tests/unit/test_tool_limit.py tests/integration/test_order_support_trajectory.py`.
  - These are regression guards, so if T014 followed the contract they may already pass.
  - Confirm each new test would fail against a naive implementation: temporarily change `find_repeated_tool` to count all tool calls in the turn, see T018 and T019 go red, then revert.

### Implementation for User Story 2

- [ ] T021 [US2] If any T018 or T019 test fails against the real implementation, fix `find_repeated_tool` in `src/customer_support_fde/nodes/tool_limit.py` until they pass. Don't change the tests.
- [ ] T022 [US2] Run the full `uv run pytest` and confirm every test that passed at T001 still passes unchanged (SC-003).

**Checkpoint**: Limit behavior is proven not to affect normal conversations.

---

## Phase 5: User Story 3 - Reusable red warning display (Priority: P2)

**Goal**: `print_warning` is a robust, generic display that works for any string (FR-006, FR-007).

**Independent Test**: Multi-line, markup-like, empty, and non-terminal inputs all print as specified in contracts/print-warning.md.

### Tests for User Story 3 (write first, confirm red where applicable)

- [ ] T023 [P] [US3] In `tests/unit/test_interactive.py`, add `print_warning` tests:
  - A multi-line message `"line one\nline two"` on a forced color terminal has `"\x1b[31m"` applied to both lines `(edge)`.
  - A message containing `"[bold]not markup[/bold]"` prints those brackets literally `(edge)`.
  - With `force_terminal=False`, the full text prints with no `"\x1b["` `(edge)`.
  - `print_warning("", console)` doesn't raise `(edge)`.
  - With `console=None`, it prints to stdout via `_make_console()`, checked with `capsys` `(base)`.
- [ ] T024 [US3] Run `uv run pytest tests/unit/test_interactive.py` and note which T023 tests fail. The `Text`-based T006 implementation should already satisfy most of them, and any that pass are kept as regression guards.

### Implementation for User Story 3

- [ ] T025 [US3] Fix `print_warning` in `src/customer_support_fde/interactive.py` for any failing T023 case, then re-run `uv run pytest tests/unit/test_interactive.py` until green.

**Checkpoint**: Future system-issue warnings can call `print_warning(message)` directly.

---

## Phase 6: User Story 4 - Limit breaches are observable to operators (Priority: P3)

**Goal**: The Phoenix trace shows which agent and tool hit the limit (FR-012, SC-005).

**Independent Test**: The output of `tool_limit_node`, which Phoenix auto-instrumentation records as the span output, names the correct agent for both paths and the repeated tool.

### Tests for User Story 4 (write first, confirm red)

- [ ] T026 [P] [US4] In `tests/unit/test_tool_limit.py`, add a parameterized test that `tool_limit_node` reports the agent and tool correctly `(base)`:
  - `destination="refund"` with a `lookup_order` ×4 history → `{"agent": "refund", "tool": "lookup_order"}`
  - `destination="order_support"` with an `add_items_to_cart` ×4 history → `{"agent": "order_support", "tool": "add_items_to_cart"}`
- [ ] T027 [US4] Run `uv run pytest tests/unit/test_tool_limit.py` and confirm the result. These may already pass after T014; if so, they're regression guards for the trace payload.

### Implementation for User Story 4

- [ ] T028 [US4] No new tracing code (research R4). If T026 fails, fix `tool_limit_node` in `src/customer_support_fde/nodes/tool_limit.py`. If `PHOENIX_COLLECTOR_ENDPOINT` is available, follow step 3 of `specs/017-tool-call-limit/quickstart.md` to confirm a `tool_limit_node` span appears with `tool_limit_reached` in its output. If not, record that this manual check was skipped.

**Checkpoint**: Breaches can be diagnosed from traces.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T029 [P] In `CLAUDE.md`, under `# Architecture`, add a **tool_limit_node** bullet saying it ends the conversation when an agent calls the same tool more than 3 steps in a row within a customer turn. Also mention the limit in the `call_model` and `refund_agent` bullets.
- [ ] T030 [P] Bump the MINOR version in `pyproject.toml` from `0.9.0` to `0.10.0` (Constitution IV: backward-compatible feature).
- [ ] T031 Run `uv run pytest` (the full suite) and confirm it's green.
- [ ] T032 Do the manual check in step 2 of `specs/017-tool-call-limit/quickstart.md`:
  - Temporarily set `MAX_CONSECUTIVE_TOOL_CALLS = 0`, run `uv run start`, ask a menu question, and confirm the red warning, the Enter prompt, and the screen clear.
  - Then restore the value to `3` and confirm with `git diff src/customer_support_fde/nodes/tool_limit.py` that it's back to 3.
- [ ] T033 Run `uv run start --graph` (needs internet) and confirm `graph.png` shows `tool_limit_node` connected from both `call_model` and `refund_agent` to `__end__`. Don't commit `graph.png` unless it's already tracked.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Phase 1. Blocks every user story (US1 needs `tool_limit_reached` and `print_warning`).
- **US1 (Phase 3)**: Depends on Phase 2.
- **US2 (Phase 4)**: Depends on US1, since it guards the `find_repeated_tool` that US1 creates.
- **US3 (Phase 5)**: Depends on Phase 2 only. It can run in parallel with US1 and US2, but it touches `tests/unit/test_interactive.py` and `interactive.py`, so do it one after the other with T012 and T016.
- **US4 (Phase 6)**: Depends on US1 (`tool_limit_node`).
- **Polish (Phase 7)**: Depends on all stories.

### Within Each Story

- Test tasks, then the red run (you must see failures), then implementation, then the green run.
- T014 comes before T015, since the graph imports the module.
- T015 and T016 touch different files, but both are needed before T017.

### Parallel Opportunities

- T002 and T003 (different files). T005 and T006 (different files).
- T008–T011 in parallel (T008 and T009 share a new file, so write them together; T010 and T011 are different integration files). T012 is in `test_interactive.py`.
- T018 and T019 (different files).
- T026 alongside Phase 5 tasks (different files).
- T029 and T030.

---

## Parallel Example: User Story 1

```text
# Write the tests together (red pass):
Task: "T008/T009 find_repeated_tool, route_after_agent, tool_limit_node tests in tests/unit/test_tool_limit.py"
Task: "T010 order-path loop integration test in tests/integration/test_order_support_trajectory.py"
Task: "T011 refund-path loop integration test in tests/integration/test_refund_trajectory.py"
Task: "T012 run_interactive limit-path tests in tests/unit/test_interactive.py"

# Then T013 (confirm red), then implement T014 → T015, and T016 in parallel with T015, then T017 (green).
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1: baseline green.
2. Phase 2: state field and `print_warning` (red, then green).
3. Phase 3: US1 (red, then green).
4. **STOP and VALIDATE**: `uv run pytest`, plus step 2 of quickstart.

### Incremental Delivery

1. US1 is the MVP: loops are stopped and the customer is warned.
2. US2: regression guards proving normal flows are untouched.
3. US3: robustness of the generic warning display.
4. US4: trace payload guarantees.
5. Polish: docs, version, graph render.

---

## Notes

- Strict TDD: never write implementation in the same pass as its tests. Always run and see red first.
- Every new test needs its one-line category comment.
- Don't change existing tests to make them pass. SC-003 requires them to pass unchanged.
- Commit after each green checkpoint.
