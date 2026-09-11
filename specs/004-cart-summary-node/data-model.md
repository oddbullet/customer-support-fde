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
| `lines` | `list[SummaryLine]` | One entry per priceable distinct cart item, in `menu_items` iteration order (insertion order — the order the customer added them). Empty when the cart is empty or nothing could be priced. |
| `unpriced` | `list[str]` | Canonical names of cart items with no menu price, in cart order. Empty in the normal case. Never merged into `lines` and never silently dropped (FR-008). |
| `total` | `float \| None` | Sum of every `lines[].line_total`, rounded to 2 decimals. `None` when `lines` is empty — which covers the empty-cart case (FR-009) and the all-items-unpriced case. |

### SummaryLine (entry in `lines`)

| Field | Type | Notes |
|---|---|---|
| `name` | `str` | Canonical menu name, copied from the `menu_items` key (FR-002). |
| `quantity` | `int` | Units ordered, copied from the `menu_items` value (FR-003). Always `>= 1` — the cart never holds zero-quantity entries. |
| `unit_price` | `float` | Menu price at summary time, from `price_for_item` (FR-007). |
| `line_total` | `float` | `unit_price * quantity`, computed as `Decimal` and quantized to `0.01` with `ROUND_HALF_UP`, then stored as `float` (FR-004). |

### Validation rules

- `total` MUST equal the sum of the `line_total` values as stored, not a separately rounded product
  — line totals are rounded first, then summed (FR-006). A test asserts this invariant directly.
- Every key in `menu_items` MUST appear exactly once across `lines` and `unpriced` combined; nothing
  is dropped and nothing is duplicated (FR-002, FR-008).
- `unit_price` MUST come from the menu, never from `SupportState`, the conversation, or the model
  (FR-007).
- `total` MUST be `None`, not `0.0`, when `lines` is empty — a zero total would read as a free order
  rather than an absent one (FR-009).
- `build_order_summary` MUST NOT mutate the `menu_items` mapping it is given — same
  no-in-place-mutation guarantee `add_items_to_cart` and `remove_items_from_cart` already provide.
- The same `menu_items` and the same menu MUST always produce an identical `order_summary` (FR-011).

## OrderTicket (`order_ticket`) — existing field, **changed shape**

Built by `ticket_gen_node` from `order_summary`, not recomputed from `menu_items` (FR-010, SC-004).

| Field | Type | Notes |
|---|---|---|
| `items` | `dict[str, int]` | Unchanged from 002 — a copy of `menu_items`. Retained so existing staff-facing consumers of the item/quantity mapping keep working. |
| `lines` | `list[SummaryLine]` | Same list as `order_summary["lines"]`. |
| `unpriced` | `list[str]` | Same list as `order_summary["unpriced"]`. |
| `total` | `float \| None` | Same value as `order_summary["total"]`. |

**Backward-incompatible**: 002 produced `{"items": {...}}` and nothing else. Two existing assertions
in `tests/integration/test_order_support_trajectory.py` (lines ~220 and ~339) compare `order_ticket`
against that exact dict and must be updated. Called out under Constitution Principle IV in
[plan.md](./plan.md).

### Validation rules

- Every priced value on the ticket MUST be identical to the value presented to the customer — the
  ticket copies `order_summary`, it does not re-derive (FR-010).
- `items` MUST stay consistent with `lines` + `unpriced`: same names, same quantities.

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

Full behavioral contract, including rendering rules and the empty/unpriced wording, in
[contracts/cart-summary-node.md](./contracts/cart-summary-node.md).
