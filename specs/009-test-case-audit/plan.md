# Implementation Plan: Test Case Audit & Coverage Rationalization

**Branch**: `009-test-case-audit` | **Date**: 2026-09-12 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/009-test-case-audit/spec.md`

## Summary

Audit the existing pytest suite (183 collected test cases across 14 files, per
`pytest --collect-only -q`) to remove test cases whose behavioral coverage is fully
duplicated elsewhere, while guaranteeing every `@tool`-decorated function and every
hand-written LangGraph node function has at least one base-case and one edge-case test.
Changes are applied directly to the test files (not merely recommended), and the audit
produces a checked-in record at `specs/009-test-case-audit/audit-record.md` documenting
before/after counts, every removal with its superseding test, and every added test with
the gap it closes. No new end-to-end/multi-agent test is authored as part of this effort.

## Technical Context

**Language/Version**: Python >=3.14 (per `pyproject.toml`)

**Primary Dependencies**: pytest >=9.1.1 (test framework under audit), langgraph >=1.2.11,
langchain / langchain-openai >=1.4.0/1.6.1, agentevals >=0.0.9 (used by the existing
trajectory/integration tests)

**Storage**: SQLite (`customer_support.db`, via `src/customer_support_fde/db.py`) — exercised
by `tests/unit/test_db.py`; not a target of this audit's coverage guarantee (FR-002 scope),
but its existing tests are still in scope for the redundancy review (FR-001, FR-004)

**Testing**: pytest — this feature's subject matter is the test suite itself; no new test
framework or runner is introduced

**Target Platform**: Cross-platform Python library/CLI (developed on Windows, no OS-specific
test logic identified)

**Project Type**: Single project (library + CLI, per Constitution Principle II) — no
frontend/backend split

**Performance Goals**: N/A (not a runtime-performance feature). The one performance-adjacent
success criterion is procedural: full-suite wall-clock run time after the audit must be the
same or better than the captured baseline (SC-007).

**Constraints**: Must not alter the assertions or pass/fail outcome of any retained test
(FR-008); every retained/added test must carry the constitution's required one-line
base/edge/error/regression category comment (FR-007); no full end-to-end/multi-agent test
may be introduced (FR-006).

**Scale/Scope**: 183 collected test cases (pytest instance count, including parametrized
cases) across 14 test files; 10 `@tool`-decorated functions (`cart_tools.py`,
`menu_tools.py`, `refund_tools.py`); 9 hand-written graph node functions across
`nodes/*.py` (see Research Decision 2 for the exact scoped list).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Test-First (NON-NEGOTIABLE)**: This feature's output *is* test code. Every test
  case added to close a base/edge gap (FR-003) must be run and confirmed to pass against
  the current implementation before being counted as closing that gap, and must carry the
  required category comment (FR-007). Because these tests backfill coverage for already-shipped
  behavior rather than accompanying new production code, the red-green-refactor sequence
  applies as: write the test, run it, confirm it passes (green) and would fail if the
  covered behavior regressed — not "watch it fail first" against unwritten code. **PASS**
  (compliant reading; no violation to justify).
- **II. Library-First & CLI Interface**: No new modules, no new CLI surface. **PASS** (N/A —
  nothing added here that this principle governs).
- **III. Simplicity (YAGNI)**: The feature's explicit purpose is reducing incidental
  complexity (redundant tests) without adding new abstractions, fixtures, or tooling beyond
  what pytest already provides. **PASS**.
- **IV. Observability & Versioning**: No agent runtime behavior changes, so no new LangSmith
  tracing is required. This is a test-suite-only change; per semantic versioning it warrants
  at most a PATCH bump (no MINOR/MAJOR behavior change) if/when the maintainer chooses to
  version-bump — not mandated by this spec. **PASS**.

No violations requiring the Complexity Tracking table.

## Project Structure

### Documentation (this feature)

```text
specs/009-test-case-audit/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md         # Phase 1 output (/speckit-plan command)
├── quickstart.md         # Phase 1 output (/speckit-plan command)
├── audit-record.md       # Feature deliverable (FR-009) — produced during implementation
│                          # (/speckit-tasks + /speckit-implement), not by /speckit-plan
└── checklists/
    └── requirements.md   # Spec quality checklist (from /speckit-specify)
```

No `contracts/` directory: this feature exposes no external interface (no new CLI command,
API, or schema). It only edits existing test files and adds one internal markdown record.
See Research Decision 4.

### Source Code (repository root)

```text
src/customer_support_fde/
├── tools/                     # 10 @tool-decorated functions — in scope for FR-002 coverage
│   ├── cart_tools.py          #   add_items_to_cart, remove_items_from_cart,
│   │                          #   mark_order_confirmed, get_cart_total
│   ├── menu_tools.py          #   get_menu, get_menu_item
│   └── refund_tools.py        #   lookup_order, process_refund_request, log_complaint,
│                              #   conclude_refund_conversation
├── nodes/                     # 9 hand-written node functions — in scope for FR-002 coverage
│   ├── router_agent.py        #   router_agent
│   ├── clarify_intent.py      #   clarify_intent
│   ├── order_support_agent.py #   call_model, await_customer (order_tools is a
│   │                          #   framework ToolNode — excluded, see Research Decision 2)
│   ├── refund_agent.py        #   refund_agent, refund_await_customer (refund_tools is a
│   │                          #   framework ToolNode — excluded)
│   ├── cart_summary_node.py   #   cart_summary_node
│   └── ticket_gen_node.py     #   ticket_gen_node, refund_ticket_node
├── db.py, refund_policy.py    # Out of FR-002 coverage scope; existing tests still reviewed
│                              # for redundancy (FR-001, FR-004)
├── cli.py, graph.py           # Out of FR-002 coverage scope; existing tests still reviewed
│                              # for redundancy (FR-001, FR-004)
└── state.py, menu/

tests/
├── unit/                      # 12 files — primary audit target for redundancy + gap-filling
│   ├── test_cart_tools.py, test_menu_tools.py, test_refund_tools.py
│   ├── test_router_agent.py, test_clarify_intent.py, test_order_support_agent.py,
│   │   test_refund_agent.py
│   ├── test_cart_summary_and_ticket_nodes.py
│   ├── test_db.py, test_refund_policy.py, test_cli.py
│   └── conftest.py
└── integration/               # Existing per-agent trajectory tests — in scope for
    ├── test_router_trajectory.py       # redundancy review (FR-001, FR-004); no new
    ├── test_order_support_trajectory.py # full end-to-end/multi-agent test is added here
    ├── test_refund_trajectory.py        # (FR-006)
    └── _trajectory.py                   # shared helper, not a test file itself
```

**Structure Decision**: Single-project layout (already established by the repository);
this feature adds no new source directories. Work is confined to editing files under
`tests/unit/` and `tests/integration/`, plus creating the one new documentation artifact
`specs/009-test-case-audit/audit-record.md`.

## Complexity Tracking

*No Constitution Check violations — table not needed.*

## Post-Design Constitution Check

*Re-evaluated after Phase 1 (data-model.md, quickstart.md; no contracts/ — see Research
Decision 4).*

Design introduced no new modules, dependencies, external interfaces, or runtime behavior —
only a bookkeeping data model (`TestCase`, `ToolOrNode`, `AuditRecord`) describing edits to
existing test files and one new markdown artifact. All four gates evaluated pre-design
(Test-First, Library-First & CLI, Simplicity, Observability & Versioning) still **PASS**
unchanged. No new complexity to justify.
