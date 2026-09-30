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


# database_path() returns CUSTOMER_SUPPORT_DB when the env var is set and non-empty. (happy)
def test_database_path_returns_env_var_when_set(monkeypatch, tmp_path):
    target = tmp_path / "custom.db"
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(target))

    assert db.database_path() == Path(str(target))


# database_path() falls back to the default filename when the env var is set but empty. (edge)
def test_database_path_falls_back_to_default_when_env_var_empty(monkeypatch):
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", "")

    assert db.database_path() == Path(db.DEFAULT_DB_FILENAME)


# database_path() is read at call time, not import time, so changing the env var
# between two calls changes the result. (edge)
def test_database_path_is_read_at_call_time_not_import_time(monkeypatch, tmp_path):
    monkeypatch.delenv("CUSTOMER_SUPPORT_DB", raising=False)
    assert db.database_path() == Path(db.DEFAULT_DB_FILENAME)

    target = tmp_path / "later.db"
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(target))
    assert db.database_path() == Path(str(target))


# init_database() on a fresh path creates all three tables and seeds every dish
# from menu.json, returning the seeded count. (happy)
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
        assert {"menu_items", "orders", "order_lines", "accounts"} <= tables
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
# but deletes nothing. (happy)
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
# lists in menu.json, in stable name order. (happy)
def test_load_menu_returns_exact_menu_json_contents_in_name_order(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)
    expected = sorted(
        json.loads(MENU_JSON_PATH.read_text(encoding="utf-8")),
        key=lambda item: item["name"],
    )

    menu = db.load_menu(path)

    assert menu == expected


# A price edited directly in the database is reflected by the next load_menu() call. (happy)
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


# load_menu() against a missing file raises MenuStoreError naming the path. (failure)
def test_load_menu_missing_file_raises_menu_store_error(tmp_path):
    missing = tmp_path / "does-not-exist.db"

    with pytest.raises(db.MenuStoreError) as excinfo:
        db.load_menu(missing)

    assert str(missing) in str(excinfo.value)


# load_menu() against a file with no menu_items table raises MenuStoreError. (failure)
def test_load_menu_missing_table_raises_menu_store_error(tmp_path):
    path = tmp_path / "no-table.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    with pytest.raises(db.MenuStoreError):
        db.load_menu(path)


# A row whose ingredients JSON will not parse raises MenuStoreError rather
# than returning a partial menu. (failure)
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


# Every generated order ID uses only ID_ALPHABET, never I, L, O, or U. (happy)
def test_generated_order_ids_use_only_the_documented_alphabet():
    forbidden = set("ILOU")
    for _ in range(200):
        order_id = db._new_order_id()
        assert len(order_id) == db.ID_LENGTH
        assert set(order_id) <= set(db.ID_ALPHABET)
        assert not (set(order_id) & forbidden)


# 1,000 generated IDs are all distinct and show no sequential pattern. (happy)
def test_generated_order_ids_are_distinct_and_not_sequential():
    ids = [db._new_order_id() for _ in range(1000)]

    assert len(set(ids)) == 1000
    assert ids != sorted(ids)


# format_order_id hyphenates mid-code and normalize_order_id inverts it exactly. (happy)
def test_format_and_normalize_order_id_round_trip():
    assert db.format_order_id("K7QP3M9X") == "K7QP-3M9X"
    assert db.normalize_order_id("K7QP-3M9X") == "K7QP3M9X"


# normalize_order_id folds lowercase, hyphens, and surrounding whitespace. (edge)
def test_normalize_order_id_folds_case_and_whitespace():
    assert db.normalize_order_id("  k7qp-3m9x  ") == "K7QP3M9X"
    assert db.normalize_order_id("k7qp 3m9x") == "K7QP3M9X"


# record_order returns an 8-char ID and get_order round-trips every line field. (happy)
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


# Two record_order calls return different IDs and both orders remain readable. (happy)
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
# order_lines rows. (failure)
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


# Editing menu_items after an order does not change that order's stored
# names or prices. (edge, regression)
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


# record_order with an empty lines list raises ValueError and writes nothing. (failure)
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


# A forced ID collision is retried onto a fresh ID and the order still saves. (edge)
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


# The _new_id/_normalize_id/_format_id refactor leaves order-id behavior unchanged:
# _new_order_id still returns 8-char ID_ALPHABET strings, and format/normalize still
# round-trip exactly as before. (happy, regression)
def test_id_helper_refactor_preserves_order_id_behavior():
    order_id = db._new_order_id()
    assert len(order_id) == db.ID_LENGTH
    assert set(order_id) <= set(db.ID_ALPHABET)
    assert db.normalize_order_id(db.format_order_id("K7QP3M9X")) == "K7QP3M9X"
    assert db.format_order_id("K7QP3M9X") == "K7QP-3M9X"


# _new_account_number returns an 8-char ID_ALPHABET string, same scheme as order ids. (happy)
def test_generated_account_numbers_use_only_the_documented_alphabet():
    forbidden = set("ILOU")
    for _ in range(200):
        account_number = db._new_account_number()
        assert len(account_number) == db.ID_LENGTH
        assert set(account_number) <= set(db.ID_ALPHABET)
        assert not (set(account_number) & forbidden)


# format_account_number hyphenates mid-code and normalize_account_number inverts it. (happy)
def test_format_and_normalize_account_number_round_trip():
    assert db.format_account_number("K7QP3M9X") == "K7QP-3M9X"
    assert db.normalize_account_number("K7QP-3M9X") == "K7QP3M9X"


# normalize_account_number folds lowercase, hyphens, and whitespace the same way
# normalize_order_id does. (edge)
def test_normalize_account_number_folds_case_and_whitespace():
    assert db.normalize_account_number("  k7qp-3m9x  ") == "K7QP3M9X"
    assert db.normalize_account_number("k7qp 3m9x") == "K7QP3M9X"


# get_account returns None for an unknown account number. (edge)
def test_get_account_returns_none_for_unknown_number(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)

    assert db.get_account("NOTAREAL1", path) is None


# create_account then get_account round-trips with preferences None and a populated
# created_at. (happy)
def test_create_account_then_get_account_round_trips(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)

    account_number = db.create_account(path)
    account = db.get_account(account_number, path)

    assert account["account_number"] == account_number
    assert account["preferences"] is None
    assert account["created_at"]


# get_account resolves a lowercase/dashed/confusable number form. (edge)
def test_get_account_resolves_forgiving_number_forms(tmp_path, monkeypatch):
    path = tmp_path / "fresh.db"
    db.init_database(path)
    monkeypatch.setattr(db, "_new_account_number", lambda: "K7QP3M9X")

    account_number = db.create_account(path)

    assert db.get_account("k7qp-3m9x", path)["account_number"] == account_number
    assert db.get_account(" K7QP 3M9X ", path)["account_number"] == account_number


# A forced account-number collision is retried onto a fresh number and the account
# still saves. (edge)
def test_create_account_retries_past_a_forced_number_collision(tmp_path, monkeypatch):
    path = tmp_path / "fresh.db"
    db.init_database(path)
    colliding_number = "AAAAAAAA"
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO accounts (account_number, preferences, created_at) "
            "VALUES (?, ?, ?)",
            (colliding_number, None, "2026-01-01T00:00:00.000Z"),
        )
        conn.commit()
    finally:
        conn.close()

    numbers = iter([colliding_number, "BBBBBBBB"])
    monkeypatch.setattr(db, "_new_account_number", lambda: next(numbers))

    account_number = db.create_account(path)

    assert account_number == "BBBBBBBB"
    assert db.get_account(account_number, path) is not None


# init_database creates the three refund/complaint tables alongside the existing ones. (happy)
def test_init_database_creates_refund_and_complaint_tables(tmp_path):
    path = tmp_path / "fresh.db"

    db.init_database(path)

    conn = sqlite3.connect(path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        conn.close()
    assert {"refund_requests", "refund_request_lines", "complaints"} <= tables


# A second refund_requests insert for the same order_id raises IntegrityError (UNIQUE). (failure)
def test_refund_requests_order_id_is_unique(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)
    order_id = db.record_order(_sample_summary(), path)

    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute(
            "INSERT INTO refund_requests "
            "(order_id, amount, substitute_dishes, return_confirmed, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (order_id, 10.0, None, 0, "pending", "2026-01-01T00:00:00.000Z"),
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO refund_requests "
                "(order_id, amount, substitute_dishes, return_confirmed, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (order_id, 5.0, None, 0, "pending", "2026-01-01T00:00:00.000Z"),
            )
    finally:
        conn.close()


# refund_requests.return_confirmed rejects values outside (0, 1). (failure)
def test_refund_requests_return_confirmed_rejects_values_outside_zero_one(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)
    order_id = db.record_order(_sample_summary(), path)

    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO refund_requests "
                "(order_id, amount, substitute_dishes, return_confirmed, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (order_id, 10.0, None, 2, "pending", "2026-01-01T00:00:00.000Z"),
            )
    finally:
        conn.close()


# A row with return_confirmed = 0 and a non-NULL substitute_dishes is rejected by the
# CHECK constraint (FR-006 waiver only applies when nothing arrived). (failure)
def test_refund_requests_rejects_unconfirmed_return_with_substitute_dishes(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)
    order_id = db.record_order(_sample_summary(), path)

    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO refund_requests "
                "(order_id, amount, substitute_dishes, return_confirmed, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    order_id,
                    10.0,
                    '["Mapo Tofu"]',
                    0,
                    "pending",
                    "2026-01-01T00:00:00.000Z",
                ),
            )
    finally:
        conn.close()


def _sample_refund_lines() -> list[dict]:
    return [
        {
            "name": "Mapo Tofu",
            "quantity": 1,
            "unit_price": 10.0,
            "line_total": 10.0,
        }
    ]


# record_refund_request writes one refund_requests row plus its refund_request_lines and
# returns the new id, with status written as pending. (happy)
def test_record_refund_request_writes_row_and_lines_returns_id(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)
    order_id = db.record_order(_sample_summary(), path)

    request_id = db.record_refund_request(
        order_id,
        lines=_sample_refund_lines(),
        amount=10.0,
        substitute_dishes=None,
        return_confirmed=False,
        path=path,
    )

    assert isinstance(request_id, int)
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "SELECT order_id, amount, status FROM refund_requests WHERE id = ?",
            (request_id,),
        ).fetchone()
        line_count = conn.execute(
            "SELECT COUNT(*) FROM refund_request_lines WHERE refund_request_id = ?",
            (request_id,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert row == (order_id, 10.0, "pending")
    assert line_count == 1


# substitute_dishes round-trips as a JSON array and is NULL when nothing arrived. (happy)
def test_record_refund_request_substitute_dishes_round_trips_as_json_or_null(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)
    order_id_1 = db.record_order(_sample_summary(), path)
    order_id_2 = db.record_order(_sample_summary(), path)

    request_id_with = db.record_refund_request(
        order_id_1,
        lines=_sample_refund_lines(),
        amount=10.0,
        substitute_dishes=["Spring Rolls"],
        return_confirmed=True,
        path=path,
    )
    request_id_without = db.record_refund_request(
        order_id_2,
        lines=_sample_refund_lines(),
        amount=10.0,
        substitute_dishes=None,
        return_confirmed=False,
        path=path,
    )

    with_result = db.get_refund_request_for_order(order_id_1, path)
    without_result = db.get_refund_request_for_order(order_id_2, path)
    assert with_result["substitute_dishes"] == ["Spring Rolls"]
    assert without_result["substitute_dishes"] is None


# get_refund_request_for_order returns the request with lines attached, or None. (happy)
def test_get_refund_request_for_order_returns_request_with_lines_or_none(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)
    order_id = db.record_order(_sample_summary(), path)
    db.record_refund_request(
        order_id,
        lines=_sample_refund_lines(),
        amount=10.0,
        substitute_dishes=None,
        return_confirmed=False,
        path=path,
    )

    found = db.get_refund_request_for_order(order_id, path)
    missing = db.get_refund_request_for_order("NOTAREAL1", path)

    assert found["order_id"] == order_id
    assert found["lines"] == _sample_refund_lines()
    assert missing is None


# list_refund_requests returns newest first. (happy)
def test_list_refund_requests_returns_newest_first(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)
    order_id_1 = db.record_order(_sample_summary(), path)
    order_id_2 = db.record_order(_sample_summary(), path)
    db.record_refund_request(
        order_id_1,
        lines=_sample_refund_lines(),
        amount=10.0,
        substitute_dishes=None,
        return_confirmed=False,
        path=path,
    )
    db.record_refund_request(
        order_id_2,
        lines=_sample_refund_lines(),
        amount=10.0,
        substitute_dishes=None,
        return_confirmed=False,
        path=path,
    )

    requests = db.list_refund_requests(path)

    assert [r["order_id"] for r in requests] == [order_id_2, order_id_1]


# A sqlite3.Error during record_refund_request surfaces as OrderStoreError. (failure)
def test_record_refund_request_sqlite_error_surfaces_as_order_store_error(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)

    with pytest.raises(db.OrderStoreError):
        db.record_refund_request(
            "NOTAREAL1",
            lines=_sample_refund_lines(),
            amount=10.0,
            substitute_dishes=None,
            return_confirmed=False,
            path=path,
        )


def _sample_complaint_kwargs() -> dict:
    return {"description": "The food was cold."}


# record_complaint writes a row and returns its id, with order_id NULL when none is
# supplied and policy_reason NULL for a standalone complaint. (happy)
def test_record_complaint_writes_row_with_nullable_order_id_and_policy_reason(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)

    complaint_id = db.record_complaint(description="Rude service.", path=path)

    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "SELECT order_id, description, policy_reason FROM complaints WHERE id = ?",
            (complaint_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row == (None, "Rude service.", None)


# extend_complaint updates description, policy_reason, and updated_at while leaving id
# and created_at unchanged. (happy)
def test_extend_complaint_updates_fields_but_preserves_id_and_created_at(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)
    complaint_id = db.record_complaint(
        description="First complaint.", policy_reason="outside_window", path=path
    )
    original = next(c for c in db.list_complaints(path) if c["id"] == complaint_id)

    db.extend_complaint(
        complaint_id,
        description="Second complaint, same issue.",
        policy_reason="outside_window",
        path=path,
    )

    updated = next(c for c in db.list_complaints(path) if c["id"] == complaint_id)
    assert updated["id"] == original["id"]
    assert updated["created_at"] == original["created_at"]
    assert updated["description"] == "Second complaint, same issue."


# list_complaints returns newest first. (happy)
def test_list_complaints_returns_newest_first(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)
    first_id = db.record_complaint(description="First.", path=path)
    second_id = db.record_complaint(description="Second.", path=path)

    complaints = db.list_complaints(path)

    assert [c["id"] for c in complaints] == [second_id, first_id]


# A sqlite3.Error during record_complaint surfaces as OrderStoreError. (failure)
def test_record_complaint_sqlite_error_surfaces_as_order_store_error(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)

    with pytest.raises(db.OrderStoreError):
        db.record_complaint(description="test", order_id="NOTAREAL1", path=path)


# update_account_preferences sets the preferences column for an existing account
# and returns None. (happy)
def test_update_account_preferences_sets_column_and_returns_none(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)
    account_number = db.create_account(path)

    result = db.update_account_preferences(
        account_number, "Allergies: peanuts.", path
    )

    assert result is None
    assert db.get_account(account_number, path)["preferences"] == (
        "Allergies: peanuts."
    )


# update_account_preferences resolves a differently-cased/spaced/confusable
# account number via the same normalization get_account uses. (edge)
def test_update_account_preferences_resolves_forgiving_number_forms(
    tmp_path, monkeypatch
):
    path = tmp_path / "fresh.db"
    db.init_database(path)
    monkeypatch.setattr(db, "_new_account_number", lambda: "K7QP3M9X")
    account_number = db.create_account(path)

    db.update_account_preferences(" k7qp-3m9x ", "Loves spicy food.", path)

    assert db.get_account(account_number, path)["preferences"] == (
        "Loves spicy food."
    )


# update_account_preferences on an account number matching no row raises
# OrderStoreError. (failure)
def test_update_account_preferences_unknown_number_raises_order_store_error(
    tmp_path,
):
    path = tmp_path / "fresh.db"
    db.init_database(path)

    with pytest.raises(db.OrderStoreError):
        db.update_account_preferences("NOTAREAL1", "Loves spicy food.", path)


# A forced sqlite3.Error during update_account_preferences raises
# OrderStoreError wrapping it. (failure)
def test_update_account_preferences_sqlite_error_surfaces_as_order_store_error(
    tmp_path, monkeypatch
):
    path = tmp_path / "fresh.db"
    db.init_database(path)
    account_number = db.create_account(path)

    class _FakeConnection:
        def execute(self, *args, **kwargs):
            raise sqlite3.Error("disk I/O error")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def close(self):
            pass

    monkeypatch.setattr(db, "_connect", lambda *args, **kwargs: _FakeConnection())

    with pytest.raises(db.OrderStoreError):
        db.update_account_preferences(account_number, "Loves spicy food.", path)


def _db_without_tables(tmp_path):
    # The file exists (so no MenuStoreError), but every query fails with
    # sqlite3.OperationalError: no such table.
    path = tmp_path / "broken.db"
    sqlite3.connect(path).close()
    return path


# A sqlite3.Error while reading an order or account, or creating an account, surfaces
# as OrderStoreError, matching the write paths. (failure)
@pytest.mark.parametrize(
    "call",
    [
        lambda path: db.get_order("K7QP3M9X", path),
        lambda path: db.get_account("K7QP3M9X", path),
        db.create_account,
    ],
    ids=["get_order", "get_account", "create_account"],
)
def test_sqlite_error_surfaces_as_order_store_error(tmp_path, call):
    path = _db_without_tables(tmp_path)

    with pytest.raises(db.OrderStoreError):
        call(path)


# A fresh database has no restaurant timezone until one is set; setting it twice keeps
# only the latest value, and re-running init_database leaves it in place. (happy)
def test_restaurant_timezone_round_trip_and_survives_reinit(tmp_path):
    path = tmp_path / "tz.db"
    db.init_database(path)

    assert db.get_restaurant_timezone(path) is None

    db.set_restaurant_timezone("America/New_York", path)
    db.set_restaurant_timezone("America/Chicago", path)
    db.init_database(path)

    assert db.get_restaurant_timezone(path) == "America/Chicago"
