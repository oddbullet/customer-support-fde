# Phase 0 Research: Refund Ticket Formatting Fix

No `NEEDS CLARIFICATION` markers remain in the Technical Context — this is a small, fully
scoped bug fix with no open technical unknowns. One formatting decision is recorded below for
traceability.

## Decision: Field line format

- **Decision**: Render each refund ticket field as `**<Label>:** <value>` — bold label including
  the trailing colon, one space, then the plain-text value — rather than the current
  `**<Label>: <value>**` (entire line bold).
- **Rationale**: Matches the spec's requirement (FR-001, FR-002) that only the label be
  emphasized, and matches the assumption recorded in `spec.md` that the target shape is
  `**Order ID:** N0690YR9`. This is also the conventional markdown idiom for a bold label
  followed by a plain value (consistent with how the existing order ticket already renders
  `**Total**: $31.40` — label bold, value plain).
- **Alternatives considered**:
  - Leave the colon outside the bold span (`**Order ID**: value`) — rejected only as a minor
    stylistic variant; either placement satisfies "only the label is bold," but
    `**Label:** value` was chosen to match the existing `_render_order_ticket`'s `**Total**:`
    convention as closely as possible for visual consistency across both ticket types. (Note:
    order ticket uses `**Total**: $X` with colon outside; refund ticket will use
    `**Label:** value` with colon inside — both keep the bold span limited to the label text
    only, satisfying the spec either way. The implementer should pick one and apply it
    consistently across all four refund fields.)
  - Use markdown table syntax for fields — rejected as unnecessary complexity (Principle III,
    YAGNI) for a four-line document; no requirement calls for tabular presentation.

## Decision: Scope of change

- **Decision**: Modify only `_render_refund_ticket` in `src/customer_support_fde/tickets.py`.
  `_render_order_ticket`, `write_order_ticket`, `write_refund_ticket`, `_write_ticket_file`, and
  `tickets_dir` are unchanged.
- **Rationale**: Spec FR-003/FR-004 and the Edge Cases section explicitly scope this fix to the
  refund ticket's field styling only; the order ticket already renders values as plain text
  after a bold label/heading and is not affected by the reported bug.
- **Alternatives considered**: None — scope is unambiguous from the spec and bug report.

**Output**: All unknowns resolved; ready for Phase 1.
