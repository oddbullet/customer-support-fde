from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage
from langgraph._internal._constants import CONF, CONFIG_KEY_RUNTIME
from langgraph.runtime import Runtime
from langgraph.types import Command

from customer_support_fde.nodes import order_support_agent
from customer_support_fde.nodes.order_support_agent import (
    _ORDER_TOOLS,
    await_customer,
    call_model,
    order_tools,
)
from customer_support_fde.tools.cart_tools import get_cart_total

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
        "menu": SAMPLE_MENU,
        "menu_items": {},
        "order_confirmed": False,
        "order_ticket": None,
        "order_summary": None,
        "order_id": None,
        "order_lookup": None,
        "refund_resolved": False,
        "refund_request": None,
        "complaint_ids": {},
        "refund_ticket": None,
        "order_conversation_summary": None,
        "refund_conversation_summary": None,
    }


def _turn(i: int, tokens: int | None = None) -> list:
    usage_metadata = None
    if tokens is not None:
        usage_metadata = {
            "input_tokens": tokens,
            "output_tokens": 10,
            "total_tokens": tokens + 10,
        }
    return [
        HumanMessage(content=f"turn {i} query", id=f"h{i}"),
        AIMessage(content=f"turn {i} reply", id=f"a{i}", usage_metadata=usage_metadata),
    ]


def _conversation(num_turns: int, last_turn_tokens: int | None = None) -> list:
    messages: list = []
    for i in range(1, num_turns + 1):
        tokens = last_turn_tokens if i == num_turns else None
        messages.extend(_turn(i, tokens))
    return messages


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

    state = _base_state("Remove one kung pao chicken")
    state["menu_items"] = {"Kung Pao Chicken": 3}

    state = _run_inner_loop(state)

    assert state["menu_items"] == {"Kung Pao Chicken": 2}


# await_customer's standard path: while the order isn't confirmed yet, it interrupts and
# appends the resumed reply as a new HumanMessage onto the existing transcript instead of
# wiping it (a prior bug reset the transcript each turn; this also guards that). (base)
def test_await_customer_interrupts_when_not_confirmed(monkeypatch):
    fake_interrupt = MagicMock(return_value="add one")
    monkeypatch.setattr(order_support_agent, "interrupt", fake_interrupt)
    state = _base_state("hello")
    prior_message = AIMessage(content="Anything else?")
    state["messages"] = [prior_message]

    result = await_customer(state)

    fake_interrupt.assert_called_once_with("Anything else?")
    assert len(result["messages"]) == 2
    assert result["messages"][0] is prior_message
    assert isinstance(result["messages"][1], HumanMessage)
    assert result["messages"][1].content == "add one"
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


# call_model rebuilds the cart-summary SystemMessage from state["menu_items"] on every
# call, not just the first turn's, now that messages persists across turns. (regression)
def test_call_model_refreshes_cart_summary_on_later_turns(monkeypatch):
    final_response = AIMessage(content="Anything else?")
    bound = MagicMock()
    bound.invoke.return_value = final_response
    fake_llm = MagicMock()
    fake_llm.bind_tools.return_value = bound
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: fake_llm)

    state = _base_state("Add a spring roll too")
    state["messages"] = [
        HumanMessage(content="Add a kung pao chicken"),
        AIMessage(content="Added! Anything else?"),
    ]
    state["menu_items"] = {"Kung Pao Chicken": 1}

    call_model(state)

    sent_messages = bound.invoke.call_args[0][0]
    system_messages = [m for m in sent_messages if isinstance(m, SystemMessage)]
    assert any(
        "Kung Pao Chicken" in m.content and "1" in m.content for m in system_messages
    )


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


# get_cart_total is registered on the order support agent's tool list, so the
# model can look up an exact total instead of computing one itself. (base)
def test_get_cart_total_is_registered_on_order_tools():
    assert get_cart_total in _ORDER_TOOLS


# With 3 or fewer completed turns, condensation is skipped even over the token
# threshold, since there is nothing older than the retained turns to condense. (edge)
def test_call_model_skips_condensation_with_three_or_fewer_turns(monkeypatch):
    final_response = AIMessage(content="Sure thing!")
    fake_llm = MagicMock()
    fake_llm.bind_tools.return_value.invoke.return_value = final_response
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: fake_llm)

    conversation = _conversation(
        3, last_turn_tokens=order_support_agent.ORDER_HISTORY_TOKEN_THRESHOLD + 1
    )
    state = _base_state("turn 4 query")
    state["messages"] = conversation

    result = call_model(state)

    fake_llm.invoke.assert_not_called()
    assert result["order_conversation_summary"] is None
    assert result["messages"] == conversation + [final_response]


# With more than 3 turns but the token count at/under threshold, condensation is
# skipped and messages/summary are left unchanged. (edge)
def test_call_model_skips_condensation_when_at_or_under_threshold(monkeypatch):
    final_response = AIMessage(content="Sure thing!")
    fake_llm = MagicMock()
    fake_llm.bind_tools.return_value.invoke.return_value = final_response
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: fake_llm)

    conversation = _conversation(
        4, last_turn_tokens=order_support_agent.ORDER_HISTORY_TOKEN_THRESHOLD
    )
    state = _base_state("turn 5 query")
    state["messages"] = conversation

    result = call_model(state)

    fake_llm.invoke.assert_not_called()
    assert result["order_conversation_summary"] is None
    assert result["messages"] == conversation + [final_response]


# With more than 3 turns and the token count over threshold, condensation folds
# every turn older than the last 3 into order_conversation_summary and removes
# those messages from state["messages"], while the last 3 turns remain intact. (base)
def test_call_model_condenses_older_turns_when_over_threshold(monkeypatch):
    final_response = AIMessage(content="Sure thing!")
    summary_response = AIMessage(content="Customer added kung pao chicken.")
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = summary_response
    fake_llm.bind_tools.return_value.invoke.return_value = final_response
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: fake_llm)

    conversation = _conversation(
        4, last_turn_tokens=order_support_agent.ORDER_HISTORY_TOKEN_THRESHOLD + 1
    )
    state = _base_state("turn 5 query")
    state["messages"] = conversation

    result = call_model(state)

    assert result["order_conversation_summary"] == "Customer added kung pao chicken."
    removed_ids = {m.id for m in result["messages"] if isinstance(m, RemoveMessage)}
    assert removed_ids == {"h1", "a1"}
    retained = [m for m in result["messages"] if not isinstance(m, RemoveMessage)]
    assert retained == conversation[2:] + [final_response]


# Re-condensing later in the same conversation replaces the prior summary wholesale
# rather than appending to it. (base)
def test_call_model_recondenses_replacing_old_summary(monkeypatch):
    final_response = AIMessage(content="Sure thing!")
    new_summary_response = AIMessage(content="Only the new summary text.")
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = new_summary_response
    fake_llm.bind_tools.return_value.invoke.return_value = final_response
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: fake_llm)

    conversation = _conversation(
        4, last_turn_tokens=order_support_agent.ORDER_HISTORY_TOKEN_THRESHOLD + 1
    )
    state = _base_state("turn 5 query")
    state["messages"] = conversation
    state["order_conversation_summary"] = "The old summary text."

    result = call_model(state)

    assert result["order_conversation_summary"] == "Only the new summary text."
    assert "old summary" not in result["order_conversation_summary"].lower()


# When the condensation model call itself raises, call_model still returns a normal
# reply for that turn and leaves messages/order_conversation_summary unchanged;
# no exception propagates out of call_model. (error)
def test_call_model_condensation_failure_is_silent(monkeypatch):
    final_response = AIMessage(content="Sure thing!")
    fake_llm = MagicMock()
    fake_llm.invoke.side_effect = RuntimeError("condensation model unavailable")
    fake_llm.bind_tools.return_value.invoke.return_value = final_response
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: fake_llm)

    conversation = _conversation(
        4, last_turn_tokens=order_support_agent.ORDER_HISTORY_TOKEN_THRESHOLD + 1
    )
    state = _base_state("turn 5 query")
    state["messages"] = conversation

    result = call_model(state)

    assert result["order_conversation_summary"] is None
    assert result["messages"] == conversation + [final_response]


# The token-count estimate never calls get_num_tokens_from_messages() on the LLM
# client, since that raises NotImplementedError for OpenRouter-style "vendor/model"
# names (e.g. "openai/gpt-4o-mini") regardless of which model actually handles the
# call. (regression) — guards the fix for that crash.
def test_call_model_never_calls_get_num_tokens_from_messages(monkeypatch):
    final_response = AIMessage(content="Sure thing!")
    fake_llm = MagicMock()
    fake_llm.bind_tools.return_value.invoke.return_value = final_response
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: fake_llm)

    conversation = _conversation(4)
    state = _base_state("turn 5 query")
    state["messages"] = conversation

    call_model(state)

    fake_llm.get_num_tokens_from_messages.assert_not_called()


# When the last AIMessage carries provider-reported usage_metadata, the token
# estimate uses its input_tokens directly rather than falling back to a
# character-count heuristic. (base)
def test_estimate_token_count_uses_usage_metadata_when_present():
    conversation = _conversation(4, last_turn_tokens=12_345)

    assert order_support_agent._estimate_token_count(conversation) == 12_345


# When no message carries usage_metadata (e.g. no reply has been generated yet),
# the token estimate falls back to a rough per-character heuristic instead of
# raising or returning zero for a non-empty conversation. (edge)
def test_estimate_token_count_falls_back_to_character_heuristic_without_usage_metadata():
    conversation = _conversation(4)

    estimate = order_support_agent._estimate_token_count(conversation)

    expected = sum(len(str(m.content)) for m in conversation) // 4
    assert estimate == expected
    assert estimate > 0
