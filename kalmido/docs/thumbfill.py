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
from ..files.store import fs_read  # 2.369.5 (#2517): pulled up from functions
from ..tasks.attachtext import file_kind  # 2.369.5 (#2517): pulled up from functions
from . import store as S  # 2.369.5 (#2517): pulled up from functions
from ..core.access import live_sql  # 2.836.0 (#5390): the trash condition of the scan mark's catch-up
from .scanmark import ScanBusy, scan_of  # 2.836.0 (#5390)

FILL = env_bool("KALMIDO_DOCS_THUMB_FILL", True)
FILL_S = max(1, int(os.environ.get("KALMIDO_DOCS_THUMB_FILL_S", "15") or 15))  # s between two portions
FILL_N = 5           # documents per portion
FILL_KEY = "docs_thumb_fill"  # settings: {"below": lowest node id handled so far} or {"done": 1}
_Q = {"at": 0.0}


def _fill_asn(c, S, nid, n, node):
    """2.363.3 (#3133): archive number n from a code into a document that has none, under asn_lock: a save with "next" at the
    same moment no longer ends in the unique index (the lock is the same one as for docs/store.py process), and a number set
    by hand meanwhile stays."""
    ws = S.meta_row(c, nid)["ws"]
    S.asn_lock(c, ws, nid)
    m = S.meta_row(c, nid)
    if m["asn"] or S.asn_taken(c, ws, n, nid):
        return
    auto = S.meta_json(c, m, "auto", {})
    auto["asn"] = "code"
    c.execute("UPDATE doc_meta SET asn=?, auto=? WHERE node_id=?", (n, json.dumps(auto, separators=(",", ":")), nid))
    m = S.meta_row(c, nid)
    S.doc_index(c, nid, ws, S.index_text(c, dict(m), node["name"], S.meta_text(c, m)))


def p61a_thumb_fill(c):
    """One portion of the catch-up (the caller runs it in the queue's system context and commits). Returns the number of
    documents looked at; 0 when it is not time yet or the catch-up is done."""
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
            code = None
            with c.savepoint():  # one broken document never stops the catch-up
                m = S.meta_row(c, nid)
                node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
                data = fs_read(c, nid)
                kind = file_kind(node["name"], node["mime"], data[:2048])
                S.thumb_store(c, m, node, data, kind)
                if not m["asn"]:
                    from .ocr import qr_codes
                    code = S.EX.find_asn(S.cfg_get(c, m["ws"])["asn_prefix"], (), codes=qr_codes(data, kind))  # 2.591.0 B (#4863): codes apart
            if code:
                c.commit()  # 2.363.3 (#3133): the number lock is held for this one write, not over the next documents of the portion
                with c.savepoint():
                    _fill_asn(c, S, nid, code, node)
                c.commit()  # the number lock ends here (review): the rest of the portion renders previews without it
        except Exception as e:  # noqa: BLE001 -- a missing file, a key that does not open, a broken image: skip it
            print("docs: preview catch-up", nid, type(e).__name__, e, flush=True)
    gset(c, FILL_KEY, json.dumps({"below": rows[-1][0]}))
    return len(rows)


# 2.583.0 (#4812): the sharper preview (800 px, doc_meta.thumb_l) for documents from before -- the same catch-up pattern: only
# while the queue is idle and after the catch-up above is done, a portion every FILL_S seconds, newest first, its own position
# (FILL_L_KEY), "done" at the end. A document with a small preview but no sharp one gets it; one that fails is skipped (log),
# its card keeps the small one. Each with its own workspace (fs_read / thumb_store_l seal like thumb_store).
FILL_L_KEY = "docs_thumb_l_fill"  # settings: {"below": lowest node id handled so far} or {"done": 1}
_QL = {"at": 0.0}


def p2583_thumb_l_fill(c):
    """One portion of the catch-up of the sharp previews (run like p61a_thumb_fill in the queue's system context, the caller
    commits). Returns the number of documents looked at; 0 when it is not time yet, the small catch-up still runs, or done."""
    if not FILL or time.monotonic() - _QL["at"] < FILL_S:
        return 0
    try:
        if not json.loads(gsetting(c, FILL_KEY) or "{}").get("done"):
            return 0  # the small previews first
        st = json.loads(gsetting(c, FILL_L_KEY) or "{}")
    except (ValueError, AttributeError):
        st = {}
    _QL["at"] = time.monotonic()
    st = st if isinstance(st, dict) else {}
    if st.get("done"):
        return 0
    below = int(st.get("below") or 2 ** 62)
    rows = c.execute("""SELECT d.node_id FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id
                        WHERE d.node_id < ? AND d.state='done' AND COALESCE(d.thumb, '')<>'' AND COALESCE(d.thumb_l, '')=''
                          AND n.deleted_at IS NULL
                        ORDER BY d.node_id DESC LIMIT ?""", (below, FILL_N)).fetchall()
    if not rows:
        gset(c, FILL_L_KEY, json.dumps({"done": 1}))
        return 0
    for (nid,) in rows:
        try:
            with c.savepoint():  # one broken document never stops the catch-up
                m = S.meta_row(c, nid)
                node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
                data = fs_read(c, nid)
                S.thumb_store_l(c, m, node, data, file_kind(node["name"], node["mime"], data[:2048]))
        except Exception as e:  # noqa: BLE001 -- a missing file, a key that does not open, a broken image: skip it
            print("docs: sharp preview catch-up", nid, type(e).__name__, e, flush=True)
    gset(c, FILL_L_KEY, json.dumps({"below": rows[-1][0]}))
    return len(rows)


# 2.781.0 (#5390): the scan mark (doc_meta.auto["_scan"], docs/scanmark.py) for documents recognised before it existed -- the
# same catch-up pattern: only while the queue is idle, a portion every FILL_S seconds, newest first, its own position
# (FILL_SCAN_KEY), "done" at the end. Only PDFs, pictures and documents of a scan inbox are looked at (anything else is no
# scan, the missing mark says so already); a document that cannot be told now keeps no mark (its next recognition sets it).
FILL_SCAN_KEY = "docs_scan_fill"  # settings: {"below": lowest node id handled so far} or {"done": 1}
_QS = {"at": 0.0}


def p5390_scan_fill(c):
    """One portion of the catch-up of the scan mark (run like p61a_thumb_fill in the queue's system context, the caller
    commits). Returns the number of documents looked at; 0 when it is not time yet or done."""
    if not FILL or time.monotonic() - _QS["at"] < FILL_S:
        return 0
    _QS["at"] = time.monotonic()
    try:
        st = json.loads(gsetting(c, FILL_SCAN_KEY) or "{}")
    except ValueError:
        st = {}
    st = st if isinstance(st, dict) else {}
    if st.get("done"):
        return 0
    below = int(st.get("below") or 2 ** 62)
    rows = c.execute(f"""SELECT d.node_id FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id
                        WHERE d.node_id < ? AND d.state='done' AND POSITION('"_scan"' IN COALESCE(d.auto, ''))=0 AND {live_sql("n")}
                          AND (d.source='scan' OR LOWER(n.mime)='application/pdf' OR LOWER(n.mime) LIKE 'image/%' OR LOWER(n.name) LIKE '%.pdf')  -- pg-ok: LOWER() on the column
                        ORDER BY d.node_id DESC LIMIT ?""", (below, FILL_N)).fetchall()  # pg-ok: LOWER() on the column only
    if not rows:
        gset(c, FILL_SCAN_KEY, json.dumps({"done": 1}))
        return 0
    for (nid,) in rows:
        try:
            with c.savepoint():  # one broken document never stops the catch-up
                m = S.meta_row(c, nid)
                node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
                data = fs_read(c, nid)
                ei = bool(S.meta_json(c, m, "extracted", {}).get("_einv")) if m["extracted"] else False
                scan = scan_of(node["name"], node["mime"], data, file_kind(node["name"], node["mime"], data[:2048]), m["source"], einvoice=ei, busy=True)
                if scan is not None:
                    r = c.execute("SELECT auto FROM doc_meta WHERE node_id=? FOR UPDATE", (nid,)).fetchone()  # a save meanwhile stays
                    auto = json.loads(r["auto"] or "{}") if r else None
                    if isinstance(auto, dict) and "_scan" not in auto:
                        auto["_scan"] = scan
                        c.execute("UPDATE doc_meta SET auto=? WHERE node_id=?", (json.dumps(auto, separators=(",", ":")), nid))
            c.commit()  # the row lock ends here, not after the whole portion
        except ScanBusy:  # 2.836.0 (#5390, review): no free PDF slot -- this document again in the next portion, not skipped for good
            c.rollback()
            gset(c, FILL_SCAN_KEY, json.dumps({"below": nid + 1}))
            return 1
        except Exception as e:  # noqa: BLE001 -- a missing file, a key that does not open, a broken PDF: skip it
            print("docs: scan mark catch-up", nid, type(e).__name__, e, flush=True)
    gset(c, FILL_SCAN_KEY, json.dumps({"below": rows[-1][0]}))
    return len(rows)
