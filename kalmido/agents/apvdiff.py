"""2.1068.0 (#5831): what the Yes of an approval card changes in a text -- the lines it removes and the lines it adds.

An agent's approval card binds a step (agents/control.py ctl_card_extra: method, path, body). For a step that replaces or
adds to a text the person sees the change itself instead of "Fields: body": the SERVER reckons it (never the agent: its
word is not to be trusted here) from the card's bound body against the target's text NOW, with the rights of the person
who looks at the card. Targets (stage 1): a knowledge page (PATCH .../wiki/pages/{id} body, POST .../append text + under),
a task's notes (PATCH .../tasks/{id} notes), a project's description (PATCH .../lists/{id}/overview description), a
comment (PATCH .../comments/{id} body). 2.1111.0 (#5830): the targeted changes (POST .../append and .../replace-section
of a page, a task's notes and a project's description; core/mdedit.py) show the change they make in the text now
("append" / "section" in the answer). Every other step: none (the card keeps its line).

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
from ..core.pg import ts_canon  # 2.1115.0 (#5951)
from ..core.i18n import tr
from ..accounts.session import me
from ..collab.liste2e import le2e_is_cipher
from ..core.objcomments import ocm_row
from ..wiki.wkfolder import wkf_locked, wkf_role
from ..wiki.wkhist import WikiUnreadable, wkh_body
from ..core.mdedit import MdHeadingError, md_edit, md_edit_input  # 2.1111.0 (#5830): the shared building block of targeted changes

APVD_CTX = 2  # lines of context around a change (#5831)
APVD_SHORT_ROWS = 40  # rows of the first view; "Show everything" asks with full=1
APVD_FULL_ROWS = 2000
APVD_SNAP_ROWS = 60  # rows kept with the answer (short: a record of what was approved, not a copy of the page)
APVD_LINE_MAX = 500  # characters of one line in the answer
APVD_LCS_MAX = 100000  # lines x lines of the changed middle; above: the middle as removed + added (review F2: difflib is
# not linear - 1,200 x 1,200 repeating lines took 20 s; the agent controls both sides)
APVD_STEPS = (  # (method, path below /api/v1, kind, the body's field with the new text)
    ("PATCH", re.compile(r"^wiki/pages/(\d+)$"), "wiki", "body"),
    ("POST", re.compile(r"^wiki/pages/(\d+)/append$"), "wiki_append", "text"),
    # 2.1111.0 (#5830): the targeted changes of a page, a task's notes and a project's description (core/mdedit.py)
    ("POST", re.compile(r"^wiki/pages/(\d+)/replace-section$"), "wiki_section", "text"),
    ("POST", re.compile(r"^tasks/(\d+)/notes/append$"), "task_append", "text"),
    ("POST", re.compile(r"^tasks/(\d+)/notes/replace-section$"), "task_section", "text"),
    ("POST", re.compile(r"^lists/(\d+)/overview/append$"), "project_append", "text"),
    ("POST", re.compile(r"^lists/(\d+)/overview/replace-section$"), "project_section", "text"),
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
    return le2e_is_cipher(v)


def apvd_split(kind):
    """2.1111.0 (#5830): a step's kind -> (the target's kind, mode None | append | replace)."""
    base, _, mode = kind.partition("_")
    return base, {"append": "append", "section": "replace"}.get(mode)


def apvd_target(c, uid, kind, tid, piece, b):
    """{name, ref, old, new, stamp} of the target for person uid, or {hidden: no_access | encrypted | gone}. A targeted
    change (append / replace a section, 2.1111.0 #5830) is reckoned against the text now with the same function as the
    route (core/mdedit.py md_edit); its heading not (or twice) there: the piece alone and no_heading."""
    base, mode = apvd_split(kind)
    t = _apvd_text(c, uid, base, tid, piece)
    if t.get("hidden") or not mode:
        return t
    try:  # review F5: the route's own check of the fields -- a step it would refuse with 400 shows no change
        _, head = md_edit_input(b, mode)
    except BadInput:
        return {**t, "old": "", "new": "", "no_heading": ""}
    try:
        return {**t, "new": md_edit(t["old"], mode, piece, head)}
    except MdHeadingError:  # the step would answer 404 / 409 - show the piece alone
        return {**t, "old": "", "new": piece, "no_heading": head}


def _apvd_text(c, uid, kind, tid, piece):
    """{name, ref, old, new = piece, stamp} of target kind (wiki | task | project | comment) for person uid, or {hidden}."""
    if kind == "wiki":
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
        return {"name": r["path"].rsplit("/", 1)[-1], "ref": r["path"], "old": old, "new": piece, "stamp": r["updated_at"],
                "sealed": (r["body"] or "") != old}  # review F4: stored sealed at rest
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
                "new": piece, "stamp": r["description_at"]}
    if kind == "comment":
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
    base, mode = apvd_split(kind)
    if base == "project":  # the save trims the description (lists/projects.py overview_patch)
        t = {**t, "new": t["new"].replace("\r\n", "\n").strip()} if "new" in t else t
    out = {"kind": base, "append": mode == "append", **({"section": True} if mode == "replace" else {})}
    if t.get("hidden"):
        return {**out, "hidden": t["hidden"], "name": "", "ref": "", "added": 0, "removed": 0, "rows": [], "more": False, "changed": False}
    d = apvd_lines(t["old"], t["new"]) if t["old"] != t["new"] else []
    rows, more = apvd_rows(d, limit)
    exp = b.get("expect_updated_at") or (ap.get("step") or {}).get("if_match")
    stamp = str(t.get("stamp") or "")
    # 2.1115.0 (#5951): stamps are TIMESTAMPTZ read canonically; the card's stored version may be an older text form
    changed = bool(stamp) and (ts_canon(exp) != ts_canon(stamp) if isinstance(exp, str) and exp
                               else bool(created_at) and ts_canon(stamp) > ts_canon(created_at))
    return {**out, "name": t["name"], "ref": t["ref"], "added": sum(1 for x in d if x[0] == "+" and x[1].strip()),
            "removed": sum(1 for x in d if x[0] == "-" and x[1].strip()),  # an empty line is no line in words
            "rows": rows, "more": more, "changed": changed,
            **({"no_heading": t["no_heading"]} if t.get("no_heading") else {}), **({"sealed": True} if t.get("sealed") else {})}


def apvd_snapshot(c, uid, ch, created_at):
    """The short diff stored with the answer of approval card ch (choices) by person uid, or None. Never fails the answer."""
    ap = (ch or {}).get("approval")
    if not isinstance(ap, dict) or not apvd_step(ap.get("step")):
        return None
    try:
        with c.savepoint():  # review F10: a failed statement must not abort the answer's transaction
            d = apvd_build(c, uid, ap, created_at, APVD_SNAP_ROWS)
    except Exception as e:  # noqa: BLE001  the answer counts; the record of the diff is extra
        print("apvd_snapshot failed", type(e).__name__, flush=True)
        return None
    if d and d.get("sealed"):  # review F4: a page sealed at rest -- its lines are never stored in plain text, only the counts
        d = {**d, "rows": [], "more": False}
    return d


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
        r = ocm_row(c, int(a["comment"]), live=True)
        if r is None or not task_visible(c, r["task_id"], uid, full=True):  # review F6: comments are the full view
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
        why = snap.get("hidden") or t.get("hidden")
        if why == "gone" and not snap.get("hidden") and (ans or {}).get("user_id") == uid:
            why = None  # review F1: a target gone since -- only the person who answered still sees what they approved
        if why:  # review F3: nothing of the target, not its name either
            return jsonify(diff={"kind": snap.get("kind"), "append": snap.get("append"), "hidden": why, "name": "", "ref": "",
                                 "added": 0, "removed": 0, "rows": [], "more": False, "changed": False, "decided": True,
                                 "at": (ans or {}).get("at")})
        return jsonify(diff={**snap, "decided": True, "at": (ans or {}).get("at")})
    return jsonify(diff=apvd_build(c, uid, ap, at, APVD_FULL_ROWS if full else APVD_SHORT_ROWS))
