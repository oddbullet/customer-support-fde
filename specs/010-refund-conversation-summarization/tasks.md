---

description: "Task list for Refund Agent Conversation Memory & Summarization"
---

# Tasks: Refund Agent Conversation Memory & Summarization

**Input**: Design documents from `/specs/010-refund-conversation-summarization/`

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

- [X] T001 Confirm no new dependency is required (research.md Decision 5, same conclusion
      `specs/008-order-history-summarization` already reached) by running
      `python -c "from langchain_openai import ChatOpenAI; print(hasattr(ChatOpenAI(model='x'),
      'get_num_tokens_from_messages'))"` — expect `True`. No file changes.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Move the system prompt and sentiment reading out of `state["messages"]` into
ephemeral context (research.md Decision 2), and add the new `refund_conversation_summary` state
field everywhere a full `SupportState` literal is constructed — both needed by User Story 2's
condensation guard and User Story 1's end-to-end proof.

**🚨 CRITICAL**: No user story work can begin until this phase is complete.

### Tests for Foundational work

> Write these first; they must fail against the current (pre-change) code.

- [X] T002 In `tests/unit/test_refund_agent.py`, rewrite
      `test_refund_agent_seeds_system_prompt_and_query_when_messages_empty` (rename to
      `test_refund_agent_seeds_only_human_message_when_messages_empty`) to assert
      `result["messages"] == [HumanMessage(content="I got the wrong dish"), ai_message]` — i.e.
      no `SystemMessage` at all in `state["messages"]` once seeded. Comment tag: `(regression)` —
      supersedes the old assertion that a `SystemMessage` is seeded into `messages`
      (contracts/refund-agent.md `refund_agent`).
- [X] T003 In `tests/unit/test_refund_agent.py`, add
      `test_build_context_messages_includes_system_prompt_and_sentiment`: call the new
      `_build_context_messages(state)` helper directly (import from `refund_agent` module) with
      `state["sentiment"] = "negative"`, and assert it returns exactly two `SystemMessage`s in
      order — `SYSTEM_PROMPT` first, then `"Customer sentiment reading: negative."` second.
      Comment tag: `(base)`.
- [X] T004 In `tests/unit/test_refund_agent.py`, rewrite
      `test_refund_agent_omits_sentiment_message_when_sentiment_is_none` to call
      `_build_context_messages(state)` directly with `state["sentiment"] = None` and assert it
      returns exactly one `SystemMessage` (the system prompt only). Comment tag: `(edge)`.
- [X] T005 In `tests/unit/test_refund_agent.py`, rewrite
      `test_refund_agent_reuses_existing_transcript_on_later_turns` so `existing` contains only
      `HumanMessage`/`AIMessage` entries (no `SystemMessage`, since `messages` no longer holds
      one): `existing = [HumanMessage("I got the wrong dish"), AIMessage("What's your order
      id?"), HumanMessage("K7QP3M9X")]`; assert `result["messages"][:3] == existing` and
      `len(result["messages"]) == 4`. Comment tag: `(regression)` — supersedes the old
      `SystemMessage`-in-transcript assumption.
- [X] T006 In `tests/unit/test_refund_agent.py`, add
      `test_build_context_messages_includes_running_summary_when_present`: call
      `_build_context_messages(state)` with `state["refund_conversation_summary"] = "Order
      ABC123: customer confirmed return, refund submitted."` and assert the returned list's last
      `SystemMessage` contains that text. Comment tag: `(base)` — regression guard for
      research.md Decision 2, mirroring `specs/008`'s cart-summary-refresh guard.

### Implementation for Foundational work

- [X] T007 In `src/customer_support_fde/state.py`, add
      `refund_conversation_summary: str | None` to the `SupportState` `TypedDict`, with an
      initial value of `None` (data-model.md "`SupportState` addition" table).
- [X] T008 In `src/customer_support_fde/cli.py`'s `run()`, seed
      `"refund_conversation_summary": None` in the initial state dict passed to `graph.invoke`,
      alongside the existing 16 keys (depends on T007).
- [X] T009 In `tests/unit/test_cli.py`'s `test_run_seeds_initial_state_with_refund_keys`, add
      `assert state["refund_conversation_summary"] is None` alongside the existing
      `order_conversation_summary` assertion (depends on T008).
- [X] T010 [P] In `tests/unit/test_refund_agent.py`'s `_base_state`, add
      `"refund_conversation_summary": None` to the returned dict (depends on T007).
- [X] T011 [P] In `tests/unit/test_order_support_agent.py`'s `_base_state`, add
      `"refund_conversation_summary": None` to the returned dict, for consistency with the full
      `SupportState` shape (depends on T007).
- [X] T012 [P] In `tests/unit/test_cart_summary_and_ticket_nodes.py`, add
      `"refund_conversation_summary": None` to both `SupportState` literals in the file (depends
      on T007).
- [X] T013 [P] In `tests/integration/test_router_trajectory.py`, add
      `"refund_conversation_summary": None` to the initial-state literal in the file (depends on
      T007).
- [X] T014 [P] In `tests/integration/test_order_support_trajectory.py`, add
      `"refund_conversation_summary": None` to every initial-state literal in the file (depends
      on T007).
- [X] T015 [P] In `tests/integration/test_refund_trajectory.py`, add
      `"refund_conversation_summary": None` to every `initial_state` literal in the file
      (depends on T007).
- [X] T016 In `src/customer_support_fde/nodes/refund_agent.py`, replace `_seed_messages` with a
      `_build_context_messages(state)` helper returning a fresh, ephemeral list:
      `SystemMessage(content=SYSTEM_PROMPT)`, then
      `SystemMessage(content=f"Customer sentiment reading: {sentiment}.")` if
      `state.get("sentiment")` is not `None`, then
      `SystemMessage(content=f"Summary of earlier conversation:\n{summary}")` if
      `state.get("refund_conversation_summary")` is not `None` (contracts/refund-agent.md
      `refund_agent`, research.md Decision 2; depends on T002-T006, T007).
- [X] T017 In `src/customer_support_fde/nodes/refund_agent.py`, update `refund_agent(state)` to
      seed `state["messages"]` with just `[HumanMessage(content=state["user_query"])]` when
      empty (no system/sentiment content persisted), build `context =
      _build_context_messages(state)` fresh for this call, call
      `llm.bind_tools(_REFUND_TOOLS).invoke(context + messages)`, and append the resulting
      `AIMessage` to `messages` only (never to `context`) — never write `context` back into
      `state["messages"]` (contracts/refund-agent.md `refund_agent`; depends on T016).

**Checkpoint**: `messages` holds only real exchanges, the system prompt/sentiment reading are
rebuilt fresh every call, and the state schema plus every existing fixture referencing it are
consistent. Both user stories can now be built on top of this.

---

## Phase 3: User Story 2 - Refund conversation history is condensed instead of growing without bound (Priority: P1)

**Goal**: Once a refund conversation has more than 3 turns and its accumulated token count
exceeds 20,000, condense every turn older than the most recent 3 into a running summary and
remove them from `state["messages"]`, keeping separate orders' facts and outcomes distinct.

**Independent Test**: At the unit level, construct a `state["messages"]` with more than 3 turns
and a token count over the threshold, call `refund_agent`, and inspect that older turns were
removed and `refund_conversation_summary` was populated, while the last 3 turns remain.

**Note on ordering**: Built before User Story 1 (spec.md lists US1 first) because US1's
acceptance scenarios explicitly require the conversation to cross the summarization threshold —
it cannot be independently demonstrated until this mechanism exists. Same reordering
`specs/008-order-history-summarization/tasks.md` applied for the order agent's equivalent
feature. See "User Story Dependencies" below.

### Tests for User Story 2

> Write these first; they must fail against the current (pre-change) code. All six live in
> `tests/unit/test_refund_agent.py`, so none are marked `[P]` (same file).

- [X] T018 [US2] Test: with 3 or fewer `HumanMessage`-started turns in `state["messages"]` and a
      token count over `REFUND_HISTORY_TOKEN_THRESHOLD` (mock `get_num_tokens_from_messages` to
      return a value over threshold), `refund_agent`'s guard leaves `state["messages"]` and
      `state["refund_conversation_summary"]` unchanged (FR-007). Comment tag: `(edge)`.
- [X] T019 [US2] Test: with more than 3 turns and a token count at/under
      `REFUND_HISTORY_TOKEN_THRESHOLD`, the guard leaves `state["messages"]` and
      `state["refund_conversation_summary"]` unchanged (FR-003). Comment tag: `(edge)`.
- [X] T020 [US2] Test: with more than 3 turns and a token count over
      `REFUND_HISTORY_TOKEN_THRESHOLD`, the guard removes every message before the 3rd-from-last
      `HumanMessage` from `state["messages"]` (via `RemoveMessage`) and sets
      `refund_conversation_summary` to the (mocked) condensation model's response, while the
      last 3 turns remain unchanged in `state["messages"]` (FR-003, FR-004, FR-005). Comment
      tag: `(base)`.
- [X] T021 [US2] Test: triggering condensation a second time with a pre-existing
      `refund_conversation_summary` replaces it wholesale with the (mocked) model's new response
      — assert the old summary text is gone and only the new text is present, not a
      concatenation of both (FR-006). Comment tag: `(base)`.
- [X] T022 [US2] Test: the condensation instructions given to the model (the `SystemMessage`
      content passed as the first element of the condensation call) explicitly direct it to
      preserve, per order discussed, the order identified, facts gathered, and any outcome
      reached, and to keep separate orders' facts and outcomes distinct rather than merged
      (FR-004, spec Clarifications). Comment tag: `(base)`.
- [X] T023 [US2] Test: when the mocked condensation model call raises an exception,
      `refund_agent` still returns a normal reply for that turn (the reply-generating call still
      runs and its `AIMessage` is appended), `state["messages"]`/`refund_conversation_summary`
      are otherwise unchanged from before the guard ran, and no exception propagates out of
      `refund_agent` (FR-010). Comment tag: `(error)`.

### Implementation for User Story 2

All in `src/customer_support_fde/nodes/refund_agent.py`; listed in dependency order, no `[P]`
(same file).

- [X] T024 [US2] Add module constant `REFUND_HISTORY_TOKEN_THRESHOLD = 20_000` (data-model.md
      "Token Threshold") and `_CONDENSATION_INSTRUCTIONS`, a system-prompt string directing the
      model to summarize the refund conversation while preserving, per order discussed, the
      order identified, the facts gathered toward a policy decision (what was missing, any
      substitute received, any return commitment given or declined), the customer's complaint
      description, and any policy decision already reached — keeping separate orders' facts and
      outcomes distinct rather than merged, and keeping only the most recent statement when the
      customer restated a fact (FR-004, FR-009, spec Clarifications; depends on T018-T023
      existing and failing).
- [X] T025 [US2] At the top of `refund_agent`, before building context or calling the model:
      find the indices of every `HumanMessage` in `state["messages"]`; if there are 3 or fewer,
      skip the rest of the guard (FR-007). Otherwise measure
      `llm.get_num_tokens_from_messages(_build_context_messages(state) + state["messages"])` (a
      plain `ChatOpenAI` from `_build_llm()`, no tools bound) against
      `REFUND_HISTORY_TOKEN_THRESHOLD`; if at or under, skip the rest of the guard (FR-003)
      (depends on T024).
- [X] T026 [US2] Complete the guard: when triggered, compute `cutoff` as the index of the
      3rd-from-last `HumanMessage` and `older_messages = state["messages"][:cutoff]`. Call the
      model (no tools bound) with `[SystemMessage(_CONDENSATION_INSTRUCTIONS)]` plus
      `SystemMessage(f"Previous summary:\n{previous_summary}")` (if
      `state.get("refund_conversation_summary")` is not `None`) plus `older_messages`, wrapped
      in a narrow `try/except Exception` scoped to only this call. On success: set
      `state["refund_conversation_summary"]` to the new summary text (replacing, not appending,
      any previous value — FR-006) and update `state["messages"]` via
      `[RemoveMessage(id=m.id) for m in older_messages]` (FR-005). On failure: leave
      `state["messages"]`/`refund_conversation_summary` unchanged and continue to the normal
      reply-generating call below (FR-010) (depends on T025).

**Checkpoint**: the condensation mechanism works and is independently verified at the unit
level — turn-count guard, threshold guard, successful condensation, re-condensation, per-order
distinctness instructions, and silent-failure handling all covered.

---

## Phase 4: User Story 1 - Agent stays consistent with earlier policy facts in a long refund conversation (Priority: P1)

**Goal**: Prove, end-to-end through the compiled graph, that the refund agent still honors the
order identified, facts gathered, and any outcome already reached after a conversation has
crossed the condensation threshold — including when more than one order was discussed.

**Independent Test**: Drive a multi-turn refund conversation through `build_graph()` (with
`REFUND_HISTORY_TOKEN_THRESHOLD` monkeypatched down to a small value so the threshold is
reachable in a fast test) where the customer establishes an order and its facts early on,
continue past the threshold, and confirm the agent's later behavior and the resulting refund
ticket still reflect what was established earlier.

**Depends on**: User Story 2 (Phase 3) — this story's acceptance scenarios require condensation
to have actually happened.

### Tests for User Story 1

All in `tests/integration/test_refund_trajectory.py`; listed in sequence (same file).

- [X] T027 [US1] Add a test that monkeypatches `refund_agent.REFUND_HISTORY_TOKEN_THRESHOLD` to
      a small value, drives enough turns through the compiled graph to cross it, and asserts:
      (a) `state["refund_conversation_summary"]` is populated (not `None`), and (b)
      `state["messages"]` no longer contains the messages from the earliest turns (FR-001,
      FR-002, FR-003). Comment tag: `(base)`.
- [X] T028 [US1] Add a test driving a single-order refund conversation (same
      monkeypatched-threshold approach as T027) where the order is identified and the key facts
      (e.g. a substitute dish arrived and the customer confirmed they'll return it) are
      established early, the conversation continues past the threshold with repeated pushback,
      and asserts the final `refund_ticket`/stored refund request still reflects those
      early-established facts without the agent re-asking for them or reversing the outcome
      (spec.md User Story 1, Acceptance Scenarios 1-2; FR-004, FR-011). Comment tag: `(base)`.
- [X] T029 [US1] Add a test driving a two-order refund conversation (same monkeypatched-threshold
      approach) where the first order's issue is resolved (refund submitted, denied, or a
      complaint logged), the conversation continues past the threshold, and the customer then
      raises a problem with a second, different order — asserting the final state/ticket
      correctly reflects the second order's own outcome without conflating it with the first
      order's already-reached outcome (spec.md User Story 1, Acceptance Scenario 3; FR-004, spec
      Clarifications). Comment tag: `(base)`.

### Implementation for User Story 1

- [X] T030 [US1] If T028 or T029 do not already pass using the condensation instructions built
      in T024, strengthen `_CONDENSATION_INSTRUCTIONS` in
      `src/customer_support_fde/nodes/refund_agent.py` to more explicitly instruct the model to
      preserve per-order facts and outcomes distinctly and verbatim rather than paraphrasing or
      merging them away (FR-004; depends on T024, T028, T029).

**Checkpoint**: both user stories are independently demonstrable; the feature's core value —
policy-consistent memory across a long, possibly multi-order refund conversation — is proven
end-to-end.

---

## Phase 5: Polish & Cross-Cutting Concerns

- [X] T031 [P] Run `uv run pytest tests/unit tests/integration -v` for full-suite confirmation,
      including that the order-support and router flows are unregressed (quickstart.md §2) and
      that refund policy/db behavior is unaffected by condensation (quickstart.md §3).
- [X] T032 Execute the manual scenario in
      `specs/010-refund-conversation-summarization/quickstart.md` §4 (a live refund conversation
      with `REFUND_HISTORY_TOKEN_THRESHOLD` lowered) to confirm condensation is silent and
      fact/outcome retention is observable outside the test suite.
- [X] T033 [P] Confirm no new dependency was introduced: `git diff --stat -- pyproject.toml
      uv.lock` shows no unexpected changes (quickstart.md §5).
- [X] T034 [P] Bump `version` in `pyproject.toml` from `"0.4.0"` to `"0.5.0"` (plan.md
      Constitution Check — MINOR, backward-compatible feature addition).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately.
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS both user stories.
- **User Story 2 (Phase 3)**: Depends on Foundational.
- **User Story 1 (Phase 4)**: Depends on Foundational **and** User Story 2 — its acceptance
  scenarios cannot be demonstrated until condensation exists (see note in Phase 4).
- **Polish (Phase 5)**: Depends on both user stories being complete.

### User Story Dependencies

- **User Story 2 (P1)**: Can start after Foundational. No dependency on User Story 1.
- **User Story 1 (P1)**: Can start after Foundational, but is **not independently testable**
  until User Story 2 is done — this is a deliberate, documented exception to the usual
  story-independence goal, because both stories are two views of the same underlying mechanism
  (condensation), and the spec's own Acceptance Scenarios for User Story 1 require crossing the
  summarization threshold to observe. Same exception `specs/008` documented for the order
  agent's equivalent feature.

### Within Each Phase

- Tests are written first and must fail before their corresponding implementation task.
- Tasks touching the same file are listed in the order they must be applied (no `[P]`).

### Parallel Opportunities

- Within Phase 2, T010 through T015 each touch a distinct file untouched by any other Phase 2
  task and can run in parallel with each other (and with T007/T008, which touch `state.py` and
  `cli.py` respectively) once T002-T006 exist.
- Phase 3 and Phase 4 have no internal `[P]` opportunities — each phase's tasks share one file
  (`refund_agent.py` for Phase 3's implementation, `test_refund_trajectory.py` for Phase 4's
  tests).
- T031, T033, and T034 in Phase 5 are independent of each other and can run in parallel.

---

## Parallel Example: Phase 2 fixture updates

```bash
# Once T002-T006 exist (failing) and T007/T008 land, these can run together:
Task: "Add refund_conversation_summary to _base_state in tests/unit/test_order_support_agent.py"
Task: "Add refund_conversation_summary to both state literals in tests/unit/test_cart_summary_and_ticket_nodes.py"
Task: "Add refund_conversation_summary to the initial-state literal in tests/integration/test_router_trajectory.py"
Task: "Add refund_conversation_summary to every initial-state literal in tests/integration/test_order_support_trajectory.py"
Task: "Add refund_conversation_summary to every initial_state literal in tests/integration/test_refund_trajectory.py"
```

---

## Implementation Strategy

### MVP scope: both user stories together

Unlike a typical spec-kit feature, User Story 1 and User Story 2 are not independently
shippable slices — they are two observable facets of one mechanism (condensation), the same
situation `specs/008-order-history-summarization` was in. The MVP for this feature is Phases
1-4 together: Setup, Foundational, User Story 2 (the mechanism), and User Story 1 (proof that
the mechanism delivers the customer-facing value, including across multiple orders). Stopping
after Phase 3 alone would leave the feature's actual value (spec.md's stated priority)
unverified.

### Incremental delivery

1. Complete Setup + Foundational → context rebuilt fresh each call, schema updated, no
   regressions in existing fixtures.
2. Add User Story 2 → condensation mechanism verified at the unit level.
3. Add User Story 1 → mechanism proven end-to-end, including the multi-order case; **this is
   the MVP**.
4. Polish → full-suite confirmation, manual quickstart pass, version bump.

---

## Notes

- `[P]` tasks touch different files with no incomplete dependency between them.
- `[Story]` labels (`US1`, `US2`) appear only on Phase 3/4 tasks, per the task-generation rules.
- Every test task's implementation carries a one-line comment stating what it verifies and its
  category (`(base)`/`(edge)`/`(error)`/`(regression)`), per constitution Principle I.
- Commit after each task or logical group.
- Stop at either checkpoint (end of Phase 2, end of Phase 3) to validate before continuing.
