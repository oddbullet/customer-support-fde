# Feature Specification: Interactive CLI Mode

**Feature Branch**: `016-interactive-cli-mode`

**Created**: 2026-09-15

**Status**: Draft

**Input**: User description: "Polish the CLI. I should not need to start with a uv run customer-support-fde "question". I can say uv run customer-support-fde to start the application and then I get a nice UX of input your question. Nice section of seeing what text is AI and what text is human. essentially preparing it for demo. Should I use rich?"

## Clarifications

### Session 2026-09-15

- Q: Should the human-vs-AI distinction in the transcript rely on color alone, or also use text labels (like "You:" / "Assistant:") so it still works when color isn't available? → A: Color + text labels — both together, so the distinction survives in degraded/non-tty output and is readable for colorblind viewers.
- Q: While the assistant is generating a response, should the CLI show a "thinking"/loading indicator, or just block silently until the reply prints? → A: Show a thinking/status indicator while waiting.
- Q: When one conversation resolves and the prompt returns for a new one, should prior conversations stay visible in the scrolling transcript, or should the screen clear so only the current conversation shows? → A: Clear the screen between conversations — only the current conversation is visible at a time.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Start a conversation without a CLI argument (Priority: P1)

A presenter launches the application with no arguments and is greeted with a welcome message and a prompt inviting them to type their first question, instead of having to pass the question as a command-line string.

**Why this priority**: This is the core friction the request calls out — today the tool cannot be demoed without pre-scripting the exact question as a shell argument. Removing that requirement is the minimum needed to make the tool feel like a real assistant during a live demo.

**Independent Test**: Run `uv run customer-support-fde` with no arguments and confirm the program starts, displays a prompt, and accepts typed input instead of exiting or erroring for lack of a query.

**Acceptance Scenarios**:

1. **Given** the application is launched with no arguments, **When** it starts, **Then** the user sees a welcome/intro message and a clearly marked input prompt.
2. **Given** the input prompt is showing, **When** the user types a question and presses enter, **Then** the application processes it exactly as it does today when a query is passed as a CLI argument.
3. **Given** the user has submitted a question, **When** the assistant is generating its response, **Then** a visible status/thinking indicator is shown until the response is ready.

---

### User Story 2 - Visually distinguish AI responses from human input (Priority: P1)

During the conversation, everything the customer (human) typed and everything the assistant (AI) said is shown in the terminal in a way that makes it immediately obvious, at a glance, which side said what — important for an audience watching a live demo who did not type the input themselves.

**Why this priority**: This is the other half of the explicit ask ("nice section of seeing what text is AI and what text is human") and is what makes the transcript legible to a demo audience rather than a wall of undifferentiated text.

**Independent Test**: Run an interactive session, have at least two back-and-forth exchanges, and confirm a viewer who did not participate can correctly identify, for every line of output, whether it came from the human or the AI, without reading the content itself.

**Acceptance Scenarios**:

1. **Given** the user has typed a question, **When** it is echoed back into the transcript, **Then** it is visually marked as human input (e.g., distinct label/styling) distinct from assistant output.
2. **Given** the assistant produces a response, **When** it is printed, **Then** it is visually marked as AI output distinct from human input, including for multi-line responses.
3. **Given** the assistant asks a follow-up/confirmation question mid-conversation (e.g., to confirm an order), **When** it is displayed, **Then** it uses the same AI styling as any other assistant message, and the user's reply uses the same human styling.

---

### User Story 3 - Continue or end the session across multiple tickets (Priority: P2)

After a conversation reaches a natural conclusion (an order is confirmed, a refund is resolved, or a question is answered), the user is returned to the prompt to start a new conversation if they want to demo another scenario, or can cleanly end the program when they're done.

**Why this priority**: A demo typically walks through several scenarios (an order, then a refund, then a menu question) in one sitting; requiring a restart of the whole program between each undermines the "nice UX" goal, but this depends on Story 1 and 2 already working.

**Independent Test**: Complete one full conversation (e.g., confirm an order) in an interactive session, confirm the prompt reappears for a new conversation, start a second unrelated conversation (e.g., a refund), complete or cancel it, then issue the exit action and confirm the program terminates cleanly.

**Acceptance Scenarios**:

1. **Given** a conversation has just resolved (order confirmed, refund resolved, or question answered), **When** control returns to the user, **Then** the screen is cleared and a new prompt is shown allowing a new, unrelated conversation to begin, with the just-finished conversation's transcript no longer visible.
2. **Given** the user is at the prompt for a new conversation, **When** they type `/exit` or press Ctrl+C, **Then** the program prints a clean closing message and terminates with a success exit code.
3. **Given** the user is mid-conversation, **When** they issue an exit/cancel action, **Then** the current conversation ends without crashing and the user is returned to the prompt for a new conversation (or the program exits, per the same exit action as above).

---

### Edge Cases

- What happens when the user presses enter without typing anything at the initial prompt (no question yet asked)?
- What happens when the assistant response contains multi-line or very long text that wraps in a narrow terminal — is the AI/human distinction still visually clear on every wrapped line?
- What happens when output is redirected to a file or piped to another program (not an interactive terminal) — does styling degrade gracefully instead of printing raw escape codes?
- What happens when an error occurs mid-conversation (e.g., an upstream API failure) — does the session recover to the prompt for a new conversation, or does the whole program exit?
- How does the existing single-shot invocation (`customer-support-fde "question"`) and the `--json` machine-readable flag behave now that interactive mode exists — do they remain available and unchanged for scripting/tests?
- What happens if the user tries to exit while a mid-conversation confirmation prompt (e.g., order confirmation) is awaiting their answer?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST allow launching the application with no query argument and, in that case, start an interactive session rather than erroring or blocking silently on unlabeled stdin input.
- **FR-002**: System MUST display a welcome/intro message when interactive mode starts, so a first-time viewer understands they are expected to type a question.
- **FR-003**: System MUST visually distinguish, for every line printed during a conversation, whether it represents human (user-typed) content or AI (assistant-generated) content, using both color and a textual label (e.g., "You:" / "Assistant:") so the distinction does not depend on color alone.
- **FR-004**: System MUST apply the human/AI visual distinction consistently across the entire conversation transcript, including initial questions, mid-conversation confirmation exchanges (e.g., order confirmation), and final results — not just the last message.
- **FR-005**: System MUST, after a conversation reaches a resolved end state (order confirmed, refund resolved, or question answered) or is cancelled, clear the screen and return the user to a prompt where a new, independent conversation can be started, with no prior conversation's transcript remaining visible.
- **FR-006**: Users MUST be able to cleanly end the interactive session by typing `/exit` at a new-conversation prompt or pressing Ctrl+C, and MUST see a closing acknowledgment before the program exits.
- **FR-007**: System MUST preserve the existing single-shot invocation (a query supplied as a CLI argument) and the existing `--json` output flag, unchanged in behavior and output format, for scripted/automated use.
- **FR-008**: System MUST continue to support the existing mid-conversation interrupt/resume behavior (e.g., order confirmation prompts) within the interactive loop, with the same human/AI visual distinction applied.
- **FR-009**: System MUST degrade to plain, unstyled text output when the terminal does not support styled/color output (e.g., output is piped or redirected), without printing raw formatting codes; the textual human/AI labels from FR-003 MUST still be present in this degraded mode so the distinction is never lost.
- **FR-010**: System MUST NOT crash the whole program on a mid-conversation error; it MUST report the error clearly, marked distinctly from normal AI/human content, and return the user to the prompt for a new conversation.
- **FR-011**: System MUST show a visible "thinking"/status indicator while waiting on the assistant's response, so the user has feedback that the system is processing rather than appearing frozen.

### Key Entities

- **CLI Session**: The lifetime of one interactive program run, from launch to exit; contains zero or more Conversations and ends when the user issues an exit action.
- **Conversation**: One question-to-resolution exchange within a session (e.g., one order, one refund, one menu question), composed of an ordered sequence of Turns and ending in a resolved, cancelled, or errored state.
- **Turn**: A single labeled unit of transcript output — either human input or an AI response — displayed with a visual marker identifying which side produced it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A presenter can go from launching the program to having the assistant respond to a first question using zero command-line flags or arguments.
- **SC-002**: In a recorded or live demo, an audience member who did not type the input can correctly attribute every line of transcript output to "human" or "AI" without being told which is which.
- **SC-003**: A presenter can complete three distinct conversations (e.g., a menu question, an order, and a refund) in a single program run without restarting the application.
- **SC-004**: Existing scripted/automated invocations (direct query argument, `--json` flag) produce output identical in structure to before this feature, with zero regressions in existing automated tests.
- **SC-005**: A user can end the session at any prompt without consulting documentation, using an exit method discoverable from on-screen text alone.

## Assumptions

- The terminal used for demos supports ANSI escape codes / styled text (e.g., Windows Terminal, standard macOS/Linux terminals); FR-009 covers graceful degradation when it doesn't.
- Styled terminal output (labels, color, status indicator, screen clearing) will be implemented using the Rich Python library, per explicit direction; Rich's built-in non-tty/no-color detection is expected to satisfy the FR-009 degradation requirement.
- The interactive loop builds on the existing LangGraph thread/checkpoint mechanism already used per conversation; each new conversation within a session starts a fresh thread, consistent with today's single-invocation behavior.
- "Human" content refers to the end user's typed input; "AI" content refers to assistant-composed conversational output. Internal-only routing data already surfaced today (e.g., destination, sentiment) is treated as supplementary status info, not a third transcript category, and keeps its current presentation.
- The existing `--json` flag continues to imply non-interactive, single-shot behavior (one query in, one JSON payload out), since machine consumers of `--json` expect a single deterministic payload rather than an interactive loop.
- No new external services or persistence are introduced; this feature is a terminal presentation and input-loop change built on the existing CLI entry point and graph invocation logic.
