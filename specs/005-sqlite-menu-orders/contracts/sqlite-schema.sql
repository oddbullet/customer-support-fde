-- Contract: SQLite schema for the menu and order records.
-- Feature: specs/005-sqlite-menu-orders
--
-- Applied idempotently by `customer-support-fde --init-db`.
-- Every connection additionally sets: PRAGMA foreign_keys = ON;

-- One dish the restaurant offers. Read once per support run (FR-002);
-- written only by --init-db, never during a conversation (FR-001).
CREATE TABLE IF NOT EXISTS menu_items (
    name        TEXT PRIMARY KEY,
    price       REAL NOT NULL CHECK (price > 0),
    -- JSON array of strings, e.g. '["chicken","peanuts"]'.
    ingredients TEXT NOT NULL
);

-- A confirmed order. Written once at confirmation; never updated or deleted.
CREATE TABLE IF NOT EXISTS orders (
    id         TEXT PRIMARY KEY,             -- 8-char code, no I/L/O/U (FR-006, FR-014, FR-015)
    total      REAL NOT NULL CHECK (total > 0),
    created_at TEXT NOT NULL                 -- ISO-8601 UTC
);

-- One dish within an order, priced as of order time.
-- `name` intentionally has NO foreign key to menu_items: a recorded order must
-- survive a dish being renamed, repriced, or removed from the menu (FR-010).
CREATE TABLE IF NOT EXISTS order_lines (
    order_id   TEXT NOT NULL REFERENCES orders (id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    quantity   INTEGER NOT NULL CHECK (quantity > 0),
    unit_price REAL NOT NULL CHECK (unit_price > 0),
    line_total REAL NOT NULL CHECK (line_total > 0),
    -- One line per dish per order, matching the dict[str, int] cart shape.
    PRIMARY KEY (order_id, name)
);

-- Seed upsert applied by --init-db for each dish in menu/menu.json.
-- Updates existing dishes and inserts new ones; never deletes, so historical
-- orders can never be orphaned by a re-seed.
--
--   INSERT INTO menu_items (name, price, ingredients)
--   VALUES (?, ?, ?)
--   ON CONFLICT (name) DO UPDATE SET
--       price = excluded.price,
--       ingredients = excluded.ingredients;
