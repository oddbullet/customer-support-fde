import pytest
from langgraph.types import Command
from pydantic import ValidationError

from customer_support_fde.tools.cart_tools import (
    CartItem,
    add_items_to_cart,
    get_cart,
    get_cart_total,
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


def _cart_items(items: dict[str, int]) -> list[CartItem]:
    return [CartItem(name=name, quantity=quantity) for name, quantity in items.items()]


def _invoke_add(items: dict[str, int], cart_items):
    return add_items_to_cart.func(
        items=_cart_items(items),
        state={"cart_items": cart_items, "menu": SAMPLE_MENU},
        tool_call_id="call_1",
    )


def _invoke_remove(items: dict[str, int], cart_items):
    return remove_items_from_cart.func(
        items=_cart_items(items),
        state={"cart_items": cart_items, "menu": SAMPLE_MENU},
        tool_call_id="call_1",
    )


# Adds a single matched item to an empty cart at the requested quantity, reporting success. (base)
def test_found_name_added_to_empty_cart_has_quantity_one():
    result = _invoke_add({"Kung Pao Chicken": 1}, {})

    assert isinstance(result, Command)
    assert result.update["cart_items"] == {"Kung Pao Chicken": 1}
    tool_message = result.update["messages"][0]
    assert tool_message.content == "Success\nCurrent cart:\n- Kung Pao Chicken x1"


# A quantity greater than one is applied directly to the item's cart entry. (edge)
def test_adding_item_with_quantity_greater_than_one_sets_that_quantity():
    result = _invoke_add({"Kung Pao Chicken": 2}, {})

    assert result.update["cart_items"] == {"Kung Pao Chicken": 2}


# Quantity for an item persists and accumulates across separate tool calls. (base)
def test_adding_same_item_across_two_calls_increments_quantity():
    first = _invoke_add({"Kung Pao Chicken": 1}, {})
    second = _invoke_add({"Kung Pao Chicken": 1}, first.update["cart_items"])

    assert second.update["cart_items"] == {"Kung Pao Chicken": 2}


# An ambiguous (tied) name is not added, and is reported as a failure by name. (edge)
def test_tie_name_leaves_cart_unchanged_but_is_reported():
    result = _invoke_add({"Beef Noodle": 1}, {})

    assert result.update["cart_items"] == {}
    tool_message = result.update["messages"][0]
    assert tool_message.content == "Failed to add: Beef Noodle\nCart is empty."


# An unmatched name is not added, and is reported as a failure by name. (edge)
def test_not_found_name_leaves_cart_unchanged_but_is_reported():
    result = _invoke_add({"Pizza": 1}, {})

    assert result.update["cart_items"] == {}
    tool_message = result.update["messages"][0]
    assert tool_message.content == "Failed to add: Pizza\nCart is empty."


# In a mixed batch, only the successfully matched names are added to the cart, and the
# failed names are reported together. (edge)
def test_batch_with_mixed_results_only_applies_found_items():
    result = _invoke_add(
        {"Kung Pao Chicken": 1, "Pizza": 1, "Beef Noodle": 1}, {}
    )

    assert result.update["cart_items"] == {"Kung Pao Chicken": 1}
    tool_message = result.update["messages"][0]
    assert (
        tool_message.content
        == "Failed to add: Pizza, Beef Noodle\nCurrent cart:\n- Kung Pao Chicken x1"
    )


# A negative quantity must be refused rather than applied. order_lines enforces
# quantity > 0, so a negative cart entry would blow up the whole order at record
# time rather than at the point the bad quantity was introduced. (negative)
def test_cart_item_with_negative_quantity_is_rejected():
    with pytest.raises(ValidationError):
        CartItem(name="Kung Pao Chicken", quantity=-2)


# Zero adds or removes nothing, so it is refused like any other non-positive
# quantity. (negative)
def test_cart_item_with_zero_quantity_is_rejected():
    with pytest.raises(ValidationError):
        CartItem(name="Spring Rolls", quantity=0)


# A non-positive quantity anywhere in a tool call's items rejects the whole call, so
# the model gets the validation error back and retries. (edge)
@pytest.mark.parametrize("tool", [add_items_to_cart, remove_items_from_cart])
def test_tool_call_with_one_non_positive_quantity_is_rejected(tool):
    with pytest.raises(ValidationError):
        tool.tool_call_schema.model_validate(
            {
                "items": [
                    {"name": "Kung Pao Chicken", "quantity": 2},
                    {"name": "Spring Rolls", "quantity": -1},
                ]
            }
        )


# The tool must copy the cart rather than mutate the caller's state dict in place. (regression)
def test_never_mutates_input_cart_items_in_place():
    original = {"Spring Rolls": 1}

    _invoke_add({"Kung Pao Chicken": 1}, original)

    assert original == {"Spring Rolls": 1}


# Confirming a non-empty cart sets order_confirmed and returns a confirmation message. (base)
def test_mark_order_confirmed_sets_true_for_non_empty_cart():
    result = mark_order_confirmed.func(
        state={"cart_items": {"Spring Rolls": 1}}, tool_call_id="call_1"
    )

    assert isinstance(result, Command)
    assert result.update["order_confirmed"] is True


# Confirming an empty cart does not set order_confirmed, just informs the customer. (edge)
def test_mark_order_confirmed_omits_flag_for_empty_cart():
    result = mark_order_confirmed.func(state={"cart_items": {}}, tool_call_id="call_1")

    assert "order_confirmed" not in result.update
    tool_message = result.update["messages"][0]
    assert tool_message.content


# A quantity matching the current cart quantity deletes the entry entirely, reporting
# success. (base)
def test_removal_quantity_matching_current_deletes_entry():
    result = _invoke_remove({"Kung Pao Chicken": 1}, {"Kung Pao Chicken": 1})

    assert isinstance(result, Command)
    assert result.update["cart_items"] == {}
    tool_message = result.update["messages"][0]
    assert tool_message.content == "Success\nCart is empty."


# A stated quantity smaller than the current cart quantity decrements the entry and
# keeps it. (base)
def test_quantified_removal_smaller_than_current_decrements_and_keeps_entry():
    result = _invoke_remove({"Kung Pao Chicken": 1}, {"Kung Pao Chicken": 3})

    assert result.update["cart_items"] == {"Kung Pao Chicken": 2}


# A stated quantity that exceeds the current cart quantity deletes the entry entirely
# and is still reported as a success, not a failure. (edge)
def test_quantified_removal_above_current_deletes_entry_as_success():
    result = _invoke_remove({"Kung Pao Chicken": 10}, {"Kung Pao Chicken": 3})

    assert result.update["cart_items"] == {}
    tool_message = result.update["messages"][0]
    assert tool_message.content == "Success\nCart is empty."


# A found menu item that isn't currently a key in the cart is reported as a failure by
# name, distinct from a not_found menu-match. (edge)
def test_found_but_not_in_cart_name_is_reported_as_failure():
    result = _invoke_remove({"Mapo Tofu": 1}, {"Kung Pao Chicken": 1})

    assert result.update["cart_items"] == {"Kung Pao Chicken": 1}
    tool_message = result.update["messages"][0]
    assert (
        tool_message.content
        == "Failed to remove: Mapo Tofu\nCurrent cart:\n- Kung Pao Chicken x1"
    )


# A tie name and a not_found name each leave the cart unchanged and are reported
# together as failures by name. (edge)
def test_tie_and_not_found_removal_names_leave_cart_unchanged_but_are_reported():
    result = _invoke_remove(
        {"Beef Noodle": 1, "Pizza": 1},
        {"Kung Pao Chicken": 1},
    )

    assert result.update["cart_items"] == {"Kung Pao Chicken": 1}
    tool_message = result.update["messages"][0]
    assert (
        tool_message.content
        == "Failed to remove: Beef Noodle, Pizza\nCurrent cart:\n- Kung Pao Chicken x1"
    )


# In a mixed batch, only the found-and-in-cart items are removed, each independently
# of the others' outcomes, and the rest are reported as failures. (edge)
def test_batch_with_mixed_results_applies_only_found_and_in_cart_items():
    result = _invoke_remove(
        {
            "Kung Pao Chicken": 1,
            "Mapo Tofu": 1,
            "Pizza": 1,
            "Beef Noodle": 1,
        },
        {"Kung Pao Chicken": 1, "Spring Rolls": 2},
    )

    assert result.update["cart_items"] == {"Spring Rolls": 2}
    tool_message = result.update["messages"][0]
    assert (
        tool_message.content
        == "Failed to remove: Mapo Tofu, Pizza, Beef Noodle\nCurrent cart:\n- Spring Rolls x2"
    )


# The tool must copy the cart rather than mutate the caller's state dict in place. (regression)
def test_remove_never_mutates_input_cart_items_in_place():
    original = {"Kung Pao Chicken": 1, "Spring Rolls": 2}

    _invoke_remove({"Kung Pao Chicken": 1}, original)

    assert original == {"Kung Pao Chicken": 1, "Spring Rolls": 2}


# Even when a batch entirely fails, the tool still reports the current (unchanged) cart
# state in its message rather than only the failure text. (regression)
def test_add_failure_still_reports_current_nonempty_cart_state():
    result = _invoke_add({"Pizza": 1}, {"Spring Rolls": 2})

    assert result.update["cart_items"] == {"Spring Rolls": 2}
    tool_message = result.update["messages"][0]
    assert (
        tool_message.content
        == "Failed to add: Pizza\nCurrent cart:\n- Spring Rolls x2"
    )


# Same guarantee for remove: a fully-failed batch still reports the current cart state. (regression)
def test_remove_failure_still_reports_current_nonempty_cart_state():
    result = _invoke_remove({"Pizza": 1}, {"Spring Rolls": 2})

    assert result.update["cart_items"] == {"Spring Rolls": 2}
    tool_message = result.update["messages"][0]
    assert (
        tool_message.content
        == "Failed to remove: Pizza\nCurrent cart:\n- Spring Rolls x2"
    )


def _invoke_get_cart_total(cart_items):
    return get_cart_total.func(state={"cart_items": cart_items, "menu": SAMPLE_MENU})


# A single item at quantity one reports that exact item's price as the total. (base)
def test_get_cart_total_single_item_reports_exact_price():
    rendered = _invoke_get_cart_total({"Kung Pao Chicken": 1})

    assert "$12.95" in rendered


# Multiple distinct items at varying quantities report the correct combined total. (base)
def test_get_cart_total_multiple_items_reports_combined_total():
    rendered = _invoke_get_cart_total(
        {"Kung Pao Chicken": 2, "Mapo Tofu": 1, "Spring Rolls": 3}
    )

    expected = 12.95 * 2 + 11.50 + 6.95 * 3
    assert f"${expected:.2f}" in rendered


# An empty cart is reported as empty, with no dollar figure in the response. (edge)
def test_get_cart_total_empty_cart_reports_no_numeric_total():
    rendered = _invoke_get_cart_total({})

    assert "$" not in rendered
    assert "empty" in rendered.lower()


def _invoke_get_cart(cart_items):
    return get_cart.func(state={"cart_items": cart_items, "menu": SAMPLE_MENU})


# A cart with multiple items renders one line per item in the shared cart-state format. (base)
def test_get_cart_multiple_items_renders_current_cart_lines():
    rendered = _invoke_get_cart({"Kung Pao Chicken": 2, "Mapo Tofu": 1})

    assert rendered == "Current cart:\n- Kung Pao Chicken x2\n- Mapo Tofu x1"


# An empty cart is reported with the exact shared empty-cart message. (edge)
def test_get_cart_empty_cart_reports_exact_empty_message():
    rendered = _invoke_get_cart({})

    assert rendered == "Cart is empty."


# The tool is a pure read: it returns a plain string, not a Command, and never mutates
# the cart dict passed in via state. (negative)
def test_get_cart_is_read_only_and_returns_plain_string_not_command():
    original = {"Spring Rolls": 2}

    result = _invoke_get_cart(original)

    assert isinstance(result, str)
    assert not isinstance(result, Command)
    assert original == {"Spring Rolls": 2}
