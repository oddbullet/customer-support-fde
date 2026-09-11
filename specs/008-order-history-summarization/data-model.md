# Phase 1 Data Model: Order Support Agent Conversation Memory & Summarization

**Feature**: `specs/008-order-history-summarization` | **Date**: 2026-09-11

No new persisted (SQLite) entities — this feature is entirely in-memory, scoped to the
conversation's `SupportState` and the checkpointer already used by the CLI
(research.md Decision 9). Full node-level behavior is in
[contracts/order-support-agent.md](./contracts/order-support-agent.md); this file covers the
state shape and the two structural concepts (turn, threshold) the contract relies on.

---

## `SupportState` addition

One new field on the existing `TypedDict` in `src/customer_support_fde/state.py`. All other
fields are unchanged.

| Field | Type | Initial | Purpose |
|---|---|---|---|
| `order_conversation_summary` | `str \| None` | `None` | The running, condensed record of everything in the order-support conversation older than the 3 most recently retained exchanges (FR-004, FR-006). Rewritten fresh — never appended to — on each condensation pass. `None` until the token threshold is first crossed with more than 3 completed turns. |

`cli.py` seeds this alongside the other 14 existing keys when building the initial state.

**Change in meaning for an existing field**:

| Field | Old meaning (`specs/002-order-support-agent`) | New meaning (this feature) |
|---|---|---|
| `messages` | Scratch, per-turn list — reset to empty at the start of every customer turn; never carries content across turns. | Persistent transcript of the order-support conversation: every `HumanMessage`/`AIMessage`/`ToolMessage` exchanged, minus whatever `call_model`'s condensation guard has folded into `order_conversation_summary` and removed. System-prompt/cart-summary/running-summary content is never stored here — see research.md Decision 2. |

This is an explicit, intentional supersession of
`specs/002-order-support-agent/contracts/support-state.md`'s guarantee #1 and change policy,
per the spec's Assumptions section.

---

## Conversation Exchange (turn) — structural definition

A turn is not a separate data structure; it is a *segment* of `state["messages"]`:

- A turn **starts** at a `HumanMessage` and includes every message after it up to (but not
  including) the next `HumanMessage`, or the end of the list.
- Because context (system prompt, cart summary, running summary) is never persisted in
  `state["messages"]` (research.md Decision 2), every message in that list belongs to exactly
  one turn, and every turn starts with exactly one `HumanMessage`.
- **"The 3 most recent turns"** = the last 3 `HumanMessage`-started segments in
  `state["messages"]` at the moment `call_model`'s condensation guard runs — i.e., at the top
  of every `call_model` invocation, which is always after the current turn's `HumanMessage` is
  already present (either just appended by `await_customer`, or seeded as the very first
  message of the conversation). This means the most recent of the "3 most recent turns" may
  still be awaiting its reply — the guard never removes it either way, since it's always the
  last `HumanMessage` in the list (research.md Decision 3).
- **"3 or fewer exchanges" (FR-007)** = 3 or fewer `HumanMessage` entries total in
  `state["messages"]` at that same point — condensation is skipped entirely.

No new field is needed to track this — it's derived by scanning for `HumanMessage` instances
each time the guard runs (research.md Decision 4). Because `call_model` runs once per
inner-loop iteration within a turn too, the guard may re-run its (cheap) check several times in
one turn; it is idempotent — once it condenses, the token count drops back under threshold and
later calls in the same turn just no-op.

---

## Token Threshold

`ORDER_HISTORY_TOKEN_THRESHOLD = 20_000` — a module constant in
`src/customer_support_fde/nodes/order_support_agent.py` (FR-002, FR-003, spec Assumptions).

Measured as `llm.get_num_tokens_from_messages(context_messages + state["messages"])`, where
`context_messages` is the same ephemeral list `call_model` is about to prepend for the model
call that follows the guard (system prompt + cart summary, if any + running summary, if any) —
i.e., the threshold check measures what's actually about to be sent to the model, not just the
raw transcript (research.md Decision 5).

---

## Condensation pass — state transition

Given `state["messages"]` with more than 3 `HumanMessage`-started turns and a token count over
`ORDER_HISTORY_TOKEN_THRESHOLD`:

1. `cutoff` = the index of the 3rd-from-last `HumanMessage`.
2. `older_messages` = `state["messages"][:cutoff]` — everything before the last 3 turns.
3. The model is asked to produce one new summary from `state["order_conversation_summary"]`
   (if any) + `older_messages`.
4. On success: `order_conversation_summary` is replaced with the new summary text, and
   `older_messages` are removed from `state["messages"]` via
   `RemoveMessage(id=m.id)` for each — the `add_messages` reducer removes exactly those
   messages by id, leaving the retained last-3-turns segment untouched (FR-005).
5. On failure (the condensation model call raises): `state["messages"]` and
   `order_conversation_summary` are left unchanged — no partial summary, no removed messages,
   no customer-visible error (FR-010) — and `call_model` proceeds to its normal model call for
   that turn. The same check runs again the next time the guard is reached.

```text
state["messages"] = [H1, A1,  H2, T2a, A2,  H3, A3,  H4, A4]
                     |older| |------- last 3 turns -------|
                     (cutoff = index of H2, the 3rd-from-last HumanMessage)
```

Here there are 4 turns (`H1`..`H4`); `older_messages` is everything before `H2`, i.e. just
`[H1, A1]`. `H2` through `A4` — 3 full turns — are retained verbatim.

(`H`=HumanMessage, `A`=AIMessage, `T`=ToolMessage; a turn may contain any number of `A`/`T`
pairs before its final `A` with no `tool_calls`.)
