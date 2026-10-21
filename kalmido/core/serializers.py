"""JSON shapes of database rows (tasks, lists, users ...) as the web client and the API see them."""
import os
from flask import g, has_request_context

from ..core.config import ATT_DIR
from ..core.i18n import tr
from ..accounts.session import me
from ..core.access import plists, PROJ_SQL, pvis
from ..core.pg import st_ids


# ---------------------------------------------------------------- serializers

def task_dict(r, tags, full_snips=False):
    from ..family.family import fam_task_out
    d = dict(zip(r.keys(), r)) if isinstance(r, tuple) else dict(r)  # 2.65.0 (#1505): a row at once, not key by key
    d.pop("reminded", None)
    d.pop("nag_at", None)
    d.pop("client_ref", None)  # 2.126.0 D (#1990): only the server matches it
    # 2.18.0 (#430): ms only on milestones, milestone_id only when set (keeps every other task's dict as it was)
    if not d.get("ms"):
        d.pop("ms", None)
    if d.get("milestone_id") is None:
        d.pop("milestone_id", None)
    for k in ("sprint_id", "sprint_at", "points"):  # 2.60.0 (#343 / #1511): only when set
        if d.get(k) is None:
            d.pop(k, None)
    if not d.get("review"):  # 2.60.0 C (#1512): review fields only when a review state is set; the reviewer when one is set
        for k in ("review", "review_at", "review_by", "review_sec"):
            d.pop(k, None)
    if d.get("reviewer_id") is None:
        d.pop("reviewer_id", None)
    if not d.get("approval"):  # 2.23.0 (#463): only on tasks that wait for / had an approval
        d.pop("approval", None)
        d.pop("approver_id", None)
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
    out = {}
    uid = uid or me()
    if ids is not None:  # 2.65.0 (#1505): only the rows of these tasks (one array parameter)
        ids = set(ids)
        for r in c.execute("SELECT task_id, tag FROM task_tags WHERE user_id=? AND task_id = ANY(CAST(? AS BIGINT[])) ORDER BY tag",
                           (uid, st_ids(ids))):
            out.setdefault(r["task_id"], []).append(r["tag"])
        return out
    for r in c.execute("SELECT task_id, tag FROM task_tags WHERE user_id=? ORDER BY tag", (uid,)):
        if ids is None or r["task_id"] in ids:
            out.setdefault(r["task_id"], []).append(r["tag"])
    return out


def load_tasks(c, where, args=(), full_snips=False):
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
    # tables' task_id indexes) instead of every row of the instance; the Python filters on ids stay (same result). The
    # dependency queries stay as they were (with the array the planner picks a far slower plan)
    idl = st_ids(sorted(ids))
    tags = tags_for(c, ids)
    ltags = ltags_for(c, ids) if ids else {}
    atts = {}  # the task's own files; files of comments are shown inside their comment (timeline)
    # 2.30.0 (#380): agent = the name of the agent that stored the file ("Created by agent" in the app), else absent
    for a in c.execute("""SELECT a.id, a.task_id, a.name, a.mime, a.size, a.created_at, u.kind, u.display_name, u.username, a.enc, a.enc_by, a.e2e_gen
                          FROM attachments a LEFT JOIN users u ON u.id=a.user_id WHERE a.comment_id IS NULL
                          AND a.task_id = ANY(CAST(? AS BIGINT[])) ORDER BY a.id""", (idl,)):
        if a["task_id"] in ids:
            d = {k: a[k] for k in ("id", "name", "mime", "size", "created_at")}
            if a["enc"] == 2:  # 2.64.2 B (#1817): a list file (name = list ciphertext, the browser decrypts it)
                d.update(enc=2, e2e_gen=a["e2e_gen"])
            elif a["enc"]:  # 2.42.0 (#828): encrypted in the browser; mine = I uploaded it (only I can open it)
                d.update(enc=True, enc_mine=bool(viewer) and a["enc_by"] == viewer)
            if a["kind"] == "agent":
                d["agent"] = a["display_name"] or a["username"]
            atts.setdefault(a["task_id"], []).append(d)
    if atts:  # 2.61.0 (#1818): + up (not checked by the virus scanner yet / locked), only files with a mark
        from ..files.scan import sc_up
        sc_up(c, "att", [d for v in atts.values() for d in v])
    # comment count + unread (comments of others newer than the last one I have seen)
    from ..core.db import iso_ms, now_utc
    cms, uid = {}, (g.user["id"] if has_request_context() and getattr(g, "user", None) else None)
    if uid and ids:
        # 2.41.0 (#1383): + a = open approval cards of agents in the comments (the task's badge)
        for r in c.execute("""SELECT k.task_id, COUNT(*) AS n,
                                     SUM(CASE WHEN k.id > COALESCE(s.seen_id, 0) AND k.user_id IS DISTINCT FROM ? THEN 1 ELSE 0 END) AS u,
                                     SUM(CASE WHEN k.choices IS NOT NULL AND k.choice IS NULL AND k.choices->>'approval' IS NOT NULL
                                              AND k.choices->>'withdrawn_at' IS NULL AND COALESCE(k.choices->>'expires_at', '9') > ?
                                              THEN 1 ELSE 0 END) AS a
                              FROM comments k LEFT JOIN task_seen s ON s.task_id=k.task_id AND s.user_id=?
                              WHERE k.deleted_at IS NULL AND k.task_id = ANY(CAST(? AS BIGINT[])) GROUP BY k.task_id""",
                           (uid, iso_ms(now_utc()), uid, idl)):
            if r["task_id"] in ids:
                cms[r["task_id"]] = (r["n"], r["u"] or 0, r["a"] or 0)
    # custom field values (fields of the task's current list) and dependencies: blocked = open blockers
    # (also ones I cannot see), blockers = the open ones I can see, blocking = open tasks waiting on it
    fvs, blk, bing = {}, {}, {}
    if ids:
        for r in c.execute("""SELECT v.task_id, v.field_id, v.value FROM task_field_values v JOIN list_fields f ON f.id=v.field_id
                              JOIN tasks t ON t.id=v.task_id WHERE f.list_id=t.list_id AND v.task_id = ANY(CAST(? AS BIGINT[]))""", (idl,)):
            if r["task_id"] in ids:
                fvs.setdefault(r["task_id"], {})[str(r["field_id"])] = r["value"]
        from ..lists.formula import fx_fill
        fx_fill(c, fvs, {r["id"]: r["list_id"] for r in rows if r["list_id"]})  # 2.43.0 (#1328): formula fields, computed
        for r in c.execute(f"""SELECT d.task_id, d.blocker_id, b.list_id FROM task_deps d JOIN tasks b ON b.id=d.blocker_id
                              JOIN tasks w ON w.id=d.task_id
                              WHERE b.status=0 AND b.deleted_at IS NULL AND b.list_id IN {PROJ_SQL} AND w.list_id IN {PROJ_SQL}"""):
            if r["task_id"] in ids:
                blk.setdefault(r["task_id"], []).append((r["blocker_id"], r["list_id"]))
        for r in c.execute(f"""SELECT d.blocker_id, COUNT(*) AS n FROM task_deps d JOIN tasks t ON t.id=d.task_id
                              JOIN tasks b ON b.id=d.blocker_id
                              WHERE t.status=0 AND t.deleted_at IS NULL AND t.list_id IN {PROJ_SQL} AND b.list_id IN {PROJ_SQL}
                              GROUP BY d.blocker_id"""):
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
    out = []
    for r in rows:
        d = task_dict(r, tags, full_snips)
        d["ltags"] = ltags.get(r["id"], [])
        if r["id"] in gcode and r["id"] not in ctx:
            d["code"] = gcode[r["id"]]
        b = gbuild.get(r["id"])
        if b and (b["state"] != "none" or b["package"]):  # 2.151.0 A (#2558): only where there is something to say
            d["code"] = {**d.get("code", {"prs": [], "commits": []}), "build": b}
        d["attachments"] = atts.get(r["id"], [])
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
        d["blocked"] = len(blk.get(r["id"], []))
        d["blockers"] = [b for b, lid in blk.get(r["id"], []) if lid in vis and (lid not in pl or b in pv)]
        d["blocking"] = bing.get(r["id"], 0)
        if r["id"] in ppl:
            d["people"] = ppl[r["id"]]
        if r["id"] in aiu and r["id"] not in ctx:
            d["ai_usage"] = aiu[r["id"]]
        if r["id"] in ctx:
            d.update(content="", url=None, attachments=[], comment_count=0, unread=0, fields={},
                     blockers=[], blocked=0, blocking=0, context=True)
            d.pop("approvals_open", None)
            d.pop("snippets", None)  # 2.35.0 (#1095)
            d.pop("snippets_n", None)
        out.append(d)
    from ..tasks.multilist import ml_fill
    ml_fill(c, out, viewer)  # 2.71.0 B (#1459): "also" = the further lists the viewer sees
    return out


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
    for p in paths:
        try:
            full = os.path.join(ATT_DIR, p)
            if not os.path.realpath(full).startswith(root + os.sep):  # 2.143.0 B (#2211, review): only files under ATT_DIR
                continue
            os.remove(full)
            d = os.path.dirname(full)
            if d != ATT_DIR and not os.listdir(d):
                os.rmdir(d)
        except OSError:
            pass


def running_pomo(c, uid=None):
    r = c.execute("SELECT * FROM pomos WHERE \"end\" IS NULL AND user_id=? ORDER BY id DESC LIMIT 1", (uid or me(),)).fetchone()
    return dict(r) if r else None


def csv_cell(s):
    """2.122.4 B (#2317): free text for a CSV cell, no formulas in spreadsheet programs (= + - @ TAB CR LF at the start)."""
    s = str(s or "")
    return "'" + s if s.lstrip(" \t\r\n\u00a0")[:1] in ("=", "+", "-", "@") or s[:1] in ("\t", "\r", "\n") else s  # 2.148.1 E (#2496): also after leading blanks
