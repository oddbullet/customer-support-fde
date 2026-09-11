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
