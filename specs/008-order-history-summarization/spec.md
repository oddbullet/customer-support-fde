# Feature Specification: Order Support Agent Conversation Memory & Summarization

**Feature Branch**: `008-order-history-summarization`

**Created**: 2026-09-11

**Status**: Draft

**Input**: User description: "Context Management for the order_support agent. Do not wipe the message history every turn. Instead once the chat window reaches a certain token count. Summarize the chat history. Keep important information such as what the user has stated the like or dislike, etc. Then append that last 3 turn of conversion to the summary."

## Clarifications

### Session 2026-09-11

- Q: If the summarization step itself fails (e.g. the underlying model call to produce the condensed summary errors out), what should happen to the conversation? → A: Fail silently — the customer sees no error or indication anything went wrong; the agent still responds normally that turn using the existing uncondensed history, and condensation is retried on a later turn (updated 2026-09-11: supersedes the original answer, which had the failure surface to the customer)
- Q: Over a very long conversation, should the running summary be re-condensed/bounded so it doesn't just keep growing, or is unbounded growth acceptable? → A: Re-condense each pass — old summary + newly-aged exchanges are rewritten into one new concise summary, keeping it naturally bounded rather than appended to
- Q: What's a concrete latency budget for the condensation step, so "no noticeable delay" is measurable? → A: No latency requirement for now — condensation is allowed to add a noticeable delay; performance is deferred, not a success criterion for this feature

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Agent remembers earlier preferences in a long conversation (Priority: P1)

A customer chats with the order support agent through many back-and-forth
exchanges — asking about dishes, stating dislikes or allergies, changing their
mind, adding and removing items. Even after the conversation grows long enough
that older exchanges are condensed into a summary, the agent still honors
preferences and decisions the customer stated earlier, without asking the
customer to repeat themselves.

**Why this priority**: This is the core value of the feature — today the agent
forgets everything after each reply, which is confusing and repetitive for
customers with multi-step orders.

**Independent Test**: Have a long conversation where the customer states a
dislike/allergy early on, keep chatting past the point where summarization
would trigger, then order a dish that conflicts with the earlier statement —
the agent should still flag or avoid it.

**Acceptance Scenarios**:

1. **Given** a customer has told the agent they dislike an ingredient early in
   a long conversation, **When** the conversation later grows past the
   summarization threshold and the customer asks for a recommendation,
   **Then** the agent's recommendation still avoids that ingredient.
2. **Given** a customer confirmed adding an item to their cart many turns ago,
   **When** the conversation continues well beyond that point, **Then** the
   agent still has an accurate understanding of what is in the cart and does
   not ask the customer to re-confirm items already agreed on.

---

### User Story 2 - Conversation history is condensed instead of discarded (Priority: P1)

As the customer and agent exchange messages, the system keeps track of the
conversation. Once the accumulated conversation reaches a set size, everything
except the most recent exchanges is condensed into a running summary that
preserves the important facts (stated preferences, dislikes, decisions made),
so the conversation can continue indefinitely without growing without bound.

**Why this priority**: This is the mechanism that makes User Story 1 possible
while keeping the agent's working context bounded — without it, memory would
either be absent (today's behavior) or grow unbounded and eventually break the
underlying model.

**Independent Test**: Drive a conversation whose accumulated size crosses the
threshold and inspect that older exchanges have been replaced by a condensed
summary while the most recent exchanges remain intact.

**Acceptance Scenarios**:

1. **Given** the accumulated conversation has just crossed 20,000 tokens,
   **When** the customer sends their next message, **Then** all exchanges
   except the 3 most recent are condensed into a single running summary before
   the agent responds.
2. **Given** a running summary already exists from an earlier condensation,
   **When** the conversation crosses the threshold again, **Then** the prior
   summary and the aging exchanges are folded into an updated summary, and the
   3 most recent exchanges continue to be kept intact.
3. **Given** a conversation has 3 or fewer exchanges so far, **When** the
   accumulated size happens to cross the threshold (e.g. due to unusually long
   messages), **Then** no summarization occurs yet, since there is nothing
   older than the retained exchanges to condense.

---

### Edge Cases

- What happens if a single exchange (e.g. a very large tool result) by itself
  exceeds the token threshold? The system still condenses everything older
  than the 3 most recent exchanges; bringing the total strictly under the
  threshold is a best-effort outcome, not a hard guarantee, when the retained
  exchanges alone are already large.
- What happens to the running summary once the order is confirmed and the
  conversation ends? The summary is scoped to the life of that conversation
  and is not required to persist or feed into the order/refund tickets
  produced afterward.
- How does this interact with the customer changing their mind (e.g. stating a
  dislike, then later saying it's fine)? The summarization step must preserve
  the most recent/authoritative statement of a preference, not just the first
  one mentioned.
- What happens if the condensation step itself fails (e.g. the model call used
  to produce the summary errors out)? The failure is handled silently from the
  customer's perspective — the customer sees no error or indication that
  anything went wrong. The agent still responds normally that turn using the
  existing uncondensed history, and condensation is attempted again on a later
  turn once the threshold is next evaluated.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The order support agent MUST retain conversation history across
  customer turns within a session instead of discarding it after every reply.
- **FR-002**: The system MUST track the accumulated size (in tokens) of the
  active conversation for the order support agent.
- **FR-003**: When the accumulated conversation exceeds 20,000 tokens, the
  system MUST condense all exchanges except the 3 most recent into a single
  running summary before the agent's next response.
- **FR-004**: The running summary MUST preserve customer-stated preferences,
  dislikes, allergies, and decisions (e.g. items added or removed, confirmations
  made) so they remain available to the agent after condensation.
- **FR-005**: The 3 most recent exchanges — each defined as one customer
  message and the agent's resulting reply, together with anything the agent
  did to produce that reply — MUST be kept intact (not summarized) after each
  condensation.
- **FR-006**: Each time the threshold is crossed again later in the same
  conversation, the system MUST re-condense the running summary by rewriting
  the previous summary together with the exchanges that have since aged out
  of the retained 3 into one new, concise summary — not by appending to the
  existing summary text — so the summary stays naturally bounded rather than
  growing linearly with conversation length, while continuing to keep only
  the latest 3 exchanges intact.
- **FR-007**: The system MUST NOT perform condensation while the conversation
  has 3 or fewer exchanges, even if the token threshold is exceeded.
- **FR-008**: This conversation memory and summarization behavior applies only
  to the order support agent; it does not change how the refund agent or
  router agent manage their conversations.
- **FR-009**: When a customer restates a preference differently than before
  (e.g. changes their mind), the agent's understanding after condensation MUST
  reflect the most recent statement, not an outdated one.
- **FR-010**: If the condensation step itself fails, the system MUST NOT
  surface any error or indication of the failure to the customer; the agent
  MUST still respond normally that turn using the existing uncondensed
  history, and the system MUST retry condensation on a later turn rather than
  losing the history that still needs to be condensed.

### Key Entities *(include if feature involves data)*

- **Conversation Exchange (turn)**: One customer message paired with the
  agent's resulting reply, including any tool lookups or cart actions the
  agent performed to produce that reply. The unit that summarization retains
  or condenses.
- **Running Summary**: A condensed record of everything in the conversation
  older than the 3 most recently retained exchanges, capturing customer
  preferences, dislikes, and decisions made so far. Rewritten fresh (not
  appended to) on each condensation pass so it stays naturally bounded rather
  than growing linearly with conversation length.
- **Token Threshold**: The accumulated conversation size (20,000 tokens) that
  triggers condensation of older exchanges into the running summary.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In conversations that exceed the token threshold, customers do
  not need to repeat previously stated preferences (e.g. allergies, dislikes)
  for the agent to continue honoring them.
- **SC-002**: Order-support conversations of realistic length no longer fail
  or get cut off due to exceeding the underlying model's context limits.
- **SC-003**: After a condensation event, the agent's replies remain accurate
  and consistent with the 3 most recent real exchanges in 100% of tested
  conversations.

## Assumptions

- The token threshold for triggering condensation is 20,000 accumulated
  tokens, scoped to the order support agent's own conversation only.
- A "turn"/"exchange" is one customer message plus the agent's final reply to
  it, including any tool calls/results used along the way; tool activity does
  not create additional turn boundaries of its own.
- This feature supersedes the order support agent's previously documented
  behavior of discarding all conversation history after every customer reply
  (`specs/002-order-support-agent`); that existing contract and its associated
  tests are expected to be revisited when this feature is implemented.
- The running summary exists only for the lifetime of the active conversation;
  persisting it beyond the conversation (e.g. across separate customer visits)
  is out of scope for this feature.
- Summarization only needs to preserve information material to continuing the
  order (preferences, dislikes, decisions already made) — verbatim retention of
  every past detail is not required once it has been condensed.
- Condensation latency/performance is intentionally out of scope for this
  iteration: the condensation step is allowed to add a noticeable delay to the
  turn it runs on, and no latency budget is defined as a success criterion.
