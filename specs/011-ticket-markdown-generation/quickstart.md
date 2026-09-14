# Quickstart: Validate Ticket Markdown Generation

Runnable validation for [spec.md](./spec.md). Automated checks come first — the ticket-writing
logic (`tickets.py`) is plain file I/O and needs no API key; the manual scenarios confirm the
full conversation actually triggers it at the right moment.

## Prerequisites

- Working tree on branch `011-ticket-markdown-generation` with the feature implemented per
  [plan.md](./plan.md) and `tasks.md`.
- Dependencies installed (`uv sync` or equivalent per `pyproject.toml`).
- `OPENROUTER_API_KEY` (or whichever key `ChatOpenAI` is configured against) set — needed only
  for the manual and trajectory scenarios, not for the unit suite.
- A clean-ish tickets folder for the manual scenarios below — either run from a scratch
  directory or set `CUSTOMER_SUPPORT_TICKETS_DIR` to a temp path
  (`contracts/tickets-module.md`).

## 1. Initialize the database

```powershell
customer-support-fde --init-db
```

This feature adds no tables or columns, and no new `SupportState` fields either — the
issue/complaint text is read from the existing conversation transcript, not persisted
(`research.md` Decision 5) — so no schema change to confirm here. Still safe/idempotent to
re-run.

## 2. Automated validation (primary)

```powershell
uv run pytest tests/unit -v
```

Expected: all pass, including the new `tickets.py` unit tests and the updated, now-unified
`ticket_gen_node` tests. This suite needs no API key — the new issue-extraction LLM call is
mocked in tests the same way `refund_agent.py`'s condensation call already is. Per the
constitution, every test carries a one-line comment naming what it verifies and its category.

The ticket-writing suite is where the file-facing requirements are actually proven:

```powershell
uv run pytest tests/unit/test_tickets.py -v
```

It must cover, at minimum:

| Scenario | Expected | Requirement |
|---|---|---|
| `write_order_ticket` with non-empty lines | file written at `tickets/order-<id>.md` with items + total | FR-001, FR-002 |
| `write_order_ticket` with empty lines | returns `None`, no file written | FR-003, SC-002 |
| `write_refund_ticket` with a known order id | file written at `tickets/refund-<id>.md` with issue, sentiment, order id, refund-created status | FR-004, FR-005 |
| `write_refund_ticket` with `order_id=None` | file written at `tickets/refund-unknown-<hex>.md`, order id rendered as unknown | FR-010, edge case |
| Two writes, same type + same known order id | second write replaces the first — one file on disk | FR-008, SC-005 |
| Directory does not yet exist | created automatically before the write | FR-007 |
| Write raises `OSError` (e.g., monkeypatch `Path.write_text`) | logged, function returns `None`, no exception raised | FR-011, SC-006 |

Then the end-to-end conversation trajectories (these do call the model):

```powershell
uv run pytest tests/integration/test_order_support_trajectory.py tests/integration/test_refund_trajectory.py -v
```

## 3. Manual end-to-end validation

Drive the CLI (`src/customer_support_fde/cli.py`) through each scenario, then inspect the
tickets folder (default `./tickets`, or `%CUSTOMER_SUPPORT_TICKETS_DIR%` if set).

### A. Confirmed order produces an order ticket (US1, P1)

Order one or more dishes and confirm.

Expected: `tickets/order-<order_id>.md` exists, listing each item (name, quantity, unit price,
line total) and the order total — nothing else.

```powershell
Get-Content "tickets\order-<order_id>.md"
```

### B. Support-only question produces no ticket (US2, P2)

Ask a menu/ingredient question and end the conversation without ordering.

Expected: no new file appears under `tickets/`.

```powershell
Get-ChildItem tickets\order-*.md -ErrorAction SilentlyContinue
```

### C. Abandoned order produces no ticket (US2, edge case)

Add an item, then end the conversation without confirming.

Expected: same as B — no file written for that interaction.

### D. Refund granted produces a refund ticket (US3, P1)

Place an order, then open a refund conversation reporting a missing item, and complete it
through to an approved refund request.

Expected: `tickets/refund-<order_id>.md` exists with the issue text you described, your
sentiment, the order id, and `Refund Request Created: Yes`.

### E. Refund denied still produces a refund ticket (US3, P1)

Same as D, but with a complaint that doesn't qualify under policy (e.g., outside the refund
window, or no undelivered items).

Expected: `tickets/refund-<order_id>.md` exists with the same fields, but
`Refund Request Created: No`.

### F. Unresolved order id still produces a refund ticket (edge case)

Start a refund conversation and voice a complaint before ever giving/confirming an order id that
resolves.

Expected: a file at `tickets/refund-unknown-<random>.md`, with `Order ID: Unknown`.

### G. Repeat ticket for the same order replaces the old file (edge case)

Repeat scenario A for the same order id a second time (e.g., re-run the flow with a seeded
`order_id`), or repeat D/E twice for the same order.

Expected: still exactly one `order-<order_id>.md` (or `refund-<order_id>.md`) file, containing
the latest content — no `-1`, `-2`, etc. suffix files accumulate.

## 4. Confirm the surrounding flows are unregressed

`state.py`, `tools/refund_tools.py`, and `cli.py` are all untouched by this feature
(`research.md` Decision 5) — the only behavioral change to existing code is the
`ticket_gen_node`/`refund_ticket_node` consolidation into one dispatching node
(`research.md` Decision 1) and `graph.py`'s rewiring to match:

```powershell
uv run pytest tests/unit/test_refund_tools.py tests/unit/test_refund_agent.py tests/unit/test_cli.py tests/unit/test_router_agent.py -v
```

Expected: all pass **unmodified** — a pass here is itself evidence that no other node, tool, or
state field was disturbed. Then confirm the consolidation specifically:

```powershell
uv run pytest tests/unit/test_cart_summary_and_ticket_nodes.py -v
```

Expected: all pass, including the pre-existing order/refund ticket-shape tests now calling
through the single `ticket_gen_node` entry point instead of two separate functions.
