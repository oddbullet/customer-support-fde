# Quickstart: Validating the Tool Call Limit

## Prerequisites

```
uv sync
uv run start --init-db
```

## 1. Automated checks (no API key needed)

```
uv run pytest
```

Expected results:
- `tests/unit/test_tool_limit.py`: every row in the [`find_repeated_tool` table](contracts/tool-limit.md) passes, plus the `route_after_agent` and `tool_limit_node` cases.
- `tests/unit/test_interactive.py`:
  - `print_warning` prints red text on a forced terminal and plain text with no ANSI codes otherwise.
  - When the result has `tool_limit_reached` set, `run_interactive` shows `TOOL_LIMIT_WARNING` and waits for Enter before `console.clear()`.
- `tests/integration/`:
  - A scripted order LLM that returns `get_menu` tool calls on every step ends the graph with `tool_limit_reached == {"agent": "order_support", "tool": "get_menu"}`.
  - The `get_menu` tool ran exactly 3 times (3 `ToolMessage`s), and no ticket file was written.
  - The same holds for the refund path with `lookup_order` (`agent == "refund"`, `refund_resolved` false, no refund ticket).
- All existing order and refund trajectory tests pass unchanged (SC-003).

## 2. Seeing the red warning by hand

The real model rarely loops, so to see the warning, temporarily set `MAX_CONSECUTIVE_TOOL_CALLS = 0` in `src/customer_support_fde/nodes/tool_limit.py`, then:

```
uv run start
> what's on the menu?
```

Expected result: the first tool request trips the limit. The red line "Sorry, our system is having some issues right now. Please try again later." appears, followed by "Press Enter to start a new conversation.". Pressing Enter clears the screen and shows a fresh prompt. There's no stack trace or `Error:` line.

Change the constant back afterwards.

## 3. Trace (optional, needs `PHOENIX_COLLECTOR_ENDPOINT`)

With the same temporary change and Phoenix running, repeat step 2. In Phoenix, the conversation's trace should end in a `tool_limit_node` span whose output has `tool_limit_reached` with `agent` and `tool` set (SC-005).
