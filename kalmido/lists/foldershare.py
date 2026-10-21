"""2.41.0 (#1420): sharing a whole folder in one dialog, like a list -- the parts the list dialog has that need a folder
route of their own: the folder's agents (several; folder_agents), handing every own list in the folder to another person,
and the public links of the folder's lists switched together.

The agents: a list keeps at most one agent (2.26.0). The first agent of a folder (by pos) is its default: it is mirrored into
folder_props.props.agent_id (the 2.29 folder default, so 2.40 reads the same database after a rollback) and the lists follow
it like before (folder_apply). Further agents of the folder can be chosen per list in the list's Share dialog; such a list
differs from the folder ("differs: Agent") as before. "Agent listens in" is stored per agent (folder_agents.listen) and
reaches the lists where that agent is the agent; the first agent's value is mirrored into props.agent_listen.
Old clients that only write props.agent_id keep working: folder_props_put calls sh_folder_agents_from_props.
Health lists never get an agent (_folder_member_add / member_set) and never a public link from here."""
import json
from flask import g, jsonify, request

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, now_utc
from ..accounts.session import me
from ..core.access import Denied, need_collab
from ..core.errors import BadInput  # 2.149.0 G (#2517): pulled up from functions
from ..api.common import v1_call  # 2.149.0 G (#2517): pulled up from functions


def sh_folder_agents(c, owner, folder):
    """[{agent_id, name, listen, first}] of exactly this folder (disabled agents left out)."""
    rows = c.execute("""SELECT a.agent_id, a.listen, u.display_name, u.username FROM folder_agents a JOIN users u ON u.id=a.agent_id
                        WHERE a.owner_id=? AND a.folder=? AND u.disabled=0 ORDER BY a.pos, a.created_at, a.agent_id""", (owner, folder)).fetchall()
    return [{"agent_id": r["agent_id"], "name": r["display_name"] or r["username"], "listen": None if r["listen"] is None else bool(r["listen"]),
             "first": i == 0} for i, r in enumerate(rows)]


def sh_folder_agents_eff(c, owner, path):
    """The agents a list at `path` gets offered: the subfolder's own, else its top folder's (like folder_effective)."""
    from ..lists.lists import FOLDER_SEP
    parts = (path or "").split(FOLDER_SEP) if path else []
    for i in range(len(parts), 0, -1):
        a = sh_folder_agents(c, owner, FOLDER_SEP.join(parts[:i]))
        if a:
            return a
    return []


def _props_write(c, owner, folder, upd):
    """Merges upd into folder_props.props of the folder (None removes a key)."""
    from ..lists.folders import folder_props_of
    props = {k: v for k, v in {**folder_props_of(c, owner, folder), **upd}.items() if v is not None}
    if props:
        c.execute("INSERT INTO folder_props(owner_id,folder,props,updated_at) VALUES(?,?,?,?) ON CONFLICT(owner_id,folder) "
                  "DO UPDATE SET props=excluded.props, updated_at=excluded.updated_at", (owner, folder, json.dumps(props), iso(now_utc())))
    else:
        c.execute("DELETE FROM folder_props WHERE owner_id=? AND folder=?", (owner, folder))


def sh_mirror(c, owner, folder):
    """props.agent_id / agent_listen follow the first agent (no agent left: the keys go, the folder no longer sets an agent)."""
    from ..lists.folders import folder_props_of
    a = sh_folder_agents(c, owner, folder)
    cur = folder_props_of(c, owner, folder)
    if a:
        upd = {"agent_id": a[0]["agent_id"]}
        if a[0]["listen"] is not None:
            upd["agent_listen"] = a[0]["listen"]
        elif cur.get("agent_id") != a[0]["agent_id"]:
            upd["agent_listen"] = None  # 2.41.0 (#1420): a new first agent without listen drops the previous one's value
        _props_write(c, owner, folder, upd)
    else:
        if cur.get("agent_id"):  # 0 ("no agent" on purpose) stays
            _props_write(c, owner, folder, {"agent_id": None})


def sh_folder_agents_from_props(c, owner, folder, agent_id):
    """An old client (or the API) set props.agent_id: that agent becomes the folder's first agent (0 / None: the folder has
    no agents any more). Called by folder_props_put."""
    if agent_id:
        if not c.execute("SELECT 1 FROM folder_agents WHERE owner_id=? AND folder=? AND agent_id=?", (owner, folder, agent_id)).fetchone():
            c.execute("INSERT INTO folder_agents(owner_id,folder,agent_id,pos,created_at) VALUES(?,?,?,?,?)", (owner, folder, agent_id, 0, iso(now_utc())))
        mn = c.execute("SELECT MIN(pos) FROM folder_agents WHERE owner_id=? AND folder=? AND agent_id!=?", (owner, folder, agent_id)).fetchone()[0]
        c.execute("UPDATE folder_agents SET pos=? WHERE owner_id=? AND folder=? AND agent_id=?", ((mn or 0) - 1, owner, folder, agent_id))
    elif agent_id is not None:
        c.execute("DELETE FROM folder_agents WHERE owner_id=? AND folder=?", (owner, folder))


def sh_folder_agents_sync(c):
    """Start-up, every time (idempotent, additive): a folder default agent in folder_props (2.29-2.40, or written by 2.40
    after a rollback) that is not in folder_agents becomes the folder's first agent. Nothing is removed. -> number added."""
    n = 0
    for r in c.execute("SELECT owner_id, folder, props FROM folder_props").fetchall():
        try:
            p = json.loads(r["props"] or "{}")
        except ValueError:
            continue
        aid = p.get("agent_id") if isinstance(p, dict) else None
        if not isinstance(aid, int) or isinstance(aid, bool) or aid <= 0:
            continue
        if not c.execute("SELECT 1 FROM users WHERE id=? AND kind='agent'", (aid,)).fetchone():
            continue
        if c.execute("SELECT 1 FROM folder_agents WHERE owner_id=? AND folder=? AND agent_id=?", (r["owner_id"], r["folder"], aid)).fetchone():
            continue
        mn = c.execute("SELECT MIN(pos) FROM folder_agents WHERE owner_id=? AND folder=?", (r["owner_id"], r["folder"])).fetchone()[0]
        lis = p.get("agent_listen")
        c.execute("INSERT INTO folder_agents(owner_id,folder,agent_id,pos,listen,created_at) VALUES(?,?,?,?,?,?)",
                  (r["owner_id"], r["folder"], aid, (mn - 1) if mn is not None else 0, None if lis is None else int(bool(lis)), iso(now_utc())))
        n += 1
    return n


def sh_folder_rename(c, uid, old, new):
    """The folder (and its subfolders) renamed / moved: its agents go along."""
    from ..lists.lists import folder_under
    for r in c.execute("SELECT folder, agent_id FROM folder_agents WHERE owner_id=?", (uid,)).fetchall():
        if folder_under(r[0], old):
            nf = new + r[0][len(old):]
            c.execute("DELETE FROM folder_agents WHERE owner_id=? AND folder=? AND agent_id=? AND folder<>?", (uid, nf, r[1], r[0]))
            c.execute("UPDATE folder_agents SET folder=? WHERE owner_id=? AND folder=? AND agent_id=?", (nf, uid, r[0], r[1]))


def _folder_arg(strict=True):
    from ..lists.lists import clean_folder
    f = clean_folder((request.args.get("folder") if request.method == "GET" else (body().get("folder"))) or "", strict=strict)
    if not f:
        raise _Bad(tr("Invalid value: {0}", "folder"))
    return f


class _Bad(Exception):
    pass


def _own_lists(c, f):
    from ..lists.folders import folder_lists
    return folder_lists(c, me(), f)


def _list_agent(c, lid):
    from ..lists.folders import _list_agent as la
    return la(c, lid)


def _agents_out(c, f):
    from ..lists.folders import folder_props_of
    from ..lists.lists import FOLDER_SEP
    own = sh_folder_agents(c, me(), f)
    inh = [] if own or FOLDER_SEP not in f else sh_folder_agents_eff(c, me(), f.rsplit(FOLDER_SEP, 1)[0])
    lists = _own_lists(c, f)
    return {"folder": f, "agents": own, "inherited": inh, "props": folder_props_of(c, me(), f),
            "lists": [{"id": r["id"], "name": r["name"], "agent_id": _list_agent(c, r["id"])} for r in lists]}


@app.get("/api/folders/agents")
def sh_agents_get():
    """?folder=: the agents of my folder ({agents: [{agent_id, name, listen, first}], inherited: the top folder's when this
    subfolder has none, lists: my lists in it with their agent)."""
    c = db()
    try:
        f = _folder_arg(strict=False)
    except _Bad as e:
        return err(str(e))
    return jsonify(_agents_out(c, f))


def _apply_lists(c, f, keys):
    from ..lists.folders import folder_apply
    shared, skipped = 0, []
    for r in _own_lists(c, f):
        sk, n = folder_apply(c, r["id"], keys=keys, uid=me())
        shared += n
        if sk:
            skipped.append({"id": r["id"], "name": r["name"], "reasons": [x["reason"] for x in sk]})
    return shared, skipped


@app.put("/api/folders/agents")
def sh_agents_put():
    """{folder, agent_id, listen?: bool|null, first?: true, apply?: all|new}: adds an agent to my folder or changes it.
    The first agent is the default of the folder's lists: they follow it (apply all, default) or only new lists do (new).
    listen reaches the folder's lists where this agent is the agent. -> the folder's agents + {changed, skipped}."""
    from ..lists.folders import _clean_props
    need_collab()
    if g.user["kind"] == "agent":
        raise Denied(403)
    c, b = db(), body()
    try:
        f = _folder_arg()
    except _Bad as e:
        return err(str(e))
    aid = b.get("agent_id")
    try:
        _clean_props(c, {"agent_id": aid})
    except BadInput as e:
        return err(str(e))
    if not aid:
        return err(tr("Invalid value: {0}", "agent_id"))
    apply = b.get("apply", "all")
    if apply not in ("all", "new"):
        return err(tr("Invalid value: {0}", "apply"))
    if "listen" in b and b["listen"] is not None and not isinstance(b["listen"], bool):
        return err(tr("Invalid value: {0}", "listen"))
    before = sh_folder_agents(c, me(), f)
    was_first = bool(before) and before[0]["agent_id"] == aid
    if not any(a["agent_id"] == aid for a in before):
        mx = c.execute("SELECT MAX(pos) FROM folder_agents WHERE owner_id=? AND folder=?", (me(), f)).fetchone()[0]
        c.execute("INSERT INTO folder_agents(owner_id,folder,agent_id,pos,created_at) VALUES(?,?,?,?,?)",
                  (me(), f, aid, (mx + 1) if mx is not None else 0, iso(now_utc())))
    if b.get("first") is True:
        mn = c.execute("SELECT MIN(pos) FROM folder_agents WHERE owner_id=? AND folder=? AND agent_id!=?", (me(), f, aid)).fetchone()[0]
        c.execute("UPDATE folder_agents SET pos=? WHERE owner_id=? AND folder=? AND agent_id=?", ((mn or 0) - 1, me(), f, aid))
    if "listen" in b:
        c.execute("UPDATE folder_agents SET listen=? WHERE owner_id=? AND folder=? AND agent_id=?",
                  (None if b["listen"] is None else int(b["listen"]), me(), f, aid))
    after = sh_folder_agents(c, me(), f)
    now_first = after[0]["agent_id"] == aid
    sh_mirror(c, me(), f)
    changed, skipped = 0, []
    if apply == "all":
        keys = []
        if now_first and not was_first:
            keys.append("agent_id")
        if now_first and "listen" in b and b["listen"] is not None:
            keys.append("agent_listen")
        if keys:
            changed, skipped = _apply_lists(c, f, keys)
        if "listen" in b and b["listen"] is not None and not now_first:  # a further agent: the lists where it is the agent
            from ..agents.core import listen_set_all
            for r in _own_lists(c, f):
                if _list_agent(c, r["id"]) == aid:
                    listen_set_all(c, r["id"], bool(b["listen"]))
                    changed += 1
    bump(c)
    c.commit()
    return jsonify(**_agents_out(c, f), changed=changed, skipped=skipped)


@app.delete("/api/folders/agents")
def sh_agents_delete():
    """{folder, agent_id, remove?: true}: the agent is no longer one of my folder's agents; remove also takes it out of the
    folder's lists now (else they keep it). The next agent becomes the default for new lists."""
    from ..lists.lists import list_agent_set
    if g.user["kind"] == "agent":
        raise Denied(403)
    c, b = db(), body()
    try:
        f = _folder_arg(strict=False)
    except _Bad as e:
        return err(str(e))
    aid = b.get("agent_id")
    if not isinstance(aid, int) or isinstance(aid, bool):
        return err(tr("Invalid value: {0}", "agent_id"))
    c.execute("DELETE FROM folder_agents WHERE owner_id=? AND folder=? AND agent_id=?", (me(), f, aid))
    sh_mirror(c, me(), f)
    removed = 0
    if b.get("remove") is True:
        for r in _own_lists(c, f):
            if _list_agent(c, r["id"]) == aid:
                g.folder_applying = True
                try:
                    v1_call(list_agent_set, r["id"], body={"agent_id": None})
                    removed += 1
                finally:
                    g.folder_applying = False
    bump(c)
    c.commit()
    return jsonify(**_agents_out(c, f), removed=removed)


@app.post("/api/folders/owner")
def sh_folder_owner():
    """{folder, user_id}: hands every list of mine in the folder (and its subfolders) to another active person, list by list
    with the rules of "Transfer ownership" (a list of an organisation only inside it). I stay in them as list admin.
    -> {moved, skipped: [{id, name, reason}]}"""
    from ..agents.core import is_agent
    from ..accounts.orgs import ws_check_member
    from ..lists.ownership import owner_transfer
    need_collab()
    if is_agent(g.user):
        raise Denied(403)
    c, b = db(), body()
    try:
        f = _folder_arg()
    except _Bad as e:
        return err(str(e))
    try:
        new = int(b.get("user_id") or 0)
    except (TypeError, ValueError):
        new = 0
    from ..accounts.orgs import may_see
    u = c.execute("SELECT * FROM users WHERE id=?", (new,)).fetchone()
    if not u or u["disabled"] or new == me() or not may_see(c, me(), new):
        return err(tr("unknown user"), 404)
    if is_agent(u):
        return err(tr("An agent cannot own a list"))
    moved, skipped = 0, []
    for r in _own_lists(c, f):
        lr = c.execute("SELECT * FROM lists WHERE id=?", (r["id"],)).fetchone()
        try:
            with c.savepoint():
                ws_check_member(c, r["id"], new)
                owner_transfer(c, lr, new)
            moved += 1
        except Denied as e:
            skipped.append({"id": r["id"], "name": r["name"], "reason": e.text()})
    bump(c)
    c.commit()
    print("folder", repr(f), "ownership of", moved, "list(s) ->", new, "by", g.user["username"], flush=True)
    return jsonify(moved=moved, skipped=skipped)


def _pub_rows(c, f):
    out = []
    from ..lists.public import pub_public
    for r in _own_lists(c, f):
        lr = c.execute("SELECT life, e2e FROM lists WHERE id=?", (r["id"],)).fetchone()
        p = c.execute("SELECT * FROM public_links WHERE list_id=?", (r["id"],)).fetchone()
        out.append({"id": r["id"], "name": r["name"], "health": (lr["life"] or "") == "health", "link": pub_public(c, p) if p else None,
                    "e2e": bool(lr["e2e"]),  # 2.64.1 (#1817): a list with the lock never gets one
                    "budget": (lr["life"] or "") == "budget"})  # 2.72.0 (#1333)
    return out


@app.get("/api/folders/public-links")
def sh_pub_get():
    """?folder=: the public links of my lists in the folder ({enabled, lists: [{id, name, health, link}]})."""
    from ..lists.public import public_links_on
    c = db()
    try:
        f = _folder_arg(strict=False)
    except _Bad as e:
        return err(str(e))
    return jsonify(enabled=public_links_on(c), lists=_pub_rows(c, f))


@app.put("/api/folders/public-links")
def sh_pub_put():
    """{folder, on: bool, notes?: bool}: turns the read-only public links of all my lists in the folder on (an existing link
    stays as it is) or off. Health lists never get one. -> {enabled, lists, created, removed}"""
    from ..lists.public import public_links_on, pub_new_token
    if g.user["kind"] == "agent":
        raise Denied(403)
    c, b = db(), body()
    try:
        f = _folder_arg()
    except _Bad as e:
        return err(str(e))
    on = b.get("on")
    if not isinstance(on, bool) or ("notes" in b and not isinstance(b["notes"], bool)):
        return err(tr("Invalid value: {0}", "on"))
    if on and not public_links_on(c):
        return err(tr("Public links are turned off on this server"), 409)
    created = removed = 0
    for r in _pub_rows(c, f):
        if on and not r["link"] and not r["health"] and not r["e2e"] and not r.get("budget"):  # 2.72.0 (#1333): a budget neither
            _, h, sealed = pub_new_token(c, r["id"])
            c.execute("""INSERT INTO public_links(list_id,token_hash,token,mode,notes,password_hash,pw_rev,expires_at,created_by,created_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?)""", (r["id"], h, sealed, "view", 1 if b.get("notes") else 0, None, 0, None, me(), iso(now_utc())))
            created += 1
        elif not on and r["link"]:
            c.execute("DELETE FROM public_links WHERE list_id=?", (r["id"],))
            removed += 1
    if created or removed:
        bump(c)  # 2.41.0 (#1420): the owner's other devices see the new / removed links at once
    c.commit()
    print("folder", repr(f), "public links", "on" if on else "off", created, removed, flush=True)
    return jsonify(enabled=public_links_on(c), lists=_pub_rows(c, f), created=created, removed=removed)


def sh_folder_shares(c, uid):
    """2.41.0 (#1428): {folder: {people, groups, agents: [names]}} of my folders shared themselves (folder people, groups,
    agents; a subfolder inherits its top folder's) -- the sidebar marks them like shared lists."""
    out = {}

    def slot(f):
        return out.setdefault(f, {"people": 0, "groups": 0, "agents": []})
    for r in c.execute("SELECT folder, COUNT(*) FROM folder_people WHERE owner_id=? GROUP BY folder", (uid,)).fetchall():
        slot(r[0])["people"] = r[1]
    for r in c.execute("SELECT folder, COUNT(*) FROM group_shares WHERE owner_id=? AND list_id IS NULL AND folder IS NOT NULL GROUP BY folder",
                       (uid,)).fetchall():
        slot(r[0])["groups"] = r[1]
    for r in c.execute("""SELECT a.folder, u.display_name, u.username FROM folder_agents a JOIN users u ON u.id=a.agent_id
                          WHERE a.owner_id=? AND u.disabled=0 ORDER BY a.folder, a.pos, a.agent_id""", (uid,)).fetchall():
        slot(r[0])["agents"].append(r[1] or r[2])
    return out
