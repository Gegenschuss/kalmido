"""2.589.0 (#4571): shoot days from a quotation as pencilled-in bookings of the disposition (decision of 04.11.2026).

Taking a quotation into a project (office/offertasks.py, #3433: GET / POST /api/office/docs/<did>/tasks) makes every shoot
part of it one shoot day of the disposition (hub/dispo.py: one job, status option, list_id = the project) with one open place
per person a crew function needs (resource_kind 'slot', resource_id 0, slot_name = the function; filled in the disposition,
POST /api/team/dispo/bookings/<id>/fill). The period: the shoot days of the part's sheet (head shoot_days, at least one whole
day; travel and prep days are no shoot days), starting on the quotation's period of service (service_from), the next shoot
part right after the one before; without a date the preview asks for one.
2.1158.0 (#4566 A): the devices of the part's equipment set (its sheet's set.items: equipment_id, qty) come along as
pencilled-in bookings of the same shoot day (resource_kind 'equipment', resource_id = the device, status option, one booking
per device with the quantity in hub_bookings.qty, offer_pos "d:<part>:g:<device>"); the call sheet of the day shows them as
its packing list (hub/callsheet.py cs_pack). A device double booked in the period is a warning, like any booking of the
disposition (hub/dispo.py dsp_conflicts), never a block. Only where the person may see the equipment area (office/rights.py
ofr_allows 'equipment', like the disposition's resources); otherwise the devices are left out and the preview says so. A row
whose device is no longer in the master data (deleted, archived) is booked as nothing: the packing list shows it as a text line.
A new version adapts the devices like the places: a pencilled-in one follows period and quantity, one no longer in the
quotation goes (Undo restores it), a firm one is only marked.
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

from ..accounts.onboarding import inds_of_area  # 2.828.0 (#5511): the set
from ..accounts.orgroles import org_writes
from ..core.access import Denied, acx_org_ok, live_sql, need_feat  # 2.1005.0 (#5415): live_sql
from ..core.db import iso, now_utc
from ..core.errors import BadInput
from ..core.i18n import tr
from ..core.pg import insert_id
from ..hub.absence import abs_admin, abs_org
from ..hub.dispo import dsp_conflicts  # 2.1158.0 (#4566 A): the double booking warning of the devices
from .calc import calc_lang
from .docs import doc_items
from .parts import tp_parts
from .sheet import dk_staff_days
from .rights import ofr_allows  # 2.1158.0 (#4566 A): the devices only with the equipment area

ODP_PLACES_MAX = 20  # open places of one crew function
ODP_DAYS_MAX = 31    # shoot days of one part (the disposition takes 62 per booking)
ODP_GEAR_MAX = 60    # 2.1158.0 (#4566 A): devices of one shoot day (the disposition takes 60 resources per booking)
ODP_QTY_MAX = 1000   # the quantity of one device (the sheet's limit)


def odp_gate(c, uid, oid):
    """'' when uid may book shoot days in office area oid, else the hint the preview shows."""
    if "film" not in inds_of_area(c, oid):  # 2.828.0 (#5511): also with a second industry on
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


def _gear_name(it, lg):
    """The name of a row of the sheet's equipment set in the document's language (like dk_staff_days)."""
    if lg == "de":
        return str(it.get("name") or "")
    return str((it.get("name_tr") or {}).get(lg) or it.get("name_en") or it.get("name") or "")


def odp_gear(c, oid, sheet, pk, lg):
    """2.1158.0 (#4566 A): the equipment set of a shoot part's sheet -> (devices [{key, eid, name, category, qty}], text lines
    [{name, qty}]): a device of the master data (live, not archived) is booked; a row without one only goes on the packing list
    as text. One device twice in the set = one booking with the quantities added up; a quantity is whole pieces (rounded up)."""
    st = (sheet or {}).get("set") if isinstance((sheet or {}).get("set"), dict) else {}
    gear, loose = {}, []
    for it in (st.get("items") or [])[:200]:
        if not isinstance(it, dict):
            continue
        try:
            q = int(min(ODP_QTY_MAX, max(1, math.ceil(Decimal(str(it.get("qty") or 1))))))
        except (ArithmeticError, ValueError):
            q = 1
        e = None
        if str(it.get("equipment_id") or "").isdigit():
            e = c.execute(f"SELECT id, name, category FROM office_equipment WHERE id=? AND org_id=? AND NOT archived AND {live_sql()}",
                          (int(it["equipment_id"]), oid)).fetchone()
        if e is None:
            nm = " ".join(_gear_name(it, lg).split())[:200]
            if nm:
                loose.append({"name": nm, "qty": q})
            continue
        k = f"d:{pk}:g:{e['id']}"
        if k in gear:
            gear[k]["qty"] = min(ODP_QTY_MAX, gear[k]["qty"] + q)
        elif len(gear) < ODP_GEAR_MAX:
            gear[k] = {"key": k, "eid": e["id"], "name": (e["name"] or "?")[:200], "category": e["category"] or "", "qty": q}
    return list(gear.values()), loose


def odp_set_rows(c, oid, doc_id, pk, lg="de"):
    """2.1158.0 (#4566 A): (devices, text lines) of shoot part pk (its origin id) of quotation doc_id -- the call sheet's text
    lines of the packing list (hub/callsheet.py cs_pack). ([], []) when the part is not there."""
    for p in tp_parts(c, oid, doc_id):
        if p["kind"] == "shoot" and str(p.get("origin_id") or p["id"]) == str(pk):
            return odp_gear(c, oid, p["sheet"], pk, lg)
    return [], []


def odp_days(c, oid, r, gear_ok=True):
    """The shoot days quotation r asks for: [{key, title, days, start (ISO or None), places: [{key, name}]}] in the print order.
    2.1158.0 (#4566 A): + gear [{key, eid, name, category, qty}] (empty without gear_ok: the equipment area), loose (the rows
    without a device of the master data, text only), gear_off (devices left out for lack of the equipment area)."""
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
        gear, loose = odp_gear(c, oid, p["sheet"], pk, lg)  # 2.1158.0 (#4566 A)
        out.append({"key": f"d:{pk}", "title": (f"{pt} – {title}" if pt else title)[:200], "days": n,
                    "start": nxt.isoformat() if nxt else None, "places": places[:60],
                    "gear": gear if gear_ok else [], "loose": loose, "gear_off": 0 if gear_ok else len(gear)})
        if nxt:
            nxt = nxt + timedelta(days=n)
    return out


def _job_key(k):
    return ":".join(k.split(":")[:2])


def odp_chain(c, oid, root):
    """2.589.0 (review F1): SQL condition + args of the bookings of a quotation chain: its root, or any document of the chain
    (deleting the first quotation moves the chain to the oldest remaining version, office/docs.py odoc_unlink_refs, like the
    tasks' fallback in office/offertasks.py otk_links)."""
    ids = [x[0] for x in c.execute(f"SELECT id FROM office_docs WHERE org_id=? AND kind='offer' AND (id=? OR version_of=?) AND {live_sql()}", (oid, root, root))]  # 2.1005.0 (#5415): not the trash
    q = ",".join("?" * len(ids))
    return (f"(offer_root=? OR offer_doc IN ({q}))" if ids else "offer_root=?"), [root, *ids]


def odp_existing(c, oid, root):
    """{day key: [booking rows]} of the living bookings the chain root made."""
    out = {}
    w, wa = odp_chain(c, oid, root)
    for b in c.execute(f"SELECT * FROM hub_bookings WHERE org_id=? AND {w} AND deleted_at IS NULL ORDER BY id", (oid, *wa)):
        out.setdefault(_job_key(b["offer_pos"] or ""), []).append(dict(b))
    return out


def _is_gear(b):
    """2.1158.0 (#4566 A): a device booking a quotation made (offer_pos d:<part>:g:<device>)."""
    return b["resource_kind"] == "equipment" and ":g:" in (b["offer_pos"] or "")


def _loose_ok(b):
    """What a newer version may delete (when pencilled in): an open place, a device from the quotation."""
    return b["resource_kind"] == "slot" or _is_gear(b)


def _have(c, oid, root, gear_ok):
    """odp_existing; 2.1158.0 (#4566 A): without the equipment area the devices of the chain are out of reach -- neither
    compared nor adapted nor deleted (someone with the area made them; they stay as they are)."""
    have = odp_existing(c, oid, root)
    if gear_ok:
        return have
    return {k: v for k, v in ((k, [b for b in bs if not _is_gear(b)]) for k, bs in have.items()) if v}


def _gear_busy(c, oid, d, own):
    """2.1158.0 (#4566 A): the devices of day d with the period d['start'] .. + days: {key: other bookings holding it then}
    (hub/dispo.py dsp_conflicts, the warning of the disposition; the day's own bookings own (ids) do not count)."""
    if not d.get("gear") or not d.get("start"):
        return {}
    a = date.fromisoformat(d["start"])
    e = a + timedelta(days=d["days"] - 1)
    rows = [{"id": None, "start": a.isoformat(), "end": e.isoformat(), "resource_kind": "equipment", "resource_id": g["eid"], "key": g["key"]}
            for g in d["gear"]]
    conf = {}
    for x in rows:
        dbl = [i for i in dsp_conflicts(c, oid, [x], a, e).get(None, {}).get("double", []) if i not in own]
        if dbl:
            conf[x["key"]] = len(dbl)
    return conf


def _span(bs):
    a = min(b["start"][:10] for b in bs)
    e = max(b["end"][:10] for b in bs)
    return a, (date.fromisoformat(e) - date.fromisoformat(a)).days + 1


def odp_preview(c, oid, uid, r, root):
    """The field dispo of the tasks preview: {on, hint, days: [{key, title, days, start, places, state new|same|changed|gone,
    pick, need_date, firm (firm bookings / filled places only marked), job}]}."""
    hint = odp_gate(c, uid, oid)
    gear_ok = not hint and ofr_allows(c, uid, oid, "equipment")
    want = odp_days(c, oid, r, gear_ok=gear_ok)
    if hint:
        return {"on": False, "hint": hint if want else "", "days": []}
    have = _have(c, oid, root, gear_ok)
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
            want_keys = {p["key"] for p in d["places"]} | {g["key"] for g in d["gear"]}  # 2.1158.0 (#4566 A): + the devices
            qty = {g["key"]: g["qty"] for g in d["gear"]}
            same = n == d["days"] and {b["offer_pos"] for b in bs if b["offer_mark"] != "gone"} == want_keys \
                and (not d["start"] or d["start"] == a) \
                and all(b.get("qty", 1) == qty[b["offer_pos"]] for b in bs if _is_gear(b) and b["offer_pos"] in qty)
            # 2.589.0 (review F2): a moved service period is a change too; 2.1158.0 (#4566 A): a device's quantity as well
            fixed = [b for b in bs if b["status"] == "firm" or (not _loose_ok(b) and b["offer_pos"] not in want_keys)]
            x.update(start=d["start"] or a, need_date=False, job=bs[0]["job"], state="same" if same else "changed", pick=not same, firm=0 if same else len(fixed))
        busy = _gear_busy(c, oid, x, {b["id"] for b in bs})  # 2.1158.0 (#4566 A): the double booking warning of the devices
        x["gear"] = [dict(g, busy=busy.get(g["key"], 0)) for g in x["gear"]]
        out.append(x)
    for k, bs in have.items():
        a, n = _span(bs)
        open_ = [b for b in bs if b["status"] == "option" and _loose_ok(b)]
        if len(open_) == len(bs) or any(not b["offer_mark"] for b in bs):  # a gone day already marked everywhere is done
            out.append({"key": k, "title": bs[0]["title"], "days": n, "start": a, "places": [], "gear": [], "loose": [], "gear_off": 0, "state": "gone", "pick": True,
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
    """An open place {key, name} or (2.1158.0, #4566 A) a device {key, eid, name, qty} of the shoot day, pencilled in."""
    kind, rid, slot = ("equipment", place["eid"], "") if "eid" in place else ("slot", 0, place["name"])
    return insert_id(c, "INSERT INTO hub_bookings(org_id,job,title,start,\"end\",resource_kind,resource_id,res_label,status,note,list_id,created_by,"
                        "created_at,updated_at,offer_root,offer_doc,offer_pos,offer_mark,slot_name,qty) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (oid, job, title, a, e, kind, rid, place["name"], "option", "", lid, uid, iso(now_utc()), iso(now_utc()),
                      root, r["id"], place["key"], "", slot, int(place.get("qty") or 1)))


def odp_apply(c, oid, uid, r, root, lid, pick, dates):
    """Applies the ticked shoot days (keys of odp_preview) -> {booked: new bookings, adapted: changed / gone pencilled-in
    bookings, marked: bookings only marked}. The caller holds the chain's lock and commits.
    2.1158.0 (#4566 A): + gear (of booked: the devices), warnings (devices double booked in their period, never a block)."""
    pick = {k for k in pick if isinstance(k, str)}
    if not pick:
        return {"booked": 0, "adapted": 0, "marked": 0, "gear": 0, "warnings": 0}
    hint = odp_gate(c, uid, oid)
    if hint:
        raise Denied(409, hint)
    pv = odp_preview(c, oid, uid, r, root)
    have = _have(c, oid, root, ofr_allows(c, uid, oid, "equipment"))
    ts = iso(now_utc())
    admin = abs_admin(c, uid, oid)
    # like the disposition (hub/dispo.py _may_change): other people's bookings change only by an admin; a member's update marks them
    loose = lambda b: b["status"] == "option" and (admin or b["created_by"] == uid)  # noqa: E731
    n_new = n_upd = n_mark = n_gear = 0
    made = []  # 2.1158.0 (#4566 A): the devices booked or moved, for the double booking warning

    def mark(b, why):
        nonlocal n_mark
        if b["offer_mark"] != why:
            c.execute("UPDATE hub_bookings SET offer_mark=?, offer_doc=?, updated_at=? WHERE id=?", (why, r["id"], ts, b["id"]))
            n_mark += 1

    def drop(b):
        nonlocal n_upd
        # 2.589.0 (review F3): only while it is still an open pencilled-in place - filled meanwhile (dsp_fill) = marked instead;
        # 2.1158.0 (#4566 A): or a pencilled-in device from the quotation
        if c.execute("UPDATE hub_bookings SET deleted_at=? WHERE id=? AND (resource_kind='slot' OR (resource_kind='equipment' AND offer_pos LIKE '%:g:%')) "
                     "AND status='option' AND deleted_at IS NULL", (ts, b["id"])).rowcount:
            n_upd += 1
        else:
            mark(b, "gone")

    for d in pv["days"]:
        if d["key"] not in pick or d["state"] == "same":
            continue
        bs = have.get(d["key"], [])
        if d["state"] == "gone":
            for b in bs:
                if loose(b) and _loose_ok(b):
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
            for p in d["places"] + d["gear"]:
                bid = _insert(c, oid, uid, lid, r, root, job, d["title"], a, e, p)
                n_new += 1
                if "eid" in p:
                    made.append(bid)
                    n_gear += 1
            continue
        keys = {p["key"] for p in d["places"]} | {g["key"] for g in d["gear"]}
        qty = {g["key"]: g["qty"] for g in d["gear"]}
        mine = {b["offer_pos"] for b in bs}
        for b in bs:
            q = qty.get(b["offer_pos"]) if _is_gear(b) else None  # 2.1158.0 (#4566 A): the quantity a device follows
            if b["offer_pos"] not in keys:
                if loose(b) and _loose_ok(b):
                    drop(b)
                else:
                    mark(b, "gone")
            elif b["offer_mark"] == "gone" and loose(b):  # its function is in the quotation again: the mark goes
                c.execute("UPDATE hub_bookings SET offer_mark='', offer_doc=?, updated_at=? WHERE id=?", (r["id"], ts, b["id"]))
                n_upd += 1
            elif not loose(b):  # firm (or someone else's for a member): stays, only marked
                if (b["start"][:10], b["end"][:10]) != (a, e) or (q is not None and b.get("qty", 1) != q):
                    mark(b, "changed")
            elif (b["start"], b["end"]) != (a, e) or (q is not None and b.get("qty", 1) != q):
                # a pencilled-in one (filled or not) follows the quotation's period (a device: and its quantity)
                c.execute("UPDATE hub_bookings SET start=?, \"end\"=?, qty=?, offer_doc=?, updated_at=? WHERE id=?",
                          (a, e, q if q is not None else b.get("qty", 1), r["id"], ts, b["id"]))
                n_upd += 1
                if q is not None:
                    made.append(b["id"])
        for p in d["places"] + d["gear"]:
            if p["key"] not in mine:
                bid = _insert(c, oid, uid, lid, r, root, d["job"], bs[0]["title"] if bs else d["title"], a, e, p)
                n_new += 1
                if "eid" in p:
                    made.append(bid)
                    n_gear += 1
    w, wa = odp_chain(c, oid, root)
    c.execute(f"UPDATE hub_bookings SET offer_doc=?, offer_root=? WHERE org_id=? AND {w} AND deleted_at IS NULL", (r["id"], root, oid, *wa))
    return {"booked": n_new, "adapted": n_upd, "marked": n_mark, "gear": n_gear, "warnings": _warned(c, oid, made)}


def _warned(c, oid, ids):
    """2.1158.0 (#4566 A): how many of the device bookings ids are double booked now (hub/dispo.py dsp_conflicts)."""
    rows = [dict(x) for x in c.execute(f"SELECT * FROM hub_bookings WHERE id IN ({','.join('?' * len(ids))})", ids)] if ids else []
    if not rows:
        return 0
    a = min(date.fromisoformat(x["start"][:10]) for x in rows)
    e = max(date.fromisoformat(x["end"][:10]) for x in rows)
    conf = dsp_conflicts(c, oid, rows, a, e)
    return sum(1 for x in rows if conf.get(x["id"], {}).get("double"))
