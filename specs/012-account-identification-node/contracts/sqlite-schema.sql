-- Schema contract: Customer Account Identification Node (specs/012-account-identification-node)
--
-- This statement is appended to _SCHEMA in src/customer_support_fde/db.py and applied by
-- init_database() via executescript(). It is additive and uses IF NOT EXISTS, so
-- `customer-support-fde --init-db` stays idempotent and safe to re-run on an existing database
-- (CLAUDE.md). No existing table is altered by this feature.

-- A customer account: its number, and a single free-text paragraph of stored preferences
-- (likes, dislikes, and allergies together). preferences is NULL until a future feature (the
-- planned conversation-summarization agent) populates it — this feature only creates and looks
-- up accounts, per spec.md Assumptions. Not a foreign key target: an account is independent of
-- any specific order (a single account may be used across many separate orders/conversations).
CREATE TABLE IF NOT EXISTS accounts (
    account_number TEXT PRIMARY KEY,
    preferences    TEXT,
    created_at     TEXT NOT NULL
);
