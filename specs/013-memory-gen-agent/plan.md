# Implementation Plan: Customer Memory Generation Agent

**Branch**: `013-memory-gen-agent` | **Date**: 2026-09-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/013-memory-gen-agent/spec.md`

## Summary

Add a `memory_gen_node` that runs immediately after the order support agent finishes (the
customer confirms their order), reads the full order conversation, and — only when the
conversation has an account number attached — extracts stated likes, dislikes, allergies, and
one-off per-order customization requests, merges them with the account's existing stored
preferences, and rewrites `accounts.preferences` in SQLite as one updated free-text passage that
clearly separates allergies (hard, safety-critical) from everything else (soft guidance for a
future feature to apply, per Clarifications). The node is wired as a second, independent branch
off `cart_summary` (alongside the existing branch to `ticket_gen_node`) so both run in the same
LangGraph step with no added latency to ticket delivery, and it is a pure side-effect node: it
never changes `SupportState`, so no new state fields, no join node, and no schema change are
needed — `accounts.preferences` already exists (`specs/012-account-identification-node`), and
`order_support_agent.py` already reads it back into context every turn, so writing better data
into that existing column is the entire scope of this feature.

## Technical Context

**Language/Version**: Python >=3.14 (`pyproject.toml`)

**Primary Dependencies**: LangGraph (>=1.2.11, graph wiring), `langchain-openai` `ChatOpenAI`
pointed at OpenRouter (extraction/merge call — same pattern as
`ticket_gen_node._extract_refund_issue` and `order_support_agent`'s condensation guard), Python
stdlib `sqlite3` (via `db.py`), `arize-phoenix-otel` + OpenInference LangChain instrumentation
(automatic tracing of the new LLM call, Principle IV — no new instrumentation code required)

**Storage**: SQLite (`customer_support.db`, `accounts.preferences` — existing column from
`specs/012-account-identification-node`; no schema change)

**Testing**: pytest — new `tests/unit/test_memory_gen_node.py`, extended `tests/unit/test_db.py`
for the new `db.update_account_preferences` function, and an extended order-support integration
trajectory test (Principle I: tests precede implementation)

**Target Platform**: Same as the rest of the project — a LangGraph agent run via the
`customer-support-fde` CLI (`cli.py`), cross-platform Python process

**Project Type**: Single project (existing `src/customer_support_fde/` library + CLI); this
feature adds one node module and one `db.py` function, no new project/package

**Performance Goals**: No numeric latency target (spec Assumptions/SC-003, matching the existing
precedent set by `specs/008-order-history-summarization`'s Assumptions) — the "no noticeable
delay to ticket delivery" requirement (FR-007) is met structurally, by running as an independent
graph branch rather than a step ticket generation waits on, not by making the LLM call itself fast

**Constraints**: MUST NOT run any extraction/DB-write logic when `state["account_number"]` is
`None` (FR-002); MUST fail silently on any extraction or write error, leaving prior stored
preferences untouched (FR-008); MUST NOT introduce a dependency edge that makes `ticket_gen_node`
wait on this node or vice versa (FR-007)

**Scale/Scope**: One new node module, one new `db.py` function, two new graph edges plus one new
node registration in `graph.py`; zero new `SupportState` fields; zero new CLI surface; zero
schema changes

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Test-First (NON-NEGOTIABLE)**: PASS (planned). `/speckit-tasks` + `/speckit-implement`
  must add failing tests in `tests/unit/test_memory_gen_node.py` and `tests/unit/test_db.py`
  before any implementation code, each with the required category comment
  (`(base)`/`(edge)`/`(error)`/`(regression)`), matching the existing convention visible in
  `tests/unit/test_account_identification_node.py`.
- **II. Library-First & CLI Interface**: PASS. `memory_gen_node` is a standalone, importable
  module under `src/customer_support_fde/nodes/`, single purpose (extraction + persistence for
  one account). It does not need its own CLI entry point — consistent with every other internal
  graph node in this project (`cart_summary_node`, `ticket_gen_node`, `account_identification_node`
  have none either); the feature is exercised through the existing `customer-support-fde` CLI
  entry point that already drives the whole graph.
- **III. Simplicity (YAGNI)**: PASS. No join/fan-in node (each branch off `cart_summary`
  terminates at `END` independently); no new `SupportState` field (the node is a pure side
  effect against SQLite); the account-number guard is a plain in-function early return, not a
  new conditional graph edge, mirroring how `order_support_agent.call_model`'s condensation guard
  and `ticket_gen_node`'s destination branch are already implemented as in-function checks rather
  than graph-level routing (see research.md Decision 5 for why a conditional edge was rejected as
  unneeded complexity here).
- **IV. Observability & Versioning**: PASS. The new `ChatOpenAI` call is automatically captured by
  the existing global OpenInference LangChain instrumentation — no new tracing code needed, same
  as every other LLM call in this codebase. This is a MINOR, backward-compatible feature addition
  (new node, new `db.py` function, no breaking change to existing behavior or schema).

No violations — Complexity Tracking table intentionally omitted.

## Project Structure

### Documentation (this feature)

```text
specs/013-memory-gen-agent/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   ├── memory-gen-node.md
│   └── db-account-preferences.md
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/customer_support_fde/
├── nodes/
│   ├── memory_gen_node.py         # NEW — extraction + merge + persistence
│   ├── cart_summary_node.py       # unchanged (source of the new graph edge)
│   ├── ticket_gen_node.py         # unchanged (runs in parallel with the new node)
│   ├── order_support_agent.py     # unchanged (already reads account_preferences back)
│   └── ... (account_identification_node.py, refund_agent.py, router_agent.py, clarify_intent.py — unchanged)
├── graph.py                       # MODIFIED — register memory_gen_node, add 2 edges
├── db.py                          # MODIFIED — add update_account_preferences()
├── state.py                       # unchanged — no new SupportState fields
└── tools/                         # unchanged

tests/
├── unit/
│   ├── test_memory_gen_node.py    # NEW
│   └── test_db.py                 # MODIFIED — cover update_account_preferences
└── integration/
    └── test_order_support_trajectory.py   # MODIFIED — extend an account-holding scenario
```

**Structure Decision**: Single project, existing layout (Option 1 from the template). No new
top-level directories; the feature is one new node module plus additive changes to two existing
modules (`graph.py`, `db.py`), matching how every prior feature in this repo
(`specs/007` through `specs/012`) has been structured.

## Complexity Tracking

*No Constitution Check violations — table intentionally left empty.*
