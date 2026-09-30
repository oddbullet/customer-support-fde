import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from customer_support_fde import clock, db
from customer_support_fde.nodes import ticket_gen_node as ticket_gen_node_module
from customer_support_fde.nodes.cart_summary_node import (
    OrderNotPlacedError,
    build_order_summary,
    cart_summary_node,
    render_order_summary,
)
from customer_support_fde.nodes.ticket_gen_node import ticket_gen_node
from customer_support_fde.tools.menu_tools import cart_total

SAMPLE_MENU = [
    {
        "name": "Kung Pao Chicken",
        "price": 12.95,
        "ingredients": ["chicken", "peanuts", "dried chili"],
    },
    {
        "name": "Hot and Sour Soup",
        "price": 5.50,
        "ingredients": ["tofu", "wood ear mushroom", "egg"],
    },
    {
        "name": "Spring Rolls",
        "price": 6.95,
        "ingredients": ["cabbage", "carrot", "wheat wrapper"],
    },
]


def _base_state() -> dict:
    return {
        "user_query": "that's all",
        "destination": "order_support",
        "sentiment": None,
        "messages": [],
        "menu": SAMPLE_MENU,
        "cart_items": {"Kung Pao Chicken": 2, "Spring Rolls": 1},
        "order_confirmed": True,
        "order_ticket": None,
        "order_summary": None,
        "order_id": None,
        "order_conversation_summary": None,
        "refund_conversation_summary": None,
        "account_number": None,
        "account_preferences": None,
        "tool_limit_reached": None,
    }


# A multi-item cart prices each line and sums to the order total. (happy)
def test_build_order_summary_multi_item_totals():
    cart = {"Kung Pao Chicken": 2, "Hot and Sour Soup": 1}

    summary = build_order_summary(cart, SAMPLE_MENU)

    assert summary["lines"] == [
        {
            "name": "Kung Pao Chicken",
            "quantity": 2,
            "unit_price": 12.95,
            "line_total": 25.90,
        },
        {
            "name": "Hot and Sour Soup",
            "quantity": 1,
            "unit_price": 5.50,
            "line_total": 5.50,
        },
    ]
    assert summary["total"] == 31.40


# A single-unit cart's line total equals the unit price. (happy)
def test_build_order_summary_single_unit_line_total_equals_unit_price():
    cart = {"Spring Rolls": 1}

    summary = build_order_summary(cart, SAMPLE_MENU)

    assert summary["lines"][0]["line_total"] == summary["lines"][0]["unit_price"]
    assert summary["lines"][0]["unit_price"] == 6.95


# Lines preserve cart_items insertion order and carry exactly the four documented fields. (happy)
def test_build_order_summary_preserves_order_and_line_fields():
    cart = {"Spring Rolls": 1, "Kung Pao Chicken": 2, "Hot and Sour Soup": 1}

    summary = build_order_summary(cart, SAMPLE_MENU)

    assert [line["name"] for line in summary["lines"]] == [
        "Spring Rolls",
        "Kung Pao Chicken",
        "Hot and Sour Soup",
    ]
    for line in summary["lines"]:
        assert set(line.keys()) == {"name", "quantity", "unit_price", "line_total"}


# build_order_summary does not mutate the cart_items dict it is given. (edge, regression)
def test_build_order_summary_does_not_mutate_input_cart_items():
    cart = {"Kung Pao Chicken": 2, "Spring Rolls": 1}
    original = dict(cart)

    build_order_summary(cart, SAMPLE_MENU)

    assert cart == original


# An empty cart yields no lines and total is None (not 0.0). (edge)
def test_build_order_summary_empty_cart_yields_none_total():
    summary = build_order_summary({}, SAMPLE_MENU)

    assert summary["lines"] == []
    assert summary["total"] is None


# build_order_summary's total matches the shared cart_total() helper for the
# same cart, so a mid-conversation total (get_cart_total) can never drift
# from the final order total — guards FR-004/SC-003 in
# specs/006-cart-total-lookup/spec.md. (happy, regression)
def test_build_order_summary_total_matches_shared_cart_total_helper():
    cart = {"Kung Pao Chicken": 2, "Hot and Sour Soup": 1, "Spring Rolls": 3}

    summary = build_order_summary(cart, SAMPLE_MENU)

    assert summary["total"] == cart_total(cart, SAMPLE_MENU)


# render_order_summary names every item, shows unit price and line total
# formatted as currency, and emits one Total line for a fully-priced order. (happy)
def test_render_order_summary_fully_priced():
    summary = build_order_summary(
        {"Kung Pao Chicken": 2, "Hot and Sour Soup": 1}, SAMPLE_MENU
    )

    rendered = render_order_summary(summary)

    assert "Kung Pao Chicken" in rendered
    assert "x2" in rendered
    assert "Hot and Sour Soup" in rendered
    assert "x1" in rendered
    assert "$12.95" in rendered
    assert "$25.90" in rendered
    assert "$5.50" in rendered
    assert "Total: $31.40" in rendered
    assert rendered.count("Total: $31.40") == 1


# An empty summary renders the empty-cart notice with no amount line. (edge)
def test_render_order_summary_empty_cart_wording():
    summary = build_order_summary({}, SAMPLE_MENU)

    rendered = render_order_summary(summary)

    assert rendered == "There's nothing in your order to summarize."


def _use_tmp_db(monkeypatch, tmp_path):
    path = tmp_path / "test.db"
    db.init_database(path)
    db.set_restaurant_timezone("America/Los_Angeles", path)
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(path))
    return path


_PLACED_AT = datetime(2026, 9, 29, 14, 3, tzinfo=timezone.utc)


# cart_summary_node writes order_summary, records the order, writes order_id,
# and appends exactly one AIMessage carrying the rendered recap with a
# hyphenated Order ID line. (happy)
def test_cart_summary_node_writes_summary_and_appends_one_message(
    monkeypatch, tmp_path
):
    _use_tmp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(clock, "trusted_now", lambda: _PLACED_AT)
    state = _base_state()

    result = cart_summary_node(state)

    expected_summary = build_order_summary(state["cart_items"], SAMPLE_MENU)
    assert result["order_summary"] == expected_summary
    assert result["order_id"] is not None
    assert len(result["messages"]) == 1
    assert isinstance(result["messages"][0], AIMessage)
    assert result["messages"][0].content == render_order_summary(
        expected_summary, result["order_id"], _PLACED_AT
    )
    assert result["messages"][0].content.endswith(
        f"Order ID: {db.format_order_id(result['order_id'])}\n"
        "Please show this ID when you pick up your order."
    )


# A placed order's recap leads with an explicit confirmation that the order went
# through, so the customer never has to infer it. (happy)
def test_render_order_summary_with_order_id_confirms_order_placed():
    summary = build_order_summary({"Spring Rolls": 1}, SAMPLE_MENU)

    rendered = render_order_summary(summary, "K7QP3M9X")

    assert rendered == (
        "Your order has been placed.\n\n"
        "Here's your order:\n"
        f"- Spring Rolls x1 @ ${6.95:.2f} each = ${6.95:.2f}\n\n"
        f"Total: ${6.95:.2f}\n"
        "Order ID: K7QP-3M9X\n"
        "Please show this ID when you pick up your order."
    )


# A placed order's recap shows when it was placed, in the restaurant's local time,
# between the total and the Order ID. (happy)
def test_render_order_summary_shows_local_placed_time():
    summary = build_order_summary({"Spring Rolls": 1}, SAMPLE_MENU)

    rendered = render_order_summary(summary, "K7QP3M9X", _PLACED_AT)

    assert rendered == (
        "Your order has been placed.\n\n"
        "Here's your order:\n"
        f"- Spring Rolls x1 @ ${6.95:.2f} each = ${6.95:.2f}\n\n"
        f"Total: ${6.95:.2f}\n"
        "Placed: Sep 29, 2026, 7:03 AM PDT\n"
        "Order ID: K7QP-3M9X\n"
        "Please show this ID when you pick up your order."
    )


# The order is stamped with the trusted (NTP) time, not the host clock. (happy)
def test_cart_summary_node_stamps_order_with_trusted_time(monkeypatch, tmp_path):
    path = _use_tmp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(clock, "trusted_now", lambda: _PLACED_AT)

    result = cart_summary_node(_base_state())

    assert db.get_order(result["order_id"], path)["created_at"] == "2026-09-29T14:03:00.000Z"
    assert "Placed: Sep 29, 2026, 7:03 AM PDT" in result["messages"][0].content


# If the time server can't be reached, the order is not placed and the failure is
# logged. (failure)
def test_cart_summary_node_clock_failure_raises_order_not_placed(
    monkeypatch, tmp_path, caplog
):
    path = _use_tmp_db(monkeypatch, tmp_path)
    error = clock.ClockUnavailableError("pool.ntp.org unreachable")

    def _clock_down():
        raise error

    monkeypatch.setattr(clock, "trusted_now", _clock_down)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(OrderNotPlacedError) as excinfo:
            cart_summary_node(_base_state())

    assert excinfo.value.__cause__ is error
    assert any(record.exc_info and record.exc_info[1] is error for record in caplog.records)
    with db._connection(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0


# An empty cart writes no order, leaves order_id as None, and keeps the
# existing "nothing to summarize" wording. (edge)
def test_cart_summary_node_empty_cart_writes_no_order(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    state = _base_state()
    state["cart_items"] = {}

    result = cart_summary_node(state)

    assert result["order_id"] is None
    assert result["messages"][0].content == "There's nothing in your order to summarize."


# A store failure while recording the order raises OrderNotPlacedError (chained to the
# original error) instead of producing a success message, and the failure is logged
# with its exception for Phoenix. (failure)
@pytest.mark.parametrize(
    "error",
    [db.OrderStoreError("disk I/O error"), db.MenuStoreError("Menu database not found")],
    ids=["order_store", "menu_store"],
)
def test_cart_summary_node_record_order_failure_raises_order_not_placed(
    monkeypatch, caplog, error
):
    def _fail(summary, **kwargs):
        raise error

    monkeypatch.setattr("customer_support_fde.db.record_order", _fail)
    state = _base_state()

    with caplog.at_level(logging.ERROR):
        with pytest.raises(OrderNotPlacedError) as excinfo:
            cart_summary_node(state)

    assert excinfo.value.__cause__ is error
    assert any(record.exc_info and record.exc_info[1] is error for record in caplog.records)


# render_order_summary(summary) called without an order_id is byte-identical
# to today's output. (edge, regression)
def test_render_order_summary_without_order_id_is_byte_identical():
    summary = build_order_summary(
        {"Kung Pao Chicken": 2, "Spring Rolls": 1}, SAMPLE_MENU
    )

    assert render_order_summary(summary) == (
        "Here's your order:\n"
        f"- Kung Pao Chicken x2 @ ${12.95:.2f} each = ${25.90:.2f}\n"
        f"- Spring Rolls x1 @ ${6.95:.2f} each = ${6.95:.2f}\n\n"
        f"Total: ${summary['total']:.2f}"
    )


# order_ticket carries items plus the same lines/total as order_summary. (happy)
def test_ticket_gen_node_ticket_mirrors_order_summary():
    state = _base_state()
    summary = build_order_summary(state["cart_items"], SAMPLE_MENU)
    state["order_summary"] = summary
    state["order_id"] = "K7QP3M9X"

    result = ticket_gen_node(state)

    assert result["order_ticket"] == {
        "order_id": "K7QP3M9X",
        "items": {"Kung Pao Chicken": 2, "Spring Rolls": 1},
        "lines": summary["lines"],
        "total": summary["total"],
    }
    for key in ("user_query", "destination", "sentiment", "cart_items", "order_confirmed"):
        assert result[key] == state[key]


# The ticket's priced values are copied from order_summary, not recomputed
# from cart_items and the menu — proven with values a fresh calculation
# could never produce. (edge, regression)
def test_ticket_gen_node_copies_order_summary_values_without_recomputing():
    state = _base_state()
    state["order_summary"] = {
        "lines": [
            {
                "name": "Kung Pao Chicken",
                "quantity": 2,
                "unit_price": 999.99,
                "line_total": 1999.98,
            }
        ],
        "total": 1999.98,
    }

    result = ticket_gen_node(state)

    assert result["order_ticket"]["lines"] == state["order_summary"]["lines"]
    assert result["order_ticket"]["total"] == 1999.98


# A missing or None order_summary yields empty defaults instead of raising. (edge)
def test_ticket_gen_node_defaults_when_order_summary_missing():
    state = _base_state()
    state["order_summary"] = None

    result = ticket_gen_node(state)

    assert result["order_ticket"]["lines"] == []
    assert result["order_ticket"]["total"] is None


# A confirmed order with a non-empty order_summary produces a ticket file on
# disk under the configured tickets directory. (happy)
def test_ticket_gen_node_writes_order_ticket_file(monkeypatch, tmp_path):
    monkeypatch.setenv("CUSTOMER_SUPPORT_TICKETS_DIR", str(tmp_path))
    state = _base_state()
    state["order_summary"] = build_order_summary(state["cart_items"], SAMPLE_MENU)
    state["order_id"] = "K7QP3M9X"

    ticket_gen_node(state)

    assert (tmp_path / "order-K7QP3M9X.md").exists()


# A state with no order_summary (nothing to summarize) writes no ticket file. (edge)
def test_ticket_gen_node_writes_no_file_when_order_summary_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("CUSTOMER_SUPPORT_TICKETS_DIR", str(tmp_path))
    state = _base_state()
    state["order_summary"] = None

    ticket_gen_node(state)

    assert list(tmp_path.iterdir()) == []


# A support-only conversation (order_summary never built) writes no ticket
# file — proves FR-003 for the "never ordered" case specifically. (edge)
def test_ticket_gen_node_writes_no_file_for_support_only_conversation(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("CUSTOMER_SUPPORT_TICKETS_DIR", str(tmp_path))
    state = _base_state()
    state["cart_items"] = {}
    state["order_summary"] = None

    ticket_gen_node(state)

    assert list(tmp_path.iterdir()) == []


# A cart that was started but never confirmed into an order_summary writes no
# ticket file — proves FR-003 for the abandoned-cart edge case. (edge)
def test_ticket_gen_node_writes_no_file_for_abandoned_cart(monkeypatch, tmp_path):
    monkeypatch.setenv("CUSTOMER_SUPPORT_TICKETS_DIR", str(tmp_path))
    state = _base_state()
    state["cart_items"] = {"Kung Pao Chicken": 1}
    state["order_summary"] = None

    ticket_gen_node(state)

    assert list(tmp_path.iterdir()) == []


def _refund_base_state() -> dict:
    return {
        "user_query": "I got the wrong dish",
        "destination": "refund",
        "sentiment": "negative",
        "messages": [],
        "menu": SAMPLE_MENU,
        "cart_items": {},
        "order_confirmed": False,
        "order_ticket": None,
        "order_summary": None,
        "order_id": None,
        "order_lookup": None,
        "refund_resolved": True,
        "refund_request": None,
        "complaint_ids": {},
        "refund_ticket": None,
        "order_conversation_summary": None,
        "refund_conversation_summary": None,
        "account_number": None,
        "account_preferences": None,
        "tool_limit_reached": None,
    }


# refund_ticket_node produces the data-model.md ticket shape from state. (happy)
def test_refund_ticket_node_produces_documented_shape():
    state = _refund_base_state()
    state["order_lookup"] = {"order_id": "K7QP3M9X", "total": 22.0, "lines": []}
    state["refund_request"] = {"id": 1, "amount": 10.0}
    state["complaint_ids"] = {"K7QP3M9X": 5}

    result = ticket_gen_node(state)

    assert result["refund_ticket"] == {
        "order_id": "K7QP3M9X",
        "order": state["order_lookup"],
        "sentiment": "negative",
        "decision": "eligible",
        "refund_request": state["refund_request"],
        "complaint_ids": [5],
        "issue": None,
        "refund_created": True,
    }


# refund_ticket_node handles the case where no order was ever identified. (edge)
def test_refund_ticket_node_handles_no_order_identified():
    state = _refund_base_state()

    result = ticket_gen_node(state)

    assert result["refund_ticket"]["order_id"] is None
    assert result["refund_ticket"]["order"] is None
    assert result["refund_ticket"]["refund_request"] is None
    assert result["refund_ticket"]["complaint_ids"] == []
    assert result["refund_ticket"]["decision"] is None


def _patch_ticket_gen_llm(monkeypatch, issue):
    fake_structured_llm = MagicMock()
    fake_structured_llm.invoke.return_value = (
        ticket_gen_node_module._RefundIssueExtraction(issue=issue)
    )
    fake_llm = MagicMock()
    fake_llm.with_structured_output.return_value = fake_structured_llm
    monkeypatch.setattr(ticket_gen_node_module, "_build_llm", lambda: fake_llm)
    return fake_structured_llm


# _extract_refund_issue returns the structured output's stripped issue field
# when there is a conversation to summarize. (happy)
def test_extract_refund_issue_returns_stripped_model_reply(monkeypatch):
    _patch_ticket_gen_llm(monkeypatch, "  Customer received the wrong dish.  ")
    state = _refund_base_state()
    state["messages"] = [HumanMessage(content="I got the wrong dish")]

    result = ticket_gen_node_module._extract_refund_issue(state)

    assert result == "Customer received the wrong dish."


# _extract_refund_issue returns None without invoking the model when both
# refund_conversation_summary and messages are empty/absent. (edge)
def test_extract_refund_issue_returns_none_without_invoking_model_when_nothing_to_summarize(
    monkeypatch,
):
    fake_structured_llm = _patch_ticket_gen_llm(monkeypatch, "irrelevant")
    state = _refund_base_state()
    state["messages"] = []
    state["refund_conversation_summary"] = None

    result = ticket_gen_node_module._extract_refund_issue(state)

    assert result is None
    fake_structured_llm.invoke.assert_not_called()


# _extract_refund_issue returns None when the structured output's issue
# field is null, its explicit signal that no issue was raised. (edge)
def test_extract_refund_issue_returns_none_when_structured_output_has_no_issue(
    monkeypatch,
):
    _patch_ticket_gen_llm(monkeypatch, None)
    state = _refund_base_state()
    state["messages"] = [HumanMessage(content="just checking my order status")]

    result = ticket_gen_node_module._extract_refund_issue(state)

    assert result is None


# _extract_refund_issue returns None and logs a WARNING when the structured
# output call raises, never letting the exception propagate. (failure)
def test_extract_refund_issue_returns_none_and_logs_warning_on_llm_failure(
    monkeypatch, caplog
):
    fake_structured_llm = MagicMock()
    fake_structured_llm.invoke.side_effect = RuntimeError("model unavailable")
    fake_llm = MagicMock()
    fake_llm.with_structured_output.return_value = fake_structured_llm
    monkeypatch.setattr(ticket_gen_node_module, "_build_llm", lambda: fake_llm)
    state = _refund_base_state()
    state["messages"] = [HumanMessage(content="I got the wrong dish")]

    with caplog.at_level(logging.WARNING):
        result = ticket_gen_node_module._extract_refund_issue(state)

    assert result is None
    assert any(record.levelno == logging.WARNING for record in caplog.records)


# ticket_gen_node's refund branch sets issue from _extract_refund_issue's
# return value and refund_created from whether a refund_request exists. (happy)
def test_ticket_gen_node_refund_branch_sets_issue_and_refund_created(monkeypatch):
    _patch_ticket_gen_llm(monkeypatch, "Customer received the wrong dish.")
    state = _refund_base_state()
    state["order_lookup"] = {"order_id": "K7QP3M9X", "total": 22.0, "lines": []}
    state["refund_request"] = {"id": 1, "amount": 10.0}
    state["messages"] = [HumanMessage(content="I got the wrong dish")]

    result = ticket_gen_node(state)

    assert result["refund_ticket"]["issue"] == "Customer received the wrong dish."
    assert result["refund_ticket"]["refund_created"] is True


# When _extract_refund_issue resolves to None, the refund_ticket's issue is
# None and refund_created is False when no refund_request exists. (edge)
def test_ticket_gen_node_refund_branch_handles_no_issue_and_no_refund(monkeypatch):
    _patch_ticket_gen_llm(monkeypatch, None)
    state = _refund_base_state()
    state["messages"] = [HumanMessage(content="just checking in")]

    result = ticket_gen_node(state)

    assert result["refund_ticket"]["issue"] is None
    assert result["refund_ticket"]["refund_created"] is False


# If the complaint lookup fails while building a refund ticket, the ticket is still
# produced with decision None and the failure is logged, so a store hiccup at the end
# doesn't hide a conversation that already finished. (failure)
def test_refund_ticket_node_degrades_when_complaint_lookup_fails(monkeypatch, caplog):
    _patch_ticket_gen_llm(monkeypatch, None)

    def _store_down(*args, **kwargs):
        raise db.OrderStoreError("database is locked")

    monkeypatch.setattr(db, "list_complaints", _store_down)
    state = _refund_base_state()
    state["order_lookup"] = {"order_id": "K7QP3M9X", "total": 22.0, "lines": []}
    state["complaint_ids"] = {"K7QP3M9X": 5}

    with caplog.at_level(logging.WARNING):
        result = ticket_gen_node(state)

    assert result["refund_ticket"]["decision"] is None
    assert result["refund_ticket"]["complaint_ids"] == [5]
    assert any(
        record.exc_info and isinstance(record.exc_info[1], db.OrderStoreError)
        for record in caplog.records
    )
