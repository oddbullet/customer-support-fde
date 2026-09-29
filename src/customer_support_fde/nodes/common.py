import logging
import os
from typing import Callable

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_openai import ChatOpenAI
from langgraph.prebuilt.tool_node import ToolInvocationError

from customer_support_fde import circuit_breaker
from customer_support_fde.circuit_breaker import CircuitBreakerLLM, ModelUnavailableError
from customer_support_fde.clock import ClockUnavailableError
from customer_support_fde.state import SupportState

DEFAULT_MODEL = "openai/gpt-4o-mini"

HISTORY_TOKEN_THRESHOLD = 40_000

# Condensation keeps this many of the newest messages (of any type) verbatim.
_CONDENSATION_KEEP_MESSAGES = 3

# One retry, then the agent keeps the full history. Each attempt already retries
# network errors LLM_MAX_RETRIES times inside the client.
_CONDENSATION_MAX_ATTEMPTS = 2

LLM_MAX_RETRIES = 3

# Per-attempt cap; without it the openai client waits up to 600 seconds per attempt.
LLM_TIMEOUT_SECONDS = 40

# The agent retries silently; if the tool keeps failing, the tool-call limit ends the
# conversation and the CLI shows its fixed warning, so the agent never explains it.
TOOL_ERROR_MESSAGE = (
    "The tool call failed with a temporary error. Call the same tool again with "
    "the same arguments. Do not mention this error to the customer."
)

logger = logging.getLogger(__name__)


def _chat_model(model: str, max_retries: int) -> ChatOpenAI:
    return ChatOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ.get("OPENROUTER_API_KEY"),
        model=model,
        max_retries=max_retries,
        timeout=LLM_TIMEOUT_SECONDS,
    )


def build_llm() -> ChatOpenAI | CircuitBreakerLLM:
    primary_model = os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)
    fallback_model = os.environ.get("FALLBACK_MODEL", "").strip()
    if not fallback_model:
        return _chat_model(primary_model, LLM_MAX_RETRIES)

    # The probe makes a single attempt so a half-open circuit doesn't repeat the full
    # retry delay against a primary that is still down.
    return CircuitBreakerLLM(
        primary=_chat_model(primary_model, LLM_MAX_RETRIES),
        probe=_chat_model(primary_model, 0),
        fallback=_chat_model(fallback_model, LLM_MAX_RETRIES),
        primary_model=primary_model,
        fallback_model=fallback_model,
        breaker=circuit_breaker.SHARED_BREAKER,
    )


def estimate_token_count(messages: list[AnyMessage]) -> int:
    # get_num_tokens_from_messages() raises NotImplementedError for OpenRouter-style
    # "vendor/model" names regardless of the underlying model, so estimate from the
    # last real reply's provider-reported prompt size, plus a rough per-character
    # estimate of everything added since (a long customer message or tool result).
    reported, start = 0, 0
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, AIMessage) and message.usage_metadata:
            reported, start = message.usage_metadata.get("input_tokens", 0), index + 1
            break
    return reported + sum(len(str(m.content)) for m in messages[start:]) // 4


def summary_messages(summary: str | None) -> list[AnyMessage]:
    # How every node shows a condensed conversation's summary to the model.
    if summary is None:
        return []
    return [SystemMessage(content=f"Summary of earlier conversation:\n{summary}")]


def select_messages_to_condense(messages: list[AnyMessage]) -> int:
    # Returns the cutoff index: messages before it are condensed (0 means none). Only
    # runs at a turn boundary (the customer's message is newest), so a turn's own tool
    # steps, which the tool-call limit counts, are never trimmed mid-turn.
    if len(messages) <= _CONDENSATION_KEEP_MESSAGES:
        return 0
    if not isinstance(messages[-1], HumanMessage):
        return 0
    cutoff = len(messages) - _CONDENSATION_KEEP_MESSAGES
    # A tool result must stay with the assistant message that made the call.
    while cutoff > 0 and isinstance(messages[cutoff], ToolMessage):
        cutoff -= 1
    return cutoff


def _render_transcript(messages: list[AnyMessage]) -> str:
    lines = []
    for message in messages:
        if isinstance(message, HumanMessage):
            lines.append(f"Customer: {message.content}")
        elif isinstance(message, ToolMessage):
            lines.append(f"Tool result: {message.content}")
        elif isinstance(message, AIMessage):
            if message.content:
                lines.append(f"Assistant: {message.content}")
            for call in message.tool_calls:
                lines.append(f"Assistant called tool {call['name']} with {call['args']}")
    return "\n".join(lines)


def condense_messages(
    llm: ChatOpenAI | CircuitBreakerLLM,
    older_messages: list[AnyMessage],
    instructions: str,
    previous_summary: str | None,
) -> str | None:
    # Returns None when every attempt fails, and the caller keeps the full history.
    # The older messages go in as one plain-text transcript: given raw tool calls and
    # results, models continue the conversation (even emitting tool-call markup)
    # instead of summarizing it.
    condense_input: list[AnyMessage] = [SystemMessage(content=instructions)]
    if previous_summary is not None:
        condense_input.append(
            SystemMessage(content=f"Previous summary:\n{previous_summary}")
        )
    condense_input.append(
        HumanMessage(
            content=f"Conversation to summarize:\n{_render_transcript(older_messages)}"
        )
    )

    for attempt in range(1, _CONDENSATION_MAX_ATTEMPTS + 1):
        try:
            content = llm.invoke(condense_input).content
        except ModelUnavailableError:
            # Both models are down; the agent's own call will surface it.
            logger.warning("Failed to condense conversation history", exc_info=True)
            return None
        except Exception as exc:
            reason: object = exc
        else:
            if isinstance(content, str) and content.strip():
                return content.strip()
            reason = "blank summary"
        logger.warning(
            "Failed to condense conversation history (attempt %d of %d): %s",
            attempt,
            _CONDENSATION_MAX_ATTEMPTS,
            reason,
            exc_info=isinstance(reason, Exception),
        )
    return None


def condense_history(
    llm: ChatOpenAI | CircuitBreakerLLM,
    state: SupportState,
    messages: list[AnyMessage],
    *,
    summary_key: str,
    threshold: int,
    instructions: str,
    context: list[AnyMessage],
) -> tuple[SupportState, list[AnyMessage], list[AnyMessage]]:
    # Once the history (plus the agent's context) is over the threshold, folds everything
    # older than the kept messages into state[summary_key]. Returns the updated state,
    # the messages to send, and the RemoveMessages for the condensed ones.
    cutoff = select_messages_to_condense(messages)
    if not cutoff or estimate_token_count(context + messages) <= threshold:
        return state, messages, []
    older_messages = messages[:cutoff]
    new_summary = condense_messages(
        llm, older_messages, instructions, state.get(summary_key)
    )
    if new_summary is None:
        return state, messages, []
    removals: list[AnyMessage] = [RemoveMessage(id=m.id) for m in older_messages]
    return {**state, summary_key: new_summary}, messages[cutoff:], removals


def handle_tool_error(exc: Exception) -> str:
    # Returned to the agent as an error ToolMessage telling it to retry; repeated
    # failures end at the tool limit. Invalid tool-call arguments keep their validation message
    # so the model can fix them; anything else is logged and replaced with a generic
    # message so internal details never reach the model or the customer.
    if isinstance(exc, ToolInvocationError):
        return exc.message
    # Retrying can't fix an unreachable time server; let it end the conversation.
    if isinstance(exc, ClockUnavailableError):
        raise exc
    logger.warning("Tool call failed", exc_info=exc)
    return TOOL_ERROR_MESSAGE


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
    "LLM_TIMEOUT_SECONDS",
    "TOOL_ERROR_MESSAGE",
    "build_llm",
    "handle_tool_error",
    "estimate_token_count",
    "condense_messages",
    "condense_history",
    "select_messages_to_condense",
    "summary_messages",
    "prompt_until",
]
