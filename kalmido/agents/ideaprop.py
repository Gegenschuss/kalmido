"""2.156.0 A (#1201): "Add ideas" on a branch of the mind map -- a CONNECTED agent proposes sub-branches. Kalmido itself
calls no model: a person asks one of the agents the list is shared with (POST /api/proposals {kind: ideas, agent_id,
list_id, branch, hint?}), the agent gets the event job_request with exactly the input below and answers with one proposal
(POST /api/v1/agent/jobs/<id>/proposal, MCP submit_proposal) {items: [{title, children?: [{title}]}]}. The mind map shows
the items as pale branches; the person takes single ones or all of them (they become tasks as that person, history "from a
proposal by <agent>") or drops them (POST /api/proposals/<id>/ideas {take, drop}); once every item is decided the job
ends (applied / discarded) and the agent hears it. The generic apply / discard / undo of proposals work as well.

Tenant boundary: only agents the list is shared with (and that the person may address there, as the client report); the
agent gets the branch's path (section, parent titles, the branch) and the list's name, the number of levels still free,
the person's hint and language -- nothing else. Proposals are stored only for lists the agent still has access to.
"""
import json

from flask import g, jsonify

from ..core.config import app
from ..core.i18n import N_, tr
from ..core.db import body, bump, db, err, iso, now_utc, usettings
from ..core.pg import insert_id
from ..core.schema import MAX_DEPTH
from ..core.access import Denied, list_role, need_collab, need_list, need_task, task_visible, WRITE_ROLES
from ..personal.timetrack import BadInput
from ..tasks.validation import check_parent, depth
from ..agents.core import agent_emit, agent_row, is_agent, job_dict, JOB_TITLE_MAX
from ..agents.proposals import (
    PROP_LIMITS, PROP_OPEN_MAX, PROP_HINT_MAX, PROP_SUBS_MAX, PROP_TITLE_MAX, _p_keys, _p_list, _p_str, need_prop, prop_insert,
    prop_notify_agent,
)
from ..collab.comments import lang_of, user_names

IDP_TITLE = N_("Ideas: {0}")
IDP_KIDS = 2       # an idea may carry sub-ideas one level down (keys "i" and "i.k" of the generic apply)
IDP_PATH_MAX = 12  # titles in the path (list name not counted)
IDP_NO_AGENT = N_("This agent cannot make proposals for you")


def idp_agents(c, uid, lid):
    """Agents uid may ask for ideas in list lid: proposals allowed, the list shared with the agent, uid may address it there."""
    from ..agents.asstprop import ast_list_agents
    from ..agents.safety import agent_reach
    # review: also within the agent's list restriction (agents.list_ids), like agent_emit's gate
    return [a for a in ast_list_agents(c, uid, lid) if lid in agent_reach(c, a["user_id"])]


def idp_agents_get(c, uid, args):
    """GET /api/proposals/agents?kind=ideas&list_id= -> {agents: [{id, name, avatar, limit_reached, online}]} (people only)."""
    from ..agents.asstprop import _pub
    try:
        lid = int(args.get("list_id") or 0)
    except (TypeError, ValueError):
        lid = 0
    if not lid:
        raise BadInput(tr("Invalid value: {0}", "list_id"))
    need_list(c, lid, write=False)
    return jsonify(agents=[_pub(c, a) for a in idp_agents(c, uid, lid)])


def _target(c, lid, branch):
    """branch "r" (the list) | "s<id>" (a section) | "t<id>" (a task) of list lid -> (kind, id, row) or BadInput / 404."""
    b = str(branch or "")
    if b == "r":
        return "list", None, None
    try:
        n = int(b[1:])
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "branch")) from None
    if b[:1] == "s":
        r = c.execute("SELECT id, name, list_id FROM sections WHERE id=?", (n,)).fetchone()
        if not r or r["list_id"] != lid:
            raise Denied(404)
        return "section", None, r
    if b[:1] == "t":
        need_task(c, n)
        r = c.execute("SELECT * FROM tasks WHERE id=?", (n,)).fetchone()
        if r["list_id"] != lid or r["deleted_at"]:
            raise Denied(404)
        return "task", n, r
    raise BadInput(tr("Invalid value: {0}", "branch"))


def _path(c, kind, row):
    """The titles from the top of the map down to the branch (section, parents, the branch itself)."""
    if kind == "list":
        return []
    if kind == "section":
        return [str(row["name"] or "")[:PROP_TITLE_MAX]]
    out, cur, seen, top = [], row, set(), row
    while cur and cur["id"] not in seen and len(out) < IDP_PATH_MAX:
        seen.add(cur["id"])
        out.insert(0, cur["title"])
        top = cur
        cur = c.execute("SELECT id, title, parent_id, section_id FROM tasks WHERE id=?", (cur["parent_id"],)).fetchone() \
            if cur["parent_id"] else None
    if top["section_id"] and not top["parent_id"]:
        s = c.execute("SELECT name FROM sections WHERE id=?", (top["section_id"],)).fetchone()
        if s:
            out.insert(0, s["name"])
    return [str(x or "")[:PROP_TITLE_MAX] for x in out]


def _levels(c, kind, tid):
    """How many levels of tasks still fit below the branch (MAX_DEPTH counts the top tasks as level 1)."""
    return MAX_DEPTH if kind != "task" else MAX_DEPTH - 1 - depth(c, tid)


def idp_request(c, uid, b):
    """POST /api/proposals {kind: ideas, agent_id, list_id, branch, hint?} -> a proposal job + job_request to that agent."""
    from ..agents.usage import usage_block
    from ..collab.liste2eguard import le2b_list_locked, le2b_off
    _p_keys(b, "", ("agent_id", "kind", "list_id", "branch", "hint"))
    try:
        aid, lid = int(b.get("agent_id") or 0), int(b.get("list_id") or 0)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", "list_id")) from None
    need_list(c, lid, write=False)
    if list_role(c, lid) not in WRITE_ROLES:
        raise Denied(403)
    if le2b_list_locked(c, lid):  # 2.64.1 B (#1817): agents never get texts of a list with the lock
        return err(le2b_off(), 409)
    kind, tid, row = _target(c, lid, b.get("branch"))
    if kind == "task":
        e = check_parent(c, None, tid)  # #1949: a branch on the deepest level takes no more sub-branches
        if e:
            raise BadInput(e)
    if not [a for a in idp_agents(c, uid, lid) if a["user_id"] == aid] or (kind == "task" and not task_visible(c, tid, aid)):
        return err(tr(IDP_NO_AGENT), 404)  # review: a participant agent only hears of branches it may see
    a = agent_row(c, aid)
    if usage_block(c, aid):
        return err(tr("{0} reached its usage limit", a["display_name"] or a["username"]), 409)
    if c.execute("SELECT COUNT(*) FROM agent_jobs WHERE user_id=? AND kind IS NOT NULL AND state IN ('running','waiting')",
                 (uid,)).fetchone()[0] >= PROP_OPEN_MAX:
        return err(tr("You have {0} open proposal requests: apply or discard some first", PROP_OPEN_MAX), 429)
    lname = c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone()["name"]
    inp = {"list": lname, "path": _path(c, kind, row), "branch": kind, "levels": min(IDP_KIDS, _levels(c, kind, tid)),
           "hint": _p_str(b.get("hint"), "hint", PROP_HINT_MAX, line=False) or None, "lang": lang_of(usettings(c, uid)),
           "target": "r" if kind == "list" else ("t" + str(tid) if kind == "task" else "s" + str(row["id"]))}
    title = tr(IDP_TITLE, (inp["path"][-1] if inp["path"] else lname)[:80])
    ts = iso(now_utc())
    jid = insert_id(c, """INSERT INTO agent_jobs(agent_id,task_id,user_id,title,state,log,created_at,updated_at,kind,input,prop_state,list_id)
                       VALUES(?,?,?,?,'running','',?,?,?,?,'requested',?)""",
                    (aid, tid, uid, title[:JOB_TITLE_MAX], ts, ts, "ideas", json.dumps(inp, ensure_ascii=False), lid))
    j = c.execute("SELECT * FROM agent_jobs WHERE id=?", (jid,)).fetchone()
    agent_emit(c, aid, "job_request", {"list_id": lid, "task_id": tid if kind == "task" else None, "job": job_dict(c, j), "kind": "ideas", "input": inp, "limits": {**PROP_LIMITS, **IDP_LIMITS},
                                       "requested_by": {"id": uid, "name": user_names(c, [uid]).get(uid, "")}})
    bump(c)
    c.commit()
    print("proposal request", jid, "ideas", "agent", aid, "by user", uid, flush=True)
    return jsonify(job_dict(c, j)), 201


IDP_LIMITS = {"ideas_max": PROP_SUBS_MAX, "ideas_levels": IDP_KIDS}


# ---------------------------------------------------------------- the agent's answer
def idp_validate(b, inp):
    """prop_validate: {items: [{title, children?: [{title}]}]}; children only where input.levels allows (deeper ones are cut),
    at most PROP_SUBS_MAX ideas in all."""
    _p_keys(b, "", ("kind", "summary", "items"))
    raw = _p_list(b.get("items"), "items", PROP_SUBS_MAX)
    if not raw:
        raise BadInput(tr("Missing field: {0}", "items"))
    deep, n, items = int(inp.get("levels") or 1) >= 2, 0, []
    for i, t in enumerate(raw):
        w = f"items[{i}]"
        _p_keys(t, w, ("title", "children"))
        kids = []
        for k, s in enumerate(_p_list(t.get("children"), w + ".children", PROP_SUBS_MAX)):
            _p_keys(s, f"{w}.children[{k}]", ("title", "children"))
            kids.append({"title": _p_str(s.get("title"), f"{w}.children[{k}].title", PROP_TITLE_MAX, True)})
        items.append({"title": _p_str(t.get("title"), w + ".title", PROP_TITLE_MAX, True), "children": kids if deep else []})
        n += 1 + len(items[-1]["children"])
    if n > PROP_SUBS_MAX:
        raise BadInput(tr("Too many entries: {0} (at most {1})", "items", PROP_SUBS_MAX))
    return {"items": items}


def idp_need_agent(c, j, aid):
    """Before the agent's proposal is stored: the list still shared with it; nothing taken over yet (no replacing then)."""
    from ..agents.safety import agent_reach
    if not j["list_id"] or not list_role(c, j["list_id"], aid) or j["list_id"] not in agent_reach(c, aid):
        raise Denied(403)
    if j["applied"]:
        raise Denied(409, tr("This proposal was already applied or discarded"))


# ---------------------------------------------------------------- the person takes ideas over
def idp_keys(prop):
    return [k for i, t in enumerate(prop["items"]) for k in [str(i), *(f"{i}.{x}" for x in range(len(t["children"])))]]


def _rec(j):
    rec = json.loads(j["applied"] or "null") or {}
    rec.setdefault("tasks", [])
    rec.update({k: rec.get(k) or v for k, v in (("taken", {}), ("dropped", []), ("sel", []), ("edits", {}), ("extra", {}),
                                                 ("sections", []), ("changes", {}))})
    rec.setdefault("undone", False)
    rec["list"] = j["list_id"]
    return rec


def idp_take(c, j, take, drop, edits=None):
    """Creates the ideas `take` (keys "i" / "i.k"; a sub-idea brings its idea along) as the current person and marks `drop`
    as dropped. -> the record (also stored by the caller). Every task: prop_insert (history "from a proposal by <agent>")."""
    prop, inp = json.loads(j["proposal"]), json.loads(j["input"] or "{}")
    keys, rec = idp_keys(prop), _rec(j)
    bad = [k for k in [*take, *drop] if k not in keys]
    if bad:
        raise BadInput(tr("Invalid value: {0}", bad[0]))
    lid = j["list_id"]
    if list_role(c, lid) not in WRITE_ROLES:
        raise Denied(403)
    want = [k for k in keys if k in set(take) and k not in rec["taken"]]
    want = list(dict.fromkeys([k.split(".")[0] for k in want if "." in k and k.split(".")[0] not in rec["taken"]] + want))
    want.sort(key=keys.index)
    ts = iso(now_utc())
    if want:
        kind, tid, row = _target(c, lid, inp.get("target"))
        sec = row["id"] if kind == "section" else row["section_id"] if kind == "task" else None
        if kind == "task":
            e = check_parent(c, None, tid)
            if e:
                raise BadInput(e)
        top = c.execute("SELECT COALESCE(MAX(sort),0) FROM tasks WHERE list_id=? AND " +
                        ("parent_id=?" if kind == "task" else "parent_id IS NULL"), (lid, tid) if kind == "task" else (lid,)).fetchone()[0]
        for n, k in enumerate(want):
            e = (edits if isinstance(edits, dict) else {}).get(k) or {}
            if not isinstance(e, dict):  # review: a bad edit is a 400, never a 500 (also through the generic /apply)
                raise BadInput(tr("Invalid value: {0}", "edits"))
            if "." in k:
                i, x = (int(v) for v in k.split("."))
                title, parent = prop["items"][i]["children"][x]["title"], rec["taken"][str(i)]
                pr = c.execute("SELECT deleted_at FROM tasks WHERE id=?", (parent,)).fetchone()
                if not pr or pr["deleted_at"]:
                    raise BadInput(tr("The parent task is in the trash"))
                m = check_parent(c, None, parent)
                if m:
                    raise BadInput(m)
                srt = x + 1
            else:
                title, parent, srt = prop["items"][int(k)]["title"], tid if kind == "task" else None, top + n + 1
            if isinstance(e.get("title"), str) and e["title"].strip():
                title = _p_str(e["title"], "title", PROP_TITLE_MAX, True)
            nid = prop_insert(c, j["agent_id"], lid, ts, title, "", sec, parent, sort=srt)
            rec["taken"][k] = nid
            rec["tasks"].append(nid)
        rec["at"] = ts
    rec["dropped"] = sorted(set(rec["dropped"]) | {k for k in drop if k not in rec["taken"]}, key=keys.index)
    rec["sel"] = list(rec["taken"])
    rec.setdefault("at", ts)
    return rec, want


def idp_open(prop, rec):
    """The keys not decided yet."""
    return [k for k in idp_keys(prop) if k not in rec["taken"] and k not in rec["dropped"]]


@app.post("/api/proposals/<int:jid>/ideas")
def idp_decide(jid):
    """{take: [keys], drop: [keys]} on an ideas proposal (ready) -> the new tasks; once every idea is decided the job ends
    (applied when one was taken, else discarded) and the agent gets its answer (event job)."""
    from ..tasks.tasks import one_task
    need_collab()
    c = db()
    j = need_prop(c, jid, lock=True)
    if j["kind"] != "ideas":
        raise Denied(404)
    if j["prop_state"] != "ready" or not j["proposal"]:
        return err(tr("There is no proposal to apply (anymore)"), 409)
    b = body()
    _p_keys(b, "", ("take", "drop", "edits"))
    take, drop = [_p_list(b.get(k), k, 500) for k in ("take", "drop")]
    if not all(isinstance(k, str) for k in [*take, *drop]) or not (take or drop):
        raise BadInput(tr("Select at least one entry"))
    ed = b.get("edits") or {}
    if not isinstance(ed, dict):
        raise BadInput(tr("Invalid value: {0}", "edits"))
    try:
        rec, made = idp_take(c, j, take, drop, ed)
    except (BadInput, Denied):
        c.rollback()
        raise
    prop = json.loads(j["proposal"])
    left, ts, state = idp_open(prop, rec), iso(now_utc()), "ready"
    c.execute("UPDATE agent_jobs SET applied=?, updated_at=? WHERE id=?", (json.dumps(rec, ensure_ascii=False), ts, jid))
    if not left:
        state = "applied" if rec["taken"] else "discarded"
        c.execute("UPDATE agent_jobs SET prop_state=?, state=?, action=?, action_by=?, action_at=?, updated_at=? WHERE id=?",
                  (state, "done" if rec["taken"] else "stopped", "approve" if rec["taken"] else "reject", g.user["id"], ts, ts, jid))
        prop_notify_agent(c, j, "approve" if rec["taken"] else "reject", state,
                          {"created": len(rec["taken"]), "changed": 0, "dropped": len(rec["dropped"])} if rec["taken"] else None)
        c.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND kind='proposal' AND read_at IS NULL AND data->>'job' = ?",
                  (ts, g.user["id"], str(jid)))
    bump(c)
    c.commit()
    return jsonify(state=state, taken=rec["taken"], dropped=rec["dropped"], open=left,
                   tasks=[one_task(c, rec["taken"][k]) for k in made])


def idp_run(c, j, sel, ed, extra, rec0):
    """The generic apply (POST /api/proposals/<id>/apply {select}): takes the selected ideas over, drops the rest."""
    prop = json.loads(j["proposal"])
    keys = idp_keys(prop)
    rec, _ = idp_take(c, j, [k for k in sel if k in keys], [k for k in keys if k not in sel], ed)
    return {**rec0, **rec, "at": rec.get("at") or rec0["at"]}


def idp_view(c, j):
    """One ideas job for the mind map (the person who asked): target, items, what is decided."""
    inp, prop = json.loads(j["input"] or "{}"), json.loads(j["proposal"] or "null")
    rec = _rec(j)
    return {"id": j["id"], "state": j["prop_state"], "agent": {"id": j["agent_id"], "name": user_names(c, [j["agent_id"]]).get(j["agent_id"], "")},
            "target": inp.get("target"), "path": inp.get("path") or [], "items": (prop or {}).get("items") or [],
            "taken": rec["taken"], "dropped": rec["dropped"], "created_at": j["created_at"], "updated_at": j["updated_at"]}


@app.get("/api/lists/<int:lid>/ideas")
def idp_list(lid):
    """The open ideas requests of the signed-in person in list lid (requested = waiting for the agent, ready = ideas there)."""
    c = db()
    need_list(c, lid, write=False)
    if is_agent(g.user):
        raise Denied(403)
    rows = c.execute("""SELECT * FROM agent_jobs WHERE user_id=? AND list_id=? AND kind='ideas' AND prop_state IN ('requested','ready')
                        AND state IN ('running','waiting') ORDER BY id DESC LIMIT 20""", (g.user["id"], lid)).fetchall()
    return jsonify(jobs=[idp_view(c, j) for j in rows])
