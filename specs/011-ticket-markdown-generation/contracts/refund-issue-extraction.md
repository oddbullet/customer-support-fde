# Contract: `_extract_refund_issue` in `nodes/ticket_gen_node.py`

New private helper, called only from `_refund_ticket_node` (the refund branch of the unified
`ticket_gen_node` — `contracts/tickets-module.md`). Reads the conversation directly instead of
any new `SupportState` field (`research.md` Decisions 5, 5a).

## `_extract_refund_issue(state: SupportState) -> str | None`

- Builds context from `state.get("refund_conversation_summary")` (if not `None`) followed by
  `state["messages"]` — the full accumulated refund transcript
  (`specs/007-refund-policy-agent/research.md` Decision 7: the refund flow never clears
  `messages` between turns).
- Returns `None` without calling the model when both are empty/absent (nothing to summarize).
- Otherwise calls a plain (non-tool-bound) LLM — its own `_build_llm()`, the same
  `ChatOpenAI(base_url=..., api_key=..., model=...)` shape `refund_agent.py` and `router_agent.py`
  already use — with a system instruction asking for a one-to-two-sentence statement of the
  customer's issue/complaint in their own terms, or the literal reply `"None"` if the transcript
  raised no issue at all.
- Returns `None` when the model's reply, stripped and case-folded, equals `"none"`.
- Returns `None` and logs at `WARNING` via `logging.getLogger(__name__)` if the LLM call itself
  raises — never lets the exception propagate (`research.md` Decision 5a).
- Otherwise returns the model's reply text, stripped.

## Guarantees

1. `_extract_refund_issue` never raises — every input (empty transcript, model failure, no
   issue found) resolves to either a string or `None`, never an exception (Decision 5a).
2. It is called exactly once per refund-agent interaction, from `_refund_ticket_node`, using the
   `messages`/`refund_conversation_summary` state as it stands at the moment the graph reaches
   its refund-resolved terminal step — never re-invoked or retried within one conversation.
3. It makes no `Command` update and touches no tool — `tools/refund_tools.py` and `state.py` are
   both unmodified by this feature (contrast with the superseded `refund_issue`-state-field
   design this replaces).
4. `order_id`, `sentiment`, and `refund_created` on the same `refund_ticket` dict are **not**
   produced by this function or any other LLM call — they remain sourced directly from
   `state["order_lookup"]`, `state["sentiment"]`, and `state["refund_request"] is not None`
   respectively (`research.md` Decision 5, `data-model.md` § Refund Ticket).
