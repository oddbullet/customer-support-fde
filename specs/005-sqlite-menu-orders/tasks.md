---

description: "Task list for SQLite menu and order records"
---

# Tasks: SQLite Menu and Order Records

**Input**: Design documents from `/specs/005-sqlite-menu-orders/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: **MANDATORY, not optional.** Constitution Principle I (Test-First) is NON-NEGOTIABLE: every
test is written and watched to fail before the implementation it covers. Every test case carries a
one-line comment above its definition stating what it verifies and tagging its category —
`(base)` / `(edge)` / `(error)` / `(regression)`.

**Organization**: Tasks are grouped by user story so each can be implemented and tested independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Exact file paths are included in every task

## Path Conventions

Single project: `src/customer_support_fde/` and `tests/` at repository root, per
[plan.md](./plan.md) Project Structure.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Keep the new database file and its configuration out of version control

- [X] T001 [P] Add `*.db` to `.gitignore` so local order data is never committed
- [X] T002 [P] Add `CUSTOMER_SUPPORT_DB=` with a comment naming the default (`customer_support.db` in the working directory) to `.env.example`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Create `db.py`, the schema, and the `--init-db` command. Both P1 stories need a database
that exists and is seeded before they can do anything.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

### Tests (write first, watch fail)

- [X] T003 Create `tests/unit/test_db.py` with failing tests for `database_path()` (returns `CUSTOMER_SUPPORT_DB` when set and non-empty; falls back to `customer_support.db` otherwise; read at call time, not import time) and for `init_database()` (creates all three tables on a fresh `tmp_path`; seeds every dish from `menu.json` and returns the count; re-running leaves the same dish count with no duplicates; updates price and ingredients of an existing dish but deletes nothing)

### Implementation

- [X] T004 Create `src/customer_support_fde/db.py` with `MenuStoreError(RuntimeError)`, `OrderStoreError(RuntimeError)`, `DEFAULT_DB_FILENAME = "customer_support.db"`, `database_path()`, and an internal `_connect(path, *, create=False)` that sets `PRAGMA foreign_keys = ON` and raises `MenuStoreError` naming the path and the `--init-db` remedy when the file is absent and `create` is `False`
- [X] T005 Add the schema DDL from `specs/005-sqlite-menu-orders/contracts/sqlite-schema.sql` as a module constant in `src/customer_support_fde/db.py` — `menu_items(name TEXT PRIMARY KEY, price REAL NOT NULL CHECK (price > 0), ingredients TEXT NOT NULL)`, `orders(id TEXT PRIMARY KEY, total REAL NOT NULL CHECK (total > 0), created_at TEXT NOT NULL)`, `order_lines(order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE, name TEXT NOT NULL, quantity INTEGER NOT NULL CHECK (quantity > 0), unit_price REAL NOT NULL CHECK (unit_price > 0), line_total REAL NOT NULL CHECK (line_total > 0), PRIMARY KEY (order_id, name))` — all as `CREATE TABLE IF NOT EXISTS`
- [X] T006 Implement `init_database(path=None) -> int` in `src/customer_support_fde/db.py`: create the file, apply the DDL, read `customer_support_fde/menu/menu.json` via `importlib.resources`, upsert each dish with `ON CONFLICT (name) DO UPDATE SET price = excluded.price, ingredients = excluded.ingredients` storing `ingredients` as a JSON array string, and return the number of dishes seeded. This is the only code path in the project that reads `menu.json`
- [X] T007 Add `--init-db` to `src/customer_support_fde/cli.py`: an argparse flag checked before the query is read, which calls `init_database()`, prints `Initialized <path> with N menu items.` to stdout and returns `0`, or prints `Error: {exc}` to stderr and returns `1` if the path is unwritable

**Checkpoint**: `uv run customer-support-fde --init-db` creates and seeds the database. User story work can begin.

---

## Phase 3: User Story 1 - Menu answers come from the menu database (Priority: P1) 🎯 MVP

**Goal**: Every menu answer, cart addition, and price comes from SQLite instead of the bundled JSON
file, so staff can change a price or ingredient list and have the next conversation reflect it with
no code change and no release.

**Independent Test**: Seed the database, ask the agent for the full menu and for one dish by name,
and confirm the replies match the `menu_items` table. Change a price in the database, start a new
conversation, and confirm the new price is quoted. Delivers value with US2 and US3 unbuilt.

### Tests for User Story 1 (write first, watch fail)

- [X] T008 [P] [US1] Add failing `load_menu()` tests to `tests/unit/test_db.py`: returns dishes with exactly the names, prices, and ingredient lists in `menu.json` and in stable `name` order (base); a price edited directly in the database is reflected by the next call (base); a missing file raises `MenuStoreError` naming the path (error); a file with no `menu_items` table raises `MenuStoreError` (error); a row whose `ingredients` JSON will not parse raises `MenuStoreError` rather than returning a partial menu (error); a seeded-then-emptied table returns `[]` (edge)
- [X] T009 [P] [US1] Update `tests/unit/test_menu_tools.py`: replace `test_real_menu_json_has_at_least_five_well_formed_items` with a database-backed equivalent built on `tmp_path`, and drop the `_load_menu` import. Add cases that `get_menu` and `get_menu_item` read `state["menu"]` (base) and that an empty `state["menu"]` renders the existing "no items available" text (edge). Leave every `resolve_menu_item` and `price_for_item` case untouched — they prove FR-004
- [X] T010 [P] [US1] Update `tests/unit/test_cart_tools.py`: delete the `setup_function` / `monkeypatch` patching of `cart_tools._load_menu` and seed `"menu": SAMPLE_MENU` on the state dict each test passes instead. Assertions stay as they are

### Implementation for User Story 1

- [X] T011 [US1] Implement `load_menu(path=None) -> list[MenuItem]` in `src/customer_support_fde/db.py`: select `name, price, ingredients` from `menu_items` ordered by `name`, deserialize `ingredients` from JSON into a `list[str]`, and return `{"name": str, "price": float, "ingredients": list[str]}` dicts — the exact shape the JSON loader returned. Wrap `sqlite3.Error` and `json.JSONDecodeError` in `MenuStoreError`
- [X] T012 [US1] Add `menu: list[MenuItem]` to `SupportState` in `src/customer_support_fde/state.py`, importing `MenuItem` from `customer_support_fde.tools.menu_tools`
- [X] T013 [US1] In `src/customer_support_fde/tools/menu_tools.py`: delete `_load_menu()` and the now-unused `json`, `importlib.resources`, and `lru_cache` imports; give `get_menu` and `get_menu_item` an `Annotated[SupportState, InjectedState]` parameter and read `state["menu"]`. Leave the docstrings, `resolve_menu_item`, `price_for_item`, `_score`, `_render_item`, `_render_menu`, and `_render_match` unchanged — `InjectedState` is stripped from the model-facing schema, so the LLM sees the same two tools
- [X] T014 [US1] In `src/customer_support_fde/tools/cart_tools.py`: replace both `_load_menu()` calls in `add_items_to_cart` and `remove_items_from_cart` with `state["menu"]` and drop the `_load_menu` import
- [X] T015 [US1] In `src/customer_support_fde/cli.py`: add `"menu": db.load_menu()` to the initial state dict, placed inside the existing `try` block so a `MenuStoreError` prints as `Error: ...` on stderr with exit code 1 before any model is contacted
- [X] T016 [P] [US1] Update `tests/integration/test_order_support_trajectory.py`: delete `_mock_menu()` and its two `monkeypatch.setattr` calls, and add `"menu": SAMPLE_MENU` to each `initial_state` dict. **Leave every expected-trajectory assertion exactly as it is** — no graph node was added
- [X] T017 [P] [US1] Update `tests/integration/test_router_trajectory.py`: add `"menu": SAMPLE_MENU` (or `[]` where the menu is irrelevant) to each `initial_state` dict; trajectory assertions unchanged

**Checkpoint**: Menu answers come from SQLite. A staff price edit shows up in the next conversation. US1 is independently demoable.

---

## Phase 4: User Story 2 - A confirmed order is recorded and given an order ID (Priority: P1)

**Goal**: Confirming an order writes the complete order — dish, quantity, unit price, line total,
order total — into the database and returns a short, confusion-free order ID the customer can read
back to the refund agent later.

**Independent Test**: Run an ordering conversation, confirm, and check that an order ID is returned
with the summary; look the ID up and confirm the stored values match what the customer was shown,
including after a restart and after menu prices change.

### Tests for User Story 2 (write first, watch fail)

- [X] T018 [US2] Add failing order-ID tests to `tests/unit/test_db.py`: every generated ID is 8 characters drawn only from `0123456789ABCDEFGHJKMNPQRSTVWXYZ` and never contains `I`, `L`, `O`, or `U` (base); 1,000 generated IDs are all distinct and show no sequential pattern (base); `format_order_id("K7QP3M9X") == "K7QP-3M9X"` and `normalize_order_id` inverts it exactly (base); `normalize_order_id` folds lowercase, hyphens, surrounding whitespace, and `O`→`0`, `I`→`1`, `L`→`1` (edge)
- [X] T019 [US2] Add failing order read/write tests to `tests/unit/test_db.py`: `record_order` returns an 8-character ID and `get_order` round-trips `name`, `quantity`, `unit_price`, `line_total`, and `total` (base); two calls return different IDs and both orders stay readable (base); a failure partway through leaves no `orders` row and no `order_lines` rows (error); an order written, connection closed, database reopened still reads identically (base); editing `menu_items` after an order does not change that order's stored names or prices (regression); `record_order` with an empty `lines` list raises `ValueError` and writes nothing (error); a forced ID collision is retried onto a fresh ID and the order still saves (error); `get_order` finds an order from its lowercase, hyphenated, and `O`/`I`/`L`-substituted forms (edge) and returns `None` for an unrecognizable string rather than raising (edge)
- [X] T020 [P] [US2] Add failing `order_id` cases to `tests/unit/test_cart_summary_and_ticket_nodes.py`: `cart_summary_node` writes `order_id` and the rendered message ends with a hyphenated `Order ID:` line (base); an empty cart writes no order, leaves `order_id` as `None`, and keeps the existing "nothing to summarize" wording (edge); an `OrderStoreError` from `record_order` propagates and no success `AIMessage` is produced (error); `render_order_summary(summary)` called without an `order_id` is byte-identical to today's output (regression); `ticket_gen_node` copies `order_id` into `order_ticket` (base). Seed `"menu": SAMPLE_MENU` and `"order_id": None` on `_base_state()` and drop the `_load_menu` monkeypatch

### Implementation for User Story 2

- [X] T021 [US2] Add ID handling to `src/customer_support_fde/db.py`: `ID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"`, `ID_LENGTH = 8`, an internal `_new_order_id()` using `secrets.choice` (not `random`), `format_order_id(order_id)` inserting the hyphen mid-code, and `normalize_order_id(raw)` which strips whitespace, uppercases, removes hyphens and spaces, and translates `O`→`0`, `I`→`1`, `L`→`1`. `normalize_order_id` must not validate — an unrecognizable string simply matches no row
- [X] T022 [US2] Implement `record_order(summary, path=None) -> str` in `src/customer_support_fde/db.py`: raise `ValueError` if `summary["lines"]` is empty; otherwise generate an ID and insert the `orders` row (`total` copied from `summary["total"]`, `created_at` as ISO-8601 UTC) plus every `order_lines` row inside one `with conn:` transaction, copying `name`, `quantity`, `unit_price`, and `line_total` verbatim with no recomputation. On a primary-key `IntegrityError` discard the code and retry with a fresh one, up to 5 attempts, then raise `OrderStoreError`; each attempt is its own transaction. Wrap other `sqlite3.Error` in `OrderStoreError`
- [X] T023 [US2] Implement `get_order(order_id, path=None) -> dict | None` in `src/customer_support_fde/db.py`: apply `normalize_order_id` to the argument, join `orders` and `order_lines`, and return `{"order_id", "total", "created_at", "lines"}` with `lines` in the same four-key shape as `order_summary["lines"]`, or `None` when no row matches
- [X] T024 [US2] Add `order_id: str | None` to `SupportState` in `src/customer_support_fde/state.py`
- [X] T025 [US2] Give `render_order_summary(summary, order_id=None)` in `src/customer_support_fde/nodes/cart_summary_node.py` an optional second parameter that appends `Order ID: {format_order_id(order_id)}` after the total line. Called without it the output must be byte-identical to today's
- [X] T026 [US2] Rewrite `cart_summary_node` in `src/customer_support_fde/nodes/cart_summary_node.py` to read the menu from `state["menu"]` instead of `_load_menu()`, then price the cart, then call `db.record_order(summary)`, then render — in that order, so the message can carry the ID and can never claim success for a failed write. Write `order_id` onto the returned state; for an empty cart skip the write entirely and leave `order_id` as `None`
- [X] T027 [US2] Add `order_id` to the ticket built by `ticket_gen_node` in `src/customer_support_fde/nodes/ticket_gen_node.py`, copied off the state alongside the lines and total it already copies — `{"order_id": str | None, "items": {...}, "lines": [...], "total": float | None}`
- [X] T028 [US2] In `src/customer_support_fde/cli.py`: add `"order_id": None` to the initial state dict, and include `order_id` in the `--json` payload alongside `order_summary` when `order_confirmed` is true (canonical unhyphenated form in JSON; the printed human summary carries the hyphenated form)

**Checkpoint**: Confirming an order writes it to the database and hands back a readable ID. US1 and US2 both work.

---

## Phase 5: User Story 3 - One consistent menu for the whole conversation (Priority: P2)

**Goal**: Prove that the menu snapshot taken at the start of a run is the one used for every lookup
and every price in that run, so a mid-conversation staff edit can never change what a customer is
charged after being quoted.

**Note**: The design makes this true by construction once US1 lands — the guarantee rides the same
checkpointed-state mechanism the cart already uses. This phase is therefore mostly verification, and
adds no production code. That is the intended outcome, not a gap.

### Tests for User Story 3 (write first, watch fail)

- [X] T029 [P] [US3] Add a failing test to `tests/integration/test_order_support_trajectory.py` that a price changed in the database mid-conversation does not affect the confirmed order: seed `menu` in the initial state, run the conversation through an interrupt, mutate the underlying `menu_items` row, then confirm — the summary and `order_summary` must use the originally seeded price (regression)
- [X] T030 [P] [US3] Add a failing test to `tests/unit/test_db.py` (or a new `tests/unit/test_cli.py`) asserting `db.load_menu` is called exactly once for a full CLI run that spans at least one interrupt-and-resume cycle, using a counting wrapper around `db.load_menu` (base)

### Implementation for User Story 3

- [X] T031 [US3] Verify no production code change is required: grep `src/customer_support_fde/` for any remaining `load_menu(` call outside `cli.py`, and for any leftover `_load_menu` reference anywhere in `src/` or `tests/`. Both must return nothing. If either does not, the offending call site is reading the database per operation and must be changed to `state["menu"]`

**Checkpoint**: All three stories independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T032 Run the full suite with `uv run pytest` and confirm green, including that every pre-existing `resolve_menu_item`, `price_for_item`, `build_order_summary`, and trajectory assertion still passes unchanged
- [X] T033 Audit every new test case in `tests/unit/test_db.py` for the one-line category comment required by Constitution Principle I — `(base)` / `(edge)` / `(error)` / `(regression)` — directly above each definition and above the outermost `@pytest.mark.parametrize` where present
- [X] T034 Walk all eight scenarios in [quickstart.md](./quickstart.md) end to end against a real database and confirm each expected outcome, including the missing-database failure (scenario 6) aborting before any model call
- [X] T035 Update `CLAUDE.md` to note that `customer-support-fde --init-db` is a required setup step and that the menu now lives in SQLite
- [X] T036 Write the PR description with the five breaking changes from [contracts/graph-and-cli.md](./contracts/graph-and-cli.md), the Principle III justification for the new `menu` state field and `db.py` module, and the MINOR version bump rationale, per Constitution Principle IV and the Development Workflow section

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup — **BLOCKS all user stories** (nothing works without a database)
- **US1 (Phase 3)**: Depends on Foundational
- **US2 (Phase 4)**: Depends on Foundational. Independent of US1 in principle — `record_order` needs no menu — but T026 rewrites `cart_summary_node`, which T011–T014 also touch for the menu read, so **run US1 first** if one person is doing both
- **US3 (Phase 5)**: Depends on US1 (it verifies US1's snapshot guarantee) and on US2 for the confirm-path test in T029
- **Polish (Phase 6)**: Depends on all three stories

### Within Each User Story

- Tests are written and watched to fail before the implementation they cover — non-negotiable
- `db.py` functions before the state field before the tools/nodes before the CLI
- Story complete and checkpointed before moving to the next

### Parallel Opportunities

- **Phase 1**: T001 and T002 are different files — both `[P]`
- **Phase 2**: T003 is a single test file; T004→T006 are sequential edits to `db.py`. No parallelism, by design
- **Phase 3**: T008, T009, T010 hit three different test files — all `[P]`. T016 and T017 are different integration files — both `[P]`. T011–T015 are sequential (shared files, and each depends on the previous)
- **Phase 4**: T018 and T019 both edit `tests/unit/test_db.py`, so they are **sequential**; T020 is a different file and is `[P]` with either. T021–T023 are sequential edits to `db.py`
- **Phase 5**: T029 and T030 are different files — both `[P]`
- **Across stories**: with two developers, one can take US1 (Phase 3) while the other takes T018–T023 of US2 (the pure `db.py` and test work), converging before T026

### Parallel Example: User Story 1

```bash
# The three test files can be written simultaneously:
Task: "Add load_menu() tests to tests/unit/test_db.py"
Task: "Update tests/unit/test_menu_tools.py for state-supplied menu"
Task: "Update tests/unit/test_cart_tools.py to seed menu on state"

# After implementation, the two integration suites update independently:
Task: "Seed menu in initial_state in tests/integration/test_order_support_trajectory.py"
Task: "Seed menu in initial_state in tests/integration/test_router_trajectory.py"
```

---

## Implementation Strategy

### MVP scope: Phases 1–3 (Setup + Foundational + US1)

That is 17 tasks and delivers the migration's core value — menu data staff own and can change
without a release. Orders still are not recorded, but nothing regresses: the conversation, the cart,
the summary, and the ticket all behave exactly as they do today.

1. Complete Phase 1 (Setup) and Phase 2 (Foundational)
2. Complete Phase 3 (US1)
3. **STOP and VALIDATE**: run quickstart scenarios 1–3
4. Demo: change a price in SQLite, start a conversation, watch the new price get quoted

### Incremental delivery

1. Setup + Foundational → a database exists and seeds
2. **+ US1** → menu comes from SQLite (MVP, quickstart 1–3)
3. **+ US2** → orders are recorded and IDs handed out (quickstart 4, 5, 7)
4. **+ US3** → snapshot consistency proven under a mid-run edit
5. Polish → full suite, quickstart walk-through, PR write-up

### Risk notes

- **T026 is the highest-risk task**: it changes the order of operations in `cart_summary_node` (price →
  record → render). Getting it wrong is how a customer gets told an order succeeded when the write
  failed. T020's error case is the test that catches it — write it first and watch it fail
- **T019's atomicity case** needs a deliberately induced mid-transaction failure. Injecting a bad row
  (violating a `CHECK`) after a good one is the simplest way to force the rollback path
- **T009 removes the only test that reads the real `menu.json`.** Its database-backed replacement is
  what keeps FR-013 (prices unchanged after migration) covered — do not drop it silently

---

## Notes

- `[P]` tasks touch different files and have no dependency on incomplete work
- Every test case needs its one-line `(base)` / `(edge)` / `(error)` / `(regression)` comment —
  Constitution Principle I, checked in T033
- Commit after each task or logical group; stop at any checkpoint to validate a story on its own
- `menu.json` is not deleted — it becomes seed data read only by `init_database()`
