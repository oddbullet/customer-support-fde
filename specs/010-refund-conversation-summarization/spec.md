# Feature Specification: Refund Agent Conversation Memory & Summarization

**Feature Branch**: `010-refund-conversation-summarization`

**Created**: 2026-09-12

**Status**: Draft

**Input**: User description: "DO the same context management strategy for the refund agent. That was implemented for the order-support-agent"

## Clarifications

This feature intentionally reuses the decisions already made and validated
for `specs/008-order-history-summarization` (same token threshold, same
retained-exchange count, same re-condense-not-append policy, same silent
failure handling), applied to the refund agent's own conversation instead of
the order support agent's. See Assumptions for the carried-over defaults.

### Session 2026-09-12

- Q: When a single refund conversation touches more than one order, should
  the running summary keep facts and the outcome for each order separately,
  or is tracking only the most recently discussed order acceptable? → A:
  Preserve facts and the outcome separately per order mentioned so far in
  the conversation.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Agent stays consistent with earlier policy facts in a long refund conversation (Priority: P1)

A customer works through a refund or complaint with the agent across many
back-and-forth exchanges — providing an order number, describing what went
wrong, being asked follow-up questions, pushing back on a denial, or raising
more than one issue in the same conversation. Even after the conversation
grows long enough that older exchanges are condensed into a summary, the
agent still honors the order identified, the facts already gathered (what was
missing, whether a substitute arrived, whether the customer committed to
return it), and any policy decision already reached, without asking the
customer to repeat themselves or re-litigating a settled outcome.

**Why this priority**: This is the core value of the feature — a refund
conversation that loses track of the order number, the facts gathered, or a
decision already made partway through would force the customer to start
over, or worse, let the agent reach an inconsistent policy outcome.

**Independent Test**: Have a long refund conversation where the customer
identifies an order and states the key facts early on (e.g. a substitute
dish arrived and they agreed to return it), keep the conversation going past
the point where summarization would trigger (e.g. through repeated
pushback or an added complaint), then ask the agent to proceed — the agent
should still act on the order and facts established earlier without asking
the customer to repeat them.

**Acceptance Scenarios**:

1. **Given** a customer has identified their order and stated the facts
   needed for a policy decision early in a long conversation, **When** the
   conversation later grows past the summarization threshold, **Then** the
   agent's next action (looking up the order, applying policy, confirming an
   outcome) still uses those facts instead of asking the customer to restate
   them.
2. **Given** a policy decision (a submitted refund request, a denial, or a
   logged complaint) was already reached earlier in a long conversation,
   **When** the conversation continues well beyond that point (for example
   the customer keeps pushing back or raises an unrelated complaint),
   **Then** the agent still has an accurate understanding of what was already
   decided and does not reverse or duplicate that outcome without new facts.
3. **Given** a customer's first order was resolved (a refund submitted,
   denied, or a complaint logged) and they then bring up a problem with a
   different order later in the same long conversation, **When** the
   conversation crosses the summarization threshold again afterward, **Then**
   the agent still keeps the two orders' facts and outcomes distinct — it
   does not conflate the second order's facts with the first order's
   already-reached outcome, or vice versa.

---

### User Story 2 - Refund conversation history is condensed instead of growing without bound (Priority: P1)

As the customer and the refund agent exchange messages, the system keeps
track of the conversation. Once the accumulated conversation reaches a set
size, everything except the most recent exchanges is condensed into a
running summary that preserves the important facts (the order identified,
what the customer reported, facts gathered toward a policy decision, and any
outcome already reached), so the conversation can continue indefinitely
without growing without bound.

**Why this priority**: This is the mechanism that makes User Story 1
possible while keeping the agent's working context bounded. Most refund
conversations are short, but the ones that aren't — repeated pushback,
several issues raised in one conversation, a customer who is slow to supply
facts — are exactly the ones where losing context or hitting the underlying
model's limits would be most damaging.

**Independent Test**: Drive a refund conversation whose accumulated size
crosses the threshold and inspect that older exchanges have been replaced by
a condensed summary while the most recent exchanges remain intact.

**Acceptance Scenarios**:

1. **Given** the accumulated conversation has just crossed 20,000 tokens,
   **When** the customer sends their next message, **Then** all exchanges
   except the 3 most recent are condensed into a single running summary
   before the agent responds.
2. **Given** a running summary already exists from an earlier condensation,
   **When** the conversation crosses the threshold again, **Then** the prior
   summary and the aging exchanges are folded into an updated summary, and
   the 3 most recent exchanges continue to be kept intact.
3. **Given** a refund conversation has 3 or fewer exchanges so far, **When**
   the accumulated size happens to cross the threshold (e.g. due to an
   unusually long order lookup or policy explanation), **Then** no
   summarization occurs yet, since there is nothing older than the retained
   exchanges to condense.

---

### Edge Cases

- What happens if a single exchange (e.g. a large order lookup result) by
  itself exceeds the token threshold? The system still condenses everything
  older than the 3 most recent exchanges; bringing the total strictly under
  the threshold is a best-effort outcome, not a hard guarantee, when the
  retained exchanges alone are already large.
- What happens to the running summary once the refund conversation
  concludes (a refund is submitted, a request is denied, or a complaint is
  logged)? The summary is scoped to the life of that conversation and is not
  required to persist or feed into the refund support ticket produced
  afterward.
- How does this interact with a customer changing their answer (e.g. first
  declining to return a substitute dish, then agreeing later)? The
  summarization step must preserve the most recent/authoritative statement
  of a fact, not an earlier one that was since superseded.
- How does this interact with a policy decision already reached (a denial or
  a submitted refund request) becoming part of the condensed summary? The
  summary must preserve that an outcome was already reached and what it was,
  so the agent does not re-evaluate policy from scratch or reach a different
  outcome for the same facts after condensation.
- What happens when a condensation pass covers a conversation that discussed
  more than one order (e.g. the first order's issue was resolved before the
  customer raised a problem with a second order)? The running summary must
  keep each order's facts and reached outcome distinct rather than merging
  them, so a later reference to either order still resolves to the right
  facts and the right outcome.
- What happens if the condensation step itself fails (e.g. the model call
  used to produce the summary errors out)? The failure is handled silently
  from the customer's perspective — the customer sees no error or indication
  that anything went wrong. The agent still responds normally that turn
  using the existing uncondensed history, and condensation is attempted
  again on a later turn once the threshold is next evaluated.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The refund agent MUST retain conversation history across
  customer turns within a session instead of discarding it after every
  reply.
- **FR-002**: The system MUST track the accumulated size (in tokens) of the
  active conversation for the refund agent.
- **FR-003**: When the accumulated conversation exceeds 20,000 tokens, the
  system MUST condense all exchanges except the 3 most recent into a single
  running summary before the agent's next response.
- **FR-004**: The running summary MUST preserve the order identified, the
  facts the customer has reported (what was missing, any substitute
  received, any return commitment given or declined), the customer's stated
  complaint description, and any policy decision already reached (a
  submitted refund request, a denial and its reason, or a logged complaint),
  so they remain available to the agent after condensation. When the
  conversation has touched more than one order, the summary MUST keep each
  order's facts and reached outcome distinct rather than merging them
  together.
- **FR-005**: The 3 most recent exchanges — each defined as one customer
  message and the agent's resulting reply, together with anything the agent
  did to produce that reply — MUST be kept intact (not summarized) after
  each condensation.
- **FR-006**: Each time the threshold is crossed again later in the same
  conversation, the system MUST re-condense the running summary by rewriting
  the previous summary together with the exchanges that have since aged out
  of the retained 3 into one new, concise summary — not by appending to the
  existing summary text — so the summary stays naturally bounded rather than
  growing linearly with conversation length, while continuing to keep only
  the latest 3 exchanges intact.
- **FR-007**: The system MUST NOT perform condensation while the
  conversation has 3 or fewer exchanges, even if the token threshold is
  exceeded.
- **FR-008**: This conversation memory and summarization behavior applies
  only to the refund agent; it does not change how the order support agent
  or router agent manage their conversations.
- **FR-009**: When a customer restates a fact differently than before (e.g.
  changes their answer on returning a substitute dish), the agent's
  understanding after condensation MUST reflect the most recent statement,
  not an outdated one.
- **FR-010**: If the condensation step itself fails, the system MUST NOT
  surface any error or indication of the failure to the customer; the agent
  MUST still respond normally that turn using the existing uncondensed
  history, and the system MUST retry condensation on a later turn rather
  than losing the history that still needs to be condensed.
- **FR-011**: Condensation MUST NOT alter or override the refund policy
  outcome for facts already established (per `specs/007-refund-policy-agent`)
  — it only changes how the conversation's history is represented internally,
  never the eligibility decision itself.

### Key Entities *(include if feature involves data)*

- **Conversation Exchange (turn)**: One customer message paired with the
  refund agent's resulting reply, including any order lookups, policy
  evaluations, or complaint logging the agent performed to produce that
  reply. The unit that summarization retains or condenses.
- **Running Summary**: A condensed record of everything in the refund
  conversation older than the 3 most recently retained exchanges, capturing
  the order(s) identified, facts gathered toward a policy decision, and any
  outcome already reached. When more than one order has been discussed, the
  summary keeps each order's facts and outcome distinct rather than merging
  them. Rewritten fresh (not appended to) on each condensation pass so it
  stays naturally bounded rather than growing linearly with conversation
  length.
- **Token Threshold**: The accumulated conversation size (20,000 tokens)
  that triggers condensation of older exchanges into the running summary.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In refund conversations that exceed the token threshold,
  customers do not need to repeat previously stated facts (order number,
  what went wrong, return commitment) for the agent to continue acting on
  them correctly.
- **SC-002**: Refund conversations of realistic length, including ones with
  repeated pushback or multiple issues raised, no longer fail or get cut off
  due to exceeding the underlying model's context limits.
- **SC-003**: After a condensation event, the agent's replies remain
  accurate and consistent with the 3 most recent real exchanges, and with
  any policy decision already reached for each order discussed, in 100% of
  tested conversations.

## Assumptions

- This feature deliberately reuses, without re-deriving, the decisions
  already made and shipped for the order support agent's equivalent feature
  (`specs/008-order-history-summarization`):
  - The token threshold for triggering condensation is 20,000 accumulated
    tokens, scoped to the refund agent's own conversation only.
  - A "turn"/"exchange" is one customer message plus the agent's final
    reply to it, including any tool calls/results used along the way; tool
    activity does not create additional turn boundaries of its own.
  - The 3 most recent exchanges are always kept intact; condensation never
    runs while 3 or fewer exchanges exist.
  - The running summary is rewritten fresh on each condensation pass, never
    appended to.
  - A condensation failure is invisible to the customer and is retried on a
    later turn rather than surfaced as an error.
- The refund agent already retains conversation history across turns within
  a session (unlike the order support agent's pre-`008` behavior of
  resetting each turn); this feature adds the missing bound on that
  history's growth rather than introducing memory where none existed.
- The running summary exists only for the lifetime of the active
  conversation; persisting it beyond the conversation (e.g. across separate
  customer visits) is out of scope for this feature.
- Summarization only needs to preserve information material to reaching or
  honoring a policy decision (order identified, facts gathered, outcome
  reached) — verbatim retention of every past detail is not required once it
  has been condensed.
- This feature does not change the refund policy logic itself
  (`specs/007-refund-policy-agent`) — eligibility rules, ticket generation,
  and record persistence are unaffected; only how conversation history is
  retained and bounded changes.
- Condensation latency/performance is intentionally out of scope for this
  iteration, consistent with `specs/008-order-history-summarization`: the
  condensation step is allowed to add a noticeable delay to the turn it runs
  on, and no latency budget is defined as a success criterion.
