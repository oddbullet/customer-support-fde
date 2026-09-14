# Phase 0 Research: Customer Account Identification Node

**Feature**: `specs/012-account-identification-node` | **Date**: 2026-09-14

No `[NEEDS CLARIFICATION]` markers remain in [spec.md](./spec.md) — four were resolved
interactively during `/speckit-specify` and `/speckit-clarify`. This phase resolves the
implementation-approach questions the feature raises, in the order they constrain the design.

---

## Decision 1: The menu reuses `clarify_intent`'s deterministic interrupt-loop pattern

**Decision**: `account_identification_node` presents its three-option menu and reads the
customer's reply using the exact same shape `clarify_intent.py` already uses: a module-level
`QUESTION` constant, `answer = str(interrupt(QUESTION)).strip()`, and a `while` loop that
re-issues the same `interrupt()` call until the reply is a recognized option (FR-002, FR-012).

**Rationale**: This is a working, tested precedent for exactly the requirement the Clarifications
session settled on (numbered menu, deterministic match, re-prompt on invalid input) already
living in this codebase. Copying its shape keeps the two deterministic menu nodes in the graph
looking and behaving the same way, which is what FR-011's "not open-ended interpretation"
requirement is really asking for.

**Alternatives considered**:

- *Structured-output LLM call to classify the reply (like `router_agent`)*: Rejected — the spec
  and Clarifications explicitly call for a deterministic step, and an LLM classification step
  would reintroduce exactly the ambiguity FR-011/FR-012 rule out.

---

## Decision 2: Account-number generation reuses the existing Crockford base32 scheme via shared private helpers

**Decision**: `db.py`'s existing `_new_order_id()` / `normalize_order_id()` / `format_order_id()`
each become thin wrappers around new generic private helpers (`_new_id()`, `_normalize_id(raw)`,
`_format_id(id_)`) that hold the actual logic (`ID_ALPHABET`, `ID_LENGTH`,
`_CONFUSION_TRANSLATION`). New `_new_account_number()` / `normalize_account_number()` /
`format_account_number()` functions call the same generic helpers. Public function names and
signatures for orders are unchanged.

**Rationale**: The spec's Assumptions call for account numbers to be "short and easy for a
customer to read back and re-enter, consistent with the format already used for order numbers" —
i.e., literally the same scheme. Duplicating the alphabet/length/confusion-folding constants and
logic across two near-identical code paths is exactly the drift risk Principle III (Simplicity)
warns about; factoring the shared one-liners into generic private helpers removes the duplication
while leaving every existing public call site (`db.format_order_id`, `db.normalize_order_id`,
tests, `refund_tools.py`'s docstring reference) untouched.

**Alternatives considered**:

- *Copy-paste new account-specific constants and functions*: Rejected — duplicates the Crockford
  alphabet and confusion-folding table for no behavioral difference, and two copies drift the
  moment one is tweaked (e.g., a future id-length change).
- *One shared `generate_id()`/`normalize_id()`/`format_id()` public API, rename order callers*:
  Rejected — touches existing, already-tested public names and their call sites across
  `refund_tools.py`, `cli.py`, and multiple test files for no functional gain; higher blast radius
  than the chosen approach for the same de-duplication benefit.

---

## Decision 3: `accounts` table is independent, with a nullable `preferences` column

**Decision**: A new `accounts` table: `account_number TEXT PRIMARY KEY`, `preferences TEXT`
(nullable, `NULL` until a future feature populates it), `created_at TEXT NOT NULL`. No foreign
key to `orders` — an account is not tied to any specific order (spec Assumptions).

**Rationale**: `NULL` for "nothing recorded yet" matches how this codebase already represents
absent optional data (e.g. `refund_requests.substitute_dishes`, `complaints.policy_reason`)
rather than an empty-string sentinel. Independence from `orders` matches the spec directly: "A
single account may be used across many separate orders and conversations over time."

**Alternatives considered**:

- *`preferences TEXT NOT NULL DEFAULT ''`*: Rejected — introduces a second "nothing here" value
  (empty string) alongside the codebase's existing `NULL` convention, for no benefit; the
  context-injection code would need to treat both as equivalent anyway.

---

## Decision 4: Placement in the graph — one node, one unconditional outgoing edge

**Decision**: `account_identification_node` is registered once and wired in wherever the graph
currently transitions to `"call_model"` from the order/support path — i.e. `router_agent`'s
`"order_support"` branch and `clarify_intent`'s `"order_support"` branch now point to
`"account_identification_node"` instead of `"call_model"`, and a single new unconditional edge
`account_identification_node → call_model` is added. The refund path is untouched.

**Rationale**: All three menu options (existing account, no account, sign up) converge on the
same next step — talking to the order/support agent — they only differ in what gets written to
`account_number`/`account_preferences` first. A conditional edge with three branches all pointing
at the same node would be needless indirection; Principle III favors the simpler unconditional
edge. This also matches the spec's own framing ("this node should sit between router and order
node") rather than introducing a fork the spec never asked for.

**Alternatives considered**:

- *Conditional edges keyed on the chosen option*: Rejected — every branch would resolve to
  `call_model` anyway, so the conditional adds a routing function and a three-entry mapping with
  no behavioral difference from a single edge.

---

## Decision 5: Not-found recovery is a second, nested menu inside the same node

**Decision**: When an entered account number doesn't match any account (FR-005), the node
presents a second `interrupt()`-driven menu — re-enter the number, sign up instead, or continue
without an account — using the same numbered-reply, re-prompt-until-valid mechanics as the
primary menu (Decision 1). This lives inside `account_identification_node`, not as a separate
graph node.

**Rationale**: The recovery menu is a sub-decision entirely local to the "use an existing
account" path (FR-005) and produces exactly the same three possible outcomes the primary menu
already produces (identified account, no account, or a newly created one). Splitting it into a
separate graph node would add a node and new edges to express something one function's control
flow already handles.

**Alternatives considered**:

- *Separate `account_not_found_node`*: Rejected — adds a node and edges for a decision that has
  no reason to be resumable independently of the step that discovered the account was missing.

---

## Decision 6: Preferences reach the order/support agent as an injected `SystemMessage`, not a tool

**Decision**: `order_support_agent._build_context_messages` gains one more conditional block: when
`state.get("account_preferences")` is not `None`, append
`SystemMessage(content=f"Customer's stored preferences: {preferences}")` to the context list
built for every `call_model` invocation — the same pattern already used for the cart summary and
`order_conversation_summary`.

**Rationale**: FR-004 only requires the text be "available to the order/support agent," and the
Clarifications session settled that this is unstructured free text meant to be used directly as
context, not parsed. Injecting it as a `SystemMessage` on every turn satisfies that with the same
mechanism the codebase already uses for the other two pieces of standing context, and needs no
new `@tool`, no model-invoked lookup, and no risk of the agent "forgetting" it mid-conversation
(unlike a one-shot tool result that could later be pruned by the history-condensation logic).

**Alternatives considered**:

- *A new `get_account_preferences` tool the model calls*: Rejected — adds an optional step the
  model could skip, and the spec's intent (context the agent already has, not something it has to
  ask for) is better served by unconditional injection.
- *Fold preferences into the existing cart-summary `SystemMessage`*: Rejected — conflates two
  independent pieces of context (what's currently in the cart vs. who the customer is) that have
  unrelated lifecycles; keeping them as separate messages matches how the summary/cart messages
  are already kept distinct from each other.

---

## Decision 7: `SupportState` gets two new flat fields, not a nested dict

**Decision**: `account_number: str | None` and `account_preferences: str | None` are added
directly to `SupportState`, both initialized to `None`. No `customer_account: dict | None`
wrapper.

**Rationale**: The spec's Customer Account entity is just an id plus one text field — there's no
multi-field record to bundle. Every other identity-shaped piece of state in this project is
already a flat field (`order_id: str | None`, not a wrapping dict), so two flat fields is the
form consistent with the rest of `SupportState` and needs no new type.

**Alternatives considered**:

- *`account: dict | None` holding `{"account_number": ..., "preferences": ...}`*: Rejected — adds
  a shape with no established precedent in this state, for two fields that are simpler as two
  fields.

---

## Decision 8: Schema and code changes ship through the existing idempotent `--init-db` path; no new dependency

**Decision**: The `accounts` table is appended to `_SCHEMA` in `db.py`, applied by the existing
`init_database()` via `executescript(...)` with `CREATE TABLE IF NOT EXISTS`. No new package is
added to `pyproject.toml` — `sqlite3` (stdlib) and `langgraph.types.interrupt` /
`langchain_core.messages.SystemMessage` (already dependencies) cover everything this feature
needs.

**Rationale**: Matches the precedent already used for every prior schema addition in this project
(`CLAUDE.md`'s documented `--init-db` guarantee, and `specs/007-refund-policy-agent`'s Decision 9)
— additive, non-destructive `CREATE TABLE` statements need no migration tooling under Principle
III.

**Alternatives considered**:

- *A dedicated `--init-accounts-db` flag or separate migration script*: Rejected — no destructive
  or transforming change exists here to justify a second initialization path.
