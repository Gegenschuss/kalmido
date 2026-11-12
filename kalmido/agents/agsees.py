"""2.1045.0 (#5822): what an agent sees right now -- the section "Sees now" of the dialog "Edit agent".

Rights decide WHAT an agent may do, shares decide WHERE: a scope such as "Read knowledge pages" opens nothing until a
knowledge folder is shared with exactly that agent. This module only READS the shares that exist; it adds no way of sharing.
The dialog makes and ends shares through the existing routes: a folder / page / the whole knowledge area (its root node
"Knowledge") with POST /api/files/nodes/<id>/shares {agent_id, role} and DELETE /api/files/shares/<id> (fs_shares, the
core's way), a project with PUT /api/lists/<id>/members {user_id, role} and DELETE /api/lists/<id>/members/<agent>.

GET /api/agents/<id>/sees[?options=1] -> {agent, items, hidden, counts, except, except_hidden[, options]}
- who may ask: who may edit the agent (agents/workstyle.py ws_need_editor: the owner of a personal agent -- nobody else, not
  even an instance admin --, an instance admin for a team agent, and then only an agent the admin may see); 404 otherwise.
- items: the live shares with exactly this agent the ASKER may see themselves: projects (membership, its own projects),
  knowledge folders / pages / whole areas, folders and files of the file store and the other areas, each with the role
  view / edit. A share the asker may not see is only counted (hidden: "+ n more") -- no name, no path, no owner.
- counts: {project, wiki, files} -- every share of each kind (seen or not), so the dialog can tell "Nothing shared yet" only
  when there is really nothing (a hidden share is something).
- except / except_hidden: the knowledge folders the agent's data lock keeps out of a whole-area share (agents.data_lock
  "wiki_folders", part B of 2.1045); names only of the folders the asker sees.
- options (only with ?options=1, for "Share…"): what the asker may share with this agent -- projects they manage in the
  agent's workspace, the knowledge areas (first choice "Entire knowledge area" = the root node) with their folders, the
  folders of the file store. An area the agent never reaches comes greyed with the reason (encrypted in the browser, an
  organisation's pages for a private agent, another workspace).
Shares that cannot work (expired, in the trash, another organisation than the agent's, an encrypted knowledge area) are not
listed: the agent does not see through them."""
import json

from flask import jsonify, request

from ..core.config import app
from ..core.access import Denied, MANAGE_ROLES, list_role, live_sql, otr_live
from ..core.db import db
from ..core.i18n import tr
from ..core.pg import system_ctx
from ..accounts.orgroles import org_sees_all, org_writes
from ..accounts.orgs import user_orgs
from ..accounts.session import me
from ..accounts.users import admin_sees
from ..agents.admin import need_agent_admin
from ..agents.datalock import _dl_lists_locked
from ..agents.workstyle import ws_need_editor
from ..files.fsroots import fs_area_root_of
from ..files.store import _now, fs_chain, fs_deleted, fs_role
from ..wiki.wkfolder import WKF_AREA, WKF_KIND, _root_of_chain, _space_locked, _subtree, _walk, wkf_root

AGS_MAX = 500          # rows of one kind in an answer (shares, options)
AGS_DEPTH = 8          # folder levels of the file store offered in "Share…"


def ags_need(c, aid):
    """The agent row when the signed-in person may edit agent aid (module docstring), else Denied(404)."""
    a = ws_need_editor(c, aid)
    if not a["owner_id"]:
        need_agent_admin(c, aid)  # the hosted operator never reads a client's agent (op_apart_deny)
        if not admin_sees(c, aid):
            raise Denied(404)
    return a


def _org_names(c, ids):
    ids = sorted({int(x) for x in ids if x})
    if not ids:
        return {}
    with system_ctx(c):  # names of the asker's own organisations only (ids come from their memberships / visible nodes)
        return {r[0]: r[1] for r in c.execute(f"SELECT id, name FROM orgs WHERE id IN ({','.join('?' * len(ids))})", ids)}


def _role(r):
    return "view" if r == "view" else "edit"


def _agent_reaches(c, aid, nid, chain):
    """Does the agent reach node nid through its shares at all (the boundary, a locked folder, an encrypted area)?"""
    if not chain or fs_deleted(chain):
        return False
    top = _root_of_chain(c, chain)
    if top is not None and _space_locked(c, top["org_id"] or None, None if top["org_id"] else top["owner_id"]):
        return False  # an area encrypted in the browser: its old nodes give nothing (wiki/wkfolder.py)
    return bool(fs_role(c, nid, aid, chain=chain))


def _asker_sees(c, uid, nid):
    """The chain of node nid when the asker sees it themselves (their own rules, not the agent's), else None."""
    chain = fs_chain(c, nid)
    if not chain or fs_deleted(chain):
        return None
    try:
        if not fs_role(c, nid, uid, chain=chain):
            return None
        if chain[0]["kind"] == "ref":
            from ..files.fsref import fs_ref_rows
            if not fs_ref_rows(c, uid, [chain[0]]):
                return None
    except Denied:
        return None
    return chain


def _may_unshare(c, nid):
    """May the asker end shares of node nid (the file store's own check of DELETE /api/files/shares)?"""
    from ..files.web import _need_share_node
    try:
        _need_share_node(c, nid)
        return True
    except Denied:
        return False


def _node_item(c, uid, s, chain, spaces):
    n = chain[0]
    top = _root_of_chain(c, chain)
    it = {"id": s["id"], "node_id": n["id"], "role": _role(s["role"]), "expires_at": s["expires_at"],
          "can_remove": _may_unshare(c, n["id"])}
    if top is not None:
        oid = top["org_id"] or None
        it["kind"] = "wiki"
        it["space"] = spaces.get(oid, tr("Private")) if oid else tr("Private")
        it["whole"] = n["id"] == top["id"]
        it["page"] = n["kind"] == "ref" and n["ref_kind"] == WKF_KIND
        it["name"] = tr("Entire knowledge area") if it["whole"] else n["name"]
        it["path"] = "/".join(x["name"] for x in reversed(chain))  # starts at "Knowledge"
        return it
    ar = fs_area_root_of(c, chain[-1]["id"])
    it["kind"] = "files"
    it["area"] = ar[1] if ar else ""
    it["folder"] = n["kind"] == "folder"
    it["name"] = n["name"]
    it["path"] = "/".join(x["name"] for x in reversed(chain))
    return it


def _shares(c, a, uid):
    """(items, hidden, counts) of the node shares with agent a (module docstring)."""
    aid = a["user_id"]
    with system_ctx(c):  # every share row of the agent (structure: ids and roles); what the asker sees is decided below
        rows = c.execute("""SELECT s.id, s.node_id, s.role, s.expires_at FROM fs_shares s WHERE (s.agent_id=? OR s.user_id=?)
                            AND COALESCE(s.list_own, 0)=0 AND (s.expires_at IS NULL OR s.expires_at > ?) ORDER BY s.id LIMIT ?""",
                         (aid, aid, _now(), AGS_MAX * 4)).fetchall()
        live = []
        for s in rows:
            chain = fs_chain(c, s["node_id"])
            ar = fs_area_root_of(c, chain[-1]["id"]) if chain else None
            if ar and ar[1] == "lists":
                continue  # a projects folder: its projects are memberships of the agent (listed as projects)
            if _agent_reaches(c, aid, s["node_id"], chain):
                live.append((s, _root_of_chain(c, chain) is not None))
    spaces = _org_names(c, user_orgs(c, uid))
    items, hidden, counts = [], 0, {"project": 0, "wiki": 0, "files": 0}
    for s, wiki in live:
        counts["wiki" if wiki else "files"] += 1
        chain = _asker_sees(c, uid, s["node_id"])
        if chain is None or len(items) >= AGS_MAX:
            hidden += 1
            continue
        items.append(_node_item(c, uid, s, chain, spaces))
    return items, hidden, counts


def _projects(c, a, uid):
    """(items, hidden, count) of the projects the agent is a member of / owns (not its basket, not in the trash)."""
    aid = a["user_id"]
    with system_ctx(c):
        rows = c.execute(f"""SELECT l.id, l.name, l.owner_id, m.role FROM lists l LEFT JOIN list_members m ON m.list_id=l.id AND m.user_id=?
                            WHERE (m.user_id IS NOT NULL OR l.owner_id=?) AND l.is_inbox=0 AND {otr_live('l')}
                            AND l.org_id IS NOT DISTINCT FROM ? ORDER BY lower(l.name), l.id LIMIT ?""",
                         (aid, aid, a["org_id"], AGS_MAX * 2)).fetchall()  # another workspace's project gives the agent nothing
    locked = _dl_lists_locked(c, aid, [r["id"] for r in rows])
    items, hidden = [], 0
    for r in rows:
        mine = list_role(c, r["id"], uid)
        if not mine or len(items) >= AGS_MAX:
            hidden += 1
            continue
        own = r["owner_id"] == aid
        items.append({"kind": "project", "id": r["id"], "list_id": r["id"], "name": r["name"],
                      "role": "edit" if own else _role(r["role"]), "list_role": "owner" if own else r["role"],
                      "locked": r["id"] in locked, "can_remove": not own and mine in MANAGE_ROLES})
    return items, hidden, len(rows)


def _excepts(c, a, uid):
    """(folders, hidden) of the data lock's knowledge folders (part B: agents.data_lock "wiki_folders")."""
    try:
        ids = json.loads(a["data_lock"] or "{}").get("wiki_folders") or []
    except (ValueError, TypeError, AttributeError):
        return [], 0
    out, hidden = [], 0
    for x in ids[:AGS_MAX]:
        if isinstance(x, bool) or not isinstance(x, int):
            continue
        chain = _asker_sees(c, uid, x)
        if chain is None or _root_of_chain(c, chain) is None:
            hidden += 1
            continue
        out.append({"id": x, "name": chain[0]["name"], "path": "/".join(n["name"] for n in reversed(chain))})
    return out, hidden


# ---- "Share…": what the asker may share with this agent
def _opt_projects(c, a, uid):
    aid = a["user_id"]
    rows = c.execute(f"""SELECT l.id, l.name FROM lists l WHERE l.is_inbox=0 AND COALESCE(l.quicknote, 0)=0 AND COALESCE(l.archived, 0)=0
                        AND {otr_live('l')} AND COALESCE(l.life, '') NOT IN ('health', 'budget')
                        AND l.org_id IS NOT DISTINCT FROM ? AND l.owner_id != ?
                        AND NOT EXISTS (SELECT 1 FROM list_members m WHERE m.list_id=l.id AND m.user_id=?)
                        ORDER BY lower(l.name), l.id LIMIT ?""", (a["org_id"], aid, aid, AGS_MAX * 2)).fetchall()
    out = []
    for r in rows:
        if list_role(c, r["id"], uid) in MANAGE_ROLES and len(out) < AGS_MAX:
            out.append({"id": r["id"], "name": r["name"]})
    return out


def _space_block(c, a, uid, oid, label):
    """One knowledge area for "Share…": {space, org_id, root, disabled, folders}."""
    owner = None if oid else uid
    blk = {"space": label, "org_id": oid, "root": None, "disabled": "", "folders": []}
    if _space_locked(c, oid, owner):
        blk["disabled"] = tr("Agents never reach encrypted areas")
        return blk
    if oid and not a["org_id"] and a["owner_id"]:
        blk["disabled"] = tr("A private personal agent never sees the pages of an organisation")
        return blk
    if (a["org_id"] or None) != (oid or None):
        blk["disabled"] = tr("Another workspace: the agent works only in its own")
        return blk
    if not oid and a["owner_id"] != uid:
        blk["disabled"] = tr("Only your own personal agent can see your private knowledge pages")
        return blk
    if oid and not (org_sees_all(c, uid, oid) and org_writes(c, uid, oid)):
        blk["disabled"] = tr("Only people who may write in this area share its pages")
        return blk
    root = wkf_root(c, uid, oid)
    if not root:
        blk["disabled"] = tr("No knowledge pages yet")
        return blk
    blk["root"] = root
    rows = _subtree(c, root)
    fp = _walk(rows, root)
    for r in rows:
        if r["kind"] == "folder" and r["id"] != root and r["id"] in fp and not fp[r["id"]][1] and len(blk["folders"]) < AGS_MAX:
            blk["folders"].append({"id": r["id"], "name": r["name"], "path": fp[r["id"]][0]})
    blk["folders"].sort(key=lambda f: f["path"].lower())
    return blk


def _opt_wiki(c, a, uid, spaces):
    out = [_space_block(c, a, uid, None, tr("Private"))]
    for oid in sorted(spaces):
        out.append(_space_block(c, a, uid, oid, spaces[oid]))
    return out


def _opt_files(c, a, uid):
    """The folders of the file store (not of an area) in the agent's workspace that the asker owns / administers."""
    org = a["org_id"]
    rows = c.execute(f"""WITH RECURSIVE t(id, path, depth) AS (
                           SELECT n.id, n.name, 1 FROM fs_nodes n WHERE n.parent_id IS NULL AND n.kind='folder' AND {live_sql('n')}
                             AND n.org_id IS NOT DISTINCT FROM ? AND {'TRUE' if org else 'n.owner_id=?'}
                             AND NOT EXISTS (SELECT 1 FROM fs_area_roots r WHERE r.node_id=n.id)
                           UNION ALL SELECT n.id, t.path || '/' || n.name, t.depth + 1 FROM fs_nodes n JOIN t ON n.parent_id=t.id
                             WHERE n.kind='folder' AND {live_sql('n')} AND t.depth < ?)
                         SELECT id, path FROM t ORDER BY lower(path) LIMIT ?""",
                     (org, *(() if org else (uid,)), AGS_DEPTH, AGS_MAX * 2)).fetchall()
    out = []
    for r in rows:
        if len(out) >= AGS_MAX:
            break
        if fs_role(c, r["id"], uid) == "owner":
            out.append({"id": r["id"], "name": r["path"].rsplit("/", 1)[-1], "path": r["path"]})
    return out


@app.get("/api/agents/<int:aid>/sees")
def ags_route(aid):
    c = db()
    a = ags_need(c, aid)
    uid = me()
    items, hidden, counts = _shares(c, a, uid)
    pitems, phidden, pcount = _projects(c, a, uid)
    counts["project"] = pcount
    ex, ex_hidden = _excepts(c, a, uid)
    out = {"agent": {"id": aid, "org_id": a["org_id"], "personal": bool(a["owner_id"])},
           "items": pitems + items, "hidden": hidden + phidden, "counts": counts, "except": ex, "except_hidden": ex_hidden}
    if request.args.get("options") == "1":
        spaces = _org_names(c, user_orgs(c, uid))
        out["options"] = {"projects": _opt_projects(c, a, uid), "wiki": _opt_wiki(c, a, uid, spaces), "files": _opt_files(c, a, uid)}
    return jsonify(out)
