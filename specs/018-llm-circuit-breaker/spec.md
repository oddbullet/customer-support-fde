# Feature Specification: LLM Circuit Breaker with Fallback Model

**Feature Branch**: `circuit-breaker`

**Created**: 2026-09-28

**Status**: Draft

**Input**: User description: "Add a circuit breaker for the llm call. Once the max retry limit has been hit, the circuit breaker should fallback and use the fallback model that I will set in the .env call FALLBACK_MODEL"

## Clarifications

### Session 2026-09-28

- Q: How many requests in a row must use up all their retries on the primary model before the circuit opens? → A: One — the circuit opens as soon as a single request's primary-model call has used up all 3 of its built-in retries.
- Q: Once the circuit is open, how long should requests go straight to the fallback before the primary model is tried again? → A: 60 seconds, fixed (not configurable).
- Q: When the primary model and the fallback model both fail on the same request, what should the customer see? → A: The existing red "system is having some issues, please try again later" warning, with the conversation kept open so the customer can retry their last message.
- Q: How many retries should the fallback model get before the request is treated as failed? → A: 3 retries, same as the primary.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Conversation continues on the fallback model when the primary model fails (Priority: P1)

A customer is mid-conversation (asking about the menu, placing an order, or requesting a refund).
The primary language model becomes unavailable — it times out, is rate limited, or returns server
errors — and every retry attempt fails. Instead of the conversation crashing, the system answers
the same request using the fallback model named in `FALLBACK_MODEL`, and the customer receives a
normal reply without needing to repeat themselves.

**Why this priority**: This is the core value of the feature — a provider outage for one model no
longer ends the customer's conversation. Every agent (router, order/support, refund, ticket
generation, memory generation, history condensation) depends on the model, so a single failure
today stops the whole flow.

**Independent Test**: Configure a primary model that always fails with a retryable error and a
working fallback model; send a customer message and confirm a normal reply is produced and the
conversation continues to its usual next step.

**Acceptance Scenarios**:

1. **Given** `FALLBACK_MODEL` is set and the primary model fails every attempt up to the maximum
   retry limit, **When** any agent makes a model request, **Then** the same request is sent to the
   fallback model and its answer is used as if it came from the primary model.
2. **Given** `FALLBACK_MODEL` is set and the primary model succeeds (on the first attempt or on a
   retry within the limit), **When** an agent makes a model request, **Then** the fallback model
   is not used.
3. **Given** a request was answered by the fallback model, **When** the request involved tool
   calls or structured output (e.g., cart tools, refund tools, router classification), **Then**
   those behave identically to a primary-model answer — tools are run and the structured result
   is consumed by the same flow.
4. **Given** the primary and fallback models both fail on a request, **When** the customer is
   mid-conversation, **Then** the customer sees the red "please try again later" warning, the
   conversation stays open with its progress intact, and pressing Enter retries the message and
   continues the conversation normally once a model answers.

---

### User Story 2 - Circuit stays open so later requests skip the failing primary model (Priority: P2)

After the primary model has exhausted its retries, it is likely still unhealthy. Rather than
making every subsequent request wait through the full retry cycle again, the circuit "opens":
later model requests go straight to the fallback model for a cool-down period. After the
cool-down, the system tries the primary model again; if that succeeds, the circuit closes and
normal operation resumes.

**Why this priority**: Without it, every turn of a conversation during an outage pays the full
retry delay before falling back, making the assistant feel very slow. It improves responsiveness
but is not required for correctness (Story 1 alone keeps conversations working).

**Independent Test**: Trip the circuit with a failing primary model, then make another model
request within the cool-down and confirm the primary is not attempted; advance past the
cool-down with a healthy primary and confirm the primary is used again.

**Acceptance Scenarios**:

1. **Given** the circuit has opened, **When** another model request is made before the
   cool-down has elapsed, **Then** the request goes directly to the fallback model without
   attempting the primary model.
2. **Given** the circuit is open and the cool-down has elapsed, **When** the next model request
   is made, **Then** the primary model is tried once; on success the circuit closes, on failure
   the request is served by the fallback model and the circuit reopens for another cool-down.

---

### User Story 3 - Operators can see when the fallback was used (Priority: P3)

An operator reviewing traces needs to know that a conversation was served (fully or partly) by
the fallback model, and why — so outages can be diagnosed and fallback quality evaluated.

**Why this priority**: Required by the project's observability principle, but it does not change
the customer's experience.

**Independent Test**: Trigger a fallback and confirm the trace for that request records that the
circuit opened, which model actually answered, and the primary-model failure that caused it.

**Acceptance Scenarios**:

1. **Given** tracing is configured, **When** a request is served by the fallback model, **Then**
   the trace records the primary failure, the circuit state change, and the fallback model id.
2. **Given** tracing is configured, **When** the circuit closes after a successful primary retry,
   **Then** the trace records that the primary model has resumed.

---

### Edge Cases

- `FALLBACK_MODEL` is not set or is empty: behavior is unchanged from today — after the retry
  limit the failure propagates exactly as it does now (no circuit, no fallback).
- `FALLBACK_MODEL` is the same as the primary model: treated as a valid configuration; the
  fallback is attempted once, and if it fails the error propagates.
- The fallback model also fails: no further fallback chain and no switching back and forth. The
  customer sees the red "system is having some issues, please try again later" warning, and the
  conversation stays open with its progress (cart, account, refund details) intact. The customer
  presses Enter to retry their last message without retyping it.
- The customer retries after both models failed: the retry follows the current circuit state
  (straight to the fallback while the cool-down is running, a primary probe after it ends).
- Non-retryable failures (e.g., invalid API key, malformed request, or a model reply that does
  not match the expected structured shape) do not trip the circuit and do not trigger the
  fallback — these are handled exactly as today (e.g., the router still falls back to asking the
  customer to clarify on an unexpected classification shape).
- A primary failure occurs in the middle of a tool-calling loop: the fallback model continues
  from the same conversation state, and the per-turn tool-call limit still applies across both
  models.
- The primary model recovers during a conversation that was partly served by the fallback:
  later turns use the primary again once the circuit closes; the conversation is unaffected.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST read an optional `FALLBACK_MODEL` setting from the environment
  configuration, alongside the existing primary model setting, and document it in `.env.example`.
- **FR-002**: When `FALLBACK_MODEL` is set, every model request made by any agent (router,
  order/support, refund, ticket generation, memory generation, history condensation) MUST be protected by the circuit breaker.
- **FR-003**: The circuit MUST open as soon as a single request to the primary model has failed
  with retryable errors on its initial attempt and all 3 built-in retries (4 attempts in total).
  No count of failed requests is kept across requests.
- **FR-004**: When the circuit opens, the request that tripped it MUST be re-sent, unchanged, to
  the fallback model, and its result returned to the caller in the same form the primary would
  have produced (plain reply, tool calls, or structured output). The fallback model MUST get the
  same 3 built-in retries as the primary before the request is treated as failed.
- **FR-005**: While the circuit is open, model requests MUST go directly to the fallback model
  without attempting the primary model, until a fixed 60-second cool-down has elapsed since the
  circuit last opened.
- **FR-006**: After the cool-down, the next request MUST try the primary model once; success
  closes the circuit, failure reopens it for another cool-down and serves the request from the
  fallback model.
- **FR-007**: Non-retryable failures MUST NOT open the circuit or trigger the fallback.
- **FR-008**: If the fallback model also fails, the system MUST NOT loop between models. Agents
  that already absorb model errors (e.g., memory generation, ticket issue extraction) MUST keep
  doing so. Otherwise the customer MUST see the existing red "system is having some issues,
  please try again later" warning instead of raw error text, and the conversation MUST stay
  open with its progress intact. Pressing Enter MUST retry the customer's last message without
  retyping it or duplicating it in the conversation.
- **FR-009**: When `FALLBACK_MODEL` is unset or empty, model-call behavior MUST be identical to
  the current behavior.
- **FR-010**: Each fallback use and each circuit state change (opened, half-open retry, closed)
  MUST be recorded in the agent trace, including the model that actually answered.
- **FR-011**: Customer-facing replies MUST NOT mention the fallback or the model switch; the
  switch is invisible to the customer.

### Key Entities

- **Circuit state**: whether model requests currently go to the primary (closed), directly to the
  fallback (open), or are testing the primary again (half-open); includes when the circuit last
  opened, used to measure the cool-down.
- **Model configuration**: the primary model id, the optional fallback model id, the maximum
  retry limit, and the cool-down period.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With a working fallback configured, 100% of customer messages sent while the
  primary model is fully unavailable receive a normal reply instead of an error.
- **SC-002**: While the circuit is open, customer replies arrive without the extra retry delay —
  zero primary-model attempts are made for requests within the cool-down.
- **SC-003**: Within one request after the cool-down elapses and the primary is healthy again,
  requests are served by the primary model.
- **SC-004**: With no fallback configured, 100% of existing tests pass unchanged.
- **SC-005**: 100% of fallback uses are identifiable from traces, including which model answered.

## Assumptions

- "Max retry limit" means the existing per-request retry limit (currently 3 retries) already
  applied to every model request; this feature does not change that limit.
- Retryable failures are the same ones the existing retry mechanism already retries (timeouts,
  connection errors, rate limits, provider server errors).
- The fallback model is served through the same provider and API key as the primary model, so
  only the model id differs; it supports tool calls and structured output.
- Circuit state is kept in memory for the running process and shared by all agents; it resets
  when the application restarts. No persistence across restarts.
