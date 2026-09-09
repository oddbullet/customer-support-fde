from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph

from customer_support_fde.clarify_intent import clarify_intent
from customer_support_fde.downstream_agents import order_support_agent, refund_agent
from customer_support_fde.router_agent import router_agent
from customer_support_fde.state import SupportState


def _route_from_destination(state: SupportState) -> str:
    return state["destination"]


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    graph = StateGraph(SupportState)

    graph.add_node("router_agent", router_agent)
    graph.add_node("clarify_intent", clarify_intent)
    graph.add_node("order_support_agent", order_support_agent)
    graph.add_node("refund_agent", refund_agent)

    graph.set_entry_point("router_agent")
    graph.add_conditional_edges(
        "router_agent",
        _route_from_destination,
        {
            "order_support": "order_support_agent",
            "refund": "refund_agent",
            "unclear": "clarify_intent",
        },
    )
    graph.add_conditional_edges(
        "clarify_intent",
        _route_from_destination,
        {
            "order_support": "order_support_agent",
            "refund": "refund_agent",
        },
    )
    graph.add_edge("order_support_agent", END)
    graph.add_edge("refund_agent", END)

    return graph.compile(checkpointer=checkpointer)
