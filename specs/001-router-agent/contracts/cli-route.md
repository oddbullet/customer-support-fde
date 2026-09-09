# Contract: CLI Routing Command

Satisfies Constitution Principle II ("Library-First & CLI Interface" — text in/out protocol, JSON and human-readable output). This is the CLI surface for this feature, exposed via the existing `customer-support-fde` script entry point.

## Invocation

```sh
customer-support-fde "My order arrived cold, I want a refund"
# or
echo "My order arrived cold, I want a refund" | customer-support-fde
```

- **Input**: the customer request text, as a single positional argument, or read from stdin if no argument is given. The full text is passed through unmodified as `user_query` (FR-001, FR-005).
- **Flags**:
  - `--json`: emit machine-readable JSON instead of human-readable text (both read from the same underlying `SupportState`).

## Clarifying exchange (ambiguous or mixed-signal input)

When the router's classification comes back `unclear`, the graph pauses at `clarify_intent`'s `interrupt()` call within the same CLI process invocation — no separate command or flag is needed. The CLI:

1. Prints the three-choice question to stdout, phrased as numbered options (1 = placing an order, 2 = asking a general question, 3 = requesting a refund) so the customer replies with a single digit rather than typing out a phrase (or stderr for the prompt itself, with the final result still following the normal stdout contract below — implementation detail, not user-facing behavior this contract mandates beyond "the question is presented and an answer is read").
2. Reads the customer's answer (`1`, `2`, or `3`) from stdin.
3. Resumes the graph with that answer (`Command(resume=...)`). If the answer doesn't match one of the three choices, the CLI repeats steps 1–2 with the same question (FR-012) — this is `clarify_intent` re-interrupting, not new CLI-level logic.
4. Once resolved, continues exactly as the non-ambiguous path below: prints the final `Destination`/`Sentiment`/`Query` (or JSON equivalent), using the sentiment `router_agent` already computed if the resolved destination is `refund` (FR-013) — the CLI never asks a second, separate sentiment question.

```text
$ customer-support-fde "hello"
Are you: (1) placing an order, (2) asking a general question, or (3) requesting a refund? Reply with 1, 2, or 3.
> 2
Destination: order_support
Query: hello
```

## Output (human-readable, default)

```text
Destination: refund
Sentiment: negative
Query: My order arrived cold, I want a refund
```

For the order/support path, the `Sentiment:` line is omitted entirely (never printed as `None` or blank — reflects the contract that sentiment does not exist for that path):

```text
Destination: order_support
Query: What's in the kung pao chicken?
```

## Output (`--json`)

Refund path:

```json
{"destination": "refund", "sentiment": "negative", "query": "My order arrived cold, I want a refund"}
```

Order/support path (note: `sentiment` key is absent, not `null`, to make FR-004 observable in the CLI contract too):

```json
{"destination": "order_support", "query": "What's in the kung pao chicken?"}
```

## Errors

On any failure to obtain a routing decision (e.g., the OpenRouter call fails) — per FR-011:

- Nothing is printed to stdout (no partial/corrupted result).
- A human-readable error message is printed to stderr.
- The process exits with a non-zero status code.
