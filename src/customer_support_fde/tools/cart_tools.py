from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from customer_support_fde.state import SupportState
from customer_support_fde.tools.menu_tools import MenuMatch, _load_menu, resolve_menu_item


def _render_add_result(name: str, match: MenuMatch) -> str:
    if match.status == "found":
        return f"Added {match.item['name']} to the cart."
    if match.status == "tie":
        candidates = ", ".join(match.candidates)
        return f"'{name}' matches multiple items: {candidates}. Which one did you mean?"
    return f"No menu item matches '{name}'."


@tool
def add_items_to_cart(
    names: list[str],
    state: Annotated[SupportState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Add one or more menu items (by name) to the customer's cart.

    Args:
        names: Menu item names to add, one entry per unit.
    """
    cart = dict(state["menu_items"])
    menu = _load_menu()
    summaries = []
    for name in names:
        match = resolve_menu_item(name, menu)
        if match.status == "found":
            item_name = match.item["name"]
            cart[item_name] = cart.get(item_name, 0) + 1
        summaries.append(_render_add_result(name, match))

    return Command(
        update={
            "menu_items": cart,
            "messages": [
                ToolMessage(content="\n".join(summaries), tool_call_id=tool_call_id)
            ],
        }
    )


@tool
def mark_order_confirmed(
    state: Annotated[SupportState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Confirm the customer is done ordering, finalizing the current cart.

    """
    if not state["menu_items"]:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="There's nothing in the cart yet to confirm.",
                        tool_call_id=tool_call_id,
                    )
                ],
            }
        )

    return Command(
        update={
            "order_confirmed": True,
            "messages": [
                ToolMessage(content="Order confirmed.", tool_call_id=tool_call_id)
            ],
        }
    )
