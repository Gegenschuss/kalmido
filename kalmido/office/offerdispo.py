"""2.589.0 (#4571): shoot days from a quotation as pencilled-in bookings of the disposition (decision of 04.11.2026).

Taking a quotation into a project (office/offertasks.py, #3433: GET / POST /api/office/docs/<did>/tasks) makes every shoot
part of it one shoot day of the disposition (hub/dispo.py: one job, status option, list_id = the project) with one open place
per person a crew function needs (resource_kind 'slot', resource_id 0, slot_name = the function; filled in the disposition,
POST /api/team/dispo/bookings/<id>/fill). The period: the shoot days of the part's sheet (head shoot_days, at least one whole
day; travel and prep days are no shoot days), starting on the quotation's period of service (service_from), the next shoot
part right after the one before; without a date the preview asks for one. Equipment and a packing list do not come (#4566).
Only with the module Disposition on (the person's setting, core/access.py need_feat), a role that changes things in the
area (need_org_write, a full member: hub/absence.py abs_org) and the industry Film & Video (accounts/onboarding.py
ind_of_area, #4573); otherwise the preview carries a hint and nothing is booked.
A new version of the quotation (the chain, version_of: offer_root) adapts the pencilled-in days: period, new places, empty
places of a function no longer there go (deleted_at, Undo in the disposition restores them). A firm booking and a filled place
stay as they are and get only a mark (offer_mark 'changed' | 'gone'), which a change by hand in the disposition takes off.
The bookings live in the quotation's office area (the organisation, or the person's own area): the same area the disposition
shows; row-level security (core/rls.py hub_bookings) keeps them there."""
import math
import secrets
from datetime import date, timedelta
from decimal import Decimal

from ..accounts.onboarding import ind_of_area
from ..accounts.orgroles import org_writes
from ..core.access import Denied, acx_org_ok, need_feat
from ..core.db import iso, now_utc
from ..core.errors import BadInput
from ..core.i18n import tr
from ..core.pg import insert_id
from ..hub.absence import abs_admin, abs_org
from .calc import calc_lang
from .docs import doc_items
from .parts import tp_parts
from .sheet import dk_staff_days

ODP_PLACES_MAX = 20  # open places of one crew function
ODP_DAYS_MAX = 31    # shoot days of one part (the disposition takes 62 per booking)


def odp_gate(c, uid, oid):
    """'' when uid may book shoot days in office area oid, else the hint the preview shows."""
    if ind_of_area(c, oid) != "film":
        return tr("Shoot days go into the disposition only with the industry Film & Video.")
    try:
        need_feat("dispo")
    except Denied:
        return tr("Switch on the module Disposition to pencil the shoot days in.")
    try:
        abs_org(c, uid, oid, create=False)  # a full member of the area (not a guest / accounting) or its owner
    except Denied:
        return tr("You cannot book in the disposition of this workspace.")
    if not org_writes(c, uid, oid) or not acx_org_ok(c, uid, oid):
        return tr("You cannot book in the disposition of this workspace.")
    return ""


def _day(v):
    try:
        return date.fromisoformat(str(v or "")[:10]) if v else None
    except ValueError:
        return None


def odp_days(c, oid, r):
    """The shoot days quotation r asks for: [{key, title, days, start (ISO or None), places: [{key, name}]}] in the print order."""
    lg = calc_lang(r["lang"])
    parts = {p["id"]: p for p in tp_parts(c, oid, r["id"])}
    out, seen = [], set()
    nxt = _day(r["service_from"] if "service_from" in r.keys() else None)
    for it in doc_items(c, r["id"], oid):
        p = parts.get(it["ref_part_id"]) if it["kind"] == "part" else None
        if p is None or p["kind"] != "shoot":
            continue
        pk = str(p.get("origin_id") or p["id"])
        if pk in seen:  # a part used twice on the title page is one shoot day job
            continue
        seen.add(pk)
        head = (p["sheet"] or {}).get("head") or {}
        try:
            n = int(math.ceil(float(head.get("shoot_days") or 0)))
        except (TypeError, ValueError):
            n = 0
        n = max(1, min(ODP_DAYS_MAX, n))
        places = []
        for s in dk_staff_days(p["sheet"], lg):
            k = int(min(ODP_PLACES_MAX, max(1, math.ceil(Decimal(str(s["people"] or 1))))))
            for i in range(1, k + 1):
                places.append({"key": f"d:{pk}:{s['uid']}:{i}", "name": (s["name"] or tr("Crew"))[:200]})
        title = " ".join((p["title"] or "").split())[:100] or tr("Shoot day")
        pt = " ".join((r["project_title"] or "").split())
        out.append({"key": f"d:{pk}", "title": (f"{pt} – {title}" if pt else title)[:200], "days": n,
                    "start": nxt.isoformat() if nxt else None, "places": places[:60]})
        if nxt:
            nxt = nxt + timedelta(days=n)
    return out


def _job_key(k):
    return ":".join(k.split(":")[:2])


def odp_chain(c, oid, root):
    """2.589.0 (review F1): SQL condition + args of the bookings of a quotation chain: its root, or any document of the chain
    (deleting the first quotation moves the chain to the oldest remaining version, office/docs.py odoc_unlink_refs, like the
    tasks' fallback in office/offertasks.py otk_links)."""
    ids = [x[0] for x in c.execute("SELECT id FROM office_docs WHERE org_id=? AND kind='offer' AND (id=? OR version_of=?)", (oid, root, root))]
    q = ",".join("?" * len(ids))
    return (f"(offer_root=? OR offer_doc IN ({q}))" if ids else "offer_root=?"), [root, *ids]


def odp_existing(c, oid, root):
    """{day key: [booking rows]} of the living bookings the chain root made."""
    out = {}
    w, wa = odp_chain(c, oid, root)
    for b in c.execute(f"SELECT * FROM hub_bookings WHERE org_id=? AND {w} AND deleted_at IS NULL ORDER BY id", (oid, *wa)):
        out.setdefault(_job_key(b["offer_pos"] or ""), []).append(dict(b))
    return out


def _span(bs):
    a = min(b["start"][:10] for b in bs)
    e = max(b["end"][:10] for b in bs)
    return a, (date.fromisoformat(e) - date.fromisoformat(a)).days + 1


def odp_preview(c, oid, uid, r, root):
    """The field dispo of the tasks preview: {on, hint, days: [{key, title, days, start, places, state new|same|changed|gone,
    pick, need_date, firm (firm bookings / filled places only marked), job}]}."""
    hint = odp_gate(c, uid, oid)
    want = odp_days(c, oid, r)
    if hint:
        return {"on": False, "hint": hint if want else "", "days": []}
    have = odp_existing(c, oid, root)
    w, wa = odp_chain(c, oid, root)
    dropped = {_job_key(k or "") for (k,) in c.execute(f"SELECT DISTINCT offer_pos FROM hub_bookings WHERE org_id=? AND {w} AND deleted_at IS NOT NULL", (oid, *wa))}
    out = []
    for d in want:
        bs = have.pop(d["key"], [])
        # a day deleted in the disposition is offered again, not ticked (like a deleted task, office/offertasks.py)
        x = dict(d, state="new", pick=bool(d["start"]) and d["key"] not in dropped, need_date=not d["start"], firm=0, job=None)
        if bs:
            a = _span(bs)[0]
            n = _span([b for b in bs if not b["offer_mark"]] or bs)[1]  # a marked booking is done: it does not count again
            want_keys = {p["key"] for p in d["places"]}
            same = n == d["days"] and {b["offer_pos"] for b in bs if b["offer_mark"] != "gone"} == want_keys \
                and (not d["start"] or d["start"] == a)  # 2.589.0 (review F2): a moved service period is a change too
            fixed = [b for b in bs if b["status"] == "firm" or (b["resource_kind"] != "slot" and b["offer_pos"] not in want_keys)]
            x.update(start=d["start"] or a, need_date=False, job=bs[0]["job"], state="same" if same else "changed", pick=not same, firm=0 if same else len(fixed))
        out.append(x)
    for k, bs in have.items():
        a, n = _span(bs)
        open_ = [b for b in bs if b["status"] == "option" and b["resource_kind"] == "slot"]
        if len(open_) == len(bs) or any(not b["offer_mark"] for b in bs):  # a gone day already marked everywhere is done
            out.append({"key": k, "title": bs[0]["title"], "days": n, "start": a, "places": [], "state": "gone", "pick": True,
                        "need_date": False, "firm": len(bs) - len(open_), "job": bs[0]["job"]})
    return {"on": True, "hint": "", "days": out}


def odp_dates_in(v):
    """{day key: 'YYYY-MM-DD'} from the request (anything else 400)."""
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise BadInput(tr("Invalid data"))
    out = {}
    for k, x in v.items():
        if x in (None, ""):
            continue
        d = _day(x) if isinstance(x, str) and len(x) == 10 else None
        if d is None:
            raise BadInput(tr("Invalid value: {0}", tr("Date")))
        out[str(k)] = d
    return out


def _insert(c, oid, uid, lid, r, root, job, title, a, e, place):
    return insert_id(c, "INSERT INTO hub_bookings(org_id,job,title,start,\"end\",resource_kind,resource_id,res_label,status,note,list_id,created_by,"
                        "created_at,updated_at,offer_root,offer_doc,offer_pos,offer_mark,slot_name) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (oid, job, title, a, e, "slot", 0, place["name"], "option", "", lid, uid, iso(now_utc()), iso(now_utc()),
                      root, r["id"], place["key"], "", place["name"]))


def odp_apply(c, oid, uid, r, root, lid, pick, dates):
    """Applies the ticked shoot days (keys of odp_preview) -> {booked: new bookings, adapted: changed / gone pencilled-in
    bookings, marked: bookings only marked}. The caller holds the chain's lock and commits."""
    pick = {k for k in pick if isinstance(k, str)}
    if not pick:
        return {"booked": 0, "adapted": 0, "marked": 0}
    hint = odp_gate(c, uid, oid)
    if hint:
        raise Denied(409, hint)
    pv = odp_preview(c, oid, uid, r, root)
    have = odp_existing(c, oid, root)
    ts = iso(now_utc())
    admin = abs_admin(c, uid, oid)
    # like the disposition (hub/dispo.py _may_change): other people's bookings change only by an admin; a member's update marks them
    loose = lambda b: b["status"] == "option" and (admin or b["created_by"] == uid)  # noqa: E731
    n_new = n_upd = n_mark = 0

    def mark(b, why):
        nonlocal n_mark
        if b["offer_mark"] != why:
            c.execute("UPDATE hub_bookings SET offer_mark=?, offer_doc=?, updated_at=? WHERE id=?", (why, r["id"], ts, b["id"]))
            n_mark += 1

    def drop(b):
        nonlocal n_upd
        # 2.589.0 (review F3): only while it is still an open pencilled-in place - filled meanwhile (dsp_fill) = marked instead
        if c.execute("UPDATE hub_bookings SET deleted_at=? WHERE id=? AND resource_kind='slot' AND status='option' AND deleted_at IS NULL",
                     (ts, b["id"])).rowcount:
            n_upd += 1
        else:
            mark(b, "gone")

    for d in pv["days"]:
        if d["key"] not in pick or d["state"] == "same":
            continue
        bs = have.get(d["key"], [])
        if d["state"] == "gone":
            for b in bs:
                if loose(b) and b["resource_kind"] == "slot":
                    drop(b)
                else:
                    mark(b, "gone")
            continue
        start = dates.get(d["key"]) or _day(d["start"])
        if start is None:
            raise BadInput(tr("Please select the date of the shoot day “{0}”", d["title"]))
        a, e = start.isoformat(), (start + timedelta(days=d["days"] - 1)).isoformat()
        if d["state"] == "new":
            job = secrets.token_hex(8)
            for p in d["places"]:
                _insert(c, oid, uid, lid, r, root, job, d["title"], a, e, p)
                n_new += 1
            continue
        keys = {p["key"] for p in d["places"]}
        mine = {b["offer_pos"] for b in bs}
        for b in bs:
            if b["offer_pos"] not in keys:
                if loose(b) and b["resource_kind"] == "slot":
                    drop(b)
                else:
                    mark(b, "gone")
            elif b["offer_mark"] == "gone" and loose(b):  # its function is in the quotation again: the mark goes
                c.execute("UPDATE hub_bookings SET offer_mark='', offer_doc=?, updated_at=? WHERE id=?", (r["id"], ts, b["id"]))
                n_upd += 1
            elif not loose(b):  # firm (or someone else's for a member): stays, only marked
                if (b["start"][:10], b["end"][:10]) != (a, e):
                    mark(b, "changed")
            elif (b["start"], b["end"]) != (a, e):  # a pencilled-in one (filled or not) follows the quotation's period
                c.execute("UPDATE hub_bookings SET start=?, \"end\"=?, offer_doc=?, updated_at=? WHERE id=?", (a, e, r["id"], ts, b["id"]))
                n_upd += 1
        for p in d["places"]:
            if p["key"] not in mine:
                _insert(c, oid, uid, lid, r, root, d["job"], bs[0]["title"] if bs else d["title"], a, e, p)
                n_new += 1
    w, wa = odp_chain(c, oid, root)
    c.execute(f"UPDATE hub_bookings SET offer_doc=?, offer_root=? WHERE org_id=? AND {w} AND deleted_at IS NULL", (r["id"], root, oid, *wa))
    return {"booked": n_new, "adapted": n_upd, "marked": n_mark}
