"""2.47.0 (part D): the purchase side of quotations -- producing per document (#1645) and the purchase of accepted
quotations for the cash flow (#1649). Helpers without routes; docs.py and core/db.py call them."""
import json
from ..core.db import iso, local_now, now_utc  # 2.149.0 G (#2517): pulled up from functions
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields  # 2.149.0 G (#2517): pulled up from functions


def ek_producing_migrate(c):
    """2.47.0 (#1645), at every start (idempotent: only rows without a value): office_docs.producing_on of documents from
    2.46 and older = 1 when one of their positions counts towards producing (that is how they compute today), else the
    office default of their organisation. Their sums stay as they are."""
    orgs = [r[0] for r in c.execute("SELECT DISTINCT org_id FROM office_docs WHERE producing_on IS NULL AND org_id IS NOT NULL").fetchall()]
    for oid in orgs:
        r = c.execute("SELECT data FROM office_settings WHERE org_id=?", (oid,)).fetchone()
        try:
            d = json.loads(r["data"]) if r and r["data"] else {}
        except ValueError:
            d = {}
        dflt = 1 if isinstance(d, dict) and d.get("producing_on") else 0  # a plain key (only "company" is encrypted)
        c.execute("UPDATE office_docs SET producing_on=CASE WHEN EXISTS (SELECT 1 FROM office_doc_items i WHERE i.doc_id=office_docs.id "
                  "AND i.producing=1) THEN 1 ELSE ? END WHERE org_id=? AND producing_on IS NULL", (dflt, oid))


# ---------------------------------------------------------------- 2.47.0 (#1649): purchase, surplus, purchases of accepted quotations
def ek_role_cost(c, oid, sv, unit):
    """The default purchase of a new position of service sv (row dict): the price of the service's freelancer role for the
    position's unit (part A's model.sr_role_cost; 0 when there is none). Later changes of the role leave positions alone."""
    from . import model
    fn = getattr(model, "sr_role_cost", None)
    if not fn or not sv.get("role_id"):
        return 0
    v = fn(c, oid, sv["role_id"], unit)
    return float(v) if v is not None else 0


def ek_item_margins(d, its):
    """Admins only (doc_public): the surplus of every position (its total minus purchase x quantity, in the document's
    currency) as it["margin"] and their sum as d["items_margin"]; from the positions and the computed lines, so nothing
    per position is stored unencrypted."""
    from .calc import dec, money, _num
    lines = {ln.get("id"): ln for ln in (d.get("totals") or {}).get("lines") or [] if ln.get("kind") == "item" and ln.get("id") is not None}
    from .homecur import hc_doc_fx
    fx = hc_doc_fx(d, (d.get("totals") or {}).get("home") or "EUR")  # 2.189.0 (#2475): the totals name the home currency
    tot, any_ = dec(0), False
    for it in its:
        ln = lines.get(it.get("id"))
        if (it.get("kind") or "service") != "service" or not ln:
            continue
        m = money(dec(ln.get("total")) - money(dec(it.get("cost")) * dec(ln.get("qty"), "1") * fx))
        it["margin"] = _num(m)
        tot += m
        any_ = True
    d["items_margin"] = _num(tot) if any_ else None


def ek_purchases_write(c, oid, did):
    """The purchase of quotation did in office_purchases, written anew: an accepted quotation gets one row per position of
    its title page with a purchase (source 'item', amount = purchase x quantity, ref = the position) and one per part it
    refers to (source 'part' / 'shoot', amount = the part's purchase from its totals x the quantity on the title page,
    ref = the part); any other status = no rows. date = the start of the period of service, else the day of acceptance;
    accepted_at = the day of acceptance (kept when an accepted quotation is written again). Amounts in the organisation's
    currency (purchases are entered in it), encrypted at rest. Returns the number of rows."""
    from .calc import dec, dstr
    from .model import office_settings
    r = c.execute("SELECT * FROM office_docs WHERE id=? AND org_id=?", (did, oid)).fetchone()
    old = c.execute("SELECT accepted_at FROM office_purchases WHERE doc_id=? AND org_id=? AND accepted_at<>'' ORDER BY id LIMIT 1", (did, oid)).fetchone()
    c.execute("DELETE FROM office_purchases WHERE doc_id=? AND org_id=?", (did, oid))
    if not r or r["kind"] != "offer" or r["status"] != "accepted":
        return 0
    acc = old["accepted_at"] if old else local_now().date().isoformat()
    day = r["service_from"] or acc
    from .homecur import hc_doc_fx, hc_home
    cur = hc_home(office_settings(c, oid))  # 2.189.0 (#2475): the home currency (purchases are entered in it)
    fx = hc_doc_fx(r, cur)
    out = []
    items = [oc_dec_fields(c, oid, "office_doc_items", x) for x in
             c.execute("SELECT * FROM office_doc_items WHERE doc_id=? AND org_id=? ORDER BY sort, id", (did, oid))]
    part_qty = {}
    for it in items:
        if it.get("part_id") is not None:
            continue  # a position inside a part: counted with the part
        if it.get("kind") == "part" and it.get("ref_part_id") is not None:
            part_qty[it["ref_part_id"]] = part_qty.get(it["ref_part_id"], dec(0)) + dec(it.get("qty"), "1")
            continue
        if (it.get("kind") or "service") != "service":
            continue
        qty = dec(1) if it.get("unit") == "percent" else dec(it.get("qty"), "1")
        amt = dec(it.get("cost")) * qty
        if amt > 0:
            out.append(("item", it["id"], it.get("title") or "", amt))
    if part_qty:
        for p in c.execute("SELECT * FROM office_doc_parts WHERE doc_id=? AND org_id=? ORDER BY sort, id", (did, oid)).fetchall():
            q = part_qty.get(p["id"])
            if not q:
                continue
            p = oc_dec_fields(c, oid, "office_doc_parts", p)
            try:
                t = json.loads(p.get("totals") or "{}")
            except ValueError:
                t = {}
            amt = dec((t or {}).get("costs")) / fx * q  # the part's totals are in the document's currency
            if amt > 0:
                out.append(("shoot" if p.get("kind") == "shoot" else "part", p["id"], p.get("title") or "", amt))
    ts = iso(now_utc())
    for src, ref, label, amt in out:
        row = oc_enc_fields(c, oid, "office_purchases", {"org_id": oid, "doc_id": did, "date": day, "accepted_at": acc, "amount": dstr(amt),
                                                         "currency": cur, "label": label[:500], "source": src, "ref": ref, "created_at": ts})
        c.execute(f"INSERT INTO office_purchases({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    return len(out)


def ek_purchases(c, oid, date_from=None, date_to=None):
    """The purchases of accepted quotations of organisation oid (decrypted, oldest first), date within [date_from,
    date_to] (ISO, each optional): [{id, doc_id, number, date, accepted_at, amount (text, 2 places), currency, label,
    source, ref}]. For the cash flow (#1652, admins only; there is no route for others)."""
    sql, args = ("SELECT p.*, d.number FROM office_purchases p JOIN office_docs d ON d.id=p.doc_id AND d.org_id=p.org_id "
                 "WHERE p.org_id=? AND d.trial=0"), [oid]  # 2.144.10 B (#2576): no purchases of trial quotations
    if date_from:
        sql += " AND p.date>=?"
        args.append(date_from)
    if date_to:
        sql += " AND p.date<=?"
        args.append(date_to)
    out = []
    for r in c.execute(sql + " ORDER BY p.date, p.id", args).fetchall():
        d = oc_dec_fields(c, oid, "office_purchases", r)
        out.append({k: d.get(k) for k in ("id", "doc_id", "number", "date", "accepted_at", "amount", "currency", "label", "source", "ref")})
    return out
