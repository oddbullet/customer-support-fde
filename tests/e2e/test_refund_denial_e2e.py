import uuid

import pytest
from langgraph.checkpoint.memory import MemorySaver

from customer_support_fde.graph import build_graph

from _driver import drive_conversation
from _judge import judge
from conftest import seed_order

pytestmark = pytest.mark.e2e


# A correctly-delivered order complained about only for being cold and late
# is denied a refund - no refund request is created, a complaint is logged
# with the specific policy reason, and the customer is told why. (failure)
def test_correctly_delivered_order_complaint_is_denied(e2e_db):
    order_id = seed_order(
        e2e_db,
        [
            {
                "name": "Kung Pao Chicken",
                "quantity": 1,
                "unit_price": 12.95,
                "line_total": 12.95,
            }
        ],
        age_hours=1,
    )

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    transcript = drive_conversation(
        graph,
        config,
        query=(
            f"My order {order_id} just arrived, but the food was cold and "
            "delivery was really late. I want my money back."
        ),
        script=[
            "No items were missing - everything on the order arrived, it "
            "was just cold and late.",
            "No, that's everything.",
        ],
    )

    assert not transcript.hit_cap, transcript.format()

    verdict = judge(
        rubric=(
            "Across the conversation, the assistant must have clearly "
            "denied the refund and stated the specific reason: a refund "
            "only applies when an ordered item was not received, and this "
            "complaint (cold, late food) does not describe a missing item. "
            "A conversation that never states any reason - only a generic "
            "apology or rejection - must fail this rubric. It's fine if a "
            "later message is a brief generic closing (e.g. 'anything "
            "else?') as long as the reason was clearly stated earlier and "
            "nothing later claims a refund was granted."
        ),
        transcript=transcript.format(),
        ground_truth=(
            f"No refund request was created for order {order_id}. A "
            "complaint was logged with policy_reason='no_undelivered_items' "
            "(refunds only apply when an ordered item was not received)."
        ),
    )
    assert verdict.verdict == "pass", verdict.reasoning
