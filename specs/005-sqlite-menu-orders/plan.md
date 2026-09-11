# Implementation Plan: SQLite Menu and Order Records

**Branch**: `json-to-sqlite` | **Date**: 2026-09-11 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-sqlite-menu-orders/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Move the menu out of the bundled `menu/menu.json` and into a SQLite database that also becomes the
system of record for confirmed orders. A new `customer_support_fde/db.py` module owns every SQLite
call; nothing else in the project imports `sqlite3`.

Two structural moves carry the feature:

1. **The menu is seeded into the initial graph state.** `cli.py` calls `db.load_menu()` once while
   building the input dict for `graph.invoke()`, and every menu tool, both cart tools, and
   `cart_summary_node` read `state["menu"]` instead of calling `_load_menu()`. The initial state is
   built exactly once per run — resumes go through `Command(resume=...)`, which continues from the
   checkpoint and never re-applies the input — and because state is checkpointed, the snapshot
   survives `await_customer`'s interrupt. That is the US3 guarantee, and the existing code already
   proves the mechanism: `menu_items` is seeded the same way and the cart accumulates correctly
   across interrupts today. **`graph.py` does not change.**
2. **`cart_summary_node` writes the order.** After pricing the cart and before rendering, it calls
   `db.record_order(summary)`, which inserts the order header and all its lines in one transaction
   and returns a short, confusion-free ID (`K7QP-3M9X`) the customer can read back to the refund
   agent later. That ID goes onto the state as `order_id`, into the rendered summary, and into
   `order_ticket`.

The migration is unusually cheap because the menu's in-memory shape does not change: `load_menu()`
returns the same `{"name", "price", "ingredients"}` dicts the JSON loader returned, so
`resolve_menu_item`, `price_for_item`, and every renderer are untouched — FR-004 (customer-visible
matching behavior unchanged) costs nothing. `menu.json` survives as seed data read only by the new
`--init-db` CLI flag.

No new third-party dependency: `sqlite3` is stdlib, which is what the constitution's Technology
Constraints require.

**Breaking changes** (called out per Constitution Principle IV, detailed in
[contracts/graph-and-cli.md](./contracts/graph-and-cli.md)): a database must now be initialized
before any conversation runs; `menu_tools._load_menu()` is deleted; `SupportState` gains `menu` and
`order_id`, both of which callers building an initial state by hand must now supply; `get_menu`/
`get_menu_item` gain an injected state parameter (Python signature only — the LLM-facing schema is
unchanged); and `order_ticket` gains `order_id`. Node trajectories are **unaffected**.

## Technical Context

**Language/Version**: Python 3.14 (per `pyproject.toml` `requires-python`), unchanged from 001–004.

**Primary Dependencies**: stdlib `sqlite3` (3.53.1 in this environment), `json`, `secrets`, `datetime`.
`langgraph.prebuilt.InjectedState` for the tool signature change — already in use by `cart_tools.py`.
No LangGraph wiring changes at all. **No new third-party dependency.**

**Storage**: SQLite file, path from `CUSTOMER_SUPPORT_DB` (already loaded through the project's
existing `dotenv` call), defaulting to `customer_support.db` in the working directory. Three tables
— `menu_items`, `orders`, `order_lines` — per
[contracts/sqlite-schema.sql](./contracts/sqlite-schema.sql). This is the first feature in the
project with any persistence; 001–004 were entirely in-memory.

**Testing**: `pytest`. One new file — `tests/unit/test_db.py` — exercises the db module against real
temporary databases on `tmp_path` (file-backed, because SC-005 requires proving an order survives a
restart). `test_menu_tools.py`, `test_cart_tools.py`, `test_cart_summary_and_ticket_nodes.py`, and
both trajectory suites are updated, and every one of them gets *smaller*: the
`monkeypatch.setattr(..., "_load_menu", ...)` patches are replaced by a `menu` key in the state
fixture. Trajectory assertions are untouched, since no graph node is added.

**Target Platform**: Server-side Python library invoked through the existing `customer-support-fde`
CLI entry point — unchanged from 001–004. SQLite is embedded, so no service to run.

**Project Type**: Single project — same `src/customer_support_fde/` package. One new top-level
module (`db.py`), no new node module, no new subpackages.

**Performance Goals**: None stated. One `SELECT` over six rows per run and one small transaction per
confirmed order; the file opens in microseconds. No target is introduced.

**Constraints**: The menu MUST be read exactly once per run and that snapshot used for every lookup
and price in the run (FR-002, SC-007) — which rules out both per-tool-call queries and the existing
process-lifetime `lru_cache`. A run against a missing or unseeded database MUST abort loudly rather
than proceed with an empty menu (FR-003). An order MUST be written whole or not at all, and a
failed write MUST NOT produce a success message or an `order_id` (FR-012). Recorded orders MUST NOT
follow later menu changes (FR-010) — which is why `order_lines.name` deliberately carries no
foreign key to `menu_items`. Prices are stored as `REAL` so every value in `menu.json` round-trips
bit-identically and existing money arithmetic is unchanged (FR-013). The order ID MUST be short and
unambiguous enough for a customer to speak or retype to the refund agent, and MUST NOT be sequential
or predictable (FR-014, FR-015) — the ID is the only evidence a customer owns the order they are
asking to refund on an unauthenticated conversational surface.

**Scale/Scope**: One new module (`db.py`, 7 public functions); two new `SupportState` fields;
signature edits to four tools; `cart_summary_node` gains a write and an ID; `ticket_gen_node` gains
one copied field; `cli.py` gains an `--init-db` flag, a menu load in its initial state, and two
output fields; `graph.py` unchanged. Six dishes, single restaurant, single database file.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Test-First (NON-NEGOTIABLE)**: PASS (planned) — failing tests land before implementation, in
  this order: the full contract-test table in [contracts/db-module.md](./contracts/db-module.md)
  (init/seed/idempotence, load shape, missing-file and missing-table errors, empty store, order
  round-trip, ID uniqueness, ID alphabet and non-sequentiality, forgiving lookup of a mistyped ID,
  collision retry, atomic rollback, survival across reconnect, immunity to later menu
  edits, empty-lines rejection); then the migration of the existing menu-tool, cart-tool,
  cart-summary, and ticket suites off `_load_menu` and onto `state["menu"]`; then `order_id` cases on
  `cart_summary_node` and `ticket_gen_node`; then the trajectory suites' state-seeding update. Every
  case carries the required one-line `(base)`/`(edge)`/`(error)`/`(regression)` comment.
- **II. Library-First & CLI Interface**: PASS (planned) — `db.py` is a standalone importable module
  of plain functions over ordinary Python values, with no LangGraph or LangChain types anywhere in
  its surface; the CLI and the tools are thin consumers of it. The one operation a human must invoke
  directly — creating and seeding the database — is exposed as `customer-support-fde --init-db`,
  printing a human-readable result to stdout and errors to stderr. The existing `--json` mode carries
  the new `order_id` so the feature's full payload is scriptable, not just readable.
- **III. Simplicity (YAGNI)**: PASS (planned) — stdlib `sqlite3` with hand-written SQL, no ORM, no
  migration framework, no connection pool, no async. Ingredients are a JSON text column rather than a
  junction table because nothing queries an individual ingredient; a short-lived connection per
  operation rather than a shared one because SQLite opens in microseconds and a connection can be
  neither checkpointed nor safely shared across LangGraph's threads. Order amendment, cancellation,
  refund-by-order-ID lookup, and multi-restaurant menus are out of scope per the spec's Assumptions
  and are not designed for. The menu is loaded by the caller into the initial state rather than by a
  dedicated entry node, so this feature adds **no** graph node, no edge, and no change to `graph.py`.
  - *Justification for the new `menu` state field*: the alternatives are strictly worse, not simpler
    — a process-level cache goes stale across runs (SC-002), and a per-tool-call query lets one
    conversation straddle two price regimes (SC-007). One checkpointed field of six small rows makes
    the run-consistency guarantee true by construction, and it rides the mechanism `menu_items`
    already uses.
  - *A `load_menu` entry node was considered and rejected* (see [research.md](./research.md) §1). It
    would guarantee no caller can forget to load the menu and would put `MenuStoreError` on the
    LangSmith trace — but with exactly one caller in the project, that is the hypothetical-need
    abstraction this principle forbids, and it would cost a module, a test file, an entry-point
    change, and a trajectory edit in every integration assertion.
  - *Justification for a new `db.py` module rather than inlining SQL*: confining `sqlite3` to one
    module is what keeps every other module free of storage concerns and testable without a database
    — the same separation `menu_tools.py` already has between pure matching logic and loading.
- **IV. Observability & Versioning**: PASS with explicit breaking-change callout — no new LLM call
  site and no new node are added, so existing LangSmith tracing covers `cart_summary_node`'s state
  updates with no new instrumentation, and `OrderStoreError` propagates through the graph so a failed
  order write appears on the trace rather than being swallowed. `MenuStoreError` is raised before the
  graph starts and is therefore a stderr/exit-code concern, not a trace concern — correct for a
  startup configuration failure. The five backward-incompatible edges listed in the Summary and
  detailed in [contracts/graph-and-cli.md](./contracts/graph-and-cli.md) must be repeated in the PR
  description. The package is pre-1.0 (`0.1.0`), so this lands as a MINOR bump with the breaking
  changes stated explicitly rather than a MAJOR bump.

No violations requiring justification — Complexity Tracking table omitted.

**Post-Phase-1 re-check**: Confirmed against the finished design
([research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/)). Phase 1
added no further dependency, no further state field beyond the two gated above, no graph node, and no
new LLM call site. Two design choices were made after the gate and are re-checked here: `get_order()`
is included in the db module although the graph never calls it — justified because SC-004 and SC-005
cannot be verified without a read-back path, so it is test-required, not speculative; and
`render_order_summary` gains an *optional* `order_id` parameter so that calling it without one
produces byte-identical output to today, keeping the existing render tests valid. All four gates
still PASS.

**Revisions (post-review)**:

1. An earlier draft loaded the menu via a dedicated `load_menu` entry node. That was replaced with
   caller-seeded initial state under Principle III — see [research.md](./research.md) §1 for the full
   comparison. The change removes one module, one test file, the entry-point edit, and every
   trajectory-assertion update, and makes a missing database fail before any LLM call rather than
   inside a checkpointed run.
2. An earlier draft used `uuid.uuid4().hex` for the order ID. The spec gained FR-014 and FR-015 once
   it was established that customers will speak or retype this ID to the refund agent, and the format
   changed to an 8-character code over a confusion-free alphabet — see
   [research.md](./research.md) §4. This adds two small public functions (`format_order_id`,
   `normalize_order_id`) and a bounded collision retry inside `record_order`. Re-checked against
   Principle III: the two functions are not speculative — they are what makes the chosen alphabet
   mean anything, and `get_order` routes through `normalize_order_id` from day one, so the tests for
   SC-008 exercise them. The refund agent's own lookup remains out of scope.

## Project Structure

### Documentation (this feature)

```text
specs/005-sqlite-menu-orders/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   ├── sqlite-schema.sql    # DDL + seed upsert
│   ├── db-module.md         # customer_support_fde.db public API + contract tests
│   └── graph-and-cli.md     # initial-state seeding, tool signatures, CLI, breaking changes
├── checklists/
│   └── requirements.md  # /speckit-specify output
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/customer_support_fde/
├── db.py                        # NEW: the only module importing sqlite3.
│                                #   database_path(), init_database(), load_menu(),
│                                #   record_order(), get_order(), format_order_id(),
│                                #   normalize_order_id(), MenuStoreError, OrderStoreError
├── state.py                     # SupportState gains menu: list[MenuItem] and order_id: str | None
├── cli.py                       # --init-db flag; initial state gains menu=db.load_menu() and
│                                #   order_id=None; --json output gains order_id
├── menu/
│   └── menu.json                # UNCHANGED content; now seed data, read only by --init-db
├── nodes/
│   ├── cart_summary_node.py     # prices from state["menu"]; calls db.record_order();
│   │                            #   writes order_id; render_order_summary() gains optional order_id
│   └── ticket_gen_node.py       # order_ticket gains order_id
└── tools/
    ├── menu_tools.py            # _load_menu() DELETED; get_menu/get_menu_item take InjectedState
    └── cart_tools.py            # two _load_menu() calls -> state["menu"]; import dropped

tests/
├── unit/
│   ├── test_db.py                             # NEW: contract tests against tmp_path databases
│   ├── test_menu_tools.py                     # real-menu.json case -> DB-backed; tools take state
│   ├── test_cart_tools.py                     # _load_menu patches -> menu on state fixture
│   └── test_cart_summary_and_ticket_nodes.py  # menu on state; order_id on node output and ticket
└── integration/
    ├── test_order_support_trajectory.py       # _mock_menu() -> menu seeded in initial_state;
    │                                          #   trajectory assertions UNCHANGED
    └── test_router_trajectory.py              # menu seeded in initial_state; trajectories unchanged

.env.example                     # documents CUSTOMER_SUPPORT_DB
.gitignore                       # *.db
```

**Structure Decision**: Single project (Option 1), unchanged from 001–004. `db.py` sits at the
package top level rather than in a `storage/` subpackage — it is one module with one responsibility,
and a subpackage holding a single file is the organizational grouping Principle II explicitly
forbids. No new module under `nodes/`, and `graph.py` is not touched: this feature changes what
existing nodes read and write, not the shape of the graph.

## Complexity Tracking

*No Constitution Check violations — table intentionally omitted.*
