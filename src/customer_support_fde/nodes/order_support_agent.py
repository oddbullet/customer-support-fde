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
from customer_support_fde.tools.cart_tools import (
    add_items_to_cart,
    get_cart_total,
    mark_order_confirmed,
    remove_items_from_cart,
)
from customer_support_fde.tools.menu_tools import get_menu, get_menu_item

DEFAULT_MODEL = "openai/gpt-4o-mini"

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
prices yourself.
"""

_ORDER_TOOLS = [
    get_menu,
    get_menu_item,
    add_items_to_cart,
    remove_items_from_cart,
    mark_order_confirmed,
    get_cart_total,
]

order_tools = ToolNode(_ORDER_TOOLS)

ORDER_HISTORY_TOKEN_THRESHOLD = 20_000

_CONDENSATION_INSTRUCTIONS = """\
Summarize the order-support conversation that follows into a concise summary \
for your own future reference. You MUST preserve every customer-stated \
preference, dislike, allergy, and decision (such as items added, removed, or \
confirmed) verbatim rather than paraphrasing them away. If the customer \
restated a preference or changed their mind, keep only their most recent \
statement, not the outdated one. Reply with only the summary text, no \
greeting or meta-commentary.
"""


def _build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ.get("OPENROUTER_API_KEY"),
        model=os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL),
    )


def _render_cart_summary(menu_items: dict[str, int]) -> str | None:
    if not menu_items:
        return None
    lines = [f"- {name} x{quantity}" for name, quantity in menu_items.items()]
    return "Current cart:\n" + "\n".join(lines)


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
    cart_summary = _render_cart_summary(state["menu_items"])
    if cart_summary:
        context.append(SystemMessage(content=cart_summary))
    summary = state.get("order_conversation_summary")
    if summary is not None:
        context.append(
            SystemMessage(content=f"Summary of earlier conversation:\n{summary}")
        )
    return context


def call_model(state: SupportState) -> SupportState:
    messages = (
        state["messages"] if state["messages"] else [HumanMessage(content=state["user_query"])]
    )

    llm = _build_llm()
    removals: list[AnyMessage] = []

    human_indices = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage)]
    if len(human_indices) > 3:
        token_count = _estimate_token_count(_build_context_messages(state) + messages)
        if token_count > ORDER_HISTORY_TOKEN_THRESHOLD:
            cutoff = human_indices[-3]
            older_messages = messages[:cutoff]
            try:
                condense_input: list[AnyMessage] = [
                    SystemMessage(content=_CONDENSATION_INSTRUCTIONS)
                ]
                previous_summary = state.get("order_conversation_summary")
                if previous_summary is not None:
                    condense_input.append(
                        SystemMessage(content=f"Previous summary:\n{previous_summary}")
                    )
                condense_input.extend(older_messages)
                new_summary = llm.invoke(condense_input).content
            except Exception:
                pass
            else:
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
