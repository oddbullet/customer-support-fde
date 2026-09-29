from datetime import datetime, timezone

import pytest

from customer_support_fde import db, restaurant_time


@pytest.fixture
def restaurant_in(monkeypatch):
    def _set(iana: str) -> None:
        db.set_restaurant_timezone(iana)
        monkeypatch.setattr(restaurant_time, "_timezone", None)

    return _set


# The same UTC instant shows as PDT in summer and PST in winter: daylight saving is
# handled by the zone, not a fixed offset. (base)
def test_format_local_switches_between_daylight_and_standard_time(restaurant_in):
    restaurant_in("America/Los_Angeles")

    assert restaurant_time.format_local("2026-07-01T19:05:00.000Z") == "Jul 1, 2026, 12:05 PM PDT"
    assert restaurant_time.format_local("2026-12-01T19:05:00.000Z") == "Dec 1, 2026, 11:05 AM PST"


# Arizona does not observe daylight saving, so summer and winter both show MST. (edge)
def test_format_local_arizona_has_no_daylight_saving(restaurant_in):
    restaurant_in("America/Phoenix")

    assert restaurant_time.format_local("2026-07-01T19:05:00.000Z") == "Jul 1, 2026, 12:05 PM MST"
    assert restaurant_time.format_local("2026-12-01T19:05:00.000Z") == "Dec 1, 2026, 12:05 PM MST"


# A time stored with another region's offset is shown in the restaurant's local time.
# (cross-region)
def test_format_local_converts_other_region_offset_to_restaurant_time(restaurant_in):
    restaurant_in("America/New_York")

    # 08:00 in Shanghai (+08:00) is 00:00 UTC, which is 8:00 PM the previous day in New York.
    assert (
        restaurant_time.format_local("2026-09-30T08:00:00.000+08:00")
        == "Sep 29, 2026, 8:00 PM EDT"
    )


# A datetime object is accepted as well as an ISO string. (base)
def test_format_local_accepts_datetime(restaurant_in):
    restaurant_in("America/Chicago")

    value = datetime(2026, 9, 29, 14, 3, tzinfo=timezone.utc)

    assert restaurant_time.format_local(value) == "Sep 29, 2026, 9:03 AM CDT"


# Unusable values show "unknown" instead of raising. (negative)
@pytest.mark.parametrize("value", [None, "", "not-a-date", "2026-09-29T14:03:00"])
def test_format_local_unusable_value_is_unknown(restaurant_in, value):
    restaurant_in("America/Los_Angeles")

    assert restaurant_time.format_local(value) == "unknown"


# Every supported US zone name maps to a real IANA timezone. (base)
def test_us_timezones_cover_main_us_zones():
    assert set(restaurant_time.US_TIMEZONES) == {
        "eastern", "central", "mountain", "arizona", "pacific", "alaska", "hawaii"
    }


# The timezone is read from the database once and then cached. (base)
def test_load_reads_database_once(restaurant_in, monkeypatch):
    restaurant_in("America/Denver")
    calls = {"n": 0}
    real_get = db.get_restaurant_timezone

    def _counting_get(*args, **kwargs):
        calls["n"] += 1
        return real_get(*args, **kwargs)

    monkeypatch.setattr(db, "get_restaurant_timezone", _counting_get)

    restaurant_time.load()
    restaurant_time.format_local("2026-09-29T14:03:00.000Z")
    restaurant_time.format_local("2026-09-29T15:03:00.000Z")

    assert calls["n"] == 1


# No timezone configured, or one outside the supported list, raises with the fix. (error)
@pytest.mark.parametrize("stored", [None, "Europe/London"])
def test_load_without_valid_timezone_raises_with_fix(monkeypatch, stored):
    monkeypatch.setattr(restaurant_time, "_timezone", None)
    monkeypatch.setattr(db, "get_restaurant_timezone", lambda *a, **k: stored)

    with pytest.raises(restaurant_time.RestaurantTimezoneError, match="--set-tz"):
        restaurant_time.load()


# A database without the settings table (created before this feature) points to the
# fix instead of crashing. (error)
def test_load_on_old_database_raises_with_fix(monkeypatch):
    def _store_error(*args, **kwargs):
        raise db.OrderStoreError("no such table: restaurant_settings")

    monkeypatch.setattr(restaurant_time, "_timezone", None)
    monkeypatch.setattr(db, "get_restaurant_timezone", _store_error)

    with pytest.raises(restaurant_time.RestaurantTimezoneError, match="--init-db"):
        restaurant_time.load()
