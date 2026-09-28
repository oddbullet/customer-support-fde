import logging
from unittest.mock import MagicMock

from langchain_core.messages import HumanMessage

from customer_support_fde import db
from customer_support_fde.nodes import memory_gen_node as memory_gen_node_module
from customer_support_fde.nodes.memory_gen_node import memory_gen_node


def _base_state() -> dict:
    return {
        "user_query": "that's all",
        "destination": "order_support",
        "sentiment": None,
        "messages": [],
        "menu": [],
        "cart_items": {},
        "order_confirmed": True,
        "order_ticket": None,
        "order_summary": None,
        "order_id": None,
        "order_conversation_summary": None,
        "refund_conversation_summary": None,
        "account_number": None,
        "account_preferences": None,
        "tool_limit_reached": None,
    }


# memory_gen_node returns {} immediately when account_number is None (guest),
# without invoking the LLM builder or db.update_account_preferences — a guest
# never triggers extraction or storage. (base, FR-002, SC-002)
def test_memory_gen_node_returns_empty_dict_when_no_account_number(monkeypatch):
    def _raise(*args, **kwargs):
        raise AssertionError("must not be called for a guest")

    monkeypatch.setattr(memory_gen_node_module, "_build_llm", _raise)
    monkeypatch.setattr(db, "update_account_preferences", _raise)
    state = _base_state()
    state["account_number"] = None

    result = memory_gen_node(state)

    assert result == {}


# The guard-clause return touches no other SupportState field. (edge)
def test_memory_gen_node_guest_return_contains_no_other_key():
    state = _base_state()
    state["account_number"] = None

    result = memory_gen_node(state)

    assert list(result.keys()) == []


def _patch_memory_gen_llm(monkeypatch, preferences):
    fake_structured_llm = MagicMock()
    fake_structured_llm.invoke.return_value = (
        memory_gen_node_module._PreferenceExtraction(preferences=preferences)
    )
    fake_llm = MagicMock()
    fake_llm.with_structured_output.return_value = fake_structured_llm
    monkeypatch.setattr(memory_gen_node_module, "_build_llm", lambda: fake_llm)
    return fake_structured_llm


# Account present, no prior preferences, model finds a like/dislike/allergy →
# update_account_preferences is called once with the account number and the
# structured output's preferences field. (base, FR-001, FR-003)
def test_memory_gen_node_calls_update_with_extracted_preferences(monkeypatch):
    _patch_memory_gen_llm(monkeypatch, "Allergies: peanuts. Likes: spicy food.")
    mock_update = MagicMock()
    monkeypatch.setattr(db, "update_account_preferences", mock_update)
    state = _base_state()
    state["account_number"] = "K7QP3M9X"
    state["account_preferences"] = None
    state["messages"] = [
        HumanMessage(content="I'm allergic to peanuts and love spicy food.")
    ]

    result = memory_gen_node(state)

    assert result == {}
    mock_update.assert_called_once_with(
        "K7QP3M9X", "Allergies: peanuts. Likes: spicy food."
    )


# Prior preferences exist → the request sent to the model includes a message
# carrying that prior text, and update_account_preferences is called with the
# structured output's combined preferences field. (base, FR-005)
def test_memory_gen_node_includes_prior_preferences_in_request_and_combines(
    monkeypatch,
):
    fake_structured_llm = _patch_memory_gen_llm(
        monkeypatch, "Allergies: peanuts. Dislikes: onions."
    )
    mock_update = MagicMock()
    monkeypatch.setattr(db, "update_account_preferences", mock_update)
    state = _base_state()
    state["account_number"] = "K7QP3M9X"
    state["account_preferences"] = "Allergies: peanuts."
    state["messages"] = [HumanMessage(content="I don't like onions.")]

    memory_gen_node(state)

    sent_messages = fake_structured_llm.invoke.call_args[0][0]
    assert any("Allergies: peanuts." in m.content for m in sent_messages)
    mock_update.assert_called_once_with(
        "K7QP3M9X", "Allergies: peanuts. Dislikes: onions."
    )


# Structured output's preferences field is null → update_account_preferences
# is NOT called. (edge, FR-006)
def test_memory_gen_node_null_preferences_skips_write(monkeypatch):
    _patch_memory_gen_llm(monkeypatch, None)
    mock_update = MagicMock()
    monkeypatch.setattr(db, "update_account_preferences", mock_update)
    state = _base_state()
    state["account_number"] = "K7QP3M9X"
    state["account_preferences"] = None
    state["messages"] = [HumanMessage(content="Just checking the hours.")]

    result = memory_gen_node(state)

    assert result == {}
    mock_update.assert_not_called()


# The model call raising an exception → the function returns {} and
# update_account_preferences is never called. (error, FR-008)
def test_memory_gen_node_model_call_failure_returns_empty_dict(monkeypatch, caplog):
    fake_structured_llm = MagicMock()
    fake_structured_llm.invoke.side_effect = RuntimeError("model unavailable")
    fake_llm = MagicMock()
    fake_llm.with_structured_output.return_value = fake_structured_llm
    monkeypatch.setattr(memory_gen_node_module, "_build_llm", lambda: fake_llm)
    mock_update = MagicMock()
    monkeypatch.setattr(db, "update_account_preferences", mock_update)
    state = _base_state()
    state["account_number"] = "K7QP3M9X"
    state["account_preferences"] = None
    state["messages"] = [HumanMessage(content="I'm allergic to peanuts.")]

    with caplog.at_level(logging.WARNING):
        result = memory_gen_node(state)

    assert result == {}
    mock_update.assert_not_called()


# db.update_account_preferences raising OrderStoreError → the function
# returns {} and no exception propagates out of memory_gen_node. (error, FR-008)
def test_memory_gen_node_db_write_failure_returns_empty_dict(monkeypatch, caplog):
    _patch_memory_gen_llm(monkeypatch, "Allergies: peanuts.")
    monkeypatch.setattr(
        db,
        "update_account_preferences",
        MagicMock(side_effect=db.OrderStoreError("boom")),
    )
    state = _base_state()
    state["account_number"] = "K7QP3M9X"
    state["account_preferences"] = None
    state["messages"] = [HumanMessage(content="I'm allergic to peanuts.")]

    with caplog.at_level(logging.WARNING):
        result = memory_gen_node(state)

    assert result == {}
