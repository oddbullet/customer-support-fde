# Contract: Interactive CLI Session

Satisfies Constitution Principle II ("Library-First & CLI Interface" — text in/out protocol,
JSON and human-readable output). Extends the existing CLI surface
(`specs/001-router-agent/contracts/cli-route.md`) exposed via the `customer-support-fde` script
entry point, without changing any part of that existing contract.

## Invocation

```sh
uv run customer-support-fde
```

with **no query argument**, and with **stdin and stdout both attached to an interactive
terminal** (`sys.stdin.isatty()` and `sys.stdout.isatty()` both true).

If either of those is false (a query argument was given, or stdin/stdout is piped/redirected),
this contract does not apply — the existing behavior in `cli-route.md` (single query in, one
result out, `--json` supported) is used unchanged. This includes:

```sh
uv run customer-support-fde "question"                     # unchanged
echo "question" | uv run customer-support-fde                # unchanged
uv run customer-support-fde "question" --json                # unchanged
```

## Session lifecycle

1. **Welcome**: prints a short banner and instructions (how to ask a question, how to exit),
   satisfying FR-002 and SC-005.
2. **Prompt**: shows a styled input prompt and reads one line as the next question.
3. **Conversation**: the typed question is echoed into the transcript labeled as human input
   (FR-003), then passed into `graph.invoke(...)` with a fresh `thread_id`
   (`data-model.md` — Conversation). While that call is in flight, a "thinking" status indicator
   is shown (FR-011). The response (or, for an ambiguous/order-confirmation interrupt, the
   interrupt's prompt text) is printed labeled as AI output (FR-003, FR-004, FR-008), and any
   further reply the user types in response to an interrupt is echoed labeled as human input,
   exactly like the initial question.
4. **Resolution**: once the conversation reaches a resolved end state (order confirmed, refund
   resolved, or a direct answer with neither), the screen is cleared (FR-005) and the loop
   returns to step 2 for a new, independent conversation.
5. **Exit**: at step 2's prompt, typing `/exit` (case-insensitive) ends the session; `Ctrl+C`
   ends the session from any point (step 2, 3, or while an interrupt answer is pending). Either
   path prints a closing message and exits with status code 0 (FR-006). Blank input or a
   question that happens to contain the word "exit" is treated as an ordinary question, not an
   exit — only the literal `/exit` command and `Ctrl+C` exit the session.

## Output labeling (human vs. AI)

Every printed line in the transcript carries **both**:
- a color style (human vs. AI use visually distinct colors), and
- a plain-text label (e.g. `You:` / `Assistant:`)

so the distinction survives even when color is unavailable (FR-003, FR-009, and the
Clarifications session in `spec.md`).

```text
$ uv run customer-support-fde
Welcome to <restaurant> support. Ask a question, place an order, or request a refund.
Type '/exit' or press Ctrl+C at any time to quit.

You: what's in the kung pao chicken?
⠋ Thinking...
Assistant: Kung Pao Chicken contains chicken, peanuts, and dried chili.

You:
```

(prompt cleared and re-shown after the conversation above resolves — see Session lifecycle
step 4)

## Degraded (non-color) output

When stdout is not a color-capable terminal but this contract otherwise applies (rare —
`isatty()` is true but color support is unavailable), the same `You:` / `Assistant:` labels are
printed without ANSI color codes; no raw escape sequences are ever printed (FR-009).

## Errors

Per FR-010, a mid-conversation error (e.g., the OpenRouter call fails):
- Is reported as a distinctly labeled error line (not styled as either `You:` or `Assistant:`),
  to stderr-equivalent styling within the transcript.
- Does **not** terminate the process — the loop clears the screen and returns to step 2 for a
  new conversation, consistent with the existing single-shot contract's stderr-and-exit-code
  behavior being reserved for the non-interactive path.

## Explicitly unchanged by this contract

- `--json` output format and semantics (`cli-route.md`).
- The piped-stdin, single-line, single-conversation contract
  (`echo "..." | customer-support-fde`).
- The query-as-argument contract, including the numbered clarifying-question exchange described
  in `cli-route.md`'s "Clarifying exchange" section — that exchange now also appears inside the
  interactive loop's step 3, rendered with the same human/AI labeling, but its underlying
  question/answer mechanics (`clarify_intent`'s `interrupt()`, numbered 1/2/3 choices) are
  unmodified.
