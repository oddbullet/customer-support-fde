# Phase 0 Research: Cart Total Lookup

No `[NEEDS CLARIFICATION]` markers remained in the spec, so this phase resolves the small set
of implementation-approach questions the feature raises rather than requirement ambiguities.

## Decision: Where the total-calculation logic lives

**Decision**: Extract the existing total-calculation logic (currently inlined in
`build_order_summary` in `src/customer_support_fde/nodes/cart_summary_node.py`, lines 10-33)
into a shared function in `src/customer_support_fde/tools/menu_tools.py`, next to the existing
`price_for_item` helper. Both `cart_summary_node.build_order_summary` (used at order
confirmation) and the new cart-total tool (used mid-conversation) call this shared function.

**Rationale**: The spec requires (FR-004) that a total quoted mid-conversation use the same
rounding rule as the final order total. Two independent implementations of a
round-up-to-nearest-cent calculation would drift silently if one were changed without the
other — exactly the kind of duplication Principle III (Simplicity/YAGNI) and the correctness
goal in SC-003 argue against. `menu_tools.py` is already the shared home for menu/price
lookups that both `cart_tools.py` and `cart_summary_node.py` import from, so it is the natural
location with no new module needed.

**Alternatives considered**:
- *Duplicate the calculation in the new tool*: Rejected — creates exactly the drift risk
  FR-004/SC-003 are meant to prevent, and violates Simplicity by introducing a second copy of
  the same rule.
- *New `pricing.py` module*: Rejected — an extra module for one small function is unjustified
  complexity per Principle III when `menu_tools.py` already serves this role.

## Decision: Tool response shape

**Decision**: The new tool returns a plain human-readable string (e.g.
`"Your current cart total is $23.50."` or `"Your cart is empty, so there's no total yet."`),
consistent with every other tool in `menu_tools.py` and `cart_tools.py` (`get_menu`,
`get_menu_item`, `add_items_to_cart`, `remove_items_from_cart`), all of which return rendered
strings for the LLM/tool-calling loop to relay directly rather than structured data the agent
would need to further interpret.

**Rationale**: FR-006 requires the agent to relay the total without altering or re-deriving
it. A pre-rendered string leaves no arithmetic for the model to redo — the safest way to
satisfy "the agent MUST NOT do math." This also matches the existing tool-authoring
convention in this codebase.

**Alternatives considered**:
- *Return a raw float/Decimal*: Rejected — leaves room for the model to reformat or
  recompute the figure when composing its reply, reintroducing the exact risk the feature
  exists to remove.

## Decision: No new dependencies, no new persisted state

**Decision**: Implement entirely with data already available on `SupportState`
(`state["menu_items"]`, `state["menu"]`) and the standard-library `decimal.Decimal`
already used by `cart_summary_node.py`. No new database table, no new state field, no new
third-party dependency.

**Rationale**: Per the Technology Constraints section of the constitution, dependencies must
only be added when existing tooling can't reasonably satisfy the need — it can here. The cart
contents and live menu prices are already injected into every cart/menu tool via
`InjectedState`.

**Alternatives considered**:
- *Add a dedicated `cart_total` field to `SupportState`, recomputed on every cart mutation*:
  Rejected — the total is cheap to derive on demand from `menu_items` + `menu`, and caching it
  would add a second source of truth that must be kept in sync with cart mutations, which is
  unjustified complexity for an O(items-in-cart) computation.
