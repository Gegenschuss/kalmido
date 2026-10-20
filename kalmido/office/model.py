"""Office & finance (2.36.1, #1021, module "office"): the gate, the organisation one works in, the module's settings and
the master data of an organisation (services, equipment + sets, text blocks, framework contracts, number counters).

Everything belongs to an organisation (tenant): every table has org_id; every query filters by it. The module exists only
for every person with the feature "office": in an organisation's workspace its office, in "Private" (and without any
organisation) the person's own personal office (2.47.3, #1360: pb_personal, a hidden orgs row). Agent tokens and kid
accounts never get in (403 before any data is read). Org admins manage settings and master data; org members read the
master data and write documents (see docs.py); foreign ids are 404, never 403 with content."""
import json
import re
from datetime import date

from flask import g, has_request_context

from ..core.i18n import N_, tr
from ..core.pg import insert_id, like_escape, table_columns
from ..core.db import db, iso, now_utc, usettings
from ..accounts.session import me
from ..core.access import Denied
from ..personal.timetrack import BadInput
from .packs import office_pack, office_pack_codes

OFFICE_FEAT = "office"
OFFICE_NO_ORG = N_("Choose a workspace at the top (Private or an organisation) to open its office")  # 2.47.3 (#1360)
OFFICE_ADMIN_ONLY = N_("Only an admin of this organisation can do this")
OFFICE_OFF = N_("Office & finance is turned off in your settings")
UNITS = ("day", "hour", "piece", "minute", "flat", "percent")  # 2.47.0 (#1649): percent = a rate on the external fees (KSK)
TAXES = ("standard", "reduced", "exempt")
INTEXT = ("intern", "extern", "shooting")  # 2.47.0 (#1216): shooting = only in the shoot calculation
CREW_INTEXT = ("intern", "extern")  # 2.47.0 (#1649): the Drehpersonal
TEXT_KINDS = ("rights_time", "rights_territory", "rights_media", "intro", "closing", "note", "block", "raw_note")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
SCHEME_RE = re.compile(r"\{(yyyy|yy|seq(?::0?(\d{1,2}))?|project|client|date|isodate|initials|version)\}")  # 2.118.0 A (#2265): version; 2.138.2 A (#2391): isodate
NAME_MAX = 200
# 2.99.0 D (#2188, decision 18.10.2026): the own company name may have up to three lines (stored with line breaks); the
# letterhead and the footer print them one under the other, the sender line, mails and the e-invoice (BT-27) on one line
OFX_NAME_LINES = 3


def ofx_name_lines(v):
    """The lines of a (company) name: whitespace folded per line, empty lines dropped."""
    return [x for x in (re.sub(r"\s+", " ", ln).strip() for ln in str(v or "").replace("\r", "").split("\n")) if x]


def ofx_name1(v):
    """A (company) name on one line: its lines joined with a space."""
    return " ".join(ofx_name_lines(v))


def ofx_name_clean(v, mx=NAME_MAX):
    """A name of up to OFX_NAME_LINES lines (control characters out, the lines joined with \\n); more lines: BadInput."""
    lines = ofx_name_lines(re.sub(r"[\x00-\x09\x0b-\x1f\x7f]", " ", str(v or "")))
    if len(lines) > OFX_NAME_LINES:
        raise BadInput(tr("The company name has at most {0} lines.", OFX_NAME_LINES))
    return "\n".join(lines)[:mx].strip()


TEXT_MAX = 8000

# ---- settings (office_settings.data), defaults filled from the country pack
SETTINGS_DEFAULTS = {"pack": "DE", "company": {"name": "", "lines": [], "contact_lines": [], "register_lines": [], "bank_lines": []},
                     "logo": "", "color": "", "lang": "de", "currency": "EUR", "fx_usd": 1.09, "offer_scheme": "KVA-{yyyy}-{seq:03}",
                     "prod_quotient": 3, "raw_factor": 0.25, "producing_service_id": None, "producing_rate": 600,
                     "offer_valid_days": 30, "intro_text_id": {"de": None, "en": None}, "closing_text_id": {"de": None, "en": None},
                     "rights_default": {"time_id": None, "territory_id": None, "media_id": None},
                     "offer_number_at": "create",  # 2.36.2 (P2): "create" | "finalize" (see ledger.OFX_NUMBER_AT_FINALIZE)
                     "offer_counter": "org",  # 2.118.0 A (#2265): quotation counter per "org" | "client" | "project" (OFFER_COUNTERS)
                     # 2.38.0 (#1021, F1): invoices -- number schemes per kind (defaults from the pack), payment terms, reminders,
                     # the e-invoice format and the DATEV document inbox (one e-mail address; PDF + XML are mailed there)
                     "invoice_scheme": "", "credit_scheme": "", "reminder_scheme": "", "delivery_scheme": "", "payment_days": 14, "reminder_fee": 0,
                     "reminder_deadline_days": 10, "einvoice_format": "zugferd", "datev_email": "", "datev_auto": 0,
                     "invoice_closing_de": "", "invoice_closing_en": "", "reminder_text_de": "", "reminder_text_en": "",
                     # 2.40.0 (#1379): producing (markup by production days) and the raw data surcharge are switched on per
                     # organisation; new organisations start without them, fe_office_rules_migrate keeps them for those using them
                     "producing_on": 0, "raw_on": 0,
                     "portal_docs": 0,  # 2.120.0 B (#2088): sent documents show in the customer portal (office/portaldocs.py)
                     "accept_on": 1,  # 2.114.4 B (#2270): quotations print the order confirmation block (per document: docs.accept_on)
                     # 2.113.1 (#2251): day rate and factor of "share by amount" (an industry pack's option); None = the
                     # pack's values. prod_quotient / producing_rate above keep their old meaning for older documents
                     "share_rate": None, "share_factor": None,
                     # 2.47.3 (#1360): small business (section 19 UStG): new documents without VAT + the note (also orgs)
                     "small_business": 0,
                     # 2.47.0 (#1216): industry packs switched on (office/packs/industry/<code>.json; "film" = shoot calculation)
                     "industry_packs": [],
                     # 2.47.0 (#1215): an invoice from a quotation with parts: "full" (like the quotation), "title" (the title
                     # page with its positions) or "summary" (one position per tax rate with this title)
                     "parts_invoice_mode": "full", "parts_summary_title_de": "Filmherstellung", "parts_summary_title_en": "Film production",
                     # 2.47.3 (#1460): the DATEV booking batch export (office.datev: advisor / client number, chart, accounts)
                     "datev_extf": {},
                     # 2.51.0 A (#1348): agents may read office data (clients, prices) -- they go to the agent's AI model; off by
                     # default, needed together with the agent's own switch "may draft office documents" (office/agentdocs.py)
                     "agents_read": 0,
                     # 2.67.0 A (#1838): the monthly task "Cash flow: check the actual state" (set only by its own route,
                     # office/fixedimport.py): on, the person it goes to, the id of the task
                     "cf_check": 0, "cf_check_user": None, "cf_check_task": None,
                     # 2.90.0 A (#1921): bookkeeping light: tax reserve in percent of the net income received (0 = off), VAT
                     # on payment received ("ist") or on invoicing ("soll") for the VAT return figures
                     "tax_reserve_pct": 0, "vat_basis": "ist",
                     # 2.90.0 C (#1922): tax dates as tasks (set only by its own route, office/taxdates.py)
                     "tax_dates": {},
                     # 2.93.0 B (#1928): the mileage allowance per business km of the logbook (set only by its own route,
                     # office/logbook.py)
                     "km_rate": "0.30",
                     # 2.93.0 B (#1928 review): the rate per year {"2026": "0.30"}; km_rate stays the default of years without one
                     "km_rates": {},
                     # 2.120.0 A (#2087): the default cash discount of new invoices (0 = none; office/abschlag.py)
                     "skonto_pct": 0, "skonto_days": 0,
                     # 2.120.0 E (#2091): the own letterhead PDF + margins (set only by its own routes, office/letterhead.py)
                     "letterhead": {},
                     # 2.113.2 (#2253): the terms and conditions as PDF per language (set only by their own routes, office/terms.py)
                     "terms": {}}
SETTINGS_KEYS = tuple(SETTINGS_DEFAULTS)


# ---------------------------------------------------------------- gate + organisation
def office_on(c, uid):
    return OFFICE_FEAT in (usettings(c, uid).get("features") or "").split(",")


def office_gate(c):
    """403 for agent tokens and kids, 403 without the feature "office". Call first in every route of the module."""
    u = g.user
    if u is None:
        raise Denied(401)
    if (u["kind"] if "kind" in u.keys() else "user") == "agent":
        raise Denied(403, tr("Agents cannot use this endpoint"))
    if "kid" in u.keys() and u["kid"]:
        raise Denied(403)
    if not office_on(c, u["id"]):
        raise Denied(403, tr(OFFICE_OFF))
    return u["id"]


def office_org(c, uid, admin=False):
    """The office area uid works in (its id, the org_id of every office_* row): the organisation of the setting "workspace"
    (org:<id>, a membership); 2.47.3 (#1360): the workspace "private", no organisation at all or the mode shared -> the
    person's own personal office (pb_personal, the person is its admin); "all" with exactly one organisation -> that one
    (as before). Otherwise 400 with a readable text. admin=True also requires the admin role (403)."""
    from ..accounts.orgs import org_role, user_orgs
    orgs = user_orgs(c, uid)
    ws = (usettings(c, uid).get("workspace") or "").strip()
    m = re.fullmatch(r"org:(\d{1,9})", ws)
    if m and int(m.group(1)) in orgs:
        oid = int(m.group(1))
        role = org_role(c, uid, oid)
    elif ws == "private" or not orgs:  # 2.47.3 (#1360): no silent fallback to the only organisation in "private"
        oid, role = pb_personal(c, uid), "admin"
    elif len(orgs) == 1:
        oid = orgs[0]
        role = org_role(c, uid, oid)
    else:
        raise BadInput(tr(OFFICE_NO_ORG))
    if not oid or not role:
        raise BadInput(tr(OFFICE_NO_ORG))
    from ..accounts.orgroles import office_allowed
    no = office_allowed(c, uid, oid)  # 2.143.0 A (#2151): guest none; read-only reads; accounting reads + exports
    if admin and role != "admin" and not (role == "accounting" and no is None):  # accounting reads the admins' bookkeeping
        raise Denied(403, tr(OFFICE_ADMIN_ONLY))
    if no:
        raise Denied(403, tr(no))
    return oid


def office_role(c, uid, oid):
    """The role of uid in office area oid: admin | member | None. 2.47.3 (#1360): a personal office has exactly one
    person, its owner (admin); nobody else has a role there."""
    owner = pb_owner(c, oid)
    if owner is not None:
        return "admin" if owner == uid else None
    from ..accounts.orgs import org_role
    return org_role(c, uid, oid)


# ---------------------------------------------------------------- 2.47.3 (#1360): the personal office
def pb_owner(c, oid):
    """The owner of office area oid when it is a personal office, else None (cached per request)."""
    if not oid:
        return None
    cache = g.setdefault("pb_owner", {}) if has_request_context() else {}
    if oid not in cache:
        from ..core.pg import system_ctx
        with system_ctx(c):  # instance structure: which person a personal office belongs to
            r = c.execute("SELECT personal_of FROM orgs WHERE id=?", (oid,)).fetchone()
        cache[oid] = r[0] if r else None
    return cache[oid]


def pb_personal(c, uid, create=True):
    """The id of uid's personal office: a hidden orgs row (personal_of = uid, no members) that shows nowhere as an
    organisation; made on the first use (create=False: None while there is none). The owner's access context carries it
    (core/access.py _ctx_build), so row-level security lets only the owner read and write its office_* rows."""
    from ..core.pg import system_ctx
    with system_ctx(c):  # instance structure: the person's own hidden area, never somebody else's
        r = c.execute("SELECT id FROM orgs WHERE personal_of=?", (uid,)).fetchone()
        if r or not create:
            return r[0] if r else None
        c.execute("INSERT INTO orgs(name,icon,created_at,personal_of) VALUES(?,?,?,?) ON CONFLICT (personal_of) WHERE personal_of IS NOT NULL DO NOTHING",
                  (f"private-{int(uid)}", "", iso(now_utc()), uid))
        oid = c.execute("SELECT id FROM orgs WHERE personal_of=?", (uid,)).fetchone()[0]
    c.commit()  # at once (also on a reading request): the area exists before anything is written into it
    from ..core.access import acx_drop
    acx_drop()  # the next statement runs with the new id in app.org_ids
    return oid


def pb_cl_sql(c, oid, col="org_id", by="created_by"):
    """The SQL condition on clients of office area oid (only integers, no parameters): an organisation's clients
    (org_id), in a personal office the owner's private clients (org_id NULL, created by the owner = the same clients the
    workspace "Private" shows)."""
    owner = pb_owner(c, oid)
    if owner is not None:
        return f"({col} IS NULL AND {by}={int(owner)})"
    return f"{col}={int(oid)}"


def pb_cl_where(c, oid, col="org_id", by="created_by"):
    """(sql, args) form of pb_cl_sql (announced in iface.txt for the other parts' modules)."""
    return pb_cl_sql(c, oid, col, by), ()


def pb_info(c, uid, oid):
    """The fields of GET /api/office/settings about the area: personal (1 = the person's own office) and, while that
    office is still empty, the organisations of the person (their offices are in their workspaces: the hint + switch)."""
    if pb_owner(c, oid) is None:
        return {"personal": 0}
    from ..accounts.orgs import instance_mode, user_orgs
    orgs = user_orgs(c, uid)
    u = getattr(g, "user", None) if has_request_context() else None
    move = {"can_move": 1 if u is not None and u["is_admin"] and instance_mode(c) == "workspaces" else 0}  # POST /api/office/move
    # 2.137.0 D (#1981): the organisations the person is an admin of (POST /api/office/move/org takes the office into one)
    from ..accounts.orgs import org_role
    adm = [o for o in orgs if org_role(c, uid, o) == "admin"]
    move["move_orgs"] = [{"id": r["id"], "name": r["name"]} for r in c.execute(
        f"SELECT id, name FROM orgs WHERE id IN ({','.join('?' * len(adm))}) AND personal_of IS NULL ORDER BY lower(name)", adm)] if adm else []
    used = c.execute("SELECT 1 FROM office_docs WHERE org_id=? UNION ALL SELECT 1 FROM office_services WHERE org_id=? LIMIT 1", (oid, oid)).fetchone()
    if used or not orgs:
        return {"personal": 1, "org_offices": [], **move}
    from ..accounts.orgs import workspaces_for
    return {"personal": 1, "org_offices": [{"id": w["id"], "name": w["name"]} for w in workspaces_for(c, uid)], **move}


def pb_cl_org(c, oid):
    """The org_id a client of office area oid gets (None in a personal office: a private client)."""
    return None if pb_owner(c, oid) is not None else oid


# ---------------------------------------------------------------- settings
def office_settings(c, oid):
    """The module's settings of organisation oid (dict with every key, defaults from the country pack)."""
    r = c.execute("SELECT data FROM office_settings WHERE org_id=?", (oid,)).fetchone()
    try:
        d = json.loads(r["data"]) if r and r["data"] else {}
    except ValueError:
        d = {}
    if isinstance(d, dict):  # 2.42.0 (#828): the company lines (bank / tax) are encrypted at rest
        from ..core.orgcrypt import oc_json_load
        oc_json_load(c, oid, "office_settings", "data", d)
    out = json.loads(json.dumps(SETTINGS_DEFAULTS))
    for k in SETTINGS_KEYS:
        if k in d and d[k] is not None:
            if isinstance(out[k], dict) and isinstance(d[k], dict):
                out[k].update(d[k])
            else:
                out[k] = d[k]
    from .catalog import pkc_bind
    pkc_bind(c, oid)  # 2.76.0 (#1023): office_pack / dk_pack resolve the packs installed in this office area from here on
    pack = office_pack(out["pack"]) or office_pack("DE")
    if pack:
        out["currency"] = out["currency"] or pack["currency"]
        if not out.get("offer_scheme"):
            out["offer_scheme"] = (pack.get("numbering") or {}).get("offer") or SETTINGS_DEFAULTS["offer_scheme"]
        for k, dflt in (("invoice", "RE-{yyyy}-{seq:03}"), ("credit", "GS-{yyyy}-{seq:03}"), ("reminder", "MA-{yyyy}-{seq:03}"), ("delivery", "LS-{yyyy}-{seq:03}")):  # 2.38.0; 2.120.0 D (#2089)
            if not out.get(k + "_scheme"):
                out[k + "_scheme"] = (pack.get("numbering") or {}).get(k) or dflt
    return out


def _num(v, name, lo=None, hi=None, allow_none=False):
    if v is None or v == "":
        if allow_none:
            return None
        raise BadInput(tr("Invalid value: {0}", name))
    if isinstance(v, str):
        v = v.strip().replace(" ", "").replace(",", ".")
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", name))
    if f != f or (lo is not None and f < lo) or (hi is not None and f > hi):
        raise BadInput(tr("Invalid value: {0}", name))
    return f


def _lines(v, name, n=12, mx=200):
    if v is None:
        return []
    if isinstance(v, str):
        v = v.splitlines()
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise BadInput(tr("Invalid value: {0}", name))
    v = [re.sub(r"[\x00-\x1f\x7f]", "", x) for x in v]  # 2.39.0 (#1209 audit M2): no control characters in the frozen sender
    return [x.strip()[:mx] for x in v if x.strip()][:n]


def _id_or_none(c, v, table, oid, name):
    if v in (None, "", 0, "0"):
        return None
    try:
        i = int(v)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", name))
    if not c.execute(f"SELECT 1 FROM {table} WHERE id=? AND org_id=?", (i, oid)).fetchone():
        raise BadInput(tr("Invalid value: {0}", name))
    return i


def office_settings_clean(c, oid, b, cur):
    """Validates a PUT body (partial) against the current settings -> the new full dict."""
    out = json.loads(json.dumps(cur))
    for k, v in b.items():
        if k not in SETTINGS_KEYS or k in ("logo", "terms"):  # the logo / the terms (2.113.2, #2253) are set by their upload routes
            continue
        if k == "pack":
            if not isinstance(v, str) or v.strip().upper() not in office_pack_codes():
                raise BadInput(tr("Invalid value: {0}", "pack"))
            out["pack"] = v.strip().upper()
        elif k == "company":
            if not isinstance(v, dict):
                raise BadInput(tr("Invalid value: {0}", "company"))
            co = out["company"]
            if "name" in v:
                co["name"] = ofx_name_clean(v["name"]) if isinstance(v.get("name"), str) else ""  # 2.99.0 D (#2188): up to three lines
            for f in ("lines", "contact_lines", "register_lines", "bank_lines"):
                if f in v:
                    co[f] = _lines(v[f], f)
        elif k == "color":
            v = (v or "").strip()
            if v and not COLOR_RE.match(v):
                raise BadInput(tr("Invalid value: {0}", "color"))
            out["color"] = v.lower()
        elif k == "lang":
            if v not in ("de", "en"):
                raise BadInput(tr("Invalid value: {0}", "lang"))
            out["lang"] = v
        elif k == "currency":
            if v not in ("EUR", "USD"):
                raise BadInput(tr("Invalid value: {0}", "currency"))
            out["currency"] = v
        elif k == "fx_usd":
            out["fx_usd"] = round(_num(v, "fx_usd", 0.0001, 1000), 4)
        elif k in ("offer_scheme", "invoice_scheme", "credit_scheme", "reminder_scheme", "delivery_scheme"):
            out[k] = office_scheme_clean(v, FE_SCHEME_NAMES.get(k), offer=k == "offer_scheme")
        elif k in ("skonto_pct", "skonto_days"):  # 2.120.0 A (#2087)
            from .abschlag import abs_settings_clean
            abs_settings_clean(k, v, out)
        elif k in ("payment_days", "reminder_deadline_days"):  # 2.38.0 (#1021, F1)
            out[k] = int(_num(v, k, 0, 365))
        elif k == "reminder_fee":
            out[k] = round(_num(v, k, 0, 1e6), 2)
        elif k == "einvoice_format":
            if v not in ("zugferd", "xrechnung"):
                raise BadInput(tr("Invalid value: {0}", k))
            out[k] = v
        elif k == "datev_email":
            v = (v or "").strip() if isinstance(v, str) else ""
            if v and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
                raise BadInput(tr("Invalid value: {0}", k))
            out[k] = v[:200]
        elif k == "industry_packs":  # 2.47.0 (#1216)
            from .sheet import dk_packs_clean
            out[k] = dk_packs_clean(v)
        elif k in ("datev_auto", "producing_on", "raw_on", "small_business", "agents_read", "accept_on", "portal_docs"):  # 2.120.0 B (#2088): portal_docs  # 2.114.4 B (#2270): accept_on  # 2.51.0 A (#1348): agents_read  # 2.40.0 (#1379): the two calculation switches
            out[k] = 1 if v in (1, True, "1", "true") else 0
        elif k in ("invoice_closing_de", "invoice_closing_en", "reminder_text_de", "reminder_text_en"):
            out[k] = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", v or "").strip()[:TEXT_MAX] if isinstance(v, str) else ""
        elif k == "parts_invoice_mode":  # 2.47.0 (#1215)
            if v not in ("full", "title", "summary"):
                raise BadInput(tr("Invalid value: {0}", k))
            out[k] = v
        elif k in ("parts_summary_title_de", "parts_summary_title_en"):
            out[k] = re.sub(r"[\x00-\x1f\x7f]", "", v or "").strip()[:300] if isinstance(v, str) else ""
        elif k == "datev_extf":  # 2.47.3 (#1460)
            from .datev import dx_settings_clean
            out[k] = dx_settings_clean(v, out.get(k) or {})
        elif k == "tax_reserve_pct":  # 2.90.0 A (#1921): whole percent 0..60
            out[k] = int(round(_num(v, k, 0, 60)))
        elif k == "vat_basis":  # 2.90.0 A (#1921)
            if v not in ("ist", "soll"):
                raise BadInput(tr("Invalid value: {0}", k))
            out[k] = v
        elif k == "offer_number_at":
            if v not in ("create", "finalize"):
                raise BadInput(tr("Invalid value: {0}", k))
            out[k] = v
        elif k == "offer_counter":  # 2.118.0 A (#2265)
            if v not in OFFER_COUNTERS:
                raise BadInput(tr("Invalid value: {0}", k))
            out[k] = v
        elif k == "prod_quotient":
            out["prod_quotient"] = _num(v, "prod_quotient", 0.1, 1000)
        elif k in ("share_rate", "share_factor"):  # 2.113.1 (#2251): empty = the pack's value
            out[k] = None if v in (None, "") else _num(v, k, *((0.01, 1e9) if k == "share_rate" else (0.01, 10)))
        elif k == "raw_factor":
            out["raw_factor"] = _num(v, "raw_factor", 0, 100)
        elif k == "producing_service_id":
            out["producing_service_id"] = _id_or_none(c, v, "office_services", oid, "producing_service_id")
        elif k == "producing_rate":
            out["producing_rate"] = _num(v, "producing_rate", 0, 1e9)
        elif k == "offer_valid_days":
            out["offer_valid_days"] = int(_num(v, "offer_valid_days", 0, 3650))
        elif k in ("intro_text_id", "closing_text_id"):
            if not isinstance(v, dict):
                raise BadInput(tr("Invalid value: {0}", k))
            for lg in ("de", "en"):
                if lg in v:
                    out[k][lg] = _id_or_none(c, v[lg], "office_texts", oid, k)
        elif k == "rights_default":
            if not isinstance(v, dict):
                raise BadInput(tr("Invalid value: {0}", k))
            for f in ("time_id", "territory_id", "media_id"):
                if f in v:
                    out[k][f] = _id_or_none(c, v[f], "office_texts", oid, k)
    return out


def fe_office_rules_migrate(c):
    """2.40.0 (#1379), once per database (kalmido_meta fe_office_rules): organisations that use producing or raw data
    (services, positions of documents, framework contracts with raw data) keep both switched on; the rest starts off.
    Decided only once, so switching off later stays off."""
    if c.execute("SELECT 1 FROM kalmido_meta WHERE key='fe_office_rules'").fetchone():
        return
    orgs = {r[0] for r in c.execute("SELECT org_id FROM office_settings UNION SELECT org_id FROM office_services UNION SELECT org_id FROM office_docs "
                                    "UNION SELECT org_id FROM office_contracts").fetchall()}
    for oid in sorted(orgs):
        prod = c.execute("SELECT 1 FROM office_services WHERE org_id=? AND producing=1 UNION ALL SELECT 1 FROM office_doc_items i JOIN office_docs d "
                         "ON d.id=i.doc_id WHERE d.org_id=? AND i.producing=1 LIMIT 1", (oid, oid)).fetchone()
        raw = c.execute("SELECT 1 FROM office_services WHERE org_id=? AND raw_fee=1 UNION ALL SELECT 1 FROM office_doc_items i JOIN office_docs d "
                        "ON d.id=i.doc_id WHERE d.org_id=? AND i.raw_fee=1 AND d.raw_mode!='none' UNION ALL SELECT 1 FROM office_contracts "
                        "WHERE org_id=? AND raw_included=1 LIMIT 1", (oid, oid, oid)).fetchone()
        r = c.execute("SELECT data FROM office_settings WHERE org_id=?", (oid,)).fetchone()
        try:
            d = json.loads(r["data"]) if r and r["data"] else {}
        except ValueError:
            d = {}
        d.setdefault("producing_on", 1 if prod else 0)
        d.setdefault("raw_on", 1 if raw else 0)
        office_settings_save(c, oid, d)
    c.execute("INSERT INTO kalmido_meta(key,value) VALUES('fe_office_rules','1') ON CONFLICT(key) DO NOTHING")


def office_settings_save(c, oid, data):
    from ..core.orgcrypt import oc_json_store
    data = oc_json_store(c, oid, "office_settings", "data", data)  # 2.42.0 (#828): the company lines encrypted at rest
    c.execute("INSERT INTO office_settings(org_id, data, updated_at) VALUES(?,?,?) ON CONFLICT(org_id) DO UPDATE SET data=excluded.data, "
              "updated_at=excluded.updated_at", (oid, json.dumps(data, ensure_ascii=False), iso(now_utc())))


def office_logo_set(c, oid, name):
    """D's upload route stores the file and calls this with the file name ('' = none)."""
    cur = office_settings(c, oid)
    cur["logo"] = name or ""
    office_settings_save(c, oid, cur)


# ---------------------------------------------------------------- number scheme
# 2.40.0 (#1382): plain-language errors of a number scheme, with the name of the scheme
FE_SCHEME_NAMES = {"offer_scheme": N_("Quotation numbers"), "invoice_scheme": N_("Invoice numbers"), "credit_scheme": N_("Credit note numbers"),
                   "reminder_scheme": N_("Reminder numbers"), "delivery_scheme": N_("Delivery note numbers")}  # 2.120.0 D (#2089)


def office_scheme_clean(v, name=None, offer=True):
    def bad(msg, *a):
        m = tr(msg).replace("{0}", a[0]) if a else tr(msg)  # (no str.format: the texts name the building blocks in braces)
        raise BadInput(f"{tr(name)}: {m}" if name else m)
    if not isinstance(v, str) or not v.strip():
        bad(N_("The scheme is empty. Example: RE-{yyyy}-{seq:03}"))
    v = v.strip()[:80]
    if "{seq" not in v:
        bad(N_("The running number is missing: add {seq} (or {seq:03} for 001)"))
    if not offer and "{version}" in v:  # 2.118.0 A (#2265): invoices, credit notes and reminders keep one gapless counter
        bad(N_("{version} is only possible in quotation numbers: invoices, credit notes and reminders count without gaps"))
    rest = SCHEME_RE.sub("", v)
    if "{" in rest or "}" in rest:
        m = re.search(r"\{[^{}]*\}?", rest)
        if offer:  # 2.118.0 A (#2265): + {version}
            bad(N_("Unknown building block {0}. Possible: {yyyy} {yy} {seq} {seq:03} {project} {client} {date} {isodate} {initials} {version}"), m.group(0) if m else "{")
        bad(N_("Unknown building block {0}. Possible: {yyyy} {yy} {seq} {seq:03} {project} {client} {date} {isodate} {initials}"), m.group(0) if m else "{")
    if re.search(r"[\\/<>\"'&\x00-\x1f]", rest):  # 2.36.1 review: no markup characters in numbers
        bad(N_("These characters cannot be part of a number: \\ / < > \" ' &"))
    return v


def office_scheme_period(scheme, d=None):
    """The counter's period of a scheme: the year when it holds {yyyy}/{yy}, else '' (one counter for ever)."""
    d = d or date.today()
    return str(d.year) if ("{yyyy}" in scheme or "{yy}" in scheme) else ""


def office_number_format(scheme, seq, d=None, project="", client="", initials="", version=1):
    d = d or date.today()

    def rep(m):
        t = m.group(1)
        if t == "yyyy":
            return str(d.year)
        if t == "yy":
            return str(d.year)[2:]
        if t.startswith("seq"):
            width = int(m.group(2)) if m.group(2) else 0
            return str(seq).zfill(width)
        if t == "project":
            return _slug(project)
        if t == "client":
            return _slug(client)
        if t == "date":
            return d.strftime("%Y%m%d")
        if t == "isodate":  # 2.138.2 A (#2391): the date with hyphens, 2026-04-15
            return d.strftime("%Y-%m-%d")
        if t == "initials":
            return _slug(initials)
        if t == "version":  # 2.118.0 A (#2265)
            return str(version)
        return m.group(0)
    return SCHEME_RE.sub(rep, scheme)


def _slug(s):
    s = re.sub(r"[^\w\-]+", "-", (s or "").strip(), flags=re.UNICODE).strip("-")
    return s[:40]


def office_number_next(c, oid, kind, scheme, d=None, peek=False, start=0, **ctx):
    """Reserves (or peeks at) the next number of kind for organisation oid: counter per (org, kind, period).
    2.118.0 A (#2265): start = the value a counter row that does not exist yet starts from (onc_next)."""
    period = office_scheme_period(scheme, d)
    if peek:
        r = c.execute("SELECT last FROM office_numbers WHERE org_id=? AND kind=? AND period=?", (oid, kind, period)).fetchone()
        seq = (r["last"] if r else start) + 1
    else:  # one atomic statement: two parallel requests never get the same counter value
        seq = c.execute("INSERT INTO office_numbers(org_id, kind, period, last) VALUES(?,?,?,?) ON CONFLICT(org_id, kind, period) "
                        "DO UPDATE SET last=office_numbers.last+1 RETURNING last", (oid, kind, period, start + 1)).fetchone()[0]
    return office_number_format(scheme, seq, d, **ctx), seq


# 2.118.0 A (#2265): the quotation counter per organisation (as before), client or project. The scope sits in the
# counter's kind (no migration): "offer" (organisation), "offer:c<client id>", "offer:n<recipient name>" (no client),
# "offer:p<list id>", "offer:t<project title>" (no list). Invoices, credit notes and reminders keep one counter.
OFFER_COUNTERS = ("org", "client", "project")


def onc_key(s, r):
    """The counter kind of quotation row r under settings s; '' = its client / project is not known yet."""
    mode = s.get("offer_counter") or "org"
    if mode == "client":
        if r["client_id"]:
            return f"offer:c{int(r['client_id'])}"
        try:
            rec = json.loads(r["recipient"] or "{}")
        except ValueError:
            rec = {}
        name = _slug(rec.get("name") if isinstance(rec, dict) and isinstance(rec.get("name"), str) else "").lower()
        return f"offer:n{name}" if name else ""
    if mode == "project":
        if r["list_id"]:
            return f"offer:p{int(r['list_id'])}"
        t = _slug(r["project_title"] or "").lower()
        return f"offer:t{t}" if t else ""
    return "offer"


def onc_ready(s, r):
    """False while a quotation counted per client / project has neither yet (it gets its number once it has one, at the
    latest when finalised: then from the organisation's counter)."""
    return r["kind"] != "offer" or (s.get("offer_counter") or "org") == "org" or bool(onc_key(s, r))


def onc_parse(scheme, num):
    """(seq, version) number num carries under scheme; None each when it does not follow the scheme / has no such block."""
    pat, pos, names = "", 0, []
    for m in SCHEME_RE.finditer(scheme):
        pat += re.escape(scheme[pos:m.start()])
        t = m.group(1)
        if t.startswith("seq") or t == "version":
            pat += r"(\d+)"
            names.append("version" if t == "version" else "seq")
        else:
            pat += {"yyyy": r"\d{4}", "yy": r"\d{2}", "date": r"\d{8}", "isodate": r"\d{4}-\d{2}-\d{2}"}.get(t, r".+?")
        pos = m.end()
    pat += re.escape(scheme[pos:])
    m = re.fullmatch(pat, num or "")
    if not m:
        return None, None
    got = {}
    for n, v in zip(names, m.groups()):
        got.setdefault(n, int(v))
    return got.get("seq"), got.get("version")


def onc_start(c, oid, s, r, key, scheme, d=None):
    """The highest running number the organisation's quotations of counter key (and the period of date d) already carry
    under scheme: a new client / project counter continues from it (existing numbers stay as they are)."""
    period = office_scheme_period(scheme, d)
    high = 0
    for x in c.execute("SELECT id, kind, number, date, client_id, list_id, project_title, recipient FROM office_docs "
                       "WHERE org_id=? AND kind='offer' AND number<>'' AND id<>?", (oid, r["id"])).fetchall():
        if (period and (x["date"] or "")[:4] != period) or onc_key(s, x) != key:
            continue
        seq = onc_parse(scheme, x["number"])[0]
        if seq and seq > high:
            high = seq
    return high


def onc_next(c, oid, s, r, scheme, d=None, peek=False, **ctx):
    """office_number_next for document row r: a quotation counts per organisation, client or project (settings s)."""
    if r["kind"] != "offer":
        return office_number_next(c, oid, r["kind"], scheme, d, peek, **ctx)
    key = onc_key(s, r) or "offer"
    start = 0
    if key != "offer" and not c.execute("SELECT 1 FROM office_numbers WHERE org_id=? AND kind=? AND period=?",
                                        (oid, key, office_scheme_period(scheme, d))).fetchone():
        start = onc_start(c, oid, s, r, key, scheme, d)
    return office_number_next(c, oid, key, scheme, d, peek, start=start, **ctx)


def onc_version(c, oid, r, scheme, ctx_of):
    """(version, number) of quotation r in its chain of duplicates (version_of, 2.88.0 #1915) when scheme holds {version}:
    version = the highest of the chain + 1 (the first one is 1); number = the first quotation's number with only the
    version changed (its running number stays, the counter does not move) or None (no chain / its running number cannot
    be read under today's scheme: the caller takes the next number). ctx_of(row) -> project / client / initials."""
    if r["kind"] != "offer" or "{version}" not in scheme or not r["version_of"]:
        return 1, None
    from .legacyimport import fi_number_taken
    root = r["version_of"]
    rows = c.execute("SELECT id, number, date, created_by, project_title, recipient, client_id FROM office_docs WHERE org_id=? "
                     "AND kind='offer' AND (id=? OR version_of=?) ORDER BY id", (oid, root, root)).fetchall()
    high, first = 0, None
    for i, x in enumerate(rows):
        if x["id"] == r["id"]:
            continue
        if x["id"] == root:
            first = x
        v = onc_parse(scheme, x["number"])[1] if x["number"] else None
        high = max(high, v or (1 if x["id"] == root else i + 1))  # an older number without the block: its place in the chain
    ver = high + 1
    seq = onc_parse(scheme, first["number"])[0] if first is not None and first["number"] else None
    if seq is None:
        return ver, None
    d = date.fromisoformat(first["date"]) if first["date"] else date.today()
    for _ in range(50):
        num = office_number_format(scheme, seq, d, version=ver, **ctx_of(first))
        if not c.execute("SELECT 1 FROM office_docs WHERE org_id=? AND number=? AND id!=?", (oid, num, r["id"])).fetchone() \
                and not fi_number_taken(c, oid, num):
            return ver, num
        ver += 1
    return ver, None


def onc_preview(c, oid, s, scheme, counter=None, **ctx):
    """The next quotation number shown on the settings page: per client / project an example one starts at 1."""
    if (counter or s.get("offer_counter") or "org") != "org":
        return office_number_format(scheme, 1, **ctx)
    return office_number_next(c, oid, "offer", scheme, peek=True, **ctx)[0]


# ---------------------------------------------------------------- master data (generic CRUD per table)
# column -> (type, required, max/choices). type: str | num | int01 | json | choice | fk
MD = {
    "services": {"table": "office_services", "order": "sort, lower(category), lower(name_de), id", "label": "name_de",
                 "cols": {"name_de": ("str", True, NAME_MAX), "name_en": ("str", False, NAME_MAX), "category": ("str", False, 80), "sort": ("num", False, None),
                          "unit": ("choice", False, UNITS), "daily_rate": ("num0", False, None), "hourly_rate": ("num0", False, None),
                          "raw_fee": ("int01", False, None), "producing": ("int01", False, None), "intext": ("choice", False, INTEXT),
                          "role": ("str", False, 80), "tax": ("choice", False, TAXES), "archived": ("int01", False, None),
                          "role_id": ("role", False, "freelancer")}},  # 2.47.0 (#1649): the freelancer role (purchase price)
    # 2.92.0 B (#1931): purchase, receipt, useful life, new / current value and the policy (assets.py); admins only, the
    # money columns and the serial number encrypted at rest ("crypt": the orgcrypt FIELDS of the table)
    "equipment": {"table": "office_equipment", "order": "lower(category), lower(name), id", "label": "name", "crypt": "office_equipment",
                  "admin_cols": ("purchase_date", "purchase_net", "serial_no", "vendor", "receipt_node_id", "life_months", "new_value",
                                 "current_value", "agreement_id"),
                  "cols": {"name": ("str", True, NAME_MAX), "name_en": ("str", False, NAME_MAX), "category": ("str", False, 80),  # 2.45.1 (#1556): name_en
                           "daily_rate": ("num0", False, None), "archived": ("int01", False, None),
                           "purchase_date": ("date", False, None), "purchase_net": ("money", False, None), "serial_no": ("str", False, 120),
                           "vendor": ("str", False, 120), "receipt_node_id": ("receipt", False, None), "life_months": ("months", False, None),
                           "new_value": ("money", False, None), "current_value": ("money", False, None), "agreement_id": ("agreement", False, None)}},
    "sets": {"table": "office_sets", "order": "lower(name), id", "label": "name",
             "cols": {"name": ("str", True, NAME_MAX), "discount_pct": ("num", False, None), "items": ("items", False, None),
                      "archived": ("int01", False, None)}},
    "texts": {"table": "office_texts", "order": "kind, sort, id", "label": "key",
              "cols": {"kind": ("choice", True, TEXT_KINDS), "key": ("str", False, 80), "text_de": ("str", False, TEXT_MAX),
                       "text_en": ("str", False, TEXT_MAX), "sort": ("num", False, None), "archived": ("int01", False, None)}},
    "contracts": {"table": "office_contracts", "order": "lower(name), id", "label": "name",
                  "cols": {"name": ("str", True, NAME_MAX), "client_id": ("fk", False, "clients"), "date": ("date", False, None),
                           "raw_included": ("int01", False, None), "rights_time_id": ("fk", False, "office_texts"),
                           "rights_territory_id": ("fk", False, "office_texts"), "rights_media_id": ("fk", False, "office_texts"),
                           "rights_note_de": ("str", False, TEXT_MAX), "rights_note_en": ("str", False, TEXT_MAX),
                           "closing_de": ("str", False, TEXT_MAX), "closing_en": ("str", False, TEXT_MAX), "rates": ("rates", False, None),
                           "note": ("str", False, TEXT_MAX), "archived": ("int01", False, None)}},
    # 2.47.0 (#1649): the two masters of office_roles (one table, kind fixed per master). cost_day / cost_hour = the
    # purchase price, kept in the encrypted JSON column costs; admin_cols never reach members (sr_public)
    "roles": {"table": "office_roles", "kind": "freelancer", "order": "sort, lower(name_de), id", "label": "name_de",
              "admin_cols": ("cost_day", "cost_hour"),
              "cols": {"name_de": ("str", True, NAME_MAX), "name_en": ("str", False, NAME_MAX), "cost_day": ("cost", False, None),
                       "cost_hour": ("cost", False, None), "sort": ("num", False, None), "archived": ("int01", False, None)}},
    "crew": {"table": "office_roles", "kind": "crew", "order": "sort, lower(name_de), id", "label": "name_de", "admin_cols": ("markup_pct",),
             "cols": {"name_de": ("str", True, NAME_MAX), "name_en": ("str", False, NAME_MAX), "rate_day": ("num0", False, None),
                      "intext": ("choice", False, CREW_INTEXT), "markup_pct": ("num0", False, None), "sort": ("num", False, None),
                      "archived": ("int01", False, None)}},
}
MD_KINDS = tuple(MD)
SR_COSTS = {"cost_day": "day", "cost_hour": "hour"}  # 2.47.0 (#1649): field -> key in office_roles.costs
JSON_COLS = {"items", "rates"}


def _row_dict(kind, r, c=None, oid=None):
    if c is not None and kind == "contracts":  # 2.42.0 (#828): the special rates are encrypted at rest
        from ..core.orgcrypt import oc_dec_fields
        r = oc_dec_fields(c, oid, "office_contracts", r)
    if c is not None and MD.get(kind, {}).get("crypt"):  # 2.92.0 B (#1931): the equipment's prices / values
        from ..core.orgcrypt import oc_dec_fields
        r = oc_dec_fields(c, oid, MD[kind]["crypt"], r)
    if c is not None and MD.get(kind, {}).get("table") == "office_roles":  # 2.47.0 (#1649): costs -> cost_day / cost_hour
        from ..core.orgcrypt import oc_dec_fields
        r = oc_dec_fields(c, oid, "office_roles", r)
    d = dict(r)
    if "costs" in d:
        try:
            j = json.loads(d.pop("costs") or "{}")
        except ValueError:
            j = {}
        j = j if isinstance(j, dict) else {}
        if kind == "roles":
            for f, k in SR_COSTS.items():
                d[f] = j.get(k)
    if kind == "roles":  # the crew's columns are not part of a freelancer role
        for k in ("rate_day", "intext", "markup_pct"):
            d.pop(k, None)
    for k in ("items", "rates"):
        if k in d:
            try:
                d[k] = json.loads(d[k]) if d[k] else ([] if k == "items" else {})
            except ValueError:
                d[k] = [] if k == "items" else {}
    for k in ("raw_fee", "producing", "archived", "raw_included"):
        if k in d:
            d[k] = int(d[k] or 0)
    return d


def office_rows(c, oid, kind, archived=True, q=""):
    m = MD[kind]
    sql = f"SELECT * FROM {m['table']} WHERE org_id=?"
    args = [oid]
    if m.get("kind"):  # 2.47.0 (#1649): office_roles holds two masters
        sql += " AND kind=?"
        args.append(m["kind"])
    if not archived:
        sql += " AND archived=0"
    if q:
        like = f"%{like_escape(q.strip())}%"
        if kind == "services":
            sql += " AND (name_de ILIKE ? ESCAPE '\\' OR name_en ILIKE ? ESCAPE '\\' OR category ILIKE ? ESCAPE '\\')"
            args += [like, like, like]
        elif kind == "equipment":  # 2.45.1 (#1556): also the English name
            sql += " AND (name ILIKE ? ESCAPE '\\' OR name_en ILIKE ? ESCAPE '\\')"
            args += [like, like]
        elif kind in ("roles", "crew"):  # 2.47.0 (#1649)
            sql += " AND (name_de ILIKE ? ESCAPE '\\' OR name_en ILIKE ? ESCAPE '\\')"
            args += [like, like]
        elif kind == "texts":
            sql += " AND (key ILIKE ? ESCAPE '\\' OR text_de ILIKE ? ESCAPE '\\' OR text_en ILIKE ? ESCAPE '\\')"
            args += [like, like, like]
        else:
            sql += f" AND {m['label']} ILIKE ? ESCAPE '\\'"
            args.append(like)
    return [_row_dict(kind, r, c, oid) for r in c.execute(sql + f" ORDER BY {m['order']}", args)]


def office_row(c, oid, kind, rid):
    """One row of the organisation, or 404 (foreign organisation = 404, never 403)."""
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        raise Denied(404)
    r = c.execute(f"SELECT * FROM {MD[kind]['table']} WHERE id=? AND org_id=?", (rid, oid)).fetchone()
    if not r or (MD[kind].get("kind") and r["kind"] != MD[kind]["kind"]):  # 2.47.0 (#1649): a crew id is no freelancer role
        raise Denied(404)
    return _row_dict(kind, r, c, oid)


def _clean_col(c, oid, kind, k, v):
    typ, req, spec = MD[kind]["cols"][k]
    if typ == "str":
        if v is None:
            v = ""
        if not isinstance(v, str):
            raise BadInput(tr("Invalid value: {0}", k))
        v = v.strip()[:spec]
        if req and not v:
            raise BadInput(tr("Invalid value: {0}", k))
        return v
    if typ == "num":
        return _num(v, k, allow_none=not req) if v not in (None, "") else (None if not req else _num(v, k))
    if typ == "num0":
        return _num(v, k, 0, 1e9, allow_none=True)
    if typ == "int01":
        return 1 if v in (1, True, "1", "true", "on") else 0
    if typ == "choice":
        if v in (None, "") and not req:
            return spec[0] if k in ("unit", "tax") else ("extern" if k == "intext" else "")
        if v not in spec:
            raise BadInput(tr("Invalid value: {0}", k))
        return v
    if typ == "fk":
        if v in (None, "", 0, "0"):
            return None
        try:
            i = int(v)
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid value: {0}", k))
        if spec == "clients":
            if not c.execute(f"SELECT 1 FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (i,)).fetchone():
                raise BadInput(tr("Invalid value: {0}", k))
        elif not c.execute(f"SELECT 1 FROM {spec} WHERE id=? AND org_id=?", (i, oid)).fetchone():
            raise BadInput(tr("Invalid value: {0}", k))
        return i
    if typ == "cost":  # 2.47.0 (#1649): a purchase price (stored by _sr_costs)
        return _num(v, k, 0, 1e9, allow_none=True)
    if typ == "role":  # 2.47.0 (#1649): a role of this organisation and kind (archived: kept, it then has no price)
        if v in (None, "", 0, "0"):
            return None
        try:
            i = int(v)
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid value: {0}", k))
        if not c.execute("SELECT 1 FROM office_roles WHERE id=? AND org_id=? AND kind=?", (i, oid, spec)).fetchone():
            raise BadInput(tr("Invalid value: {0}", k))
        return i
    if typ == "money":  # 2.92.0 B (#1931): an amount kept as text "1234.50" ('' = none; encrypted by _md_crypt)
        if v in (None, ""):
            return ""
        from .calc import dstr
        return dstr(_num(v, k, 0, 1e9))
    if typ == "months":  # 2.92.0 B (#1931): a useful life in months (None = the suggestion)
        if v in (None, "", 0, "0"):
            return None
        return int(_num(v, k, 1, 600))
    if typ == "receipt":  # 2.92.0 B (#1931): a document of the office's document space
        from .assets import ast_receipt_check
        return ast_receipt_check(c, oid, v)
    if typ == "agreement":  # 2.92.0 B (#1931): a live contract of the office (#1925)
        if v in (None, "", 0, "0"):
            return None
        try:
            i = int(v)
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid value: {0}", k))
        from .assets import ast_agreement_ok
        if not ast_agreement_ok(c, oid, i):
            raise BadInput(tr("Invalid value: {0}", k))
        return i
    if typ == "date":
        if v in (None, ""):
            return ""
        if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            raise BadInput(tr("Invalid value: {0}", k))
        try:
            date.fromisoformat(v)
        except ValueError:
            raise BadInput(tr("Invalid value: {0}", k))
        return v
    if typ == "items":  # [{equipment_id, qty}]
        if v in (None, ""):
            return "[]"
        if not isinstance(v, list):
            raise BadInput(tr("Invalid value: {0}", k))
        out = []
        for it in v[:200]:
            if not isinstance(it, dict):
                raise BadInput(tr("Invalid value: {0}", k))
            try:
                eid = int(it.get("equipment_id"))
            except (TypeError, ValueError):
                raise BadInput(tr("Invalid value: {0}", k))
            if not c.execute("SELECT 1 FROM office_equipment WHERE id=? AND org_id=?", (eid, oid)).fetchone():
                raise BadInput(tr("Invalid value: {0}", k))
            out.append({"equipment_id": eid, "qty": _num(it.get("qty", 1), k, 0, 1e6)})
        return json.dumps(out)
    if typ == "rates":  # {service_id: rate}
        if v in (None, ""):
            return "{}"
        if not isinstance(v, dict):
            raise BadInput(tr("Invalid value: {0}", k))
        out = {}
        for sid, rate in list(v.items())[:500]:
            try:
                i = int(sid)
            except (TypeError, ValueError):
                raise BadInput(tr("Invalid value: {0}", k))
            if not c.execute("SELECT 1 FROM office_services WHERE id=? AND org_id=?", (i, oid)).fetchone():
                raise BadInput(tr("Invalid value: {0}", k))
            if rate in (None, ""):
                continue
            out[str(i)] = _num(rate, k, 0, 1e9)
        from ..core.orgcrypt import oc_enc_fields
        return oc_enc_fields(c, oid, "office_contracts", {"rates": json.dumps(out)})["rates"]  # 2.42.0 (#828)
    raise BadInput(tr("Invalid value: {0}", k))


def office_create(c, oid, kind, b):
    m = MD[kind]
    cols, vals = ["org_id"], [oid]
    for k, (typ, req, spec) in m["cols"].items():
        if k in b or req:
            cols.append(k)
            vals.append(_clean_col(c, oid, kind, k, b.get(k)))
    if m.get("kind"):  # 2.47.0 (#1649)
        _sr_costs(c, oid, cols, vals, {})
        cols.append("kind"), vals.append(m["kind"])
    _md_crypt(c, oid, kind, cols, vals)
    if kind == "texts" and not b.get("key"):
        cols.append("key"), vals.append("")
    ts = iso(now_utc())
    if "created_at" in _cols(c, m["table"]):
        cols += ["created_at", "updated_at"]
        vals += [ts, ts]
    cur_id = insert_id(c, f"INSERT INTO {m['table']}({','.join(cols)}) VALUES({','.join('?' * len(cols))})", vals)
    return office_row(c, oid, kind, cur_id)


def office_update(c, oid, kind, rid, b):
    m = MD[kind]
    r = office_row(c, oid, kind, rid)
    sets, vals = [], []
    for k, v in b.items():
        if k not in m["cols"]:
            continue
        if m["cols"][k][0] in ("agreement", "receipt") and v not in (None, "") and str(v) == str(r.get(k)):
            continue  # 2.92.0 B (#1931): an unchanged link stays even when its policy is archived by now
        sets.append(k)
        vals.append(_clean_col(c, oid, kind, k, v))
    if m.get("kind"):  # 2.47.0 (#1649)
        _sr_costs(c, oid, sets, vals, {f: r.get(f) for f in SR_COSTS})
    _md_crypt(c, oid, kind, sets, vals)
    sets = [f"{k}=?" for k in sets]
    if sets:
        if "updated_at" in _cols(c, m["table"]):
            sets.append("updated_at=?")
            vals.append(iso(now_utc()))
        vals += [r["id"], oid]
        c.execute(f"UPDATE {m['table']} SET {', '.join(sets)} WHERE id=? AND org_id=?", vals)
    return office_row(c, oid, kind, rid)


def _sr_costs(c, oid, cols, vals, cur):
    """2.47.0 (#1649): the cost fields of cols / vals (in place) -> one encrypted column costs {"day", "hour"}; cur = the
    row's current values (a partial update keeps the other one)."""
    if not any(f in cols for f in SR_COSTS):
        return
    j = {}
    for f, k in SR_COSTS.items():
        v = cur.get(f)
        if f in cols:
            i = cols.index(f)
            v = vals[i]
            del cols[i], vals[i]
        if v is not None:
            j[k] = v
    from ..core.orgcrypt import oc_enc_fields
    cols.append("costs")
    vals.append(oc_enc_fields(c, oid, "office_roles", {"costs": json.dumps(j)})["costs"])


def _md_crypt(c, oid, kind, cols, vals):
    """2.92.0 B (#1931): the protected columns of a master with "crypt" encrypted in place (orgcrypt FIELDS)."""
    t = MD[kind].get("crypt")
    if not t:
        return
    from ..core.orgcrypt import oc_enc_fields
    enc = oc_enc_fields(c, oid, t, dict(zip(cols, vals)))
    vals[:] = [enc[k] for k in cols]


def sr_public(kind, row, admin):
    """2.47.0 (#1649): a master data row for the person: members never get the purchase price / markup (admin_cols)."""
    if admin:
        return row
    return {k: v for k, v in row.items() if k not in MD.get(kind, {}).get("admin_cols", ())}


def sr_role_cost(c, oid, role_id, unit):
    """2.47.0 (#1649): the purchase price of freelancer role role_id of organisation oid for unit ('day' | 'hour') as a
    Decimal, or None (no role, archived, another kind / organisation, no price for that unit)."""
    from decimal import Decimal, InvalidOperation
    k = {"day": "day", "hour": "hour"}.get(unit)
    try:
        rid = int(role_id)
    except (TypeError, ValueError):
        return None
    if not k:
        return None
    r = c.execute("SELECT * FROM office_roles WHERE id=? AND org_id=? AND kind='freelancer' AND archived=0", (rid, oid)).fetchone()
    if not r:
        return None
    v = _row_dict("roles", r, c, oid).get("cost_" + k)
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return None


def office_in_use(c, kind, rid, oid):
    """True when documents or other master data of organisation oid refer to the row: then delete = archive.
    2.36.2 (#1146): every query is limited to the organisation."""
    if kind == "services":
        if c.execute("SELECT 1 FROM office_doc_items WHERE service_id=? AND org_id=? LIMIT 1", (rid, oid)).fetchone():
            return True
        # 2.42.0 (#828): the rates may be encrypted -> compared after decrypting (an organisation has few contracts)
        return any(str(rid) in (x.get("rates") or {}) for x in office_rows(c, oid, "contracts"))
    if kind == "equipment":
        return bool(c.execute("SELECT 1 FROM office_sets WHERE org_id=? AND items ILIKE ? LIMIT 1", (oid, f'%"equipment_id": {rid},%')).fetchone()
                    or c.execute("SELECT 1 FROM office_sets WHERE org_id=? AND items ILIKE ? LIMIT 1", (oid, f'%"equipment_id": {rid}}}%')).fetchone())
    if kind == "texts":
        if c.execute("SELECT 1 FROM office_contracts WHERE org_id=? AND (rights_time_id=? OR rights_territory_id=? OR rights_media_id=?) LIMIT 1",
                     (oid, rid, rid, rid)).fetchone():
            return True
        return False
    if kind == "contracts":
        return bool(c.execute("SELECT 1 FROM office_docs WHERE contract_id=? AND org_id=? LIMIT 1", (rid, oid)).fetchone())
    if kind == "roles":  # 2.47.0 (#1649): a role services point to is archived (the services then have none)
        return bool(c.execute("SELECT 1 FROM office_services WHERE role_id=? AND org_id=? LIMIT 1", (rid, oid)).fetchone())
    return False


def office_delete(c, oid, kind, rid):
    """Deletes the row; when it is in use (documents, contracts, sets) it is archived instead. -> 'deleted' | 'archived'"""
    m = MD[kind]
    r = office_row(c, oid, kind, rid)
    if office_in_use(c, kind, r["id"], oid):
        c.execute(f"UPDATE {m['table']} SET archived=1 WHERE id=? AND org_id=?", (r["id"], oid))
        return "archived"
    c.execute(f"DELETE FROM {m['table']} WHERE id=? AND org_id=?", (r["id"], oid))
    if kind == "contracts":  # 2.117.0 B (#2285): its PDF files go into the trash (purged after DMA_PURGE_DAYS)
        from .contractfiles import dma_trash_contract
        dma_trash_contract(c, oid, r["id"])
    if kind == "services":
        s = office_settings(c, oid)
        if s.get("producing_service_id") == r["id"]:
            s["producing_service_id"] = None
            office_settings_save(c, oid, s)
    if kind == "texts":
        s = office_settings(c, oid)
        changed = False
        for k in ("intro_text_id", "closing_text_id"):
            for lg in ("de", "en"):
                if s[k].get(lg) == r["id"]:
                    s[k][lg] = None
                    changed = True
        for f in ("time_id", "territory_id", "media_id"):
            if s["rights_default"].get(f) == r["id"]:
                s["rights_default"][f] = None
                changed = True
        if changed:
            office_settings_save(c, oid, s)
    return "deleted"


_COLS = {}


def _cols(c, table):
    if table not in _COLS:
        _COLS[table] = table_columns(c, table)
    return _COLS[table]


# ---------------------------------------------------------------- import / export (JSON, master data only)
EXPORT_KINDS = ("roles", "crew", "services", "equipment", "sets", "texts", "contracts")  # 2.47.0 (#1649): roles before services (role_id)


def office_export(c, oid, admin=True):
    """The master data + settings of the organisation as one JSON-able dict (no documents, no logo file).
    2.47.0 (#1649): admin=False leaves out the purchase prices / markups of the roles (sr_public)."""
    s = office_settings(c, oid)
    out = {"kalmido_office": 1, "exported_at": iso(now_utc()), "settings": s}
    for k in EXPORT_KINDS:
        rows = [sr_public(k, r, admin) for r in office_rows(c, oid, k)]
        for r in rows:
            r.pop("org_id", None)
            if k in ("roles", "crew"):
                r.pop("kind", None)
        out[k] = rows
    return out


def office_import(c, oid, d, overwrite=False):
    """Additive import of an export (or a hand-made file of the same shape): rows are matched by their label (services:
    name_de, equipment/sets/contracts: name, texts: kind + key); existing ones are left alone unless overwrite. Ids inside
    the file (sets.items, contracts.rates / rights ids, settings' text ids) are mapped to the new ids; 2.36.2 (#1146): an id
    that maps to no row of the file is left empty (never taken over as it is) and listed in counts["unmapped"]."""
    if not isinstance(d, dict):
        raise BadInput(tr("Invalid data"))
    counts = {k: {"added": 0, "updated": 0, "skipped": 0} for k in EXPORT_KINDS}
    idmap = {k: {} for k in EXPORT_KINDS}
    unmapped = []

    def mapped(kind, v, where, field):
        """The new id of the file's id v of kind, or None (reported)."""
        if v in (None, "", 0, "0"):
            return None
        n = idmap[kind].get(_i(v))
        if n is None:
            unmapped.append({"in": where[0], "name": str(where[1] or "")[:NAME_MAX], "field": field, "id": _i(v)})
        return n

    def key_of(kind, r):
        if kind == "texts":
            return (r.get("kind") or "", (r.get("key") or "").strip().lower(), (r.get("text_de") or "").strip().lower() if not (r.get("key") or "").strip() else "")
        return (MD[kind]["label"], (r.get(MD[kind]["label"]) or "").strip().lower())

    for kind in EXPORT_KINDS:
        rows = d.get(kind)
        if rows is None:
            continue
        if not isinstance(rows, list):
            raise BadInput(tr("Invalid value: {0}", kind))
        existing = {key_of(kind, r): r for r in office_rows(c, oid, kind)}
        for src in rows[:5000]:
            if not isinstance(src, dict):
                raise BadInput(tr("Invalid value: {0}", kind))
            b = {k: v for k, v in src.items() if k in MD[kind]["cols"]}
            old_id = src.get("id")
            # remap foreign ids of earlier kinds
            where = (kind, b.get(MD[kind]["label"]))
            if kind == "sets" and isinstance(b.get("items"), list):
                its = []
                for it in b["items"]:
                    if isinstance(it, dict):
                        eid = mapped("equipment", it.get("equipment_id"), where, "items")
                        if eid is not None:
                            its.append({"equipment_id": eid, "qty": it.get("qty", 1)})
                b["items"] = its
            if kind == "contracts":
                if isinstance(b.get("rates"), dict):
                    rates = {}
                    for k_, v in b["rates"].items():
                        sid = mapped("services", k_, where, "rates")
                        if sid is not None:
                            rates[str(sid)] = v
                    b["rates"] = rates
                for f in ("rights_time_id", "rights_territory_id", "rights_media_id"):
                    if b.get(f) is not None:
                        b[f] = mapped("texts", b[f], where, f)
                b.pop("client_id", None)  # clients are not part of the master data file
            if kind == "equipment":  # 2.92.0 B (#1931): receipt and policy are ids of the source office, never taken over
                b.pop("receipt_node_id", None), b.pop("agreement_id", None)
            if kind == "services" and b.get("role_id") is not None:  # 2.47.0 (#1649)
                b["role_id"] = mapped("roles", b["role_id"], where, "role_id")
            k = key_of(kind, b)
            cur = existing.get(k)
            if cur and not overwrite:
                counts[kind]["skipped"] += 1
                if old_id is not None:
                    idmap[kind][_i(old_id)] = cur["id"]
                continue
            if cur:
                r = office_update(c, oid, kind, cur["id"], b)
                counts[kind]["updated"] += 1
            else:
                r = office_create(c, oid, kind, b)
                existing[k] = r
                counts[kind]["added"] += 1
            if old_id is not None:
                idmap[kind][_i(old_id)] = r["id"]
    st = d.get("settings")
    if isinstance(st, dict):
        cur = office_settings(c, oid)
        b = {k: v for k, v in st.items() if k in SETTINGS_KEYS and k not in ("logo", "terms")}  # 2.113.2 (#2253): no terms files
        where = ("settings", "")
        if "producing_service_id" in b and b["producing_service_id"] is not None:
            b["producing_service_id"] = mapped("services", b["producing_service_id"], where, "producing_service_id")
        for k in ("intro_text_id", "closing_text_id"):
            if isinstance(b.get(k), dict):
                b[k] = {lg: mapped("texts", v, where, k) for lg, v in b[k].items() if lg in ("de", "en")}
        if isinstance(b.get("rights_default"), dict):
            b["rights_default"] = {f: mapped("texts", v, where, "rights_default") for f, v in b["rights_default"].items()
                                   if f in ("time_id", "territory_id", "media_id")}
        if overwrite or not c.execute("SELECT 1 FROM office_settings WHERE org_id=?", (oid,)).fetchone():
            office_settings_save(c, oid, office_settings_clean(c, oid, b, cur))
            counts["settings"] = "updated"
        else:
            counts["settings"] = "skipped"
    counts["unmapped"] = unmapped[:200]
    return counts


def _i(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- starter texts from the pack (first use of an organisation)
def office_seed_texts(c, oid):
    """Copies the pack's rights catalogue + intro / closing into office_texts when the organisation has none yet."""
    if c.execute("SELECT 1 FROM office_texts WHERE org_id=? LIMIT 1", (oid,)).fetchone():
        return 0
    pack = office_pack(office_settings(c, oid)["pack"]) or office_pack("DE")
    if not pack:
        return 0
    n = 0
    tx = pack["texts"]
    for kind in ("rights_time", "rights_territory", "rights_media"):
        for i, t in enumerate(tx.get(kind) or []):
            office_create(c, oid, "texts", {"kind": kind, "key": t["key"], "text_de": t["de"], "text_en": t["en"], "sort": i})
            n += 1
    for kind in ("intro", "closing"):
        t = tx.get(kind)
        if t:
            office_create(c, oid, "texts", {"kind": kind, "key": "default", "text_de": t["de"], "text_en": t["en"], "sort": 0})
            n += 1
    if tx.get("rights_note"):
        office_create(c, oid, "texts", {"kind": "note", "key": "rights_note", "text_de": tx["rights_note"]["de"], "text_en": tx["rights_note"]["en"], "sort": 0})
        n += 1
    return n
