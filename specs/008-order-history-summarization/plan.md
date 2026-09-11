# Implementation Plan: Order Support Agent Conversation Memory & Summarization

**Branch**: `008-order-history-summarization` | **Date**: 2026-09-11 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/008-order-history-summarization/spec.md`

## Summary

Replace the order-support agent's per-turn full-history wipe with a persistent conversation
transcript, bounded by summarization: once a conversation has more than 3 completed turns and
its accumulated token count exceeds 20,000, every turn older than the most recent 3 is folded
into a running summary and removed from the live transcript, so the agent keeps remembering
customer preferences, dislikes, and decisions indefinitely without the underlying model's
context growing without bound.

The load-bearing technical decisions: the transcript now persists the way the refund agent's
already does (research.md Decision 1), but — unlike the refund agent — the system prompt, cart
summary, and running summary are rebuilt fresh on every model call rather than seeded once, so
the cart summary keeps refreshing every turn exactly as it does today (Decision 2).
Condensation is a guard clause at the top of `call_model` itself, with no new graph node or
edge — the turn/threshold check is cheap and idempotent, so it's safe to re-run it on every
inner-loop invocation within a turn (Decisions 3-4). No new dependency is needed for token
counting (Decision 5), and condensation failures are swallowed silently per the clarified
FR-010 — a narrow, explicitly scoped exception to the rest of the codebase's "model failures
propagate" convention, isolated to that one `try/except` inside `call_model` (Decision 7). Full
reasoning in [research.md](./research.md).

## Technical Context

**Language/Version**: Python >=3.14

**Primary Dependencies**: LangGraph, LangChain (+ `langchain-openai` via OpenRouter) — all
already declared. No new dependencies; token counting uses `ChatOpenAI.get_num_tokens_from_messages`,
already available on the installed version (research.md Decision 5).

**Storage**: None new. The running summary lives only in `SupportState`, inside whatever
checkpointer the graph is compiled with (today, `cli.py`'s per-invocation `MemorySaver()`) —
scoped to the conversation's lifetime per the spec's Assumptions (research.md Decision 9).

**Testing**: PyTest. Unit tests mock `_build_llm` for the condensation call the same way the
existing suite already mocks it for the main model call; one integration trajectory test
exercises condensation end-to-end with a monkeypatched, lowered threshold.

**Target Platform**: Cross-platform CLI (developed on Windows; no platform-specific code).

**Project Type**: Single Python package — importable library plus a CLI entry point.

**Performance Goals**: None constrained this iteration — the spec explicitly defers
condensation latency out of scope (clarified 2026-09-11; SC-004 was removed rather than given a
budget).

**Constraints**: Condensation only triggers with more than 3 completed turns and an
accumulated token count over 20,000 (FR-003, FR-007). Condensation failures MUST be invisible
to the customer (FR-010) — the one deliberate, narrowly-scoped exception to this codebase's
general rule that model-call failures propagate.

**Scale/Scope**: Single-user local CLI conversation; feature touches one existing node module
(a guard clause added to `call_model`) and one new `SupportState` field. No new persisted
entity, no new CLI subcommand, no graph topology change.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Evaluated against `.specify/memory/constitution.md` v1.2.0.

| Principle | Gate | Status |
|---|---|---|
| I. Test-First (NON-NEGOTIABLE) | Tests written, reviewed, and failing before implementation; every test carries a one-line comment naming what it verifies and its category | **PASS (committed)** — `/speckit-tasks` must order every test task ahead of the implementation it covers, including the two rewritten tests (`test_await_customer_interrupts_when_not_confirmed`, `test_messages_do_not_accumulate_across_turns`) whose old assertions this feature deliberately inverts. |
| II. Library-First & CLI Interface | Every feature starts as a standalone importable module with a single purpose; human-invocable functionality exposed via CLI | **PASS** — stays inside the existing `nodes/order_support_agent.py` module (already the order-support agent's single-purpose home); no new CLI surface is owed, since the feature changes the existing conversational interface's internal memory handling, not what a human invokes. |
| III. Simplicity (YAGNI) | Simplest design that satisfies the current requirement; no speculative abstraction; added complexity justified | **PASS** — no new dependency (reuses `ChatOpenAI.get_num_tokens_from_messages`), no new module and no new graph node/edge (condensation is a guard clause inside the one function that already owns this loop, research.md Decision 3), no extra bookkeeping field for turn counting (derived structurally from `messages`, Decision 4), and the running summary is a plain `str \| None` rather than a new message-shaped abstraction (Decision 8). |
| IV. Observability & Versioning | Agent runs/tool calls/errors traced via LangSmith; semantic versioning | **PASS** — the condensation guard's model call is a plain LangChain `ChatOpenAI` invocation, traced by the existing configuration with no extra instrumentation. Version bump: `0.3.0` → `0.4.0` (MINOR — behavior changes for the order agent's internal memory handling, but no public field is removed and no existing consumer's required interface changes; purely additive to `SupportState`). |

**No violations. Complexity Tracking section omitted.**

One deliberate, narrowly-scoped divergence from house convention is called out here rather than
in Complexity Tracking, since it isn't a constitution violation: the condensation guard inside
`call_model` swallows its own model-call failures (FR-010), unlike every other model call in
this codebase (including `call_model`'s own reply-generating call, a few lines later in the
same function), which lets failures propagate. See research.md Decision 7 for why, and why it's
scoped to only that one `try/except`.

**Post-Phase 1 re-check**: Re-evaluated after the data model and contracts were written. No
gate changed status. The design added exactly one field and one module constant, plus a guard
clause inside an existing function — no new node, no new module, nothing beyond what's listed
above.

## Project Structure

### Documentation (this feature)

```text
specs/008-order-history-summarization/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── order-support-agent.md   # supersedes specs/002's guarantee #1
│   └── support-state.md         # extends specs/002's, adds order_conversation_summary
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/customer_support_fde/
├── state.py                     # MODIFY: + order_conversation_summary field
├── cli.py                       # MODIFY: seed order_conversation_summary in initial state
└── nodes/
    └── order_support_agent.py   # REWRITE: persistent messages (await_customer appends
                                  #          instead of wiping); _build_context_messages
                                  #          rebuilds system/cart/summary context fresh per
                                  #          call_model invocation; a condensation guard clause
                                  #          at the top of call_model (turn-boundary detection,
                                  #          ORDER_HISTORY_TOKEN_THRESHOLD constant, and
                                  #          silent-failure handling) — no new node

# graph.py is NOT modified — topology is unchanged from specs/002-order-support-agent.

tests/
├── unit/
│   ├── test_order_support_agent.py   # MODIFY: rewrite the two tests tied to the old
│   │                                  #         wipe-every-turn contract; add condensation
│   │                                  #         tests (threshold guard, turn-count guard,
│   │                                  #         re-condensation, silent failure, cart-summary
│   │                                  #         refresh regression guard)
│   └── test_cli.py                   # MODIFY: seed the new state key
└── integration/
    └── test_order_support_trajectory.py  # MODIFY: replace
                                           #  test_messages_do_not_accumulate_across_turns
                                           #  with a test proving accumulation *and*
                                           #  condensation, using a monkeypatched threshold
```

**Structure Decision**: The existing single-package layout is kept unchanged. Everything lives
inside the module that already owns the order-support agent's loop
(`nodes/order_support_agent.py`) rather than a new module or graph node, because condensation is
tightly coupled to that loop's own turn/message shape (research.md Decision 3) — splitting it
out into a separate node would add a graph edge with no correctness benefit, which Principle III
argues against.

## Graph topology

**Unchanged.** This feature adds no node and no edge — the order-support branch's topology is
identical to `specs/002-order-support-agent`; only `call_model`'s function body and
`await_customer`'s reset behavior change.

```text
router_agent ─┬─ "order_support" → call_model ⇄ order_tools
              │                         │ tools_condition "__end__"
              │                         ▼
              │                  await_customer ──┬─ not confirmed → call_model
              │                                    └─ confirmed → cart_summary → ticket_gen_node → END
              ├─ "unclear"       → clarify_intent ─┐
              └─ "refund" ───────────────────────┬─┘
                                                 ▼
                                        refund_agent  (unchanged by this feature)
```

`call_model` now runs a condensation guard clause before generating its reply (see
`contracts/order-support-agent.md`). `await_customer` still interrupts with the agent's last
message, but now **appends** the reply as a new `HumanMessage` instead of clearing `messages`
first — mirroring `refund_await_customer`'s existing shape.

## Phase 0: Research

**Status**: Complete — [research.md](./research.md).

Nine decisions recorded. The ones that most shape the implementation: persisting the
transcript like the refund agent (1), but rebuilding context fresh every call to avoid
regressing the cart-summary refresh (2), condensation as a cheap, idempotent guard clause
inside `call_model` rather than a separate graph node (3), turn boundaries derived structurally
with no new bookkeeping field (4), and condensation failures being swallowed silently as a
narrow, spec-mandated exception isolated to that one `try/except` (7).

## Phase 1: Design & Contracts

**Status**: Complete.

- [data-model.md](./data-model.md) — the one new `SupportState` field, the structural
  definition of a "turn," the token threshold, and the condensation state transition.
- [contracts/order-support-agent.md](./contracts/order-support-agent.md) — the revised node
  contract (`call_model`'s new condensation guard, `await_customer`), explicitly superseding
  `specs/002-order-support-agent`'s guarantee #1. Graph topology and routing are unchanged.
- [contracts/support-state.md](./contracts/support-state.md) — extends
  `specs/002-order-support-agent`'s `SupportState` contract with the new field and the changed
  meaning of `messages` for this loop.
- [quickstart.md](./quickstart.md) — automated validation as the primary path (the 20,000-token
  threshold is impractical to reach by hand), plus a manual scenario using a monkeypatched,
  lowered threshold to observe a real condensation pass.

## Requirements coverage

| Requirements | Satisfied by |
|---|---|
| FR-001 (retain history across turns) | `await_customer` appends instead of wiping (research.md Decision 1) |
| FR-002, FR-003 (track size, condense over threshold) | The guard's `get_num_tokens_from_messages` check against `ORDER_HISTORY_TOKEN_THRESHOLD`, at the top of `call_model` |
| FR-004 (preserve preferences/decisions) | The condensation prompt given to the model by the guard, exercised by the quickstart's manual scenario and unit tests asserting the summary field is populated |
| FR-005 (keep last 3 turns intact) | Structural turn-boundary detection (data-model.md); `RemoveMessage` only targets `older_messages` |
| FR-006 (re-condense, don't append) | The guard always calls the model with the *previous* summary + newly-aged messages and replaces the field wholesale (research.md Decision 6) |
| FR-007 (skip with ≤3 turns) | The turn-count check at the top of the guard |
| FR-008 (scoped to order-support only) | The guard and `order_conversation_summary` are only read/written inside `order_support_agent.py`; refund/router nodes untouched |
| FR-009 (most recent preference wins) | Falls out of FR-004/FR-006: the condensation prompt always sees the full ordered transcript of `older_messages`, so a later restatement naturally supersedes an earlier one in the produced summary |
| FR-010 (silent condensation failure) | The narrow `try/except` around only the guard's own model call (research.md Decision 7) |

## Risks and mitigations

- **The cart summary silently stops refreshing.** This was the most likely regression from
  naively copying the refund agent's "seed once" pattern. Mitigated by rebuilding context fresh
  on every `call_model` call (research.md Decision 2); the quickstart and unit tests both
  explicitly guard this.
- **Redundant re-checks within a turn.** Running the guard at the top of every `call_model`
  call (including mid-inner-loop calls) re-evaluates the token count more often than strictly
  necessary. Accepted as a cheap, local, idempotent cost rather than mitigated with extra state,
  per research.md Decision 3 — introducing a "have I already checked this turn" flag would be
  exactly the speculative bookkeeping Principle III argues against.
- **The condensation model call's failure mode gets confused with `call_model`'s own
  reply-generating call.** Mitigated by scoping the `try/except` to only the guard's own
  `llm.invoke(...)`, a few lines apart from the reply-generating call in the same function;
  nothing else in the loop changes its failure behavior
  (contracts/order-support-agent.md guarantee #8).
- **Existing tests hard-code the old wipe-every-turn contract.** Both affected tests are named
  explicitly in Project Structure and Requirements coverage above so `/speckit-tasks` cannot
  miss them; leaving either unchanged would make the suite red against the new, intended
  behavior.
- **Non-OpenAI models via `OPENROUTER_MODEL` get an approximate token count.** Documented as a
  known, accepted limitation (research.md Decision 5) rather than solved — no exact tokenizer is
  available for an arbitrary OpenRouter-routed model without a new dependency, and FR-002/FR-003
  only need a consistent proxy for "getting long," not an exact count.
