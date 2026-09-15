# Implementation Plan: Interactive CLI Mode

**Branch**: `016-interactive-cli-mode` | **Date**: 2026-09-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/016-interactive-cli-mode/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Running `customer-support-fde` with no query argument currently falls back to reading one line
from stdin, running exactly one conversation, and exiting. This feature adds a genuinely
interactive REPL mode for that same no-argument invocation *when stdin is a real terminal*:
a welcome banner, a styled prompt, a Rich-rendered transcript that labels every line as human
or AI (color + text label), a "thinking" indicator while the graph is running, and a loop that
clears the screen and returns to a fresh prompt after each conversation resolves — until the
user exits. The existing single-shot query-argument invocation, the `--json` flag, and the
documented piped-stdin contract (`echo "..." | customer-support-fde`, from
`specs/001-router-agent/contracts/cli-route.md`) are left byte-for-byte unchanged; the new
loop is reached only when no query argument was given *and* stdin is attached to an interactive
terminal.

## Technical Context

**Language/Version**: Python >=3.14 (per `pyproject.toml`)

**Primary Dependencies**: `langgraph`, `langchain`, `langchain-openai`, `rich` (already a pinned
dependency — no new dependency is introduced), `python-dotenv`, `arize-phoenix-otel`,
`openinference-instrumentation-langchain`

**Storage**: SQLite via `customer_support_fde.db` (unchanged — this feature does not touch
storage; N/A for its own scope)

**Testing**: pytest (`tests/unit/`, `tests/integration/`), per Constitution Principle I

**Target Platform**: Cross-platform terminal CLI (Windows Terminal / PowerShell, macOS/Linux
shells); primary dev environment is Windows 11

**Project Type**: Single project — importable library under `src/customer_support_fde/` with a
CLI entry point (Constitution Principle II)

**Performance Goals**: N/A beyond immediate feedback — response latency is dominated by the
LLM call itself; the requirement (FR-011) is that the user sees a status indicator within one
render frame of submitting a question, not a specific latency bound

**Constraints**:
- MUST NOT change the behavior or output format of the existing query-argument invocation,
  the `--json` flag, or the piped-stdin (`echo ... | customer-support-fde`) contract (FR-007,
  Constitution Principle II)
- MUST NOT introduce a new dependency for styling — `rich` is already pinned and is the
  confirmed choice (spec Assumptions)
- MUST degrade to plain, unstyled — but still human/AI-labeled — text when stdout is not an
  interactive terminal (FR-009)

**Scale/Scope**: Single local user, one process, one terminal session at a time — no
concurrency or multi-user considerations

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Test-First (NON-NEGOTIABLE)**: New behavior (TTY-dispatch branch, REPL loop, turn
  rendering, thinking indicator, screen-clear-and-continue, exit handling) MUST get failing
  tests before implementation, each with a one-line `(base)/(edge)/(error)/(regression)` tag
  comment. Existing `tests/unit/test_cli.py` cases that pin today's argument/`--json`/piped-stdin
  behavior MUST keep passing unmodified — they double as the regression guard for FR-007.
  **Status**: PASS (planned for Phase 1 via `quickstart.md` + task breakdown in `/speckit-tasks`).
- **II. Library-First & CLI Interface**: The REPL/rendering logic MUST live in its own
  single-purpose importable module (not inlined into `cli.py`'s argument parsing), and the CLI
  MUST keep supporting both a human-readable and a machine-readable (`--json`) mode per the
  text in/out protocol. **Status**: PASS — see Project Structure below (`interactive.py`).
- **III. Simplicity (YAGNI)**: No new dependency, no persistent chat-history store, no custom
  terminal framework — reuse `rich.console.Console`, `Console.status()`, and `Console.clear()`
  directly; the loop reuses the existing `graph.invoke`/`Command(resume=...)` interrupt handling
  unchanged, only adding presentation around it. **Status**: PASS.
- **IV. Observability & Versioning**: Each conversation within a session MUST remain a
  distinctly traceable Phoenix run — a fresh `thread_id` is generated per conversation (per
  loop iteration), matching today's one-thread-per-invocation behavior rather than merging
  multiple conversations into one trace. This is a backward-compatible feature addition, so
  `pyproject.toml` version bumps MINOR (0.8.2 → 0.9.0) as part of implementation.
  **Status**: PASS.

No violations requiring justification — Complexity Tracking table is omitted.

### Post-Design Re-Check

Re-evaluated after Phase 1 (`research.md`, `data-model.md`, `contracts/cli-interactive.md`,
`quickstart.md`) — no new dependency, module, or pattern was introduced beyond what the initial
gate anticipated:

- **I. Test-First**: `quickstart.md` step 8 and the Project Structure's `test_interactive.py`
  entry keep the test-first requirement concrete and checkable; still PASS.
- **II. Library-First & CLI**: `data-model.md` and `contracts/cli-interactive.md` confirm the
  new behavior is entirely additive presentation around the existing `SupportState`/graph
  contract — `interactive.py` remains the single new, single-purpose module; still PASS.
- **III. Simplicity**: `research.md`'s decisions all resolve to `rich`'s simplest applicable
  primitives (`Console.print`/`status`/`clear`), explicitly rejecting heavier alternatives
  (`Live`, `Layout`, `Panel`, hand-rolled spinners); still PASS.
- **IV. Observability & Versioning**: `data-model.md`'s Conversation entity fixes the
  fresh-`thread_id`-per-conversation decision in the data model itself, not just prose; still
  PASS. Version bump to 0.9.0 remains a task for `/speckit-tasks`/implementation.

Gate re-check: **PASS**, no changes to the initial Constitution Check.

## Project Structure

### Documentation (this feature)

```text
specs/016-interactive-cli-mode/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   └── cli-interactive.md
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/customer_support_fde/
├── cli.py                # EXISTING — arg parsing + dispatch; gains the isatty() branch
│                          # that routes a no-argument, interactive-terminal invocation to
│                          # interactive.py, leaving the argument/--json/piped-stdin paths
│                          # (_read_query, _print_result) untouched
├── interactive.py         # NEW — single-purpose module: Rich Console setup, welcome banner,
│                           # human/AI turn rendering (color + text label), thinking-status
│                           # wrapper around graph.invoke, the resolve → clear-screen → new
│                           # prompt loop, and exit handling (command/blank/Ctrl+C)
├── graph.py               # UNCHANGED — build_graph(), interrupt/resume flow reused as-is
├── state.py                # UNCHANGED
├── db.py                   # UNCHANGED
├── tracing.py               # UNCHANGED — setup_tracing() already called once at import
├── nodes/                   # UNCHANGED — all agent nodes
└── tools/                   # UNCHANGED

tests/
├── unit/
│   ├── test_cli.py          # EXISTING — extended with regression cases proving the
│   │                         # argument/--json/piped-stdin (non-tty) paths are byte-for-byte
│   │                         # unchanged, plus a case proving the isatty() dispatch itself
│   └── test_interactive.py  # NEW — REPL loop, turn rendering/labeling, thinking indicator,
│                             # screen-clear-and-continue, exit handling (command/blank/^C),
│                             # non-tty degradation of interactive.py's own render helpers
└── integration/             # UNCHANGED structure; no new integration surface — the loop
                              # composes existing graph.invoke()/Command(resume=...) calls
```

**Structure Decision**: Single project (this repo has no frontend/backend or mobile split).
The feature adds exactly one new module, `interactive.py`, alongside the existing `cli.py`,
satisfying Constitution Principle II's "standalone, importable module with a clear, single
purpose" — `cli.py` keeps owning argument parsing and the non-interactive text in/out contract,
`interactive.py` owns everything about the new terminal REPL experience. No other existing
module changes; `graph.py`, `state.py`, and the agent `nodes/` are reused unmodified since this
feature is purely a CLI presentation/input-loop change per the spec's Assumptions.
