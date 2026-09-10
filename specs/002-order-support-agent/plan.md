# Implementation Plan: Order/Support Agent with Menu Tools

**Branch**: `002-order-support-agent` | **Date**: 2026-09-10 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-order-support-agent/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Build the real order-support conversation (replacing the current single-node pass-through placeholder) as a native LLM tool-calling loop — three LangGraph nodes (`call_model`, `order_tools` as a `langgraph.prebuilt.ToolNode`, `await_customer`) operating directly on shared state, rather than a structured-output classifier with fixed reply templates. The model is bound to four tools (`get_menu`, `get_menu_item`, `add_items_to_cart`, `mark_order_confirmed`); the two cart-mutating tools read/write `SupportState` via `langgraph.prebuilt.InjectedState`/`langgraph.types.Command`, so tool execution and state mutation stay code-guaranteed and unit-testable even though the customer-facing reply text is now model-composed (enabling genuine recommendation-style answers and multi-item requests in one message, e.g. "add two spring rolls and a kung pao chicken" — handled by one batched `add_items_to_cart(names=[...])` call). Item-name resolution is flexible/fuzzy (stdlib `difflib`), shared by the lookup and cart-add tools; a tie between equally-close matches is surfaced to the customer as a disambiguation question, composed by the model from the tool's tie result rather than a fixed template. The per-turn message list (`SupportState.messages`) is rebuilt fresh every turn — never accumulated across turns — bounding LLM context growth to one turn's tool-calling exchange regardless of conversation length. The outer conversation loops via `interrupt()`/resume for each new customer message until `mark_order_confirmed` sets `order_confirmed` on a non-empty cart, at which point it hands off — via a dummy `confirm_node` — to a dummy `ticket_gen_node` that writes a minimal placeholder `order_ticket` onto shared state. Existing agent-node modules (`router_agent`, `clarify_intent`, the `refund_agent` placeholder) are moved into a new `nodes/` subpackage with zero behavior change; new `tools/` and `menu/` subpackages hold the tool functions and the seeded 5-item `menu.json` respectively. A pre-existing CLI bug (always printing a hardcoded question on any interrupt, rather than the actual interrupt payload) is fixed as part of this work since the new multi-turn flow depends on it. Correctness is verified with `pytest`: pure-function/tool unit tests (LLM boundary faked or bypassed entirely by calling tool functions directly), and `agentevals` graph-trajectory-match integration tests spanning multiple `Command(resume=...)` turns, asserting on tool execution and resulting state — not on model-composed reply wording, which is validated manually via `quickstart.md` (an LLM-as-judge evaluation layer was considered and explicitly deferred out of this feature's scope).

## Technical Context

**Language/Version**: Python 3.14 (per `pyproject.toml` `requires-python`, unchanged from 001).

**Primary Dependencies**: `langgraph` (conditional edges, `interrupt()`/`Command(resume=...)` for the outer per-turn loop reusing the `clarify_intent` pattern; `langgraph.prebuilt.ToolNode`/`InjectedState`/`tools_condition` and `langgraph.types.Command` for the inner tool-calling loop — all verified present in the installed `langgraph==1.2.11`, research.md §2); `langchain-openai` (`ChatOpenAI` against OpenRouter, `.bind_tools([...])`); `langchain` (core message types: `SystemMessage`/`HumanMessage`/`AIMessage`/`ToolMessage`); `agentevals` (multi-turn trajectory tests); `pytest`. No new third-party dependency: fuzzy name matching uses stdlib `difflib`, menu loading uses stdlib `importlib.resources`/`json` (research.md §3, §6).

**Storage**: N/A for conversation data — `messages`, `menu_items`, `order_confirmed`, and `order_ticket` live only in in-memory `SupportState` for the duration of a single graph run/thread, same `MemorySaver` checkpointer model as 001 (Assumptions: cart scoped to one conversation, not persisted; `messages` additionally resets every turn — research.md §4). `menu/menu.json` is static, read-only, bundled package data (not a runtime storage system) — loaded once and cached in-process (research.md §6).

**Testing**: `pytest`; unit tests for `tools/menu_tools.py` and `tools/cart_tools.py` — pure-function resolution tests plus direct calls to the `InjectedState`/`Command`-based tools with a hand-constructed state dict (no LLM, no graph); unit tests for the two dummy nodes; `agentevals.graph_trajectory.strict.graph_trajectory_strict_match` (trajectory extracted via `agentevals.graph_trajectory.utils.extract_langgraph_trajectory_from_thread`) driving multi-turn integration tests over `build_graph()`, with the LLM boundary faked to return canned `AIMessage`s carrying specific `tool_calls` and real `ToolNode` execution against a real (test) sample menu, each turn resumed via `Command(resume=<message>)` — assertions target tool execution and resulting state, never model-composed reply wording (research.md §9; an LLM-as-judge layer for reply quality was considered and deferred out of scope).

**Target Platform**: Server-side Python library invoked via the existing `customer-support-fde` CLI entry point (Constitution Principle II) — unchanged from 001, except the CLI's interrupt-echo bug fix (research.md §8).

**Project Type**: Single project — same `src/customer_support_fde/` package, now internally organized into `nodes/`, `tools/`, and `menu/` subpackages (FR-010, FR-011, FR-012; research.md §1).

**Performance Goals**: Not a stated Success Criterion for this feature (SC-001–SC-005 are about correctness/completeness, not latency); each conversational turn is dominated by one LLM call, consistent with 001's per-request latency expectations — no new performance target introduced.

**Constraints**: Item-name resolution MUST accept partial names/typos/close variations (FR-001) and MUST ask the customer to disambiguate rather than guess on a tie (FR-005a) or report not-found when nothing is close enough (FR-005); the cart MUST hold one entry per distinct item with an incrementing quantity, never duplicate entries (FR-004), including when several items arrive in one batched `add_items_to_cart` call; the "anything else?" question MUST be asked after every successful add (FR-006) — the tool contract guarantees the model is *given* the information needed to ask it (a successful-add `ToolMessage`), but the exact wording is now model-composed, not a fixed template (see research.md §9's Note on this tradeoff — reply-wording compliance is validated manually via `quickstart.md`, not asserted by automated tests); the flow MUST NOT reach the confirmation/ticket steps before an explicit "done" confirmation over a non-empty cart, and MUST NOT reach them at all if the cart stays empty — this part stays code-guaranteed via `mark_order_confirmed`'s `Command` (FR-007, Edge Cases); `confirm_node` and `ticket_gen_node` MUST remain placeholders (FR-008); agent-node, tool, and menu code MUST live in separate dedicated areas (FR-010–FR-012); reorganizing existing modules MUST NOT change `router_agent`/`clarify_intent`/`refund_agent` external behavior (Assumptions).

**Scale/Scope**: Three graph nodes for the order-support loop (`call_model`, `order_tools`, `await_customer`), two new dummy nodes (`confirm_node`, `ticket_gen_node`), two new tool modules (`menu_tools.py`, `cart_tools.py`), one static menu file (≥5 items, FR-009); one or more LLM calls per customer message (the inner `call_model ⇄ order_tools` loop may call the model more than once within a single turn if it chooses to call tools across multiple rounds, e.g. a lookup followed by an add); three existing node modules relocated (not rewritten) into `nodes/`.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Test-First (NON-NEGOTIABLE)**: PASS (planned), with a scoped caveat — Phase 2 tasks will write failing unit tests for `menu_tools`, `cart_tools` (including the `InjectedState`/`Command`-based tools, called directly with a hand-built state dict), the order-support loop's tool-execution and state-mutation behavior, `confirm_node`/`ticket_gen_node`, and failing multi-turn trajectory tests, before implementation exists (red-green-refactor, same discipline as 001). The caveat: FR-006's exact reply *wording* ("MUST ask anything else") is not itself asserted by an automated test in this design, since the reply is model-composed rather than template-generated — the tool contract guarantees the *information* needed to comply is available to the model (research.md §9), but wording compliance is validated manually via `quickstart.md`, not proven by a failing-then-passing test. This is a deliberate, called-out tradeoff from design review, not an oversight — flagged here for visibility rather than treated as silently satisfying the principle.
- **II. Library-First & CLI Interface**: PASS (planned) — all new logic lives as plain importable modules under `src/customer_support_fde/{nodes,tools,menu}/`, with no framework-specific coupling; the CLI continues to be extended (not replaced) — the interrupt-echo fix keeps it a correct text in/out interface per Principle II, using only stdlib for the fix.
- **III. Simplicity (YAGNI)**: PASS (planned) — uses `langgraph.prebuilt.ToolNode`/`InjectedState`/`tools_condition` directly against `SupportState` rather than hand-rolling a tool-execution loop or reaching for the fully-prebuilt `create_react_agent` (which would require reconciling a separate agent-internal state schema with `SupportState` across a subgraph boundary — research.md §2); `add_items_to_cart` batches multiple items in one call instead of requiring a state-merge reducer for concurrent same-turn tool calls (research.md §5); reuses stdlib `difflib` instead of a new fuzzy-matching dependency (research.md §3); `confirm_node`/`ticket_gen_node` stay deliberately minimal placeholders per FR-008; the previously-considered LLM-as-judge evaluation layer was dropped as unnecessary complexity for this phase (research.md §9).
- **IV. Observability & Versioning**: PASS (planned) — the order-support loop's LLM calls are traced via the same LangSmith env-var mechanism already relied on for `router_agent`; no custom logging layer added. No breaking changes to `SupportState`'s existing three fields (only additive fields — see `contracts/support-state.md` Change policy); package stays pre-1.0 pending a minor bump when this feature merges.

No violations requiring justification — Complexity Tracking table omitted.

**Post-Phase-1 re-check**: Confirmed against the finished design (`data-model.md`, `contracts/*.md`). `SupportState` gains four additive fields (`messages`, `menu_items`, `order_confirmed`, `order_ticket`) without touching the three fields 001's contract governs — consistent with that contract's Change policy. The reorg into `nodes/`/`tools/`/`menu/` is a pure move for the three existing modules (verified against `graph.py`/`cli.py`/existing test import paths in Project Structure below) — no behavior change, satisfying the Assumptions guarantee. One additional, previously-latent bug fix (CLI interrupt-echo) was identified as necessary during design (research.md §8); it's a minimal, scoped fix, not new complexity. The `ToolNode`/`InjectedState`/`Command`/`tools_condition` API surface was verified against the installed `langgraph==1.2.11` directly (not assumed from general knowledge) before being committed to this design. All four gates still PASS, with Principle I's scoped caveat noted above carried forward rather than hidden.

## Project Structure

### Documentation (this feature)

```text
specs/002-order-support-agent/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   ├── support-state.md
│   ├── menu-tools.md
│   ├── cart-tools.md
│   ├── order-support-agent.md
│   └── confirm-and-ticket-nodes.md
└── tasks.md              # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/customer_support_fde/
├── __init__.py            # main() CLI entry point (existing, unchanged)
├── cli.py                 # existing; interrupt-echo bug fixed (research.md §8) to print the real payload instead of the hardcoded QUESTION constant
├── state.py                # SupportState TypedDict; gains messages, menu_items, order_confirmed, order_ticket (contracts/support-state.md)
├── graph.py                 # build_graph(): wires call_model/order_tools/await_customer (tools_condition + custom routing), confirm_node, ticket_gen_node; router_agent/clarify_intent imports updated to nodes/
├── nodes/                   # dedicated area for agent nodes (FR-010)
│   ├── __init__.py
│   ├── router_agent.py       # moved from package root, unchanged behavior
│   ├── clarify_intent.py     # moved from package root, unchanged behavior
│   ├── refund_agent.py       # moved out of the old downstream_agents.py, unchanged placeholder behavior
│   ├── order_support_agent.py # new: call_model/order_tools(ToolNode)/await_customer tool-calling loop (contracts/order-support-agent.md)
│   ├── confirm_node.py        # new: dummy pass-through hand-off node (contracts/confirm-and-ticket-nodes.md)
│   └── ticket_gen_node.py     # new: dummy placeholder ticket-writer node (contracts/confirm-and-ticket-nodes.md)
├── tools/                    # dedicated area for tools (FR-011)
│   ├── __init__.py
│   ├── menu_tools.py          # resolve_menu_item() (pure), get_menu()/get_menu_item() (LLM-callable tools) (contracts/menu-tools.md)
│   └── cart_tools.py          # add_items_to_cart(), mark_order_confirmed() — InjectedState/Command-based tools (contracts/cart-tools.md)
└── menu/                      # dedicated, self-contained menu data area (FR-012)
    ├── __init__.py
    └── menu.json                # ≥5 seeded items: name, price, ingredients (FR-009)

tests/
├── unit/
│   ├── test_router_agent.py           # existing; import path updated to nodes.router_agent
│   ├── test_clarify_intent.py         # existing; import path updated to nodes.clarify_intent
│   ├── test_menu_tools.py             # new: found/tie/not-found resolution over a sample menu (resolve_menu_item, no LLM)
│   ├── test_cart_tools.py             # new: add_items_to_cart/mark_order_confirmed called directly with a hand-built state dict — batched add/increment/tie/not-found, Command.update assertions
│   ├── test_order_support_agent.py    # new: call_model/order_tools loop's tool execution + resulting state mutation, LLM boundary faked to return canned tool_calls
│   └── test_confirm_and_ticket_nodes.py # new: pass-through + placeholder order_ticket shape
└── integration/
    ├── test_router_trajectory.py       # existing; import path updated to nodes.router_agent
    └── test_order_support_trajectory.py # new: multi-turn agentevals trajectory tests over build_graph(), asserting tool execution/state — not reply wording
```

**Structure Decision**: Single project (Option 1), unchanged from 001. This feature reorganizes the existing flat `src/customer_support_fde/` package into `nodes/`, `tools/`, and `menu/` subpackages (FR-010–FR-012), relocating three existing modules without changing their behavior, and adds six new modules (three nodes, two tools, one data file) plus a `menu.json` fixture. Test layout stays `tests/unit/` and `tests/integration/`, matching Constitution Principle II and this repo's existing convention; two existing test files need only an import-path update for the move, not a rewrite.

## Complexity Tracking

*No Constitution Check violations — table intentionally omitted.*
