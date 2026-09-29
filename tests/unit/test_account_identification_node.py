from unittest.mock import MagicMock

import pytest

from customer_support_fde.nodes import account_identification_node as node_module
from customer_support_fde.nodes.account_identification_node import (
    ACCOUNT_NUMBER_PROMPT,
    PRIMARY_MENU,
    RECOVERY_MENU,
    account_identification_node,
)
from customer_support_fde.state import SupportState


def _base_state() -> SupportState:
    return {
        "account_number": None,
        "account_preferences": None,
        "tool_limit_reached": None,
    }


# An unrecognized reply to the primary menu re-issues the identical prompt and does
# not advance to any of the three outcomes. (edge)
def test_unrecognized_primary_menu_reply_re_asks_the_same_question(monkeypatch):
    fake_interrupt = MagicMock(side_effect=["banana", "2"])
    monkeypatch.setattr(node_module, "interrupt", fake_interrupt)
    state = _base_state()

    result = account_identification_node(state)

    assert fake_interrupt.call_count == 2
    for call in fake_interrupt.call_args_list:
        assert call.args[0] == PRIMARY_MENU
    assert result == {"account_number": None, "account_preferences": None}


# Replying "2" returns None/None account fields, with no other outcome reached and
# no account row created. (base)
def test_primary_menu_continue_without_account_returns_none_none(monkeypatch):
    monkeypatch.setattr(node_module, "interrupt", MagicMock(return_value="2"))
    monkeypatch.setattr(
        node_module.db,
        "create_account",
        MagicMock(side_effect=AssertionError("create_account should not be called")),
    )
    state = _base_state()

    result = account_identification_node(state)

    assert result == {"account_number": None, "account_preferences": None}


# Replying "1" then a number db.get_account resolves sets account_number/
# account_preferences from that account's row. (base)
def test_existing_account_found_sets_account_fields_from_row(monkeypatch):
    fake_interrupt = MagicMock(side_effect=["1", "K7QP3M9X"])
    monkeypatch.setattr(node_module, "interrupt", fake_interrupt)
    monkeypatch.setattr(
        node_module.db,
        "get_account",
        MagicMock(
            return_value={
                "account_number": "K7QP3M9X",
                "preferences": "Loves spicy food.",
                "created_at": "2026-01-01T00:00:00.000Z",
            }
        ),
    )
    state = _base_state()

    result = account_identification_node(state)

    assert result == {
        "account_number": "K7QP3M9X",
        "account_preferences": "Loves spicy food.",
    }
    fake_interrupt.assert_any_call(ACCOUNT_NUMBER_PROMPT)


# Replying "1" then a number db.get_account returns None for presents the recovery
# menu instead of any of the three outcomes. (edge)
def test_unknown_account_number_presents_recovery_menu(monkeypatch):
    fake_interrupt = MagicMock(side_effect=["1", "NOTAREAL1", "3"])
    monkeypatch.setattr(node_module, "interrupt", fake_interrupt)
    monkeypatch.setattr(node_module.db, "get_account", MagicMock(return_value=None))
    state = _base_state()

    result = account_identification_node(state)

    assert fake_interrupt.call_args_list[2].args[0] == RECOVERY_MENU
    assert result == {"account_number": None, "account_preferences": None}


# The recovery menu re-prompts on an unrecognized reply the same way the primary
# menu does. (edge)
def test_recovery_menu_re_asks_on_unrecognized_reply(monkeypatch):
    fake_interrupt = MagicMock(
        side_effect=["1", "NOTAREAL1", "banana", "3"]
    )
    monkeypatch.setattr(node_module, "interrupt", fake_interrupt)
    monkeypatch.setattr(node_module.db, "get_account", MagicMock(return_value=None))
    state = _base_state()

    result = account_identification_node(state)

    assert fake_interrupt.call_count == 4
    assert fake_interrupt.call_args_list[2].args[0] == RECOVERY_MENU
    assert fake_interrupt.call_args_list[3].args[0] == RECOVERY_MENU
    assert result == {"account_number": None, "account_preferences": None}


# The recovery menu's "1" (try again) loops back to the account-number prompt and
# succeeds on a subsequent valid number. (edge)
def test_recovery_menu_try_again_loops_back_and_succeeds(monkeypatch):
    fake_interrupt = MagicMock(
        side_effect=["1", "NOTAREAL1", "1", "K7QP3M9X"]
    )
    monkeypatch.setattr(node_module, "interrupt", fake_interrupt)
    fake_get_account = MagicMock(
        side_effect=[
            None,
            {
                "account_number": "K7QP3M9X",
                "preferences": None,
                "created_at": "2026-01-01T00:00:00.000Z",
            },
        ]
    )
    monkeypatch.setattr(node_module.db, "get_account", fake_get_account)
    state = _base_state()

    result = account_identification_node(state)

    assert fake_interrupt.call_args_list[3].args[0] == ACCOUNT_NUMBER_PROMPT
    assert result == {"account_number": "K7QP3M9X", "account_preferences": None}


# Replying "3" at the primary menu calls the (task-wrapped) account creation,
# returns the new number with no preferences, and shows the customer the
# formatted account number. _create_account is mocked directly rather than
# db.create_account because @task requires a real graph run to resolve its
# future, which these direct-call unit tests don't provide. (base)
def test_primary_menu_sign_up_creates_account_and_shows_formatted_number(monkeypatch):
    fake_interrupt = MagicMock(side_effect=["3", "ok"])
    monkeypatch.setattr(node_module, "interrupt", fake_interrupt)
    fake_future = MagicMock()
    fake_future.result.return_value = "K7QP3M9X"
    monkeypatch.setattr(
        node_module, "_create_account", MagicMock(return_value=fake_future)
    )
    state = _base_state()

    result = account_identification_node(state)

    assert result == {"account_number": "K7QP3M9X", "account_preferences": None}
    sign_up_message = fake_interrupt.call_args_list[1].args[0]
    assert node_module.db.format_account_number("K7QP3M9X") in sign_up_message


# The recovery menu's "2" (sign up) reaches the same sign-up outcome as the primary
# menu's "3", after a not-found account number. (edge)
def test_recovery_menu_sign_up_matches_primary_menu_sign_up(monkeypatch):
    fake_interrupt = MagicMock(side_effect=["1", "NOTAREAL1", "2", "ok"])
    monkeypatch.setattr(node_module, "interrupt", fake_interrupt)
    monkeypatch.setattr(node_module.db, "get_account", MagicMock(return_value=None))
    fake_future = MagicMock()
    fake_future.result.return_value = "K7QP3M9X"
    monkeypatch.setattr(
        node_module, "_create_account", MagicMock(return_value=fake_future)
    )
    state = _base_state()

    result = account_identification_node(state)

    assert result == {"account_number": "K7QP3M9X", "account_preferences": None}


def _raise_store_error(*_args, **_kwargs):
    raise node_module.db.OrderStoreError("database is locked")


# If the account lookup fails with a store error, the node stops the workflow by
# letting the error propagate (the CLI turns it into a warning) instead of treating
# the account as not found or continuing without it. (error)
def test_account_lookup_store_error_stops_the_workflow(monkeypatch):
    fake_interrupt = MagicMock(side_effect=["1", "K7QP3M9X"])
    monkeypatch.setattr(node_module, "interrupt", fake_interrupt)
    monkeypatch.setattr(node_module.db, "get_account", _raise_store_error)
    state = _base_state()

    with pytest.raises(node_module.db.OrderStoreError):
        account_identification_node(state)

    prompts = [call.args[0] for call in fake_interrupt.call_args_list]
    assert prompts == [PRIMARY_MENU, ACCOUNT_NUMBER_PROMPT]


# If creating an account fails with a store error, the node stops the workflow by
# letting the error propagate, without showing an account number. (error)
def test_sign_up_store_error_stops_the_workflow(monkeypatch):
    fake_interrupt = MagicMock(side_effect=["3"])
    monkeypatch.setattr(node_module, "interrupt", fake_interrupt)
    fake_future = MagicMock()
    fake_future.result.side_effect = _raise_store_error
    monkeypatch.setattr(
        node_module, "_create_account", MagicMock(return_value=fake_future)
    )
    state = _base_state()

    with pytest.raises(node_module.db.OrderStoreError):
        account_identification_node(state)

    prompts = [call.args[0] for call in fake_interrupt.call_args_list]
    assert prompts == [PRIMARY_MENU]
