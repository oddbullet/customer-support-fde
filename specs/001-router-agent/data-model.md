# Phase 1 Data Model: Router Agent with Sentiment-Aware Refund Handoff

This feature has no persistent storage (see `research.md` / plan Technical Context: Storage = N/A). The entities below exist only as fields on the shared LangGraph state object (`SupportState`) for the lifetime of a single graph invocation.

## SupportState (the Handoff Package)

The single state schema shared by all nodes in the graph — this **is** the "Handoff Package" entity from the spec's Key Entities section.

| Field | Type | Populated by | Notes |
|---|---|---|---|
| `user_query` | `str` | Graph input (caller) | The full, original Customer Request text. Never modified or truncated by any node (FR-005, SC-003). |
| `destination` | `Literal["order_support", "refund", "unclear"]` | `router_agent` node; finalized by `clarify_intent` when it starts as `"unclear"` | The Routing Decision entity. `router_agent` may leave it as the transient `"unclear"` value; `clarify_intent` (reached only in that case) always resolves it to `"order_support"` or `"refund"` before any downstream placeholder node runs (FR-002, FR-008, FR-009). Neither `order_support_agent` nor `refund_agent` — nor the CLI's final output — ever observes `"unclear"`. |
| `sentiment` | `Literal["positive", "neutral", "negative"] \| None` | `router_agent` node; may be overwritten (to `None`) by `clarify_intent` | The Sentiment Assessment entity. `router_agent` always computes it in its one LLM call, regardless of `destination`; it is set to `None` as soon as `destination` is finalized to `"order_support"` — either immediately by `router_agent` (direct classification) or by `clarify_intent` (after resolving an `"unclear"` classification). Whenever the finalized `destination` is `"refund"`, `sentiment` is the value `router_agent` originally computed — never recomputed or re-elicited from the customer (FR-003, FR-004, FR-006, FR-013). |

### Validation rules

- `user_query` MUST be non-empty-string-or-whitespace-tolerant: even empty/near-empty input still produces a routing outcome (falling back to the clarifying question per Edge Cases if intent can't be determined at all), it is never rejected outright.
- `destination` MUST be one of exactly three values at any point in the graph, and exactly one of the first two (`"order_support"`, `"refund"`) by the time any downstream placeholder node or the CLI observes it — `"unclear"` is strictly transient (FR-002, FR-008, FR-009).
- `sentiment` MUST be `None` whenever the *finalized* `destination == "order_support"` — this is a state-shape invariant enforced in code (by `router_agent` for a direct classification, by `clarify_intent` for one resolved from `"unclear"`), never left to the LLM (see `research.md` §2, §7), and is directly asserted by unit tests.
- `sentiment`, when present, MUST be exactly one of the three fixed categories (per Clarifications) — no free-form or numeric values.
- When `clarify_intent` resolves `destination` to `"refund"`, `sentiment` MUST be byte-for-byte the same value `router_agent` originally computed for that request — `clarify_intent` MUST NOT compute, request, or ask the customer for a new sentiment value (FR-013).

### Lifecycle

`SupportState` has no persistence beyond a single graph run; LangGraph's checkpointer (`MemorySaver`) retains per-step snapshots in memory for the duration of that run, not across process restarts, and is used both to support trajectory extraction in tests and — at runtime — to hold the graph paused across an `interrupt()`/resume cycle while `clarify_intent` waits on the customer's answer, within the lifetime of a single CLI process invocation. There are at most two decision points: the router's classification, and — only when that classification is `"unclear"` — the clarifying exchange; this is still not a general multi-turn state machine, and a request is never routed to a downstream placeholder more than once.

## RouterDecision (LLM structured-output contract, internal to `router_agent.py`)

Not part of the graph state itself, but the intermediate shape returned by the LLM call inside the router node before it is copied into `SupportState`.

| Field | Type | Notes |
|---|---|---|
| `destination` | `Literal["order_support", "refund", "unclear"]` | Directly copied to `SupportState.destination`. `"unclear"` covers both a request with no clear order/support-vs-refund signal (FR-008) and one that mixes both (FR-009); code also maps any unparseable model output to `"unclear"` rather than guessing (`research.md` §6). |
| `sentiment` | `Literal["positive", "neutral", "negative"]` | Always requested from the model in the single structured-output call (see `research.md` §2), for every value of `destination` including `"unclear"`. Copied to `SupportState.sentiment` and kept only once `destination` is finalized to `"refund"` (whether directly or via `clarify_intent`); discarded (`None`) otherwise. |

This internal type exists purely to give the LLM call a concrete Pydantic schema for `with_structured_output`; it is not forwarded to downstream nodes as-is.

## ClarificationAnswer (internal to `clarify_intent.py`)

Not part of the graph state, not backed by any LLM call — the parsed result of matching the customer's raw resumed answer against the three fixed choices presented by `clarify_intent`'s `interrupt()` call.

| Value | Meaning | Resulting `SupportState.destination` |
|---|---|---|
| "1" | Customer is ordering (placing an order) | `"order_support"` |
| "2" | Customer has a menu/ingredient/general question (asking a general question) | `"order_support"` |
| "3" | Customer wants a refund/has a complaint (requesting a refund) | `"refund"` |
| *(anything else)* | Unrecognized | Not a valid answer — `clarify_intent` calls `interrupt()` again with the same three-choice question (FR-012) rather than producing a `SupportState` |
