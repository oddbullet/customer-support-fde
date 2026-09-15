# Phase 1 Data Model: Interactive CLI Mode

This feature has no persistent storage of its own (spec Assumptions: "No new external services
or persistence are introduced"). The three entities from the spec's Key Entities section are
in-process, transient constructs scoped to a single `interactive.py` REPL loop — not database
tables. They're documented here as the shapes `interactive.py` should model, to keep the loop,
rendering, and tests aligned on the same vocabulary.

## CLI Session

The lifetime of one interactive program run.

| Field | Type | Notes |
|---|---|---|
| `console` | `rich.console.Console` | One instance, constructed once at loop start; owns all styled output and the tty/no-color detection used for FR-009 degradation. |
| `active` | `bool` | `True` until an exit action (command, blank input, or `KeyboardInterrupt`) is observed; drives the outer `while` loop in `interactive.py`. |

A session has no identity beyond the process itself — it is not persisted or logged as an
entity; only its constituent Conversations are individually traceable (via their own
`thread_id`, for Phoenix/LangGraph purposes).

## Conversation

One question-to-resolution exchange within a session — corresponds to exactly one
`graph.invoke(...)` call (plus any `Command(resume=...)` continuations from interrupts) against
a single LangGraph `SupportState` (`src/customer_support_fde/state.py`, unchanged by this
feature).

| Field | Type | Notes |
|---|---|---|
| `thread_id` | `str` (uuid4) | Freshly generated per conversation (see `research.md` — Decision: fresh thread_id per conversation), passed as `config["configurable"]["thread_id"]`. |
| `state` | `SupportState` | The existing typed dict from `state.py`; unmodified shape. |
| `status` | `"resolved" \| "cancelled" \| "errored"` | Derived after the graph call returns (or raises): `resolved` when `order_confirmed` or `refund_resolved` is true, or a plain Q&A completed without either; `cancelled` when the user exits mid-conversation (edge case in spec User Story 3, scenario 3); `errored` when the graph call raises (FR-010). |
| `turns` | `list[Turn]` | Rendered, in order, as the conversation progresses; not retained after the screen clears (spec clarification: only the current conversation is visible; nothing is kept for later replay). |

A Conversation ends the loop iteration it started: after `status` is set, `interactive.py`
clears the screen (`Console.clear()`) and starts the next Conversation (or exits the session).

## Turn

A single labeled unit of transcript output.

| Field | Type | Notes |
|---|---|---|
| `speaker` | `"human" \| "ai"` | Determines both the text label (`"You"` / `"Assistant"`) and the Rich style applied (FR-003). |
| `content` | `str` | The typed question, or the assistant message content already produced today by the graph (`state["messages"][-1].content`, or an interrupt's prompt text) — no new content generation, only new presentation. |

Turns are not a new data structure stored by the graph — they are how `interactive.py` labels
each `console.print` call as it echoes user input and assistant/interrupt output that already
flows through the existing `messages` state and `__interrupt__` mechanism. No changes to
`SupportState`, `graph.py`, or any node are required to produce Turns; `interactive.py` derives
them purely from data the graph already returns.
