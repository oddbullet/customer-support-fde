# Phase 1 Data Model: Order/Support Agent with Menu Tools

This feature has no persistent storage (see `research.md` §6, plan Technical Context: Storage = N/A for conversation data). `menu.json` is static, read-only, bundled data, not a runtime storage system. All conversation entities below live only on the shared LangGraph state object (`SupportState`) for the lifetime of a single graph run.

**Revision note (2026-09-10)**: The original design's `OrderIntentDecision` (a single structured-output classification per turn) is removed — replaced by a native tool-calling loop (`research.md` §2). `SupportState` gains a `messages` field to support that loop. Tool contracts (`get_menu`, `get_menu_item`, `add_items_to_cart`, `mark_order_confirmed`) replace the classify-then-dispatch design.

## SupportState (extended)

The shared state schema across all nodes. `user_query`, `destination`, and `sentiment` are unchanged from `specs/001-router-agent/contracts/support-state.md`. Four fields are new:

| Field | Type | Populated by | Notes |
|---|---|---|---|
| `user_query` | `str` | *(unchanged, see 001)* | Holds the customer's original request as forwarded by the router; `order_support`'s own turn-by-turn exchange happens via `messages`, not by continuing to mutate this field. |
| `destination` | `Literal["order_support", "refund", "unclear"]` | *(unchanged, see 001)* | — |
| `sentiment` | `Literal["positive", "neutral", "negative"] \| None` | *(unchanged, see 001)* | — |
| `messages` | `list[AnyMessage]` (LangChain message objects: `SystemMessage`, `HumanMessage`, `AIMessage`, `ToolMessage`) | `call_model`, `order_tools` (`ToolNode`), `await_customer` | Scratch, **per-turn** message list for the tool-calling loop (`research.md` §4). Reset at the start of every customer turn (first turn seeded from `user_query`; later turns seeded on `interrupt()` resume) — never accumulates across turns. |
| `menu_items` | `dict[str, int]` | `add_items_to_cart` tool (via `Command`) | The Cart entity. Keyed by menu item name, valued by quantity; starts as `{}`. Persists across turns (unlike `messages`). |
| `order_confirmed` | `bool` | `mark_order_confirmed` tool (via `Command`) | `True` only once the customer has explicitly confirmed they're done with a non-empty cart (FR-006, FR-007); starts `False`. Read by `await_customer`'s routing to decide `confirm_node` vs. continuing the conversation. |
| `order_ticket` | `dict \| None` | `ticket_gen_node` | The placeholder Order Ticket artifact (FR-008); starts `None`. |

### Validation rules

- `messages` MUST be reset (not appended to) at the start of each new customer turn — it is scratch state scoped to one turn's tool-calling exchange, not a conversation transcript (`research.md` §4).
- `menu_items` MUST only contain keys that are exact menu item names (post-resolution) — never the customer's raw, unresolved input text (FR-003, FR-005).
- `menu_items[name]` MUST be a positive integer, incrementing by exactly 1 per successful add of that item (FR-004, Edge Cases) — including when multiple additions of the same item arrive in one batched `add_items_to_cart` call.
- `order_confirmed` MUST be `False` on every turn except the one where `mark_order_confirmed` is called with a non-empty `menu_items` — it MUST NOT be set `True` when `menu_items` is empty (FR-007, Edge Cases: "done without having added any items").
- `order_ticket` MUST be `None` until `ticket_gen_node` runs, and once set MUST reflect exactly the `menu_items` present at the moment `order_confirmed` became `True` (SC-003).

### Lifecycle

`menu_items` accumulates across repeated turns within one conversation/thread (no persistence beyond that, per Assumptions). `order_confirmed` flips `False → True` at most once per conversation. `messages` is rebuilt fresh every turn and holds only that turn's system/human/AI/tool messages — it is discarded (conceptually) once `await_customer` either calls `interrupt()` or routes to `confirm_node`.

## MenuItem (menu data, not state) — unchanged

Loaded from `menu/menu.json` (research.md §6), not part of `SupportState`.

| Field | Type | Notes |
|---|---|---|
| `name` | `str` | Canonical display name and the key used in `menu_items`. Unique across the menu (FR-009). |
| `price` | `number` | Positive. |
| `ingredients` | `list[str]` | Non-empty. |

At least 5 `MenuItem` entries MUST exist in `menu.json` (FR-009).

## MenuMatch (internal to `tools/menu_tools.py`) — unchanged

The tagged result of `resolve_menu_item(name, menu)` — shared by the `get_menu_item` tool and `add_items_to_cart`.

| Status | Payload | Meaning |
|---|---|---|
| `found` | `item: MenuItem` | Exactly one candidate at the top match score, at or above the cutoff. |
| `tie` | `candidates: list[str]` | Two or more item names tied at the top score, at or above the cutoff (FR-005a). |
| `not_found` | *(none)* | No candidate meets the cutoff (FR-005). |

## Tool contracts (replaces `OrderIntentDecision`)

Four LLM-callable tools, bound to the model in `call_model` and executed by `order_tools` (`ToolNode`):

| Tool | Signature | Injected? | Returns |
|---|---|---|---|
| `get_menu` | `() -> str` | No | A rendered listing of every menu item (name/price/ingredients), as `ToolMessage` content. |
| `get_menu_item` | `(name: str) -> str` | No | A rendered `found`/`tie`/`not_found` result for one name, via `resolve_menu_item`. |
| `add_items_to_cart` | `(names: list[str], state: Annotated[SupportState, InjectedState]) -> Command` | Yes (`InjectedState`) | `Command(update={"menu_items": <updated cart>, "messages": [ToolMessage(...)]})` — per-name found/tie/not_found results summarized in the `ToolMessage` content; only `found` resolutions change `menu_items` (FR-003, FR-004, FR-005, FR-005a). |
| `mark_order_confirmed` | `(state: Annotated[SupportState, InjectedState]) -> Command` | Yes (`InjectedState`) | `Command(update={"order_confirmed": True, ...})` when `menu_items` is non-empty; otherwise `Command(update={"messages": [...]})` only, leaving `order_confirmed` unchanged (FR-006, FR-007, Edge Cases). |

None of these are forwarded to downstream nodes as a separate internal type — their effect is entirely expressed through the `Command` updates they make to `SupportState`.

## Order Ticket (placeholder artifact) — unchanged

The `order_ticket` `SupportState` field **is** the Order Ticket entity from the spec's Key Entities — intentionally minimal (`{"items": {<name>: <quantity>, ...}}`) for this feature (FR-008, Assumptions).
