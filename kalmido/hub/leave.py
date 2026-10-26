"""2.125.0 A (#2118, #2117): working days per person and leave -- the vacation account and vacation requests.

Working days (#2118): every person has their working weekdays (setting workdays "0,1,2,3,4" = Monday..Friday, '' = the
default Monday..Friday as before). The time gaps look only at them, the workload spreads the weekly hours (capacity_h)
over them and takes the absent / holiday ones off, the vacation account counts only them. An organisation's admins set
the working days and weekly hours of its members (they are the person's own settings; people set them in Settings too).

Vacation account (#2117): per person, area (the organisation, or the personal area of a person without one) and year an
entitlement in days plus an optional carry-over from the year before (hub_leave_quota; no row = no account, nothing
changes). Taken = the approved vacation working days of the year (half days 0.5; public holidays of the area's state and
non-working days do not count), requested = the same of the open requests, rest = entitlement + carry - taken - requested.

Requests (#2117): an organisation whose admins switch on "vacation needs approval" (orgs.hub_leave_approval, default off =
as before) turns a vacation a member (not an admin) enters for themselves into a request (hub_absences.status 'pending').
The person and the admins see it marked "requested"; the team, the workload, the day plan, the booking page and agents
count only approved absences. The admins approve or reject it (with an optional note); the admins get a News item + push
about a new request, the person about the decision -- the row "Vacation requests" of the notification settings switches
both off. Other kinds (sick leave, day off, other) and personal areas never need an approval."""
from datetime import date, timedelta

from flask import g, jsonify, request

from ..core.config import app, PUBLIC_URL
from ..core.i18n import tr
from ..core.db import body, bump, iso, local_now, now_utc, usettings, uset
from ..core.access import Denied
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields
from ..core.errors import BadInput
from .absence import _gate, _row, abs_admin, abs_holidays, abs_org, abs_people, abs_public, abs_state
from ..core.pg import system_ctx  # 2.149.0 G (#2517): pulled up from functions

WT_DEFAULT = (0, 1, 2, 3, 4)  # Monday..Friday
LV_STATES = ("approved", "pending", "rejected")
LV_DAYS_MAX = 366
LV_NOTE_MAX = 500


# ---------------------------------------------------------------- #2118: working days
def wt_parse(v):
    """'0,1,2,3,4' -> (0, 1, 2, 3, 4) (weekday numbers, Monday = 0); '' / invalid -> None."""
    try:
        d = tuple(sorted({int(x) for x in str(v or "").split(",") if x.strip()}))
    except ValueError:
        return None
    return d if d and all(0 <= x <= 6 for x in d) else None


def wt_clean(v):
    """The setting as stored ('' = the default); BadInput when invalid."""
    if isinstance(v, (list, tuple)):
        v = ",".join(str(x) for x in v)
    sv = "" if v is None else str(v).strip()
    if sv == "":
        return ""
    d = wt_parse(sv)
    if d is None:
        raise BadInput(tr("Invalid value: {0}", "workdays"))
    return "" if d == WT_DEFAULT else ",".join(str(x) for x in d)


def wt_workdays(c, uid):
    """The working weekdays of person uid (Monday = 0); without a setting Monday..Friday."""
    return wt_parse(usettings(c, uid).get("workdays")) or WT_DEFAULT


def lv_count(start, end, half, wd, hol, first=None, last=None):
    """Working days of an absence [start, end] (ISO days) within [first, last] (dates, optional): only weekdays in wd, no
    public holiday (hol: {ISO day: name}); a half day counts 0.5."""
    d, e = date.fromisoformat(start), date.fromisoformat(end)
    if first:
        d = max(d, first)
    if last:
        e = min(e, last)
    n = 0
    while d <= e:
        if d.weekday() in wd and d.isoformat() not in hol:
            n += 1
        d += timedelta(days=1)
    return n * 0.5 if half and n else float(n)


# ---------------------------------------------------------------- #2117: requests
def lv_approval_on(c, oid):
    """True when area oid is an organisation whose admins switched on approvals for vacation."""
    if not oid:
        return False
    with system_ctx(c):  # the organisation's own setting (read for its members)
        r = c.execute("SELECT personal_of, hub_leave_approval FROM orgs WHERE id=?", (oid,)).fetchone()
    return bool(r and not r["personal_of"] and r["hub_leave_approval"])


def lv_status_new(c, uid, oid, who, kind):
    """The status of a new absence: a member's own vacation in an organisation with approvals is a request."""
    if kind == "vacation" and who == uid and lv_approval_on(c, oid) and not abs_admin(c, uid, oid):
        return "pending"
    return "approved"


def lv_status_edit(c, uid, r, v):
    """{status: ...} for a change v (plain values, abs_clean) of absence r by uid: a member who changes the kind or the
    period of their vacation (or changes a rejected request) asks again; a change to another kind needs no approval; an
    admin's change keeps the status. {} = unchanged."""
    cur = r["status"] or "approved"
    if abs_admin(c, uid, r["org_id"]) or not lv_approval_on(c, r["org_id"]):
        return {}
    old = oc_dec_fields(c, r["org_id"], "hub_absences", r)["kind"]
    kind = v.get("kind", old)
    if kind != "vacation":
        return {"status": "approved"} if cur != "approved" else {}
    moved = kind != old or any(k in v and v[k] != r[k] for k in ("start_date", "end_date", "half_day"))
    return {"status": "pending"} if moved or cur == "rejected" else {}


def lv_admins(c, oid):
    with system_ctx(c):  # membership structure of the caller's own organisation (checked by abs_org)
        return [r[0] for r in c.execute("SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? "
                                        "AND m.role='admin' AND u.disabled=0 AND COALESCE(u.kind,'user')!='agent'", (oid,)).fetchall()]


def lv_notify(c, rcpts, kind, r, data):
    """News + push about a request (kind leavereq, to the admins) or a decision (leavedecide, to the person). The notes stay
    out of both (they are sealed with the absence; the person reads the decision's note in the app)."""
    from ..collab.news import KIND_ROW, news_add, notif_ok
    from ..collab.comments import collab_user, lang_of, user_names
    from ..notify.push import push_prio, push_reachable
    from ..accounts.session import me
    actor = me()
    who = user_names(c, [actor]).get(actor, "?")
    span = r["start_date"] if r["start_date"] == r["end_date"] else f"{r['start_date']} – {r['end_date']}"
    for u in rcpts:
        if not u or u == actor:
            continue
        s = collab_user(c, u, None)
        if not s:
            continue
        news_add(c, u, kind, actor=actor, data={"absence_id": r["id"], "org_id": r["org_id"], "start": r["start_date"],
                                                "end": r["end_date"], **data}, s=s)
        if not notif_ok(c, u, s, KIND_ROW[kind], "push") or not push_reachable(c, u, s):
            continue
        lg = lang_of(s)
        title = (tr("{0} asks for vacation", who, lg=lg) if kind == "leavereq" else
                 tr("{0} approved your vacation", who, lg=lg) if data.get("state") == "approved" else
                 tr("{0} rejected your vacation", who, lg=lg))
        g.pushes.append((u, title, span, f"{PUBLIC_URL}/#workload", push_prio(s), {"scope": f"o:{r['org_id']}"}))  # 2.240.0 B2 (#2867)


def lv_requested(c, r):
    """After a new / changed absence r: tell the admins when it waits for them."""
    if (r["status"] or "") == "pending":
        lv_notify(c, lv_admins(c, r["org_id"]), "leavereq", r, {})


def lv_news_live(c, uid, data):
    """A leave News item stays while its absence is there (row-level security: my areas only)."""
    try:
        aid = int((data or {}).get("absence_id") or 0)
    except (TypeError, ValueError, AttributeError):
        return False
    return bool(c.execute("SELECT 1 FROM hub_absences WHERE id=? AND deleted_at IS NULL", (aid,)).fetchone())


# ---------------------------------------------------------------- the account
def lv_quota(c, oid, uid, year):
    r = c.execute("SELECT days, carry FROM hub_leave_quota WHERE org_id=? AND user_id=? AND year=?", (oid, uid, year)).fetchone()
    return {"days": r["days"], "carry": r["carry"]} if r else None


def lv_account(c, oid, people, year, state):
    """{user id: {quota, taken, requested, rest}} of the given people in area oid for year."""
    first, last = date(year, 1, 1), date(year, 12, 31)
    hol = abs_holidays(state, first, last)
    ids = [p["id"] for p in people]
    out = {i: {"quota": None, "taken": 0.0, "requested": 0.0, "rest": None} for i in ids}
    if not ids:
        return out
    q = ",".join("?" * len(ids))
    for r in c.execute(f"SELECT user_id, days, carry FROM hub_leave_quota WHERE org_id=? AND year=? AND user_id IN ({q})",
                       (oid, year, *ids)).fetchall():
        out[r["user_id"]]["quota"] = {"days": r["days"], "carry": r["carry"]}
    wds = {i: wt_workdays(c, i) for i in ids}
    for r in c.execute(f"SELECT * FROM hub_absences WHERE org_id=? AND deleted_at IS NULL AND user_id IN ({q}) "
                       "AND start_date<=? AND end_date>=? AND status IN ('approved','pending')",
                       (oid, *ids, last.isoformat(), first.isoformat())).fetchall():
        if oc_dec_fields(c, oid, "hub_absences", r)["kind"] != "vacation":
            continue
        n = lv_count(r["start_date"], r["end_date"], r["half_day"], wds[r["user_id"]], hol, first, last)
        out[r["user_id"]]["taken" if r["status"] == "approved" else "requested"] += n
    for v in out.values():
        if v["quota"]:
            v["rest"] = round(v["quota"]["days"] + v["quota"]["carry"] - v["taken"] - v["requested"], 1)
    return out


def _area(c, uid, v):
    try:
        want = int(v) if v else None
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid data")) from None
    return abs_org(c, uid, want)


def _num(v, name, lo=0, hi=LV_DAYS_MAX):
    try:
        x = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", name)) from None
    if not lo <= x <= hi or x * 2 != int(x * 2):  # whole or half days
        raise BadInput(tr("Invalid value: {0}", name))
    return x


def _member(c, oid, who):
    if who not in {p["id"] for p in abs_people(c, oid)}:
        raise Denied(404, tr("unknown user"))


# ---------------------------------------------------------------- routes
@app.get("/api/team/leave")
def lv_get():
    """?org=&year=: the vacation accounts (admins: everybody of the area, else oneself), the open requests (admins: all,
    else one's own), whether the area asks for approvals, the working days + weekly hours of the people shown."""
    from ..team.workload import capacity_h
    c, uid = _gate()
    a = request.args
    oid = _area(c, uid, a.get("org"))
    try:
        year = int(a.get("year") or local_now().year)
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "year")) from None
    if not 2000 <= year <= 2100:
        raise BadInput(tr("Invalid value: {0}", "year"))
    adm = abs_admin(c, uid, oid)
    people = [p for p in abs_people(c, oid) if adm or p["id"] == uid]
    st = abs_state(c, oid)
    acc = lv_account(c, oid, people, year, st)
    pids = {p["id"] for p in people}
    rows = c.execute("SELECT * FROM hub_absences WHERE org_id=? AND deleted_at IS NULL AND status='pending' ORDER BY start_date, id",
                     (oid,)).fetchall()
    pend = []
    for r in rows:
        if r["user_id"] not in pids:
            continue
        hol = abs_holidays(st, date.fromisoformat(r["start_date"]), date.fromisoformat(r["end_date"]))
        pend.append({**abs_public(r, True, c), "days": lv_count(r["start_date"], r["end_date"], r["half_day"], wt_workdays(c, r["user_id"]), hol)})
    with system_ctx(c):  # the area's own row (personal or not)
        o = c.execute("SELECT personal_of FROM orgs WHERE id=?", (oid,)).fetchone()
    return jsonify(org_id=oid, year=year, admin=adm, personal=bool(o and o[0]), approval=lv_approval_on(c, oid),
                   people=[{"id": p["id"], "display_name": p["display_name"] or p["username"], "own": p["id"] == uid,
                            "workdays": list(wt_workdays(c, p["id"])), "capacity_h": capacity_h(c, p["id"]),
                            "capacity_set": bool(usettings(c, p["id"]).get("capacity_h")), **acc[p["id"]]} for p in people],
                   pending=pend)


@app.put("/api/team/leave/quota")
def lv_set_quota():
    """{user_id, year, days: number | null (null = no account), carry?, org?}: the vacation entitlement of a person (the
    area's admins; a person without an organisation for themselves)."""
    c, uid = _gate()
    b = body()
    oid = _area(c, uid, b.get("org"))
    if not abs_admin(c, uid, oid):
        raise Denied(403, tr("Only admins of the organisation can change this"))
    try:
        who, year = int(b.get("user_id") or uid), int(b.get("year") or 0)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid data")) from None
    if not 2000 <= year <= 2100:
        raise BadInput(tr("Invalid value: {0}", "year"))
    _member(c, oid, who)
    if b.get("days") is None or b.get("days") == "":
        c.execute("DELETE FROM hub_leave_quota WHERE org_id=? AND user_id=? AND year=?", (oid, who, year))
    else:
        days, carry = _num(b.get("days"), "days"), _num(b.get("carry") or 0, "carry")
        c.execute("INSERT INTO hub_leave_quota(org_id,user_id,year,days,carry,updated_by,updated_at) VALUES(?,?,?,?,?,?,?) "
                  "ON CONFLICT(org_id,user_id,year) DO UPDATE SET days=excluded.days, carry=excluded.carry, "
                  "updated_by=excluded.updated_by, updated_at=excluded.updated_at", (oid, who, year, days, carry, uid, iso(now_utc())))
    bump(c)
    c.commit()
    return jsonify(org_id=oid, user_id=who, year=year, quota=lv_quota(c, oid, who, year))


@app.put("/api/team/leave/approval")
def lv_set_approval():
    """{on: bool, org?}: vacation of members needs an approval of the admins (an organisation's admins; not for a personal
    area: its owner is their own admin)."""
    c, uid = _gate()
    b = body()
    oid = _area(c, uid, b.get("org"))
    from ..accounts.orgs import is_org_admin
    if not is_org_admin(c, uid, oid):
        raise Denied(403, tr("Only admins of the organisation can change this"))
    on = 1 if b.get("on") else 0
    with system_ctx(c):  # the organisation's own row (orgs is structure); the admin right is checked above
        c.execute("UPDATE orgs SET hub_leave_approval=? WHERE id=? AND personal_of IS NULL", (on, oid))
    bump(c)
    c.commit()
    return jsonify(org_id=oid, approval=bool(on))


@app.put("/api/team/leave/worktime/<int:who>")
def lv_set_worktime(who):
    """{workdays?: [0..6] | '0,1,2' | '' (default Monday..Friday), hours?: number | null (default), org?}: working days and
    weekly hours of a person -- oneself, or an admin of the area for its members (they are the person's own settings)."""
    c, uid = _gate()
    b = body()
    oid = _area(c, uid, b.get("org"))
    if who != uid:
        if not abs_admin(c, uid, oid):
            raise Denied(403, tr("Only admins of the organisation can change this"))
        _member(c, oid, who)
    from ..accounts.settings import clean_setting
    if "workdays" in b:
        uset(c, who, "workdays", wt_clean(b.get("workdays")))
    if "hours" in b:
        uset(c, who, "capacity_h", clean_setting("capacity_h", b.get("hours")) or "")
    bump(c)
    c.commit()
    from ..team.workload import capacity_h
    return jsonify(id=who, workdays=list(wt_workdays(c, who)), capacity_h=capacity_h(c, who),
                   capacity_set=bool(usettings(c, who).get("capacity_h")))


@app.post("/api/team/absences/<int:aid>/decide")
def lv_decide(aid):
    """{action: approve | reject | reopen, note?}: the area's admins decide on a vacation request (reopen = back to open,
    the Undo of a decision)."""
    c, uid = _gate()
    r = _row(c, aid)
    if r["deleted_at"]:
        raise Denied(404)
    if not abs_admin(c, uid, r["org_id"]):
        raise Denied(403, tr("Only admins of the organisation can decide on vacation requests"))
    b = body()
    act = b.get("action")
    if act not in ("approve", "reject", "reopen"):
        raise BadInput(tr("Invalid value: {0}", "action"))
    note = b.get("note") or ""
    if not isinstance(note, str):
        raise BadInput(tr("Invalid value: {0}", "note"))
    note = note.strip()[:LV_NOTE_MAX]
    cur = r["status"] or "approved"
    if act == "reopen":
        if cur == "pending":
            raise BadInput(tr("This vacation request is still open"))
        # 2.125.0 R (#2117): only the Undo of a decision on a vacation request (a sick leave set to pending would count nowhere)
        if not r["decided_by"] or oc_dec_fields(c, r["org_id"], "hub_absences", r)["kind"] != "vacation":
            raise Denied(409, tr("This absence was not decided on"))
        c.execute("UPDATE hub_absences SET status='pending', decided_by=NULL, decided_at=NULL, decision_note='' WHERE id=?", (aid,))
    else:
        if cur != "pending":
            raise BadInput(tr("This vacation request was decided already"))
        state = "approved" if act == "approve" else "rejected"
        e = oc_enc_fields(c, r["org_id"], "hub_absences", {"decision_note": note})
        c.execute("UPDATE hub_absences SET status=?, decided_by=?, decided_at=?, decision_note=? WHERE id=?",
                  (state, uid, iso(now_utc()), e["decision_note"], aid))
        lv_notify(c, [r["user_id"]], "leavedecide", r, {"state": state})
    bump(c)
    c.commit()
    return jsonify({**abs_public(_row(c, aid), True, c), "can_edit": True})
