"""Office & finance (2.47.3, #1022, part B): travel expenses. Trips (office_trips) with their receipts (office_trip_items),
the list of receipts not yet ticked "in DATEV", an evaluation by month / year / person / project / client / category (also
as CSV) and billing receipts on to a client (positions of a quotation / invoice with purchase = amount, marked so nothing is
billed twice). Kalmido keeps no receipt images: they live in DATEV (decision of 2026-10-08, variant A). 2.95.0 (#1932): the
per diem (Verpflegungsmehraufwand) of every trip with the BMF rates of the year (office/vma.py), its report as PDF / Excel /
CSV and the import of a per diem spreadsheet (office/vmaimport.py).

Every route: office_gate + office_org with the admin of the office area (like purchases; members get 403). Amounts are
decimal strings; participants, note and amounts encrypted at rest (orgcrypt). Never reached by agents."""
import csv
import io
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import jsonify, request, Response

from ..core.config import app
from ..core.pg import insert_id, write_lock
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields, oc_item_store
from ..core.i18n import N_, tr
from ..core.db import body, bump, db, iso, now_utc
from ..core.access import Denied
from ..core.errors import BadInput
from .calc import dec, dstr, money
from .model import office_gate, office_org, office_settings
from .ledger import ofx_items_brief, ofx_log, ofx_need_editable
from .olock import olk_need_trip_items, olk_trip_item_reason
from .vma import vma_trip
from .periodlock import period_need_open

RK_CATS = (("car", N_("Car / fuel")), ("train", N_("Train")), ("flight", N_("Flight")), ("rental_car", N_("Rental car")),
           ("taxi", N_("Taxi / public transport")), ("parking", N_("Parking")), ("hotel", N_("Hotel")), ("meals", N_("Meals")),
           ("other", N_("Other|travel")))
RK_CAT_KEYS = tuple(k for k, _ in RK_CATS)
RK_PURPOSES = ("job", "acquisition")  # job = for a client / project; acquisition = acquisition / research
RK_BY = ("month", "year", "person", "project", "client", "category", "purpose")  # 2.117.0 A (#2292): + purpose
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CUR_RE = re.compile(r"^[A-Z]{3}$")
CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_PEOPLE = 20
MAX_ITEMS = 200
RKA_MAX_PURPOSES = 200  # 2.117.0 A (#2292): own purposes per office area


from .model import office_ctx_admin as _ctx  # noqa: E402  2.149.0 G (#2517): was an own copy


def rk_cat_label(k, lg=None):
    return tr(dict(RK_CATS).get(k, "Other|travel"), lg=lg)


def _date(v, name, required=False):
    if v in (None, ""):
        if required:
            raise BadInput(tr("Invalid value: {0}", name))
        return ""
    if isinstance(v, str) and DATE_RE.match(v.strip()):
        try:
            return date.fromisoformat(v.strip()).isoformat()
        except ValueError:
            pass
    raise BadInput(tr("Invalid value: {0}", name))


def _text(v, name, mx=500):
    if v is None:
        return ""
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", name))
    return CTRL_RE.sub("", v).strip()[:mx]


def _amount(v, name, lo=0, hi=10 ** 9, allow_none=False):
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
    if d.is_nan() or not d.is_finite() or d < lo or d > hi:
        raise BadInput(tr("Invalid value: {0}", name))
    return d


def rk_cl_where(c, oid):
    """The clients of the office area as (sql, args) -- the ONE place of B's client queries: part A's model.pb_cl_where
    (a personal office's clients are the person's private ones) when it is there, else the organisation's."""
    from . import model
    fn = getattr(model, "pb_cl_where", None)
    return fn(c, oid) if fn else ("org_id=?", [oid])


def rk_home_cur(c, oid):
    return (office_settings(c, oid).get("currency") or "EUR").upper()


def rk_people(c, oid, uid):
    """The people of the office area [{id, name}]: the members of the organisation (a personal office: its person)."""
    # 2.143.0 A (#2151, review): the organisation's staff (admin, member, read-only), not guests / accounting
    rows = c.execute("SELECT u.id, u.display_name, u.username FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? "
                     "AND m.role IN ('admin','member','readonly') "
                     "ORDER BY lower(COALESCE(NULLIF(u.display_name, ''), u.username))", (oid,)).fetchall()
    if not any(r["id"] == uid for r in rows):
        rows = list(rows) + list(c.execute("SELECT id, display_name, username FROM users WHERE id=?", (uid,)).fetchall())
    return [{"id": r["id"], "name": r["display_name"] or r["username"]} for r in rows]


def _people_clean(v, known):
    """[{id} | {name}] -> the cleaned list: ids of people of the area (name filled in), free names (external people)."""
    if v in (None, ""):
        return []
    if not isinstance(v, list) or len(v) > MAX_PEOPLE:
        raise BadInput(tr("Invalid value: {0}", "people"))
    out, seen = [], set()
    for p in v:
        if isinstance(p, dict) and p.get("id") not in (None, ""):
            try:
                pid = int(p["id"])
            except (TypeError, ValueError):
                raise BadInput(tr("Invalid value: {0}", "people"))
            if pid not in known:
                raise BadInput(tr("Invalid value: {0}", "people"))
            if ("u", pid) not in seen:
                seen.add(("u", pid))
                out.append({"id": pid, "name": known[pid]})
            continue
        name = _text(p.get("name") if isinstance(p, dict) else p, "people", 120)
        if name and ("n", name.lower()) not in seen:
            seen.add(("n", name.lower()))
            out.append({"name": name})
    return out


def _client_ok(c, oid, v):
    if v in (None, ""):
        return None
    try:
        cid = int(v)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", "client_id"))
    w, wa = rk_cl_where(c, oid)
    if not c.execute(f"SELECT 1 FROM clients WHERE id=? AND {w}", [cid] + list(wa)).fetchone():
        raise BadInput(tr("Invalid value: {0}", "client_id"))
    return cid


def rk_trip_clean(c, oid, uid, b, cur=None):
    """The columns of a trip from body b (partial when cur is given)."""
    cur = cur or {}
    out = {}
    if "date_from" in b or not cur:
        out["date_from"] = _date(b.get("date_from"), "date_from", required=True)
    if "date_to" in b or not cur:
        out["date_to"] = _date(b.get("date_to"), "date_to") or out.get("date_from") or cur.get("date_from")
    df, dt = out.get("date_from", cur.get("date_from")), out.get("date_to", cur.get("date_to"))
    if df and dt and dt < df:
        raise BadInput(tr("The end is before the start"))
    if "dest" in b or not cur:
        out["dest"] = _text(b.get("dest"), "dest", 300)
    if "overnight" in b or not cur:
        out["overnight"] = 1 if b.get("overnight") else 0
    if "people" in b or not cur:
        known = {p["id"]: p["name"] for p in rk_people(c, oid, uid)}
        out["people"] = json.dumps(_people_clean(b.get("people"), known), ensure_ascii=False)
    if "purpose" in b or not cur:
        p = b.get("purpose") or "job"
        if p not in RK_PURPOSES:  # 2.117.0 A (#2292): an own purpose is kept as its text
            p = rka_purpose_name(p)
        out["purpose"] = p
    if "client_id" in b or not cur:
        out["client_id"] = _client_ok(c, oid, b.get("client_id"))
    if "project" in b or not cur:
        out["project"] = _text(b.get("project"), "project", 200)
    if "km" in b or not cur:
        km = _amount(b.get("km"), "km", 0, 10 ** 6, allow_none=True)
        out["km"] = float(km) if km is not None else None
    if "note" in b or not cur:
        out["note"] = _text(b.get("note"), "note", 2000)
    out.update(rk_vma_clean(b, cur))  # 2.95.0 (#1932)
    return out


TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _country(v, name="country"):
    """'' (Germany) or an ISO 3166-1 alpha-2 code (office/countries.py)."""
    from .countries import fk_country_code
    code = fk_country_code(v if isinstance(v, str) or v is None else "?")
    if code is None:
        raise BadInput(tr("Invalid value: {0}", name))
    return "" if code == "DE" else code


def rk_vma_clean(b, cur=None):
    """2.95.0 (#1932): the per diem fields of a trip from body b: country (ISO, '' = Germany), place (a city of the BMF table,
    '' = the whole country), t_start / t_end (HH:MM or ''), vma_days [{date, country, place, b, l, d}] (only days with another
    country or meals provided are kept, at most one per date), vma_off (no per diem)."""
    cur = cur or {}
    out = {}
    if "country" in b or not cur:
        out["country"] = _country(b.get("country"))
    if "place" in b or not cur:
        out["place"] = _text(b.get("place"), "place", 120)
    for k in ("t_start", "t_end"):
        if k in b or not cur:
            v = b.get(k) or ""
            if v and (not isinstance(v, str) or not TIME_RE.match(v.strip())):
                raise BadInput(tr("Invalid value: {0}", k))
            out[k] = v.strip() if v else ""
    if "vma_days" in b or not cur:
        v = b.get("vma_days")
        if v in (None, ""):
            v = []
        if not isinstance(v, list) or len(v) > 400:
            raise BadInput(tr("Invalid value: {0}", "vma_days"))
        days = {}
        for x in v:
            if not isinstance(x, dict):
                raise BadInput(tr("Invalid value: {0}", "vma_days"))
            d = _date(x.get("date"), "vma_days", required=True)
            row = {"date": d}
            if x.get("country") not in (None, ""):
                row["country"] = _country(x.get("country"), "vma_days") or "DE"
            if x.get("place"):
                row["place"] = _text(x.get("place"), "vma_days", 120)
            for m in ("b", "l", "d"):
                if x.get(m):
                    row[m] = 1
            if len(row) > 1:
                days[d] = row
        out["vma_days"] = json.dumps([days[k] for k in sorted(days)], ensure_ascii=False)
    if "vma_off" in b or not cur:
        out["vma_off"] = 1 if b.get("vma_off") else 0
    return out


def rk_vma_fields(d):
    """The per diem fields of a stored (decrypted) trip row -> the dict office/vma.vma_trip reads."""
    try:
        days = json.loads(d.get("vma_days") or "[]")
    except ValueError:
        days = []
    return {"date_from": d.get("date_from") or "", "date_to": d.get("date_to") or "", "country": d.get("country") or "",
            "place": d.get("place") or "", "t_start": d.get("t_start") or "", "t_end": d.get("t_end") or "",
            "overnight": d.get("overnight") or 0, "vma_days": days if isinstance(days, list) else [], "vma_off": d.get("vma_off") or 0}


def rk_item_clean(c, oid, b, cur=None, home=None):
    """The columns of a receipt from body b (partial when cur is given). amount in currency; fx_rate = units of currency per
    one unit of the office currency (like the documents' rate); amount_home given = taken as it is (e.g. from the bank
    statement), else amount / fx_rate."""
    cur = cur or {}
    out = {}
    if "date" in b or not cur:
        out["date"] = _date(b.get("date"), "date")
    if "category" in b or not cur:
        k = b.get("category") or "other"
        if k not in RK_CAT_KEYS:
            raise BadInput(tr("Invalid value: {0}", "category"))
        out["category"] = k
    if "text" in b or not cur:
        out["text"] = _text(b.get("text"), "text", 300)
    if "datev" in b or not cur:
        out["datev"] = 1 if b.get("datev") else 0
    if "datev_no" in b or not cur:
        out["datev_no"] = _text(b.get("datev_no"), "datev_no", 60)
    money_keys = ("amount", "currency", "fx_rate", "amount_home")
    if any(k in b for k in money_keys) or not cur:
        amt = _amount(b.get("amount", cur.get("amount")), "amount")
        ccy = str(b.get("currency", cur.get("currency")) or home or "EUR").strip().upper()
        if not CUR_RE.match(ccy):
            raise BadInput(tr("Invalid value: {0}", "currency"))
        if ccy == (home or "EUR"):
            fx, ah = None, amt
        else:
            ofx = cur.get("fx_rate")
            fx = _amount(b.get("fx_rate", str(ofx) if ofx is not None else None), "fx_rate", dec("0.000001"), 10 ** 6, allow_none=True)
            ah = _amount(b.get("amount_home"), "amount_home", allow_none=True) if "amount_home" in b else None
            if ah is None:
                if fx is not None:
                    ah = amt / fx
                elif cur and "amount" not in b and "currency" not in b:
                    ah = dec(cur.get("amount_home"))  # an amount in the office currency entered by hand stays
                else:
                    raise BadInput(tr("A foreign currency needs its exchange rate"))
        out.update(amount=dstr(money(amt)), currency=ccy, fx_rate=float(fx) if fx is not None else None, amount_home=dstr(money(ah)))
    return out


def _billed_ok(c, oid, r):
    """The document a receipt was billed on, if it still exists: {id, number, kind, project_title} or None."""
    if not r.get("billed_doc_id"):
        return None
    d = c.execute("SELECT id, number, kind, project_title, status FROM office_docs WHERE id=? AND org_id=?", (r["billed_doc_id"], oid)).fetchone()
    return dict(d) if d else None


def _item_public(c, oid, r, docs):
    d = oc_dec_fields(c, oid, "office_trip_items", r)
    bd = docs.get(d.get("billed_doc_id")) if d.get("billed_doc_id") else None
    return {"id": d["id"], "trip_id": d["trip_id"], "date": d["date"], "category": d["category"], "amount": d["amount"], "currency": d["currency"],
            "fx_rate": format(dec(d["fx_rate"]).normalize(), "f") if d.get("fx_rate") is not None else None, "amount_home": d["amount_home"], "text": d["text"],
            "datev": d["datev"], "datev_no": d["datev_no"], "billed": bd, "billed_at": d.get("billed_at") if bd else None}


def _docs_map(c, oid):
    return {r["id"]: {"id": r["id"], "number": r["number"], "kind": r["kind"], "project_title": r["project_title"]}
            for r in c.execute("SELECT id, number, kind, project_title FROM office_docs WHERE org_id=? AND id IN "
                               "(SELECT billed_doc_id FROM office_trip_items WHERE org_id=? AND billed_doc_id IS NOT NULL)", (oid, oid))}


def rk_trip_public(c, oid, t, items, docs=None):
    """A trip with its receipts (decrypted; sum in the office currency, missing = receipts not ticked "in DATEV")."""
    docs = _docs_map(c, oid) if docs is None else docs
    d = oc_dec_fields(c, oid, "office_trips", t)
    try:
        people = json.loads(d.get("people") or "[]")
    except ValueError:
        people = []
    its = [_item_public(c, oid, r, docs) for r in items]
    total = sum((dec(x["amount_home"]) for x in its), dec(0))
    vf = rk_vma_fields(d)  # 2.95.0 (#1932): the per diem for ONE participant (vma.amount) and for all of them (vma.total)
    vma = vma_trip(vf)
    npp = max(1, len(people) if isinstance(people, list) else 0)
    vma["persons"] = npp
    vma["total"] = dstr(money(dec(vma["amount"]) * npp)) if vma["amount"] is not None else None
    return {"id": d["id"], "date_from": d["date_from"], "date_to": d["date_to"], "dest": d["dest"], "overnight": d["overnight"],
            "people": people if isinstance(people, list) else [], "purpose": d["purpose"], "client_id": d["client_id"], "project": d["project"],
            "km": dstr(dec(d["km"])) if d.get("km") is not None else None, "note": d.get("note") or "", "items": its,
            "total": dstr(money(total)), "missing": sum(1 for x in its if not x["datev"]), "unbilled": sum(1 for x in its if not x["billed"]),
            "country": vf["country"], "place": vf["place"], "t_start": vf["t_start"], "t_end": vf["t_end"], "vma_days": vf["vma_days"],
            "vma_off": vf["vma_off"], "vma": vma}


def rk_trips(c, oid, year=None, trip_id=None):
    sql, args = "SELECT * FROM office_trips WHERE org_id=?", [oid]
    if trip_id is not None:
        sql += " AND id=?"
        args.append(trip_id)
    elif year:
        sql += " AND (substr(date_from, 1, 4)=? OR substr(date_to, 1, 4)=?)"
        args += [str(year), str(year)]
    trips = c.execute(sql + " ORDER BY date_from DESC, id DESC", args).fetchall()
    if not trips:
        return []
    ids = [t["id"] for t in trips]
    by = {}
    for r in c.execute(f"SELECT * FROM office_trip_items WHERE org_id=? AND trip_id IN ({','.join('?' * len(ids))}) ORDER BY date, sort, id", [oid] + ids):
        by.setdefault(r["trip_id"], []).append(r)
    docs = _docs_map(c, oid)
    return [rk_trip_public(c, oid, t, by.get(t["id"], []), docs) for t in trips]


def _trip_need_open(c, oid, t, *days, items=True):
    """2.148.0 A (#2471): 409 when trip t (its days, its receipts' days when items) or one of days lies in a locked month."""
    ds = [t["date_from"], t["date_to"], *days]
    if items:
        ds += [r["date"] for r in c.execute("SELECT date FROM office_trip_items WHERE trip_id=? AND org_id=?", (t["id"], oid)).fetchall()]
    period_need_open(c, oid, *ds)


def _trip(c, oid, tid):
    r = c.execute("SELECT * FROM office_trips WHERE id=? AND org_id=?", (tid, oid)).fetchone()
    if not r:
        raise Denied(404)
    return r


def _one(c, oid, tid):
    return rk_trips(c, oid, trip_id=tid)[0]


def _insert_item(c, oid, tid, row, sort=0):
    ts = iso(now_utc())
    row = dict(row, org_id=oid, trip_id=tid, sort=sort, created_at=ts, updated_at=ts)
    row = oc_enc_fields(c, oid, "office_trip_items", row)
    return insert_id(c, f"INSERT INTO office_trip_items({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))


# ---------------------------------------------------------------- routes: trips and receipts
@app.get("/api/office/trips")
def rk_trips_get():
    """?year=YYYY (optional) -> {trips, people, clients, projects, categories, currency, missing}; missing = receipts of
    all trips not yet ticked "in DATEV"."""
    c, uid, oid = _ctx()
    y = request.args.get("year") or ""
    if y and not re.fullmatch(r"\d{4}", y):
        raise BadInput(tr("Invalid value: {0}", "year"))
    trips = rk_trips(c, oid, year=y or None)
    missing = c.execute("SELECT COUNT(*) FROM office_trip_items WHERE org_id=? AND datev=0", (oid,)).fetchone()[0]
    clients = [{"id": r["id"], "name": r["name"]} for r in
               c.execute(f"SELECT id, name FROM clients WHERE {rk_cl_where(c, oid)[0]} AND archived=0 ORDER BY lower(name)", rk_cl_where(c, oid)[1])]
    projects = [r[0] for r in c.execute("SELECT DISTINCT project_title FROM office_docs WHERE org_id=? AND project_title<>'' ORDER BY 1", (oid,))][:300]
    return jsonify(trips=trips, people=rk_people(c, oid, uid), clients=clients, projects=projects, currency=rk_home_cur(c, oid),
                   categories=[{"key": k, "label": tr(n)} for k, n in RK_CATS], missing=missing,
                   purposes=rka_purposes(c, oid))  # 2.117.0 A (#2292)


@app.post("/api/office/trips")
def rk_trip_post():
    """A new trip {date_from, date_to, dest, overnight, people: [{id}|{name}], purpose job|acquisition, client_id, project,
    km, note, items?: [receipt, ...]} (items: also the way back of an undone delete). 201 the trip."""
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    row = rk_trip_clean(c, oid, uid, b)
    its = b.get("items") or []
    if not isinstance(its, list) or len(its) > MAX_ITEMS:
        raise BadInput(tr("Invalid value: {0}", "items"))
    home = rk_home_cur(c, oid)
    clean = [rk_item_clean(c, oid, x if isinstance(x, dict) else {}, home=home) for x in its]
    period_need_open(c, oid, row.get("date_from"), row.get("date_to"), *[x.get("date") for x in clean])  # 2.148.0 A (#2471)
    ts = iso(now_utc())
    row.update(org_id=oid, created_by=uid, created_at=ts, updated_at=ts)
    row = oc_enc_fields(c, oid, "office_trips", row)
    tid = insert_id(c, f"INSERT INTO office_trips({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    for i, x in enumerate(clean):
        bd = its[i].get("billed") if isinstance(its[i], dict) else None  # the undo of a delete keeps "billed on"
        if isinstance(bd, dict) and isinstance(bd.get("id"), int) and _billed_ok(c, oid, {"billed_doc_id": bd["id"]}):
            x = dict(x, billed_doc_id=bd["id"], billed_at=_text(its[i].get("billed_at"), "billed_at", 40) or ts)
        _insert_item(c, oid, tid, x, i)
    bump(c)
    c.commit()
    return jsonify(_one(c, oid, tid)), 201


@app.patch("/api/office/trips/<int:tid>")
def rk_trip_patch(tid):
    c, uid, oid = _ctx()
    t = oc_dec_fields(c, oid, "office_trips", _trip(c, oid, tid))
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    row = rk_trip_clean(c, oid, uid, b, t)
    if row:
        _trip_need_open(c, oid, t, row.get("date_from"), row.get("date_to"))  # 2.148.0 A (#2471)
        row["updated_at"] = iso(now_utc())
        row = oc_enc_fields(c, oid, "office_trips", row)
        c.execute(f"UPDATE office_trips SET {','.join(k + '=?' for k in row)} WHERE id=? AND org_id=?", list(row.values()) + [tid, oid])
        bump(c)
        c.commit()
    return jsonify(_one(c, oid, tid))


@app.delete("/api/office/trips/<int:tid>")
def rk_trip_delete(tid):
    """Deletes a trip with its receipts; answers the trip as it was (the client's undo posts it again)."""
    c, uid, oid = _ctx()
    _trip_need_open(c, oid, _trip(c, oid, tid))  # 2.148.0 A (#2471)
    # 2.152.0 C (#2168): receipts in DATEV / billed on a finalised document are kept by law -> the trip stays (409)
    olk_need_trip_items(c, oid, c.execute("SELECT * FROM office_trip_items WHERE trip_id=? AND org_id=?", (tid, oid)).fetchall())
    old = _one(c, oid, tid)
    c.execute("DELETE FROM office_trips WHERE id=? AND org_id=?", (tid, oid))
    bump(c)
    c.commit()
    return jsonify(ok=True, trip=old)


@app.post("/api/office/trips/<int:tid>/items")
def rk_item_post(tid):
    """A new receipt {date, category, amount, currency, fx_rate | amount_home, text, datev, datev_no}. 201 the trip."""
    c, uid, oid = _ctx()
    _trip(c, oid, tid)
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    if c.execute("SELECT COUNT(*) FROM office_trip_items WHERE trip_id=? AND org_id=?", (tid, oid)).fetchone()[0] >= MAX_ITEMS:
        raise BadInput(tr("Too many entries"))
    row = rk_item_clean(c, oid, b, home=rk_home_cur(c, oid))
    _trip_need_open(c, oid, _trip(c, oid, tid), row.get("date"), items=False)  # 2.148.0 A (#2471)
    mx = c.execute("SELECT COALESCE(MAX(sort), 0) FROM office_trip_items WHERE trip_id=? AND org_id=?", (tid, oid)).fetchone()[0]
    iid = _insert_item(c, oid, tid, row, (mx or 0) + 1)
    c.execute("UPDATE office_trips SET updated_at=? WHERE id=? AND org_id=?", (iso(now_utc()), tid, oid))
    bump(c)
    c.commit()
    return jsonify(dict(_one(c, oid, tid), item_id=iid)), 201


def _item(c, oid, tid, iid):
    r = c.execute("SELECT * FROM office_trip_items WHERE id=? AND trip_id=? AND org_id=?", (iid, tid, oid)).fetchone()
    if not r:
        raise Denied(404)
    return r


RK_LOCKED_KEYS = ("datev", "amount", "currency", "fx_rate", "amount_home", "date")


def _rk_val(v):
    """A receipt value made comparable (numbers as Decimal, empty as None)."""
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return str(v)


@app.patch("/api/office/trips/<int:tid>/items/<int:iid>")
def rk_item_patch(tid, iid):
    c, uid, oid = _ctx()
    cur = oc_dec_fields(c, oid, "office_trip_items", _item(c, oid, tid, iid))
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    row = rk_item_clean(c, oid, b, cur, home=rk_home_cur(c, oid))
    # 2.152.0 (#2168, review B-M1): a locked receipt (in DATEV / billed on a finalised document) keeps its tick, amount
    # and date; text, DATEV number and category stay editable
    why = olk_trip_item_reason(c, oid, cur)
    if why and "amount_home" not in b and all(_rk_val(row.get(k)) == _rk_val(cur.get(k)) for k in ("amount", "currency", "fx_rate")):
        for k in ("amount", "currency", "fx_rate", "amount_home"):
            row.pop(k, None)  # the dialog sends the money unchanged: the stored amount in the office currency stays as it is
    if why and any(_rk_val(row[k]) != _rk_val(cur.get(k)) for k in RK_LOCKED_KEYS if k in row):
        raise Denied(409, why)
    if row:
        _trip_need_open(c, oid, _trip(c, oid, tid), cur["date"], row.get("date"), items=False)  # 2.148.0 A (#2471)
        row["updated_at"] = iso(now_utc())
        row = oc_enc_fields(c, oid, "office_trip_items", row)
        c.execute(f"UPDATE office_trip_items SET {','.join(k + '=?' for k in row)} WHERE id=? AND org_id=?", list(row.values()) + [iid, oid])
        bump(c)
        c.commit()
    return jsonify(_one(c, oid, tid))


@app.delete("/api/office/trips/<int:tid>/items/<int:iid>")
def rk_item_delete(tid, iid):
    """Deletes a receipt; answers the trip and the receipt as it was (for the undo)."""
    c, uid, oid = _ctx()
    r = _item(c, oid, tid, iid)
    _trip_need_open(c, oid, _trip(c, oid, tid), r["date"], items=False)  # 2.148.0 A (#2471)
    olk_need_trip_items(c, oid, [r])  # 2.152.0 C (#2168): in DATEV / billed on a finalised document -> 409
    old = _item_public(c, oid, r, _docs_map(c, oid))
    c.execute("DELETE FROM office_trip_items WHERE id=? AND org_id=?", (iid, oid))
    bump(c)
    c.commit()
    return jsonify(trip=_one(c, oid, tid), item=old)


# ---------------------------------------------------------------- 2.117.0 A (#2292): own purposes
def rka_purpose_name(v):
    """A clean own purpose (1-120 characters, not one of the built-in keys) or 400."""
    n = " ".join(_text(v, "purpose", 200).split())
    if not n or len(n) > 120 or n.casefold() in RK_PURPOSES:
        raise BadInput(tr("Invalid value: {0}", "purpose"))
    return n


def rka_purposes(c, oid):
    """The own purposes of the office area [{id, name}] by name."""
    rows = c.execute("SELECT id, name FROM office_trip_purposes WHERE org_id=? AND deleted_at IS NULL", (oid,)).fetchall()
    return sorted(({"id": r["id"], "name": r["name"]} for r in rows), key=lambda x: x["name"].casefold())


def rka_purpose_add(c, oid, uid, name):
    """Adds an own purpose (or restores a removed one of the same name); -> (row {id, name}, created). Same name = the one there."""
    ts = iso(now_utc())
    for r in c.execute("SELECT id, name, deleted_at FROM office_trip_purposes WHERE org_id=? ORDER BY deleted_at IS NOT NULL, id", (oid,)).fetchall():
        if r["name"].casefold() == name.casefold():
            if r["deleted_at"] is None:
                return {"id": r["id"], "name": r["name"]}, False
            c.execute("UPDATE office_trip_purposes SET deleted_at=NULL, name=?, updated_at=? WHERE id=? AND org_id=?", (name, ts, r["id"], oid))
            return {"id": r["id"], "name": name}, True
    if c.execute("SELECT COUNT(*) FROM office_trip_purposes WHERE org_id=? AND deleted_at IS NULL", (oid,)).fetchone()[0] >= RKA_MAX_PURPOSES:
        raise BadInput(tr("Too many entries"))
    pid = insert_id(c, "INSERT INTO office_trip_purposes(org_id, name, created_by, created_at, updated_at) VALUES(?,?,?,?,?)", (oid, name, uid, ts, ts))
    return {"id": pid, "name": name}, True


def rka_purposes_adopt(c, oid, uid, names):
    """The own purposes among names (trip purposes of an import / a move) added to the office area where missing."""
    for n in {x for x in names if isinstance(x, str) and x and x not in RK_PURPOSES}:
        try:
            rka_purpose_add(c, oid, uid, rka_purpose_name(n))
        except BadInput:
            pass  # an odd old text or the limit: the trip keeps it anyway


def _purpose(c, oid, pid):
    r = c.execute("SELECT id, name FROM office_trip_purposes WHERE id=? AND org_id=? AND deleted_at IS NULL", (pid, oid)).fetchone()
    if not r:
        raise Denied(404)
    return r


@app.get("/api/office/trips/purposes")
def rka_purposes_get():
    """The own purposes of the office area {purposes: [{id, name}]} (office admins, like the trips)."""
    c, uid, oid = _ctx()
    return jsonify(purposes=rka_purposes(c, oid))


@app.post("/api/office/trips/purposes")
def rka_purpose_post():
    """{name} -> 201 {id, name} a new own purpose (a removed one of the same name comes back: the undo of a removal);
    200 when it is there already."""
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    row, made = rka_purpose_add(c, oid, uid, rka_purpose_name(b.get("name")))
    if made:
        bump(c)
        c.commit()
    return jsonify(row), 201 if made else 200


@app.patch("/api/office/trips/purposes/<int:pid>")
def rka_purpose_patch(pid):
    """{name} renames an own purpose; the trips keep the text they have."""
    c, uid, oid = _ctx()
    _purpose(c, oid, pid)
    b = body()
    name = rka_purpose_name(b.get("name") if isinstance(b, dict) else None)
    for r in c.execute("SELECT id, name FROM office_trip_purposes WHERE org_id=? AND deleted_at IS NULL AND id<>?", (oid, pid)).fetchall():
        if r["name"].casefold() == name.casefold():
            raise BadInput(tr("This purpose already exists"))
    c.execute("UPDATE office_trip_purposes SET name=?, updated_at=? WHERE id=? AND org_id=?", (name, iso(now_utc()), pid, oid))
    bump(c)
    c.commit()
    return jsonify(id=pid, name=name)


@app.delete("/api/office/trips/purposes/<int:pid>")
def rka_purpose_delete(pid):
    """Removes an own purpose from the choice (the trips keep their text); the undo posts the name again."""
    c, uid, oid = _ctx()
    r = _purpose(c, oid, pid)
    ts = iso(now_utc())
    c.execute("UPDATE office_trip_purposes SET deleted_at=?, updated_at=? WHERE id=? AND org_id=?", (ts, ts, pid, oid))
    bump(c)
    c.commit()
    return jsonify(ok=True, purpose={"id": r["id"], "name": r["name"]})


def rka_purpose_label(p):
    return tr("Acquisition / research") if p == "acquisition" else tr("Job for a client / project") if p == "job" or not p else p


# ---------------------------------------------------------------- evaluation
def rka_pkey(p):
    """2.117.0 A (#2291): the key of a participant (like the per diem report): u<id> = a person of the office, n:<name> = a free name."""
    return ("u%s" % p["id"]) if p.get("id") else ("n:" + (p.get("name") or "").lower())


def rka_person_arg():
    """2.117.0 A (#2291): ?person=u<id>|n:<name> -> the key or None."""
    v = request.args.get("person") or None
    if v is not None and (len(v) > 200 or not re.fullmatch(r"u\d{1,12}|n:.+", v, re.S)):
        raise BadInput(tr("Invalid value: {0}", "person"))
    return v


def rk_report(c, oid, by, date_from="", date_to="", missing=False, person=None):
    """Sums of the receipts (office currency) grouped by month | year | person | project | client | category, receipt date
    (else the trip's start) within [date_from, date_to]. By person every receipt is shared equally between the trip's
    participants (the sum stays the sum of the receipts; trips without participants under "No person"). 2.117.0 A (#2291):
    person = a participant's key: only the trips with that person, each receipt with that person's equal share."""
    w, wa = rk_cl_where(c, oid)
    clients = {r["id"]: r["name"] for r in c.execute(f"SELECT id, name FROM clients WHERE {w}", wa)}
    groups = {}
    total, n = dec(0), 0
    for t in rk_trips(c, oid):
        if person and person not in [rka_pkey(p) for p in t["people"]]:  # 2.117.0 A (#2291)
            continue
        for it in t["items"]:
            day = it["date"] or t["date_from"]
            if (date_from and day < date_from) or (date_to and day > date_to) or (missing and it["datev"]):
                continue
            amt = dec(it["amount_home"])
            if person:
                amt = amt / len(t["people"])
            total += amt
            n += 1
            if by == "person":
                ppl = t["people"] or [{"name": ""}]
                share = amt if person else amt / len(ppl)
                keys = [(("u%s" % p["id"]) if p.get("id") else ("n:" + (p.get("name") or "").lower()), p.get("name") or tr("No person")) for p in ppl]
                for k, lab in keys:
                    if person and k != person:
                        continue
                    g = groups.setdefault(k, {"key": k, "label": lab, "amount": dec(0), "count": 0})
                    g["amount"] += share
                    g["count"] += 1
                continue
            if by == "month":
                k, lab = day[:7], day[:7]
            elif by == "year":
                k, lab = day[:4], day[:4]
            elif by == "project":
                k = t["project"] or ("~acq" if t["purpose"] == "acquisition" else "")  # 2.117.0 A (#2292): own purposes = no project
                lab = t["project"] or (tr("Acquisition / research") if t["purpose"] == "acquisition" else tr("No project"))
            elif by == "client":
                k = str(t["client_id"] or ("~acq" if t["purpose"] == "acquisition" else ""))  # 2.117.0 A (#2292)
                lab = clients.get(t["client_id"]) or (tr("Acquisition / research") if t["purpose"] == "acquisition" else tr("No client"))
            elif by == "purpose":  # 2.117.0 A (#2292)
                k, lab = t["purpose"] or "job", rka_purpose_label(t["purpose"])
            else:
                k, lab = it["category"], rk_cat_label(it["category"])
            g = groups.setdefault(k, {"key": k, "label": lab, "amount": dec(0), "count": 0})
            g["amount"] += amt
            g["count"] += 1
    rows = list(groups.values())
    if by in ("month", "year"):
        rows.sort(key=lambda g: g["key"])
    else:
        rows.sort(key=lambda g: (-g["amount"], g["label"].lower()))
    for g in rows:
        g["amount"] = dstr(money(g["amount"]))
    return {"by": by, "rows": rows, "total": dstr(money(total)), "count": n}


@app.get("/api/office/trips/report")
def rk_report_get():
    """?by=month|year|person|project|client|category|purpose&from=YYYY-MM-DD&to=YYYY-MM-DD&missing=1&person=KEY&format=csv -> the sums
    (JSON {by, rows: [{key, label, amount, count}], total, count, currency}) or a CSV file (semicolon, like the other
    office exports: one row per group, then the total)."""
    c, uid, oid = _ctx()
    by = request.args.get("by") or "month"
    if by not in RK_BY:
        raise BadInput(tr("Invalid value: {0}", "by"))
    df = _date(request.args.get("from"), "from")
    dt = _date(request.args.get("to"), "to")
    person = rka_person_arg()  # 2.117.0 A (#2291)
    rep = rk_report(c, oid, by, df, dt, request.args.get("missing") == "1", person)
    cur = rk_home_cur(c, oid)
    if request.args.get("format") == "csv":
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        head = {"month": tr("Month"), "year": tr("Year"), "person": tr("Person"), "project": tr("Project"), "client": tr("Client"), "category": tr("Category"), "purpose": tr("Purpose")}[by]
        w.writerow([head, tr("Receipts"), tr("Amount") + f" ({cur})"])
        for g in rep["rows"]:
            w.writerow([_csv_safe(g["label"]), g["count"], g["amount"].replace(".", ",")])
        w.writerow([tr("Total"), rep["count"], rep["total"].replace(".", ",")])
        name = f"travel-{by}-{df or 'all'}-{dt or 'all'}{'-' + re.sub(r'[^a-z0-9]+', '-', person.lower()).strip('-') if person else ''}.csv"
        return Response("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"',
                                                                                               "Cache-Control": "no-store"})  # 2.190.0 D (#2496)
    return jsonify(dict(rep, currency=cur))


def _csv_safe(s):
    """No formula injection in spreadsheet programs."""
    from ..core.serializers import csv_cell  # 2.122.4 B (#2317): one shared helper
    return csv_cell(s)


# ---------------------------------------------------------------- billing on to the client
def _bill_doc(c, oid, did):
    try:
        did = int(did)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", "doc_id"))
    r = c.execute("SELECT * FROM office_docs WHERE id=? AND org_id=?", (did, oid)).fetchone()
    if not r or r["kind"] not in ("offer", "invoice"):
        raise Denied(404)
    ofx_need_editable(r)
    return r


@app.post("/api/office/trips/bill")
def rk_bill_post():
    """{doc_id, item_ids: [...], markup_pct?, one?} the receipts as external costs on a quotation / invoice in draft: one
    position per receipt (one=1: one position for all) at the end of its title page, unit flat, purchase = the amount in
    the office currency, rate = purchase plus markup_pct. Receipts already billed on an existing document: 409 (never
    twice). Answers {doc_id, positions, items: [ids]}; POST .../unbill takes it back."""
    from .docs import doc_items, recalc
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    r = _bill_doc(c, oid, b.get("doc_id"))
    ids = b.get("item_ids")
    if not isinstance(ids, list) or not ids or len(ids) > MAX_ITEMS or not all(isinstance(x, int) and not isinstance(x, bool) for x in ids):
        raise BadInput(tr("Invalid value: {0}", "item_ids"))
    mk = _amount(b.get("markup_pct"), "markup_pct", 0, 1000, allow_none=True) or dec(0)
    rows = c.execute(f"SELECT i.*, t.dest, t.date_from FROM office_trip_items i JOIN office_trips t ON t.id=i.trip_id AND t.org_id=i.org_id "
                     f"WHERE i.org_id=? AND i.id IN ({','.join('?' * len(ids))}) ORDER BY i.date, i.sort, i.id", [oid] + ids).fetchall()
    if len(rows) != len(set(ids)):
        raise Denied(404)
    # 2.47.3 (review S1): two parallel billings of the same receipts -> the second sees them billed (409), never twice
    write_lock(c, f"office_trips_bill_{int(oid)}")
    rows = c.execute(f"SELECT i.*, t.dest, t.date_from FROM office_trip_items i JOIN office_trips t ON t.id=i.trip_id AND t.org_id=i.org_id "
                     f"WHERE i.org_id=? AND i.id IN ({','.join('?' * len(ids))}) ORDER BY i.date, i.sort, i.id", [oid] + ids).fetchall()
    for x in rows:
        if _billed_ok(c, oid, dict(x)):
            raise Denied(409, tr("A receipt has already been billed"))
    lg = r["lang"] or "de"
    its = [oc_dec_fields(c, oid, "office_trip_items", x) for x in rows]
    if b.get("one"):
        tot = sum((dec(x["amount_home"]) for x in its), dec(0))
        dests = sorted({x["dest"] for x in its if x["dest"]})
        pos = [(tr("Travel expenses", lg=lg), ", ".join(dests)[:300], tot)]
    else:
        pos = [((rk_cat_label(x["category"], lg) + (": " + x["text"] if x["text"] else ""))[:300],
                ", ".join(v for v in (x["dest"], _fmt_day(x["date"] or x["date_from"], lg)) if v)[:300], dec(x["amount_home"])) for x in its]
    before = ofx_items_brief(doc_items(c, r["id"], oid))
    mx = c.execute("SELECT COALESCE(MAX(sort), 0) FROM office_doc_items WHERE doc_id=? AND org_id=? AND part_id IS NULL", (r["id"], oid)).fetchone()[0]
    pids = []
    for i, (title, detail, cost) in enumerate(pos):
        row = {"doc_id": r["id"], "org_id": oid, "sort": (mx or 0) + 1 + i, "kind": "service", "service_id": None, "title": title, "detail": detail,
               "qty": 1.0, "unit": "flat", "rate": float(money(cost * (1 + mk / 100))), "tax": "standard", "raw_fee": 0, "producing": 0,
               "intext": "extern", "cost": float(money(cost)), "discountable": 0}
        row = oc_item_store(c, oid, row)
        pids.append(insert_id(c, f"INSERT INTO office_doc_items({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values())))
    ts = iso(now_utc())
    for i, x in enumerate(its):
        c.execute("UPDATE office_trip_items SET billed_doc_id=?, billed_at=?, updated_at=? WHERE id=? AND org_id=?", (r["id"], ts, ts, x["id"], oid))
    ofx_log(c, oid, "items", doc_id=r["id"], detail={"before": before, "after": ofx_items_brief(doc_items(c, r["id"], oid))})
    recalc(c, oid, r["id"])
    bump(c)
    c.commit()
    return jsonify(doc_id=r["id"], number=r["number"], positions=pids, items=[x["id"] for x in its])


def _fmt_day(s, lg):
    if not s or not DATE_RE.match(s):
        return s or ""
    y, m, d = s.split("-")
    return f"{d}.{m}.{y}" if lg == "de" else s


@app.post("/api/office/trips/unbill")
def rk_unbill_post():
    """{item_ids, positions?} the undo of a billing: the receipts are free again; positions (ids from the billing's
    answer) are removed from the document while it is still a draft."""
    from .docs import doc_items, recalc
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    ids = b.get("item_ids") or []
    pids = b.get("positions") or []
    if not isinstance(ids, list) or not isinstance(pids, list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in ids + pids):
        raise BadInput(tr("Invalid value: {0}", "item_ids"))
    docs = set()
    if ids:
        for x in c.execute(f"SELECT billed_doc_id FROM office_trip_items WHERE org_id=? AND id IN ({','.join('?' * len(ids))})", [oid] + ids):
            if x[0]:
                docs.add(x[0])
        # 2.47.3 (review S2): receipts on a finalised document stay billed (it can no longer lose its positions);
        # 2.144.10 (#2576, review): except on a trial document - they are free for the real invoice
        c.execute(f"UPDATE office_trip_items SET billed_doc_id=NULL, billed_at=NULL, updated_at=? WHERE org_id=? AND id IN ({','.join('?' * len(ids))}) "
                  "AND NOT EXISTS (SELECT 1 FROM office_docs d WHERE d.id=office_trip_items.billed_doc_id AND d.trial=0 AND d.locked_at IS NOT NULL AND d.locked_at != '')",
                  [iso(now_utc()), oid] + ids)
    removed = 0
    for did in docs:
        r = c.execute("SELECT * FROM office_docs WHERE id=? AND org_id=?", (did, oid)).fetchone()
        if not r or r["locked_at"] or not pids:
            continue
        before = ofx_items_brief(doc_items(c, did, oid))
        n = c.execute(f"DELETE FROM office_doc_items WHERE doc_id=? AND org_id=? AND part_id IS NULL AND id IN ({','.join('?' * len(pids))})",
                      [did, oid] + pids).rowcount
        if n:
            removed += n
            ofx_log(c, oid, "items", doc_id=did, detail={"before": before, "after": ofx_items_brief(doc_items(c, did, oid))})
            recalc(c, oid, did)
    bump(c)
    c.commit()
    return jsonify(ok=True, removed=removed)


@app.get("/api/office/trips/bill-docs")
def rk_bill_docs():
    """?client_id= -> the quotations / invoices a receipt can be billed on (drafts, not finalised), the client's first."""
    c, uid, oid = _ctx()
    try:
        cid = int(request.args.get("client_id") or 0)
    except ValueError:
        cid = 0
    rows = c.execute("SELECT id, kind, number, project_title, client_id, date, status FROM office_docs WHERE org_id=? AND kind IN ('offer', 'invoice') "
                     "AND locked_at IS NULL AND status='draft' ORDER BY id DESC LIMIT 200", (oid,)).fetchall()
    out = [dict(r) for r in rows]
    out.sort(key=lambda d: 0 if cid and d["client_id"] == cid else 1)
    return jsonify(docs=out)
