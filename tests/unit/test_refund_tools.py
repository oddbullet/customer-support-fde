import pytest
from langgraph.types import Command
from pydantic import ValidationError

from customer_support_fde import db
from customer_support_fde.tools.refund_tools import (
    UndeliveredItem,
    conclude_refund_conversation,
    log_complaint,
    lookup_order,
    process_refund_request,
)

from conftest import seed_order


def _sample_lines() -> list[dict]:
    return [
        {
            "name": "Kung Pao Chicken",
            "quantity": 2,
            "unit_price": 12.95,
            "line_total": 25.90,
        },
        {
            "name": "Spring Rolls",
            "quantity": 1,
            "unit_price": 6.95,
            "line_total": 6.95,
        },
    ]


# A found order id sets order_lookup and renders lines, quantities, unit prices, total,
# and placement time. (base)
def test_lookup_order_found_sets_order_lookup_and_renders_details(refund_db, monkeypatch):
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(refund_db))
    order_id = db.record_order(
        {"lines": _sample_lines(), "total": 32.85}, refund_db
    )

    result = lookup_order.func(
        order_id=order_id, state={"order_lookup": None}, tool_call_id="call_1"
    )

    assert isinstance(result, Command)
    assert result.update["order_lookup"]["order_id"] == order_id
    message = result.update["messages"][0].content
    assert "Kung Pao Chicken" in message
    assert "2" in message
    assert "$12.95" in message
    assert "$32.85" in message


# An unknown order id leaves order_lookup unchanged and asks the customer to re-check it. (edge)
def test_lookup_order_not_found_leaves_order_lookup_unchanged(refund_db, monkeypatch):
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(refund_db))

    result = lookup_order.func(
        order_id="NOTAREAL1", state={"order_lookup": None}, tool_call_id="call_1"
    )

    assert "order_lookup" not in result.update
    message = result.update["messages"][0].content
    assert "re-check" in message.lower() or "check" in message.lower()


# A lowercase, dashed, and O-for-0 order id form still resolves via db.normalize_order_id. (edge)
def test_lookup_order_resolves_forgiving_id_forms(refund_db, monkeypatch):
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(refund_db))
    monkeypatch.setattr(db, "_new_order_id", lambda: "K7QP3M9X")
    order_id = db.record_order({"lines": _sample_lines(), "total": 32.85}, refund_db)

    result = lookup_order.func(
        order_id="k7qp-3m9x", state={"order_lookup": None}, tool_call_id="call_1"
    )

    assert result.update["order_lookup"]["order_id"] == order_id


# conclude_refund_conversation returns a Command setting refund_resolved: True. (base)
def test_conclude_refund_conversation_sets_refund_resolved_true():
    result = conclude_refund_conversation.func(state={}, tool_call_id="call_1")

    assert isinstance(result, Command)
    assert result.update["refund_resolved"] is True
    assert result.update["messages"][0].content


# Calling again on a state that's already resolved is still idempotent: it
# reports refund_resolved: True rather than erroring or toggling it off. (edge)
def test_conclude_refund_conversation_idempotent_when_already_resolved():
    result = conclude_refund_conversation.func(
        state={"refund_resolved": True}, tool_call_id="call_1"
    )

    assert result.update["refund_resolved"] is True


def _order_with_lines(refund_db, hours_old=1) -> dict:
    order_id = seed_order(
        refund_db,
        [
            {
                "name": "Mapo Tofu",
                "quantity": 2,
                "unit_price": 10.0,
                "line_total": 20.0,
            },
            {
                "name": "Spring Rolls",
                "quantity": 1,
                "unit_price": 6.95,
                "line_total": 6.95,
            },
        ],
        age_hours=hours_old,
    )
    return db.get_order(order_id, refund_db)


def _invoke_process_refund(
    order,
    undelivered_items,
    substitute_dishes=None,
    return_confirmed=False,
    customer_issue="I didn't get my mapo tofu",
    complaint_ids=None,
):
    return process_refund_request.func(
        undelivered_items=undelivered_items,
        substitute_dishes=substitute_dishes or [],
        return_confirmed=return_confirmed,
        customer_issue=customer_issue,
        state={"order_lookup": order, "complaint_ids": complaint_ids or {}},
        tool_call_id="call_1",
    )


# A zero or negative undelivered quantity is rejected before it can record a $0.00 or
# negative refund amount. (negative)
@pytest.mark.parametrize("quantity", [0, -1])
def test_undelivered_item_with_non_positive_quantity_is_rejected(quantity):
    with pytest.raises(ValidationError):
        UndeliveredItem(name="Mapo Tofu", quantity=quantity)


# The eligible path writes a request and the reply states the amount and that it is
# submitted and awaiting review, but never "complete" (FR-016). (base)
def test_process_refund_request_eligible_writes_request_and_reports_pending(
    refund_db, monkeypatch
):
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(refund_db))
    order = _order_with_lines(refund_db)

    result = _invoke_process_refund(
        order, [UndeliveredItem(name="Mapo Tofu", quantity=2)]
    )

    assert isinstance(result, Command)
    assert result.update["refund_request"]["amount"] == 20.0
    message = result.update["messages"][0].content
    assert "$20.00" in message
    assert "submitted" in message.lower()
    assert "complete" not in message.lower()
    stored = db.get_refund_request_for_order(order["order_id"], refund_db)
    assert stored is not None
    assert stored["amount"] == 20.0


# A reported quantity greater than ordered is clamped to the ordered quantity, and the
# reply says so. (edge)
def test_process_refund_request_clamps_quantity_over_ordered_amount(
    refund_db, monkeypatch
):
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(refund_db))
    order = _order_with_lines(refund_db)

    result = _invoke_process_refund(
        order, [UndeliveredItem(name="Mapo Tofu", quantity=10)]
    )

    assert result.update["refund_request"]["amount"] == 20.0
    message = result.update["messages"][0].content
    assert "2" in message


# A reported name matching no order line contributes no amount and is reported as
# unmatched. (edge)
def test_process_refund_request_unmatched_name_contributes_nothing(
    refund_db, monkeypatch
):
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(refund_db))
    order = _order_with_lines(refund_db)

    result = _invoke_process_refund(
        order, [UndeliveredItem(name="Pizza", quantity=1)]
    )

    assert "refund_request" not in result.update
    message = result.update["messages"][0].content
    assert "Pizza" in message


# Calling with state["order_lookup"] as None writes nothing and asks for a lookup first. (edge)
def test_process_refund_request_no_order_lookup_asks_for_lookup_first(monkeypatch, tmp_path):
    path = tmp_path / "unused.db"
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(path))

    result = process_refund_request.func(
        undelivered_items=[UndeliveredItem(name="Mapo Tofu", quantity=1)],
        substitute_dishes=[],
        return_confirmed=False,
        customer_issue="missing item",
        state={"order_lookup": None, "complaint_ids": {}},
        tool_call_id="call_1",
    )

    assert "refund_request" not in result.update
    assert "complaint_ids" not in result.update
    message = result.update["messages"][0].content
    assert "look" in message.lower()


# An order that already has a request writes nothing and reports the existing
# request's status (FR-011). (edge)
def test_process_refund_request_existing_request_reports_status_not_duplicate(
    refund_db, monkeypatch
):
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(refund_db))
    order = _order_with_lines(refund_db)
    db.record_refund_request(
        order["order_id"],
        lines=[
            {"name": "Mapo Tofu", "quantity": 2, "unit_price": 10.0, "line_total": 20.0}
        ],
        amount=20.0,
        substitute_dishes=None,
        return_confirmed=False,
        path=refund_db,
    )

    result = _invoke_process_refund(
        order, [UndeliveredItem(name="Mapo Tofu", quantity=2)]
    )

    assert "refund_request" not in result.update
    message = result.update["messages"][0].content
    assert "pending" in message.lower()
    assert len(db.list_refund_requests(refund_db)) == 1


# An OrderStoreError during the write yields an explicit "could not be recorded"
# message rather than a confirmation (FR-025). (error)
def test_process_refund_request_store_error_yields_not_recorded_message(
    refund_db, monkeypatch
):
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(refund_db))
    order = _order_with_lines(refund_db)
    monkeypatch.setattr(
        db,
        "record_refund_request",
        lambda *a, **k: (_ for _ in ()).throw(db.OrderStoreError("boom")),
    )

    result = _invoke_process_refund(
        order, [UndeliveredItem(name="Mapo Tofu", quantity=2)]
    )

    assert "refund_request" not in result.update
    message = result.update["messages"][0].content
    assert "could not be recorded" in message.lower()


# --- Denial path (US2) ---


# A denial (order older than 48h) writes a complaint carrying customer_issue and the
# outside_window reason code, and writes no refund_requests row (FR-010, FR-018). (base)
def test_process_refund_request_denial_outside_window_writes_complaint_no_request(
    refund_db, monkeypatch
):
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(refund_db))
    order = _order_with_lines(refund_db, hours_old=49)

    result = _invoke_process_refund(
        order,
        [UndeliveredItem(name="Mapo Tofu", quantity=2)],
        customer_issue="It's been days and I never got my tofu",
    )

    assert "refund_request" not in result.update
    assert db.list_refund_requests(refund_db) == []
    complaints = db.list_complaints(refund_db)
    assert len(complaints) == 1
    assert complaints[0]["policy_reason"] == "outside_window"
    assert complaints[0]["description"] == "It's been days and I never got my tofu"
    message = result.update["messages"][0].content
    assert "48" in message


# A denial (no undelivered items reported) writes a complaint with that reason. (base)
def test_process_refund_request_denial_no_undelivered_items(refund_db, monkeypatch):
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(refund_db))
    order = _order_with_lines(refund_db)

    result = _invoke_process_refund(order, [], customer_issue="Food was cold")

    assert db.list_refund_requests(refund_db) == []
    complaints = db.list_complaints(refund_db)
    assert complaints[0]["policy_reason"] == "no_undelivered_items"


# A denial (substitute received, return declined) writes a complaint with that reason. (base)
def test_process_refund_request_denial_return_declined(refund_db, monkeypatch):
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(refund_db))
    order = _order_with_lines(refund_db)

    result = _invoke_process_refund(
        order,
        [UndeliveredItem(name="Mapo Tofu", quantity=2)],
        substitute_dishes=["Kung Pao Chicken"],
        return_confirmed=False,
        customer_issue="Got the wrong dish, won't bring it back",
    )

    assert db.list_refund_requests(refund_db) == []
    complaints = db.list_complaints(refund_db)
    assert complaints[0]["policy_reason"] == "return_declined"


# A second denial for the same order in the same conversation extends the complaint
# recorded in state["complaint_ids"] instead of inserting a second row (FR-020, SC-010). (edge)
def test_process_refund_request_second_denial_same_order_extends_complaint(
    refund_db, monkeypatch
):
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(refund_db))
    order = _order_with_lines(refund_db, hours_old=49)

    first = _invoke_process_refund(
        order, [UndeliveredItem(name="Mapo Tofu", quantity=2)], customer_issue="first"
    )
    complaint_ids = first.update["complaint_ids"]

    second = _invoke_process_refund(
        order,
        [UndeliveredItem(name="Mapo Tofu", quantity=2)],
        customer_issue="second, still upset",
        complaint_ids=complaint_ids,
    )

    assert len(db.list_complaints(refund_db)) == 1
    assert second.update["complaint_ids"] == complaint_ids
    stored = db.list_complaints(refund_db)[0]
    assert stored["description"] == "second, still upset"


# A denial for a different order creates its own complaint row. (edge)
def test_process_refund_request_denial_different_order_creates_own_row(
    refund_db, monkeypatch
):
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(refund_db))
    order_a = _order_with_lines(refund_db, hours_old=49)
    order_b = _order_with_lines(refund_db, hours_old=49)

    first = _invoke_process_refund(
        order_a, [UndeliveredItem(name="Mapo Tofu", quantity=2)], customer_issue="a"
    )
    second = _invoke_process_refund(
        order_b,
        [UndeliveredItem(name="Mapo Tofu", quantity=2)],
        customer_issue="b",
        complaint_ids=first.update["complaint_ids"],
    )

    assert len(db.list_complaints(refund_db)) == 2
    assert (
        second.update["complaint_ids"][order_b["order_id"]]
        != first.update["complaint_ids"][order_a["order_id"]]
    )


# --- log_complaint (US3) ---


def _invoke_log_complaint(description, order_lookup=None, complaint_ids=None):
    return log_complaint.func(
        description=description,
        state={"order_lookup": order_lookup, "complaint_ids": complaint_ids or {}},
        tool_call_id="call_1",
    )


# log_complaint records a complaint with policy_reason NULL. (base)
def test_log_complaint_records_with_null_policy_reason(refund_db, monkeypatch):
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(refund_db))

    result = _invoke_log_complaint("The service was rude.")

    assert isinstance(result, Command)
    complaints = db.list_complaints(refund_db)
    assert len(complaints) == 1
    assert complaints[0]["policy_reason"] is None
    assert complaints[0]["description"] == "The service was rude."


# log_complaint links to order_lookup's order when one was retrieved, and stores
# order_id NULL otherwise (FR-019). (base)
def test_log_complaint_links_to_order_when_retrieved_else_null(refund_db, monkeypatch):
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(refund_db))
    order = _order_with_lines(refund_db)

    with_order = _invoke_log_complaint("Order took forever.", order_lookup=order)
    without_order = _invoke_log_complaint("General complaint, no order given.")

    complaints = db.list_complaints(refund_db)
    linked = next(c for c in complaints if c["description"] == "Order took forever.")
    unlinked = next(
        c for c in complaints if c["description"] == "General complaint, no order given."
    )
    assert linked["order_id"] == order["order_id"]
    assert unlinked["order_id"] is None


# log_complaint extends rather than duplicates when complaint_ids already holds an id
# for that order (FR-020). (edge)
def test_log_complaint_extends_rather_than_duplicates(refund_db, monkeypatch):
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(refund_db))
    order = _order_with_lines(refund_db)

    first = _invoke_log_complaint("First complaint.", order_lookup=order)
    second = _invoke_log_complaint(
        "Second complaint, same issue.",
        order_lookup=order,
        complaint_ids=first.update["complaint_ids"],
    )

    assert len(db.list_complaints(refund_db)) == 1
    assert second.update["complaint_ids"] == first.update["complaint_ids"]


# An OrderStoreError yields a "could not be recorded" message rather than a
# confirmation (FR-025). (error)
def test_log_complaint_store_error_yields_not_recorded_message(refund_db, monkeypatch):
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(refund_db))
    monkeypatch.setattr(
        db,
        "record_complaint",
        lambda *a, **k: (_ for _ in ()).throw(db.OrderStoreError("boom")),
    )

    result = _invoke_log_complaint("Rude service.")

    message = result.update["messages"][0].content
    assert "could not be recorded" in message.lower()
