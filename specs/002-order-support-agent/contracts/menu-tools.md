# Contract: `tools/menu_tools.py`

**Revision note (2026-09-10)**: `get_menu`/`get_menu_item` are now LLM-callable tools (`@langchain_core.tools.tool`-decorated, or equivalent), bound in `call_model` and executed via `order_tools` (`ToolNode`) — see `research.md` §2. The underlying `resolve_menu_item` resolver is unchanged and remains a plain, independently-testable function; the tool wrappers are thin adapters over it, so unit tests target `resolve_menu_item` directly wherever possible (no LLM/graph involved) and need no `InjectedState`.

## `resolve_menu_item(name: str, menu: list[MenuItem]) -> MenuMatch`

Shared resolver used by both the `get_menu_item` tool and `add_items_to_cart` (`contracts/cart-tools.md`), so the two can never disagree about what counts as a match, a tie, or not-found.

**Guarantees**:

1. An exact (case-insensitive) name match always resolves `found` with that exact item.
2. A case-insensitive substring match resolves `found` when it's the unique best-scoring candidate.
3. A minor typo or close variation of exactly one item's name resolves `found` with that item, per the scoring/cutoff in `research.md` §3.
4. When two or more items score equally at the top and above the cutoff, resolves `tie` with all their names, never guessing (FR-005a).
5. When no item scores at or above the cutoff, resolves `not_found` (FR-005) — never fabricates.
6. Deterministic: the same `(name, menu)` input always produces the same `MenuMatch`.

## `get_menu() -> str` (tool)

Returns every item in `menu.json`, rendered as `ToolMessage` content the model can read and reason over (e.g. to answer "what do you recommend?"). Never raises for an empty menu — returns a message saying nothing is available rather than fabricating content (Edge Cases); not exercised in this feature since the menu is always seeded (FR-002, Assumptions).

## `get_menu_item(name: str) -> str` (tool)

Resolves `name` via `resolve_menu_item` and renders the result as `ToolMessage` content: full detail on `found`, the tied candidate names on `tie`, a clear not-found statement on `not_found`. Implements FR-001, FR-005, FR-005a as information available to the model — the model composes the customer-facing reply from this content (`research.md` §9: reply wording itself is not asserted by automated tests in this phase).

## `MenuMatch` (return type)

See `data-model.md` — tagged union of `found` (`item`), `tie` (`candidates: list[str]`), `not_found`.
