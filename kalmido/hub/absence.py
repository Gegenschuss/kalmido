"""2.50.0 (#1195): absences -- vacation, sick leave, days off, other -- per person, seen by the team as "absent" only.

An absence belongs to one person and one area: the organisation it was entered in (hub_absences.org_id), or the person's
own hidden area (pb_personal, people without an organisation). Row-level security keeps every row inside its organisation;
the app adds the rest:
- everyone enters their own absences; an organisation's admins also those of its members (no approval, just entering;
  2.125.0 A (#2117): an organisation's admins may ask for approvals of vacation, hub/leave.py -- only approved absences
  count as "away" for the team, the workload, the day plan, the booking page and agents);
- the team sees "absent" and the period; the kind (above all sick leave) and the note only the person and the admins of
  the organisation. Agents never see the kind (health data), at most "absent" (GET /api/v1/absences);
- German public holidays per state, computed here (Easter formula, no library, no service): one state per organisation
  (its admins), people without an organisation set their own (their personal area);
- workload (capacity 0 on absent workdays), the day plan (a hint instead of a proposal) and assigning (a warning, never a
  block) read abs_days() / abs_check().
Deleting sets deleted_at (Undo restores)."""
import re
from datetime import date, timedelta

from flask import g, jsonify, request

from ..core.config import app
from ..core.pg import insert_id, system_ctx
from ..core.i18n import tr
from ..core.db import body, bump, db, iso, local_now, now_utc, usettings
from ..core.access import Denied
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields
from ..accounts.session import me, user_public
from ..core.errors import BadInput
from ..api.common import v1_args, v1_view

ABS_KINDS = ("vacation", "sick", "off", "other")
ABS_HALF = ("", "am", "pm")
ABS_NOTE_MAX = 500
ABS_SPAN_MAX = 366  # days of one absence
ABS_RANGE_MAX = 370  # days of one view
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# ---------------------------------------------------------------- German public holidays
ABS_STATES = {"BW": "Baden-Württemberg", "BY": "Bayern", "BE": "Berlin", "BB": "Brandenburg", "HB": "Bremen",
              "HH": "Hamburg", "HE": "Hessen", "MV": "Mecklenburg-Vorpommern", "NI": "Niedersachsen",
              "NW": "Nordrhein-Westfalen", "RP": "Rheinland-Pfalz", "SL": "Saarland", "SN": "Sachsen",
              "ST": "Sachsen-Anhalt", "SH": "Schleswig-Holstein", "TH": "Thüringen",
              "AT": "Österreich"}  # 2.155.0 B (#2076): Austria (nationwide holidays only)
# names stay German (they are German holidays); regional ones only where they hold in the whole state
_FIXED = ((1, 1, "Neujahr", None), (1, 6, "Heilige Drei Könige", "BW BY ST"), (3, 8, "Internationaler Frauentag", "BE MV"),
          (5, 1, "Tag der Arbeit", None), (8, 15, "Mariä Himmelfahrt", "SL"), (9, 20, "Weltkindertag", "TH"),
          (10, 3, "Tag der Deutschen Einheit", None), (10, 31, "Reformationstag", "BB HB HH MV NI SN ST SH TH"),
          (11, 1, "Allerheiligen", "BW BY NW RP SL"), (12, 25, "1. Weihnachtstag", None), (12, 26, "2. Weihnachtstag", None))
_EASTER = ((-2, "Karfreitag", None), (0, "Ostersonntag", "BB"), (1, "Ostermontag", None), (39, "Christi Himmelfahrt", None),
           (49, "Pfingstsonntag", "BB"), (50, "Pfingstmontag", None), (60, "Fronleichnam", "BW BY HE NW RP SL"))
# 2.155.0 B (#2076): Austria's nationwide public holidays (Good Friday is none since 2019)
_AT_FIXED = ((1, 1, "Neujahr"), (1, 6, "Heilige Drei Könige"), (5, 1, "Staatsfeiertag"), (8, 15, "Mariä Himmelfahrt"),
             (10, 26, "Nationalfeiertag"), (11, 1, "Allerheiligen"), (12, 8, "Mariä Empfängnis"), (12, 25, "Christtag"),
             (12, 26, "Stefanitag"))
_AT_EASTER = ((1, "Ostermontag"), (39, "Christi Himmelfahrt"), (50, "Pfingstmontag"), (60, "Fronleichnam"))


def abs_easter(y):
    """Easter Sunday of year y (Gregorian; the anonymous algorithm)."""
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g_ = (b - f + 1) // 3
    h = (19 * a + b - d - g_ + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    return date(y, month, (h + l_ - 7 * m + 114) % 31 + 1)


def abs_holidays_year(y, state):
    """{ISO day: name} of the public holidays of year y in state (one of ABS_STATES; '' = none)."""
    if state not in ABS_STATES:
        return {}
    if state == "AT":  # 2.155.0 B (#2076)
        e = abs_easter(y)
        out = {date(y, mo, d).isoformat(): name for mo, d, name in _AT_FIXED}
        out.update({(e + timedelta(days=off)).isoformat(): name for off, name in _AT_EASTER})
        return out
    out = {}
    for mo, d, name, only in _FIXED:
        if only is None or state in only.split():
            if (mo, d) == (3, 8) and (y < 2019 or (state == "MV" and y < 2023)):
                continue
            if (mo, d) == (9, 20) and y < 2019:
                continue
            if (mo, d) == (10, 31) and state in ("HB", "HH", "NI", "SH") and y < 2018:
                continue
            out[date(y, mo, d).isoformat()] = name
    e = abs_easter(y)
    for off, name, only in _EASTER:
        if only is None or state in only.split():
            out[(e + timedelta(days=off)).isoformat()] = name
    if state == "SN":  # Buss- und Bettag: the Wednesday before 23 November
        d = date(y, 11, 22)
        out[(d - timedelta(days=(d.weekday() - 2) % 7)).isoformat()] = "Buß- und Bettag"
    return out


def abs_holidays(state, first, last):
    """{ISO day: name} within [first, last] (dates)."""
    out = {}
    for y in range(first.year, last.year + 1):
        out.update({k: v for k, v in abs_holidays_year(y, state).items() if first.isoformat() <= k <= last.isoformat()})
    return out


def abs_state(c, oid):
    if not oid:
        return ""
    with system_ctx(c):  # the organisation's own setting (also read for its members' workload)
        r = c.execute("SELECT hub_holiday_state FROM orgs WHERE id=?", (oid,)).fetchone()
    return (r[0] or "") if r else ""


# ---------------------------------------------------------------- area + rights
def abs_org(c, uid, want=None, create=True):
    """The area (orgs.id) uid looks at / enters into: ?org= (a membership, 404 otherwise), else the area of the workspace
    switch ("org:<id>" that organisation, "private" the personal area), else the first organisation; without any
    organisation the personal area (pb_personal)."""
    from ..accounts.orgs import user_orgs
    from ..office.model import pb_personal
    from ..accounts.orgroles import user_orgs_full
    orgs = [o for o in user_orgs(c, uid) if o in user_orgs_full(c, uid)]  # 2.143.0 A (#2151): not guests / accounting
    if want is not None:
        if want in orgs or want == pb_personal(c, uid, create=False):
            return want
        raise Denied(404)
    ws = (usettings(c, uid).get("workspace") or "").strip()
    m = re.fullmatch(r"org:(\d{1,9})", ws)
    if m and int(m.group(1)) in orgs:
        return int(m.group(1))
    if ws == "private":  # 2.96.0 D (#1941): the switch on "Private" is the personal area, not the first organisation
        return pb_personal(c, uid, create=create)
    return orgs[0] if orgs else pb_personal(c, uid, create=create)


def abs_admin(c, uid, oid):
    """True when uid runs area oid: an organisation's admin, or the owner of a personal area."""
    from ..accounts.orgs import is_org_admin
    from ..office.model import pb_personal
    return is_org_admin(c, uid, oid) or oid == pb_personal(c, uid, create=False)


def abs_people(c, oid):
    """The people of area oid (no agents, no kids): the organisation's members, or the owner of a personal area."""
    with system_ctx(c):  # membership structure of an area the caller belongs to (checked by abs_org)
        own = c.execute("SELECT personal_of FROM orgs WHERE id=?", (oid,)).fetchone()
        if own and own[0]:
            q, a = "SELECT * FROM users WHERE id=?", (own[0],)
        else:
            q, a = "SELECT u.* FROM users u JOIN org_members m ON m.user_id=u.id WHERE m.org_id=?", (oid,)
        return c.execute(f"SELECT * FROM ({q}) x WHERE disabled=0 AND kid=0 AND COALESCE(kind,'user')!='agent' "
                         "ORDER BY lower(display_name), id", a).fetchall()


def _gate():
    u = g.user
    if u is None:
        raise Denied(401)
    if (u["kind"] or "user") == "agent":
        raise Denied(403, tr("Agents cannot use this endpoint"))
    if u["kid"]:
        raise Denied(403)
    return db(), u["id"]


def _date(v, name):
    if isinstance(v, str) and DATE_RE.match(v.strip()):
        try:
            return date.fromisoformat(v.strip())
        except ValueError:
            pass
    raise BadInput(tr("Invalid value: {0}", name))


def abs_public(r, full, c=None):
    """An absence as JSON: the kind and the note only when full (the person, the area's admins; decrypted, orgcrypt)."""
    if full and c is not None:
        r = oc_dec_fields(c, r["org_id"], "hub_absences", r)
    d = {"id": r["id"], "user_id": r["user_id"], "start_date": r["start_date"], "end_date": r["end_date"],
         "half_day": r["half_day"] or "", "status": r["status"] or "approved"}  # 2.125.0 A (#2117)
    if full:
        d.update(kind=r["kind"], note=r["note"] or "", decision_note=r["decision_note"] or "")
    return d


def abs_clean(b, cur=None):
    cur = cur or {}
    out = {}
    if "kind" in b or not cur:
        k = b.get("kind") or "vacation"
        if k not in ABS_KINDS:
            raise BadInput(tr("Invalid value: {0}", "kind"))
        out["kind"] = k
    if "start_date" in b or not cur:
        out["start_date"] = _date(b.get("start_date"), "start_date").isoformat()
    if "end_date" in b or not cur:
        v = b.get("end_date") or out.get("start_date") or cur.get("start_date")
        out["end_date"] = _date(v, "end_date").isoformat()
    if "half_day" in b:
        h = b.get("half_day") or ""
        if h is True:
            h = "am"
        if h not in ABS_HALF:
            raise BadInput(tr("Invalid value: {0}", "half_day"))
        out["half_day"] = h
    if "note" in b:
        v = b.get("note") or ""
        if not isinstance(v, str):
            raise BadInput(tr("Invalid value: {0}", "note"))
        out["note"] = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", v).strip()[:ABS_NOTE_MAX]
    st, en = out.get("start_date", cur.get("start_date")), out.get("end_date", cur.get("end_date"))
    if en < st:
        raise BadInput(tr("The end is before the start"))
    if (date.fromisoformat(en) - date.fromisoformat(st)).days >= ABS_SPAN_MAX:
        raise BadInput(tr("An absence can last one year at most"))
    if out.get("half_day", cur.get("half_day")) and st != en:
        raise BadInput(tr("A half day is a single day"))
    return out


def _row(c, aid):
    r = c.execute("SELECT * FROM hub_absences WHERE id=?", (aid,)).fetchone()  # row-level security: only my areas
    if not r:
        raise Denied(404)
    return r


def _may_edit(c, uid, r):
    return r["user_id"] == uid or abs_admin(c, uid, r["org_id"])


# ---------------------------------------------------------------- reading for others (workload, day plan, assigning)
def abs_days(c, user_ids, first, last, oid=None):
    """{user id: {ISO day: 1 | 0.5}} of the absent days within [first, last] (dates) of the given people -- the rows the
    caller may read (row-level security), only of area oid when given. Kinds are not part of it."""
    if not user_ids:
        return {}
    q = ",".join("?" * len(user_ids))
    sql = (f"SELECT user_id, start_date, end_date, half_day FROM hub_absences WHERE deleted_at IS NULL AND user_id IN ({q}) "
           "AND start_date<=? AND end_date>=? AND status='approved'")  # 2.125.0 A (#2117): a request is not "away" yet
    args = [*user_ids, last.isoformat(), first.isoformat()]
    if oid is not None:
        sql += " AND org_id=?"
        args.append(oid)
    out = {}
    for r in c.execute(sql, args).fetchall():
        d, e = max(first, date.fromisoformat(r["start_date"])), min(last, date.fromisoformat(r["end_date"]))
        cell = out.setdefault(r["user_id"], {})
        while d <= e:
            k = d.isoformat()
            cell[k] = max(cell.get(k, 0), 0.5 if r["half_day"] else 1)
            d += timedelta(days=1)
    return out


def abs_capacity_factor(days, holidays, a, b, wd=(0, 1, 2, 3, 4)):
    """The share of the workdays (wd; 2.125.0 A (#2118): the person's, default Monday..Friday) of the week [a, b] the
    person is there (0..1)."""
    n = len(wd)
    gone = 0.0
    d = a
    while d <= b:
        if d.weekday() in wd:
            k = d.isoformat()
            gone += 1 if k in holidays else days.get(k, 0)
        d += timedelta(days=1)
    return max(0.0, (n - min(n, gone)) / n) if n else 0.0


def abs_check(c, uid, day):
    """{absent, half_day, until} of person uid on day (date) as far as the caller may read it, or None."""
    from ..accounts.orgs import may_see
    if not may_see(c, me(), uid):
        return None
    r = c.execute("SELECT end_date, half_day FROM hub_absences WHERE deleted_at IS NULL AND user_id=? AND start_date<=? AND end_date>=? "
                  "AND status='approved' ORDER BY half_day, end_date DESC LIMIT 1", (uid, day.isoformat(), day.isoformat())).fetchone()
    return {"absent": True, "half_day": r["half_day"] or "", "until": r["end_date"]} if r else None


def abs_mine_today(c, uid, day):
    """For the day plan: {kind, half_day, holiday} when uid is absent on day / it is a holiday of their area, else None."""
    r = c.execute("SELECT org_id, kind, half_day FROM hub_absences WHERE deleted_at IS NULL AND user_id=? AND start_date<=? AND end_date>=? "
                  "AND status='approved' ORDER BY half_day LIMIT 1", (uid, day.isoformat(), day.isoformat())).fetchone()
    hol = ""
    try:
        hol = abs_holidays_year(day.year, abs_state(c, abs_org(c, uid, create=False))).get(day.isoformat(), "")
    except (Denied, BadInput):
        pass
    if not r and not hol:
        return None
    if r:
        r = oc_dec_fields(c, r["org_id"], "hub_absences", r)
    return {"kind": r["kind"] if r else "", "half_day": (r["half_day"] or "") if r else "", "holiday": hol}


# ---------------------------------------------------------------- routes
@app.get("/api/team/absences")
def abs_list():
    """?start=&end= (ISO days, default this month) &org=<id>: the people of the area, their absences (the kind only for
    oneself / the area's admins), the public holidays of the area's state."""
    c, uid = _gate()
    a = request.args
    try:
        want = int(a["org"]) if a.get("org") else None
    except ValueError:
        raise BadInput(tr("Invalid data")) from None
    oid = abs_org(c, uid, want)
    today = local_now().date()
    first = _date(a["start"], "start") if a.get("start") else today.replace(day=1)
    last = _date(a["end"], "end") if a.get("end") else (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    if last < first or (last - first).days > ABS_RANGE_MAX:
        raise BadInput(tr("Invalid value: {0}", "end"))
    people = abs_people(c, oid)
    pids = {p["id"] for p in people}  # former members' rows stay out (tenancy.py CHECKS "absence" counts them)
    adm = abs_admin(c, uid, oid)
    rows = c.execute("SELECT * FROM hub_absences WHERE org_id=? AND deleted_at IS NULL AND start_date<=? AND end_date>=? "
                     "ORDER BY start_date, id", (oid, last.isoformat(), first.isoformat())).fetchall()
    st = abs_state(c, oid)
    from ..accounts.orgs import user_orgs
    from ..office.model import pb_personal
    from ..accounts.orgroles import user_orgs_full
    mine = [o for o in user_orgs(c, uid) if o in user_orgs_full(c, uid)]  # 2.143.0 A (#2151)
    with_org = [{"id": r[0], "name": r[1]} for r in c.execute(
        "SELECT id, name FROM orgs WHERE personal_of IS NULL ORDER BY lower(name), id") if r[0] in mine]
    # 2.96.0 D (#1941): the personal area (when there is one) is offered next to the organisations
    return jsonify(org_id=oid, orgs=with_org, personal=pb_personal(c, uid, create=False), admin=adm, state=st, states=ABS_STATES, today=today.isoformat(),
                   start=first.isoformat(), end=last.isoformat(),
                   people=[{**user_public(p), "own": p["id"] == uid} for p in people],
                   items=[{**abs_public(r, adm or r["user_id"] == uid, c), "can_edit": adm or r["user_id"] == uid}
                          for r in rows if r["user_id"] in pids
                          and (r["status"] == "approved" or adm or r["user_id"] == uid)],  # 2.125.0 A (#2117): requests only for them
                   holidays=[{"date": k, "name": v} for k, v in sorted(abs_holidays(st, first, last).items())])


@app.post("/api/team/absences")
def abs_create():
    """{user_id? (default oneself; others: the area's admins), kind, start_date, end_date?, half_day? ('' | am | pm),
    note?, org?}"""
    c, uid = _gate()
    b = body()
    try:
        want = int(b["org"]) if b.get("org") else None
        who = int(b.get("user_id") or uid)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid data")) from None
    oid = abs_org(c, uid, want)
    if who != uid:
        if not abs_admin(c, uid, oid):
            raise Denied(403, tr("Only admins of the organisation can enter absences for other people"))
        if who not in {p["id"] for p in abs_people(c, oid)}:
            raise Denied(404, tr("unknown user"))
    v = abs_clean(b)
    e = oc_enc_fields(c, oid, "hub_absences", {"kind": v["kind"], "note": v.get("note", "")})
    from .leave import lv_requested, lv_status_new
    st = lv_status_new(c, uid, oid, who, v["kind"])  # 2.125.0 A (#2117): a member's vacation may be a request
    aid = insert_id(c, "INSERT INTO hub_absences(org_id,user_id,kind,start_date,end_date,half_day,note,created_by,created_at,status) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?)", (oid, who, e["kind"], v["start_date"], v["end_date"], v.get("half_day", ""),
                                                       e["note"], uid, iso(now_utc()), st))
    lv_requested(c, _row(c, aid))
    bump(c)
    c.commit()
    return jsonify({**abs_public(_row(c, aid), True, c), "can_edit": True}), 201


@app.patch("/api/team/absences/<int:aid>")
def abs_edit(aid):
    c, uid = _gate()
    r = _row(c, aid)
    if r["deleted_at"] or not _may_edit(c, uid, r):
        raise Denied(404 if r["deleted_at"] else 403)
    p = abs_clean(body(), dict(r))
    v = oc_enc_fields(c, r["org_id"], "hub_absences", p)
    from .leave import lv_requested, lv_status_edit
    v.update(lv_status_edit(c, uid, r, p))  # 2.125.0 A (#2117): a member's changed vacation asks again
    if v:
        c.execute(f"UPDATE hub_absences SET {', '.join(k + '=?' for k in v)} WHERE id=?", (*v.values(), aid))
        if v.get("status") == "pending" and r["status"] != "pending":
            lv_requested(c, _row(c, aid))
        bump(c)
        c.commit()
    return jsonify({**abs_public(_row(c, aid), True, c), "can_edit": True})


@app.delete("/api/team/absences/<int:aid>")
def abs_delete(aid):
    c, uid = _gate()
    r = _row(c, aid)
    if not _may_edit(c, uid, r):
        raise Denied(403)
    c.execute("UPDATE hub_absences SET deleted_at=? WHERE id=? AND deleted_at IS NULL", (iso(now_utc()), aid))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.post("/api/team/absences/<int:aid>/restore")
def abs_restore(aid):
    """Undo of a delete."""
    c, uid = _gate()
    r = _row(c, aid)
    if not _may_edit(c, uid, r):
        raise Denied(403)
    c.execute("UPDATE hub_absences SET deleted_at=NULL WHERE id=?", (aid,))
    bump(c)
    c.commit()
    return jsonify({**abs_public(_row(c, aid), True, c), "can_edit": True})


@app.put("/api/team/absences/holidays")
def abs_set_state():
    """{state: 'BY' | '' (none), org?}: the state of the area's public holidays (the area's admins)."""
    c, uid = _gate()
    b = body()
    try:
        want = int(b["org"]) if b.get("org") else None
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid data")) from None
    oid = abs_org(c, uid, want)
    if not abs_admin(c, uid, oid):
        raise Denied(403, tr("Only admins of the organisation can change this"))
    st = b.get("state") or ""
    if st and st not in ABS_STATES:
        raise BadInput(tr("Invalid value: {0}", "state"))
    with system_ctx(c):  # the organisation's own row (orgs is structure); the admin right is checked above
        c.execute("UPDATE orgs SET hub_holiday_state=? WHERE id=?", (st, oid))
    bump(c)
    c.commit()
    return jsonify(org_id=oid, state=st)


@app.get("/api/team/absences/check")
def abs_check_get():
    """?user=<id>&date=YYYY-MM-DD: is the person away that day? Only "absent", never the kind (the warning when
    assigning a task; it never blocks)."""
    c, _uid = _gate()
    a = request.args
    try:
        who = int(a.get("user") or 0)
    except ValueError:
        raise BadInput(tr("Invalid data")) from None
    day = _date(a.get("date") or "", "date")
    return jsonify(abs_check(c, who, day) or {"absent": False})


# ---------------------------------------------------------------- REST API v1 (+ MCP get_absences): "away" only
@app.get("/api/v1/absences")
@v1_view
def v1_absences():
    """Who of the organisation is away when, never the kind or the note (sick leave = health data): an agent only for its
    own workspace (agents.org_id; a private agent: 404), a person's token like the web app's area (?org=)."""
    a = v1_args(("start", "end", "org"))
    c, u = db(), g.user
    try:
        want = int(a["org"]) if a.get("org") else None
    except ValueError:
        raise BadInput(tr("Invalid data")) from None
    if (u["kind"] or "user") == "agent":
        r = c.execute("SELECT org_id FROM agents WHERE user_id=?", (u["id"],)).fetchone()
        oid = r[0] if r and r[0] else None
        if not oid or (want is not None and want != oid):
            raise Denied(404)
    else:
        if u["kid"]:
            raise Denied(403)
        oid = abs_org(c, u["id"], want, create=False)
    today = local_now().date()
    first = _date(a["start"], "start") if a.get("start") else today
    last = _date(a["end"], "end") if a.get("end") else first + timedelta(days=30)
    if last < first or (last - first).days > ABS_RANGE_MAX:
        raise BadInput(tr("Invalid value: {0}", "end"))
    if not oid:
        return jsonify(org_id=None, people=[], items=[], holidays=[])
    people = abs_people(c, oid)
    pids = {p["id"] for p in people}
    rows = c.execute("SELECT * FROM hub_absences WHERE org_id=? AND deleted_at IS NULL AND start_date<=? AND end_date>=? "
                     "AND status='approved' ORDER BY start_date, id",  # 2.125.0 A (#2117): never a request
                     (oid, last.isoformat(), first.isoformat())).fetchall()
    return jsonify(org_id=oid, people=[{"id": p["id"], "display_name": p["display_name"] or p["username"]} for p in people],
                   items=[{k: v for k, v in abs_public(r, False).items() if k not in ("id", "status")} for r in rows if r["user_id"] in pids],
                   holidays=[{"date": k, "name": v} for k, v in sorted(abs_holidays(abs_state(c, oid), first, last).items())])


def abs_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q):
    paths["/absences"] = {"get": op(
        "2.50.0 (#1195): who of your organisation is away when (vacation, sick leave, days off) -- only \"away\" and the period, "
        "never the kind or the note; an agent sees its own workspace only (a private agent: 404); plus the public holidays of the "
        "organisation's state; 2.125.0 (#2117): approved absences only, never an open or rejected vacation request", "Workload",
        ok({"type": "object", "properties": {
            "org_id": nul("integer"),
            "people": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "integer"}, "display_name": {"type": "string"}}}},
            "items": {"type": "array", "items": {"type": "object", "properties": {
                "user_id": {"type": "integer"}, "start_date": {"type": "string"}, "end_date": {"type": "string"},
                "half_day": {"type": "string", "enum": ["", "am", "pm"]}}}},
            "holidays": {"type": "array", "items": {"type": "object", "properties": {"date": {"type": "string"}, "name": {"type": "string"}}}}}})
        | errs("400", "403", "404"),
        [q("start", "First day (YYYY-MM-DD, default today)"), q("end", "Last day (default start + 30 days, at most a year)"),
         q("org", "Organisation id (people only; default: the workspace / first organisation)", {"type": "integer"})])}
