"""Large complaint and issue texts are stored and ticketed in full.

The CLI refuses customer lines over 1,000 characters, but the model writes the tool
arguments itself, so a complaint or issue can reach the tools longer than that."""

from customer_support_fde import db, tickets
from customer_support_fde.tools.refund_tools import (
    UndeliveredItem,
    log_complaint,
    process_refund_request,
)

from conftest import seed_order

# Ten times the CLI cap, with a unique ending so any truncation shows up.
LARGE_TEXT = "My dumplings were cold and the soup was missing. " * 200 + "END-OF-COMPLAINT"


def _old_order(refund_db) -> dict:
    order_id = seed_order(
        refund_db,
        [{"name": "Mapo Tofu", "quantity": 1, "unit_price": 10.0, "line_total": 10.0}],
        age_hours=49,
    )
    return db.get_order(order_id, refund_db)


# A very long complaint is stored exactly, not truncated. (edge)
def test_log_complaint_stores_large_description_in_full(refund_db, monkeypatch):
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(refund_db))

    log_complaint.func(
        description=LARGE_TEXT,
        state={"order_lookup": None, "complaint_ids": {}},
        tool_call_id="call_1",
    )

    complaints = db.list_complaints(refund_db)
    assert [c["description"] for c in complaints] == [LARGE_TEXT]


# A denied refund with a very long issue stores the whole issue on its complaint. (edge)
def test_process_refund_request_denial_stores_large_issue_in_full(refund_db, monkeypatch):
    monkeypatch.setenv("CUSTOMER_SUPPORT_DB", str(refund_db))
    order = _old_order(refund_db)

    process_refund_request.func(
        undelivered_items=[UndeliveredItem(name="Mapo Tofu", quantity=1)],
        substitute_dishes=[],
        return_confirmed=False,
        customer_issue=LARGE_TEXT,
        state={"order_lookup": order, "complaint_ids": {}},
        tool_call_id="call_1",
    )

    complaints = db.list_complaints(refund_db)
    assert [c["description"] for c in complaints] == [LARGE_TEXT]


# A very long issue reaches the refund ticket file in full. (edge)
def test_write_refund_ticket_keeps_large_issue_in_full(monkeypatch, tmp_path):
    monkeypatch.setenv("CUSTOMER_SUPPORT_TICKETS_DIR", str(tmp_path))
    refund_ticket = {
        "order_id": "K7QP3M9X",
        "order": {"order_id": "K7QP3M9X", "total": 10.0, "lines": []},
        "sentiment": "negative",
        "decision": None,
        "refund_request": None,
        "complaint_ids": [],
        "issue": LARGE_TEXT,
        "refund_created": False,
    }

    content = tickets.write_refund_ticket(refund_ticket).read_text(encoding="utf-8")

    assert f"**Issue:** {LARGE_TEXT}\n" in content
