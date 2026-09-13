# Contract: `SupportState` (extended again)

Extends `specs/002-order-support-agent/contracts/support-state.md` and
`specs/008-order-history-summarization/contracts/support-state.md`, which remain authoritative
for `user_query`, `destination`, `sentiment`, `menu_items`, `order_confirmed`, `order_ticket`,
and `order_conversation_summary`. This document supersedes only what it explicitly calls out
below, for the refund loop specifically.

**Revision note (2026-09-12)**: adds `refund_conversation_summary`; changes the meaning of
`messages` for the refund loop from a transcript seeded once with the system prompt/sentiment
baked in, to a persistent transcript of only real exchanges.

## Schema

```python
class SupportState(TypedDict):
    user_query: str
    destination: Literal["order_support", "refund", "unclear"]
    sentiment: Literal["positive", "neutral", "negative"] | None
    messages: Annotated[list[AnyMessage], add_messages]
    menu: list[MenuItem]
    menu_items: dict[str, int]
    order_confirmed: bool
    order_ticket: dict | None
    order_summary: dict | None
    order_id: str | None
    order_lookup: dict | None
    refund_resolved: bool
    refund_request: dict | None
    complaint_ids: dict[str, int]
    refund_ticket: dict | None
    order_conversation_summary: str | None
    refund_conversation_summary: str | None   # NEW
```

## Changed field

- `messages` — **for the refund loop specifically**: still persists across the whole
  conversation (unchanged from `specs/007-refund-policy-agent` — it was never wiped), but now
  holds only `HumanMessage`/`AIMessage`/`ToolMessage` entries. The system prompt and sentiment
  reading are no longer baked into it by `_seed_messages`; they are assembled fresh per call by
  `_build_context_messages`, per `contracts/refund-agent.md`. Bounded in size by the
  condensation guard at the top of `refund_agent`, which removes turns older than the most
  recent 3 once the accumulated token count exceeds 20,000 and more than 3 turns exist.

  This explicitly supersedes the seeding behavior `specs/007-refund-policy-agent` shipped
  (`_seed_messages` prepending `SystemMessage` entries into `messages` permanently) — the
  refund loop's persistence guarantee itself (never wiped) is unchanged, only what kind of
  content is allowed to live in `messages`.

  The order-support loop's use of `messages` and `order_conversation_summary`
  (`order_support_agent.py`) is unaffected — this feature does not touch that module (FR-008).

## New field

- `refund_conversation_summary` — `str | None`, starts `None`. The refund agent's running
  summary of every turn older than the 3 most recently retained ones, maintained by the
  condensation guard inside `refund_agent`. Rewritten fresh (never appended to) on each
  condensation pass. Keeps separate orders' facts and reached outcomes distinct when a
  conversation has touched more than one order. Not meaningful outside an active `refund`
  conversation; unrelated to the order-support loop's `order_conversation_summary`.

## Guarantees provided by the refund tool-calling loop (updated)

Supersedes `specs/007-refund-policy-agent`'s implicit seeding contract for this loop:

1. `messages` accumulates every real exchange for the life of the conversation, except for
   turns the condensation guard has folded into `refund_conversation_summary` and removed.
   (The "never wiped" guarantee itself is unchanged from `specs/007`.)
2. `refund_tools` (`ToolNode`) executes exactly the tool calls the model requested against the
   live `SupportState`; unchanged from `specs/007-refund-policy-agent`.
3. `refund_await_customer` reads `refund_resolved` only after that turn's inner tool-calling
   loop has fully settled — unchanged.
4. `destination` and `sentiment` pass through unchanged — unchanged.
5. If `refund_agent`'s reply-generating model call itself fails, the failure propagates —
   unchanged. (Only the condensation guard's own model call is caught and swallowed; see
   `contracts/refund-agent.md` guarantee #4.)
6. Once the condensation guard runs successfully, `refund_conversation_summary` reflects every
   turn older than the retained last 3, and those turns' messages are no longer present in
   `state["messages"]`.
7. `order_lookup`, `refund_request`, `complaint_ids`, and `refund_resolved` are never read from
   or reconstructed out of `messages`/`refund_conversation_summary` — they are written directly
   by tool calls at decision time (`specs/007-refund-policy-agent/contracts/refund-tools.md`)
   and are therefore unaffected by condensation (FR-011).

## Consumers

Unchanged from `specs/007-refund-policy-agent`: `refund_ticket_node`. It does not read
`messages` or `refund_conversation_summary` at all — it builds the refund ticket entirely from
`order_lookup`, `refund_request`, `complaint_ids`, and `sentiment` (see
`specs/007-refund-policy-agent/data-model.md`'s refund ticket shape), so it is structurally
unaffected by this feature.

## Change policy

Unchanged in spirit from `specs/002-order-support-agent` and `specs/008`: any future feature
reading or extending `messages`, `refund_conversation_summary`, `order_lookup`, `refund_request`,
`complaint_ids`, or `refund_ticket` MUST NOT repurpose their meaning without a corresponding
spec/plan update.
