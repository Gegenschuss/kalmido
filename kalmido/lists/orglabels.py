"""2.609.0 (#3373): labels of an organisation -- project tags defined once for every project of the organisation (org_tags).
In a project they are project tags linked to the label (list_tags.org_tag_id): made the first time a task of the project gets
the label (collab/reactions.py ltag_get_or_create, also for people who may not make new project tags), renamed and recoloured
with the label, kept as plain project tags when the label is deleted. Personal tags (task_tags) stay private and unchanged; the
app shows the three kinds apart. Only the organisation's admins change its labels; the labels of another organisation are never
offered (the app state lists only the labels of organisations whose projects the person sees).

2.947.0 (#5275, stage Q5a, decided 08.11.2026): a label is a tag of the core (core/objtags.py, obj_tags scope org) and sits on
the task itself -- no copy per project any more; a rename / new colour reaches every task at once. A new label takes over the
project tags of the same name in the organisation's projects (their tasks get the label, the project tag goes). A deleted label
leaves its tasks as plain project tags of their projects (as before)."""
import re

from flask import g, has_request_context, jsonify, request

from ..core.config import app
from ..core.pg import qi, write_lock
from ..core.i18n import tr
from ..core.db import body, bump, db, err
from ..core.objtags import otg_add, otg_find, otg_link, otg_merge, otg_rekey_refs
from ..accounts.session import me
from ..core.access import Denied
from ..core.errors import BadInput
from ..accounts.orgs import is_org_admin
from ..accounts.orgroles import org_writes, user_orgs_full
from ..lists.lists import clean_color

OLB_MAX = 200  # labels per organisation
OLB_NAME_MAX = 60


def olb_need_person():
    u = getattr(g, "user", None) if has_request_context() else None
    try:
        agent = bool(u) and (u["kind"] or "user") == "agent"
    except (KeyError, IndexError):
        agent = False
    if agent or (has_request_context() and g.get("auth_via") == "token"):
        raise Denied(403, tr("The labels of an organisation are only managed in the app"))


def olb_name(v):
    n = re.sub(r"[\x00-\x1f]", "", str(v or "")).strip().lstrip("#").strip() if isinstance(v, str) else ""
    if not n or len(n) > OLB_NAME_MAX:
        raise BadInput(tr("Invalid value: {0}", tr("Tag")))
    return n


def olb_admin(c, uid, oid):
    if oid not in user_orgs_full(c, uid):
        raise Denied(404)
    if not (org_writes(c, uid, oid) and is_org_admin(c, uid, oid)):
        raise Denied(403, tr("Only an administrator of the organisation can change its labels"))


def olb_get(c, uid, lbid):
    r = c.execute("SELECT * FROM obj_tags WHERE id=? AND scope_kind='org'", (lbid,)).fetchone()
    if not r:
        raise Denied(404)
    olb_admin(c, uid, r["org_id"])
    return r


def olb_out(c, r):
    """lists = the projects whose tasks carry the label."""
    return {"id": r["id"], "org_id": r["org_id"], "name": r["name"], "color": r["color"], "sort": r["sort"],
            # review F1: only projects of the label's organisation (a link left on a task of another one is not shown)
            "lists": c.execute("""SELECT COUNT(DISTINCT t.list_id) FROM obj_tag_links k JOIN tasks t ON t.id=k.obj_id
                                  JOIN lists l ON l.id=t.list_id AND l.org_id=? WHERE k.tag_id=? AND k.kind='task'""",
                               (r["org_id"], r["id"])).fetchone()[0]}


def olb_full(c, uid=None):
    """Review F4 (2.947.0): what a reader may see of the labels, for core/objtags.py otg_list_sql / otg_in_list (full=): True
    outside a request with a person (the server's own work), else the organisations the person fully sees (user_orgs_full) --
    a label of another organisation of a project only where a task of the project carries it."""
    if uid is None:
        u = getattr(g, "user", None) if has_request_context() else None
        if not u:
            return True
        uid = u["id"]
    return user_orgs_full(c, uid)


def olb_match(c, lid, name):
    """The label of list lid's organisation named name (any case), or None (a list without an organisation: never).
    2.609.0 (#3373, review F3): only for a person with the full view of that organisation -- a guest / accounting person who
    may tag in a shared project gets a plain project tag, so the labels' names are no oracle for them. 2.947.0 (#5275): or a
    label a task of the project carries already (they see it on that task, as they saw the project's copy before)."""
    r = c.execute("""SELECT o.* FROM obj_tags o JOIN lists l ON l.org_id=o.org_id WHERE l.id=? AND o.scope_kind='org'
                     AND lower(o.name)=lower(?)""", (lid, name)).fetchone()
    if not r:
        return None
    full = olb_full(c)  # 2.947.0 (#5275, review F1): no me() -- the git issue sync calls this outside a request
    if full is True or r["org_id"] in full:
        return r
    used = c.execute("""SELECT 1 FROM obj_tag_links k JOIN tasks t ON t.id=k.obj_id AND k.kind='task'
                        WHERE k.tag_id=? AND t.list_id=? LIMIT 1""", (r["id"], lid)).fetchone()
    return r if used else None


@app.get("/api/org-labels")
def olb_index():
    """?org_id: the labels of one organisation the person fully sees (else of all of them) -> {labels: [...]}."""
    olb_need_person()
    c, uid = db(), me()
    orgs = user_orgs_full(c, uid)
    want = request.args.get("org_id")
    if want not in (None, ""):
        try:
            orgs = [o for o in orgs if o == int(want)]
        except ValueError:
            return err(tr("Invalid value: {0}", "org_id"))
    rows = c.execute("SELECT * FROM obj_tags WHERE scope_kind='org' AND org_id = ANY(CAST(? AS BIGINT[])) ORDER BY org_id, sort, lower(name), id",
                     (orgs,)).fetchall() if orgs else []
    return jsonify(labels=[olb_out(c, r) for r in rows])


@app.post("/api/org-labels")
def olb_create():
    """{org_id, name, color?}: admins of the organisation."""
    olb_need_person()
    b = body()
    c, uid = db(), me()
    try:
        oid = int(b.get("org_id") or 0)
    except (TypeError, ValueError):
        return err(tr("Invalid value: {0}", "org_id"))
    olb_admin(c, uid, oid)
    write_lock(c, f"org-labels-{oid}")  # 2.609.0 (#3373): the name check and the insert under one lock
    try:
        name = olb_name(b.get("name"))
    except BadInput as e:
        return err(str(e))
    if otg_find(c, "org", oid, name):
        return err(tr("This label already exists in the organisation"), 409)
    if c.execute("SELECT COUNT(*) FROM obj_tags WHERE scope_kind='org' AND scope_id=?", (str(oid),)).fetchone()[0] >= OLB_MAX:
        return err(tr("At most {0} labels", OLB_MAX))
    lbid = otg_add(c, "org", oid, name, clean_color(b.get("color") or ""), by=uid)
    # a project tag of the same name in a project of the organisation becomes this label: its tasks get the label (2.947.0, #5275)
    for r in c.execute("""SELECT ot.id FROM obj_tags ot JOIN lists l ON ot.scope_kind='list' AND ot.scope_id=CAST(l.id AS TEXT)
                          WHERE l.org_id=? AND lower(ot.name)=lower(?)""", (oid, name)).fetchall():
        otg_merge(c, r["id"], lbid)
    bump(c)
    c.commit()
    return jsonify(olb_out(c, c.execute("SELECT * FROM obj_tags WHERE id=?", (lbid,)).fetchone())), 201


@app.patch("/api/org-labels/<int:lbid>")
def olb_update(lbid):
    """{name?, color?}: reaches every project that uses the label."""
    olb_need_person()
    b = body()
    c, uid = db(), me()
    r = olb_get(c, uid, lbid)
    write_lock(c, f"org-labels-{r['org_id']}")  # 2.609.0 (#3373)
    sets = {}
    try:
        if "name" in b:
            sets["name"] = olb_name(b["name"])
            if c.execute("SELECT 1 FROM obj_tags WHERE scope_kind='org' AND scope_id=? AND lower(name)=lower(?) AND id<>?",
                         (r["scope_id"], sets["name"], lbid)).fetchone():
                return err(tr("This label already exists in the organisation"), 409)
        if "color" in b:
            sets["color"] = clean_color(b.get("color") or "")
    except BadInput as e:
        return err(str(e))
    if sets:
        c.execute(f"UPDATE obj_tags SET {','.join(qi(k, ('name', 'color')) + '=?' for k in sets)} WHERE id=?", [*sets.values(), lbid])
        bump(c)
        c.commit()
    return jsonify(olb_out(c, c.execute("SELECT * FROM obj_tags WHERE id=?", (lbid,)).fetchone()))


@app.delete("/api/org-labels/<int:lbid>")
def olb_delete(lbid):
    """The label goes; its tasks keep it as a plain project tag of their project (2.947.0, #5275: made / found by name there,
    the label's colour where the project tag has none)."""
    olb_need_person()
    c, uid = db(), me()
    r = olb_get(c, uid, lbid)
    n = 0
    # review F1: only the projects of the label's organisation -- a link left on a task of another project (hidden there) goes
    # with the label, it gives no project tag to a project outside the organisation
    for lid, tids in c.execute("""SELECT t.list_id, array_agg(t.id ORDER BY t.id) FROM obj_tag_links k JOIN tasks t ON t.id=k.obj_id
                                  JOIN lists l ON l.id=t.list_id AND l.org_id=? WHERE k.tag_id=? AND k.kind='task'
                                  GROUP BY t.list_id ORDER BY t.list_id""", (r["org_id"], lbid)).fetchall():
        pt = otg_find(c, "list", lid, r["name"])
        i = pt["id"] if pt else otg_add(c, "list", lid, r["name"], r["color"], by=uid)
        if pt and not pt["color"] and r["color"]:
            c.execute("UPDATE obj_tags SET color=? WHERE id=?", (r["color"], i))
        for tid in tids:
            otg_link(c, i, tid, by=uid)
        otg_rekey_refs(c, {int(lbid): int(i)}, lid)  # the project's rules / shared views that named the label name its tag
        n += 1
    c.execute("DELETE FROM obj_tags WHERE id=?", (lbid,))
    bump(c)
    c.commit()
    return jsonify(ok=True, unlinked=n)
