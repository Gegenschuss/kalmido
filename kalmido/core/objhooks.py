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


def person_revoked(c, uid, org, reason, heir=None, role=None):
    """What a person loses when they leave an organisation, change role, the organisation retires or the account goes
    (accounts/orgs.py, accounts/users.py, accounts/orgretain.py call it). {what: number of rows} of every hook."""
    out = {}
    for f in REVOKE:
        out.update(f(c, uid, org, reason, heir=heir, role=role) or {})
    return out


def obj_settle(c, kind, rid):
    """2.568.0 (#4739, review F1): the members of an object changed outside its area (accounts/orgs.py ol_private: the
    organisation's agents leave a project that turns private) -- the area's own share rows of the core follow (restorable)."""
    for f in SETTLE:
        f(c, kind, rid)


def obj_private_refs(c, uid):
    """2.578.0 (#4796): before account uid goes (accounts/users.py _user_purge) -- [(kind, id)] of its PRIVATE core objects
    (no organisation, owner uid) that have rows in obj_history / obj_undo / obj_revoked. obj_gone_drop takes them afterwards."""
    out = []
    with system_ctx(c):  # structure: also the rows other people wrote on the object
        for reg in list(OBJ.values()):
            k, t = reg["kind"], reg["table"]
            refs = ("(SELECT ref_id FROM obj_history WHERE kind=? UNION SELECT ref_id FROM obj_undo WHERE kind=? "
                    "UNION SELECT ref_id FROM obj_revoked WHERE kind=? AND ref_id IS NOT NULL)")
            if reg["space"] is None:  # the default columns of a kind's table (core/objects.py obj_space)
                ids = [r[0] for r in c.execute(f"SELECT t.id FROM {t} t WHERE t.org_id IS NULL AND t.owner_id=? AND t.id IN {refs}",
                                               (int(uid), k, k, k)).fetchall()]
            else:
                ids = [r[0] for r in c.execute(f"SELECT t.id FROM {t} t WHERE t.id IN {refs}", (k, k, k)).fetchall()
                       if (sp := reg["space"](c, int(r[0]))) and not sp[0] and sp[1] == int(uid)]
            out += [(k, int(i)) for i in ids]
    return out


def obj_gone_drop(c, refs):
    """2.578.0 (#4796): after the account's deletion -- the history, undo steps and revoked shares of those of refs
    (obj_private_refs) whose object went with the account, like obj_purge. A private object handed on (admin/purgeshare.py)
    stays and keeps its rows (user_id NULL). Returns the number of rows deleted. One-way: the rows are gone for good."""
    n = 0
    with system_ctx(c):
        for k, i in refs:
            reg = OBJ.get(k)
            if reg is None or c.execute(f"SELECT 1 FROM {reg['table']} WHERE id=?", (int(i),)).fetchone():
                continue
            n += obj_rows_drop(c, k, i)
    return n


def obj_rows_drop(c, kind, rid):
    """2.578.0 (#4796): an object deleted for good -- its rows in obj_history / obj_undo / obj_revoked go with it (as
    core/writes.py obj_purge; for the old areas' own deletion: lists/lists.py list_purge, contacts/web.py op_book_purge).
    Returns the number of rows deleted. One-way."""
    n = 0
    with system_ctx(c):  # also the rows other people wrote on the object
        for t in ("obj_history", "obj_undo", "obj_revoked"):
            n += c.execute(f"DELETE FROM {t} WHERE kind=? AND ref_id=?", (kind, int(rid))).rowcount
    return n
