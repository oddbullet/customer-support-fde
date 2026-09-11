# Tool Contract: `get_cart_total`

This project has no HTTP/REST surface; the interface it exposes to an external caller (the
LLM, via LangChain tool-calling) is a set of `@tool`-decorated functions bound to the
order support agent. This document specifies the contract for the one new tool this feature
adds, following the same shape as the existing tools in `src/customer_support_fde/tools/`.

## Tool: `get_cart_total`

**Module**: `src/customer_support_fde/tools/cart_tools.py`

**Registered on**: `order_support_agent._ORDER_TOOLS`
(`src/customer_support_fde/nodes/order_support_agent.py`)

### Purpose

Return the customer's current cart total, computed deterministically from cart contents and
menu prices, so the agent never needs to perform or approximate the arithmetic itself (FR-001).

### Input

| Parameter | Source | Type | Description |
|-----------|--------|------|--------------|
| *(none user-supplied)* | — | — | The tool takes no arguments from the model. |
| `state` | `InjectedState` | `SupportState` | Injected automatically; the tool reads `state["menu_items"]` and `state["menu"]`. |

This mirrors `get_menu` in `menu_tools.py`, the closest existing precedent for a
no-argument, state-only tool.

### Output

- **Type**: `str` — a single rendered message, returned as a `ToolMessage` (or directly, per
  the existing read-only-tool convention in `menu_tools.py`; see Implementation Note below).
- **Cart has items**: A message stating the total, e.g.
  `"Your current cart total is $23.50."` The dollar figure is the shared `cart_total()` helper's
  output, formatted to two decimal places — never reformatted or recomputed downstream.
- **Cart is empty**: A message stating there's nothing to total, e.g.
  `"Your cart is empty, so there's no total yet."` (FR-005) — no numeric value is included.

### Error Handling

- No error cases: `state["menu_items"]` and `state["menu"]` are always present on
  `SupportState` by the time the order support agent runs (same precondition every existing
  cart/menu tool already relies on). There is no user input to validate.

### Implementation Note (non-binding — resolved during `/speckit-tasks` / implementation)

`add_items_to_cart` / `remove_items_from_cart` return a `Command` (because they mutate
`menu_items`). `get_cart_total` does not mutate state, so it follows the simpler
`get_menu` / `get_menu_item` pattern: return the rendered string directly rather than a
`Command`.

### Contract Test Expectations

(Sequenced as failing tests before implementation per Principle I — see `tasks.md`.)

1. **(base)** Cart with one item, quantity 1 → total equals that item's price.
2. **(base)** Cart with multiple distinct items and quantities > 1 → total equals
   `Σ price × quantity`.
3. **(edge)** Empty cart (`menu_items == {}`) → response indicates no total / empty cart, no
   numeric value.
4. **(edge)** Cart total requires rounding (fractional-cent sum) → rounded up to the nearest
   cent, matching `cart_summary_node.build_order_summary`'s rounding for the same cart.
5. **(regression)** A total computed via `get_cart_total` for a given cart equals the `total`
   `cart_summary_node.build_order_summary` would compute for that same cart — guards against
   the two call sites drifting apart (FR-004 / SC-003).
