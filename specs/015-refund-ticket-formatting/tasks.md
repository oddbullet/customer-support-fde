---

description: "Task list for Refund Ticket Formatting Fix"
---

# Tasks: Refund Ticket Formatting Fix

**Input**: Design documents from `/specs/015-refund-ticket-formatting/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [quickstart.md](./quickstart.md)

**Tests**: Included and REQUIRED — this project's constitution (Principle I, Test-First,
NON-NEGOTIABLE) mandates a failing test before every implementation change, and every test
case carries a one-line `(base)`/`(edge)`/`(error)`/`(regression)` comment per the constitution.

**Organization**: This feature has a single user story (US1, P1) — the entire fix. There is no
foundational/shared-prerequisite phase because nothing is shared across multiple stories.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1)
- Exact file paths are included in each description

## Path Conventions

Single project layout (existing): `src/customer_support_fde/tickets.py`,
`tests/unit/test_tickets.py` at repository root.

---

## Phase 1: Setup

**Purpose**: Confirm a clean, known-good starting point before touching `tickets.py`.

- [X] T001 At the repository root, run `uv run pytest tests/unit/test_tickets.py -v` and
      confirm all existing tests pass before any change, establishing the baseline this fix
      must not regress.

**Checkpoint**: Baseline green — safe to begin.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Not applicable** — there is only one user story and no shared infrastructure, model, or
service to extract first (see [research.md](./research.md), "Decision: Scope of change"). Proceed
directly to Phase 3.

---

## Phase 3: User Story 1 - Staff read a clearly formatted refund ticket (Priority: P1) 🎯 MVP

**Goal**: Refund tickets render each field as a bold label followed by a plain-text value
(e.g. `**Order ID:** N0690YR9`) instead of the entire field line in bold, while the
`# Refund Ticket` header and all field content/order stay unchanged.

**Independent Test**: Call `tickets.write_refund_ticket(...)` (or run the unit tests) and
verify the produced markdown has bold labels with plain values, per
[quickstart.md](./quickstart.md).

### Tests for User Story 1 ⚠️

> **NOTE: Write these tests FIRST in `tests/unit/test_tickets.py`, run them, and confirm they FAIL before touching `tickets.py`.**

- [X] T002 [P] [US1] In `tests/unit/test_tickets.py`, add a failing test asserting
      `_render_refund_ticket` (or the content written by `write_refund_ticket`) renders each
      of the four fields as `**Order ID:** K7QP3M9X`, `**Issue:** <issue text>`,
      `**Customer Sentiment:** <sentiment>`, and `**Refund Request Created:** Yes`/`No` — bold
      label with trailing colon inside the bold span, one space, then a plain-text value — for
      a fully-populated refund ticket dict (FR-001, FR-002). Tag it `(regression)` since it
      guards against the reported all-bold bug.
- [X] T003 [P] [US1] In `tests/unit/test_tickets.py`, add a failing test asserting the
      rendered content does **not** contain any of the old all-bold field shapes (e.g.
      `**Order ID: K7QP3M9X**`, `**Issue: ` immediately followed later by `**` closing the
      whole line) — i.e. no field line has its value inside the bold span (FR-001, SC-001).
      Tag it `(regression)`.
- [X] T004 [P] [US1] In `tests/unit/test_tickets.py`, add a failing test asserting the
      `# Refund Ticket` header line is emitted exactly as `# Refund Ticket` (unchanged,
      unaffected by the label/value styling change) (FR-003). Tag it `(regression)`.
- [X] T005 [US1] In `tests/unit/test_tickets.py`, extend
      `test_write_refund_ticket_unknown_order_id` and
      `test_write_refund_ticket_renders_missing_sentiment_and_issue` (or add new assertions
      alongside them) to confirm the fallback values (`Unknown`, `Not recorded`, `unavailable`)
      still appear as plain text immediately after their bold labels, not inside the bold span
      (edge case from spec.md). Tag additions `(edge)`.
- [X] T006 [US1] Run `uv run pytest tests/unit/test_tickets.py -v` and confirm the new/extended
      tests from T002-T005 FAIL against the current implementation (red), while the pre-existing
      tests still pass unmodified.

### Implementation for User Story 1

- [X] T007 [US1] In `src/customer_support_fde/tickets.py`, modify `_render_refund_ticket` so
      each of the four field lines uses the format `**<Label>:** <value>` (bold label with
      trailing colon, one space, plain-text value) instead of wrapping the entire line
      (`**<Label>: <value>**`) in bold. Do not change: the `# Refund Ticket` header line, the
      set of fields, their order, the blank-line spacing between fields, the fallback values
      (`Unknown`, `Not recorded`, `unavailable`), or any other function in the file (FR-001
      through FR-004; scope confirmed in research.md).
- [X] T008 [US1] Run `uv run pytest tests/unit/test_tickets.py -v` and confirm every test
      (T002-T005's new/extended tests plus all pre-existing tests) now passes (green).

**Checkpoint**: User Story 1 — and the entire feature — is complete, independently verified, and
matches [quickstart.md](./quickstart.md)'s expected output shape.

---

## Final Phase: Polish & Cross-Cutting Concerns

**Purpose**: Confirm the fix is fully unregressed and versioned per the constitution.

- [X] T009 In `pyproject.toml`, bump `version` from `0.8.1` to `0.8.2` (PATCH) per Constitution
      Principle IV, since this is a backward-compatible bug fix with no API/behavior contract
      change beyond the markdown styling.
- [X] T010 [P] Follow [quickstart.md](./quickstart.md) section 2 (manual inspection): generate a
      refund ticket for order `N0690YR9` with `refund_created=False` and confirm
      `tickets/refund-N0690YR9.md` matches the expected bold-label/plain-value shape shown
      there, replacing the previously all-bold file described in the original bug report.
- [X] T011 [P] Run `uv run pytest` (full suite) at the repository root and confirm no
      regressions outside `test_tickets.py` — in particular `tests/unit/test_tickets.py -k
      order_ticket` (per quickstart.md section 3) and any refund-agent/ticket-node tests that
      exercise `write_refund_ticket`.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — run first.
- **Foundational (Phase 2)**: Not applicable for this feature.
- **User Story 1 (Phase 3)**: Depends on Setup (T001) completion.
- **Polish (Final Phase)**: Depends on User Story 1 (Phase 3) completion.

### User Story Dependencies

- **User Story 1 (P1)**: The only user story; no dependency on any other story.

### Within User Story 1

- T002, T003, T004 (new tests) can be written in parallel — different assertions, same file,
  no shared mutable state, so they are marked [P] as independent additions; apply them as
  separate edits to `tests/unit/test_tickets.py` before running the suite.
- T005 depends on the existing tests it extends already being present (they are — no new
  dependency).
- T006 (confirm red) depends on T002-T005.
- T007 (implementation) depends on T006 confirming the tests fail first (Constitution
  Principle I).
- T008 (confirm green) depends on T007.

### Parallel Opportunities

- T002, T003, T004 can be drafted in parallel (distinct test functions in the same file —
  coordinate final edits to avoid overwriting each other, or apply sequentially if working
  solo).
- T010 and T011 (Polish phase) can run in parallel — independent verification activities.

---

## Parallel Example: User Story 1

```bash
# Draft all new tests for User Story 1 together (same file, distinct functions):
Task: "Add (regression) test for bold-label/plain-value shape in tests/unit/test_tickets.py"
Task: "Add (regression) test that old all-bold shape is absent in tests/unit/test_tickets.py"
Task: "Add (regression) test that '# Refund Ticket' header is unchanged in tests/unit/test_tickets.py"
```

---

## Implementation Strategy

### MVP First (and Only) Scope

1. Complete Phase 1: Setup (T001).
2. Skip Phase 2: Foundational (not applicable).
3. Complete Phase 3: User Story 1 (T002-T008) — tests red, then implementation, then green.
4. **STOP and VALIDATE**: Confirm `tests/unit/test_tickets.py` passes in full.
5. Complete Final Phase: Polish (T009-T011) — version bump, manual spot-check, full-suite
   regression check.

This feature has no incremental-delivery slicing beyond its single user story — the fix is the
MVP.

---

## Notes

- [P] tasks = distinct test functions/edits with no interdependency, though they share one file.
- Only one [Story] label (US1) exists for this feature.
- Verify tests fail (T006) before implementing (T007), per Constitution Principle I.
- Commit after the test-red state (T002-T006) and again after the implementation-green state
  (T007-T008), or as one commit once both are verified — follow existing repository commit
  conventions.
- Avoid: touching `_render_order_ticket`, `write_order_ticket`, `write_refund_ticket`'s
  filename logic, or `_write_ticket_file` — none are in scope for this fix.
