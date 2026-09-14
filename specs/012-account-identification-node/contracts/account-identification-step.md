# Step Contract: Account Identification

This project has no HTTP/REST surface; the interface this feature exposes to the customer is a
deterministic conversational menu, resumed across turns via LangGraph's `interrupt()` /
`Command(resume=...)` mechanism — the same mechanism `clarify_intent.py` already uses and that
the CLI (`cli.py`) already drives generically via its `while "__interrupt__" in result` loop. No
CLI flag, HTTP endpoint, or `@tool` is added by this feature.

**Module**: `src/customer_support_fde/nodes/account_identification_node.py`

**Registered on**: `graph.py`, between `router_agent`/`clarify_intent`'s `"order_support"` branch
and `call_model` (research.md Decision 4).

---

## Primary menu

**Prompt** (exact wording is an implementation detail; shape is the contract):

```text
1) Use an existing account
2) Continue without an account
3) Sign up for a new account
Reply with 1, 2, or 3.
```

**Input**: the customer's reply to the `interrupt()` call, as free text.

**Behavior**:

- Reply recognized as option 1 → proceed to **Account number prompt** below.
- Reply recognized as option 2 → return `{"account_number": None, "account_preferences": None}`
  merged into state; no database write (FR-007).
- Reply recognized as option 3 → call `db.create_account()`, return
  `{"account_number": <new number>, "account_preferences": None}` merged into state, and include
  the new account number in the customer-facing message so they can save it (FR-006).
- Reply not recognized as 1, 2, or 3 → re-issue the identical prompt via `interrupt()` again
  (FR-012). Does not count as any of the three options and produces no state change.

---

## Account number prompt (option 1 only)

**Prompt**: asks the customer to state their account number (FR-003).

**Input**: the customer's reply, normalized the same way `db.normalize_order_id` already
normalizes order ids (case, spacing, dashes, `O`/`I`/`L` confusion-folding — research.md
Decision 2) before being looked up via `db.get_account`.

**Behavior**:

- Normalized value matches an existing account → return
  `{"account_number": <that number>, "account_preferences": <that account's preferences, possibly None>}`
  merged into state (FR-004).
- Normalized value matches no account → proceed to **Recovery menu** below (FR-005). No state
  change yet.

---

## Recovery menu (only reached after a not-found account number)

**Prompt**:

```text
I couldn't find an account with that number.
1) Try entering it again
2) Sign up for a new account
3) Continue without an account
Reply with 1, 2, or 3.
```

**Behavior** (research.md Decision 5 — same node, not a separate graph step):

- Reply recognized as option 1 → return to **Account number prompt** above.
- Reply recognized as option 2 → same effect as primary-menu option 3 (create and return a new
  account number).
- Reply recognized as option 3 → same effect as primary-menu option 2 (`None`/`None`, no account).
- Reply not recognized as 1, 2, or 3 → re-issue the identical recovery prompt again, same
  re-prompt rule as the primary menu.

---

## Output — `SupportState` fields touched

Exactly one of the three outcomes in the table below is reached before the node hands off to
`call_model` (single unconditional edge — research.md Decision 4):

| Outcome | `account_number` | `account_preferences` |
|---|---|---|
| Existing account found (primary or after recovery retry) | that account's number | that account's `preferences` (may be `None`) |
| No account (chosen directly, or via recovery) | `None` | `None` |
| New account created (chosen directly, or via recovery) | newly generated number | `None` |

No other `SupportState` field is written by this node. `messages` accumulates the prompts and
replies exchanged, consistent with how `clarify_intent` and the order/refund agents already
append to `messages`.

## Error handling

`MenuStoreError` / `OrderStoreError` from `db.get_account` / `db.create_account` propagate —
the existing CLI already renders such errors with the `--init-db` remediation hint, matching how
every other `db.py`-backed path in this project behaves.
