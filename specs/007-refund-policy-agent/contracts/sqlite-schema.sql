-- Schema contract: Refund Policy Agent (specs/007-refund-policy-agent)
--
-- These statements are appended to _SCHEMA in src/customer_support_fde/db.py and applied by
-- init_database() via executescript(). Every statement is additive and uses IF NOT EXISTS, so
-- `customer-support-fde --init-db` stays idempotent and safe to re-run on an existing database
-- (CLAUDE.md). No existing table is altered by this feature.
--
-- Foreign keys are enforced: _connect() already issues `PRAGMA foreign_keys = ON`.

-- A customer's qualifying refund, recorded as pending.
-- UNIQUE (order_id) is the storage-level enforcement of FR-011 / SC-007: a denied refund is
-- never stored here (it becomes a complaint), so every row is open or approved, which makes
-- "at most one row per order" identical to "no second open or approved request per order".
CREATE TABLE IF NOT EXISTS refund_requests (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id          TEXT    NOT NULL UNIQUE REFERENCES orders (id) ON DELETE CASCADE,
    amount            REAL    NOT NULL CHECK (amount > 0),
    substitute_dishes TEXT,
    return_confirmed  INTEGER NOT NULL CHECK (return_confirmed IN (0, 1)),
    status            TEXT    NOT NULL CHECK (status IN ('pending', 'approved')),
    created_at        TEXT    NOT NULL,

    -- FR-006: the return requirement may be waived only when nothing arrived in place of the
    -- missing item. A received substitute with no return commitment is a denial and must never
    -- reach this table.
    CHECK (return_confirmed = 1 OR substitute_dishes IS NULL)
);

-- One ordered line the customer paid for but did not receive.
-- Mirrors order_lines so the two read the same way. unit_price is copied from the order rather
-- than looked up on the menu, so a later price change cannot alter a past refund (SC-008).
CREATE TABLE IF NOT EXISTS refund_request_lines (
    refund_request_id INTEGER NOT NULL REFERENCES refund_requests (id) ON DELETE CASCADE,
    name              TEXT    NOT NULL,
    quantity          INTEGER NOT NULL CHECK (quantity > 0),
    unit_price        REAL    NOT NULL CHECK (unit_price > 0),
    line_total        REAL    NOT NULL CHECK (line_total > 0),
    PRIMARY KEY (refund_request_id, name)
);

-- Customer dissatisfaction: standalone (US3) or the residue of a denied refund (FR-018).
-- order_id is nullable because a complaint may arrive with no order identified (FR-019).
-- policy_reason is NULL for a standalone complaint and carries the denial reason code
-- otherwise. There is deliberately no uniqueness constraint here: FR-020 scopes complaint
-- uniqueness to a single conversation, which SupportState.complaint_ids tracks in memory
-- (research.md Decision 5). The same order complained about in a later conversation correctly
-- gets its own row.
CREATE TABLE IF NOT EXISTS complaints (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id      TEXT REFERENCES orders (id) ON DELETE CASCADE,
    description   TEXT NOT NULL,
    policy_reason TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

-- Backs the FR-011 duplicate check and the FR-024 per-order retrieval path.
CREATE INDEX IF NOT EXISTS idx_complaints_order_id ON complaints (order_id);
