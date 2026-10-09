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


def office_pack_codes():
    """The codes of the packs shipped with the app (upper case, sorted)."""
    out = []
    for f in sorted(os.listdir(PACK_DIR)) if os.path.isdir(PACK_DIR) else []:
        if f.endswith(".json") and _CODE_RE.match(f[:-5].upper()):
            out.append(f[:-5].upper())
    return out


def office_pack(code):
    """The country pack dict for code ("DE"), or None when there is none. Cached per process (packs are files)."""
    code = (code or "").strip().upper()
    if not _CODE_RE.match(code):
        return None
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


def office_pack_public(d):
    """What the app shows of a pack (the whole data pack: it holds nothing private)."""
    return d
