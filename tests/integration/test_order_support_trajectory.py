import uuid
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from agentevals.graph_trajectory.strict import graph_trajectory_strict_match

from customer_support_fde.graph import build_graph
from customer_support_fde.nodes import order_support_agent, router_agent
from customer_support_fde.nodes.router_agent import RouterDecision

from _trajectory import extract_outputs

SAMPLE_MENU = [
    {
        "name": "Kung Pao Chicken",
        "price": 12.95,
        "ingredients": ["chicken", "peanuts", "dried chili"],
    },
    {
        "name": "Mapo Tofu",
        "price": 11.50,
        "ingredients": ["tofu", "ground pork", "chili bean paste"],
    },
    {
        "name": "Spring Rolls",
        "price": 6.95,
        "ingredients": ["cabbage", "carrot", "wheat wrapper"],
    },
]


def _fake_router_llm(decision: RouterDecision) -> MagicMock:
    llm = MagicMock()
    llm.invoke.return_value = decision
    return llm


def _fake_order_llm(responses: list[AIMessage]) -> MagicMock:
    bound = MagicMock()
    bound.invoke.side_effect = responses
    llm = MagicMock()
    llm.bind_tools.return_value = bound
    return llm


def _mock_menu(monkeypatch) -> None:
    monkeypatch.setattr(
        "customer_support_fde.tools.menu_tools._load_menu", lambda: SAMPLE_MENU
    )
    monkeypatch.setattr(
        "customer_support_fde.tools.cart_tools._load_menu", lambda: SAMPLE_MENU
    )


def test_menu_question_pauses_for_the_next_customer_message(monkeypatch):
    monkeypatch.setattr(
        router_agent,
        "_build_llm",
        lambda: _fake_router_llm(
            RouterDecision(destination="order_support", sentiment="neutral")
        ),
    )
    order_llm = _fake_order_llm(
        [
            AIMessage(
                content="",
                tool_calls=[{"name": "get_menu", "args": {}, "id": "call_1"}],
            ),
            AIMessage(content="Here's what we have on the menu."),
        ]
    )
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: order_llm)
    monkeypatch.setattr(
        "customer_support_fde.tools.menu_tools._load_menu", lambda: SAMPLE_MENU
    )

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    initial_state = {
        "user_query": "What's on the menu?",
        "destination": "order_support",
        "sentiment": None,
        "messages": [],
        "menu_items": {},
        "order_confirmed": False,
        "order_ticket": None,
    }

    result = graph.invoke(initial_state, config)

    assert "__interrupt__" in result


def test_repeated_adds_across_turns_accumulate_quantities(monkeypatch):
    monkeypatch.setattr(
        router_agent,
        "_build_llm",
        lambda: _fake_router_llm(
            RouterDecision(destination="order_support", sentiment="neutral")
        ),
    )
    _mock_menu(monkeypatch)

    def _add_call(item_name: str, call_id: str) -> AIMessage:
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "add_items_to_cart",
                    "args": {"names": [item_name]},
                    "id": call_id,
                }
            ],
        )

    order_llm = _fake_order_llm(
        [
            _add_call("Kung Pao Chicken", "call_1"),
            AIMessage(content="Added! Anything else?"),
            _add_call("Spring Rolls", "call_2"),
            AIMessage(content="Added! Anything else?"),
            _add_call("Kung Pao Chicken", "call_3"),
            AIMessage(content="Added! Anything else?"),
        ]
    )
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: order_llm)

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    initial_state = {
        "user_query": "Add a kung pao chicken",
        "destination": "order_support",
        "sentiment": None,
        "messages": [],
        "menu_items": {},
        "order_confirmed": False,
        "order_ticket": None,
    }

    result = graph.invoke(initial_state, config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="Also add spring rolls"), config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="Add another kung pao chicken"), config)
    assert "__interrupt__" in result

    final_menu_items = graph.get_state(config).values["menu_items"]
    assert final_menu_items == {"Kung Pao Chicken": 2, "Spring Rolls": 1}


def test_messages_do_not_accumulate_across_turns(monkeypatch):
    monkeypatch.setattr(
        router_agent,
        "_build_llm",
        lambda: _fake_router_llm(
            RouterDecision(destination="order_support", sentiment="neutral")
        ),
    )
    _mock_menu(monkeypatch)

    def _add_call(item_name: str, call_id: str) -> AIMessage:
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "add_items_to_cart",
                    "args": {"names": [item_name]},
                    "id": call_id,
                }
            ],
        )

    order_llm = _fake_order_llm(
        [
            _add_call("Kung Pao Chicken", "call_1"),
            AIMessage(content="Added! Anything else?"),
            _add_call("Spring Rolls", "call_2"),
            AIMessage(content="Added! Anything else?"),
            _add_call("Mapo Tofu", "call_3"),
            AIMessage(content="Added! Anything else?"),
        ]
    )
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: order_llm)

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    initial_state = {
        "user_query": "Add a kung pao chicken",
        "destination": "order_support",
        "sentiment": None,
        "messages": [],
        "menu_items": {},
        "order_confirmed": False,
        "order_ticket": None,
    }

    graph.invoke(initial_state, config)
    messages_after_turn_1 = graph.get_state(config).values["messages"]

    graph.invoke(Command(resume="Also add spring rolls"), config)
    graph.invoke(Command(resume="Also add mapo tofu"), config)
    messages_after_turn_3 = graph.get_state(config).values["messages"]

    # Each turn's message exchange is roughly constant-sized (system prompt +
    # optional cart summary + human message + one tool-call round + final
    # reply). If the per-turn reset in `await_customer` stopped actually
    # clearing checkpointed state (e.g. reverted to a bare `[]`, a no-op
    # under the `add_messages` reducer), this would instead grow by a full
    # turn's worth of messages with every additional turn.
    assert len(messages_after_turn_3) <= len(messages_after_turn_1) + 2


def test_full_conversation_confirms_and_produces_order_ticket(monkeypatch):
    monkeypatch.setattr(
        router_agent,
        "_build_llm",
        lambda: _fake_router_llm(
            RouterDecision(destination="order_support", sentiment="neutral")
        ),
    )
    _mock_menu(monkeypatch)

    def _tool_call(name: str, args: dict, call_id: str) -> AIMessage:
        return AIMessage(
            content="", tool_calls=[{"name": name, "args": args, "id": call_id}]
        )

    order_llm = _fake_order_llm(
        [
            _tool_call(
                "add_items_to_cart", {"names": ["Kung Pao Chicken"]}, "call_1"
            ),
            AIMessage(content="Added! Anything else?"),
            _tool_call("add_items_to_cart", {"names": ["Spring Rolls"]}, "call_2"),
            AIMessage(content="Added! Anything else?"),
            _tool_call("mark_order_confirmed", {}, "call_3"),
            AIMessage(content="Great, your order is confirmed!"),
        ]
    )
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: order_llm)

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    initial_state = {
        "user_query": "Add a kung pao chicken",
        "destination": "order_support",
        "sentiment": None,
        "messages": [],
        "menu_items": {},
        "order_confirmed": False,
        "order_ticket": None,
    }

    result = graph.invoke(initial_state, config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="Also add spring rolls"), config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="That's all, I'm done"), config)
    assert "__interrupt__" not in result

    final_state = graph.get_state(config).values
    assert final_state["order_confirmed"] is True
    assert final_state["order_ticket"] == {
        "items": {"Kung Pao Chicken": 1, "Spring Rolls": 1}
    }

    actual = extract_outputs(graph, config)
    reference_outputs = {
        "steps": [
            [
                "__start__",
                "router_agent",
                "call_model",
                "order_tools",
                "call_model",
                "await_customer",
                "__interrupt__",
            ],
            [
                "call_model",
                "order_tools",
                "call_model",
                "await_customer",
                "__interrupt__",
            ],
            [
                "call_model",
                "order_tools",
                "call_model",
                "await_customer",
                "confirm_node",
                "ticket_gen_node",
            ],
        ]
    }
    match_result = graph_trajectory_strict_match(
        outputs=actual, reference_outputs=reference_outputs
    )
    assert match_result["score"] is True


def test_confirming_with_an_empty_cart_never_reaches_confirm_node(monkeypatch):
    monkeypatch.setattr(
        router_agent,
        "_build_llm",
        lambda: _fake_router_llm(
            RouterDecision(destination="order_support", sentiment="neutral")
        ),
    )
    _mock_menu(monkeypatch)

    order_llm = _fake_order_llm(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "mark_order_confirmed", "args": {}, "id": "call_1"}
                ],
            ),
            AIMessage(content="There's nothing in your cart yet — want to order something?"),
        ]
    )
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: order_llm)

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    initial_state = {
        "user_query": "I'm done, that's all",
        "destination": "order_support",
        "sentiment": None,
        "messages": [],
        "menu_items": {},
        "order_confirmed": False,
        "order_ticket": None,
    }

    result = graph.invoke(initial_state, config)

    assert "__interrupt__" in result
    final_state = graph.get_state(config).values
    assert final_state["order_confirmed"] is False
    assert final_state["order_ticket"] is None
