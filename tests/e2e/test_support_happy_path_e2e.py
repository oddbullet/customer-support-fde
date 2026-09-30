import uuid

import pytest
from langgraph.checkpoint.memory import MemorySaver

from customer_support_fde.graph import build_graph

from _driver import drive_conversation
from _judge import judge

pytestmark = pytest.mark.e2e


# A guest asks an ingredient/allergy question and gets a faithful,
# menu-grounded answer with a peanut-free recommendation - no ordering
# involved. (happy)
def test_allergy_question_gets_faithful_recommendation(e2e_db):
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    transcript = drive_conversation(
        graph,
        config,
        query=(
            "Does the Kung Pao Chicken have peanuts in it? I have a peanut "
            "allergy."
        ),
        script=[
            "Yes, a peanut allergy - what would you recommend instead?",
        ],
        max_turns=2,
    )

    verdict = judge(
        rubric=(
            "The assistant must correctly state that Kung Pao Chicken "
            "contains peanuts, and when asked for an alternative, "
            "recommend only a dish that does not contain peanuts, without "
            "inventing menu items, prices, or ingredients not backed by "
            "the actual menu."
        ),
        transcript=transcript.format(),
        ground_truth=(
            "The full menu is: Kung Pao Chicken $12.95 (chicken, peanuts, "
            "dried chili, bell pepper, scallion); Mapo Tofu $11.50 (tofu, "
            "ground pork, chili bean paste, scallion, sichuan peppercorn); "
            "Spring Rolls $6.95 (cabbage, carrot, wood ear mushroom, wheat "
            "wrapper); Hot and Sour Soup $5.50 (tofu, wood ear mushroom, "
            "egg, bamboo shoot, white pepper, vinegar); Beef Chow Fun "
            "$13.50 (beef, rice noodle, bean sprout, scallion, soy sauce); "
            "Vegetable Fried Rice $9.95 (rice, egg, carrot, peas, scallion, "
            "soy sauce). Only Kung Pao Chicken contains peanuts, so any "
            "price, ingredient, or peanut-free claim about a dish must "
            "match this data to count as faithful rather than invented."
        ),
    )
    assert verdict.verdict == "pass", verdict.reasoning
