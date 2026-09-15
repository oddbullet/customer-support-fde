# Phase 0 Research: Interactive CLI Mode

No `NEEDS CLARIFICATION` markers remained in the Technical Context after `/speckit-clarify` —
`rich` was already a pinned dependency and the three material UX ambiguities (speaker labeling,
loading feedback, transcript persistence) were resolved during clarification. This document
records the remaining implementation-level decisions needed before design.

## Decision: Dispatch on `sys.stdin.isatty()`, not merely "no query argument"

**Decision**: When `cli.run()` receives no query argument, branch on `sys.stdin.isatty()`
(and `sys.stdout.isatty()`, since Rich styling and a REPL prompt are meaningless if output
isn't a terminal either). If both are true → enter the new interactive loop in
`interactive.py`. If either is false (piped/redirected) → fall through to today's behavior:
read exactly one line from stdin, run one conversation, print, exit.

**Rationale**: `specs/001-router-agent/contracts/cli-route.md` documents
`echo "..." | customer-support-fde` as a supported, no-argument invocation, and existing tests
(`tests/unit/test_cli.py`) rely on `cli.run()` working non-interactively. "No query argument"
alone is not a safe signal for "start a REPL" — it's also how the piped-stdin automation path
is triggered. `isatty()` is the standard, dependency-free way to tell the two apart and is what
`rich.console.Console` itself already uses internally to decide whether to emit ANSI codes.

**Alternatives considered**:
- *Always start the interactive loop when no argument is given*: rejected — breaks the
  documented piped-stdin contract and several existing/regression tests that invoke `cli.run()`
  with no argument and a monkeypatched non-interactive `sys.stdin`.
- *Add a new explicit flag (e.g. `--interactive`) instead of auto-detecting*: rejected — this is
  exactly the friction the spec calls out ("I should not need to start with `uv run
  customer-support-fde "question"`"); the user explicitly wants zero-flag interactive startup.

## Decision: `rich.console.Console.status()` for the thinking indicator

**Decision**: Wrap each `graph.invoke(...)` / `graph.invoke(Command(resume=...), ...)` call
inside `with console.status("Thinking...", spinner="dots"):` in `interactive.py`.

**Rationale**: `Console.status()` is a built-in Rich context manager purpose-built for exactly
this ("show a spinner until this blocking call returns"); it already respects `Console`'s
own non-tty detection (degrades to nothing when not a terminal), so it composes directly with
the `isatty()` dispatch decision above and needs no extra guard logic (FR-011, FR-009).

**Alternatives considered**:
- *Hand-rolled spinner via `\r` + `print`*: rejected — reimplements what Rich already provides,
  against Constitution Principle III (Simplicity/YAGNI).
- *`rich.progress`*: rejected — designed for measurable progress/tasks; the wait here has no
  known duration or steps, `Status` is the correct-weight primitive.

## Decision: `Console.clear()` between resolved/cancelled conversations

**Decision**: After a conversation reaches a resolved or cancelled end state, call
`console.clear()` before printing the next prompt.

**Rationale**: `Console.clear()` is Rich's cross-platform screen clear (handles the
Windows-vs-ANSI difference internally), matching the clarified decision that only the current
conversation's transcript should be visible at a time.

**Alternatives considered**:
- *`os.system("cls" if os.name == "nt" else "clear")`*: rejected — Rich already solves this
  portably; shelling out is unnecessary complexity.

## Decision: Fresh `thread_id` per conversation, not per process

**Decision**: `interactive.py`'s loop generates a new `uuid.uuid4()` thread_id for each
conversation it runs (each call into the graph with a fresh initial state), rather than reusing
one thread_id for the whole interactive session.

**Rationale**: Today's single-shot `cli.run()` already generates one thread_id per process
invocation = per conversation (`config = {"configurable": {"thread_id": str(uuid.uuid4())}}`
in `cli.py`). Preserving "one thread_id per conversation" in the new loop keeps each order,
refund, or Q&A exchange as its own independently traceable/resumable LangGraph checkpoint
thread and Phoenix trace grouping (Constitution Principle IV), rather than merging unrelated
conversations into one ever-growing thread history.

**Alternatives considered**:
- *One thread_id for the whole session*: rejected — would conflate multiple, unrelated
  conversations (e.g., an order followed by a refund) into a single checkpoint/trace history,
  making both LangGraph state and Phoenix traces harder to reason about, and has no benefit
  since the spec's clarified screen-clear behavior already treats each conversation as visually
  independent.

## Decision: Exit recognized via the `/exit` command, or `KeyboardInterrupt`

**Decision**: At the "start a new conversation" prompt, treat the literal input `/exit`
(case-insensitive) as an explicit exit. Catch `KeyboardInterrupt` (Ctrl+C) at any point in the
loop and treat it the same way: print a closing message, exit code 0. Plain blank input and
bare words like `exit`/`quit` are *not* treated as exit — they're passed through as an ordinary
(empty or literal) question, per explicit direction to standardize on a single, unambiguous
`/exit` command.

**Rationale**: A slash-prefixed command (`/exit`) cannot collide with a legitimate customer
question or an accidental blank Enter press, unlike a bare word such as `exit` or `quit` which a
real query could plausibly contain (e.g., "how do I exit a subscription refund request?"). It's
discoverable from the welcome banner text (FR-002, SC-005) without documentation, and requires
no new dependency — this mirrors the familiar CLI slash-command convention.

**Alternatives considered**:
- *Bare `exit`/`quit` words, or blank input, as exit triggers*: rejected — ambiguous against
  real question text and accidental empty submissions; superseded by explicit direction to use
  `/exit`.
- *Ctrl+C only*: rejected — less discoverable for a typed-first UX, and SC-005 requires
  discoverability from on-screen text.
- *A numbered menu ("1) Ask another question 2) Exit")*: rejected as unnecessary ceremony for a
  two-choice decision — YAGNI (Principle III).

## Decision: Rendering primitives kept to `Console.print` + `Console.status` + `Console.clear`

**Decision**: No `rich.live.Live`, no `rich.layout.Layout`, no third-party TUI framework.
Human turns and AI turns are each a single `console.print(...)` call using a Rich style/markup
convention (e.g. a colored, bold `"You"` / `"Assistant"` label prefix) applied consistently by
a small helper in `interactive.py`.

**Rationale**: The spec's scope is a labeled, readable transcript for a demo audience — not a
full-screen dashboard. `rich` (already pinned) fully covers the FR-003/FR-009/FR-011 needs with
its simplest APIs. Constitution Principle III requires not reaching for heavier abstractions
than the current requirement needs.

**Alternatives considered**:
- *`rich.panel.Panel` per turn*: considered for visual polish but rejected for v1 — adds
  vertical space cost for a live demo transcript without being required by any FR/SC; can be
  revisited later without any interface change since it's purely inside the rendering helper.
