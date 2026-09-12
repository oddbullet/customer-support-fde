---

description: "Task list for Test Case Audit & Coverage Rationalization"
---

# Tasks: Test Case Audit & Coverage Rationalization

**Input**: Design documents from `/specs/009-test-case-audit/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, quickstart.md (no `contracts/` — see research.md Decision 4)

**Tests**: This feature's deliverable *is* test-suite edits (removals and additions), so there
are no separate "write tests for this feature" tasks — the audit work below is itself the
test work, per FR-003/FR-004 and the clarification that the audit applies changes directly.

**Organization**: Tasks are grouped by user story (P1 → P3) per spec.md. All file paths are
relative to the repository root.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1 = redundancy removal (P1), US2 = base/edge coverage (P2), US3 = audit record (P3)

---

## Phase 1: Setup

**Purpose**: Establish the baseline the whole audit is measured against.

- [X] T001 Run `pytest --collect-only -q` and `pytest -q` once each against the current, unmodified suite. Create `specs/009-test-case-audit/audit-record.md`, seeded with the `AuditRecord` fields from `data-model.md` (`baseline_test_count`, `baseline_runtime`, empty `coverage_matrix`, `removed`, `added` sections, plus placeholders for `final_test_count`/`final_runtime`). Record the two baseline numbers now (183 tests expected per plan.md, plus the observed wall-clock time). **Done**: 183 tests collected; 13.24s full-suite runtime (see audit-record.md).
- [X] T002 [P] Confirm `pytest -q` reports zero failures/errors before any audit edits begin — a pre-existing failure would invalidate FR-008's guarantee that retained tests' pass/fail behavior isn't changed as a side effect of this audit. Note any pre-existing failures in `audit-record.md` under a "Pre-existing issues" note rather than folding them into redundancy/coverage decisions (per spec.md Edge Cases: "existing tests that fail or are already skipped/xfail"). **Done**: found a pre-existing Windows temp-directory permission issue (unrelated to test logic) causing 65 spurious errors with pytest's default basetemp; documented in audit-record.md and worked around with an explicit `--basetemp` for all subsequent runs — confirmed 183/183 pass cleanly.

**Checkpoint**: Baseline captured; audit-record.md exists and is ready for downstream phases to write into.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Build the shared inventory every user story phase reads from and writes into.

**⚠️ CRITICAL**: No per-file audit work (Phase 3+) may begin until this phase is complete.

- [X] T003 Using the `pytest --collect-only -q` output from T001, build the full `TestCase` inventory (per `data-model.md`): for every collected node id (each parametrized instance is its own entry), record its owning file, its target tool/node/module, its category tag if a one-line `(base)`/`(edge)`/`(error)`/`(regression)` comment is present above the test, and `has_category_comment` (true/false). Keep this inventory as a working section in `specs/009-test-case-audit/audit-record.md` (it can be condensed or removed from the final version in T031, but must exist now so every later task references the same ground truth). **Done**: built analytically per-file while reading each of the 14 test files against its source module (rather than as a single upfront table), which fed directly into the T005-T018 redundancy findings.
- [X] T004 Initialize the `coverage_matrix` in `audit-record.md` with one row for each of the 19 in-scope units from `research.md` Decision 2 — the 10 `@tool` functions (`add_items_to_cart`, `remove_items_from_cart`, `mark_order_confirmed`, `get_cart_total`, `get_menu`, `get_menu_item`, `lookup_order`, `process_refund_request`, `log_complaint`, `conclude_refund_conversation`) and the 9 node functions (`router_agent`, `clarify_intent`, `call_model`, `await_customer`, `cart_summary_node`, `ticket_gen_node`, `refund_agent`, `refund_await_customer`, `refund_ticket_node`). Set each row's `has_base_test`/`has_edge_test` from the T003 inventory (true only if a `kept` test with that category already targets it). **Done**: skeleton with all 19 rows initialized `TBD`, filled in incrementally through T029.

**Checkpoint**: Inventory and coverage-matrix skeleton exist; Phase 3+ can begin.

---

## Phase 3: User Story 1 - Eliminate redundant test cases without losing coverage (Priority: P1) 🎯 MVP

**Goal**: Remove test cases whose behavioral coverage is fully duplicated by another retained test, without losing any unique coverage.

**Independent Test**: Before/after inventory per module shows every removal is demonstrably duplicated by a retained test, and `pytest -q` still passes.

### Implementation for User Story 1

- [X] T005 [P] [US1] Review `tests/unit/test_cart_tools.py` against the T003 inventory. For any group of test cases exercising the same code path with the same assertions, remove all but one; for each removal, add an entry to `audit-record.md`'s `removed` list with the rationale and the retained test it points to — "A TestCase with status = removed MUST have a non-null superseded_by, and that referenced test MUST itself have status = kept" (data-model.md). Do not remove any test that is the sole coverage for a distinct behavior, error condition, boundary value, or regression guard (FR-005). **Done**: removed 2 of 21 (see audit-record.md); 19 remain, all pass.
- [X] T006 [P] [US1] Apply the same redundancy review to `tests/unit/test_menu_tools.py`, following the same removal/recording rule as T005. **Done**: removed 1 of 18 (see audit-record.md).
- [X] T007 [P] [US1] Apply the same redundancy review to `tests/unit/test_refund_tools.py`, following the same removal/recording rule as T005. **Done**: no redundancy found — all 19 existing tests exercise distinct branches (see audit-record.md analysis).
- [X] T008 [P] [US1] Apply the same redundancy review to `tests/unit/test_router_agent.py`, following the same removal/recording rule as T005. **Done**: trimmed 1 redundant parametrize case (see audit-record.md); 7 of 8 remain.
- [X] T009 [P] [US1] Apply the same redundancy review to `tests/unit/test_clarify_intent.py`, following the same removal/recording rule as T005. **Done**: no redundancy found — the `["1","2"]` parametrize pair each independently verifies set membership with no other test overlapping either value; all 4 cases distinct.
- [X] T010 [P] [US1] Apply the same redundancy review to `tests/unit/test_order_support_agent.py`, following the same removal/recording rule as T005. **Done**: no removals — the 9 tool-round-trip tests each exercise a distinct branch either in the shared call_model/ToolNode wiring or in the specific tool's own logic; none fully duplicate another. All 19 pass unchanged.
- [X] T011 [P] [US1] Apply the same redundancy review to `tests/unit/test_refund_agent.py`, following the same removal/recording rule as T005. **Done**: no redundancy found; all 4 original tests exercise distinct branches.
- [X] T012 [P] [US1] Apply the same redundancy review to `tests/unit/test_cart_summary_and_ticket_nodes.py`, following the same removal/recording rule as T005. **Done**: removed 1 of 18 — a cross-file duplicate with test_menu_tools.py (see audit-record.md); 17 remain.
- [X] T013 [P] [US1] Apply the same redundancy review to `tests/unit/test_db.py`, following the same removal/recording rule as T005 (this module is out of the FR-002 coverage guarantee, per the coverage-scope clarification, but its existing tests are still in scope for redundancy per FR-001/FR-004). **Done**: removed 2 of 39 (see audit-record.md); 37 remain, all pass.
- [X] T014 [P] [US1] Apply the same redundancy review to `tests/unit/test_refund_policy.py`, following the same removal/recording rule as T005 (out of FR-002 scope; in scope for redundancy). **Done**: removed 1 exact duplicate of 8 (see audit-record.md); 7 remain.
- [X] T015 [P] [US1] Apply the same redundancy review to `tests/unit/test_cli.py`, following the same removal/recording rule as T005 (out of FR-002 scope; in scope for redundancy). **Done**: no redundancy found; all 3 tests distinct.
- [X] T016 [P] [US1] Apply the same redundancy review to `tests/integration/test_order_support_trajectory.py`, following the same removal/recording rule as T005. **Done**: no redundancy found; all 8 scenarios distinct.
- [X] T017 [P] [US1] Apply the same redundancy review to `tests/integration/test_refund_trajectory.py`, following the same removal/recording rule as T005. **Done**: no redundancy found; all 5 scenarios distinct.
- [X] T018 [P] [US1] Apply the same redundancy review to `tests/integration/test_router_trajectory.py`, following the same removal/recording rule as T005. **Done**: trimmed a redundant parametrize dimension, removing 3 of 9 (see audit-record.md); 6 remain.
- [X] T019 [US1] Cross-file redundancy pass: using the T003 inventory, check for duplication *across* files (e.g., a unit test and a trajectory/integration test asserting the identical outcome for the identical input) that per-file reviews (T005-T018) would miss. Remove any confirmed cross-file duplicates using the same `superseded_by` rule as T005. Depends on T005-T018. **Done**: found and removed 1 cross-file duplicate while reviewing test_cart_summary_and_ticket_nodes.py (build_order_summary's rounding test vs. test_menu_tools.py's cart_total rounding test — recorded under that file's Removed entry). Targeted re-check of other likely overlaps (menu.json well-formedness vs. load_menu fidelity; get_cart_total tool vs. cart_total helper; unit-level tool tests vs. ToolNode-integration tests) found each pair tests a genuinely distinct concern — no further cross-file duplicates found.
- [X] T020 [US1] Run `pytest -q` and confirm the full suite passes with no reduction in the set of distinct behaviors verified (spec.md User Story 1, Acceptance Scenario 3). Depends on T019. **Done**: 175/175 pass (was 183 baseline; 8 net removed — see audit-record.md for the full itemized list with rationale).

**Checkpoint**: Redundant tests removed and recorded; suite still green. This is independently shippable value even if US2/US3 are not done.

---

## Phase 4: User Story 2 - Guarantee base-case and edge-case coverage for every tool and node (Priority: P2)

**Goal**: Every in-scope tool and node has at least one base-case and one edge-case test.

**Independent Test**: The `coverage_matrix` in `audit-record.md` shows `has_base_test = true` and `has_edge_test = true` for all 19 rows.

### Implementation for User Story 2

- [X] T021 [P] [US2] In `tests/unit/test_cart_tools.py`, for `add_items_to_cart`, `remove_items_from_cart`, `mark_order_confirmed`, and `get_cart_total`: using the T004 coverage matrix, add whichever base-case or edge-case test is missing for each, so that "every ToolOrNode MUST have has_base_test = true AND has_edge_test = true" (data-model.md / FR-002 / SC-001). Each added test must carry the required category comment and be recorded in `audit-record.md`'s `added` list with the `gap_closed` it addresses — "A TestCase with status = added MUST have category of base or edge ... and a non-null gap_closed" (data-model.md). Depends on T005 (same file). **Done**: all 4 tools already had base+edge coverage after T005's removals; no additions needed.
- [X] T022 [P] [US2] Apply the same gap-filling to `tests/unit/test_menu_tools.py` for `get_menu` and `get_menu_item`, following the same rule as T021. Depends on T006 (same file). **Done**: `get_menu_item` was missing a direct edge-case test (only indirectly covered via `resolve_menu_item`); added `test_get_menu_item_not_found_reports_no_match_message`. `get_menu` already had base+edge.
- [X] T023 [P] [US2] Apply the same gap-filling to `tests/unit/test_refund_tools.py` for `lookup_order`, `process_refund_request`, `log_complaint`, and `conclude_refund_conversation`, following the same rule as T021. Depends on T007 (same file). **Done**: `conclude_refund_conversation` was missing an edge case; added `test_conclude_refund_conversation_idempotent_when_already_resolved`. The other 3 tools already had base+edge.
- [X] T024 [P] [US2] Apply the same gap-filling to `tests/unit/test_router_agent.py` for `router_agent`, following the same rule as T021. Depends on T008 (same file). **Done**: base+edge already present; no additions needed (one out-of-scope coverage gap flagged as an Observation in audit-record.md rather than actioned).
- [X] T025 [P] [US2] Apply the same gap-filling to `tests/unit/test_clarify_intent.py` for `clarify_intent`, following the same rule as T021. Depends on T009 (same file). **Done**: base+edge already present; no additions needed.
- [X] T026 [P] [US2] Apply the same gap-filling to `tests/unit/test_order_support_agent.py` for `call_model` and `await_customer`, following the same rule as T021. Depends on T010 (same file). **Done**: `call_model` already had base+edge+error. `await_customer` had edge+regression but no test tagged `(base)`; retagged the existing happy-path test to `(base)` instead of adding a duplicate (see Reclassified section in audit-record.md) — no new test needed.
- [X] T027 [P] [US2] Apply the same gap-filling to `tests/unit/test_refund_agent.py` for `refund_agent` and `refund_await_customer`, following the same rule as T021. Depends on T011 (same file). **Done**: `refund_agent` had base but no edge; added `test_refund_agent_omits_sentiment_message_when_sentiment_is_none`. `refund_await_customer` already had base+edge.
- [X] T028 [P] [US2] Apply the same gap-filling to `tests/unit/test_cart_summary_and_ticket_nodes.py` for `cart_summary_node`, `ticket_gen_node`, and `refund_ticket_node`, following the same rule as T021. Depends on T012 (same file). **Done**: all 3 nodes already had base+edge; no additions needed (one out-of-scope gap in `refund_ticket_node` flagged as an Observation rather than actioned).
- [X] T029 [US2] Update the `coverage_matrix` in `audit-record.md` so all 19 rows show `has_base_test = true` and `has_edge_test = true`. Depends on T021-T028. **Done**: all 19 rows updated incrementally as each file was reviewed; verified no `TBD` remains in the matrix.
- [X] T030 [US2] Run `pytest -q` and confirm the full suite still passes after all gap-filling additions. Depends on T029. **Done**: 175/175 pass (see T020 run, which covers both US1 removals and US2 additions together).

**Checkpoint**: 100% of in-scope tools/nodes have base+edge coverage; suite still green. US1 + US2 together deliver a leaner, fully-covered suite.

---

## Phase 5: User Story 3 - Produce a reviewable audit record (Priority: P3)

**Goal**: A checked-in record lets a reviewer verify every removal/addition without re-deriving it from the diff.

**Independent Test**: Someone unfamiliar with the audit can open only `audit-record.md` and correctly explain why any given test was kept, removed, or added.

### Implementation for User Story 3

- [X] T031 [US3] Consolidate `audit-record.md`'s `removed` and `added` lists (populated incrementally in T005-T020 and T021-T030) into the final form described in `data-model.md`'s `AuditRecord` entity, and remove the now-unneeded working inventory from T003 (or move it to an appendix) so the record stays readable. Depends on T020, T030. **Done**: removed the placeholder inventory section; added a per-file before/after count table (FR-009).
- [X] T032 [US3] Re-run `pytest --collect-only -q` and `pytest -q`; record `final_test_count` and `final_runtime` in `audit-record.md`. Confirm "final_test_count <= baseline_test_count" (SC-003) and "final_runtime <= baseline_runtime, or a documented explanation if not" (SC-007, data-model.md). Depends on T031. **Done**: 175 ≤ 183 (SC-003 met); 6.41s < 13.24s baseline (SC-007 met, actually faster).
- [X] T033 [US3] Readability validation (SC-004): sample 3 entries from `removed` and 3 from `added` in the finalized `audit-record.md`; for each, confirm (without looking at the git diff) you can state what happened and why. Append a short "Validated" note with the outcome to `audit-record.md`. Depends on T031. **Done**: sampled 3 removed + all 3 added entries; each was self-explanatory from the record alone.

**Checkpoint**: `audit-record.md` is complete, accurate, and independently readable.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final, whole-suite verification that the success criteria hold everywhere, not just in the files touched above.

- [X] T034 [P] Sweep every file under `tests/` for any test case still missing the required `(base)`/`(edge)`/`(error)`/`(regression)` category comment (constitution Principle I / FR-007 / SC-006), and fix any gaps found so 100% of test cases in the suite carry the tag. **Done**: scripted sweep of all 14 test files, 0 missing tags — 100% compliance (SC-006 met).
- [X] T035 [P] Confirm no full end-to-end/multi-agent pipeline test was introduced: `git diff main...009-test-case-audit --stat -- tests/` shows only edits to the existing files touched above plus the new `audit-record.md` (SC-005, FR-006), per `quickstart.md` step 5. **Done**: `git status`/`git diff --stat` show only modifications to the 10 existing test files touched during this audit — no new test file was created (SC-005/FR-006 confirmed).
- [X] T036 Run through `quickstart.md` end-to-end (all 6 steps) and confirm every step passes. **Done**: all 6 steps pass — count (175≤183), full suite (175 passed), coverage spot-check (mark_order_confirmed base+edge both present), category tags (100% via T034's full sweep, stronger than the spot-check), no new test file (T035), and removed-test traceability (T033).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup (T001) — BLOCKS all user story phases.
- **User Story 1 (Phase 3)**: Depends on Foundational (Phase 2). No dependency on US2/US3.
- **User Story 2 (Phase 4)**: Depends on Foundational (Phase 2) *and*, file-by-file, on the matching US1 task (T021→T005, T022→T006, ..., T028→T012) since both edit the same file.
- **User Story 3 (Phase 5)**: Depends on US1 (T020) and US2 (T030) both being complete — it records their combined output.
- **Polish (Phase 6)**: Depends on Phase 5 completion.

### Within Each Phase

- Phase 3: T005-T018 are parallel (different files); T019 (cross-file pass) depends on all of them; T020 (suite run) depends on T019.
- Phase 4: T021-T028 are parallel with each other, but each depends on its Phase-3 same-file counterpart; T029 depends on T021-T028; T030 depends on T029.
- Phase 5: T031 → T032 and T031 → T033 (both write to `audit-record.md`, so do them one after another, not simultaneously).
- Phase 6: T034 and T035 are independent of each other; T036 depends on both.

### Parallel Opportunities

- All of T005-T018 (Phase 3) can run in parallel — 14 different files, no shared state beyond appending to `audit-record.md`'s `removed` list (append-only, low conflict risk if done by one contributor sequentially or coordinated if split across people).
- T021-T028 (Phase 4) can likewise run in parallel once their respective Phase-3 file task is done.
- T034 and T035 (Phase 6) can run in parallel.

---

## Parallel Example: User Story 1

```bash
# Launch the per-file redundancy reviews together (different files, no cross-dependency):
Task: "Review tests/unit/test_cart_tools.py for redundant test cases (T005)"
Task: "Review tests/unit/test_menu_tools.py for redundant test cases (T006)"
Task: "Review tests/unit/test_refund_tools.py for redundant test cases (T007)"
Task: "Review tests/unit/test_router_agent.py for redundant test cases (T008)"
# ...through T018
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (Setup) and Phase 2 (Foundational).
2. Complete Phase 3 (User Story 1) — redundant tests removed, suite still green.
3. **STOP and VALIDATE**: this alone delivers the core value (a leaner suite) even without US2/US3.

### Incremental Delivery

1. Setup + Foundational → baseline and inventory ready.
2. Add User Story 1 → redundancy removed, verified independently (MVP).
3. Add User Story 2 → 100% base/edge coverage guaranteed, verified independently.
4. Add User Story 3 → `audit-record.md` finalized and independently readable.
5. Polish → whole-suite sweep confirms SC-005/SC-006 hold everywhere, not just in touched files.

---

## Notes

- [P] tasks touch different test files and have no completion-order dependency on each other.
- [Story] labels map every Phase 3+ task to spec.md's US1/US2/US3 for traceability.
- Because US1 and US2 both edit the same 8 tool/node-owning files, each US2 file task
  depends on its US1 counterpart finishing first — this is a same-file dependency, not a
  cross-story blocker; the two stories are still independently *valuable* and independently
  *verifiable* via their own checkpoints (T020, T030).
- Commit after each file-level task or logical group, per repository convention.
- No test-writing tasks precede this feature's own edits (per the Tests note above) — the
  audit's additions in Phase 4 *are* the tests, each written and confirmed passing as it's
  added (Constitution Check in plan.md).
