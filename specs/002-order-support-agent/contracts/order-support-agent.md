# Contract: `nodes/order_support_agent.py`

**Revision note (2026-09-10)**: replaces the original classify-then-dispatch (`OrderIntentDecision`) design with a native tool-calling loop of three graph nodes, all operating on `SupportState` directly — `research.md` §2/§4.

## Nodes

### `call_model(state) -> SupportState`

If `state["messages"]` is empty (start of a new customer turn): seeds it with a fixed system prompt, a brief rendered summary of `state["menu_items"]` if non-empty, and a `HumanMessage` from `state["user_query"]` (first turn) or the just-resumed customer message (later turns). Otherwise (mid-inner-loop, after `order_tools` ran): appends nothing extra — the tool results are already in `messages`. Calls `ChatOpenAI(...).bind_tools([get_menu, get_menu_item, add_items_to_cart, mark_order_confirmed])` and appends the resulting `AIMessage` to `state["messages"]`.

### `order_tools` = `ToolNode([get_menu, get_menu_item, add_items_to_cart, mark_order_confirmed])`

Executes whatever tool calls the last `AIMessage` carries, against live `SupportState` (`messages_key="messages"`). `add_items_to_cart`/`mark_order_confirmed` mutate `menu_items`/`order_confirmed` via their `Command` returns (`contracts/cart-tools.md`); `get_menu`/`get_menu_item` return plain `ToolMessage` content (`contracts/menu-tools.md`).

### `await_customer(state) -> SupportState`

Reached when `tools_condition` finds no `tool_calls` on the last `AIMessage` (the model has produced its reply for this turn). Reads `state["order_confirmed"]`:

- If `True`: returns state unchanged — the graph's conditional edge routes to `confirm_node`, no `interrupt()` call this turn.
- If `False`: calls `interrupt()` with the last `AIMessage`'s content (the customer-facing reply for this turn), and on resume resets `state["messages"] = []` (cleared, to be reseeded by `call_model` on the next visit) and sets `state["user_query"]` to the resumed value, then the graph loops back to `call_model`.

## Routing (conditional edges)

```python
graph.add_conditional_edges("call_model", tools_condition, {"tools": "order_tools", "__end__": "await_customer"})
graph.add_edge("order_tools", "call_model")
graph.add_conditional_edges("await_customer", <fn reading state["order_confirmed"]>, {"continue": "call_model", "confirmed": "confirm_node"})
```

## Guarantees

1. `messages` never carries content from a prior customer turn into a new one (`data-model.md` validation rules) — bounding the model's context to one turn's exchange.
2. `menu_items`/`order_confirmed` are mutated only via the tool `Command`s described in `contracts/cart-tools.md` — never directly by `call_model` or `await_customer`.
3. `destination`/`sentiment` pass through every node in this loop unchanged.
4. `order_confirmed` is read by `await_customer` only after that turn's inner tool-calling loop has fully settled — never while `order_tools` might still be executing.
5. If `call_model`'s LLM call itself fails (transport/API error), the failure propagates rather than the loop returning a partial or corrupted `SupportState` (same failure-propagation guarantee as `router_agent`).
6. Reply *wording* is not guaranteed by code in this design (it's model-composed) — `research.md` §9 explains why automated tests target tool execution and state mutation instead, with reply quality validated manually via `quickstart.md`.
