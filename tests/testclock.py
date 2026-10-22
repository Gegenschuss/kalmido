"""Test clock (2.85.0, #1863): "today" in the app's time zone (Europe/Berlin), not the one of the test process.
KALMIDO_TEST_NOW (ISO instant, e.g. 2026-10-17T22:30:00Z) replaces the real time. 2.149.0 (#2512): with KALMIDO_TEST_NOW_AT
(Unix seconds, run_all.sh `now <instant>; fresh` sets both) the clock runs on from that instant like the server's (core/db.py);
without it the instant stays fixed."""
import os
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Berlin")


def now() -> datetime:
    v = os.environ.get("KALMIDO_TEST_NOW")
    if v:
        t = datetime.fromisoformat(v.replace("Z", "+00:00"))
        t = t if t.tzinfo else t.replace(tzinfo=TZ)
        at = os.environ.get("KALMIDO_TEST_NOW_AT")
        if at:
            t += datetime.now(timezone.utc) - datetime.fromtimestamp(float(at), timezone.utc)
        return t.astimezone(TZ)
    return datetime.now(timezone.utc).astimezone(TZ)


def today() -> date:
    return now().date()


def day_start() -> datetime:
    """2.180.0 B (#2693): 00:00 of today in Berlin - entries at "now - N h" start no earlier (no entry over midnight, none in last month)."""
    return datetime.combine(today(), time(0), TZ)
