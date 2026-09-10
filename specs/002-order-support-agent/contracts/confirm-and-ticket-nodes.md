# Contract: `nodes/confirm_node.py` and `nodes/ticket_gen_node.py`

Both are intentional placeholders per FR-008 and the spec's Assumptions (see also the 2026-09-10 Clarifications entry that introduced `confirm_node` as a distinct hand-off step).

**Revision note (2026-09-10)**: `order_confirmed` is now set by the `mark_order_confirmed` tool's `Command` return (`contracts/cart-tools.md`), read by `await_customer`'s routing (`contracts/order-support-agent.md`) — not by a `confirm_done` classifier branch. `confirm_node`'s own contract is unaffected.

## `confirm_node(state: SupportState) -> SupportState`

Reached only when `await_customer` observes `order_confirmed == True` (never reached otherwise — see `order-support-agent.md` routing). Pure pass-through: returns `state` unchanged, field-for-field. Its only role is to exist as a separate, connectable step between the order-support tool-calling loop and `ticket_gen_node` — no confirmation logic beyond what `mark_order_confirmed` already performed (FR-006) is re-implemented here.

Unconditional edge: `confirm_node -> ticket_gen_node`.

## `ticket_gen_node(state: SupportState) -> SupportState`

Reached only via `confirm_node`. Returns `state` with `order_ticket` set to `{"items": dict(state["menu_items"])}`; every other field passes through unchanged. Does not implement real ticket formatting/numbering/persistence — that remains the responsibility of the project's ticket summary agent (FR-008).

Unconditional edge: `ticket_gen_node -> END`.

## Guarantees

1. Neither node ever runs when `menu_items` is empty (guaranteed transitively by `mark_order_confirmed` never setting `order_confirmed = True` for an empty cart).
2. `order_ticket["items"]` is always exactly the `menu_items` present at the moment `order_confirmed` became `True` — 100% of added items present (SC-003).
3. Both nodes run at most once per conversation, in the fixed order `confirm_node -> ticket_gen_node -> END` (User Story 3, all three acceptance scenarios).
