"""2.93.0 B (#1928): the logbook: vehicles, drives, change log, year report, mileage allowance into the EUeR (filled by part B).

Vehicles (office_vehicles: name, plate, kind private = a private car used for business -> mileage allowance | company = a
company car, its costs come through receipts; odometer at the start; archived instead of deleted). Drives (office_drives:
day, start, destination, purpose, km or the odometer at start / end -> km, kind business | private | commute, client /
project like the travel expenses, driver). Every create / change / delete / restore writes office_drive_log with the values
before (JSON, encrypted at rest); a delete only sets deleted_at (the undo restores it), nothing is ever deleted for real.
A gap / an overlap to the odometer of the previous drive of the vehicle is a warning, never blocks. A business drive can be
taken over into the travel expenses once (a trip with day, destination, purpose job, client, project, km -- no receipt, so
the EUeR counts nothing twice). The year report per vehicle (km total / business / private / commute, business share,
mileage allowance with the rate of the office settings km_rate, default 0.30) also as CSV and PDF with the change log.
lb_allowance_year feeds the EUeR line "Mileage allowance" (books.bk_euer).

Every route: office_gate + office_org with the admin of the office area (like the travel expenses; members get 403, agents
and kids 403, ids of other areas 404); a person without an organisation is the admin of the personal office."""
import csv
import io
import json
import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request, Response

from ..core.config import app
from ..core.pg import insert_id, write_lock
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields
from ..core.i18n import N_, lang, tr
from ..core.db import body, bump, db, iso, now_utc
from ..core.access import Denied
from ..personal.timetrack import BadInput
from .calc import dec, dstr, money
from .model import ofx_name1, office_gate, office_org, office_settings, office_settings_save

LB_VEH_KINDS = ("private", "company")
LB_KINDS = (("business", N_("Business")), ("private", N_("Private|drive")), ("commute", N_("Home - workplace")))
LB_KIND_KEYS = tuple(k for k, _ in LB_KINDS)
LB_RATE = "0.30"
LB_NOTE = N_("The tax office only accepts a logbook kept promptly and without gaps, with date, odometer, destination, purpose and client; later changes are logged here. No tax advice.")  # noqa: E501
LB_FIELDS = ("vehicle_id", "user_id", "day", "start_place", "dest", "purpose", "km", "odo_start", "odo_end", "kind", "client_id", "project")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_KM = Decimal(10 ** 6)
MAX_ODO = Decimal(10 ** 9)
MAX_VEHICLES = 100


def _ctx():
    """Admins of the office area only (like the travel expenses)."""
    c = db()
    uid = office_gate(c)
    return c, uid, office_org(c, uid, admin=True)


def _body():
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    return b


def _text(v, name, mx=300):
    if v is None:
        return ""
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", name))
    return CTRL_RE.sub("", v).strip()[:mx]


def _day(v, name="day"):
    if isinstance(v, str) and DATE_RE.match(v.strip()):
        try:
            return date.fromisoformat(v.strip()).isoformat()
        except ValueError:
            pass
    raise BadInput(tr("Invalid value: {0}", name))


def _num(v, name, hi, allow_none=True):
    """A non-negative number with one decimal (km) or None."""
    if v in (None, ""):
        if allow_none:
            return None
        raise BadInput(tr("Invalid value: {0}", name))
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise BadInput(tr("Invalid value: {0}", name))
    try:
        d = dec(v, "NaN")
    except Exception:
        raise BadInput(tr("Invalid value: {0}", name))
    if d.is_nan() or not d.is_finite() or d < 0 or d > hi:
        raise BadInput(tr("Invalid value: {0}", name))
    return d.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _year(v):
    from .books import _year as bk_year
    return bk_year(v)


def _id(v, name):
    if v in (None, ""):
        return None
    if isinstance(v, bool):
        raise BadInput(tr("Invalid value: {0}", name))
    try:
        return int(v)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", name))


def _km_str(v):
    return None if v is None else format(dec(v).quantize(Decimal("0.1")), "f")


def lb_rate(c, oid, year=None):
    """The mileage allowance per business km of the office area (text, two decimals): the rate of the year (km_rates), else
    the default km_rate. 2.93.0 B (#1928 review): per year, so a new rate never changes the allowance of earlier years."""
    s = office_settings(c, oid)
    rates = s.get("km_rates") if isinstance(s.get("km_rates"), dict) else {}
    v = rates.get(str(year)) if year is not None else None
    if v in (None, ""):
        v = s.get("km_rate")
    try:
        d = dec(v or LB_RATE, "NaN")
    except Exception:
        d = dec(LB_RATE)
    if d.is_nan() or d < 0:
        d = dec(LB_RATE)
    return format(d.quantize(Decimal("0.01")), "f")


def _veh_log(c, oid, action, vid, before, after):
    """2.93.0 B (#1928 review): a new or changed vehicle into the office log (kind / start odometer change the allowance)."""
    from .ledger import ofx_diff, ofx_log
    diff = ofx_diff(before or {}, after)
    if diff["after"]:
        ofx_log(c, oid, action, target="vehicle", detail={"vehicle_id": vid, **diff})


# ---------------------------------------------------------------- vehicles
def _vehicle(c, oid, vid):
    r = c.execute("SELECT * FROM office_vehicles WHERE id=? AND org_id=?", (vid, oid)).fetchone()
    if not r:
        raise Denied(404)
    return r


def lb_vehicles(c, oid):
    """Every vehicle of the area (archived ones too), with last_odo = the odometer to start the next drive with."""
    last = {r["vehicle_id"]: r["m"] for r in c.execute(
        "SELECT vehicle_id, MAX(odo_end) AS m FROM office_drives WHERE org_id=? AND deleted_at IS NULL AND odo_end IS NOT NULL "
        "GROUP BY vehicle_id", (oid,))}
    out = []
    for r in c.execute("SELECT * FROM office_vehicles WHERE org_id=? ORDER BY archived, lower(name), id", (oid,)):
        d = oc_dec_fields(c, oid, "office_vehicles", r)
        lo = last.get(d["id"])
        if lo is None:
            lo = d.get("odo_start")
        out.append({"id": d["id"], "name": d["name"], "plate": d.get("plate") or "", "kind": d["kind"], "odo_start": _km_str(d.get("odo_start")),
                    "archived": d["archived"], "last_odo": _km_str(lo)})
    return out


def _vehicle_clean(b, cur=None):
    out = {}
    if "name" in b or cur is None:
        out["name"] = _text(b.get("name"), "name", 120)
        if not out["name"]:
            raise BadInput(tr("Please enter a name"))
    if "plate" in b or cur is None:
        out["plate"] = _text(b.get("plate"), "plate", 30)
    if "kind" in b or cur is None:
        k = b.get("kind") or "private"
        if k not in LB_VEH_KINDS:
            raise BadInput(tr("Invalid value: {0}", "kind"))
        out["kind"] = k
    if "odo_start" in b or cur is None:
        o = _num(b.get("odo_start"), "odo_start", MAX_ODO)
        out["odo_start"] = float(o) if o is not None else None
    if "archived" in b and cur is not None:
        out["archived"] = 1 if b.get("archived") else 0
    return out


LB_VEH_LOG = ("name", "plate", "kind", "odo_start", "archived")


def _veh_vals(v):
    return {k: v[k] for k in LB_VEH_LOG if k in v}


@app.get("/api/office/vehicles")
def lb_vehicles_get():
    """-> {vehicles, people, clients, projects, km_rate, currency, kinds}: what the logbook view needs to start."""
    from .travel import rk_cl_where, rk_home_cur, rk_people
    c, uid, oid = _ctx()
    w, wa = rk_cl_where(c, oid)
    clients = [{"id": r["id"], "name": r["name"]} for r in c.execute(f"SELECT id, name FROM clients WHERE {w} AND archived=0 ORDER BY lower(name)", wa)]
    projects = [r[0] for r in c.execute("SELECT DISTINCT project_title FROM office_docs WHERE org_id=? AND project_title<>'' ORDER BY 1", (oid,))][:300]
    return jsonify(vehicles=lb_vehicles(c, oid), people=rk_people(c, oid, uid), clients=clients, projects=projects, km_rate=lb_rate(c, oid, _year(None)),
                   currency=rk_home_cur(c, oid), me=uid, kinds=[{"key": k, "label": tr(n)} for k, n in LB_KINDS], note=tr(LB_NOTE))


@app.post("/api/office/vehicles")
def lb_vehicle_post():
    """A new vehicle {name, plate, kind private|company, odo_start}. 201 the vehicle."""
    c, uid, oid = _ctx()
    row = _vehicle_clean(_body())
    if c.execute("SELECT COUNT(*) FROM office_vehicles WHERE org_id=?", (oid,)).fetchone()[0] >= MAX_VEHICLES:
        raise BadInput(tr("Too many entries"))
    ts = iso(now_utc())
    row.update(org_id=oid, created_by=uid, created_at=ts, updated_at=ts)
    row = oc_enc_fields(c, oid, "office_vehicles", row)
    vid = insert_id(c, f"INSERT INTO office_vehicles({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    _veh_log(c, oid, "create", vid, None, {k: v for k, v in _veh_vals(next(v for v in lb_vehicles(c, oid) if v["id"] == vid)).items() if k != "archived"})
    bump(c)
    c.commit()
    return jsonify(next(v for v in lb_vehicles(c, oid) if v["id"] == vid)), 201


@app.patch("/api/office/vehicles/<int:vid>")
def lb_vehicle_patch(vid):
    """Partial {name, plate, kind, odo_start, archived 0|1} (archived = the undo-able "delete")."""
    c, uid, oid = _ctx()
    cur = _vehicle(c, oid, vid)
    row = _vehicle_clean(_body(), cur)
    if row:
        before = _veh_vals(next(v for v in lb_vehicles(c, oid) if v["id"] == vid))
        after = dict(before, **_veh_vals(dict(row, odo_start=_km_str(row["odo_start"]) if "odo_start" in row else before["odo_start"])))
        _veh_log(c, oid, "update", vid, before, after)
        row["updated_at"] = iso(now_utc())
        row = oc_enc_fields(c, oid, "office_vehicles", row)
        c.execute(f"UPDATE office_vehicles SET {','.join(k + '=?' for k in row)} WHERE id=? AND org_id=?", list(row.values()) + [vid, oid])
        bump(c)
        c.commit()
    return jsonify(next(v for v in lb_vehicles(c, oid) if v["id"] == vid))


# ---------------------------------------------------------------- drives
def _drive(c, oid, did, deleted=False):
    r = c.execute("SELECT * FROM office_drives WHERE id=? AND org_id=?", (did, oid)).fetchone()
    if not r or (bool(r["deleted_at"]) != deleted):
        raise Denied(404)
    return r


def _vals(d):
    """The logged values of a decrypted drive row (JSON-safe)."""
    out = {}
    for k in LB_FIELDS:
        v = d.get(k)
        out[k] = _km_str(v) if k in ("km", "odo_start", "odo_end") else v
    return out


def _log(c, oid, did, action, prev, uid):
    row = oc_enc_fields(c, oid, "office_drive_log", {"org_id": oid, "drive_id": did, "action": action,
                                                     "prev": json.dumps(prev, ensure_ascii=False), "by_user": uid, "at": iso(now_utc())})
    c.execute(f"INSERT INTO office_drive_log({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))


def _drive_clean(c, oid, uid, b, cur=None):
    """The columns of a drive from body b (partial when cur, the decrypted row, is given). km from the odometer when both
    ends are given and km is not; the end never before the start."""
    from .travel import _client_ok, rk_people
    new = cur is None
    cur = cur or {}
    out = {}
    if "vehicle_id" in b or new:
        vid = _id(b.get("vehicle_id"), "vehicle_id")
        if vid is not None:
            _vehicle(c, oid, vid)  # 404 for a vehicle of another area
        out["vehicle_id"] = vid
    if "user_id" in b or new:
        u = _id(b.get("user_id"), "user_id") or uid
        if u != cur.get("user_id") and u not in {p["id"] for p in rk_people(c, oid, uid)}:
            raise BadInput(tr("Invalid value: {0}", "user_id"))
        out["user_id"] = u
    if "day" in b or new:
        out["day"] = _day(b.get("day"))
    for k, mx in (("start_place", 300), ("dest", 300), ("purpose", 500), ("project", 200)):
        if k in b or new:
            out[k] = _text(b.get(k), k, mx)
    if "kind" in b or new:
        k = b.get("kind") or "business"
        if k not in LB_KIND_KEYS:
            raise BadInput(tr("Invalid value: {0}", "kind"))
        out["kind"] = k
    if "client_id" in b or new:
        out["client_id"] = _client_ok(c, oid, b.get("client_id"))
    odo = {}
    for k in ("odo_start", "odo_end"):
        if k in b or new:
            odo[k] = _num(b.get(k), k, MAX_ODO)
        else:
            odo[k] = dec(cur[k]) if cur.get(k) is not None else None
    s, e = odo["odo_start"], odo["odo_end"]
    if s is not None and e is not None and e < s:
        raise BadInput(tr("The odometer at the end is below the start"))
    km = None
    if "km" in b or new:
        km = _num(b.get("km"), "km", MAX_KM)
    touched = any(k in b for k in ("odo_start", "odo_end")) or new
    if km is None and s is not None and e is not None and (touched or "km" in b):
        km = e - s
    if km is not None and km > MAX_KM:
        raise BadInput(tr("Invalid value: {0}", "km"))
    if "km" in b or new or (touched and km is not None):
        out["km"] = float(km if km is not None else 0)
    for k in ("odo_start", "odo_end"):
        if k in b or new:
            out[k] = float(odo[k]) if odo[k] is not None else None
    return out


def _warns(c, oid, vid):
    """{drive id: {"kind": "gap"|"overlap", "km": text}} -- the odometer at the start of a drive against the end of the
    previous drive of the vehicle (by day; drives without odometer are skipped). A warning, never a block."""
    if not vid:
        return {}
    out, prev = {}, None
    for r in c.execute("SELECT id, odo_start, odo_end FROM office_drives WHERE org_id=? AND vehicle_id=? AND deleted_at IS NULL "
                       "AND (odo_start IS NOT NULL OR odo_end IS NOT NULL) ORDER BY day, COALESCE(odo_start, odo_end), id", (oid, vid)):
        s = dec(r["odo_start"]) if r["odo_start"] is not None else None
        if s is not None and prev is not None and s != prev:
            out[r["id"]] = {"kind": "gap" if s > prev else "overlap", "km": _km_str(abs(s - prev))}
        if r["odo_end"] is not None:
            prev = dec(r["odo_end"])
    return out


def lb_drive_public(c, oid, r, names=None, warns=None, trips=None):
    d = oc_dec_fields(c, oid, "office_drives", r)
    out = _vals(d)
    tid = d.get("trip_id")
    if tid and trips is not None and tid not in trips:
        tid = None
    # 2.93.0 B (#1928 review): the trip keeps its km when the drive changes later -> a hint, never changed on its own
    tkm = _km_str((trips or {}).get(tid)) if tid and isinstance(trips, dict) else None
    hint = tr("The trip in the travel expenses still has {0} km.", tkm if lang() == "en" else _de(tkm)) if tkm is not None and tkm != out["km"] else ""
    out.update(id=d["id"], trip_id=tid, trip_km=tkm, trip_hint=hint, driver=(names or {}).get(d.get("user_id")) or "", deleted=bool(d.get("deleted_at")),
               warn=(warns or {}).get(d["id"]), created_at=d["created_at"], updated_at=d["updated_at"])
    return out


def _names(c, oid, uid):
    from .travel import rk_people
    n = {p["id"]: p["name"] for p in rk_people(c, oid, uid)}
    return n


def lb_drives(c, oid, uid, vehicle_id=None, year=None, deleted=False):
    sql, args = "SELECT * FROM office_drives WHERE org_id=?", [oid]
    sql += " AND deleted_at IS NOT NULL" if deleted else " AND deleted_at IS NULL"
    if vehicle_id is not None:
        sql += " AND vehicle_id=?"
        args.append(vehicle_id)
    if year:
        sql += " AND substr(day, 1, 4)=?"
        args.append(str(year))
    rows = c.execute(sql + " ORDER BY day DESC, COALESCE(odo_start, 0) DESC, id DESC", args).fetchall()
    names = _names(c, oid, uid)
    warns = {}
    for vid in {r["vehicle_id"] for r in rows if r["vehicle_id"]}:
        warns.update(_warns(c, oid, vid))
    trips = {r[0]: r[1] for r in c.execute("SELECT id, km FROM office_trips WHERE org_id=?", (oid,))}
    return [lb_drive_public(c, oid, r, names, warns, trips) for r in rows]


def _one(c, oid, uid, did):
    r = c.execute("SELECT * FROM office_drives WHERE id=? AND org_id=?", (did, oid)).fetchone()
    trips = {x[0]: x[1] for x in c.execute("SELECT id, km FROM office_trips WHERE org_id=?", (oid,))}
    return lb_drive_public(c, oid, r, _names(c, oid, uid), _warns(c, oid, r["vehicle_id"]), trips)


@app.get("/api/office/drives")
def lb_drives_get():
    """?vehicle_id=&year=YYYY -> {drives (newest first; warn = gap / overlap to the previous odometer), year}."""
    c, uid, oid = _ctx()
    vid = _id(request.args.get("vehicle_id"), "vehicle_id")
    if vid is not None:
        _vehicle(c, oid, vid)
    y = _year(request.args.get("year"))
    return jsonify(drives=lb_drives(c, oid, uid, vid, y), year=y)


@app.post("/api/office/drives")
def lb_drive_post():
    """A new drive {vehicle_id, day, start_place, dest, purpose, km | odo_start + odo_end, kind business|private|commute,
    client_id, project, user_id (driver, default: me)}. 201 the drive (warn: gap / overlap to the previous odometer)."""
    c, uid, oid = _ctx()
    row = _drive_clean(c, oid, uid, _body())
    ts = iso(now_utc())
    row.update(org_id=oid, created_by=uid, created_at=ts, updated_at=ts)
    plain = dict(row)
    row = oc_enc_fields(c, oid, "office_drives", row)
    did = insert_id(c, f"INSERT INTO office_drives({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    _log(c, oid, did, "create", _vals(plain), uid)  # create: the values entered
    bump(c)
    c.commit()
    return jsonify(_one(c, oid, uid, did)), 201


@app.patch("/api/office/drives/<int:did>")
def lb_drive_patch(did):
    """Partial drive (keys as POST); logs the values before of every changed field."""
    c, uid, oid = _ctx()
    cur = oc_dec_fields(c, oid, "office_drives", _drive(c, oid, did))
    row = _drive_clean(c, oid, uid, _body(), cur)
    before, after = _vals(cur), _vals(dict(cur, **row))
    prev = {k: before[k] for k in LB_FIELDS if before[k] != after[k]}
    if prev:
        row["updated_at"] = iso(now_utc())
        row = oc_enc_fields(c, oid, "office_drives", row)
        c.execute(f"UPDATE office_drives SET {','.join(k + '=?' for k in row)} WHERE id=? AND org_id=?", list(row.values()) + [did, oid])
        _log(c, oid, did, "change", prev, uid)
        bump(c)
        c.commit()
    return jsonify(_one(c, oid, uid, did))


@app.delete("/api/office/drives/<int:did>")
def lb_drive_delete(did):
    """Removes a drive (deleted_at; the row and its log stay; POST .../restore brings it back)."""
    c, uid, oid = _ctx()
    cur = oc_dec_fields(c, oid, "office_drives", _drive(c, oid, did))
    ts = iso(now_utc())
    c.execute("UPDATE office_drives SET deleted_at=?, updated_at=? WHERE id=? AND org_id=?", (ts, ts, did, oid))
    _log(c, oid, did, "delete", _vals(cur), uid)
    bump(c)
    c.commit()
    return jsonify(ok=True, id=did)


@app.post("/api/office/drives/<int:did>/restore")
def lb_drive_restore(did):
    c, uid, oid = _ctx()
    _drive(c, oid, did, deleted=True)
    c.execute("UPDATE office_drives SET deleted_at=NULL, updated_at=? WHERE id=? AND org_id=?", (iso(now_utc()), did, oid))
    _log(c, oid, did, "restore", {}, uid)
    bump(c)
    c.commit()
    return jsonify(_one(c, oid, uid, did))


def lb_log_rows(c, oid, drive_ids=None, year=None):
    """The change log [{id, drive_id, action, prev, by, at}] of some drives (or of the drives of a year), oldest first."""
    sql, args = ("SELECT l.*, u.display_name, u.username FROM office_drive_log l LEFT JOIN users u ON u.id=l.by_user "
                 "WHERE l.org_id=?"), [oid]
    if drive_ids is not None:
        if not drive_ids:
            return []
        sql += f" AND l.drive_id IN ({','.join('?' * len(drive_ids))})"
        args += list(drive_ids)
    if year:
        sql += " AND l.drive_id IN (SELECT id FROM office_drives WHERE org_id=? AND substr(day, 1, 4)=?)"
        args += [oid, str(year)]
    out = []
    for r in c.execute(sql + " ORDER BY l.at, l.id", args):
        d = oc_dec_fields(c, oid, "office_drive_log", r)
        try:
            prev = json.loads(d.get("prev") or "{}")
        except ValueError:
            prev = {}
        out.append({"id": d["id"], "drive_id": d["drive_id"], "action": d["action"], "prev": prev if isinstance(prev, dict) else {},
                    "by": d.get("display_name") or d.get("username") or "", "at": d["at"]})
    return out


@app.get("/api/office/drives/<int:did>/log")
def lb_drive_log(did):
    """The change log of one drive (deleted drives too), oldest first."""
    c, uid, oid = _ctx()
    if not c.execute("SELECT 1 FROM office_drives WHERE id=? AND org_id=?", (did, oid)).fetchone():
        raise Denied(404)
    return jsonify(log=lb_log_rows(c, oid, [did]))


@app.post("/api/office/drives/<int:did>/trip")
def lb_drive_trip(did):
    """Takes a business drive over into the travel expenses: a trip (day, destination, purpose job, client, project, km,
    the driver as participant; no receipt) -- once: taken over already = the existing trip (200, existing true)."""
    from .travel import _one as rk_one, rk_people, rk_trip_clean
    c, uid, oid = _ctx()
    write_lock(c, f"office_drive_trip_{oid}")
    d = oc_dec_fields(c, oid, "office_drives", _drive(c, oid, did))
    if d.get("trip_id") and c.execute("SELECT 1 FROM office_trips WHERE id=? AND org_id=?", (d["trip_id"], oid)).fetchone():
        return jsonify(trip=rk_one(c, oid, d["trip_id"]), existing=True)
    if d["kind"] != "business":
        raise BadInput(tr("Only business drives go into the travel expenses"))
    ppl = [{"id": d["user_id"]}] if d.get("user_id") in {p["id"] for p in rk_people(c, oid, uid)} else []
    # 2.93.0 B (#1928 review): office_trips.dest is plain text -> only the destination (like a trip typed by hand); start and
    # purpose go into the encrypted note
    note = "\n".join(x for x in (d.get("purpose"), f"{tr('Start')}: {d['start_place']}" if d.get("start_place") else "") if x)
    b = {"date_from": d["day"], "dest": d.get("dest") or "", "purpose": "job", "client_id": d.get("client_id"), "project": d.get("project") or "",
         "km": _km_str(d.get("km")), "note": note, "people": ppl}
    row = rk_trip_clean(c, oid, uid, b)
    ts = iso(now_utc())
    row.update(org_id=oid, created_by=uid, created_at=ts, updated_at=ts)
    row = oc_enc_fields(c, oid, "office_trips", row)
    tid = insert_id(c, f"INSERT INTO office_trips({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    c.execute("UPDATE office_drives SET trip_id=? WHERE id=? AND org_id=?", (tid, did, oid))
    _log(c, oid, did, "trip", {}, uid)  # 2.93.0 B (#1928 review): the takeover in the change log
    bump(c)
    c.commit()
    return jsonify(trip=rk_one(c, oid, tid), existing=False), 201


# ---------------------------------------------------------------- report, allowance, exports
def lb_allowance_year(c, oid, year):
    """The mileage allowance of a year for the EUeR: business, not deleted drives with a vehicle of the kind private
    -> {"km": Decimal, "amount": Decimal, "rate": "0.30", "count": int}. Drives without a vehicle do not count."""
    rate = lb_rate(c, oid, year)
    km, n = Decimal(0), 0
    for r in c.execute("SELECT d.km FROM office_drives d JOIN office_vehicles v ON v.id=d.vehicle_id AND v.org_id=d.org_id "
                       "WHERE d.org_id=? AND d.deleted_at IS NULL AND d.kind='business' AND v.kind='private' AND substr(d.day, 1, 4)=?",
                       (oid, str(year))):
        km += dec(r["km"] or 0)
        n += 1
    return {"km": km, "amount": money(km * dec(rate)), "rate": rate, "count": n}


def lb_report(c, oid, uid, year, vehicle_id=None):
    """The year per vehicle: km total / business / private / commute, business share (%), allowance (private cars)."""
    rate = dec(lb_rate(c, oid, year))
    vs = [v for v in lb_vehicles(c, oid) if vehicle_id is None or v["id"] == vehicle_id]
    sums = {v["id"]: {k: Decimal(0) for k in LB_KIND_KEYS} for v in vs}
    count = {v["id"]: 0 for v in vs}
    for r in c.execute("SELECT vehicle_id, kind, km FROM office_drives WHERE org_id=? AND deleted_at IS NULL AND substr(day, 1, 4)=?",
                       (oid, str(year))):
        if r["vehicle_id"] in sums and r["kind"] in LB_KIND_KEYS:
            sums[r["vehicle_id"]][r["kind"]] += dec(r["km"] or 0)
            count[r["vehicle_id"]] += 1
    out, total = [], Decimal(0)
    for v in vs:
        s = sums[v["id"]]
        if v["archived"] and not count[v["id"]]:
            continue
        all_km = sum(s.values(), Decimal(0))
        allow = money(s["business"] * rate) if v["kind"] == "private" else Decimal(0)
        total += allow
        out.append(dict(v, drives=count[v["id"]], km_total=_km_str(all_km), km_business=_km_str(s["business"]), km_private=_km_str(s["private"]),
                        km_commute=_km_str(s["commute"]),
                        business_pct=int((s["business"] * 100 / all_km).quantize(Decimal(1), rounding=ROUND_HALF_UP)) if all_km else 0,
                        allowance=dstr(allow)))
    return {"year": year, "km_rate": format(rate, "f"), "vehicles": out, "allowance": dstr(money(total)), "note": tr(LB_NOTE)}


def _vid_arg():
    return _id(request.args.get("vehicle_id"), "vehicle_id")


@app.get("/api/office/logbook/report")
def lb_report_get():
    """?year=YYYY&vehicle_id= -> the year report (see lb_report)."""
    c, uid, oid = _ctx()
    vid = _vid_arg()
    if vid is not None:
        _vehicle(c, oid, vid)
    return jsonify(lb_report(c, oid, uid, _year(request.args.get("year")), vid))


@app.put("/api/office/logbook/settings")
def lb_settings_put():
    """{km_rate: "0.30", year: YYYY} -> the rate per business km (0 .. 5, two decimals) of that year (default: this year) in the
    office settings (km_rates); logged in the office log with the rate before. -> {km_rate, year}."""
    from .ledger import ofx_log
    c, uid, oid = _ctx()
    b = _body()
    y = _year(b.get("year"))
    if "km_rate" in b:
        v = b.get("km_rate")
        if isinstance(v, str):
            v = v.strip().replace(",", ".")
        if isinstance(v, bool) or not isinstance(v, (int, float, str)) or v == "":
            raise BadInput(tr("Invalid value: {0}", "km_rate"))
        try:
            r = dec(v, "NaN")
        except Exception:
            raise BadInput(tr("Invalid value: {0}", "km_rate"))
        if r.is_nan() or not r.is_finite() or r < 0 or r > 5:
            raise BadInput(tr("Invalid value: {0}", "km_rate"))
        old, new = lb_rate(c, oid, y), format(r.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")
        s = office_settings(c, oid)
        rates = s.get("km_rates") if isinstance(s.get("km_rates"), dict) else {}
        s["km_rates"] = dict(rates, **{str(y): new})
        office_settings_save(c, oid, s)
        if old != new:
            ofx_log(c, oid, "update", target="km_rate", detail={"year": y, "before": {"km_rate": old}, "after": {"km_rate": new}})
        bump(c)
        c.commit()
    return jsonify(km_rate=lb_rate(c, oid, y), year=y)


def _kind_label(k):
    return tr(dict(LB_KINDS).get(k, "Business"))


def _export_data(c, oid, uid):
    vid = _vid_arg()
    if vid is not None:
        _vehicle(c, oid, vid)
    y = _year(request.args.get("year"))
    from .travel import rk_cl_where
    w, wa = rk_cl_where(c, oid)
    clients = {r["id"]: r["name"] for r in c.execute(f"SELECT id, name FROM clients WHERE {w}", wa)}
    vs = {v["id"]: v for v in lb_vehicles(c, oid)}
    drives = sorted(lb_drives(c, oid, uid, vid, y), key=lambda d: (d["day"], dec(d["odo_start"] or 0), d["id"]))
    ids = [d["id"] for d in drives] + [d["id"] for d in lb_drives(c, oid, uid, vid, y, deleted=True)]
    log = sorted(lb_log_rows(c, oid, ids) + lb_office_log(c, oid, y, [v for v in vs if vid is None or v == vid], vs), key=lambda r: r["at"])
    return y, vid, vs, clients, drives, log, lb_report(c, oid, uid, y, vid)


def _veh_val(k, v):
    if k == "kind":
        return tr("Private car used for business") if v == "private" else tr("Company car")
    if k == "archived":
        return tr("Archived") if v else tr("Restored")
    if k == "odo_start":
        return _de(v)
    return "" if v is None else str(v)


def lb_office_log(c, oid, year, vids, vs):
    """2.93.0 B (#1928 review): the entries of the office log that change the allowance of the year -- every new / changed
    vehicle of vids (also later ones: a kind change counts for all years) and the rate of the year -- as change-log rows
    {drive_id None, action, prev {}, by, at, text}."""
    from .ledger import _log_public
    labels = {"name": tr("Name"), "plate": tr("Plate"), "kind": tr("Kind"), "odo_start": tr("Odometer start"), "archived": tr("Archived")}
    out = []
    for r in c.execute("SELECT * FROM office_doc_log WHERE org_id=? AND target IN ('vehicle', 'km_rate') ORDER BY id", (oid,)):
        d = _log_public(c, r)
        det = d["detail"] if isinstance(d["detail"], dict) else {}
        b, a = det.get("before") or {}, det.get("after") or {}
        if r["target"] == "km_rate":
            if str(det.get("year")) != str(year):
                continue
            text = f"{tr('Mileage allowance per business km')} {year}: {_de(b.get('km_rate'))} -> {_de(a.get('km_rate'))}"
        else:
            if det.get("vehicle_id") not in vids:
                continue
            name = (vs.get(det.get("vehicle_id")) or {}).get("name") or ""
            parts = [f"{labels.get(k, k)}: " + (f"{_veh_val(k, b.get(k))} -> " if r["action"] != "create" else "") + _veh_val(k, a.get(k))
                     for k in LB_VEH_LOG if k in a]
            text = f"{tr('Vehicle')} {name}: " + ", ".join(parts)
        out.append({"id": None, "drive_id": None, "action": r["action"], "prev": {}, "by": d["user_name"], "at": d["at"], "text": text})
    return out


def _de(v):
    return "" if v is None else str(v).replace(".", ",")


def _prev_text(prev, vs, clients):
    """The logged values as one readable line (field: value, ...)."""
    labels = {"vehicle_id": tr("Vehicle"), "user_id": tr("Driver"), "day": tr("Date"), "start_place": tr("Start"), "dest": tr("Destination"),
              "purpose": tr("Purpose"), "km": "km", "odo_start": tr("Odometer start"), "odo_end": tr("Odometer end"), "kind": tr("Kind"),
              "client_id": tr("Client"), "project": tr("Project")}
    out = []
    for k, v in prev.items():
        if k == "vehicle_id":
            v = (vs.get(v) or {}).get("name") or v
        elif k == "client_id":
            v = clients.get(v) or v
        elif k == "kind":
            v = _kind_label(v)
        elif k in ("km", "odo_start", "odo_end"):
            v = _de(v)
        out.append(f"{labels.get(k, k)}: {'' if v is None else v}")
    return ", ".join(out)


LB_ACTIONS = {"create": N_("Created"), "change": N_("Changed"), "delete": N_("Deleted"), "restore": N_("Restored"),
              "update": N_("Changed"), "trip": N_("Taken over into the travel expenses")}  # 2.93.0 B (#1928 review): update, trip


@app.get("/api/office/logbook.csv")
def lb_csv():
    """?year=&vehicle_id= -> the drives of the year with odometer and sums, then the change log (semicolon, decimal comma)."""
    from .books import bk_csv_cell
    from .ledger import ofx_log
    c, uid, oid = _ctx()
    y, vid, vs, clients, drives, log, rep = _export_data(c, oid, uid)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    cell = bk_csv_cell
    w.writerow([tr("Date"), tr("Vehicle"), tr("Plate"), tr("Driver"), tr("Start"), tr("Destination"), tr("Purpose"), tr("Client"), tr("Project"),
                tr("Kind"), tr("Odometer start"), tr("Odometer end"), "km"])
    for d in drives:
        v = vs.get(d["vehicle_id"]) or {}
        w.writerow([d["day"], cell(v.get("name")), cell(v.get("plate")), cell(d["driver"]), cell(d["start_place"]), cell(d["dest"]), cell(d["purpose"]),
                    cell(clients.get(d["client_id"], "")), cell(d["project"]), cell(_kind_label(d["kind"])), _de(d["odo_start"]), _de(d["odo_end"]), _de(d["km"])])
    w.writerow([])
    w.writerow([cell(tr("Vehicle")), tr("km total"), tr("Business"), tr("Private|drive"), tr("Home - workplace"), tr("Business share"), tr("Mileage allowance")])
    for v in rep["vehicles"]:
        w.writerow([cell(v["name"]), _de(v["km_total"]), _de(v["km_business"]), _de(v["km_private"]), _de(v["km_commute"]), f"{v['business_pct']} %", _de(v["allowance"])])
    w.writerow([])
    w.writerow([cell(tr("Change log"))])
    w.writerow([tr("Time"), tr("Date"), tr("Action"), tr("By"), tr("Values before")])
    days = {d["id"]: d["day"] for d in drives}
    for r in log:
        w.writerow([r["at"], days.get(r["drive_id"], ""), cell(tr(LB_ACTIONS.get(r["action"], r["action"]))), cell(r["by"]), cell(r.get("text") or _prev_text(r["prev"], vs, clients))])
    w.writerow([cell(tr(LB_NOTE))])
    ofx_log(c, oid, "export", target="logbook", detail={"what": "logbook.csv", "year": y})
    c.commit()
    return Response("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="logbook-{y}.csv"', "Cache-Control": "no-store"})


def lb_pdf_bytes(c, oid, y, vs, clients, drives, log, rep, lang):
    """A plain A4 PDF: the drives of the year with odometer, the sums per vehicle and the change log as appendix."""
    from .ledger import ofx_company
    from .pdf import A4_H, A4_W, C_INK2, C_RULE, _Page, pdf_money, pdf_write
    s = office_settings(c, oid)
    company = ofx_name1(ofx_company(c, oid).get("name") or (s.get("company") or {}).get("name"))  # 2.99.0 D (#2188): one line
    lg = "de" if lang == "de" else "en"
    cur = (s.get("currency") or "EUR").upper()
    x0, x1 = 40, A4_W - 40
    pages, st = [], {"pg": None, "y": 0}

    def page():
        st["pg"] = _Page()
        pages.append(st["pg"])
        st["y"] = 48

    def need(h):
        if st["pg"] is None or st["y"] + h > A4_H - 48:
            page()

    def km(v):
        return "" if v in (None, "") else (_de(v) if lg == "de" else str(v))

    page()
    pg = lambda: st["pg"]  # noqa: E731
    if company:
        pg().text(x0, st["y"], company, 10, color=C_INK2)
        st["y"] += 18
    pg().text(x0, st["y"], tr("Logbook {0}", y), 16, bold=True)
    st["y"] += 28
    # columns: date, vehicle, route, purpose / client, kind, odometer start / end, km (x, width, align)
    cols = [(x0, 48, "l"), (x0 + 50, 60, "l"), (x0 + 112, 120, "l"), (x0 + 234, 110, "l"), (x0 + 346, 50, "l"),
            (x0 + 398, 40, "r"), (x0 + 440, 40, "r"), (x1 - 33, 33, "r")]
    heads = (tr("Date"), tr("Vehicle"), tr("Route"), tr("Purpose"), tr("Kind"), tr("Start"), tr("End"), "km")

    def head():
        for (cx, cw, al), h in zip(cols, heads):
            pg().text(cx, st["y"], h, 7, color=C_INK2, align=al, width=cw)
        st["y"] += 11
        pg().line(x0, st["y"], x1, st["y"], color=C_RULE)
        st["y"] += 4

    need(40)
    head()
    for d in drives:
        if st["y"] + 12 > A4_H - 48:
            page()
            head()
        v = vs.get(d["vehicle_id"]) or {}
        route = " – ".join(x for x in (d["start_place"], d["dest"]) if x)
        purpose = ", ".join(x for x in (d["purpose"], clients.get(d["client_id"], ""), d["project"]) if x)
        vals = (d["day"], v.get("name") or "", route, purpose, _kind_label(d["kind"]), km(d["odo_start"]), km(d["odo_end"]), km(d["km"]))
        lim = (12, 14, 30, 28, 12, 10, 10, 9)
        for (cx, cw, al), val, mx in zip(cols, vals, lim):
            pg().text(cx, st["y"], str(val)[:mx], 7, align=al, width=cw)
        st["y"] += 11
    if not drives:
        pg().text(x0, st["y"], tr("No drives in this year."), 8, color=C_INK2)
        st["y"] += 12
    st["y"] += 14
    need(40)
    pg().text(x0, st["y"], tr("Year report"), 11, bold=True)
    st["y"] += 16
    for v in rep["vehicles"]:
        need(28)
        pg().text(x0, st["y"], f"{v['name']}{(' (' + v['plate'] + ')') if v['plate'] else ''}", 9, bold=True)
        st["y"] += 12
        line = (f"{tr('km total')}: {km(v['km_total'])} · {tr('Business')}: {km(v['km_business'])} · {tr('Private|drive')}: {km(v['km_private'])} · "
                f"{tr('Home - workplace')}: {km(v['km_commute'])} · {tr('Business share')}: {v['business_pct']} %")
        if v["kind"] == "private":
            line += f" · {tr('Mileage allowance')}: {pdf_money(v['allowance'], lg, cur)}"
        st["y"] += pg().para(x0, st["y"], line, 8, x1 - x0) + 6
    if not rep["vehicles"]:
        pg().text(x0, st["y"], tr("None"), 8, color=C_INK2)
        st["y"] += 12
    st["y"] += 6
    need(30)
    st["y"] += pg().para(x0, st["y"], tr(LB_NOTE), 7.5, x1 - x0, color=C_INK2) + 10
    page()
    pg().text(x0, st["y"], tr("Change log"), 13, bold=True)
    st["y"] += 22
    days = {d["id"]: d["day"] for d in drives}
    for r in log:
        need(26)
        pg().text(x0, st["y"], f"{r['at'][:16].replace('T', ' ')} · {tr(LB_ACTIONS.get(r['action'], r['action']))} · {r['by']}"
                  + (f" · {tr('Drive of {0}', days[r['drive_id']])}" if r["drive_id"] in days else ""), 8, bold=True)
        st["y"] += 11
        t = r.get("text") or _prev_text(r["prev"], vs, clients)
        if t:
            st["y"] += pg().para(x0 + 8, st["y"], t, 7.5, x1 - x0 - 8, color=C_INK2)
        st["y"] += 5
    if not log:
        pg().text(x0, st["y"], tr("None"), 8, color=C_INK2)
    return pdf_write(pages, {}, title=tr("Logbook {0}", y), author=company)


@app.get("/api/office/logbook.pdf")
def lb_pdf():
    """?year=&vehicle_id= -> the logbook of the year as PDF (drives, sums, change log)."""
    from .ledger import ofx_log
    c, uid, oid = _ctx()
    y, vid, vs, clients, drives, log, rep = _export_data(c, oid, uid)
    data = lb_pdf_bytes(c, oid, y, vs, clients, drives, log, rep, lang())
    ofx_log(c, oid, "export", target="logbook", detail={"what": "logbook.pdf", "year": y})
    c.commit()
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="logbook-{y}.pdf"', "Cache-Control": "no-store"})
