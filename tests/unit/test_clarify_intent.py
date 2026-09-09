from unittest.mock import MagicMock

import pytest

from customer_support_fde import clarify_intent as clarify_intent_module
from customer_support_fde.clarify_intent import QUESTION, clarify_intent
from customer_support_fde.state import SupportState


@pytest.mark.parametrize("answer", ["1", "2"])
def test_order_support_answers_resolve_destination_with_no_sentiment(
    monkeypatch, answer
):
    monkeypatch.setattr(
        clarify_intent_module, "interrupt", MagicMock(return_value=answer)
    )
    state: SupportState = {
        "user_query": "hello",
        "destination": "unclear",
        "sentiment": "neutral",
    }

    result = clarify_intent(state)

    assert result["destination"] == "order_support"
    assert result["sentiment"] is None


def test_refund_answer_forwards_the_sentiment_already_in_state(monkeypatch):
    monkeypatch.setattr(
        clarify_intent_module,
        "interrupt",
        MagicMock(return_value="3"),
    )
    state: SupportState = {
        "user_query": "the food I ordered was cold, and also what's in the mapo tofu?",
        "destination": "unclear",
        "sentiment": "negative",
    }

    result = clarify_intent(state)

    assert result["destination"] == "refund"
    assert result["sentiment"] == "negative"


def test_unrecognized_answer_re_asks_the_same_question(monkeypatch):
    fake_interrupt = MagicMock(side_effect=["banana", "3"])
    monkeypatch.setattr(clarify_intent_module, "interrupt", fake_interrupt)
    state: SupportState = {
        "user_query": "hello",
        "destination": "unclear",
        "sentiment": "neutral",
    }

    result = clarify_intent(state)

    assert fake_interrupt.call_count == 2
    for call in fake_interrupt.call_args_list:
        assert call.args[0] == QUESTION
    assert result["destination"] == "refund"
    assert result["sentiment"] == "neutral"
