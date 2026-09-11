import sqlite3
import uuid
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from agentevals.graph_trajectory.strict import graph_trajectory_strict_match

from customer_support_fde import db
from customer_support_fde.graph import build_graph
from customer_support_fde.nodes import order_support_agent, router_agent
from customer_support_fde.nodes.cart_summary_node import render_order_summary
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


def _use_tmp_db(monkeypatch, tmp_path):
    path = tmp_path / "test.db"
    db.init_database(path)
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(path))
    return path


# Asking about the menu triggers a get_menu tool call, then the graph pauses for the customer. (base)
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

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    initial_state = {
        "user_query": "What's on the menu?",
        "destination": "order_support",
        "sentiment": None,
        "messages": [],
        "menu": SAMPLE_MENU,
        "menu_items": {},
        "order_confirmed": False,
        "order_ticket": None,
        "order_summary": None,
        "order_id": None,
    }

    result = graph.invoke(initial_state, config)

    assert "__interrupt__" in result


# Adding the same and different items across three separate turns accumulates quantities correctly. (base)
def test_repeated_adds_across_turns_accumulate_quantities(monkeypatch):
    monkeypatch.setattr(
        router_agent,
        "_build_llm",
        lambda: _fake_router_llm(
            RouterDecision(destination="order_support", sentiment="neutral")
        ),
    )

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
        "menu": SAMPLE_MENU,
        "menu_items": {},
        "order_confirmed": False,
        "order_ticket": None,
        "order_summary": None,
        "order_id": None,
    }

    result = graph.invoke(initial_state, config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="Also add spring rolls"), config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="Add another kung pao chicken"), config)
    assert "__interrupt__" in result

    final_menu_items = graph.get_state(config).values["menu_items"]
    assert final_menu_items == {"Kung Pao Chicken": 2, "Spring Rolls": 1}


# Adding two items then removing one entirely in a later turn leaves only the other. (base)
def test_add_then_remove_across_turns_reflects_removal(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(
        router_agent,
        "_build_llm",
        lambda: _fake_router_llm(
            RouterDecision(destination="order_support", sentiment="neutral")
        ),
    )

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
            _tool_call(
                "remove_items_from_cart",
                {"items": [{"name": "Kung Pao Chicken"}]},
                "call_3",
            ),
            AIMessage(content="Removed! Anything else?"),
            _tool_call("mark_order_confirmed", {}, "call_4"),
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
        "menu": SAMPLE_MENU,
        "menu_items": {},
        "order_confirmed": False,
        "order_ticket": None,
        "order_summary": None,
        "order_id": None,
    }

    result = graph.invoke(initial_state, config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="Also add spring rolls"), config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="Remove the kung pao chicken"), config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="That's all, I'm done"), config)
    assert "__interrupt__" not in result

    final_state = graph.get_state(config).values
    assert final_state["menu_items"] == {"Spring Rolls": 1}
    assert final_state["order_id"] is not None
    assert final_state["order_ticket"] == {
        "order_id": final_state["order_id"],
        "items": {"Spring Rolls": 1},
        "lines": [
            {
                "name": "Spring Rolls",
                "quantity": 1,
                "unit_price": 6.95,
                "line_total": 6.95,
            }
        ],
        "total": 6.95,
    }


# Guards that per-turn message reset in await_customer keeps message count roughly constant. (regression)
def test_messages_do_not_accumulate_across_turns(monkeypatch):
    monkeypatch.setattr(
        router_agent,
        "_build_llm",
        lambda: _fake_router_llm(
            RouterDecision(destination="order_support", sentiment="neutral")
        ),
    )

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
        "menu": SAMPLE_MENU,
        "menu_items": {},
        "order_confirmed": False,
        "order_ticket": None,
        "order_summary": None,
        "order_id": None,
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


# A full multi-turn conversation confirms the order and produces the expected ticket and graph trajectory. (base)
def test_full_conversation_confirms_and_produces_order_ticket(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(
        router_agent,
        "_build_llm",
        lambda: _fake_router_llm(
            RouterDecision(destination="order_support", sentiment="neutral")
        ),
    )

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
        "menu": SAMPLE_MENU,
        "menu_items": {},
        "order_confirmed": False,
        "order_ticket": None,
        "order_summary": None,
        "order_id": None,
    }

    result = graph.invoke(initial_state, config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="Also add spring rolls"), config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="That's all, I'm done"), config)
    assert "__interrupt__" not in result

    final_state = graph.get_state(config).values
    assert final_state["order_confirmed"] is True
    assert final_state["order_id"] is not None
    assert final_state["order_ticket"] == {
        "order_id": final_state["order_id"],
        "items": {"Kung Pao Chicken": 1, "Spring Rolls": 1},
        "lines": final_state["order_summary"]["lines"],
        "total": final_state["order_summary"]["total"],
    }
    assert final_state["order_summary"]["lines"] == [
        {
            "name": "Kung Pao Chicken",
            "quantity": 1,
            "unit_price": 12.95,
            "line_total": 12.95,
        },
        {
            "name": "Spring Rolls",
            "quantity": 1,
            "unit_price": 6.95,
            "line_total": 6.95,
        },
    ]
    assert final_state["order_summary"]["total"] == 19.90
    assert final_state["messages"][-1].content == render_order_summary(
        final_state["order_summary"], final_state["order_id"]
    )

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
                "cart_summary",
                "ticket_gen_node",
            ],
        ]
    }
    match_result = graph_trajectory_strict_match(
        outputs=actual, reference_outputs=reference_outputs
    )
    assert match_result["score"] is True


# Confirming an empty cart never advances the graph to cart_summary/ticket_gen_node. (edge)
def test_confirming_with_an_empty_cart_never_reaches_cart_summary(monkeypatch):
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
        "menu": SAMPLE_MENU,
        "menu_items": {},
        "order_confirmed": False,
        "order_ticket": None,
        "order_summary": None,
        "order_id": None,
    }

    result = graph.invoke(initial_state, config)

    assert "__interrupt__" in result
    final_state = graph.get_state(config).values
    assert final_state["order_confirmed"] is False
    assert final_state["order_ticket"] is None


# A price changed in the database mid-conversation does not affect the
# confirmed order — the run keeps using the menu snapshot taken at start. (regression)
def test_price_change_mid_conversation_does_not_affect_confirmed_order(
    monkeypatch, tmp_path
):
    db_path = _use_tmp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(
        router_agent,
        "_build_llm",
        lambda: _fake_router_llm(
            RouterDecision(destination="order_support", sentiment="neutral")
        ),
    )

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
            _tool_call("mark_order_confirmed", {}, "call_2"),
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
        "menu": SAMPLE_MENU,
        "menu_items": {},
        "order_confirmed": False,
        "order_ticket": None,
        "order_summary": None,
        "order_id": None,
    }

    result = graph.invoke(initial_state, config)
    assert "__interrupt__" in result

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE menu_items SET price = 999.99 WHERE name = 'Kung Pao Chicken'"
        )
        conn.commit()
    finally:
        conn.close()

    result = graph.invoke(Command(resume="That's all, I'm done"), config)
    assert "__interrupt__" not in result

    final_state = graph.get_state(config).values
    assert final_state["order_summary"]["lines"][0]["unit_price"] == 12.95
    assert final_state["order_summary"]["total"] == 12.95
    stored = db.get_order(final_state["order_id"], db_path)
    assert stored["lines"][0]["unit_price"] == 12.95
