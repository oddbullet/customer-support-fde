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

_CONFUSION_TRANSLATION = str.maketrans({"O": "0", "I": "1", "L": "1"})

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
"""

MenuItem = dict[str, object]


class MenuStoreError(RuntimeError):
    pass


class OrderStoreError(RuntimeError):
    pass


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
        f"Menu database not found at '{path}'. Run: customer-support-fde --init-db"
    )


def _connect(path: Path, *, create: bool = False) -> sqlite3.Connection:
    if not create and not path.exists():
        raise MenuStoreError(_remedy(path))
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_database(path: Path | str | None = None) -> int:
    resolved = _resolve_path(path)
    conn = _connect(resolved, create=True)
    try:
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
    finally:
        conn.close()


def load_menu(path: Path | str | None = None) -> list[MenuItem]:
    resolved = _resolve_path(path)
    conn = _connect(resolved)
    try:
        try:
            rows = conn.execute(
                "SELECT name, price, ingredients FROM menu_items ORDER BY name"
            ).fetchall()
        except sqlite3.Error as exc:
            raise MenuStoreError(
                f"Menu database at '{resolved}' is missing the menu_items table. "
                f"Run: customer-support-fde --init-db"
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
    finally:
        conn.close()


def _new_order_id() -> str:
    return "".join(secrets.choice(ID_ALPHABET) for _ in range(ID_LENGTH))


def format_order_id(order_id: str) -> str:
    midpoint = ID_LENGTH // 2
    return f"{order_id[:midpoint]}-{order_id[midpoint:]}"


def normalize_order_id(raw: str) -> str:
    stripped = raw.strip().upper().replace("-", "").replace(" ", "")
    return stripped.translate(_CONFUSION_TRANSLATION)


def record_order(summary: dict, path: Path | str | None = None) -> str:
    lines = summary["lines"]
    if not lines:
        raise ValueError("Cannot record an order with no lines.")

    resolved = _resolve_path(path)
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    last_error: sqlite3.Error | None = None
    for _ in range(_MAX_ID_ATTEMPTS):
        order_id = _new_order_id()
        conn = _connect(resolved)
        try:
            try:
                with conn:
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
                return order_id
            except sqlite3.IntegrityError as exc:
                if "UNIQUE constraint failed: orders.id" in str(exc):
                    last_error = exc
                    continue
                raise OrderStoreError(
                    f"Failed to record order in database at '{resolved}': {exc}"
                ) from exc
            except sqlite3.Error as exc:
                raise OrderStoreError(
                    f"Failed to record order in database at '{resolved}': {exc}"
                ) from exc
        finally:
            conn.close()

    raise OrderStoreError(
        f"Failed to record order in database at '{resolved}': "
        f"exhausted {_MAX_ID_ATTEMPTS} order ID attempts"
    ) from last_error


def get_order(order_id: str, path: Path | str | None = None) -> dict | None:
    resolved = _resolve_path(path)
    normalized = normalize_order_id(order_id)

    conn = _connect(resolved)
    try:
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
    finally:
        conn.close()
