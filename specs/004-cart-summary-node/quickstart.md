# Quickstart: Cart Summary at Order Confirmation

Validates the feature end-to-end once implemented. See [data-model.md](./data-model.md) and
[contracts/cart-summary-node.md](./contracts/cart-summary-node.md) for the exact shapes and wording
referenced below.

## Prerequisites

- Python 3.14 environment with project dependencies installed: `uv sync` (or equivalent) from repo
  root.
- Same environment variables as `specs/002-order-support-agent/quickstart.md`
  (`OPENROUTER_API_KEY` required for live CLI calls only; `OPENROUTER_MODEL` optional; LangSmith
  tracing variables optional locally). **None of the automated tests below need an API key** — the
  summary node makes no model call.

## Run the automated tests (no live API calls required)

```sh
pytest tests/unit/test_menu_tools.py -v
pytest tests/unit/test_cart_summary_and_ticket_nodes.py -v
pytest tests/integration/test_order_support_trajectory.py -v
```

Expected outcome:

- `test_menu_tools.py` covers `price_for_item`: exact canonical-name hit returns the menu price, a
  name not on the menu returns `None`, and an empty menu returns `None`.
- `test_cart_summary_and_ticket_nodes.py` calls the pure functions directly with hand-built carts and
  a sample menu (no LLM, no graph) and asserts:
  - `build_order_summary` — multi-item line totals and order total; a single-unit order; that the
    total always rounds up (never down) to the cent; an empty cart yielding `total is None` (not
    `0.0`); and that the input cart dict is not mutated.
  - `render_order_summary` — every item name and quantity present, one `Total:` line for a fully
    priced order, and the empty-cart wording with no amount line.
  - `cart_summary_node` — writes `order_summary` and appends exactly one `AIMessage` whose content
    is the rendered text.
  - `ticket_gen_node` — `order_ticket` carries the same `lines` and `total` as `order_summary` (the
    FR-010/SC-004 guarantee), alongside the existing `items` mapping.
- `test_order_support_trajectory.py` confirms a full conversation still reaches the summary and
  ticket steps, with the expected node-name trajectory updated from `confirm_node` to
  `cart_summary` and the two `order_ticket` assertions updated to the priced shape.

## Manually exercise the CLI (requires `OPENROUTER_API_KEY`)

The CLI is one long-running process per conversation: it prints each turn's reply and reads the next
customer line from stdin until the order is confirmed (`cli.py`'s `while "__interrupt__" in result`
loop). At an interactive prompt:

```text
$ customer-support-fde "Add two kung pao chicken and a hot and sour soup"
> (reply confirms both were added, asks if there's anything else)
That's everything, go ahead
> Here's your order:
> - Kung Pao Chicken x2 @ $12.95 each = $25.90
> - Hot and Sour Soup x1 @ $5.50 each = $5.50
>
> Total: $31.40
```

Check the JSON path too — every amount must serialize cleanly:

```sh
customer-support-fde --json "Add a spring roll, that's all"
```

## Manual reply-quality checks (not covered by automated tests, per `specs/002-order-support-agent/research.md` §9's testing-scope decision, which this feature follows)

- [ ] The summary appears after confirmation without the customer having to ask for it.
- [ ] Quantities in the summary match what the customer actually asked for across the whole
      conversation, including items added in separate turns (one consolidated line, not one per add).
- [ ] An item added and then removed does not appear in the summary.
- [ ] The arithmetic is checkable by hand: each line is unit price times quantity, and the lines add
      up to the stated total.
- [ ] Names in the summary are the restaurant's menu names, not the customer's phrasing.

## Validation checklist (maps to spec Success Criteria)

- [ ] SC-001: Every confirmed order produces a summary naming every ordered item with its quantity.
- [ ] SC-002: The stated total survives an independent recalculation from menu prices and
      quantities — verify by hand on a multi-item order and by the rounding-invariant unit test.
- [ ] SC-003: The summary answers "what did I order and what does it cost" with no follow-up
      question needed.
- [ ] SC-004: `order_ticket`'s items, quantities, and total match the summary text the customer saw.
- [ ] SC-005: An empty cart produces the "nothing to summarize" wording and no amount line. (A
      unit-tested defensive branch — `mark_order_confirmed` blocks empty-cart confirmation on
      today's graph, see [research.md](./research.md) §6.)
