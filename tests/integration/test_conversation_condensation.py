"""Conversation condensation: the 40,000-token trigger, large chat histories, summarization
failure handling, and context retention after older messages are condensed away.

Compaction keeps the last 3 messages of any type and only runs at a turn boundary (the
newest message is the customer's). The LLM-judged retention tests at the bottom are marked
e2e and call the real OpenRouter model.
"""

import itertools
import logging
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from customer_support_fde import db
from customer_support_fde.circuit_breaker import ModelUnavailableError
from customer_support_fde.graph import build_graph
from customer_support_fde.nodes import (
    common,
    memory_gen_node,
    order_support_agent,
    refund_agent,
    ticket_gen_node,
)
from customer_support_fde.nodes.common import estimate_token_count
from customer_support_fde.state import initial_state

from _graph_fakes import (
    fake_agent_llm,
    mock_router,
    order_initial_state,
    seed_order,
    tool_call,
    use_tmp_db,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "e2e"))
from _driver import drive_conversation  # noqa: E402
from _judge import judge  # noqa: E402

# Comfortably over the 40,000-token threshold, as reported by the provider.
OVER_THRESHOLD_TOKENS = 50_000

AGENTS = [
    pytest.param(
        order_support_agent,
        order_support_agent.call_model,
        "order_conversation_summary",
        "ORDER_HISTORY_TOKEN_THRESHOLD",
        id="order",
    ),
    pytest.param(
        refund_agent,
        refund_agent.refund_agent,
        "refund_conversation_summary",
        "REFUND_HISTORY_TOKEN_THRESHOLD",
        id="refund",
    ),
]


@pytest.fixture(autouse=True)
def _db(monkeypatch, tmp_path):
    return use_tmp_db(monkeypatch, tmp_path)


def _usage(tokens: int) -> dict:
    return {"input_tokens": tokens, "output_tokens": 10, "total_tokens": tokens + 10}


def _reply(content: str, tokens: int | None = None, **kwargs) -> AIMessage:
    usage = _usage(tokens) if tokens is not None else None
    return AIMessage(content=content, usage_metadata=usage, **kwargs)


def _history(num_turns: int, last_reply_tokens: int | None = None) -> list:
    # h1 a1 ... hN aN h(N+1): N completed turns plus the customer's newest message, so
    # the history sits at a turn boundary. Customer messages are 2 characters long, which
    # the per-character estimate rounds to 0 tokens, so a boundary test's token count is
    # exactly the reply's reported input_tokens.
    messages: list = []
    for i in range(1, num_turns + 1):
        tokens = last_reply_tokens if i == num_turns else None
        messages.append(HumanMessage(content=f"q{i}", id=f"h{i}"))
        messages.append(_reply(f"a{i}", tokens, id=f"a{i}"))
    messages.append(HumanMessage(content=f"q{num_turns + 1}", id=f"h{num_turns + 1}"))
    return messages


def _agent_state(module, messages: list, **overrides) -> dict:
    destination = "refund" if module is refund_agent else "order_support"
    return {
        **initial_state(str(messages[-1].content) if messages else "hi"),
        "destination": destination,
        "messages": messages,
        **overrides,
    }


def _fake_llm(condense_results: list, reply: AIMessage | None = None) -> MagicMock:
    # llm.invoke is the condensation call; llm.bind_tools(...).invoke is the agent reply.
    llm = MagicMock()
    llm.invoke.side_effect = condense_results
    llm.bind_tools.return_value.invoke.return_value = reply or AIMessage(content="Sure thing!")
    return llm


def _removed_ids(result: dict) -> set[str]:
    return {m.id for m in result["messages"] if isinstance(m, RemoveMessage)}


def _retained(result: dict) -> list:
    return [m for m in result["messages"] if not isinstance(m, RemoveMessage)]


def _sent_to_agent(llm: MagicMock) -> list:
    return llm.bind_tools.return_value.invoke.call_args[0][0]


def _conversation_sent_to_agent(llm: MagicMock) -> list:
    return [m for m in _sent_to_agent(llm) if not isinstance(m, SystemMessage)]


# ---------------------------------------------------------------------------
# 1. Trigger at 40,000 tokens
# ---------------------------------------------------------------------------


# The compaction threshold is 40,000 tokens for both agents; the literal value is pinned so
# an accidental change is caught. (base)
def test_threshold_is_40000_tokens():
    assert common.HISTORY_TOKEN_THRESHOLD == 40_000
    assert order_support_agent.ORDER_HISTORY_TOKEN_THRESHOLD == 40_000
    assert refund_agent.REFUND_HISTORY_TOKEN_THRESHOLD == 40_000


# Exactly 40,000 tokens is not over the threshold, so nothing is condensed. (edge)
@pytest.mark.parametrize("module, node, summary_key, _threshold_name", AGENTS)
def test_exactly_40000_tokens_does_not_condense(
    monkeypatch, module, node, summary_key, _threshold_name
):
    llm = _fake_llm([AIMessage(content="unused summary")])
    monkeypatch.setattr(module, "_build_llm", lambda: llm)
    history = _history(3, last_reply_tokens=40_000)

    result = node(_agent_state(module, history))

    llm.invoke.assert_not_called()
    assert result[summary_key] is None
    assert result["messages"] == history + [llm.bind_tools.return_value.invoke.return_value]


# 40,001 tokens condenses everything except the last 3 messages into the summary. (base)
@pytest.mark.parametrize("module, node, summary_key, _threshold_name", AGENTS)
def test_40001_tokens_condenses_all_but_last_three_messages(
    monkeypatch, module, node, summary_key, _threshold_name
):
    llm = _fake_llm([AIMessage(content="Summary of the early turns.")])
    monkeypatch.setattr(module, "_build_llm", lambda: llm)
    history = _history(3, last_reply_tokens=40_001)

    result = node(_agent_state(module, history))

    assert result[summary_key] == "Summary of the early turns."
    assert _removed_ids(result) == {"h1", "a1", "h2", "a2"}
    reply = llm.bind_tools.return_value.invoke.return_value
    assert _retained(result) == history[-3:] + [reply]
    assert _conversation_sent_to_agent(llm) == history[-3:]
    context = _sent_to_agent(llm)
    assert any(
        isinstance(m, SystemMessage) and "Summary of the early turns." in m.content
        for m in context
    )


# Without any usage metadata, the per-character estimate (4 characters per token) decides:
# 160,003 characters is 40,000 tokens (no compaction), 160,004 is 40,001 (compaction). (edge)
@pytest.mark.parametrize("extra_chars, condenses", [(3, False), (4, True)])
@pytest.mark.parametrize("module, node, summary_key, _threshold_name", AGENTS)
def test_character_estimate_triggers_just_over_40000_tokens(
    monkeypatch, module, node, summary_key, _threshold_name, extra_chars, condenses
):
    llm = _fake_llm([AIMessage(content="Summary.")])
    monkeypatch.setattr(module, "_build_llm", lambda: llm)
    history = _history(3)
    state = _agent_state(module, history)
    context_chars = sum(len(str(m.content)) for m in module._build_context_messages(state))
    other_chars = sum(len(str(m.content)) for m in history[1:])
    padding = 160_000 - context_chars - other_chars + extra_chars
    history[0] = HumanMessage(content="x" * padding, id="h1")

    result = node(_agent_state(module, history))

    assert (llm.invoke.call_count == 1) is condenses
    assert (result[summary_key] is not None) is condenses


# With 3 or fewer messages there is nothing older than the kept messages, so nothing is
# condensed however large the count is. (edge)
@pytest.mark.parametrize("module, node, summary_key, _threshold_name", AGENTS)
def test_three_messages_never_condense(monkeypatch, module, node, summary_key, _threshold_name):
    llm = _fake_llm([AIMessage(content="unused summary")])
    monkeypatch.setattr(module, "_build_llm", lambda: llm)
    history = _history(1, last_reply_tokens=100_000)

    result = node(_agent_state(module, history))

    llm.invoke.assert_not_called()
    assert result[summary_key] is None


# ---------------------------------------------------------------------------
# 1b. Compaction rule safeguards
# ---------------------------------------------------------------------------


# Mid-turn (the agent is between tool steps) nothing is condensed, even over the threshold:
# trimming there would drop the current turn's tool steps and the customer's request. (edge)
@pytest.mark.parametrize("module, node, summary_key, _threshold_name", AGENTS)
def test_does_not_condense_mid_turn(monkeypatch, module, node, summary_key, _threshold_name):
    llm = _fake_llm([AIMessage(content="unused summary")])
    monkeypatch.setattr(module, "_build_llm", lambda: llm)
    history = _history(3) + [
        _reply(
            "",
            OVER_THRESHOLD_TOKENS,
            id="tc",
            tool_calls=[{"name": "get_menu", "args": {}, "id": "call_1"}],
        ),
        ToolMessage(content="menu", tool_call_id="call_1", id="t1"),
    ]

    result = node(_agent_state(module, history))

    llm.invoke.assert_not_called()
    assert result[summary_key] is None
    assert not _removed_ids(result)


# When the 3-message cutoff lands on a tool result, the cutoff moves back to keep the
# assistant message that made the call, so no tool result is sent without it. (edge)
@pytest.mark.parametrize("module, node, summary_key, _threshold_name", AGENTS)
def test_cutoff_never_orphans_a_tool_result(
    monkeypatch, module, node, summary_key, _threshold_name
):
    llm = _fake_llm([AIMessage(content="Summary.")])
    monkeypatch.setattr(module, "_build_llm", lambda: llm)
    tool_step = AIMessage(
        content="", id="tc", tool_calls=[{"name": "get_menu", "args": {}, "id": "call_1"}]
    )
    history = [
        HumanMessage(content="q1", id="h1"),
        AIMessage(content="a1", id="a1"),
        HumanMessage(content="q2", id="h2"),
        tool_step,
        ToolMessage(content="menu", tool_call_id="call_1", id="t1"),
        _reply("a2", OVER_THRESHOLD_TOKENS, id="a2"),
        HumanMessage(content="q3", id="h3"),
    ]

    result = node(_agent_state(module, history))

    assert _removed_ids(result) == {"h1", "a1", "h2"}
    sent = _conversation_sent_to_agent(llm)
    assert sent[0] is tool_step
    assert sent == history[3:]


# A runaway tool loop in a turn that starts over the threshold still ends at the tool-call
# limit rather than the workflow recursion limit. (regression)
def test_runaway_tool_loop_after_condensation_still_hits_tool_limit(monkeypatch):
    mock_router(monkeypatch, "order_support")
    order_llm = fake_agent_llm(
        [
            _reply("Hi! What can I get you?", OVER_THRESHOLD_TOKENS),
            _reply("Sure.", OVER_THRESHOLD_TOKENS),
        ]
        + [
            _reply(
                "",
                OVER_THRESHOLD_TOKENS,
                tool_calls=[{"name": "get_menu", "args": {}, "id": f"call_{i}"}],
            )
            for i in range(6)
        ]
    )
    order_llm.invoke.return_value = AIMessage(content="Summary.")
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: order_llm)

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    graph.invoke(order_initial_state("Hello"), config)
    graph.invoke(Command(resume="2"), config)  # Continue without an account.
    graph.invoke(Command(resume="Tell me about the food"), config)

    result = graph.invoke(Command(resume="Show me the menu"), config)

    assert order_llm.invoke.call_count >= 1
    assert result["tool_limit_reached"] == {"agent": "order_support", "tool": "get_menu"}
    assert "__interrupt__" not in result


# ---------------------------------------------------------------------------
# 2. Large chat histories
# ---------------------------------------------------------------------------


# A long order conversation condenses repeatedly: each new summary is built on the previous
# one, the stored history stays bounded, never starts with a tool result, and the newest
# summary reaches the agent's context. (base)
def test_long_conversation_condenses_repeatedly_with_bounded_history(monkeypatch):
    mock_router(monkeypatch, "order_support")
    replies = []
    for i in range(1, 13):
        if i % 3 == 0:
            replies.append(
                _reply(
                    "",
                    OVER_THRESHOLD_TOKENS,
                    tool_calls=[{"name": "get_menu", "args": {}, "id": f"call_{i}"}],
                )
            )
        replies.append(_reply(f"Reply {i}", OVER_THRESHOLD_TOKENS))
    order_llm = fake_agent_llm(replies)
    counter = itertools.count(1)
    order_llm.invoke.side_effect = lambda messages: AIMessage(
        content=f"summary {next(counter)}"
    )
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: order_llm)

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    graph.invoke(order_initial_state("Turn 1"), config)
    graph.invoke(Command(resume="2"), config)  # Continue without an account.

    for turn in range(2, 13):
        result = graph.invoke(Command(resume=f"Turn {turn}"), config)
        assert "__interrupt__" in result
        messages = graph.get_state(config).values["messages"]
        assert not isinstance(messages[0], ToolMessage)
        if order_llm.invoke.call_count:
            # Kept: the last 3 messages (plus a tool-calling message pulled in with its
            # result), then this turn's tool step, tool result, and reply.
            assert len(messages) <= 7

    condense_calls = order_llm.invoke.call_args_list
    assert len(condense_calls) >= 3
    for k, call in enumerate(condense_calls[1:], start=1):
        condense_input = call[0][0]
        assert any(
            isinstance(m, SystemMessage) and m.content == f"Previous summary:\nsummary {k}"
            for m in condense_input
        )

    final_state = graph.get_state(config).values
    latest = f"summary {len(condense_calls)}"
    assert final_state["order_conversation_summary"] == latest
    last_context = order_llm.bind_tools.return_value.invoke.call_args[0][0]
    assert any(isinstance(m, SystemMessage) and latest in m.content for m in last_context)


# One huge customer message after a short reply pushes the conversation over the
# threshold, and compaction runs even though the last reported count was small. (regression)
@pytest.mark.parametrize("module, node, summary_key, _threshold_name", AGENTS)
def test_huge_customer_message_triggers_condensation(
    monkeypatch, module, node, summary_key, _threshold_name
):
    llm = _fake_llm([AIMessage(content="Summary.")])
    monkeypatch.setattr(module, "_build_llm", lambda: llm)
    history = _history(2, last_reply_tokens=1_000)
    history[-1] = HumanMessage(content="x" * 200_000, id="h3")

    result = node(_agent_state(module, history))

    assert result[summary_key] == "Summary."
    assert _removed_ids(result) == {"h1", "a1"}


# The estimate is the last reported input size plus a per-character estimate of every
# message added after that reply. (base)
def test_estimate_counts_messages_after_the_last_reported_reply():
    messages = [
        HumanMessage(content="q1"),
        _reply("a1", 1_000),
        HumanMessage(content="x" * 4_000),
        ToolMessage(content="y" * 400, tool_call_id="call_1"),
    ]

    assert estimate_token_count(messages) == 1_000 + 4_400 // 4


# An empty history estimates to 0 tokens. (edge)
def test_estimate_of_empty_history_is_zero():
    assert estimate_token_count([]) == 0


# The summarizer receives the older messages as one plain-text transcript, not as raw chat
# messages: given raw tool calls and results, a real model continued the conversation and
# emitted tool-call markup as its "summary", losing the customer's allergy. (regression)
def test_summarizer_receives_older_messages_as_a_transcript():
    llm = MagicMock()
    llm.invoke.return_value = AIMessage(content="Summary.")
    older = [
        HumanMessage(content="I'm allergic to peanuts."),
        AIMessage(
            content="", tool_calls=[{"name": "get_menu", "args": {}, "id": "call_1"}]
        ),
        ToolMessage(content="Kung Pao Chicken: chicken, peanuts", tool_call_id="call_1"),
        AIMessage(content="Avoid the Kung Pao Chicken."),
    ]

    assert common.condense_messages(llm, older, "Summarize.", "Earlier summary.") == "Summary."

    condense_input = llm.invoke.call_args[0][0]
    assert [type(m) for m in condense_input] == [SystemMessage, SystemMessage, HumanMessage]
    transcript = condense_input[-1].content
    for expected in [
        "Customer: I'm allergic to peanuts.",
        "get_menu",
        "Kung Pao Chicken: chicken, peanuts",
        "Assistant: Avoid the Kung Pao Chicken.",
    ]:
        assert expected in transcript
    assert transcript.index("allergic") < transcript.index("Avoid")


# ---------------------------------------------------------------------------
# 3. Summarization failure: retry once, then keep the full history
# ---------------------------------------------------------------------------


# A summarization call that raises is retried, and the second attempt's summary is used. (error)
@pytest.mark.parametrize("module, node, summary_key, _threshold_name", AGENTS)
def test_summarization_error_is_retried(monkeypatch, module, node, summary_key, _threshold_name):
    llm = _fake_llm([RuntimeError("provider error"), AIMessage(content="Second try.")])
    monkeypatch.setattr(module, "_build_llm", lambda: llm)
    history = _history(3, last_reply_tokens=OVER_THRESHOLD_TOKENS)

    result = node(_agent_state(module, history))

    assert llm.invoke.call_count == 2
    assert result[summary_key] == "Second try."
    assert _removed_ids(result) == {"h1", "a1", "h2", "a2"}


# A blank summary counts as a failed attempt and is retried rather than replacing the
# history with nothing. (error)
@pytest.mark.parametrize("blank", ["", "   \n"])
@pytest.mark.parametrize("module, node, summary_key, _threshold_name", AGENTS)
def test_blank_summary_is_retried(
    monkeypatch, module, node, summary_key, _threshold_name, blank
):
    llm = _fake_llm([AIMessage(content=blank), AIMessage(content="  Second try.  ")])
    monkeypatch.setattr(module, "_build_llm", lambda: llm)
    history = _history(3, last_reply_tokens=OVER_THRESHOLD_TOKENS)

    result = node(_agent_state(module, history))

    assert llm.invoke.call_count == 2
    assert result[summary_key] == "Second try."


# After 2 failed attempts the agent keeps the full, uncondensed history and the prior
# summary, still replies normally, and logs the failure. (error)
@pytest.mark.parametrize(
    "failures",
    [
        [RuntimeError("down"), RuntimeError("still down")],
        [AIMessage(content=""), AIMessage(content=" ")],
        [RuntimeError("down"), AIMessage(content="")],
    ],
    ids=["errors", "blank", "mixed"],
)
@pytest.mark.parametrize("module, node, summary_key, _threshold_name", AGENTS)
def test_falls_back_to_full_history_after_two_failed_attempts(
    monkeypatch, caplog, module, node, summary_key, _threshold_name, failures
):
    llm = _fake_llm(failures)
    monkeypatch.setattr(module, "_build_llm", lambda: llm)
    history = _history(3, last_reply_tokens=OVER_THRESHOLD_TOKENS)
    state = _agent_state(module, history, **{summary_key: "Prior summary."})

    with caplog.at_level(logging.WARNING, logger=common.__name__):
        result = node(state)

    assert llm.invoke.call_count == 2
    assert result[summary_key] == "Prior summary."
    assert not _removed_ids(result)
    reply = llm.bind_tools.return_value.invoke.return_value
    assert result["messages"] == history + [reply]
    assert _conversation_sent_to_agent(llm) == history
    assert any("condense" in r.getMessage().lower() for r in caplog.records)


# When both models are down (ModelUnavailableError) summarization is not retried; the
# agent's own call then raises the same error, which the CLI turns into its retry prompt. (error)
@pytest.mark.parametrize("module, node, summary_key, _threshold_name", AGENTS)
def test_model_unavailable_during_summarization_is_not_retried(
    monkeypatch, module, node, summary_key, _threshold_name
):
    llm = _fake_llm([ModelUnavailableError("both down"), AIMessage(content="unused")])
    llm.bind_tools.return_value.invoke.side_effect = ModelUnavailableError("both down")
    monkeypatch.setattr(module, "_build_llm", lambda: llm)
    history = _history(3, last_reply_tokens=OVER_THRESHOLD_TOKENS)

    with pytest.raises(ModelUnavailableError):
        node(_agent_state(module, history))

    assert llm.invoke.call_count == 1
    assert _conversation_sent_to_agent(llm) == history


# Summarization failing on one turn keeps every message; the next turn condenses
# successfully. (error)
def test_failed_summarization_recovers_on_the_next_turn(monkeypatch):
    mock_router(monkeypatch, "order_support")
    order_llm = fake_agent_llm(
        [_reply(f"Reply {i}", OVER_THRESHOLD_TOKENS) for i in range(1, 5)]
    )
    order_llm.invoke.side_effect = [
        RuntimeError("down"),
        RuntimeError("still down"),
        AIMessage(content="Recovered summary."),
    ]
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: order_llm)

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    graph.invoke(order_initial_state("Turn 1"), config)
    graph.invoke(Command(resume="2"), config)  # Continue without an account.
    graph.invoke(Command(resume="Turn 2"), config)

    graph.invoke(Command(resume="Turn 3"), config)  # Both attempts fail.
    failed_turn = graph.get_state(config).values
    assert order_llm.invoke.call_count == 2
    assert failed_turn["order_conversation_summary"] is None
    assert len(failed_turn["messages"]) == 6

    graph.invoke(Command(resume="Turn 4"), config)
    recovered = graph.get_state(config).values
    assert order_llm.invoke.call_count == 3
    assert recovered["order_conversation_summary"] == "Recovered summary."
    assert [m.content for m in recovered["messages"]] == [
        "Turn 3",
        "Reply 3",
        "Turn 4",
        "Reply 4",
    ]


# ---------------------------------------------------------------------------
# 4. Context retention (scripted LLM)
# ---------------------------------------------------------------------------


# An allergy stated in the first turn and then condensed away still reaches the account's
# stored preferences: memory_gen_node reads the conversation summary. (regression)
def test_allergy_condensed_away_still_reaches_stored_preferences(monkeypatch, _db):
    account_number = db.create_account(_db)
    mock_router(monkeypatch, "order_support")
    order_llm = fake_agent_llm(
        [
            _reply("Noted, no peanuts.", OVER_THRESHOLD_TOKENS),
            _reply("The Spring Rolls are popular.", OVER_THRESHOLD_TOKENS),
            tool_call(
                "add_items_to_cart",
                {"items": [{"name": "Spring Rolls", "quantity": 1}]},
                "call_1",
            ),
            _reply("Added! Anything else?", OVER_THRESHOLD_TOKENS),
            tool_call("mark_order_confirmed", {}, "call_2"),
            _reply("Your order is confirmed.", OVER_THRESHOLD_TOKENS),
        ]
    )
    order_llm.invoke.return_value = AIMessage(content="Customer is allergic to peanuts.")
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: order_llm)

    structured = MagicMock()
    structured.invoke.return_value = memory_gen_node._PreferenceExtraction(
        preferences="Allergies: peanuts."
    )
    memory_llm = MagicMock()
    memory_llm.with_structured_output.return_value = structured
    monkeypatch.setattr(memory_gen_node, "_build_llm", lambda: memory_llm)

    menu = [{"name": "Spring Rolls", "price": 6.95, "ingredients": ["cabbage", "carrot"]}]
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    graph.invoke({**initial_state("I'm allergic to peanuts."), "menu": menu}, config)
    graph.invoke(Command(resume="1"), config)
    graph.invoke(Command(resume=account_number), config)
    graph.invoke(Command(resume="What's good?"), config)
    graph.invoke(Command(resume="Add spring rolls"), config)
    result = graph.invoke(Command(resume="That's all"), config)

    assert result["order_confirmed"] is True
    extraction_input = structured.invoke.call_args[0][0]
    assert not any(
        isinstance(m, HumanMessage) and "allergic" in str(m.content)
        for m in extraction_input
    ), "the allergy turn should have been condensed away"
    assert any(
        isinstance(m, SystemMessage) and "Customer is allergic to peanuts." in m.content
        for m in extraction_input
    )
    assert db.get_account(account_number, _db)["preferences"] == "Allergies: peanuts."


# After the refund conversation is condensed, the refund ticket's issue extraction still
# receives the summary of the condensed turns. (regression guard)
def test_refund_ticket_issue_extraction_receives_the_summary(monkeypatch):
    mock_router(monkeypatch, "refund")
    refund_llm = fake_agent_llm(
        [
            _reply("Sorry to hear that. What's your order id?", OVER_THRESHOLD_TOKENS),
            _reply("Thanks, anything else?", OVER_THRESHOLD_TOKENS),
            tool_call("conclude_refund_conversation", {}, "call_1"),
            _reply("I've noted your complaint.", OVER_THRESHOLD_TOKENS),
        ]
    )
    refund_llm.invoke.return_value = AIMessage(content="Customer's order arrived cold.")
    monkeypatch.setattr(refund_agent, "_build_llm", lambda: refund_llm)

    structured = MagicMock()
    structured.invoke.return_value = ticket_gen_node._RefundIssueExtraction(
        issue="Order arrived cold."
    )
    ticket_llm = MagicMock()
    ticket_llm.with_structured_output.return_value = structured
    monkeypatch.setattr(ticket_gen_node, "_build_llm", lambda: ticket_llm)

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    graph.invoke(initial_state("My order arrived cold."), config)
    graph.invoke(Command(resume="I don't have it handy."), config)
    result = graph.invoke(Command(resume="No, that's all."), config)

    assert result["refund_conversation_summary"] == "Customer's order arrived cold."
    extraction_input = structured.invoke.call_args[0][0]
    assert any(
        isinstance(m, SystemMessage) and "Customer's order arrived cold." in m.content
        for m in extraction_input
    )
    assert result["refund_ticket"]["issue"] == "Order arrived cold."


# ---------------------------------------------------------------------------
# 5. Context retention, judged by an LLM (real OpenRouter calls)
# ---------------------------------------------------------------------------


@pytest.fixture
def live_llm(monkeypatch):
    from dotenv import load_dotenv

    load_dotenv()
    missing = [name for name in ("OPENROUTER_API_KEY", "LLM_JUDGE") if not os.environ.get(name)]
    if missing:
        pytest.skip(f"e2e tests require {', '.join(missing)} to be set (see .env.example)")
    # Condense at every turn boundary so a short conversation exercises retention.
    monkeypatch.setattr(order_support_agent, "ORDER_HISTORY_TOKEN_THRESHOLD", 1)
    monkeypatch.setattr(refund_agent, "REFUND_HISTORY_TOKEN_THRESHOLD", 1)


# A peanut allergy stated in the first message is condensed away, yet the agent's later
# recommendation still avoids peanuts. (base)
@pytest.mark.e2e
def test_judge_allergy_retained_after_condensation(live_llm):
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    first_message = "Hi! Just so you know, I'm severely allergic to peanuts."

    transcript = drive_conversation(
        graph,
        config,
        query=first_message,
        script=[
            "What soups do you have?",
            "What's in the Spring Rolls?",
            "How much is the Beef Chow Fun?",
            "What would you recommend for my main dish?",
        ],
        max_turns=5,
    )

    state = graph.get_state(config).values
    assert state["order_conversation_summary"], transcript.format()
    assert all(m.content != first_message for m in state["messages"]), transcript.format()

    verdict = judge(
        rubric=(
            "The customer said they are severely allergic to peanuts at the start. The "
            "assistant's final reply recommends a main dish. It must not recommend any "
            "dish containing peanuts, and it should account for the allergy."
        ),
        transcript=transcript.format(),
        ground_truth=(
            "Only Kung Pao Chicken contains peanuts. Mapo Tofu, Spring Rolls, Hot and "
            "Sour Soup, Beef Chow Fun, and Vegetable Fried Rice contain no peanuts."
        ),
    )
    assert verdict.verdict == "pass", verdict.reasoning


# Refund facts given early (order id, missing dish, no substitute) are condensed away, yet
# the agent neither re-asks for them nor reaches the wrong policy outcome. (base)
@pytest.mark.e2e
def test_judge_refund_facts_retained_after_condensation(live_llm, _db):
    order_id = seed_order(_db, age_hours=1)
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    transcript = drive_conversation(
        graph,
        config,
        query=f"Hi, I have a problem with my order {order_id}.",
        script=[
            "Both of the Mapo Tofu never arrived, and nothing came in their place.",
            "Sorry, one second, someone is at the door.",
            "Ok, I'm back. How long do refunds usually take?",
            "Alright. Please go ahead with the refund.",
            "No, that's everything.",
        ],
        max_turns=8,
        fallback="No, that's everything, thanks.",
    )

    state = graph.get_state(config).values
    assert state["refund_conversation_summary"], transcript.format()
    stored = db.list_refund_requests(_db)

    verdict = judge(
        rubric=(
            "The customer gave their order id and said both Mapo Tofu never arrived with "
            "no substitute early on. After that, the assistant must not ask again for the "
            "order id or which dish was missing, and what it tells the customer about the "
            "refund must match the ground truth."
        ),
        transcript=transcript.format(),
        ground_truth=(
            f"Order {order_id} (placed 1 hour ago): Mapo Tofu x2 at $10.00 each and "
            "Spring Rolls x1. Refund requests recorded in the database: "
            f"{[(r['order_id'], r['amount']) for r in stored]}."
        ),
    )
    assert verdict.verdict == "pass", verdict.reasoning
