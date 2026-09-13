import os

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
)
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

REFUND_HISTORY_TOKEN_THRESHOLD = 20_000

_CONDENSATION_INSTRUCTIONS = """\
Summarize the refund conversation that follows into a concise summary for \
your own future reference. For each order discussed, you MUST preserve: the \
order identified, the facts gathered toward a policy decision (which dishes \
were missing, whether a substitute arrived, and any return commitment given \
or declined), the customer's complaint description, and any policy decision \
already reached. If the conversation discussed more than one order, keep \
each order's facts and outcome distinct rather than merging them together. \
If the customer restated a fact, keep only their most recent statement, not \
the outdated one. Reply with only the summary text, no greeting or \
meta-commentary.
"""


def _build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ.get("OPENROUTER_API_KEY"),
        model=os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL),
    )


def _estimate_token_count(messages: list[AnyMessage]) -> int:
    # get_num_tokens_from_messages() raises NotImplementedError for OpenRouter-style
    # "vendor/model" names regardless of the underlying model, so estimate from the
    # last real reply's provider-reported prompt size instead, falling back to a
    # rough per-character estimate before any usage data exists.
    for message in reversed(messages):
        if isinstance(message, AIMessage) and message.usage_metadata:
            return message.usage_metadata.get("input_tokens", 0)
    return sum(len(str(message.content)) for message in messages) // 4


def _build_context_messages(state: SupportState) -> list[AnyMessage]:
    context: list[AnyMessage] = [SystemMessage(content=SYSTEM_PROMPT)]
    sentiment = state.get("sentiment")
    if sentiment is not None:
        context.append(
            SystemMessage(content=f"Customer sentiment reading: {sentiment}.")
        )
    summary = state.get("refund_conversation_summary")
    if summary is not None:
        context.append(
            SystemMessage(content=f"Summary of earlier conversation:\n{summary}")
        )
    return context


def refund_agent(state: SupportState) -> SupportState:
    messages = (
        state["messages"] if state["messages"] else [HumanMessage(content=state["user_query"])]
    )

    llm = _build_llm()
    removals: list[AnyMessage] = []

    human_indices = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage)]
    if len(human_indices) > 3:
        token_count = _estimate_token_count(_build_context_messages(state) + messages)
        if token_count > REFUND_HISTORY_TOKEN_THRESHOLD:
            cutoff = human_indices[-3]
            older_messages = messages[:cutoff]
            try:
                condense_input: list[AnyMessage] = [
                    SystemMessage(content=_CONDENSATION_INSTRUCTIONS)
                ]
                previous_summary = state.get("refund_conversation_summary")
                if previous_summary is not None:
                    condense_input.append(
                        SystemMessage(content=f"Previous summary:\n{previous_summary}")
                    )
                condense_input.extend(older_messages)
                new_summary = llm.invoke(condense_input).content
            except Exception:
                pass
            else:
                state = {**state, "refund_conversation_summary": new_summary}
                removals = [RemoveMessage(id=m.id) for m in older_messages]
                messages = messages[cutoff:]

    context = _build_context_messages(state)
    ai_message = llm.bind_tools(_REFUND_TOOLS).invoke(context + messages)

    return {**state, "messages": removals + messages + [ai_message]}


def refund_await_customer(state: SupportState) -> SupportState:
    if state["refund_resolved"]:
        return state

    last_message = state["messages"][-1]
    answer = interrupt(last_message.content)
    return {
        **state,
        "messages": state["messages"] + [HumanMessage(content=str(answer))],
    }
