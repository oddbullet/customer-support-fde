# Implementation Plan: LLM Circuit Breaker with Fallback Model

**Branch**: `circuit-breaker` | **Date**: 2026-09-28 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/018-llm-circuit-breaker/spec.md`

## Summary

When the primary OpenRouter model fails a request after its 3 built-in retries, requests switch
to the model named in `FALLBACK_MODEL`.

**The circuit**:
- **Opening:** the circuit opens on that failed request.
- **While open:** for 60 seconds every model request skips the primary.
- **Probing:** after the cool-down, one single-attempt probe of the primary decides whether the
  circuit closes or reopens.

**How it's built**:
- **Where:** everything is wrapped in `build_llm()`, which every agent already uses, so no node
  changes.
- **The wrapper:** when `FALLBACK_MODEL` is set, `build_llm()` returns a small
  `CircuitBreakerLLM` wrapper. It supports the three methods the nodes use (`invoke`,
  `bind_tools`, `with_structured_output`) and shares one in-memory circuit per process.
- **Breaker disabled:** when `FALLBACK_MODEL` is unset, `build_llm()` returns the same
  `ChatOpenAI` it does today.

**When both models fail**: the wrapper raises `ModelUnavailableError`. The interactive CLI catches
it, shows the existing red "please try again later" warning, waits for Enter, and replays the
failed step from the LangGraph checkpoint. The conversation and its cart, account and refund
progress survive.

**Tracing**: an OpenTelemetry span per request records circuit state, fallback use and the model
that answered.

## Technical Context

**Language/Version**: Python 3.14

**Primary Dependencies**:
- `langchain-openai` 1.6 / `langchain-core` 1.6 (existing)
- `openai` 3.11 (existing; source of the retryable exception types)
- LangGraph `MemorySaver` (existing; used for the retry replay)
- `opentelemetry-api` (already installed as a required dependency of `arize-phoenix-otel`)
- No new dependencies.

**Storage**: N/A. The circuit state is process memory only, with no DB or `SupportState` changes.

**Testing**:
- pytest with a fake injectable clock and fake runnables for the breaker.
- An integration test with a faked HTTP transport (the same pattern as
  `tests/unit/test_common.py`) that routes by model id through the real graph.
- An OpenTelemetry in-memory span exporter for the tracing assertions.

**Target Platform**: Local CLI (Windows/macOS/Linux)

**Project Type**: Single-project Python library with a CLI

**Performance Goals**:
- **While the circuit is open:** zero primary attempts (SC-002).
- **Half-open probe:** costs at most one primary attempt, with no retry backoff.

**Constraints**:
- **Unchanged without a fallback:** behavior with `FALLBACK_MODEL` unset must match today's
  exactly (FR-009, SC-004).
- **Invisible to customers:** customers never see the switch or raw errors (FR-011, FR-008).
- **No printing from nodes:** nodes run under the "Thinking..." spinner.

**Scale/Scope**:
- **Code:** one new module (`circuit_breaker.py`) plus edits to `nodes/common.py`,
  `interactive.py`, `.env.example` and `CLAUDE.md`.
- **Tests:** about 4 new test groups.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Assessment | Status |
|-----------|------------|--------|
| I. Test-First | These tests are written and seen failing before any implementation: the `is_retryable` table, the breaker state table (contracts/circuit-breaker.md), the `build_llm` selection, the wrapper's `bind_tools`/`with_structured_output` pass-through, the CLI retry path, graph-level fallback, the replay-after-failure integration test, and span attributes. Each test gets a one-line category comment (`(base)`/`(edge)`/`(error)`/`(regression)`). The existing `test_build_llm_retries_failing_api_calls_before_giving_up` stays as the FR-009 regression guard. | PASS |
| II. Library-First & CLI | The breaker is its own single-purpose importable module, `src/customer_support_fde/circuit_breaker.py`. The CLI change stays in `interactive.py`. No new CLI flags; configuration is via `.env`. | PASS |
| III. Simplicity | There is no generic resilience framework, and only the 3 methods callers actually use are wrapped. The cool-down is a constant (per clarification). There's no lock, since the CLI is single-threaded, and no new dependency. Two justified additions are noted under Complexity Tracking. | PASS (justified) |
| IV. Observability | Each request emits an `llm.circuit_breaker` span with state before and after, fallback use, the answering model, the primary error, and open/close events. Inner model calls stay auto-instrumented. This is a MINOR version bump (backward compatible, opt-in via `.env`). | PASS |

**Post-design re-check**: PASS. The design matches the gates above, with no new violations.

## Project Structure

### Documentation (this feature)

```text
specs/018-llm-circuit-breaker/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── circuit-breaker.md
│   └── cli-model-unavailable.md
└── tasks.md             # created by /speckit-tasks
```

### Source Code (repository root)

```text
src/customer_support_fde/
├── circuit_breaker.py           # NEW: CIRCUIT_COOLDOWN_SECONDS, is_retryable, CircuitBreaker,
│                                #      CircuitBreakerLLM, ModelUnavailableError, reset_circuit
├── interactive.py               # MODIFY: catch ModelUnavailableError in _run_conversation →
│                                #         warning + "Press Enter to try again" + invoke(None, config)
└── nodes/
    └── common.py                # MODIFY: build_llm() returns CircuitBreakerLLM when FALLBACK_MODEL set

.env.example                     # MODIFY: add FALLBACK_MODEL=
CLAUDE.md                        # MODIFY: document FALLBACK_MODEL and the breaker

tests/
├── unit/
│   ├── test_circuit_breaker.py  # NEW: is_retryable table, state table, probe, wrapper pass-through, spans
│   ├── test_common.py           # MODIFY: build_llm selection by FALLBACK_MODEL (unset/blank/set)
│   └── test_interactive.py      # MODIFY: ModelUnavailableError → warning, Enter, invoke(None) same thread
└── integration/
    └── test_circuit_breaker_graph.py  # NEW: real graph + faked transport: primary 503 → fallback answers;
                                       #      both fail → replay via invoke(None) keeps cart and messages
```

**Structure Decision**: Single project, following the existing layout. The breaker isn't a graph
node, so it lives at package level next to `tracing.py` rather than under `nodes/`.

## Complexity Tracking

| Addition | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Third client (`probe`, `max_retries=0`) | FR-006 says the half-open probe tries the primary **once** | Probing with the normal client repeats the full 4-attempt retry delay every 60 seconds during an outage, breaking SC-002 for those customers |
| `ModelUnavailableError` plus CLI replay loop | The clarification says the conversation stays open after both models fail | Letting the error reach the existing catch-all discards the conversation, which is the behavior the clarification rejected |
