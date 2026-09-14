# Contract: `tickets.py` and the unified `ticket_gen_node`

New module `src/customer_support_fde/tickets.py`. Pure file I/O and rendering — takes the ticket
dicts `ticket_gen_node`'s two internal branches build, does not read `SupportState` itself.

## `tickets_dir() -> Path`

Returns `Path(os.environ["CUSTOMER_SUPPORT_TICKETS_DIR"])` when that variable is set and
non-empty, else `Path("tickets")`. Mirrors `db.database_path()` (`research.md` Decision 2). Does
not create the directory — callers that write call `.mkdir(parents=True, exist_ok=True)` first.

## `write_order_ticket(order_ticket: dict) -> Path | None`

- Returns `None` and writes nothing when `order_ticket["lines"]` is empty (`research.md`
  Decision 4).
- Otherwise renders the order ticket markdown (`data-model.md` § Order Ticket File) and writes
  it to `tickets_dir() / f"order-{order_ticket['order_id']}.md"`, creating `tickets_dir()` first
  if needed. Returns the path written.
- On any `OSError` during directory creation or write, logs the failure at `ERROR` via
  `logging.getLogger(__name__)` and returns `None` — never raises (`research.md` Decision 6,
  FR-011).

## `write_refund_ticket(refund_ticket: dict) -> Path | None`

- Always attempts a write (refund tickets are unconditional — FR-004).
- Path is `tickets_dir() / f"refund-{refund_ticket['order_id']}.md"` when `order_id` is not
  `None`, else `tickets_dir() / f"refund-unknown-{uuid.uuid4().hex}.md"`.
- Same failure handling as `write_order_ticket`: logs and returns `None` on `OSError`, never
  raises.

## Callers: the unified `ticket_gen_node` (`nodes/ticket_gen_node.py`)

`graph.py` registers a single node, `ticket_gen_node`, reached from both
`cart_summary -> ticket_gen_node` and `refund_await_customer -[resolved]-> ticket_gen_node`,
each still followed by `-> END` (`research.md` Decision 1):

```python
def ticket_gen_node(state: SupportState) -> SupportState:
    if state["destination"] == "refund":
        return _refund_ticket_node(state)
    return _order_ticket_node(state)
```

`_order_ticket_node` is today's `ticket_gen_node` body (`specs/002-order-support-agent`'s
contract, unchanged) plus one added line: a call to `tickets.write_order_ticket(order_ticket)`
after building the `order_ticket` dict. `_refund_ticket_node` is today's `refund_ticket_node`
body (`specs/007-refund-policy-agent`'s contract, unchanged for `order_id`/`order`/`sentiment`/
`decision`/`refund_request`/`complaint_ids`) plus: a call to `_extract_refund_issue(state)`
(`contracts/refund-issue-extraction.md`) to populate the new `issue` key, `refund_created` set
from `refund_request is not None`, and a call to `tickets.write_refund_ticket(refund_ticket)`
after building the dict. Both branches ignore the `Path | None` the write functions return — the
write's outcome is not surfaced in `SupportState`, per spec.md's assumption that ticket
generation has no customer-visible effect on success or failure.

## Guarantees

1. A ticket file write is attempted at most once per conversation — `ticket_gen_node` runs at
   most once (it is a graph terminal step reached exactly once per conversation, on whichever of
   the two edges the conversation's single `destination` follows), and each branch attempts
   exactly one write.
2. No exception raised by file I/O inside `tickets.py`, or by `_extract_refund_issue`
   (`contracts/refund-issue-extraction.md`), ever reaches `ticket_gen_node` or the graph runner
   (FR-011, SC-006).
3. `write_order_ticket` writes a file if and only if `order_ticket["lines"]` is non-empty
   (FR-001, FR-003, SC-001, SC-002).
4. `write_refund_ticket` writes a file for every call it is given (FR-004, SC-003).
5. Two writes with the same ticket type and the same known `order_id` produce one file on disk
   (the later write's content), never two (FR-008, SC-005).
6. `tools/refund_tools.py` and `state.py` are unmodified by this feature — every field this
   feature adds to `refund_ticket` is either read from existing state or produced by
   `_extract_refund_issue` reading the existing conversation, never by a new state field
   (`research.md` Decision 5).
