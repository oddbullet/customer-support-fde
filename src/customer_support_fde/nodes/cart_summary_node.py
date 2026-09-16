from decimal import Decimal

from langchain_core.messages import AIMessage

from customer_support_fde import db
from customer_support_fde.state import SupportState
from customer_support_fde.tools.menu_tools import MenuItem, cart_total, price_for_item


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


def render_order_summary(summary: dict, order_id: str | None = None) -> str:
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
    if order_id is not None:
        rendered += f"\nOrder ID: {db.format_order_id(order_id)}"
    return rendered


def cart_summary_node(state: SupportState) -> SupportState:
    summary = build_order_summary(state["cart_items"], state["menu"])

    order_id = None
    if summary["lines"]:
        order_id = db.record_order(summary)

    rendered = render_order_summary(summary, order_id)
    return {
        **state,
        "order_summary": summary,
        "order_id": order_id,
        "messages": [AIMessage(content=rendered)],
    }
