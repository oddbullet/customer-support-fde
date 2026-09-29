import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from customer_support_fde import circuit_breaker, db


@pytest.fixture
def refund_db(tmp_path) -> Path:
    path = tmp_path / "refund.db"
    db.init_database(path)
    return path


@pytest.fixture(autouse=True)
def _isolate_tickets_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("CUSTOMER_SUPPORT_TICKETS_DIR", str(tmp_path / "tickets"))


@pytest.fixture(autouse=True)
def _reset_circuit():
    circuit_breaker.reset_circuit()
    yield
    circuit_breaker.reset_circuit()


def seed_order(db_path: Path, lines: list[dict], age_hours: float = 0) -> str:
    total = sum(line["line_total"] for line in lines)
    order_id = db.record_order({"lines": lines, "total": total}, db_path)

    created_at = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    )[:-3] + "Z"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE orders SET created_at = ? WHERE id = ?", (created_at, order_id)
        )
        conn.commit()
    finally:
        conn.close()

    return order_id
