"""2.48.0 (#1207): the file store ("Ablage") -- folders and files of a person (org_id NULL) and of an organisation.

Rules (the same as lists, see core/access.py):
- One tree per workspace. owner_id is the owner of the whole branch (copied from the parent); in an organisation tree the
  organisation's admins are owners as well. created_by = who added the node.
- A share (fs_shares) gives ONE person, group or agent 'view' or 'edit' on a node and everything below it, optionally until
  expires_at. org_access 'view' | 'edit' on a node opens it (and its subtree) to every person of its organisation.
- Organisation boundary: a node of organisation X exists only for members of X (agents: only agents of workspace X; a
  private agent never sees an organisation's node). Row-level security on fs_nodes is the second floor.
- Agents see only what is shared with exactly them, plus their own result folder (fs_nodes.agent_id = the agent: it may
  write there without a share). They are never owners and never share. Every access of an agent goes into fs_log.
- kind 'link' points to a task file (ref_kind 'att') or a project file ('list_file'): reading it needs the rights on the
  original as well (no move, no copy). 'page' (#1199) is reserved: a node need not have a stored file.
- Contents are versions (fs_versions, ATT_DIR/files/<node>/<uuid>), sealed with the organisation's key at rest (orgcrypt,
  like task files; 2.64.0 (#1864): a private file with its owner's account key). Deleting moves into the trash (deleted_at, the subtree with it);
  fs_purge removes for good and calls the hooks in fs_on_delete (other packages clean their own rows).

Functions of the interface (kalmido/docs and the import use them; signatures are fixed): fs_role, need_node, fs_put,
fs_new_version, fs_read, fs_folder, fs_visible_sql, fs_log_add, fs_on_delete.
"""
import hashlib
import mimetypes
import os
import uuid

from flask import g, has_request_context

from ..core.config import ATT_DIR, MAX_FILE_MB
from ..core.i18n import tr
from ..core.db import insert_id, iso, now_utc, write_lock, db
from ..core.access import Denied, acx_of, collab_all
from ..core.orgcrypt import oc_read_file, oc_write_file, oc_user_space
from ..core.pg import system_ctx  # 2.149.0 G (#2517): pulled up from functions

FS_DIR = "files"  # below ATT_DIR
FS_VERSIONS_KEEP = 20  # 2.152.0 D (#2173): older versions of a file go (rows; the stored file by the orphan clean-up) while ret_on("files")
KINDS = ("folder", "file", "link", "page")
ROLE_RANK = {None: 0, "view": 1, "edit": 2, "owner": 3}
CHAIN_MAX = 64  # a cycle guard for the walk to the root
DEPTH_MAX = 32  # folders below each other at most (well inside CHAIN_MAX, so every walk sees the whole chain)
READ_ACTIONS = ("list", "read", "download", "text", "meta")

# functions f(c, nid) called for every node removed for good (fs_purge), before its rows go
fs_on_delete = []
# 2.48.0 (#1111): functions f(c, uid, chain) -> bool: may person uid add a FILE of their own (owner = uid) to the folder
# chain[0] without edit there (the documents folder of an organisation: members file in, they see only their own)
fs_add_hooks = []


from ..core.db import now_iso as _now  # noqa: E402  2.149.0 G (#2517): was an own copy


def _uid():
    return g.user["id"] if has_request_context() and getattr(g, "user", None) is not None else None


def _best(a, b):
    return a if ROLE_RANK[a] >= ROLE_RANK[b] else b


def fs_chain(c, nid):
    """The node nid and its ancestors up to the root (rows, nid first); [] when it does not exist."""
    rows = c.execute("""WITH RECURSIVE up(id, lvl) AS (SELECT id, 0 FROM fs_nodes WHERE id=?
                           UNION ALL SELECT n.parent_id, up.lvl + 1 FROM fs_nodes n JOIN up ON n.id=up.id
                           WHERE n.parent_id IS NOT NULL AND up.lvl < ?)
                         SELECT n.*, up.lvl FROM up JOIN fs_nodes n ON n.id=up.id ORDER BY up.lvl""", (int(nid), CHAIN_MAX)).fetchall()
    return rows


def fs_deleted(chain):
    """Is the node of this chain in the trash (itself or an ancestor)?"""
    return any(r["deleted_at"] for r in chain)


def fs_trash_root(chain):
    """The node of the chain that was deleted (the trash entry), or None."""
    for r in reversed(chain):
        if r["deleted_at"]:
            return r
    return None


def _shares_role(c, ids, uid, agent):
    if not ids:
        return None
    q = ",".join("?" * len(ids))
    now = _now()
    if agent:
        sql = f"""SELECT role FROM fs_shares WHERE node_id IN ({q}) AND (agent_id=? OR user_id=?)
                  AND (expires_at IS NULL OR expires_at > ?)"""
        args = (*ids, uid, uid, now)
    else:
        if not collab_all():
            return None
        sql = f"""SELECT role FROM fs_shares WHERE node_id IN ({q}) AND (expires_at IS NULL OR expires_at > ?)
                  AND (user_id=? OR group_id IN (SELECT group_id FROM group_members WHERE user_id=?))"""
        args = (*ids, now, uid, uid)
    best = None
    for r in c.execute(sql, args):
        best = _best(r[0] if r[0] in ("view", "edit") else "view", best)
    return best


def fs_role(c, nid, uid=None, chain=None):
    """'owner' | 'edit' | 'view' | None: the role account uid (default: the signed-in one) has on node nid -- inherited
    from the folders above, shares with an expiry, the organisation boundary and the agent rules (module docstring).
    Ignores the trash (need_node decides about deleted nodes).
    2.148.1 D (#2488): a node filed with a hub mail (or below one) also needs the mail's rule (hub/hubmail.py hbm_can):
    the folder's owner or an organisation admin does not read mails the mail filing hides from them."""
    uid = uid or _uid()
    if not uid:
        return None
    chain = chain if chain is not None else fs_chain(c, nid)
    if not chain:
        return None
    mails = {r["hub_mail_id"] for r in chain if r["hub_mail_id"]}
    if mails:
        from ..hub.hubmail import hbm_node_ok
        if not all(hbm_node_ok(c, uid, m) for m in mails):
            return None
    return _fs_role(c, uid, chain)


def _fs_role(c, uid, chain):
    n = chain[0]
    org = n["org_id"]
    ctx = acx_of(c, uid)
    agent = ctx.role == "agent"
    if org:
        if agent and ctx.agent_org_id != org:
            return None
        if not agent and org not in ctx.org_ids:
            return None
    ids = [r["id"] for r in chain]
    if agent:
        if org and _fs_receipt_hidden(c, uid, org, n):
            return None  # 2.187.1 A (#2735): a share alone is not enough for an organisation's receipt (the area receipts)
        role = "edit" if any(r["agent_id"] == uid for r in chain) else None
        return _best(_shares_role(c, ids, uid, True), role)
    if org and _fs_receipt_hidden(c, uid, org, n):
        return None  # 2.187.0 C (#2476)
    from ..accounts.orgroles import org_limited
    if org and org_limited(c, uid, org):
        return _fs_limited_role(c, uid, org, chain, ids)  # 2.143.0 A (#2151)
    if n["owner_id"] == uid:
        return "owner"
    if org:
        from ..accounts.orgs import is_org_admin
        if is_org_admin(c, uid, org):
            return "owner"
    role = None
    for r in chain:
        if r["org_access"] in ("view", "edit") and org:
            role = _best(r["org_access"], role)
    return _best(_shares_role(c, ids, uid, False), role)


def _fs_receipt_hidden(c, uid, org, n):
    """2.187.0 C (#2476): a receipt of organisation org (a file with an rc_receipts row) for a person ruled by office groups:
    only with the area receipts (level "own": only the receipts they uploaded). Everybody else as before.
    2.187.1 A (#2735): agents are always ruled by office groups (ofr_rights; no group = no area = no receipt)."""
    from ..office.rights import LV, ofr_rights
    r = ofr_rights(c, uid, org)
    if r is None:
        return False
    lv = r["levels"].get("receipts", "none")
    mine = (n["created_by"] if "created_by" in n.keys() and n["created_by"] else n["owner_id"]) == uid  # review: the uploader, as the list
    if LV[lv] >= LV["view"] or (lv == "own" and mine):
        return False
    return c.execute("SELECT 1 FROM rc_receipts WHERE node_id=?", (n["id"],)).fetchone() is not None


def _fs_docs_root(c, org):
    from ..docs.store import doc_ws, root_id
    return root_id(c, doc_ws(org, None))


def _fs_limited_role(c, uid, org, chain, ids):
    """2.143.0 A (#2151): the role of a guest / read-only / accounting person on a node of organisation org. Read-only: what
    a member sees, at most 'view'. Guest: only their own nodes and shares. Accounting: like a guest, plus the organisation's
    documents folder to read (receipts) and their own uploads there (the upload itself is the documents area's,
    docs/web.py). Review: a guest / accounting person corrects and removes their own nodes ('edit'); read-only stays 'view'."""
    from ..accounts.orgroles import org_role_key
    rk = org_role_key(c, uid, org)
    role = ("view" if rk == "readonly" else "edit") if chain[0]["owner_id"] == uid else None
    if rk == "readonly":
        for r in chain:
            if r["org_access"] in ("view", "edit"):
                role = "view"
    elif rk == "accounting":
        root = _fs_docs_root(c, org)
        if root and any(r["id"] == root for r in chain):
            role = _best(role, "view")  # own receipts stay 'edit' (review)
    share = _shares_role(c, ids, uid, False)
    if rk == "readonly" and share:
        share = "view"
    return _best(share, role)


def need_node(c, nid, write=False, trash=False, manage=False):
    """The node row for the signed-in account: 404 when it may not see it (or it is in the trash and trash=False), 403
    when write / manage (shares, organisation access: owners only) needs more. Reading a link also needs the rights on
    its original (task / project file). The row carries the role as row["role"] (a dict)."""
    chain = fs_chain(c, nid) if nid else []
    role = fs_role(c, nid, chain=chain) if chain else None
    if not role:
        raise Denied(404)
    if fs_deleted(chain) and not trash:
        raise Denied(404)
    if (write and role == "view") or (manage and role != "owner"):
        raise Denied(403)
    n = dict(chain[0])
    n["role"] = role
    if n["kind"] == "link" and not write:
        fs_link_target(c, n)
    return n


def fs_link_target(c, n):
    """The original of a link node as {path, name, mime, size} -- raises Denied when the signed-in account may not read it
    (its rights are always the original's: task visibility incl. participants and health lists, project page access)."""
    if n["ref_kind"] == "att":
        from ..tasks.attachments import need_attachment
        a = need_attachment(c, n["ref_id"], False)
    elif n["ref_kind"] == "list_file":
        from ..lists.projects import need_list_file
        a = need_list_file(c, n["ref_id"], False)
    else:
        raise Denied(404)
    return {"path": a["path"], "name": a["name"], "mime": a["mime"], "size": a["size"]}


def fs_visible_sql(uid, c=None):
    """Subquery (no ? parameters, ids inlined) of the ids of every node account uid can see -- not in the trash, the
    organisation boundary applied. Use as `id IN <fs_visible_sql(uid)>`. c: the connection (default: the request's)."""
    return fs_visible_sql_c(c if c is not None else db(), uid)


def fs_visible_sql_c(c, uid):
    """fs_visible_sql with the connection (reads the account's organisations / groups once)."""
    uid = int(uid)
    ctx = acx_of(c, uid)
    agent = ctx.role == "agent"
    now = _now().replace("'", "")
    if agent:
        orgs = f"n.org_id IS NULL OR n.org_id = {int(ctx.agent_org_id)}" if ctx.agent_org_id else "n.org_id IS NULL"
        seed = (f"n.agent_id = {uid} OR n.id IN (SELECT node_id FROM fs_shares WHERE (agent_id = {uid} OR user_id = {uid}) "
                f"AND (expires_at IS NULL OR expires_at > '{now}'))")
    else:
        oids = ",".join(str(int(x)) for x in ctx.org_ids) or "0"
        orgs = f"n.org_id IS NULL OR n.org_id IN ({oids})"
        from ..accounts.orgs import is_org_admin
        from ..accounts.orgroles import org_role_key
        admin = [int(o) for o in ctx.org_ids if is_org_admin(c, uid, o)]
        seed = f"n.owner_id = {uid}"
        if admin:
            seed += f" OR n.org_id IN ({','.join(map(str, admin))})"
        # 2.143.0 A (#2151): "everyone in the organisation" folders only for member / admin / read-only; accounting: the
        # organisation's documents folder; guests: their own nodes and shares
        rks = {int(o): org_role_key(c, uid, o) for o in ctx.org_ids}
        full = ",".join(str(o) for o, rk in rks.items() if rk not in ("guest", "accounting")) or "0"
        seed += f" OR (n.org_access IN ('view', 'edit') AND n.org_id IN ({full}))"
        roots = [_fs_docs_root(c, o) for o, rk in rks.items() if rk == "accounting"]
        if any(roots):
            seed += f" OR n.id IN ({','.join(str(int(x)) for x in roots if x)})"
        if collab_all():
            seed += (f" OR n.id IN (SELECT node_id FROM fs_shares WHERE (user_id = {uid} OR group_id IN "
                     f"(SELECT group_id FROM group_members WHERE user_id = {uid})) AND (expires_at IS NULL OR expires_at > '{now}'))")
    return (f"(WITH RECURSIVE fv(id) AS (SELECT n.id FROM fs_nodes n WHERE ({seed}) AND ({orgs}) "
            f"UNION SELECT n.id FROM fs_nodes n JOIN fv ON n.parent_id = fv.id WHERE ({orgs})), "
            f"fd(id) AS (SELECT id FROM fs_nodes WHERE deleted_at IS NOT NULL "
            f"UNION SELECT n.id FROM fs_nodes n JOIN fd ON n.parent_id = fd.id) "
            f"SELECT id FROM fv WHERE id NOT IN (SELECT id FROM fd){_mail_hidden(c, uid)}{_receipts_hidden_sql(c, uid, ctx.org_ids)})")  # 2.187.1 A (#2735): agents too


def _receipts_hidden_sql(c, uid, org_ids):
    """2.187.0 (#2476, review): the clause that leaves out the receipts (files with an rc_receipts row) of the organisations
    where uid is ruled by office groups without the area receipts (level "own": all but the ones uid uploaded) -- the
    listings, searches and ZIPs follow the same rule as a single file (_fs_receipt_hidden). '' for everybody else."""
    from ..office.rights import LV, ofr_rights
    hide, own = [], []
    for o in org_ids:
        r = ofr_rights(c, uid, int(o))
        if r is None:
            continue
        lv = r["levels"].get("receipts", "none")
        if lv == "own":
            own.append(int(o))
        elif LV[lv] < LV["view"]:
            hide.append(int(o))
    parts = []
    if hide:
        parts.append(f"node_id IN (SELECT node_id FROM rc_receipts WHERE org_id IN ({','.join(map(str, hide))}))")
    if own:
        parts.append(f"node_id IN (SELECT r.node_id FROM rc_receipts r JOIN fs_nodes m ON m.id = r.node_id WHERE r.org_id IN "
                     f"({','.join(map(str, own))}) AND COALESCE(m.created_by, m.owner_id) <> {int(uid)})")
    if not parts:
        return ""
    return f" AND id NOT IN (SELECT node_id FROM rc_receipts WHERE {' OR '.join(parts)})"


def fs_mail_rows(c, uid, rows):
    """2.148.1 D (#2488): rows without the nodes filed with a hub mail uid may not read (a folder's listing).
    2.187.1 A (#2735): also without the organisation receipts uid may not read (_fs_receipt_hidden, people and agents)."""
    seen, out = {}, []
    for r in rows:
        org = r["org_id"] if "org_id" in r.keys() else None  # a caller with fewer columns (public links) as before
        if org and _fs_receipt_hidden(c, uid, org, r):
            continue
        m = r["hub_mail_id"]
        if m:
            if m not in seen:
                from ..hub.hubmail import hbm_node_ok
                seen[m] = hbm_node_ok(c, uid, m)
            if not seen[m]:
                continue
        out.append(r)
    return out


def _mail_hidden(c, uid):
    """2.148.1 D (#2488): the clause that leaves out nodes filed with a hub mail uid may not read ('' when there are none)."""
    if not c.execute("SELECT 1 FROM fs_nodes WHERE hub_mail_id IS NOT NULL LIMIT 1").fetchone():
        return ""
    from ..hub.hubmail import hbm_node_mail_ids
    ok = sorted(hbm_node_mail_ids(c, uid))
    keep = f" AND hub_mail_id NOT IN ({','.join(str(int(x)) for x in ok)})" if ok else ""
    return f" AND id NOT IN (SELECT id FROM fs_nodes WHERE hub_mail_id IS NOT NULL{keep})"


def fs_visible_ids(c, uid=None):
    """The set of node ids account uid (default: signed in) can see (not in the trash)."""
    uid = uid or _uid()
    return {r[0] for r in c.execute(f"SELECT id FROM fs_nodes WHERE id IN {fs_visible_sql_c(c, uid)}")} if uid else set()


def safe_fs_name(name):
    from ..tasks.attachments import safe_name
    return safe_name(name)[:150]


def _is_agent(c, uid):
    return bool(uid) and acx_of(c, uid).role == "agent"


def _free_name(c, parent_id, owner_id, org_id, name, skip=None):
    """name, or "name (2).ext" ... when a node of that name already sits in the same folder (trash excluded).
    2.190.0 D (#2496): a node owned by another than the folder's owner (a member's document in the organisation's documents
    folder) only avoids the names of its owner's own nodes there (no hint at names it cannot see)."""
    own = None
    if parent_id and owner_id:
        p = c.execute("SELECT owner_id FROM fs_nodes WHERE id=?", (parent_id,)).fetchone()
        own = owner_id if p and p["owner_id"] != owner_id else None

    def taken(nm):
        if parent_id and own:
            r = c.execute("SELECT id FROM fs_nodes WHERE parent_id=? AND owner_id=? AND lower(name)=lower(?) AND deleted_at IS NULL",
                          (parent_id, own, nm))
        elif parent_id:
            r = c.execute("SELECT id FROM fs_nodes WHERE parent_id=? AND lower(name)=lower(?) AND deleted_at IS NULL", (parent_id, nm))
        elif org_id:
            r = c.execute("SELECT id FROM fs_nodes WHERE parent_id IS NULL AND org_id=? AND lower(name)=lower(?) AND deleted_at IS NULL",
                          (org_id, nm))
        else:
            r = c.execute("""SELECT id FROM fs_nodes WHERE parent_id IS NULL AND org_id IS NULL AND owner_id=? AND lower(name)=lower(?)
                             AND deleted_at IS NULL""", (owner_id, nm))
        return any(x[0] != skip for x in r.fetchall())
    if not taken(name):
        return name
    stem, dot, ext = name.rpartition(".") if "." in name.strip(".") else (name, "", "")
    for i in range(2, 1000):
        nm = f"{stem[:140]} ({i}){dot}{ext}"
        if not taken(nm):
            return nm
    return f"{stem[:120]} {uuid.uuid4().hex[:6]}{dot}{ext}"


def _place(c, uid, parent_id, org_id, write_role=True, add_file=False):
    """(owner_id, org_id) of a new node below parent_id (None: the workspace root of org_id / uid's own space); checks the
    right to add there (raises Denied). add_file: a file -- fs_add_hooks may let uid add it as its owner."""
    if parent_id:
        chain = fs_chain(c, parent_id)
        role = fs_role(c, parent_id, uid, chain=chain) if chain else None
        if (add_file and role in (None, "view") and chain and not fs_deleted(chain) and len(chain) < DEPTH_MAX
                and any(f(c, uid, chain) for f in fs_add_hooks)):
            return uid, chain[0]["org_id"]
        if not role or fs_deleted(chain):
            raise Denied(404)
        if chain[0]["kind"] != "folder":
            raise Denied(409, tr("Not a folder"))
        if write_role and role == "view":
            raise Denied(403)
        if len(chain) >= DEPTH_MAX:
            raise Denied(409, tr("Folders can be nested at most {0} levels deep", DEPTH_MAX))
        return chain[0]["owner_id"], chain[0]["org_id"]
    ctx = acx_of(c, uid)
    if ctx.role == "agent":
        raise Denied(403, tr("Agents add files only in folders shared with them or in their own folder"))
    if org_id and int(org_id) not in ctx.org_ids:
        raise Denied(404)
    if org_id:  # 2.143.0 A (#2151, review): the organisation's top level only for members / admins (receipts: docs/web.py)
        from ..accounts.orgroles import need_org_write
        need_org_write(c, uid, int(org_id))
    return uid, (int(org_id) if org_id else None)


def _check_data(name, data):
    if not data:
        raise ValueError(tr("{0}: the file is empty and was not uploaded", name))
    if len(data) > MAX_FILE_MB * 1024 * 1024:
        raise ValueError(tr("{0}: larger than {1} MB", name, MAX_FILE_MB))


def fs_space(org_id, owner_id):
    """2.64.0 (#1864): the key space of a node's files: its organisation, else its owner's account."""
    return int(org_id) if org_id else oc_user_space(owner_id)


def _store_version(c, nid, org_id, data, mime, uid):
    """Write data as the next version of node nid (sealed for an organisation) and point the node at it. Returns the no.
    2.64.0 (#1864): org_id = the space id (fs_space: the organisation, else the owner's account key)."""
    from ..notify.alerts import aa_count, aa_oserr
    d = os.path.join(ATT_DIR, FS_DIR, str(int(nid)))
    rel = os.path.join(FS_DIR, str(int(nid)), uuid.uuid4().hex[:16])
    try:
        os.makedirs(d, exist_ok=True)
        oc_write_file(c, org_id or 0, os.path.join(ATT_DIR, rel), bytes(data), fresh=True)
    except OSError as e:
        aa_count("storage", "files", aa_oserr(e))
        raise
    write_lock(c, f"fs_version:{int(nid)}")  # two uploads at once: the numbers stay unique
    no = (c.execute("SELECT COALESCE(MAX(no), 0) FROM fs_versions WHERE node_id=?", (nid,)).fetchone()[0] or 0) + 1
    ts = _now()
    c.execute("INSERT INTO fs_versions(node_id,no,path,size,mime,sha256,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",
              (nid, no, rel, len(data), mime, hashlib.sha256(data).hexdigest(), uid, ts))
    c.execute("UPDATE fs_nodes SET cur_version=?, size=?, mime=?, updated_at=? WHERE id=?", (no, len(data), mime, ts, nid))
    if no > FS_VERSIONS_KEEP:
        from ..admin.dataretention import orf_prune_versions
        orf_prune_versions(c, nid)  # 2.152.0 D (#2173): rows only, in this transaction; the files follow with the orphan clean-up
    return no


def _mime_of(name, mime):
    if mime and mime != "application/octet-stream":
        return mime[:120]
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def fs_put(c, uid, parent_id, name, data, mime=None, org_id=None, agent_id=None, up=None):
    """A new file `name` with the bytes `data` below folder parent_id (None: the root of the workspace org_id / uid's own
    space; the parent decides the workspace). uid needs 'edit' on the parent. A name that is taken gets " (2)"; an agent's
    executable ending gets ".txt" (#380). Checks size and quota. Returns the node id (the caller commits). Raises Denied
    (rights), ValueError (empty / too large; upsafe.UploadRefused: a virus find) or hosting.QuotaExceeded. up (a dict)
    gets the info of the upload checks (2.61.0: scan state, capture date of a photo)."""
    from ..admin.hosting import quota_guard
    from ..tasks.attachments import unexec_name
    name = safe_fs_name(name)
    agent = _is_agent(c, uid)
    if agent:
        if unexec_name(name) != name:
            name, mime = unexec_name(name), "text/plain"
    data = bytes(data or b"")
    _check_data(name, data)
    owner, org = _place(c, uid, parent_id, org_id, add_file=True)
    from .upsafe import up_check, up_after_store  # 2.61.0 (#1818 #1819 #1820): scan, metadata, text recognition
    data, mime, info = up_check(c, name, data, _mime_of(name, mime), uid, org, "fs")
    quota_guard(c, uid, len(data))
    ts = _now()
    nid = insert_id(c, """INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,agent_id,mime,size,created_by,created_at,updated_at)
                          VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (parent_id or None, "file", _free_name(c, parent_id, owner, org, name), owner, org, agent_id,
                     mime, len(data), uid, ts, ts))  # 2.61.0 (#1818): the type of the upload checks (octet-stream from the content stays)
    _store_version(c, nid, fs_space(org, owner), data, mime, uid)  # 2.64.0 (#1864): sealed with the space's key, also private
    up_after_store(c, "fs", nid, org, info)
    if up is not None:
        up.update(info)
    from ..integrations.webhooks import who_note
    who_note("file.created", "file", nid)  # 2.115.0 A (#2061)
    return nid


def fs_new_version(c, nid, data, mime=None):
    """Store data as the newest version of file nid (the older ones stay). The caller checked the write right. Returns the
    new version number."""
    from ..admin.hosting import quota_guard
    n = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    if not n or n["kind"] != "file":
        raise Denied(404)
    data = bytes(data or b"")
    _check_data(n["name"], data)
    uid = _uid()
    if uid and _is_agent(c, uid):  # #380: an agent never writes an executable / script file people may run
        from ..tasks.attachments import unexec_name
        if unexec_name(n["name"]) != n["name"]:
            raise Denied(403, tr("Agents do not write new versions of executable files"))
        mime = "text/plain"
    from .upsafe import up_check, up_after_store  # 2.61.0 (#1818 #1819 #1820)
    data, mime, info = up_check(c, n["name"], data, _mime_of(n["name"], mime or n["mime"]), uid, n["org_id"], "fs")
    if uid:
        quota_guard(c, uid, len(data))
    no = _store_version(c, nid, fs_space(n["org_id"], n["owner_id"]), data, mime, uid)  # 2.64.0 (#1864)
    up_after_store(c, "fs", nid, n["org_id"], info)
    return no


def fs_version_row(c, nid, version=None):
    if version:
        return c.execute("SELECT * FROM fs_versions WHERE node_id=? AND no=?", (nid, int(version))).fetchone()
    return c.execute("SELECT v.* FROM fs_versions v JOIN fs_nodes n ON n.id=v.node_id AND v.no=n.cur_version WHERE n.id=?",
                     (nid,)).fetchone()


def fs_read(c, nid, version=None):
    """The plain bytes of file nid (version: that number, default the current one; a link: its original). No rights check
    (need_node first). Raises Denied(404) when there is no content."""
    n = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    if not n:
        raise Denied(404)
    if n["kind"] == "link":
        t = fs_link_target(c, dict(n))
        return oc_read_file(c, os.path.join(ATT_DIR, t["path"]))
    v = fs_version_row(c, nid, version)
    if not v:
        raise Denied(404)
    from .scan import sc_guard
    sc_guard(c, "fs", nid, v["no"])  # 2.61.0 (#1818): a version found infected later is locked
    return oc_read_file(c, os.path.join(ATT_DIR, v["path"]))


def fs_folder(c, uid, org_id, names, agent_id=None):
    """Find or create the folder path `names` (e.g. ["Dokumente", "Eingang"]) at the root of workspace org_id (None: uid's
    own space) and return the id of the last folder. Existing folders are only reused when uid can see them (a folder of
    that name uid cannot see is left alone, a new one is created). agent_id: the LAST folder is that agent's result folder
    (found by agent_id, not by name, so renaming it keeps it; the agent may write there)."""
    names = [safe_fs_name(x) for x in (names or []) if str(x or "").strip()]
    if not names:
        raise ValueError(tr("Name missing"))
    parent, org = None, (int(org_id) if org_id else None)
    owner = uid
    for i, nm in enumerate(names):
        last = i == len(names) - 1
        found = None
        if last and agent_id:
            r = c.execute("""SELECT id FROM fs_nodes WHERE agent_id=? AND kind='folder' AND deleted_at IS NULL AND
                             (parent_id=? OR (? IS NULL AND parent_id IS NULL)) AND (org_id=? OR (? IS NULL AND org_id IS NULL))
                             ORDER BY id LIMIT 1""", (agent_id, parent, parent, org, org)).fetchone()
            found = r[0] if r else None
        else:
            if parent:
                rows = c.execute("SELECT id FROM fs_nodes WHERE parent_id=? AND kind='folder' AND lower(name)=lower(?) AND deleted_at IS NULL "
                                 "ORDER BY id", (parent, nm)).fetchall()
            elif org:
                rows = c.execute("SELECT id FROM fs_nodes WHERE parent_id IS NULL AND org_id=? AND kind='folder' AND lower(name)=lower(?) "
                                 "AND deleted_at IS NULL AND agent_id IS NULL ORDER BY id", (org, nm)).fetchall()
            else:
                rows = c.execute("SELECT id FROM fs_nodes WHERE parent_id IS NULL AND org_id IS NULL AND owner_id=? AND kind='folder' "
                                 "AND lower(name)=lower(?) AND deleted_at IS NULL AND agent_id IS NULL ORDER BY id", (owner, nm)).fetchall()
            for r in rows:
                if ROLE_RANK[fs_role(c, r[0], uid)] >= ROLE_RANK["edit"]:
                    found = r[0]
                    break
        if found:
            parent = found
            continue
        if parent or not _is_agent(c, uid):
            own, org2 = _place(c, uid, parent, org)
        else:  # an agent's folder at the top: only in its own workspace, owned by the agent's owner (never the agent)
            ctx = acx_of(c, uid)
            if (org or None) != (ctx.agent_org_id or None):
                raise Denied(404)
            from ..core.pg import system_ctx
            with system_ctx(c):  # the agent's settings row (structure)
                a = c.execute("SELECT owner_id FROM agents WHERE user_id=?", (uid,)).fetchone()
            if not a or not a[0]:
                raise Denied(403)
            own, org2 = a[0], org
        ts = _now()
        parent = insert_id(c, """INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,agent_id,created_by,created_at,updated_at)
                                 VALUES(?,?,?,?,?,?,?,?,?)""",
                           (parent, "folder", _free_name(c, parent, own, org2, nm), own, org2,
                            agent_id if last else None, uid, ts, ts))
    return parent


def fs_log_add(c, nid, action, detail=""):
    """Note an access of the signed-in account in the node's history. Agents: every access; people: only changes (reads of
    people are not logged -- the history answers "what did the agent do with my file")."""
    uid = _uid()
    agent = bool(uid) and _is_agent(c, uid)
    if not agent and action in READ_ACTIONS:
        return
    c.execute("INSERT INTO fs_log(node_id,user_id,agent,action,detail,at) VALUES(?,?,?,?,?,?)",
              (int(nid), uid, 1 if agent else 0, str(action)[:40], str(detail or "")[:300], _now()))


def fs_height(c, nid):
    """How many levels lie below node nid (0: none)."""
    r = c.execute("""WITH RECURSIVE dn(id, lvl) AS (SELECT id, 0 FROM fs_nodes WHERE id=?
                       UNION ALL SELECT n.id, dn.lvl + 1 FROM fs_nodes n JOIN dn ON n.parent_id=dn.id WHERE dn.lvl < ?)
                     SELECT COALESCE(MAX(lvl), 0) FROM dn""", (int(nid), CHAIN_MAX)).fetchone()
    return int(r[0] or 0)


def fs_subtree(c, nid):
    """Ids of node nid and everything below it (deleted ones included)."""
    return [r[0] for r in c.execute("""WITH RECURSIVE dn(id, lvl) AS (SELECT id, 0 FROM fs_nodes WHERE id=?
                                         UNION ALL SELECT n.id, dn.lvl + 1 FROM fs_nodes n JOIN dn ON n.parent_id=dn.id
                                         WHERE dn.lvl < ?) SELECT id FROM dn""", (int(nid), CHAIN_MAX))]


def fs_purge(c, nid):
    """Remove node nid and its subtree for good: the hooks of fs_on_delete, the stored versions, the rows. Returns
    (ids, paths); the caller commits and only then calls fs_purge_files(ids, paths) -- 2.86.0 (N25): a failed commit
    keeps the rows and their files."""
    ids = fs_subtree(c, nid)
    paths = []
    for i in ids:
        for f in fs_on_delete:
            f(c, i)
        paths += [r[0] for r in c.execute("SELECT path FROM fs_versions WHERE node_id=?", (i,))]
    c.execute("DELETE FROM fs_nodes WHERE id=?", (int(nid),))  # ON DELETE CASCADE: children, versions, shares, log
    return ids, paths


def fs_purge_files(ids, paths):
    """The stored files of an fs_purge, after the commit."""
    for p in paths:
        try:
            os.remove(os.path.join(ATT_DIR, p))
        except OSError:
            pass
    for i in ids:
        try:
            os.rmdir(os.path.join(ATT_DIR, FS_DIR, str(i)))
        except OSError:
            pass


def fs_bytes_of(c, uids):
    """Bytes of the file-store versions uploaded by the accounts uids (the storage quota, admin/hosting.py)."""
    if not uids:
        return 0
    q = ",".join("?" * len(uids))
    return int(c.execute(f"SELECT COALESCE(SUM(size),0) FROM fs_versions WHERE created_by IN ({q})", list(uids)).fetchone()[0])


def fs_user_purge(c, uid):
    """A person is deleted (accounts/users.py user_purge): the branches they own in an organisation's tree go to an admin of
    that organisation (else another member) and stay; their own tree is removed (the hooks of fs_on_delete run). Returns
    the stored files to unlink after the commit (paths relative to ATT_DIR)."""
    paths = []
    with system_ctx(c):  # the person's nodes in every organisation (an instance admin deletes accounts of organisations they are not in)
        for (oid,) in c.execute("SELECT DISTINCT org_id FROM fs_nodes WHERE owner_id=? AND org_id IS NOT NULL", (uid,)).fetchall():
            heir = c.execute("""SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND m.user_id!=?
                                AND COALESCE(u.kind, '')!='agent' ORDER BY (m.role='admin') DESC, m.user_id LIMIT 1""", (oid, uid)).fetchone()
            if not heir and c.execute("SELECT 1 FROM orgs WHERE id=? AND retired_at IS NOT NULL", (oid,)).fetchone():
                from ..accounts.orgretain import odl_custodian  # 2.152.0 A (#2167): a retired organisation keeps its files (an instance admin)
                keeper = odl_custodian(c, uid)
                heir = (keeper,) if keeper else None
            if heir:
                c.execute("UPDATE fs_nodes SET owner_id=? WHERE owner_id=? AND org_id=?", (heir[0], uid, oid))
        roots = [r[0] for r in c.execute("SELECT id FROM fs_nodes WHERE owner_id=? AND (parent_id IS NULL OR parent_id NOT IN "
                                         "(SELECT id FROM fs_nodes WHERE owner_id=?))", (uid, uid))]
        for nid in roots:
            for i in fs_subtree(c, nid):
                for f in fs_on_delete:
                    f(c, i)
                paths += [r[0] for r in c.execute("SELECT path FROM fs_versions WHERE node_id=?", (i,))]
            c.execute("DELETE FROM fs_nodes WHERE id=?", (nid,))
    return paths


def fs_org_live(c, oid):
    """Folders and files of organisation oid outside the trash (an organisation is deleted only without them). 2.186.0 A
    (#2599): what lies in a deleted folder is in the trash too (only the folder carries deleted_at), as the trash shows it."""
    with system_ctx(c):  # the instance admin deletes an organisation they need not be in
        return c.execute("""WITH RECURSIVE live(id) AS (
                              SELECT id FROM fs_nodes WHERE org_id=? AND deleted_at IS NULL
                                AND (parent_id IS NULL OR parent_id NOT IN (SELECT id FROM fs_nodes WHERE org_id=?))
                              UNION ALL
                              SELECT n.id FROM fs_nodes n JOIN live l ON n.parent_id=l.id WHERE n.org_id=? AND n.deleted_at IS NULL)
                            SELECT COUNT(*) FROM live""", (int(oid), int(oid), int(oid))).fetchone()[0]


def fs_org_purge(c, oid):
    """The trash of organisation oid before the organisation is deleted: hooks, rows; returns the files to unlink."""
    paths = []
    with system_ctx(c):  # see fs_org_live
        for (nid,) in c.execute("SELECT id FROM fs_nodes WHERE org_id=? AND parent_id IS NULL", (int(oid),)).fetchall():
            for i in fs_subtree(c, nid):
                for f in fs_on_delete:
                    f(c, i)
                paths += [r[0] for r in c.execute("SELECT path FROM fs_versions WHERE node_id=?", (i,))]
            c.execute("DELETE FROM fs_nodes WHERE id=?", (nid,))
    return paths
