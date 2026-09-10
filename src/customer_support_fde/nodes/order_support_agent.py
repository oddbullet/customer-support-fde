import os

from langchain_core.messages import AnyMessage, HumanMessage, RemoveMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt

from customer_support_fde.state import SupportState
from customer_support_fde.tools.cart_tools import add_items_to_cart, mark_order_confirmed
from customer_support_fde.tools.menu_tools import get_menu, get_menu_item

DEFAULT_MODEL = "openai/gpt-4o-mini"

SYSTEM_PROMPT = """\
You are the order-support agent for a Chinese restaurant. Help the customer \
with menu questions, ingredient/allergy questions, recommendations, and \
building their order. Use the available tools to look up real menu \
information and manage the cart rather than guessing. After a successful \
add to the cart, ask the customer if there's anything else they'd like. \
When a tool reports multiple equally-close matches for a name, ask the \
customer which one they meant instead of guessing.
"""

_ORDER_TOOLS = [get_menu, get_menu_item, add_items_to_cart, mark_order_confirmed]

order_tools = ToolNode(_ORDER_TOOLS)


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


def _seed_messages(state: SupportState) -> list[AnyMessage]:
    seeded: list[AnyMessage] = [SystemMessage(content=SYSTEM_PROMPT)]
    cart_summary = _render_cart_summary(state["menu_items"])
    if cart_summary:
        seeded.append(SystemMessage(content=cart_summary))
    seeded.append(HumanMessage(content=state["user_query"]))
    return seeded


def call_model(state: SupportState) -> SupportState:
    messages = state["messages"] if state["messages"] else _seed_messages(state)

    ai_message = _build_llm().bind_tools(_ORDER_TOOLS).invoke(messages)

    return {**state, "messages": messages + [ai_message]}


def await_customer(state: SupportState) -> SupportState:
    if state["order_confirmed"]:
        return state

    last_message = state["messages"][-1]
    answer = interrupt(last_message.content)
    return {
        **state,
        "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES)],
        "user_query": str(answer),
    }
