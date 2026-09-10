from langgraph.types import Command

from customer_support_fde.tools import cart_tools
from customer_support_fde.tools.cart_tools import (
    CartRemoval,
    add_items_to_cart,
    mark_order_confirmed,
    remove_items_from_cart,
)

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


def _invoke_remove(items, menu_items):
    return remove_items_from_cart.func(
        items=items, state={"menu_items": menu_items}, tool_call_id="call_1"
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


# An unqualified removal deletes a quantity-1 entry entirely. (base)
def test_unqualified_removal_deletes_quantity_one_entry():
    result = _invoke_remove(
        [CartRemoval(name="Kung Pao Chicken")], {"Kung Pao Chicken": 1}
    )

    assert isinstance(result, Command)
    assert result.update["menu_items"] == {}


# An unqualified removal deletes a quantity-3 entry entirely, regardless of how many
# units were present. (base)
def test_unqualified_removal_deletes_multi_quantity_entry_entirely():
    result = _invoke_remove(
        [CartRemoval(name="Kung Pao Chicken")], {"Kung Pao Chicken": 3}
    )

    assert result.update["menu_items"] == {}


# A stated quantity smaller than the current cart quantity decrements the entry and
# keeps it. (base)
def test_quantified_removal_smaller_than_current_decrements_and_keeps_entry():
    result = _invoke_remove(
        [CartRemoval(name="Kung Pao Chicken", quantity=1)], {"Kung Pao Chicken": 3}
    )

    assert result.update["menu_items"] == {"Kung Pao Chicken": 2}


# A stated quantity that meets or exceeds the current cart quantity deletes the entry
# entirely and reports the actual capped amount removed, not the requested amount. (edge)
def test_quantified_removal_at_or_above_current_deletes_entry_and_reports_capped_amount():
    result = _invoke_remove(
        [CartRemoval(name="Kung Pao Chicken", quantity=10)], {"Kung Pao Chicken": 3}
    )

    assert result.update["menu_items"] == {}
    tool_message = result.update["messages"][0]
    assert "3" in tool_message.content
    assert "10" not in tool_message.content


# A found menu item that isn't currently a key in the cart is reported as "isn't in
# your cart", distinct from a not_found menu-match. (edge)
def test_found_but_not_in_cart_name_is_reported_as_not_in_cart():
    result = _invoke_remove([CartRemoval(name="Mapo Tofu")], {"Kung Pao Chicken": 1})

    assert result.update["menu_items"] == {"Kung Pao Chicken": 1}
    tool_message = result.update["messages"][0]
    assert "isn't in your cart" in tool_message.content


# A tie name and a not_found name each leave the cart unchanged and are reported in
# the ToolMessage content. (edge)
def test_tie_and_not_found_removal_names_leave_cart_unchanged_but_are_reported():
    result = _invoke_remove(
        [CartRemoval(name="Beef Noodle"), CartRemoval(name="Pizza")],
        {"Kung Pao Chicken": 1},
    )

    assert result.update["menu_items"] == {"Kung Pao Chicken": 1}
    tool_message = result.update["messages"][0]
    assert "Beef Noodle Soup" in tool_message.content
    assert "Beef Noodle Bowl" in tool_message.content
    assert "No menu item matches" in tool_message.content


# In a mixed batch, only the found-and-in-cart items are removed, each independently
# of the others' outcomes. (edge)
def test_batch_with_mixed_results_applies_only_found_and_in_cart_items():
    result = _invoke_remove(
        [
            CartRemoval(name="Kung Pao Chicken"),
            CartRemoval(name="Mapo Tofu"),
            CartRemoval(name="Pizza"),
            CartRemoval(name="Beef Noodle"),
        ],
        {"Kung Pao Chicken": 1, "Spring Rolls": 2},
    )

    assert result.update["menu_items"] == {"Spring Rolls": 2}


# The tool must copy the cart rather than mutate the caller's state dict in place. (regression)
def test_remove_never_mutates_input_menu_items_in_place():
    original = {"Kung Pao Chicken": 1, "Spring Rolls": 2}

    _invoke_remove([CartRemoval(name="Kung Pao Chicken")], original)

    assert original == {"Kung Pao Chicken": 1, "Spring Rolls": 2}
