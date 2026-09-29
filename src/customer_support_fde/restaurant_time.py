"""The restaurant's timezone, loaded once from the database, for showing times to people.

Times are stored and compared in UTC; they are only converted here, for display.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from customer_support_fde import db

# IANA names rather than fixed offsets, so daylight saving (e.g. EST ↔ EDT) is automatic.
US_TIMEZONES = {
    "eastern": "America/New_York",
    "central": "America/Chicago",
    "mountain": "America/Denver",
    "arizona": "America/Phoenix",
    "pacific": "America/Los_Angeles",
    "alaska": "America/Anchorage",
    "hawaii": "Pacific/Honolulu",
}

_FIX = "Run: uv run start --set-tz <" + "|".join(US_TIMEZONES) + ">"

_timezone: ZoneInfo | None = None


class RestaurantTimezoneError(RuntimeError):
    pass


def load() -> ZoneInfo:
    global _timezone
    try:
        name = db.get_restaurant_timezone()
    except db.OrderStoreError as exc:
        raise RestaurantTimezoneError(
            f"Restaurant timezone can't be read. Run: uv run start --init-db, then {_FIX}"
        ) from exc
    if name not in US_TIMEZONES.values():
        raise RestaurantTimezoneError(f"Restaurant timezone is not set. {_FIX}")
    _timezone = ZoneInfo(name)
    return _timezone


def format_local(value: datetime | str | None) -> str:
    try:
        moment = datetime.fromisoformat(value) if isinstance(value, str) else value
        if moment is None or moment.tzinfo is None:
            return "unknown"
    except ValueError:
        return "unknown"
    local = moment.astimezone(_timezone or load())
    return f"{local:%b} {local.day}, {local:%Y}, {local.hour % 12 or 12}:{local:%M %p %Z}"
