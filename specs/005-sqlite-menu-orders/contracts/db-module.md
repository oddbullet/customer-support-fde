# Contract: `customer_support_fde.db`

**Feature**: `specs/005-sqlite-menu-orders`

The single module that owns SQLite. Nothing outside it imports `sqlite3`. Every function is a plain
importable function taking ordinary Python values — no LangGraph types (Principle II).

---

## Path resolution

```python
DEFAULT_DB_FILENAME = "customer_support.db"

def database_path() -> Path
```

Returns `Path(os.environ["CUSTOMER_SUPPORT_DB"])` when that variable is set and non-empty,
otherwise `Path(DEFAULT_DB_FILENAME)` relative to the working directory. Read at call time, not at
import time, so tests and `.env` can both steer it.

---

## Errors

```python
class MenuStoreError(RuntimeError)    # raised by load_menu
class OrderStoreError(RuntimeError)   # raised by record_order
```

Both messages name the database path and state the remedy, e.g.:

```text
Menu database not found at 'customer_support.db'. Run: customer-support-fde --init-db
```

---

## Reading the menu

```python
def load_menu(path: Path | str | None = None) -> list[MenuItem]
```

Opens the database, reads every row of `menu_items`, and returns them as the dict shape the rest of
the codebase already uses — `{"name": str, "price": float, "ingredients": list[str]}` — with
`ingredients` deserialized from its JSON column. `path` defaults to `database_path()`.

**Guarantees**:

- Called exactly once per support run, by the caller building the initial graph state (FR-002).
- Returns `[]` when the table exists but is empty — the menu tools then render their existing
  "no items available" text (edge case: empty store).
- Raises `MenuStoreError` when the file does not exist, cannot be opened, lacks a `menu_items`
  table, or holds a row whose `ingredients` JSON will not parse (FR-003). It never returns a
  partial menu.
- Ordering is stable: rows come back ordered by `name`.

---

## Writing an order

```python
def record_order(summary: dict, path: Path | str | None = None) -> str
```

Takes an `order_summary` (`{"lines": [...], "total": float}` — see
[data-model.md](../data-model.md)), writes it as one `orders` row plus one `order_lines` row per
line, and returns the new order ID.

**Guarantees**:

- Generates an 8-character code via `secrets.choice` over
  `0123456789ABCDEFGHJKMNPQRSTVWXYZ` and returns it in canonical form — uppercase, no separator
  (FR-006, FR-007, FR-014, FR-015).
- On a primary-key `IntegrityError` it discards the code, generates another, and retries, up to 5
  attempts, then raises `OrderStoreError`. Each attempt is its own transaction, so a rejected
  attempt leaves nothing behind.
- Writes header and all lines inside a single transaction: on any failure nothing is committed and
  `OrderStoreError` is raised (FR-012).
- Copies `name`, `quantity`, `unit_price`, `line_total`, and `total` verbatim from `summary` — no
  value is recomputed against the current menu (FR-010, SC-004).
- Raises `ValueError` if `summary` has no lines — `record_order` is never called for an empty cart,
  and calling it anyway is a programming error, not a customer-facing one (FR-011).
- Stamps `created_at` with the current UTC time in ISO-8601.

---

## Order ID handling

```python
ID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"   # Crockford base32: no I, L, O, U
ID_LENGTH = 8

def format_order_id(order_id: str) -> str     # "K7QP3M9X" -> "K7QP-3M9X"
def normalize_order_id(raw: str) -> str       # anything a customer types -> "K7QP3M9X"
```

`format_order_id` inserts the display hyphen and is used wherever a customer sees the code.

`normalize_order_id` is the inverse and is deliberately forgiving (FR-014, SC-008): it strips
surrounding whitespace, uppercases, removes hyphens and spaces, and folds the confusions the
alphabet was chosen to make foldable — `O → 0`, `I → 1`, `L → 1`. It does **not** validate; an
unrecognizable string simply normalizes to something no row matches, and `get_order` returns `None`.

These two are the seam the refund agent will sit on: it can accept whatever a customer says and
hand it straight to `get_order`.

---

## Reading an order back

```python
def get_order(order_id: str, path: Path | str | None = None) -> dict | None
```

Returns `{"order_id": str, "total": float, "created_at": str, "lines": [...]}` where `lines` has
the same four-key shape as `order_summary["lines"]`, or `None` when no such order exists. The
returned `order_id` is the canonical stored form.

Applies `normalize_order_id` to its argument, so `get_order("k7qp-3m9x")` and
`get_order("K7QP3M9X")` are the same call.

Not called by the graph. It exists so staff (and the SC-004/SC-005/SC-008 tests) can verify what was
stored, and it is what the refund agent's lookup will build on.

---

## Initialization

```python
def init_database(path: Path | str | None = None) -> int
```

Creates the file if absent, applies the schema from
[sqlite-schema.sql](./sqlite-schema.sql), upserts every dish from
`customer_support_fde/menu/menu.json`, and returns the number of dishes seeded.

**Guarantees**:

- Idempotent — safe to re-run; updates prices and ingredients of existing dishes, inserts new ones,
  deletes nothing (FR-013).
- The only code path in the project that reads `menu.json` (FR-001).

---

## Contract tests

| Test | Asserts | Category |
|---|---|---|
| `init_database` on a fresh path creates all three tables and seeds every dish from `menu.json` | FR-013 | base |
| `init_database` run twice leaves the same dish count and no duplicates | idempotence | edge |
| `load_menu` returns dishes with the exact names, prices, and ingredient lists in `menu.json` | FR-013, SC-001 | base |
| A price edited directly in the database is reflected by the next `load_menu` | SC-002 | base |
| `load_menu` against a missing file raises `MenuStoreError` naming the path | FR-003 | error |
| `load_menu` against a file with no `menu_items` table raises `MenuStoreError` | FR-003 | error |
| `load_menu` on a seeded-then-emptied table returns `[]` | empty store | edge |
| `record_order` returns an 8-char ID and `get_order` round-trips every line field | FR-005, SC-004 | base |
| Two `record_order` calls return different IDs and both orders remain readable | FR-006, SC-006 | base |
| Every generated ID uses only `ID_ALPHABET` — never `I`, `L`, `O`, or `U` | FR-014 | base |
| 1,000 generated IDs are all distinct and show no sequential pattern | FR-015 | base |
| `get_order` finds an order from its lowercase, hyphenated, and spaced forms | FR-014, SC-008 | edge |
| `get_order` finds an order when `O`/`I`/`L` are typed for `0`/`1`/`1` | FR-014, SC-008 | edge |
| `get_order` on an unrecognizable string returns `None` rather than raising | FR-014 | edge |
| `format_order_id` hyphenates mid-code and `normalize_order_id` inverts it exactly | FR-014 | base |
| A forced ID collision is retried onto a fresh ID and the order still saves | FR-006 | error |
| A failure partway through `record_order` leaves no `orders` row and no `order_lines` rows | FR-012 | error |
| An order written, connection closed, database reopened, still reads back identically | FR-009, SC-005 | base |
| Editing `menu_items` after an order does not change that order's stored names or prices | FR-010 | regression |
| `record_order` with an empty `lines` list raises `ValueError` and writes nothing | FR-011 | error |
