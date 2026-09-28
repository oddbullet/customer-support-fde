# Contract: `customer_support_fde.circuit_breaker` and `build_llm()`

## `build_llm()` (`nodes/common.py`)

| `FALLBACK_MODEL` | Returns |
|---|---|
| unset, `""`, or whitespace only | `ChatOpenAI` exactly as today (FR-009) |
| any other value | `CircuitBreakerLLM` (primary = `OPENROUTER_MODEL` or default, fallback = `FALLBACK_MODEL`) |

Both return values support `.invoke(input)`, `.bind_tools(tools)` and
`.with_structured_output(schema)`, and callers must not need to know which one they got.

## `is_retryable(exc: BaseException) -> bool`

| Exception | Result |
|---|---|
| `openai.APIConnectionError` / `openai.APITimeoutError` | `True` |
| `openai.APIStatusError` with status 408, 409, 429, 500, 502, 503, 504 | `True` |
| `openai.AuthenticationError` (401), `BadRequestError` (400), `NotFoundError` (404), `PermissionDeniedError` (403), `UnprocessableEntityError` (422) | `False` |
| `pydantic.ValidationError`, `ValueError`, `RuntimeError`, any other exception | `False` |

## `CircuitBreakerLLM.invoke(input, config=None, **kwargs)`

| Effective state | Primary outcome | Fallback outcome | Result | State after |
|---|---|---|---|---|
| closed | ok | not called | primary reply | closed |
| closed | retryable error | ok | fallback reply | open |
| closed | retryable error | retryable error | raises `ModelUnavailableError` | open |
| closed | retryable error | non-retryable error | re-raises fallback error | open |
| closed | non-retryable error | not called | re-raises primary error | closed |
| open (in cool-down) | not called | ok | fallback reply | open |
| open (in cool-down) | not called | retryable error | raises `ModelUnavailableError` | open |
| half_open | probe ok | not called | probe reply | closed |
| half_open | probe retryable error | ok | fallback reply | open (cool-down restarted) |
| half_open | probe non-retryable error | not called | re-raises probe error | open (unchanged) |

**Invariants**:
- **At most one model switch:** the fallback is called at most once per `invoke`, and never
  retried by the wrapper beyond the client's own 3 retries.
- **Unchanged request:** the input passed to the fallback is the same object passed to the
  primary.
- **Traced:** every `invoke` emits exactly one `llm.circuit_breaker` span with the attributes in
  [research.md §8](../research.md).

## `reset_circuit() -> None`

Returns the shared breaker to `closed` with `opened_at = None`, and restores the default clock.
Intended for tests.
