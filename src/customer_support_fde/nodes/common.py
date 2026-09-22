import os
from typing import Callable

from langchain_core.messages import AIMessage, AnyMessage, SystemMessage
from langchain_openai import ChatOpenAI

DEFAULT_MODEL = "openai/gpt-4o-mini"

HISTORY_TOKEN_THRESHOLD = 40_000

# Retries for a failed OpenRouter request, on top of the initial attempt. Applied by the
# underlying OpenAI client and backed off between attempts, so it covers the HTTP call at
# every call site, including the ones built by .bind_tools() and .with_structured_output().
# Only the request is retried — tool functions run in ToolNode, outside this scope.
LLM_MAX_RETRIES = 3


def build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ.get("OPENROUTER_API_KEY"),
        model=os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL),
        max_retries=LLM_MAX_RETRIES,
    )


def estimate_token_count(messages: list[AnyMessage]) -> int:
    # get_num_tokens_from_messages() raises NotImplementedError for OpenRouter-style
    # "vendor/model" names regardless of the underlying model, so estimate from the
    # last real reply's provider-reported prompt size instead, falling back to a
    # rough per-character estimate before any usage data exists.
    for message in reversed(messages):
        if isinstance(message, AIMessage) and message.usage_metadata:
            return message.usage_metadata.get("input_tokens", 0)
    return sum(len(str(message.content)) for message in messages) // 4


def condense_messages(
    llm: ChatOpenAI,
    older_messages: list[AnyMessage],
    instructions: str,
    previous_summary: str | None,
) -> str | None:
    try:
        condense_input: list[AnyMessage] = [SystemMessage(content=instructions)]
        if previous_summary is not None:
            condense_input.append(
                SystemMessage(content=f"Previous summary:\n{previous_summary}")
            )
        condense_input.extend(older_messages)
        return llm.invoke(condense_input).content
    except Exception:
        return None


def prompt_until(
    interrupt_fn: Callable[[str], object], question: str, valid_answers: set[str]
) -> str:
    answer = str(interrupt_fn(question)).strip()
    while answer not in valid_answers:
        answer = str(interrupt_fn(question)).strip()
    return answer


__all__ = [
    "DEFAULT_MODEL",
    "HISTORY_TOKEN_THRESHOLD",
    "LLM_MAX_RETRIES",
    "build_llm",
    "estimate_token_count",
    "condense_messages",
    "prompt_until",
]
