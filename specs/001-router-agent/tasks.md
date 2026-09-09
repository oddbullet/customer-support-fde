---

description: "Task list template for feature implementation"
---

# Tasks: Router Agent with Sentiment-Aware Refund Handoff

**Input**: Design documents from `/specs/001-router-agent/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/support-state.md, contracts/cli-route.md, quickstart.md

**Tests**: Included and REQUIRED — Constitution Principle I (Test-First, NON-NEGOTIABLE) mandates failing tests before implementation for this feature (see plan.md Constitution Check).

**Organization**: Tasks are grouped by user story (spec.md) to enable independent implementation and testing of each story. User Stories 1 and 2 both depend on the same single-LLM-call `router_agent` node (research.md §2: one structured-output call always returns both `destination` and `sentiment`; code — not the model — enforces that `sentiment` is discarded outside the refund path). User Story 3 (the clarifying-question path) depends on `router_agent` being able to return the third `"unclear"` destination and adds a new, deliberately non-LLM node (`clarify_intent`) plus a second conditional edge on top of User Story 1's graph. Story independence is therefore expressed as: each story adds its own failing tests plus the specific behavior/prompt guardrails or nodes that make those tests pass, on top of what earlier stories built.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)
- Exact file paths are included in every task description

## Path Conventions

Single project (per plan.md Project Structure): `src/customer_support_fde/`, `tests/unit/`, `tests/integration/` at repository root.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the project is ready for implementation

- [X] T001 Verify project dependencies declared in `pyproject.toml` (`langgraph>=1.2.11`, `langchain-openai>=1.6.1`, `agentevals>=0.0.9`, `langchain>=1.4.0`, `pytest>=9.1.1`) are installed by running `uv sync` from the repo root
- [X] T002 [P] Create `.env.example` in the repo root documenting the environment variables required per `quickstart.md`: `OPENROUTER_API_KEY` (required for live calls), `OPENROUTER_MODEL` (optional, falls back to project default), `LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`, `LANGSMITH_PROJECT` (optional, LangSmith tracing per Constitution Principle IV)

**Checkpoint**: Environment ready for module implementation

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core state contract and placeholder nodes that every user story's graph/tests depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T003 Create `SupportState` TypedDict in `src/customer_support_fde/state.py` per `contracts/support-state.md`: `user_query: str`, `destination: Literal["order_support", "refund", "unclear"]`, `sentiment: Literal["positive", "neutral", "negative"] | None`. `"unclear"` is a transient value only `router_agent` may produce and only `clarify_intent` resolves — no other node ever sets or reads it
- [X] T004 [P] Create placeholder node functions `order_support_agent(state: SupportState) -> SupportState` and `refund_agent(state: SupportState) -> SupportState` in `src/customer_support_fde/downstream_agents.py`. Per `contracts/support-state.md`: `order_support_agent` MUST accept a `SupportState` with `destination == "order_support"` and `sentiment is None`; `refund_agent` MUST accept a `SupportState` with `destination == "refund"` and `sentiment` set to one of the three categories. Neither ever receives `destination == "unclear"`. Both currently just return the state unchanged (no other behavior defined for this feature)
- [X] T005 [P] Create the `RouterDecision` Pydantic model in `src/customer_support_fde/router_agent.py` per `data-model.md`: `destination: Literal["order_support", "refund", "unclear"]`, `sentiment: Literal["positive", "neutral", "negative"]`
- [X] T006 Configure the OpenRouter-backed `ChatOpenAI` client in `src/customer_support_fde/router_agent.py` (depends on T005): `base_url="https://openrouter.ai/api/v1"`, `api_key` read from the `OPENROUTER_API_KEY` environment variable, model selected via the `OPENROUTER_MODEL` environment variable with a small structured-output-capable default, bound via `.with_structured_output(RouterDecision)`

**Checkpoint**: Foundation ready — `router_agent`, and every user story's graph, can now be built

---

## Phase 3: User Story 1 - General question routed to order/support (Priority: P1) 🎯 MVP

**Goal**: A customer's menu/ingredient/ordering question is classified as order/support and forwarded with the full original text and no sentiment.

**Independent Test**: Submit clear order/support-style requests and confirm the router selects `order_support` and forwards the unaltered request text with no sentiment attached.

### Tests for User Story 1 ⚠️

> **Write these tests FIRST, ensure they FAIL before implementation**

- [X] T007 [P] [US1] Write a failing unit test in `tests/unit/test_router_agent.py`: with the LLM boundary faked/mocked to return `RouterDecision(destination="order_support", sentiment="positive")` for a clear order/support-style input (e.g. "What's in the kung pao chicken, does it have peanuts?"), assert `router_agent(state)` returns a `SupportState` with `destination == "order_support"`, `sentiment is None` (FR-004), and `user_query` unchanged (FR-005)
- [X] T008 [P] [US1] Write a failing integration test in `tests/integration/test_router_trajectory.py`: compile `build_graph()` (once it exists — see T010) with a `langgraph.checkpoint.memory.MemorySaver` checkpointer, invoke it with a unique `thread_id` and a clear order/support-style sample request (LLM boundary faked), extract the trajectory via `agentevals.graph_trajectory.utils.extract_langgraph_trajectory_from_thread`, and assert it strictly matches `["router_agent", "order_support_agent"]` via `agentevals.graph_trajectory.strict.graph_trajectory_strict_match`

### Implementation for User Story 1

- [X] T009 [US1] Implement the `router_agent(state: SupportState) -> SupportState` node function in `src/customer_support_fde/router_agent.py` (depends on T006, makes T007 pass): invoke the structured-output LLM call with `state["user_query"]`, copy `destination` to the returned state, and — enforced in code, not left to the model — set `sentiment` to `None` whenever `destination == "order_support"` (FR-004, per `research.md` §2). This story only requires correct behavior for clear-cut order/support input; classifying ambiguous/mixed-signal input as `"unclear"` (rather than defaulting, per revised FR-008/FR-009) is covered by User Story 3
- [X] T010 [US1] Implement `build_graph()` in `src/customer_support_fde/graph.py` (depends on T004, T009, makes T008 pass): `StateGraph(SupportState)` with `router_agent` as the entry node, `add_conditional_edges(router_agent, <path fn reading state["destination"]>, {"order_support": "order_support_agent", "refund": "refund_agent"})` (the `"unclear"` branch is added in User Story 3 once `clarify_intent` exists), both placeholder nodes routing to `END`; the compiled graph must accept a checkpointer argument for trajectory extraction and for the interrupt/resume flow added in User Story 3

**Checkpoint**: User Story 1 fully functional and independently testable — order/support routing works end-to-end with no sentiment ever attached

---

## Phase 4: User Story 2 - Complaint or refund request routed with sentiment (Priority: P1)

**Goal**: A customer's clear complaint/refund message is classified as refund, assessed for sentiment, and forwarded with both the full original text and the sentiment assessment.

**Independent Test**: Submit clear complaint/refund-style requests spanning calm, frustrated, and angry tones and confirm the router selects `refund` and forwards both the full text and a sentiment assessment.

### Tests for User Story 2 ⚠️

> **Write these tests FIRST, ensure they FAIL before implementation**

- [X] T011 [P] [US2] Write failing unit tests in `tests/unit/test_router_agent.py`: (a) with the LLM boundary faked to return `RouterDecision(destination="refund", sentiment="negative")` for a clear refund-style input (e.g. "My order arrived cold and an hour late, I want my money back"), assert `router_agent(state)` returns `destination == "refund"` and `sentiment == "negative"` (FR-003, FR-006); (b) assert `sentiment`, when present, is always exactly one of `"positive"`, `"neutral"`, `"negative"` — never a free-form or numeric value (`data-model.md` validation rules)
- [X] T012 [P] [US2] Write a failing integration test in `tests/integration/test_router_trajectory.py`: invoke `build_graph()` with a clear refund-style sample request (LLM boundary faked) and assert the extracted trajectory strictly matches `["router_agent", "refund_agent"]`

### Implementation for User Story 2

- [X] T013 [US2] Extend the system prompt used in `src/customer_support_fde/router_agent.py`'s structured-output call (depends on T009, makes T011–T012 pass) so that clearly refund-classified requests with empty/near-empty or no discernible sentiment still produce a best-effort `neutral` sentiment rather than failing the handoff (Edge Cases in spec.md)

**Checkpoint**: User Stories 1 AND 2 both work independently — refund path always carries a valid sentiment, order/support path never does

---

## Phase 5: User Story 3 - Ambiguous or mixed-signal request resolved by asking the customer (Priority: P1)

**Goal**: When a request is ambiguous, or mixes both ordering/question and refund/complaint signals, the system does not guess — it directly asks the customer to choose one of three options (placing an order, asking a general question, requesting a refund) and routes based on the answer, re-asking if the answer is unrecognized. If the answer resolves to refund, the sentiment already computed by `router_agent` is forwarded — the customer is never asked a second, separate sentiment question.

**Independent Test**: Submit ambiguous requests (e.g. "hello") and mixed-signal requests (e.g. "the food I ordered was cold, and also what's in the mapo tofu?") and confirm: the three-way clarifying question is presented instead of a silent default; each of the three possible answers routes to the correct final destination; an unrecognized answer causes the question to be asked again; and a refund resolution carries forward the original sentiment rather than eliciting a new one.

### Tests for User Story 3 ⚠️

> **Write these tests FIRST, ensure they FAIL before implementation**

- [X] T014 [P] [US3] Write a failing unit test in `tests/unit/test_router_agent.py`: with the LLM boundary faked to return `RouterDecision(destination="unclear", sentiment="neutral")` for an ambiguous input (e.g. "hello") and, separately, for a mixed-signal input (e.g. "the food I ordered was cold, and also what's in the mapo tofu?"), assert `router_agent(state)` returns `destination == "unclear"` and keeps the computed `sentiment` in state rather than discarding it (FR-008, FR-009 — the value must survive for `clarify_intent` to forward per FR-013)
- [X] T015 [P] [US3] Write failing unit tests in a new file `tests/unit/test_clarify_intent.py`, with the `interrupt()` boundary faked/resumed directly (no LLM involved): (a) resuming with `"placing an order"` or `"asking a general question"` resolves `destination` to `"order_support"` and `sentiment` to `None`; (b) resuming with `"requesting a refund"` resolves `destination` to `"refund"` and `sentiment` to exactly the value already present in the incoming state (i.e. what `router_agent` computed) — not recomputed, not re-elicited (FR-013); (c) resuming with an unrecognized answer (e.g. `"banana"`) causes `clarify_intent` to call `interrupt()` again with the same three-choice question rather than returning a `SupportState` (FR-012)
- [X] T016 [P] [US3] Write failing integration tests in `tests/integration/test_router_trajectory.py`: for an ambiguous sample and a mixed-signal sample (LLM boundary faked to return `destination="unclear"`), invoke `build_graph()` with a `MemorySaver` checkpointer and a `thread_id`, catch the interrupt raised at `clarify_intent`, resume via `graph.invoke(Command(resume=<choice>), config)` for each of the three possible choices, and assert the trajectory strictly matches `["router_agent", "clarify_intent", "order_support_agent"]` or `["router_agent", "clarify_intent", "refund_agent"]` depending on the resumed choice

### Implementation for User Story 3

- [X] T017 [US3] Extend the system prompt used in `src/customer_support_fde/router_agent.py`'s structured-output call (depends on T009, makes T014 pass) to classify strictly into `order_support` / `refund` / `unclear`: `unclear` for a request with no clear order/support-vs-refund signal (FR-008) and for a request that mixes both ordering/question and refund/complaint signals (FR-009) — the model MUST NOT be instructed to default either case to a concrete destination. Additionally, in code, map any unparseable/invalid `destination` value returned by the model to `"unclear"` rather than guessing (`research.md` §6)
- [X] T018 [US3] Create `src/customer_support_fde/clarify_intent.py` implementing `clarify_intent(state: SupportState) -> SupportState` (depends on T003, makes T015 pass). No LLM call. Call `interrupt()` with the fixed question "Are you placing an order, asking a general question, or requesting a refund?"; deterministically map the resumed answer to `"order_support"` (for "placing an order" or "asking a general question") or `"refund"` (for "requesting a refund") per `data-model.md`'s `ClarificationAnswer` mapping; on an unrecognized answer, call `interrupt()` again with the same question rather than guessing or failing (FR-012); once resolved, set `sentiment` to `None` if the resolved destination is `"order_support"`, or leave it as the value already present in `state["sentiment"]` (computed earlier by `router_agent`) if `"refund"` — never compute, request, or ask the customer for a new sentiment value (FR-013)
- [X] T019 [US3] Extend `build_graph()` in `src/customer_support_fde/graph.py` (depends on T010, T018, makes T016 pass): add `clarify_intent` as a node; change `router_agent`'s conditional edge to the 3-way mapping `{"order_support": "order_support_agent", "refund": "refund_agent", "unclear": "clarify_intent"}`; add a second conditional edge from `clarify_intent` to `{"order_support": "order_support_agent", "refund": "refund_agent"}`

**Checkpoint**: User Stories 1, 2, and 3 all work independently — every ambiguous or mixed-signal request is resolved by directly asking the customer, never by a silent default

---

## Phase 6: User Story 4 - Routing behavior is verifiable end-to-end (Priority: P2)

**Goal**: A developer or reviewer needs confidence that the router consistently sends each type of request down the correct path — including via the clarifying question — before any real order/support or refund logic is built behind it, and that failures are surfaced rather than swallowed.

**Independent Test**: Run a labeled suite of representative requests (order/support, refund, and ambiguous/mixed-signal) through the router — answering the clarifying question where one is presented — and confirm, for each one, which destination was chosen and what information (query text, and sentiment when applicable) was attached, independent of what the placeholder destinations do with it.

### Tests for User Story 4 ⚠️

> **Write these tests FIRST, ensure they FAIL before implementation**

- [X] T020 [P] [US4] Write a failing unit test in `tests/unit/test_router_agent.py`: with the LLM boundary faked to raise an exception, assert `router_agent(state)` propagates the failure (raises) rather than returning a partial/corrupted `SupportState` (FR-011)
- [X] T021 [P] [US4] Assemble a labeled sample set (≥10 requests spanning clear order/support cases, clear refund cases across calm/frustrated/angry tones, and ambiguous/mixed-signal cases from spec.md's Edge Cases) as fixtures in `tests/integration/test_router_trajectory.py`, and write a failing integration test that runs each sample through `build_graph()` (LLM boundary faked per case; ambiguous/mixed-signal cases resumed with a fixed, correct answer to the clarifying question) and asserts overall routing accuracy — the final destination — is ≥90% (SC-001, FR-010)

### Implementation for User Story 4

- [X] T022 [US4] Add error propagation in `src/customer_support_fde/router_agent.py`'s `router_agent` node (depends on T009, makes T020 pass): ensure any exception from the structured-output LLM call is allowed to propagate rather than being caught/swallowed or mapped to a default state
- [X] T023 [US4] Implement CLI argument/stdin parsing, the interrupt/resume clarifying exchange, and output formatting in `src/customer_support_fde/cli.py` per `contracts/cli-route.md` (depends on T010, T019, T022): read the customer request from a positional argument or stdin; invoke `build_graph()`; if the graph pauses at `clarify_intent`'s `interrupt()`, print the three-choice question, read an answer from stdin, and resume via `Command(resume=...)`, repeating on an unrecognized answer (FR-012); once resolved, print human-readable text by default (`Destination:`, `Sentiment:`, `Query:` lines, with the `Sentiment:` line omitted entirely — not printed as `None`/blank — for the order/support path) or JSON with `--json` (the `sentiment` key absent, not `null`, for the order/support path); on failure, print nothing to stdout, print a human-readable error to stderr, and exit non-zero (FR-011)
- [X] T024 [US4] Wire `src/customer_support_fde/__init__.py`'s `main()` to invoke the `cli.py` entry point (depends on T023), matching the existing `customer-support-fde = "customer_support_fde:main"` script declared in `pyproject.toml`

**Checkpoint**: All four user stories independently functional; routing (including the clarifying-question path) is verifiable via tests and via the CLI

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final validation against quickstart.md and the constitution

- [X] T025 [P] Run `pytest tests/unit/test_router_agent.py tests/unit/test_clarify_intent.py tests/integration/test_router_trajectory.py -v` per `quickstart.md` and confirm all tests pass
- [X] T026 [P] Manually validate the `quickstart.md` CLI examples against a live model (requires `OPENROUTER_API_KEY` set per `.env.example`), including the ambiguous-input clarifying exchange, and confirm SC-005 (routing completes in well under 3 seconds, excluding time spent waiting on the customer's answer)
- [X] T027 Confirm `src/customer_support_fde/graph.py` and CLI invocation respect standard LangSmith tracing environment variables (`LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`, `LANGSMITH_PROJECT`) per Constitution Principle IV, with no custom logging layer added

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational completion. Builds the shared `router_agent` node and `build_graph()` — every later story builds on top of these
- **User Story 2 (Phase 4)**: Depends on User Story 1's `router_agent` implementation (T009) existing, since both stories share the single structured-output call; adds its own failing tests and a narrow prompt refinement on top
- **User Story 3 (Phase 5)**: Depends on User Story 1's `router_agent` (T009, for the `"unclear"` outcome) and `build_graph()` (T010, which it extends with a new node and edge); introduces the new `clarify_intent` module, independent of User Story 2
- **User Story 4 (Phase 6)**: Depends on User Story 1's `build_graph()` (T010) and `router_agent` (T009); its integration accuracy test (T021) exercises User Story 3's clarifying path too, so it is written and validated after Phase 5, though its own error-propagation and CLI tasks do not modify `clarify_intent.py`
- **Polish (Phase 7)**: Depends on all four user stories being complete

### Within Each User Story

- Tests MUST be written and FAIL before implementation tasks in that story
- Node/graph logic before CLI wiring
- Story's checkpoint reached before moving to the next priority

### Parallel Opportunities

- T002 can run in parallel with T001 (different files)
- T004 and T005 can run in parallel with each other (different files), after T003
- T007 and T008 can run in parallel (different test files)
- T011 and T012 can run in parallel (different test files)
- T014, T015, and T016 can run in parallel (three different files: `test_router_agent.py`, `test_clarify_intent.py`, `test_router_trajectory.py`)
- T020 and T021 can run in parallel (different files: T020 is a new test function in `test_router_agent.py`; T021 is in `test_router_trajectory.py`)
- T025 and T026 can run in parallel (independent validation activities)

---

## Parallel Example: User Story 3

```bash
# Launch all three User Story 3 test tasks together (three different files):
Task: "Write failing unit test in tests/unit/test_router_agent.py asserting router_agent classifies ambiguous/mixed-signal input as 'unclear' and keeps sentiment"
Task: "Write failing unit tests in tests/unit/test_clarify_intent.py for answer-mapping, sentiment carryover, and the re-ask-on-invalid-answer loop"
Task: "Write failing integration test in tests/integration/test_router_trajectory.py for the clarify_intent trajectory, resuming via Command(resume=...)"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — builds `SupportState`, placeholder nodes, `RouterDecision`, and the OpenRouter client)
3. Complete Phase 3: User Story 1 (order/support routing, no sentiment)
4. **STOP and VALIDATE**: `pytest tests/unit/test_router_agent.py tests/integration/test_router_trajectory.py -v` — order/support path green
5. Demo via CLI once Phase 6's `cli.py` exists, or via direct `build_graph()` invocation before that

### Incremental Delivery

1. Setup + Foundational → shared state/node scaffolding ready
2. Add User Story 1 → order/support routing works and is tested (MVP!)
3. Add User Story 2 → refund + sentiment routing works and is tested
4. Add User Story 3 → ambiguous/mixed-signal requests are resolved by directly asking the customer, never by a silent default
5. Add User Story 4 → error surfacing, CLI (including the clarifying exchange), and 90%-accuracy validation complete
6. Polish → full quickstart.md validation checklist satisfied

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Because User Stories 1 and 2 share one LLM call (`router_agent`), User Story 2's "implementation" task is narrower (a prompt refinement) than a fully independent story would have — this reflects the design decision in `research.md` §2, not a shortcut
- `clarify_intent` is deliberately not named `clarify_agent` — it makes no LLM call and does no agentic work; it is fixed-question, deterministic control flow (`research.md` §7)
- Verify tests fail before implementing
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
</content>
