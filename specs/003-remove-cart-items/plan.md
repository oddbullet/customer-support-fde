# Implementation Plan: Remove Items From Cart

**Branch**: `003-remove-cart-items` | **Date**: 2026-09-10 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-remove-cart-items/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Add a fifth tool, `remove_items_from_cart`, to the existing order-support tool-calling loop (`nodes/order_support_agent.py`), alongside `get_menu`, `get_menu_item`, `add_items_to_cart`, and `mark_order_confirmed`. The tool lives in `tools/cart_tools.py` next to `add_items_to_cart`, reuses the same `resolve_menu_item` fuzzy-matching helper from `tools/menu_tools.py`, and follows the same `InjectedState`/`Command`-returning shape already established for cart mutation. Per the clarified spec, each requested removal names an item and optionally a quantity: an unqualified name deletes that item's entire cart entry regardless of how many units were present, while a stated quantity decrements the entry by that amount (capped at the entry's current quantity, deleting it if the cap is hit). No new graph nodes, no new `SupportState` fields, and no new third-party dependency are needed — this is an additive change to an existing tool module and the existing tool-binding list.

## Technical Context

**Language/Version**: Python 3.14 (per `pyproject.toml` `requires-python`, unchanged from 002).

**Primary Dependencies**: `langgraph` (`langgraph.prebuilt.InjectedState`, `langgraph.types.Command`, `langgraph.prebuilt.ToolNode` — all already in use by `add_items_to_cart`/`mark_order_confirmed`, no new API surface); `langchain-core` (`@tool`, `InjectedToolCallId`, `ToolMessage`); `pydantic` (`BaseModel`, already a transitive dependency via `langchain-core`/used directly in `nodes/router_agent.py`) for the per-item removal request shape the LLM populates. No new third-party dependency.

**Storage**: N/A — unchanged from 002; `menu_items` continues to live only on in-memory `SupportState` for the duration of a conversation/thread.

**Testing**: `pytest`; new unit tests in `tests/unit/test_cart_tools.py` for `remove_items_from_cart` (direct calls with a hand-built state dict, no LLM, no graph — same pattern as the existing `add_items_to_cart` tests); a new tool-call case added to `tests/unit/test_order_support_agent.py`'s inner-loop tests (LLM boundary faked, real tool execution); one new multi-turn scenario added to `tests/integration/test_order_support_trajectory.py` covering add-then-remove-then-confirm, following the existing `agentevals` trajectory-match pattern.

**Target Platform**: Server-side Python library invoked via the existing `customer-support-fde` CLI entry point — unchanged from 002.

**Project Type**: Single project — same `src/customer_support_fde/` package; no new subpackages, only an additive function in the existing `tools/cart_tools.py` module and a registration change in `nodes/order_support_agent.py`.

**Performance Goals**: Not a stated Success Criterion (SC-001–SC-004 are about correctness/completeness of removal outcomes, not latency); no new performance target introduced.

**Constraints**: Item-name resolution for removal MUST reuse the existing fuzzy-match/tie/not-found behavior (FR-001, FR-006, FR-006a) rather than a separate matching strategy; an unqualified removal MUST delete the entire entry regardless of current quantity (FR-002); a quantified removal MUST decrement by the requested amount, capped at the current quantity, deleting the entry if the cap is reached (FR-003, FR-004, FR-007); an item not currently in the cart MUST be reported rather than silently ignored (FR-005); multiple distinct items in one request MUST be resolved and removed independently (FR-008); cart mutation after `order_confirmed` is set stays out of scope, matching `add_items_to_cart`'s existing behavior (Assumptions).

**Scale/Scope**: One new tool function (`remove_items_from_cart`) plus one small helper/result-rendering function in `tools/cart_tools.py`; one new pydantic model (`CartRemoval`) describing a single removal request (item name + optional quantity); one line added to `_ORDER_TOOLS` and a short addition to `SYSTEM_PROMPT` in `nodes/order_support_agent.py`; no new modules, no new graph nodes, no `SupportState` schema change.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Test-First (NON-NEGOTIABLE)**: PASS (planned) — failing unit tests for `remove_items_from_cart` (full-entry removal, partial-quantity decrement, over-quantity capping, not-in-cart, not-found, tie, batched multi-item, no-mutate-input) will be written before the tool exists, then the inner-loop tool-call test and the trajectory-test addition, following the same red-green-refactor discipline as 002. Every new test case carries the required one-line `(base)`/`(edge)`/`(error)`/`(regression)` comment.
- **II. Library-First & CLI Interface**: PASS (planned) — `remove_items_from_cart` is a plain importable function in the existing `tools/` package with no framework-specific coupling beyond the `@tool` decorator already used by its siblings; no CLI changes are needed since it's exposed the same way `add_items_to_cart` already is, through the order-support agent's tool-calling loop.
- **III. Simplicity (YAGNI)**: PASS (planned) — reuses `resolve_menu_item`, `InjectedState`, and `Command` exactly as `add_items_to_cart` already does, rather than introducing a new matching strategy or state-update mechanism; the optional-quantity shape is the minimum needed to satisfy both clarified behaviors (unqualified = full removal, quantified = partial decrement) without a second tool or a separate "how many would you like to remove" conversational step.
- **IV. Observability & Versioning**: PASS (planned) — no new LLM call site is introduced (the existing `call_model`'s single `bind_tools([...])` call site gains one more bound tool), so the existing LangSmith tracing coverage extends to it automatically; this is a backward-compatible feature addition (MINOR version bump), not a breaking change to `SupportState` or any existing tool's signature.

No violations requiring justification — Complexity Tracking table omitted.

**Post-Phase-1 re-check**: Confirmed against the finished design (`data-model.md`, `contracts/cart-tools.md`). The change is additive only: one new tool function, one new pydantic request model, one new entry in `_ORDER_TOOLS`. `SupportState` is untouched — `menu_items` keeps its existing `dict[str, int]` shape and every existing guarantee in `specs/002-order-support-agent/data-model.md` continues to hold; this feature only adds a new way to shrink or remove entries from it. All four gates still PASS.

## Project Structure

### Documentation (this feature)

```text
specs/003-remove-cart-items/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   └── cart-tools.md
└── tasks.md              # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/customer_support_fde/
├── nodes/
│   └── order_support_agent.py   # _ORDER_TOOLS gains remove_items_to_cart; SYSTEM_PROMPT mentions removal
└── tools/
    └── cart_tools.py             # gains remove_items_from_cart(), CartRemoval, and a result-rendering helper,
                                   # alongside the existing add_items_to_cart()/mark_order_confirmed()

tests/
├── unit/
│   ├── test_cart_tools.py           # existing; gains remove_items_from_cart test cases
│   └── test_order_support_agent.py  # existing; gains an inner-loop remove_items_from_cart tool-call case
└── integration/
    └── test_order_support_trajectory.py  # existing; gains an add-then-remove-then-confirm scenario
```

**Structure Decision**: Single project (Option 1), unchanged from 001/002. No new source directories or modules — this feature only extends `tools/cart_tools.py` (new function) and `nodes/order_support_agent.py` (tool registration + prompt update), with corresponding additions to the three already-existing test files that cover those modules.

## Complexity Tracking

*No Constitution Check violations — table intentionally omitted.*
