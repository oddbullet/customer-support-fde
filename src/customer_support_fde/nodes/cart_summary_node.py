import logging
from datetime import datetime
from decimal import Decimal

from langchain_core.messages import AIMessage

from customer_support_fde import clock, db, restaurant_time
from customer_support_fde.state import SupportState
from customer_support_fde.tools.menu_tools import MenuItem, cart_total, price_for_item

_logger = logging.getLogger(__name__)


class OrderNotPlacedError(Exception):
    # record_order is a single transaction, so when it fails nothing was saved and the
    # CLI can tell the customer their order was not placed.
    pass


def build_order_summary(cart_items: dict[str, int], menu: list[MenuItem]) -> dict:
    lines = []

    for name, quantity in cart_items.items():
        unit_price = price_for_item(name, menu)
        line_total_decimal = Decimal(str(unit_price)) * quantity
        lines.append(
            {
                "name": name,
                "quantity": quantity,
                "unit_price": unit_price,
                "line_total": float(line_total_decimal),
            }
        )

    return {"lines": lines, "total": cart_total(cart_items, menu)}


def render_order_summary(
    summary: dict, order_id: str | None = None, placed_at: datetime | None = None
) -> str:
    lines = summary["lines"]

    if not lines:
        return "There's nothing in your order to summarize."

    body_lines = ["Here's your order:"]
    for line in lines:
        body_lines.append(
            f"- {line['name']} x{line['quantity']} "
            f"@ ${line['unit_price']:.2f} each = ${line['line_total']:.2f}"
        )

    total_line = f"Total: ${summary['total']:.2f}"
    rendered = "\n".join(body_lines) + "\n\n" + total_line
    if placed_at is not None:
        rendered += f"\nPlaced: {restaurant_time.format_local(placed_at)}"
    if order_id is not None:
        rendered = (
            "Your order has been placed.\n\n"
            + rendered
            + f"\nOrder ID: {db.format_order_id(order_id)}"
            + "\nPlease show this ID when you pick up your order."
        )
    return rendered


def cart_summary_node(state: SupportState) -> SupportState:
    summary = build_order_summary(state["cart_items"], state["menu"])

    order_id = None
    placed_at = None
    if summary["lines"]:
        try:
            # The trusted clock, not the host clock, is the source of truth for when
            # the order was placed; the refund window is measured from it.
            placed_at = clock.trusted_now()
            order_id = db.record_order(summary, created_at=placed_at)
        except (
            db.OrderStoreError,
            db.MenuStoreError,
            clock.ClockUnavailableError,
        ) as exc:
            _logger.error("Failed to record confirmed order", exc_info=exc)
            raise OrderNotPlacedError() from exc

    rendered = render_order_summary(summary, order_id, placed_at)
    return {
        **state,
        "order_summary": summary,
        "order_id": order_id,
        "messages": [AIMessage(content=rendered)],
    }
