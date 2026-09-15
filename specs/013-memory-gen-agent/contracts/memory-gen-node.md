# Contract: `memory_gen_node`

**Module**: `src/customer_support_fde/nodes/memory_gen_node.py`

**Signature**: `memory_gen_node(state: SupportState) -> SupportState`

Registered in `graph.py` on its own branch off `cart_summary`, running concurrently with
`ticket_gen_node` (research.md Decisions 1–2). Never called directly by anything else.

## Preconditions

- Called only after `cart_summary_node` has run for the current turn (i.e. the customer just
  confirmed their order). The graph never reaches this node from the refund flow.
- `state["messages"]` holds the full order-support conversation transcript up to and including
  confirmation.
- `state["account_number"]` and `state["account_preferences"]` are present (may be `None`),
  per `specs/012-account-identification-node`.

## Behavior

1. **Guard** (FR-002): if `state.get("account_number")` is `None`, return `{}` immediately. No
   LLM call, no database access.
2. **Build the extraction/merge request**: a system prompt (below) plus, if
   `state.get("account_preferences")` is not `None`, a message stating the account's current
   stored preferences, followed by the entirety of `state["messages"]`.
3. **Call the model** via the same `ChatOpenAI`/OpenRouter client shape used elsewhere in this
   codebase (`base_url="https://openrouter.ai/api/v1"`, `api_key` from `OPENROUTER_API_KEY`,
   model from `OPENROUTER_MODEL` env var, falling back to the module's `DEFAULT_MODEL`).
4. **Interpret the reply**:
   - Exactly `"None"` (case-insensitive, stripped) → nothing to record. If prior preferences
     existed, leave them untouched (do not overwrite with `NULL`). No database write occurs.
   - Any other text → the full replacement value for `accounts.preferences` for this account.
5. **Persist** via `db.update_account_preferences(account_number, new_preferences)` (skipped
   entirely in the "None"/no-op case above).
6. **Return `{}`** in every case (success, no-op, or failure) — this node never changes
   `SupportState` (research.md Decision 3).

## Error handling (FR-008)

The model call and the database write are wrapped in one `try/except Exception`, logged via
`_logger.warning("...", exc_info=True)`. On any exception, the function returns `{}` without
raising — the account's existing `preferences` value is left exactly as it was (the failed write
never happens; a `sqlite3`/`OrderStoreError` raised by `db.update_account_preferences` is caught
by this same handler, not allowed to propagate).

## System prompt contract (research.md Decision 8)

The prompt MUST direct the model to:

1. Read the customer's order-support conversation and identify explicit statements about food
   likes, dislikes, or allergies — including one-off per-order customization requests (e.g. "no
   onions on this one"), per the spec's Clarifications.
2. If given a "current stored preferences" passage, combine it with anything newly found into
   one rewritten, coherent passage — never simply append; preserve every previously known fact
   (especially allergies) unless a newer statement in this conversation explicitly contradicts
   it, in which case the newer statement wins (FR-005, Edge Cases).
3. When the same conversation contains contradictory statements about the same thing, keep only
   the customer's most recent statement (Edge Cases).
4. Distinguish allergies from everything else in the output text — e.g. lead with an explicit
   `Allergies: ...` clause when one or more exist, followed by likes/dislikes/customizations —
   so a future feature reading this text back can treat allergies as closer to a hard constraint
   and everything else as a guideline (FR-010, Clarifications).
5. Reply with exactly `None` (and nothing else) only when there is nothing to record at all: no
   prior preferences were supplied AND nothing new was found in the conversation. Otherwise
   always reply with the full passage (even if it ends up identical to the prior one).

## Non-goals (explicitly out of scope for this node)

- It does not alter `state["messages"]` or any other `SupportState` field.
- It does not read `db.get_account` — it trusts `state["account_preferences"]` as the "current"
  value (Assumptions: single customer, single session).
- It does not implement the consumption side (reading `accounts.preferences` back into a future
  conversation and applying the guideline-vs-allergy distinction) — that already exists in
  `order_support_agent._build_context_messages` and is unchanged by this feature.
