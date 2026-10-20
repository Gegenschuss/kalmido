"""2.146.0 B (#2452): duplicates of documents (receipts above all: the same invoice by mail and as a photo, a PDF uploaded
twice -- otherwise both go into the DATEV batch).

 - The same file: docs_ingest(dedup=True) (upload, share target, mail input) compares the sha256 of the bytes as they came
   (doc_meta.raw_sha) and of the stored version (fs_versions.sha256: documents from before 2.146) with the documents of the
   same workspace. A match the person may see is returned instead of a second copy (the caller says "already there").
 - The same invoice: after a recognition run (doc_on_done) a document with a recognised supplier / invoice number is
   compared with the older documents of its workspace: same supplier + same invoice number, or same supplier + same amount +
   same date (no supplier known: the invoice number alone, 4+ characters) -> doc_meta.dup_of = the older one. The document
   stays; the sheet warns with a link, "No duplicate" (dup_ok = 1) keeps the decision across new recognition runs.
 - The DATEV batch leaves a possible duplicate out unless the export asks for it (office/datevin.py)."""
import hashlib
import re
from decimal import Decimal, InvalidOperation

from . import store as S

DUP_SCAN = 300  # older documents of the workspace looked at for the same invoice


def raw_sha(data):
    return hashlib.sha256(bytes(data or b"")).hexdigest()


def _visible(c, nid, uid):
    from ..files.store import fs_chain, fs_deleted, fs_role
    ch = fs_chain(c, nid)
    return bool(ch) and not fs_deleted(ch) and (not uid or bool(fs_role(c, nid, uid, chain=ch)))


def dup_same_file(c, ws, sha, uid):
    """The id of a document of ws with these bytes that account uid may see (not in the trash), else None."""
    rows = c.execute("""SELECT d.node_id FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id
                        WHERE d.ws=? AND d.raw_sha=? AND n.deleted_at IS NULL ORDER BY d.node_id LIMIT 5""", (ws, sha)).fetchall()
    rows += c.execute("""SELECT d.node_id FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id
                         JOIN fs_versions v ON v.node_id=n.id AND v.no=n.cur_version
                         WHERE d.ws=? AND v.sha256=? AND n.deleted_at IS NULL ORDER BY d.node_id LIMIT 5""", (ws, sha)).fetchall()
    for r in rows:
        if _visible(c, r[0], uid):
            return r[0]
    return None


def _norm_no(v):
    return re.sub(r"[\s\-/._#:]+", "", str(v or "")).casefold()


def _amount(c, m, det):
    """The document's amount, else the recognised gross (a till receipt's amount is only set for an invoice type)."""
    for raw in (S.doc_open(c, m["ws"], "doc_meta.amount", m["amount"]), det.get("gross")):
        try:
            v = Decimal(str(raw or "").replace(",", "."))
        except (InvalidOperation, ValueError):
            continue
        if v != 0:
            return v
    return None


def _key(c, m):
    from ..receipts.extracted import _rx_norm
    det = S.meta_json(c, m, "extracted", {})
    return {"sender": m["sender_id"], "sup": _rx_norm(det.get("supplier")), "vat_id": str(det.get("vat_id") or "").upper(),
            "no": _norm_no(det.get("invoice_no")), "amount": _amount(c, m, det), "date": m["doc_date"] or ""}


def _same_supplier(a, b):
    return bool((a["sender"] and a["sender"] == b["sender"]) or (a["sup"] and a["sup"] == b["sup"])
                or (a["vat_id"] and a["vat_id"] == b["vat_id"]))


def _no_supplier(k):
    return not (k["sender"] or k["sup"] or k["vat_id"])


def dup_match(a, b):
    """Do the keys a / b look like the same invoice?"""
    if a["no"] and a["no"] == b["no"]:
        if _same_supplier(a, b) or ((_no_supplier(a) or _no_supplier(b)) and len(a["no"]) >= 4):
            return True
    return bool(a["amount"] is not None and a["amount"] == b["amount"] and a["date"] and a["date"] == b["date"] and _same_supplier(a, b))


def dup_find(c, m):
    """The id of an older document of m's workspace that looks like the same invoice, else None."""
    if not m["extracted"]:
        return None
    k = _key(c, m)
    if not (k["no"] or k["amount"] is not None):
        return None
    for r in c.execute("""SELECT d.* FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id
                          WHERE d.ws=? AND d.node_id<? AND d.extracted<>'' AND n.deleted_at IS NULL
                          ORDER BY d.node_id DESC LIMIT ?""", (m["ws"], m["node_id"], DUP_SCAN)).fetchall():
        if dup_match(k, _key(c, r)):
            return r["node_id"]
    return None


def dup_on_done(c, nid, first):
    """doc_on_done hook: mark (or clear) the possible duplicate after every recognition run, unless a person said no."""
    m = S.meta_row(c, nid)
    if not m or m["dup_ok"]:
        return
    other = dup_find(c, m)
    if other != m["dup_of"]:
        c.execute("UPDATE doc_meta SET dup_of=? WHERE node_id=?", (other, nid))


def dup_view(c, m, uid):
    """{id, name} of the older document a document may duplicate (the person sees it, it is not in the trash), else None."""
    if not m["dup_of"] or m["dup_ok"] or not uid:
        return None
    if not _visible(c, m["dup_of"], uid):
        return None
    r = c.execute("SELECT name FROM fs_nodes WHERE id=?", (m["dup_of"],)).fetchone()
    return {"id": m["dup_of"], "name": r["name"]} if r else None


def dup_open(c, ids):
    """The ids among ids that are a possible duplicate nobody confirmed (and whose older document is not in the trash)."""
    ids = [int(x) for x in ids]
    if not ids:
        return set()
    from ..files.store import fs_chain, fs_deleted
    out = set()
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        q = ",".join("?" * len(part))
        for r in c.execute(f"SELECT node_id, dup_of FROM doc_meta WHERE node_id IN ({q}) AND dup_of IS NOT NULL AND dup_ok=0", tuple(part)):
            ch = fs_chain(c, r["dup_of"])
            if ch and not fs_deleted(ch):
                out.add(r["node_id"])
    return out


def _hook():
    from .ingest import doc_on_done
    if dup_on_done not in doc_on_done:
        doc_on_done.append(dup_on_done)


_hook()
