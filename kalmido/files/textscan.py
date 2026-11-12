"""2.61.0 (#1820): text recognition for normal stored files in the background -- task / comment files ("att"), project
files ("list") and Ablage files that are no document ("fs"; a document has its own recognition in docs/).

The upload only adds a file_text row (state wait, ts_after_store) and wakes the queue; it never waits for the
recognition. The queue is one thread in the server process (like docs/ingest.py): it takes the waiting files one by one,
reads them through the app's readers (sealed files decrypted), recognises their text with the documents' tools
(docs/ocr.py doc_text: the PDF text layer first, else Tesseract -- same limits, same semaphore, nothing leaves the
container) and keeps the text sealed with the workspace key plus a keyed word index (2.1002.0 #5279: the shared word index
obj_search_words, kind 'file_text', core/objwords.py; was file_words). Documents
go first: while the documents queue has work, the files wait. The same content in the same workspace (sha256) takes the
text over instead of a second recognition. A slow catch-up (backfill) queues files stored before this release: at most one
every BACKFILL_S seconds, only when both queues are idle, newest first, its position kept in the settings (a restart goes
on where it stopped). KALMIDO_FILE_OCR=off switches the whole recognition of files off, KALMIDO_FILE_OCR_BACKFILL=off only
the catch-up.

The text serves the search -- the task search (a task file's text finds its task, "in file <name>"), the Ablage search
(name + text, also project files) -- and agents (GET /api/v1/attachments/<id>/text of a scan, source "ocr"). Every hit is
checked against the file's own visibility; a deleted file takes its row with it (foreign keys, ON DELETE CASCADE)."""
import hashlib
import json
import os
import threading
import time
from datetime import timedelta

from flask import request

from ..core.config import app, ATT_DIR
from ..core.db import connect, db, gsetting, gset, iso, now_utc
from ..core.i18n import tr
from ..core.pg import system_ctx
from ..accounts.session import bg_here, me
from ..accounts.orgretain import odl_before_delete
from ..core.access import Denied, acx_of, vis_sql
from ..docs import store as S
from ..core.srchreg import srch_register  # 2.1026.0 (#5280)
from ..core.objsearch import osr_name_cond  # 2.1026.0 (#5280)
from ..core.objwords import osw_copy, osw_drop, osw_match, osw_prefilter, osw_put, osw_register, osw_terms  # 2.1002.0 (#5279)
from ..core.env import env_bool
from ..core.orgcrypt import oc_read_file  # 2.149.0 G (#2517): pulled up from functions
from .fslock import fl_is_locked  # 2.353.0 A (#2758)
from .fsviews import fsv_drop  # 2.429.0 (#3580)

KINDS = ("att", "list", "fs")
COL = {"att": "att_id", "list": "list_file_id", "fs": "node_id"}
ON = env_bool("KALMIDO_FILE_OCR", True)
BACKFILL = ON and env_bool("KALMIDO_FILE_OCR_BACKFILL", True)
BACKFILL_S = max(1, int(os.environ.get("KALMIDO_FILE_OCR_BACKFILL_S", "20") or 20))  # s between two files of the catch-up
MAX_MB = max(1, int(os.environ.get("KALMIDO_FILE_OCR_MAX_MB", "50") or 50))  # larger files are not read
REHOME_S = max(1, int(os.environ.get("KALMIDO_FILE_OCR_REHOME_S", "300") or 300))  # s between two workspace sweeps
# 2.92.0 C (#1926): + Word / Excel (.docx / .xlsx: their text through the limited worker of files/officeprev.py, no OCR)
MIMES = ("application/pdf", "image/jpeg", "image/png", "image/heic", "image/heif",
         "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
EXTS = (".pdf", ".jpg", ".jpeg", ".png", ".heic", ".heif", ".docx", ".xlsx")
IDLE = 5             # s the queue sleeps when there is nothing to do
# min after which a cut-off run is taken up again. 2.81.0 (#1856): longer than the longest recognition (pages x time per
# page, docs/ocr.py: 30 x 60 s by default) plus a margin, so a slow scan is never recognised twice at the same time
RUN_STALE = 45
TRIES = 3
SEARCH_MAX = 100     # hits of the Ablage search
BF_KEY = "ts_backfill"  # settings: {kind: lowest id queued so far, "done": [kinds]}
_Q = {"thread": None, "bf": 0.0}
_WAKE = threading.Event()
_LOCK = threading.Lock()
_HAS = {}


from ..core.db import now_iso as _now  # noqa: E402  2.149.0 G (#2517): was an own copy
from ..accounts.session import GATE  # 2.369.5 (#2517): pulled up from functions
from .scan import _sc_magic  # 2.369.5 (#2517): pulled up from functions
from .officeprev import dpv_kind, dpv_model  # 2.369.5 (#2517): pulled up from functions
from ..docs.ocr import TEXT_CAP, doc_text  # 2.369.5 (#2517): pulled up from functions
from .store import fs_visible_sql_c, fs_read  # 2.369.5 (#2517): pulled up from functions
from .web import _items  # 2.369.5 (#2517): pulled up from functions
from ..lists.projects import need_overview  # 2.369.5 (#2517): pulled up from functions


def _wanted(name, mime):
    return (mime or "").lower() in MIMES or (name or "").lower().endswith(EXTS)


def _ref(c, kind, ref_id):
    """{name, mime, size, path?, org_id, ws} of a stored file the recognition may read, else None (gone, encrypted in the
    browser, a folder / link)."""
    if kind == "att":
        r = c.execute("""SELECT a.name, a.mime, a.size, a.path, a.enc, l.org_id, l.owner_id FROM attachments a
                         JOIN tasks t ON t.id=a.task_id JOIN lists l ON l.id=t.list_id WHERE a.id=?""", (ref_id,)).fetchone()
        if not r or r["enc"]:
            return None
    elif kind == "list":
        r = c.execute("""SELECT f.name, f.mime, f.size, f.path, l.org_id, l.owner_id FROM list_files f JOIN lists l ON l.id=f.list_id
                         WHERE f.id=?""", (ref_id,)).fetchone()
    elif kind == "fs":
        r = c.execute("SELECT name, mime, size, kind, org_id, owner_id, e2e_gen FROM fs_nodes WHERE id=?", (ref_id,)).fetchone()
        if not r or r["kind"] != "file" or r["e2e_gen"]:  # 2.353.0 A (#2758): a ciphertext of a locked folder is never read
            return None
        if fl_is_locked(c, ref_id):
            return None  # 2.353.0 A (#2758): nor a plain file waiting for its conversion
    else:
        return None
    if not r:
        return None
    d = dict(r)
    d["ws"] = S.doc_ws(d["org_id"], d["owner_id"])
    return d


def _read(c, kind, ref_id, ref):
    """The plain bytes of the file (sealed organisation files decrypted, the current version of an Ablage file)."""
    if kind == "fs":
        return fs_read(c, ref_id)
    return oc_read_file(c, os.path.join(ATT_DIR, ref["path"]))


def ts_after_store(c, kind, ref_id, org_id, info):
    """Queue the text recognition of the stored file (never slows the upload down). A new version of an Ablage file
    is recognised anew."""
    if not ON or kind not in KINDS or (info or {}).get("scan") == "infected":
        return None
    ref = _ref(c, kind, ref_id)
    if not ref or not _wanted(ref["name"], ref["mime"]):
        return None
    _enqueue(c, kind, ref_id, ref)
    ts_kick()
    return None


def _enqueue(c, kind, ref_id, ref):
    ts = _now()
    r = c.execute(f"""INSERT INTO file_text(kind, ref_id, {COL[kind]}, org_id, ws, state, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)
                      ON CONFLICT(kind, ref_id) DO UPDATE SET state='wait', tries=0, error='', method='', text='', pages=0,
                      org_id=excluded.org_id, ws=excluded.ws,
                      truncated=0, sha256='', updated_at=excluded.updated_at RETURNING id""",
                  (kind, ref_id, ref_id, ref["org_id"], ref["ws"], "wait", ts, ts)).fetchone()
    osw_drop(c, "file_text", [r[0]])  # the old version's words go at once (2.1002.0 #5279: the shared word index)


def ts_marks(c, kind, ids):
    """{id: {"text": "found"|"none"|"wait"}} for the files of `kind` the recognition has seen (nothing for files it could
    not read, documents, or while it is off)."""
    if kind not in KINDS or not ids:
        return {}
    ids = [int(i) for i in ids][:5000]
    q = ",".join("?" * len(ids))
    sql = f"SELECT ref_id, state FROM file_text WHERE kind=? AND ref_id IN ({q}) AND state IN ('wait', 'run', 'found', 'none')"
    if kind == "fs":  # a document shows its own recognition
        sql += " AND NOT EXISTS (SELECT 1 FROM doc_meta d WHERE d.node_id=file_text.ref_id)"
    return {r["ref_id"]: {"text": "wait" if r["state"] == "run" else r["state"]} for r in c.execute(sql, (kind, *ids))}


def ts_forget(c, kind, ref_id):
    """Drop the recognised text of a file (its index words go with it), e.g. when a later virus scan finds something."""
    c.execute("DELETE FROM file_text WHERE kind=? AND ref_id=?", (kind, ref_id))


def ts_text(c, kind, ref_id):
    """The recognised text of a file (the caller checked the rights) or None."""
    r = c.execute("SELECT ws, text, state, pages, truncated FROM file_text WHERE kind=? AND ref_id=?", (kind, ref_id)).fetchone()
    if not r or r["state"] != "found":
        return None
    return {"text": S.doc_open(c, r["ws"], "file_text.text", r["text"]) or "", "pages": r["pages"], "truncated": bool(r["truncated"])}


def ts_fill(c, kind, ref_id, out, max_chars=200_000):
    """A text answer of a scan without a text layer / of an image (tasks/attachtext.py text_of_bytes) gets the recognised
    text, marked source "ocr" (agents: read_attachment / read_file)."""
    if not (out.get("no_text_layer") or out.get("kind") == "image"):
        return out
    o = ts_text(c, kind, ref_id)
    if o:
        t = o["text"]
        out.update(text=t[:max_chars], chars=min(len(t), max_chars), truncated=o["truncated"] or len(t) > max_chars, source="ocr", message=None)
    return out


# ---- the queue ------------------------------------------------------------------------------------------------------------
def ts_kick():
    """Wake the queue (start it when it does not run yet)."""
    if not ON:
        return
    if not bg_here():  # 2.193.0 D (#2220): role web -- the worker runs the queue from its table
        return
    with _LOCK:
        if _Q["thread"] is None or not _Q["thread"].is_alive():
            _Q["thread"] = threading.Thread(target=_loop, daemon=True, name="filetext")
            _Q["thread"].start()
    _WAKE.set()


@app.before_request
def _ts_start():
    if _Q["thread"] is None and ON:
        ts_kick()


def _loop():
    time.sleep(2)
    while True:
        n = 0
        try:
            with GATE.bg():
                n = ts_run_once()
        except Exception as e:  # noqa: BLE001 -- the queue never dies
            print("filetext: queue", type(e).__name__, e, flush=True)
            time.sleep(IDLE)
        if not n:
            _WAKE.wait(IDLE)
            _WAKE.clear()


def _docs_busy(c):
    return bool(c.execute("""SELECT 1 FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id WHERE d.state IN ('wait', 'run')
                             AND n.deleted_at IS NULL LIMIT 1""").fetchone())


_REHOME = {"at": 0.0}
_WS_SQL = "CASE WHEN {0}.org_id IS NOT NULL THEN 'o' || {0}.org_id ELSE 'u' || {0}.owner_id END"
_REHOME_SQL = {  # kind -> (FROM / WHERE joining the file's workspace owner as "w")
    "att": "FROM attachments a JOIN tasks t ON t.id=a.task_id JOIN lists w ON w.id=t.list_id WHERE f.kind='att' AND f.att_id=a.id",
    "list": "FROM list_files lf JOIN lists w ON w.id=lf.list_id WHERE f.kind='list' AND f.list_file_id=lf.id",
    "fs": "FROM fs_nodes w WHERE f.kind='fs' AND f.node_id=w.id",
}


def _rehome(c, org_id=None):
    """2.61.0 review: a file whose workspace changed (its list / task / folder moved between organisations or into a
    private space) is recognised again under the new workspace (key, index, row rights); every 5 minutes.
    2.209.0 D (#1856): org_id = at once, only the rows still kept for that organisation (ts_org_rehome)."""
    if org_id is None:
        if time.time() - _REHOME["at"] < REHOME_S:
            return
        _REHOME["at"] = time.time()
    more, args = (" AND f.org_id=?", (int(org_id),)) if org_id is not None else ("", ())
    moved = []
    for kind, src in _REHOME_SQL.items():
        ws = _WS_SQL.format("w")
        moved += [r[0] for r in c.execute(
            f"""UPDATE file_text f SET state='wait', tries=0, error='', method='', text='', pages=0, truncated=0, sha256='',
                org_id=w.org_id, ws={ws}, updated_at=? {src} AND f.ws <> {ws}{more} RETURNING f.id""", (_now(), *args)).fetchall()]
    osw_drop(c, "file_text", moved)  # 2.1002.0 (#5279): the shared word index


def ts_org_rehome(c, oid):
    """2.209.0 D (#1856): before organisation oid is deleted, the text rows of files that left it (a list / folder moved out
    shortly before) go to their new workspace, so the deletion's cascade (file_text.org_id) only takes its own files' rows."""
    _rehome(c, oid)


odl_before_delete.append(ts_org_rehome)


def ts_run_once():
    """One step: one waiting file (documents first); with nothing waiting, maybe one file of the catch-up. Returns 1 when
    a file was handled."""
    c = connect()
    try:
        with system_ctx(c):  # file text queue: server-side recognition of every workspace's files, nothing handed to a person
            try:  # its own transaction: a failure here never stops the queue
                _rehome(c)
                c.commit()
            except Exception as e:  # noqa: BLE001
                c.rollback()
                print("filetext: rehome", type(e).__name__, e, flush=True)
            if _docs_busy(c):
                c.commit()
                return 0
            from ..docs.ocr import OCR_PAGES, OCR_PAGE_S
            stale = iso(now_utc() - timedelta(minutes=max(RUN_STALE, OCR_PAGES * OCR_PAGE_S // 60 + 15)))
            c.execute("UPDATE file_text SET state='wait' WHERE state='run' AND updated_at < ?", (stale,))
            c.execute("UPDATE file_text SET state='error', error='failed' WHERE state='wait' AND tries >= ?", (TRIES,))
            r = c.execute("""UPDATE file_text SET state='run', tries=tries+1, updated_at=? WHERE id=(
                               SELECT id FROM file_text WHERE state='wait' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED)
                             RETURNING id, kind, ref_id, ws""", (_now(),)).fetchone()
            if not r:
                _backfill(c)
        c.commit()
        if not r:
            return 0
        try:
            with system_ctx(c):  # file text queue: see above
                _process(c, dict(r))
            c.commit()
        except Exception as e:  # noqa: BLE001 -- one broken file must not stop the others
            c.rollback()
            print("filetext: recognition", r["kind"], r["ref_id"], type(e).__name__, e, flush=True)
            with system_ctx(c):  # file text queue: see above
                c.execute("UPDATE file_text SET state=CASE WHEN tries >= ? THEN 'error' ELSE 'wait' END, error='failed', updated_at=? "
                          "WHERE id=?", (TRIES, _now(), r["id"]))
            c.commit()
        return 1
    finally:
        c.close()


def _set(c, fid, state, error="", **kw):
    cols = ", ".join(f"{k}=?" for k in kw)
    c.execute(f"UPDATE file_text SET state=?, error=?, updated_at=?{', ' + cols if cols else ''} WHERE id=?",
              (state, error, _now(), *kw.values(), fid))


def _infected(c, kind, ref_id):
    """True when the virus scan (part #1818, table upload_scan) found something in the file since."""
    if "scan" not in _HAS:
        _HAS["scan"] = bool(c.execute("SELECT to_regclass('upload_scan')").fetchone()[0])
    return _HAS["scan"] and bool(c.execute("SELECT 1 FROM upload_scan WHERE kind=? AND ref_id=? AND state='infected' LIMIT 1",
                                           (kind, ref_id)).fetchone())


def _sniff(data):
    m = _sc_magic(data) or ""
    return m if m in ("application/pdf", "image/jpeg", "image/png", "image/heic") else ("image/heic" if m == "image/heif" else "")


def _process(c, row):
    fid, kind, ref_id = row["id"], row["kind"], row["ref_id"]
    ref = _ref(c, kind, ref_id)
    if not ref:
        c.execute("DELETE FROM file_text WHERE id=?", (fid,))
        return
    if kind == "fs" and c.execute("SELECT 1 FROM doc_meta WHERE node_id=?", (ref_id,)).fetchone():
        return _set(c, fid, "skip", "document")  # the documents' own recognition has it
    if _infected(c, kind, ref_id):
        return _set(c, fid, "skip", "infected")
    if (ref["size"] or 0) > MAX_MB * 1024 * 1024:
        return _set(c, fid, "skip", "too_large")
    try:
        data = _read(c, kind, ref_id, ref)
    except Exception:  # noqa: BLE001 -- a missing / damaged file or a key that cannot open it
        return _set(c, fid, "error", "unreadable")
    office = dpv_kind(ref["name"], ref["mime"], data[:16])
    mime = "office" if office in ("docx", "xlsx", "odt", "ods") else _sniff(data)  # 2.635.0 (#4807): + odt / ods
    if mime not in ("application/pdf", "image/jpeg", "image/png", "office"):
        # HEIC: neither Tesseract nor Pillow in the image read it -- no mark ("not readable" is no "no text found")
        return _set(c, fid, "skip", "heic" if mime == "image/heic" else "type")
    sha = hashlib.sha256(data).hexdigest()
    same = c.execute("""SELECT id, state, text, method, pages, truncated FROM file_text WHERE ws=? AND sha256=? AND id<>?
                        AND state IN ('found', 'none') ORDER BY id DESC LIMIT 1""", (row["ws"], sha, fid)).fetchone()
    if same:  # the same content in the same workspace: take its text over (same key, same index words)
        _set(c, fid, same["state"], text=same["text"], method=same["method"], pages=same["pages"], truncated=same["truncated"], sha256=sha)
        osw_copy(c, "file_text", same["id"], fid)  # 2.1002.0 (#5279): the shared word index
        return
    if mime == "office":  # 2.92.0 C (#1926): the text of the preview model (the same limits as a PDF)
        r = dpv_model(data, office)
        r = {"error": r["error"]} if r.get("error") else {"text": r.get("text") or "", "method": "office", "pages": 0}
    else:
        r = doc_text(ref["name"], mime, data)
    if r.get("error") == "busy":
        c.execute("UPDATE file_text SET state='wait', tries=GREATEST(tries-1, 0), updated_at=? WHERE id=?", (_now(), fid))
        return
    if r.get("error"):  # no_ocr | unreadable | too_complex | encrypted: no mark
        return _set(c, fid, "error", str(r["error"])[:40], sha256=sha)
    text = (r.get("text") or "").strip()[:TEXT_CAP]
    if not "".join(text.split()):
        return _set(c, fid, "none", method=r.get("method") or "", pages=r.get("pages") or 0, sha256=sha)
    _set(c, fid, "found", text=S.doc_seal(c, row["ws"], "file_text.text", text), method=r.get("method") or "",
         pages=r.get("pages") or 0, truncated=int(len(r.get("text") or "") >= TEXT_CAP), sha256=sha)
    _index(c, fid, row["ws"], text)


def _index(c, fid, ws, text):
    osw_put(c, "file_text", fid, ws, text)  # 2.1002.0 (#5279): the shared word index (core/objwords.py)


def ts_reindex(c, ids):
    """2.1002.0 (#5279): recognised texts indexed again by this version's rules (core/objwords.py osw_tick)."""
    for r in c.execute("SELECT id, ws, state, text FROM file_text WHERE id = ANY(CAST(? AS BIGINT[]))", (list(ids),)).fetchall():
        text = S.doc_open(c, r["ws"], "file_text.text", r["text"], default=None) if r["state"] == "found" else None
        if r["state"] == "found" and text is None:  # review of 2.1002: a key that cannot open it keeps its copied words
            raise S.OrgCryptError(f"file_text {r['id']}: the text cannot be opened")
        _index(c, r["id"], r["ws"], text)


osw_register("file_text", "file_text", "id", "x.state='found'", ts_reindex)


# ---- the catch-up of files stored before 2.61.0 -----------------------------------------------------------------------------
_BF_SQL = {
    "att": """SELECT a.id FROM attachments a WHERE a.enc=0 AND a.id < ? AND (a.mime IN ({m}) OR {ext})
              AND NOT EXISTS (SELECT 1 FROM file_text f WHERE f.att_id=a.id) ORDER BY a.id DESC LIMIT 1""",
    "list": """SELECT a.id FROM list_files a WHERE a.id < ? AND (a.mime IN ({m}) OR {ext})
               AND NOT EXISTS (SELECT 1 FROM file_text f WHERE f.list_file_id=a.id) ORDER BY a.id DESC LIMIT 1""",
    "fs": """SELECT a.id FROM fs_nodes a WHERE a.kind='file' AND a.deleted_at IS NULL AND a.id < ? AND (a.mime IN ({m}) OR {ext})
             AND NOT EXISTS (SELECT 1 FROM file_text f WHERE f.node_id=a.id) AND NOT EXISTS (SELECT 1 FROM doc_meta d WHERE d.node_id=a.id)
             ORDER BY a.id DESC LIMIT 1""",
}


def _bf_state(c):
    try:
        v = json.loads(gsetting(c, BF_KEY) or "{}")
    except ValueError:
        v = {}
    return v if isinstance(v, dict) else {}


def _backfill(c):
    """Queue ONE file stored before the recognition existed (newest first), at most every BACKFILL_S seconds and only
    when nothing waits. The position per kind stays in the settings."""
    if not BACKFILL or time.monotonic() - _Q["bf"] < BACKFILL_S:
        return
    st = _bf_state(c)
    done = set(st.get("done") or [])
    if done >= set(KINDS):
        return
    _Q["bf"] = time.monotonic()
    m = ",".join(f"'{x}'" for x in MIMES)
    ext = "(" + " OR ".join(f"LOWER(a.name) LIKE '%{e}'" for e in EXTS) + ")"  # pg-ok: LOWER() on both sides
    for kind in KINDS:
        if kind in done:
            continue
        top = int(st.get(kind) or 2 ** 62)
        r = c.execute(_BF_SQL[kind].format(m=m, ext=ext), (top,)).fetchone()
        if not r:
            done.add(kind)
            continue
        st[kind] = r[0]
        ref = _ref(c, kind, r[0])
        if ref:
            _enqueue(c, kind, r[0], ref)
        break
    st["done"] = sorted(done)
    gset(c, BF_KEY, json.dumps(st, separators=(",", ":")))


# ---- search -----------------------------------------------------------------------------------------------------------------
def _ts_opened(c, ws, ids):
    """{file_text id: its recognised text} for the word index's check of a longer word."""
    return {r["id"]: S.doc_open(c, ws, "file_text.text", r["text"]) or ""
            for r in c.execute("SELECT id, text FROM file_text WHERE id = ANY(CAST(? AS BIGINT[]))", (list(ids),))}


def ts_task_hits(c, uid, raw):
    """{task id: file name} of tasks in lists uid can see whose task / comment file text matches raw (the caller's task
    query applies the task visibility on top). Browser-encrypted files and files of deleted comments never count."""
    if not ON or not osw_terms(raw or ""):
        return {}
    # 2.1002.0 (#5279): the recognised files of the visible lists per workspace, narrowed by the shared word index
    rows = []
    for (ws,) in c.execute(f"SELECT DISTINCT {_WS_SQL.format('l')} FROM lists l WHERE l.id IN {vis_sql()}", (uid, uid)).fetchall():
        if S.ws_org(ws) and S.SECRET_KEY and not S.oc_key(c, S.ws_org(ws), create=False):
            continue  # an organisation without its key yet has no indexed file (a search never makes a key)
        # 2.1028.0 (#5783): narrowed in SQL by the index's hashes first (as before 2.1002), osw_match below decides
        pq, pa = osw_prefilter(c, "file_text", ws, raw, "f.id")
        rows += c.execute(f"""SELECT f.id, f.ws, a.task_id, a.name FROM file_text f JOIN attachments a ON a.id=f.att_id
                              JOIN tasks t ON t.id=a.task_id LEFT JOIN obj_comments cm ON cm.id=a.comment_id
                              WHERE f.kind='att' AND f.state='found' AND f.ws=? AND a.enc=0 AND a.deleted_at IS NULL AND t.deleted_at IS NULL AND t.list_id IN {vis_sql()}
                              AND (a.comment_id IS NULL OR (cm.id IS NOT NULL AND cm.deleted_at IS NULL)){pq}""",
                          (ws, uid, uid, *pa)).fetchall()
    cand, by = {}, {}
    for r in rows:
        cand.setdefault(r["ws"], set()).add(r["id"])
        by[r["id"]] = (r["task_id"], r["name"])
    out = {}
    for fid in sorted(osw_match(c, "file_text", cand, raw, _ts_opened) or ()):
        tid, name = by[fid]
        out.setdefault(tid, name)
    return out


def ts_files_find(c, uid, raw, space=""):
    """The Ablage nodes uid can see (not the trash) whose name or recognised text (documents: their text) matches raw,
    newest first: (rows, {id: "name" | "text"}). space = private | org:<id> | shared narrows it ("" = all)."""
    where, args = "", []
    if space == "private":
        where, args = " AND n.org_id IS NULL AND n.owner_id=?", [uid]
    elif space.startswith("org:") and space[4:].isdigit():
        if int(space[4:]) not in acx_of(c, uid).org_ids:
            raise Denied(404)
        where, args = " AND n.org_id=?", [int(space[4:])]
    elif space == "shared":
        where, args = " AND n.owner_id<>?", [uid]
    elif space not in ("", "all"):
        raise Denied(400, tr("Invalid value: {0}", "space"))
    vis = f"n.id IN {fs_visible_sql_c(c, uid)} AND n.deleted_at IS NULL AND n.e2e_gen = 0" + where  # 2.353.0 A (#2758): the browser searches a locked folder
    # 2.1026.0 (#5280, stage Q6c): a part of the name, umlauts as ae / oe / ue like every search (no ILIKE)
    ncond, nargs = osr_name_cond("n.name", raw)
    hit = {r[0]: "name" for r in c.execute(f"SELECT n.id FROM fs_nodes n WHERE {vis} AND {ncond} ORDER BY n.id DESC LIMIT ?",
                                           (*args, *nargs, SEARCH_MAX))} if ncond else {}
    if ON and osw_terms(raw):
        cand, node = {}, {}
        for r in c.execute(f"""SELECT f.id, f.ws, f.node_id FROM file_text f JOIN fs_nodes n ON n.id=f.node_id
                               WHERE f.kind='fs' AND f.state='found' AND {vis}""", args):
            cand.setdefault(r["ws"], set()).add(r["id"])
            node[r["id"]] = r["node_id"]
        for fid in osw_match(c, "file_text", cand, raw, _ts_opened) or ():  # 2.1002.0 (#5279): the shared word index
            hit.setdefault(node[fid], "text")
    docs = {}
    for r in c.execute(f"SELECT d.node_id, d.ws FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id WHERE {vis}", args):
        docs.setdefault(r["ws"], []).append(r["node_id"])
    if ON and osw_terms(raw):
        for nid in osw_match(c, "doc", docs, raw, S.doc_opened) or ():  # 2.1002.0 (#5279): the shared word index
            hit.setdefault(nid, "text")
    for nid in _doc_label_hits(c, docs, raw):  # 2.353.0 D (#2759): sender, document type, tags of the documents (before "text":
        if hit.get(nid) != "name":              # the word index holds the sender too)
            hit[nid] = "doc"
    ids = sorted(hit, reverse=True)[:SEARCH_MAX]
    rows = c.execute(f"SELECT * FROM fs_nodes WHERE id IN ({','.join('?' * len(ids))})", tuple(ids)).fetchall() if ids else []
    return sorted(rows, key=lambda r: -r["id"]), hit


def _doc_label_hits(c, docs, raw):
    """2.353.0 D (#2759): the documents among docs ({ws: [node ids]}, all visible) whose sender, type or a tag contains raw."""
    low, out = raw.casefold(), set()
    for ws, nids in docs.items():
        mine, got = set(nids), set()
        for kind, col in (("sender", "sender_id"), ("type", "type_id"), ("tag", None)):
            ids = [x["id"] for x in S.labels(c, ws, kind) if low in (x["name"] or "").casefold()][:500]
            if not ids:
                continue
            q = ",".join("?" * len(ids))
            sql = (f"SELECT node_id FROM doc_meta WHERE ws=? AND {col} IN ({q})" if col else
                   f"SELECT nt.node_id FROM doc_node_tags nt JOIN doc_meta d ON d.node_id=nt.node_id WHERE d.ws=? AND nt.tag_id IN ({q})")
            got |= {r[0] for r in c.execute(sql, (ws, *ids))}
        out |= got & mine
    return out


def ts_query():
    raw = (request.args.get("q") or "").strip()
    if not raw or len(raw) > 200:
        raise Denied(400, tr("Invalid value: {0}", "q"))
    return raw


def files_search():
    """GET /api/search?kind=files (2.1026.0, #5280: was /api/files/search). 2.61.0 (#1820): the Ablage search -- ?q= over the
    names and the recognised text (documents: their text; 2.353.0 D (#2759): + their sender, type and tags, hit "doc") of the
    nodes the asker can see (not the trash), ?space=private | org:<id> | shared narrows it; plus project files of
    visible project lists. {items: [node + hit: name | text, folder], list_files: [{id, name, mime, size, list_id, list_name, hit}]}"""
    c = db()
    uid = me()
    raw = ts_query()
    space = (request.args.get("space") or "").strip()
    return {"items": ts_items(c, uid, raw, space), "list_files": _list_file_hits(c, uid, raw) if space in ("", "all") else []}


def ts_items(c, uid, raw, space=""):
    """The file store's hits as the web lists them (node + hit + folder), newest first."""
    rows, hit = ts_files_find(c, uid, raw, space)
    rows = fsv_drop(c, rows)  # 2.429.0 (#3580): no folder / knowledge page / table of another area (the global search finds those)
    items = [x for x in _items(c, rows) if not x.get("no_access")]  # a link to an original the asker may not open
    parents = {r["id"]: r["parent_id"] for r in rows}
    pids = sorted({p for p in parents.values() if p})
    pnames = {r["id"]: r["name"] for r in c.execute(f"SELECT id, name FROM fs_nodes WHERE id IN ({','.join('?' * len(pids))})", tuple(pids))} if pids else {}
    for x in items:
        x["hit"] = hit.get(x["id"], "name")
        x["folder"] = pnames.get(parents.get(x["id"]), "")
    items.sort(key=lambda x: -x["id"])
    return items


srch_register("files", web=files_search, group=lambda c, uid, q, n: ts_items(c, uid, q)[:n], scope="files:read",
              gate="/api/files/search", order=40)  # 2.1026.0 (#5280): gate = the file store's switches (modcards / wsareas)


def _list_file_hits(c, uid, raw):
    """Project files of lists uid can see (project lists only, like the overview) whose name or recognised text matches."""
    rows = c.execute(f"""SELECT f.id, f.name, f.mime, f.size, f.list_id, f.created_at, l.name AS list_name, ft.id AS ft_id, ft.ws,
                         ft.state FROM list_files f JOIN lists l ON l.id=f.list_id LEFT JOIN file_text ft ON ft.list_file_id=f.id
                         WHERE f.list_id IN {vis_sql()} AND f.deleted_at IS NULL ORDER BY f.id DESC LIMIT 5000""", (uid, uid)).fetchall()
    low = raw.casefold()
    cand = {}
    for r in rows:
        if r["ft_id"] and r["state"] == "found":
            cand.setdefault(r["ws"], set()).add(r["ft_id"])
    texts = (osw_match(c, "file_text", cand, raw, _ts_opened) or set()) if ON else set()
    out, ok = [], {}
    for r in rows:
        h = "name" if low in (r["name"] or "").casefold() else ("text" if r["ft_id"] in texts else None)
        if not h:
            continue
        if r["list_id"] not in ok:
            try:
                need_overview(c, r["list_id"], full=True)  # the same check as opening the project file (2.223.7 B #2918)
                ok[r["list_id"]] = True
            except Denied:
                ok[r["list_id"]] = False
        if ok[r["list_id"]]:
            out.append({"id": r["id"], "name": r["name"], "mime": r["mime"], "size": r["size"], "list_id": r["list_id"],
                        "list_name": r["list_name"], "created_at": r["created_at"], "hit": h})
        if len(out) >= SEARCH_MAX:
            break
    return out
