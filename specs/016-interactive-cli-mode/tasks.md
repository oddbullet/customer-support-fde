---

description: "Task list for Interactive CLI Mode"
---

# Tasks: Interactive CLI Mode

**Input**: Design documents from `/specs/016-interactive-cli-mode/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-interactive.md, quickstart.md

**Tests**: Constitution Principle I (Test-First, NON-NEGOTIABLE) requires a failing test before
every implementation task in this project — test tasks below are mandatory, not optional. Each
new test case MUST carry a one-line comment above its definition tagging its category
(`(base)`/`(edge)`/`(error)`/`(regression)`), per the constitution.

**Organization**: Tasks are grouped by user story (spec.md priorities: US1 = P1, US2 = P1,
US3 = P2) to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- File paths are exact and relative to the repository root

## Path Conventions

Single project (per plan.md's Structure Decision): `src/customer_support_fde/`, `tests/unit/`,
`tests/integration/` at the repository root. No new top-level directories are introduced.

---

## Phase 1: Setup

**Purpose**: Create the two new files this feature adds, so subsequent tasks have somewhere to
write.

- [ ] T001 Create the new module file `src/customer_support_fde/interactive.py` (empty; target
      for all interactive-mode logic per plan.md's Project Structure)
- [ ] T002 [P] Create the new test file `tests/unit/test_interactive.py` (empty; target for all
      interactive-mode tests)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared plumbing every user story depends on — the entry-point dispatch, the shared
`Console`, and the core conversation-running engine. No user story work can begin until this
phase is complete.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T003 [P] Write failing tests in `tests/unit/test_cli.py` asserting `cli.run()` with no
      query argument calls `interactive.run_interactive()` when `sys.stdin.isatty()` and
      `sys.stdout.isatty()` are both `True`, and falls through unchanged to the existing
      single-line-stdin read (`_read_query`) when either is `False` — one test per branch,
      each tagged `(base)` for the tty-dispatch case and `(regression)` for the non-tty case
      (protects the piped-stdin contract documented in
      `specs/001-router-agent/contracts/cli-route.md`)
- [ ] T004 Implement the `isatty()`-based dispatch branch in `src/customer_support_fde/cli.py`
      per `research.md`'s "Dispatch on `sys.stdin.isatty()`" decision — no query argument +
      both stdin and stdout are a tty → call `interactive.run_interactive()` (a stub returning
      `0` is sufficient for now); otherwise fall through to the existing `_read_query` path
      unchanged. Depends on T003 (make it pass without changing its assertions).
- [ ] T005 [P] Write a failing test in `tests/unit/test_interactive.py` asserting the `Console`
      produced by `interactive.py`'s console factory emits output with no raw ANSI escape
      sequences when stdout is not a tty (tag: `(edge)`, FR-009)
- [ ] T006 Implement a shared `Console` factory in `src/customer_support_fde/interactive.py` —
      one `rich.console.Console` instance constructed once and reused by every interactive-mode
      render call in this module. Depends on T005 (make it pass).
- [ ] T007 [P] Write a failing test in `tests/unit/test_interactive.py` asserting
      `_run_conversation(console, graph, query)` generates a distinct `thread_id` on each call
      (two calls → two different ids) and, given a mocked graph whose `invoke` first returns an
      `__interrupt__` payload and then a resolved state on resume, drives that
      interrupt/`Command(resume=...)` cycle through to the resolved `SupportState` — matching
      `cli.run()`'s existing interrupt-handling loop (tag: `(base)`)
- [ ] T008 Implement `_run_conversation(console, graph, query)` in
      `src/customer_support_fde/interactive.py` per `data-model.md`'s Conversation entity: a
      fresh `uuid.uuid4()` `thread_id` per call, the same initial `SupportState` seed shape
      `cli.run()` already uses, and the same `__interrupt__` / `Command(resume=...)` loop
      `cli.run()` already implements, returning the final resolved state. Depends on T007 (make
      it pass).

**Checkpoint**: Foundation ready — `interactive.py` has a working `Console`, a working
conversation engine, and `cli.py` correctly routes to it. User story implementation can now
begin.

---

## Phase 3: User Story 1 - Start a conversation without a CLI argument (Priority: P1) 🎯 MVP

**Goal**: Running `uv run customer-support-fde` with no arguments in a real terminal shows a
welcome message and a prompt, accepts a typed question, shows a thinking indicator while it
runs, and prints the result — instead of requiring the question as a CLI argument.

**Independent Test**: Run `uv run customer-support-fde` with no arguments; confirm it starts,
shows a welcome message and a prompt, accepts typed input, shows a status indicator while
processing, and prints a result (spec.md User Story 1, all 3 acceptance scenarios).

### Tests for User Story 1

> **Write these tests FIRST — confirm they FAIL before implementation**

- [ ] T009 [P] [US1] Write failing tests in `tests/unit/test_interactive.py`:
      `run_interactive()` prints a welcome/intro message before the first prompt is shown
      (tag: `(base)`, FR-002); a submitted question is passed through to `_run_conversation`
      and its result is printed (tag: `(base)`, FR-001 / acceptance scenario 2); the call to
      `_run_conversation` is wrapped in a visible "Thinking..." status indicator (tag: `(base)`,
      FR-011 / acceptance scenario 3)

### Implementation for User Story 1

- [ ] T010 [US1] Implement `run_interactive()` in `src/customer_support_fde/interactive.py`:
      print the welcome banner (FR-002), read one line at a styled prompt, call
      `_run_conversation` (T008) wrapped in `console.status("Thinking...", spinner="dots")` per
      `research.md`, and print the final result in plain text (mirroring today's
      `cli._print_result` non-JSON formatting). Depends on T006, T008, T009.
- [ ] T011 [US1] Point `cli.py`'s dispatch branch (T004) at the real
      `interactive.run_interactive()`, replacing the T004 stub. Depends on T010.

**Checkpoint**: User Story 1 is independently functional — a no-argument run in a real terminal
shows a banner, a prompt, a thinking indicator, and a plain-text result for one question.

---

## Phase 4: User Story 2 - Visually distinguish AI responses from human input (Priority: P1)

**Goal**: Every line in the transcript — the typed question, the AI's reply, and any
mid-conversation confirmation exchange — is visually marked, by both color and a text label, as
either human or AI, so a demo audience can tell who said what at a glance.

**Independent Test**: Run an interactive session, have at least two back-and-forth exchanges,
and confirm every printed line is correctly attributable to "human" or "AI" by its label/style
alone (spec.md User Story 2, all 3 acceptance scenarios).

### Tests for User Story 2

> **Write these tests FIRST — confirm they FAIL before implementation**

- [ ] T012 [P] [US2] Write failing tests in `tests/unit/test_interactive.py`: a human turn
      renders with a distinct color style and the text label `"You:"` (tag: `(base)`, FR-003);
      an AI turn renders with a distinct color style and the text label `"Assistant:"`
      (tag: `(base)`, FR-003); a multi-line AI response keeps the label/style applied
      consistently, not just on its first line (tag: `(edge)`, acceptance scenario 2); a
      mid-conversation interrupt question renders with AI styling and the user's reply to it
      renders with human styling (tag: `(base)`, FR-004/FR-008, acceptance scenario 3); the
      `"You:"`/`"Assistant:"` text labels are still printed, with no raw ANSI codes, when the
      `Console` is constructed for non-color output (tag: `(edge)`, FR-009)

### Implementation for User Story 2

- [ ] T013 [P] [US2] Implement `_print_turn(console, speaker, content)` in
      `src/customer_support_fde/interactive.py`, applying the color+label convention (e.g. bold
      cyan `"You:"` / bold green `"Assistant:"`) per FR-003 and
      `contracts/cli-interactive.md`'s labeling contract. Depends on T012.
- [ ] T014 [US2] Replace `run_interactive()`'s plain question-echo and result-print calls
      (added in T010) with `_print_turn` calls labeled `"human"`/`"ai"`. Depends on T013.
- [ ] T015 [US2] Route `_run_conversation`'s (T008) interrupt-question print and
      resume-answer echo through `_print_turn` as well, so a mid-conversation confirmation
      exchange (e.g. order confirmation) is labeled identically to the rest of the transcript
      (FR-004, FR-008). Depends on T013.

**Checkpoint**: User Stories 1 and 2 together are functional — a full interactive conversation,
including any order-confirmation interrupt, is fully human/AI-labeled end to end.

---

## Phase 5: User Story 3 - Continue or end the session across multiple tickets (Priority: P2)

**Goal**: After a conversation resolves (or is cancelled), the screen clears and a new prompt
appears so the user can start another, independent conversation, until they explicitly exit
with `/exit` or Ctrl+C.

**Independent Test**: Complete one full conversation, confirm the prompt reappears with the
screen cleared, start and complete a second unrelated conversation, then exit and confirm the
program terminates cleanly (spec.md User Story 3, all 3 acceptance scenarios).

### Tests for User Story 3

> **Write these tests FIRST — confirm they FAIL before implementation**

- [ ] T016 [P] [US3] Write failing tests in `tests/unit/test_interactive.py`: after a
      conversation resolves, the console is cleared and a new prompt is shown, allowing a
      second, independent conversation to run (tag: `(base)`, FR-005, acceptance scenario 1);
      typing `/exit` (case-insensitive) at a new-conversation prompt ends the session with a
      closing message and exit code `0` (tag: `(base)`, FR-006, acceptance scenario 2); a
      `KeyboardInterrupt` raised at the prompt or mid-conversation ends the session the same way
      (tag: `(edge)`, FR-006); a blank line, or a question that happens to contain the literal
      word "exit", does **not** end the session (tag: `(regression)` — protects the
      `/exit`-only decision in `research.md`); a mid-conversation error raised by
      `_run_conversation` is caught, printed as a distinctly styled error line, and the loop
      returns to a fresh prompt instead of crashing the process (tag: `(error)`, FR-010,
      acceptance scenario 3)

### Implementation for User Story 3

- [ ] T017 [US3] Wrap `run_interactive()`'s single-conversation flow (T010) in an outer loop in
      `src/customer_support_fde/interactive.py`: after `_run_conversation` resolves or is
      cancelled, call `console.clear()` and loop back to the prompt; recognize the literal
      `/exit` (case-insensitive) at the prompt as ending the loop. Depends on T010, T016.
- [ ] T018 [US3] Add `KeyboardInterrupt` handling around the prompt and conversation call in
      `run_interactive()`'s loop, printing a closing message and returning exit code `0` on
      Ctrl+C exactly as `/exit` does. Depends on T017.
- [ ] T019 [US3] Add mid-conversation error handling in `run_interactive()`'s loop: catch
      exceptions raised by `_run_conversation`, print them as a distinctly styled error line
      (not `"You:"`/`"Assistant:"`), and continue the loop to a fresh prompt rather than
      exiting the process (FR-010). Depends on T017.

**Checkpoint**: All three user stories are independently functional — the full demo flow
(multiple conversations, fully labeled transcript, clean exit) works end to end.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Regression-proof the untouched paths, finish housekeeping, validate end to end.

- [ ] T020 [P] Add regression tests to `tests/unit/test_cli.py` proving the existing
      query-argument invocation, `--json` output, and piped-stdin (non-tty) behavior are
      byte-for-byte unchanged after this feature (tag: `(regression)`, SC-004)
- [ ] T021 [P] Bump the version in `pyproject.toml` from `0.8.2` to `0.9.0` per Constitution
      Principle IV (MINOR — backward-compatible feature addition)
- [ ] T022 Manually run `specs/016-interactive-cli-mode/quickstart.md` steps 1-8 against a real
      terminal to validate the full demo flow end to end
- [ ] T023 Run the full test suite (`uv run pytest`) and confirm zero regressions (SC-004)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational only
- **User Story 2 (Phase 4)**: Depends on Foundational; also modifies output first wired up by
  User Story 1 (T010, T008), so is implemented after US1 even though its own acceptance
  criteria are independently testable
- **User Story 3 (Phase 5)**: Depends on Foundational; wraps the single-conversation flow User
  Story 1 wired up (T010), so is implemented after US1 — matches spec.md's explicit note that
  US3 "depends on Story 1 and 2 already working"
- **Polish (Phase 6)**: Depends on all three user stories being complete

### Within Each User Story

- Tests MUST be written and FAIL before implementation (Constitution Principle I)
- Story complete and checkpointed before moving to the next priority

### Parallel Opportunities

- T001 and T002 (Setup) can run in parallel
- T003/T005/T007 (Foundational tests, different files/functions) can be written in parallel;
  each blocks only its own paired implementation task (T004/T006/T008)
- T009 (US1 tests) has no same-phase parallel partner (all target one new behavior in one file)
- T012 and T013 (US2 tests, then the `_print_turn` implementation) can start once Foundational
  and US1 are done; T014 and T015 both depend on T013 but touch different call sites
  (`run_interactive` vs `_run_conversation`) and could be done in parallel once T013 lands
- T016 (US3 tests) can be written as soon as Foundational is done, in parallel with US2 work,
  since it targets the loop-wrapping behavior rather than `_print_turn`
- T020 and T021 (Polish) can run in parallel

---

## Parallel Example: Foundational Phase

```bash
# Launch all three foundational test-writing tasks together:
Task: "Write failing dispatch tests in tests/unit/test_cli.py (T003)"
Task: "Write failing Console non-tty test in tests/unit/test_interactive.py (T005)"
Task: "Write failing _run_conversation thread_id/interrupt test in tests/unit/test_interactive.py (T007)"
```

## Parallel Example: User Story 2

```bash
# Once T013 (_print_turn) lands, these two call-site updates touch different functions:
Task: "Replace run_interactive()'s plain echo/print calls with _print_turn (T014)"
Task: "Route _run_conversation's interrupt print/echo through _print_turn (T015)"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: run `uv run customer-support-fde` with no arguments; confirm banner,
   prompt, thinking indicator, and a plain result — independent of any styling or looping work
5. Demo if ready (plain-text single-question interactive mode is already a real improvement)

### Incremental Delivery

1. Setup + Foundational → shared engine ready
2. Add User Story 1 → validate independently → MVP demoable
3. Add User Story 2 → validate independently → transcript now fully labeled
4. Add User Story 3 → validate independently → full multi-conversation demo flow works
5. Polish → regression-proof the untouched paths, bump version, run full suite

### Parallel Team Strategy

With multiple developers, after Foundational is done: one developer can take US2 (styling,
`_print_turn` and its call-site wiring) while another takes US3 (loop, exit, error handling) —
both build on US1's `run_interactive()`/`_run_conversation()` shape but touch largely
non-overlapping code paths (rendering vs. looping), so conflicts should be limited to the shared
call sites noted in T014/T015/T017.

---

## Notes

- `[P]` tasks touch different files or independent call sites with no completed-task dependency
  between them
- `[Story]` labels map every user-story-phase task back to spec.md's US1/US2/US3 for traceability
- Every test task's actual test code MUST carry the one-line `(base)`/`(edge)`/`(error)`/
  `(regression)` tag comment required by Constitution Principle I — noted per test above, but
  restated here as a blanket requirement for whoever implements each task
- No task in this list modifies `graph.py`, `state.py`, `db.py`, or any file under `nodes/` —
  per plan.md's Structure Decision, this feature is presentation/input-loop only
- Commit after each task or logical group; stop at any checkpoint to validate a story
  independently before continuing
