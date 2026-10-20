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
from ..core.pg import insert_id, like_escape, write_lock
from ..core.orgcrypt import oc_dec_fields, oc_item_store, oc_json_store
from ..core.i18n import N_, tr
from ..core.db import body, bump, db, err, iso, local_now, now_utc
from ..core.access import Denied
from ..personal.timetrack import BadInput
from .costs import ek_item_margins, ek_purchases_write, ek_role_cost
from .calc import INV_ITEM_KINDS, INV_VAT_NOTES, RAW_MODES, TAX_KEYS, dec, fmt_money, inv_calc, office_calc
from .packs import office_pack
from .model import (NAME_MAX, TEXT_MAX, UNITS, pb_cl_sql, office_gate, office_org, onc_next, onc_ready, onc_version, office_role, office_settings,
                    office_seed_texts)
from .ledger import (ofx_company, ofx_company_print, ofx_sender_line, ofx_diff, ofx_items_brief, ofx_locked, ofx_log, ofx_logo_path, ofx_need_editable,
                     ofx_number_at_finalize, ofx_snapshot_pack, OFX_LOCKED)
from .invoices import (INV_KINDS, INV_STATUSES, STATE_TXT, inv_apply_client, inv_manual_number, inv_money_fields, inv_new_row, inv_paid_map, inv_payments,
                       inv_reminder_totals, inv_render, inv_scheme, inv_state)

DOC_KINDS = ("offer",) + INV_KINDS + ("delivery",)  # 2.120.0 D (#2089): delivery notes / proofs of service (office/delivery.py); 2.38.0 (#1021, F1): invoices, credit notes, reminders live in office/invoices.py
STATUSES = ("draft", "sent", "accepted", "declined")
ITEM_KINDS = ("service", "text", "heading")
STATUS_TXT = {"draft": N_("Draft"), "sent": N_("Sent"), "accepted": N_("Accepted"), "declined": N_("Declined"), **STATE_TXT}
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


CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _text(v, name, mx=TEXT_MAX):
    if v is None:
        return ""
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", name))
    return CTRL_RE.sub("", v).strip()[:mx]  # 2.39.0 (#1209 audit M2): control characters break the e-invoice XML / PDF/A


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
    return oc_dec_fields(c, oid, "office_docs", r)  # 2.42.0 (#828): sender / internal costs encrypted at rest


def doc_items(c, did, oid, part=None):
    """The positions of document did; oid (the organisation) is required: 2.36.2 (#1142) every read filters by it.
    2.47.0 (#1215): the title page's (part_id NULL); part = the positions of that part (office/parts.py)."""
    psql, pargs = (" AND part_id IS NULL", ()) if part is None else (" AND part_id=?", (part,))
    return [oc_dec_fields(c, oid, "office_doc_items", r)  # 2.42.0 (#828): cost from cost_enc
            for r in c.execute("SELECT * FROM office_doc_items WHERE doc_id=? AND org_id=?" + psql + " ORDER BY sort, id", (did, oid, *pargs))]


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
    d = oc_dec_fields(c, oid, "office_contracts", r)  # 2.42.0 (#828)
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
    r = c.execute(f"SELECT id, name, name_extra, contact, address, email, street, address_extra, zip, city, country FROM clients WHERE id=? AND "
                  f"{pb_cl_sql(c, oid)}", (_iid(cid),)).fetchone()  # 2.97.0 B (#1951): the fixed address fields
    return dict(r) if r else None


def _recipient_from_client(cl, contact=None, home="DE"):
    """contact (2.40.0 #1380): the chosen contact person's name ("" = none; None = the client's default).
    2.97.0 B (#1951): the address comes from the client's fixed fields only (name, attn., street, extra line, postcode city,
    the country when it is not home = the company's, as the invoice prints it); the fields themselves travel along (the
    e-invoice reads them, no parsing of lines). missing: street, postcode or city empty."""
    g_ = lambda k: re.sub(r"\s+", " ", str(cl.get(k) or "")).strip()
    lines = [cl["name"]]
    if g_("name_extra"):  # 2.99.0 D (#2188): the name addition is its own line under the name
        lines.append(g_("name_extra"))
    contact = cl.get("contact") if contact is None else contact
    if contact:
        lines.append(contact)
    country = g_("country").upper()
    lines += [x for x in (g_("street"), g_("address_extra"), " ".join(x for x in (g_("zip"), g_("city")) if x),
                          country if country and country != (home or "DE").upper() else "") if x]
    return {"name": cl["name"], "name_extra": g_("name_extra"), "lines": lines[:12], "street": g_("street"), "extra": g_("address_extra"), "zip": g_("zip"),
            "city": g_("city"), "country": country, "missing": not all(g_(k) for k in ("street", "zip", "city"))}


def cdn_home(c, oid):
    """The company's country (the recipient's country line is left out when it is the same)."""
    return (ofx_company(c, oid).get("country") or "DE").upper()


def cdn_doc_recipient(c, oid, r, stored=None):
    """2.97.0 B (#1951): the recipient of document row r: a draft with a client reads it from the client (now), a finished /
    sent one or one without a client keeps what is stored (old free lines stay as they are)."""
    rec = stored if stored is not None else _j(r["recipient"], {})
    if not r["client_id"] or ofx_locked(r) or r["status"] == "sent":
        return rec
    cl = _client(c, oid, r["client_id"])
    if not cl:
        return rec
    return _recipient_from_client(cl, fk_doc_contact_name(c, cl["id"], _cur_val(r, "contact_id")), cdn_home(c, oid))


# 2.40.0 (#1380): the contact person of a document (office_docs.contact_id): NULL = the client's default, 0 = none, else
# one of the client's contact persons (a deleted one falls back to the default). The "attn." line follows a change.
def _cur_val(cur, k):
    return cur[k] if k in cur.keys() else None


def fk_doc_contact(c, cid, kid):
    """The contact person (dict) a document of client cid with contact_id kid is addressed to, None = none."""
    from .contacts_cl import fk_contact
    if not cid or kid == 0:
        return None
    return fk_contact(c, cid, kid)


def fk_doc_contact_name(c, cid, kid):
    if kid in (None, ""):
        k = fk_doc_contact(c, cid, None)
    else:
        try:
            k = fk_doc_contact(c, cid, int(kid))
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid value: {0}", "contact_id")) from None
    return k["name"] if k else ""


def fk_doc_contact_clean(c, oid, b, cur, f):
    """contact_id from body b (with the client of f / cur); a new client without one chosen takes its default. Rewrites the
    attn. line of the recipient unless the body sets the recipient itself."""
    cid = f["client_id"] if "client_id" in f else _cur_val(cur, "client_id")
    changed_client = "client_id" in f and f["client_id"] != _cur_val(cur, "client_id")
    if "contact_id" not in b and not changed_client:
        return
    kid = b.get("contact_id")
    if kid in (None, "") or not cid:
        kid = None
    else:
        if isinstance(kid, bool):
            raise BadInput(tr("Invalid value: {0}", "contact_id"))
        try:
            kid = int(kid)
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid value: {0}", "contact_id")) from None
        if kid and not c.execute("SELECT 1 FROM office_client_contacts WHERE id=? AND client_id=?", (kid, cid)).fetchone():
            raise BadInput(tr("Invalid value: {0}", "contact_id"))
    f["contact_id"] = kid
    if changed_client or b.get("recipient") is not None or "recipient" in f:
        return
    old = fk_doc_contact(c, cid, _cur_val(cur, "contact_id"))
    new = fk_doc_contact(c, cid, kid)
    on, nn = (old or {}).get("name") or "", (new or {}).get("name") or ""
    if on == nn:
        return
    rec = _j(cur["recipient"], {}) if _cur_val(cur, "recipient") else {}
    lines = [str(x) for x in (rec.get("lines") or [])]
    if on and on in [x.strip() for x in lines]:
        i = [x.strip() for x in lines].index(on)
        if nn:
            lines[i] = nn
        else:
            lines.pop(i)
    elif nn:
        lines.insert(1 if lines else 0, nn)
    f["recipient"] = json.dumps({"name": rec.get("name") or "", "lines": lines[:12]}, ensure_ascii=False)


# ---------------------------------------------------------------- the document as the client sees it
def _calc_doc(r):
    return {"lang": r["lang"], "currency": r["currency"], "fx_rate": r["fx_rate"], "vat_mode": r["vat_mode"], "raw_mode": r["raw_mode"],
            "raw_factor": r["raw_factor"], "prod_quotient": r["prod_quotient"], "producing_rate": r["producing_rate"],
            "discount_pct": r["discount_pct"], "producing_on": dict(r).get("producing_on"),  # 2.47.0 (#1645)
            "vat_note": dict(r).get("vat_note")}  # 2.47.3 (#1360): "small" prints the section 19 note


def doc_totals(c, oid, r, items=None):
    s = office_settings(c, oid)
    pack = office_pack(s["pack"]) or office_pack("DE")
    if r["kind"] == "reminder":  # 2.38.0: a reminder has no positions, its lines are the invoices it lists
        return inv_reminder_totals(c, oid, r, pack)
    calc = inv_calc if r["kind"] in ("invoice", "credit", "delivery") else office_calc
    if r["kind"] == "offer":  # 2.47.0 (#1215): a quotation with parts (None: it has none, computed as before)
        from .parts import tp_doc_totals
        t = tp_doc_totals(c, oid, r, items if items is not None else doc_items(c, r["id"], oid), pack)
        if t is not None:
            t.pop("_part_calcs", None)
            return t
    return calc(_calc_doc(r), items if items is not None else doc_items(c, r["id"], oid), pack)


def recalc(c, oid, did):
    """Recomputes and caches the totals of document did (after any change of its head or positions). A finalised
    document keeps its frozen totals (2.36.2)."""
    r = doc_row(c, oid, did)
    if ofx_locked(r):
        return _j(r["totals"], {})
    if r["kind"] == "offer":  # 2.47.0 (#1215): the parts' cached totals and the rates of their title page lines
        from .parts import tp_recalc
        tp_recalc(c, oid, r)
    t = doc_totals(c, oid, r)
    c.execute("UPDATE office_docs SET totals=?, updated_at=? WHERE id=? AND org_id=?",
              (json.dumps(oc_json_store(c, oid, "office_docs", "totals", t), ensure_ascii=False), iso(now_utc()), did, oid))  # 2.42.0 (#828)
    if r["kind"] == "offer" and r["status"] == "accepted":
        ek_purchases_write(c, oid, did)  # 2.47.0 (#1649): a changed accepted quotation writes its purchase anew
    return t


def doc_public(c, oid, r, admin, items=True):
    d = oc_dec_fields(c, oid, "office_docs", r)  # 2.42.0 (#828)
    for k, dflt in (("recipient", {}), ("rights", {}), ("fields", []), ("totals", {})):
        d[k] = _j(d.get(k), dflt)
    d["recipient"] = dict(cdn_doc_recipient(c, oid, r, d["recipient"]))  # 2.97.0 B (#1951): a draft shows its client's address now
    d["recipient_missing"] = bool(d["recipient"].pop("missing", False))  # street, postcode or city missing at the client
    pm = inv_paid_map(c, oid, [r["id"]]) if r["kind"] in ("invoice", "credit") else {}
    d["state"] = inv_state(r, pm)  # 2.38.0: the derived state (partial / overdue) next to the stored status
    d["status_text"] = tr(STATUS_TXT.get(d["state"], d["state"]))
    d["net_text"] = fmt_money(d["totals"].get("net") or 0, d["lang"], d["currency"])
    d["gross_text"] = fmt_money(d["totals"].get("gross") or 0, d["lang"], d["currency"])
    d["ref_doc_ids"] = _j(d.get("ref_doc_ids") or "[]", [])
    if r["kind"] in ("invoice", "credit"):
        d.update(inv_money_fields(r, pm))
        d["open_text"] = fmt_money(d["open"], d["lang"], d["currency"])
        if items:
            d["payments"] = inv_payments(c, oid, r["id"]) if r["kind"] == "invoice" else []
            cr = c.execute("SELECT id, number, status, locked_at, totals FROM office_docs WHERE org_id=? AND kind='credit' AND cancels_id=? ORDER BY id",
                           (oid, r["id"])).fetchall() if r["kind"] == "invoice" else []
            d["credits_of"] = [{"id": x["id"], "number": x["number"], "status": x["status"], "locked": bool(x["locked_at"]), "gross": _j(x["totals"], {}).get("gross")} for x in cr]
            if r["kind"] == "credit" and d.get("cancels_id"):
                x = c.execute("SELECT id, number FROM office_docs WHERE id=? AND org_id=?", (d["cancels_id"], oid)).fetchone()
                d["cancels"] = {"id": x["id"], "number": x["number"]} if x else None
    if r["kind"] in ("invoice", "reminder"):  # 2.40.0 (#1368 points 8 + 9)
        from .invoices import fd_reminder_extra
        fd_reminder_extra(c, oid, [d])
    d["statuses"] = list(INV_STATUSES.get(r["kind"]) or STATUSES)
    if not admin:
        d["totals"] = {k: v for k, v in d["totals"].items() if k not in ("costs", "margin")}
    if items:
        its = doc_items(c, r["id"], oid)
        for it in its:
            it["discountable"] = int(it.get("discountable") or 0)
            if not admin:
                it.pop("cost", None)  # 2.47.0 (#1649): members get no purchase at all (was None)
                it.pop("cost_enc", None)
        if admin:
            ek_item_margins(d, its)  # 2.47.0 (#1649): the surplus per position, computed here (never stored in plain)
        d["items"] = its
        if r["kind"] == "offer":  # 2.47.0 (#1215): the parts (purchase side only for admins)
            from .parts import tp_public, tp_shoot_ok
            d["parts"] = tp_public(c, oid, r, admin)
            d["parts_shoot"] = tp_shoot_ok(c, oid)
        from .contacts_cl import fk_contacts
        d["client_contacts"] = fk_contacts(c, r["client_id"]) if r["client_id"] else []  # 2.40.0 (#1380): the choice of contact_id
        d["contract"] = _contract(c, oid, d.get("contract_id"))
        if d["contract"]:
            d["contract"] = {k: d["contract"][k] for k in ("id", "name", "raw_included", "rates", "rights_time_id", "rights_territory_id",
                                                             "rights_media_id", "rights_note_de", "rights_note_en", "closing_de", "closing_en", "date")}
    locked = ofx_locked(r)
    if items and r["kind"] == "offer":  # 2.114.4 B (#2270): what the PDF prints (a finalised quotation: its frozen value)
        d["accept_print"] = bwb_accept_on(r, office_settings(c, oid), _j(d.get("sender"), {}) if locked else None)
    for k in ("sender", "recipient_snapshot", "tax_snapshot"):
        d.pop(k, None)  # the frozen copies stay on the server (the print model shows them)
    d["locked"] = locked
    d["locked_by_name"] = ""
    if locked and r["locked_by"]:
        u = c.execute("SELECT display_name, username FROM users WHERE id=?", (r["locked_by"],)).fetchone()
        d["locked_by_name"] = (u["display_name"] or u["username"]) if u else ""
    d["can_edit"] = not locked and r["status"] != "sent"  # 2.38.0: sent documents are locked as well
    d["can_unlock"] = bool(admin) and locked and not bga_offer_block(c, oid, r)  # 2.114.2 A (#2263): back to a draft, or delete
    d["can_delete"] = d["can_unlock"] if locked else bool(admin) and r["status"] != "sent"
    d["number_at_finalize"] = ofx_number_at_finalize(office_settings(c, oid), r["kind"])
    if r["kind"] == "invoice":  # 2.120.0 D (#2089): "attach timesheet" is offered when the invoice has a client and a period
        d["timesheet_ok"] = bool(r["client_id"] and r["service_from"] and r["service_to"])
    from .agentdocs import ofa_doc_extra
    ofa_doc_extra(c, d)  # 2.51.0 A (#1348): "drafted by agent X", the project list
    if r["kind"] == "offer":
        from .cashflow import cf8_chain
        d["cf_chain"] = cf8_chain(c, oid, r)  # 2.88.0 (#1915): which version of the chain counts in the cash flow
    return d


def doc_brief(r, pm=None):
    rec = _j(r["recipient"], {})
    t = _j(r["totals"], {})
    pm = pm if pm is not None else {}
    state = inv_state(r, pm)
    d = {"id": r["id"], "kind": r["kind"], "number": r["number"], "status": r["status"], "state": state, "status_text": tr(STATUS_TXT.get(state, state)),
         "lang": r["lang"], "currency": r["currency"], "client_id": r["client_id"], "recipient_name": rec.get("name") or "",
         "project_title": r["project_title"], "project_ref": r["project_ref"], "date": r["date"], "valid_until": r["valid_until"],
         "net": t.get("net") or 0, "net_text": fmt_money(t.get("net") or 0, r["lang"], r["currency"]),
         "gross": t.get("gross") or 0, "gross_text": fmt_money(t.get("gross") or 0, r["lang"], r["currency"]),
         "net_incl_raw": t.get("net_incl_raw"), "updated_at": r["updated_at"], "created_by": r["created_by"],
         "locked": ofx_locked(r), "due_date": r["due_date"] if "due_date" in r.keys() else None, "cancels_id": r["cancels_id"] if "cancels_id" in r.keys() else None,
         "inv_type": r["inv_type"] if "inv_type" in r.keys() else ""}  # 2.120.0 A (#2087)
    if r["kind"] == "offer" and "cashflow" in r.keys():  # 2.88.0 (#1915)
        d.update(version_of=r["version_of"], cashflow=r["cashflow"] or "auto")
    if r["kind"] in ("invoice", "credit"):
        d.update(inv_money_fields(r, pm))
        d["open_text"] = fmt_money(d["open"], r["lang"], r["currency"])
    return d


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
    f["raw_mode"] = "included" if ct.get("raw_included") else "optional"  # 2.47.0 (#1645): always, the switch is per document
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
    fk_doc_contact_clean(c, oid, b, cur, f)
    ncid = f["client_id"] if "client_id" in f else _cur_val(cur, "client_id")
    if ncid:  # 2.97.0 B (#1951): a draft with a client: the recipient is the client's (a given "recipient" is ignored)
        kid = f["contact_id"] if "contact_id" in f else _cur_val(cur, "contact_id")
        cl = _client(c, oid, ncid)
        if cl:
            rec = _recipient_from_client(cl, fk_doc_contact_name(c, cl["id"], kid), cdn_home(c, oid))
            rec.pop("missing", None)
            f["recipient"] = json.dumps(rec, ensure_ascii=False)
    elif "recipient" in b and b.get("recipient") is not None:
        f["recipient"] = json.dumps(_recipient_clean(b["recipient"]), ensure_ascii=False)
    for k, mx in (("project_title", NAME_MAX), ("project_ref", 80), ("intro", TEXT_MAX), ("closing", TEXT_MAX), ("order_ref", 80)):
        if k in b:
            f[k] = _text(b.get(k), k, mx)
    for k in ("date", "valid_until", "service_from", "service_to", "due_date"):  # 2.36.2: period of service; 2.38.0: due date
        if k in b:
            f[k] = _date(b.get(k), k)
    nd = f.get("date", cur["date"])
    ndue = f.get("due_date", cur["due_date"] if "due_date" in cur.keys() else None)
    if nd and ndue and ndue < nd and ("date" in f or "due_date" in f):  # 2.38.0 review
        raise BadInput(tr("The due date must not lie before the date"))
    if "payment_days" in b:  # 2.38.0 (#1021, F1): invoice fields
        v = _num(b.get("payment_days"), "payment_days", 0, 365)
        f["payment_days"] = None if v is None else int(v)
    if "vat_note" in b:
        f["vat_note"] = _choice(b.get("vat_note") or "", "vat_note", ("",) + INV_VAT_NOTES)
    if "einvoice_format" in b:
        f["einvoice_format"] = _choice(b.get("einvoice_format") or "", "einvoice_format", ("", "zugferd", "xrechnung"))
    if cur["kind"] == "delivery" and "delivery_title" in b:  # 2.120.0 D (#2089): "Lieferschein" or "Leistungsnachweis"
        f["delivery_title"] = _choice(b.get("delivery_title") or "", "delivery_title", ("", "service"))
    from .abschlag import abs_clean
    abs_clean(b, cur, f)  # 2.120.0 A (#2087): cash discount, progress / final invoice
    if cur["kind"] == "reminder":
        if "reminder_level" in b:
            f["reminder_level"] = int(_num(b.get("reminder_level"), "reminder_level", 1, 3) or 1)
        if "reminder_fee" in b:
            f["reminder_fee"] = _num(b.get("reminder_fee"), "reminder_fee", 0, 1e6) or 0
        if "reminder_deadline_days" in b:
            f["reminder_deadline_days"] = int(_num(b.get("reminder_deadline_days"), "reminder_deadline_days", 0, 365) or 0)
    if f.get("service_from") and f.get("service_to") and f["service_to"] < f["service_from"]:
        raise BadInput(tr("The period of service ends before it starts"))
    if "raw_mode" in b:
        f["raw_mode"] = _choice(b.get("raw_mode"), "raw_mode", RAW_MODES)
    if "producing_on" in b:  # 2.47.0 (#1645): producing per document (the office setting is only the default)
        f["producing_on"] = 0 if b.get("producing_on") in (0, False, "0", "false", None, "") else 1
    if "accept_on" in b:  # 2.114.4 B (#2270): order confirmation block per quotation (None = like the office setting)
        f["accept_on"] = None if b.get("accept_on") in (None, "", "default") else (0 if b.get("accept_on") in (0, False, "0", "false") else 1)
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


def clean_items(c, oid, r, items, admin, part=None):
    """The whole list of positions: [{kind, service_id, title, detail, qty, unit, rate, tax, raw_fee, producing, intext,
    cost, discountable}]. A service_id fills what the position leaves empty (title in the document's language, rate from
    the framework contract or the catalogue, tax and flags). cost only by the admin (others keep the stored value)."""
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise BadInput(tr("Invalid value: {0}", "items"))
    lang = r["lang"]
    ct = _contract(c, oid, r["contract_id"])
    old = {it["id"]: it for it in doc_items(c, r["id"], oid, part)}  # 2.47.0 (#1215): part = the positions of that part
    out = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            raise BadInput(tr("Invalid value: {0}", "items"))
        kind = it.get("kind") or "service"
        if kind == "part" and r["kind"] == "offer" and part is None:  # 2.47.0 (#1215): a part on the title page
            from .parts import tp_clean_item
            out.append(tp_clean_item(c, oid, r, it, i, old.get(it.get("id")) if it.get("id") else None))
            continue
        _choice(kind, "items.kind", ITEM_KINDS if r["kind"] == "offer" else INV_ITEM_KINDS)  # 2.38.0: discount positions on invoices
        row = {"sort": i, "kind": kind, "service_id": None, "title": _text(it.get("title"), "items.title", 500),
               "detail": _text(it.get("detail"), "items.detail", 4000), "qty": 1, "unit": "day", "rate": 0, "tax": "standard",
               "raw_fee": 0, "producing": 0, "intext": "intern", "cost": 0, "discountable": 1}
        prev = old.get(it.get("id")) if it.get("id") else None
        if kind == "discount":  # 2.38.0: a discount position: its amount (qty x rate) is taken off, same tax class
            row["qty"] = _num(it.get("qty"), "items.qty", 0, 1e6) or 1
            row["unit"] = _choice(it.get("unit") or "flat", "items.unit", UNITS)
            row["rate"] = abs(_num(it.get("rate"), "items.rate", -1e8, 1e8) or 0)
            row["tax"] = _choice(it.get("tax") or "standard", "items.tax", TAX_KEYS)
            if not row["title"]:
                raise BadInput(tr("Invalid value: {0}", "items.title"))
        elif kind == "service":
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
                # 2.47.0 (#1645): the flags are always taken over; the switches of the document decide what counts
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
            if sv and not prev and it.get("cost") in (None, ""):  # 2.47.0 (#1649): a new position takes the purchase of the service's role
                row["cost"] = ek_role_cost(c, oid, sv, row["unit"])
        elif not row["title"] and not row["detail"]:
            raise BadInput(tr("Invalid value: {0}", "items.title"))
        out.append(row)
    return out


# ---------------------------------------------------------------- creating
def doc_create(c, oid, uid, b, admin, number=True):
    """A new quotation from the organisation's settings (+ a framework contract / client when given); the number is
    reserved at once. 2.51.0 A (#1348): number=False (an agent's draft) reserves none (a person does, or finalising)."""
    s = office_settings(c, oid)
    kind = _choice(b.get("kind") or "offer", "kind", DOC_KINDS)
    lang = _choice(b.get("lang") or s.get("lang") or "de", "lang", ("de", "en"))
    today = local_now().date()
    if kind != "offer":  # 2.38.0 (#1021, F1): an empty invoice / credit note / reminder draft
        from .invoices import _insert_doc
        row = inv_new_row(c, oid, s, kind, lang)
        cur = dict(row)
        cur["id"] = 0
        cur["kind"] = kind
        row.update(clean_doc(c, oid, {k: v for k, v in b.items() if k != "kind"}, cur, admin))
        inv_apply_client(c, oid, row, b)
        did = _insert_doc(c, oid, uid, row)
        if isinstance(b.get("items"), list) and kind != "reminder":
            _put_items(c, oid, doc_row(c, oid, did), b["items"], admin)
        recalc(c, oid, did)
        return did
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
           "fx_rate": s.get("fx_usd") or 1.09, "vat_mode": "novat" if s.get("small_business") else "vat", "client_id": None, "recipient": json.dumps({"name": "", "lines": []}),
           "project_title": "", "project_ref": "", "date": today.isoformat(),
           "valid_until": (today + timedelta(days=int(s.get("offer_valid_days") or 30))).isoformat(), "contract_id": None,
           "producing_on": 1 if s.get("producing_on") else 0,  # 2.47.0 (#1645): the office setting is the default of a new quotation
           "raw_mode": "optional" if s.get("raw_on") else "none", "raw_factor": s.get("raw_factor") if s.get("raw_factor") is not None else 0.25,
           "prod_quotient": s.get("prod_quotient") or 3, "producing_rate": prod_rate, "discount_pct": 0,
           "intro": _default_text(c, oid, s, "intro", lang), "closing": _default_text(c, oid, s, "closing", lang),
           "rights": json.dumps(rights, ensure_ascii=False), "fields": "[]", "totals": "{}", "created_by": uid, "created_at": ts,
           "updated_at": ts, "sent_at": None}
    if s.get("small_business"):  # 2.47.3 (#1360): section 19 UStG
        row["vat_note"] = "small"
    if row["currency"] not in ("EUR", "USD"):
        row["currency"] = "EUR"
    cur = dict(row)
    cur["id"] = 0
    f = clean_doc(c, oid, {k: v for k, v in b.items() if k != "kind"}, cur, admin)
    row.update(f)
    did = insert_id(c, f"INSERT INTO office_docs({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    if number and not ofx_number_at_finalize(s, kind) and onc_ready(s, doc_row(c, oid, did)):  # 2.36.2 (P2): kinds numbered at finalising stay without a number as drafts; 2.118.0 A (#2265): onc_ready
        _assign_number(c, oid, did, s)
    if isinstance(b.get("items"), list):
        _put_items(c, oid, doc_row(c, oid, did), b["items"], admin)
    recalc(c, oid, did)
    return did


def _assign_number(c, oid, did, s=None, manual=None, reason=""):
    from .legacyimport import fi_number_taken
    write_lock(c, f"office_num_{int(oid)}")  # 2.39.1 (#1210 N2): check and write of a number (manual or next) in one go
    r = doc_row(c, oid, did)
    s = s or office_settings(c, oid)
    if manual is not None:
        num = _text(manual, "number", 80)
        if not num:
            raise BadInput(tr("Invalid value: {0}", "number"))
        if r["kind"] != "offer":  # 2.38.0: only above the series' last value (no back-dating), the counter follows
            inv_manual_number(c, oid, r, s, num, reason)
    else:
        rec = _j(r["recipient"], {})
        d = date.fromisoformat(r["date"]) if r["date"] else local_now().date()
        # 2.118.0 A (#2265): a quotation's duplicate keeps the first one's running number with the next {version};
        # quotations count per organisation, client or project (onc_next)
        ver, num = onc_version(c, oid, r, inv_scheme(s, r["kind"]), lambda x: {"project": x["project_title"], "client": _j(x["recipient"], {}).get("name") or "",
                                                                             "initials": _initials(c, x["created_by"])})
        for _ in range(0 if num else 50):  # a scheme without {seq} uniqueness (e.g. only {date}): keep counting until free
            num, _seq = onc_next(c, oid, s, r, inv_scheme(s, r["kind"]), d, project=r["project_title"], client=rec.get("name") or "",
                                 initials=_initials(c, r["created_by"]), version=ver)
            if not c.execute("SELECT 1 FROM office_docs WHERE org_id=? AND number=? AND id!=?", (oid, num, did)).fetchone() \
                    and not fi_number_taken(c, oid, num):  # 2.39.1 (#1182): nor a number of the legacy archive
                break
    if c.execute("SELECT 1 FROM office_docs WHERE org_id=? AND number=? AND id!=?", (oid, num, did)).fetchone() or fi_number_taken(c, oid, num):
        raise BadInput(tr("The number {0} is already used", num))
    c.execute("UPDATE office_docs SET number=?, updated_at=? WHERE id=? AND org_id=?", (num, iso(now_utc()), did, oid))
    return num


def _initials(c, uid):
    r = c.execute("SELECT display_name, username FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    if not r:
        return ""
    name = r["display_name"] or r["username"] or ""
    return "".join(p[0] for p in name.split() if p)[:4].upper()


def _put_items(c, oid, r, items, admin, flags=None):
    """2.51.0 A (#1348): flags = the agent's marks per position (office/agentdocs.py); a person's save keeps the mark of an
    unchanged position and drops it on a changed or confirmed one (item.confirm)."""
    rows = clean_items(c, oid, r, items, admin)
    if flags is None:
        from .agentdocs import ofa_keep_flags
        flags = ofa_keep_flags(c, oid, r["id"], items, rows)
    c.execute("DELETE FROM office_doc_items WHERE doc_id=? AND org_id=? AND part_id IS NULL", (r["id"], oid))  # 2.47.0 (#1215): not the parts'
    c.execute("DELETE FROM office_doc_items WHERE doc_id=? AND org_id IS NULL", (r["id"],))  # rows of an older version
    for row, fl in zip(rows, flags):
        if fl:
            row["agent_flag"] = fl
        row["doc_id"] = r["id"]
        row["org_id"] = oid
        row = oc_item_store(c, oid, row)  # 2.42.0 (#828): the purchase price encrypted at rest
        c.execute(f"INSERT INTO office_doc_items({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))


# ---------------------------------------------------------------- the print model
def bwb_accept_on(r, s, snd=None):
    """2.114.4 B (#2270): 1 when a quotation prints the order confirmation block: the document's own value, else the office
    setting (default on). snd = the sender snapshot of a finalised document: its frozen value (none = finalised before = on)."""
    if snd is not None:
        return 0 if snd.get("accept_on") == 0 else 1
    v = r["accept_on"] if "accept_on" in r.keys() else None
    if v is None:
        v = s.get("accept_on", 1)
    return 0 if v in (0, False, "0") else 1


def odoc_render(c, doc_id, oid):
    """The print model of a document (dict, see docs/OFFICE.md and tests/fixtures): everything in the document's language
    and formats, nothing of the signed-in person. oid: the organisation the caller works in (required; foreign document =
    404). A finalised document (2.36.2) is printed from its snapshot only: frozen totals, sender, recipient, pack words."""
    r = doc_row(c, oid, doc_id)
    s = office_settings(c, oid)
    locked = ofx_locked(r)
    lang = "en" if r["lang"] == "en" else "de"
    if locked:
        pack = ofx_snapshot_pack(r)
        t = _j(r["totals"], {})
        snd = _j(r["sender"], {})
        co = snd.get("company") or {}
        logo_path = ofx_logo_path(oid, snd.get("logo"))
        color = snd.get("color") or ""
    else:
        pack = office_pack(s["pack"]) or office_pack("DE") or {}
        t = doc_totals(c, oid, r)
        co = ofx_company_print(ofx_company(c, oid), s.get("company") or {}, lang, pack)
        logo_path = None
        if s.get("logo"):
            import os
            from ..core.config import OFFICE_DIR
            p = os.path.join(OFFICE_DIR, str(oid), os.path.basename(s["logo"]))
            logo_path = p if os.path.isfile(p) else None
        color = s.get("color") or ""
    L = dict((pack.get("labels") or {}).get(lang) or {})
    cur = r["currency"]
    for ln in t["lines"]:
        if ln["kind"] in ("item", "producing", "raw", "discount"):
            ln["total_text"] = fmt_money(ln["total"], lang, cur)
            if ln.get("rate") is not None:
                ln["rate_text"] = fmt_money(ln["rate"], lang, cur)
    rec = _j(r["recipient_snapshot"] if locked and r["recipient_snapshot"] else r["recipient"], {})
    if not locked:
        rec = cdn_doc_recipient(c, oid, r, rec)  # 2.97.0 B (#1951): a draft prints its client's address as it is now
    rec = {"name": rec.get("name") or "", "name_extra": rec.get("name_extra") or "", "lines": rec.get("lines") or []}  # 2.99.0 D (#2188)
    rights = _j(r["rights"], {})
    if not re.match(r"^#[0-9a-fA-F]{6}$", color):
        color = "#2f5d8a"
    valid_text = _fmt_date(r["valid_until"], pack)
    meta = [[L.get("offer_no", "Angebot Nr."), r["number"]], [L.get("date", "Datum"), _fmt_date(r["date"], pack)]]
    # 2.114.4 A (#2277): no "Kunde" row any more, the name heads the address field (pdf.py adds it when the lines lack it)
    # 2.97.1 (#2224): the customer number as on the invoice; a document finalised before prints as it did
    if locked and "sender_line" in co:
        cno = _j(r["recipient_snapshot"], {}).get("customer_no") if r["recipient_snapshot"] else ""
    elif not locked and r["client_id"]:
        cl = c.execute(f"SELECT customer_no FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (r["client_id"],)).fetchone()
        cno = cl["customer_no"] if cl else ""
    else:
        cno = ""
    if cno:
        meta.append([L.get("customer_no", "Customer no." if lang == "en" else "Kunden-Nr."), cno])
    if r["project_ref"]:
        meta.append([L.get("ref", "Ref./PO-Nr."), r["project_ref"]])
    if r["valid_until"]:
        meta.append([L.get("valid_until", "Gültig bis"), valid_text])
    sf, st = (r["service_from"] or "", r["service_to"] or "") if "service_from" in r.keys() else ("", "")
    if sf or st:  # 2.36.2: period of service
        per = _fmt_date(sf, pack) if sf == st or not st else (_fmt_date(st, pack) if not sf else f"{_fmt_date(sf, pack)} – {_fmt_date(st, pack)}")
        meta.append([L.get("service_period", "Period of service" if lang == "en" else "Leistungszeitraum"), per])
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
    # 2.97.1 (#2224): with the company name; a document finalised before keeps the line it was printed with
    sender_line = co["sender_line"] if locked and "sender_line" in co else (" · ".join(x for x in (co.get("lines") or []) if x) if locked else ofx_sender_line(co))
    m = {
        "kind": r["kind"], "lang": lang, "locked": locked, "locked_at": r["locked_at"] if locked else None,
        "pack_version": (r["pack_version"] or "") if locked else str(pack.get("version") or ""),
        "service_from": r["service_from"] or "", "service_to": r["service_to"] or "", "currency": cur, "fx_rate": t.get("fx_rate"), "fx_note": t.get("fx_note") or "", "vat_mode": t["vat_mode"],
        "raw_mode": t["raw_mode"], "status": r["status"], "number": r["number"], "date": r["date"], "date_text": _fmt_date(r["date"], pack),
        "valid_until": r["valid_until"], "valid_until_text": valid_text, "title": L.get("offer", "Kostenvoranschlag" if lang == "de" else "Quotation"),
        "project_title": r["project_title"], "project_ref": r["project_ref"],
        "company": {"name": co.get("name") or "", "name_lines": co.get("name_lines") or [], "lines": co.get("lines") or [], "contact_lines": co.get("contact_lines") or [],
                    "register_lines": co.get("register_lines") or [], "bank_lines": co.get("bank_lines") or [],
                    "sender_line": sender_line, "logo_path": logo_path, "color": color},  # 2.99.0 D (#2188): name_lines; 2.97.1 (#2224): sender_line
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
    m["accept_on"] = bwb_accept_on(r, s, snd if locked else None)  # 2.114.4 B (#2270)
    if r["kind"] == "offer":  # 2.47.0 (#1215): the printed parts as own pages
        from .parts import tp_render
        tp_render(c, oid, r, m, pack, lang, locked)
    if r["kind"] != "offer":  # 2.38.0 (#1021, F1): the invoice words on top (title, due date, tax lines, reminder table, payment info)
        inv_render(c, oid, r, m, t, pack, L, lang, _fmt_date)
    return m


# ---------------------------------------------------------------- routes
@app.get("/api/office/docs")
def odoc_list():
    """?kind=offer&status=&q= -> the organisation's documents, newest first (brief rows)."""
    c, uid, oid = _ctx()
    kind = request.args.get("kind") or "offer"
    if kind not in DOC_KINDS:
        kind = "offer"
    sql, args = "SELECT * FROM office_docs WHERE org_id=? AND kind=?", [oid, kind]
    st = request.args.get("status")
    if st in STATUSES + ("issued", "paid", "cancelled") and st not in ("partial", "overdue"):
        sql += " AND status=?"
        args.append(st)
    q = (request.args.get("q") or "").strip()
    if q:
        like = f"%{like_escape(q)}%"
        sql += " AND (number ILIKE ? ESCAPE '\\' OR project_title ILIKE ? ESCAPE '\\' OR project_ref ILIKE ? ESCAPE '\\' OR recipient ILIKE ? ESCAPE '\\')"
        args += [like, like, like, like]
    pm = inv_paid_map(c, oid) if kind in ("invoice", "credit") else {}
    raw = c.execute(sql + " ORDER BY date DESC, id DESC LIMIT 500", args).fetchall()
    rows = [doc_brief(r, pm) for r in raw]
    role = office_role(c, uid, oid)
    if kind == "offer" and role == "admin":  # 2.114.2 A (#2263): which finalised quotations the row menu may delete
        for b, r in zip(rows, raw):
            if b["locked"] and r["status"] == "draft":
                b["can_delete"] = b["can_unlock"] = not bga_offer_block(c, oid, r)
    if kind in ("invoice", "reminder"):  # 2.40.0 (#1368 points 8 + 9): open reminder fees, settled reminders ("done")
        from .invoices import fd_reminder_extra
        fd_reminder_extra(c, oid, rows)
    if st in ("partial", "overdue"):  # derived states: filtered after the fact
        rows = [x for x in rows if x["state"] == st]
    return jsonify(docs=rows, role=role, org_id=oid)


@app.post("/api/office/docs")
def odoc_create():
    """{kind?: offer, lang?, client_id?, contract_id?, project_title?, recipient?, items?: [...]} -> 201 the document (number
    reserved, unless the organisation numbers quotations when they are finalised)."""
    c, uid, oid = _ctx()
    office_seed_texts(c, oid)
    admin = office_role(c, uid, oid) == "admin"
    b = body()
    if not isinstance(b, dict):
        return err(tr("Invalid data"))
    did = doc_create(c, oid, uid, b, admin)
    r = doc_row(c, oid, did)
    ofx_log(c, oid, "create", doc_id=did, detail={"number": r["number"], "items": len(doc_items(c, did, oid))})
    bump(c)
    c.commit()
    return jsonify(doc_public(c, oid, r, admin)), 201


@app.get("/api/office/docs/<int:did>")
def odoc_get(did):
    c, uid, oid = _ctx()
    r = doc_row(c, oid, did)
    ofx_log(c, oid, "open", doc_id=did, dedupe_min=10)
    c.commit()
    return jsonify(doc_public(c, oid, r, office_role(c, uid, oid) == "admin"))


@app.patch("/api/office/docs/<int:did>")
def odoc_update(did):
    """Head fields (partial); contract_id (changed) presets raw data / rights / closing unless apply_contract: false;
    client_id fills the recipient from the client (2.97.0 B #1951: always, a given recipient is ignored while the document
    has a client; it is read from the client until the document is finalised / sent). Returns the document with totals.
    A finalised document: 409."""
    c, uid, oid = _ctx()
    admin = office_role(c, uid, oid) == "admin"
    r = doc_row(c, oid, did)
    ofx_need_editable(r)
    b = body()
    if not isinstance(b, dict):
        return err(tr("Invalid data"))
    f = clean_doc(c, oid, b, r, admin)
    from .doclang import fd_lang_swap, fd_put_titles  # 2.40.0 (#1381, #1363): a new language swaps unchanged standard texts
    lang_notes, titles = fd_lang_swap(c, oid, r, b, f)
    if f:
        diff = ofx_diff({k: r[k] for k in f if k in r.keys()}, f)
        f["updated_at"] = iso(now_utc())
        c.execute(f"UPDATE office_docs SET {','.join(k + '=?' for k in f)} WHERE id=? AND org_id=?", [*f.values(), did, oid])
        if diff["after"]:
            ofx_log(c, oid, "update", doc_id=did, detail=diff)
    fd_put_titles(c, oid, did, titles)
    n = doc_row(c, oid, did)  # 2.118.0 A (#2265): a quotation counted per client / project gets its number once it has one
    if n["kind"] == "offer" and not n["number"] and not r["number"] and f:
        s = office_settings(c, oid)
        if (s.get("offer_counter") or "org") != "org" and not ofx_number_at_finalize(s, "offer") and onc_ready(s, n):
            _assign_number(c, oid, did, s)
    recalc(c, oid, did)
    bump(c)
    c.commit()
    out = doc_public(c, oid, doc_row(c, oid, did), admin)
    if lang_notes:
        out["lang_notes"] = lang_notes
    return jsonify(out)


@app.put("/api/office/docs/<int:did>/items")
def odoc_items_put(did):
    """{items: [...]} the whole list of positions in order (see clean_items). Returns the document with totals.
    A finalised document: 409."""
    c, uid, oid = _ctx()
    admin = office_role(c, uid, oid) == "admin"
    r = doc_row(c, oid, did)
    ofx_need_editable(r)
    b = body()
    items = b.get("items") if isinstance(b, dict) else b
    rows_before = doc_items(c, did, oid)
    before = ofx_items_brief(rows_before)
    _put_items(c, oid, r, items, admin)
    if isinstance(b, dict) and "parts_known" in b:  # 2.138.0 A (#2239): a list built before a part was added keeps its line
        from .parts import kva_keep_unseen_parts
        kva_keep_unseen_parts(c, oid, r, rows_before, b.get("parts_known"))
    after = ofx_items_brief(doc_items(c, did, oid))
    if before != after:
        ofx_log(c, oid, "items", doc_id=did, detail={"before": before, "after": after})
    recalc(c, oid, did)
    bump(c)
    c.commit()
    return jsonify(doc_public(c, oid, doc_row(c, oid, did), admin))


@app.post("/api/office/docs/<int:did>/number")
def odoc_number(did):
    """{number?} sets a number by hand (unique within the organisation) or reserves the next one of the scheme.
    A finalised document: 409."""
    c, uid, oid = _ctx()
    r = doc_row(c, oid, did)
    ofx_need_editable(r)
    b = body()
    b = b if isinstance(b, dict) else {}
    reason = _text(b.get("reason"), "reason", 300)
    num = _assign_number(c, oid, did, manual=b.get("number") if "number" in b else None, reason=reason)
    if num != r["number"]:
        ofx_log(c, oid, "number", doc_id=did, detail={"before": {"number": r["number"]}, "after": {"number": num, **({"reason": reason} if reason else {})}})
    bump(c)
    c.commit()
    return jsonify(id=did, number=num)


@app.post("/api/office/docs/<int:did>/status")
def odoc_status(did):
    """{status: draft|sent|accepted|declined}; sent sets sent_at (once). Also for finalised quotations."""
    c, uid, oid = _ctx()
    r = doc_row(c, oid, did)
    b = body()
    st = _choice((b if isinstance(b, dict) else {}).get("status"), "status", STATUSES if r["kind"] == "offer" else INV_STATUSES[r["kind"]])
    odoc_set_status(c, oid, did, st, uid, r)
    bump(c)
    c.commit()
    return jsonify(doc_public(c, oid, doc_row(c, oid, did), office_role(c, uid, oid) == "admin", items=False))


def odoc_set_status(c, oid, did, st, uid, r=None):
    """2.50.0 (#1200): the status change of document did (checked, logged, purchase, pipeline), shared by the route above
    and the customer's approval (office/signoff.py, uid None). Denied 403 / 409 when not allowed; the caller commits."""
    r = r or doc_row(c, oid, did)
    if r["kind"] == "offer" and st == "draft" and r["status"] != "draft":  # 2.39.0 (#1209 audit N1): sent = locked, a copy for changes
        raise Denied(409, tr("This status change is not allowed ({0} to {1})", r["status"], st))
    ts = iso(now_utc())
    if r["kind"] != "offer" and "paid" in (st, r["status"]) and st != r["status"] and office_role(c, uid, oid) != "admin":
        raise Denied(403, tr("Only an admin of this organisation can record payments"))  # 2.39.1 (#1210 N3, decided 12.10.)
    if r["kind"] != "offer" and st != r["status"]:  # 2.38.0: issued only by finalising, never back to draft, cancelled only by a credit note
        ok = ofx_locked(r) and r["status"] != "cancelled" and st in ("sent", "paid") and (st != "paid" or r["kind"] == "invoice")
        if not ok:
            raise Denied(409, tr("This status change is not allowed ({0} to {1})", r["status"], st))
        if r["status"] == "paid" and c.execute("SELECT 1 FROM office_payments WHERE org_id=? AND doc_id=? LIMIT 1", (oid, did)).fetchone():
            raise Denied(409, tr("Payments are recorded on this invoice; remove them first"))  # 2.38.0 review
    c.execute("UPDATE office_docs SET status=?, updated_at=?, sent_at=COALESCE(sent_at, ?) WHERE id=? AND org_id=?",
              (st, ts, ts if st in ("sent", "accepted", "declined") else None, did, oid))
    if r["kind"] != "offer":
        c.execute("UPDATE office_docs SET paid_at=CASE WHEN status='paid' THEN COALESCE(paid_at, ?) ELSE NULL END WHERE id=? AND org_id=?", (ts, did, oid))
    if st != r["status"]:
        ofx_log(c, oid, "status", doc_id=did, detail={"before": {"status": r["status"]}, "after": {"status": st}})
        if r["kind"] == "offer":
            ek_purchases_write(c, oid, did)  # 2.47.0 (#1649): accepted = its purchase is written, left = removed
            from .pipeline import pl2_offer_status  # 2.50.0 (#1196): a linked deal of the pipeline follows (one place for both callers)
            pl2_offer_status(c, oid, did, st)
            if st == "accepted":
                from .agentdocs import ofa_offer_accepted
                ofa_offer_accepted(c, oid, did)  # 2.51.0 A (#1348): the event offer_accepted to the area's office agents


# 2.36.2: columns a copy never takes over (identity, state, the frozen snapshot of a finalised original)
DUP_SKIP = {"id", "number", "status", "created_at", "updated_at", "sent_at", "created_by", "date", "valid_until", "totals", "locked_at",
            "locked_by", "sender", "recipient_snapshot", "tax_snapshot", "pack_version",
            "due_date", "paid_at", "pdf_sha256", "xml_sha256", "datev_sent_at",  # 2.38.0: the invoice's own marks
            "cancels_id", "ref_doc_ids", "source_doc_id",  # 2.38.0 review: a copy is a fresh document, bound to nothing
            "version_of", "cashflow",  # 2.88.0 (#1915): set below (a quotation's copy = its next version, cash flow auto)
            "series_id", "series_period", "abs_refs"}  # 2.120.0 A (#2087): abs_refs  # 2.91.0 A (#1923): a copy is no invoice of the series (office/recurring.py sets them itself)
DUP_ITEM_SKIP = {"id", "tax_pct", "net", "tax_amount"}


@app.post("/api/office/docs/<int:did>/duplicate")
def odoc_duplicate(did):
    """A copy as a new draft of today with the next number (positions, rights and texts copied); also of a finalised
    document (= a new version)."""
    c, uid, oid = _ctx()
    admin = office_role(c, uid, oid) == "admin"
    r = doc_row(c, oid, did)
    s = office_settings(c, oid)
    row = {k: r[k] for k in r.keys() if k not in DUP_SKIP}
    today = local_now().date()
    ts = iso(now_utc())
    row.update(number="", status="draft", date=today.isoformat(), totals="{}", created_by=uid, created_at=ts, updated_at=ts, sent_at=None,
               valid_until=(today + timedelta(days=int(s.get("offer_valid_days") or 30))).isoformat() if r["kind"] == "offer" else "")
    if r["kind"] == "offer":  # 2.88.0 (#1915): the chain of versions points at its first quotation (a copy of a copy too)
        row["version_of"] = r["version_of"] or r["id"]
    nid = insert_id(c, f"INSERT INTO office_docs({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    for it in doc_items(c, did, oid):
        it = {k: v for k, v in it.items() if k not in DUP_ITEM_SKIP}
        it["doc_id"] = nid
        it["org_id"] = oid
        it = oc_item_store(c, oid, it)  # 2.42.0 (#828)
        c.execute(f"INSERT INTO office_doc_items({','.join(it)}) VALUES({','.join('?' * len(it))})", list(it.values()))
    if r["kind"] == "offer":  # 2.47.0 (#1215): the parts with their positions
        from .parts import tp_duplicate
        tp_duplicate(c, oid, did, nid)
    if not ofx_number_at_finalize(s, r["kind"]) and onc_ready(s, doc_row(c, oid, nid)):  # 2.118.0 A (#2265): onc_ready
        _assign_number(c, oid, nid, s)
    recalc(c, oid, nid)
    n = doc_row(c, oid, nid)
    ofx_log(c, oid, "duplicate", doc_id=nid, detail={"from_id": did, "from_number": r["number"], "number": n["number"]})
    bump(c)
    c.commit()
    return jsonify(doc_public(c, oid, n, admin)), 201


# 2.114.2 A (#2263): a finalised quotation that never left the house may go (decision of 2026-10-19)
BGA_SENT = N_("This quotation was sent to the client; the record is kept")
BGA_USED = N_("An invoice or a document was made from this quotation; the record is kept")


def bga_offer_block(c, oid, r):
    """2.114.2 A (#2263): why finalised document r cannot be deleted (None = it can): only a quotation still in draft that
    was never sent (sent_at, a logged mail), never answered by the client (signoffs) and that nothing was made from (an
    invoice's source_doc_id, an order confirmation in office_gen_docs). Open signoff links go with it (ON DELETE CASCADE)."""
    if r["kind"] != "offer" or r["status"] != "draft":
        return OFX_LOCKED
    if r["sent_at"] or c.execute("SELECT 1 FROM office_doc_log WHERE org_id=? AND doc_id=? AND action='send' LIMIT 1",
                                 (oid, r["id"])).fetchone():
        return BGA_SENT
    if c.execute("SELECT 1 FROM office_signoffs WHERE doc_id=? AND org_id=? AND state <> 'open' LIMIT 1", (r["id"], oid)).fetchone():
        return N_("The customer has signed this quotation; the record is kept")
    if c.execute("SELECT 1 FROM office_docs WHERE org_id=? AND source_doc_id=? LIMIT 1", (oid, r["id"])).fetchone() or \
            c.execute("SELECT 1 FROM office_gen_docs WHERE org_id=? AND doc_id=? LIMIT 1", (oid, r["id"])).fetchone():
        return BGA_USED
    return None


@app.delete("/api/office/docs/<int:did>")
def odoc_delete(did):
    """The organisation's admin only (members: 403); a finalised document: 409 (2.114.2 A, #2263: except a finalised
    quotation that was never sent, see bga_offer_block)."""
    c, uid, oid = _ctx()
    write_lock(c, f"office_mail_{int(oid)}")  # 2.114.2 (#2263 review): no mail send / unlock / finalise in between
    write_lock(c, f"office_doc_{int(did)}")
    r = doc_row(c, oid, did)
    if office_role(c, uid, oid) != "admin":
        raise Denied(403, tr("Only an admin of this organisation can do this"))
    locked = ofx_locked(r)
    if locked:
        why = bga_offer_block(c, oid, r)
        if why:
            raise Denied(409, tr(why))
    else:
        ofx_need_editable(r)
    if c.execute("SELECT 1 FROM office_signoffs WHERE doc_id=? AND org_id=? AND state <> 'open' LIMIT 1", (did, oid)).fetchone():
        raise Denied(409, tr("The customer has signed this quotation; the record is kept"))  # 2.50.0 (#1200 review)
    ofx_log(c, oid, "delete", doc_id=did, detail={"number": r["number"], "status": r["status"], "net": _j(r["totals"], {}).get("net"),
                                                  **({"locked": True} if locked else {})})  # 2.114.2 A (#2263): the number gap stays traceable
    c.execute("DELETE FROM office_docs WHERE id=? AND org_id=?", (did, oid))
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
    ofx_log(c, oid, "render", doc_id=did, dedupe_min=10)
    c.commit()
    return jsonify(rd)
