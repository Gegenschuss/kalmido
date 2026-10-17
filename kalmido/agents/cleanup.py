"""2.39.0 (#1151): "Tidy up this list" -- the list's tidy agent (#379) cleans up tasks that are already in a list.

A person with write access asks (list menu "Tidy up the list", multi-select "Tidy up"); the server always picks the ONE
tidy agent of the list (tidy_agent_of) and sends it the open top-level tasks in packages of CLN_PACK (one proposal job and
one job_request event per package, at most CLN_PACKS packages = the first 250 tasks). The agent never changes anything
itself: it answers with ONE bundled proposal of kind "cleanup" (merge | rename | move | close entries), the person gets
one News entry / push (kind proposal) per package and reviews it in the usual proposal sheet.

MASS PROTECTION (2.29.0 #1031, agents/safety.py): an agent cannot change many tasks in one go here -- the proposal is only
data. The person's explicit confirmation of the ticked entries IS the approval; the changes run as that person, at most
PROP_MAX_ITEMS entries per proposal, each task once, and one undo step takes everything back (redo again). Health lists
never reach an agent, the agent's list limit (agents.list_ids) and agent_usable are checked before a job is created.

Applying checks every task on its own and skips it (with the reason) when someone is editing it right now (#999,
task_being_edited), it changed since the snapshot was sent, it is closed / deleted / moved to another list, or the person
lost write access. Merge: the kept task gets the (edited) title and the notes of the others appended under a line
"Merged from #id title"; the others are closed as won't do (status -1, comments and files stay with them). Close: won't
do, the reason goes into the history. Move: section (section_id, null = no section) and / or the order inside the
section (position, 1 = top) -- two separate things."""
import json
import secrets

from flask import jsonify

from ..core.pg import insert_id
from ..core.i18n import N_, tr
from ..core.db import bump, err, iso, now_utc
from ..core.access import Denied, list_role, need_task, task_visible, WRITE_ROLES
from ..accounts.session import me
from ..collab.comments import user_names
from ..personal.timetrack import BadInput
from ..tasks.validation import descendants, log_act
from ..tasks.lifecycle import apply_update
from ..agents.core import (
    agent_active, agent_emit, agent_row, agent_usable, job_dict, JOB_TITLE_MAX, list_sections, task_being_edited, tidy_agent_of,
)

CLN_PACK = 50          # open top-level tasks per package (= per proposal job)
CLN_PACKS = 5          # packages per request (more: only the first CLN_PACK * CLN_PACKS tasks, the answer says so)
CLN_NOTES = 2000       # notes per task in the job input
CLN_OPS = ("merge", "rename", "move", "close")
CLN_MERGE_MAX = 10     # tasks in one merge entry
CLN_TITLE = N_("Tidy up: {0}")
CLN_TITLE_PACK = N_("Tidy up: {0} (package {1} of {2})")
CLN_WHY = {"editing": N_("someone is editing it right now"), "changed": N_("changed since the proposal was made"),
           "closed": N_("already completed or deleted"), "moved": N_("moved to another list"), "denied": N_("no write access")}


# ---- the request
def cln_request(c, uid, b):
    """POST /api/proposals {kind: "cleanup", list_id, task_ids?, hint?} -> one proposal job per package (201)."""
    from ..agents.proposals import _p_int, _p_keys, _p_list, _p_str, PROP_HINT_MAX, PROP_LIMITS, PROP_OPEN_MAX
    from ..agents.usage import usage_block
    from ..agents.safety import agent_cap
    _p_keys(b, "", ("agent_id", "kind", "list_id", "task_ids", "hint"))
    lid = _p_int(b.get("list_id"), "list_id")
    lst = c.execute("SELECT * FROM lists WHERE id=?", (lid,)).fetchone()
    if not lst or not list_role(c, lid, uid):
        raise Denied(404)
    if (lst["life"] or "") in ("health", "budget"):  # 2.72.0 (#1333): budgets neither
        return err(tr("Health lists never reach an agent"), 403)
    if list_role(c, lid, uid) not in WRITE_ROLES:
        raise Denied(403)
    aid = tidy_agent_of(c, lid)
    a = agent_row(c, aid) if aid else None
    if not a or not agent_active(a):
        return err(tr("This list has no agent that may tidy it up: share it with an agent with edit rights first"), 409)
    name = a["display_name"] or a["username"]
    from ..agents.proposals import prop_mode
    if prop_mode(a) == "off":  # the agent's admin switched proposals off for it
        return err(tr("{0} does not make proposals", name), 409)
    cap = agent_cap(c, aid)
    if cap is not None and lid not in cap:
        return err(tr("{0} is limited to other lists", name), 409)
    if not agent_usable(c, aid, uid, lid):  # 2.26.0 (#928): the owner decides who may use the list's agent
        return err(tr("The list owner has not opened this agent to members"), 403)
    if usage_block(c, aid):
        return err(tr("{0} reached its usage limit", name), 409)
    q = "SELECT * FROM tasks WHERE list_id=? AND parent_id IS NULL AND status=0 AND deleted_at IS NULL"
    if b.get("task_ids") in (None, "all"):
        rows = c.execute(q + " ORDER BY sort, id", (lid,)).fetchall()
    else:
        ids = list(dict.fromkeys(_p_int(x, "task_ids") for x in _p_list(b.get("task_ids"), "task_ids", 1000)))
        if not ids:
            raise BadInput(tr("Missing field: {0}", "task_ids"))
        rows = c.execute(q + f" AND id IN ({','.join('?' * len(ids))}) ORDER BY sort, id", (lid, *ids)).fetchall()
        if len(rows) != len(ids):
            raise BadInput(tr("Only open tasks of this list can be tidied up"))
    rows = [r for r in rows if task_visible(c, r["id"], uid, write=True) and task_visible(c, r["id"], aid, write=True)]
    if not rows:
        return err(tr("There are no open tasks to tidy up"), 400)
    total = len(rows)
    rows = rows[:CLN_PACK * CLN_PACKS]
    packs = [rows[i:i + CLN_PACK] for i in range(0, len(rows), CLN_PACK)]
    if c.execute("SELECT COUNT(*) FROM agent_jobs WHERE user_id=? AND kind IS NOT NULL AND state IN ('running','waiting')",
                 (uid,)).fetchone()[0] + len(packs) > PROP_OPEN_MAX:
        return err(tr("You have {0} open proposal requests: apply or discard some first", PROP_OPEN_MAX), 429)
    hint = _p_str(b.get("hint"), "hint", PROP_HINT_MAX, line=False) or None
    ts, group = iso(now_utc()), secrets.token_hex(6)
    lname = "Inbox" if lst["is_inbox"] else lst["name"]
    secs = list_sections(c, uid, lid)
    ltags = cln_ltags(c, [r["id"] for r in rows])
    ncom = dict(c.execute(f"SELECT task_id, COUNT(*) FROM comments WHERE deleted_at IS NULL AND task_id IN ({','.join('?' * len(rows))}) "
                          "GROUP BY task_id", [r["id"] for r in rows]).fetchall())
    by = {"id": uid, "name": user_names(c, [uid]).get(uid, "")}
    jobs = []
    for n, pk in enumerate(packs, 1):
        inp = {"list": {"id": lid, "name": lname, "sections": secs},
               "package": {"n": n, "of": len(packs), "group": group}, "snapshot_at": ts, "hint": hint,
               "items": [{"task_id": r["id"], "title": r["title"], "notes": (r["content"] or "")[:CLN_NOTES], "section_id": r["section_id"],
                          "sort": r["sort"], "due": r["due"], "priority": r["priority"], "list_tags": ltags.get(r["id"], []),
                          "assignee_id": r["assignee_id"], "created_at": r["created_at"], "updated_at": r["updated_at"],
                          "comments_count": ncom.get(r["id"], 0)} for r in pk]}
        title = tr(CLN_TITLE_PACK, lname[:80], n, len(packs)) if len(packs) > 1 else tr(CLN_TITLE, lname[:80])
        jid = insert_id(c, """INSERT INTO agent_jobs(agent_id,task_id,user_id,title,state,log,created_at,updated_at,kind,input,prop_state,list_id)
                           VALUES(?,?,?,?,'running','',?,?,?,?,'requested',?)""",
                        (aid, None, uid, title[:JOB_TITLE_MAX], ts, ts, "cleanup", json.dumps(inp, ensure_ascii=False), lid))
        j = c.execute("SELECT * FROM agent_jobs WHERE id=?", (jid,)).fetchone()
        # list_id on top: agent_emit checks health list / list limit / playbook (2.39.0 #1168) with it
        agent_emit(c, aid, "job_request", {"job": job_dict(c, j), "kind": "cleanup", "list_id": lid, "input": inp,
                                           "limits": PROP_LIMITS, "requested_by": by})
        jobs.append(job_dict(c, j))
    bump(c)
    c.commit()
    print("cleanup request list", lid, "packages", len(packs), "agent", aid, "by user", uid, flush=True)
    return jsonify(jobs=jobs, agent={"id": aid, "name": name}, tasks=len(rows), total=total, packages=len(packs),
                   truncated=total > len(rows), job=jobs[0]), 201


def cln_ltags(c, ids):
    out = {}
    if ids:
        for r in c.execute(f"""SELECT x.task_id, lt.name FROM task_list_tags x JOIN list_tags lt ON lt.id=x.tag_id
                               WHERE x.task_id IN ({','.join('?' * len(ids))}) ORDER BY lt.sort, lt.id""", ids):
            out.setdefault(r[0], []).append(r[1])
    return out


# ---- the agent's proposal
def cln_validate(b, inp):
    """{summary, items: [{op, ...}]} -> normalized entries; every task_id from the input, each at most once."""
    from ..agents.proposals import _p_int, _p_keys, _p_list, _p_str, PROP_MAX_ITEMS, PROP_NOTES_MAX, PROP_TITLE_MAX
    ids = {x["task_id"] for x in inp.get("items", [])}
    secs = {s["id"] for s in (inp.get("list") or {}).get("sections", [])}
    raw = _p_list(b.get("items"), "items", PROP_MAX_ITEMS)
    if not raw:
        raise BadInput(tr("Missing field: {0}", "items"))
    seen, items = set(), []

    def tid_ok(v, w):
        t = _p_int(v, w)
        if t not in ids or t in seen:
            raise BadInput(tr("Invalid value: {0}", w))
        seen.add(t)
        return t
    for i, t in enumerate(raw):
        w = f"items[{i}]"
        if not isinstance(t, dict) or t.get("op") not in CLN_OPS:
            raise BadInput(tr("Invalid value: {0}", w + ".op"))
        op = t["op"]
        reason = _p_str(t.get("reason"), w + ".reason", PROP_NOTES_MAX, op == "close", line=False) or None
        if op == "merge":
            _p_keys(t, w, ("op", "task_ids", "title", "reason"))
            tl = _p_list(t.get("task_ids"), w + ".task_ids", CLN_MERGE_MAX)
            if len(tl) < 2:
                raise BadInput(tr("Invalid value: {0}", w + ".task_ids"))
            items.append({"op": op, "task_ids": [tid_ok(x, f"{w}.task_ids[{k}]") for k, x in enumerate(tl)],
                          "title": _p_str(t.get("title"), w + ".title", PROP_TITLE_MAX) or None, "reason": reason})
        elif op == "rename":
            _p_keys(t, w, ("op", "task_id", "title", "reason"))
            items.append({"op": op, "task_id": tid_ok(t.get("task_id"), w + ".task_id"),
                          "title": _p_str(t.get("title"), w + ".title", PROP_TITLE_MAX, True), "reason": reason})
        elif op == "move":
            _p_keys(t, w, ("op", "task_id", "section_id", "position", "reason"))
            sid = t.get("section_id")
            sid = None if sid in (None, "", 0) else _p_int(sid, w + ".section_id")
            if sid is not None and sid not in secs:
                raise BadInput(tr("Invalid value: {0}", w + ".section_id"))
            pos = t.get("position")
            pos = None if pos in (None, "") else _p_int(pos, w + ".position", 1, 100000)
            if "section_id" not in t and pos is None:
                raise BadInput(tr("Missing field: {0}", w + ".section_id"))
            items.append({"op": op, "task_id": tid_ok(t.get("task_id"), w + ".task_id"), "section": "section_id" in t,
                          "section_id": sid, "position": pos, "reason": reason})
        else:
            _p_keys(t, w, ("op", "task_id", "reason"))
            items.append({"op": op, "task_id": tid_ok(t.get("task_id"), w + ".task_id"), "reason": reason})
    return {"items": items}


# ---- applying (as the person), undo, redo
def cln_check(c, tid, lid, snap, cache):
    """None when task tid may be changed now, else the reason code (CLN_WHY). snap: {task id: the item sent to the agent};
    changed = another updated_at or another value of what the agent saw (updated_at has whole seconds only)."""
    if tid in cache:
        return cache[tid]
    t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    why = None
    if not t or t["deleted_at"] or t["status"] != 0:
        why = "closed"
    elif t["list_id"] != lid:
        why = "moved"
    else:
        try:
            need_task(c, tid)
            if list_role(c, lid) not in WRITE_ROLES:
                why = "denied"
        except Denied:
            why = "denied"
    if not why and task_being_edited(tid):
        why = "editing"
    if not why and tid in snap and cln_changed(t, snap[tid]):
        why = "changed"
    cache[tid] = why
    return why


def cln_changed(t, x):
    """Did task row t change since item x of the job input was taken?"""
    if (t["updated_at"] or "") != (x.get("updated_at") or ""):
        return True
    return any(t[k] != x.get(k) for k in ("title", "section_id", "sort", "due", "priority")) or \
        (t["content"] or "")[:CLN_NOTES] != (x.get("notes") or "")


def cln_title(c, tid, inp):
    r = c.execute("SELECT title FROM tasks WHERE id=?", (tid,)).fetchone()
    if r:
        return r[0]
    return next((x["title"] for x in inp.get("items", []) if x["task_id"] == tid), "")


def cln_pos_sort(c, lid, sid, tid, pos):
    """The sort value that puts task tid at position pos (1 = top) among the open top-level tasks of section sid."""
    rows = [r[0] for r in c.execute("""SELECT sort FROM tasks WHERE list_id=? AND parent_id IS NULL AND status=0 AND deleted_at IS NULL
                                       AND id<>? AND section_id IS NOT DISTINCT FROM ? ORDER BY sort, id""", (lid, tid, sid))]
    if not rows:
        return None
    i = min(max(pos, 1), len(rows) + 1) - 1
    if i == 0:
        return rows[0] - 1
    if i >= len(rows):
        return rows[-1] + 1
    return (rows[i - 1] + rows[i]) / 2


def cln_change(c, rec, tid, want, aid):
    """One field change through apply_update (before / after for undo)."""
    cur = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    before = {k: cur[k] for k in want}
    want = {k: v for k, v in want.items() if before[k] != v}
    if not want:
        return
    msg = apply_update(c, tid, dict(want))
    if msg:
        raise BadInput(msg)
    log_act(c, tid, "proposal", {"agent": aid})
    rec["changes"][str(tid)] = {"before": {k: before[k] for k in want}, "after": want}


def cln_close(c, rec, tid, reason, into=None):
    """Won't do (status -1) with the open subtasks; the undo record keeps what changed."""
    ts = iso(now_utc())
    kids = [d for d in descendants(c, tid) if c.execute("SELECT status FROM tasks WHERE id=?", (d,)).fetchone()[0] == 0]
    c.execute("UPDATE tasks SET status=-1, completed_at=?, completed_by=?, updated_at=? WHERE id=?", (ts, me(), ts, tid))
    for d in kids:
        c.execute("UPDATE tasks SET status=-1, completed_at=?, completed_by=?, updated_at=? WHERE id=? AND status=0", (ts, me(), ts, d))
    log_act(c, tid, "wont", {k: v for k, v in (("reason", (reason or "")[:500] or None), ("merged_into", into)) if v})
    from ..tasks.dependencies import completed_ids, unblock_events
    unblock_events(c, completed_ids(c, tid))
    rec["closed"].append({"id": tid, "kids": kids, "at": ts})


def cln_run(c, j, sel, edits, rec):
    """Applies the selected entries (edits: {key: {title}} for rename / merge). Fills rec (changes, closed, skipped, counts)."""
    prop, inp = json.loads(j["proposal"]), json.loads(j["input"] or "{}")
    lid, aid = j["list_id"], j["agent_id"]
    snap = {x["task_id"]: x for x in inp.get("items", [])}
    rec.update(list=lid, closed=[], skipped=[], counts={k: 0 for k in CLN_OPS})
    cache, selected = {}, set(sel)
    for i, it in enumerate(prop["items"]):
        if str(i) not in selected:
            continue
        e = edits.get(str(i), {})
        ids = it["task_ids"] if it["op"] == "merge" else [it["task_id"]]
        bad = [(t, cln_check(c, t, lid, snap, cache)) for t in ids]
        bad = [(t, w) for t, w in bad if w]
        if bad:
            rec["skipped"] += [{"task_id": t, "title": cln_title(c, t, inp)[:200], "why": w, "entry": i} for t, w in bad]
            continue
        op = it["op"]
        if op == "rename":
            cln_change(c, rec, ids[0], {"title": e.get("title") or it["title"]}, aid)
        elif op == "move":
            want = {}
            sid = it["section_id"] if it["section"] else c.execute("SELECT section_id FROM tasks WHERE id=?", (ids[0],)).fetchone()[0]
            if it["section"]:
                want["section_id"] = sid
            if it["position"]:
                s = cln_pos_sort(c, lid, sid, ids[0], it["position"])
                if s is not None:
                    want["sort"] = s
            cln_change(c, rec, ids[0], want, aid)
        elif op == "close":
            cln_close(c, rec, ids[0], it["reason"])
        else:  # merge: the first one stays, the notes of the others are appended with a reference, the others are closed
            keep, rest = ids[0], ids[1:]
            k = c.execute("SELECT title, content FROM tasks WHERE id=?", (keep,)).fetchone()
            parts = [(k["content"] or "").rstrip()]
            for t in rest:
                r = c.execute("SELECT title, content FROM tasks WHERE id=?", (t,)).fetchone()
                parts.append(tr("Merged from #{0} {1}", t, r["title"]) + ("\n\n" + r["content"].strip() if (r["content"] or "").strip() else ""))
            want = {"content": "\n\n---\n\n".join(p for p in parts if p)}
            title = e.get("title") or it["title"]
            if title:
                want["title"] = title
            cln_change(c, rec, keep, want, aid)
            for t in rest:
                # review M2: open subtasks of a merged-away task move to the kept one (undo puts them back) instead of
                # being closed with it; one that cannot move (depth, milestone) is closed with its parent as before
                for (kid,) in c.execute("SELECT id FROM tasks WHERE parent_id=? AND status=0 AND deleted_at IS NULL ORDER BY sort, id",
                                        (t,)).fetchall():
                    try:
                        with c.savepoint():
                            cln_change(c, rec, kid, {"parent_id": keep}, aid)
                    except (BadInput, Denied):
                        pass
                cln_close(c, rec, t, it["reason"], into=keep)
        rec["counts"][op] += 1
    return rec


def cln_result(rec):
    """The counts of the apply answer (and the agent's job event)."""
    return {"changed": len(rec.get("changes") or {}) + len(rec.get("closed") or []), **(rec.get("counts") or {}),
            "skipped": [{**s, "why_text": tr(CLN_WHY.get(s["why"], s["why"]))} for s in rec.get("skipped") or []]}


def cln_undo(c, rec, back=True):
    """One step back (back) or forward again: field changes through apply_update (what someone changed since stays and is
    reported), closed tasks open again while they are still closed from this apply (and closed again on redo)."""
    from ..agents.proposals import prop_titles
    skipped, n, ts = [], 0, iso(now_utc())
    for tid, ch in (rec.get("changes") or {}).items():
        tid = int(tid)
        try:
            need_task(c, tid)
        except Denied:
            skipped += prop_titles(c, [tid])
            continue
        conf = []
        a, b = (ch["before"], ch["after"]) if back else (ch["after"], ch["before"])
        try:
            msg = apply_update(c, tid, {**a, "_prev": b}, conf)
        except Denied as e:
            msg = e.text()
        if msg or conf:
            skipped += prop_titles(c, [tid])
        if not msg and len(conf) < len(a):
            n += 1
    for x in rec.get("closed") or []:
        tid = x["id"]
        try:
            need_task(c, tid)
        except Denied:
            skipped += prop_titles(c, [tid])
            continue
        t = c.execute("SELECT status, completed_at, deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()
        if back:
            if not t or t["deleted_at"] or t["status"] != -1 or t["completed_at"] != x["at"]:
                skipped += prop_titles(c, [tid])
                continue
            for d in [tid, *x["kids"]]:
                c.execute("UPDATE tasks SET status=0, completed_at=NULL, completed_by=NULL, updated_at=? WHERE id=? AND status=-1", (ts, d))
            log_act(c, tid, "reopen")
        else:
            if not t or t["deleted_at"] or t["status"] != 0:
                skipped += prop_titles(c, [tid])
                continue
            new = {"closed": [], "changes": {}}
            cln_close(c, new, tid, None)
            x.update(at=new["closed"][0]["at"], kids=new["closed"][0]["kids"])
        n += 1
    return n, skipped
