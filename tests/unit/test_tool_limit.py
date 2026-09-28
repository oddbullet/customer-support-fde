from itertools import count

import pytest

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage

from customer_support_fde.nodes.tool_limit import (
    MAX_CONSECUTIVE_TOOL_CALLS,
    find_repeated_tool,
    route_after_agent,
    tool_limit_node,
)

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


# The limit is 3 consecutive calls to the same tool. (base)
def test_max_consecutive_tool_calls_is_three():
    assert MAX_CONSECUTIVE_TOOL_CALLS == 3


# A 4th consecutive step calling the same tool is reported as repeated. (base)
def test_fourth_consecutive_call_to_same_tool_is_repeated():
    messages = _history(
        _step("get_menu"), _step("get_menu"), _step("get_menu"), _pending("get_menu")
    )

    assert find_repeated_tool(messages) == "get_menu"


# A 4th consecutive call still trips the limit when bundled with another tool in one step. (edge)
def test_fourth_consecutive_call_bundled_with_another_tool_is_repeated():
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


# route_after_agent sends a 4th consecutive same-tool request to the tool-limit node. (base)
def test_route_after_agent_routes_repeated_tool_to_tool_limit():
    messages = _history(
        _step("get_menu"), _step("get_menu"), _step("get_menu"), _pending("get_menu")
    )

    assert route_after_agent({"messages": messages}) == "tool_limit"


# route_after_agent sends a first tool request to the tool node. (base)
def test_route_after_agent_routes_first_tool_call_to_tools():
    messages = _history(_pending("get_menu"))

    assert route_after_agent({"messages": messages}) == "tools"


# route_after_agent ends the agent loop when the newest message has no tool calls. (base)
def test_route_after_agent_routes_plain_reply_to_end():
    messages = _history(_step("get_menu")) + [AIMessage(content="Here's the menu.")]

    assert route_after_agent({"messages": messages}) == "__end__"


# tool_limit_node records the agent and the repeated tool. (base)
def test_tool_limit_node_records_agent_and_tool():
    messages = _history(
        _step("get_menu"), _step("get_menu"), _step("get_menu"), _pending("get_menu")
    )

    result = tool_limit_node({"destination": "order_support", "messages": messages})

    assert result == {
        "tool_limit_reached": {"agent": "order_support", "tool": "get_menu"}
    }


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
    with_results = _history(
        _step("get_menu"), _step("get_menu"), _step("get_menu"), _pending("get_menu")
    )
    without_results = [m for m in with_results if not isinstance(m, ToolMessage)]

    assert find_repeated_tool(with_results) == find_repeated_tool(without_results)


# tool_limit_node names the right agent and tool on both paths, which is what the
# Phoenix span for this node records. (base)
@pytest.mark.parametrize(
    ("destination", "tool"),
    [("refund", "lookup_order"), ("order_support", "add_items_to_cart")],
)
def test_tool_limit_node_reports_agent_and_tool_per_path(destination, tool):
    messages = _history(_step(tool), _step(tool), _step(tool), _pending(tool))

    result = tool_limit_node({"destination": destination, "messages": messages})

    assert result == {"tool_limit_reached": {"agent": destination, "tool": tool}}
