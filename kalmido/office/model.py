"""Office & finance (2.36.1, #1021, module "office"): the gate, the organisation one works in, the module's settings and
the master data of an organisation (services, equipment + sets, text blocks, framework contracts, number counters).

Everything belongs to an organisation (tenant): every table has org_id; every query filters by it. The module exists only
in the business area: the person needs the feature "office" AND a membership in an organisation. Agent tokens and kid
accounts never get in (403 before any data is read). Org admins manage settings and master data; org members read the
master data and write documents (see docs.py); foreign ids are 404, never 403 with content."""
import json
import re
from datetime import date

from flask import g

from ..core.i18n import N_, tr
from ..core.db import db, iso, now_utc, usettings
from ..accounts.session import me
from ..core.access import Denied
from ..personal.timetrack import BadInput
from .packs import office_pack, office_pack_codes

OFFICE_FEAT = "office"
OFFICE_NO_ORG = N_("Office & finance belongs to an organisation: choose your organisation's workspace at the top")
OFFICE_ADMIN_ONLY = N_("Only an admin of this organisation can do this")
OFFICE_OFF = N_("Office & finance is turned off in your settings")
UNITS = ("day", "hour", "piece", "minute", "flat")
TAXES = ("standard", "reduced", "exempt")
INTEXT = ("intern", "extern")
TEXT_KINDS = ("rights_time", "rights_territory", "rights_media", "intro", "closing", "note", "block", "raw_note")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
SCHEME_RE = re.compile(r"\{(yyyy|yy|seq(?::0?(\d{1,2}))?|project|client|date|initials)\}")
NAME_MAX = 200
TEXT_MAX = 8000

# ---- settings (office_settings.data), defaults filled from the country pack
SETTINGS_DEFAULTS = {"pack": "DE", "company": {"name": "", "lines": [], "contact_lines": [], "register_lines": [], "bank_lines": []},
                     "logo": "", "color": "", "lang": "de", "currency": "EUR", "fx_usd": 1.09, "offer_scheme": "KVA-{yyyy}-{seq:03}",
                     "prod_quotient": 3, "raw_factor": 0.25, "producing_service_id": None, "producing_rate": 600,
                     "offer_valid_days": 30, "intro_text_id": {"de": None, "en": None}, "closing_text_id": {"de": None, "en": None},
                     "rights_default": {"time_id": None, "territory_id": None, "media_id": None}}
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
    """The organisation uid works in: the one of the setting "workspace" (org:<id>), else the person's only organisation.
    None of them -> 400 with a readable text. admin=True also requires org_role admin (403)."""
    from ..accounts.orgs import org_role, user_orgs
    orgs = user_orgs(c, uid)
    ws = (usettings(c, uid).get("workspace") or "").strip()
    oid = None
    m = re.fullmatch(r"org:(\d{1,9})", ws)
    if m and int(m.group(1)) in orgs:
        oid = int(m.group(1))
    elif len(orgs) == 1:
        oid = orgs[0]
    if not oid:
        raise BadInput(tr(OFFICE_NO_ORG))
    role = org_role(c, uid, oid)
    if not role:
        raise BadInput(tr(OFFICE_NO_ORG))
    if admin and role != "admin":
        raise Denied(403, tr(OFFICE_ADMIN_ONLY))
    return oid


def office_role(c, uid, oid):
    from ..accounts.orgs import org_role
    return org_role(c, uid, oid)


# ---------------------------------------------------------------- settings
def office_settings(c, oid):
    """The module's settings of organisation oid (dict with every key, defaults from the country pack)."""
    r = c.execute("SELECT data FROM office_settings WHERE org_id=?", (oid,)).fetchone()
    try:
        d = json.loads(r["data"]) if r and r["data"] else {}
    except ValueError:
        d = {}
    out = json.loads(json.dumps(SETTINGS_DEFAULTS))
    for k in SETTINGS_KEYS:
        if k in d and d[k] is not None:
            if isinstance(out[k], dict) and isinstance(d[k], dict):
                out[k].update(d[k])
            else:
                out[k] = d[k]
    pack = office_pack(out["pack"]) or office_pack("DE")
    if pack:
        out["currency"] = out["currency"] or pack["currency"]
        if not out.get("offer_scheme"):
            out["offer_scheme"] = (pack.get("numbering") or {}).get("offer") or SETTINGS_DEFAULTS["offer_scheme"]
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
        if k not in SETTINGS_KEYS or k == "logo":  # the logo is set by the upload route
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
                co["name"] = (v.get("name") or "").strip()[:NAME_MAX] if isinstance(v.get("name"), str) else ""
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
        elif k == "offer_scheme":
            out["offer_scheme"] = office_scheme_clean(v)
        elif k == "prod_quotient":
            out["prod_quotient"] = _num(v, "prod_quotient", 0.1, 1000)
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


def office_settings_save(c, oid, data):
    c.execute("INSERT INTO office_settings(org_id, data, updated_at) VALUES(?,?,?) ON CONFLICT(org_id) DO UPDATE SET data=excluded.data, "
              "updated_at=excluded.updated_at", (oid, json.dumps(data, ensure_ascii=False), iso(now_utc())))


def office_logo_set(c, oid, name):
    """D's upload route stores the file and calls this with the file name ('' = none)."""
    cur = office_settings(c, oid)
    cur["logo"] = name or ""
    office_settings_save(c, oid, cur)


# ---------------------------------------------------------------- number scheme
def office_scheme_clean(v):
    if not isinstance(v, str) or not v.strip():
        raise BadInput(tr("Invalid value: {0}", "offer_scheme"))
    v = v.strip()[:80]
    if "{seq" not in v:
        raise BadInput(tr("The number scheme needs a {seq} counter"))
    rest = SCHEME_RE.sub("", v)
    if "{" in rest or "}" in rest:
        raise BadInput(tr("Invalid value: {0}", "offer_scheme"))
    if re.search(r"[\\/<>\"'&\x00-\x1f]", rest):  # 2.36.1 review: no markup characters in numbers
        raise BadInput(tr("Invalid value: {0}", "offer_scheme"))
    return v


def office_scheme_period(scheme, d=None):
    """The counter's period of a scheme: the year when it holds {yyyy}/{yy}, else '' (one counter for ever)."""
    d = d or date.today()
    return str(d.year) if ("{yyyy}" in scheme or "{yy}" in scheme) else ""


def office_number_format(scheme, seq, d=None, project="", client="", initials=""):
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
        if t == "initials":
            return _slug(initials)
        return m.group(0)
    return SCHEME_RE.sub(rep, scheme)


def _slug(s):
    s = re.sub(r"[^\w\-]+", "-", (s or "").strip(), flags=re.UNICODE).strip("-")
    return s[:40]


def office_number_next(c, oid, kind, scheme, d=None, peek=False, **ctx):
    """Reserves (or peeks at) the next number of kind for organisation oid: counter per (org, kind, period)."""
    period = office_scheme_period(scheme, d)
    if peek:
        r = c.execute("SELECT last FROM office_numbers WHERE org_id=? AND kind=? AND period=?", (oid, kind, period)).fetchone()
        seq = (r["last"] if r else 0) + 1
    else:  # one atomic statement: two parallel requests never get the same counter value
        seq = c.execute("INSERT INTO office_numbers(org_id, kind, period, last) VALUES(?,?,?,1) ON CONFLICT(org_id, kind, period) "
                        "DO UPDATE SET last=last+1 RETURNING last", (oid, kind, period)).fetchone()[0]
    return office_number_format(scheme, seq, d, **ctx), seq


# ---------------------------------------------------------------- master data (generic CRUD per table)
# column -> (type, required, max/choices). type: str | num | int01 | json | choice | fk
MD = {
    "services": {"table": "office_services", "order": "sort, category COLLATE NOCASE, name_de COLLATE NOCASE, id", "label": "name_de",
                 "cols": {"name_de": ("str", True, NAME_MAX), "name_en": ("str", False, NAME_MAX), "category": ("str", False, 80), "sort": ("num", False, None),
                          "unit": ("choice", False, UNITS), "daily_rate": ("num0", False, None), "hourly_rate": ("num0", False, None),
                          "raw_fee": ("int01", False, None), "producing": ("int01", False, None), "intext": ("choice", False, INTEXT),
                          "role": ("str", False, 80), "tax": ("choice", False, TAXES), "archived": ("int01", False, None)}},
    "equipment": {"table": "office_equipment", "order": "category COLLATE NOCASE, name COLLATE NOCASE, id", "label": "name",
                  "cols": {"name": ("str", True, NAME_MAX), "category": ("str", False, 80), "daily_rate": ("num0", False, None),
                           "archived": ("int01", False, None)}},
    "sets": {"table": "office_sets", "order": "name COLLATE NOCASE, id", "label": "name",
             "cols": {"name": ("str", True, NAME_MAX), "discount_pct": ("num", False, None), "items": ("items", False, None),
                      "archived": ("int01", False, None)}},
    "texts": {"table": "office_texts", "order": "kind, sort, id", "label": "key",
              "cols": {"kind": ("choice", True, TEXT_KINDS), "key": ("str", False, 80), "text_de": ("str", False, TEXT_MAX),
                       "text_en": ("str", False, TEXT_MAX), "sort": ("num", False, None), "archived": ("int01", False, None)}},
    "contracts": {"table": "office_contracts", "order": "name COLLATE NOCASE, id", "label": "name",
                  "cols": {"name": ("str", True, NAME_MAX), "client_id": ("fk", False, "clients"), "date": ("date", False, None),
                           "raw_included": ("int01", False, None), "rights_time_id": ("fk", False, "office_texts"),
                           "rights_territory_id": ("fk", False, "office_texts"), "rights_media_id": ("fk", False, "office_texts"),
                           "rights_note_de": ("str", False, TEXT_MAX), "rights_note_en": ("str", False, TEXT_MAX),
                           "closing_de": ("str", False, TEXT_MAX), "closing_en": ("str", False, TEXT_MAX), "rates": ("rates", False, None),
                           "note": ("str", False, TEXT_MAX), "archived": ("int01", False, None)}},
}
MD_KINDS = tuple(MD)
JSON_COLS = {"items", "rates"}


def _row_dict(kind, r):
    d = dict(r)
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
    if not archived:
        sql += " AND archived=0"
    if q:
        like = f"%{q.strip()}%"
        if kind == "services":
            sql += " AND (name_de LIKE ? OR name_en LIKE ? OR category LIKE ?)"
            args += [like, like, like]
        elif kind == "texts":
            sql += " AND (key LIKE ? OR text_de LIKE ? OR text_en LIKE ?)"
            args += [like, like, like]
        else:
            sql += f" AND {m['label']} LIKE ?"
            args.append(like)
    return [_row_dict(kind, r) for r in c.execute(sql + f" ORDER BY {m['order']}", args)]


def office_row(c, oid, kind, rid):
    """One row of the organisation, or 404 (foreign organisation = 404, never 403)."""
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        raise Denied(404)
    r = c.execute(f"SELECT * FROM {MD[kind]['table']} WHERE id=? AND org_id=?", (rid, oid)).fetchone()
    if not r:
        raise Denied(404)
    return _row_dict(kind, r)


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
            if not c.execute("SELECT 1 FROM clients WHERE id=? AND org_id=?", (i, oid)).fetchone():
                raise BadInput(tr("Invalid value: {0}", k))
        elif not c.execute(f"SELECT 1 FROM {spec} WHERE id=? AND org_id=?", (i, oid)).fetchone():
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
        return json.dumps(out)
    raise BadInput(tr("Invalid value: {0}", k))


def office_create(c, oid, kind, b):
    m = MD[kind]
    cols, vals = ["org_id"], [oid]
    for k, (typ, req, spec) in m["cols"].items():
        if k in b or req:
            cols.append(k)
            vals.append(_clean_col(c, oid, kind, k, b.get(k)))
    if kind == "texts" and not b.get("key"):
        cols.append("key"), vals.append("")
    ts = iso(now_utc())
    if "created_at" in _cols(c, m["table"]):
        cols += ["created_at", "updated_at"]
        vals += [ts, ts]
    cur = c.execute(f"INSERT INTO {m['table']}({','.join(cols)}) VALUES({','.join('?' * len(cols))})", vals)
    return office_row(c, oid, kind, cur.lastrowid)


def office_update(c, oid, kind, rid, b):
    m = MD[kind]
    r = office_row(c, oid, kind, rid)
    sets, vals = [], []
    for k, v in b.items():
        if k not in m["cols"]:
            continue
        sets.append(f"{k}=?")
        vals.append(_clean_col(c, oid, kind, k, v))
    if sets:
        if "updated_at" in _cols(c, m["table"]):
            sets.append("updated_at=?")
            vals.append(iso(now_utc()))
        vals += [r["id"], oid]
        c.execute(f"UPDATE {m['table']} SET {', '.join(sets)} WHERE id=? AND org_id=?", vals)
    return office_row(c, oid, kind, rid)


def office_in_use(c, kind, rid):
    """True when documents (C's tables) or other master data refer to the row: then delete = archive."""
    if kind == "services":
        if _table(c, "office_doc_items") and c.execute("SELECT 1 FROM office_doc_items WHERE service_id=? LIMIT 1", (rid,)).fetchone():
            return True
        if c.execute("SELECT 1 FROM office_contracts WHERE rates LIKE ? LIMIT 1", (f'%"{rid}":%',)).fetchone():
            return True
        return False
    if kind == "equipment":
        return bool(c.execute("SELECT 1 FROM office_sets WHERE items LIKE ? LIMIT 1", (f'%"equipment_id": {rid},%',)).fetchone()
                    or c.execute("SELECT 1 FROM office_sets WHERE items LIKE ? LIMIT 1", (f'%"equipment_id": {rid}}}%',)).fetchone())
    if kind == "texts":
        if c.execute("SELECT 1 FROM office_contracts WHERE rights_time_id=? OR rights_territory_id=? OR rights_media_id=? LIMIT 1", (rid, rid, rid)).fetchone():
            return True
        return False
    if kind == "contracts":
        return bool(_table(c, "office_docs") and c.execute("SELECT 1 FROM office_docs WHERE contract_id=? LIMIT 1", (rid,)).fetchone())
    return False


def office_delete(c, oid, kind, rid):
    """Deletes the row; when it is in use (documents, contracts, sets) it is archived instead. -> 'deleted' | 'archived'"""
    m = MD[kind]
    r = office_row(c, oid, kind, rid)
    if office_in_use(c, kind, r["id"]):
        c.execute(f"UPDATE {m['table']} SET archived=1 WHERE id=? AND org_id=?", (r["id"], oid))
        return "archived"
    c.execute(f"DELETE FROM {m['table']} WHERE id=? AND org_id=?", (r["id"], oid))
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
        _COLS[table] = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
    return _COLS[table]


def _table(c, name):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


# ---------------------------------------------------------------- import / export (JSON, master data only)
EXPORT_KINDS = ("services", "equipment", "sets", "texts", "contracts")


def office_export(c, oid):
    """The master data + settings of the organisation as one JSON-able dict (no documents, no logo file)."""
    s = office_settings(c, oid)
    out = {"kalmido_office": 1, "exported_at": iso(now_utc()), "settings": s}
    for k in EXPORT_KINDS:
        rows = office_rows(c, oid, k)
        for r in rows:
            r.pop("org_id", None)
        out[k] = rows
    return out


def office_import(c, oid, d, overwrite=False):
    """Additive import of an export (or a hand-made file of the same shape): rows are matched by their label (services:
    name_de, equipment/sets/contracts: name, texts: kind + key); existing ones are left alone unless overwrite. Ids inside
    the file (sets.items, contracts.rates / rights ids, settings' text ids) are mapped to the new ids. -> counts"""
    if not isinstance(d, dict):
        raise BadInput(tr("Invalid data"))
    counts = {k: {"added": 0, "updated": 0, "skipped": 0} for k in EXPORT_KINDS}
    idmap = {k: {} for k in EXPORT_KINDS}

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
            if kind == "sets" and isinstance(b.get("items"), list):
                b["items"] = [{"equipment_id": idmap["equipment"].get(_i(it.get("equipment_id")), _i(it.get("equipment_id"))), "qty": it.get("qty", 1)}
                              for it in b["items"] if isinstance(it, dict)]
            if kind == "contracts":
                if isinstance(b.get("rates"), dict):
                    b["rates"] = {str(idmap["services"].get(_i(k), _i(k))): v for k, v in b["rates"].items()}
                for f in ("rights_time_id", "rights_territory_id", "rights_media_id"):
                    if b.get(f) is not None:
                        b[f] = idmap["texts"].get(_i(b[f]), _i(b[f]))
                b.pop("client_id", None)  # clients are not part of the master data file
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
        b = {k: v for k, v in st.items() if k in SETTINGS_KEYS and k != "logo"}
        if "producing_service_id" in b and b["producing_service_id"] is not None:
            b["producing_service_id"] = idmap["services"].get(_i(b["producing_service_id"]))
        for k in ("intro_text_id", "closing_text_id"):
            if isinstance(b.get(k), dict):
                b[k] = {lg: idmap["texts"].get(_i(v)) for lg, v in b[k].items() if lg in ("de", "en")}
        if isinstance(b.get("rights_default"), dict):
            b["rights_default"] = {f: idmap["texts"].get(_i(v)) for f, v in b["rights_default"].items() if f in ("time_id", "territory_id", "media_id")}
        if overwrite or not c.execute("SELECT 1 FROM office_settings WHERE org_id=?", (oid,)).fetchone():
            office_settings_save(c, oid, office_settings_clean(c, oid, b, cur))
            counts["settings"] = "updated"
        else:
            counts["settings"] = "skipped"
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
