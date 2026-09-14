# Feature Specification: Ticket Markdown Generation

**Feature Branch**: `011-ticket-markdown-generation`

**Created**: 2026-09-14

**Status**: Draft

**Input**: User description: "Ticket Node will generate a ticket based on the customer interaction (order, support, and refund). This ticket will be a markdown file and outputted into the ticket folder. For the order/support agent, the output should just be the customer order and total. If the customer didn't order anything and just ask support question, don't output anything. For the refund agent, the ticket should include the issue or complaint, customer sentiment, order id, and whether a refund request was created or not."

## Clarifications

### Session 2026-09-14

- Q: What should determine each ticket file's name so it stays unique and never overwrites another ticket? → A: Order ID only (a new ticket for the same order and ticket type replaces the prior file for that order).
- Q: If writing the ticket file fails (e.g. a disk or permission error), should the customer-facing interaction still complete normally? → A: Yes, complete normally and just log the failure.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Order ticket produced for a confirmed order (Priority: P1)

A customer chats with the order/support agent, browses the menu, and confirms an order. Once the interaction concludes, a markdown ticket describing exactly what was ordered and the total price is saved to the tickets folder so restaurant staff can act on it without replaying the conversation.

**Why this priority**: This is the core, most common outcome of a customer interaction and the primary reason a ticket system exists — staff need a record of what to prepare and charge.

**Independent Test**: Run a conversation that ends in a confirmed order and verify a single markdown file appears in the tickets folder listing the ordered items and the total.

**Acceptance Scenarios**:

1. **Given** a customer has confirmed an order of one or more menu items, **When** the order/support interaction concludes, **Then** a markdown ticket file is written to the tickets folder containing the list of ordered items and the order total.
2. **Given** a customer confirmed an order, **When** the ticket is generated, **Then** the ticket contains no unrelated content (e.g., no general support Q&A transcript, no refund-specific fields).

---

### User Story 2 - No ticket for support-only questions (Priority: P2)

A customer asks the order/support agent a question (e.g., about an ingredient or allergy) but never places an order. Because nothing was ordered, no ticket should be created — staff should not have to sift through tickets that represent no actionable outcome.

**Why this priority**: Prevents ticket-folder noise and false work items; important for staff trust in the ticket system, but secondary to correctly capturing real orders.

**Independent Test**: Run a conversation with the order/support agent that only asks questions and never confirms an order; verify no new file is written to the tickets folder.

**Acceptance Scenarios**:

1. **Given** a customer only asks menu/support questions and never confirms an order, **When** the interaction concludes, **Then** no ticket file is written for that interaction.
2. **Given** a customer starts building an order but abandons it before confirming, **When** the interaction concludes, **Then** no ticket file is written for that interaction.

---

### User Story 3 - Refund ticket captures complaint outcome (Priority: P1)

A customer contacts the refund agent about an issue with a past order. Once the interaction concludes, a markdown ticket is saved recording the complaint, the customer's sentiment, the related order ID, and whether a refund request was actually created, so staff and management can review complaint handling and outcomes.

**Why this priority**: Refund/complaint interactions carry financial and customer-satisfaction consequences and must always leave an auditable record; equally critical to the order ticket path.

**Independent Test**: Run a conversation with the refund agent that ends with (a) a refund request created, and separately (b) no refund request created, and verify each produces a ticket file with the complaint, sentiment, order ID, and correct refund-created status.

**Acceptance Scenarios**:

1. **Given** a customer describes an issue with an order and a refund request is created as a result, **When** the refund interaction concludes, **Then** a markdown ticket is written containing the complaint/issue, the customer's sentiment, the order ID, and an indication that a refund request was created.
2. **Given** a customer describes an issue with an order but no refund request is created (e.g., the complaint falls outside policy), **When** the refund interaction concludes, **Then** a markdown ticket is written containing the complaint/issue, the customer's sentiment, the order ID, and an indication that no refund request was created.

---

### Edge Cases

- What happens when a refund interaction cannot resolve the order ID (lookup fails or was never provided)? The ticket is still generated, with the order ID field marked as unknown/not found, and the filename falls back to a fallback identifier (see FR-008) so multiple unresolved-order tickets do not collide.
- What happens when the tickets folder does not yet exist on disk? It is created automatically before the first ticket is written.
- What happens when two tickets are generated in the same interaction session but for different orders or ticket types (e.g., customer orders, then later opens a refund conversation about a different order)? Each gets its own ticket file since the order ID and/or ticket type differ.
- What happens when a new ticket is generated for the same order ID and ticket type as an earlier ticket (e.g., the customer's order is re-ticketed, or a second refund conversation happens about the same order)? The new file replaces the earlier ticket for that order and type — this is expected behavior of order-ID-based naming, not a defect.
- What happens if the ticket file cannot be written (e.g., a disk or permission error)? The customer-facing interaction still completes normally; the failure is logged rather than shown to the customer or blocking the conversation (see FR-011).
- What happens when the customer's sentiment could not be determined? The refund ticket still generates, with sentiment recorded as unavailable/neutral rather than blocking ticket creation.
- What happens when an order/support interaction includes both a confirmed order and unrelated support questions? Only the order and total are recorded in the ticket; the support Q&A content is not included.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST generate a markdown ticket file whenever an order/support interaction concludes with a confirmed order.
- **FR-002**: The order ticket MUST contain only the ordered items (with quantities) and the order total — no other conversation content.
- **FR-003**: System MUST NOT generate any ticket file when an order/support interaction concludes without a confirmed order (support-only questions, or an abandoned/unconfirmed order).
- **FR-004**: System MUST generate a markdown ticket file whenever a refund-agent interaction concludes.
- **FR-005**: The refund ticket MUST contain the customer's issue/complaint, the customer's sentiment, the related order ID, and whether a refund request was created.
- **FR-006**: Ticket files MUST be written into a single, designated tickets folder.
- **FR-007**: System MUST create the tickets folder automatically if it does not already exist.
- **FR-008**: Each generated ticket's filename MUST be derived from its ticket type (order/support vs. refund) and its order ID, so staff can locate the ticket for a given order at a glance; a new ticket for the same order ID and ticket type MUST replace the previous file for that order and type. When the order ID is unknown (see FR-010), the filename MUST instead use a fallback identifier that keeps unresolved-order tickets from colliding with one another.
- **FR-009**: Ticket content MUST be plain, human-readable markdown that a support staff member can read directly without additional tooling.
- **FR-010**: When the order ID cannot be determined for a refund ticket, the ticket MUST still be generated with the order ID field explicitly marked as unknown rather than omitted or causing a failure.
- **FR-011**: If a ticket file fails to be written (e.g., disk or permission error), the customer-facing interaction MUST still complete normally; the failure MUST be logged rather than surfaced to the customer or allowed to block the conversation.

### Key Entities *(include if feature involves data)*

- **Order/Support Ticket**: Represents the outcome of a concluded order/support interaction that resulted in a confirmed order. Attributes: ordered items (name and quantity), order total.
- **Refund Ticket**: Represents the outcome of a concluded refund-agent interaction. Attributes: issue/complaint description, customer sentiment, related order ID (or unknown), whether a refund request was created (yes/no).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of interactions that end with a confirmed order produce exactly one order ticket file containing the correct items and total.
- **SC-002**: 100% of support-only interactions (no order confirmed) produce zero ticket files.
- **SC-003**: 100% of concluded refund interactions produce exactly one refund ticket file containing the complaint, sentiment, order ID, and refund-created status.
- **SC-004**: A staff member can determine the full outcome of any past interaction (what was ordered, or what the complaint and refund outcome were) by reading one ticket file, without needing the original conversation transcript.
- **SC-005**: No ticket file for one order is ever overwritten by a ticket for a different order or by a ticket of a different type; a ticket file is replaced only by a newer ticket of the same type for the same order.
- **SC-006**: A ticket file failing to write never prevents a customer's interaction from completing.

## Assumptions

- "The ticket folder" refers to a single, consistently named directory within the project dedicated to generated tickets, distinct from other project folders such as specs.
- The refund agent is only engaged for post-order issues/complaints, so — unlike the order/support path — every concluded refund interaction is expected to produce a ticket; there is no "nothing happened" case to suppress for refunds.
- "Whether a refund request was created" is represented in the ticket as a simple yes/no outcome, separate from any more detailed internal policy reasoning.
- One ticket file is generated per concluded interaction (i.e., per conversation session reaching its end state for that agent), not per individual message turn.
- Ticket generation is triggered automatically at the point an interaction reaches its existing conclusion for the order/support or refund path; no manual trigger is required.
- Replacing a ticket file when a new one is generated for the same order ID and ticket type is acceptable: the ticket folder is meant to reflect the latest known record per order, not a full history of every interaction on that order.
- The fallback identifier used when an order ID is unknown (FR-008) only needs to prevent unresolved-order tickets from colliding with each other; it does not need to be predictable or human-meaningful.
