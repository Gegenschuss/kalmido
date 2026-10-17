"""Test clock (2.85.0, #1863): "today" in the app's time zone (Europe/Berlin), not the one of the test process.
KALMIDO_TEST_NOW (ISO instant, e.g. 2026-10-17T22:30:00Z) replaces the real time."""
import os
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Berlin")


def now() -> datetime:
    v = os.environ.get("KALMIDO_TEST_NOW")
    if v:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(TZ)
    return datetime.now(timezone.utc).astimezone(TZ)


def today() -> date:
    return now().date()
