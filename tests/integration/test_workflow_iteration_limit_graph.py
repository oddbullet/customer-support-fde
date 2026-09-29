import uuid
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphRecursionError

from customer_support_fde import db, interactive
from customer_support_fde.graph import build_graph
from customer_support_fde.nodes import refund_agent, router_agent
from customer_support_fde.nodes.router_agent import RouterDecision
from customer_support_fde.state import initial_state

# Far more tool steps than the iteration limit allows, then a plain reply that would
# end the turn normally if the limit were not enforced.
_SCRIPTED_TOOL_STEPS = 200


def _alternating_tool_calls() -> list[AIMessage]:
    # Alternating tools never repeat one tool consecutively, so tool_limit_node
    # never trips and only the iteration limit can stop the loop.
    steps = []
    for i in range(_SCRIPTED_TOOL_STEPS):
        if i % 2 == 0:
            call = {"name": "lookup_order", "args": {"order_id": "X"}, "id": f"call_{i}"}
        else:
            call = {"name": "log_complaint", "args": {"description": "late"}, "id": f"call_{i}"}
        steps.append(AIMessage(content="", tool_calls=[call]))
    return steps + [AIMessage(content="Anything else?")]


# A refund agent looping between two different tools within one customer turn is
# stopped by the workflow iteration limit: the real graph raises GraphRecursionError
# after roughly WORKFLOW_ITERATION_LIMIT / 2 agent steps, long before the script runs
# out. (error)
def test_runaway_tool_loop_is_stopped_by_iteration_limit(monkeypatch, tmp_path):
    db_path = tmp_path / "test.db"
    db.init_database(db_path)
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(db_path))

    router_llm = MagicMock()
    router_llm.invoke.return_value = RouterDecision(destination="refund", sentiment="neutral")
    monkeypatch.setattr(router_agent, "_build_llm", lambda: router_llm)

    bound = MagicMock()
    bound.invoke.side_effect = _alternating_tool_calls()
    refund_llm = MagicMock()
    refund_llm.bind_tools.return_value = bound
    monkeypatch.setattr(refund_agent, "_build_llm", lambda: refund_llm)

    graph = build_graph(checkpointer=MemorySaver())
    config = {
        "configurable": {"thread_id": str(uuid.uuid4())},
        "recursion_limit": interactive.WORKFLOW_ITERATION_LIMIT,
    }

    with pytest.raises(GraphRecursionError):
        graph.invoke(initial_state("My order was late"), config)

    # Each loop is two steps (refund_agent, then refund_tools), so the agent runs
    # about half the limit's worth of times and never reaches the final reply.
    agent_calls = bound.invoke.call_count
    assert interactive.WORKFLOW_ITERATION_LIMIT // 2 - 5 <= agent_calls
    assert agent_calls <= interactive.WORKFLOW_ITERATION_LIMIT // 2 + 1
