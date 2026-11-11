"""2.156.0 C (#2073): section templates -- a name and the ordered names of a list's sections, saved once and added to another
list ("Sections from a template": only the missing names are added, nothing is removed or renamed). Only for people in the app
(no agent, no API token): agents create sections directly.

2.905.0 (#5288, stage Q10 of the cross-cutting core): a section template is a template of the shared core's kind "template"
(lists/templates.py) with kind 'sections' and data {"sections": [name, ...]} -- the table section_templates and its own copy of
the rights (sct_orgs / sct_space / sct_may_write / sct_get) are gone (core/tplmove.py moved the rows). Private (org_id NULL:
its owner) or an organisation's: every member with the full view reads and uses it, its admins add, change and delete it
(org_access view, org_join admin; before 2.905 a member could add one and change their own). Deleting puts it into the
trash of templates (restore: POST /api/templates/<id>/restore, the projects' trash lists it). The routes and answers stay."""
import json

from flask import g, has_request_context, jsonify

from ..core.config import app
from ..core.pg import insert_id
from ..core.i18n import tr
from ..core.db import body, bump, db, err
from ..accounts.session import me
from ..core.access import Denied, need_list, WRITE_ROLES
from ..core.objparts import part_trash, part_write
from ..personal.timetrack import BadInput
from .templates import need_template, TPL_KIND, tpl_new, tpl_org_of, tpl_room, tpl_rows, tpl_space

SCT_KIND = ("sections",)  # the kind of templates this module serves (lists/templates.py need_template / tpl_rows)
SCT_MAX_SECTIONS = 50
SCT_NAME_MAX = 200


def sct_need_person():
    from ..agents.core import is_agent
    if has_request_context() and (is_agent(getattr(g, "user", None)) or g.get("auth_via") == "token"):
        raise Denied(403, tr("Section templates are only available in the app"))


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


def sct_names(r):
    """The section names of template row r (data {"sections": [...]})."""
    try:
        d = json.loads(r["data"] or "{}")
    except ValueError:
        return []
    return [str(x) for x in d.get("sections") or []] if isinstance(d, dict) else []


def sct_out(c, uid, r, role=None):
    return {"id": r["id"], "name": r["name"], "sections": sct_names(r),
            "space": f"org:{r['org_id']}" if r["org_id"] else "private", **tpl_org_of(r, role), "updated_at": r["updated_at"]}


def sct_row(c, tid):
    return c.execute("SELECT * FROM templates WHERE id=?", (tid,)).fetchone()


@app.get("/api/section-templates")
def sct_index():
    sct_need_person()
    c, uid = db(), me()
    rows = sorted(tpl_rows(c, SCT_KIND), key=lambda x: ((x[0]["name"] or "").lower(), x[0]["id"]))  # 2.905.0 (#5288): the core's listing
    return jsonify(templates=[sct_out(c, uid, r, role) for r, role in rows])


@app.post("/api/section-templates")
def sct_create():
    """{name, space?, list_id | sections}: list_id = the sections of that list (who may write it), sections = names."""
    sct_need_person()
    b = body()
    c, uid = db(), me()
    try:
        oid = tpl_space(c, b.get("space"))
        if b.get("list_id") is not None:
            from ..tasks.validation import as_int
            lid = as_int(b["list_id"], "list_id", 1)
            role = need_list(c, lid, write=False)
            if role not in WRITE_ROLES:
                raise Denied(403, tr("Read-only: the project cannot be saved as a template"))
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
    full = tpl_room(c, oid, uid, kinds=SCT_KIND)  # 2.905.0 (#5288): the limit of the space it goes to (as the other templates)
    if full:
        return full
    tid = tpl_new(c, uid, "sections", name, {"sections": names}, oid)  # the core brings it into an organisation (its admins)
    bump(c)
    c.commit()
    return jsonify(sct_out(c, uid, sct_row(c, tid)))


@app.patch("/api/section-templates/<int:tid>")
def sct_update(tid):
    """{name?, sections?, expect_updated_at?}"""
    sct_need_person()
    b = body()
    c, uid = db(), me()
    need_template(c, tid, write=True, kinds=SCT_KIND)
    sets = {}
    if "name" in b:
        n = str(b["name"] or "").strip()[:SCT_NAME_MAX]
        if not n:
            return err(tr("Name missing"))
        sets["name"] = n
    if "sections" in b:
        try:
            sets["data"] = json.dumps({"sections": sct_clean_names(b["sections"])}, ensure_ascii=False)
        except BadInput as e:
            return err(str(e))
    ug = None
    if sets:
        from .tplkind import tk_touch  # after the core in ORDER (lists/tplkind.py)
        from .tplundo import tpu_plain, tpu_post, tpu_pre  # 2.905.0 (#5288): a rename is a step of the undo list, as templates

        def apply(c, r):  # 2.905.0 (#5288): under the template's lock, with its version (the core's write layer, as templates)
            if tpu_plain(b):
                tpu_pre(c, uid, tid)
            if "name" in sets:
                c.execute("UPDATE templates SET name=? WHERE id=?", (sets["name"], tid))
            if "data" in sets:
                c.execute("UPDATE templates SET data=? WHERE id=?", (sets["data"], tid))
            tk_touch(c, tid)
        part_write(c, TPL_KIND, tid, b, apply, public=lambda c, r: sct_out(c, uid, r))
        ug = tpu_post(c) if tpu_plain(b) else None
        bump(c)
        c.commit()
    return jsonify({**sct_out(c, uid, sct_row(c, tid)), **({"undo_group": ug} if ug else {})})


@app.delete("/api/section-templates/<int:tid>")
def sct_delete(tid):
    """2.905.0 (#5288): into the trash of templates (was deleted at once); POST /api/templates/<id>/restore brings it back."""
    sct_need_person()
    c, uid = db(), me()
    need_template(c, tid, write=True, kinds=SCT_KIND)
    from .tplundo import tpu_post, tpu_pre  # 2.905.0 (#5288): a step of the person's undo list, as a task / project template
    tpu_pre(c, uid, tid, "delete")
    part_trash(c, TPL_KIND, tid, uid)
    ug = tpu_post(c)
    bump(c)
    c.commit()
    return jsonify(ok=True, id=tid, trash=True, **({"undo_group": ug} if ug else {}))


@app.post("/api/lists/<int:lid>/sections/from-template")
def sct_apply(lid):
    """{template_id}: the template's sections the list lacks (same name, any case) are added at the end, in the template's
    order; nothing is removed or renamed. -> {added: [section rows], skipped: [names already there]}"""
    sct_need_person()
    b = body()
    c = db()
    from ..tasks.validation import as_int
    try:
        tid = as_int(b.get("template_id"), "template_id", 1)
    except BadInput as e:
        return err(str(e))
    r = need_template(c, tid, kinds=SCT_KIND)  # 2.905.0 (#5288): the core's role (view)
    need_list(c, lid)
    from ..collab.liste2eguard import le2b_list_locked, le2b_off
    if le2b_list_locked(c, lid):  # the names would land as plain text in a list with the lock
        return jsonify(error=le2b_off(), code="list_e2e"), 409
    have = {str(x["name"]).strip().casefold() for x in c.execute("SELECT name FROM sections WHERE list_id=?", (lid,))}
    srt = c.execute("SELECT COALESCE(MAX(sort),0) FROM sections WHERE list_id=?", (lid,)).fetchone()[0]
    added, skipped = [], []
    for n in sct_names(r):
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
