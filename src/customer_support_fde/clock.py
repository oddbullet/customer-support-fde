"""Trusted current time from an NTP server, so order and refund times don't depend on
the host clock being correct."""

import time
from datetime import datetime, timezone

import ntplib

NTP_SERVER = "time.windows.com"
NTP_TIMEOUT_SECONDS = 3


class ClockUnavailableError(RuntimeError):
    pass


def trusted_now() -> datetime:
    try:
        response = ntplib.NTPClient().request(NTP_SERVER, timeout=NTP_TIMEOUT_SECONDS)
    except (ntplib.NTPException, OSError) as exc:
        raise ClockUnavailableError(f"Could not reach time server {NTP_SERVER}: {exc}") from exc
    # offset is the host clock's error as measured by the server, corrected for the
    # network round trip.
    return datetime.fromtimestamp(time.time() + response.offset, timezone.utc)
