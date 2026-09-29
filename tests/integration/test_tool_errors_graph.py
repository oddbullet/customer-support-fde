import uuid

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from customer_support_fde import db
from customer_support_fde.graph import build_graph
from customer_support_fde.nodes import order_support_agent, refund_agent
from customer_support_fde.nodes.common import TOOL_ERROR_MESSAGE
from customer_support_fde.state import initial_state
from customer_support_fde.tools import menu_tools

from _graph_fakes import (
    fake_agent_llm,
    mock_router,
    order_initial_state,
    seed_order,
    tool_call,
    tool_messages,
    use_tmp_db,
)

INTERNAL_DETAIL = "internal-detail-do-not-leak"


def _raise_internal_error(*_args, **_kwargs):
    raise RuntimeError(INTERNAL_DETAIL)


def _fail_once(real):
    # Raises on the first call, then behaves like the real function.
    calls = {"n": 0}

    def _flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            _raise_internal_error()
        return real(*args, **kwargs)

    return _flaky


def _sent_tool_message(llm, call_index: int) -> ToolMessage:
    # The latest ToolMessage in what the agent was sent on its call_index-th call.
    messages = llm.bind_tools.return_value.invoke.call_args_list[call_index].args[0]
    return next(m for m in reversed(messages) if isinstance(m, ToolMessage))


def _assert_retry_instruction(message: ToolMessage, call_id: str) -> None:
    assert message.tool_call_id == call_id
    assert message.status == "error"
    assert message.content == TOOL_ERROR_MESSAGE


def _assert_ended_at_tool_limit(result, agent: str, tool: str) -> None:
    assert "__interrupt__" not in result
    assert result["tool_limit_reached"] == {"agent": agent, "tool": tool}
    messages = tool_messages(result)
    assert len(messages) == 3
    assert all(m.status == "error" for m in messages)
    assert all(m.content == TOOL_ERROR_MESSAGE for m in messages)


def _start_order_conversation(monkeypatch, tmp_path, responses):
    use_tmp_db(monkeypatch, tmp_path)
    mock_router(monkeypatch, "order_support")
    llm = fake_agent_llm(responses)
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: llm)
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    graph.invoke(order_initial_state("I'd like to order"), config)
    # Continue without an account, so the next step is the order agent.
    result = graph.invoke(Command(resume="2"), config)
    return result, llm


def _start_refund_conversation(monkeypatch, query, responses):
    mock_router(monkeypatch, "refund")
    llm = fake_agent_llm(responses)
    monkeypatch.setattr(refund_agent, "_build_llm", lambda: llm)
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    result = graph.invoke(initial_state(query), config)
    return result, llm


# Tool-call arguments that don't match the tool's schema are returned to the order
# agent as an error ToolMessage, and the agent gets to recover with a normal reply
# instead of the graph crashing. (error)
def test_order_tool_invalid_args_are_reported_back_to_the_agent(monkeypatch, tmp_path):
    result, llm = _start_order_conversation(
        monkeypatch,
        tmp_path,
        [
            tool_call("add_items_to_cart", {"items": "two kung pao please"}, "call_1"),
            AIMessage(content="Sorry, how many would you like?"),
        ],
    )

    assert result["__interrupt__"][0].value == "Sorry, how many would you like?"
    tool_message = _sent_tool_message(llm, 1)
    assert tool_message.tool_call_id == "call_1"
    assert tool_message.status == "error"


# A single unexpected exception inside an order tool is sent back to the order agent
# only as the fixed retry instruction (no internal details); the agent retries the
# same call, it succeeds, and the conversation carries on with no warning. (error)
def test_order_tool_single_exception_is_retried_by_the_agent(monkeypatch, tmp_path):
    monkeypatch.setattr(
        menu_tools, "resolve_menu_item", _fail_once(menu_tools.resolve_menu_item)
    )
    result, llm = _start_order_conversation(
        monkeypatch,
        tmp_path,
        [
            tool_call("get_menu_item", {"name": "kung pao"}, "call_1"),
            tool_call("get_menu_item", {"name": "kung pao"}, "call_2"),
            AIMessage(content="Kung Pao Chicken is $12.95."),
        ],
    )

    assert result["__interrupt__"][0].value == "Kung Pao Chicken is $12.95."
    assert result.get("tool_limit_reached") is None
    _assert_retry_instruction(_sent_tool_message(llm, 1), "call_1")
    retried = _sent_tool_message(llm, 2)
    assert retried.tool_call_id == "call_2"
    assert retried.status != "error"
    assert "Kung Pao Chicken" in retried.content


# An order agent that keeps retrying a tool that keeps raising is stopped by the
# tool limit: the tool runs 3 times (each an error ToolMessage), then the graph ends
# with tool_limit_reached recorded so the CLI shows its warning. (error)
def test_order_tool_repeated_exceptions_end_at_tool_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(menu_tools, "resolve_menu_item", _raise_internal_error)
    result, _llm = _start_order_conversation(
        monkeypatch,
        tmp_path,
        [tool_call("get_menu_item", {"name": "kung pao"}, f"call_{i}") for i in range(6)],
    )

    _assert_ended_at_tool_limit(result, "order_support", "get_menu_item")
    assert result.get("order_ticket") is None


# A single unexpected exception inside a refund tool is sent back to the refund agent
# only as the fixed retry instruction (no internal details); the agent retries the
# same call, it succeeds, and the conversation carries on with no warning. (error)
def test_refund_tool_single_exception_is_retried_by_the_agent(monkeypatch, tmp_path):
    order_id = seed_order(use_tmp_db(monkeypatch, tmp_path))
    monkeypatch.setattr(db, "get_order", _fail_once(db.get_order))

    result, llm = _start_refund_conversation(
        monkeypatch,
        f"I never got my order {order_id}",
        [
            tool_call("lookup_order", {"order_id": order_id}, "call_1"),
            tool_call("lookup_order", {"order_id": order_id}, "call_2"),
            AIMessage(content="I found your order. What went wrong?"),
        ],
    )

    assert result["__interrupt__"][0].value == "I found your order. What went wrong?"
    assert result.get("tool_limit_reached") is None
    assert result["order_lookup"]["order_id"] == order_id
    _assert_retry_instruction(_sent_tool_message(llm, 1), "call_1")


# A refund agent that keeps retrying a tool that keeps raising is stopped by the
# tool limit: the tool runs 3 times (each an error ToolMessage), then the graph ends
# with tool_limit_reached recorded and no refund ticket written. (error)
def test_refund_tool_repeated_exceptions_end_at_tool_limit(monkeypatch, tmp_path):
    use_tmp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(db, "get_order", _raise_internal_error)

    result, _llm = _start_refund_conversation(
        monkeypatch,
        "I never got my order K7QP3M9X",
        [tool_call("lookup_order", {"order_id": "K7QP3M9X"}, f"call_{i}") for i in range(6)],
    )

    _assert_ended_at_tool_limit(result, "refund", "lookup_order")
    assert result.get("refund_ticket") is None
