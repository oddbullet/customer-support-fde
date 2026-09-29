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
from customer_support_fde.nodes.common import select_messages_to_condense
from customer_support_fde.nodes.common import estimate_token_count as _estimate_token_count
from customer_support_fde.state import SupportState
from customer_support_fde.tools.cart_tools import (
    add_items_to_cart,
    get_cart,
    get_cart_total,
    mark_order_confirmed,
    remove_items_from_cart,
)
from customer_support_fde.tools.menu_tools import get_menu, get_menu_item

SYSTEM_PROMPT = """\
You are the order-support agent for a Chinese restaurant. Help the customer \
with menu questions, ingredient/allergy questions, recommendations, and \
building their order. Use the available tools to look up real menu \
information and manage the cart rather than guessing. After a successful \
add to the cart, ask the customer if there's anything else they'd like. \
You can also remove items the customer no longer wants from the cart, \
either entirely or by a specific quantity. \
When a tool reports multiple equally-close matches for a name, ask the \
customer which one they meant instead of guessing. \
Whenever the customer asks for their cart total (or anything about how much \
they currently owe), call get_cart_total to look it up rather than adding up \
prices yourself. \
Whenever the customer asks what's currently in their cart, call get_cart to \
look it up rather than relying on your memory of the conversation.
"""

_ORDER_TOOLS = [
    get_menu,
    get_menu_item,
    add_items_to_cart,
    remove_items_from_cart,
    mark_order_confirmed,
    get_cart_total,
    get_cart,
]

order_tools = ToolNode(_ORDER_TOOLS, handle_tool_errors=handle_tool_error)

ORDER_HISTORY_TOKEN_THRESHOLD = HISTORY_TOKEN_THRESHOLD

_CONDENSATION_INSTRUCTIONS = """\
Summarize the order-support conversation that follows into a concise summary \
for your own future reference. You MUST preserve every customer-stated \
preference, dislike, allergy, and decision (such as items added, removed, or \
confirmed) verbatim rather than paraphrasing them away. If the customer \
restated a preference or changed their mind, keep only their most recent \
statement, not the outdated one. Reply with only the summary text, no \
greeting or meta-commentary.
"""


def _build_context_messages(state: SupportState) -> list[AnyMessage]:
    context: list[AnyMessage] = [SystemMessage(content=SYSTEM_PROMPT)]
    summary = state.get("order_conversation_summary")
    if summary is not None:
        context.append(
            SystemMessage(content=f"Summary of earlier conversation:\n{summary}")
        )
    preferences = state.get("account_preferences")
    if preferences is not None:
        context.append(
            SystemMessage(content=f"Customer's stored preferences: {preferences}")
        )
    return context


def call_model(state: SupportState) -> SupportState:
    messages = (
        state["messages"] if state["messages"] else [HumanMessage(content=state["user_query"])]
    )

    llm = _build_llm()
    removals: list[AnyMessage] = []

    cutoff = select_messages_to_condense(messages)
    if cutoff is not None:
        token_count = _estimate_token_count(_build_context_messages(state) + messages)
        if token_count > ORDER_HISTORY_TOKEN_THRESHOLD:
            older_messages = messages[:cutoff]
            new_summary = condense_messages(
                llm,
                older_messages,
                _CONDENSATION_INSTRUCTIONS,
                state.get("order_conversation_summary"),
            )
            if new_summary is not None:
                state = {**state, "order_conversation_summary": new_summary}
                removals = [RemoveMessage(id=m.id) for m in older_messages]
                messages = messages[cutoff:]

    context = _build_context_messages(state)
    ai_message = llm.bind_tools(_ORDER_TOOLS).invoke(context + messages)

    return {**state, "messages": removals + messages + [ai_message]}


def await_customer(state: SupportState) -> SupportState:
    if state["order_confirmed"]:
        return state

    last_message = state["messages"][-1]
    answer = interrupt(last_message.content)
    return {
        **state,
        "messages": state["messages"] + [HumanMessage(content=str(answer))],
        "user_query": str(answer),
    }
