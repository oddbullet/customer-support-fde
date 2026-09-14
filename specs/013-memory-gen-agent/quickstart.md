# Quickstart: Validate the Customer Memory Generation Agent

Runnable validation for [spec.md](./spec.md).

## Prerequisites

- Working tree on branch `013-memory-gen-agent` with the feature implemented per
  [plan.md](./plan.md) and `tasks.md`.
- Dependencies installed (`uv sync` or equivalent per `pyproject.toml`).
- Database initialized (idempotent, safe to re-run):

  ```powershell
  customer-support-fde --init-db
  ```

  This feature makes no schema change — it writes to the `accounts.preferences` column the
  `--init-db` step already creates (`specs/012-account-identification-node`).

- `OPENROUTER_API_KEY` set — needed for the manual and trajectory scenarios (both the order
  support agent and this feature's extraction/merge call use the model), not for the unit suite.

## 1. Automated validation (primary)

```powershell
uv run pytest tests/unit -v
```

Expected: all pass, including the new `memory_gen_node` suite and the extended `db.py` account
tests. Per the constitution, every test carries a one-line comment naming what it verifies and
its category.

The node suite is where FR-001 through FR-010 are actually proven:

```powershell
uv run pytest tests/unit/test_memory_gen_node.py -v
```

It must cover, at minimum:

| Scenario | Expected | Requirement |
|---|---|---|
| `account_number` is `None` | Returns `{}`; the LLM client and `db.update_account_preferences` are never called | FR-002, SC-002 |
| Account present, conversation states a like/dislike/allergy, no prior preferences | `db.update_account_preferences` called with the newly extracted passage | FR-001, FR-003 |
| Account present, conversation states a one-off per-order request (e.g. "no onions on this one") | Recorded as a dislike/customization, distinguishable from an allergy | FR-001, FR-010, Clarifications |
| Account present, prior preferences exist, new statement found | Update call's value combines both, preserving the prior fact | FR-005 |
| Account present, nothing found in conversation, prior preferences `None` | `db.update_account_preferences` NOT called; still `NULL` | FR-006 |
| Account present, nothing new found, prior preferences exist | Prior preferences left effectively unchanged (no-op or identical rewrite) | FR-006 |
| Model call raises | Returns `{}`; `db.update_account_preferences` NOT called; no exception propagates | FR-008 |
| `db.update_account_preferences` raises | Returns `{}`; no exception propagates | FR-008 |
| Any of the above | Returned value never contains `messages` or any other `SupportState` key | Decision 3 (research.md) |

Then the new `db.py` coverage:

```powershell
uv run pytest tests/unit/test_db.py -k account_preferences -v
```

| Scenario | Expected |
|---|---|
| Update an existing account | `accounts.preferences` for that row equals the new value |
| Update with a differently-cased/spaced account number | Still resolves via normalization (same as `get_account`) |
| Update a non-existent account number | Raises `OrderStoreError` |

Then the end-to-end conversation trajectory (calls the model):

```powershell
uv run pytest tests/integration/test_order_support_trajectory.py -v
```

## 2. Manual end-to-end validation

Create an account and note its number:

```powershell
python -c "from customer_support_fde import db; num = db.create_account(); print(db.format_account_number(num))"
```

Drive the CLI (`src/customer_support_fde/cli.py`):

### A. Stated allergy and preference are saved (US1, P1)

At the account menu, reply `1` and enter the account number from above. During ordering, state
a like, a dislike, and an allergy in your own words (e.g. "I love spicy food, I don't really
like cilantro, and I'm allergic to peanuts"). Confirm your order.

Verify the account record:

```powershell
python -c "from customer_support_fde import db; print(db.get_account('PASTE-THE-NUMBER-HERE')['preferences'])"
```

Expected: all three facts present, with the allergy clearly distinguishable from the other two
(e.g. a leading "Allergies: peanuts." clause).

### B. One-off per-order request is captured as a soft preference (Clarifications)

Same as A, but instead ask for a one-off change on a specific dish (e.g. "no onions on this
one") without framing it as a general statement. Confirm your order.

Expected: `preferences` now mentions onions as a dislike/customization, not as an allergy.

### C. Guest customer — nothing is written (US2, P1)

At the account menu, reply `2` (continue without an account). State a clear allergy during
ordering. Confirm your order.

Expected: no new account row exists, and no preference data was written anywhere — there is no
account number to check against, which is itself the point (SC-002).

### D. Second visit preserves prior facts (US1, SC-004)

Start a new conversation, use the same account number from scenario A, and have a conversation
that never mentions food at all before confirming an order (e.g. only ask about hours or an
unrelated menu question, then place an order for something already agreed).

Verify the account record again (same command as A) — expected: the allergy and preferences from
scenario A are still present, not erased by the conversation that didn't mention them (FR-006).

### E. Ticket delivery is not delayed (US3, P2)

Compare how the order confirmation message is delivered in scenario A versus a guest run
(scenario C) — expected: no perceptible difference in response time, since the two flows'
account status is the only thing that changes which branches run in parallel.

## 3. Confirm the order flow is unregressed

This feature edits `graph.py` and `db.py`, both shared with the existing ordering and account
flows:

```powershell
uv run pytest tests/unit/test_cart_summary_and_ticket_nodes.py tests/unit/test_account_identification_node.py tests/unit/test_order_support_agent.py -v
```

Expected: all pass, proving the new node and graph edges did not disturb ticket generation,
account identification, or ordering when no account is involved (scenario C above).
