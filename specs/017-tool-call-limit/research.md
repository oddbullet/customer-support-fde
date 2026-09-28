# Research: Tool Call Limit

## R1. Where to keep the consecutive-call count

- **Decision**: Work out the count from `state["messages"]` when routing, instead of storing a counter in state. Walk backward from the newest message to the most recent `HumanMessage`. For each tool in the newest `AIMessage.tool_calls`, count how many consecutive `AIMessage`s with tool calls (ending at the newest) include that tool name.
- **Rationale**: The message history already records exactly what the spec counts:
  - Stopping at the latest `HumanMessage` gives the "reset on customer reply" rule (FR-003) for free.
  - An `AIMessage` that doesn't include a tool breaks that tool's run (FR-003).
  - Duplicate names inside one `AIMessage` collapse to one (FR-002).
  - A stored counter would add a state field, reset logic in both `await_customer` nodes, and increment logic in both tool nodes. That's four touch points that could drift out of sync.
- **Condensation safety**: Condensation only removes messages before the third-most-recent `HumanMessage` (`order_support_agent.py`, `refund_agent.py`). The current turn is never condensed, so the backward walk always sees the whole turn.
- **Alternatives considered**:
  - A counter dict in `SupportState` updated by a wrapper around `ToolNode`. Rejected: it duplicates what the messages already record.
  - LangGraph's `recursion_limit`. Rejected: it counts total steps, not same-tool repeats. It raises `GraphRecursionError`, which the interactive loop would show as a raw `Error: ...` line. It stays in place as the backstop for alternating loops (see spec Assumptions).

## R2. Where to enforce the limit in the graph

- **Decision**: Replace `tools_condition` on the `call_model` and `refund_agent` edges with a shared router, `route_after_agent`. It returns `"tools"`, `"tool_limit"`, or `"__end__"`. A new `tool_limit_node` records the breach and goes to `END`.
- **Rationale**: Deciding at the edge means the 4th request never reaches `order_tools` or `refund_tools`, so nothing in that step runs (FR-005). Routing to `END` skips `cart_summary`, `ticket_gen_node`, and `memory_gen_node`, and leaves `refund_resolved` false (FR-009). Effects of earlier steps are already committed, so nothing is rolled back (FR-010). One router and one node serve both agents.
- **Alternatives considered**: Subclassing or wrapping `ToolNode` to refuse execution. Rejected: the tool node would then have to return fake `ToolMessage`s and signal the agent to stop. That needs a second routing change anyway, and the model would get another turn to loop.

## R3. How the CLI learns the limit was hit, and which agent hit it

- **Decision**: Add one state field, `tool_limit_reached: dict | None`, defaulting to `None`. `tool_limit_node` sets it to `{"agent": state["destination"], "tool": <repeated tool name>}`.
- **Rationale**:
  - The interactive loop needs a clear signal, because the last message is an `AIMessage` holding tool calls with empty content, so it has nothing to show.
  - `destination` is already `"order_support"` or `"refund"` by the time either agent runs (set by `router_agent` or `clarify_intent`). So one node can name the agent without two separate routing functions.
- **Alternatives considered**:
  - A plain `bool`. Rejected: the trace would lose the agent and tool (FR-012).
  - Appending a warning `AIMessage`. Rejected: the CLI would still need a flag to know to show it in red rather than as a normal assistant turn.

## R4. Tracing the breach (FR-012)

- **Decision**: No new tracing code. `setup_tracing()` registers Phoenix with `auto_instrument=True`, and the OpenInference LangChain instrumentor records each LangGraph node as a span with its inputs and outputs. The `tool_limit_node` span's output holds `tool_limit_reached = {"agent": ..., "tool": ...}`, which is the required record.
- **Rationale**: Constitution Principle IV requires Phoenix traces, and Principle III (Simplicity) rules out adding manual span code the instrumentor already covers.
- **Alternatives considered**: A manual OpenTelemetry span or event. Rejected: it would duplicate the node span.

## R5. Red warning display with Rich (user input: "Use the Rich Python package")

- **Decision**: Add `print_warning(message: str, console: Console | None = None) -> None` to `interactive.py`. It prints `rich.text.Text(message, style="red")`. When no console is passed, it falls back to `_make_console()`.
- **Rationale**:
  - Rich is already a dependency, and `interactive.py` is the only module that draws on screen. Graph nodes run under the "Thinking..." spinner and must not print.
  - Using `Text(...)` instead of `console.print(f"[red]{message}[/red]")` means Rich doesn't parse `[...]` in the message as markup, so any string shows exactly as written.
  - Rich drops color codes automatically when output isn't a terminal. That meets FR-007 and matches `test_make_console_emits_no_ansi_when_not_a_tty`.
  - The optional `console` argument lets the loop reuse its own console, and lets tests pass a recording console.
- **Alternatives considered**:
  - A new `display.py` module. Rejected for now under YAGNI, since every current caller lives in `interactive.py`. It can be split out when a second caller appears.
  - `style="bold red"` (used by the existing `Error:` line). Rejected: the user asked for red.

## R6. Keeping the warning on screen (FR-011)

- **Decision**: When `tool_limit_reached` is set, the loop prints the warning with `print_warning`, then shows "Press Enter to start a new conversation." and waits for one line on stdin. Only then does it reach `console.clear()`.
- **Rationale**: `run_interactive` currently calls `console.clear()` straight after a conversation ends, which would wipe the warning before anyone could read it. Waiting for Enter only on this path leaves normal conversations unchanged (FR-013) and keeps the existing clear-screen tests valid.
- **Alternatives considered**: Skipping `console.clear()` for this path. Rejected: the next conversation would then begin under the old transcript, going against the spec 016 decision to clear between conversations.

## R7. Warning text

- **Decision**: `TOOL_LIMIT_WARNING = "Sorry, our system is having some issues right now. Please try again later."`, defined in `interactive.py`.
- **Rationale**: It's presentation text owned by the CLI. It's the same for every agent and tool, and exposes no internal details (FR-008).
