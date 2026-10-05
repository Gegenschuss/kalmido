"""External calendars (read-only subscriptions): SSRF guard, ICS / CalDAV sync, API."""
import base64
import functools
import hashlib
import html
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import icalendar
import recurring_ical_events
from datetime import date, datetime, timedelta, timezone
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from dateutil.rrule import rrulestr
from flask import jsonify, request

from ..core.config import _origin, app, APP_NAME, APP_VERSION, TZ
from ..core.i18n import lang, N_, tr
from ..core.db import body, connect, db, err, gsetting, iso, iso_ms, local_now, now_utc, parse_iso
from ..accounts.session import FAIL_WINDOW, GATE, me
from ..core.access import Denied
from ..tasks.validation import RR_FREQS, RR_PROBE_DAYS
from ..personal.timetrack import BadInput
from ..calendars.caldav import _DtdRefused, xml_no_dtd
from ..notify.push import _b64u, _b64u_dec
from ..notify.alerts import _env_int, aa_count, aa_now


# ---------------------------------------------------------------- external calendars (read-only subscriptions)
# Per user, private (never shared with list members): ICS / iCal links (Google "secret address in iCal format",
# iCloud public links, Outlook, any .ics) or CalDAV calendars (discovered via current-user-principal ->
# calendar-home-set -> the calendars of that home). A background thread fetches each subscription every 15 or
# 60 minutes, expands recurrences (RRULE, RDATE, EXDATE, RECURRENCE-ID overrides, time zones) in a window of
# CAL_BACK_DAYS back and CAL_AHEAD_DAYS ahead and stores the occurrences in cal_events; the client asks only for
# the range it shows (GET /api/calendars/events), not via /api/state. Events are read-only: nothing is ever
# written back to a calendar.
# Outbound requests (cal_http): http(s) only, no proxy from the environment, time-outs, a size limit, redirects
# followed by hand, and an SSRF guard AT CONNECT TIME: every address the host name resolves to must be public
# (not private, loopback, link-local, CGNAT, multicast, reserved, ... also inside IPv4-mapped / NAT64 / 6to4
# IPv6), and the socket connects to exactly the address that was checked (no DNS rebinding) while TLS still
# verifies the host name (SNI). Hosts on the admin allow-list (Settings > Users > Whole server, env
# KALMIDO_CALENDAR_ALLOW_HOSTS) may be internal. Credentials only ever go to the host they were entered for.
# The ICS link (itself a secret) and the CalDAV password are stored encrypted (AES-GCM, key derived from a random
# server secret in the settings table) and are never sent back to the client, nor logged.
CAL_ON = os.environ.get("KALMIDO_CALENDARS", "1").strip().lower() not in ("0", "false", "no", "off")
CAL_ALLOW_ENV = os.environ.get("KALMIDO_CALENDAR_ALLOW_HOSTS", "")
CAL_MAX_BYTES = _env_int("KALMIDO_CALENDAR_MAX_MB", 10) * 1024 * 1024  # per download (ICS file / CalDAV answer)
CAL_MAX_EVENTS = _env_int("KALMIDO_CALENDAR_MAX_EVENTS", 5000)        # stored occurrences per subscription
CAL_TICK = _env_int("KALMIDO_CALENDAR_TICK", 60)                      # seconds per "minute" of the interval (tests: 1)
CAL_REFRESH_GAP = _env_int("KALMIDO_CALENDAR_REFRESH_GAP", 30, lo=0)  # s between two manual refreshes of one calendar
CAL_BACK_DAYS, CAL_AHEAD_DAYS = 60, 365
CAL_MAX_COMPONENTS = 20000   # VEVENTs per download
CAL_CPU_S = 20.0             # parse + expansion budget per sync
CAL_TIMEOUT, CAL_DEADLINE = 20, 60  # s per socket operation / for a whole download
CAL_MAX_SUBS = 20            # per user
CAL_INTERVALS = (15, 60)     # minutes
CAL_ALERT_FAILS = 5          # failed syncs in a row -> admin alert ("integration")
CAL_NET_LIMIT = _env_int("KALMIDO_CALENDAR_RATE", 30)  # adds / discoveries / manual refreshes per user within FAIL_WINDOW (15 min)
CAL_COLORS = ("#6d8cff", "#2dd4bf", "#f5b041", "#f87171", "#c084fc", "#4ade80", "#f472b6", "#94a3b8", "#6ee7b7")
CAL_TEXT = {"title": 300, "location": 300, "description": 4000}
CAL_ERR = {"blocked": N_("This address is in a private network. An admin can allow the host under Settings > Administration > Advanced."),
           "auth": N_("Access denied: wrong username or password, or the link needs a login"),
           "not_found": N_("Not found: check the link"),
           "http": N_("The server answered with an error ({0})"),
           "too_large": N_("The calendar is larger than {0} MB"),
           "timeout": N_("The server did not answer in time"),
           "network": N_("The server is not reachable"),
           "tls": N_("Secure connection failed (certificate)"),
           "redirect": N_("The server redirects to another address, which is not followed"),
           "parse": N_("Not a valid calendar file"),
           "not_calendar": N_("No calendar found at this address"),
           "no_calendars": N_("No calendars with events found in this account"),
           "too_complex": N_("The calendar is too complex to process"),
           "config": N_("Invalid link"),
           "error": N_("Unexpected error")}
DAV_NS, CALDAV_NS, CS_NS, ICAL_NS = "DAV:", "urn:ietf:params:xml:ns:caldav", "http://calendarserver.org/ns/", "http://apple.com/ns/ical/"
_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_CAL_HOST_RE = re.compile(r"(?:[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9])?\.)*[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9])?\.?")


class CalError(Exception):
    """A sync / discovery failure: code (a CAL_ERR key) + a short detail (an HTTP status); never content."""
    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code, self.detail = code, str(detail)[:20]

    def stored(self):
        return self.code + (":" + self.detail if self.detail else "")


def cal_err_text(stored):
    code, _, detail = (stored or "error").partition(":")
    if code == "http":
        return tr(CAL_ERR["http"], detail or "?")
    if code == "too_large":
        return tr(CAL_ERR["too_large"], CAL_MAX_BYTES // (1024 * 1024))
    return tr(CAL_ERR.get(code, CAL_ERR["error"]))


# ---- SSRF guard
def cal_ip_public(ip):
    """True only for a globally routable unicast address (IPv4-mapped / NAT64 / 6to4 IPv6 are checked as the IPv4
    address inside; Teredo is refused)."""
    try:
        ip = ipaddress.ip_address(str(ip).split("%", 1)[0])
    except ValueError:
        return False
    if ip.version == 6:
        if ip.ipv4_mapped:
            return cal_ip_public(ip.ipv4_mapped)
        if ip in _NAT64:
            return cal_ip_public(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
        if ip.sixtofour:
            return cal_ip_public(ip.sixtofour)
        if ip.teredo:
            return False
    if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified
            or (ip.version == 4 and ip in _CGNAT)):
        return False
    return ip.is_global


def cal_allow_parse(s):
    """'host, host:port, [v6]:port ...' -> ([(host, port or None)], [invalid entries])."""
    out, bad = [], []
    for part in re.split(r"[\s,;]+", str(s or "")):
        p = part.strip().lower()
        if not p:
            continue
        m = re.fullmatch(r"(\[[0-9a-f:.]+\]|[^:\[\]/]+)(?::(\d{1,5}))?", p)
        host = m.group(1).strip("[]") if m else ""
        port = int(m.group(2)) if m and m.group(2) else None
        ok = bool(m) and len(p) <= 260 and (port is None or 1 <= port <= 65535)
        if ok:
            try:
                ipaddress.ip_address(host)
            except ValueError:
                ok = bool(_CAL_HOST_RE.fullmatch(host)) and not m.group(1).startswith("[")
        if ok:
            out.append((host.rstrip("."), port))
        else:
            bad.append(part.strip()[:80])
    return out, bad


def cal_allow_text(entries):
    return ", ".join((f"[{h}]" if ":" in h else h) + (f":{p}" if p else "") for h, p in entries)


def cal_allow(c):
    """Hosts that may be internal: env KALMIDO_CALENDAR_ALLOW_HOSTS + the admin setting."""
    return frozenset(cal_allow_parse(CAL_ALLOW_ENV)[0] + cal_allow_parse(gsetting(c, "cal_allow_hosts"))[0])


def cal_host_allowed(allow, host, port):
    h = str(host or "").lower().strip("[]").rstrip(".")
    return (h, None) in allow or (h, port) in allow


def _cal_connector(allow):
    """socket.create_connection replacement: resolve, check every address, connect to a checked one."""
    def create(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, *a, **k):  # noqa: ARG001
        host, port = address
        trusted = cal_host_allowed(allow, host, port)
        try:
            infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
        except (socket.gaierror, UnicodeError) as e:
            raise CalError("network") from e
        fail = None
        for fam, typ, proto, _, sa in infos:
            if not trusted and not cal_ip_public(sa[0]):
                fail = fail or CalError("blocked")
                continue
            s = socket.socket(fam, typ, proto)
            try:
                if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                    s.settimeout(timeout)
                s.connect(sa)  # exactly the checked address
                return s
            except OSError as e:
                s.close()
                fail = e
        raise fail or CalError("network")
    return create


class _CalHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *a, cal_allow=frozenset(), **k):
        super().__init__(*a, **k)
        self._create_connection = _cal_connector(cal_allow)


class _CalHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *a, cal_allow=frozenset(), **k):
        super().__init__(*a, **k)
        self._create_connection = _cal_connector(cal_allow)  # then TLS with server_hostname = the host name


class _CalHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, allow):
        super().__init__()
        self._allow = allow

    def http_open(self, req):
        return self.do_open(functools.partial(_CalHTTPConnection, cal_allow=self._allow), req)


class _CalHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, allow):
        super().__init__(context=ssl.create_default_context())
        self._allow = allow

    def https_open(self, req):
        return self.do_open(functools.partial(_CalHTTPSConnection, cal_allow=self._allow), req, context=self._context)


def _cal_opener(allow):
    """No proxy handler (the environment's proxies are ignored), no redirect handler (cal_http follows by hand)."""
    o = urllib.request.OpenerDirector()
    for h in (_CalHTTPHandler(allow), _CalHTTPSHandler(allow), urllib.request.HTTPDefaultErrorHandler(),
              urllib.request.HTTPErrorProcessor()):
        o.add_handler(h)
    return o


def cal_norm_url(u):
    """A subscription / server URL as https?://... (webcal:// and webcals:// become https://), or None."""
    u = str(u or "").strip()
    if not u or len(u) > 2000 or any(ch.isspace() or ord(ch) < 32 for ch in u):
        return None
    low = u.lower()
    if low.startswith("webcals://"):
        u = "https://" + u[10:]
    elif low.startswith("webcal://"):
        u = "https://" + u[9:]
    p = urllib.parse.urlsplit(u)
    try:
        p.port
    except ValueError:
        return None
    if p.scheme.lower() not in ("http", "https") or not p.hostname or p.username or p.password:
        return None
    return u


def cal_url_hint(u):
    """What the client sees of a stored link: scheme://host[:port]/… (the path / token stays secret)."""
    p = urllib.parse.urlsplit(u or "")
    try:
        port = f":{p.port}" if p.port else ""
    except ValueError:
        port = ""
    host = p.hostname or "?"
    return f"{p.scheme}://{'[' + host + ']' if ':' in host else host}{port}/…"


CAL_UA = f"{APP_NAME}/{APP_VERSION} (calendar subscription)"


def cal_http(url, method="GET", body=None, headers=None, auth=None, allow=frozenset(), cross_redirects=False):
    """One request, redirects followed by hand (at most 5; never https -> http). Returns (status, headers, body,
    final url). auth = (user, password): Basic auth, only ever sent to the host of `url`; a redirect to another
    host is only followed without credentials (cross_redirects, https only). Every hop runs through the SSRF guard."""
    first = (urllib.parse.urlsplit(url).hostname or "").lower()
    op = _cal_opener(allow)
    deadline = time.monotonic() + CAL_DEADLINE
    for _hop in range(6):
        p = urllib.parse.urlsplit(url)
        if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
            raise CalError("config")
        hd = {"User-Agent": CAL_UA, "Accept": "text/calendar, application/xml, text/xml, */*;q=0.5", **(headers or {})}
        if auth and p.hostname.lower() == first:
            hd["Authorization"] = "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req = urllib.request.Request(url, data=body, method=method, headers=hd)
        try:
            r = op.open(req, timeout=CAL_TIMEOUT)
        except urllib.error.HTTPError as e:
            loc, code = (e.headers.get("Location") if e.headers else None), e.code
            hdrs = e.headers
            e.close()
            if code in (301, 302, 303, 307, 308) and loc:
                new = urllib.parse.urljoin(url, loc.strip())
                q = urllib.parse.urlsplit(new)
                same = (q.hostname or "").lower() == p.hostname.lower()
                if q.scheme not in ("http", "https") or (p.scheme == "https" and q.scheme != "https") or \
                        (not same and not (cross_redirects and not auth and q.scheme == "https")):
                    raise CalError("redirect") from None
                if code == 303:
                    method, body = "GET", None
                url = new
                continue
            if code == 304:
                return 304, hdrs, b"", url
            if code in (401, 403):
                raise CalError("auth", code) from None
            if code in (404, 410):
                raise CalError("not_found", code) from None
            raise CalError("http", code) from None
        except CalError:
            raise
        except urllib.error.URLError as e:
            rs = e.reason
            if isinstance(rs, CalError):
                raise rs from None
            if isinstance(rs, ssl.SSLError):
                raise CalError("tls") from None
            if isinstance(rs, (TimeoutError, socket.timeout)):
                raise CalError("timeout") from None
            raise CalError("network") from None
        except ssl.SSLError:
            raise CalError("tls") from None
        except (TimeoutError, socket.timeout):
            raise CalError("timeout") from None
        except (OSError, http.client.HTTPException, ValueError):
            raise CalError("network") from None
        try:
            with r:
                cl = r.headers.get("Content-Length") or ""
                if cl.isdigit() and int(cl) > CAL_MAX_BYTES:
                    raise CalError("too_large")
                chunks, n = [], 0
                while True:
                    if time.monotonic() > deadline:
                        raise CalError("timeout")
                    b = r.read(65536)
                    if not b:
                        break
                    n += len(b)
                    if n > CAL_MAX_BYTES:
                        raise CalError("too_large")
                    chunks.append(b)
                return r.status, r.headers, b"".join(chunks), url
        except CalError:
            raise
        except (TimeoutError, socket.timeout):
            raise CalError("timeout") from None
        except (OSError, http.client.HTTPException, ValueError):
            raise CalError("network") from None
    raise CalError("redirect")


# ---- secrets at rest
_CAL_KEY = {}


def cal_key(c):
    if "k" not in _CAL_KEY:
        _CAL_KEY["k"] = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"kalmido-calendars",
                             info=b"subscription secrets v1").derive(bytes.fromhex(gsetting(c, "cal_secret")))
    return _CAL_KEY["k"]


def cal_seal(c, uid, s):
    if not s:
        return ""
    n = os.urandom(12)
    return "v1." + _b64u(n + AESGCM(cal_key(c)).encrypt(n, s.encode(), f"kalmido-cal:{uid}".encode()))


def cal_unseal(c, uid, s):
    if not s:
        return ""
    raw = _b64u_dec(s[3:])
    return AESGCM(cal_key(c)).decrypt(raw[:12], raw[12:], f"kalmido-cal:{uid}".encode()).decode()


# ---- parsing + expansion
def _cal_clean(v, n):
    if isinstance(v, list):
        v = v[0] if v else ""
    s = str(v if v is not None else "")
    s = re.sub("[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f\\x7f\\u202a-\\u202e\\u2066-\\u2069]", "", s.replace("\r\n", "\n").replace("\r", "\n"))
    return s.strip()[:n]


def _cal_plain(v, n):
    """DESCRIPTION as plain text: some calendars (Google) put HTML there; tags go, entities are decoded. The client
    escapes everything anyway (and only links http / https URLs)."""
    s = _cal_clean(v, 20000)
    if re.search(r"<[a-zA-Z/!]", s):
        s = re.sub(r"(?i)<br\s*/?>|</p\s*>|</div\s*>|</li\s*>", "\n", s)
        s = re.sub(r"(?s)<!--.*?-->|<[^>]{0,2000}>", "", s)
        s = html.unescape(s)
        s = re.sub(r"\n{3,}", "\n\n", s)
    return _cal_clean(s, n)


@functools.lru_cache(maxsize=4096)
def _cal_feasible(base, start):
    """The rule (without COUNT / UNTIL) has a date within RR_PROBE_DAYS of start (see rr_feasible: the probe runs
    400-year cycles later, so a rule that never matches costs a fraction of a second)."""
    try:
        k = max(0, (9800 - start.year) // 400)
        st = start.replace(year=start.year + 400 * k)
        nxt = rrulestr(base, dtstart=st, ignoretz=True).after(st, inc=True)
    except (ValueError, TypeError, OverflowError, KeyError, IndexError):
        return False
    return bool(nxt) and (nxt - st).days <= RR_PROBE_DAYS


def _cal_sanitize(ev, w0):
    """Makes a VEVENT safe to expand (False = drop it). Rules the app cannot expand cheaply lose their recurrence
    (the first occurrence stays): anything below daily (SECONDLY / MINUTELY / HOURLY, BYHOUR / BYMINUTE /
    BYSECOND), a rule that never matches, COUNT above 10000. An open-ended rule starting long before the window
    starts later by whole periods (same dates inside the window), so dateutil does not walk through centuries."""
    rr = ev.get("RRULE")
    if rr is None:
        return True
    try:
        st = ev.decoded("DTSTART")
    except (KeyError, ValueError, TypeError):
        return False
    if not isinstance(st, date):
        return False
    naive = st.replace(tzinfo=None) if isinstance(st, datetime) else datetime(st.year, st.month, st.day)
    keep = []
    for r in (rr if isinstance(rr, list) else [rr]):
        try:
            txt = r.to_ical().decode()
        except (AttributeError, ValueError, TypeError):
            continue
        parts = {}
        for p in txt.split(";"):
            k, _, v = p.partition("=")
            parts[k.strip().upper()] = v.strip()
        freq = parts.get("FREQ", "").upper()
        if len(txt) > 500 or freq not in RR_FREQS or any(k in parts for k in ("BYSECOND", "BYMINUTE", "BYHOUR")):
            continue
        if not re.fullmatch(r"\d{1,4}", parts.get("INTERVAL", "1")) or not 1 <= int(parts.get("INTERVAL", "1")) <= 1000:
            continue
        if "COUNT" in parts and (not parts["COUNT"].isdigit() or int(parts["COUNT"]) > 10000):
            parts.pop("COUNT")
        base = ";".join(f"{k}={v}" for k, v in parts.items() if k not in ("COUNT", "UNTIL"))
        if not _cal_feasible(base, naive):
            continue
        keep.append(parts)
    del ev["RRULE"]
    for parts in keep:
        ev.add("RRULE", icalendar.vRecur.from_ical(";".join(f"{k}={v}" for k, v in parts.items())))
    if len(keep) == 1 and "COUNT" not in keep[0]:
        freq, n = keep[0]["FREQ"], int(keep[0].get("INTERVAL", "1"))
        gap = (w0.date() - naive.date()).days - 7
        if freq in ("DAILY", "WEEKLY"):
            step = n * (7 if freq == "WEEKLY" else 1)
            shift = gap // step * step if gap > 400 else 0
        else:  # whole 400-year cycles: the Gregorian calendar repeats exactly (weekdays included)
            ok = (4800 % n == 0) if freq == "MONTHLY" else (400 % n == 0)
            shift = gap // 146097 * 146097 if ok and gap > 146097 else 0
        if shift > 0:
            for key in ("DTSTART", "DTEND"):
                prop = ev.get(key)
                if prop is not None and hasattr(prop, "dt"):
                    prop.dt = prop.dt + timedelta(days=shift)
    return True


def _cal_occ(occ):
    """One expanded occurrence -> a cal_events row (dict), or None (cancelled / unusable)."""
    comp = occ.as_component(False)
    if str(comp.get("STATUS", "")).upper() == "CANCELLED":
        return None
    st, en = occ.start, occ.end
    ev = {"uid": _cal_clean(comp.get("UID"), 300), "title": _cal_clean(comp.get("SUMMARY"), CAL_TEXT["title"]),
          "location": _cal_clean(comp.get("LOCATION"), CAL_TEXT["location"]),
          "description": _cal_plain(comp.get("DESCRIPTION"), CAL_TEXT["description"])}
    if not isinstance(st, datetime):  # all-day: dates, end exclusive
        e = en.date() if isinstance(en, datetime) else en if isinstance(en, date) else None
        if not e or e <= st:
            e = st + timedelta(days=1)
        t = datetime(st.year, st.month, st.day, tzinfo=TZ).timestamp()
        return {**ev, "all_day": 1, "start": st.isoformat(), "end": e.isoformat(), "d0": st.isoformat(),
                "d1": (e - timedelta(days=1)).isoformat(), "t": t}
    if st.tzinfo is None:  # floating time: the server's time zone
        st = st.replace(tzinfo=TZ)
    if isinstance(en, datetime):
        en = en if en.tzinfo else en.replace(tzinfo=TZ)
    else:
        en = st
    if en < st:
        en = st
    d0 = st.astimezone(TZ).date()
    d1 = (en - timedelta(microseconds=1)).astimezone(TZ).date() if en > st else d0
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return {**ev, "all_day": 0, "start": st.astimezone(timezone.utc).strftime(fmt), "end": en.astimezone(timezone.utc).strftime(fmt),
            "d0": d0.isoformat(), "d1": max(d0, d1).isoformat(), "t": st.timestamp()}


def cal_expand(raws):
    """ICS texts (one file, or the calendar-data of CalDAV resources) -> (events sorted by start, truncated, name).
    At most CAL_MAX_EVENTS occurrences (the ones closest to today), within CAL_CPU_S."""
    t0 = time.monotonic()
    today = local_now().date()
    w0 = datetime.combine(today - timedelta(days=CAL_BACK_DAYS), datetime.min.time())
    w1 = datetime.combine(today + timedelta(days=CAL_AHEAD_DAYS + 1), datetime.min.time())
    merged, tzids, n, found, name = icalendar.Calendar(), set(), 0, False, ""
    for raw in raws:
        if isinstance(raw, str):
            raw = raw.encode("utf-8", "replace")
        if b"BEGIN:VCALENDAR" not in raw.upper():
            continue
        try:
            cals = icalendar.Calendar.from_ical(raw, multiple=True)
        except Exception:  # noqa: BLE001  (icalendar raises ValueError / KeyError / IndexError / ... on bad input)
            raise CalError("parse") from None
        for cal in cals:
            if getattr(cal, "name", "") != "VCALENDAR":
                continue
            found = True
            if not name:
                name = _cal_clean(cal.get("X-WR-CALNAME"), 100)
            if "X-WR-TIMEZONE" in cal and "X-WR-TIMEZONE" not in merged:
                merged["X-WR-TIMEZONE"] = cal["X-WR-TIMEZONE"]
            for comp in cal.subcomponents:
                if comp.name == "VTIMEZONE":
                    tzid = str(comp.get("TZID", ""))
                    if tzid not in tzids:
                        tzids.add(tzid)
                        merged.add_component(comp)
                elif comp.name == "VEVENT":
                    n += 1
                    if n > CAL_MAX_COMPONENTS or time.monotonic() - t0 > CAL_CPU_S:
                        raise CalError("too_complex")
                    if _cal_sanitize(comp, w0):
                        merged.add_component(comp)
    if not found:
        raise CalError("not_calendar")
    try:
        q = recurring_ical_events.of(merged, skip_bad_series=True)
    except Exception:  # noqa: BLE001
        raise CalError("parse") from None
    out, seen, truncated = [], set(), False
    for series in q.series:
        try:
            for occ in series.between(w0, w1):
                ev = _cal_occ(occ)
                if not ev or (ev["uid"], ev["start"]) in seen:
                    continue
                seen.add((ev["uid"], ev["start"]))
                out.append(ev)
                if len(out) >= 4 * CAL_MAX_EVENTS or time.monotonic() - t0 > CAL_CPU_S:
                    truncated = True
                    break
        except CalError:
            raise
        except Exception:  # noqa: BLE001  (one broken series never breaks the calendar)
            continue
        if truncated:
            break
    if len(out) > CAL_MAX_EVENTS:
        truncated, now = True, time.time()
        out.sort(key=lambda e: abs(e["t"] - now))
        out = out[:CAL_MAX_EVENTS]
    out.sort(key=lambda e: (e["start"], e["title"]))
    return out, truncated, name


# ---- CalDAV
def _dav_xml(data):
    try:  # no DTDs / entities (XXE, entity expansion), in any encoding
        return xml_no_dtd(data)
    except (_DtdRefused, ET.ParseError):
        raise CalError("parse") from None


def _dav_responses(root, base):
    """[(absolute href, {tag: element})] with the properties of the 200 propstats of a multistatus."""
    out = []
    for r in root.findall(f"{{{DAV_NS}}}response"):
        href = (r.findtext(f"{{{DAV_NS}}}href") or "").strip()
        props = {}
        for ps in r.findall(f"{{{DAV_NS}}}propstat"):
            if " 200" not in (ps.findtext(f"{{{DAV_NS}}}status") or ""):
                continue
            prop = ps.find(f"{{{DAV_NS}}}prop")
            for el in (list(prop) if prop is not None else []):
                props[el.tag] = el
        out.append((urllib.parse.urljoin(base, href) if href else base, props))
    return out


def _dav_href(el, base):
    h = el.findtext(f"{{{DAV_NS}}}href") if el is not None else None
    return urllib.parse.urljoin(base, h.strip()) if h and h.strip() else None


def cal_href_ok(base, url):
    """A URL a CalDAV server pointed to may get the credentials: same origin, or (https only) the same parent
    domain, e.g. caldav.icloud.com -> p52-caldav.icloud.com."""
    a, b = _origin(base), _origin(url)
    if not a or not b:
        return False
    if a == b:
        return True
    if a[0] != "https" or b[0] != "https":
        return False
    try:
        ipaddress.ip_address(a[1])
        return False
    except ValueError:
        pass
    pa, pb = a[1].rstrip(".").split("."), b[1].rstrip(".").split(".")
    return len(pa) >= 2 and len(pb) >= 2 and pa[-2:] == pb[-2:]


def dav_propfind(url, depth, props, auth, allow):
    body = ('<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav" '
            'xmlns:cs="http://calendarserver.org/ns/" xmlns:a="http://apple.com/ns/ical/"><d:prop>' + props + '</d:prop></d:propfind>')
    st, _, data, final = cal_http(url, "PROPFIND", body.encode(), {"Depth": str(depth), "Content-Type": "application/xml; charset=utf-8"},
                                  auth, allow)
    if st != 207:
        raise CalError("not_calendar")
    return final, _dav_responses(_dav_xml(data), final)


def _dav_is_cal(props):
    rt = props.get(f"{{{DAV_NS}}}resourcetype")
    return rt is not None and rt.find(f"{{{CALDAV_NS}}}calendar") is not None


def _dav_events_ok(props):
    cs = props.get(f"{{{CALDAV_NS}}}supported-calendar-component-set")
    names = {(x.get("name") or "").upper() for x in (list(cs) if cs is not None else [])}
    return not names or "VEVENT" in names


def _dav_cal(url, props):
    col = props.get(f"{{{ICAL_NS}}}calendar-color")
    m = re.fullmatch(r"#([0-9a-fA-F]{6})(?:[0-9a-fA-F]{2})?", (col.text or "").strip() if col is not None else "")
    dn = props.get(f"{{{DAV_NS}}}displayname")
    name = _cal_clean(dn.text if dn is not None else "", 100) or urllib.parse.unquote(urllib.parse.urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1])[:100]
    return {"url": url, "name": name or tr("Calendar"), "color": ("#" + m.group(1).lower()) if m else ""}


def caldav_discover(url, auth, allow):
    """The event calendars of a CalDAV account (the URL may be the server, the principal or one calendar)."""
    cup, home = None, None
    o = _origin(url)
    root = f"{o[0]}://{'[' + o[1] + ']' if ':' in o[1] else o[1]}:{o[2]}" if o else url
    for cand in dict.fromkeys((url, root + "/.well-known/caldav")):
        try:
            final, rs = dav_propfind(cand, 0, "<d:current-user-principal/><d:resourcetype/><d:displayname/>"
                                              "<c:calendar-home-set/><a:calendar-color/><c:supported-calendar-component-set/>", auth, allow)
        except CalError as e:
            if e.code in ("auth", "blocked", "tls", "timeout", "too_large"):
                raise
            continue
        if not rs:
            continue
        href, props = rs[0]
        if _dav_is_cal(props):
            if not _dav_events_ok(props):
                raise CalError("no_calendars")
            return [_dav_cal(href, props)]
        home = _dav_href(props.get(f"{{{CALDAV_NS}}}calendar-home-set"), final)
        cup = _dav_href(props.get(f"{{{DAV_NS}}}current-user-principal"), final)
        if home or cup:
            break
    if not home and cup:
        if not cal_href_ok(url, cup):
            raise CalError("redirect")
        final, rs = dav_propfind(cup, 0, "<c:calendar-home-set/>", auth, allow)
        home = _dav_href(rs[0][1].get(f"{{{CALDAV_NS}}}calendar-home-set"), final) if rs else None
    if not home:
        raise CalError("not_calendar")
    if not cal_href_ok(url, home):
        raise CalError("redirect")
    final, rs = dav_propfind(home, 1, "<d:resourcetype/><d:displayname/><a:calendar-color/><c:supported-calendar-component-set/>",
                             auth, allow)
    cals = [_dav_cal(h, p) for h, p in rs if _dav_is_cal(p) and _dav_events_ok(p) and cal_href_ok(url, h)]
    if not cals:
        raise CalError("no_calendars")
    return cals[:50]


def caldav_tag(url, auth, allow):
    """getctag / sync-token of a calendar ('' when the server has neither): unchanged = nothing to fetch."""
    try:
        _, rs = dav_propfind(url, 0, "<cs:getctag/><d:sync-token/>", auth, allow)
    except CalError as e:
        if e.code in ("not_calendar", "parse"):
            return ""
        raise
    if not rs:
        return ""
    p = rs[0][1]
    for tag in (f"{{{CS_NS}}}getctag", f"{{{DAV_NS}}}sync-token"):
        if p.get(tag) is not None and (p[tag].text or "").strip():
            return (p[tag].text or "").strip()[:200]
    return ""


def caldav_fetch(url, auth, allow):
    """calendar-data of every event resource that overlaps the window (REPORT calendar-query with a time range)."""
    today = local_now().date()
    a = (today - timedelta(days=CAL_BACK_DAYS + 1)).strftime("%Y%m%dT000000Z")
    b = (today + timedelta(days=CAL_AHEAD_DAYS + 2)).strftime("%Y%m%dT000000Z")
    body = ('<?xml version="1.0" encoding="utf-8"?><c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            '<d:prop><d:getetag/><c:calendar-data/></d:prop><c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
            f'<c:time-range start="{a}" end="{b}"/></c:comp-filter></c:comp-filter></c:filter></c:calendar-query>')
    st, _, data, _ = cal_http(url, "REPORT", body.encode(), {"Depth": "1", "Content-Type": "application/xml; charset=utf-8"}, auth, allow)
    if st != 207:
        raise CalError("not_calendar")
    return [el.text for el in _dav_xml(data).iter(f"{{{CALDAV_NS}}}calendar-data") if el.text and el.text.strip()]


# ---- sync
_CAL_LOCK = threading.Lock()
_CAL_BUSY = set()
CAL_EV_COLS = ("uid", "title", "location", "description", "all_day", "start", "end", "d0", "d1")


def cal_store(c, sid, evs, truncated):
    """Replaces the stored occurrences when they changed (ids stay stable otherwise). True = changed."""
    dig = hashlib.sha256(json.dumps([[e[k] for k in CAL_EV_COLS] for e in evs], ensure_ascii=False).encode()).hexdigest()
    old = c.execute("SELECT digest FROM cal_subs WHERE id=?", (sid,)).fetchone()
    if old and old[0] == dig:
        return False
    c.execute("DELETE FROM cal_events WHERE sub_id=?", (sid,))
    c.executemany(f"INSERT INTO cal_events(sub_id,{','.join(CAL_EV_COLS)}) VALUES(?,{','.join('?' * len(CAL_EV_COLS))})",
                  [(sid, *[e[k] for k in CAL_EV_COLS]) for e in evs])
    c.execute("UPDATE cal_subs SET digest=?, events=?, truncated=?, changed_at=? WHERE id=?",
              (dig, len(evs), 1 if truncated else 0, iso_ms(now_utc()), sid))
    return True


def cal_sync(c, sid, force=False):
    """Fetches one subscription now (errors land in the row, never raised). False = it was already syncing."""
    with _CAL_LOCK:
        if sid in _CAL_BUSY:
            return False
        _CAL_BUSY.add(sid)
    try:
        s = c.execute("SELECT s.*, u.username AS u_login FROM cal_subs s JOIN users u ON u.id=s.user_id WHERE s.id=?",
                      (sid,)).fetchone()
        if not s:
            return False
        now = now_utc()
        c.execute("UPDATE cal_subs SET tried_at=? WHERE id=?", (iso(now), sid))
        c.commit()
        # re-expand at least once a day (the window moves); otherwise ETag / ctag say whether anything changed
        fresh = not force and bool(s["fetched_at"]) and parse_iso(s["fetched_at"]).astimezone(TZ).date() == local_now().date()
        upd, url, lg = {}, "", lang(c, s["user_id"])
        try:
            allow = cal_allow(c)
            url = cal_unseal(c, s["user_id"], s["url"])
            res = None
            if s["kind"] == "caldav":
                auth = (s["username"], cal_unseal(c, s["user_id"], s["password"]))
                tag = caldav_tag(url, auth, allow)
                if not (tag and tag == s["ctag"] and fresh):
                    raws = caldav_fetch(url, auth, allow)
                    res = cal_expand(raws) if raws else ([], False, "")
                    upd["ctag"] = tag
            else:
                hd = {}
                if fresh and s["etag"]:
                    hd["If-None-Match"] = s["etag"]
                if fresh and s["last_modified"]:
                    hd["If-Modified-Since"] = s["last_modified"]
                st, h, data, _ = cal_http(url, headers=hd, allow=allow, cross_redirects=True)
                if st != 304:
                    res = cal_expand([data])
                    upd.update(etag=(h.get("ETag") or "")[:200], last_modified=(h.get("Last-Modified") or "")[:100])
            if res is not None:
                evs, trunc, name = res
                cal_store(c, sid, evs, trunc)
                upd["fetched_at"] = iso(now_utc())
                if not s["name"]:
                    upd["name"] = name or urllib.parse.urlsplit(url).hostname or tr("Calendar", lg=lg)
            upd.update(status="ok", error="", fails=0, synced_at=iso(now_utc()))
        except Exception as e:  # noqa: BLE001
            ce = e if isinstance(e, CalError) else CalError("error", type(e).__name__)
            if not isinstance(e, CalError):
                print("calendar sync: subscription", sid, "failed:", type(e).__name__, flush=True)  # never the URL
            upd.update(status="error", error=ce.stored(), fails=s["fails"] + 1)
            if not s["name"]:
                upd["name"] = (urllib.parse.urlsplit(url).hostname if url else "") or tr("Calendar", lg=lg)
            if upd["fails"] >= CAL_ALERT_FAILS:
                aa_now("integration", f"calendar:{sid}:{ce.code}",
                       N_("Calendar subscription #{0} of user {1} failed {2} times in a row ({3})."),
                       [sid, s["u_login"], upd["fails"], ce.stored()])
        c.execute(f"UPDATE cal_subs SET {', '.join(k + '=?' for k in upd)} WHERE id=?", (*upd.values(), sid))
        c.commit()
        return True
    finally:
        with _CAL_LOCK:
            _CAL_BUSY.discard(sid)


def cal_due(r, now):
    if not r["tried_at"]:
        return True
    iv = (r["interval"] if r["interval"] in CAL_INTERVALS else 15) * CAL_TICK
    if r["fails"]:  # back off while it keeps failing: up to 8x the interval, at most 6 h
        iv = min(iv * 2 ** min(r["fails"], 3), max(iv, 6 * 60 * CAL_TICK))
    return (now - parse_iso(r["tried_at"])).total_seconds() >= iv


def cal_loop():
    from ..family.carddav import contacts_due
    while True:
        time.sleep(min(30, max(1, CAL_TICK // 2)))
        try:
            c = connect()
            try:
                rows = c.execute("""SELECT s.id, s.tried_at, s.interval, s.fails FROM cal_subs s JOIN users u ON u.id=s.user_id
                                    WHERE u.disabled=0 ORDER BY s.tried_at IS NOT NULL, s.tried_at""").fetchall()
                now = now_utc()
                for r in rows:
                    if cal_due(r, now):
                        with GATE.bg():
                            cal_sync(c, r["id"])
                contacts_due(c)  # 2.19.0 (#653): address books, once a day
            finally:
                c.close()
        except Exception as e:  # noqa: BLE001
            print("calendar loop error:", type(e).__name__, flush=True)
            aa_count("watchdog", f"calendar|{type(e).__name__}", "calendar")


# ---- API (every row is private to its user: all queries carry user_id)
_CAL_RATE, _CAL_RATE_LOCK = {}, threading.Lock()


def cal_rate(uid, sid=None):
    """True if another outbound action by hand is allowed now (and records it)."""
    now = time.time()
    with _CAL_RATE_LOCK:
        arr = [t for t in _CAL_RATE.get(("u", uid), []) if now - t < FAIL_WINDOW]
        if len(arr) >= CAL_NET_LIMIT:
            _CAL_RATE[("u", uid)] = arr
            return False
        if sid is not None and now - _CAL_RATE.get(("s", sid), 0.0) < CAL_REFRESH_GAP:
            return False
        arr.append(now)
        _CAL_RATE[("u", uid)] = arr
        if sid is not None:
            _CAL_RATE[("s", sid)] = now
        if len(_CAL_RATE) > 5000:
            _CAL_RATE.clear()
    return True


def need_cal():
    if not CAL_ON:
        raise Denied(409, tr("Calendar subscriptions are turned off on this server"))


def cal_public(r):
    return {"id": r["id"], "kind": r["kind"], "name": r["name"], "color": r["color"], "visible": bool(r["visible"]),
            "interval": r["interval"], "url_hint": r["url_hint"], "username": r["username"],
            "password_saved": bool(r["password"]), "status": r["status"],
            "error": r["error"], "error_text": cal_err_text(r["error"]) if r["error"] else "",
            "synced_at": r["synced_at"], "tried_at": r["tried_at"], "events": r["events"], "truncated": bool(r["truncated"]),
            "fails": r["fails"]}


def cal_list(c, uid):
    rows = c.execute("SELECT * FROM cal_subs WHERE user_id=? ORDER BY id", (uid,)).fetchall()
    return {"enabled": CAL_ON, "subs": [cal_public(r) for r in rows], "colors": list(CAL_COLORS), "intervals": list(CAL_INTERVALS),
            "max": CAL_MAX_SUBS}


def cal_sig(c, uid):
    r = c.execute("SELECT COUNT(*), MAX(changed_at), SUM(visible) FROM cal_subs WHERE user_id=?", (uid,)).fetchone()
    return f"{r[0]}.{r[2] or 0}.{r[1] or ''}"


def need_calsub(c, sid):
    r = c.execute("SELECT * FROM cal_subs WHERE id=? AND user_id=?", (sid, me())).fetchone()
    if not r:
        raise Denied(404)
    return r


def _cal_fields(b, old=None):
    """name / color / visible / interval of a request body -> {column: value}; BadInput when invalid."""
    out = {}
    if "name" in b:
        if not isinstance(b["name"], str):
            raise BadInput(tr("Invalid value: {0}", "name"))
        out["name"] = _cal_clean(b["name"], 100)
        if not out["name"] and old is not None:
            raise BadInput(tr("Invalid value: {0}", "name"))
    if "color" in b:
        v = b["color"]
        if not isinstance(v, str) or not (v == "" or re.fullmatch(r"#[0-9a-fA-F]{6}", v)):
            raise BadInput(tr("Invalid value: {0}", tr("Color")))
        out["color"] = v.lower()
    if "visible" in b:
        if not isinstance(b["visible"], bool):
            raise BadInput(tr("Invalid value: {0}", "visible"))
        out["visible"] = 1 if b["visible"] else 0
    if "interval" in b:
        if b["interval"] not in CAL_INTERVALS or isinstance(b["interval"], bool):
            raise BadInput(tr("Invalid value: {0}", "interval"))
        out["interval"] = b["interval"]
    return out


def _cal_next_color(c, uid):
    used = [r[0] for r in c.execute("SELECT color FROM cal_subs WHERE user_id=?", (uid,))]
    return next((x for x in CAL_COLORS if x not in used), CAL_COLORS[len(used) % len(CAL_COLORS)])


def _cal_insert(c, uid, kind, url, fields, username="", password=""):
    now = iso(now_utc())
    return c.execute("""INSERT INTO cal_subs(user_id,kind,name,color,visible,interval,url,url_hint,username,password,created_at,changed_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (uid, kind, fields.get("name", ""), fields.get("color") or _cal_next_color(c, uid), fields.get("visible", 1),
                      fields.get("interval", 15), cal_seal(c, uid, url), cal_url_hint(url), username,
                      cal_seal(c, uid, password), now, iso_ms(now_utc()))).lastrowid


def _cal_limited():
    return err(tr("Too many calendar requests, please wait a moment"), 429)


@app.get("/api/calendars")
def cal_get():
    return jsonify(cal_list(db(), me()))


@app.post("/api/calendars/discover")
def cal_discover_api():
    """{url, username, password} -> {calendars: [{url, name, color}]} of a CalDAV account (nothing is stored)."""
    need_cal()
    b = body()
    url = cal_norm_url(b.get("url"))
    user, pw = b.get("username"), b.get("password")
    if not url or not isinstance(user, str) or not isinstance(pw, str) or not user.strip() or not pw or len(user) > 200 or len(pw) > 500:
        return err(tr("Server address, username and password are needed"))
    if not cal_rate(me()):
        return _cal_limited()
    try:
        cals = caldav_discover(url, (user.strip(), pw), cal_allow(db()))
    except CalError as e:
        return jsonify(error=cal_err_text(e.stored()), code=e.code), 400
    return jsonify(calendars=cals)


@app.post("/api/calendars")
def cal_create():
    """ICS: {kind: 'ics', url, name?, color?, interval?}. CalDAV: {kind: 'caldav', url (server), username, password,
    calendars: [{url, name, color}]} -> one subscription per calendar. Each is fetched at once; one that fails is
    not kept (the answer names the error)."""
    need_cal()
    b, c, uid = body(), db(), me()
    kind = b.get("kind")
    fields = _cal_fields({k: b[k] for k in ("name", "color", "visible", "interval") if k in b})
    have = c.execute("SELECT COUNT(*) FROM cal_subs WHERE user_id=?", (uid,)).fetchone()[0]
    if kind == "ics":
        url = cal_norm_url(b.get("url"))
        if not url:
            return err(tr("Invalid link"))
        todo = [(url, fields)]
        user = pw = ""
    elif kind == "caldav":
        server = cal_norm_url(b.get("url"))
        user, pw = b.get("username"), b.get("password")
        sel = b.get("calendars")
        if not server or not isinstance(user, str) or not isinstance(pw, str) or not user.strip() or not pw or len(user) > 200 or len(pw) > 500:
            return err(tr("Server address, username and password are needed"))
        if not isinstance(sel, list) or not sel or len(sel) > CAL_MAX_SUBS or not all(isinstance(x, dict) for x in sel):
            return err(tr("Choose at least one calendar"))
        user, todo = user.strip(), []
        for x in sel:
            u = cal_norm_url(x.get("url"))
            if not u or not cal_href_ok(server, u):
                return err(tr("Invalid link"))
            f = _cal_fields({k: x[k] for k in ("name", "color") if k in x})
            todo.append((u, {**fields, **f}))
    else:
        return err(tr("Invalid value: {0}", "kind"))
    if have + len(todo) > CAL_MAX_SUBS:
        return err(tr("At most {0} calendars", CAL_MAX_SUBS), 409)
    if not cal_rate(uid):
        return _cal_limited()
    made, errors = [], []
    for url, f in todo:
        sid = _cal_insert(c, uid, kind, url, f, user or "", pw or "")
        c.commit()
        cal_sync(c, sid, force=True)
        r = c.execute("SELECT * FROM cal_subs WHERE id=?", (sid,)).fetchone()
        if r["status"] != "ok":
            errors.append({"name": f.get("name") or "", "code": r["error"].split(":", 1)[0], "error": cal_err_text(r["error"])})
            c.execute("DELETE FROM cal_subs WHERE id=?", (sid,))
            c.commit()
        else:
            made.append(sid)
    if not made:
        return jsonify(error=errors[0]["error"], code=errors[0]["code"], errors=errors), 400
    return jsonify({**cal_list(c, uid), "created": made, "errors": errors})


@app.patch("/api/calendars/<int:sid>")
def cal_update(sid):
    """name / color / visible / interval; a new ICS link, or new CalDAV username / password (then fetched again)."""
    c, b = db(), body()
    r = need_calsub(c, sid)
    upd = _cal_fields(b, r)
    resync = False
    if "url" in b and r["kind"] == "ics" and b["url"] not in ("", None):
        url = cal_norm_url(b["url"])
        if not url:
            return err(tr("Invalid link"))
        upd.update(url=cal_seal(c, r["user_id"], url), url_hint=cal_url_hint(url), etag="", last_modified="")
        resync = True
    if r["kind"] == "caldav":
        if "username" in b:
            if not isinstance(b["username"], str) or not b["username"].strip() or len(b["username"]) > 200:
                return err(tr("Invalid value: {0}", "username"))
            upd["username"] = b["username"].strip()
            resync = True
        if b.get("password"):
            if not isinstance(b["password"], str) or len(b["password"]) > 500:
                return err(tr("Invalid value: {0}", "password"))
            upd.update(password=cal_seal(c, r["user_id"], b["password"]), ctag="")
            resync = True
    if upd:
        upd["changed_at"] = iso_ms(now_utc())
        c.execute(f"UPDATE cal_subs SET {', '.join(k + '=?' for k in upd)} WHERE id=? AND user_id=?", (*upd.values(), sid, me()))
        c.commit()
    if resync and CAL_ON:
        if not cal_rate(me(), sid):
            return _cal_limited()
        cal_sync(c, sid, force=True)
    return jsonify(cal_public(need_calsub(c, sid)))


@app.delete("/api/calendars/<int:sid>")
def cal_delete(sid):
    c = db()
    need_calsub(c, sid)
    c.execute("DELETE FROM cal_subs WHERE id=? AND user_id=?", (sid, me()))
    c.commit()
    return jsonify(cal_list(c, me()))


@app.post("/api/calendars/<int:sid>/refresh")
def cal_refresh(sid):
    need_cal()
    c = db()
    need_calsub(c, sid)
    if not cal_rate(me(), sid):
        return _cal_limited()
    cal_sync(c, sid, force=True)
    return jsonify(cal_public(need_calsub(c, sid)))


@app.get("/api/calendars/events")
def cal_events():
    """Occurrences of my visible subscriptions that overlap [from, to] (local dates, at most 400 days)."""
    try:
        lo = date.fromisoformat(request.args["from"])
        hi = date.fromisoformat(request.args["to"])
    except (KeyError, ValueError):
        return err(tr("from/to missing"))
    if hi < lo or (hi - lo).days > 400:
        return err(tr("Date range too large"))
    c, uid = db(), me()
    if not CAL_ON:
        return jsonify(events=[], subs={})
    subs = {r["id"]: {"name": r["name"], "color": r["color"]}
            for r in c.execute("SELECT id, name, color FROM cal_subs WHERE user_id=? AND visible=1", (uid,))}
    rows = c.execute("""SELECT e.* FROM cal_events e JOIN cal_subs s ON s.id=e.sub_id
                        WHERE s.user_id=? AND s.visible=1 AND e.d1>=? AND e.d0<=? ORDER BY e.start, e.id LIMIT 20000""",
                     (uid, lo.isoformat(), hi.isoformat())).fetchall()
    return jsonify(events=[{"id": r["id"], "sub": r["sub_id"], "title": r["title"], "location": r["location"],
                            "description": r["description"], "all_day": bool(r["all_day"]), "start": r["start"], "end": r["end"]}
                           for r in rows], subs=subs)
