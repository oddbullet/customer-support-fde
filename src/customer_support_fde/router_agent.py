import os
from typing import Literal

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError

from customer_support_fde.state import SupportState

DEFAULT_MODEL = "openai/gpt-4o-mini"

SYSTEM_PROMPT = """\
You are the routing agent for a Chinese restaurant's customer support system. \
Assume all customer input is in English.

Classify the customer's request into exactly one destination:
- "order_support": a menu, ingredient/allergy, or ordering question.
- "refund": a complaint about a past order or a refund request.
- "unclear": the request has no clear order/support-vs-refund signal, or it \
mixes both order/support and refund signals in the same message. Never guess \
between "order_support" and "refund" for these requests.

Always also assess sentiment as "positive", "neutral", or "negative", \
regardless of which destination you choose. If the request is refund-related \
but too short or otherwise gives no discernible emotional signal, use your \
best-effort judgment and default to "neutral" rather than omitting a value.
"""


class RouterDecision(BaseModel):
    destination: Literal["order_support", "refund", "unclear"]
    sentiment: Literal["positive", "neutral", "negative"]


def _build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ.get("OPENROUTER_API_KEY"),
        model=os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL),
    ).with_structured_output(RouterDecision)


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
