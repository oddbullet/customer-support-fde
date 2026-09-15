# Implementation Plan: Refund Ticket Formatting Fix

**Branch**: `015-refund-ticket-formatting` | **Date**: 2026-09-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/015-refund-ticket-formatting/spec.md`

## Summary

`_render_refund_ticket` in `src/customer_support_fde/tickets.py` currently wraps each entire
field line (label **and** value) in markdown bold, e.g. `**Order ID: N0690YR9**`. Per the spec,
only the field label should be bold, with the value following as plain text, e.g.
`**Order ID:** N0690YR9`. This is a pure string-formatting fix inside one existing function; no
data, control flow, filenames, or the document header (`# Refund Ticket`) change.

## Technical Context

**Language/Version**: Python >=3.14 (per `pyproject.toml`)

**Primary Dependencies**: None new — uses only what `tickets.py` already imports (`pathlib`,
stdlib string formatting).

**Storage**: Flat markdown files under the tickets folder (`tickets_dir()`); no schema/DB change.

**Testing**: pytest (`tests/unit/test_tickets.py`), per Constitution Principle I (Test-First).

**Target Platform**: Cross-platform (Windows/Linux) CLI-invoked Python module — no platform-
specific behavior involved.

**Project Type**: Single project (existing `src/customer_support_fde/` library, per Principle II).

**Performance Goals**: N/A — negligible-cost string formatting change.

**Constraints**: MUST NOT alter field content, field order, filenames, or the `# Refund Ticket`
header (FR-003, FR-004).

**Scale/Scope**: One function (`_render_refund_ticket`) in one file; no new files, entities, or
public interfaces.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Test-First (NON-NEGOTIABLE)**: A failing regression test must be added to
  `tests/unit/test_tickets.py` asserting the label-bold/value-plain shape (e.g. that the
  rendered content contains `"**Order ID:** N0690YR9"` and does NOT contain the old
  all-bold shape `"**Order ID: N0690YR9**"`) before `_render_refund_ticket` is changed. Tagged
  `(regression)` per the constitution's per-test comment convention. **PASS** (planned in
  `tasks.md`, not yet written — no implementation has landed).
- **II. Library-First & CLI Interface**: No new module or CLI surface is introduced; the existing
  `tickets.py` library function is corrected in place. **PASS**.
- **III. Simplicity (YAGNI)**: The fix changes only the f-string templates inside
  `_render_refund_ticket` — no new abstraction, parameter, or config option is introduced.
  **PASS**.
- **IV. Observability & Versioning**: This is plain file-rendering logic, not an agent/LLM
  invocation, so no new Phoenix tracing is required (consistent with how `tickets.py` is
  already untraced). This is a backward-compatible bug fix → PATCH version bump (0.8.1 →
  0.8.2) per semantic versioning. **PASS**.

No violations; Complexity Tracking section is not needed.

## Project Structure

### Documentation (this feature)

```text
specs/015-refund-ticket-formatting/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

No `contracts/` directory: this fix touches only an internal rendering function with no
external/public interface change (see Phase 1 below).

### Source Code (repository root)

```text
src/customer_support_fde/
└── tickets.py            # _render_refund_ticket() — the function being fixed

tests/unit/
└── test_tickets.py        # Existing refund-ticket tests + new (regression) formatting test
```

**Structure Decision**: Single project (existing layout under `src/customer_support_fde/` and
`tests/unit/`, unchanged from feature 011). This fix adds no new directories or modules.

## Complexity Tracking

*No Constitution Check violations — this section is not applicable.*
