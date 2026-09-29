import itertools
import shutil
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from customer_support_fde import circuit_breaker, clock, db, restaurant_time


@pytest.fixture(scope="session")
def _seeded_db_template(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("db-template") / "support.db"
    db.init_database(path)
    db.set_restaurant_timezone("America/Los_Angeles", path)
    return path


@pytest.fixture
def refund_db(tmp_path, _seeded_db_template) -> Path:
    path = tmp_path / "refund.db"
    shutil.copyfile(_seeded_db_template, path)
    return path


@pytest.fixture(scope="session")
def _isolated_db_paths(tmp_path_factory) -> Iterator[Path]:
    # One session directory with numbered files; tmp_path_factory.mktemp per test
    # rescans an ever-growing base directory to pick the next number.
    root = tmp_path_factory.mktemp("isolated-dbs")
    return (root / f"{n}.db" for n in itertools.count())


# Point every unit test at its own freshly seeded database, so nothing depends on
# (or writes to) a customer_support.db in the working directory. Tests that need a
# specific database still override CUSTOMER_SUPPORT_DB themselves.
@pytest.fixture(autouse=True)
def _isolate_database(monkeypatch, _isolated_db_paths, _seeded_db_template):
    # Kept out of tmp_path, which some tests assert stays empty.
    path = next(_isolated_db_paths)
    shutil.copyfile(_seeded_db_template, path)
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(path))


@pytest.fixture(autouse=True)
def _isolate_tickets_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("CUSTOMER_SUPPORT_TICKETS_DIR", str(tmp_path / "tickets"))


@pytest.fixture(autouse=True)
def _reset_restaurant_timezone(monkeypatch):
    # Reloaded from each test's own database rather than cached across tests.
    monkeypatch.setattr(restaurant_time, "_timezone", None)


@pytest.fixture(autouse=True)
def _local_trusted_clock(monkeypatch):
    # Tests never reach the real NTP server; test_clock.py covers trusted_now itself.
    monkeypatch.setattr(clock, "trusted_now", lambda: datetime.now(timezone.utc))


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
