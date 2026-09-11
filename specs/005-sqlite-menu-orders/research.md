# Phase 0 Research: SQLite Menu and Order Records

**Feature**: `specs/005-sqlite-menu-orders` | **Date**: 2026-09-11

All Technical Context unknowns are resolved below. No `NEEDS CLARIFICATION` markers remain.

---

## 1. How the menu reaches the tools, loaded once per run

**Decision**: The caller loads the menu and seeds it into the **initial graph state**. `cli.py`
calls `db.load_menu()` once while building the input dict for `graph.invoke()`, putting it on
`SupportState` as `menu: list[MenuItem]`. `get_menu`, `get_menu_item`, `add_items_to_cart`,
`remove_items_from_cart`, and `cart_summary_node` all read `state["menu"]` instead of calling
`_load_menu()`. **`graph.py` does not change** — no new node, no entry-point move.

**Rationale**:

- FR-002 asks for exactly one read per support run, and the initial state is constructed exactly
  once per run. Resumes go through `Command(resume=...)`, which continues from the checkpoint and
  never re-applies the input dict.
- The snapshot must survive `await_customer`'s `interrupt`, and it does: state is checkpointed.
  The existing code already proves this — `menu_items` is seeded in the initial state the same way
  and the cart accumulates correctly across interrupts today. `menu` rides the same mechanism, so
  US3 (a price quoted before the pause is the price charged after it) holds for the same reason the
  cart does.
- It fails before the graph starts. A missing or unseeded database aborts with no LLM call made and
  no half-started thread checkpointed — a strictly better failure mode than starting the run and
  dying inside it.
- The tools already consume `SupportState` through `InjectedState` (`cart_tools.py`), so reading
  `state["menu"]` is the pattern the codebase already uses, not a new one.
- `InjectedState` parameters are stripped from the schema the model sees, so `get_menu` and
  `get_menu_item` keep the exact tool signatures the LLM is prompted against today. FR-004 costs
  nothing.

**Alternatives considered**:

| Alternative | Rejected because |
|---|---|
| A `load_menu` entry node that reads the DB onto the state | Buys two things — a caller physically cannot forget to load the menu, and `MenuStoreError` lands on the LangSmith trace. Neither pays for itself: the project has exactly one caller (`cli.py`), so "future callers need not know how loading works" is the hypothetical-need abstraction Principle III forbids, and a missing database is a startup/config error that belongs on stderr, not in an agent trace. It also costs a new module, a new test file, an entry-point change, and a leading `load_menu` entry in every trajectory assertion across both integration suites. |
| Keep `@lru_cache(maxsize=1)` on a SQLite-backed `_load_menu()` | Caches for the life of the *process*, not the run. Two conversations in one process would never see a staff price edit between them, contradicting SC-002 and the spec's assumption that "once at the start of the graph run" means per run. |
| Query SQLite inside each tool call | One connection and query per menu question; a mid-conversation price edit would split a single conversation across two price regimes, breaking US3/SC-007. |
| LangGraph runtime context (`context_schema` + `get_runtime()`) | Context is supplied per `invoke` and is not checkpointed, so every `Command(resume=...)` after an `interrupt` would have to re-supply it — reintroducing the mid-run inconsistency this feature exists to prevent. |

**Costs accepted**:

- The menu is serialized into every checkpoint. At six rows of short strings this is negligible, and
  it buys the run-consistency guarantee outright.
- Any caller building an initial state by hand must include `menu`. That is `cli.py` and the
  integration tests — and for the tests it is a simplification, since seeding one key replaces the
  `monkeypatch.setattr(..., "_load_menu", ...)` patches they use today. A missing key surfaces as a
  loud `KeyError` on `state["menu"]`, not as silent wrong behavior.

---

## 2. Database driver

**Decision**: Python's stdlib `sqlite3`. No new dependency.

**Rationale**: The constitution's Technology Constraints require that dependencies not be added
when the standard library covers the need. `sqlite3` covers all of it: file-backed storage,
transactions, and parameterized queries. Rows are converted to plain `dict`s via a small helper so
the menu keeps the `{"name", "price", "ingredients"}` shape every existing pure function already
expects.

**Alternatives considered**: SQLAlchemy or any ORM — rejected outright under Principle III for a
three-table schema with five queries; `aiosqlite` — rejected, the graph is synchronous throughout.

---

## 3. Schema shape

**Decision**: Three tables — `menu_items`, `orders`, `order_lines`. Full DDL in
[contracts/sqlite-schema.sql](./contracts/sqlite-schema.sql).

**Prices stored as `REAL`**: SQLite `REAL` is an IEEE-754 double, the same type Python `float`
already uses, so every price in `menu.json` round-trips bit-identically and FR-013 ("prices
unchanged on the first run after migration") holds by construction. `build_order_summary` already
wraps each price in `Decimal(str(...))` before arithmetic, so the money path is unchanged.

- *Integer cents rejected*: it would change `build_order_summary`'s arithmetic and invalidate the
  existing always-rounds-up regression test, for no benefit the `Decimal` conversion does not
  already provide.

**Ingredients stored as a JSON array in a `TEXT` column**: ingredients are only ever read as a
whole list and rendered joined with `", "`. Nothing queries, filters, or joins on an individual
ingredient.

- *An `ingredients` junction table rejected*: it is the textbook normalization, but it is
  speculative structure for a query nobody makes today (Principle III). If ingredient-level allergy
  search is ever specified, migrating then is a contained change behind `load_menu()`.

**`order_lines` keyed by `(order_id, name)`**: the cart is a `dict[str, int]`, so a dish can appear
at most once per order. The composite primary key makes the "repeat additions consolidate into one
line" guarantee a database invariant rather than a convention.

**`created_at` on `orders`**: ISO-8601 UTC text. Needed for the Order entity's "time it was placed"
and for staff to make any sense of a list of orders; costs one column.

---

## 4. Order ID format

**Decision**: An 8-character random code drawn from a 32-character confusion-free alphabet, stored
uppercase and unhyphenated as the `orders.id` `TEXT PRIMARY KEY`, displayed hyphenated in the
middle.

```python
_ID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"   # Crockford base32: no I, L, O, U
_ID_LENGTH = 8
# stored: "K7QP3M9X"        displayed: "K7QP-3M9X"
```

Generated with `secrets.choice`, not `random`, because the ID functions as a bearer token (see the
enumeration argument below).

**Rationale**: The driving constraint is that a customer reads this code aloud or types it back to
the refund agent (FR-014). That makes three properties necessary:

- **Short enough to transcribe.** Eight characters in two four-character groups is about the limit
  of what someone repeats accurately from a screen or over a phone.
- **No ambiguous characters.** Removing `I`, `L`, `O`, and `U` means no character a customer
  mishears or mistypes can land on a *different valid* code. It also makes the common confusions
  mechanically correctable: `normalize_order_id()` maps `O → 0` and `I`/`L` → `1`, uppercases, and
  strips hyphens and spaces, so a customer who types `k7qp-3m9x` or says "oh" for zero still gets
  their order. (`U` is dropped as well, which keeps accidental profanity out of generated codes.)
- **Not guessable.** The refund agent is an unauthenticated conversational surface: the order ID is
  the only evidence a customer owns the order they are asking to refund. 32⁸ ≈ 1.1 × 10¹² makes
  guessing infeasible.

**Collision handling**: 8 characters is short enough that collisions are not theoretical — at
~100,000 lifetime orders the birthday probability is roughly 0.45%, and a collision would mean a
customer's order fails to save. `record_order` therefore catches the primary-key `IntegrityError`,
generates a fresh code, and retries up to 5 times before raising `OrderStoreError`. Each attempt is
its own transaction, so a rejected attempt leaves nothing behind. This is ~5 lines and is cheaper
than padding the code to 10 characters, which would degrade the ergonomics that motivated the change.

**Alternatives considered**:

| Alternative | Rejected because |
|---|---|
| `uuid.uuid4().hex` (the earlier choice) | 32 characters of undifferentiated hex. Unique and collision-free, but nobody reads it aloud correctly, which defeats the refund handoff this ID exists to serve. |
| `INTEGER PRIMARY KEY AUTOINCREMENT` ("order 47") | The simplest and most readable option, but sequential IDs are enumerable: on an unauthenticated refund surface, "refund order 46" would hand a stranger's order to whoever asks. Also collides outright if two database files are ever merged. |
| Date-prefixed sequence (`20260911-014`) | Readable and sorts nicely, but enumerable within a day — same objection as above — and leaks order volume. |
| 10+ random characters, no retry | Trades the ergonomics that motivated the whole change for ~5 lines of retry logic. Worse on the axis that matters. |
| Random code plus a check digit | Catches single-character typos without a round-trip, but the database already detects a bad code by finding no row. Extra machinery for no reachable benefit (Principle III). |

---

## 5. Write atomicity

**Decision**: Insert the `orders` row and all `order_lines` rows inside one `with conn:` block,
with `PRAGMA foreign_keys = ON` set on every connection.

**Rationale**: `with conn:` commits on clean exit and rolls back on any exception, which is exactly
FR-012 — a failure mid-write leaves no order header without its lines. The foreign key from
`order_lines.order_id` to `orders.id` enforces the same invariant from the schema side. Because the
exception propagates out of `cart_summary_node`, the node returns nothing, no `AIMessage` claiming
success is appended, and no `order_id` reaches the state — the customer is never handed an ID for
an order that was not written.

---

## 6. Connection lifecycle

**Decision**: Open a short-lived connection per operation — one in `load_menu`, one in
`cart_summary_node` — rather than holding a single connection open for the run.

**Rationale**: A `sqlite3.Connection` is not JSON-serializable, so it cannot live on the
checkpointed state; and connections default to `check_same_thread=True`, while LangGraph is free to
run nodes on different threads. Opening a SQLite file is microseconds, and each run does exactly
two operations. A shared connection would buy nothing and introduce a real threading hazard.

---

## 7. Database location and initialization

**Decision**: Path from the `CUSTOMER_SUPPORT_DB` environment variable (already loaded via the
project's existing `dotenv` call), defaulting to `customer_support.db` in the working directory.
Schema creation and menu seeding happen through a new `customer-support-fde --init-db` CLI flag,
which is idempotent (`CREATE TABLE IF NOT EXISTS` plus an upsert of every seed row).

**Rationale**: Principle II requires that anything a human needs to invoke directly be reachable
from the CLI; creating and seeding the database is exactly that. Keeping it an explicit command
rather than an implicit side effect of the first conversation is what makes FR-003 enforceable — a
run against a missing or unseeded database fails loudly and tells the operator to run `--init-db`,
instead of silently creating an empty menu and telling customers the restaurant has no food.

`src/customer_support_fde/menu/menu.json` is retained as the seed source read only by `--init-db`,
resolving the open question the spec left to planning. Nothing in a conversation reads it, which is
FR-001.

**Alternatives considered**: auto-create-and-seed on first connect — rejected per the FR-003
reasoning above; a fixed path inside the installed package — rejected, it writes customer order data
into `site-packages` and breaks on a read-only install.

---

## 8. Error surface

**Decision**: Two exception types in the db module — `MenuStoreError` (raised by `load_menu` when
the database file is missing, unreadable, or has no `menu_items` table) and `OrderStoreError`
(raised by `record_order` when the write fails). Both carry the database path and a remedy in the
message. `cli.py` already wraps `graph.invoke` in `try/except Exception` and prints `Error: {exc}`
to stderr with exit code 1, so both surface correctly with no CLI change beyond the message text.

**Rationale**: FR-003 and FR-012 both require a clear, actionable failure rather than a degraded
run. Distinct types let tests assert the read path and the write path separately, and let a future
caller treat "menu unavailable" differently from "order not saved" without string-matching.

---

## 9. Test strategy

**Decision**: Unit tests build a real temporary SQLite database on pytest's `tmp_path` and exercise
the db module against it; node and tool tests pass a plain `SAMPLE_MENU` list on the state dict and
never touch SQLite at all.

**Rationale**: The db module is where SQLite behavior lives and deserves real-database coverage
(seeding, uniqueness, atomic rollback, retrieval after reconnect, survival across a reconnect for
SC-005). Everywhere else, moving the menu onto the state actually *removes* test machinery: the
`monkeypatch.setattr(..., "_load_menu", lambda: SAMPLE_MENU)` patches in `test_cart_tools.py`,
`test_cart_summary_and_ticket_nodes.py`, and `test_order_support_trajectory.py` all disappear in
favor of a `menu` key in the state fixture.

**Alternatives considered**: `:memory:` databases — used for pure-logic cases, but SC-005
explicitly requires that an order survive a restart, which only a file-backed database can
demonstrate; mocking `sqlite3` — rejected, it would test the mock rather than the schema.
