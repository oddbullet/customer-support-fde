# Implementation Plan: Router Agent with Sentiment-Aware Refund Handoff

**Branch**: `001-router-agent` | **Date**: 2026-09-09 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-router-agent/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Build a LangGraph router agent that reads a customer's full request text, classifies it as an order/support matter, a refund/complaint matter, or — when neither is clear, including messages that mix both — `unclear`, and — only for the refund path — attaches a sentiment assessment (positive/neutral/negative), always produced during the same classification pass regardless of which destination is ultimately chosen. Requests classified `unclear` are routed to a deterministic (non-LLM) `clarify_intent` node that pauses the graph via LangGraph's `interrupt()`, directly asks the customer to choose one of three options (placing an order, asking a general question, or requesting a refund), re-asking on an unrecognized answer, and resolves to a final destination — forwarding the sentiment already computed by the router if that destination is refund. The classification (and, when applicable, sentiment) is written into shared LangGraph state and handed off via conditional edges to one of two placeholder nodes (`order_support_agent`, `refund_agent`) that will be built out in a future feature. Classification/sentiment inference is performed by an LLM reached through OpenRouter's OpenAI-compatible API (via `langchain-openai`'s `ChatOpenAI` pointed at OpenRouter); the clarification step performs no LLM call. Correctness is verified with `pytest` + `agentevals` graph-trajectory-match tests that assert the exact node path taken for representative order/support, refund, and ambiguous/mixed-signal inputs (the latter resuming a real interrupt via `Command(resume=...)`), and LangSmith tracing is enabled per the project constitution.

## Technical Context

**Language/Version**: Python 3.14 (per `pyproject.toml` `requires-python` and `.python-version`)

**Primary Dependencies**: `langgraph` (state graph + conditional routing, and — for the clarification step — the `interrupt()`/`Command(resume=...)` human-in-the-loop mechanism backed by `langgraph.checkpoint.memory.MemorySaver`), `langchain-openai` (`ChatOpenAI` client configured against OpenRouter's base URL, used with structured output for the classification+sentiment call), `langchain` (core message/runnable types), `agentevals` (graph-trajectory-match evaluators for routing-correctness tests), `pytest` (test runner); `langsmith` is already present transitively via `langchain` and satisfies Constitution Principle IV's tracing requirement. No new dependency is introduced for the clarification step — `MemorySaver` was already required for trajectory-test checkpointing and is now also used at runtime.

**Storage**: N/A — the feature is stateless; all data (query, sentiment, destination) lives only in in-memory LangGraph state for the duration of a single graph invocation. The `MemorySaver` checkpointer used to hold a graph run across an `interrupt()`/resume pause is RAM-only and scoped to the single CLI process invocation handling that request — nothing is persisted to disk or across process restarts.

**Testing**: `pytest`, with `agentevals.graph_trajectory.strict.graph_trajectory_strict_match` (trajectory extracted via `agentevals.graph_trajectory.utils.extract_langgraph_trajectory_from_thread`, which requires the graph to be compiled with a checkpointer such as `langgraph.checkpoint.memory.MemorySaver`) driving the agent trajectory tests, including ambiguous/mixed-signal cases whose expected trajectory includes `clarify_intent` and whose test resumes the paused graph via `graph.invoke(Command(resume=<choice>), config)`; unit tests cover the classification/sentiment parsing logic and the `clarify_intent` answer-mapping/re-ask logic with the LLM boundary mocked/faked so tests are deterministic and do not require live API calls.

**Target Platform**: Server-side Python library, invoked via a CLI entry point (per Constitution Principle II) — no OS-specific behavior.

**Project Type**: Single project — importable library module under `src/customer_support_fde/` with a CLI entry point (existing `customer-support-fde` script in `pyproject.toml`).

**Performance Goals**: Routing decision + handoff completes in under 3 seconds under normal conditions (SC-005); dominated by a single LLM call latency.

**Constraints**: English-only input (per Clarifications); sentiment MUST NOT be produced or forwarded for the order/support path (FR-004); full original query text MUST be forwarded unmodified (FR-005); router MUST surface (not swallow) failures from the classification/sentiment step (FR-011); LLM calls MUST go through OpenRouter's API (explicit user requirement); no persistent storage; ambiguous/mixed-signal requests MUST NOT be silently defaulted — they MUST trigger a direct clarifying question to the customer (FR-008, FR-009), re-asked on an unrecognized answer (FR-012), with no additional LLM call in that step; a refund resolved via the clarifying question MUST forward the sentiment already produced by the router's original analysis, never a separately elicited value (FR-013).

**Scale/Scope**: One router node, one deterministic (non-LLM) clarification node, two conditional edges (`router_agent` → 3-way; `clarify_intent` → 2-way), two placeholder downstream nodes (`order_support_agent`, `refund_agent`); one LLM call per request (never repeated for the same request, even when clarification is needed); the only looping behavior in this feature is `clarify_intent` re-presenting its fixed question until it receives a recognized answer.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Test-First (NON-NEGOTIABLE)**: PASS (planned) — Phase 2 tasks will write failing unit tests (classification/sentiment logic) and failing trajectory tests (`agentevals` graph-trajectory-match) before any node/graph implementation exists, per red-green-refactor.
- **II. Library-First & CLI Interface**: PASS (planned) — router logic, state schema, and graph construction live as plain importable modules under `src/customer_support_fde/`, with no framework-specific entry-point coupling. The existing `customer-support-fde` CLI script is extended to accept a query (arg or stdin) and print the routing decision as JSON (`--json`) or human-readable text to stdout, with errors to stderr.
- **III. Simplicity (YAGNI)**: PASS (planned) — one router node with a single structured-output LLM call handles both classification and sentiment; sentiment is stripped from state at the router node itself when the final destination is order/support (plain code, no second LLM call, no extra "sentiment node"). The clarification step is the one addition beyond the original two-node/one-edge design, and it stays minimal: `clarify_intent` is plain Python control flow (fixed question, `interrupt()`/resume, deterministic answer mapping) with no LLM call and no new dependency — `MemorySaver` was already required for trajectory-test checkpointing.
- **IV. Observability & Versioning**: PASS (planned) — the graph is invoked with LangSmith tracing enabled (standard `langchain`/`langgraph` env-var-based tracing, no custom logging layer); CLI errors additionally go to stderr for immediate operator feedback per the constitution's allowance. No breaking changes to existing code (new module, package remains at 0.1.0 pending a minor bump when merged).

No violations requiring justification — Complexity Tracking table omitted.

**Post-Phase-1 re-check**: Confirmed against the finished design (`data-model.md`, `contracts/support-state.md`, `contracts/cli-route.md`). No new dependencies. `SupportState` stays a 3-field `TypedDict` (`destination`'s literal grows to include the transient `"unclear"` value, never a new field). One node was added beyond the original two required placeholders — `clarify_intent` — and it is deliberately not LLM-backed, keeping the single-LLM-call-per-request property intact even on the clarification path. The CLI contract satisfies Principle II without a new CLI framework; the interrupt/resume exchange is handled within the same `main()` process invocation. All four gates still PASS.

## Project Structure

### Documentation (this feature)

```text
specs/001-router-agent/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   ├── support-state.md
│   └── cli-route.md
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/customer_support_fde/
├── __init__.py            # main() CLI entry point (existing; extended to wire up the CLI command)
├── cli.py                 # argument/stdin parsing, invokes the graph, handles the interrupt/resume clarifying exchange over stdin/stdout, prints JSON or human-readable output
├── state.py                # SupportState TypedDict shared across graph nodes (the Handoff Package contract)
├── router_agent.py        # OpenRouter-backed ChatOpenAI client setup, structured-output classification+sentiment call, router node function
├── clarify_intent.py       # clarify_intent() node: no LLM call — presents the fixed three-choice question via interrupt(), re-asks on an unrecognized answer, maps the answer to a final destination and forwards the router's original sentiment when that destination is refund
├── downstream_agents.py    # order_support_agent() and refund_agent() placeholder node functions
└── graph.py                # build_graph(): StateGraph wiring router_agent -> conditional_edge -> {order_support_agent, refund_agent, clarify_intent}, clarify_intent -> conditional_edge -> {order_support_agent, refund_agent}

tests/
├── unit/
│   ├── test_router_agent.py       # classification/sentiment parsing + state-shaping logic, LLM boundary faked
│   └── test_clarify_intent.py     # answer-mapping + re-ask-on-invalid-answer logic, sentiment carryover, interrupt() boundary faked
└── integration/
    └── test_router_trajectory.py  # agentevals graph-trajectory-match tests over build_graph() for representative order/support, refund, and ambiguous/mixed-signal (via Command(resume=...)) inputs
```

**Structure Decision**: Single project (Option 1). This feature adds six small modules under the existing `src/customer_support_fde/` package (no new top-level project) and three test modules under `tests/unit/` and `tests/integration/`, matching Constitution Principle II's library-first layout and this repo's existing single-package structure (no `backend/`/`frontend/` split applies). `clarify_intent` is a separate module from `router_agent` specifically because it has no LLM dependency — keeping it out of `router_agent.py` keeps that module's OpenRouter/`ChatOpenAI` concerns and the deterministic control-flow concerns from mixing.

## Complexity Tracking

*No Constitution Check violations — table intentionally omitted.*
