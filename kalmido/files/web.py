"""2.48.0 (#1207): the routes of the file store ("Ablage") for the web app. The rules live in files/store.py.

Spaces: private (the person's own tree), org:<id> (an organisation's tree: what the person may see of it), shared
(nodes shared with the person whose folder above is not), trash (what the person may restore). A folder lists its
children. Same name uploaded into the same folder = a new version of that file (the older ones stay).
"""
import os

from flask import jsonify, request

from ..core.config import app, ATT_DIR, INLINE_TYPES
from ..core.i18n import tr
from ..core.db import bump, body, db, err, insert_id, iso
from ..accounts.session import me
from ..core.access import Denied, acx_of, collab_all
from ..core.orgcrypt import oc_send_file
from .upsafe import h6d_one_file_request, h6d_read
from .store import (fs_chain, fs_deleted, fs_link_target, fs_log_add, fs_new_version, fs_purge, fs_purge_files, fs_put, fs_read,
                    fs_height, fs_role, fs_version_row, DEPTH_MAX, fs_visible_ids, need_node, safe_fs_name, _free_name,
                    _now, _place, ROLE_RANK)

SHARE_MAX = 200  # shares per node
LOG_MAX = 100    # history entries shown


def _names(c, ids):
    ids = [int(x) for x in set(ids) if x]
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    return {r[0]: r[1] for r in c.execute(f"SELECT id, display_name FROM users WHERE id IN ({q})", ids)}


def fs_node_json(c, n, role=None, names=None, shared=None, up=None):
    """The public form of a node row (role: the asker's; shared: has shares / organisation access; up: the marks of
    files/upsafe.up_marks for a list, None = read for this node)."""
    names = names if names is not None else _names(c, [n["owner_id"], n["created_by"]])
    out = {"id": n["id"], "parent_id": n["parent_id"], "kind": n["kind"], "name": n["name"], "org_id": n["org_id"],
           "owner_id": n["owner_id"], "owner": names.get(n["owner_id"], ""), "created_by": n["created_by"],
           "created_by_name": names.get(n["created_by"], ""), "agent_id": n["agent_id"], "mime": n["mime"], "size": n["size"],
           "version": n["cur_version"], "created_at": n["created_at"], "updated_at": n["updated_at"],
           "deleted_at": n["deleted_at"], "org_access": n["org_access"] or "", "role": role}
    if n["kind"] == "link":
        out["ref_kind"], out["ref_id"] = n["ref_kind"], n["ref_id"]
    if shared is not None:
        out["shared"] = shared
    if n["kind"] == "file":  # 2.61.0 (#1818): + up (not checked by the virus scanner yet / locked)
        if up is None:
            from .upsafe import up_marks
            up = up_marks(c, "fs", [n["id"]])
        if up.get(n["id"]):
            out["up"] = up[n["id"]]
    return out


def _shared_flags(c, ids):
    if not ids:
        return set()
    q = ",".join("?" * len(ids))
    return {r[0] for r in c.execute(f"SELECT DISTINCT node_id FROM fs_shares WHERE node_id IN ({q})", list(ids))}


def _items(c, rows, parent_role=None):
    uid = me()
    names = _names(c, [x for r in rows for x in (r["owner_id"], r["created_by"])])
    sh = _shared_flags(c, [r["id"] for r in rows])
    from .upsafe import up_marks
    up = up_marks(c, "fs", [r["id"] for r in rows if r["kind"] == "file"])  # 2.61.0 (#1818)
    from .extlinks import xl_flags
    xl = xl_flags(c, [r["id"] for r in rows])  # 2.112.1 B (#2058): live external links (a badge for the owners)
    out = []
    for r in rows:
        role = parent_role
        if role != "owner":
            role = fs_role(c, r["id"], uid) or role
        x = fs_node_json(c, r, role, names, r["id"] in sh or bool(r["org_access"]), up)
        if r["id"] in xl and role == "owner":
            x["xl"] = True
        if r["kind"] == "link":
            try:
                fs_link_target(c, dict(r))
            except Denied:  # nothing of an original the asker may not open (name, size, type, id)
                x.update(name=tr("Linked file (no access)"), size=0, mime="", ref_id=None, no_access=True)
        out.append(x)
    out.sort(key=lambda x: (x["kind"] != "folder", x["name"].lower()))
    from .fstags import dt_attach  # 2.122.0 B (#2099): the tags of each row
    return dt_attach(c, out)


def _crumbs(c, chain, vis=None):
    """[{id, name}] from the top the asker can see down to the node (chain = node first)."""
    vis = vis if vis is not None else fs_visible_ids(c, me())
    out = []
    for r in chain:
        if r["id"] not in vis and out:
            break
        out.append({"id": r["id"], "name": r["name"]})
        if r["id"] not in vis:
            break
    return list(reversed(out))


def _space_of(v):
    v = (v or "private").strip()
    if v in ("private", "shared", "trash"):
        return v, None
    if v.startswith("org:") and v[4:].isdigit():
        return "org", int(v[4:])
    raise Denied(400, tr("Invalid value: {0}", "space"))


@app.get("/api/files")
def files_list():
    """?parent=<id>: the children of a folder; else ?space=private | org:<id> | shared | trash: the top of a space."""
    c = db()
    uid = me()
    pid = request.args.get("parent", type=int)
    if pid:
        n = need_node(c, pid)
        if n["kind"] != "folder":
            raise Denied(409, tr("Not a folder"))
        rows = c.execute("SELECT * FROM fs_nodes WHERE parent_id=? AND deleted_at IS NULL ORDER BY id", (pid,)).fetchall()
        fs_log_add(c, pid, "list")
        c.commit()
        chain = fs_chain(c, pid)
        return jsonify(items=_items(c, rows, n["role"]), node=fs_node_json(c, n, n["role"]), crumbs=_crumbs(c, chain),
                       space=("org:%d" % n["org_id"]) if n["org_id"] else ("private" if n["owner_id"] == uid else "shared"))
    space, oid = _space_of(request.args.get("space"))
    ctx = acx_of(c, uid)
    if space == "org" and oid not in ctx.org_ids:
        raise Denied(404)
    if space == "trash":
        return jsonify(items=_trash(c, uid), node=None, crumbs=[], space="trash")
    vis = fs_visible_ids(c, uid)
    if space == "private":
        rows = c.execute("SELECT * FROM fs_nodes WHERE parent_id IS NULL AND org_id IS NULL AND owner_id=? AND deleted_at IS NULL ORDER BY id",
                         (uid,)).fetchall()
        role = "owner"
    elif space == "org":
        rows = [r for r in c.execute("SELECT * FROM fs_nodes WHERE parent_id IS NULL AND org_id=? AND deleted_at IS NULL ORDER BY id", (oid,))
                if r["id"] in vis]
        role = "edit" if ctx.role != "agent" else None  # every person of the organisation may add at its top
        from ..accounts.orgroles import org_writes
        if role and not org_writes(c, uid, oid):
            role = "view"  # 2.143.0 A (#2151, review): guest / read-only / accounting add nothing at the top
    else:
        rows = []
        if vis:
            q = ",".join(str(int(x)) for x in vis)
            rows = [r for r in c.execute(f"SELECT * FROM fs_nodes WHERE id IN ({q}) ORDER BY id")
                    if r["owner_id"] != uid and (r["parent_id"] not in vis) and not (r["parent_id"] is None and r["org_id"])]
        role = None
    return jsonify(items=_items(c, rows, role if role == "owner" else None), node=None, crumbs=[], space=request.args.get("space") or "private",
                   role=role)


def _trash(c, uid):
    """Nodes in the trash the asker may restore (owner of the branch, organisation admin, or who deleted it with edit)."""
    out = []
    # candidates only (own branches, what the person deleted, organisation nodes -- row-level security keeps those to their
    # organisations); fs_role decides
    rows = c.execute("""SELECT * FROM fs_nodes WHERE deleted_at IS NOT NULL AND (owner_id=? OR deleted_by=? OR org_id IS NOT NULL)
                        ORDER BY deleted_at DESC LIMIT 500""", (uid, uid)).fetchall()
    for r in rows:
        chain = fs_chain(c, r["id"])
        if any(x["deleted_at"] for x in chain[1:]):
            continue  # inside a deleted folder: restored with it
        role = fs_role(c, r["id"], uid, chain=chain)
        if role == "owner" or (role == "edit" and r["deleted_by"] == uid):
            out.append(r)
    return _items(c, out)


def _parent_arg(c, b):
    """(parent_id, org_id) of a new node from {parent_id} or {space}."""
    pid = b.get("parent_id")
    if pid not in (None, "", 0):
        try:
            return int(pid), None
        except (TypeError, ValueError):
            raise Denied(400, tr("Invalid value: {0}", "parent_id")) from None
    space, oid = _space_of(b.get("space"))
    if space not in ("private", "org"):
        raise Denied(400, tr("Invalid value: {0}", "space"))
    return None, oid


@app.post("/api/files/folders")
def files_folder_new():
    c = db()
    b = body()
    name = safe_fs_name(str(b.get("name") or "").strip())
    if not str(b.get("name") or "").strip():
        return err(tr("Name missing"))
    pid, oid = _parent_arg(c, b)
    uid = me()
    owner, org = _place(c, uid, pid, oid)
    ts = _now()
    nid = insert_id(c, "INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (pid, "folder", _free_name(c, pid, owner, org, name), owner, org, uid, ts, ts))
    fs_log_add(c, nid, "create")
    bump(c)
    c.commit()
    n = need_node(c, nid)
    return jsonify(fs_node_json(c, n, n["role"])), 201


def _same_name_file(c, pid, owner, org, name):
    if pid:
        r = c.execute("SELECT id FROM fs_nodes WHERE parent_id=? AND kind='file' AND lower(name)=lower(?) AND deleted_at IS NULL", (pid, name))
    elif org:
        r = c.execute("SELECT id FROM fs_nodes WHERE parent_id IS NULL AND org_id=? AND kind='file' AND lower(name)=lower(?) AND deleted_at IS NULL",
                      (org, name))
    else:
        r = c.execute("""SELECT id FROM fs_nodes WHERE parent_id IS NULL AND org_id IS NULL AND owner_id=? AND kind='file' AND lower(name)=lower(?)
                         AND deleted_at IS NULL""", (owner, name))
    x = r.fetchone()
    return x[0] if x else None


@app.post("/api/files/upload")
def files_upload():
    """multipart: file (repeatable) + parent_id or space; replace=0 keeps both when the name exists (default: a new version)."""
    c = db()
    files = request.files.getlist("file")
    if not files:
        return err(tr("File missing"))
    pid, oid = _parent_arg(c, request.form)
    uid = me()
    owner, org = _place(c, uid, pid, oid)
    replace = request.form.get("replace", "1") != "0"
    out = []
    try:
        for f in files:
            data = h6d_read(f)  # 2.86.0 (N22): at most MAX_FILE_MB + 1 bytes in memory (_check_data refuses more)
            name = safe_fs_name(f.filename)
            same = _same_name_file(c, pid, owner, org, name) if replace else None
            if same and ROLE_RANK[fs_role(c, same, uid)] >= ROLE_RANK["edit"]:
                no = fs_new_version(c, same, data, f.mimetype)
                fs_log_add(c, same, "version", str(no))
                out.append(same)
            else:
                nid = fs_put(c, uid, pid, name, data, f.mimetype, org_id=org)
                fs_log_add(c, nid, "upload")
                out.append(nid)
    except ValueError as e:
        c.rollback()
        return err(str(e))
    bump(c)
    c.commit()
    rows = [c.execute("SELECT * FROM fs_nodes WHERE id=?", (i,)).fetchone() for i in out]
    return jsonify(items=_items(c, rows)), 201


def _versions(c, nid):
    names = {}
    rows = c.execute("SELECT no, size, mime, sha256, created_by, created_at FROM fs_versions WHERE node_id=? ORDER BY no DESC", (nid,)).fetchall()
    names = _names(c, [r["created_by"] for r in rows])
    return [{"no": r["no"], "size": r["size"], "mime": r["mime"], "created_by": r["created_by"], "by": names.get(r["created_by"], ""),
             "created_at": r["created_at"]} for r in rows]


def _shares(c, nid):
    rows = c.execute("SELECT * FROM fs_shares WHERE node_id=? ORDER BY id", (nid,)).fetchall()
    names = _names(c, [r["user_id"] or r["agent_id"] for r in rows])
    gq = [r["group_id"] for r in rows if r["group_id"]]
    gn = {}
    if gq:
        gn = {r[0]: r[1] for r in c.execute(f"SELECT id, name FROM groups WHERE id IN ({','.join('?' * len(gq))})", gq)}
    return [{"id": r["id"], "user_id": r["user_id"], "group_id": r["group_id"], "agent_id": r["agent_id"], "role": r["role"],
             "expires_at": r["expires_at"], "name": names.get(r["user_id"] or r["agent_id"]) or gn.get(r["group_id"], "")}
            for r in rows]


def _inherited_shares(c, chain):
    """Shares of the folders above (shown read-only in the dialog: they apply here too)."""
    out = []
    for r in chain[1:]:
        for s in _shares(c, r["id"]):
            out.append({**s, "from_id": r["id"], "from": r["name"]})
    return out


def _log(c, nid):
    rows = c.execute("SELECT * FROM fs_log WHERE node_id=? ORDER BY id DESC LIMIT ?", (nid, LOG_MAX)).fetchall()
    names = _names(c, [r["user_id"] for r in rows])
    return [{"user_id": r["user_id"], "name": names.get(r["user_id"], ""), "agent": bool(r["agent"]), "action": r["action"],
             "detail": r["detail"], "at": r["at"]} for r in rows]


@app.get("/api/files/nodes/<int:nid>")
def files_node_get(nid):
    """A node with its path, versions, shares (owners) and history (owners and editors)."""
    c = db()
    n = need_node(c, nid, trash=True)
    chain = fs_chain(c, nid)
    if fs_deleted(chain) and n["role"] != "owner" and not (n["role"] == "edit" and fs_trash_root_by(chain) == me()):
        raise Denied(404)  # the trash hides a withdrawn branch from everybody but who may restore it
    out = fs_node_json(c, n, n["role"], shared=bool(_shared_flags(c, [nid])) or bool(n["org_access"]))
    out["crumbs"] = _crumbs(c, chain)
    out["in_trash"] = fs_deleted(chain)
    from .fstags import dt_attach  # 2.122.0 B (#2099)
    dt_attach(c, [out])
    if n["kind"] == "file":
        out["versions"] = _versions(c, nid)
    if n["role"] == "owner":
        out["shares"] = _shares(c, nid)
        out["inherited"] = _inherited_shares(c, chain)
        out["org_access_from"] = next(({"id": r["id"], "name": r["name"], "access": r["org_access"]} for r in chain[1:] if r["org_access"]), None)
    if n["role"] in ("owner", "edit"):
        out["log"] = _log(c, nid)
        if n["role"] != "owner":  # 2.112.1 (#2058): the label of an external link is for the owners only
            out["log"] = [{**x, "detail": ""} if x["action"].startswith("ext_") else x for x in out["log"]]
    fs_log_add(c, nid, "meta")
    c.commit()
    return jsonify(out)


def fs_trash_root_by(chain):
    """Who moved the deleted node of this chain into the trash."""
    for r in reversed(chain):
        if r["deleted_at"]:
            return r["deleted_by"]
    return None


def _send(c, n, version=None, dl=False):
    """The content of a file / link node for the browser (images / pdf / text inline, else a download; sandbox CSP)."""
    if n["kind"] == "link":
        t = fs_link_target(c, n)
        path, name, mime, size = t["path"], t["name"], t["mime"], t["size"]
    else:
        v = fs_version_row(c, n["id"], version)
        if not v:
            raise Denied(404)
        path, name, mime, size = v["path"], n["name"], v["mime"] or n["mime"], v["size"]
        from .scan import sc_guard
        sc_guard(c, "fs", n["id"], v["no"])  # 2.61.0 (#1818): a version found infected later is locked
    full = os.path.join(ATT_DIR, path)
    if not os.path.isfile(full):
        return err(tr("File damaged or missing"), 404)
    inline = mime in INLINE_TYPES and request.args.get("dl") != "1" and not dl
    resp = oc_send_file(c, full, mimetype=mime if inline else "application/octet-stream", as_attachment=not inline,
                        download_name=name, conditional=True, max_age=0)
    if mime != "application/pdf":
        resp.headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox"
    else:  # 2.86.0 (N23): a foreign PDF opened in a tab runs no script / form under the app origin (as the archive PDFs)
        resp.headers["Content-Security-Policy"] = "sandbox"
    resp.headers["Cache-Control"] = "private, no-cache"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@app.get("/api/files/nodes/<int:nid>/content")
def files_content(nid):
    c = db()
    n = need_node(c, nid)
    if n["kind"] not in ("file", "link"):
        raise Denied(409, tr("Not a file"))
    fs_log_add(c, nid, "download", request.args.get("v") or "")
    c.commit()
    return _send(c, n, request.args.get("v", type=int))


@app.post("/api/files/nodes/<int:nid>/versions")
def files_version_upload(nid):
    """multipart file: a new version of the file (keeps its name)."""
    c = db()
    n = need_node(c, nid, write=True)
    if n["kind"] != "file":
        raise Denied(409, tr("Not a file"))
    from ..office.periodlock import pl_receipt_need_open
    pl_receipt_need_open(c, nid)  # 2.148.0 A (#2471): the image of a locked receipt stays
    h6d_one_file_request()  # 2.86.0 (N22): one file -- a longer body is refused before it is read
    f = request.files.get("file")
    if not f:
        return err(tr("File missing"))
    try:
        no = fs_new_version(c, nid, h6d_read(f), f.mimetype)
    except ValueError as e:
        c.rollback()
        return err(str(e))
    fs_log_add(c, nid, "version", str(no))
    bump(c)
    c.commit()
    return jsonify(files_node_get(nid).get_json()), 201


@app.post("/api/files/nodes/<int:nid>/versions/<int:no>/restore")
def files_version_restore(nid, no):
    """An older version becomes the newest again (a new version with its content; nothing is lost)."""
    c = db()
    n = need_node(c, nid, write=True)
    from ..office.periodlock import pl_receipt_need_open
    pl_receipt_need_open(c, nid)  # 2.148.0 A (#2471)
    v = fs_version_row(c, nid, no)
    if n["kind"] != "file" or not v:
        raise Denied(404)
    new = fs_new_version(c, nid, fs_read(c, nid, no), v["mime"])
    fs_log_add(c, nid, "restore_version", f"{no}->{new}")
    bump(c)
    c.commit()
    return jsonify(files_node_get(nid).get_json())


@app.patch("/api/files/nodes/<int:nid>")
def files_node_patch(nid):
    """{name?, parent_id? (move; null = the top of its space), org_access? ('' | view | edit; owners of an organisation node)}."""
    c = db()
    b = body()
    n = need_node(c, nid, write=True)
    if n["kind"] == "link":
        fs_link_target(c, n)  # a link changes only for someone who may open its original
    uid = me()
    ts = _now()
    if "name" in b:
        nm = str(b.get("name") or "").strip()
        if not nm:
            return err(tr("Name missing"))
        nm = safe_fs_name(nm)
        if nm != n["name"]:
            nm = _free_name(c, n["parent_id"], n["owner_id"], n["org_id"], nm, skip=nid)
            c.execute("UPDATE fs_nodes SET name=?, updated_at=? WHERE id=?", (nm, ts, nid))
            fs_log_add(c, nid, "rename", nm)
    if "parent_id" in b:
        _move(c, n, b.get("parent_id"), uid)
    if "org_access" in b:
        v = b.get("org_access") or ""
        if v not in ("", "view", "edit"):
            return err(tr("Invalid value: {0}", "org_access"))
        if n["role"] != "owner":
            raise Denied(403)
        if v and not n["org_id"]:
            return err(tr("Only folders of an organisation can be opened to it"), 409)
        c.execute("UPDATE fs_nodes SET org_access=?, updated_at=? WHERE id=?", (v, ts, nid))
        fs_log_add(c, nid, "org_access", v or "off")
    bump(c)
    c.commit()
    n = need_node(c, nid)
    return jsonify(fs_node_json(c, n, n["role"]))


def _move(c, n, target, uid):
    tid = int(target) if target not in (None, "", 0) else None
    if tid == n["parent_id"]:
        return
    if tid:
        t = need_node(c, tid, write=True)
        if t["kind"] != "folder":
            raise Denied(409, tr("Not a folder"))
        up = fs_chain(c, tid)
        if n["id"] in [r["id"] for r in up]:
            raise Denied(409, tr("A folder cannot be moved into itself"))
        if len(up) + 1 + fs_height(c, n["id"]) > DEPTH_MAX:
            raise Denied(409, tr("Folders can be nested at most {0} levels deep", DEPTH_MAX))
        if (t["org_id"] or None) != (n["org_id"] or None) or t["owner_id"] != n["owner_id"]:
            # 2.48.0 (#1207): never into another workspace / someone else's tree (the key and the owner would change)
            raise Denied(409, tr("Files can only be moved within the same space"))
    elif n["owner_id"] != uid and not (n["org_id"] and n["role"] == "owner"):
        raise Denied(403)
    nm = _free_name(c, tid, n["owner_id"], n["org_id"], n["name"], skip=n["id"])
    c.execute("UPDATE fs_nodes SET parent_id=?, name=?, updated_at=? WHERE id=?", (tid, nm, _now(), n["id"]))
    fs_log_add(c, n["id"], "move", str(tid or ""))


@app.delete("/api/files/nodes/<int:nid>")
def files_node_delete(nid):
    """Into the trash (the subtree with it); ?purge=1 on a node in the trash: remove for good (owners)."""
    c = db()
    uid = me()
    if request.args.get("purge") == "1":
        n = need_node(c, nid, write=True, trash=True)
        chain = fs_chain(c, nid)
        if not fs_deleted(chain):
            return err(tr("Only what is in the trash can be deleted for good"), 409)
        if n["role"] != "owner":
            raise Denied(403)
        ids, paths = fs_purge(c, nid)  # this node and what is below it (a node inside a deleted folder: only that one)
        bump(c)
        c.commit()
        fs_purge_files(ids, paths)  # 2.86.0 (N25): after the commit
        return jsonify(ok=True)
    n = need_node(c, nid, write=True)
    if n["parent_id"] is None and n["role"] != "owner":
        raise Denied(403)
    from ..office.periodlock import pl_tree_need_open
    pl_tree_need_open(c, nid)  # 2.148.0 A (#2471): a receipt of a locked month (also inside a folder) cannot go into the trash
    c.execute("UPDATE fs_nodes SET deleted_at=?, deleted_by=? WHERE id=?", (_now(), uid, nid))
    fs_log_add(c, nid, "trash")
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.post("/api/files/nodes/<int:nid>/restore")
def files_node_restore(nid):
    c = db()
    n = need_node(c, nid, write=True, trash=True)
    if not n["deleted_at"]:
        return jsonify(fs_node_json(c, n, n["role"]))
    if n["role"] != "owner" and n["deleted_by"] != me():
        raise Denied(403)
    from ..office.periodlock import pl_tree_need_open
    pl_tree_need_open(c, nid)  # 2.148.0 A (#2471)
    nm = _free_name(c, n["parent_id"], n["owner_id"], n["org_id"], n["name"], skip=nid)
    c.execute("UPDATE fs_nodes SET deleted_at=NULL, deleted_by=NULL, name=? WHERE id=?", (nm, nid))
    fs_log_add(c, nid, "restore")
    bump(c)
    c.commit()
    n = need_node(c, nid)
    return jsonify(fs_node_json(c, n, n["role"]))


# ---- shares
def _share_targets(c, n):
    """{people, groups, agents} the owner may share node n with: the same workspace only (an organisation's node: its members
    and its agents; a private node: the people the person may share lists with and the private agents without an owner or
    their own -- the agents a list can be shared with)."""
    from ..accounts.orgs import visible_people
    from ..lists.groups import grp_visible
    uid = me()
    vis = visible_people(c, uid)
    org = n["org_id"]
    people, agents = [], []
    from ..core.pg import system_ctx
    with system_ctx(c):  # which accounts are agents / members of the node's organisation (ids, structure; vis filters people)
        ag = {r[0]: (r[1], r[2]) for r in c.execute("SELECT user_id, org_id, owner_id FROM agents")}
        members = {r[0] for r in c.execute("SELECT user_id FROM org_members WHERE org_id=?", (org,))} if org else None
        rows = c.execute("SELECT id, display_name, kind FROM users WHERE disabled=0 ORDER BY display_name").fetchall()
    for r in rows:
        if r["id"] == uid:
            continue
        if r["id"] in ag or (r["kind"] or "") == "agent":
            aorg, aown = ag.get(r["id"], (None, None))
            if (org and aorg == org) or (not org and not aorg and aown in (None, uid)):  # like lists: no foreign personal agents
                agents.append({"id": r["id"], "name": r["display_name"]})
            continue
        if not collab_all() or (vis is not None and r["id"] not in vis) or (members is not None and r["id"] not in members):
            continue
        people.append({"id": r["id"], "name": r["display_name"]})
    groups = []
    if collab_all():
        groups = [{"id": r["id"], "name": r["name"]} for r in c.execute("SELECT id, name FROM groups ORDER BY name") if grp_visible(c, r)]
    return {"people": people, "groups": groups, "agents": agents}


@app.get("/api/files/nodes/<int:nid>/share-targets")
def files_share_targets(nid):
    c = db()
    n = need_node(c, nid, manage=True)
    return jsonify(_share_targets(c, n))


def _expiry(v, tz=None):
    if v in (None, ""):
        return None
    v = str(v).strip()
    import re
    from datetime import datetime, timezone
    from ..events.model import ev_zone, tz_ok
    try:  # stored in UTC with the same shape as iso(): the comparison with "now" is a text comparison
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            # 2.58.0 (#1787): a plain date = the end of that day where the person is (else the instance's zone), not in UTC
            d = datetime.fromisoformat(v + "T23:59:59")
            return iso(d.replace(tzinfo=ev_zone(tz if tz_ok(tz) else "")).astimezone(timezone.utc))
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        raise Denied(400, tr("Invalid value: {0}", "expires_at")) from None
    return iso(dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


@app.post("/api/files/nodes/<int:nid>/shares")
def files_share_add(nid):
    """{user_id | group_id | agent_id, role: view | edit, expires_at?: YYYY-MM-DD}: share the node (and all below it). Same
    target again = role / expiry updated."""
    c = db()
    n = need_node(c, nid, manage=True)
    if acx_of(c, me()).role == "agent":
        raise Denied(403)
    b = body()
    role = b.get("role") or "view"
    if role not in ("view", "edit"):
        return err(tr("Invalid value: {0}", "role"))
    exp = _expiry(b.get("expires_at"), b.get("tz"))  # 2.58.0 (#1787): tz = the person's zone
    t = _share_targets(c, n)
    key = next((k for k in ("user_id", "group_id", "agent_id") if b.get(k)), None)
    if not key:
        return err(tr("Expected {0}", "user_id | group_id | agent_id"))
    try:
        tid = int(b[key])
    except (TypeError, ValueError):
        return err(tr("Invalid value: {0}", key))
    pool = {"user_id": t["people"], "group_id": t["groups"], "agent_id": t["agents"]}[key]
    if not any(x["id"] == tid for x in pool):
        return err(tr("Only people, groups and agents of the same workspace can get a share"), 409)
    old = c.execute(f"SELECT id FROM fs_shares WHERE node_id=? AND {key}=?", (nid, tid)).fetchone()
    if old:
        c.execute("UPDATE fs_shares SET role=?, expires_at=? WHERE id=?", (role, exp, old[0]))
        sid = old[0]
    else:
        if c.execute("SELECT COUNT(*) FROM fs_shares WHERE node_id=?", (nid,)).fetchone()[0] >= SHARE_MAX:
            return err(tr("Too many shares"), 409)
        sid = insert_id(c, f"INSERT INTO fs_shares(node_id,{key},role,expires_at,created_by,created_at) VALUES(?,?,?,?,?,?)",
                        (nid, tid, role, exp, me(), _now()))
    fs_log_add(c, nid, "share", f"{key[:-3]}:{tid}:{role}")
    if key == "agent_id" and not old:
        _agent_event(c, tid, n, role)
    bump(c)
    c.commit()
    return jsonify(id=sid, shares=_shares(c, nid)), 201


def _agent_event(c, aid, n, role):
    """The agent learns that a folder / file was shared with it (event file_shared)."""
    try:
        from ..agents.core import agent_emit
        agent_emit(c, aid, "file_shared", {"node": {"id": n["id"], "name": n["name"], "kind": n["kind"]}, "role": role})
    except Exception as e:  # an event must never block the share itself
        print(f"WARNING file_shared event for agent {aid}: {e}", flush=True)


@app.patch("/api/files/shares/<int:sid>")
def files_share_patch(sid):
    c = db()
    s = c.execute("SELECT * FROM fs_shares WHERE id=?", (sid,)).fetchone()
    if not s:
        raise Denied(404)
    need_node(c, s["node_id"], manage=True)
    b = body()
    role = b.get("role", s["role"])
    if role not in ("view", "edit"):
        return err(tr("Invalid value: {0}", "role"))
    exp = _expiry(b["expires_at"], b.get("tz")) if "expires_at" in b else s["expires_at"]
    c.execute("UPDATE fs_shares SET role=?, expires_at=? WHERE id=?", (role, exp, sid))
    fs_log_add(c, s["node_id"], "share_change", f"{sid}:{role}")
    bump(c)
    c.commit()
    return jsonify(shares=_shares(c, s["node_id"]))


@app.delete("/api/files/shares/<int:sid>")
def files_share_delete(sid):
    c = db()
    s = c.execute("SELECT * FROM fs_shares WHERE id=?", (sid,)).fetchone()
    if not s:
        raise Denied(404)
    need_node(c, s["node_id"], manage=True)
    c.execute("DELETE FROM fs_shares WHERE id=?", (sid,))
    fs_log_add(c, s["node_id"], "unshare", str(sid))
    bump(c)
    c.commit()
    return jsonify(shares=_shares(c, s["node_id"]))


# ---- links to task / project files (no move: the original's rights apply)
@app.post("/api/files/links")
def files_link_new():
    """{ref_kind: att | list_file, ref_id, parent_id? | space?}: show a task / project file in the file store."""
    c = db()
    b = body()
    kind = b.get("ref_kind")
    if kind not in ("att", "list_file"):
        return err(tr("Invalid value: {0}", "ref_kind"))
    try:
        rid = int(b.get("ref_id"))
    except (TypeError, ValueError):
        return err(tr("Invalid value: {0}", "ref_id"))
    t = fs_link_target(c, {"ref_kind": kind, "ref_id": rid})
    pid, oid = _parent_arg(c, b)
    uid = me()
    owner, org = _place(c, uid, pid, oid)
    ts = _now()
    nid = insert_id(c, """INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,mime,size,ref_kind,ref_id,created_by,created_at,updated_at)
                          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (pid, "link", _free_name(c, pid, owner, org, safe_fs_name(t["name"])), owner, org, t["mime"], t["size"], kind, rid, uid, ts, ts))
    fs_log_add(c, nid, "link")
    bump(c)
    c.commit()
    n = need_node(c, nid)
    return jsonify(fs_node_json(c, n, n["role"])), 201


@app.get("/api/files/folders")
def files_folders():
    """Every folder the asker may add to ({id, name, path, org_id}) -- the target list of "Move to…"."""
    c = db()
    uid = me()
    vis = fs_visible_ids(c, uid)
    if not vis:
        return jsonify(folders=[])
    q = ",".join(str(int(x)) for x in vis)
    rows = {r["id"]: r for r in c.execute(f"SELECT id, parent_id, name, org_id, owner_id FROM fs_nodes WHERE id IN ({q}) AND kind='folder'")}
    out = []
    for r in rows.values():
        if ROLE_RANK[fs_role(c, r["id"], uid)] < ROLE_RANK["edit"]:
            continue
        path, p, guard = [r["name"]], r["parent_id"], 0
        while p in rows and guard < 64:
            path.insert(0, rows[p]["name"])
            p, guard = rows[p]["parent_id"], guard + 1
        out.append({"id": r["id"], "name": r["name"], "path": " / ".join(path), "org_id": r["org_id"], "owner_id": r["owner_id"]})
    out.sort(key=lambda x: x["path"].lower())
    return jsonify(folders=out[:1000])


def fs_agent_folder(c, aid):
    """The result folder of agent aid (created on first use): at the top of its owner's space (an organisation's agent: of
    the organisation), named like the agent. Returns the node id or None (an agent without an owner / organisation)."""
    from ..core.pg import system_ctx
    with system_ctx(c):  # the agent's settings row and its owner (structure; the folder is created in the agent's own workspace)
        a = c.execute("SELECT a.org_id, a.owner_id, u.display_name FROM agents a JOIN users u ON u.id=a.user_id WHERE a.user_id=?", (aid,)).fetchone()
        r = c.execute("SELECT id FROM fs_nodes WHERE agent_id=? AND parent_id IS NULL AND kind='folder' AND deleted_at IS NULL "
                      "AND (org_id=? OR (? IS NULL AND org_id IS NULL)) ORDER BY id LIMIT 1",
                      (aid, a["org_id"] if a else None, a["org_id"] if a else None)).fetchone() if a else None
        if not a:
            return None
        if r:
            return r[0]
        owner = a["owner_id"]
        if not owner:
            x = c.execute("SELECT id FROM users WHERE is_admin=1 AND COALESCE(kind, '')!='agent' ORDER BY id LIMIT 1").fetchone()
            owner = x[0] if x else None
        if not owner:
            return None
        ts = _now()
        org = a["org_id"]
        return insert_id(c, """INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,agent_id,created_by,created_at,updated_at)
                               VALUES(NULL,'folder',?,?,?,?,?,?,?)""",
                         (_free_name(c, None, owner, org, safe_fs_name(a["display_name"] or "Agent")), owner, org, aid, aid, ts, ts))

