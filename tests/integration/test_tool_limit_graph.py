import uuid

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from customer_support_fde.graph import build_graph
from customer_support_fde.nodes import order_support_agent, refund_agent
from customer_support_fde.state import initial_state

from _graph_fakes import (
    fake_agent_llm,
    mock_router,
    order_initial_state,
    seed_order,
    tool_call,
    tool_messages,
    use_tmp_db,
)


# An order agent that calls get_menu over the limit runs it only 3 times, then the graph
# ends with the breach recorded and no order confirmed or ticket written. (failure)
def test_order_agent_exceeding_tool_limit_ends_conversation(monkeypatch, tmp_path):
    use_tmp_db(monkeypatch, tmp_path)
    mock_router(monkeypatch, "order_support")
    order_llm = fake_agent_llm(
        [tool_call("get_menu", {}, f"call_{i}") for i in range(6)]
    )
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: order_llm)

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    result = graph.invoke(order_initial_state("What's on the menu?"), config)
    assert "__interrupt__" in result
    # Continue without an account.
    result = graph.invoke(Command(resume="2"), config)

    assert "__interrupt__" not in result
    assert result["tool_limit_reached"] == {"agent": "order_support", "tool": "get_menu"}
    messages = tool_messages(result)
    assert len(messages) == 3
    assert result["order_confirmed"] is False
    assert result.get("order_ticket") is None
    tickets_dir = tmp_path / "tickets"
    assert not tickets_dir.exists() or not any(tickets_dir.iterdir())


# Three get_menu steps before replying don't trip the limit, and the count resets on the
# customer's reply so three more in the next turn don't trip it either. (edge, regression)
def test_three_same_tool_steps_per_turn_do_not_trip_limit(monkeypatch, tmp_path):
    use_tmp_db(monkeypatch, tmp_path)
    mock_router(monkeypatch, "order_support")
    order_llm = fake_agent_llm(
        [tool_call("get_menu", {}, f"call_a{i}") for i in range(3)]
        + [AIMessage(content="Here's the menu.")]
        + [tool_call("get_menu", {}, f"call_b{i}") for i in range(3)]
        + [AIMessage(content="Here it is again.")]
    )
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: order_llm)

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    graph.invoke(order_initial_state("What's on the menu?"), config)
    # Continue without an account.
    result = graph.invoke(Command(resume="2"), config)
    assert "__interrupt__" in result
    assert result.get("tool_limit_reached") is None

    result = graph.invoke(Command(resume="Can you show me the menu again?"), config)
    assert "__interrupt__" in result
    assert result.get("tool_limit_reached") is None
    messages = tool_messages(result)
    assert len(messages) == 6


# A refund agent that calls lookup_order over the limit runs it only 3 times, then the
# graph ends with the breach recorded and the refund left unresolved with no ticket. (failure)
def test_refund_agent_exceeding_tool_limit_ends_conversation(monkeypatch, tmp_path):
    db_path = use_tmp_db(monkeypatch, tmp_path)
    order_id = seed_order(db_path)
    mock_router(monkeypatch, "refund")
    refund_llm = fake_agent_llm(
        [tool_call("lookup_order", {"order_id": order_id}, f"call_{i}") for i in range(6)]
    )
    monkeypatch.setattr(refund_agent, "_build_llm", lambda: refund_llm)

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    result = graph.invoke(initial_state("I never got my mapo tofu"), config)

    assert "__interrupt__" not in result
    assert result["tool_limit_reached"] == {"agent": "refund", "tool": "lookup_order"}
    messages = tool_messages(result)
    assert len(messages) == 3
    assert result["refund_resolved"] is False
    assert result.get("refund_ticket") is None
