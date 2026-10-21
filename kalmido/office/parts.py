"""2.47.0 (#1215): parts of a quotation (Teilangebote) -- sub pages behind the title page.

A quotation may have parts (office_doc_parts): kind 'items' = positions of their own (office_doc_items.part_id) with the
document's calculation (producing, raw data, discount; the part's settings override the document's values), kind 'shoot'
= the shoot calculation sheet of office/sheet.py (#1216). The title page refers to a part with a position of kind 'part'
(ref_part_id, qty): it counts the part's net x qty, its tax bases per rate x qty, its raw data x qty (optional stays
optional, included stays included) and its purchase x qty. A part nobody refers to counts nothing. A quotation without
parts is computed by office_calc exactly as before (doc_totals only calls tp_doc_totals for documents with parts).
Purchase / surplus (costs, margin) only for the organisation's admins (callers strip them for members)."""
import json
import math
from decimal import Decimal

from flask import jsonify

from ..core.config import app
from ..core.db import body, bump, err, iso, now_utc
from ..core.access import Denied
from ..core.i18n import N_, tr
from ..core.pg import insert_id
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields, oc_item_store, oc_json_load, oc_json_store
from ..core.errors import BadInput
from .calc import RAW_MODES, TAX_KEYS, dec, fmt_money, fmt_qty, label, money, office_calc, pack_tax, unit_text, _num
from .model import UNITS, office_role, office_settings
from .packs import office_pack_for

try:  # the shoot calculation (part C, office/sheet.py); until it is there a shoot part counts nothing
    from . import sheet as _dk_sheet
except ImportError:  # pragma: no cover
    _dk_sheet = None

PART_KINDS = ("items", "shoot")
MAX_PARTS = 60
PART_SETTING_KEYS = ("raw_mode", "raw_factor", "prod_quotient", "producing_rate", "producing_on", "discount_pct")
INVOICE_MODES = ("full", "title", "summary")
D0 = Decimal(0)


def _dk(name):
    fn = getattr(_dk_sheet, name, None) if _dk_sheet is not None else None
    return fn if callable(fn) else None


def tp_shoot_ok(c=None, oid=None):
    """True when the shoot calculation (part C) is there and switched on for the organisation (dk_enabled): only then a
    part of kind 'shoot' may be created."""
    if _dk("dk_sheet_clean") is None or _dk("dk_sheet_calc") is None:
        return False
    en = _dk("dk_enabled")
    return en is None or c is None or bool(en(office_settings(c, oid)))


def _sheet_store(c, oid, sheet):
    """The sheet column as stored: JSON text, encrypted as a whole when the organisation key is on (orgcrypt FIELDS)."""
    return oc_enc_fields(c, oid, "office_doc_parts", {"sheet": json.dumps(sheet, ensure_ascii=False, default=str)})["sheet"]


def _j(s, default):
    if isinstance(s, type(default)):
        return s
    try:
        v = json.loads(s) if s else default
    except (TypeError, ValueError):
        return default
    return v if isinstance(v, type(default)) else default


# ---------------------------------------------------------------- rows
def tp_parts(c, oid, did):
    """The parts of document did in order (dicts; settings / sheet parsed, totals decrypted)."""
    out = []
    for r in c.execute("SELECT * FROM office_doc_parts WHERE doc_id=? AND org_id=? ORDER BY sort, id", (did, oid)):
        p = oc_dec_fields(c, oid, "office_doc_parts", r)
        p["settings"] = _j(p.get("settings"), {})
        p["sheet"] = _j(p.get("sheet"), {})
        p["totals"] = oc_json_load(c, oid, "office_doc_parts", "totals", _j(p.get("totals"), {}))
        p["print"] = int(p.get("print") or 0)
        out.append(p)
    return out


def tp_has_parts(c, oid, did):
    return c.execute("SELECT 1 FROM office_doc_parts WHERE doc_id=? AND org_id=? LIMIT 1", (did, oid)).fetchone() is not None


def tp_part(c, oid, did, pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        raise Denied(404)
    for p in tp_parts(c, oid, did):
        if p["id"] == pid:
            return p
    raise Denied(404)


def _part_items(c, oid, did, pid):
    from .docs import doc_items
    return doc_items(c, did, oid, part=pid)


def tp_part_items_all(c, oid, did):
    """The positions of all parts of document did (for the language switch of doclang)."""
    return [oc_dec_fields(c, oid, "office_doc_items", r)
            for r in c.execute("SELECT * FROM office_doc_items WHERE doc_id=? AND org_id=? AND part_id IS NOT NULL ORDER BY part_id, sort, id", (did, oid))]


def tp_settings_clean(v, cur=None, share=False):
    """The part's own calculation values; a key with None / '' falls back to the document's value (removed).
    2.113.1 (#2251): share = the document computes "share by amount": prod_quotient is its factor (0.01..10)."""
    if not isinstance(v, dict):
        raise BadInput(tr("Invalid value: {0}", "settings"))
    out = dict(cur or {})
    for k, x in v.items():
        if k not in PART_SETTING_KEYS:
            continue
        if x is None or x == "":
            out.pop(k, None)
            continue
        if k == "raw_mode":
            if x not in RAW_MODES:
                raise BadInput(tr("Invalid value: {0}", "settings.raw_mode"))
            out[k] = x
        elif k == "producing_on":
            out[k] = 1 if x in (1, True, "1", "true") else 0
        else:  # 2.113.1 (#2251): prod_quotient from 0.01 (the factor of "share by amount")
            lo, hi = {"raw_factor": (0, 100), "prod_quotient": (0.01, 1000), "producing_rate": (0, 1e9), "discount_pct": (0, 100)}[k]
            try:
                n = float(dec(x, "nan"))
            except (ValueError, ArithmeticError):
                n = float("nan")
            if not (lo <= n <= hi) or share and k == "prod_quotient" and n > 10:
                raise BadInput(tr("Invalid value: {0}", "settings." + k))
            out[k] = n
    return out


# ---------------------------------------------------------------- calculating
def _doc_calc(r, eur=False):
    from .docs import _calc_doc
    d = _calc_doc(r)
    if "producing_on" in r.keys():  # 2.47.0 (#1645, part D): the document's producing switch, when it has one
        d.setdefault("producing_on", r["producing_on"])
    if eur:
        d["currency"] = "EUR"
    return d


def _bases(t, novat):
    """The tax bases per rate of a calculator result (after its discount); without VAT everything counts as standard."""
    if novat:
        return {"standard": dec(t.get("net"))}
    b = {k: D0 for k in TAX_KEYS}
    for tl in t.get("tax_lines") or []:
        if tl.get("rate_key") in b:
            b[tl["rate_key"]] += dec(tl.get("base"))
    rest = dec(t.get("net")) - sum(b.values())  # rounding safety: the bases always add up to the net
    if rest:
        b["standard"] += rest
    return {k: v for k, v in b.items() if v}


def tp_part_calc(c, oid, r, p, pack, eur=False):
    """The calculation of one part: office_calc over its positions with the document's values overridden by the part's
    settings; a shoot part through dk_sheet_calc (part C). Adds "bases" {rate key: net} and "kind"."""
    # the document's values unless the part has its own; not its discount: that one applies to the part lines of the title page
    doc = {**_doc_calc(r, eur), "discount_pct": 0, **(p.get("settings") or {})}
    novat = str(doc.get("vat_mode") or "vat") == "novat"
    if p["kind"] == "shoot":
        fn = _dk("dk_sheet_calc")
        t = None
        if fn is not None:
            try:
                fx = dec(doc.get("fx_rate"), "1.09") if str(doc.get("currency") or "EUR").upper() == "USD" else Decimal(1)
                t = fn(p.get("sheet") or {}, None, doc.get("lang") or "de", doc.get("currency") or "EUR", fx)  # None: the sheet's own pack
            except Exception:  # noqa: BLE001 -- a broken sheet must not break the whole quotation
                t = None
        t = dict(t or {})
        net = money(dec(t.get("net")))
        base = {k: money(dec(v)) for k, v in (t.get("base") or {}).items() if k in TAX_KEYS and dec(v)}
        if novat or not base:
            base = {"standard": net} if net else {}
        out = {"net": _num(net), "costs": _num(money(dec(t.get("costs")))), "raw_amount": 0, "raw_mode": "none", "net_incl_raw": None,
               "net_excl_raw": None, "lines": t.get("lines") or [], "labels": t.get("labels") or {}, "sheet_calc": t}
        out["margin"] = _num(net - dec(out["costs"]))
    else:
        out = office_calc(doc, _part_items(c, oid, r["id"], p["id"]), pack)
        base = _bases(out, novat)
    out["kind"] = p["kind"]
    out["bases"] = {k: _num(v) for k, v in base.items()}
    return out


def f8b_qty_bases(bases, qty):
    """2.58.0 (#1759): a part's tax bases x qty that add up to exactly money(net x qty), the title line's rate x qty:
    every rate rounded on its own, the rest cent on the last rate (1.5 x 110.01 + 1.5 x 50.01 would be a cent more)."""
    pb = {tk: money(dec(v) * qty) for tk, v in bases.items()}
    if len(pb) > 1:
        pb[list(pb)[-1]] += money(sum((dec(v) for v in bases.values()), D0) * qty) - sum(pb.values(), D0)
    return pb


def f8b_fix_cents(rows, want, lang="de"):
    """2.58.0 (#1759): invoice positions made from a part (x a fractional qty) round every position on its own; per tax
    rate their sum must equal the part line's amount on the title page (want: {rate key: amount}). The rest cent goes
    on the last position of that rate, which then becomes one flat amount (its qty x rate stays in the detail)."""
    have = {}
    for x in rows:
        if x.get("kind") not in ("service", "discount"):
            continue
        if x.get("unit") == "percent":
            return rows  # its amount depends on the whole invoice: leave as before
        v = money(dec(x.get("qty"), "1") * money(dec(x.get("rate"))))
        have[x.get("tax")] = have.get(x.get("tax"), D0) + (-v if x["kind"] == "discount" else v)
    for k, w in (want or {}).items():
        diff = money(dec(w)) - have.get(k, D0)
        last = next((x for x in reversed(rows) if x.get("kind") == "service" and x.get("tax") == k), None)
        if not diff or last is None or abs(diff) > Decimal("0.05"):
            continue
        q, rate = dec(last.get("qty"), "1"), money(dec(last.get("rate")))
        last.update(qty=_num(1), unit="flat", rate=_num(money(q * rate) + diff),
                    detail=" · ".join(t for t in (f"{fmt_qty(q, lang)} × {fmt_money(rate, lang)}", last.get("detail") or "") if t))
    return rows


def _dominant(bases):
    return max(bases, key=lambda k: abs(dec(bases[k]))) if bases else "standard"


def tp_doc_totals(c, oid, r, items, pack, eur=False):
    """The totals of quotation r with parts (None: it has none -> office_calc as before). items: its title page positions.
    Part lines (kind 'item' with part_id) carry the part's net x qty; producing of the title page counts only its direct
    positions; the title page's discount takes in part lines marked discountable."""
    parts = tp_parts(c, oid, r["id"])
    if not parts:
        return None
    pmap = {p["id"]: p for p in parts}
    calcs = {p["id"]: tp_part_calc(c, oid, r, p, pack, eur) for p in parts}
    doc = _doc_calc(r, eur)
    lang = "en" if str(doc.get("lang") or "de").lower().startswith("en") else "de"
    currency = "USD" if str(doc.get("currency") or "EUR").upper() == "USD" else "EUR"
    novat = str(doc.get("vat_mode") or "vat") == "novat"
    rates = {k: (D0 if novat else pack_tax(pack, k)) for k in TAX_KEYS}
    ph, refs = [], {}
    for n, it in enumerate(items or []):
        if (it.get("kind") or "service") == "part":
            key = f"tp{n}"
            refs[key] = it
            ph.append({**it, "kind": "service", "id": key, "rate": 0, "cost": 0, "raw_fee": 0, "producing": 0, "discountable": 0})
        else:
            ph.append(it)
    t = office_calc(doc, ph, pack)
    base = {k: D0 for k in TAX_KEYS}
    disc_base = {k: D0 for k in TAX_KEYS}
    items_net, costs = D0, dec(t["costs"])
    raw_opt, raw_inc, raw_own = D0, D0, D0  # raw_own: the title page's own included raw data (the parts' is inside their nets)
    lines = []
    for ln in t["lines"]:
        k = ln["kind"]
        if k == "discount":
            continue  # computed again below over the direct positions and the part lines
        if k == "item" and ln.get("id") in refs:
            it = refs[ln["id"]]
            p = pmap.get(it.get("ref_part_id"))
            pc = calcs.get(it.get("ref_part_id")) or {"net": 0, "bases": {}, "costs": 0, "raw_amount": 0}
            qty = dec(it.get("qty"), "1")
            pb = f8b_qty_bases(pc.get("bases") or {}, qty)  # 2.58.0 (#1759): adds up to rate x qty
            total = sum(pb.values(), D0)
            for tk, v in pb.items():
                base[tk] += v
                if _flag(it.get("discountable", 1)):
                    disc_base[tk] += v
            costs += money(dec(pc.get("costs")) * qty)
            if pc.get("net_incl_raw") is not None:
                raw_opt += money(dec(pc.get("raw_amount")) * qty)
            if pc.get("net_excl_raw") is not None:
                raw_inc += money(dec(pc.get("raw_amount")) * qty)
            tax = _dominant(pc.get("bases") or {})
            ln = {**ln, "id": it.get("id"), "service_id": None, "part_id": it.get("ref_part_id"), "part_kind": (p or {}).get("kind") or "items",
                  "title": it.get("title") or (p or {}).get("title") or "", "rate": _num(money(dec(pc.get("net")))), "total": _num(total), "tax": tax,
                  "tax_pct": _num(rates[tax]), "mixed_tax": len(pb) > 1, "taxes": {tk: _num(v) for tk, v in pb.items()},
                  "discountable": 1 if _flag(it.get("discountable", 1)) else 0, "intext": "intern", "raw_fee": 0, "producing": 0,
                  "counts": p is not None}
            items_net += total
        elif k == "item":
            items_net += dec(ln["total"])
            base[ln["tax"]] += dec(ln["total"])
            if ln.get("discountable"):
                disc_base[ln["tax"]] += dec(ln["total"])
        elif k in ("producing", "surcharge"):  # 2.113.1 (#2252): + surcharge
            base["standard"] += dec(ln["total"])
        elif k == "raw":
            if ln.get("optional"):
                raw_opt += dec(ln["total"])
            else:
                raw_inc += dec(ln["total"])
                raw_own += dec(ln["total"])
                base["standard"] += dec(ln["total"])
            continue  # one raw line per mode, made again below with the parts' raw data
        lines.append(ln)
    raw_title = next((x for x in t["lines"] if x["kind"] == "raw"), None)
    for opt, amt in ((False, raw_own), (True, raw_opt)):
        if amt <= 0:
            continue
        own = raw_title if raw_title is not None and bool(raw_title.get("optional")) == opt else None
        if own is not None:
            lines.append({**own, "rate": _num(amt), "total": _num(amt)})
        else:
            lines.append({"kind": "raw", "optional": opt, "title": label(pack, lang, "raw_optional" if opt else "raw_included"),
                          "qty": None if opt else 1, "qty_text": "" if opt else "1", "unit": "flat", "unit_text": "", "rate": _num(amt),
                          "tax": "standard", "tax_pct": _num(rates["standard"]), "total": _num(amt), "detail": "", "parts": True})
    disc_pct = dec(doc.get("discount_pct"), "0")
    discount = D0
    if disc_pct > 0:
        for tk in TAX_KEYS:
            d = money(disc_base[tk] * disc_pct / 100)
            base[tk] -= d
            discount += d
        if discount > 0:
            lines.append({"kind": "discount", "title": label(pack, lang, "discount"), "pct": _num(disc_pct), "total": _num(-discount),
                          "detail": label(pack, lang, "discount_detail", pct=fmt_qty(disc_pct, lang)),
                          "taxes": {tk: _num(money(disc_base[tk] * disc_pct / 100)) for tk in TAX_KEYS if disc_base[tk]}})
    net = sum(base.values(), D0)
    tax_lines, tax_sum = [], D0
    if not novat:
        for tk in TAX_KEYS:
            if base[tk] == 0:
                continue
            amt = money(base[tk] * rates[tk] / 100)
            tax_sum += amt
            tax_lines.append({"rate_key": tk, "pct": _num(rates[tk]), "base": _num(base[tk]), "amount": _num(amt),
                              "label": label(pack, lang, "tax_" + tk, pct=fmt_qty(rates[tk], lang))})
    out = dict(t)
    out.update(lines=lines, items_net=_num(items_net), discount=_num(discount), net=_num(net), tax_lines=tax_lines, tax_total=_num(tax_sum),
               gross=_num(net + tax_sum), raw_amount=_num(raw_opt + raw_inc),
               net_incl_raw=_num(net + raw_opt) if raw_opt > 0 else None, net_excl_raw=_num(net - raw_inc) if raw_inc > 0 else None,
               costs=_num(costs), margin=_num(net - costs), currency=currency,
               parts={str(pid): {"net": pc["net"], "bases": pc["bases"]} for pid, pc in calcs.items()})
    out["_part_calcs"] = calcs  # for the callers in this module; doc_totals pops it
    return out


NF_INTERNAL = ("cost", "markup_pct", "intext", "costs", "margin")


def nf_shoot_public(calc):
    """A shoot calculation without its purchase side (costs, margin, cost / markup / intern-extern per line)."""
    pub = _dk("dk_calc_public")
    out = dict(pub(calc, False)) if pub is not None else {k: v for k, v in calc.items() if k not in ("costs", "margin")}
    out["lines"] = [{k: v for k, v in ln.items() if k not in NF_INTERNAL} for ln in out.get("lines") or []]
    return out


def _flag(v):
    return v not in (None, 0, "0", "", False, "false", "off")


def tp_recalc(c, oid, r, pack=None):
    """After any change: caches every part's totals (costs / margin encrypted) and gives every title page position of
    kind 'part' the part's net as its rate and the main tax (so an older version shows plausible sums)."""
    parts = tp_parts(c, oid, r["id"])
    if not parts:
        return
    if pack is None:
        s = office_settings(c, oid)
        pack = office_pack_for(s)
    nets = {}
    for p in parts:
        t = tp_part_calc(c, oid, r, p, pack)
        if t.get("sheet_calc") is not None:  # 2.47.0 (#1216): cache only the public side (prints a finalised quotation), never purchase / markup
            sc = nf_shoot_public(t["sheet_calc"])
            t["sheet_calc"], t["lines"] = sc, sc.get("lines") or []
        nets[p["id"]] = (t["net"], _dominant(t.get("bases") or {}))
        c.execute("UPDATE office_doc_parts SET totals=? WHERE id=? AND org_id=?",
                  (json.dumps(oc_json_store(c, oid, "office_doc_parts", "totals", t), ensure_ascii=False, default=str), p["id"], oid))
    for it in c.execute("SELECT id, ref_part_id FROM office_doc_items WHERE doc_id=? AND org_id=? AND kind='part' AND part_id IS NULL",
                        (r["id"], oid)).fetchall():
        if it["ref_part_id"] in nets:
            net, tax = nets[it["ref_part_id"]]
            c.execute("UPDATE office_doc_items SET rate=?, tax=? WHERE id=? AND org_id=?", (net, tax, it["id"], oid))


def tp_clean_item(c, oid, r, it, i, prev):
    """A title page position of kind 'part' (the part it stands for, qty; title defaults to the part's title)."""
    from .docs import _num as num_in, _text
    try:
        pid = int(it.get("ref_part_id"))
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", "items.ref_part_id"))
    p = c.execute("SELECT id, title, totals FROM office_doc_parts WHERE id=? AND doc_id=? AND org_id=?", (pid, r["id"], oid)).fetchone()
    if not p:
        raise Denied(404)
    qty = num_in(it.get("qty"), "items.qty", 0, 1e6)
    unit = it.get("unit") or "piece"
    if unit not in UNITS:
        raise BadInput(tr("Invalid value: {0}", "items.unit"))
    net = _j(p["totals"], {}).get("net") or 0
    return {"sort": i, "kind": "part", "service_id": None, "ref_part_id": pid, "title": _text(it.get("title"), "items.title", 500) or p["title"] or "",
            "detail": _text(it.get("detail"), "items.detail", 4000), "qty": 1 if qty is None else qty, "unit": unit, "rate": net,
            "tax": (prev or {}).get("tax") or "standard", "raw_fee": 0, "producing": 0, "intext": "intern", "cost": 0,
            "discountable": 0 if it.get("discountable") in (0, False, "0", "false") else 1}


def kva_keep_unseen_parts(c, oid, r, before, known):
    """2.138.0 A (#2239): a title page save whose list was built before a part was added (the editor sends the ids of the
    parts it knew, parts_known) keeps the title page line of every part it did not know. Without parts_known (API,
    older clients) the list is taken as it is."""
    from .docs import DUP_ITEM_SKIP
    if r["kind"] != "offer" or not isinstance(known, list):
        return
    known = {int(x) for x in known if (isinstance(x, int) and not isinstance(x, bool)) or (isinstance(x, str) and x.isdigit())}
    have = {x["ref_part_id"] for x in c.execute("SELECT ref_part_id FROM office_doc_items WHERE doc_id=? AND org_id=? AND kind='part' "
                                                "AND part_id IS NULL", (r["id"], oid)).fetchall()}
    parts = {x["id"] for x in c.execute("SELECT id FROM office_doc_parts WHERE doc_id=? AND org_id=?", (r["id"], oid)).fetchall()}
    mx = c.execute("SELECT MAX(sort) FROM office_doc_items WHERE doc_id=? AND org_id=? AND part_id IS NULL", (r["id"], oid)).fetchone()[0]
    sort = (mx if mx is not None else -1) + 1
    for it in before:
        pid = it.get("ref_part_id")
        if it.get("kind") != "part" or pid in known or pid in have or pid not in parts:
            continue
        row = {k: v for k, v in it.items() if k not in DUP_ITEM_SKIP}
        row.update(sort=sort, doc_id=r["id"], org_id=oid)
        row = oc_item_store(c, oid, row)
        c.execute(f"INSERT INTO office_doc_items({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
        have.add(pid)
        sort += 1


# ---------------------------------------------------------------- the API answer
def tp_public(c, oid, r, admin, totals=None):
    """parts: [{id, kind, title, print, sort, settings, items, totals, used, sheet?, calc?}] -- costs / margin / position
    costs only for admins."""
    parts = tp_parts(c, oid, r["id"])
    used = {}
    for row in c.execute("SELECT ref_part_id, qty FROM office_doc_items WHERE doc_id=? AND org_id=? AND kind='part' AND part_id IS NULL",
                         (r["id"], oid)):
        used[row["ref_part_id"]] = used.get(row["ref_part_id"], 0) + 1
    out = []
    for p in parts:
        t = dict(p["totals"])
        if not admin:
            for k in ("costs", "margin"):
                t.pop(k, None)
            # 2.47.0 (#1216): defensive -- no purchase, markup or intern / extern per line for members
            t["lines"] = [{k: v for k, v in ln.items() if k not in NF_INTERNAL} if isinstance(ln, dict) else ln for ln in t.get("lines") or []]
        t.pop("sheet_calc", None)
        q = {"id": p["id"], "kind": p["kind"], "title": p["title"], "print": p["print"], "sort": p["sort"], "settings": p["settings"],
             "totals": t, "used": used.get(p["id"], 0)}
        if p["kind"] == "items":
            its = _part_items(c, oid, r["id"], p["id"])
            for it in its:
                it["discountable"] = int(it.get("discountable") or 0)
                if not admin:
                    it.pop("cost", None)  # members never get the purchase price (as the title page, part D)
            q["items"] = its
        else:
            q["items"] = []
            pub = _dk("dk_sheet_public")
            q["sheet"] = pub(p["sheet"], admin) if pub is not None else p["sheet"]
            q["calc"] = _shoot_calc_public(c, oid, r, p, admin)
        out.append(q)
    return out


def _shoot_calc_public(c, oid, r, p, admin):
    """The shoot calculation of part p for the editor (C's dk_calc_public strips the purchase side for members)."""
    s = office_settings(c, oid)
    pack = office_pack_for(s)
    t = tp_part_calc(c, oid, r, p, pack)
    calc = dict(t.get("sheet_calc") or {})
    pub = _dk("dk_calc_public")
    if pub is not None:
        return pub(calc, admin)
    if not admin:
        calc.pop("costs", None)
        calc.pop("margin", None)
    return calc


# ---------------------------------------------------------------- copying (duplicate)
def tp_duplicate(c, oid, did, nid):
    """Copies the parts of document did (with their positions) into the new document nid and points nid's title page
    positions of kind 'part' to the copies."""
    from .docs import DUP_ITEM_SKIP
    ts = iso(now_utc())
    pmap = {}
    for p in c.execute("SELECT * FROM office_doc_parts WHERE doc_id=? AND org_id=? ORDER BY sort, id", (did, oid)).fetchall():
        row = {k: p[k] for k in p.keys() if k not in ("id", "doc_id", "created_at", "updated_at")}
        row.update(doc_id=nid, created_at=ts, updated_at=ts)
        pmap[p["id"]] = insert_id(c, f"INSERT INTO office_doc_parts({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
        for it in _part_items(c, oid, did, p["id"]):
            it = {k: v for k, v in it.items() if k not in DUP_ITEM_SKIP}
            it.update(doc_id=nid, org_id=oid, part_id=pmap[p["id"]])
            it = oc_item_store(c, oid, it)
            c.execute(f"INSERT INTO office_doc_items({','.join(it)}) VALUES({','.join('?' * len(it))})", list(it.values()))
    for old, new in pmap.items():
        c.execute("UPDATE office_doc_items SET ref_part_id=? WHERE doc_id=? AND org_id=? AND kind='part' AND ref_part_id=?", (new, nid, oid, old))


# ---------------------------------------------------------------- the print model
def tp_render(c, oid, r, m, pack, lang, locked):
    """Adds m["parts"]: the printed parts as own pages [{title, number, kind, lines, totals {rows, raw_opt}}] and marks
    the title page's part lines. A finalised quotation prints its parts from their cached totals."""
    if r["kind"] != "offer":
        return
    parts = tp_parts(c, oid, r["id"])
    if not parts:
        return
    cur = r["currency"]
    L = (pack.get("labels") or {}).get(lang) or {}
    used = {x["ref_part_id"] for x in c.execute("SELECT ref_part_id FROM office_doc_items WHERE doc_id=? AND org_id=? AND kind='part' AND part_id IS NULL",
                                                   (r["id"], oid))}
    out = []
    for p in parts:
        if not p["print"] or p["id"] not in used:  # a part not on the title page counts nothing and is not printed
            continue
        pc = p["totals"] if locked else tp_part_calc(c, oid, r, p, pack)
        if p["kind"] == "shoot":
            fn = _dk("dk_sheet_print")
            pr = None
            if fn is not None and pc.get("sheet_calc") is not None:
                try:
                    pr = fn(pc["sheet_calc"], lang)
                except Exception:  # noqa: BLE001
                    pr = None
            pr = pr or {}
            lines = []
            for x in pr.get("rows") or []:
                k = x.get("kind")
                if k == "group":
                    lines.append({"kind": "heading", "title": x.get("label") or ""})
                elif k == "note":
                    lines.append({"kind": "text", "text": x.get("label") or ""})
                else:
                    lines.append({"kind": "item", "title": x.get("label") or "", "qty_text": x.get("qty_text") or "", "unit_text": "",
                                  "rate_text": x.get("rate_text") or "", "total_text": x.get("total_text") or "", "bold": k == "sum"})
            rows = [[str(a), str(b)] for a, b in (pr.get("totals") or [])] or [[L.get("net_total", label(pack, lang, "net")), fmt_money(pc.get("net") or 0, lang, cur)]]
            head = pr.get("head") or (pc.get("sheet_calc") or {}).get("head_print") or []
            out.append({"id": p["id"], "kind": "shoot", "title": p["title"] or pr.get("title") or "", "head": head, "lines": lines,
                        "totals": {"rows": rows, "raw_opt": None}})
            continue
        lines = []
        for ln in pc.get("lines") or []:
            ln = dict(ln)
            if ln["kind"] in ("item", "producing", "surcharge", "raw", "discount"):  # 2.113.1 (#2252): + surcharge
                ln["total_text"] = fmt_money(ln["total"], lang, cur)
                if ln.get("rate") is not None:
                    ln["rate_text"] = fmt_money(ln["rate"], lang, cur)
            lines.append(ln)
        labels = pc.get("labels") or {}
        rows = [[L.get("net_total", labels.get("net") or label(pack, lang, "net")), fmt_money(pc.get("net") or 0, lang, cur)]]
        if pc.get("net_incl_raw") is not None:
            rows.append([L.get("incl_raw", labels.get("net_incl_raw") or label(pack, lang, "net_incl_raw")), fmt_money(pc["net_incl_raw"], lang, cur)])
        if pc.get("net_excl_raw") is not None:
            rows.append([L.get("excl_raw", labels.get("net_excl_raw") or label(pack, lang, "net_excl_raw")), fmt_money(pc["net_excl_raw"], lang, cur)])
        out.append({"id": p["id"], "kind": "items", "title": p["title"], "head": [], "lines": lines, "totals": {"rows": rows}})
    m["parts"] = out
    m["part_label"] = L.get("part") or tr("Part|document", lg=lang)  # 2.149.0 A (#2520)
    for ln in m.get("lines") or []:
        if ln.get("part_id") is not None and ln.get("kind") == "item":
            ln.pop("taxes", None)
            if ln.get("mixed_tax"):  # the part has several rates: no single rate in the VAT column
                ln["tax_pct"] = None


# ---------------------------------------------------------------- invoices from a quotation with parts
def tp_inv_items(c, oid, r, mode=None, title=None):
    """The positions of an invoice from quotation r with parts (None: it has none). mode (else the office setting
    parts_invoice_mode, app default "full"): "title" = the title page with its positions, a part line becomes a position
    with its amount (one per tax rate when the part mixes rates); "summary" = one position per tax rate titled title (default
    from the settings: "Filmherstellung" / "Film production"); "full" = the title page's direct positions plus, per printed
    part, a heading and its positions (qty x part qty, producing / raw data / discount as positions); a part that is not
    printed stays one line. Net and gross equal the quotation's in every mode. Rates in EUR like inv_items_from_offer."""
    if not tp_has_parts(c, oid, r["id"]):
        return None
    from .docs import doc_items
    s = office_settings(c, oid)
    pack = office_pack_for(s)
    mode = mode or s.get("parts_invoice_mode") or "full"
    if mode not in INVOICE_MODES:
        raise BadInput(tr("Invalid value: {0}", "mode"))
    items = doc_items(c, r["id"], oid)
    t = tp_doc_totals(c, oid, r, items, pack, eur=True)
    calcs = t.pop("_part_calcs")
    lang = "en" if r["lang"] == "en" else "de"
    pmap = {p["id"]: p for p in tp_parts(c, oid, r["id"])}
    pct = {k: pack_tax(pack, k) for k in TAX_KEYS}

    def pos(title, qty, unit, rate, tax, detail="", cost=0, kind="service"):
        return {"kind": kind, "service_id": None, "title": title, "detail": detail, "qty": _num(dec(qty)), "unit": unit, "rate": _num(dec(rate)),
                "tax": tax, "intext": "intern", "cost": _num(dec(cost)), "raw_fee": 0, "producing": 0, "discountable": 1}

    def tax_word(k):
        return label(pack, lang, "tax_" + k, pct=fmt_qty(pct[k], lang))

    if mode == "summary":
        ttl = (title or "").strip()[:500] or s.get("parts_summary_title_" + lang) or tr("Film production|document", lg=lang)  # 2.149.0 A (#2520)
        out = []
        bases = {tl["rate_key"]: tl["base"] for tl in t["tax_lines"]} if t["vat_mode"] != "novat" else {"standard": t["net"]}
        for n, (k, b) in enumerate((k, bases[k]) for k in TAX_KEYS if k in bases and dec(bases[k])):
            out.append(pos(ttl, 1, "flat", b, k, detail=tax_word(k) if len(bases) > 1 else "", cost=t["costs"] if n == 0 else 0))
        return out or [pos(ttl, 1, "flat", 0, "standard")]

    def part_line(ln, it):
        """A part as positions with its amount: one per tax rate (detail names the rate when it mixes)."""
        qty = dec(it.get("qty"), "1")
        pc = calcs.get(it.get("ref_part_id")) or {}
        bs = pc.get("bases") or {}
        res = []
        for n, k in enumerate(k for k in TAX_KEYS if k in bs):
            res.append(pos(ln["title"], qty, it.get("unit") or "piece", bs[k], k, detail=tax_word(k) if len(bs) > 1 else (it.get("detail") or ""),
                           cost=pc.get("costs") if n == 0 else 0))
        return f8b_fix_cents(res, ln.get("taxes"), lang) or [pos(ln["title"], qty, it.get("unit") or "piece", 0, "standard")]

    def auto(lines, factor=Decimal(1), with_disc=True):
        res = []
        for ln in lines:
            if ln["kind"] == "producing":  # 2.113.1 (#2251): without its calculation (internal)
                res.append(pos(ln["title"], dec(ln["qty"]) * factor, "day", ln["rate"], "standard", ""))
            elif ln["kind"] == "raw" and not ln.get("optional") or ln["kind"] == "surcharge":  # 2.113.1 (#2252): + surcharge
                res.append(pos(ln["title"], factor, "flat", ln["total"], "standard", "" if ln["kind"] == "surcharge" else ln.get("detail") or ""))
            elif ln["kind"] == "discount" and with_disc:
                taxes = ln.get("taxes") or {"standard": abs(dec(ln["total"]))}
                for k in TAX_KEYS:
                    if dec(taxes.get(k)):
                        res.append(pos(ln["title"], factor, "flat", abs(dec(taxes[k])), k, ln.get("detail") or "", kind="discount"))
        return res

    by_id = {it["id"]: it for it in items}
    out = []
    for ln in t["lines"]:
        k = ln["kind"]
        if k in ("heading", "text"):
            out.append({**pos(ln.get("title") or "", 1, "day", 0, "standard", ln.get("text") or ""), "kind": k})
            continue
        if k != "item":
            continue
        it = by_id.get(ln.get("id")) or {}
        if ln.get("part_id") is None:
            row = {kk: it.get(kk) for kk in ("kind", "service_id", "title", "detail", "qty", "unit", "rate", "tax", "intext", "cost")}
            row.update(raw_fee=0, producing=0, discountable=1)
            if ln.get("pct") is not None:  # 2.47.0 (#1649): a percent position becomes its amount (as invoices.inv_items_from_offer)
                row.update(qty=1, unit="flat", rate=ln["total"])
            out.append(row)
            continue
        p = pmap.get(ln["part_id"])
        pc = calcs.get(ln["part_id"])
        if not dec(it.get("qty"), "1"):
            continue  # 2.47.0 (#1215): a part with quantity 0 adds nothing to the invoice
        if mode == "title" or p is None or pc is None or not p["print"] or p["kind"] != "items":
            out += part_line(ln, it)
            continue
        qty = dec(it.get("qty"), "1")
        start = len(out)  # 2.58.0 (#1759): the part's positions, for the rest cent below
        out.append({**pos(ln["title"] + (f" × {fmt_qty(qty, lang)}" if qty != 1 else ""), 1, "day", 0, "standard"), "kind": "heading"})
        pct_lines = {x.get("id"): x for x in pc["lines"] if x["kind"] == "item" and x.get("pct") is not None}
        for pit in _part_items(c, oid, r["id"], p["id"]):
            if (pit.get("kind") or "service") in ("heading", "text"):
                out.append({**pos(pit.get("title") or "", 1, "day", 0, "standard", pit.get("detail") or ""), "kind": pit["kind"]})
                continue
            if pit.get("unit") == "percent" and pit.get("id") in pct_lines:
                # 2.47.0 (#1649): a percent position (artists' social insurance) is its amount in the part x the part's qty;
                # the invoice would otherwise take the percentage of all its extern positions
                out.append({**pos(pit.get("title") or "", qty, "flat", pct_lines[pit["id"]]["total"], pit.get("tax") or "standard",
                                  pit.get("detail") or "", cost=pit.get("cost") or 0), "service_id": pit.get("service_id")})
                continue
            out.append({"kind": "service", "service_id": pit.get("service_id"), "title": pit.get("title") or "", "detail": pit.get("detail") or "",
                        "qty": _num(dec(pit.get("qty"), "1") * qty), "unit": pit.get("unit") or "day", "rate": pit.get("rate"), "tax": pit.get("tax") or "standard",
                        "intext": pit.get("intext") or "intern", "cost": pit.get("cost") or 0, "raw_fee": 0, "producing": 0, "discountable": 1})
        dl = next((x for x in pc["lines"] if x["kind"] == "discount"), None)
        if dl is not None:  # the part's discount per tax rate (office_calc keeps one line; the bases tell the rates)
            raw_lines = [x for x in pc["lines"] if x["kind"] != "discount"]
            dl = dict(dl)
            dl["taxes"] = _part_disc_taxes(c, oid, r, p, pc)
            out += auto(raw_lines + [dl], qty)
        else:
            out += auto(pc["lines"], qty)
        out[start:] = f8b_fix_cents(out[start:], ln.get("taxes"), lang)
    out += auto(t["lines"])
    return out


def _part_disc_taxes(c, oid, r, p, pc):
    """The discount of a part per tax rate: the same rule as office_calc (pct of the discountable positions per rate),
    from the part's calculated lines (a percent position counts with its amount, 2.47.0 #1649)."""
    pct = dec(pc.get("discount_pct"))
    res = {k: D0 for k in TAX_KEYS}
    for ln in pc.get("lines") or []:
        if ln.get("kind") != "item" or not ln.get("discountable"):
            continue
        res[ln.get("tax") if ln.get("tax") in TAX_KEYS else "standard"] += dec(ln.get("total"))
    return {k: _num(money(v * pct / 100)) for k, v in res.items() if v}


# ---------------------------------------------------------------- routes
def _ctx_doc(did):
    from .docs import _ctx, doc_row
    from .ledger import ofx_need_editable
    c, uid, oid = _ctx()
    admin = office_role(c, uid, oid) == "admin"
    r = doc_row(c, oid, did)
    if r["kind"] != "offer":
        raise Denied(409, tr("Only a quotation has parts"))
    ofx_need_editable(r)
    from .undo import oun_pre
    oun_pre(c, uid, oid, "doc", did)  # 2.111.0 A (#2233): every change of a part is a step of the document's undo
    return c, uid, oid, admin, r


def _answer(c, oid, did, admin, part=None):
    from .docs import doc_public, doc_row
    out = doc_public(c, oid, doc_row(c, oid, did), admin)
    if part is not None:
        out["part"] = next((p for p in out.get("parts") or [] if p["id"] == part), None)
        out["doc_totals"] = out.get("totals")
    return out


def _done(c, oid, r, admin, part=None, code=200):
    from .docs import recalc
    from .undo import oun_post
    recalc(c, oid, r["id"])
    bump(c)
    oun_post(c)
    c.commit()
    return jsonify(_answer(c, oid, r["id"], admin, part)), code


@app.post("/api/office/docs/<int:did>/parts")
def tp_part_create(did):
    """{kind?: items|shoot, title?, print?, add_to_title?: true} -> 201 the document (with "part" = the new part). A new
    part is put on the title page once (qty 1) unless add_to_title is false."""
    from .ledger import ofx_log
    c, uid, oid, admin, r = _ctx_doc(did)
    b = body()
    b = b if isinstance(b, dict) else {}
    kind = b.get("kind") or "items"
    if kind not in PART_KINDS or (kind == "shoot" and not tp_shoot_ok(c, oid)):
        raise BadInput(tr("Invalid value: {0}", "kind"))
    n = c.execute("SELECT COUNT(*) FROM office_doc_parts WHERE doc_id=? AND org_id=?", (did, oid)).fetchone()[0]
    if n >= MAX_PARTS:
        raise BadInput(tr("Too many parts (at most {0})", MAX_PARTS))
    from .docs import _text
    title = _text(b.get("title"), "title", 300) or tr("Part {0}", n + 1)
    ts = iso(now_utc())
    sort = (c.execute("SELECT MAX(sort) FROM office_doc_parts WHERE doc_id=? AND org_id=?", (did, oid)).fetchone()[0] or 0) + 1
    pid = insert_id(c, "INSERT INTO office_doc_parts(org_id, doc_id, sort, kind, title, print, settings, sheet, totals, created_at, updated_at) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (oid, did, sort, kind, title, 0 if b.get("print") in (0, False, "0") else 1, "{}", "{}", "{}", ts, ts))
    if kind == "shoot":  # a new sheet with the film pack's presets (part C), then what the body brings
        new, pk = _dk("dk_sheet_new"), _dk("dk_pack")
        sh = new(pk("film") if pk is not None else None) if new is not None else {}
        if isinstance(b.get("sheet"), dict):
            sh = _dk("dk_sheet_clean")(c, oid, b["sheet"], sh, admin)
        c.execute("UPDATE office_doc_parts SET sheet=? WHERE id=? AND org_id=?", (_sheet_store(c, oid, sh), pid, oid))
    if b.get("add_to_title", True) not in (False, 0, "0"):
        mx = c.execute("SELECT MAX(sort) FROM office_doc_items WHERE doc_id=? AND org_id=? AND part_id IS NULL", (did, oid)).fetchone()[0]
        c.execute("INSERT INTO office_doc_items(doc_id, org_id, sort, kind, title, detail, qty, unit, rate, tax, ref_part_id, discountable) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (did, oid, (mx if mx is not None else -1) + 1, "part", title, "", 1, "piece", 0, "standard", pid, 1))
    ofx_log(c, oid, "part", doc_id=did, detail={"after": {"part": pid, "kind": kind, "title": title}})
    return _done(c, oid, r, admin, pid, 201)


@app.patch("/api/office/docs/<int:did>/parts/<int:pid>")
def tp_part_patch(did, pid):
    """{title?, print?, sort?, settings?, sheet?} -> the document with "part" (a shoot part: + "calc") and "doc_totals"."""
    from .docs import _text
    from .ledger import ofx_diff, ofx_log
    c, uid, oid, admin, r = _ctx_doc(did)
    p = tp_part(c, oid, did, pid)
    b = body()
    if not isinstance(b, dict):
        return err(tr("Invalid data"))
    f = {}
    if "title" in b:
        f["title"] = _text(b.get("title"), "title", 300)
    if "print" in b:
        f["print"] = 0 if b.get("print") in (0, False, "0", "false") else 1
    if "sort" in b:
        try:
            f["sort"] = float(b.get("sort"))
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid value: {0}", "sort"))
        if not math.isfinite(f["sort"]):  # 2.47.0 (#1215): no nan / inf, the order of the parts must stay defined
            raise BadInput(tr("Invalid value: {0}", "sort"))
    if "settings" in b:
        f["settings"] = json.dumps(tp_settings_clean(b.get("settings"), p["settings"], dict(r).get("producing_mode") == "amount"), ensure_ascii=False)
    if "sheet" in b:
        if p["kind"] != "shoot":
            raise BadInput(tr("Invalid value: {0}", "sheet"))
        fn = _dk("dk_sheet_clean")
        if fn is None:
            raise BadInput(tr("Invalid value: {0}", "sheet"))
        f["sheet"] = _sheet_store(c, oid, fn(c, oid, b.get("sheet"), p["sheet"], admin))
    if f:
        before = {k: (json.dumps(p[k], ensure_ascii=False) if k == "settings" else p[k]) for k in f if k != "sheet"}
        diff = ofx_diff(before, f)
        f["updated_at"] = iso(now_utc())
        c.execute(f"UPDATE office_doc_parts SET {','.join(k + '=?' for k in f)} WHERE id=? AND org_id=?", [*f.values(), pid, oid])
        if f.get("title") and f["title"] != p["title"]:  # 2.138.0 A (#2239): the title page lines of the part follow a rename (own texts stay)
            c.execute("UPDATE office_doc_items SET title=? WHERE doc_id=? AND org_id=? AND kind='part' AND ref_part_id=? AND part_id IS NULL "
                      "AND (title=? OR title='' OR title IS NULL)", (f["title"], did, oid, pid, p["title"] or ""))
        if "sheet" in f:
            diff.setdefault("after", {})["sheet"] = "changed"  # the sheet itself stays out of the log
        if diff.get("after"):
            ofx_log(c, oid, "part", doc_id=did, detail={"part": pid, **diff})
    return _done(c, oid, r, admin, pid)


@app.delete("/api/office/docs/<int:did>/parts/<int:pid>")
def tp_part_delete(did, pid):
    """Removes the part, its positions and the title page positions that stand for it. Returns the document."""
    from .ledger import ofx_log
    c, uid, oid, admin, r = _ctx_doc(did)
    p = tp_part(c, oid, did, pid)
    c.execute("DELETE FROM office_doc_items WHERE doc_id=? AND org_id=? AND (part_id=? OR (kind='part' AND ref_part_id=?))", (did, oid, pid, pid))
    c.execute("DELETE FROM office_doc_parts WHERE id=? AND doc_id=? AND org_id=?", (pid, did, oid))
    ofx_log(c, oid, "part", doc_id=did, detail={"before": {"part": pid, "kind": p["kind"], "title": p["title"]}})
    return _done(c, oid, r, admin)


@app.put("/api/office/docs/<int:did>/parts/<int:pid>/items")
def tp_part_items_put(did, pid):
    """{items: [...]} the whole list of the part's positions (as PUT /api/office/docs/<id>/items, no kind 'part').
    Returns the document with "part" and "doc_totals"."""
    from .docs import clean_items
    from .ledger import ofx_items_brief, ofx_log
    c, uid, oid, admin, r = _ctx_doc(did)
    p = tp_part(c, oid, did, pid)
    if p["kind"] != "items":
        raise BadInput(tr("Invalid value: {0}", "items"))
    b = body()
    items = b.get("items") if isinstance(b, dict) else b
    before = ofx_items_brief(_part_items(c, oid, did, pid))
    rows = clean_items(c, oid, r, items, admin, part=pid)
    c.execute("DELETE FROM office_doc_items WHERE doc_id=? AND org_id=? AND part_id=?", (did, oid, pid))
    for row in rows:
        row.update(doc_id=did, org_id=oid, part_id=pid)
        row = oc_item_store(c, oid, row)
        c.execute(f"INSERT INTO office_doc_items({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    after = ofx_items_brief(_part_items(c, oid, did, pid))
    if before != after:
        ofx_log(c, oid, "items", doc_id=did, detail={"part": pid, "before": before, "after": after})
    c.execute("UPDATE office_doc_parts SET updated_at=? WHERE id=? AND org_id=?", (iso(now_utc()), pid, oid))
    return _done(c, oid, r, admin, pid)


N_("Part {0}")
N_("Only a quotation has parts")
N_("Too many parts (at most {0})")
