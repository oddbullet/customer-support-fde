import logging

from langchain_core.messages import SystemMessage

from customer_support_fde import db, tickets
from customer_support_fde.nodes.common import build_llm as _build_llm
from customer_support_fde.state import SupportState

_EMPTY_SUMMARY = {"lines": [], "total": None}

_logger = logging.getLogger(__name__)

_ISSUE_EXTRACTION_INSTRUCTIONS = """\
You are summarizing a customer's refund conversation for a support ticket. \
Read the conversation that follows and reply with a one-to-two-sentence \
statement of the customer's issue or complaint, in their own terms. If the \
conversation never raised any issue or complaint, reply with exactly \
"None" and nothing else.
"""


def _extract_refund_issue(state: SupportState) -> str | None:
    summary = state.get("refund_conversation_summary")
    messages = state.get("messages") or []
    if summary is None and not messages:
        return None

    context = [SystemMessage(content=_ISSUE_EXTRACTION_INSTRUCTIONS)]
    if summary is not None:
        context.append(
            SystemMessage(content=f"Summary of earlier conversation:\n{summary}")
        )
    context.extend(messages)

    try:
        reply = _build_llm().invoke(context).content
    except Exception:
        _logger.warning(
            "Failed to extract refund issue from conversation", exc_info=True
        )
        return None

    reply = reply.strip()
    if reply.lower() == "none":
        return None
    return reply


def ticket_gen_node(state: SupportState) -> SupportState:
    if state["destination"] == "refund":
        return _refund_ticket_node(state)
    return _order_ticket_node(state)


def _order_ticket_node(state: SupportState) -> SupportState:
    summary = state.get("order_summary") or _EMPTY_SUMMARY
    order_ticket = {
        "order_id": state.get("order_id"),
        "items": dict(state["cart_items"]),
        "lines": summary["lines"],
        "total": summary["total"],
    }
    tickets.write_order_ticket(order_ticket)
    return {**state, "order_ticket": order_ticket}


def _refund_ticket_node(state: SupportState) -> SupportState:
    order_lookup = state.get("order_lookup")
    order_id = order_lookup["order_id"] if order_lookup else None
    refund_request = state.get("refund_request")
    complaint_ids = state.get("complaint_ids") or {}

    decision = None
    if refund_request is not None:
        decision = "eligible"
    else:
        complaint_id = complaint_ids.get(order_id or "")
        if complaint_id is not None:
            complaint = next(
                (c for c in db.list_complaints() if c["id"] == complaint_id), None
            )
            if complaint is not None:
                decision = complaint["policy_reason"]

    refund_ticket = {
        "order_id": order_id,
        "order": order_lookup,
        "sentiment": state.get("sentiment"),
        "decision": decision,
        "refund_request": refund_request,
        "complaint_ids": list(complaint_ids.values()),
        "issue": _extract_refund_issue(state),
        "refund_created": refund_request is not None,
    }
    tickets.write_refund_ticket(refund_ticket)
    return {**state, "refund_ticket": refund_ticket}
