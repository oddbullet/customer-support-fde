# Quickstart: Validating Interactive CLI Mode

Prerequisites: repo checked out on branch `016-interactive-cli-mode`, `.env` with the OpenRouter
key present, dependencies installed (`rich` is already pinned in `pyproject.toml`, no install
step needed for it specifically).

```sh
uv run customer-support-fde --init-db
```

## 1. Interactive mode starts with zero arguments

```sh
uv run customer-support-fde
```

Expected: a welcome banner appears, followed by a styled input prompt — no query argument was
needed (SC-001). Confirms FR-001, FR-002.

## 2. Turns are labeled and a thinking indicator appears

At the prompt, type a menu question, e.g. `what's in the kung pao chicken?`, and press enter.

Expected:
- Your typed line is echoed back labeled `You:` in its own color.
- A "Thinking..." spinner appears while the request is in flight.
- The assistant's reply is printed labeled `Assistant:` in a different color.

Confirms FR-003, FR-004, FR-011; see `contracts/cli-interactive.md` for the exact labeling
contract.

## 3. A full order, then the screen clears for a new conversation

At the fresh prompt, start and confirm an order (e.g. `I'd like to order a kung pao chicken`,
follow the assistant's prompts through to confirmation).

Expected: once the order is confirmed, the screen clears and a new prompt appears — no restart
of the program was needed, and the previous conversation's transcript is no longer visible.
Confirms FR-005, SC-003, and the clarified screen-clear behavior.

## 4. A second, unrelated conversation in the same run

At the new prompt, ask an unrelated question or start a refund. Confirms the session supports
multiple independent conversations (User Story 3), not just one.

## 5. Exiting

At a fresh prompt, either:
- type `/exit`, or
- press `Ctrl+C`

Expected: a closing message prints and the process exits with status code 0, without needing to
consult any documentation (SC-005). Confirms FR-006. Also confirm that pressing enter on a
blank line, or typing a question that happens to contain the word "exit", does *not* end the
session — only the literal `/exit` command and Ctrl+C do.

## 6. Existing non-interactive paths are unchanged

```sh
uv run customer-support-fde "what's in the kung pao chicken?"
uv run customer-support-fde "what's in the kung pao chicken?" --json
echo "what's in the kung pao chicken?" | uv run customer-support-fde
```

Expected: identical output to before this feature — no welcome banner, no prompt loop, no
thinking spinner, no screen clearing; each exits after one conversation. Confirms FR-007,
SC-004, and the "explicitly unchanged" section of `contracts/cli-interactive.md`.

## 7. Non-color / degraded terminal

```sh
uv run customer-support-fde > transcript.txt
```

(stdout redirected to a file — not a real terminal) Expected: falls through to the existing
single-line-stdin behavior per the `isatty()` dispatch in `research.md`, since stdout is not a
terminal either; no raw ANSI escape codes appear in `transcript.txt`. Confirms FR-009 and the
`isatty()` dispatch decision.

## 8. Automated regression

```sh
uv run pytest tests/unit/test_cli.py tests/unit/test_interactive.py -v
```

Expected: all pass, including the pre-existing `test_cli.py` cases (unmodified assertions) and
the new interactive-mode cases from `test_interactive.py`. Confirms SC-004 (zero regressions)
and Constitution Principle I (test-first coverage of the new module).
