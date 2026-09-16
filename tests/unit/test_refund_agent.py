from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage

from customer_support_fde.nodes import refund_agent as refund_agent_module
from customer_support_fde.nodes.refund_agent import (
    SYSTEM_PROMPT,
    _build_context_messages,
    refund_agent,
    refund_await_customer,
)


def _base_state(**overrides) -> dict:
    state = {
        "user_query": "I got the wrong dish",
        "destination": "refund",
        "sentiment": "neutral",
        "messages": [],
        "menu": [],
        "cart_items": {},
        "order_confirmed": False,
        "order_ticket": None,
        "order_summary": None,
        "order_id": None,
        "order_lookup": None,
        "refund_resolved": False,
        "refund_request": None,
        "complaint_ids": {},
        "refund_ticket": None,
        "order_conversation_summary": None,
        "refund_conversation_summary": None,
        "account_number": None,
        "account_preferences": None,
    }
    state.update(overrides)
    return state


def _patch_llm(monkeypatch, responses: list[AIMessage]) -> None:
    bound = MagicMock()
    bound.invoke.side_effect = responses
    fake_llm = MagicMock()
    fake_llm.bind_tools.return_value = bound
    monkeypatch.setattr(refund_agent_module, "_build_llm", lambda: fake_llm)


# When messages is empty, refund_agent seeds only the customer's query as a
# HumanMessage — no SystemMessage lives in state["messages"] anymore, since the
# system prompt/sentiment/summary are now assembled fresh via
# _build_context_messages instead of being baked into the transcript. (regression) —
# supersedes the old assertion that a SystemMessage is seeded into messages.
def test_refund_agent_seeds_only_human_message_when_messages_empty(monkeypatch):
    ai_message = AIMessage(content="Sure, can you give me the order id?")
    _patch_llm(monkeypatch, [ai_message])
    state = _base_state()

    result = refund_agent(state)

    assert result["messages"] == [
        HumanMessage(content="I got the wrong dish"),
        ai_message,
    ]


# _build_context_messages assembles the system prompt and, when sentiment is set,
# a sentiment-reading SystemMessage right after it, in that order. (base)
def test_build_context_messages_includes_system_prompt_and_sentiment():
    state = _base_state(sentiment="negative")

    context = _build_context_messages(state)

    assert len(context) == 2
    assert context[0] == SystemMessage(content=SYSTEM_PROMPT)
    assert context[1] == SystemMessage(
        content="Customer sentiment reading: negative."
    )


# _build_context_messages omits the sentiment reading system message entirely when
# state["sentiment"] is None rather than seeding a null/placeholder line. (edge) —
# supersedes the old omission test which asserted this against refund_agent's output.
def test_refund_agent_omits_sentiment_message_when_sentiment_is_none():
    state = _base_state(sentiment=None)

    context = _build_context_messages(state)

    assert context == [SystemMessage(content=SYSTEM_PROMPT)]


# _build_context_messages appends the running summary as a further SystemMessage
# when refund_conversation_summary is present. (base) — regression guard for
# research.md Decision 2, mirroring specs/008's cart-summary-refresh guard.
def test_build_context_messages_includes_running_summary_when_present():
    state = _base_state(
        refund_conversation_summary=(
            "Order ABC123: customer confirmed return, refund submitted."
        )
    )

    context = _build_context_messages(state)

    system_messages = [m for m in context if isinstance(m, SystemMessage)]
    assert "Order ABC123: customer confirmed return, refund submitted." in (
        system_messages[-1].content
    )


# On a later turn (messages already populated), refund_agent reuses the existing
# transcript as-is rather than re-seeding anything — messages now holds only
# Human/AIMessage entries, never a SystemMessage. (regression) — supersedes the
# old SystemMessage-in-transcript assumption.
def test_refund_agent_reuses_existing_transcript_on_later_turns(monkeypatch):
    _patch_llm(monkeypatch, [AIMessage(content="Got it, thanks.")])
    existing = [
        HumanMessage(content="I got the wrong dish"),
        AIMessage(content="What's your order id?"),
        HumanMessage(content="K7QP3M9X"),
    ]
    state = _base_state(messages=existing)

    result = refund_agent(state)

    assert result["messages"][:3] == existing
    assert len(result["messages"]) == 4


# refund_await_customer appends the reply as a HumanMessage without clearing the transcript. (base)
def test_refund_await_customer_appends_reply_without_clearing_transcript(monkeypatch):
    fake_interrupt = MagicMock(return_value="K7QP3M9X")
    monkeypatch.setattr(refund_agent_module, "interrupt", fake_interrupt)
    existing = [
        SystemMessage(content="prior system prompt"),
        HumanMessage(content="I got the wrong dish"),
        AIMessage(content="What's your order id?"),
    ]
    state = _base_state(messages=existing)

    result = refund_await_customer(state)

    assert result["messages"][:3] == existing
    assert len(result["messages"]) == 4
    assert isinstance(result["messages"][3], HumanMessage)
    assert result["messages"][3].content == "K7QP3M9X"


# refund_await_customer does not interrupt once refund_resolved is True. (edge)
def test_refund_await_customer_does_not_interrupt_when_resolved(monkeypatch):
    fake_interrupt = MagicMock()
    monkeypatch.setattr(refund_agent_module, "interrupt", fake_interrupt)
    state = _base_state(
        messages=[AIMessage(content="Thanks, anything else?")],
        refund_resolved=True,
    )

    result = refund_await_customer(state)

    fake_interrupt.assert_not_called()
    assert result["refund_resolved"] is True


def _turn(i: int, tokens: int | None = None) -> list:
    usage_metadata = None
    if tokens is not None:
        usage_metadata = {
            "input_tokens": tokens,
            "output_tokens": 10,
            "total_tokens": tokens + 10,
        }
    return [
        HumanMessage(content=f"turn {i} query", id=f"h{i}"),
        AIMessage(content=f"turn {i} reply", id=f"a{i}", usage_metadata=usage_metadata),
    ]


def _conversation(num_turns: int, last_turn_tokens: int | None = None) -> list:
    messages: list = []
    for i in range(1, num_turns + 1):
        tokens = last_turn_tokens if i == num_turns else None
        messages.extend(_turn(i, tokens))
    return messages


# With 3 or fewer completed turns, condensation is skipped even over the token
# threshold, since there is nothing older than the retained turns to condense. (edge)
def test_refund_agent_skips_condensation_with_three_or_fewer_turns(monkeypatch):
    final_response = AIMessage(content="Sure thing!")
    fake_llm = MagicMock()
    fake_llm.bind_tools.return_value.invoke.return_value = final_response
    monkeypatch.setattr(refund_agent_module, "_build_llm", lambda: fake_llm)

    conversation = _conversation(
        3, last_turn_tokens=refund_agent_module.REFUND_HISTORY_TOKEN_THRESHOLD + 1
    )
    state = _base_state(messages=conversation)

    result = refund_agent(state)

    fake_llm.invoke.assert_not_called()
    assert result["refund_conversation_summary"] is None
    assert result["messages"] == conversation + [final_response]


# With more than 3 turns but the token count at/under threshold, condensation is
# skipped and messages/summary are left unchanged. (edge)
def test_refund_agent_skips_condensation_when_at_or_under_threshold(monkeypatch):
    final_response = AIMessage(content="Sure thing!")
    fake_llm = MagicMock()
    fake_llm.bind_tools.return_value.invoke.return_value = final_response
    monkeypatch.setattr(refund_agent_module, "_build_llm", lambda: fake_llm)

    conversation = _conversation(
        4, last_turn_tokens=refund_agent_module.REFUND_HISTORY_TOKEN_THRESHOLD
    )
    state = _base_state(messages=conversation)

    result = refund_agent(state)

    fake_llm.invoke.assert_not_called()
    assert result["refund_conversation_summary"] is None
    assert result["messages"] == conversation + [final_response]


# With more than 3 turns and the token count over threshold, condensation folds
# every turn older than the last 3 into refund_conversation_summary and removes
# those messages from state["messages"], while the last 3 turns remain intact. (base)
def test_refund_agent_condenses_older_turns_when_over_threshold(monkeypatch):
    final_response = AIMessage(content="Sure thing!")
    summary_response = AIMessage(content="Order ABC123: customer wants a refund.")
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = summary_response
    fake_llm.bind_tools.return_value.invoke.return_value = final_response
    monkeypatch.setattr(refund_agent_module, "_build_llm", lambda: fake_llm)

    conversation = _conversation(
        4, last_turn_tokens=refund_agent_module.REFUND_HISTORY_TOKEN_THRESHOLD + 1
    )
    state = _base_state(messages=conversation)

    result = refund_agent(state)

    assert (
        result["refund_conversation_summary"]
        == "Order ABC123: customer wants a refund."
    )
    removed_ids = {m.id for m in result["messages"] if isinstance(m, RemoveMessage)}
    assert removed_ids == {"h1", "a1"}
    retained = [m for m in result["messages"] if not isinstance(m, RemoveMessage)]
    assert retained == conversation[2:] + [final_response]


# Re-condensing later in the same conversation replaces the prior summary wholesale
# rather than appending to it. (base)
def test_refund_agent_recondenses_replacing_old_summary(monkeypatch):
    final_response = AIMessage(content="Sure thing!")
    new_summary_response = AIMessage(content="Only the new summary text.")
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = new_summary_response
    fake_llm.bind_tools.return_value.invoke.return_value = final_response
    monkeypatch.setattr(refund_agent_module, "_build_llm", lambda: fake_llm)

    conversation = _conversation(
        4, last_turn_tokens=refund_agent_module.REFUND_HISTORY_TOKEN_THRESHOLD + 1
    )
    state = _base_state(
        messages=conversation,
        refund_conversation_summary="The old summary text.",
    )

    result = refund_agent(state)

    assert result["refund_conversation_summary"] == "Only the new summary text."
    assert "old summary" not in result["refund_conversation_summary"].lower()


# The condensation instructions given to the model direct it to preserve, per
# order discussed, the order identified, the facts gathered, and any outcome
# reached, and to keep separate orders' facts and outcomes distinct rather than
# merged. (base)
def test_refund_agent_condensation_instructions_keep_orders_distinct(monkeypatch):
    final_response = AIMessage(content="Sure thing!")
    summary_response = AIMessage(content="Some summary.")
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = summary_response
    fake_llm.bind_tools.return_value.invoke.return_value = final_response
    monkeypatch.setattr(refund_agent_module, "_build_llm", lambda: fake_llm)

    conversation = _conversation(
        4, last_turn_tokens=refund_agent_module.REFUND_HISTORY_TOKEN_THRESHOLD + 1
    )
    state = _base_state(messages=conversation)

    refund_agent(state)

    condense_call_messages = fake_llm.invoke.call_args[0][0]
    instructions = condense_call_messages[0].content
    assert "order" in instructions.lower()
    assert "outcome" in instructions.lower()
    assert "distinct" in instructions.lower()


# When the condensation model call itself raises, refund_agent still returns a
# normal reply for that turn and leaves messages/refund_conversation_summary
# unchanged; no exception propagates out of refund_agent. (error)
def test_refund_agent_condensation_failure_is_silent(monkeypatch):
    final_response = AIMessage(content="Sure thing!")
    fake_llm = MagicMock()
    fake_llm.invoke.side_effect = RuntimeError("condensation model unavailable")
    fake_llm.bind_tools.return_value.invoke.return_value = final_response
    monkeypatch.setattr(refund_agent_module, "_build_llm", lambda: fake_llm)

    conversation = _conversation(
        4, last_turn_tokens=refund_agent_module.REFUND_HISTORY_TOKEN_THRESHOLD + 1
    )
    state = _base_state(messages=conversation)

    result = refund_agent(state)

    assert result["refund_conversation_summary"] is None
    assert result["messages"] == conversation + [final_response]


# The token-count estimate never calls get_num_tokens_from_messages() on the LLM
# client, since that raises NotImplementedError for OpenRouter-style "vendor/model"
# names (e.g. "openai/gpt-4o-mini") regardless of which model actually handles the
# call. (regression) — guards the fix for that crash.
def test_refund_agent_never_calls_get_num_tokens_from_messages(monkeypatch):
    final_response = AIMessage(content="Sure thing!")
    fake_llm = MagicMock()
    fake_llm.bind_tools.return_value.invoke.return_value = final_response
    monkeypatch.setattr(refund_agent_module, "_build_llm", lambda: fake_llm)

    conversation = _conversation(4)
    state = _base_state(messages=conversation)

    refund_agent(state)

    fake_llm.get_num_tokens_from_messages.assert_not_called()


# When the last AIMessage carries provider-reported usage_metadata, the token
# estimate uses its input_tokens directly rather than falling back to a
# character-count heuristic. (base)
def test_estimate_token_count_uses_usage_metadata_when_present():
    conversation = _conversation(4, last_turn_tokens=12_345)

    assert refund_agent_module._estimate_token_count(conversation) == 12_345


# When no message carries usage_metadata (e.g. no reply has been generated yet),
# the token estimate falls back to a rough per-character heuristic instead of
# raising or returning zero for a non-empty conversation. (edge)
def test_estimate_token_count_falls_back_to_character_heuristic_without_usage_metadata():
    conversation = _conversation(4)

    estimate = refund_agent_module._estimate_token_count(conversation)

    expected = sum(len(str(m.content)) for m in conversation) // 4
    assert estimate == expected
    assert estimate > 0
