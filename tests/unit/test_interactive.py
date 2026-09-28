import io
from contextlib import contextmanager
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage
from langgraph.types import Command
from rich.console import Console

from customer_support_fde import interactive

_RESOLVED_STATE = {
    "destination": "order_support",
    "user_query": "what's on the menu?",
    "sentiment": None,
    "order_confirmed": False,
    "messages": [AIMessage(content="We have kung pao chicken.")],
}


# interactive.py's Console factory emits no raw ANSI escape sequences when
# stdout is not a tty. (edge)
def test_make_console_emits_no_ansi_when_not_a_tty(capsys):
    console = interactive._make_console(force_terminal=False)
    console.print("[bold red]hello[/bold red]")

    captured = capsys.readouterr()
    assert "\x1b[" not in captured.out
    assert "hello" in captured.out


# _run_conversation generates a distinct thread_id on each call, and drives an
# __interrupt__ / Command(resume=...) cycle through to a resolved state. (base)
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


# run_interactive() prints a welcome/intro message before the first prompt is shown. (base)
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
# printed. (base)
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
# "Thinking..." status indicator. (base)
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


# A human turn renders with the text label "You:". (base)
def test_print_turn_renders_human_turn_with_label(capsys):
    console = interactive._make_console(force_terminal=False)
    interactive._print_turn(console, "human", "what's on the menu?")

    captured = capsys.readouterr()
    assert "You:" in captured.out
    assert "what's on the menu?" in captured.out


# An AI turn renders with the text label "Assistant:". (base)
def test_print_turn_renders_ai_turn_with_label(capsys):
    console = interactive._make_console(force_terminal=False)
    interactive._print_turn(console, "ai", "We have kung pao chicken.")

    captured = capsys.readouterr()
    assert "Assistant:" in captured.out
    assert "We have kung pao chicken." in captured.out


# human and ai turns use visually distinct labels from each other. (base)
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


# A single-line turn keeps the speaker label inline with its content. (base)
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
# what the user typed). (base)
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
# allowing a second, independent conversation to run. (base)
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
# with exit code 0 and no closing message. (base)
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


# A blank line, or a question that happens to contain the literal word "exit", does
# not end the session. (regression)
def test_run_interactive_does_not_exit_on_blank_line_or_word_exit(monkeypatch):
    monkeypatch.setattr(interactive, "build_graph", lambda checkpointer: object())

    conversation_calls = []

    def _fake_run_conversation(console, graph, query):
        conversation_calls.append(query)
        return _RESOLVED_STATE

    monkeypatch.setattr(interactive, "_run_conversation", _fake_run_conversation)
    monkeypatch.setattr(
        interactive.sys,
        "stdin",
        io.StringIO("\nhow do I exit a subscription refund request?\n/exit\n"),
    )

    exit_code = interactive.run_interactive()

    assert exit_code == 0
    assert conversation_calls == ["", "how do I exit a subscription refund request?"]


# A mid-conversation error raised by _run_conversation is caught, printed as a
# distinctly styled error line, and the loop returns to a fresh prompt instead of
# crashing the process. (error)
def test_run_interactive_recovers_from_mid_conversation_error(monkeypatch, capsys):
    monkeypatch.setattr(interactive, "build_graph", lambda checkpointer: object())

    calls = {"n": 0}

    def _fake_run_conversation(console, graph, query):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return _RESOLVED_STATE

    monkeypatch.setattr(interactive, "_run_conversation", _fake_run_conversation)
    monkeypatch.setattr(interactive.sys, "stdin", io.StringIO("first\nsecond\n/exit\n"))

    exit_code = interactive.run_interactive()

    assert exit_code == 0
    assert calls["n"] == 2
    captured = capsys.readouterr()
    assert "Error" in captured.out
    assert "boom" in captured.out


def _color_console() -> Console:
    return Console(file=io.StringIO(), force_terminal=True, color_system="standard")


# print_warning() renders the given message in red on a color terminal. (base)
def test_print_warning_renders_message_in_red():
    console = _color_console()

    interactive.print_warning("System issue", console)

    output = console.file.getvalue()
    assert "System issue" in output
    assert "\x1b[31m" in output


_TOOL_LIMIT_STATE = {
    "destination": "order_support",
    "user_query": "hi",
    "sentiment": None,
    "order_confirmed": False,
    "tool_limit_reached": {"agent": "order_support", "tool": "get_menu"},
    "messages": [
        AIMessage(
            content="", tool_calls=[{"name": "get_menu", "args": {}, "id": "call_1"}]
        )
    ],
}


# The tool-limit warning is a fixed, friendly message with no internal details. (base)
def test_tool_limit_warning_text():
    assert interactive.TOOL_LIMIT_WARNING == (
        "Sorry, our system is having some issues right now. Please try again later."
    )


# When a conversation exceeds the tool limit, the red warning is shown, the loop waits
# for Enter before clearing the screen, and no generic error line is printed. (base)
def test_run_interactive_shows_warning_when_tool_limit_exceeded(monkeypatch, capsys):
    events = []
    monkeypatch.setattr(
        interactive,
        "print_warning",
        lambda message, console=None: events.append(("warning", message)),
    )
    monkeypatch.setattr(interactive.Console, "clear", lambda self: events.append(("clear",)))
    monkeypatch.setattr(interactive, "build_graph", lambda checkpointer: object())
    monkeypatch.setattr(
        interactive, "_run_conversation", lambda console, graph, query: _TOOL_LIMIT_STATE
    )
    stdin = io.StringIO("hi\n\n/exit\n")
    monkeypatch.setattr(interactive.sys, "stdin", stdin)

    exit_code = interactive.run_interactive()

    assert exit_code == 0
    assert events == [("warning", interactive.TOOL_LIMIT_WARNING), ("clear",)]
    captured = capsys.readouterr()
    assert "Press Enter to start a new conversation." in captured.out
    assert "Error:" not in captured.out
    # The blank line was consumed by the Enter pause, so /exit ends the session.
    assert stdin.read() == ""


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


# With no console given, the warning prints to stdout via the default console. (base)
def test_print_warning_defaults_to_stdout_console(capsys):
    interactive.print_warning("System issue")

    assert "System issue" in capsys.readouterr().out
