"""2.81.0 B (#1834): correct an archived document of the office (office_archive, legacyimport.py) afterwards: its client,
its amount as net + tax lines (19 %, 7 %, 0 %, reverse charge; Kalmido adds the gross) and paid (invoices only). The PDF
and its number never change. Everybody who reads the office archive of the organisation may assign its client (members
and admins; agents never reach the office routes, office_gate); amount, tax lines and paid only an office admin
(audit 2.86 B3, #1968: the bookkeeping sums hang on them) and never below zero. Every change goes into the entry's history
(office_archive_log: when, who, in which role, old and new value as JSON text), shown in the edit dialog.
office_archive.amount stays the gross sum (2.80.0 reads it unchanged); tax_lines NULL = only the gross is known."""
import json
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify

from ..core.config import app
from ..core.access import Denied
from ..core.i18n import tr
from ..core.db import iso, now_utc
from ..personal.timetrack import BadInput
from .model import OFFICE_ADMIN_ONLY, office_role, pb_cl_sql

R81B_RATES = {"19": 19, "7": 7, "0": 0, "rc": 0}  # rc = reverse charge: the client pays the tax, none on the document
R81B_LINES_MAX = 10
R81B_ADMIN_FIELDS = ("amount", "tax_lines", "paid")  # #1968: members only assign the client
CENT = Decimal("0.01")


def r81b_tax_lines(v):
    """The checked tax lines [{net, tax}] -> ([{net, tax, amount}] with texts, gross Decimal); 400 for anything else."""
    from .legacyimport import _amount
    if not isinstance(v, list) or not 1 <= len(v) <= R81B_LINES_MAX:
        raise BadInput(tr("Invalid value: {0}", "tax_lines"))
    out, gross = [], Decimal(0)
    for ln in v:
        net = _amount(ln.get("net")) if isinstance(ln, dict) else None
        tax = str(ln.get("tax")) if isinstance(ln, dict) else ""
        if net is None or net < 0 or tax not in R81B_RATES:  # #1968: no negative net
            raise BadInput(tr("Invalid value: {0}", "tax_lines"))
        net = net.quantize(CENT, ROUND_HALF_UP)
        amt = (net * R81B_RATES[tax] / 100).quantize(CENT, ROUND_HALF_UP)
        out.append({"net": str(net), "tax": tax, "amount": str(amt)})
        gross += net + amt
    return out, gross


def r81b_lines(r):
    try:
        v = json.loads(r["tax_lines"]) if r["tax_lines"] else None
    except (ValueError, TypeError):
        v = None
    return v if isinstance(v, list) else None


def r81b_public(d, r):
    """The tax lines + net / tax sums into the public dict of an entry (_archive_public); None = only the gross known."""
    lines = r81b_lines(r) if "tax_lines" in r.keys() else None
    if lines:  # review: the gross changed without them (an older version) -> they no longer fit, tax unknown again
        try:
            if sum(Decimal(x["net"]) + Decimal(x["amount"]) for x in lines) != Decimal(str(r["amount"])):
                lines = None
        except Exception:  # noqa: BLE001 -- no readable gross
            lines = None
    d["tax_lines"] = lines
    d["net"] = float(sum(Decimal(x["net"]) for x in lines)) if lines else None
    d["tax"] = float(sum(Decimal(x["amount"]) for x in lines)) if lines else None
    return d


def _client(c, oid, cid):
    if not cid:
        return None
    r = c.execute(f"SELECT name FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (cid,)).fetchone()
    return {"id": cid, "name": r["name"] if r else ""}


def _amount_val(gross, lines):
    return {"gross": float(gross) if gross is not None else None, "lines": lines}


def r81b_archive_patch(c, oid, uid, aid, b):
    """Apply {client_id?, tax_lines? | amount?, paid?} to entry aid of office area oid; one history row per changed field.
    Returns the names of the changed fields. tax_lines win over amount; amount alone = gross only (tax unknown).
    #1968: amount / tax_lines / paid only an office admin (403), a negative amount 400."""
    from .legacyimport import _archive_fields
    r = c.execute("SELECT * FROM office_archive WHERE id=? AND org_id=?", (aid, oid)).fetchone()
    if not r:
        raise Denied(404)
    role = office_role(c, uid, oid)
    if role != "admin" and any(k in b for k in R81B_ADMIN_FIELDS):
        raise Denied(403, tr(OFFICE_ADMIN_ONLY))
    keep = ("client_id", "amount") + (("paid",) if r["kind"] == "invoice" else ())  # paid: invoices only (an offer ignores it)
    f = _archive_fields(c, oid, {k: v for k, v in b.items() if k in keep}, partial=True)
    if b.get("tax_lines") not in (None, []):
        lines, gross = r81b_tax_lines(b["tax_lines"])
        f["amount"], f["tax_lines"] = str(gross), json.dumps(lines)
    elif "amount" in f:
        if f["amount"] is not None and Decimal(f["amount"]) < 0:
            raise BadInput(tr("Invalid value: {0}", "amount"))
        f["tax_lines"] = None
    log, ts = [], iso(now_utc())
    if "client_id" in f and (f["client_id"] or None) != (r["client_id"] or None):
        log.append(("client", _client(c, oid, r["client_id"]), _client(c, oid, f["client_id"])))
    if "amount" in f:
        old_g = Decimal(str(r["amount"])) if r["amount"] is not None else None
        new_g = Decimal(f["amount"]) if f["amount"] is not None else None
        old_l, new_l = r81b_lines(r), (json.loads(f["tax_lines"]) if f["tax_lines"] else None)
        if old_g != new_g or old_l != new_l:
            log.append(("amount", _amount_val(old_g, old_l), _amount_val(new_g, new_l)))
    if "paid" in f and int(f["paid"]) != int(r["paid"] or 0):
        log.append(("paid", int(r["paid"] or 0), int(f["paid"])))
    if not log:
        return []
    c.execute(f"UPDATE office_archive SET {', '.join(k + '=?' for k in f)} WHERE id=? AND org_id=?", [*f.values(), aid, oid])
    for field, old, new in log:
        c.execute("INSERT INTO office_archive_log(org_id, archive_id, at, user_id, field, old, new, role) VALUES(?,?,?,?,?,?,?,?)",
                  (oid, aid, ts, uid, field, json.dumps(old, ensure_ascii=False), json.dumps(new, ensure_ascii=False),
                   "" if role == "admin" else "member"))
    return [x[0] for x in log]


def r81b_history(c, oid, aid):
    users, out = {}, []
    for r in c.execute("SELECT * FROM office_archive_log WHERE org_id=? AND archive_id=? ORDER BY id DESC LIMIT 200", (oid, aid)):
        if r["user_id"] and r["user_id"] not in users:
            u = c.execute("SELECT display_name, username FROM users WHERE id=?", (r["user_id"],)).fetchone()
            users[r["user_id"]] = (u["display_name"] or u["username"]) if u else ""
        try:
            old, new = json.loads(r["old"] or "null"), json.loads(r["new"] or "null")
        except ValueError:
            old = new = None
        out.append({"id": r["id"], "at": r["at"], "user_name": users.get(r["user_id"], ""), "field": r["field"], "old": old, "new": new,
                    "by_member": r["role"] == "member"})
    return out


@app.get("/api/office/legacy/archive/<int:aid>")
def r81b_archive_get(aid):
    """Members: one archived document with its history (newest first) -- the edit dialog."""
    from .legacyimport import _archive_public, _ctx
    c, uid, oid = _ctx(admin=False)
    r = c.execute("SELECT * FROM office_archive WHERE id=? AND org_id=?", (aid, oid)).fetchone()
    if not r:
        raise Denied(404)
    cl = _client(c, oid, r["client_id"])
    d = _archive_public(r, {r["client_id"]: cl["name"]} if cl else {})
    d["history"] = r81b_history(c, oid, aid)
    d["admin"] = office_role(c, uid, oid) == "admin"  # #1968: only an admin edits amount / tax lines / paid
    return jsonify(d)
