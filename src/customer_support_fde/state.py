from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from customer_support_fde.tools.menu_tools import MenuItem


class SupportState(TypedDict):
    user_query: str
    destination: Literal["order_support", "refund", "unclear"]
    sentiment: Literal["positive", "neutral", "negative"] | None
    messages: Annotated[list[AnyMessage], add_messages]
    menu: list[MenuItem]
    menu_items: dict[str, int]
    order_confirmed: bool
    order_ticket: dict | None
    order_summary: dict | None
    order_id: str | None
