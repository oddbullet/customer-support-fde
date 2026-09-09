import argparse
import json
import sys
import uuid

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from customer_support_fde.clarify_intent import QUESTION
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
    args = _parse_args(argv)
    query = _read_query(args)

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    try:
        result = graph.invoke(
            {"user_query": query, "destination": "order_support", "sentiment": None},
            config,
        )
        while "__interrupt__" in result:
            print(QUESTION)
            answer = sys.stdin.readline().rstrip("\n")
            result = graph.invoke(Command(resume=answer), config)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    _print_result(result, args.as_json)
    return 0
