# Contract: Warning Display and CLI Behavior (`customer_support_fde.interactive`)

## `print_warning(message: str, console: Console | None = None) -> None`

A generic, reusable way to show a system-issue warning to the customer.

- Prints `message` exactly as given, as a `rich.text.Text` with `style="red"`. Square brackets in `message` are not treated as Rich markup.
- On a color terminal, every line of a multi-line message is red (ANSI `\x1b[31m`).
- When output isn't a terminal, the full text is printed with no `\x1b[` sequences.
- An empty `message` prints an empty line and does not raise.
- If `console` is `None`, it uses `_make_console()`.
- Returns nothing and doesn't read stdin.

## `TOOL_LIMIT_WARNING: str`

`"Sorry, our system is having some issues right now. Please try again later."`

## `run_interactive()` behavior change

After `_run_conversation` returns `result`:

| `result.get("tool_limit_reached")` | Behavior |
|------------------------------------|----------|
| `None` / missing | Unchanged: `_print_turn(console, "ai", <last message content>)`, then `console.clear()`. |
| set | `print_warning(TOOL_LIMIT_WARNING, console)`, then print `"Press Enter to start a new conversation."`, read one line from stdin, then `console.clear()` and go back to the prompt. Exit code is unaffected, and the generic `Error:` line is not printed. |

The warning names no tool, agent, or error text (FR-008).
