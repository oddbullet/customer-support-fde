import sys
import uuid

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from rich.console import Console
from rich.text import Text

from customer_support_fde.graph import build_graph
from customer_support_fde.state import SupportState, initial_state

_SPEAKER_LABELS = {
    "human": "You",
    "ai": "Assistant",
}


def _make_console(force_terminal: bool | None = None) -> Console:
    return Console(force_terminal=force_terminal)


_AI_BACKGROUND_STYLE = "on #00384A"


def _print_turn(console: Console, speaker: str, content: str) -> None:
    label = _SPEAKER_LABELS[speaker]
    separator = "\n" if "\n" in content else " "
    style = _AI_BACKGROUND_STYLE if speaker == "ai" else None
    console.print(Text(f"{label}:{separator}{content}", style=style))


TOOL_LIMIT_WARNING = (
    "Sorry, our system is having some issues right now. Please try again later."
)


def print_warning(message: str, console: Console | None = None) -> None:
    if console is None:
        console = _make_console()
    console.print(Text(message, style="red"))


def _invoke_with_status(console: Console, graph, state_or_command, config) -> SupportState:
    with console.status("Thinking...", spinner="dots"):
        return graph.invoke(state_or_command, config)


def _run_conversation(console: Console, graph, query: str) -> SupportState:
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    result = _invoke_with_status(console, graph, initial_state(query), config)

    while "__interrupt__" in result:
        _print_turn(console, "ai", result["__interrupt__"][0].value)
        console.print("> ", end="")
        answer = sys.stdin.readline().rstrip("\n")
        console.print()
        result = _invoke_with_status(console, graph, Command(resume=answer), config)

    return result


_WELCOME_MESSAGE = (
    "Welcome to the restaurant's customer support assistant.\n"
    "Ask a question, place an order, or request a refund.\n"
    "Type '/exit' or press Ctrl+C at any time to quit."
)


def run_interactive() -> int:
    console = _make_console()
    graph = build_graph(checkpointer=MemorySaver())

    console.print(_WELCOME_MESSAGE)

    while True:
        try:
            console.print("> ", end="")
            query = sys.stdin.readline().rstrip("\n")

            if query.strip().lower() == "/exit":
                return 0

            console.print()
            result = _run_conversation(console, graph, query)

            if result.get("tool_limit_reached"):
                print_warning(TOOL_LIMIT_WARNING, console)
                console.print("Press Enter to start a new conversation.")
                sys.stdin.readline()
            else:
                content = result["messages"][-1].content if result.get("messages") else ""
                _print_turn(console, "ai", content)
        except KeyboardInterrupt:
            console.print()
            return 0
        except Exception as exc:
            console.print(Text(f"Error: {exc}", style="bold red"))

        console.clear()
