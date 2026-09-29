import io
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage
from rich.console import Console

from customer_support_fde import interactive

# Shared fakes for tests that drive interactive.py's conversation loop.

RESOLVED_STATE = {
    "destination": "order_support",
    "user_query": "what's on the menu?",
    "sentiment": None,
    "order_confirmed": False,
    "messages": [AIMessage(content="We have kung pao chicken.")],
}


class FakeInterrupt:
    def __init__(self, value):
        self.value = value


def scripted_graph(outcomes):
    # Each graph.invoke call records (input, thread_id) and consumes the next scripted
    # outcome: an exception instance is raised, anything else is returned.
    calls = []
    remaining = list(outcomes)

    def _invoke(state_or_command, config):
        calls.append((state_or_command, config["configurable"]["thread_id"]))
        outcome = remaining.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    graph = MagicMock()
    graph.invoke.side_effect = _invoke
    return graph, calls


def record_warnings(monkeypatch):
    warnings = []
    monkeypatch.setattr(
        interactive, "print_warning", lambda message, console=None: warnings.append(message)
    )
    return warnings


def buffer_console() -> Console:
    console = interactive._make_console(force_terminal=False)
    console.file = io.StringIO()
    return console
