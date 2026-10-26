"""2.48.0 (#1111): documents in -- docs_ingest (the interface the upload, the share target, the mail input and the import
#1152 use) and the background queue that recognises them.

docs_ingest stores the file with the file store (fs_put) in the folder "Dokumente" of the workspace and adds its doc_meta
row (state 'wait'); the queue -- one thread in the server process, started with the first request -- takes the waiting
documents one by one (text, OCR, preview, date / amount, sorting, index; docs/store.py process). The state lives in
doc_meta: after a restart the queue simply goes on (a run that was cut off is taken up again after RUN_STALE minutes, at
most TRIES times). The same thread looks into the inbox folders ("Dokumente/Eingang") every SCAN_EVERY seconds: a file put
there becomes a document. Mails to a person's / an organisation's document address (plus address with a doc_mail token)
become documents (their attachments), see docs_mail_import."""
import os
import threading
import time
from datetime import timedelta

from ..core.config import app
from ..core.db import connect, iso, now_utc
from ..accounts.session import bg_here
from ..core.pg import system_ctx
from ..files.store import fs_add_hooks, fs_on_delete, fs_put
from . import store as S
from .unpack import doc_unpack
from ..core.access import acx_of, Denied  # 2.149.0 G (#2517): pulled up from functions
from ..core.i18n import tr  # 2.353.0 (#2769)
from ..office.lettermail import ltm_token_space  # 2.312.0 C (#3265)
from ..files.fslock import fl_is_locked  # 2.353.0 (#2769)

IDLE = 5             # s the queue sleeps when there is nothing to do (a new document wakes it at once)
SCAN_EVERY = max(1, int(os.environ.get("KALMIDO_DOCS_SCAN_S", "60") or 60))  # s between two looks into the inbox folders
RUN_STALE = 30       # min after which a run that was cut off (restart) is taken up again
TRIES = 3            # runs of one document at most
MAIL_FILES = 20      # attachments of one mail at most
MAIL_UNPACKED = 50   # 2.146.0 B (#2453): files out of one ZIP / winmail.dat of a mail at most
_Q = {"thread": None, "scan": 0.0}
doc_on_done = []     # 2.48.0 (#1356): hooks f(c, nid, first) after a recognition run (receipts: the event document_added)
_WAKE = threading.Event()
_LOCK = threading.Lock()


from ..core.db import now_iso as _now  # noqa: E402  2.149.0 G (#2517): was an own copy


def docs_ingest(c, uid, org_id, name, data, mime=None, source="upload", meta=None, parent_id=None, dedup=False, info=None):
    """Store a new document of account uid in the workspace org_id (None: uid's own) and queue its recognition. meta:
    fields given by the caller (an import) -- date, due, amount, currency, sender, type, tags [names], text, ext_id; they
    are taken as they are ("import"), the recognition fills in the rest. An ext_id already present in the workspace
    returns that document instead of a second copy. Returns the node id; the caller commits (then docs_kick()). Raises
    what fs_put raises (Denied, ValueError, hosting.QuotaExceeded). parent_id: 2.122.0 (#2098) a folder the API puts it in
    (needs 'edit' there; default: the workspace's documents folder). dedup: 2.146.0 B (#2452) the same bytes already in the
    workspace (a document uid may see) return that document; info (a dict) then gets dup = True."""
    from .dups import dup_same_file, raw_sha
    meta = dict(meta or {})
    ext = str(meta.pop("ext_id", "") or "")[:200] or None
    ws_guess = S.doc_ws(org_id, uid)
    if ext:
        r = c.execute("SELECT node_id FROM doc_meta WHERE ws=? AND ext_id=?", (ws_guess, ext)).fetchone()
        if r:
            return r[0]
    sha = raw_sha(data)
    if dedup:
        same = dup_same_file(c, ws_guess, sha, uid)
        if same:
            if info is not None:
                info["dup"] = True
            return same
    folder = int(parent_id) if parent_id else S.root_folder(c, uid, org_id)  # 2.48.0 review: the marked documents folder, members file in
    if fl_is_locked(c, folder):  # 2.353.0 (#2769): scans, the documents mail address, imports: never into a locked folder
        from .scankeys import LOCKED_MSG
        raise Denied(409, tr(LOCKED_MSG))
    up = {}  # 2.61.0 B (#1819): the upload checks' info -- the capture date of a photo (read before its metadata went)
    nid = fs_put(c, uid, folder, name, data, mime, None if parent_id else org_id, up=up)
    node = c.execute("SELECT org_id, owner_id FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    doc_add(c, nid, node["org_id"], node["owner_id"], uid, source, ext, meta)
    if up.get("taken_at"):
        c.execute("UPDATE doc_meta SET taken_at=? WHERE node_id=?", (str(up["taken_at"])[:40], nid))
    c.execute("UPDATE doc_meta SET raw_sha=? WHERE node_id=?", (sha, nid))  # 2.146.0 B (#2452)
    return nid


def doc_add(c, nid, org_id, owner_id, uid, source="upload", ext=None, meta=None):
    """The doc_meta row of an existing file node (state wait)."""
    ws = S.doc_ws(org_id, owner_id)
    given = {k: v for k, v in (meta or {}).items() if k in ("date", "due", "amount", "currency", "sender", "type", "tags", "text", "_by") and v}
    if isinstance(given.get("tags"), str):
        given["tags"] = [t.strip() for t in given["tags"].split(",") if t.strip()]
    for k in ("date", "due"):
        if k in given and not _iso_day(given[k]):
            given.pop(k)
    ts = _now()
    c.execute("""INSERT INTO doc_meta(node_id, org_id, ws, state, source, ext_id, suggest, doc_date, created_by, created_at, updated_at)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(node_id) DO NOTHING""",
              (nid, org_id, ws, "wait", str(source or "upload")[:20], ext,
               S._jseal(c, ws, "doc_meta.suggest", {"_given": given}) if given else "", _iso_day(given.get("date")), uid, ts, ts))
    return ws


def _iso_day(v):
    import re
    v = str(v or "")[:10]
    return v if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) else None


def doc_on_delete(c, nid):
    """fs_on_delete hook: a document deleted for good leaves the models, its preview goes (rows: ON DELETE CASCADE).
    2.306.0 D3 (#2875): the preview file is returned for the caller to unlink after the commit (a failed delete keeps it)."""
    m = c.execute("SELECT thumb FROM doc_meta WHERE node_id=?", (nid,)).fetchone()
    if not m:
        return []
    try:
        S.untrain(c, nid)
    except Exception as e:  # noqa: BLE001 -- deleting never fails because of a model
        print("docs: untrain", nid, type(e).__name__, flush=True)
    rel = m["thumb"] or ""
    return [rel] if rel.startswith(S.THUMB_DIR + os.sep) and ".." not in rel else []


fs_on_delete.append(doc_on_delete)
fs_add_hooks.append(S.root_add_ok)


# ---- the queue ------------------------------------------------------------------------------------------------------------
def docs_kick():
    """Wake the queue (start it when it does not run yet)."""
    if not bg_here():  # 2.193.0 D (#2220): role web -- the worker runs the queue from its table
        return
    with _LOCK:
        if _Q["thread"] is None or not _Q["thread"].is_alive():
            _Q["thread"] = threading.Thread(target=_loop, daemon=True, name="docs")
            _Q["thread"].start()
    _WAKE.set()


@app.before_request
def _docs_start():
    if _Q["thread"] is None:
        docs_kick()


def _loop():
    from ..accounts.session import GATE
    time.sleep(1)
    while True:
        n = 0
        try:
            with GATE.bg():
                n = docs_run_once()
        except Exception as e:  # noqa: BLE001 -- the queue never dies
            print("docs: queue", type(e).__name__, e, flush=True)
            time.sleep(IDLE)
        if not n:
            _WAKE.wait(IDLE)
            _WAKE.clear()


def docs_run_once():
    """One step of the queue: the inbox folders (every SCAN_EVERY s), then one waiting document. Returns 1 when a
    document was handled."""
    c = connect()
    try:
        if time.monotonic() - _Q["scan"] > SCAN_EVERY:
            _Q["scan"] = time.monotonic()
            with system_ctx(c):  # docs queue: server-side recognition of every workspace's documents, nothing handed to a person
                inbox_scan(c)
            c.commit()
        stale = iso(now_utc() - timedelta(minutes=RUN_STALE))
        with system_ctx(c):  # docs queue: server-side recognition of every workspace's documents, nothing handed to a person
            r = None
            # 2.149.0 C (#2516): the three writes below only touch waiting / running rows: none (the usual idle tick) -> no writes
            if c.execute("SELECT 1 FROM doc_meta WHERE state IN ('wait', 'run') LIMIT 1").fetchone():
                c.execute("UPDATE doc_meta SET state='wait' WHERE state='run' AND updated_at < ?", (stale,))
                c.execute("UPDATE doc_meta SET state='failed', error='failed' WHERE state='wait' AND tries >= ?", (TRIES,))
                r = c.execute("""UPDATE doc_meta SET state='run', tries=tries+1, updated_at=? WHERE node_id=(
                                   SELECT d.node_id FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id
                                   WHERE d.state='wait' AND n.deleted_at IS NULL ORDER BY d.created_at, d.node_id LIMIT 1
                                   FOR UPDATE OF d SKIP LOCKED) RETURNING node_id""", (_now(),)).fetchone()
        c.commit()
        if not r:
            from .split import sp_scan_queued  # 2.209.0 C (#2589): the page scan a split preview asked for, out of the request
            try:
                with system_ctx(c):  # docs queue: server-side page scan of a document a person opened the split preview of
                    took = sp_scan_queued(c)
                c.commit()
                if took:
                    return 1
            except Exception as e:  # noqa: BLE001 -- the queue never dies
                c.rollback()
                print("docs: split scan", type(e).__name__, e, flush=True)
            from .thumbfill import p61a_thumb_fill  # 2.66.1 (#1944): previews of imports from before, while nothing waits
            try:
                with system_ctx(c):  # docs queue: server-side catch-up of every workspace's previews, nothing handed to a person
                    p61a_thumb_fill(c)
                c.commit()
            except Exception as e:  # noqa: BLE001 -- the queue never dies
                c.rollback()
                print("docs: preview catch-up", type(e).__name__, e, flush=True)
            return 0
        nid = r[0]
        try:
            with system_ctx(c):  # docs queue: server-side recognition of every workspace's documents, nothing handed to a person
                first = not c.execute("SELECT done_at FROM doc_meta WHERE node_id=?", (nid,)).fetchone()[0]  # 2.48.0 (#1356)
                st = S.process(c, nid)
                if st == "wait":
                    c.execute("UPDATE doc_meta SET state='wait', tries=GREATEST(tries-1, 0) WHERE node_id=?", (nid,))
                else:
                    _after(c, nid)
                    for f in doc_on_done:  # 2.48.0 (#1356): f(c, nid, first) after a recognition run (first = the first one)
                        f(c, nid, first)
            c.commit()
        except Exception as e:  # noqa: BLE001 -- one broken document must not stop the others
            c.rollback()
            print("docs: recognition", nid, type(e).__name__, e, flush=True)
            with system_ctx(c):  # docs queue: server-side recognition of every workspace's documents, nothing handed to a person
                c.execute("UPDATE doc_meta SET state=CASE WHEN tries >= ? THEN 'failed' ELSE 'wait' END, error='failed', updated_at=? "
                          "WHERE node_id=?", (TRIES, _now(), nid))
            c.commit()
        return 1
    finally:
        c.close()


def _after(c, nid):
    """A document recognised out of the inbox folder moves on into the documents folder (unless it was sorted)."""
    n = c.execute("SELECT n.*, p.name AS pname, p.parent_id AS pparent FROM fs_nodes n LEFT JOIN fs_nodes p ON p.id=n.parent_id "
                  "WHERE n.id=?", (nid,)).fetchone()
    if not n or not n["pparent"] or (n["pname"] or "").lower() != S.INBOX.lower():
        return
    root = c.execute("SELECT id, parent_id, name, org_id, owner_id FROM fs_nodes WHERE id=?", (n["pparent"],)).fetchone()
    if root and root["parent_id"] is None and S.root_id(c, S.doc_ws(root["org_id"], root["owner_id"])) == root["id"]:
        from ..files.store import _free_name
        c.execute("UPDATE fs_nodes SET parent_id=?, name=?, updated_at=? WHERE id=?",
                  (root["id"], _free_name(c, root["id"], n["owner_id"], n["org_id"], n["name"], skip=nid), _now(), nid))


def inbox_scan(c):
    """Files put into an inbox folder ("Dokumente/Eingang" at the root of a workspace) become documents."""
    rows = c.execute("""SELECT n.id, n.org_id, n.owner_id, n.created_by, r.id AS rid, r.owner_id AS rowner FROM fs_nodes n
                        JOIN fs_nodes f ON f.id=n.parent_id AND f.kind='folder' AND lower(f.name)=lower(?) AND f.deleted_at IS NULL
                        JOIN fs_nodes r ON r.id=f.parent_id AND r.parent_id IS NULL AND r.kind='folder' AND lower(r.name)=lower(?)
                          AND r.deleted_at IS NULL
                        LEFT JOIN doc_meta d ON d.node_id=n.id
                        WHERE n.kind='file' AND n.deleted_at IS NULL AND d.node_id IS NULL ORDER BY n.id LIMIT 100""",
                     (S.INBOX, S.ROOT)).fetchall()
    # a new version of a document's file (the file store's upload with the same name): recognise it again
    c.execute("""UPDATE doc_meta d SET state='wait', tries=0 FROM fs_nodes n WHERE n.id=d.node_id AND d.state IN ('done', 'failed')
                 AND d.version > 0 AND n.cur_version <> d.version""")
    added = 0
    for r in rows:
        ws = S.doc_ws(r["org_id"], r["owner_id"])
        if S.root_id(c, S.doc_ws(r["org_id"], r["rowner"])) != r["rid"]:  # 2.48.0 review: only the marked documents folder
            continue
        if not S.cfg_get(c, ws)["inbox"]:
            continue
        doc_add(c, r["id"], r["org_id"], r["owner_id"], r["created_by"] or r["owner_id"], "folder")
        added += 1
    return added


# ---- mail -------------------------------------------------------------------------------------------------------------
def docs_mail_import(c, msg, raw):
    """A mail to a document address (plus address with a doc_mail token): its attachments become documents of that
    person / organisation. None = not a document address (the task import goes on); else the first node id or 0."""
    from ..integrations.mail import MAIL_TOKEN_RE, mail_text
    from ..admin.hosting import QuotaExceeded
    import hashlib
    from ..office.einvoice_in import ei_is
    hdrs = " ".join(str(msg.get_all(h, [])) for h in ("To", "Cc", "Delivered-To", "X-Original-To", "Envelope-To"))
    toks = MAIL_TOKEN_RE.findall(hdrs)
    if not toks:
        return None
    with system_ctx(c):  # docs mail: resolving a secret address token (like a public link), membership checked below
        r = next((x for x in (c.execute("SELECT * FROM doc_mail WHERE token=?", (t,)).fetchone() for t in toks) if x), None)
        letter = None
        if r:
            uid, org = r["user_id"], r["org_id"]
        else:  # 2.312.0 C (#3265): the Reply-To bound to one mailed letter -> that letter's documents space
            hit = next((x for x in (ltm_token_space(c, t) for t in toks) if x), None)
            if not hit:
                return None
            uid, org, letter = hit
        u = c.execute("SELECT disabled FROM users WHERE id=?", (uid,)).fetchone()
        if not u or u["disabled"]:
            return 0
        if org and int(org) not in acx_of(c, uid).org_ids:
            return 0  # no longer a member: nothing goes in
        mid = str(msg.get("Message-ID", "")).strip()[:200] or ("sha:" + hashlib.sha256(raw).hexdigest())
        _text, files = mail_text(msg)
        first, made = 0, []
        for i, (name, mime, data) in enumerate(files[:MAIL_FILES]):
            parts = doc_unpack(name, data, MAIL_UNPACKED)  # 2.146.0 B (#2453): a ZIP / winmail.dat -> its files
            if parts is not None:
                for e in parts[1]:
                    print("docs: mail attachment", e[:200], flush=True)
                # 2.146.0 A (#2451): an XML in it only when it is an e-invoice, like a single attachment
                parts = [(n, m2, b, f"mail:{mid}:{i}:{j}") for j, (n, b, m2) in enumerate(parts[0])
                         if not n.casefold().endswith(".xml") or ei_is(b)]
            # 2.146.0 A (#2451): an e-invoice XML (XRechnung UBL / CII) goes in too, any other XML does not
            elif mime.startswith("image/") or mime == "application/pdf" or name.lower().endswith(".pdf") or ei_is(data):
                parts = [(name, mime, data, f"mail:{mid}:{i}")]
            else:
                continue
            for pname, pmime, pdata, pext in parts:
                try:
                    with c.savepoint():  # 2.146.0 B (#2452): a file already there is linked, not stored again
                        nid = docs_ingest(c, uid, org, pname, pdata, pmime, "mail", {"ext_id": pext}, dedup=True)
                    first = first or nid
                    made.append(nid)
                except (Denied, ValueError, QuotaExceeded) as e:
                    print("docs: mail attachment refused", type(e).__name__, flush=True)
        if made:  # 2.153.0 (#2029): the answer to a letter sent by e-mail (In-Reply-To / References) -> linked to it
            try:
                from ..office.lettermail import ltm_link_replies
                with c.savepoint():
                    ltm_link_replies(c, uid, org, msg, made, letter)
            except Exception as e:  # noqa: BLE001 -- the documents are in; a failed link is assigned by hand
                print("docs: letter link failed", type(e).__name__, flush=True)
    c.commit()
    if first:
        docs_kick()
    return first
