# Quickstart: Validate Order Support Agent Conversation Memory & Summarization

Runnable validation for [spec.md](./spec.md). The 20,000-token threshold is too large to
reasonably reach by hand-typing a CLI conversation, so automated tests are the primary
validation; the manual section describes how to exercise a real condensation pass anyway.

## Prerequisites

- Working tree with the feature implemented per [plan.md](./plan.md) and `tasks.md`.
- Dependencies installed (`uv sync` or equivalent per `pyproject.toml`) — no new dependencies
  are added by this feature.
- `OPENROUTER_API_KEY` set — needed only for the manual scenario and the trajectory tests that
  call a real model, not for the unit suite.

## 1. Automated validation (primary)

```powershell
uv run pytest tests/unit/test_order_support_agent.py -v
```

Expected: all pass, including the rewritten reset-behavior tests and the new condensation
tests. This suite needs no API key for the turn-boundary/threshold-guard logic (the
condensation call itself is mocked the same way `_build_llm` already is elsewhere in this file).
It must cover, at minimum:

| Scenario | Expected | Requirement |
|---|---|---|
| `await_customer` resumes with a reply | Reply appended as a new `HumanMessage`; prior messages retained (not cleared) | FR-001, supersedes the old reset test |
| 3 or fewer completed turns, token count over threshold | `call_model`'s guard leaves `messages`/`order_conversation_summary` unchanged | FR-007 |
| More than 3 turns, token count at/under threshold | Guard leaves `messages`/`order_conversation_summary` unchanged | FR-003 |
| More than 3 turns, token count over threshold | Turns older than the last 3 removed from `messages`; `order_conversation_summary` set | FR-003, FR-004, FR-005 |
| Condensation triggered a second time with an existing summary | New summary replaces the old one (not appended); still only last 3 turns retained | FR-006 |
| Condensation model call raises | Guard leaves state unchanged; no exception propagates; `call_model` still produces its normal reply that turn | FR-010 |
| `call_model` invoked twice in one turn (inner tool loop) after condensing | Second invocation's guard check is a cheap no-op (already under threshold) | Regression guard for research.md Decision 3 |
| Cart summary rendering | Still reflects current `menu_items` on every `call_model` call, not just the first turn | Regression guard for research.md Decision 2 |

Then the end-to-end trajectory test (calls a real model):

```powershell
uv run pytest tests/integration/test_order_support_trajectory.py -v
```

This replaces `test_messages_do_not_accumulate_across_turns` with a test proving the opposite
of the old contract: messages *do* accumulate across turns up to the threshold, and get
condensed once it's crossed. Because reaching 20,000 real tokens through a live model
conversation is impractical for a fast test, that test should monkeypatch
`ORDER_HISTORY_TOKEN_THRESHOLD` down to a small value (e.g. a few hundred tokens) for the
purposes of the test, and drive enough turns to cross it.

## 2. Confirm the refund and router flows are unregressed

`messages`'s new semantics are scoped to the order-support loop; the refund loop already
accumulates `messages` and is unaffected by this feature (`contracts/support-state.md`).

```powershell
uv run pytest tests/unit/test_refund_agent.py tests/unit/test_router_agent.py tests/unit/test_cli.py -v
```

Expected: all pass, proving the new `order_conversation_summary` state key (seeded in `cli.py`)
and the order loop's changed reset behavior did not disturb the refund or router flows.

## 3. Manual validation of a real condensation pass

Reaching 20,000 tokens by typing is impractical, so temporarily lower the threshold to observe
a real condensation pass end-to-end:

```powershell
python -c "
from customer_support_fde.nodes import order_support_agent
order_support_agent.ORDER_HISTORY_TOKEN_THRESHOLD = 200
from customer_support_fde.cli import run
run()
"
```

Drive a conversation of at least 5-6 turns (ask about a few dishes, add items, ask again),
stating a dislike or allergy in an early turn. Once enough turns have accumulated:

- The agent's replies should still respect the early-stated dislike/allergy even though that
  turn is no longer in the raw transcript (User Story 1).
- Nothing about the conversation should visibly change from the customer's point of view —
  no error, no mention of "summarizing" — condensation is silent by design (FR-010, edge case).

To confirm it actually happened, inspect the checkpointed state after the run (requires a
short script using the same `build_graph`/`thread_id` pattern as `cli.py`, since the CLI itself
doesn't print internal state): `state["order_conversation_summary"]` should be non-`None`, and
`len(state["messages"])` should be smaller than the total turns driven would otherwise produce.

## 4. Confirm no new dependency was introduced

```powershell
git diff --stat -- pyproject.toml uv.lock
```

Expected: no changes, or none beyond what's already on the branch for unrelated reasons — this
feature relies entirely on `ChatOpenAI.get_num_tokens_from_messages`, already available
transitively (research.md Decision 5).
