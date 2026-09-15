# Phase 0 Research: Customer Memory Generation Agent

**Feature**: `specs/013-memory-gen-agent` | **Date**: 2026-09-14

No `[NEEDS CLARIFICATION]` markers remain in [spec.md](./spec.md) — the one open question
(whether one-off per-order requests count as preference signals) was resolved interactively
during `/speckit-clarify`. This phase resolves the remaining implementation-approach questions,
reusing established patterns from `specs/008-order-history-summarization`,
`specs/010-refund-conversation-summarization`, `specs/011-ticket-markdown-generation`, and
`specs/012-account-identification-node` wherever they transfer directly.

---

## Decision 1: A new, dedicated node — not folded into `cart_summary_node` or `ticket_gen_node`

**Decision**: Extraction and persistence live in a new `memory_gen_node`
(`src/customer_support_fde/nodes/memory_gen_node.py`), not added as extra logic inside
`cart_summary_node` or `ticket_gen_node`.

**Rationale**: FR-007/SC-003 require this work not to delay ticket delivery, and the feature
request explicitly asks for it to run "at the same time as" ticket generation. Both are only
achievable if this is a separate graph node on its own branch — folding the logic into either
existing node would make its LLM call and DB write sit on the same sequential path as ticket
creation, directly violating FR-007.

**Alternatives considered**: Adding the extraction call at the end of `cart_summary_node` (before
handing off to `ticket_gen_node`) — rejected, since that's still on the critical path to ticket
delivery, exactly what FR-007 forbids. Adding it inside `ticket_gen_node`'s `_order_ticket_node`
branch — rejected for the same reason, and it would also entangle two independently-testable
responsibilities (ticket rendering vs. account memory) in one function, which
Principle III (Simplicity) argues against once they have no shared logic to justify merging.

---

## Decision 2: Graph wiring — a second, independent branch off `cart_summary`, no join node

**Decision**: `graph.py` registers `memory_gen_node` and adds two edges:
`cart_summary → memory_gen_node` and `memory_gen_node → END`, alongside the existing
`cart_summary → ticket_gen_node` and `ticket_gen_node → END`. No fan-in/join node is introduced.

**Rationale**: LangGraph runs all nodes reachable via unconditional edges from a just-completed
node in the same superstep, so both branches execute concurrently without any special
parallel-branch API. Each branch independently reaching `END` is sufficient — nothing needs to
wait for or merge with the other, because (per Decision 3 below) `memory_gen_node` writes no
`SupportState` field, so there is no state key for the two branches to race on or merge. This is
also why the branch is only reachable from `cart_summary`: that node is the order-support flow's
sole confirmation point (spec Assumptions), so the refund flow's own path into `ticket_gen_node`
(via `refund_await_customer`) is untouched — this feature stays scoped to order-support
conversations exactly as the spec requires (FR-001, Assumptions).

**Alternatives considered**:
- *A join/fan-in node before `END`*: rejected — nothing needs to be reconciled between the two
  branches (disjoint state keys), so a join node would be pure ceremony, the kind of speculative
  structure Principle III rules out.
- *A conditional edge choosing between `ticket_gen_node` and `memory_gen_node`*: rejected — that
  would make them sequential/mutually exclusive, defeating the "run at the same time" goal
  entirely.

---

## Decision 3: `memory_gen_node` is a pure side-effect node — no new `SupportState` field

**Decision**: `memory_gen_node` returns `{}` (or an unchanged/empty partial update) in every
case. It never adds or modifies any `SupportState` key; all of its output goes to SQLite via
`db.update_account_preferences`.

**Rationale**: Nothing downstream in the same conversation needs the freshly-extracted
preferences back in state — the order is already confirmed and the ticket is being produced by
the parallel branch, and `order_support_agent.call_model` only reads `account_preferences` at the
*start* of a conversation (`_build_context_messages`, `nodes/order_support_agent.py:100-104`), a
turn that has already passed by the time this node runs. Keeping the return value empty also
sidesteps any interaction with the `messages` channel's `add_messages` reducer — the node simply
never touches `messages`, following the same "return only what changed" convention
`account_identification_node._no_account()` already uses for its own partial updates.

**Alternatives considered**: Writing the merged preferences back into
`state["account_preferences"]` too — rejected as dead state for the remainder of this run (the
conversation is over) and unnecessary complexity for no observable benefit (Principle III).

---

## Decision 4: One LLM call does extraction *and* merge together

**Decision**: A single `ChatOpenAI` call (OpenRouter-backed, same `_build_llm()` shape as
`ticket_gen_node.py` and `order_support_agent.py`) receives the account's current stored
`preferences` (if any) plus the full order conversation `messages`, and returns one rewritten
free-text passage — not two separate calls (one to extract, one to merge).

**Rationale**: A single call keeps the merge "coherent," per FR-005/spec Assumptions (a rewrite,
not a raw append) — the model naturally reconciles old and new information in one pass, the same
way `order_support_agent.call_model`'s re-condensation (Decision 6 of `specs/008`) rewrites its
summary fresh each time rather than appending. Two calls (extract, then separately merge) would
add latency and a second failure point for no accuracy benefit.

**Alternatives considered**: Rule-based/string-append merge (skip the LLM for merging, only use
it for extraction) — rejected: FR-005 requires *combining* into one coherent passage while
FR-010 requires the allergy/other distinction to survive the merge, both of which a raw
string-append cannot guarantee (e.g. it can't drop an outdated contradicted statement per the
Edge Cases section), and the project already trusts an LLM for this exact kind of rewrite
(`specs/008`'s condensation, `ticket_gen_node`'s issue extraction).

---

## Decision 5: The account-number guard is an in-function early return, not a graph-level conditional edge

**Decision**: `memory_gen_node` checks `state.get("account_number")` as its first statement; if
`None`, it returns immediately (no LLM call, no DB access). `graph.py` does not add a conditional
edge to route guests around the node.

**Rationale**: FR-002's requirement is about side effects ("MUST NOT run this review and any
resulting storage"), which a cheap in-function guard fully satisfies — a guest's request still
reaches the node but does zero work and touches neither the LLM nor SQLite, identically
satisfying SC-002 ("zero preference data being written"). This mirrors how the codebase already
handles comparable guards: `order_support_agent.call_model`'s condensation threshold check and
`ticket_gen_node`'s `destination`-based branch are both in-function conditionals, not graph
routing, per `specs/008`/`specs/010`/`specs/011`'s established precedent. A conditional edge would
require a new routing function and a second exit label for one `add_conditional_edges` call,
adding graph complexity to express something one `if` already expresses — the kind of
speculative structure Principle III rules out.

**Alternatives considered**: A conditional edge (`account_number is None` → `END`,
otherwise → `memory_gen_node`) — rejected per the rationale above; functionally equivalent to the
guard clause but strictly more code and one more thing to keep in sync with `graph.py`'s existing
`_route_from_*` helpers.

---

## Decision 6: Extraction/merge failures are swallowed silently — the same scoped exception as elsewhere

**Decision**: The LLM call (and, if it somehow throws, the DB write) is wrapped in a narrow
`try/except Exception`, logged via `_logger.warning(..., exc_info=True)`. On any failure,
`memory_gen_node` returns `{}` and the account's existing `preferences` are left exactly as they
were.

**Rationale**: Directly required by FR-008, and it is the same fail-silent convention already
established by `order_support_agent.call_model`'s condensation guard (`specs/008` Decision 7),
`refund_agent`'s condensation guard (`specs/010` Decision 7), and
`ticket_gen_node._extract_refund_issue`. Since this node's caller (`graph.py`) never inspects its
return value beyond the standard state-merge, there is nothing else to notify — the customer has
already received their order ticket via the parallel branch regardless of this node's outcome.

**Alternatives considered**: Letting the exception propagate — rejected, would fail the entire
graph run for a background enhancement the customer isn't aware of, well past what FR-008
allows.

---

## Decision 7: New `db.py` function — `update_account_preferences`, following existing conventions exactly

**Decision**: Add `update_account_preferences(account_number: str, preferences: str, path:
Path | str | None = None) -> None` to `db.py`, normalizing `account_number` via the existing
`normalize_account_number`, executing `UPDATE accounts SET preferences = ? WHERE account_number =
?`, and raising `OrderStoreError` (a) on any `sqlite3.Error`, following the existing wrap-and-hint
style, and (b) if the update matches zero rows (the account looked up/created earlier in this
same run no longer exists — an invariant violation, not a normal "guest" case, since FR-002's
guard already prevents calling this function without a real `account_number`).

**Rationale**: Matches `get_account`/`create_account`'s existing shape exactly (`_resolve_path`,
a connection opened via `_connect` and closed in `finally`, `OrderStoreError` with a remediation
hint) — no new pattern introduced. No schema change is needed since `accounts.preferences`
already exists (`specs/012-account-identification-node`).

**Alternatives considered**: Reusing `create_account`'s `INSERT ... ON CONFLICT DO UPDATE` style
— rejected; this function only ever updates an existing row (the account was already created or
looked up earlier in the same conversation by `account_identification_node`), so `INSERT` syntax
would be misleading and the `ON CONFLICT` branch would be dead code the tests can't meaningfully
exercise.

---

## Decision 8: Prompt design encodes the allergy/guideline distinction directly (FR-010)

**Decision**: The extraction/merge system prompt instructs the model to (a) preserve every prior
allergy statement unless explicitly contradicted by a newer statement, (b) fold in one-off
per-order customization requests as dislikes/preferences (not allergies), (c) resolve
in-conversation contradictions in favor of the customer's most recent statement, and (d) format
its reply so allergies are unambiguously distinguishable from softer preferences (e.g. leading
with an explicit "Allergies: ..." clause when any exist), and (e) reply with exactly `"None"`
only when there is nothing to record at all (no prior preferences and nothing new found) — the
same "reply with exactly None" sentinel convention `ticket_gen_node._extract_refund_issue`
already uses, letting `memory_gen_node` skip the DB write entirely in that one case without a
separate empty-result state to track. The exact prompt text is a contract, not a state/data
decision — see `contracts/memory-gen-node.md`.

**Rationale**: This is what actually makes the "guideline, not gospel" behavior from
Clarifications work at runtime: `order_support_agent._build_context_messages` already injects
`account_preferences` verbatim into the model's context every conversation
(`nodes/order_support_agent.py:100-104`), unchanged by this feature. Because that consuming model
call is itself an LLM (not hard-coded business logic), a clearly-labeled "Allergies: peanuts."
vs. "Dislikes: onions (asked to leave off one order)." is what lets that *existing* code already
treat the allergy as closer to non-negotiable and the dislike as a soft cue to confirm or steer
around — exactly the behavior described in Clarifications — with zero changes needed to
`order_support_agent.py` itself. This also confirms the spec's own Assumption that "reading this
back into a conversation" is out of this feature's scope: it is already implemented, just
starved of real data until this feature populates `preferences`.

**Alternatives considered**: Storing allergies and other preferences as two separate free-text
fields — rejected by FR-009 (single free-text record, matching the existing schema exactly);
splitting would require a schema/migration change this feature has no reason to make.
