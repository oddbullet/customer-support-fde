# Feature Specification: Refund Policy Agent

**Feature Branch**: `007-refund-policy-agent`

**Created**: 2026-09-11

**Status**: Draft

**Input**: User description: "Support agent that can pull up old order and process user issues according to the company policy. If the customer meets company policy a refund request is generated (saved in the database). Once it is approved, the refund is considered complete. If a customer just has a complaint these issues will also be logged in the database. Policy: only orders within 48 hours would be considered for a refund; only if the customer got the wrong order can it be considered for a refund; customer must confirm that they will bring the wrong item back, if not no refund; all other cases do not get a refund."

## Clarifications

### Session 2026-09-11

- Q: When a customer receives the wrong dish, which order line does the refund cover - the item they paid for but never got, or the unexpected dish that showed up? → A: Refund the ordered line the customer paid for but did not receive; the incorrect dish that arrived is recorded by name only (no price) as the item being returned.
- Q: What should the refund agent do with the sentiment reading the router hands it? → A: Tone and ticket priority only — it adapts wording and is recorded on the support ticket for staff triage, with zero effect on the eligibility decision.
- Q: How should restaurant staff read the stored refund requests and complaints? → A: Retrieval functions only, no human-facing command this phase — records are queryable and test-covered, and a staff-facing view is deferred.
- Q: If an ordered dish simply never arrived and nothing came in its place, does that qualify as "got the wrong order"? → A: Yes — an undelivered item is refundable, and the return requirement is waived when there is no substitute dish to bring back.
- Q: If a customer is denied more than once in the same conversation, how many complaint records should be stored? → A: One per conversation — repeated denials extend the single record; a genuinely separate issue about a different order gets its own.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Customer gets a refund for a wrong item on a recent order (Priority: P1)

A customer contacts support saying they received the wrong dish. They give their order number. The agent pulls up that past order and shows what was ordered and when. The agent confirms the order was placed within the last 48 hours and that the customer did not receive something they ordered. If a substitute dish arrived, the agent asks the customer to confirm they will bring it back; if nothing arrived at all, there is nothing to return and the agent skips that step. Once the applicable conditions are met, the agent creates a refund request that is stored for the restaurant, and tells the customer their refund request has been submitted and what happens next.

**Why this priority**: This is the entire purpose of the feature — the only path that results in money being returned to a customer. Without it, nothing else in this feature has value.

**Independent Test**: Place (or seed) an order timestamped within the last 48 hours, start a support conversation reporting a wrong item, confirm the item will be returned, and verify a stored refund request exists that references that order.

**Acceptance Scenarios**:

1. **Given** an order placed 2 hours ago, **When** the customer reports receiving the wrong dish and confirms they will return it, **Then** a refund request is created and stored referencing that order, and the customer is told the request was submitted.
2. **Given** the customer has supplied a valid order number, **When** the agent pulls up the order, **Then** the customer is shown the items, quantities, prices, order total, and when the order was placed.
3. **Given** a refund request has been created for an order, **When** the stored records are retrieved for that order, **Then** the request comes back in a pending state with its order, the undelivered line(s), the dish(es) to be returned, and the refund amount.
4. **Given** the customer reports a substitute dish on an order placed within 48 hours, **When** the agent has not yet received an explicit return confirmation, **Then** no refund request is created.
5. **Given** an order placed 2 hours ago where one ordered dish never arrived and nothing came in its place, **When** the customer reports it, **Then** a refund request is created for that line without requiring any return commitment.

---

### User Story 2 - Customer is told why their refund is denied (Priority: P2)

A customer asks for a refund in a case the policy does not cover — the order is older than 48 hours, the problem is with an item that was correctly delivered (for example the food was cold, late, or they changed their mind), or they decline to bring back a substitute dish they received. The agent explains, in plain language, that the request does not qualify and which part of the policy applies. No refund request is created, and the customer's issue is still recorded as a complaint so the restaurant can see it.

**Why this priority**: Denials will be the most common outcome. Getting them right protects the restaurant from unwarranted refunds, and recording them means bad experiences are still visible to staff rather than silently dropped.

**Independent Test**: Report a refund-seeking issue that violates each policy condition in turn (order too old, wrong reason, return declined) and verify that in every case no refund request is stored, a complaint record is stored, and the customer is given the specific reason.

**Acceptance Scenarios**:

1. **Given** an order placed 3 days ago, **When** the customer requests a refund for a wrong item, **Then** no refund request is created, the customer is told the order is outside the 48-hour window, and a complaint is recorded.
2. **Given** an order placed 1 hour ago where every ordered dish was delivered, **When** the customer requests a refund because the food was cold, **Then** no refund request is created, the customer is told refunds only apply when an ordered item was not received, and a complaint is recorded.
3. **Given** an order placed 1 hour ago where a substitute dish arrived, **When** the customer declines to bring that dish back, **Then** no refund request is created, the customer is told the return is required, and a complaint is recorded.
4. **Given** any denial, **When** the agent explains the outcome, **Then** the explanation names the specific policy condition that was not met rather than a generic rejection.

---

### User Story 3 - Customer raises a complaint without asking for money back (Priority: P3)

A customer contacts support to report a bad experience — a rude interaction, a long wait, a dish they disliked — without requesting a refund. The agent acknowledges the complaint, records it against the customer's order when one is identified, and confirms it has been passed on to the restaurant.

**Why this priority**: Valuable for the restaurant's visibility into service quality, but it does not affect refund correctness, so it can ship after the refund paths are solid.

**Independent Test**: Start a support conversation that voices dissatisfaction but never asks for a refund, and verify a complaint record is stored and no refund request is created.

**Acceptance Scenarios**:

1. **Given** a customer describing a bad experience with no refund request, **When** the conversation concludes, **Then** a complaint record is stored containing the customer's description and no refund request is created.
2. **Given** a complaint where the customer supplies an order number, **When** the complaint is recorded, **Then** it is linked to that order.
3. **Given** a complaint where the customer supplies no order number, **When** the complaint is recorded, **Then** it is still stored, without an order link.

---

### Edge Cases

- **Order not found**: The customer gives an order number that does not exist. The agent says so and asks them to re-check the number instead of guessing or assuming an order.
- **No order number given**: The customer requests a refund without identifying an order. The agent asks for the order number and does not evaluate policy until one is supplied.
- **48-hour boundary**: An order placed exactly 48 hours ago. The window is inclusive — an order at exactly 48 hours old still qualifies; one older does not.
- **Nothing arrived in place of the missing item**: The customer ordered a dish that never came, and no substitute was delivered. The refund proceeds on that line and the return requirement is waived — the agent MUST NOT block on a return the customer cannot make.
- **Customer changes their mind about the return**: The customer first declines to return the item, then agrees later in the same conversation. The final, explicit answer governs, and a refund request is created if they ultimately confirm.
- **Duplicate request**: The customer asks for a refund on an order that already has an open or approved refund request. The agent reports the existing request's status rather than creating a second one.
- **Customer pushes back on a denial**: The customer re-argues the same denied request several times. The policy outcome does not change, and the existing complaint is extended rather than duplicated.
- **Customer names only the dish that arrived**: The dish the customer received is normally not on the order, so naming it alone does not identify a refundable line. The agent asks which of the order's own items never arrived, and does not fabricate a line or look up a menu price for the received dish.
- **Multiple undelivered items**: The customer reports that more than one ordered dish never arrived. All affected lines are captured in a single refund request, and the amount is the sum of those lines.
- **Partial quantity undelivered**: The customer ordered 3 of a dish and received only 2. The refund covers the 1 undelivered unit, not the full line.
- **Mixed intent**: The customer raises both a qualifying wrong-item refund and an unrelated complaint. Both are recorded — a refund request and a complaint.
- **Storage unavailable**: The underlying record store cannot be read or written. The agent tells the customer their request could not be recorded rather than falsely confirming a refund.

## Requirements *(mandatory)*

### Functional Requirements

#### Order retrieval

- **FR-001**: System MUST retrieve a previously placed order by its order number, returning the items ordered, quantities, unit prices, order total, and the time the order was placed.
- **FR-002**: System MUST return a clear, actionable message when the supplied order number does not match any stored order, and MUST NOT proceed to a refund decision for an unidentified order.
- **FR-003**: System MUST ask the customer for an order number when a refund is requested and none has been provided.

#### Policy evaluation

- **FR-004**: System MUST deny a refund when the order was placed more than 48 hours before the refund request. Orders placed 48 hours ago or more recently remain eligible.
- **FR-005**: System MUST deny a refund when the customer's stated problem is anything other than not receiving an item they ordered. Both cases qualify: a substitute dish arrived instead of the ordered one, and the ordered dish never arrived at all. Problems with a correctly delivered item — quality, temperature, timeliness, or a change of mind — MUST be denied.
- **FR-006**: When a substitute dish was received, System MUST obtain the customer's explicit confirmation that they will return it before a refund request is created, and MUST deny the refund if that confirmation is declined or absent. When nothing arrived in place of the missing item there is nothing to return, and the return requirement MUST be waived rather than blocking the refund.
- **FR-007**: System MUST establish whether a substitute dish was received in place of the missing item, because that determines whether a return commitment is required.
- **FR-008**: System MUST deny a refund in all cases not satisfying every one of FR-004, FR-005, FR-006, and FR-007 together.
- **FR-009**: System MUST state, in the customer-facing response, the specific policy condition that caused a denial.
- **FR-010**: System MUST NOT create a refund request record when any policy condition is unmet.
- **FR-011**: System MUST NOT create a second refund request for an order that already has an open or approved request; it MUST report the existing request's status instead.

#### Refund requests

- **FR-012**: System MUST create and persist a refund request when, and only when, all policy conditions are met, recording at minimum the order reference, the undelivered order line(s) and quantities, any substitute dish(es) the customer received, the refund amount, the customer's return commitment, the request status, and the time the request was created.
- **FR-013**: A refund request MUST be created in a pending state. An approved request is considered a completed refund, but no approval action is provided in this phase — the agent MUST NOT create a request in any state other than pending.
- **FR-014**: The refund amount MUST cover only the ordered line(s) the customer paid for but did not receive, at the quantities not received and the unit prices recorded on the order — not the full order total.
- **FR-015**: System MUST identify which of the order's lines went undelivered and MUST record those lines on the refund request so the amount is traceable to them. The dish the customer actually received MUST be recorded by name only, as the item they are committing to return, and MUST NOT be priced or looked up on the menu.
- **FR-016**: System MUST tell the customer their refund request is submitted and awaiting review, and MUST NOT tell them the refund is complete.

#### Complaints

- **FR-017**: System MUST persist a complaint record whenever a customer reports dissatisfaction without requesting a refund, capturing the customer's description and the time it was recorded.
- **FR-018**: System MUST persist a complaint record whenever a refund request is denied, capturing the customer's description and the policy reason for the denial.
- **FR-019**: System MUST link a complaint to an order when the customer has identified one, and MUST still record the complaint when no order is identified.
- **FR-020**: System MUST record at most one complaint per conversation per order. A repeated or rephrased denial MUST extend the existing complaint rather than create a second record; a distinct issue about a different order MUST get its own record.
- **FR-021**: A complaint that is extended MUST retain its original creation time and reflect the latest description and denial reason.

#### Outcome and handoff

- **FR-022**: System MUST confirm to the customer what was recorded — a submitted refund request, a denial with reason, or a logged complaint — so the customer is never left without an outcome.
- **FR-023**: System MUST produce a refund support ticket summarizing the order, the customer's issue, the policy decision and its reason, the sentiment reading for the conversation, and the resulting refund request or complaint.
- **FR-024**: Every stored refund request and complaint MUST be retrievable by order reference and as a complete listing, exposing status, amount, and recorded reason. No staff-facing command or view is provided in this phase — retrieval is a data guarantee the records must satisfy.
- **FR-025**: System MUST inform the customer when a refund request or complaint could not be recorded, rather than confirming an action that did not occur.
- **FR-026**: System MUST use the sentiment reading supplied for the conversation to adjust the tone of its customer-facing wording, responding more carefully when sentiment is negative.
- **FR-027**: Sentiment MUST NOT influence the eligibility decision in any way — the same order, problem, and return commitment MUST produce the same policy outcome regardless of sentiment.

### Key Entities

- **Order**: A previously placed and confirmed order. Key attributes: order number, items with quantities and unit prices, order total, time placed. Already exists in the system; this feature reads it and never modifies it.
- **Refund Request**: A record that a customer qualified for a refund under policy. Key attributes: reference to the order, the undelivered order lines and quantities, the refund amount derived from those lines, the name(s) of any substitute dish(es) received and to be returned (name only, unpriced, absent when nothing arrived), the return commitment where one was required, status (pending in this phase; approved reserved for later), and the time created. One order has at most one open or approved refund request.
- **Complaint**: A record of customer dissatisfaction, whether standalone or the result of a denied refund. Key attributes: optional reference to an order, the customer's description of the issue, the policy reason when it stems from a denial, time first recorded. Scoped to one conversation and one order — at most one complaint exists per that pairing.
- **Policy Decision**: The reasoned outcome of evaluating a customer's issue against the refund policy. Key attributes: eligible or not, the specific condition that failed when not eligible, and the resulting record (refund request or complaint). Surfaced to the customer and carried into the support ticket.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of refund requests that fail any policy condition result in no stored refund request — zero refunds are issued outside policy.
- **SC-002**: 100% of stored refund requests trace back to an order placed within the 48-hour window and an item the customer ordered but did not receive; every request where a substitute dish was received also carries a recorded return commitment.
- **SC-003**: 100% of customer issues that do not produce a refund request are still recorded as complaints, so no reported problem is lost.
- **SC-004**: A customer who supplies a valid order number receives their eligibility decision within 3 conversational turns.
- **SC-005**: 100% of refund denials name the specific policy condition that was not met, so customers are never given an unexplained rejection.
- **SC-006**: 100% of created refund requests and complaints are retrievable afterwards with their status and reason intact, with no records missing from the record store.
- **SC-007**: Repeat refund attempts on the same order produce at most one refund request, in 100% of cases.
- **SC-008**: Every stored refund amount equals the sum of the undelivered quantities at their order-recorded unit prices, and never exceeds the order total.
- **SC-009**: Identical refund scenarios evaluated under positive, neutral, and negative sentiment produce identical eligibility outcomes, in 100% of cases.
- **SC-010**: A conversation containing repeated denials for the same order produces exactly one complaint record, in 100% of cases.

## Assumptions

- The customer identifies their past order by supplying the order number they were given at order time; no additional identity verification is performed in this phase, consistent with the project's current scope.
- The 48-hour window is measured from the time the order was placed to the time the customer's refund request is evaluated, using a single consistent time reference.
- Orders are read from the existing confirmed-order store; refund requests and complaints are persisted alongside them in the same store.
- A refund is recorded as a decision, not a money movement — no payment provider or card network integration is in scope. "Approved" means the restaurant has accepted the refund; settling the money happens outside this system.
- Approving a pending refund request is out of scope for this phase. The agent creates pending requests and staff can read them, but no approval action (agent-driven or staff-facing) is built here. The approved state is reserved in the record so a later phase can add it without reshaping the data.
- Refund amounts use the prices already recorded on the order; no separate pricing lookup and no tax, tip, or delivery-fee apportionment.
- The refund agent is reached through the existing router agent, which also supplies a sentiment reading for the conversation; the resulting ticket is produced by the existing ticket summary agent. Sentiment is a presentation and triage signal only, never a policy input (FR-026, FR-027).
- The customer's return of the wrong item is a commitment captured in the record, not a step this system tracks to completion — the system does not verify that the item was actually returned.
- Editing, cancelling, or negotiating a refund request after creation is out of scope for this phase.
- A staff-facing way to browse refund requests and complaints is out of scope for this phase. Retrieval exists as callable behavior and is covered by tests; surfacing it to a human — alongside the deferred approval action — is left to a later phase.
