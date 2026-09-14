import pytest


@pytest.fixture(autouse=True)
def _isolate_tickets_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("CUSTOMER_SUPPORT_TICKETS_DIR", str(tmp_path / "tickets"))
