# Quickstart: Order/Support Agent with Menu Tools

Validates the feature end-to-end once implemented. See [data-model.md](./data-model.md) and [contracts/](./contracts/) for the exact shapes referenced below.

**Revision note (2026-09-10)**: updated for the native tool-calling design (`research.md` §2/§4/§5) — replaces the earlier classify-then-dispatch/reply-template description. Reply *wording* is now model-composed and validated manually here, not asserted by automated tests (the previously-considered LLM-as-judge layer was dropped from scope).

## Prerequisites

- Python 3.14 environment with project dependencies installed: `uv sync` (or equivalent) from repo root.
- `src/customer_support_fde/menu/menu.json` present with at least 5 items (FR-009).
- Environment variables (same as `specs/001-router-agent/quickstart.md`):
  - `OPENROUTER_API_KEY` — required for live calls (router and order-support).
  - `OPENROUTER_MODEL` — optional.
  - Standard LangSmith tracing variables — optional locally, expected in any traced/CI run (Constitution Principle IV).

## Run the automated tests (no live API calls required)

```sh
pytest tests/unit/test_menu_tools.py -v
pytest tests/unit/test_cart_tools.py -v
pytest tests/unit/test_order_support_agent.py -v
pytest tests/unit/test_confirm_and_ticket_nodes.py -v
pytest tests/integration/test_order_support_trajectory.py -v
```

Expected outcome:
- `test_menu_tools.py` confirms `resolve_menu_item` found/tie/not-found resolution over a sample menu — no LLM involved ([contracts/menu-tools.md](./contracts/menu-tools.md)).
- `test_cart_tools.py` calls `add_items_to_cart`/`mark_order_confirmed` directly with a hand-built state dict (no LLM, no graph) and asserts the returned `Command.update` — batched multi-item adds, quantity increments, tie/not-found leaving the cart unchanged ([contracts/cart-tools.md](./contracts/cart-tools.md)).
- `test_order_support_agent.py` confirms the `call_model ⇄ order_tools` loop, with the LLM boundary faked to return canned `AIMessage`s carrying specific `tool_calls`: real tool execution runs against those calls, and assertions target the resulting `SupportState` (`menu_items`, `order_confirmed`) — not the model's reply text ([contracts/order-support-agent.md](./contracts/order-support-agent.md)).
- `test_confirm_and_ticket_nodes.py` confirms `confirm_node`'s pass-through and `ticket_gen_node`'s placeholder `order_ticket` shape ([contracts/confirm-and-ticket-nodes.md](./contracts/confirm-and-ticket-nodes.md)).
- `test_order_support_trajectory.py` confirms, via `agentevals.graph_trajectory.strict.graph_trajectory_strict_match` across multiple `Command(resume=...)` turns, that a full ordering conversation (add one item → add a second item → confirm done) reaches `confirm_node`/`ticket_gen_node` with the trajectory expressed as **nested per-resume segments** (matching the pattern already established in `tests/integration/test_router_trajectory.py` for multi-`interrupt()` conversations — each segment ends at `"__interrupt__"` except the last), e.g.:
  ```python
  reference_outputs = {
      "steps": [
          ["__start__", "router_agent", "call_model", "order_tools", "call_model", "__interrupt__"],
          ["call_model", "order_tools", "call_model", "__interrupt__"],
          ["call_model", "order_tools", "call_model", "confirm_node", "ticket_gen_node"],
      ]
  }
  ```
  (exact node sequence per segment depends on how many tool-calling rounds the faked model takes within each turn).
- All test modules fake the LLM boundary so they run deterministically offline; none assert on model-composed reply text.

## Manually exercise the CLI (requires `OPENROUTER_API_KEY`)

```sh
customer-support-fde "What's on the menu?"
# > (full menu listing, composed by the model from the get_menu tool result)

customer-support-fde "What do you recommend if I like spicy food?"
# > (a genuine recommendation, reasoned over the get_menu tool result — not a raw listing)

customer-support-fde "Add two spring rolls and a kung pao chicken"
# > (one add_items_to_cart(names=["spring rolls", "kung pao chicken"]) call handles both;
#    reply should mention both items were added and ask if there's anything else)

customer-support-fde "Do you have kung pao chicken?"
# Destination: order_support
# ... (interrupt loop begins)
# > (item detail, or a disambiguation question if the name is ambiguous against the seeded menu)
# (customer replies to continue the conversation, e.g. "add one")
# > (confirmation the item was added, plus an "anything else?"-style question)
# (customer types "no, that's all")
# > (an acknowledgment that the order is confirmed)
```

Note: per `research.md` §8, `cli.py`'s resume loop must print the actual `interrupt()` payload (not a hardcoded constant) for this multi-turn exchange to display correctly.

## Manual reply-quality checks (not covered by automated tests — research.md §9)

- [ ] A recommendation-style question ("what do you recommend?") gets a reasoned answer referencing actual menu items, not a raw `get_menu` dump.
- [ ] A message naming two or more items to add in one sentence results in all of them being added (one `add_items_to_cart` call, not just the first item).
- [ ] After a successful add, the reply asks some form of "anything else?" (FR-006 — wording not fixed, but the question should be present).
- [ ] A tie between two similarly-named items produces a reply asking which one was meant, not a guess.

## Validation checklist (maps to spec Success Criteria)

- [ ] SC-001: A single item-detail question for an existing item returns full name/price/ingredients with no follow-up needed.
- [ ] SC-002: A single menu question returns every seeded menu item.
- [ ] SC-003: For every trajectory-test conversation, `order_ticket["items"]` exactly matches the `menu_items` accumulated before confirmation.
- [ ] SC-004: Every trajectory-test conversation that adds ≥1 item and confirms reaches `ticket_gen_node`; no conversation reaches `confirm_node`/`ticket_gen_node` before an explicit confirmation with a non-empty cart.
- [ ] SC-005: Unit tests over labeled name variants (exact, partial, typo, tie, unrelated) confirm `resolve_menu_item` returns `found`/`tie`/`not_found` as expected in each case.
