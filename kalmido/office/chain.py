"""2.531.0 (#4497): the hash chain over finalised documents.

Every finalised invoice, credit note, reminder and delivery note joins the chain of its office (organisation or personal
office) and number series (chain_key = the counter it counts with, models.num_kind: credit notes on the invoices' counter share
that chain) when it is finalised:

    chain_hash = sha256(chain_prev + canonical data of the document)      chain_prev = chain_hash of the one before ('' = first)
    chain_seq  = its place in that chain (1, 2, ...)

Quotations and trial documents stay outside: a quotation may be taken back to a draft (ledger.ofx_unlock_post) and a trial
document deleted at any time (docs.trial_drop_doc) -- both would break the chain in everyday use.

The canonical data (hch_canon) is deterministic JSON (sorted keys, fixed separators, numbers as plain text) of the fields that
never change after finalising (HCH_DOC_FIELDS, HCH_ITEM_FIELDS, HCH_TAX_KEYS): number, kind, date, service period, currency,
locked_at, the recipient snapshot, the sender snapshot (decrypted: switching the encryption on or a new key changes nothing),
the positions, the totals (without the internal purchase prices / margin) and the frozen rates. Fields that change after
finalising on purpose stay out: status, paid / paid_at, due date, reminder level / fee state, sent_at, DATEV mark, the stored
files' checksums, notes, project / list links, cash flow, terms.

hch_check recomputes every chain of an office: {ok, count, pending, first_bad: {id, number, chain} | None}. A document that was
changed, removed from the middle, moved to another chain or unlocked in the database is the first bad one of its chain;
pending = finalised documents not chained yet (an import of a whole office, a start before the next one chains them).
Removing the newest document of a chain leaves no trace in the chain itself (the office log keeps its finalise entry)."""
import hashlib
import json
from decimal import Decimal

from ..core.moneycol import mc_fields  # 2.755.0 (#5293)
from ..core.orgcrypt import oc_dec_fields
from ..core.pg import write_lock
from ..core.access import live_sql  # 2.1005.0 (#5415)
from .model import num_kind, office_settings, ofx_release  # 2.542.0 (#4598): freeing a copied place passes the trigger

HCH_DOC_FIELDS = ("number", "kind", "date", "service_from", "service_to", "currency", "locked_at")
HCH_JSON_FIELDS = {"recipient_snapshot": "recipient", "sender": "sender", "totals": "totals"}
HCH_TOTALS_SKIP = ("costs", "margin")  # internal (purchase side), encrypted on their own, never printed
HCH_TAX_KEYS = ("rates", "tax")  # of tax_snapshot
HCH_ITEM_FIELDS = ("kind", "title", "detail", "qty", "unit", "rate", "tax", "tax_pct", "net", "tax_amount")


def hch_chained(r):
    """Does document row r join a chain when it is finalised? (not a quotation, not a trial document)"""
    return r["kind"] != "offer" and not (r["trial"] if "trial" in r.keys() else 0)


def _plain(v):
    if isinstance(v, Decimal):
        return format(v.normalize(), "f")
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return v


def _json(v, dflt):
    if isinstance(v, (dict, list)):
        return v
    try:
        x = json.loads(v or "")
    except (TypeError, ValueError):
        return dflt
    return x


def hch_canon(c, oid, r):
    """The canonical text of document row r (a raw or decrypted office_docs row) of office oid."""
    d = oc_dec_fields(c, oid, "office_docs", r)
    out = {k: d.get(k) for k in HCH_DOC_FIELDS}
    for col, key in HCH_JSON_FIELDS.items():
        out[key] = _json(d.get(col), {})
    if isinstance(out["totals"], dict):
        out["totals"] = {k: v for k, v in out["totals"].items() if k not in HCH_TOTALS_SKIP}
    tax = _json(d.get("tax_snapshot"), {})
    out["tax"] = {k: tax.get(k) for k in HCH_TAX_KEYS} if isinstance(tax, dict) else {}
    # 2.755.0 (#5293): net / tax_amount are NUMERIC now: the same text as before ("23.80", None), the checksums stay
    out["items"] = [mc_fields("office_doc_items", {k: it[k] for k in HCH_ITEM_FIELDS}) for it in c.execute(
        f"SELECT {', '.join(HCH_ITEM_FIELDS)} FROM office_doc_items WHERE doc_id=? AND {live_sql()} ORDER BY sort, id", (d["id"],))]  # 2.1005.0 (#5415): not the trash (a trashed part's positions may be purged later)
    return json.dumps(_plain(out), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def hch_hash(prev, canon):
    return hashlib.sha256((prev + canon).encode("utf-8")).hexdigest()


def _tail(c, oid, key):
    t = c.execute("SELECT chain_seq, chain_hash FROM office_docs WHERE org_id=? AND chain_key=? AND chain_seq IS NOT NULL "
                  "ORDER BY chain_seq DESC LIMIT 1", (oid, key)).fetchone()
    return (int(t["chain_seq"]), t["chain_hash"] or "") if t else (0, "")


def _link(c, oid, r, key):
    seq, prev = _tail(c, oid, key)
    h = hch_hash(prev, hch_canon(c, oid, r))
    c.execute("UPDATE office_docs SET chain_key=?, chain_seq=?, chain_prev=?, chain_hash=? WHERE id=? AND org_id=?",
              (key, seq + 1, prev, h, r["id"], oid))
    return h


def hch_pending(c, oid):
    """Finalised documents of office oid that belong in a chain and have no place yet, oldest first."""
    return [r for r in c.execute("SELECT * FROM office_docs WHERE org_id=? AND locked_at IS NOT NULL AND chain_seq IS NULL AND kind<>'offer' "
                                 f"AND COALESCE(trial, 0)=0 AND {live_sql()} ORDER BY locked_at, id", (oid,))]  # 2.1005.0 (#5415): not the trash


def hch_append(c, oid, did=None, s=None):
    """Chains the finalised documents of office oid that have no place yet (older ones first: an import, documents from
    before 2.531), then document did (just finalised). Under the office's chain lock; the caller commits."""
    write_lock(c, f"office_chain_{int(oid)}")
    s = s if s is not None else office_settings(c, oid)
    for r in hch_pending(c, oid):
        _link(c, oid, r, num_kind(s, r["kind"]))
    if did is not None:
        r = c.execute(f"SELECT * FROM office_docs WHERE id=? AND org_id=? AND {live_sql()}", (did, oid)).fetchone()  # 2.1005.0 (#5415): not the trash
        if r is not None and r["chain_seq"] is None and r["locked_at"] and hch_chained(r):
            _link(c, oid, r, num_kind(s, r["kind"]))


def hch_check(c, oid):
    """Recomputes every chain of office oid -> {ok, count, pending, first_bad}. first_bad = the first document (of the first
    broken chain, by its first finalising) whose link or data does not fit."""
    bad, count = [], 0
    keys = [x[0] for x in c.execute("SELECT DISTINCT chain_key FROM office_docs WHERE org_id=? AND chain_seq IS NOT NULL ORDER BY chain_key", (oid,))]
    for key in keys:
        prev, want = "", 1
        for r in c.execute("SELECT * FROM office_docs WHERE org_id=? AND chain_key=? AND chain_seq IS NOT NULL ORDER BY chain_seq, id", (oid, key)).fetchall():
            count += 1
            # review job/2606: why it breaks - gap (a document before it is gone), link, unlocked or data
            why = "gap" if int(r["chain_seq"]) != want else "link" if (r["chain_prev"] or "") != prev else "unlocked" if not r["locked_at"] else ""
            if not why:
                try:
                    why = "" if hch_hash(prev, hch_canon(c, oid, r)) == (r["chain_hash"] or "") else "data"
                except Exception:  # noqa: BLE001 -- a value that cannot be read (decryption) is a break as well
                    why = "data"
            if why:
                bad.append({"id": r["id"], "number": r["number"] or "", "chain": key, "seq": int(r["chain_seq"]), "reason": why})
                break
            prev, want = r["chain_hash"] or "", want + 1
    first = min(bad, key=lambda b: b["id"]) if bad else None
    return {"ok": not bad, "count": count, "pending": len(hch_pending(c, oid)), "first_bad": first}


def hch_migrate(c):
    """Every start (core/db.py init_db through ledger.ofx_migrate): offices with finalised documents not chained yet (documents
    from before 2.531, an imported office) get them chained in the order they were finalised. Idempotent (only rows without a
    place); an office whose data cannot be read now (decryption) is left for the next start / its next finalising."""
    # review job/2606: a place copied by an older version (rollback: duplicate / recurring invoice took the chain columns along)
    # is no place - a draft, or the later of two rows on one place, gets chained anew when it is finalised / at this start
    with ofx_release(c):
        c.execute("UPDATE office_docs SET chain_key='', chain_seq=NULL, chain_prev='', chain_hash='' WHERE chain_seq IS NOT NULL AND "
                  "(locked_at IS NULL OR EXISTS (SELECT 1 FROM office_docs o WHERE o.org_id=office_docs.org_id AND o.chain_key=office_docs.chain_key "
                  "AND o.chain_seq=office_docs.chain_seq AND o.chain_hash=office_docs.chain_hash AND o.id<office_docs.id))")
    for (oid,) in c.execute("SELECT DISTINCT org_id FROM office_docs WHERE locked_at IS NOT NULL AND chain_seq IS NULL AND kind<>'offer' "
                            f"AND COALESCE(trial, 0)=0 AND {live_sql()}").fetchall():  # 2.1005.0 (#5415): not the trash
        try:
            with c.savepoint():
                hch_append(c, oid)
        except Exception:  # noqa: BLE001 -- never stop the start for this
            continue
