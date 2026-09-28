# Data Model: Tool Call Limit

No database changes. The only change is to the in-memory graph state (`SupportState`).

## SupportState: new field

| Field | Type | Default (`initial_state`) | Set by | Meaning |
|-------|------|---------------------------|--------|---------|
| `tool_limit_reached` | `dict \| None` | `None` | `tool_limit_node` | `None` while the conversation is within the limit. Otherwise `{"agent": "order_support" \| "refund", "tool": str}`. |

Validation:
- `agent` is copied from `state["destination"]`, which is always `"order_support"` or `"refund"` once an agent node has run.
- `tool` is the name of a tool in the newest `AIMessage.tool_calls` whose consecutive run was over the limit. If several tools are over the limit in the same step, it's the first one in `tool_calls` order.

## Consecutive tool-call count (derived, not stored)

This is computed from `state["messages"]` each time routing runs (see research R1).

- **Scope**: messages after the most recent `HumanMessage`.
- **Step**: each `AIMessage` with a non-empty `tool_calls` in that scope. `ToolMessage`s between steps are ignored.
- **Count for tool T**: the number of consecutive steps, ending at the newest step, whose set of `tool_calls` names includes T.
- **Limit**: `MAX_CONSECUTIVE_TOOL_CALLS = 3`. The limit is hit when the count for any tool in the newest step is **greater than** 3, meaning this would be the 4th consecutive step to call it.

## State transitions

```text
call_model / refund_agent
   │  route_after_agent(state)
   ├── no tool calls ...................... "__end__"    → await_customer / refund_await_customer (unchanged)
   ├── tool calls, all counts ≤ 3 ......... "tools"      → order_tools / refund_tools (unchanged)
   └── tool calls, some count > 3 ......... "tool_limit" → tool_limit_node → END
                                                             sets tool_limit_reached
```

When the graph ends through `tool_limit_node`:
- `order_confirmed` and `refund_resolved` keep whatever values they had (both are `False` at that point).
- `order_ticket`, `order_summary`, and `refund_ticket` stay `None`.
- No `cart_summary`, `ticket_gen_node`, or `memory_gen_node` runs.
