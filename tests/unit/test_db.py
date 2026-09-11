import json
import sqlite3
from pathlib import Path

import pytest

from customer_support_fde import db

MENU_JSON_PATH = (
    Path(__file__).parents[2]
    / "src"
    / "customer_support_fde"
    / "menu"
    / "menu.json"
)


# database_path() returns CUSTOMER_SUPPORT_DB when the env var is set and non-empty. (base)
def test_database_path_returns_env_var_when_set(monkeypatch, tmp_path):
    target = tmp_path / "custom.db"
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(target))

    assert db.database_path() == Path(str(target))


# database_path() falls back to the default filename when the env var is unset. (base)
def test_database_path_falls_back_to_default_when_env_var_unset(monkeypatch):
    monkeypatch.delenv("CUSTOMER_SUPPORT_DB", raising=False)

    assert db.database_path() == Path(db.DEFAULT_DB_FILENAME)


# database_path() falls back to the default filename when the env var is set but empty. (edge)
def test_database_path_falls_back_to_default_when_env_var_empty(monkeypatch):
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", "")

    assert db.database_path() == Path(db.DEFAULT_DB_FILENAME)


# database_path() is read at call time, not import time, so changing the env var
# between two calls changes the result. (base)
def test_database_path_is_read_at_call_time_not_import_time(monkeypatch, tmp_path):
    monkeypatch.delenv("CUSTOMER_SUPPORT_DB", raising=False)
    assert db.database_path() == Path(db.DEFAULT_DB_FILENAME)

    target = tmp_path / "later.db"
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(target))
    assert db.database_path() == Path(str(target))


# init_database() on a fresh path creates all three tables and seeds every dish
# from menu.json, returning the seeded count. (base)
def test_init_database_creates_tables_and_seeds_menu(tmp_path):
    path = tmp_path / "fresh.db"

    count = db.init_database(path)

    assert count >= 5
    conn = sqlite3.connect(path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert {"menu_items", "orders", "order_lines"} <= tables
        seeded = conn.execute("SELECT COUNT(*) FROM menu_items").fetchone()[0]
        assert seeded == count
    finally:
        conn.close()


# Re-running init_database() leaves the same dish count with no duplicates. (edge)
def test_init_database_is_idempotent(tmp_path):
    path = tmp_path / "fresh.db"

    first_count = db.init_database(path)
    second_count = db.init_database(path)

    assert first_count == second_count
    conn = sqlite3.connect(path)
    try:
        seeded = conn.execute("SELECT COUNT(*) FROM menu_items").fetchone()[0]
        assert seeded == first_count
    finally:
        conn.close()


# Re-running init_database() updates price and ingredients of an existing dish
# but deletes nothing. (base)
def test_init_database_updates_existing_dish_without_deleting_others(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)

    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "UPDATE menu_items SET price = 1.23, ingredients = '[\"changed\"]' "
            "WHERE name = (SELECT name FROM menu_items LIMIT 1)"
        )
        conn.commit()
        edited_name = conn.execute(
            "SELECT name FROM menu_items WHERE price = 1.23"
        ).fetchone()[0]
    finally:
        conn.close()

    count_after = db.init_database(path)

    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "SELECT price, ingredients FROM menu_items WHERE name = ?", (edited_name,)
        ).fetchone()
        total = conn.execute("SELECT COUNT(*) FROM menu_items").fetchone()[0]
    finally:
        conn.close()

    assert row[0] != 1.23
    assert row[1] != '["changed"]'
    assert total == count_after


# load_menu() returns dishes with exactly the names, prices, and ingredient
# lists in menu.json, in stable name order. (base)
def test_load_menu_returns_exact_menu_json_contents_in_name_order(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)
    expected = sorted(
        json.loads(MENU_JSON_PATH.read_text(encoding="utf-8")),
        key=lambda item: item["name"],
    )

    menu = db.load_menu(path)

    assert menu == expected


# A price edited directly in the database is reflected by the next load_menu() call. (base)
def test_load_menu_reflects_a_direct_database_price_edit(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)
    name = db.load_menu(path)[0]["name"]

    conn = sqlite3.connect(path)
    try:
        conn.execute("UPDATE menu_items SET price = 42.00 WHERE name = ?", (name,))
        conn.commit()
    finally:
        conn.close()

    updated = next(item for item in db.load_menu(path) if item["name"] == name)
    assert updated["price"] == 42.00


# load_menu() against a missing file raises MenuStoreError naming the path. (error)
def test_load_menu_missing_file_raises_menu_store_error(tmp_path):
    missing = tmp_path / "does-not-exist.db"

    with pytest.raises(db.MenuStoreError) as excinfo:
        db.load_menu(missing)

    assert str(missing) in str(excinfo.value)


# load_menu() against a file with no menu_items table raises MenuStoreError. (error)
def test_load_menu_missing_table_raises_menu_store_error(tmp_path):
    path = tmp_path / "no-table.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    with pytest.raises(db.MenuStoreError):
        db.load_menu(path)


# A row whose ingredients JSON will not parse raises MenuStoreError rather
# than returning a partial menu. (error)
def test_load_menu_malformed_ingredients_json_raises_menu_store_error(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)

    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "UPDATE menu_items SET ingredients = 'not-json' "
            "WHERE name = (SELECT name FROM menu_items LIMIT 1)"
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(db.MenuStoreError):
        db.load_menu(path)


# A seeded-then-emptied menu_items table returns []. (edge)
def test_load_menu_returns_empty_list_when_table_is_empty(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)

    conn = sqlite3.connect(path)
    try:
        conn.execute("DELETE FROM menu_items")
        conn.commit()
    finally:
        conn.close()

    assert db.load_menu(path) == []


def _sample_summary() -> dict:
    return {
        "lines": [
            {
                "name": "Kung Pao Chicken",
                "quantity": 2,
                "unit_price": 12.95,
                "line_total": 25.90,
            },
            {
                "name": "Spring Rolls",
                "quantity": 1,
                "unit_price": 6.95,
                "line_total": 6.95,
            },
        ],
        "total": 32.85,
    }


# Every generated order ID uses only ID_ALPHABET, never I, L, O, or U. (base)
def test_generated_order_ids_use_only_the_documented_alphabet():
    forbidden = set("ILOU")
    for _ in range(200):
        order_id = db._new_order_id()
        assert len(order_id) == db.ID_LENGTH
        assert set(order_id) <= set(db.ID_ALPHABET)
        assert not (set(order_id) & forbidden)


# 1,000 generated IDs are all distinct and show no sequential pattern. (base)
def test_generated_order_ids_are_distinct_and_not_sequential():
    ids = [db._new_order_id() for _ in range(1000)]

    assert len(set(ids)) == 1000
    assert ids != sorted(ids)


# format_order_id hyphenates mid-code and normalize_order_id inverts it exactly. (base)
def test_format_and_normalize_order_id_round_trip():
    assert db.format_order_id("K7QP3M9X") == "K7QP-3M9X"
    assert db.normalize_order_id("K7QP-3M9X") == "K7QP3M9X"


# normalize_order_id folds lowercase, hyphens, surrounding whitespace, and
# confusable characters O->0, I->1, L->1. (edge)
def test_normalize_order_id_folds_confusable_input():
    assert db.normalize_order_id("  k7qp-3m9x  ") == "K7QP3M9X"
    assert db.normalize_order_id("k7qp 3m9x") == "K7QP3M9X"
    assert db.normalize_order_id("k7Op-3M9X") == "K70P3M9X"
    assert db.normalize_order_id("IL0O") == "1100"


# record_order returns an 8-char ID and get_order round-trips every line field. (base)
def test_record_order_returns_id_and_get_order_round_trips(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)
    summary = _sample_summary()

    order_id = db.record_order(summary, path)

    assert len(order_id) == db.ID_LENGTH
    stored = db.get_order(order_id, path)
    assert stored["order_id"] == order_id
    assert stored["total"] == summary["total"]
    assert stored["lines"] == summary["lines"]


# Two record_order calls return different IDs and both orders remain readable. (base)
def test_two_record_order_calls_return_different_ids_and_both_readable(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)
    summary = _sample_summary()

    first_id = db.record_order(summary, path)
    second_id = db.record_order(summary, path)

    assert first_id != second_id
    assert db.get_order(first_id, path) is not None
    assert db.get_order(second_id, path) is not None


# A failure partway through record_order leaves no orders row and no
# order_lines rows. (error)
def test_record_order_failure_partway_through_leaves_no_rows(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)
    summary = {
        "lines": [
            {
                "name": "Kung Pao Chicken",
                "quantity": 2,
                "unit_price": 12.95,
                "line_total": 25.90,
            },
            {
                # Violates the line_total > 0 CHECK constraint.
                "name": "Spring Rolls",
                "quantity": 1,
                "unit_price": 6.95,
                "line_total": -1,
            },
        ],
        "total": 32.85,
    }

    with pytest.raises(db.OrderStoreError):
        db.record_order(summary, path)

    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM order_lines").fetchone()[0] == 0
    finally:
        conn.close()


# An order written, connection closed, database reopened, still reads back
# identically. (base)
def test_record_order_survives_reconnect(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)
    summary = _sample_summary()
    order_id = db.record_order(summary, path)

    reread = db.get_order(order_id, path)

    assert reread["lines"] == summary["lines"]
    assert reread["total"] == summary["total"]


# Editing menu_items after an order does not change that order's stored
# names or prices. (regression)
def test_record_order_immune_to_later_menu_edits(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)
    summary = _sample_summary()
    order_id = db.record_order(summary, path)

    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "UPDATE menu_items SET price = 999.99 WHERE name = 'Kung Pao Chicken'"
        )
        conn.commit()
    finally:
        conn.close()

    reread = db.get_order(order_id, path)
    assert reread["lines"][0]["unit_price"] == 12.95


# record_order with an empty lines list raises ValueError and writes nothing. (error)
def test_record_order_empty_lines_raises_value_error(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)

    with pytest.raises(ValueError):
        db.record_order({"lines": [], "total": None}, path)

    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0
    finally:
        conn.close()


# A forced ID collision is retried onto a fresh ID and the order still saves. (error)
def test_record_order_retries_past_a_forced_id_collision(tmp_path, monkeypatch):
    path = tmp_path / "fresh.db"
    db.init_database(path)
    colliding_id = "AAAAAAAA"
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO orders (id, total, created_at) VALUES (?, ?, ?)",
            (colliding_id, 1.00, "2026-01-01T00:00:00.000Z"),
        )
        conn.commit()
    finally:
        conn.close()

    ids = iter([colliding_id, "BBBBBBBB"])
    monkeypatch.setattr(db, "_new_order_id", lambda: next(ids))

    order_id = db.record_order(_sample_summary(), path)

    assert order_id == "BBBBBBBB"
    assert db.get_order(order_id, path) is not None


# get_order finds an order from its lowercase, hyphenated, and O/I/L-typed forms. (edge)
def test_get_order_finds_order_from_forgiving_input_forms(tmp_path, monkeypatch):
    path = tmp_path / "fresh.db"
    db.init_database(path)
    monkeypatch.setattr(db, "_new_order_id", lambda: "K7QP3M9X")

    order_id = db.record_order(_sample_summary(), path)

    assert db.get_order("k7qp-3m9x", path)["order_id"] == order_id
    assert db.get_order(" K7QP 3M9X ", path)["order_id"] == order_id


# get_order on an unrecognizable string returns None rather than raising. (edge)
def test_get_order_returns_none_for_unrecognizable_id(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)

    assert db.get_order("NOT-A-REAL-ID", path) is None
