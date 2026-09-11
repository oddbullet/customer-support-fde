# Contract: Cart Summary Node

The customer-facing interface this feature exposes. Shapes referenced here are defined in
[data-model.md](../data-model.md).

## `price_for_item(name, menu)` — `tools/menu_tools.py`

```python
def price_for_item(name: str, menu: list[MenuItem]) -> float | None
```

| Input | Result |
|---|---|
| `name` exactly matches a menu entry's `name` | that entry's `price` |
| no menu entry has that exact `name` | `None` |
| `menu` is empty | `None` |

Exact match only. Case and whitespace are not normalized — cart keys are canonical menu names by
construction, so any mismatch means the item is genuinely no longer on the menu
([research.md](../research.md) §4). Never raises.

## `build_order_summary(menu_items, menu)` — `nodes/cart_summary_node.py`

```python
def build_order_summary(menu_items: dict[str, int], menu: list[MenuItem]) -> dict
```

Pure. Returns an `OrderSummary` dict. Does not mutate `menu_items`.

| Case | `lines` | `unpriced` | `total` |
|---|---|---|---|
| `{"Kung Pao Chicken": 2, "Hot and Sour Soup": 1}`, both priced at `12.95` / `5.50` | two lines, `line_total` `25.90` and `5.50` | `[]` | `31.40` |
| `{"Spring Rolls": 1}` at `6.95` | one line, `line_total` `6.95` | `[]` | `6.95` |
| `{}` (empty cart) | `[]` | `[]` | `None` |
| `{"Peking Duck": 1}`, not on the menu | `[]` | `["Peking Duck"]` | `None` |
| `{"Spring Rolls": 2, "Peking Duck": 1}`, only the first priced | one line for Spring Rolls | `["Peking Duck"]` | `13.90` |

Arithmetic rules:

- `line_total = Decimal(str(unit_price)) * quantity`, quantized to `Decimal("0.01")` with
  `ROUND_HALF_UP`, stored as `float`.
- `total = sum(line_total for line in lines)` over the **already quantized** values, so the stored
  total always equals the sum of the stored line totals (FR-006).
- `total` is `None` — never `0.0` — whenever `lines` is empty.
- `lines` and `unpriced` follow `menu_items` insertion order; between them they account for every
  cart key exactly once.

## `render_order_summary(summary)` — `nodes/cart_summary_node.py`

```python
def render_order_summary(summary: dict) -> str
```

Pure. Turns an `OrderSummary` into the text the customer reads. ASCII only — the CLI already had to
defend against Windows console encoding failures on em dashes and curly quotes
(`cli.py`'s `sys.stdout.reconfigure` comment), and there is no reason to reintroduce that risk here.

**Normal order** — every item priced:

```text
Here's your order:
- Kung Pao Chicken x2 @ $12.95 each = $25.90
- Hot and Sour Soup x1 @ $5.50 each = $5.50

Total: $31.40
```

**Empty cart** (FR-009) — no total line is emitted:

```text
There's nothing in your order to summarize.
```

**Some items unpriceable** (FR-008) — the unpriced items are named, and the amount is relabelled so
it cannot be mistaken for the whole order's cost:

```text
Here's your order:
- Spring Rolls x2 @ $6.95 each = $13.90

We couldn't price these items: Peking Duck. A staff member will confirm them with you.

Subtotal for priced items: $13.90
```

**All items unpriceable** — the unpriced notice only, no amount line at all.

Rules:

- Every name in `lines` and every name in `unpriced` appears in the output; nothing is truncated or
  collapsed into an "and others" line (spec Edge Cases).
- All amounts are formatted `$%.2f` (FR-006).
- The word `Total` is used only when `unpriced` is empty; otherwise `Subtotal for priced items`.

## `cart_summary_node(state)` — `nodes/cart_summary_node.py`

```python
def cart_summary_node(state: SupportState) -> SupportState
```

Returns `{**state, "order_summary": <summary>, "messages": [AIMessage(content=<rendered>)]}`.

- Calls `build_order_summary(state["menu_items"], _load_menu())` then `render_order_summary`.
- Returning a one-element `messages` list appends via the `add_messages` reducer — it does not
  replace the history. `await_customer` returns early once `order_confirmed` is set, so it no longer
  clears `messages`, and this `AIMessage` survives to `END`.
- Makes no LLM call and no tool call ([research.md](../research.md) §1).
- Touches no other state field.

## `ticket_gen_node(state)` — `nodes/ticket_gen_node.py` (**changed**)

Returns `{**state, "order_ticket": {...}}` where the ticket is:

```python
{
    "items": dict(state["menu_items"]),
    "lines": summary["lines"],
    "unpriced": summary["unpriced"],
    "total": summary["total"],
}
```

- `summary` is `state["order_summary"]`; if it is absent or `None` the node falls back to
  `{"lines": [], "unpriced": [], "total": None}` rather than raising. (Unreachable on today's graph —
  `ticket_gen_node` is only entered from `cart_summary_node` — but the node must not explode if the
  graph is rewired.)
- The priced values are **copied**, never recomputed, which is what makes FR-010/SC-004 structural.
- Previously returned `{"items": ...}` alone. Backward-incompatible; see
  [data-model.md](../data-model.md).

## Graph wiring — `graph.py` (**changed**)

| Before | After |
|---|---|
| `from ...nodes.confirm_node import confirm_node` | `from ...nodes.cart_summary_node import cart_summary_node` |
| `graph.add_node("confirm_node", confirm_node)` | `graph.add_node("cart_summary", cart_summary_node)` |
| `{"continue": "call_model", "confirmed": "confirm_node"}` | `{"continue": "call_model", "confirmed": "cart_summary"}` |
| `graph.add_edge("confirm_node", "ticket_gen_node")` | `graph.add_edge("cart_summary", "ticket_gen_node")` |

No nodes or edges are added or removed — only renamed. The node key appears in
`agentevals` trajectory assertions, so
`tests/integration/test_order_support_trajectory.py` (~line 367) changes with it.

## CLI output — `cli.py` (**changed**)

- Initial state dict gains `"order_summary": None`.
- Human-readable mode: when the order was confirmed, print the rendered summary before the existing
  `Destination:`/`Query:` lines. Without this the feature produces no visible output at all
  (FR-001).
- `--json` mode: the payload gains `"order_summary": state["order_summary"]` when the order was
  confirmed. Every amount is a `float`, so the payload stays JSON-serializable
  ([research.md](../research.md) §3).
- Unconfirmed and refund conversations print exactly what they print today.
