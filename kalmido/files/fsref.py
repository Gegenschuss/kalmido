"""2.199.0 A (#2742): reference nodes -- an object of another area (an office document, a sheet ...) filed in a folder of the
file store. The folder system is the file store's (fs_nodes / fs_shares, files/store.py); a reference node is a row with
kind 'ref', ref_kind = the registered kind, ref_id = the object's id, name = the object's title (the area keeps it current).

Rules:
- An object has at most ONE reference node (unique index fs_nodes_ref): it lies in the tree of the workspace the object
  belongs to (a private object only in its owner's private tree, an organisation's object only in that organisation's
  tree). fs_ref_place enforces it; a node whose object moved to another workspace gives nothing (fs_ref_role).
- Unlike a link (kind 'link', the original's rights only), the folder GIVES access: the role on the object is the higher one
  of the area's own role (base_role) and the role on the reference node through its folders (fs_role: shares, owners,
  expiry, the organisation boundary; 'owner' counts as 'edit'). Organisation access ("every member", fs_nodes.org_access)
  opens NO object (else every member read invoices / project tables without their office group or project): only the
  explicit shares of the chain (person, group, agent) count -- 2.199.0 F (#2742, review): in an organisation's tree not the
  ownership of the branch (who made the folder), nor the accounting role's documents folder; in a private tree its owner.
  Agents only through shares with exactly them. A node in the trash (itself or a folder above) gives
  nothing. A folder share never gives a special right of an area (office: release / send, payments, lock, export stay with
  the office groups, office/rights.py): callers use fs_ref_role only to read / edit the DOCUMENT.
- hidden: what an area keeps from a person even with a folder share (the receipts lock of the office groups applies to agents
  and people alike, 2.187.1): those objects keep only their base role, and their nodes are left out of the listings.
- Deleting a folder moves it with its content into the trash; a node whose protect hook names a reason (a locked invoice, a
  receipt inside its retention period) moves one level up first (files/web.py, kept: [{id, name, reason}]). on_trash tells
  the area a node went into the trash / came back with its folder (e.g. a sheet into the sheets' own trash). Removing a
  reference node for good (fs_purge) never deletes the object -- deleting the object stays its area's business (then
  fs_ref_drop).

Interface (signatures fixed; B / C and 2.200-2.202 use them):
  fs_ref_register(kind, *, label, open_url, base_role, space, protect=None, hidden=None, on_trash=None, title=None, content=None)
      kind      str, a new ref_kind ([a-z][a-z0-9_]*, not 'att' / 'list_file'), at most 20 characters
      label     the kind's name for people, marked with N_() (translated when sent), e.g. N_("Invoice")
      open_url  f(ref_id) -> the app route that opens the object (for go(), without '#'), e.g. "office/doc/12"
      base_role f(c, uid, ref_id) -> None | 'view' | 'edit': uid's role from the area alone (office groups, sheet_shares ...)
      space     f(c, ref_id) -> (org_id | None, owner_id) of the object, None = it does not exist (any more)
      protect   f(c, ref_id) -> a reason (text for people, translated) or None: the object may not go into the trash
      hidden    f(c, uid) -> an SQL subquery in parentheses (ids inlined, no ? parameters) of the ref_ids a folder must not open to
                uid, or '' (none)
      on_trash  f(c, uid, ref_id, restore) -> None: the node went into the trash (restore False) / came back (True)
      title     f(c, ref_id) -> the object's title: the node's name when fs_ref_place gets none (else the label)
      content   f(c, uid, ref_id) -> (bytes, file name, mime) | None: the object as a file (its PDF ...) for the content
                routes of the file store (web and /api/v1, + text); called only with fs_ref_role >= 'view'
  fs_ref_role(c, uid, ref_kind, ref_id) -> None | 'view' | 'edit'
  fs_ref_node(c, ref_kind, ref_id) -> the fs_nodes row of the object (also in the trash) or None
  fs_ref_content(c, uid, n) -> (bytes, name, mime) of reference node n (a row); Denied(404) without a role, 409 without content
  fs_ref_place(c, uid, ref_kind, ref_id, parent_id, name=None) -> node id | None: files the object into folder parent_id
      (creates the node or moves / restores it); parent_id None removes the node (the object is in no folder). uid needs
      'edit' on the object from its area (base_role, fs_ref_may_file -- 2.199.0 F: a folder share is not enough), 'edit' on
      the target folder and -- for a node that lies in a folder -- 'edit' there. Raises Denied. The caller commits.
      The node's name is always the area's title (title hook); name only counts for a kind without one.
  fs_ref_may_file(c, uid, ref_kind, ref_id) -> bool   'edit' from the area: file / move / trash the object's node
  fs_ref_need_move(c, uid, n)                moving node n into another folder: Denied(403) unless fs_ref_may_file on every
                                             object filed in its subtree
  fs_ref_need_share(c, uid, n, role)         sharing node n with role: Denied(403) unless uid has that role (fs_ref_role) on
                                             every object filed in its subtree
  fs_ref_rename(c, ref_kind, ref_id, name)   the object's new title on its node (no rights check)
  fs_ref_drop(c, ref_kind, ref_id)           the object was deleted for good: its node goes (no rights check)
  fs_protect(c, n) -> reason | None          a node (row) that may not go into the trash: fs_protect_hooks + protect
  fs_protect_hook(fn)                        adds fn(c, n) -> reason | None, asked for every node BELOW a folder going into
                                             the trash (files too, e.g. receipts inside their retention period; not for
                                             the node chosen itself)
"""
import re

from ..accounts.orgroles import org_role_key
from ..core.access import Denied, acx_of
from ..core.db import insert_id
from ..core.i18n import tr
from ..core.pg import system_ctx
from .store import (DEPTH_MAX, ROLE_RANK, _free_name, _now, _shares_role, fs_chain, fs_deleted, fs_log_add, fs_role, safe_fs_name)

FSR = {}  # ref_kind -> the registered hooks
FSR_RESERVED = ("att", "list_file")  # the kinds of link nodes (files/store.py fs_link_target)
fs_protect_hooks = []


def fs_ref_register(kind, *, label, open_url, base_role, space, protect=None, hidden=None, on_trash=None, title=None, content=None):
    """Register a kind of reference node (module docstring). Registering the same kind again replaces it (a module reload)."""
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,19}", kind or "") or kind in FSR_RESERVED:
        raise ValueError(f"fs_ref_register: invalid kind {kind!r}")
    FSR[kind] = {"label": label, "open_url": open_url, "base_role": base_role, "space": space, "protect": protect,
                 "hidden": hidden, "on_trash": on_trash, "title": title, "content": content}


def fs_protect_hook(fn):
    """Add fn(c, n) -> reason | None to the checks of fs_protect (once)."""
    if fn not in fs_protect_hooks:
        fs_protect_hooks.append(fn)
    return fn


def _reg(kind):
    r = FSR.get(kind or "")
    if r is None:
        raise Denied(404)
    return r


def _role_of(v):
    return v if v in ("view", "edit") else None


def fs_ref_node(c, ref_kind, ref_id):
    """The node of the object (also in the trash) or None."""
    return c.execute("SELECT * FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id=?", (ref_kind, int(ref_id))).fetchone()


def _same_space(sp, n):
    """Does node n lie in the object's workspace (sp = (org_id, owner_id))?"""
    org, owner = sp
    if org:
        return (n["org_id"] or None) == int(org)
    return not n["org_id"] and n["owner_id"] == owner


def _hidden(c, uid, reg, ref_id):
    if not reg["hidden"]:
        return False
    sql = reg["hidden"](c, uid) or ""
    if not sql:
        return False
    return c.execute(f"SELECT 1 WHERE ? IN {sql}", (int(ref_id),)).fetchone() is not None


def fs_ref_node_role(c, uid, n, chain=None):
    """The role a reference node row n gives uid through its folders (None | 'view' | 'edit'), without the base role.
    2.199.0 F (#2742, review): only the explicit shares of the chain count (person, group, agent; a read-only member at most
    'view') -- not the ownership of an organisation's branch (who made the folder), not organisation access, not the
    accounting role's documents folder, not an agent's result folder. In a private tree its owner (the object is theirs:
    _same_space) has 'edit'."""
    reg = FSR.get(n["ref_kind"] or "")
    if reg is None:
        return None
    chain = chain if chain is not None else fs_chain(c, n["id"])
    if not chain or fs_deleted(chain):
        return None
    sp = reg["space"](c, n["ref_id"])
    if not sp or not _same_space(sp, n):
        return None
    if _hidden(c, uid, reg, n["ref_id"]):
        return None
    if not fs_role(c, n["id"], uid, chain=chain):
        return None  # the organisation boundary, hidden receipts / mails (fs_role)
    org = n["org_id"]
    if not org and n["owner_id"] == uid:
        return "edit"
    agent = acx_of(c, uid).role == "agent"
    r = _role_of(_shares_role(c, [x["id"] for x in chain], uid, agent))
    if r and org and not agent:
        if org_role_key(c, uid, org) == "readonly":
            r = "view"
    return r


def fs_ref_role(c, uid, ref_kind, ref_id):
    """None | 'view' | 'edit': the higher role of the area's own (base_role) and the one the folders give (module docstring)."""
    reg = FSR.get(ref_kind or "")
    if reg is None or not uid:
        return None
    base = _role_of(reg["base_role"](c, uid, int(ref_id)))
    if base == "edit":
        return base
    n = fs_ref_node(c, ref_kind, ref_id)
    if not n:
        return base
    r = fs_ref_node_role(c, uid, n)
    return r if ROLE_RANK[r] > ROLE_RANK[base] else base


def _folder_ok(c, uid, pid):
    """The chain of folder pid, checked: uid may add there ('edit'), not in the trash, not too deep."""
    chain = fs_chain(c, pid)
    role = fs_role(c, pid, uid, chain=chain) if chain else None
    if not role or fs_deleted(chain):
        raise Denied(404)
    if chain[0]["kind"] != "folder":
        raise Denied(409, tr("Not a folder"))
    if role == "view":
        raise Denied(403)
    if len(chain) >= DEPTH_MAX:
        raise Denied(409, tr("Folders can be nested at most {0} levels deep", DEPTH_MAX))
    return chain


def fs_ref_may_file(c, uid, ref_kind, ref_id):
    """2.199.0 F (#2742, review G4): may uid file / move / take out / put into the trash the node of this object? Only with
    'edit' from its area (base_role): a folder share gives the document, never the say where it lies (else who edits only
    through a share hangs it into a folder of their own and shares that one)."""
    reg = FSR.get(ref_kind or "")
    return bool(reg and uid) and _role_of(reg["base_role"](c, uid, int(ref_id))) == "edit"


def fs_ref_place(c, uid, ref_kind, ref_id, parent_id, name=None):
    """File the object into folder parent_id (None: into no folder) -- module docstring. Returns the node id or None."""
    reg = _reg(ref_kind)
    ref_id = int(ref_id)
    if not fs_ref_role(c, uid, ref_kind, ref_id):
        raise Denied(404)
    if not fs_ref_may_file(c, uid, ref_kind, ref_id):
        raise Denied(403)  # 2.199.0 F (#2742, review G4): filing needs edit from the area, a folder share is not enough
    sp = reg["space"](c, ref_id)
    if not sp:
        raise Denied(404)
    n = fs_ref_node(c, ref_kind, ref_id)
    was_trash = False
    if n is None:
        with system_ctx(c):  # 2.199.0 F (#2742, review): a node row-level security hides (another tree): a clear 409, not the unique index
            hid = c.execute("SELECT 1 FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id=?", (ref_kind, ref_id)).fetchone()
        if hid:
            raise Denied(409, tr("This document already lies in a folder you cannot see"))
    else:
        chain = fs_chain(c, n["id"])
        was_trash = fs_deleted(chain)
        if not fs_deleted(chain) and _same_space(sp, n) and ROLE_RANK[fs_role(c, n["id"], uid, chain=chain)] < ROLE_RANK["edit"]:
            raise Denied(403)  # taking it out of a folder takes the folder's shares away: edit there too
    if not parent_id:
        if n is not None:
            c.execute("DELETE FROM fs_nodes WHERE id=?", (n["id"],))
        return None
    pchain = _folder_ok(c, uid, int(parent_id))
    p = pchain[0]
    if not _same_space(sp, p):
        raise Denied(409, tr("Files can only be moved within the same space"))  # the organisation boundary
    if reg["title"]:  # 2.199.0 F (#2742, review): the name is the area's (its title), never one of the caller's
        name = reg["title"](c, ref_id) if n is None else None
    nm = safe_fs_name(str(name or (n["name"] if n is not None else "") or tr(reg["label"])).strip() or tr(reg["label"]))
    ts = _now()
    if n is None:
        nid = insert_id(c, """INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,ref_kind,ref_id,created_by,created_at,updated_at)
                              VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (p["id"], "ref", _free_name(c, p["id"], p["owner_id"], p["org_id"], nm), p["owner_id"], p["org_id"],
                         ref_kind, ref_id, uid, ts, ts))
        fs_log_add(c, nid, "create")
        return nid
    if n["parent_id"] == p["id"] and not n["deleted_at"] and (name is None or nm == n["name"]) and _same_space(sp, n):
        return n["id"]
    c.execute("""UPDATE fs_nodes SET parent_id=?, owner_id=?, org_id=?, name=?, sort_no=NULL, deleted_at=NULL, deleted_by=NULL,
                 updated_at=? WHERE id=?""",
              (p["id"], p["owner_id"], p["org_id"], _free_name(c, p["id"], p["owner_id"], p["org_id"], nm, skip=n["id"]), ts, n["id"]))
    fs_log_add(c, n["id"], "move", str(p["id"]))
    if was_trash:
        fs_ref_trashed(c, uid, n, True)  # 2.199.0 F (#2742, review): back out of the trash -- the area's too (e.g. a sheet)
    return n["id"]


def fs_ref_content(c, uid, n):
    """(bytes, name, mime) of reference node n (a row) for uid: its area's content hook, with fs_ref_role >= 'view'."""
    reg = FSR.get(n["ref_kind"] or "")
    if reg is None or not fs_ref_role(c, uid, n["ref_kind"], n["ref_id"]):
        raise Denied(404)
    out = reg["content"](c, uid, n["ref_id"]) if reg["content"] else None
    if not out:
        raise Denied(409, tr("Not a file"))
    data, name, mime = out
    return bytes(data), safe_fs_name(name or n["name"]), mime or "application/octet-stream"


def fs_ref_rename(c, ref_kind, ref_id, name):
    """The object's new title on its node (a taken name in the folder gets " (2)")."""
    n = fs_ref_node(c, ref_kind, ref_id)
    nm = safe_fs_name(str(name or "").strip())
    if n is None or not nm or nm == n["name"]:
        return
    c.execute("UPDATE fs_nodes SET name=?, updated_at=? WHERE id=?",
              (_free_name(c, n["parent_id"], n["owner_id"], n["org_id"], nm, skip=n["id"]), _now(), n["id"]))


def fs_ref_drop(c, ref_kind, ref_id):
    """The object was deleted for good: its node goes (its shares with it)."""
    c.execute("DELETE FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id=?", (ref_kind, int(ref_id)))


def fs_protect(c, n, hooks=True):
    """A reason why node n (a row) may not go into the trash, or None. hooks=False: only a reference node's protect (the
    node chosen itself: a single receipt may go into the trash, only removing it for good waits for its period)."""
    for f in (fs_protect_hooks if hooks else ()):
        why = f(c, n)
        if why:
            return why
    if n["kind"] == "ref":
        reg = FSR.get(n["ref_kind"] or "")
        if reg and reg["protect"]:
            return reg["protect"](c, n["ref_id"]) or None
    return None


def fs_ref_trashed(c, uid, n, restore):
    """Tell the area of reference node n (a row) that it went into the trash / came back (its on_trash hook)."""
    reg = FSR.get(n["ref_kind"] or "") if n["kind"] == "ref" else None
    if reg and reg["on_trash"]:
        reg["on_trash"](c, uid, n["ref_id"], bool(restore))


def _live_below(c, nid):
    """The rows below node nid that are not in the trash themselves (a deleted subfolder keeps its own content)."""
    out, todo = [], [int(nid)]
    while todo and len(out) < 100000:
        q = ",".join("?" * len(todo))
        rows = c.execute(f"SELECT * FROM fs_nodes WHERE parent_id IN ({q}) AND deleted_at IS NULL", todo).fetchall()
        out += rows
        todo = [r["id"] for r in rows if r["kind"] == "folder"]
    return out


def fs_ref_subtree(c, n):
    """2.199.0 F (#2742, review): the reference node rows in node n's subtree (n itself when it is one; not what is in the
    trash below it)."""
    if n["kind"] == "ref":
        return [n]
    if n["kind"] != "folder":
        return []
    return [r for r in _live_below(c, n["id"]) if r["kind"] == "ref"]


def fs_ref_need_move(c, uid, n):
    """2.199.0 F (#2742, review): moving node n (a row) into another folder changes who reaches the objects filed in it (the
    shares above): uid needs 'edit' on every one of them (fs_ref_role), else Denied(403). Sorting among the same siblings
    does not ask."""
    for r in fs_ref_subtree(c, n):
        if not fs_ref_may_file(c, uid, r["ref_kind"], r["ref_id"]):
            raise Denied(403, tr("The folder holds documents you may not edit") if n["kind"] == "folder" else None)


def fs_ref_need_share(c, uid, n, role):
    """2.199.0 F (#2742, review): sharing node n (a row) with role passes the objects filed below it on: uid needs at least
    that role on every one of them through the area (base_role) or an explicit share of their own (fs_ref_role) -- owning
    the folder is not enough. Else Denied(403)."""
    for r in fs_ref_subtree(c, n):
        if ROLE_RANK[fs_ref_role(c, uid, r["ref_kind"], r["ref_id"])] < ROLE_RANK[role]:
            raise Denied(403, tr("The folder holds documents you may not share with this role"))


def fs_trash_prepare(c, uid, n):
    """Before node n (a row) goes into the trash: the protected nodes below a folder (fs_protect; a protected subfolder with
    all it holds) move one level up -- next to the folder, the top of its tree for a top folder. Returns (kept [{id, name,
    reason}], the reference nodes going into the trash with it). A protected reference node n itself raises Denied(409,
    reason); the hooks of fs_protect_hook are asked only for the nodes below n.
    2.199.0 F (#2742, review): a reference node whose object uid may not edit (fs_ref_role) is protected too ("no rights to
    the document"; n itself: Denied(403)); a kept node uid cannot see (a hidden receipt / mail, an object without a role)
    comes back as {reason} only, without id and name."""
    if n["kind"] == "ref" and not fs_ref_may_file(c, uid, n["ref_kind"], n["ref_id"]):
        raise Denied(403)
    why = fs_protect(c, n, hooks=False)
    if why:
        raise Denied(409, why)
    if n["kind"] != "folder":
        return [], ([n] if n["kind"] == "ref" else [])
    kept, refs, todo = [], [], [n["id"]]
    ts = _now()
    while todo and len(refs) + len(kept) < 100000:
        q = ",".join("?" * len(todo))
        nxt = []
        for r in c.execute(f"SELECT * FROM fs_nodes WHERE parent_id IN ({q}) AND deleted_at IS NULL ORDER BY id", todo).fetchall():
            role = fs_ref_role(c, uid, r["ref_kind"], r["ref_id"]) if r["kind"] == "ref" else None
            why = fs_protect(c, r) or (tr("No rights to the document") if r["kind"] == "ref" and not (
                role and fs_ref_may_file(c, uid, r["ref_kind"], r["ref_id"])) else None)
            if not why:
                if r["kind"] == "ref":
                    refs.append(r)
                elif r["kind"] == "folder":
                    nxt.append(r["id"])
                continue
            seen = (role is not None) if r["kind"] == "ref" else bool(fs_role(c, r["id"], uid))  # before it moves (the chain)
            nm = _free_name(c, n["parent_id"], r["owner_id"], r["org_id"], r["name"], skip=r["id"])
            c.execute("UPDATE fs_nodes SET parent_id=?, name=?, sort_no=NULL, updated_at=? WHERE id=?", (n["parent_id"], nm, ts, r["id"]))
            fs_log_add(c, r["id"], "move", str(n["parent_id"] or ""))
            kept.append({"id": r["id"], "name": nm, "reason": why} if seen else {"reason": why})
        todo = nxt
    return kept, refs


def fs_trash_restored(c, uid, n):
    """After node n (a row) came back out of the trash: on_trash(restore=True) for it / the reference nodes below it."""
    rows = [n] if n["kind"] == "ref" else [r for r in _live_below(c, n["id"]) if r["kind"] == "ref"]
    for r in rows:
        fs_ref_trashed(c, uid, r, True)


def fs_ref_json(n):
    """The extra keys of a reference node for the client / the API: ref_kind, ref_id, open (route), label; unknown kind:
    no_access (an area switched off)."""
    reg = FSR.get(n["ref_kind"] or "")
    if reg is None:
        return {"ref_kind": n["ref_kind"], "ref_id": None, "no_access": True}
    return {"ref_kind": n["ref_kind"], "ref_id": n["ref_id"], "open": reg["open_url"](n["ref_id"]), "label": tr(reg["label"])}


def fs_ref_rows(c, uid, rows):
    """rows (a listing) without the reference nodes uid may not reach (fs_ref_role None: an unknown kind, no role from the
    area nor from an explicit share of the folders -- organisation access opens none --, a hidden object, an object that
    moved to another workspace): their titles stay unseen too."""
    if not any(r["kind"] == "ref" for r in rows):
        return rows
    return [r for r in rows if r["kind"] != "ref" or fs_ref_role(c, uid, r["ref_kind"], r["ref_id"])]


def fs_ref_hidden_sql(c, uid):
    """The clause for fs_visible_sql: leaves out the reference nodes of objects a folder must not open to uid ('' none)."""
    parts = []
    for kind, reg in FSR.items():
        sql = reg["hidden"](c, uid) if reg["hidden"] else ""
        if sql:
            parts.append(f"(ref_kind = '{kind}' AND ref_id IN {sql})")
    if not parts:
        return ""
    return f" AND id NOT IN (SELECT id FROM fs_nodes WHERE kind = 'ref' AND ({' OR '.join(parts)}))"


def _probe_register():
    """Test containers only (KALMIDO_TEST=1 and KALMIDO_TEST_FSREF=1, tests/p2199_a_fsref_test.py): kind 'probe' = a file
    of the store as the object. Its base role = the role on that file; a name starting with "keep" is protected, one
    starting with "hide" is hidden from folder shares; on_trash notes probe_trash / probe_back in the file's history."""
    import os
    if os.environ.get("KALMIDO_TEST") != "1" or os.environ.get("KALMIDO_TEST_FSREF") != "1":
        return

    def row(c, rid):
        return c.execute("SELECT * FROM fs_nodes WHERE id=? AND kind='file'", (int(rid),)).fetchone()

    def base(c, uid, rid):
        r = row(c, rid)
        if not r:
            return None
        x = fs_role(c, r["id"], uid)
        return "edit" if x == "owner" else x

    def space(c, rid):
        r = row(c, rid)
        return (r["org_id"], r["owner_id"]) if r else None

    def protect(c, rid):
        r = row(c, rid)
        return "kept for the test" if r and r["name"].startswith("keep") else None

    def trashed(c, uid, rid, restore):
        fs_log_add(c, rid, "probe_back" if restore else "probe_trash")

    fs_ref_register("probe", label="Test object", open_url=lambda rid: f"ablage/{int(rid)}", base_role=base, space=space,
                    protect=protect, hidden=lambda c, uid: "(SELECT id FROM fs_nodes WHERE kind = 'file' AND name ILIKE 'hide%')",
                    on_trash=trashed, title=lambda c, rid: (row(c, rid) or {"name": ""})["name"],
                    content=lambda c, uid, rid: (f"probe {int(rid)}".encode(), "probe.txt", "text/plain") if row(c, rid) else None)


_probe_register()
