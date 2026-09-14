# Phase 1 Data Model: Refund Agent Conversation Memory & Summarization

**Feature**: `specs/010-refund-conversation-summarization` | **Date**: 2026-09-12

No new persisted (SQLite) entities — this feature is entirely in-memory, scoped to the
conversation's `SupportState` and the checkpointer already used by the CLI (research.md
Decision 9). Full node-level behavior is in
[contracts/refund-agent.md](./contracts/refund-agent.md); this file covers the state shape and
the two structural concepts (turn, threshold) the contract relies on — deliberately mirroring
`specs/008-order-history-summarization/data-model.md`'s structure for the order agent's
equivalent feature.

---

## `SupportState` addition

One new field on the existing `TypedDict` in `src/customer_support_fde/state.py`. All other
fields, including `order_conversation_summary` (unrelated, order-support-only), are unchanged.

| Field | Type | Initial | Purpose |
|---|---|---|---|
| `refund_conversation_summary` | `str \| None` | `None` | The running, condensed record of everything in the refund conversation older than the 3 most recently retained exchanges (FR-004, FR-006). Preserves each order's facts and reached outcome distinctly when more than one order has been discussed (spec Clarifications). Rewritten fresh — never appended to — on each condensation pass. `None` until the token threshold is first crossed with more than 3 completed turns. |

`cli.py` seeds this alongside the other 15 existing keys when building the initial state.

**Change in meaning for an existing field**:

| Field | Old meaning (`specs/007-refund-policy-agent`) | New meaning (this feature) |
|---|---|---|
| `messages` | Persistent transcript, but seeded once with the system prompt and (if present) the sentiment reading baked in as `SystemMessage` entries at the head of the list (`_seed_messages`); never reset thereafter. | Persistent transcript of only `HumanMessage`/`AIMessage`/`ToolMessage` entries — the system prompt, sentiment reading, and running summary are assembled fresh for each `refund_agent` call by `_build_context_messages` and are never stored in `state["messages"]` (research.md Decision 2). |

This is an explicit, intentional supersession of the seeding behavior
`tests/unit/test_refund_agent.py`'s pre-existing tests assert on (see contracts/refund-agent.md
and quickstart.md for the affected tests) — the same kind of change-in-place `specs/008`
introduced for the order agent's `messages` semantics, applied here in the other direction
(pulling non-transcript content *out* of `messages` rather than *stopping a wipe* of it).

---

## Conversation Exchange (turn) — structural definition

Identical in shape to `specs/008-order-history-summarization/data-model.md`'s definition,
applied to the refund loop:

- A turn **starts** at a `HumanMessage` and includes every message after it up to (but not
  including) the next `HumanMessage`, or the end of the list.
- Because context (system prompt, sentiment reading, running summary) is never persisted in
  `state["messages"]` (research.md Decision 2), every message in that list belongs to exactly
  one turn, and every turn starts with exactly one `HumanMessage`.
- **"The 3 most recent turns"** = the last 3 `HumanMessage`-started segments in
  `state["messages"]` at the moment `refund_agent`'s condensation guard runs — i.e., at the top
  of every `refund_agent` invocation, which is always after the current turn's `HumanMessage` is
  already present (either just appended by `refund_await_customer`, or seeded as the very first
  message of the conversation).
- **"3 or fewer exchanges" (FR-007)** = 3 or fewer `HumanMessage` entries total in
  `state["messages"]` at that same point — condensation is skipped entirely.

No new field is needed to track this — it's derived by scanning for `HumanMessage` instances
each time the guard runs, identically to the order agent's approach (research.md Decision 4).
Because `refund_agent` runs once per inner-loop iteration within a turn too (via `refund_tools`),
the guard may re-run its (cheap) check several times in one turn; it is idempotent.

---

## Token Threshold

`REFUND_HISTORY_TOKEN_THRESHOLD = 20_000` — a module constant in
`src/customer_support_fde/nodes/refund_agent.py` (FR-002, FR-003, spec Assumptions; same value
as `order_support_agent.py`'s `ORDER_HISTORY_TOKEN_THRESHOLD`, but a distinct constant per
research.md Decision 8).

Measured as `llm.get_num_tokens_from_messages(context_messages + state["messages"])`, where
`context_messages` is the same ephemeral list `refund_agent` is about to prepend for the model
call that follows the guard (system prompt + sentiment reading, if any + running summary, if
any) — i.e., the threshold check measures what's actually about to be sent to the model, not
just the raw transcript (mirrors research.md Decision 5, and `specs/008`'s Decision 5).

---

## Condensation pass — state transition

Given `state["messages"]` with more than 3 `HumanMessage`-started turns and a token count over
`REFUND_HISTORY_TOKEN_THRESHOLD`:

1. `cutoff` = the index of the 3rd-from-last `HumanMessage`.
2. `older_messages` = `state["messages"][:cutoff]` — everything before the last 3 turns.
3. The model is asked to produce one new summary from `state["refund_conversation_summary"]`
   (if any) + `older_messages`, instructed to keep each order's facts and reached outcome
   distinct when more than one order appears in `older_messages` (spec Clarifications, FR-004).
4. On success: `refund_conversation_summary` is replaced with the new summary text, and
   `older_messages` are removed from `state["messages"]` via `RemoveMessage(id=m.id)` for each —
   the `add_messages` reducer removes exactly those messages by id, leaving the retained
   last-3-turns segment untouched (FR-005).
5. On failure (the condensation model call raises): `state["messages"]` and
   `refund_conversation_summary` are left unchanged — no partial summary, no removed messages,
   no customer-visible error (FR-010) — and `refund_agent` proceeds to its normal model call for
   that turn. The same check runs again the next time the guard is reached.

```text
state["messages"] = [H1, A1,  H2, T2a, A2,  H3, A3,  H4, A4]
                     |older| |------- last 3 turns -------|
                     (cutoff = index of H2, the 3rd-from-last HumanMessage)
```

Here there are 4 turns (`H1`..`H4`); `older_messages` is everything before `H2`, i.e. just
`[H1, A1]`. `H2` through `A4` — 3 full turns — are retained verbatim.

(`H`=HumanMessage, `A`=AIMessage, `T`=ToolMessage; a turn may contain any number of `A`/`T`
pairs — e.g. a `lookup_order` or `process_refund_request` call and its result — before its
final `A` with no `tool_calls`.)

This transition is structurally identical to `specs/008`'s for the order agent; the only
content difference is what the condensation instructions ask the model to preserve (order-per-
order refund facts and outcomes here, vs. cart preferences/decisions there).
