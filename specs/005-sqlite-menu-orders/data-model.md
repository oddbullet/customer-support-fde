# Phase 1 Data Model: SQLite Menu and Order Records

**Feature**: `specs/005-sqlite-menu-orders` | **Date**: 2026-09-11

Covers the three persisted entities from [spec.md](./spec.md) plus the `SupportState` fields that
carry them through a run. DDL lives in [contracts/sqlite-schema.sql](./contracts/sqlite-schema.sql).

---

## Persisted entities

### MenuItem

One dish the restaurant offers. Read-only during a conversation; written only by `--init-db`.

| Field | SQLite type | Constraints | Notes |
|---|---|---|---|
| `name` | `TEXT` | `PRIMARY KEY`, non-empty | Canonical dish name. Also the identity customers and carts refer to. |
| `price` | `REAL` | `NOT NULL`, `> 0` | IEEE-754 double, identical to the value in `menu.json`. |
| `ingredients` | `TEXT` | `NOT NULL` | JSON array of strings, e.g. `["chicken","peanuts"]`. May be an empty array. |

**In-memory shape** (unchanged from today — every existing pure function keeps working):

```python
MenuItem = dict[str, object]   # {"name": str, "price": float, "ingredients": list[str]}
```

**Validation rules**:

- `name` is unique and is the join key to `order_lines.name` and to `SupportState.menu_items` keys
  (FR-004: cart keys are already canonical menu names).
- `ingredients` must deserialize to a `list[str]`; a row whose JSON is malformed makes the whole
  menu load fail (FR-003) rather than yielding a half-formed dish.
- Seeding is an upsert on `name`: re-running `--init-db` updates price and ingredients for existing
  dishes and inserts new ones. It never deletes dishes, so it cannot orphan historical orders.

---

### Order

A confirmed order, written once at confirmation and never updated (spec Assumptions: no amend, no
cancel).

| Field | SQLite type | Constraints | Notes |
|---|---|---|---|
| `id` | `TEXT` | `PRIMARY KEY` | 8 chars from `0123456789ABCDEFGHJKMNPQRSTVWXYZ` (no `I`/`L`/`O`/`U`), stored uppercase and unhyphenated, e.g. `K7QP3M9X`. Random, never reused (FR-006, FR-014, FR-015). |
| `total` | `REAL` | `NOT NULL`, `> 0` | The order total exactly as shown to the customer. |
| `created_at` | `TEXT` | `NOT NULL` | ISO-8601 UTC, e.g. `2026-09-11T18:04:22.511Z`. |

**Validation rules**:

- An Order always has at least one OrderLine — orders are only written for non-empty carts
  (FR-011), and header plus lines are inserted in one transaction (FR-012), so a lineless order can
  never be observed.
- `total` equals the value in `order_summary["total"]`; it is copied, never recomputed (SC-004,
  mirroring the same guarantee `ticket_gen_node` already makes).
- `id` is **stored** canonically (uppercase, no separator) but **displayed** hyphenated in the
  middle — `K7QP-3M9X` — because that is what a customer reads back to the refund agent. Any string
  reaching a lookup passes through `normalize_order_id()` first, which uppercases, strips hyphens
  and spaces, and folds the confusions the alphabet was chosen to make foldable (`O → 0`,
  `I`/`L` → `1`). See [contracts/db-module.md](./contracts/db-module.md).

---

### OrderLine

One dish within an order. Values are captured at order time and never follow later menu changes
(FR-010).

| Field | SQLite type | Constraints | Notes |
|---|---|---|---|
| `order_id` | `TEXT` | `REFERENCES orders(id)`, part of PK | Owning order. |
| `name` | `TEXT` | part of PK, non-empty | Dish name as it stood when ordered. **No** foreign key to `menu_items`. |
| `quantity` | `INTEGER` | `NOT NULL`, `> 0` | |
| `unit_price` | `REAL` | `NOT NULL`, `> 0` | Price charged, frozen at order time. |
| `line_total` | `REAL` | `NOT NULL`, `> 0` | `unit_price × quantity`, copied from the summary. |

**Validation rules**:

- The composite primary key `(order_id, name)` makes "one line per dish" a database invariant,
  matching the `dict[str, int]` cart that produced it.
- `name` deliberately carries **no** foreign key to `menu_items`. This is what makes FR-010 true: a
  dish renamed or deleted from the menu tomorrow leaves every order placed today readable and
  intact.
- `unit_price` and `line_total` are copied from `order_summary["lines"]`, never recalculated
  against the current menu.

---

## Relationships

```text
menu_items                 orders 1 ──── N order_lines
    │                                          │
    └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┘
      by name only, at order time — no FK, intentionally
      (a recorded order must outlive menu edits)
```

- `orders` → `order_lines`: one-to-many, `ON DELETE CASCADE`. Orders are never deleted in normal
  operation; the cascade exists so a manual cleanup cannot leave dangling lines.
- `menu_items` → `order_lines`: **not** enforced. See FR-010 above.

---

## SupportState changes

`src/customer_support_fde/state.py` gains two fields:

| Field | Type | Written by | Purpose |
|---|---|---|---|
| `menu` | `list[MenuItem]` | The caller, in the initial state dict, once per run | The single menu snapshot every tool and the summary node read (FR-002). |
| `order_id` | `str \| None` | `cart_summary_node` | The recorded order's ID; `None` until an order is written, and for any run that never confirms (FR-007, FR-011). |

Full state after this feature:

```python
class SupportState(TypedDict):
    user_query: str
    destination: Literal["order_support", "refund", "unclear"]
    sentiment: Literal["positive", "neutral", "negative"] | None
    messages: Annotated[list[AnyMessage], add_messages]
    menu: list[MenuItem]          # NEW
    menu_items: dict[str, int]
    order_confirmed: bool
    order_ticket: dict | None
    order_summary: dict | None
    order_id: str | None          # NEW
```

**State transitions for `order_id`**:

```text
None ──(cart_summary_node, cart non-empty, write succeeds)──> "K7QP3M9X"  [terminal]
None ──(cart_summary_node, cart empty)────────────────────── > None       [no order written]
None ──(write fails: OrderStoreError propagates)───────────── > (run aborts, no state update)
```

`order_id` on the state and in `order_ticket` always holds the canonical stored form; only the
rendered customer message hyphenates it.

---

## Derived shapes

**`order_summary`** — unchanged in structure; it is the source the order record is copied from:

```python
{"lines": [{"name": str, "quantity": int, "unit_price": float, "line_total": float}, ...],
 "total": float | None}
```

**`order_ticket`** — gains `order_id` (FR-008):

```python
{"order_id": str | None, "items": dict[str, int], "lines": [...], "total": float | None}
```

`ticket_gen_node` copies `order_id` off the state alongside the lines and total it already copies,
keeping ticket, customer-facing summary, and stored order in agreement by construction.
