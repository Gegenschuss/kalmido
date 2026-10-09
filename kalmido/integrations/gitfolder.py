"""2.33.0 (#934): a repository connected to a FOLDER (builds on the folder settings of #929 / #1030).

The owner of a folder connects a repository once (folder settings > Repository); every PROJECT list of the owner in that
folder and its subfolders uses it -- also lists that come into the folder later -- unless the list switched it off
(lists.git_folder_off) or has a repository of its own (its own ones replace the folder's). A subfolder with repositories of
its own replaces the ones of its parent folder for its lists. "#id" / "fixes #id" in pull requests and commits find the
tasks of all these lists, and the repository is still polled ONCE (one connection row), not once per list.

Storage, so that 2.32 keeps working with the database: the connection is a normal git_conns row (token sealed as before)
that hangs on one of the folder's lists (list_id, the "carrier", only for the foreign key) plus a row in the new table
git_folders (conn_id, owner_id, folder). 2.32 does not know git_folders and simply sees a repository of the carrier list.
The carrier moves to another list of the folder when it leaves the folder or is deleted (gf_rehome: each poll, before a
list is deleted); a renamed / moved folder takes its repositories along, a deleted folder hands them to its parent folder
(a deleted top folder: they stay with the carrier list as its own). Only the folder's owner connects, changes or removes a
folder repository (never an agent); everyone who sees a list that uses it sees it like a repository of that list."""
from flask import g, jsonify, request

from ..core.config import app, SECRET_KEY
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, now_utc
from ..accounts.session import me
from ..core.access import Denied, list_role, need_list
from ..personal.timetrack import BadInput
from ..agents.core import is_agent


def _under(p, top):
    from ..lists.lists import folder_under
    return folder_under(p or "", top)


def gf_row(c, cid):
    return c.execute("SELECT * FROM git_folders WHERE conn_id=?", (cid,)).fetchone()


def _viewer():
    try:
        return (g.user or {})["id"]
    except (AttributeError, RuntimeError, KeyError, TypeError):
        return None


def gf_folder(c, cid):
    """The folder's path for its owner; "" for everyone else (the owner's folder names stay private); None = no folder repository."""
    r = gf_row(c, cid)
    if not r:
        return None
    return r["folder"] if r["owner_id"] == _viewer() else ""


def gf_own_conns(c, lid):
    """The list's own repositories (not a folder repository that only hangs on it)."""
    return c.execute("SELECT * FROM git_conns WHERE list_id=? AND id NOT IN (SELECT conn_id FROM git_folders) ORDER BY id", (lid,)).fetchall()


def _owner_lists(c, owner, folder):
    return [r for r in c.execute("SELECT id, name, folder, kind, archived, git_folder_off FROM lists WHERE owner_id=? AND is_inbox=0 ORDER BY sort, id",
                                 (owner,)) if _under(r["folder"], folder)]


def _nearest(c, owner, path):
    """(folder, [connection rows]) of the deepest folder of owner on path that has repositories, else (None, [])."""
    if not path:
        return None, []
    rows = c.execute("""SELECT k.*, f.folder AS gf_folder FROM git_folders f JOIN git_conns k ON k.id=f.conn_id
                        WHERE f.owner_id=? ORDER BY k.id""", (owner,)).fetchall()
    best = None
    for r in rows:
        if _under(path, r["gf_folder"]) and (best is None or len(r["gf_folder"]) > len(best)):
            best = r["gf_folder"]
    return (best, [r for r in rows if r["gf_folder"] == best]) if best else (None, [])


def gf_conns_for_list(c, lid, ignore_own=False, ignore_off=False):
    """The folder repositories list lid uses ([] = none): a project list of the folder's owner, not switched off, without a
    repository of its own (ignore_*: what it would use -- the list dialog shows them)."""
    lst = c.execute("SELECT id, owner_id, folder, kind, git_folder_off FROM lists WHERE id=?", (lid,)).fetchone()
    if not lst or lst["kind"] != "project" or not lst["folder"] or (lst["git_folder_off"] and not ignore_off):
        return []
    if not ignore_own and gf_own_conns(c, lid):
        return []
    return _nearest(c, lst["owner_id"], lst["folder"])[1]


def gf_lists_of_conn(c, cid):
    """None = no folder repository; else the ids of the lists that use it."""
    f = gf_row(c, cid)
    if not f:
        return None
    return {r["id"] for r in _owner_lists(c, f["owner_id"], f["folder"]) if any(x["id"] == cid for x in gf_conns_for_list(c, r["id"]))}


def gf_list_state(c, lid):
    """For the list dialog: {folder (the folder whose repositories it uses / would use, null = none), off, own, uses}."""
    lst = c.execute("SELECT owner_id, folder, kind, git_folder_off FROM lists WHERE id=?", (lid,)).fetchone()
    if not lst:
        return None
    f, rows = _nearest(c, lst["owner_id"], lst["folder"] or "")
    own = bool(gf_own_conns(c, lid))
    return {"folder": (f if lst["owner_id"] == _viewer() else "") if f else None, "inherited": bool(rows),
            "off": bool(lst["git_folder_off"]), "own": own,
            "uses": bool(rows) and lst["kind"] == "project" and not own and not lst["git_folder_off"]}


def gf_need_conn(c, r, manage):
    """git_need_conn for a folder repository (False = it is a list's own one). Managing: only the folder's owner (a person);
    reading / refreshing: whoever sees a list that uses it. Anyone else: 404."""
    f = gf_row(c, r["id"])
    if not f:
        return False
    uid = me()
    if manage:
        if f["owner_id"] != uid or is_agent(g.user):
            if f["owner_id"] == uid or any(list_role(c, x) for x in gf_lists_of_conn(c, r["id"]) or ()):
                raise Denied(403, tr("Only the owner of the folder can change its repository"))
            raise Denied(404)
        return True
    if f["owner_id"] != uid and not any(list_role(c, x) for x in gf_lists_of_conn(c, r["id"]) or ()):
        raise Denied(404)
    return True


def gf_rehome(c, cid, exclude=None):
    """The carrier list of folder repository cid must be a list of the owner in the folder (not exclude): else it moves to
    one (preferably a list that uses it). Nothing to move to: it stays (deleting its list then removes it)."""
    f = gf_row(c, cid)
    if not f:
        return
    k = c.execute("SELECT list_id FROM git_conns WHERE id=?", (cid,)).fetchone()
    lst = c.execute("SELECT owner_id, folder, archived FROM lists WHERE id=?", (k["list_id"],)).fetchone() if k else None
    ok = lst and k["list_id"] != exclude and lst["owner_id"] == f["owner_id"] and _under(lst["folder"], f["folder"])
    if ok and not lst["archived"]:
        return
    cand = [r for r in _owner_lists(c, f["owner_id"], f["folder"]) if r["id"] != exclude]
    cand.sort(key=lambda r: (bool(r["archived"]), r["kind"] != "project", r["git_folder_off"]))
    if ok and (not cand or cand[0]["archived"]):  # an archived carrier is fine while every list of the folder is archived
        return
    if cand:
        c.execute("UPDATE git_conns SET list_id=? WHERE id=?", (cand[0]["id"], cid))


def gf_before_list_delete(c, lid):
    """A list is about to be deleted: folder repositories hanging on it move to another list of their folder first."""
    for (cid,) in c.execute("SELECT k.id FROM git_conns k JOIN git_folders f ON f.conn_id=k.id WHERE k.list_id=?", (lid,)).fetchall():
        gf_rehome(c, cid, exclude=lid)


def gf_rename(c, uid, old, new):
    """A folder of uid was renamed / moved (old -> new, subfolders along): its repositories go along."""
    for r in c.execute("SELECT conn_id, folder FROM git_folders WHERE owner_id=?", (uid,)).fetchall():
        if _under(r["folder"], old):
            c.execute("UPDATE git_folders SET folder=? WHERE conn_id=?", (new + r["folder"][len(old):], r["conn_id"]))


def gf_folder_removed(c, uid, up):
    """A folder of uid was deleted (its lists moved up one level; up(path) = the new path, '' = top level): its repositories
    go to the parent folder; a deleted top folder's stay with their carrier list as that list's own."""
    for r in c.execute("SELECT conn_id, folder FROM git_folders WHERE owner_id=?", (uid,)).fetchall():
        nf = up(r["folder"])
        if not nf:
            c.execute("DELETE FROM git_folders WHERE conn_id=?", (r["conn_id"],))
        elif nf != r["folder"]:
            c.execute("UPDATE git_folders SET folder=? WHERE conn_id=?", (nf, r["conn_id"]))


# ---- endpoints (web app; people only -- the REST API reads folder repositories through GET /api/v1/lists/{id}/repos)
def _need_folder(c, f, write=False):
    from ..lists.lists import clean_folder
    if is_agent(g.user):
        raise Denied(403, tr("Agents cannot connect repositories"))
    f = clean_folder(f or "", strict=write) if isinstance(f, str) else ""
    if not f:
        raise BadInput(tr("Invalid value: {0}", "folder"))
    return f


def gf_info(c, uid, f):
    from ..integrations.git import GIT_MAX_CONNS, git_public
    rows = c.execute("""SELECT k.* FROM git_folders x JOIN git_conns k ON k.id=x.conn_id WHERE x.owner_id=? AND x.folder=?
                        ORDER BY k.id""", (uid, f)).fetchall()
    parent = f.rsplit(_fsep(), 1)[0] if _fsep() in f else ""
    pf, prow = _nearest(c, uid, parent)
    lists = []
    for r in _owner_lists(c, uid, f):
        uses = gf_conns_for_list(c, r["id"])
        lists.append({"id": r["id"], "name": r["name"], "folder": r["folder"], "project": r["kind"] == "project",
                      "off": bool(r["git_folder_off"]), "own": bool(gf_own_conns(c, r["id"])),
                      "uses": bool(uses), "via": gf_row(c, uses[0]["id"])["folder"] if uses else None})
    return {"folder": f, "repos": [git_public(c, r, True) for r in rows], "max": GIT_MAX_CONNS, "key": bool(SECRET_KEY),
            "inherited": {"folder": pf, "repos": [git_public(c, r) for r in prow]} if pf else None, "lists": lists}


def _fsep():
    from ..lists.lists import FOLDER_SEP
    return FOLDER_SEP


@app.get("/api/folders/repos")
def gf_get():
    """?folder=: the repositories of my folder, the ones it inherits from a parent folder, and its lists (project, uses it /
    switched off / has its own / via which folder)."""
    c = db()
    try:
        f = _need_folder(c, request.args.get("folder"))
    except BadInput as e:
        return err(str(e))
    return jsonify(gf_info(c, me(), f))


@app.post("/api/folders/repos")
def gf_add():
    """{folder, provider?, base_url?, repo: "owner/name" or its address, token?} -- connects a repository to my folder: every
    project list of mine in it (and its subfolders, also later ones) uses it."""
    from ..integrations.git import git_clean_input, git_connect, git_key_error, GIT_MAX_CONNS
    c, b = db(), body()
    try:
        f = _need_folder(c, b.get("folder"), write=True)
        provider, base, owner, name, token = git_clean_input({k: v for k, v in b.items() if k != "folder"})
    except BadInput as e:
        return err(str(e))
    if token and not SECRET_KEY:
        return err(git_key_error(), 409)
    lists = _owner_lists(c, me(), f)
    if not lists:
        return err(tr("This folder has no lists"), 404)
    cur = c.execute("""SELECT k.* FROM git_folders x JOIN git_conns k ON k.id=x.conn_id WHERE x.owner_id=? AND x.folder=?""", (me(), f)).fetchall()
    if len(cur) >= GIT_MAX_CONNS:
        return err(tr("At most {0} repositories per folder", GIT_MAX_CONNS), 409)
    if any((x["provider"], x["base_url"], x["owner"].lower(), x["repo"].lower()) == (provider, base, owner.lower(), name.lower()) for x in cur):
        return err(tr("This repository is already connected"), 409)
    lists.sort(key=lambda r: (bool(r["archived"]), r["kind"] != "project", r["git_folder_off"]))
    resp = git_connect(c, lists[0]["id"], provider, base, owner, name, token, folder=f)
    if isinstance(resp, tuple) and resp[1] == 201:
        print("folder", repr(f), "of", g.user["username"], "repository", f"{owner}/{name}", flush=True)
    return resp


@app.put("/api/lists/<int:lid>/folder-repo")
def gf_list_use(lid):
    """{use: true | false}: the list uses its folder's repositories (default) or not (the list owner / a list admin)."""
    c, b = db(), body()
    if is_agent(g.user):
        raise Denied(403, tr("Agents cannot connect repositories"))
    need_list(c, lid, write=False, manage=True)
    if not isinstance(b.get("use"), bool):
        return err(tr("Invalid value: {0}", "use"))
    c.execute("UPDATE lists SET git_folder_off=? WHERE id=?", (0 if b["use"] else 1, lid))
    bump(c)
    c.commit()
    return jsonify(gf_list_state(c, lid))
