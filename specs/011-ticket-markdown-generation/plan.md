# Implementation Plan: Ticket Markdown Generation

**Branch**: `011-ticket-markdown-generation` | **Date**: 2026-09-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/011-ticket-markdown-generation/spec.md`

## Summary

When an order/support interaction concludes with a confirmed order, write a markdown ticket
(items + total) to a `tickets/` folder; when it concludes without an order, write nothing. When
a refund-agent interaction concludes, always write a markdown ticket (issue/complaint,
sentiment, order id, refund-created yes/no). The graph's two separate terminal ticket nodes
collapse into one: a single `ticket_gen_node` (`nodes/ticket_gen_node.py`) dispatches on
`state["destination"]` to an order branch or a refund branch (`research.md` Decision 1),
matching CLAUDE.md's own "one Ticket Summary Agent, two ticket types" architecture. A new
`tickets.py` module renders each branch's ticket dict to markdown and writes it. Three of the
refund ticket's four fields (order ID, sentiment, refund-created) stay sourced from graph state,
exactly as today — only the issue/complaint text is new, and it comes from a plain LLM call over
the conversation transcript inside `ticket_gen_node` itself, not from any new state field or
change to `tools/refund_tools.py` (`research.md` Decisions 5, 5a). Filenames are
`<type>-<order_id>.md`, so a repeat ticket for the same order/type replaces the prior file; both
the file write and the issue-extraction LLM call fail safely — caught, logged, and never
blocking the customer-facing conversation.

## Technical Context

**Language/Version**: Python >=3.14 (`pyproject.toml`)

**Primary Dependencies**: LangGraph (existing graph/node structure) and `langchain_openai`'s
`ChatOpenAI` (already a dependency, already used the same way by `refund_agent.py`/
`router_agent.py`) for the new issue-extraction call — no new dependency; the rest of the new
code uses only the standard library (`pathlib`, `logging`, `uuid`, `os`)

**Storage**: Filesystem only for this feature — markdown files under `tickets/` (default,
overridable via `CUSTOMER_SUPPORT_TICKETS_DIR`, mirroring `CUSTOMER_SUPPORT_DB`). The existing
SQLite database is read indirectly (via already-built `order_ticket`/`refund_ticket` state) but
gains no new tables or columns. No new `SupportState` field either — see Storage note above on
the issue text specifically.

**Testing**: pytest, following existing conventions — `tests/unit/test_tickets.py` (new,
`tmp_path`/`monkeypatch` for filesystem isolation, mirroring `test_cart_summary_and_ticket_nodes.py`'s
`_use_tmp_db` pattern) and updates to `tests/unit/test_cart_summary_and_ticket_nodes.py`,
including LLM-mocking for `_extract_refund_issue` via `monkeypatch.setattr(module, "_build_llm", lambda: fake_llm)`,
the same pattern `tests/unit/test_refund_agent.py` already uses for its condensation call.
`tools/refund_tools.py` and `state.py` are unmodified by this feature, so their test files need
no changes; the `tests/integration/*_trajectory.py` suites are unaffected for the same reason.

**Target Platform**: Same as the rest of the project — cross-platform CLI, developed/run on
Windows (CLAUDE.md).

**Project Type**: Single project (library + CLI), per constitution Principle II — no new
top-level project or service boundary.

**Performance Goals**: N/A — one small (<1KB) file write per concluded conversation; no
throughput target.

**Constraints**: A ticket-file write failure MUST NOT block or alter the customer-facing
interaction (FR-011).

**Scale/Scope**: One ticket file per concluded interaction; no concurrency requirements beyond
FR-008's same-order/same-type replace-on-repeat behavior.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Result |
|---|---|---|
| I. Test-First | New behavior (`tickets.py`, the unified `ticket_gen_node`, `_extract_refund_issue`) requires failing tests before implementation, per `quickstart.md` §2's table and the updated existing-test files. Enforced in `/speckit-tasks`/`/speckit-implement`, not violated by this plan. | PASS |
| II. Library-First & CLI Interface | `tickets.py` is a new standalone, single-purpose module (rendering/writing only, `research.md` Decision 1). The issue-extraction LLM call is a small helper *within* `ticket_gen_node.py`, not a new module — consistent with `refund_agent.py`'s own condensation call living alongside the node it serves rather than in a separate file. Neither needs a separate CLI entry point; ticket generation is a side effect of the conversation already exposed through the existing `customer-support-fde` CLI. | PASS |
| III. Simplicity (YAGNI) | Two existing graph nodes collapse into one rather than adding a third; no new database tables/migrations; no new `SupportState` fields; no new dependencies (the issue-extraction call reuses the existing `ChatOpenAI` pattern); no configurable ticket formats beyond the one FR-009 requires (`research.md` Decisions 1, 2, 5, 7). | PASS |
| IV. Observability & Versioning | Ticket-write failures (`research.md` Decision 6) and issue-extraction failures (`research.md` Decision 5a) are both logged rather than silently dropped — the latter deliberately goes further than the `refund_agent.py` condensation precedent it otherwise mirrors, because a lost issue is a permanent gap in the ticket record. Both sit outside the LLM-driven *tool-calling* flow the LangSmith requirement primarily targets, so stderr-visible `logging` is appropriate, matching the project's existing CLI error-visibility pattern. This is a MINOR (backward-compatible) feature addition — version bump is a task, not a design concern. | PASS |

No violations to justify — Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/011-ticket-markdown-generation/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md         # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/            # Phase 1 output (/speckit-plan command)
│   ├── tickets-module.md
│   └── refund-issue-extraction.md
└── tasks.md              # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/customer_support_fde/
├── tickets.py                       # NEW — tickets_dir(), write_order_ticket(), write_refund_ticket()
├── graph.py                         # MODIFIED — one ticket_gen_node registered; both terminal edges route to it
├── nodes/
│   └── ticket_gen_node.py           # MODIFIED — unified ticket_gen_node(state) dispatching to
│                                     #   _order_ticket_node/_refund_ticket_node; adds
│                                     #   _extract_refund_issue() and calls tickets.write_*_ticket()
├── state.py                         # unchanged
├── tools/
│   └── refund_tools.py              # unchanged
├── cli.py                           # unchanged
├── db.py                            # unchanged
└── ...                              # unchanged

tests/
├── unit/
│   ├── test_tickets.py              # NEW
│   └── test_cart_summary_and_ticket_nodes.py   # MODIFIED — unified-node dispatch, order/refund
│                                     #   ticket writing, and issue-extraction assertions
│                                     #   (LLM mocked per `refund_agent.py`'s test pattern)
└── integration/
    ├── test_order_support_trajectory.py   # unchanged
    └── test_refund_trajectory.py          # unchanged
```

**Structure Decision**: Single project, matching the existing layout exactly — this feature adds
one new module (`tickets.py`) and consolidates the existing two-function
`nodes/ticket_gen_node.py` into one dispatching node, touching `graph.py`'s wiring accordingly.
`state.py`, `tools/refund_tools.py`, and `cli.py` are untouched, which is narrower than the
original plan (`research.md` Decision 5).

## Complexity Tracking

*(No entries — no Constitution Check violations.)*
