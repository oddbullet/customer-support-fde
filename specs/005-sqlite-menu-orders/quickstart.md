# Quickstart: SQLite Menu and Order Records

**Feature**: `specs/005-sqlite-menu-orders`

End-to-end validation that the feature works. Run these after implementation; each scenario maps to
the success criteria in [spec.md](./spec.md). Details of function signatures and schema live in
[contracts/](./contracts/) — not repeated here.

## Prerequisites

```powershell
uv sync
```

No new dependency — `sqlite3` is stdlib. `OPENROUTER_API_KEY` in `.env` is required only for the
conversation scenarios (3, 4, 6); the database scenarios need no model access.

---

## 1. Initialize the database (FR-013)

```powershell
uv run customer-support-fde --init-db
```

**Expected**: `Initialized customer_support.db with 6 menu items.`, exit code 0, and a
`customer_support.db` file in the working directory.

Re-run it. **Expected**: the same line, still 6 items — seeding is idempotent, not additive.

Inspect what landed:

```powershell
uv run python -c "from customer_support_fde import db; [print(i['name'], i['price'], i['ingredients']) for i in db.load_menu()]"
```

**Expected**: all six dishes with exactly the prices and ingredient lists from
`src/customer_support_fde/menu/menu.json`.

---

## 2. Menu answers come from the database, not the file (SC-001, SC-002)

Change a price in the database only, leaving `menu.json` untouched:

```powershell
uv run python -c "import sqlite3; c=sqlite3.connect('customer_support.db'); c.execute(\"UPDATE menu_items SET price=99.99 WHERE name='Mapo Tofu'\"); c.commit()"
uv run python -c "from customer_support_fde import db; print([i for i in db.load_menu() if i['name']=='Mapo Tofu'])"
```

**Expected**: `99.99`. The menu is being read from SQLite. Put it back with `--init-db`, which
re-upserts the seed values.

---

## 3. A conversation quotes database prices (SC-001, FR-004)

```powershell
uv run customer-support-fde "what's on the menu?"
```

**Expected**: every dish, price, and ingredient list in the reply matches the `menu_items` table.
Then check that matching behavior is unchanged — ask for a dish by a partial name (`"do you have
mapo?"`) and get a direct answer, and by an ambiguous one to get the "which one did you mean"
prompt.

---

## 4. Confirming an order records it and returns an ID (SC-003, SC-004)

```powershell
uv run customer-support-fde --json "I'd like two kung pao chicken and a hot and sour soup"
```

Answer the follow-up prompts until you confirm ("that's all").

**Expected**: the printed summary ends with an `Order ID:` line, and the `--json` payload carries
both `order_summary` and an 8-character `order_id` (the JSON carries the canonical unhyphenated
form; the printed line hyphenates it).

Verify the stored record matches what you were shown:

```powershell
uv run python -c "from customer_support_fde import db; print(db.get_order('<paste id>'))"
```

**Expected**: same dishes, same quantities, same unit prices, same line totals, same total — zero
discrepancies against the printed summary.

---

## 5. Orders survive a restart and outlive menu edits (SC-005, FR-010)

Using the ID from scenario 4, in a brand-new process:

```powershell
uv run python -c "from customer_support_fde import db; print(db.get_order('<paste id>'))"
```

**Expected**: identical contents — the process that wrote it is long gone.

Now change that dish's price in the database and read the order again.

**Expected**: the order still shows the price it was placed at, not the new one.

---

## 6. A missing database fails loudly (FR-003)

```powershell
$env:CUSTOMER_SUPPORT_DB="nope.db"; uv run customer-support-fde "what's on the menu?"
```

**Expected**: exit code 1 and a stderr line naming the missing path and telling you to run
`--init-db`, produced *before* the graph starts — so no model call is made and no thread is
checkpointed. **Not** expected: a conversation that starts and tells the customer the restaurant has
no menu.

```powershell
Remove-Item Env:CUSTOMER_SUPPORT_DB
```

---

## 7. Empty cart writes nothing (FR-011)

Ask to confirm without adding anything ("that's my whole order").

**Expected**: the existing "nothing in the cart yet to confirm" reply, no `Order ID` line, `null`
`order_id` in `--json`, and no new row in `orders`:

```powershell
uv run python -c "import sqlite3; print(sqlite3.connect('customer_support.db').execute('SELECT COUNT(*) FROM orders').fetchone())"
```

---

## 8. Test suite

```powershell
uv run pytest
```

**Expected**: green. New `tests/unit/test_db.py` covers every row of the contract-test table in
[contracts/db-module.md](./contracts/db-module.md) against a real temporary database; the existing
node, tool, and trajectory suites pass with their `_load_menu` patches replaced by a `menu` key on
the state fixture, and with their expected node trajectories unchanged.
