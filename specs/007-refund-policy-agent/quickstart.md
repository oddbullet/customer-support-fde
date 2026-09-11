# Quickstart: Validate the Refund Policy Agent

Runnable validation for [spec.md](./spec.md). Automated checks come first because the policy
itself is a pure function and needs no API key; the manual scenarios exist to confirm the
conversation actually reaches those decisions.

## Prerequisites

- Working tree on branch `007-refund-policy-agent` with the feature implemented per
  [plan.md](./plan.md) and `tasks.md`.
- Dependencies installed (`uv sync` or equivalent per `pyproject.toml`).
- `OPENROUTER_API_KEY` set — needed only for the manual and trajectory scenarios, not for the
  unit suite.

## 1. Initialize the database

```powershell
customer-support-fde --init-db
```

Idempotent. On an existing database this is the step that creates the three new tables from
[contracts/sqlite-schema.sql](./contracts/sqlite-schema.sql) — **re-run it even if you have a
database already**, or every refund write will fail with a missing-table error.

Confirm the tables exist:

```powershell
python -c "import sqlite3; print(sorted(r[0] for r in sqlite3.connect('customer_support.db').execute(\"SELECT name FROM sqlite_master WHERE type='table'\")))"
```

Expected to include `complaints`, `refund_request_lines`, and `refund_requests`.

## 2. Automated validation (primary)

```powershell
uv run pytest tests/unit -v
```

Expected: all pass, including the new policy, tool, node, and persistence tests. This suite
needs no API key. Per the constitution, every test carries a one-line comment naming what it
verifies and its category.

The policy suite is the one that matters most — it is where SC-001, SC-008, and SC-009 are
actually proven:

```powershell
uv run pytest tests/unit/test_refund_policy.py -v
```

It must cover, at minimum:

| Scenario | Expected | Requirement |
|---|---|---|
| Order 47h59m old, substitute received, return confirmed | eligible | FR-004 |
| Order exactly 48h00m old | eligible — boundary is inclusive | FR-004, edge case |
| Order 48h01m old | denied, `outside_window` | FR-004 |
| Correctly delivered item, customer unhappy with quality | denied, `item_delivered` | FR-005 |
| Substitute received, return declined | denied, `return_declined` | FR-006 |
| Ordered dish never arrived, nothing in its place, no return commitment | **eligible** — waiver applies | FR-006, FR-007 |
| No undelivered line reported | denied, `no_undelivered_items` | FR-005 |
| Same inputs under positive / neutral / negative sentiment | identical outcomes | SC-009 |

Then the end-to-end conversation trajectories (these do call the model):

```powershell
uv run pytest tests/integration/test_refund_trajectory.py -v
```

## 3. Manual end-to-end validation

Each scenario needs an order in the database. Place one through the normal ordering flow and
note the order id the agent reports, or seed one directly for age-sensitive cases:

```powershell
python -c "from customer_support_fde import db; print(db.format_order_id(db.record_order({'lines':[{'name':'Kung Pao Chicken','quantity':1,'unit_price':12.0,'line_total':12.0},{'name':'Mapo Tofu','quantity':1,'unit_price':10.0,'line_total':10.0}],'total':22.0})))"
```

To exercise the 48-hour denial, backdate that order's `created_at`:

```powershell
python -c "import sqlite3,sys; sqlite3.connect('customer_support.db').execute(\"UPDATE orders SET created_at = '2020-01-01T00:00:00.000Z' WHERE id = ?\", (sys.argv[1],)).connection.commit()" ORDERID
```

Drive the CLI (`src/customer_support_fde/cli.py`) through each scenario:

### A. Qualifying refund (US1, P1)

Report that you received the wrong dish, give the order id, name the dish that never arrived,
confirm you will bring the substitute back.

Expected: the agent shows the order, states a refund amount covering **only** the undelivered
line, and says the request is *submitted and awaiting review* — never "complete" (FR-016).

Verify:

```powershell
python -c "from customer_support_fde import db; print(db.list_refund_requests())"
```

One row, `status='pending'`, `amount` equal to the undelivered line's total (SC-008).

### B. Missing item with no substitute (FR-006 waiver)

Same, but say nothing arrived in place of the missing dish.

Expected: refund request created **without** ever asking you to return anything.
`return_confirmed = 0`, `substitute_dishes` is `NULL`.

### C. Each denial branch (US2, P2)

Run three conversations: an order older than 48 hours; a complaint that the food was cold; a
wrong dish where you refuse to return the substitute.

Expected each time: no refund request, a complaint row written, and a reply naming the specific
policy condition that failed (FR-009, SC-005).

```powershell
python -c "from customer_support_fde import db; print(db.list_complaints())"
```

### D. Complaint de-duplication (FR-020, SC-010)

In a single conversation, get denied, then argue the same point twice more.

Expected: exactly **one** complaint row for that order, with `created_at` unchanged from the
first denial and `updated_at` advanced (FR-021).

### E. Duplicate refund attempt (FR-011, SC-007)

After scenario A succeeds, start a new conversation and request a refund on the same order.

Expected: no second row. The agent reports the existing request's pending status.

### F. Complaint only (US3, P3)

Voice dissatisfaction without asking for money back.

Expected: a complaint row with `policy_reason = NULL`, and no refund request.

## 4. Confirm the order flow is unregressed

The refund branch shares `SupportState`, the router, and the CLI with the ordering flow, and
this feature adds required state keys:

```powershell
uv run pytest tests/unit/test_cli.py tests/unit/test_order_support_agent.py tests/unit/test_cart_tools.py tests/unit/test_router_agent.py -v
```

Expected: all pass, proving the added state fields and graph edges did not disturb ordering.
