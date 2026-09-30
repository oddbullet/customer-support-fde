# Review: Failure Path Testing

Failures are simulated with fakes in the unit and integration suites, so they run offline and
deterministically. Run them all with:

```
uv run pytest
```

| Area | Example test | What it proves |
|---|---|---|
| Database failures | `test_record_order_failure_partway_through_leaves_no_rows` ([test_db.py, line 288](tests/unit/test_db.py)) | A write that fails partway leaves no partial order behind. |
| | `test_cart_summary_node_record_order_failure_raises_order_not_placed` ([test_cart_summary_and_ticket_nodes.py, line 292](tests/unit/test_cart_summary_and_ticket_nodes.py)) | If saving the order fails, the customer is told the order was not placed. |
| | `test_process_refund_request_store_error_yields_not_submitted_message` ([test_refund_tools.py, line 337](tests/unit/test_refund_tools.py)) | A DB error inside a refund tool gives a safe message, not a crash. |
| Tool errors | `test_order_tool_single_exception_is_retried_by_the_agent` ([test_tool_errors_graph.py, line 110](tests/integration/test_tool_errors_graph.py)) | A tool exception goes back to the agent, which retries it. |
| | `test_refund_tool_repeated_exceptions_end_at_tool_limit` ([test_tool_errors_graph.py, line 174](tests/integration/test_tool_errors_graph.py)) | A tool that keeps failing stops at the tool-call limit instead of looping forever. |
| | `test_order_tool_invalid_args_are_reported_back_to_the_agent` ([test_tool_errors_graph.py, line 91](tests/integration/test_tool_errors_graph.py)) | Bad tool arguments come back to the model so it can fix them. |
| Missing records | `test_lookup_order_not_found_leaves_order_lookup_unchanged` ([test_refund_tools.py, line 78](tests/unit/test_refund_tools.py)) | A refund for an unknown order ID is handled cleanly. |
| | `test_unknown_account_number_presents_recovery_menu` ([test_account_identification_node.py, line 83](tests/unit/test_account_identification_node.py)) | An unknown account number shows a recovery menu. |
| | `test_load_menu_missing_table_raises_menu_store_error` ([test_db.py, line 161](tests/unit/test_db.py)) | A missing menu table is caught at startup. |
| Malformed responses | `test_bad_reply_is_retried_once` ([test_structured_output_retry.py, line 50](tests/unit/test_structured_output_retry.py)) | An unusable LLM reply is asked for one more time. |
| | `test_malformed_router_reply_asks_customer_to_clarify` ([test_circuit_breaker_graph.py, line 194](tests/integration/test_circuit_breaker_graph.py)) | If the retry is also bad, the router asks the customer to clarify. |
| | `test_denied_invalid_order_date_when_created_at_is_unusable` ([test_refund_policy.py, line 145](tests/unit/test_refund_policy.py)) | A bad order timestamp is rejected by the refund policy. |
| API failures | `test_closed_primary_retryable_failure_falls_back_and_opens` ([test_circuit_breaker.py, line 128](tests/unit/test_circuit_breaker.py)) | When the primary model fails, requests switch to the fallback model. |
| | `test_router_falls_back_when_primary_is_down` ([test_circuit_breaker_graph.py, line 90](tests/integration/test_circuit_breaker_graph.py)) | Same, through the full graph with a fake HTTP 503. |
| | `test_run_conversation_retries_failed_step_after_model_unavailable` ([test_circuit_breaker.py, line 472](tests/unit/test_circuit_breaker.py)) | When both models are down, the customer can press Enter to retry. |
| Network timeouts | `test_both_models_timing_out_raises_model_unavailable` ([test_circuit_breaker_graph.py, line 176](tests/integration/test_circuit_breaker_graph.py)) | LLM requests that time out lead to the retry prompt. |
| | `test_trusted_now_raises_clock_unavailable_on_failure` ([test_clock.py, line 40](tests/unit/test_clock.py)) | An NTP (time server) timeout raises a clear error. |
| | `test_cart_summary_node_clock_failure_raises_order_not_placed` ([test_cart_summary_and_ticket_nodes.py, line 250](tests/unit/test_cart_summary_and_ticket_nodes.py)) | No order is placed without a trusted timestamp. |

Last line of defense: `test_run_interactive_shows_generic_message_and_exits_on_unrecoverable_error` ([test_interactive.py, line 671](tests/unit/test_interactive.py))
shows that any unexpected error ends with a friendly message and exit code 1, never a stack trace.

# Review: Conversation Condensation

Condensation is tested offline with a fake LLM in
[test_conversation_condensation.py](tests/integration/test_conversation_condensation.py), and
with real summarization calls in the e2e suite.

| Area | Example test | What it proves |
|---|---|---|
| Token limits | `test_exactly_40000_tokens_does_not_condense` ([test_conversation_condensation.py, line 156](tests/integration/test_conversation_condensation.py)) | A history right at the 40,000-token limit is left alone. |
| | `test_40001_tokens_condenses_all_but_last_three_messages` ([test_conversation_condensation.py, line 172](tests/integration/test_conversation_condensation.py)) | One token over the limit folds everything but the last 3 messages into the summary. |
| Large chat histories | `test_long_conversation_condenses_repeatedly_with_bounded_history` ([test_conversation_condensation.py, line 309](tests/integration/test_conversation_condensation.py)) | A long conversation condenses again and again, and the history never grows without bound. |
| | `test_cutoff_never_orphans_a_tool_result` ([test_conversation_condensation.py, line 251](tests/integration/test_conversation_condensation.py)) | A tool result is never kept without the tool call before it. |
| Summarization failures | `test_blank_summary_is_retried` ([test_conversation_condensation.py, line 441](tests/integration/test_conversation_condensation.py)) | A blank summary is asked for one more time. |
| | `test_falls_back_to_full_history_after_two_failed_attempts` ([test_conversation_condensation.py, line 466](tests/integration/test_conversation_condensation.py)) | If both attempts fail, the full history is kept for that turn. |
| Context retention | `test_allergy_condensed_away_still_reaches_stored_preferences` ([test_conversation_condensation.py, line 548](tests/integration/test_conversation_condensation.py)) | An allergy mentioned in a condensed turn is still saved to the account's preferences. |
| | `test_refund_ticket_issue_extraction_receives_the_summary` ([test_conversation_condensation.py, line 597](tests/integration/test_conversation_condensation.py)) | The refund ticket still gets the issue from condensed turns. |

Real summarization calls (OpenRouter, LLM-judged) run with:

```
uv run pytest -m e2e
```

| Example test | What it proves |
|---|---|
| `test_judge_allergy_retained_after_condensation` ([test_condensation_retention_e2e.py, line 35](tests/e2e/test_condensation_retention_e2e.py)) | After the first message ("allergic to peanuts") is condensed away, the agent still recommends a main dish without peanuts. |
| `test_judge_refund_facts_retained_after_condensation` ([test_condensation_retention_e2e.py, line 73](tests/e2e/test_condensation_retention_e2e.py)) | After the order ID and missing dish are condensed away, the agent doesn't ask for them again and reaches the correct refund outcome. |

To keep them short, these e2e tests lower the threshold to 1 token so every turn condenses. The
40,000-token limit itself is only tested with the fake LLM.

# Review: Loop Protection Controls

All loop protection tests run offline with fakes as part of `uv run pytest`.

| Control | Implemented in |
|---|---|
| Max tool calls (same tool more than 3 steps in a row per customer turn) | `MAX_CONSECUTIVE_TOOL_CALLS`, `find_repeated_tool`, `tool_limit_node` ([tool_limit.py, line 9](src/customer_support_fde/nodes/tool_limit.py)); wired in [graph.py, line 53](src/customer_support_fde/graph.py) |
| Workflow iteration limit (100 graph steps per `graph.invoke()`) | `WORKFLOW_ITERATION_LIMIT`, passed as `recursion_limit` ([interactive.py, line 38](src/customer_support_fde/interactive.py)) |
| Circuit breaker (fallback model, 60 s cool-down, probe; 2 manual retries) | `CircuitBreaker`, `CircuitBreakerLLM` ([circuit_breaker.py, line 28](src/customer_support_fde/circuit_breaker.py)); `MODEL_RETRY_LIMIT` ([interactive.py, line 42](src/customer_support_fde/interactive.py)) |
| Execution timeouts (40 s per LLM request, 4,000 output tokens) | `LLM_TIMEOUT_SECONDS`, `LLM_MAX_OUTPUT_TOKENS`, `_chat_model` ([common.py, line 37](src/customer_support_fde/nodes/common.py)) |

| Control | Type | Example test | What it proves |
|---|---|---|---|
| Max tool calls | Happy | `test_three_same_tool_steps_per_turn_do_not_trip_limit` ([test_tool_limit_graph.py, line 52](tests/integration/test_tool_limit_graph.py)) | Normal tool use within a turn is not stopped. |
| | Edge | `test_find_repeated_tool_allows_legitimate_histories` ([test_tool_limit.py, line 147](tests/unit/test_tool_limit.py)) | Exactly 3 in a row, a run broken by another tool, parallel calls in one step, and a customer reply between calls do not trip the limit. |
| | Failure | `test_order_agent_exceeding_tool_limit_ends_conversation` ([test_tool_limit_graph.py, line 24](tests/integration/test_tool_limit_graph.py)) | A runaway order agent is stopped and the tool is not run. |
| Workflow iteration limit | Happy | `test_run_conversation_passes_iteration_limit_on_every_invoke` ([test_workflow_iteration_limit.py, line 25](tests/unit/test_workflow_iteration_limit.py)) | Every `graph.invoke()`, including resumes, runs with the limit. |
| | Edge | `test_runaway_tool_loop_is_stopped_by_iteration_limit` ([test_workflow_iteration_limit_graph.py, line 37](tests/integration/test_workflow_iteration_limit_graph.py)) | An agent alternating between two tools (which the tool limit never catches) is stopped after about 50 loops. |
| | Failure | `test_run_interactive_shows_generic_message_and_exits_when_iteration_limit_reached` ([test_workflow_iteration_limit.py, line 66](tests/unit/test_workflow_iteration_limit.py)) | The customer sees the generic error message and the CLI exits 1. |
| Circuit breaker | Happy | `test_half_open_probe_success_closes_circuit` ([test_circuit_breaker.py, line 232](tests/unit/test_circuit_breaker.py)) | After the cool-down, a successful probe switches back to the primary. |
| | Edge | `test_circuit_stays_open_just_before_cooldown_ends` ([test_circuit_breaker.py, line 271](tests/unit/test_circuit_breaker.py)) | The primary is not retried a moment before the 60 s cool-down ends. |
| | Failure | `test_router_falls_back_when_primary_is_down` ([test_circuit_breaker_graph.py, line 90](tests/integration/test_circuit_breaker_graph.py)) | A failing primary (HTTP 503) falls back through the full graph. |
| Execution timeouts | Happy | `test_build_llm_sets_request_timeout_on_all_circuit_breaker_models` ([test_llm_timeout.py, line 17](tests/unit/test_llm_timeout.py)) | Both the primary and fallback models get the 40 s timeout. |
| | Edge | `test_build_llm_caps_output_tokens_on_all_circuit_breaker_models` ([test_llm_timeout.py, line 40](tests/unit/test_llm_timeout.py)) | Both models are capped at 4,000 output tokens, so a reply that keeps streaming still ends. |
| | Failure | `test_router_falls_back_when_primary_times_out` ([test_circuit_breaker_graph.py, line 163](tests/integration/test_circuit_breaker_graph.py)) | A primary that times out falls back to the fallback model. |
