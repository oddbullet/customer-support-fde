import logging

from langchain_core.messages import SystemMessage
from pydantic import BaseModel, Field

from customer_support_fde import db, tickets
from customer_support_fde.nodes.common import build_llm as _build_llm
from customer_support_fde.nodes.common import invoke_with_retry, summary_messages
from customer_support_fde.state import SupportState

_EMPTY_SUMMARY = {"lines": [], "total": None}

_logger = logging.getLogger(__name__)

_ISSUE_EXTRACTION_INSTRUCTIONS = """\
You are summarizing a customer's refund conversation for a support ticket. \
Read the conversation that follows and extract the customer's issue or \
complaint, in their own terms (such as missing items, incorrect items, poor \
food quality, or late delivery). Leave the issue field null if the \
conversation never raised any issue or complaint.
"""


class _RefundIssueExtraction(BaseModel):
    issue: str | None = Field(
        default=None,
        description=(
            "A one-to-two-sentence statement of the customer's issue or "
            "complaint, in their own terms. Null when no issue or "
            "complaint was raised."
        ),
    )


def _extract_refund_issue(state: SupportState) -> str | None:
    summary = state.get("refund_conversation_summary")
    messages = state.get("messages") or []
    if summary is None and not messages:
        return None

    context = [SystemMessage(content=_ISSUE_EXTRACTION_INSTRUCTIONS)]
    context.extend(summary_messages(summary))
    context.extend(messages)

    try:
        result = invoke_with_retry(
            _build_llm().with_structured_output(_RefundIssueExtraction), context
        )
    except Exception:
        _logger.warning(
            "Failed to extract refund issue from conversation", exc_info=True
        )
        return None

    if result.issue is None:
        return None
    return result.issue.strip() or None


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
            try:
                complaints = db.list_complaints()
            except db.OrderStoreError:
                # The conversation already finished; write the ticket without the
                # decision rather than failing the customer at the last step.
                _logger.warning(
                    "Failed to read complaint for refund ticket", exc_info=True
                )
                complaints = []
            complaint = next((c for c in complaints if c["id"] == complaint_id), None)
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
