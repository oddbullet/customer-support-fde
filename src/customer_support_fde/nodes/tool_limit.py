import logging
from typing import Literal

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.prebuilt import tools_condition

from customer_support_fde.state import SupportState

MAX_CONSECUTIVE_TOOL_CALLS = 3

_logger = logging.getLogger(__name__)


def _current_turn_steps_newest_first(messages: list[AnyMessage]) -> list[AIMessage]:
    steps: list[AIMessage] = []
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        if isinstance(message, AIMessage) and message.tool_calls:
            steps.append(message)
    return steps


def find_repeated_tool(messages: list[AnyMessage]) -> str | None:
    newest_calls = getattr(messages[-1], "tool_calls", None) if messages else None
    if not newest_calls:
        return None

    # Parallel calls to the same tool in one step count once.
    step_tool_names = [
        {call["name"] for call in step.tool_calls}
        for step in _current_turn_steps_newest_first(messages)
    ]
    for call in newest_calls:
        name = call["name"]
        consecutive = 0
        for names in step_tool_names:
            if name not in names:
                break
            consecutive += 1
        if consecutive > MAX_CONSECUTIVE_TOOL_CALLS:
            return name
    return None


def route_after_agent(state: SupportState) -> Literal["tools", "tool_limit", "__end__"]:
    if tools_condition(state) == "__end__":
        return "__end__"
    if find_repeated_tool(state["messages"]) is not None:
        return "tool_limit"
    return "tools"


def tool_limit_node(state: SupportState) -> SupportState:
    agent = state["destination"]
    tool = find_repeated_tool(state["messages"])
    _logger.warning("Tool-call limit reached: agent=%s tool=%s", agent, tool)
    return {"tool_limit_reached": {"agent": agent, "tool": tool}}
