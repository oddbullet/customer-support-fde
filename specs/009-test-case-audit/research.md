# Phase 0 Research: Test Case Audit & Coverage Rationalization

No `[NEEDS CLARIFICATION]` markers remain in the spec (all resolved during `/speckit-clarify`
on 2026-09-12). The research below grounds the Technical Context in the actual repository
state and settles the remaining "how do we do this" questions before design.

## Decision 1: How to establish the canonical test-case inventory (FR-001)

**Decision**: Use `pytest --collect-only -q` as the authoritative enumeration of test cases.
Running it against the current suite returns **183 collected tests** — each parametrized
instance listed on its own line (e.g.,
`test_refund_sentiment_is_always_one_of_the_three_fixed_categories[positive]`), which
matches the spec's Assumption that a parametrized instance, not the enclosing function, is
the unit of audit.

**Rationale**: A tooling-verified list removes ambiguity about what counts as "one test
case" and gives an exact, reproducible baseline number to compare against post-audit
(SC-003). Manually counting `def test_*` occurrences (174 in this repo) undercounts because
it doesn't expand `@pytest.mark.parametrize`.

**Alternatives considered**:
- *Manual grep of `def test_*` only* — rejected: undercounts parametrized suites, already
  known to diverge from the true 183.
- *Coverage.py branch/line coverage report* — rejected: measures code coverage, not test
  redundancy or category (base/edge); doesn't identify which tests duplicate each other.

## Decision 2: Exact scope of "tool" and "node" for the FR-002 coverage guarantee

**Decision**: The in-scope set is exactly:

- **10 tools** (`@tool`-decorated functions): `add_items_to_cart`, `remove_items_from_cart`,
  `mark_order_confirmed`, `get_cart_total` (`tools/cart_tools.py`); `get_menu`,
  `get_menu_item` (`tools/menu_tools.py`); `lookup_order`, `process_refund_request`,
  `log_complaint`, `conclude_refund_conversation` (`tools/refund_tools.py`).
- **9 nodes** (hand-written functions registered in `graph.py` via `add_node`):
  `router_agent`, `clarify_intent`, `call_model`, `await_customer`, `cart_summary_node`,
  `ticket_gen_node`, `refund_agent`, `refund_await_customer`, `refund_ticket_node`.

Excluded: the `order_tools` and `refund_tools` graph nodes are `langgraph.prebuilt.ToolNode`
instances (framework-provided dispatchers with no author-written branching logic) — their
behavior is fully a function of the already-scoped tool functions, so they don't need
independent base/edge tests.

**Rationale**: Matches the clarified spec boundary exactly and avoids busywork testing a
framework passthrough that has no custom logic to exercise.

**Alternatives considered**:
- *Include `order_tools`/`refund_tools` as nodes requiring their own tests* — rejected per
  the clarification session; confirmed by reading `graph.py` and `order_support_agent.py` /
  `refund_agent.py`, which show they're `ToolNode(_ORDER_TOOLS)` / `ToolNode(_REFUND_TOOLS)`,
  not custom functions.

## Decision 3: Verifying category-comment compliance (FR-007 / SC-006)

**Decision**: A file-level grep for `(base)`/`(edge)`/`(error)`/`(regression)` shows all 14
test files already contain at least one tagged comment (the constitution's Principle I
requirement predates this feature). The audit must still check **per test case**, not per
file — a file having one tagged test doesn't mean every test in it is tagged. This
per-test check is folded into the same pass that builds the FR-001 inventory.

**Rationale**: Avoids a false-positive "already compliant" conclusion from a coarse
file-level signal.

**Alternatives considered**: Trusting the file-level grep as sufficient — rejected as too
imprecise to certify SC-006 at 100%.

## Decision 4: No `contracts/` artifact

**Decision**: Skip the Phase 1 contracts output entirely.

**Rationale**: This feature has no external interface — it adds no CLI flag, no API, no
schema. Its only outputs are edited test files and one internal markdown record
(`audit-record.md`), which is documented directly in `data-model.md` instead.

**Alternatives considered**: Defining a "schema" for `audit-record.md` as a pseudo-contract
— rejected as unnecessary ceremony for an internal markdown report; `data-model.md`'s
Audit Record entity definition already captures its required structure.

## Decision 5: Baseline capture method for SC-003 / SC-007

**Decision**: Before making any changes, record in `audit-record.md`:
1. Total collected test count: `pytest --collect-only -q` → last line (`183 tests collected`).
2. Full-suite wall-clock time: `pytest -q` run once, noting the reported duration.

Re-run both after the audit's changes are applied and compare.

**Rationale**: Gives an objective, reproducible way to verify "test count is no higher than
before" (SC-003) and "same or better run time" (SC-007) without relying on impression.

**Alternatives considered**: Only comparing test counts without timing — rejected because
SC-007 explicitly requires a run-time comparison, not just a count comparison.

**Output**: All unknowns resolved; ready for Phase 1 design.
