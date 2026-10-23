"""2.50.0 (#1194): resources and disposition -- booking crew and equipment for shoot days, seeing who and what is free per
day, spotting double bookings.

A booking (hub_bookings) = one resource for one period in one area (org_id: the organisation, or the person's personal area
like the office): resource_kind user (a member with an account) | contact (an address book contact without an account, from
the area's address books) | equipment (office_equipment) | set (office_sets: books its equipment along). Bookings made
together share job (one shoot day = one job: title, period, project list / client optional). status option (pencilled in) |
firm. start / end: ISO day (whole days) or ISO day + "T" + HH:MM.
Double bookings and absences (hub/absence.py: vacation, sick leave, day off -- the kind is never shown here) are warnings,
never blocks. Booking: the module "dispo" on (Settings > Modules, off by default) and a member of the area (organisations
have no guest role; people outside see nothing). The booked people see their own bookings (GET /api/team/bookings/mine,
also without the module); a firm booking puts a News entry in their feed (event "assigned to me", their switch).
Deleting sets deleted_at (Undo restores)."""
import csv
import io
import json
import re
import secrets
from datetime import date, datetime, timedelta

from flask import Response, g, jsonify, request

from ..core.config import app, APP_NAME
from ..core.pg import insert_id
from ..core.i18n import dec_comma, lang, tr
from ..core.db import body, bump, db, iso, local_now, now_utc
from ..core.access import Denied, need_feat
from ..accounts.session import me, user_public
from ..core.errors import BadInput
from .absence import abs_admin, abs_days, abs_holidays, abs_org, abs_people, abs_state

DSP_KINDS = ("user", "contact", "equipment", "set")
DSP_STATUS = ("option", "firm")
DSP_DAYS_MAX = 62
DSP_RES_MAX = 60  # resources of one booking
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T([01]\d|2[0-3]):[0-5]\d)?$")


def _gate(feat=True):
    u = g.user
    if u is None:
        raise Denied(401)
    if (u["kind"] or "user") == "agent":
        raise Denied(403, tr("Agents cannot use this endpoint"))
    if u["kid"]:
        raise Denied(403)
    if feat:
        need_feat("dispo")
    return db(), u["id"]


def _ts(v, name):
    if isinstance(v, str) and TS_RE.match(v.strip()):
        v = v.strip()
        try:
            date.fromisoformat(v[:10])
            return v
        except ValueError:
            pass
    raise BadInput(tr("Invalid value: {0}", name))


def dsp_span(start, end):
    """(from, to) comparable strings of a booking: a whole day runs 00:00..24:00."""
    a = start if "T" in start else start + "T00:00"
    b = end if "T" in end else end + "T24:00"
    return a, b


def dsp_overlap(x, y):
    a1, b1 = dsp_span(x["start"], x["end"])
    a2, b2 = dsp_span(y["start"], y["end"])
    return a1 < b2 and a2 < b1


def _set_items(raw):
    try:
        v = json.loads(raw or "[]")
    except ValueError:
        return []
    return [int(x["equipment_id"]) for x in v if isinstance(x, dict) and str(x.get("equipment_id", "")).isdigit()]


# ---------------------------------------------------------------- the resources of an area
def dsp_contacts(c, uid, oid):
    """[(id, name)] of the individual contacts of the area's address books uid may read (organisation books; a personal
    area: the person's own books without an organisation)."""
    from ..contacts.model import my_book_ids
    from ..office.model import pb_personal
    personal = oid == pb_personal(c, uid, create=False)
    bids = [b for b in my_book_ids(c, uid)]
    if not bids:
        return []
    q = ",".join("?" * len(bids))
    rows = c.execute(f"SELECT c.id, c.fn, c.given, c.family FROM contacts c JOIN books b ON b.id=c.book_id WHERE c.book_id IN ({q}) "
                     f"AND c.kind='individual' AND {'b.org_id IS NULL AND b.owner_id=?' if personal else 'b.org_id=?'} "
                     "ORDER BY lower(c.fn), c.id LIMIT 500", (*bids, uid if personal else oid)).fetchall()
    return [(r["id"], (r["fn"] or f"{r['given']} {r['family']}").strip() or "?") for r in rows]


def dsp_resources(c, uid, oid):
    people = [{"kind": "user", "id": p["id"], "name": p["display_name"] or p["username"], "avatar": user_public(p)["avatar"]} for p in abs_people(c, oid)]
    contacts = [{"kind": "contact", "id": i, "name": n} for i, n in dsp_contacts(c, uid, oid)]
    from ..office.rights import ofr_allows
    if not ofr_allows(c, uid, oid, "equipment"):  # 2.187.0 C (#2476): office groups without the equipment area
        return {"people": people, "contacts": contacts, "equipment": [], "sets": []}
    eq = [{"kind": "equipment", "id": r["id"], "name": r["name"], "category": r["category"] or ""} for r in c.execute(
        "SELECT id, name, category FROM office_equipment WHERE org_id=? AND archived=0 ORDER BY lower(category), lower(name), id", (oid,))]
    sets = [{"kind": "set", "id": r["id"], "name": r["name"], "items": _set_items(r["items"])} for r in c.execute(
        "SELECT id, name, items FROM office_sets WHERE org_id=? AND archived=0 ORDER BY lower(name), id", (oid,))]
    return {"people": people, "contacts": contacts, "equipment": eq, "sets": sets}


def _res_index(res):
    return {(r["kind"], r["id"]): r for grp in res.values() for r in grp}


# ---------------------------------------------------------------- conflicts
def dsp_units(b, sets):
    """The physical things a booking holds: ("user", id) / ("contact", id) / ("equipment", id), a set -> its equipment."""
    if b["resource_kind"] == "set":
        return {("equipment", e) for e in sets.get(b["resource_id"], [])} | {("set", b["resource_id"])}
    return {(b["resource_kind"], b["resource_id"])}


def dsp_conflicts(c, oid, rows, first, last):
    """{booking id: {"double": [other booking ids], "away": bool}} for rows (dicts) against every booking of the area in
    [first, last] and the absences of the booked people (the kind never)."""
    sets = {r["id"]: _set_items(r["items"]) for r in c.execute("SELECT id, items FROM office_sets WHERE org_id=?", (oid,))}
    allb = [dict(r) for r in c.execute("SELECT id, start, \"end\", resource_kind, resource_id FROM hub_bookings WHERE org_id=? "
                                        "AND deleted_at IS NULL AND start<=? AND \"end\">=?", (oid, last.isoformat() + "T99", first.isoformat()))]
    units = {b["id"]: dsp_units(b, sets) for b in allb}
    uids = sorted({r["resource_id"] for r in rows if r["resource_kind"] == "user"})
    away = abs_days(c, uids, first, last, oid) if uids else {}
    out = {}
    for r in rows:
        mine = units.get(r["id"]) or dsp_units(r, sets)
        dbl = [b["id"] for b in allb if b["id"] != r["id"] and units[b["id"]] & mine and dsp_overlap(r, b)]
        gone = False
        if r["resource_kind"] == "user":
            d0, d1 = date.fromisoformat(r["start"][:10]), date.fromisoformat(r["end"][:10])
            days = away.get(r["resource_id"], {})
            d = d0
            while d <= d1 and not gone:
                gone = d.isoformat() in days
                d += timedelta(days=1)
        out[r["id"]] = {"double": dbl, "away": gone}
    return out


def dsp_public(r, conf=None):
    d = {"id": r["id"], "job": r["job"], "title": r["title"], "start": r["start"], "end": r["end"],
         "kind": r["resource_kind"], "rid": r["resource_id"], "label": r["res_label"], "status": r["status"],
         "note": r["note"] or "", "list_id": r["list_id"], "event_id": r["event_id"]}
    if conf is not None:
        d.update(conflicts=conf.get("double", []), away=conf.get("away", False))
    return d


def _clean(b, cur=None):
    cur = cur or {}
    out = {}
    if "title" in b or not cur:
        v = b.get("title")
        if not isinstance(v, str) or not v.strip():
            raise BadInput(tr("Please enter a name"))
        out["title"] = re.sub(r"[\x00-\x1f\x7f]", "", v).strip()[:200]
    if "start" in b or not cur:
        out["start"] = _ts(b.get("start"), "start")
    if "end" in b or not cur:
        out["end"] = _ts(b.get("end") or out.get("start") or cur.get("start"), "end")
    if "status" in b or not cur:
        st = b.get("status") or "option"
        if st not in DSP_STATUS:
            raise BadInput(tr("Invalid value: {0}", "status"))
        out["status"] = st
    if "note" in b:
        v = b.get("note") or ""
        if not isinstance(v, str):
            raise BadInput(tr("Invalid value: {0}", "note"))
        out["note"] = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", v).strip()[:1000]
    s, e = out.get("start", cur.get("start")), out.get("end", cur.get("end"))
    if dsp_span(s, e)[1] <= dsp_span(s, e)[0]:
        raise BadInput(tr("The end is before the start"))
    if (date.fromisoformat(e[:10]) - date.fromisoformat(s[:10])).days > DSP_DAYS_MAX:
        raise BadInput(tr("Invalid value: {0}", "end"))
    return out


def _area(c, uid, want):
    try:
        want = int(want) if want else None
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid data")) from None
    return abs_org(c, uid, want)


def _row(c, bid):
    r = c.execute("SELECT * FROM hub_bookings WHERE id=?", (bid,)).fetchone()  # row-level security: my areas only
    if not r:
        raise Denied(404)
    return r


def _notify(c, r):
    """A firm booking of a person with an account: a News entry for them (event "assigned to me", their own switch)."""
    if r["resource_kind"] != "user" or r["status"] != "firm" or r["resource_id"] == me():
        return
    from ..collab.news import news_add
    news_add(c, r["resource_id"], "dispo", data={"booking_id": r["id"], "title": r["title"], "start": r["start"], "end": r["end"]})


# ---------------------------------------------------------------- routes
@app.get("/api/team/dispo")
def dsp_get():
    """?start=YYYY-MM-DD (default today) &days=1..62 (7) &org=<id>: the resources of the area, the bookings of the period
    with their conflicts, the absent days of the people ("away" only), the public holidays."""
    c, uid = _gate()
    a = request.args
    oid = _area(c, uid, a.get("org"))
    today = local_now().date()
    try:
        first = date.fromisoformat(a["start"]) if a.get("start") else today
        n = max(1, min(DSP_DAYS_MAX, int(a.get("days") or 7)))
    except ValueError:
        raise BadInput(tr("Invalid data")) from None
    last = first + timedelta(days=n - 1)
    res = dsp_resources(c, uid, oid)
    rows = [dict(r) for r in c.execute("SELECT * FROM hub_bookings WHERE org_id=? AND deleted_at IS NULL AND start<=? AND \"end\">=? "
                                        "ORDER BY start, id", (oid, last.isoformat() + "T99", first.isoformat()))]
    conf = dsp_conflicts(c, oid, rows, first, last)
    gone = abs_days(c, [p["id"] for p in res["people"]], first, last, oid)
    from ..accounts.orgroles import user_orgs_full
    mine = user_orgs_full(c, uid)  # 2.143.0 A (#2151): not guests / accounting
    return jsonify(org_id=oid, orgs=[{"id": r[0], "name": r[1]} for r in c.execute(
        "SELECT id, name FROM orgs WHERE personal_of IS NULL ORDER BY lower(name), id") if r[0] in mine],
        can_book=True, admin=abs_admin(c, uid, oid), today=today.isoformat(), start=first.isoformat(), end=last.isoformat(),
        resources=res, bookings=[dsp_public(r, conf.get(r["id"])) for r in rows],
        away={str(k): v for k, v in gone.items()},
        holidays=[{"date": k, "name": v} for k, v in sorted(abs_holidays(abs_state(c, oid), first, last).items())])


# 2.141.0 C (#2142): the visible disposition (period, filter and area like the view) as CSV or ICS
def _export_rows(c, uid, a):
    oid = _area(c, uid, a.get("org"))
    try:
        first = date.fromisoformat(a["start"]) if a.get("start") else local_now().date()
        n = max(1, min(DSP_DAYS_MAX, int(a.get("days") or 7)))
    except ValueError:
        raise BadInput(tr("Invalid data")) from None
    last = first + timedelta(days=n - 1)
    kinds = {"people": ("user", "contact"), "tech": ("equipment", "set")}.get(a.get("filter"))
    rows = [r for r in c.execute("SELECT * FROM hub_bookings WHERE org_id=? AND deleted_at IS NULL AND start<=? AND \"end\">=? "
                                  "ORDER BY start, id", (oid, last.isoformat() + "T99", first.isoformat()))
            if not kinds or r["resource_kind"] in kinds]
    return first, last, rows


def _hours(r):
    if "T" not in r["start"] or "T" not in r["end"]:
        return ""  # whole days carry no hours
    h = (datetime.fromisoformat(r["end"]) - datetime.fromisoformat(r["start"])).total_seconds() / 3600
    return f"{h:.2f}".rstrip("0").rstrip(".")


@app.get("/api/team/dispo/export")
def dsp_export():
    """?format=csv|ics &start=YYYY-MM-DD &days=1..62 &org= &filter=all|people|tech: the bookings the view shows. CSV: resource, kind,
    booking, project, status, start, end, hours (timed bookings), note; ICS: one VEVENT per booking."""
    c, uid = _gate()
    a = request.args
    fmt = a.get("format") or "csv"
    if fmt not in ("csv", "ics"):
        raise BadInput(tr("Invalid value: {0}", "format"))
    first, last, rows = _export_rows(c, uid, a)
    name = f"dispo-{first.isoformat()}-{last.isoformat()}.{fmt}"
    hdr = {"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"}
    if fmt == "csv":
        from ..core.serializers import csv_cell as cell
        from ..core.access import list_role
        lists = {}
        for r in rows:
            if r["list_id"] and r["list_id"] not in lists:
                x = c.execute("SELECT name, e2e FROM lists WHERE id=?", (r["list_id"],)).fetchone()  # row-level security: lists I may see
                # 2.141.0 C (#2142, review): only names of lists I am a member of (the view shows no other names either)
                lists[r["list_id"]] = "" if not x or x["e2e"] or not list_role(c, r["list_id"], uid) else x["name"]
        kind = {"user": tr("Person"), "contact": tr("Contact"), "equipment": tr("Equipment"), "set": tr("Equipment set")}
        status = {"option": tr("Option"), "firm": tr("Firm")}
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";" if dec_comma(lang()) else ",", lineterminator="\r\n")
        w.writerow([tr("Resource"), tr("Kind"), tr("Booking"), tr("Project"), tr("Status"), tr("Start"), tr("End"), tr("Hours"), tr("Note")])
        for r in rows:
            h = _hours(r)
            w.writerow([cell(r["res_label"]), kind.get(r["resource_kind"], ""), cell(r["title"]), cell(lists.get(r["list_id"], "")),
                        status.get(r["status"], ""), r["start"].replace("T", " "), r["end"].replace("T", " "),
                        h.replace(".", ",") if dec_comma(lang()) else h, cell(r["note"])])
        return Response("\ufeff" + buf.getvalue(), mimetype="text/csv; charset=utf-8", headers=hdr)
    from ..calendars.icalfeed import ics_fold, ics_text, ics_utc
    stamp = ics_utc(now_utc())
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//{APP_NAME}//Disposition//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    for r in rows:
        allday = "T" not in r["start"]
        end = r["end"]
        if allday:
            e = date.fromisoformat(end[:10]) + timedelta(days=1)
            dt = [f"DTSTART;VALUE=DATE:{r['start'][:10].replace('-', '')}", f"DTEND;VALUE=DATE:{e.isoformat().replace('-', '')}"]
        else:
            if "T" not in end:
                end = end[:10] + "T23:59"
            dt = [f"DTSTART:{r['start'].replace('-', '').replace(':', '')}00", f"DTEND:{end.replace('-', '').replace(':', '')}00"]
        lines += ["BEGIN:VEVENT", f"UID:dispo-{r['id']}@kalmido", f"DTSTAMP:{stamp}", *dt,
                  f"SUMMARY:{ics_text(r['title'] + (' – ' + r['res_label'] if r['res_label'] else ''))}",
                  f"STATUS:{'CONFIRMED' if r['status'] == 'firm' else 'TENTATIVE'}"]
        if r["note"]:
            lines.append(f"DESCRIPTION:{ics_text(r['note'])}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return Response("\r\n".join(ics_fold(x) for x in lines) + "\r\n", mimetype="text/calendar; charset=utf-8", headers=hdr)


@app.get("/api/team/dispo/free")
def dsp_free():
    """?date=YYYY-MM-DD &org=: who and what is free that day (no booking, not away; equipment: not in a booked set)."""
    c, uid = _gate()
    a = request.args
    oid = _area(c, uid, a.get("org"))
    try:
        day = date.fromisoformat(a.get("date") or "")
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "date")) from None
    res = dsp_resources(c, uid, oid)
    sets = {s["id"]: s["items"] for s in res["sets"]}
    busy = set()
    for b in c.execute("SELECT * FROM hub_bookings WHERE org_id=? AND deleted_at IS NULL AND start<=? AND \"end\">=?",
                       (oid, day.isoformat() + "T99", day.isoformat())):
        busy |= dsp_units(b, sets)
    gone = abs_days(c, [p["id"] for p in res["people"]], day, day, oid)
    free = lambda grp: [r for r in grp if (r["kind"], r["id"]) not in busy and not (r["kind"] == "user" and gone.get(r["id"]))]  # noqa: E731
    return jsonify(date=day.isoformat(), people=free(res["people"]), contacts=free(res["contacts"]), equipment=free(res["equipment"]),
                   sets=[s for s in res["sets"] if ("set", s["id"]) not in busy and not any(("equipment", e) in busy for e in s["items"])],
                   away=[p["id"] for p in res["people"] if gone.get(p["id"])])


@app.post("/api/team/dispo/bookings")
def dsp_create():
    """{title, start, end?, status option|firm, note?, list_id?, org?, resources: [{kind, id}]}: one booking per resource
    (one job). Answers {bookings (with conflicts / away), warnings: n} -- conflicts never block."""
    c, uid = _gate()
    b = body()
    oid = _area(c, uid, b.get("org"))
    v = _clean(b)
    res = b.get("resources")
    if not isinstance(res, list) or not res or len(res) > DSP_RES_MAX:
        raise BadInput(tr("Choose at least one person or device"))
    idx = _res_index(dsp_resources(c, uid, oid))
    picks = []
    for x in res:
        try:
            k, i = x.get("kind"), int(x.get("id"))
        except (AttributeError, TypeError, ValueError):
            raise BadInput(tr("Invalid data")) from None
        if k not in DSP_KINDS or (k, i) not in idx:
            raise Denied(404, tr("unknown"))
        if (k, i) not in picks:
            picks.append((k, i))
    lid = b.get("list_id")
    if lid not in (None, ""):
        from ..core.access import list_role
        try:
            lid = int(lid)
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid data")) from None
        from ..office.model import pb_cl_sql
        # 2.50.0 (#1194 review): a project of this area only (a personal area: the owner's private lists), and visible
        if not list_role(c, lid, uid) or not c.execute(f"SELECT 1 FROM lists WHERE id=? AND {pb_cl_sql(c, oid, 'org_id', 'owner_id')}",
                                                         (lid,)).fetchone():
            raise Denied(404)
    else:
        lid = None
    job = secrets.token_hex(8)
    now = iso(now_utc())
    ids = []
    for k, i in picks:
        ids.append(insert_id(c, "INSERT INTO hub_bookings(org_id,job,title,start,\"end\",resource_kind,resource_id,res_label,status,note,list_id,"
                                "created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (oid, job, v["title"], v["start"], v["end"], k, i, idx[(k, i)]["name"][:200], v["status"], v.get("note", ""), lid, uid, now, now)))
    rows = [dict(_row(c, x)) for x in ids]
    for r in rows:
        _notify(c, r)
    bump(c)
    c.commit()
    first, last = date.fromisoformat(v["start"][:10]), date.fromisoformat(v["end"][:10])
    conf = dsp_conflicts(c, oid, rows, first, last)
    out = [dsp_public(r, conf.get(r["id"])) for r in rows]
    return jsonify(bookings=out, warnings=sum(1 for x in out if x["conflicts"] or x["away"])), 201


@app.patch("/api/team/dispo/bookings/<int:bid>")
def dsp_edit(bid):
    """{title?, start?, end?, status?, note?, all?: true (the whole job)}"""
    c, uid = _gate()
    r = _row(c, bid)
    if r["deleted_at"]:
        raise Denied(404)
    b = body()
    v = _clean(b, dict(r))
    targets = [x for x in c.execute("SELECT * FROM hub_bookings WHERE org_id=? AND job=? AND deleted_at IS NULL", (r["org_id"], r["job"]))] if b.get("all") else [r]
    if v:
        for t in targets:
            c.execute(f"UPDATE hub_bookings SET {', '.join(_q(k) + '=?' for k in v)}, updated_at=? WHERE id=?", (*v.values(), iso(now_utc()), t["id"]))
        if v.get("status") == "firm":
            for t in targets:
                if t["status"] != "firm":
                    _notify(c, _row(c, t["id"]))
        bump(c)
        c.commit()
    rows = [dict(_row(c, t["id"])) for t in targets]
    first = min(date.fromisoformat(x["start"][:10]) for x in rows)
    last = max(date.fromisoformat(x["end"][:10]) for x in rows)
    conf = dsp_conflicts(c, r["org_id"], rows, first, last)
    return jsonify(bookings=[dsp_public(x, conf.get(x["id"])) for x in rows])


def _q(k):
    return '"end"' if k == "end" else k


@app.delete("/api/team/dispo/bookings/<int:bid>")
def dsp_delete(bid):
    """?all=1: the whole job. Answers {ids} (for Undo: POST .../restore {ids})."""
    c, uid = _gate()
    r = _row(c, bid)
    if request.args.get("all"):
        ids = [x[0] for x in c.execute("SELECT id FROM hub_bookings WHERE org_id=? AND job=? AND deleted_at IS NULL", (r["org_id"], r["job"]))]
    else:
        ids = [bid] if not r["deleted_at"] else []
    now = iso(now_utc())
    for x in ids:
        c.execute("UPDATE hub_bookings SET deleted_at=? WHERE id=?", (now, x))
    bump(c)
    c.commit()
    return jsonify(ids=ids)


@app.post("/api/team/dispo/bookings/restore")
def dsp_restore():
    """{ids: [...]}: Undo of a delete."""
    c, uid = _gate()
    ids = body().get("ids")
    if not isinstance(ids, list) or len(ids) > 500:
        raise BadInput(tr("Invalid data"))
    n = 0
    for x in ids:
        try:
            r = _row(c, int(x))
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid data")) from None
        n += c.execute("UPDATE hub_bookings SET deleted_at=NULL WHERE id=? AND deleted_at IS NOT NULL", (r["id"],)).rowcount
    bump(c)
    c.commit()
    return jsonify(restored=n)


@app.get("/api/team/bookings/mine")
def dsp_mine():
    """My own bookings (as a person with an account) from today on, of every area I am in -- also without the module."""
    c, uid = _gate(feat=False)
    since = (request.args.get("since") or local_now().date().isoformat())[:10]
    rows = c.execute("SELECT b.*, o.name AS org_name, o.personal_of FROM hub_bookings b JOIN orgs o ON o.id=b.org_id "
                     "WHERE b.resource_kind='user' AND b.resource_id=? AND b.deleted_at IS NULL AND b.\"end\">=? "
                     "ORDER BY b.start, b.id LIMIT 200", (uid, since)).fetchall()
    return jsonify(bookings=[{**dsp_public(r), "org": "" if r["personal_of"] else r["org_name"]} for r in rows])


def dsp_cal(c, uid, lo, hi):
    """My own bookings overlapping [lo, hi] (dates) as read-only calendar entries (GET /api/calendars/events): an option
    says so in its title. Whole days: end = the day after (exclusive, like the other all-day events)."""
    out = []
    for r in c.execute("SELECT id, title, start, \"end\", status FROM hub_bookings WHERE resource_kind='user' AND resource_id=? "
                       "AND deleted_at IS NULL AND start<=? AND \"end\">=? ORDER BY start, id LIMIT 500",
                       (uid, hi.isoformat() + "T99", lo.isoformat())):
        allday = "T" not in r["start"]
        end = r["end"]
        if allday:
            end = (date.fromisoformat(end[:10]) + timedelta(days=1)).isoformat()
        elif "T" not in end:
            end = end[:10] + "T23:59"
        out.append({"id": f"b{r['id']}", "booking": r["id"], "status": r["status"], "all_day": allday, "start": r["start"], "end": end,
                    "title": tr("Option: {0}", r["title"]) if r["status"] == "option" else tr("Booked: {0}", r["title"]),
                    "location": "", "description": ""})
    return out
