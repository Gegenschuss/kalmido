"""JSON shapes of database rows (tasks, lists, users ...) as the web client and the API see them."""
import json
import os
import re
from datetime import timedelta
from flask import g, has_request_context

from ..core.config import ATT_DIR
from ..core.i18n import tr
from ..core.ctx import me  # 2.149.0 G (#2517): was accounts.session
from ..core.access import plists, PROJ_SQL, pvis
from ..core.pg import st_ids
from .objfollow import ofl_watchers_of  # 2.972.0 (#5285)
from ..core.dlock import dl_tasks_locked  # 2.576.0 (#3371)
from ..core.db import iso, iso_ms, now_utc  # 2.149.0 G (#2517): pulled up from functions
from ..core.objtags import otg_user_of  # 2.955.0 (#5276)
from ..core.retention import ret_days  # 2.272.0 E2 (#3038)


# ---------------------------------------------------------------- serializers

RSN_ITEMS_MAX, RSN_TITLE_MAX = 100, 500  # 2.556.0 C review (#4583): as lifecycle.RSN_MAX; a title is cut to this


def rsn_out(v):
    """2.556.0 C (#4583): tasks.sub_snapshot (JSON text, lifecycle.rsn_take) -> {done, total, items} or None (none / damaged).
    Review (finding 4): only the known shape goes out -- at most RSN_ITEMS_MAX items, each {title: str (cut), status in
    -1 / 0 / 2, depth: int}; anything else (an import, an old row) is dropped."""
    try:
        ss = json.loads(v or "null")
    except (TypeError, ValueError, RecursionError):
        return None
    if not isinstance(ss, dict) or not isinstance(ss.get("items"), list):
        return None
    items = []
    for i in ss["items"]:
        if len(items) >= RSN_ITEMS_MAX:
            break
        if not isinstance(i, dict) or not isinstance(i.get("title"), str) or isinstance(i.get("status"), bool) \
                or i.get("status") not in (-1, 0, 2) or isinstance(i.get("depth"), bool) or not isinstance(i.get("depth"), int):
            continue
        items.append({"title": i["title"][:RSN_TITLE_MAX], "status": i["status"], "depth": min(max(i["depth"], 1), 60)})
    if not items:
        return None

    def num(k):
        x = ss.get(k)
        return x if isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 100000 else None
    done, total = num("done"), num("total")
    if done is None or total is None or total < len(items) or done > total:  # counts that do not fit: those of the items
        done, total = sum(1 for i in items if i["status"] == 2), len(items)
    return {"done": done, "total": total, "items": items}


def rsn_shown(d):
    """2.556.0 C review (#4583): may this task dict carry its sub_snapshot? Only a completed copy that is not a series again
    (finding 3: reopened / given a repeat it is a live task) and never for an agent (finding 1: the snapshot names subtasks the
    agent's data lock hides -- core/dlock.py; agents read the copy's subtasks nowhere else either)."""
    if d.get("status") != 2 or d.get("repeat"):
        return False
    u = getattr(g, "user", None) if has_request_context() else None
    try:  # an agent's person row says kind "agent" (agents/core.is_agent, not imported: core does not reach up into agents)
        return not (u and (u["kind"] or "user") == "agent")
    except (KeyError, IndexError, TypeError):
        return True
def sk_kinds_of(c, ids):
    """{section id: meaning} of those sections that have one."""
    q = "SELECT id, kind FROM sections WHERE kind<>'' AND id = ANY(CAST(? AS BIGINT[]))"
    return {r[0]: r[1] for r in c.execute(q, (st_ids(sorted(ids)),))} if ids else {}


def task_dict(r, tags, full_snips=False):
    from ..family.family import fam_task_out
    d = dict(zip(r.keys(), r)) if isinstance(r, tuple) else dict(r)  # 2.65.0 (#1505): a row at once, not key by key
    d.pop("reminded", None)
    d.pop("nag_at", None)
    d.pop("client_ref", None)  # 2.126.0 D (#1990): only the server matches it
    d.pop("acceptance_of", None)  # 2.392.0 C (#3370): only the server matches it
    d.pop("org_id", None)  # 2.724.0 (#5184): the row-level security column of #4602, the client takes the organisation from the list
    # 2.18.0 (#430): ms only on milestones, milestone_id only when set (keeps every other task's dict as it was)
    if not d.get("ms"):
        d.pop("ms", None)
    if d.get("milestone_id") is None:
        d.pop("milestone_id", None)
    for k in ("sprint_id", "sprint_at", "points", "section_at", "partial_until"):  # 2.60.0 (#343 / #1511): only when set; 2.410.0 B (#3515): + section_at; 2.392.0 B (#3364): + partial_until
        if d.get(k) is None:
            d.pop(k, None)
    if not d.get("review"):  # 2.60.0 C (#1512): review fields only when a review state is set; the reviewer when one is set
        for k in ("review", "review_at", "review_by", "review_sec"):
            d.pop(k, None)
    if d.get("reviewer_id") is None:
        d.pop("reviewer_id", None)
    if d.get("delegate_agent_id") is None:  # 2.473.0 (#3357): only when set
        d.pop("delegate_agent_id", None)
    if not d.get("approval"):  # 2.23.0 (#463): only on tasks that wait for / had an approval
        d.pop("approval", None)
        d.pop("approver_id", None)
    if "sub_snapshot" in d:  # 2.556.0 C (#4583): a completed copy of a recurring task: its subtasks then (read only), only when set
        raw = d.pop("sub_snapshot")
        ss = rsn_out(raw) if rsn_shown(d) else None  # review: not for agents, not on a live task
        if ss:
            d["sub_snapshot"] = ss
    fam_task_out(d)  # 2.19.0 (#653): fam / rotation as objects, only when set
    from ..collab.liste2e import le2a_snip_cipher
    if "snippets" in d and le2a_snip_cipher(d["snippets"]):  # 2.64.1 (#1817): a list with the lock: the ciphertext (the browser decrypts)
        d["snippets"] = le2a_snip_cipher(d["snippets"])
    elif "snippets" in d:  # 2.35.0 (#1095): lists / state only the number (snippets_n, when > 0); the snippets themselves
        from ..tasks.snippets import snip_out  # with full_snips (one task: GET /api/tasks/<id>, the answer of a change, API)
        sn = snip_out(d.pop("snippets"))
        if full_snips:
            d["snippets"] = sn
        if sn or full_snips:
            d["snippets_n"] = len(sn)
    d["tags"] = tags.get(r["id"], [])
    return d


def tags_for(c, ids=None, uid=None):
    uid = uid or me()
    # 2.955.0 (#5276): the personal tags of the core (obj_tags scope user; were task_tags); 2.65.0 (#1505): only these tasks
    return otg_user_of(c, uid, ids)


ST_NOTE_MAX = 200  # 2.280.0 A (#3108): a longer note is not in the start state (lean_notes)
WK_TTL = 900     # 2.407.0 A (#3513): an agent's "working" on a task fades after this many seconds without an update
WK_TEXT_MAX = 200  # its progress line as the rows show it


def wk_for(c, ids):
    """2.407.0 A (#3513): {task id: {agent_id, agent, name, text, at, ttl}} = an agent works on the task now: its newest
    running job of the task (not a proposal / approval job) updated within WK_TTL; text = the job log's last line. Read
    only (the caller filtered the tasks by what the viewer sees); a job past WK_TTL simply drops out, no clean-up needed."""
    if not ids:
        return {}
    cut = now_utc() - timedelta(seconds=WK_TTL)
    out = {}
    for r in c.execute("""SELECT DISTINCT ON (j.task_id) j.task_id, j.agent_id, j.updated_at, j.name, RIGHT(j.log, 1000) AS tail,
                                 u.display_name, u.username
                          FROM agent_jobs j JOIN users u ON u.id=j.agent_id
                          WHERE j.state='running' AND j.kind IS NULL AND COALESCE(j.approval, '')='' AND j.updated_at>=?
                          AND j.task_id = ANY(CAST(? AS BIGINT[])) ORDER BY j.task_id, j.updated_at DESC, j.id DESC""",
                       (iso(cut), st_ids(sorted(ids)))):
        line = next((x for x in reversed((r["tail"] or "").splitlines()) if x.strip()), "")
        line = re.sub(r"^\d{1,2}:\d{2}\s+", "", " ".join(line.split()))  # a host's own "11:04 " in front (agent_job.py): the time is shown anyway
        out[r["task_id"]] = {"agent_id": r["agent_id"], "agent": r["display_name"] or r["username"], "name": r["name"] or None,
                             "text": line[:WK_TEXT_MAX - 1] + "…" if len(line) > WK_TEXT_MAX else line, "at": r["updated_at"],
                             "ttl": WK_TTL}
    return out


def wat_of(c, ids):
    """2.473.0 (#3357): {task id: [user ids]} of the tasks ids that have watchers."""
    return ofl_watchers_of(c, "task", ids)  # 2.972.0 (#5285): the core's obj_follow


# 2.576.0 (#3371): the saved relations as the reading side sees them (tasks/relations.py)
REL_OUT = {("relates", True): "relates", ("relates", False): "relates", ("duplicate", True): "duplicate_of", ("duplicate", False): "has_duplicate"}


def rel_of(c, ids, mkvis, uid=None):
    """2.576.0 (#3371): {task id: [{id, kind}]} of the saved relations of the tasks ids whose other task is visible
    (mkvis() -> personal.timetrack.VisIds, built only when there is a relation) and not in the trash; for an agent uid, other
    tasks its data lock covers are left out too (core/dlock.py; nothing for people)."""
    out = {}
    if not ids:
        return out
    st = st_ids(sorted(ids))
    rows = c.execute("""SELECT r.task_id, r.other_id, r.kind, a.list_id AS al, b.list_id AS bl FROM task_relations r
                        JOIN tasks a ON a.id=r.task_id JOIN tasks b ON b.id=r.other_id
                        WHERE (r.task_id = ANY(CAST(? AS BIGINT[])) OR r.other_id = ANY(CAST(? AS BIGINT[])))
                        AND a.deleted_at IS NULL AND b.deleted_at IS NULL ORDER BY r.id""", (st, st)).fetchall()
    if not rows:
        return out
    vis = mkvis()
    lck = dl_tasks_locked(c, uid, [r[k] for r in rows for k in ("task_id", "other_id")]) if uid else set()
    for r in rows:
        if r["task_id"] in ids and r["other_id"] not in lck and r["bl"] in vis and vis.task_ok(r["other_id"], r["bl"]):
            out.setdefault(r["task_id"], []).append({"id": r["other_id"], "kind": REL_OUT[(r["kind"], True)]})
        if r["other_id"] in ids and r["task_id"] not in lck and r["al"] in vis and vis.task_ok(r["task_id"], r["al"]):
            out.setdefault(r["other_id"], []).append({"id": r["task_id"], "kind": REL_OUT[(r["kind"], False)]})
    return out


def load_tasks(c, where, args=(), full_snips=False, lean_notes=False):
    """lean_notes: 2.280.0 A (#3108) the start state (GET /api/state): a note longer than ST_NOTE_MAX goes without its text
    (no "content" key, content_n = its length); the detail loads it (GET /api/tasks/<id>), the delta and every other answer
    carry it. A list's ciphertext (the lock: the browser decrypts and searches it) stays."""
    from ..personal.timetrack import vis_ids
    from ..collab.reactions import ltags_for
    from ..integrations.git import git_code_for
    from ..family.family import people_of
    rows = c.execute(f"SELECT * FROM tasks WHERE {where}", args).fetchall()
    # 1.10.0 safety net: a participant never gets a task of that list they must not see, whatever the caller's query;
    # context tasks (parents of an assigned subtask) come without notes, link, files, fields and comments
    ctx, pl, pv = set(), set(), set()
    viewer = g.user["id"] if has_request_context() and getattr(g, "user", None) else None
    if viewer and rows:
        pl = set(plists(c, viewer))
        if pl:
            pv, _, ctx = pvis(c, viewer)
            rows = [r for r in rows if r["list_id"] not in pl or r["id"] in pv]
    ids = {r["id"] for r in rows}
    # 2.65.0 (#1505): files, comments, field values and AI usage read only the rows of these tasks (one array parameter, the
    # tables' task_id indexes) instead of every row of the instance; the Python filters on ids stay (same result).
    # 2.579.0 (#4184): the dependency queries now too (were left whole for a slower plan with the array; the array now only
    # limits the task_deps side: its primary key / blocker index, tests/p2579_b_api_test.py prints both EXPLAINs)
    idl = st_ids(sorted(ids))
    tags = tags_for(c, ids)
    ltags = ltags_for(c, ids) if ids else {}
    atts = {}  # the task's own files; files of comments are shown inside their comment (timeline)
    # 2.30.0 (#380): agent = the name of the agent that stored the file ("Created by agent" in the app), else absent
    for a in c.execute("""SELECT a.id, a.task_id, a.name, a.mime, a.size, a.created_at, u.kind, u.display_name, u.username, a.enc, a.enc_by, a.e2e_gen, a.legacy_aad
                          FROM attachments a LEFT JOIN users u ON u.id=a.user_id WHERE a.comment_id IS NULL AND a.deleted_at IS NULL
                          AND a.task_id = ANY(CAST(? AS BIGINT[])) ORDER BY a.id""", (idl,)):
        if a["task_id"] in ids:
            d = {k: a[k] for k in ("id", "name", "mime", "size", "created_at")}
            if a["enc"] == 2:  # 2.64.2 B (#1817): a list file (name = list ciphertext, the browser decrypts it)
                d.update(enc=2, e2e_gen=a["e2e_gen"], task_id=a["task_id"])  # 2.539.0 (#4376): + its task (the file's AAD)
            elif a["enc"]:  # 2.42.0 (#828): encrypted in the browser; mine = I uploaded it (only I can open it)
                d.update(enc=True, enc_mine=bool(viewer) and a["enc_by"] == viewer)
                if d["enc_mine"] and a["legacy_aad"]:  # 2.278.0 C (#3091): the AAD of the old server, only for the uploader
                    d["legacy_aad"] = a["legacy_aad"]
            if a["kind"] == "agent":
                d["agent"] = a["display_name"] or a["username"]
            atts.setdefault(a["task_id"], []).append(d)
    # 2.272.0 E2 (#3038): the files of the task and its comments in the trash (restore in the app), only when there are some
    atrash = {}
    # 2.272.0 F (#3038, review E2-M6): not the files of a deleted comment (their restore is 404); mine = my comment's file
    for a in c.execute("""SELECT a.id, a.task_id, a.name, a.size, a.comment_id, a.deleted_at, cm.user_id AS cm_user FROM attachments a
                          LEFT JOIN obj_comments cm ON cm.id=a.comment_id WHERE a.deleted_at IS NOT NULL
                          AND (a.comment_id IS NULL OR (cm.id IS NOT NULL AND cm.deleted_at IS NULL))
                          AND a.task_id = ANY(CAST(? AS BIGINT[])) ORDER BY a.deleted_at DESC, a.id""", (idl,)):
        if a["task_id"] in ids:
            atrash.setdefault(a["task_id"], []).append({**{k: a[k] for k in ("id", "name", "size", "comment_id", "deleted_at")},
                                                        "mine": bool(viewer) and a["cm_user"] == viewer,
                                                        "days": max(1, ret_days("trash"))})
    if atts:  # 2.61.0 (#1818): + up (not checked by the virus scanner yet / locked), only files with a mark
        from ..files.scan import sc_up
        sc_up(c, "att", [d for v in atts.values() for d in v])
    # comment count + unread (comments of others newer than the last one I have seen)
    cms, uid = {}, (g.user["id"] if has_request_context() and getattr(g, "user", None) else None)
    if uid and ids:
        # 2.41.0 (#1383): + a = open approval cards of agents in the comments (the task's badge)
        # 2.972.0 (#5272): the comments' core (obj_comments kind 'task'; the buttons in extra)
        for r in c.execute("""SELECT k.ref_id AS task_id, COUNT(*) AS n,
                                     SUM(CASE WHEN k.id > COALESCE(s.seen_id, 0) AND k.user_id IS DISTINCT FROM ? THEN 1 ELSE 0 END) AS u,
                                     SUM(CASE WHEN k.extra->'choice' IS NULL AND k.extra->'choices'->>'approval' IS NOT NULL
                                              AND k.extra->'choices'->>'withdrawn_at' IS NULL AND COALESCE(k.extra->'choices'->>'expires_at', '9') > ?
                                              THEN 1 ELSE 0 END) AS a
                              FROM obj_comments k LEFT JOIN obj_seen s ON s.kind='task' AND s.ref_id=k.ref_id AND s.user_id=?
                              WHERE k.kind='task' AND k.deleted_at IS NULL AND k.ref_id = ANY(CAST(? AS BIGINT[])) GROUP BY k.ref_id""",
                           (uid, iso_ms(now_utc()), uid, idl)):
            if r["task_id"] in ids:
                cms[r["task_id"]] = (r["n"], r["u"] or 0, r["a"] or 0)
    # custom field values (fields of the task's current list) and dependencies: blocked = open blockers
    # (also ones I cannot see), blockers = the open ones I can see, blocking = open tasks waiting on it
    fvs, blk, bing, fat = {}, {}, {}, {}
    if ids:
        for r in c.execute("""SELECT v.task_id, v.field_id, v.value, v.set_at FROM task_field_values v JOIN list_fields f ON f.id=v.field_id
                              JOIN tasks t ON t.id=v.task_id WHERE f.list_id=t.list_id AND v.task_id = ANY(CAST(? AS BIGINT[]))""", (idl,)):
            if r["task_id"] in ids:
                fvs.setdefault(r["task_id"], {})[str(r["field_id"])] = r["value"]
                if r["set_at"]:  # 2.410.0 B (#3515): since when (only the known ones)
                    fat.setdefault(r["task_id"], {})[str(r["field_id"])] = r["set_at"]
        from ..lists.formula import fx_fill
        fx_fill(c, fvs, {r["id"]: r["list_id"] for r in rows if r["list_id"]})  # 2.43.0 (#1328): formula fields, computed
        for r in c.execute(f"""SELECT d.task_id, d.blocker_id, b.list_id FROM task_deps d JOIN tasks b ON b.id=d.blocker_id
                              JOIN tasks w ON w.id=d.task_id
                              WHERE b.status=0 AND b.deleted_at IS NULL AND b.list_id IN {PROJ_SQL} AND w.list_id IN {PROJ_SQL}
                              AND d.task_id = ANY(CAST(? AS BIGINT[]))""", (idl,)):
            if r["task_id"] in ids:
                blk.setdefault(r["task_id"], []).append((r["blocker_id"], r["list_id"]))
        for r in c.execute(f"""SELECT d.blocker_id, COUNT(*) AS n FROM task_deps d JOIN tasks t ON t.id=d.task_id
                              JOIN tasks b ON b.id=d.blocker_id
                              WHERE t.status=0 AND t.deleted_at IS NULL AND t.list_id IN {PROJ_SQL} AND b.list_id IN {PROJ_SQL}
                              AND d.blocker_id = ANY(CAST(? AS BIGINT[])) GROUP BY d.blocker_id""", (idl,)):
            if r["blocker_id"] in ids:
                bing[r["blocker_id"]] = r["n"]
    vis = vis_ids(c, uid) if blk and uid else set()
    aiu = {}  # 2.1.1 (#326): model usage agents reported for the task ("AI usage" in the task panel)
    if ids and uid and c.execute("SELECT 1 FROM agent_usage WHERE task_id IS NOT NULL LIMIT 1").fetchone():
        for r in c.execute("""SELECT task_id, COUNT(*) AS n, SUM(input_tokens+output_tokens+cache_write_tokens) AS tok,
                                     SUM(cost_usd) AS cost FROM agent_usage WHERE task_id = ANY(CAST(? AS BIGINT[])) GROUP BY task_id""",
                           (idl,)):
            if r["task_id"] in ids:
                aiu[r["task_id"]] = {"tokens": r["tok"] or 0, "cost": round(r["cost"], 4) if r["cost"] is not None else None,
                                     "calls": r["n"]}
    gcode = git_code_for(c, ids) if ids else {}  # 2.2.0 (#271): linked pull requests + commits
    from ..integrations.gitbuild import git_build_for
    gbuild = git_build_for(c, [r for r in rows if r["id"] not in ctx]) if ids else {}  # 2.151.0 A (#2558): the build state
    from ..collab.e2e import e2e_note_flags
    encn = e2e_note_flags(c, ids, viewer)  # 2.42.0 (#828): tasks with an encrypted note (never its content)
    from ..collab.notelock import ln_locked_ids
    lockn = ln_locked_ids(c, ids)  # 2.48.0 (#1642): tasks whose note is locked with a password (never its content)
    ppl = people_of(c, ids)  # 2.19.0 (#653): who comes along
    wat = wat_of(c, ids - ctx)  # 2.473.0 (#3357): who watches it (not on a read-only context task)
    wk = wk_for(c, ids - ctx) if uid else {}  # 2.407.0 A (#3513): an agent works on it now
    rel = rel_of(c, ids - ctx, lambda: vis or vis_ids(c, uid), uid) if uid and ids else {}  # 2.576.0 (#3371): saved relations
    skinds = sk_kinds_of(c, {r["section_id"] for r in rows if r["section_id"]})  # 2.577.0 (#3354): the column's meaning, for section_kind
    out = []
    for r in rows:
        d = task_dict(r, tags, full_snips)
        d["ltags"] = ltags.get(r["id"], [])
        if r["section_id"] in skinds:
            d["sec_kind"] = skinds[r["section_id"]]
        if r["id"] in gcode and r["id"] not in ctx:
            d["code"] = gcode[r["id"]]
        b = gbuild.get(r["id"])
        if b and (b["state"] != "none" or b["package"]):  # 2.151.0 A (#2558): only where there is something to say
            d["code"] = {**d.get("code", {"prs": [], "commits": []}), "build": b}
        d["attachments"] = atts.get(r["id"], [])
        if r["id"] in atrash:
            d["attachments_trash"] = atrash[r["id"]]
        if r["id"] in encn and r["id"] not in ctx:
            d["encrypted_note"] = True
            if encn[r["id"]]:
                d["encrypted_note_mine"] = True
        if r["id"] in lockn and r["id"] not in ctx:
            d["note_locked"] = True
            if lockn[r["id"]] == viewer:
                d["note_locked_mine"] = True
        d["comment_count"], d["unread"], apv = cms.get(r["id"], (0, 0, 0))
        if apv:
            d["approvals_open"] = apv  # 2.41.0 (#1383)
        d["fields"] = fvs.get(r["id"], {})
        if r["id"] in fat:  # 2.410.0 B (#3515): {field id: since when it has its value}, absent = none known
            d["field_at"] = fat[r["id"]]
        d["blocked"] = len(blk.get(r["id"], []))
        d["blockers"] = [b for b, lid in blk.get(r["id"], []) if lid in vis and (lid not in pl or b in pv)]
        d["blocking"] = bing.get(r["id"], 0)
        if r["id"] in ppl:
            d["people"] = ppl[r["id"]]
        if r["id"] in wat:
            d["watchers"] = wat[r["id"]]
        if r["id"] in aiu and r["id"] not in ctx:
            d["ai_usage"] = aiu[r["id"]]
        if r["id"] in wk:
            d["working"] = wk[r["id"]]
        if r["id"] in rel:
            d["relations"] = rel[r["id"]]  # 2.576.0 (#3371): absent = none
        if r["id"] in ctx:
            d.update(content="", url=None, attachments=[], comment_count=0, unread=0, fields={}, irreversible_reason="", delivery_note="",
                     blockers=[], blocked=0, blocking=0, context=True)
            d.pop("approvals_open", None)
            d.pop("snippets", None)  # 2.35.0 (#1095)
            d.pop("snippets_n", None)
        if lean_notes and len(d.get("content") or "") > ST_NOTE_MAX and not d["content"].startswith("e2e1:"):
            d["content_n"] = len(d.pop("content").encode("utf-16-le")) // 2  # 2.280.0 F (#3108): as the client counts (JS length)
        out.append(d)
    from ..tasks.multilist import ml_fill
    ml_fill(c, out, viewer)  # 2.71.0 B (#1459): "also" = the further lists the viewer sees
    return out


# 2.575.0 B (#3966): the start state without the values every task has. A client that asks for it (td=1 on GET /api/state and
# GET /api/state/lists) gets the tasks without the keys below while they hold their default (None / '' / 0 / [] / {}) and this
# table as "tdef" in the same answer; it fills them back before any use (liveparts.js tdFill), so the task it works with is the
# one the whole state has. Only keys every task of load_tasks carries are in it (one that is sometimes absent -- milestone_id,
# review, fam, snippets_n, content of a long note ... -- would come back where it was absent on purpose); content only when the
# task has no content_n (a long note). Never in the agent API (/api/v1 serializes its own fields) nor without td=1.
TD_DEFAULTS = {
    "section_id": None, "parent_id": None, "content": "", "priority": 0, "status": 0, "due": None, "due_time": None,
    "reminders": "", "repeat": "", "repeat_from": "due", "completed_at": None, "deleted_at": None, "tt_id": None,
    "trash_section": None, "assigned_by": None, "assignee_group_id": None, "assignee_id": None, "budget_warn": 0,
    "completed_by": None, "created_by": None, "deadline": 0, "delivery": "", "delivery_at": None, "delivery_by": None,
    "delivery_job_id": None, "delivery_note": "", "delivery_task_id": None, "duration": None, "irreversible": 0,
    "irreversible_reason": "", "irreversible_yes_at": None, "irreversible_yes_by": None, "locked": 0, "nag": "", "pinned": 0,
    "plan_start": None, "remind_at": None, "start": None, "ticket_no": None, "ttype": "", "url": None, "wait_by": None,
    "wait_fired": "", "waiting_at": None, "wait_note": "", "wait_until": None,
    "tags": [], "ltags": [], "attachments": [], "comment_count": 0, "unread": 0, "fields": {}, "blocked": 0, "blockers": [],
    "blocking": 0,
    # 2.1002.0 (#5491): the core's columns of migration 5491_a (every task row has them, SELECT *); unset they cost a big start
    # set much (p3136_state_size)
    "updated_by": None, "deleted_by": None, "rev": 1,
}


def td_lean(tasks):
    """2.575.0 B (#3966): drop the keys of TD_DEFAULTS that hold their default (same type: 0 is not False) from these task
    dicts (in place) -> tasks."""
    for d in tasks:
        for k, v in TD_DEFAULTS.items():
            if k in d and type(d[k]) is type(v) and d[k] == v and not (k == "content" and "content_n" in d):
                del d[k]
    return tasks


def attachment_files(c, task_ids):
    """Paths of all attachments of these tasks (and their subtasks), to unlink after a hard delete."""
    from ..tasks.validation import descendants
    ids = set(task_ids)
    for t in list(ids):
        ids.update(descendants(c, t))
    if not ids:
        return []
    q = ",".join("?" * len(ids))
    return [r[0] for r in c.execute(f"SELECT path FROM attachments WHERE task_id IN ({q})", list(ids))]


def unlink_files(paths):
    root = os.path.realpath(ATT_DIR)
    failed = []
    for p in paths:
        if callable(p):  # 2.152.0 A (#2164): a clean-up after the commit outside ATT_DIR (an office folder, a picture)
            try:
                p()
            except Exception as e:  # noqa: BLE001 - the data is gone already; what is left is logged
                print("clean-up after a deletion failed:", type(e).__name__, flush=True)
            continue
        full = os.path.join(ATT_DIR, p)
        try:
            if not os.path.realpath(full).startswith(root + os.sep):  # 2.143.0 B (#2211, review): only files under ATT_DIR
                continue
            os.remove(full)
        except FileNotFoundError:
            continue
        except OSError as e:  # 2.152.0 D (#2173): counted + logged (path relative), tried again by the orphan sweep
            from ..notify.alerts import aa_count, aa_oserr
            aa_count("storage", "unlink", aa_oserr(e))
            print(f"unlink failed: {p} {type(e).__name__}", flush=True)
            failed.append(p)
            continue
        try:
            d = os.path.dirname(full)
            if d != ATT_DIR and not os.listdir(d):
                os.rmdir(d)
        except OSError:
            pass
    if failed:
        from ..admin.dataretention import orf_queue
        orf_queue(failed)


def running_pomo(c, uid=None):
    r = c.execute("SELECT * FROM pomos WHERE \"end\" IS NULL AND user_id=? ORDER BY id DESC LIMIT 1", (uid or me(),)).fetchone()
    return dict(r) if r else None


def csv_cell(s):
    """2.122.4 B (#2317): free text for a CSV cell, no formulas in spreadsheet programs (= + - @ TAB CR LF at the start)."""
    s = str(s or "")
    return "'" + s if s.lstrip(" \t\r\n\u00a0")[:1] in ("=", "+", "-", "@") or s[:1] in ("\t", "\r", "\n") else s  # 2.148.1 E (#2496): also after leading blanks


def csv_uncell(s):
    """2.273.0 D (#3051): inverse of csv_cell for a Kalmido CSV coming back in: drop the guard "'" it put before = + - @ (so "- x" lists survive)."""
    s = str(s or "")
    if s[:1] == "'" and (s[1:].lstrip(" \t\r\n\u00a0")[:1] in ("=", "+", "-", "@") or s[1:2] in ("\t", "\r", "\n")):
        return s[1:]
    return s
