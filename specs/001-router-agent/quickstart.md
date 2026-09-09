# Quickstart: Router Agent with Sentiment-Aware Refund Handoff

Validates the feature end-to-end once implemented. See [data-model.md](./data-model.md) and [contracts/](./contracts/) for the exact shapes referenced below.

## Prerequisites

- Python 3.14 environment with project dependencies installed: `uv sync` (or equivalent) from repo root.
- Environment variables set (e.g. in `.env`, currently empty — populate before running against a live model):
  - `OPENROUTER_API_KEY` — required to make live classification/sentiment calls.
  - `OPENROUTER_MODEL` — optional; falls back to the project default if unset (see `research.md` §1).
  - Standard LangSmith tracing variables (e.g. `LANGCHAIN_TRACING_V2=true`, `LANGCHAIN_API_KEY`, `LANGSMITH_PROJECT`) per Constitution Principle IV — optional for local dev, expected in any traced/CI run.

## Run the automated tests (no live API calls required)

```sh
pytest tests/unit/test_router_agent.py -v
pytest tests/integration/test_router_trajectory.py -v
```

Expected outcome:
- Unit tests confirm the state-shaping invariant from [contracts/support-state.md](./contracts/support-state.md): `sentiment` is `None` if and only if the *finalized* `destination == "order_support"`.
- Unit tests in `test_clarify_intent.py` confirm the fixed three-choice answer mapping, the re-ask-on-unrecognized-answer loop (FR-012), and that a refund resolved via clarification carries forward `router_agent`'s original sentiment rather than a new one (FR-013).
- Integration tests confirm, via `agentevals.graph_trajectory.strict.graph_trajectory_strict_match`, that:
  - An order/support-style sample request produces the trajectory `["router_agent", "order_support_agent"]`.
  - A refund/complaint-style sample request produces the trajectory `["router_agent", "refund_agent"]`.
  - An ambiguous or mixed-signal sample request produces the trajectory `["router_agent", "clarify_intent", "order_support_agent"]` or `["router_agent", "clarify_intent", "refund_agent"]`, resuming the paused graph via `Command(resume=<choice>)`.
- All test modules fake/mock the LLM boundary (and, for `clarify_intent`, the `interrupt()` resume value) so they run deterministically offline (per plan Technical Context: Testing).

## Manually exercise the CLI (requires `OPENROUTER_API_KEY`)

```sh
customer-support-fde "What's in the kung pao chicken, does it have peanuts?"
# Destination: order_support
# Query: What's in the kung pao chicken, does it have peanuts?

customer-support-fde --json "My order arrived cold and an hour late, I want my money back"
# {"destination": "refund", "sentiment": "negative", "query": "My order arrived cold and an hour late, I want my money back"}

customer-support-fde "hello"
# Are you: (1) placing an order, (2) asking a general question, or (3) requesting a refund? Reply with 1, 2, or 3.
# > 3
# Destination: refund
# Sentiment: neutral
# Query: hello
```

## Validation checklist (maps to spec Success Criteria)

- [ ] SC-001: Running the full labeled sample set (order/support, refund, and ambiguous/mixed-signal cases) through the integration tests yields ≥90% correct final destinations.
- [ ] SC-002: For every refund-path test case, `sentiment` is present; for every order/support-path case, it is absent — asserted directly in `test_router_agent.py` and `test_clarify_intent.py`.
- [ ] SC-003: Sample requests with punctuation/casing edge cases come back with `user_query` unchanged, character-for-character.
- [ ] SC-004: A reviewer can read a trajectory test's expected list (e.g. `["router_agent", "refund_agent"]` or `["router_agent", "clarify_intent", "refund_agent"]`) and the assertion result without running the placeholder nodes' own logic.
- [ ] SC-005: A manual CLI run against a live model completes in well under 3 seconds under normal network conditions (excluding time spent waiting on a clarifying answer).
- [ ] SC-006: Every ambiguous/mixed-signal sample in the labeled set triggers the clarifying question rather than a silent default.
- [ ] SC-007: For every clarified-to-refund sample, the forwarded `sentiment` matches `router_agent`'s original computed value exactly.
