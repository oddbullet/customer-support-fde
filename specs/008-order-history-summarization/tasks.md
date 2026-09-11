---

description: "Task list for Order Support Agent Conversation Memory & Summarization"
---

# Tasks: Order Support Agent Conversation Memory & Summarization

**Input**: Design documents from `/specs/008-order-history-summarization/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

**Tests**: Included — the project constitution (`.specify/memory/constitution.md` Principle I,
NON-NEGOTIABLE) requires tests before implementation for every feature, each carrying a
one-line comment naming what it verifies and its category (`(base)`/`(edge)`/`(error)`/
`(regression)`).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1, US2)
- Tasks touching the same file are listed in sequence (no `[P]`) even within a phase, to avoid
  concurrent edits to one file.

## Path Conventions

Single project — `src/customer_support_fde/`, `tests/` at repository root, per plan.md.

---

## Phase 1: Setup

**Purpose**: Confirm the feature needs no new project setup.

- [X] T001 Verify `ChatOpenAI(...).get_num_tokens_from_messages` is available on the installed
      `langchain-openai` version with `python -c "from langchain_openai import ChatOpenAI;
      print(hasattr(ChatOpenAI(model='x'), 'get_num_tokens_from_messages'))"` — expect `True`.
      No new dependency is added (research.md Decision 5); no file changes.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Persistent `messages` and the new state field, needed by both user stories, plus
every existing test fixture that constructs a full `SupportState` literal (adding a required
`TypedDict` key breaks every in-repo constructor — same pattern as
`specs/007-refund-policy-agent/plan.md`'s "Risks and mitigations").

**🚨 CRITICAL**: No user story work can begin until this phase is complete.

### Tests for Foundational work

> Write these first; they must fail against the current (pre-change) code.

- [X] T002 In `tests/unit/test_order_support_agent.py`, rewrite
      `test_await_customer_interrupts_when_not_confirmed` to assert that on resume,
      `await_customer` appends the reply as a new `HumanMessage` to the existing
      `state["messages"]` (not `RemoveMessage(id=REMOVE_ALL_MESSAGES)`) — start the test with a
      `state["messages"]` that already has one prior message, and assert the result list has
      both the prior message and the new `HumanMessage`, in that order. Comment tag:
      `(regression)` — supersedes the old wipe-every-turn assertion
      (contracts/order-support-agent.md `await_customer`).
- [X] T003 In `tests/unit/test_order_support_agent.py`, add a test asserting `call_model`
      renders an up-to-date cart-summary `SystemMessage` from `state["menu_items"]` on a call
      where `state["messages"]` already contains prior turns (not just the first, empty-list
      call) — i.e., the cart summary must still refresh every turn, not just once. Comment tag:
      `(regression)` — guards research.md Decision 2 against silently copying the refund
      agent's seed-once pattern.

### Implementation for Foundational work

- [X] T004 In `src/customer_support_fde/state.py`, add `order_conversation_summary: str | None`
      to the `SupportState` `TypedDict`, with an initial value of `None` (data-model.md
      "`SupportState` addition" table).
- [X] T005 In `src/customer_support_fde/cli.py`'s `run()`, seed
      `"order_conversation_summary": None` in the initial state dict passed to `graph.invoke`,
      alongside the existing 15 keys.
- [X] T006 In `tests/unit/test_order_support_agent.py`'s `_base_state`, add
      `"order_conversation_summary": None` to the returned dict.
- [X] T007 [P] In `tests/unit/test_refund_agent.py`'s `_base_state` (or equivalent state
      factory), add `"order_conversation_summary": None` to the returned dict.
- [X] T008 [P] In `tests/integration/test_order_support_trajectory.py`, add
      `"order_conversation_summary": None` to every initial-state literal in the file.
- [X] T009 [P] In `tests/integration/test_refund_trajectory.py`, add
      `"order_conversation_summary": None` to every initial-state literal in the file.
- [X] T010 [P] In `tests/integration/test_router_trajectory.py`, add
      `"order_conversation_summary": None` to every initial-state literal in the file.
- [X] T011 [P] In `tests/unit/test_cart_summary_and_ticket_nodes.py`, add
      `"order_conversation_summary": None` to every state literal in the file.
- [X] T012 [P] In `tests/unit/test_cli.py`'s `test_run_seeds_initial_state_with_refund_keys`,
      add `assert state["order_conversation_summary"] is None` alongside the existing
      refund-key assertions.
- [X] T013 In `src/customer_support_fde/nodes/order_support_agent.py`, rewrite `await_customer`
      so that on resume it appends `HumanMessage(content=str(answer))` to the existing
      `state["messages"]` (via `state["messages"] + [HumanMessage(...)]`) instead of returning
      `RemoveMessage(id=REMOVE_ALL_MESSAGES)`; keep updating `state["user_query"]` for CLI
      display/JSON output (contracts/order-support-agent.md `await_customer`; depends on T002).
- [X] T014 In `src/customer_support_fde/nodes/order_support_agent.py`, replace `_seed_messages`
      with a `_build_context_messages(state)` helper returning a fresh, ephemeral list:
      `SystemMessage(SYSTEM_PROMPT)`, then `SystemMessage(cart_summary)` if
      `_render_cart_summary(state["menu_items"])` is non-empty, then
      `SystemMessage(f"Summary of earlier conversation:\n{summary}")` if
      `state.get("order_conversation_summary")` is not `None`. Update `call_model` to seed
      `state["messages"]` with just `[HumanMessage(content=state["user_query"])]` when empty
      (no system/cart content persisted), prepend `_build_context_messages(state)` to
      `messages` only for the `.bind_tools(...).invoke(...)` call, and never write that
      ephemeral context back into `state["messages"]` (research.md Decision 2,
      contracts/order-support-agent.md `call_model`; depends on T003, T013).

**Checkpoint**: `messages` persists across turns, the cart summary still refreshes every turn,
and the state schema plus every existing fixture referencing it are consistent. Both user
stories can now be built on top of this.

---

## Phase 3: User Story 2 - Conversation history is condensed instead of discarded (Priority: P1)

**Goal**: Once a conversation has more than 3 turns and its accumulated token count exceeds
20,000, condense every turn older than the most recent 3 into a running summary and remove
them from `state["messages"]`.

**Independent Test**: At the unit level, construct a `state["messages"]` with more than 3 turns
and a token count over the threshold, call `call_model`, and inspect that older turns were
removed and `order_conversation_summary` was populated, while the last 3 turns remain.

**Note on ordering**: Built before User Story 1 (spec.md lists US1 first) because US1's
acceptance scenario explicitly requires the conversation to cross the summarization threshold —
it cannot be independently demonstrated until this mechanism exists. See "User Story
Dependencies" below.

### Tests for User Story 2

> Write these first; they must fail against the current (pre-change) code. All five live in
> `tests/unit/test_order_support_agent.py`, so none are marked `[P]` (same file).

- [X] T015 [US2] Test: with 3 or fewer `HumanMessage`-started turns in `state["messages"]` and
      a token count over `ORDER_HISTORY_TOKEN_THRESHOLD` (mock `get_num_tokens_from_messages`
      to return a value over threshold), `call_model`'s guard leaves `state["messages"]` and
      `state["order_conversation_summary"]` unchanged (FR-007). Comment tag: `(edge)`.
- [X] T016 [US2] Test: with more than 3 turns and a token count at/under
      `ORDER_HISTORY_TOKEN_THRESHOLD`, the guard leaves `state["messages"]` and
      `state["order_conversation_summary"]` unchanged (FR-003). Comment tag: `(edge)`.
- [X] T017 [US2] Test: with more than 3 turns and a token count over
      `ORDER_HISTORY_TOKEN_THRESHOLD`, the guard removes every message before the 3rd-from-last
      `HumanMessage` from `state["messages"]` (via `RemoveMessage`) and sets
      `order_conversation_summary` to the (mocked) condensation model's response, while the
      last 3 turns remain unchanged in `state["messages"]` (FR-003, FR-004, FR-005). Comment
      tag: `(base)`.
- [X] T018 [US2] Test: triggering condensation a second time with a pre-existing
      `order_conversation_summary` replaces it wholesale with the (mocked) model's new response
      — assert the old summary text is gone and only the new text is present, not a
      concatenation of both (FR-006). Comment tag: `(base)`.
- [X] T019 [US2] Test: when the mocked condensation model call raises an exception,
      `call_model` still returns a normal reply for that turn (the reply-generating call still
      runs and its `AIMessage` is appended), `state["messages"]`/`order_conversation_summary`
      are otherwise unchanged from before the guard ran, and no exception propagates out of
      `call_model` (FR-010). Comment tag: `(error)`.

### Implementation for User Story 2

All in `src/customer_support_fde/nodes/order_support_agent.py`; listed in dependency order, no
`[P]` (same file).

- [X] T020 [US2] Add module constant `ORDER_HISTORY_TOKEN_THRESHOLD = 20_000` (data-model.md
      "Token Threshold"; depends on T015-T019 existing and failing).
- [X] T021 [US2] At the top of `call_model`, before building context or calling the model:
      find the indices of every `HumanMessage` in `state["messages"]`; if there are 3 or fewer,
      skip the rest of the guard (FR-007). Otherwise measure
      `llm.get_num_tokens_from_messages(_build_context_messages(state) + state["messages"])`
      (a plain `ChatOpenAI` from `_build_llm()`, no tools bound) against
      `ORDER_HISTORY_TOKEN_THRESHOLD`; if at or under, skip the rest of the guard (FR-003)
      (depends on T020).
- [X] T022 [US2] Complete the guard: when triggered, compute `cutoff` as the index of the
      3rd-from-last `HumanMessage` and `older_messages = state["messages"][:cutoff]`. Call the
      model (no tools bound) with `state["order_conversation_summary"]` (if not `None`) plus
      `older_messages`, wrapped in a narrow `try/except Exception` scoped to only this call.
      On success: set `state["order_conversation_summary"]` to the new summary text (replacing,
      not appending, any previous value — FR-006) and update `state["messages"]` via
      `[RemoveMessage(id=m.id) for m in older_messages]` (FR-005). On failure: leave
      `state["messages"]`/`order_conversation_summary` unchanged and continue to the normal
      reply-generating call below (FR-010) (depends on T021).

**Checkpoint**: the condensation mechanism works and is independently verified at the unit
level — turn-count guard, threshold guard, successful condensation, re-condensation, and
silent-failure handling all covered.

---

## Phase 4: User Story 1 - Agent remembers earlier preferences in a long conversation (Priority: P1)

**Goal**: Prove, end-to-end through the compiled graph, that the agent still honors a
preference or decision the customer stated early in a conversation after that conversation has
crossed the condensation threshold.

**Independent Test**: Drive a multi-turn conversation through `build_graph()` (with
`ORDER_HISTORY_TOKEN_THRESHOLD` monkeypatched down to a small value so the threshold is
reachable in a fast test) where the customer states a dislike early on, continue past the
threshold, and confirm the agent's later behavior still reflects that earlier statement.

**Depends on**: User Story 2 (Phase 3) — this story's acceptance scenario requires condensation
to have actually happened.

### Tests for User Story 1

Both in `tests/integration/test_order_support_trajectory.py`; listed in sequence (same file).

- [X] T023 [US1] Replace `test_messages_do_not_accumulate_across_turns` with a test that
      monkeypatches `order_support_agent.ORDER_HISTORY_TOKEN_THRESHOLD` to a small value, drives
      enough turns through the compiled graph to cross it, and asserts: (a)
      `state["order_conversation_summary"]` is populated (not `None`), and (b)
      `state["messages"]` no longer contains the messages from the earliest turns (FR-001,
      FR-003). Comment tag: `(regression)` — supersedes the old wipe-every-turn assertion this
      test previously guarded.
- [X] T024 [US1] Add a test driving a conversation (same monkeypatched-threshold approach as
      T023) where the customer states a dislike/allergy in an early turn, continues chatting
      past the threshold, and asserts the agent's subsequent tool calls/replies still avoid or
      flag that ingredient — i.e., the preference survives condensation (spec.md User Story 1,
      Acceptance Scenario 1). Comment tag: `(base)`.

### Implementation for User Story 1

- [X] T025 [US1] If T024 does not already pass using the condensation prompt built in T022,
      strengthen that prompt in `src/customer_support_fde/nodes/order_support_agent.py` to more
      explicitly instruct the model to preserve customer-stated preferences, dislikes,
      allergies, and decisions verbatim rather than paraphrasing them away (FR-004; depends on
      T022, T024).

**Checkpoint**: both user stories are independently demonstrable; the feature's core value —
memory across a long conversation — is proven end-to-end.

---

## Phase 5: Polish & Cross-Cutting Concerns

- [X] T026 [P] Run `uv run pytest tests/unit tests/integration -v` for full-suite confirmation,
      including that the refund and router flows are unregressed (quickstart.md §1-2).
- [X] T027 Execute the manual scenario in `specs/008-order-history-summarization/quickstart.md`
      §3 (a live conversation with `ORDER_HISTORY_TOKEN_THRESHOLD` lowered) to confirm
      condensation is silent and preference retention is observable outside the test suite.
- [X] T028 [P] Bump `version` in `pyproject.toml` from `"0.3.0"` to `"0.4.0"` (plan.md
      Constitution Check — MINOR, backward-compatible feature addition).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately.
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS both user stories.
- **User Story 2 (Phase 3)**: Depends on Foundational.
- **User Story 1 (Phase 4)**: Depends on Foundational **and** User Story 2 — its acceptance
  scenario cannot be demonstrated until condensation exists (see note in Phase 4).
- **Polish (Phase 5)**: Depends on both user stories being complete.

### User Story Dependencies

- **User Story 2 (P1)**: Can start after Foundational. No dependency on User Story 1.
- **User Story 1 (P1)**: Can start after Foundational, but is **not independently testable**
  until User Story 2 is done — this is a deliberate, documented exception to the usual
  story-independence goal, because both stories are two views of the same underlying mechanism
  (condensation), and the spec's own Acceptance Scenario 1 for User Story 1 requires crossing
  the summarization threshold to observe.

### Within Each Phase

- Tests are written first and must fail before their corresponding implementation task.
- Tasks touching the same file are listed in the order they must be applied (no `[P]`).

### Parallel Opportunities

- Within Phase 2, T007 through T012 each touch a distinct file untouched by any other Phase 2
  task and can run in parallel with each other (and with T004/T005, which touch `state.py` and
  `cli.py` respectively) once T002/T003 exist.
- Phase 3 and Phase 4 have no internal `[P]` opportunities — each phase's tasks share one file
  (`order_support_agent.py` for Phase 3's implementation, `test_order_support_trajectory.py`
  for Phase 4's tests).
- T026 and T028 in Phase 5 are independent of each other and can run in parallel.

---

## Parallel Example: Phase 2 fixture updates

```bash
# Once T002/T003 exist (failing) and T004/T005 land, these can run together:
Task: "Add order_conversation_summary to _base_state in tests/unit/test_refund_agent.py"
Task: "Add order_conversation_summary to every state literal in tests/integration/test_order_support_trajectory.py"
Task: "Add order_conversation_summary to every state literal in tests/integration/test_refund_trajectory.py"
Task: "Add order_conversation_summary to every state literal in tests/integration/test_router_trajectory.py"
Task: "Add order_conversation_summary to every state literal in tests/unit/test_cart_summary_and_ticket_nodes.py"
Task: "Add the order_conversation_summary assertion in tests/unit/test_cli.py"
```

---

## Implementation Strategy

### MVP scope: both user stories together

Unlike a typical spec-kit feature, User Story 1 and User Story 2 are not independently
shippable slices — they are two observable facets of one mechanism (condensation). The MVP for
this feature is Phases 1-4 together: Setup, Foundational, User Story 2 (the mechanism), and
User Story 1 (proof that the mechanism delivers the customer-facing value). Stopping after
Phase 3 alone would leave the feature's actual value (spec.md's stated priority) unverified.

### Incremental delivery

1. Complete Setup + Foundational → transcript persists, schema updated, no regressions in
   existing fixtures.
2. Add User Story 2 → condensation mechanism verified at the unit level.
3. Add User Story 1 → mechanism proven end-to-end; **this is the MVP**.
4. Polish → full-suite confirmation, manual quickstart pass, version bump.

---

## Notes

- `[P]` tasks touch different files with no incomplete dependency between them.
- `[Story]` labels (`US1`, `US2`) appear only on Phase 3/4 tasks, per the task-generation rules.
- Every test task's implementation carries a one-line comment stating what it verifies and its
  category (`(base)`/`(edge)`/`(error)`/`(regression)`), per constitution Principle I.
- Commit after each task or logical group.
- Stop at either checkpoint (end of Phase 2, end of Phase 3) to validate before continuing.
