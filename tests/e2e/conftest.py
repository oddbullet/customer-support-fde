import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from dotenv import load_dotenv

from customer_support_fde import db, restaurant_time
from customer_support_fde.tracing import setup_tracing

load_dotenv()
setup_tracing()

_REQUIRED_ENV_VARS = ["OPENROUTER_API_KEY", "LLM_JUDGE"]


def pytest_collection_modifyitems(config, items):
    missing = [name for name in _REQUIRED_ENV_VARS if not os.environ.get(name)]
    if not missing:
        return
    skip_marker = pytest.mark.skip(
        reason=f"e2e tests require {', '.join(missing)} to be set (see .env.example)"
    )
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip_marker)


@pytest.fixture(autouse=True)
def _isolate_tickets_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("CUSTOMER_SUPPORT_TICKETS_DIR", str(tmp_path / "tickets"))


@pytest.fixture
def e2e_db(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "e2e.db"
    db.init_database(path)
    db.set_restaurant_timezone("America/Los_Angeles", path)
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(path))
    monkeypatch.setattr(restaurant_time, "_timezone", None)
    return path


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
