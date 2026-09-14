# Phase 1 Data Model: Ticket Markdown Generation

This feature adds no database tables and no new `SupportState` fields (`research.md` Decision 5
— the issue/complaint text is read from the existing conversation transcript, not persisted as
new state). It introduces one new on-disk artifact type (the ticket markdown file) and extends
the existing `order_ticket`/`refund_ticket` in-memory shapes that `specs/002-order-support-agent`
and `specs/007-refund-policy-agent` introduced. `SupportState` itself is unchanged from
`specs/010-refund-conversation-summarization`.

## Order Ticket (`order_ticket`, unchanged shape) → Order Ticket File (new)

`_order_ticket_node`, the order branch of the unified `ticket_gen_node`
(`nodes/ticket_gen_node.py`, `research.md` Decision 1), continues to build `order_ticket` exactly
as today: `{"order_id": ..., "items": {...}, "lines": [...], "total": ...}`. This feature adds a
derived, on-disk **Order Ticket File**, written by `tickets.write_order_ticket(order_ticket)`
only when `order_ticket["lines"]` is non-empty (`research.md` Decision 4).

| Attribute | Source | Notes |
|---|---|---|
| Path | `tickets_dir() / f"order-{order_id}.md"` | `order_id` is `order_ticket["order_id"]`, always present when `lines` is non-empty (`cart_summary_node` only assigns an id when the cart has lines). |
| Ordered items | `order_ticket["lines"]` | Each line: name, quantity, unit price, line total — same fields `render_order_summary` already renders for the customer. |
| Total | `order_ticket["total"]` | — |

**Content contract**: exactly the items (name, quantity, unit price, line total) and the order
total — no support Q&A, no refund fields (FR-002).

## Refund Ticket (`refund_ticket`, extended shape) → Refund Ticket File (new)

`_refund_ticket_node`, the refund branch of the unified `ticket_gen_node`
(`nodes/ticket_gen_node.py`, `research.md` Decision 1), continues to build the existing keys
(`order_id`, `order`, `sentiment`, `decision`, `refund_request`, `complaint_ids` — all still
sourced from state exactly as before) and gains two more required by FR-005:

| Field | Type | Populated by | Notes |
|---|---|---|---|
| `issue` | `str \| None` | `_extract_refund_issue(state)` (`nodes/ticket_gen_node.py`) | New. An LLM-generated one-to-two-sentence summary of the customer's issue, read from `state.get("refund_conversation_summary")` + `state["messages"]` — not a new state field (`research.md` Decisions 5, 5a). `None` when there was nothing to summarize, the model found no issue, or the LLM call failed. |
| `refund_created` | `bool` | `state.get("refund_request") is not None` | New. The explicit yes/no FR-005 asks for, distinct from the more detailed `decision` field already on the ticket. Stays state-sourced, not LLM-derived (`research.md` Decision 5) — this is an exact fact the graph already tracks. |

Every `refund_ticket` is written to a derived **Refund Ticket File** by
`tickets.write_refund_ticket(refund_ticket)`, unconditionally (`research.md` Decision 1; FR-004).

| Attribute | Source | Notes |
|---|---|---|
| Path | `tickets_dir() / f"refund-{order_id}.md"`, or `tickets_dir() / f"refund-unknown-{uuid4().hex}.md"` when `order_id` is `None` | `research.md` Decision 3. |
| Order ID | `refund_ticket["order_id"]` | Rendered as `Unknown` in the file body when `None` (FR-010). |
| Issue/complaint | `refund_ticket["issue"]` | Rendered as `Not recorded` when `None` (spec.md edge case: interaction ends with no issue ever raised, or extraction failed — `research.md` Decision 5a). |
| Sentiment | `refund_ticket["sentiment"]` | Rendered as `unavailable` when `None` (spec.md edge case). |
| Refund request created | `refund_ticket["refund_created"]` | Rendered as `Yes`/`No`. |

**Content contract**: issue/complaint, customer sentiment, order ID, and refund-created status —
exactly the four fields FR-005 names (`decision`, `order`, `refund_request`,
`complaint_ids` remain on the in-memory `refund_ticket` dict for any other consumer, but are not
rendered into the markdown file, which follows FR-005's shorter, ticket-facing contract).

## Lifecycle

Both ticket files are write-once-per-conclusion, replace-on-repeat artifacts, not an append-only
log: a second ticket generated later for the same order id and ticket type overwrites the file
from the first (`research.md` Decision 3; spec.md Assumptions). They are never read back by the
graph — purely an output artifact for restaurant staff.
