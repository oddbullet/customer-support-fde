from customer_support_fde.nodes.confirm_node import confirm_node
from customer_support_fde.nodes.ticket_gen_node import ticket_gen_node


def _base_state() -> dict:
    return {
        "user_query": "that's all",
        "destination": "order_support",
        "sentiment": None,
        "messages": [],
        "menu_items": {"Kung Pao Chicken": 2, "Spring Rolls": 1},
        "order_confirmed": True,
        "order_ticket": None,
    }


def test_confirm_node_returns_state_unchanged():
    state = _base_state()

    result = confirm_node(state)

    assert result == state


def test_ticket_gen_node_sets_order_ticket_from_menu_items():
    state = _base_state()

    result = ticket_gen_node(state)

    assert result["order_ticket"] == {
        "items": {"Kung Pao Chicken": 2, "Spring Rolls": 1}
    }
    for key in ("user_query", "destination", "sentiment", "menu_items", "order_confirmed"):
        assert result[key] == state[key]
