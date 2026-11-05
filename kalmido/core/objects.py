"""2.558.0 (#4709): the shared core, stage 1 -- ONE register of object kinds and ONE role function for every new area
(docs/dev/kern.md "So baut man einen neuen Bereich"). A new area (meetings, social media planner, team projects ...) needs no
share table, no check function and no save path of its own: obj_register + obj_need + obj_write (core/writes.py) = done.

It is built on what exists (no second register): obj_register registers the kind with the reference nodes of the file store
too (files/fsref.py fs_ref_register), so an object can lie in folders, folder shares open it, and its own shares are rows of
fs_shares on its reference node (person / group / agent, role view | edit, expiry). The organisation roles come from
accounts/orgroles.py, the organisation floor from core/access.py acx_org_ok, the agents' data lock from core/dlock.py.
Stage 1 rebuilds no old table and changes no old area; stages 2 ff. (#4711 office, #4712 calendars + contacts) move areas
onto it through the hooks (base_role, space, cap, hidden, undo_scope).

The table of a kind (the area's own, e.g. a migrations.d fragment) has at least: id, org_id (NULL = private), owner_id,
rev, created_at, created_by, updated_at, updated_by, deleted_at, deleted_by and the columns of its fields (a title column
unless a title hook is given). Private objects belong to owner_id (REFERENCES users ON DELETE CASCADE: they go with the
account), an organisation's to the organisation (owner_id = who made it; obj_revoke_person hands it to the heir).

Roles (rank): None < 'view' < 'edit' < 'manage'. 'manage' = share, put into the trash, restore, delete for good (only from
the area's own role: a share gives at most 'edit'). obj_role(c, uid, kind, id) is THE role, in this order:
  1. the object exists and its workspace (space) is known; the organisation floor (acx_org_ok: members only, an agent of
     another workspace never)
  2. agents and API tokens: what the area hides (hidden) stays hidden, also from the area's own role (as fs_ref_role);
     an agent's data lock (dl_area of the kind locked) and an API token limited to lists (a kind with a list_id column:
     only objects of those lists; without one: nothing) give nothing
  3. the area's own role (base_role; default below) and the role its reference node gives through shares (fs_ref_node_role:
     person, group, agent, expiry, the folders above, read-only members at most 'view', the area's cap) -- the higher one
  4. an object in the trash: only 'manage' (to restore / delete it); obj_need refuses it unless trash=True
Default base role (no hook): agents nothing (only explicit shares); a private object: its owner 'manage'; an
organisation's object: its admins 'manage', its owner 'manage' as a member ('view' when read-only / guest / accounting
now), every other full member org_access ('edit' default | 'view' | None), read-only members at most 'view', guests /
accounting nothing (only personal shares).

Interface (signatures fixed; stages 2 / 3 and the first areas #1958 #1957 #4675 use them):
  obj_register(kind, table, *, label, fields, open_url=None, space=None, title=None, base_role=None, visible=None, cap=None,
               hidden=None, org_access="edit", area="other", scopes=("read", "tasks:write"), dl_area=None, feat=None,
               protect=None, on_trash=None, content=None, undo_scope=None, public=None, routes=True, trash_role="manage")
      fields     {name: cleaner} -- what obj_create / obj_write may set; cleaner(c, value, row) -> the clean value (raise
                 BadInput); helpers f_text / f_int / f_bool / f_choice / f_date below
      space      f(c, id) -> (org_id | None, owner_id) | None (default: the row's columns)
      base_role  f(c, uid, id) -> None | 'view' | 'edit' | 'manage' -- the area's own role (office groups, calendar members ...)
      visible    f(c, uid) -> an SQL subquery of the ids the base role opens (required with a base_role hook: obj_visible_sql)
      cap        f(c, uid, id) -> the most a share gives uid (fsref cap); hidden f(c, uid) -> SQL of ids a share never opens
      area       the change counter of /api/version this kind bumps (core/db.py LV_AREA_KEYS)
      scopes     (read, write) scope of API tokens for the agent routes (core/objweb.py)
      undo_scope f(id, org_id) -> [(table, where, args, several rows?)] for undo of more than the main row (office/undo.py)
      public     f(c, uid, row, role) -> dict: the object as the client / the API see it (default: obj_public)
      routes     the generic routes /api/obj/<kind>/... and /api/v1/agent/objects/<kind>/... (core/objweb.py) serve the kind
  obj_role(c, uid, kind, id, row=None) -> None | 'view' | 'edit' | 'manage'
  obj_need(c, uid, kind, id, need="view" | "write" | "manage", trash=False) -> (row, role); Denied 404 / 403
  obj_visible_sql(c, uid, kind) -> "(SELECT id ...)" the ids uid sees (not in the trash), ids inlined, no ? parameters
  obj_rows(c, uid, kind, where="", args=(), trash=False) -> [(row, role)] the visible objects (trash=True: the trash uid manages)
  obj_share(c, uid, kind, id, key, target, role="view", expires_at=None) -> share id   (key user_id | group_id | agent_id)
  obj_unshare(c, uid, kind, id, sid) -> revoked id  (the share goes into obj_revoked: obj_share_restore puts it back)
  obj_share_restore(c, uid, kind, id, rid) -> share id
  obj_shares(c, uid, kind, id) -> {shares, inherited, revoked}
  obj_revoke_person(c, uid, org, reason, heir=None, role=None) -> {table: rows} -- reason 'leave' (uid leaves org: its shares
      and its agents' on the organisation's nodes, its team chat memberships of the organisation's rooms; its core objects
      to heir), 'role' (uid's role in org is now role: guest / accounting leave the open channels they joined themselves),
      'retire' (org retires, uid None: every share on its nodes, every membership of its rooms), 'delete' (account uid goes:
      its undo steps, its name in the history). What goes lands in obj_revoked (30 days, OBJ_REVOKED_DAYS).
The caller commits."""
import json
import re
from datetime import timedelta

from flask import g, has_request_context, request

from ..accounts.orgroles import org_role_key, FULL_READ
from .access import Denied, acx_of, acx_org_ok, collab_all
from .db import insert_id, iso, now_utc
from .errors import BadInput
from .i18n import tr
from .pg import system_ctx

OBJ = {}  # kind -> the registered hooks
OBJ_RANK = {None: 0, "view": 1, "edit": 2, "manage": 3}
OBJ_ROLES = ("view", "edit", "manage")
OBJ_REVOKED_DAYS = 30  # rows taken away stay restorable this long (obj_revoked)
OBJ_SHARE_MAX = 200
OBJ_REASONS = ("leave", "role", "retire", "delete", "unshare")
OBJ_COLS = ("id", "org_id", "owner_id", "rev", "created_at", "created_by", "updated_at", "updated_by", "deleted_at", "deleted_by")
_NAME = re.compile(r"[a-z][a-z0-9_]{0,19}")
_TABLE = re.compile(r"[a-z][a-z0-9_]{0,62}")


# ---------------------------------------------------------------- field cleaners (for fields={...})
def f_text(mx=200, required=False, line=True):
    """A text up to mx characters (line: no line breaks); required: not empty."""
    def clean(c, v, row=None):
        if v is None and not required:
            return ""
        if not isinstance(v, str):
            raise BadInput(tr("Invalid data"))
        v = v.strip()
        if line:
            v = " ".join(v.split())
        if required and not v:
            raise BadInput(tr("Expected {0}", "text"))
        if len(v) > mx:
            raise BadInput(tr("At most {0} characters", mx))
        return v
    return clean


def f_int(lo=None, hi=None, null=True):
    def clean(c, v, row=None):
        if v is None and null:
            return None
        if isinstance(v, bool) or not isinstance(v, int) or (lo is not None and v < lo) or (hi is not None and v > hi):
            raise BadInput(tr("Invalid data"))
        return v
    return clean


def f_bool():
    def clean(c, v, row=None):
        if v is None:
            return 0
        if not isinstance(v, bool):
            raise BadInput(tr("Invalid data"))
        return 1 if v else 0
    return clean


def f_choice(values, default=None):
    """One of values; None = default (or the first value)."""
    def clean(c, v, row=None):
        if v is None:
            return default if default is not None else values[0]
        if v not in values:
            raise BadInput(tr("Invalid data"))
        return v
    return clean


def f_date(null=True):
    def clean(c, v, row=None):
        if v in (None, "") and null:
            return None
        if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            raise BadInput(tr("Invalid data"))
        return v
    return clean


# ---------------------------------------------------------------- the register
def obj_register(kind, table, *, label, fields, open_url=None, space=None, title=None, base_role=None, visible=None, cap=None,
                 hidden=None, org_access="edit", area="other", scopes=("read", "tasks:write"), dl_area=None, feat=None,
                 protect=None, on_trash=None, content=None, undo_scope=None, public=None, routes=True, trash_role="manage"):
    """Register a kind of core object (module docstring). Registering the same kind again replaces it (a module reload)."""
    from ..files.fsref import fs_ref_register
    from .db import LV_AREA_KEYS
    if not _NAME.fullmatch(kind or "") or not _TABLE.fullmatch(table or ""):
        raise ValueError(f"obj_register: invalid kind / table {kind!r} {table!r}")
    if base_role is not None and visible is None:
        raise ValueError(f"obj_register {kind}: a base_role hook needs its visible hook (obj_visible_sql)")
    if org_access not in ("edit", "view", None) or trash_role not in ("edit", "manage") or area not in LV_AREA_KEYS:
        raise ValueError(f"obj_register {kind}: invalid org_access / trash_role / area")
    if not isinstance(fields, dict) or any(k in OBJ_COLS or not _TABLE.fullmatch(k) for k in fields):
        raise ValueError(f"obj_register {kind}: fields must be own columns")
    reg = {"kind": kind, "table": table, "label": label, "fields": dict(fields), "space": space, "title": title, "base_role": base_role,
           "visible": visible, "cap": cap, "hidden": hidden, "org_access": org_access, "area": area, "scopes": tuple(scopes),
           "dl_area": dl_area, "feat": feat, "undo_scope": undo_scope, "public": public, "routes": bool(routes), "trash_role": trash_role,
           "open_url": open_url or (lambda rid: f"obj/{kind}/{int(rid)}")}
    OBJ[kind] = reg

    def fsr_base(c, uid, rid):  # the folders ask for the area's role: the core's, without the shares, 'manage' counts as 'edit'
        row = obj_row(c, kind, rid)
        if not row or row["deleted_at"] or not _gate(c, uid, reg, row):
            return None
        r = _base(c, uid, reg, row)
        return "edit" if r == "manage" else r

    def fsr_on_trash(c, uid, rid, restore):
        """Review F7: an object in the trash has its reference node in the file store's trash too (writes.py obj_trash), so the
        folders need no hidden clause for it. Should the node come back on its own while the object is still in the trash: who
        manages the object restores it with it, anyone else leaves both in the trash ("stays")."""
        row = obj_row(c, kind, rid)
        if restore and row is not None and row["deleted_at"]:
            if uid and obj_role(c, uid, kind, rid, row=row) == "manage":
                from .writes import obj_restore
                obj_restore(c, uid, kind, rid)
            else:
                c.execute("UPDATE fs_nodes SET deleted_at=?, deleted_by=? WHERE kind='ref' AND ref_kind=? AND ref_id=?",
                          (row["deleted_at"], row["deleted_by"], kind, int(rid)))
                return "stays"
        return on_trash(c, uid, rid, restore) if on_trash else None

    fs_ref_register(kind, label=label, open_url=reg["open_url"], base_role=fsr_base, space=lambda c, rid: obj_space(c, kind, rid),
                    protect=protect, hidden=hidden, on_trash=fsr_on_trash, title=lambda c, rid: obj_title(c, kind, rid),
                    content=content, cap=cap)
    return reg


def obj_reg(kind):
    """The registered hooks of kind; Denied(404) for an unknown one."""
    r = OBJ.get(kind or "")
    if r is None:
        raise Denied(404)
    return r


def obj_row(c, kind, rid):
    """The object's row (also in the trash) or None."""
    reg = OBJ.get(kind or "")
    if reg is None:
        return None
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        return None
    return c.execute(f"SELECT * FROM {reg['table']} WHERE id=?", (rid,)).fetchone()


def obj_space(c, kind, rid):
    """(org_id | None, owner_id) of the object, None when it does not exist."""
    reg = OBJ.get(kind or "")
    if reg is None:
        return None
    if reg["space"]:
        return reg["space"](c, int(rid))
    r = obj_row(c, kind, rid)
    return (r["org_id"] or None, r["owner_id"]) if r else None


def obj_title(c, kind, rid):
    reg = OBJ.get(kind or "")
    if reg is None:
        return ""
    if reg["title"]:
        return reg["title"](c, int(rid)) or ""
    r = obj_row(c, kind, rid)
    return (r["title"] if r is not None and "title" in r.keys() else "") or ""


# ---------------------------------------------------------------- the role
def _api_way(c, uid):
    from ..files.fsref import _api_way as fsr_api_way
    return fsr_api_way(c, uid)


def _req_token_lists(uid):
    """The list limit of the request's own token (None: none, or not uid's request)."""
    if not has_request_context() or g.get("auth_via") != "token" or not g.get("user") or g.user["id"] != uid:
        return None
    from .access import token_lists
    return token_lists()


def _gate(c, uid, reg, row):
    """Steps 1 + 2 of obj_role: the organisation floor, what the area hides from agents / tokens, the data lock, the token's
    list limit. False = no role at all."""
    sp = reg["space"](c, row["id"]) if reg["space"] else (row["org_id"] or None, row["owner_id"])
    if not sp:
        return False
    org = sp[0]
    if not acx_org_ok(c, uid, org):
        return False
    ctx = acx_of(c, uid)
    agent = ctx.role == "agent"
    if agent and org and ctx.agent_org_id != org:
        return False  # an agent of another workspace (a private agent never reaches an organisation's object)
    if reg["hidden"] and _api_way(c, uid):
        sql = reg["hidden"](c, uid) or ""
        if sql and c.execute(f"SELECT 1 WHERE ? IN {sql}", (int(row["id"]),)).fetchone():
            return False
    if agent and reg["dl_area"]:
        from .dlock import dl_of
        d = dl_of(c, uid)
        if d and d["areas"].get(reg["dl_area"], True):
            return False
    lim = _req_token_lists(uid)
    if lim is not None:
        if "list_id" not in row.keys() or row["list_id"] not in lim:
            return False
    return True


def _base(c, uid, reg, row):
    """Step 3a: the area's own role (its hook, or the default of the module docstring)."""
    if reg["base_role"]:
        r = reg["base_role"](c, uid, int(row["id"]))
        return r if r in OBJ_ROLES else None
    if acx_of(c, uid).role == "agent":
        return None
    org, owner = row["org_id"] or None, row["owner_id"]
    if not org:
        return "manage" if owner == uid else None
    rk = org_role_key(c, uid, org)
    if rk is None:
        return None
    if rk == "admin":
        return "manage"
    if owner == uid:
        return "manage" if rk == "member" else "view"
    if rk not in FULL_READ or not reg["org_access"]:
        return None
    return "view" if rk == "readonly" else reg["org_access"]


def _share_role(c, uid, reg, row, pre=None):
    """Step 3b: the role the object's reference node gives through shares (fsref: explicit shares of its chain only).
    pre: the nodes, chains and share reads of a whole listing (obj_rows, review F3)."""
    from ..files.fsref import fs_ref_node, fs_ref_node_role
    if pre is not None:
        n = pre["nodes"].get(int(row["id"]))
        if not n:
            return None
        sp = None if reg["space"] else (row["org_id"] or None, row["owner_id"])
        r = fs_ref_node_role(c, uid, n, chain=pre["chains"].get(n["id"]) or [], pre=pre["fs"], sp=sp,
                             hidden=int(row["id"]) in pre["hidden"] if pre["hidden"] is not None else None)
        return r if r in ("view", "edit") else None
    n = fs_ref_node(c, reg["kind"], row["id"])
    if not n:
        return None
    r = fs_ref_node_role(c, uid, n)
    return r if r in ("view", "edit") else None


def _cache():
    if not has_request_context() or request.method not in ("GET", "HEAD"):
        return None  # a write request asks again every time (a share / a role may change in it)
    return g.setdefault("obj_roles", {})


def obj_forget():
    """Drops the request's cached roles (after a share or a membership changed)."""
    if has_request_context():
        g.pop("obj_roles", None)


def obj_role(c, uid, kind, rid, row=None, pre=None):
    """None | 'view' | 'edit' | 'manage' -- THE role of account uid on the object (module docstring, steps 1-4). pre: obj_rows'
    reads of the whole listing (_rows_pre)."""
    reg = OBJ.get(kind or "")
    if reg is None or not uid:
        return None
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        return None
    cache = _cache()
    key = (int(uid), kind, rid)
    if cache is not None and key in cache:
        return cache[key]
    row = row if row is not None else obj_row(c, kind, rid)
    out = None
    if row is not None and _gate(c, uid, reg, row):
        base = _base(c, uid, reg, row)
        # review F3: a share gives at most 'edit' -- the chain is read only when the area's own role is below it
        share = _share_role(c, uid, reg, row, pre=pre) if OBJ_RANK[base] < OBJ_RANK["edit"] else None
        out = base if OBJ_RANK[base] >= OBJ_RANK[share] else share
        if row["deleted_at"] and out != "manage":
            out = None  # step 4: the trash only for who may restore it
    if cache is not None:
        cache[key] = out
    return out


def obj_need(c, uid, kind, rid, need="view", trash=False):
    """(row, role) of the object for uid, or Denied: 404 without a role (or in the trash unless trash=True; outside the
    trash with trash=True too), 403 without the role need ('view' | 'write' | 'manage')."""
    reg = obj_reg(kind)
    if reg["feat"]:
        from .access import need_feat
        need_feat(reg["feat"])
    row = obj_row(c, kind, rid)
    role = obj_role(c, uid, kind, rid, row=row) if row is not None else None
    if not role or bool(row["deleted_at"]) != bool(trash):
        raise Denied(404)
    want = {"view": "view", "write": "edit", "edit": "edit", "manage": "manage"}.get(need)
    if want is None:
        raise ValueError(f"obj_need: unknown need {need!r}")
    if OBJ_RANK[role] < OBJ_RANK[want]:
        org = row["org_id"] or None
        if org and org_role_key(c, uid, org) == "readonly":
            from ..accounts.orgroles import RO_MSG
            raise Denied(403, tr(RO_MSG))
        raise Denied(403)
    return row, role


# ---------------------------------------------------------------- what uid sees (SQL)
def _ids(xs):
    return ",".join(str(int(x)) for x in xs) or "0"


def _share_sql(c, uid, reg, agent):
    """The ids whose reference node lies below (or is) a node shared explicitly with uid, in the object's own workspace,
    reachable in the file store (fs_visible_sql: the boundary, the trash of the folders, locks) and not hidden."""
    from ..files.store import fs_visible_sql_c
    from .db import now_iso
    now = now_iso().replace("'", "")
    u = int(uid)
    if agent:
        who = f"(agent_id = {u} OR user_id = {u})"
    elif collab_all():
        who = f"(user_id = {u} OR group_id IN (SELECT group_id FROM group_members WHERE user_id = {u}))"
    else:
        return ""
    kind, t = reg["kind"], reg["table"]
    hid = ""
    sql = reg["hidden"](c, uid) if reg["hidden"] else ""
    if sql:
        hid = f" AND n.ref_id NOT IN {sql}"
    return (f"(WITH RECURSIVE os(id) AS (SELECT node_id FROM fs_shares WHERE {who} AND (expires_at IS NULL OR expires_at > '{now}') "
            f"UNION SELECT n.id FROM fs_nodes n JOIN os ON n.parent_id = os.id) "
            f"SELECT n.ref_id FROM fs_nodes n JOIN {t} o ON o.id = n.ref_id WHERE n.kind = 'ref' AND n.ref_kind = '{kind}' "
            f"AND n.id IN (SELECT id FROM os) AND n.id IN {fs_visible_sql_c(c, uid)} "
            f"AND (CASE WHEN o.org_id IS NULL THEN n.org_id IS NULL AND n.owner_id = o.owner_id ELSE n.org_id = o.org_id END){hid})")


def obj_visible_sql(c, uid, kind):
    """A subquery (ids inlined, no ? parameters) of the ids of kind account uid sees, not in the trash: the area's own role
    (visible hook, or the default base role) or a share; the organisation floor, hidden, the data lock and a token's list limit
    applied. Use as `id IN <obj_visible_sql(c, uid, kind)>`. Review F6: a kind with a cap hook gets ValueError -- a share
    may open less there than the SQL names, so its area lists with obj_rows (which asks obj_role per row)."""
    if obj_reg(kind)["cap"]:
        raise ValueError(f"obj_visible_sql {kind}: the kind has a cap hook, list it with obj_rows")
    return _visible_sql(c, uid, kind)


def _visible_sql(c, uid, kind):
    """obj_visible_sql without the cap guard (obj_rows: the SQL is its candidate set, obj_role decides each row)."""
    reg = obj_reg(kind)
    t = reg["table"]
    none = f"(SELECT id FROM {t} WHERE FALSE)"
    if not uid:
        return none
    uid = int(uid)
    ctx = acx_of(c, uid)
    agent = ctx.role == "agent"
    if agent and reg["dl_area"]:
        from .dlock import dl_of
        d = dl_of(c, uid)
        if d and d["areas"].get(reg["dl_area"], True):
            return none
    parts = []
    if reg["visible"]:
        own = reg["visible"](c, uid) or ""
        if own:
            parts.append(f"o.id IN {own}")
    elif not agent:
        roles = {int(o): org_role_key(c, uid, o) for o in ctx.org_ids}
        parts.append(f"(o.org_id IS NULL AND o.owner_id = {uid})")
        admin = [o for o, rk in roles.items() if rk == "admin"]
        if admin:
            parts.append(f"o.org_id IN ({_ids(admin)})")
        mine = [o for o, rk in roles.items() if rk and rk != "admin"]
        if mine:
            parts.append(f"(o.org_id IN ({_ids(mine)}) AND o.owner_id = {uid})")
        full = [o for o, rk in roles.items() if rk in FULL_READ and rk != "admin"]
        if full and reg["org_access"]:
            parts.append(f"o.org_id IN ({_ids(full)})")
    sh = _share_sql(c, uid, reg, agent)
    if sh:
        parts.append(f"o.id IN {sh}")
    if not parts:
        return none
    if agent:
        floor = f"(o.org_id IS NULL OR o.org_id = {int(ctx.agent_org_id)})" if ctx.agent_org_id else "o.org_id IS NULL"
    else:
        floor = f"(o.org_id IS NULL OR o.org_id IN ({_ids(ctx.org_ids)}))"
    extra = ""
    if reg["hidden"] and _api_way(c, uid):
        sql = reg["hidden"](c, uid) or ""
        if sql:
            extra += f" AND o.id NOT IN {sql}"
    lim = _req_token_lists(uid)
    if lim is not None:
        from .pg import table_columns
        if "list_id" not in table_columns(c, t):
            return none
        extra += f" AND o.list_id IN ({_ids(sorted(lim))})"
    return f"(SELECT o.id FROM {t} o WHERE o.deleted_at IS NULL AND {floor} AND ({' OR '.join(parts)}){extra})"


def obj_rows(c, uid, kind, where="", args=(), trash=False, limit=500):
    """[(row, role)] of the objects of kind uid sees (where: an extra condition on the table, alias o), newest change first.
    trash=True: the objects in the trash uid may restore. Every row is checked with obj_role (the SQL is the candidate set)."""
    reg = obj_reg(kind)
    t = reg["table"]
    if trash:  # the candidates: own private ones and those of uid's organisations (obj_role decides)
        ctx = acx_of(c, uid)
        org_ids = [ctx.agent_org_id] if ctx.role == "agent" and ctx.agent_org_id else ([] if ctx.role == "agent" else ctx.org_ids)
        sql = (f"SELECT o.* FROM {t} o WHERE o.deleted_at IS NOT NULL AND ((o.org_id IS NULL AND o.owner_id = {int(uid)}) "
               f"OR o.org_id IN ({_ids(org_ids)}))")
    else:
        sql = f"SELECT o.* FROM {t} o WHERE o.id IN {_visible_sql(c, uid, kind)}"
    if where:
        sql += f" AND ({where})"
    sql += f" ORDER BY o.updated_at DESC, o.id DESC LIMIT {int(limit)}"
    out = []
    rows = c.execute(sql, tuple(args)).fetchall()
    pre = _rows_pre(c, uid, kind, [r["id"] for r in rows])
    for r in rows:
        role = obj_role(c, uid, kind, r["id"], row=r, pre=pre)
        if role and (not trash or role == "manage"):
            out.append((r, role))
    return out


def _rows_pre(c, uid, kind, ids):
    """Review F3: for a listing, the reference nodes of all its objects, their chains and the share reads at once (files/store.py
    fs_chains + _FsPre, the pattern of fs_roles_many) -- obj_role keeps its rules, only the reads are shared."""
    from ..files.store import _FsPre, fs_chains
    nodes = {}
    ids = sorted({int(i) for i in ids})
    for k in range(0, len(ids), 500):
        part = ids[k:k + 500]
        for n in c.execute(f"SELECT * FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id IN ({_ids(part)})", (kind,)).fetchall():
            nodes[int(n["ref_id"])] = n
    from ..files.fsref import FSR
    chains = fs_chains(c, [n["id"] for n in nodes.values()]) if nodes else {}
    hidden, hk = None, (FSR.get(kind) or {}).get("hidden")
    if hk and nodes:  # what the file store's hidden hook of the kind names (fsr_hidden), for the filed ones at once
        sql = hk(c, uid) or ""
        hidden = {int(x[0]) for x in c.execute(f"SELECT id FROM {OBJ[kind]['table']} WHERE id IN ({_ids(nodes)}) AND id IN {sql}").fetchall()} if sql else set()
    return {"nodes": nodes, "chains": chains, "hidden": hidden, "fs": _FsPre({r["id"] for ch in chains.values() for r in ch})}


# ---------------------------------------------------------------- shares of an object (rows of fs_shares on its node)
def _by_role(c, uid, org):
    return (org_role_key(c, uid, org) or "") if org else "owner"


def obj_node(c, uid, kind, rid, make=False):
    """The reference node of the object (a row); make: an object in no folder gets its node at the top of its workspace's
    tree (it then shows in the file store like every filed object)."""
    from ..files.fsref import fs_ref_node
    from ..files.store import fs_log_add, safe_fs_name, _free_name
    reg = obj_reg(kind)
    n = fs_ref_node(c, kind, rid)
    if n is not None or not make:
        return n
    sp = obj_space(c, kind, rid)
    if not sp:
        raise Denied(404)
    org, owner = sp
    nm = safe_fs_name(obj_title(c, kind, rid) or tr(reg["label"])) or tr(reg["label"])
    ts = iso(now_utc())
    nid = insert_id(c, """INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,ref_kind,ref_id,created_by,created_at,updated_at)
                          VALUES(NULL,'ref',?,?,?,?,?,?,?,?)""",
                    (_free_name(c, None, owner, org, nm), owner, org, kind, int(rid), uid, ts, ts))
    fs_log_add(c, nid, "create")
    return c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()


def _pool_ok(c, n, key, tid, uid=None):
    """Is target (key, tid) one uid (default the signed-in person) may share node n with (files/web.py: the same workspace
    only)? Review F5: obj_share / obj_share_restore pass their own uid."""
    from ..files.web import _share_targets
    pool = _share_targets(c, n, uid=int(uid) if uid else None)[{"user_id": "people", "group_id": "groups", "agent_id": "agents"}[key]]
    return any(x["id"] == tid for x in pool)


def obj_share(c, uid, kind, rid, key, target, role="view", expires_at=None):
    """Share the object with ONE person / group / agent (key user_id | group_id | agent_id): needs 'manage'; the same target
    again changes role / expiry. Returns the share id."""
    from ..files.store import fs_log_add
    row, _ = obj_need(c, uid, kind, rid, "manage")
    if acx_of(c, uid).role == "agent":
        raise Denied(403)
    if key not in ("user_id", "group_id", "agent_id") or role not in ("view", "edit"):
        raise BadInput(tr("Invalid data"))
    if isinstance(target, bool) or not isinstance(target, int):
        raise BadInput(tr("Invalid value: {0}", key))
    n = obj_node(c, uid, kind, rid, make=True)
    if not _pool_ok(c, n, key, target, uid):
        raise Denied(409, tr("Only people, groups and agents of the same workspace can get a share"))
    if key == "agent_id":
        from ..files.fslock import fl_is_locked, fsl_denied
        if fl_is_locked(c, n["id"]):
            raise fsl_denied("fs_locked_agent")
    old = c.execute(f"SELECT id FROM fs_shares WHERE node_id=? AND {key}=?", (n["id"], target)).fetchone()
    if old:
        c.execute("UPDATE fs_shares SET role=?, expires_at=? WHERE id=?", (role, expires_at, old[0]))
        sid = old[0]
    else:
        if c.execute("SELECT COUNT(*) FROM fs_shares WHERE node_id=?", (n["id"],)).fetchone()[0] >= OBJ_SHARE_MAX:
            raise Denied(409, tr("Too many shares"))
        sid = insert_id(c, f"INSERT INTO fs_shares(node_id,{key},role,expires_at,created_by,created_at,by_role) VALUES(?,?,?,?,?,?,?)",
                        (n["id"], target, role, expires_at, uid, iso(now_utc()), _by_role(c, uid, row["org_id"] or None)))
        if key == "agent_id":
            from ..files.web import _agent_event
            _agent_event(c, target, n, role)
    fs_log_add(c, n["id"], "share", f"{key[:-3]}:{target}:{role}")
    obj_forget()
    return sid


def _revoked_add(c, src, row, reason, by, org=None, uid=None, kind=None, ref_id=None):
    d = {k: (row[k] if not isinstance(row[k], (bytes, bytearray, memoryview)) else None) for k in row.keys()}
    return insert_id(c, "INSERT INTO obj_revoked(src,org_id,user_id,kind,ref_id,row_json,reason,by_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                     (src, org, uid, kind, ref_id, json.dumps(d, default=str), reason, by, iso(now_utc())))


def _revoked_prune(c):
    c.execute("DELETE FROM obj_revoked WHERE created_at<?", (iso(now_utc() - timedelta(days=OBJ_REVOKED_DAYS)),))


def obj_unshare(c, uid, kind, rid, sid):
    """Take the share sid of the object's own node back (needs 'manage'): it goes into obj_revoked, restorable. Returns the
    obj_revoked id. Shares of the folders above are the file store's (its dialog)."""
    from ..files.store import fs_log_add
    row, _ = obj_need(c, uid, kind, rid, "manage")
    n = obj_node(c, uid, kind, rid)
    s = c.execute("SELECT * FROM fs_shares WHERE id=? AND node_id=?", (int(sid), n["id"] if n else 0)).fetchone()
    if not s:
        raise Denied(404)
    _revoked_prune(c)
    out = _revoked_add(c, "fs_shares", s, "unshare", uid, org=row["org_id"] or None, uid=s["user_id"] or s["agent_id"], kind=kind, ref_id=int(rid))
    c.execute("DELETE FROM fs_shares WHERE id=?", (s["id"],))
    fs_log_add(c, n["id"], "unshare", str(s["id"]))
    obj_forget()
    return out


def obj_share_restore(c, uid, kind, rid, revoked_id):
    """Put a share taken back (obj_unshare / obj_revoke_person) on the object's node again: needs 'manage', and the target
    must still be one the object may be shared with (409 otherwise). Returns the share id."""
    row, _ = obj_need(c, uid, kind, rid, "manage")
    r = c.execute("SELECT * FROM obj_revoked WHERE id=? AND src='fs_shares' AND kind=? AND ref_id=?", (int(revoked_id), kind, int(rid))).fetchone()
    if not r:
        raise Denied(404)
    s = json.loads(r["row_json"])
    key = next((k for k in ("user_id", "group_id", "agent_id") if s.get(k)), None)
    n = obj_node(c, uid, kind, rid, make=True)
    if not key or not _pool_ok(c, n, key, int(s[key]), uid):
        raise Denied(409, tr("Only people, groups and agents of the same workspace can get a share"))
    if c.execute(f"SELECT 1 FROM fs_shares WHERE node_id=? AND {key}=?", (n["id"], int(s[key]))).fetchone():
        c.execute("DELETE FROM obj_revoked WHERE id=?", (r["id"],))
        raise Denied(409, tr("Already shared"))
    sid = insert_id(c, f"INSERT INTO fs_shares(node_id,{key},role,expires_at,created_by,created_at,by_role) VALUES(?,?,?,?,?,?,?)",
                    (n["id"], int(s[key]), s.get("role") if s.get("role") in ("view", "edit") else "view", s.get("expires_at"),
                     s.get("created_by"), s.get("created_at") or iso(now_utc()), s.get("by_role")))
    c.execute("DELETE FROM obj_revoked WHERE id=?", (r["id"],))
    obj_forget()
    return sid


def obj_shares(c, uid, kind, rid):
    """{shares: the object's own, inherited: those of the folders above (read-only here), revoked: taken back, restorable}
    -- for who manages the object."""
    from ..files.web import _inherited_shares, _shares
    from ..files.store import fs_chain
    obj_need(c, uid, kind, rid, "manage")
    n = obj_node(c, uid, kind, rid)
    if n is None:
        own, inh = [], []
    else:
        own, inh = _shares(c, n["id"]), _inherited_shares(c, fs_chain(c, n["id"]))
    rev = []
    for r in c.execute("SELECT * FROM obj_revoked WHERE src='fs_shares' AND kind=? AND ref_id=? ORDER BY id DESC LIMIT 50", (kind, int(rid))):
        s = json.loads(r["row_json"])
        rev.append({"id": r["id"], "user_id": s.get("user_id"), "group_id": s.get("group_id"), "agent_id": s.get("agent_id"),
                    "role": s.get("role"), "reason": r["reason"], "at": r["created_at"]})
    return {"shares": own, "inherited": inh, "revoked": rev}


# ---------------------------------------------------------------- revocation in one place
def _take(c, src, sql, args, reason, by, org, who_col, kind=None):
    """Moves the rows of src matching sql into obj_revoked and deletes them. Returns their number."""
    rows = c.execute(f"SELECT * FROM {src} WHERE {sql}", args).fetchall()
    refs = {}
    if src == "fs_shares" and rows:  # review F2: a share on a core object's reference node keeps kind / ref_id (obj_shares, restore)
        q = ",".join("?" * len({r["node_id"] for r in rows}))
        refs = {x[0]: (x[1], x[2]) for x in c.execute(f"SELECT id, ref_kind, ref_id FROM fs_nodes WHERE kind='ref' AND id IN ({q})",
                                                      tuple({r["node_id"] for r in rows})).fetchall() if x[1] in OBJ}
    for r in rows:
        who = (r[who_col] or (r["agent_id"] if "agent_id" in r.keys() else None)) if who_col else None
        rk, ri = refs.get(r["node_id"], (kind, None)) if refs else (kind, None)
        _revoked_add(c, src, r, reason, by, org=org, uid=who, kind=rk, ref_id=ri)
    if rows:
        c.execute(f"DELETE FROM {src} WHERE {sql}", args)
    return len(rows)


def _agents_of(c, uid):
    return [r[0] for r in c.execute("SELECT user_id FROM agents WHERE owner_id=?", (int(uid),)).fetchall()]


def _actor():
    u = getattr(g, "user", None) if has_request_context() else None
    return u["id"] if u is not None else None


def obj_revoke_person(c, uid, org, reason, heir=None, role=None):
    """What a person (and their agents) loses in one place (module docstring); runs beside the old loops of org_leave /
    org_member_put / odl_retire / the account deletion, which stay as they are. Returns {what: number of rows}."""
    if reason not in OBJ_REASONS or reason == "unshare":
        raise ValueError(f"obj_revoke_person: unknown reason {reason!r}")
    out = {}
    by = _actor()
    with system_ctx(c):  # who loses what is structure (also rows of other people's agents and of nodes the actor does not see)
        _revoked_prune(c)
        if reason == "leave" and uid and org:
            ppl = [int(uid), *_agents_of(c, uid)]
            q = ",".join("?" * len(ppl))
            out["fs_shares"] = _take(c, "fs_shares", f"(user_id IN ({q}) OR agent_id IN ({q})) AND node_id IN (SELECT id FROM fs_nodes WHERE org_id=?)",
                                     (*ppl, *ppl, int(org)), reason, by, int(org), "user_id")
            out["tchat_members"] = _take(c, "tchat_members", f"user_id IN ({q}) AND room_id IN (SELECT id FROM tchat_rooms WHERE org_id=?)",
                                         (*ppl, int(org)), reason, by, int(org), "user_id")
            c.execute("DELETE FROM obj_undo WHERE user_id=? AND org_id=?", (int(uid), int(org)))
            if heir and heir != uid:
                for reg in OBJ.values():
                    if reg["base_role"] is None:  # the default rules: the organisation's object stays with it, the heir owns it
                        c.execute(f"UPDATE {reg['table']} SET owner_id=? WHERE org_id=? AND owner_id=?", (int(heir), int(org), int(uid)))
        elif reason == "role" and uid and org:
            if role in ("guest", "accounting"):  # F5 (#2822): the open channels they joined themselves (added_by = themselves / unknown)
                out["tchat_members"] = _take(c, "tchat_members", "user_id=? AND (added_by=? OR added_by IS NULL) AND room_id IN "
                                             "(SELECT id FROM tchat_rooms WHERE org_id=? AND kind='channel' AND is_open=1)",
                                             (int(uid), int(uid), int(org)), reason, by, int(org), "user_id")
        elif reason == "retire" and org:
            out["fs_shares"] = _take(c, "fs_shares", "node_id IN (SELECT id FROM fs_nodes WHERE org_id=?)", (int(org),), reason, by, int(org), "user_id")
            out["tchat_members"] = _take(c, "tchat_members", "room_id IN (SELECT id FROM tchat_rooms WHERE org_id=?)", (int(org),),
                                         reason, by, int(org), "user_id")
            c.execute("DELETE FROM obj_undo WHERE org_id=?", (int(org),))
        elif reason == "delete" and uid:
            from ..accounts.orgretain import upg_heir
            for reg in OBJ.values():  # review F1: an organisation's object stays with it, the heir owns it (owner_id cascades)
                if reg["base_role"] is None:
                    out[reg["kind"]] = 0
                    for (o,) in c.execute(f"SELECT DISTINCT org_id FROM {reg['table']} WHERE owner_id=? AND org_id IS NOT NULL", (int(uid),)).fetchall():
                        h = upg_heir(c, o, uid)
                        if h:
                            out[reg["kind"]] += c.execute(f"UPDATE {reg['table']} SET owner_id=? WHERE org_id=? AND owner_id=?",
                                                          (int(h), int(o), int(uid))).rowcount
            c.execute("DELETE FROM obj_undo WHERE user_id=?", (int(uid),))
            c.execute("UPDATE obj_history SET user_id=NULL WHERE user_id=?", (int(uid),))
            c.execute("UPDATE obj_revoked SET by_id=NULL WHERE by_id=?", (int(uid),))
            c.execute("DELETE FROM obj_revoked WHERE user_id=?", (int(uid),))
    obj_forget()
    return out


# ---------------------------------------------------------------- the object as the client sees it
def obj_public(c, uid, kind, row, role=None):
    """The object for the client / the API: its fields, workspace, version and what uid may do."""
    reg = obj_reg(kind)
    if reg["public"]:
        return reg["public"](c, uid, row, role)
    out = {k: row[k] for k in ("id", "org_id", "owner_id", "rev", "created_at", "created_by", "updated_at", "updated_by", "deleted_at")}
    for k in reg["fields"]:
        out[k] = row[k]
    title = obj_title(c, kind, row["id"]) if reg["title"] or "title" not in row.keys() else (row["title"] or "")  # review F3: the row is here
    out.update(kind=kind, role=role, title=title, open=reg["open_url"](row["id"]))
    return out


def _probe_register():
    """Test containers only (KALMIDO_TEST=1 and KALMIDO_TEST_OBJ=1, tests/obj_core_test.py, tests/obj_write_test.py): kind
    'objprobe' = a row of table obj_probe, which the tests create (tests/obj_probe.sql); it never exists elsewhere.
    Fields title / note / size / done; a title starting with "hide" is hidden from shares, agents and tokens; the agents' data
    lock area "contracts" locks the kind."""
    import os
    if os.environ.get("KALMIDO_TEST") != "1" or os.environ.get("KALMIDO_TEST_OBJ") != "1":
        return
    obj_register("objprobe", "obj_probe", label="Test object", area="other",
                 fields={"title": f_text(120, required=True), "note": f_text(2000, line=False), "size": f_int(0, 1000), "done": f_bool()},
                 hidden=lambda c, uid: "(SELECT id FROM obj_probe WHERE title ILIKE 'hide%')", dl_area="contracts")


_probe_register()
