"""2.778.0 (#5383): the preview of a receipt on the candidate cards (credit card positions, bank bookings, office_cand.js).
No new file processing: the address of a picture that already exists -- the document's stored preview (GET /api/docs/<id>/thumb,
made at its recognition, PDF page 1 or the image) or, for a picture file without one, the file store's small preview made on
request (GET /api/files/nodes/<id>/thumb). Both routes check the rights themselves; the candidates handed in here are already
the ones the person sees (cardlines.cl_found / bank._receipts). No preview (a PDF not recognised yet, a locked folder): None,
the card shows its icon."""
from urllib.parse import quote


def oc_thumbs(c, nids):
    """{node_id: address of its small preview} for the files nids (live, not deleted); files without one are missing."""
    ids = sorted({int(n) for n in nids if n})
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    out = {}
    for r in c.execute(f"SELECT n.id, n.mime, n.cur_version, d.thumb, d.updated_at FROM fs_nodes n LEFT JOIN doc_meta d ON d.node_id=n.id "
                       f"WHERE n.id IN ({q}) AND n.kind='file' AND n.deleted_at IS NULL", ids).fetchall():
        if r["thumb"]:
            out[r["id"]] = f"/api/docs/{int(r['id'])}/thumb?v={quote(str(r['updated_at'] or ''), safe='')}"
        elif str(r["mime"] or "").startswith("image/"):
            out[r["id"]] = f"/api/files/nodes/{int(r['id'])}/thumb?v={int(r['cur_version'] or 0)}"
    return out


def oc_with_thumbs(c, items, kinds=("receipt",)):
    """items [{id, kind?, ...}] with "thumb" (address or None): the receipts (a kind in kinds, or no kind = a document); an
    invoice or a card statement keeps None. Returns items."""
    docs = [x for x in items if x and (x.get("kind") in kinds or "kind" not in x)]
    th, mine = oc_thumbs(c, [x["id"] for x in docs]), {id(x) for x in docs}
    for x in items:
        if x:
            x["thumb"] = th.get(x["id"]) if id(x) in mine else None
    return items
