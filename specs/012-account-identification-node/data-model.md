# Phase 1 Data Model: Customer Account Identification Node

**Feature**: `specs/012-account-identification-node` | **Date**: 2026-09-14

Covers the one new persisted entity from [spec.md](./spec.md) and the `SupportState` fields that
carry it through a run. DDL lives in [contracts/sqlite-schema.sql](./contracts/sqlite-schema.sql).

Existing entities (`menu_items`, `orders`, `order_lines`, `refund_requests`,
`refund_request_lines`, `complaints`) are unchanged and untouched by this feature.

---

## Persisted entities

### Account

A customer's account: its number, and a single free-text paragraph of stored preferences
(likes, dislikes, and allergies, together — see spec Clarifications). Written by
`account_identification_node` on sign-up; read (never written) by the same node on lookup this
feature. Populating `preferences` after creation is a future feature's responsibility (spec
Assumptions).

| Field | SQLite type | Constraints | Notes |
|---|---|---|---|
| `account_number` | `TEXT` | `PRIMARY KEY` | 8-character Crockford base32, generated the same way as `orders.id` (research.md Decision 2). Not a foreign key target — no other table references it in this feature. |
| `preferences` | `TEXT` | nullable | `NULL` until a future feature (the planned conversation-summarization agent) populates it. One free-text paragraph covering likes, dislikes, and allergies together — never parsed by this feature (FR-004, FR-008, Clarifications). |
| `created_at` | `TEXT` | `NOT NULL` | UTC ISO-8601 with trailing `Z`, same format `db.record_order` already writes. |

**Validation rules**:

- `account_number` MUST be unique (FR-010) — enforced by the `PRIMARY KEY` constraint and, at
  generation time, by retrying on a collision the same way `db.record_order` already retries
  `_new_order_id()` (research.md Decision 2).
- Lookup MUST succeed on `account_number` alone — no other column participates in matching an
  account to a customer (FR-009).
- `preferences` is opaque to this feature: no format, length, or content validation is applied
  beyond "it is text or absent."

---

## `SupportState` additions

Two fields added to `src/customer_support_fde/state.py`. Existing fields are unchanged.

| Field | Type | Initial | Purpose |
|---|---|---|---|
| `account_number` | `str \| None` | `None` | The account attached to this conversation, if any — either looked up (FR-004) or newly created (FR-006). `None` when the customer chose to continue without one (FR-007). |
| `account_preferences` | `str \| None` | `None` | That account's stored `preferences` text, copied into state at lookup/creation time so `order_support_agent` can inject it into context without a further database read per turn (research.md Decision 6). `None` whenever `account_number` is `None`, or when a found/newly-created account has no preferences recorded yet. |

`cli.py` seeds both when building the initial state, alongside the existing fields.

---

## Retrieval / write surface

No staff-facing command ships this feature. Two functions on `db.py` back the node's three
outcomes:

| Function | Behavior |
|---|---|
| `get_account(account_number, path=None)` | Normalizes `account_number` the same way `get_order` normalizes an order id, then returns `{"account_number": ..., "preferences": ..., "created_at": ...}` or `None` on no match. Backs FR-004/FR-005. |
| `create_account(path=None)` | Generates a new, collision-checked account number (research.md Decision 2), inserts a row with `preferences = NULL`, and returns the created account's number. Backs FR-006. |

Each follows the existing `db.py` convention: an optional `path` argument resolved through
`_resolve_path`, a connection opened via `_connect` and closed in a `finally`, and `sqlite3.Error`
wrapped in `OrderStoreError` with the existing remediation-hint style.

---

## Node outcome summary

`account_identification_node` always returns exactly one of these three `SupportState` shapes
(full menu/re-prompt contract in
[contracts/account-identification-step.md](./contracts/account-identification-step.md)):

| Customer choice | `account_number` | `account_preferences` | Account row |
|---|---|---|---|
| Use existing account (found) | that account's number | that account's `preferences` (may be `None`) | unchanged |
| Continue without an account | `None` | `None` | none created |
| Sign up for a new account | the newly created number | `None` | one row inserted, `preferences = NULL` |
