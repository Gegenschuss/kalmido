"""2.299.0 B (#3191): bank rules -- bookings of a statement marked by rules, and rules learned from what people confirm.

A rule (office_bank_rules, one office area) has conditions -- counterpart and purpose as a word part (normalised like
bank._norm), the counterpart's IBAN, an amount range on the absolute amount, the direction in / out -- and one action:
private | ignored | noreceipt mark an open booking (match_kind, office_bank_tx.rule_id = the rule, matched_by NULL), category
only suggests: a receipt matched with such a booking by a person gets the rule's category when it has none. Invoices and
receipts are never matched by a rule (money moves; they stay suggestions of bank.bnk_suggest).
Applied after every import (bank.bnk_import / restore) and, when asked, to the open bookings once a rule is made. Never a
booking that is matched already, never one in a locked month (office/periodlock.py, skipped and counted). Several rules
fit: the most specific one wins (IBAN > counterpart + purpose > counterpart > purpose, then with an amount range); a tie
with different outcomes marks nothing (the booking shows the rules as a suggestion).
Learning: a person marks the same counterpart (IBAN, else name) the same way twice (private / ignored / noreceipt, or a
receipt of the same category) -> the answer of match carries a rule suggestion ("Always like this?"); declined ones are
remembered per counterpart (office_bank_rule_nos, a keyed hash) and never asked again.
Every route: office_gate + office_org(admin=True) like bank.py -- admins of the office area only (the person in a personal
office); agents and kids 403, foreign ids 404. Texts, IBAN and amounts of a rule are encrypted at rest (orgcrypt)."""
import hashlib
import hmac
import re
from datetime import timedelta
from decimal import Decimal

from flask import jsonify

from ..core.config import SECRET_KEY, app
from ..core.pg import insert_id, write_lock
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields
from ..core.i18n import tr
from ..core.db import body, bump, iso, local_now, now_utc
from ..core.access import Denied
from ..core.errors import BadInput
from ..receipts.suggest import rc_categories
from .bank import BNK_KINDS, IBAN_RE, _clean, _norm, _tx_dec
from .books import bk_ws
from .calc import dec, dstr, money
from .model import office_ctx_admin as _ctx
from .periodlock import period_need_open, pl_is_locked

BR_ACTIONS = ("private", "ignored", "noreceipt", "category")
BR_MARKS = ("private", "ignored", "noreceipt")  # the actions that mark a booking
BR_DIRS = ("", "in", "out")
BR_MAX = 300  # rules per office area
BR_LEARN = 2  # the same confirmation this often -> a rule suggestion
BR_LEARN_SCAN = 2000  # matched bookings looked at for it (newest first)
BR_LEARN_DAYS = 400  # ... of the last 400 days (2.299.0 review: bounded by the day index)
BR_NOS_MAX = 5000  # declined suggestions per office area (2.299.0 review)
ACCT_RE = re.compile(r"^\d{1,9}$")
_FIELDS = ("name", "counterpart", "iban", "purpose", "amount_min", "amount_max", "direction", "action", "category", "account", "active")


def br_iban(v):
    return re.sub(r"\s+", "", v if isinstance(v, str) else "").upper()


def br_key(oid, kind, value):
    """The keyed hash of a counterpart (kind iban | cp) for a declined suggestion -- never the value itself."""
    key = SECRET_KEY if isinstance(SECRET_KEY, bytes) else str(SECRET_KEY).encode()
    return hmac.new(key, f"bank-rule\x1f{oid}\x1f{kind}\x1f{value}".encode(), hashlib.sha256).hexdigest()[:40]


def _keys(oid, t):
    """The keys of booking t's counterpart: the IBAN and the normalised name (what is there)."""
    out = []
    if br_iban(t.get("iban")):
        out.append(br_key(oid, "iban", br_iban(t.get("iban"))))
    if _norm(t.get("counterpart")):
        out.append(br_key(oid, "cp", _norm(t.get("counterpart"))))
    return out


# ---------------------------------------------------------------- rules: load, check, pick
def _amt(v):
    return None if v in (None, "") else money(dec(v))


def _rule_dec(c, oid, r):
    d = oc_dec_fields(c, oid, "office_bank_rules", r)
    d["_cp"], d["_pp"], d["_iban"] = _norm(d["counterpart"]), _norm(d["purpose"]), br_iban(d["iban"])
    d["_min"], d["_max"] = _amt(d["amount_min"]), _amt(d["amount_max"])
    return d


def br_rules(c, oid, active=True):
    """The rules of area oid (decrypted), oldest first; active=True: only the ones switched on (not deleted either way)."""
    q = "SELECT * FROM office_bank_rules WHERE org_id=? AND deleted_at IS NULL" + (" AND active=1" if active else "")
    return [_rule_dec(c, oid, r) for r in c.execute(q + " ORDER BY id", (oid,)).fetchall()]


def br_hit(r, t):
    """Rule r (br_rules) fits booking t (bank._tx_dec: amount a signed Decimal)."""
    a = t["amount"]
    if (r["direction"] == "in" and a <= 0) or (r["direction"] == "out" and a >= 0):
        return False
    if r["_iban"] and br_iban(t.get("iban")) != r["_iban"]:
        return False
    if "_ncp" not in t:  # 2.299.0 (#3191 review): normalised once per booking, not once per rule
        t["_ncp"], t["_npp"] = f" {_norm(t.get('counterpart'))} ", f" {_norm(t.get('purpose'))} "
    if r["_cp"] and f" {r['_cp']} " not in t["_ncp"]:
        return False
    if r["_pp"] and f" {r['_pp']} " not in t["_npp"]:
        return False
    if (r["_min"] is not None and abs(a) < r["_min"]) or (r["_max"] is not None and abs(a) > r["_max"]):
        return False
    return bool(r["_iban"] or r["_cp"] or r["_pp"])  # a rule without a text condition never fits (cannot be made either)


def br_rank(r):
    """How specific rule r is: IBAN > counterpart + purpose > counterpart > purpose, then with an amount range."""
    base = 3 if r["_iban"] else 2 if r["_cp"] and r["_pp"] else 1 if r["_cp"] else 0
    return base, 1 if r["_min"] is not None or r["_max"] is not None else 0


def br_pick(rules, t):
    """(the rule that decides booking t or None, the most specific fitting rules). A tie of rules with different outcomes
    decides nothing; the same outcome = the oldest of them."""
    hits = [r for r in rules if br_hit(r, t)]
    if not hits:
        return None, []
    top = max(br_rank(r) for r in hits)
    best = [r for r in hits if br_rank(r) == top]
    if len({(r["action"], r["category"].casefold(), r["account"]) for r in best}) > 1:
        return None, best
    return best[0], best


def br_hint(r):
    return {"id": r["id"], "name": r["name"], "action": r["action"], "category": r["category"] or None, "account": r["account"] or None}


# ---------------------------------------------------------------- applying
def _tx_try_lock(c, tid):
    """The lock of bank.py's match / unmatch on booking tid, only when it is free: a booking a person is matching right now
    is left to them (no waiting, so no lock cycle with the period lock either)."""
    return bool(c.execute("SELECT pg_try_advisory_xact_lock(hashtext(?))", (f"office_bank_tx_{tid}",)).fetchone()[0])


def br_apply(c, oid, import_id=None, only=None):
    """Marks the open bookings of area oid (of one import: import_id) that a rule decides with a marking action (only: the
    rule id that must be the deciding one). Never a matched booking, never one in a locked month (counted). -> {applied,
    locked}. Holds the area's rule lock; writes a booking only under the (free) lock of bank.py's match / unmatch."""
    write_lock(c, f"office_bank_rules_{oid}")
    rules = br_rules(c, oid)
    out = {"applied": 0, "locked": 0}
    if not any(r["action"] in BR_MARKS for r in rules):
        return out
    period_need_open(c, oid)  # the period lock shared until the commit (a month being locked waits)
    q, args = "SELECT * FROM office_bank_tx WHERE org_id=? AND deleted_at IS NULL AND match_kind IS NULL", [oid]
    if import_id is not None:
        q += " AND import_id=?"
        args.append(import_id)
    hits, ts = {}, iso(now_utc())
    for row in c.execute(q + " ORDER BY id", args).fetchall():
        t = _tx_dec(c, oid, row)
        r, _best = br_pick(rules, t)
        if r is None or r["action"] not in BR_MARKS or (only is not None and r["id"] != only):
            continue
        if r["action"] not in BNK_KINDS:  # noreceipt before part C (#3192) is in: nothing is marked
            continue
        if pl_is_locked(c, oid, t["day"]):
            out["locked"] += 1
            continue
        if not _tx_try_lock(c, t["id"]):
            continue
        n = c.execute("UPDATE office_bank_tx SET match_kind=?, match_id=NULL, payment_id=NULL, matched_by=NULL, matched_at=?, rule_id=? "
                      "WHERE id=? AND org_id=? AND match_kind IS NULL AND deleted_at IS NULL", (r["action"], ts, r["id"], t["id"], oid)).rowcount
        if n:
            out["applied"] += 1
            hits[r["id"]] = hits.get(r["id"], 0) + 1
    for rid, n in hits.items():
        c.execute("UPDATE office_bank_rules SET hits=hits+?, last_hit_at=? WHERE id=? AND org_id=?", (n, ts, rid, oid))
    return out


def br_release(c, oid, rule_id=None, import_id=None):
    """Lifts the marks rules set (of one rule / of one import) outside the locked months -> {undone, locked}."""
    q, args = "SELECT id, day FROM office_bank_tx WHERE org_id=? AND deleted_at IS NULL AND rule_id IS NOT NULL AND match_kind IS NOT NULL", [oid]
    if rule_id is not None:
        q += " AND rule_id=?"
        args.append(rule_id)
    if import_id is not None:
        q += " AND import_id=?"
        args.append(import_id)
    out = {"undone": 0, "locked": 0}
    period_need_open(c, oid)
    for t in c.execute(q + " ORDER BY id", args).fetchall():
        if pl_is_locked(c, oid, t["day"]):
            out["locked"] += 1
            continue
        if not _tx_try_lock(c, t["id"]):
            continue
        out["undone"] += c.execute("UPDATE office_bank_tx SET match_kind=NULL, match_id=NULL, payment_id=NULL, matched_by=NULL, matched_at=NULL, "
                                   "rule_id=NULL WHERE id=? AND org_id=? AND rule_id IS NOT NULL AND matched_by IS NULL "  # never by hand
                                   "AND match_kind IN ('private', 'ignored', 'noreceipt')",
                                   (t["id"], oid)).rowcount
    return out


def br_on_receipt(c, oid, t, node_id):
    """A person matched booking t with receipt node_id: a category rule deciding t gives the receipt its category when it
    has none. -> the rule's hint or None."""
    r, _best = br_pick(br_rules(c, oid), t)
    if r is None or r["action"] != "category" or not r["category"]:
        return None
    n = c.execute("UPDATE rc_receipts SET category=?, set_at=? WHERE node_id=? AND category=''",  # review: set_at like rc_set
                  (r["category"], iso(now_utc()), node_id)).rowcount
    if not n:
        return None
    c.execute("UPDATE office_bank_rules SET hits=hits+1, last_hit_at=? WHERE id=? AND org_id=?", (iso(now_utc()), r["id"], oid))
    return br_hint(r)


# ---------------------------------------------------------------- learning
def _rc_category(c, node_id):
    r = c.execute("SELECT category FROM rc_receipts WHERE node_id=?", (node_id,)).fetchone()
    return (r["category"] or "") if r else ""


def br_learn(c, oid, t, kind, mid=None):
    """After a person matched booking t (kind, receipt id mid): a rule suggestion when the same counterpart got the same
    mark (or a receipt of the same category) by hand BR_LEARN times, no rule decides t yet and nobody declined it --
    {counterpart, iban, action, category, count} or None."""
    if kind not in BR_MARKS and kind != "receipt":
        return None
    iban, cp = br_iban(t.get("iban")), _norm(t.get("counterpart"))
    if not iban and not cp:
        return None
    keys = _keys(oid, t)
    if c.execute(f"SELECT 1 FROM office_bank_rule_nos WHERE org_id=? AND key IN ({','.join('?' * len(keys))}) LIMIT 1", [oid, *keys]).fetchone():
        return None
    if any(br_hit(r, t) for r in br_rules(c, oid, active=False)):  # a rule fits already (also one switched off)
        return None
    cat = ""
    if kind == "receipt":
        cat = _rc_category(c, mid)
        if not cat:
            return None
    same = lambda x: (br_iban(x.get("iban")) == iban) if iban else (_norm(x.get("counterpart")) == cp)  # noqa: E731
    n = 0
    since = (local_now().date() - timedelta(days=BR_LEARN_DAYS)).isoformat()  # review: the day index bounds the scan
    for row in c.execute("SELECT * FROM office_bank_tx WHERE org_id=? AND day>=? AND deleted_at IS NULL AND match_kind=? AND rule_id IS NULL "
                         f"ORDER BY id DESC LIMIT {BR_LEARN_SCAN}", (oid, since, kind)).fetchall():
        x = _tx_dec(c, oid, row)
        if not same(x) or (kind == "receipt" and _rc_category(c, x["match_id"]).casefold() != cat.casefold()):
            continue
        n += 1
        if n >= BR_LEARN:
            break
    if n < BR_LEARN:
        return None
    return {"counterpart": t.get("counterpart") or "", "iban": iban or None, "action": "category" if kind == "receipt" else kind,
            "category": cat or None, "direction": "out" if kind == "receipt" else None, "count": n}


# ---------------------------------------------------------------- the rule itself
def _num(v, field):
    if v in (None, ""):
        return ""
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise BadInput(tr("Invalid value: {0}", field))
    d = dec(v, "NaN")
    if not d.is_finite() or d < 0 or d > Decimal("1000000000"):
        raise BadInput(tr("Invalid value: {0}", field))
    return dstr(d)


def _txt(b, k, n):
    v = b.get(k)
    if v is None:
        return ""
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", k))
    return _clean(v, n)


def br_spec(b, old=None):
    """A checked rule from body b (a PUT: the fields given over the old rule) -> the columns to write."""
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    d = {k: old[k] for k in _FIELDS} if old else {"active": 1}
    for k, n in (("name", 80), ("counterpart", 200), ("purpose", 200), ("category", 80)):
        if k in b or not old:
            d[k] = _txt(b, k, n)
    if "iban" in b or not old:
        if b.get("iban") is not None and not isinstance(b.get("iban"), str):
            raise BadInput(tr("Invalid value: {0}", "iban"))
        d["iban"] = br_iban(b.get("iban"))
        if d["iban"] and not IBAN_RE.match(d["iban"]):
            raise BadInput(tr("Invalid value: {0}", "iban"))
    for k in ("amount_min", "amount_max"):
        if k in b or not old:
            d[k] = _num(b.get(k), k)
    if "direction" in b or not old:
        d["direction"] = b.get("direction") or ""
        if d["direction"] not in BR_DIRS:
            raise BadInput(tr("Invalid value: {0}", "direction"))
    if "action" in b or not old:
        d["action"] = b.get("action")
        if d["action"] not in BR_ACTIONS:
            raise BadInput(tr("Invalid value: {0}", "action"))
    if "account" in b or not old:
        d["account"] = b.get("account") if isinstance(b.get("account"), str) else "" if b.get("account") is None else str(b.get("account"))
        d["account"] = d["account"].strip()
        if d["account"] and not ACCT_RE.match(d["account"]):
            raise BadInput(tr("Invalid value: {0}", "account"))
    if "active" in b:
        if not isinstance(b["active"], bool):
            raise BadInput(tr("Invalid value: {0}", "active"))
        d["active"] = 1 if b["active"] else 0
    if not (_norm(d["counterpart"]) or d["iban"] or _norm(d["purpose"])):
        raise BadInput(tr("A rule needs the name, the IBAN or a word of the purpose"))
    if d["amount_min"] and d["amount_max"] and dec(d["amount_min"]) > dec(d["amount_max"]):
        raise BadInput(tr("Invalid value: {0}", "amount_max"))
    if d["action"] == "category":
        if not d["category"]:
            raise BadInput(tr("Please choose a category"))
    else:
        d["category"], d["account"] = "", ""
    if not d["name"]:
        d["name"] = _clean(d["counterpart"] or d["iban"] or d["purpose"], 80)
    return d


def br_public(r):
    return {"id": r["id"], "name": r["name"], "counterpart": r["counterpart"] or "", "iban": r["iban"] or None, "purpose": r["purpose"] or "",
            "amount_min": r["amount_min"] or None, "amount_max": r["amount_max"] or None, "direction": r["direction"] or None,
            "action": r["action"], "category": r["category"] or None, "account": r["account"] or None, "active": bool(r["active"]),
            "hits": r["hits"], "last_hit_at": r["last_hit_at"], "created_at": r["created_at"], "deleted": bool(r["deleted_at"])}


def _rule_row(c, oid, rid, deleted=False):
    r = c.execute("SELECT * FROM office_bank_rules WHERE id=? AND org_id=?" + ("" if deleted else " AND deleted_at IS NULL"), (rid, oid)).fetchone()
    if r is None:
        raise Denied(404)
    return r


def _write(c, oid, rid, d):
    row = oc_enc_fields(c, oid, "office_bank_rules", {k: d[k] for k in _FIELDS})
    row["updated_at"] = iso(now_utc())
    c.execute(f"UPDATE office_bank_rules SET {', '.join(k + '=?' for k in row)} WHERE id=? AND org_id=?", [*row.values(), rid, oid])


def br_create(c, oid, uid, spec):
    """Makes a rule in area oid from spec (the body of POST /rules; checked by br_spec) -> its id. 409 at BR_MAX rules."""
    d = br_spec(spec)
    write_lock(c, f"office_bank_rules_{oid}")
    if c.execute("SELECT COUNT(*) FROM office_bank_rules WHERE org_id=? AND deleted_at IS NULL", (oid,)).fetchone()[0] >= BR_MAX:
        raise Denied(409, tr("At most {0} rules", BR_MAX))
    ts = iso(now_utc())
    row = oc_enc_fields(c, oid, "office_bank_rules", {"org_id": oid, **{k: d[k] for k in _FIELDS}, "created_by": uid, "created_at": ts, "updated_at": ts})
    return insert_id(c, f"INSERT INTO office_bank_rules({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))


def _one(c, oid, rid, deleted=False):
    return br_public(_rule_dec(c, oid, _rule_row(c, oid, rid, deleted)))


# ---------------------------------------------------------------- routes
@app.get("/api/office/bank/rules")
def br_list():
    """-> {items: [rules, newest first], categories: [the receipt categories of the area, for the editor]}."""
    c, uid, oid = _ctx()
    items = [br_public(r) for r in reversed(br_rules(c, oid, active=False))]
    return jsonify(items=items, categories=rc_categories(c, bk_ws(c, oid)), max=BR_MAX)


@app.post("/api/office/bank/rules")
def br_new():
    """{name?, counterpart?, iban?, purpose?, amount_min?, amount_max?, direction? in|out, action private|ignored|noreceipt|category,
    category?, account?, apply_open?: bool} -> 201 {rule, applied, locked} (apply_open: marked on the open bookings at once)."""
    c, uid, oid = _ctx()
    b = body()
    rid = br_create(c, oid, uid, b)
    res = br_apply(c, oid, only=rid) if isinstance(b, dict) and b.get("apply_open") is True else {"applied": 0, "locked": 0}
    bump(c)
    c.commit()
    return jsonify(rule=_one(c, oid, rid), **res), 201


@app.put("/api/office/bank/rules/<int:rid>")
def br_edit(rid):
    """The fields given change (also active: bool); marks set already stay (POST /rules/<id>/revert lifts them)."""
    c, uid, oid = _ctx()
    write_lock(c, f"office_bank_rules_{oid}")
    old = _rule_dec(c, oid, _rule_row(c, oid, rid))
    _write(c, oid, rid, br_spec(body(), old))
    bump(c)
    c.commit()
    return jsonify(rule=_one(c, oid, rid))


@app.delete("/api/office/bank/rules/<int:rid>")
def br_delete(rid):
    """The rule goes (deleted_at; POST /restore brings it back); bookings it marked stay marked ("by rule" with its name)."""
    c, uid, oid = _ctx()
    write_lock(c, f"office_bank_rules_{oid}")
    _rule_row(c, oid, rid)
    c.execute("UPDATE office_bank_rules SET deleted_at=? WHERE id=? AND org_id=?", (iso(now_utc()), rid, oid))
    bump(c)
    c.commit()
    return jsonify(ok=True, rule=_one(c, oid, rid, deleted=True))


@app.post("/api/office/bank/rules/<int:rid>/restore")
def br_restore(rid):
    c, uid, oid = _ctx()
    write_lock(c, f"office_bank_rules_{oid}")
    r = _rule_row(c, oid, rid, deleted=True)
    if not r["deleted_at"]:
        raise Denied(409, tr("This rule is not deleted"))
    c.execute("UPDATE office_bank_rules SET deleted_at=NULL WHERE id=? AND org_id=?", (rid, oid))
    bump(c)
    c.commit()
    return jsonify(ok=True, rule=_one(c, oid, rid))


@app.post("/api/office/bank/rules/<int:rid>/apply")
def br_apply_route(rid):
    """Marks the open bookings this rule decides -> {applied, locked, rule}."""
    c, uid, oid = _ctx()
    r = _rule_row(c, oid, rid)
    if not r["active"]:
        raise Denied(409, tr("This rule is switched off"))
    res = br_apply(c, oid, only=rid)
    bump(c)
    c.commit()
    return jsonify(rule=_one(c, oid, rid), **res)


@app.post("/api/office/bank/rules/<int:rid>/revert")
def br_revert(rid):
    """Lifts every mark this rule set outside the locked months -> {undone, locked}; the rule itself stays."""
    c, uid, oid = _ctx()
    write_lock(c, f"office_bank_rules_{oid}")
    _rule_row(c, oid, rid, deleted=True)
    res = br_release(c, oid, rule_id=rid)
    bump(c)
    c.commit()
    return jsonify(**res)


@app.post("/api/office/bank/rules/decline")
def br_decline():
    """{counterpart?, iban?}: a learned suggestion for this counterpart is not offered again."""
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    t = {"iban": b.get("iban") if isinstance(b.get("iban"), str) else "", "counterpart": b.get("counterpart") if isinstance(b.get("counterpart"), str) else ""}
    keys = _keys(oid, t)
    if not keys:
        raise BadInput(tr("Invalid value: {0}", "counterpart"))
    if c.execute("SELECT COUNT(*) FROM office_bank_rule_nos WHERE org_id=?", (oid,)).fetchone()[0] >= BR_NOS_MAX:
        raise Denied(409, tr("Too many entries"))
    ts = iso(now_utc())
    for k in keys:
        c.execute("INSERT INTO office_bank_rule_nos(org_id, key, created_by, created_at) VALUES(?,?,?,?) ON CONFLICT (org_id, key) DO NOTHING",
                  (oid, k, uid, ts))
    c.commit()
    return jsonify(ok=True)


def br_names(c, oid, ids):
    """{rule id: name} of the rules ids of area oid (deleted ones too: a booking keeps showing which rule marked it)."""
    ids = [i for i in ids if i]
    if not ids:
        return {}
    return {r["id"]: oc_dec_fields(c, oid, "office_bank_rules", r)["name"] for r in c.execute(
        f"SELECT id, name FROM office_bank_rules WHERE org_id=? AND id IN ({','.join('?' * len(ids))})", [oid, *ids])}
