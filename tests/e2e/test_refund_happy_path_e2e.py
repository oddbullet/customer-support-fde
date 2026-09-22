import uuid

import pytest
from langgraph.checkpoint.memory import MemorySaver

from customer_support_fde.graph import build_graph

from _driver import drive_conversation
from _judge import judge
from conftest import seed_order

pytestmark = pytest.mark.e2e


# A recent order where an ordered item never arrived and nothing came in its
# place results in a submitted refund request for the correct amount. (base)
def test_missing_item_gets_refund(e2e_db):
    order_id = seed_order(
        e2e_db,
        [
            {
                "name": "Mapo Tofu",
                "quantity": 2,
                "unit_price": 11.50,
                "line_total": 23.00,
            }
        ],
        age_hours=2,
    )

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    transcript = drive_conversation(
        graph,
        config,
        query=(
            f"Hi, I placed order {order_id} and I never received my Mapo "
            "Tofu - nothing else arrived in its place. I'd like a refund."
        ),
        script=[
            "No, nothing else arrived in its place.",
            "No, that's everything - please go ahead.",
        ],
    )

    assert not transcript.hit_cap, transcript.format()

    verdict = judge(
        rubric=(
            "Across the conversation, the assistant must have clearly told "
            "the customer their refund request was submitted (awaiting "
            "review) for $23.00 - never that it is already complete. "
            "Nothing later in the conversation may contradict that."
        ),
        transcript=transcript.format(),
        ground_truth=(
            f"A pending refund request for order {order_id} was created "
            "for $23.00 (2 units of Mapo Tofu that never arrived)."
        ),
    )
    assert verdict.verdict == "pass", verdict.reasoning
