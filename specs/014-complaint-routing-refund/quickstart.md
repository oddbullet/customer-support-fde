# Quickstart: Complaint Routing to Refund Agent

Validates this feature once implemented. This extends `specs/001-router-agent/quickstart.md` — it does not replace it. See that feature's [data-model.md](../001-router-agent/data-model.md) and [contracts/](../001-router-agent/contracts/) for the `RouterDecision`/`SupportState` shapes, which are unchanged by this feature.

## Prerequisites

Same as `specs/001-router-agent/quickstart.md`:

- Python 3.14 environment with project dependencies installed: `uv sync` (or equivalent) from repo root.
- `OPENROUTER_API_KEY` set (only required for the manual/live CLI check below — automated tests mock the LLM boundary).
- `customer-support-fde --init-db` run at least once against `CUSTOMER_SUPPORT_DB` (or the default `customer_support.db`), per `CLAUDE.md`.

## Run the automated tests (no live API calls required)

```sh
pytest tests/unit/test_router_agent.py -v
pytest tests/integration/test_router_trajectory.py -v
```

Expected outcome:
- `test_router_agent.py` includes assertions on `router_agent.SYSTEM_PROMPT` confirming it explicitly instructs: a past-order complaint routes to `refund` without requiring refund/money-back language; a complaint combined with an explicit refund ask is a single `refund` case, not a mixed-signal case; a complaint unrelated to a past order does not route to `refund`. These are the tests that actually fail before this feature's prompt change and pass after — see `research.md` §1 for why.
- `test_router_agent.py` also includes mocked-`RouterDecision` cases mirroring the spec's acceptance scenarios (complaint-only phrasing, complaint + explicit refund ask), documenting the expected state-shaping behavior (destination `refund`, sentiment attached) for each.
- `test_router_trajectory.py`'s `LABELED_SAMPLES` includes complaint-only entries (no refund/money-back language) that resolve to the `refund_agent` trajectory, alongside the existing order/support, explicit-refund, and ambiguous/mixed-signal entries.
- All test modules continue to fake/mock the LLM boundary so they run deterministically offline.

## Manually exercise the CLI (requires `OPENROUTER_API_KEY`)

```sh
customer-support-fde --json "My order arrived 45 minutes late and the food was cold"
# {"destination": "refund", "sentiment": "negative", "query": "My order arrived 45 minutes late and the food was cold"}
# (No refund/money-back language was used — this is the behavior this feature adds.)

customer-support-fde --json "The spring rolls I got were missing from my bag"
# {"destination": "refund", "sentiment": ..., "query": "..."}

customer-support-fde --json "My order arrived cold and an hour late, I want my money back"
# {"destination": "refund", "sentiment": "negative", "query": "..."}
# (Complaint + explicit refund ask — still a single refund case, no clarifying question.)

customer-support-fde "my last order was cold, and also does the mapo tofu have peanuts?"
# Are you: (1) placing an order, (2) asking a general question, or (3) requesting a refund? Reply with 1, 2, or 3.
# (Still triggers the clarifying question — a complaint mixed with an unrelated menu question
#  is unchanged by this feature.)
```

## Validation checklist (maps to spec Success Criteria)

- [x] SC-001: Running a representative set of complaint-only messages (no refund/money-back language) through the integration tests yields the `refund` destination at least 90% of the time. Verified via `test_labeled_sample_set_routes_to_the_expected_destination_at_least_90_percent`, which now includes 3 complaint-only entries alongside the existing samples, all resolving to `refund`.
- [x] SC-002: Every sample combining a past-order complaint with an explicit refund ask resolves directly to `refund` with no clarifying question triggered. Verified via `test_complaint_plus_refund_ask_query_routes_directly_to_refund` (unit) and the `LABELED_SAMPLES` entry for the peanut-allergy refund-ask query (integration) — none hit `clarify_intent`.
- [x] SC-003: Every message routed to `refund` via complaint recognition arrives with a sentiment assessment attached (never `None`). Verified via `test_complaint_only_query_routes_to_refund_with_sentiment` and `test_complaint_plus_refund_ask_query_routes_directly_to_refund`, both asserting `result["sentiment"] is not None`.
