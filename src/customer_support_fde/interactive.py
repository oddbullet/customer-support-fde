import sys
import uuid

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from rich.console import Console
from rich.text import Text

from customer_support_fde import db
from customer_support_fde.graph import build_graph
from customer_support_fde.state import SupportState

_SPEAKER_LABELS = {
    "human": "You",
    "ai": "Assistant",
}


def _make_console(force_terminal: bool | None = None) -> Console:
    return Console(force_terminal=force_terminal)


def _print_turn(console: Console, speaker: str, content: str) -> None:
    label = _SPEAKER_LABELS[speaker]
    separator = "\n" if "\n" in content else " "
    console.print(Text(f"{label}:{separator}{content}"))


def _run_conversation(console: Console, graph, query: str) -> SupportState:
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    with console.status("Thinking...", spinner="dots"):
        result = graph.invoke(
            {
                "user_query": query,
                "destination": "order_support",
                "sentiment": None,
                "messages": [],
                "menu": db.load_menu(),
                "menu_items": {},
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
            },
            config,
        )

    while "__interrupt__" in result:
        _print_turn(console, "ai", result["__interrupt__"][0].value)
        console.print("> ", end="")
        answer = sys.stdin.readline().rstrip("\n")
        with console.status("Thinking...", spinner="dots"):
            result = graph.invoke(Command(resume=answer), config)

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
                console.print("Goodbye!")
                return 0

            result = _run_conversation(console, graph, query)

            content = result["messages"][-1].content if result.get("messages") else ""
            _print_turn(console, "ai", content)
        except KeyboardInterrupt:
            console.print("\nGoodbye!")
            return 0
        except Exception as exc:
            console.print(Text(f"Error: {exc}", style="bold red"))

        console.clear()
