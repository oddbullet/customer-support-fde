# Quickstart: Validate Refund Agent Conversation Memory & Summarization

Runnable validation for [spec.md](./spec.md). The 20,000-token threshold is too large to
reasonably reach by hand-typing a CLI conversation, so automated tests are the primary
validation; the manual section describes how to exercise a real condensation pass anyway. This
mirrors `specs/008-order-history-summarization/quickstart.md`'s approach for the order agent's
equivalent feature.

## Prerequisites

- Working tree with the feature implemented per [plan.md](./plan.md) and `tasks.md`.
- Dependencies installed (`uv sync` or equivalent per `pyproject.toml`) — no new dependencies
  are added by this feature.
- `OPENROUTER_API_KEY` set — needed only for the manual scenario and the trajectory tests that
  call a real model, not for the unit suite.

## 1. Automated validation (primary)

```powershell
uv run pytest tests/unit/test_refund_agent.py -v
```

Expected: all pass, including the rewritten seeding-behavior tests (system prompt and sentiment
reading are no longer asserted to live inside `state["messages"]`) and the new condensation
tests. This suite needs no API key for the turn-boundary/threshold-guard logic (the condensation
call itself is mocked the same way `_build_llm` already is elsewhere in this file). It must
cover, at minimum:

| Scenario | Expected | Requirement |
|---|---|---|
| `messages` empty | Seeded with a single `HumanMessage(user_query)` only — no `SystemMessage` in `messages` | FR-001, supersedes the old seeding test |
| `_build_context_messages` with `sentiment` set | Returns system prompt + sentiment `SystemMessage`, in that order | Regression guard for research.md Decision 2 |
| `_build_context_messages` with `sentiment=None` | Omits the sentiment message entirely | Regression guard, supersedes the old omission test |
| `refund_await_customer` resumes with a reply | Reply appended as a new `HumanMessage`; prior messages retained (unchanged from `specs/007`) | FR-001 |
| 3 or fewer completed turns, token count over threshold | Guard leaves `messages`/`refund_conversation_summary` unchanged | FR-007 |
| More than 3 turns, token count at/under threshold | Guard leaves `messages`/`refund_conversation_summary` unchanged | FR-003 |
| More than 3 turns, token count over threshold | Turns older than the last 3 removed from `messages`; `refund_conversation_summary` set | FR-003, FR-004, FR-005 |
| Condensation triggered a second time with an existing summary | New summary replaces the old one (not appended); still only last 3 turns retained | FR-006 |
| Condensation covering a conversation that discussed two different orders | Condensation prompt/instructions direct the model to keep each order's facts and outcome distinct | FR-004, spec Clarifications |
| Condensation model call raises | Guard leaves state unchanged; no exception propagates; `refund_agent` still produces its normal reply that turn | FR-010 |
| `refund_agent` invoked twice in one turn (inner tool loop via `refund_tools`) after condensing | Second invocation's guard check is a cheap no-op (already under threshold) | Regression guard for research.md Decision 3 |
| Sentiment reading still present in context on a later turn | Still reflects `state["sentiment"]` on every call, not just the first turn | Regression guard for research.md Decision 2 |

Then the end-to-end trajectory test (calls a real model):

```powershell
uv run pytest tests/integration/test_refund_trajectory.py -v
```

This should add a test proving messages accumulate across turns up to the threshold and get
condensed once it's crossed — the same shape as `specs/008`'s replacement trajectory test.
Because reaching 20,000 real tokens through a live model conversation is impractical for a fast
test, that test should monkeypatch `REFUND_HISTORY_TOKEN_THRESHOLD` down to a small value (e.g.
a few hundred tokens) and drive enough turns to cross it.

## 2. Confirm the order-support and router flows are unregressed

This feature's changes are scoped to `refund_agent.py` and `SupportState`; the order-support and
router flows must be untouched (FR-008).

```powershell
uv run pytest tests/unit/test_order_support_agent.py tests/unit/test_router_agent.py tests/unit/test_cli.py -v
```

Expected: all pass, proving the new `refund_conversation_summary` state key (seeded in
`cli.py`) and the refund loop's changed message-seeding behavior did not disturb the
order-support or router flows.

## 3. Confirm refund policy outcomes are unaffected by condensation

```powershell
uv run pytest tests/unit/test_db.py -k "refund or complaint" -v
```

Expected: all pass unchanged — condensation never touches `order_lookup`, `refund_request`,
`complaint_ids`, or the persisted `refund_requests`/`complaints` tables (contracts/refund-agent.md
guarantee #5, FR-011). These are written directly by tool calls at decision time, independent of
how `messages`/`refund_conversation_summary` represent the conversation.

## 4. Manual validation of a real condensation pass

Reaching 20,000 tokens by typing is impractical, so temporarily lower the threshold to observe
a real condensation pass end-to-end:

```powershell
python -c "
from customer_support_fde.nodes import refund_agent
refund_agent.REFUND_HISTORY_TOKEN_THRESHOLD = 200
from customer_support_fde.cli import run
run()
"
```

Drive a refund conversation of at least 5-6 turns: identify an order, describe a wrong-item
issue, get denied or asked for more detail, push back on the outcome a couple of times. Once
enough turns have accumulated:

- The agent's replies should still respect the order identified and any facts/outcome already
  established earlier, even though that turn is no longer in the raw transcript (User Story 1).
- Nothing about the conversation should visibly change from the customer's point of view — no
  error, no mention of "summarizing" — condensation is silent by design (FR-010, edge case).

To confirm it actually happened, inspect the checkpointed state after the run (requires a short
script using the same `build_graph`/`thread_id` pattern as `cli.py`, since the CLI itself
doesn't print internal state): `state["refund_conversation_summary"]` should be non-`None`, and
`len(state["messages"])` should be smaller than the total turns driven would otherwise produce.

## 5. Confirm no new dependency was introduced

```powershell
git diff --stat -- pyproject.toml uv.lock
```

Expected: no changes, or none beyond what's already on the branch for unrelated reasons — this
feature relies entirely on `ChatOpenAI.get_num_tokens_from_messages`, already available
transitively (research.md Decision 5), same as the order agent's equivalent feature.
