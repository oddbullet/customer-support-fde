# Phase 0 Research: Remove Items From Cart

All spec-level ambiguities were already closed in `/speckit-clarify`. The one open technical decision for this feature is the removal tool's argument shape, since it has to express two different clarified behaviors (unqualified name → full removal; named quantity → partial decrement) through a single LLM-callable tool signature.

## 1. Removal request shape: `list[CartRemoval]` vs. parallel `names`/`quantities` lists vs. a single-item tool

**Decision**: One new pydantic model in `tools/cart_tools.py`:

```python
class CartRemoval(BaseModel):
    name: str
    quantity: int | None = None
```

`remove_items_from_cart(items: list[CartRemoval], state: Annotated[SupportState, InjectedState], tool_call_id: Annotated[str, InjectedToolCallId]) -> Command` accepts a batch of these in one call, mirroring `add_items_to_cart`'s batching but pairing each name with its own optional quantity rather than requiring the caller to repeat a name per unit.

**Rationale**: `add_items_to_cart(names: list[str])` works because every add is implicitly "one unit"; removal isn't uniform in that way once quantity-qualified removal is in scope (FR-003), so a bare `list[str]` can't express "remove 2 of the fried rice" alongside "remove the spring rolls" in the same batch. A pydantic model is the least-new-surface way to give the LLM a structured per-item argument — `nodes/router_agent.py` already establishes the pattern of a pydantic model describing a model-populated shape (`RouterDecision`), and `@tool`'s schema inference handles a `list[SomePydanticModel]` field directly, so no manual JSON-schema authoring is needed.

**Alternatives considered**: Two parallel lists, `names: list[str]` and `quantities: list[int | None]` — rejected: correctness would depend on the LLM keeping two lists the same length and correctly aligned, which is a needless way to reintroduce the exact pairing a single structured list already guarantees. A single-item `remove_item_from_cart(name: str, quantity: int | None)` tool (no batching) — rejected: the spec (FR-008) explicitly requires removing more than one distinct item per request to be supported the same way `add_items_to_cart` already batches, and per-item independent reporting falls out naturally from iterating one batched call rather than relying on the model to make several separate tool calls in one turn.

## 2. Full-removal vs. partial-decrement dispatch

**Decision**: A single helper, `_apply_removal(cart: dict[str, int], match: MenuMatch, quantity: int | None) -> str`, holds the branching: not `found` → report tie/not-found (reusing the same rendering pattern as `add_items_to_cart`'s `_render_add_result`); `found` but the resolved name isn't a key in `cart` → report "isn't in your cart"; `found` and present → if `quantity is None` or `quantity >= cart[name]`, `del cart[name]` (full removal, reporting the amount that was actually removed); otherwise `cart[name] -= quantity` (partial decrement, entry kept).

**Rationale**: Keeps the "how much actually got removed" computation and its customer-facing message in one place, mirroring how `_render_add_result` keeps `add_items_to_cart`'s per-name outcome message next to the state change it describes. Capping the requested quantity at the entry's current amount directly implements FR-007 without a separate over-removal branch.

**Alternatives considered**: Raising/erroring on an over-large requested quantity — rejected, explicitly ruled out by FR-007 in favor of capping and reporting the actual amount removed.

## Outcome

No `NEEDS CLARIFICATION` markers remain. No new third-party dependency, no new graph node, no `SupportState` schema change.
