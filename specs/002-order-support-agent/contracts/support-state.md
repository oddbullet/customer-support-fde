# Contract: `SupportState` (extended)

Extends `specs/001-router-agent/contracts/support-state.md`, which remains authoritative for `user_query`, `destination`, and `sentiment`.

**Revision note (2026-09-10)**: adds `messages` (not in the original 002 design) to support the native tool-calling loop in `research.md` §2/§4.

## Schema

```python
class SupportState(TypedDict):
    user_query: str
    destination: Literal["order_support", "refund", "unclear"]
    sentiment: Literal["positive", "neutral", "negative"] | None
    messages: list[AnyMessage]
    menu_items: dict[str, int]
    order_confirmed: bool
    order_ticket: dict | None
```

## New fields

- `messages` — scratch, per-turn message list (`SystemMessage`/`HumanMessage`/`AIMessage`/`ToolMessage`) for the `call_model ⇄ order_tools` tool-calling loop. Reset at the start of every customer turn; never carried forward. Not meaningful outside an active `order_support` conversation.
- `menu_items` — the customer's cart, keyed by canonical menu item name, valued by quantity. Starts `{}`. Only mutated via the `add_items_to_cart` tool's `Command` return (FR-003, FR-004), and persists across turns (unlike `messages`).
- `order_confirmed` — `False` until `mark_order_confirmed` runs with a non-empty `menu_items`; `True` from that point on (FR-006, FR-007).
- `order_ticket` — `None` until `ticket_gen_node` runs; then `{"items": dict(menu_items)}` (FR-008).

## Guarantees provided by the order-support tool-calling loop (`call_model`, `order_tools`, `await_customer`)

1. `messages` at the start of `call_model` for a given turn contains only that turn's system prompt, a brief cart summary (if non-empty), and the current customer message — never prior turns' messages.
2. `order_tools` (`ToolNode`) executes exactly the tool calls the model requested against the live `SupportState`; `add_items_to_cart` and `mark_order_confirmed` are the only tools that mutate `menu_items`/`order_confirmed`, and only via their returned `Command`.
3. `await_customer` reads `order_confirmed` **after** the inner tool-calling loop has fully settled for that turn (i.e., after the last `Command` update from that turn has applied) before deciding whether to call `interrupt()` or route to `confirm_node` — never mid-loop.
4. `destination` and `sentiment` pass through unchanged (this loop never touches routing/sentiment fields).
5. If the model call itself fails (transport/API error), the failure propagates rather than the loop returning a partial or corrupted `SupportState`.

## Guarantees provided by `confirm_node`

Reached only when `order_confirmed == True`. Pure pass-through: every field of `SupportState` on exit is identical to entry.

## Guarantees provided by `ticket_gen_node`

Reached only via `confirm_node`. Sets `order_ticket = {"items": dict(menu_items)}`; all other fields pass through unchanged.

## Consumers

- `confirm_node`: requires `order_confirmed == True` and `menu_items` non-empty on entry.
- `ticket_gen_node`: requires the same, plus running only after `confirm_node`.
- A future real ticket-summary agent (out of scope here): will read `order_ticket` once this feature's placeholder is replaced.

## Change policy

Any future feature reading or extending `messages`, `menu_items`, `order_confirmed`, or `order_ticket` MUST NOT repurpose their meaning without a corresponding spec/plan update. In particular, `messages`'s per-turn-reset semantics MUST be preserved by any future node that reads it — a node that assumes it holds full conversation history would be wrong.
