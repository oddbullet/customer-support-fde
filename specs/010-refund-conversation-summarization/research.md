# Phase 0 Research: Refund Agent Conversation Memory & Summarization

**Feature**: `specs/010-refund-conversation-summarization` | **Date**: 2026-09-12

No `[NEEDS CLARIFICATION]` markers remain in [spec.md](./spec.md) — one was resolved
interactively during `/speckit-clarify` (multi-order handling in the running summary). This
phase resolves the implementation-approach questions the feature raises, reusing
`specs/008-order-history-summarization/research.md`'s decisions wherever they transfer
directly, and calling out where the refund agent's existing shape forces a different call.

---

## Decision 1: No change needed to *whether* `messages` persists — the refund agent already does this

**Decision**: `refund_agent`/`refund_await_customer` already keep `state["messages"]` across
customer turns (`nodes/refund_agent.py:80-96`, unchanged since `specs/007-refund-policy-agent`).
This feature does not touch that; it only adds the missing bound on how large that transcript is
allowed to grow.

**Rationale**: This is the opposite gap from the order-support agent's (`specs/008`'s Decision
1 introduced persistence where none existed). The refund agent already proves the persistent
shape works within the existing graph/checkpointer setup — nothing to change here.

**Alternatives considered**: None — there is no decision to make; noted only to make explicit
why this plan has no "Decision 1" analogous to 008's.

---

## Decision 2: Move the system prompt and sentiment reading out of `state["messages"]` into ephemeral context, rebuilt fresh each call

**Decision**: `refund_agent` no longer seeds `SystemMessage(SYSTEM_PROMPT)` and (when present)
`SystemMessage(f"Customer sentiment reading: {sentiment}.")` permanently into
`state["messages"]` via `_seed_messages`. Instead, a new `_build_context_messages(state)` helper
— mirroring `order_support_agent.py`'s helper of the same name — assembles the system prompt,
the sentiment reading (if any), and the running summary (if any) into an ephemeral list
prepended to `state["messages"]` on every `refund_agent` invocation, never written back into
state. `state["messages"]` holds only `HumanMessage`/`AIMessage`/`ToolMessage` entries from here
on.

**Rationale**: This is the one place the refund agent's current shape is incompatible with
condensation as designed in `specs/008`: today the system prompt and sentiment reading are
messages 0 and (optionally) 1 in `state["messages"]` itself. Condensation's turn-boundary
detection and cutoff logic (Decision 4 below) operates on "everything before the 3rd-from-last
`HumanMessage`" — if the system prompt stayed in `messages`, it would be exactly the kind of
message that cutoff sweeps into `older_messages` on the very first condensation pass, be handed
to the condensation model as conversation content to summarize, and then be gone from the live
transcript for the rest of the conversation (and never rebuilt, since nothing re-seeds it).
Pulling it into ephemeral context — exactly the fix `specs/008`'s Decision 2 applied to the order
agent for the same structural reason — sidesteps this category of bug entirely: `messages`
becomes purely a transcript of real exchanges, safe to slice by `HumanMessage` position, and the
system prompt/sentiment/summary are always present because they're rebuilt fresh every call
regardless of what condensation has done to `messages`.

Unlike the order agent's cart summary (which must be *re-rendered* every call because its
content changes turn to turn), the refund agent's sentiment reading is fixed for the life of a
conversation (set once by the router). Rebuilding it fresh each call costs nothing extra over
seeding it once, and buys the structural safety above at no cost — so there is no reason to seed
it once and accept the condensation hazard.

**Alternatives considered**:

- *Leave the system prompt/sentiment in `messages`, special-case the cutoff to always skip
  index 0 (and 1, when sentiment is present)*: rejected. This works only as long as those
  messages stay at fixed leading indices, which is true today but is exactly the kind of
  positional assumption `specs/008`'s Decision 2 rejected for the order agent (there, the
  rejected alternative was a fixed-id `SystemMessage` updated in place — a different mechanism,
  same underlying complaint: coupling condensation's cutoff logic to *where* non-transcript
  content happens to sit in `messages`, rather than keeping `messages` free of it entirely).
  Skipping a fixed prefix is also strictly more bookkeeping than the ephemeral-context approach
  for zero behavioral benefit.
- *Keep seeding once (refund agent's existing pattern), and simply never let the cutoff go below
  index 2*: same rejection as above — still couples correctness to a positional invariant that a
  future change to `_seed_messages` could silently break.

---

## Decision 3: Condensation is a guard clause at the top of `refund_agent` — no new graph node

**Decision**: `refund_agent` checks the turn count and token threshold before invoking the
model, on every call (including mid-inner-loop calls after `refund_tools`), the same shape as
`order_support_agent.call_model`'s guard (`specs/008` Decision 3). No new node, no new edge —
the refund loop's topology (`refund_agent ⇄ refund_tools`, `__end__ →
refund_await_customer`) is unchanged from `specs/007-refund-policy-agent`.

**Rationale**: Identical reasoning to `specs/008` Decision 3 — the guard is a cheap, local,
idempotent check, so re-running it on every inner-loop invocation costs a few redundant token
counts, not correctness. Folding it into the one function that already owns this loop is
simpler than a dedicated node per Principle III, and keeps the two agents' condensation logic
structurally parallel, which matters since this feature's entire premise is "do what the order
agent already does."

**Alternatives considered**: Same as `specs/008` Decision 3 (a dedicated `condense_history`
node; checking inside `refund_await_customer` instead) — rejected for the same reasons.

---

## Decision 4: Turn boundaries are structural — no new counter field

**Decision**: A "turn" boundary is the index of each `HumanMessage` in `state["messages"]`,
found the same way `order_support_agent.call_model` does. No `turn_count` field is added to
`SupportState`.

**Rationale**: Identical to `specs/008` Decision 4. Because context (system prompt, sentiment,
summary) is never persisted in `state["messages"]` after Decision 2 above, every message in that
list belongs to exactly one turn, and every turn starts with exactly one `HumanMessage` — either
the very first customer message (seeded directly when `messages` is empty, the same way
`order_support_agent.call_model` seeds it) or one appended by `refund_await_customer`.

**Alternatives considered**: An explicit turn counter — rejected as redundant bookkeeping,
same as `specs/008` Decision 4.

---

## Decision 5: Token counting via the existing `ChatOpenAI` client — no new dependency

**Decision**: The guard measures
`llm.get_num_tokens_from_messages(_build_context_messages(state) + messages)` against a new
module constant, `REFUND_HISTORY_TOKEN_THRESHOLD = 20_000` (FR-002, FR-003; same value as the
order agent's `ORDER_HISTORY_TOKEN_THRESHOLD`, per spec Assumptions).

**Rationale**: Identical to `specs/008` Decision 5 — `get_num_tokens_from_messages` is already
available on the installed `ChatOpenAI`, no new dependency needed. Kept as a separate module
constant (not a shared import from `order_support_agent.py`) so the two agents' condensation
logic remains fully independent modules, consistent with Decision 3's "structurally parallel,
not shared" approach (see Decision 8 below for why no shared helper module is introduced
either).

**Same known limitation, documented rather than solved**: the token count is an approximation
for non-OpenAI models routed through OpenRouter, acceptable for the same reason `specs/008`
Decision 5 gives — a consistent proxy for "getting long" is all FR-002/FR-003 require.

**Alternatives considered**: Same as `specs/008` Decision 5.

---

## Decision 6: Re-condensation rewrites the summary fresh; it never appends

**Decision**: Each time the guard fires, it calls the model with the *previous*
`refund_conversation_summary` (if any) plus the newly-aged-out messages, and asks for one new,
complete summary that replaces the old one (FR-006).

**Rationale**: Identical to `specs/008` Decision 6 — keeps the summary naturally bounded. The
condensation instructions additionally direct the model to keep separate orders' facts and
outcomes distinct (spec Clarifications, FR-004) rather than merging them, since a refund
conversation — unlike an order-support conversation, which only ever concerns one cart — can
legitimately span more than one order.

**Alternatives considered**: Append-only — rejected for the same reason as `specs/008`.

---

## Decision 7: Condensation failures are swallowed silently — the same scoped exception as the order agent

**Decision**: The condensation model call is wrapped in a narrow `try/except Exception`,
isolated to only that call. On failure, the guard leaves `state["messages"]` and
`refund_conversation_summary` unchanged, and `refund_agent` proceeds to its normal
(uncondensed) model call for that turn (FR-010).

**Rationale**: Identical to `specs/008` Decision 7. This remains a narrowly-scoped, explicit
divergence from the codebase's general convention that model-call failures propagate — scoped
to exactly this one `try/except`, mirroring `order_support_agent.call_model`'s.
`refund_agent`'s own reply-generating model call, a few lines later in the same function, still
lets failures propagate unchanged.

**Alternatives considered**: Same as `specs/008` Decision 7.

---

## Decision 8: The running summary is a new, separate plain state field — not shared with the order agent's, and no shared helper module

**Decision**: `SupportState` gains `refund_conversation_summary: str | None`, starting `None` —
a distinct field from `order_conversation_summary`, not a rename or a shared/generic field. The
condensation guard logic itself is written directly inside `refund_agent.py`, as its own
self-contained copy of the pattern `order_support_agent.py` already uses — no shared
`context_management.py`-style helper module is introduced.

**Rationale**: A separate field is required by FR-008 (this feature must not change how the
order support agent manages its own conversation) and by the fact the two conversations are
entirely independent — an order-support conversation and a refund conversation never share a
transcript or a summary. On the shared-helper question: `specs/008`'s own Decision 1 set the
precedent for this project — when the order agent needed the refund agent's existing
"don't wipe messages" shape, it copied the shape rather than extracting a function both nodes
would call, because the two loops' turn/message shapes are each tightly coupled to their own
node (008 Decision 3's stated rationale). The same reasoning applies in reverse here: extracting
a shared condensation helper today would have exactly one caller changed to use it
(`refund_agent.py`) while `order_support_agent.py`'s already-shipped, already-tested inline guard
stays as-is — refactoring working, unrelated code into a shared abstraction to serve a single new
call site is the premature abstraction Principle III rules out, not a simplification.

**Alternatives considered**:

- *Extract a shared `condense_conversation(...)` helper used by both agents*: rejected per the
  rationale above — no second concrete caller exists today (touching
  `order_support_agent.py` is out of this feature's scope), so the abstraction has nothing to
  justify it beyond hypothetical future reuse (Principle III).
- *Reuse `order_conversation_summary` for both agents*: rejected — the two conversations are
  unrelated; conflating their summaries would leak order-support context into a refund
  conversation and vice versa.

---

## Decision 9: No new persisted (SQLite) entity

**Decision**: The running summary lives only in `SupportState`, inside the same checkpointer the
order agent's summary already uses (`cli.py`'s per-invocation `MemorySaver()`). Nothing is added
to `db.py` or `db._SCHEMA`.

**Rationale**: Identical to `specs/008` Decision 9 — the spec's Assumptions section scopes the
summary to the conversation's lifetime, same as the order agent's. This is also consistent with
`specs/007`'s existing persisted entities (`RefundRequest`, `RefundRequestLine`, `Complaint`),
none of which store conversation transcript or summary content — those records are written
directly by tool calls at decision time, independent of how the conversation history is
represented (FR-011 of this spec makes this explicit: condensation must never alter the policy
outcome).

**Alternatives considered**: Same as `specs/008` Decision 9.
