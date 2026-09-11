# Implementation Plan: Cart Summary at Order Confirmation

**Branch**: `004-cart-summary-node` | **Date**: 2026-09-11 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-cart-summary-node/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Turn the currently-empty pass-through `confirm_node` into a real `cart_summary_node` that, at the
moment `order_confirmed` becomes true, prices the confirmed cart against the menu and hands the
customer an itemized recap: one line per distinct dish (canonical menu name, quantity, unit price,
line total) plus one order total. The summary is computed deterministically in Python — no LLM call
— because FR-006/SC-002 demand exact arithmetic that an LLM cannot be trusted or cheaply tested to
produce. The node writes a structured `order_summary` onto `SupportState` and appends the rendered
text as an `AIMessage`; `ticket_gen_node` then builds `order_ticket` from that same structure rather
than recomputing, which makes FR-010/SC-004 (ticket matches what the customer saw) true by
construction rather than by a second, drift-prone calculation.

Three pieces of scaffolding come with it: a `price_for_item` lookup in `tools/menu_tools.py` (exact
match on the canonical name, since cart keys are already canonical); a new `order_summary` field on
`SupportState`; and CLI output that actually prints the summary, which today prints only
`destination`/`query` and would otherwise drop the feature's entire user-visible payload on the
floor. No new third-party dependency — money arithmetic uses stdlib `decimal`.

**Breaking changes** (called out per Constitution Principle IV): the graph node key `confirm_node`
is renamed to `cart_summary`, the module `nodes/confirm_node.py` is renamed to
`nodes/cart_summary_node.py`, and `order_ticket` grows from `{"items": ...}` to a priced shape. Each
has existing callers/tests that must move with it.

## Technical Context

**Language/Version**: Python 3.14 (per `pyproject.toml` `requires-python`), unchanged from 001–003.

**Primary Dependencies**: `langgraph` (`StateGraph` node/edge wiring only — no new API surface);
`langchain-core` (`AIMessage`, already used across the nodes); stdlib `decimal` for money
arithmetic. No new third-party dependency, and — unlike 002/003 — no new LLM or tool-call surface:
this node never calls a model.

**Storage**: N/A. `order_summary` and `order_ticket` live on in-memory `SupportState` for the
duration of a thread, same as every other field.

**Testing**: `pytest`. `tests/unit/test_confirm_and_ticket_nodes.py` is renamed to
`tests/unit/test_cart_summary_and_ticket_nodes.py` and rewritten against the real node (pure
functions called with hand-built state dicts — no LLM, no graph); `tests/unit/test_menu_tools.py`
gains `price_for_item` cases; `tests/integration/test_order_support_trajectory.py` has its expected
node-name trajectory and its two `order_ticket` assertions updated for the rename and the new ticket
shape.

**Target Platform**: Server-side Python library invoked through the existing
`customer-support-fde` CLI entry point — unchanged from 001–003.

**Project Type**: Single project — same `src/customer_support_fde/` package. One module renamed, no
new subpackages.

**Performance Goals**: None stated. SC-001–SC-005 are correctness and completeness criteria; the
node does a dict walk over a cart that holds at most a few dozen entries, so no performance target
is introduced.

**Constraints**: Summary values MUST be derived from the recorded cart and menu prices, never from
customer-supplied or model-generated numbers (FR-007, FR-011) — which rules out asking the LLM to
compose the recap. The order total is the sum of all raw line values, rounded up (never down) to two
decimals once (FR-006) — sum-then-round rather than round-then-sum, since menu prices are assumed to
always have ≤2 decimal places (spec.md Assumptions), making the two orderings equivalent for real
data. Repeat additions MUST appear as one consolidated line (FR-003) — already guaranteed by
`menu_items` being a `dict[str, int]`. Every cart item is assumed priceable by construction, so
there is no unpriceable-item branch; an empty cart MUST produce no total (FR-009). The ticket MUST
carry the same numbers shown to the customer (FR-010).

**Scale/Scope**: One renamed module gaining two pure functions (`build_order_summary`,
`render_order_summary`) plus the node itself; one new helper in `tools/menu_tools.py`; one new
`SupportState` field; a rewritten `ticket_gen_node` body; three edited lines in `graph.py`; CLI
initial-state and output changes. No new graph nodes, no new tools, no new edges.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Test-First (NON-NEGOTIABLE)**: PASS (planned) — failing tests land before implementation, in
  this order: `price_for_item` unit cases; `build_order_summary` cases (multi-item totalling,
  single unit, always-rounds-up total, empty cart, input not mutated); `render_order_summary` cases
  (every item named, total line present, empty-cart wording); `cart_summary_node` (writes
  `order_summary`, appends one `AIMessage`); `ticket_gen_node` (ticket mirrors `order_summary`); then
  the trajectory updates. Every case carries the required one-line
  `(base)`/`(edge)`/`(error)`/`(regression)` comment.
- **II. Library-First & CLI Interface**: PASS (planned) — `build_order_summary` and
  `render_order_summary` are plain importable pure functions taking a cart dict and returning
  data/text, with no LangGraph coupling; only the thin `cart_summary_node` wrapper touches
  `SupportState`. The CLI surfaces the result in both output modes: rendered text on stdout for
  humans, the structured summary inside `--json`. This closes a real gap — the CLI currently prints
  neither the ticket nor any confirmation output.
- **III. Simplicity (YAGNI)**: PASS (planned) — one new state field, justified below; no new tool,
  node, edge, or dependency; the node computes rather than prompting, which is both simpler and
  cheaper than a second LLM call site. Tax, fees, tips, discounts, and summary-time cart editing are
  out of scope per the spec's Assumptions and are not designed for.
  - *Justification for the new `order_summary` field*: the alternative is for `ticket_gen_node` to
    recompute prices independently, which is strictly more code and can silently disagree with what
    the customer was shown — the exact failure SC-004 exists to prevent. One shared field is the
    smaller and safer design, not speculative extensibility.
- **IV. Observability & Versioning**: PASS with explicit breaking-change callout — no new LLM call
  site is added, so existing LangSmith tracing covers the node's state updates with no new
  instrumentation. This is **not** a purely additive change: the graph node key `confirm_node` →
  `cart_summary`, the module path `nodes/confirm_node.py` → `nodes/cart_summary_node.py`, and the
  `order_ticket` shape all change. Per Principle IV these are called out here and must be repeated
  in the PR description; the package is pre-1.0 (`0.1.0`), so this lands as a MINOR bump with the
  breaking changes stated explicitly rather than a MAJOR bump.

No violations requiring justification — Complexity Tracking table omitted.

**Post-Phase-1 re-check**: Confirmed against the finished design
([data-model.md](./data-model.md), [contracts/cart-summary-node.md](./contracts/cart-summary-node.md)).
The design added no further state fields, no new dependency, and no new call sites beyond what was
gated above; `menu_items` keeps its existing `dict[str, int]` shape and every guarantee in
`specs/002-order-support-agent/data-model.md` continues to hold. The rename and `order_ticket` shape
change remain the only backward-incompatible edges, already disclosed under Principle IV. All four
gates still PASS.

## Project Structure

### Documentation (this feature)

```text
specs/004-cart-summary-node/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   └── cart-summary-node.md
├── checklists/
│   └── requirements.md  # /speckit-specify output
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/customer_support_fde/
├── state.py                     # SupportState gains order_summary: dict | None
├── graph.py                     # import + node key "confirm_node" -> "cart_summary"; both edges retargeted
├── cli.py                       # initial state gains order_summary; _print_result prints the summary
├── nodes/
│   ├── cart_summary_node.py     # RENAMED from confirm_node.py; gains build_order_summary(),
│   │                            # render_order_summary(), and the real cart_summary_node()
│   └── ticket_gen_node.py       # builds order_ticket from order_summary instead of menu_items alone
└── tools/
    └── menu_tools.py            # gains price_for_item(name, menu) -> float | None

tests/
├── unit/
│   ├── test_cart_summary_and_ticket_nodes.py  # RENAMED from test_confirm_and_ticket_nodes.py; rewritten
│   └── test_menu_tools.py                     # existing; gains price_for_item cases
└── integration/
    └── test_order_support_trajectory.py       # existing; node-name trajectory + order_ticket assertions updated
```

**Structure Decision**: Single project (Option 1), unchanged from 001–003. No new source
directories. The one structural move is the `confirm_node.py` → `cart_summary_node.py` rename the
feature request asked for; everything else is an edit to a module that already exists.

## Complexity Tracking

*No Constitution Check violations — table intentionally omitted.*
