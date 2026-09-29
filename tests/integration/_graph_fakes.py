"""Shared fakes for integration tests that drive the compiled graph with scripted LLMs."""

import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, ToolMessage

from customer_support_fde import db
from customer_support_fde.nodes import router_agent
from customer_support_fde.nodes.router_agent import RouterDecision
from customer_support_fde.state import initial_state

SAMPLE_MENU = [
    {
        "name": "Kung Pao Chicken",
        "price": 12.95,
        "ingredients": ["chicken", "peanuts", "dried chili"],
    },
]


def mock_router(monkeypatch, destination: str) -> None:
    llm = MagicMock()
    llm.invoke.return_value = RouterDecision(destination=destination, sentiment="neutral")
    monkeypatch.setattr(router_agent, "_build_llm", lambda: llm)


def fake_agent_llm(responses: list[AIMessage]) -> MagicMock:
    # The scripted replies come from llm.bind_tools(...).invoke; tests that inspect
    # what the agent was sent read llm.bind_tools.return_value.invoke.call_args_list.
    bound = MagicMock()
    bound.invoke.side_effect = responses
    llm = MagicMock()
    llm.bind_tools.return_value = bound
    return llm


def tool_call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def tool_messages(result) -> list[ToolMessage]:
    return [m for m in result["messages"] if isinstance(m, ToolMessage)]


def use_tmp_db(monkeypatch, tmp_path):
    path = tmp_path / "test.db"
    db.init_database(path)
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(path))
    return path


def order_initial_state(user_query: str) -> dict:
    return {**initial_state(user_query), "menu": SAMPLE_MENU}


def seed_order(db_path, age_hours=1) -> str:
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
