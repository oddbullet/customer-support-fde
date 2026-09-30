import socket
from datetime import timezone

import ntplib
import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph._internal._constants import CONF, CONFIG_KEY_RUNTIME
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime

from customer_support_fde import clock
# Imported directly: conftest replaces clock.trusted_now with a local fake.
from customer_support_fde.clock import trusted_now
from customer_support_fde.nodes.common import handle_tool_error


class _FakeResponse:
    def __init__(self, offset: float):
        self.offset = offset


# trusted_now() returns an aware UTC time corrected by the NTP server's offset. (happy)
def test_trusted_now_applies_ntp_offset_and_is_utc(monkeypatch):
    monkeypatch.setattr(clock.time, "time", lambda: 1_000_000.0)
    monkeypatch.setattr(
        ntplib.NTPClient, "request", lambda self, host, **kwargs: _FakeResponse(30.0)
    )

    now = trusted_now()

    assert now.tzinfo is timezone.utc
    assert now.timestamp() == 1_000_030.0


# Any failure reaching the time server surfaces as ClockUnavailableError. (failure)
@pytest.mark.parametrize(
    "error", [ntplib.NTPException("no response"), socket.gaierror("dns"), OSError("down")]
)
def test_trusted_now_raises_clock_unavailable_on_failure(monkeypatch, error):
    def _fail(self, host, **kwargs):
        raise error

    monkeypatch.setattr(ntplib.NTPClient, "request", _fail)

    with pytest.raises(clock.ClockUnavailableError):
        trusted_now()


# A clock failure inside a tool is not turned into a "retry" tool message: it escapes
# the ToolNode so the CLI can show the generic error and exit. (failure)
def test_clock_failure_escapes_tool_node():
    @tool
    def needs_clock() -> str:
        """Needs the trusted clock."""
        raise clock.ClockUnavailableError("down")

    node = ToolNode([needs_clock], handle_tool_errors=handle_tool_error)
    call = {"name": "needs_clock", "args": {}, "id": "call_1", "type": "tool_call"}

    with pytest.raises(clock.ClockUnavailableError):
        node.invoke(
            {"messages": [AIMessage(content="", tool_calls=[call])]},
            {CONF: {CONFIG_KEY_RUNTIME: Runtime()}},
        )
