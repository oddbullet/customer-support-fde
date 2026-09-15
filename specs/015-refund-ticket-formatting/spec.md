# Feature Specification: Refund Ticket Formatting Fix

**Feature Branch**: `015-refund-ticket-formatting`

**Created**: 2026-09-15

**Status**: Draft

**Input**: User description: "Fix the Refund Ticket Generation. Everything is in bold markdown. Only the header need to be bold. Everything else can just be after the header."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Staff read a clearly formatted refund ticket (Priority: P1)

A restaurant staff member opens a generated refund ticket to review a customer's complaint and refund outcome. Today, every line in the ticket (the order ID, the issue, the sentiment, the refund status) is rendered in bold markdown, making the whole document visually heavy and harder to scan at a glance. After the fix, only the ticket's field labels (e.g. "Order ID", "Issue", "Customer Sentiment", "Refund Request Created") are bold, and the corresponding values are plain text following the label, so the ticket is easier to read and visually distinguishes labels from content.

**Why this priority**: This is the entire scope of the requested fix and the only user-facing outcome — correcting it delivers the full value of this feature.

**Independent Test**: Generate a refund ticket from a concluded refund interaction and visually/structurally verify that only field labels are bold markdown and field values are plain text.

**Acceptance Scenarios**:

1. **Given** a concluded refund interaction that produces a ticket, **When** the ticket markdown file is generated, **Then** each field label (Order ID, Issue, Customer Sentiment, Refund Request Created) is rendered in bold markdown and its value is rendered as plain (non-bold) text immediately after the label.
2. **Given** an existing refund ticket generated before this fix (all-bold formatting), **When** a new refund ticket is generated for that same order, **Then** the replacement ticket uses the corrected label-bold/value-plain formatting.
3. **Given** a refund ticket is generated, **When** compared to the current behavior, **Then** the ticket's document title/header (e.g. "# Refund Ticket") is unaffected by this change and remains formatted as before.

---

### Edge Cases

- What happens when a field value is missing or unknown (e.g. order ID could not be resolved, per existing fallback behavior)? The label is still bold and the "unknown"/fallback value is still rendered as plain text after it — the missing-value handling itself is unchanged, only the bolding is corrected.
- What happens to the order/support ticket format (non-refund tickets)? Out of scope — this fix applies only to the refund ticket's field formatting; the order/support ticket template is not changed.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The refund ticket generator MUST render each field label (Order ID, Issue, Customer Sentiment, Refund Request Created) in bold markdown.
- **FR-002**: The refund ticket generator MUST render each field's value as plain, non-bold text, placed after its corresponding bold label.
- **FR-003**: The refund ticket generator MUST NOT change the ticket's document title/header formatting or any other structural element outside of the field label/value styling.
- **FR-004**: The refund ticket generator MUST NOT change which fields are included in the ticket, their order, or the underlying data/logic used to populate them — only the markdown styling of labels versus values changes.
- **FR-005**: This formatting correction MUST apply to every newly generated refund ticket going forward; previously generated ticket files on disk are not retroactively rewritten by this fix.

### Key Entities *(include if feature involves data)*

- **Refund Ticket**: Unchanged in content/fields from the existing specification ([[011-ticket-markdown-generation]]) — issue/complaint, customer sentiment, order ID, refund-created status. Only the markdown presentation of each field's label versus value changes.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of newly generated refund tickets show field labels in bold and field values in plain text, with no field line rendered entirely in bold.
- **SC-002**: A staff member can visually distinguish a field's label from its value in a generated refund ticket without reading the raw markdown source.
- **SC-003**: No existing refund ticket field, its data, or its order within the document is altered by this fix — only the bold/plain styling changes.

## Assumptions

- "The header" refers to the ticket's top-level document title (e.g. "# Refund Ticket"), which should remain bold/heading-styled as it already is; the fix applies to the field label/value lines beneath it.
- The intended format for each field line is: a bold label followed by a plain-text value on the same line (e.g. `**Order ID:** N0690YR9`), consistent with the example ticket currently on disk apart from the value's bolding.
- This is a formatting-only fix to the refund ticket template; no changes to ticket file naming, storage location, generation triggers, or the order/support ticket path are in scope.
