import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from customer_support_fde import db
from customer_support_fde.graph import build_graph
from customer_support_fde.nodes import order_support_agent, refund_agent, router_agent
from customer_support_fde.nodes.router_agent import RouterDecision
from customer_support_fde.state import initial_state

SAMPLE_MENU = [
    {
        "name": "Kung Pao Chicken",
        "price": 12.95,
        "ingredients": ["chicken", "peanuts", "dried chili"],
    },
]


def _fake_router_llm(decision: RouterDecision) -> MagicMock:
    llm = MagicMock()
    llm.invoke.return_value = decision
    return llm


def _mock_router(monkeypatch, destination: str) -> None:
    monkeypatch.setattr(
        router_agent,
        "_build_llm",
        lambda: _fake_router_llm(RouterDecision(destination=destination, sentiment="neutral")),
    )


def _fake_agent_llm(responses: list[AIMessage]) -> MagicMock:
    bound = MagicMock()
    bound.invoke.side_effect = responses
    llm = MagicMock()
    llm.bind_tools.return_value = bound
    return llm


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
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE orders SET created_at = ? WHERE id = ?", (created_at, order_id)
        )
        conn.commit()
    finally:
        conn.close()
    return order_id


def _order_initial_state(user_query: str) -> dict:
    return {**initial_state(user_query), "menu": SAMPLE_MENU}


def _tool_call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


# An order agent that calls get_menu over the limit runs it only 3 times, then the graph
# ends with the breach recorded and no order confirmed or ticket written. (base)
def test_order_agent_exceeding_tool_limit_ends_conversation(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    _mock_router(monkeypatch, "order_support")
    order_llm = _fake_agent_llm(
        [_tool_call("get_menu", {}, f"call_{i}") for i in range(6)]
    )
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: order_llm)

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    result = graph.invoke(_order_initial_state("What's on the menu?"), config)
    assert "__interrupt__" in result
    # Continue without an account.
    result = graph.invoke(Command(resume="2"), config)

    assert "__interrupt__" not in result
    assert result["tool_limit_reached"] == {"agent": "order_support", "tool": "get_menu"}
    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 3
    assert result["order_confirmed"] is False
    assert result.get("order_ticket") is None
    tickets_dir = tmp_path / "tickets"
    assert not tickets_dir.exists() or not any(tickets_dir.iterdir())


# Three get_menu steps before replying don't trip the limit, and the count resets on the
# customer's reply so three more in the next turn don't trip it either. (regression)
def test_three_same_tool_steps_per_turn_do_not_trip_limit(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    _mock_router(monkeypatch, "order_support")
    order_llm = _fake_agent_llm(
        [_tool_call("get_menu", {}, f"call_a{i}") for i in range(3)]
        + [AIMessage(content="Here's the menu.")]
        + [_tool_call("get_menu", {}, f"call_b{i}") for i in range(3)]
        + [AIMessage(content="Here it is again.")]
    )
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: order_llm)

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    graph.invoke(_order_initial_state("What's on the menu?"), config)
    # Continue without an account.
    result = graph.invoke(Command(resume="2"), config)
    assert "__interrupt__" in result
    assert result.get("tool_limit_reached") is None

    result = graph.invoke(Command(resume="Can you show me the menu again?"), config)
    assert "__interrupt__" in result
    assert result.get("tool_limit_reached") is None
    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 6


# A refund agent that calls lookup_order over the limit runs it only 3 times, then the
# graph ends with the breach recorded and the refund left unresolved with no ticket. (base)
def test_refund_agent_exceeding_tool_limit_ends_conversation(monkeypatch, tmp_path):
    db_path = _use_tmp_db(monkeypatch, tmp_path)
    order_id = _seed_order(db_path)
    _mock_router(monkeypatch, "refund")
    refund_llm = _fake_agent_llm(
        [_tool_call("lookup_order", {"order_id": order_id}, f"call_{i}") for i in range(6)]
    )
    monkeypatch.setattr(refund_agent, "_build_llm", lambda: refund_llm)

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    result = graph.invoke(initial_state("I never got my mapo tofu"), config)

    assert "__interrupt__" not in result
    assert result["tool_limit_reached"] == {"agent": "refund", "tool": "lookup_order"}
    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 3
    assert result["refund_resolved"] is False
    assert result.get("refund_ticket") is None
