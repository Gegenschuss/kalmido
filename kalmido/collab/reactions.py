"""Reactions on comments, tidy suggestions and shared list tags."""
import json
import re
from flask import g, has_request_context, jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, iso_ms, now_utc
from ..accounts.session import me
from ..core.access import Denied, list_role, MANAGE_ROLES, need_collab, need_list, need_task, task_visible, WRITE_ROLES
from ..lists.lists import clean_color, clean_list_value
from ..tasks.validation import as_int, CONTENT_MAX, descendants, log_act, PRIORITIES, TITLE_MAX
from ..tasks.tasks import one_task
from ..tasks.lifecycle import apply_update
from ..collab.comments import comment_plain, need_live_comment, user_names
from ..personal.timetrack import BadInput, UnknownFields
from ..api.v1 import _tag_arg, PRIO_NAMES, PRIO_VALUES
from ..agents.core import (
    agent_emit, agent_ids, agent_task_data, is_agent, is_approver, list_agents, LTAG_MAX, LTAG_NAME_MAX,
    REACTION_ALIASES, REACTIONS, tidy_agent_of, tidy_candidates, TIDY_MODES,
)


# ---- reactions
def reactions_of(c, cids):
    out = {}
    cids = [x for x in cids if x]
    if not cids:
        return out
    rows = c.execute(f"""SELECT r.comment_id, r.emoji, r.user_id, u.display_name, u.username FROM comment_reactions r
                         JOIN users u ON u.id=r.user_id WHERE r.comment_id IN ({','.join('?' * len(cids))})
                         ORDER BY r.created_at, r.user_id""", cids).fetchall()
    for r in rows:
        lst = out.setdefault(r["comment_id"], [])
        e = next((x for x in lst if x["emoji"] == r["emoji"]), None)
        if not e:
            e = {"emoji": r["emoji"], "count": 0, "users": []}
            lst.append(e)
        e["count"] += 1
        e["users"].append({"id": r["user_id"], "name": r["display_name"] or r["username"]})
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


def react(c, k, uid, emoji, on):
    """Adds (on) / removes my reaction; on a new 👍 / 👎: approval, suggestion apply / reject, event to an agent author.
    Returns {"approval": ..., "applied": bool} (caller commits)."""
    res = {"approval": None, "applied": False}
    if not on:
        c.execute("DELETE FROM comment_reactions WHERE comment_id=? AND user_id=? AND emoji=?", (k["id"], uid, emoji))
        return res
    if not c.execute("INSERT OR IGNORE INTO comment_reactions(comment_id,user_id,emoji,created_at) VALUES(?,?,?,?)",
                     (k["id"], uid, emoji, iso_ms(now_utc()))).rowcount:
        return res
    t = c.execute("SELECT * FROM tasks WHERE id=?", (k["task_id"],)).fetchone()
    author = c.execute("SELECT * FROM users WHERE id=?", (k["user_id"],)).fetchone() if k["user_id"] else None
    if is_agent(author) and emoji in ("up", "down") and uid != author["id"] and is_approver(c, t, uid):
        res["approval"] = "approved" if emoji == "up" else "rejected"
        log_act(c, t["id"], "approval", {"agent": author["id"], "comment": k["id"], "ok": emoji == "up"})
    sug = json.loads(k["suggestion"]) if k["suggestion"] else None
    if sug and sug.get("kind") in ("integrate", "deploy"):  # 2.26.0 (#949): only an approver decides (see agents/gates.py)
        from ..agents.gates import gate_decide
        if sug.get("state") == "open" and res["approval"]:
            res["gate"] = gate_decide(c, k, t, uid, emoji == "up")
            if res["gate"] == "blocked":  # open checklist: 👍 alone does not approve a deploy
                res["approval"] = None
    elif sug and sug.get("kind") == "merge_request":  # 2.2.0 (#339): only an approver decides; the agent merges itself
        if sug.get("state") == "open" and res["approval"]:
            st = "approved" if emoji == "up" else "rejected"
            c.execute("UPDATE comments SET suggestion=? WHERE id=?",
                      (json.dumps({**sug, "state": st, "by": uid, "at": iso(now_utc())}, ensure_ascii=False), k["id"]))
            res["merge"] = st
    elif sug and sug.get("state") == "open" and emoji in ("up", "down") and not is_agent(g.user) \
            and task_visible(c, t["id"], uid, write=True) and not t["deleted_at"]:
        if emoji == "up":
            suggestion_apply(c, k, t)
            res["applied"] = True
        else:
            c.execute("UPDATE comments SET suggestion=? WHERE id=?",
                      (json.dumps({**sug, "state": "rejected", "by": uid, "at": iso(now_utc())}, ensure_ascii=False), k["id"]))
    if is_agent(author) and uid != author["id"] and task_visible(c, t["id"], author["id"], full=True):
        k2 = c.execute("SELECT * FROM comments WHERE id=?", (k["id"],)).fetchone()
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
    have = bool(c.execute("SELECT 1 FROM comment_reactions WHERE comment_id=? AND user_id=? AND emoji=?", (cid, me(), emoji)).fetchone())
    on = bool(b["on"]) if isinstance(b.get("on"), bool) else not have
    if on and k["user_id"] == me():  # 2.23.0 (#823): not on one's own comment (taking an old one back still works)
        return err(tr("You cannot react to your own message"))
    res = react(c, k, me(), emoji, on)
    bump(c)
    c.commit()
    k = c.execute("SELECT * FROM comments WHERE id=?", (cid,)).fetchone()
    return jsonify(ok=True, reactions=reactions_of(c, [cid]).get(cid, []), suggestion=json.loads(k["suggestion"]) if k["suggestion"] else None, **res)


# ---- tidy: suggestions (comments.suggestion) and applying them
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
    c.execute("UPDATE comments SET suggestion=? WHERE id=?",
              (json.dumps({**sug, "state": "applied", "by": me(), "at": iso(now_utc())}, ensure_ascii=False), k["id"]))


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
    c.execute("INSERT OR IGNORE INTO comment_reactions(comment_id,user_id,emoji,created_at) VALUES(?,?,?,?)",
              (cid, me(), "up", iso_ms(now_utc())))
    author = c.execute("SELECT * FROM users WHERE id=?", (k["user_id"],)).fetchone() if k["user_id"] else None
    if is_agent(author) and task_visible(c, t["id"], author["id"], full=True):
        k2 = c.execute("SELECT * FROM comments WHERE id=?", (cid,)).fetchone()
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
        raise Denied(403, tr("Only the list owner or a list admin can change this"))
    cands = tidy_candidates(c, lid)
    if mode is not None and mode != "off" and not list_agents(c, lid):
        return tr("Share the list with an agent first")
    if set_agent and agent is not None and agent not in cands:
        raise BadInput(tr("This agent cannot tidy up the list (it needs edit rights)"))
    if mode is not None and mode != "off" and not cands:
        return tr("Give an agent of this list edit rights first")
    if set_agent:
        c.execute("UPDATE lists SET tidy_agent=? WHERE id=?", (agent, lid))
    if mode is not None:
        c.execute("UPDATE lists SET agent_tidy=? WHERE id=?", (mode, lid))
        if mode != "off" and c.execute("SELECT tidy_agent FROM lists WHERE id=?", (lid,)).fetchone()[0] not in cands:
            c.execute("UPDATE lists SET tidy_agent=? WHERE id=?", (tidy_agent_of(c, lid, cands), lid))
    return None


# ---- list tags
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
    out = {}
    lids = [x for x in lids if x]
    if not lids:
        return out
    for r in c.execute(f"SELECT * FROM list_tags WHERE list_id IN ({','.join('?' * len(lids))}) ORDER BY sort, name COLLATE NOCASE, id", lids):
        out.setdefault(r["list_id"], []).append({"id": r["id"], "name": r["name"], "color": r["color"]})
    return out


def ltags_for(c, ids):
    """{task id: [list tag names]} (only tags of the task's current list)."""
    out = {}
    ids = list(ids)
    for i in range(0, len(ids), 900):
        part = ids[i:i + 900]
        for r in c.execute(f"""SELECT x.task_id, lt.name FROM task_list_tags x JOIN list_tags lt ON lt.id=x.tag_id JOIN tasks t ON t.id=x.task_id
                               WHERE x.task_id IN ({','.join('?' * len(part))}) AND lt.list_id=t.list_id ORDER BY lt.sort, lt.name COLLATE NOCASE""", part):
            out.setdefault(r["task_id"], []).append(r["name"])
    return out


def ltag_names(c, tid):
    return ltags_for(c, [tid]).get(tid, [])


def ltag_get_or_create(c, lid, name, create):
    r = c.execute("SELECT id FROM list_tags WHERE list_id=? AND name=? COLLATE NOCASE", (lid, name)).fetchone()
    if r:
        return r[0]
    if not create:
        raise BadInput(tr("Unknown list tag: {0}", name))
    if c.execute("SELECT COUNT(*) FROM list_tags WHERE list_id=?", (lid,)).fetchone()[0] >= LTAG_MAX:
        raise BadInput(tr("At most {0} list tags", LTAG_MAX))
    srt = c.execute("SELECT COALESCE(MAX(sort),0)+1 FROM list_tags WHERE list_id=?", (lid,)).fetchone()[0]
    return c.execute("INSERT INTO list_tags(list_id,name,color,sort,created_at) VALUES(?,?,?,?,?)",
                     (lid, name, "", srt, iso(now_utc()))).lastrowid


def set_ltags(c, tid, names, log=True):
    """The list tags of task tid (names; missing ones are created when the current user may change the list). Logged."""
    t = c.execute("SELECT list_id FROM tasks WHERE id=?", (tid,)).fetchone()
    names = clean_ltag_names(names)
    before = ltag_names(c, tid)
    create = list_role(c, t["list_id"]) in WRITE_ROLES if has_request_context() and getattr(g, "user", None) else True
    ids = [ltag_get_or_create(c, t["list_id"], n, create) for n in names]
    c.execute("DELETE FROM task_list_tags WHERE task_id=?", (tid,))
    for i in dict.fromkeys(ids):
        c.execute("INSERT OR IGNORE INTO task_list_tags(task_id,tag_id) VALUES(?,?)", (tid, i))
    after = ltag_names(c, tid)
    if log and sorted(before, key=str.casefold) != sorted(after, key=str.casefold):
        log_act(c, tid, "ltags", {"tags": after})


def ltags_follow(c, tid, lid):
    """After a move to list lid: the list tags of tid and its subtasks follow by name (created there when the mover may
    change that list, else dropped)."""
    create = list_role(c, lid) in WRITE_ROLES if has_request_context() and getattr(g, "user", None) else True
    for x in [tid] + descendants(c, tid):
        rows = c.execute("""SELECT lt.name, lt.list_id, lt.color FROM task_list_tags k JOIN list_tags lt ON lt.id=k.tag_id
                            WHERE k.task_id=?""", (x,)).fetchall()
        if not rows or all(r["list_id"] == lid for r in rows):
            continue
        c.execute("DELETE FROM task_list_tags WHERE task_id=?", (x,))
        for r in rows:
            try:
                i = ltag_get_or_create(c, lid, r["name"], create)
            except BadInput:
                continue
            if r["color"]:
                c.execute("UPDATE list_tags SET color=? WHERE id=? AND color=''", (r["color"], i))
            c.execute("INSERT OR IGNORE INTO task_list_tags(task_id,tag_id) VALUES(?,?)", (x, i))


def need_ltag(c, tag_id, write=True):
    r = c.execute("SELECT * FROM list_tags WHERE id=?", (tag_id,)).fetchone()
    if not r:
        raise Denied(404)
    need_list(c, r["list_id"], write=write)
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


@app.post("/api/lists/<int:lid>/tags")
def ltag_create(lid):
    """{name, color?} -- a new list tag (members with edit rights)."""
    c = db()
    need_list(c, lid)
    f = ltag_fields(body())
    if c.execute("SELECT 1 FROM list_tags WHERE list_id=? AND name=? COLLATE NOCASE", (lid, f["name"])).fetchone():
        return err(tr("This tag already exists in the list"), 409)
    i = ltag_get_or_create(c, lid, f["name"], True)
    if f.get("color"):
        c.execute("UPDATE list_tags SET color=? WHERE id=?", (f["color"], i))
    bump(c)
    c.commit()
    return jsonify(dict(c.execute("SELECT id, list_id, name, color, sort FROM list_tags WHERE id=?", (i,)).fetchone())), 201


@app.patch("/api/list-tags/<int:tag_id>")
def ltag_update(tag_id):
    c = db()
    r = need_ltag(c, tag_id)
    f = ltag_fields(body(), partial=True)
    if "name" in f and c.execute("SELECT 1 FROM list_tags WHERE list_id=? AND name=? COLLATE NOCASE AND id!=?",
                                 (r["list_id"], f["name"], tag_id)).fetchone():
        return err(tr("This tag already exists in the list"), 409)
    if f:
        c.execute(f"UPDATE list_tags SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), tag_id])
        bump(c)
        c.commit()
    return jsonify(dict(c.execute("SELECT id, list_id, name, color, sort FROM list_tags WHERE id=?", (tag_id,)).fetchone()))


@app.delete("/api/list-tags/<int:tag_id>")
def ltag_delete(tag_id):
    """Removes the list tag from every task of the list (answers the task ids, for the undo)."""
    c = db()
    r = need_ltag(c, tag_id)
    ids = [x[0] for x in c.execute("SELECT task_id FROM task_list_tags WHERE tag_id=?", (tag_id,))]
    c.execute("DELETE FROM list_tags WHERE id=?", (tag_id,))
    bump(c)
    c.commit()
    return jsonify(ok=True, ids=ids, tag={"name": r["name"], "color": r["color"], "list_id": r["list_id"]})


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
    ids = [r[0] for r in c.execute("""SELECT g.task_id FROM task_tags g JOIN tasks t ON t.id=g.task_id
                                      WHERE g.user_id=? AND g.tag=? AND t.list_id=?""", (me(), tag, lid))]
    for x in ids:
        c.execute("INSERT OR IGNORE INTO task_list_tags(task_id,tag_id) VALUES(?,?)", (x, i))
        c.execute("DELETE FROM task_tags WHERE task_id=? AND user_id=? AND tag=?", (x, me(), tag))
        log_act(c, x, "ltags", {"tags": ltag_names(c, x)})
    bump(c)
    c.commit()
    return jsonify(ok=True, id=i, name=name, count=len(ids), ids=ids)
