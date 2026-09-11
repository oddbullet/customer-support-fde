from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from customer_support_fde.nodes import refund_agent as refund_agent_module
from customer_support_fde.nodes.refund_agent import refund_agent, refund_await_customer


def _base_state(**overrides) -> dict:
    state = {
        "user_query": "I got the wrong dish",
        "destination": "refund",
        "sentiment": "neutral",
        "messages": [],
        "menu": [],
        "menu_items": {},
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
    }
    state.update(overrides)
    return state


def _patch_llm(monkeypatch, responses: list[AIMessage]) -> None:
    bound = MagicMock()
    bound.invoke.side_effect = responses
    fake_llm = MagicMock()
    fake_llm.bind_tools.return_value = bound
    monkeypatch.setattr(refund_agent_module, "_build_llm", lambda: fake_llm)


# When messages is empty, refund_agent seeds a system prompt plus the customer's query. (base)
def test_refund_agent_seeds_system_prompt_and_query_when_messages_empty(monkeypatch):
    _patch_llm(monkeypatch, [AIMessage(content="Sure, can you give me the order id?")])
    state = _base_state()

    result = refund_agent(state)

    seeded = result["messages"]
    assert isinstance(seeded[0], SystemMessage)
    human_messages = [m for m in seeded if isinstance(m, HumanMessage)]
    assert len(human_messages) == 1
    assert human_messages[0].content == "I got the wrong dish"
    assert isinstance(seeded[-1], AIMessage)


# On a later turn (messages already populated), refund_agent reuses the existing
# transcript rather than re-seeding a new system prompt. (base)
def test_refund_agent_reuses_existing_transcript_on_later_turns(monkeypatch):
    _patch_llm(monkeypatch, [AIMessage(content="Got it, thanks.")])
    existing = [
        SystemMessage(content="prior system prompt"),
        HumanMessage(content="I got the wrong dish"),
        AIMessage(content="What's your order id?"),
        HumanMessage(content="K7QP3M9X"),
    ]
    state = _base_state(messages=existing)

    result = refund_agent(state)

    assert result["messages"][:4] == existing
    assert len(result["messages"]) == 5


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
