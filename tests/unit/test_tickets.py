import logging
import re

import pytest

from customer_support_fde import tickets


# tickets_dir() defaults to Path("tickets") when no env var is set. (happy)
def test_tickets_dir_defaults_to_tickets_folder(monkeypatch):
    monkeypatch.delenv("CUSTOMER_SUPPORT_TICKETS_DIR", raising=False)

    assert tickets.tickets_dir() == tickets.Path("tickets")


# tickets_dir() resolves CUSTOMER_SUPPORT_TICKETS_DIR when set. (happy)
def test_tickets_dir_resolves_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("CUSTOMER_SUPPORT_TICKETS_DIR", str(tmp_path))

    assert tickets.tickets_dir() == tickets.Path(str(tmp_path))


# The shared write path creates a missing tickets directory before writing. (edge)
def test_shared_write_creates_missing_directory(monkeypatch, tmp_path):
    target_dir = tmp_path / "nested" / "tickets"
    monkeypatch.setenv("CUSTOMER_SUPPORT_TICKETS_DIR", str(target_dir))

    path = tickets._write_ticket_file(target_dir / "order-ABC123.md", "content")

    assert path == target_dir / "order-ABC123.md"
    assert path.read_text() == "content"


# An OSError during directory creation or write is caught, logged, and the
# caller gets None back with no exception propagating. (failure)
def test_shared_write_handles_oserror(monkeypatch, tmp_path, caplog):
    target_path = tmp_path / "order-ABC123.md"

    def _raise_oserror(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(tickets.Path, "mkdir", _raise_oserror)

    with caplog.at_level(logging.ERROR):
        result = tickets._write_ticket_file(target_path, "content")

    assert result is None
    assert not target_path.exists()
    assert any(record.levelno == logging.ERROR for record in caplog.records)


# Non-ASCII content (e.g. a customer's own words in the issue text) is
# written as UTF-8 rather than the platform's default encoding, which on
# Windows (cp1252) would raise UnicodeEncodeError for characters like this. (edge, regression)
def test_shared_write_handles_non_ascii_content(monkeypatch, tmp_path):
    target_path = tmp_path / "refund-ABC123.md"

    path = tickets._write_ticket_file(target_path, "customer wrote: 拍照留念")

    assert path == target_path
    assert path.read_text(encoding="utf-8") == "customer wrote: 拍照留念"


def _order_ticket(order_id="ABC123", lines=None, total=31.40):
    return {
        "order_id": order_id,
        "items": {"Kung Pao Chicken": 2, "Spring Rolls": 1},
        "lines": lines
        if lines is not None
        else [
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
        "total": total,
    }


# write_order_ticket writes every line's name/quantity/unit price/line total
# and the total to order-<order_id>.md, returning that path. (happy)
def test_write_order_ticket_writes_lines_and_total(monkeypatch, tmp_path):
    monkeypatch.setenv("CUSTOMER_SUPPORT_TICKETS_DIR", str(tmp_path))
    order_ticket = _order_ticket()

    path = tickets.write_order_ticket(order_ticket)

    assert path == tmp_path / "order-ABC123.md"
    content = path.read_text()
    assert "Kung Pao Chicken" in content
    assert "2" in content
    assert "12.95" in content
    assert "25.90" in content
    assert "Spring Rolls" in content
    assert "6.95" in content
    assert "31.40" in content


# write_order_ticket writes nothing and returns None for an empty cart. (edge)
def test_write_order_ticket_empty_lines_writes_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("CUSTOMER_SUPPORT_TICKETS_DIR", str(tmp_path))
    order_ticket = _order_ticket(lines=[], total=None)

    path = tickets.write_order_ticket(order_ticket)

    assert path is None
    assert list(tmp_path.iterdir()) == []


# A second write for the same order_id replaces the first file. (edge)
def test_write_order_ticket_repeat_write_replaces_file(monkeypatch, tmp_path):
    monkeypatch.setenv("CUSTOMER_SUPPORT_TICKETS_DIR", str(tmp_path))
    tickets.write_order_ticket(_order_ticket())

    tickets.write_order_ticket(_order_ticket(total=999.99))

    matching = list(tmp_path.glob("order-ABC123.md"))
    assert len(matching) == 1
    assert "999.99" in matching[0].read_text()


def _refund_ticket(
    order_id="K7QP3M9X",
    issue="Customer received the wrong dish.",
    sentiment="negative",
    refund_created=True,
):
    return {
        "order_id": order_id,
        "order": {"order_id": order_id, "total": 22.0, "lines": []} if order_id else None,
        "sentiment": sentiment,
        "decision": "eligible" if refund_created else None,
        "refund_request": {"id": 1, "amount": 10.0} if refund_created else None,
        "complaint_ids": [],
        "issue": issue,
        "refund_created": refund_created,
    }


# write_refund_ticket writes the issue, sentiment, order ID, and
# refund-created status to refund-<order_id>-<suffix>.md for a known order id. (happy)
def test_write_refund_ticket_known_order_id(monkeypatch, tmp_path):
    monkeypatch.setenv("CUSTOMER_SUPPORT_TICKETS_DIR", str(tmp_path))
    refund_ticket = _refund_ticket()

    path = tickets.write_refund_ticket(refund_ticket)

    assert path.parent == tmp_path
    assert re.match(r"refund-K7QP3M9X-[0-9a-f]{8}\.md$", path.name)
    content = path.read_text()
    assert "Customer received the wrong dish." in content
    assert "negative" in content
    assert "K7QP3M9X" in content
    assert "**Refund Request Created:** Yes" in content


# write_refund_ticket denotes no refund created for a denied/no-refund case. (happy)
def test_write_refund_ticket_no_refund_created(monkeypatch, tmp_path):
    monkeypatch.setenv("CUSTOMER_SUPPORT_TICKETS_DIR", str(tmp_path))
    refund_ticket = _refund_ticket(refund_created=False)

    path = tickets.write_refund_ticket(refund_ticket)

    assert "**Refund Request Created:** No" in path.read_text()


# write_refund_ticket falls back to a random-suffixed filename and renders
# the order id as Unknown when order_id is None. (edge)
def test_write_refund_ticket_unknown_order_id(monkeypatch, tmp_path):
    monkeypatch.setenv("CUSTOMER_SUPPORT_TICKETS_DIR", str(tmp_path))
    refund_ticket = _refund_ticket(order_id=None)

    path = tickets.write_refund_ticket(refund_ticket)

    assert re.match(r"refund-unknown-[0-9a-f]{32}\.md$", path.name)
    assert "Unknown" in path.read_text()


# write_refund_ticket renders None sentiment/issue as unavailable/Not
# recorded rather than the literal string "None". (edge)
def test_write_refund_ticket_renders_missing_sentiment_and_issue(monkeypatch, tmp_path):
    monkeypatch.setenv("CUSTOMER_SUPPORT_TICKETS_DIR", str(tmp_path))
    refund_ticket = _refund_ticket(issue=None, sentiment=None)

    path = tickets.write_refund_ticket(refund_ticket)
    content = path.read_text()

    assert "unavailable" in content
    assert "Not recorded" in content
    assert "**Issue:** Not recorded" in content
    assert "**Customer Sentiment:** unavailable" in content


# write_refund_ticket bolds only the field label, leaving the value as
# plain text after it, for every field (order id, issue, sentiment,
# refund-created status). (happy, regression)
def test_write_refund_ticket_bolds_only_labels(monkeypatch, tmp_path):
    monkeypatch.setenv("CUSTOMER_SUPPORT_TICKETS_DIR", str(tmp_path))
    refund_ticket = _refund_ticket()

    path = tickets.write_refund_ticket(refund_ticket)
    content = path.read_text()

    assert "**Order ID:** K7QP3M9X" in content
    assert "**Issue:** Customer received the wrong dish." in content
    assert "**Customer Sentiment:** negative" in content
    assert "**Refund Request Created:** Yes" in content


# write_refund_ticket never wraps an entire field line (label and value
# together) in bold markdown - only the label is bold. (happy, regression)
def test_write_refund_ticket_does_not_bold_entire_field_line(monkeypatch, tmp_path):
    monkeypatch.setenv("CUSTOMER_SUPPORT_TICKETS_DIR", str(tmp_path))
    refund_ticket = _refund_ticket()

    path = tickets.write_refund_ticket(refund_ticket)
    content = path.read_text()

    assert "**Order ID: K7QP3M9X**" not in content
    assert "**Issue: Customer received the wrong dish.**" not in content
    assert "**Customer Sentiment: negative**" not in content
    assert "**Refund Request Created: Yes**" not in content


# write_refund_ticket leaves the document header unaffected by the
# label/value bolding fix. (happy, regression)
def test_write_refund_ticket_header_unchanged(monkeypatch, tmp_path):
    monkeypatch.setenv("CUSTOMER_SUPPORT_TICKETS_DIR", str(tmp_path))
    refund_ticket = _refund_ticket()

    path = tickets.write_refund_ticket(refund_ticket)
    content = path.read_text()

    assert content.startswith("# Refund Ticket\n")


# Two refund conversations about the same order write two separate tickets; the
# second never overwrites the first. (edge)
def test_write_refund_ticket_same_order_twice_keeps_both_files(monkeypatch, tmp_path):
    monkeypatch.setenv("CUSTOMER_SUPPORT_TICKETS_DIR", str(tmp_path))
    first = tickets.write_refund_ticket(_refund_ticket())

    second = tickets.write_refund_ticket(_refund_ticket(refund_created=False))

    assert first != second
    assert len(list(tmp_path.glob("refund-K7QP3M9X-*.md"))) == 2
    assert "**Refund Request Created:** Yes" in first.read_text()
    assert "**Refund Request Created:** No" in second.read_text()


# A blank or spaces-only issue/sentiment falls back to the same default as a missing
# one, so no ticket field is ever empty. (edge)
@pytest.mark.parametrize("blank", ["", "   "])
def test_write_refund_ticket_renders_blank_fields_as_defaults(monkeypatch, tmp_path, blank):
    monkeypatch.setenv("CUSTOMER_SUPPORT_TICKETS_DIR", str(tmp_path))
    refund_ticket = _refund_ticket(issue=blank, sentiment=blank)

    content = tickets.write_refund_ticket(refund_ticket).read_text()

    assert "**Issue:** Not recorded" in content
    assert "**Customer Sentiment:** unavailable" in content


# Chinese characters and emoji in the customer's issue reach the ticket file
# unchanged. (edge)
def test_write_refund_ticket_keeps_chinese_and_emoji(monkeypatch, tmp_path):
    monkeypatch.setenv("CUSTOMER_SUPPORT_TICKETS_DIR", str(tmp_path))
    refund_ticket = _refund_ticket(issue="My 宫保鸡丁 was missing 😊")

    content = tickets.write_refund_ticket(refund_ticket).read_text(encoding="utf-8")

    assert "**Issue:** My 宫保鸡丁 was missing 😊" in content
