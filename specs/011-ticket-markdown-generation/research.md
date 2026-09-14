# Phase 0 Research: Ticket Markdown Generation

**Feature**: `specs/011-ticket-markdown-generation` | **Date**: 2026-09-14

No `[NEEDS CLARIFICATION]` markers remain in [spec.md](./spec.md) — two were resolved
interactively during `/speckit-clarify` (filename scheme, write-failure behavior). This phase
resolves the implementation-approach questions the feature raises.

---

## Decision 1: One `ticket_gen_node`, dispatching on `destination`; a separate `tickets.py` for rendering/writing

**Decision**: `graph.py`'s two separate terminal nodes collapse into one. `nodes/ticket_gen_node.py`
exports a single public `ticket_gen_node(state) -> SupportState` that dispatches on
`state["destination"]` to one of two internal functions, `_order_ticket_node` (today's
`ticket_gen_node` body) and `_refund_ticket_node` (today's `refund_ticket_node` body):

```python
def ticket_gen_node(state: SupportState) -> SupportState:
    if state["destination"] == "refund":
        return _refund_ticket_node(state)
    return _order_ticket_node(state)
```

`graph.py` registers only this one node and routes both terminal edges to it —
`cart_summary -> ticket_gen_node` and `refund_await_customer -[resolved]-> ticket_gen_node` —
each still followed by `-> END`. A separate module, `src/customer_support_fde/tickets.py`, holds
the markdown-rendering and file-writing logic; both internal functions call into it after
building their respective ticket dict.

**Rationale**: This directly matches CLAUDE.md's own architecture description — a single
"Ticket Summary Agent" that produces *either* ticket type, not two independent node functions
each wired into its own branch. `destination` is already known and unambiguous by the time
either branch reaches this point (set once by `router_agent`, never both in one conversation),
so dispatching on it is a plain `if`, not a new classification step. Keeping `tickets.py`
separate still holds for the same reason as before: Principle II wants file I/O/rendering kept
out of the state-transformation module, and it stays unit-testable without a `SupportState`
fixture.

**Alternatives considered**:

- *Keep two separate node functions (original 011 plan)*: Rejected on review — the graph never
  runs both in one conversation, so two node identities only added a second thing to keep in
  sync with the shared `tickets.py` writer, for no behavioral benefit over one node with an
  internal branch.
- *Inline the markdown rendering directly in `ticket_gen_node.py`*: Rejected — mixes state/LLM
  logic with file I/O in one module, harder to unit test the rendering/writing logic in
  isolation (no `SupportState` fixture needed).
- *A dedicated `ticket_write_node` graph node after the unified node*: Rejected — pure wiring
  overhead; the unified node already has everything it needs (the built ticket dict) to call a
  plain function before returning.

---

## Decision 2: Tickets folder defaults to `tickets/`, overridable the same way as the database path

**Decision**: `tickets.py` exposes `tickets_dir() -> Path`, resolving
`CUSTOMER_SUPPORT_TICKETS_DIR` if set, else `Path("tickets")` (relative to the working
directory). The directory is created with `Path.mkdir(parents=True, exist_ok=True)` immediately
before the first write in a process (FR-007).

**Rationale**: Mirrors the existing `db.database_path()` / `CUSTOMER_SUPPORT_DB` convention
(`db.py`) that CLAUDE.md's Setup section already documents, so the project has one consistent
pattern for "where does generated output live, and how do you override it" rather than
inventing a second one (Principle III).

**Alternatives considered**:

- *Hardcode `tickets/` with no override*: Rejected — every other on-disk output in this project
  (`customer_support.db`) is overridable for tests and deployment; an un-overridable path would
  be the odd one out and would force tests to `chdir` instead of setting an env var.
- *A CLI flag (`--tickets-dir`)*: Rejected — no other output path in the project is
  flag-configured; would be a second, inconsistent override mechanism for no added value over
  the existing env-var convention.

---

## Decision 3: Filenames are `<type>-<order_id>.md`; unknown order ids get a random fallback suffix

**Decision**: `write_order_ticket` writes to `tickets/order-<order_id>.md`. `write_refund_ticket`
writes to `tickets/refund-<order_id>.md` when the order id is known, or
`tickets/refund-unknown-<uuid4().hex>.md` when it is not. A write for the same type and known
order id overwrites the previous file for that order (per the `/speckit-clarify` answer and
FR-008); each unknown-order refund ticket gets its own random suffix so those never collide with
each other, satisfying the edge case in spec.md without contradicting the "order ID only" naming
choice for the normal case.

**Rationale**: Directly implements FR-008/FR-010 and the clarified answer. Using the raw order
id (not `db.format_order_id`'s hyphenated display form) avoids a second hyphen convention
colliding with the `<type>-` prefix and keeps the filename a single unambiguous token per
segment.

**Alternatives considered**:

- *Timestamp-appended filenames*: Rejected in `/speckit-clarify` — the user explicitly chose
  order-ID-only naming over order-ID-plus-timestamp.
- *`format_order_id`'s hyphenated form in the filename*: Rejected — `order-K7QP-3M9X.md` reads
  ambiguously (is `K7QP` or `K7QP-3M9X` the id?) versus `order-K7QP3M9X.md`.

---

## Decision 4: Order tickets are written only when `order_ticket["lines"]` is non-empty

**Decision**: `_order_ticket_node` (the order branch of `ticket_gen_node`, `research.md`
Decision 1) calls `tickets.write_order_ticket(order_ticket)` only when `order_ticket["lines"]`
is non-empty; `write_order_ticket` itself also guards on this (belt and suspenders, since it is
a public function other callers could reach directly) and returns `None` without writing when
there is nothing to record.

**Rationale**: FR-003 — no ticket file for a support-only or abandoned-order interaction. The
existing order-ticket-building logic (today's `ticket_gen_node`, becoming `_order_ticket_node`)
already computes `order_ticket["lines"]` as `[]` (via `_EMPTY_SUMMARY`) whenever `order_summary`
is missing, which is exactly the "customer didn't order anything" condition FR-003 describes —
no new state field is needed to detect it.

**Alternatives considered**:

- *Gate on `order_confirmed` instead of `order_ticket["lines"]`*: Rejected — `order_confirmed`
  is not present on every path that reaches this branch with an equivalent meaning, and
  `order_ticket["lines"]` is already the value the existing tests
  (`test_ticket_gen_node_defaults_when_order_summary_missing`) assert is empty in exactly this
  case, so reusing it needs no new coupling.

---

## Decision 5: The issue/complaint text is extracted from the conversation by an LLM call inside `_refund_ticket_node`; the other three refund-ticket fields stay state-sourced

**Decision**: `_refund_ticket_node` (the refund branch of `ticket_gen_node`, Decision 1) keeps
building `order_id`, `sentiment`, and `refund_created` exactly as today — from
`state["order_lookup"]`, `state["sentiment"]`, and `state["refund_request"] is not None`
respectively. No new `SupportState` field is added and `tools/refund_tools.py` is untouched.
Only the `issue` field is new, and it is **not** threaded through state at all: a new helper,
`_extract_refund_issue(state) -> str | None`, makes a plain (non-tool-bound) LLM call over
`state.get("refund_conversation_summary")` (if any) followed by `state["messages"]` — the full
accumulated refund transcript, kept un-cleared across turns per
`specs/007-refund-policy-agent/research.md` Decision 7 — asking for a one-to-two-sentence
statement of the customer's issue in their own terms. This mirrors the plain-LLM-call pattern
`refund_agent.py` already uses for summary condensation (`llm.invoke(condense_input).content`,
`nodes/refund_agent.py:139`), reusing the same `_build_llm()` shape (a fresh helper in
`ticket_gen_node.py`, not the tool-bound one from `refund_agent.py`).

**Rationale**: Order ID, sentiment, and refund-created status are exact facts the graph already
tracks with certainty — re-deriving them from free text would risk the ticket disagreeing with
what state says actually happened (a mistyped order id, a misjudged refund outcome), for a
narrative field that needs no such precision. The issue/complaint text is the opposite: it is
inherently a summary of unstructured conversation, which is exactly what an LLM call is for, and
sourcing it this way needs **no changes to `refund_tools.py` or `state.py`** — the original plan
(a `refund_issue` state field set by `process_refund_request`/`log_complaint`) only existed to
work around not having this option; reading the transcript directly at ticket-generation time is
simpler and touches fewer files.

**Alternatives considered**:

- *Thread `refund_issue` through `SupportState` via the two tools (original Decision 5)*:
  Rejected on review — works, but requires modifying two tool functions and a state field for
  something `ticket_gen_node` can read directly from the transcript it already has access to.
- *Also derive `order_id`/`refund_created`/`sentiment` from the conversation via the same LLM
  call*: Rejected — these are precise facts the graph state already carries reliably (an exact
  8-character order id, a definite create/no-create outcome); asking an LLM to reconstruct them
  from prose adds a failure mode with no upside over reading the field that is already correct.
- *Re-assess sentiment from the full conversation at ticket time*: Considered — `sentiment` is
  currently a one-time classification of the customer's opening message
  (`nodes/router_agent.py`), never updated as the conversation continues, so it may not reflect
  how the customer felt by the end. Rejected for this feature: it would produce a second,
  possibly-conflicting sentiment judgment alongside the one `refund_agent` already used for tone
  during the conversation itself, and re-scoping what `sentiment` means is a bigger change than
  this feature's remit.

---

## Decision 5a: Extraction failures are logged and degrade to `None`, never raised

**Decision**: `_extract_refund_issue` returns `None` (rendered as `Not recorded` on the ticket,
per `data-model.md`) instead of raising when: there is nothing to read (`refund_conversation_summary`
is `None` and `messages` is empty); the model's own reply is exactly `"None"` (its explicit
signal that no issue was raised); or the LLM call itself throws. On the exception path it also
logs at `WARNING` via `logging.getLogger(__name__)` before returning `None`.

**Rationale**: This mirrors `refund_agent.py`'s condensation call, which also treats an LLM
failure as non-fatal (`except Exception: pass`) rather than breaking the conversation — but adds
logging where that precedent doesn't, because the two failures have different stakes: a failed
condensation just means the next turn's prompt stays a bit longer (self-healing), while a failed
issue extraction is a permanent gap in that ticket's record, worth an operator-visible trace the
same way a failed ticket *write* already is (Decision 6).

**Alternatives considered**:

- *Match the condensation precedent exactly (no logging)*: Rejected — a silently-missing issue
  on a ticket is a worse, less recoverable outcome than a silently-deferred summary, so the same
  silence isn't the right call here even though the failure-handling shape otherwise matches.
- *Let the exception propagate*: Rejected — would block ticket generation (and, by extension,
  the graph reaching `END`) on a transient LLM failure, which is strictly worse than shipping a
  ticket with `issue: Not recorded`.

---

## Decision 6: Ticket-write failures are caught, logged, and never propagate

**Decision**: `write_order_ticket`/`write_refund_ticket` wrap the actual `Path.write_text` call
in `try/except OSError`, logging via the standard library `logging` module
(`logging.getLogger(__name__).error(...)`) on failure and returning normally either way. Callers
(`_order_ticket_node`, `_refund_ticket_node` — the two branches of `ticket_gen_node`, Decision 1)
never see an exception from a failed ticket write.

**Rationale**: Directly implements FR-011 and the clarified answer ("complete normally, just log
the failure"). `logging` to stderr matches the project's existing error-visibility pattern
(`cli.py` already writes operator-facing errors to stderr) without requiring a LangSmith trace
for what is a plain filesystem I/O failure, not agent/tool-call behavor — the constitution's
Principle IV observability requirement targets "agent runs, tool calls, and errors" in the
LLM-driven flow, which this filesystem side-effect sits outside of.

**Alternatives considered**:

- *Let the exception propagate*: Rejected — would violate FR-011 by blocking the
  customer-facing interaction on a filesystem error.
- *Swallow the failure silently with no logging*: Rejected — leaves no record at all that a
  ticket was lost, undermining the entire purpose of the ticket system for that interaction.

---

## Decision 7: No new dependencies; markdown is built with plain string templates; no generation timestamp

**Decision**: Ticket markdown is assembled with plain f-strings/joins, the same manual-templating
style `render_order_summary` (`nodes/cart_summary_node.py`) already uses — no markdown-generation
library. The rendered content is exactly what FR-002/FR-005 list — items + total for an order
ticket, issue/sentiment/order-id/refund-created for a refund ticket — and nothing else; in
particular, no "generated at" timestamp is rendered, since no FR calls for one and adding it
would be scope beyond what the spec asks for (Principle III).

**Rationale**: FR-009 only requires "plain, human-readable markdown" — headings, bold labels,
and bullet lists, all trivially producible as strings. Adding a templating or markdown-building
dependency for this would be unjustified under Principle III and the Technology Constraints
section (new dependencies only when the standard library can't reasonably do it).

**Alternatives considered**:

- *A templating engine (Jinja2, etc.)*: Rejected — the tickets project defines are five to eight
  fixed fields; a templating engine adds a dependency and indirection for no benefit over an
  f-string function.
