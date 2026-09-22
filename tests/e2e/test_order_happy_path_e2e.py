import uuid

import pytest
from langgraph.checkpoint.memory import MemorySaver

from customer_support_fde.graph import build_graph

from _driver import drive_conversation
from _judge import judge

pytestmark = pytest.mark.e2e


# A guest orders two real menu items across a couple of turns, confirms, and
# the conversation ends with a correctly-totaled order recorded and reflected
# back to the customer. (base)
def test_guest_orders_two_items_and_confirms(e2e_db):
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    transcript = drive_conversation(
        graph,
        config,
        query="I'd like to order one Kung Pao Chicken and one Spring Rolls, please.",
        script=["No, that's everything — please confirm my order."],
    )

    assert not transcript.hit_cap, transcript.format()
    final_state = transcript.final_result
    assert "__interrupt__" not in final_state, transcript.format()
    assert final_state["order_confirmed"] is True, transcript.format()

    verdict = judge(
        rubric=(
            "Across the conversation, the assistant must have clearly "
            "confirmed an order containing one Kung Pao Chicken and one "
            "Spring Rolls, at a total of $19.90, with nothing invented and "
            "nothing dropped. Nothing later in the conversation may "
            "contradict that confirmation."
        ),
        transcript=transcript.format(),
        ground_truth=(
            "An order was recorded with lines Kung Pao Chicken x1 ($12.95) "
            "and Spring Rolls x1 ($6.95), total $19.90. The order id is not "
            "part of this rubric - the system may display it formatted "
            "with a dash (e.g. ZTV8-4JH1); that is not an invented detail."
        ),
    )
    assert verdict.verdict == "pass", verdict.reasoning
