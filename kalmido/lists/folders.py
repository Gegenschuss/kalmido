"""2.29.0 (#1030 / #929): folder settings. A folder of its owner carries defaults for every list in it and in its subfolders
(the owner's lists; members see the lists in their own folders): the workspace, the agent with "Members may use it" /
"Agents may address each other", tidying -- next to the people and their roles (folder_people, "Share folder"), which
work since 2.22.0. A new list in the folder gets them, a list moved into it too; changing them asks whether the existing
lists follow. A list changed on its own keeps its value (lists.folder_own, "differs from the folder") until "Back to the
folder". Someone who creates a list in a folder shared with them keeps it and it is shared with the folder's owner and
people at once."""
import json
from flask import g, jsonify, request

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, now_utc, uset, usettings
from ..accounts.session import me
from ..accounts.login import login_log_who  # 2.239.0 B (#2888)
from ..core.access import Denied, need_collab, collab_all, need_list
from ..core.errors import BadInput
from ..api.common import v1_call, V1Error  # 2.149.0 G (#2517): pulled up from functions
from ..lists.lists import folder_under  # 2.411.0 (#3516)

# 2.40.0 (#1373): agent_peers is no folder default any more (agents never address each other); a stored one is ignored
FOLDER_PROPS = ("org_id", "agent_id", "agent_members", "agent_tidy", "agent_listen")  # 2.30.0 (#1034): agent_listen
FOLDER_PROPS += ("hide_done",)  # 2.39.1 (#1214): "Hide completed" for the lists of the folder; 2.46.1 (#1422): a real default, see lc_done_*
FOLDER_PROPS += ("agent_followup",)  # 2.41.0 (#1423): "Agent follows up" as a folder default (2.40 ignores the key)
FOLDER_PROPS += ("time_tracking",)  # 2.41.0 (#1471): time tracking on / off for the lists of the folder (lists.time_tracking)
FOLDER_PROPS += ("ptype",)  # 2.411.0 (#3516): the project type of NEW lists in the folder (folder_ptype); existing lists keep theirs
FOLDER_APPLY = ("all", "new")


def _fsep():
    from ..lists.lists import FOLDER_SEP
    return FOLDER_SEP


def _under(p, top):
    from ..lists.lists import folder_under
    return folder_under(p or "", top)


def _props(raw):
    try:
        d = json.loads(raw or "{}")
    except ValueError:
        d = {}
    return {k: v for k, v in d.items() if k in FOLDER_PROPS} if isinstance(d, dict) else {}


def folder_props_of(c, owner, folder):
    """The props stored on exactly this folder ({} = none)."""
    r = c.execute("SELECT props FROM folder_props WHERE owner_id=? AND folder=?", (owner, folder)).fetchone()
    return _props(r[0]) if r else {}


def folder_effective(c, owner, path):
    """The defaults for a list at `path` of owner: the top folder's, overridden by the subfolder's -> ({key: value},
    {key: folder it comes from})."""
    if not path:
        return {}, {}
    parts = path.split(_fsep())
    out, src = {}, {}
    for i in range(1, len(parts) + 1):
        f = _fsep().join(parts[:i])
        for k, v in folder_props_of(c, owner, f).items():
            out[k], src[k] = v, f
    return out, src


def list_own(c, lid):
    r = c.execute("SELECT folder_own FROM lists WHERE id=?", (lid,)).fetchone()
    try:
        v = json.loads(r[0] or "[]") if r else []
    except ValueError:
        v = []
    return [k for k in v if k in FOLDER_PROPS] if isinstance(v, list) else []


def list_own_mark(c, lid, key, on=True):
    """A list's setting changed on its own (key): it differs from its folder from now on (only while the folder sets that key)."""
    own = set(list_own(c, lid))
    if on:
        r = c.execute("SELECT owner_id, folder FROM lists WHERE id=?", (lid,)).fetchone()
        if not r or key not in folder_effective(c, r["owner_id"], r["folder"] or "")[0]:
            return
        own.add(key)
    else:
        own.discard(key)
    c.execute("UPDATE lists SET folder_own=? WHERE id=?", (json.dumps(sorted(own)), lid))


def _v1_msg(e):
    try:
        return (e.resp.get_json() or {}).get("error") or ""
    except Exception:  # noqa: BLE001
        return ""


def _list_agent(c, lid):
    r = c.execute("SELECT m.user_id FROM list_members m JOIN users u ON u.id=m.user_id WHERE m.list_id=? AND u.kind='agent' "
                  "AND NOT (m.frole IS NOT NULL AND m.own_role IS NULL) ORDER BY m.user_id", (lid,)).fetchone()  # 2.352.0 A (#2748): not a folder's agent
    return r[0] if r else None


def folder_apply(c, lid, keys=None, force=False, dry=False, uid=None):
    """Applies the folder defaults to list lid (of the current person, its owner). keys: only these (None = all set ones);
    force: also the ones the list keeps on its own. Returns [{key, reason}] of what could not be applied (dry: what WOULD not,
    nothing is changed) and the number of changed settings. 2.58.0 (#1422): uid = the person (the callers pass it)."""
    uid = uid or me()
    from ..accounts.orgs import clean_org_id, list_org, list_space_follow, ws_member_problem
    from ..collab.reactions import list_tidy_update
    from ..lists.lists import list_agent_set
    lr = c.execute("SELECT id, owner_id, folder, is_inbox, family, life, archived FROM lists WHERE id=?", (lid,)).fetchone()
    if not lr or lr["is_inbox"] or lr["owner_id"] != uid:
        return [], 0
    eff, _ = folder_effective(c, lr["owner_id"], lr["folder"] or "")
    own = set() if force else set(list_own(c, lid))
    skipped, changed = [], 0
    for k in FOLDER_PROPS:
        if k not in eff or (keys is not None and k not in keys) or k in own or k == "ptype":  # 2.411.0 (#3516): only list_create takes it
            continue
        v = eff[k]
        try:
            if k == "org_id":
                want = v or None
                if (list_org(c, lid) or None) == want:
                    continue
                if want and (lr["family"] or (lr["life"] and lr["life"] != "travel")):  # 2.173.1 A (#2714): a trip moves as in list_org_set
                    skipped.append({"key": k, "reason": tr("Home & life and family projects stay private")})
                    continue
                if want:
                    clean_org_id(c, want, uid)
                from ..accounts.orgout import OO_ADMIN_ONLY, org_out, org_out_ok
                cur = list_org(c, lid) or None
                if not org_out_ok(c, cur, want, "list", lid):  # 2.361.2 (#2923): + a released request  # 2.148.1 B (#2483): out of an organisation only through its admin
                    skipped.append({"key": k, "reason": tr(OO_ADMIN_ONLY)})
                    continue
                bad = [r[0] for r in c.execute("SELECT user_id FROM list_members WHERE list_id=?", (lid,)) if ws_member_problem(c, lid, r[0], org_id=want or 0)]
                if bad:
                    names = ", ".join(r[0] or r[1] for r in c.execute(f"SELECT display_name, username FROM users WHERE id IN ({','.join('?' * len(bad))})", bad))
                    skipped.append({"key": k, "reason": tr("Not in the workspace: {0}", names)})
                    continue
                if not dry:
                    lname = c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone()[0]
                    org_out(c, cur, want, "list", lname, list_id=lid, obj=lid)  # 2.148.1 B (#2483): logged, admins told
                    c.execute("UPDATE lists SET org_id=? WHERE id=?", (want, lid))
                    from ..team.clients import _org_boundary
                    list_space_follow(c, lid, cur, _org_boundary(c))  # 2.401.0 (#2924): its customer reports and bells go along
                    if _org_boundary(c):  # 2.173.1 (#2714): a client of another workspace does not travel along (as in list_org_set)
                        c.execute("UPDATE lists SET client_id=NULL WHERE id=? AND client_id IS NOT NULL AND client_id NOT IN"
                                  " (SELECT id FROM clients WHERE org_id IS NOT DISTINCT FROM ?)", (lid, want))
                    from ..admin.orgcrypt_cli import oc_settle_kick
                    oc_settle_kick([lid])  # 2.42.0 (#828), 2.64.0 (#1864): the list's files get the key of its new space
                changed += 1
            elif k == "agent_id":
                v = v or None  # 0 = "no agent"
                if _list_agent(c, lid) == v:
                    continue
                if v and ws_member_problem(c, lid, v, org_id=(eff.get("org_id") or 0) if "org_id" in eff and "org_id" not in own else None):
                    skipped.append({"key": k, "reason": tr("The agent works in another workspace")})
                    continue
                from ..agents.safety import bridge_blocks
                if v and bridge_blocks(c, lid, v):  # 2.30.0 (#919): would connect lists with different people
                    skipped.append({"key": k, "reason": tr("This project has other people than the agent’s other projects. Choose the agent here explicitly so it may see them.")})
                    continue
                if not dry:
                    g.folder_applying = True  # list_agent_set must not mark it as the list's own
                    prev = g.user  # 2.82.0 (#1831): the inner call runs as the person uid too (the list's owner), not the caller
                    if prev is None or prev["id"] != uid:
                        g.user = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
                    try:
                        v1_call(list_agent_set, lid, body={"agent_id": v})
                    finally:
                        g.folder_applying = False
                        g.user = prev
                changed += 1
            elif k in ("agent_members", "agent_peers", "agent_followup", "time_tracking"):  # 2.41.0 (#1423): + agent_followup, (#1471) time_tracking
                cur = c.execute(f"SELECT {k} FROM lists WHERE id=?", (lid,)).fetchone()[0]
                if int(bool(v)) == int(cur or 0):
                    continue
                if not dry:
                    c.execute(f"UPDATE lists SET {k}=? WHERE id=?", (int(bool(v)), lid))
                changed += 1
            elif k == "agent_listen":  # 2.30.0 (#1034): every agent of the list listens in / only per @mention
                from ..agents.core import listen_set_all
                cur = c.execute("SELECT agent_listen FROM lists WHERE id=?", (lid,)).fetchone()[0]
                if cur == ("*" if v else "-*"):
                    continue
                if not dry:
                    listen_set_all(c, lid, bool(v))
                changed += 1
            elif k == "hide_done":  # 2.46.1 (#1422): the list follows the folder: the owner's own choice for it goes
                views = lc_done_views(c, uid)
                prev = (getattr(g, "lc_done_prev", None) or {}).get(lid)
                if prev is None:
                    prev = lc_done_shown(c, uid, lid, lr["folder"], views)
                if f"l:{lid}" in views and not dry:
                    del views[f"l:{lid}"]
                    lc_done_put(c, uid, views)
                if prev == bool(v):  # it showed completed tasks and the folder hides them, or the other way round
                    changed += 1
            elif k == "agent_tidy":
                cur = c.execute("SELECT agent_tidy FROM lists WHERE id=?", (lid,)).fetchone()[0] or "off"
                if cur == v:
                    continue
                if dry:
                    if v != "off" and not (_list_agent(c, lid) or eff.get("agent_id")):
                        skipped.append({"key": k, "reason": tr("Share the project with an agent first")})
                    else:
                        changed += 1
                    continue
                e = list_tidy_update(c, lid, v)
                if e:
                    skipped.append({"key": k, "reason": e})
                else:
                    changed += 1
        except V1Error as e:
            skipped.append({"key": k, "reason": _v1_msg(e) or tr("Not possible")})
        except Denied as e:
            skipped.append({"key": k, "reason": e.text()})
        except BadInput as e:
            skipped.append({"key": k, "reason": str(e)})
    if force and not dry:
        c.execute("UPDATE lists SET folder_own='[]' WHERE id=?", (lid,))
    return skipped, changed


def folder_lists(c, owner, folder):
    from ..lists.lists import folder_under
    return [r for r in c.execute("SELECT id, name, folder FROM lists WHERE owner_id=? AND is_inbox=0 AND archived=0 ORDER BY sort, id", (owner,))
            if folder_under(r["folder"] or "", folder)]


def _clean_props(c, b):
    from ..accounts.orgs import clean_org_id
    from ..agents.core import agent_ids, TIDY_MODES
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid value: {0}", "props"))
    out = {}
    for k, v in b.items():
        if k == "agent_peers":  # 2.40.0 (#1373): still accepted from old clients, ignored
            continue
        if k not in FOLDER_PROPS:
            raise BadInput(tr("Invalid value: {0}", k))
        if v is None:
            out[k] = None  # removes the default
        elif k == "org_id":
            out[k] = clean_org_id(c, v, me()) or 0  # 0 = private (a default, unlike None)
        elif k == "agent_id":
            if v in (0, "none"):
                out[k] = 0  # 0 = "no agent" as the default
            elif isinstance(v, bool) or not isinstance(v, int) or v not in agent_ids(c):
                raise BadInput(tr("Invalid value: {0}", k))
            else:
                from ..agents.core import agent_shares
                from ..agents.admin import agent_owner
                o = agent_owner(c, v)
                if (o is not None and o != me()) or (o is None and not agent_shares(c, v, me()) and not g.user["is_admin"]):
                    raise BadInput(tr("Invalid value: {0}", k))
                out[k] = v
        elif k in ("agent_members", "agent_peers", "agent_listen", "hide_done", "agent_followup", "time_tracking"):  # 2.41.0 (#1471): time_tracking
            if not isinstance(v, bool) and v not in (0, 1):
                raise BadInput(tr("Invalid value: {0}", k))
            out[k] = bool(v)
        elif k == "agent_tidy":
            if v not in TIDY_MODES:
                raise BadInput(tr("Invalid value: {0}", k))
            out[k] = v
        elif k == "ptype":  # 2.411.0 (#3516)
            from ..lists.templates import PTYPES
            if v not in PTYPES:
                raise BadInput(tr("Invalid value: {0}", k))
            out[k] = v
    return out


def folder_ptype(c, owner, folder):
    """2.411.0 (#3516): the project type a new list of owner in folder gets ('' = none): the folder's default (ptype, also from
    the folder above); without one the type the owner's projects in the folder (and its subfolders) have -- when those with a
    type all share it and they are more than the ones without (a few lists made before without a type do not break it)."""
    if not folder:
        return ""
    eff = folder_effective(c, owner, folder)[0]
    if eff.get("ptype"):
        return eff["ptype"]
    from ..lists.templates import PTYPES
    ts = [r[1] or "" for r in c.execute("SELECT folder, ptype FROM lists WHERE owner_id=? AND is_inbox=0 AND archived=0 AND family=''", (owner,))
          if folder_under(r[0] or "", folder)]
    typed = {t for t in ts if t}
    if len(typed) != 1 or 2 * sum(1 for t in ts if t) <= len(ts):
        return ""
    t = typed.pop()
    return t if t in PTYPES else ""


def _norm(props):
    """Stored form -> applied form: org_id 0 = private (None), agent_id 0 = no agent (None)."""
    return {k: (None if k in ("org_id", "agent_id") and not v else v) for k, v in props.items()}


def folder_info(c, owner, folder):
    eff, src = folder_effective(c, owner, folder)
    rows = folder_lists(c, owner, folder)
    return {"folder": folder, "props": folder_props_of(c, owner, folder),
            "inherited": {k: {"value": v, "folder": src[k]} for k, v in eff.items() if src[k] != folder},
            "lists": [{"id": r["id"], "name": r["name"], "own": list_own(c, r["id"])} for r in rows]}


@app.get("/api/folders/props")
def folder_props_get():
    """?folder=: the defaults of my folder (props), the ones it inherits from its top folder, and its lists with the keys
    each keeps on its own."""
    from ..lists.lists import clean_folder
    c = db()
    from ..lists.lffolder import lf_path_arg
    f = clean_folder(lf_path_arg(c, request.args.get("folder"), request.args.get("node")) or "", strict=False)  # 2.352.0 A (#2748): or node=
    if not f:
        return err(tr("Invalid value: {0}", "folder"))
    return jsonify(folder_info(c, me(), f))


@app.put("/api/folders/props")
def folder_props_put():
    """{folder, props: {org_id?, agent_id?, agent_members?, agent_peers?, agent_tidy?, agent_listen?} (null removes a default),
    apply: all (default: the existing lists follow) | new (only lists that come later), force?: also the lists that differ on
    purpose, dry_run?: only say what would happen}. -> {props, changed, lists: [{id, name, skipped: [{key, reason}]}]}"""
    from ..lists.lists import clean_folder
    c, b = db(), body()
    if g.user["kind"] == "agent":
        raise Denied(403)
    from ..lists.lffolder import lf_path_arg
    f = clean_folder(lf_path_arg(c, b.get("folder"), b.get("node")) or "")  # 2.352.0 A (#2748): or node=
    if not f:
        return err(tr("Invalid value: {0}", "folder"))
    apply = b.get("apply", "all")
    if apply not in FOLDER_APPLY:
        return err(tr("Invalid value: {0}", "apply"))
    try:
        new = _clean_props(c, b.get("props") or {})
    except BadInput as e:
        return err(str(e))
    if new.get("agent_id") or new.get("agent_tidy") not in (None, "off"):
        need_collab()
    cur = folder_props_of(c, me(), f)
    props = {k: v for k, v in {**cur, **new}.items() if v is not None}
    dry = b.get("dry_run") is True
    out, changed = [], 0
    if "hide_done" in new:  # 2.46.1 (#1422): what each list shows before the change (counted / kept below)
        g.lc_done_prev = {r["id"]: lc_done_shown(c, me(), r["id"], r["folder"]) for r in folder_lists(c, me(), f)}
    if not dry:
        if props:
            c.execute("INSERT INTO folder_props(owner_id,folder,props,updated_at) VALUES(?,?,?,?) ON CONFLICT(owner_id,folder) "
                      "DO UPDATE SET props=excluded.props, updated_at=excluded.updated_at", (me(), f, json.dumps(props), iso(now_utc())))
        else:
            c.execute("DELETE FROM folder_props WHERE owner_id=? AND folder=?", (me(), f))
        if "agent_id" in new:  # 2.41.0 (#1420): the one agent of an older client = the folder's first agent (none: no agents)
            from ..lists.foldershare import sh_folder_agents_from_props
            sh_folder_agents_from_props(c, me(), f, new["agent_id"] or 0)
    if "hide_done" in new and not dry and (apply == "new" or new["hide_done"] is None):
        lc_done_keep(c, f)  # 2.46.1 (#1422): "Only new lists" / "Not set" again: the lists keep what they show
    if apply == "all":
        keys = [k for k in new if new[k] is not None]
        if dry:  # what would happen: the new values against every list; rolled back below, nothing stays
            c.execute("INSERT INTO folder_props(owner_id,folder,props,updated_at) VALUES(?,?,?,?) ON CONFLICT(owner_id,folder) "
                      "DO UPDATE SET props=excluded.props", (me(), f, json.dumps(props), iso(now_utc())))
        for r in folder_lists(c, me(), f):
            sk, n = folder_apply(c, r["id"], keys=keys, force=b.get("force") is True, dry=dry, uid=me())
            changed += n
            if sk or (list_own(c, r["id"]) and not b.get("force")):
                out.append({"id": r["id"], "name": r["name"], "skipped": sk,
                            "own": [k for k in list_own(c, r["id"]) if k in keys] if not b.get("force") else []})
    if dry:
        c.rollback()
        return jsonify(props=_norm(props), changed=changed, lists=out, dry_run=True)
    bump(c)
    c.commit()
    print("folder", repr(f), "of", login_log_who(g.user), "props", json.dumps(props), "apply", apply, flush=True)
    return jsonify(props=_norm(props), changed=changed, lists=out)


@app.post("/api/lists/<int:lid>/folder-reset")
def list_folder_reset(lid):
    """{keys?: [...]}: the list takes its folder's defaults again (all keys, or these) -- "Back to the folder"."""
    c, b = db(), body()
    r = c.execute("SELECT owner_id FROM lists WHERE id=?", (lid,)).fetchone()
    if not r or r[0] != me():
        raise Denied(403, tr("Only the owner can change this project"))
    keys = b.get("keys")
    if isinstance(keys, list):
        keys = [k for k in keys if k != "agent_peers"]  # 2.40.0 (#1373): no folder default any more
    if keys is not None and (not isinstance(keys, list) or any(k not in FOLDER_PROPS for k in keys)):
        return err(tr("Invalid value: {0}", "keys"))
    own = [k for k in list_own(c, lid) if keys is not None and k not in keys]
    c.execute("UPDATE lists SET folder_own=? WHERE id=?", (json.dumps(own), lid))
    sk, n = folder_apply(c, lid, keys=keys, uid=me())
    bump(c)
    c.commit()
    return jsonify(ok=True, changed=n, skipped=sk)


def folder_list_arrived(c, lid, keep=()):
    """A list of mine came into a folder (created there, moved there): it takes the folder's defaults (a moved list forgets
    what it kept on its own in its old folder). keep: keys the person set explicitly in the same request -- they stay and,
    when they differ from the folder, are marked as the list's own. What cannot be applied is skipped (the list stays as it is)."""
    r = c.execute("SELECT owner_id, folder FROM lists WHERE id=?", (lid,)).fetchone()
    if not r or not r["folder"] or r["owner_id"] != me():
        return
    eff = folder_effective(c, r["owner_id"], r["folder"])[0]
    if not eff:
        return
    c.execute("UPDATE lists SET folder_own='[]' WHERE id=?", (lid,))
    # 2.40.0 (#1422): only a kept value that really differs from the folder's counts as the list's own (the list dialog
    # sends the workspace with every create, the same value as the folder's must not show "differs: Workspace")
    diff = {x["key"] for x in lm_folder_changes(c, lid, r["folder"])} if keep else set()
    for k in keep:
        if k in eff and (k in diff or k not in LM_MOVE_KEYS):
            list_own_mark(c, lid, k)
    folder_apply(c, lid, keys=[k for k in FOLDER_PROPS if k not in keep], uid=r["owner_id"])


def folder_member_created(c, uid, lid):
    """A list someone creates in a folder that is shared with them stays theirs and is shared with the folder's
    owner (list admin) and the folder's other people (their folder roles) at once -- the folder sits with them under the same
    name (member_folder_adopt). Returns the number of people it was shared with."""
    from ..lists.lists import _folder_member_add, folder_under
    from ..accounts.orgs import may_see
    r = c.execute("SELECT owner_id, folder, is_inbox FROM lists WHERE id=?", (lid,)).fetchone()
    if not r or r["is_inbox"] or not r["folder"] or r["owner_id"] != uid or not collab_all():
        return 0
    n = 0
    for fp in c.execute("SELECT owner_id, folder FROM folder_people WHERE user_id=? AND owner_id!=?", (uid, uid)).fetchall():
        if not folder_under(r["folder"], fp["folder"]) or not may_see(c, uid, fp["owner_id"]):
            continue
        # only the folder that really holds the owner's shared lists for uid (not a private folder of the same name)
        if not any(folder_under(m["folder"] or "", r["folder"].split("/")[0]) and folder_under(m["lfolder"] or "", fp["folder"])
                   for m in c.execute("""SELECT m.folder, l.folder AS lfolder FROM list_members m JOIN lists l ON l.id=m.list_id
                                         WHERE m.user_id=? AND l.owner_id=?""", (uid, fp["owner_id"]))):
            continue
        if _folder_member_add(c, lid, fp["owner_id"], "admin", uid):
            n += 1
        from ..agents.admin import personal_agent_foreign
        for p in c.execute("SELECT user_id, role FROM folder_people WHERE owner_id=? AND folder=? AND user_id!=?", (fp["owner_id"], fp["folder"], uid)).fetchall():
            # 2.30.0 (#1036): only people uid may see and no personal agent of somebody else (as when uid shares by hand);
            # the workspace rule itself is checked by _folder_member_add
            if not may_see(c, uid, p["user_id"]) or personal_agent_foreign(c, p["user_id"], uid):
                continue
            if _folder_member_add(c, lid, p["user_id"], p["role"], uid):
                n += 1
    return n


def folders_shared_in(c, uid):
    """The folders of other people shared with uid (the new-list dialog says the list will be shared with them)."""
    out = []
    for fp in c.execute("""SELECT f.owner_id, f.folder, u.display_name, u.username FROM folder_people f JOIN users u ON u.id=f.owner_id
                           WHERE f.user_id=? AND f.owner_id!=? ORDER BY f.folder""", (uid, uid)).fetchall():
        n = c.execute("SELECT COUNT(*) FROM folder_people WHERE owner_id=? AND folder=? AND user_id!=?", (fp["owner_id"], fp["folder"], uid)).fetchone()[0]
        out.append({"owner_id": fp["owner_id"], "owner_name": fp["display_name"] or fp["username"], "folder": fp["folder"], "people": n + 1})
    return out


def my_folder_props(c, uid):
    """{folder: props} of my folders (the sidebar marks them, the list dialog says "from the folder")."""
    return {r["folder"]: _norm(_props(r["props"])) for r in c.execute("SELECT folder, props FROM folder_props WHERE owner_id=?", (uid,))}


# 2.39.1 (#1188): moving a list into a folder with defaults never re-hangs it silently. The app asks first when the move
# would change the workspace or the agent (both directions: private -> organisation and back) and then sends
# folder_adopt: true; without it the list keeps its settings and the differing ones count as its own ("differs from the folder").
LM_MOVE_KEYS = ("org_id", "agent_id", "agent_members", "agent_tidy", "agent_listen")  # 2.40.0 (#1373): no agent_peers


def lm_folder_changes(c, lid, folder):
    """What moving my list lid into `folder` would change: [{key, from, to}] (org_id / agent_id with names too)."""
    from ..accounts.orgs import list_org
    lr = c.execute("SELECT owner_id, is_inbox, agent_members, agent_peers, agent_tidy, agent_listen FROM lists WHERE id=?", (lid,)).fetchone()
    if not lr or lr["is_inbox"] or lr["owner_id"] != me():
        return []
    eff = _norm(folder_effective(c, lr["owner_id"], folder or "")[0])
    out = []
    for k in LM_MOVE_KEYS:
        if k not in eff:
            continue
        v = eff[k]
        if k == "org_id":
            cur = list_org(c, lid) or None
        elif k == "agent_id":
            cur = _list_agent(c, lid)
        elif k in ("agent_members", "agent_peers"):
            cur, v = bool(lr[k]), bool(v)
        elif k == "agent_listen":
            cur, v = lr[k] == "*", bool(v)
        else:
            cur = lr[k] or "off"
        if cur != v:
            out.append({"key": k, "from": cur, "to": v})
    names = {}
    oids = [x[y] for x in out if x["key"] == "org_id" for y in ("from", "to") if x[y]]
    for r in c.execute(f"SELECT id, name FROM orgs WHERE id IN ({','.join('?' * len(oids)) or 'NULL'})", oids).fetchall() if oids else []:
        names[("org", r[0])] = r[1]
    aids = [x[y] for x in out if x["key"] == "agent_id" for y in ("from", "to") if x[y]]
    for r in c.execute(f"SELECT id, display_name, username FROM users WHERE id IN ({','.join('?' * len(aids)) or 'NULL'})", aids).fetchall() if aids else []:
        names[("agent", r[0])] = r[1] or r[2]
    for x in out:
        if x["key"] in ("org_id", "agent_id"):
            t = "org" if x["key"] == "org_id" else "agent"
            x["from_name"], x["to_name"] = names.get((t, x["from"]), ""), names.get((t, x["to"]), "")
    return out


def lm_folder_keep(c, lid, keep=(), uid=None):
    """My list lid moved into a folder without folder_adopt: nothing is applied; what differs from the folder (and the
    keys set in the same request) counts as the list's own from now on. 2.58.0 (#1422): uid = the person."""
    uid = uid or me()
    r = c.execute("SELECT owner_id, folder FROM lists WHERE id=?", (lid,)).fetchone()
    if not r or r["owner_id"] != uid:
        return
    diff = {x["key"] for x in lm_folder_changes(c, lid, r["folder"] or "")} | {k for k in keep if k not in LM_MOVE_KEYS}  # 2.40.0 (#1422)
    eff = folder_effective(c, r["owner_id"], r["folder"] or "")[0]
    if lc_done_differs(c, uid, lid, eff):  # 2.46.1 (#1422): an own "Show / Hide completed" of the list
        diff.add("hide_done")
    c.execute("UPDATE lists SET folder_own=? WHERE id=?", (json.dumps(sorted(k for k in diff if k in eff)), lid))


def lm_folder_moved(c, lid, adopt, keep=()):
    """A list of mine really moved into another folder (PATCH, drag): adopt = the person confirmed the folder's settings."""
    if adopt:
        folder_list_arrived(c, lid, keep=keep)
    else:
        lm_folder_keep(c, lid, keep=keep, uid=me())


@app.get("/api/lists/<int:lid>/folder-preview")
def lm_folder_preview(lid):
    """?folder=: what moving my list into that folder would change (workspace, agent and its settings) -> {changes:
    [{key, from, to, from_name?, to_name?}]}. Empty = nothing to confirm. Members / other lists: always empty."""
    from ..lists.lists import clean_folder
    c = db()
    need_list(c, lid, write=False)
    f = clean_folder(request.args.get("folder") or "", strict=False)
    return jsonify(changes=lm_folder_changes(c, lid, f))


# ---- 2.46.1 (#1422): "Hide completed" (hide_done) as a real folder default for the owner's own lists. What a list shows is
# the owner's own choice for it (user setting show_done_views, key "l:<id>"), else the folder default, else the person's
# default (the client: showDone / lmDoneDefault). The folder applies through folder_apply like its other defaults: a list
# that follows drops the owner's own choice; an own choice that differs from the folder marks the list (folder_own
# "hide_done": "This list differs", "Back to the folder"); "Only new lists" and "Not set" again keep what each list shows.
# Shared lists of others keep their own settings (only the owner's lists, as for every folder default).
def lc_done_views(c, uid):
    try:
        d = json.loads(usettings(c, uid).get("show_done_views") or "{}")
    except ValueError:
        d = {}
    return d if isinstance(d, dict) else {}


def lc_done_put(c, uid, views):
    uset(c, uid, "show_done_views", json.dumps(views, ensure_ascii=False, separators=(",", ":")))


def lc_done_shown(c, uid, lid, folder, views=None):
    """True when list lid of uid shows its completed tasks now."""
    v = (lc_done_views(c, uid) if views is None else views).get(f"l:{lid}")
    if v is not None:
        return bool(int(v))
    eff = folder_effective(c, uid, folder or "")[0]
    if "hide_done" in eff:
        return not eff["hide_done"]
    return usettings(c, uid).get("show_done_default") != "0"


def lc_done_differs(c, uid, lid, eff, views=None):
    """The owner chose "Show / Hide completed" for list lid against the folder's default."""
    v = (lc_done_views(c, uid) if views is None else views).get(f"l:{lid}")
    return "hide_done" in eff and v is not None and bool(int(v)) == bool(eff["hide_done"])


def lc_done_keep(c, folder):
    """After the folder default changed without the lists following: every list of mine in it keeps what it showed before
    (g.lc_done_prev) as its own choice; where that differs from the folder, the list is marked as differing."""
    prev = getattr(g, "lc_done_prev", None) or {}
    views = lc_done_views(c, me())
    for r in folder_lists(c, me(), folder):
        was = prev.get(r["id"])
        if was is not None and f"l:{r['id']}" not in views and lc_done_shown(c, me(), r["id"], r["folder"], views) != was:
            views[f"l:{r['id']}"] = int(was)
    lc_done_put(c, me(), views)
    for r in folder_lists(c, me(), folder):
        eff = folder_effective(c, me(), r["folder"] or "")[0]
        list_own_mark(c, r["id"], "hide_done", lc_done_differs(c, me(), r["id"], eff, views))


def lc_done_sync(c, uid, old_raw, new_raw):
    """The person changed their per-view choices (PATCH /api/settings show_done_views): a changed entry of an own list in a
    folder with "Hide completed" marks the list as differing from the folder (or no longer)."""
    try:
        old, new = json.loads(old_raw or "{}"), json.loads(new_raw or "{}")
    except ValueError:
        return
    if not isinstance(old, dict) or not isinstance(new, dict):
        return
    for k in {k for k in set(old) | set(new) if old.get(k) != new.get(k) and k.startswith("l:") and k[2:].isdigit()}:
        r = c.execute("SELECT id, owner_id, folder FROM lists WHERE id=?", (int(k[2:]),)).fetchone()
        if not r or r["owner_id"] != uid or not r["folder"]:
            continue
        eff = folder_effective(c, uid, r["folder"])[0]
        if "hide_done" in eff:
            list_own_mark(c, r["id"], "hide_done", lc_done_differs(c, uid, r["id"], eff, new))
