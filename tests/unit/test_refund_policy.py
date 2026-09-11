from datetime import datetime, timedelta, timezone

import pytest

from customer_support_fde import refund_policy

ORDER = {"order_id": "K7QP3M9X", "total": 22.0, "created_at": "", "lines": []}

UNDELIVERED = [
    {"name": "Mapo Tofu", "quantity": 1, "unit_price": 10.0, "line_total": 10.0}
]


_NOW = datetime(2026, 1, 3, 12, 0, 0, tzinfo=timezone.utc)


def _order_aged(hours: float) -> dict:
    created_at = (_NOW - timedelta(hours=hours)).strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    )[:-3] + "Z"
    return {**ORDER, "created_at": created_at}


# An order 47h59m old, with a confirmed return of the received substitute, is eligible. (base)
def test_eligible_at_47h59m_with_confirmed_return():
    order = _order_aged(47 + 59 / 60)

    decision = refund_policy.evaluate(
        order,
        undelivered=UNDELIVERED,
        substitute_received=True,
        return_confirmed=True,
        now=_NOW,
    )

    assert decision.eligible is True
    assert decision.reason is None


# An order exactly 48h00m old is still eligible — the window boundary is inclusive. (edge)
def test_eligible_at_exactly_48h00m_boundary_is_inclusive():
    order = _order_aged(48)

    decision = refund_policy.evaluate(
        order,
        undelivered=UNDELIVERED,
        substitute_received=False,
        return_confirmed=False,
        now=_NOW,
    )

    assert decision.eligible is True


# An order 48h01m old is denied outside_window. (edge)
def test_denied_outside_window_at_48h01m():
    order = _order_aged(48 + 1 / 60)

    decision = refund_policy.evaluate(
        order,
        undelivered=UNDELIVERED,
        substitute_received=False,
        return_confirmed=False,
        now=_NOW,
    )

    assert decision.eligible is False
    assert decision.reason == "outside_window"


# A correctly delivered item complained about for quality/temperature/timing is denied
# item_delivered when no line is reported undelivered. (base)
def test_denied_item_delivered_when_no_undelivered_line_and_item_complaint():
    order = _order_aged(1)

    decision = refund_policy.evaluate(
        order,
        undelivered=[],
        substitute_received=False,
        return_confirmed=False,
        now=_NOW,
    )

    assert decision.eligible is False
    assert decision.reason == "no_undelivered_items"


# A substitute was received but the customer declines to return it: denied return_declined. (base)
def test_denied_return_declined_when_substitute_received_and_return_not_confirmed():
    order = _order_aged(1)

    decision = refund_policy.evaluate(
        order,
        undelivered=UNDELIVERED,
        substitute_received=True,
        return_confirmed=False,
        now=_NOW,
    )

    assert decision.eligible is False
    assert decision.reason == "return_declined"


# No undelivered line reported at all is denied no_undelivered_items. (base)
def test_denied_no_undelivered_items_when_list_is_empty():
    order = _order_aged(1)

    decision = refund_policy.evaluate(
        order,
        undelivered=[],
        substitute_received=False,
        return_confirmed=False,
        now=_NOW,
    )

    assert decision.eligible is False
    assert decision.reason == "no_undelivered_items"


# An item never arrived, nothing came in its place, and no return was confirmed: still
# eligible because the return requirement is waived when nothing arrived (FR-006). (edge)
def test_eligible_when_item_never_arrived_and_no_substitute_waives_return():
    order = _order_aged(1)

    decision = refund_policy.evaluate(
        order,
        undelivered=UNDELIVERED,
        substitute_received=False,
        return_confirmed=False,
        now=_NOW,
    )

    assert decision.eligible is True
    assert decision.reason is None


# Identical inputs produce identical PolicyDecision values regardless of any sentiment
# value held elsewhere — evaluate() takes no sentiment argument at all (SC-009). (regression)
def test_evaluate_has_no_sentiment_parameter_and_is_deterministic():
    order = _order_aged(1)

    first = refund_policy.evaluate(
        order,
        undelivered=UNDELIVERED,
        substitute_received=True,
        return_confirmed=True,
        now=_NOW,
    )
    second = refund_policy.evaluate(
        order,
        undelivered=UNDELIVERED,
        substitute_received=True,
        return_confirmed=True,
        now=_NOW,
    )

    assert first == second
    import inspect

    assert "sentiment" not in inspect.signature(refund_policy.evaluate).parameters
