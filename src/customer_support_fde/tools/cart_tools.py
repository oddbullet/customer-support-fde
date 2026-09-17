from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from customer_support_fde.state import SupportState
from customer_support_fde.tools.menu_tools import cart_total, resolve_menu_item


def _format_cart_state(cart: dict[str, int]) -> str:
    if not cart:
        return "Cart is empty."
    lines = [f"- {name} x{quantity}" for name, quantity in cart.items()]
    return "Current cart:\n" + "\n".join(lines)


def _cart_result(
    cart: dict[str, int], failed: list[str], verb: str, tool_call_id: str
) -> Command:
    status = f"Failed to {verb}: {', '.join(failed)}" if failed else "Success"
    content = f"{status}\n{_format_cart_state(cart)}"
    return Command(
        update={
            "cart_items": cart,
            "messages": [ToolMessage(content=content, tool_call_id=tool_call_id)],
        }
    )


@tool
def add_items_to_cart(
    items: dict[str, int],
    state: Annotated[SupportState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Add one or more menu items to the customer's cart.

    Args:
        items: Mapping of menu item name to the quantity to add.
    """
    cart = dict(state["cart_items"])
    menu = state["menu"]
    failed = []
    for name, quantity in items.items():
        match = resolve_menu_item(name, menu)
        if match.status == "found":
            item_name = match.item["name"]
            cart[item_name] = cart.get(item_name, 0) + quantity
        else:
            failed.append(name)

    return _cart_result(cart, failed, "add", tool_call_id)


@tool
def remove_items_from_cart(
    items: dict[str, int],
    state: Annotated[SupportState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Remove one or more menu items from the customer's cart.

    Args:
        items: Mapping of menu item name to the quantity to remove. If the
            quantity given meets or exceeds what's currently in the cart,
            the entire entry is removed.
    """
    cart = dict(state["cart_items"])
    menu = state["menu"]
    failed = []
    for name, quantity in items.items():
        match = resolve_menu_item(name, menu)
        if match.status != "found":
            failed.append(name)
            continue
        item_name = match.item["name"]
        current = cart.get(item_name)
        if current is None:
            failed.append(name)
            continue
        if quantity >= current:
            del cart[item_name]
        else:
            cart[item_name] -= quantity

    return _cart_result(cart, failed, "remove", tool_call_id)


@tool
def mark_order_confirmed(
    state: Annotated[SupportState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Confirm the customer is done ordering, finalizing the current cart."""
    update = {}
    if state["cart_items"]:
        update["order_confirmed"] = True
        content = "Order confirmed."
    else:
        content = "There's nothing in the cart yet to confirm."
    update["messages"] = [ToolMessage(content=content, tool_call_id=tool_call_id)]
    return Command(update=update)


@tool
def get_cart_total(state: Annotated[SupportState, InjectedState]) -> str:
    """Return the customer's current cart total, computed from cart contents and
    live menu prices. Always use this instead of computing or estimating the
    total yourself.

    Returns:
        str: A message stating the exact current total, or a message saying
        the cart is empty when there's nothing in it yet.
    """
    total = cart_total(state["cart_items"], state["menu"])
    if total is None:
        return "Your cart is empty, so there's no total yet."
    return f"Your current cart total is ${total:.2f}."
