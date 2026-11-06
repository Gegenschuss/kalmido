"""2.609.0 (#3373): labels of an organisation -- project tags defined once for every project of the organisation (org_tags).
In a project they are project tags linked to the label (list_tags.org_tag_id): made the first time a task of the project gets
the label (collab/reactions.py ltag_get_or_create, also for people who may not make new project tags), renamed and recoloured
with the label, kept as plain project tags when the label is deleted. Personal tags (task_tags) stay private and unchanged; the
app shows the three kinds apart. Only the organisation's admins change its labels; the labels of another organisation are never
offered (the app state lists only the labels of organisations whose projects the person sees)."""
import re

from flask import g, has_request_context, jsonify, request

from ..core.config import app
from ..core.pg import insert_id, write_lock
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, now_utc
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
    r = c.execute("SELECT * FROM org_tags WHERE id=?", (lbid,)).fetchone()
    if not r:
        raise Denied(404)
    olb_admin(c, uid, r["org_id"])
    return r


def olb_out(c, r):
    return {"id": r["id"], "org_id": r["org_id"], "name": r["name"], "color": r["color"], "sort": r["sort"],
            "lists": c.execute("SELECT COUNT(*) FROM list_tags WHERE org_tag_id=?", (r["id"],)).fetchone()[0]}


def olb_match(c, lid, name):
    """The label of list lid's organisation named name (any case), or None (a list without an organisation: never).
    2.609.0 (#3373, review F3): only for a person with the full view of that organisation -- a guest / accounting person who
    may tag in a shared project gets a plain project tag, so the labels' names are no oracle for them."""
    r = c.execute("""SELECT o.* FROM org_tags o JOIN lists l ON l.org_id=o.org_id WHERE l.id=? AND lower(o.name)=lower(?)""",
                  (lid, name)).fetchone()
    return r if r and r["org_id"] in user_orgs_full(c, me()) else None


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
    rows = c.execute(f"SELECT * FROM org_tags WHERE org_id IN ({','.join('?' * len(orgs))}) ORDER BY org_id, sort, lower(name), id",
                     orgs).fetchall() if orgs else []
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
    if c.execute("SELECT 1 FROM org_tags WHERE org_id=? AND lower(name)=lower(?)", (oid, name)).fetchone():
        return err(tr("This label already exists in the organisation"), 409)
    if c.execute("SELECT COUNT(*) FROM org_tags WHERE org_id=?", (oid,)).fetchone()[0] >= OLB_MAX:
        return err(tr("At most {0} labels", OLB_MAX))
    srt = c.execute("SELECT COALESCE(MAX(sort),0)+1 FROM org_tags WHERE org_id=?", (oid,)).fetchone()[0]
    lbid = insert_id(c, "INSERT INTO org_tags(org_id,name,color,sort,created_at) VALUES(?,?,?,?,?)",
                     (oid, name, clean_color(b.get("color") or ""), srt, iso(now_utc())))
    # a project tag of the same name in a project of the organisation becomes this label (same name, its colour)
    c.execute("""UPDATE list_tags SET org_tag_id=? WHERE org_tag_id IS NULL AND lower(name)=lower(?)
                 AND list_id IN (SELECT id FROM lists WHERE org_id=?)""", (lbid, name, oid))
    olb_sync(c, lbid)
    bump(c)
    c.commit()
    return jsonify(olb_out(c, c.execute("SELECT * FROM org_tags WHERE id=?", (lbid,)).fetchone())), 201


def olb_sync(c, lbid):
    """The linked project tags take the label's name (where the project has no other tag of that name) and colour."""
    r = c.execute("SELECT * FROM org_tags WHERE id=?", (lbid,)).fetchone()
    c.execute("UPDATE list_tags SET color=? WHERE org_tag_id=?", (r["color"], lbid))
    c.execute("""UPDATE list_tags SET name=? WHERE org_tag_id=? AND name<>? AND NOT EXISTS (SELECT 1 FROM list_tags x
                 WHERE x.list_id=list_tags.list_id AND x.id<>list_tags.id AND lower(x.name)=lower(?))""", (r["name"], lbid, r["name"], r["name"]))


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
            if c.execute("SELECT 1 FROM org_tags WHERE org_id=? AND lower(name)=lower(?) AND id<>?", (r["org_id"], sets["name"], lbid)).fetchone():
                return err(tr("This label already exists in the organisation"), 409)
        if "color" in b:
            sets["color"] = clean_color(b.get("color") or "")
    except BadInput as e:
        return err(str(e))
    if sets:
        c.execute(f"UPDATE org_tags SET {','.join(k + '=?' for k in sets)} WHERE id=?", [*sets.values(), lbid])
        olb_sync(c, lbid)
        bump(c)
        c.commit()
    return jsonify(olb_out(c, c.execute("SELECT * FROM org_tags WHERE id=?", (lbid,)).fetchone()))


@app.delete("/api/org-labels/<int:lbid>")
def olb_delete(lbid):
    """The label goes; its project tags stay in their projects as plain project tags (on their tasks)."""
    olb_need_person()
    c, uid = db(), me()
    olb_get(c, uid, lbid)
    n = c.execute("UPDATE list_tags SET org_tag_id=NULL WHERE org_tag_id=?", (lbid,)).rowcount
    c.execute("DELETE FROM org_tags WHERE id=?", (lbid,))
    bump(c)
    c.commit()
    return jsonify(ok=True, unlinked=n)
