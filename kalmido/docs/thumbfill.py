"""2.66.1 (#1944): catch-up of the preview images of documents imported with their text (Paperless, ZIP import) before
the recognition run made a preview for them. Once after the update, in the documents queue (docs/ingest.py) and only while
nothing waits there: at most FILL_N documents every FILL_S seconds, newest first, the position in the settings (a restart
goes on where it stopped), "done" at the end -- then it never runs again. Each document is handled with its own workspace:
fs_read opens the file with its organisation's key / the private space's key, thumb_store seals the preview the same way.
Only the preview and (while the document has none) the archive number from a QR code are filled in; text, sender, type,
folder and the review state stay as they are. A document that fails is skipped (log), the run goes on.
KALMIDO_DOCS_THUMB_FILL=off switches it off."""
import json
import os
import time

from ..core.db import gsetting, gset
from ..core.env import env_bool

FILL = env_bool("KALMIDO_DOCS_THUMB_FILL", True)
FILL_S = max(1, int(os.environ.get("KALMIDO_DOCS_THUMB_FILL_S", "15") or 15))  # s between two portions
FILL_N = 5           # documents per portion
FILL_KEY = "docs_thumb_fill"  # settings: {"below": lowest node id handled so far} or {"done": 1}
_Q = {"at": 0.0}


def p61a_thumb_fill(c):
    """One portion of the catch-up (the caller runs it in the queue's system context and commits). Returns the number of
    documents looked at; 0 when it is not time yet or the catch-up is done."""
    from ..files.store import fs_read
    from ..tasks.attachtext import file_kind
    from . import store as S
    if not FILL or time.monotonic() - _Q["at"] < FILL_S:
        return 0
    _Q["at"] = time.monotonic()
    try:
        st = json.loads(gsetting(c, FILL_KEY) or "{}")
    except ValueError:
        st = {}
    st = st if isinstance(st, dict) else {}
    if st.get("done"):
        return 0
    below = int(st.get("below") or 2 ** 62)
    rows = c.execute("""SELECT d.node_id FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id
                        WHERE d.node_id < ? AND d.state='done' AND COALESCE(d.thumb, '')='' AND n.deleted_at IS NULL
                          AND (LOWER(n.mime)='application/pdf' OR LOWER(n.mime) LIKE 'image/%' OR LOWER(n.name) LIKE '%.pdf')  -- pg-ok: LOWER() on the column
                        ORDER BY d.node_id DESC LIMIT ?""", (below, FILL_N)).fetchall()  # pg-ok: LOWER() on the column only
    if not rows:
        gset(c, FILL_KEY, json.dumps({"done": 1}))
        return 0
    for (nid,) in rows:
        try:
            with c.savepoint():  # one broken document never stops the catch-up
                m = S.meta_row(c, nid)
                node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
                data = fs_read(c, nid)
                kind = file_kind(node["name"], node["mime"], data[:2048])
                S.thumb_store(c, m, node, data, kind)
                if not m["asn"]:
                    from .ocr import qr_codes
                    n = S.EX.find_asn(S.cfg_get(c, m["ws"])["asn_prefix"], qr_codes(data, kind))
                    if n and not S.asn_taken(c, m["ws"], n, nid):
                        auto = S.meta_json(c, m, "auto", {})
                        auto["asn"] = "code"
                        c.execute("UPDATE doc_meta SET asn=?, auto=? WHERE node_id=?", (n, json.dumps(auto, separators=(",", ":")), nid))
                        m = S.meta_row(c, nid)
                        S.doc_index(c, nid, m["ws"], S.index_text(c, dict(m), node["name"], S.meta_text(c, m)))
        except Exception as e:  # noqa: BLE001 -- a missing file, a key that does not open, a broken image: skip it
            print("docs: preview catch-up", nid, type(e).__name__, e, flush=True)
    gset(c, FILL_KEY, json.dumps({"below": rows[-1][0]}))
    return len(rows)
