from langgraph.types import Command

from customer_support_fde.tools import cart_tools
from customer_support_fde.tools.cart_tools import add_items_to_cart, mark_order_confirmed

SAMPLE_MENU = [
    {
        "name": "Kung Pao Chicken",
        "price": 12.95,
        "ingredients": ["chicken", "peanuts", "dried chili"],
    },
    {
        "name": "Mapo Tofu",
        "price": 11.50,
        "ingredients": ["tofu", "ground pork", "chili bean paste"],
    },
    {
        "name": "Beef Noodle Soup",
        "price": 10.95,
        "ingredients": ["beef", "noodle", "scallion"],
    },
    {
        "name": "Beef Noodle Bowl",
        "price": 9.95,
        "ingredients": ["beef", "noodle", "bean sprout"],
    },
    {
        "name": "Spring Rolls",
        "price": 6.95,
        "ingredients": ["cabbage", "carrot", "wheat wrapper"],
    },
]


def setup_function(_):
    cart_tools._load_menu = lambda: SAMPLE_MENU


def _invoke_add(names, menu_items):
    return add_items_to_cart.func(
        names=names, state={"menu_items": menu_items}, tool_call_id="call_1"
    )


# Adds a single matched item to an empty cart at quantity one. (base)
def test_found_name_added_to_empty_cart_has_quantity_one():
    result = _invoke_add(["Kung Pao Chicken"], {})

    assert isinstance(result, Command)
    assert result.update["menu_items"] == {"Kung Pao Chicken": 1}


# Duplicate names within one call each increment the same item's quantity. (edge)
def test_adding_same_item_twice_in_one_call_increments_quantity():
    result = _invoke_add(["Kung Pao Chicken", "Kung Pao Chicken"], {})

    assert result.update["menu_items"] == {"Kung Pao Chicken": 2}


# Quantity for an item persists and accumulates across separate tool calls. (base)
def test_adding_same_item_across_two_calls_increments_quantity():
    first = _invoke_add(["Kung Pao Chicken"], {})
    second = _invoke_add(["Kung Pao Chicken"], first.update["menu_items"])

    assert second.update["menu_items"] == {"Kung Pao Chicken": 2}


# An ambiguous (tied) name is not added, and both candidates are reported. (edge)
def test_tie_name_leaves_cart_unchanged_but_is_reported():
    result = _invoke_add(["Beef Noodle"], {})

    assert result.update["menu_items"] == {}
    tool_message = result.update["messages"][0]
    assert "Beef Noodle Soup" in tool_message.content
    assert "Beef Noodle Bowl" in tool_message.content


# An unmatched name is not added, and a not-found message is reported. (edge)
def test_not_found_name_leaves_cart_unchanged_but_is_reported():
    result = _invoke_add(["Pizza"], {})

    assert result.update["menu_items"] == {}
    tool_message = result.update["messages"][0]
    assert "No menu item matches" in tool_message.content


# In a mixed batch, only the successfully matched names are added to the cart. (edge)
def test_batch_with_mixed_results_only_applies_found_items():
    result = _invoke_add(["Kung Pao Chicken", "Pizza", "Beef Noodle"], {})

    assert result.update["menu_items"] == {"Kung Pao Chicken": 1}


# The tool must copy the cart rather than mutate the caller's state dict in place. (regression)
def test_never_mutates_input_menu_items_in_place():
    original = {"Spring Rolls": 1}

    _invoke_add(["Kung Pao Chicken"], original)

    assert original == {"Spring Rolls": 1}


# Confirming a non-empty cart sets order_confirmed and returns a confirmation message. (base)
def test_mark_order_confirmed_sets_true_for_non_empty_cart():
    result = mark_order_confirmed.func(
        state={"menu_items": {"Spring Rolls": 1}}, tool_call_id="call_1"
    )

    assert isinstance(result, Command)
    assert result.update["order_confirmed"] is True


# Confirming an empty cart does not set order_confirmed, just informs the customer. (edge)
def test_mark_order_confirmed_omits_flag_for_empty_cart():
    result = mark_order_confirmed.func(state={"menu_items": {}}, tool_call_id="call_1")

    assert "order_confirmed" not in result.update
    tool_message = result.update["messages"][0]
    assert tool_message.content
