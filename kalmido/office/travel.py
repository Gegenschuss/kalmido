"""Office & finance (2.47.3, #1022, part B): travel expenses. Trips (office_trips) with their receipts (office_trip_items),
the list of receipts not yet ticked "in DATEV", an evaluation by month / year / person / project / client / category (also
as CSV) and billing receipts on to a client (positions of a quotation / invoice with purchase = amount, marked so nothing is
billed twice). Kalmido keeps no receipt images: they live in DATEV (decision of 2026-10-08, variant A). 2.95.0 (#1932): the
per diem (Verpflegungsmehraufwand) of every trip with the BMF rates of the year (office/vma.py), its report as PDF / Excel /
CSV and the import of a per diem spreadsheet (office/vmaimport.py).

Every route: office_gate + office_org with the admin of the office area (like purchases). 2.545.0 (#4592): an org member
enters, changes and deletes their own trips (office/rights.py LEGACY_OWN, level "own": rk_trips / _trip filter by the
person, somebody else's trip = 404); approving, DATEV, billing, purposes and exports stay the admins'. Amounts are
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
from ..core.orgcrypt import oc_dec_col, oc_dec_fields, oc_enc_fields, oc_item_store
from ..core.i18n import N_, csv_dialect, tr
from ..core.db import body, bump, db, iso, now_utc
from ..core.access import Denied, live_sql, trash_sql, vis_sql
from ..core.errors import BadInput
from .pdf import pdf_date
from .calc import dec, dstr, money
from .model import office_gate, office_org, office_settings, pb_cl_live, pb_owner
from .ledger import ofx_items_brief, ofx_log, ofx_need_editable
from .olock import olk_need_trip_items, olk_trip_item_reason
from .vma import vma_trip
from .periodlock import period_need_open
from .rights import ofr_own_uid, NO_SPECIAL, ofr_allows

RK_CATS = (("car", N_("Car / fuel")), ("train", N_("Train")), ("flight", N_("Flight")), ("rental_car", N_("Rental car")),
           ("taxi", N_("Taxi / public transport")), ("parking", N_("Parking")), ("hotel", N_("Hotel")), ("meals", N_("Meals")),
           ("other", N_("Other|travel")))
RK_CAT_KEYS = tuple(k for k, _ in RK_CATS)
RK_PURPOSES = ("job", "acquisition")  # job = for a client / project; acquisition = acquisition / research
RK_BY = ("month", "year", "person", "project", "client", "category", "purpose")  # 2.117.0 A (#2292): + purpose
RK_OWN_RO = N_("This trip was entered by somebody else: you can read it, but not change it.")  # 2.187.1 B (#2735)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CUR_RE = re.compile(r"^[A-Z]{3}$")
CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_PEOPLE = 20
MAX_ITEMS = 200
RKA_MAX_PURPOSES = 200  # 2.117.0 A (#2292): own purposes per office area


from .model import office_ctx_admin as _ctx  # noqa: E402  2.149.0 G (#2517): was an own copy
from .homecur import hc_code, hc_home, hc_office_rate  # noqa: E402  2.189.0 B (#2475)
from . import model  # 2.369.5 (#2517): pulled up from functions
from .countries import fk_country_code  # 2.369.5 (#2517): pulled up from functions
from ..core.serializers import csv_cell  # 2.369.5 (#2517): pulled up from functions
from .docs import doc_items, recalc, ofd_free_receipts  # 2.369.5 (#2517): pulled up from functions
from .owrite import ow_history_answer, ow_kind, ow_need_row, ow_write  # noqa: E402  2.567.0 D (#4711): the saves go through the core's write layer
from .years import ofc_years, ofc_years_sql  # 2.593.0 (#4891): the years with data
from .okern import ofk_register, ofk_restore, ofk_trash  # noqa: E402  2.1005.0 (#5415): trips and receipts on the core's trash

ow_kind("office_trip", "office_trips")
ow_kind("office_trip_item", "office_trip_items")
ow_kind("office_trip_purpose", "office_trip_purposes")


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
    fn = getattr(model, "pb_cl_where", None)
    return fn(c, oid) if fn else ("org_id=?", [oid])


def rk_home_cur(c, oid):
    return hc_home(office_settings(c, oid))  # 2.189.0 B (#2475): the home currency, not the one of new documents


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
        pb_cl_live(c, oid, out["client_id"], cur["client_id"] if cur else None)  # 2.370.4 (#3089) N2
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
    own = ofr_own_uid("travel") is not None  # 2.187.0 (#2476, review): level "own" never ticks "in DATEV" (the bookkeeping does)
    if "datev" in b or not cur:
        out["datev"] = 1 if b.get("datev") and not own else (cur.get("datev", 0) if own and cur else 0)
    if "datev_no" in b or not cur:
        out["datev_no"] = _text(b.get("datev_no"), "datev_no", 60) if not own else ((cur or {}).get("datev_no") or "")
    if "vat_pct" in b or not cur:  # 2.545.0 (#4387): the VAT rate of the receipt (None = no input tax, as before)
        v = b.get("vat_pct")
        v = None if v in (None, "") else str(v)
        if v not in (None, "19", "7", "0"):
            raise BadInput(tr("Invalid value: {0}", "vat_pct"))
        out["vat_pct"] = v
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
            if ah is None and fx is None and "fx_rate" not in b and ("amount" in b or "currency" in b or not cur):
                fx = hc_office_rate(office_settings(c, oid), ccy) if hc_code(ccy) == ccy else None  # 2.189.0 B (#2475): the office rate as the default
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
    d = c.execute(f"SELECT id, number, kind, project_title, status FROM office_docs WHERE id=? AND org_id=? AND {live_sql()}",
                  (r["billed_doc_id"], oid)).fetchone()  # 2.1005.0 (#5415): a draft in the trash bills nothing
    return dict(d) if d else None


def _item_public(c, oid, r, docs):
    d = oc_dec_fields(c, oid, "office_trip_items", r)
    bd = docs.get(d.get("billed_doc_id")) if d.get("billed_doc_id") else None
    return {"id": d["id"], "trip_id": d["trip_id"], "date": d["date"], "category": d["category"], "amount": d["amount"], "currency": d["currency"],
            "fx_rate": format(dec(d["fx_rate"]).normalize(), "f") if d.get("fx_rate") is not None else None, "amount_home": d["amount_home"], "text": d["text"],
            "datev": d["datev"], "datev_no": d["datev_no"], "billed": bd, "billed_at": d.get("billed_at") if bd else None,
            "vat_pct": d.get("vat_pct"), "updated_at": d.get("updated_at") or ""}  # 2.545.0 (#4387); 2.560.0 D (#4700): the version the dialog sends back


def _docs_map(c, oid):
    return {r["id"]: {"id": r["id"], "number": r["number"], "kind": r["kind"], "project_title": r["project_title"]}
            for r in c.execute(f"SELECT id, number, kind, project_title FROM office_docs WHERE org_id=? AND {live_sql()} AND id IN "  # 2.1005.0 (#5415)
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
            "vma_off": vf["vma_off"], "vma": vma, "updated_at": d.get("updated_at") or ""}  # 2.560.0 D (#4700): the version the dialog sends back


def rk_trips(c, oid, year=None, trip_id=None):
    sql, args = f"SELECT * FROM office_trips WHERE org_id=? AND {live_sql()}", [oid]  # 2.1005.0 (#5415): never the trash
    own = ofr_own_uid("travel")  # 2.187.0 B (#2476): office groups, level "own": only the person's own trips
    if trip_id is not None:
        sql += " AND id=?"
        args.append(trip_id)
    elif year:
        sql += " AND (substr(date_from, 1, 4)=? OR substr(date_to, 1, 4)=?)"
        args += [str(year), str(year)]
    trips = c.execute(sql + " ORDER BY date_from DESC, id DESC", args).fetchall()
    if own is not None:  # 2.187.1 B (#2735): own = entered by the person or the person travelled (people may be encrypted)
        trips = rk_own_rows(c, oid, trips, own)  # 2.360.5 (#2753)
    if not trips:
        return []
    ids = [t["id"] for t in trips]
    by = {}
    for r in c.execute(f"SELECT * FROM office_trip_items WHERE org_id=? AND trip_id IN ({','.join('?' * len(ids))}) AND {live_sql()} ORDER BY date, sort, id", [oid] + ids):
        by.setdefault(r["trip_id"], []).append(r)
    docs = _docs_map(c, oid)
    out = [rk_trip_public(c, oid, t, by.get(t["id"], []), docs) for t in trips]
    if own is not None:  # 2.187.1 B (#2735): a trip somebody else entered for the person: read only
        for t, d in zip(trips, out):
            d["own_ro"] = 0 if t["created_by"] == own else 1
    return out


def rk_own_sees(c, oid, t, own):
    """2.187.1 B (#2735): trip row t belongs to person own: entered by them or they are one of its people."""
    return t["created_by"] == own or _travelled(oc_dec_col(c, oid, "office_trips", "people", [t["people"]])[0], own)


def _travelled(v, own):
    try:
        people = json.loads(v or "[]")
    except (ValueError, TypeError):
        return False
    return isinstance(people, list) and any(isinstance(p, dict) and p.get("id") == own for p in people)


def rk_own_rows(c, oid, trips, own):
    """2.360.5 (#2753): the trips of person own (rk_own_sees for a whole list): the people column decrypted only for the
    trips somebody else entered, the key read once."""
    other = [t for t in trips if t["created_by"] != own]
    people = oc_dec_col(c, oid, "office_trips", "people", [t["people"] for t in other])
    keep = {t["id"] for t, v in zip(other, people) if _travelled(v, own)}
    return [t for t in trips if t["created_by"] == own or t["id"] in keep]


def _trip_need_open(c, oid, t, *days, items=True):
    """2.148.0 A (#2471): 409 when trip t (its days, its receipts' days when items) or one of days lies in a locked month."""
    ds = [t["date_from"], t["date_to"], *days]
    if items:
        ds += [r["date"] for r in c.execute(f"SELECT date FROM office_trip_items WHERE trip_id=? AND org_id=? AND {live_sql()}", (t["id"], oid)).fetchall()]
    period_need_open(c, oid, *ds)


def _trip(c, oid, tid, deleted=False):
    """2.1005.0 (#5415): deleted=True also finds a trip of the core's trash (its restore), else the trash is 404."""
    r = c.execute("SELECT * FROM office_trips WHERE id=? AND org_id=?" + ("" if deleted else f" AND {live_sql()}"), (tid, oid)).fetchone()
    own = ofr_own_uid("travel")
    if not r or (own is not None and not rk_own_sees(c, oid, r, own)):  # 2.187.0 B (#2476): level "own": somebody else's = 404
        raise Denied(404)
    if own is not None and r["created_by"] != own:  # 2.187.1 B (#2735): entered by somebody else for the person: read only
        raise Denied(403, tr(RK_OWN_RO))
    return r


def _one(c, oid, tid):
    return rk_trips(c, oid, trip_id=tid)[0]


def _insert_item(c, oid, tid, row, sort=0):
    ts = iso(now_utc())
    row = dict(row, org_id=oid, trip_id=tid, sort=sort, created_at=ts, updated_at=ts)
    row = oc_enc_fields(c, oid, "office_trip_items", row)
    return insert_id(c, f"INSERT INTO office_trip_items({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))


def rk_real_projects(c, oid, uid):
    """2.489.0 (#2652): the real projects (lists) the travel expenses and the logbook offer to choose: the ones uid may see
    in this office's workspace only (an organisation's office: its lists; a personal office: the private ones), never the
    basket, archived, end-to-end encrypted (no readable name) or health / budget lists. [{id, name}]; the trip / drive keeps
    the chosen name as its text "project" (the free text stays the fallback, nothing new is stored)."""
    org = None if pb_owner(c, oid) is not None else oid
    rows = c.execute(f"SELECT id, name FROM lists WHERE is_inbox=0 AND archived=0 AND e2e IS NULL AND COALESCE(life, '') NOT IN ('health', 'budget') "
                     f"AND {'org_id IS NULL' if org is None else 'org_id=?'} AND id IN {vis_sql()} ORDER BY lower(name), id LIMIT 500",
                     ((uid, uid) if org is None else (org, uid, uid))).fetchall()
    return [{"id": r["id"], "name": r["name"]} for r in rows if (r["name"] or "").strip()]


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
    own = ofr_own_uid("travel")
    if own is not None:  # 2.187.1 B (#2735): the receipts of the person's trips (rk_trips: entered or travelled)
        missing = sum(t["missing"] for t in rk_trips(c, oid))
    else:
        missing = c.execute(f"SELECT COUNT(*) FROM office_trip_items WHERE org_id=? AND datev=0 AND {live_sql()}", (oid,)).fetchone()[0]
    clients = [{"id": r["id"], "name": r["name"]} for r in
               c.execute(f"SELECT id, name FROM clients WHERE {rk_cl_where(c, oid)[0]} AND archived=0 AND deleted_at IS NULL ORDER BY lower(name)", rk_cl_where(c, oid)[1])]
    projects = [r[0] for r in c.execute(f"SELECT DISTINCT project_title FROM office_docs WHERE org_id=? AND project_title<>'' AND {live_sql()} ORDER BY 1",
                                        (oid,))][:300]  # 2.1005.0 (#5415): not the trash
    if own is not None:  # 2.187.0 B (#2476): the project names of the invoices are not part of "own"
        projects = sorted({t["project"] for t in trips if t.get("project")})
    return jsonify(trips=trips, people=rk_people(c, oid, uid), clients=clients, projects=projects, currency=rk_home_cur(c, oid),
                   categories=[{"key": k, "label": tr(n)} for k, n in RK_CATS], missing=missing,
                   purposes=rka_purposes(c, oid), real_projects=rk_real_projects(c, oid, uid),  # 2.117.0 A (#2292); 2.489.0 (#2652)
                   years=rk_years(c, oid))  # 2.593.0 (#4891)


def rk_years(c, oid):
    """2.593.0 (#4891): {min, max} of the years of the trips the person sees (rk_trips' rights: level "own" = the person's
    own trips), from the first day to the last day (a trip over New Year counts in both, as ?year= does); None: no trip."""
    own = ofr_own_uid("travel")
    if own is None:
        return ofc_years_sql(c, "SELECT MIN(date_from), MAX(COALESCE(NULLIF(date_to, ''), date_from)) FROM office_trips "
                                f"WHERE org_id=? AND date_from>='1900' AND {live_sql()}", (oid,))
    rows = rk_own_rows(c, oid, c.execute(f"SELECT id, created_by, people, date_from, date_to FROM office_trips WHERE org_id=? AND {live_sql()}", (oid,)).fetchall(), own)
    return ofc_years([d for t in rows for d in (t["date_from"], t["date_to"])])


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
        if isinstance(bd, dict) and isinstance(bd.get("id"), int) and ofr_own_uid("travel") is None \
                and _billed_ok(c, oid, {"billed_doc_id": bd["id"]}):  # 2.187.0 (#2476, review): never by level "own"
            x = dict(x, billed_doc_id=bd["id"], billed_at=_text(its[i].get("billed_at"), "billed_at", 40) or ts)
        _insert_item(c, oid, tid, x, i)
    bump(c)
    c.commit()
    return jsonify(_one(c, oid, tid)), 201


@app.patch("/api/office/trips/<int:tid>")
def rk_trip_patch(tid):
    """2.567.0 D (#4711): through office/owrite.py ow_write -- lock, version (expect_updated_at; 409 with the trip under
    "current"), only the fields sent, history, updated_by, bump. Without expect_updated_at as before."""
    c, uid, oid = _ctx()
    _trip(c, oid, tid)  # the rights (level "own") as before
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))

    def clean(c, b, t):
        row = rk_trip_clean(c, oid, uid, b, t)
        if row:
            _trip_need_open(c, oid, t, row.get("date_from"), row.get("date_to"))  # 2.148.0 A (#2471)
        return row
    ow_write(c, uid, "office_trip", tid, b, clean, oid=oid, dec=lambda c, r: oc_dec_fields(c, oid, "office_trips", r),
             enc=lambda c, v: oc_enc_fields(c, oid, "office_trips", v), public=lambda c, t: _one(c, oid, tid))
    c.commit()
    return jsonify(_one(c, oid, tid))


@app.get("/api/office/trips/<int:tid>/history")
def rk_trip_history(tid):
    """2.570.0 (#4783): the history (office/owrite.py ow_history) with the rights of the save route."""
    c, uid, oid = _ctx()
    _trip(c, oid, tid)
    return ow_history_answer(c, "office_trip", tid, oid)


@app.delete("/api/office/trips/<int:tid>")
def rk_trip_delete(tid):
    """Deletes a trip with its receipts; answers the trip as it was and 2.1005.0 (#5415) where it lies in the core's trash
    (trash = {kind, id}: the client's undo POST /api/office/trips/<id>/restore; the office trash lists it until its period ends)."""
    c, uid, oid = _ctx()
    _trip_need_open(c, oid, _trip(c, oid, tid))  # 2.148.0 A (#2471)
    # 2.152.0 C (#2168): receipts in DATEV / billed on a finalised document are kept by law -> the trip stays (409)
    olk_need_trip_items(c, oid, c.execute(f"SELECT * FROM office_trip_items WHERE trip_id=? AND org_id=? AND {live_sql()}", (tid, oid)).fetchall())
    old = _one(c, oid, tid)
    ofk_trash(c, uid, RK_TRIP_KIND, tid)  # 2.1005.0 (#5415): the core's trash (deleted_at), its live receipts go with it (children)
    c.commit()
    return jsonify(ok=True, trip=old, trash={"kind": RK_TRIP_KIND, "id": tid})


@app.post("/api/office/trips/<int:tid>/restore")
def rk_trip_restore(tid):
    """2.1005.0 (#5415): the undo of deleting a trip: out of the core's trash with the receipts that went with it (the trip's
    rights as deleting it, level "own": the person's own trip), only into open months (409) -> the trip. Past the trash period:
    gone (404). A live trip answers as it is."""
    c, uid, oid = _ctx()
    write_lock(c, f"office_trip_trash_{int(tid)}")
    r = _trip(c, oid, tid, deleted=True)
    if r["deleted_at"]:
        ofk_restore(c, uid, RK_TRIP_KIND, tid)
        _rk_trip_back(c, oid, dict(r))
        ofx_log(c, oid, "restore", target="trip", detail={"id": tid})
        bump(c)
        c.commit()
    return jsonify(_one(c, oid, tid))


@app.post("/api/office/trips/<int:tid>/items")
def rk_item_post(tid):
    """A new receipt {date, category, amount, currency, fx_rate | amount_home, text, datev, datev_no}. 201 the trip."""
    c, uid, oid = _ctx()
    _trip(c, oid, tid)
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    if c.execute(f"SELECT COUNT(*) FROM office_trip_items WHERE trip_id=? AND org_id=? AND {live_sql()}", (tid, oid)).fetchone()[0] >= MAX_ITEMS:
        raise BadInput(tr("Too many entries"))
    row = rk_item_clean(c, oid, b, home=rk_home_cur(c, oid))
    _trip_need_open(c, oid, _trip(c, oid, tid), row.get("date"), items=False)  # 2.148.0 A (#2471)
    mx = c.execute("SELECT COALESCE(MAX(sort), 0) FROM office_trip_items WHERE trip_id=? AND org_id=?", (tid, oid)).fetchone()[0]
    iid = _insert_item(c, oid, tid, row, (mx or 0) + 1)
    c.execute("UPDATE office_trips SET updated_at=? WHERE id=? AND org_id=?", (iso(now_utc()), tid, oid))
    bump(c)
    c.commit()
    return jsonify(dict(_one(c, oid, tid), item_id=iid)), 201


def _item(c, oid, tid, iid, deleted=False):
    _trip(c, oid, tid)  # 2.187.0 B (#2476): the trip's checks (level "own")
    r = c.execute("SELECT * FROM office_trip_items WHERE id=? AND trip_id=? AND org_id=?" + ("" if deleted else f" AND {live_sql()}"),  # 2.1005.0 (#5415)
                  (iid, tid, oid)).fetchone()
    if not r:
        raise Denied(404)
    return r


RK_LOCKED_KEYS = ("datev", "amount", "currency", "fx_rate", "amount_home", "date", "vat_pct")  # 2.545.0 (#4387): + VAT rate


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
    """2.567.0 D (#4711): through ow_write like the trip (409 with the receipt under "current")."""
    c, uid, oid = _ctx()
    _item(c, oid, tid, iid)  # the trip's rights, the receipt is there
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))

    def clean(c, b, cur):
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
        return row
    ow_write(c, uid, "office_trip_item", iid, b, clean, where=f"id=? AND trip_id=? AND org_id=? AND {live_sql()}", args=(iid, tid, oid), oid=oid,  # 2.1005.0 (#5415)
             dec=lambda c, r: oc_dec_fields(c, oid, "office_trip_items", r), enc=lambda c, v: oc_enc_fields(c, oid, "office_trip_items", v),
             public=lambda c, cur: next((x for x in _one(c, oid, tid)["items"] if x["id"] == iid), None))
    c.commit()
    return jsonify(_one(c, oid, tid))


@app.get("/api/office/trips/<int:tid>/items/<int:iid>/history")
def rk_item_history(tid, iid):
    """2.570.0 (#4783): the history (office/owrite.py ow_history) with the rights of the save route."""
    c, uid, oid = _ctx()
    _item(c, oid, tid, iid)
    return ow_history_answer(c, "office_trip_item", iid, oid)


@app.delete("/api/office/trips/<int:tid>/items/<int:iid>")
def rk_item_delete(tid, iid):
    """Deletes a receipt; answers the trip and the receipt as it was (for the undo)."""
    c, uid, oid = _ctx()
    r = _item(c, oid, tid, iid)
    _trip_need_open(c, oid, _trip(c, oid, tid), r["date"], items=False)  # 2.148.0 A (#2471)
    olk_need_trip_items(c, oid, [r])  # 2.152.0 C (#2168): in DATEV / billed on a finalised document -> 409
    old = _item_public(c, oid, r, _docs_map(c, oid))
    ofk_trash(c, uid, RK_ITEM_KIND, iid)  # 2.1005.0 (#5415): the core's trash (deleted_at); restorable while the trip is live
    c.commit()
    return jsonify(trip=_one(c, oid, tid), item=old, trash={"kind": RK_ITEM_KIND, "id": iid})


@app.post("/api/office/trips/<int:tid>/items/<int:iid>/restore")
def rk_item_restore(tid, iid):
    """2.1005.0 (#5415): the undo of deleting a receipt: out of the core's trash (the trip's rights; the trip live and the
    receipt's day in an open month, else 409) -> the trip."""
    c, uid, oid = _ctx()
    write_lock(c, f"office_trip_trash_{int(tid)}")
    r = _item(c, oid, tid, iid, deleted=True)
    if r["deleted_at"]:
        ofk_restore(c, uid, RK_ITEM_KIND, iid)
        _rk_item_back(c, oid, dict(r))
        ofx_log(c, oid, "restore", target="trip_item", detail={"id": iid})
        bump(c)
        c.commit()
    return jsonify(_one(c, oid, tid))


# ---------------------------------------------------------------- 2.530.0 C (#4315, B17): trips and receipts in the office trash
def rk_trash_span(t):
    """The days of a trip for the trash label (no sealed field: the label is stored plain)."""
    a, b = t.get("date_from") or "", t.get("date_to") or ""
    return a if not b or a == b else f"{a} – {b}"


def _rk_trip_label(c, oid, row):
    d = oc_dec_fields(c, oid, "office_trips", row)
    return " · ".join(x for x in (d.get("dest") or "", rk_trash_span(d)) if x)


def _rk_item_label(c, oid, row):
    cat = dict(RK_CATS).get(row.get("category"))
    return " · ".join(x for x in (tr(cat) if cat else "", row.get("date") or "") if x)


def _rk_trip_back(c, oid, row):
    """2.1005.0 (#5415): after the restore of a trip (its own route, the office trash; same transaction): its days and its
    receipts' days in open months (2.148.0 A, #2471; else 409, rolled back). A trip of a per diem import taken back
    (vmaimport.vmi_remove leaves it in the trash with updated_at = created_at, a single delete stamps the time) comes back
    unchanged (a second take-back takes it again) and its run counts as not undone again."""
    tid = row["id"]
    _trip_need_open(c, oid, _trip(c, oid, tid))
    if row.get("import_run_id") and row.get("updated_at") and row.get("updated_at") == row.get("created_at"):
        c.execute("UPDATE office_trips SET updated_at=created_at WHERE id=? AND org_id=?", (tid, oid))
        c.execute("UPDATE office_import_runs SET undone_at=NULL, undone_by=NULL WHERE id=? AND org_id=? AND undone_at IS NOT NULL",
                  (row["import_run_id"], oid))


RK_TRIP_GONE = N_("The trip is in the trash; restore it first")


def _rk_item_back(c, oid, row):
    """2.1005.0 (#5415): after the restore of a receipt: only into a live trip (409) and an open month (#2471, #4555: the
    trip's days and the receipt's own date, not the trip's other receipts)."""
    if not c.execute(f"SELECT 1 FROM office_trips WHERE id=? AND org_id=? AND {live_sql()}", (row["trip_id"], oid)).fetchone():
        raise Denied(409, tr(RK_TRIP_GONE))
    _trip_need_open(c, oid, _trip(c, oid, row["trip_id"]), row.get("date"), items=False)


RK_TRIP_KIND = "otrip"  # 2.1005.0 (#5415): a trip in the core's trash (with its receipts: children)
RK_ITEM_KIND = "otripitem"  # a travel receipt deleted on its own
ofk_register(RK_TRIP_KIND, "office_trips", N_("Trip"), "travel", need="own", children=(("office_trip_items", "trip_id"),),
             view={"kind": "trip", "label": _rk_trip_label, "ctx": _ctx, "back": _rk_trip_back}, step=False)
ofk_register(RK_ITEM_KIND, "office_trip_items", N_("Travel receipt"), "travel", need="own",
             view={"kind": "trip_item", "label": _rk_item_label, "ctx": _ctx, "back": _rk_item_back,
                   # the receipts that went into the trash with their trip are the trip's entry, not entries of their own
                   "where": f"NOT EXISTS (SELECT 1 FROM office_trips t WHERE t.id=office_trip_items.trip_id AND {trash_sql('t')})"}, step=False)
# step=False: no step in the person's undo list -- a redo / undo through /api/undo would skip the open-month and DATEV checks


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
    """{name} renames an own purpose; the trips keep the text they have. 2.567.0 D (#4711): through ow_write (version
    optional, 409 under "current"); the answer carries updated_at."""
    c, uid, oid = _ctx()
    _purpose(c, oid, pid)
    b = body()
    b = b if isinstance(b, dict) else {}
    name = rka_purpose_name(b.get("name"))
    for r in c.execute("SELECT id, name FROM office_trip_purposes WHERE org_id=? AND deleted_at IS NULL AND id<>?", (oid, pid)).fetchall():
        if r["name"].casefold() == name.casefold():
            raise BadInput(tr("This purpose already exists"))
    row, _ = ow_write(c, uid, "office_trip_purpose", pid, b, lambda c, b, cur: {"name": name}, where="id=? AND org_id=? AND deleted_at IS NULL",
                      oid=oid, public=lambda c, cur: {"id": cur["id"], "name": cur["name"], "updated_at": cur["updated_at"]})
    c.commit()
    return jsonify(id=pid, name=row["name"], updated_at=row["updated_at"])


@app.get("/api/office/trips/purposes/<int:pid>/history")
def rka_purpose_history(pid):
    """2.570.0 (#4783): the history (office/owrite.py ow_history) with the rights of the save route."""
    c, uid, oid = _ctx()
    ow_need_row(c, "office_trip_purposes", "id=? AND org_id=? AND deleted_at IS NULL", (pid, oid))
    return ow_history_answer(c, "office_trip_purpose", pid, oid)


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
        if not ofr_allows(c, uid, oid, "travel", "own", "export"):  # 2.237.0 A (#2861): the file needs the special export
            raise Denied(403, tr(NO_SPECIAL))
        buf = io.StringIO()
        sep, num = csv_dialect()  # 2.368.2 (#2984): separator and decimal sign of the language
        w = csv.writer(buf, delimiter=sep)
        head = {"month": tr("Month"), "year": tr("Year"), "person": tr("Person"), "project": tr("Project"), "client": tr("Client"), "category": tr("Category"), "purpose": tr("Purpose")}[by]
        w.writerow([head, tr("Receipts"), tr("Amount") + f" ({cur})"])
        for g in rep["rows"]:
            w.writerow([_csv_safe(g["label"]), g["count"], num(g["amount"])])
        w.writerow([tr("Total"), rep["count"], num(rep["total"])])
        name = f"travel-{by}-{df or 'all'}-{dt or 'all'}{'-' + re.sub(r'[^a-z0-9]+', '-', person.lower()).strip('-') if person else ''}.csv"
        return Response("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"',
                                                                                               "Cache-Control": "no-store"})  # 2.190.0 D (#2496)
    return jsonify(dict(rep, currency=cur))


def _csv_safe(s):
    """No formula injection in spreadsheet programs."""
    return csv_cell(s)


# ---------------------------------------------------------------- billing on to the client
def _bill_doc(c, oid, did):
    try:
        did = int(did)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", "doc_id"))
    write_lock(c, f"office_doc_{did}")  # 2.269.0 A (#3012): the document first (before the billing lock), like its own saves
    r = c.execute(f"SELECT * FROM office_docs WHERE id=? AND org_id=? AND {live_sql()}", (did, oid)).fetchone()  # 2.1005.0 (#5415): never into the trash
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
                     f"WHERE i.org_id=? AND i.id IN ({','.join('?' * len(ids))}) AND {live_sql('i')} AND {live_sql('t')} ORDER BY i.date, i.sort, i.id", [oid] + ids).fetchall()
    if len(rows) != len(set(ids)):
        raise Denied(404)
    # 2.47.3 (review S1): two parallel billings of the same receipts -> the second sees them billed (409), never twice
    write_lock(c, f"office_trips_bill_{int(oid)}")
    rows = c.execute(f"SELECT i.*, t.dest, t.date_from FROM office_trip_items i JOIN office_trips t ON t.id=i.trip_id AND t.org_id=i.org_id "
                     f"WHERE i.org_id=? AND i.id IN ({','.join('?' * len(ids))}) AND {live_sql('i')} AND {live_sql('t')} ORDER BY i.date, i.sort, i.id", [oid] + ids).fetchall()
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
    mx = c.execute(f"SELECT COALESCE(MAX(sort), 0) FROM office_doc_items WHERE doc_id=? AND org_id=? AND part_id IS NULL AND {live_sql()}",
                   (r["id"], oid)).fetchone()[0]  # 2.1005.0 (#5415): as outlays.py
    pids = []
    for i, (title, detail, cost) in enumerate(pos):
        row = {"doc_id": r["id"], "org_id": oid, "sort": (mx or 0) + 1 + i, "kind": "service", "service_id": None, "title": title, "detail": detail,
               "qty": 1.0, "unit": "flat", "rate": float(money(cost * (1 + mk / 100))), "tax": "standard", "raw_fee": 0, "producing": 0,
               "intext": "extern", "cost": float(money(cost)), "discountable": 0}
        row = oc_item_store(c, oid, row)
        pids.append(insert_id(c, f"INSERT INTO office_doc_items({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values())))
    ts = iso(now_utc())
    for i, x in enumerate(its):  # 2.269.0 A (#3012): + the position it became (one=1: the same for all)
        c.execute("UPDATE office_trip_items SET billed_doc_id=?, billed_item_id=?, billed_at=?, updated_at=? WHERE id=? AND org_id=?",
                  (r["id"], pids[0 if b.get("one") else i], ts, ts, x["id"], oid))
    ofx_log(c, oid, "items", doc_id=r["id"], detail={"before": before, "after": ofx_items_brief(doc_items(c, r["id"], oid))})
    recalc(c, oid, r["id"])
    bump(c)
    c.commit()
    return jsonify(doc_id=r["id"], number=r["number"], positions=pids, items=[x["id"] for x in its])


def _fmt_day(s, lg):
    """2.368.2 (#2986): the date of an invoice line as on the rest of the document (was ISO in every language but German)."""
    return pdf_date(s, str(lg).split("-")[0]) if s and DATE_RE.match(s) else s or ""


@app.post("/api/office/trips/unbill")
def rk_unbill_post():
    """{item_ids, positions?} the undo of a billing: the receipts are free again; positions (ids from the billing's
    answer) are removed from the document while it is still a draft."""
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
        for did in sorted(docs):
            write_lock(c, f"office_doc_{int(did)}")  # 2.269.0 A (#3012): never in between a save of the document
        pids = pids + rk_linked_positions(c, oid, ids)
        # 2.47.3 (review S2): receipts on a finalised document stay billed (it can no longer lose its positions);
        # 2.144.10 (#2576, review): except on a trial document - they are free for the real invoice
        c.execute(f"UPDATE office_trip_items SET billed_doc_id=NULL, billed_at=NULL, billed_item_id=NULL, updated_at=? WHERE org_id=? AND id IN ({','.join('?' * len(ids))}) "
                  "AND NOT EXISTS (SELECT 1 FROM office_docs d WHERE d.id=office_trip_items.billed_doc_id AND d.trial=0 AND d.locked_at IS NOT NULL AND d.locked_at != '')",
                  [iso(now_utc()), oid] + ids)
    removed = 0
    for did in docs:
        r = c.execute("SELECT * FROM office_docs WHERE id=? AND org_id=?", (did, oid)).fetchone()
        if not r or r["locked_at"] or not pids:
            continue
        before = ofx_items_brief(doc_items(c, did, oid))
        n = c.execute(f"DELETE FROM office_doc_items WHERE doc_id=? AND org_id=? AND part_id IS NULL AND {live_sql()} AND id IN ({','.join('?' * len(pids))})",
                      [did, oid] + pids).rowcount  # 2.1005.0 (#5415): a trash row stays with its part (as outlays.py)
        if n:
            removed += n
            ofx_log(c, oid, "items", doc_id=did, detail={"before": before, "after": ofx_items_brief(doc_items(c, did, oid))})
            ofd_free_receipts(c, oid, did)  # 2.269.0 A (#3012): other receipts of a removed position are open again
            recalc(c, oid, did)
    bump(c)
    c.commit()
    return jsonify(ok=True, removed=removed)


def rk_linked_positions(c, oid, ids):
    """2.269.0 A (#3012): the positions the receipts ids were billed as (the kept ids), each only when every receipt billed
    as it is among ids (one position for several receipts stays while one of them is still billed). Older billings: none."""
    q = ",".join("?" * len(ids))
    pos = {x[0] for x in c.execute(f"SELECT billed_item_id FROM office_trip_items WHERE org_id=? AND id IN ({q}) AND billed_item_id IS NOT NULL", [oid] + ids)}
    if not pos:
        return []
    q2 = ",".join("?" * len(pos))
    busy = {x[0] for x in c.execute(f"SELECT billed_item_id FROM office_trip_items WHERE org_id=? AND billed_item_id IN ({q2}) AND id NOT IN ({q})", [oid, *pos, *ids])}
    return sorted(pos - busy)


@app.get("/api/office/trips/bill-docs")
def rk_bill_docs():
    """?client_id= -> the quotations / invoices a receipt can be billed on (drafts, not finalised), the client's first."""
    c, uid, oid = _ctx()
    try:
        cid = int(request.args.get("client_id") or 0)
    except ValueError:
        cid = 0
    rows = c.execute("SELECT id, kind, number, project_title, client_id, date, status FROM office_docs WHERE org_id=? AND kind IN ('offer', 'invoice') "
                     f"AND locked_at IS NULL AND status='draft' AND {live_sql()} ORDER BY id DESC LIMIT 200", (oid,)).fetchall()  # 2.1005.0 (#5415): not the trash
    out = [dict(r) for r in rows]
    out.sort(key=lambda d: 0 if cid and d["client_id"] == cid else 1)
    return jsonify(docs=out)
