"""2.425.0 B (#3451): recurring providers of the bank bookings -- found from the bookings, their missing invoices, the receipt
that comes later matched by itself.

A provider is a counterpart (its IBAN, else its normalised name) that took money out at a regular rhythm: weekly (4+
bookings), monthly (3+), quarterly or yearly (2+); one period may be skipped. Nothing is stored for that: the bookings of
the last BV_SCAN_DAYS days are looked at each time. What a person sets for a provider is one row of office_bank_vendors
(the customer portal link, active, "needs no receipt"): a provider switched off gets no "invoice missing" hint, one that
needs no receipt leaves the list of bookings without a receipt (banknorc.bnr_open / bnr_counts) with all its bookings.
The hint: an open booking of an active provider older than the office's days (setting "bank_vendors": {days}, default
BV_DAYS, set only by its own route here) -> "Invoice <provider> <month> missing", with the portal link; shown in Bank >
Without receipt and bundled into the existing reminder task of banknorc (no task, no push of its own).
A document recognised later (upload, mail, folder watch: every way ends in docs.ingest's doc_on_done) whose amount (+-3 %
through the office rate for another currency), date (BV_BEFORE days before .. BV_AFTER days after the booking) and sender /
name / text fit exactly one open booking of an active provider -- and no other receipt fits that booking -- is matched
with it like a person's match (payment day = the booking's day, matched_by NULL); fitting more than one: it becomes a
receipt and stays a suggestion of the bank list (bank.bnk_suggest). No model, no portal login, nothing fetched.
Every route: office_ctx_admin like office/bank.py -- admins of the office area only (the person in a personal office);
agents and kids 403."""
import re
from contextlib import nullcontext
from datetime import date, timedelta
from decimal import Decimal

from flask import has_app_context, jsonify

from ..core.config import app
from ..core.db import body, bump, iso, local_now, now_utc
from ..core.access import Denied
from ..core.errors import BadInput
from ..core.i18n import lang, tr
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields
from ..core.pg import insert_id, write_lock
from ..docs.ingest import doc_on_done
from ..docs.store import doc_open, label_name, meta_row, meta_text, ws_org, ws_user
from ..receipts.suggest import rc_set
from .bank import _clean, _norm, _tx_dec
from .books import bk_home_rate, bk_receipt_set_paid, bk_receipts, bk_to_home, bk_ws
from .calc import dec, dstr, money
from .model import office_ctx_admin as _ctx, office_settings, office_settings_lock, office_settings_save
from .periodlock import pl_is_locked
from .recurring import RIN_MONTHS, _rin_months

BV_DAYS = 5  # days after the booking before its invoice counts as missing (default)
BV_DAYS_MAX = 90
BV_SCAN_DAYS = 400  # bookings looked at for the rhythm
BV_BEFORE, BV_AFTER = 35, 10  # the date of a receipt that fits a booking: this many days before .. after it
BV_FX_TOL = Decimal("0.03")  # another currency: +-3 % through the office rate
BV_HINTS_MAX = 20  # hint lines in the reminder task
BV_PORTAL_MAX = 500
# (name, days of one period, shortest, longest gap, bookings at least)
BV_RHYTHMS = (("week", 7, 5, 9, 4), ("month", 30, 26, 35, 3), ("quarter", 91, 84, 98, 2), ("year", 365, 350, 380, 2))
PORTAL_RE = re.compile(r"^https://[A-Za-z0-9.-]+(:\d{1,5})?(/[^\s<>\"']*)?$")
# known providers: a pattern on the counterpart -> the page of its invoices (a suggestion, the person may change it)
BV_KNOWN = ((r"\badobe\b", "https://account.adobe.com/orders"), (r"\bgoogle\b", "https://payments.google.com/"),
            (r"\bmicrosoft\b", "https://account.microsoft.com/billing/orders"), (r"\bamazon\b|\bamzn\b", "https://www.amazon.de/gp/css/order-history"),
            (r"\bapple\b", "https://reportaproblem.apple.com/"), (r"\btelekom\b", "https://www.telekom.de/kundencenter"),
            (r"\bvodafone\b", "https://www.vodafone.de/meinvodafone"), (r"\b1\s*(&|und)\s*1\b", "https://control-center.1und1.de/"),
            (r"\bhetzner\b", "https://accounts.hetzner.com/"), (r"\bionos\b", "https://my.ionos.de/"))
# words of a name that say nothing about the provider
_STOP = {"gmbh", "mbh", "ltd", "limited", "inc", "corp", "corporation", "llc", "sarl", "gmbh&co", "europe", "deutschland", "germany",
         "ireland", "international", "services", "service", "software", "systems", "online", "payment", "payments", "sepa", "lastschrift",
         "rechnung", "invoice", "kunde", "kundennummer", "danke", "und", "the", "for", "von", "mit", "bank", "company"}


def bv_key(t):
    """(kind, match) of a booking's counterpart: ("iban", IBAN) or ("cp", normalised name); None without both."""
    ib = re.sub(r"\s+", "", t.get("iban") or "").upper()
    if ib:
        return ("iban", ib)
    n = _norm(t.get("counterpart") or "")
    return ("cp", n) if n else None


def _rhythm(days):
    """The rhythm of the sorted distinct booking days, or None."""
    if len(days) < 2:
        return None
    gaps = [(date.fromisoformat(b) - date.fromisoformat(a)).days for a, b in zip(days, days[1:])]
    for name, _p, lo, hi, least in BV_RHYTHMS:
        one = sum(1 for g in gaps if lo <= g <= hi)
        if len(days) >= least and one >= least - 1 and all(lo <= g <= hi or 2 * lo <= g <= 2 * hi for g in gaps):
            return name
    return None


def _known_portal(name):
    s = (name or "").casefold()
    return next((u for p, u in BV_KNOWN if re.search(p, s)), "")


def bv_days(s):
    v = (s.get("bank_vendors") or {}).get("days") if isinstance(s.get("bank_vendors"), dict) else None
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= BV_DAYS_MAX else BV_DAYS


def bv_rows(c, oid):
    """{(kind, match): row} of what was set for the providers of area oid (decrypted)."""
    out = {}
    for r in c.execute("SELECT * FROM office_bank_vendors WHERE org_id=? ORDER BY id", (oid,)).fetchall():
        d = oc_dec_fields(c, oid, "office_bank_vendors", r)
        out[(d["kind"], d["match"])] = d
    return out


def bv_noreceipt_keys(c, oid):
    """{(kind, match)} of the providers whose bookings need no receipt (an empty set without any)."""
    if not c.execute("SELECT 1 FROM office_bank_vendors WHERE org_id=? AND noreceipt=1 LIMIT 1", (oid,)).fetchone():
        return set()
    return {k for k, r in bv_rows(c, oid).items() if r["noreceipt"]}


def bv_vendors(c, oid, today=None):
    """The providers of area oid: found by their rhythm, or set by a person once (then also without a rhythm now), with
    "_txs" = their money-out bookings of the last BV_SCAN_DAYS days (decrypted, oldest first). Sorted by name."""
    today = today or local_now().date().isoformat()
    since = (date.fromisoformat(today) - timedelta(days=BV_SCAN_DAYS)).isoformat()
    groups = {}
    for r in c.execute("SELECT * FROM office_bank_tx WHERE org_id=? AND deleted_at IS NULL AND day>=? ORDER BY day, id", (oid, since)).fetchall():
        t = _tx_dec(c, oid, r)
        k = bv_key(t) if t["amount"] < 0 else None
        if k:
            groups.setdefault(k, []).append(t)
    stored = bv_rows(c, oid)
    out = []
    for k in set(groups) | set(stored):
        txs, st = groups.get(k, []), stored.get(k)
        every = _rhythm(sorted({t["day"] for t in txs}))
        if not every and not st:
            continue
        last = txs[-1] if txs else None
        name = (last["counterpart"] if last else "") or (st["name"] if st else "") or k[1]
        portal = st["portal"] if st and st["portal"] else ""
        out.append({"kind": k[0], "match": k[1], "name": name, "iban": k[1] if k[0] == "iban" else "", "every": every,
                    "count": len(txs), "last_day": last["day"] if last else "", "amount": dstr(-last["amount"]) if last else "",
                    "currency": last["currency"] if last else "", "portal": portal or _known_portal(name),
                    "portal_suggested": not portal and bool(_known_portal(name)), "active": bool(st["active"]) if st else True,
                    "noreceipt": bool(st["noreceipt"]) if st else False, "stored": bool(st), "_txs": txs})
    return sorted(out, key=lambda v: (v["name"].casefold(), v["match"]))


def _month(day, lg):
    d = date.fromisoformat(day)
    return f"{(RIN_MONTHS.get(lg) or _rin_months(lg))[d.month - 1]} {d.year}"


def bv_missing(c, oid, lg, today=None, vendors=None):
    """The "invoice missing" hints of area oid: an open money-out booking of an active provider (with a rhythm, not "needs
    no receipt") older than the office's days, newest first: [{id (the booking), day, amount, currency, vendor, month,
    portal, text}]."""
    today = today or local_now().date().isoformat()
    edge = (date.fromisoformat(today) - timedelta(days=bv_days(office_settings(c, oid)))).isoformat()
    out = []
    for v in (bv_vendors(c, oid, today) if vendors is None else vendors):
        if not v["every"] or not v["active"] or v["noreceipt"]:
            continue
        for t in v["_txs"]:
            if t["match_kind"] is None and t["day"] <= edge:
                mo = _month(t["day"], lg)
                out.append({"id": t["id"], "day": t["day"], "amount": dstr(-t["amount"]), "currency": t["currency"], "vendor": v["name"],
                            "month": mo, "portal": v["portal"], "text": tr("Invoice {0} {1} missing", v["name"], mo, lg=lg)})
    return sorted(out, key=lambda h: (h["day"], h["id"]), reverse=True)


def bv_task_lines(c, oid, person, today=None):
    """The hints as lines of the reminder task (markdown, at most BV_HINTS_MAX, the portal as a link)."""
    hs = bv_missing(c, oid, lang(c, person), today)
    lines = [f"- {h['text']}" + (f" ([{tr('Customer portal', lg=lang(c, person))}]({h['portal']}))" if h["portal"] else "")
             for h in hs[:BV_HINTS_MAX]]
    if len(hs) > BV_HINTS_MAX:
        lines.append(f"- … +{len(hs) - BV_HINTS_MAX}")
    return lines


def _public(v):
    return {k: x for k, x in v.items() if not k.startswith("_")}


# ---------------------------------------------------------------- the receipt that comes later
def _words(s):
    return {w for w in _norm(s).split() if len(w) >= 4 and w not in _STOP}


def _name_fits(name, sender, hay):
    """A word of the provider's name in the document (sender, file name, text), or a word of the sender in that name."""
    wn = _words(name)
    return bool(wn & set(_norm(hay).split())) or bool(_words(sender) & wn)


def _amount_fits(a, cur, t, s):
    """Receipt amount a (currency cur) fits booking t (amount < 0): the same in the same currency, else +-3 % through the
    office rate (only when the booking is in the home currency and the office has a rate)."""
    want = -t["amount"]
    home = bk_home_rate("", s)[0]
    cur = (cur or "").upper() or home
    if cur == t["currency"]:
        return money(a) == want
    if t["currency"] != home or bk_home_rate(cur, s)[1] is None:
        return False
    return abs(money(bk_to_home(a, cur, s)) - want) <= want * BV_FX_TOL


def _fits_day(doc_day, t):
    g = (date.fromisoformat(doc_day[:10]) - date.fromisoformat(t["day"])).days
    return -BV_BEFORE <= g <= BV_AFTER


def _office_of(c, ws):
    """The office area of a documents space ('o<org>' or the personal office of 'u<person>'), else None."""
    o = ws_org(ws)
    if o:
        return o
    u = ws_user(ws)
    r = c.execute("SELECT id FROM orgs WHERE personal_of=?", (u,)).fetchone() if u else None
    return r[0] if r else None


def bv_autolink(c, nid, today=None):
    """Document nid after its recognition (see the module text): {"matched": booking id} | {"suggest": n} | None."""
    m = meta_row(c, nid)
    if not m or not m["doc_date"] or not re.match(r"^\d{4}-\d{2}-\d{2}", m["doc_date"] or ""):
        return None
    oid = _office_of(c, m["ws"])
    if not oid or bk_ws(c, oid) != m["ws"]:
        return None
    n = c.execute("SELECT id, org_id, name FROM fs_nodes WHERE id=? AND kind='file' AND deleted_at IS NULL", (nid,)).fetchone()
    a = dec(doc_open(c, m["ws"], "doc_meta.amount", m["amount"]) or "0", "0")
    if not n or a <= 0:
        return None
    rc = c.execute("SELECT paid_at FROM rc_receipts WHERE node_id=?", (nid,)).fetchone()
    if (rc and rc["paid_at"]) or c.execute("SELECT 1 FROM office_bank_tx WHERE org_id=? AND deleted_at IS NULL AND match_kind='receipt' "
                                            "AND match_id=? LIMIT 1", (oid, nid)).fetchone():
        return None
    s = office_settings(c, oid)
    sender = label_name(c, m["ws"], "sender", m["sender_id"]) or "" if m["sender_id"] else ""
    hay = f"{sender} {n['name']} {meta_text(c, m)[:4000]}"
    cands = []
    for v in bv_vendors(c, oid, today):
        if not v["every"] or not v["active"] or v["noreceipt"] or not _name_fits(v["name"], sender, hay):
            continue
        cands += [t for t in v["_txs"] if t["match_kind"] is None and _fits_day(m["doc_date"], t) and _amount_fits(a, m["currency"], t, s)
                  and not pl_is_locked(c, oid, t["day"])]
    if not cands:
        return None
    if not rc:  # it is the invoice of a provider: a receipt of the office (the bank list suggests it from now on)
        rc_set(c, {"id": nid, "org_id": n["org_id"]}, m["ws"], None, "", None, keep=True)
    if len(cands) > 1:
        return {"suggest": len(cands)}
    t = cands[0]
    taken = {r[0] for r in c.execute("SELECT match_id FROM office_bank_tx WHERE org_id=? AND deleted_at IS NULL AND match_kind='receipt'", (oid,))}
    frm = (date.fromisoformat(t["day"]) - timedelta(days=BV_BEFORE)).isoformat()
    to = (date.fromisoformat(t["day"]) + timedelta(days=BV_AFTER)).isoformat()
    for r in bk_receipts(c, oid, frm, to, uid=0):  # another open receipt of the same amount around it: the person decides
        if r["node_id"] != nid and r["node_id"] not in taken and not r.get("paid_at") and money(dec(r["amount"])) == -t["amount"]:
            return {"suggest": 2}
    write_lock(c, f"office_bank_tx_{t['id']}")
    write_lock(c, f"office_bank_receipt_{nid}")
    if not c.execute("SELECT 1 FROM office_bank_tx WHERE id=? AND org_id=? AND match_kind IS NULL AND deleted_at IS NULL", (t["id"], oid)).fetchone():
        return None
    bk_receipt_set_paid(c, oid, nid, t["day"])
    c.execute("UPDATE office_bank_tx SET match_kind='receipt', match_id=?, payment_id=NULL, matched_by=NULL, matched_at=?, rule_id=NULL "
              "WHERE id=? AND org_id=? AND match_kind IS NULL", (nid, iso(now_utc()), t["id"], oid))
    bump(c)
    return {"matched": t["id"]}


def bv_on_done(c, nid, first):
    """doc_on_done hook (docs/ingest.py): after every recognition run; never stops the recognition."""
    try:
        with nullcontext() if has_app_context() else app.app_context(), c.savepoint():  # the docs queue runs outside the app (period locks cache in g)
            bv_autolink(c, nid)
    except Exception as e:  # noqa: BLE001 -- a document that cannot be matched stays as it is
        print(f"WARNING bank provider receipt {nid}: {type(e).__name__} {e}", flush=True)


if bv_on_done not in doc_on_done:
    doc_on_done.append(bv_on_done)


# ---------------------------------------------------------------- routes
def _answer(c, oid, lg):
    vs = bv_vendors(c, oid)
    return {"items": [_public(v) for v in vs], "days": bv_days(office_settings(c, oid)), "days_default": BV_DAYS,
            "missing": bv_missing(c, oid, lg, vendors=vs)}


@app.get("/api/office/bank/vendors")
def bv_list():
    """{items: [{kind, match, name, iban, every (week|month|quarter|year|null), count, last_day, amount, currency, portal,
    portal_suggested, active, noreceipt, stored}], days, days_default, missing (the hints, see bv_missing)}."""
    c, uid, oid = _ctx()
    return jsonify(_answer(c, oid, lang(c, uid)))


@app.put("/api/office/bank/vendors")
def bv_put():
    """{kind: iban|cp, match, active?, noreceipt?, portal? (https link or '')} -> like GET. A provider that is neither found
    nor set before: 404; a link that is not https: 400."""
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict) or b.get("kind") not in ("iban", "cp") or not isinstance(b.get("match"), str) or not b["match"]:
        raise BadInput(tr("Invalid data"))
    vals = {}
    for f in ("active", "noreceipt"):
        if f in b:
            if not isinstance(b[f], bool):
                raise BadInput(tr("Invalid value: {0}", f))
            vals[f] = int(b[f])
    if "portal" in b:
        p = _clean(b["portal"], BV_PORTAL_MAX) if isinstance(b["portal"], str) else None
        if p is None or (p and not PORTAL_RE.match(p)):
            raise BadInput(tr("The link must start with https://"))
        vals["portal"] = p
    write_lock(c, f"office_bank_vendors_{oid}")
    k = (b["kind"], b["match"])
    v = next((x for x in bv_vendors(c, oid) if (x["kind"], x["match"]) == k), None)
    if v is None:
        raise Denied(404)
    ts = iso(now_utc())
    if v["stored"]:
        row = bv_rows(c, oid)[k]
        enc = oc_enc_fields(c, oid, "office_bank_vendors", {"name": v["name"], **({"portal": vals.pop("portal")} if "portal" in vals else {})})
        sets = {**enc, **vals, "updated_by": uid, "updated_at": ts}
        c.execute(f"UPDATE office_bank_vendors SET {', '.join(f'{f}=?' for f in sets)} WHERE id=? AND org_id=?", (*sets.values(), row["id"], oid))
    else:
        d = {"kind": k[0], "match": k[1], "name": v["name"], "portal": vals.pop("portal", ""), "active": 1, "noreceipt": 0, **vals}
        enc = oc_enc_fields(c, oid, "office_bank_vendors", {"org_id": oid, **d, "updated_by": uid, "created_at": ts, "updated_at": ts})
        insert_id(c, f"INSERT INTO office_bank_vendors({', '.join(enc)}) VALUES({', '.join('?' * len(enc))})", tuple(enc.values()))
    bump(c)
    c.commit()
    return jsonify(_answer(c, oid, lang(c, uid)))


@app.put("/api/office/bank/vendors/settings")
def bv_settings():
    """{days: 0..90} -> like GET: the days after a booking before its invoice counts as missing."""
    c, uid, oid = _ctx()
    b = body()
    v = b.get("days") if isinstance(b, dict) else None
    if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= BV_DAYS_MAX:
        raise BadInput(tr("Invalid value: {0}", "days"))
    office_settings_lock(c, oid)
    s = office_settings(c, oid)
    s["bank_vendors"] = {**(s.get("bank_vendors") if isinstance(s.get("bank_vendors"), dict) else {}), "days": v}
    office_settings_save(c, oid, s)
    bump(c)
    c.commit()
    return jsonify(_answer(c, oid, lang(c, uid)))
