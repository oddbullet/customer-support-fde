# Contract: graph surface and CLI

**Feature**: `specs/005-sqlite-menu-orders`

What changes for callers of the graph and the `customer-support-fde` command.

---

## Graph wiring: unchanged

`graph.py` is not modified. No node is added, no edge is retargeted, and `router_agent` remains the
entry point.

**Trajectory impact: none.** Every expected-trajectory assertion in
`tests/integration/test_order_support_trajectory.py` and `test_router_trajectory.py` stays exactly
as it is.

The menu arrives instead on the **initial state** built by the caller:

```python
graph.invoke({..., "menu": db.load_menu(), "order_id": None, ...}, config)
```

| Aspect | Contract |
|---|---|
| Loaded | Once per run, when the caller builds the input dict (FR-002). |
| Survives interrupts | Yes — `Command(resume=...)` continues from the checkpoint and never re-applies the input dict, so the snapshot persists for the whole run (US3). The cart already relies on this. |
| Failure | `MenuStoreError` is raised before `graph.invoke` is reached: the run never starts, no LLM call is made, no checkpoint is written, and the CLI exits 1 with the error on stderr (FR-003). |

---

## Menu tools — signature changes

```python
@tool
def get_menu(state: Annotated[SupportState, InjectedState]) -> str

@tool
def get_menu_item(name: str, state: Annotated[SupportState, InjectedState]) -> str
```

Both now read `state["menu"]` instead of calling `_load_menu()`. `_load_menu()` and the
`json`/`importlib.resources`/`lru_cache` imports are deleted from `menu_tools.py`.

**The model-facing schema is unchanged.** `InjectedState` parameters are stripped from the schema
sent to the LLM, so `get_menu` still takes no arguments and `get_menu_item` still takes only
`name`. The system prompt needs no edit, and `resolve_menu_item`, `price_for_item`, `_score`,
`_render_item`, `_render_menu`, and `_render_match` are untouched — which is how FR-004 (customer-
visible matching behavior unchanged) is satisfied.

`cart_tools.py` changes identically: `add_items_to_cart` and `remove_items_from_cart` already take
`InjectedState`, so their two `_load_menu()` calls become `state["menu"]` and the import is dropped.

---

## `cart_summary_node` — new output

```python
def cart_summary_node(state: SupportState) -> SupportState
```

| Aspect | Contract |
|---|---|
| Reads | `state["menu_items"]`, `state["menu"]` (was: `_load_menu()`). |
| Writes | `order_summary` (unchanged), `order_id` (**new**), one `AIMessage` (unchanged shape, one added line). |
| Empty cart | No order written, `order_id` stays `None`, existing "nothing to summarize" message unchanged (FR-011). |
| Write failure | `OrderStoreError` propagates; the node returns nothing, so no success message and no `order_id` reach the state (FR-012). |

Order of operations matters: price the cart, write the order, *then* render — so the rendered
message can carry the ID and can never claim success for a write that failed.

**Rendered message** gains a final line after the total:

```text
Here's your order:
- Kung Pao Chicken x2 @ $12.95 each = $25.90
- Hot and Sour Soup x1 @ $5.50 each = $5.50

Total: $31.40
Order ID: K7QP-3M9X
```

`render_order_summary(summary, order_id=None)` gains an optional second parameter; called without
it the output is byte-identical to today's, so existing render tests hold.

---

## `ticket_gen_node` — new field

`order_ticket` gains `order_id`, copied off the state:

```python
{"order_id": str | None, "items": {...}, "lines": [...], "total": float | None}
```

Still a pure copy — nothing is recomputed (the existing "copies without recomputing" regression
test continues to hold).

---

## CLI

### `--init-db`

```text
customer-support-fde --init-db
```

Creates and seeds the database at `database_path()`, prints `Initialized <path> with N menu items.`
to stdout, exits `0`. Exits `1` with an `Error:` line on stderr if the path is unwritable. Takes no
query and starts no conversation; it is checked before the query is read.

### Conversation run

Unchanged invocation. Two output changes:

- **Human output**: the rendered summary already printed on confirmation now ends with its
  `Order ID:` line.
- **`--json` output**: gains `"order_id"` alongside `"order_summary"`, both present only when
  `order_confirmed` is true.

```json
{"destination": "order_support", "query": "...", "order_summary": {...}, "order_id": "K7QP3M9X"}
```

### Initial state

`cli.py`'s initial state dict gains `"menu": db.load_menu()` and `"order_id": None`. The
`db.load_menu()` call sits inside the existing `try` block so a `MenuStoreError` prints as
`Error: ...` on stderr with exit code 1, before any model is contacted.

### Environment

`CUSTOMER_SUPPORT_DB` — optional path to the database file; defaults to `customer_support.db` in
the working directory. Added to `.env.example`; `*.db` added to `.gitignore`.

---

## Breaking changes (Constitution Principle IV)

1. A database must exist before any conversation runs — `--init-db` is a new required setup step.
2. `SupportState` gains two keys, `menu` and `order_id`, and **both must be supplied by any caller
   building an initial state by hand** (`cli.py` and the integration tests).
3. `menu_tools._load_menu()` is removed. Every test that patched it must switch to putting `menu`
   on the state.
4. `get_menu` / `get_menu_item` gain an injected parameter (Python signature only — the LLM-facing
   schema is unchanged).
5. `order_ticket` gains `order_id`.

Node trajectories and `graph.py` are **not** affected.

Pre-1.0 package (`0.1.0`), so this lands as a MINOR bump with the above stated explicitly in the PR
description.
