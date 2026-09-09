from unittest.mock import MagicMock

import pytest

from customer_support_fde import router_agent
from customer_support_fde.router_agent import RouterDecision
from customer_support_fde.state import SupportState


def _fake_llm(decision: RouterDecision) -> MagicMock:
    llm = MagicMock()
    llm.invoke.return_value = decision
    return llm


def test_order_support_query_has_no_sentiment(monkeypatch):
    monkeypatch.setattr(
        router_agent,
        "_build_llm",
        lambda: _fake_llm(
            RouterDecision(destination="order_support", sentiment="positive")
        ),
    )
    query = "What's in the kung pao chicken, does it have peanuts?"
    state: SupportState = {
        "user_query": query,
        "destination": "order_support",
        "sentiment": None,
    }

    result = router_agent.router_agent(state)

    assert result["destination"] == "order_support"
    assert result["sentiment"] is None
    assert result["user_query"] == query


def test_refund_query_carries_negative_sentiment(monkeypatch):
    monkeypatch.setattr(
        router_agent,
        "_build_llm",
        lambda: _fake_llm(
            RouterDecision(destination="refund", sentiment="negative")
        ),
    )
    query = "My order arrived cold and an hour late, I want my money back"
    state: SupportState = {
        "user_query": query,
        "destination": "order_support",
        "sentiment": None,
    }

    result = router_agent.router_agent(state)

    assert result["destination"] == "refund"
    assert result["sentiment"] == "negative"
    assert result["user_query"] == query


@pytest.mark.parametrize("sentiment", ["positive", "neutral", "negative"])
def test_refund_sentiment_is_always_one_of_the_three_fixed_categories(
    monkeypatch, sentiment
):
    monkeypatch.setattr(
        router_agent,
        "_build_llm",
        lambda: _fake_llm(RouterDecision(destination="refund", sentiment=sentiment)),
    )
    state: SupportState = {
        "user_query": "refund please",
        "destination": "order_support",
        "sentiment": None,
    }

    result = router_agent.router_agent(state)

    assert result["sentiment"] in ("positive", "neutral", "negative")


@pytest.mark.parametrize(
    "query",
    [
        "hello",
        "the food I ordered was cold, and also what's in the mapo tofu?",
    ],
)
def test_ambiguous_or_mixed_signal_query_stays_unclear_and_keeps_sentiment(
    monkeypatch, query
):
    monkeypatch.setattr(
        router_agent,
        "_build_llm",
        lambda: _fake_llm(RouterDecision(destination="unclear", sentiment="neutral")),
    )
    state: SupportState = {
        "user_query": query,
        "destination": "order_support",
        "sentiment": None,
    }

    result = router_agent.router_agent(state)

    assert result["destination"] == "unclear"
    assert result["sentiment"] == "neutral"


def test_llm_call_failure_propagates_rather_than_returning_partial_state(monkeypatch):
    failing_llm = MagicMock()
    failing_llm.invoke.side_effect = RuntimeError("OpenRouter request failed")
    monkeypatch.setattr(router_agent, "_build_llm", lambda: failing_llm)
    state: SupportState = {
        "user_query": "hello",
        "destination": "order_support",
        "sentiment": None,
    }

    with pytest.raises(RuntimeError):
        router_agent.router_agent(state)
