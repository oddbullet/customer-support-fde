import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from agentevals.graph_trajectory.strict import graph_trajectory_strict_match
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from customer_support_fde import db
from customer_support_fde.graph import build_graph
from customer_support_fde.nodes import refund_agent, router_agent
from customer_support_fde.nodes.router_agent import RouterDecision

from _trajectory import extract_outputs


def _fake_router_llm(decision: RouterDecision) -> MagicMock:
    llm = MagicMock()
    llm.invoke.return_value = decision
    return llm


def _fake_refund_llm(responses: list[AIMessage]) -> MagicMock:
    bound = MagicMock()
    bound.invoke.side_effect = responses
    llm = MagicMock()
    llm.bind_tools.return_value = bound
    return llm


def _mock_router(monkeypatch, sentiment="neutral") -> None:
    monkeypatch.setattr(
        router_agent,
        "_build_llm",
        lambda: _fake_router_llm(
            RouterDecision(destination="refund", sentiment=sentiment)
        ),
    )


def _use_tmp_db(monkeypatch, tmp_path):
    path = tmp_path / "test.db"
    db.init_database(path)
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(path))
    return path


def _seed_order(db_path, age_hours=1) -> str:
    lines = [
        {"name": "Mapo Tofu", "quantity": 2, "unit_price": 10.0, "line_total": 20.0},
        {"name": "Spring Rolls", "quantity": 1, "unit_price": 6.95, "line_total": 6.95},
    ]
    order_id = db.record_order({"lines": lines, "total": 26.95}, db_path)
    created_at = (
        datetime.now(timezone.utc) - timedelta(hours=age_hours)
    ).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE orders SET created_at = ? WHERE id = ?", (created_at, order_id)
        )
        conn.commit()
    finally:
        conn.close()
    return order_id


def _tool_call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


# A qualifying refund conversation results in a stored pending refund request and the
# reply says it is submitted and awaiting review, never complete. (base)
def test_qualifying_refund_conversation_creates_pending_request(monkeypatch, tmp_path):
    db_path = _use_tmp_db(monkeypatch, tmp_path)
    order_id = _seed_order(db_path, age_hours=2)
    _mock_router(monkeypatch, sentiment="neutral")

    refund_llm = _fake_refund_llm(
        [
            _tool_call("lookup_order", {"order_id": order_id}, "call_1"),
            _tool_call(
                "process_refund_request",
                {
                    "undelivered_items": [{"name": "Mapo Tofu", "quantity": 2}],
                    "substitute_dishes": [],
                    "return_confirmed": False,
                    "customer_issue": "Never got my mapo tofu",
                },
                "call_2",
            ),
            _tool_call("conclude_refund_conversation", {}, "call_3"),
            AIMessage(content="Your refund request has been submitted."),
        ]
    )
    monkeypatch.setattr(refund_agent, "_build_llm", lambda: refund_llm)

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    initial_state = {
        "user_query": "I never got my mapo tofu",
        "destination": "order_support",
        "sentiment": None,
        "messages": [],
        "menu": [],
        "menu_items": {},
        "order_confirmed": False,
        "order_ticket": None,
        "order_summary": None,
        "order_id": None,
        "order_lookup": None,
        "refund_resolved": False,
        "refund_request": None,
        "complaint_ids": {},
        "refund_ticket": None,
    }

    result = graph.invoke(initial_state, config)

    assert "__interrupt__" not in result
    assert result["refund_ticket"]["decision"] == "eligible"
    stored = db.list_refund_requests(db_path)
    assert len(stored) == 1
    assert stored[0]["order_id"] == order_id
    assert stored[0]["status"] == "pending"
    assert stored[0]["amount"] == 20.0
    assert "submitted" in result["messages"][-1].content.lower()
    assert "complete" not in result["messages"][-1].content.lower()


# Shared driver for the three denial-branch tests below: runs a refund conversation
# that ends in the given process_refund_request denial and returns the final state.
def _run_denial_conversation(monkeypatch, tmp_path, order_id, process_args):
    _mock_router(monkeypatch, sentiment="negative")
    refund_llm = _fake_refund_llm(
        [
            _tool_call("lookup_order", {"order_id": order_id}, "call_1"),
            _tool_call("process_refund_request", process_args, "call_2"),
            _tool_call("conclude_refund_conversation", {}, "call_3"),
            AIMessage(content="I've noted your complaint."),
        ]
    )
    monkeypatch.setattr(refund_agent, "_build_llm", lambda: refund_llm)

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    initial_state = {
        "user_query": "I want a refund",
        "destination": "order_support",
        "sentiment": None,
        "messages": [],
        "menu": [],
        "menu_items": {},
        "order_confirmed": False,
        "order_ticket": None,
        "order_summary": None,
        "order_id": None,
        "order_lookup": None,
        "refund_resolved": False,
        "refund_request": None,
        "complaint_ids": {},
        "refund_ticket": None,
    }

    return graph.invoke(initial_state, config)


# A refund request against an order placed more than 48 hours ago is denied
# outside_window, with no refund request stored and a complaint recorded (FR-004, FR-009). (base)
def test_denial_order_outside_48_hour_window(monkeypatch, tmp_path):
    db_path = _use_tmp_db(monkeypatch, tmp_path)
    order_id = _seed_order(db_path, age_hours=72)

    result = _run_denial_conversation(
        monkeypatch,
        tmp_path,
        order_id,
        {
            "undelivered_items": [{"name": "Mapo Tofu", "quantity": 2}],
            "substitute_dishes": [],
            "return_confirmed": False,
            "customer_issue": "Order is late, want a refund",
        },
    )

    assert db.list_refund_requests(db_path) == []
    complaints = db.list_complaints(db_path)
    assert len(complaints) == 1
    assert complaints[0]["policy_reason"] == "outside_window"
    assert result["refund_ticket"]["decision"] == "outside_window"


# A complaint about a correctly delivered item (no undelivered lines reported) is
# denied no_undelivered_items, with no refund request stored (FR-005, FR-009). (base)
def test_denial_correctly_delivered_item(monkeypatch, tmp_path):
    db_path = _use_tmp_db(monkeypatch, tmp_path)
    order_id = _seed_order(db_path, age_hours=1)

    result = _run_denial_conversation(
        monkeypatch,
        tmp_path,
        order_id,
        {
            "undelivered_items": [],
            "substitute_dishes": [],
            "return_confirmed": False,
            "customer_issue": "Food was cold",
        },
    )

    assert db.list_refund_requests(db_path) == []
    complaints = db.list_complaints(db_path)
    assert complaints[0]["policy_reason"] == "no_undelivered_items"
    assert result["refund_ticket"]["decision"] == "no_undelivered_items"


# A denial where a substitute dish arrived but the customer declines to return it is
# denied return_declined, with no refund request stored (FR-006, FR-009). (base)
def test_denial_return_declined(monkeypatch, tmp_path):
    db_path = _use_tmp_db(monkeypatch, tmp_path)
    order_id = _seed_order(db_path, age_hours=1)

    result = _run_denial_conversation(
        monkeypatch,
        tmp_path,
        order_id,
        {
            "undelivered_items": [{"name": "Mapo Tofu", "quantity": 2}],
            "substitute_dishes": ["Kung Pao Chicken"],
            "return_confirmed": False,
            "customer_issue": "Got the wrong dish, won't return it",
        },
    )

    assert db.list_refund_requests(db_path) == []
    complaints = db.list_complaints(db_path)
    assert complaints[0]["policy_reason"] == "return_declined"
    assert result["refund_ticket"]["decision"] == "return_declined"


# A complaint-only conversation (no refund requested) creates no refund request. (base)
def test_complaint_only_conversation_creates_no_refund_request(monkeypatch, tmp_path):
    db_path = _use_tmp_db(monkeypatch, tmp_path)
    _mock_router(monkeypatch, sentiment="negative")

    refund_llm = _fake_refund_llm(
        [
            _tool_call(
                "log_complaint",
                {"description": "The service was rude tonight."},
                "call_1",
            ),
            _tool_call("conclude_refund_conversation", {}, "call_2"),
            AIMessage(content="I've passed your feedback to the restaurant."),
        ]
    )
    monkeypatch.setattr(refund_agent, "_build_llm", lambda: refund_llm)

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    initial_state = {
        "user_query": "The service was rude tonight",
        "destination": "order_support",
        "sentiment": None,
        "messages": [],
        "menu": [],
        "menu_items": {},
        "order_confirmed": False,
        "order_ticket": None,
        "order_summary": None,
        "order_id": None,
        "order_lookup": None,
        "refund_resolved": False,
        "refund_request": None,
        "complaint_ids": {},
        "refund_ticket": None,
    }

    result = graph.invoke(initial_state, config)

    assert "__interrupt__" not in result
    assert db.list_refund_requests(db_path) == []
    complaints = db.list_complaints(db_path)
    assert len(complaints) == 1
    assert complaints[0]["policy_reason"] is None
    assert complaints[0]["order_id"] is None
