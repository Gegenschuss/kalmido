"""2.368.3 (#2985): a person's own clock. The setting "tz" (an IANA name, '' = the server's time zone) decides for that person:
when a reminder, nag, digest, briefing or review comes (a due time of "09:00" means 09:00 where they are), their quiet hours,
which day is "today" in those texts. Stored dates and times stay as they are: local to whoever reads them. "time_format" decides
how a time reads in a push ('' = 24 hours: the server does not know the browser's region)."""
from datetime import datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo, available_timezones

from .config import TZ
from .db import local_now


@lru_cache(maxsize=1)
def tz_names():
    return frozenset(available_timezones())


@lru_cache(maxsize=128)
def tz_zone(name):
    """A stored name -> ZoneInfo; '' or unknown (e.g. removed from the system's tzdata) -> the server's TZ."""
    if not name or name not in tz_names():
        return TZ
    try:
        return ZoneInfo(name)
    except (KeyError, ValueError, OSError):
        return TZ


def tz_of_s(s):
    return tz_zone((s or {}).get("tz") or "")


def user_now(s, now=None):
    """The moment now (default: this one) on the person's clock."""
    return (now or local_now()).astimezone(tz_of_s(s))


def tz_gap(S, now):
    """The largest distance between the server's clock and a person's (S: uid -> settings): how far a first look "by the
    server's clock" has to reach so that nobody's reminder is missed."""
    base = now.astimezone(TZ).utcoffset()
    gaps = [abs(now.astimezone(tz_zone(z)).utcoffset() - base) for z in {(s or {}).get("tz") or "" for s in S.values()}]
    return max(gaps, default=timedelta(0))


def hm_text(v, s):
    """A time ("14:30" or a datetime) as the person reads it: 24 hours, or "2:30 PM" with the setting 12."""
    try:
        t = v if isinstance(v, datetime) else datetime.strptime(v, "%H:%M")
    except (TypeError, ValueError):
        return v  # a stored oddity reads as it is: never a reminder lost over its text
    if (s or {}).get("time_format") != "12":
        return t.strftime("%H:%M")
    return f"{(t.hour % 12) or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"
