# Quickstart: Validate Cart Total Lookup

## Prerequisites

- Working tree on branch `006-cart-total-lookup` with the feature implemented per
  [plan.md](./plan.md) and [tasks.md](./tasks.md).
- Dependencies installed (`uv sync` or equivalent per `pyproject.toml`).
- `OPENROUTER_API_KEY` set (the order support agent's LLM calls go through OpenRouter — see
  `order_support_agent.py`).

## 1. Initialize the database

```powershell
customer-support-fde --init-db
```

Seeds/updates `customer_support.db` from `menu/menu.json` (idempotent).

## 2. Automated validation (primary)

```powershell
uv run pytest tests/unit/test_menu_tools.py tests/unit/test_cart_tools.py tests/unit/test_cart_summary_and_ticket_nodes.py -v
```

Expected: all tests pass, including the new `get_cart_total` / shared `cart_total()` helper
tests described in [contracts/get_cart_total.md](./contracts/get_cart_total.md), and the
existing `cart_summary_node` tests continue to pass unchanged (proving the extraction in
[research.md](./research.md) didn't change final-order-total behavior).

## 3. Manual end-to-end validation

Run the CLI's interactive agent entry point (see `src/customer_support_fde/cli.py` for the
exact invocation) and drive this scenario:

1. Ask to add two different menu items to the cart (e.g. one of each of two dishes with known
   prices from `menu/menu.json`).
2. Ask: **"What's my total?"**
   - **Expected**: The agent responds with a dollar total. Manually verify it equals
     `price_1 + price_2` (rounded up to the nearest cent) by cross-checking against
     `menu/menu.json` — this is the SC-001 check.
3. Remove one item, then ask again: **"What's my total now?"**
   - **Expected**: The new total reflects only the remaining item (SC of User Story 2 /
     FR-007).
4. Ask for the total before adding anything (fresh conversation, empty cart).
   - **Expected**: The agent states the cart is empty — no dollar figure (FR-005 / SC-004).
5. Confirm the order (trigger `mark_order_confirmed` then the cart summary flow) and compare
   the final order total shown against the total quoted in step 2/3.
   - **Expected**: They match exactly (SC-003), since both now derive from the same shared
     helper.

## 6. Trace check (Observability, Principle IV)

In LangSmith, confirm the `get_cart_total` tool call appears as a traced step in the agent run
for step 2 above, with no additional custom logging required — it should be captured
automatically by the existing `ToolNode` tracing, the same as `get_menu` / `add_items_to_cart`.
