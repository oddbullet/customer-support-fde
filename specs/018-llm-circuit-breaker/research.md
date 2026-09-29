# Research: LLM Circuit Breaker with Fallback Model

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## 1. Where to put the breaker

**Decision**: Wrap the model inside `build_llm()` (`nodes/common.py`). When `FALLBACK_MODEL` is
set, `build_llm()` returns a `CircuitBreakerLLM` instead of a bare `ChatOpenAI`. The circuit logic
lives in a new single-purpose module, `src/customer_support_fde/circuit_breaker.py`.

**Rationale**: Every model call in the project already goes through `build_llm()`: router, order
support (including history condensation), refund (including condensation), ticket generation and
memory generation. Wrapping at this one point covers FR-002 without touching any node.

**Alternatives considered**:
- *Wrapping in each node*: duplicates the logic in five places and makes it easy to miss one.
- *A graph-level retry/fallback node*: the graph cannot swap the model inside a node, and it
  would re-run whole nodes rather than single model requests.

## 2. Why not LangChain's `with_fallbacks()`

**Decision**: Write a small wrapper class instead of using `RunnableWithFallbacks`.

**Rationale**: `primary.with_fallbacks([fallback])` does per-request fallback and even passes
`bind_tools` / `with_structured_output` through to both models. But it keeps no state between
requests, so it cannot keep the circuit open (FR-005) or probe after the cool-down (FR-006).
Adding that state around it would still need a custom wrapper, so it adds nothing.

**Alternatives considered**: a `BaseChatModel` subclass that delegates `_generate`. Rejected
because `ChatOpenAI.with_structured_output` builds a provider-specific request (JSON-schema
`response_format`), which a generic subclass would lose.

## 3. Which interface the wrapper must copy

**Decision**: `CircuitBreakerLLM` exposes exactly the three methods the call sites use:

| Call site | Usage |
|---|---|
| `router_agent._build_llm` | `.with_structured_output(RouterDecision).invoke(...)` |
| `order_support_agent.call_model` | `.bind_tools(tools).invoke(...)`; plain `.invoke(...)` via `condense_messages` |
| `refund_agent.refund_agent` | same as order support |
| `ticket_gen_node` | `.with_structured_output(...).invoke(...)` |
| `memory_gen_node` | `.with_structured_output(...).invoke(...)` |

`bind_tools(...)` and `with_structured_output(...)` return a new `CircuitBreakerLLM` whose inner
runnables have had the same call applied, all sharing the same circuit. `invoke(...)` runs the
circuit logic.

**Rationale**: YAGNI (Principle III). Nothing calls `stream`, `batch` or async methods.

## 4. What counts as a retryable failure

**Decision**: A failure trips the circuit only if it is one the openai client retries:

- `openai.APIConnectionError` (includes `APITimeoutError`)
- `openai.APIStatusError` with status 408, 409, 429 or ≥ 500

Everything else, such as `AuthenticationError` (401), `BadRequestError` (400), `NotFoundError`
(404) and pydantic `ValidationError`, is re-raised unchanged and never touches the circuit
(FR-007).

**Rationale**: This mirrors `openai._base_client._should_retry` (openai 3.11.0, checked in this
repo's environment). By the time `ChatOpenAI` raises one of these, it has already made 1 + 3
attempts (`LLM_MAX_RETRIES = 3`), which is exactly FR-003's trigger.

**Known gap**: The client also obeys the server's `x-should-retry` and oversized `Retry-After`
headers. Those are ignored here, because the response headers aren't needed to classify by
exception type and status code. The worst case is a slightly early or late trip, which is
harmless.

## 5. The half-open probe

**Decision**: After the cool-down, the next request tries the primary through a separate
**probe** client with `max_retries=0`: one attempt. On success the circuit closes. On a
retryable failure it reopens (the cool-down restarts) and that same request is answered by the
fallback.

**Rationale**: FR-006 says the primary is "tried once". With the normal client, each probe during
an outage would repeat the full 4-attempt retry delay every 60 seconds. That defeats SC-002 for
one unlucky customer per minute.

**Alternatives considered**: probing through the normal primary client. Simpler (two clients
instead of three), but slow during outages, as above.

## 6. Circuit state and time

**Decision**:
- **One shared circuit:** a single module-level `CircuitBreaker` instance is shared by every
  wrapper. Circuit state is keyed to the running process (spec Assumptions), not to a model id.
- **Time source:** `time.monotonic`, injectable for tests.
- **Test reset:** a `reset_circuit()` helper for test isolation.
- **No lock:** the CLI runs one conversation at a time on one thread (YAGNI).

## 7. When both models fail: keep the conversation open

**Decision**:
- **In the wrapper:** when the fallback fails with a retryable error, raise
  `ModelUnavailableError` (chained `from` the fallback's error). A non-retryable fallback error is
  re-raised unchanged.
- **In the CLI:** `interactive._run_conversation` catches `ModelUnavailableError` around each
  graph invoke. It shows the existing red `TOOL_LIMIT_WARNING` text through `print_warning` and
  prints "Press Enter to try again." It then calls `graph.invoke(None, config)` on the **same
  thread** and keeps looping.

**Rationale**:
- **Replaying the failed step:** LangGraph with the `MemorySaver` checkpointer keeps the thread's
  last good checkpoint. Invoking with `None` re-runs only the step that failed, and the
  customer's message is already in the saved state. The conversation keeps its cart, account and
  refund details, and the message is not appended twice. Retyping it would add it twice.
- **What the customer sees:** "Press Enter" is how the spec's "retry their last message" works in
  practice. The spec wording is updated to match.
- **Other exceptions:** they still reach `run_interactive`'s catch-all, so FR-009 is unchanged.
- **Swallowing nodes:** `memory_gen_node`, `ticket_gen_node` and `condense_messages` already catch
  `Exception`, so they keep absorbing this error (FR-008).

**To verify with a test**: `invoke(None, config)` re-runs the failed node for both first-turn
failures (router) and failures after an interrupt resume (`call_model` / `refund_agent`).

## 8. Tracing

**Decision**: `CircuitBreakerLLM.invoke` opens an OpenTelemetry span, `llm.circuit_breaker`,
through `opentelemetry.trace.get_tracer(__name__)`. It sets these attributes:

- `circuit.state_before` / `circuit.state_after`: `closed` | `open` | `half_open`
- `circuit.model_answered`: the model id that produced the reply (absent when both models fail)
- `circuit.fallback_used`: bool
- `circuit.primary_error`: the exception class and message, when the primary failed

It adds span events `circuit_opened` / `circuit_closed` on state changes. Phoenix's
auto-instrumentation already records the inner `ChatOpenAI` calls as child spans.

**Rationale**: This satisfies FR-010 and Constitution IV. `opentelemetry-api` is already installed
as a required dependency of `arize-phoenix-otel`, so there is no new dependency. When tracing is
not configured, the API's no-op tracer makes this free.

## 9. Configuration

**Decision**:
- **New setting:** `FALLBACK_MODEL` in `.env.example`, under `OPENROUTER_MODEL`.
- **Unset or blank:** `build_llm()` returns exactly today's `ChatOpenAI` (FR-009).
- **Same model as the primary:** allowed.
- **Fixed values:** the cool-down (`CIRCUIT_COOLDOWN_SECONDS = 60`) is a constant. The fallback
  reuses `OPENROUTER_API_KEY`, the base URL and `LLM_MAX_RETRIES`.
