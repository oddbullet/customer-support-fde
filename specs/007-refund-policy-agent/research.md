# Phase 0 Research: Refund Policy Agent

**Feature**: `specs/007-refund-policy-agent` | **Date**: 2026-09-11

No `[NEEDS CLARIFICATION]` markers remain in [spec.md](./spec.md) — five were resolved
interactively during `/speckit-clarify`. This phase resolves the implementation-approach
questions the feature raises, in the order they constrain the design.

---

## Decision 1: The LLM gathers facts; a pure function decides eligibility

**Decision**: Refund eligibility is computed by a deterministic, LLM-free function in a new
module `src/customer_support_fde/refund_policy.py`. The agent's language model never decides
whether a refund is granted — it only collects the facts the policy needs (which ordered items
were not received, whether a substitute dish arrived, whether the customer will return it) and
relays the decision.

**Rationale**: SC-001 requires that *zero* refunds are issued outside policy and SC-009
requires identical outcomes across positive, neutral, and negative sentiment. A model asked to
"apply the policy" cannot satisfy either as a guarantee — only as a tendency. Pushing the four
policy conditions (FR-004 through FR-007) into a pure function makes them exhaustively unit
testable without an API key, and makes SC-009 true by construction rather than by evaluation:
the function has no sentiment parameter to be influenced by.

**Alternatives considered**:

- *Policy in the system prompt, model decides*: Rejected — makes SC-001 and SC-009
  unverifiable, and every regression would require live model calls to detect.
- *Policy in the prompt plus a validation function that rejects bad decisions*: Rejected — two
  encodings of the same rules, exactly the drift risk Principle III argues against, with the
  prompt copy adding nothing the function does not already enforce.

---

## Decision 2: Evaluation and persistence happen in one tool call

**Decision**: A single tool, `process_refund_request`, evaluates the policy *and* writes the
resulting record — a refund request when eligible, a complaint when denied. There is no
separate "create refund request" tool the model can reach on its own.

**Rationale**: FR-010 forbids creating a refund request when any condition is unmet. If
evaluation and creation were separate tools, the model could call the creation tool without the
evaluation tool, or after a denial, and SC-001 would depend on the model's discipline. Fusing
them means there is no code path from the model to a stored refund request that does not pass
through the policy function first. It also satisfies FR-018 for free: a denial writes its
complaint in the same call that refused the refund, so a denied customer's issue cannot be
silently dropped.

**Alternatives considered**:

- *Separate `evaluate_refund` and `file_refund_request` tools*: Rejected — leaves a tool the
  model can call to mint an unpoliced refund, which is the single highest-severity failure this
  feature can have.
- *Evaluate in the tool, persist in a downstream graph node*: Rejected — the node would have to
  re-derive the decision from state, reintroducing a second decision point, and it delays the
  write past the point where the agent has already told the customer what happened.

---

## Decision 3: The order under discussion comes from state, not from a model argument

**Decision**: `process_refund_request` and `log_complaint` read the order from
`state["order_lookup"]`, populated by the `lookup_order` tool. Neither tool accepts an order id
as a model-supplied argument.

**Rationale**: FR-002 forbids proceeding to a refund decision for an unidentified order. If the
model passed an order id, it could pass a hallucinated or misremembered one. Reading from state
means the only orders reachable are ones `lookup_order` actually found in the database, and
line names and unit prices used for the amount come from the stored order rather than from the
model's recollection of it (FR-014, SC-008).

**Alternatives considered**:

- *Model supplies `order_id` on each call*: Rejected — permits a refund against an order that
  was never retrieved, and invites transcription errors in the 8-character order id.

---

## Decision 4: Refund amount is derived from stored order lines, using the existing rounding path

**Decision**: The amount sums `Decimal(str(unit_price)) * quantity` over the undelivered lines,
taking `unit_price` from the order row, then converts to `float` — the same construction
`build_order_summary` already uses in `cart_summary_node.py`. Requested quantities are clamped
to the quantity actually ordered on that line.

**Rationale**: SC-008 requires the stored amount to equal the undelivered quantities at
order-recorded unit prices and never to exceed the order total. Using the order's own
`unit_price` (not a live menu lookup) keeps the refund consistent with what the customer
actually paid even if menu prices have since changed — which the assumption in spec.md about no
separate pricing lookup already commits to. Clamping to the ordered quantity is what makes the
"never exceeds the order total" half of SC-008 hold regardless of what the model reports.

**Alternatives considered**:

- *Look up current menu prices*: Rejected — a price change between order and refund would
  produce a refund that does not match the charge, violating SC-008.
- *Reject rather than clamp when quantity exceeds the line*: Considered and partially adopted —
  the tool clamps and says so in its reply, rather than failing the whole request, so a model
  overstating a quantity degrades to a correct refund instead of a dead end.

---

## Decision 5: Complaint de-duplication lives in conversation state, not in a database column

**Decision**: `SupportState` carries `complaint_ids: dict[str, int]`, mapping an order id (or
`""` when no order was identified) to the row id of the complaint already written for it this
conversation. A second denial for the same order updates that row instead of inserting.

**Rationale**: FR-020 scopes complaint uniqueness to one conversation and one order. The
alternative — a `conversation_id` column with a uniqueness constraint — would require
threading a conversation identifier from the CLI's `thread_id` through `SupportState` into
every tool, adding a field and a column to express something the conversation's own state
already knows. FR-021 (an extended complaint keeps its original creation time) falls out
naturally: the row is updated, so `created_at` is never rewritten, and only `description`,
`policy_reason`, and `updated_at` change.

**Alternatives considered**:

- *`conversation_id` column plus `UNIQUE(conversation_id, order_id)`*: Rejected — a new state
  field, a new column, and a new identifier to plumb through, all to re-derive something the
  in-memory state already holds. Fails Principle III.
- *No de-duplication, one row per denial*: Rejected — contradicts FR-020 and SC-010.

---

## Decision 6: Duplicate refund requests are blocked by the database, not only by the tool

**Decision**: `refund_requests.order_id` carries a `UNIQUE` constraint, and the tool also
checks for an existing request before evaluating so it can report that request's status
(FR-011) rather than surfacing an integrity error.

**Rationale**: Unlike complaints, FR-011 spans conversations — a customer can reopen the topic
in a fresh session — so state cannot carry this. Every stored request is by definition pending
or approved (denials are never stored as requests), which makes a plain `UNIQUE` on `order_id`
exactly the constraint FR-011 describes. The tool-level check exists for the customer-facing
message; the constraint exists so SC-007 holds even if that check is ever bypassed.

**Alternatives considered**:

- *Tool-level check only*: Rejected — SC-007 demands "at most one, in 100% of cases," which is
  a claim better backed by the storage layer than by a read-then-write the code could race.

---

## Decision 7: The refund conversation reuses the order agent's loop shape, but keeps its messages

**Decision**: The refund flow mirrors the existing `call_model → tools → await_customer` loop,
with its own nodes. Unlike `await_customer` in the order flow, the refund flow does **not**
clear `messages` between turns — it appends the customer's reply as a `HumanMessage` and lets
the transcript accumulate.

**Rationale**: The order flow can safely wipe messages each turn because everything durable
lives in `state["menu_items"]` and is re-seeded into a fresh prompt. The refund flow's working
facts — which dish was missing, whether a substitute arrived, whether the customer agreed to
return it — are gathered conversationally across turns and have no equivalent structured home
until `process_refund_request` is called. Wiping the transcript would lose them mid-gathering.

**Alternatives considered**:

- *Mirror the order flow and re-seed from structured state*: Rejected — would require
  promoting every partially-gathered fact to a `SupportState` field before the decision is
  made, adding four speculative fields to avoid keeping a transcript the graph already
  supports.

---

## Decision 8: A `conclude_refund_conversation` tool terminates the loop

**Decision**: The agent signals completion with an explicit tool call that sets
`refund_resolved: True`, mirroring how `mark_order_confirmed` sets `order_confirmed` in the
order flow. Recording tools do not themselves end the conversation.

**Rationale**: The spec's mixed-intent edge case requires that a qualifying refund *and* an
unrelated complaint can both be recorded in one conversation. If `process_refund_request` ended
the conversation, the second record could never be written. Separating "record something" from
"we're done here" also matches the existing house pattern, so the graph's termination condition
reads the same way in both flows.

**Alternatives considered**:

- *Recording tools set `refund_resolved` directly*: Rejected — makes the mixed-intent edge case
  unreachable and gives the agent no way to close a conversation that produced no record at all.

---

## Decision 9: Schema extends the existing database via `--init-db`; no migration tooling

**Decision**: The three new tables are appended to `_SCHEMA` in `db.py`, which
`init_database()` applies with `executescript` using `CREATE TABLE IF NOT EXISTS`. Existing
databases pick them up by re-running `customer-support-fde --init-db`.

**Rationale**: CLAUDE.md already documents `--init-db` as idempotent and safe to re-run, and
the existing menu/order tables were introduced the same way. Adding a migration framework for
three additive, non-destructive `CREATE TABLE` statements would be unjustified complexity under
Principle III.

**Alternatives considered**:

- *Add a migration tool (alembic or hand-rolled versioning)*: Rejected — no destructive or
  transforming change exists here to justify it.

---

## Decision 10: No new dependencies

**Decision**: The feature is built entirely from the standard library (`sqlite3`, `datetime`,
`decimal`, `dataclasses`) and dependencies already declared in `pyproject.toml`.

**Rationale**: Principle III and the Technology Constraints section both require that new
dependencies be added only when nothing available can reasonably satisfy the need. Date
arithmetic for the 48-hour window is `datetime.fromisoformat` plus a `timedelta` comparison;
persistence is the `sqlite3` module already in use.

**Observation (pre-existing, not introduced here)**: the constitution names LangSmith a
required dependency, but `pyproject.toml` does not declare `langsmith` explicitly — it arrives
transitively through `langchain`. Tracing works for this feature's nodes and tools without
changes, since they are LangChain runnables. Declaring the dependency explicitly is a
repository-wide concern and is deliberately left outside this feature's scope.

---

## Resolved: the 48-hour window's time handling

`orders.created_at` is written by `db.record_order` as
`datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"` — millisecond
precision, UTC, trailing `Z`. `datetime.fromisoformat` parses this directly on the project's
Python (>=3.14), yielding a timezone-aware value that can be compared against
`datetime.now(timezone.utc)` with no naive/aware mixing.

The boundary is inclusive per the spec's edge case: an order is eligible when
`now - created_at <= timedelta(hours=48)`. The policy function accepts `now` as an injected
parameter so tests can pin ages exactly — at 47:59, at exactly 48:00, and at 48:01 — without
sleeping or freezing the clock.
