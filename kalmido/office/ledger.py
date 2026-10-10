"""Office & finance foundation (2.36.2, #1021 P1/P2/P4/P6 and the office part of #1142): finalising documents, the
structured company data of an organisation, and the office log.

Finalising (POST /api/office/docs/<id>/finalize) freezes a document: the number is assigned when it has none, the totals
stop being recomputed, every position keeps its tax rate, net and tax amount as decimal text, and the sender (company,
logo by its hash, colour), the recipient and the country pack's rates and print words are stored in the document. After
that the head, the positions, the number and deleting answer 409 (ofx_need_editable); duplicating stays possible (= a new
version). The print model of a finalised document is built from the snapshot only (docs.odoc_render).

Numbers: OFX_NUMBER_AT_FINALIZE says per kind whether a draft gets its number when it is created (quotations, as before)
or only when it is finalised (later invoices); the organisation may switch quotations to "when finalised"
(office_settings.offer_number_at). Uniqueness per organisation stays one query in docs._assign_number (the partial
unique index office_docs_number exists since 2.36.1).

office_company: the company as single fields (P4); the print lines are made from them, group by group, and the free
lines of office_settings.data.company remain the fallback of a group without fields (2.36.1 reads only those).

office_doc_log (#1142): who changed or read which document or master data, when; detail = JSON with before / after for
changes. Shown to the organisation's admins only (document history, the module's settings). Never part of alerts.
Agents never reach any of this (office_gate)."""
import hashlib
import json
import os
import re
import shutil
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import g, jsonify, request

from ..core.config import app, OFFICE_DIR
from ..core.i18n import N_, tr
from ..core.db import bump, db, iso, now_utc
from ..core.access import Denied
from ..personal.timetrack import BadInput
from .model import office_gate, office_org, office_role, office_settings
from .packs import office_pack

# P2: does a document of this kind get its number only when it is finalised? (quotations: at creation, unless the
# organisation chose otherwise; invoices / credit notes of a later release: always at finalising)
OFX_NUMBER_AT_FINALIZE = {"offer": False, "invoice": True, "credit": True}
OFX_LOCKED = N_("This document is finalised and cannot be changed. Duplicate it to make a new version.")
OFX_DETAIL_MAX = 60000
Q2 = Decimal("0.01")

COMPANY_COLS = ("name", "street", "zip", "city", "country", "email", "phone", "tax_number", "vat_id", "iban", "bic", "bank_name",
                "register_court", "register_no", "managing_directors")
COMPANY_MAX = {"name": 200, "street": 200, "zip": 20, "city": 120, "country": 2, "email": 200, "phone": 60, "tax_number": 40,
               "vat_id": 20, "iban": 42, "bic": 11, "bank_name": 120, "register_court": 120, "register_no": 60, "managing_directors": 300}
# words of the printed company lines (the document's language); a pack may override them with labels[lang]["company_<key>"]
COMPANY_WORDS = {
    "de": {"phone": "Tel.", "email": "E-Mail", "tax_number": "Steuernummer", "vat_id": "USt-IdNr.", "iban": "IBAN", "bic": "BIC",
           "register": "Registergericht", "managing_directors": "Geschäftsführung"},
    "en": {"phone": "Phone", "email": "Email", "tax_number": "Tax number", "vat_id": "VAT ID", "iban": "IBAN", "bic": "BIC",
           "register": "Register court", "managing_directors": "Managing directors"},
}


# ---------------------------------------------------------------- locking
def ofx_locked(r):
    return bool(r is not None and "locked_at" in r.keys() and r["locked_at"])


def ofx_need_editable(r):
    """409 with a readable reason when document row r is finalised (head, positions, number, delete)."""
    if ofx_locked(r):
        raise Denied(409, tr(OFX_LOCKED))


def ofx_number_at_finalize(s, kind):
    if kind == "offer":
        return (s or {}).get("offer_number_at") == "finalize"
    return OFX_NUMBER_AT_FINALIZE.get(kind, True)


# ---------------------------------------------------------------- the log
def _cap(detail):
    try:
        s = json.dumps(detail if detail is not None else {}, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        s = "{}"
    if len(s) > OFX_DETAIL_MAX:
        keys = sorted(detail.keys()) if isinstance(detail, dict) else []
        s = json.dumps({"truncated": True, "keys": keys[:50]})
    return s


def ofx_log(c, oid, action, target="doc", doc_id=None, detail=None, dedupe_min=0):
    """One entry of the office log of organisation oid by the signed-in person. dedupe_min: reads (open, pdf, render,
    export) of the same person on the same thing within that many minutes are written once."""
    u = getattr(g, "user", None)
    uid = u["id"] if u is not None else None
    at = now_utc()
    if dedupe_min:
        since = iso(at - timedelta(minutes=dedupe_min))
        sql = ("SELECT 1 FROM office_doc_log WHERE org_id=? AND action=? AND target=? AND at>=? AND "
               + ("doc_id=?" if doc_id is not None else "doc_id IS NULL") + " AND " + ("user_id=?" if uid is not None else "user_id IS NULL"))
        args = [oid, action, target, since] + ([doc_id] if doc_id is not None else []) + ([uid] if uid is not None else [])
        if c.execute(sql + " LIMIT 1", args).fetchone():
            return
    c.execute("INSERT INTO office_doc_log(org_id, doc_id, user_id, at, action, target, detail) VALUES(?,?,?,?,?,?,?)",
              (oid, doc_id, uid, iso(at), action, target, _cap(detail)))


def ofx_diff(before, after):
    """{before: {...}, after: {...}} with the keys whose values differ (JSON text columns compared parsed)."""
    def norm(v):
        if isinstance(v, str) and v[:1] in "[{":
            try:
                return json.loads(v)
            except ValueError:
                return v
        return v
    b, a = {}, {}
    for k, v in (after or {}).items():
        ov = norm((before or {}).get(k))
        nv = norm(v)
        if ov != nv:
            b[k], a[k] = ov, nv
    return {"before": b, "after": a}


ITEM_LOG_KEYS = ("kind", "service_id", "title", "detail", "qty", "unit", "rate", "tax", "raw_fee", "producing", "discountable", "cost")


def ofx_items_brief(rows):
    return [{k: r.get(k) for k in ITEM_LOG_KEYS if k in r} for r in rows or []]


def _log_public(c, r):
    d = dict(r)
    try:
        d["detail"] = json.loads(d.get("detail") or "{}")
    except ValueError:
        d["detail"] = {}
    u = c.execute("SELECT display_name, username FROM users WHERE id=?", (r["user_id"],)).fetchone() if r["user_id"] else None
    d["user_name"] = (u["display_name"] or u["username"]) if u else ""
    return d


def ofx_log_rows(c, oid, doc_id=None, limit=100):
    sql, args = "SELECT * FROM office_doc_log WHERE org_id=?", [oid]
    if doc_id is not None:
        sql += " AND doc_id=?"
        args.append(doc_id)
    args.append(max(1, min(int(limit), 500)))
    return [_log_public(c, r) for r in c.execute(sql + " ORDER BY id DESC LIMIT ?", args)]


# ---------------------------------------------------------------- company (structured)
def ofx_company(c, oid):
    r = c.execute("SELECT * FROM office_company WHERE org_id=?", (oid,)).fetchone()
    return {k: (r[k] if r else "") or "" for k in COMPANY_COLS}


def _iban_ok(v):
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", v):
        return False
    s = v[4:] + v[:4]
    n = "".join(str(int(ch, 36)) for ch in s)
    return int(n) % 97 == 1


def ofx_company_clean(v, cur):
    """A partial body {field: text} -> the full new dict (BadInput on a wrong value)."""
    if not isinstance(v, dict):
        raise BadInput(tr("Invalid value: {0}", "company_fields"))
    out = dict(cur)
    for k, x in v.items():
        if k not in COMPANY_COLS:
            continue
        if x is None:
            x = ""
        if not isinstance(x, str):
            raise BadInput(tr("Invalid value: {0}", k))
        x = re.sub(r"[\x00-\x1f]+", " ", x).strip()
        if k in ("iban", "bic"):
            x = x.replace(" ", "").upper()
        if k == "country":
            x = x.upper()
        if len(x) > COMPANY_MAX[k]:
            raise BadInput(tr("Invalid value: {0}", k))
        if x:
            if k == "country" and not re.fullmatch(r"[A-Z]{2}", x):
                raise BadInput(tr("Invalid value: {0}", k))
            if k == "email" and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", x):
                raise BadInput(tr("Invalid value: {0}", k))
            if k == "iban" and not _iban_ok(x):
                raise BadInput(tr("Invalid value: {0}", "IBAN"))
            if k == "bic" and not re.fullmatch(r"[A-Z0-9]{8}([A-Z0-9]{3})?", x):
                raise BadInput(tr("Invalid value: {0}", "BIC"))
        out[k] = x
    return out


def ofx_company_save(c, oid, d):
    cols = list(COMPANY_COLS)
    c.execute(f"INSERT INTO office_company(org_id, {', '.join(cols)}, updated_at) VALUES(?{', ?' * len(cols)}, ?) "
              f"ON CONFLICT(org_id) DO UPDATE SET {', '.join(k + '=excluded.' + k for k in cols)}, updated_at=excluded.updated_at",
              [oid] + [d.get(k) or "" for k in cols] + [iso(now_utc())])


def ofx_company_print(fields, free, lang="de", pack=None):
    """The printed company (name + the four line groups) from the structured fields; a group without any field takes
    the free lines of the settings (fallback, also for documents of organisations that never filled the fields)."""
    lg = "en" if lang == "en" else "de"
    W = dict(COMPANY_WORDS[lg])
    pl = (((pack or {}).get("labels") or {}).get(lg) or {})
    for k in list(W):
        if isinstance(pl.get("company_" + k), str):
            W[k] = pl["company_" + k]
    f = fields or {}
    free = free or {}
    home = ((pack or {}).get("code") or "").upper()
    addr = [x for x in (f.get("street"), " ".join(y for y in (f.get("zip"), f.get("city")) if y)) if x]
    if f.get("country") and f["country"] != home and addr:
        addr.append(f["country"])
    contact = [x for x in (f"{W['phone']} {f['phone']}" if f.get("phone") else "", f"{W['email']} {f['email']}" if f.get("email") else "") if x]
    reg = []
    if f.get("register_court") or f.get("register_no"):
        reg.append(" ".join(x for x in (W["register"] + ":" if f.get("register_court") else "", f.get("register_court"), f.get("register_no")) if x))
    if f.get("managing_directors"):
        reg.append(f"{W['managing_directors']}: {f['managing_directors']}")
    bank = []
    if f.get("bank_name"):
        bank.append(f["bank_name"])
    if f.get("iban"):
        bank.append(f"{W['iban']} {' '.join(f['iban'][i:i + 4] for i in range(0, len(f['iban']), 4))}")
    if f.get("bic"):
        bank.append(f"{W['bic']} {f['bic']}")
    if f.get("tax_number"):
        bank.append(f"{W['tax_number']} {f['tax_number']}")
    if f.get("vat_id"):
        bank.append(f"{W['vat_id']} {f['vat_id']}")
    return {"name": f.get("name") or free.get("name") or "", "lines": addr or list(free.get("lines") or []),
            "contact_lines": contact or list(free.get("contact_lines") or []),
            "register_lines": reg or list(free.get("register_lines") or []), "bank_lines": bank or list(free.get("bank_lines") or [])}


# ---------------------------------------------------------------- finalising
def _dtext(v):
    return format(Decimal(str(v)).quantize(Q2, rounding=ROUND_HALF_UP), "f")


def _logo_snapshot(oid, s):
    """The current logo copied once to logo-<hash>.png (content-addressed, never overwritten) -> (file name, sha256)."""
    if not s.get("logo"):
        return "", ""
    src = os.path.join(OFFICE_DIR, str(int(oid)), os.path.basename(s["logo"]))
    if not os.path.isfile(src):
        return "", ""
    h = hashlib.sha256()
    with open(src, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    sha = h.hexdigest()
    name = f"logo-{sha[:16]}.png"
    dst = os.path.join(OFFICE_DIR, str(int(oid)), name)
    if not os.path.isfile(dst):
        shutil.copyfile(src, dst + ".part")
        os.replace(dst + ".part", dst)
    return name, sha


def ofx_logo_path(oid, name):
    if not name or not re.fullmatch(r"logo-[0-9a-f]{16}\.png", name):
        return None
    p = os.path.join(OFFICE_DIR, str(int(oid)), name)
    return p if os.path.isfile(p) else None


def ofx_finalize(c, oid, uid, did):
    """Finalises document did of organisation oid (see the module text). 409 when it already is."""
    from .docs import _assign_number, _j, doc_items, doc_row, doc_totals
    r = doc_row(c, oid, did)
    ofx_need_editable(r)
    s = office_settings(c, oid)
    pack = office_pack(s["pack"]) or office_pack("DE") or {}
    if not r["number"]:
        _assign_number(c, oid, did, s)
        r = doc_row(c, oid, did)
    lang = "en" if r["lang"] == "en" else "de"
    t = doc_totals(c, oid, r)
    lines = {ln.get("id"): ln for ln in t["lines"] if ln.get("kind") == "item"}
    for it in doc_items(c, did, oid):
        ln = lines.get(it["id"])
        if not ln:
            continue
        pct = Decimal(str(ln.get("tax_pct") or 0))
        net = Decimal(str(ln.get("total") or 0))
        c.execute("UPDATE office_doc_items SET tax_pct=?, net=?, tax_amount=? WHERE id=? AND org_id=?",
                  (format(pct.normalize(), "f"), _dtext(net), _dtext(net * pct / 100), it["id"], oid))
    logo, sha = _logo_snapshot(oid, s)
    color = s.get("color") or ""
    fields = ofx_company(c, oid)
    sender = {"company": ofx_company_print(fields, s.get("company") or {}, lang, pack), "fields": fields, "color": color,
              "logo": logo, "logo_sha256": sha, "pack": pack.get("code") or s["pack"]}
    rec = _j(r["recipient"], {})
    rsnap = {"name": rec.get("name") or "", "lines": rec.get("lines") or []}
    if r["client_id"]:
        cl = c.execute("SELECT * FROM clients WHERE id=? AND org_id=?", (r["client_id"], oid)).fetchone()
        if cl:
            for k in ("street", "zip", "city", "country", "vat_id", "customer_no", "buyer_reference", "email_invoice", "payment_terms_days"):
                rsnap[k] = cl[k] if k in cl.keys() else None
    tax = pack.get("tax") or {}
    tsnap = {"pack": pack.get("code") or "", "version": str(pack.get("version") or ""),
             "rates": {k: tax.get(k) for k in ("standard", "reduced", "exempt")}, "tax": tax,
             "formats": pack.get("formats") or {}, "labels": {lang: (pack.get("labels") or {}).get(lang) or {}},
             "texts": {"valid_note": {lang: (((pack.get("texts") or {}).get("valid_note") or {}).get(lang) or "")}}}
    ts = iso(now_utc())
    c.execute("UPDATE office_docs SET locked_at=?, locked_by=?, sender=?, recipient_snapshot=?, tax_snapshot=?, pack_version=?, totals=?, "
              "updated_at=? WHERE id=? AND org_id=?",
              (ts, uid, json.dumps(sender, ensure_ascii=False), json.dumps(rsnap, ensure_ascii=False), json.dumps(tsnap, ensure_ascii=False),
               tsnap["version"], json.dumps(t, ensure_ascii=False), ts, did, oid))
    ofx_log(c, oid, "finalize", doc_id=did, detail={"number": r["number"], "net": t.get("net"), "gross": t.get("gross"),
                                                     "pack_version": tsnap["version"], "logo_sha256": sha})
    return doc_row(c, oid, did)


def ofx_snapshot_pack(r):
    """The pack-shaped snapshot of a finalised document (formats, labels, texts, tax) for the print model."""
    try:
        d = json.loads(r["tax_snapshot"] or "{}")
    except ValueError:
        d = {}
    return d if isinstance(d, dict) else {}


# ---------------------------------------------------------------- start-up
def ofx_migrate(c):
    """Every start (inside init_db's transaction): positions written without organisation (older versions) get the one
    of their document; the index for organisation-filtered reads."""
    c.execute("UPDATE office_doc_items SET org_id=(SELECT d.org_id FROM office_docs d WHERE d.id=office_doc_items.doc_id) "
              "WHERE org_id IS NULL")
    c.execute("CREATE INDEX IF NOT EXISTS office_doc_items_org ON office_doc_items(org_id, doc_id)")


# ---------------------------------------------------------------- routes
def _ctx(admin=False):
    c = db()
    uid = office_gate(c)
    return c, uid, office_org(c, uid, admin=admin)


@app.post("/api/office/docs/<int:did>/finalize")
def ofx_finalize_post(did):
    """Members of the organisation: freezes the document (number, totals, sender, recipient, tax rates); then it can only
    be duplicated. Returns the document."""
    from .docs import doc_public
    c, uid, oid = _ctx()
    r = ofx_finalize(c, oid, uid, did)
    bump(c)
    c.commit()
    return jsonify(doc_public(c, oid, r, office_role(c, uid, oid) == "admin"))


@app.get("/api/office/docs/<int:did>/log")
def ofx_doc_log_get(did):
    """The organisation's admin: the history of one document (newest first)."""
    from .docs import doc_row
    c, uid, oid = _ctx(admin=True)
    doc_row(c, oid, did)
    return jsonify(log=ofx_log_rows(c, oid, did, 200))


@app.get("/api/office/log")
def ofx_log_get():
    """The organisation's admin: the latest entries of the office log (?limit=, at most 500)."""
    c, uid, oid = _ctx(admin=True)
    try:
        limit = int(request.args.get("limit") or 50)
    except ValueError:
        limit = 50
    return jsonify(log=ofx_log_rows(c, oid, None, limit))
