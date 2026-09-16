from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from customer_support_fde import db
from customer_support_fde.tools.menu_tools import MenuItem


class SupportState(TypedDict):
    user_query: str
    destination: Literal["order_support", "refund", "unclear"]
    sentiment: Literal["positive", "neutral", "negative"] | None
    messages: Annotated[list[AnyMessage], add_messages]
    menu: list[MenuItem]
    cart_items: dict[str, int]
    order_confirmed: bool
    order_ticket: dict | None
    order_summary: dict | None
    order_id: str | None
    order_lookup: dict | None
    refund_resolved: bool
    refund_request: dict | None
    complaint_ids: dict[str, int]
    refund_ticket: dict | None
    order_conversation_summary: str | None
    refund_conversation_summary: str | None
    account_number: str | None
    account_preferences: str | None


def initial_state(query: str) -> SupportState:
    return {
        "user_query": query,
        "destination": "order_support",
        "sentiment": None,
        "messages": [],
        "menu": db.load_menu(),
        "cart_items": {},
        "order_confirmed": False,
        "order_ticket": None,
        "order_summary": None,
        "order_id": None,
        "order_lookup": None,
        "refund_resolved": False,
        "refund_request": None,
        "complaint_ids": {},
        "refund_ticket": None,
        "order_conversation_summary": None,
        "refund_conversation_summary": None,
        "account_number": None,
        "account_preferences": None,
    }
