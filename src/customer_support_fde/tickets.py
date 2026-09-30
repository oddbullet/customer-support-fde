"""Markdown ticket rendering and file writing for confirmed orders and refund outcomes."""

import logging
import os
import uuid
from pathlib import Path

_logger = logging.getLogger(__name__)


def tickets_dir() -> Path:
    env_value = os.environ.get("CUSTOMER_SUPPORT_TICKETS_DIR")
    if env_value:
        return Path(env_value)
    return Path("tickets")


def _write_ticket_file(path: Path, content: str) -> Path | None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError:
        _logger.error("Failed to write ticket file %s", path, exc_info=True)
        return None
    return path


def _render_order_ticket(order_ticket: dict) -> str:
    lines = [
        f"- {line['name']} x{line['quantity']} @ ${line['unit_price']:.2f} each "
        f"= ${line['line_total']:.2f}"
        for line in order_ticket["lines"]
    ]
    return (
        "# Order Ticket\n\n"
        + "\n".join(lines)
        + f"\n\n**Total**: ${order_ticket['total']:.2f}\n"
    )


def write_order_ticket(order_ticket: dict) -> Path | None:
    if not order_ticket["lines"]:
        return None
    content = _render_order_ticket(order_ticket)
    path = tickets_dir() / f"order-{order_ticket['order_id']}.md"
    return _write_ticket_file(path, content)


def _or_default(value: str | None, default: str) -> str:
    # A blank value renders like a missing one, so no ticket field is ever empty.
    if value is None or not value.strip():
        return default
    return value


def _render_refund_ticket(refund_ticket: dict) -> str:
    order_id = _or_default(refund_ticket["order_id"], "Unknown")
    issue = _or_default(refund_ticket["issue"], "Not recorded")
    sentiment = _or_default(refund_ticket["sentiment"], "unavailable")
    refund_created = "Yes" if refund_ticket["refund_created"] else "No"
    return (
        "# Refund Ticket\n\n"
        f"**Order ID:** {order_id}\n\n"
        f"**Issue:** {issue}\n\n"
        f"**Customer Sentiment:** {sentiment}\n\n"
        f"**Refund Request Created:** {refund_created}\n"
    )


def write_refund_ticket(refund_ticket: dict) -> Path | None:
    order_id = refund_ticket["order_id"]
    if order_id is not None:
        # A suffix keeps a later refund conversation about the same order from
        # overwriting this ticket.
        path = tickets_dir() / f"refund-{order_id}-{uuid.uuid4().hex[:8]}.md"
    else:
        path = tickets_dir() / f"refund-unknown-{uuid.uuid4().hex}.md"
    content = _render_refund_ticket(refund_ticket)
    return _write_ticket_file(path, content)
