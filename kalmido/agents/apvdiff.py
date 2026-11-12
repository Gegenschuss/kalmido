"""2.1068.0 (#5831): what the Yes of an approval card changes in a text -- the lines it removes and the lines it adds.

An agent's approval card binds a step (agents/control.py ctl_card_extra: method, path, body). For a step that replaces or
adds to a text the person sees the change itself instead of "Fields: body": the SERVER reckons it (never the agent: its
word is not to be trusted here) from the card's bound body against the target's text NOW, with the rights of the person
who looks at the card. Targets (stage 1): a knowledge page (PATCH .../wiki/pages/{id} body, POST .../append text + under),
a task's notes (PATCH .../tasks/{id} notes), a project's description (PATCH .../lists/{id}/overview description), a
comment (PATCH .../comments/{id} body). Every other step: none (the card keeps its line).

  GET /api/approvals/diff?chat=<message id> | ?comment=<comment id> [&full=1]
    -> {diff: null} (no text step) | {diff: {kind, name, ref, added, removed, rows, more, changed, hidden?, decided?, at?}}
       rows = [[op, line]]: op " " (context, two lines around each change), "+" added, "-" removed, "…" (a gap);
       more = rows were cut (full=1: all, up to APVD_FULL_ROWS); changed = the target changed since the card was made;
       hidden = encrypted | no_access | gone (no rows, no text of the target); decided = the snapshot stored with the
       answer (the state at the time of the Yes / No, short) instead of the state now.

Only the person of a chat card (its chat partner) and people who see the task of a comment card may ask; the target is
read with their rights (an approver who may not read the page sees "no_access", never its text). The snapshot is stored at
the answer (apvd_snapshot, agents/chat.py chat_choice_answer -> agent_chat.apv_diff, collab/cchoice.py lv_answer ->
obj_comments.extra->'apvdiff'; never inside choices, which go to the agent) with the answering person's rights and shown
only to a viewer who may read the target now (a gone target: the stored lines stay readable); the line diff is the one of the knowledge history (static/js/wkhist.js renders both with txtDiffHtml).
"""
import difflib
import json
import re

from flask import jsonify, request

from ..core.config import API_PREFIX, app
from ..core.access import Denied, list_role, task_visible
from ..core.db import db
from ..core.errors import BadInput
from ..core.i18n import tr
from ..accounts.session import me

APVD_CTX = 2  # lines of context around a change (#5831)
APVD_SHORT_ROWS = 40  # rows of the first view; "Show everything" asks with full=1
APVD_FULL_ROWS = 2000
APVD_SNAP_ROWS = 60  # rows kept with the answer (short: a record of what was approved, not a copy of the page)
APVD_LINE_MAX = 500  # characters of one line in the answer
APVD_LCS_MAX = 1500000  # lines x lines of the changed middle; above: the middle as removed + added (as wkhist.js wkh_diff)
APVD_STEPS = (  # (method, path below /api/v1, kind, the body's field with the new text)
    ("PATCH", re.compile(r"^wiki/pages/(\d+)$"), "wiki", "body"),
    ("POST", re.compile(r"^wiki/pages/(\d+)/append$"), "wiki_append", "text"),
    ("PATCH", re.compile(r"^tasks/(\d+)$"), "task", "notes"),
    ("PATCH", re.compile(r"^lists/(\d+)/overview$"), "project", "description"),
    ("PATCH", re.compile(r"^comments/(\d+)$"), "comment", "body"),
)


def apvd_step(st):
    """(kind, target id, the new text or the appended piece, body) of a text step, or None."""
    if not isinstance(st, dict) or not isinstance(st.get("path"), str):
        return None
    p = st["path"]
    if not p.startswith(API_PREFIX):
        return None
    b = st.get("body") if isinstance(st.get("body"), dict) else {}
    for m, rx, kind, field in APVD_STEPS:
        hit = rx.match(p[len(API_PREFIX):])
        if hit and st.get("method") == m:
            v = b.get(field)
            if kind == "task" and v is None:
                v = b.get("content")  # the old name of notes (api/v1.py field_alias)
            if not isinstance(v, str):
                return None
            return kind, int(hit.group(1)), v, b
    return None


def _cipher(v):
    from ..collab.liste2e import le2e_is_cipher
    return le2e_is_cipher(v)


def apvd_target(c, uid, kind, tid, piece, b):
    """{name, ref, old, new, stamp} of the target for person uid, or {hidden: no_access | encrypted | gone}."""
    if kind in ("wiki", "wiki_append"):
        from ..wiki.wkfolder import wkf_locked, wkf_role
        from ..wiki.wkhist import WikiUnreadable, wkh_body
        r = c.execute("SELECT * FROM wiki_pages WHERE id=?", (tid,)).fetchone()
        if r is None or r["deleted_at"]:
            return {"hidden": "gone"}
        if wkf_role(c, uid, r) is None:
            return {"hidden": "no_access"}
        if wkf_locked(c, r) or _cipher(r["body"]):
            return {"hidden": "encrypted"}
        try:
            old = wkh_body(c, r) or ""
        except WikiUnreadable:
            return {"hidden": "encrypted"}
        if kind == "wiki_append":
            from ..wiki.wkv1 import wkv_append_text
            under = b.get("under") if isinstance(b.get("under"), str) and b["under"].strip() else None
            new = wkv_append_text(old, piece, under)
            if new is None:  # the heading is not there (any more): the step would answer 404 - show the piece alone
                return {"name": r["path"].rsplit("/", 1)[-1], "ref": r["path"], "old": "", "new": piece, "stamp": r["updated_at"],
                        "no_heading": under}
        else:
            new = piece
        return {"name": r["path"].rsplit("/", 1)[-1], "ref": r["path"], "old": old, "new": new, "stamp": r["updated_at"]}
    if kind == "task":
        r = c.execute("SELECT id, title, content, updated_at, deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()
        if r is None or r["deleted_at"]:
            return {"hidden": "gone"}
        if not task_visible(c, tid, uid, full=True):
            return {"hidden": "no_access"}
        if _cipher(r["content"]) or _cipher(piece):
            return {"hidden": "encrypted"}
        return {"name": "" if _cipher(r["title"]) else r["title"], "ref": f"#{tid}", "old": r["content"] or "", "new": piece,
                "stamp": r["updated_at"]}
    if kind == "project":
        r = c.execute("SELECT id, name, description, description_at FROM lists WHERE id=?", (tid,)).fetchone()
        if r is None:
            return {"hidden": "gone"}
        if list_role(c, tid, uid) in (None, "participant"):  # the overview is the full roles' (lists/projects.py need_overview)
            return {"hidden": "no_access"}
        if _cipher(r["description"]) or _cipher(piece):
            return {"hidden": "encrypted"}
        return {"name": "" if _cipher(r["name"]) else r["name"], "ref": "", "old": r["description"] or "",
                "new": piece.replace("\r\n", "\n").strip(), "stamp": r["description_at"]}
    if kind == "comment":
        from ..core.objcomments import ocm_row
        r = ocm_row(c, tid, live=True)
        if r is None:
            return {"hidden": "gone"}
        if not task_visible(c, r["task_id"], uid, full=True):
            return {"hidden": "no_access"}
        if _cipher(r["body"]) or _cipher(piece):
            return {"hidden": "encrypted"}
        t = c.execute("SELECT title FROM tasks WHERE id=?", (r["task_id"],)).fetchone()
        name = t["title"] if t and not _cipher(t["title"]) else ""
        return {"name": name, "ref": f"#{r['task_id']}", "old": r["body"] or "", "new": piece, "stamp": r["edited_at"] or r["created_at"]}
    return {"hidden": "gone"}


def apvd_lines(a, b):
    """The line diff of texts a -> b: [[op, line]] with op " " / "-" / "+" (every line, no context cut yet)."""
    A, B = a.split("\n"), b.split("\n")
    s = 0
    while s < len(A) and s < len(B) and A[s] == B[s]:
        s += 1
    e = 0
    while e < len(A) - s and e < len(B) - s and A[-1 - e] == B[-1 - e]:
        e += 1
    a1, b1 = A[s:len(A) - e], B[s:len(B) - e]
    mid = []
    if len(a1) * len(b1) > APVD_LCS_MAX:
        mid = [["-", x] for x in a1] + [["+", x] for x in b1]
    else:
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a1, b1, autojunk=False).get_opcodes():
            if op == "equal":
                mid += [[" ", x] for x in a1[i1:i2]]
            else:
                mid += [["-", x] for x in a1[i1:i2]] + [["+", x] for x in b1[j1:j2]]
    return [[" ", x] for x in A[:s]] + mid + [[" ", x] for x in A[len(A) - e:]]


def apvd_rows(d, limit):
    """Only the changes with APVD_CTX lines around them, gaps as ["…", ""]; -> (rows, more)."""
    near = [False] * len(d)
    for i, (op, _) in enumerate(d):
        if op != " ":
            for k in range(max(0, i - APVD_CTX), min(len(d), i + APVD_CTX + 1)):
                near[k] = True
    out, gap = [], False
    for i, (op, x) in enumerate(d):
        if not near[i]:
            if not gap:
                out.append(["…", ""])
            gap = True
            continue
        gap = False
        out.append([op, x[:APVD_LINE_MAX]])
    while out and out[-1][0] == "…":
        out.pop()
    return out[:limit], len(out) > limit


def apvd_build(c, uid, ap, created_at, limit):
    """The diff dict of approval card ap (choices.approval) for person uid, or None (no text step)."""
    hit = apvd_step(ap.get("step"))
    if not hit:
        return None
    kind, tid, piece, b = hit
    t = apvd_target(c, uid, kind, tid, piece, b)
    out = {"kind": "wiki" if kind == "wiki_append" else kind, "append": kind == "wiki_append"}
    if t.get("hidden"):
        return {**out, "hidden": t["hidden"], "name": "", "ref": "", "added": 0, "removed": 0, "rows": [], "more": False, "changed": False}
    d = apvd_lines(t["old"], t["new"]) if t["old"] != t["new"] else []
    rows, more = apvd_rows(d, limit)
    exp = b.get("expect_updated_at") or (ap.get("step") or {}).get("if_match")
    stamp = str(t.get("stamp") or "")
    changed = bool(stamp) and (exp != stamp if isinstance(exp, str) and exp else bool(created_at) and stamp > str(created_at))
    return {**out, "name": t["name"], "ref": t["ref"], "added": sum(1 for x in d if x[0] == "+"),
            "removed": sum(1 for x in d if x[0] == "-"), "rows": rows, "more": more, "changed": changed,
            **({"no_heading": t["no_heading"]} if t.get("no_heading") else {})}


def apvd_snapshot(c, uid, ch, created_at):
    """The short diff stored with the answer of approval card ch (choices) by person uid, or None. Never fails the answer."""
    ap = (ch or {}).get("approval")
    if not isinstance(ap, dict) or not apvd_step(ap.get("step")):
        return None
    try:
        return apvd_build(c, uid, ap, created_at, APVD_SNAP_ROWS)
    except Exception as e:  # noqa: BLE001  the answer counts; the record of the diff is extra
        print("apvd_snapshot failed", type(e).__name__, flush=True)
        return None


def _jl(v):
    if isinstance(v, (dict, list)) or v is None:
        return v
    try:
        return json.loads(v)
    except ValueError:
        return None


@app.get("/api/approvals/diff")
def apvd_route():
    """?chat=<id> | ?comment=<id> [&full=1] -> {diff} (module docstring)."""
    c = db()
    uid = me()
    a = request.args
    full = a.get("full") == "1"
    if bool(a.get("chat")) == bool(a.get("comment")) or not re.fullmatch(r"[0-9]{1,18}", a.get("chat") or a.get("comment") or ""):
        raise BadInput(tr("Invalid value: {0}", "chat"))
    if a.get("chat"):
        m = c.execute("""SELECT choices, choice, created_at, apv_diff FROM agent_chat WHERE id=? AND user_id=? AND sender='agent'
                         AND choices->'approval' IS NOT NULL""", (int(a["chat"]), uid)).fetchone()
        if not m:
            raise Denied(404)
        ch, ans, at, snap = _jl(m["choices"]) or {}, _jl(m["choice"]), m["created_at"], _jl(m["apv_diff"])
    else:
        from ..core.objcomments import ocm_row
        r = ocm_row(c, int(a["comment"]), live=True)
        if r is None or not task_visible(c, r["task_id"], uid):
            raise Denied(404)
        ch, ans, at = _jl(r["choices"]) or {}, _jl(r["choice"]), r["created_at"]
        if not isinstance(ch.get("approval"), dict):
            raise Denied(404)
        snap = _jl(c.execute("SELECT extra->'apvdiff' FROM obj_comments WHERE id=?", (int(a["comment"]),)).fetchone()[0])
    ap = ch.get("approval") or {}
    if ans is not None or ch.get("withdrawn_at"):  # decided / closed: the state at the answer, never the target now
        if not isinstance(snap, dict):
            return jsonify(diff=None)
        hit = apvd_step(ap.get("step"))  # the viewer's rights NOW decide whether the stored lines may be shown
        t = apvd_target(c, uid, hit[0], hit[1], hit[2], hit[3]) if hit else {"hidden": "gone"}
        if t.get("hidden") in ("no_access", "encrypted") or snap.get("hidden"):
            return jsonify(diff={**snap, "rows": [], "more": False, "hidden": snap.get("hidden") or t["hidden"], "decided": True,
                                 "at": (ans or {}).get("at")})
        return jsonify(diff={**snap, "decided": True, "at": (ans or {}).get("at")})
    return jsonify(diff=apvd_build(c, uid, ap, at, APVD_FULL_ROWS if full else APVD_SHORT_ROWS))
