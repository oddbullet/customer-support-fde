# Feature Specification: Router Agent with Sentiment-Aware Refund Handoff

**Feature Branch**: `001-router-agent`

**Created**: 2026-09-09

**Status**: Draft

**Input**: User description: "Create a router agent that will look at the user request and determind if it should be sent to the order/support agent or refund agent. Additionally, it should give a sentiment analysist that will only be given to the refund agent. The way the information will be pass to the next agents is through langgraph state. It should include full user query and sentiment. The test should include agent trajectory test to determind if it is routing correctly. The api will be sent through openrouter. Connect this agent to two placeholder node for the order/support agent and refund agent."

## Clarifications

### Session 2026-09-09

- Q: What language(s) must the router be able to classify and assess sentiment in? → A: English only
- Q: What minimum routing accuracy should the router be required to hit against the labeled test set before this feature is considered done? → A: 90%
- Q: How many sentiment categories should the refund agent receive for each request? → A: 3 categories: positive, neutral, negative
- Q: What should the router do when a request is ambiguous or mixes both ordering/question and refund signals, instead of silently defaulting? → A: Ask the customer directly to choose one of three options — placing an order, asking a general question, or requesting a refund — and route based on their answer. No destination is guessed on the customer's behalf.
- Q: If that clarifying answer resolves to refund, where does the sentiment assessment come from? → A: The sentiment already produced by the original classification pass over the customer's message is forwarded as-is; the customer is never asked a separate question about how they feel.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - General question routed to order/support (Priority: P1)

A customer asks a menu, ingredient, allergy, or ordering question. The system reads the request and determines it is a general support/ordering matter, then hands it off to the order/support agent along with the customer's full original question.

**Why this priority**: This is the most common entry point for the overall support system — without correct routing here, no downstream agent can help the customer at all. It is the simplest path and the foundation the rest of the system builds on.

**Independent Test**: Can be fully tested by submitting a variety of menu/ordering-style requests and confirming the router selects the order/support destination and forwards the complete, unaltered request text.

**Acceptance Scenarios**:

1. **Given** a customer asks "What's in the kung pao chicken, does it have peanuts?", **When** the request reaches the router, **Then** it is routed to the order/support agent with the full question intact.
2. **Given** a customer asks "I'd like to order two spring rolls and a fried rice", **When** the request reaches the router, **Then** it is routed to the order/support agent with the full question intact.
3. **Given** a request is routed to the order/support agent, **When** the handoff occurs, **Then** no sentiment assessment is attached to the information passed along.

---

### User Story 2 - Complaint or refund request routed with sentiment (Priority: P1)

A customer expresses dissatisfaction with a past order or asks for a refund. The system determines this is a post-order/complaint matter, assesses the emotional tone of the request, and hands it off to the refund agent along with both the customer's full original message and the sentiment assessment.

**Why this priority**: Refund and complaint handling is the most sensitive interaction type — misrouting it, or routing it without the emotional context the refund agent needs to prioritize and respond appropriately, directly harms customer experience and is core to the feature's stated purpose.

**Independent Test**: Can be fully tested by submitting a variety of complaint/refund-style requests (spanning calm, frustrated, and angry tones) and confirming the router selects the refund destination, and that both the full request text and a sentiment assessment are forwarded.

**Acceptance Scenarios**:

1. **Given** a customer says "My order arrived cold and an hour late, I want my money back", **When** the request reaches the router, **Then** it is routed to the refund agent with the full message and a sentiment assessment reflecting the customer's frustration.
2. **Given** a customer calmly says "I was charged twice for my last order, can I get one charge refunded?", **When** the request reaches the router, **Then** it is routed to the refund agent with the full message and a sentiment assessment reflecting the customer's neutral tone.
3. **Given** a request is routed to the refund agent, **When** the handoff occurs, **Then** the sentiment assessment is included alongside the full original message.

---

### User Story 3 - Ambiguous or mixed-signal request resolved by asking the customer (Priority: P1)

A customer's message doesn't clearly indicate a single intent — either it's unclear altogether (e.g., "hello", "are you open today?"), or it mixes an ordering/question with a complaint/refund (e.g., "the food I ordered was cold, and also what's in the mapo tofu?"). Rather than guessing, the system asks the customer directly which of three things they mean — placing an order, asking a general question, or requesting a refund — and routes based on their answer.

**Why this priority**: Silently guessing on unclear or mixed-signal input risks misrouting exactly the requests where the customer's actual intent matters most (refund/complaint vs. general support). Asking directly is now a hard requirement, not a fallback — it applies to the same category of requests as the P1 stories above and must work before the feature can be considered correct.

**Independent Test**: Can be fully tested by submitting ambiguous requests and mixed-signal requests and confirming: (a) the system presents the three-way clarifying question rather than silently choosing a destination; (b) whichever of the three choices the customer selects, the request is routed to the matching destination (order/support for "placing an order" or "asking a general question", refund for "requesting a refund"); (c) if the resolved destination is refund, the sentiment assessment forwarded is the one already produced by the original analysis of the customer's message, not a separately elicited value.

**Acceptance Scenarios**:

1. **Given** a customer says "hello" or "are you open today?", **When** the request reaches the router, **Then** the system asks the customer directly whether they are placing an order, asking a general question, or requesting a refund, and does not route anywhere until it receives an answer.
2. **Given** a customer says "the food I ordered was cold, and also what's in the mapo tofu?", **When** the request reaches the router, **Then** the system asks the same three-way clarifying question rather than assuming refund or order/support.
3. **Given** the customer answers "requesting a refund" to the clarifying question, **When** the handoff occurs, **Then** it goes to the refund agent along with the full original message and the sentiment assessment produced by the original analysis of that message.
4. **Given** the customer answers "placing an order" or "asking a general question" to the clarifying question, **When** the handoff occurs, **Then** it goes to the order/support agent with the full original message and no sentiment assessment.
5. **Given** the customer's answer to the clarifying question doesn't match any of the three offered choices, **When** the system receives that answer, **Then** it asks the clarifying question again rather than guessing or failing.

---

### User Story 4 - Routing behavior is verifiable end-to-end (Priority: P2)

A developer or reviewer needs confidence that the router consistently sends each type of request down the correct path before any real order/support or refund logic is built behind it.

**Why this priority**: Because the order/support and refund agents are initially placeholders, the only way to validate this feature's value before those agents exist is to verify the router's decisions and handoff contents directly.

**Independent Test**: Can be fully tested by running a suite of representative requests through the router and confirming, for each one, which destination was chosen and what information (query text, and sentiment when applicable) was attached — independent of what the placeholder destinations do with it.

**Acceptance Scenarios**:

1. **Given** a labeled set of sample requests covering order/support, refund, and ambiguous/mixed-signal scenarios, **When** each sample is run through the router (answering the clarifying question where one is presented), **Then** the actual destination chosen matches the expected destination for at least the agreed accuracy threshold (see Success Criteria).
2. **Given** any sample request, **When** it is routed, **Then** the presence or absence of a sentiment assessment in the forwarded information matches the destination (present only for refund, absent for order/support).

---

### Edge Cases

- What happens when a request is ambiguous or does not clearly indicate either an order/support or a refund/complaint intent (e.g., "hello", "are you open today?")? The router does not default — it directly asks the customer to choose between placing an order, asking a general question, or requesting a refund, and routes based on their answer (see User Story 3).
- What happens when a single message mixes both an ordering question and a complaint/refund request (e.g., "the food I ordered was cold, and also what's in the mapo tofu?")? The router does not default to refund — it asks the same three-way clarifying question and routes based on the customer's answer (see User Story 3).
- What happens when the customer's answer to the clarifying question doesn't match any of the three offered choices? The system asks the clarifying question again rather than guessing or failing.
- What happens when the request text is empty, extremely short, or contains no discernible sentiment (e.g., a single emoji, or non-language input)? The router still produces a best-effort routing decision (asking the clarifying question if intent is unclear) and, if the request is ultimately routed to the refund agent, a best-effort neutral sentiment assessment rather than failing the handoff.
- What happens when the underlying request-analysis service is unavailable or errors out? The router must not silently drop the customer's request; it must surface a failure rather than forwarding an incomplete or corrupted handoff.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST accept a customer's full, unmodified request text as input to the routing decision. Requests are assumed to be in English; handling of other languages is out of scope for this feature.
- **FR-002**: The system MUST classify each incoming request into exactly one of two categories: order/support, or refund/complaint.
- **FR-003**: The system MUST produce a sentiment assessment of the customer's request whenever the request is classified as refund/complaint.
- **FR-004**: The system MUST NOT produce or forward a sentiment assessment for requests classified as order/support.
- **FR-005**: The system MUST forward the complete, original customer request text to whichever destination (order/support or refund) is chosen.
- **FR-006**: The system MUST forward the sentiment assessment alongside the full request text specifically to the refund destination, and only to that destination.
- **FR-007**: The system MUST route classified requests to one of two next-step destinations: an order/support handler or a refund handler, each of which may initially be a non-functional placeholder that simply receives the handoff.
- **FR-008**: The system MUST NOT silently default ambiguous or unclear requests to either destination. Instead, it MUST directly ask the customer to choose exactly one of three options — placing an order, asking a general question, or requesting a refund — and route based on the customer's answer.
- **FR-009**: The system MUST NOT silently default requests that contain both ordering and refund/complaint signals to refund/complaint. Instead, it MUST use the same direct three-way clarifying question described in FR-008 and route based on the customer's answer.
- **FR-010**: The system MUST be independently verifiable: for a given request, it must be possible to observe which destination was chosen and what information was forwarded, without depending on the internal behavior of the destination itself.
- **FR-011**: The system MUST surface an error rather than forwarding a partial or corrupted handoff if the routing or sentiment analysis step fails.
- **FR-012**: If the customer's answer to the clarifying question does not match any of the three offered choices, the system MUST ask the clarifying question again rather than guessing a destination or failing the handoff.
- **FR-013**: When a clarifying question resolves to the refund/complaint destination, the system MUST forward the Sentiment Assessment already produced by the original analysis of the customer's request; it MUST NOT ask the customer a separate question about their emotional state to obtain it.

### Key Entities

- **Customer Request**: The full, original text of what the customer asked or said; must be preserved without truncation or modification as it moves through the system.
- **Routing Decision**: The outcome of evaluating a Customer Request — which of the two destinations (order/support or refund) it is assigned to. May pass through an interim "unclear" state that is never itself a valid handoff destination — it is always resolved to order/support or refund, either directly or via the Clarifying Exchange, before a handoff occurs.
- **Sentiment Assessment**: A characterization of the emotional tone of a Customer Request, expressed as exactly one of three categories — positive, neutral, or negative; produced only when the Routing Decision is refund, and never produced or attached otherwise. Always comes from the original analysis of the Customer Request, even when the Routing Decision was reached via the Clarifying Exchange.
- **Clarifying Exchange**: A direct question presented to the customer — offering exactly three choices (placing an order, asking a general question, requesting a refund) — used only when the Customer Request does not clearly indicate a single intent, together with the customer's answer to it. Re-presented if the answer doesn't match one of the three choices. Determines the final Routing Decision when present; absent entirely for requests that are unambiguous.
- **Handoff Package**: The bundle of information forwarded to the chosen destination — always includes the full Customer Request, and includes the Sentiment Assessment only when the destination is refund.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: When evaluated against a representative labeled set of sample requests, the router selects the correct destination (order/support vs. refund) at least 90% of the time.
- **SC-002**: 100% of requests routed to the refund destination arrive with a sentiment assessment attached; 0% of requests routed to the order/support destination arrive with a sentiment assessment attached.
- **SC-003**: 100% of forwarded requests retain the customer's original wording exactly, with no loss or alteration of content.
- **SC-004**: A reviewer can determine, for any given test request, the chosen destination and the exact information forwarded, without needing to inspect or run the destination's own logic.
- **SC-005**: Routing a request adds no perceptible delay to the customer's experience (decision and handoff complete in under 3 seconds under normal conditions, excluding time spent waiting on a customer's answer to a clarifying question).
- **SC-006**: 100% of ambiguous or mixed-signal requests in the labeled sample set trigger the direct clarifying question rather than being routed without customer input.
- **SC-007**: For every sample request that reaches the refund destination via the clarifying question, the sentiment assessment forwarded is identical to the one produced by the original analysis of that request — never a separately elicited or default value.

## Assumptions

- Ambiguous or unclear requests (those without a clear order/support or refund signal), and requests containing signals for both categories, are resolved by directly asking the customer to choose one of three options — placing an order, asking a general question, or requesting a refund — rather than by an automatic default; the router does not guess the customer's intent in these cases.
- Sentiment is expressed as one of three fixed categories (positive, neutral, negative) sufficient for the refund agent to prioritize and tailor its response; a numeric or fine-grained emotional score is not required for this feature.
- The order/support agent and refund agent are out of scope for this feature beyond existing as placeholder destinations that receive a handoff; their internal behavior will be specified in future features.
- Verifying routing behavior (which destination is chosen, and what is forwarded) is sufficient to validate this feature; validating the quality of downstream agent responses is out of scope since those agents are placeholders.
- The system has access to whatever request-analysis capability is needed to classify intent and assess sentiment; the specific provider of that capability is an implementation detail outside this specification's scope.
