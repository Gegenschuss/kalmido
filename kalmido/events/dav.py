"""Events over CalDAV: every event calendar (and the person's invitations) as a VEVENT collection next to the task lists."""
import email.utils
import functools
import hashlib
import json
import re
import threading
import time
import urllib.parse
import zlib
from datetime import date, datetime, timedelta, timezone

from flask import request, Response

from ..core.config import APP_NAME, TZ
from ..core.i18n import tr
from ..core.db import IntegrityError, gsetting, iso_ms, now_utc, parse_iso
from ..core.access import collab_all
from ..calendars.caldav import (
    _el, _privs, _xe, A_, C_, CS_, D_, dav_body, dav_common, dav_href, dav_multistatus, dav_principal_href, dav_propfind_req,
    dav_response, dav_xml, DAV_MAX_BODY, DAV_NAME_RE, DAV_SYNC_KEEP, DavError, dav_color, dav_report_props,
)
from ..events.model import att_rows, ev_att_ok, ev_delete, ev_expand, events_on, my_cal_ids
from ..events.ics import etag, ev_lines, EvError, read_vevent, store_parsed, wrap

_CACHE, _LOCK = {}, threading.Lock()
EV_REPORTS = ("<D:supported-report><D:report><C:calendar-query/></D:report></D:supported-report>"
              "<D:supported-report><D:report><C:calendar-multiget/></D:report></D:supported-report>"
              "<D:supported-report><D:report><D:sync-collection/></D:report></D:supported-report>")


def evdav_colls(c, u):
    """{collection key: info} of u's event collections: e<id> per calendar (owner / shared), inv = invitations."""
    if not events_on(c, u["id"]):
        return {}
    ids = my_cal_ids(c, u["id"])
    out = {}
    if ids:
        q = ",".join("?" * len(ids))
        for r in c.execute(f"SELECT * FROM ev_cals WHERE id IN ({q}) ORDER BY owner_id!=?, sort, id", [*ids, u["id"]]):
            k = r["dav_name"] if r["dav_name"] and r["owner_id"] == u["id"] else f"e{r['id']}"  # 2.155.0 A (#2079)
            out[k] = {"key": k, "id": r["id"], "name": r["name"], "color": r["color"], "role": ids[r["id"]],
                                  "description": r["description"]}
    if collab_all() and any(ev_att_ok(c, u["id"], r[0]) for r in c.execute(  # 2.87.0 (#1983): only invitations one may still see
            "SELECT DISTINCT k.org_id FROM event_attendees a JOIN events e ON e.id=a.event_id JOIN ev_cals k ON k.id=e.cal_id "
            "WHERE a.user_id=?", (u["id"],)).fetchall()):
        # 2.155.0 A (#2074): role rsvp = read, and the own answer (PARTSTAT) may be written back (ev_rsvp_put)
        out["inv"] = {"key": "inv", "id": None, "name": tr("Invitations"), "color": "#94a3b8", "role": "rsvp", "description": ""}
    return out


def _rows(c, u, coll):
    if coll["id"] is not None:
        return c.execute("SELECT * FROM events WHERE cal_id=? AND deleted_at IS NULL ORDER BY id", (coll["id"],)).fetchall()
    mine = set(my_cal_ids(c, u["id"]))
    return [r for r in c.execute("""SELECT e.*, k.org_id AS cal_org FROM events e JOIN event_attendees a ON a.event_id=e.id AND a.user_id=?
                                    JOIN ev_cals k ON k.id=e.cal_id WHERE e.deleted_at IS NULL ORDER BY e.id""", (u["id"],))
            if r["cal_id"] not in mine and ev_att_ok(c, u["id"], r["cal_org"])]  # 2.87.0 (#1983)


class EvColl:
    def __init__(self, coll, members):
        self.coll, self.members = coll, members
        h = hashlib.sha1(usedforsecurity=False)
        for n in sorted(members):
            h.update(f"{n}\0{members[n][1]}\n".encode("utf-8"))
        self.hash = h.hexdigest()[:20]
        self.token = f"urn:kalmido:sync:{coll['key']}-{self.hash}"
        self.ctag = '"' + self.hash + '"'

    def state(self):
        return {n: m[1] for n, m in self.members.items()}


def ev_coll(c, u, coll):
    key = (u["id"], coll["key"], gsetting(c, "version"), coll["name"], coll["color"], coll["role"], collab_all())
    now = time.monotonic()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and hit[0] > now:
            return hit[1]
    rows = _rows(c, u, coll)
    atts = att_rows(c, [r["id"] for r in rows])
    members = {}
    for r in rows:
        try:
            lines, tzs = ev_lines(c, r, atts.get(r["id"], []))
        except (ValueError, TypeError, KeyError) as e:  # one broken row never breaks the collection
            print("caldav: skipping event", r["id"], e, flush=True)
            continue
        members[r["href"]] = (r["id"], etag(lines, tzs), lines, tzs, r)
    ec = EvColl(coll, members)
    with _LOCK:
        if len(_CACHE) > 64:
            for k in sorted(_CACHE, key=lambda k: _CACHE[k][0])[:16]:
                _CACHE.pop(k, None)
        _CACHE[key] = (now + 60, ec)
    return ec


def sync_save(c, u, ec):
    k = ec.coll["key"]
    if c.execute("SELECT 1 FROM dav_sync2 WHERE user_id=? AND coll=? AND token=?", (u["id"], k, ec.hash)).fetchone():
        c.execute("UPDATE dav_sync2 SET created_at=? WHERE user_id=? AND coll=? AND token=?", (iso_ms(now_utc()), u["id"], k, ec.hash))
        c.commit()  # handed out again: the newest, never pruned first
        return ec.token
    blob = zlib.compress(json.dumps(ec.state(), separators=(",", ":")).encode("utf-8"))
    c.execute("INSERT INTO dav_sync2(user_id,coll,token,state,created_at) VALUES(?,?,?,?,?) ON CONFLICT (user_id,coll,token) DO UPDATE SET state=excluded.state, created_at=excluded.created_at",
              (u["id"], k, ec.hash, blob, iso_ms(now_utc())))
    c.execute("""DELETE FROM dav_sync2 WHERE user_id=? AND coll=? AND token NOT IN
                 (SELECT token FROM dav_sync2 WHERE user_id=? AND coll=? ORDER BY created_at DESC LIMIT ?)""",
              (u["id"], k, u["id"], k, DAV_SYNC_KEEP))
    c.commit()
    return ec.token


def sync_load(c, u, key, token):
    m = re.fullmatch(r"urn:kalmido:sync:([A-Za-z0-9_.-]+)-([0-9a-f]{20})", token or "")  # 2.155.0 A (#2079): client names
    if not m or m.group(1) != key:
        return None
    r = c.execute("SELECT state FROM dav_sync2 WHERE user_id=? AND coll=? AND token=?", (u["id"], key, m.group(2))).fetchone()
    try:
        return json.loads(zlib.decompress(r["state"]).decode("utf-8")) if r else None
    except (zlib.error, ValueError):
        return None


def _privs_of(role):
    if role in ("owner", "edit"):
        return _privs(["read", "write", "write-content", "bind", "unbind"])
    if role == "rsvp":  # 2.155.0 A (#2074): answers to invitations, no new objects (no bind)
        return _privs(["read", "write-content"])
    return _privs(["read"])


def coll_href(u, coll):
    return dav_href("calendars", u["username"], coll["key"], coll=True)


def props_coll(c, u, coll, order, ec_fn):
    color = dav_color(coll["color"])
    p = {**dav_common(u), D_ + "resourcetype": "<D:collection/><C:calendar/>", D_ + "displayname": _xe(coll["name"]),
         D_ + "owner": f"<D:href>{_xe(dav_principal_href(u))}</D:href>",
         C_ + "supported-calendar-component-set": '<C:comp name="VEVENT"/>',
         C_ + "supported-calendar-data": '<C:calendar-data content-type="text/calendar" version="2.0"/>',
         C_ + "max-resource-size": str(DAV_MAX_BODY), D_ + "supported-report-set": EV_REPORTS,
         D_ + "current-user-privilege-set": _privs_of(coll["role"]), A_ + "calendar-order": str(order),
         C_ + "calendar-timezone": lambda: _xe(wrap([], {getattr(TZ, "key", "UTC")})),
         CS_ + "getctag": lambda: _xe(ec_fn().ctag), D_ + "sync-token": lambda: _xe(sync_save(c, u, ec_fn())),
         D_ + "getcontenttype": "text/calendar; charset=utf-8"}
    if coll["description"]:
        p[C_ + "calendar-description"] = _xe(coll["description"])
    if color:
        p[A_ + "calendar-color"] = color
    return p


def props_member(u, m, role):
    eid, et, lines, tzs, r = m
    box = []

    def data():
        if not box:
            box.append(wrap(lines, tzs))
        return box[0]
    return {**dav_common(u), D_ + "resourcetype": "", D_ + "getetag": _xe(et),
            D_ + "getcontenttype": "text/calendar; charset=utf-8; component=VEVENT",
            D_ + "getlastmodified": email.utils.format_datetime(parse_iso(r["updated_at"]).astimezone(timezone.utc), usegmt=True),
            D_ + "getcontentlength": lambda: str(len(data().encode("utf-8"))), C_ + "calendar-data": lambda: _xe(data()),
            D_ + "current-user-privilege-set": _privs_of(role), D_ + "owner": f"<D:href>{_xe(dav_principal_href(u))}</D:href>"}


def home_responses(c, u, want, start):
    """The event collections in the calendar home (PROPFIND Depth 1 on the home)."""
    out = []
    for i, coll in enumerate(evdav_colls(c, u).values()):
        out.append(dav_response(coll_href(u, coll), want, props_coll(c, u, coll, start + i, functools.partial(ev_coll, c, u, coll))))
    return out


def member_now(c, u, coll, name):
    """(row, etag, lines, tzs) of a resource, rendered fresh."""
    if coll["id"] is not None:
        r = c.execute("SELECT * FROM events WHERE cal_id=? AND href=? AND deleted_at IS NULL", (coll["id"], name)).fetchone()
    else:
        r = next((x for x in _rows(c, u, coll) if x["href"] == name), None)
    if not r:
        return None
    lines, tzs = ev_lines(c, r)
    return r, etag(lines, tzs), lines, tzs


def _tr_dt(s):
    s = (s or "").strip()
    try:
        if not 1900 <= int(s[:4] or 0) <= 2999:
            return None
        if re.fullmatch(r"\d{8}T\d{6}Z", s):
            return datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone(TZ).date()
        if re.fullmatch(r"\d{8}", s):
            return datetime.strptime(s, "%Y%m%d").date()
    except (ValueError, OverflowError):
        pass
    return None


def query_filter(root):
    filt = root.find(C_ + "filter")
    if filt is None:
        return lambda m: True
    cal = filt.find(C_ + "comp-filter")
    if cal is None or cal.get("name", "").upper() != "VCALENDAR":
        return lambda m: True
    comps = cal.findall(C_ + "comp-filter")
    if not comps:
        return lambda m: True
    ev = next((x for x in comps if x.get("name", "").upper() == "VEVENT"), None)
    if ev is None or ev.find(C_ + "is-not-defined") is not None:
        return lambda m: False  # VTODO / VJOURNAL: never in an event calendar
    tr_ = ev.find(C_ + "time-range")
    if tr_ is None:
        return lambda m: True
    a = _tr_dt(tr_.get("start")) or date(1900, 1, 1)
    b = _tr_dt(tr_.get("end")) or date(2999, 12, 31)
    if (b - a).days > 3660:  # a very wide window: everything that starts before its end
        return lambda m: m[4]["first_day"] <= b.isoformat()
    return lambda m: bool(ev_expand(m[4], a - timedelta(days=1), b, 1))


def ev_report(c, u, coll, raw):
    root = dav_xml(raw)
    want = dav_report_props(root)
    ec = ev_coll(c, u, coll)
    base = ("calendars", u["username"], coll["key"])
    role = coll["role"]
    if root.tag == C_ + "calendar-multiget":
        pre = urllib.parse.unquote(dav_href(*base, coll=True))
        items = []
        for h in root.findall(D_ + "href"):
            rh = (h.text or "").strip()
            if rh:
                path = urllib.parse.unquote(urllib.parse.urlsplit(rh).path)
                items.append((rh, path, path.rsplit("/", 1)[-1]))

        def gen():
            for rh, path, name in items:
                m = ec.members.get(name) if path.startswith(pre) else None
                if m is None:
                    yield f"<D:response><D:href>{_xe(rh)}</D:href><D:status>HTTP/1.1 404 Not Found</D:status></D:response>"
                else:
                    yield dav_response(dav_href(*base, name), want, props_member(u, m, role))
        return dav_multistatus(gen())
    if root.tag == C_ + "calendar-query":
        ok = query_filter(root)
        return dav_multistatus(dav_response(dav_href(*base, n), want, props_member(u, m, role)) for n, m in ec.members.items() if ok(m))
    if root.tag == D_ + "sync-collection":
        te = root.find(D_ + "sync-token")
        tok = (te.text or "").strip() if te is not None else ""
        lvl = root.find(D_ + "sync-level")
        if lvl is not None and (lvl.text or "").strip() not in ("1", ""):
            raise DavError(403, "Only sync-level 1", "<D:number-of-matches-within-limits/>")
        old = None
        if tok:
            old = sync_load(c, u, coll["key"], tok)
            if old is None:
                raise DavError(403, "Unknown sync-token", "<D:valid-sync-token/>")
        sync_save(c, u, ec)
        new = ec.state()
        changed = [n for n in ec.members if old is None or old.get(n) != new[n]]
        gone = [n for n in (old or {}) if n not in new]

        def gen():
            for n in changed:
                yield dav_response(dav_href(*base, n), want, props_member(u, ec.members[n], role))
            for n in gone:
                yield f"<D:response><D:href>{_xe(dav_href(*base, n))}</D:href><D:status>HTTP/1.1 404 Not Found</D:status></D:response>"
        return dav_multistatus(gen(), f"<D:sync-token>{_xe(ec.token)}</D:sync-token>")
    if root.tag == C_ + "free-busy-query":
        raise DavError(403, "Free / busy is not offered", "<D:supported-report/>")
    raise DavError(403, "Unsupported report", "<D:supported-report/>")


def ev_put(c, u, coll, name):
    if coll["role"] not in ("owner", "edit"):
        raise DavError(403, "Read only", "<D:need-privileges/>")
    if "text/calendar" not in (request.content_type or "text/calendar").lower():
        raise DavError(415, "Expected text/calendar", "<C:supported-calendar-data/>")
    raw = dav_body()
    if len(raw) > DAV_MAX_BODY:
        raise DavError(413, "Too large", "<C:max-resource-size/>")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise DavError(400, "The calendar data must be UTF-8") from None
    try:
        v = read_vevent(text)
    except EvError as e:
        raise DavError(e.code, e.text, e.cond) from None
    except (ValueError, TypeError, OverflowError, KeyError, AttributeError):
        raise DavError(400, "The calendar data could not be read", "<C:valid-calendar-data/>") from None
    have = member_now(c, u, coll, name)
    inm, im = request.headers.get("If-None-Match", "").strip(), request.headers.get("If-Match", "").strip()
    if have and inm == "*":
        raise DavError(412, "The resource exists already")
    if im and (not have or (im != "*" and have[1] not in [x.strip() for x in im.split(",")])):
        raise DavError(412, "The resource was changed meanwhile")
    if have:
        eid = have[0]["id"]
        if v["uid"] != have[0]["uid"] and c.execute("SELECT 1 FROM events WHERE cal_id=? AND uid=? AND id!=? AND deleted_at IS NULL",
                                                    (coll["id"], v["uid"], eid)).fetchone():
            raise DavError(403, "This UID exists already", "<C:no-uid-conflict/>")
        store_parsed(c, u["id"], coll["id"], v, eid=eid)
        if v["uid"] != have[0]["uid"]:
            c.execute("UPDATE events SET uid=? WHERE id=?", (v["uid"], eid))
        c.commit()
        return Response(status=204)
    dup = c.execute("SELECT href FROM events WHERE cal_id=? AND uid=? AND deleted_at IS NULL", (coll["id"], v["uid"])).fetchone()
    if dup:
        href = dav_href("calendars", u["username"], coll["key"], dup[0])
        raise DavError(403, "This UID exists already", f"<C:no-uid-conflict><D:href>{_xe(href)}</D:href></C:no-uid-conflict>")
    old = c.execute("SELECT id FROM events WHERE cal_id=? AND href=? AND deleted_at IS NOT NULL", (coll["id"], name)).fetchone()
    if old:  # a name used by a deleted event: that one is gone for good now
        c.execute("DELETE FROM events WHERE id=?", (old[0],))
    store_parsed(c, u["id"], coll["id"], v, href=name)
    c.commit()
    r = Response(status=201)
    r.headers["Location"] = dav_href("calendars", u["username"], coll["key"], name)
    return r


def evdav(m, c, u, pw_row, kind, key, name):
    """The DAV methods on an event collection (kind evcoll) or one of its resources (kind evmember)."""
    coll = evdav_colls(c, u).get(key)
    if not coll:
        raise DavError(404, "Not found")
    if name is not None and not DAV_NAME_RE.fullmatch(name):
        raise DavError(404, "Not found")
    if m == "PROPFIND":
        want = dav_propfind_req(dav_body())
        deep = request.headers.get("Depth", "1").strip().lower() in ("1", "infinity")
        order = 1000 + list(evdav_colls(c, u)).index(key)
        if kind == "evcoll":
            ec = ev_coll(c, u, coll)
            first = dav_response(coll_href(u, coll), want, props_coll(c, u, coll, order, lambda: ec))

            def gen():
                yield first
                if deep:
                    for n, mm in ec.members.items():
                        yield dav_response(dav_href("calendars", u["username"], key, n), want, props_member(u, mm, coll["role"]))
            return dav_multistatus(gen())
        have = member_now(c, u, coll, name)
        if not have:
            raise DavError(404, "Not found")
        r, et, lines, tzs = have
        return dav_multistatus([dav_response(dav_href("calendars", u["username"], key, name), want,
                                             props_member(u, (r["id"], et, lines, tzs, r), coll["role"]))])
    if m == "REPORT":
        if kind != "evcoll":
            raise DavError(403, "Only on a calendar", "<D:supported-report/>")
        return ev_report(c, u, coll, dav_body())
    if m in ("GET", "HEAD"):
        if kind != "evmember":
            return Response(f"{APP_NAME} CalDAV\n", 200, content_type="text/plain; charset=utf-8")
        have = member_now(c, u, coll, name)
        if not have:
            raise DavError(404, "Not found")
        text = wrap(have[2], have[3])
        r = Response("" if m == "HEAD" else text, 200, content_type="text/calendar; charset=utf-8")
        r.headers["ETag"] = have[1]
        r.headers["Last-Modified"] = email.utils.format_datetime(parse_iso(have[0]["updated_at"]).astimezone(timezone.utc), usegmt=True)
        if m == "HEAD":
            r.headers["Content-Length"] = str(len(text.encode("utf-8")))
        return r
    if m == "PUT":
        if kind == "evmember" and coll["role"] in ("rsvp", "view"):  # 2.155.0 A (#2074): the own answer to an invitation
            return ev_rsvp_put(c, u, coll, name)
        if kind != "evmember":
            raise DavError(405, "PUT works on an event inside a calendar")
        return ev_put(c, u, coll, name)
    if m == "DELETE":
        if kind != "evmember":
            raise DavError(403, "Calendars are deleted in the app")
        if coll["role"] == "rsvp":  # 2.155.0 A (#2074): an invitation removed on the device = declined
            return ev_rsvp_delete(c, u, coll, name)
        if coll["role"] not in ("owner", "edit"):
            raise DavError(403, "Read only", "<D:need-privileges/>")
        have = member_now(c, u, coll, name)
        if not have:
            raise DavError(404, "Not found")
        im = request.headers.get("If-Match", "").strip()
        if im and im != "*" and have[1] not in [x.strip() for x in im.split(",")]:
            raise DavError(412, "The resource was changed meanwhile")
        ev_delete(c, have[0])
        c.commit()
        return Response(status=204)
    if m == "PROPPATCH":
        root = dav_xml(dav_body())
        names = [x.tag for s_ in root for pr in s_ if pr.tag == D_ + "prop" for x in pr if isinstance(x.tag, str)]
        href = coll_href(u, coll) if kind == "evcoll" else dav_href("calendars", u["username"], key, name)
        return dav_multistatus([f"<D:response><D:href>{_xe(href)}</D:href><D:propstat><D:prop>{''.join(_el(n) for n in names)}"
                                "</D:prop><D:status>HTTP/1.1 403 Forbidden</D:status></D:propstat></D:response>"])
    raise DavError(405, "Method not allowed")




# ---- 2.155.0 A (#2074): answers to invitations from a device (PARTSTAT of the own ATTENDEE), 2.155.0 A (#2079): MKCALENDAR
EV_DAVNAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")  # a collection name a client may choose (not e<id> / inv / digits)


def _rsvp_mine(u, raw):
    """The PARTSTAT (app value) the device wrote for the person's own ATTENDEE line, or None (no own line)."""
    me_ = f"urn:kalmido:user:{u['id']}"
    mail = "mailto:" + (u["email"] or "").strip().lower() if u["email"] else None
    for a in raw:
        addr = (a["addr"] or "").strip().lower()
        if str(a.get("kuser") or "") == str(u["id"]) or addr == me_ or (mail and addr == mail):
            return a["partstat"]
    return None


def _rsvp_member(c, u, coll, name, missing=403):
    """(row, etag) of an invitation the person answers, or DavError 403 like before (read-only, no new objects);
    a DELETE of an unknown invitation gets 404 (review 2.155.0), so the device stops repeating it."""
    have = member_now(c, u, coll, name)
    if not have and missing == 404:
        raise DavError(404, "Not found")
    if not have or not c.execute("SELECT 1 FROM event_attendees WHERE event_id=? AND user_id=?", (have[0]["id"], u["id"])).fetchone():
        raise DavError(403, "Read only", "<D:need-privileges/>")
    return have


def ev_rsvp_put(c, u, coll, name):
    """2.155.0 A (#2074): a device answers an invitation by writing the event back with a changed PARTSTAT of the own
    ATTENDEE. Only that answer is taken (op_rsvp, like the answer in the app); every other change (time, title, other
    attendees) is ignored without an error, so the device shows none. A new resource stays refused (403)."""
    from ..events.web import op_rsvp
    have = _rsvp_member(c, u, coll, name)
    if "text/calendar" not in (request.content_type or "text/calendar").lower():
        raise DavError(415, "Expected text/calendar", "<C:supported-calendar-data/>")
    raw = dav_body()
    if len(raw) > DAV_MAX_BODY:
        raise DavError(413, "Too large", "<C:max-resource-size/>")
    try:
        v = read_vevent(raw.decode("utf-8"))
    except UnicodeDecodeError:
        raise DavError(400, "The calendar data must be UTF-8") from None
    except EvError as e:
        raise DavError(e.code, e.text, e.cond) from None
    except (ValueError, TypeError, OverflowError, KeyError, AttributeError):
        raise DavError(400, "The calendar data could not be read", "<C:valid-calendar-data/>") from None
    inm, im = request.headers.get("If-None-Match", "").strip(), request.headers.get("If-Match", "").strip()
    if inm == "*":
        raise DavError(412, "The resource exists already")
    if im and im != "*" and have[1] not in [x.strip() for x in im.split(",")]:
        raise DavError(412, "The resource was changed meanwhile")
    ps = _rsvp_mine(u, v["attendees_raw"])
    eid = have[0]["id"]
    cur = c.execute("SELECT partstat FROM event_attendees WHERE event_id=? AND user_id=?", (eid, u["id"])).fetchone()
    if ps and cur and ps != cur[0]:
        op_rsvp(c, u["id"], eid, {"partstat": ps})
    return Response(status=204)


def ev_rsvp_delete(c, u, coll, name):
    """2.155.0 A (#2074): an invitation deleted on the device counts as declined (the app keeps declined invitations, so
    the event comes back marked as declined with the next sync)."""
    from ..events.web import op_rsvp
    have = _rsvp_member(c, u, coll, name, missing=404)
    im = request.headers.get("If-Match", "").strip()
    if im and im != "*" and have[1] not in [x.strip() for x in im.split(",")]:
        raise DavError(412, "The resource was changed meanwhile")
    cur = c.execute("SELECT partstat FROM event_attendees WHERE event_id=? AND user_id=?", (have[0]["id"], u["id"])).fetchone()
    if cur and cur[0] != "declined":
        op_rsvp(c, u["id"], have[0]["id"], {"partstat": "declined"})
    return Response(status=204)


def _mk_props(root):
    """{property tag: element} of the D:set / D:prop parts of a MKCALENDAR / extended MKCOL body."""
    out = {}
    for s_ in root:
        if s_.tag != D_ + "set":
            continue
        for pr in s_:
            if pr.tag == D_ + "prop":
                out.update({x.tag: x for x in pr if isinstance(x.tag, str)})
    return out


def evdav_mkcal(m, c, u, p):
    """2.155.0 A (#2079): MKCALENDAR (and extended MKCOL with resourcetype calendar, RFC 5689) creates a calendar of the
    person like "new calendar" in the app (cal_create: workspace default, limit, colour). The client's name for it stays
    its address (ev_cals.dav_name). Name, colour, description and the components are taken from the body. A calendar
    only for tasks (VTODO without VEVENT) is refused: task lists are created in the app."""
    from ..core.db import bump
    from ..calendars.caldav import dav_lists
    from ..events.model import cal_create
    parts = [x for x in p.split("/") if x]
    if len(parts) != 3 or parts[0] != "calendars" or parts[1].lower() != u["username"]:
        raise DavError(403, "Create calendars in your calendar home", "<D:resource-must-be-null/>")
    key = parts[2]
    if key in evdav_colls(c, u) or (key.isdigit() and int(key) in dav_lists(c, u)):
        raise DavError(405, "The calendar exists already", "<D:resource-must-be-null/>")
    if not events_on(c, u["id"]):
        raise DavError(403, "Create lists and calendars in the app", "<D:resource-must-be-null/>")
    if not EV_DAVNAME_RE.fullmatch(key) or key.isdigit() or re.fullmatch(r"e\d+|inv", key) \
            or c.execute("SELECT 1 FROM ev_cals WHERE owner_id=? AND dav_name=?", (u["id"], key)).fetchone():
        raise DavError(403, "Choose another name for the calendar", "<D:resource-must-be-null/>")
    raw = dav_body()
    props = _mk_props(dav_xml(raw)) if raw.strip() else {}
    if m == "MKCOL":
        rt = props.get(D_ + "resourcetype")
        if rt is None or rt.find(C_ + "calendar") is None:
            raise DavError(403, "Create lists and calendars in the app", "<D:resource-must-be-null/>")
    comps = props.get(C_ + "supported-calendar-component-set")
    if comps is not None:
        names = {(x.get("name") or "").upper() for x in comps.findall(C_ + "comp")}
        if names and "VEVENT" not in names:
            raise DavError(403, "Create task lists in the app", "<C:supported-calendar-component/>")
    b = {"name": " ".join((props[D_ + "displayname"].text or "").split()) if D_ + "displayname" in props else ""}
    if not b["name"]:
        b["name"] = tr("Calendar")
    col = (props[A_ + "calendar-color"].text or "").strip() if A_ + "calendar-color" in props else ""
    if re.fullmatch(r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", col):
        b["color"] = col[:7]
    if C_ + "calendar-description" in props:
        b["description"] = (props[C_ + "calendar-description"].text or "").strip()
    cid = cal_create(c, u["id"], b)
    try:
        c.execute("UPDATE ev_cals SET dav_name=? WHERE id=?", (key, cid))
    except IntegrityError:  # 2.155.0 review: the same name created at the same time -> 405, the new calendar is rolled back
        c.rollback()
        raise DavError(405, "The calendar exists already") from None
    bump(c)
    c.commit()
    r = Response(status=201)
    r.headers["Location"] = dav_href("calendars", u["username"], key, coll=True)
    r.headers["Cache-Control"] = "no-cache"
    return r
