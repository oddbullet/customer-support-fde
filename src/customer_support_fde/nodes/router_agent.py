from typing import Literal

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError

from customer_support_fde.nodes.common import build_llm
from customer_support_fde.state import SupportState

SYSTEM_PROMPT = """\
You are the routing agent for a Chinese restaurant's customer support system. \
Assume all customer input is in English.

Classify the customer's request into exactly one destination:
- "order_support": a menu, ingredient/allergy, or ordering question.
- "refund": a complaint about a past order (cold food, a missing item, a \
late delivery, a wrong dish, or a repeated problem with past orders) or an \
explicit refund/money-back request. Route a past-order complaint to \
"refund" even when the customer never uses refund or money-back language — \
do not require that language before choosing "refund". When a message both \
describes a past-order complaint and explicitly asks for a refund, treat it \
as a single "refund" case rather than the mixed-signal case below.
- "unclear": the request has no clear order/support-vs-refund signal, or it \
mixes both order/support and refund signals in the same message (for \
example, a past-order complaint paired with an unrelated menu/ordering \
question). Never guess between "order_support" and "refund" for these \
requests. A complaint with no connection to a past order (for example, \
about restaurant hours, ambiance, or the website) is not a refund \
complaint — do not route it to "refund".

Always also assess sentiment as "positive", "neutral", or "negative", \
regardless of which destination you choose. If the request is refund-related \
but too short or otherwise gives no discernible emotional signal, use your \
best-effort judgment and default to "neutral" rather than omitting a value.
"""


class RouterDecision(BaseModel):
    destination: Literal["order_support", "refund", "unclear"]
    sentiment: Literal["positive", "neutral", "negative"]


def _build_llm() -> ChatOpenAI:
    return build_llm().with_structured_output(RouterDecision)


def router_agent(state: SupportState) -> SupportState:
    try:
        decision = _build_llm().invoke(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": state["user_query"]},
            ]
        )
    except ValidationError:
        # The model returned a destination/sentiment shape that doesn't match
        # RouterDecision (research.md §6) — not a call failure (FR-011 still
        # propagates those), so fall back to the same "ask the customer"
        # path used for any other ambiguous/mixed-signal request.
        destination: Literal["order_support", "refund", "unclear"] = "unclear"
        sentiment: Literal["positive", "neutral", "negative"] | None = "neutral"
    else:
        destination = decision.destination
        sentiment = decision.sentiment if destination != "order_support" else None

    return {
        "user_query": state["user_query"],
        "destination": destination,
        "sentiment": sentiment,
    }
