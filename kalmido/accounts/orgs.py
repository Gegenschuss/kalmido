"""Organisations (#752): people in 1..n organisations and whom a person may see (all / own organisation / own contacts)."""
import os
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

# 2.23.0 (#799): the kind of instance is set when it is set up, not in the app (later by the operator console):
#   KALMIDO_INSTANCE_MODE=organisation  exactly one organisation (KALMIDO_ORG_NAME, else the name the first-run setup asked
#                                       for / the instance's domain); every account is a member; admins see its name only
#                                       (renaming = the configuration); people see the people of the organisation
#   KALMIDO_INSTANCE_MODE=shared        a shared (Basic) instance of many households: no organisations, people see only their
#                                       own contacts (fixed)
#   not set                             organisation while the instance has at most one organisation (every instance up to
#                                       2.22, the work Pi included); an instance that made several in 2.22 keeps them
#                                       ("multi": members and visibility stay editable, but nobody creates or deletes any)
# The admin API never creates or deletes organisations any more (403).
INSTANCE_MODES = ("organisation", "shared")
INSTANCE_ENV = os.environ.get("KALMIDO_INSTANCE_MODE", "").strip().lower()
ORG_NAME_ENV = re.sub(r"\s+", " ", os.environ.get("KALMIDO_ORG_NAME", "")).strip()[:ORG_NAME_MAX]


def instance_mode(c):
    if INSTANCE_ENV in INSTANCE_MODES:
        return INSTANCE_ENV
    return "multi" if c.execute("SELECT COUNT(*) FROM orgs").fetchone()[0] > 1 else "organisation"


def main_org(c):
    r = c.execute("SELECT id FROM orgs ORDER BY id LIMIT 1").fetchone()
    return r[0] if r else None


def instance_sync(c):
    """At every start (init_db): the organisation mode has its one organisation (named by KALMIDO_ORG_NAME when set) with
    every account in it; nothing to do for shared / multi. The caller commits."""
    if instance_mode(c) != "organisation":
        return
    oid = main_org(c)
    if oid is None:
        from ..core.config import PUBLIC_URL
        host = PUBLIC_URL.split("://", 1)[-1].split("/")[0].split(":")[0]
        parts = [p for p in host.split(".") if p and not p.isdigit()]
        name = ORG_NAME_ENV or (parts[-2] if len(parts) >= 2 else (parts[0] if parts else "Kalmido")).capitalize()
        oid = c.execute("INSERT INTO orgs(name,icon,created_at) VALUES(?,?,?)", (name, "", iso(now_utc()))).lastrowid
    elif ORG_NAME_ENV:
        c.execute("UPDATE orgs SET name=? WHERE id=? AND name!=?", (ORG_NAME_ENV, oid, ORG_NAME_ENV))
    c.execute("INSERT OR IGNORE INTO org_members(org_id,user_id) SELECT ?, id FROM users", (oid,))


def vis_mode(c):
    m = instance_mode(c)
    if m == "shared":
        return "contacts"
    if m == "organisation":
        return "org"
    v = gsetting(c, "people_visibility")
    return v if v in VIS_MODES else "all"


def user_orgs(c, uid):
    m = instance_mode(c)
    if m == "shared":
        return []
    if m == "organisation":
        oid = main_org(c)
        return [oid] if oid else []
    return [r[0] for r in c.execute("SELECT org_id FROM org_members WHERE user_id=? ORDER BY org_id", (uid,))]


def org_names(c, uid):
    return [r[0] for r in c.execute(f"SELECT name FROM orgs WHERE id IN ({','.join(str(int(x)) for x in user_orgs(c, uid)) or 'NULL'}) ORDER BY id")]


def visible_people(c, uid):
    """None = everyone; else the set of user ids uid may see (uid included)."""
    u = c.execute("SELECT is_admin FROM users WHERE id=?", (uid,)).fetchone()
    if not u or u[0]:
        return None
    mode = vis_mode(c)
    if mode == "all":
        return None
    if mode == "org" and instance_mode(c) == "organisation":
        return None  # everyone is in the one organisation
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
    return {"id": r["id"], "name": r["name"], "icon": r["icon"], "domains": r["domains"],  # 2.23.0 (#711): e-mail domains
            "members": [x[0] for x in c.execute("SELECT user_id FROM org_members WHERE org_id=? ORDER BY user_id", (r["id"],))]}


def org_label(c, uid=None):
    """The organisation name to show next to the app name: the person's first one; before a login the instance's only one."""
    if uid:
        n = org_names(c, uid)
        return n[0] if n else ""
    m = instance_mode(c)
    if m == "shared":
        return ""
    if m == "organisation":
        r = c.execute("SELECT name FROM orgs WHERE id=?", (main_org(c),)).fetchone()
        return r[0] if r else ""
    rows = c.execute("SELECT name FROM orgs ORDER BY id LIMIT 2").fetchall()
    return rows[0][0] if len(rows) == 1 else ""


def _clean_name(v):
    if not isinstance(v, str) or not v.strip():
        raise Denied(400, tr("Name missing"))
    return re.sub(r"\s+", " ", v).strip()[:ORG_NAME_MAX]


def _clean_icon(v):
    v = str(v or "").strip()
    return v[:8]


def _clean_domains(v):
    """2.23.0 (#711): "acme.example, @Other.example" -> "acme.example, other.example" (registrations join by these)."""
    if not isinstance(v, str):
        raise Denied(400, tr("Invalid value: {0}", "domains"))
    out = []
    for d in re.split(r"[,\s;]+", v.lower()):
        d = d.strip().lstrip("@")
        if d and "." in d and re.fullmatch(r"[a-z0-9.-]{1,100}", d) and d not in out:
            out.append(d)
    return ", ".join(out[:50])


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
    """2.23.0 (#799): + mode (organisation | shared | multi) and whether names / members can be changed here (multi only)."""
    _need_admin()
    c = db()
    m = instance_mode(c)
    rows = [] if m == "shared" else c.execute("SELECT * FROM orgs" + (" WHERE id=?" if m == "organisation" else "") + " ORDER BY name COLLATE NOCASE, id",
                                              (main_org(c),) if m == "organisation" else ()).fetchall()
    return jsonify(orgs=[org_public(c, r) for r in rows], visibility=vis_mode(c), mode=m, editable=m == "multi",
                   name_env=bool(ORG_NAME_ENV))


def _no_change():
    raise Denied(403, tr("Organisations are set by the server's configuration (KALMIDO_INSTANCE_MODE, KALMIDO_ORG_NAME)"))


@app.post("/api/admin/orgs")
def org_create():
    """2.23.0 (#799): organisations are no longer created in the app (403)."""
    _need_admin()
    _no_change()


@app.patch("/api/admin/orgs/<int:oid>")
def org_update(oid):
    """{name?, icon?, members?: [user ids] (replaces them), domains?} -- only on an instance that kept several organisations
    from 2.22 ("multi"); else 403 (#799)."""
    _need_admin()
    c, b = db(), body()
    if instance_mode(c) != "multi":
        _no_change()
    if not c.execute("SELECT 1 FROM orgs WHERE id=?", (oid,)).fetchone():
        return err(tr("Not found"), 404)
    if "name" in b:
        c.execute("UPDATE orgs SET name=? WHERE id=?", (_clean_name(b["name"]), oid))
    if "icon" in b:
        c.execute("UPDATE orgs SET icon=? WHERE id=?", (_clean_icon(b["icon"]), oid))
    if "domains" in b:
        c.execute("UPDATE orgs SET domains=? WHERE id=?", (_clean_domains(b["domains"]), oid))
    if "members" in b:
        _set_members(c, oid, b["members"])
    bump(c)
    c.commit()
    return jsonify(org_public(c, c.execute("SELECT * FROM orgs WHERE id=?", (oid,)).fetchone()))


@app.delete("/api/admin/orgs/<int:oid>")
def org_delete(oid):
    """2.23.0 (#799): not in the app any more (403)."""
    _need_admin()
    _no_change()


@app.put("/api/admin/orgs/visibility")
def org_visibility():
    """{mode: all | org | contacts}: whom people see (admins always everyone)."""
    _need_admin()
    c, b = db(), body()
    if instance_mode(c) != "multi":
        _no_change()
    if b.get("mode") not in VIS_MODES:
        return err(tr("Invalid value: {0}", "mode"))
    gset(c, "people_visibility", b["mode"])
    bump(c)
    c.commit()
    return jsonify(visibility=b["mode"])
