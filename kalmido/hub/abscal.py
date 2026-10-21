"""2.155.0 B (#2076): public holidays and absences in the calendar views + the absences as a subscription link.

- The calendar's range answer (GET /api/calendars/events, calendars/subscriptions.py) gets read-only all-day entries:
  the public holidays of my state (holiday: true), my own absences (absence: "own", the kind like in the absences tab,
  an open vacation request marked as such) and -- switched on by the person -- the absences of the colleagues of the
  organisations I am a full member of (absence: "team", only "away" and the period, never the kind or the note; approved
  ones only, like the team view of hub/absence.py abs_list). Three user settings switch them: cal_holidays (default on),
  cal_abs (own absences, default on), cal_abs_team (colleagues, default off).
- The state of the holidays: the person's own setting holiday_state (Settings: anyone, above all a person without an
  organisation; '' = the area's state, hub/absence.py abs_state), computed offline (abs_holidays).
- A subscription link of my own absences + the holidays of my state (GET /ical/abs/<id>.<secret>.ics) for the calendar
  app of a phone: made, replaced and removed like the link of an event calendar (events/evfeed.py: the secret in the path
  is the only credential, a wrong one counts per client address, 404 like an unknown one). Never data of other people;
  the kind of a sick leave never leaves the app ("Away" instead, health data)."""
import hmac
import secrets
from datetime import date, timedelta

from flask import jsonify, Response

from ..core.config import app, APP_NAME, PUBLIC_URL
from ..core.i18n import tr
from ..core.db import body, db, iso, local_now, now_utc, usettings
from ..core.access import Denied
from ..core.orgcrypt import oc_dec_fields
from ..accounts.session import _rate_blocked, _rate_fail, client_ip
from ..personal.timetrack import BadInput
from .absence import ABS_STATES, _gate, abs_holidays, abs_org, abs_people, abs_state

ABC_KIND = {"vacation": "Vacation", "sick": "Sick leave", "off": "Day off", "other": "Other absence"}
ABC_MAX = 2000  # absences in one answer / feed
ABC_FAIL_LIMIT = 30  # wrong links per client address within the login fail window, then 429 (as events/evfeed.py)


def abc_on(s, k):
    """A calendar switch of settings s: cal_holidays / cal_abs on unless '0', cal_abs_team only when '1'."""
    v = s.get(k)
    return v == "1" if k == "cal_abs_team" else v != "0"


def abc_state(c, uid, s=None):
    """The state of uid's public holidays: their own setting, else the one of their area (workspace switch / first
    organisation / personal area); '' = none."""
    s = s if s is not None else usettings(c, uid)
    own = s.get("holiday_state") or ""
    if own in ABS_STATES:
        return own
    try:
        return abs_state(c, abs_org(c, uid, create=False))
    except (Denied, BadInput):
        return ""


def abc_kind_title(c, r, feed=False):
    """The title of one of my own absences: its kind (the feed says "Away" for a sick leave), a half day and an open
    request said so."""
    kind = ""
    try:
        kind = oc_dec_fields(c, r["org_id"], "hub_absences", r).get("kind") or ""
    except Exception as e:  # noqa: BLE001 -- a sealed area without its key: "Away" instead of an error
        print("abscal: kind not readable", type(e).__name__, flush=True)
    t = tr("Away") if feed and kind == "sick" else tr(ABC_KIND.get(kind, "Away"))
    t += abc_half(r)
    if (r["status"] or "approved") == "pending":
        t += " · " + tr("requested")
    return t


def abc_half(r):
    return (" · " + (tr("morning") if r["half_day"] == "am" else tr("afternoon"))) if r["half_day"] else ""


def abc_holidays(state, lo, hi):
    return [{"date": k, "name": v} for k, v in sorted(abs_holidays(state, lo, hi).items())] if state else []


def abc_own_rows(c, uid, lo, hi):
    """My own absences overlapping [lo, hi] in every area I see (row-level security), open requests too, no rejected."""
    return c.execute("SELECT * FROM hub_absences WHERE user_id=? AND deleted_at IS NULL AND start_date<=? AND end_date>=? "
                     "AND status IN ('approved','pending') ORDER BY start_date, id LIMIT ?",
                     (uid, hi.isoformat(), lo.isoformat(), ABC_MAX)).fetchall()


def abc_team_orgs(c, uid, s):
    """The organisations whose colleagues' absences I may see in the calendar: my full memberships (no guests /
    accounting), only the switched one when the workspace switch shows one organisation, none on "Private"."""
    import re
    from ..accounts.orgs import user_orgs
    from ..accounts.orgroles import user_orgs_full
    full = [o for o in user_orgs(c, uid) if o in user_orgs_full(c, uid)]
    ws = (s.get("workspace") or "").strip()
    m = re.fullmatch(r"org:(\d{1,9})", ws)
    if m:
        return [o for o in full if o == int(m.group(1))]
    return [] if ws == "private" else full


def abc_cal(c, uid, lo, hi):
    """Read-only all-day entries of [lo, hi] (dates) for the calendar views: holidays, my absences, the colleagues'."""
    u = c.execute("SELECT kind, kid FROM users WHERE id=?", (uid,)).fetchone()
    if not u or u["kid"] or (u["kind"] or "user") == "agent":
        return []
    s = usettings(c, uid)
    out = []
    if abc_on(s, "cal_holidays"):
        for h in abc_holidays(abc_state(c, uid, s), lo, hi):
            out.append({"id": "h" + h["date"], "holiday": True, "all_day": True, "start": h["date"],
                        "end": (date.fromisoformat(h["date"]) + timedelta(days=1)).isoformat(), "title": h["name"],
                        "location": "", "description": ""})

    def entry(r, kind, title):
        return {"id": f"a{r['id']}", "absence": kind, "all_day": True, "start": r["start_date"], "half_day": r["half_day"] or "",
                "end": (date.fromisoformat(r["end_date"]) + timedelta(days=1)).isoformat(), "title": title, "location": "", "description": ""}
    if abc_on(s, "cal_abs"):
        out += [entry(r, "own", abc_kind_title(c, r)) for r in abc_own_rows(c, uid, lo, hi)]
    if abc_on(s, "cal_abs_team"):
        seen = set()
        for oid in abc_team_orgs(c, uid, s):
            names = {p["id"]: p["display_name"] or p["username"] for p in abs_people(c, oid)}  # former members stay out
            for r in c.execute("SELECT id, user_id, start_date, end_date, half_day FROM hub_absences WHERE org_id=? AND user_id<>? "
                               "AND deleted_at IS NULL AND status='approved' AND start_date<=? AND end_date>=? ORDER BY start_date, id LIMIT ?",
                               (oid, uid, hi.isoformat(), lo.isoformat(), ABC_MAX)).fetchall():
                if r["user_id"] in names and r["id"] not in seen:
                    seen.add(r["id"])
                    t = tr("{0}: away", names[r["user_id"]]) + abc_half(r)
                    out.append({**entry(r, "team", t), "user_id": r["user_id"]})
    return out


# ---------------------------------------------------------------- the subscription link (ICS feed)
def abc_url(row):
    return f"{PUBLIC_URL}/ical/abs/{row['id']}.{row['secret']}.ics" if row else None


def abc_feed_row(c, uid):
    return c.execute("SELECT * FROM abs_cal_feeds WHERE user_id=?", (uid,)).fetchone()


def abc_ics(c, uid):
    """VCALENDAR of uid's own absences (a year back, every coming one) and the holidays of their state (this year and the
    next two). All-day events; the absences busy, the holidays free (TRANSP)."""
    from ..calendars.icalfeed import ics_fold, ics_text
    today = local_now().date()
    stamp = now_utc().strftime("%Y%m%dT%H%M%SZ")
    lo, hi = today - timedelta(days=366), date(today.year + 2, 12, 31)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//{ics_text(APP_NAME)}//Absences//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             f"X-WR-CALNAME:{ics_text(APP_NAME + ' · ' + tr('Absences'))}", "REFRESH-INTERVAL;VALUE=DURATION:PT1H", "X-PUBLISHED-TTL:PT1H"]

    def ev(uid_, d0, d1, title, transp):
        lines.extend(["BEGIN:VEVENT", f"UID:{uid_}", f"DTSTAMP:{stamp}", f"DTSTART;VALUE=DATE:{d0.strftime('%Y%m%d')}",
                      f"DTEND;VALUE=DATE:{d1.strftime('%Y%m%d')}", ics_fold("SUMMARY:" + ics_text(title)), f"TRANSP:{transp}", "END:VEVENT"])
    for r in abc_own_rows(c, uid, lo, hi):
        ev(f"absence-{r['id']}@kalmido", date.fromisoformat(r["start_date"]), date.fromisoformat(r["end_date"]) + timedelta(days=1),
           abc_kind_title(c, r, feed=True), "OPAQUE")
    st = abc_state(c, uid)
    for h in abc_holidays(st, date(today.year, 1, 1), hi):
        d = date.fromisoformat(h["date"])
        ev(f"holiday-{st}-{h['date']}@kalmido", d, d + timedelta(days=1), h["name"], "TRANSPARENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def _nf():
    return Response("Not found\n", 404, content_type="text/plain; charset=utf-8", headers={"Cache-Control": "private, no-store"})


@app.get("/ical/abs/<token>.ics")
def abc_feed(token):
    from ..notify.alerts import aa_count
    keys = [("ical:" + client_ip(), ABC_FAIL_LIMIT)]
    if _rate_blocked(keys):
        return Response("Too many requests\n", 429, content_type="text/plain; charset=utf-8")
    c = db()
    fid, _, secret = token.partition(".")
    f = None
    if fid.isdigit() and len(fid) < 19 and secret:
        r = c.execute("SELECT f.*, u.disabled, u.kid, u.kind FROM abs_cal_feeds f JOIN users u ON u.id=f.user_id WHERE f.id=?",
                      (int(fid),)).fetchone()
        if r and not r["disabled"] and not r["kid"] and (r["kind"] or "user") != "agent" \
                and hmac.compare_digest(r["secret"].encode(), secret.encode()):
            f = r
    if not f:
        _rate_fail(keys)
        aa_count("security", "ics", client_ip())
        return _nf()
    from ..core.access import acx_token_bind
    acx_token_bind(f["user_id"])  # reads with the link owner's context (row-level security), like the other feeds
    return Response(abc_ics(c, f["user_id"]), content_type="text/calendar; charset=utf-8",
                    headers={"Cache-Control": "private, no-store", "Content-Disposition": 'inline; filename="absences.ics"',
                             "X-Robots-Tag": "noindex"})


@app.get("/api/team/absences/feed")
def abc_feed_info():
    """The subscription link (null = none) + what the "Calendars" window shows next to it: the states to choose from, my
    own choice (holiday_state, '' = my area's), the state that applies now and my area's."""
    c, uid = _gate()
    s = usettings(c, uid)
    return jsonify(url=abc_url(abc_feed_row(c, uid)), states=ABS_STATES, own=s.get("holiday_state") or "", state=abc_state(c, uid, s),
                   area=abc_state(c, uid, {}))


@app.post("/api/team/absences/feed")
def abc_feed_set():
    """{action: create | rotate | off}: create keeps an existing link, rotate replaces it (the old one stops at once), off
    removes it. Only one's own absences and the holidays of one's state are in it."""
    c, uid = _gate()
    b = body()
    a = b.get("action") if isinstance(b, dict) else None
    row = abc_feed_row(c, uid)
    if a == "off":
        c.execute("DELETE FROM abs_cal_feeds WHERE user_id=?", (uid,))
    elif a == "rotate" and row:
        c.execute("UPDATE abs_cal_feeds SET secret=?, created_at=? WHERE id=?", (secrets.token_urlsafe(32), iso(now_utc()), row["id"]))
    elif a in ("create", "rotate") and not row:
        c.execute("INSERT INTO abs_cal_feeds(user_id, secret, created_at) VALUES(?,?,?)", (uid, secrets.token_urlsafe(32), iso(now_utc())))
    elif a != "create":
        raise BadInput(tr("Invalid value: {0}", "action"))
    c.commit()
    return jsonify(url=abc_url(abc_feed_row(c, uid)))
