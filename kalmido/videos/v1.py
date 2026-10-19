"""2.99.1 C (#1959): video sign-offs for agents and scripts (API v1; scopes read / comments).

A connected agent summarises the customer's feedback for the edit or adds notes at a timecode; Kalmido itself calls no
language model. What a token sees: the reviews at a task / list its account sees (review.py vdr_may with api=True). An AGENT
sees a review only when its task or list is shared with it (its list limit, never a health list, never another workspace);
reviews at a client only or at nothing (after a move) are for people in the app -- for every token, so the API answers the
same for an agent and a person's script. Never in the answer: the customer links (their token, signer data). No creating,
changing, deleting a review, no new version, no decision in the customer's name: that stays with people.
Writing: a comment / answer (author = the token's account) by everybody who sees the review (like the app); an answer to a
CUSTOMER's comment shows on the customer page, so it needs the right to change the task / list (like the portal answers of
tasks); done / not done: its author or who may change it."""
from flask import jsonify

from ..core.config import app
from ..core.access import access_note, Denied
from ..core.db import db
from ..core.i18n import N_, tr
from ..accounts.session import me
from ..api.v1 import BadInput, v1_args, v1_json, v1_view
from ..personal.timetrack import reject_unknown
from .review import vdr_comment_add, vdr_comment_row, vdr_dict, vdr_list_of, vdr_may, vdr_reload, vdr_tc, vdr_touch, vdr_versions

VDR_V1_LIMIT = 200
VDR_V1_CUSTOMER = N_("Only people who may change the task answer the customer")  # the portal answers' text (team/portal.py)


def vdr_v1_need(c, vid, write=False):
    """The review row for the token's account; 404 when it may not see it (in the trash, at a client only, at nothing)."""
    r = c.execute("SELECT * FROM video_reviews WHERE id=?", (vid,)).fetchone() if 0 < vid < 2 ** 62 else None
    uid = me()
    if not r or r["deleted_at"] or not (r["task_id"] or r["list_id"]) or not vdr_may(c, uid, r, api=True):
        raise Denied(404)
    if write and not vdr_may(c, uid, r, write=True, api=True):
        raise Denied(403)
    return r


def vdr_v1_comments(c, d):
    """The flat comments of vdr_dict -> top-level comments (by version, timecode) with their answers; timecode as text and the
    version's number; agent = written by an agent."""
    ns = {v["id"]: v["n"] for v in vdr_versions(c, d["id"])}
    ids = {x["author_id"] for x in d["comments"] if x["author_id"]}
    ag = {r[0] for r in c.execute(f"SELECT id FROM users WHERE id IN ({','.join('?' * len(ids))}) AND kind='agent'", list(ids))} if ids else set()
    out, by = [], {}
    for x in d["comments"]:
        y = {**x, "version": ns.get(x["version_id"]), "timecode": vdr_tc(x["at_sec"]), "agent": x["author_id"] in ag}
        if x["parent_id"]:
            by.setdefault(x["parent_id"], []).append(y)
        else:
            out.append(y)
    for y in out:
        y["replies"] = by.get(y["id"], [])
    out.sort(key=lambda y: (y["version"] or 0, y["at_sec"] is None, y["at_sec"] or 0, y["id"]))
    return out


def vdr_v1_dict(c, r, full=False):
    d = vdr_dict(c, r, me(), full=full, signoffs=False)  # 2.99.1 review C-L1: the customer links are never built here
    for k in ("signoffs", "org_id", "client_id", "deleted"):  # review C-L2: app-only keys (not in the schema)
        d.pop(k, None)
    d["can_write"] = vdr_may(c, me(), r, write=True, api=True)
    d["url"] = f"/api/v1/videos/{r['id']}"
    if full:
        d["comments"] = vdr_v1_comments(c, d)
    return d


def vdr_v1_id(v, what):
    try:
        i = int(v)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", what)) from None
    if not 0 < i < 2 ** 62:
        raise BadInput(tr("Invalid value: {0}", what))
    return i


@app.get("/api/v1/videos")
@v1_view
def vdr_v1_list():
    """?task_id= (the reviews at that task) | ?list_id= (at the list and at its tasks): the reviews you may see, newest first."""
    a = v1_args(("task_id", "list_id"))
    keys = [k for k in ("task_id", "list_id") if a.get(k) not in (None, "")]
    if len(keys) != 1:
        raise BadInput(tr("Invalid value: {0}", "task_id / list_id"))
    i, c, uid = vdr_v1_id(a[keys[0]], keys[0]), db(), me()
    if keys[0] == "task_id":
        rows = c.execute("SELECT * FROM video_reviews WHERE task_id=? AND deleted_at IS NULL ORDER BY id DESC LIMIT ?", (i, VDR_V1_LIMIT))
    else:
        rows = c.execute("SELECT * FROM video_reviews WHERE deleted_at IS NULL AND (list_id=? OR task_id IN "
                         "(SELECT id FROM tasks WHERE list_id=? AND deleted_at IS NULL)) ORDER BY id DESC LIMIT ?", (i, i, VDR_V1_LIMIT))
    return jsonify(data=[vdr_v1_dict(c, r) for r in rows.fetchall() if vdr_may(c, uid, r, api=True)], next_cursor=None)


@app.get("/api/v1/videos/<int:vid>")
@v1_view
def vdr_v1_get(vid):
    """A review: versions (links), state, the comments with timecode, name, text, done and their answers."""
    v1_args(())
    c = db()
    return jsonify(vdr_v1_dict(c, vdr_v1_need(c, vid), full=True))


@app.post("/api/v1/videos/<int:vid>/comments")
@v1_view
def vdr_v1_comment_new(vid):
    """{body, at_sec?, version_id? (default the newest), parent_id? (an answer)}."""
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("body", "at_sec", "version_id", "parent_id"))
    c, uid = db(), me()
    r = vdr_v1_need(c, vid)
    par = b.get("parent_id")
    if isinstance(par, int) and not isinstance(par, bool):
        p = c.execute("SELECT ext_name FROM video_comments WHERE id=? AND review_id=? AND deleted_at IS NULL", (par, vid)).fetchone()
        if p and p["ext_name"] and not vdr_may(c, uid, r, write=True, api=True):  # the customer page shows this answer
            raise Denied(403, tr(VDR_V1_CUSTOMER))
    cid = vdr_comment_add(c, r, uid, b)
    access_note(vdr_list_of(c, r), True)
    c.commit()
    d = vdr_v1_dict(c, vdr_reload(c, vid), full=True)
    one = next((y for x in d["comments"] for y in [x, *x["replies"]] if y["id"] == cid), None)
    return jsonify(comment=one, review=d), 201


@app.patch("/api/v1/videos/<int:vid>/comments/<int:cid>")
@v1_view
def vdr_v1_comment_patch(vid, cid):
    """{done: bool}: its author or who may change the review (like the app)."""
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("done",))
    if not isinstance(b.get("done"), bool):
        raise BadInput(tr("Expected {0}", '{"done": true}'))
    c, uid = db(), me()
    r = vdr_v1_need(c, vid)
    x = vdr_comment_row(c, r, cid)
    if x["author_id"] != uid and not vdr_may(c, uid, r, write=True, api=True):
        raise Denied(403)
    c.execute("UPDATE video_comments SET done=? WHERE id=?", (1 if b["done"] else 0, cid))
    vdr_touch(c, vid)
    access_note(vdr_list_of(c, r), True)
    c.commit()
    return jsonify(vdr_v1_dict(c, vdr_reload(c, vid), full=True))


def vdr_v1_spec(paths, schemas, op, ok, errs, ref, pid, q):
    """OpenAPI of the video sign-offs (called from api/openapi.py)."""
    T = "Tasks"
    cm = {"type": "object", "properties": {
        "id": {"type": "integer"}, "version_id": {"type": "integer"}, "version": {"type": ["integer", "null"], "description": "v1, v2 ... as a number"},
        "parent_id": {"type": ["integer", "null"]}, "at_sec": {"type": ["number", "null"], "description": "Seconds from the start; null = no timecode"},
        "timecode": {"type": "string", "description": "mm:ss or h:mm:ss, empty without a timecode"}, "body": {"type": "string"},
        "author_id": {"type": ["integer", "null"], "description": "null = the customer"}, "author": {"type": "string", "description": "Name"},
        "customer": {"type": "boolean", "description": "Written by the customer through the approval link"},
        "agent": {"type": "boolean"}, "done": {"type": "boolean"}, "created_at": {"type": "string"},
        "replies": {"type": "array", "items": {"type": "object"}, "description": "The answers (one level), same fields"}}}
    schemas["VideoComment"] = cm
    schemas["VideoReview"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "title": {"type": "string"}, "state": {"type": "string", "enum": ["open", "approved", "changes"],
                                                                         "description": "The customer's decision (changes = changes requested)"},
        "space": {"type": "string"}, "task_id": {"type": ["integer", "null"]}, "list_id": {"type": ["integer", "null"]},
        "versions": {"type": "array", "items": {"type": "object", "description": "{id, n, url, provider vimeo|youtube|file|link, embed, timed, created_at}"}},
        "version": {"type": "integer", "description": "The newest version's number"}, "open_comments": {"type": "integer"},
        "can_write": {"type": "boolean"}, "comments": {"type": "array", "items": ref("VideoComment"), "description": "Only when reading one review"},
        "url": {"type": "string"}}}
    vid = pid("id", "Video sign-off id")
    paths["/videos"] = {"get": op(
        "Video sign-offs at a task or list (2.99.1)", T, ok({"type": "object", "properties": {"data": {"type": "array", "items": ref("VideoReview")},
                                                                                             "next_cursor": {"type": "null"}}}) | errs("400"),
        [q("task_id", "The reviews at this task", {"type": "integer"}), q("list_id", "The reviews at this list and at its tasks", {"type": "integer"})],
        desc="Exactly one of task_id / list_id. Only reviews whose task / list you see; an agent: shared with it. Reviews at a client "
             "only are for people in the app. Kalmido stores no video: versions are links.")}
    paths["/videos/{id}"] = {"get": op(
        "A video sign-off with its versions and comments (2.99.1)", T, ok(ref("VideoReview")) | errs("404"), [vid],
        desc="The comments by version and timecode, each with its answers; customer = written by the customer. Never the customer "
             "link itself.")}
    paths["/videos/{id}/comments"] = {"post": op(
        "Comment on a video sign-off, optionally at a timecode, or answer a comment (2.99.1)", T,
        ok({"type": "object", "properties": {"comment": ref("VideoComment"), "review": ref("VideoReview")}}, "Created", "201")
        | errs("400", "403", "404"), [vid],
        body={"type": "object", "required": ["body"], "properties": {
            "body": {"type": "string", "maxLength": 2000}, "at_sec": {"type": ["number", "null"], "minimum": 0, "maximum": 86400},
            "version_id": {"type": "integer", "description": "Default: the newest version"},
            "parent_id": {"type": "integer", "description": "Answer this top-level comment (its version and timecode)"}}},
        scope="comments",
        desc="Team comments stay internal. An answer to a customer's comment shows on the customer page: it needs the right to "
             "change the task / list (403 otherwise). A link without time control takes no timecode.")}
    paths["/videos/{id}/comments/{comment_id}"] = {"patch": op(
        "Mark a video comment done or open again (2.99.1)", T, ok(ref("VideoReview")) | errs("400", "403", "404"),
        [vid, pid("comment_id", "Comment id")], body={"type": "object", "required": ["done"], "properties": {"done": {"type": "boolean"}}},
        scope="comments", desc="Its author or who may change the task / list.")}
