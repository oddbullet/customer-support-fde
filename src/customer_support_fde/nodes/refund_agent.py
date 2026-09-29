from langchain_core.messages import (
    AnyMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
)
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt

from customer_support_fde.nodes.common import HISTORY_TOKEN_THRESHOLD
from customer_support_fde.nodes.common import build_llm as _build_llm
from customer_support_fde.nodes.common import condense_messages
from customer_support_fde.nodes.common import handle_tool_error
from customer_support_fde.nodes.common import estimate_token_count as _estimate_token_count
from customer_support_fde.state import SupportState
from customer_support_fde.tools.refund_tools import (
    conclude_refund_conversation,
    log_complaint,
    lookup_order,
    process_refund_request,
)

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

When the tool denies the request, never describe a denial with words like \
"processed," "submitted," or "approved" — those imply a refund went \
through even if the rest of the sentence says otherwise. Introduce a \
denial neutrally (for example, "I checked this against our refund \
policy") and then relay the tool's message plainly.

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

refund_tools = ToolNode(_REFUND_TOOLS, handle_tool_errors=handle_tool_error)

REFUND_HISTORY_TOKEN_THRESHOLD = HISTORY_TOKEN_THRESHOLD

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
            new_summary = condense_messages(
                llm,
                older_messages,
                _CONDENSATION_INSTRUCTIONS,
                state.get("refund_conversation_summary"),
            )
            if new_summary is not None:
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
