import io
import logging
from itertools import count

import pytest

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage

from customer_support_fde import interactive, messages
from customer_support_fde.nodes.tool_limit import (
    MAX_CONSECUTIVE_TOOL_CALLS,
    find_repeated_tool,
    route_after_agent,
    tool_limit_node,
)

from _cli_fakes import record_warnings

_call_ids = count(1)


def _step(*tool_names: str) -> list[AnyMessage]:
    # One agent step requesting the given tools, followed by a ToolMessage per call.
    ids = [f"call_{next(_call_ids)}" for _ in tool_names]
    request = AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": {}, "id": call_id}
            for name, call_id in zip(tool_names, ids)
        ],
    )
    return [request] + [ToolMessage(content="ok", tool_call_id=call_id) for call_id in ids]


def _pending(*tool_names: str) -> list[AnyMessage]:
    # The newest agent step, whose tool calls have not run yet.
    return _step(*tool_names)[:1]


def _history(*steps: list[AnyMessage]) -> list[AnyMessage]:
    messages: list[AnyMessage] = [HumanMessage(content="hi")]
    for step in steps:
        messages.extend(step)
    return messages


def _exceeding_limit(tool_name: str) -> list[AnyMessage]:
    # A turn where the agent has called tool_name 3 times in a row and asks for a 4th.
    return _history(
        _step(tool_name), _step(tool_name), _step(tool_name), _pending(tool_name)
    )


# The limit is 3 consecutive calls to the same tool. (base)
def test_max_consecutive_tool_calls_is_three():
    assert MAX_CONSECUTIVE_TOOL_CALLS == 3


# A 4th consecutive get_menu call exceeds the limit of 3 and is reported. (base)
def test_fourth_consecutive_get_menu_exceeds_limit():
    messages = _history(
        _step("get_menu"),  # 1
        _step("get_menu"),  # 2
        _step("get_menu"),  # 3
        _pending("get_menu"),  # 4: over the limit
    )

    assert find_repeated_tool(messages) == "get_menu"


# A 4th consecutive call still exceeds the limit when bundled with another tool in one step. (edge)
def test_fourth_consecutive_call_exceeds_limit_when_bundled_with_another_tool():
    messages = _history(
        _step("get_menu"),
        _step("get_menu"),
        _step("get_menu"),
        _pending("get_menu", "get_cart"),
    )

    assert find_repeated_tool(messages) == "get_menu"


# When several tools in the newest step are over the limit, the first in tool_calls order is reported. (edge)
def test_first_over_limit_tool_in_call_order_is_reported():
    both = ("get_cart", "get_menu")
    messages = _history(_step(*both), _step(*both), _step(*both), _pending(*both))

    assert find_repeated_tool(messages) == "get_cart"


# route_after_agent sends a call over the limit to the tool-limit node instead of the tools. (base)
def test_route_after_agent_routes_call_over_limit_to_tool_limit():
    messages = _exceeding_limit("get_menu")

    assert route_after_agent({"messages": messages}) == "tool_limit"


# route_after_agent sends a first tool request to the tool node. (base)
def test_route_after_agent_routes_first_tool_call_to_tools():
    messages = _history(_pending("get_menu"))

    assert route_after_agent({"messages": messages}) == "tools"


# route_after_agent ends the agent loop when the newest message has no tool calls. (base)
def test_route_after_agent_routes_plain_reply_to_end():
    messages = _history(_step("get_menu")) + [AIMessage(content="Here's the menu.")]

    assert route_after_agent({"messages": messages}) == "__end__"


# Histories that must NOT trip the limit: plain replies, exactly 3 in a row, runs broken
# by another tool, parallel calls in one step, and repeats across customer turns. (edge)
@pytest.mark.parametrize(
    "messages",
    [
        pytest.param(
            _history(_step("get_menu")) + [AIMessage(content="Here's the menu.")],
            id="newest-is-plain-reply",
        ),
        pytest.param(
            _history(_step("get_menu"), _step("get_menu"), _pending("get_menu")),
            id="three-in-a-row",
        ),
        pytest.param(
            _history(
                _step("get_menu"),
                _step("get_menu"),
                _step("get_menu"),
                _step("get_cart"),
                _pending("get_menu"),
            ),
            id="run-broken-by-another-tool",
        ),
        pytest.param(
            _history(_pending(*["add_items_to_cart"] * 4)),
            id="parallel-calls-in-one-step",
        ),
        pytest.param(
            _history(_step("lookup_order"), _step("lookup_order"), _step("lookup_order"))
            + [HumanMessage(content="it was order 42")]
            + _pending("lookup_order"),
            id="customer-reply-resets-count",
        ),
    ],
)
def test_find_repeated_tool_allows_legitimate_histories(messages):
    assert find_repeated_tool(messages) is None


# ToolMessages between steps do not change the result. (edge)
def test_tool_messages_between_steps_do_not_affect_result():
    with_results = _exceeding_limit("get_menu")
    without_results = [m for m in with_results if not isinstance(m, ToolMessage)]

    assert find_repeated_tool(with_results) == find_repeated_tool(without_results)


# tool_limit_node names the right agent and tool on both paths, which is what the
# Phoenix span for this node records. (base)
@pytest.mark.parametrize(
    ("destination", "tool"),
    [("refund", "lookup_order"), ("order_support", "add_items_to_cart")],
)
def test_tool_limit_node_records_which_agent_and_tool_exceeded_limit(destination, tool):
    messages = _exceeding_limit(tool)

    result = tool_limit_node({"destination": destination, "messages": messages})

    assert result == {"tool_limit_reached": {"agent": destination, "tool": tool}}


_TOOL_LIMIT_STATE = {
    "destination": "order_support",
    "user_query": "hi",
    "sentiment": None,
    "order_confirmed": False,
    "tool_limit_reached": {"agent": "order_support", "tool": "get_menu"},
    "messages": [
        AIMessage(
            content="", tool_calls=[{"name": "get_menu", "args": {}, "id": "call_1"}]
        )
    ],
}


# When a conversation exceeds the tool limit, only the generic message is shown, the
# CLI waits for Enter and exits with code 1, and the tool-limit details are logged at
# ERROR for Phoenix rather than printed. (base)
def test_run_interactive_shows_generic_message_and_exits_when_tool_limit_exceeded(
    monkeypatch, capsys, caplog
):
    warnings = record_warnings(monkeypatch)
    monkeypatch.setattr(interactive, "build_graph", lambda checkpointer: object())
    monkeypatch.setattr(
        interactive, "_run_conversation", lambda console, graph, query: _TOOL_LIMIT_STATE
    )
    stdin = io.StringIO("hi\n\nsecond question\n")
    monkeypatch.setattr(interactive.sys, "stdin", stdin)

    with caplog.at_level(logging.ERROR, logger="customer_support_fde.interactive"):
        exit_code = interactive.run_interactive()

    assert exit_code == 1
    assert warnings == [messages.GENERIC_ERROR_MESSAGE]
    captured = capsys.readouterr()
    assert "Press Enter to exit." in captured.out
    assert "get_menu" not in captured.out
    assert stdin.read() == "second question\n"
    logged = [r for r in caplog.records if r.name == "customer_support_fde.interactive"]
    assert len(logged) == 1
    assert "get_menu" in logged[0].getMessage()


# tool_limit_node logs a warning naming the agent and the repeated tool, so the
# runaway loop is visible in Phoenix. (base)
def test_tool_limit_node_logs_agent_and_tool(caplog):
    messages_so_far = [HumanMessage(content="hi")]
    for _ in range(MAX_CONSECUTIVE_TOOL_CALLS):
        messages_so_far += _step("get_menu")
    messages_so_far += _step("get_menu")[:1]
    state = {"destination": "order_support", "messages": messages_so_far}

    with caplog.at_level(logging.WARNING, logger="customer_support_fde.nodes.tool_limit"):
        tool_limit_node(state)

    logged = [
        r for r in caplog.records if r.name == "customer_support_fde.nodes.tool_limit"
    ]
    assert len(logged) == 1
    assert "order_support" in logged[0].getMessage()
    assert "get_menu" in logged[0].getMessage()
