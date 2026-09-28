# Data Model: LLM Circuit Breaker with Fallback Model

No database or `SupportState` changes. All state is in memory, for the life of the process.

## CircuitBreaker (module-level singleton in `circuit_breaker.py`)

| Field | Type | Meaning |
|---|---|---|
| `state` | `"closed" \| "open"` | Stored state. `half_open` is derived, not stored (see below). |
| `opened_at` | `float \| None` | `clock()` value when the circuit last opened; `None` while closed |
| `cooldown_seconds` | `float` | `CIRCUIT_COOLDOWN_SECONDS = 60` |
| `clock` | `Callable[[], float]` | Defaults to `time.monotonic`; injected in tests |

**Effective state** at request time:
- `closed`: `state == "closed"`
- `open`: `state == "open"` and `clock() - opened_at < cooldown_seconds`
- `half_open`: `state == "open"` and the cool-down has elapsed

### State transitions (per request)

```text
closed ──primary ok──────────────────────────▶ closed
closed ──primary retryable fail (after 1+3)──▶ open    (opened_at = now; request → fallback)
closed ──primary non-retryable fail──────────▶ closed  (error re-raised)

open   ──(within cool-down)──────────────────▶ open    (primary skipped; request → fallback)

half_open ──probe ok (1 attempt)─────────────▶ closed  (opened_at = None)
half_open ──probe retryable fail─────────────▶ open    (opened_at = now; request → fallback)
half_open ──probe non-retryable fail─────────▶ open    (opened_at unchanged; error re-raised)
```

The fallback's result never changes the circuit state. If the fallback fails:
- **Retryable failure:** `ModelUnavailableError`
- **Non-retryable failure:** re-raised unchanged

## CircuitBreakerLLM (wrapper returned by `build_llm()` when `FALLBACK_MODEL` is set)

| Field | Type | Meaning |
|---|---|---|
| `primary` | Runnable | `ChatOpenAI(model=OPENROUTER_MODEL, max_retries=3)`, after any bind/structured call |
| `probe` | Runnable | Same primary model with `max_retries=0`, after the same calls |
| `fallback` | Runnable | `ChatOpenAI(model=FALLBACK_MODEL, max_retries=3)`, after the same calls |
| `primary_model` / `fallback_model` | `str` | Model ids, for tracing |
| `breaker` | `CircuitBreaker` | The shared singleton |

**Rules**:
- `bind_tools(*args, **kwargs)` and `with_structured_output(*args, **kwargs)` return a new
  `CircuitBreakerLLM` with the call applied to all three runnables and the same `breaker`.

## ModelUnavailableError

`Exception` subclass raised when the fallback fails with a retryable error. It is chained
(`__cause__`) to the fallback's error. The CLI catches it to show the retry warning.

## Configuration

| Setting | Source | Default | Notes |
|---|---|---|---|
| `OPENROUTER_MODEL` | `.env` | `openai/gpt-4o-mini` | Unchanged |
| `FALLBACK_MODEL` | `.env` | unset | Unset or blank means the breaker is disabled (today's behavior) |
| `LLM_MAX_RETRIES` | constant | 3 | Unchanged; applies to primary and fallback |
| `CIRCUIT_COOLDOWN_SECONDS` | constant | 60 | Fixed per clarification |
