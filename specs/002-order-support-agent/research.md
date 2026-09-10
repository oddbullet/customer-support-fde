# Phase 0 Research: Order/Support Agent with Menu Tools

All items below were unresolved technical decisions (not spec-level ambiguities — those were already closed in `/speckit-clarify`). Each follows Decision / Rationale / Alternatives considered.

**Revision note (2026-09-10, post-plan design review)**: §2 and §4 originally specified a single structured-output classification call (`OrderIntentDecision`) per turn, with deterministic Python dispatch and fixed reply templates. That design couldn't cleanly express a customer asking for multiple things in one message (e.g. "add two spring rolls and a kung pao chicken," or "what's in X, and also recommend something spicy"), and fixed templates can't produce a genuine recommendation. Both are replaced below with a native tool-calling loop (`ToolNode` + `InjectedState` + `Command`), verified against the installed `langgraph==1.2.11`. §9's testing strategy is updated accordingly, and the previously-considered LLM-as-judge evaluation layer is dropped from this feature's scope.

## 1. Package reorganization into `nodes/`, `tools/`, `menu/`

**Decision**: Move the existing agent-node modules (`router_agent.py`, `clarify_intent.py`, and the two placeholder functions currently in `downstream_agents.py`) into a new `src/customer_support_fde/nodes/` subpackage, one module per node, and add the new order-flow nodes there too (`order_support_agent.py` — now containing the tool-calling loop's node functions, see §2/§4 — `confirm_node.py`, `ticket_gen_node.py`). Create `src/customer_support_fde/tools/` for tool functions (`menu_tools.py`, `cart_tools.py`) and `src/customer_support_fde/menu/` holding only `menu.json`. `state.py`, `graph.py`, and `cli.py` stay at the package root since they aren't agent logic, tool implementations, or menu data. Every import of a moved module (in `graph.py`, `cli.py`, and the existing 001 tests) is updated to the new path; no behavior changes for `router_agent`, `clarify_intent`, or `refund_agent`.

**Rationale**: Directly implements FR-010/FR-011/FR-012. Splitting `downstream_agents.py` into one module per node keeps `refund_agent` (still a placeholder, out of scope here) untouched while `order_support_agent.py` grows real logic in this feature.

**Alternatives considered**: Leaving all node modules flat at the package root and only adding `tools/`/`menu/` — rejected because it wouldn't satisfy FR-010 once the new order-flow nodes are added. A deeper split (e.g., `nodes/order/`) — rejected as unnecessary nesting (Principle III).

## 2. Native tool-calling loop for `order_support_agent` (revised)

**Decision**: Build the order-support conversation as a small tool-calling loop of two graph nodes, both registered directly in the main `StateGraph` (no separate agent subgraph, no custom `state_schema` — they read/write `SupportState` directly, so there's no state-isolation boundary to manage):

- **`call_model`**: calls `ChatOpenAI(...).bind_tools([get_menu, get_menu_item, add_items_to_cart, mark_order_confirmed])` against the turn's message list (see §4 for how that list is built/reset) and appends the resulting `AIMessage`.
- **`order_tools`**: `langgraph.prebuilt.ToolNode([get_menu, get_menu_item, add_items_to_cart, mark_order_confirmed])`, wired with `messages_key="messages"` (its default) against `SupportState.messages`.

The conditional edge between them is `langgraph.prebuilt.tools_condition` (verified present in the installed `langgraph==1.2.11`, `langgraph.prebuilt.tools_condition`) — no custom routing function needed: it returns `"tools"` when the last `AIMessage` has `tool_calls`, `"__end__"` otherwise. We remap `"__end__"` to a third node, `await_customer` (see §4), instead of the graph actually ending there.

Tools that need to read or write the cart use `langgraph.prebuilt.InjectedState` to receive `SupportState` (or just the `menu_items` field) as a function argument the LLM never sees or supplies, and return a `langgraph.types.Command(update={...})` to write `menu_items`/`order_confirmed` directly — confirmed as a supported `ToolNode` return type (`ToolNode` explicitly documents and implements handling for tools that "return `Command(...)` or a mixed list with regular tool outputs"). `get_menu`/`get_menu_item` need no injected state (the menu is static, cached module data per §6) and return plain strings/structures as their `ToolMessage` content.

**Rationale**: This replaces a hand-written classify-then-dispatch call *and* a hand-written tool-execution loop with two verified library primitives (`ToolNode`, `tools_condition`) wired directly against our own state — no adapter/translation layer, no separate agent-internal schema to reconcile with `SupportState` (Constitution Principle III: don't hand-roll what a maintained primitive already provides). It also directly enables recommendation-style questions ("what do you recommend?"): the model reasons over `get_menu`'s actual tool result and composes its own answer, which a fixed template could never do.

**Alternatives considered**: The original single structured-output `OrderIntentDecision` call + deterministic dispatch (see revision note above) — rejected because it can't express multi-intent/multi-item messages and can't produce a genuine recommendation, only a menu dump. `langgraph.prebuilt.create_react_agent` (the fully-prebuilt wrapper around this same loop) — rejected in favor of assembling `call_model`/`order_tools` directly in our own graph: `create_react_agent` draws a boundary between its own internal graph and the one it's embedded in, requiring a custom `state_schema` and relying on LangGraph's shared-key subgraph-embedding behavior to expose `menu_items` across that boundary — assembling the two nodes ourselves, using `SupportState` throughout, removes that boundary (and the question of whether it's configured correctly) entirely, at no real cost in code volume since `create_react_agent` is built from the same two primitives.

## 3. Fuzzy name matching and tie detection (unchanged)

**Decision**: `resolve_menu_item(name: str, menu: list[MenuItem]) -> MenuMatch` in `tools/menu_tools.py`, used by both the `get_menu_item` tool and `add_items_to_cart`. Scores every menu item's name against the query using stdlib `difflib.SequenceMatcher(None, query.casefold(), item_name.casefold()).ratio()`, with a fixed `1.0` score when the query is a case-insensitive substring of the item name. Candidates at or above a `0.6` cutoff; `found` (one top-scoring candidate), `tie` (two-plus within a small epsilon of the top score), or `not_found` (none meet the cutoff).

**Rationale**: `difflib` is stdlib — no new dependency. A single shared resolver keeps "reasonably close match" (FR-001, FR-005) and "equally well" (FR-005a) defined in exactly one place, independent of whether the caller is a lookup or a cart add.

**Alternatives considered**: A third-party fuzzy-matching library — rejected as unjustified for a 5-item menu. Exact-substring-only matching — rejected, wouldn't satisfy the "minor typos" clarification.

## 4. Multi-turn ordering conversation and the confirm hand-off (revised)

**Decision**: Two layers of looping, kept structurally separate:

- **Inner loop, within one customer turn**: `call_model ⇄ order_tools`, driven by `tools_condition`, continues until the model produces a final `AIMessage` with no `tool_calls`. `add_items_to_cart` and `mark_order_confirmed` update `SupportState.menu_items`/`order_confirmed` via `Command` as they execute, so by the time the inner loop ends, `SupportState` already reflects every change made during that turn — no separate "flush" step is needed.
- **Outer loop, across turns**: a new node, `await_customer`, is reached when the inner loop ends (`tools_condition` → `"__end__"` remapped to `await_customer`). It checks `order_confirmed`: if `True`, it does **not** call `interrupt()` — the graph proceeds to `confirm_node` (routed by the same conditional-edge pattern used elsewhere in this codebase, reading `state["order_confirmed"]`). If `False`, it calls `interrupt()` with the final `AIMessage`'s content, and on resume resets `SupportState.messages` to a fresh list (system prompt + a brief cart summary + the newly resumed customer message — see below) before looping back to `call_model`.

`SupportState.messages` is **not** carried forward across turns — it is reset at the start of each new turn (either the very first one, seeded by `router_agent`'s original query, or after each `interrupt()` resume in `await_customer`). This bounds the LLM's context to one turn's tool-calling exchange regardless of how long the overall conversation runs, rather than growing with every turn. `menu_items`/`order_confirmed` are the only state that persists across turns — and they already did, structurally, before this revision.

A fuzzy-match tie (FR-005a) needs no special-casing here: `add_items_to_cart` reports it as part of its tool result, and the model's next turn — still within the same inner loop, since a tie doesn't stop the model from responding — naturally turns it into a disambiguation question as part of composing its reply.

**Rationale**: Separating "loop until this turn's tool calls are resolved" from "loop until the customer is done" keeps each loop's termination condition simple and independently reasoned about. Resetting `messages` per turn directly answers the context-growth concern raised during design review, using state that's already structurally separate from `menu_items`/`order_confirmed`.

**Alternatives considered**: Persisting the full multi-turn transcript in `messages` — rejected; unbounded growth over a long conversation for no benefit, since the cart itself (not the transcript) is what needs to survive across turns. A dedicated node/state field for the tie-disambiguation case — rejected as unneeded; it falls out of the existing tool-result-to-reply flow for free.

## 5. Cart representation and the batched add tool (revised)

**Decision**: `menu_items: dict[str, int]`, keyed by canonical menu item name. The cart-mutating tool is `add_items_to_cart(names: list[str], state: Annotated[SupportState, InjectedState]) -> Command`, **not** a single-item `add_item_to_cart` — it resolves each name in the list against the menu (via `resolve_menu_item`) and applies all of them to one derived copy of `menu_items` sequentially, within that one function call, before returning a single `Command(update={"menu_items": ..., "messages": [...]})`. `mark_order_confirmed(state: Annotated[SupportState, InjectedState]) -> Command` sets `order_confirmed = True` only when `menu_items` is non-empty.

**Rationale**: A single tool call processing a whole batch internally (plain sequential Python, not separate LangGraph steps) sidesteps any question of whether two sibling tool calls in the same turn would see each other's state updates — there's only ever one `Command` write to `menu_items` per model turn that actually adds items, regardless of how many items the customer mentioned in one message. This directly solves the multi-item-in-one-message case raised during design review, without requiring a custom state-merge reducer.

**Alternatives considered**: A singular `add_item_to_cart` tool, relying on the model emitting multiple tool calls for multiple items in one turn — rejected: correctness would then depend on exactly how/when `ToolNode` applies multiple `Command` updates to the same state key within one step (a reducer would be needed to merge them safely), which is more moving parts than a tool that just loops internally. Storing full `MenuItem` copies per cart entry — rejected as redundant with the menu, which is cheap to re-read.

## 6. Menu data storage and loading (unchanged)

**Decision**: `src/customer_support_fde/menu/menu.json` — a JSON array of objects (`name`, `price`, `ingredients`). Loaded once via `importlib.resources` and cached at module level in `tools/menu_tools.py`.

**Rationale**: `importlib.resources` (stdlib) resolves correctly whether run from source or installed. Caching avoids re-parsing static content on every call.

**Alternatives considered**: A Python literal instead of JSON — rejected, spec asks for JSON. Reloading from disk every call — unnecessary I/O (Principle III).

## 7. Dummy `confirm_node` and `ticket_gen_node` (unchanged in behavior; trigger renamed)

**Decision**: `confirm_node(state) -> SupportState` is a pure pass-through, reached once `mark_order_confirmed` has set `order_confirmed = True` (previously described as a `confirm_done` classification action — now a tool call). `ticket_gen_node(state) -> SupportState` sets `order_ticket = {"items": dict(state["menu_items"])}`.

**Rationale**: Satisfies FR-007/FR-008 unchanged from the original design — only the mechanism that flips `order_confirmed` changed (a tool's `Command`, not a classifier branch).

**Alternatives considered**: See original research — unchanged; merging the two nodes was rejected for the same reasons as before.

## 8. CLI interrupt-echo fix (unchanged)

**Decision**: `cli.py`'s resume loop currently `print(QUESTION)` unconditionally; change it to print the real payload from `result["__interrupt__"]`.

**Rationale**: `await_customer`'s `interrupt()` calls carry dynamic, per-turn text (menu answers, recommendations, disambiguation questions) — a hardcoded question would break the CLI experience for every order-flow turn.

**Alternatives considered**: Unchanged from the original research — none of the alternatives considered there depend on the classify-then-dispatch design that was revised.

## 9. Testing strategy (revised)

**Decision**: Testing splits into what's deterministic and what isn't, and the feature explicitly does **not** attempt automated testing of LLM-composed reply *wording* for this phase (the previously-considered LLM-as-judge evaluation layer is dropped from scope — reply quality is validated manually via `quickstart.md` only):

- **Pure-function unit tests** (`test_menu_tools.py`, `test_cart_tools.py`): `resolve_menu_item`/`get_menu`/`get_menu_item` found/tie/not-found cases (no LLM, no graph); `add_items_to_cart` and `mark_order_confirmed` called directly as plain Python functions with a hand-constructed `SupportState`-shaped dict (bypassing the LLM/graph entirely, since `InjectedState` just means "this parameter receives the state dict when called via `ToolNode`" — nothing prevents calling the underlying function directly with an explicit state argument in a test), asserting the returned `Command.update` contains the correct `menu_items`/`order_confirmed` values, including the batched-multi-item and tie/not-found-leaves-cart-unchanged cases.
- **Loop/trajectory tests** (`test_order_support_trajectory.py`): the LLM boundary is faked to return canned `AIMessage`s with specific `tool_calls`; real `ToolNode` executes against the real tool functions and real (test) `menu.json`-equivalent sample menu; assertions are on resulting graph state (`menu_items`, `order_confirmed`, `order_ticket`) and on the node-path trajectory (`call_model`/`order_tools` cycle counts, eventual `confirm_node`/`ticket_gen_node`) — never on the exact text of a model-composed reply.
- **Confirm/ticket node tests** (`test_confirm_and_ticket_nodes.py`): unchanged from the original research — pure pass-through / placeholder-shape assertions.

**Rationale**: Keeps every automated assertion deterministic and fast (Constitution Principle I is satisfied by testing what the code actually guarantees — tool execution and state mutation — rather than by asserting on non-deterministic prose, which would make tests flaky regardless of whether an LLM-as-judge scored them). Dropping the judge-eval layer for now is a scope decision, not a technical dead-end — it can be added later without touching this test layer.

**Alternatives considered**: LLM-as-judge scoring of composed replies — dropped per explicit design-review decision; revisit if reply-quality regressions become a real problem in practice. Exact-string reply assertions (the original design's approach) — no longer applicable once replies are LLM-composed rather than template-generated.

## Outcome

All unknowns from Technical Context are resolved, including verification of the `ToolNode`/`InjectedState`/`Command`/`tools_condition` API surface against the installed `langgraph==1.2.11`. No `NEEDS CLARIFICATION` markers remain.
