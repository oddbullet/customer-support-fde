from typing import Literal

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from customer_support_fde.state import SupportState

MAX_CONSECUTIVE_TOOL_CALLS = 3


def _current_turn_steps(messages: list[AnyMessage]) -> list[AIMessage]:
    steps: list[AIMessage] = []
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        if isinstance(message, AIMessage) and message.tool_calls:
            steps.append(message)
    steps.reverse()
    return steps


def find_repeated_tool(messages: list[AnyMessage]) -> str | None:
    if not messages:
        return None
    newest = messages[-1]
    if not isinstance(newest, AIMessage) or not newest.tool_calls:
        return None

    # Parallel calls to the same tool in one step count once.
    step_tool_names = [
        {call["name"] for call in step.tool_calls}
        for step in _current_turn_steps(messages)
    ]
    for call in newest.tool_calls:
        name = call["name"]
        consecutive = 0
        for names in reversed(step_tool_names):
            if name not in names:
                break
            consecutive += 1
        if consecutive > MAX_CONSECUTIVE_TOOL_CALLS:
            return name
    return None


def route_after_agent(state: SupportState) -> Literal["tools", "tool_limit", "__end__"]:
    newest = state["messages"][-1]
    if not isinstance(newest, AIMessage) or not newest.tool_calls:
        return "__end__"
    if find_repeated_tool(state["messages"]) is not None:
        return "tool_limit"
    return "tools"


def tool_limit_node(state: SupportState) -> SupportState:
    return {
        "tool_limit_reached": {
            "agent": state["destination"],
            "tool": find_repeated_tool(state["messages"]),
        }
    }
