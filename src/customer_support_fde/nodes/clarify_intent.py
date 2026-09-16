from langgraph.types import interrupt

from customer_support_fde.nodes.common import prompt_until
from customer_support_fde.state import SupportState

QUESTION = (
    "Are you: (1) placing an order, (2) asking a general question, "
    "or (3) requesting a refund? Reply with 1, 2, or 3."
)

_ORDER_SUPPORT_ANSWERS = {"1", "2"}
_REFUND_ANSWERS = {"3"}


def clarify_intent(state: SupportState) -> SupportState:
    answer = prompt_until(interrupt, QUESTION, _ORDER_SUPPORT_ANSWERS | _REFUND_ANSWERS)

    if answer in _ORDER_SUPPORT_ANSWERS:
        return {
            "user_query": state["user_query"],
            "destination": "order_support",
            "sentiment": None,
        }

    return {
        "user_query": state["user_query"],
        "destination": "refund",
        "sentiment": state["sentiment"],
    }
