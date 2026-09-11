from langchain_core.messages import AIMessage

from customer_support_fde.nodes.cart_summary_node import (
    build_order_summary,
    cart_summary_node,
    render_order_summary,
)
from customer_support_fde.nodes.ticket_gen_node import ticket_gen_node

SAMPLE_MENU = [
    {
        "name": "Kung Pao Chicken",
        "price": 12.95,
        "ingredients": ["chicken", "peanuts", "dried chili"],
    },
    {
        "name": "Hot and Sour Soup",
        "price": 5.50,
        "ingredients": ["tofu", "wood ear mushroom", "egg"],
    },
    {
        "name": "Spring Rolls",
        "price": 6.95,
        "ingredients": ["cabbage", "carrot", "wheat wrapper"],
    },
]


def _base_state() -> dict:
    return {
        "user_query": "that's all",
        "destination": "order_support",
        "sentiment": None,
        "messages": [],
        "menu_items": {"Kung Pao Chicken": 2, "Spring Rolls": 1},
        "order_confirmed": True,
        "order_ticket": None,
        "order_summary": None,
    }


# A multi-item cart prices each line and sums to the order total. (base)
def test_build_order_summary_multi_item_totals():
    cart = {"Kung Pao Chicken": 2, "Hot and Sour Soup": 1}

    summary = build_order_summary(cart, SAMPLE_MENU)

    assert summary["lines"] == [
        {
            "name": "Kung Pao Chicken",
            "quantity": 2,
            "unit_price": 12.95,
            "line_total": 25.90,
        },
        {
            "name": "Hot and Sour Soup",
            "quantity": 1,
            "unit_price": 5.50,
            "line_total": 5.50,
        },
    ]
    assert summary["total"] == 31.40


# A single-unit cart's line total equals the unit price. (base)
def test_build_order_summary_single_unit_line_total_equals_unit_price():
    cart = {"Spring Rolls": 1}

    summary = build_order_summary(cart, SAMPLE_MENU)

    assert summary["lines"][0]["line_total"] == summary["lines"][0]["unit_price"]
    assert summary["lines"][0]["unit_price"] == 6.95


# Lines preserve menu_items insertion order and carry exactly the four documented fields. (base)
def test_build_order_summary_preserves_order_and_line_fields():
    cart = {"Spring Rolls": 1, "Kung Pao Chicken": 2, "Hot and Sour Soup": 1}

    summary = build_order_summary(cart, SAMPLE_MENU)

    assert [line["name"] for line in summary["lines"]] == [
        "Spring Rolls",
        "Kung Pao Chicken",
        "Hot and Sour Soup",
    ]
    for line in summary["lines"]:
        assert set(line.keys()) == {"name", "quantity", "unit_price", "line_total"}


# The total always rounds up (never down), even when the raw sum is only a
# hair above the lower cent — distinguishes ceiling rounding from nearest. (regression)
def test_build_order_summary_total_always_rounds_up():
    fractional_cent_menu = [{"name": "Item A", "price": 4.321, "ingredients": []}]
    cart = {"Item A": 1}

    summary = build_order_summary(cart, fractional_cent_menu)

    assert summary["total"] == 4.33


# build_order_summary does not mutate the menu_items dict it is given. (regression)
def test_build_order_summary_does_not_mutate_input_menu_items():
    cart = {"Kung Pao Chicken": 2, "Spring Rolls": 1}
    original = dict(cart)

    build_order_summary(cart, SAMPLE_MENU)

    assert cart == original


# An empty cart yields no lines and total is None (not 0.0). (edge)
def test_build_order_summary_empty_cart_yields_none_total():
    summary = build_order_summary({}, SAMPLE_MENU)

    assert summary["lines"] == []
    assert summary["total"] is None


# render_order_summary names every item, shows unit price and line total
# formatted as currency, and emits one Total line for a fully-priced order. (base)
def test_render_order_summary_fully_priced():
    summary = build_order_summary(
        {"Kung Pao Chicken": 2, "Hot and Sour Soup": 1}, SAMPLE_MENU
    )

    rendered = render_order_summary(summary)

    assert "Kung Pao Chicken" in rendered
    assert "x2" in rendered
    assert "Hot and Sour Soup" in rendered
    assert "x1" in rendered
    assert "$12.95" in rendered
    assert "$25.90" in rendered
    assert "$5.50" in rendered
    assert "Total: $31.40" in rendered
    assert rendered.count("Total: $31.40") == 1


# An empty summary renders the empty-cart notice with no amount line. (edge)
def test_render_order_summary_empty_cart_wording():
    summary = build_order_summary({}, SAMPLE_MENU)

    rendered = render_order_summary(summary)

    assert rendered == "There's nothing in your order to summarize."


# cart_summary_node writes order_summary and appends exactly one AIMessage
# carrying the rendered recap. (base)
def test_cart_summary_node_writes_summary_and_appends_one_message(monkeypatch):
    monkeypatch.setattr(
        "customer_support_fde.nodes.cart_summary_node._load_menu",
        lambda: SAMPLE_MENU,
    )
    state = _base_state()

    result = cart_summary_node(state)

    expected_summary = build_order_summary(state["menu_items"], SAMPLE_MENU)
    assert result["order_summary"] == expected_summary
    assert len(result["messages"]) == 1
    assert isinstance(result["messages"][0], AIMessage)
    assert result["messages"][0].content == render_order_summary(expected_summary)


# order_ticket carries items plus the same lines/total as order_summary. (base)
def test_ticket_gen_node_ticket_mirrors_order_summary():
    state = _base_state()
    summary = build_order_summary(state["menu_items"], SAMPLE_MENU)
    state["order_summary"] = summary

    result = ticket_gen_node(state)

    assert result["order_ticket"] == {
        "items": {"Kung Pao Chicken": 2, "Spring Rolls": 1},
        "lines": summary["lines"],
        "total": summary["total"],
    }
    for key in ("user_query", "destination", "sentiment", "menu_items", "order_confirmed"):
        assert result[key] == state[key]


# The ticket's priced values are copied from order_summary, not recomputed
# from menu_items and the menu — proven with values a fresh calculation
# could never produce. (regression)
def test_ticket_gen_node_copies_order_summary_values_without_recomputing():
    state = _base_state()
    state["order_summary"] = {
        "lines": [
            {
                "name": "Kung Pao Chicken",
                "quantity": 2,
                "unit_price": 999.99,
                "line_total": 1999.98,
            }
        ],
        "total": 1999.98,
    }

    result = ticket_gen_node(state)

    assert result["order_ticket"]["lines"] == state["order_summary"]["lines"]
    assert result["order_ticket"]["total"] == 1999.98


# A missing or None order_summary yields empty defaults instead of raising. (edge)
def test_ticket_gen_node_defaults_when_order_summary_missing():
    state = _base_state()
    state["order_summary"] = None

    result = ticket_gen_node(state)

    assert result["order_ticket"]["lines"] == []
    assert result["order_ticket"]["total"] is None
