import logging
import sys
import uuid

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from rich.console import Console
from rich.text import Text

from customer_support_fde import db, messages, restaurant_time
from customer_support_fde.circuit_breaker import ModelUnavailableError
from customer_support_fde.graph import build_graph
from customer_support_fde.nodes.cart_summary_node import OrderNotPlacedError
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


# Max graph steps per invoke (LangGraph's recursion_limit). The counter resets on each
# customer reply, so this only stops a runaway loop within a single turn.
WORKFLOW_ITERATION_LIMIT = 100

# Manual "Press Enter to try again" replays per step when both models are down, on top
# of the client retries and circuit breaker; after that the CLI gives up.
MODEL_RETRY_LIMIT = 2

logger = logging.getLogger(__name__)


def print_warning(message: str, console: Console | None = None) -> None:
    if console is None:
        console = _make_console()
    console.print(Text(message, style="red"))


def _fail_and_exit(message: str, console: Console) -> int:
    # Every unrecoverable failure ends the session with one fixed message; the details
    # were already logged, which sends them to Phoenix.
    print_warning(message, console)
    console.print("Press Enter to exit.")
    sys.stdin.readline()
    return 1


def _invoke_with_status(console: Console, graph, state_or_command, config) -> SupportState:
    with console.status("Thinking...", spinner="dots"):
        return graph.invoke(state_or_command, config)


def _invoke_with_retry(console: Console, graph, state_or_command, config) -> SupportState:
    # When both models are down, keep the conversation: on Enter, invoke(None) replays
    # the failed step from the thread's last checkpoint, where the customer's message
    # is already saved.
    retries = 0
    while True:
        try:
            return _invoke_with_status(console, graph, state_or_command, config)
        except ModelUnavailableError:
            if retries >= MODEL_RETRY_LIMIT:
                raise
            retries += 1
            logger.warning("Both models unavailable; manual retry %d", retries)
            print_warning(messages.MODEL_RETRY_PROMPT, console)
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
        # Operator setup check before any customer interaction, so it shows the fix.
        logger.error("Menu database unavailable at startup", exc_info=exc)
        print_warning(str(exc), console)
        return 1

    # Every time shown to the customer or agent is in the restaurant's timezone.
    try:
        restaurant_time.load()
    except restaurant_time.RestaurantTimezoneError as exc:
        logger.error("Restaurant timezone unavailable at startup", exc_info=exc)
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
                logger.error("Tool-call limit reached: %s", result["tool_limit_reached"])
                return _fail_and_exit(messages.GENERIC_ERROR_MESSAGE, console)
            content = result["messages"][-1].content if result.get("messages") else ""
            _print_turn(console, "ai", content)
        except KeyboardInterrupt:
            console.print()
            return 0
        except OrderNotPlacedError as exc:
            logger.error("Confirmed order was not placed", exc_info=exc)
            return _fail_and_exit(messages.ORDER_NOT_PLACED_MESSAGE, console)
        except Exception as exc:
            # Includes GraphRecursionError, ModelUnavailableError after its retries, and
            # store errors: all unrecoverable here, and all get the same message.
            logger.error("Conversation failed: %s", type(exc).__name__, exc_info=exc)
            return _fail_and_exit(messages.GENERIC_ERROR_MESSAGE, console)

        console.clear()
