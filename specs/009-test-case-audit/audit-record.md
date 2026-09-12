# Audit Record: Test Case Audit & Coverage Rationalization

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

## Baseline (captured before any audit edits)

- **baseline_test_count**: 183 (via `pytest --collect-only -q`)
- **baseline_runtime**: 13.24s (via `pytest -q --basetemp=<scratch>`; see Pre-existing issues)

## Pre-existing issues (not folded into redundancy/coverage decisions)

- On this machine, `pytest -q` run with pytest's default temp-directory base
  (`%TEMP%\pytest-of-bill.yang`) fails 65 of 183 tests with
  `PermissionError: [WinError 5] Access is denied` while pytest tries to prune old
  `tmp_path` subdirectories under that base directory. This reproduces on a clean run with
  no code changes and is unrelated to any test's logic (confirmed: passing `--basetemp`
  pointing at a fresh, unlocked directory makes all 183 tests pass). Treated as a
  pre-existing environment issue per spec.md's Edge Cases guidance, not a test defect.
  All `pytest` invocations in this audit use an explicit `--basetemp` to get a reliable
  signal; this does not change any test's code, assertions, or behavior.

## Per-file test case counts (before → after)

| File | Before | After | Change |
|---|---|---|---|
| tests/unit/test_cart_tools.py | 21 | 19 | -2 |
| tests/unit/test_menu_tools.py | 18 | 18 | -1 removed, +1 added |
| tests/unit/test_refund_tools.py | 19 | 20 | +1 added |
| tests/unit/test_router_agent.py | 8 | 7 | -1 |
| tests/unit/test_clarify_intent.py | 4 | 4 | none |
| tests/unit/test_order_support_agent.py | 19 | 19 | none (1 retagged) |
| tests/unit/test_refund_agent.py | 4 | 5 | +1 added |
| tests/unit/test_cart_summary_and_ticket_nodes.py | 18 | 17 | -1 |
| tests/unit/test_db.py | 39 | 37 | -2 |
| tests/unit/test_refund_policy.py | 8 | 7 | -1 |
| tests/unit/test_cli.py | 3 | 3 | none |
| tests/integration/test_order_support_trajectory.py | 8 | 8 | none |
| tests/integration/test_refund_trajectory.py | 5 | 5 | none |
| tests/integration/test_router_trajectory.py | 9 | 6 | -3 |
| **Total** | **183** | **175** | **-8 net** |

## Coverage Matrix (T004, updated through T029)

| Tool/Node | Kind | Module | has_base_test | has_edge_test |
|---|---|---|---|---|
| add_items_to_cart | tool | tools/cart_tools.py | true | true |
| remove_items_from_cart | tool | tools/cart_tools.py | true | true |
| mark_order_confirmed | tool | tools/cart_tools.py | true | true |
| get_cart_total | tool | tools/cart_tools.py | true | true |
| get_menu | tool | tools/menu_tools.py | true | true |
| get_menu_item | tool | tools/menu_tools.py | true | true |
| lookup_order | tool | tools/refund_tools.py | true | true |
| process_refund_request | tool | tools/refund_tools.py | true | true |
| log_complaint | tool | tools/refund_tools.py | true | true |
| conclude_refund_conversation | tool | tools/refund_tools.py | true | true |
| router_agent | node | nodes/router_agent.py | true | true |
| clarify_intent | node | nodes/clarify_intent.py | true | true |
| call_model | node | nodes/order_support_agent.py | true | true |
| await_customer | node | nodes/order_support_agent.py | true | true |
| cart_summary_node | node | nodes/cart_summary_node.py | true | true |
| ticket_gen_node | node | nodes/ticket_gen_node.py | true | true |
| refund_agent | node | nodes/refund_agent.py | true | true |
| refund_await_customer | node | nodes/refund_agent.py | true | true |
| refund_ticket_node | node | nodes/ticket_gen_node.py | true | true |

## Removed

### tests/unit/test_cart_tools.py

- `test_unqualified_removal_deletes_multi_quantity_entry_entirely` — superseded by
  `test_unqualified_removal_deletes_quantity_one_entry`. Both exercise the same
  `quantity is None` deletion branch in `remove_items_from_cart`; the starting cart
  quantity (1 vs 3) doesn't change which branch runs or what's asserted (both just check
  the entry is fully gone), so the second was pure duplicate coverage, not a distinct
  edge case.
- `test_get_cart_total_reflects_cart_after_it_changes` — superseded by
  `test_get_cart_total_multiple_items_reports_combined_total`. `get_cart_total` is a pure
  computation with no caching/memoization anywhere in the call path, so calling it twice
  proves nothing beyond what a single multi-item total assertion already proves; the
  "reflects change" framing didn't correspond to any stateful behavior worth
  regression-guarding.

### tests/unit/test_menu_tools.py

- `test_price_for_item_returns_none_for_empty_menu` — superseded by
  `test_price_for_item_returns_none_when_name_not_on_menu`. `price_for_item`'s for-loop
  falls through to `return None` identically whether the menu has zero items or has items
  that just don't match the name; there is no branch that distinguishes "empty list" from
  "non-empty list with no match," so the empty-menu case added no new code-path coverage.

### tests/integration/test_router_trajectory.py

- `test_ambiguous_or_mixed_signal_request_resolved_via_clarify_intent[hello-*]` (3 of the 6
  parametrized cases) — superseded by the corresponding `[...mapo tofu?...-*]` cases.
  `router_agent` is mocked to return `"unclear"` regardless of query content, and
  `clarify_intent` never reads `user_query`, so the `query` dimension had zero effect on
  the trajectory being asserted — trimmed to the single more-illustrative query (the
  mixed-signal one named in the router's own system prompt), keeping all 3 `answer` values
  since those genuinely change the asserted trajectory branch.

### tests/unit/test_refund_policy.py

- `test_denied_no_undelivered_items_when_list_is_empty` — superseded by
  `test_denied_item_delivered_when_no_undelivered_line_and_item_complaint`. The two test
  bodies were byte-identical (same order age, same `undelivered=[]`, same
  `substitute_received`/`return_confirmed`, same assertions) — an exact duplicate, differing
  only in docstring narrative framing.

### tests/unit/test_db.py

- `test_database_path_falls_back_to_default_when_env_var_unset` — superseded by
  `test_database_path_is_read_at_call_time_not_import_time`, whose first half (delenv, then
  assert default) is the identical scenario and assertion. `database_path()`'s
  `if env_value:` check treats "unset" and "empty string" identically, and the distinct
  "empty string" trigger is separately covered by `test_database_path_falls_back_to_default_when_env_var_empty`,
  so nothing was lost.
- `test_record_order_survives_reconnect` — superseded by
  `test_record_order_returns_id_and_get_order_round_trips`. Both do the identical
  record-then-read scenario; there is no explicit connection object held open and closed in
  either test, since the path-based API opens a fresh sqlite3 connection per call regardless
  — so "survives reconnect" didn't exercise any mechanism the round-trip test doesn't
  already exercise, and its assertions were a strict subset of the round-trip test's.

### tests/unit/test_cart_summary_and_ticket_nodes.py (cross-file with test_menu_tools.py)

- `test_build_order_summary_total_always_rounds_up` — superseded by
  `test_cart_total_rounds_up_on_fractional_cent` (`tests/unit/test_menu_tools.py`).
  `build_order_summary`'s `total` field is set directly from `cart_total(menu_items, menu)`
  with no additional rounding logic of its own; both tests used the identical fractional-
  cent fixture and identical expected result, so this was a pure passthrough duplicate,
  not independent coverage of `build_order_summary` itself.

### tests/unit/test_router_agent.py

- `test_refund_sentiment_is_always_one_of_the_three_fixed_categories[negative]` —
  superseded by `test_refund_query_carries_negative_sentiment`. Both exercise the identical
  scenario (refund destination, negative sentiment) through the identical code path; the
  base test already asserts it with exact equality, while the parametrized instance only
  asserted weak set-membership. Trimmed the parametrize list to `["positive", "neutral"]`
  — the two values genuinely not covered anywhere else — rather than dropping the whole
  parametrized test.

## Added

### tests/unit/test_refund_agent.py

- `test_refund_agent_omits_sentiment_message_when_sentiment_is_none` — **gap closed**:
  `refund_agent` had two `(base)` tests (seed vs. reuse transcript) but no edge case.
  `_seed_messages`' `if sentiment is not None` branch was only ever exercised with a
  non-None sentiment; this test exercises the omission branch directly.

### tests/unit/test_refund_tools.py

- `test_conclude_refund_conversation_idempotent_when_already_resolved` — **gap closed**:
  `conclude_refund_conversation` had only a base-case test. Its body is a single
  unconditional return with no branches, so rather than force an artificial branch-based
  edge case, this test covers "boundary/unusual input" per spec.md's definition — calling
  it on a state where `refund_resolved` is already `True` — confirming idempotency (no
  crash, no toggling), which the base test (empty state) doesn't establish.

### tests/unit/test_menu_tools.py

- `test_get_menu_item_not_found_reports_no_match_message` — **gap closed**: `get_menu_item`
  (a `@tool` in FR-002 scope) had only a base-case test; its not-found/tie rendering paths
  were exercised only indirectly through `resolve_menu_item`'s own tests, which test the
  match object, not the tool's rendered string output. This test exercises the tool's
  `_render_match` not-found branch directly, giving `get_menu_item` a real edge-case test
  in its own right.

## Observations (flagged, not actioned — outside FR-002/FR-003 scope)

- `router_agent`'s `ValidationError` fallback branch (malformed structured-output from the
  LLM falls back to `destination="unclear"`, `sentiment="neutral"`) has no test coverage.
  Not added here because `router_agent` already has both a base-case and an edge-case test
  (FR-002 is satisfied), and FR-003 only mandates adding tests to close base/edge gaps —
  adding an additional test for a third, already-non-gap scenario would be scope creep
  beyond what this audit is chartered to do. Worth a follow-up ticket outside this feature.
- `refund_ticket_node`'s "complaint was logged, decision surfaces the policy_reason" branch
  (`complaint_id = complaint_ids.get(order_id or "")` then `decision = complaint["policy_reason"]`)
  has no test — existing tests cover only the "eligible" (refund_request set) and
  "no order identified" paths. Not added: `refund_ticket_node` already has both a base and
  an edge test (FR-002 satisfied), so per FR-003 this is outside this audit's mandate.

## Reclassified (category-tag correction only — not a removal or addition)

### tests/unit/test_order_support_agent.py

- `test_await_customer_interrupts_when_not_confirmed` — retagged `(regression)` →
  `(base)`. This test's scenario (order not yet confirmed → interrupt and append) is
  `await_customer`'s standard/happy path, but it carried only a `(regression)` tag, leaving
  the node with an edge-case test and a regression test but no test tagged `(base)` —
  failing `data-model.md`'s `has_base_test` check (FR-002/SC-001). Retagging (not adding a
  near-duplicate test) resolves the gap without introducing new redundancy; per FR-008 this
  only changes a category-comment label, not the test's assertions or pass/fail behavior.
  The original regression context is preserved in the comment prose.

## Final metrics (T032)

- **final_test_count**: 175 (via `pytest --collect-only -q`) — ≤ baseline of 183. **SC-003 met.**
- **final_runtime**: 6.41s (via `pytest -q --basetemp=<scratch>`) — better than the baseline
  13.24s (fewer tests, and the removed cases included some of the slower db/integration
  tests). **SC-007 met.**

## Validated (T033 — readability check, SC-004)

Sampled 3 `Removed` entries (`test_unqualified_removal_deletes_multi_quantity_entry_entirely`,
`test_ambiguous_or_mixed_signal_request_resolved_via_clarify_intent[hello-*]`,
`test_record_order_survives_reconnect`) and all 3 `Added` entries, reading only this
record (not the git diff). For each, the entry alone answers: what happened, and — for
removals — which retained test makes it redundant and why. No entry required cross-
referencing outside this file to understand. Check passed.
