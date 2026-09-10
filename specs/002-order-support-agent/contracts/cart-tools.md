# Contract: `tools/cart_tools.py`

**Revision note (2026-09-10)**: replaces the original single-item `add_item_to_cart(menu_items, name, menu) -> tuple[...]` design. The cart-mutating tools are now LLM-callable, state-injected, `Command`-returning tools — `add_items_to_cart` (plural, batched) and `mark_order_confirmed` — per `research.md` §2/§4/§5.

## `add_items_to_cart(names: list[str], state: Annotated[SupportState, InjectedState]) -> Command`

Resolves each name in `names` against the menu (via `tools.menu_tools.resolve_menu_item`), applying all of them **sequentially within this one function call** to a single derived copy of `state["menu_items"]`, then returns one `Command`:

```python
Command(update={
    "menu_items": <updated cart>,
    "messages": [ToolMessage(content=<per-name results summary>, tool_call_id=...)],
})
```

**Guarantees**:

1. Never mutates `state["menu_items"]` in place — the `Command.update["menu_items"]` value is a new mapping built from it.
2. For each name in `names`: a `found` resolution increments that item's quantity in the derived cart by 1 (created at `1` if absent); a `tie` or `not_found` resolution leaves the cart untouched for that name and is reported in the `ToolMessage` content, not silently dropped (FR-005, FR-005a).
3. Adding the same resolved item name twice — whether in one call's `names` list or across two separate calls — results in a quantity of exactly 2 on that one entry, never two separate entries (FR-004, Edge Cases).
4. Because the whole batch is applied within one function call before the single `Command` is returned, there is no dependency on how `ToolNode`/LangGraph would order or merge multiple concurrent `Command` updates to the same state key — only one `Command` touching `menu_items` is ever produced per call to this tool (`research.md` §5).
5. Deterministic given the same `(names, state["menu_items"])` input.

## `mark_order_confirmed(state: Annotated[SupportState, InjectedState]) -> Command`

**Guarantees**:

1. If `state["menu_items"]` is non-empty: returns `Command(update={"order_confirmed": True, "messages": [ToolMessage(...)]})` (FR-006, FR-007).
2. If `state["menu_items"]` is empty: returns `Command(update={"messages": [ToolMessage(...)]})` only — `order_confirmed` is omitted from the update (stays `False`) — and the `ToolMessage` content signals there's nothing to confirm yet, so the model can acknowledge that to the customer (Edge Cases).
3. Never itself decides to call `interrupt()` or otherwise end the conversation — that remains `await_customer`'s responsibility, reading `order_confirmed` after the tool-calling loop settles.
