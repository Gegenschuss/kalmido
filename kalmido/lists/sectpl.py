"""2.156.0 C (#2073): section templates -- a name and the ordered names of a list's sections, saved once and added to another
list ("Sections from a template": only the missing names are added, nothing is removed or renamed). A template belongs to
one person (org_id NULL) or to an organisation (every member with the full view reads it, its creator and the organisation's
admins change it). Only for people in the app (no agent, no API token): agents create sections directly."""
import json

from flask import g, has_request_context, jsonify

from ..core.config import app
from ..core.pg import insert_id
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, now_utc
from ..accounts.session import me
from ..core.access import Denied, need_list, WRITE_ROLES
from ..personal.timetrack import BadInput

SCT_MAX_SECTIONS = 50
SCT_MAX_PER_USER = 200
SCT_NAME_MAX = 200


def sct_need_person():
    from ..agents.core import is_agent
    if has_request_context() and (is_agent(getattr(g, "user", None)) or g.get("auth_via") == "token"):
        raise Denied(403, tr("Section templates are only available in the app"))


def sct_orgs(c, uid):
    from ..accounts.orgroles import user_orgs_full
    return user_orgs_full(c, uid)


def sct_space(c, uid, v):
    """org id (None = private) of a space value "private" | "org:<id>" | <id>; 404 for an organisation uid does not fully see."""
    if v in (None, "", "private", 0, "0"):
        return None
    s = str(v)
    s = s[4:] if s.startswith("org:") else s
    try:
        oid = int(s)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", "space")) from None
    if oid not in sct_orgs(c, uid):
        raise Denied(404)
    from ..accounts.orgroles import need_org_area
    need_org_area(c, uid, oid, write=True)
    return oid


def sct_may_write(c, uid, r):
    if not r["org_id"]:
        return r["user_id"] == uid
    from ..accounts.orgroles import org_writes
    from ..accounts.orgs import is_org_admin
    return org_writes(c, uid, r["org_id"]) and (r["user_id"] == uid or is_org_admin(c, uid, r["org_id"]))


def sct_get(c, uid, tid, write=False):
    r = c.execute("SELECT * FROM section_templates WHERE id=?", (tid,)).fetchone()
    if not r:
        raise Denied(404)
    if r["org_id"] is None:
        if r["user_id"] != uid:
            raise Denied(404)
    elif r["org_id"] not in sct_orgs(c, uid):
        raise Denied(404)
    if write and not sct_may_write(c, uid, r):
        raise Denied(403, tr("Only its creator or an administrator of the organisation can change this template"))
    return r


def sct_clean_names(v):
    if not isinstance(v, list):
        raise BadInput(tr("Invalid value: {0}", "sections"))
    out, seen = [], set()
    for x in v:
        n = str(x if isinstance(x, (str, int, float)) else "").strip()[:SCT_NAME_MAX]
        if n and n.casefold() not in seen:
            seen.add(n.casefold())
            out.append(n)
    if not out:
        raise BadInput(tr("The template has no sections"))
    return out[:SCT_MAX_SECTIONS]


def sct_list_names(c, lid):
    """The section names of list lid in their order (a list with the lock: refused, its names are ciphertext)."""
    from ..collab.liste2eguard import le2b_list_locked, le2b_off
    if le2b_list_locked(c, lid):
        raise Denied(409, le2b_off())
    return [r["name"] for r in c.execute("SELECT name FROM sections WHERE list_id=? ORDER BY sort, id", (lid,))]


def sct_out(c, uid, r):
    return {"id": r["id"], "name": r["name"], "sections": json.loads(r["sections"] or "[]"),
            "space": f"org:{r['org_id']}" if r["org_id"] else "private", "org_id": r["org_id"],
            "mine": r["user_id"] == uid, "can_edit": sct_may_write(c, uid, r), "updated_at": r["updated_at"]}


@app.get("/api/section-templates")
def sct_index():
    sct_need_person()
    c, uid = db(), me()
    orgs = sct_orgs(c, uid)
    q, a = "(org_id IS NULL AND user_id=?)", [uid]
    if orgs:
        q += f" OR org_id IN ({','.join('?' * len(orgs))})"
        a += orgs
    rows = c.execute(f"SELECT * FROM section_templates WHERE {q} ORDER BY lower(name), id", a).fetchall()
    return jsonify(templates=[sct_out(c, uid, r) for r in rows])


@app.post("/api/section-templates")
def sct_create():
    """{name, space?, list_id | sections}: list_id = the sections of that list (who may write it), sections = names."""
    sct_need_person()
    b = body()
    c, uid = db(), me()
    try:
        oid = sct_space(c, uid, b.get("space"))
        if b.get("list_id") is not None:
            from ..tasks.validation import as_int
            lid = as_int(b["list_id"], "list_id", 1)
            role = need_list(c, lid, write=False)
            if role not in WRITE_ROLES:
                raise Denied(403, tr("View only: the project cannot be saved as a template"))
            names = sct_clean_names(sct_list_names(c, lid))
            src_org = c.execute("SELECT org_id FROM lists WHERE id=?", (lid,)).fetchone()["org_id"]
        else:
            src_org = None
            names = sct_clean_names(b.get("sections"))
    except BadInput as e:
        return err(str(e))
    name = str(b.get("name") or "").strip()[:SCT_NAME_MAX]
    if not name:
        return err(tr("Name missing"))
    from ..accounts.orgout import org_out  # 2.306.0 D4 (#2875): the sections of an organisation's list leave it only through its admin
    org_out(c, src_org, oid, "template", name)
    if c.execute("SELECT COUNT(*) FROM section_templates WHERE user_id=?", (uid,)).fetchone()[0] >= SCT_MAX_PER_USER:
        return err(tr("At most {0} templates", SCT_MAX_PER_USER))
    ts = iso(now_utc())
    tid = insert_id(c, "INSERT INTO section_templates(user_id,org_id,name,sections,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    (uid, oid, name, json.dumps(names, ensure_ascii=False), ts, ts))
    bump(c)
    c.commit()
    return jsonify(sct_out(c, uid, c.execute("SELECT * FROM section_templates WHERE id=?", (tid,)).fetchone()))


@app.patch("/api/section-templates/<int:tid>")
def sct_update(tid):
    """{name?, sections?}"""
    sct_need_person()
    b = body()
    c, uid = db(), me()
    sct_get(c, uid, tid, write=True)
    sets = {}
    if "name" in b:
        n = str(b["name"] or "").strip()[:SCT_NAME_MAX]
        if not n:
            return err(tr("Name missing"))
        sets["name"] = n
    if "sections" in b:
        try:
            sets["sections"] = json.dumps(sct_clean_names(b["sections"]), ensure_ascii=False)
        except BadInput as e:
            return err(str(e))
    if sets:
        sets["updated_at"] = iso(now_utc())
        c.execute(f"UPDATE section_templates SET {','.join(k + '=?' for k in sets)} WHERE id=?", [*sets.values(), tid])
        bump(c)
        c.commit()
    return jsonify(sct_out(c, uid, c.execute("SELECT * FROM section_templates WHERE id=?", (tid,)).fetchone()))


@app.delete("/api/section-templates/<int:tid>")
def sct_delete(tid):
    sct_need_person()
    c, uid = db(), me()
    sct_get(c, uid, tid, write=True)
    c.execute("DELETE FROM section_templates WHERE id=?", (tid,))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.post("/api/lists/<int:lid>/sections/from-template")
def sct_apply(lid):
    """{template_id}: the template's sections the list lacks (same name, any case) are added at the end, in the template's
    order; nothing is removed or renamed. -> {added: [section rows], skipped: [names already there]}"""
    sct_need_person()
    b = body()
    c, uid = db(), me()
    from ..tasks.validation import as_int
    try:
        tid = as_int(b.get("template_id"), "template_id", 1)
    except BadInput as e:
        return err(str(e))
    r = sct_get(c, uid, tid)
    need_list(c, lid)
    from ..collab.liste2eguard import le2b_list_locked, le2b_off
    if le2b_list_locked(c, lid):  # the names would land as plain text in a list with the lock
        return jsonify(error=le2b_off(), code="list_e2e"), 409
    have = {str(x["name"]).strip().casefold() for x in c.execute("SELECT name FROM sections WHERE list_id=?", (lid,))}
    srt = c.execute("SELECT COALESCE(MAX(sort),0) FROM sections WHERE list_id=?", (lid,)).fetchone()[0]
    added, skipped = [], []
    for n in json.loads(r["sections"] or "[]"):
        if n.casefold() in have:
            skipped.append(n)
            continue
        srt += 1
        sid = insert_id(c, "INSERT INTO sections(list_id,name,sort) VALUES(?,?,?)", (lid, n[:SCT_NAME_MAX], srt))
        have.add(n.casefold())
        added.append(dict(c.execute("SELECT * FROM sections WHERE id=?", (sid,)).fetchone()))
    if added:
        bump(c)
    c.commit()
    return jsonify(added=added, skipped=skipped)
