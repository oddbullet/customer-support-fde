from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import tools_condition

from customer_support_fde.nodes.clarify_intent import clarify_intent
from customer_support_fde.nodes.confirm_node import confirm_node
from customer_support_fde.nodes.order_support_agent import (
    await_customer,
    call_model,
    order_tools,
)
from customer_support_fde.nodes.refund_agent import refund_agent
from customer_support_fde.nodes.router_agent import router_agent
from customer_support_fde.nodes.ticket_gen_node import ticket_gen_node
from customer_support_fde.state import SupportState


def _route_from_destination(state: SupportState) -> str:
    return state["destination"]


def _route_from_await_customer(state: SupportState) -> str:
    return "confirmed" if state["order_confirmed"] else "continue"


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    graph = StateGraph(SupportState)

    graph.add_node("router_agent", router_agent)
    graph.add_node("clarify_intent", clarify_intent)
    graph.add_node("call_model", call_model)
    graph.add_node("order_tools", order_tools)
    graph.add_node("await_customer", await_customer)
    graph.add_node("confirm_node", confirm_node)
    graph.add_node("ticket_gen_node", ticket_gen_node)
    graph.add_node("refund_agent", refund_agent)

    graph.set_entry_point("router_agent")
    graph.add_conditional_edges(
        "router_agent",
        _route_from_destination,
        {
            "order_support": "call_model",
            "refund": "refund_agent",
            "unclear": "clarify_intent",
        },
    )
    graph.add_conditional_edges(
        "clarify_intent",
        _route_from_destination,
        {
            "order_support": "call_model",
            "refund": "refund_agent",
        },
    )
    graph.add_conditional_edges(
        "call_model",
        tools_condition,
        {"tools": "order_tools", "__end__": "await_customer"},
    )
    graph.add_edge("order_tools", "call_model")
    graph.add_conditional_edges(
        "await_customer",
        _route_from_await_customer,
        {"continue": "call_model", "confirmed": "confirm_node"},
    )
    graph.add_edge("confirm_node", "ticket_gen_node")
    graph.add_edge("ticket_gen_node", END)
    graph.add_edge("refund_agent", END)

    return graph.compile(checkpointer=checkpointer)
