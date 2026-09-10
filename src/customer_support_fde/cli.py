import argparse
import json
import sys
import uuid

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from customer_support_fde.graph import build_graph


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="customer-support-fde")
    parser.add_argument("query", nargs="?", default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser.parse_args(argv)


def _read_query(args: argparse.Namespace) -> str:
    if args.query is not None:
        return args.query
    return sys.stdin.readline().rstrip("\n")


def _print_result(state, as_json: bool) -> None:
    if as_json:
        payload = {"destination": state["destination"], "query": state["user_query"]}
        if state["destination"] == "refund":
            payload["sentiment"] = state["sentiment"]
        print(json.dumps(payload))
        return

    print(f"Destination: {state['destination']}")
    if state["destination"] == "refund":
        print(f"Sentiment: {state['sentiment']}")
    print(f"Query: {state['user_query']}")


def run(argv: list[str] | None = None) -> int:
    # Model-composed replies can contain characters (em dashes, curly quotes)
    # that the default console codec on Windows can't encode; without this,
    # printing such a reply crashes the CLI mid-conversation.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    args = _parse_args(argv)
    query = _read_query(args)

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    try:
        result = graph.invoke(
            {
                "user_query": query,
                "destination": "order_support",
                "sentiment": None,
                "messages": [],
                "menu_items": {},
                "order_confirmed": False,
                "order_ticket": None,
            },
            config,
        )
        while "__interrupt__" in result:
            print(result["__interrupt__"][0].value)
            answer = sys.stdin.readline().rstrip("\n")
            result = graph.invoke(Command(resume=answer), config)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    _print_result(result, args.as_json)
    return 0
