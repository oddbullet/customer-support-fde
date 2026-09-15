# Quickstart: Validate Refund Ticket Formatting Fix

Runnable validation for [spec.md](./spec.md). This is a pure file-rendering fix — no API key or
running conversation is required to verify it.

## Prerequisites

- Working tree on branch `015-refund-ticket-formatting` with the fix implemented per
  [plan.md](./plan.md) and `tasks.md`.
- Dependencies installed (`uv sync` or equivalent per `pyproject.toml`).

## 1. Automated validation (primary)

```powershell
uv run pytest tests/unit/test_tickets.py -v
```

Expected: all existing refund-ticket tests still pass (they assert on substrings like
`"Refund Request Created: Yes"`, which remain true whether or not the value is bold), **plus**
a new `(regression)`-tagged test confirming:

| Scenario | Expected | Requirement |
|---|---|---|
| Render a refund ticket | each field line contains a bold label (`**Order ID:**`, `**Issue:**`, `**Customer Sentiment:**`, `**Refund Request Created:**`) followed by a plain-text value | FR-001, FR-002 |
| Render a refund ticket | no field line matches the old all-bold shape (e.g. `**Order ID: <value>**`) | FR-001, SC-001 |
| Render a refund ticket | the `# Refund Ticket` header line is unchanged | FR-003 |
| Render a refund ticket with unknown order id / missing issue / missing sentiment | label still bold, fallback value (`Unknown`, `Not recorded`, `unavailable`) still rendered as plain text | Edge case in spec.md |

## 2. Manual inspection

Generate a refund ticket directly and read the file:

```powershell
uv run python -c "from customer_support_fde import tickets; tickets.write_refund_ticket({'order_id': 'N0690YR9', 'issue': \"The spring rolls didn't have enough vegetables in them.\", 'sentiment': 'negative', 'refund_created': False})"
Get-Content tickets\refund-N0690YR9.md
```

Expected output shape (values plain, labels bold, header unchanged):

```markdown
# Refund Ticket

**Order ID:** N0690YR9

**Issue:** The spring rolls didn't have enough vegetables in them.

**Customer Sentiment:** negative

**Refund Request Created:** No
```

## 3. Confirm the order ticket path is unregressed

```powershell
uv run pytest tests/unit/test_tickets.py -k order_ticket -v
```

Expected: all pass unmodified — evidence that `_render_order_ticket` was not touched by this
fix (per `research.md`, scope is limited to `_render_refund_ticket`).
