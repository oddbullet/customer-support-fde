from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel

from customer_support_fde import db, refund_policy
from customer_support_fde.state import SupportState


class UndeliveredItem(BaseModel):
    name: str
    quantity: int


def _render_order(order: dict) -> str:
    lines = ["Here's that order:"]
    for line in order["lines"]:
        lines.append(
            f"- {line['name']} x{line['quantity']} "
            f"@ ${line['unit_price']:.2f} each = ${line['line_total']:.2f}"
        )
    lines.append(f"\nTotal: ${order['total']:.2f}")
    lines.append(f"Placed: {order['created_at']}")
    return "\n".join(lines)


@tool
def lookup_order(
    order_id: str,
    state: Annotated[SupportState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Look up a past order by the order id the customer supplied.

    Args:
        order_id: The order id as the customer stated it. Case, spacing, and
            dashes are normalized, and O/I/L are folded to 0/1/1.
    """
    order = db.get_order(order_id)
    if order is None:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=(
                            f"No order matches '{order_id}'. Please re-check the "
                            "order number."
                        ),
                        tool_call_id=tool_call_id,
                    )
                ],
            }
        )

    return Command(
        update={
            "order_lookup": order,
            "messages": [
                ToolMessage(content=_render_order(order), tool_call_id=tool_call_id)
            ],
        }
    )


def _match_undelivered(
    undelivered_items: list[UndeliveredItem], order_lines: list[dict]
) -> tuple[list[dict], list[str], list[str]]:
    lines_by_name = {line["name"]: line for line in order_lines}

    quantities: dict[str, int] = {}
    for item in undelivered_items:
        quantities[item.name] = quantities.get(item.name, 0) + item.quantity

    matched: list[dict] = []
    clamped_names: list[str] = []
    unmatched_names: list[str] = []
    for name, quantity in quantities.items():
        line = lines_by_name.get(name)
        if line is None:
            unmatched_names.append(name)
            continue
        actual_quantity = quantity
        if actual_quantity > line["quantity"]:
            clamped_names.append(name)
            actual_quantity = line["quantity"]
        unit_price = line["unit_price"]
        line_total = float(Decimal(str(unit_price)) * actual_quantity)
        matched.append(
            {
                "name": name,
                "quantity": actual_quantity,
                "unit_price": unit_price,
                "line_total": line_total,
            }
        )
    return matched, clamped_names, unmatched_names


def _sum_amount(lines: list[dict]) -> float:
    total = Decimal("0")
    for line in lines:
        total += Decimal(str(line["unit_price"])) * line["quantity"]
    return float(total)


def _annotate(message: str, clamped_names: list[str], unmatched_names: list[str]) -> str:
    notes = []
    if clamped_names:
        notes.append(
            "I could only refund the quantity actually ordered for: "
            + ", ".join(clamped_names) + "."
        )
    if unmatched_names:
        notes.append(
            "I couldn't match this to anything on your order, so it wasn't "
            "included: " + ", ".join(unmatched_names) + "."
        )
    if not notes:
        return message
    return message + " " + " ".join(notes)


@tool
def process_refund_request(
    undelivered_items: list[UndeliveredItem],
    substitute_dishes: list[str],
    return_confirmed: bool,
    customer_issue: str,
    state: Annotated[SupportState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Apply the refund policy to the order under discussion and record the outcome.

    Args:
        undelivered_items: Ordered dishes the customer did not receive, with
            the quantity of each not received.
        substitute_dishes: Names of dishes that arrived in their place. Empty
            when nothing arrived at all.
        return_confirmed: Whether the customer explicitly agreed to return
            any substitute dish. Ignored when substitute_dishes is empty.
        customer_issue: The customer's problem, in their own terms.
    """
    order = state.get("order_lookup")
    if order is None:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=(
                            "Please look up the order first before I can process "
                            "a refund."
                        ),
                        tool_call_id=tool_call_id,
                    )
                ],
            }
        )

    order_id = order["order_id"]

    existing = db.get_refund_request_for_order(order_id)
    if existing is not None:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=(
                            f"There's already a refund request for this order — "
                            f"it's currently {existing['status']}, for "
                            f"${existing['amount']:.2f}."
                        ),
                        tool_call_id=tool_call_id,
                    )
                ],
            }
        )

    matched, clamped_names, unmatched_names = _match_undelivered(
        undelivered_items, order["lines"]
    )
    amount = _sum_amount(matched)

    decision = refund_policy.evaluate(
        order,
        undelivered=matched,
        substitute_received=bool(substitute_dishes),
        return_confirmed=return_confirmed,
        now=datetime.now(timezone.utc),
    )

    if decision.eligible:
        try:
            db.record_refund_request(
                order_id,
                lines=matched,
                amount=amount,
                substitute_dishes=substitute_dishes or None,
                return_confirmed=return_confirmed,
            )
        except db.OrderStoreError:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=(
                                "Your refund request could not be recorded. "
                                "Please try again shortly."
                            ),
                            tool_call_id=tool_call_id,
                        )
                    ],
                }
            )

        refund_request = db.get_refund_request_for_order(order_id)
        message = (
            f"Your refund request for ${amount:.2f} has been submitted and is "
            "awaiting review."
        )
        if substitute_dishes:
            message += " Please return: " + ", ".join(substitute_dishes) + "."
        message = _annotate(message, clamped_names, unmatched_names)

        return Command(
            update={
                "refund_request": refund_request,
                "messages": [
                    ToolMessage(content=message, tool_call_id=tool_call_id)
                ],
            }
        )

    complaint_ids = dict(state.get("complaint_ids") or {})
    try:
        if order_id in complaint_ids:
            db.extend_complaint(complaint_ids[order_id], customer_issue, decision.reason)
        else:
            complaint_ids[order_id] = db.record_complaint(
                customer_issue, order_id, decision.reason
            )
    except db.OrderStoreError:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=(
                            "Your issue could not be recorded. Please try again "
                            "shortly."
                        ),
                        tool_call_id=tool_call_id,
                    )
                ],
            }
        )

    message = _annotate(decision.message, clamped_names, unmatched_names)
    return Command(
        update={
            "complaint_ids": complaint_ids,
            "messages": [ToolMessage(content=message, tool_call_id=tool_call_id)],
        }
    )


@tool
def log_complaint(
    description: str,
    state: Annotated[SupportState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Record customer dissatisfaction when no refund is being requested.

    Args:
        description: The customer's issue, in their own terms.
    """
    order = state.get("order_lookup")
    order_id = order["order_id"] if order else None
    complaint_ids = dict(state.get("complaint_ids") or {})
    key = order_id or ""

    try:
        if key in complaint_ids:
            db.extend_complaint(complaint_ids[key], description, None)
        else:
            complaint_ids[key] = db.record_complaint(description, order_id, None)
    except db.OrderStoreError:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=(
                            "Your complaint could not be recorded. Please try "
                            "again shortly."
                        ),
                        tool_call_id=tool_call_id,
                    )
                ],
            }
        )

    return Command(
        update={
            "complaint_ids": complaint_ids,
            "messages": [
                ToolMessage(
                    content=(
                        "I've recorded your feedback and passed it on to the "
                        "restaurant. Thank you for letting us know."
                    ),
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


@tool
def conclude_refund_conversation(
    state: Annotated[SupportState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Signal that this refund conversation has reached an outcome and can end."""
    return Command(
        update={
            "refund_resolved": True,
            "messages": [
                ToolMessage(
                    content="Thanks, is there anything else I can help with?",
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )
