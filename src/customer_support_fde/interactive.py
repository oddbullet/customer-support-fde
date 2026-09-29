import sys
import uuid

from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphRecursionError
from langgraph.types import Command
from rich.console import Console
from rich.text import Text

from customer_support_fde import db
from customer_support_fde.circuit_breaker import ModelUnavailableError
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


_SYSTEM_ISSUE_WARNING = (
    "Sorry, our system is having some issues right now. Please try again later."
)

TOOL_LIMIT_WARNING = _SYSTEM_ISSUE_WARNING

MODEL_UNAVAILABLE_WARNING = _SYSTEM_ISSUE_WARNING

STORE_UNAVAILABLE_WARNING = _SYSTEM_ISSUE_WARNING

ITERATION_LIMIT_WARNING = (
    "Sorry, we weren't able to finish handling your request. "
    "Please ask a member of our staff for help."
)

# Max graph steps per invoke (LangGraph's recursion_limit). The counter resets on each
# customer reply, so this only stops a runaway loop within a single turn.
WORKFLOW_ITERATION_LIMIT = 100


def print_warning(message: str, console: Console | None = None) -> None:
    if console is None:
        console = _make_console()
    console.print(Text(message, style="red"))


def _warn_and_wait_for_new_conversation(message: str, console: Console) -> None:
    print_warning(message, console)
    console.print("Press Enter to start a new conversation.")
    sys.stdin.readline()


def _invoke_with_status(console: Console, graph, state_or_command, config) -> SupportState:
    with console.status("Thinking...", spinner="dots"):
        return graph.invoke(state_or_command, config)


def _invoke_with_retry(console: Console, graph, state_or_command, config) -> SupportState:
    # When both models are down, keep the conversation: on Enter, invoke(None) replays
    # the failed step from the thread's last checkpoint, where the customer's message
    # is already saved.
    while True:
        try:
            return _invoke_with_status(console, graph, state_or_command, config)
        except ModelUnavailableError:
            print_warning(MODEL_UNAVAILABLE_WARNING, console)
            console.print("Press Enter to try again.")
            sys.stdin.readline()
            state_or_command = None


def _run_conversation(console: Console, graph, query: str) -> SupportState:
    thread_id = str(uuid.uuid4())
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": WORKFLOW_ITERATION_LIMIT,
    }

    result = _invoke_with_retry(console, graph, initial_state(query), config)

    while "__interrupt__" in result:
        _print_turn(console, "ai", result["__interrupt__"][0].value)
        console.print("> ", end="")
        answer = sys.stdin.readline().rstrip("\n")
        console.print()
        result = _invoke_with_retry(console, graph, Command(resume=answer), config)

    return result


_WELCOME_MESSAGE = (
    "Welcome to the restaurant's customer support assistant.\n"
    "Ask a question, place an order, or request a refund.\n"
    "Type '/exit' or press Ctrl+C at any time to quit."
)


def run_interactive() -> int:
    console = _make_console()

    # Every conversation starts by loading the menu, so a missing or broken menu
    # database would fail every message; stop up front with the fix instead.
    try:
        db.load_menu()
    except db.MenuStoreError as exc:
        print_warning(str(exc), console)
        return 1

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
                _warn_and_wait_for_new_conversation(TOOL_LIMIT_WARNING, console)
            else:
                content = result["messages"][-1].content if result.get("messages") else ""
                _print_turn(console, "ai", content)
        except GraphRecursionError:
            _warn_and_wait_for_new_conversation(ITERATION_LIMIT_WARNING, console)
        except db.OrderStoreError:
            _warn_and_wait_for_new_conversation(STORE_UNAVAILABLE_WARNING, console)
        except KeyboardInterrupt:
            console.print()
            return 0
        except Exception as exc:
            console.print(Text(f"Error: {exc}", style="bold red"))

        console.clear()
