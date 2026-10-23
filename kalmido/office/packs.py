"""Office & finance (2.36.1, #1021): country packs -- data only (tax rates, formats, labels, default texts), one JSON
per country under kalmido/office/packs/<code>.json. A pack never holds code; office_pack_validate() checks the shape
so community packs (planned: a catalogue, installed per organisation) can be refused before they are used."""
import json
import os
import re

PACK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "packs")
PACK_LANGS = ("de", "en")  # document languages a pack must label
PACK_TAX_KEYS = ("standard", "reduced", "exempt")
PACK_LABEL_KEYS = ("offer", "offer_no", "project", "date", "valid_until", "pos", "title", "qty", "unit_price", "vat", "total",
                   "net_total", "incl_raw", "excl_raw", "raw_optional", "raw_included", "producing", "discount", "rights",
                   "rights_time", "rights_territory", "rights_media", "page_of", "signature", "units")
PACK_TEXT_KEYS = ("intro", "closing", "vat_note")
PACK_RIGHTS_KINDS = ("rights_time", "rights_territory", "rights_media")
_CODE_RE = re.compile(r"^[A-Z]{2}$")
_cache = {}

# 2.147.0 (#2459): the office functions a country pack offers ("features": {key: {"status": "ready"|"planned"}}). The key
# names a area + function so later packages add functions next to them (2.148: books.receipt_images, books.period_lock,
# books.procedure_doc are known as "planned" already). switch = the office admin may switch it off (#2460, settings
# features_off); a function that is not switchable (the finalising rules) stays in force whatever the settings say.
PACK_FEATURES = {
    "books.datev": {"switch": True},         # DATEV: booking batch (EXTF), document inbox, SKR accounts, travel "in DATEV"
    "docs.einvoice": {"switch": True},       # e-invoice XML (XRechnung / ZUGFeRD / Factur-X) on finalising and mailing
    "books.vat_return": {"switch": True},    # the VAT return figures (UStVA); the filing itself (ELSTER) stays outside
    "books.tax_dates": {"switch": True},     # tax dates as tasks (deadlines)
    "books.export_csv": {"switch": True},    # neutral export for any tax advisor: booking list (CSV) + receipts (ZIP)
    "books.gobd": {"switch": False},         # finalising rules: locked documents, number gaps with a reason, date order
}
PACK_FEATURES_PLANNED = ("books.receipt_images", "books.period_lock", "books.procedure_doc")  # 2.148 (#2470-#2472)
PACK_FEATURE_STATUS = ("ready", "planned")
# 2.147.0 (#2459, #2461): how long receipts and books are kept (years). editable = the office sets its own value (the
# neutral base pack); never below min_years. A pack without the block keeps everything 10 years, editable.
RETENTION_DEFAULT = {"receipts": 10, "books": 10, "min_years": 1, "editable": True}
RETENTION_MAX = 30


def _pkc(name, *a):
    """2.76.0 (#1023): office/catalog.py's view of the installed packs of the bound office area (None without the app, e.g.
    tools/packs_catalog.py or a pure test loading this file alone: then only the shipped packs exist)."""
    try:
        from . import catalog
    except ImportError:
        return None
    return getattr(catalog, name)(*a)


def office_pack_codes():
    """The codes of the packs shipped with the app (upper case, sorted)."""
    out = []
    for f in sorted(os.listdir(PACK_DIR)) if os.path.isdir(PACK_DIR) else []:
        if f.endswith(".json") and _CODE_RE.match(f[:-5].upper()):
            out.append(f[:-5].upper())
    return sorted(set(out) | (_pkc("pkc_codes", "country") or set()))  # 2.76.0 (#1023): + the installed packs


def office_pack(code, builtin=False):
    """The country pack dict for code ("DE"), or None when there is none. Cached per process (packs are files).
    2.76.0 (#1023): an installation of the bound office area (office/catalog.py) comes first; builtin=True: the file only."""
    code = (code or "").strip().upper()
    if not _CODE_RE.match(code):
        return None
    if not builtin:
        inst = _pkc("pkc_installed", "country", code)
        if inst:
            return inst
    if code in _cache:
        return _cache[code]
    p = os.path.join(PACK_DIR, code.lower() + ".json")
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    if office_pack_validate(d):
        return None
    _cache[code] = d
    return d


def office_pack_validate(d):
    """-> list of problems (empty = valid). Checks the shape a document renderer and the calculator rely on."""
    bad = []
    if not isinstance(d, dict):
        return ["pack must be an object"]
    code = d.get("code")
    if not isinstance(code, str) or not _CODE_RE.match(code):
        bad.append("code: two upper-case letters")
    for k in ("name", "currency"):
        if not isinstance(d.get(k), str) or not d.get(k).strip():
            bad.append(f"{k}: text required")
    if not isinstance(d.get("version"), int) or d.get("version") < 1:
        bad.append("version: integer >= 1")
    if not isinstance(d.get("community", False), bool):
        bad.append("community: true/false")
    tax = d.get("tax")
    if not isinstance(tax, dict):
        bad.append("tax: object required")
    else:
        for k in PACK_TAX_KEYS:
            v = tax.get(k)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0 or v > 100:
                bad.append(f"tax.{k}: number 0..100")
        if tax.get("exempt") not in (0, 0.0):
            bad.append("tax.exempt: must be 0")
        labels = tax.get("labels")
        if not isinstance(labels, dict) or any(not isinstance(labels.get(lg), dict) or any(not isinstance(labels[lg].get(k), str) for k in PACK_TAX_KEYS) for lg in PACK_LANGS):
            bad.append("tax.labels: de/en with standard/reduced/exempt")
        if not _text_pair(tax.get("exempt_note")):
            bad.append("tax.exempt_note: de/en")
    fm = d.get("formats")
    if not isinstance(fm, dict) or not isinstance(fm.get("date"), str) or fm.get("decimal") not in (",", ".") \
            or fm.get("thousands") not in (".", ",", " ", "'", "") or fm.get("currency_pos") not in ("before", "after"):
        bad.append("formats: date, decimal (, or .), thousands, currency_pos (before|after)")
    rf = d.get("required_fields")
    if not isinstance(rf, list) or any(not isinstance(x, str) for x in rf):
        bad.append("required_fields: list of texts")
    lb = d.get("labels")
    if not isinstance(lb, dict):
        bad.append("labels: object required")
    else:
        for lg in PACK_LANGS:
            L = lb.get(lg)
            if not isinstance(L, dict):
                bad.append(f"labels.{lg}: object required")
                continue
            for k in PACK_LABEL_KEYS:
                if k == "units":
                    if not isinstance(L.get("units"), dict) or any(not isinstance(L["units"].get(u), str) for u in ("day", "hour", "piece", "minute", "flat")):
                        bad.append(f"labels.{lg}.units: day/hour/piece/minute/flat")
                elif not isinstance(L.get(k), str) or not L[k]:
                    bad.append(f"labels.{lg}.{k}: text required")
    tx = d.get("texts")
    if not isinstance(tx, dict):
        bad.append("texts: object required")
    else:
        for k in PACK_TEXT_KEYS:
            if not _text_pair(tx.get(k)):
                bad.append(f"texts.{k}: de/en")
        for k in PACK_RIGHTS_KINDS:
            lst = tx.get(k)
            if not isinstance(lst, list) or not lst or any(not isinstance(x, dict) or not isinstance(x.get("key"), str)
                                                           or not x["key"] or not _text_pair(x) for x in lst):
                bad.append(f"texts.{k}: list of {{key, de, en}}")
            elif len({x["key"] for x in lst}) != len(lst):
                bad.append(f"texts.{k}: keys must be unique")
    nb = d.get("numbering")
    if nb is not None and (not isinstance(nb, dict) or any(not isinstance(v, str) for v in nb.values())):
        bad.append("numbering: object of texts")
    ev = d.get("einvoice")
    if ev is not None and (not isinstance(ev, dict) or not isinstance(ev.get("formats"), list) or ev.get("status") not in ("planned", "ready")):
        bad.append("einvoice: {formats: [], status: planned|ready}")
    ft = d.get("features")
    if ft is not None:
        if not isinstance(ft, dict):
            bad.append("features: object {key: {status}}")
        else:
            for k, v in ft.items():
                if k not in PACK_FEATURES and k not in PACK_FEATURES_PLANNED:
                    bad.append(f"features.{k}: unknown function")
                elif not isinstance(v, dict) or v.get("status") not in PACK_FEATURE_STATUS:
                    bad.append(f"features.{k}: {{status: planned|ready}}")
                elif k in PACK_FEATURES_PLANNED and v.get("status") != "planned":
                    bad.append(f"features.{k}: planned only")
    rt = d.get("retention")
    if rt is not None:
        if not isinstance(rt, dict) or any(not isinstance(rt.get(k), int) or isinstance(rt.get(k), bool) or not 1 <= rt[k] <= RETENTION_MAX
                                           for k in ("receipts", "books")) \
                or not isinstance(rt.get("editable", False), bool) \
                or not isinstance(rt.get("min_years", 1), int) or not 1 <= rt.get("min_years", 1) <= RETENTION_MAX:
            bad.append(f"retention: {{receipts, books: years 1..{RETENTION_MAX}, min_years, editable}}")
    if tax is not None and isinstance(tax, dict) and not isinstance(tax.get("editable", False), bool):
        bad.append("tax.editable: true/false")
    if not isinstance(d.get("neutral", False), bool):
        bad.append("neutral: true/false")
    if not isinstance(d.get("currency_editable", False), bool):  # 2.189.0 (#2475): the office chooses its home currency
        bad.append("currency_editable: true/false")
    bk = d.get("bookkeeping")
    if bk is not None and (not isinstance(bk, dict) or not isinstance(bk.get("export"), str) or bk.get("status") not in ("planned", "ready")):
        bad.append("bookkeeping: {export, status: planned|ready}")
    # no code, no markup: every text is plain (a pack is data like a language file)
    for path, s in _strings(d):
        if "<" in s and ">" in s or "javascript:" in s.lower():
            bad.append(f"{path}: markup is not allowed")
            break
    return bad


def _text_pair(v):
    return isinstance(v, dict) and all(isinstance(v.get(lg), str) and v[lg] for lg in PACK_LANGS)


def _strings(d, path="pack"):
    if isinstance(d, str):
        yield path, d
    elif isinstance(d, dict):
        for k, v in d.items():
            yield from _strings(v, f"{path}.{k}")
    elif isinstance(d, list):
        for i, v in enumerate(d):
            yield from _strings(v, f"{path}[{i}]")


def pack_features(d):
    """2.147.0 (#2459): {key: "ready"|"planned"} the pack offers. A pack without "features" (built before 2.147, e.g. an
    installed community pack) offers what its einvoice / bookkeeping blocks say + the neutral export + the finalising rules."""
    d = d or {}
    ft = d.get("features")
    if isinstance(ft, dict):
        return {k: v.get("status") for k, v in ft.items() if isinstance(v, dict) and (k in PACK_FEATURES or k in PACK_FEATURES_PLANNED)}
    # (review 2.147.0: an office on such a pack had the VAT return figures and tax dates before -- they stay)
    out = {"books.export_csv": "ready", "books.gobd": "ready", "books.vat_return": "ready", "books.tax_dates": "ready"}
    ev, bk = d.get("einvoice") or {}, d.get("bookkeeping") or {}
    if ev.get("formats"):
        out["docs.einvoice"] = ev.get("status") or "planned"
    if bk.get("export") == "datev":
        out["books.datev"] = bk.get("status") or "planned"
    return out


def office_features(s, pack=None):
    """2.147.0 (#2459, #2460): {key: True|False} for every function of PACK_FEATURES in an office area with settings s: the
    pack offers it as ready AND (it cannot be switched off OR it is not in s["features_off"]). Server routes check this,
    the client only hides what is off."""
    pack = pack if pack is not None else office_pack_for(s)
    offered = pack_features(pack)
    off = set((s or {}).get("features_off") or [])
    return {k: offered.get(k) == "ready" and (not m["switch"] or k not in off) for k, m in PACK_FEATURES.items()}


def office_feature_on(s, key, pack=None):
    return bool(office_features(s, pack).get(key))


def pack_retention(pack, s=None):
    """2.147.0 (#2459, #2461): {"receipts": years, "books": years, "editable", "min_years"} of an office area: the pack's
    values; an editable pack takes the office's retention_years (never below min_years)."""
    rt = dict(RETENTION_DEFAULT)
    if isinstance((pack or {}).get("retention"), dict):
        rt.update({k: v for k, v in pack["retention"].items() if k in RETENTION_DEFAULT})
        rt.setdefault("min_years", 1)
    own = (s or {}).get("retention_years")
    if rt.get("editable") and isinstance(own, int) and not isinstance(own, bool) and own > 0:
        y = max(int(rt.get("min_years") or 1), min(own, RETENTION_MAX))
        rt["receipts"] = rt["books"] = y
    return rt


def office_pack_for(s):
    """2.147.0 (#2461): the country pack an office area with settings s works with (DE when its pack is gone, as before).
    A pack with tax.editable (the neutral base pack) takes the office's own rates (settings tax_rates {standard, reduced});
    its tax labels may hold {rate}. Documents finalised before keep their snapshot (ledger.ofx_finalize)."""
    pack = office_pack((s or {}).get("pack")) or office_pack("DE")
    if not pack:
        return pack
    tax = pack.get("tax") or {}
    if not tax.get("editable"):
        return pack
    own = (s or {}).get("tax_rates") or {}
    p = json.loads(json.dumps(pack))
    t = p["tax"]
    for k in ("standard", "reduced"):
        v = own.get(k) if isinstance(own, dict) else None
        if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 100:
            t[k] = v
    for lg, L in (t.get("labels") or {}).items():
        for k in PACK_TAX_KEYS:
            if isinstance(L.get(k), str):
                L[k] = L[k].replace("{rate}", _rate_text(t.get(k), lg))
    return p


def _rate_text(v, lg):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return ""
    txt = f"{v:.2f}".rstrip("0").rstrip(".")
    return txt.replace(".", ",") if lg == "de" else txt


def office_pack_public(d):
    """What the app shows of a pack (the whole data pack: it holds nothing private)."""
    return d
