import io
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage

from customer_support_fde import cli, db
from customer_support_fde.nodes import order_support_agent, router_agent
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
    monkeypatch.setattr("sys.stdin", io.StringIO("that's all\n"))

    exit_code = cli.run(["Add a kung pao chicken"])

    assert exit_code == 0
    assert call_count["n"] == 1
