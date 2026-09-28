# Implementation Plan: Tool Call Limit

**Branch**: `tool-limit` | **Date**: 2026-09-28 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/017-tool-call-limit/spec.md`

## Summary

This feature stops runaway tool loops in the order/support and refund agents. No tool may be called in more than 3 consecutive agent steps within a customer turn. When the limit is hit, the customer sees a red "system is having issues, please try again later" warning.

The count is worked out from the message history, so no counter is stored. A shared edge router (`route_after_agent`) replaces `tools_condition` on both agents' edges. On a 4th consecutive request it sends the graph to a new `tool_limit_node`, which records `{agent, tool}` in state and ends the graph. The interactive CLI sees that flag and shows the warning through a new generic, Rich-based `print_warning(message)`. It then waits for Enter before clearing the screen.

## Technical Context

**Language/Version**: Python 3.14

**Primary Dependencies**: LangGraph / LangChain (existing), Rich (existing; used for the red warning, per user input), arize-phoenix-otel (existing). No new dependencies.

**Storage**: N/A. There are no schema changes; one new in-memory `SupportState` field.

**Testing**: pytest (unit and integration, with scripted `MagicMock` LLMs as in `tests/integration/test_order_support_trajectory.py`)

**Target Platform**: Local CLI (Windows/macOS/Linux terminals)

**Project Type**: Single-project Python library with a CLI

**Performance Goals**: A looping conversation ends within 4 agent steps of the loop starting (SC-002). The routing check is a linear walk over the current turn's messages, which is negligible.

**Constraints**:
- Legitimate conversations must not change (FR-013, SC-003).
- The warning must not expose internal details (FR-008).
- Nodes must not print, because they run under the "Thinking..." spinner.

**Scale/Scope**:
- Two new small modules/functions.
- Edits to `graph.py`, `state.py`, and `interactive.py`.
- About 4 new test groups.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Assessment | Status |
|-----------|------------|--------|
| I. Test-First | Tests are written and seen failing first for `find_repeated_tool`, `route_after_agent`, `tool_limit_node`, `print_warning`, the `run_interactive` warning path, and graph-level loops on both agents. Each test gets a one-line category comment (`(base)`, `(edge)`, `(regression)`). | PASS |
| II. Library-First & CLI | The limit logic lives in its own importable module, `nodes/tool_limit.py`, with a single purpose. The warning display lives in `interactive.py`, the existing CLI rendering module. No new CLI flags are needed. | PASS |
| III. Simplicity | The count comes from the messages instead of a stored counter. One router and one node serve both agents. There's a single constant, no settings, and no new dependency. `print_warning` stays in `interactive.py` until it has a second caller. | PASS |
| IV. Observability | The breach shows up as a Phoenix span for `tool_limit_node`, recorded by the existing LangChain auto-instrumentation, with `{agent, tool}` in its output. No console-only logging. This is a MINOR version bump (backward-compatible feature). | PASS |

**Post-design re-check**: PASS. The design adds one state field, one module, and one graph node. There are no violations, so Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/017-tool-call-limit/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── tool-limit.md
│   └── print-warning.md
└── tasks.md             # created by /speckit-tasks
```

### Source Code (repository root)

```text
src/customer_support_fde/
├── graph.py                     # MODIFY: route_after_agent on both agent edges; add tool_limit_node → END
├── state.py                     # MODIFY: add tool_limit_reached: dict | None (default None)
├── interactive.py               # MODIFY: add print_warning, TOOL_LIMIT_WARNING; warning + wait-for-Enter path
└── nodes/
    └── tool_limit.py            # NEW: MAX_CONSECUTIVE_TOOL_CALLS, find_repeated_tool, route_after_agent, tool_limit_node

tests/
├── unit/
│   ├── test_tool_limit.py       # NEW: contract table for find_repeated_tool; router and node cases
│   └── test_interactive.py      # MODIFY: print_warning color/no-color/markup/multi-line; limit path waits before clear
└── integration/
    ├── test_order_support_trajectory.py  # MODIFY: scripted get_menu loop → limit hit, 3 tool runs, no ticket
    └── test_refund_trajectory.py         # MODIFY: scripted lookup_order loop → limit hit, refund unresolved, no ticket
```

**Structure Decision**: This is the existing single-project layout. The new logic goes in `nodes/tool_limit.py` next to the agent nodes it guards. See [contracts/tool-limit.md](contracts/tool-limit.md) and [contracts/print-warning.md](contracts/print-warning.md) for the interfaces, and [data-model.md](data-model.md) for the state change and transitions.

## Key Design Decisions

See [research.md](research.md) for the rationale and alternatives behind each.

1. **R1: The count comes from the messages.** The router walks back to the latest `HumanMessage` and counts consecutive tool-calling `AIMessage`s that include each tool. Tools repeated within one step count once.
2. **R2: The limit is enforced at the edge.** The 4th request never reaches `ToolNode`, and the graph goes to `END`, skipping cart summary, ticket, and memory nodes.
3. **R3: One flag with agent and tool.** `tool_limit_reached = {"agent": destination, "tool": name}` tells the CLI to show the warning and gives the trace its record.
4. **R5: `print_warning(message, console=None)`** prints `rich.text.Text(message, style="red")`. It's safe against markup and drops color codes when output isn't a terminal.
5. **R6: Wait for Enter before clearing.** This applies only on the limit path, so the warning isn't wiped by the existing `console.clear()`.

## Complexity Tracking

No violations.
