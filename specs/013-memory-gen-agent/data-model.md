# Phase 1 Data Model: Customer Memory Generation Agent

**Feature**: `specs/013-memory-gen-agent` | **Date**: 2026-09-14

This feature introduces **no new persisted entity and no schema change**. It writes to the
`preferences` column of the existing `accounts` table, defined by
`specs/012-account-identification-node` (see
[../012-account-identification-node/data-model.md](../012-account-identification-node/data-model.md)
and `db.py`'s `_SCHEMA`). It also introduces **no new `SupportState` field** — see
research.md Decision 3.

---

## Existing entity this feature writes to

### Account (`accounts` table — unchanged shape)

| Field | SQLite type | Constraints | This feature's role |
|---|---|---|---|
| `account_number` | `TEXT` | `PRIMARY KEY` | Read-only lookup key — never generated or modified here (that remains `account_identification_node`'s job). |
| `preferences` | `TEXT` | nullable | **Written by this feature for the first time** — previously always `NULL` per `specs/012`'s Assumptions ("populating `preferences` after creation is a future feature's responsibility"). This feature is that future feature. |
| `created_at` | `TEXT` | `NOT NULL` | Untouched. |

**New validation/shape rule this feature adds** (FR-009, FR-010; not a schema constraint —
enforced by the extraction prompt, not the database):

- `preferences` remains a single free-text value (no structure change), but its *content* must
  now be produced so that a safety-critical allergy statement is textually distinguishable from a
  softer like/dislike/customization statement (e.g. a leading "Allergies: ..." clause when
  allergies are present) — see `contracts/memory-gen-node.md` for the exact expected shape.
- An update MUST be a full replacement of the column's value with the newly rewritten passage
  (never a raw append) — the merge already happened inside the LLM call before the write
  (research.md Decision 4).
- Rows are never inserted or deleted by this feature — only updated. The row for the conversation's
  `account_number` is guaranteed to already exist by the time this node runs (created or looked up
  earlier in the same conversation by `account_identification_node`).

---

## Transient input this feature reads (not persisted by this feature)

### Order Conversation (`SupportState["messages"]`, plus `account_number` / `account_preferences`)

| Field | Type | Source | Used for |
|---|---|---|---|
| `messages` | `list[AnyMessage]` | `SupportState` (existing) | Full order-support transcript handed to the extraction/merge LLM call as-is — this feature does not condense, filter, or store it. |
| `account_number` | `str \| None` | `SupportState` (existing, from `specs/012`) | Guard (FR-002) and the key used for `db.update_account_preferences`. |
| `account_preferences` | `str \| None` | `SupportState` (existing, from `specs/012`) | The account's preferences *as they were at conversation start* — passed to the LLM as "previous preferences" context for the merge. Note this may be stale relative to the database if something else updated the row mid-conversation; acceptable per Assumptions (single customer, single session, no concurrent-write scenario in scope). |

No new fields are added to `SupportState` (`src/customer_support_fde/state.py` is unmodified by
this feature).

---

## Retrieval / write surface

One new function on `db.py` backs this feature's only persistence need:

| Function | Behavior |
|---|---|
| `update_account_preferences(account_number, preferences, path=None)` | Normalizes `account_number` the same way `get_account` does, then executes `UPDATE accounts SET preferences = ? WHERE account_number = ?`. Raises `OrderStoreError` on any `sqlite3.Error`, and also if zero rows matched (the account is expected to already exist — see Decision 7 in research.md). Returns `None`. |

No new read function is needed: `memory_gen_node` receives the account's current preferences from
`SupportState["account_preferences"]` rather than re-querying `db.get_account`.

---

## Node outcome summary

`memory_gen_node` always returns `{}` (no `SupportState` change — research.md Decision 3). Its
only externally observable effect is on the `accounts.preferences` column:

| Scenario | `accounts.preferences` after this node runs |
|---|---|
| No `account_number` on the conversation (guest) | Untouched — node no-ops before any LLM call or DB access (FR-002, SC-002). |
| Account present, conversation contains no like/dislike/allergy/customization statement, and no prior preferences existed | Untouched, remains `NULL` (FR-006). |
| Account present, conversation contains no new statement, but prior preferences existed | Untouched — the merge call reproduces the same prior text unchanged, an idempotent no-op write, or the implementation may skip the write entirely when the rewritten text is identical to the input (implementation detail, not a behavioral difference). |
| Account present, new statement(s) found, no prior preferences | Set to the newly extracted passage. |
| Account present, new statement(s) found, prior preferences existed | Replaced with one rewritten passage combining both, preserving prior allergy/preference facts (FR-005) and formatted per FR-010. |
| Extraction or write fails for any reason | Untouched — fail-silent (FR-008). |
