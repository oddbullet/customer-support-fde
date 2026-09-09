# Contract: `SupportState` (LangGraph state / Handoff Package)

This is the interface contract between the router agent and any downstream node in the graph (today: the two placeholders; in future features: the real order/support and refund agents). Any node added later that consumes router output MUST read this exact shape.

## Schema

```python
class SupportState(TypedDict):
    user_query: str
    destination: Literal["order_support", "refund", "unclear"]
    sentiment: Literal["positive", "neutral", "negative"] | None
```

`"unclear"` is a **transient** value: it is a valid interim result of `router_agent`, but it MUST NOT be observed by `order_support_agent`, `refund_agent`, or the CLI's final output — `clarify_intent` always resolves it to `"order_support"` or `"refund"` first.

## Guarantees provided by the router node (`router_agent`)

1. `user_query` on exit from `router_agent` is byte-for-byte identical to `user_query` on entry (FR-005, SC-003) — the router only reads this field, never rewrites it.
2. `destination` is always set to exactly one of `"order_support"`, `"refund"`, or `"unclear"` on exit from `router_agent` (FR-002, FR-008, FR-009) — no other value, no `None`. `"unclear"` covers both an ambiguous request and one that mixes both order/support and refund signals — `router_agent` MUST NOT guess between `"order_support"` and `"refund"` in either case.
3. `sentiment` is always populated by `router_agent`'s single LLM call, for every value of `destination` (see `research.md` §2, §6). If `destination == "order_support"`, `router_agent` discards it (`None`) before returning state (FR-003, FR-004, FR-006). If `destination == "refund"` or `"unclear"`, `router_agent` keeps the computed value in state — for `"unclear"`, this is so `clarify_intent` can forward it later without recomputing it (FR-013).
4. If the classification/sentiment call fails (e.g., the OpenRouter request errors), `router_agent` raises rather than emitting a `SupportState` with a missing `destination` or a corrupted partial state (FR-011) — no downstream node will ever observe a `SupportState` lacking `destination`.

## Guarantees provided by the clarification node (`clarify_intent`)

Reached only when `router_agent` leaves `destination == "unclear"`. Performs no LLM call.

1. Presents a fixed, hardcoded three-choice question to the customer via `interrupt()`, phrased as numbered options — `1` = placing an order, `2` = asking a general question, `3` = requesting a refund — so the customer replies with a single digit rather than typing out a phrase, using the in-memory `MemorySaver` checkpointer and the run's `thread_id` (no persistent storage; see `research.md` §7).
2. If the resumed answer doesn't match one of the three numbered choices, `clarify_intent` calls `interrupt()` again with the same question rather than guessing or failing (FR-012) — it never returns a `SupportState` for an unrecognized answer.
3. Once a valid choice is received, `destination` on exit from `clarify_intent` is always exactly `"order_support"` or `"refund"` — never `"unclear"` and never anything else.
4. `sentiment` on exit from `clarify_intent` follows the same invariant as `router_agent`: `None` if and only if the resolved `destination == "order_support"`. When the resolved `destination == "refund"`, `sentiment` is exactly the value `router_agent` originally computed for this request — `clarify_intent` MUST NOT ask the customer a separate sentiment question or recompute it (FR-013).
5. `user_query` on exit from `clarify_intent` is unchanged from entry (same guarantee as `router_agent`, FR-005, SC-003).

## Consumers

- `order_support_agent` (placeholder in this feature): MUST accept a `SupportState` with `destination == "order_support"` and `sentiment is None`; reads only `user_query` in this feature (no other behavior defined yet). Never receives `destination == "unclear"`.
- `refund_agent` (placeholder in this feature): MUST accept a `SupportState` with `destination == "refund"` and `sentiment` set to one of the three categories; reads `user_query` and `sentiment` in this feature (no other behavior defined yet). Never receives `destination == "unclear"`.

## Change policy

Any future feature that adds fields to `SupportState` MUST NOT repurpose or remove `user_query`, `destination`, or `sentiment` without a corresponding spec/plan update, since both placeholder nodes and this feature's trajectory tests depend on this exact shape. `destination`'s literal type MUST continue to include `"unclear"` as long as `clarify_intent` exists, since `router_agent`'s conditional edge depends on it.
