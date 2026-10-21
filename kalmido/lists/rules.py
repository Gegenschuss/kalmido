"""2.71.0 A (#1457): rules of a list ("When ... then ..."), set by its owner or a list admin.

A rule has ONE trigger (a task comes into column X, is completed, is opened again, gets the list tag Y, its due day is
today) and ONE action (assign it to a person of the list, set / clear the due date relative to today, write a fixed
comment, move it to a list and / or column). 2.138.0 D (#2060): triggers created / assigned / field (a custom field changes),
actions priority / tag (a list tag) / field (a custom field gets a fixed value). It runs with the rights of the person who created it (created_by), checked
again every time it runs: that person must still be owner / admin of the list, and a move needs write access to the target
list too (same organisation / private as the source, never a health list, never a locked list). If a right is missing the
rule does not run and pauses itself (paused_reason), it never goes on with other rights.

Loop protection (owner decision of the release lead, depth 0): a change made by a rule never triggers a rule, not even in
the target list of a move. Predictable, no chains across lists, no ping-pong of two rules. At most RUL_FIRE_MAX rules per
triggering change and RUL_LIST_MAX rules per list.

Every change goes through the usual paths (apply_update, log_act, comment pushes, webhooks); the activity carries
{"rule": {"id", "name"}} and the client shows "Rule <name>" instead of the person. Agents read rules (GET
/api/v1/lists/{id}/rules) and may only PROPOSE one (POST /api/v1/lists/{id}/rules/proposals, kind "rule"); the owner /
an admin accepts it and the rule then belongs to that person.
"""
import contextlib
import json
from datetime import timedelta
from flask import g, has_request_context, jsonify, request

from ..core.config import app
from ..core.pg import insert_id, system_ctx as pg_system
from ..core.i18n import N_, tr
from ..core.db import body, bump, db, err, iso, local_now, now_utc
from ..core.access import Denied, list_people, list_role, MANAGE_ROLES, need_list, WRITE_ROLES
from ..accounts.session import me
from ..personal.timetrack import BadInput, reject_unknown
from ..api.v1 import v1_args, v1_err, v1_json, v1_view

RUL_LIST_MAX = 50           # rules per list
RUL_FIRE_MAX = 20           # rules run for one triggering change
RUL_NAME_MAX = 80
RUL_TEXT_MAX = 2000         # the fixed comment
RUL_DAYS_MAX = 365          # due date: today + 0..365 days
RUL_DUE_BATCH = 500         # tasks per watchdog tick (due date reached)
RUL_PROP_DAY_MAX = 20       # rule proposals of one agent per 24 hours
RUL_TRIGGERS = ("section", "done", "reopen", "ltag", "due", "created", "assigned", "field")  # 2.138.0 D (#2060): + created, assigned, field
RUL_ACTIONS = ("assign", "due", "comment", "move", "priority", "tag", "field")  # 2.138.0 D (#2060): + priority, tag, field
RUL_PRIO = {"none": 0, "low": 1, "medium": 3, "high": 5}  # 2.138.0 D (#2060): action priority (names as in API v1)
RUL_PAUSE = {  # paused_reason -> the text the settings show
    "creator": N_("the person who set it up has no access to the list any more"),
    "role": N_("the person who set it up is no longer owner or admin of the list"),
    "target": N_("no write access to the target list any more"),
    "assignee": N_("the person to assign is no longer in the list"),
    "locked": N_("the list or the target list is locked"),
    "section": N_("the target column no longer exists"),  # 2.71.0 (#1457, review N2)
    "list": N_("rules are no longer available in this list"),  # 2.71.0 (#1457, review N4)
    "field": N_("the custom field or its value no longer exists"),  # 2.138.0 D (#2060)
    "tag": N_("the list tag no longer exists"),  # 2.138.0 D (#2060)
}
_NEW = {"new": True}  # rul_fire: the task was just created


# ---------------------------------------------------------------- 2.64a (lock per list)


def rul_locked(c, lid):
    """True when list lid is locked (end-to-end encrypted, 2.64a)."""
    if not lid:  # lists.e2e exists since 2.64a (merged before 2.71: no column probe any more)
        return False
    r = c.execute("SELECT e2e IS NOT NULL FROM lists WHERE id=?", (lid,)).fetchone()
    return bool(r and r[0])


# ---------------------------------------------------------------- input
def _int(v, what):
    if isinstance(v, bool):
        raise BadInput(tr("Invalid value: {0}", what))
    try:
        return int(v)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", what)) from None


def _list_row(c, lid):
    return c.execute("SELECT id, org_id, life, is_inbox, owner_id FROM lists WHERE id=?", (lid,)).fetchone()


def rul_list_ok(c, lid):
    """None when list lid may have rules, else the reason (health lists, the basket and locked lists have none)."""
    r = _list_row(c, lid)
    if not r:
        raise Denied(404)
    if r["life"] in ("health", "budget") or r["is_inbox"]:  # 2.72.0 (#1333): budgets neither
        return tr("Rules are not available in this list")
    if rul_locked(c, lid):
        return tr("Rules are not available in locked lists")
    return None


def rul_target_ok(c, src, dst, uid, see_only=False):
    """None when a rule of list src (run by uid, the current user) may move tasks into list dst, else an error text.
    see_only: an agent's proposal (the person who accepts it is checked with write access when accepting)."""
    from ..tasks.tasks import can_move
    s, d = _list_row(c, src), _list_row(c, dst)
    role = list_role(c, dst, uid) if d else None
    if not d or not role:
        raise Denied(404)
    if d["life"] in ("health", "budget") or rul_locked(c, dst):
        return tr("Tasks cannot be moved into this list by a rule")
    if (s["org_id"] or 0) != (d["org_id"] or 0):
        return tr("The target list must be in the same workspace")
    if not see_only and (role not in WRITE_ROLES or not can_move(c, src, dst)):
        return tr("You need write access to the target list")
    return None


def rul_clean(c, lid, b, partial=None, see_only=False):
    """{name, trigger: {kind, section_id | tag_id}, action: {kind, user_id | days | text | list_id, section_id}} -> the
    columns (BadInput / Denied). The references are checked with the rights of the current user. partial = the stored
    row (PATCH: missing parts stay)."""
    from ..tasks.tasks import check_assignee
    reject_unknown(b, ("name", "trigger", "action", "active"))
    out = {}
    if "name" in b or partial is None:
        name = " ".join(str(b.get("name") or "").split())
        if not name or not isinstance(b.get("name"), str):
            raise BadInput(tr("Name missing"))
        out["name"] = name[:RUL_NAME_MAX]
    if "trigger" in b or partial is None:
        t = b.get("trigger")
        if not isinstance(t, dict) or t.get("kind") not in RUL_TRIGGERS:
            raise BadInput(tr("Invalid value: {0}", "trigger"))
        reject_unknown(t, ("kind", "section_id", "tag_id", "user_id", "field_id", "value"))
        val = ""
        if t["kind"] == "section":
            sid = _int(t.get("section_id"), "trigger.section_id")
            if not c.execute("SELECT 1 FROM sections WHERE id=? AND list_id=?", (sid, lid)).fetchone():
                raise BadInput(tr("Invalid value: {0}", "trigger.section_id"))
            val = str(sid)
        elif t["kind"] == "ltag":
            tag = _int(t.get("tag_id"), "trigger.tag_id")
            if not c.execute("SELECT 1 FROM list_tags WHERE id=? AND list_id=?", (tag, lid)).fetchone():
                raise BadInput(tr("Invalid value: {0}", "trigger.tag_id"))
            val = str(tag)
        elif t["kind"] in ("assigned", "field"):
            val = rul_trig_clean(c, lid, t)
        out["trig"], out["trig_val"] = t["kind"], val
    if "action" in b or partial is None:
        a = b.get("action")
        if not isinstance(a, dict) or a.get("kind") not in RUL_ACTIONS:
            raise BadInput(tr("Invalid value: {0}", "action"))
        k, target, v = a["kind"], None, {}
        if k == "assign":
            reject_unknown(a, ("kind", "user_id"))
            aid = _int(a.get("user_id"), "action.user_id")
            e = check_assignee(c, lid, aid)
            if e:
                raise BadInput(e)
            v = {"user_id": aid}
        elif k == "due":
            reject_unknown(a, ("kind", "days"))
            d = a.get("days")
            if d is not None:
                d = _int(d, "action.days")
                if not 0 <= d <= RUL_DAYS_MAX:
                    raise BadInput(tr("Invalid value: {0}", "action.days"))
            v = {"days": d}
        elif k == "comment":
            reject_unknown(a, ("kind", "text"))
            text = a.get("text")
            if not isinstance(text, str) or not text.strip():
                raise BadInput(tr("The comment is empty"))
            if len(text) > RUL_TEXT_MAX:
                raise BadInput(tr("The comment is too long (max. {0} characters)", RUL_TEXT_MAX))
            v = {"text": text.strip()}
        elif k in ("priority", "tag", "field"):
            v = rul_act_clean(c, lid, a)
        else:  # move: into a list and / or a column (the column belongs to the target list)
            reject_unknown(a, ("kind", "list_id", "section_id"))
            dst = _int(a["list_id"], "action.list_id") if a.get("list_id") not in (None, "", 0) else lid
            sid = _int(a["section_id"], "action.section_id") if a.get("section_id") not in (None, "", 0) else None
            if dst == lid and sid is None:
                raise BadInput(tr("Choose a list or a column"))
            if dst != lid:
                e = rul_target_ok(c, lid, dst, me(), see_only)
                if e:
                    raise BadInput(e)
            if sid is not None and not c.execute("SELECT 1 FROM sections WHERE id=? AND list_id=?", (sid, dst)).fetchone():
                raise BadInput(tr("Invalid value: {0}", "action.section_id"))
            v, target = {"list_id": dst, "section_id": sid}, (dst if dst != lid else None)
        out["act"], out["act_val"], out["target_list_id"] = k, json.dumps(v, separators=(",", ":")), target
    if "active" in b:
        out["active"] = 1 if b["active"] else 0
    return out


# ---------------------------------------------------------------- 2.138.0 D (#2060): created / assigned / field, priority / tag / field
def _field_row(c, lid, fid):
    return c.execute("SELECT * FROM list_fields WHERE id=? AND list_id=?", (fid, lid)).fetchone()


def rul_trig_clean(c, lid, t):
    """trig_val of the triggers assigned ({user_id?}: "" = anybody, else that person of the list) and field ({field_id,
    value?}: "<id>" = any change; "<id>=<option id>" = set to that option of a selection field; checkbox "<id>=1" = checked,
    "<id>=" = unchecked). Formula fields are computed, they never trigger."""
    if t["kind"] == "assigned":
        if t.get("user_id") in (None, "", 0):
            return ""
        uid = _int(t["user_id"], "trigger.user_id")
        if uid not in list_people(c, lid):
            raise BadInput(tr("Invalid value: {0}", "trigger.user_id"))
        return str(uid)
    fid = _int(t.get("field_id"), "trigger.field_id")
    f = _field_row(c, lid, fid)
    if not f or f["type"] == "formula":
        raise BadInput(tr("Invalid value: {0}", "trigger.field_id"))
    v = t.get("value")
    if v is None or v == "":
        return str(fid)
    if f["type"] == "checkbox":
        if v in (True, 1, "1", "true") or v in (False, 0, "0", "false"):  # 2.138.0 D (#2060, review): anything else is no checkbox value
            return f"{fid}={'1' if v in (True, 1, '1', 'true') else ''}"
        raise BadInput(tr("Invalid value: {0}", "trigger.value"))
    if f["type"] == "select" and str(v) in {o["id"] for o in json.loads(f["options"] or "{}").get("options", [])}:
        return f"{fid}={v}"
    raise BadInput(tr("Invalid value: {0}", "trigger.value"))


def rul_act_clean(c, lid, a):
    """act_val of the actions priority ({priority: none | low | medium | high}), tag ({tag_id}: adds a tag of THIS list --
    the rule belongs to everybody in the list, so never personal tags) and field ({field_id, value}: null clears it; checked
    against the field type like the normal field route)."""
    from .fields import field_value
    k = a["kind"]
    if k == "priority":
        reject_unknown(a, ("kind", "priority"))
        if a.get("priority") not in RUL_PRIO:
            raise BadInput(tr("Invalid value: {0}", "action.priority"))
        return {"priority": a["priority"]}
    if k == "tag":
        reject_unknown(a, ("kind", "tag_id"))
        tag = _int(a.get("tag_id"), "action.tag_id")
        if not c.execute("SELECT 1 FROM list_tags WHERE id=? AND list_id=?", (tag, lid)).fetchone():
            raise BadInput(tr("Invalid value: {0}", "action.tag_id"))
        return {"tag_id": tag}
    reject_unknown(a, ("kind", "field_id", "value"))
    fid = _int(a.get("field_id"), "action.field_id")
    f = _field_row(c, lid, fid)
    if not f or f["type"] == "formula":
        raise BadInput(tr("Invalid value: {0}", "action.field_id"))
    return {"field_id": fid, "value": field_value(c, f, a.get("value"), lid)}


def rul_trig_val(t):
    """The stored trig_val of a (checked) trigger dict -- the proposal card builds a rule row from it."""
    t = t or {}
    if t.get("kind") == "field" and t.get("field_id"):
        v = t.get("value")
        return str(t["field_id"]) + ("" if v is None or v == "" else "=" + ("" if v in (False, 0, "0", "false") else "1" if v is True else str(v)))
    return str(t.get("section_id") or t.get("tag_id") or t.get("user_id") or "")


def rul_val_name(c, f, v):
    """The readable value of a field rule (option / person name); None for a checkbox (the client words it)."""
    from .fields import field_act
    if not f or v is None or f["type"] == "checkbox":
        return None
    return field_act(c, f, v)["v"]


def rul_ref_gone(c, r):
    """The pause reason when the custom field / list tag a rule refers to was deleted, else None."""
    a = json.loads(r["act_val"] or "{}")
    tv = (r["trig_val"] or "").split("=")[0]
    if (r["trig"] == "field" and tv.isdigit() and not _field_row(c, r["list_id"], int(tv))) or \
            (r["act"] == "field" and not _field_row(c, r["list_id"], a.get("field_id") or 0)):
        return "field"
    tags = [int(tv)] if r["trig"] == "ltag" and tv.isdigit() else []
    tags += [a.get("tag_id") or 0] if r["act"] == "tag" else []
    if any(not c.execute("SELECT 1 FROM list_tags WHERE id=? AND list_id=?", (x, r["list_id"])).fetchone() for x in tags):
        return "tag"
    return None


def rul_fvals(c, tid, lid):
    """{field id: value} of task tid when list lid has an active rule "field changed", else None (normal changes stay cheap)."""
    k = _cache().setdefault("fl", {})
    if lid not in k:
        k[lid] = bool(c.execute("SELECT 1 FROM list_rules WHERE list_id=? AND trig='field' AND active=1 AND deleted_at IS NULL LIMIT 1",
                                (lid,)).fetchone())
    if not k[lid]:
        return None
    return {r[0]: r[1] for r in c.execute("SELECT field_id, value FROM task_field_values WHERE task_id=?", (tid,))}


def rul_new_events(c, t, before, new):
    """The events of the new triggers: created, assigned (only when the person is new on the task), field (a value of the
    list's own fields changed, compared within the same list)."""
    ev = {("created", "")} if new else set()
    if t["assignee_id"] and (new or t["assignee_id"] != before.get("assignee")):
        ev |= {("assigned", ""), ("assigned", str(t["assignee_id"]))}
    if new or (t["list_id"] == before["list_id"] and before.get("fields") is not None):
        cur = rul_fvals(c, t["id"], t["list_id"]) or {}
        old = {} if new else before["fields"]
        for fid in set(old) | set(cur):
            if old.get(fid) != cur.get(fid):
                ev |= {("field", str(fid)), ("field", f"{fid}={cur.get(fid) or ''}")}
    return ev


# ---------------------------------------------------------------- output
def rul_rows(c, lid):
    """The live rules of list lid (oldest first). 2.71.0 A: read as "system" -- only after the caller checked the list (the
    rules of a list that moved between private and an organisation keep their old org_id until rul_sync)."""
    rul_sync(c, lid)
    rows = c.execute("SELECT * FROM list_rules WHERE list_id=? AND deleted_at IS NULL ORDER BY id", (lid,)).fetchall()
    gone = [(r, rul_ref_gone(c, r)) for r in rows if r["active"]]  # 2.138.0 D (#2060): deleted field / tag -> paused
    if any(w for _, w in gone):
        for r, w in gone:
            if w:
                rul_pause(c, r, w)
        c.commit()  # the GET routes (rules_get / v1_rules_get) only read otherwise
        rows = c.execute("SELECT * FROM list_rules WHERE list_id=? AND deleted_at IS NULL ORDER BY id", (lid,)).fetchall()
    return rows


def rul_sync(c, lid):
    """A rule's org_id follows its list (row-level security sees it in the list's organisation)."""
    with pg_system(c):  # 2.71.0 A (#1457): system on purpose: the rules of ONE list the caller may see, re-tagged with the list's org
        c.execute("""UPDATE list_rules SET org_id=(SELECT org_id FROM lists WHERE id=?) WHERE list_id=?
                     AND org_id IS DISTINCT FROM (SELECT org_id FROM lists WHERE id=?)""", (lid, lid, lid))


def rul_dict(c, r):
    from ..collab.comments import user_names
    a = json.loads(r["act_val"] or "{}")
    trig = {"kind": r["trig"]}
    names = {}
    if r["trig"] == "section" and r["trig_val"]:
        trig["section_id"] = int(r["trig_val"])
        s = c.execute("SELECT name FROM sections WHERE id=?", (trig["section_id"],)).fetchone()
        names["section"] = s[0] if s else None
    elif r["trig"] == "ltag" and r["trig_val"]:
        trig["tag_id"] = int(r["trig_val"])
        s = c.execute("SELECT name FROM list_tags WHERE id=?", (trig["tag_id"],)).fetchone()
        names["tag"] = s[0] if s else None
    elif r["trig"] == "assigned":  # 2.138.0 D (#2060)
        trig["user_id"] = int(r["trig_val"]) if r["trig_val"] else None
        names["trig_user"] = user_names(c, [trig["user_id"]]).get(trig["user_id"]) if trig["user_id"] else None
    elif r["trig"] == "field" and r["trig_val"]:
        fid, eq, v = r["trig_val"].partition("=")
        f = _field_row(c, r["list_id"], int(fid))
        trig["field_id"], trig["value"] = int(fid), (("1" if v else "0") if f and f["type"] == "checkbox" else v) if eq else None
        names["field"] = f["name"] if f else None
        names["value"] = rul_val_name(c, f, v) if eq else None
    act = {"kind": r["act"], **a}
    if r["act"] == "assign":
        names["user"] = user_names(c, [a.get("user_id")]).get(a.get("user_id"))
    elif r["act"] == "move":
        # 2.71.0 (#1457, review M1): the target's names only for a viewer who sees the target list
        see = not a.get("list_id") or a["list_id"] == r["list_id"] or bool(has_request_context() and g.get("user") and list_role(c, a["list_id"]))
        if a.get("list_id") and a["list_id"] != r["list_id"] and see:
            s = c.execute("SELECT name FROM lists WHERE id=?", (a["list_id"],)).fetchone()
            names["list"] = s[0] if s else None
        if a.get("section_id") and see:
            s = c.execute("SELECT name FROM sections WHERE id=?", (a["section_id"],)).fetchone()
            names["section_to"] = s[0] if s else None
    elif r["act"] == "tag":  # 2.138.0 D (#2060)
        s = c.execute("SELECT name FROM list_tags WHERE id=?", (a.get("tag_id"),)).fetchone()
        names["tag_to"] = s[0] if s else None
    elif r["act"] == "field":
        f = _field_row(c, r["list_id"], a.get("field_id") or 0)
        names["field_to"], names["value_to"] = (f["name"] if f else None), rul_val_name(c, f, a.get("value"))
        names["field_type"] = f["type"] if f else None
    by = r["created_by"]
    return {"id": r["id"], "list_id": r["list_id"], "name": r["name"], "trigger": trig, "action": act, "names": names,
            "active": bool(r["active"]), "paused_reason": r["paused_reason"] or None,
            "paused_text": tr(RUL_PAUSE[r["paused_reason"]]) if r["paused_reason"] in RUL_PAUSE else None,
            "created_by": by, "created_by_name": user_names(c, [by]).get(by) if by else None,
            "created_at": r["created_at"], "updated_at": r["updated_at"]}


# ---------------------------------------------------------------- web routes (owner / list admins; agents never)
def _need_person():
    from ..agents.core import is_agent
    if is_agent(g.user):
        raise Denied(403, tr("Agents can only propose rules"))


def need_rule(c, rid, deleted=False):
    r = c.execute("SELECT * FROM list_rules WHERE id=?", (rid,)).fetchone()
    if not r or (r["deleted_at"] is not None) != deleted:
        raise Denied(404)
    need_list(c, r["list_id"], write=False, manage=True)
    return r


@app.get("/api/lists/<int:lid>/rules")
def rules_get(lid):
    c = db()
    need_list(c, lid, write=False, manage=True)
    return jsonify(rules=[rul_dict(c, r) for r in rul_rows(c, lid)], limit=RUL_LIST_MAX, available=rul_list_ok(c, lid) is None)


def rul_insert(c, lid, f, uid):
    ts = iso(now_utc())
    if c.execute("SELECT COUNT(*) FROM list_rules WHERE list_id=? AND deleted_at IS NULL", (lid,)).fetchone()[0] >= RUL_LIST_MAX:
        raise BadInput(tr("At most {0} rules per list", RUL_LIST_MAX))
    org = c.execute("SELECT org_id FROM lists WHERE id=?", (lid,)).fetchone()[0]
    return insert_id(c, """INSERT INTO list_rules(list_id,org_id,name,trig,trig_val,act,act_val,target_list_id,active,paused_reason,
                         created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'',?,?,?)""",
                     (lid, org, f["name"], f["trig"], f["trig_val"], f["act"], f["act_val"], f["target_list_id"], f.get("active", 1),
                      uid, ts, ts))


@app.post("/api/lists/<int:lid>/rules")
def rule_create(lid):
    _need_person()
    c = db()
    need_list(c, lid, write=False, manage=True)
    e = rul_list_ok(c, lid)
    if e:
        return err(e, 409)
    try:
        rid = rul_insert(c, lid, rul_clean(c, lid, body()), me())
    except BadInput as e:
        return err(str(e))
    bump(c)
    c.commit()
    return jsonify(rul_dict(c, c.execute("SELECT * FROM list_rules WHERE id=?", (rid,)).fetchone())), 201


@app.patch("/api/rules/<int:rid>")
def rule_update(rid):
    """{name?, trigger?, action?, active?}. Changing the trigger / action or switching a rule on again makes the editing
    person its owner (it runs with their rights from now on) and clears a pause."""
    _need_person()
    c = db()
    r = need_rule(c, rid)
    b = body()
    e = rul_list_ok(c, r["list_id"])
    if e:
        return err(e, 409)
    try:
        f = rul_clean(c, r["list_id"], b, partial=r)
        if ((f.get("active") and not r["active"]) or "trig" in f) and "act" not in f:  # on again / new owner (review N1): the stored action is checked with my rights
            rul_clean(c, r["list_id"], {"action": rul_dict(c, r)["action"]}, partial=r)
    except BadInput as e:
        return err(str(e))
    if any(k in f for k in ("trig", "act")) or (f.get("active") and not r["active"]):
        f.update(created_by=me(), paused_reason="")
    f["updated_at"] = iso(now_utc())
    c.execute(f"UPDATE list_rules SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), rid])
    bump(c)
    c.commit()
    return jsonify(rul_dict(c, c.execute("SELECT * FROM list_rules WHERE id=?", (rid,)).fetchone()))


@app.delete("/api/rules/<int:rid>")
def rule_delete(rid):
    """Into the trash of the list's rules (POST .../restore brings it back: the client's undo)."""
    _need_person()
    c = db()
    need_rule(c, rid)
    c.execute("UPDATE list_rules SET deleted_at=?, updated_at=? WHERE id=?", (iso(now_utc()), iso(now_utc()), rid))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.post("/api/rules/<int:rid>/restore")
def rule_restore(rid):
    _need_person()
    c = db()
    r = need_rule(c, rid, deleted=True)
    if c.execute("SELECT COUNT(*) FROM list_rules WHERE list_id=? AND deleted_at IS NULL", (r["list_id"],)).fetchone()[0] >= RUL_LIST_MAX:
        return err(tr("At most {0} rules per list", RUL_LIST_MAX))
    c.execute("UPDATE list_rules SET deleted_at=NULL, updated_at=? WHERE id=?", (iso(now_utc()), rid))
    bump(c)
    c.commit()
    return jsonify(rul_dict(c, c.execute("SELECT * FROM list_rules WHERE id=?", (rid,)).fetchone()))


# ---------------------------------------------------------------- running the rules
def _cache():
    return g.setdefault("rul_any", {}) if has_request_context() else {}


def _any_rules(c):
    """Are there active rules at all (once per request; a cheap no for instances without rules)."""
    k = _cache()
    if "any" not in k:
        k["any"] = bool(c.execute("SELECT 1 FROM list_rules WHERE active=1 AND deleted_at IS NULL LIMIT 1").fetchone())
    return k["any"]


def rul_snap(c, tid):
    """What rul_fire compares with after a change ({} = nothing to do: no rules, or a rule is running = depth 0)."""
    if (has_request_context() and g.get("rul_run")) or not _any_rules(c):
        return {}
    t = c.execute("SELECT list_id, section_id, status, assignee_id FROM tasks WHERE id=?", (tid,)).fetchone()
    if not t:
        return {}
    return {"list_id": t["list_id"], "section_id": t["section_id"], "status": t["status"],
            "tags": {x[0] for x in c.execute("SELECT tag_id FROM task_list_tags WHERE task_id=?", (tid,))},
            "assignee": t["assignee_id"], "fields": rul_fvals(c, tid, t["list_id"])}  # 2.138.0 D (#2060)


def rul_snap_new(c):
    """rul_fire's `before` for a task created just now."""
    return _NEW if not (has_request_context() and g.get("rul_run")) and _any_rules(c) else {}


def rul_fire(c, tid, before):
    """# 2.71.0 A (#1457): the hook after a successful change / creation of task tid. Runs the matching rules of the
    task's list (as their creators). Never raises: a rule that fails is skipped (or paused when a right is missing)."""
    if not before or not has_request_context() or g.get("rul_run"):
        return  # outside a request (a repository closing a task in the background): no rules -- nobody to run them as safely
    t = c.execute("SELECT id, list_id, section_id, status, deleted_at, assignee_id FROM tasks WHERE id=?", (tid,)).fetchone()
    if not t or t["deleted_at"]:
        return
    tags = {x[0] for x in c.execute("SELECT tag_id FROM task_list_tags WHERE task_id=?", (tid,))}
    new = before is _NEW
    ev = set()
    if t["section_id"] and (new or t["section_id"] != before["section_id"] or t["list_id"] != before["list_id"]):
        ev.add(("section", str(t["section_id"])))
    if not new and before["status"] == 0 and t["status"] == 2:
        ev.add(("done", ""))
    if not new and before["status"] != 0 and t["status"] == 0:
        ev.add(("reopen", ""))
    for x in tags - (set() if new or t["list_id"] != before["list_id"] else before["tags"]):
        ev.add(("ltag", str(x)))
    ev |= rul_new_events(c, t, before, new)  # 2.138.0 D (#2060)
    if not ev:
        return
    rul_run_matching(c, t, ev)


def rul_fire_done(c, tid, copy_id, before):
    """do_complete: a recurring task moves on (it stays open) -- its completed occurrence (copy_id) is the task that was done."""
    rul_fire(c, copy_id or tid, before)


def rul_run_matching(c, t, ev):
    rul_sync(c, t["list_id"])
    rows = c.execute("""SELECT * FROM list_rules WHERE list_id=? AND active=1 AND deleted_at IS NULL AND trig<>'due'
                        ORDER BY id""", (t["list_id"],)).fetchall()
    n = 0
    for r in rows:
        if (r["trig"], r["trig_val"] or "") not in ev:
            continue
        if n >= RUL_FIRE_MAX:
            break
        n += 1
        rul_exec(c, r, t["id"])


@contextlib.contextmanager
def rul_as(c, r):
    """The block runs as the rule's creator (g.user; the database context follows it, core/access.py acx_conn_hook) with
    the rule noted for the history (log_act) and as the depth-0 guard. Token limits of the triggering request do not carry
    over (they belong to that request's caller); restored afterwards in any case."""
    keys = ("user", "auth_via", "token", "token_lists", "audit_aid", "scopes", "acx", "rul_run")
    keep = {k: g.get(k) for k in keys if k in g}
    u = c.execute("SELECT * FROM users WHERE id=?", (r["created_by"],)).fetchone()
    for k in keys:
        g.pop(k, None)
    g.user, g.auth_via, g.rul_run = u, "rule", {"id": r["id"], "name": r["name"]}
    try:
        yield
    finally:
        for k in keys:
            g.pop(k, None)
        for k, v in keep.items():
            setattr(g, k, v)


def rul_pause(c, r, why):
    with pg_system(c):  # 2.71.0 A (#1457): system on purpose: pausing exactly this rule (also from the watchdog, no person)
        c.execute("UPDATE list_rules SET active=0, paused_reason=?, updated_at=? WHERE id=?", (why, iso(now_utc()), r["id"]))
    _cache().pop("any", None)
    _cache().pop("fl", None)  # 2.138.0 D (#2060)


def rul_check(c, r, tid):
    """Under rul_as: None when the creator may run rule r on task tid now, else the pause reason."""
    from ..tasks.tasks import check_assignee
    from ..agents.core import is_agent
    if not g.user or g.user["disabled"] or is_agent(g.user):
        return "creator"
    role = list_role(c, r["list_id"])
    if not role:
        return "creator"
    if role not in MANAGE_ROLES:
        return "role"
    if rul_locked(c, r["list_id"]):
        return "locked"
    if rul_list_ok(c, r["list_id"]):  # 2.71.0 (#1457, review N4): the list became a health list afterwards
        return "list"
    a = json.loads(r["act_val"] or "{}")
    if r["act"] == "move" and a.get("section_id") and not c.execute(  # review N2: a deleted target column pauses the rule
            "SELECT 1 FROM sections WHERE id=? AND list_id=?", (a["section_id"], a.get("list_id") or r["list_id"])).fetchone():
        return "section"
    if r["act"] == "move" and a.get("list_id") and a["list_id"] != r["list_id"]:
        if rul_locked(c, a["list_id"]):
            return "locked"
        try:
            if rul_target_ok(c, r["list_id"], a["list_id"], me()):
                return "target"
        except Denied:
            return "target"
    why = rul_ref_gone(c, r)  # 2.138.0 D (#2060): the field / list tag of the rule was deleted
    if why:
        return why
    if r["act"] == "field":  # the fixed value must still fit (an option removed, a person left the list)
        from .fields import field_value
        try:
            field_value(c, _field_row(c, r["list_id"], a["field_id"]), a.get("value"), r["list_id"])
        except BadInput:
            return "field"
    if r["act"] == "assign" and (a.get("user_id") not in list_people(c, r["list_id"]) or check_assignee(c, r["list_id"], a.get("user_id"))):
        return "assignee"
    return None


def rul_exec(c, r, tid):
    """Runs the action of rule r on task tid as its creator (one savepoint: a failing action leaves nothing behind)."""
    from ..tasks.lifecycle import apply_update
    if not r["created_by"]:
        rul_pause(c, r, "creator")
        return False
    with rul_as(c, r):
        try:
            why = rul_check(c, r, tid)
        except Denied:
            why = "role"
        if why:
            pause = why
        else:
            pause = None
            a = json.loads(r["act_val"] or "{}")
            try:
                with c.savepoint():
                    if r["act"] == "comment":
                        rul_comment(c, r, tid, a["text"])
                    else:
                        if r["act"] == "assign":
                            b = {"assignee_id": a["user_id"]}
                        elif r["act"] == "priority":  # 2.138.0 D (#2060)
                            b = {"priority": RUL_PRIO.get(a.get("priority"), 0)}
                        elif r["act"] == "tag":
                            from ..collab.reactions import ltag_names
                            b = {"ltags": ltag_names(c, tid) + [c.execute("SELECT name FROM list_tags WHERE id=?", (a["tag_id"],)).fetchone()[0]]}
                        elif r["act"] == "field":
                            b = {"fields": {str(a["field_id"]): a.get("value")}}
                        elif r["act"] == "due":
                            b = {"due": None if a.get("days") is None else (local_now().date() + timedelta(days=a["days"])).isoformat()}
                        elif r["act"] == "move":
                            b = {"list_id": a.get("list_id") or r["list_id"], **({"section_id": a["section_id"]} if a.get("section_id") else {})}
                        else:  # 2.138.0 D (#2060, review): an action this version does not know does nothing (never a move)
                            return False
                        e = apply_update(c, tid, b)
                        if e:
                            raise BadInput(e)
            except Denied:
                pause = "target" if r["act"] == "move" else "role"
            except BadInput:
                return False  # not a question of rights (e.g. a milestone cannot move): this time nothing happens
            except Exception as e:  # noqa: BLE001  (a rule never breaks the change that triggered it)
                print("list rule", r["id"], "failed:", type(e).__name__, e, flush=True)
                return False
    if pause:
        rul_pause(c, r, pause)
        return False
    return True


def rul_comment(c, r, tid, text):
    """The rule's fixed comment, written as its creator and marked with the rule (comments.rule_name)."""
    from ..core.db import iso_ms
    from ..core.access import collab_all
    from ..collab.comments import comment_pushes
    from ..integrations.webhooks import wh_note
    t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    from ..collab.comments import clean_mentions
    text, _ = clean_mentions(c, t["list_id"], text, tid)  # 2.148.1 H (#2490): mention tokens only of people of the list
    cid = insert_id(c, "INSERT INTO comments(task_id,user_id,body,mentions,created_at,rule_name) VALUES(?,?,?,?,?,?)",
                    (tid, me(), text, "", iso_ms(now_utc()), r["name"]))
    if collab_all():
        from ..agents.core import agent_comment_events
        g.setdefault("pushes", []).extend(comment_pushes(c, t, cid, text, [], [], 0))
        agent_comment_events(c, t, cid, [], [])
    wh_note(c, tid, "comment", cid=cid)
    return cid


# ---------------------------------------------------------------- due date reached (watchdog)
def rul_due_tick(c):
    """Watchdog: rules "due date reached" -- open tasks of the rule's list (subtasks too) whose due day is today (server time
    zone), once per rule, task and due day (list_rule_runs). Each run as the rule's creator inside a request context of its
    own (no request is going on here)."""
    day = local_now().date().isoformat()
    rows = c.execute("""SELECT r.id AS rid, t.id AS tid FROM list_rules r JOIN tasks t ON t.list_id=r.list_id
                        WHERE r.trig='due' AND r.active=1 AND r.deleted_at IS NULL AND t.due=? AND t.status=0 AND t.deleted_at IS NULL
                        AND NOT EXISTS (SELECT 1 FROM list_rule_runs x WHERE x.rule_id=r.id AND x.task_id=t.id AND x.key=?)
                        ORDER BY r.id, t.id LIMIT ?""", (day, "due:" + day, RUL_DUE_BATCH)).fetchall()
    if not rows:
        return
    from ..collab.comments import send_pushes
    for x in rows:
        r = c.execute("SELECT * FROM list_rules WHERE id=?", (x["rid"],)).fetchone()
        if not r or not r["active"]:
            continue
        with app.test_request_context("/api/rules/due"):
            g.db, g.pushes = c, []
            try:
                c.execute("INSERT INTO list_rule_runs(rule_id,task_id,key,at) VALUES(?,?,?,?) ON CONFLICT DO NOTHING",
                          (r["id"], x["tid"], "due:" + day, iso(now_utc())))
                rul_exec(c, r, x["tid"])
                _due_flush(c)
                bump(c)
                c.commit()
                send_pushes(g.pop("pushes", None))
            except Exception as e:  # noqa: BLE001  review N3: one failing row never blocks the others; its marker stays
                c.rollback()
                print("list rule", r["id"], "due run failed:", type(e).__name__, e, flush=True)
                with pg_system(c):  # 2.71.0 (#1457): system on purpose: only the run marker of this rule and task
                    c.execute("INSERT INTO list_rule_runs(rule_id,task_id,key,at) VALUES(?,?,?,?) ON CONFLICT DO NOTHING",
                              (r["id"], x["tid"], "due:" + day, iso(now_utc())))
                c.commit()
            finally:
                g.pop("db", None)  # the watchdog's connection: closed by the watchdog, not by this context
        c.set_ctx(role="system")  # back to the watchdog's own context (the request context above followed the creator)
    c.execute("DELETE FROM list_rule_runs WHERE at<?", (iso(now_utc() - timedelta(days=40)),))
    c.commit()


def _due_flush(c):
    """The webhooks a rule run noted (a request flushes them after its response)."""
    n = g.pop("wh", None)
    if n:
        from ..integrations.webhooks import wh_enqueue
        with pg_system(c):  # 2.71.0 A (#1457): the watchdog queues what the rule run (as its creator) noted, like after_request
            wh_enqueue(c, n)


# ---------------------------------------------------------------- agents: read (API v1) + propose (kind "rule")
def _v1_rules_list(c, lid):
    """2.86.0 (N18): people read rules over the API like on the web (owner / list admin); an agent needs write access to the
    list (it works there and proposes rules), a viewing or participating agent does not see them."""
    from ..agents.core import is_agent
    role = list_role(c, lid)
    if not role:
        raise Denied(404)
    if role not in (WRITE_ROLES if is_agent(g.user) else MANAGE_ROLES):
        raise Denied(403)
    return role


@app.get("/api/v1/lists/<int:lid>/rules")
@v1_view
def v1_rules_get(lid):
    v1_args(())
    c = db()
    _v1_rules_list(c, lid)
    return jsonify(data=[rul_dict(c, r) for r in rul_rows(c, lid)], next_cursor=None)


@app.post("/api/v1/lists/<int:lid>/rules/proposals")
@v1_view
def v1_rules_propose(lid):
    """{name, trigger, action, summary?, user_id?} -> a ready proposal (kind rule) for the list's owner (or user_id: an owner /
    admin of the list). Nothing changes until that person accepts it; the rule then belongs to them."""
    from ..agents.core import JOB_TITLE_MAX, job_dict, need_agent
    from ..agents.proposals import prop_ready_notify, prop_validate, PROP_MAX_BYTES
    from ..agents.usage import usage_block
    v1_args(())
    aid = need_agent()
    if len(request.data or b"") > PROP_MAX_BYTES:
        return v1_err(413, tr("The proposal is too large (at most {0} KB)", PROP_MAX_BYTES // 1024))
    b = v1_json()
    c = db()
    _v1_rules_list(c, lid)
    e = rul_list_ok(c, lid)
    if e:
        return v1_err(409, e)
    pid = rul_prop_person(c, lid, b.get("user_id"))
    if usage_block(c, aid):
        return v1_err(409, tr("You reached your usage limit"))
    if c.execute("SELECT COUNT(*) FROM agent_jobs WHERE agent_id=? AND kind='rule' AND created_at>=?",
                 (aid, iso(now_utc() - timedelta(days=1)))).fetchone()[0] >= RUL_PROP_DAY_MAX:
        return v1_err(429, tr("At most {0} rule proposals per day", RUL_PROP_DAY_MAX))
    inp = {"list_id": lid, "user_id": pid}
    p = prop_validate("rule", {k: v for k, v in b.items() if k != "user_id"}, inp)
    ts = iso(now_utc())
    lname = c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone()[0]
    title = tr("Rule for {0}: {1}", lname, p["rule"]["name"])
    jid = insert_id(c, """INSERT INTO agent_jobs(agent_id,task_id,user_id,title,state,log,created_at,updated_at,kind,input,prop_state,list_id,proposal)
                       VALUES(?,NULL,?,?,'waiting','',?,?,'rule',?,'ready',?,?)""",
                    (aid, pid, title[:JOB_TITLE_MAX], ts, ts, json.dumps(inp, ensure_ascii=False), lid, json.dumps(p, ensure_ascii=False)))
    j = c.execute("SELECT * FROM agent_jobs WHERE id=?", (jid,)).fetchone()
    prop_ready_notify(c, j)
    bump(c)
    c.commit()
    return jsonify({**job_dict(c, j), "proposal": p}), 201


def rul_prop_person(c, lid, uid_arg):
    """Whose card: user_id (an owner / admin of the list, a person) or the list's owner."""
    from ..agents.core import agent_ids
    if uid_arg in (None, ""):
        pid = c.execute("SELECT owner_id FROM lists WHERE id=?", (lid,)).fetchone()[0]
    else:
        pid = _int(uid_arg, "user_id")
    if pid in agent_ids(c) or list_role(c, lid, pid) not in MANAGE_ROLES:
        raise BadInput(tr("Only the owner or an admin of the list can accept a rule (user_id)"))
    return pid


def rul_prop_validate(b, inp):
    """prop_validate for kind rule: {name, trigger, action, summary} -> {rule: {name, trigger, action}}. The references are
    checked as the agent sees them (a target list the agent sees); accepting checks them again as the person."""
    from ..agents.proposals import _p_keys
    _p_keys(b, "", ("kind", "summary", "name", "trigger", "action", "title"))
    c = db()
    lid = int(inp["list_id"])
    rule = {k: b.get(k) for k in ("name", "trigger", "action")}
    f = rul_clean(c, lid, rule, see_only=True)
    rule["name"] = f["name"]
    return {"rule": rule}


def rul_prop_extra(c, j):
    """For the card: the rule in the person's words (names) and whether it can be accepted."""
    p = json.loads(j["proposal"] or "null") or {}
    inp = json.loads(j["input"] or "{}")
    lid = inp.get("list_id")
    if not lid or j["user_id"] != me() or not list_role(c, lid):
        return {}
    rr = p.get("rule") or {}
    fake = {"id": 0, "list_id": lid, "name": rr.get("name") or "", "trig": (rr.get("trigger") or {}).get("kind"),
            "trig_val": rul_trig_val(rr.get("trigger")),  # 2.138.0 D (#2060)
            "act": (rr.get("action") or {}).get("kind"), "act_val": json.dumps({k: v for k, v in (rr.get("action") or {}).items() if k != "kind"}),
            "active": 1, "paused_reason": "", "created_by": None, "created_at": j["created_at"], "updated_at": j["created_at"]}
    name = c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone()
    return {"rule_view": rul_dict(c, fake), "list_name": name[0] if name else ""}


def rul_prop_run(c, j, rec):
    """Accepting (as the person): the rule is created with their rights and belongs to them. rec = the undo record."""
    p = json.loads(j["proposal"])
    lid = int(json.loads(j["input"] or "{}")["list_id"])
    need_list(c, lid, write=False, manage=True)
    e = rul_list_ok(c, lid)
    if e:
        raise Denied(409, e)
    rid = rul_insert(c, lid, rul_clean(c, lid, p["rule"]), me())
    rec.update(rule_id=rid, list=None)
    return rec


def rul_prop_undo(c, j, rec, back=True):
    """Undo: the accepted rule goes to the trash (redo: back)."""
    rid = rec.get("rule_id")
    r = c.execute("SELECT * FROM list_rules WHERE id=?", (rid,)).fetchone() if rid else None
    if not r:
        return 0, []
    need_list(c, r["list_id"], write=False, manage=True)
    ts = iso(now_utc())
    c.execute("UPDATE list_rules SET deleted_at=?, updated_at=? WHERE id=?", (ts if back else None, ts, rid))
    return 1, []


def rul_spec(paths, schemas, op, ok, errs, ref, pid):
    """OpenAPI of the rules routes (2.71.0 A, #1457)."""
    T = "Lists"
    schemas["ListRule"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "list_id": {"type": "integer"}, "name": {"type": "string", "maxLength": RUL_NAME_MAX},
        "trigger": {"type": "object", "description": "kind: section (a task comes into column section_id), done (completed), "
                    "reopen (opened again), ltag (gets the list tag tag_id), due (its due day is today), created (a task is created "
                    "in the list), assigned (a person is newly assigned; user_id = only that person, null = anybody), field (a value "
                    "of the list's custom field field_id changes; value = only when set to that option id of a selection field / "
                    "\"1\" checked, \"0\" unchecked of a checkbox field, null = any change; formula fields never trigger)",
                    "properties": {"kind": {"type": "string", "enum": list(RUL_TRIGGERS)}, "section_id": {"type": "integer"},
                                   "tag_id": {"type": "integer"}, "user_id": {"type": ["integer", "null"]},
                                   "field_id": {"type": "integer"}, "value": {"type": ["string", "null"]}}},
        "action": {"type": "object", "description": "kind: assign (user_id, a person of the list), due (days from today 0.."
                   f"{RUL_DAYS_MAX}, null = clear), comment (text, at most {RUL_TEXT_MAX} characters), move (list_id and / or section_id), "
                   "priority (priority none | low | medium | high), tag (adds the list tag tag_id), field (sets the list's custom "
                   "field field_id to value, checked like a normal field value; null = clear it)",
                   "properties": {"kind": {"type": "string", "enum": list(RUL_ACTIONS)}, "user_id": {"type": "integer"},
                                  "days": {"type": ["integer", "null"]}, "text": {"type": "string"}, "list_id": {"type": "integer"},
                                  "section_id": {"type": ["integer", "null"]}, "priority": {"type": "string", "enum": list(RUL_PRIO)},
                                  "tag_id": {"type": "integer"}, "field_id": {"type": "integer"},
                                  "value": {"type": ["string", "null"]}}},
        "names": {"type": "object", "description": "Names of what the rule refers to (section, tag, trig_user, field, value, user, list, "
                  "section_to, tag_to, field_to, value_to, field_type)"},
        "active": {"type": "boolean"}, "paused_reason": {"type": ["string", "null"], "enum": [None, *RUL_PAUSE]},
        "created_by": {"type": ["integer", "null"], "description": "The rule runs with this person's rights"},
        "created_at": {"type": "string"}, "updated_at": {"type": "string"}}}
    lp = pid(desc="List id")
    paths["/lists/{id}/rules"] = {"get": op(
        "2.71.0 (#1457): the rules of a list (When ... then ...)", T,
        ok({"type": "object", "properties": {"data": {"type": "array", "items": ref("ListRule")}, "next_cursor": {"type": "null"}}})
        | errs("403", "404"), [lp],
        desc="Read only. A rule runs with the rights of the person who set it up; a change made by a rule never triggers "
             "another rule. Agents propose rules (POST .../rules/proposals), they never create or change them.")}
    paths["/lists/{id}/rules/proposals"] = {"post": op(
        "2.71.0 (#1457): propose a rule for a list (the owner or an admin accepts or declines it)", "Agents",
        ok({"type": "object"}, "Created", "201") | errs("400", "403", "404", "409", "413", "429"), [lp],
        body={"type": "object", "required": ["name", "trigger", "action"], "properties": {
            "name": {"type": "string", "maxLength": RUL_NAME_MAX}, "trigger": {"type": "object"}, "action": {"type": "object"},
            "summary": {"type": "string", "description": "Markdown: why this rule helps"}, "title": {"type": "string"},
            "user_id": {"type": "integer", "description": "Owner / admin of the list who decides (default: the list's owner)"}}},
        scope="structure",
        desc=f"Agents only. trigger / action as in ListRule. A ready proposal (kind rule) for the person: News + a card. Accepting "
             f"creates the rule with THEIR rights (it belongs to them, never to you). At most {RUL_PROP_DAY_MAX} per day. The answer "
             "comes as the event job (action approve / reject).")}
