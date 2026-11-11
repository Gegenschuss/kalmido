"""Reactions on comments, tidy suggestions and shared list tags."""
import json
import re
from flask import g, has_request_context, jsonify, request

from ..core.config import app
from ..core.pg import qi, system_ctx
from ..core.objtags import (  # 2.947.0 (#5275): the tags of the shared core
    obj_tags_of, obj_tags_set, otg_add, otg_count, otg_find, otg_in_list, otg_link, otg_of_list, OTG_PROJECT,
    otg_user_rescope)  # 2.955.0 (#5276): promote = a scope change
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, now_utc
from ..accounts.session import me
from ..core.access import Denied, list_role, MANAGE_ROLES, need_collab, need_list, need_task, task_visible, WRITE_ROLES
from ..accounts.orgroles import user_orgs_full  # 2.947.0 (#5275, review F4)
from ..lists.lists import clean_color, clean_list_value
from ..tasks.validation import as_int, CONTENT_MAX, descendants, log_act, PRIORITIES, TITLE_MAX
from ..tasks.tasks import one_task
from ..tasks.lifecycle import apply_update
from ..collab.comments import comment_plain, need_live_comment, user_names
from ..core.objcomments import ocm_extra, ocm_row, ocm_say_refusal  # 2.972.0 (#5272): the comments' core
from ..core.objreact import orx_of, orx_set, orx_toggle  # 2.763.0 (#5269): the reactions of the shared core
from ..core.errors import BadInput, UnknownFields
from ..lists.orglabels import olb_full, olb_match  # 2.609.0 (#3373); 2.947.0 (#5275, review F4): olb_full
from ..api.v1 import _tag_arg, PRIO_NAMES, PRIO_VALUES
from ..lists.folderdefs import fdf_named_gone  # 2.757.0 (#4501)
from ..agents.core import (
    agent_emit, agent_ids, agent_task_data, is_agent, is_approver, list_agents, LTAG_MAX, LTAG_NAME_MAX,
    REACTION_ALIASES, REACTIONS, tidy_agent_of, tidy_candidates, TIDY_MODES,
)


# ---- reactions
def reactions_of(c, cids):
    """{comment id: [{emoji, count, users}]} -- the core's reactions (2.763.0, #5269), up / down / heart first."""
    out = orx_of(c, "comment", cids)
    for lst in out.values():
        lst.sort(key=lambda x: REACTIONS.index(x["emoji"]) if x["emoji"] in REACTIONS else len(REACTIONS))  # stable: others by first use
    return out


def with_reactions(c, comments):
    rs = reactions_of(c, [x["id"] for x in comments])
    for x in comments:
        x["reactions"] = rs.get(x["id"], [])
    return comments


def single_emoji(v):
    """True for exactly one emoji (a ZWJ sequence, skin tone, flag or VS16 variant included), nothing else."""
    import unicodedata
    if not v or len(v) > 16 or any(ch.isspace() for ch in v):
        return False
    for part in v.split("\u200d"):
        base = [ch for ch in part if ch not in "\ufe0f\ufe0e\u20e3" and not 0x1F3FB <= ord(ch) <= 0x1F3FF and not 0xE0020 <= ord(ch) <= 0xE007F]
        ri = [ch for ch in base if 0x1F1E6 <= ord(ch) <= 0x1F1FF]
        if not base or (ri and (len(ri) != 2 or len(base) != 2)) or (not ri and len(base) != 1):
            return False
        if not ri and unicodedata.category(base[0]) != "So":
            return False
    return True


def clean_emoji(v):
    v = str(v or "").strip()
    e = REACTION_ALIASES.get(v)
    if e:
        return e
    if single_emoji(v):
        return v
    raise BadInput(tr("A reaction is one emoji (or up, down, heart)"))


def comment_rx_on(c, k, uid, emoji, on=None):
    """2.763.0 (#5269): the core's one rule for a reaction on comment row k (core/objreact.py orx_toggle): not on one's own
    comment, a guest / read-only person of the task's organisation does not react (taking one back stays). -> on."""
    return orx_toggle(c, "comment", k["id"], uid, emoji, on, own=k["user_id"] == uid,
                      say=lambda: ocm_say_refusal(c, "task", k["task_id"], uid))


def react(c, k, uid, emoji, on):
    """Adds (on) / removes my reaction; on a new 👍 / 👎: approval, suggestion apply / reject, event to an agent author.
    Returns {"approval": ..., "applied": bool} (caller commits). The rule (comment_rx_on) the caller asked before."""
    res = {"approval": None, "applied": False}
    if emoji in ("up", "down") and k["suggestion"]:  # 2.574.0 (#3376, review F2): a thumb taken back and another one at the same
        k = ocm_row(c, k["id"], lock=True) or k  # time read the stored state in turn
    if not on:
        orx_set(c, "comment", k["id"], uid, emoji, False)
        sg = json.loads(k["suggestion"]) if emoji == "up" and k["suggestion"] else None
        if sg and sg.get("state") == "open" and any(isinstance(a, dict) and a.get("by") == uid for a in sg.get("approvals") or []):
            sg["approvals"] = [a for a in sg["approvals"] if not (isinstance(a, dict) and a.get("by") == uid)]  # 2.574.0 (#3376): a first of two taken back
            ocm_extra(c, k["id"], "suggestion", json.dumps(sg, ensure_ascii=False))
        return res
    if not orx_set(c, "comment", k["id"], uid, emoji, True):
        return res
    t = c.execute("SELECT * FROM tasks WHERE id=?", (k["task_id"],)).fetchone()
    author = c.execute("SELECT * FROM users WHERE id=?", (k["user_id"],)).fetchone() if k["user_id"] else None
    from .cchoice import lv_jload
    card = lv_jload(k["choices"]) if "choices" in k.keys() else None  # 2.87.9 (#1963): a thumb never decides an approval card
    if is_agent(author) and emoji in ("up", "down") and uid != author["id"] and is_approver(c, t, uid) \
            and not (isinstance(card, dict) and (card.get("approval") or card.get("permission"))):
        res["approval"] = "approved" if emoji == "up" else "rejected"
    sug = json.loads(k["suggestion"]) if k["suggestion"] else None
    if res["approval"] and sug and sug.get("kind") in ("integrate", "deploy", "merge_request") \
            and not is_approver(c, t, uid, agent=author["id"], assignee=sug.get("kind") == "merge_request"):  # 2.126.0 B (#1975): only who may address the agent decides
        res["approval"] = None  # 2.148.1 D (#2495): integrate / deploy: the assignee alone does not decide (as approval jobs, #1974)
    ap0 = res["approval"]
    from ..agents.gates import gate_decide, gate_two_eyes
    if sug and sug.get("kind") in ("integrate", "deploy"):  # 2.26.0 (#949): only an approver decides (see agents/gates.py)
        if sug.get("state") == "open" and res["approval"]:
            res["gate"] = gate_decide(c, k, t, uid, emoji == "up")
            if res["gate"] in ("blocked", "waiting"):  # open checklist: 👍 alone does not approve a deploy; 2.574.0 (#3376): nor a first of two
                res["approval"] = None
    elif sug and sug.get("kind") == "merge_request":  # 2.2.0 (#339): only an approver decides; the agent merges itself
        if sug.get("state") == "open" and res["approval"] == "approved" and gate_two_eyes(c, k, t, sug, uid):
            res["merge"], res["approval"] = "waiting", None  # 2.574.0 (#3376): the list wants a second approver
        elif sug.get("state") == "open" and res["approval"]:
            st = "approved" if emoji == "up" else "rejected"
            ocm_extra(c, k["id"], "suggestion",
                      json.dumps({**sug, "state": st, "by": uid, "at": iso(now_utc())}, ensure_ascii=False))
            res["merge"] = st
            if st == "approved":  # 2.60.0 C (#1512): an approved pull request counts as the review (by someone who may approve it)
                from ..tasks.review import rvw_approved_by_pr
                rvw_approved_by_pr(c, t["id"], f"{sug.get('repo') or ''}#{sug.get('number') or ''}", sug.get("pr_url"), uid=uid)
    elif sug and sug.get("state") == "open" and emoji in ("up", "down") and not is_agent(g.user) \
            and task_visible(c, t["id"], uid, write=True) and not t["deleted_at"]:
        if emoji == "up":
            suggestion_apply(c, k, t)
            res["applied"] = True
        else:
            ocm_extra(c, k["id"], "suggestion",
                      json.dumps({**sug, "state": "rejected", "by": uid, "at": iso(now_utc())}, ensure_ascii=False))
    # 2.126.0 review: logged only once the approval counts; 2.574.0 (#3376, review F3): after the gate, a first of two approvals as
    # waiting (like the decide route), a blocked one not at all. Own block after the kinds: the plain apply / reject way above is
    # the else of the kinds and never runs for a gate / merge request (#3506: as an elif here it applied a viewer's 👍)
    if res["approval"]:
        log_act(c, t["id"], "approval", {"agent": author["id"], "comment": k["id"], "ok": emoji == "up"})
    elif ap0 and "waiting" in (res.get("gate"), res.get("merge")):
        log_act(c, t["id"], "approval", {"agent": author["id"], "comment": k["id"], "ok": True, "waiting": True})
    if is_agent(author) and uid != author["id"] and task_visible(c, t["id"], author["id"], full=True):
        k2 = ocm_row(c, k["id"])
        agent_emit(c, author["id"], "reaction", agent_task_data(
            c, t["id"], author["id"], comment={"id": k2["id"], "text": comment_plain(c, k2["body"]),
                                               "suggestion": json.loads(k2["suggestion"]) if k2["suggestion"] else None},
            reaction={"emoji": emoji, "user": {"id": uid, "name": user_names(c, [uid]).get(uid, "")}}, approval=res["approval"],
            applied=res["applied"], **({"merge_request": {"pr_url": sug["pr_url"], "number": sug.get("number"), "repo": sug.get("repo"),
                                                          "state": json.loads(k2["suggestion"])["state"]}}
                                       if sug and sug.get("kind") == "merge_request" else {}),
            **({"gate": _gate_ev(json.loads(k2["suggestion"]))} if sug and sug.get("kind") in ("integrate", "deploy") else {})))
    return res


def _gate_ev(sug):
    from ..agents.gates import gate_event
    return gate_event(sug)


@app.post("/api/comments/<int:cid>/reactions")
def comment_react(cid):
    """{emoji: up|down|heart or one emoji, on?: bool} -- toggles my reaction (on given: sets it)."""
    need_collab()
    c = db()
    k, _ = need_live_comment(c, cid)
    b = body()
    emoji = clean_emoji(b.get("emoji"))
    try:  # 2.763.0 (#5269): the core's rule (own comment 400, a guest / read-only person 403)
        on = comment_rx_on(c, k, me(), emoji, bool(b["on"]) if isinstance(b.get("on"), bool) else None)
    except BadInput as e:
        return err(str(e))
    res = react(c, k, me(), emoji, on)
    bump(c)
    c.commit()
    k = ocm_row(c, cid)
    return jsonify(ok=True, reactions=reactions_of(c, [cid]).get(cid, []), suggestion=json.loads(k["suggestion"]) if k["suggestion"] else None, **res)


# ---- tidy: suggestions (the comment's extra.suggestion, 2.972.0 #5272) and applying them
def clean_suggestion(c, t, s):
    if not isinstance(s, dict):
        raise BadInput(tr("Invalid value: {0}", "suggestion"))
    unknown = sorted(k for k in s if k not in ("title", "notes", "section_id", "list_tags", "priority"))
    if unknown:
        raise UnknownFields(unknown)
    out = {}
    if s.get("title") is not None:
        if not isinstance(s["title"], str) or not s["title"].strip():
            raise BadInput(tr("Invalid value: {0}", "title"))
        out["title"] = s["title"].strip()[:TITLE_MAX]
    if s.get("notes") is not None:
        if not isinstance(s["notes"], str):
            raise BadInput(tr("Invalid value: {0}", "notes"))
        out["notes"] = s["notes"][:CONTENT_MAX // 2]
    if s.get("section_id") is not None:
        sid = as_int(s["section_id"], "section_id", 1)
        if not c.execute("SELECT 1 FROM sections WHERE id=? AND list_id=?", (sid, t["list_id"])).fetchone():
            raise BadInput(tr("Invalid value: {0}", "section_id"))
        out["section_id"] = sid
    if s.get("list_tags") is not None:
        out["list_tags"] = clean_ltag_names(s["list_tags"])
    if s.get("priority") is not None:
        p = s["priority"]
        if isinstance(p, str) and p in PRIO_VALUES:
            p = PRIO_VALUES[p]
        if isinstance(p, bool) or p not in PRIORITIES:
            raise BadInput(tr("Invalid value: {0}", "priority"))
        out["priority"] = PRIO_NAMES[p]
    if not out:
        raise BadInput(tr("Nothing to change"))
    return out


def tidy_apply(c, t, s):
    """Applies a tidy result s ({title, notes, section_id, list_tags, priority}) to task row t as the current user. The
    original title + notes stay verbatim at the top of the notes ("**Original (creator):** ..."), once."""
    b = {}
    content = t["content"] or ""
    if "title" in s or "notes" in s:
        if content.lstrip().startswith("**Original ("):
            keep = content.rstrip()
        else:
            who = user_names(c, [t["created_by"]]).get(t["created_by"]) or tr("unknown")
            keep = f"**Original ({who}):** {t['title']}" + (f"\n\n{content.strip()}" if content.strip() else "")
        new = (s.get("notes") or "").strip()
        b["content"] = keep + (f"\n\n{new}" if new and new not in keep else "")
    if s.get("title"):
        b["title"] = s["title"]
    if "section_id" in s:
        b["section_id"] = s["section_id"]
    if "priority" in s:
        b["priority"] = PRIO_VALUES.get(s["priority"], 0)
    if "list_tags" in s:
        b["ltags"] = list(dict.fromkeys(ltag_names(c, t["id"]) + s["list_tags"]))
    e = apply_update(c, t["id"], b)
    if e:
        raise BadInput(e)
    log_act(c, t["id"], "tidy", {"by": me()})


def suggestion_apply(c, k, t):
    sug = json.loads(k["suggestion"])
    tidy_apply(c, t, {x: sug[x] for x in ("title", "notes", "section_id", "list_tags", "priority") if x in sug})
    ocm_extra(c, k["id"], "suggestion",
              json.dumps({**sug, "state": "applied", "by": me(), "at": iso(now_utc())}, ensure_ascii=False))


@app.post("/api/comments/<int:cid>/apply")
def comment_apply(cid):
    """Applies the tidy suggestion of a comment (someone who may change the task)."""
    need_collab()
    c = db()
    k, _ = need_live_comment(c, cid)
    t = c.execute("SELECT * FROM tasks WHERE id=?", (k["task_id"],)).fetchone()
    need_task(c, t["id"], write=True)
    sug = json.loads(k["suggestion"]) if k["suggestion"] else None
    if not sug:
        raise Denied(404)
    if sug.get("kind") in ("merge_request", "integrate", "deploy"):
        return err(tr("A merge request is approved with 👍 (or rejected with 👎)"), 409)
    if sug.get("state") != "open" or t["deleted_at"]:
        return err(tr("This suggestion was already handled"), 409)
    suggestion_apply(c, k, t)
    orx_set(c, "comment", cid, me(), "up", True)
    author = c.execute("SELECT * FROM users WHERE id=?", (k["user_id"],)).fetchone() if k["user_id"] else None
    if is_agent(author) and task_visible(c, t["id"], author["id"], full=True):
        k2 = ocm_row(c, cid)
        agent_emit(c, author["id"], "reaction", agent_task_data(
            c, t["id"], author["id"], comment={"id": cid, "text": comment_plain(c, k2["body"]), "suggestion": json.loads(k2["suggestion"])},
            reaction={"emoji": "up", "user": {"id": me(), "name": user_names(c, [me()]).get(me(), "")}},
            approval="approved" if is_approver(c, t, me()) else None, applied=True))
    bump(c)
    c.commit()
    return jsonify(ok=True, task=one_task(c, t["id"]))


def list_tidy_update(c, lid, mode=None, agent=None, set_agent=False):
    """lists.agent_tidy (mode) and 2.4.1 (#379) lists.tidy_agent (agent, set_agent: it was given): owner / list admins (or,
    in a list an agent owns, its members with edit rights); never an agent. The tidy agent must be one of the list's
    agents with edit rights (tidy_candidates)."""
    if mode is not None and mode not in TIDY_MODES:
        raise BadInput(tr("Invalid value: {0}", "agent_tidy"))
    if set_agent and agent is not None and (isinstance(agent, bool) or not isinstance(agent, int)):
        raise BadInput(tr("Invalid value: {0}", "tidy_agent_id"))
    role = need_list(c, lid, write=False)
    owner = c.execute("SELECT owner_id FROM lists WHERE id=?", (lid,)).fetchone()[0]
    agent_owned = owner in agent_ids(c)
    if is_agent(g.user) or not (role in MANAGE_ROLES or (agent_owned and role in WRITE_ROLES)):
        raise Denied(403, tr("Only the project owner or a project admin can change this"))
    cands = tidy_candidates(c, lid)
    if mode is not None and mode != "off" and not list_agents(c, lid):
        return tr("Share the project with an agent first")
    if set_agent and agent is not None and agent not in cands:
        raise BadInput(tr("This agent cannot tidy up the project (it needs edit rights)"))
    if mode is not None and mode != "off" and not cands:
        return tr("Give an agent of this project edit rights first")
    if set_agent:
        c.execute("UPDATE lists SET tidy_agent=? WHERE id=?", (agent, lid))
    if mode is not None:
        c.execute("UPDATE lists SET agent_tidy=? WHERE id=?", (mode, lid))
        if mode != "off" and c.execute("SELECT tidy_agent FROM lists WHERE id=?", (lid,)).fetchone()[0] not in cands:
            c.execute("UPDATE lists SET tidy_agent=? WHERE id=?", (tidy_agent_of(c, lid, cands), lid))
    return None


# ---- list tags
LTAG_COLS = ("name", "color", "sort")  # what PATCH /api/list-tags/<id> changes (the allowlist of qi)


def clean_ltag_name(v):
    n = re.sub(r"[\x00-\x1f]", "", str(v or "")).strip().lstrip("#").strip()
    if not n or len(n) > LTAG_NAME_MAX or not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", tr("Tag")))
    return n


def clean_ltag_names(v):
    if not isinstance(v, list) or len(v) > 50:
        raise BadInput(tr("Invalid value: {0}", "list_tags"))
    return list(dict.fromkeys(clean_ltag_name(x) for x in v))


def ltags_of_lists(c, lids):
    """{list id: [{id, name, color, org_tag_id}]} -- the project tags of the lists, then the labels of their organisation that a
    task of the list carries (org_tag_id = the label's id; 2.947.0 (#5275): the label itself, no copy in the project). A label
    of an organisation the reader is not a member of is not there (row-level security)."""
    out = {}
    lids = sorted({int(x) for x in lids if x})
    if not lids:
        return out
    # review F7: the order of the core (sort, then the name in any case, then the id) -- UNION orders by output columns only
    for r in c.execute("""SELECT CAST(ot.scope_id AS BIGINT) AS lid, ot.id, ot.name, ot.color, NULL AS org_tag_id, 0 AS o, ot.sort,
                          lower(ot.name) AS lname FROM obj_tags ot WHERE ot.scope_kind='list' AND ot.scope_id = ANY(CAST(? AS TEXT[]))
                          UNION SELECT t.list_id, ot.id, ot.name, ot.color, ot.id, 1, ot.sort, lower(ot.name) FROM obj_tag_links k
                          JOIN tasks t ON t.id=k.obj_id AND k.kind='task' JOIN lists l ON l.id=t.list_id
                          JOIN obj_tags ot ON ot.id=k.tag_id AND ot.scope_kind='org' AND ot.scope_id=CAST(l.org_id AS TEXT)
                          WHERE t.list_id = ANY(CAST(? AS BIGINT[]))
                          ORDER BY lid, o, sort, lname, id""", ([str(x) for x in lids], lids)):
        out.setdefault(r["lid"], []).append({"id": r["id"], "name": r["name"], "color": r["color"], "org_tag_id": r["org_tag_id"]})
    return out


def ltags_for(c, ids):
    """{task id: [project tag names]} (only tags of the task's current project and labels of its organisation)."""
    return {k: [x["name"] for x in v] for k, v in obj_tags_of(c, ids).items()}


def ltag_names(c, tid):
    return ltags_for(c, [tid]).get(tid, [])


def ltag_get_or_create(c, lid, name, create):
    """The id of the tag named name (any case) a task of list lid gets: the project's own tag, else a label of the project's
    organisation (one a task of the project carries already, or any for a person with the organisation's full view: olb_match),
    else a new project tag when create (the person may change the list). Review F6 (2.947.0): a label the writer may see
    (olb_match) comes before a project tag of the same name -- such a tag is left only where a person without the full view
    made it; a project joining the organisation turns its tags into the labels (trigger kalmido_otg_org_moved)."""
    ol = olb_match(c, lid, name)  # 2.609.0 (#3373), 2.947.0 (#5275): the label itself goes on the task
    if ol:
        return ol["id"]
    r = otg_find(c, "list", lid, name)
    if r:
        return r["id"]
    if not create:
        raise BadInput(tr("Unknown project tag: {0}", name))
    if otg_count(c, "list", lid) >= LTAG_MAX:
        raise BadInput(tr("At most {0} project tags", LTAG_MAX))
    u = getattr(g, "user", None) if has_request_context() else None
    return otg_add(c, "list", lid, name, by=u["id"] if u else None)


def _ltag_src():
    """(src, by) of a link the current request makes: an agent's / a person's (outside a request: the server's own)."""
    u = getattr(g, "user", None) if has_request_context() else None
    if not u:
        return "auto", None
    try:
        return ("agent" if (u["kind"] or "user") == "agent" else "person"), u["id"]
    except (KeyError, IndexError):
        return "person", u["id"]


def set_ltags(c, tid, names, log=True):
    """The project tags of task tid (names; missing ones are created when the current user may change the list). Logged.
    2.947.0 (#5275): links of the core (obj_tags_set; a label of an organisation the writer cannot see stays on the task)."""
    t = c.execute("SELECT list_id FROM tasks WHERE id=?", (tid,)).fetchone()
    names = clean_ltag_names(names)
    before = ltag_names(c, tid)
    create = list_role(c, t["list_id"]) in WRITE_ROLES if has_request_context() and getattr(g, "user", None) else True
    ids = [ltag_get_or_create(c, t["list_id"], n, create) for n in names]
    src, by = _ltag_src()
    obj_tags_set(c, tid, ids, src=src, by=by)
    after = ltag_names(c, tid)
    if log and sorted(before, key=str.casefold) != sorted(after, key=str.casefold):
        log_act(c, tid, "ltags", {"tags": after})


def ltags_follow(c, tid, lid):
    """After a move to list lid: the project tags of tid and its subtasks follow by name (created there when the mover may
    change that list, else dropped). 2.947.0 (#5275): a label of the organisation stays as it is when lid is in the same
    organisation; else it becomes the tag of that name there (a project tag or the other organisation's label)."""
    create = list_role(c, lid) in WRITE_ROLES if has_request_context() and getattr(g, "user", None) else True
    keep = {(k, v) for k, v in otg_of_list(c, lid)}
    src, by = _ltag_src()
    for x in [tid] + descendants(c, tid):
        # review F7: read as "system" -- a mover who is no member of the old organisation (row-level security) would leave its
        # labels' links behind on the task, hidden; they follow by name like every other tag (as a label's copy in the project did)
        with system_ctx(c):
            rows = c.execute("""SELECT ot.id, ot.name, ot.color, ot.scope_kind, ot.scope_id FROM obj_tag_links k JOIN obj_tags ot ON ot.id=k.tag_id
                                WHERE k.kind='task' AND k.obj_id=? AND ot.scope_kind = ANY(CAST(? AS TEXT[]))""", (x, list(OTG_PROJECT))).fetchall()
        gone = [r for r in rows if (r["scope_kind"], r["scope_id"]) not in keep]
        if not gone:
            continue
        c.execute("DELETE FROM obj_tag_links WHERE kind='task' AND obj_id=? AND tag_id = ANY(CAST(? AS BIGINT[]))", (x, [r["id"] for r in gone]))
        for r in gone:
            try:
                i = ltag_get_or_create(c, lid, r["name"], create)
            except BadInput:
                continue
            if r["color"]:
                c.execute("UPDATE obj_tags SET color=? WHERE id=? AND scope_kind='list' AND color=''", (r["color"], i))
            otg_link(c, i, x, src=src, by=by)


def ltag_row(c, tag_id, lid=None):
    """The answer of the tag routes: {id, list_id, name, color, sort, org_tag_id}."""
    r = c.execute("SELECT * FROM obj_tags WHERE id=?", (tag_id,)).fetchone()
    return {"id": r["id"], "list_id": int(r["scope_id"]) if r["scope_kind"] == "list" else lid, "name": r["name"], "color": r["color"],
            "sort": r["sort"], "org_tag_id": r["id"] if r["scope_kind"] == "org" else None}


def need_ltag(c, tag_id, write=True, lid=None, label=False):
    """A project tag (scope list) the person may see / change, or with lid a label of lid's organisation (in that project).
    label=True: a label without lid as the reader sees it -- for the answer "change it in the organisation's labels" only,
    nothing is written with it. Review F4 (2.947.0): that only with the organisation's full view (a guest / accounting member
    passes row-level security, but gets no label it does not see in a project); with lid a label of the organisation only for
    the full view or when a task of lid carries it (otg_in_list full=olb_full)."""
    r = c.execute("SELECT * FROM obj_tags WHERE id=? AND scope_kind = ANY(CAST(? AS TEXT[]))", (tag_id, list(OTG_PROJECT))).fetchone()
    if not r:
        raise Denied(404)
    if r["scope_kind"] == "list":
        need_list(c, int(r["scope_id"]), write=write)
        return r
    if lid is None and label:
        if r["org_id"] not in user_orgs_full(c, me()):
            raise Denied(404)
        return r
    if lid is None or not otg_in_list(c, tag_id, lid, full=olb_full(c)):
        raise Denied(404)
    need_list(c, lid, write=write)
    return r


def ltag_fields(b, partial=False):
    out = {}
    if "name" in b or not partial:
        out["name"] = clean_ltag_name(b.get("name"))
    if "color" in b:
        out["color"] = clean_color(b.get("color") or "")
    if "sort" in b:
        out["sort"] = clean_list_value("sort", b["sort"])
    return out


def _ltag_lid_arg():
    v = request.args.get("list_id")
    try:
        return int(v) if v not in (None, "") else None
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "list_id")) from None


@app.post("/api/lists/<int:lid>/tags")
def ltag_create(lid):
    """{name, color?} -- a new project tag (members with edit rights); the name of a label of the organisation that the
    person may use gives that label."""
    c = db()
    need_list(c, lid)
    f = ltag_fields(body())
    if otg_find(c, "list", lid, f["name"]) or any(x["name"].casefold() == f["name"].casefold() and x["org_tag_id"]
                                                    for x in ltags_of_lists(c, [lid]).get(lid, [])):
        return err(tr("This tag already exists in the project"), 409)
    i = ltag_get_or_create(c, lid, f["name"], True)
    if f.get("color"):
        c.execute("UPDATE obj_tags SET color=? WHERE id=? AND scope_kind='list'", (f["color"], i))
    bump(c)
    c.commit()
    return jsonify(ltag_row(c, i, lid)), 201


@app.patch("/api/list-tags/<int:tag_id>")
def ltag_update(tag_id, lid=None):
    """{name?, color?, sort?} -- a project tag; a label of the organisation (?list_id= / lid: in that project) changes only in
    the organisation's labels (409 for name / colour)."""
    c = db()
    try:
        lid = lid if lid is not None else _ltag_lid_arg()
        r = need_ltag(c, tag_id, lid=lid, label=True)
    except BadInput as e:
        return err(str(e))
    f = ltag_fields(body(), partial=True)
    if r["scope_kind"] == "org":  # 2.609.0 (#3373): a label changes only in the organisation's labels (its order too, 2.947.0)
        # review F7: the order too -- a label's place is the organisation's (no silent 200 for a sort that did nothing)
        if any(k in f and f[k] != r[k] for k in ("name", "color", "sort")):
            return err(tr("This label belongs to the organisation: change it in the organisation's labels"), 409)
        return jsonify(ltag_row(c, tag_id, lid))
    lid = int(r["scope_id"])
    if "name" in f and c.execute("SELECT 1 FROM obj_tags WHERE scope_kind='list' AND scope_id=? AND lower(name)=lower(?) AND id!=?",
                                 (r["scope_id"], f["name"], tag_id)).fetchone():
        return err(tr("This tag already exists in the project"), 409)
    if f:
        c.execute(f"UPDATE obj_tags SET {','.join(qi(k, LTAG_COLS) + '=?' for k in f)} WHERE id=?", [*f.values(), tag_id])
        if "name" in f and f["name"].casefold() != r["name"].casefold():  # 2.757.0 (#4501): a folder's tag renamed -> the list differs
            fdf_named_gone(c, lid, "list_tags", r["name"])
        bump(c)
        c.commit()
    return jsonify(ltag_row(c, tag_id))


@app.delete("/api/list-tags/<int:tag_id>")
def ltag_delete(tag_id, lid=None):
    """Removes the project tag from every task of the project (answers the task ids, for the undo). 2.947.0 (#5275): a label of
    the organisation (?list_id=) is taken off the tasks of that project only; the label stays in the organisation."""
    c = db()
    try:
        lid = lid if lid is not None else _ltag_lid_arg()
        r = need_ltag(c, tag_id, lid=lid)
    except BadInput as e:
        return err(str(e))
    if r["scope_kind"] == "org":
        ids = [x[0] for x in c.execute("""DELETE FROM obj_tag_links k USING tasks t WHERE k.kind='task' AND k.tag_id=? AND t.id=k.obj_id
                                          AND t.list_id=? RETURNING k.obj_id""", (tag_id, lid))]
    else:
        lid = int(r["scope_id"])
        ids = [x[0] for x in c.execute("SELECT obj_id FROM obj_tag_links WHERE tag_id=? AND kind='task'", (tag_id,))]
        c.execute("DELETE FROM obj_tags WHERE id=?", (tag_id,))
    fdf_named_gone(c, lid, "list_tags", r["name"])  # 2.757.0 (#4501): a folder's tag deleted -> the list differs
    bump(c)
    c.commit()
    return jsonify(ok=True, ids=ids, tag={"name": r["name"], "color": r["color"], "list_id": lid})


@app.post("/api/lists/<int:lid>/tags/promote")
def ltag_promote(lid):
    """{tag} -- my personal tag becomes a list tag: every task of the list that carries it gets the list tag instead."""
    c = db()
    need_list(c, lid)
    try:
        tag = _tag_arg(body().get("tag"))
        name = clean_ltag_name(tag)
    except BadInput as e:
        return err(str(e))
    i = ltag_get_or_create(c, lid, name, True)
    # 2.955.0 (#5276): a scope change in the core -- the links of my personal tag (any case) on the list's tasks move to the
    # project's tag (when and by whom they were set stays); my tag goes when no other task keeps it
    ids = otg_user_rescope(c, me(), tag, i, lid)
    for x in ids:
        log_act(c, x, "ltags", {"tags": ltag_names(c, x)})
    bump(c)
    c.commit()
    return jsonify(ok=True, id=i, name=name, count=len(ids), ids=ids)
