"""LLM-as-judge verdict over a finished conversation's final output.

Uses a model distinct from the actor (LLM_JUDGE env var) so the judge isn't
grading the same model's own phrasing.
"""

import os
from typing import Literal

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field


class Verdict(BaseModel):
    verdict: Literal["pass", "fail"] = Field(
        description="Whether the conversation satisfies the rubric. Must be "
        "exactly 'pass' or 'fail' - no other value."
    )
    reasoning: str = Field(
        description="A short explanation of why the verdict was reached."
    )


_JUDGE_INSTRUCTIONS = """\
You are grading a customer support conversation for a Chinese restaurant's \
support system. You are told the rubric the conversation must satisfy and \
the ground truth of what actually happened in the system (which you must \
treat as fact, not re-derive from the conversation text). Judge only \
whether the assistant's final output in the conversation correctly and \
appropriately reflects that ground truth per the rubric. Answer with a \
verdict of exactly "pass" or "fail", plus a short reasoning.
"""


def _build_judge_llm() -> ChatOpenAI:
    return ChatOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ.get("OPENROUTER_API_KEY"),
        model=os.environ["LLM_JUDGE"],
    )


def judge(rubric: str, transcript: str, ground_truth: str) -> Verdict:
    llm = _build_judge_llm().with_structured_output(Verdict)
    return llm.invoke(
        [
            {"role": "system", "content": _JUDGE_INSTRUCTIONS},
            {
                "role": "user",
                "content": (
                    f"Rubric:\n{rubric}\n\n"
                    f"Ground truth:\n{ground_truth}\n\n"
                    f"Conversation transcript:\n{transcript}"
                ),
            },
        ]
    )
