import os

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt

from customer_support_fde.state import SupportState
from customer_support_fde.tools.refund_tools import (
    conclude_refund_conversation,
    log_complaint,
    lookup_order,
    process_refund_request,
)

DEFAULT_MODEL = "openai/gpt-4o-mini"

SYSTEM_PROMPT = """\
You are the refund and complaints agent for a Chinese restaurant. A customer \
is reaching out about a past order.

Before anything else, get the order id and call lookup_order to pull up that \
order — never evaluate a refund without having looked the order up first.

Once you have the order, gather the facts the refund policy needs: which of \
the ordered dishes the customer did not receive, whether a substitute dish \
arrived in its place, and — only when a substitute did arrive — whether the \
customer will bring it back. When nothing arrived in place of a missing \
dish, there is nothing to return, so do not ask for a return commitment in \
that case.

Once you have what you need, call process_refund_request to apply the \
refund policy and record the outcome. You never decide eligibility \
yourself — always call the tool and relay what it reports, without \
restating amounts or verdicts in your own words beyond what the tool told \
you.

If the customer voices dissatisfaction without asking for a refund, call \
log_complaint instead.

When the conversation has reached an outcome (a refund was submitted, a \
request was denied, or a complaint was logged) and the customer has nothing \
more to add, call conclude_refund_conversation.

Adjust your tone to the situation: when the customer's sentiment is \
negative, respond with extra care and patience. This never changes the \
policy outcome — only how you say it.
"""

_REFUND_TOOLS = [
    lookup_order,
    process_refund_request,
    log_complaint,
    conclude_refund_conversation,
]

refund_tools = ToolNode(_REFUND_TOOLS)


def _build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ.get("OPENROUTER_API_KEY"),
        model=os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL),
    )


def _seed_messages(state: SupportState) -> list[AnyMessage]:
    seeded: list[AnyMessage] = [SystemMessage(content=SYSTEM_PROMPT)]
    sentiment = state.get("sentiment")
    if sentiment is not None:
        seeded.append(
            SystemMessage(content=f"Customer sentiment reading: {sentiment}.")
        )
    seeded.append(HumanMessage(content=state["user_query"]))
    return seeded


def refund_agent(state: SupportState) -> SupportState:
    messages = state["messages"] if state["messages"] else _seed_messages(state)

    ai_message = _build_llm().bind_tools(_REFUND_TOOLS).invoke(messages)

    return {**state, "messages": messages + [ai_message]}


def refund_await_customer(state: SupportState) -> SupportState:
    if state["refund_resolved"]:
        return state

    last_message = state["messages"][-1]
    answer = interrupt(last_message.content)
    return {
        **state,
        "messages": state["messages"] + [HumanMessage(content=str(answer))],
    }
