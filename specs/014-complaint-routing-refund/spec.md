# Feature Specification: Complaint Routing to Refund Agent

**Feature Branch**: `014-complaint-routing-refund`

**Created**: 2026-09-15

**Status**: Draft

**Input**: User description: "The router should know to route to refund_agent for a complaint."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Complaint without an explicit refund ask is routed to the refund agent (Priority: P1)

A customer describes a problem with a past order — food arrived cold, an item was missing, the order was late, the dish tasted wrong — without explicitly asking for money back. The router recognizes this as a complaint and hands it off to the refund agent, the same as it would for an explicit refund request.

**Why this priority**: Customers voicing dissatisfaction rarely open with "I want a refund" — they describe what went wrong. If the router only recognizes explicit refund language, most real complaints would be misrouted to the order/support agent, which has no way to log or act on them.

**Independent Test**: Can be fully tested by submitting a variety of past-order complaint messages that never use refund/money-back language and confirming the router selects the refund destination with a sentiment assessment attached.

**Acceptance Scenarios**:

1. **Given** a customer says "My order arrived 45 minutes late and the food was cold", **When** the request reaches the router, **Then** it is routed to the refund agent with the full message and a sentiment assessment.
2. **Given** a customer says "The spring rolls I got were missing from my bag", **When** the request reaches the router, **Then** it is routed to the refund agent with the full message and a sentiment assessment.
3. **Given** a customer says "This is the second time my order has been wrong", **When** the request reaches the router, **Then** it is routed to the refund agent, not the order/support agent.

---

### User Story 2 - Complaint paired with an explicit refund request is still routed as one case (Priority: P2)

A customer both describes what went wrong with a past order and explicitly asks for a refund in the same message. The router treats this as a single refund-destination case rather than treating the complaint and the refund ask as competing or ambiguous signals.

**Why this priority**: This is the most common real-world phrasing (a complaint that motivates a refund ask), and it must not be mistaken for the "mixed signal" case that triggers a clarifying question — that case is reserved for messages that mix order/support intent with refund/complaint intent, not for messages that are entirely about a past order.

**Independent Test**: Can be fully tested by submitting messages that combine a complaint description with an explicit refund ask and confirming the router routes directly to the refund agent without asking a clarifying question.

**Acceptance Scenarios**:

1. **Given** a customer says "My order arrived cold and an hour late, I want my money back", **When** the request reaches the router, **Then** it is routed directly to the refund agent with no clarifying question asked.
2. **Given** a customer says "The dish had peanuts in it even though I asked for none — can I get a refund?", **When** the request reaches the router, **Then** it is routed directly to the refund agent.

---

### User Story 3 - Complaint routing behavior is verifiable end-to-end (Priority: P2)

A developer or reviewer needs confidence that complaint-style messages — not just explicit refund requests — consistently reach the refund agent before relying on the refund agent's downstream complaint-handling behavior.

**Why this priority**: The refund agent already distinguishes complaints from refund requests once it receives them (logging a complaint versus processing a refund); none of that logic can be exercised if complaints never arrive at the refund agent in the first place.

**Independent Test**: Can be fully tested by running a labeled set of complaint-only, refund-request, and mixed-signal messages through the router and confirming each reaches the expected destination.

**Acceptance Scenarios**:

1. **Given** a labeled set of sample messages covering complaint-only, explicit-refund, order/support, and mixed-signal scenarios, **When** each sample is run through the router, **Then** the destination chosen for every complaint-only and explicit-refund sample is the refund agent.

---

### Edge Cases

- What happens when a complaint is phrased mildly or without strong negative language (e.g., "just letting you know the soup was lukewarm")? The router still classifies it as a complaint and routes to the refund agent with a best-effort sentiment assessment, rather than requiring strong language to recognize it as a complaint.
- What happens when a message complains about a past order and also asks an unrelated menu/ordering question (e.g., "my last order was cold, and also does the mapo tofu have peanuts?")? This remains a mixed-signal case per the router's existing ambiguity handling — the customer is asked to choose between placing an order, asking a general question, or requesting a refund; it is not silently routed to refund.
- What happens when a customer complains about something other than a past order (e.g., the restaurant's hours, the dining room, or the website)? This has no past-order signal, so it is treated as order/support or unclear per the router's existing classification, not routed to the refund agent.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST classify a customer message describing dissatisfaction with a past order as a complaint belonging to the refund destination, whether or not the message explicitly asks for a refund or money back.
- **FR-002**: The system MUST NOT require explicit refund/money-back language as a precondition for routing a past-order complaint to the refund destination.
- **FR-003**: The system MUST route a message that both describes a past-order complaint and explicitly requests a refund to the refund destination directly, without treating it as a mixed-signal/ambiguous case.
- **FR-004**: The system MUST produce a sentiment assessment for every complaint routed to the refund destination, consistent with existing refund-destination behavior.
- **FR-005**: The system MUST continue to treat a message that mixes a past-order complaint with an unrelated order/support question (e.g., a menu question) as a mixed-signal case requiring the existing clarifying question, rather than silently routing it to refund.
- **FR-006**: The system MUST NOT route a complaint that has no connection to a past order (e.g., about hours, ambiance, or the website) to the refund destination.

### Key Entities

- **Complaint**: A customer message expressing dissatisfaction about a past order (e.g., wrong, missing, late, or unsatisfactory items) that does not necessarily include an explicit refund request. Always resolves to the refund Routing Decision when it is the sole or dominant signal in the message.
- **Refund Request**: A customer message explicitly asking for money back for a past order, with or without an accompanying complaint description. Always resolves to the refund Routing Decision.
- **Routing Decision**: The destination chosen for a Customer Request — order/support or refund — as defined by the router. A message that is entirely a Complaint, entirely a Refund Request, or both, resolves to refund.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: When evaluated against a representative labeled set of complaint-only messages (no explicit refund language), the router selects the refund destination at least 90% of the time.
- **SC-002**: 100% of messages that combine a past-order complaint with an explicit refund request are routed directly to the refund destination, with none incorrectly triggering the mixed-signal clarifying question.
- **SC-003**: 100% of messages routed to the refund destination as a result of complaint recognition arrive with a sentiment assessment attached.

## Assumptions

- This feature refines the classification behavior of the router established in the router agent feature (complaint recognition), without changing the router's two-destination-plus-unclear model, its sentiment rules, or its clarifying-question behavior for genuinely mixed order/support-and-refund signals.
- "Complaint" and "refund request" are both handled by the refund agent once routed there (it already distinguishes between logging a complaint and processing a refund internally), so this feature only needs to ensure both reach that single destination — it does not change how the refund agent behaves after receiving them.
- A complaint with no relation to a past order (e.g., about restaurant hours or ambiance) falls outside this feature's scope and continues to follow the router's existing order/support-vs-unclear handling.
