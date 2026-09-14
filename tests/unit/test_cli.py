import io
import json
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage

from customer_support_fde import cli, db
from customer_support_fde.nodes import order_support_agent, refund_agent, router_agent
from customer_support_fde.nodes.router_agent import RouterDecision

SAMPLE_MENU = [
    {
        "name": "Kung Pao Chicken",
        "price": 12.95,
        "ingredients": ["chicken", "peanuts", "dried chili"],
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


# db.load_menu is called exactly once for a full CLI run that spans an
# interrupt-and-resume cycle, using a counting wrapper around db.load_menu. (base)
def test_cli_run_calls_load_menu_exactly_once_across_an_interrupt(
    monkeypatch, tmp_path, capsys
):
    path = tmp_path / "test.db"
    db.init_database(path)
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(path))

    real_load_menu = db.load_menu
    call_count = {"n": 0}

    def _counting_load_menu(*args, **kwargs):
        call_count["n"] += 1
        return real_load_menu(*args, **kwargs)

    monkeypatch.setattr(cli.db, "load_menu", _counting_load_menu)

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
                    {
                        "name": "add_items_to_cart",
                        "args": {"names": ["Kung Pao Chicken"]},
                        "id": "call_1",
                    }
                ],
            ),
            AIMessage(content="Added! Anything else?"),
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "mark_order_confirmed", "args": {}, "id": "call_2"}
                ],
            ),
            AIMessage(content="Confirmed!"),
        ]
    )
    monkeypatch.setattr(order_support_agent, "_build_llm", lambda: order_llm)
    monkeypatch.setattr("sys.stdin", io.StringIO("2\nthat's all\n"))

    exit_code = cli.run(["Add a kung pao chicken"])

    assert exit_code == 0
    assert call_count["n"] == 1


# run() seeds the initial state dict with all five refund-agent SupportState keys
# at their documented initial values. (base)
def test_run_seeds_initial_state_with_refund_keys(monkeypatch, tmp_path):
    path = tmp_path / "test.db"
    db.init_database(path)
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(path))

    captured = {}
    fake_graph = MagicMock()

    def _fake_invoke(state, config):
        captured["state"] = state
        return {
            "destination": "order_support",
            "user_query": state["user_query"],
            "sentiment": None,
            "order_confirmed": False,
            "messages": [],
        }

    fake_graph.invoke.side_effect = _fake_invoke
    monkeypatch.setattr(cli, "build_graph", lambda checkpointer: fake_graph)

    cli.run(["What's on the menu?"])

    state = captured["state"]
    assert state["order_lookup"] is None
    assert state["refund_resolved"] is False
    assert state["refund_request"] is None
    assert state["complaint_ids"] == {}
    assert state["refund_ticket"] is None
    assert state["order_conversation_summary"] is None
    assert state["refund_conversation_summary"] is None
    assert state["account_number"] is None
    assert state["account_preferences"] is None


# _print_result prints the agent's closing message for a resolved refund conversation,
# and includes refund_ticket in the --json payload. (base)
def test_print_result_renders_resolved_refund_conversation(capsys):
    refund_ticket = {
        "order_id": "K7QP3M9X",
        "order": {"order_id": "K7QP3M9X", "total": 20.0, "lines": []},
        "sentiment": "negative",
        "decision": "eligible",
        "refund_request": {"id": 1, "amount": 20.0},
        "complaint_ids": [],
    }
    state = {
        "destination": "refund",
        "user_query": "I got the wrong dish",
        "sentiment": "negative",
        "order_confirmed": False,
        "messages": [AIMessage(content="Your refund request has been submitted.")],
        "refund_resolved": True,
        "refund_ticket": refund_ticket,
    }

    cli._print_result(state, as_json=False)
    captured = capsys.readouterr()
    assert "Your refund request has been submitted." in captured.out

    cli._print_result(state, as_json=True)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["refund_ticket"] == refund_ticket
