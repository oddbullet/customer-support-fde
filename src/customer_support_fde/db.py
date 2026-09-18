import contextlib
import json
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

DEFAULT_DB_FILENAME = "customer_support.db"

ID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32: no I, L, O, U
ID_LENGTH = 8
_MAX_ID_ATTEMPTS = 5

_SCHEMA = """
CREATE TABLE IF NOT EXISTS menu_items (
    name        TEXT PRIMARY KEY,
    price       REAL NOT NULL CHECK (price > 0),
    ingredients TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id         TEXT PRIMARY KEY,
    total      REAL NOT NULL CHECK (total > 0),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_lines (
    order_id   TEXT NOT NULL REFERENCES orders (id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    quantity   INTEGER NOT NULL CHECK (quantity > 0),
    unit_price REAL NOT NULL CHECK (unit_price > 0),
    line_total REAL NOT NULL CHECK (line_total > 0),
    PRIMARY KEY (order_id, name)
);

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
"""

MenuItem = dict[str, object]


class MenuStoreError(RuntimeError):
    pass


class OrderStoreError(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def database_path() -> Path:
    env_value = os.environ.get("CUSTOMER_SUPPORT_DB")
    if env_value:
        return Path(env_value)
    return Path(DEFAULT_DB_FILENAME)


def _resolve_path(path: Path | str | None) -> Path:
    if path is None:
        return database_path()
    return Path(path)


def _remedy(path: Path) -> str:
    return (
        f"Menu database not found at '{path}'. Run: uv run start --init-db"
    )


def _connect(path: Path, *, create: bool = False) -> sqlite3.Connection:
    if not create and not path.exists():
        raise MenuStoreError(_remedy(path))
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextlib.contextmanager
def _connection(path: Path, *, create: bool = False):
    conn = _connect(path, create=create)
    try:
        yield conn
    finally:
        conn.close()


def init_database(path: Path | str | None = None) -> int:
    resolved = _resolve_path(path)
    with _connection(resolved, create=True) as conn:
        conn.executescript(_SCHEMA)

        menu_json = (
            resources.files("customer_support_fde.menu")
            .joinpath("menu.json")
            .read_text(encoding="utf-8")
        )
        dishes = json.loads(menu_json)

        with conn:
            for dish in dishes:
                conn.execute(
                    """
                    INSERT INTO menu_items (name, price, ingredients)
                    VALUES (?, ?, ?)
                    ON CONFLICT (name) DO UPDATE SET
                        price = excluded.price,
                        ingredients = excluded.ingredients
                    """,
                    (dish["name"], dish["price"], json.dumps(dish["ingredients"])),
                )

        return len(dishes)


def load_menu(path: Path | str | None = None) -> list[MenuItem]:
    resolved = _resolve_path(path)
    with _connection(resolved) as conn:
        try:
            rows = conn.execute(
                "SELECT name, price, ingredients FROM menu_items ORDER BY name"
            ).fetchall()
        except sqlite3.Error as exc:
            raise MenuStoreError(
                f"Menu database at '{resolved}' is missing the menu_items table. "
                f"Run: uv run start --init-db"
            ) from exc

        menu: list[MenuItem] = []
        for name, price, ingredients_json in rows:
            try:
                ingredients = json.loads(ingredients_json)
            except json.JSONDecodeError as exc:
                raise MenuStoreError(
                    f"Menu database at '{resolved}' has a malformed ingredients "
                    f"value for '{name}'."
                ) from exc
            menu.append({"name": name, "price": price, "ingredients": ingredients})
        return menu


def _new_id() -> str:
    return "".join(secrets.choice(ID_ALPHABET) for _ in range(ID_LENGTH))


def _format_id(id_: str) -> str:
    midpoint = ID_LENGTH // 2
    return f"{id_[:midpoint]}-{id_[midpoint:]}"


def _normalize_id(raw: str) -> str:
    return raw.strip().upper().replace("-", "").replace(" ", "")


def _insert_with_new_id(
    resolved: Path,
    id_generator,
    insert,
    unique_error_substring: str,
    action_description: str,
) -> str:
    last_error: sqlite3.Error | None = None
    for _ in range(_MAX_ID_ATTEMPTS):
        new_id = id_generator()
        with _connection(resolved) as conn:
            try:
                with conn:
                    insert(conn, new_id)
                return new_id
            except sqlite3.IntegrityError as exc:
                if unique_error_substring in str(exc):
                    last_error = exc
                    continue
                raise OrderStoreError(
                    f"Failed to {action_description} in database at '{resolved}': {exc}"
                ) from exc
            except sqlite3.Error as exc:
                raise OrderStoreError(
                    f"Failed to {action_description} in database at '{resolved}': {exc}"
                ) from exc

    raise OrderStoreError(
        f"Failed to {action_description} in database at '{resolved}': "
        f"exhausted {_MAX_ID_ATTEMPTS} attempts generating a unique id"
    ) from last_error


def _new_order_id() -> str:
    return _new_id()


def format_order_id(order_id: str) -> str:
    return _format_id(order_id)


def normalize_order_id(raw: str) -> str:
    return _normalize_id(raw)


def _new_account_number() -> str:
    return _new_id()


def format_account_number(account_number: str) -> str:
    return _format_id(account_number)


def normalize_account_number(raw: str) -> str:
    return _normalize_id(raw)


def record_order(summary: dict, path: Path | str | None = None) -> str:
    lines = summary["lines"]
    if not lines:
        raise ValueError("Cannot record an order with no lines.")

    resolved = _resolve_path(path)
    created_at = _now_iso()

    def insert(conn: sqlite3.Connection, order_id: str) -> None:
        conn.execute(
            "INSERT INTO orders (id, total, created_at) VALUES (?, ?, ?)",
            (order_id, summary["total"], created_at),
        )
        for line in lines:
            conn.execute(
                """
                INSERT INTO order_lines
                    (order_id, name, quantity, unit_price, line_total)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    line["name"],
                    line["quantity"],
                    line["unit_price"],
                    line["line_total"],
                ),
            )

    return _insert_with_new_id(
        resolved,
        _new_order_id,
        insert,
        "UNIQUE constraint failed: orders.id",
        "record order",
    )


def get_order(order_id: str, path: Path | str | None = None) -> dict | None:
    resolved = _resolve_path(path)
    normalized = normalize_order_id(order_id)

    with _connection(resolved) as conn:
        order_row = conn.execute(
            "SELECT id, total, created_at FROM orders WHERE id = ?", (normalized,)
        ).fetchone()
        if order_row is None:
            return None

        line_rows = conn.execute(
            """
            SELECT name, quantity, unit_price, line_total
            FROM order_lines
            WHERE order_id = ?
            ORDER BY name
            """,
            (normalized,),
        ).fetchall()

        return {
            "order_id": order_row[0],
            "total": order_row[1],
            "created_at": order_row[2],
            "lines": [
                {
                    "name": name,
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "line_total": line_total,
                }
                for name, quantity, unit_price, line_total in line_rows
            ],
        }


def create_account(path: Path | str | None = None) -> str:
    resolved = _resolve_path(path)
    created_at = _now_iso()

    def insert(conn: sqlite3.Connection, account_number: str) -> None:
        conn.execute(
            "INSERT INTO accounts (account_number, preferences, created_at) "
            "VALUES (?, NULL, ?)",
            (account_number, created_at),
        )

    return _insert_with_new_id(
        resolved,
        _new_account_number,
        insert,
        "UNIQUE constraint failed: accounts.account_number",
        "create account",
    )


def get_account(account_number: str, path: Path | str | None = None) -> dict | None:
    resolved = _resolve_path(path)
    normalized = normalize_account_number(account_number)

    with _connection(resolved) as conn:
        row = conn.execute(
            "SELECT account_number, preferences, created_at FROM accounts "
            "WHERE account_number = ?",
            (normalized,),
        ).fetchone()
        if row is None:
            return None
        return {
            "account_number": row[0],
            "preferences": row[1],
            "created_at": row[2],
        }


def update_account_preferences(
    account_number: str,
    preferences: str,
    path: Path | str | None = None,
) -> None:
    resolved = _resolve_path(path)
    normalized = normalize_account_number(account_number)

    with _connection(resolved) as conn:
        try:
            with conn:
                cursor = conn.execute(
                    "UPDATE accounts SET preferences = ? WHERE account_number = ?",
                    (preferences, normalized),
                )
            if cursor.rowcount == 0:
                raise OrderStoreError(
                    f"No account '{normalized}' found in database at '{resolved}'."
                )
        except sqlite3.Error as exc:
            raise OrderStoreError(
                f"Failed to update account preferences in database at "
                f"'{resolved}': {exc}"
            ) from exc


def record_refund_request(
    order_id: str,
    lines: list[dict],
    amount: float,
    substitute_dishes: list[str] | None,
    return_confirmed: bool,
    path: Path | str | None = None,
) -> int:
    resolved = _resolve_path(path)
    created_at = _now_iso()
    substitute_json = json.dumps(substitute_dishes) if substitute_dishes else None

    with _connection(resolved) as conn:
        try:
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO refund_requests
                        (order_id, amount, substitute_dishes, return_confirmed,
                         status, created_at)
                    VALUES (?, ?, ?, ?, 'pending', ?)
                    """,
                    (
                        order_id,
                        amount,
                        substitute_json,
                        1 if return_confirmed else 0,
                        created_at,
                    ),
                )
                request_id = cursor.lastrowid
                for line in lines:
                    conn.execute(
                        """
                        INSERT INTO refund_request_lines
                            (refund_request_id, name, quantity, unit_price, line_total)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            request_id,
                            line["name"],
                            line["quantity"],
                            line["unit_price"],
                            line["line_total"],
                        ),
                    )
            return request_id
        except sqlite3.Error as exc:
            raise OrderStoreError(
                f"Failed to record refund request in database at '{resolved}': {exc}"
            ) from exc


def _row_to_refund_request(
    conn: sqlite3.Connection,
    row: tuple,
) -> dict:
    request_id, order_id, amount, substitute_json, return_confirmed, status, created_at = row
    line_rows = conn.execute(
        """
        SELECT name, quantity, unit_price, line_total
        FROM refund_request_lines
        WHERE refund_request_id = ?
        ORDER BY name
        """,
        (request_id,),
    ).fetchall()
    return {
        "id": request_id,
        "order_id": order_id,
        "amount": amount,
        "substitute_dishes": json.loads(substitute_json) if substitute_json else None,
        "return_confirmed": bool(return_confirmed),
        "status": status,
        "created_at": created_at,
        "lines": [
            {
                "name": name,
                "quantity": quantity,
                "unit_price": unit_price,
                "line_total": line_total,
            }
            for name, quantity, unit_price, line_total in line_rows
        ],
    }


def get_refund_request_for_order(order_id: str, path: Path | str | None = None) -> dict | None:
    resolved = _resolve_path(path)
    with _connection(resolved) as conn:
        row = conn.execute(
            """
            SELECT id, order_id, amount, substitute_dishes, return_confirmed,
                   status, created_at
            FROM refund_requests
            WHERE order_id = ?
            """,
            (order_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_refund_request(conn, row)


def list_refund_requests(path: Path | str | None = None) -> list[dict]:
    resolved = _resolve_path(path)
    with _connection(resolved) as conn:
        rows = conn.execute(
            """
            SELECT id, order_id, amount, substitute_dishes, return_confirmed,
                   status, created_at
            FROM refund_requests
            ORDER BY id DESC
            """
        ).fetchall()
        return [_row_to_refund_request(conn, row) for row in rows]


def record_complaint(
    description: str,
    order_id: str | None = None,
    policy_reason: str | None = None,
    path: Path | str | None = None,
) -> int:
    resolved = _resolve_path(path)
    now = _now_iso()

    with _connection(resolved) as conn:
        try:
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO complaints
                        (order_id, description, policy_reason, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (order_id, description, policy_reason, now, now),
                )
            return cursor.lastrowid
        except sqlite3.Error as exc:
            raise OrderStoreError(
                f"Failed to record complaint in database at '{resolved}': {exc}"
            ) from exc


def extend_complaint(
    complaint_id: int,
    description: str,
    policy_reason: str | None,
    path: Path | str | None = None,
) -> None:
    resolved = _resolve_path(path)
    now = _now_iso()

    with _connection(resolved) as conn:
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE complaints
                    SET description = ?, policy_reason = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (description, policy_reason, now, complaint_id),
                )
        except sqlite3.Error as exc:
            raise OrderStoreError(
                f"Failed to update complaint in database at '{resolved}': {exc}"
            ) from exc


def list_complaints(path: Path | str | None = None) -> list[dict]:
    resolved = _resolve_path(path)
    with _connection(resolved) as conn:
        rows = conn.execute(
            """
            SELECT id, order_id, description, policy_reason, created_at, updated_at
            FROM complaints
            ORDER BY id DESC
            """
        ).fetchall()
        return [
            {
                "id": id_,
                "order_id": order_id,
                "description": description,
                "policy_reason": policy_reason,
                "created_at": created_at,
                "updated_at": updated_at,
            }
            for id_, order_id, description, policy_reason, created_at, updated_at in rows
        ]
