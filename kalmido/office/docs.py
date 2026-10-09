"""Office & finance (2.36.1, #1021), part C: quotations (documents of kind "offer") and their positions.
Tables office_docs / office_doc_items (schema.py). Every route: office_gate (no agents, no kids, feature on) + office_org
(the organisation one works in); members read and write quotations, only the organisation's admin deletes them and sees
the internal costs / margin. The sums come from kalmido/office/calc.py (office_calc) and are cached in office_docs.totals.
odoc_render(c, doc_id) builds the print model (see docs/OFFICE.md) that the PDF writer (part D) and the preview use."""
import json
import re
from datetime import date, timedelta

from flask import g, jsonify, request

from ..core.config import app
from ..core.i18n import N_, tr
from ..core.db import body, bump, db, err, iso, local_now, now_utc
from ..core.access import Denied
from ..personal.timetrack import BadInput
from .calc import RAW_MODES, TAX_KEYS, dec, fmt_money, office_calc
from .packs import office_pack
from .model import (NAME_MAX, TEXT_MAX, UNITS, office_gate, office_org, office_number_next, office_role, office_settings,
                    office_seed_texts)

DOC_KINDS = ("offer",)
STATUSES = ("draft", "sent", "accepted", "declined")
ITEM_KINDS = ("service", "text", "heading")
STATUS_TXT = {"draft": N_("Draft"), "sent": N_("Sent"), "accepted": N_("Accepted"), "declined": N_("Declined")}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_ITEMS = 300
MAX_FIELDS = 20


def _ctx(admin=False):
    c = db()
    uid = office_gate(c)
    return c, uid, office_org(c, uid, admin=admin)


def _j(s, default):
    try:
        v = json.loads(s) if s else default
    except ValueError:
        return default
    return v if isinstance(v, type(default)) else default


def _date(v, name):
    if v in (None, ""):
        return ""
    if isinstance(v, str) and DATE_RE.match(v.strip()):
        try:
            date.fromisoformat(v.strip())
            return v.strip()
        except ValueError:
            pass
    raise BadInput(tr("Invalid value: {0}", name))


def _text(v, name, mx=TEXT_MAX):
    if v is None:
        return ""
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", name))
    return v.strip()[:mx]


def _num(v, name, lo=None, hi=None):
    if v in (None, ""):
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise BadInput(tr("Invalid value: {0}", name))
    try:
        d = dec(v, "NaN")
    except Exception:
        raise BadInput(tr("Invalid value: {0}", name))
    if d.is_nan() or not d.is_finite():
        raise BadInput(tr("Invalid value: {0}", name))
    if (lo is not None and d < lo) or (hi is not None and d > hi):
        raise BadInput(tr("Invalid value: {0}", name))
    return float(d)


def _choice(v, name, choices):
    if v not in choices:
        raise BadInput(tr("Invalid value: {0}", name))
    return v


def _fmt_date(s, pack):
    """2026-10-09 -> 09.10.2026 by the pack's date format (dd.mm.yyyy / yyyy-mm-dd / mm/dd/yyyy)."""
    if not s:
        return ""
    f = ((pack or {}).get("formats") or {}).get("date") or "dd.mm.yyyy"
    try:
        d = date.fromisoformat(s)
    except ValueError:
        return s
    return f.replace("dd", f"{d.day:02d}").replace("mm", f"{d.month:02d}").replace("yyyy", str(d.year)).replace("yy", str(d.year)[2:])


# ---------------------------------------------------------------- rows
def doc_row(c, oid, did):
    try:
        did = int(did)
    except (TypeError, ValueError):
        raise Denied(404)
    r = c.execute("SELECT * FROM office_docs WHERE id=? AND org_id=?", (did, oid)).fetchone()
    if not r:
        raise Denied(404)
    return r


def doc_items(c, did):
    return [dict(r) for r in c.execute("SELECT * FROM office_doc_items WHERE doc_id=? ORDER BY sort, id", (did,))]


def _texts(c, oid, kind=None):
    sql = "SELECT * FROM office_texts WHERE org_id=? AND archived=0"
    args = [oid]
    if kind:
        sql += " AND kind=?"
        args.append(kind)
    return [dict(r) for r in c.execute(sql + " ORDER BY kind, sort, id", args)]


def _iid(v):
    """An id from client data; anything that is not a whole number matches no row (instead of a 500)."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _text_of(c, oid, tid, lang):
    if not tid:
        return None
    r = c.execute("SELECT text_de, text_en FROM office_texts WHERE id=? AND org_id=?", (_iid(tid), oid)).fetchone()
    if not r:
        return None
    return (r["text_en"] if lang == "en" else r["text_de"]) or r["text_de"] or r["text_en"] or ""


def _contract(c, oid, cid):
    if not cid:
        return None
    r = c.execute("SELECT * FROM office_contracts WHERE id=? AND org_id=?", (_iid(cid), oid)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["rates"] = _j(d.get("rates"), {})
    return d


def _service(c, oid, sid):
    if not sid:
        return None
    r = c.execute("SELECT * FROM office_services WHERE id=? AND org_id=?", (_iid(sid), oid)).fetchone()
    return dict(r) if r else None


def _client(c, oid, cid):
    if not cid:
        return None
    r = c.execute("SELECT id, name, contact, address, email FROM clients WHERE id=? AND org_id=?", (_iid(cid), oid)).fetchone()
    return dict(r) if r else None


def _recipient_from_client(cl):
    lines = [cl["name"]]
    if cl.get("contact"):
        lines.append(cl["contact"])
    lines += [x.strip() for x in (cl.get("address") or "").replace("\r", "").split("\n") if x.strip()]
    return {"name": cl["name"], "lines": lines[:12]}


# ---------------------------------------------------------------- the document as the client sees it
def _calc_doc(r):
    return {"lang": r["lang"], "currency": r["currency"], "fx_rate": r["fx_rate"], "vat_mode": r["vat_mode"], "raw_mode": r["raw_mode"],
            "raw_factor": r["raw_factor"], "prod_quotient": r["prod_quotient"], "producing_rate": r["producing_rate"],
            "discount_pct": r["discount_pct"]}


def doc_totals(c, oid, r, items=None):
    s = office_settings(c, oid)
    pack = office_pack(s["pack"]) or office_pack("DE")
    return office_calc(_calc_doc(r), items if items is not None else doc_items(c, r["id"]), pack)


def recalc(c, oid, did):
    """Recomputes and caches the totals of document did (after any change of its head or positions)."""
    r = doc_row(c, oid, did)
    t = doc_totals(c, oid, r)
    c.execute("UPDATE office_docs SET totals=?, updated_at=? WHERE id=?", (json.dumps(t, ensure_ascii=False), iso(now_utc()), did))
    return t


def doc_public(c, oid, r, admin, items=True):
    d = dict(r)
    for k, dflt in (("recipient", {}), ("rights", {}), ("fields", []), ("totals", {})):
        d[k] = _j(d.get(k), dflt)
    d["status_text"] = tr(STATUS_TXT.get(d["status"], d["status"]))
    d["net_text"] = fmt_money(d["totals"].get("net") or 0, d["lang"], d["currency"])
    if not admin:
        d["totals"] = {k: v for k, v in d["totals"].items() if k not in ("costs", "margin")}
    if items:
        its = doc_items(c, r["id"])
        for it in its:
            it["discountable"] = int(it.get("discountable") or 0)
            if not admin:
                it["cost"] = None
        d["items"] = its
        d["contract"] = _contract(c, oid, d.get("contract_id"))
        if d["contract"]:
            d["contract"] = {k: d["contract"][k] for k in ("id", "name", "raw_included", "rates", "rights_time_id", "rights_territory_id",
                                                             "rights_media_id", "rights_note_de", "rights_note_en", "closing_de", "closing_en", "date")}
    d["can_delete"] = bool(admin)
    return d


def doc_brief(r):
    rec = _j(r["recipient"], {})
    t = _j(r["totals"], {})
    return {"id": r["id"], "kind": r["kind"], "number": r["number"], "status": r["status"], "status_text": tr(STATUS_TXT.get(r["status"], r["status"])),
            "lang": r["lang"], "currency": r["currency"], "client_id": r["client_id"], "recipient_name": rec.get("name") or "",
            "project_title": r["project_title"], "project_ref": r["project_ref"], "date": r["date"], "valid_until": r["valid_until"],
            "net": t.get("net") or 0, "net_text": fmt_money(t.get("net") or 0, r["lang"], r["currency"]),
            "net_incl_raw": t.get("net_incl_raw"), "updated_at": r["updated_at"], "created_by": r["created_by"]}


# ---------------------------------------------------------------- cleaning
def _rights_clean(c, oid, v, lang, cur):
    """{time: {id, text}, territory: {...}, media: {...}, exceptions, exclusive, note}: an id without text takes the
    catalogue's text in the document's language (snapshot: the text stays when the catalogue changes later)."""
    if not isinstance(v, dict):
        raise BadInput(tr("Invalid value: {0}", "rights"))
    out = dict(cur or {})
    for dim in ("time", "territory", "media"):
        if dim not in v:
            continue
        x = v[dim]
        if x in (None, ""):
            out[dim] = {"id": None, "text": ""}
            continue
        if isinstance(x, str):
            x = {"id": None, "text": x}
        if not isinstance(x, dict):
            raise BadInput(tr("Invalid value: {0}", "rights." + dim))
        tid = x.get("id")
        if tid not in (None, ""):
            try:
                tid = int(tid)
            except (TypeError, ValueError):
                raise BadInput(tr("Invalid value: {0}", "rights." + dim))
        text = x.get("text")
        if (text is None or text == "") and tid:
            text = _text_of(c, oid, tid, lang) or ""
        out[dim] = {"id": tid or None, "text": _text(text, "rights." + dim, 1000)}
    if "exceptions" in v:
        out["exceptions"] = _text(v.get("exceptions"), "rights.exceptions", 2000)
    if "exclusive" in v:
        out["exclusive"] = 1 if v.get("exclusive") in (1, True, "1", "true") else 0
    if "note" in v:
        out["note"] = _text(v.get("note"), "rights.note", 2000)
    for dim in ("time", "territory", "media"):
        out.setdefault(dim, {"id": None, "text": ""})
    out.setdefault("exceptions", "")
    out.setdefault("exclusive", 0)
    out.setdefault("note", "")
    return out


def _fields_clean(v):
    if not isinstance(v, list) or len(v) > MAX_FIELDS:
        raise BadInput(tr("Invalid value: {0}", "fields"))
    out = []
    for f in v:
        if not isinstance(f, dict):
            raise BadInput(tr("Invalid value: {0}", "fields"))
        name, val = _text(f.get("name"), "fields", 80), _text(f.get("value"), "fields", 500)
        if name or val:
            out.append({"name": name, "value": val})
    return out


def _recipient_clean(v):
    if not isinstance(v, dict):
        raise BadInput(tr("Invalid value: {0}", "recipient"))
    lines = v.get("lines") or []
    if isinstance(lines, str):
        lines = lines.replace("\r", "").split("\n")
    if not isinstance(lines, list) or len(lines) > 12:
        raise BadInput(tr("Invalid value: {0}", "recipient"))
    lines = [_text(x, "recipient", 200) for x in lines]
    lines = [x for x in lines if x]
    return {"name": _text(v.get("name"), "recipient", NAME_MAX), "lines": lines}


def _rights_from_contract(c, oid, ct, lang):
    """The rights of a framework contract as a document snapshot."""
    out = {}
    for dim, col in (("time", "rights_time_id"), ("territory", "rights_territory_id"), ("media", "rights_media_id")):
        tid = ct.get(col)
        out[dim] = {"id": tid, "text": _text_of(c, oid, tid, lang) or ""} if tid else {"id": None, "text": ""}
    out["note"] = (ct.get("rights_note_en") if lang == "en" else ct.get("rights_note_de")) or ct.get("rights_note_de") or ""
    return out


def _default_text(c, oid, s, kind, lang):
    """The organisation's default text block of kind intro / closing in lang: the settings' choice, else the first one,
    else the pack's."""
    ids = s.get(kind + "_text_id") or {}
    t = _text_of(c, oid, ids.get(lang) if isinstance(ids, dict) else ids, lang)
    if t is None:
        rows = _texts(c, oid, kind)
        if rows:
            t = (rows[0]["text_en"] if lang == "en" else rows[0]["text_de"]) or rows[0]["text_de"]
    if t is None:
        pack = office_pack(s["pack"]) or office_pack("DE") or {}
        pt = (pack.get("texts") or {}).get(kind) or {}
        t = pt.get(lang) or pt.get("de") or ""
    if kind == "intro":
        pack = office_pack(s["pack"]) or office_pack("DE") or {}
        sal = ((pack.get("texts") or {}).get("salutation") or {}).get(lang) or ""
        if sal and not t.startswith(sal.split(",")[0]):
            t = sal + "\n" + t
    return t


def _apply_contract(c, oid, f, ct, lang, cur_rights):
    """The preset of a framework contract: raw data included, its rights, its closing (each only when it has one)."""
    f["raw_mode"] = "included" if ct.get("raw_included") else "optional"
    rights = dict(cur_rights or {})
    rights.update(_rights_from_contract(c, oid, ct, lang))
    f["rights"] = json.dumps(rights, ensure_ascii=False)
    closing = (ct.get("closing_en") if lang == "en" else ct.get("closing_de")) or ""
    if closing:
        f["closing"] = closing


def clean_doc(c, oid, b, cur, admin):
    """The changeable head fields of a document from body b (partial); cur = the row as it is. -> {column: value}"""
    f = {}
    lang = cur["lang"]
    if "lang" in b:
        f["lang"] = lang = _choice(b.get("lang"), "lang", ("de", "en"))
    if "currency" in b:
        f["currency"] = _choice(str(b.get("currency") or "").upper(), "currency", ("EUR", "USD"))
    if "fx_rate" in b:
        f["fx_rate"] = _num(b.get("fx_rate"), "fx_rate", 0.0001, 1000) or 1.09
    if "vat_mode" in b:
        f["vat_mode"] = _choice(b.get("vat_mode"), "vat_mode", ("vat", "novat"))
    if "client_id" in b:
        cid = b.get("client_id")
        if cid in (None, "", 0):
            f["client_id"] = None
        else:
            cl = _client(c, oid, cid)
            if not cl:
                raise Denied(404)
            f["client_id"] = cl["id"]
            if not b.get("recipient") and (not _j(cur["recipient"], {}).get("name") or b.get("recipient_from_client")):
                f["recipient"] = json.dumps(_recipient_from_client(cl), ensure_ascii=False)
    if "recipient" in b and b.get("recipient") is not None:
        f["recipient"] = json.dumps(_recipient_clean(b["recipient"]), ensure_ascii=False)
    for k, mx in (("project_title", NAME_MAX), ("project_ref", 80), ("intro", TEXT_MAX), ("closing", TEXT_MAX)):
        if k in b:
            f[k] = _text(b.get(k), k, mx)
    for k in ("date", "valid_until"):
        if k in b:
            f[k] = _date(b.get(k), k)
    if "raw_mode" in b:
        f["raw_mode"] = _choice(b.get("raw_mode"), "raw_mode", RAW_MODES)
    for k, lo, hi, dflt in (("raw_factor", 0, 10, 0.25), ("prod_quotient", 0.01, 1000, 3), ("producing_rate", 0, 1e7, 600), ("discount_pct", 0, 100, 0)):
        if k in b:
            v = _num(b.get(k), k, lo, hi)
            f[k] = dflt if v is None else v
    if "rights" in b and b.get("rights") is not None:
        f["rights"] = json.dumps(_rights_clean(c, oid, b["rights"], lang, _j(cur["rights"], {})), ensure_ascii=False)
    if "fields" in b and b.get("fields") is not None:
        f["fields"] = json.dumps(_fields_clean(b["fields"]), ensure_ascii=False)
    if "contract_id" in b:
        cid = b.get("contract_id")
        if cid in (None, "", 0):
            f["contract_id"] = None
        else:
            ct = _contract(c, oid, cid)
            if not ct:
                raise Denied(404)
            f["contract_id"] = ct["id"]
            if ct["id"] != cur["contract_id"] and b.get("apply_contract", True):
                _apply_contract(c, oid, f, ct, lang, _j(f.get("rights") or cur["rights"], {}))
    return f


def clean_items(c, oid, r, items, admin):
    """The whole list of positions: [{kind, service_id, title, detail, qty, unit, rate, tax, raw_fee, producing, intext,
    cost, discountable}]. A service_id fills what the position leaves empty (title in the document's language, rate from
    the framework contract or the catalogue, tax and flags). cost only by the admin (others keep the stored value)."""
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise BadInput(tr("Invalid value: {0}", "items"))
    lang = r["lang"]
    ct = _contract(c, oid, r["contract_id"])
    old = {it["id"]: it for it in doc_items(c, r["id"])}
    out = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            raise BadInput(tr("Invalid value: {0}", "items"))
        kind = it.get("kind") or "service"
        _choice(kind, "items.kind", ITEM_KINDS)
        row = {"sort": i, "kind": kind, "service_id": None, "title": _text(it.get("title"), "items.title", 500),
               "detail": _text(it.get("detail"), "items.detail", 4000), "qty": 1, "unit": "day", "rate": 0, "tax": "standard",
               "raw_fee": 0, "producing": 0, "intext": "intern", "cost": 0, "discountable": 1}
        prev = old.get(it.get("id")) if it.get("id") else None
        if kind == "service":
            sv = _service(c, oid, it.get("service_id")) if it.get("service_id") else None
            if it.get("service_id") and not sv:
                raise Denied(404)
            if sv:
                row["service_id"] = sv["id"]
                unit = it.get("unit") or sv["unit"] or "day"
                if not row["title"]:
                    row["title"] = (sv["name_en"] if lang == "en" else sv["name_de"]) or sv["name_de"]
                rate = it.get("rate")
                if rate in (None, ""):
                    if ct and str(sv["id"]) in (ct.get("rates") or {}):
                        rate = ct["rates"][str(sv["id"])]
                    else:
                        rate = sv["hourly_rate"] if unit == "hour" and sv["hourly_rate"] is not None else sv["daily_rate"]
                it = {**{"unit": unit, "tax": sv["tax"], "raw_fee": sv["raw_fee"], "producing": sv["producing"], "intext": sv["intext"]},
                      **{k: v for k, v in it.items() if v not in (None, "")}, "rate": rate}
            row["qty"] = _num(it.get("qty"), "items.qty", 0, 1e6)
            if row["qty"] is None:
                row["qty"] = 1
            row["unit"] = _choice(it.get("unit") or "day", "items.unit", UNITS)
            row["rate"] = _num(it.get("rate"), "items.rate", -1e8, 1e8) or 0
            row["tax"] = _choice(it.get("tax") or "standard", "items.tax", TAX_KEYS)
            row["raw_fee"] = 1 if it.get("raw_fee") in (1, True, "1", "true") else 0
            row["producing"] = 1 if it.get("producing") in (1, True, "1", "true") else 0
            row["intext"] = _choice(it.get("intext") or "intern", "items.intext", ("intern", "extern"))
            row["discountable"] = 0 if it.get("discountable") in (0, False, "0", "false") else 1
            if admin:
                row["cost"] = _num(it.get("cost"), "items.cost", 0, 1e8) or 0
            else:
                row["cost"] = (prev or {}).get("cost") or 0
        elif not row["title"] and not row["detail"]:
            raise BadInput(tr("Invalid value: {0}", "items.title"))
        out.append(row)
    return out


# ---------------------------------------------------------------- creating
def doc_create(c, oid, uid, b, admin):
    """A new quotation from the organisation's settings (+ a framework contract / client when given); the number is
    reserved at once."""
    s = office_settings(c, oid)
    kind = _choice(b.get("kind") or "offer", "kind", DOC_KINDS)
    lang = _choice(b.get("lang") or s.get("lang") or "de", "lang", ("de", "en"))
    today = local_now().date()
    prod_rate = s.get("producing_rate") or 600
    if s.get("producing_service_id"):
        sv = _service(c, oid, s["producing_service_id"])
        if sv and sv.get("daily_rate") is not None:
            prod_rate = sv["daily_rate"]
    rd = s.get("rights_default") or {}
    rights = {"time": {"id": None, "text": ""}, "territory": {"id": None, "text": ""}, "media": {"id": None, "text": ""},
              "exceptions": "", "exclusive": 0, "note": ""}
    for dim, key in (("time", "time_id"), ("territory", "territory_id"), ("media", "media_id")):
        if rd.get(key):
            rights[dim] = {"id": rd[key], "text": _text_of(c, oid, rd[key], lang) or ""}
    notes = _texts(c, oid, "note")
    if notes:
        rights["note"] = (notes[0]["text_en"] if lang == "en" else notes[0]["text_de"]) or notes[0]["text_de"]
    ts = iso(now_utc())
    row = {"org_id": oid, "kind": kind, "number": "", "status": "draft", "lang": lang, "currency": (s.get("currency") or "EUR").upper(),
           "fx_rate": s.get("fx_usd") or 1.09, "vat_mode": "vat", "client_id": None, "recipient": json.dumps({"name": "", "lines": []}),
           "project_title": "", "project_ref": "", "date": today.isoformat(),
           "valid_until": (today + timedelta(days=int(s.get("offer_valid_days") or 30))).isoformat(), "contract_id": None,
           "raw_mode": "optional", "raw_factor": s.get("raw_factor") if s.get("raw_factor") is not None else 0.25,
           "prod_quotient": s.get("prod_quotient") or 3, "producing_rate": prod_rate, "discount_pct": 0,
           "intro": _default_text(c, oid, s, "intro", lang), "closing": _default_text(c, oid, s, "closing", lang),
           "rights": json.dumps(rights, ensure_ascii=False), "fields": "[]", "totals": "{}", "created_by": uid, "created_at": ts,
           "updated_at": ts, "sent_at": None}
    if row["currency"] not in ("EUR", "USD"):
        row["currency"] = "EUR"
    cur = dict(row)
    cur["id"] = 0
    f = clean_doc(c, oid, {k: v for k, v in b.items() if k != "kind"}, cur, admin)
    row.update(f)
    did = c.execute(f"INSERT INTO office_docs({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values())).lastrowid
    _assign_number(c, oid, did, s)
    if isinstance(b.get("items"), list):
        _put_items(c, oid, doc_row(c, oid, did), b["items"], admin)
    recalc(c, oid, did)
    return did


def _assign_number(c, oid, did, s=None, manual=None):
    r = doc_row(c, oid, did)
    s = s or office_settings(c, oid)
    if manual is not None:
        num = _text(manual, "number", 80)
        if not num:
            raise BadInput(tr("Invalid value: {0}", "number"))
    else:
        rec = _j(r["recipient"], {})
        d = date.fromisoformat(r["date"]) if r["date"] else local_now().date()
        for _ in range(50):  # a scheme without {seq} uniqueness (e.g. only {date}): keep counting until free
            num, _seq = office_number_next(c, oid, r["kind"], s["offer_scheme"], d, project=r["project_title"], client=rec.get("name") or "",
                                           initials=_initials(c, r["created_by"]))
            if not c.execute("SELECT 1 FROM office_docs WHERE org_id=? AND number=? AND id!=?", (oid, num, did)).fetchone():
                break
    if c.execute("SELECT 1 FROM office_docs WHERE org_id=? AND number=? AND id!=?", (oid, num, did)).fetchone():
        raise BadInput(tr("The number {0} is already used", num))
    c.execute("UPDATE office_docs SET number=?, updated_at=? WHERE id=?", (num, iso(now_utc()), did))
    return num


def _initials(c, uid):
    r = c.execute("SELECT display_name, username FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    if not r:
        return ""
    name = r["display_name"] or r["username"] or ""
    return "".join(p[0] for p in name.split() if p)[:4].upper()


def _put_items(c, oid, r, items, admin):
    rows = clean_items(c, oid, r, items, admin)
    c.execute("DELETE FROM office_doc_items WHERE doc_id=?", (r["id"],))
    for row in rows:
        row["doc_id"] = r["id"]
        c.execute(f"INSERT INTO office_doc_items({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))


# ---------------------------------------------------------------- the print model
def odoc_render(c, doc_id, oid=None):
    """The print model of a document (dict, see docs/OFFICE.md and tests/fixtures): everything in the document's language
    and formats, nothing of the signed-in person. oid: the organisation the caller works in (foreign document = 404)."""
    r = c.execute("SELECT * FROM office_docs WHERE id=?", (int(doc_id),)).fetchone()
    if not r or (oid is not None and r["org_id"] != oid):
        raise Denied(404)
    oid = r["org_id"]
    s = office_settings(c, oid)
    pack = office_pack(s["pack"]) or office_pack("DE") or {}
    lang = "en" if r["lang"] == "en" else "de"
    L = dict((pack.get("labels") or {}).get(lang) or {})
    cur = r["currency"]
    t = doc_totals(c, oid, r)
    for ln in t["lines"]:
        if ln["kind"] in ("item", "producing", "raw", "discount"):
            ln["total_text"] = fmt_money(ln["total"], lang, cur)
            if ln.get("rate") is not None:
                ln["rate_text"] = fmt_money(ln["rate"], lang, cur)
    rec = _j(r["recipient"], {})
    rec = {"name": rec.get("name") or "", "lines": rec.get("lines") or []}
    rights = _j(r["rights"], {})
    co = s.get("company") or {}
    logo_path = None
    if s.get("logo"):
        import os
        from ..core.config import OFFICE_DIR
        p = os.path.join(OFFICE_DIR, str(oid), os.path.basename(s["logo"]))
        logo_path = p if os.path.isfile(p) else None
    color = s.get("color") or ""
    if not re.match(r"^#[0-9a-fA-F]{6}$", color):
        color = "#2f5d8a"
    valid_text = _fmt_date(r["valid_until"], pack)
    meta = [[L.get("offer_no", "Angebot Nr."), r["number"]], [L.get("date", "Datum"), _fmt_date(r["date"], pack)]]
    if rec["name"]:
        meta.append([L.get("client", "Kunde"), rec["name"]])
    if r["project_ref"]:
        meta.append([L.get("ref", "Ref./PO-Nr."), r["project_ref"]])
    if r["valid_until"]:
        meta.append([L.get("valid_until", "Gültig bis"), valid_text])
    rows = [[L.get("net_total", t["labels"]["net"]), fmt_money(t["net"], lang, cur)]]
    if t.get("net_incl_raw") is not None:
        rows.append([L.get("incl_raw", t["labels"]["net_incl_raw"]), fmt_money(t["net_incl_raw"], lang, cur)])
    if t.get("net_excl_raw") is not None:
        rows.append([L.get("excl_raw", t["labels"]["net_excl_raw"]), fmt_money(t["net_excl_raw"], lang, cur)])
    rrows = [[L.get("rights_" + dim, dim), (rights.get(dim) or {}).get("text") or ""] for dim in ("time", "territory", "media")]
    rrows = [x for x in rrows if x[1]]
    if rights.get("exceptions"):
        rrows.append([L.get("rights_exceptions", "Ausnahmen"), rights["exceptions"]])
    if rights.get("exclusive"):
        rrows.append([L.get("rights_exclusive", "Exklusiv"), "ja" if lang == "de" else "yes"])
    texts = pack.get("texts") or {}
    valid_note = ((texts.get("valid_note") or {}).get(lang) or "").replace("{date}", valid_text) if r["valid_until"] else ""
    labels = {k: v for k, v in L.items() if not isinstance(v, dict)}
    labels["units"] = L.get("units") or {}
    labels["page_of"] = L.get("page_of") or ("Page {x} of {y}" if lang == "en" else "Seite {x} von {y}")
    role = office_role(c, g.user["id"], oid) if getattr(g, "user", None) is not None else None
    return {
        "kind": r["kind"], "lang": lang, "currency": cur, "fx_rate": t.get("fx_rate"), "fx_note": t.get("fx_note") or "", "vat_mode": t["vat_mode"],
        "raw_mode": t["raw_mode"], "status": r["status"], "number": r["number"], "date": r["date"], "date_text": _fmt_date(r["date"], pack),
        "valid_until": r["valid_until"], "valid_until_text": valid_text, "title": L.get("offer", "Kostenvoranschlag" if lang == "de" else "Quotation"),
        "project_title": r["project_title"], "project_ref": r["project_ref"],
        "company": {"name": co.get("name") or "", "lines": co.get("lines") or [], "contact_lines": co.get("contact_lines") or [],
                    "register_lines": co.get("register_lines") or [], "bank_lines": co.get("bank_lines") or [],
                    "sender_line": " · ".join(x for x in (co.get("lines") or []) if x), "logo_path": logo_path, "color": color},
        "recipient": rec, "meta": meta, "intro": r["intro"] or "", "lines": t["lines"],
        "totals": {"net": t["net"], "net_text": fmt_money(t["net"], lang, cur), "tax_lines": t["tax_lines"], "tax_total": t["tax_total"],
                   "gross": t["gross"], "net_incl_raw": t.get("net_incl_raw"),
                   "net_incl_raw_text": fmt_money(t["net_incl_raw"], lang, cur) if t.get("net_incl_raw") is not None else "",
                   "net_excl_raw": t.get("net_excl_raw"),
                   "net_excl_raw_text": fmt_money(t["net_excl_raw"], lang, cur) if t.get("net_excl_raw") is not None else "",
                   "raw_amount": t["raw_amount"], "producing_days": t["producing_days"], "discount": t["discount"], "rows": rows,
                   "vat_note": t["vat_note"], "show_tax_lines": False},
        "rights": {"title": L.get("rights", "Rechteübertragung"), "rows": rrows, "exceptions": rights.get("exceptions") or "",
                   "exclusive": int(rights.get("exclusive") or 0), "note": rights.get("note") or ""},
        "closing": r["closing"] or "", "signature": L.get("signature", "Mit freundlichen Grüßen"), "signature_name": "",
        "valid_note": valid_note, "fields": _j(r["fields"], []), "labels": labels, "formats": pack.get("formats") or {},
        "internal": {"costs": t["costs"], "margin": t["margin"]} if role == "admin" else None,
    }


# ---------------------------------------------------------------- routes
@app.get("/api/office/docs")
def odoc_list():
    """?kind=offer&status=&q= -> the organisation's documents, newest first (brief rows)."""
    c, uid, oid = _ctx()
    kind = request.args.get("kind") or "offer"
    sql, args = "SELECT * FROM office_docs WHERE org_id=? AND kind=?", [oid, kind]
    st = request.args.get("status")
    if st in STATUSES:
        sql += " AND status=?"
        args.append(st)
    q = (request.args.get("q") or "").strip()
    if q:
        like = f"%{q}%"
        sql += " AND (number LIKE ? OR project_title LIKE ? OR project_ref LIKE ? OR recipient LIKE ?)"
        args += [like, like, like, like]
    rows = [doc_brief(r) for r in c.execute(sql + " ORDER BY date DESC, id DESC LIMIT 500", args)]
    return jsonify(docs=rows, role=office_role(c, uid, oid), org_id=oid)


@app.post("/api/office/docs")
def odoc_create():
    """{kind?: offer, lang?, client_id?, contract_id?, project_title?, recipient?, items?: [...]} -> 201 the document (number reserved)."""
    c, uid, oid = _ctx()
    office_seed_texts(c, oid)
    admin = office_role(c, uid, oid) == "admin"
    b = body()
    if not isinstance(b, dict):
        return err(tr("Invalid data"))
    did = doc_create(c, oid, uid, b, admin)
    bump(c)
    c.commit()
    return jsonify(doc_public(c, oid, doc_row(c, oid, did), admin)), 201


@app.get("/api/office/docs/<int:did>")
def odoc_get(did):
    c, uid, oid = _ctx()
    return jsonify(doc_public(c, oid, doc_row(c, oid, did), office_role(c, uid, oid) == "admin"))


@app.patch("/api/office/docs/<int:did>")
def odoc_update(did):
    """Head fields (partial); contract_id (changed) presets raw data / rights / closing unless apply_contract: false;
    client_id fills an empty recipient (recipient_from_client: true overwrites it). Returns the document with totals."""
    c, uid, oid = _ctx()
    admin = office_role(c, uid, oid) == "admin"
    r = doc_row(c, oid, did)
    b = body()
    if not isinstance(b, dict):
        return err(tr("Invalid data"))
    f = clean_doc(c, oid, b, r, admin)
    if f:
        f["updated_at"] = iso(now_utc())
        c.execute(f"UPDATE office_docs SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), did])
    recalc(c, oid, did)
    bump(c)
    c.commit()
    return jsonify(doc_public(c, oid, doc_row(c, oid, did), admin))


@app.put("/api/office/docs/<int:did>/items")
def odoc_items_put(did):
    """{items: [...]} the whole list of positions in order (see clean_items). Returns the document with totals."""
    c, uid, oid = _ctx()
    admin = office_role(c, uid, oid) == "admin"
    r = doc_row(c, oid, did)
    b = body()
    items = b.get("items") if isinstance(b, dict) else b
    _put_items(c, oid, r, items, admin)
    recalc(c, oid, did)
    bump(c)
    c.commit()
    return jsonify(doc_public(c, oid, doc_row(c, oid, did), admin))


@app.post("/api/office/docs/<int:did>/number")
def odoc_number(did):
    """{number?} sets a number by hand (unique within the organisation) or reserves the next one of the scheme."""
    c, uid, oid = _ctx()
    b = body()
    num = _assign_number(c, oid, did, manual=b.get("number") if isinstance(b, dict) and "number" in b else None)
    bump(c)
    c.commit()
    return jsonify(id=did, number=num)


@app.post("/api/office/docs/<int:did>/status")
def odoc_status(did):
    """{status: draft|sent|accepted|declined}; sent sets sent_at (once)."""
    c, uid, oid = _ctx()
    r = doc_row(c, oid, did)
    b = body()
    st = _choice((b if isinstance(b, dict) else {}).get("status"), "status", STATUSES)
    ts = iso(now_utc())
    c.execute("UPDATE office_docs SET status=?, updated_at=?, sent_at=COALESCE(sent_at, ?) WHERE id=?",
              (st, ts, ts if st in ("sent", "accepted", "declined") else None, did))
    bump(c)
    c.commit()
    return jsonify(doc_public(c, oid, doc_row(c, oid, did), office_role(c, uid, oid) == "admin", items=False))


@app.post("/api/office/docs/<int:did>/duplicate")
def odoc_duplicate(did):
    """A copy as a new draft of today with the next number (positions, rights and texts copied)."""
    c, uid, oid = _ctx()
    admin = office_role(c, uid, oid) == "admin"
    r = doc_row(c, oid, did)
    s = office_settings(c, oid)
    row = {k: r[k] for k in r.keys() if k not in ("id", "number", "status", "created_at", "updated_at", "sent_at", "created_by", "date", "valid_until", "totals")}
    today = local_now().date()
    ts = iso(now_utc())
    row.update(number="", status="draft", date=today.isoformat(), valid_until=(today + timedelta(days=int(s.get("offer_valid_days") or 30))).isoformat(),
               totals="{}", created_by=uid, created_at=ts, updated_at=ts, sent_at=None)
    nid = c.execute(f"INSERT INTO office_docs({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values())).lastrowid
    for it in doc_items(c, did):
        it.pop("id", None)
        it["doc_id"] = nid
        c.execute(f"INSERT INTO office_doc_items({','.join(it)}) VALUES({','.join('?' * len(it))})", list(it.values()))
    _assign_number(c, oid, nid, s)
    recalc(c, oid, nid)
    bump(c)
    c.commit()
    return jsonify(doc_public(c, oid, doc_row(c, oid, nid), admin)), 201


@app.delete("/api/office/docs/<int:did>")
def odoc_delete(did):
    """The organisation's admin only (members: 403)."""
    c, uid, oid = _ctx()
    doc_row(c, oid, did)
    if office_role(c, uid, oid) != "admin":
        raise Denied(403, tr("Only an admin of this organisation can do this"))
    c.execute("DELETE FROM office_docs WHERE id=?", (did,))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.get("/api/office/docs/<int:did>/render")
def odoc_render_get(did):
    """The print model (JSON) for the preview and the PDF writer."""
    c, uid, oid = _ctx()
    rd = odoc_render(c, did, oid)
    co = rd.get("company") or {}
    co["logo"] = bool(co.pop("logo_path", None))  # 2.36.1 review: no server path in the API answer
    return jsonify(rd)
