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
from ..core.db import body, bump, db, err, iso, now_utc
from ..accounts.session import me
from ..core.access import Denied, need_collab
from ..personal.timetrack import BadInput

FOLDER_PROPS = ("org_id", "agent_id", "agent_members", "agent_peers", "agent_tidy")
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
    r = c.execute("SELECT m.user_id FROM list_members m JOIN users u ON u.id=m.user_id WHERE m.list_id=? AND u.kind='agent' ORDER BY m.user_id",
                  (lid,)).fetchone()
    return r[0] if r else None


def folder_apply(c, lid, keys=None, force=False, dry=False):
    """Applies the folder defaults to list lid (of the current person, its owner). keys: only these (None = all set ones);
    force: also the ones the list keeps on its own. Returns [{key, reason}] of what could not be applied (dry: what WOULD not,
    nothing is changed) and the number of changed settings."""
    from ..api.v1 import V1Error, v1_call
    from ..accounts.orgs import clean_org_id, list_org, ws_member_problem
    from ..collab.reactions import list_tidy_update
    from ..lists.lists import list_agent_set
    lr = c.execute("SELECT id, owner_id, folder, is_inbox, family, life, archived FROM lists WHERE id=?", (lid,)).fetchone()
    if not lr or lr["is_inbox"] or lr["owner_id"] != me():
        return [], 0
    eff, _ = folder_effective(c, lr["owner_id"], lr["folder"] or "")
    own = set() if force else set(list_own(c, lid))
    skipped, changed = [], 0
    for k in FOLDER_PROPS:
        if k not in eff or (keys is not None and k not in keys) or k in own:
            continue
        v = eff[k]
        try:
            if k == "org_id":
                want = v or None
                if (list_org(c, lid) or None) == want:
                    continue
                if want and (lr["family"] or lr["life"]):
                    skipped.append({"key": k, "reason": tr("Home & life and family lists stay private")})
                    continue
                if want:
                    clean_org_id(c, want, me())
                bad = [r[0] for r in c.execute("SELECT user_id FROM list_members WHERE list_id=?", (lid,)) if ws_member_problem(c, lid, r[0], org_id=want or 0)]
                if bad:
                    names = ", ".join(r[0] or r[1] for r in c.execute(f"SELECT display_name, username FROM users WHERE id IN ({','.join('?' * len(bad))})", bad))
                    skipped.append({"key": k, "reason": tr("Not in the workspace: {0}", names)})
                    continue
                if not dry:
                    c.execute("UPDATE lists SET org_id=? WHERE id=?", (want, lid))
                changed += 1
            elif k == "agent_id":
                v = v or None  # 0 = "no agent"
                if _list_agent(c, lid) == v:
                    continue
                if v and ws_member_problem(c, lid, v, org_id=(eff.get("org_id") or 0) if "org_id" in eff and "org_id" not in own else None):
                    skipped.append({"key": k, "reason": tr("The agent works in another workspace")})
                    continue
                if not dry:
                    g.folder_applying = True  # list_agent_set must not mark it as the list's own
                    try:
                        v1_call(list_agent_set, lid, body={"agent_id": v})
                    finally:
                        g.folder_applying = False
                changed += 1
            elif k in ("agent_members", "agent_peers"):
                cur = c.execute(f"SELECT {k} FROM lists WHERE id=?", (lid,)).fetchone()[0]
                if int(bool(v)) == int(cur or 0):
                    continue
                if not dry:
                    c.execute(f"UPDATE lists SET {k}=? WHERE id=?", (int(bool(v)), lid))
                changed += 1
            elif k == "agent_tidy":
                cur = c.execute("SELECT agent_tidy FROM lists WHERE id=?", (lid,)).fetchone()[0] or "off"
                if cur == v:
                    continue
                if dry:
                    if v != "off" and not (_list_agent(c, lid) or eff.get("agent_id")):
                        skipped.append({"key": k, "reason": tr("Share the list with an agent first")})
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
        elif k in ("agent_members", "agent_peers"):
            if not isinstance(v, bool) and v not in (0, 1):
                raise BadInput(tr("Invalid value: {0}", k))
            out[k] = bool(v)
        elif k == "agent_tidy":
            if v not in TIDY_MODES:
                raise BadInput(tr("Invalid value: {0}", k))
            out[k] = v
    return out


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
    f = clean_folder(request.args.get("folder") or "", strict=False)
    if not f:
        return err(tr("Invalid value: {0}", "folder"))
    return jsonify(folder_info(c, me(), f))


@app.put("/api/folders/props")
def folder_props_put():
    """{folder, props: {org_id?, agent_id?, agent_members?, agent_peers?, agent_tidy?} (null removes a default),
    apply: all (default: the existing lists follow) | new (only lists that come later), force?: also the lists that differ on
    purpose, dry_run?: only say what would happen}. -> {props, changed, lists: [{id, name, skipped: [{key, reason}]}]}"""
    from ..lists.lists import clean_folder
    c, b = db(), body()
    if g.user["kind"] == "agent":
        raise Denied(403)
    f = clean_folder(b.get("folder") or "")
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
    if not dry:
        if props:
            c.execute("INSERT INTO folder_props(owner_id,folder,props,updated_at) VALUES(?,?,?,?) ON CONFLICT(owner_id,folder) "
                      "DO UPDATE SET props=excluded.props, updated_at=excluded.updated_at", (me(), f, json.dumps(props), iso(now_utc())))
        else:
            c.execute("DELETE FROM folder_props WHERE owner_id=? AND folder=?", (me(), f))
    if apply == "all":
        keys = [k for k in new if new[k] is not None]
        if dry:  # what would happen: the new values against every list; rolled back below, nothing stays
            c.execute("INSERT INTO folder_props(owner_id,folder,props,updated_at) VALUES(?,?,?,?) ON CONFLICT(owner_id,folder) "
                      "DO UPDATE SET props=excluded.props", (me(), f, json.dumps(props), iso(now_utc())))
        for r in folder_lists(c, me(), f):
            sk, n = folder_apply(c, r["id"], keys=keys, force=b.get("force") is True, dry=dry)
            changed += n
            if sk or (list_own(c, r["id"]) and not b.get("force")):
                out.append({"id": r["id"], "name": r["name"], "skipped": sk,
                            "own": [k for k in list_own(c, r["id"]) if k in keys] if not b.get("force") else []})
    if dry:
        c.rollback()
        return jsonify(props=_norm(props), changed=changed, lists=out, dry_run=True)
    bump(c)
    c.commit()
    print("folder", repr(f), "of", g.user["username"], "props", json.dumps(props), "apply", apply, flush=True)
    return jsonify(props=_norm(props), changed=changed, lists=out)


@app.post("/api/lists/<int:lid>/folder-reset")
def list_folder_reset(lid):
    """{keys?: [...]}: the list takes its folder's defaults again (all keys, or these) -- "Back to the folder"."""
    c, b = db(), body()
    r = c.execute("SELECT owner_id FROM lists WHERE id=?", (lid,)).fetchone()
    if not r or r[0] != me():
        raise Denied(403, tr("Only the owner can change this list"))
    keys = b.get("keys")
    if keys is not None and (not isinstance(keys, list) or any(k not in FOLDER_PROPS for k in keys)):
        return err(tr("Invalid value: {0}", "keys"))
    own = [k for k in list_own(c, lid) if keys is not None and k not in keys]
    c.execute("UPDATE lists SET folder_own=? WHERE id=?", (json.dumps(own), lid))
    sk, n = folder_apply(c, lid, keys=keys)
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
    for k in keep:
        if k in eff:
            list_own_mark(c, lid, k)
    folder_apply(c, lid, keys=[k for k in FOLDER_PROPS if k not in keep])


def folder_member_created(c, uid, lid):
    """A list someone creates in a folder that is shared with them stays theirs and is shared with the folder's
    owner (list admin) and the folder's other people (their folder roles) at once -- the folder sits with them under the same
    name (member_folder_adopt). Returns the number of people it was shared with."""
    from ..lists.lists import _folder_member_add, folder_under
    from ..core.access import collab_all
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
        for p in c.execute("SELECT user_id, role FROM folder_people WHERE owner_id=? AND folder=? AND user_id!=?", (fp["owner_id"], fp["folder"], uid)).fetchall():
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
