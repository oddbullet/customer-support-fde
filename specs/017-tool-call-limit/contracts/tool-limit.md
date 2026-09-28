# Contract: Tool Limit (`customer_support_fde.nodes.tool_limit`)

## `MAX_CONSECUTIVE_TOOL_CALLS: int = 3`

This is the only place the limit is defined (FR-004).

## `find_repeated_tool(messages: list[AnyMessage]) -> str | None`

Returns the name of the first tool in the newest message's `tool_calls` that would be called more than `MAX_CONSECUTIVE_TOOL_CALLS` steps in a row within the current customer turn. Returns `None` otherwise.

| Input (current turn, oldest → newest) | Result |
|---------------------------------------|--------|
| newest message is not an `AIMessage` with tool calls | `None` |
| `get_menu`, `get_menu`, `get_menu` | `None` (3 in a row is allowed) |
| `get_menu` ×4 | `"get_menu"` |
| `get_menu` ×3, then `[get_menu, get_cart]` | `"get_menu"` |
| `get_menu` ×3, `get_cart`, `get_menu` | `None` (the run was broken by `get_cart`) |
| one step with `[add_items_to_cart, add_items_to_cart, add_items_to_cart, add_items_to_cart]` | `None` (duplicates within one step count once) |
| `lookup_order` ×3, `HumanMessage`, `lookup_order` | `None` (the customer's reply resets the count) |

`ToolMessage`s between steps don't affect the result. The function doesn't read or change anything outside `messages`.

## `route_after_agent(state: SupportState) -> Literal["tools", "tool_limit", "__end__"]`

This replaces `tools_condition` on the `call_model` and `refund_agent` conditional edges.

- The newest message has no tool calls → `"__end__"`
- `find_repeated_tool(state["messages"])` is not `None` → `"tool_limit"`
- Otherwise → `"tools"`

## `tool_limit_node(state: SupportState) -> dict`

Returns `{"tool_limit_reached": {"agent": state["destination"], "tool": find_repeated_tool(state["messages"])}}`. It makes no LLM or tool calls and writes nothing to the database. It always goes to `END`.

## Graph wiring (`graph.py`)

```text
call_model   --route_after_agent--> {"tools": order_tools,  "tool_limit": tool_limit_node, "__end__": await_customer}
refund_agent --route_after_agent--> {"tools": refund_tools, "tool_limit": tool_limit_node, "__end__": refund_await_customer}
tool_limit_node --> END
```
