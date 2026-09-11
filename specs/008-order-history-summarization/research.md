# Phase 0 Research: Order Support Agent Conversation Memory & Summarization

**Feature**: `specs/008-order-history-summarization` | **Date**: 2026-09-11

No `[NEEDS CLARIFICATION]` markers remain in [spec.md](./spec.md) — five were resolved
interactively during `/speckit-clarify` (three during the original pass, one revised
afterward). This phase resolves the implementation-approach questions the feature raises.

---

## Decision 1: Stop wiping `messages`; persist the transcript like the refund agent already does

**Decision**: `await_customer` no longer clears `state["messages"]` with
`RemoveMessage(id=REMOVE_ALL_MESSAGES)`. It appends the customer's reply as a new
`HumanMessage` instead — the same shape `refund_await_customer` already uses
(`nodes/refund_agent.py:87-96`).

**Rationale**: This is the feature's core ask (FR-001) and the user-confirmed decision that
this feature supersedes the per-turn wipe documented in
`specs/002-order-support-agent/contracts/order-support-agent.md` guarantee #1. The refund
agent already proves this shape works within the existing graph/checkpointer setup, so no new
persistence mechanism is needed — only the order agent's own reset behavior changes.

**Alternatives considered**:

- *Keep the wipe, add a side-channel memory field*: this was the "smaller change" option
  offered during clarification and explicitly not chosen — it would not give the model the
  actual last-3-turns transcript the spec's User Story 1 depends on, only a summary.

---

## Decision 2: Context (system prompt, cart summary, running summary) is rebuilt fresh on every call, not persisted in `messages`

**Decision**: `state["messages"]` holds only the real conversational turns — `HumanMessage`,
`AIMessage` (with any `tool_calls`), and `ToolMessage` entries. The system prompt, the
rendered cart summary, and the running summary (when one exists) are assembled into an
ephemeral list by a new `_build_context_messages(state)` helper and prepended to
`state["messages"]` on every `call_model` invocation — never written back into state.

**Rationale**: Under the old design, `_seed_messages` ran at the start of *every* turn (since
`messages` was always empty by then), so the cart summary was naturally re-rendered from
`state["menu_items"]` every turn. Simply switching to a persistent transcript and only seeding
once (the refund agent's pattern) would silently regress this: the cart starts empty, so the
one-time seed renders no cart summary at all, and it would never appear for the rest of the
conversation. Rebuilding the context fresh each call keeps the cart summary accurate exactly as
it is today, and gives the running summary a natural place to be injected once condensation
produces one, without hunting for a message id to update in place.

**Alternatives considered**:

- *Seed once like `refund_agent` does (system prompt + sentiment baked into `messages`
  permanently)*: rejected — correct for the refund agent, which has no per-turn-changing
  context to refresh, but would regress the order agent's cart-summary behavior.
- *Store the running summary as a fixed-id `SystemMessage` inside `messages`, updated in place
  via `add_messages`'s same-id-replaces semantics*: rejected — `add_messages` appends
  new/replaced messages in whatever position the reducer chooses relative to existing ones,
  not necessarily right after the leading system prompt, and it adds a class of "which id is
  the summary message" bookkeeping the ephemeral-context approach avoids entirely.

---

## Decision 3: Condensation is a guard clause at the top of `call_model` — no new graph node

**Decision**: `call_model` checks the turn count and token threshold *before* invoking the
model, on every call (including mid-inner-loop calls after `order_tools`). If the guard
condenses, it does so in place and continues with the (now-shorter) `messages` for that same
invocation. There is no separate `condense_history` node and no new graph edge — the order
loop's topology is unchanged from `specs/002-order-support-agent`.

**Rationale**: An earlier version of this design used a dedicated node so the check would run
exactly once per turn, on a transcript containing only fully-completed exchanges. On reflection
that precision isn't load-bearing: the guard is a cheap, local, idempotent check (a
`tiktoken`-based count, no network call), so running it on every inner-loop call_model
invocation within a turn costs a few redundant token counts, not correctness — once it
condenses, the token count drops below threshold and later calls in the same turn just no-op
immediately. Folding it into `call_model` removes an entire node and edge for a check that is
naturally "a guard clause at the top of the function that already owns this loop," which is the
simpler design Principle III asks for.

One consequence worth naming explicitly rather than treating as a defect: because the guard now
runs *after* `await_customer` has already appended the customer's newest message (or, on the
very first turn, after that message is seeded), "the 3 most recent turns" it protects includes
that newest message even when it has no reply yet. This is a different, but equally
well-defined, place to draw the line than checking only between fully-completed turns — see
data-model.md's turn definition, which is written for this placement.

**Alternatives considered**:

- *A dedicated `condense_history` node between `call_model` and `await_customer`*: this was the
  original design. Rejected on reflection as an unnecessary extra node/edge for a check that
  works just as correctly, and more simply, as a guard clause — see Rationale above.
- *Check inside `await_customer`, before appending the new reply*: workable, but conflates two
  responsibilities (interrupting for input, and condensing history) in one function; keeping it
  in `call_model` at least keeps it next to the one thing it exists to protect (the size of the
  context sent to the model).

---

## Decision 4: Turn boundaries are structural — no new counter field

**Decision**: A "turn" boundary is simply the index of each `HumanMessage` in
`state["messages"]`. `call_model`'s condensation guard finds these indices directly; there is
no separate `turn_count` or similar bookkeeping field on `SupportState`.

**Rationale**: Because context messages are never persisted in `state["messages"]` (Decision
2), every message in that list is unambiguously part of some turn, and every turn begins with
exactly one `HumanMessage` — either the very first customer message (seeded directly, not via
`_seed_messages`, since there's no system scaffolding to bundle it with) or one appended by
`await_customer`. Deriving turn boundaries structurally means there's nothing to keep in sync
if the message list is ever mutated by other means, satisfying Principle III (no speculative
bookkeeping beyond what the current requirement needs).

**Alternatives considered**:

- *Track an explicit turn counter on `SupportState`*: rejected — redundant with information
  already recoverable from `messages`, and one more field that could drift out of sync with the
  actual transcript.

---

## Decision 5: Token counting via the existing `ChatOpenAI` client — no new dependency

**Decision**: `call_model`'s condensation guard measures
`llm.get_num_tokens_from_messages(context + state["messages"])` (using a plain, un-tool-bound
`ChatOpenAI` instance from `_build_llm()`) against a new module constant,
`ORDER_HISTORY_TOKEN_THRESHOLD = 20_000` (FR-002, FR-003).

**Rationale**: `get_num_tokens_from_messages` is already available on the installed
`langchain-openai` version's `ChatOpenAI` (verified: `ChatOpenAI(...).get_num_tokens_from_messages`
exists and needs no extra install — it uses `tiktoken`, already present transitively). Adding a
dedicated tokenizer dependency for this one feature would violate Principle III's "add
dependencies only when nothing existing can reasonably satisfy the need."

**Known limitation, documented rather than solved**: `get_num_tokens_from_messages` counts
using an OpenAI tokenizer regardless of which model `OPENROUTER_MODEL` actually points at, so
for a non-OpenAI model routed through OpenRouter the count is an approximation. This is
acceptable because FR-002/FR-003 only need a consistent, monotonic proxy for "conversation is
getting long," not an exact provider-specific token count, and no other tokenizer is available
without a new dependency.

**Alternatives considered**:

- *Add `tiktoken` as a direct dependency and call it directly*: rejected — it's already present
  transitively and already wrapped by the method above; adding it directly buys nothing.
- *Count characters or messages instead of tokens*: rejected — FR-002 specifically asks for a
  token-based measure, and the spec's assumption fixes the threshold at 20,000 tokens.

---

## Decision 6: Re-condensation rewrites the summary fresh; it never appends

**Decision**: Each time the guard fires, it calls the model with the *previous*
`order_conversation_summary` (if any) plus the newly-aged-out messages, and asks for one new,
complete summary that replaces the old one — never string-concatenation of "old summary text"
+ "new summary text" (FR-006, clarified answer 2026-09-11).

**Rationale**: This is the clarified answer that keeps the summary naturally bounded across a
very long conversation, rather than growing linearly with conversation length and eventually
becoming a new instance of the exact problem this feature solves.

**Alternatives considered**: Append-only and hard-capped-append were both raised during
clarification and explicitly not chosen — see spec.md's Clarifications section.

---

## Decision 7: Condensation failures are swallowed silently — a scoped, spec-mandated exception

**Decision**: The condensation model call (a plain `llm.invoke(...)`, no tools bound) is
wrapped in a narrow `try/except Exception`, isolated to only that call. On failure, the guard
leaves `state["messages"]` and `order_conversation_summary` unchanged and `call_model` proceeds
to its normal (uncondensed) model call for that turn — no error surfaces to the customer, and
the threshold is simply re-evaluated on a later turn (FR-010, clarified answer 2026-09-11,
revised from the original "propagate like any other failure" answer).

**Rationale**: This deliberately diverges from the rest of the codebase's convention that
model-call failures propagate rather than being swallowed. It is scoped to exactly the one
`try/except` around the condensation call — `call_model`'s own reply-generating model call, a
few lines later in the same function, still lets failures propagate unchanged
(`specs/002-order-support-agent/contracts/order-support-agent.md` guarantee #5), as do
`order_tools` and `await_customer`. Keeping both calls in the same function makes this
side-by-side contrast easy to see in the code itself, rather than splitting "the call that's
allowed to fail loudly" and "the call that isn't" across two different node functions.

**Alternatives considered**:

- *Propagate the failure like every other model call*: this was the original clarification
  answer; superseded by the user's follow-up correction before planning began.
- *Retry the condensation call inline with backoff*: rejected as unnecessary complexity —
  Principle III — since simply deferring to the next turn's threshold check already gives a
  retry with no extra code.

---

## Decision 8: The running summary is a plain state field, not a message

**Decision**: `SupportState` gains one new field: `order_conversation_summary: str | None`,
starting `None`. It is not stored as a message inside `state["messages"]`.

**Rationale**: Keeping it as a plain string makes each re-condensation pass a single dict
write (`{"order_conversation_summary": new_summary}`) rather than requiring the guard to locate
and replace a specific message by id inside the transcript. It also keeps
`state["messages"]` purely a transcript of real exchanges, which is what makes turn-boundary
detection (Decision 4) simple and unambiguous.

**Alternatives considered**: See Decision 2's rejected alternative (fixed-id `SystemMessage`).

---

## Decision 9: No new persisted (SQLite) entity

**Decision**: The running summary lives only in `SupportState`, inside whatever checkpointer
the graph is compiled with (today, `cli.py`'s per-invocation `MemorySaver()`). Nothing is added
to `db.py` or `db._SCHEMA`.

**Rationale**: The spec's Assumptions section explicitly scopes the summary to the lifetime of
the active conversation and puts cross-session persistence out of scope. The existing
checkpointer already discards all conversation state (messages, cart, summary alike) when the
CLI process exits, which already matches that scope with zero new code.

**Alternatives considered**: *Persist the summary to SQLite so it survives process restarts*:
rejected — not required by any FR/SC in the spec, and would need a conversation/session
identity concept the project does not otherwise have (out of scope per spec Assumptions).
