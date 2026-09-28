# Feature Specification: Tool Call Limit

**Feature Branch**: `tool-limit`

**Created**: 2026-09-28

**Status**: Draft

**Input**: User description: "The system should limit the amount of time a tool can be called to prevent infinite tool calling loop caused by the agent. Should the limit be reach, we need to return a warning to the user informing them that the system is having issue and asking them to try later."

## Clarifications

### Session 2026-09-28

- Q: How is the limit counted? → A: Per tool, consecutively: the same tool may be called at most 3 times in a row; the 4th consecutive call of that tool trips the limit.
- Q: How is the warning shown to the customer? → A: Through one generic, reusable warning display that takes any message text and shows it in red, so it can be reused for future system-issue warnings.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Stop a runaway tool loop and warn the customer (Priority: P1)

A customer is talking to the assistant (placing an order or requesting a refund). Because of a model misbehavior, the assistant keeps calling the same tool over and over without replying to the customer. Instead of hanging, running up cost, or crashing, the system stops once that tool is about to be called a 4th time in a row. It then shows the customer a red warning saying the system is having trouble and they should try again later.

**Why this priority**: This is the core of the feature. An unbounded tool loop leaves the customer staring at a spinner indefinitely, keeps paying for model calls, and can eventually crash the session with an internal error.

**Independent Test**: Drive a conversation with a scripted model that requests the same tool on every step and never replies. Confirm that the tool runs exactly 3 times, the 4th request is not executed, the red warning is shown, and the session neither crashes nor hangs.

**Acceptance Scenarios**:

1. **Given** the order/support agent has called the same tool 3 times in a row, **When** it requests that tool a 4th consecutive time, **Then** the tool is not executed and the customer sees the "system is having issues, please try again later" warning in red.
2. **Given** the refund agent has called the same tool 3 times in a row, **When** it requests that tool a 4th consecutive time, **Then** the tool is not executed and the customer sees the same red warning.
3. **Given** the warning has been shown, **When** the conversation ends, **Then** no stack trace or raw error is shown. The warning stays readable until the customer takes their next action, and the customer is then returned to the prompt to start a new conversation.

---

### User Story 2 - Normal conversations are unaffected (Priority: P1)

A customer places a typical order (e.g., asks about several dishes, adds and removes items, checks the total) or goes through a typical refund conversation. Legitimate tool use never triggers the warning.

**Why this priority**: A limit that fires on real conversations would break the core product.

**Independent Test**: Run the existing order and refund conversation tests, including the long multi-turn ones. Confirm none of them trigger the limit and their outcomes are unchanged.

**Acceptance Scenarios**:

1. **Given** the agent calls tool A 3 times in a row, **When** it then calls a different tool B, **Then** the consecutive count for A is cleared, and later calls to A start counting again from 1.
2. **Given** the agent called a tool 3 times in a row before replying, **When** the customer replies and the agent calls that same tool again, **Then** counting starts again from 1 and no warning is shown.
3. **Given** the customer asks to add 4 or more dishes in one message, **When** the agent adds them to the cart in a single step, **Then** no warning is shown, because the calls in one step count as one.

---

### User Story 3 - Reusable red warning display (Priority: P2)

Developers have one generic way to show a system-issue warning to the customer. It takes any message text and shows it in red, clearly different from normal assistant replies. The tool-limit warning is its first use, and future system-level warnings can reuse it without new display code.

**Why this priority**: The tool-limit warning needs it, but its value as a shared building block matters more to future work than to this story alone.

**Independent Test**: Call the warning display with any message text and confirm the text appears in red and is visually distinct from assistant and customer messages.

**Acceptance Scenarios**:

1. **Given** any message text, **When** it is passed to the warning display, **Then** the exact text is shown to the customer in red.
2. **Given** a message that spans several lines, **When** it is shown, **Then** every line is red.
3. **Given** the output does not support color (e.g., redirected to a file), **When** a warning is shown, **Then** the message text still appears in full, with no raw color codes.

---

### User Story 4 - Limit breaches are observable to operators (Priority: P3)

When the limit is hit, an operator reviewing traces can see that the conversation was stopped by the tool-call limit, which agent and which tool triggered it, and the calls that led up to it.

**Why this priority**: Stopping the loop protects the customer, and recording it lets the team fix the root cause. The customer-facing protection works without it.

**Independent Test**: With tracing enabled, trigger the limit using a scripted looping model. Confirm the trace marks the conversation as ended by the tool-call limit.

**Acceptance Scenarios**:

1. **Given** tracing is configured, **When** the tool-call limit is reached, **Then** the trace records a limit-reached event that names the agent (order/support or refund) and the repeated tool.

---

### Edge Cases

- The agent requests the same tool several times in parallel in one step (e.g., adding several dishes at once). This counts as one call toward the in-a-row limit, so a single large request does not trip it.
- One step requests several different tools. Each of those tools counts as called once in that step. Any tool not requested in that step has its consecutive count cleared.
- The agent alternates two tools in a loop (A, B, A, B, …). Neither tool is called twice in a row, so this limit does not catch it, and the system's existing overall step safeguard remains the backstop.
- The limit is reached on a call that would have changed something (e.g., added to the cart or recorded a refund). That call does not run. Calls that already ran keep their effects.
- The limit is reached mid-order, before confirmation. The order is not confirmed or recorded, and no order ticket or preferences update is produced.
- The limit is reached mid-refund. The refund conversation is not marked resolved and no refund ticket is produced. Any refund request or complaint already recorded by earlier calls remains recorded.
- The warning display receives an empty message. Nothing meaningful can be shown, so it shows the empty text without failing.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST track, for both the order/support agent and the refund agent, how many times in a row each tool has been called within the current customer turn.
- **FR-002**: All calls to the same tool within a single agent step MUST count as one call toward that tool's consecutive count.
- **FR-003**: A tool's consecutive count MUST be cleared when an agent step does not call that tool, and all counts MUST be cleared whenever the customer provides a new reply.
- **FR-004**: A single tool MUST be allowed at most 3 consecutive calls. This limit MUST be defined in one place and apply to every tool.
- **FR-005**: When an agent requests a tool that has already been called 3 times in a row, the system MUST NOT execute any of the tools requested in that step. It MUST also stop the agent's loop for that conversation.
- **FR-006**: The system MUST provide a single generic warning display that accepts any message text and shows it to the customer in red, visually distinct from assistant and customer messages.
- **FR-007**: When color output is unavailable, the warning display MUST still show the full message text, with no raw color codes.
- **FR-008**: When the limit is reached, the system MUST show a warning through the generic warning display. The warning MUST say the system is experiencing issues and ask the customer to try again later. It MUST NOT expose internal details (tool names, error text, stack traces), and its text MUST be the same no matter which agent or tool triggered it.
- **FR-009**: After the warning is shown, the conversation MUST end cleanly. No order is confirmed or recorded, no ticket is generated, no preferences update is performed, and the refund conversation is not marked resolved.
- **FR-010**: Effects of tool calls that ran before the limit was reached (e.g., a refund request or complaint already recorded) MUST be kept, not rolled back.
- **FR-011**: The warning MUST stay visible until the customer takes their next action. The customer MUST then be returned to the prompt to start a new conversation, and this MUST NOT be reported as a crash.
- **FR-012**: When the limit is reached, the system MUST record the event in the conversation's trace. The record MUST name the agent that hit the limit and the repeated tool.
- **FR-013**: Conversations that never call the same tool more than 3 times in a row MUST behave exactly as they do today.

### Key Entities

- **Consecutive tool-call count**: For each tool, the number of agent steps in a row, within the current customer turn, in which that tool was called. It is cleared when a step skips the tool or when the customer replies.
- **Tool-limit warning**: The fixed message shown to the customer when the limit is reached.
- **Warning display**: A generic function that takes a message and shows it in red. It is used for the tool-limit warning and is available for future system-issue warnings.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In 100% of simulated same-tool loops (order/support and refund), the repeated tool runs no more than 3 times in a row, and the customer sees the red warning.
- **SC-002**: A looping conversation ends and shows the warning within 4 agent steps of the loop starting, instead of running indefinitely or ending in an unhandled error.
- **SC-003**: None of the existing order and refund conversation tests trigger the limit or change outcome after this feature is introduced.
- **SC-004**: Any message passed to the warning display is shown in full, in red when color is available, in 100% of tested cases.
- **SC-005**: When tracing is enabled, 100% of limit-reached events can be found in traces, with the agent and tool named.

## Assumptions

- "Limit the amount of time a tool can be called" means limiting the **number** of consecutive calls to the same tool (3 in a row), not wall-clock time.
- Calls to the same tool within one agent step count once. Otherwise a single legitimate request, such as adding 4 dishes at once, would trip the limit.
- "In a row" is measured within one customer turn. Calling the same lookup once per customer message over many messages is normal and must not trip the limit.
- The limit is a single fixed value that customers and operators cannot change, per the project's simplicity principle.
- The warning ends the conversation instead of letting the customer continue, since a model that looped once is likely to loop again in the same conversation.
- Loops that alternate between different tools are out of scope for this limit. The system's existing overall step safeguard remains the backstop for them.
- The generic warning display is limited to showing a message in red. It does not add severity levels, icons, or logging.
- Nodes outside the two agents' tool loops (router, clarification, account identification, summaries, tickets, memory) do not call tools in a loop and are out of scope.
