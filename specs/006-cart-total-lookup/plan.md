# Implementation Plan: Cart Total Lookup

**Branch**: `006-cart-total-lookup` | **Date**: 2026-09-11 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-cart-total-lookup/spec.md`

## Summary

Give the order support agent a dedicated tool that computes and returns the customer's exact
current cart total, so the agent relays a looked-up figure instead of doing arithmetic itself
when a customer asks "what's my total?". The total-calculation logic (sum of item price ×
quantity, rounded up to the nearest cent) is extracted from `cart_summary_node.py` into a
shared helper in `menu_tools.py` so both the mid-conversation tool and the final order summary
use the exact same rule, per FR-004/SC-003.

## Technical Context

**Language/Version**: Python >=3.14 (per `pyproject.toml`)

**Primary Dependencies**: `langchain` / `langgraph` (existing `@tool` + `InjectedState` /
`ToolNode` pattern already used by every other cart/menu tool). No new dependencies.

**Storage**: SQLite via `customer_support_fde.db` — read-only for this feature (menu prices
already loaded into `SupportState["menu"]` before the agent runs; no new tables or writes).

**Testing**: pytest, following the existing unit-test conventions in `tests/unit/test_cart_tools.py`,
`tests/unit/test_menu_tools.py`, and `tests/unit/test_cart_summary_and_ticket_nodes.py`.

**Target Platform**: Server-side LangGraph agent runtime, invoked via the `customer-support-fde`
CLI entry point.

**Project Type**: Single project (library + CLI per Constitution Principle II) — this feature
adds one function to an existing module (`menu_tools.py`) and one tool to an existing module
(`cart_tools.py`); no new top-level module.

**Performance Goals**: N/A beyond "same turn" (SC-002) — the computation is an in-memory sum
over the cart's item count (bounded by a single order, effectively O(1) in practice).

**Constraints**: Must reuse the existing round-up-to-nearest-cent rule from
`cart_summary_node.build_order_summary` rather than reimplementing it (FR-004, SC-003); must
not require any new customer- or agent-facing state beyond what's already on `SupportState`.

**Scale/Scope**: One new pure function (shared total calculation) + one new LangChain tool +
wiring it into `order_support_agent.py`'s tool list and system prompt. No new entities, no
schema changes.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Test-First (NON-NEGOTIABLE)**: PASS (planned) — `/speckit-tasks` will sequence failing
  unit tests for the new shared total helper and the new tool (happy path, empty cart, mixed
  quantities, rounding edge case) before any implementation task, each with a one-line
  `(base)`/`(edge)`/`(error)`/`(regression)` comment per the constitution's test-comment
  requirement.
- **II. Library-First & CLI Interface**: PASS — the new capability is a plain function in
  `menu_tools.py` plus a `@tool`-decorated wrapper in `cart_tools.py`, matching how every
  existing cart/menu capability is structured; it is reached through the same
  `customer-support-fde` CLI/agent runtime as the rest of ordering, not a bespoke entry point.
- **III. Simplicity (YAGNI)**: PASS — reuses the existing rounding logic via extraction rather
  than adding a new module, a cached/duplicated total field, or new configuration. See
  [research.md](./research.md) for the alternatives rejected as unjustified complexity.
- **IV. Observability & Versioning**: PASS — the new tool call flows through the existing
  `ToolNode`/agent-invocation path, which is already covered by LangSmith tracing; no bespoke
  logging is added. This is a backward-compatible additive change (new tool, no behavior
  change to existing tools/state shape), so it lands as a MINOR version bump per semver.

No violations to record in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/006-cart-total-lookup/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md         # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   └── get_cart_total.md
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/customer_support_fde/
├── tools/
│   ├── menu_tools.py          # ADD: cart_total(menu_items, menu) helper (shared)
│   └── cart_tools.py          # ADD: get_cart_total @tool wrapper
├── nodes/
│   ├── cart_summary_node.py   # MODIFY: build_order_summary uses the shared cart_total() helper
│   └── order_support_agent.py # MODIFY: register get_cart_total in _ORDER_TOOLS + system prompt
└── state.py                    # unchanged — reuses existing menu_items / menu fields

tests/unit/
├── test_menu_tools.py          # ADD: tests for the shared cart_total() helper
├── test_cart_tools.py          # ADD: tests for the get_cart_total tool
└── test_cart_summary_and_ticket_nodes.py  # VERIFY: still passes using the shared helper
```

**Structure Decision**: Single project (existing layout under `src/customer_support_fde/`).
This feature is additive within the existing `tools/` and `nodes/` packages — no new
directories, no new project, consistent with Principle III (Simplicity) and Principle II
(Library-First, single importable package).

## Complexity Tracking

*No violations — table intentionally omitted.*
