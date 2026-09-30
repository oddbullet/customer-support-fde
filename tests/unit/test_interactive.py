import io
import logging
import sqlite3
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from langgraph.errors import GraphRecursionError
from langgraph.types import Command
from rich.console import Console

from customer_support_fde import db, interactive, messages, restaurant_time
from customer_support_fde.circuit_breaker import ModelUnavailableError
from customer_support_fde.clock import ClockUnavailableError
from customer_support_fde.nodes.cart_summary_node import OrderNotPlacedError

from _cli_fakes import RESOLVED_STATE as _RESOLVED_STATE
from _cli_fakes import record_warnings


# interactive.py's Console factory emits no raw ANSI escape sequences when
# stdout is not a tty. (edge)
def test_make_console_emits_no_ansi_when_not_a_tty(capsys):
    console = interactive._make_console(force_terminal=False)
    console.print("[bold red]hello[/bold red]")

    captured = capsys.readouterr()
    assert "\x1b[" not in captured.out
    assert "hello" in captured.out


# _run_conversation generates a distinct thread_id on each call, and drives an
# __interrupt__ / Command(resume=...) cycle through to a resolved state. (happy)
def test_run_conversation_generates_distinct_thread_ids_and_resolves_interrupt(monkeypatch):
    console = interactive._make_console(force_terminal=False)

    seen_thread_ids = []

    class _FakeInterruptValue:
        def __init__(self, value):
            self.value = value

    def _make_graph():
        graph = MagicMock()

        def _invoke(state_or_command, config):
            seen_thread_ids.append(config["configurable"]["thread_id"])
            if isinstance(state_or_command, Command):
                return {
                    "destination": "order_support",
                    "user_query": "hi",
                    "sentiment": None,
                    "order_confirmed": True,
                    "messages": [],
                }
            return {"__interrupt__": [_FakeInterruptValue("Confirm? (1/2)")]}

        graph.invoke.side_effect = _invoke
        return graph

    monkeypatch.setattr(interactive.sys, "stdin", io.StringIO("1\n1\n"))

    graph1 = _make_graph()
    result1 = interactive._run_conversation(console, graph1, "hi")
    graph2 = _make_graph()
    result2 = interactive._run_conversation(console, graph2, "hi again")

    assert result1["order_confirmed"] is True
    assert result2["order_confirmed"] is True
    assert len(set(seen_thread_ids)) == 2


# run_interactive() prints a welcome/intro message before the first prompt is shown. (happy)
def test_run_interactive_prints_welcome_before_prompt(monkeypatch, capsys):
    monkeypatch.setattr(interactive, "build_graph", lambda checkpointer: object())
    monkeypatch.setattr(
        interactive, "_run_conversation", lambda console, graph, query: _RESOLVED_STATE
    )
    monkeypatch.setattr(
        interactive.sys, "stdin", io.StringIO("what's on the menu?\n/exit\n")
    )

    interactive.run_interactive()

    captured = capsys.readouterr()
    assert "Welcome" in captured.out
    assert captured.out.index("Welcome") < captured.out.index(">")


# A submitted question is passed through to _run_conversation, and its result is
# printed. (happy)
def test_run_interactive_passes_query_to_run_conversation_and_prints_result(
    monkeypatch, capsys
):
    sentinel_graph = object()
    monkeypatch.setattr(interactive, "build_graph", lambda checkpointer: sentinel_graph)

    captured_call = {}

    def _fake_run_conversation(console, graph, query):
        captured_call["console"] = console
        captured_call["graph"] = graph
        captured_call["query"] = query
        return _RESOLVED_STATE

    monkeypatch.setattr(interactive, "_run_conversation", _fake_run_conversation)
    monkeypatch.setattr(
        interactive.sys, "stdin", io.StringIO("what's on the menu?\n/exit\n")
    )

    interactive.run_interactive()

    assert captured_call["graph"] is sentinel_graph
    assert captured_call["query"] == "what's on the menu?"
    assert isinstance(captured_call["console"], interactive.Console)

    captured = capsys.readouterr()
    assert "We have kung pao chicken." in captured.out


# Each graph.invoke call inside _run_conversation is wrapped in a visible
# "Thinking..." status indicator. (happy)
def test_run_conversation_wraps_each_invoke_call_in_thinking_status(monkeypatch):
    console = interactive._make_console(force_terminal=False)
    status_calls = []

    @contextmanager
    def _fake_status(self, message, **kwargs):
        status_calls.append(message)
        yield

    monkeypatch.setattr(interactive.Console, "status", _fake_status)
    monkeypatch.setattr(interactive.sys, "stdin", io.StringIO("1\n"))

    class _FakeInterruptValue:
        def __init__(self, value):
            self.value = value

    call_count = {"n": 0}

    def _invoke(state_or_command, config):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {"__interrupt__": [_FakeInterruptValue("Confirm? (1/2)")]}
        return {
            "destination": "order_support",
            "user_query": "hi",
            "sentiment": None,
            "order_confirmed": True,
            "messages": [],
        }

    graph = MagicMock()
    graph.invoke.side_effect = _invoke

    interactive._run_conversation(console, graph, "hi")

    assert status_calls == ["Thinking...", "Thinking..."]


# The "Thinking..." status is not active while reading the user's reply to a
# mid-conversation interrupt, so terminal input echo is never obscured by the
# spinner. (edge) — regression guard for the spinner-swallows-typed-input bug
def test_run_conversation_does_not_wrap_interrupt_input_in_thinking_status(monkeypatch):
    console = interactive._make_console(force_terminal=False)
    status_active = {"value": False}

    @contextmanager
    def _fake_status(self, message, **kwargs):
        status_active["value"] = True
        try:
            yield
        finally:
            status_active["value"] = False

    monkeypatch.setattr(interactive.Console, "status", _fake_status)

    read_while_status_active = []

    class _TrackingStdin:
        def __init__(self, lines):
            self._io = io.StringIO(lines)

        def readline(self):
            read_while_status_active.append(status_active["value"])
            return self._io.readline()

    monkeypatch.setattr(interactive.sys, "stdin", _TrackingStdin("1\n"))

    class _FakeInterruptValue:
        def __init__(self, value):
            self.value = value

    call_count = {"n": 0}

    def _invoke(state_or_command, config):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {"__interrupt__": [_FakeInterruptValue("Confirm? (1/2)")]}
        return {
            "destination": "order_support",
            "user_query": "hi",
            "sentiment": None,
            "order_confirmed": True,
            "messages": [],
        }

    graph = MagicMock()
    graph.invoke.side_effect = _invoke

    interactive._run_conversation(console, graph, "hi")

    assert read_while_status_active == [False]


# A human turn renders with the text label "You:". (happy)
def test_print_turn_renders_human_turn_with_label(capsys):
    console = interactive._make_console(force_terminal=False)
    interactive._print_turn(console, "human", "what's on the menu?")

    captured = capsys.readouterr()
    assert "You:" in captured.out
    assert "what's on the menu?" in captured.out


# An AI turn renders with the text label "Assistant:". (happy)
def test_print_turn_renders_ai_turn_with_label(capsys):
    console = interactive._make_console(force_terminal=False)
    interactive._print_turn(console, "ai", "We have kung pao chicken.")

    captured = capsys.readouterr()
    assert "Assistant:" in captured.out
    assert "We have kung pao chicken." in captured.out


# human and ai turns use visually distinct labels from each other. (happy)
def test_print_turn_uses_distinct_labels_for_human_and_ai():
    assert interactive._SPEAKER_LABELS["human"] != interactive._SPEAKER_LABELS["ai"]


# A multi-line AI response keeps the label applied consistently, not just on
# its first line. (edge)
def test_print_turn_applies_label_across_a_multiline_response():
    console = interactive._make_console(force_terminal=False)
    printed = {}

    def _fake_print(renderable, *args, **kwargs):
        printed["renderable"] = renderable

    console.print = _fake_print

    multiline = "Line one.\nLine two.\nLine three."
    interactive._print_turn(console, "ai", multiline)

    text = printed["renderable"]
    assert "Line one." in text.plain
    assert "Line three." in text.plain


# A multi-line turn puts the speaker label on its own line, so a numbered list or
# multi-paragraph reply isn't crammed onto the label's line. (edge)
def test_print_turn_puts_label_on_own_line_for_multiline_content():
    console = interactive._make_console(force_terminal=False)
    printed = {}

    def _fake_print(renderable, *args, **kwargs):
        printed["renderable"] = renderable

    console.print = _fake_print

    multiline = (
        "1) Use an existing account\n"
        "2) Continue without an account\n"
        "3) Sign up for a new account\n"
        "Reply with 1, 2, or 3."
    )
    interactive._print_turn(console, "ai", multiline)

    text = printed["renderable"]
    assert text.plain == "Assistant:\n" + multiline


# A single-line turn keeps the speaker label inline with its content. (happy)
def test_print_turn_keeps_label_inline_for_single_line_content():
    console = interactive._make_console(force_terminal=False)
    printed = {}

    def _fake_print(renderable, *args, **kwargs):
        printed["renderable"] = renderable

    console.print = _fake_print

    interactive._print_turn(console, "human", "what's on the menu?")

    text = printed["renderable"]
    assert text.plain == "You: what's on the menu?"


# A mid-conversation interrupt question renders with AI styling, and the user's
# reply to it is not echoed back through _print_turn (the terminal already shows
# what the user typed). (happy)
def test_run_conversation_routes_interrupt_and_resume_answer_through_print_turn(
    monkeypatch,
):
    console = interactive._make_console(force_terminal=False)
    printed_turns = []

    def _fake_print_turn(console_arg, speaker, content):
        printed_turns.append((speaker, content))

    monkeypatch.setattr(interactive, "_print_turn", _fake_print_turn)
    monkeypatch.setattr(interactive.sys, "stdin", io.StringIO("2\n"))

    class _FakeInterruptValue:
        def __init__(self, value):
            self.value = value

    call_count = {"n": 0}

    def _invoke(state_or_command, config):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {"__interrupt__": [_FakeInterruptValue("Confirm order? 1) yes 2) no")]}
        return {
            "destination": "order_support",
            "user_query": "order",
            "sentiment": None,
            "order_confirmed": True,
            "messages": [],
        }

    graph = MagicMock()
    graph.invoke.side_effect = _invoke

    interactive._run_conversation(console, graph, "I'd like to order")

    assert ("ai", "Confirm order? 1) yes 2) no") in printed_turns
    assert ("human", "2") not in printed_turns


# The "You:"/"Assistant:" text labels are still printed, with no raw ANSI codes,
# when the Console is constructed for non-color output. (edge)
def test_print_turn_emits_no_ansi_when_console_is_non_color(capsys):
    console = interactive._make_console(force_terminal=False)
    interactive._print_turn(console, "human", "hello")
    interactive._print_turn(console, "ai", "hi there")

    captured = capsys.readouterr()
    assert "\x1b[" not in captured.out
    assert "You:" in captured.out
    assert "Assistant:" in captured.out


# After a conversation resolves, the console is cleared and a new prompt is shown,
# allowing a second, independent conversation to run. (happy)
def test_run_interactive_clears_screen_and_loops_for_a_second_conversation(monkeypatch):
    console_clear_calls = []
    monkeypatch.setattr(
        interactive.Console, "clear", lambda self: console_clear_calls.append(True)
    )
    monkeypatch.setattr(interactive, "build_graph", lambda checkpointer: object())

    conversation_calls = []

    def _fake_run_conversation(console, graph, query):
        conversation_calls.append(query)
        return _RESOLVED_STATE

    monkeypatch.setattr(interactive, "_run_conversation", _fake_run_conversation)
    monkeypatch.setattr(
        interactive.sys, "stdin", io.StringIO("first question\nsecond question\n/exit\n")
    )

    exit_code = interactive.run_interactive()

    assert exit_code == 0
    assert conversation_calls == ["first question", "second question"]
    assert len(console_clear_calls) == 2


# Typing /exit (case-insensitive) at a new-conversation prompt ends the session
# with exit code 0 and no closing message. (happy)
def test_run_interactive_exits_on_slash_exit_command(monkeypatch):
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("_run_conversation should not be called")

    monkeypatch.setattr(interactive, "build_graph", lambda checkpointer: object())
    monkeypatch.setattr(interactive, "_run_conversation", _fail_if_called)
    monkeypatch.setattr(interactive.sys, "stdin", io.StringIO("/EXIT\n"))

    exit_code = interactive.run_interactive()

    assert exit_code == 0


# A KeyboardInterrupt raised at the prompt ends the session the same way as /exit. (edge)
def test_run_interactive_exits_cleanly_on_keyboard_interrupt_at_prompt(monkeypatch):
    class _RaisingStdin:
        def readline(self):
            raise KeyboardInterrupt()

    monkeypatch.setattr(interactive, "build_graph", lambda checkpointer: object())
    monkeypatch.setattr(interactive.sys, "stdin", _RaisingStdin())

    exit_code = interactive.run_interactive()

    assert exit_code == 0


# A KeyboardInterrupt raised mid-conversation ends the session the same way as /exit. (edge)
def test_run_interactive_exits_cleanly_on_keyboard_interrupt_mid_conversation(monkeypatch):
    def _raise(*args, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(interactive, "build_graph", lambda checkpointer: object())
    monkeypatch.setattr(interactive, "_run_conversation", _raise)
    monkeypatch.setattr(interactive.sys, "stdin", io.StringIO("hello\n"))

    exit_code = interactive.run_interactive()

    assert exit_code == 0


# A blank or spaces-only line is skipped (no conversation, no exit), and a question
# that happens to contain the literal word "exit" does not end the session. (edge, regression)
def test_run_interactive_skips_blank_lines_and_does_not_exit_on_word_exit(monkeypatch):
    monkeypatch.setattr(interactive, "build_graph", lambda checkpointer: object())

    conversation_calls = []

    def _fake_run_conversation(console, graph, query):
        conversation_calls.append(query)
        return _RESOLVED_STATE

    monkeypatch.setattr(interactive, "_run_conversation", _fake_run_conversation)
    monkeypatch.setattr(
        interactive.sys,
        "stdin",
        io.StringIO("\n   \n\t\nhow do I exit a subscription refund request?\n/exit\n"),
    )

    exit_code = interactive.run_interactive()

    assert exit_code == 0
    assert conversation_calls == ["how do I exit a subscription refund request?"]


# A first message of exactly 1,000 characters is accepted; one of 1,001 is rejected
# with INPUT_TOO_LONG and never starts a conversation. (edge)
def test_run_interactive_rejects_input_over_1000_characters(monkeypatch):
    monkeypatch.setattr(interactive, "build_graph", lambda checkpointer: object())
    warnings = record_warnings(monkeypatch)

    conversation_calls = []

    def _fake_run_conversation(console, graph, query):
        conversation_calls.append(query)
        return _RESOLVED_STATE

    monkeypatch.setattr(interactive, "_run_conversation", _fake_run_conversation)
    monkeypatch.setattr(
        interactive.sys,
        "stdin",
        io.StringIO("x" * 1001 + "\n" + "y" * 1000 + "\n/exit\n"),
    )

    exit_code = interactive.run_interactive()

    assert exit_code == 0
    assert conversation_calls == ["y" * 1000]
    assert warnings == [messages.INPUT_TOO_LONG]


# Mid-conversation replies follow the same rules: blank and over-long replies are
# skipped, and only the next valid reply resumes the graph. (edge)
def test_run_conversation_skips_blank_and_too_long_replies(monkeypatch):
    console = interactive._make_console(force_terminal=False)
    warnings = record_warnings(monkeypatch)
    monkeypatch.setattr(
        interactive.sys, "stdin", io.StringIO("\n   \n" + "x" * 1001 + "\n1\n")
    )
    resumed = []

    class _FakeInterruptValue:
        def __init__(self, value):
            self.value = value

    def _invoke(state_or_command, config):
        if isinstance(state_or_command, Command):
            resumed.append(state_or_command.resume)
            return _RESOLVED_STATE
        return {"__interrupt__": [_FakeInterruptValue("Confirm? (1/2)")]}

    graph = MagicMock()
    graph.invoke.side_effect = _invoke

    interactive._run_conversation(console, graph, "hi")

    assert resumed == ["1"]
    assert warnings == [messages.INPUT_TOO_LONG]


# End of input (e.g. Ctrl+Z / Ctrl+D) ends the session like /exit instead of looping
# on blank reads. (edge)
def test_run_interactive_exits_cleanly_at_end_of_input(monkeypatch):
    monkeypatch.setattr(interactive, "build_graph", lambda checkpointer: object())
    run_conversation = MagicMock(side_effect=AssertionError("should not be called"))
    monkeypatch.setattr(interactive, "_run_conversation", run_conversation)
    monkeypatch.setattr(interactive.sys, "stdin", io.StringIO(""))

    exit_code = interactive.run_interactive()

    assert exit_code == 0
    run_conversation.assert_not_called()


# The too-long message tells the customer the limit. (happy)
def test_input_too_long_message_text():
    assert messages.INPUT_TOO_LONG == (
        "Sorry, that message is too long. Please keep it to 1,000 characters or fewer."
    )


def _color_console() -> Console:
    return Console(file=io.StringIO(), force_terminal=True, color_system="standard")


# print_warning() renders the given message in red on a color terminal. (happy)
def test_print_warning_renders_message_in_red():
    console = _color_console()

    interactive.print_warning("System issue", console)

    output = console.file.getvalue()
    assert "System issue" in output
    assert "\x1b[31m" in output


# Every line of a multi-line warning is rendered red. (edge)
def test_print_warning_colors_every_line_of_multiline_message():
    console = _color_console()

    interactive.print_warning("line one\nline two", console)

    lines = console.file.getvalue().splitlines()
    assert "\x1b[31m" in lines[0] and "line one" in lines[0]
    assert "\x1b[31m" in lines[1] and "line two" in lines[1]


# Square brackets in a warning are printed literally, not parsed as Rich markup. (edge)
def test_print_warning_does_not_parse_markup():
    console = interactive._make_console(force_terminal=False)
    console.file = io.StringIO()

    interactive.print_warning("[bold]not markup[/bold]", console)

    assert "[bold]not markup[/bold]" in console.file.getvalue()


# Without a color terminal, the full warning text prints with no ANSI escape codes. (edge)
def test_print_warning_emits_no_ansi_when_not_a_tty():
    console = interactive._make_console(force_terminal=False)
    console.file = io.StringIO()

    interactive.print_warning("System issue", console)

    output = console.file.getvalue()
    assert "System issue" in output
    assert "\x1b[" not in output


# An empty warning prints an empty line without raising. (edge)
def test_print_warning_accepts_empty_message():
    console = interactive._make_console(force_terminal=False)
    console.file = io.StringIO()

    interactive.print_warning("", console)

    assert console.file.getvalue() == "\n"


# With no console given, the warning prints to stdout via the default console. (happy)
def test_print_warning_defaults_to_stdout_console(capsys):
    interactive.print_warning("System issue")

    assert "System issue" in capsys.readouterr().out


# If the menu can't be loaded at startup (database file missing, or present without
# the dishes table), the CLI shows a red warning that includes the --init-db fix and
# exits with 1 before taking any customer message, instead of failing every
# conversation. (failure)
@pytest.mark.parametrize("db_state", ["missing_file", "missing_table"])
def test_run_interactive_exits_with_remedy_when_menu_cannot_load(
    monkeypatch, tmp_path, db_state
):
    path = tmp_path / "support.db"
    if db_state == "missing_table":
        sqlite3.connect(path).close()
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(path))
    run_conversation = MagicMock(return_value=_RESOLVED_STATE)
    monkeypatch.setattr(interactive, "_run_conversation", run_conversation)
    warnings = record_warnings(monkeypatch)

    exit_code = interactive.run_interactive()

    assert exit_code == 1
    run_conversation.assert_not_called()
    assert any("--init-db" in message for message in warnings)


# When the restaurant timezone isn't configured, the CLI shows a red warning with the
# --set-tz fix and exits 1 before taking any customer message. (failure)
def test_run_interactive_exits_with_remedy_when_timezone_not_set(monkeypatch):
    monkeypatch.setattr(restaurant_time, "_timezone", None)
    monkeypatch.setattr(db, "get_restaurant_timezone", lambda *a, **k: None)
    run_conversation = MagicMock(return_value=_RESOLVED_STATE)
    monkeypatch.setattr(interactive, "_run_conversation", run_conversation)
    warnings = record_warnings(monkeypatch)

    exit_code = interactive.run_interactive()

    assert exit_code == 1
    run_conversation.assert_not_called()
    assert any("--set-tz" in message for message in warnings)




# The generic error message is one fixed, friendly text that tells the customer to
# exit and try again, with a counter fallback. (happy)
def test_generic_error_message_text():
    assert messages.GENERIC_ERROR_MESSAGE == (
        "Sorry, something went wrong on our end. Please exit the application and try "
        "again. If the problem continues, please order at the counter."
    )


# The order-not-placed message states plainly that the order was not placed, with the
# same recovery guidance. (happy)
def test_order_not_placed_message_text():
    assert messages.ORDER_NOT_PLACED_MESSAGE == (
        "Sorry, something went wrong on our end and your order was not placed. Please "
        "exit the application and try again. If the problem continues, please order at "
        "the counter."
    )


# Every unrecoverable failure that escapes a conversation shows only the generic
# message, waits for Enter, and exits with code 1 without running another
# conversation or printing the raw error. (failure)
@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("boom secret detail"),
        db.OrderStoreError("Failed to read account: database is locked"),
        db.MenuStoreError("Menu database not found at 'C:/secret/support.db'"),
        GraphRecursionError("Recursion limit of 100 reached without hitting a stop"),
        ModelUnavailableError("primary and fallback models unavailable"),
        ClockUnavailableError("Could not reach time server pool.ntp.org"),
    ],
    ids=[
        "unexpected",
        "order_store",
        "menu_store",
        "recursion",
        "model_unavailable",
        "clock_unavailable",
    ],
)
def test_run_interactive_shows_generic_message_and_exits_on_unrecoverable_error(
    monkeypatch, capsys, error
):
    warnings = record_warnings(monkeypatch)
    monkeypatch.setattr(interactive, "build_graph", lambda checkpointer: object())
    run_conversation = MagicMock(side_effect=error)
    monkeypatch.setattr(interactive, "_run_conversation", run_conversation)
    stdin = io.StringIO("hi\n\nsecond question\n")
    monkeypatch.setattr(interactive.sys, "stdin", stdin)

    exit_code = interactive.run_interactive()

    assert exit_code == 1
    assert warnings == [messages.GENERIC_ERROR_MESSAGE]
    assert run_conversation.call_count == 1
    captured = capsys.readouterr()
    assert "Press Enter to exit." in captured.out
    assert "Error:" not in captured.out
    assert str(error) not in captured.out
    # Only the Enter pause was consumed after the first question.
    assert stdin.read() == "second question\n"


# A failure to record a confirmed order tells the customer their order was not
# placed, then exits. (failure)
def test_run_interactive_shows_order_not_placed_message(monkeypatch, capsys):
    warnings = record_warnings(monkeypatch)
    monkeypatch.setattr(interactive, "build_graph", lambda checkpointer: object())

    def _order_failed(console, graph, query):
        raise OrderNotPlacedError() from db.OrderStoreError("disk I/O error")

    monkeypatch.setattr(interactive, "_run_conversation", _order_failed)
    monkeypatch.setattr(interactive.sys, "stdin", io.StringIO("order\n\n"))

    exit_code = interactive.run_interactive()

    assert exit_code == 1
    assert warnings == [messages.ORDER_NOT_PLACED_MESSAGE]
    captured = capsys.readouterr()
    assert "Press Enter to exit." in captured.out
    assert "disk I/O error" not in captured.out


# The unrecoverable failure is logged at ERROR with its exception, so the handler
# sends the traceback to Phoenix. (failure)
def test_run_interactive_logs_unrecoverable_error_with_exception(monkeypatch, caplog):
    record_warnings(monkeypatch)
    monkeypatch.setattr(interactive, "build_graph", lambda checkpointer: object())
    error = RuntimeError("boom")
    monkeypatch.setattr(
        interactive, "_run_conversation", MagicMock(side_effect=error)
    )
    monkeypatch.setattr(interactive.sys, "stdin", io.StringIO("hi\n\n"))

    with caplog.at_level(logging.ERROR, logger="customer_support_fde.interactive"):
        interactive.run_interactive()

    logged = [r for r in caplog.records if r.name == "customer_support_fde.interactive"]
    assert len(logged) == 1
    assert logged[0].levelno == logging.ERROR
    assert logged[0].exc_info[1] is error
