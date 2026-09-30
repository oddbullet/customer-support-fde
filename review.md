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
