# Quickstart: Remove Items From Cart

Validates the feature end-to-end once implemented. See [data-model.md](./data-model.md) and [contracts/cart-tools.md](./contracts/cart-tools.md) for the exact shapes referenced below.

## Prerequisites

- Python 3.14 environment with project dependencies installed: `uv sync` (or equivalent) from repo root.
- Same environment variables as `specs/002-order-support-agent/quickstart.md` (`OPENROUTER_API_KEY` required for live calls; `OPENROUTER_MODEL` optional; LangSmith tracing variables optional locally).

## Run the automated tests (no live API calls required)

```sh
pytest tests/unit/test_cart_tools.py -v
pytest tests/unit/test_order_support_agent.py -v
pytest tests/integration/test_order_support_trajectory.py -v
```

Expected outcome:
- `test_cart_tools.py` calls `remove_items_from_cart` directly with a hand-built state dict (no LLM, no graph) and asserts the returned `Command.update["menu_items"]` for: full removal when no quantity is given, partial decrement when a smaller quantity is given, capping/full-delete when the requested quantity meets or exceeds what's in the cart, not-in-cart, not-found, tie, a mixed multi-item batch, and never mutating the input dict in place ([contracts/cart-tools.md](./contracts/cart-tools.md)).
- `test_order_support_agent.py` confirms a `remove_items_from_cart` tool call flows through the `call_model ⇄ order_tools` inner loop correctly, with the LLM boundary faked and real tool execution against a sample menu/cart.
- `test_order_support_trajectory.py` confirms a full conversation — add items, remove one, confirm — ends with `menu_items`/`order_ticket` reflecting the removal, via `agentevals.graph_trajectory.strict.graph_trajectory_strict_match` across multiple `Command(resume=...)` turns (same pattern as the existing add/confirm scenario in that file).

## Manually exercise the CLI (requires `OPENROUTER_API_KEY`)

The CLI is one long-running process per conversation: it prints each turn's reply and reads the next customer line from stdin until the order is confirmed (`cli.py`'s `while "__interrupt__" in result` loop). At an interactive prompt:

```text
$ customer-support-fde "Add two spring rolls and a kung pao chicken"
> (reply confirms both were added, asks if there's anything else)
Remove the spring rolls
> (entire Spring Rolls entry removed, regardless of the "two" originally added)
Remove one kung pao chicken
> (Kung Pao Chicken's quantity decremented by one, entry kept if more than one remained)
Remove the mapo tofu
> (told it isn't in the cart, since it was never added)
```

## Manual reply-quality checks (not covered by automated tests, per `specs/002-order-support-agent/research.md` §9's testing-scope decision, which this feature follows)

- [ ] Removing an item by name alone (no quantity mentioned) results in the whole entry disappearing, even if more than one unit was in the cart.
- [ ] Removing a stated smaller quantity keeps the entry with a reduced count, and the reply states the new remaining amount.
- [ ] Removing more units than are present removes all of them and the reply says how many were actually removed, rather than erroring.
- [ ] Removing an item not currently in the cart produces a clear "not in your cart" reply rather than a silent no-op.
- [ ] A tied or unmatched item name produces the same disambiguation/not-found reply style already used by `add_items_to_cart`/`get_menu_item`.

## Validation checklist (maps to spec Success Criteria)

- [ ] SC-001: A single removal request for an existing cart item succeeds with no follow-up needed.
- [ ] SC-002: 100% of removal requests for an item actually present in the cart result in an accurately decremented or deleted entry, matching what was requested (whole entry vs. specified amount).
- [ ] SC-003: Removal requests for an item not in the cart, or with no reasonably close menu match, always receive a clear explanatory reply rather than a silent no-op.
- [ ] SC-004: A removal request whose name ties between two or more menu items is met with a disambiguation question, never a guess.
