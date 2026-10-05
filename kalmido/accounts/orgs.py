"""Organisations (#752): people in 1..n organisations and whom a person may see (all / own organisation / own contacts)."""
import re

from flask import g, jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, err, gset, gsetting, iso, now_utc
from ..accounts.session import me
from ..core.access import Denied


# ---------------------------------------------------------------- 2.22.0 (#752): organisations
# Built the way a hosted service uses them later: an organisation is its own thing (name, an emoji), people belong to
# one or more. The instance setting "people_visibility" says whom a person sees in the share dialog, the user list, as
# an attendee or a new owner:
#   all       everyone (as before 2.22)
#   org       only people of their own organisations (the default once there is one; one company per instance)
#   contacts  only people they are connected with: a list in common, a group in common, a child / its parents (a shared
#             instance of many households and companies: no directory; one shares by e-mail address and learns
#             nothing about whether an address has an account)
# Admins always see everyone. Filtered on the server (GET /api/users, sharing, attendees, owners), never only in the app.
VIS_MODES = ("all", "org", "contacts")
ORG_NAME_MAX = 60


def vis_mode(c):
    v = gsetting(c, "people_visibility")
    return v if v in VIS_MODES else "all"


def user_orgs(c, uid):
    return [r[0] for r in c.execute("SELECT org_id FROM org_members WHERE user_id=? ORDER BY org_id", (uid,))]


def org_names(c, uid):
    return [r[0] for r in c.execute("SELECT o.name FROM org_members m JOIN orgs o ON o.id=m.org_id WHERE m.user_id=? ORDER BY o.id", (uid,))]


def visible_people(c, uid):
    """None = everyone; else the set of user ids uid may see (uid included)."""
    u = c.execute("SELECT is_admin FROM users WHERE id=?", (uid,)).fetchone()
    if not u or u[0]:
        return None
    mode = vis_mode(c)
    if mode == "all":
        return None
    if mode == "org":
        orgs = user_orgs(c, uid)
        if not orgs:  # somebody outside every organisation sees the others outside too
            ids = {r[0] for r in c.execute("SELECT id FROM users WHERE id NOT IN (SELECT user_id FROM org_members)")}
        else:
            q = ",".join("?" * len(orgs))
            ids = {r[0] for r in c.execute(f"SELECT user_id FROM org_members WHERE org_id IN ({q})", orgs)}
        return ids | {uid}
    rows = c.execute("""SELECT m2.user_id FROM list_members m1 JOIN list_members m2 ON m2.list_id=m1.list_id WHERE m1.user_id=?
                        UNION SELECT l.owner_id FROM list_members m JOIN lists l ON l.id=m.list_id WHERE m.user_id=?
                        UNION SELECT m.user_id FROM list_members m JOIN lists l ON l.id=m.list_id WHERE l.owner_id=?
                        UNION SELECT g2.user_id FROM group_members g1 JOIN group_members g2 ON g2.group_id=g1.group_id WHERE g1.user_id=?
                        UNION SELECT parent_id FROM kid_parents WHERE kid_id=? UNION SELECT kid_id FROM kid_parents WHERE parent_id=?
                        UNION SELECT user_id FROM agents WHERE owner_id=?""", (uid,) * 7).fetchall()
    return {r[0] for r in rows} | {uid}


def may_see(c, uid, other):
    v = visible_people(c, uid)
    return v is None or other in v


def need_visible(c, other):
    """404 (as for an unknown user) when the current person must not see `other`."""
    if not may_see(c, me(), other):
        raise Denied(404, tr("unknown user"))


def org_public(c, r):
    return {"id": r["id"], "name": r["name"], "icon": r["icon"],
            "members": [x[0] for x in c.execute("SELECT user_id FROM org_members WHERE org_id=? ORDER BY user_id", (r["id"],))]}


def org_label(c, uid=None):
    """The organisation name to show next to the app name: the person's first one; before a login the instance's only one."""
    if uid:
        n = org_names(c, uid)
        return n[0] if n else ""
    rows = c.execute("SELECT name FROM orgs ORDER BY id LIMIT 2").fetchall()
    return rows[0][0] if len(rows) == 1 else ""


def _clean_name(v):
    if not isinstance(v, str) or not v.strip():
        raise Denied(400, tr("Name missing"))
    return re.sub(r"\s+", " ", v).strip()[:ORG_NAME_MAX]


def _clean_icon(v):
    v = str(v or "").strip()
    return v[:8]


def _need_admin():
    if not g.user["is_admin"]:
        raise Denied(403)


def _set_members(c, oid, ids):
    if not isinstance(ids, list) or not all(isinstance(x, int) for x in ids):
        raise Denied(400, tr("Invalid value: {0}", "members"))
    have = {r[0] for r in c.execute("SELECT id FROM users")}
    c.execute("DELETE FROM org_members WHERE org_id=?", (oid,))
    for u in sorted(set(ids) & have):
        c.execute("INSERT OR IGNORE INTO org_members(org_id,user_id) VALUES(?,?)", (oid, u))


@app.get("/api/admin/orgs")
def orgs_get():
    _need_admin()
    c = db()
    return jsonify(orgs=[org_public(c, r) for r in c.execute("SELECT * FROM orgs ORDER BY name COLLATE NOCASE, id")], visibility=vis_mode(c))


@app.post("/api/admin/orgs")
def org_create():
    """{name, icon?, members?: [user ids]}"""
    _need_admin()
    c, b = db(), body()
    oid = c.execute("INSERT INTO orgs(name,icon,created_at) VALUES(?,?,?)", (_clean_name(b.get("name")), _clean_icon(b.get("icon")), iso(now_utc()))).lastrowid
    if "members" in b:
        _set_members(c, oid, b["members"])
    bump(c)
    c.commit()
    return jsonify(org_public(c, c.execute("SELECT * FROM orgs WHERE id=?", (oid,)).fetchone())), 201


@app.patch("/api/admin/orgs/<int:oid>")
def org_update(oid):
    """{name?, icon?, members?: [user ids] (replaces them)}"""
    _need_admin()
    c, b = db(), body()
    if not c.execute("SELECT 1 FROM orgs WHERE id=?", (oid,)).fetchone():
        return err(tr("Not found"), 404)
    if "name" in b:
        c.execute("UPDATE orgs SET name=? WHERE id=?", (_clean_name(b["name"]), oid))
    if "icon" in b:
        c.execute("UPDATE orgs SET icon=? WHERE id=?", (_clean_icon(b["icon"]), oid))
    if "members" in b:
        _set_members(c, oid, b["members"])
    bump(c)
    c.commit()
    return jsonify(org_public(c, c.execute("SELECT * FROM orgs WHERE id=?", (oid,)).fetchone()))


@app.delete("/api/admin/orgs/<int:oid>")
def org_delete(oid):
    _need_admin()
    c = db()
    c.execute("DELETE FROM orgs WHERE id=?", (oid,))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.put("/api/admin/orgs/visibility")
def org_visibility():
    """{mode: all | org | contacts}: whom people see (admins always everyone)."""
    _need_admin()
    c, b = db(), body()
    if b.get("mode") not in VIS_MODES:
        return err(tr("Invalid value: {0}", "mode"))
    gset(c, "people_visibility", b["mode"])
    bump(c)
    c.commit()
    return jsonify(visibility=b["mode"])
