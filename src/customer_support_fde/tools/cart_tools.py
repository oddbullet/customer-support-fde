from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel

from customer_support_fde.state import SupportState
from customer_support_fde.tools.menu_tools import MenuMatch, _load_menu, resolve_menu_item


class CartRemoval(BaseModel):
    name: str
    quantity: int | None = None


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


def _render_remove_result(
    name: str, match: MenuMatch, cart: dict[str, int], quantity: int | None
) -> str:
    if match.status == "tie":
        candidates = ", ".join(match.candidates)
        return f"'{name}' matches multiple items: {candidates}. Which one did you mean?"
    if match.status == "not_found":
        return f"No menu item matches '{name}'."

    item_name = match.item["name"]
    current = cart.get(item_name)
    if current is None:
        return f"{item_name} isn't in your cart."
    if quantity is None or quantity >= current:
        return f"Removed all {current} of {item_name} from the cart."
    remaining = current - quantity
    return f"Removed {quantity} of {item_name} from the cart. {remaining} remaining."


@tool
def remove_items_from_cart(
    items: list[CartRemoval],
    state: Annotated[SupportState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Remove one or more menu items (by name) from the customer's cart.

    Args:
        items: Each entry names a cart item to remove and an optional quantity.
            Omitting quantity (or leaving it None) removes the entire entry
            regardless of how many units are in the cart. A positive quantity
            decrements the entry by that amount, capped at what's actually in
            the cart (deleting the entry if the cap is reached).
    """
    cart = dict(state["menu_items"])
    menu = _load_menu()
    summaries = []
    for removal in items:
        match = resolve_menu_item(removal.name, menu)
        summaries.append(
            _render_remove_result(removal.name, match, cart, removal.quantity)
        )
        if match.status != "found":
            continue
        item_name = match.item["name"]
        if item_name not in cart:
            continue
        current = cart[item_name]
        if removal.quantity is None or removal.quantity >= current:
            del cart[item_name]
        else:
            cart[item_name] -= removal.quantity

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
