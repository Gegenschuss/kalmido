"""2.353.0 D (#2759): recognition per folder or file -- the file store and the documents are ONE area ("Ablage"); a document
is a file with its doc_meta row (docs/store.py), recognised by the queue (docs/ingest.py).

fs_nodes.recog of a folder or file: '' = as the folder above, 'on', 'off'. Without an own value anywhere up the path a
node recognises inside the workspace's documents folder (store.root_id, its inbox included) and nowhere else -- so the
folder "Dokumente" keeps its recognition, nothing moves. Subfolders inherit like the rights of the folders. A locked folder
(end-to-end encrypted, part A) never recognises: the server only holds ciphertext.

Switched on: the files of the folder (also those of subfolders that do not say 'off') become documents at once (at most
BULK per request, the rest with the next upload / switch), and so does every file uploaded or moved in later
(rc_after_add from the file store's routes). Switched off: new files stay plain files; documents already recognised stay
documents (nothing is deleted). A single file outside a recognising folder: "Recognise" (PUT .../recognition {mode: on})
adds it as a document. Rights: 'edit' on the node (the file store's need_node); agents use the API v1 and do not switch."""
from flask import jsonify

from ..core.config import app
from ..core.db import body, bump, db, err
from ..core.i18n import tr
from ..accounts.session import me
from ..files.store import ROLE_RANK, fs_chain, fs_log_add, fs_role, need_node
from ..files.fsroots import fs_area_root_of
from ..files.fslock import fl_is_locked
from . import store as S
from .ingest import doc_add, docs_kick
from .web import _no_agent, doc_json

MODES = ("", "on", "off")
BULK = 500      # files made documents by one switch at most (the rest follows with the next upload / switch)
DEPTH = 30      # folder levels walked below a switched folder


def _ab_locked(c, nid):
    """A node inside a locked (end-to-end encrypted) folder: no recognition there."""
    return fl_is_locked(c, nid)  # 2.353.0 (#2759): part A's lock (files/fslock.py)


def _val(r):
    v = r["recog"] if "recog" in r.keys() else ""
    return v if v in ("on", "off") else ""


def rc_state(c, nid, chain=None):
    """{on, own, from: {id, name} | None, root: bool} of node nid: on = recognises; own = its own value ('' | on | off);
    from = the folder above that decides (None: the node itself or nothing); root = decided by the documents folder."""
    chain = chain if chain is not None else fs_chain(c, nid)
    if not chain:
        return {"on": False, "own": "", "from": None, "root": False}
    own = _val(chain[0])
    if _ab_locked(c, chain[0]["id"]):
        return {"on": False, "own": own, "from": None, "root": False, "locked": True}
    for x in chain:
        v = _val(x)
        if v:
            return {"on": v == "on", "own": own, "from": None if x["id"] == chain[0]["id"] else {"id": x["id"], "name": x["name"]},
                    "root": False}
    top = chain[-1]
    root = (top["kind"] == "folder" and top["parent_id"] is None
            and S.root_id(c, S.doc_ws(top["org_id"], top["owner_id"])) == top["id"])
    return {"on": root, "own": own, "from": {"id": top["id"], "name": top["name"]} if root and top["id"] != chain[0]["id"] else None,
            "root": root}


def rc_on(c, nid):
    return rc_state(c, nid)["on"]


def _add(c, row, uid):
    """The doc_meta row of one plain file (state wait); True when it became a document now."""
    if row["kind"] != "file" or row["deleted_at"] or c.execute("SELECT 1 FROM doc_meta WHERE node_id=?", (row["id"],)).fetchone():
        return False
    doc_add(c, row["id"], row["org_id"], row["owner_id"], uid or row["created_by"] or row["owner_id"], "folder")
    return True


def rc_after_add(c, nid, uid):
    """A file uploaded / moved into a folder (or a folder moved): what lands in a recognising folder becomes a document.
    Returns how many became one (the caller commits, then docs_kick)."""
    r = c.execute("SELECT * FROM fs_nodes WHERE id=?", (int(nid),)).fetchone()
    if not r or r["deleted_at"]:
        return 0
    if r["kind"] == "folder":
        return rc_bulk(c, r["id"], uid)
    return 1 if r["kind"] == "file" and rc_on(c, r["id"]) and _add(c, r, uid) else 0


def rc_kick(added):
    """Wake the recognition queue after the commit when files became documents."""
    if added:
        docs_kick()


def rc_bulk(c, fid, uid, limit=BULK):
    """The plain files below folder fid (subfolders with their own value follow it) become documents while the folder
    recognises: at most limit of them, only files uid may change (a hub mail's folder, a share-less corner) and never in the
    root folder of another area (knowledge, office, tables: their own rules). Returns the count."""
    if not rc_on(c, fid):
        return 0
    n, level, depth = 0, [fid], 0
    while level and n < limit and depth < DEPTH:
        q = ",".join("?" * len(level))
        rows = c.execute(f"SELECT * FROM fs_nodes WHERE parent_id IN ({q}) AND deleted_at IS NULL ORDER BY id", level).fetchall()
        nxt = []
        for r in rows:
            if r["kind"] == "folder":
                if _val(r) != "off" and not _ab_locked(c, r["id"]) and not fs_area_root_of(c, r["id"]):
                    nxt.append(r["id"])
            elif (r["kind"] == "file" and _val(r) != "off" and n < limit
                  and (not uid or ROLE_RANK[fs_role(c, r["id"], uid)] >= ROLE_RANK["edit"]) and _add(c, r, uid)):
                n += 1
        level, depth = nxt, depth + 1
    return n


def rc_flags(c, ids):
    """{node id: {state, review}} of the documents among ids (the list of a folder marks them)."""
    ids = [int(x) for x in ids]
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    return {r["node_id"]: {"state": r["state"], "review": bool(r["review"])}
            for r in c.execute(f"SELECT node_id, state, review FROM doc_meta WHERE node_id IN ({q})", ids)}


def rc_list_extra(c, chain, node, items, full=False):
    """The file store's list (files/web.py files_list): node (the listed folder, chain = its path; None: the top of a space)
    gets recog_on / recog_from / recog_root, each folder and file of items recog_on, each document doc {state, review}
    (full: the document as the documents list has it, for the cards)."""
    st = rc_state(c, node["id"], chain) if node else None
    if node:
        node.update(recog_on=st["on"], recog_from=(st["from"] or {}).get("name") or "", recog_root=st["root"])
    for x in items:
        if x["kind"] not in ("folder", "file"):
            continue
        own = x.get("recog") or ""
        if (st and st.get("locked")) or x.get("locked"):
            x["recog_on"] = False
        elif own:
            x["recog_on"] = own == "on"
        elif st:
            x["recog_on"] = st["on"]
        else:  # the top of a space: the documents folder recognises
            x["recog_on"] = x["kind"] == "folder" and x["parent_id"] is None and \
                S.root_id(c, S.doc_ws(x["org_id"], x["owner_id"])) == x["id"] and not _ab_locked(c, x["id"])
    flags = rc_flags(c, [x["id"] for x in items if x["kind"] == "file"])
    if full and flags:
        for x in items:
            if x["id"] in flags:
                m = S.meta_row(c, x["id"])
                n = c.execute("SELECT * FROM fs_nodes WHERE id=?", (x["id"],)).fetchone()
                x["doc"] = doc_json(c, m, n) if m and n else flags[x["id"]]
    else:
        for x in items:
            if x["id"] in flags:
                x["doc"] = flags[x["id"]]
    return items


@app.put("/api/files/nodes/<int:nid>/recognition")
def files_recognition_put(nid):
    """{mode: on | off | inherit} -- a folder: its own value (inherit = as the folder above; on: its files become documents);
    a file: on = recognise it now (a file outside a recognising folder). -> {recog: rc_state, added}."""
    c = db()
    uid = me()
    _no_agent()
    mode = str((body() or {}).get("mode") or "").strip()
    mode = "" if mode == "inherit" else mode
    if mode not in MODES:
        return err(tr("Invalid value: {0}", "mode"))
    n = need_node(c, nid, write=True)
    if n["kind"] not in ("folder", "file"):
        return err(tr("Only folders and files can be recognised"), 409)
    if _ab_locked(c, nid):
        return err(tr("Locked folders are never recognised: the server cannot read them"), 409)
    added = 0
    if n["kind"] == "file":
        if mode != "on":
            return err(tr("Invalid value: {0}", "mode"))
        added = 1 if _add(c, n, uid) else 0
        if added:
            fs_log_add(c, nid, "recognise")
    else:
        if mode != _val(n):
            c.execute("UPDATE fs_nodes SET recog=? WHERE id=?", (mode, nid))
            fs_log_add(c, nid, "recognise", mode or "inherit")
        added = rc_bulk(c, nid, uid)
    bump(c)
    c.commit()
    if added:
        docs_kick()
    return jsonify(recog=rc_state(c, nid), added=added)
