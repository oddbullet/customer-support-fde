import uuid

import pytest
from langgraph.checkpoint.memory import MemorySaver

from customer_support_fde import db, tickets
from customer_support_fde.graph import build_graph

from _driver import drive_conversation
from _judge import judge
from conftest import seed_order

pytestmark = pytest.mark.e2e


# A refund request written with Chinese characters, emoji, an apostrophe, symbols,
# and SQL-looking text is understood like any other: the refund is submitted for
# the right amount, the database is intact, and the ticket records the issue. (edge)
def test_refund_request_with_special_characters_is_handled(e2e_db):
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
            f"Order {order_id}: my 宫保鸡丁 (Kung Pao Chicken) never arrived 😡 "
            "I paid $12.95 & didn't get it!! '; DROP TABLE complaints; --"
        ),
        script=[
            "没有 - nothing else arrived in its place. 🙏",
            "No, that's everything - please go ahead. 谢谢!",
        ],
    )

    assert not transcript.hit_cap, transcript.format()

    refund = db.get_refund_request_for_order(order_id, e2e_db)
    assert refund is not None, transcript.format()
    assert refund["amount"] == pytest.approx(12.95)

    # The SQL-looking text was stored as plain text, not run: the table still works.
    db.list_complaints(e2e_db)

    ticket_files = list(tickets.tickets_dir().glob(f"refund-{order_id}-*.md"))
    assert len(ticket_files) == 1
    ticket = ticket_files[0].read_text(encoding="utf-8")
    assert "**Issue:** Not recorded" not in ticket

    verdict = judge(
        rubric=(
            "The customer wrote with Chinese characters, emoji, symbols, and "
            "SQL-looking text. The assistant must have understood that the "
            "missing dish was Kung Pao Chicken, told the customer a refund "
            "request was submitted for it, and its replies must be readable, "
            "with no garbled or broken characters. Judge only these points."
        ),
        transcript=transcript.format(),
        ground_truth=(
            f"A pending refund request for order {order_id} was created for "
            "$12.95 (1 Kung Pao Chicken that never arrived)."
        ),
    )
    assert verdict.verdict == "pass", verdict.reasoning
