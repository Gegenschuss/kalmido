"""2.52.0 B (#1128): writing events into CalDAV subscriptions (new, change, delete) with ETags."""
import posixpath
import threading
import time
import urllib.parse
import uuid as uuidlib
from datetime import date, datetime, timedelta, timezone
import icalendar
from flask import jsonify, request

from ..core.config import _origin, app, TZ
from ..core.i18n import tr
from ..core.db import body, db, err, iso_ms, now_utc
from ..accounts.session import FAIL_WINDOW, me
from ..core.access import Denied
from ..calendars.icalfeed import ics_text, ics_utc
from ..calendars.subscriptions import (DAV_NS, CalError, _CAL_RATE, _CAL_RATE_LOCK, _cal_clean, _cal_limited,
                                       cal_allow, cal_err_text, cal_href_ok, cal_public, cal_sync, cal_unseal, dav_propfind,
                                       cal_http, need_cal, need_calsub)
from ..events.ics import _dt_line, wrap
from ..events.model import ev_zone, tz_ok, wall


# ---------------------------------------------------------------- writing into CalDAV subscriptions
# Off by default per subscription ("Allow writing", cal_subs.dav_write) and only for CalDAV (ICS links stay read-only).
# Turning it on and every sync ask the server for current-user-privilege-set of the collection (dav_can_write); events are
# only written when both are 1. Each sync stores where every event lives (cal_dav_res: href + ETag per UID). A change
# fetches the resource, replaces only the changed properties of the series (VEVENT without RECURRENCE-ID: unknown
# properties, VALARM, ATTENDEE, X-... stay as they are) and PUTs it back with If-Match; a new event is PUT with
# If-None-Match: * under the collection; a delete uses If-Match. 412 (or an ETag that moved) = changed elsewhere: nothing
# is overwritten, the subscription is fetched again. Every request goes through cal_http (SSRF guard, allow-list, no
# credentials across hosts) and only to resources below the subscription's collection (cdw_inside). Only the owner of a
# subscription writes (need_calsub); agents get no access (session routes only). One date of a repeating series is not
# changed on its own (the whole series moves; the client offers only "All dates").
CDW_LIMIT = 60          # writes per user within FAIL_WINDOW (own bucket next to cal_rate: dragging is quick)
CDW_TEXT = {"title": 500, "location": 500, "description": 20000}
CDW_UNDO_S = 15 * 60    # how long a deleted event can be put back (the old resource, in memory)
_CDW_UNDO, _CDW_UNDO_LOCK = {}, threading.Lock()
_CDW_PRIV = f"{{{DAV_NS}}}current-user-privilege-set"


class CdwConflict(Exception):
    pass


def cdw_rate(uid):
    now = time.time()
    with _CAL_RATE_LOCK:
        arr = [t for t in _CAL_RATE.get(("w", uid), []) if now - t < FAIL_WINDOW]
        if len(arr) >= CDW_LIMIT:
            _CAL_RATE[("w", uid)] = arr
            return False
        arr.append(now)
        _CAL_RATE[("w", uid)] = arr
    return True


def cdw_privs(url, auth, allow):
    """True when the collection lets this account create and change resources (current-user-privilege-set)."""
    _, rs = dav_propfind(url, 0, "<d:current-user-privilege-set/>", auth, allow)
    ps = rs[0][1].get(_CDW_PRIV) if rs else None
    if ps is None:
        return False
    names = {el.tag.rsplit("}", 1)[-1] for p in ps.findall(f"{{{DAV_NS}}}privilege") for el in p}
    return bool(names & {"all", "write"}) or {"write-content", "bind"} <= names


def cdw_check(c, s, url, auth, allow):
    """Called by cal_sync for a subscription with "Allow writing": the privilege check of every sync (1 / 0)."""
    try:
        return 1 if cdw_privs(url, auth, allow) else 0
    except CalError as e:
        if e.code in ("network", "timeout"):
            return s["dav_can_write"]  # a hiccup does not switch it off
        return 0


def cdw_inside(coll, href):
    """The resource lies directly or deeper below the subscription's collection on the same origin (never a
    manipulated href elsewhere)."""
    if not href or not cal_href_ok(coll, href) or _origin(coll) != _origin(href):
        return False
    a, b = urllib.parse.urlsplit(coll), urllib.parse.urlsplit(href)
    if b.query or b.fragment or b.username or b.password:
        return False
    pa = posixpath.normpath(urllib.parse.unquote(a.path or "/")).rstrip("/") + "/"
    raw = urllib.parse.unquote(b.path or "")
    if "/../" in raw + "/" or "/./" in raw + "/":
        return False
    pb = posixpath.normpath(raw)
    return pb.startswith(pa) and len(pb) > len(pa)


def _unfold(text):
    return text.replace("\r\n", "\n").replace("\n ", "").replace("\n\t", "").split("\n")


def cdw_store_res(c, sid, coll, items):
    """items = [(href, etag, calendar-data)] of a CalDAV fetch -> cal_dav_res (one row per UID)."""
    rows = {}
    for href, etag, data in items:
        if not data or not cdw_inside(coll, href):
            continue
        uid, rec, comp = "", 0, []
        for ln in _unfold(data):
            name = ln.split(":", 1)[0].split(";", 1)[0].strip().upper()
            if name in ("BEGIN", "END"):
                v = ln.split(":", 1)[-1].strip().upper()
                comp = comp + [v] if name == "BEGIN" else comp[:-1]
            elif comp[-1:] != ["VEVENT"]:
                continue  # only the event's own lines (not VTIMEZONE / VALARM)
            elif name == "UID" and not uid:
                v = ln.split(":", 1)[1] if ":" in ln else ""
                uid = _cal_clean(v.replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\"), 300)
            elif name in ("RRULE", "RDATE", "RECURRENCE-ID"):
                rec = 1
        if uid:
            rows[uid] = (href[:2000], (etag or "")[:200], rec)
    c.execute("DELETE FROM cal_dav_res WHERE sub_id=?", (sid,))
    c.executemany("INSERT INTO cal_dav_res(sub_id,uid,href,etag,rec) VALUES(?,?,?,?,?)",
                  [(sid, u, *v) for u, v in rows.items()])


# ---- helpers for the routes
def _cdw_sub(c, sid):
    """My CalDAV subscription with "Allow writing" on and the right to write; Denied otherwise."""
    need_cal()
    r = need_calsub(c, sid)
    if r["kind"] != "caldav" or not r["dav_write"] or not r["dav_can_write"]:
        raise Denied(403, tr("Writing into this calendar is not allowed"))
    return r


def _cdw_auth(c, r):
    return cal_unseal(c, r["user_id"], r["url"]), (r["username"], cal_unseal(c, r["user_id"], r["password"])), cal_allow(c)


def _cdw_fields(b, need_times):
    """Validated {title, location, description, all_day, start (date | aware datetime), end, tz} of a request body."""
    out = {}
    for k, n in CDW_TEXT.items():
        if k in b:
            if not isinstance(b[k], str):
                raise ValueError(k)
            v = b[k].replace("\r\n", "\n")
            out[k] = (" ".join(v.split()) if k != "description" else v)[:n]
    if "start" in b or "end" in b or need_times:
        ad = b.get("all_day")
        if not isinstance(ad, bool):
            raise ValueError("all_day")
        zn = b.get("tz") or getattr(TZ, "key", "UTC")
        if not isinstance(zn, str) or not tz_ok(zn):
            raise ValueError("tz")
        if ad:
            try:
                s, e = date.fromisoformat(str(b.get("start"))[:10]), date.fromisoformat(str(b.get("end"))[:10])
            except ValueError:
                raise ValueError("start") from None
            if e <= s:
                e = s + timedelta(days=1)
        else:
            s, e = wall(b.get("start")), wall(b.get("end"))
            if not s or not e or e < s:
                raise ValueError("start")
            z = ev_zone(zn)
            s, e = s.replace(tzinfo=z), e.replace(tzinfo=z)
        if (e - s).days > 366 * 3:
            raise ValueError("end")
        out.update(all_day=ad, start=s, end=e, tz=zn)
    return out


def _bad(k):
    return err(tr("Invalid value: {0}", k))


def _conflict(c, sid):
    cal_sync(c, sid, force=True)
    return jsonify(error=tr("This event was changed elsewhere. The calendar was reloaded; nothing was overwritten."),
                   code="conflict"), 409


def _cal_fail(e):
    if e.code == "auth" and e.detail == "403":
        return jsonify(error=tr("This calendar does not allow writing"), code="read_only"), 409
    return jsonify(error=cal_err_text(e.stored()), code=e.code), 502


def _put(url, ics, auth, allow, match=None, new=False):
    hd = {"Content-Type": "text/calendar; charset=utf-8"}
    if new:
        hd["If-None-Match"] = "*"
    elif match:
        hd["If-Match"] = match
    try:
        st, _, _, _ = cal_http(url, "PUT", ics.encode("utf-8"), hd, auth, allow)
    except CalError as e:
        if e.code == "http" and e.detail == "412":
            raise CdwConflict() from None
        raise
    if st not in (200, 201, 204):
        raise CalError("http", st)


def _tag(t):
    t = (t or "").strip()
    return t[2:] if t.startswith("W/") else t


def _res(c, sid, uid):
    r = c.execute("SELECT * FROM cal_dav_res WHERE sub_id=? AND uid=?", (sid, uid)).fetchone() if isinstance(uid, str) else None
    if not r:
        raise Denied(404, tr("This event was not found in the calendar. Reload and try again."))
    return r


def _naive_in(dt, z):
    return dt.astimezone(z).replace(tzinfo=None)


def _set_dt(comp, name, value, like=None):
    """Sets DTSTART / DTEND as a date, or a date-time in the zone of `like` (the old value: same TZID, UTC or floating)."""
    comp.pop(name, None)
    if not isinstance(value, datetime):
        comp.add(name, value)
        comp[name].params["VALUE"] = "DATE"
        return
    tzid = like.params.get("TZID") if like is not None and hasattr(like, "params") else None
    lv = like.dt if like is not None and hasattr(like, "dt") else None
    if tzid and isinstance(lv, datetime) and lv.tzinfo is not None:
        comp.add(name, _naive_in(value, lv.tzinfo))
        comp[name].params["TZID"] = tzid
    elif isinstance(lv, datetime) and lv.tzinfo is None:
        comp.add(name, _naive_in(value, TZ))  # floating stays floating (read in the server's zone)
    else:
        comp.add(name, value.astimezone(timezone.utc))


def _shift(prop, delta, days):
    """EXDATE / RECURRENCE-ID values moved like the series (keeps excluded / changed dates attached)."""
    try:
        if hasattr(prop, "dts"):
            for d in prop.dts:
                d.dt = d.dt + (timedelta(days=days) if not isinstance(d.dt, datetime) else delta)
        elif hasattr(prop, "dt"):
            prop.dt = prop.dt + (timedelta(days=days) if not isinstance(prop.dt, datetime) else delta)
    except (TypeError, ValueError, OverflowError):
        pass


def cdw_patch_ics(raw, uid, f, occ):
    """The resource with the series' changed properties (str). occ = the start of the occurrence that was edited
    (as stored in cal_events: a date or a UTC time): new times move the series by the same amount."""
    cal = icalendar.Calendar.from_ical(raw)
    comps = [x for x in cal.walk("VEVENT") if _cal_clean(x.get("UID"), 300) == uid]
    master = next((x for x in comps if x.get("RECURRENCE-ID") is None), None)
    if master is None:
        raise ValueError("uid")
    rec = master.get("RRULE") is not None or master.get("RDATE") is not None or len(comps) > 1
    for k, p in (("title", "SUMMARY"), ("location", "LOCATION"), ("description", "DESCRIPTION")):
        if k in f:
            master.pop(p, None)
            if f[k]:
                master.add(p, f[k])
    if "start" in f:
        ms = master.get("DTSTART")
        mdt = ms.dt if ms is not None else None
        dur = f["end"] - f["start"]
        was_ad = mdt is not None and not isinstance(mdt, datetime)
        if f["all_day"] != was_ad and rec:
            raise ValueError("all_day")
        delta, days = timedelta(0), 0
        if not rec or mdt is None or f["all_day"] != was_ad:
            new_s = f["start"]
        elif f["all_day"]:
            days = (f["start"] - date.fromisoformat(occ[:10])).days
            new_s = mdt + timedelta(days=days)
        else:  # the wall-clock shift in the series' zone (DST-safe for weekly rules)
            z = mdt.tzinfo or TZ
            o = datetime.strptime(occ, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            wdelta = _naive_in(f["start"], z) - _naive_in(o, z)
            new_s = (mdt.replace(tzinfo=None) + wdelta).replace(tzinfo=z)
            delta = wdelta
        master.pop("DURATION", None)
        _set_dt(master, "DTSTART", new_s, ms if not f["all_day"] else None)
        _set_dt(master, "DTEND", new_s + dur, ms if not f["all_day"] else None)
        if rec and (delta or days):
            for x in (master.get("EXDATE") if isinstance(master.get("EXDATE"), list) else [master.get("EXDATE")]):
                if x is not None:
                    _shift(x, delta, days)
            for x in comps:
                if x is not master and x.get("RECURRENCE-ID") is not None:
                    _shift(x["RECURRENCE-ID"], delta, days)
    seq = master.get("SEQUENCE")
    master.pop("SEQUENCE", None)
    try:
        master.add("SEQUENCE", int(str(seq)) + 1 if seq is not None else 1)
    except ValueError:
        master.add("SEQUENCE", 1)
    for p in ("DTSTAMP", "LAST-MODIFIED"):
        master.pop(p, None)
        master.add(p, now_utc().replace(microsecond=0))
    return cal.to_ical().decode("utf-8"), rec


def cdw_new_ics(f, uid):
    ad = f["all_day"]
    key = (lambda v: v.isoformat()) if ad else (lambda v: v.strftime("%Y-%m-%dT%H:%M"))
    stamp = ics_utc(now_utc())
    L = ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}", f"CREATED:{stamp}", f"LAST-MODIFIED:{stamp}", "SEQUENCE:0",
         f"SUMMARY:{ics_text(f.get('title') or tr('(no title)'))}",
         _dt_line("DTSTART", key(f["start"]), ad, f["tz"]), _dt_line("DTEND", key(f["end"]), ad, f["tz"])]
    if f.get("location"):
        L.append(f"LOCATION:{ics_text(f['location'])}")
    if f.get("description"):
        L.append(f"DESCRIPTION:{ics_text(f['description'])}")
    L.append("END:VEVENT")
    return wrap(L, set() if ad else {f["tz"]}, f["start"].year)


# ---- API (session only: the owner of the subscription)
@app.post("/api/calendars/<int:sid>/write")
def cdw_toggle(sid):
    """{on: bool} -> "Allow writing" of a CalDAV subscription; turning it on checks the server's privileges first."""
    need_cal()
    c, b = db(), body()
    r = need_calsub(c, sid)
    on = b.get("on")
    if not isinstance(on, bool):
        return _bad("on")
    if r["kind"] != "caldav":
        return err(tr("Only CalDAV calendars can be written to; calendar links stay read-only"), 409)
    can = r["dav_can_write"]
    if on:
        if not cdw_rate(me()):
            return _cal_limited()
        url, auth, allow = _cdw_auth(c, r)
        c.commit()  # no open transaction while the calendar server is asked
        try:
            can = 1 if cdw_privs(url, auth, allow) else 0
        except CalError as e:
            return _cal_fail(e)
        if not can:
            c.execute("UPDATE cal_subs SET dav_can_write=0 WHERE id=? AND user_id=?", (sid, me()))
            c.commit()
            return jsonify(error=tr("This calendar does not allow writing"), code="read_only"), 409
    c.execute("UPDATE cal_subs SET dav_write=?, dav_can_write=?, changed_at=? WHERE id=? AND user_id=?",
              (1 if on else 0, can, iso_ms(now_utc()), sid, me()))
    c.commit()
    if on:
        cal_sync(c, sid, force=True)  # the resources (href + ETag) of every event
    return jsonify(cal_public(need_calsub(c, sid)))


@app.post("/api/calendars/<int:sid>/events")
def cdw_create(sid):
    """{title, location?, description?, all_day, start, end, tz?} -> a new event in the CalDAV calendar."""
    c, b = db(), body()
    r = _cdw_sub(c, sid)
    try:
        f = _cdw_fields(b, True)
    except ValueError as e:
        return _bad(str(e))
    if not cdw_rate(me()):
        return _cal_limited()
    url, auth, allow = _cdw_auth(c, r)
    c.commit()
    uid = str(uuidlib.uuid4())
    href = urllib.parse.urljoin(url if url.endswith("/") else url + "/", uid + ".ics")
    if not cdw_inside(url, href):
        return _bad("url")
    try:
        _put(href, cdw_new_ics(f, uid), auth, allow, new=True)
    except CdwConflict:
        return _conflict(c, sid)
    except CalError as e:
        return _cal_fail(e)
    cal_sync(c, sid, force=True)
    return jsonify(ok=True, uid=uid)


@app.patch("/api/calendars/<int:sid>/events")
def cdw_update(sid):
    """{uid, occ (the edited occurrence's start), scope?, fields like create} -> the series' properties changed
    (If-Match). scope 'one' is refused for repeating events."""
    c, b = db(), body()
    r = _cdw_sub(c, sid)
    res = _res(c, sid, b.get("uid"))
    if b.get("scope") == "one" and res["rec"]:
        return err(tr("For calendars of other services only the whole series can be changed"), 409)
    try:
        f = _cdw_fields(b, False)
    except ValueError as e:
        return _bad(str(e))
    occ = b.get("occ")
    if "start" in f and not isinstance(occ, str):
        return _bad("occ")
    if not cdw_rate(me()):
        return _cal_limited()
    url, auth, allow = _cdw_auth(c, r)
    c.commit()
    if not cdw_inside(url, res["href"]):
        return _bad("href")
    try:
        st, h, data, _ = cal_http(res["href"], "GET", None, {"Accept": "text/calendar"}, auth, allow)
        tag = _tag(h.get("ETag")) if h else ""
        if st != 200 or (tag and res["etag"] and tag != _tag(res["etag"])):
            return _conflict(c, sid)
        match = res["etag"] or tag
        if not match:
            return _conflict(c, sid)
        try:
            ics, _ = cdw_patch_ics(data, res["uid"], f, occ or "")
        except ValueError as e:
            if str(e) == "all_day":
                return err(tr("A repeating event of this calendar cannot switch between all-day and timed"), 409)
            return _conflict(c, sid)
        except Exception:  # noqa: BLE001  (icalendar raises many types on bad input)
            return jsonify(error=cal_err_text("parse"), code="parse"), 502
        _put(res["href"], ics, auth, allow, match=match)
    except CdwConflict:
        return _conflict(c, sid)
    except CalError as e:
        if e.code == "not_found":
            return _conflict(c, sid)
        return _cal_fail(e)
    cal_sync(c, sid, force=True)
    return jsonify(ok=True, uid=res["uid"])


@app.delete("/api/calendars/<int:sid>/events")
def cdw_delete(sid):
    """?uid= -> the whole event (a repeating one: every date) removed (If-Match). The answer carries an undo token."""
    c = db()
    r = _cdw_sub(c, sid)
    res = _res(c, sid, request.args.get("uid"))
    if not cdw_rate(me()):
        return _cal_limited()
    url, auth, allow = _cdw_auth(c, r)
    c.commit()
    if not cdw_inside(url, res["href"]):
        return _bad("href")
    try:
        st, h, data, _ = cal_http(res["href"], "GET", None, {"Accept": "text/calendar"}, auth, allow)
        tag = _tag(h.get("ETag")) if h else ""
        if st != 200 or (tag and res["etag"] and tag != _tag(res["etag"])):
            return _conflict(c, sid)
        match = res["etag"] or tag
        if not match:
            return _conflict(c, sid)
        try:
            cal_http(res["href"], "DELETE", None, {"If-Match": match}, auth, allow)
        except CalError as e:
            if e.code == "http" and e.detail == "412":
                raise CdwConflict() from None
            raise
    except CdwConflict:
        return _conflict(c, sid)
    except CalError as e:
        if e.code == "not_found":
            return _conflict(c, sid)
        return _cal_fail(e)
    tok = uuidlib.uuid4().hex
    with _CDW_UNDO_LOCK:
        now = time.time()
        for k in [k for k, v in _CDW_UNDO.items() if now - v[0] > CDW_UNDO_S]:
            _CDW_UNDO.pop(k, None)
        if len(_CDW_UNDO) > 500:
            _CDW_UNDO.clear()
        _CDW_UNDO[tok] = (now, me(), sid, res["href"], data)
    cal_sync(c, sid, force=True)
    return jsonify(ok=True, undo=tok)


@app.post("/api/calendars/<int:sid>/events/restore")
def cdw_restore(sid):
    """{undo} -> a deleted event put back where it was (If-None-Match: *), within CDW_UNDO_S."""
    c, b = db(), body()
    r = _cdw_sub(c, sid)
    tok = b.get("undo")
    with _CDW_UNDO_LOCK:
        u = _CDW_UNDO.get(tok) if isinstance(tok, str) else None
        if not u or u[1] != me() or u[2] != sid or time.time() - u[0] > CDW_UNDO_S:
            u = None
        else:
            _CDW_UNDO.pop(tok, None)
    if not u:
        return err(tr("This can no longer be undone"), 410)
    if not cdw_rate(me()):
        return _cal_limited()
    url, auth, allow = _cdw_auth(c, r)
    c.commit()
    if not cdw_inside(url, u[3]):
        return _bad("href")
    try:
        _put(u[3], u[4].decode("utf-8", "replace") if isinstance(u[4], bytes) else u[4], auth, allow, new=True)
    except CdwConflict:
        return _conflict(c, sid)
    except CalError as e:
        return _cal_fail(e)
    cal_sync(c, sid, force=True)
    return jsonify(ok=True)

