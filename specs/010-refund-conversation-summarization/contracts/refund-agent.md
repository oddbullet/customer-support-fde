# Contract: `nodes/refund_agent.py` (revised)

**Revision note (2026-09-12)**: supersedes `specs/007-refund-policy-agent`'s implicit
seeding behavior (`_seed_messages` baking the system prompt and sentiment reading permanently
into `state["messages"]`). `messages` now holds only real conversational turns; a condensation
guard at the top of `refund_agent` bounds its growth, mirroring
`specs/008-order-history-summarization/contracts/order-support-agent.md`'s revision of the order
agent. Graph topology, `refund_tools`, and routing are **unchanged** — no new node or edge is
introduced.

## Nodes

### `refund_agent(state) -> SupportState`

If `state["messages"]` is empty (only true at the very start of a brand-new conversation):
seeds it with a single `HumanMessage(state["user_query"])` — nothing else (no `SystemMessage`,
no sentiment message; those now live only in the ephemeral context built below). Otherwise,
uses `state["messages"]` as-is (it already holds every prior turn's exchange, or the tool
results from earlier in the current turn's inner loop).

**Condensation guard** (runs first, before building context or calling the model):

1. Finds the indices of every `HumanMessage` in `state["messages"]` (turn starts). If there are
   3 or fewer, the guard does nothing (FR-007).
2. Otherwise measures `llm.get_num_tokens_from_messages(_build_context_messages(state) +
   state["messages"])` against `REFUND_HISTORY_TOKEN_THRESHOLD` (20,000). If at or under, the
   guard does nothing.
3. Otherwise: `cutoff` = the index of the 3rd-from-last `HumanMessage`;
   `older_messages = state["messages"][:cutoff]`.
4. Calls the model (no tools bound) with `state["refund_conversation_summary"]` (if any) plus
   `older_messages`, asking for one new, complete summary preserving, per order discussed,
   the order identified, the facts gathered toward a policy decision, the customer's complaint
   description, and any policy decision already reached — keeping separate orders' facts and
   outcomes distinct rather than merged (FR-004).
   - **On success**: `refund_conversation_summary` is replaced with the new summary text (never
     appended to — FR-006), and `older_messages` are removed from `state["messages"]` via
     `RemoveMessage(id=m.id)` for each. The `add_messages` reducer removes exactly those
     messages by id; the retained last-3-turns segment is untouched (FR-005).
   - **On failure** (this one model call raises — wrapped in its own narrow
     `try/except Exception`, isolated from the rest of `refund_agent`): `state["messages"]` and
     `refund_conversation_summary` are left unchanged. No error is surfaced to the customer; the
     turn already in flight proceeds normally on the uncondensed transcript, and the guard
     re-evaluates on the next `refund_agent` call (FR-010).

Because `refund_agent` runs once per inner tool-call round trip within a turn (via
`refund_tools`), this guard may run several times per turn; it is cheap and idempotent
(data-model.md).

**Reply generation** (using whatever `state["messages"]` the guard above leaves in place):
builds an ephemeral context list via `_build_context_messages(state)` — the fixed system
prompt, a `SystemMessage` carrying the sentiment reading if `state["sentiment"]` is not `None`,
and `state["refund_conversation_summary"]` (if not `None`) as a further `SystemMessage` — and
prepends it to `state["messages"]` for this call only. This context is **never** written back
into `state["messages"]` (data-model.md, research.md Decision 2).

Calls `ChatOpenAI(...).bind_tools([lookup_order, process_refund_request, log_complaint,
conclude_refund_conversation])` on `context + messages` and appends the resulting `AIMessage`
to `state["messages"]` (not to the ephemeral context). If this model call itself fails
(transport/API error), the failure propagates — unaffected by the guard's own try/except, which
wraps only the condensation call above.

### `refund_tools` = `ToolNode([...])`

Unchanged from `specs/007-refund-policy-agent`. Executes tool calls against live
`SupportState`.

### `refund_await_customer(state) -> SupportState`

Unchanged in shape from `specs/007-refund-policy-agent`. Reads `state["refund_resolved"]`:

- If `True`: returns state unchanged — routes to `refund_ticket_node`, no `interrupt()` call.
- If `False`: calls `interrupt()` with the last `AIMessage`'s content, and on resume appends the
  resumed value as a new `HumanMessage` to `state["messages"]` (already the existing behavior —
  unchanged by this feature).

## Routing (conditional edges)

**Unchanged** from `specs/007-refund-policy-agent` — no new node, no new edge:

```python
graph.add_conditional_edges(
    "refund_agent", tools_condition, {"tools": "refund_tools", "__end__": "refund_await_customer"}
)
graph.add_edge("refund_tools", "refund_agent")
graph.add_conditional_edges(
    "refund_await_customer", <fn reading state["refund_resolved"]>,
    {"continue": "refund_agent", "resolved": "refund_ticket_node"},
)
```

This feature's condensation logic lives entirely inside `refund_agent`'s function body, not in
the graph topology.

## Guarantees

1. `messages` persists across customer turns for the life of the conversation — unchanged from
   `specs/007-refund-policy-agent` (the refund agent never wiped it).
2. `messages` contains only `HumanMessage`/`AIMessage`/`ToolMessage` entries — the system
   prompt, sentiment reading, and running summary are assembled fresh for each model call and
   never stored in state. (Supersedes `specs/007-refund-policy-agent`'s `_seed_messages`, which
   baked the system prompt and sentiment reading into `messages` permanently.)
3. At the top of every `refund_agent` call, once more than 3 turns exist and the accumulated
   (context + transcript) token count exceeds 20,000, the condensation guard folds every turn
   older than the last 3 into `refund_conversation_summary` before that call's reply-generating
   model call runs. `refund_conversation_summary` is rewritten fresh on each pass, never
   appended to, and keeps separate orders' facts and outcomes distinct when more than one order
   has been discussed.
4. A condensation failure is invisible to the customer: the current `refund_agent` call
   proceeds normally on the uncondensed transcript, and the guard is retried the next time
   `refund_agent` runs (including later in the same turn, or on a later turn).
5. `order_lookup`, `refund_resolved`, `refund_request`, `complaint_ids` are mutated only via the
   tool `Command`s described in `specs/007-refund-policy-agent/contracts/refund-tools.md` —
   unchanged by this feature. Condensation never alters or overrides these fields or the policy
   outcome they encode (FR-011) — it only changes how `messages`/`refund_conversation_summary`
   represent the conversation's history.
6. `destination`/`sentiment` pass through every node in this loop unchanged.
7. `refund_resolved` is read by `refund_await_customer` only after that turn's inner
   tool-calling loop has fully settled — unchanged.
8. If `refund_agent`'s reply-generating model call fails (transport/API error), the failure
   propagates — unchanged. Only the condensation guard's own model call is caught and
   swallowed (guarantee #4); this narrower exception does not extend to any other model call in
   this loop.
9. This feature does not change `order_support_agent.py` or `router_agent.py` in any way
   (FR-008) — `order_conversation_summary` and this feature's `refund_conversation_summary` are
   independent fields, each read/written only inside their own agent's module.
