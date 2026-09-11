from customer_support_fde import db
from customer_support_fde.state import SupportState

_EMPTY_SUMMARY = {"lines": [], "total": None}


def ticket_gen_node(state: SupportState) -> SupportState:
    summary = state.get("order_summary") or _EMPTY_SUMMARY
    return {
        **state,
        "order_ticket": {
            "order_id": state.get("order_id"),
            "items": dict(state["menu_items"]),
            "lines": summary["lines"],
            "total": summary["total"],
        },
    }


def refund_ticket_node(state: SupportState) -> SupportState:
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

    return {
        **state,
        "refund_ticket": {
            "order_id": order_id,
            "order": order_lookup,
            "sentiment": state.get("sentiment"),
            "decision": decision,
            "refund_request": refund_request,
            "complaint_ids": list(complaint_ids.values()),
        },
    }
