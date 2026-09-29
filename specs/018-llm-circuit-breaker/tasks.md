---

description: "Task list for the LLM circuit breaker with fallback model"
---

# Tasks: LLM Circuit Breaker with Fallback Model

**Input**: Design documents from `specs/018-llm-circuit-breaker/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: REQUIRED. Constitution Principle I (Test-First) and the project's TDD rule apply.

**TDD rhythm for every story**:
1. Write the tests.
2. Run them and confirm they fail (red) as a separate step.
3. Implement.
4. Run them and confirm they pass (green).

Every new test gets a one-line comment directly above its definition (above the outermost `@pytest.mark.parametrize`, if present). The comment states what it verifies and a category tag: `(base)`, `(edge)`, `(error)` or `(regression)`.

**Organization**: Tasks are grouped by user story so each story can be built and tested on its own.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)

## Shared test conventions (used by the tasks below)

- **Fake runnables**: In `tests/unit/test_circuit_breaker.py`, define a small `FakeRunnable` class with:
  - `invoke(input, config=None, **kwargs)`, which records `input` and then either returns a preset value or raises a preset exception;
  - `bind_tools(*a, **kw)` and `with_structured_output(*a, **kw)`, which each return a new `FakeRunnable` recording the call and sharing the outcome.
- **Fake clock**: a mutable holder, e.g. `clock = {"now": 0.0}` with `lambda: clock["now"]`.
- **Retryable error factories**:
  - `openai.APIConnectionError(request=httpx.Request("POST", "https://x"))`
  - `openai.InternalServerError("boom", response=httpx.Response(503, request=req), body=None)`
- **Non-retryable error factory**: `openai.AuthenticationError("bad key", response=httpx.Response(401, request=req), body=None)`
- **Isolation**: an autouse fixture in `tests/unit/test_circuit_breaker.py` calls `circuit_breaker.reset_circuit()` before and after each test. Do the same in `tests/integration/test_circuit_breaker_graph.py` and in the circuit-related tests in `tests/unit/test_common.py`.
- **Env isolation**: any test that builds a real model calls `monkeypatch.delenv("FALLBACK_MODEL", raising=False)` unless it is explicitly testing the fallback.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Configuration surface.

- [X] T001 Add `FALLBACK_MODEL=` to `.env.example` directly under `OPENROUTER_MODEL=`. Add a one-line comment above it: `# Optional model id used when the primary model fails after all retries (circuit breaker). Leave blank to disable.`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The error classification and exception type that every story depends on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T002 Write the `is_retryable` contract tests in `tests/unit/test_circuit_breaker.py`, one parametrized test built from the table in `contracts/circuit-breaker.md`.
  - **True**: `APIConnectionError`, `APITimeoutError`, and `APIStatusError`/subclasses with status 408, 409, 429, 500, 502, 503, 504.
  - **False**: status 400, 401, 403, 404, 422, plus `pydantic.ValidationError`, `ValueError`, `RuntimeError`.
  - Also add a `(base)` test that `ModelUnavailableError` is an `Exception` subclass and that `CIRCUIT_COOLDOWN_SECONDS == 60`.
- [X] T003 Run `uv run pytest tests/unit/test_circuit_breaker.py`. Confirm the new tests fail (red) because the `customer_support_fde.circuit_breaker` module does not exist yet.
- [X] T004 Create `src/customer_support_fde/circuit_breaker.py` with:
  - `CIRCUIT_COOLDOWN_SECONDS = 60`
  - `class ModelUnavailableError(Exception)`
  - `is_retryable(exc: BaseException) -> bool`. It returns True for `isinstance(exc, openai.APIConnectionError)` (which covers `APITimeoutError`), or for `isinstance(exc, openai.APIStatusError)` with `exc.status_code in (408, 409, 429)` or `exc.status_code >= 500`. Otherwise it returns False.
- [X] T005 Run `uv run pytest tests/unit/test_circuit_breaker.py`. Confirm green.

**Checkpoint**: Foundation ready. User story work can begin.

---

## Phase 3: User Story 1 - Conversation continues on the fallback model when the primary model fails (Priority: P1) 🎯 MVP

**Goal**:
- **Fallback**: when the primary model runs out of retries, the same request is answered by `FALLBACK_MODEL`.
- **Both fail**: the CLI shows the red warning and replays the failed step when the customer presses Enter, and the conversation survives.
- **No fallback set**: with `FALLBACK_MODEL` unset, nothing changes.

**Independent Test**: With a primary that always returns 503 and a working fallback, a customer message through the real graph gets a normal reply. With both failing, the CLI shows the warning, and pressing Enter after recovery continues the same conversation.

### Tests for User Story 1 (write first, confirm red) ⚠️

- [X] T006 [P] [US1] Add `CircuitBreakerLLM` **closed-state** tests to `tests/unit/test_circuit_breaker.py`, one test per row of the "closed" rows in `contracts/circuit-breaker.md`. Build each wrapper as `CircuitBreakerLLM(primary=FakeRunnable, probe=FakeRunnable, fallback=FakeRunnable, primary_model="p", fallback_model="f", breaker=circuit_breaker.CircuitBreaker(clock=fake_clock))`.
  - (a) `(base)` The primary succeeds, the result is returned, the fallback is not called, and `breaker.effective_state() == "closed"`.
  - (b) `(base)` The primary raises a retryable error, the fallback's result is returned, the fallback received the **same input object** (`is`), and the state is now `"open"`.
  - (c) `(error)` Both models raise retryable errors. `ModelUnavailableError` is raised with `__cause__` being the fallback's error, and the state is `"open"`.
  - (d) `(error)` The primary raises a retryable error and the fallback raises `AuthenticationError`. The `AuthenticationError` is re-raised unchanged.
  - (e) `(error)` The primary raises `AuthenticationError`. It is re-raised, the fallback is not called, and the state stays `"closed"`.
  - (f) `(base)` `bind_tools(["t"])` and `with_structured_output(Schema)` each return a new `CircuitBreakerLLM`. All three inner runnables received the same call, and the new wrapper shares the **same** `breaker` object.
- [X] T007 [P] [US1] Add `build_llm` selection tests to `tests/unit/test_common.py`.
  - `(regression)` With `FALLBACK_MODEL` unset, `""`, or `"   "` (parametrized), `common.build_llm()` returns a `ChatOpenAI` instance.
  - `(base)` With `FALLBACK_MODEL="fallback/model"` and `OPENROUTER_MODEL="primary/model"`, it returns a `CircuitBreakerLLM` where:
    - `primary.model_name == "primary/model"` and `primary.max_retries == 3`;
    - `probe.model_name == "primary/model"` and `probe.max_retries == 0`;
    - `fallback.model_name == "fallback/model"` and `fallback.max_retries == 3`;
    - `breaker is circuit_breaker._BREAKER` (the shared singleton).
  - `(edge)` With `OPENROUTER_MODEL` unset, the primary uses `DEFAULT_MODEL`.
  - Add `monkeypatch.delenv("FALLBACK_MODEL", raising=False)` to the existing `test_build_llm_retries_failing_api_calls_before_giving_up`, so it keeps guarding FR-009.
- [X] T008 [P] [US1] Add CLI tests to `tests/unit/test_interactive.py` following `contracts/cli-model-unavailable.md`. Reuse the existing fake-graph/fake-stdin patterns in that file.
  - (a) `(base)` The first `graph.invoke` raises `ModelUnavailableError`. `print_warning` is called with `TOOL_LIMIT_WARNING`, then "Press Enter to try again." is printed, one stdin line is read, and the next call is `graph.invoke(None, config)` with the **same** `thread_id`. Its result is returned by `_run_conversation`.
  - (b) `(edge)` `ModelUnavailableError` twice in a row. The warning is shown twice and `invoke(None, config)` is called twice.
  - (c) `(base)` The error happens after an interrupt resume (`Command(resume=...)` raises). Recovery via `invoke(None, config)` then yields another `__interrupt__`, which is printed and answered normally.
  - (d) `(regression)` A plain `RuntimeError` from `graph.invoke` is **not** caught by `_run_conversation`. It propagates, and `run_interactive` still prints `Error: ...`.
  - (e) `(error)` The raw `ModelUnavailableError` message text never appears in the output.
- [X] T009 [P] [US1] Create `tests/integration/test_circuit_breaker_graph.py`.
  - **Environment**: set `OPENROUTER_API_KEY="test-key"`, `OPENROUTER_MODEL="primary/model"`, `FALLBACK_MODEL="fallback/model"`. Patch `openai._base_client.time.sleep` to a no-op. Use an autouse `reset_circuit()` fixture.
  - **Fake transport**: patch `openai._base_client.SyncHttpxClientWrapper.send` (the class used in `tests/unit/test_common.py` via `type(llm.root_client._client)`) with a function that reads `json.loads(request.content)["model"]` and records each call's model id in a list.
    - For a failing model, it returns `httpx.Response(503, json={"error": {"message": "down"}}, request=request)`.
    - Otherwise it returns a valid chat-completion JSON (`id`, `object: "chat.completion"`, `created`, `model`, `choices[0].message` with `role: "assistant"`, `finish_reason: "stop"`, `usage`).
    - The `content` is `'{"destination": "order_support", "sentiment": "neutral"}'` when the request body contains `response_format`, and `"What would you like to order?"` otherwise.
    - Keep a mutable `failing = {"primary/model"}` set so tests can change which models fail.
  - **Graph**: `build_graph(checkpointer=MemorySaver())` with a fixed `thread_id` config.
  - **Tests**:
    - (a) `(base)` With only the primary failing, `graph.invoke(initial_state("Do you have dumplings?"), config)` returns an `__interrupt__` whose value is the account `PRIMARY_MENU`. This proves the router's structured output came from the fallback. Recorded model ids show 4 primary attempts, then fallback.
    - (b) `(base)` Continue (a) with `Command(resume="2")` (continue without an account). The result is an `__interrupt__` whose value is `"What would you like to order?"`, from call_model via the fallback.
    - (c) `(error)` With `failing = {"primary/model", "fallback/model"}`, `graph.invoke(initial_state(...), config)` raises `ModelUnavailableError`. Then set `failing = set()` and call `graph.invoke(None, config)`, which returns the `PRIMARY_MENU` interrupt. This proves the replay re-runs the failed router step.
    - (d) `(regression)` Reach call_model as in (b). Make both models fail, and `Command(resume=...)` of the next customer message raises `ModelUnavailableError`. Clear the failures and call `graph.invoke(None, config)`, which returns the next reply. `graph.get_state(config).values["messages"]` contains that customer message exactly **once**.
- [X] T010 [US1] Run `uv run pytest tests/unit/test_circuit_breaker.py tests/unit/test_common.py tests/unit/test_interactive.py tests/integration/test_circuit_breaker_graph.py`. Confirm the new US1 tests fail (red) and the previously passing tests still pass.

### Implementation for User Story 1

- [X] T011 [US1] In `src/customer_support_fde/circuit_breaker.py`, add `class CircuitBreaker`.
  - **Constructor**: `__init__(self, cooldown_seconds: float = CIRCUIT_COOLDOWN_SECONDS, clock: Callable[[], float] = time.monotonic)`.
  - **Fields**: `state: Literal["closed", "open"] = "closed"` and `opened_at: float | None = None`.
  - **Methods**:
    - `effective_state()`, which returns `"closed" | "open" | "half_open"`. Half-open means `state == "open"` and `clock() - opened_at >= cooldown_seconds`.
    - `record_open()`, which sets `state = "open"` and `opened_at = clock()`.
    - `record_close()`, which sets `state = "closed"` and `opened_at = None`.
  - **Singleton**: a module-level `_BREAKER = CircuitBreaker()`, plus `reset_circuit()`, which resets `_BREAKER` to closed with `opened_at = None` and `clock = time.monotonic`.
- [X] T012 [US1] In `src/customer_support_fde/circuit_breaker.py`, add `class CircuitBreakerLLM`.
  - **Constructor**: `__init__(self, primary, probe, fallback, primary_model: str, fallback_model: str, breaker: CircuitBreaker)`.
  - **Pass-through methods**: `bind_tools(*args, **kwargs)` and `with_structured_output(*args, **kwargs)` return `CircuitBreakerLLM` with the call applied to `primary`, `probe` and `fallback`, the same model ids, and the same `breaker`.
  - **`invoke(input, config=None, **kwargs)`, closed-state path only for now**:
    1. Try `primary.invoke(input, config, **kwargs)`.
    2. On a non-retryable error, re-raise it.
    3. On a retryable error, call `breaker.record_open()`, then call `fallback.invoke(input, config, **kwargs)`.
    4. If the fallback raises a retryable error, `raise ModelUnavailableError("primary and fallback models unavailable") from exc`. If it raises a non-retryable error, re-raise it.
- [X] T013 [US1] In `src/customer_support_fde/nodes/common.py`, update `build_llm()`.
  - **Read the setting**: `fallback = os.environ.get("FALLBACK_MODEL", "").strip()`.
  - **Empty**: return the existing `ChatOpenAI(...)`, unchanged.
  - **Set**: build three `ChatOpenAI` clients with the same `base_url` and `api_key`:
    - primary: `model=OPENROUTER_MODEL or DEFAULT_MODEL`, `max_retries=LLM_MAX_RETRIES`;
    - probe: same model, `max_retries=0`;
    - fallback: `model=fallback`, `max_retries=LLM_MAX_RETRIES`.
  - **Return**: `CircuitBreakerLLM(..., breaker=circuit_breaker._BREAKER)`.
  - Update the `condense_messages` `llm` parameter type hint to `ChatOpenAI | CircuitBreakerLLM`.
- [X] T014 [US1] In `src/customer_support_fde/interactive.py`, catch `ModelUnavailableError` inside `_run_conversation`. Put the handling in a helper `_invoke_with_retry(console, graph, state_or_command, config)` that wraps `_invoke_with_status` and is used for both the initial invoke and each resume:
  1. `print_warning(TOOL_LIMIT_WARNING, console)`
  2. `console.print("Press Enter to try again.")`
  3. `sys.stdin.readline()`
  4. `state_or_command = None`, then loop.

  Do not catch any other exception type.
- [X] T015 [US1] Run the T010 command. Confirm all US1 tests are green, then run `uv run pytest` and confirm the full suite passes.

**Checkpoint**: MVP. The fallback works per request, the CLI survives when both models fail, and nothing changes without `FALLBACK_MODEL`. The circuit records "open", but nothing skips the primary yet.

---

## Phase 4: User Story 2 - Circuit stays open so later requests skip the failing primary model (Priority: P2)

**Goal**:
- **Open**: within 60 seconds of the circuit opening, requests go straight to the fallback.
- **Probe**: after 60 seconds, one single-attempt probe of the primary closes the circuit or reopens it.

**Independent Test**: With a fake clock, trip the circuit, then invoke again at +30 s. The primary and probe get zero calls. At +61 s with a healthy primary, the probe answers and the circuit closes.

### Tests for User Story 2 (write first, confirm red) ⚠️

- [X] T016 [P] [US2] Add open and half-open tests to `tests/unit/test_circuit_breaker.py`, one per remaining row of `contracts/circuit-breaker.md`, using the fake clock.
  - (a) `(base)` Open at t=0, invoke at t=30. The primary and probe are not called, the fallback answers, and the state stays `"open"`.
  - (b) `(error)` Open, the fallback raises a retryable error. `ModelUnavailableError` is raised and the state stays `"open"` with `opened_at` unchanged.
  - (c) `(base)` Open at t=0, invoke at t=60 (the boundary, `>=`). The **probe** is called once, the primary is not called, the probe's result is returned, and the state is `"closed"`.
  - (d) `(error)` Half-open, the probe raises a retryable error. The fallback answers, the state is `"open"` and `opened_at == 60` (the cool-down restarted).
  - (e) `(edge)` Half-open, the probe raises `AuthenticationError`. It is re-raised, the fallback is not called, and the state is `"open"` with `opened_at` unchanged.
  - (f) `(edge)` Open at t=0, invoke at t=59.9. Still open, and the probe is not called.
  - (g) `(base)` `reset_circuit()` returns `_BREAKER` to `"closed"`.
- [X] T017 [P] [US2] Add test (e) to `tests/integration/test_circuit_breaker_graph.py`. `(base)` Run the flow of test (a). Clear the recorded model ids, then send the next customer message (`Command(resume="2")`) while the primary still fails. The recorded model ids for that step contain **no** `"primary/model"` entries (SC-002).
- [X] T018 [US2] Run `uv run pytest tests/unit/test_circuit_breaker.py tests/integration/test_circuit_breaker_graph.py`. Confirm the new US2 tests fail (red).

### Implementation for User Story 2

- [X] T019 [US2] Extend `CircuitBreakerLLM.invoke` in `src/customer_support_fde/circuit_breaker.py` to branch on `breaker.effective_state()`, following the state table in `data-model.md`.
  - **`"open"`**: skip the primary and go straight to the fallback path, with no state change.
  - **`"half_open"`**: call `probe.invoke(...)`.
    - On success: `breaker.record_close()` and return.
    - On a retryable error: `breaker.record_open()`, then the fallback path.
    - On a non-retryable error: re-raise with the state unchanged.
  - **`"closed"`**: unchanged from T012.
  - Factor the fallback path (the fallback call plus the `ModelUnavailableError` mapping) into one private method used by all three branches.
- [X] T020 [US2] Run the T018 command, then `uv run pytest`. Confirm green.

**Checkpoint**: US1 and US2 both work. During an outage, customers pay the retry delay at most once per 60-second window.

---

## Phase 5: User Story 3 - Operators can see when the fallback was used (Priority: P3)

**Goal**: Every wrapped model request emits one `llm.circuit_breaker` span recording the circuit state, fallback use, the answering model and the primary error (FR-010, SC-005).

**Independent Test**: With an in-memory span exporter, trigger a fallback. The finished span has `circuit.fallback_used=True`, `circuit.model_answered="f"`, `circuit.state_before="closed"`, `circuit.state_after="open"`, and a `circuit_opened` event.

### Tests for User Story 3 (write first, confirm red) ⚠️

- [X] T021 [P] [US3] Add span tests to `tests/unit/test_circuit_breaker.py`.
  - **Fixture setup**: build `TracerProvider()` with `SimpleSpanProcessor(InMemorySpanExporter())` (from `opentelemetry.sdk.trace` / `opentelemetry.sdk.trace.export` / `opentelemetry.sdk.trace.export.in_memory_span_exporter`). Monkeypatch `circuit_breaker._get_tracer` to return `provider.get_tracer("test")`, which avoids setting the global provider.
  - (a) `(base)` The primary succeeds. There is exactly one span named `llm.circuit_breaker` with:
    - `circuit.state_before="closed"` and `circuit.state_after="closed"`;
    - `circuit.fallback_used=False` and `circuit.model_answered="p"`;
    - no `circuit.primary_error`.
  - (b) `(base)` Fallback after a primary failure. The span has `fallback_used=True`, `model_answered="f"`, `state_before="closed"`, `state_after="open"`, a `circuit.primary_error` containing `"InternalServerError"`, and one event named `circuit_opened`.
  - (c) `(base)` A half-open probe succeeds. The span has `state_before="half_open"`, `state_after="closed"`, `model_answered="p"` and an event `circuit_closed`.
  - (d) `(error)` Both models fail. The span has `fallback_used=True`, **no** `circuit.model_answered` attribute, `state_after="open"`, and the span status is ERROR.
  - (e) `(edge)` Open state. The span has `state_before="open"`, `fallback_used=True` and no `circuit.primary_error`.
- [X] T022 [US3] Run `uv run pytest tests/unit/test_circuit_breaker.py`. Confirm the new US3 tests fail (red).

### Implementation for User Story 3

- [X] T023 [US3] In `src/customer_support_fde/circuit_breaker.py`, add `_get_tracer()`, which returns `opentelemetry.trace.get_tracer(__name__)`.
  - **Span**: wrap the body of `CircuitBreakerLLM.invoke` in `with _get_tracer().start_as_current_span("llm.circuit_breaker") as span:`.
  - **Attributes**:
    - `circuit.state_before` at entry and `circuit.state_after` before returning or raising (`breaker.effective_state()`);
    - `circuit.fallback_used` (bool);
    - `circuit.model_answered` (`primary_model` or `fallback_model`), only when a model returned;
    - `circuit.primary_error` (`f"{type(exc).__name__}: {exc}"`) when the primary or probe failed with a retryable error.
  - **Events**: `span.add_event("circuit_opened")` in `record_open` paths and `span.add_event("circuit_closed")` on probe success.
  - **Errors**: on exception, `span.set_status(StatusCode.ERROR)` and re-raise. The `start_as_current_span` default `record_exception` is fine.
  - **No new dependency**: `opentelemetry-api` and `opentelemetry-sdk` come from `arize-phoenix-otel`. Do not edit `pyproject.toml`.
- [X] T024 [US3] Run `uv run pytest tests/unit/test_circuit_breaker.py`, then `uv run pytest`. Confirm green.

**Checkpoint**: All user stories work on their own.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T025 [P] Update `CLAUDE.md`.
  - **Project Overview bullets**: add "LLM circuit breaker: after the primary model exhausts its retries, requests fall back to `FALLBACK_MODEL` for a 60-second cool-down, then a single-attempt probe tries the primary again; if both models fail, the CLI shows a retry warning and replays the failed step on Enter."
  - **Architecture**: add a note under `call_model` / `refund_agent` that every model call goes through `build_llm()` in `nodes/common.py`, which wraps it in `circuit_breaker.CircuitBreakerLLM` when `FALLBACK_MODEL` is set.
- [X] T026 [P] Check that every new test in `tests/unit/test_circuit_breaker.py`, `tests/unit/test_common.py`, `tests/unit/test_interactive.py` and `tests/integration/test_circuit_breaker_graph.py` has its one-line category comment directly above its definition (Constitution I). Add any that are missing.
- [X] T027 Run `uv run pytest` (the full unit and integration suite). Confirm all tests pass with `FALLBACK_MODEL` unset in the environment (SC-004).
- [X] T028 Run the manual checks in `quickstart.md` sections 3–4 (both models down, then breaker disabled) and record the outcome in the PR description.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: T002 → T003 → T004 → T005. Blocks all stories.
- **US1 (Phase 3)**: depends on Phase 2.
- **US2 (Phase 4)**: depends on US1's `CircuitBreaker` and `CircuitBreakerLLM` (T011–T012). It extends the same `invoke`.
- **US3 (Phase 5)**: depends on US1. It can run before or after US2; if after US2, test (c) and test (e) apply, otherwise mark them `xfail` until US2 lands.
- **Polish (Phase 6)**: after the desired stories are done.

### Within Each User Story

1. Tests are written first.
2. A separate run confirms red.
3. Implement.
4. A separate run confirms green.
5. Run the full suite before moving on.

### Parallel Opportunities

- T006, T007, T008 and T009 touch four different test files and can be written in parallel.
- T016 and T017 touch different files and can run in parallel.
- T025 and T026 can run in parallel.
- Implementation tasks within a story are sequential. T011, T012, T019 and T023 all edit `circuit_breaker.py`. T013 and T014 edit different files but depend on T012.

---

## Parallel Example: User Story 1

```text
Task: "T006 CircuitBreakerLLM closed-state tests in tests/unit/test_circuit_breaker.py"
Task: "T007 build_llm selection tests in tests/unit/test_common.py"
Task: "T008 ModelUnavailableError CLI retry tests in tests/unit/test_interactive.py"
Task: "T009 Graph-level fallback and replay tests in tests/integration/test_circuit_breaker_graph.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1, then Phase 2.
2. Phase 3 (US1): the fallback per request, the CLI retry, and no change when the breaker is disabled.
3. **STOP and VALIDATE**: `uv run pytest` plus quickstart §3–4.

### Incremental Delivery

1. US1: conversations survive a primary outage (MVP).
2. US2: no repeated retry delay while the circuit is open.
3. US3: fallback use is visible in Phoenix.

---

## Notes

- **Plan decisions the spec doesn't spell out**: the tasks follow them. 409 counts as retryable, the half-open probe is a single attempt (no retries), a non-retryable probe failure leaves the circuit open, and the warning-and-retry path applies only when `FALLBACK_MODEL` is set.
- **Separate steps**: never merge a "confirm red" run into an implementation task.
- **Commits**: commit after each checkpoint.
