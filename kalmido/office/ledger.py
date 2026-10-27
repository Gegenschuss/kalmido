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

from flask import g, jsonify, request, has_app_context

from ..core.config import app, OFFICE_DIR
from ..core.i18n import N_, tr
from ..core.db import bump, db, iso, now_utc
from ..core.pg import write_lock
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields, oc_json_store, oc_log_detail
from ..core.access import Denied
from ..core.errors import BadInput
from .model import ofx_name1, ofx_name_clean, ofx_name_lines, office_gate, office_org, office_role, office_settings, pb_cl_sql
from .packs import office_pack_for
from .doclang import doc_lg, doc_pack
from .rights import ofr_admin_or
from .countries import fk_country_label  # 2.296.0 B (#3168)
from .pdfweb import _stored  # 2.296.0 F (#3177)

# P2: does a document of this kind get its number only when it is finalised? (quotations: at creation, unless the
# organisation chose otherwise; invoices / credit notes of a later release: always at finalising)
OFX_NUMBER_AT_FINALIZE = {"offer": False, "invoice": True, "credit": True, "reminder": True, "delivery": True}  # 2.120.0 D (#2089)
OFX_LOCKED = N_("This document is finalised and cannot be changed. Duplicate it to make a new version.")
OFX_DETAIL_MAX = 60000
Q2 = Decimal("0.01")

COMPANY_COLS = ("name", "street", "address_extra", "zip", "city", "country", "email", "phone", "tax_number", "vat_id", "iban", "bic", "bank_name",
                "register_court", "register_no", "managing_directors", "md_label")
COMPANY_MAX = {"name": 200, "street": 200, "address_extra": 200, "zip": 20, "city": 120, "country": 2, "email": 200, "phone": 60, "tax_number": 40,
               "vat_id": 20, "iban": 42, "bic": 11, "bank_name": 120, "register_court": 120, "register_no": 60, "managing_directors": 300, "md_label": 20}
# 2.40.0 (#1377): the word before the names of the management in the printed footer (md_label; '' = "Geschäftsführung" as before)
# 2.185.0 C (#2520): English keys through tr() in the document's language (was a de / en pair; the words stay the same)
FE_MD_LABELS = {"": N_("Managing directors|company"), "shareholders": N_("Shareholders|company"),
                "owner_m": N_("Owner|company, male"), "owner_f": N_("Owner|company, female"), "board": N_("Executive board|company"),
                "partners": N_("Partners|company"),
                "gbr_partners": N_("Partners|company, GbR")}  # 2.138.0 E (#2242): GbR partners; "shareholders" stays as stored
# words of the printed company lines (the document's language); a pack may override them with labels[lang]["company_<key>"]
COMPANY_WORDS = {"phone": N_("Phone|company"), "email": N_("Email|company"), "tax_number": N_("Tax number|company"), "vat_id": N_("VAT ID|company"),
                 "iban": "IBAN", "bic": "BIC", "register": N_("Register court|company"), "managing_directors": N_("Managing directors|company")}


# ---------------------------------------------------------------- locking
def ofx_locked(r):
    return bool(r is not None and "locked_at" in r.keys() and r["locked_at"])


OFX_SENT = N_("This document was sent and cannot be changed. Duplicate it to make a new version.")


def ofx_need_editable(r):
    """409 with a readable reason when document row r is finalised (head, positions, number, delete). 2.38.0: a sent
    document (quotations too, decision of 2026-10-10) is locked the same way; a new version = duplicate."""
    if ofx_locked(r):
        raise Denied(409, tr(OFX_LOCKED))
    if r is not None and r["status"] == "sent":
        raise Denied(409, tr(OFX_SENT))


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
    u = getattr(g, "user", None) if has_app_context() else None  # 2.138.0 (#1972): also from a background thread (org export)
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
              (oid, doc_id, uid, iso(at), action, target, oc_log_detail(c, oid, _cap(detail))))  # 2.42.0 (#828)


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


ITEM_LOG_KEYS = ("kind", "service_id", "title", "detail", "qty", "unit", "rate", "tax", "raw_fee", "producing", "discountable", "cost", "in_handling", "in_markup")  # 2.113.1 (#2252): + the surcharge flags


def ofx_items_brief(rows):
    return [{k: r.get(k) for k in ITEM_LOG_KEYS if k in r} for r in rows or []]


def _log_public(c, r):
    d = oc_dec_fields(c, r["org_id"], "office_doc_log", r)  # 2.42.0 (#828)
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
    r = oc_dec_fields(c, oid, "office_company", r) if r else None  # 2.42.0 (#828): bank / tax fields encrypted at rest
    out = {k: (r[k] if r and k in r.keys() else "") or "" for k in COMPANY_COLS}
    if not any(out[k] for k in ("street", "zip", "city")):  # 2.99.0 D (#2188): the old free address lines, read into the fields
        out.update(ofx_company_from_free(out, (office_settings(c, oid).get("company") or {}).get("lines") or []))
    return out


def ofx_company_from_free(f, lines):
    """2.99.0 D (#2188): {street, zip, city, country?} read from the free address lines of the settings (the parser of the
    clients' free address, 2.97.0 #1951) -- only for a plain address (street, postcode + city, maybe a country: nothing
    would be lost in print); else {} and the free lines stay what the documents print. Nothing is stored here: the form
    shows the fields, saving it keeps them; the free lines stay in the settings."""
    from ..team.clients import cdn_split_free
    lines = [str(x).strip() for x in lines if str(x).strip()]
    if not 2 <= len(lines) <= 3:
        return {}
    sp = cdn_split_free({"name": ofx_name1(f.get("name")) or "-", "address": "\n".join(lines), "country": ""})
    from .legacyimport import COUNTRIES
    if not all(sp.get(k) for k in ("street", "zip", "city")) or (len(lines) == 3 and lines[-1].strip(" .").lower() not in COUNTRIES):
        return {}
    if f.get("country"):
        sp.pop("country", None)
    return sp


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
        x = ofx_name_clean(x, COMPANY_MAX[k]) if k == "name" else re.sub(r"[\x00-\x1f]+", " ", x).strip()  # 2.99.0 D (#2188): up to 3 lines
        if k in ("iban", "bic"):
            x = x.replace(" ", "").upper()
        if k == "country":
            x = x.upper()
        if k == "md_label" and x not in FE_MD_LABELS:  # 2.40.0 (#1377)
            raise BadInput(tr("Invalid value: {0}", k))
        if len(x) > COMPANY_MAX[k]:
            raise BadInput(tr("Invalid value: {0}", k))
        if x:
            if k == "country" and x != (cur.get(k) or ""):  # 2.40.0 (#1372): ISO 3166-1 alpha-2 only (UK -> GB, EL -> GR); an
                from .countries import fk_country  # old value sent back unchanged stays (the dialog marks it)
                x = fk_country(x)
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
    d = oc_enc_fields(c, oid, "office_company", {k: d.get(k) or "" for k in cols})  # 2.42.0 (#828)
    c.execute(f"INSERT INTO office_company(org_id, {', '.join(cols)}, updated_at) VALUES(?{', ?' * len(cols)}, ?) "
              f"ON CONFLICT(org_id) DO UPDATE SET {', '.join(k + '=excluded.' + k for k in cols)}, updated_at=excluded.updated_at",
              [oid] + [d.get(k) or "" for k in cols] + [iso(now_utc())])


def ofx_company_print(fields, free, lang="de", pack=None):
    """The printed company (name + the four line groups) from the structured fields; a group without any field takes
    the free lines of the settings (fallback, also for documents of organisations that never filled the fields)."""
    lg = doc_lg(lang)  # 2.185.0 C (#2520): every app language
    W = {k: tr(v, lg=lg) if k not in ("iban", "bic") else v for k, v in COMPANY_WORDS.items()}
    pl = (((pack or {}).get("labels") or {}).get(lg) or {})
    for k in list(W):
        if isinstance(pl.get("company_" + k), str):
            W[k] = pl["company_" + k]
    f = fields or {}
    free = free or {}
    home = ((pack or {}).get("code") or "").upper()
    addr = [x for x in (f.get("street"), f.get("address_extra"), " ".join(y for y in (f.get("zip"), f.get("city")) if y)) if x]  # 2.99.0 D (#2188): + extra line
    if f.get("country") and f["country"] != home and addr:
        addr.append(fk_country_label(f["country"], home) or f["country"])  # 2.296.0 B (#3168): the name in capitals, in the sender's language
    from .pdf import pdf_phone  # 2.114.4 A (#2272): grouped for print, the stored value stays
    # 2.357.0 B (#3180): one rule for every label: a colon after a word ("E-Mail:", "Steuernummer:"), none after an
    # abbreviation with its dot ("Tel.", "USt-IdNr.") and none after IBAN / BIC (was a colon only after the e-mail)
    def cl(w):
        return w if w.endswith((".", ":")) or w in ("IBAN", "BIC") else w + ":"
    contact = [x for x in (f"{cl(W['phone'])} {pdf_phone(f['phone'])}" if f.get("phone") else "", f"{cl(W['email'])} {f['email']}" if f.get("email") else "") if x]  # 2.114.5 (#2300): "E-Mail:"
    reg = []
    if f.get("register_court") or f.get("register_no"):
        reg.append(" ".join(x for x in (cl(W["register"]) if f.get("register_court") else "", f.get("register_court"), f.get("register_no")) if x))
    if f.get("managing_directors"):
        md = tr(FE_MD_LABELS[f.get("md_label")], lg=lg) if f.get("md_label") in FE_MD_LABELS and f.get("md_label") else W["managing_directors"]  # 2.40.0 (#1377)
        reg.append(f"{cl(md)} {f['managing_directors']}")
    bank = []
    if f.get("bank_name"):
        bank.append(f["bank_name"])
    if f.get("iban"):
        bank.append(f"{W['iban']} {' '.join(f['iban'][i:i + 4] for i in range(0, len(f['iban']), 4))}")
    if f.get("bic"):
        bank.append(f"{W['bic']} {f['bic']}")
    # 2.357.0 B (#3180): tax number / VAT ID in the register column (was the bank column); the free lines of a column stay
    # the fallback exactly as before (a tax line alone kept the free bank lines out and the free register lines in)
    tax = [f"{cl(W[k])} {f[k]}" for k in ("tax_number", "vat_id") if f.get(k)]
    nm = f.get("name") or free.get("name") or ""  # 2.99.0 D (#2188): name = one line, name_lines = the up to three lines
    return {"name": ofx_name1(nm), "name_lines": ofx_name_lines(nm), "lines": addr or list(free.get("lines") or []),
            "contact_lines": contact or list(free.get("contact_lines") or []),
            "register_lines": (reg or list(free.get("register_lines") or [])) + tax, "bank_lines": bank or ([] if tax else list(free.get("bank_lines") or []))}


def ofx_sender_line(co):
    """2.97.1 (#2224): the sender line above the address field, "Company · Street · Postcode City" (as the document
    templates print it); a name that is already one of the lines is not doubled. The PDF shortens it to the field width."""
    return " · ".join(dict.fromkeys(str(x).strip() for x in [co.get("name") or ""] + list(co.get("lines") or []) if str(x).strip()))


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
    from .invoices import inv_before_finalize, inv_after_finalize
    write_lock(c, f"office_doc_{int(did)}")  # 2.39.0 (#1209 audit M1): two parallel finalise calls -> the second gets 409, no lost number
    r = doc_row(c, oid, did)
    ofx_need_editable(r)
    s = office_settings(c, oid)
    pack = office_pack_for(s) or {}
    if r["kind"] != "offer":  # 2.38.0 (#1021, F1): the required fields of an invoice (400 with the list), due date
        write_lock(c, f"office_num_{int(oid)}")  # 2.126.0 A (#1979 F5): the date check and the number in one go (docs._assign_number)
        if r["kind"] == "credit":  # 2.354.0 review (#2838): the required-field check with the invoice's rates like the totals
            from .invoices import inv_credit_pack
            pack = inv_credit_pack(c, oid, r, pack)
        inv_before_finalize(c, oid, r, s, pack)
        r = doc_row(c, oid, did)
        from .periodlock import period_need_open
        period_need_open(c, oid, r["date"])  # 2.148.0 A (#2471): no new booking in a locked month
    if not r["number"]:
        _assign_number(c, oid, did, s)
        r = doc_row(c, oid, did)
    lang = doc_lg(r["lang"])  # 2.185.0 C (#2520): every app language; the pack's words / texts in it (doclang.doc_pack)
    pack = doc_pack(pack, lang)
    if r["kind"] == "credit":
        from .invoices import inv_credit_pack
        pack = inv_credit_pack(c, oid, r, pack)  # 2.354.0 D (#2838): its snapshot freezes the invoice's rates too
    t = doc_totals(c, oid, r)
    lines = {ln.get("id"): ln for ln in t["lines"] if ln.get("kind") in ("item", "discount")}
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
    sender["company"]["sender_line"] = ofx_sender_line(sender["company"])  # 2.97.1 (#2224): frozen with the rest
    sender["girocode"] = 1 if int(s.get("girocode", 1) or 0) else 0  # 2.147.1 B (#2054): the GiroCode decision, frozen (girocode.py)
    if s.get("exempt_reason"):
        sender["exempt_reason"] = s["exempt_reason"]  # 2.296.0 B (#3169): the exemption reason, frozen (invoices.inv_render)
    if s.get("paper") == "letter":
        sender["paper"] = "letter"  # 2.357.0 A (#3156): the paper size, frozen (docs.odoc_render; none = A4)
    if r["kind"] in ("offer", "reminder") and s.get("sign_offers"):  # 2.357.0 (#3158, review M1): the finaliser's signature, frozen
        pr = c.execute("SELECT * FROM office_letter_profiles WHERE org_id=? AND user_id=?", (oid, uid)).fetchone()
        img = (oc_dec_fields(c, oid, "office_letter_profiles", pr)["image"] if pr else "") or ""
        if img:  # a quotation is rendered from its snapshot at every call: a later setting / picture never changes it
            sender["sign_image"] = img
    from .letterhead import bp_snapshot
    lhs = bp_snapshot(c, oid, s)  # 2.120.0 E (#2091): the own letterhead frozen with the rest (only when there is one)
    if lhs:
        sender["letterhead"] = lhs
    from .docs import cdn_doc_recipient, bwb_accept_on
    if r["kind"] == "offer":  # 2.114.4 B (#2270): the order confirmation block frozen with the rest (a later setting never changes it)
        sender["accept_on"] = bwb_accept_on(r, s)
    rec = cdn_doc_recipient(c, oid, r)  # 2.97.0 B (#1951): the client's address as it is now, frozen below
    if r["client_id"] and rec.get("lines") is not None:
        c.execute("UPDATE office_docs SET recipient=? WHERE id=? AND org_id=?",
                  (json.dumps({k: v for k, v in rec.items() if k != "missing"}, ensure_ascii=False), did, oid))
    rsnap = {"name": rec.get("name") or "", "name_extra": rec.get("name_extra") or "", "lines": rec.get("lines") or []}  # 2.99.0 D (#2188)
    if r["client_id"]:
        cl = c.execute(f"SELECT * FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (r["client_id"],)).fetchone()
        if cl:
            for k in ("street", "zip", "city", "country", "vat_id", "customer_no", "buyer_reference", "email_invoice", "payment_terms_days"):
                rsnap[k] = cl[k] if k in cl.keys() else None
            rsnap["extra"] = cl["address_extra"] if "address_extra" in cl.keys() else ""  # 2.97.0 B (#1951)
            if not rsnap.get("email_invoice") and cl["email"]:  # 2.99.0 D (#2188): BT-49 falls back to the client's e-mail
                rsnap["email_invoice"] = cl["email"]
            from .docs import fk_doc_contact
            k = fk_doc_contact(c, r["client_id"], r["contact_id"] if "contact_id" in r.keys() else None)  # 2.40.0 (#1380)
            rsnap["contact"] = {"name": k["name"], "email": k["email"], "phone": k["phone"]} if k else None
    tax = pack.get("tax") or {}
    tsnap = {"pack": pack.get("code") or "", "version": str(pack.get("version") or ""),
             "rates": {k: tax.get(k) for k in ("standard", "reduced", "exempt")}, "tax": tax,
             "formats": pack.get("formats") or {}, "labels": {lang: (pack.get("labels") or {}).get(lang) or {}},
             # the pack's texts in the document's language (2.38.0: every plain text, the invoice words need them)
             "texts": {k: {lang: v.get(lang) or ""} for k, v in (pack.get("texts") or {}).items() if isinstance(v, dict) and isinstance(v.get(lang) or "", str)}}
    from .catalog import pkc_origin  # 2.76.0 (#1023): which pack file exactly (built in or installed from a catalogue)
    tsnap["pack_sha256"], tsnap["pack_source"] = pkc_origin("country", tsnap["pack"])
    from .terms import agb_freeze
    agb_freeze(c, oid, r)  # 2.113.2 (#2253): the terms of the document's language, before the stored PDF is written
    ts = iso(now_utc())
    c.execute("UPDATE office_docs SET locked_at=?, locked_by=?, sender=?, recipient_snapshot=?, tax_snapshot=?, pack_version=?, totals=?, "
              "updated_at=? WHERE id=? AND org_id=?",
              (ts, uid, oc_enc_fields(c, oid, "office_docs", {"sender": json.dumps(sender, ensure_ascii=False)})["sender"],  # 2.42.0 (#828)
               json.dumps(rsnap, ensure_ascii=False), json.dumps(tsnap, ensure_ascii=False),
               tsnap["version"], json.dumps(oc_json_store(c, oid, "office_docs", "totals", t), ensure_ascii=False), ts, did, oid))
    ofx_log(c, oid, "finalize", doc_id=did, detail={"number": r["number"], "net": t.get("net"), "gross": t.get("gross"),
                                                     "pack_version": tsnap["version"], "logo_sha256": sha})
    if r["kind"] != "offer":  # 2.38.0: status issued, a credit note settles its invoice, the stored PDF / XML (F2)
        inv_after_finalize(c, oid, uid, doc_row(c, oid, did))
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
    # 2.39.1 (#1210 N5): then the column becomes NOT NULL (RLS lets no row without organisation through). Here and not in
    # MIGRATIONS: an old SQLite archive (restore) is loaded after the column exists and filled just above. Every write path
    # since 2.36.2 sets org_id, so older versions run on with it; a row that could not be filled keeps the column nullable.
    if c.execute("SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='office_doc_items' "
                 "AND column_name='org_id' AND is_nullable='YES'").fetchone() \
            and not c.execute("SELECT 1 FROM office_doc_items WHERE org_id IS NULL LIMIT 1").fetchone():
        c.execute("ALTER TABLE office_doc_items ALTER COLUMN org_id SET NOT NULL")
    c.execute("CREATE INDEX IF NOT EXISTS office_doc_items_org ON office_doc_items(org_id, doc_id)")


# ---------------------------------------------------------------- routes
from .model import office_ctx as _ctx  # noqa: E402  2.149.0 G (#2517): was an own copy


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


@app.post("/api/office/docs/<int:did>/unlock")
def ofx_unlock_post(did):
    """2.114.2 A (#2263): the organisation's admin (members: 403) takes a finalised quotation back to a draft while it was
    never sent nor answered by the client and nothing was made from it (docs.bga_offer_block; else 409: a new version =
    duplicate). Invoices, credit notes and the rest: 409. The number stays (finalising again keeps it); the frozen copies go
    and are made anew then. Not finalised: the document as it is."""
    from .docs import bga_offer_block, doc_public, doc_row
    c, uid, oid = _ctx()
    write_lock(c, f"office_mail_{int(oid)}")  # 2.114.2 (#2263 review): a parallel mail send sees the lock (sent_at) first
    write_lock(c, f"office_doc_{int(did)}")
    r = doc_row(c, oid, did)
    if not ofr_admin_or(c, uid, oid, "offers", "edit", "release"):  # 2.187.0 B (#2476): office groups: level + special
        raise Denied(403, tr("Only an admin of this organisation can do this"))
    if ofx_locked(r):
        why = bga_offer_block(c, oid, r)
        if why:
            raise Denied(409, tr(why))
        # 2.296.0 F (#3177): the frozen files and their checksums go too (only a quotation in draft gets here, never an invoice)
        c.execute("UPDATE office_docs SET locked_at=NULL, locked_by=NULL, sender=NULL, recipient_snapshot=NULL, tax_snapshot=NULL, "
                  "pdf_sha256='', xml_sha256='', updated_at=? WHERE id=? AND org_id=?", (iso(now_utc()), did, oid))
        ofx_log(c, oid, "unlock", doc_id=did, detail={"number": r["number"]})
        bump(c)
        c.commit()
        for ext in ("pdf", "xml"):
            p = _stored(oid, r, ext)
            try:
                if p:
                    os.unlink(p)
            except OSError:
                pass
    return jsonify(doc_public(c, oid, doc_row(c, oid, did), True))


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
