# Contract: `SupportState` (extended again)

Extends `specs/002-order-support-agent/contracts/support-state.md`, which remains authoritative
for `user_query`, `destination`, `sentiment`, `menu_items`, `order_confirmed`, and
`order_ticket`. This document supersedes only what it explicitly calls out below.

**Revision note (2026-09-11)**: adds `order_conversation_summary`; changes the meaning of
`messages` for the order-support loop from a per-turn scratch list to a persistent transcript.

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
    order_conversation_summary: str | None   # NEW
    # ...(order_summary, order_id, order_lookup, refund_* fields unchanged)
```

## Changed field

- `messages` — **for the order-support loop specifically**: no longer reset at the start of
  every customer turn. It persists across the whole conversation, holding only
  `HumanMessage`/`AIMessage`/`ToolMessage` entries (never the system prompt, cart summary, or
  running summary — those are assembled fresh per call by `_build_context_messages`, per
  `contracts/order-support-agent.md`). Bounded in size by the condensation guard at the top of
  `call_model`, which removes turns older than the most recent 3 once the accumulated token
  count exceeds 20,000 and more than 3 turns exist.

  This explicitly supersedes `specs/002-order-support-agent/contracts/support-state.md`'s
  guarantee #1 and its change-policy warning against repurposing `messages`'s per-turn-reset
  semantics — that warning is satisfied here via exactly the spec/plan update it required.

  The refund loop's use of `messages` (`refund_agent.py`) is unaffected — it already
  accumulates per `specs/002-order-support-agent/contracts/support-state.md`'s original scope,
  which only ever described the order-support loop's per-turn reset.

## New field

- `order_conversation_summary` — `str | None`, starts `None`. The order-support agent's running
  summary of every turn older than the 3 most recently retained ones, maintained by the
  condensation guard inside `call_model`. Rewritten fresh (never appended to) on each
  condensation pass. Not meaningful outside an active `order_support` conversation; unrelated to
  the refund loop's fields.

## Guarantees provided by the order-support tool-calling loop (updated)

Supersedes `specs/002-order-support-agent/contracts/support-state.md`'s guarantee list for this
loop:

1. `messages` accumulates every real exchange for the life of the conversation, except for
   turns the condensation guard has folded into `order_conversation_summary` and removed.
2. `order_tools` (`ToolNode`) executes exactly the tool calls the model requested against the
   live `SupportState`; unchanged from `specs/002-order-support-agent`.
3. `await_customer` reads `order_confirmed` only after that turn's inner tool-calling loop has
   fully settled — unchanged.
4. `destination` and `sentiment` pass through unchanged — unchanged.
5. If `call_model`'s reply-generating model call itself fails, the failure propagates —
   unchanged. (Only the condensation guard's own model call is caught and swallowed; see
   `contracts/order-support-agent.md` guarantee #4.)
6. Once the condensation guard runs successfully, `order_conversation_summary` reflects every
   turn older than the retained last 3, and those turns' messages are no longer present in
   `state["messages"]`.

## Consumers

Unchanged from `specs/002-order-support-agent/contracts/support-state.md`: `confirm_node`,
`ticket_gen_node`. Neither reads `order_conversation_summary`; it is scoped to the conversation
and not carried into the order ticket (spec Assumptions).

## Change policy

Unchanged in spirit from `specs/002-order-support-agent`: any future feature reading or
extending `messages`, `order_conversation_summary`, `menu_items`, `order_confirmed`, or
`order_ticket` MUST NOT repurpose their meaning without a corresponding spec/plan update.
