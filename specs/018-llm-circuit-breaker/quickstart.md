# Quickstart: Validating the LLM Circuit Breaker

## Prerequisites

- Database initialized: `uv run start --init-db`
- `.env` has `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` set

## 1. Automated tests

```
uv run pytest tests/unit/test_circuit_breaker.py tests/unit/test_common.py tests/unit/test_interactive.py
uv run pytest tests/integration/test_circuit_breaker_graph.py
uv run pytest
```

**Expected**:
- **Tests pass:** all tests pass, including the existing suite unchanged (SC-004).
- **Rules covered:** the breaker's rules come from the tables in
  [contracts/circuit-breaker.md](contracts/circuit-breaker.md).
- **CLI covered:** the retry path comes from
  [contracts/cli-model-unavailable.md](contracts/cli-model-unavailable.md).

## 2. Manual: primary down, fallback works (User Story 1)

An outage of only the primary model can't be reproduced reliably against the live OpenRouter
API, because both models share one host. It is validated by
`tests/integration/test_circuit_breaker_graph.py`. That test fakes the HTTP transport so requests
for the primary model id fail with 503 and requests for the fallback model id succeed, then runs
the real graph.

**Expected**: the customer gets a normal reply that doesn't mention the fallback.

**Negative check (FR-007)**:
1. Set `OPENROUTER_MODEL=does-not-exist/model` and `FALLBACK_MODEL=openai/gpt-4o-mini`.
2. Run `uv run start`.

**Expected**: the invalid model id is a non-retryable 400/404, so there is **no** fallback. You
see today's `Error: ...` output.

## 3. Manual: both models down (clarification Q3)

1. Disconnect from the network (or set `HTTPS_PROXY=http://127.0.0.1:9`) with `FALLBACK_MODEL`
   set.
2. Run `uv run start`, add an item to the cart, then send another message.

**Expected**:
- **Warning:** after the retry delays, the red "Sorry, our system is having some issues right now.
  Please try again later." appears, followed by "Press Enter to try again."
- **Recovery:** reconnect and press Enter. The assistant answers the message you already sent,
  and the cart still holds the earlier item.

## 4. Manual: breaker disabled (FR-009)

1. Remove `FALLBACK_MODEL` from `.env`.
2. Repeat step 3.

**Expected**: today's behavior. You see the bold red `Error: ...` and a new conversation starts.

## 5. Tracing (User Story 3)

1. Set `PHOENIX_COLLECTOR_ENDPOINT`.
2. Repeat step 2 (via the integration test with tracing enabled) or step 3.

**Expected**:
- **Span:** each model request has an `llm.circuit_breaker` span with
  `circuit.state_before`/`circuit.state_after`, `circuit.fallback_used` and
  `circuit.model_answered`.
- **Events:** state changes show `circuit_opened` / `circuit_closed` events.
