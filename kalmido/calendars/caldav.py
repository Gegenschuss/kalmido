"""CalDAV server for tasks (VTODO) with app passwords; the /dav/ entry point for event calendars and CardDAV too."""
import email.message
import email.policy
import email.utils
import functools
import hashlib
import html
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib
import icalendar
from datetime import date, datetime, timedelta, timezone
from flask import g, jsonify, redirect, request, Response
from werkzeug.security import check_password_hash, generate_password_hash

from ..core.config import app, APP_NAME, APP_VERSION, PUBLIC_URL, TZ
from ..core.i18n import N_, tr
from ..core.db import (
    body, bump, db, gset, gsetting, inbox_default, iso, iso_ms, local_now, now_utc, parse_iso, usettings,
)
from ..accounts.session import (
    _DUMMY_HASH, _rate_blocked, _rate_fail, _rate_keys, _rate_reset, client_ip, FAIL_WINDOW, me,
)
from ..accounts.login import RC_ALPHABET
from ..core.access import _members_on, collab_all, Denied, plists, pvis, task_visible, tvis, WRITE_ROLES
from ..core.pages import valid_url
from ..tasks.validation import (
    check_parent, CONTENT_MAX, REM_COUNT, REM_MAX, REM_MIN, rr_feasible, rr_norm, rr_problem, TITLE_MAX, valid_date,
)
from ..tasks.tasks import my_tags, task_create, task_update
from ..tasks.lifecycle import task_complete, task_delete, task_reopen, task_restore
from ..personal.timetrack import BadInput
from ..calendars.icalfeed import hm_minutes, ics_dur, ics_fold, ics_rrule, ics_text, ics_utc, ics_vtimezone


# ---------------------------------------------------------------- CalDAV server for tasks (2.9.0, #435)
# /dav/ speaks the part of CalDAV (RFC 4791) and WebDAV sync (RFC 6578) that real task clients use: Reminders on iPhone,
# iPad and Mac, Thunderbird, Evolution, DAVx5 with Tasks.org / jtx Board, the CalDAV account of Tasks.org. Every list
# the person sees (not archived) is one calendar collection that holds VTODOs only; every task (open, or completed /
# won't do within KALMIDO_CALDAV_DONE_DAYS) is one resource. Discovery: /.well-known/caldav -> /dav/,
# current-user-principal, calendar-home-set.
# Login: HTTP Basic with an app password (Settings > Account > App passwords: named, shown once, stored with the same
# KDF as passwords, revocable, last use). Never the account password, never an agent, never the proxy header (DAV
# clients cannot do a browser login, so /dav and /.well-known/caldav must bypass a login proxy). Only while PUBLIC_URL
# is https:// (TLS at the proxy) unless KALMIDO_CALDAV_HTTP=1. Failed logins count like the login
# form (per user name and client address within FAIL_WINDOW) and then lock out with 429. Passwords are never logged.
# Changes run through the app's own views (task_create / task_update / task_complete / task_reopen / task_delete), so
# the list roles (viewers read only, participants only their own tasks), history ("via CalDAV"), News, webhooks and
# agent events behave as in the app; DELETE moves to the trash. Mapping both ways: SUMMARY, DESCRIPTION, DUE / DTSTART
# (date or date-time; any TZID -> the server's time zone), PRIORITY 1-4 / 5 / 6-9 <-> high / medium / low, STATUS +
# COMPLETED + PERCENT-COMPLETE, CATEGORIES <-> my tags, RELATED-TO (parent) <-> subtasks, RRULE (what Kalmido repeats;
# any other rule is kept as it came and only the client repeats it), VALARM with a relative or absolute TRIGGER <->
# reminder offsets, URL. Everything else a client wrote (X- properties, other alarms, SEQUENCE, ...) is stored as it
# came (dav_meta.extra) and sent back, so a round trip loses nothing. A client that never sent CATEGORIES / RELATED-TO
# (Reminders keeps tags and subtasks to itself) does not clear tags or the parent by leaving them out: each app password
# remembers which of the two its client writes (app_passwords.caps).
# ETag = hash of the rendered VTODO; getctag / sync-token = hash of the collection's (href, ETag) set. The last
# DAV_SYNC_KEEP sets per person and list are kept (dav_sync) for the deltas of sync-collection; an unknown token answers
# 403 valid-sync-token and the client loads the collection again. Rendered collections are cached per person, list and
# change counter (settings.version), so the clients' frequent polls cost no rendering.
DAV_ON = os.environ.get("KALMIDO_CALDAV", "1").strip().lower() not in ("0", "false", "no", "off")
DAV_HTTP_OK = os.environ.get("KALMIDO_CALDAV_HTTP", "0").strip().lower() in ("1", "true", "yes", "on")
try:
    DAV_DONE_DAYS = max(0, int(os.environ.get("KALMIDO_CALDAV_DONE_DAYS", "") or 90))
except ValueError:
    DAV_DONE_DAYS = 90
DAV_ROOT = "/dav/"
DAV_MAX_BODY = 1024 * 1024        # one resource / one REPORT body (C:max-resource-size)
DAV_EXTRA_MAX = 16000             # characters of a task's stored extra properties
DAV_SYNC_KEEP = 30                # sync-token states kept per person and list
DAV_RATE = 600                    # requests per app password and minute (a first sync of many lists is bursty)
DAV_MOVE_S = 900                  # a task trashed this recently comes back when a client re-creates it in another list
DAV_TAGS_MAX = 50
APPPW_MAX = 20                    # per person
APPPW_USED_EVERY = 60             # s between two last_used_at updates
APPPW_CACHE_S = 900               # s a verified app password skips the KDF (revoking it still stops it at once)
DAVS_PFX = {"DAV:": "D", "urn:ietf:params:xml:ns:caldav": "C", "http://calendarserver.org/ns/": "CS",
          "http://apple.com/ns/ical/": "A", "urn:ietf:params:xml:ns:carddav": "CR"}
D_, C_, CS_, A_ = "{DAV:}", "{urn:ietf:params:xml:ns:caldav}", "{http://calendarserver.org/ns/}", "{http://apple.com/ns/ical/}"
CR_ = "{urn:ietf:params:xml:ns:carddav}"  # 2.21.0 (#658): CardDAV (contacts/carddav.py)
DAV_METHODS = ["OPTIONS", "PROPFIND", "PROPPATCH", "REPORT", "GET", "HEAD", "PUT", "DELETE", "MKCALENDAR", "MKCOL",
               "MOVE", "COPY", "POST", "LOCK", "UNLOCK", "ACL"]
DAV_ALLOW = "OPTIONS, PROPFIND, PROPPATCH, REPORT, GET, HEAD, PUT, DELETE"
# the UID / resource name of a task no client named: kalmido-<task id>-<instance> (the instance id, random per database,
# keeps tasks of two Kalmido servers in one client apart)
DAV_UID_RE = re.compile(r"kalmido-(\d{1,12})-([0-9a-f]{8})")
DAV_HREF_RE = re.compile(r"kalmido-(\d{1,12})-([0-9a-f]{8})\.ics")
DAV_NAME_RE = re.compile(r"[^/\\\x00-\x1f\x7f]{1,200}")
# properties of a VTODO that map to task fields (everything else is kept in dav_meta.extra)
DAV_MAPPED = {"UID", "DTSTAMP", "CREATED", "LAST-MODIFIED", "SUMMARY", "DESCRIPTION", "DUE", "DTSTART", "PRIORITY",
              "STATUS", "COMPLETED", "PERCENT-COMPLETE", "CATEGORIES", "RELATED-TO", "RRULE", "URL"}
_DAV_CACHE, _DAV_CACHE_LOCK = {}, threading.Lock()
_DAV_VTZ, _DAV_INST = {}, {}
# properties that appear once in a VTODO: a stored copy of one of them yields to the value Kalmido writes
DAV_SINGLE = {"UID", "DTSTAMP", "CREATED", "LAST-MODIFIED", "SUMMARY", "DESCRIPTION", "DUE", "DTSTART", "PRIORITY", "STATUS",
              "COMPLETED", "PERCENT-COMPLETE", "URL", "RRULE"}
_APPPW_OK, _APPPW_LOCK = {}, threading.Lock()


class DavError(Exception):
    """An answer of the DAV handler: status, plain text or a DAV:error precondition element."""
    def __init__(self, code, text="", cond=None):
        super().__init__(text)
        self.code, self.text, self.cond = code, text, cond


def _xe(s):
    return html.escape(str(s), quote=False)


def dav_href(*parts, coll=False):
    path = DAV_ROOT + "/".join(urllib.parse.quote(str(p), safe="@._~+=-:") for p in parts)
    return path + ("/" if coll and parts else "")


def _el(clark, inner=""):
    """An element in Clark notation ({ns}name) with the multistatus prefixes (other namespaces declared inline)."""
    ns, _, name = clark[1:].partition("}") if clark.startswith("{") else ("", "", clark)
    pre = DAVS_PFX.get(ns)
    if pre:
        tag, decl = f"{pre}:{name}", ""
    else:
        tag, decl = f"X:{name}", f' xmlns:X="{html.escape(ns)}"'
    return f"<{tag}{decl}/>" if not inner else f"<{tag}{decl}>{inner}</{tag}>"


MS_HEAD = ('<?xml version="1.0" encoding="utf-8"?>\n<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav" '
           'xmlns:CS="http://calendarserver.org/ns/" xmlns:A="http://apple.com/ns/ical/" xmlns:CR="urn:ietf:params:xml:ns:carddav">')


def dav_response(href, want, avail):
    """One <D:response>: the wanted properties found in avail (clark -> value or callable) under 200, the rest 404."""
    found, missing = [], []
    for k in want:
        if k in avail:
            v = avail[k]
            found.append(_el(k, v() if callable(v) else v))
        else:
            missing.append(_el(k))
    out = f"<D:response><D:href>{_xe(href)}</D:href>"
    if found or not missing:
        out += f"<D:propstat><D:prop>{''.join(found)}</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat>"
    if missing:
        out += f"<D:propstat><D:prop>{''.join(missing)}</D:prop><D:status>HTTP/1.1 404 Not Found</D:status></D:propstat>"
    return out + "</D:response>"


def dav_multistatus(parts, extra_tail=""):
    """207 streamed: the responses (an iterable of strings) in chunks."""
    def gen():
        buf = [MS_HEAD]
        n = len(MS_HEAD)
        for p in parts:
            buf.append(p)
            n += len(p)
            if n > 32768:
                yield "".join(buf)
                buf, n = [], 0
        buf.append(extra_tail + "</D:multistatus>\n")
        yield "".join(buf)
    return Response(gen(), 207, content_type="application/xml; charset=utf-8")


class _NoDtdBuilder(ET.TreeBuilder):
    """Refuses any DOCTYPE while parsing: entity declarations only exist inside one. The parser reports it in every
    encoding (a byte search for "<!ENTITY" misses a UTF-16 body)."""

    def doctype(self, name, pubid, system):
        raise _DtdRefused()


class _DtdRefused(Exception):
    pass


def xml_no_dtd(data):
    """ElementTree root of data; _DtdRefused for a DTD (no entities: billion laughs, XXE), ET.ParseError when broken."""
    p = ET.XMLParser(target=_NoDtdBuilder())  # nosec B314
    p.feed(data)
    return p.close()


def dav_xml(raw):
    """Parses a request body; no DTD / entities (billion laughs), at most DAV_MAX_BODY bytes."""
    if len(raw) > DAV_MAX_BODY:
        raise DavError(413, "Request too large")
    try:
        return xml_no_dtd(raw)
    except _DtdRefused:
        raise DavError(400, "DTDs are not allowed") from None
    except ET.ParseError:
        raise DavError(400, "Invalid XML") from None


def dav_body():
    if (request.content_length or 0) > DAV_MAX_BODY:
        raise DavError(413, "Request too large")
    return request.get_data(cache=False)[:DAV_MAX_BODY + 1]


def _privs(names):
    return "".join(f"<D:privilege><D:{n}/></D:privilege>" for n in names)


def dav_privs(role):
    if role in WRITE_ROLES:
        return _privs(["read", "write", "write-content", "bind", "unbind"])
    if role == "participant":  # their own tasks + new ones (assigned to them); no deleting
        return _privs(["read", "write-content", "bind"])
    return _privs(["read"])


REPORTS_XML = ("<D:supported-report><D:report><C:calendar-query/></D:report></D:supported-report>"
               "<D:supported-report><D:report><C:calendar-multiget/></D:report></D:supported-report>"
               "<D:supported-report><D:report><D:sync-collection/></D:report></D:supported-report>")


def dav_color(v):
    v = str(v or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{3}", v):
        v = "#" + "".join(ch * 2 for ch in v[1:])
    if re.fullmatch(r"#[0-9a-fA-F]{6}", v):
        return v.upper() + "FF"
    return v.upper() if re.fullmatch(r"#[0-9a-fA-F]{8}", v) else ""


def dav_vtz(year=None):
    year = year or local_now().year
    if year not in _DAV_VTZ:
        _DAV_VTZ[year] = ics_vtimezone(TZ, year)
    return _DAV_VTZ[year]


def dav_inst(c):
    """Random id of this database (settings.dav_instance), part of the UIDs Kalmido makes up."""
    if "i" not in _DAV_INST:
        v = gsetting(c, "dav_instance")
        if not re.fullmatch(r"[0-9a-f]{8}", v or ""):
            v = secrets.token_hex(4)
            gset(c, "dav_instance", v)
            c.commit()
        _DAV_INST["i"] = v
    return _DAV_INST["i"]


def dav_uid_of(tid, meta):
    return (meta["uid"] if meta is not None and meta["uid"] else None) or f"kalmido-{tid}-{_DAV_INST.get('i', '00000000')}"


def dav_name_of(tid, meta):
    return (meta["href"] if meta is not None and meta["href"] else None) or f"kalmido-{tid}-{_DAV_INST.get('i', '00000000')}.ics"


def _own_id(rx, s):
    """The task id in a made-up UID / name of THIS server, else None."""
    m = rx.fullmatch(s or "")
    return int(m.group(1)) if m and m.group(2) == _DAV_INST.get("i") else None


def dav_lname(r):
    return tr("Inbox") if r["is_inbox"] and inbox_default(r["name"]) else r["name"]


# ---- app passwords
def apppw_norm(s):
    return re.sub(r"[\s-]", "", str(s or "")).lower()


def apppw_new():
    raw = "".join(secrets.choice(RC_ALPHABET) for _ in range(20))  # 20 x 31 symbols ~ 99 bits
    return "-".join(raw[i:i + 5] for i in range(0, 20, 5))


def apppw_public(r):
    return {"id": r["id"], "name": r["name"], "created_at": r["created_at"], "last_used_at": r["last_used_at"],
            "last_client": r["last_client"] or ""}


def need_dav():
    if not DAV_ON:
        raise Denied(409, tr("CalDAV is turned off on this server"))


def dav_info(u):
    base = PUBLIC_URL.rstrip("/")
    return {"enabled": DAV_ON, "url": base + DAV_ROOT, "server": urllib.parse.urlsplit(base).netloc or base,
            "username": u["username"], "principal": base + dav_href("principals", u["username"], coll=True),
            "home": base + dav_href("calendars", u["username"], coll=True), "done_days": DAV_DONE_DAYS}


def apppw_list(c, uid):
    return [apppw_public(r) for r in c.execute("SELECT * FROM app_passwords WHERE user_id=? ORDER BY id DESC", (uid,))]


def apppw_create(c, u, name):
    """-> (row dict, password). The password is shown this once; only its KDF hash is stored."""
    from ..agents.core import is_agent
    need_dav()
    if is_agent(u):
        raise Denied(403, tr("Agents cannot use calendar apps"))
    name = str(name or "").strip()[:60]
    if not name:
        raise BadInput(tr("Name missing"))
    if c.execute("SELECT COUNT(*) FROM app_passwords WHERE user_id=?", (u["id"],)).fetchone()[0] >= APPPW_MAX:
        raise Denied(409, tr("At most {0} app passwords", APPPW_MAX))
    pw = apppw_new()
    pid = c.execute("INSERT INTO app_passwords(user_id,name,pw_hash,created_at) VALUES(?,?,?,?)",
                    (u["id"], name, generate_password_hash(apppw_norm(pw)), iso(now_utc()))).lastrowid
    c.commit()
    print("app password", pid, "created for user", u["id"], flush=True)
    return apppw_public(c.execute("SELECT * FROM app_passwords WHERE id=?", (pid,)).fetchone()), pw


def apppw_delete(c, uid, pid):
    if not c.execute("DELETE FROM app_passwords WHERE id=? AND user_id=?", (pid, uid)).rowcount:
        raise Denied(404)
    c.commit()
    with _APPPW_LOCK:
        for k in [k for k in _APPPW_OK if k[0] == pid]:
            _APPPW_OK.pop(k, None)


@app.get("/api/me/app-passwords")
def apppw_get():
    c = db()
    return jsonify(caldav=dav_info(g.user), items=apppw_list(c, me()), max=APPPW_MAX)


@app.post("/api/me/app-passwords")
def apppw_post():
    row, pw = apppw_create(db(), g.user, body().get("name"))
    return jsonify({**row, "password": pw}), 201


@app.delete("/api/me/app-passwords/<int:pid>")
def apppw_del(pid):
    apppw_delete(db(), me(), pid)
    return jsonify(ok=True)


# ---- login
def dav_secure():
    """HTTP Basic only where the clients' address is https. 2.10.0 (#445): a trusted proxy (KALMIDO_TRUSTED_PROXIES) tells
    the scheme in X-Forwarded-Proto (https -> request.is_secure; http -> refused unless KALMIDO_CALDAV_HTTP=1). Without that
    header (a direct request, or a proxy that does not send it) as before: PUBLIC_URL https:// (TLS ends at the proxy) or
    KALMIDO_CALDAV_HTTP=1 (a plain-http setup inside a trusted network, on the operator's own decision)."""
    if request.is_secure:
        return True
    if request.environ.get("kalmido.fwd_proto"):
        return DAV_HTTP_OK
    return PUBLIC_URL.lower().startswith("https://") or DAV_HTTP_OK


def dav_401():
    r = Response("Authentication required: your user name and an app password (Settings > Account > App passwords)\n",
                 401, content_type="text/plain; charset=utf-8")
    r.headers["WWW-Authenticate"] = f'Basic realm="{APP_NAME}", charset="UTF-8"'
    return r


def dav_login():
    """The person of this request (HTTP Basic: user name + app password) or raises DavError / returns a 401."""
    from ..notify.alerts import aa_count, aa_now
    from ..api.v1 import hit_limit
    from ..agents.core import is_agent
    if not dav_secure():
        raise DavError(403, "CalDAV needs HTTPS")
    a = request.authorization
    if not a or (a.type or "").lower() != "basic" or not a.username:
        return None
    username = a.username.strip().lower()[:64]
    pw = apppw_norm(a.password)[:100]
    keys = _rate_keys(username, "dav:", (10, 30, 150))
    if _rate_blocked(keys):
        raise DavError(429, "Too many failed logins, please wait a few minutes")
    c = db()
    u = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    rows = c.execute("SELECT * FROM app_passwords WHERE user_id=? ORDER BY id DESC", (u["id"],)).fetchall() \
        if u and not u["disabled"] and not is_agent(u) and pw else []
    hit, ph, now = None, hashlib.sha256(pw.encode()).hexdigest(), time.monotonic()
    for r in rows:
        k = (r["id"], r["pw_hash"], ph)
        with _APPPW_LOCK:
            cached = _APPPW_OK.get(k, 0) > now
        if cached or check_password_hash(r["pw_hash"], pw):
            hit = r
            with _APPPW_LOCK:
                if len(_APPPW_OK) > 5000:
                    _APPPW_OK.clear()
                _APPPW_OK[k] = now + APPPW_CACHE_S
            break
    if not rows:
        check_password_hash(_DUMMY_HASH, pw or "x")  # same cost for an unknown user / no app password
    if not hit:
        for k in _rate_fail(keys):
            if k.startswith("dav:ip:"):
                aa_now("security", "ratelimit:" + k, N_("Login rate limit reached for IP {0} (logins refused for {1} min)."),
                       [client_ip(), FAIL_WINDOW // 60])
            elif u:
                aa_now("security", "ratelimit:" + k, N_("Login rate limit reached for user {0} (logins refused for {1} min)."),
                       [username, FAIL_WINDOW // 60])
            else:
                aa_now("security", "ratelimit:dav:u:?",
                       N_("Login rate limit reached for an unknown user name (logins refused for {0} min)."), [FAIL_WINDOW // 60])
        aa_count("security", "logins", client_ip(), user=("caldav:" + username) if u else "caldav:?")
        print("caldav login failed for", repr(username), "from", client_ip(), flush=True)
        return None
    _rate_reset(username, "dav:")
    if hit_limit(f"dav:{hit['id']}", DAV_RATE):
        raise DavError(429, "Too many requests, please slow down")
    last = hit["last_used_at"]
    if not last or (now_utc() - parse_iso(last)).total_seconds() >= APPPW_USED_EVERY:
        ua = re.sub(r"[\x00-\x1f\x7f]", "", request.headers.get("User-Agent", ""))[:120]
        c.execute("UPDATE app_passwords SET last_used_at=?, last_client=? WHERE id=?", (iso(now_utc()), ua, hit["id"]))
        c.commit()
    return u, hit


# ---- rendering
def dav_vtodo(t, ctx):
    """The VTODO lines of a task (unfolded) and whether they use the server's TZID."""
    tid, meta = t["id"], ctx["meta"].get(t["id"])
    key = getattr(TZ, "key", "UTC")
    stamp = ics_utc(parse_iso(t["updated_at"]))
    L = ["BEGIN:VTODO", f"UID:{ics_text(dav_uid_of(tid, meta))}", f"DTSTAMP:{stamp}",
         f"CREATED:{ics_utc(parse_iso(t['created_at']))}", f"LAST-MODIFIED:{stamp}", f"SUMMARY:{ics_text(t['title'])}"]
    hide = tid in ctx["context"]  # a participant's context task: no notes / link
    if (t["content"] or "").strip() and not hide:
        L.append(f"DESCRIPTION:{ics_text(t['content'])}")
    timed = bool(t["due"] and t["due_time"])
    anchor = None
    if t["due"]:
        d = date.fromisoformat(t["due"])
        if timed:
            hh, mm = map(int, t["due_time"].split(":"))
            anchor = datetime(d.year, d.month, d.day, hh, mm)
            L.append(f"DUE;TZID={key}:{anchor:%Y%m%dT%H%M%S}")
        else:
            anchor = datetime(d.year, d.month, d.day)
            L.append(f"DUE;VALUE=DATE:{d:%Y%m%d}")
        st = t["start"] if t["start"] and t["start"] < t["due"] else (t["due"] if t["repeat"] else None)
        if st:
            s = date.fromisoformat(st)
            if st == t["due"]:
                L.append(L[-1].replace("DUE", "DTSTART", 1))
            else:
                anchor = datetime(s.year, s.month, s.day)
                L.append(f"DTSTART;TZID={key}:{s:%Y%m%d}T000000" if timed else f"DTSTART;VALUE=DATE:{s:%Y%m%d}")
    prio = {5: 1, 3: 5, 1: 9}.get(t["priority"])
    if prio:
        L.append(f"PRIORITY:{prio}")
    if t["status"] == 2:
        L += ["STATUS:COMPLETED", f"COMPLETED:{ics_utc(parse_iso(t['completed_at'] or t['updated_at']))}", "PERCENT-COMPLETE:100"]
    elif t["status"] == -1:
        L.append("STATUS:CANCELLED")
    else:
        L.append("STATUS:NEEDS-ACTION")
    tags = ctx["tags"].get(tid)
    if tags:
        L.append("CATEGORIES:" + ",".join(ics_text(x) for x in tags))
    if t["parent_id"]:
        L.append(f"RELATED-TO;RELTYPE=PARENT:{ics_text(ctx['uid'](t['parent_id']))}")
    elif meta is not None and meta["parent_uid"]:  # its parent has not arrived yet: kept as the client wrote it
        L.append(f"RELATED-TO;RELTYPE=PARENT:{ics_text(meta['parent_uid'])}")
    if t["url"] and not hide:
        L.append(f"URL:{t['url']}")
    own_rule = False
    if t["repeat"] and anchor is not None:
        rule, _ = ics_rrule(t["repeat"], anchor, timed)
        if rule:
            L.append(f"RRULE:{rule}")
            own_rule = True
    if t["due"] and t["reminders"]:
        base = 0 if timed else ctx["allday"]
        for off in str(t["reminders"]).split(","):
            if re.fullmatch(r"-?\d{1,7}", off.strip()):
                L += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{ics_text(t['title'])}",
                      f"TRIGGER;RELATED=END:{ics_dur(base - int(off))}", "END:VALARM"]
    if meta is not None and meta["extra"]:
        have, depth = {_prop_name(x) for x in L}, 0
        for x in meta["extra"].split("\n"):
            if not x:
                continue
            up = x[:6].upper()
            if depth == 0 and up != "BEGIN:":
                n = _prop_name(x)
                if (n in DAV_SINGLE and n in have) or (own_rule and n in ("EXRULE", "RDATE", "EXDATE")):
                    continue
            depth += 1 if up == "BEGIN:" else -1 if x[:4].upper() == "END:" else 0
            L.append(x)
    L.append("END:VTODO")
    return L, timed or any(";TZID=" in x for x in L)


def dav_wrap(lines, tz):
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//{APP_NAME}//CalDAV {APP_VERSION}//EN", "CALSCALE:GREGORIAN"]
    out += (dav_vtz() if tz else []) + lines + ["END:VCALENDAR"]
    return "\r\n".join(ics_fold(x) for x in out) + "\r\n"


def dav_etag(lines, tz):
    return '"' + hashlib.sha1(("\n".join(lines) + ("|tz" if tz else "")).encode("utf-8"), usedforsecurity=False).hexdigest()[:24] + '"'


def dav_lists(c, u):
    """{list id: row (+ role)} of the lists that are calendars for u: visible, not archived."""
    rows = c.execute(f"""SELECT l.id, l.name, l.color, l.sort, l.is_inbox, l.owner_id, l.created_at, m.role AS m_role
                         FROM lists l LEFT JOIN list_members m ON m.list_id=l.id AND m.user_id=?
                         WHERE l.archived=0 AND (l.owner_id=? OR (m.user_id IS NOT NULL{_members_on()}))
                         ORDER BY l.is_inbox DESC, COALESCE(m.sort, l.sort), l.id""", (u["id"], u["id"])).fetchall()
    out = {}
    for r in rows:
        role = "owner" if r["owner_id"] == u["id"] else r["m_role"]
        if role:
            out[r["id"]] = {**dict(r), "role": role}
    return out


def dav_done_cutoff():
    d = local_now().date() - timedelta(days=DAV_DONE_DAYS)
    return iso(datetime(d.year, d.month, d.day, tzinfo=TZ).astimezone(timezone.utc))


def dav_ctx(c, u, task_ids):
    """Rendering context of these tasks for u (bulk: one query per kind, never per task)."""
    ids = list(task_ids)
    meta, tags = {}, {}
    for i in range(0, len(ids), 900):
        part = ids[i:i + 900]
        q = ",".join("?" * len(part))
        for r in c.execute(f"SELECT * FROM dav_meta WHERE task_id IN ({q})", part):
            meta[r["task_id"]] = r
        for r in c.execute(f"SELECT task_id, tag FROM task_tags WHERE user_id=? AND task_id IN ({q}) ORDER BY tag", [u["id"], *part]):
            tags.setdefault(r["task_id"], []).append(r["tag"])
    extra_meta = {}

    def uid(pid):
        if pid in meta:
            return dav_uid_of(pid, meta[pid])
        if pid not in extra_meta:
            extra_meta[pid] = c.execute("SELECT * FROM dav_meta WHERE task_id=?", (pid,)).fetchone()
        return dav_uid_of(pid, extra_meta[pid])
    s = usettings(c, u["id"])
    return {"meta": meta, "tags": tags, "uid": uid, "allday": hm_minutes(s.get("allday_time") or "09:00"), "context": set()}


class DavColl:
    """One list as a calendar collection for one person: members {name: (task id, etag, lines, tz, row)}, token."""
    def __init__(self, lst, members):
        self.lst, self.members = lst, members
        h = hashlib.sha1(usedforsecurity=False)
        for name in sorted(members):
            h.update(f"{name}\0{members[name][1]}\n".encode("utf-8"))
        self.hash = h.hexdigest()[:20]
        self.token = f"urn:kalmido:sync:{lst['id']}-{self.hash}"
        self.ctag = '"' + self.hash + '"'

    def state(self):
        return {n: m[1] for n, m in self.members.items()}


def dav_coll(c, u, lst):
    """The rendered collection of list lst for u (cached per person, list, change counter and day)."""
    key = (u["id"], lst["id"], gsetting(c, "version"), dav_done_cutoff(), lst["name"], lst["color"], lst["role"], collab_all())
    now = time.monotonic()
    with _DAV_CACHE_LOCK:
        hit = _DAV_CACHE.get(key)
        if hit and hit[0] > now:
            return hit[1]
    uid = u["id"]
    pl = plists(c, uid)
    rows = c.execute(f"""SELECT * FROM tasks t WHERE t.list_id=? AND t.deleted_at IS NULL
                         AND (t.status=0 OR COALESCE(t.completed_at, t.updated_at)>=?) AND {tvis(c, uid, 't.')}
                         ORDER BY t.id""", (lst["id"], dav_done_cutoff())).fetchall()
    ctx = dav_ctx(c, u, [r["id"] for r in rows])
    if lst["id"] in pl:
        _, _, ctx["context"] = pvis(c, uid, lst["id"])
    members = {}
    for t in rows:
        try:
            lines, tz = dav_vtodo(t, ctx)
        except (ValueError, TypeError) as e:  # one broken row never breaks the collection
            print("caldav: skipping task", t["id"], e, flush=True)
            continue
        members[dav_name_of(t["id"], ctx["meta"].get(t["id"]))] = (t["id"], dav_etag(lines, tz), lines, tz, t)
    coll = DavColl(lst, members)
    with _DAV_CACHE_LOCK:
        if len(_DAV_CACHE) > 64:
            for k in sorted(_DAV_CACHE, key=lambda k: _DAV_CACHE[k][0])[:16]:
                _DAV_CACHE.pop(k, None)
        _DAV_CACHE[key] = (now + 60, coll)
    return coll


def dav_sync_save(c, u, coll):
    if c.execute("SELECT 1 FROM dav_sync WHERE user_id=? AND list_id=? AND token=?", (u["id"], coll.lst["id"], coll.hash)).fetchone():
        return coll.token
    blob = zlib.compress(json.dumps(coll.state(), separators=(",", ":")).encode("utf-8"))
    c.execute("INSERT OR REPLACE INTO dav_sync(user_id,list_id,token,state,created_at) VALUES(?,?,?,?,?)",
              (u["id"], coll.lst["id"], coll.hash, blob, iso_ms(now_utc())))
    c.execute("""DELETE FROM dav_sync WHERE user_id=? AND list_id=? AND token NOT IN
                 (SELECT token FROM dav_sync WHERE user_id=? AND list_id=? ORDER BY created_at DESC LIMIT ?)""",
              (u["id"], coll.lst["id"], u["id"], coll.lst["id"], DAV_SYNC_KEEP))
    c.commit()
    return coll.token


def dav_sync_load(c, u, lid, token):
    m = re.fullmatch(r"urn:kalmido:sync:(\d+)-([0-9a-f]{20})", token or "")
    if not m or int(m.group(1)) != lid:
        return None
    r = c.execute("SELECT state FROM dav_sync WHERE user_id=? AND list_id=? AND token=?", (u["id"], lid, m.group(2))).fetchone()
    try:
        return json.loads(zlib.decompress(r["state"]).decode("utf-8")) if r else None
    except (zlib.error, ValueError):
        return None


# ---- properties
def dav_principal_href(u):
    return dav_href("principals", u["username"], coll=True)


def dav_home_href(u):
    return dav_href("calendars", u["username"], coll=True)


def dav_common(u):
    return {D_ + "current-user-principal": f"<D:href>{_xe(dav_principal_href(u))}</D:href>",
            D_ + "principal-collection-set": f"<D:href>{_xe(dav_href('principals', coll=True))}</D:href>"}


def dav_props_root(u):
    from ..contacts.carddav import ab_home_href
    return {**dav_common(u), D_ + "resourcetype": "<D:collection/>", D_ + "displayname": _xe(APP_NAME),
            C_ + "calendar-home-set": f"<D:href>{_xe(dav_home_href(u))}</D:href>",
            CR_ + "addressbook-home-set": f"<D:href>{_xe(ab_home_href(u))}</D:href>",
            D_ + "current-user-privilege-set": _privs(["read"])}


def dav_props_principal(u):
    from ..contacts.carddav import ab_home_href
    addr = [f"<D:href>{_xe(dav_principal_href(u))}</D:href>", f"<D:href>urn:kalmido:user:{u['id']}</D:href>"]
    if u["email"]:
        addr.insert(0, f"<D:href>mailto:{_xe(u['email'])}</D:href>")
    return {**dav_common(u), D_ + "resourcetype": "<D:collection/><D:principal/>",
            CR_ + "addressbook-home-set": f"<D:href>{_xe(ab_home_href(u))}</D:href>",
            D_ + "displayname": _xe(u["display_name"] or u["username"]),
            D_ + "principal-URL": f"<D:href>{_xe(dav_principal_href(u))}</D:href>",
            C_ + "calendar-home-set": f"<D:href>{_xe(dav_home_href(u))}</D:href>",
            C_ + "calendar-user-address-set": "".join(addr), C_ + "calendar-user-type": "INDIVIDUAL",
            D_ + "current-user-privilege-set": _privs(["read"])}


def dav_props_home(u):
    return {**dav_common(u), D_ + "resourcetype": "<D:collection/>", D_ + "displayname": _xe(APP_NAME),
            D_ + "owner": f"<D:href>{_xe(dav_principal_href(u))}</D:href>",
            D_ + "current-user-privilege-set": _privs(["read"])}


def dav_props_cal(c, u, lst, order, coll_fn):
    color = dav_color(lst["color"])
    p = {**dav_common(u), D_ + "resourcetype": "<D:collection/><C:calendar/>", D_ + "displayname": _xe(dav_lname(lst)),
         D_ + "owner": f"<D:href>{_xe(dav_principal_href(u))}</D:href>",
         C_ + "supported-calendar-component-set": '<C:comp name="VTODO"/>',
         C_ + "supported-calendar-data": '<C:calendar-data content-type="text/calendar" version="2.0"/>',
         C_ + "max-resource-size": str(DAV_MAX_BODY), D_ + "supported-report-set": REPORTS_XML,
         D_ + "current-user-privilege-set": dav_privs(lst["role"]), A_ + "calendar-order": str(order),
         C_ + "calendar-timezone": lambda: _xe(dav_wrap([], True)),
         CS_ + "getctag": lambda: _xe(coll_fn().ctag), D_ + "sync-token": lambda: _xe(dav_sync_save(c, u, coll_fn())),
         D_ + "getcontenttype": "text/calendar; charset=utf-8"}
    if color:
        p[A_ + "calendar-color"] = color
    return p


def dav_props_member(u, m, role):
    tid, etag, lines, tz, t = m
    body = []

    def data():
        if not body:
            body.append(dav_wrap(lines, tz))
        return body[0]
    return {**dav_common(u), D_ + "resourcetype": "", D_ + "getetag": _xe(etag),
            D_ + "getcontenttype": "text/calendar; charset=utf-8; component=VTODO",
            D_ + "getlastmodified": email.utils.format_datetime(parse_iso(t["updated_at"]).astimezone(timezone.utc), usegmt=True),
            D_ + "getcontentlength": lambda: str(len(data().encode("utf-8"))),
            C_ + "calendar-data": lambda: _xe(data()), D_ + "current-user-privilege-set": dav_privs(role),
            D_ + "owner": f"<D:href>{_xe(dav_principal_href(u))}</D:href>"}


ALLPROP = [D_ + "resourcetype", D_ + "displayname", D_ + "getetag", D_ + "getcontenttype", D_ + "getlastmodified",
           D_ + "current-user-principal", D_ + "owner", C_ + "supported-calendar-component-set", CS_ + "getctag",
           D_ + "sync-token", A_ + "calendar-color"]


def dav_propfind_req(raw):
    if not raw.strip():
        return ALLPROP
    root = dav_xml(raw)
    if root.tag != D_ + "propfind":
        raise DavError(400, "Expected DAV:propfind")
    for ch in root:
        if ch.tag == D_ + "prop":
            return [x.tag for x in ch if isinstance(x.tag, str)]
        if ch.tag in (D_ + "allprop", D_ + "propname"):
            return ALLPROP
    return ALLPROP


# ---- resolving paths and tasks
def dav_path(p, u):
    """-> (kind, list id, resource name). kind: root | principals | principal | calendars | home | cal | member."""
    parts = [x for x in p.split("/") if x]
    if not parts:
        return "root", None, None
    if parts[0] == "principals":
        if len(parts) == 1:
            return "principals", None, None
        if len(parts) == 2 and parts[1].lower() == u["username"]:
            return "principal", None, None
        raise DavError(404, "Not found")
    if parts[0] == "calendars":
        if len(parts) == 1:
            return "calendars", None, None
        if parts[1].lower() != u["username"] or len(parts) > 4:
            raise DavError(404, "Not found")
        if len(parts) == 2:
            return "home", None, None
        if re.fullmatch(r"e\d{1,12}|inv", parts[2]):  # 2.21.0 (#659): an event calendar / the invitations (events/dav.py)
            return ("evcoll", parts[2], None) if len(parts) == 3 else ("evmember", parts[2], parts[3])
        if not parts[2].isdigit():
            raise DavError(404, "Not found")
        if len(parts) == 3:
            return "cal", int(parts[2]), None
        if not DAV_NAME_RE.fullmatch(parts[3]):
            raise DavError(404, "Not found")
        return "member", int(parts[2]), parts[3]
    raise DavError(404, "Not found")


def dav_find_name(c, lid, name):
    """The (not deleted) task of list lid stored under this resource name, or None."""
    r = c.execute("""SELECT t.id FROM dav_meta m JOIN tasks t ON t.id=m.task_id
                     WHERE m.href=? AND t.list_id=? AND t.deleted_at IS NULL""", (name, lid)).fetchone()
    if r:
        return r[0]
    own = _own_id(DAV_HREF_RE, name)
    if own:
        r = c.execute("""SELECT t.id FROM tasks t LEFT JOIN dav_meta d ON d.task_id=t.id WHERE t.id=? AND t.list_id=?
                         AND t.deleted_at IS NULL AND (d.href IS NULL OR d.href=?)""", (own, lid, name)).fetchone()
        if r:
            return r[0]
    return None


def dav_find_uid(c, uid_, lid=None, trashed_since=None):
    """Task ids carrying this UID (in list lid first), live ones (and trashed ones since trashed_since)."""
    ids = [r[0] for r in c.execute("""SELECT t.id FROM dav_meta m JOIN tasks t ON t.id=m.task_id WHERE m.uid=?
                                      AND (t.deleted_at IS NULL OR t.deleted_at>=?) ORDER BY t.list_id=? DESC, t.id""",
                                   (uid_, trashed_since or "9999", lid or 0))]
    own = _own_id(DAV_UID_RE, uid_)
    if own:
        r = c.execute("""SELECT t.id FROM tasks t LEFT JOIN dav_meta d ON d.task_id=t.id WHERE t.id=? AND d.uid IS NULL
                         AND (t.deleted_at IS NULL OR t.deleted_at>=?)""", (own, trashed_since or "9999")).fetchone()
        if r and r[0] not in ids:
            ids.append(r[0])
    return ids


def dav_member(c, u, lst, name):
    """(task row, etag, lines, tz) of a resource, rendered fresh (writes compare against the current state)."""
    tid = dav_find_name(c, lst["id"], name)
    if not tid:
        return None
    t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    if not task_visible(c, tid, u["id"]):
        return None
    ctx = dav_ctx(c, u, [tid])
    if lst["role"] == "participant":
        _, _, ctx["context"] = pvis(c, u["id"], lst["id"])
    lines, tz = dav_vtodo(t, ctx)
    return t, dav_etag(lines, tz), lines, tz


# ---- reading a VTODO from a client
def _ics_unfold(text):
    return re.sub(r"\r?\n[ \t]", "", text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")).split("\r\n")


def dav_split(text):
    """Raw content lines of every VTODO (top level lines, VALARM blocks) in document order, plus the other components
    of the calendar (to refuse events)."""
    todos, kinds, depth, cur, sub = [], set(), 0, None, None
    for line in _ics_unfold(text):
        if not line.strip():
            continue
        up = line.upper()
        if up.startswith("BEGIN:"):
            depth += 1
            comp = up[6:].strip()
            if depth == 2:
                kinds.add(comp)
                if comp == "VTODO":
                    cur = {"lines": [], "alarms": [], "blocks": []}
                continue
            if cur is not None:
                if depth == 3:
                    sub = [line]
                    (cur["alarms"] if comp == "VALARM" else cur["blocks"]).append(sub)
                elif sub is not None:
                    sub.append(line)
            continue
        if up.startswith("END:"):
            if depth == 2 and cur is not None:
                todos.append(cur)
                cur = None
            elif depth == 3 and sub is not None:
                sub.append(line)
                sub = None
            elif depth > 3 and sub is not None:
                sub.append(line)
            depth = max(0, depth - 1)
            continue
        if cur is not None:
            if depth == 2:
                cur["lines"].append(line)
            elif sub is not None:
                sub.append(line)
    return todos, kinds


def _prop_name(line):
    return re.split(r"[;:]", line, maxsplit=1)[0].strip().upper()


def _prop_params(line):
    head = line.split(":", 1)[0]
    return {k.strip().upper(): v.strip().strip('"').upper() for k, _, v in (p.partition("=") for p in head.split(";")[1:])}


def dav_read(raw, allday_min):
    """A client's VTODO -> the task values it describes (see dav_apply). DavError for what cannot be stored."""
    from ..integrations.importers import _ics_val, imp_local
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise DavError(400, "The calendar data must be UTF-8") from None
    if "BEGIN:VCALENDAR" not in text[:2000].upper():
        raise DavError(415, "Expected text/calendar", "<C:supported-calendar-data/>")
    todos_raw, kinds = dav_split(text)
    if kinds - {"VTODO", "VTIMEZONE"}:
        raise DavError(403, "Only tasks (VTODO)", "<C:supported-calendar-component/>")
    try:
        cal = icalendar.Calendar.from_ical(text)
        todos = list(cal.walk("VTODO"))
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise DavError(400, "The calendar data could not be read", "<C:valid-calendar-data/>") from None
    if not todos or len(todos) != len(todos_raw):
        raise DavError(400, "No task in the calendar data", "<C:valid-calendar-data/>")
    masters = [i for i, td in enumerate(todos) if td.get("RECURRENCE-ID") is None]
    if len(masters) != 1:
        raise DavError(400, "Exactly one task per resource", "<C:valid-calendar-object-resource/>")
    td, rw = todos[masters[0]], todos_raw[masters[0]]
    uid_ = str(td.get("UID") or "").strip()[:250]
    if not uid_:
        raise DavError(400, "UID missing", "<C:valid-calendar-object-resource/>")
    if any(str(x.get("UID") or "").strip()[:250] != uid_ for x in todos):
        raise DavError(400, "One UID per resource", "<C:valid-calendar-object-resource/>")
    keep, mapped = [], set()  # raw lines kept as they came / names that went into task fields
    v = {"uid": uid_, "title": (str(td.get("SUMMARY") or "").strip() or tr("(untitled)"))[:TITLE_MAX],
         "content": str(td.get("DESCRIPTION") or "")[:CONTENT_MAX], "priority": 0}
    try:
        p = int(td.get("PRIORITY") or 0)
        v["priority"] = 5 if 1 <= p <= 4 else 3 if p == 5 else 1 if 6 <= p <= 9 else 0
    except (TypeError, ValueError):
        pass
    due, start = _ics_val(td.get("DUE")), _ics_val(td.get("DTSTART"))
    v["due"], v["due_time"] = imp_local(due)
    if v["due"] and not valid_date(v["due"]):
        v["due"], v["due_time"] = None, None
    v["start"] = None
    if start is not None:
        sd, _ = imp_local(start)
        if v["due"] and sd and valid_date(sd) and sd <= v["due"]:
            v["start"] = sd
            mapped.add("DTSTART")
    st = str(td.get("STATUS") or "").strip().upper()
    comp = _ics_val(td.get("COMPLETED"))
    try:
        pct = int(td.get("PERCENT-COMPLETE")) if td.get("PERCENT-COMPLETE") is not None else None
    except (TypeError, ValueError):
        pct = None
    v["status"] = -1 if st == "CANCELLED" else 2 if st == "COMPLETED" else 0 if st in ("NEEDS-ACTION", "IN-PROCESS") \
        else 2 if comp is not None or pct == 100 else 0
    if isinstance(comp, datetime):
        comp = comp if comp.tzinfo else comp.replace(tzinfo=TZ)
    elif isinstance(comp, date):
        comp = datetime(comp.year, comp.month, comp.day, tzinfo=TZ)
    v["completed_at"] = iso((comp or now_utc()).astimezone(timezone.utc)) if v["status"] != 0 else None
    cats = td.get("CATEGORIES")
    if cats is not None:
        tags = []
        for cv in (cats if isinstance(cats, list) else [cats]):
            tags += [str(x).strip().lstrip("#")[:100] for x in getattr(cv, "cats", []) if str(x).strip().lstrip("#")]
        v["tags"] = list(dict.fromkeys(tags))[:DAV_TAGS_MAX]
    v["parent_uid"] = ""
    v["url"] = None
    v["repeat"] = ""
    for line in rw["lines"]:
        name = _prop_name(line)
        if name == "RELATED-TO":
            if _prop_params(line).get("RELTYPE", "PARENT") == "PARENT" and not v["parent_uid"]:
                v["parent_uid"] = icalendar.prop.vText.from_ical(line.split(":", 1)[1]).strip()[:250]
                mapped.add("RELATED-TO")
                continue
            keep.append(line)
        elif name == "URL":
            u_ = line.split(":", 1)[1].strip()
            if not v["url"] and valid_url(u_) and len(u_) <= 2000:
                v["url"] = u_
            else:
                keep.append(line)
        elif name == "RRULE":
            rule = rr_norm(line.split(":", 1)[1])
            if not v["repeat"] and rule and v["due"] and not rr_problem(rule) and rr_feasible(rule, v["due"]):
                v["repeat"] = rule
            else:
                keep.append(line)
        elif name == "DTSTART":
            if "DTSTART" not in mapped and not (v["due"] and imp_local(start)[0] == v["due"]):
                keep.append(line)  # a start without a due date (Kalmido needs one): kept for the client
        elif name not in DAV_MAPPED:
            keep.append(line)
    # reminders: VALARMs with a TRIGGER that fits an offset from the due date; the others are kept as they came
    rems = []
    alarms = list(td.walk("VALARM"))
    for i, block in enumerate(rw["alarms"]):
        al = alarms[i] if i < len(alarms) else None
        off = None
        trig = al.get("TRIGGER") if al is not None else None
        tv = _ics_val(trig)
        if v["due"] and trig is not None and tv is not None:
            due_d = date.fromisoformat(v["due"])
            if v["due_time"]:
                hh, mm = map(int, v["due_time"].split(":"))
                due_dt = datetime(due_d.year, due_d.month, due_d.day, hh, mm, tzinfo=TZ)
                fire_ref = due_dt
            else:
                due_dt = datetime(due_d.year, due_d.month, due_d.day, tzinfo=TZ)  # DUE;VALUE=DATE = midnight
                fire_ref = due_dt + timedelta(minutes=allday_min)                  # Kalmido: the all-day reminder time
            if isinstance(tv, timedelta):
                ref = due_dt
                if str(trig.params.get("RELATED", "START")).upper() == "START" and start is not None:
                    sd, stm = imp_local(start)
                    if sd:
                        ref = datetime.fromisoformat(f"{sd}T{stm or '00:00'}").replace(tzinfo=TZ)
                at = ref + tv
            elif isinstance(tv, datetime):
                at = tv if tv.tzinfo else tv.replace(tzinfo=TZ)
            else:
                at = None
            if at is not None:
                o = int((fire_ref - at).total_seconds() // 60)
                if REM_MIN <= o <= REM_MAX and len(rems) < REM_COUNT:
                    off = o
        if off is None:
            keep += block
        elif off not in rems:
            rems.append(off)
    v["reminders"] = rems
    for b in rw["blocks"]:
        keep += b
    extra = "\n".join(x for x in keep if x)
    if len(extra) > DAV_EXTRA_MAX:
        extra = extra[:DAV_EXTRA_MAX].rsplit("\n", 1)[0]
        print("caldav: extra properties of", repr(uid_[:60]), "cut to", DAV_EXTRA_MAX, "characters", flush=True)
    v["extra"] = extra
    v["has"] = {_prop_name(x) for x in rw["lines"]}
    # changed occurrences of a recurring task (RECURRENCE-ID): only "this occurrence is done" is understood
    v["done_occurrence"] = False
    for i, x in enumerate(todos):
        if i != masters[0] and str(x.get("STATUS") or "").upper() == "COMPLETED":
            rid, _ = imp_local(_ics_val(x.get("RECURRENCE-ID")))
            if rid and rid == v["due"]:
                v["done_occurrence"] = True
    return v


# ---- writing
def dav_caps_learn(c, pw_row, v):
    have = set(filter(None, (pw_row["caps"] or "").split(",")))
    new = have | ({"CATEGORIES", "RELATED-TO"} & v["has"])
    if new != have:
        c.execute("UPDATE app_passwords SET caps=? WHERE id=?", (",".join(sorted(new)), pw_row["id"]))
        c.commit()
    return new


def dav_parent_id(c, u, lid, tid, puid):
    """The task id of the parent UID in list lid (None: none / not there yet)."""
    if not puid:
        return None
    for pid in dav_find_uid(c, puid, lid):
        if pid == tid:
            continue
        r = c.execute("SELECT list_id, deleted_at FROM tasks WHERE id=?", (pid,)).fetchone()
        if r and r["list_id"] == lid and not r["deleted_at"] and task_visible(c, pid, u["id"]):
            if tid and check_parent(c, tid, pid):
                return None
            if not tid and check_parent(c, None, pid):
                return None
            return pid
    return None


def dav_meta_set(c, tid, **kv):
    if not c.execute("SELECT 1 FROM dav_meta WHERE task_id=?", (tid,)).fetchone():
        c.execute("INSERT INTO dav_meta(task_id) VALUES(?)", (tid,))
    c.execute(f"UPDATE dav_meta SET {','.join(k + '=?' for k in kv)} WHERE task_id=?", [*kv.values(), tid])


def dav_adopt_children(c, u, lid, tid, uid_):
    """Tasks that arrived before their parent (RELATED-TO to a UID not here yet) get this task as their parent."""
    from ..api.v1 import v1_call, V1Error
    for r in c.execute("""SELECT m.task_id FROM dav_meta m JOIN tasks t ON t.id=m.task_id WHERE m.parent_uid=? AND t.list_id=?
                          AND t.deleted_at IS NULL AND t.parent_id IS NULL""", (uid_, lid)).fetchall():
        if not check_parent(c, r[0], tid) and task_visible(c, r[0], u["id"], write=True):
            try:
                v1_call(task_update, r[0], body={"parent_id": tid})
                c.execute("UPDATE dav_meta SET parent_uid=NULL WHERE task_id=?", (r[0],))
            except (V1Error, Denied, BadInput):
                pass


def _rem_set(csv_):
    return sorted(int(x) for x in str(csv_ or "").split(",") if re.fullmatch(r"-?\d{1,7}", x.strip()))


def dav_patch(c, u, cur, v, caps, lid):
    """The task_update body that turns the stored task into what the client sent (only what changed)."""
    tid, p = cur["id"], {}
    for k in ("title", "content", "priority", "due", "due_time", "url"):
        if (cur[k] or None) != (v[k] or None):
            p[k] = v[k]
    if cur["status"] == 0 or v["status"] == 0:  # completing moves a recurring task on: dates of a done task are kept
        start = v["start"]
        if start and start == v["due"] and not cur["start"]:
            start = None
        if (cur["start"] or None) != (start or None):
            p["start"] = start
        if (cur["repeat"] or "") != v["repeat"]:
            p["repeat"] = v["repeat"]
    if _rem_set(cur["reminders"]) != sorted(v["reminders"]) and v["due"]:
        p["reminders"] = ",".join(str(x) for x in v["reminders"])
    if "tags" in v or "CATEGORIES" in caps:
        want = v.get("tags") or []
        if sorted(my_tags(c, tid)) != sorted(want):
            p["tags"] = want
    if v["parent_uid"] or "RELATED-TO" in caps:
        pid = dav_parent_id(c, u, lid, tid, v["parent_uid"])
        if pid != cur["parent_id"] and (pid or not v["parent_uid"]):
            p["parent_id"] = pid
    return p


def dav_status(tid, cur_status, want, done_occurrence=False):
    from ..api.v1 import v1_call
    if done_occurrence and cur_status == 0:
        want = 2
    if want == cur_status:
        return
    if want == 0:
        v1_call(task_reopen, tid, body={})
    else:
        if cur_status != 0:
            v1_call(task_reopen, tid, body={})
        v1_call(task_complete, tid, body={"status": want})


def dav_put(c, u, pw_row, lst, name):
    from ..api.v1 import v1_call
    if "text/calendar" not in (request.content_type or "text/calendar").lower():
        raise DavError(415, "Expected text/calendar", "<C:supported-calendar-data/>")
    raw = dav_body()
    if len(raw) > DAV_MAX_BODY:
        raise DavError(413, "Too large", "<C:max-resource-size/>")
    s = usettings(c, u["id"])
    v = dav_read(raw, hm_minutes(s.get("allday_time") or "09:00"))
    caps = dav_caps_learn(c, pw_row, v)
    have = dav_member(c, u, lst, name)
    inm, im = request.headers.get("If-None-Match", "").strip(), request.headers.get("If-Match", "").strip()
    if have and inm == "*":
        raise DavError(412, "The resource exists already")
    if im and (not have or (im != "*" and have[1] not in [x.strip() for x in im.split(",")])):
        raise DavError(412, "The resource was changed meanwhile")
    lid = lst["id"]
    if have:
        cur = have[0]
        if cur["id"] in pvis(c, u["id"], lid)[2] or lst["role"] == "view":
            raise DavError(403, "Read only", "<D:need-privileges/>")
        p = dav_patch(c, u, cur, v, caps, lid)
        if p:
            v1_call(task_update, cur["id"], body=p)
        dav_status(cur["id"], c.execute("SELECT status FROM tasks WHERE id=?", (cur["id"],)).fetchone()[0], v["status"],
                   v["done_occurrence"])
        old_uid = dav_uid_of(cur["id"], c.execute("SELECT * FROM dav_meta WHERE task_id=?", (cur["id"],)).fetchone())
        pend = v["parent_uid"] if v["parent_uid"] and not c.execute("SELECT parent_id FROM tasks WHERE id=?", (cur["id"],)).fetchone()[0] else None
        dav_meta_set(c, cur["id"], extra=v["extra"], parent_uid=pend, **({"uid": v["uid"]} if v["uid"] != old_uid else {}))
        c.commit()
        return Response(status=204)
    if lst["role"] == "view":
        raise DavError(403, "Read only", "<D:need-privileges/>")
    # a UID that already lives here under another name / in another list (a client moving a task between lists)
    since = iso(now_utc() - timedelta(seconds=DAV_MOVE_S))
    for oid in dav_find_uid(c, v["uid"], lid, since):
        o = c.execute("SELECT * FROM tasks WHERE id=?", (oid,)).fetchone()
        if not task_visible(c, oid, u["id"], write=True):
            continue
        if o["list_id"] == lid and not o["deleted_at"]:
            meta = c.execute("SELECT * FROM dav_meta WHERE task_id=?", (oid,)).fetchone()
            href = dav_href("calendars", u["username"], lid, dav_name_of(oid, meta))
            raise DavError(403, "This UID exists already", f"<C:no-uid-conflict><D:href>{_xe(href)}</D:href></C:no-uid-conflict>")
        if o["deleted_at"]:
            v1_call(task_restore, oid, body={})
        p = dav_patch(c, u, c.execute("SELECT * FROM tasks WHERE id=?", (oid,)).fetchone(), v, caps, lid)
        p["list_id"] = lid
        if "parent_id" not in p and o["parent_id"]:
            p["parent_id"] = None
        v1_call(task_update, oid, body=p)
        dav_status(oid, c.execute("SELECT status FROM tasks WHERE id=?", (oid,)).fetchone()[0], v["status"])
        dav_meta_set(c, oid, uid=v["uid"], href=name, extra=v["extra"], parent_uid=None)
        c.commit()
        return Response(status=201)
    if _own_id(DAV_HREF_RE, name):  # names of this form belong to the tasks they name
        raise DavError(403, "This resource name is reserved", "<C:no-uid-conflict/>")
    b = {k: v[k] for k in ("title", "content", "priority", "due", "due_time", "start", "repeat", "url") if v[k] not in (None, "", 0)}
    b["list_id"] = lid
    if v["reminders"] and v["due"]:
        b["reminders"] = ",".join(str(x) for x in v["reminders"])
    if v.get("tags"):
        b["tags"] = v["tags"]
    pid = dav_parent_id(c, u, lid, None, v["parent_uid"])
    if pid:
        b["parent_id"] = pid
    if v["start"] and v["start"] == v["due"]:
        b.pop("start", None)
    j = v1_call(task_create, body=b)
    tid = j["id"]
    if v["status"] != 0:  # arrives completed (an old done task): no completion events, no next occurrence
        c.execute("UPDATE tasks SET status=?, completed_at=?, completed_by=? WHERE id=?", (v["status"], v["completed_at"], u["id"], tid))
        bump(c)
    dav_meta_set(c, tid, uid=v["uid"], href=name, extra=v["extra"],
                 parent_uid=v["parent_uid"] if v["parent_uid"] and not pid else None)
    c.commit()
    dav_adopt_children(c, u, lid, tid, v["uid"])
    c.commit()
    r = Response(status=201)
    r.headers["Location"] = dav_href("calendars", u["username"], lid, name)
    return r


# ---- REPORT
def dav_report_props(root):
    for ch in root:
        if ch.tag == D_ + "prop":
            return [x.tag for x in ch if isinstance(x.tag, str)]
    return [D_ + "getetag"]


def _tr_bound(s):
    s = (s or "").strip()
    try:
        if re.fullmatch(r"\d{8}T\d{6}Z", s):
            return datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone(TZ).date().isoformat()
        if re.fullmatch(r"\d{8}", s):
            return datetime.strptime(s, "%Y%m%d").date().isoformat()
    except ValueError:
        pass
    return None


def dav_query_filter(root):
    """calendar-query: a predicate over members (VTODO only; time-range on the dates, COMPLETED / STATUS)."""
    filt = root.find(C_ + "filter")
    if filt is None:
        return lambda m: True
    cal = filt.find(C_ + "comp-filter")
    if cal is None or cal.get("name", "").upper() != "VCALENDAR":
        return lambda m: True
    comps = cal.findall(C_ + "comp-filter")
    if not comps:
        return lambda m: True
    todo = next((x for x in comps if x.get("name", "").upper() == "VTODO"), None)
    if todo is None:
        return lambda m: False  # VEVENT / VJOURNAL: never here
    if todo.find(C_ + "is-not-defined") is not None:
        return lambda m: False
    tests = []
    tr_ = todo.find(C_ + "time-range")
    if tr_ is not None:
        a, b = _tr_bound(tr_.get("start")), _tr_bound(tr_.get("end"))
        tests.append(lambda t: not t["due"] or bool(t["repeat"]) or ((not a or (t["due"] >= a)) and (not b or (t["start"] or t["due"]) <= b)))
    for pf in todo.findall(C_ + "prop-filter"):
        pn = pf.get("name", "").upper()
        if pn == "COMPLETED" and pf.find(C_ + "is-not-defined") is not None:
            tests.append(lambda t: t["status"] != 2)
        elif pn == "STATUS":
            tm = pf.find(C_ + "text-match")
            if tm is not None and (tm.text or "").strip():
                val, neg = (tm.text or "").strip().upper(), tm.get("negate-condition", "no") == "yes"
                st = {0: "NEEDS-ACTION", 2: "COMPLETED", -1: "CANCELLED"}
                tests.append(lambda t, val=val, neg=neg: (val in st.get(t["status"], "")) != neg)
    return lambda m: all(f(m[4]) for f in tests)


def dav_report(c, u, kind, lid, lst, raw):
    root = dav_xml(raw)
    want = dav_report_props(root)
    if kind != "cal":
        if root.tag == D_ + "sync-collection":
            raise DavError(403, "Only on a calendar", "<D:valid-sync-token/>")
        return dav_multistatus([])
    coll = dav_coll(c, u, lst)
    base = ("calendars", u["username"], lid)
    if root.tag == C_ + "calendar-multiget":
        pre = urllib.parse.unquote(dav_href(*base, coll=True))
        items = []
        for h in root.findall(D_ + "href"):
            raw_h = (h.text or "").strip()
            if raw_h:
                path = urllib.parse.unquote(urllib.parse.urlsplit(raw_h).path)
                items.append((raw_h, path, path.rsplit("/", 1)[-1]))

        def gen():
            for raw_h, path, name in items:
                m = coll.members.get(name) if path.startswith(pre) else None
                if m is None:
                    yield f"<D:response><D:href>{_xe(raw_h)}</D:href><D:status>HTTP/1.1 404 Not Found</D:status></D:response>"
                else:
                    yield dav_response(dav_href(*base, name), want, dav_props_member(u, m, lst["role"]))
        return dav_multistatus(gen())
    if root.tag == C_ + "calendar-query":
        ok = dav_query_filter(root)
        return dav_multistatus(dav_response(dav_href(*base, n), want, dav_props_member(u, m, lst["role"]))
                               for n, m in coll.members.items() if ok(m))
    if root.tag == D_ + "sync-collection":
        tok_el = root.find(D_ + "sync-token")
        tok = (tok_el.text or "").strip() if tok_el is not None else ""
        lvl = root.find(D_ + "sync-level")
        if lvl is not None and (lvl.text or "").strip() not in ("1", ""):
            raise DavError(403, "Only sync-level 1", "<D:number-of-matches-within-limits/>")
        old = None
        if tok:
            old = dav_sync_load(c, u, lid, tok)
            if old is None:
                raise DavError(403, "Unknown sync-token", "<D:valid-sync-token/>")
        dav_sync_save(c, u, coll)
        new = coll.state()
        changed = [n for n in coll.members if old is None or old.get(n) != new[n]]
        gone = [n for n in (old or {}) if n not in new]

        def gen():
            for n in changed:
                yield dav_response(dav_href(*base, n), want, dav_props_member(u, coll.members[n], lst["role"]))
            for n in gone:
                yield f"<D:response><D:href>{_xe(dav_href(*base, n))}</D:href><D:status>HTTP/1.1 404 Not Found</D:status></D:response>"
        return dav_multistatus(gen(), f"<D:sync-token>{_xe(coll.token)}</D:sync-token>")
    raise DavError(403, "Unsupported report", "<D:supported-report/>")


# ---- the handler
def dav_err_resp(e):
    if e.cond:
        r = Response(f'<?xml version="1.0" encoding="utf-8"?>\n<D:error xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav" '
                     f'xmlns:CR="urn:ietf:params:xml:ns:carddav">{e.cond}</D:error>\n', e.code, content_type="application/xml; charset=utf-8")
    else:
        r = Response((e.text or "Error") + "\n", e.code, content_type="text/plain; charset=utf-8")
    if e.code == 429:
        r.headers["Retry-After"] = str(FAIL_WINDOW if "login" in e.text else 60)
    return r


def dav_options():
    r = Response(status=200)
    r.headers["DAV"] = "1, 3, calendar-access, addressbook"
    r.headers["Allow"] = DAV_ALLOW
    r.headers["Content-Length"] = "0"
    return r


@app.route("/", methods=["PROPFIND", "REPORT"], endpoint="dav_root_probe")  # clients given only the server's address
@app.route("/.well-known/caldav", methods=DAV_METHODS, provide_automatic_options=False)
@app.route("/.well-known/caldav/", methods=DAV_METHODS, provide_automatic_options=False)
@app.route("/.well-known/carddav", methods=DAV_METHODS, provide_automatic_options=False, endpoint="dav_wellknown_card")
@app.route("/.well-known/carddav/", methods=DAV_METHODS, provide_automatic_options=False, endpoint="dav_wellknown_card2")
def dav_wellknown():
    if not DAV_ON:
        return Response("Not found\n", 404, content_type="text/plain; charset=utf-8")
    return redirect(request.script_root + DAV_ROOT, 301)


@app.route("/dav", methods=DAV_METHODS, provide_automatic_options=False, defaults={"p": ""})
@app.route("/dav/", methods=DAV_METHODS, provide_automatic_options=False, defaults={"p": ""})
@app.route("/dav/<path:p>", methods=DAV_METHODS, provide_automatic_options=False)
def dav(p):
    from ..api.v1 import v1_call, V1Error
    if not DAV_ON:
        return Response("Not found\n", 404, content_type="text/plain; charset=utf-8")
    m = request.method
    if m == "OPTIONS":
        return dav_options()
    try:
        who = dav_login()
        if not who:
            return dav_401()
        u, pw_row = who
        g.user, g.auth_via = u, "dav"
        c = db()
        dav_inst(c)
        if m in ("MKCALENDAR", "MKCOL"):
            raise DavError(403, "Create lists and calendars in the app", "<D:resource-must-be-null/>")
        if p.split("/", 1)[0] == "addressbooks":  # 2.21.0 (#658): CardDAV
            from ..contacts.carddav import abdav
            return abdav(m, c, u, p)
        kind, lid, name = dav_path(p, u)
        if kind in ("evcoll", "evmember"):
            from ..events.dav import evdav
            return evdav(m, c, u, pw_row, kind, lid, name)
        lst = None
        if lid is not None:
            lst = dav_lists(c, u).get(lid)
            if not lst:
                raise DavError(404, "Not found")
        if m == "PROPFIND":
            return davs_propfind(c, u, kind, lst, name)
        if m == "REPORT":
            return dav_report(c, u, kind, lid, lst, dav_body())
        if m in ("GET", "HEAD"):
            if kind != "member":
                return Response(f"{APP_NAME} CalDAV\n", 200, content_type="text/plain; charset=utf-8")
            have = dav_member(c, u, lst, name)
            if not have:
                raise DavError(404, "Not found")
            text = dav_wrap(have[2], have[3])
            r = Response("" if m == "HEAD" else text, 200, content_type="text/calendar; charset=utf-8")
            r.headers["ETag"] = have[1]
            r.headers["Last-Modified"] = email.utils.format_datetime(parse_iso(have[0]["updated_at"]).astimezone(timezone.utc), usegmt=True)
            if m == "HEAD":
                r.headers["Content-Length"] = str(len(text.encode("utf-8")))
            return r
        if m == "PUT":
            if kind != "member":
                raise DavError(405, "PUT works on a task resource inside a list")
            return dav_put(c, u, pw_row, lst, name)
        if m == "DELETE":
            if kind != "member":
                raise DavError(403, "Lists are deleted in the app")
            have = dav_member(c, u, lst, name)
            if not have:
                raise DavError(404, "Not found")
            im = request.headers.get("If-Match", "").strip()
            if im and im != "*" and have[1] not in [x.strip() for x in im.split(",")]:
                raise DavError(412, "The resource was changed meanwhile")
            v1_call(task_delete, have[0]["id"])
            return Response(status=204)
        if m == "PROPPATCH":
            root = dav_xml(dav_body())
            names = [x.tag for s_ in root for pr in s_ if pr.tag == D_ + "prop" for x in pr if isinstance(x.tag, str)]
            href = request.script_root + "/dav/" + p
            return dav_multistatus([f"<D:response><D:href>{_xe(href)}</D:href><D:propstat><D:prop>{''.join(_el(n) for n in names)}"
                                    "</D:prop><D:status>HTTP/1.1 403 Forbidden</D:status></D:propstat></D:response>"])
        raise DavError(405, "Method not allowed")
    except DavError as e:
        return dav_err_resp(e)
    except Denied as e:
        return dav_err_resp(DavError(e.code if e.code in (403, 404, 409) else 403, e.text() if e.code != 404 else "Not found"))
    except BadInput as e:
        return dav_err_resp(DavError(400, str(e)))
    except V1Error as e:
        code = e.resp.status_code
        msg = ((e.resp.get_json(silent=True) or {}).get("error") or {}).get("message") or "Error"
        return dav_err_resp(DavError(code if code in (400, 403, 404, 409, 413) else 400, msg))


def davs_propfind(c, u, kind, lst, name):
    want = dav_propfind_req(dav_body())
    depth = request.headers.get("Depth", "1").strip().lower()
    deep = depth in ("1", "infinity")
    out = []
    if kind == "root":
        out.append(dav_response(DAV_ROOT, want, dav_props_root(u)))
        if deep:
            out.append(dav_response(dav_principal_href(u), want, dav_props_principal(u)))
            out.append(dav_response(dav_home_href(u), want, dav_props_home(u)))
        return dav_multistatus(out)
    if kind in ("principals", "calendars"):
        out.append(dav_response(DAV_ROOT + kind + "/", want, {**dav_props_home(u), D_ + "displayname": kind}))
        if deep:
            out.append(dav_response(dav_principal_href(u), want, dav_props_principal(u)) if kind == "principals"
                       else dav_response(dav_home_href(u), want, dav_props_home(u)))
        return dav_multistatus(out)
    if kind == "principal":
        return dav_multistatus([dav_response(dav_principal_href(u), want, dav_props_principal(u))])
    if kind == "home":
        # the responses are built here: the database and the person's language are gone once the body streams
        out.append(dav_response(dav_home_href(u), want, dav_props_home(u)))
        if deep:
            from ..events.dav import home_responses
            for i, L in enumerate(dav_lists(c, u).values()):
                out.append(dav_response(dav_href("calendars", u["username"], L["id"], coll=True), want,
                                        dav_props_cal(c, u, L, i, functools.partial(dav_coll, c, u, L))))
            out += home_responses(c, u, want, 1000)
        return dav_multistatus(out)
    order = list(dav_lists(c, u)).index(lst["id"])
    if kind == "cal":
        coll = dav_coll(c, u, lst)
        first = dav_response(dav_href("calendars", u["username"], lst["id"], coll=True), want,
                             dav_props_cal(c, u, lst, order, lambda: coll))
        role = lst["role"]

        def gen():
            yield first
            if deep:
                for n, m in coll.members.items():
                    yield dav_response(dav_href("calendars", u["username"], lst["id"], n), want, dav_props_member(u, m, role))
        return dav_multistatus(gen())
    have = dav_member(c, u, lst, name)
    if not have:
        raise DavError(404, "Not found")
    t, etag, lines, tz = have
    return dav_multistatus([dav_response(dav_href("calendars", u["username"], lst["id"], name), want,
                                         dav_props_member(u, (t["id"], etag, lines, tz, t), lst["role"]))])
