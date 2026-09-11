# Data Model: Cart Total Lookup

This feature introduces no new persisted entities or database schema changes. It derives a
value from two entities that already exist in `SupportState` (`src/customer_support_fde/state.py`).

## Existing Entities Used

### Cart (`SupportState["menu_items"]`)

- **Representation**: `dict[str, int]` mapping menu item name → quantity in the cart.
- **Source**: Populated/mutated by `add_items_to_cart` / `remove_items_from_cart`
  (`tools/cart_tools.py`); read-only for this feature.

### Menu Item (`SupportState["menu"]`, element type `MenuItem` in `tools/menu_tools.py`)

- **Representation**: `dict[str, object]` with at least `name: str` and `price: float`.
- **Source**: Loaded from SQLite at graph setup; read-only for this feature.

## New Value Object: Cart Total (in-memory only, not persisted)

Produced by the new shared helper (see [research.md](./research.md)) and consumed directly by
the new tool — not stored on `SupportState` and not written to the database.

| Field   | Type          | Description                                                                 |
|---------|---------------|-------------------------------------------------------------------------------|
| `total` | `float \| None` | Sum of `price × quantity` across all cart entries, rounded up to the nearest cent (`ROUND_CEILING`, matching `cart_summary_node.build_order_summary`). `None` when the cart is empty (FR-005). |

**Validation / invariants**:
- Every item name in `menu_items` is expected to resolve to a price via the menu (cart
  mutation tools only ever add resolved menu item names, per FR-003 of
  `specs/003-remove-cart-items` / existing `cart_tools.py` behavior) — this feature does not
  need to handle an unresolvable cart line as a new case.
- `total` is never negative (quantities in the cart are always positive; enforced by the
  existing cart-mutation tools, not by this feature).
- Rounding MUST use the same rule as `cart_summary_node.build_order_summary` (FR-004) — this is
  the reason the calculation is a single shared function rather than two implementations.

## State Transitions

None. This feature only reads `menu_items` and `menu`; it does not transition `SupportState`
into any new status and does not mutate the cart.
