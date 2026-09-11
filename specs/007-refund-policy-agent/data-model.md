# Phase 1 Data Model: Refund Policy Agent

**Feature**: `specs/007-refund-policy-agent` | **Date**: 2026-09-11

Covers the three new persisted entities from [spec.md](./spec.md), the in-memory policy
decision, and the `SupportState` fields that carry them through a run. DDL lives in
[contracts/sqlite-schema.sql](./contracts/sqlite-schema.sql).

Existing entities (`menu_items`, `orders`, `order_lines`) are unchanged. This feature reads
orders and never writes them.

---

## Persisted entities

### RefundRequest

A customer's qualifying refund, recorded as pending. Written only by `process_refund_request`,
and only after `refund_policy.evaluate()` returns eligible.

| Field | SQLite type | Constraints | Notes |
|---|---|---|---|
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Internal row id. Not shown to customers — unlike `orders.id`, nobody has to read or retype it, so the human-friendly Crockford base32 scheme is unnecessary here. |
| `order_id` | `TEXT` | `NOT NULL`, `UNIQUE`, FK → `orders(id)` `ON DELETE CASCADE` | `UNIQUE` is the enforcement of FR-011/SC-007 — see the note below. |
| `amount` | `REAL` | `NOT NULL`, `> 0` | Sum of the undelivered lines at order-recorded unit prices (FR-014). |
| `substitute_dishes` | `TEXT` | nullable | JSON array of dish names the customer received instead. `NULL` when nothing arrived (FR-006's waiver case). Names only — never priced (FR-015). |
| `return_confirmed` | `INTEGER` | `NOT NULL`, `0` or `1` | `1` only when a substitute was received and the customer confirmed return. `0` when the waiver applied. |
| `status` | `TEXT` | `NOT NULL`, in (`pending`, `approved`) | Always written as `pending` this phase (FR-013). |
| `created_at` | `TEXT` | `NOT NULL` | UTC ISO-8601 with trailing `Z`, same format `db.record_order` already writes. |

**Why `UNIQUE(order_id)` is exactly FR-011**: a denied refund is never stored as a request — it
becomes a complaint instead. So every row in this table is by definition open (`pending`) or
`approved`, and "at most one row per order" *is* "no second request for an order that already
has an open or approved one."

**Validation rules**:

- `amount` equals the sum of the attached `refund_request_lines.line_total` values, and never
  exceeds the parent order's `total` (SC-008).
- A row MUST have at least one attached line — a refund with no undelivered line has nothing to
  price.
- `return_confirmed = 0` is permitted only when `substitute_dishes IS NULL`. A received
  substitute with no return commitment is a denial (FR-006) and must never reach this table.
- `status` is written as `pending` and never updated by this feature. The `approved` value is
  reserved so a later phase can add approval without reshaping the table (spec Assumptions).

---

### RefundRequestLine

One ordered line the customer paid for but did not receive. Mirrors the shape of the existing
`order_lines` table so the two read the same way.

| Field | SQLite type | Constraints | Notes |
|---|---|---|---|
| `refund_request_id` | `INTEGER` | `NOT NULL`, FK → `refund_requests(id)` `ON DELETE CASCADE`, part of PK | |
| `name` | `TEXT` | `NOT NULL`, part of PK | Copied from `order_lines.name`; must match a line on the parent order. |
| `quantity` | `INTEGER` | `NOT NULL`, `> 0` | Units not received. Clamped to the ordered quantity before insert. |
| `unit_price` | `REAL` | `NOT NULL`, `> 0` | Copied from `order_lines.unit_price` — the price the customer actually paid, not a live menu lookup. |
| `line_total` | `REAL` | `NOT NULL`, `> 0` | `unit_price * quantity`, computed through `Decimal` the way `build_order_summary` already does. |

**Validation rules**:

- `(refund_request_id, name)` is the primary key, so a dish cannot appear twice on one request;
  a customer reporting the same dish twice increases its quantity instead.
- `quantity` MUST NOT exceed the matching `order_lines.quantity` on the parent order. The tool
  clamps rather than rejects, and says so in its reply (research.md Decision 4).
- `name` MUST match a line on the parent order. A name that matches nothing is reported back to
  the agent as unmatched and contributes no amount (FR-015).

---

### Complaint

Customer dissatisfaction, either standalone (US3) or the residue of a denied refund (FR-018).

| Field | SQLite type | Constraints | Notes |
|---|---|---|---|
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Held in `SupportState.complaint_ids` for the life of the conversation so a repeat denial updates rather than inserts. |
| `order_id` | `TEXT` | nullable, FK → `orders(id)` `ON DELETE CASCADE` | `NULL` when the customer identified no order (FR-019). |
| `description` | `TEXT` | `NOT NULL` | The customer's issue in their own terms, as summarized by the agent. |
| `policy_reason` | `TEXT` | nullable | The denial reason code when the complaint came from a refused refund; `NULL` for a standalone complaint. |
| `created_at` | `TEXT` | `NOT NULL` | Never rewritten once set (FR-021). |
| `updated_at` | `TEXT` | `NOT NULL` | Equals `created_at` on insert; advanced each time the row is extended. |

**Validation rules**:

- At most one row per (conversation, order) pairing — enforced in memory via
  `SupportState.complaint_ids`, not by a database constraint (research.md Decision 5).
- Extending a complaint updates `description`, `policy_reason`, and `updated_at` only. A row's
  `created_at` and `id` are immutable (FR-021).
- No uniqueness constraint spans conversations: the same customer complaining about the same
  order in a new conversation correctly gets a new row.

---

## Refund request status lifecycle

```text
          (policy satisfied)
  [none] ────────────────────► pending ─ ─ ─ ─ ─► approved
                                          (out of scope
                                           this phase)
```

- Entry to `pending` is the only transition this feature implements (FR-013).
- `approved` is a reserved value with no code path that writes it. A refund reaching `approved`
  is considered complete and requires no further customer action.
- There is no `denied` state: denials never produce a refund request row at all (FR-010). They
  produce a `Complaint` carrying the denial reason.

---

## In-memory types

### `PolicyDecision` (`src/customer_support_fde/refund_policy.py`)

The return value of the pure evaluation function. Frozen dataclass, no LangChain coupling.

```python
@dataclass(frozen=True)
class PolicyDecision:
    eligible: bool
    reason: str | None       # denial reason code; None when eligible
    message: str             # customer-facing explanation, pre-rendered
```

**Denial reason codes** (`reason`), one per policy condition, so FR-009 and SC-005 can be
verified by asserting on a code rather than on prose:

| Code | Condition | Requirement |
|---|---|---|
| `outside_window` | Order placed more than 48 hours ago | FR-004 |
| `item_delivered` | Problem is with an item that did arrive — quality, temperature, timing, change of mind | FR-005 |
| `return_declined` | A substitute arrived but the customer will not return it | FR-006 |
| `no_undelivered_items` | No line on the order was reported as not received | FR-005, FR-015 |

**Signature note**: `evaluate()` takes the order, the undelivered lines, whether a substitute
was received, whether return was confirmed, and an injected `now`. It takes **no sentiment
argument** — SC-009 holds because there is nothing to pass (FR-027).

---

## `SupportState` additions

Five fields added to `src/customer_support_fde/state.py`. Existing fields are unchanged.

| Field | Type | Initial | Purpose |
|---|---|---|---|
| `order_lookup` | `dict \| None` | `None` | The order retrieved by `lookup_order`, in `db.get_order`'s shape. The only source of truth for pricing a refund (FR-002, FR-014). |
| `refund_resolved` | `bool` | `False` | Set by `conclude_refund_conversation`; routes the loop to the ticket node. |
| `refund_request` | `dict \| None` | `None` | The created request, for the ticket (FR-023). `None` when none was created. |
| `complaint_ids` | `dict[str, int]` | `{}` | Order id (or `""` when none) → complaint row id written this conversation (FR-020, FR-021). |
| `refund_ticket` | `dict \| None` | `None` | The artifact produced by `refund_ticket_node` (FR-023). |

`cli.py` seeds all five when building the initial state, alongside the existing fields.

### Refund ticket shape

Produced by `refund_ticket_node`, mirroring how `ticket_gen_node` builds `order_ticket`:

```python
{
    "order_id":   str | None,    # from order_lookup, None if never identified
    "order":      dict | None,   # the retrieved order (lines, total, created_at)
    "sentiment":  str | None,    # carried from the router (FR-023, tone/triage only)
    "decision":   str | None,    # "eligible" or the denial reason code
    "refund_request": dict | None,
    "complaint_ids":  list[int], # complaints written during this conversation
}
```

---

## Retrieval surface (FR-024)

No staff-facing command ships this phase. Retrieval is a data guarantee, satisfied by three
functions in `db.py` that the test suite exercises directly:

| Function | Returns |
|---|---|
| `get_refund_request_for_order(order_id, path=None)` | The single request for that order with its lines attached, or `None`. Backs the FR-011 duplicate check. |
| `list_refund_requests(path=None)` | All requests, newest first, lines attached. |
| `list_complaints(path=None)` | All complaints, newest first. |

Each follows the existing `db.py` convention: an optional `path` argument resolved through
`_resolve_path`, connections opened via `_connect` and closed in a `finally`, and
`sqlite3.Error` wrapped in `OrderStoreError` with the remediation hint.
