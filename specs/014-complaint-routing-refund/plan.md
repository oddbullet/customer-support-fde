# Implementation Plan: Complaint Routing to Refund Agent

**Branch**: `014-complaint-routing-refund` | **Date**: 2026-09-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/014-complaint-routing-refund/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Sharpen the existing `router_agent` node (`src/customer_support_fde/nodes/router_agent.py`) so that a customer message describing dissatisfaction with a past order — cold food, a missing item, a late delivery, a wrong dish — is classified to the `refund` destination even when it never uses refund/money-back language, and so a message that combines such a complaint with an explicit refund ask resolves directly to `refund` rather than tripping the existing `unclear`/mixed-signal path. This is a prompt-wording refinement of the single structured-output classification call already in place (`RouterDecision.destination: Literal["order_support", "refund", "unclear"]`); no new node, edge, state field, or dependency is introduced. Because the classification boundary (the LLM call) is mocked in every existing and planned unit/trajectory test, the correctness of the new instruction is locked in with tests that assert on the concrete wording of `SYSTEM_PROMPT` itself (the only way to get a genuine red state before the prompt is edited and green after, given this project's established mocked-LLM-boundary testing style — see `research.md` §1), supplemented by state-plumbing tests mirroring the spec's acceptance scenarios for documentation and regression coverage.

## Technical Context

**Language/Version**: Python 3.14 (per `pyproject.toml` `requires-python` and `.python-version`)

**Primary Dependencies**: None added. Reuses `langchain-openai` (`ChatOpenAI` against OpenRouter, structured output via the existing `RouterDecision` Pydantic model) and `langgraph` (existing `router_agent` node and conditional edges), unchanged from `001-router-agent`.

**Storage**: N/A — no state shape change; `SupportState`'s `destination`/`sentiment` fields and the router's stateless, single-invocation behavior are unchanged.

**Testing**: `pytest`. Unit tests in `tests/unit/test_router_agent.py` gain (a) assertions on `router_agent.SYSTEM_PROMPT` content that fail before the prompt wording changes and pass after (the red/green mechanism for this feature, since the LLM boundary is mocked everywhere else — see Summary), and (b) additional mocked-`RouterDecision` plumbing cases mirroring the spec's acceptance scenarios (complaint-only, complaint+explicit-refund-ask). `tests/integration/test_router_trajectory.py`'s existing `LABELED_SAMPLES` list gains complaint-only entries for documentation/regression parity with the spec's edge cases, following the same pattern as `001-router-agent`'s labeled set.

**Target Platform**: Server-side Python library invoked via the existing `customer-support-fde` CLI entry point — unchanged, no OS-specific behavior.

**Project Type**: Single project — modifies one existing module (`src/customer_support_fde/nodes/router_agent.py`) and two existing test modules; no new modules.

**Performance Goals**: No change — still one LLM call per request, under 3 seconds under normal conditions (inherited from `001-router-agent` SC-005; unaffected by a prompt-wording change).

**Constraints**: The change MUST stay within the existing three-value `destination` classification (`order_support`, `refund`, `unclear`) and the existing sentiment rules (FR-004/FR-005 of `001-router-agent`) — this feature adds classification guidance, not new destinations, fields, or edges. A complaint with no relation to a past order MUST NOT be pulled into `refund` (FR-006). A complaint mixed with an unrelated order/support question MUST still resolve to `unclear` (FR-005), preserving `001-router-agent`'s clarifying-question behavior.

**Scale/Scope**: One file changed in `src/` (`router_agent.py`, `SYSTEM_PROMPT` text only — no function signature or control-flow change), two test files extended. No `research.md`, `data-model.md`, or `contracts/` changes are needed beyond what `001-router-agent` already established, since no new entity, interface, or technical unknown is introduced (see Phase 0 below for why these are intentionally thin).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Test-First (NON-NEGOTIABLE)**: PASS (planned) — new `SYSTEM_PROMPT`-content assertions in `test_router_agent.py` will be written first and observed to fail against the current prompt text before `router_agent.py` is edited, then pass once the prompt is updated (genuine red-green, since this is the only boundary in this codebase's router tests that isn't mocked away). Each new/changed test case gets a one-line category comment per the constitution's tagging convention.
- **II. Library-First & CLI Interface**: PASS (unchanged) — no new module or CLI surface; the existing `router_agent` function and CLI entry point are untouched in shape.
- **III. Simplicity (YAGNI)**: PASS (planned) — this is a wording-only change to an existing prompt string. No new node, no new state field, no new dependency, no confidence-scoring or heuristic layer added; the existing `unclear` fallback and clarifying-question flow are reused as-is for the cases spec.md explicitly keeps out of scope (FR-005, FR-006).
- **IV. Observability & Versioning**: PASS (planned) — no change to tracing (still routed through the existing Arize Phoenix instrumentation covering `router_agent`). This is a behavioral clarification/fix to already-shipped routing logic, not a new feature surface or breaking change, so it MUST be released as a PATCH version bump per the constitution's semantic versioning rule.

No violations requiring justification — Complexity Tracking table omitted.

**Post-Phase-1 re-check**: Confirmed. Phase 1 produced no new entities, contracts, or state shape changes (see Project Structure below), so nothing here changes from the pre-Phase-0 assessment. All four gates still PASS.

## Project Structure

### Documentation (this feature)

```text
specs/014-complaint-routing-refund/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

No `data-model.md` or `contracts/` are generated for this feature: it introduces no new entity, state field, or external interface beyond what `specs/001-router-agent/data-model.md` and `specs/001-router-agent/contracts/` already document (the `RouterDecision`/`SupportState` shapes are reused unchanged) — see Phase 1 below.

### Source Code (repository root)

```text
src/customer_support_fde/
└── nodes/
    └── router_agent.py        # SYSTEM_PROMPT updated: explicit complaint-recognition guidance
                                # (no signature/control-flow change to router_agent() or RouterDecision)

tests/
├── unit/
│   └── test_router_agent.py           # + SYSTEM_PROMPT content assertions (red/green driver)
│                                       # + mocked-RouterDecision cases for complaint-only and
│                                       #   complaint+explicit-refund-ask acceptance scenarios
└── integration/
    └── test_router_trajectory.py      # + complaint-only entries in LABELED_SAMPLES
```

**Structure Decision**: Single project (Option 1), unchanged from `001-router-agent`. This feature makes no structural change — it edits one existing module's prompt string and extends two existing test modules in place. No new top-level directory, package, or test module is warranted for a prompt-wording refinement (Principle III).

## Complexity Tracking

*No Constitution Check violations — table intentionally omitted.*
