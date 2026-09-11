# Implementation Plan: Refund Policy Agent

**Branch**: `007-refund-policy-agent` | **Date**: 2026-09-11 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/007-refund-policy-agent/spec.md`

## Summary

Turn the stub `refund_agent` node into a working post-order support agent: it looks up a past
order by id, gathers the facts the refund policy needs, applies that policy deterministically,
and writes the outcome to SQLite as either a pending refund request or a complaint.

The load-bearing technical decision is that the language model never decides eligibility. A
pure function in a new `refund_policy` module evaluates the four policy conditions, and a
single tool (`process_refund_request`) fuses evaluation with persistence so there is no code
path from the model to a stored refund request that skips the policy. Sentiment reaches the
agent's prompt for tone only and is structurally absent from the policy function's signature,
which makes SC-009 true by construction. Full reasoning in [research.md](./research.md).

## Technical Context

**Language/Version**: Python >=3.14

**Primary Dependencies**: LangGraph, LangChain (+ `langchain-openai` via OpenRouter), Pydantic —
all already declared. No new dependencies.

**Storage**: SQLite via the standard-library `sqlite3` module, in the existing
`customer_support.db` (path overridable with `CUSTOMER_SUPPORT_DB`). Three new tables.

**Testing**: PyTest. Unit tests run without an API key; trajectory tests follow the existing
`tests/integration/_trajectory.py` harness.

**Target Platform**: Cross-platform CLI (developed on Windows; no platform-specific code).

**Project Type**: Single Python package — importable library plus a CLI entry point.

**Performance Goals**: Not latency-bound. The only user-facing budget is SC-004: a customer
supplying a valid order id gets an eligibility decision within 3 conversational turns, which is
a prompt/flow-design constraint rather than a throughput one.

**Constraints**: Policy evaluation must be deterministic and reproducible without live model
calls (SC-001, SC-009). No money movement, no payment integration. No staff-facing command this
phase — retrieval is a data guarantee only (FR-024).

**Scale/Scope**: Single-user local CLI against a local SQLite file; order volume in the tens.
Feature scope is 2 new modules, 3 new tables, 4 new tools, 3 new graph nodes.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Evaluated against `.specify/memory/constitution.md` v1.2.0.

| Principle | Gate | Status |
|---|---|---|
| I. Test-First (NON-NEGOTIABLE) | Tests written, reviewed, and failing before implementation; every test carries a one-line comment naming what it verifies and its category | **PASS (committed)** — `/speckit-tasks` must order every test task ahead of the implementation it covers. The design is deliberately shaped for this: the policy function is pure and the DB layer takes an explicit path, so the bulk of the suite runs with no API key and no global state. |
| II. Library-First & CLI Interface | Every feature starts as a standalone importable module with a single purpose; human-invocable functionality exposed via CLI | **PASS** — `refund_policy.py` (policy evaluation) and `tools/refund_tools.py` (agent-facing tools) are each single-purpose and importable. No new CLI subcommand is added, and none is owed: the only human-invocable surface here is the refund conversation, already reachable through the existing CLI, and staff-facing retrieval was explicitly clarified out of scope for this phase. |
| III. Simplicity (YAGNI) | Simplest design that satisfies the current requirement; no speculative abstraction; added complexity justified | **PASS** — no new dependencies, no migration framework, no repository/service layer. Each of the 5 new `SupportState` fields traces to a specific FR (table below). The one reserved-for-later element is the `approved` status value, which the spec explicitly asks be reserved so a later phase need not reshape the data. |
| IV. Observability & Versioning | Agent runs/tool calls/errors traced via LangSmith; semantic versioning | **PASS** — new nodes and tools are LangChain/LangGraph runnables and are traced by the existing configuration with no per-node instrumentation. Version bump: `0.2.0` → `0.3.0` (MINOR — backward-compatible feature addition; no existing public behavior changes). See the pre-existing dependency-declaration observation in research.md Decision 10, which this feature does not introduce and does not fix. |

**No violations. Complexity Tracking section omitted.**

Every new `SupportState` field is justified by a requirement it is needed to satisfy:

| Field | Required by |
|---|---|
| `order_lookup` | FR-002 (no decision without an identified order), FR-014 (price from stored lines), FR-023 (ticket carries the order) |
| `refund_resolved` | Loop termination for the multi-turn refund flow (FR-022) |
| `refund_request` | FR-023 (ticket carries the resulting record) |
| `complaint_ids` | FR-020, FR-021 (one complaint per conversation per order, extended in place) |
| `refund_ticket` | FR-023 (the artifact itself) |

**Post-Phase 1 re-check**: Re-evaluated after the data model and contracts were written. No
gate changed status. The design added no module, table, field, or dependency beyond those
listed above.

## Project Structure

### Documentation (this feature)

```text
specs/007-refund-policy-agent/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── sqlite-schema.sql
│   └── refund-tools.md
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/customer_support_fde/
├── cli.py                      # MODIFY: seed new state fields; print the refund outcome
├── db.py                       # MODIFY: 3 tables added to _SCHEMA; refund/complaint accessors
├── graph.py                    # MODIFY: wire the refund loop and its ticket node
├── refund_policy.py            # NEW: pure, LLM-free policy evaluation
├── state.py                    # MODIFY: 5 new SupportState fields
├── nodes/
│   ├── refund_agent.py         # REWRITE: stub -> call_model / await_customer for refunds
│   └── ticket_gen_node.py      # MODIFY: add refund_ticket_node alongside the order ticket
└── tools/
    └── refund_tools.py         # NEW: lookup_order, process_refund_request,
                                #      log_complaint, conclude_refund_conversation

tests/
├── unit/
│   ├── test_refund_policy.py   # NEW: every policy branch, boundary-inclusive window
│   ├── test_refund_tools.py    # NEW: tool behavior, state guards, clamping
│   ├── test_refund_agent.py    # NEW: node seeding, turn handling, termination
│   ├── test_db.py              # MODIFY: refund request + complaint persistence
│   ├── test_cart_summary_and_ticket_nodes.py  # MODIFY: refund ticket shape
│   └── test_cli.py             # MODIFY: new state seeding, refund output
└── integration/
    └── test_refund_trajectory.py  # NEW: end-to-end conversation trajectories
```

**Structure Decision**: The existing single-package layout is kept unchanged — this feature
adds two modules inside it and touches six existing files. `refund_policy.py` sits at package
root rather than under `tools/` because it is domain logic with no LangChain coupling, and
placing it beside `db.py` keeps it importable by tests that bind no model. The refund flow gets
its own graph nodes rather than branching the order flow's, because the two loops differ in how
they treat the message transcript (research.md Decision 7).

## Graph topology

The refund branch mirrors the order branch's shape. New nodes are marked `NEW`.

```text
router_agent ─┬─ "order_support" → call_model → … → cart_summary → ticket_gen_node → END
              ├─ "unclear"       → clarify_intent ─┐
              └─ "refund" ───────────────────────┬─┘
                                                 ▼
                                        refund_agent  (REWRITTEN: seeds + calls model)
                                                 │ tools_condition
                                   ┌─────────────┴──────────────┐
                                   ▼ "tools"                    ▼ "__end__"
                            refund_tools (NEW)         refund_await_customer (NEW)
                                   │                             │
                                   └──────► refund_agent ◄───────┤ not resolved
                                                                 │ resolved
                                                                 ▼
                                                      refund_ticket_node (NEW) → END
```

`refund_await_customer` interrupts with the agent's last message and appends the reply as a
`HumanMessage`; it does not clear the transcript. It routes to `refund_ticket_node` only once
`conclude_refund_conversation` has set `refund_resolved`.

## Phase 0: Research

**Status**: Complete — [research.md](./research.md).

Ten decisions recorded, each with rationale and rejected alternatives. The ones that most
shape the implementation: policy as a pure function (1), evaluation fused with persistence (2),
order read from state rather than a model argument (3), complaint de-duplication in state
rather than a database column (5), and duplicate refund requests blocked by a `UNIQUE`
constraint (6).

## Phase 1: Design & Contracts

**Status**: Complete.

- [data-model.md](./data-model.md) — the three persisted entities, the in-memory
  `PolicyDecision`, the five new `SupportState` fields, validation rules traced to FRs, and the
  refund request status lifecycle.
- [contracts/sqlite-schema.sql](./contracts/sqlite-schema.sql) — DDL for `refund_requests`,
  `refund_request_lines`, and `complaints`, appended to `db._SCHEMA`.
- [contracts/refund-tools.md](./contracts/refund-tools.md) — the four agent-facing tool
  contracts, following the convention established by
  `specs/006-cart-total-lookup/contracts/get_cart_total.md`.
- [quickstart.md](./quickstart.md) — runnable validation scenarios covering the qualifying
  refund, each denial branch, the no-substitute waiver, and complaint de-duplication.

## Requirements coverage

Where each group of functional requirements is satisfied:

| Requirements | Satisfied by |
|---|---|
| FR-001 – FR-003 (order retrieval) | `lookup_order` tool over the existing `db.get_order`, which already normalizes ids and returns `None` for a miss |
| FR-004 – FR-008 (policy evaluation) | `refund_policy.evaluate()` — pure, exhaustively unit tested |
| FR-009 – FR-011 (denial, no-create, duplicates) | `process_refund_request` pre-checks, plus `UNIQUE(order_id)` on `refund_requests` |
| FR-012 – FR-016 (refund requests) | `db.record_refund_request` writing `refund_requests` + `refund_request_lines`; status fixed to `pending` |
| FR-017 – FR-021 (complaints) | `log_complaint` and the denial path of `process_refund_request`, de-duplicated via `state["complaint_ids"]` |
| FR-022, FR-025 (outcome, storage failure) | Tool-rendered reply strings; `OrderStoreError` surfaced as a customer-facing "not recorded" message rather than a false confirmation |
| FR-023 (ticket) | `refund_ticket_node` in `nodes/ticket_gen_node.py` |
| FR-024 (retrievability) | `db.get_refund_request_for_order`, `db.list_refund_requests`, `db.list_complaints` |
| FR-026, FR-027 (sentiment) | Sentiment seeded into the system prompt for tone; absent from `refund_policy.evaluate()`'s signature |

## Risks and mitigations

- **The model fabricates an undelivered line.** Amounts are computed only from lines present on
  the retrieved order, and quantities are clamped to what was ordered (SC-008). A fabricated
  name matches no line and yields no amount rather than an invented one.
- **The model claims a refund was granted when the write failed.** The persistence error path
  returns an explicit "could not be recorded" string for the model to relay (FR-025), and the
  tool never reports success it did not achieve.
- **Existing databases lack the new tables.** `--init-db` is idempotent and already documented
  as the setup step; quickstart.md opens with it, and the tables use `IF NOT EXISTS`.
- **Adding required `SupportState` keys breaks in-repo constructors.** `cli.py` and existing
  tests construct the state dict literally and must be updated in the same change. Caught by
  the existing unit suite rather than at runtime.
