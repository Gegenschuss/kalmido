"""2.353.0 A (#2758): locked folders of the file store ("Ablage") -- names and contents encrypted in the browser.

A folder can be locked like a knowledge space (wiki/wikie2e.py): a folder key per generation (32 random bytes, made in the
browser), wrapped for every person with access (fs_lock_keys; ECDH -> HKDF-SHA256(salt "fslock:<folder>:<gen>", info
"kalmido-fslockkey:v1") -> AES-256-GCM, AAD "kalmido-fslockkey:v1:<folder>:<gen>:<R>:<W>"). Below such a folder:
- names of files and folders: "e2e1:{v, g, iv, ct}" (AES-256-GCM, AAD "kalmido-fsname:v1:<folder>:<g>", padded to 64 bytes);
- file contents: the format of the lists' files (collab/liste2efile.py) with the AAD "kalmido-fsfile:v1:<folder>:<gen>":
  b"KENC\\x02" | gen (u32) | iv (12) | AES-256-GCM(u32 header length | {name, type, size} | bytes); stored as versions of
  type application/octet-stream (sealed at rest as every file on top);
- fs_nodes.e2e_gen = the generation of a node's ciphertexts (0 = plain). The locked folder's own name stays plain.
The server never sees a plain name or content of such a node: no preview, no text recognition, no search on the server, no
document recognition, no agent and no API token (only a person in the web app). Shares go to people only; who has access
but no key waits until a manager (the folder's owner, an organisation's admin) hands it over from the browser.
Switching: open -> encrypting (the browser converts every node, todo / convert) -> on; on -> decrypting (account password)
-> open; a start that fails is aborted (encrypting -> decrypting without a password: nothing was locked yet).
"""
import json
import os
import struct

from flask import jsonify, request

from ..core.config import app, ATT_DIR, MAX_FILE_MB
from ..core.db import body, bump, db, err, insert_id, iso, now_utc
from ..core.i18n import N_, tr
from ..core.access import Denied
from ..core.pg import IntegrityError
from ..accounts.session import me
from ..collab.comments import user_names
from ..collab.e2e import e2e_blob, e2e_keys_of, e2e_reauth
from ..collab.liste2e import LE2EDenied, le2e_is_cipher, le2e_parse, le2e_writer_ok
from .store import (fs_chain, fs_deleted, fs_log_add, fs_read, fs_role, fs_space, fs_subtree, fs_version_row, need_node, safe_fs_name,
                    _free_name, _mime_of, _store_version, _now, DEPTH_MAX)
from .fsroots import fs_area_of
from .web import _items, _move, fs_node_json

FSL_MAGIC = b"KENC\x02"
FSL_HEAD = len(FSL_MAGIC) + 4
FSL_SLACK = 64 * 1024        # header + iv + tag on top of the plain size limit
FSL_NAME_MAX = 4000          # characters of an encrypted name
FSL_TODO_MAX = 100           # nodes per todo call
FSL_KEYS_MAX = 500
FSL_WRAP_MAX = 200
FSL_MIME = "application/octet-stream"
FSL_MSG = {
    "fs_locked": N_("This folder is locked (encrypted in the browser). Files can only be added and changed in the app."),
    "fs_locked_busy": N_("This folder is being encrypted. Try again in a moment."),
    "fs_locked_move": N_("Moving into or out of a locked folder re-encrypts the file in the browser. Use the app for it."),
    "fs_locked_nest": N_("A locked folder cannot lie in another locked folder."),
    "fs_locked_agent": N_("Locked folders are never shared with agents or API tokens."),
    "fs_locked_link": N_("Locked folders have no links for external people and no file requests."),
    "fs_locked_space": N_("Locked folders stay in their space. Unlock the folder first."),
}


def fsl_denied(code, status=409):
    return LE2EDenied(code, status, tr(FSL_MSG[code]))


# ---------------------------------------------------------------- where a lock applies
def _fsl_any(c):
    """Is any folder locked (or switching)? A cheap first look so open trees pay nothing."""
    return c.execute("SELECT 1 FROM fs_locks WHERE e2e IS NOT NULL LIMIT 1").fetchone() is not None


def fsl_of_chain(c, chain):
    """The fs_locks row of the locked folder this chain (node first) lies in -- the node itself or a folder above -- or None."""
    if not chain or not _fsl_any(c):
        return None
    ids = [r["id"] for r in chain]
    rows = {r["node_id"]: r for r in c.execute(f"SELECT * FROM fs_locks WHERE e2e IS NOT NULL AND node_id IN ({','.join('?' * len(ids))})", ids)}
    for i in ids:
        if i in rows:
            return rows[i]
    return None


def fsl_of(c, nid):
    return fsl_of_chain(c, fs_chain(c, nid)) if nid else None


def fl_is_locked(c, node_id):
    """THE interface for other areas (documents, recognition, 2.353.0 D): does node_id lie in a locked folder (or is one,
    any switching state included)? Then no recognition, no preview, no server-side text of it."""
    return fsl_of(c, node_id) is not None


def fsl_map(c, ids):
    """{node id: (lock folder id, mode)} of the nodes among ids that lie in a locked folder (or are one)."""
    ids = [int(i) for i in ids if i]
    if not ids or not _fsl_any(c):
        return {}
    q = ",".join("?" * len(ids))
    rows = c.execute(f"""WITH RECURSIVE up(start, id, lvl) AS (SELECT id, id, 0 FROM fs_nodes WHERE id IN ({q})
                           UNION ALL SELECT up.start, n.parent_id, up.lvl + 1 FROM fs_nodes n JOIN up ON n.id=up.id
                           WHERE n.parent_id IS NOT NULL AND up.lvl < 64)
                         SELECT up.start, l.node_id, l.e2e FROM up JOIN fs_locks l ON l.node_id=up.id AND l.e2e IS NOT NULL
                         ORDER BY up.lvl""", ids).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r[0], (r[1], r[2]))
    return out


def fsl_hidden_sql(c):
    """The clause that leaves the locked trees out of a listing (agents, API tokens): '' when nothing is locked."""
    if not _fsl_any(c):
        return ""
    return (" AND id NOT IN (WITH RECURSIVE lk(id) AS (SELECT node_id FROM fs_locks WHERE e2e IS NOT NULL "
            "UNION SELECT x.id FROM fs_nodes x JOIN lk ON x.parent_id = lk.id) SELECT id FROM lk)")


def fsl_person_ok():
    """Only a person signed in to the web app reaches a locked folder (no agent, no API token, no calendar app, no public
    link, no background work)."""
    return le2e_writer_ok()


def fsl_need_reach(c, chain):
    """need_node: a locked tree exists only for a person in the web app (404 for agents and API tokens)."""
    if fsl_of_chain(c, chain) is not None and not fsl_person_ok():
        raise Denied(404)


def fsl_need_plain(c, parent_id):
    """Every plain way of adding below folder parent_id (upload, new folder, API, scans, mail filing, office filing): 409 in a
    locked folder -- the browser adds there through this module's routes."""
    if parent_id and fsl_of(c, parent_id) is not None:
        raise fsl_denied("fs_locked")


def fsl_need_unlocked(c, nid, code="fs_locked"):
    """The node lies in no locked folder (else 409 code)."""
    if fsl_of(c, nid) is not None:
        raise fsl_denied(code)


def fsl_subtree_locked(c, nid):
    """Does the subtree of nid (itself included) hold a locked folder?"""
    if not _fsl_any(c):
        return False
    ids = fs_subtree(c, nid)
    return bool(ids) and c.execute(f"SELECT 1 FROM fs_locks WHERE e2e IS NOT NULL AND node_id IN ({','.join('?' * len(ids))}) LIMIT 1",
                                   ids).fetchone() is not None


def fsl_move_guard(c, n, tid):
    """files/web.py _move: node n moves into folder tid (None: the top). Inside one locked folder: fine (same key). Across its
    border (in, out, from one to another): 409 fs_locked_move (the browser re-encrypts through /api/files/lock/move). A
    locked folder never moves into another one (409 fs_locked_nest)."""
    if not _fsl_any(c):
        return
    lt = fsl_of(c, tid) if tid else None
    if lt is not None and fsl_subtree_locked(c, n["id"]):
        raise fsl_denied("fs_locked_nest")
    ls = fsl_of(c, n["parent_id"]) if n["parent_id"] else None
    if (ls["node_id"] if ls else None) != (lt["node_id"] if lt else None):
        raise fsl_denied("fs_locked_move")


def fsl_space_guard(c, ids):
    """files/fsmove.py (move into another space): nothing of or in a locked folder."""
    for i in ids or []:
        if fsl_of(c, i) is not None or fsl_subtree_locked(c, i):
            raise fsl_denied("fs_locked_space")


# ---------------------------------------------------------------- people and keys
def _fsl_wrapped(v):
    return e2e_blob(v, FSL_WRAP_MAX)


def fsl_can_manage(c, uid, nid):
    """The owner of the folder (and an organisation's admins, fs_role 'owner')."""
    return fs_role(c, nid, uid) == "owner"


def fsl_people(c, ln):
    """[{user_id, name, role, has_keys, pub, key_gens}] of the people who reach locked folder row ln (fs_nodes) or something
    in it -- never agents: the owner, an organisation's members with a role on it, people / group members with a share on it,
    above it or on something inside it."""
    cand = {ln["owner_id"]}
    if ln["org_id"]:
        cand |= {r[0] for r in c.execute("SELECT user_id FROM org_members WHERE org_id=?", (ln["org_id"],))}
    ids = [r["id"] for r in fs_chain(c, ln["id"])] + [i for i in fs_subtree(c, ln["id"]) if i != ln["id"]]
    q = ",".join("?" * len(ids))
    inner = set()
    for r in c.execute(f"SELECT node_id, user_id, group_id FROM fs_shares WHERE node_id IN ({q}) AND agent_id IS NULL", ids):
        us = {r["user_id"]} if r["user_id"] else {x[0] for x in c.execute("SELECT user_id FROM group_members WHERE group_id=?", (r["group_id"],))}
        cand |= us
        if r["node_id"] != ln["id"]:
            inner |= us
    cand.discard(None)
    if not cand:
        return []
    cq = ",".join("?" * len(cand))
    agents = {r[0] for r in c.execute(f"SELECT id FROM users WHERE id IN ({cq}) AND COALESCE(kind, '')='agent'", list(cand))}
    rows = []
    for u in sorted(cand - agents):
        role = fs_role(c, ln["id"], u)
        if role or u in inner:
            rows.append((u, role or "view"))
    uids = [u for u, _ in rows]
    names = user_names(c, uids)
    uq = ",".join("?" * len(uids)) or "NULL"
    pubs = {r[0]: r[1] for r in c.execute(f"SELECT user_id, pub FROM e2e_keys WHERE user_id IN ({uq})", uids)}
    gens = {}
    for r in c.execute("SELECT user_id, gen FROM fs_lock_keys WHERE node_id=? ORDER BY gen", (ln["id"],)):
        gens.setdefault(r[0], []).append(r[1])
    return [{"user_id": u, "name": names.get(u, ""), "role": role, "has_keys": u in pubs,
             "pub": json.loads(pubs[u]) if u in pubs else None, "key_gens": gens.get(u, [])} for u, role in rows]


def fsl_row(c, nid):
    return c.execute("SELECT * FROM fs_locks WHERE node_id=?", (nid,)).fetchone()


def fsl_left(c, lk):
    """The nodes below locked folder row lk (trash included) not yet in the target format of its mode -> count."""
    return int(c.execute(f"SELECT COUNT(*) FROM fs_nodes WHERE id IN ({_fsl_inner_sql()}) AND {_fsl_cond(lk)}",
                         (lk["node_id"],)).fetchone()[0])


def _fsl_inner_sql():
    """The ids below the folder (one ? parameter), the folder itself not."""
    return ("WITH RECURSIVE dn(id, lvl) AS (SELECT id, 0 FROM fs_nodes WHERE parent_id=? "
            f"UNION ALL SELECT n.id, dn.lvl + 1 FROM fs_nodes n JOIN dn ON n.parent_id=dn.id WHERE dn.lvl < {DEPTH_MAX * 2}) SELECT id FROM dn")


def _fsl_cond(lk):
    """SQL condition on fs_nodes: still to convert in the mode of lock row lk (kinds file / folder only)."""
    if lk["e2e"] == "decrypting":
        return "e2e_gen > 0"
    return f"(e2e_gen = 0 OR e2e_gen < {int(lk['e2e_gen'] or 0)})"


def fsl_info(c, nid, uid):
    """The answer of GET /api/files/lock/<nid> (and of the switching routes)."""
    n = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    lk = fsl_row(c, nid)
    mode = (lk["e2e"] or None) if lk else None
    gen = int(lk["e2e_gen"] or 0) if lk else 0
    people = fsl_people(c, n)
    keys = [] if not lk else [
        {"gen": r["gen"], "wrapped": json.loads(r["wrapped"]), "wrapped_by": r["wrapped_by"], "wrapper_pub": json.loads(r["wrapper_pub"])}
        for r in c.execute("SELECT * FROM fs_lock_keys WHERE node_id=? AND user_id=? ORDER BY gen", (nid, uid))]
    pending = [{"user_id": p["user_id"], "name": p["name"], "has_keys": p["has_keys"]} for p in people if mode and gen not in p["key_gens"]]
    return {"node_id": nid, "mode": mode, "gen": gen, "by": lk["e2e_by"] if lk else None, "at": lk["e2e_at"] if lk else None,
            "can_manage": fsl_can_manage(c, uid, nid), "keys": keys, "members": people, "pending": pending,
            "left": fsl_left(c, lk) if mode in ("encrypting", "decrypting") else 0}


# ---------------------------------------------------------------- route helpers
def _fsl_person():
    if not fsl_person_ok():
        raise Denied(403)
    return me()


def _fsl_folder(c, nid, manage=False):
    """(uid, folder row) of a folder the signed-in person reaches (404) -- manage: its owner (403)."""
    uid = _fsl_person()
    n = need_node(c, nid)
    if n["kind"] != "folder":
        raise Denied(409, tr("Not a folder"))
    if manage and n["role"] != "owner":
        raise Denied(403, tr("Only the owner of the folder can change this setting"))
    return uid, n


def _fsl_lock_of_node(c, nid, write=False):
    """(uid, node, lock row) of a node in a locked folder the signed-in person may read (write: edit)."""
    uid = _fsl_person()
    n = need_node(c, nid, write=write)
    lk = fsl_of(c, nid)
    if lk is None:
        raise Denied(409, tr("The folder is not locked."))
    return uid, n, lk


def fsl_name_ok(v, gen):
    """A name as a ciphertext of generation gen."""
    d = le2e_parse(v, FSL_NAME_MAX) if isinstance(v, str) and len(v) <= FSL_NAME_MAX + 200 else None
    return bool(d) and d["g"] == gen


def fsl_blob_gen(head):
    if len(head) < FSL_HEAD or head[:len(FSL_MAGIC)] != FSL_MAGIC:
        return None
    return struct.unpack(">I", head[len(FSL_MAGIC):FSL_HEAD])[0]


def _fsl_data(f, gen):
    """The bytes of an uploaded encrypted file of generation gen (ValueError otherwise)."""
    from .upsafe import h6d_read
    data = h6d_read(f, MAX_FILE_MB * 1024 * 1024 + FSL_SLACK)
    if len(data) > MAX_FILE_MB * 1024 * 1024 + FSL_SLACK:
        raise ValueError(tr("{0}: larger than {1} MB", tr("Encrypted file"), MAX_FILE_MB))
    if len(data) <= FSL_HEAD + 12 + 16 or fsl_blob_gen(data[:FSL_HEAD]) != gen:
        raise ValueError(tr("Invalid value: {0}", "file"))
    return data


def _fsl_forget(c, nid):
    """What the server derived from a plain file goes when it becomes ciphertext: recognised text, photo data, scan marks."""
    from .textscan import ts_forget
    ts_forget(c, "fs", nid)
    for sql in ("DELETE FROM photo_meta WHERE node_id=?", "DELETE FROM upload_scan WHERE kind='fs' AND ref_id=?"):
        try:
            with c.savepoint():
                c.execute(sql, (nid,))
        except Exception:  # noqa: BLE001 -- a table of a feature this instance does not have
            pass


def _fsl_replace(c, n, data, mime, gen, uid):
    """Store data as the only version of file row n (the earlier ones -- plain before the lock, or the other format -- go:
    the wanted consequence of locking / unlocking; nothing else is removed). -> the stored files to unlink after the commit."""
    old = [r[0] for r in c.execute("SELECT path FROM fs_versions WHERE node_id=?", (n["id"],))]
    no = _store_version(c, n["id"], fs_space(n["org_id"], n["owner_id"]), data, mime, uid)
    c.execute("DELETE FROM fs_versions WHERE node_id=? AND no<>?", (n["id"], no))
    return old


def _fsl_unlink(paths):
    for p in paths:
        try:
            os.remove(os.path.join(ATT_DIR, p))
        except OSError:
            pass


def _fsl_start_block(c, n, uid):
    """Why folder n cannot be locked (a message) or None."""
    chain = fs_chain(c, n["id"])
    if fs_deleted(chain):
        return tr("The folder is in the trash")
    if fsl_of_chain(c, chain[1:]) is not None or fsl_subtree_locked(c, n["id"]):
        return tr(FSL_MSG["fs_locked_nest"])
    from ..docs.store import doc_ws, root_id
    top = chain[-1]
    if fs_area_of(c, n["id"]) or root_id(c, doc_ws(top["org_id"], top["owner_id"])) == top["id"]:
        return tr("Folders of an area (documents, knowledge, office) cannot be locked.")
    ids = fs_subtree(c, n["id"])
    q = ",".join("?" * len(ids))
    if c.execute(f"SELECT 1 FROM fs_nodes WHERE id IN ({q}) AND (kind NOT IN ('file', 'folder') OR agent_id IS NOT NULL "
                 "OR hub_mail_id IS NOT NULL) LIMIT 1", ids).fetchone():
        return tr("The folder holds links, filed objects, mails or an agent's folder. Move them out first.")
    for sql in (f"SELECT 1 FROM doc_meta WHERE node_id IN ({q}) LIMIT 1", f"SELECT 1 FROM rc_receipts WHERE node_id IN ({q}) LIMIT 1"):
        if c.execute(sql, ids).fetchone():
            return tr("The folder holds documents or receipts with recognition. Move them out first.")
    up = [r["id"] for r in chain]
    uq = ",".join("?" * len(up))
    if c.execute(f"SELECT 1 FROM fs_shares WHERE agent_id IS NOT NULL AND (node_id IN ({q}) OR node_id IN ({uq})) LIMIT 1", [*ids, *up]).fetchone():
        return tr(FSL_MSG["fs_locked_agent"])
    if c.execute(f"SELECT 1 FROM fs_ext_links WHERE node_id IN ({q}) AND revoked_at IS NULL LIMIT 1", ids).fetchone() or \
            c.execute(f"SELECT 1 FROM fs_upload_requests WHERE node_id IN ({q}) AND deleted_at IS NULL LIMIT 1", ids).fetchone():
        return tr(FSL_MSG["fs_locked_link"])
    if c.execute(f"SELECT 1 FROM fs_nodes WHERE id IN ({q}) AND (left(name, 5)='e2e1:') LIMIT 1", ids).fetchone():
        return tr("A name in this folder starts with \"e2e1:\". Rename it first.")
    return None


# ---------------------------------------------------------------- routes: state and switching
@app.get("/api/files/lock/<int:nid>")
def fsl_get(nid):
    """The lock of folder nid as the browser needs it (a node inside: the lock it lies in; none: the folder's own state)."""
    c = db()
    uid = _fsl_person()
    n = need_node(c, nid)
    lk = fsl_of(c, nid)
    root = lk["node_id"] if lk else nid
    out = fsl_info(c, root, uid)
    if not out["can_manage"]:  # who has access to a part only: its own keys, nothing about the other people
        out["members"], out["pending"] = [], []
    if not lk:
        out["block"] = _fsl_start_block(c, n, uid) if n["kind"] == "folder" else tr("Not a folder")
    return jsonify(out)


@app.post("/api/files/lock/<int:nid>/start")
def fsl_start(nid):
    """{keys: [{user_id, wrapped}]} -- lock folder nid (its owner, with own keys set up): the browser made the folder key of the
    next generation and wrapped it for every person with access and encryption set up (the others wait). -> encrypting; the
    browser converts every node below (todo / convert) and finishes."""
    c = db()
    b = body()
    uid, n = _fsl_folder(c, nid, manage=True)
    lk = fsl_row(c, nid)
    if lk and lk["e2e"]:
        return err(tr("The folder is already locked."), 409)
    block = _fsl_start_block(c, n, uid)
    if block:
        return err(block, 409)
    mine = e2e_keys_of(c, uid)
    if not mine:
        return err(tr("Set up end-to-end encryption first (Settings > Account)."), 409)
    people = fsl_people(c, n)
    ready = {p["user_id"] for p in people if p["has_keys"]}
    keys = b.get("keys")
    given = {}
    if not isinstance(keys, list) or len(keys) > FSL_KEYS_MAX:
        return err(tr("Invalid value: {0}", "keys"))
    for k in keys:
        w = _fsl_wrapped(k.get("wrapped")) if isinstance(k, dict) else None
        u = k.get("user_id") if isinstance(k, dict) else None
        if not w or isinstance(u, bool) or not isinstance(u, int) or u not in ready or u in given:
            return err(tr("Invalid value: {0}", "keys"))
        given[u] = w
    if uid not in given or ready - set(given):
        return jsonify(error=tr("A key is missing for: {0}", ", ".join(sorted(p["name"] for p in people if p["user_id"] in (ready | {uid}) - set(given)))),
                       code="fs_lock_keys", missing=sorted((ready | {uid}) - set(given))), 409
    if not lk:
        try:
            with c.savepoint():
                c.execute("INSERT INTO fs_locks(node_id, org_id) VALUES(?,?)", (nid, n["org_id"]))
        except IntegrityError:
            pass
        lk = fsl_row(c, nid)
    gen, ts = int(lk["e2e_gen"] or 0) + 1, iso(now_utc())
    if not c.execute("UPDATE fs_locks SET e2e='encrypting', e2e_gen=?, e2e_by=?, e2e_at=? WHERE node_id=? AND e2e IS NULL AND e2e_gen=?",
                     (gen, uid, ts, nid, gen - 1)).rowcount:
        c.rollback()
        return err(tr("The folder is already locked."), 409)
    c.execute("DELETE FROM fs_lock_keys WHERE node_id=?", (nid,))
    for u, w in given.items():
        c.execute("INSERT INTO fs_lock_keys(node_id,gen,user_id,wrapped,wrapped_by,wrapper_pub,created_at) VALUES(?,?,?,?,?,?,?)",
                  (nid, gen, u, w, uid, mine["pub"], ts))
    fs_log_add(c, nid, "lock", "on")
    bump(c)
    c.commit()
    return jsonify(fsl_info(c, nid, uid))


def _fsl_switch(c, nid):
    """(uid, folder, lock row) of a running switch (encrypting / decrypting) -- its managers only."""
    uid, n = _fsl_folder(c, nid, manage=True)
    lk = fsl_row(c, nid)
    if not lk or lk["e2e"] not in ("encrypting", "decrypting"):
        raise Denied(409, tr("No encryption change is running for this folder."))
    return uid, n, lk


@app.get("/api/files/lock/<int:nid>/todo")
def fsl_todo(nid):
    """The next nodes (at most 100) the browser converts: [{id, kind, name, gen, size, version}] (trash included)."""
    c = db()
    _uid, _n, lk = _fsl_switch(c, nid)
    rows = c.execute(f"SELECT id, kind, name, e2e_gen, size, cur_version, mime FROM fs_nodes WHERE id IN ({_fsl_inner_sql()}) "
                     f"AND {_fsl_cond(lk)} ORDER BY id LIMIT ?", (nid, FSL_TODO_MAX)).fetchall()
    return jsonify(items=[{"id": r["id"], "kind": r["kind"], "name": r["name"], "gen": r["e2e_gen"], "size": r["size"],
                           "version": r["cur_version"], "mime": r["mime"]} for r in rows],
                   left=fsl_left(c, lk), mode=lk["e2e"], gen=int(lk["e2e_gen"] or 0))


def _fsl_inner(c, nid, fid):
    """The node row fid below folder nid (404 otherwise)."""
    if fid == nid or nid not in [r["id"] for r in fs_chain(c, fid)]:
        raise Denied(404)
    return c.execute("SELECT * FROM fs_nodes WHERE id=?", (fid,)).fetchone()


@app.get("/api/files/lock/<int:nid>/raw/<int:fid>")
def fsl_raw(nid, fid):
    """The stored bytes of the current version of file fid below locked folder nid (plain while it is encrypted, ciphertext
    otherwise) -- for the switch (managers) and for reading in the browser (everyone who may read the file, trash too for the
    switch). Always a download of type application/octet-stream (never rendered by the browser)."""
    from flask import Response
    c = db()
    _fsl_person()
    need_node(c, fid, trash=True)  # who may not see the file learns nothing (404)
    lk = fsl_row(c, nid)
    if not lk or not lk["e2e"]:
        raise Denied(409, tr("The folder is not locked."))
    n = _fsl_inner(c, nid, fid)
    if n["kind"] != "file":
        raise Denied(409, tr("Not a file"))
    if lk["e2e"] in ("encrypting", "decrypting") and fsl_can_manage(c, me(), nid):
        pass  # the switch reads the nodes in the trash as well
    else:
        need_node(c, fid)
    data = fs_read(c, fid, request.args.get("v", type=int))
    resp = Response(data, mimetype=FSL_MIME)
    resp.headers["Content-Disposition"] = "attachment; filename=encrypted.kenc"
    resp.headers["Cache-Control"] = "private, no-cache"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@app.post("/api/files/lock/<int:nid>/convert/<int:fid>")
def fsl_convert(nid, fid):
    """multipart name (+ file for a file): node fid below folder nid in the target format of the running switch, replacing
    name and content of the same node. encrypting: a name cipher and a KENC file of the current generation; decrypting: the
    plain name and bytes (+ type). The earlier versions of the file go (see _fsl_replace)."""
    c = db()
    uid, _n, lk = _fsl_switch(c, nid)
    n = _fsl_inner(c, nid, fid)
    mode, gen = lk["e2e"], int(lk["e2e_gen"] or 0)
    todo = (n["e2e_gen"] > 0) if mode == "decrypting" else (n["e2e_gen"] == 0 or n["e2e_gen"] < gen)
    if not todo:
        return err(tr("Nothing to do"), 409)
    name = request.form.get("name") or ""
    f = request.files.get("file")
    gone = []
    try:
        if mode == "decrypting":
            if le2e_is_cipher(name) or not name.strip():
                raise ValueError(tr("Invalid value: {0}", "name"))
            name = safe_fs_name(name)
            if n["kind"] == "file":
                from .upsafe import h6d_read
                if not f:
                    raise ValueError(tr("File missing"))
                data = h6d_read(f)
                if fsl_blob_gen(data[:FSL_HEAD]) is not None:
                    raise ValueError(tr("Invalid value: {0}", "file"))
                if not data or len(data) > MAX_FILE_MB * 1024 * 1024:
                    raise ValueError(tr("{0}: larger than {1} MB", name, MAX_FILE_MB))
                mime = _mime_of(name, request.form.get("type") or "")
                gone = _fsl_replace(c, n, data, mime, 0, uid)
                c.execute("UPDATE fs_nodes SET mime=? WHERE id=?", (mime, fid))
            name = _free_name(c, n["parent_id"], n["owner_id"], n["org_id"], name, skip=fid)
            c.execute("UPDATE fs_nodes SET name=?, e2e_gen=0 WHERE id=?", (name, fid))
        else:
            if not fsl_name_ok(name, gen):
                raise ValueError(tr("Invalid value: {0}", "name"))
            if n["kind"] == "file":
                if not f:
                    raise ValueError(tr("File missing"))
                gone = _fsl_replace(c, n, _fsl_data(f, gen), FSL_MIME, gen, uid)
                c.execute("UPDATE fs_nodes SET mime=? WHERE id=?", (FSL_MIME, fid))
                _fsl_forget(c, fid)
            c.execute("UPDATE fs_nodes SET name=?, e2e_gen=? WHERE id=?", (name, gen, fid))
    except ValueError as e:
        c.rollback()
        return err(str(e))
    bump(c)
    c.commit()
    _fsl_unlink(gone)
    return jsonify(ok=True, id=fid, left=fsl_left(c, lk))


@app.post("/api/files/lock/<int:nid>/finish")
def fsl_finish(nid):
    """Ends a switch when nothing is left: encrypting -> on, decrypting -> open (the keys go)."""
    c = db()
    uid, _n, lk = _fsl_switch(c, nid)
    left = fsl_left(c, lk)
    if left:
        return jsonify(error=tr("Not all files are converted yet."), code="fs_lock_left", left=left), 409
    mode = lk["e2e"]
    if not c.execute("UPDATE fs_locks SET e2e=?, e2e_at=? WHERE node_id=? AND e2e=? AND e2e_gen=?",
                     ("on" if mode == "encrypting" else None, iso(now_utc()), nid, mode, lk["e2e_gen"])).rowcount:
        c.rollback()
        return err(tr("No encryption change is running for this folder."), 409)
    if mode == "decrypting":
        c.execute("DELETE FROM fs_lock_keys WHERE node_id=?", (nid,))
    fs_log_add(c, nid, "lock", "done" if mode == "encrypting" else "off")
    bump(c)
    c.commit()
    return jsonify(fsl_info(c, nid, uid))


@app.post("/api/files/lock/<int:nid>/stop")
def fsl_stop(nid):
    """{password} -- unlock (the owner holding the current key, with the account password): on -> decrypting. {abort: true}
    -- a start that failed (encrypting, by a manager, no password: nothing was locked yet) -> decrypting. The browser then
    writes the plain names and files back through todo / convert / finish."""
    c = db()
    b = body()
    uid, _n = _fsl_folder(c, nid, manage=True)
    lk = fsl_row(c, nid)
    want = ("encrypting",) if b.get("abort") is True else ("on", "encrypting")
    if not lk or lk["e2e"] not in want:
        return err(tr("The folder is not locked."), 409)
    if not c.execute("SELECT 1 FROM fs_lock_keys WHERE node_id=? AND user_id=? AND gen=?", (nid, uid, lk["e2e_gen"])).fetchone():
        return err(tr("You have no key for this folder yet."), 409)
    if b.get("abort") is not True:
        e = e2e_reauth(c, uid, b)
        if e is not None:
            return e
    if not c.execute(f"UPDATE fs_locks SET e2e='decrypting', e2e_by=?, e2e_at=? WHERE node_id=? AND e2e IN ({','.join('?' * len(want))})",
                     (uid, iso(now_utc()), nid, *want)).rowcount:
        c.rollback()
        return err(tr("The folder is not locked."), 409)
    bump(c)
    c.commit()
    return jsonify(fsl_info(c, nid, uid))


@app.post("/api/files/lock/<int:nid>/keys")
def fsl_keys(nid):
    """{keys: [{user_id, gen, wrapped}]} -- hand the folder key to people waiting for it: only a manager holding that
    generation; the recipient must reach the folder (no agent) and have encryption set up."""
    c = db()
    b = body()
    uid, n = _fsl_folder(c, nid, manage=True)
    lk = fsl_row(c, nid)
    if not lk or not lk["e2e"]:
        return err(tr("The folder is not locked."), 409)
    mine = e2e_keys_of(c, uid)
    keys = b.get("keys")
    if not mine or not isinstance(keys, list) or not keys or len(keys) > FSL_KEYS_MAX:
        return err(tr("Invalid value: {0}", "keys"))
    people = {p["user_id"]: p for p in fsl_people(c, n)}
    have = {r[0] for r in c.execute("SELECT gen FROM fs_lock_keys WHERE node_id=? AND user_id=?", (nid, uid))}
    ts, got = iso(now_utc()), set()
    for k in keys:
        if not isinstance(k, dict):
            return err(tr("Invalid value: {0}", "keys"))
        u, gn, w = k.get("user_id"), k.get("gen"), _fsl_wrapped(k.get("wrapped"))
        if isinstance(u, bool) or not isinstance(u, int) or isinstance(gn, bool) or not isinstance(gn, int) or not w:
            return err(tr("Invalid value: {0}", "keys"))
        if u not in people or not people[u]["has_keys"]:
            return err(tr("{0} cannot receive the key (no access or encryption not set up).", people[u]["name"] if u in people else "?"), 409)
        if gn not in have:
            return err(tr("You have no key for this folder yet."), 409)
        old = c.execute("SELECT created_at FROM fs_lock_keys WHERE node_id=? AND gen=? AND user_id=?", (nid, gn, u)).fetchone()
        if old and u != uid:
            ku = c.execute("SELECT updated_at FROM e2e_keys WHERE user_id=?", (u,)).fetchone()
            if not ku or (ku[0] or "") <= (old[0] or ""):
                continue  # an existing copy is replaced only after the recipient set up new keys (like the lists)
        c.execute("INSERT INTO fs_lock_keys(node_id,gen,user_id,wrapped,wrapped_by,wrapper_pub,created_at) VALUES(?,?,?,?,?,?,?) "
                  "ON CONFLICT (node_id,gen,user_id) DO UPDATE SET wrapped=excluded.wrapped, wrapped_by=excluded.wrapped_by, "
                  "wrapper_pub=excluded.wrapper_pub, created_at=excluded.created_at", (nid, gn, u, w, uid, mine["pub"], ts))
        got.add(u)
    bump(c)
    c.commit()
    return jsonify(ok=True, released=sorted(got))


# ---------------------------------------------------------------- routes: working in a locked folder
def _fsl_on(c, nid, write=True):
    """(uid, node, lock row) of a node (a folder for adding) in a locked folder that is 'on'."""
    uid, n, lk = _fsl_lock_of_node(c, nid, write=write)
    if lk["e2e"] != "on":
        raise fsl_denied("fs_locked_busy")
    return uid, n, lk


@app.post("/api/files/lock/upload")
def fsl_upload():
    """multipart parent_id (a folder in a locked folder, or the locked folder), file + name (repeatable, in the same order):
    files encrypted in the browser with the current generation, names as ciphers. Needs edit on the folder. No virus scan, no
    recognition, no preview (the server cannot read them)."""
    from ..admin.hosting import quota_guard
    c = db()
    pid = request.form.get("parent_id", type=int)
    uid, p, lk = _fsl_on(c, pid or 0)
    if p["kind"] != "folder":
        raise Denied(409, tr("Not a folder"))
    files, names = request.files.getlist("file"), request.form.getlist("name")
    gen = int(lk["e2e_gen"])
    if not files or len(files) != len(names):
        return err(tr("File missing"))
    if not all(fsl_name_ok(x, gen) for x in names):
        return err(tr("Invalid value: {0}", "name"))
    out, ts = [], _now()
    try:
        for f, name in zip(files, names):
            data = _fsl_data(f, gen)
            quota_guard(c, uid, len(data))
            nid = insert_id(c, """INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,mime,size,created_by,created_at,updated_at,e2e_gen)
                                  VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                            (p["id"], "file", name, p["owner_id"], p["org_id"], FSL_MIME, len(data), uid, ts, ts, gen))
            _store_version(c, nid, fs_space(p["org_id"], p["owner_id"]), data, FSL_MIME, uid)
            fs_log_add(c, nid, "upload")
            out.append(nid)
    except ValueError as e:
        c.rollback()
        return err(str(e))
    bump(c)
    c.commit()
    return jsonify(items=_items(c, [c.execute("SELECT * FROM fs_nodes WHERE id=?", (i,)).fetchone() for i in out])), 201


@app.post("/api/files/lock/folder")
def fsl_folder_new():
    """{parent_id, name (cipher)}: a folder in a locked folder."""
    c = db()
    b = body()
    try:
        pid = int(b.get("parent_id") or 0)
    except (TypeError, ValueError):
        return err(tr("Invalid value: {0}", "parent_id"))
    uid, p, lk = _fsl_on(c, pid)
    if p["kind"] != "folder":
        raise Denied(409, tr("Not a folder"))
    if len(fs_chain(c, pid)) >= DEPTH_MAX:
        raise Denied(409, tr("Folders can be nested at most {0} levels deep", DEPTH_MAX))
    if not fsl_name_ok(b.get("name"), int(lk["e2e_gen"])):
        return err(tr("Invalid value: {0}", "name"))
    ts = _now()
    nid = insert_id(c, "INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,created_by,created_at,updated_at,e2e_gen) VALUES(?,?,?,?,?,?,?,?,?)",
                    (pid, "folder", b["name"], p["owner_id"], p["org_id"], uid, ts, ts, int(lk["e2e_gen"])))
    fs_log_add(c, nid, "create")
    bump(c)
    c.commit()
    n = need_node(c, nid)
    return jsonify(fs_node_json(c, n, n["role"])), 201


@app.post("/api/files/lock/rename/<int:fid>")
def fsl_rename(fid):
    """{name (cipher)}: rename a file / folder below a locked folder (edit on it)."""
    c = db()
    b = body()
    _uid, n, lk = _fsl_on(c, fid)
    if n["id"] == lk["node_id"]:
        return err(tr("Invalid value: {0}", "name"), 409)  # the locked folder's own name is plain (the normal rename)
    if not fsl_name_ok(b.get("name"), int(lk["e2e_gen"])):
        return err(tr("Invalid value: {0}", "name"))
    c.execute("UPDATE fs_nodes SET name=?, e2e_gen=?, updated_at=? WHERE id=?", (b["name"], int(lk["e2e_gen"]), _now(), fid))
    fs_log_add(c, fid, "rename", "")
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.post("/api/files/lock/version/<int:fid>")
def fsl_version(fid):
    """multipart file: a new version of an encrypted file (the current generation; edit on the file)."""
    from ..admin.hosting import quota_guard
    c = db()
    uid, n, lk = _fsl_on(c, fid)
    if n["kind"] != "file" or n["id"] == lk["node_id"]:
        raise Denied(409, tr("Not a file"))
    f = request.files.get("file")
    if not f:
        return err(tr("File missing"))
    gen = int(lk["e2e_gen"])
    try:
        data = _fsl_data(f, gen)
    except ValueError as e:
        return err(str(e))
    quota_guard(c, uid, len(data))
    no = _store_version(c, fid, fs_space(n["org_id"], n["owner_id"]), data, FSL_MIME, uid)
    if (n["e2e_gen"] or 0) != gen:
        c.execute("UPDATE fs_nodes SET e2e_gen=? WHERE id=?", (gen, fid))  # the name stays of its generation (still readable)
    fs_log_add(c, fid, "version", str(no))
    bump(c)
    c.commit()
    return jsonify(ok=True, version=no), 201


def fsl_restore_version(c, n, no):
    """files/web.py: an older version of an encrypted file becomes the newest again (its ciphertext as it is: no check, no
    recognition -- fs_new_version would treat it as a plain upload). -> the new number."""
    v = fs_version_row(c, n["id"], no)
    if not v:
        raise Denied(404)
    return _store_version(c, n["id"], fs_space(n["org_id"], n["owner_id"]), fs_read(c, n["id"], no), FSL_MIME, me())


@app.post("/api/files/lock/move/<int:fid>")
def fsl_move(fid):
    """multipart parent_id (target folder, empty = the top of the space), name, file (for a file): move file fid across the
    border of a locked folder, re-encrypted in the browser -- into a locked folder: name cipher + KENC of the target's
    generation; out of it: the plain name and bytes (+ type). The file's earlier versions go (they are in the other format).
    Folders cross the border only when empty. Same space only (as every move)."""
    c = db()
    uid = _fsl_person()
    n = need_node(c, fid, write=True)
    if n["kind"] not in ("file", "folder"):
        raise Denied(409, tr("Not a file"))
    tid = request.form.get("parent_id", type=int) or None
    ls = fsl_of(c, n["parent_id"]) if n["parent_id"] else None
    lt = fsl_of(c, tid) if tid else None
    if (ls["node_id"] if ls else None) == (lt["node_id"] if lt else None):
        return err(tr("Nothing to do"), 409)
    if fsl_subtree_locked(c, fid) or (lt and lt["e2e"] != "on") or (ls and ls["e2e"] != "on"):
        raise fsl_denied("fs_locked_busy" if not fsl_subtree_locked(c, fid) else "fs_locked_nest")
    if n["kind"] == "folder" and c.execute("SELECT 1 FROM fs_nodes WHERE parent_id=? LIMIT 1", (fid,)).fetchone():
        return err(tr("Move the files of a folder into or out of a locked folder one by one."), 409)
    if lt:
        for k in ("fs_shares", "fs_ext_links", "fs_upload_requests"):
            col = "agent_id IS NOT NULL" if k == "fs_shares" else ("revoked_at IS NULL" if k == "fs_ext_links" else "deleted_at IS NULL")
            if c.execute(f"SELECT 1 FROM {k} WHERE node_id=? AND {col} LIMIT 1", (fid,)).fetchone():
                raise fsl_denied("fs_locked_agent" if k == "fs_shares" else "fs_locked_link")
        if c.execute("SELECT 1 FROM doc_meta WHERE node_id=? UNION ALL SELECT 1 FROM rc_receipts WHERE node_id=? LIMIT 1", (fid, fid)).fetchone():
            return err(tr("The folder holds documents or receipts with recognition. Move them out first."), 409)
    name = request.form.get("name") or ""
    f = request.files.get("file")
    gone = []
    try:
        if lt:
            gen = int(lt["e2e_gen"])
            if not fsl_name_ok(name, gen):
                raise ValueError(tr("Invalid value: {0}", "name"))
            if n["kind"] == "file":
                if not f:
                    raise ValueError(tr("File missing"))
                gone = _fsl_replace(c, n, _fsl_data(f, gen), FSL_MIME, gen, uid)
                _fsl_forget(c, fid)
                c.execute("UPDATE fs_nodes SET mime=? WHERE id=?", (FSL_MIME, fid))
            c.execute("UPDATE fs_nodes SET name=?, e2e_gen=? WHERE id=?", (name, gen, fid))
        else:
            if le2e_is_cipher(name) or not name.strip():
                raise ValueError(tr("Invalid value: {0}", "name"))
            name = safe_fs_name(name)
            if n["kind"] == "file":
                from .upsafe import h6d_read, up_check, up_after_store
                if not f:
                    raise ValueError(tr("File missing"))
                data = h6d_read(f)
                if fsl_blob_gen(data[:FSL_HEAD]) is not None or not data or len(data) > MAX_FILE_MB * 1024 * 1024:
                    raise ValueError(tr("Invalid value: {0}", "file"))
                data, mime, info = up_check(c, name, data, _mime_of(name, request.form.get("type") or ""), uid, n["org_id"], "fs")
                gone = _fsl_replace(c, n, data, mime, 0, uid)
                c.execute("UPDATE fs_nodes SET mime=? WHERE id=?", (mime, fid))
                up_after_store(c, "fs", fid, n["org_id"], info)  # plain again: checks and recognition like an upload
            c.execute("UPDATE fs_nodes SET name=?, e2e_gen=0 WHERE id=?", (name, fid))
        c.execute("UPDATE fs_nodes SET parent_id=? WHERE id=?", (n["parent_id"], fid))
        n2 = dict(c.execute("SELECT * FROM fs_nodes WHERE id=?", (fid,)).fetchone())
        n2["role"] = n["role"]
        _move(c, n2, tid, uid, fsl_ok=True)  # rights on the target, same space, depth, the free name
    except ValueError as e:
        c.rollback()
        return err(str(e))
    fs_log_add(c, fid, "move", "lock")
    bump(c)
    c.commit()
    _fsl_unlink(gone)
    return jsonify(ok=True, id=fid)
