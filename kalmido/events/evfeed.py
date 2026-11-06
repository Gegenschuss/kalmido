"""2.111.0 B (#2056): a subscription link (ICS feed) per event calendar and person, for the calendar app of a phone or of
another service that only reads: GET /ical/ev/<id>.<secret>.ics. The secret link is the only credential (it lies under
/ical/, which bypasses the login proxy like the task feed of calendars/icalfeed.py); there is no feed without one. Each person
who sees a calendar makes their own link (ev_cal_feeds: create keeps it, rotate replaces it at once, off removes it), so
removing a person from a shared calendar ends their link too: at EVERY fetch the feed checks that the person who made the link
may still see the calendar (organisation membership included, events/model.py ev_role), else 404 -- the same 404 as an
unknown or wrong link, counted per client address like the task feed. It holds the calendar's events as the CalDAV export
does (series with rule, left-out and changed dates; events are stored in plain text in every space, there is nothing sealed
to open), without attendees (their addresses stay inside Kalmido) and without alarms of the person (2.190.0 D, #2496: also
none kept from an imported event). The token never goes into
a log line; answers are Cache-Control private, no-store."""
from flask import jsonify, Response

from ..core.config import app, APP_NAME, PUBLIC_URL
from ..core.i18n import tr
from ..core.db import body, db, usettings
from ..accounts.session import _rate_blocked, _rate_fail, client_ip, me
from ..core.access import need_feat, acx_token_bind
from ..core.errors import BadInput
from ..core.tokenhash import tkh_evfeed_match, tkh_set_evfeed
from ..events.model import ev_role, need_evcal
from ..calendars.icalfeed import ics_text  # 2.369.5 (#2517): pulled up from functions
from ..events.ics import ev_dl_drop, ev_lines, wrap  # 2.369.5 (#2517): pulled up from functions
from ..notify.alerts import aa_count  # 2.369.5 (#2517): pulled up from functions

EVF_FAIL_LIMIT = 30  # wrong links per client address within the login fail window, then 429 (as calendars/icalfeed.py)
EVF_MAX = 20000


def evf_url(fid, secret):
    """2.577.0 (#4708 6): the address with its secret (only in the answer that made it; the server keeps the hash)."""
    return f"{PUBLIC_URL}/ical/ev/{fid}.{secret}.ics"


def evf_state(row):
    """2.577.0 (#4708 6): whether the person has a link and since when (the address itself is shown once, as GET /api/ical)."""
    return {"active": bool(row), "created_at": (row["created_at"] or "") if row else ""}


def evf_row(c, cid, uid):
    return c.execute("SELECT * FROM ev_cal_feeds WHERE cal_id=? AND user_id=?", (cid, uid)).fetchone()


EVF_DROP = {"ORGANIZER", "ATTENDEE"}


def evf_extra(extra):
    """2.190.0 D (#2496): the kept lines of an imported event without organiser, attendees and alarms (the feed has none)."""
    out, skip, alarm = [], False, 0
    for line in (extra or "").split("\n") if extra else []:
        if line[:1] in (" ", "\t"):  # a folded continuation belongs to the line before
            if not skip:
                out.append(line)
            continue
        n = line.split(":", 1)[0].split(";", 1)[0].strip().upper()
        if n == "BEGIN" and line.split(":", 1)[-1].strip().upper() == "VALARM":
            alarm += 1
        skip = bool(alarm) or n in EVF_DROP
        if n == "END" and alarm and line.split(":", 1)[-1].strip().upper() == "VALARM":
            alarm -= 1
        if not skip:
            out.append(line)
    return "\n".join(out)


def evf_build(c, cal, uid=None):
    lines, tzs = [], set()
    rows = c.execute("SELECT * FROM events WHERE cal_id=? AND deleted_at IS NULL ORDER BY id LIMIT ?", (cal["id"], EVF_MAX)).fetchall()
    for r in ev_dl_drop(c, uid, rows):  # 2.560.0 (#4699): an agent's link leaves the events of its locked tasks out
        try:
            L, t = ev_lines(c, {**dict(r), "reminders": "", "extra": evf_extra(r["extra"]), "guests_visible": 0}, [])  # 2.380 H (#3392): not in a feed
        except (ValueError, TypeError) as e:  # one broken row never breaks the whole feed
            print("evfeed: skipping event", r["id"], type(e).__name__, flush=True)
            continue
        lines += L
        tzs |= t
    s = wrap(lines, tzs)
    head = (f"METHOD:PUBLISH\r\nX-WR-CALNAME:{ics_text(APP_NAME + ' · ' + cal['name'])}\r\n"
            "REFRESH-INTERVAL;VALUE=DURATION:PT15M\r\nX-PUBLISHED-TTL:PT15M\r\n")
    return s.replace("CALSCALE:GREGORIAN\r\n", "CALSCALE:GREGORIAN\r\n" + head, 1)


def _nf():
    return Response("Not found\n", 404, content_type="text/plain; charset=utf-8", headers={"Cache-Control": "private, no-store"})


@app.get("/ical/ev/<token>.ics")
def evf_feed(token):
    keys = [("ical:" + client_ip(), EVF_FAIL_LIMIT)]
    if _rate_blocked(keys):
        return Response("Too many requests\n", 429, content_type="text/plain; charset=utf-8")
    c = db()
    fid, _, secret = token.partition(".")
    f = None
    if fid.isdigit() and len(fid) < 19 and secret:
        r = c.execute("SELECT f.*, u.disabled FROM ev_cal_feeds f JOIN users u ON u.id=f.user_id WHERE f.id=?", (int(fid),)).fetchone()
        if r and not r["disabled"] and tkh_evfeed_match(c, r, secret):  # 2.577.0 (#4708 6): compared with the stored hash (a plain one left is hashed)
            f = r
    if not f:
        _rate_fail(keys)
        aa_count("security", "ics", client_ip())
        return _nf()
    acx_token_bind(f["user_id"])  # reads with the link owner's context (row-level security), like the task feed
    cal = c.execute("SELECT * FROM ev_cals WHERE id=?", (f["cal_id"],)).fetchone()
    if not ev_role(c, f["user_id"], cal):  # the person may no longer see the calendar (left the organisation, sharing ended)
        return _nf()
    if "events" not in (usettings(c, f["user_id"]).get("features") or "").split(","):  # 2.111.0 review: module off = links off
        return _nf()
    return Response(evf_build(c, cal, f["user_id"]), content_type="text/calendar; charset=utf-8",
                    headers={"Cache-Control": "private, no-store", "Content-Disposition": 'inline; filename="calendar.ics"',
                             "X-Robots-Tag": "noindex"})


@app.get("/api/evcals/<int:cid>/feed")
def evf_info(cid):
    c = db()
    need_evcal(c, cid)
    return jsonify(url=None, **evf_state(evf_row(c, cid, me())))  # 2.577.0 (#4708 6): the address is in the answer of create / rotate only


@app.post("/api/evcals/<int:cid>/feed")
def evf_set(cid):
    """{action: create | rotate | off}: create keeps an existing link, rotate replaces it (the old one stops at once), off
    removes it. Anyone who sees the calendar makes their own link (it shows what they see)."""
    need_feat("events")
    c = db()
    uid = me()
    need_evcal(c, cid)
    b = body()
    a = b.get("action") if isinstance(b, dict) else None  # 2.111.0 review: no 500 on a non-object body
    row, tok = evf_row(c, cid, uid), None
    if a == "off":
        c.execute("DELETE FROM ev_cal_feeds WHERE cal_id=? AND user_id=?", (cid, uid))
    elif a == "rotate" and row:
        tok = tkh_set_evfeed(c, fid=row["id"])
    elif a in ("create", "rotate") and not row:
        tok = tkh_set_evfeed(c, cal_id=cid, uid=uid)
    elif a != "create":
        raise BadInput(tr("Invalid value: {0}", "action"))
    c.commit()
    row = evf_row(c, cid, uid)
    # 2.577.0 (#4708 6): only the hash is stored: the new address is in this answer once; create with a link answers url null
    return jsonify(url=evf_url(row["id"], tok) if tok and row else None, **evf_state(row))

