import uuid
from unittest.mock import MagicMock

import pytest
from agentevals.graph_trajectory.strict import graph_trajectory_strict_match
from agentevals.graph_trajectory.utils import (
    extract_langgraph_trajectory_from_thread,
)
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from customer_support_fde import router_agent
from customer_support_fde.graph import build_graph
from customer_support_fde.router_agent import RouterDecision


def _fake_llm(decision: RouterDecision) -> MagicMock:
    llm = MagicMock()
    llm.invoke.return_value = decision
    return llm


def _run_and_extract_trajectory(graph, initial_state):
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    graph.invoke(initial_state, config)
    extracted = extract_langgraph_trajectory_from_thread(graph, config)
    return extracted["outputs"]


def test_order_support_style_request_routes_through_order_support_agent(monkeypatch):
    monkeypatch.setattr(
        router_agent,
        "_build_llm",
        lambda: _fake_llm(
            RouterDecision(destination="order_support", sentiment="positive")
        ),
    )
    graph = build_graph(checkpointer=MemorySaver())
    initial_state = {
        "user_query": "What's in the kung pao chicken, does it have peanuts?",
        "destination": "order_support",
        "sentiment": None,
    }

    actual = _run_and_extract_trajectory(graph, initial_state)

    result = graph_trajectory_strict_match(
        outputs=actual,
        reference_outputs={
            "steps": [["__start__", "router_agent", "order_support_agent"]],
        },
    )
    assert result["score"] is True


def test_refund_style_request_routes_through_refund_agent(monkeypatch):
    monkeypatch.setattr(
        router_agent,
        "_build_llm",
        lambda: _fake_llm(RouterDecision(destination="refund", sentiment="negative")),
    )
    graph = build_graph(checkpointer=MemorySaver())
    initial_state = {
        "user_query": "My order arrived cold and an hour late, I want my money back",
        "destination": "order_support",
        "sentiment": None,
    }

    actual = _run_and_extract_trajectory(graph, initial_state)

    result = graph_trajectory_strict_match(
        outputs=actual,
        reference_outputs={
            "steps": [["__start__", "router_agent", "refund_agent"]],
        },
    )
    assert result["score"] is True


@pytest.mark.parametrize(
    "query",
    [
        "hello",
        "the food I ordered was cold, and also what's in the mapo tofu?",
    ],
)
@pytest.mark.parametrize(
    "answer,expected_final_node",
    [
        ("1", "order_support_agent"),
        ("2", "order_support_agent"),
        ("3", "refund_agent"),
    ],
)
def test_ambiguous_or_mixed_signal_request_resolved_via_clarify_intent(
    monkeypatch, query, answer, expected_final_node
):
    monkeypatch.setattr(
        router_agent,
        "_build_llm",
        lambda: _fake_llm(RouterDecision(destination="unclear", sentiment="neutral")),
    )
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    initial_state = {
        "user_query": query,
        "destination": "order_support",
        "sentiment": None,
    }

    first_result = graph.invoke(initial_state, config)
    assert "__interrupt__" in first_result

    graph.invoke(Command(resume=answer), config)
    actual = extract_langgraph_trajectory_from_thread(graph, config)["outputs"]

    result = graph_trajectory_strict_match(
        outputs=actual,
        reference_outputs={
            "steps": [
                ["__start__", "router_agent", "clarify_intent", "__interrupt__"],
                [expected_final_node],
            ],
        },
    )
    assert result["score"] is True


# Labeled sample set (spec.md Edge Cases + primary flows): each entry is
# (query, RouterDecision the LLM boundary is faked to return, clarify_intent
# answer to resume with if the decision is "unclear", expected final node).
LABELED_SAMPLES = [
    (
        "What's in the kung pao chicken, does it have peanuts?",
        RouterDecision(destination="order_support", sentiment="positive"),
        None,
        "order_support_agent",
    ),
    (
        "Can I order two spring rolls and a bowl of hot and sour soup?",
        RouterDecision(destination="order_support", sentiment="neutral"),
        None,
        "order_support_agent",
    ),
    (
        "Do you have any vegetarian options on the menu?",
        RouterDecision(destination="order_support", sentiment="neutral"),
        None,
        "order_support_agent",
    ),
    (
        "What time do you close tonight?",
        RouterDecision(destination="order_support", sentiment="neutral"),
        None,
        "order_support_agent",
    ),
    (
        "My order arrived cold and an hour late, I want my money back",
        RouterDecision(destination="refund", sentiment="negative"),
        None,
        "refund_agent",
    ),
    (
        "I'd like to request a refund for my last order please, thanks",
        RouterDecision(destination="refund", sentiment="neutral"),
        None,
        "refund_agent",
    ),
    (
        "This is unacceptable! My food never arrived and nobody is answering the phone!",
        RouterDecision(destination="refund", sentiment="negative"),
        None,
        "refund_agent",
    ),
    (
        "I got charged twice for the same order, can you refund the extra charge?",
        RouterDecision(destination="refund", sentiment="negative"),
        None,
        "refund_agent",
    ),
    (
        "hello",
        RouterDecision(destination="unclear", sentiment="neutral"),
        "2",
        "order_support_agent",
    ),
    (
        "the food I ordered was cold, and also what's in the mapo tofu?",
        RouterDecision(destination="unclear", sentiment="negative"),
        "3",
        "refund_agent",
    ),
    (
        "???",
        RouterDecision(destination="unclear", sentiment="neutral"),
        "1",
        "order_support_agent",
    ),
    (
        "I want to place an order but also the last one was refunded wrong",
        RouterDecision(destination="unclear", sentiment="negative"),
        "3",
        "refund_agent",
    ),
]


def test_labeled_sample_set_routes_to_the_expected_destination_at_least_90_percent(
    monkeypatch,
):
    correct = 0
    for query, decision, resume_answer, expected_final_node in LABELED_SAMPLES:
        monkeypatch.setattr(
            router_agent, "_build_llm", lambda decision=decision: _fake_llm(decision)
        )
        graph = build_graph(checkpointer=MemorySaver())
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        initial_state = {
            "user_query": query,
            "destination": "order_support",
            "sentiment": None,
        }

        result = graph.invoke(initial_state, config)
        if resume_answer is not None:
            assert "__interrupt__" in result
            result = graph.invoke(Command(resume=resume_answer), config)

        actual_destination = (
            "order_support"
            if expected_final_node == "order_support_agent"
            else "refund"
        )
        if result["destination"] == actual_destination:
            correct += 1

    accuracy = correct / len(LABELED_SAMPLES)
    assert accuracy >= 0.90
