# Feature Specification: Customer Memory Generation Agent

**Feature Branch**: `013-memory-gen-agent`

**Created**: 2026-09-14

**Status**: Draft

**Input**: User description: "Create a memory_gen_agent that is call after the order_support_agent is done. Send the message history to the agent and pull out information about what the user likes / dislike and allergy. Save the information to the SQLite. This node should only run if the user has an account number. Ideally, this agent can run at the same time as ticket-gen agent."

## Clarifications

### Session 2026-09-14

- Q: Should a one-off, per-order request (like "no onions on this dish") be treated the same as a general standing statement (like "I love spicy food"), or should only general standing statements be saved? → A: Capture both, but the two carry different weight downstream. Per-order customizations and general statements are both recorded (e.g. a customer asking for no onions on one order gets "dislikes onions" noted), but whenever a future feature reads this information back into a conversation, it MUST treat it as a guideline, not an absolute rule — e.g. if the customer later orders a dish with onions, the agent should ask whether they want onions on it (not silently omit them), and if the customer asks for a recommendation, the agent should avoid suggesting dishes with onions rather than refusing to mention them. (This consumption behavior itself remains out of scope for this feature per the Assumptions below, but the recorded data must be shaped so that behavior is possible later.)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Stated preferences and allergies are remembered on the customer's account (Priority: P1)

A customer with an account chats with the order support agent and, along the
way, mentions things like "I don't eat shellfish," "I love spicy food," or
"I'm allergic to peanuts." Once the customer finishes ordering, that
information is automatically pulled out of the conversation and saved to
their account, without the customer having to fill out any kind of profile or
preferences form.

**Why this priority**: This is the entire value of the feature — turning
conversational asides into durable account knowledge that future visits can
draw on, instead of the customer having to repeat themselves every time they
order.

**Independent Test**: Have an account-holding customer state a clear like,
dislike, and allergy during an order conversation, confirm the order, then
check that customer's account record — the stated information should now be
present.

**Acceptance Scenarios**:

1. **Given** an account-holding customer mentions an allergy during their
   order conversation, **When** they confirm their order and the order
   support agent finishes, **Then** that allergy is saved to their account
   record.
2. **Given** an account-holding customer mentions a food they like and a food
   they dislike in the same conversation, **When** the order is confirmed,
   **Then** both pieces of information are saved to their account record.
3. **Given** an account-holding customer asks for a one-off change on a
   specific dish (e.g. "no onions on this one"), **When** the order is
   confirmed, **Then** that request is saved to their account record as a
   dislike, distinct from a hard allergy, so a future feature can treat it as
   a guideline rather than an absolute rule.
4. **Given** an account already has stored preferences from an earlier visit,
   **When** the customer has a new order conversation that mentions an
   additional preference, **Then** the account's stored record ends up
   reflecting both the previously known information and the newly stated
   information — nothing previously known (especially an allergy) is lost.

---

### User Story 2 - Guest customers are never profiled (Priority: P1)

A customer who chooses to order without using or creating an account should
never have any personal information extracted or stored, since there is no
account to attach it to and no consent implied by ordering as a guest.

**Why this priority**: This is a hard boundary, not a nice-to-have — writing
preference data anywhere for a customer who explicitly declined an account
would be a privacy violation of the feature's own premise.

**Independent Test**: Have a customer decline an account, state a clear
allergy during ordering, confirm the order, and verify no new account record
is created and no preference data is stored anywhere.

**Acceptance Scenarios**:

1. **Given** a customer is ordering without an account, **When** they state a
   preference or allergy and confirm their order, **Then** no preference
   extraction or storage occurs.

---

### User Story 3 - Memory capture never slows down the customer (Priority: P2)

While the account's stored preferences are being updated in the background,
the customer should still receive their order ticket/confirmation without
any added delay, since the memory update is a behind-the-scenes improvement
for future visits, not something the customer is waiting on.

**Why this priority**: Protects the existing, already-working order
confirmation experience from regressing because of a feature the customer
isn't even aware of.

**Independent Test**: Time order ticket delivery for an account-holding
customer before and after this feature ships and confirm there is no
noticeable added wait.

**Acceptance Scenarios**:

1. **Given** an account-holding customer confirms an order, **When** the
   order ticket is produced, **Then** it is delivered without waiting on the
   preference-extraction step to finish.

---

### Edge Cases

- Conversation contains no mention of any like, dislike, or allergy: the
  account's existing stored preferences (if any) are left exactly as they
  were — nothing is erased.
- Customer contradicts themselves within the same conversation (e.g. says
  they dislike shrimp, then later says they love it): the saved record
  reflects their final, most recent statement.
- Customer signed up for a brand-new account during this same conversation
  (no prior stored preferences to merge with).
- The extraction step itself fails (e.g. an underlying error from the
  summarization step): the customer sees no error, their order is unaffected,
  and the account's existing stored preferences are left untouched.
- Customer abandons the conversation before ever confirming an order: no
  extraction or storage happens, since the order support agent never reaches
  its finished state.
- Customer's stated preference conflicts with something already stored from a
  previous visit (e.g. previously said they liked shellfish, now say they're
  allergic to it): the newer, more specific/safety-relevant statement
  (the allergy) is reflected in the saved record.
- Customer makes a one-off, per-order customization request (e.g. "no onions
  on this one") rather than a general self-statement: it is still recorded,
  but as a dislike/preference rather than an allergy, so it is distinguishable
  from a safety-critical statement when the record is read back later.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST review the order support conversation's full
  message history once the order support agent has finished (the customer
  has confirmed their order) to identify any statements indicating food
  likes, dislikes, or allergies — including one-off, per-order customization
  requests (e.g. "no onions on this one"), not only general self-statements
  (e.g. "I love spicy food").
- **FR-002**: System MUST perform this review and any resulting storage only
  when the conversation has an account number attached (the customer used an
  existing account or signed up for one); it MUST NOT run for guest customers.
- **FR-003**: System MUST save identified likes, dislikes, and allergies to
  the corresponding customer account record, keyed by that account's number.
- **FR-004**: System MUST never write extracted information to any account
  other than the one identified for the current conversation.
- **FR-005**: When a customer already has previously stored preference
  information on their account, System MUST combine the newly extracted
  information with what was already stored, rather than discarding the
  previously known information.
- **FR-006**: When no like, dislike, or allergy information is found in the
  conversation, System MUST leave the account's existing stored preferences
  unchanged.
- **FR-007**: System MUST NOT delay delivery of the customer's order ticket
  or order confirmation while performing this extraction and storage.
- **FR-008**: If the extraction step fails for any reason, System MUST leave
  the account's existing stored preferences unchanged and MUST NOT surface
  any error or delay to the customer.
- **FR-009**: Saved preference information MUST remain a single free-text
  record per account (consistent with how account preferences are already
  stored), rather than being split into separate structured fields per
  category.
- **FR-010**: Within that single free-text record, System MUST distinguish
  safety-critical statements (allergies) from softer taste signals (likes,
  dislikes, and per-order customizations), so that a future feature reading
  this record back can treat allergies as hard constraints and everything
  else as a guideline (e.g. confirm with the customer or steer recommendations
  away from a disliked ingredient, rather than silently enforcing or ignoring
  it) — see Clarifications.

### Key Entities

- **Account**: A customer's existing account record, identified by account
  number, that already has a place to hold free-text preference information.
  This feature is what populates and keeps that information up to date.
- **Order Conversation**: The in-progress exchange of messages between a
  customer and the order support agent for a single visit; this feature reads
  it but does not alter or store the conversation itself.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: When an account-holding customer clearly states a like,
  dislike, or allergy during ordering, that information is reflected on their
  account record immediately after the order is confirmed, with no manual
  step required by staff or customer.
- **SC-002**: 100% of guest (no-account) order conversations result in zero
  preference data being written anywhere.
- **SC-003**: Order ticket delivery time for account-holding customers shows
  no noticeable increase after this feature ships.
- **SC-004**: A customer who stated an allergy on one visit still has that
  allergy on record on a later visit, even if the later visit's conversation
  never mentions it again.

## Assumptions

- This feature covers the order support conversation flow only, per the
  feature request ("called after the order_support_agent is done"). The
  refund conversation flow is out of scope and is not analyzed for
  preferences by this feature.
- "The order support agent is done" means the point where the customer has
  confirmed their order — the same point that already triggers order ticket
  generation today. There is currently no other way for the order support
  flow to end.
- Extraction covers the same three categories the account record's
  preferences field already anticipates — likes, dislikes, and allergies —
  captured together as one free-text passage rather than separate structured
  fields, matching how that field is already documented and stored.
- Combining newly extracted information with previously stored information
  (FR-005) is a rewrite of the stored text into one updated, coherent
  passage, not a raw append of separate notes — this avoids the record
  growing without bound over many visits while still preserving prior
  allergy/preference facts.
- If the extraction step fails, the feature fails silently — no customer
  facing error and no partial/corrupted write — consistent with the
  fail-silent convention already used for order conversation summarization
  elsewhere in this project.
- "Running at the same time as" ticket generation, as mentioned in the
  feature request, is a preference about not adding customer-facing delay
  (see FR-007 / SC-003), not a strict requirement on how the two steps are
  wired together internally.
- No user-facing surface is introduced by this feature to display stored
  preferences back to staff or customers; actually reading this stored
  information back into a future conversation (and applying the
  guideline-not-gospel behavior described in Clarifications) is explicitly
  out of scope for this feature's implementation, left to a later feature —
  this feature's responsibility is limited to capturing and storing the
  information in a shape (per FR-010) that later feature can use correctly.
