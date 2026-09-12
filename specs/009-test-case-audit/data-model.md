# Phase 1 Data Model: Test Case Audit & Coverage Rationalization

This feature's "data" is the audit's bookkeeping, not application/runtime data — there is
no new database schema or persisted application state. The entities below describe the
structure of the working inventory the audit builds and the `audit-record.md` artifact it
produces (FR-009).

## TestCase

An individual executable pytest test — one plain test function, or one instance of a
parametrized test (per Research Decision 1, each `pytest --collect-only` line is one
`TestCase`).

| Field | Type | Notes |
|---|---|---|
| `id` | string | Full pytest node id, e.g. `tests/unit/test_router_agent.py::test_refund_sentiment_is_always_one_of_the_three_fixed_categories[positive]` |
| `target` | ref → ToolOrNode \| module name | What this test exercises. Not every test targets an in-scope ToolOrNode (e.g., `test_db.py` targets `db.py`) |
| `category` | enum: `base` \| `edge` \| `error` \| `regression` \| `other` | Read from the constitution-mandated one-line comment above the test (FR-007); `other` if a comment exists but doesn't match the four canonical tags |
| `has_category_comment` | boolean | Whether the required tag comment is present at all (drives SC-006) |
| `status` | enum: `kept` \| `removed` \| `added` | Audit outcome for this test case |
| `superseded_by` | ref → TestCase (nullable) | Set only when `status = removed`; points at the retained `TestCase` whose coverage makes this one redundant (FR-004, FR-005 guardrail) |
| `gap_closed` | string (nullable) | Set only when `status = added`; one-line description of the base/edge gap this test closes (FR-003) |

**Validation rules**:
- A `TestCase` with `status = removed` MUST have a non-null `superseded_by`, and that
  referenced test MUST itself have `status = kept` (FR-004/FR-005 — never remove a test in
  favor of one that's also being removed).
- A `TestCase` with `status = added` MUST have `category` of `base` or `edge` (FR-003 only
  requires filling base/edge gaps) and a non-null `gap_closed`.
- Every `TestCase` with `status` in `{kept, added}` MUST have `has_category_comment = true`
  by the end of the audit (SC-006).
- Removing a `TestCase` MUST NOT change the `category`/behavior coverage represented by any
  other `TestCase` still marked `kept` (FR-008 — no incidental edits to retained assertions).

## ToolOrNode

A unit of system behavior in the FR-002 coverage scope: one of the 10 `@tool`-decorated
functions or 9 hand-written graph node functions enumerated in Research Decision 2.

| Field | Type | Notes |
|---|---|---|
| `name` | string | Function name, e.g. `add_items_to_cart`, `router_agent` |
| `kind` | enum: `tool` \| `node` | |
| `module` | string | Owning file, e.g. `src/customer_support_fde/tools/cart_tools.py` |
| `has_base_test` | boolean | True iff at least one `TestCase` with `category = base`, `status ∈ {kept, added}` targets it |
| `has_edge_test` | boolean | True iff at least one `TestCase` with `category = edge`, `status ∈ {kept, added}` targets it |

**Validation rule**: By the end of the audit, every `ToolOrNode` MUST have
`has_base_test = true` AND `has_edge_test = true` (FR-002, SC-001). This is the row-level
check that drives the coverage matrix in `audit-record.md`.

## AuditRecord

The single output artifact of this feature (FR-009), checked in at
`specs/009-test-case-audit/audit-record.md`.

| Field | Type | Notes |
|---|---|---|
| `baseline_test_count` | integer | `pytest --collect-only -q` count before any changes (Research Decision 5) — 183 as of this plan |
| `baseline_runtime` | duration | `pytest -q` wall-clock time before any changes |
| `final_test_count` | integer | Same measurement after the audit's edits are applied |
| `final_runtime` | duration | Same measurement after the audit's edits are applied |
| `coverage_matrix` | list of ToolOrNode rows | Every in-scope tool/node with its final `has_base_test` / `has_edge_test` |
| `removed` | list of TestCase (status=removed) | Each with `id`, `superseded_by`, and a one-line rationale |
| `added` | list of TestCase (status=added) | Each with `id`, `category`, and `gap_closed` |

**Validation rules**:
- `final_test_count <= baseline_test_count` (SC-003).
- `final_runtime <= baseline_runtime`, or a documented explanation if not (SC-007).
- Every row in `coverage_matrix` has both boolean columns `true` (SC-001).
- Every entry in `removed` and `added` must be traceable back to a `TestCase` recorded
  during the audit (SC-004 — a reader can verify without the raw diff).

## State transitions (TestCase.status)

```
 (exists in baseline inventory) ──┬──> kept     [default; no change needed]
                                  └──> removed  [confirmed redundant; superseded_by set]

 (does not exist in baseline) ────────> added   [created to close a base/edge gap; gap_closed set]
```

There is no transition back from `removed` or `added` within a single audit pass — each
`TestCase` id resolves to exactly one terminal `status`.
