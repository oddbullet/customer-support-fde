"""Drives a live, multi-turn conversation against the real compiled graph.

Only the customer's side of the conversation is scripted - the assistant's
replies come from the real LLM, so the exact tool-call sequence can't be
scripted the way the mocked integration tests do.
"""

from dataclasses import dataclass, field

from customer_support_fde.nodes.account_identification_node import (
    PRIMARY_MENU,
    RECOVERY_MENU,
)
from customer_support_fde.state import initial_state
from langgraph.types import Command


@dataclass
class ConversationTranscript:
    turns: list[tuple[str, str]] = field(default_factory=list)
    final_result: dict = field(default_factory=dict)
    hit_cap: bool = False

    def format(self) -> str:
        lines = [f"[interrupt] {prompt}\n[customer] {reply}" for prompt, reply in self.turns]
        if self.final_result.get("__interrupt__"):
            lines.append(f"[assistant] {self.final_result['__interrupt__'][0].value}")
        elif self.final_result.get("messages"):
            lines.append(f"[assistant] {self.final_result['messages'][-1].content}")
        lines.append(f"[hit_cap] {self.hit_cap}")
        return "\n\n".join(lines)


def _next_reply(interrupt_text: str, script: list[str], fallback: str) -> str:
    if interrupt_text in (PRIMARY_MENU, RECOVERY_MENU):
        return "2"
    if script:
        return script.pop(0)
    return fallback


def drive_conversation(
    graph,
    config: dict,
    query: str,
    script: list[str],
    *,
    max_turns: int = 8,
    fallback: str = "No, that's everything - please go ahead and finish that up.",
) -> ConversationTranscript:
    transcript = ConversationTranscript()
    result = graph.invoke(initial_state(query), config)

    turn_count = 0
    while "__interrupt__" in result and turn_count < max_turns:
        interrupt_text = result["__interrupt__"][0].value
        reply = _next_reply(interrupt_text, script, fallback)
        transcript.turns.append((interrupt_text, reply))
        result = graph.invoke(Command(resume=reply), config)
        turn_count += 1

    transcript.hit_cap = "__interrupt__" in result
    transcript.final_result = result
    return transcript
