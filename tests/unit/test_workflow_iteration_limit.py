import io
from unittest.mock import MagicMock

import pytest
from langgraph.errors import GraphRecursionError

from customer_support_fde import interactive, messages

from _cli_fakes import (
    RESOLVED_STATE,
    FakeInterrupt,
    buffer_console,
    record_warnings,
    scripted_graph,
)


# The workflow iteration limit is 100 graph steps per invoke. (base)
def test_workflow_iteration_limit_is_100():
    assert interactive.WORKFLOW_ITERATION_LIMIT == 100


# Every graph.invoke call (the first message, interrupt resumes, and model-outage
# replays) carries the workflow iteration limit as its recursion_limit. (base)
def test_run_conversation_passes_iteration_limit_on_every_invoke(monkeypatch):
    record_warnings(monkeypatch)
    monkeypatch.setattr(interactive.sys, "stdin", io.StringIO("2\n\n"))
    limits = []
    remaining = [
        {"__interrupt__": [FakeInterrupt("Reply with 1, 2, or 3.")]},
        interactive.ModelUnavailableError("down"),
        RESOLVED_STATE,
    ]

    def _invoke(state_or_command, config):
        limits.append(config.get("recursion_limit"))
        outcome = remaining.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    graph = MagicMock()
    graph.invoke.side_effect = _invoke

    interactive._run_conversation(buffer_console(), graph, "hi")

    assert limits == [interactive.WORKFLOW_ITERATION_LIMIT] * 3


# GraphRecursionError is not retried by _run_conversation: replaying the step would
# only hit the limit again. (regression)
def test_run_conversation_does_not_retry_iteration_limit(monkeypatch):
    warnings = record_warnings(monkeypatch)
    graph, calls = scripted_graph([GraphRecursionError("Recursion limit of 100 reached")])

    with pytest.raises(GraphRecursionError):
        interactive._run_conversation(buffer_console(), graph, "hi")

    assert len(calls) == 1
    assert warnings == []


# When a conversation hits the iteration limit, only the generic message is shown,
# the CLI waits for Enter and exits with code 1, and the raw LangGraph message is
# never printed. (base)
def test_run_interactive_shows_generic_message_and_exits_when_iteration_limit_reached(
    monkeypatch, capsys
):
    warnings = record_warnings(monkeypatch)
    monkeypatch.setattr(interactive, "build_graph", lambda checkpointer: object())

    def _hit_limit(console, graph, query):
        raise GraphRecursionError("Recursion limit of 100 reached without hitting a stop")

    monkeypatch.setattr(interactive, "_run_conversation", _hit_limit)
    stdin = io.StringIO("hi\n\nsecond question\n")
    monkeypatch.setattr(interactive.sys, "stdin", stdin)

    exit_code = interactive.run_interactive()

    assert exit_code == 1
    assert warnings == [messages.GENERIC_ERROR_MESSAGE]
    captured = capsys.readouterr()
    assert "Press Enter to exit." in captured.out
    assert "Recursion limit" not in captured.out
    assert stdin.read() == "second question\n"
