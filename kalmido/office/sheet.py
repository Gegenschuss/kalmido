"""2.47.0 (#1216): the calculation sheet of a quotation part of kind 'shoot' (Drehkalkulation) and the industry packs.

Three layers, no code plugin:
 1. this core: head values + rows with fixed rules (kinds staff, share, km, meals, hotel, set, free);
 2. the crew master data (office_roles kind 'crew': name, day rate = the client's price, intern | extern, markup_pct);
 3. an industry pack (kalmido/office/packs/industry/<code>.json): data only -- labels DE/EN, print order of the blocks,
    default values (meal rates, weekend surcharges, producing share, km rate), suggested crew functions. Switched on per
    organisation in the office settings (industry_packs); without a pack there is no shoot calculation.

Rules (the spreadsheet the module replaces):
 - staff: day rate x (shoot days + travel days x travel share + [prep] prep days x prep share + Saturdays x surcharge
   + Sundays x surcharge) per person, times the number of people; an optional markup raises the price (not the purchase)
 - share (producing): share x the sum of the staff rows, intern
 - km: km x rate x trips, extern; meals: people x (travel days x small rate + shoot days x (large rate when more than one
   night, else small rate)), extern; hotel: people x nights x price per night (only with nights), extern
 - set: days (default = shoot days) x price per day x (1 - discount), intern unless set otherwise
 - free: qty x rate (+ markup), extern by default; a 'shooting' service can be picked as such a row
 - discount on the sum rounded to whole units; costs (Fremdkosten) = the purchase of the extern rows (without markup)
Money is Decimal rounded half up like calc.money; the result holds strings (exact) for the parts calculation.
"""
import json
import logging
import os
import re
import secrets
import stat
from decimal import Decimal, ROUND_HALF_UP

from .calc import calc_code, calc_lang, dec, money, fmt_money, fmt_qty

IND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "packs", "industry")
DK_BLOCKS = ("staff", "share", "km", "meals", "hotel", "set", "free")
DK_HEAD = ("shoot_days", "travel_days", "travel_share", "prep_days", "prep_share", "nights", "night_rate",
           "meal_large", "meal_small", "sat_days", "sat_pct", "sun_days", "sun_pct")
DK_DEFAULT_KEYS = DK_HEAD + ("producing_share", "km", "km_rate", "km_trips")
DK_INTEXT = ("intern", "extern")
DK_LABEL_KEYS = DK_HEAD + DK_BLOCKS + ("title", "item", "qty", "rate", "total", "sum", "discount", "net", "costs", "margin",
                                       "prep", "set_days_note", "set_discount", "km_detail", "share_detail", "meals_detail",
                                       "hotel_detail")
DK_MAX_ROWS = 60
DK_NAME_MAX = 200
_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
_cache = {}
# 2.113.1 (#2252): own industry packs of an instance in its data folder (next to the database, /data/packs/industry in
# Docker), checked like the shipped ones; a file with the code of a shipped pack is refused (log line), the shipped one stays
IND_DATA_DIR = os.path.join(os.path.dirname(os.environ.get("TASKS_DB", "/data/tasks.db")), "packs", "industry")
PRD_PACK_MAX = 512 * 1024
PRD_OPTS = ("share", "handling", "markup")  # 2.113.1 (#2251, #2252): the calculation options a pack may offer
_data = {}  # path -> ((mtime, size), pack or None)
log = logging.getLogger(__name__)


def _pkc(name, *a):
    """2.76.0 (#1023): office/catalog.py's view of the installed packs of the bound office area (None without the app, e.g.
    tools/packs_catalog.py or a pure test loading this file alone: then only the shipped packs exist)."""
    try:
        from . import catalog
    except ImportError:
        return None
    return getattr(catalog, name)(*a)


# ---------------------------------------------------------------- industry packs
def dk_pack_codes():
    """The codes of the industry packs shipped with the app (sorted)."""
    if not os.path.isdir(IND_DIR):
        return []
    return sorted({f[:-5] for f in os.listdir(IND_DIR) if f.endswith(".json") and _CODE_RE.match(f[:-5])} | (_pkc("pkc_codes", "industry") or set())  # 2.76.0 (#1023): + the installed packs
                  | set(prd_data_packs()))  # 2.113.1 (#2252): + the own packs of the data folder


def prd_data_packs():
    """2.113.1 (#2252): {code: pack} of the valid own packs in IND_DATA_DIR (a file is read again when it changes)."""
    if not os.path.isdir(IND_DATA_DIR):
        return {}
    out = {}
    for f in sorted(os.listdir(IND_DATA_DIR)):
        code = f[:-5] if f.endswith(".json") else ""
        if not _CODE_RE.match(code):
            continue
        p = os.path.join(IND_DATA_DIR, f)
        try:
            st = os.lstat(p)
        except OSError:
            continue
        if not stat.S_ISREG(st.st_mode):  # a regular file only (no symlink, no folder)
            continue
        key = (st.st_mtime_ns, st.st_size)
        hit = _data.get(p)
        if not hit or hit[0] != key:
            hit = _data[p] = (key, _prd_load(p, code, st.st_size))
        if hit[1]:
            out[code] = hit[1]
    return out


def _prd_load(p, code, size):
    if os.path.isfile(os.path.join(IND_DIR, code + ".json")):
        log.warning("own industry pack %s refused: a shipped pack has this code", code)
        return None
    if size > PRD_PACK_MAX:
        log.warning("own industry pack %s refused: larger than %d bytes", code, PRD_PACK_MAX)
        return None
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        log.warning("own industry pack %s refused: not readable as JSON", code)
        return None
    bad = dk_pack_validate(d)
    if not bad and d.get("code") != code:
        bad = ["code: must match the file name"]
    if bad:
        log.warning("own industry pack %s refused: %s", code, "; ".join(bad[:5]))
        return None
    return d


def dk_pack(code, builtin=False):
    """The industry pack dict for code ("film"), or None (unknown / invalid). Cached per process.
    2.76.0 (#1023): an installation of the bound office area (office/catalog.py) comes first; builtin=True: the file only."""
    code = (code or "").strip().lower()
    if not _CODE_RE.match(code):
        return None
    if not builtin:
        inst = _pkc("pkc_installed", "industry", code)
        if inst:
            return inst
    if code in _cache:
        return _cache[code]
    p = os.path.join(IND_DIR, code + ".json")
    if not os.path.isfile(p):
        return prd_data_packs().get(code)  # 2.113.1 (#2252): an own pack of the data folder
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    if dk_pack_validate(d):
        return None
    _cache[code] = d
    return d


def _num_ok(v, lo=0, hi=None):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= lo and (hi is None or v <= hi)


def dk_pack_validate(d):
    """-> list of problems (empty = valid): the shape the sheet relies on; data only, no markup."""
    bad = []
    if not isinstance(d, dict):
        return ["pack must be an object"]
    if not isinstance(d.get("code"), str) or not _CODE_RE.match(d["code"]):
        bad.append("code: lower-case letters, digits, _")
    if d.get("kind") != "industry":
        bad.append("kind: industry")
    if not isinstance(d.get("version"), int) or isinstance(d.get("version"), bool) or d["version"] < 1:
        bad.append("version: integer >= 1")
    nm = d.get("name")
    if not isinstance(nm, dict) or any(not isinstance(nm.get(lg), str) or not nm[lg] for lg in ("de", "en")):
        bad.append("name: de/en")
    if d.get("part_kind") != "shoot":
        bad.append("part_kind: shoot")
    bl = d.get("blocks")
    if not isinstance(bl, list) or not bl or any(b not in DK_BLOCKS for b in bl) or len(set(bl)) != len(bl):
        bad.append("blocks: list of " + "|".join(DK_BLOCKS) + ", each once")
    df = d.get("defaults")
    if not isinstance(df, dict):
        bad.append("defaults: object required")
    else:
        for k in DK_DEFAULT_KEYS:
            if not _num_ok(df.get(k), 0, 100000):
                bad.append(f"defaults.{k}: number >= 0")
    ro = d.get("roles", [])
    if not isinstance(ro, list) or any(not isinstance(r, dict) or not isinstance(r.get("de"), str) or not r["de"]
                                       or not isinstance(r.get("en"), str) or r.get("intext") not in DK_INTEXT for r in ro):
        bad.append("roles: list of {de, en, intext intern|extern}")
    lb = d.get("labels")
    if not isinstance(lb, dict):
        bad.append("labels: object required")
    else:
        for lg in ("de", "en"):
            L = lb.get(lg)
            if not isinstance(L, dict):
                bad.append(f"labels.{lg}: object required")
                continue
            for k in DK_LABEL_KEYS:
                if not isinstance(L.get(k), str) or not L[k]:
                    bad.append(f"labels.{lg}.{k}: text required")
    bad += prd_calc_validate(d.get("calc"))  # 2.113.1 (#2251, #2252)
    for path, s in _strings(d):
        if "<" in s and ">" in s or "javascript:" in s.lower():
            bad.append(f"{path}: markup is not allowed")
            break
    return bad


def _prd_name(v, n=60):
    return isinstance(v, dict) and all(isinstance(v.get(lg), str) and v[lg].strip() and len(v[lg]) <= n for lg in ("de", "en"))


def prd_calc_validate(cl):
    """2.113.1 (#2251, #2252): the optional calculation options of a pack, "calc": {"share": {"label": {de, en}, "rate":
    day rate, "factor": 0.01..10}, "handling": {"label": {de, en}, "pct": 0..100, "on": bool}, "markup": {"label":
    {de, en}, "pct": 0..100, "on": bool, "stacked": bool}} -> list of problems."""
    if cl is None:
        return []
    if not isinstance(cl, dict) or any(k not in PRD_OPTS for k in cl):
        return ["calc: object with " + " | ".join(PRD_OPTS)]
    bad = []
    sh = cl.get("share")
    if sh is not None and (not isinstance(sh, dict) or not _prd_name(sh.get("label")) or not _num_ok(sh.get("rate"), 0.01, 1e7)
                           or not _num_ok(sh.get("factor"), 0.01, 10)):
        bad.append("calc.share: {label {de, en}, rate > 0, factor 0.01..10}")
    for k in ("handling", "markup"):
        x = cl.get(k)
        if x is not None and (not isinstance(x, dict) or not _prd_name(x.get("label")) or not _num_ok(x.get("pct"), 0, 100)
                              or not isinstance(x.get("on", False), bool) or not isinstance(x.get("stacked", False), bool)
                              or k == "handling" and "stacked" in x):
            bad.append(f"calc.{k}: {{label {{de, en}}, pct 0..100, on true|false" + (", stacked true|false}" if k == "markup" else "}"))
    return bad


def prd_options(settings):
    """2.113.1 (#2251, #2252): the calculation options of the industry packs switched on: {"share" | "handling" |
    "markup": {...} | None}, each the first pack (in the order switched on) that offers it, with its "pack" code."""
    out = {k: None for k in PRD_OPTS}
    for code in dk_packs_on(settings):
        cl = (dk_pack(code) or {}).get("calc") or {}
        for k in out:
            if out[k] is None and isinstance(cl.get(k), dict):
                out[k] = {**cl[k], "pack": code}
    return out


def _strings(d, path="pack"):
    if isinstance(d, str):
        yield path, d
    elif isinstance(d, dict):
        for k, v in d.items():
            yield from _strings(v, f"{path}.{k}")
    elif isinstance(d, list):
        for i, v in enumerate(d):
            yield from _strings(v, f"{path}[{i}]")


def dk_packs_on(settings):
    """The industry packs switched on in the office settings (codes that exist)."""
    codes = (settings or {}).get("industry_packs") or []
    return [x for x in codes if isinstance(x, str) and dk_pack(x)] if isinstance(codes, list) else []


def dk_enabled(settings):
    """True when the organisation may add a shoot calculation part (an industry pack is switched on)."""
    return bool(dk_packs_on(settings))


def dk_packs_clean(v):
    """The settings value industry_packs from a request: a list of known pack codes (unknown ones dropped)."""
    if not isinstance(v, list):
        return []
    known = set(dk_pack_codes())
    out = []
    for x in v[:20]:
        x = str(x or "").strip().lower()
        if x in known and x not in out:
            out.append(x)
    return out


def dk_pack_public(d, lang="de"):
    """What the client needs of a pack: code, name, blocks, defaults, labels (both languages), role suggestions."""
    if not d:
        return None
    return {"code": d["code"], "name": d["name"], "blocks": d["blocks"], "defaults": d["defaults"],
            "labels": d["labels"], "roles": d.get("roles") or [], "calc": d.get("calc") or {}}  # 2.113.1 (#2251): + calc options


# ---------------------------------------------------------------- clean (request -> stored sheet)
def _uid(v):
    s = str(v or "")
    return s if re.match(r"^[A-Za-z0-9_-]{1,24}$", s) else secrets.token_hex(5)


def _n(v, default, lo=Decimal(0), hi=Decimal(100000)):
    """A non-negative number (as a JSON float/int) from the request, clamped; bad input = default."""
    d = dec(v, str(default))
    if not d.is_finite():
        d = dec(default)
    d = max(lo, min(hi, d))
    d = d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP).normalize()
    return int(d) if d == d.to_integral() else float(d)


def _txt(v, mx=DK_NAME_MAX):
    return re.sub(r"[\x00-\x1f]", " ", str(v or "")).strip()[:mx]


def _ie(v, default):
    return v if v in DK_INTEXT else default


def _row_by_uid(rows):
    return {r.get("uid"): r for r in rows or [] if isinstance(r, dict) and r.get("uid")}


def _role(c, oid, rid):
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        return None
    r = c.execute("SELECT id, name_de, name_en, rate_day, intext, markup_pct FROM office_roles WHERE id=? AND org_id=? AND kind='crew'",
                  (rid, oid)).fetchone()
    return dict(r) if r else None


def _service(c, oid, sid):
    try:
        sid = int(sid)
    except (TypeError, ValueError):
        return None
    r = c.execute("SELECT id, name_de, name_en, daily_rate FROM office_services WHERE id=? AND org_id=? AND intext='shooting'",
                  (sid, oid)).fetchone()
    return dict(r) if r else None


def _set_items(c, oid, set_id):
    """The equipment of a master set as sheet rows [{equipment_id, name, name_en, qty, rate}] + its discount."""
    try:
        set_id = int(set_id)
    except (TypeError, ValueError):
        return None
    r = c.execute("SELECT id, name, discount_pct, items FROM office_sets WHERE id=? AND org_id=?", (set_id, oid)).fetchone()
    if not r:
        return None
    try:
        items = json.loads(r["items"] or "[]")
    except ValueError:
        items = []
    out = []
    for it in items if isinstance(items, list) else []:
        eq = _equipment(c, oid, (it or {}).get("equipment_id"))
        if eq:
            eq["qty"] = _n((it or {}).get("qty"), 1)
            out.append(eq)
    return {"set_id": r["id"], "name": r["name"], "discount_pct": _n(r["discount_pct"], 0, hi=Decimal(100)), "items": out}


def _equipment(c, oid, eid):
    try:
        eid = int(eid)
    except (TypeError, ValueError):
        return None
    e = c.execute("SELECT id, name, name_en, daily_rate FROM office_equipment WHERE id=? AND org_id=?", (eid, oid)).fetchone()
    if not e:
        return None
    return {"equipment_id": e["id"], "name": e["name"], "name_en": e["name_en"] or "", "qty": 1, "rate": _n(e["daily_rate"], 0)}


def dk_sheet_new(pack):
    """An empty sheet with the pack's defaults (a new part of kind 'shoot')."""
    df = (pack or {}).get("defaults") or {}
    return {"v": 1, "pack": (pack or {}).get("code") or "film",
            "head": {k: _n(df.get(k), 0) for k in DK_HEAD},
            "staff": [], "producing": {"on": 1, "share": _n(df.get("producing_share"), 0)},
            "km": {"km": _n(df.get("km"), 0), "rate": _n(df.get("km_rate"), 0), "trips": _n(df.get("km_trips"), 0)},
            "meals_on": 1, "set": None, "extras": [], "discount_pct": 0}


def dk_sheet_clean(c, oid, sheet_in, cur_sheet, admin):
    """The sheet to store from a request (sheet_in) and the stored one (cur_sheet, {} for a new part).
    Rows carry a uid; a new staff row takes name / rate / intext / markup from the crew role at insert time (a later change
    of the role touches only new rows). Members (admin False) cannot set markup_pct or the base rate of a row: the stored
    value stays (new rows: the role's); they never get these values (dk_sheet_public)."""
    cur = cur_sheet if isinstance(cur_sheet, dict) and cur_sheet.get("v") else None
    b = sheet_in if isinstance(sheet_in, dict) else {}
    pack = dk_pack((cur or {}).get("pack") or b.get("pack") or "film") or dk_pack("film")
    base = cur or dk_sheet_new(pack)
    out = {"v": 1, "pack": base.get("pack") or "film"}
    hin, hcur = b.get("head") if isinstance(b.get("head"), dict) else {}, base.get("head") or {}
    out["head"] = {k: _n(hin.get(k, hcur.get(k)), hcur.get(k, 0)) for k in DK_HEAD}
    # staff rows
    old = _row_by_uid(base.get("staff"))
    rows = b.get("staff") if isinstance(b.get("staff"), list) else base.get("staff") or []
    staff = []
    for r in rows[:DK_MAX_ROWS]:
        if not isinstance(r, dict):
            continue
        prev = old.get(r.get("uid"))
        if prev:
            row = dict(prev)
        else:
            role = _role(c, oid, r.get("role_id"))
            if role:
                row = {"uid": _uid(None), "role_id": role["id"], "name": role["name_de"], "name_en": role["name_en"] or "",
                       "rate": _n(role["rate_day"], 0), "intext": _ie(role["intext"], "extern"),
                       "markup_pct": _n(role["markup_pct"], 0, hi=Decimal(1000))}
            elif admin and _txt(r.get("name")):  # a row without a role (admin only: it sets a price)
                row = {"uid": _uid(None), "role_id": None, "name": _txt(r.get("name")), "name_en": _txt(r.get("name_en")),
                       "rate": 0, "intext": "extern", "markup_pct": 0}
            else:
                continue
        row["qty"] = _n(r.get("qty", row.get("qty", 1)), 1, hi=Decimal(1000))
        row["prep"] = 1 if r.get("prep", row.get("prep", 1)) in (1, True, "1") else 0
        if admin and "intext" in r:  # intern / extern decides the purchase: admins only
            row["intext"] = _ie(r.get("intext"), row.get("intext", "extern"))
        if admin:
            if "rate" in r:
                row["rate"] = _n(r.get("rate"), row.get("rate", 0))
            if "markup_pct" in r:
                row["markup_pct"] = _n(r.get("markup_pct"), row.get("markup_pct", 0), hi=Decimal(1000))
        staff.append(row)
    out["staff"] = staff
    pin, pcur = b.get("producing") if isinstance(b.get("producing"), dict) else {}, base.get("producing") or {}
    out["producing"] = {"on": 1 if pin.get("on", pcur.get("on", 1)) in (1, True, "1") else 0,
                        "share": _n(pin.get("share", pcur.get("share", 0)), pcur.get("share", 0), hi=Decimal(10))}
    kin, kcur = b.get("km") if isinstance(b.get("km"), dict) else {}, base.get("km") or {}
    out["km"] = {k: _n(kin.get(k, kcur.get(k, 0)), kcur.get(k, 0)) for k in ("km", "rate", "trips")}
    out["meals_on"] = 1 if b.get("meals_on", base.get("meals_on", 1)) in (1, True, "1") else 0
    out["set"] = _clean_set(c, oid, b, base, admin)
    # extras (Zusatzkosten): free text rows or a 'shooting' service
    old = _row_by_uid(base.get("extras"))
    rows = b.get("extras") if isinstance(b.get("extras"), list) else base.get("extras") or []
    extras = []
    for r in rows[:DK_MAX_ROWS]:
        if not isinstance(r, dict):
            continue
        prev = old.get(r.get("uid"))
        if prev:
            row = dict(prev)
        else:
            sv = _service(c, oid, r.get("service_id")) if r.get("service_id") else None
            if sv:
                row = {"uid": _uid(None), "service_id": sv["id"], "name": sv["name_de"], "name_en": sv["name_en"] or "",
                       "rate": _n(sv["daily_rate"], 0), "intext": "extern", "markup_pct": 0}
            else:
                row = {"uid": _uid(None), "service_id": None, "name": "", "name_en": "", "rate": 0, "intext": "extern", "markup_pct": 0}
        if "name" in r:
            row["name"] = _txt(r.get("name"))
        row["qty"] = _n(r.get("qty", row.get("qty", 1)), 1)
        if "rate" in r and (admin or not row.get("markup_pct")):  # a member keeps the price of a row with a markup
            row["rate"] = _n(r.get("rate"), row.get("rate", 0))
        if admin and "intext" in r:  # intern / extern decides the purchase: admins only
            row["intext"] = _ie(r.get("intext"), row.get("intext", "extern"))
        if admin and "markup_pct" in r:
            row["markup_pct"] = _n(r.get("markup_pct"), row.get("markup_pct", 0), hi=Decimal(1000))
        extras.append(row)
    out["extras"] = extras
    out["discount_pct"] = _n(b.get("discount_pct", base.get("discount_pct", 0)), base.get("discount_pct", 0), hi=Decimal(100))
    return out


def _clean_set(c, oid, b, base, admin):
    """The equipment set of the sheet: picking a master set copies its equipment and discount (the master stays as it is);
    then the rows can be changed here (add / remove equipment, qty), days (None = the shoot days) and discount."""
    cur = base.get("set") if isinstance(base.get("set"), dict) else None
    if "set" not in b:
        return cur
    s = b.get("set")
    if not isinstance(s, dict):
        return None
    if s.get("set_id") and (not cur or str(s.get("set_id")) != str(cur.get("set_id"))):
        m = _set_items(c, oid, s.get("set_id"))
        if not m:
            return cur
        cur = {"set_id": m["set_id"], "name": m["name"], "days": None, "discount_pct": m["discount_pct"],
               "intext": "intern", "items": m["items"]}
        return cur
    if not cur:
        cur = {"set_id": None, "name": "", "days": None, "discount_pct": 0, "intext": "intern", "items": []}
    out = dict(cur)
    if "name" in s:
        out["name"] = _txt(s.get("name"))
    if "days" in s:
        out["days"] = None if s.get("days") in (None, "") else _n(s.get("days"), 0, hi=Decimal(1000))
    if "discount_pct" in s:
        out["discount_pct"] = _n(s.get("discount_pct"), cur.get("discount_pct", 0), hi=Decimal(100))
    if admin and "intext" in s:
        out["intext"] = _ie(s.get("intext"), cur.get("intext", "intern"))
    if isinstance(s.get("items"), list):
        old = {str(i.get("equipment_id")): i for i in cur.get("items") or []}
        items = []
        for it in s["items"][:DK_MAX_ROWS]:
            if not isinstance(it, dict):
                continue
            prev = old.get(str(it.get("equipment_id")))
            row = dict(prev) if prev else _equipment(c, oid, it.get("equipment_id"))
            if not row:
                continue
            row["qty"] = _n(it.get("qty", row.get("qty", 1)), 1, hi=Decimal(1000))
            items.append(row)
        out["items"] = items
    return out


def dk_sheet_public(sheet, admin):
    """The stored sheet for the client: members get no markup_pct and see a row's price including the markup as its rate."""
    if admin or not isinstance(sheet, dict):
        return sheet
    out = json.loads(json.dumps(sheet))
    for k in ("staff", "extras"):
        for r in out.get(k) or []:
            r.pop("intext", None)  # 2.47.0 (#1216): intern / extern is the purchase line, admins only (as dk_calc_public)
            m = dec(r.pop("markup_pct", 0) or 0)
            if m:
                r["rate"] = float(money(dec(r.get("rate")) * (1 + m / 100)))
    if isinstance(out.get("set"), dict):
        out["set"].pop("intext", None)
    return out


# ---------------------------------------------------------------- calc
def _lab(pack, lang, key, **kw):
    lg = "de" if calc_lang(lang) == "de" else "en"  # 2.185.0 C (#2520): the pack's words are de / en; other languages take English
    L = (((pack or {}).get("labels") or {}).get(lg) or {})
    s = L.get(key) or (((pack or {}).get("labels") or {}).get("de") or {}).get(key) or key
    if kw:
        try:
            s = re.sub(r"\{(\w+)\}", lambda m: str(kw[m.group(1)]) if m.group(1) in kw else m.group(0), s)  # 2.148.1 E (#2496): plain placeholders only
        except (KeyError, IndexError, ValueError):
            pass
    return s


def _s(d):
    return str(money(d))


def dk_sheet_calc(sheet, pack=None, lang="de", currency="EUR", fx=1, home="EUR"):
    """-> {net, base {standard, reduced, exempt}, sum, discount, costs, margin, lines [...], labels {...}, blocks [...]}.
    Amounts are strings with 2 places in the document's currency (rates are kept in the organisation's currency and
    converted with fx when the document is in USD, the converted rate rounded first like calc.office_calc).
    lines: {block, uid, label, detail, qty, rate, total, intext, cost, markup_pct}; cost / markup_pct / costs / margin are
    internal (dk_calc_public strips them for members). 2.189.0 (#2475): home = the office's home currency (the rates'),
    every other currency is converted with fx."""
    sheet = sheet if isinstance(sheet, dict) else {}
    if not (isinstance(pack, dict) and pack.get("blocks")):
        pack = dk_pack(sheet.get("pack") or "film") or {}
    lg = calc_lang(lang)  # 2.185.0 C (#2520): every app language (numbers); names / words of the pack: de, else English (plg)
    plg = "de" if lg == "de" else "en"
    home = calc_code(home)
    cur = calc_code(currency, home)
    usd = cur != home  # 2.189.0 (#2475): "foreign", was USD
    fxd = dec(fx, "1") if usd else Decimal(1)
    if fxd <= 0:
        fxd = Decimal(1)

    def conv(v):
        return money(dec(v) * fxd) if usd else money(dec(v))

    h = sheet.get("head") or {}
    H = {k: dec(h.get(k), "0") for k in DK_HEAD}
    D, R, V, N = H["shoot_days"], H["travel_days"], H["prep_days"], H["nights"]
    weekend = H["sat_days"] * H["sat_pct"] / 100 + H["sun_days"] * H["sun_pct"] / 100
    base_days = D + R * H["travel_share"] + weekend
    lines = {b: [] for b in DK_BLOCKS}

    def name(r):
        return (r.get("name_en") or r.get("name") or "") if plg == "en" else (r.get("name") or "")

    # staff
    people = Decimal(0)
    staff_sum = Decimal(0)
    for r in sheet.get("staff") or []:
        qty = dec(r.get("qty"), "1")
        mk = dec(r.get("markup_pct"), "0")
        days = base_days + (V * H["prep_share"] if r.get("prep") else 0)
        unit = money(conv(r.get("rate")) * (1 + mk / 100) * days)  # the price per person for the whole shoot
        total = money(qty * unit)
        cost = money(qty * money(conv(r.get("rate")) * days)) if r.get("intext") == "extern" else Decimal(0)
        people += qty
        staff_sum += total
        lines["staff"].append({"block": "staff", "uid": r.get("uid"), "label": name(r), "detail": _lab(pack, lg, "prep") if r.get("prep") and V else "",
                               "qty": fmt_qty(qty, lg), "rate": _s(unit), "total": _s(total), "intext": r.get("intext") or "extern",
                               "cost": _s(cost), "markup_pct": str(mk.normalize())})
    # producing share of the crew
    p = sheet.get("producing") or {}
    if p.get("on", 1):
        sh = dec(p.get("share"), "0")
        tot = money(staff_sum * sh)
        lines["share"].append({"block": "share", "uid": "share", "label": _lab(pack, lg, "share"),
                               "detail": _lab(pack, lg, "share_detail", pct=fmt_qty(sh * 100, lg)), "qty": fmt_qty(sh, lg),
                               "rate": _s(staff_sum), "total": _s(tot), "intext": "intern", "cost": "0.00", "markup_pct": "0"})
    # km
    k = sheet.get("km") or {}
    km, kr, kt = dec(k.get("km")), conv(k.get("rate")), dec(k.get("trips"))
    if km and kt:
        tot = money(km * kr * kt)
        lines["km"].append({"block": "km", "uid": "km", "label": _lab(pack, lg, "km"),
                            "detail": _lab(pack, lg, "km_detail", km=fmt_qty(km, lg), rate=fmt_money(kr, lg, cur), trips=fmt_qty(kt, lg)),
                            "qty": fmt_qty(km, lg), "rate": _s(kr), "total": _s(tot), "intext": "extern", "cost": _s(tot), "markup_pct": "0"})
    # meals: the spreadsheet's rule -- travel days at the small rate, shoot days at the large rate only with more than one night
    if sheet.get("meals_on", 1) and people:
        rate = R * conv(H["meal_small"]) + D * conv(H["meal_large"] if N > 1 else H["meal_small"])
        rate = money(rate)
        tot = money(people * rate)
        if tot:
            lines["meals"].append({"block": "meals", "uid": "meals", "label": _lab(pack, lg, "meals"),
                                   "detail": _lab(pack, lg, "meals_detail", n=fmt_qty(people, lg)), "qty": fmt_qty(people, lg),
                                   "rate": _s(rate), "total": _s(tot), "intext": "extern", "cost": _s(tot), "markup_pct": "0"})
    if N > 0 and people:
        rate = money(N * conv(H["night_rate"]))
        tot = money(people * rate)
        lines["hotel"].append({"block": "hotel", "uid": "hotel", "label": _lab(pack, lg, "hotel"),
                               "detail": _lab(pack, lg, "hotel_detail", n=fmt_qty(N, lg)), "qty": fmt_qty(people, lg),
                               "rate": _s(rate), "total": _s(tot), "intext": "extern", "cost": _s(tot), "markup_pct": "0"})
    # equipment set: price per day = the sum of its equipment
    st = sheet.get("set")
    if isinstance(st, dict) and (st.get("items") or st.get("name")):
        day = money(sum((dec(i.get("qty"), "1") * conv(i.get("rate")) for i in st.get("items") or []), Decimal(0)))
        days = D if st.get("days") is None else dec(st.get("days"))
        disc = dec(st.get("discount_pct"), "0")
        tot = money(days * day * (1 - disc / 100))
        notes = []
        if st.get("days") is not None and days != D:
            notes.append(_lab(pack, lg, "set_days_note", days=fmt_qty(D, lg)))
        if disc:
            notes.append(_lab(pack, lg, "set_discount", pct=fmt_qty(disc, lg)))
        ie = st.get("intext") or "intern"
        lines["set"].append({"block": "set", "uid": "set", "label": _lab(pack, lg, "set") + (": " + st["name"] if st.get("name") else ""),
                             "detail": ", ".join(notes), "qty": fmt_qty(days, lg), "rate": _s(day), "total": _s(tot), "intext": ie,
                             "cost": _s(tot) if ie == "extern" else "0.00", "markup_pct": "0", "days_differ": bool(notes and days != D)})
    for r in sheet.get("extras") or []:
        qty = dec(r.get("qty"), "1")
        mk = dec(r.get("markup_pct"), "0")
        rate = money(conv(r.get("rate")) * (1 + mk / 100))
        tot = money(qty * rate)
        ie = r.get("intext") or "extern"
        lines["free"].append({"block": "free", "uid": r.get("uid"), "label": name(r) or _lab(pack, lg, "free"), "detail": "",
                              "qty": fmt_qty(qty, lg), "rate": _s(rate), "total": _s(tot), "intext": ie,
                              "cost": _s(money(qty * conv(r.get("rate")))) if ie == "extern" else "0.00", "markup_pct": str(mk.normalize())})
    order = [b for b in (pack.get("blocks") or DK_BLOCKS) if b in DK_BLOCKS]
    order += [b for b in DK_BLOCKS if b not in order]
    flat = [ln for b in order for ln in lines[b]]
    total = sum((dec(ln["total"]) for ln in flat), Decimal(0))
    dp = dec(sheet.get("discount_pct"), "0")
    disc = -(total * dp / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP) if dp else Decimal(0)  # whole units like the sheet
    net = money(total + disc)
    costs = money(sum((dec(ln["cost"]) for ln in flat), Decimal(0)))
    labels = dict(((pack.get("labels") or {}).get(plg) or {}))
    head_print = [[labels.get(k) or k, fmt_qty(H[k], lg)] for k in ("shoot_days", "travel_days", "prep_days", "nights", "sat_days", "sun_days")
                  if H[k] or k == "shoot_days"]
    return {"net": _s(net), "base": {"standard": _s(net), "reduced": "0.00", "exempt": "0.00"}, "sum": _s(total),
            "discount": _s(disc), "discount_pct": str(dp.normalize()), "costs": _s(costs), "margin": _s(net - costs),
            "people": fmt_qty(people, lg), "staff_sum": _s(staff_sum), "lines": flat, "blocks": order,
            "labels": labels, "head_print": head_print, "lang": lg, "currency": cur}


def dk_calc_public(calc, admin):
    """The calculation for the client: members get no purchase (costs, margin, cost per row) and no markup."""
    if admin or not isinstance(calc, dict):
        return calc
    out = {k: v for k, v in calc.items() if k not in ("costs", "margin")}
    out["lines"] = [{k: v for k, v in ln.items() if k not in ("cost", "markup_pct", "intext")} for ln in calc.get("lines") or []]
    return out


# ---------------------------------------------------------------- print
def dk_sheet_print(calc, lang="de"):
    """The page model of the sheet for the PDF (for the client: no intern / extern, no purchase, no markup column):
    {title, head: [[label, value]], rows: [{kind group|row|sum|note, label, qty_text, rate_text, total_text}], totals}."""
    calc = calc or {}
    lg = calc_lang(lang or calc.get("lang"))  # 2.185.0 C (#2520)
    L = calc.get("labels") or {}
    cur = calc.get("currency") or "EUR"

    def lab(k):
        return L.get(k) or k

    def m(v):
        return fmt_money(dec(v), lg, cur)

    rows = []
    last = None
    for ln in calc.get("lines") or []:
        if ln["block"] == "staff" and last != "staff":
            rows.append({"kind": "group", "label": lab("staff"), "qty_text": "", "rate_text": "", "total_text": ""})
        last = ln["block"]
        label = ln["label"] + (" (" + ln["detail"] + ")" if ln.get("detail") else "")
        rows.append({"kind": "row", "label": label, "qty_text": ln["qty"], "rate_text": m(ln["rate"]), "total_text": m(ln["total"])})
    rows.append({"kind": "sum", "label": lab("sum"), "qty_text": "", "rate_text": "", "total_text": m(calc.get("sum", "0"))})
    totals = [[lab("sum"), m(calc.get("sum", "0"))]]
    if dec(calc.get("discount", "0")):
        totals.append([lab("discount") + f" {fmt_qty(calc.get('discount_pct', '0'), lg)} %", m(calc["discount"])])
    totals.append([lab("net"), m(calc.get("net", "0"))])
    return {"title": lab("title"), "head": calc.get("head_print") or [], "rows": rows, "totals": totals}

