"""2.94.0 B (#1929): appointment booking by customers ("Booking page"), separate from the internal disposition (hub_bookings).
One public page per person (appt_pages: slug, on / off, title, intro, the calendar confirmed bookings go into, weekly hours in
the page's time zone, optionally an office area a booking makes a lead in) with appointment types (appt_types: duration,
buffer, notice, days ahead). The customer opens /s/b/<slug> (server-rendered like the approval links, no scripts, no login),
picks a type and a free time (the weekly hours minus what is busy in the person's calendars, subscriptions, absences and other
bookings -- only free times leave the server, never titles), types name + e-mail and gets a mail with a confirmation link.
Only the POST of /s/b/c/<token> (a page with a button: mail scanners only GET) confirms: then an event in the chosen
calendar (the customer as attendee), a contact in the person's address book (an existing one with the same e-mail is
taken), a lead in the office area (office/leads.py lead_from_booking, part A) and a mail with the cancel link /s/b/x/<token>.
An unconfirmed booking holds its time APB_HOLD_MIN minutes, then it expires (on the next read).
Security: 256-bit tokens (only their hashes are stored), the same 404 for unknown / switched-off pages and tokens, rate limits
per client address and per page, at most APB_PENDING_MAIL open bookings per e-mail and APB_PENDING_PAGE per page, a honeypot,
a form check value bound to page + type + time (HMAC) plus Sec-Fetch-Site, the recipient's daily mail budget, escaped text,
length limits. Customer mails only go out while the page is on (the person's own cancel tells the customer by mail)."""
import hashlib
import hmac
import html
import json
import re
import secrets
import threading
from datetime import date, datetime, timedelta, timezone

from flask import g, jsonify, redirect, request

from ..core.config import app, APP_NAME, PUBLIC_URL, TZ
from ..core.i18n import LANGS, N_, short_day, tr
from ..core.db import body, bump, db, err, iso, now_utc, parse_iso, usettings
from ..core.pg import insert_id, system_ctx, write_lock
from ..core.access import acx_token_bind, Denied, need_feat
from ..accounts.session import _rate_blocked, _rate_fail, _token_hash, rate_ip
from ..core.errors import BadInput
from ..tasks.validation import as_int, valid_date, valid_hm
from ..api.common import hit_limit  # 2.149.0 G (#2517): pulled up from functions

APB_PREFIX = "/s/b/"
APB_HOLD_MIN = 30            # an unconfirmed booking holds its time this long
APB_PURGE_DAYS = 7           # expired (never confirmed) bookings are deleted after this
APB_CANCEL_DAYS = 30         # 2.148.1 C (#2493): cancelled, never confirmed bookings are deleted after this
APB_PENDING_MAIL = 3         # open bookings per customer e-mail and page
APB_PENDING_PAGE = 50        # open bookings per page
APB_VIEW_RATE = 60           # page views per client address and minute
APB_POST_RATE = 10           # bookings / confirmations per client address and minute
APB_PAGE_HOUR = 30           # booking attempts per page, client address and hour (2.148.1 D: per address)
APB_MAIL_DAY = 60            # 2.148.1 D (#2485): confirmation mails a booking page sends per day (own quota)
APB_BAD_LIMIT = 30           # unknown pages / tokens per address within the fail window (shared with the list links)
APB_TYPES_MAX = 30
APB_WEEKS = 8                # the first page view looks this many weeks ahead for the first free time
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,38}[a-z0-9]")
SLOT_RE = re.compile(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DEFAULT_HOURS = {d: ([["09:00", "17:00"]] if i < 5 else []) for i, d in enumerate(DAYS)}
NAME_MAX, EMAIL_MAX, PHONE_MAX, MSG_MAX, TITLE_MAX, INTRO_MAX = 120, 200, 40, 1000, 120, 1000
EMAIL_RE = re.compile(r"[^@\s<>\"(),;:\[\]]+@[^@\s<>\"(),;:\[\]]+\.[^@\s<>\"(),;:\[\]]+")  # one address only (no list, no display name)
PHONE_RE = re.compile(r"[0-9+()/. -]{3,40}")
APB_PRIVACY = N_("Your details are only used to arrange this appointment. You get one e-mail to confirm the booking and one with the confirmation.")


# ---------------------------------------------------------------- helpers
def apb_gate(c):
    """The person's own settings: people only (no agents, no kid accounts), the calendar module on."""
    u = g.user
    if u is None:
        raise Denied(401)
    if (u["kind"] if "kind" in u.keys() else "user") == "agent" or ("kid" in u.keys() and u["kid"]):
        raise Denied(403)
    need_feat("events")
    return u["id"]


def apb_mail_on():
    from ..integrations.mail import MAIL_OUT_ON
    return MAIL_OUT_ON


def apb_zone(p):
    from ..events.model import ev_zone
    return ev_zone(p["tz"] if p else "")


def apb_hours(p):
    try:
        h = json.loads(p["hours"] or "") if p else None
    except ValueError:
        h = None
    return h if isinstance(h, dict) else DEFAULT_HOURS


def apb_hours_clean(v):
    """{mon: [[HH:MM, HH:MM], ...], ...} -> the stored JSON (BadInput when invalid; at most three times per day, sorted)."""
    if not isinstance(v, dict) or any(k not in DAYS for k in v):
        raise BadInput(tr("Invalid value: {0}", "hours"))
    out = {}
    for d in DAYS:
        rows = v.get(d) or []
        if not isinstance(rows, list) or len(rows) > 3:
            raise BadInput(tr("Invalid value: {0}", "hours"))
        clean = []
        for r in rows:
            if not isinstance(r, list) or len(r) != 2 or not all(isinstance(x, str) and valid_hm(x) for x in r) or r[0] >= r[1]:
                raise BadInput(tr("Opening hours: the end must be after the start"))
            clean.append([r[0], r[1]])
        clean.sort()
        if any(clean[i][1] > clean[i + 1][0] for i in range(len(clean) - 1)):
            raise BadInput(tr("Opening hours: the times of one day overlap"))
        out[d] = clean
    return json.dumps(out)


def apb_slug_suggest(c, uid):
    from ..collab.comments import user_names
    base = (user_names(c, [uid]).get(uid) or "").lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        base = base.replace(a, b)
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:30] or "termine"
    if len(base) < 3:
        base = f"{base}-termine"
    for i in range(20):
        s = base if i == 0 else f"{base}-{secrets.token_hex(2)}"
        if not c.execute("SELECT 1 FROM appt_pages WHERE slug=?", (s,)).fetchone():
            return s
    return f"termine-{secrets.token_hex(4)}"


def apb_page_row(c, uid):
    return c.execute("SELECT * FROM appt_pages WHERE user_id=?", (uid,)).fetchone()


def apb_url(slug):
    return PUBLIC_URL.rstrip("/") + APB_PREFIX + slug


def apb_cal_ok(c, uid, cid):
    """True when uid may write into calendar cid (own or shared with "can edit")."""
    from ..events.model import need_evcal
    try:
        need_evcal(c, cid, write=True, uid=uid)
        return True
    except Denied:
        return False


def apb_offices(c, uid):
    """[{id, name, personal}] the office areas uid may put leads into: the personal office and the organisations where uid is
    an admin of the office (only with the module Office on)."""
    from ..office.model import office_on, office_role, pb_personal
    from ..accounts.orgs import user_orgs
    if not office_on(c, uid):
        return []
    out = [{"id": pb_personal(c, uid, create=False) or "personal", "name": tr("Private office"), "personal": True}]
    for oid in user_orgs(c, uid):
        if office_role(c, uid, oid) == "admin":
            with system_ctx(c):  # the name of an organisation uid belongs to (instance structure)
                r = c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone()
            out.append({"id": oid, "name": r[0] if r else "?", "personal": False})
    return out


def apb_office_clean(c, uid, v):
    """office_org_id of the settings: null, "personal" (the personal office, made on first use) or an organisation where uid
    is an office admin -> id | None (BadInput / 403 otherwise)."""
    from ..office.model import office_on, office_role, pb_personal, pb_owner
    if v in (None, "", 0):
        return None
    if not office_on(c, uid):
        raise Denied(403)
    if v == "personal":
        return pb_personal(c, uid)
    oid = as_int(v, "office_org_id", 1)
    if pb_owner(c, oid) not in (None, uid) or office_role(c, uid, oid) != "admin":
        raise Denied(404)
    return oid


def apb_page_out(c, uid, p):
    from ..events.model import cals_for
    from ..contacts.model import contacts_on
    from ..lists.public import public_links_on
    cals = [{"id": k["id"], "name": k["name"], "color": k["color"]} for k in cals_for(c, uid) if k["role"] in ("owner", "edit")]
    d = {"slug": p["slug"], "enabled": bool(p["enabled"]), "title": p["title"], "intro": p["intro"], "cal_id": p["cal_id"],
         "office_org_id": p["office_org_id"], "hours": apb_hours(p), "tz": p["tz"] or getattr(TZ, "key", ""),
         "url": apb_url(p["slug"])} if p else \
        {"slug": apb_slug_suggest(c, uid), "enabled": False, "title": "", "intro": "", "cal_id": None, "office_org_id": None,
         "hours": DEFAULT_HOURS, "tz": getattr(TZ, "key", ""), "url": None}
    return {"page": d, "exists": bool(p), "calendars": cals, "offices": apb_offices(c, uid), "mail_ok": apb_mail_on(),
            "links_ok": bool(public_links_on(c)), "contacts_on": contacts_on(c, uid)}


# ---------------------------------------------------------------- the person's settings
@app.get("/api/appt/page")
def apb_page_get():
    c = db()
    uid = apb_gate(c)
    return jsonify(apb_page_out(c, uid, apb_page_row(c, uid)))


@app.put("/api/appt/page")
def apb_page_put():
    """{slug?, enabled?, title?, intro?, cal_id?, office_org_id? (id | "personal" | null), hours?, tz?} -> the page (made on the
    first save). Switching on needs outgoing mail, public links and a calendar the person may write into."""
    from ..events.model import default_cal, tz_ok
    from ..lists.public import public_links_on
    c = db()
    uid = apb_gate(c)
    b = body()
    if not isinstance(b, dict):
        return err(tr("Invalid data"))
    if b.get("office_org_id") == "personal":  # 2.94.0 (#1929 review): made before the locks (making it commits, which would end them)
        from ..office.model import office_on, pb_personal
        if office_on(c, uid):
            pb_personal(c, uid)
    write_lock(c, f"appt:{uid}")
    p = apb_page_row(c, uid)
    f = {}
    try:
        if "slug" in b or not p:
            s = b.get("slug") if "slug" in b else apb_slug_suggest(c, uid)
            if not isinstance(s, str) or not SLUG_RE.fullmatch(s.strip().lower()):
                raise BadInput(tr("The address may have 3 to 40 lower-case letters, digits and hyphens"))
            f["slug"] = s.strip().lower()
            write_lock(c, "appt:slugs")  # two people taking the same address at once
            if c.execute("SELECT 1 FROM appt_pages WHERE slug=? AND user_id<>?", (f["slug"], uid)).fetchone():
                return err(tr("This address is already taken"), 409)
        for k, mx in (("title", TITLE_MAX), ("intro", INTRO_MAX)):
            if k in b:
                v = b[k] if b[k] is not None else ""
                if not isinstance(v, str):
                    raise BadInput(tr("Invalid value: {0}", k))
                v = v.replace("\r", "").replace("\x00", "").strip()
                f[k] = (" ".join(v.split()) if k == "title" else v)[:mx]
        if "cal_id" in b:
            if b["cal_id"] in (None, ""):
                f["cal_id"] = None
            else:
                cid = as_int(b["cal_id"], "cal_id", 1)
                if not apb_cal_ok(c, uid, cid):
                    raise Denied(404)
                f["cal_id"] = cid
        if "office_org_id" in b:
            f["office_org_id"] = apb_office_clean(c, uid, b["office_org_id"])
        if "hours" in b:
            f["hours"] = apb_hours_clean(b["hours"])
        if "tz" in b:
            if not isinstance(b["tz"], str) or not b["tz"] or not tz_ok(b["tz"]):
                raise BadInput(tr("Invalid value: {0}", "tz"))
            f["tz"] = b["tz"]
        if "enabled" in b:
            if not isinstance(b["enabled"], bool):
                raise BadInput(tr("Invalid value: {0}", "enabled"))
            f["enabled"] = 1 if b["enabled"] else 0
    except BadInput as x:
        return err(str(x))
    if f.get("enabled"):
        if not apb_mail_on():
            return err(tr("This server sends no e-mail: the booking page cannot be switched on"), 409)
        if not public_links_on(c):
            return err(tr("Public links are turned off on this server"), 409)
        cid = f.get("cal_id", p["cal_id"] if p else None)
        if not cid or not apb_cal_ok(c, uid, cid):
            f["cal_id"] = default_cal(c, uid)
    ts = iso(now_utc())
    if not p:
        cols = {"user_id": uid, "slug": f.pop("slug"), "hours": json.dumps(DEFAULT_HOURS), "tz": getattr(TZ, "key", ""),
                "created_at": ts, "updated_at": ts, **f}
        c.execute(f"INSERT INTO appt_pages({','.join(cols)}) VALUES({','.join('?' * len(cols))})", list(cols.values()))
    elif f:
        f["updated_at"] = ts
        c.execute(f"UPDATE appt_pages SET {','.join(k + '=?' for k in f)} WHERE user_id=?", [*f.values(), uid])
    bump(c)
    c.commit()
    return jsonify(apb_page_out(c, uid, apb_page_row(c, uid)))


# appointment types
TYPE_NUM = {"duration_min": (5, 480), "buffer_min": (0, 240), "notice_h": (0, 720), "days_ahead": (1, 365)}


def apb_type_fields(b, create=False):
    f = {}
    if "name" in b or create:
        v = b.get("name")
        if not isinstance(v, str) or not " ".join(v.split()):
            raise BadInput(tr("Name missing"))
        f["name"] = " ".join(v.split())[:100]
    for k, (lo, hi) in TYPE_NUM.items():
        if k in b:
            f[k] = as_int(b[k], k, lo, hi)
    for k, mx in (("location", 200), ("note", 1000)):
        if k in b:
            v = b[k] if b[k] is not None else ""
            if not isinstance(v, str):
                raise BadInput(tr("Invalid value: {0}", k))
            f[k] = (" ".join(v.split()) if k == "location" else v.replace("\r", "").replace("\x00", "").strip())[:mx]
    if "active" in b:
        if not isinstance(b["active"], bool):
            raise BadInput(tr("Invalid value: {0}", "active"))
        f["active"] = 1 if b["active"] else 0
    if "sort" in b:
        if not isinstance(b["sort"], (int, float)) or isinstance(b["sort"], bool):
            raise BadInput(tr("Invalid value: {0}", "sort"))
        f["sort"] = float(b["sort"])
    return f


def apb_type_out(r):
    return {"id": r["id"], "name": r["name"], "duration_min": r["duration_min"], "buffer_min": r["buffer_min"], "notice_h": r["notice_h"],
            "days_ahead": r["days_ahead"], "location": r["location"], "note": r["note"], "active": bool(r["active"]), "sort": r["sort"]}


def apb_type_row(c, uid, tid, deleted=False):
    r = c.execute(f"SELECT * FROM appt_types WHERE id=? AND user_id=? AND deleted_at IS {'NOT ' if deleted else ''}NULL", (tid, uid)).fetchone()
    if not r:
        raise Denied(404)
    return r


@app.get("/api/appt/types")
def apb_types_list():
    c = db()
    uid = apb_gate(c)
    rows = c.execute("SELECT * FROM appt_types WHERE user_id=? AND deleted_at IS NULL ORDER BY sort, id", (uid,)).fetchall()
    return jsonify(types=[apb_type_out(r) for r in rows])


@app.post("/api/appt/types")
def apb_type_new():
    c = db()
    uid = apb_gate(c)
    b = body()
    try:
        f = apb_type_fields(b if isinstance(b, dict) else {}, create=True)
    except BadInput as x:
        return err(str(x))
    write_lock(c, f"appt:{uid}")
    if c.execute("SELECT COUNT(*) FROM appt_types WHERE user_id=? AND deleted_at IS NULL", (uid,)).fetchone()[0] >= APB_TYPES_MAX:
        return err(tr("At most {0} appointment types", APB_TYPES_MAX), 409)
    if "sort" not in f:
        f["sort"] = float((c.execute("SELECT MAX(sort) FROM appt_types WHERE user_id=?", (uid,)).fetchone()[0] or 0) + 1)
    ts = iso(now_utc())
    cols = {"user_id": uid, **f, "created_at": ts, "updated_at": ts}
    tid = insert_id(c, f"INSERT INTO appt_types({','.join(cols)}) VALUES({','.join('?' * len(cols))})", list(cols.values()))
    bump(c)
    c.commit()
    return jsonify(apb_type_out(apb_type_row(c, uid, tid))), 201


@app.patch("/api/appt/types/<int:tid>")
def apb_type_edit(tid):
    c = db()
    uid = apb_gate(c)
    apb_type_row(c, uid, tid)
    b = body()
    try:
        f = apb_type_fields(b if isinstance(b, dict) else {})
    except BadInput as x:
        return err(str(x))
    if f:
        f["updated_at"] = iso(now_utc())
        c.execute(f"UPDATE appt_types SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), tid])
        bump(c)
        c.commit()
    return jsonify(apb_type_out(apb_type_row(c, uid, tid)))


@app.delete("/api/appt/types/<int:tid>")
def apb_type_delete(tid):
    """Deleted with deleted_at (Undo: restore); its bookings stay as they are."""
    c = db()
    uid = apb_gate(c)
    apb_type_row(c, uid, tid)
    c.execute("UPDATE appt_types SET deleted_at=? WHERE id=?", (iso(now_utc()), tid))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.post("/api/appt/types/<int:tid>/restore")
def apb_type_restore(tid):
    c = db()
    uid = apb_gate(c)
    apb_type_row(c, uid, tid, deleted=True)
    c.execute("UPDATE appt_types SET deleted_at=NULL, updated_at=? WHERE id=?", (iso(now_utc()), tid))
    bump(c)
    c.commit()
    return jsonify(apb_type_out(apb_type_row(c, uid, tid)))


# bookings
def apb_expire(c, uid):
    """Unconfirmed bookings older than APB_HOLD_MIN expire; expired ones older than APB_PURGE_DAYS are deleted (their data was
    never confirmed)."""
    write_lock(c, f"appt:{uid}")  # CI of 2.167.1: two sweeps of the same person at once (bookings list + a booking) deadlocked on the rows
    now = now_utc()
    c.execute("UPDATE appt_bookings SET status='expired' WHERE user_id=? AND status='pending' AND created_at<?",
              (uid, iso(now - timedelta(minutes=APB_HOLD_MIN))))
    c.execute("DELETE FROM appt_bookings WHERE user_id=? AND status='expired' AND created_at<?", (uid, iso(now - timedelta(days=APB_PURGE_DAYS))))
    # 2.148.1 C (#2493): cancelled bookings that were never confirmed (address, contact data) go after APB_CANCEL_DAYS
    c.execute("DELETE FROM appt_bookings WHERE user_id=? AND status='cancelled' AND COALESCE(confirmed_at, '')='' AND COALESCE(cancelled_at, '')<>'' "
              "AND cancelled_at<?", (uid, iso(now - timedelta(days=APB_CANCEL_DAYS))))


def apb_booking_out(r, tnames):
    return {"id": r["id"], "type_id": r["type_id"], "type_name": tnames.get(r["type_id"], ""), "start": r["start"], "end": r["end"],
            "name": r["name"], "email": r["email"], "phone": r["phone"], "message": r["message"], "status": r["status"],
            "event_id": r["event_id"], "contact_id": r["contact_id"], "deal_id": r["deal_id"], "cancel_reason": r["cancel_reason"],
            "cancelled_by": r["cancelled_by"] or None, "created_at": r["created_at"], "confirmed_at": r["confirmed_at"],
            "cancelled_at": r["cancelled_at"]}


@app.get("/api/appt/bookings")
def apb_bookings_list():
    """The coming bookings and those of the last 30 days (confirmed, open and cancelled; expired ones are not shown)."""
    c = db()
    uid = apb_gate(c)
    apb_expire(c, uid)
    c.commit()
    rows = c.execute("SELECT * FROM appt_bookings WHERE user_id=? AND status IN ('pending','confirmed','cancelled') AND \"end\">=? "
                     "ORDER BY start, id LIMIT 300", (uid, iso(now_utc() - timedelta(days=30)))).fetchall()
    tnames = {r[0]: r[1] for r in c.execute("SELECT id, name FROM appt_types WHERE user_id=?", (uid,))}
    return jsonify(bookings=[apb_booking_out(r, tnames) for r in rows])


@app.post("/api/appt/bookings/<int:bid>/cancel")
def apb_booking_cancel(bid):
    """{reason?} -> the person cancels a booking: the event goes (as a deletion in the calendar), the customer gets a mail."""
    c = db()
    uid = apb_gate(c)
    b = body()
    reason = b.get("reason") if isinstance(b, dict) else None
    reason = apb_clean(reason if isinstance(reason, str) else "", MSG_MAX)
    write_lock(c, f"appt:{uid}")
    r = c.execute("SELECT * FROM appt_bookings WHERE id=? AND user_id=?", (bid, uid)).fetchone()
    if not r:
        raise Denied(404)
    if r["status"] not in ("pending", "confirmed"):
        return err(tr("This booking is no longer open"), 409)
    mail = apb_cancel(c, r, "host", reason)
    c.commit()
    if mail:
        threading.Thread(target=apb_mail_bg, args=mail, daemon=True).start()
    tnames = {x[0]: x[1] for x in c.execute("SELECT id, name FROM appt_types WHERE user_id=?", (uid,))}
    return jsonify(apb_booking_out(c.execute("SELECT * FROM appt_bookings WHERE id=?", (bid,)).fetchone(), tnames))


def apb_cancel(c, r, by, reason=""):
    """Cancels booking r (by guest | host): status, the event deleted like in the calendar (restorable from its trash); host:
    returns the mail to the customer (or None), guest: a push to the person. The caller commits."""
    from ..events.model import ev_delete
    c.execute("UPDATE appt_bookings SET status='cancelled', cancelled_by=?, cancel_reason=?, cancelled_at=? WHERE id=?",
              (by, reason[:MSG_MAX], iso(now_utc()), r["id"]))  # both links stay: they show "cancelled" / "expired"
    if r["event_id"]:
        ev = c.execute("SELECT * FROM events WHERE id=? AND deleted_at IS NULL", (r["event_id"],)).fetchone()
        if ev:
            ev_delete(c, ev)
    bump(c)
    if by == "host":
        if r["status"] != "confirmed" or not apb_mail_on():
            return None
        return apb_mail_cancelled(c, r, reason)
    apb_push(c, r, "cancel")
    return None


# ---------------------------------------------------------------- free times
def apb_utc(dt):
    return dt.astimezone(timezone.utc)


def apb_busy(c, uid, p, lo, hi, skip=None):
    """[(start, end)] aware UTC of everything that blocks uid between lo and hi (aware): events (busy, not cancelled) of the
    calendars uid sees and did not hide plus the page's calendar, events uid accepted, timed events of visible subscriptions,
    absences (whole / half days in the page's zone), open bookings and confirmed ones without an event (the event stands for
    the booking: moved or deleted in the calendar, the time follows)."""
    from ..events.model import ev_expand, my_cal_ids
    zone = apb_zone(p)
    dlo, dhi = (lo - timedelta(days=1)).date(), (hi + timedelta(days=1)).date()
    out = []

    def day_span(d0, d1):  # local days [d0, d1) -> UTC
        return (apb_utc(datetime(d0.year, d0.month, d0.day, tzinfo=zone)), apb_utc(datetime(d1.year, d1.month, d1.day, tzinfo=zone)))
    from ..events.model import default_cal
    cals = set(my_cal_ids(c, uid, hidden=False))
    # 2.94.0 (#1929 review): the calendar the bookings go into counts even when hidden in the view (apb_make's choice)
    tc = p["cal_id"] if p and p["cal_id"] and apb_cal_ok(c, uid, p["cal_id"]) else default_cal(c, uid, create=False)
    if tc:
        cals.add(tc)
    rows = []
    if cals:
        q = ",".join("?" * len(cals))
        rows = c.execute(f"""SELECT * FROM events WHERE cal_id IN ({q}) AND deleted_at IS NULL AND busy=1 AND status<>'cancelled'
                             AND first_day<=? AND (last_day='' OR last_day>=?)""", [*cals, dhi.isoformat(), dlo.isoformat()]).fetchall()
    rows += c.execute("""SELECT e.* FROM events e JOIN event_attendees a ON a.event_id=e.id AND a.user_id=? WHERE a.partstat='accepted'
                         AND e.deleted_at IS NULL AND e.busy=1 AND e.status<>'cancelled' AND e.first_day<=? AND (e.last_day='' OR e.last_day>=?)""",
                      (uid, dhi.isoformat(), dlo.isoformat())).fetchall()
    for r in rows:
        for o in ev_expand(r, dlo, dhi):
            if o["all_day"]:
                out.append(day_span(o["s"], o["e"]))
            else:
                out.append((apb_utc(o["s"]), apb_utc(o["e"])))
    for r in c.execute("""SELECT e.start, e."end" FROM cal_events e JOIN cal_subs s ON s.id=e.sub_id WHERE s.user_id=? AND s.visible=1
                          AND e.all_day=0 AND e.d1>=? AND e.d0<=?""", (uid, dlo.isoformat(), dhi.isoformat())):
        s, e = parse_iso(r[0]), parse_iso(r[1])
        if s and e:
            out.append((s, e))
    for r in c.execute("SELECT start_date, end_date, half_day FROM hub_absences WHERE user_id=? AND deleted_at IS NULL AND end_date>=? AND start_date<=? "
                       "AND status='approved'",  # 2.125.0 A (#2117): an open vacation request does not block the booking page yet
                       (uid, dlo.isoformat(), dhi.isoformat())):
        if not (valid_date(r[0]) and valid_date(r[1])):
            continue
        d0, d1 = date.fromisoformat(r[0]), date.fromisoformat(r[1]) + timedelta(days=1)
        s, e = day_span(d0, d1)
        if r[2] in ("am", "pm") and r[0] == r[1]:
            mid = apb_utc(datetime(d0.year, d0.month, d0.day, 12, tzinfo=zone))
            s, e = (s, mid) if r[2] == "am" else (mid, e)
        out.append((s, e))
    cut = iso(now_utc() - timedelta(minutes=APB_HOLD_MIN))
    for r in c.execute("""SELECT id, start, "end" FROM appt_bookings WHERE user_id=? AND start<? AND "end">?
                          AND ((status='pending' AND created_at>=?) OR (status='confirmed' AND event_id IS NULL))""",
                       (uid, iso(hi), iso(lo), cut)):
        if r[0] != skip:
            s, e = parse_iso(r[1]), parse_iso(r[2])
            if s and e:
                out.append((s, e))
    return sorted(x for x in out if x[1] > lo and x[0] < hi)


def apb_slots(c, p, t, d0, d1, busy=None, skip=None):
    """{local day: [slot start (aware, page zone)]} of type t between the local days d0..d1 (inclusive): the weekly hours on
    a grid of the duration (at most 30-minute steps), after the notice, within days ahead, free of busy times +- the buffer."""
    zone = apb_zone(p)
    now = now_utc()
    dur, buf = timedelta(minutes=t["duration_min"]), timedelta(minutes=t["buffer_min"])
    step = timedelta(minutes=min(t["duration_min"], 30))
    first = now + timedelta(hours=t["notice_h"])
    today = now.astimezone(zone).date()
    last = min(d1, today + timedelta(days=t["days_ahead"]))
    d0 = max(d0, today)
    if d0 > last:
        return {}
    if busy is None:
        busy = apb_busy(c, p["user_id"], p, apb_utc(datetime(d0.year, d0.month, d0.day, tzinfo=zone)) - buf - timedelta(days=1),
                        apb_utc(datetime(last.year, last.month, last.day, tzinfo=zone)) + timedelta(days=2) + buf, skip)
    hours = apb_hours(p)
    out = {}
    d = d0
    while d <= last:
        for a, b in hours.get(DAYS[d.weekday()]) or []:
            if not (valid_hm(a) and valid_hm(b)):
                continue
            t0 = datetime(d.year, d.month, d.day, int(a[:2]), int(a[3:]))
            end = datetime(d.year, d.month, d.day, int(b[:2]), int(b[3:]))
            while t0 + dur <= end:
                s = t0.replace(tzinfo=zone)
                su = apb_utc(s)
                if su >= first and su.astimezone(zone).replace(tzinfo=None) == t0:  # skips a time the clock change leaves out
                    lo_, hi_ = su - buf, su + dur + buf
                    if not any(x[0] < hi_ and x[1] > lo_ for x in busy):
                        out.setdefault(d, []).append(s)
                t0 += step
        d += timedelta(days=1)
    return out


def apb_slot_parse(p, v):
    """'YYYYMMDDTHHMM' (wall time in the page's zone) -> aware datetime | None."""
    m = SLOT_RE.fullmatch(v or "")
    if not m:
        return None
    try:
        return datetime(*map(int, m.groups()), tzinfo=apb_zone(p))
    except ValueError:
        return None


def apb_slot_key(s):
    return s.strftime("%Y%m%dT%H%M")


def apb_slot_free(c, p, t, s, skip=None):
    """True when s (aware, page zone) is one of the free times of type t right now."""
    return any(x == s for x in apb_slots(c, p, t, s.date(), s.date(), skip=skip).get(s.date(), []))


# ---------------------------------------------------------------- the customer's pages
def apb_clean(v, mx):
    v = (v or "").replace("\r", "")
    v = "".join(ch for ch in v if ch == "\n" or ord(ch) >= 32)
    return v.strip()[:mx]


def apb_lang(c, uid):
    """The customer's language: Accept-Language if the app has it, else the person's language."""
    for part in (request.headers.get("Accept-Language") or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in LANGS:
            return code
    lg = usettings(c, uid).get("lang") or "en"
    return lg if lg in LANGS else "en"


def apb_bind(uid):
    """From here on the request reads and writes with the page owner's context (row-level security), like the calendar feed."""
    from ..lists.public import PUB_ACTOR
    g.user, g.auth_via = PUB_ACTOR, "public"
    acx_token_bind(uid)


def apb_live(c, uid):
    """True when the page of uid may serve customers: the account enabled, a person, calendar module on, mail out, public links."""
    from ..lists.public import public_links_on
    with system_ctx(c):  # the owner's account state (the public request has no user yet)
        u = c.execute("SELECT disabled, kind, kid FROM users WHERE id=?", (uid,)).fetchone()
    if not u or u["disabled"] or u["kind"] == "agent" or u["kid"]:
        return False
    return apb_mail_on() and public_links_on(c) and "events" in (usettings(c, uid).get("features") or "").split(",")


def apb_open(c, slug):
    """(page, None) or (None, the 404 / rate-limit answer): the same answer for unknown and switched-off pages."""
    from ..lists.public import pub_gone, pub_limited
    from ..notify.alerts import aa_count
    ip = rate_ip()
    if hit_limit("apbv:" + ip, APB_VIEW_RATE):
        return None, pub_limited(apb_lang_hdr())
    bad = [("pubbad:" + ip, APB_BAD_LIMIT)]  # 2.126.0 C (#1979 I2): limited only when the link is not valid
    p = c.execute("SELECT * FROM appt_pages WHERE slug=? AND enabled=1", (slug,)).fetchone() if SLUG_RE.fullmatch(slug or "") else None
    if not p or not apb_live(c, p["user_id"]):
        if _rate_blocked(bad):
            return None, pub_limited(apb_lang_hdr())
        _rate_fail(bad)
        aa_count("security", "publink", ip)
        return None, pub_gone()
    apb_bind(p["user_id"])
    return p, None


def apb_lang_hdr():
    from ..accounts.session import _accept_lang
    return _accept_lang()


def apb_type_pub(c, p, tid):
    return c.execute("SELECT * FROM appt_types WHERE id=? AND user_id=? AND active=1 AND deleted_at IS NULL", (tid, p["user_id"])).fetchone()


def apb_owner_name(c, uid):
    """2.190.0 D (#2496): the owner's display name for public pages and mails ('' without one, never the login name --
    also not when the display name is just the login name)."""
    r = c.execute("SELECT display_name, username FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    dn = (r[0] or "").strip() if r else ""
    return dn if dn.lower() != (r[1] or "").strip().lower() else ""


def apb_head(c, p, lg, sub=""):
    e = html.escape
    title = p["title"] or apb_owner_name(c, p["user_id"]) or tr("Book an appointment", lg=lg)
    return f'<header><div class="brand"><span>{e(apb_owner_name(c, p["user_id"]))}</span></div><h1>{e(title)}</h1>' + \
        (f'<p class="sub">{e(sub)}</p>' if sub else "") + '</header>'


def apb_day(d, lg):
    names = (LANGS.get(lg) or {}).get("_weekdays")
    wd = names[(d.weekday() + 1) % 7] if isinstance(names, list) and len(names) == 7 else d.strftime("%A")
    return f"{wd}, {short_day(d, lg)}"


def apb_when(p, s, e, lg):
    """'Monday, 20.10., 09:30 - 10:00 (Europe/Berlin)' of an aware start / end shown in the page's zone."""
    zone = apb_zone(p)
    s, e = s.astimezone(zone), e.astimezone(zone)
    return f"{apb_day(s.date(), lg)}, {s:%H:%M} – {e:%H:%M} ({getattr(zone, 'key', '') or 'UTC'})"


def apb_dur(t, lg):
    return tr("{0} min", t["duration_min"], lg=lg)


def apb_html(c, p, title, main, lg, code=200):
    from ..lists.public import pub_html
    return pub_html(f"{title} · {APP_NAME}", main, lg, code)


def apb_msg(c, p, lg, h, lines=(), back=None, code=200):
    e = html.escape
    main = f'<div class="msg"><h1>{e(h)}</h1>' + "".join(f"<p>{e(x)}</p>" for x in lines if x) + \
        (f'<p><a class="btn" href="{e(back)}">{e(tr("Choose another time", lg=lg))}</a></p>' if back else "") + "</div>"
    return apb_html(c, p, h, main, lg, code)


@app.get("/s/b/<slug>")
def apb_pub_page(slug):
    c = db()
    p, bad = apb_open(c, slug)
    if bad:
        return bad
    lg = apb_lang(c, p["user_id"])
    e = html.escape
    types = c.execute("SELECT * FROM appt_types WHERE user_id=? AND active=1 AND deleted_at IS NULL ORDER BY sort, id", (p["user_id"],)).fetchall()
    items = "".join(f'<li><a href="{APB_PREFIX}{e(p["slug"])}/{t["id"]}"><b>{e(t["name"])}</b><span class="sub">{e(apb_dur(t, lg))}'
                    f'{" · " + e(t["location"]) if t["location"] else ""}</span>'
                    + (f'<span class="apb-note">{e(t["note"])}</span>' if t["note"] else "") + '</a></li>' for t in types)
    main = apb_head(c, p, lg, tr("Book an appointment", lg=lg)) + \
        (f'<div class="intro"><p>{e(p["intro"])}</p></div>' if p["intro"] else "") + \
        (f'<ul class="ptall apb-types">{items}</ul>' if types else f'<p class="empty">{e(tr("No appointments can be booked at the moment.", lg=lg))}</p>')
    return apb_html(c, p, p["title"] or tr("Book an appointment", lg=lg), main, lg)


@app.get("/s/b/<slug>/<int:tid>")
def apb_pub_times(slug, tid):
    """The free times of one type, a week at a time (?w=YYYY-MM-DD: the Monday; without it the first week with a free time)."""
    c = db()
    p, bad = apb_open(c, slug)
    if bad:
        return bad
    from ..lists.public import pub_gone
    t = apb_type_pub(c, p, tid)
    if not t:
        return pub_gone()
    lg = apb_lang(c, p["user_id"])
    e = html.escape
    zone = apb_zone(p)
    today = now_utc().astimezone(zone).date()
    w = request.args.get("w") or ""
    mon = today - timedelta(days=today.weekday())
    if valid_date(w):
        x = date.fromisoformat(w)
        mon = max(mon, x - timedelta(days=x.weekday()))
        slots = apb_slots(c, p, t, mon, mon + timedelta(days=6))
    else:  # the first week with a free time (looking APB_WEEKS ahead at most)
        allw = apb_slots(c, p, t, mon, mon + timedelta(days=7 * APB_WEEKS - 1))
        if allw:
            f0 = min(allw)
            mon = f0 - timedelta(days=f0.weekday())
        slots = {d: v for d, v in allw.items() if mon <= d <= mon + timedelta(days=6)}
    last = today + timedelta(days=t["days_ahead"])
    base = f'{APB_PREFIX}{e(p["slug"])}/{t["id"]}'
    days = ""
    for i in range(7):
        d = mon + timedelta(days=i)
        v = slots.get(d) or []
        if not v:
            continue
        days += (f'<section class="apb-day"><h2>{e(apb_day(d, lg))}</h2><div class="apb-slots">'
                 + "".join(f'<a href="{base}/{apb_slot_key(s)}">{s:%H:%M}</a>' for s in v) + '</div></section>')
    prev = mon - timedelta(days=7)
    nxt = mon + timedelta(days=7)
    nav = '<nav class="apb-nav">' + \
        (f'<a href="{base}?w={prev.isoformat()}" rel="nofollow">{e(tr("Previous week", lg=lg))}</a>' if mon > today else '<span></span>') + \
        f'<span class="sub">{e(short_day(mon, lg))} – {e(short_day(mon + timedelta(days=6), lg))}</span>' + \
        (f'<a href="{base}?w={nxt.isoformat()}" rel="nofollow">{e(tr("Next week", lg=lg))}</a>' if nxt <= last else '<span></span>') + '</nav>'
    main = apb_head(c, p, lg, f'{t["name"]} · {apb_dur(t, lg)}') + \
        f'<p class="sub"><a href="{APB_PREFIX}{e(p["slug"])}">{e(tr("All appointment types", lg=lg))}</a></p>' + nav + \
        (days or f'<p class="empty">{e(tr("No free times this week.", lg=lg))}</p>') + \
        f'<p class="sub apb-tz">{e(tr("Times in {0}", getattr(zone, "key", "") or "UTC", lg=lg))}</p>'
    return apb_html(c, p, t["name"], main, lg)


def apb_form_key(c, p, tid, slot):
    from ..accounts.login import auth_key
    return hmac.new(auth_key(c), f"apb:{p['user_id']}:{p['slug']}:{tid}:{slot}".encode(), hashlib.sha256).hexdigest()


def apb_form(c, p, t, s, lg, vals=None, error=None, code=200):
    e = html.escape
    v = vals or {}
    key = apb_slot_key(s)
    act = f'{APB_PREFIX}{e(p["slug"])}/{t["id"]}/{key}'
    form = (f'<form method="post" action="{act}" class="fform apb-form">'
            f'<input type="hidden" name="f" value="{apb_form_key(c, p, t["id"], key)}">'
            f'<div class="hp" aria-hidden="true"><label for="apb-web">Website</label><input id="apb-web" name="website" tabindex="-1" autocomplete="off"></div>'
            f'<label for="apb-name">{e(tr("Your name|public", lg=lg))}</label><input id="apb-name" name="name" maxlength="{NAME_MAX}" autocomplete="name" required value="{e(v.get("name", ""))}">'
            f'<label for="apb-mail">{e(tr("E-mail", lg=lg))}</label><input id="apb-mail" name="email" type="email" maxlength="{EMAIL_MAX}" autocomplete="email" required value="{e(v.get("email", ""))}">'
            f'<label for="apb-tel">{e(tr("Phone (optional)", lg=lg))}</label><input id="apb-tel" name="phone" type="tel" maxlength="{PHONE_MAX}" autocomplete="tel" value="{e(v.get("phone", ""))}">'
            f'<label for="apb-msg">{e(tr("Message (optional)", lg=lg))}</label><textarea id="apb-msg" name="message" rows="3" maxlength="{MSG_MAX}">{e(v.get("message", ""))}</textarea>'
            + (f'<p class="err" role="alert">{e(error)}</p>' if error else "")
            + f'<button type="submit">{e(tr("Book", lg=lg))}</button></form>'
            f'<p class="signote">{e(tr(APB_PRIVACY, lg=lg))}</p>')
    main = apb_head(c, p, lg, t["name"]) + f'<p class="apb-when">{e(apb_when(p, s, s + timedelta(minutes=t["duration_min"]), lg))}</p>' + \
        (f'<p class="sub">{e(t["location"])}</p>' if t["location"] else "") + \
        f'<p class="sub"><a href="{APB_PREFIX}{e(p["slug"])}/{t["id"]}?w={(s.date() - timedelta(days=s.weekday())).isoformat()}">{e(tr("Choose another time", lg=lg))}</a></p>' + form
    return apb_html(c, p, t["name"], main, lg, code)


def apb_gone_slot(c, p, t, s, lg):
    back = f'{APB_PREFIX}{p["slug"]}/{t["id"]}' + (f'?w={(s.date() - timedelta(days=s.weekday())).isoformat()}' if s else "")
    return apb_msg(c, p, lg, tr("This time is no longer free", lg=lg), [tr("Please choose another time.", lg=lg)], back, 409)


@app.get("/s/b/<slug>/<int:tid>/<slot>")
def apb_pub_form(slug, tid, slot):
    c = db()
    p, bad = apb_open(c, slug)
    if bad:
        return bad
    from ..lists.public import pub_gone
    t = apb_type_pub(c, p, tid)
    s = apb_slot_parse(p, slot)
    if not t or not s:
        return pub_gone()
    lg = apb_lang(c, p["user_id"])
    if not apb_slot_free(c, p, t, s):
        return apb_gone_slot(c, p, t, s, lg)
    return apb_form(c, p, t, s, lg)


def apb_denied(lg):
    from ..lists.public import pub_html
    return pub_html(tr("Not allowed", lg=lg), f'<div class="msg"><h1>{html.escape(tr("Not allowed", lg=lg))}</h1></div>', lg, 403)


@app.post("/s/b/<slug>/<int:tid>/<slot>")
def apb_pub_book(slug, tid, slot):
    """The customer books: a pending booking (holds the time APB_HOLD_MIN minutes) + a mail with the confirmation link."""
    from ..lists.public import pub_gone, pub_limited
    c = db()
    p, bad = apb_open(c, slug)
    if bad:
        return bad
    t = apb_type_pub(c, p, tid)
    s = apb_slot_parse(p, slot)
    if not t or not s:
        return pub_gone()
    lg, ip, uid = apb_lang(c, p["user_id"]), rate_ip(), p["user_id"]
    if request.headers.get("Sec-Fetch-Site", "") == "cross-site" or \
            not hmac.compare_digest(request.form.get("f") or "", apb_form_key(c, p, tid, apb_slot_key(s))):
        return apb_denied(lg)
    if hit_limit("apbp:" + ip, APB_POST_RATE):
        return pub_limited(lg)
    vals = {k: apb_clean(request.form.get(k), mx) for k, mx in (("name", NAME_MAX), ("email", EMAIL_MAX), ("phone", PHONE_MAX), ("message", MSG_MAX))}
    vals["name"] = " ".join(vals["name"].split())
    if request.form.get("website"):  # the honeypot: a bot gets the same answer as a person, nothing is stored or sent
        return apb_msg(c, p, lg, tr("Almost done: please check your e-mail", lg=lg), [tr("We sent you a link. Your booking counts once you confirm it there (within 30 minutes).", lg=lg)])
    if len(vals["name"]) < 2:
        return apb_form(c, p, t, s, lg, vals, tr("Please type your name.", lg=lg), 400)
    if not EMAIL_RE.fullmatch(vals["email"]):
        return apb_form(c, p, t, s, lg, vals, tr("Please check the e-mail address.", lg=lg), 400)
    if vals["phone"] and not PHONE_RE.fullmatch(vals["phone"]):
        return apb_form(c, p, t, s, lg, vals, tr("Please check the phone number.", lg=lg), 400)
    # 2.148.1 D (#2485): the hourly limit counts per page and client address (one address cannot close the page for all)
    if hit_limit(f"apbs:{uid}:{ip}", APB_PAGE_HOUR, 3600):  # 2.94.0 (#1929 review): counted only for valid requests (no lock-out by junk)
        return pub_limited(lg)
    write_lock(c, f"appt:{uid}")  # two bookings of the same time: the second sees the first
    apb_expire(c, uid)
    em = vals["email"].lower()
    if c.execute("SELECT COUNT(*) FROM appt_bookings WHERE user_id=? AND status='pending' AND lower(email)=?", (uid, em)).fetchone()[0] >= APB_PENDING_MAIL:
        c.commit()
        return apb_msg(c, p, lg, tr("Please confirm your open bookings first", lg=lg), [tr("We sent you an e-mail for each booking. Please confirm or wait 30 minutes.", lg=lg)], code=429)
    if c.execute("SELECT COUNT(*) FROM appt_bookings WHERE user_id=? AND status='pending'", (uid,)).fetchone()[0] >= APB_PENDING_PAGE:
        c.commit()
        return pub_limited(lg)
    if not apb_slot_free(c, p, t, s):
        c.commit()
        return apb_gone_slot(c, p, t, s, lg)
    from ..admin.hosting import mail_budget
    if not mail_budget(c, None, em) or not apb_mail_quota(c, uid):  # 2.148.1 D (#2485): own quota, not the owner's; G: refused address first
        c.commit()
        return apb_msg(c, p, lg, tr("No more e-mails to this address today", lg=lg), [tr("Please try again tomorrow.", lg=lg)], code=429)
    tok = secrets.token_urlsafe(32)  # 256 bits; only the hash is stored
    st, en = apb_utc(s), apb_utc(s + timedelta(minutes=t["duration_min"]))
    bid = insert_id(c, """INSERT INTO appt_bookings(user_id, type_id, start, "end", name, email, phone, message, lang, status, confirm_hash, ip, created_at)
                          VALUES(?,?,?,?,?,?,?,?,?,'pending',?,?,?)""",
                    (uid, t["id"], iso(st), iso(en), vals["name"], vals["email"], vals["phone"], vals["message"], lg, _token_hash(tok), ip, iso(now_utc())))
    r = c.execute("SELECT * FROM appt_bookings WHERE id=?", (bid,)).fetchone()
    mail = apb_mail_confirm(c, p, t, r, tok)
    bump(c)
    c.commit()
    print("apptbook pending", bid, flush=True)
    threading.Thread(target=apb_mail_bg, args=mail, daemon=True).start()
    return apb_msg(c, p, lg, tr("Almost done: please check your e-mail", lg=lg), [tr("We sent you a link. Your booking counts once you confirm it there (within 30 minutes).", lg=lg)])


def apb_mail_quota(c, uid):
    """2.148.1 D (#2485): True and counted if the booking page of uid may send one more confirmation mail today. A quota of
    its own (APB_MAIL_DAY), apart from the owner's daily mail budget, so strangers cannot use that up."""
    day = now_utc().strftime("%Y-%m-%d")
    k = f"apb:{uid}"
    r = c.execute("SELECT n, day FROM mail_counts WHERE k=?", (k,)).fetchone()
    if r and r[1] == day and r[0] >= APB_MAIL_DAY:
        return False
    c.execute("""INSERT INTO mail_counts(k,day,n) VALUES(?,?,1) ON CONFLICT(k) DO UPDATE SET
                 n=CASE WHEN mail_counts.day=excluded.day THEN mail_counts.n+1 ELSE 1 END, day=excluded.day""", (k, day))
    return True


# confirmation and cancel links
def apb_token_row(c, token, col):
    """(booking, page) of a confirm / cancel token or (None, None); the request then reads as the page's owner."""
    if hit_limit("apbv:" + rate_ip(), APB_VIEW_RATE) or not PUB_TOKEN_OK(token):
        return None, None
    with system_ctx(c):  # resolve the token (one row) across people, then read with exactly its owner's context
        r = c.execute(f"SELECT * FROM appt_bookings WHERE {col}=?", (_token_hash(token),)).fetchone()
    if not r or not apb_live(c, r["user_id"]):
        return None, None
    p = c.execute("SELECT * FROM appt_pages WHERE user_id=?", (r["user_id"],)).fetchone()
    if not p:
        return None, None
    apb_bind(r["user_id"])
    return r, p


def PUB_TOKEN_OK(token):  # noqa: N802
    from ..lists.public import PUB_TOKEN_RE
    return bool(PUB_TOKEN_RE.fullmatch(token or ""))


def apb_bad_token():
    from ..lists.public import pub_gone, pub_limited
    from ..notify.alerts import aa_count
    ip = rate_ip()
    bad = [("pubbad:" + ip, APB_BAD_LIMIT)]
    if _rate_blocked(bad):
        return pub_limited(apb_lang_hdr())
    _rate_fail(bad)
    aa_count("security", "publink", ip)
    return pub_gone()


def apb_tok_key(c, r, what):
    from ..accounts.login import auth_key
    return hmac.new(auth_key(c), f"apb{what}:{r['id']}:{r['created_at']}".encode(), hashlib.sha256).hexdigest()


def apb_summary(c, p, r, lg):
    e = html.escape
    t = c.execute("SELECT name, location FROM appt_types WHERE id=?", (r["type_id"],)).fetchone() if r["type_id"] else None
    s, en = parse_iso(r["start"]), parse_iso(r["end"])
    return (f'<p class="apb-when"><b>{e(t["name"] if t else "")}</b><br>{e(apb_when(p, s, en, lg))}</p>'
            + (f'<p class="sub">{e(t["location"])}</p>' if t and t["location"] else "") + f'<p class="sub">{e(r["name"])} · {e(r["email"])}</p>')


def apb_expired(r):
    return r["status"] == "pending" and parse_iso(r["created_at"]) < now_utc() - timedelta(minutes=APB_HOLD_MIN)


@app.get("/s/b/c/<token>")
def apb_confirm_page(token):
    c = db()
    r, p = apb_token_row(c, token, "confirm_hash")
    if not r or not p["enabled"]:
        return apb_bad_token()
    lg = r["lang"] if r["lang"] in LANGS else apb_lang(c, r["user_id"])
    e = html.escape
    if r["status"] == "confirmed":
        return apb_html(c, p, tr("Booking confirmed", lg=lg), apb_head(c, p, lg) + f'<div class="msg"><h1>{e(tr("Booking confirmed", lg=lg))}</h1></div>'
                        + apb_summary(c, p, r, lg) + f'<p class="sub">{e(tr("You will get an e-mail with the details and a link to cancel.", lg=lg))}</p>', lg)
    if r["status"] != "pending" or apb_expired(r):
        return apb_msg(c, p, lg, tr("This link has expired", lg=lg), [tr("Unconfirmed bookings are released after 30 minutes. Please book again.", lg=lg)],
                       f'{APB_PREFIX}{p["slug"]}', 410)
    form = (f'<form method="post" action="{APB_PREFIX}c/{e(token)}" class="fform"><input type="hidden" name="f" value="{apb_tok_key(c, r, "c")}">'
            f'<button type="submit">{e(tr("Confirm the booking", lg=lg))}</button></form>')
    return apb_html(c, p, tr("Confirm the booking", lg=lg), apb_head(c, p, lg, tr("Confirm the booking", lg=lg)) + apb_summary(c, p, r, lg) + form, lg)


@app.post("/s/b/c/<token>")
def apb_confirm(token):
    """The customer confirms: event + contact + lead, the mail with the cancel link, a push to the person."""
    from ..lists.public import pub_limited
    c = db()
    r, p = apb_token_row(c, token, "confirm_hash")
    if not r or not p["enabled"]:
        return apb_bad_token()
    lg = r["lang"] if r["lang"] in LANGS else apb_lang(c, r["user_id"])
    if request.headers.get("Sec-Fetch-Site", "") == "cross-site" or not hmac.compare_digest(request.form.get("f") or "", apb_tok_key(c, r, "c")):
        return apb_denied(lg)
    if hit_limit("apbp:" + rate_ip(), APB_POST_RATE):
        return pub_limited(lg)
    uid = r["user_id"]
    write_lock(c, f"appt:{uid}")
    r = c.execute("SELECT * FROM appt_bookings WHERE id=?", (r["id"],)).fetchone()
    if r["status"] != "pending" or apb_expired(r):
        c.rollback()
        return redirect(APB_PREFIX + "c/" + token, 303)
    t = c.execute("SELECT * FROM appt_types WHERE id=? AND user_id=?", (r["type_id"], uid)).fetchone() if r["type_id"] else None
    s = parse_iso(r["start"])
    tp = dict(t) if t else None
    if tp:  # the same check as when booking, without the notice / days ahead (they counted when the customer chose the time)
        tp.update(notice_h=0, days_ahead=max(tp["days_ahead"], (s.date() - now_utc().date()).days + 1))
    if not tp or not tp["active"] or t["deleted_at"] or not apb_slot_free(c, p, tp, s.astimezone(apb_zone(p)), skip=r["id"]):
        c.execute("UPDATE appt_bookings SET status='expired', confirm_hash=NULL WHERE id=?", (r["id"],))
        c.commit()
        return apb_msg(c, p, lg, tr("This time is no longer free", lg=lg), [tr("Please choose another time.", lg=lg)], f'{APB_PREFIX}{p["slug"]}', 409)
    eid, cid, did = apb_make(c, p, t, r)
    ctok = secrets.token_urlsafe(32)
    c.execute("UPDATE appt_bookings SET status='confirmed', confirmed_at=?, cancel_hash=?, event_id=?, contact_id=?, deal_id=?, ip='' WHERE id=?",
              (iso(now_utc()), _token_hash(ctok), eid, cid, did, r["id"]))
    r = c.execute("SELECT * FROM appt_bookings WHERE id=?", (r["id"],)).fetchone()
    mail = apb_mail_confirmed(c, p, t, r, ctok)
    apb_push(c, r, "new")
    bump(c)
    c.commit()
    print("apptbook confirmed", r["id"], flush=True)
    threading.Thread(target=apb_mail_bg, args=mail, daemon=True).start()
    return redirect(APB_PREFIX + "c/" + token, 303)


def apb_make(c, p, t, r):
    """The event (page calendar, else the person's first own calendar), the contact (module Contacts on) and the lead (an
    office area chosen) of a confirmed booking -> (event id, contact id | None, deal id | None)."""
    from ..events.model import default_cal, ev_store
    uid = r["user_id"]
    olg = usettings(c, uid).get("lang") or "en"
    cid = p["cal_id"] if p["cal_id"] and apb_cal_ok(c, uid, p["cal_id"]) else default_cal(c, uid)
    zone = apb_zone(p)
    s, e = parse_iso(r["start"]).astimezone(zone), parse_iso(r["end"]).astimezone(zone)
    desc = "\n".join(x for x in (tr("Booked through the booking page", lg=olg), "", f'{tr("Name", lg=olg)}: {r["name"]}',
                                 f'{tr("E-mail", lg=olg)}: {r["email"]}', f'{tr("Phone", lg=olg)}: {r["phone"]}' if r["phone"] else "",
                                 "", r["message"]) if x is not None).strip()
    f = {"title": f'{t["name"]}: {r["name"]}'[:500], "location": t["location"], "description": desc[:20000], "all_day": 0,
         "start": s.strftime("%Y-%m-%dT%H:%M"), "end": e.strftime("%Y-%m-%dT%H:%M"),
         "tz": "" if getattr(zone, "key", "") == getattr(TZ, "key", "") else getattr(zone, "key", "")}
    att = [{"user_id": None, "contact_id": None, "email": r["email"], "name": r["name"], "partstat": "accepted", "role": "req"}]
    eid = ev_store(c, uid, cid, f, attendees=att)
    ct = None
    try:
        from ..contacts.model import contact_by_email, contact_fields, contact_store, contacts_on, default_book
        if contacts_on(c, uid):
            ct = contact_by_email(c, uid, r["email"])
            if not ct:
                cf = contact_fields({"fn": r["name"], "emails": [r["email"]], "phones": [r["phone"]] if r["phone"] else [],
                                     "note": tr("Booked through the booking page", lg=olg)})
                with c.savepoint():
                    ct = contact_store(c, uid, default_book(c, uid), cf)
    except (BadInput, Denied) as x:  # a full address book: the booking counts without the contact
        print("apptbook contact skipped:", type(x).__name__, flush=True)
        ct = None
    deal = None
    if p["office_org_id"]:
        try:
            from ..office.leads import lead_from_booking
            with c.savepoint():
                deal = lead_from_booking(c, p["office_org_id"], uid, r["name"], email=r["email"], phone=r["phone"], note=r["message"],
                                         source="booking", follow_up=s.date().isoformat())
        except Exception as x:  # noqa: BLE001  (a lead problem never stops the booking; part A returns None when not allowed)
            print("apptbook lead skipped:", type(x).__name__, flush=True)
            deal = None
    return eid, ct, deal


@app.get("/s/b/x/<token>")
def apb_cancel_page(token):
    c = db()
    r, p = apb_token_row(c, token, "cancel_hash")
    if not r:
        return apb_bad_token()
    lg = r["lang"] if r["lang"] in LANGS else apb_lang(c, r["user_id"])
    e = html.escape
    if r["status"] == "cancelled":
        return apb_msg(c, p, lg, tr("Appointment cancelled", lg=lg), [tr("Thank you. You can close this page.", lg=lg)])
    if r["status"] != "confirmed" or parse_iso(r["start"]) <= now_utc():
        return apb_msg(c, p, lg, tr("This appointment can no longer be cancelled here", lg=lg), [tr("Please reply to the confirmation e-mail.", lg=lg)], code=410)
    form = (f'<form method="post" action="{APB_PREFIX}x/{e(token)}" class="fform"><input type="hidden" name="f" value="{apb_tok_key(c, r, "x")}">'
            f'<label for="apb-why">{e(tr("Reason (optional)", lg=lg))}</label><textarea id="apb-why" name="reason" rows="3" maxlength="{MSG_MAX}"></textarea>'
            f'<button type="submit">{e(tr("Cancel the appointment", lg=lg))}</button></form>')
    return apb_html(c, p, tr("Cancel the appointment", lg=lg), apb_head(c, p, lg, tr("Cancel the appointment", lg=lg)) + apb_summary(c, p, r, lg) + form, lg)


@app.post("/s/b/x/<token>")
def apb_cancel_guest(token):
    from ..lists.public import pub_limited
    c = db()
    r, p = apb_token_row(c, token, "cancel_hash")
    if not r:
        return apb_bad_token()
    lg = r["lang"] if r["lang"] in LANGS else apb_lang(c, r["user_id"])
    if request.headers.get("Sec-Fetch-Site", "") == "cross-site" or not hmac.compare_digest(request.form.get("f") or "", apb_tok_key(c, r, "x")):
        return apb_denied(lg)
    if hit_limit("apbp:" + rate_ip(), APB_POST_RATE):
        return pub_limited(lg)
    write_lock(c, f"appt:{r['user_id']}")
    cur = c.execute("SELECT * FROM appt_bookings WHERE id=?", (r["id"],)).fetchone()
    if cur["status"] != "confirmed" or parse_iso(cur["start"]) <= now_utc():
        c.rollback()
        return apb_msg(c, p, lg, tr("This appointment can no longer be cancelled here", lg=lg), [tr("Please reply to the confirmation e-mail.", lg=lg)], code=410)
    apb_cancel(c, cur, "guest", apb_clean(request.form.get("reason"), MSG_MAX))
    c.commit()
    print("apptbook cancelled by guest", r["id"], flush=True)
    return apb_msg(c, p, lg, tr("Appointment cancelled", lg=lg), [tr("Thank you. You can close this page.", lg=lg)])


# ---------------------------------------------------------------- mails and the push
def apb_mail_bg(to, subject, text, html_body, reply_to, from_name):
    from ..integrations.mail import mail_send
    try:
        mail_send(to, subject, text, html_body, from_name=from_name, reply_to=reply_to or None)
    except Exception as ex:  # noqa: BLE001  (nobody waits for this; the customer can book again)
        print("apptbook mail failed:", type(ex).__name__, flush=True)


def apb_mail_html(lines, url=None, button=None, foot=""):
    e = html.escape
    return ('<div style="font-family:system-ui,sans-serif;max-width:34rem;line-height:1.5">'
            + "".join(f"<p>{e(x).replace(chr(10), '<br>')}</p>" for x in lines if x)
            + (f'<p><a href="{e(url)}" style="display:inline-block;background:#6d4ad8;color:#fff;padding:.6rem 1rem;border-radius:.5rem;'
               f'text-decoration:none">{e(button)}</a></p>' if url else "")
            + (f'<p style="color:#777;font-size:.85rem">{e(foot)}</p>' if foot else "") + "</div>")


def apb_mail_meta(c, uid):
    """(reply-to = the person's e-mail, sender name = the person's name)."""
    with system_ctx(c):  # the owner's own address (the public request reads as the owner, users is instance structure)
        u = c.execute("SELECT email FROM users WHERE id=?", (uid,)).fetchone()
    return (u[0] or "") if u else "", apb_owner_name(c, uid) or APP_NAME


def apb_mail_confirm(c, p, t, r, tok):
    lg = r["lang"] or "en"
    url = f"{PUBLIC_URL.rstrip('/')}{APB_PREFIX}c/{tok}"
    when = apb_when(p, parse_iso(r["start"]), parse_iso(r["end"]), lg)
    lines = [tr("Hello {0},", r["name"], lg=lg), tr("please confirm your booking: {0}, {1}.", t["name"], when, lg=lg),
             tr("Without your confirmation the time is released after 30 minutes.", lg=lg)]
    foot = tr("If you did not book this, you can ignore this mail.", lg=lg)
    rt, fn = apb_mail_meta(c, r["user_id"])
    return (r["email"], tr("Please confirm your booking", lg=lg), "\n\n".join(lines) + f"\n\n{url}\n\n{foot}",
            apb_mail_html(lines, url, tr("Confirm the booking", lg=lg), foot), rt, fn)


def apb_mail_confirmed(c, p, t, r, ctok):
    lg = r["lang"] or "en"
    url = f"{PUBLIC_URL.rstrip('/')}{APB_PREFIX}x/{ctok}"
    when = apb_when(p, parse_iso(r["start"]), parse_iso(r["end"]), lg)
    lines = [tr("Hello {0},", r["name"], lg=lg), tr("your appointment is booked: {0}, {1}.", t["name"], when, lg=lg),
             (tr("Location: {0}", t["location"], lg=lg) if t["location"] else ""), tr("If you cannot come, please cancel it with this link.", lg=lg)]
    rt, fn = apb_mail_meta(c, r["user_id"])
    return (r["email"], tr("Your appointment is booked", lg=lg), "\n\n".join(x for x in lines if x) + f"\n\n{url}",
            apb_mail_html(lines, url, tr("Cancel the appointment", lg=lg)), rt, fn)


def apb_mail_cancelled(c, r, reason):
    p = apb_page_row(c, r["user_id"])
    lg = r["lang"] or "en"
    t = c.execute("SELECT name FROM appt_types WHERE id=?", (r["type_id"],)).fetchone() if r["type_id"] else None
    when = apb_when(p, parse_iso(r["start"]), parse_iso(r["end"]), lg)
    lines = [tr("Hello {0},", r["name"], lg=lg), tr("unfortunately your appointment was cancelled: {0}, {1}.", t[0] if t else "", when, lg=lg),
             (tr("Reason: {0}", reason, lg=lg) if reason else ""), tr("You can book a new time on the booking page.", lg=lg)]
    url = apb_url(p["slug"]) if p and p["enabled"] else None
    rt, fn = apb_mail_meta(c, r["user_id"])
    return (r["email"], tr("Your appointment was cancelled", lg=lg), "\n\n".join(x for x in lines if x) + (f"\n\n{url}" if url else ""),
            apb_mail_html(lines, url, tr("Book an appointment", lg=lg) if url else None), rt, fn)


def apb_push(c, r, what):
    """Push to the person (the switch "assign" like an event invitation): a new confirmed booking / a cancel by the customer."""
    from ..collab.news import notif_ok
    from ..notify.push import push_prio
    uid = r["user_id"]
    s = usettings(c, uid)
    if not notif_ok(c, uid, s, "assign", "push"):
        return
    lg = s.get("lang") or "en"
    p = apb_page_row(c, uid)
    t = c.execute("SELECT name FROM appt_types WHERE id=?", (r["type_id"],)).fetchone() if r["type_id"] else None
    title = tr("New booking", lg=lg) if what == "new" else tr("Booking cancelled by the customer", lg=lg)
    msg = f'{r["name"]} · {t[0] if t else ""} · {apb_when(p, parse_iso(r["start"]), parse_iso(r["end"]), lg)}'
    click = f"{PUBLIC_URL}/#ev/{r['event_id']}" if r["event_id"] and what == "new" else f"{PUBLIC_URL}/#calendar"
    g.setdefault("pushes", []).append((uid, title, msg, click, push_prio(s)))
