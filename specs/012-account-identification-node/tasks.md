---

description: "Task list for Customer Account Identification Node"
---

# Tasks: Customer Account Identification Node

**Input**: Design documents from `/specs/012-account-identification-node/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: Test tasks are included and are **NON-NEGOTIABLE** — Constitution v1.2.1 Principle I
requires tests to be written, reviewed, and observed failing before the implementation they
cover. Every test case MUST carry a one-line comment directly above its definition (above the
outermost `@pytest.mark.parametrize`, if present) stating what it verifies and tagging its
category: `(base)`, `(edge)`, `(error)`, or `(regression)`.

**Organization**: Grouped by user story so each can be implemented, tested, and demoed
independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Exact file paths are included in every task

## Path Conventions

Single Python package at repository root: `src/customer_support_fde/`, `tests/unit/`,
`tests/integration/`.

---

## Phase 1: Setup

**Not needed for this feature.** It extends an existing project with no new dependency, no new
CLI surface, and no new shared test fixture — the existing `tests/unit/conftest.py` `refund_db`
fixture already initializes every table in `_SCHEMA` (including the new `accounts` table once
Phase 2 adds it), so no new fixture is required either. Proceed straight to Phase 2.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The storage layer, conversation state, and a runnable (if not yet fully
option-complete) account-identification step wired into the graph. No user story can be
implemented until these exist — and because this step is inserted into the *existing*
order/support path, this phase must also repair the trajectory tests that path already has.

**⚠️ CRITICAL**: No user story work begins until this phase completes.

### Storage (Track A)

- [X] T001 [P] Write failing tests in `tests/unit/test_db.py`: (a) regression coverage proving the id-helper refactor doesn't change existing order-id behavior — `db._new_order_id()` still returns 8-char strings drawn only from `ID_ALPHABET`, `db.format_order_id`/`db.normalize_order_id` still round-trip and fold confusables exactly as today, and the existing collision-retry test stays valid; (b) `db._new_account_number()` returns an 8-char `ID_ALPHABET` string; `db.format_account_number("K7QP3M9X") == "K7QP-3M9X"` and `db.normalize_account_number("K7QP-3M9X") == "K7QP3M9X"` round-trip; `db.normalize_account_number` folds lowercase, hyphens, surrounding whitespace, and O/I/L confusables the same way `normalize_order_id` does; (c) extend `test_init_database_creates_tables_and_seeds_menu`'s table-set assertion to include `"accounts"`; (d) `db.get_account` returns `None` for an unknown number; `db.create_account()` then `db.get_account(...)` round-trips with `preferences` `None` and a populated `created_at`; `db.get_account` resolves a lowercase/dashed/confusable number form (mirror `test_lookup_order_resolves_forgiving_id_forms`); `db.create_account` retries past a forced account-number collision (mirror `test_record_order_retries_past_a_forced_id_collision`, monkeypatching `db._new_account_number`)
- [X] T002 Implement in `src/customer_support_fde/db.py` (research.md Decision 2): extract private helpers `_new_id()`, `_normalize_id(raw)`, `_format_id(id_)` holding the `ID_ALPHABET`/`ID_LENGTH`/`_CONFUSION_TRANSLATION` logic; rewire `_new_order_id()`, `normalize_order_id()`, `format_order_id()` to call them (names/signatures/behavior unchanged); add `_new_account_number()`, `normalize_account_number(raw)`, `format_account_number(account_number)` as thin wrappers over the same helpers. Append the `accounts` table DDL to `_SCHEMA`, copied verbatim from [contracts/sqlite-schema.sql](./contracts/sqlite-schema.sql). Implement `get_account(account_number, path=None)` and `create_account(path=None)` per [data-model.md](./data-model.md)'s retrieval/write surface, following the existing `_resolve_path`/`_connect`/`finally`/`OrderStoreError` convention used by `get_order`/`record_order`

### State and CLI (Track B)

- [X] T003 [P] Add `account_number: str | None` and `account_preferences: str | None` to `SupportState` in `src/customer_support_fde/state.py`
- [X] T004 Write failing test in `tests/unit/test_cli.py` asserting the initial state dict built in `run()` contains `"account_number": None` and `"account_preferences": None` (extend `test_run_seeds_initial_state_with_refund_keys` or add a sibling assertion) — depends on T003
- [X] T005 Seed `"account_number": None` and `"account_preferences": None` in the initial state dict in `run()` in `src/customer_support_fde/cli.py` — depends on T004

### Account-identification step and graph wiring (Track C)

- [X] T006 [P] Write failing tests in `tests/unit/test_account_identification_node.py` (new file) for the primary menu's generic mechanics only — no option-specific outcome yet: an unrecognized reply (e.g. `"banana"`) re-issues the identical prompt via `interrupt()` and does not advance (mirror `test_unrecognized_answer_re_asks_the_same_question` in `test_clarify_intent.py`); a reply of `"2"` returns `{"account_number": None, "account_preferences": None}` with no database write
- [X] T007 Create `src/customer_support_fde/nodes/account_identification_node.py`: a `PRIMARY_MENU` prompt constant and `account_identification_node(state)` that loops `str(interrupt(PRIMARY_MENU)).strip()` until the reply is `"1"`, `"2"`, or `"3"` (FR-002, FR-011, FR-012, mirroring `clarify_intent.py`'s loop shape — research.md Decision 1); `"2"` returns `{"account_number": None, "account_preferences": None}`; `"1"` and `"3"` call `_use_existing_account()` / `_sign_up()`, defined for now as `raise NotImplementedError` placeholders (implemented in T012 and T016) — depends on T006
- [X] T008 Register `account_identification_node` in `src/customer_support_fde/graph.py`: add the node; change `router_agent`'s and `clarify_intent`'s `"order_support"` conditional-edge targets from `"call_model"` to `"account_identification_node"`; add a new unconditional edge `account_identification_node → call_model` (research.md Decision 4). The refund-path and unclear-routing edges are otherwise unchanged — depends on T007
- [X] T009 Fix the trajectory regression this wiring causes (run `uv run pytest tests/integration -v` first to see it fail): every real-graph test that reaches `call_model` via the order/support path now first pauses at `account_identification_node`'s menu. In `tests/integration/test_order_support_trajectory.py`, prepend a `Command(resume="2")` turn (continue without an account) before each test's existing flow continues, and update `test_full_conversation_confirms_and_produces_order_ticket`'s `reference_outputs["steps"]` to insert a leading `["__start__", "router_agent", "account_identification_node", "__interrupt__"]` segment, with the former first segment now starting `"account_identification_node", "call_model", ...` instead of `"__start__", "router_agent", "call_model", ...`. In `tests/integration/test_router_trajectory.py`, apply the same fix to `test_order_support_style_request_reaches_call_model_and_pauses` and to the `"1"`/`"2"` (order_support) cases of `test_ambiguous_or_mixed_signal_request_resolved_via_clarify_intent` — its `"3"`/refund case, and `test_refund_style_request_routes_through_refund_agent`, are untouched, since the refund path never reaches this node. `test_labeled_sample_set_routes_to_the_expected_destination_at_least_90_percent` needs **no** change — it only reads `state["destination"]`, which router_agent/clarify_intent already set before the graph ever reaches the new node. `tests/integration/test_refund_trajectory.py` needs **no** change for the same reason — depends on T008

**Checkpoint**: Schema, state, CLI seeding, and a runnable account-identification step exist and
are wired into the graph. The full pre-existing test suite is green again. No user story's
option-specific behavior (found/not-found/recovery, sign-up) is implemented yet — `"1"` and
`"3"` still raise `NotImplementedError`.

---

## Phase 3: User Story 1 - Returning customer uses their existing account (Priority: P1) 🎯 MVP

**Goal**: A customer who enters a known account number reaches the order/support agent with
that account's stored preferences available to it.

**Independent Test**: Seed an account with known preferences text, start a conversation, reply
`"1"` then that account number at the menu, and confirm the mocked order-agent LLM's context
includes a `SystemMessage` carrying that text.

### Tests for User Story 1 ⚠️

> Write these FIRST and observe them FAIL before implementing.

- [X] T010 [P] [US1] Write failing tests in `tests/unit/test_account_identification_node.py` for the "use an existing account" path: reply `"1"` then a number `db.get_account` resolves (monkeypatched) sets `account_number`/`account_preferences` from that account's row (base); reply `"1"` then a number `db.get_account` returns `None` for presents a recovery menu — a second, distinct `interrupt()` prompt — instead of any of the three outcomes (edge, FR-005); the recovery menu re-prompts on an unrecognized reply the same way the primary menu does (edge, FR-012); the recovery menu's `"1"` (try again) loops back to the account-number prompt and succeeds on a subsequent valid number (edge)
- [X] T011 [P] [US1] Write failing tests in `tests/unit/test_order_support_agent.py` for `_build_context_messages`: when `state["account_preferences"]` is a non-`None` string, the returned context includes a `SystemMessage` whose content contains that text (base); when it is `None`, no such message is present (edge) — mirror the existing cart-summary/conversation-summary conditional-message tests' style

### Implementation for User Story 1

- [X] T012 [P] [US1] Implement `_use_existing_account()` in `src/customer_support_fde/nodes/account_identification_node.py`: `interrupt()`-prompt for the account number (FR-003), call `db.get_account(raw_reply)` (lookup normalizes internally — FR-009, no normalization needed in the node), on a match return `{"account_number": ..., "account_preferences": ...}` (FR-004); on no match, present a recovery menu — an `interrupt()`-loop until the reply is `"1"`, `"2"`, or `"3"` — where `"1"` loops back to the account-number prompt, `"2"` delegates to `_sign_up()`, and `"3"` returns the no-account result, per [contracts/account-identification-step.md](./contracts/account-identification-step.md) (FR-005) — depends on T010
- [X] T013 [P] [US1] Add the account-preferences `SystemMessage` block to `_build_context_messages` in `src/customer_support_fde/nodes/order_support_agent.py`, appended after the existing conversation-summary block, only when `state.get("account_preferences")` is not `None` (research.md Decision 6) — depends on T011
- [X] T014 [US1] Write a trajectory test in `tests/integration/test_order_support_trajectory.py`: seed an account via `db.create_account()` plus a direct SQL update setting its `preferences`, resume the account menu with `"1"` then that account's number, and assert the mocked order LLM's context (`bound.invoke.call_args_list[-1][0][0]`) includes a `SystemMessage` containing the seeded preferences text — mirror `test_preference_stated_early_survives_condensation`'s pattern — depends on T012, T013

**Checkpoint**: A returning customer with a correct account number reaches the order/support
agent with their preferences in context. The recovery menu's `"2"` (sign-up) branch still calls
`_sign_up()`, which raises `NotImplementedError` until US2 lands — see Story Dependencies below;
this does not block US1's own Independent Test, which never exercises that branch.

---

## Phase 4: User Story 2 - New customer signs up for an account (Priority: P2)

**Goal**: A customer who signs up receives a new, unique account number that a later,
separate conversation can look up successfully.

**Independent Test**: Reply `"3"` at the menu, capture the account number shown to the
customer, then in a fresh conversation reply `"1"` with that number and confirm it's found with
no preferences recorded yet.

### Tests for User Story 2 ⚠️

- [X] T015 [P] [US2] Write failing tests in `tests/unit/test_account_identification_node.py` for the "sign up" path: reply `"3"` calls `db.create_account()`, returns `{"account_number": <new number>, "account_preferences": None}`, and the customer is shown the account number (assert the `interrupt()` call used to deliver it contains `db.format_account_number(new_number)`) (base, FR-006); the same behavior is exercised via the recovery menu's `"2"` (sign up) option reached after a not-found account number (edge)

### Implementation for User Story 2

- [X] T016 [US2] Implement `_sign_up()` in `src/customer_support_fde/nodes/account_identification_node.py`: call `db.create_account()`, then `interrupt()` a message containing `db.format_account_number(...)` telling the customer to save it, and return `{"account_number": ..., "account_preferences": None}` regardless of what they reply back — per [contracts/account-identification-step.md](./contracts/account-identification-step.md) — depends on T015
- [X] T017 [P] [US2] Write a trajectory test in `tests/integration/test_order_support_trajectory.py`: resume the account menu with `"3"`, assert the interrupt message shown to the customer contains a formatted account number, then — in a **separate** `graph.invoke` thread — resume the account menu with `"1"` and that same (unformatted) number and assert `db.get_account(...)` finds it with `preferences: None` — depends on T016

**Checkpoint**: US1 and US2 both independently functional — sign-up produces a working,
later-retrievable account with no preferences yet, and US1's recovery-menu sign-up branch is
now fully functional too.

---

## Phase 5: User Story 3 - Customer continues without an account (Priority: P3)

**Goal**: A customer who doesn't want an account proceeds exactly as they do today, with no
account created and no behavior change to the order/support agent.

**Independent Test**: Reply `"2"` at the menu and confirm no `accounts` row is written and the
order/support agent's context is unaffected.

### Tests for User Story 3 ⚠️

- [X] T018 [P] [US3] Write failing test in `tests/unit/test_account_identification_node.py` strengthening the Foundational T006 assertion: reply `"2"`, monkeypatch `db.create_account` to raise `AssertionError` if called, and confirm it's never invoked (base, FR-007)
- [X] T019 [P] [US3] Write a trajectory test in `tests/integration/test_order_support_trajectory.py` resuming the account menu with `"2"` and asserting the conversation proceeds to `call_model` within the same invoke cycle with `account_number`/`account_preferences` both `None`, and that no account-preferences `SystemMessage` is present in the mocked order LLM's context (base, SC-004)

### Implementation for User Story 3

- [X] T020 [US3] No new production code is needed — the `"2"` branch was already implemented in Foundational (T007). Run `uv run pytest tests/unit/test_account_identification_node.py tests/integration/test_order_support_trajectory.py -v` and confirm T018/T019 pass against the existing implementation with zero further edits — depends on T018, T019

**Checkpoint**: All three user stories independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T021 [P] Update the Setup section of `CLAUDE.md` to note that `--init-db` must be re-run on an existing database to create the new `accounts` table
- [ ] T022 [P] Bump `version` in `pyproject.toml` from `0.6.0` to `0.7.0` (MINOR — backward-compatible feature addition, Constitution Principle IV)
- [X] T023 Run the full suite (`uv run pytest tests/unit tests/integration -v`) and confirm every pre-existing test plus all new tests pass, with no regressions in the refund or router-accuracy tests
- [X] T024 Walk every scenario in [quickstart.md](./quickstart.md) end to end: init-db, automated tests, manual CLI scenarios A–E, and the unregressed-order-flow check

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: None — skipped
- **Foundational (Phase 2)**: **BLOCKS all user stories**
- **US1 (Phase 3)**: Depends on Foundational
- **US2 (Phase 4)**: Depends on Foundational. US1's recovery menu calls `_sign_up()`, implemented here, so in practice US2 follows US1
- **US3 (Phase 5)**: Depends on Foundational only — its production behavior already exists from T007
- **Polish (Phase 6)**: Depends on all desired stories

### Story Dependencies

Like the refund feature before it, these three stories share one node function, so they are
**independently testable but not independently developable**:

- **US1 (P1)**: Independent for its own Independent Test (existing account found). Its
  recovery-menu sign-up branch depends on US2's `_sign_up()` (T016) to be fully functional
  end-to-end, but that branch is outside US1's own acceptance scenarios.
- **US2 (P2)**: Independent. Also completes US1's recovery-menu sign-up branch.
- **US3 (P3)**: Fully independent — its behavior shipped in Foundational; this phase only adds
  story-scoped tests confirming it.

### Within Each Story

- Tests are written and observed failing before the implementation they cover (Principle I)
- `db.py` accessors before the node functions that call them
- Node functions before the graph wiring and trajectory tests that exercise them
- Unit tests before trajectory tests

### Parallel Opportunities

- **Phase 2**: Three independent tracks: T001→T002 (storage), T003→T004→T005 (state/CLI),
  T006→T007→T008→T009 (node/graph). Only the first task of each track (T001, T003, T006) can
  truly start immediately in parallel; the rest of each track is sequential.
- **Phase 3**: T010 and T011 are different test files and can be written in parallel; their
  implementation tasks T012 and T013 are likewise independent of each other (different files,
  each depending only on its own preceding test task).
- **Phase 4**: T015 is the only test task; T017 is a separate file from T016.
- **Phase 5**: T018 and T019 are different files and independent of each other.
- **Phase 6**: T021 and T022 touch unrelated files.

Tasks in the same file are never marked `[P]` relative to each other: T010/T015/T018 all edit
`tests/unit/test_account_identification_node.py` and are sequential across phases, as is
`account_identification_node.py` across T007/T012/T016, and
`tests/integration/test_order_support_trajectory.py` across T009/T014/T017/T019.

---

## Parallel Example: Phase 2 Foundational

```bash
# Three independent tracks once the phase starts:
Track A: T001 → T002                     # storage (accounts table, id helpers)
Track B: T003 → T004 → T005              # state fields + CLI seeding
Track C: T006 → T007 → T008 → T009       # node skeleton, graph wiring, regression fix

# T009 (the trajectory regression fix) needs T008; it does not need Track A or B to be done,
# but in practice the full suite (Polish T023) needs all three tracks complete.
```

## Parallel Example: User Story 1

```bash
# Write both failing test files together:
Task: "Account lookup + recovery-menu tests in tests/unit/test_account_identification_node.py"  # T010
Task: "Preferences SystemMessage tests in tests/unit/test_order_support_agent.py"                # T011

# Then their independent implementations:
Task: "_use_existing_account() in nodes/account_identification_node.py"                          # T012
Task: "Preferences injection in nodes/order_support_agent.py"                                     # T013
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 2: Foundational — T001–T009 (**critical path; blocks everything**)
2. Phase 3: User Story 1 — T010–T014
3. **STOP and VALIDATE**: run quickstart.md scenario A and confirm the order agent's context
   carries a seeded account's preferences
4. Demo: a returning customer's stored preferences reach the order/support agent. Signing up and
   continuing without an account still work at the menu level (Foundational), just without their
   own dedicated coverage yet — and the recovery menu's sign-up option isn't functional until US2.

### Incremental Delivery

1. Foundational → storage, state, and a partially-functional account step exist; regression-free
2. \+ US1 → returning customers get personalized context (**MVP**)
3. \+ US2 → sign-up works end-to-end; US1's recovery menu becomes fully functional
4. \+ US3 → no-account path gets its own dedicated tests (behavior already shipped)
5. \+ Polish → docs, version bump, full regression + quickstart walkthrough

### Notes

- `[P]` means different files with no incomplete dependencies
- Every test case needs its one-line `(base)` / `(edge)` / `(error)` / `(regression)` comment —
  Principle I is non-negotiable and reviewers check for it
- Observe each test failing before writing the implementation; a test that passes on first run
  is not testing what you think
- Commit after each task or logical group
- T009 (the trajectory regression fix) is the task most likely to be underestimated — it touches
  tests across two integration files that this feature didn't otherwise need to change; budget
  real time for it
