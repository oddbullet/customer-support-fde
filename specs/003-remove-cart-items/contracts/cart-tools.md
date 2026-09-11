# Contract: `tools/cart_tools.py` (addition)

This amends `specs/002-order-support-agent/contracts/cart-tools.md`, which documents the existing `add_items_to_cart`/`mark_order_confirmed`. Both are unchanged by this feature. This document covers the new third tool in the same module.

## `remove_items_from_cart(items: list[CartRemoval], state: Annotated[SupportState, InjectedState]) -> Command`

Where `CartRemoval` is:

```python
class CartRemoval(BaseModel):
    name: str
    quantity: int | None = None
```

Resolves each `items[i].name` against the menu (via `tools.menu_tools.resolve_menu_item`), applying all of them **sequentially within this one function call** to a single derived copy of `state["menu_items"]`, then returns one `Command`:

```python
Command(update={
    "menu_items": <updated cart>,
    "messages": [ToolMessage(content=<per-item results summary>, tool_call_id=...)],
})
```

**Guarantees**:

1. Never mutates `state["menu_items"]` in place — the `Command.update["menu_items"]` value is a new mapping built from it (same guarantee as `add_items_to_cart`).
2. For each entry in `items`:
   - A `tie` or `not_found` resolution (from `resolve_menu_item`) leaves the cart untouched for that name and is reported in the `ToolMessage` content (FR-006, FR-006a) — same rendering as `get_menu_item`/`add_items_to_cart`'s tie/not-found messages.
   - A `found` resolution whose resolved name is **not currently a key** in the cart is reported as "isn't in your cart" and the cart is left untouched for that name (FR-005).
   - A `found` resolution whose resolved name **is** a key in the cart:
     - If `quantity` is `None`, or `quantity` is greater than or equal to the entry's current value: the entry is deleted entirely, and the reported outcome states the full amount that was actually removed (FR-002, FR-004, FR-007).
     - Otherwise: the entry's quantity is decremented by `quantity`, the entry is kept (FR-003), and the reported outcome states the new remaining quantity.
3. Each named item in a multi-item request is resolved and applied independently of the others — one item being not-found, tied, or not-in-cart does not prevent the rest from being processed (FR-008).
4. Because the whole batch is applied within one function call before the single `Command` is returned, there is no dependency on how `ToolNode`/LangGraph would order or merge multiple concurrent `Command` updates to the same state key — same rationale as `add_items_to_cart` (`specs/002-order-support-agent/research.md` §5).
5. Deterministic given the same `(items, state["menu_items"])` input.
6. Never itself decides to call `interrupt()`, block on `order_confirmed`, or otherwise end the conversation — cart mutation after `order_confirmed` is set is out of scope for this feature (spec Assumptions), matching `add_items_to_cart`'s existing behavior of not checking that flag either.
