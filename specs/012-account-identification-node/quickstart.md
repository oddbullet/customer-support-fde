# Quickstart: Validate the Customer Account Identification Node

Runnable validation for [spec.md](./spec.md).

## Prerequisites

- Working tree on branch `012-account-identification-node` with the feature implemented per
  [plan.md](./plan.md) and `tasks.md`.
- Dependencies installed (`uv sync` or equivalent per `pyproject.toml`).
- `OPENROUTER_API_KEY` set — needed only for the manual and trajectory scenarios (the order/
  support agent still uses the model to converse), not for the unit suite.

## 1. Initialize the database

```powershell
customer-support-fde --init-db
```

Idempotent. On an existing database this is the step that creates the `accounts` table from
[contracts/sqlite-schema.sql](./contracts/sqlite-schema.sql) — **re-run it even if you have a
database already**, or account creation/lookup will fail with a missing-table error.

Confirm the table exists:

```powershell
python -c "import sqlite3; print(sorted(r[0] for r in sqlite3.connect('customer_support.db').execute(\"SELECT name FROM sqlite_master WHERE type='table'\")))"
```

Expected to include `accounts`.

## 2. Automated validation (primary)

```powershell
uv run pytest tests/unit -v
```

Expected: all pass, including the new node, `db.py` account functions, and
`order_support_agent` preferences-injection tests. Per the constitution, every test carries a
one-line comment naming what it verifies and its category.

The node suite is where FR-001 through FR-012 are actually proven:

```powershell
uv run pytest tests/unit/test_account_identification_node.py -v
```

It must cover, at minimum:

| Scenario | Expected | Requirement |
|---|---|---|
| Reply "1" then a known account number | `account_number`/`account_preferences` set from that row | FR-002, FR-003, FR-004 |
| Reply "2" | `account_number` and `account_preferences` both `None`, no row created | FR-002, FR-007 |
| Reply "3" | new unique account number returned to customer and set in state, `account_preferences` is `None` | FR-002, FR-006 |
| Reply "1" then an unknown account number | recovery menu offered, no state change yet | FR-005 |
| Recovery menu → "try again" → a known number | account found | FR-005 |
| Recovery menu → "sign up" / "continue without" | same effect as primary-menu options 3 / 2 | FR-005 |
| Reply "4" (or garbage) to the primary menu | prompt re-issued, no state change | FR-011, FR-012 |
| Account number entered with stray spacing/casing/dashes | still resolves to the matching account | Edge case (normalization) |

Then the end-to-end conversation trajectory (calls the model):

```powershell
uv run pytest tests/integration/test_order_support_trajectory.py -v
```

## 3. Manual end-to-end validation

Seed an account with preferences directly (populating preferences is out of scope for this
feature's own code paths, so seed it for the purposes of this manual check):

```powershell
python -c "from customer_support_fde import db; num = db.create_account(); import sqlite3; sqlite3.connect('customer_support.db').execute('UPDATE accounts SET preferences = ? WHERE account_number = ?', ('Loves spicy food, dislikes cilantro, allergic to peanuts.', num)); sqlite3.connect('customer_support.db').commit(); print(db.format_account_number(num))"
```

Note the printed account number. Drive the CLI (`src/customer_support_fde/cli.py`) through each
scenario:

### A. Returning customer with an account (US1, P1)

Ask a menu question (routes to order/support). At the account menu, reply `1`, then enter the
seeded account number (try it with extra spaces or lowercase to confirm normalization).

Expected: the conversation proceeds to the order/support agent, and its responses are informed
by the seeded preferences (e.g., it avoids recommending something with peanuts, or references the
customer's spice preference unprompted).

### B. Unknown account number (FR-005)

Same as A, but enter a number that doesn't exist.

Expected: told the account wasn't found, offered the recovery menu (try again / sign up /
continue without).

### C. New sign-up (US2, P2)

At the account menu, reply `3`.

Expected: a new account number is generated and shown to you. Confirm it's retrievable in a
fresh conversation:

```powershell
python -c "from customer_support_fde import db; print(db.get_account('PASTE-THE-NUMBER-HERE'))"
```

Expected: a dict with that `account_number`, `preferences: None`.

### D. No account (US3, P3)

At the account menu, reply `2`.

Expected: proceeds straight to the order/support agent exactly as it behaves without this
feature — no account prompt, no preferences-derived behavior.

### E. Invalid menu input (FR-011, FR-012)

At the account menu, reply with something that isn't `1`, `2`, or `3` (e.g. "maybe").

Expected: the same three-option menu is presented again rather than the conversation advancing.

## 4. Confirm the order flow is unregressed

This feature edits `state.py`, `graph.py`, `cli.py`, and `order_support_agent.py`'s context
builder — all shared with the existing ordering flow:

```powershell
uv run pytest tests/unit/test_cli.py tests/unit/test_order_support_agent.py tests/unit/test_router_agent.py tests/unit/test_clarify_intent.py -v
```

Expected: all pass, proving the added state fields, graph edges, and context-injection change
did not disturb ordering when no account is involved (scenario D above).
