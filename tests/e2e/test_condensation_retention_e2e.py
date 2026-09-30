"""Context retention after conversation condensation, judged by an LLM (real OpenRouter
calls). The threshold is dropped to 1 token so every turn boundary condenses, letting a
short conversation exercise retention.
"""

import uuid

import pytest
from langgraph.checkpoint.memory import MemorySaver

from customer_support_fde import db
from customer_support_fde.graph import build_graph
from customer_support_fde.nodes import order_support_agent, refund_agent

from _driver import drive_conversation
from _judge import judge
from conftest import seed_order

pytestmark = pytest.mark.e2e


@pytest.fixture(autouse=True)
def _condense_every_turn(monkeypatch):
    monkeypatch.setattr(order_support_agent, "ORDER_HISTORY_TOKEN_THRESHOLD", 1)
    monkeypatch.setattr(refund_agent, "REFUND_HISTORY_TOKEN_THRESHOLD", 1)


def _new_graph():
    graph = build_graph(checkpointer=MemorySaver())
    return graph, {"configurable": {"thread_id": str(uuid.uuid4())}}


# A peanut allergy stated in the first message is condensed away, yet the agent's later
# recommendation still avoids peanuts. (edge)
def test_judge_allergy_retained_after_condensation(e2e_db):
    graph, config = _new_graph()
    first_message = "Hi! Just so you know, I'm severely allergic to peanuts."

    transcript = drive_conversation(
        graph,
        config,
        query=first_message,
        script=[
            "What soups do you have?",
            "What's in the Spring Rolls?",
            "How much is the Beef Chow Fun?",
            "What would you recommend for my main dish?",
        ],
        max_turns=5,
    )

    state = graph.get_state(config).values
    assert state["order_conversation_summary"], transcript.format()
    assert all(m.content != first_message for m in state["messages"]), transcript.format()

    verdict = judge(
        rubric=(
            "The customer said they are severely allergic to peanuts at the start. The "
            "assistant's final reply recommends a main dish. It must not recommend any "
            "dish containing peanuts, and it should account for the allergy."
        ),
        transcript=transcript.format(),
        ground_truth=(
            "Only Kung Pao Chicken contains peanuts. Mapo Tofu, Spring Rolls, Hot and "
            "Sour Soup, Beef Chow Fun, and Vegetable Fried Rice contain no peanuts."
        ),
    )
    assert verdict.verdict == "pass", verdict.reasoning


# Refund facts given early (order id, missing dish, no substitute) are condensed away, yet
# the agent neither re-asks for them nor reaches the wrong policy outcome. (edge)
def test_judge_refund_facts_retained_after_condensation(e2e_db):
    order_id = seed_order(
        e2e_db,
        [
            {"name": "Mapo Tofu", "quantity": 2, "unit_price": 10.0, "line_total": 20.0},
            {"name": "Spring Rolls", "quantity": 1, "unit_price": 6.95, "line_total": 6.95},
        ],
        age_hours=1,
    )
    graph, config = _new_graph()

    transcript = drive_conversation(
        graph,
        config,
        query=f"Hi, I have a problem with my order {order_id}.",
        script=[
            "Both of the Mapo Tofu never arrived, and nothing came in their place.",
            "Sorry, one second, someone is at the door.",
            "Ok, I'm back. How long do refunds usually take?",
            "Alright. Please go ahead with the refund.",
            "No, that's everything.",
        ],
        max_turns=8,
        fallback="No, that's everything, thanks.",
    )

    state = graph.get_state(config).values
    assert state["refund_conversation_summary"], transcript.format()
    stored = db.list_refund_requests(e2e_db)

    verdict = judge(
        rubric=(
            "The customer gave their order id and said both Mapo Tofu never arrived with "
            "no substitute early on. After that, the assistant must not ask again for the "
            "order id or which dish was missing, and what it tells the customer about the "
            "refund must match the ground truth."
        ),
        transcript=transcript.format(),
        ground_truth=(
            f"Order {order_id} (placed 1 hour ago): Mapo Tofu x2 at $10.00 each and "
            "Spring Rolls x1. Refund requests recorded in the database: "
            f"{[(r['order_id'], r['amount']) for r in stored]}."
        ),
    )
    assert verdict.verdict == "pass", verdict.reasoning
