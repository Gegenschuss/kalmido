"""2.39.0 (#1168): the Playbook of a list or folder -- the owner's working rules for agents ("how tasks are handled here").

A Playbook is a Markdown text (at most PB_MAX characters) on a list, or on a folder of its owner (owner_id + folder path, like
folder_props; a subfolder "A/b" inherits "A"). The effective Playbook of a list = the Playbooks of every folder on the path of
its owner's folder (outer first) + the list's own one last ("it adds to them"). Every saved text is a version (who / when /
source: edit | restore | proposal | import | template), at most PB_KEEP per Playbook; the newest is the current one.

Who writes: a list's owner or list admins (a list that belongs to an agent: its members with edit rights), a folder's owner;
never an agent -- an agent proposes a change (POST /api/v1/lists/<lid>/playbook/proposals, at most PB_PROP_OPEN per agent and
list), people apply (optionally edited) or discard it, the agent hears the outcome (event playbook_proposal). Who reads:
everyone who sees the list. Agents get the effective Playbook with every event of the list (agents/core.py agent_emit ->
pb_event, never for a health list) and read it with GET /api/v1/lists/<lid>/playbook.

The scheduled check of a list (list check): a plan of agents/schedules.py (agent_schedules.list_check = 1, list_id set) made in
the list's Playbook view by someone who may write the Playbook, for an agent of the list; when due the agent gets the event
scheduled_job with list_check: true, the list, its open task ids and the Playbook. Losing the access switches it off like
every plan (sched_fire)."""
import hashlib

from flask import g, has_request_context, jsonify, request

from ..core.config import app
from ..core.pg import insert_id, write_lock
from ..core.i18n import N_, tr
from ..core.db import body, bump, db, err, iso, now_utc, parse_iso
from ..accounts.session import me
from ..core.access import Denied, list_role, MANAGE_ROLES, need_list, tvis, WRITE_ROLES
from ..collab.comments import user_names
from ..core.errors import BadInput
from ..api.common import v1_args, v1_json, v1_view

PB_MAX = 8000          # characters of one Playbook
PB_KEEP = 200          # versions kept per Playbook
PB_SOURCES = ("edit", "restore", "proposal", "import", "template")
PB_PROP_OPEN = 3       # open proposals per agent and list
PB_NOTE_MAX = 500
PB_CHECKS_MAX = 5      # scheduled checks per list
PB_OPEN_IDS_MAX = 500  # open task ids in a list check event
PB_SEP = "\n\n---\n\n"


# ---------------------------------------------------------------- storage
def pb_text(v):
    """A Playbook text from a client: a string, CRLF -> LF, trimmed, at most PB_MAX characters (BadInput otherwise)."""
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", "text"))
    v = v.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "").strip()
    if len(v) > PB_MAX:
        raise BadInput(tr("Too long: {0} (at most {1} characters)", "Playbook", PB_MAX))
    return v


def _where(lid, owner, folder):
    if lid:
        return "list_id=?", (lid,)
    return "list_id IS NULL AND owner_id=? AND folder=?", (owner, folder)


def pb_current(c, lid=None, owner=None, folder=None):
    """The newest version row of a list's (lid) or a folder's Playbook, or None."""
    w, a = _where(lid, owner, folder)
    return c.execute(f"SELECT * FROM playbooks WHERE {w} ORDER BY version DESC LIMIT 1", a).fetchone()


def pb_cache_drop():
    if has_request_context():
        g.pop("pb_cache", None)


def pb_save(c, text, source, author, lid=None, owner=None, folder=None):
    """Stores text as the new version of the Playbook (list lid, or folder of owner) unless it equals the current one.
    Returns (version, created_at, changed). The caller checked rights and commits."""
    write_lock(c, f"playbook:{lid}" if lid else f"playbook:{owner}:{folder}")
    cur = pb_current(c, lid, owner, folder)
    if (cur["body"] if cur else "") == text:
        return (cur["version"], cur["created_at"], False) if cur else (0, None, False)
    v, ts = (cur["version"] if cur else 0) + 1, iso(now_utc())
    c.execute("INSERT INTO playbooks(list_id,owner_id,folder,version,body,source,author_id,created_at) VALUES(?,?,?,?,?,?,?,?)",
              (lid, None if lid else owner, None if lid else folder, v, text, source if source in PB_SOURCES else "edit", author, ts))
    w, a = _where(lid, owner, folder)
    c.execute(f"DELETE FROM playbooks WHERE {w} AND version<=?", (*a, v - PB_KEEP))
    pb_cache_drop()
    return v, ts, True


def pb_parts(c, lid):
    """(list row {owner_id, folder, life} | None, the list's current version row | None, [(folder, row)] outer first) --
    ONE query for the Playbooks (the list's own + the folders on the path of its owner's folder)."""
    lr = c.execute("SELECT owner_id, COALESCE(folder,'') AS folder, life FROM lists WHERE id=?", (lid,)).fetchone()
    if not lr:
        return None, None, []
    rows = c.execute("""SELECT DISTINCT ON (COALESCE(p.list_id, 0), COALESCE(p.folder, '')) p.* FROM playbooks p
                        WHERE p.list_id=? OR (p.list_id IS NULL AND p.owner_id=? AND ?<>'' AND (p.folder=? OR left(?, length(p.folder) + 1)=p.folder || '/'))
                        ORDER BY COALESCE(p.list_id, 0), COALESCE(p.folder, ''), p.version DESC""",
                     (lid, lr["owner_id"], lr["folder"], lr["folder"], lr["folder"])).fetchall()
    own = next((r for r in rows if r["list_id"]), None)
    folders = sorted(((r["folder"], r) for r in rows if not r["list_id"]), key=lambda x: len(x[0]))
    return lr, own, folders


def pb_key(text):
    """A short marker of an effective Playbook (changes whenever its text changes)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12] if text else ""


def pb_effective(c, lid):
    """{text (effective), list_text, list_version, folders: [{folder, text, version, updated_at}] (non-empty, outer first),
    updated_at, key, life} of list lid ({} when the list does not exist)."""
    lr, own, folders = pb_parts(c, lid)
    if not lr:
        return {}
    fl = [{"folder": f, "text": r["body"], "version": r["version"], "updated_at": r["created_at"]} for f, r in folders if r["body"]]
    parts = [x["text"] for x in fl] + ([own["body"]] if own and own["body"] else [])
    text = PB_SEP.join(parts)
    times = [x["updated_at"] for x in fl] + ([own["created_at"]] if own else [])
    # 2.126.0 B (#1978): who wrote the parts (a version without an author: the list's owner)
    authors = sorted({r["author_id"] or lr["owner_id"] for _, r in folders if r["body"]} | ({own["author_id"] or lr["owner_id"]} if own and own["body"] else set()))
    return {"text": text, "list_text": own["body"] if own else "", "list_version": own["version"] if own else 0,
            "list_row": own, "folders": fl, "updated_at": max(times) if times else None, "key": pb_key(text), "life": lr["life"],
            "authors": authors}


def pb_event(c, lid):
    """The playbook part of an agent event of list lid ({text, version, updated_at, list_id}) or None (no Playbook, a health
    list). Cached per request (many events of one request: one query per list)."""
    cache = g.setdefault("pb_cache", {}) if has_request_context() else {}
    if lid in cache:
        return cache[lid]
    e = pb_effective(c, lid)
    out = None
    if e and e["text"] and e["life"] != "health":
        out = {"text": e["text"], "version": e["key"], "updated_at": e["updated_at"], "list_id": lid, "authors": e["authors"]}
    cache[lid] = out
    return out


def pb_for_agent(c, pb, aid):
    """2.126.0 B (#1978): the playbook part of an event for agent aid with its authors ({id, name}) and foreign: true when one
    of them is not the agent's operator (a personal agent: its owner; a team agent: the list's owner / admins). The launcher
    then shows it as information about the list, not as rules to follow."""
    from ..agents.admin import agent_owner
    ids = list(pb.get("authors") or [])
    o = agent_owner(c, aid)
    foreign = any(a != o for a in ids) if o is not None else any(list_role(c, pb["list_id"], a) not in MANAGE_ROLES for a in ids)
    names = user_names(c, ids)
    return {**pb, "authors": [{"id": a, "name": names.get(a, "")} for a in ids], "foreign": foreign}


def pb_flags(c, rows):
    """{list id: True} of the lists (rows with id, owner_id, folder) whose effective Playbook is not empty (state: l.playbook)."""
    ids = [r["id"] for r in rows]
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    out = {r[0]: True for r in c.execute(f"""SELECT DISTINCT ON (list_id) list_id, body FROM playbooks WHERE list_id IN ({q})
                                             ORDER BY list_id, version DESC""", ids) if r[1]}
    owners = {r["owner_id"] for r in rows if r["folder"]}
    if owners:
        q2 = ",".join("?" * len(owners))
        full = {(r[0], r[1]) for r in c.execute(f"""SELECT DISTINCT ON (owner_id, folder) owner_id, folder, body FROM playbooks
                                                   WHERE list_id IS NULL AND owner_id IN ({q2}) ORDER BY owner_id, folder, version DESC""",
                                                list(owners)) if r[2]}
        if full:
            for r in rows:
                f = r["folder"] or ""
                parts = f.split("/")
                if f and any((r["owner_id"], "/".join(parts[:i])) in full for i in range(1, len(parts) + 1)):
                    out[r["id"]] = True
    return out


def pb_folder_rename(c, uid, old, new):
    """A folder of uid was renamed / moved (old -> new, subfolders along): its Playbooks go along. A folder merged into an
    existing one: its versions follow the target's (the moved text becomes the current one; nothing is lost)."""
    from ..lists.lists import folder_under
    for (f,) in c.execute("SELECT DISTINCT folder FROM playbooks WHERE list_id IS NULL AND owner_id=?", (uid,)).fetchall():
        if not folder_under(f, old):
            continue
        nf = new + f[len(old):]
        if nf == f:
            continue
        tmax = c.execute("SELECT COALESCE(MAX(version), 0) FROM playbooks WHERE list_id IS NULL AND owner_id=? AND folder=?", (uid, nf)).fetchone()[0]
        c.execute("UPDATE playbooks SET folder=?, version=version+? WHERE list_id IS NULL AND owner_id=? AND folder=?", (nf, tmax, uid, f))
        if tmax:
            top = c.execute("SELECT MAX(version) FROM playbooks WHERE list_id IS NULL AND owner_id=? AND folder=?", (uid, nf)).fetchone()[0]
            c.execute("DELETE FROM playbooks WHERE list_id IS NULL AND owner_id=? AND folder=? AND version<=?", (uid, nf, top - PB_KEEP))
    pb_cache_drop()


def pb_folder_removed(c, uid, name, move):
    """The folder `name` of uid was removed (its lists and subfolders moved up, move(path) -> new path): the subfolders'
    Playbooks go along. The removed folder's own one ends with an empty version (review M3: a new folder of the same name
    must not take over the old rules silently); its earlier versions stay in the history."""
    cur = pb_current(c, owner=uid, folder=name)
    if cur and cur["body"]:
        pb_save(c, "", "edit", uid, owner=uid, folder=name)
    for (f,) in c.execute("SELECT DISTINCT folder FROM playbooks WHERE list_id IS NULL AND owner_id=?", (uid,)).fetchall():
        if f != name and f.startswith(name + "/"):
            pb_folder_rename(c, uid, f, move(f))


# ---------------------------------------------------------------- rights
def _is_agent_user():
    return (g.user["kind"] or "user") == "agent"


def pb_can_edit(c, lid, uid=None, role=None):
    """May uid write the Playbook of list lid? Owner / list admins; a list that belongs to an agent: its members with edit
    rights; never an agent."""
    from ..agents.core import agent_ids
    uid = uid or me()
    u = c.execute("SELECT kind FROM users WHERE id=?", (uid,)).fetchone()
    if not u or u["kind"] == "agent":
        return False
    role = role or list_role(c, lid, uid)
    if role in MANAGE_ROLES:
        return True
    owner = c.execute("SELECT owner_id FROM lists WHERE id=?", (lid,)).fetchone()
    return bool(owner) and owner[0] in agent_ids(c) and role in WRITE_ROLES


def _need_edit(c, lid):
    role = need_list(c, lid, write=False)
    if _is_agent_user() or not pb_can_edit(c, lid, me(), role):
        raise Denied(403, tr("Only the project owner or a project admin can change the Playbook"))
    return role


def pb_editors(c, lid):
    """The people who decide on the Playbook of list lid (News about an agent's proposal)."""
    from ..agents.core import agent_ids
    ag = agent_ids(c)
    lr = c.execute("SELECT owner_id FROM lists WHERE id=?", (lid,)).fetchone()
    if not lr:
        return []
    roles = MANAGE_ROLES if lr[0] not in ag else WRITE_ROLES
    out = [] if lr[0] in ag else [lr[0]]
    out += [r[0] for r in c.execute("SELECT user_id FROM list_members WHERE list_id=?", (lid,)).fetchall()
            if r[0] not in ag and r[0] not in out and list_role(c, lid, r[0]) in roles]
    return out


# ---------------------------------------------------------------- output
def _by(c, uid, names=None, kinds=None):
    if not uid:
        return None
    names = names if names is not None else user_names(c, [uid])
    out = {"id": uid, "name": names.get(uid, "")}
    if kinds is not None:
        out["kind"] = "agent" if uid in kinds else "user"
    return out


def pb_versions_out(c, lid=None, owner=None, folder=None):
    from ..agents.core import agent_ids
    w, a = _where(lid, owner, folder)
    rows = c.execute(f"SELECT version, created_at, author_id, source, length(body) AS chars FROM playbooks WHERE {w} "
                     f"ORDER BY version DESC LIMIT ?", (*a, PB_KEEP)).fetchall()
    names, ag = user_names(c, [r["author_id"] for r in rows]), agent_ids(c)
    return [{"version": r["version"], "created_at": r["created_at"], "by": _by(c, r["author_id"], names, ag), "source": r["source"],
             "chars": r["chars"]} for r in rows]


def pb_version_out(c, v, lid=None, owner=None, folder=None):
    from ..agents.core import agent_ids
    w, a = _where(lid, owner, folder)
    r = c.execute(f"SELECT * FROM playbooks WHERE {w} AND version=?", (*a, v)).fetchone()
    if not r:
        raise Denied(404)
    return {"version": r["version"], "text": r["body"], "created_at": r["created_at"], "by": _by(c, r["author_id"], None, agent_ids(c)),
            "source": r["source"]}


def pb_proposals_out(c, lid):
    rows = c.execute("SELECT * FROM playbook_proposals WHERE list_id=? AND state='open' ORDER BY id", (lid,)).fetchall()
    names = user_names(c, [r["agent_id"] for r in rows])
    return [{"id": r["id"], "agent": _by(c, r["agent_id"], names), "text": r["body"], "note": r["note"], "created_at": r["created_at"],
             "base_version": r["base_version"]} for r in rows]


def pb_list_out(c, lid, uid):
    e = pb_effective(c, lid)
    own = e["list_row"]
    can = pb_can_edit(c, lid, uid)
    return {"list_id": lid, "text": e["list_text"], "version": e["list_version"], "updated_at": own["created_at"] if own else None,
            "updated_by": _by(c, own["author_id"]) if own else None, "can_edit": can, "max": PB_MAX,
            "folders": e["folders"], "effective": e["text"],
            "proposals": pb_proposals_out(c, lid) if can else [], "checks": chk_list(c, lid) if can else []}


def _int_arg(v, what):
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise BadInput(tr("Invalid value: {0}", what))
    return v


# ---------------------------------------------------------------- web API (people): lists
@app.get("/api/lists/<int:lid>/playbook")
def pb_list_get(lid):
    c = db()
    need_list(c, lid, write=False)
    return jsonify(pb_list_out(c, lid, me()))


@app.put("/api/lists/<int:lid>/playbook")
def pb_list_put(lid):
    """{text, base_version?}: a new version (unchanged text: none). base_version older than the current one: 409."""
    c, b = db(), body()
    _need_edit(c, lid)
    try:
        text = pb_text(b.get("text"))
        base = _int_arg(b["base_version"], "base_version") if b.get("base_version") is not None else None
    except BadInput as e:
        return err(str(e))
    write_lock(c, f"playbook:{lid}")  # review M1: the base_version check under the same lock as pb_save (no lost update)
    cur = pb_current(c, lid)
    cv = cur["version"] if cur else 0
    if base is not None and base != cv and (cur["body"] if cur else "") != text:
        return jsonify(error=tr("The Playbook was changed in the meantime. Reload it and try again."), current_version=cv), 409
    v, ts, changed = pb_save(c, text, "edit", me(), lid=lid)
    if changed:
        bump(c)
    c.commit()
    return jsonify(version=v, updated_at=ts, changed=changed)


@app.get("/api/lists/<int:lid>/playbook/versions")
def pb_list_versions(lid):
    c = db()
    need_list(c, lid, write=False)
    return jsonify(versions=pb_versions_out(c, lid=lid))


@app.get("/api/lists/<int:lid>/playbook/versions/<int:v>")
def pb_list_version(lid, v):
    c = db()
    need_list(c, lid, write=False)
    return jsonify(pb_version_out(c, v, lid=lid))


@app.post("/api/lists/<int:lid>/playbook/restore")
def pb_list_restore(lid):
    """{version}: that version's text becomes the current one (a new version, source restore)."""
    c, b = db(), body()
    _need_edit(c, lid)
    try:
        v = _int_arg(b.get("version"), "version")
    except BadInput as e:
        return err(str(e))
    old = pb_version_out(c, v, lid=lid)
    nv, ts, changed = pb_save(c, old["text"], "restore", me(), lid=lid)
    if changed:
        bump(c)
    c.commit()
    return jsonify(version=nv, updated_at=ts, changed=changed)


def _prop(c, lid, pid):
    r = c.execute("SELECT * FROM playbook_proposals WHERE id=? AND list_id=?", (pid, lid)).fetchone()
    if not r:
        raise Denied(404)
    if r["state"] != "open":
        raise Denied(409, tr("This proposal was already applied or discarded"))
    return r


def _prop_decided(c, r, state, version=None):
    from ..agents.core import agent_emit
    c.execute("UPDATE playbook_proposals SET state=?, decided_by=?, decided_at=? WHERE id=?", (state, me(), iso(now_utc()), r["id"]))
    data = {"list_id": r["list_id"], "proposal_id": r["id"], "state": state, "note": r["note"],
            "by": _by(c, me()), "hint": "A person decided on your proposed change of this list's Playbook. Nothing to do; "
                                        "the current Playbook comes with this event (playbook) and with every event of the list."}
    if version is not None:
        data["version"] = version
    agent_emit(c, r["agent_id"], "playbook_proposal", data)


@app.post("/api/lists/<int:lid>/playbook/proposals/<int:pid>/apply")
def pb_prop_apply(lid, pid):
    """{text?}: the agent's proposed text (or the person's edited version of it) becomes the current Playbook."""
    c, b = db(), body()
    _need_edit(c, lid)
    r = _prop(c, lid, pid)
    try:
        text = pb_text(b["text"]) if b.get("text") is not None else r["body"]
    except BadInput as e:
        return err(str(e))
    v, ts, _ = pb_save(c, text, "proposal", me(), lid=lid)
    _prop_decided(c, r, "applied", v)
    bump(c)
    c.commit()
    return jsonify(version=v, updated_at=ts)


@app.post("/api/lists/<int:lid>/playbook/proposals/<int:pid>/discard")
def pb_prop_discard(lid, pid):
    c = db()
    _need_edit(c, lid)
    r = _prop(c, lid, pid)
    _prop_decided(c, r, "discarded")
    bump(c)
    c.commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------- web API (people): folders (only the folder's owner)
def _folder_arg(v, strict=True):
    from ..lists.lists import clean_folder
    if _is_agent_user():
        raise Denied(403)
    try:
        f = clean_folder(v if isinstance(v, str) else "", strict=strict)
    except BadInput:
        f = ""
    if not f:
        raise BadInput(tr("Invalid value: {0}", "folder"))
    return f


def _folder_parents(c, owner, f):
    parts = f.split("/")
    out = []
    for i in range(1, len(parts)):
        p = "/".join(parts[:i])
        r = pb_current(c, owner=owner, folder=p)
        if r and r["body"]:
            out.append({"folder": p, "text": r["body"], "version": r["version"], "updated_at": r["created_at"]})
    return out


@app.get("/api/folders/playbook")
def pb_folder_get():
    from ..lists.folders import folder_lists
    c, uid = db(), me()
    try:
        f = _folder_arg(request.args.get("folder"), strict=False)
    except BadInput as e:
        return err(str(e))
    cur = pb_current(c, owner=uid, folder=f)
    return jsonify(folder=f, text=cur["body"] if cur else "", version=cur["version"] if cur else 0,
                   updated_at=cur["created_at"] if cur else None, updated_by=_by(c, cur["author_id"]) if cur else None,
                   can_edit=True, max=PB_MAX, folders=_folder_parents(c, uid, f),
                   lists=[{"id": r["id"], "name": r["name"]} for r in folder_lists(c, uid, f)])


@app.put("/api/folders/playbook")
def pb_folder_put():
    """{folder, text, base_version?} -- like the list's."""
    c, b, uid = db(), body(), me()
    try:
        f = _folder_arg(b.get("folder"))
        text = pb_text(b.get("text"))
        base = _int_arg(b["base_version"], "base_version") if b.get("base_version") is not None else None
    except BadInput as e:
        return err(str(e))
    write_lock(c, f"playbook:{uid}:{f}")  # review M1
    cur = pb_current(c, owner=uid, folder=f)
    cv = cur["version"] if cur else 0
    if base is not None and base != cv and (cur["body"] if cur else "") != text:
        return jsonify(error=tr("The Playbook was changed in the meantime. Reload it and try again."), current_version=cv), 409
    v, ts, changed = pb_save(c, text, "edit", uid, owner=uid, folder=f)
    if changed:
        bump(c)
    c.commit()
    return jsonify(version=v, updated_at=ts, changed=changed)


@app.get("/api/folders/playbook/versions")
def pb_folder_versions():
    c = db()
    try:
        f = _folder_arg(request.args.get("folder"), strict=False)
    except BadInput as e:
        return err(str(e))
    return jsonify(versions=pb_versions_out(c, owner=me(), folder=f))


@app.get("/api/folders/playbook/versions/<int:v>")
def pb_folder_version(v):
    c = db()
    try:
        f = _folder_arg(request.args.get("folder"), strict=False)
    except BadInput as e:
        return err(str(e))
    return jsonify(pb_version_out(c, v, owner=me(), folder=f))


@app.post("/api/folders/playbook/restore")
def pb_folder_restore():
    c, b, uid = db(), body(), me()
    try:
        f = _folder_arg(b.get("folder"))
        v = _int_arg(b.get("version"), "version")
    except BadInput as e:
        return err(str(e))
    old = pb_version_out(c, v, owner=uid, folder=f)
    nv, ts, changed = pb_save(c, old["text"], "restore", uid, owner=uid, folder=f)
    if changed:
        bump(c)
    c.commit()
    return jsonify(version=nv, updated_at=ts, changed=changed)


# ---------------------------------------------------------------- agent API
@app.get("/api/v1/lists/<int:lid>/playbook")
@v1_view
def v1_pb_get(lid):
    """The effective Playbook of a list you see (a health list: 404): {list_id, text, list_text, folders, version, list_version,
    updated_at}."""
    v1_args(())
    c = db()
    need_list(c, lid, write=False)
    e = pb_effective(c, lid)
    if not e or e["life"] == "health":
        raise Denied(404)
    return jsonify(list_id=lid, text=e["text"], list_text=e["list_text"], folders=[{"folder": x["folder"], "text": x["text"]} for x in e["folders"]],
                   version=e["key"], list_version=e["list_version"], updated_at=e["updated_at"])


@app.post("/api/v1/lists/<int:lid>/playbook/proposals")
@v1_view
def v1_pb_propose(lid):
    """{text, note?}: an agent of the list proposes a new text of the list's own Playbook (people apply or discard it)."""
    from ..agents.core import need_agent
    from ..collab.news import news_add
    v1_args(())
    aid = need_agent()
    c = db()
    need_list(c, lid, write=False)
    lr = c.execute("SELECT name, life FROM lists WHERE id=?", (lid,)).fetchone()
    if lr["life"] == "health":
        raise Denied(404)
    b = v1_json()
    unknown = sorted(k for k in b if k not in ("text", "note"))
    if unknown:
        raise BadInput(tr("Invalid value: {0}", ", ".join(unknown)))
    text = pb_text(b.get("text"))
    note = b.get("note") or ""
    if not isinstance(note, str) or len(note) > PB_NOTE_MAX:
        raise BadInput(tr("Too long: {0} (at most {1} characters)", "note", PB_NOTE_MAX))
    write_lock(c, f"playbook:{lid}")  # review N2: the open-proposal limit holds for parallel calls
    if c.execute("SELECT COUNT(*) FROM playbook_proposals WHERE list_id=? AND agent_id=? AND state='open'", (lid, aid)).fetchone()[0] >= PB_PROP_OPEN:
        raise Denied(409, tr("At most {0} open proposals per project. Wait until people decided on them.", PB_PROP_OPEN))
    cur = pb_current(c, lid)
    if (cur["body"] if cur else "") == text:
        raise BadInput(tr("The proposal equals the current Playbook"))
    pid = insert_id(c, "INSERT INTO playbook_proposals(list_id,agent_id,body,note,base_version,state,created_at) VALUES(?,?,?,?,?,'open',?)",
                    (lid, aid, text, note.strip(), cur["version"] if cur else 0, iso(now_utc())))
    aname = user_names(c, [aid]).get(aid, "")
    for uid in pb_editors(c, lid):
        news_add(c, uid, "playbook_proposal", list_id=lid, data={"proposal_id": pid, "agent": aname, "name": lr["name"], "note": note.strip()[:300]},
                 actor=aid)
    bump(c)
    c.commit()
    return jsonify(id=pid, state="open", base_version=cur["version"] if cur else 0), 201



# ---------------------------------------------------------------- scheduled checks of a list
def chk_dict(c, r, names=None):
    names = names or user_names(c, [r["agent_id"], r["user_id"]])
    from ..agents.schedules import sched_days
    return {"id": r["id"], "agent": _by(c, r["agent_id"], names), "title": r["title"], "freq": r["freq"], "days": sched_days(r),
            "time": r["at_time"], "tz": r["tz"], "enabled": bool(r["enabled"]), "prompt": r["prompt"],
            "next_at": r["next_at"] if r["enabled"] else None, "last_at": r["last_at"], "last_state": r["last_state"] or None,
            "by": _by(c, r["user_id"], names)}


def chk_list(c, lid):
    rows = c.execute("SELECT * FROM agent_schedules WHERE list_id=? AND list_check=1 ORDER BY id", (lid,)).fetchall()
    names = user_names(c, [r["agent_id"] for r in rows] + [r["user_id"] for r in rows])
    return [chk_dict(c, r, names) for r in rows]


def chk_agents(c, lid, uid):
    """The agents of list lid uid may choose for a check (members of the list, open to uid, inside their list limit)."""
    from ..agents.core import agent_row, agent_usable, list_agents
    from ..agents.safety import ids_parse
    out = []
    for aid in list_agents(c, lid):
        a = agent_row(c, aid)
        if a and agent_usable(c, aid, uid, lid) and (not a["list_ids"] or lid in ids_parse(a["list_ids"])):
            out.append(aid)
    names = user_names(c, out)
    return [{"id": a, "name": names.get(a, "")} for a in out]


def _chk_agent(c, lid, uid, aid):
    if isinstance(aid, bool) or not isinstance(aid, int) or aid not in {a["id"] for a in chk_agents(c, lid, uid)}:
        raise BadInput(tr("Choose an agent of this project"))
    return aid


def _chk_prompt(v):
    from ..agents.schedules import SCHED_PROMPT_MAX
    if v is None:
        return ""
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", "prompt"))
    v = v.strip()
    if len(v) > SCHED_PROMPT_MAX:
        raise BadInput(tr("Too long: {0} (at most {1} characters)", "prompt", SCHED_PROMPT_MAX))
    return v


CHK_FIELDS = ("agent_id", "freq", "days", "time", "tz", "enabled", "prompt")


@app.get("/api/lists/<int:lid>/checks")
def chk_get(lid):
    c = db()
    _need_edit(c, lid)
    return jsonify(checks=chk_list(c, lid), agents=chk_agents(c, lid, me()), max=PB_CHECKS_MAX)


@app.post("/api/lists/<int:lid>/checks")
def chk_create(lid):
    """{agent_id, freq, days?, time, tz?, enabled?, prompt?}: a scheduled check of the list by one of its agents."""
    from ..agents.schedules import _sched_set_next, sched_in, sched_row, SCHED_TITLE_MAX
    c, b, uid = db(), body(), me()
    _need_edit(c, lid)
    try:
        unknown = sorted(k for k in b if k not in CHK_FIELDS)
        if unknown:
            raise BadInput(tr("Invalid value: {0}", ", ".join(unknown)))
        aid = _chk_agent(c, lid, uid, b.get("agent_id"))
        prompt = _chk_prompt(b.get("prompt"))
        name = c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone()[0]
        title = tr("Playbook check: {0}", name)[:SCHED_TITLE_MAX]
        f = sched_in(c, aid, uid, {**{k: b[k] for k in ("freq", "days", "time", "tz", "enabled") if k in b},
                                   "title": title, "prompt": prompt or "-", "list_id": lid})
    except BadInput as e:
        return err(str(e))
    if c.execute("SELECT COUNT(*) FROM agent_schedules WHERE list_id=? AND list_check=1", (lid,)).fetchone()[0] >= PB_CHECKS_MAX:
        return err(tr("At most {0} checks per project", PB_CHECKS_MAX), 409)
    ts = iso(now_utc())
    sid = insert_id(c, """INSERT INTO agent_schedules(agent_id,user_id,title,prompt,freq,days,at_time,tz,list_id,enabled,list_check,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,1,?,?)""",
                    (aid, uid, f["title"], prompt, f["freq"], f["days"], f["at_time"], f["tz"], lid, f.get("enabled", 1), ts, ts))
    _sched_set_next(c, sid)
    c.commit()
    return jsonify(chk_dict(c, sched_row(c, sid))), 201


def _chk_need(c, sid):
    """A list check the current person may manage: they may write the list's Playbook, or they manage the agent."""
    from ..agents.schedules import sched_manager, sched_row
    r = sched_row(c, sid)
    if not r or not r["list_check"] or _is_agent_user():
        raise Denied(404)
    uid = me()
    if list_role(c, r["list_id"], uid) and pb_can_edit(c, r["list_id"], uid):
        return r
    if sched_manager(c, r["agent_id"], uid):
        return r
    raise Denied(404)


@app.patch("/api/list-checks/<int:sid>")
def chk_update(sid):
    from ..agents.schedules import _sched_set_next, sched_in, sched_row
    c, b = db(), body()
    r = _chk_need(c, sid)
    try:
        unknown = sorted(k for k in b if k not in CHK_FIELDS)
        if unknown:
            raise BadInput(tr("Invalid value: {0}", ", ".join(unknown)))
        aid = r["agent_id"]
        if "agent_id" in b and b["agent_id"] != aid:
            aid = _chk_agent(c, r["list_id"], r["user_id"], b["agent_id"])
        f = sched_in(c, aid, r["user_id"], {k: b[k] for k in ("freq", "days", "time", "tz", "enabled") if k in b}, cur=r)
        if "prompt" in b:
            f["prompt"] = _chk_prompt(b["prompt"])
        if aid != r["agent_id"]:
            f["agent_id"] = aid
    except BadInput as e:
        return err(str(e))
    if f.get("enabled") and not r["enabled"]:
        f["last_state"] = ""
    sets = ", ".join(f"{k}=?" for k in f)
    c.execute(f"UPDATE agent_schedules SET {sets}, updated_at=? WHERE id=?", (*f.values(), iso(now_utc()), sid))
    _sched_set_next(c, sid)
    c.commit()
    return jsonify(chk_dict(c, sched_row(c, sid)))


@app.delete("/api/list-checks/<int:sid>")
def chk_delete(sid):
    c = db()
    _chk_need(c, sid)
    c.execute("DELETE FROM agent_schedules WHERE id=?", (sid,))
    c.commit()
    return jsonify(ok=True)


@app.post("/api/list-checks/<int:sid>/run")
def chk_run(sid):
    """Check now: the event goes out at once (manual: true), at most every SCHED_RUN_GAP_S seconds."""
    from ..agents.core import agent_active, agent_row
    from ..agents.schedules import SCHED_RUN_GAP_S, sched_fire, sched_row
    c, uid = db(), me()
    r = _chk_need(c, sid)
    now = now_utc()
    if r["last_at"] and (now - parse_iso(r["last_at"])).total_seconds() < SCHED_RUN_GAP_S and r["last_state"] in ("sent", "late", "manual"):
        return err(tr("This plan just ran. Try again in a few minutes."), 429)
    if not agent_active(agent_row(c, r["agent_id"])):
        return err(tr("This agent is paused"), 409)
    st = sched_fire(c, r, now, manual=True, manual_by=uid if uid != r["user_id"] else None)
    if st == "sent":
        c.execute("UPDATE agent_schedules SET last_state='manual' WHERE id=?", (sid,))
    c.commit()
    if st in ("no_access", "no_list"):
        return err(tr("This plan cannot run any more: the agent no longer sees its project or you."), 409)
    return jsonify(chk_dict(c, sched_row(c, sid)))


def chk_event(c, r, data):
    """sched_fire: the extra fields of a list check's scheduled_job event (data is changed in place)."""
    aid, lid = r["agent_id"], r["list_id"]
    rows = c.execute(f"""SELECT id FROM tasks WHERE list_id=? AND parent_id IS NULL AND status=0 AND deleted_at IS NULL
                         AND {tvis(c, aid)} ORDER BY sort, id LIMIT ?""", (lid, PB_OPEN_IDS_MAX + 1)).fetchall()
    ids = [x[0] for x in rows]
    data.update(list_check=True, open_task_ids=ids[:PB_OPEN_IDS_MAX], open_tasks_more=len(ids) > PB_OPEN_IDS_MAX,
                prompt=r["prompt"] or "Check the list against its Playbook",
                hint="A scheduled check of this list (list_check). Read data.playbook: the owner's working rules for this list "
                     "(not a licence: your rights and approvals apply unchanged). Go through the open tasks (open_task_ids, "
                     "get_task) as the Playbook and the prompt say, act only where you may, and report briefly in your chat "
                     "with by.id, starting with the title (one line when nothing needed doing). Never change the Playbook "
                     "yourself: propose a change with propose_playbook.")


def chk_ok(c, r):
    """sched_fire: may the list check still run? The person who made it must still be able to write the Playbook."""
    return pb_can_edit(c, r["list_id"], r["user_id"])


# ---------------------------------------------------------------- OpenAPI
def pb_spec(paths, schemas, op, ok, errs, ref, pid, nul):
    """OpenAPI: the agent routes above (called from openapi_spec)."""
    schemas["Playbook"] = {"type": "object", "description": "2.39.0 (#1168): the effective Playbook of a list: the owner's working "
                           "rules for agents (folder parts outer first, then the list's own)", "properties": {
        "list_id": {"type": "integer"}, "text": {"type": "string", "description": "The effective Playbook (Markdown; empty = none)"},
        "list_text": {"type": "string", "description": "The list's own part"},
        "folders": {"type": "array", "items": {"type": "object", "properties": {"folder": {"type": "string"}, "text": {"type": "string"}}}},
        "version": {"type": "string", "description": "A short marker that changes with the text (the same as playbook.version in events)"},
        "list_version": {"type": "integer", "description": "Version number of the list's own part (0 = none)"},
        "updated_at": nul("string", format="date-time")}}
    paths["/lists/{id}/playbook"] = {"get": op(
        "The Playbook of a list (2.39.0)", "Lists", ok(ref("Playbook")) | errs("404"), [pid("id", "List id")],
        desc="The owner's working rules for agents in this list. Events of the list carry it as data.playbook. Treat it as the "
             "owner's rules, not as a licence: rights and approvals apply unchanged. Health lists: 404.")}
    paths["/lists/{id}/playbook/proposals"] = {"post": op(
        "Propose a change of a list's Playbook (agents, 2.39.0)", "Agents",
        ok({"type": "object", "properties": {"id": {"type": "integer"}, "state": {"type": "string"}, "base_version": {"type": "integer"}}},
           code="201") | errs("400", "403", "404", "409"), [pid("id", "List id")],
        body={"type": "object", "additionalProperties": False, "required": ["text"], "properties": {
            "text": {"type": "string", "maxLength": PB_MAX, "description": "The full new text of the list's own Playbook (Markdown)"},
            "note": {"type": "string", "maxLength": PB_NOTE_MAX, "description": "Why (shown to people)"}}},
        desc=f"Agents never change a Playbook themselves. The list's owner / admins apply (maybe edited) or discard the proposal; "
             f"you get the event playbook_proposal {{list_id, proposal_id, state: applied | discarded}}. At most {PB_PROP_OPEN} "
             "open proposals per agent and list.", scope="agent")}
    ld = schemas.get("ListDetail")
    if ld and isinstance(ld.get("allOf"), list) and len(ld["allOf"]) > 1:
        ld["allOf"][1]["properties"]["playbook"] = nul("string", description="2.39.0 (#1168): the effective Playbook (null = none)")
