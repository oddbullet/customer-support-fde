from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from customer_support_fde.nodes import router_agent
from customer_support_fde.nodes.router_agent import RouterDecision
from customer_support_fde.state import SupportState


def _fake_llm(decision: RouterDecision) -> MagicMock:
    llm = MagicMock()
    llm.invoke.return_value = decision
    return llm


# A clear order/menu query routes to order_support and carries no sentiment. (base)
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


# A clear complaint routes to refund and carries the negative sentiment through. (base)
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


# Regardless of which of the three sentiment values the LLM returns, it passes through unchanged.
# "negative" is covered by test_refund_query_carries_negative_sentiment above with a
# stronger (exact-equality) assertion, so only the two values not covered elsewhere are
# parametrized here. (edge)
@pytest.mark.parametrize("sentiment", ["positive", "neutral"])
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


# Vague or mixed-signal queries stay "unclear" and keep whatever sentiment was returned. (edge)
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


# A past-order complaint with no refund/money-back language still routes to refund
# with sentiment attached, mirroring spec.md User Story 1 Acceptance Scenarios 1-3. (base)
@pytest.mark.parametrize(
    "query",
    [
        "My order arrived 45 minutes late and the food was cold",
        "The spring rolls I got were missing from my bag",
        "This is the second time my order has been wrong",
    ],
)
def test_complaint_only_query_routes_to_refund_with_sentiment(monkeypatch, query):
    monkeypatch.setattr(
        router_agent,
        "_build_llm",
        lambda: _fake_llm(RouterDecision(destination="refund", sentiment="negative")),
    )
    state: SupportState = {
        "user_query": query,
        "destination": "order_support",
        "sentiment": None,
    }

    result = router_agent.router_agent(state)

    assert result["destination"] == "refund"
    assert result["sentiment"] is not None


# A message combining a past-order complaint with an explicit refund ask routes
# directly to refund (never unclear), mirroring spec.md User Story 2 Acceptance
# Scenarios 1-2. (base)
@pytest.mark.parametrize(
    "query",
    [
        "My order arrived cold and an hour late, I want my money back",
        "The dish had peanuts in it even though I asked for none — can I get a refund?",
    ],
)
def test_complaint_plus_refund_ask_query_routes_directly_to_refund(monkeypatch, query):
    monkeypatch.setattr(
        router_agent,
        "_build_llm",
        lambda: _fake_llm(RouterDecision(destination="refund", sentiment="negative")),
    )
    state: SupportState = {
        "user_query": query,
        "destination": "order_support",
        "sentiment": None,
    }

    result = router_agent.router_agent(state)

    assert result["destination"] == "refund"
    assert result["sentiment"] is not None


# An LLM call failure in router_agent raises rather than returning partial state. (error)
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


# A model reply that doesn't fit RouterDecision (pydantic ValidationError) falls back
# to "unclear" with neutral sentiment instead of raising. (error)
def test_malformed_structured_output_falls_back_to_unclear(monkeypatch):
    with pytest.raises(ValidationError) as excinfo:
        RouterDecision.model_validate({"destination": "kitchen", "sentiment": "angry"})
    malformed_llm = MagicMock()
    malformed_llm.invoke.side_effect = excinfo.value
    monkeypatch.setattr(router_agent, "_build_llm", lambda: malformed_llm)
    state: SupportState = {
        "user_query": "hello",
        "destination": "order_support",
        "sentiment": None,
    }

    result = router_agent.router_agent(state)

    assert result["destination"] == "unclear"
    assert result["sentiment"] == "neutral"
