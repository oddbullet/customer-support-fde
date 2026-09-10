from customer_support_fde.state import SupportState


def ticket_gen_node(state: SupportState) -> SupportState:
    return {
        **state,
        "order_ticket": {"items": dict(state["menu_items"])},
    }
