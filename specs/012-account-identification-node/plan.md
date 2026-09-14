# Implementation Plan: Customer Account Identification Node

**Branch**: `012-account-identification-node` | **Date**: 2026-09-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/012-account-identification-node/spec.md`

## Summary

Insert a deterministic, non-LLM node (`account_identification_node`) between the router/clarify
step and the order/support agent's `call_model`. It presents a numbered three-option menu (use
an existing account, continue without one, sign up), resolved the same
`interrupt()`-loop-until-valid way `clarify_intent` already resolves its own menu. A new
`accounts` table (account number + a single free-text `preferences` paragraph) is added to the
existing SQLite database via the existing `--init-db` path. When an account is identified (found
or newly created), its account number and preferences text are carried on `SupportState` and
injected into the order/support agent's context as an extra `SystemMessage`, the same way the
cart summary and conversation summary are already injected — no new agent tool is needed since
the spec only requires the text be *available*, not programmatically inspected. Populating
`preferences` during conversation is explicitly out of scope (spec Assumptions); this feature
only creates the column and the create/lookup path.

## Technical Context

**Language/Version**: Python >=3.14 (per `pyproject.toml`)

**Primary Dependencies**: langgraph (existing — `interrupt()`/`Command(resume=...)`, already used
by `clarify_intent.py`); no new dependency. `langchain_core.messages.SystemMessage` (existing,
already used in `order_support_agent.py`) to carry preferences text into the agent's context.

**Storage**: SQLite (`customer_support.db`, via `src/customer_support_fde/db.py`) — one new table,
`accounts`, appended to the existing idempotent `_SCHEMA` / `init_database()` path.

**Testing**: pytest (`tests/unit`, `tests/integration`), matching the project's existing
unit-plus-trajectory split.

**Target Platform**: Cross-platform Python library/CLI (existing target, unchanged).

**Project Type**: Single project (library + CLI, per Constitution Principle II) — no new
directories.

**Performance Goals**: N/A — a single-row SQLite lookup/insert on an existing connection pattern;
no throughput target beyond what the existing menu/order lookups already meet.

**Constraints**: The step's branching MUST be driven only by a numbered/lettered reply (FR-002,
FR-011, FR-012) — never by open-ended LLM interpretation, consistent with `clarify_intent`'s
existing determinism. Account lookup MUST succeed on the account number alone (FR-009,
Clarifications). Preferences MUST be stored and surfaced as a single opaque free-text field, not
parsed (Clarifications, Assumptions).

**Scale/Scope**: One new node function, one new table, two new `SupportState` fields, edits to
`graph.py`, `cli.py`, and `order_support_agent.py`'s context builder. No new CLI flags, no new
`@tool`-decorated functions, no changes to the refund path.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Test-First (NON-NEGOTIABLE)**: `/speckit-tasks` + `/speckit-implement` will write failing
  tests first for the new node (menu handling, found/not-found/sign-up/no-account paths, invalid
  input re-prompt), the new `db.py` account functions, the `SupportState` wiring, and the
  preferences-injection change in `order_support_agent.py`, each carrying the required
  base/edge/error/regression category comment. **PASS** (procedural gate — enforced during
  implementation, not violated by this plan).
- **II. Library-First & CLI Interface**: The new node is a single-purpose module,
  `src/customer_support_fde/nodes/account_identification_node.py`, alongside the existing
  `nodes/*.py` files. No new CLI surface is needed — the CLI's existing generic
  `while "__interrupt__" in result` loop (`cli.py`) already drives any node's `interrupt()`
  calls; only two keys are added to the initial state dict it builds. **PASS**.
- **III. Simplicity (YAGNI)**: Reuses the existing Crockford base32 account-number scheme
  (`db.py`'s `ID_ALPHABET`/`ID_LENGTH`/confusion-folding) instead of inventing a new id format;
  adds two flat `SupportState` fields (matching the existing flat-field convention — see
  `order_id`, `refund_request`, etc. — rather than a nested dict); routes the new node to
  `call_model` with a single unconditional edge, since all three menu options converge on the
  same next step and no conditional graph routing is needed. **PASS**.
- **IV. Observability & Versioning**: The new node is a plain function registered in the
  `StateGraph`, so Phoenix's existing `auto_instrument=True` OpenInference instrumentation
  (`tracing.py`) traces it automatically like every other node — no manual instrumentation code
  is added. This is a backward-compatible feature addition (new table, new optional state
  fields, no existing behavior changed for customers who pick "continue without an account"), so
  it warrants a MINOR version bump per semantic versioning when released. **PASS**.

No violations — the Complexity Tracking table is not needed.

## Project Structure

### Documentation (this feature)

```text
specs/012-account-identification-node/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md         # Phase 1 output (/speckit-plan command)
├── quickstart.md         # Phase 1 output (/speckit-plan command)
├── contracts/            # Phase 1 output (/speckit-plan command)
│   ├── sqlite-schema.sql
│   └── account-identification-step.md
├── checklists/
│   └── requirements.md   # Spec quality checklist (from /speckit-specify /speckit-clarify)
└── tasks.md              # Phase 2 output (/speckit-tasks command — NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/customer_support_fde/
├── nodes/
│   ├── router_agent.py                 # unchanged
│   ├── clarify_intent.py               # unchanged — pattern reused, not modified
│   ├── account_identification_node.py  # NEW — deterministic 3-option menu node
│   ├── order_support_agent.py          # edited — inject account_preferences into context
│   ├── refund_agent.py                 # unchanged — feature is scoped to order/support only
│   ├── cart_summary_node.py            # unchanged
│   └── ticket_gen_node.py              # unchanged
├── db.py            # edited — accounts table in _SCHEMA; account create/lookup functions
├── state.py          # edited — account_number, account_preferences fields
├── graph.py          # edited — node registered and wired in
├── cli.py            # edited — two new keys in the initial state dict
└── tools/, menu/, refund_policy.py, tracing.py, tickets.py   # unchanged

tests/
├── unit/
│   ├── test_account_identification_node.py   # NEW
│   ├── test_db.py                             # edited — account create/lookup coverage
│   ├── test_order_support_agent.py            # edited — preferences-injection coverage
│   └── test_cli.py                            # edited — initial state fields present
└── integration/
    └── test_order_support_trajectory.py       # edited or extended — account flow end-to-end
```

**Structure Decision**: Single-project layout (already established). No new top-level
directories; the feature adds one node module and extends five existing files plus their tests.

## Complexity Tracking

*No Constitution Check violations — table not needed.*

## Post-Design Constitution Check

*Re-evaluated after Phase 1 (data-model.md, contracts/, quickstart.md).*

Design added exactly what Phase 0 research anticipated: one table (`accounts`), one node module,
two flat state fields, and a context-injection edit — no new dependency, no new CLI flag, no
conditional graph branching beyond the node's own internal menu loop. All four gates evaluated
pre-design (Test-First, Library-First & CLI, Simplicity, Observability & Versioning) still
**PASS** unchanged. No new complexity to justify.
