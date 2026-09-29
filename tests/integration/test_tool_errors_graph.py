import uuid
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from customer_support_fde import db
from customer_support_fde.graph import build_graph
from customer_support_fde.nodes import order_support_agent, refund_agent, router_agent
from customer_support_fde.nodes.common import TOOL_ERROR_MESSAGE
from customer_support_fde.nodes.router_agent import RouterDecision
from customer_support_fde.tools import menu_tools

SAMPLE_MENU = [
    {
        "name": "Kung Pao Chicken",
        "price": 12.95,
        "ingredients": ["chicken", "peanuts", "dried chili"],
    },
]

INTERNAL_DETAIL = "internal-detail-do-not-leak"


def _fake_router_llm(destination: str) -> MagicMock:
    llm = MagicMock()
    llm.invoke.return_value = RouterDecision(destination=destination, sentiment="neutral")
    return llm


def _fake_agent_llm(responses: list[AIMessage]) -> tuple[MagicMock, MagicMock]:
    bound = MagicMock()
    bound.invoke.side_effect = responses
    llm = MagicMock()
    llm.bind_tools.return_value = bound
    return llm, bound


def _tool_call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def _initial_state(query: str) -> dict:
    return {
        "user_query": query,
        "destination": "order_support",
        "sentiment": None,
        "messages": [],
        "menu": SAMPLE_MENU,
        "cart_items": {},
        "order_confirmed": False,
        "order_ticket": None,
        "order_summary": None,
        "order_id": None,
        "order_lookup": None,
        "refund_resolved": False,
        "refund_request": None,
        "complaint_ids": {},
        "refund_ticket": None,
        "order_conversation_summary": None,
        "refund_conversation_summary": None,
        "account_number": None,
        "account_preferences": None,
        "tool_limit_reached": None,
    }


def _use_tmp_db(monkeypatch, tmp_path):
    path = tmp_path / "test.db"
    db.init_database(path)
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(path))
    return path


def _last_tool_message(bound: MagicMock, call_index: int) -> ToolMessage:
    messages = bound.invoke.call_args_list[call_index].args[0]
    return next(m for m in reversed(messages) if isinstance(m, ToolMessage))


def _start_order_conversation(monkeypatch, tmp_path, responses):
    _use_tmp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(
        router_agent, "_build_llm", lambda: _fake_router_llm("order_support")
    )
    llm, bound = _fake_agent_llm(responses)
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: llm)
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    graph.invoke(_initial_state("I'd like to order"), config)
    # Continue without an account, so the next step is the order agent.
    result = graph.invoke(Command(resume="2"), config)
    return result, bound


# Tool-call arguments that don't match the tool's schema are returned to the order
# agent as an error ToolMessage, and the agent gets to recover with a normal reply
# instead of the graph crashing. (error)
def test_order_tool_invalid_args_are_reported_back_to_the_agent(monkeypatch, tmp_path):
    result, bound = _start_order_conversation(
        monkeypatch,
        tmp_path,
        [
            _tool_call("add_items_to_cart", {"items": "two kung pao please"}, "call_1"),
            AIMessage(content="Sorry, how many would you like?"),
        ],
    )

    assert result["__interrupt__"][0].value == "Sorry, how many would you like?"
    tool_message = _last_tool_message(bound, 1)
    assert tool_message.tool_call_id == "call_1"
    assert tool_message.status == "error"


def _raise_internal_error(*_args, **_kwargs):
    raise RuntimeError(INTERNAL_DETAIL)


def _tool_messages(result) -> list[ToolMessage]:
    return [m for m in result["messages"] if isinstance(m, ToolMessage)]


def _fail_once(real):
    # Raises on the first call, then behaves like the real function.
    calls = {"n": 0}

    def _flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            _raise_internal_error()
        return real(*args, **kwargs)

    return _flaky


# A single unexpected exception inside an order tool is sent back to the order agent
# only as the fixed retry instruction (no internal details); the agent retries the
# same call, it succeeds, and the conversation carries on with no warning. (error)
def test_order_tool_single_exception_is_retried_by_the_agent(monkeypatch, tmp_path):
    monkeypatch.setattr(
        menu_tools, "resolve_menu_item", _fail_once(menu_tools.resolve_menu_item)
    )
    result, bound = _start_order_conversation(
        monkeypatch,
        tmp_path,
        [
            _tool_call("get_menu_item", {"name": "kung pao"}, "call_1"),
            _tool_call("get_menu_item", {"name": "kung pao"}, "call_2"),
            AIMessage(content="Kung Pao Chicken is $12.95."),
        ],
    )

    assert result["__interrupt__"][0].value == "Kung Pao Chicken is $12.95."
    assert result.get("tool_limit_reached") is None
    failed = _last_tool_message(bound, 1)
    assert failed.tool_call_id == "call_1"
    assert failed.status == "error"
    assert failed.content == TOOL_ERROR_MESSAGE
    retried = _last_tool_message(bound, 2)
    assert retried.tool_call_id == "call_2"
    assert retried.status != "error"
    assert "Kung Pao Chicken" in retried.content


# An order agent that keeps retrying a tool that keeps raising is stopped by the
# tool limit: the tool runs 3 times (each an error ToolMessage), then the graph ends
# with tool_limit_reached recorded so the CLI shows its warning. (error)
def test_order_tool_repeated_exceptions_end_at_tool_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(menu_tools, "resolve_menu_item", _raise_internal_error)
    result, _bound = _start_order_conversation(
        monkeypatch,
        tmp_path,
        [_tool_call("get_menu_item", {"name": "kung pao"}, f"call_{i}") for i in range(6)],
    )

    assert "__interrupt__" not in result
    assert result["tool_limit_reached"] == {
        "agent": "order_support",
        "tool": "get_menu_item",
    }
    tool_messages = _tool_messages(result)
    assert len(tool_messages) == 3
    assert all(m.status == "error" for m in tool_messages)
    assert all(m.content == TOOL_ERROR_MESSAGE for m in tool_messages)
    assert result.get("order_ticket") is None


def _start_refund_conversation(monkeypatch, tmp_path, responses):
    _use_tmp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(db, "get_order", _raise_internal_error)
    monkeypatch.setattr(router_agent, "_build_llm", lambda: _fake_router_llm("refund"))
    llm, bound = _fake_agent_llm(responses)
    monkeypatch.setattr(refund_agent, "_build_llm", lambda: llm)
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    result = graph.invoke(_initial_state("I never got my order K7QP3M9X"), config)
    return result, bound


# A single unexpected exception inside a refund tool is sent back to the refund agent
# only as the fixed retry instruction (no internal details); the agent retries the
# same call, it succeeds, and the conversation carries on with no warning. (error)
def test_refund_tool_single_exception_is_retried_by_the_agent(monkeypatch, tmp_path):
    db_path = _use_tmp_db(monkeypatch, tmp_path)
    order_id = db.record_order(
        {
            "lines": [
                {
                    "name": "Kung Pao Chicken",
                    "quantity": 1,
                    "unit_price": 12.95,
                    "line_total": 12.95,
                }
            ],
            "total": 12.95,
        },
        db_path,
    )
    monkeypatch.setattr(db, "get_order", _fail_once(db.get_order))
    monkeypatch.setattr(router_agent, "_build_llm", lambda: _fake_router_llm("refund"))
    llm, bound = _fake_agent_llm(
        [
            _tool_call("lookup_order", {"order_id": order_id}, "call_1"),
            _tool_call("lookup_order", {"order_id": order_id}, "call_2"),
            AIMessage(content="I found your order. What went wrong?"),
        ]
    )
    monkeypatch.setattr(refund_agent, "_build_llm", lambda: llm)
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    result = graph.invoke(_initial_state(f"I never got my order {order_id}"), config)

    assert result["__interrupt__"][0].value == "I found your order. What went wrong?"
    assert result.get("tool_limit_reached") is None
    assert result["order_lookup"]["order_id"] == order_id
    failed = _last_tool_message(bound, 1)
    assert failed.tool_call_id == "call_1"
    assert failed.status == "error"
    assert failed.content == TOOL_ERROR_MESSAGE


# A refund agent that keeps retrying a tool that keeps raising is stopped by the
# tool limit: the tool runs 3 times (each an error ToolMessage), then the graph ends
# with tool_limit_reached recorded and no refund ticket written. (error)
def test_refund_tool_repeated_exceptions_end_at_tool_limit(monkeypatch, tmp_path):
    result, _bound = _start_refund_conversation(
        monkeypatch,
        tmp_path,
        [_tool_call("lookup_order", {"order_id": "K7QP3M9X"}, f"call_{i}") for i in range(6)],
    )

    assert "__interrupt__" not in result
    assert result["tool_limit_reached"] == {"agent": "refund", "tool": "lookup_order"}
    tool_messages = _tool_messages(result)
    assert len(tool_messages) == 3
    assert all(m.status == "error" for m in tool_messages)
    assert all(m.content == TOOL_ERROR_MESSAGE for m in tool_messages)
    assert result.get("refund_ticket") is None
