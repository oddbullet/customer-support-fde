# Contract: Interactive CLI when both models fail

Applies to `interactive._run_conversation` (and therefore `run_interactive`).

## Behavior

When any `graph.invoke(...)` inside a conversation raises `ModelUnavailableError`, the CLI:

1. Prints `TOOL_LIMIT_WARNING` ("Sorry, our system is having some issues right now. Please try
   again later.") in red through `print_warning`.
2. Prints `Press Enter to try again.`
3. Reads one line from stdin. Its content is ignored.
4. Calls `graph.invoke(None, config)` with the **same** `thread_id`, under the "Thinking..."
   status. This re-runs only the failed step, from the last checkpoint.
5. Carries on with the normal loop: prints interrupts, reads answers, returns the final result.

Steps 1–4 repeat for as long as `ModelUnavailableError` keeps being raised. The conversation is
never discarded because of this error.

## Guarantees

- **Nothing lost:** the cart, account, refund details and message history are preserved. The
  customer's last message is not duplicated in state.
- **No internals shown:** raw exception text is never printed for `ModelUnavailableError`.
- **Other errors unchanged:** any other exception still reaches `run_interactive`'s existing
  catch-all (`Error: <exc>`), so behavior is unchanged when `FALLBACK_MODEL` is unset (FR-009).
- **Ctrl+C still quits:** `KeyboardInterrupt` exits during the "Press Enter" wait, as it does
  elsewhere.
