from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from customer_support_fde import clock, restaurant_time


@pytest.fixture(autouse=True)
def _isolate_tickets_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("CUSTOMER_SUPPORT_TICKETS_DIR", str(tmp_path / "tickets"))


@pytest.fixture(autouse=True)
def _restaurant_timezone(monkeypatch):
    # These tests build their own databases, so skip the database read and use a fixed zone.
    monkeypatch.setattr(restaurant_time, "_timezone", ZoneInfo("America/Los_Angeles"))


@pytest.fixture(autouse=True)
def _local_trusted_clock(monkeypatch):
    # Integration tests never reach the real NTP server.
    monkeypatch.setattr(clock, "trusted_now", lambda: datetime.now(timezone.utc))
