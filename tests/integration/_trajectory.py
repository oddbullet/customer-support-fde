"""Shared helper for extracting agentevals trajectories in integration tests.

`extract_langgraph_trajectory_from_thread` raises IndexError on a terminal
snapshot whose "messages" list is empty (agentevals==0.0.9). SupportState's
`messages` field is scratch, per-turn state that legitimately stays an empty
list for conversations that never enter the order-support tool-calling loop
(e.g. a refund conversation) — so we drop an empty "messages" key from each
snapshot's values before handing it to agentevals, which only touches
"steps" for `graph_trajectory_strict_match` and doesn't need "results".
"""

from agentevals.graph_trajectory.utils import extract_langgraph_trajectory_from_snapshots


def extract_outputs(graph, config):
    snapshots = []
    for snapshot in graph.get_state_history(config):
        if isinstance(snapshot.values, dict) and snapshot.values.get("messages") == []:
            snapshot = snapshot._replace(
                values={k: v for k, v in snapshot.values.items() if k != "messages"}
            )
        snapshots.append(snapshot)
    return extract_langgraph_trajectory_from_snapshots(snapshots)["outputs"]
