import json

import httpx2
import openai
import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from customer_support_fde import circuit_breaker, db
from customer_support_fde.graph import build_graph
from customer_support_fde.nodes.account_identification_node import PRIMARY_MENU
from customer_support_fde.nodes.router_agent import RouterDecision
from customer_support_fde.state import initial_state

PRIMARY = "primary/model"
FALLBACK = "fallback/model"
ROUTER_REPLY = RouterDecision(destination="order_support", sentiment="neutral").model_dump_json()
AGENT_REPLY = "What would you like to order?"
CONFIG = {"configurable": {"thread_id": "circuit-breaker-test"}}


class FakeOpenRouter:
    # Stands in for the HTTP transport under ChatOpenAI: requests for a model in
    # `failing` get a 503, everything else gets a canned chat completion.
    def __init__(self):
        self.failing: set[str] = {PRIMARY}
        self.models: list[str] = []

    def send(self, request, **kwargs):
        body = json.loads(request.content)
        model = body["model"]
        self.models.append(model)
        if model in self.failing:
            return httpx2.Response(503, json={"error": {"message": "down"}}, request=request)
        content = ROUTER_REPLY if "response_format" in body else AGENT_REPLY
        return httpx2.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 0,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                        "logprobs": None,
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
            request=request,
        )


@pytest.fixture
def openrouter(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", PRIMARY)
    monkeypatch.setenv("FALLBACK_MODEL", FALLBACK)
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(tmp_path / "support.db"))
    db.init_database()
    monkeypatch.setattr(openai._base_client.time, "sleep", lambda _seconds: None)

    fake = FakeOpenRouter()
    monkeypatch.setattr(
        httpx2.Client, "send", lambda self, request, **kwargs: fake.send(request, **kwargs)
    )

    circuit_breaker.reset_circuit()
    yield fake
    circuit_breaker.reset_circuit()


def _interrupt_value(result) -> str:
    return result["__interrupt__"][0].value


# With the primary down, the router's structured classification is answered by the
# fallback after the primary's 1 + 3 attempts, and the graph moves on to account
# identification. (base)
def test_router_falls_back_when_primary_is_down(openrouter):
    graph = build_graph(checkpointer=MemorySaver())

    result = graph.invoke(initial_state("Do you have dumplings?"), CONFIG)

    assert _interrupt_value(result) == PRIMARY_MENU
    assert openrouter.models == [PRIMARY] * 4 + [FALLBACK]


# The order agent's tool-bound call is also answered by the fallback, so the customer
# gets a normal reply. (base)
def test_order_agent_reply_comes_from_fallback(openrouter):
    graph = build_graph(checkpointer=MemorySaver())
    graph.invoke(initial_state("Do you have dumplings?"), CONFIG)

    result = graph.invoke(Command(resume="2"), CONFIG)

    assert _interrupt_value(result) == AGENT_REPLY
    assert openrouter.models[-1] == FALLBACK


# When both models fail, the graph raises ModelUnavailableError; once a model recovers,
# invoke(None) replays the failed router step from the checkpoint. (error)
def test_failed_first_step_is_replayed_after_recovery(openrouter):
    graph = build_graph(checkpointer=MemorySaver())
    openrouter.failing = {PRIMARY, FALLBACK}

    with pytest.raises(circuit_breaker.ModelUnavailableError):
        graph.invoke(initial_state("Do you have dumplings?"), CONFIG)

    openrouter.failing = set()
    result = graph.invoke(None, CONFIG)

    assert _interrupt_value(result) == PRIMARY_MENU


# A failure after an interrupt resume is replayed without duplicating the customer's
# message in the conversation. (regression)
def test_failed_resume_step_is_replayed_without_duplicating_message(openrouter):
    graph = build_graph(checkpointer=MemorySaver())
    graph.invoke(initial_state("Do you have dumplings?"), CONFIG)
    graph.invoke(Command(resume="2"), CONFIG)

    openrouter.failing = {PRIMARY, FALLBACK}
    with pytest.raises(circuit_breaker.ModelUnavailableError):
        graph.invoke(Command(resume="Two dumplings please"), CONFIG)

    openrouter.failing = set()
    result = graph.invoke(None, CONFIG)

    assert _interrupt_value(result) == AGENT_REPLY
    messages = graph.get_state(CONFIG).values["messages"]
    customer_turns = [
        m for m in messages if isinstance(m, HumanMessage) and m.content == "Two dumplings please"
    ]
    assert len(customer_turns) == 1


# Once the circuit has opened, the customer's next message makes no primary attempts
# at all, so it doesn't pay the retry delay again. (base)
def test_open_circuit_skips_primary_on_next_message(openrouter):
    graph = build_graph(checkpointer=MemorySaver())
    graph.invoke(initial_state("Do you have dumplings?"), CONFIG)
    openrouter.models.clear()

    result = graph.invoke(Command(resume="2"), CONFIG)

    assert _interrupt_value(result) == AGENT_REPLY
    assert PRIMARY not in openrouter.models
