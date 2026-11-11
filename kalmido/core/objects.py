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
               protect=None, on_trash=None, content=None, undo_scope=None, public=None, routes=True, trash_role="manage",
               fsref=True, share_cols=(), on_restore=None, on_revoke=None, list_col="list_id", org_join="member")
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
      2.568.0 (#4739, stage 6 lists) -- for an old area that already has its own reference kind and keeps its role table:
      fsref      False: the kind keeps its own registration in files/fsref.py (the core does not replace it) and the area
                 materializes the shares of its node into its base role (lists: lists/lffolder.py -> list_members), so obj_role
                 does not read the node's shares a second time, and obj_node never makes a node (the area places it)
      share_cols columns of fs_shares the area writes on its shares (obj_share extra=) and obj_share_restore puts back
      on_restore f(c, uid, id, share) after obj_share_restore put a share back (share = the row as it was): the area puts its
                 role table right under its own rules (raise Denied to refuse: the caller does not commit); with it the
                 core leaves the target check to the area
      on_revoke  f(c, uid, org, reason, role=None) -> {what: n}: called by obj_revoke_person after the core's own part
      list_col   the column an API token's list limit is checked against (lists: their own id)
      2.773.0 (#5292) -- the one trash of the core (core/writes.py obj_trash / obj_restore / obj_purge / obj_trash_prune):
      children   ((table, key column), ...): rows of other tables that belong to the object (an event of a calendar); they go
                 into the trash with it (its deleted_at; one in the trash on its own before keeps its own time), come back with
                 it (only the ones that went with it) and are deleted for good with it
      trash_prune True: the core's retention run (obj_trash_tick) deletes the kind's trash after the trash period; False
                 (default): the area keeps its own run until its stage moves it onto the core
      2.754.0 (#5268, Q0b of the cross-section audit #3563) -- a light kind of an old area (task, event, hub_mail, client):
      node       False: the kind has no reference node at all (no fs_ref_register, no shares, no folder, no routes -- routes=
                 is ignored --, no fields, no write path of the core: obj_reg_node refuses it with 404, obj_visible_sql / obj_rows with ValueError -- the
                 area lists its own rows). It only names its objects for the (kind, id) tables of the core: obj_role /
                 obj_need (base_role = exactly the area's own check, steps 1 + 2 still apply), obj_title, open_url, obj_space.
                 base_role is required, visible is not.
  obj_role(c, uid, kind, id, row=None) -> None | 'view' | 'edit' | 'manage'
  obj_need(c, uid, kind, id, need="view" | "write" | "manage", trash=False) -> (row, role); Denied 404 / 403
  obj_visible_sql(c, uid, kind) -> "(SELECT id ...)" the ids uid sees (not in the trash), ids inlined, no ? parameters
  obj_rows(c, uid, kind, where="", args=(), trash=False) -> [(row, role)] the visible objects (trash=True: the trash uid manages)
  obj_share(c, uid, kind, id, key, target, role="view", expires_at=None, extra=None, checked=False) -> share id
      (key user_id | group_id | agent_id; extra: the kind's share_cols; checked=True: the area's route checked the rights and
      the target itself under rules of its own -- the core writes the share row, its log and nothing else, #4739)
  obj_unshare(c, uid, kind, id, sid, checked=False) -> revoked id  (the share goes into obj_revoked: obj_share_restore puts it
      back; checked=True: the area checked the right itself, e.g. a member leaving a list)
  obj_share_restore(c, uid, kind, id, rid) -> share id
  obj_node_share(c, uid, node, key, target, role, expires_at, org) / obj_node_unshare(c, uid, node, sid, kind, ref_id, org)
      2.565.0 (#4717): the bare share row on a reference node (no rights check: the caller's) -- for the old areas whose
      reference kind is the file store's own (wiki pages, tables, stage 4); obj_share / obj_unshare use them too
  obj_shares(c, uid, kind, id) -> {shares, inherited, revoked}
  obj_gate(c, uid, kind, row) -> bool   steps 1 + 2 of obj_role for a row the area listed itself (2.565.0, #4719)
  obj_token_lists(uid) -> set | None    the list limit of uid's own API token in this request (step 2)
  obj_share_rows_sql(kind) -> "(SELECT ref_id, user_id, group_id, agent_id, role, created_by ...)" the live shares of the kind
  obj_member_put(c, by, kind, id, key, target, role="edit") / obj_member_take(c, by, kind, id, key, targets, reason="unshare")
      a kind registered with listed=False (the team chat's rooms): the area's own rule decided, the core writes / takes back
      the share row (taken = obj_revoked, restorable)
  obj_revoke_person(c, uid, org, reason, heir=None, role=None) -> {table: rows} -- reason 'leave' (uid leaves org: its shares
      and its agents' on the organisation's nodes, its team chat memberships of the organisation's rooms; its core objects
      to heir), 'role' (uid's role in org is now role: guest / accounting leave the open channels they joined themselves),
      'retire' (org retires, uid None: every share on its nodes, every membership of its rooms), 'delete' (account uid goes:
      its undo steps, its name in the history). What goes lands in obj_revoked (30 days, OBJ_REVOKED_DAYS).
      2.649.0 (#5051): 'leave' / 'retire' also revoke the person's (the organisation's) public links and file requests of
      the file store (revoked_at + a row in obj_revoked), 'role' those of nodes uid can no longer share / write in
The caller commits."""
import json
import re
from datetime import timedelta

from flask import g, has_request_context, request

from ..accounts.orgroles import FULL_READ, RO_MSG, org_role_key
from .access import Denied, acx_of, acx_org_ok, collab_all, need_feat, token_lists
from .db import LV_AREA_KEYS, insert_id, iso, now_iso, now_utc
from .db import iso_ms  # 2.649.0 (#5051): a table's card (sheet_shares.revoked_at)
from .errors import BadInput
from .i18n import tr
from .pg import system_ctx, table_columns
from ..files.fsref import FSR, _api_way as fsr_api_way, fs_ref_node, fs_ref_node_role, fs_ref_register
from ..files.store import _free_name, _FsPre, fs_chain, fs_chains, fs_log_add, fs_visible_sql_c, safe_fs_name
from ..files.store import fs_role  # 2.649.0 (#5051): _take_public
from ..files.fsref import fs_unshare_hooks  # 2.649.0 (#5051): obj_boundary_take
from ..files.web import _agent_event, _inherited_shares, _share_targets, _shares
from .dlock import dl_of
from ..files.fslock import fl_is_locked, fsl_denied
from ..accounts.orgretain import upg_heir
from ..accounts.orgretain import obj_share_gone  # 2.924.0 (#5069)

from .objhooks import BOUNDARY  # 2.649.0 (#5051)
from .undogroups import ug_drop  # 2.747.0 (#5249): a person's step groups go where their undo rows go
from .objhooks import FOLLOW, OBJ, REVOKE  # kind -> the registered hooks; what a person loses (core/objhooks.py: accounts reads them)
OBJ_RANK = {None: 0, "view": 1, "edit": 2, "manage": 3}
OBJ_ROLES = ("view", "edit", "manage")
OBJ_REVOKED_DAYS = 30  # rows taken away stay restorable this long (obj_revoked)
OBJ_SHARE_MAX = 200
OBJ_REASONS = ("leave", "role", "retire", "delete", "unshare", "expired", "boundary", "move")  # 2.747.0 (#5246): + a move to another workspace ended it; 2.568.0 (#4739, review F4): + an expiry ran out; 2.649.0 (#5051): + the nightly boundary repair
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
                 protect=None, on_trash=None, content=None, undo_scope=None, public=None, routes=True, trash_role="manage",
                 fsref=True, share_cols=(), on_restore=None, on_revoke=None, list_col="list_id", listed=True, node_shares=False,
                 fs_hooks=None, org_join="member", children=(), trash_prune=False, node=True, agent_own=False,
                 on_share_back=None):
    """Register a kind of core object (module docstring). Registering the same kind again replaces it (a module reload).
    2.565.0 (#4719): listed=False = the object's reference node only carries its shares (files/fsref.py): it lies in no
    folder and the file store never shows it; the area writes the shares with obj_member_put / obj_member_take.
    2.924.0 (#5069, stage 7b): node_shares=True = an area whose own sharing dialog writes the shares of the object's node (the
    calendars and address books; their old member tables of stage 3, members= before, are gone): the node does not go into the
    file store's trash alone while it carries shares (_members_protect), when an organisation retires the shares of the
    owner's own agents stay on it (their delegates; the node follows the object into the owner's private tree), and the
    generic routes GET /api/obj/<kind>/<id>/shares and POST .../shares/<rid>/restore serve it (core/objweb.py).
    on_share_back = f(c, uid, id, share) after obj_share_restore put a share of such a kind back the core's way (the core
    checked the target): the area's side effects (cal_touch / book_touch, the News of a new share). fs_hooks = keyword arguments of fs_ref_register that replace the core's
    (base_role, on_trash, content_gate ...): a kind the file store knew before the core keeps its folder rules (contacts:
    filing and sharing the book's node stay with who manages it, files/fsref.py 2.199.0 F).
    2.579.0 (#4802): org_join = who may bring an object into an organisation (obj_create with org_id, core/writes.py
    obj_space_set): "member" (default: every member who writes there) or "admin" (only its admins: a saved view of the
    documents search, which a person keeps private until an admin shares it with everyone of the organisation; 2.657.0, #4828:
    obj_create refuses an org_id for such a kind, even from an admin -- it is made private and shared with obj_space_set).
    2.905.0 (#5288): agent_own=True = an agent's own private object of the kind (owner_id = the agent, made through the area's own
    API route, e.g. a template) is its own ('manage', listed) as a person's is; every other object an agent still reaches only
    through a share."""
    if not _NAME.fullmatch(kind or "") or not _TABLE.fullmatch(table or ""):
        raise ValueError(f"obj_register: invalid kind / table {kind!r} {table!r}")
    if not node:  # 2.754.0 (#5268): a light kind (module docstring): only its role, title, open_url and space
        if base_role is None or fields or node_shares:  # 2.924.0 (#5069): node_shares was members
            raise ValueError(f"obj_register {kind}: a kind without a node needs base_role and has no fields or node shares")
        routes, fsref = False, False
    elif base_role is not None and visible is None:
        raise ValueError(f"obj_register {kind}: a base_role hook needs its visible hook (obj_visible_sql)")
    if org_access not in ("edit", "view", None) or trash_role not in ("edit", "manage") or area not in LV_AREA_KEYS or org_join not in ("member", "admin"):
        raise ValueError(f"obj_register {kind}: invalid org_access / trash_role / area")
    if not isinstance(fields, dict) or any(k in OBJ_COLS or not _TABLE.fullmatch(k) for k in fields):
        raise ValueError(f"obj_register {kind}: fields must be own columns")
    reg = {"kind": kind, "table": table, "label": label, "fields": dict(fields), "space": space, "title": title, "base_role": base_role,
           "visible": visible, "cap": cap, "hidden": hidden, "org_access": org_access, "area": area, "scopes": tuple(scopes),
           "dl_area": dl_area, "feat": feat, "undo_scope": undo_scope, "public": public, "routes": bool(routes), "trash_role": trash_role,
           "listed": bool(listed), "open_url": open_url or (lambda rid: f"obj/{kind}/{int(rid)}"),
           # 2.568.0 (#4739): an old area with its own reference kind and role table (module docstring)
           "fsref": bool(fsref), "share_cols": tuple(x for x in share_cols if _TABLE.fullmatch(x)), "on_restore": on_restore,
           "on_revoke": on_revoke, "list_col": list_col if _TABLE.fullmatch(list_col or "") else "list_id",
           "node_shares": bool(node_shares), "on_share_back": on_share_back,  # 2.924.0 (#5069): was members= (stage 3)
           "org_join": org_join,  # 2.579.0 (#4802)
           "node": bool(node),  # 2.754.0 (#5268)
           "agent_own": bool(agent_own)}  # 2.905.0 (#5288)
    kids = tuple(tuple(x) for x in (children or ()))  # 2.773.0 (#5292)
    if any(len(x) != 2 or not all(_TABLE.fullmatch(y or "") for y in x) or x[0] == table for x in kids):
        raise ValueError(f"obj_register {kind}: children must be ((table, key column), ...) of other tables")
    if not node and (kids or trash_prune):  # a light kind (2.754.0, #5268) has no trash of the core (2.773.0, #5292)
        raise ValueError(f"obj_register {kind}: a kind without node has no children / trash_prune")
    reg.update(children=kids, trash_prune=bool(trash_prune))
    OBJ[kind] = reg
    if not fsref:
        return reg  # 2.568.0 (#4739): the area's own registration in files/fsref.py stays

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
                obj_restore(c, uid, kind, rid, step=False)  # 2.773.0 (#5292): the file store's restore, no step of its own
            else:
                c.execute("UPDATE fs_nodes SET deleted_at=?, deleted_by=? WHERE kind='ref' AND ref_kind=? AND ref_id=?",
                          (row["deleted_at"], row["deleted_by"], kind, int(rid)))
                return "stays"
        return on_trash(c, uid, rid, restore) if on_trash else None

    if node_shares and protect is None:  # review F3 (#4712): the node of a shared object stays out of the file store's trash alone
        protect = _members_protect(kind)
    fsr = dict(label=label, open_url=reg["open_url"], base_role=fsr_base, space=lambda c, rid: obj_space(c, kind, rid),
               protect=protect, hidden=hidden, on_trash=fsr_on_trash, title=lambda c, rid: obj_title(c, kind, rid),
               content=content, cap=cap, listed=listed)
    fsr.update(fs_hooks or {})  # 2.566.0 (#4712)
    fs_ref_register(kind, **fsr)
    return reg


def _members_protect(kind):
    """2.566.0 (#4712, review F3): the file store's protect hook of a kind with node_shares (#5069): while its node carries
    shares it does not go into the file store's trash on its own (its people would lose the object while the object itself
    stays); it goes there with the object (obj_trash), a folder going into the trash leaves it one level up."""
    def protect(c, rid):
        with system_ctx(c):  # structure: whether the node carries a share
            on = c.execute("SELECT 1 FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id WHERE n.kind='ref' AND n.ref_kind=? AND n.ref_id=? "
                           "LIMIT 1", (kind, int(rid))).fetchone()
        return tr("This entry carries the shares of its calendar or address book: it goes into the trash only with it") if on else None
    return protect


def obj_reg(kind):
    """The registered hooks of kind; Denied(404) for an unknown one."""
    r = OBJ.get(kind or "")
    if r is None:
        raise Denied(404)
    return r


def obj_reg_node(kind):
    """2.754.0 (#5268): obj_reg for the core's own write paths (core/writes.py): Denied(404) also for a light kind (node=False),
    whose objects are written by their area only."""
    r = obj_reg(kind)
    if not r.get("node", True):
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
    return fsr_api_way(c, uid)


def _req_token_lists(uid):
    """The list limit of the request's own token (None: none, or not uid's request)."""
    if not has_request_context() or g.get("auth_via") != "token" or not g.get("user") or g.user["id"] != uid:
        return None
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
        d = dl_of(c, uid)
        if d and d["areas"].get(reg["dl_area"], True):
            return False
    lim = _req_token_lists(uid)
    if lim is not None:
        col = reg["list_col"]  # 2.568.0 (#4739): a list itself is checked by its own id
        if col not in row.keys() or row[col] not in lim:
            return False
    return True


def _base(c, uid, reg, row):
    """Step 3a: the area's own role (its hook, or the default of the module docstring)."""
    if reg["base_role"]:
        r = reg["base_role"](c, uid, int(row["id"]))
        return r if r in OBJ_ROLES else None
    if acx_of(c, uid).role == "agent":  # 2.905.0 (#5288): agent_own -- its own private object only
        return "manage" if reg.get("agent_own") and not row["org_id"] and row["owner_id"] == uid else None
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


def obj_role(c, uid, kind, rid, row=None, pre=None, own_trash=False):
    """None | 'view' | 'edit' | 'manage' -- THE role of account uid on the object (module docstring, steps 1-4). pre: obj_rows'
    reads of the whole listing (_rows_pre). 2.778.0 (#5371): own_trash=True skips step 4 for an object uid itself put into
    the trash (deleted_by) -- only for taking that own step back (core/writes.py obj_restore undo=True); not cached."""
    reg = OBJ.get(kind or "")
    if reg is None or not uid:
        return None
    try:
        rid = int(rid)
        uid = int(uid)  # #5268 review F6: the own-request checks (_req_token_lists, hmv1._hmv_own) compare ints
    except (TypeError, ValueError):
        return None
    cache = None if own_trash else _cache()
    key = (uid, kind, rid)
    if cache is not None and key in cache:
        return cache[key]
    row = row if row is not None else obj_row(c, kind, rid)
    out = None
    if row is not None and _gate(c, uid, reg, row):
        base = _base(c, uid, reg, row)
        # review F3: a share gives at most 'edit' -- the chain is read only when the area's own role is below it
        share = _share_role(c, uid, reg, row, pre=pre) if OBJ_RANK[base] < OBJ_RANK["edit"] and reg["fsref"] else None  # #4739
        out = base if OBJ_RANK[base] >= OBJ_RANK[share] else share
        own = own_trash and row["deleted_by"] is not None and int(row["deleted_by"]) == int(uid)
        if row["deleted_at"] and out != "manage" and not own:
            out = None  # step 4: the trash only for who may restore it
    if cache is not None:
        cache[key] = out
    return out


def obj_need(c, uid, kind, rid, need="view", trash=False, own_trash=False):
    """(row, role) of the object for uid, or Denied: 404 without a role (or in the trash unless trash=True; outside the
    trash with trash=True too), 403 without the role need ('view' | 'write' | 'manage'). own_trash: obj_role's (#5371)."""
    reg = obj_reg(kind)
    if reg["feat"]:
        need_feat(reg["feat"])
    row = obj_row(c, kind, rid)
    role = obj_role(c, uid, kind, rid, row=row, own_trash=own_trash) if row is not None else None
    if not role or bool(row["deleted_at"]) != bool(trash):
        raise Denied(404)
    want = {"view": "view", "write": "edit", "edit": "edit", "manage": "manage"}.get(need)
    if want is None:
        raise ValueError(f"obj_need: unknown need {need!r}")
    if OBJ_RANK[role] < OBJ_RANK[want]:
        org = row["org_id"] or None
        if org and org_role_key(c, uid, org) == "readonly":
            raise Denied(403, tr(RO_MSG))
        raise Denied(403)
    return row, role


# ---------------------------------------------------------------- what uid sees (SQL)
def _ids(xs):
    return ",".join(str(int(x)) for x in xs) or "0"


def _share_sql(c, uid, reg, agent):
    """The ids whose reference node lies below (or is) a node shared explicitly with uid, in the object's own workspace,
    reachable in the file store (fs_visible_sql: the boundary, the trash of the folders, locks) and not hidden."""
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
    if not reg.get("listed", True):  # 2.565.0 (#4719): the node lies in no folder and in no listing of the file store
        return (f"(SELECT n.ref_id FROM fs_nodes n JOIN {t} o ON o.id = n.ref_id WHERE n.kind = 'ref' AND n.ref_kind = '{kind}' "
                f"AND n.deleted_at IS NULL AND n.id IN (SELECT node_id FROM fs_shares WHERE {who} AND (expires_at IS NULL OR expires_at > '{now}')) "
                f"AND (CASE WHEN o.org_id IS NULL THEN n.org_id IS NULL ELSE n.org_id = o.org_id END){hid})")
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
    if not reg.get("node", True):  # 2.754.0 (#5268): a light kind is listed by its area (its own visibility), not here
        raise ValueError(f"obj_visible_sql {kind}: a kind without a node is listed by its area")
    t = reg["table"]
    none = f"(SELECT id FROM {t} WHERE FALSE)"
    if not uid:
        return none
    uid = int(uid)
    ctx = acx_of(c, uid)
    agent = ctx.role == "agent"
    if agent and reg["dl_area"]:
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
    elif reg.get("agent_own"):  # 2.905.0 (#5288): an agent's own private objects of the kind
        parts.append(f"(o.org_id IS NULL AND o.owner_id = {uid})")
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
        if "list_id" not in table_columns(c, t):
            return none
        extra += f" AND o.list_id IN ({_ids(sorted(lim))})"
    return f"(SELECT o.id FROM {t} o WHERE o.deleted_at IS NULL AND {floor} AND ({' OR '.join(parts)}){extra})"


def obj_rows(c, uid, kind, where="", args=(), trash=False, limit=500):
    """[(row, role)] of the objects of kind uid sees (where: an extra condition on the table, alias o), newest change first.
    trash=True: the objects in the trash uid may restore. Every row is checked with obj_role (the SQL is the candidate set)."""
    reg = obj_reg(kind)
    if not reg.get("node", True):  # 2.754.0 (#5268): see _visible_sql
        raise ValueError(f"obj_rows {kind}: a kind without a node is listed by its area")
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
    nodes = {}
    ids = sorted({int(i) for i in ids})
    for k in range(0, len(ids), 500):
        part = ids[k:k + 500]
        for n in c.execute(f"SELECT * FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id IN ({_ids(part)})", (kind,)).fetchall():
            nodes[int(n["ref_id"])] = n
    chains = fs_chains(c, [n["id"] for n in nodes.values()]) if nodes else {}
    hidden, hk = None, (FSR.get(kind) or {}).get("hidden")
    if hk and nodes:  # what the file store's hidden hook of the kind names (fsr_hidden), for the filed ones at once
        sql = hk(c, uid) or ""
        hidden = {int(x[0]) for x in c.execute(f"SELECT id FROM {OBJ[kind]['table']} WHERE id IN ({_ids(nodes)}) AND id IN {sql}").fetchall()} if sql else set()
    return {"nodes": nodes, "chains": chains, "hidden": hidden, "fs": _FsPre({r["id"] for ch in chains.values() for r in ch})}


# ---------------------------------------------------------------- shares of an object (rows of fs_shares on its node)
def _by_role(c, uid, org):
    return (org_role_key(c, uid, org) or "") if org else "owner"


def obj_node(c, uid, kind, rid, make=False, parent=None):
    """The reference node of the object (a row); make: an object in no folder gets its node at the top of its workspace's
    tree (it then shows in the file store like every filed object). 2.566.0 (#4712): parent = the folder (of the object's
    workspace, the caller's choice: an area's root folder) instead of the top."""
    reg = obj_reg(kind)
    n = fs_ref_node(c, kind, rid)
    if n is not None or not make or not reg["fsref"]:  # 2.568.0 (#4739): such an area places its nodes itself
        return n
    sp = obj_space(c, kind, rid)
    if not sp:
        raise Denied(404)
    org, owner = sp
    nm = safe_fs_name(obj_title(c, kind, rid) or tr(reg["label"])) or tr(reg["label"])
    ts = iso(now_utc())
    pid = int(parent) if parent else None
    nid = insert_id(c, """INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,ref_kind,ref_id,created_by,created_at,updated_at)
                          VALUES(?,'ref',?,?,?,?,?,?,?,?)""",
                    (pid, _free_name(c, pid, owner, org, nm), owner, org, kind, int(rid), uid, ts, ts))
    fs_log_add(c, nid, "create")
    return c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()


def obj_node_follow(c, kind, rid):
    """2.566.0 (#4712): the object moved into another workspace (its area checked that its shares fit there, e.g. obj_org_set):
    its reference node follows to the top of that workspace's tree with the shares on it (a node in the old tree gives
    nothing, files/fsref.py _same_space). Nothing without a node. No rights check; the caller commits."""
    sp = obj_space(c, kind, rid)
    with system_ctx(c):  # structure: the node may lie in the tree the object just left
        n = c.execute("SELECT id, name FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id=?", (kind, int(rid))).fetchone()
        if sp is None or n is None:
            return
        org, owner = sp
        c.execute("UPDATE fs_nodes SET org_id=?, owner_id=?, parent_id=NULL, name=? WHERE id=?",
                  (org, owner, _free_name(c, None, owner, org, n["name"], skip=n["id"]), n["id"]))
    obj_forget()


def _pool_ok(c, n, key, tid, uid=None):
    """Is target (key, tid) one uid (default the signed-in person) may share node n with (files/web.py: the same workspace
    only)? Review F5: obj_share / obj_share_restore pass their own uid."""
    pool = _share_targets(c, n, uid=int(uid) if uid else None)[{"user_id": "people", "group_id": "groups", "agent_id": "agents"}[key]]
    return any(x["id"] == tid for x in pool)


def _share_extra(reg, extra):
    """2.568.0 (#4739): the kind's own share columns of extra ({} for none; another column is a programming error)."""
    extra = dict(extra or {})
    bad = [k for k in extra if k not in reg["share_cols"]]
    if bad:
        raise ValueError(f"obj_share {reg['kind']}: not a share column of the kind: {bad}")
    return extra


def _share_match(reg, extra):
    """2.568.0 (#4739): the SQL that tells a share row of the area's own (share_cols carry a marker) from other rows of the node
    with the same target (e.g. a list's own member share beside a share made in the file store's dialog)."""
    if "list_own" in reg["share_cols"]:
        return " AND COALESCE(list_own, 0)=?", (1 if (extra or {}).get("list_own") else 0,)
    return "", ()


def obj_share(c, uid, kind, rid, key, target, role="view", expires_at=None, extra=None, checked=False):
    """Share the object with ONE person / group / agent (key user_id | group_id | agent_id): needs 'manage'; the same target
    again changes role / expiry. Returns the share id. 2.568.0 (#4739): extra = the kind's share_cols; checked=True = the area's
    route checked the right, the target and its own rules (lists: owner / list admin, the workspace, one agent per list ...)."""
    reg = obj_reg(kind)
    extra = _share_extra(reg, extra)
    if checked:
        row = obj_row(c, kind, rid)
        if row is None:
            raise Denied(404)
    else:
        row, _ = obj_need(c, uid, kind, rid, "manage")
        if acx_of(c, uid).role == "agent":
            raise Denied(403)
    if key not in ("user_id", "group_id", "agent_id") or role not in ("view", "edit"):
        raise BadInput(tr("Invalid data"))
    if isinstance(target, bool) or not isinstance(target, int):
        raise BadInput(tr("Invalid value: {0}", key))
    n = obj_node(c, uid, kind, rid, make=True)
    if n is None:
        raise Denied(404)  # #4739: an area that places its nodes itself has none for it (a list's basket)
    if not checked and not _pool_ok(c, n, key, target, uid):
        raise Denied(409, tr("Only people, groups and agents of the same workspace can get a share"))
    return obj_node_share(c, uid, n, key, target, role, expires_at, row["org_id"] or None, event=not checked, checked=checked,
                          match=_share_match(reg, extra), extra=extra)


def obj_node_share(c, uid, n, key, target, role="view", expires_at=None, org=None, event=True, checked=False, match=None,
                   extra=None):
    """2.565.0 (#4717): the share row itself on reference node n (a row) -- obj_share's write, also for the old areas whose
    reference kind is the file store's own (wiki pages, tables: stage 4), which check who may share and with whom by their own
    rules first (the caller did). The same target again changes role / expiry; event=False: an agent hears of a new share from
    the caller (or not at all: a migration). Returns the share id. 2.568.0 (#4739): checked=True = the area's own rules for
    agents and the share limit (lists: the lock, the bridge); match = _share_match's SQL, extra = the kind's share_cols."""
    if key not in ("user_id", "group_id", "agent_id") or role not in ("view", "edit"):
        raise BadInput(tr("Invalid data"))
    if key == "agent_id" and not checked:
        if fl_is_locked(c, n["id"]):
            raise fsl_denied("fs_locked_agent")
    mq, ma = match or ("", ())
    old = c.execute(f"SELECT id FROM fs_shares WHERE node_id=? AND {key}=?{mq}", (n["id"], int(target), *ma)).fetchone()
    if old:
        c.execute("UPDATE fs_shares SET role=?, expires_at=? WHERE id=?", (role, expires_at, old[0]))
        sid = old[0]
    else:
        if not checked and c.execute("SELECT COUNT(*) FROM fs_shares WHERE node_id=?", (n["id"],)).fetchone()[0] >= OBJ_SHARE_MAX:
            raise Denied(409, tr("Too many shares"))
        sid = insert_id(c, f"INSERT INTO fs_shares(node_id,{key},role,expires_at,created_by,created_at,by_role) VALUES(?,?,?,?,?,?,?)",
                        (n["id"], int(target), role, expires_at, uid, iso(now_utc()), _by_role(c, uid, org) if uid else None))
        if key == "agent_id" and event and not checked:
            _agent_event(c, int(target), n, role)
    for k, v in (extra or {}).items():
        c.execute(f"UPDATE fs_shares SET {k}=? WHERE id=?", (v, sid))
    fs_log_add(c, n["id"], "share", f"{key[:-3]}:{int(target)}:{role}")
    obj_forget()
    return sid


def _revoked_add(c, src, row, reason, by, org=None, uid=None, kind=None, ref_id=None):
    d = {k: (row[k] if not isinstance(row[k], (bytes, bytearray, memoryview)) else None) for k in row.keys()}
    return insert_id(c, "INSERT INTO obj_revoked(src,org_id,user_id,kind,ref_id,row_json,reason,by_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                     (src, org, uid, kind, ref_id, json.dumps(d, default=str), reason, by, iso(now_utc())))


def _revoked_prune(c):
    c.execute("DELETE FROM obj_revoked WHERE created_at<?", (iso(now_utc() - timedelta(days=OBJ_REVOKED_DAYS)),))


def obj_unshare(c, uid, kind, rid, sid, checked=False):
    """Take the share sid of the object's own node back (needs 'manage'): it goes into obj_revoked, restorable. Returns the
    obj_revoked id. Shares of the folders above are the file store's (its dialog). 2.568.0 (#4739): checked=True = the area
    checked the right itself (a member leaving a list on their own)."""
    if checked:
        row = obj_row(c, kind, rid)
        if row is None:
            raise Denied(404)
    else:
        row, _ = obj_need(c, uid, kind, rid, "manage")
    n = obj_node(c, uid, kind, rid)
    out = obj_node_unshare(c, uid, n, sid, kind=kind, ref_id=int(rid), org=row["org_id"] or None)
    if out is None:
        raise Denied(404)
    return out


def obj_node_unshare(c, uid, n, sid, kind=None, ref_id=None, org=None, reason="unshare"):
    """2.565.0 (#4717): take share sid of reference node n (a row) back -- obj_unshare's step, also for the old areas of stage
    4 (the caller checked who may): the row goes into obj_revoked (restorable for OBJ_REVOKED_DAYS) and is deleted. Returns
    the obj_revoked id, None when node n has no such share."""
    s = c.execute("SELECT * FROM fs_shares WHERE id=? AND node_id=?", (int(sid), n["id"] if n else 0)).fetchone()
    if not s:
        return None
    _revoked_prune(c)
    out = _revoked_add(c, "fs_shares", s, reason, uid, org=org, uid=s["user_id"] or s["agent_id"], kind=kind, ref_id=ref_id)
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
    reg = obj_reg(kind)
    n = obj_node(c, uid, kind, rid, make=True)
    if n is None:
        raise Denied(404)  # #4739: an area that places its nodes itself has none for it
    # 2.568.0 (#4739): with an on_restore hook the area checks the target under its own rules (below); review F2: only for
    # the area's own rows of a person / an agent (lists: list_own) -- any other row (the file store's share on the node, a
    # group) takes the core's way
    own = reg["on_restore"] is not None and ("list_own" not in reg["share_cols"] or bool(s.get("list_own")))
    if own and key == "group_id":
        raise Denied(409, tr("Only people, groups and agents of the same workspace can get a share"))
    if not key or (not own and not _pool_ok(c, n, key, int(s[key]), uid)):
        raise Denied(409, tr("Only people, groups and agents of the same workspace can get a share"))
    extra = {k: s.get(k) for k in reg["share_cols"] if k in s}
    mq, ma = _share_match(reg, extra)
    if c.execute(f"SELECT 1 FROM fs_shares WHERE node_id=? AND {key}=?{mq}", (n["id"], int(s[key]), *ma)).fetchone():
        c.execute("DELETE FROM obj_revoked WHERE id=?", (r["id"],))
        c.commit()  # 2.568.0 (#4739): the stale row goes for good (a refusal is not committed; both routes wrote nothing before)
        raise Denied(409, tr("Already shared"))
    sid = insert_id(c, f"INSERT INTO fs_shares(node_id,{key},role,expires_at,created_by,created_at,by_role) VALUES(?,?,?,?,?,?,?)",
                    (n["id"], int(s[key]), s.get("role") if s.get("role") in ("view", "edit") else "view", s.get("expires_at"),
                     s.get("created_by"), s.get("created_at") or iso(now_utc()), s.get("by_role")))
    for k, v in extra.items():
        c.execute(f"UPDATE fs_shares SET {k}=? WHERE id=?", (v, sid))
    c.execute("DELETE FROM obj_revoked WHERE id=?", (r["id"],))
    obj_forget()
    if not own:  # 2.654.0 (#5050): like obj_share -- the node's history and its hooks (lists: _on_change -> grp_sync gives the role)
        fs_log_add(c, n["id"], "share", f"{key[:-3]}:{int(s[key])}:{s.get('role') if s.get('role') in ('view', 'edit') else 'view'}")
    if own:
        s2 = dict(s, id=sid)
        reg["on_restore"](c, uid, int(rid), s2)
    elif reg.get("on_share_back"):  # 2.924.0 (#5069, fable F3): a calendar's / book's side effects (touch, News), the core checked
        reg["on_share_back"](c, uid, int(rid), dict(s, id=sid))
    return sid


def obj_shares(c, uid, kind, rid):
    """{shares: the object's own, inherited: those of the folders above (read-only here), revoked: taken back, restorable}
    -- for who manages the object."""
    obj_need(c, uid, kind, rid, "manage")
    n = obj_node(c, uid, kind, rid)
    if n is None:
        own, inh = [], []
    else:
        own, inh = _shares(c, n["id"], own=True), _inherited_shares(c, fs_chain(c, n["id"]))  # #4739: + an area's own
    rev = []
    for r in c.execute("SELECT * FROM obj_revoked WHERE src='fs_shares' AND kind=? AND ref_id=? ORDER BY id DESC LIMIT 50", (kind, int(rid))):
        s = json.loads(r["row_json"])
        rev.append({"id": r["id"], "user_id": s.get("user_id"), "group_id": s.get("group_id"), "agent_id": s.get("agent_id"),
                    "role": s.get("role"), "reason": r["reason"], "at": r["created_at"]})
    return {"shares": own, "inherited": inh, "revoked": rev}


# ---------------------------------------------------------------- 2.565.0 (#4719): shares an area keeps itself (listed=False)
def obj_gate(c, uid, kind, row):
    """Steps 1 + 2 of obj_role for a row the area read itself (its listing): the organisation floor, an agent of another
    workspace, hidden, the data lock, a token's list limit. False = no role at all, whatever the area's own rule says."""
    reg = OBJ.get(kind or "")
    return bool(reg and uid and row is not None and _gate(c, uid, reg, row))


def obj_token_lists(uid):
    """The list limit of the request's own API token when uid asks through it (None: no limit / not uid's request) -- step 2
    of obj_role for an area that lists its objects itself: an object without a list_id is out then."""
    return _req_token_lists(uid)


def obj_share_rows_sql(kind, trash=False):
    """The live shares of the reference nodes of kind as an SQL subquery (no ? parameters) with the columns ref_id, user_id,
    group_id, agent_id, role, created_by -- for an area that reads its members in bulk (team chat: collab/teamchan.py
    tcx_members_of). Not in the trash, not expired; the area applies its own rules to the people it names. 2.647.0 (#5046,
    review): trash=True also counts nodes in the trash (a check that holds back while a share could come back)."""
    reg = obj_reg(kind)
    now = now_iso().replace("'", "")
    return (f"(SELECT n.ref_id, s.user_id, s.group_id, s.agent_id, s.role, s.created_by FROM fs_shares s JOIN fs_nodes n ON n.id = s.node_id "
            f"WHERE n.kind = 'ref' AND n.ref_kind = '{reg['kind']}'{'' if trash else ' AND n.deleted_at IS NULL'} "
            f"AND (s.expires_at IS NULL OR s.expires_at > '{now}'))")


def _unlisted(kind):
    reg = obj_reg(kind)
    if reg.get("listed", True):
        raise ValueError(f"obj_member_put / obj_member_take {kind}: only for kinds registered with listed=False")
    return reg


def obj_member_put(c, by, kind, rid, key, target, role="edit"):
    """The area decided by its OWN rule (team chat: tcx_may_add, who may manage the room) that target joins the object: the
    share row on its reference node (made at the top of its workspace when missing); the same target again changes the role.
    No pool check of the file store (a group conversation spans workspaces) -- hence only for kinds with listed=False, whose
    node lies in no folder. key user_id | group_id | agent_id. Returns the share id. The caller commits."""
    _unlisted(kind)
    if key not in ("user_id", "group_id", "agent_id") or role not in ("view", "edit"):
        raise BadInput(tr("Invalid data"))
    with system_ctx(c):  # the node of a room of an organisation / of another person's space is structure (the area checked)
        n = obj_node(c, by, kind, rid, make=True)
        old = c.execute(f"SELECT id, role FROM fs_shares WHERE node_id=? AND {key}=?", (n["id"], int(target))).fetchone()
        if old:
            if old["role"] != role:
                c.execute("UPDATE fs_shares SET role=? WHERE id=?", (role, old["id"]))
            sid = old["id"]
        else:
            if c.execute("SELECT COUNT(*) FROM fs_shares WHERE node_id=?", (n["id"],)).fetchone()[0] >= OBJ_SHARE_MAX:
                raise Denied(409, tr("Too many shares"))
            sid = insert_id(c, f"INSERT INTO fs_shares(node_id,{key},role,created_by,created_at,by_role) VALUES(?,?,?,?,?,?)",
                            (n["id"], int(target), role, by, iso(now_utc()), _by_role(c, by, n["org_id"]) if by else None))
    obj_forget()
    return sid


def obj_member_take(c, by, kind, rid, key, targets, reason="unshare"):
    """The shares of targets (ids of key user_id | group_id | agent_id) on the object's node go into obj_revoked (restorable
    for OBJ_REVOKED_DAYS, obj_share_restore). Returns their number. The caller commits."""
    _unlisted(kind)
    if key not in ("user_id", "group_id", "agent_id") or reason not in OBJ_REASONS:
        raise ValueError("obj_member_take: invalid key / reason")
    ids = sorted({int(x) for x in targets or ()})
    if not ids:
        return 0
    with system_ctx(c):  # the area checked who may take whom out
        n = fs_ref_node(c, kind, rid)
        if n is None:
            return 0
        _revoked_prune(c)
        q = ",".join("?" * len(ids))
        out = _take(c, "fs_shares", f"node_id=? AND {key} IN ({q})", (n["id"], *ids), reason, by, n["org_id"] or None, "user_id", kind=kind)
    obj_forget()
    return out


# ---------------------------------------------------------------- 2.924.0 (#5069): a calendar's / address book's own dialog
def obj_node_person_put(c, by, n, target, role):
    """The share of person / agent target on reference node n (a row; a kind with node_shares) after the area's own dialog
    checked who may share and with whom (events/model.py cal_member_set, contacts/model.py book_member_set): it replaces the
    old member row of stage 3. The same target again changes the role of each of its rows on the node; a row whose end date
    has passed comes back without one (sharing anew lets the person in again, #5089), a still valid end date (given in the
    file store's dialog) stays. Returns True when the target had no row on the node (a new member: the area's News). The
    caller commits."""
    if role not in ("view", "edit"):
        raise BadInput(tr("Invalid data"))
    u = c.execute("SELECT kind FROM users WHERE id=?", (int(target),)).fetchone()
    key = "agent_id" if u is not None and (u[0] or "user") == "agent" else "user_id"
    now = iso(now_utc())
    with system_ctx(c):  # the node may lie in an organisation's tree; the area checked the right
        n_old = c.execute("UPDATE fs_shares SET role=?, expires_at=CASE WHEN expires_at IS NOT NULL AND expires_at<=? THEN NULL "
                          "ELSE expires_at END WHERE node_id=? AND (user_id=? OR agent_id=?)",
                          (role, now, n["id"], int(target), int(target))).rowcount
        if not n_old:
            insert_id(c, f"INSERT INTO fs_shares(node_id,{key},role,created_by,created_at,by_role) VALUES(?,?,?,?,?,?)",
                      (n["id"], int(target), role, by, now, _by_role(c, by, n["org_id"]) if by else None))
        fs_log_add(c, n["id"], "share", f"{key[:-3]}:{int(target)}:{role}")
    obj_forget()
    return not n_old


def obj_node_person_drop(c, kind, rid, who):
    """Person / agent who leaves the object of kind (its own dialog: the owner takes them out, or they leave): every share row
    of theirs on its reference node goes (deleted, as the old member row went; no obj_revoked: the dialog shares anew).
    Returns the number of rows. The caller checked the right and commits."""
    out = obj_share_gone(c, kind, rid, who)
    obj_forget()
    return out


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


_PUBLIC = (("fs_ext_links", "label", ("owner",), ""), ("fs_upload_requests", "title", ("owner", "edit"), " AND deleted_at IS NULL"))


def _take_public(c, sql, args, reason, by, org, uid=None):
    """2.649.0 (#5051): the public links of the file store (fs_ext_links) and file requests (fs_upload_requests) matching sql
    die (revoked_at) and go into obj_revoked (src = the table, ref_id = the row's id; no token in row_json). uid given (a
    role change): only the rows whose node uid can no longer share (links) / write in (requests). Restorable as before:
    files/extlinks.py xl_restore, files/filereq.py frq_update revoked=false (both drop the obj_revoked row). {table: n}."""
    out, at = {}, iso(now_utc())
    for src, tcol, keep, more in _PUBLIC:
        rows = c.execute(f"SELECT id, node_id, org_id, created_by, {tcol} AS t FROM {src} WHERE revoked_at IS NULL{more} AND {sql}",
                         args).fetchall()
        if uid is not None:
            rows = [r for r in rows if fs_role(c, r["node_id"], int(uid)) not in keep]
        for r in rows:
            c.execute(f"UPDATE {src} SET revoked_at=? WHERE id=?", (at, r["id"]))
            _revoked_add(c, src, {"id": r["id"], "node_id": r["node_id"], "org_id": r["org_id"], "created_by": r["created_by"],
                                  "title": r["t"]}, reason, by, org=org, uid=r["created_by"], ref_id=r["id"])
        out[src] = len(rows)
    return out


def _agents_of(c, uid):
    return [r[0] for r in c.execute("SELECT user_id FROM agents WHERE owner_id=?", (int(uid),)).fetchall()]


def _actor():
    u = getattr(g, "user", None) if has_request_context() else None
    return u["id"] if u is not None else None


def obj_revoke_person(c, uid, org, reason, heir=None, role=None):
    """What a person (and their agents) loses in one place (module docstring); runs beside the old loops of org_leave /
    org_member_put / odl_retire / the account deletion, which stay as they are. Returns {what: number of rows}."""
    if reason not in OBJ_REASONS or reason in ("unshare", "expired", "boundary"):  # the two of one share (obj_unshare, an area's expiry); #5051: obj_boundary_take
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
            # 2.649.0 (#5051): their public links and file requests in the organisation die (coming back, also as a guest = still dead)
            out.update(_take_public(c, "created_by=? AND org_id=?", (int(uid), int(org)), reason, by, int(org)))
            ug_drop(c, "user_id=? AND org_id=?", (int(uid), int(org)))  # 2.747.0 (#5249): the step groups there with their parts
            c.execute("DELETE FROM obj_undo WHERE user_id=? AND org_id=?", (int(uid), int(org)))
            if heir and heir != uid:
                for reg in OBJ.values():
                    if reg["base_role"] is None:  # the default rules: the organisation's object stays with it, the heir owns it
                        c.execute(f"UPDATE {reg['table']} SET owner_id=? WHERE org_id=? AND owner_id=?", (int(heir), int(org), int(uid)))
        elif reason == "role" and uid and org:
            # 2.649.0 (#5051): the public links / file requests of a node they can no longer share / write in die
            out.update(_take_public(c, "created_by=? AND org_id=?", (int(uid), int(org)), reason, by, int(org), uid=uid))
            if role in ("guest", "accounting"):  # F5 (#2822): the open channels they had joined
                # 2.565.0 (#4719): like #4698 b (accounts/orgs.py org_open_chan_off) every row of them and their personal agents,
                # and their shares on those rooms' nodes too (the core's members) -- restorable, nothing stays to reopen the room
                ppl = [int(uid), *_agents_of(c, uid)]
                q = ",".join("?" * len(ppl))
                rooms = "SELECT id FROM tchat_rooms WHERE org_id=? AND kind='channel' AND is_open=1"
                out["fs_shares"] = _take(c, "fs_shares", f"(user_id IN ({q}) OR agent_id IN ({q})) AND node_id IN (SELECT id FROM fs_nodes "
                                         f"WHERE kind='ref' AND ref_kind='tchat_room' AND ref_id IN ({rooms}))",
                                         (*ppl, *ppl, int(org)), reason, by, int(org), "user_id")
        elif reason == "retire" and org:
            # 2.566.0 (#4712, review F1): the shares of the owner's own agents on a calendar's / book's node stay (their delegates,
            # 2.924.0, #5069: their old member rows are gone): the node follows the object into the owner's private tree (orgretain.obj_nodes_follow)
            keep = "".join(f" AND NOT EXISTS (SELECT 1 FROM fs_nodes n JOIN {r['table']} k ON k.id=n.ref_id JOIN agents a ON "
                           f"a.user_id=fs_shares.agent_id AND a.owner_id=k.owner_id WHERE n.id=fs_shares.node_id AND n.kind='ref' "
                           f"AND n.ref_kind='{r['kind']}')" for r in OBJ.values() if r["node_shares"])
            out["fs_shares"] = _take(c, "fs_shares", "node_id IN (SELECT id FROM fs_nodes WHERE org_id=?)" + keep, (int(org),), reason, by,
                                     int(org), "user_id")
            # 2.924.0 (#5069): the rooms' members are the shares above (tchat_members is no member table any more)
            out.update(_take_public(c, "org_id=?", (int(org),), reason, by, int(org)))  # 2.649.0 (#5051)
            ug_drop(c, "org_id=?", (int(org),))  # 2.747.0 (#5249)
            c.execute("DELETE FROM obj_undo WHERE org_id=?", (int(org),))
        elif reason == "delete" and uid:
            for reg in OBJ.values():  # review F1: an organisation's object stays with it, the heir owns it (owner_id cascades)
                if reg["base_role"] is None:
                    out[reg["kind"]] = 0
                    for (o,) in c.execute(f"SELECT DISTINCT org_id FROM {reg['table']} WHERE owner_id=? AND org_id IS NOT NULL", (int(uid),)).fetchall():
                        h = upg_heir(c, o, uid)
                        if h:
                            out[reg["kind"]] += c.execute(f"UPDATE {reg['table']} SET owner_id=? WHERE org_id=? AND owner_id=?",
                                                          (int(h), int(o), int(uid))).rowcount
            for reg in OBJ.values():  # 2.565.0 (#4719): a node that only carries shares (a room) stays with the next person in it
                if not reg.get("listed", True):
                    for n in c.execute("SELECT id FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND owner_id=?", (reg["kind"], int(uid))).fetchall():
                        nxt = c.execute("SELECT MIN(s.user_id) FROM fs_shares s JOIN users u ON u.id=s.user_id WHERE s.node_id=? AND s.user_id!=? "
                                        "AND COALESCE(u.kind,'')!='agent'", (n["id"], int(uid))).fetchone()[0]
                        if nxt:
                            c.execute("UPDATE fs_nodes SET owner_id=? WHERE id=?", (int(nxt), n["id"]))
            ug_drop(c, "user_id=?", (int(uid),))  # 2.747.0 (#5249)
            c.execute("DELETE FROM obj_undo WHERE user_id=?", (int(uid),))
            c.execute("UPDATE obj_history SET user_id=NULL WHERE user_id=?", (int(uid),))
            c.execute("UPDATE obj_revoked SET by_id=NULL WHERE by_id=?", (int(uid),))
            c.execute("DELETE FROM obj_revoked WHERE user_id=?", (int(uid),))
    for reg in list(OBJ.values()):  # 2.568.0 (#4739): an old area's own role table (lists: list_members through groups)
        if reg["on_revoke"]:
            out.update(reg["on_revoke"](c, uid, org, reason, role=role) or {})
    obj_forget()
    return out


# ---------------------------------------------------------------- 2.649.0 (#5051): the nightly boundary repair through the core
def _boundary_share(c, n, s):
    """Share row s of node n (a person outside the node's organisation) goes the way the file store's dialog takes it back
    (files/web.py files_share_delete): a core object's node -> obj_revoked under its kind + its old member row (calendar,
    address book, room); a table's / a knowledge page's card -> the area's hook (card ended, core share in obj_revoked); any
    other node -> obj_revoked without a kind. Returns 1."""
    if n is not None and n["kind"] == "ref" and n["ref_kind"] in OBJ:
        reg = OBJ[n["ref_kind"]]
        obj_node_unshare(c, None, n, s["id"], kind=reg["kind"], ref_id=n["ref_id"], org=n["org_id"] or None, reason="boundary")
        if s["user_id"]:
            _boundary_old(c, reg, n["ref_id"], s["user_id"], n["org_id"] or None)
    else:
        # 2.649.0 (#5051, Fable 2): the hooks write the repair's reason themselves (no renaming afterwards)
        if not (n is not None and any(f(c, None, n, s, reason="boundary") for f in fs_unshare_hooks)):
            _take(c, "fs_shares", "id=?", (s["id"],), "boundary", None, (n["org_id"] if n is not None else None) or None, "user_id")
    return 1


def _boundary_old(c, reg, rid, uid, org):
    """The old member row of core object rid of person uid. 2.924.0 (#5069): none any more -- a room's, a calendar's and an
    address book's members are the shares of its node (tchat_members, ev_cal_members and book_members are gone)."""
    return 0


def obj_boundary_take(c, table, oid, uid):
    """accounts/tenancy.py boundary_repair (core/objhooks.BOUNDARY): person uid's rows of table on the given object -- a person no
    member of the object's organisation -- go through the core instead of a bare DELETE: into obj_revoked (restorable for
    OBJ_REVOKED_DAYS), and both sides of a share that has a card / an old member row (the core share on the reference node
    and the area's row), so neither side reopens the other. None = not a table of the core (the caller deletes as before)."""
    oid, uid = int(oid), int(uid)
    with system_ctx(c):  # a nightly round over every organisation
        _revoked_prune(c)
        if table == "fs_shares":
            n = c.execute("SELECT * FROM fs_nodes WHERE id=?", (oid,)).fetchone()
            out = sum(_boundary_share(c, n, s) for s in c.execute("SELECT * FROM fs_shares WHERE node_id=? AND user_id=?", (oid, uid)).fetchall())
        elif table == "sheet_shares":  # the card and its core share (sheets/shshare.py shs_leave, one table)
            out = 0
            for x in c.execute("SELECT * FROM sheet_shares WHERE sheet_id=? AND user_id=? AND revoked_at IS NULL", (oid, uid)).fetchall():
                n = c.execute("SELECT n.* FROM fs_nodes n JOIN fs_shares f ON f.node_id=n.id WHERE f.id=?", (x["core_id"],)).fetchone() \
                    if x["core_id"] else None
                if n is not None:
                    obj_node_unshare(c, None, n, x["core_id"], kind="sheet", ref_id=oid, org=x["org_id"] or None, reason="boundary")
                if x["email_key"]:  # 2.360.2 M (#2561): an address row stays listed, open again (no account, no right)
                    c.execute("UPDATE sheet_shares SET user_id=NULL, core_id=NULL WHERE id=?", (x["id"],))
                else:
                    c.execute("UPDATE sheet_shares SET revoked_at=? WHERE id=?", (iso_ms(now_utc()), x["id"]))
                out += 1
        else:
            # 2.924.0 (#5069): a calendar's / book's member is the share of its node: tenancy REPAIR names the kind (evcal |
            # address_book) instead of the gone member table
            reg = OBJ[table] if table in OBJ and OBJ[table]["node_shares"] else None
            if reg is None:
                return None
            org = c.execute(f"SELECT org_id FROM {reg['table']} WHERE id=?", (oid,)).fetchone()
            org = (org[0] if org else None) or None
            out = _boundary_old(c, reg, oid, uid, org)
            out += _take(c, "fs_shares", "user_id=? AND node_id IN (SELECT id FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id=?)",
                         (uid, reg["kind"], oid), "boundary", None, org, "user_id", kind=reg["kind"])
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


BOUNDARY.append(obj_boundary_take)  # 2.649.0 (#5051): accounts/tenancy.py boundary_repair
REVOKE.append(obj_revoke_person)  # core/objhooks.person_revoked (accounts calls it without importing the domain layer)
FOLLOW.append(obj_node_follow)  # 2.566.0 (#4712, review F1): accounts/orgretain.py obj_nodes_follow


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
                 hidden=lambda c, uid: "(SELECT id FROM obj_probe WHERE title ILIKE 'hide%')", dl_area="contracts",
                 # 2.773.0 (#5292): with KALMIDO_TEST_OBJ_PARTS=1 (tests/p2773_b_trash_core_test.py) its parts (table
                 # obj_probe_part, made by that suite) are its children, and the core's retention run takes its trash
                 **({"children": (("obj_probe_part", "probe_id"),), "trash_prune": True} if os.environ.get("KALMIDO_TEST_OBJ_PARTS") == "1" else {}))
    if os.environ.get("KALMIDO_TEST_OBJ_PARTS") == "1":  # 2.778.0 (#5371): a kind whose writers may trash (table obj_probe_e)
        obj_register("objprobe_e", "obj_probe_e", label="Test object", area="other", fields={"title": f_text(120, required=True)},
                     trash_role="edit")


_probe_register()
