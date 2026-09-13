# Implementation Plan: Refund Agent Conversation Memory & Summarization

**Branch**: `010-refund-conversation-summarization` | **Date**: 2026-09-12 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/010-refund-conversation-summarization/spec.md`

## Summary

Apply the same conversation-memory bound already shipped for the order support agent
(`specs/008-order-history-summarization`) to the refund agent: once a refund conversation has
more than 3 completed turns and its accumulated token count exceeds 20,000, every turn older
than the most recent 3 is folded into a running summary and removed from the live transcript, so
the agent keeps remembering the order identified, the facts gathered toward a policy decision,
and any outcome already reached — for every order discussed, kept distinct — indefinitely
without the underlying model's context growing without bound.

The refund agent already persists `messages` across turns (unlike the order agent's pre-`008`
state), so this feature does not need `specs/008`'s Decision 1. It does need `specs/008`'s
Decision 2 in the same spirit: today the refund agent's system prompt and sentiment reading are
baked permanently into `state["messages"]` (`_seed_messages`), which would put them squarely in
the path of condensation's cutoff logic. This plan pulls them into an ephemeral context list
rebuilt fresh every call — mirroring `order_support_agent.py`'s `_build_context_messages` —
so `messages` becomes purely a transcript safe to slice by `HumanMessage` position
(research.md Decision 2). Condensation itself is a guard clause at the top of `refund_agent`,
no new graph node or edge (Decision 3), with turn boundaries derived structurally (Decision 4),
no new dependency for token counting (Decision 5), and condensation failures swallowed silently
per FR-010, isolated to that one `try/except` (Decision 7) — all structurally identical to
`specs/008`. The refund-specific addition: the condensation instructions and the running summary
must keep separate orders' facts and outcomes distinct when a conversation touches more than one
order (spec Clarifications, FR-004), since unlike the order agent's single cart, a refund
conversation can legitimately span multiple orders. Full reasoning in
[research.md](./research.md).

## Technical Context

**Language/Version**: Python >=3.14

**Primary Dependencies**: LangGraph, LangChain (+ `langchain-openai` via OpenRouter) — all
already declared. No new dependencies; token counting uses `ChatOpenAI.get_num_tokens_from_messages`,
already available on the installed version (research.md Decision 5).

**Storage**: None new. The running summary lives only in `SupportState`, inside whatever
checkpointer the graph is compiled with (today, `cli.py`'s per-invocation `MemorySaver()`) —
scoped to the conversation's lifetime per the spec's Assumptions (research.md Decision 9). No
change to the persisted `refund_requests`/`refund_request_lines`/`complaints` tables
(`specs/007-refund-policy-agent`) — those are written directly by tool calls, unaffected by
condensation (FR-011).

**Testing**: PyTest. Unit tests mock `_build_llm` for the condensation call the same way the
existing suite already mocks it for the main model call; one integration trajectory test
exercises condensation end-to-end with a monkeypatched, lowered threshold.

**Target Platform**: Cross-platform CLI (developed on Windows; no platform-specific code).

**Project Type**: Single Python package — importable library plus a CLI entry point.

**Performance Goals**: None constrained this iteration — the spec explicitly defers
condensation latency out of scope, consistent with `specs/008`.

**Constraints**: Condensation only triggers with more than 3 completed turns and an
accumulated token count over 20,000 (FR-003, FR-007). Condensation failures MUST be invisible
to the customer (FR-010) — the same deliberate, narrowly-scoped exception to this codebase's
general rule that model-call failures propagate that `specs/008` already established for the
order agent. Condensation MUST NOT alter the refund policy outcome (FR-011).

**Scale/Scope**: Single-user local CLI conversation; feature touches one existing node module
(`refund_agent.py` — a condensation guard added, and `_seed_messages` replaced with
`_build_context_messages`) and one new `SupportState` field. No new persisted entity, no new
CLI subcommand, no graph topology change.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Evaluated against `.specify/memory/constitution.md` v1.2.0.

| Principle | Gate | Status |
|---|---|---|
| I. Test-First (NON-NEGOTIABLE) | Tests written, reviewed, and failing before implementation; every test carries a one-line comment naming what it verifies and its category | **PASS (committed)** — `/speckit-tasks` must order every test task ahead of the implementation it covers, including the three rewritten tests (`test_refund_agent_seeds_system_prompt_and_query_when_messages_empty`, `test_refund_agent_omits_sentiment_message_when_sentiment_is_none`, `test_refund_agent_reuses_existing_transcript_on_later_turns`) whose old assertions this feature deliberately supersedes (research.md Decision 2, data-model.md). |
| II. Library-First & CLI Interface | Every feature starts as a standalone importable module with a single purpose; human-invocable functionality exposed via CLI | **PASS** — stays inside the existing `nodes/refund_agent.py` module (already the refund agent's single-purpose home); no new CLI surface is owed, since the feature changes the existing conversational interface's internal memory handling, not what a human invokes. |
| III. Simplicity (YAGNI) | Simplest design that satisfies the current requirement; no speculative abstraction; added complexity justified | **PASS** — no new dependency (reuses `ChatOpenAI.get_num_tokens_from_messages`), no new module and no new graph node/edge (condensation is a guard clause inside the one function that already owns this loop, research.md Decision 3), no extra bookkeeping field for turn counting (derived structurally from `messages`, Decision 4), and the running summary is a plain `str \| None` (Decision 8). No shared helper module is extracted between the order and refund agents' condensation guards — Decision 8 explains why that would be a premature abstraction with only one real caller today. |
| IV. Observability & Versioning | Agent runs/tool calls/errors traced via LangSmith; semantic versioning | **PASS** — the condensation guard's model call is a plain LangChain `ChatOpenAI` invocation, traced by the existing configuration with no extra instrumentation. Version bump: `0.4.0` → `0.5.0` (MINOR — behavior changes for the refund agent's internal memory handling, but no public field is removed and no existing consumer's required interface changes; purely additive to `SupportState`). |

**No violations. Complexity Tracking section omitted.**

One deliberate, narrowly-scoped divergence from house convention is called out here rather than
in Complexity Tracking, since it isn't a constitution violation: the condensation guard inside
`refund_agent` swallows its own model-call failures (FR-010), unlike every other model call in
this codebase (including `refund_agent`'s own reply-generating call, a few lines later in the
same function), which lets failures propagate. This is the same, already-accepted divergence
`specs/008` established for the order agent (research.md Decision 7 there and here).

**Post-Phase 1 re-check**: Re-evaluated after the data model and contracts were written. No
gate changed status. The design added exactly one field and one module constant, plus a guard
clause and a context-building helper inside an existing function — no new node, no new module,
nothing beyond what's listed above.

## Project Structure

### Documentation (this feature)

```text
specs/010-refund-conversation-summarization/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── refund-agent.md          # supersedes specs/007's _seed_messages contract
│   └── support-state.md         # extends specs/002's/008's, adds refund_conversation_summary
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/customer_support_fde/
├── state.py                # MODIFY: + refund_conversation_summary field
├── cli.py                  # MODIFY: seed refund_conversation_summary in initial state
└── nodes/
    └── refund_agent.py      # REWRITE: replace _seed_messages with _build_context_messages
                              #          (system prompt + sentiment + running summary, rebuilt
                              #          fresh every call, never persisted in state["messages"]);
                              #          add a condensation guard clause at the top of
                              #          refund_agent (turn-boundary detection,
                              #          REFUND_HISTORY_TOKEN_THRESHOLD constant, per-order-aware
                              #          condensation instructions, and silent-failure handling)
                              #          — no new node

# graph.py is NOT modified — topology is unchanged from specs/007-refund-policy-agent.
# order_support_agent.py, router_agent.py are NOT modified (FR-008).

tests/
├── unit/
│   ├── test_refund_agent.py   # MODIFY: rewrite the three tests tied to the old
│   │                           #         seed-into-messages contract; add condensation
│   │                           #         tests (threshold guard, turn-count guard,
│   │                           #         re-condensation, multi-order distinctness, silent
│   │                           #         failure, sentiment-context refresh regression guard)
│   └── test_cli.py            # MODIFY: seed the new state key
└── integration/
    └── test_refund_trajectory.py  # MODIFY: add a test proving accumulation *and*
                                    #  condensation, using a monkeypatched threshold
```

**Structure Decision**: The existing single-package layout is kept unchanged. Everything lives
inside the module that already owns the refund agent's loop (`nodes/refund_agent.py`) rather
than a new module or graph node, because condensation is tightly coupled to that loop's own
turn/message shape (research.md Decision 3) — splitting it out into a separate node, or into a
module shared with `order_support_agent.py`, would add complexity (a graph edge, or a shared
abstraction with one real caller) with no correctness benefit, which Principle III argues
against (research.md Decision 8).

## Graph topology

**Unchanged.** This feature adds no node and no edge — the refund branch's topology is
identical to `specs/007-refund-policy-agent`; only `refund_agent`'s function body changes.

```text
router_agent ─┬─ "order_support" → call_model (unchanged by this feature)
              ├─ "unclear"       → clarify_intent ─┐
              └─ "refund" ───────────────────────┬─┘
                                                 ▼
                                        refund_agent ⇄ refund_tools
                                              │ tools_condition "__end__"
                                              ▼
                                      refund_await_customer ──┬─ not resolved → refund_agent
                                                               └─ resolved → refund_ticket_node → END
```

`refund_agent` now runs a condensation guard clause before generating its reply (see
`contracts/refund-agent.md`), and builds the system prompt/sentiment/summary context fresh each
call instead of seeding it once. `refund_await_customer` is unchanged.

## Phase 0: Research

**Status**: Complete — [research.md](./research.md).

Nine decisions recorded, deliberately structured to parallel `specs/008-order-history-summarization/research.md`'s
nine decisions one-for-one. The ones that most shape the implementation: no persistence change
needed since the refund agent already keeps `messages` (1); moving the system prompt and
sentiment reading out of `messages` into ephemeral context, because unlike the order agent they
were previously baked in and would otherwise be swept into the condensation cutoff (2);
condensation as a cheap, idempotent guard clause inside `refund_agent` rather than a separate
graph node (3); turn boundaries derived structurally with no new bookkeeping field (4); and no
shared helper module between the two agents' condensation guards, since only one concrete
caller would use it today (8).

## Phase 1: Design & Contracts

**Status**: Complete.

- [data-model.md](./data-model.md) — the one new `SupportState` field, the structural
  definition of a "turn," the token threshold, and the condensation state transition.
- [contracts/refund-agent.md](./contracts/refund-agent.md) — the revised node contract
  (`refund_agent`'s new `_build_context_messages` helper and condensation guard,
  `refund_await_customer`), explicitly superseding `specs/007-refund-policy-agent`'s
  `_seed_messages` contract. Graph topology and routing are unchanged.
- [contracts/support-state.md](./contracts/support-state.md) — extends
  `specs/002-order-support-agent`'s and `specs/008`'s `SupportState` contract with the new field
  and the changed meaning of `messages` for the refund loop.
- [quickstart.md](./quickstart.md) — automated validation as the primary path (the 20,000-token
  threshold is impractical to reach by hand), plus a manual scenario using a monkeypatched,
  lowered threshold to observe a real condensation pass.

## Requirements coverage

| Requirements | Satisfied by |
|---|---|
| FR-001 (retain history across turns) | Already true (`specs/007`); unchanged by this feature (research.md Decision 1) |
| FR-002, FR-003 (track size, condense over threshold) | The guard's `get_num_tokens_from_messages` check against `REFUND_HISTORY_TOKEN_THRESHOLD`, at the top of `refund_agent` |
| FR-004 (preserve order/facts/decision, per order distinctly) | The condensation prompt given to the model by the guard, exercised by the quickstart's manual scenario and unit tests asserting the summary field is populated and multi-order facts stay distinct |
| FR-005 (keep last 3 turns intact) | Structural turn-boundary detection (data-model.md); `RemoveMessage` only targets `older_messages` |
| FR-006 (re-condense, don't append) | The guard always calls the model with the *previous* summary + newly-aged messages and replaces the field wholesale (research.md Decision 6) |
| FR-007 (skip with ≤3 turns) | The turn-count check at the top of the guard |
| FR-008 (scoped to refund agent only) | The guard and `refund_conversation_summary` are only read/written inside `refund_agent.py`; order-support/router nodes untouched |
| FR-009 (most recent fact wins) | Falls out of FR-004/FR-006: the condensation prompt always sees the full ordered transcript of `older_messages`, so a later restatement naturally supersedes an earlier one in the produced summary |
| FR-010 (silent condensation failure) | The narrow `try/except` around only the guard's own model call (research.md Decision 7) |
| FR-011 (condensation never alters policy outcome) | `order_lookup`/`refund_request`/`complaint_ids`/`refund_resolved` are written directly by tool calls, never reconstructed from `messages`/summary (contracts/refund-agent.md guarantee #5) |

## Risks and mitigations

- **The system prompt or sentiment reading silently disappears from context.** This is the
  refund-agent-specific analogue of `specs/008`'s "cart summary stops refreshing" risk: naively
  adding a condensation cutoff on top of the existing `_seed_messages` pattern would sweep the
  system prompt (and sentiment message) into `older_messages` on the first condensation pass and
  never restore it. Mitigated by rebuilding context fresh on every `refund_agent` call via
  `_build_context_messages` (research.md Decision 2); unit tests explicitly guard this.
- **Redundant re-checks within a turn.** Same accepted cost as `specs/008`'s equivalent risk —
  cheap, local, idempotent, and not worth extra bookkeeping per Principle III (research.md
  Decision 3).
- **The condensation model call's failure mode gets confused with `refund_agent`'s own
  reply-generating call.** Mitigated by scoping the `try/except` to only the guard's own
  `llm.invoke(...)`, a few lines apart from the reply-generating call in the same function;
  nothing else in the loop changes its failure behavior (contracts/refund-agent.md guarantee
  #8).
- **Existing tests hard-code the old seed-into-`messages` contract.** All three affected tests
  are named explicitly in Project Structure and the Constitution Check above so
  `/speckit-tasks` cannot miss them; leaving any unchanged would make the suite red against the
  new, intended behavior.
- **A refund conversation touching two orders gets its facts merged.** Mitigated by explicit
  condensation instructions directing the model to keep each order's facts and outcome distinct
  (research.md Decision 6, FR-004), with a dedicated unit test covering the two-order case.
- **Condensation accidentally influences a policy decision.** Mitigated structurally, not just
  by convention: `refund_policy.evaluate()` and the tools that call it read `order_lookup` and
  explicit tool arguments, never `messages` or `refund_conversation_summary`
  (`specs/007-refund-policy-agent/data-model.md`), so there is no code path by which condensed
  history could change a policy outcome (FR-011).
- **Non-OpenAI models via `OPENROUTER_MODEL` get an approximate token count.** Same documented,
  accepted limitation as `specs/008` (research.md Decision 5) — no exact tokenizer is available
  for an arbitrary OpenRouter-routed model without a new dependency.
