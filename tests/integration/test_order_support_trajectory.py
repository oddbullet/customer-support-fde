import sqlite3
import uuid
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from agentevals.graph_trajectory.strict import graph_trajectory_strict_match

from customer_support_fde import db
from customer_support_fde.graph import build_graph
from customer_support_fde.nodes import memory_gen_node, order_support_agent, router_agent
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
    # These scripted conversations are far shorter than the real 20,000-token
    # threshold; with no usage_metadata on the responses, the token estimate falls
    # back to a per-character heuristic that stays well under it, keeping the
    # condensation guard a no-op here.
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
        "tool_limit_reached": None,
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
                    "args": {"items": [{"name": item_name, "quantity": 1}]},
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
        "tool_limit_reached": None,
    }

    result = graph.invoke(initial_state, config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="2"), config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="Also add spring rolls"), config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="Add another kung pao chicken"), config)
    assert "__interrupt__" in result

    final_cart_items = graph.get_state(config).values["cart_items"]
    assert final_cart_items == {"Kung Pao Chicken": 2, "Spring Rolls": 1}


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
                "add_items_to_cart", {"items": [{"name": "Kung Pao Chicken", "quantity": 1}]}, "call_1"
            ),
            AIMessage(content="Added! Anything else?"),
            _tool_call("add_items_to_cart", {"items": [{"name": "Spring Rolls", "quantity": 1}]}, "call_2"),
            AIMessage(content="Added! Anything else?"),
            _tool_call(
                "remove_items_from_cart",
                {"items": [{"name": "Kung Pao Chicken", "quantity": 1}]},
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
        "tool_limit_reached": None,
    }

    result = graph.invoke(initial_state, config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="2"), config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="Also add spring rolls"), config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="Remove the kung pao chicken"), config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="That's all, I'm done"), config)
    assert "__interrupt__" not in result

    final_state = graph.get_state(config).values
    assert final_state["cart_items"] == {"Spring Rolls": 1}
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


# Conversation history persists across turns and, once it grows past the token
# threshold, is condensed into a running summary instead of either being wiped
# every turn (the old contract) or growing without bound. (regression) —
# supersedes the old wipe-every-turn assertion this test previously guarded.
def test_condenses_conversation_history_past_the_threshold(monkeypatch):
    monkeypatch.setattr(order_support_agent, "ORDER_HISTORY_TOKEN_THRESHOLD", 1)
    monkeypatch.setattr(
        router_agent,
        "_build_llm",
        lambda: _fake_router_llm(
            RouterDecision(destination="order_support", sentiment="neutral")
        ),
    )

    bound = MagicMock()
    bound.invoke.side_effect = [
        AIMessage(content="Got it. Anything else?"),
        AIMessage(content="Sure thing. Anything else?"),
        AIMessage(content="Noted. Anything else?"),
        AIMessage(content="Okay. Anything else?"),
        AIMessage(content="Sure. Anything else?"),
    ]
    order_llm = MagicMock()
    order_llm.bind_tools.return_value = bound
    order_llm.invoke.return_value = AIMessage(
        content="Running summary of the earliest turns."
    )
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: order_llm)

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    initial_state = {
        "user_query": "Turn 1 message",
        "destination": "order_support",
        "sentiment": None,
        "messages": [],
        "menu": SAMPLE_MENU,
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
        "tool_limit_reached": None,
    }

    result = graph.invoke(initial_state, config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="2"), config)
    assert "__interrupt__" in result
    first_human_message = graph.get_state(config).values["messages"][0]

    for reply in ["Turn 2 message", "Turn 3 message", "Turn 4 message", "Turn 5 message"]:
        result = graph.invoke(Command(resume=reply), config)
        assert "__interrupt__" in result

    final_state = graph.get_state(config).values
    assert final_state["order_conversation_summary"] is not None
    assert first_human_message not in final_state["messages"]


# A dislike/allergy stated early in a long conversation is preserved in
# order_conversation_summary once older turns are condensed out, and later
# model calls still receive that summary in their context. (base)
def test_preference_stated_early_survives_condensation(monkeypatch):
    monkeypatch.setattr(order_support_agent, "ORDER_HISTORY_TOKEN_THRESHOLD", 1)
    monkeypatch.setattr(
        router_agent,
        "_build_llm",
        lambda: _fake_router_llm(
            RouterDecision(destination="order_support", sentiment="neutral")
        ),
    )

    bound = MagicMock()
    bound.invoke.side_effect = [
        AIMessage(content="Noted, no peanuts. Anything else?"),
        AIMessage(content="Sure. Anything else?"),
        AIMessage(content="Sure. Anything else?"),
        AIMessage(content="Sure. Anything else?"),
        AIMessage(content="Recommending Mapo Tofu, no peanuts involved."),
    ]
    order_llm = MagicMock()
    order_llm.bind_tools.return_value = bound
    order_llm.invoke.return_value = AIMessage(
        content="Customer is allergic to peanuts; avoid peanuts in all recommendations."
    )
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: order_llm)

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    initial_state = {
        "user_query": "I'm allergic to peanuts, what do you recommend?",
        "destination": "order_support",
        "sentiment": None,
        "messages": [],
        "menu": SAMPLE_MENU,
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
        "tool_limit_reached": None,
    }

    result = graph.invoke(initial_state, config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="2"), config)
    assert "__interrupt__" in result

    for reply in ["What else is good?", "Tell me more", "Anything spicy?"]:
        result = graph.invoke(Command(resume=reply), config)
        assert "__interrupt__" in result

    result = graph.invoke(Command(resume="What do you recommend for me?"), config)
    assert "__interrupt__" in result

    final_state = graph.get_state(config).values
    assert "peanuts" in final_state["order_conversation_summary"].lower()

    last_call_messages = bound.invoke.call_args_list[-1][0][0]
    system_messages = [m for m in last_call_messages if isinstance(m, SystemMessage)]
    assert any("peanuts" in m.content.lower() for m in system_messages)


# A returning customer who identifies a seeded account reaches the order/support agent
# with that account's stored preferences injected into the model's context. (base)
def test_returning_customer_account_preferences_reach_order_agent_context(
    monkeypatch, tmp_path
):
    db_path = _use_tmp_db(monkeypatch, tmp_path)
    account_number = db.create_account(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE accounts SET preferences = ? WHERE account_number = ?",
            ("Loves spicy food, allergic to peanuts.", account_number),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(
        router_agent,
        "_build_llm",
        lambda: _fake_router_llm(
            RouterDecision(destination="order_support", sentiment="neutral")
        ),
    )
    order_llm = _fake_order_llm([AIMessage(content="Sure, how can I help?")])
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: order_llm)

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    initial_state = {
        "user_query": "What do you recommend?",
        "destination": "order_support",
        "sentiment": None,
        "messages": [],
        "menu": SAMPLE_MENU,
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
        "tool_limit_reached": None,
    }

    result = graph.invoke(initial_state, config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="1"), config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume=account_number), config)
    assert "__interrupt__" in result

    bound = order_llm.bind_tools.return_value
    last_call_messages = bound.invoke.call_args_list[-1][0][0]
    system_messages = [m for m in last_call_messages if isinstance(m, SystemMessage)]
    assert any(
        "Loves spicy food, allergic to peanuts." in m.content for m in system_messages
    )


# Signing up shows the customer a formatted account number that a later, separate
# conversation can look up successfully with no preferences recorded yet. (base)
def test_sign_up_account_number_is_retrievable_in_a_later_conversation(
    monkeypatch, tmp_path
):
    _use_tmp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(
        router_agent,
        "_build_llm",
        lambda: _fake_router_llm(
            RouterDecision(destination="order_support", sentiment="neutral")
        ),
    )
    monkeypatch.setattr(
        order_support_agent,
        "_build_llm",
        lambda: _fake_order_llm([AIMessage(content="Sure, how can I help?")]),
    )

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    initial_state = {
        "user_query": "I'd like to sign up",
        "destination": "order_support",
        "sentiment": None,
        "messages": [],
        "menu": SAMPLE_MENU,
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
        "tool_limit_reached": None,
    }

    result = graph.invoke(initial_state, config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="3"), config)
    assert "__interrupt__" in result
    sign_up_message = result["__interrupt__"][0].value
    assert "-" in sign_up_message
    formatted_number = next(
        token.strip(".") for token in sign_up_message.split() if "-" in token
    )
    assert formatted_number in sign_up_message

    result = graph.invoke(Command(resume="ok"), config)
    assert "__interrupt__" in result

    other_config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    other_result = graph.invoke(initial_state, other_config)
    assert "__interrupt__" in other_result

    other_result = graph.invoke(Command(resume="1"), other_config)
    assert "__interrupt__" in other_result

    other_result = graph.invoke(Command(resume=formatted_number), other_config)
    assert "__interrupt__" in other_result

    found_state = graph.get_state(other_config).values
    assert found_state["account_preferences"] is None
    assert found_state["account_number"] == db.normalize_account_number(
        formatted_number
    )


# The resume that merely acknowledges the sign-up message must not create a
# second account behind the scenes: the account number recorded in the
# conversation's own final state must match the one shown to the customer,
# and exactly one row must exist for it. (regression)
def test_sign_up_does_not_duplicate_account_on_acknowledgement_resume(
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
    monkeypatch.setattr(
        order_support_agent,
        "_build_llm",
        lambda: _fake_order_llm([AIMessage(content="Sure, how can I help?")]),
    )

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    initial_state = {
        "user_query": "I'd like to sign up",
        "destination": "order_support",
        "sentiment": None,
        "messages": [],
        "menu": SAMPLE_MENU,
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
        "tool_limit_reached": None,
    }

    result = graph.invoke(initial_state, config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="3"), config)
    assert "__interrupt__" in result
    sign_up_message = result["__interrupt__"][0].value
    formatted_number = next(
        token.strip(".") for token in sign_up_message.split() if "-" in token
    )

    result = graph.invoke(Command(resume="ok"), config)
    assert "__interrupt__" in result

    final_state = graph.get_state(config).values
    assert final_state["account_number"] == db.normalize_account_number(
        formatted_number
    )

    conn = sqlite3.connect(db_path)
    try:
        account_count = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    finally:
        conn.close()
    assert account_count == 1


# Continuing without an account reaches call_model within the same invoke cycle with
# both account fields None, and no account-preferences SystemMessage in context. (base)
def test_continue_without_account_reaches_call_model_with_no_account_state(monkeypatch):
    monkeypatch.setattr(
        router_agent,
        "_build_llm",
        lambda: _fake_router_llm(
            RouterDecision(destination="order_support", sentiment="neutral")
        ),
    )
    order_llm = _fake_order_llm([AIMessage(content="Sure, how can I help?")])
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: order_llm)

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    initial_state = {
        "user_query": "hi",
        "destination": "order_support",
        "sentiment": None,
        "messages": [],
        "menu": SAMPLE_MENU,
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
        "tool_limit_reached": None,
    }

    result = graph.invoke(initial_state, config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="2"), config)
    assert "__interrupt__" in result

    final_state = graph.get_state(config).values
    assert final_state["account_number"] is None
    assert final_state["account_preferences"] is None

    bound = order_llm.bind_tools.return_value
    last_call_messages = bound.invoke.call_args_list[-1][0][0]
    system_messages = [m for m in last_call_messages if isinstance(m, SystemMessage)]
    assert not any("preferences" in m.content.lower() for m in system_messages)


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
                "add_items_to_cart", {"items": [{"name": "Kung Pao Chicken", "quantity": 1}]}, "call_1"
            ),
            AIMessage(content="Added! Anything else?"),
            _tool_call("add_items_to_cart", {"items": [{"name": "Spring Rolls", "quantity": 1}]}, "call_2"),
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
        "tool_limit_reached": None,
    }

    result = graph.invoke(initial_state, config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="2"), config)
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
                "account_identification_node",
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
                "__interrupt__",
            ],
            [
                "call_model",
                "order_tools",
                "call_model",
                "await_customer",
                "cart_summary",
                "memory_gen_node",
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
        "tool_limit_reached": None,
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
                "add_items_to_cart", {"items": [{"name": "Kung Pao Chicken", "quantity": 1}]}, "call_1"
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
        "tool_limit_reached": None,
    }

    result = graph.invoke(initial_state, config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="2"), config)
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


# An account-holding customer's stated preferences are captured into their
# account record once their order is confirmed, running alongside ticket
# generation with no interrupt left pending. (base, US1)
def test_account_holder_preferences_are_saved_on_order_confirmation(
    monkeypatch, tmp_path
):
    db_path = _use_tmp_db(monkeypatch, tmp_path)
    account_number = db.create_account(db_path)
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
                "add_items_to_cart", {"items": [{"name": "Kung Pao Chicken", "quantity": 1}]}, "call_1"
            ),
            AIMessage(content="Added! Anything else?"),
            _tool_call("mark_order_confirmed", {}, "call_2"),
            AIMessage(content="Great, your order is confirmed!"),
        ]
    )
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: order_llm)

    fixed_preferences = "Allergies: peanuts. Likes: spicy food."
    fake_structured_llm = MagicMock()
    fake_structured_llm.invoke.return_value = memory_gen_node._PreferenceExtraction(
        preferences=fixed_preferences
    )
    fake_memory_llm = MagicMock()
    fake_memory_llm.with_structured_output.return_value = fake_structured_llm
    monkeypatch.setattr(memory_gen_node, "_build_llm", lambda: fake_memory_llm)

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    initial_state = {
        "user_query": "I'm allergic to peanuts and love spicy food",
        "destination": "order_support",
        "sentiment": None,
        "messages": [],
        "menu": SAMPLE_MENU,
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
        "tool_limit_reached": None,
    }

    result = graph.invoke(initial_state, config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="1"), config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume=account_number), config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="That's all, I'm done"), config)
    assert "__interrupt__" not in result

    assert db.get_account(account_number, db_path)["preferences"] == (
        fixed_preferences
    )


# A guest who states a clear allergy during ordering never has any preference
# data extracted or stored — no accounts row is created and none exists to
# check against. (base, US2, FR-002, SC-002)
def test_guest_conversation_writes_no_preference_data(monkeypatch, tmp_path):
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
                "add_items_to_cart", {"items": [{"name": "Kung Pao Chicken", "quantity": 1}]}, "call_1"
            ),
            AIMessage(content="Added! Anything else?"),
            _tool_call("mark_order_confirmed", {}, "call_2"),
            AIMessage(content="Great, your order is confirmed!"),
        ]
    )
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: order_llm)

    fake_memory_llm = MagicMock()
    fake_memory_llm.invoke.side_effect = AssertionError(
        "memory_gen_node must not call the LLM for a guest"
    )
    monkeypatch.setattr(memory_gen_node, "_build_llm", lambda: fake_memory_llm)

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    initial_state = {
        "user_query": "I'm allergic to peanuts",
        "destination": "order_support",
        "sentiment": None,
        "messages": [],
        "menu": SAMPLE_MENU,
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
        "tool_limit_reached": None,
    }

    result = graph.invoke(initial_state, config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="2"), config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="That's all, I'm done"), config)
    assert "__interrupt__" not in result

    conn = sqlite3.connect(db_path)
    try:
        account_count = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    finally:
        conn.close()
    assert account_count == 0


# A failure in memory_gen_node's branch never affects order ticket delivery —
# the two branches are independent, so the ticket is produced with the same
# contents regardless of the memory-capture outcome. (base, US3, FR-007, FR-008,
# SC-003)
def test_memory_gen_node_failure_does_not_affect_ticket_delivery(monkeypatch, tmp_path):
    db_path = _use_tmp_db(monkeypatch, tmp_path)
    account_number = db.create_account(db_path)
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
                "add_items_to_cart", {"items": [{"name": "Kung Pao Chicken", "quantity": 1}]}, "call_1"
            ),
            AIMessage(content="Added! Anything else?"),
            _tool_call("mark_order_confirmed", {}, "call_2"),
            AIMessage(content="Great, your order is confirmed!"),
        ]
    )
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: order_llm)

    def _raise_build_llm():
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(memory_gen_node, "_build_llm", _raise_build_llm)

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    initial_state = {
        "user_query": "I'm allergic to peanuts",
        "destination": "order_support",
        "sentiment": None,
        "messages": [],
        "menu": SAMPLE_MENU,
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
        "tool_limit_reached": None,
    }

    result = graph.invoke(initial_state, config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="1"), config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume=account_number), config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="That's all, I'm done"), config)
    assert "__interrupt__" not in result

    final_state = graph.get_state(config).values
    assert final_state["order_ticket"] == {
        "order_id": final_state["order_id"],
        "items": {"Kung Pao Chicken": 1},
        "lines": final_state["order_summary"]["lines"],
        "total": final_state["order_summary"]["total"],
    }
    assert db.get_account(account_number, db_path)["preferences"] is None
