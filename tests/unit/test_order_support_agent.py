from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, RemoveMessage
from langgraph._internal._constants import CONF, CONFIG_KEY_RUNTIME
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.runtime import Runtime
from langgraph.types import Command

from customer_support_fde.nodes import order_support_agent
from customer_support_fde.nodes.order_support_agent import (
    await_customer,
    call_model,
    order_tools,
)

# ToolNode.invoke() requires a LangGraph Runtime in its config even outside a
# compiled graph run; this matches the minimal one the graph executor injects.
_TOOL_NODE_CONFIG = {CONF: {CONFIG_KEY_RUNTIME: Runtime()}}

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


def _base_state(user_query: str) -> dict:
    return {
        "user_query": user_query,
        "destination": "order_support",
        "sentiment": None,
        "messages": [],
        "menu_items": {},
        "order_confirmed": False,
        "order_ticket": None,
        "order_summary": None,
    }


def _fake_bound_llm(responses: list[AIMessage]) -> MagicMock:
    bound = MagicMock()
    bound.invoke.side_effect = responses
    return bound


def _patch_llm(monkeypatch, responses: list[AIMessage]) -> None:
    bound = _fake_bound_llm(responses)
    fake_llm = MagicMock()
    fake_llm.bind_tools.return_value = bound
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: fake_llm)


def _merge_tool_result(state: dict, result) -> dict:
    # ToolNode.invoke() returns a plain dict update for ordinary tools, but a
    # list of Command objects when any invoked tool returns a Command.
    updates = [item.update if isinstance(item, Command) else item for item in result] \
        if isinstance(result, list) else [result]

    merged = dict(state)
    new_messages = []
    for update in updates:
        for key, value in update.items():
            if key == "messages":
                new_messages.extend(value)
            else:
                merged[key] = value
    merged["messages"] = state["messages"] + new_messages
    return merged


def _run_inner_loop(state: dict) -> dict:
    state = call_model(state)
    while state["messages"][-1].tool_calls:
        result = order_tools.invoke(state, _TOOL_NODE_CONFIG)
        state = _merge_tool_result(state, result)
        state = call_model(state)
    return state


# A get_menu tool call returns a listing containing every seeded menu item. (base)
def test_get_menu_tool_call_lists_every_seeded_item(monkeypatch):
    tool_call_response = AIMessage(
        content="",
        tool_calls=[{"name": "get_menu", "args": {}, "id": "call_1"}],
    )
    final_response = AIMessage(content="Here's our menu.")
    _patch_llm(monkeypatch, [tool_call_response, final_response])
    monkeypatch.setattr(
        "customer_support_fde.tools.menu_tools._load_menu",
        lambda: SAMPLE_MENU,
    )

    state = _run_inner_loop(_base_state("What's on the menu?"))

    tool_message = next(
        m for m in state["messages"] if getattr(m, "tool_call_id", None) == "call_1"
    )
    for item in SAMPLE_MENU:
        assert item["name"] in tool_message.content


# A get_menu_item tool call for a matched name returns that item's details. (base)
def test_get_menu_item_tool_call_found(monkeypatch):
    tool_call_response = AIMessage(
        content="",
        tool_calls=[
            {"name": "get_menu_item", "args": {"name": "Mapo Tofu"}, "id": "call_1"}
        ],
    )
    final_response = AIMessage(content="Mapo Tofu has tofu and pork.")
    _patch_llm(monkeypatch, [tool_call_response, final_response])
    monkeypatch.setattr(
        "customer_support_fde.tools.menu_tools._load_menu",
        lambda: SAMPLE_MENU,
    )

    state = _run_inner_loop(_base_state("What's in the mapo tofu?"))

    tool_message = next(
        m for m in state["messages"] if getattr(m, "tool_call_id", None) == "call_1"
    )
    assert "Mapo Tofu" in tool_message.content
    assert "tofu" in tool_message.content


# A get_menu_item tool call for an ambiguous name reports both tied candidates. (edge)
def test_get_menu_item_tool_call_tie(monkeypatch):
    tool_call_response = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "get_menu_item",
                "args": {"name": "Beef Noodle"},
                "id": "call_1",
            }
        ],
    )
    final_response = AIMessage(content="Which one did you mean?")
    _patch_llm(monkeypatch, [tool_call_response, final_response])
    monkeypatch.setattr(
        "customer_support_fde.tools.menu_tools._load_menu",
        lambda: SAMPLE_MENU,
    )

    state = _run_inner_loop(_base_state("Tell me about the beef noodle dish"))

    tool_message = next(
        m for m in state["messages"] if getattr(m, "tool_call_id", None) == "call_1"
    )
    assert "Beef Noodle Soup" in tool_message.content
    assert "Beef Noodle Bowl" in tool_message.content


# A get_menu_item tool call for an unmatched name reports it was not found. (edge)
def test_get_menu_item_tool_call_not_found(monkeypatch):
    tool_call_response = AIMessage(
        content="",
        tool_calls=[
            {"name": "get_menu_item", "args": {"name": "Pizza"}, "id": "call_1"}
        ],
    )
    final_response = AIMessage(content="We don't have that.")
    _patch_llm(monkeypatch, [tool_call_response, final_response])
    monkeypatch.setattr(
        "customer_support_fde.tools.menu_tools._load_menu",
        lambda: SAMPLE_MENU,
    )

    state = _run_inner_loop(_base_state("Do you have pizza?"))

    tool_message = next(
        m for m in state["messages"] if getattr(m, "tool_call_id", None) == "call_1"
    )
    assert "No menu item matches" in tool_message.content


# An add_items_to_cart tool call for one item updates the state's menu_items. (base)
def test_add_items_to_cart_tool_call_updates_menu_items(monkeypatch):
    tool_call_response = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "add_items_to_cart",
                "args": {"names": ["Kung Pao Chicken"]},
                "id": "call_1",
            }
        ],
    )
    final_response = AIMessage(content="Added it! Anything else?")
    _patch_llm(monkeypatch, [tool_call_response, final_response])
    monkeypatch.setattr(
        "customer_support_fde.tools.menu_tools._load_menu",
        lambda: SAMPLE_MENU,
    )

    state = _run_inner_loop(_base_state("Add a kung pao chicken"))

    assert state["menu_items"] == {"Kung Pao Chicken": 1}


# An add_items_to_cart tool call with multiple names updates all of them at once. (base)
def test_add_items_to_cart_tool_call_batch_updates_menu_items(monkeypatch):
    tool_call_response = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "add_items_to_cart",
                "args": {"names": ["Kung Pao Chicken", "Spring Rolls"]},
                "id": "call_1",
            }
        ],
    )
    final_response = AIMessage(content="Added both! Anything else?")
    _patch_llm(monkeypatch, [tool_call_response, final_response])
    monkeypatch.setattr(
        "customer_support_fde.tools.menu_tools._load_menu",
        lambda: SAMPLE_MENU,
    )

    state = _run_inner_loop(
        _base_state("Add a kung pao chicken and spring rolls")
    )

    assert state["menu_items"] == {"Kung Pao Chicken": 1, "Spring Rolls": 1}


# Unmatched/ambiguous names in an add_items_to_cart call leave menu_items unchanged. (edge)
def test_add_items_to_cart_tool_call_not_found_or_tie_leaves_menu_items_unchanged(
    monkeypatch,
):
    tool_call_response = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "add_items_to_cart",
                "args": {"names": ["Pizza", "Beef Noodle"]},
                "id": "call_1",
            }
        ],
    )
    final_response = AIMessage(content="I couldn't find those.")
    _patch_llm(monkeypatch, [tool_call_response, final_response])
    monkeypatch.setattr(
        "customer_support_fde.tools.menu_tools._load_menu",
        lambda: SAMPLE_MENU,
    )

    state = _run_inner_loop(_base_state("Add a pizza and beef noodle"))

    assert state["menu_items"] == {}


# A remove_items_from_cart tool call for an unqualified name deletes the entry entirely. (base)
def test_remove_items_from_cart_tool_call_unqualified_deletes_entry(monkeypatch):
    tool_call_response = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "remove_items_from_cart",
                "args": {"items": [{"name": "Kung Pao Chicken"}]},
                "id": "call_1",
            }
        ],
    )
    final_response = AIMessage(content="Removed it! Anything else?")
    _patch_llm(monkeypatch, [tool_call_response, final_response])
    monkeypatch.setattr(
        "customer_support_fde.tools.menu_tools._load_menu",
        lambda: SAMPLE_MENU,
    )

    state = _base_state("Remove the kung pao chicken")
    state["menu_items"] = {"Kung Pao Chicken": 2}

    state = _run_inner_loop(state)

    assert state["menu_items"] == {}


# A remove_items_from_cart tool call with a quantity decrements and keeps the entry. (base)
def test_remove_items_from_cart_tool_call_quantified_decrements_entry(monkeypatch):
    tool_call_response = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "remove_items_from_cart",
                "args": {"items": [{"name": "Kung Pao Chicken", "quantity": 1}]},
                "id": "call_1",
            }
        ],
    )
    final_response = AIMessage(content="Removed one! Anything else?")
    _patch_llm(monkeypatch, [tool_call_response, final_response])
    monkeypatch.setattr(
        "customer_support_fde.tools.menu_tools._load_menu",
        lambda: SAMPLE_MENU,
    )

    state = _base_state("Remove one kung pao chicken")
    state["menu_items"] = {"Kung Pao Chicken": 3}

    state = _run_inner_loop(state)

    assert state["menu_items"] == {"Kung Pao Chicken": 2}


# await_customer interrupts for the next message and resets state from the reply. (base)
def test_await_customer_interrupts_when_not_confirmed(monkeypatch):
    fake_interrupt = MagicMock(return_value="add one")
    monkeypatch.setattr(order_support_agent, "interrupt", fake_interrupt)
    state = _base_state("hello")
    state["messages"] = [AIMessage(content="Anything else?")]

    result = await_customer(state)

    fake_interrupt.assert_called_once_with("Anything else?")
    assert len(result["messages"]) == 1
    assert isinstance(result["messages"][0], RemoveMessage)
    assert result["messages"][0].id == REMOVE_ALL_MESSAGES
    assert result["user_query"] == "add one"


# await_customer skips the interrupt once the order is already confirmed. (edge)
def test_await_customer_does_not_interrupt_when_confirmed(monkeypatch):
    fake_interrupt = MagicMock()
    monkeypatch.setattr(order_support_agent, "interrupt", fake_interrupt)
    state = _base_state("hello")
    state["messages"] = [AIMessage(content="Order confirmed.")]
    state["order_confirmed"] = True

    result = await_customer(state)

    fake_interrupt.assert_not_called()
    assert result["order_confirmed"] is True


# An LLM call failure in call_model raises rather than returning partial state. (error)
def test_call_model_llm_failure_propagates_rather_than_returning_partial_state(
    monkeypatch,
):
    failing_llm = MagicMock()
    failing_llm.bind_tools.return_value.invoke.side_effect = RuntimeError(
        "OpenRouter request failed"
    )
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: failing_llm)
    state = _base_state("What's on the menu?")

    with pytest.raises(RuntimeError):
        call_model(state)
