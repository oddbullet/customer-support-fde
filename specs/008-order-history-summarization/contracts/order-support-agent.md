# Contract: `nodes/order_support_agent.py` (revised)

**Revision note (2026-09-11)**: supersedes
`specs/002-order-support-agent/contracts/order-support-agent.md`'s guarantee #1
(per-turn full-history reset). `messages` now persists across turns; a condensation guard at
the top of `call_model` bounds its growth instead. Graph topology, `order_tools`, and routing
are **unchanged** from `specs/002-order-support-agent` — no new node or edge is introduced.

## Nodes

### `call_model(state) -> SupportState`

If `state["messages"]` is empty (only true at the very start of a brand-new conversation):
seeds it with a single `HumanMessage(state["user_query"])` — nothing else. Otherwise, uses
`state["messages"]` as-is (it already holds every prior turn's exchange, or the tool results
from earlier in the current turn's inner loop).

**Condensation guard** (runs first, before building context or calling the model):

1. Finds the indices of every `HumanMessage` in `state["messages"]` (turn starts). If there are
   3 or fewer, the guard does nothing (FR-007).
2. Otherwise measures `llm.get_num_tokens_from_messages(_build_context_messages(state) +
   state["messages"])` against `ORDER_HISTORY_TOKEN_THRESHOLD` (20,000). If at or under, the
   guard does nothing.
3. Otherwise: `cutoff` = the index of the 3rd-from-last `HumanMessage`;
   `older_messages = state["messages"][:cutoff]`.
4. Calls the model (no tools bound) with `state["order_conversation_summary"]` (if any) plus
   `older_messages`, asking for one new, complete summary preserving customer-stated
   preferences, dislikes, allergies, and decisions (FR-004).
   - **On success**: `order_conversation_summary` is replaced with the new summary text (never
     appended to — FR-006), and `older_messages` are removed from `state["messages"]` via
     `RemoveMessage(id=m.id)` for each. The `add_messages` reducer removes exactly those
     messages by id; the retained last-3-turns segment is untouched (FR-005).
   - **On failure** (this one model call raises — wrapped in its own narrow
     `try/except Exception`, isolated from the rest of `call_model`): `state["messages"]` and
     `order_conversation_summary` are left unchanged. No error is surfaced to the customer; the
     turn already in flight proceeds normally on the uncondensed transcript, and the guard
     re-evaluates on the next `call_model` call (FR-010).

Because `call_model` runs once per inner tool-call round trip within a turn, this guard may run
several times per turn; it is cheap and idempotent (data-model.md).

**Reply generation** (unchanged in spirit from `specs/002-order-support-agent`, using whatever
`state["messages"]` the guard above leaves in place): builds an ephemeral context list via
`_build_context_messages(state)` — the fixed system prompt, a rendered cart summary from
`state["menu_items"]` if non-empty, and `state["order_conversation_summary"]` (if not `None`)
as a further `SystemMessage` — and prepends it to `state["messages"]` for this call only. This
context is **never** written back into `state["messages"]` (data-model.md, research.md
Decision 2).

Calls `ChatOpenAI(...).bind_tools([get_menu, get_menu_item, add_items_to_cart,
remove_items_from_cart, mark_order_confirmed, get_cart_total])` on `context + messages` and
appends the resulting `AIMessage` to `state["messages"]` (not to the ephemeral context). If
this model call itself fails (transport/API error), the failure propagates — unaffected by the
guard's own try/except, which wraps only the condensation call above.

### `order_tools` = `ToolNode([...])`

Unchanged from `specs/002-order-support-agent`. Executes tool calls against live `SupportState`.

### `await_customer(state) -> SupportState`

Reached the same way as `specs/002-order-support-agent` (via `tools_condition`'s `"__end__"`
branch, unchanged). Reads `state["order_confirmed"]`:

- If `True`: returns state unchanged — routes to `cart_summary`, no `interrupt()` call.
- If `False`: calls `interrupt()` with the last `AIMessage`'s content, and on resume **appends**
  the resumed value as a new `HumanMessage` to `state["messages"]` (no longer clears it — this
  is the change from `specs/002-order-support-agent`'s guarantee #1), and sets
  `state["user_query"]` to the resumed value (kept for CLI display/JSON output only — it is no
  longer used to seed `messages`).

## Routing (conditional edges)

**Unchanged** from `specs/002-order-support-agent` — no new node, no new edge:

```python
graph.add_conditional_edges(
    "call_model", tools_condition, {"tools": "order_tools", "__end__": "await_customer"}
)
graph.add_edge("order_tools", "call_model")
graph.add_conditional_edges(
    "await_customer", <fn reading state["order_confirmed"]>,
    {"continue": "call_model", "confirmed": "cart_summary"},
)
```

This feature's condensation logic lives entirely inside `call_model`'s function body, not in
the graph topology.

## Guarantees

1. `messages` persists across customer turns for the life of the conversation; it is never
   fully reset. (Supersedes `specs/002-order-support-agent` guarantee #1.)
2. `messages` contains only `HumanMessage`/`AIMessage`/`ToolMessage` entries — the system
   prompt, cart summary, and running summary are assembled fresh for each model call and never
   stored in state.
3. At the top of every `call_model` call, once more than 3 turns exist and the accumulated
   (context + transcript) token count exceeds 20,000, the condensation guard folds every turn
   older than the last 3 into `order_conversation_summary` before that call's reply-generating
   model call runs. `order_conversation_summary` is rewritten fresh on each pass, never
   appended to.
4. A condensation failure is invisible to the customer: the current `call_model` call proceeds
   normally on the uncondensed transcript, and the guard is retried the next time `call_model`
   runs (including later in the same turn, or on a later turn).
5. `menu_items`/`order_confirmed` are mutated only via the tool `Command`s described in
   `specs/002-order-support-agent/contracts/cart-tools.md` — unchanged by this feature.
6. `destination`/`sentiment` pass through every node in this loop unchanged.
7. `order_confirmed` is read by `await_customer` only after that turn's inner tool-calling loop
   has fully settled — unchanged.
8. If `call_model`'s reply-generating model call fails (transport/API error), the failure
   propagates — unchanged. Only the condensation guard's own model call is caught and
   swallowed (guarantee #4); this narrower exception does not extend to any other model call in
   this loop.
