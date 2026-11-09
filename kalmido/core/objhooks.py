"""2.558.0 (#4709): the two things of the shared core that the layer accounts needs, without importing upward.

core/objects.py (the shared core, layer domain: it stands on the file store's register) fills them when it loads; kalmido's
package import loads every module of ORDER, so they are always filled before a request or a command runs (the same pattern
as core/instance.UPDATE_KICK).
  OBJ     kind -> the registered hooks of obj_register (accounts/orgretain.py reads it: the heir of an account's objects)
  START   2.565.0 (#4717 #4719): (key, once, f(c)) that core/db.init_db runs at every start (once: only until gsetting key is "1") -
          the areas' forward copies onto the shared core, without core/db importing the areas
  REVOKE  the functions f(c, uid, org, reason, heir=None, role=None) of what a person loses (core/objects.obj_revoke_person)
  FOLLOW  f(c, kind, rid): the object's reference node follows it into its new workspace (core/objects.obj_node_follow,
          2.566.0 #4712 review F1: accounts/orgretain.py obj_nodes_follow)
"""
from .pg import system_ctx

OBJ = {}
START = []
REVOKE = []
SETTLE = []  # 2.568.0 (#4739): f(c, kind, rid) -- an area's own core rows follow its member table again (lists/lmcore.py)
FOLLOW = []
BOUNDARY = []  # 2.649.0 (#5051): f(c, table, object id, user id) -> rows taken | None (core/objects.obj_boundary_take)
GONE = {}  # review 2.578 F2: kind -> table of an area's kind outside OBJ whose rows in obj_revoked / obj_history / obj_undo go
#            with its objects when an account goes (contacts: contacts/ctfolder.py, cascade over their book)


def person_revoked(c, uid, org, reason, heir=None, role=None):
    """What a person loses when they leave an organisation, change role, the organisation retires or the account goes
    (accounts/orgs.py, accounts/users.py, accounts/orgretain.py call it). {what: number of rows} of every hook."""
    out = {}
    for f in REVOKE:
        out.update(f(c, uid, org, reason, heir=heir, role=role) or {})
    return out


def obj_boundary(c, table, oid, uid):
    """2.649.0 (#5051): the nightly boundary repair (accounts/tenancy.py) takes a row through the core (obj_revoked, both
    sides of a card). None = no hook knows the table: the caller deletes as before."""
    for f in BOUNDARY:
        n = f(c, table, oid, uid)
        if n is not None:
            return n
    return None


def obj_settle(c, kind, rid):
    """2.568.0 (#4739, review F1): the members of an object changed outside its area (accounts/orgs.py ol_private: the
    organisation's agents leave a project that turns private) -- the area's own share rows of the core follow (restorable)."""
    for f in SETTLE:
        f(c, kind, rid)


def obj_private_refs(c, uid):
    """2.578.0 (#4796): before account uid goes (accounts/users.py _user_purge) -- [(kind, id)] of the core objects that may go
    with it and have rows in obj_history / obj_undo / obj_revoked. obj_gone_drop takes those that really went afterwards.
    Review 2.578 F2/F3: a kind with the default columns: its private objects of uid (also in the trash); a kind with its own
    space hook (channels) and the kinds of GONE (contacts): every object with rows, one query and no hook per object --
    complete also for objects in the trash or of a deactivated owner, whose space a hook does not name any more."""
    out = []
    kinds = list(OBJ.values()) + [{"kind": k, "table": t, "space": "own"} for k, t in GONE.items() if k not in OBJ]
    with system_ctx(c):  # structure: also the rows other people wrote on the object
        for reg in kinds:
            k, t = reg["kind"], reg["table"]
            refs = ("(SELECT ref_id FROM obj_history WHERE kind=? UNION SELECT ref_id FROM obj_undo WHERE kind=? "
                    "UNION SELECT ref_id FROM obj_revoked WHERE kind=? AND ref_id IS NOT NULL)")
            if reg["space"] is None:  # the default columns of a kind's table (core/objects.py obj_space)
                ids = [r[0] for r in c.execute(f"SELECT t.id FROM {t} t WHERE t.org_id IS NULL AND t.owner_id=? AND t.id IN {refs}",
                                               (int(uid), k, k, k)).fetchall()]
            else:
                ids = [r[0] for r in c.execute(f"SELECT t.id FROM {t} t WHERE t.id IN {refs}", (k, k, k)).fetchall()]
            out += [(k, int(i)) for i in ids]
    return out


def obj_gone_drop(c, refs):
    """2.578.0 (#4796): after the account's deletion -- the history, undo steps and revoked shares of those of refs
    (obj_private_refs) whose object went with the account, like obj_purge. An object that still exists (handed on by
    admin/purgeshare.py, shared, an organisation's, somebody else's) stays and keeps its rows. Per kind in sets (review 2.578
    F3). Returns the number of rows deleted. One-way: the rows are gone for good."""
    by = {}
    for k, i in refs:
        by.setdefault(k, []).append(int(i))
    n = 0
    for k, ids in by.items():
        t = OBJ[k]["table"] if k in OBJ else GONE.get(k)
        if t:
            n += obj_rows_drop_many(c, k, ids, gone=t)
    return n


def obj_rows_drop_many(c, kind, ids, gone=None):
    """The rows in obj_history / obj_undo / obj_revoked of the objects ids of kind, 500 at a time; gone = the kind's table:
    only of those whose row is not there any more. Returns the number of rows deleted. One-way."""
    from .pg import qi, table_names
    from .undogroups import ug_gc, ug_gids  # 2.747.0 (#5249)
    ids = sorted({int(i) for i in ids})
    n = 0
    with system_ctx(c):  # also the rows other people wrote on the object
        for at in range(0, len(ids), 500):
            part = ids[at:at + 500]
            q = ",".join("?" * len(part))
            cg = f" AND NOT EXISTS (SELECT 1 FROM {qi(gone, table_names(c))} g WHERE g.id=obj_undo.ref_id)" if gone else ""
            gids = ug_gids(c, f"kind=? AND ref_id IN ({q}){cg}", [kind] + part)  # 2.747.0 (#5249): their step groups
            for t in ("obj_history", "obj_undo", "obj_revoked"):
                cond = f" AND NOT EXISTS (SELECT 1 FROM {gone} g WHERE g.id={t}.ref_id)" if gone else ""
                n += c.execute(f"DELETE FROM {t} WHERE kind=? AND ref_id IN ({q}){cond}", [kind] + part).rowcount
            ug_gc(c, gids)
    return n


def obj_rows_drop(c, kind, rid):
    """2.578.0 (#4796): an object deleted for good -- its rows in obj_history / obj_undo / obj_revoked go with it (as
    core/writes.py obj_purge; for the old areas' own deletion: lists/lists.py list_purge, contacts/web.py op_book_purge).
    Returns the number of rows deleted. One-way."""
    from .undogroups import ug_gc, ug_gids  # 2.747.0 (#5249): their step groups (a group left without parts goes)
    n = 0
    with system_ctx(c):  # also the rows other people wrote on the object
        gids = ug_gids(c, "kind=? AND ref_id=?", (kind, int(rid)))
        for t in ("obj_history", "obj_undo", "obj_revoked"):
            n += c.execute(f"DELETE FROM {t} WHERE kind=? AND ref_id=?", (kind, int(rid))).rowcount
        ug_gc(c, gids)
    return n
