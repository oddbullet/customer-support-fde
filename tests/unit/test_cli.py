from unittest.mock import MagicMock

import pytest

from customer_support_fde import cli, db


# cli.run() with no --init-db flag always dispatches to interactive.run_interactive(),
# regardless of stdin/stdout tty status (single-shot/piped-stdin modes removed). (base)
def test_run_dispatches_to_interactive_unconditionally(monkeypatch):
    fake_run_interactive = MagicMock(return_value=0)
    monkeypatch.setattr(cli.interactive, "run_interactive", fake_run_interactive)

    exit_code = cli.run([])

    assert exit_code == 0
    fake_run_interactive.assert_called_once()


# cli.run(["--init-db"]) initializes the database and reports the seeded item count,
# without touching interactive mode. (base)
def test_run_init_db_initializes_database_and_reports_count(monkeypatch, tmp_path, capsys):
    path = tmp_path / "test.db"
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(path))

    fake_run_interactive = MagicMock(return_value=0)
    monkeypatch.setattr(cli.interactive, "run_interactive", fake_run_interactive)

    exit_code = cli.run(["--init-db"])

    assert exit_code == 0
    assert path.exists()
    fake_run_interactive.assert_not_called()

    captured = capsys.readouterr()
    assert str(db.database_path()) in captured.out
    assert "Initialized" in captured.out


# --set-tz stores the IANA name for a supported US zone. (base)
def test_run_set_timezone_stores_iana_name(monkeypatch, capsys):
    fake_run_interactive = MagicMock(return_value=0)
    monkeypatch.setattr(cli.interactive, "run_interactive", fake_run_interactive)

    exit_code = cli.run(["--set-tz", "pacific"])

    assert exit_code == 0
    assert db.get_restaurant_timezone() == "America/Los_Angeles"
    fake_run_interactive.assert_not_called()
    assert "America/Los_Angeles" in capsys.readouterr().out


# An unknown or missing zone name exits 1 and lists the valid options. (negative)
@pytest.mark.parametrize("argv", [["--set-tz", "london"], ["--set-tz"]])
def test_run_set_timezone_rejects_unknown_zone(monkeypatch, capsys, argv):
    db.set_restaurant_timezone("America/Chicago")

    exit_code = cli.run(argv)

    assert exit_code == 1
    assert db.get_restaurant_timezone() == "America/Chicago"
    err = capsys.readouterr().err
    assert "eastern" in err and "hawaii" in err


# cli.run(["--init-db"]) reports errors to stderr and returns a nonzero exit code
# instead of falling through to interactive mode. (base)
def test_run_init_db_reports_error_on_failure(monkeypatch, capsys):
    def _boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(cli.db, "init_database", _boom)

    fake_run_interactive = MagicMock(return_value=0)
    monkeypatch.setattr(cli.interactive, "run_interactive", fake_run_interactive)

    exit_code = cli.run(["--init-db"])

    assert exit_code == 1
    fake_run_interactive.assert_not_called()
    captured = capsys.readouterr()
    assert "boom" in captured.err
