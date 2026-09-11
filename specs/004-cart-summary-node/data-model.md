# Phase 1 Data Model: Cart Summary at Order Confirmation

This feature adds no persistent storage. It adds one `SupportState` field (`order_summary`), changes
the shape of an existing one (`order_ticket`), and leaves `menu_items` untouched.

## Cart (`menu_items`) — unchanged

Still `dict[str, int]`, keyed by canonical menu item name, valued by quantity, as defined in
`specs/002-order-support-agent/data-model.md` and extended (removal only) in
`specs/003-remove-cart-items/data-model.md`. This feature only *reads* it.

Two existing guarantees are what make FR-003 and FR-007 free here, and they must not be weakened:

- Keys are canonical menu names produced by `resolve_menu_item`, never raw customer phrasing — so
  the summary can print the key directly (FR-002) and look its price up by exact match.
- One key per distinct item, quantity accumulated — so repeat additions are already consolidated and
  the summary needs no grouping pass (FR-003).

## OrderSummary (`order_summary`) — new `SupportState` field

Type: `dict | None`. `None` before `cart_summary_node` runs (and for every conversation that never
confirms an order — refund conversations included). Written exactly once, by `cart_summary_node`.

| Field | Type | Notes |
|---|---|---|
| `lines` | `list[SummaryLine]` | One entry per distinct cart item, in `menu_items` iteration order (insertion order — the order the customer added them). Every cart item is guaranteed priceable (see spec.md Assumptions), so `lines` has exactly one entry per cart key. Empty only when the cart is empty. |
| `total` | `float \| None` | Sum of every `lines[].line_total`, rounded up to 2 decimals. `None` when `lines` is empty (the empty-cart case, FR-009). |

### SummaryLine (entry in `lines`)

| Field | Type | Notes |
|---|---|---|
| `name` | `str` | Canonical menu name, copied from the `menu_items` key (FR-002). |
| `quantity` | `int` | Units ordered, copied from the `menu_items` value (FR-003). Always `>= 1` — the cart never holds zero-quantity entries. |
| `unit_price` | `float` | Menu price at summary time, from `price_for_item` (FR-007). |
| `line_total` | `float` | `unit_price * quantity`, computed as `Decimal` and stored as `float` (FR-004). Not independently rounded — see the `total` rule below. |

### Validation rules

- `total` is computed by summing every line's raw `Decimal` value first, then rounding the sum up
  (never down) to 2 decimals in a single step (FR-006). Since menu prices always have at most 2
  decimal places (spec.md Assumptions), this rounding step never actually changes the sum for real
  data — it exists as a defensive, never-shortchange rule for the total.
- `unit_price` MUST come from the menu, never from `SupportState`, the conversation, or the model
  (FR-007).
- `total` MUST be `None`, not `0.0`, when `lines` is empty — a zero total would read as a free order
  rather than an absent one (FR-009).
- `build_order_summary` MUST NOT mutate the `menu_items` mapping it is given — same
  no-in-place-mutation guarantee `add_items_to_cart` and `remove_items_from_cart` already provide.
- The same `menu_items` and the same menu MUST always produce an identical `order_summary` (FR-011).
- `build_order_summary` does not guard against `price_for_item` returning `None` — every cart item
  is assumed priceable by construction (spec.md Assumptions), so this is treated as an impossible
  state rather than a case to handle.

## OrderTicket (`order_ticket`) — existing field, **changed shape**

Built by `ticket_gen_node` from `order_summary`, not recomputed from `menu_items` (FR-010, SC-004).

| Field | Type | Notes |
|---|---|---|
| `items` | `dict[str, int]` | Unchanged from 002 — a copy of `menu_items`. Retained so existing staff-facing consumers of the item/quantity mapping keep working. |
| `lines` | `list[SummaryLine]` | Same list as `order_summary["lines"]`. |
| `total` | `float \| None` | Same value as `order_summary["total"]`. |

**Backward-incompatible**: 002 produced `{"items": {...}}` and nothing else. Two existing assertions
in `tests/integration/test_order_support_trajectory.py` (lines ~220 and ~339) compare `order_ticket`
against that exact dict and must be updated. Called out under Constitution Principle IV in
[plan.md](./plan.md).

### Validation rules

- Every priced value on the ticket MUST be identical to the value presented to the customer — the
  ticket copies `order_summary`, it does not re-derive (FR-010).
- `items` MUST stay consistent with `lines`: same names, same quantities.

## Menu access (`tools/menu_tools.py`) — one new helper

| Function | Signature | Notes |
|---|---|---|
| `price_for_item` | `(name: str, menu: list[MenuItem]) -> float \| None` | Exact match on the menu entry's `name`; returns that entry's `price`, or `None` when no entry matches. Deliberately *not* fuzzy — see [research.md](./research.md) §4. |

`_load_menu`, `resolve_menu_item`, `get_menu`, and `get_menu_item` are unchanged.

## Node contracts

| Node | Reads | Writes |
|---|---|---|
| `cart_summary_node` | `menu_items`, menu prices | `order_summary`, plus one `AIMessage` appended to `messages` carrying the rendered recap (FR-001) |
| `ticket_gen_node` | `menu_items`, `order_summary` | `order_ticket` (FR-010) |

Full behavioral contract, including rendering rules and the empty-cart wording, in
[contracts/cart-summary-node.md](./contracts/cart-summary-node.md).
