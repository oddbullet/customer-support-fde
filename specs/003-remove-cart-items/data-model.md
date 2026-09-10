# Phase 1 Data Model: Remove Items From Cart

This feature adds no persistent storage and no `SupportState` fields. It adds one new request-shape entity used only as this tool's argument type; the existing Cart entity's stored shape (`dict[str, int]`) is unchanged.

## Cart (`menu_items`) — unchanged

Still `dict[str, int]`, keyed by canonical menu item name, valued by quantity, as defined in `specs/002-order-support-agent/data-model.md`. This feature only adds a new way to shrink or delete entries from it (via `remove_items_from_cart`); it does not change how entries are added or structured, and does not touch any other `SupportState` field.

### New validation rules (additive to the existing ones)

- A `remove_items_from_cart` call MUST NOT leave a zero- or negative-quantity entry in `menu_items` — reaching zero (or a requested quantity at or beyond the entry's current amount) MUST delete the key entirely (FR-004, FR-007).
- A `remove_items_from_cart` call MUST NOT create a new entry, change an unrelated entry, or mutate the caller's `menu_items` mapping in place — it operates on a derived copy, same guarantee `add_items_to_cart` already provides.

## CartRemoval (new — tool argument shape only, not stored state)

One entry in the `items` list the LLM passes to `remove_items_from_cart`. Never persisted; exists only for the duration of one tool call.

| Field | Type | Notes |
|---|---|---|
| `name` | `str` | The customer's item name as given; resolved via `resolve_menu_item` (`tools/menu_tools.py`), same fuzzy-match/tie/not-found behavior used by `get_menu_item` and `add_items_to_cart`. |
| `quantity` | `int \| None` | `None` (or omitted) means "remove the entire entry regardless of current quantity" (FR-002). A positive integer means "decrement by this amount," capped at the entry's current quantity (FR-003, FR-007). |

### Validation rules

- `name` MUST be resolved through `resolve_menu_item` before being used as a `menu_items` key — never the raw customer-supplied text (consistent with the existing Cart validation rule).
- `quantity`, when given, is expected to be a positive integer; the tool's behavior is defined only for `None` or a positive `quantity` (matching the spec's scope — no negative/zero-quantity scenario is described in FR-001–FR-008).

## Tool contract (addition to the existing four)

| Tool | Signature | Injected? | Returns |
|---|---|---|---|
| `remove_items_from_cart` | `(items: list[CartRemoval], state: Annotated[SupportState, InjectedState]) -> Command` | Yes (`InjectedState`) | `Command(update={"menu_items": <updated cart>, "messages": [ToolMessage(...)]})` — per-item found/tie/not-found/not-in-cart outcomes summarized in the `ToolMessage` content; only a `found` resolution that is also present in the cart changes `menu_items` (FR-001–FR-008). |

This sits alongside the four tools already documented in `specs/002-order-support-agent/data-model.md`'s "Tool contracts" table — none of those four change.
