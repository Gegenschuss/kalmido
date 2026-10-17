"""2.46.0 (#1603): who sees an organisation list. lists.org_visibility '' = only the people it is shared with (the default),
'org' = every current member of the list's organisation sees it ("Everyone in the organisation"). Who is not shared with
it is a reader (role view; edit when lists.org_edit = 1) and may join (becomes a member with the role edit). Never for
agents (only when shared with them), never for health / Home & life / family lists or private lists (core/access.py
ov_open, ov_role, the list scope _ov_sql). Events, News, push, reminders and calendars stay with the owner and members."""
from flask import g, jsonify

from ..core.config import app
from ..core.db import bump, db, err, iso, now_utc
from ..core.i18n import tr
from ..core.access import Denied, list_role, MANAGE_ROLES, my_max_sort, need_collab, ov_role
from ..accounts.session import me
from ..api.v1 import v1_args, v1_view

OV_VALUES = ("", "org")


def ov_list_patch(c, lid, role, b):
    """PATCH /api/lists/<id> {org_visibility?, org_edit?}: owner / list admins, organisation lists that are not private by
    kind. Returns an error response or None."""
    if role not in MANAGE_ROLES:
        return err(tr("Only the owner and list admins can change this setting"), 403)
    r = c.execute("SELECT org_id, life, family, is_inbox, org_visibility, org_edit FROM lists WHERE id=?", (lid,)).fetchone()
    from ..agents.core import is_agent
    opens = (b.get("org_visibility") == "org" and r["org_visibility"] != "org") or (b.get("org_edit") in (1, True, "1") and not r["org_edit"])
    if opens and is_agent(getattr(g, "user", None)) and not g.get("approved_job"):  # an agent: only after a person approved it (v1)
        return err(tr("Only the owner and list admins can change this setting"), 403)
    if "org_visibility" in b:
        v = b["org_visibility"] if b["org_visibility"] is not None else ""
        if v not in OV_VALUES:
            return err(tr("Invalid value: {0}", "org_visibility"))
        if v == "org" and (not r["org_id"] or r["life"] or r["family"] or r["is_inbox"]):
            return err(tr("Only lists of an organisation can be visible to the whole organisation"), 409)
        from ..collab.liste2e import le2e_mode
        if v == "org" and le2e_mode(c, lid):  # 2.64.1 (#1817): nobody could hand the list key to people joining by themselves
            return jsonify(error=tr("A list encrypted in the browser cannot be open to the whole organisation."), code="list_e2e_open_org"), 409
        c.execute("UPDATE lists SET org_visibility=? WHERE id=?", (v, lid))
    if "org_edit" in b:
        v = b["org_edit"]
        if isinstance(v, float) or v not in (0, 1, True, False, "0", "1"):
            return err(tr("Invalid value: {0}", "org_edit"))
        c.execute("UPDATE lists SET org_edit=? WHERE id=?", (int(v), lid))
    if r["org_visibility"] == "org" and r["org_edit"]:  # 2.83.0 (#1725): was open for editing
        o3a_unassign_readers(c, lid)
    return None


def o3a_unassign_readers(c, lid):
    """2.83.0 (#1725): tasks assigned to a member of the organisation who has not joined (allowed while everyone in the
    organisation may edit the list) are unassigned once the list is no longer open to them for editing -- like leaving."""
    c.execute("UPDATE tasks SET assignee_id=NULL WHERE list_id=? AND assignee_id IS NOT NULL "
              "AND NOT EXISTS (SELECT 1 FROM lists l WHERE l.id=tasks.list_id AND l.org_visibility='org' AND l.org_edit=1) "
              "AND assignee_id NOT IN (SELECT owner_id FROM lists WHERE id=?) "
              "AND assignee_id NOT IN (SELECT user_id FROM list_members WHERE list_id=?)", (lid, lid, lid))


def ov_private_reset(c, lid, org0=None):
    """A list that became private (no organisation, Home & life, family) or moved to another organisation (org0 = the one
    before) is shared again only with its members."""
    was = c.execute("SELECT 1 FROM lists WHERE id=? AND org_visibility='org' AND org_edit=1", (lid,)).fetchone()  # 2.83.0 (#1725)
    c.execute("UPDATE lists SET org_visibility='', org_edit=0 WHERE id=? AND (org_id IS NULL OR COALESCE(life, '')!='' "
              "OR COALESCE(family, '')!='' OR (CAST(? AS BIGINT) IS NOT NULL AND org_id!=CAST(? AS BIGINT))) AND (org_visibility!='' OR org_edit!=0)",
              (lid, org0, org0))
    if was:
        o3a_unassign_readers(c, lid)  # 2.83.0 (#1725)


def ov_join(c, lid, uid):
    """A reader joins: a member row with the role edit. 404 when uid cannot see the list, 409 when already a member."""
    need_collab()
    if not list_role(c, lid, uid):
        raise Denied(404)
    if c.execute("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (lid, uid)).fetchone() or \
            c.execute("SELECT 1 FROM lists WHERE id=? AND owner_id=?", (lid, uid)).fetchone():
        return err(tr("You are already a member of this list"), 409)
    if not ov_role(c, lid, uid):
        raise Denied(404)
    from ..lists.lists import member_folder_adopt
    c.execute("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,?,?,?,?)",
              (lid, uid, "edit", "edit", my_max_sort(c, uid) + 1, iso(now_utc())))
    member_folder_adopt(c, lid, uid)
    bump(c)
    c.commit()
    return jsonify(ok=True, role="edit")


@app.post("/api/lists/<int:lid>/join")
def ov_join_web(lid):
    """Join a list visible to the whole organisation (undo: DELETE /api/lists/<id>/members/<my id>)."""
    return ov_join(db(), lid, me())


@app.post("/api/v1/lists/<int:lid>/join")
@v1_view
def ov_join_v1(lid):
    """2.46.0 (#1603): join a list visible to the whole organisation (people only; an agent is never a reader)."""
    v1_args(())
    return ov_join(db(), lid, me())


def ov_spec(paths, schemas, op, ok, errs, ref, pid):
    """OpenAPI: "Everyone in the organisation" (called from openapi_spec)."""
    vis = {"type": "string", "enum": list(OV_VALUES), "description": "2.46.0 (#1603): who sees this organisation list: \"\" = only "
           "the people it is shared with (default), \"org\" = every member of its organisation (read-only until they join, see "
           "org_edit). Owner / list admins; only lists of an organisation, never health / Home & life / family lists (409)"}
    edit = {"type": "boolean", "description": "2.46.0 (#1603): with org_visibility \"org\": members of the organisation who are not "
            "shared with the list may edit it without joining (owner / list admins)"}
    for k in ("List", "ListDetail"):
        if k in schemas and "properties" in schemas[k]:
            schemas[k]["properties"].update(org_visibility=vis, org_edit=edit, org_reader={
                "type": "boolean", "description": "2.46.0 (#1603): you see this list only because it is visible to your "
                "organisation (not shared with you); POST /lists/{id}/join makes you a member"})
    if "ListPatch" in schemas:
        schemas["ListPatch"]["properties"].update(org_visibility=vis, org_edit=edit)
    paths["/lists/{id}/join"] = {"post": op(
        "Join a list visible to your organisation (2.46.0)", "Lists",
        ok({"type": "object", "properties": {"ok": {"type": "boolean"}, "role": {"type": "string"}}}) | errs("404", "409"),
        [pid("id", "List id")], scope="write",
        desc="For a list with org_visibility \"org\" that you see as a reader (org_reader): you become a member with the role "
             "edit (you get its notifications from now on). Leaving: DELETE /lists/{id}/members/{your id}. Agents never see "
             "lists this way (404).")}
