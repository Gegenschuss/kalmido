"""Notes of a list / project."""
import re
from flask import jsonify, request, Response

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, iso, iso_ms, now_utc
from ..accounts.session import me
from ..core.access import Denied, list_role, plists, vis_sql, WRITE_ROLES
from ..tasks.validation import as_int
from ..collab.comments import user_names
from ..personal.timetrack import BadInput, reject_unknown
from ..api.v1 import API_PAGE_MAX, cursor_dec, cursor_enc, v1_args, v1_call, v1_json, v1_limit, v1_view


# ---------------------------------------------------------------- 2.17.0 (#442): notes of a list / project
# Markdown documents next to the tasks of a list (meeting notes, briefings, decisions). Who sees the list (not as a
# participant, who only sees the tasks assigned to them) reads its notes; owner, admins and members write them. #123 in a
# note links that task (in the app), a note has its own address (#note/<id>), tags, can be pinned (first in the list) and
# is found by the search and the command field. The REST API + MCP tools do the same (scope tasks:write to write,
# delete to delete).
NOTE_TITLE_MAX, NOTE_BODY_MAX, NOTE_TAGS_MAX = 300, 200_000, 20


def note_role(c, lid, write=False):
    """The role of the current user in list lid for its notes; 404 = cannot see them (participants neither)."""
    role = list_role(c, lid) if lid else None
    if not role or role == "participant":
        raise Denied(404)
    if write and role not in WRITE_ROLES:
        raise Denied(403)
    return role


def need_note(c, nid, write=False):
    r = c.execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()
    if not r:
        raise Denied(404)
    note_role(c, r["list_id"], write)
    return r


def clean_note_tags(v):
    if v in (None, ""):
        return []
    if isinstance(v, str):
        v = v.split(",")
    if not isinstance(v, list):
        raise BadInput(tr("Invalid value: {0}", "tags"))
    out = []
    for x in v:
        if not isinstance(x, str):
            raise BadInput(tr("Invalid value: {0}", "tags"))
        x = x.strip().lstrip("#").strip()[:40]
        if x and x.casefold() not in (y.casefold() for y in out):
            out.append(x)
    return out[:NOTE_TAGS_MAX]


def note_fields(b, partial=False):
    out = {}
    if "title" in b or not partial:
        t = b.get("title")
        if not isinstance(t, str) or not t.strip():
            raise BadInput(tr("Please give the note a title"))
        out["title"] = re.sub(r"\s+", " ", t).strip()[:NOTE_TITLE_MAX]
    if "body" in b:
        if not isinstance(b["body"], str):
            raise BadInput(tr("Invalid value: {0}", "body"))
        if len(b["body"]) > NOTE_BODY_MAX:
            raise BadInput(tr("The note is too long (at most {0} characters)", NOTE_BODY_MAX))
        out["body"] = b["body"]
    if "tags" in b:
        out["tags"] = ",".join(clean_note_tags(b["tags"]))
    if "pinned" in b:
        if not isinstance(b["pinned"], (bool, int)) or b["pinned"] not in (0, 1, True, False):
            raise BadInput(tr("Invalid value: {0}", "pinned"))
        out["pinned"] = int(bool(b["pinned"]))
    return out


def note_dict(r, full=True, names=None):
    d = {"id": r["id"], "list_id": r["list_id"], "title": r["title"], "tags": [x for x in (r["tags"] or "").split(",") if x],
         "pinned": bool(r["pinned"]), "created_by": r["created_by"], "updated_by": r["updated_by"],
         "created_at": r["created_at"], "updated_at": r["updated_at"]}
    if full:
        d["body"] = r["body"]
    else:
        d["excerpt"] = re.sub(r"\s+", " ", re.sub(r"[#*_`>\[\]]", "", r["body"] or "")).strip()[:160]
    if names is not None:
        d["updated_by_name"] = names.get(r["updated_by"], "")
    return d


def notes_visible_sql(c, uid):
    """(where, args) for the notes the user may read: lists they see, without the lists where they are a participant."""
    pl = plists(c, uid)
    w = f"list_id IN {vis_sql()}" + (f" AND list_id NOT IN ({','.join(str(int(x)) for x in pl)})" if pl else "")
    return w, [uid, uid]


def notes_brief(c, uid):
    """For /api/state: every readable note without its text (the sidebar count, the command field, links)."""
    w, a = notes_visible_sql(c, uid)
    return [{"id": r["id"], "list_id": r["list_id"], "title": r["title"], "tags": [x for x in (r["tags"] or "").split(",") if x],
             "pinned": bool(r["pinned"]), "updated_at": r["updated_at"]}
            for r in c.execute(f"SELECT id, list_id, title, tags, pinned, updated_at FROM notes WHERE {w} ORDER BY updated_at DESC LIMIT 2000", a)]


@app.get("/api/lists/<int:lid>/notes")
def notes_of_list(lid):
    """The notes of a list, pinned first, then the newest change first (with their text)."""
    c = db()
    role = note_role(c, lid)
    rows = c.execute("SELECT * FROM notes WHERE list_id=? ORDER BY pinned DESC, updated_at DESC, id DESC", (lid,)).fetchall()
    names = user_names(c, {r["updated_by"] for r in rows if r["updated_by"]})
    return jsonify(notes=[note_dict(r, names=names) for r in rows], may_write=role in WRITE_ROLES)


@app.post("/api/lists/<int:lid>/notes")
def note_create(lid):
    """{title, body?, tags?, pinned?} -- a new note in the list (owner, admins, members)."""
    c = db()
    note_role(c, lid, write=True)
    f = note_fields(body())
    ts, uid = iso(now_utc()), me()
    nid = c.execute("INSERT INTO notes(list_id,title,body,tags,pinned,created_by,updated_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (lid, f["title"], f.get("body", ""), f.get("tags", ""), f.get("pinned", 0), uid, uid, ts, ts)).lastrowid
    bump(c)
    c.commit()
    r = c.execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()
    return jsonify(note_dict(r)), 201


@app.get("/api/notes/<int:nid>")
def note_get(nid):
    c = db()
    r = need_note(c, nid)
    return jsonify(note_dict(r, names=user_names(c, [r["updated_by"]] if r["updated_by"] else [])))


@app.patch("/api/notes/<int:nid>")
def note_update(nid):
    """{title?, body?, tags?, pinned?, list_id? (move to another list I may write), expect_updated_at? (409 when someone
    else changed it in between: the client shows both versions)}"""
    c = db()
    r = need_note(c, nid, write=True)
    b = body()
    f = note_fields(b, partial=True)
    if "list_id" in b:
        lid = b["list_id"]
        if isinstance(lid, bool) or not isinstance(lid, int):
            raise BadInput(tr("Invalid value: {0}", "list_id"))
        note_role(c, lid, write=True)
        f["list_id"] = lid
    exp = b.get("expect_updated_at")
    if exp and exp != r["updated_at"] and ("body" in f or "title" in f):
        cur = note_dict(r, names=user_names(c, [r["updated_by"]] if r["updated_by"] else []))
        return jsonify(error=tr("Changed in the meantime by {0}", cur.get("updated_by_name") or "?"), note=cur), 409
    if f:
        f["updated_by"], f["updated_at"] = me(), iso_ms(now_utc())
        c.execute(f"UPDATE notes SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), nid])
        bump(c)
        c.commit()
    r = c.execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()
    return jsonify(note_dict(r, names=user_names(c, [r["updated_by"]] if r["updated_by"] else [])))


@app.delete("/api/notes/<int:nid>")
def note_delete(nid):
    """Deletes the note; answers it in full (the app's Undo creates it again)."""
    c = db()
    r = need_note(c, nid, write=True)
    c.execute("DELETE FROM notes WHERE id=?", (nid,))
    bump(c)
    c.commit()
    return jsonify(ok=True, note=note_dict(r))


def notes_search(c, uid, q, lid=None, limit=50):
    w, a = notes_visible_sql(c, uid)
    if lid:
        w += " AND list_id=?"
        a.append(lid)
    if q:
        for word in q.split()[:6]:
            like = "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            w += " AND (title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\' OR tags LIKE ? ESCAPE '\\')"
            a += [like, like, like]
    return c.execute(f"SELECT * FROM notes WHERE {w} ORDER BY pinned DESC, updated_at DESC LIMIT ?", (*a, limit)).fetchall()


@app.get("/api/notes")
def notes_find():
    """?q=words (title, text, tags; all words), ?list_id= -- notes I may read, without their full text."""
    c = db()
    uid = me()
    lid = request.args.get("list_id")
    lid = as_int(lid, "list_id", 1) if lid else None
    rows = notes_search(c, uid, (request.args.get("q") or "").strip()[:200], lid)
    return jsonify(notes=[note_dict(r, full=False) for r in rows])


# ---- REST API v1
@app.get("/api/v1/lists/<int:lid>/notes")
@v1_view
def v1_list_notes(lid):
    v1_args(("limit", "cursor"))
    a = request.args
    c = db()
    note_role(c, lid)
    after, limit = cursor_dec("n", a.get("cursor")), v1_limit(a)
    rows = c.execute("SELECT * FROM notes WHERE list_id=? AND id>? ORDER BY id LIMIT ?", (lid, after, limit + 1)).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    return jsonify(data=[note_dict(r) for r in rows], next_cursor=cursor_enc("n", rows[-1]["id"]) if more else None)


@app.post("/api/v1/lists/<int:lid>/notes")
@v1_view
def v1_note_create(lid):
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("title", "body", "tags", "pinned"))
    j = v1_call(note_create, lid, body=b)
    return jsonify({k: v for k, v in j.items() if k != "updated_by_name"}), 201


@app.get("/api/v1/notes")
@v1_view
def v1_notes_search():
    a = v1_args(("q", "list_id", "limit"))
    c = db()
    lid = as_int(a["list_id"], "list_id", 1) if a.get("list_id") else None
    rows = notes_search(c, me(), (a.get("q") or "").strip()[:200], lid, v1_limit(a))
    return jsonify(data=[note_dict(r, full=False) for r in rows], next_cursor=None)


@app.get("/api/v1/notes/<int:nid>")
@v1_view
def v1_note_get(nid):
    v1_args(())
    return jsonify(note_dict(need_note(db(), nid)))


@app.patch("/api/v1/notes/<int:nid>")
@v1_view
def v1_note_update(nid):
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("title", "body", "tags", "pinned", "list_id", "expect_updated_at"))
    j = v1_call(note_update, nid, body=b)
    return jsonify({k: v for k, v in j.items() if k != "updated_by_name"})


@app.delete("/api/v1/notes/<int:nid>")
@v1_view
def v1_note_delete(nid):
    v1_args(())
    v1_call(note_delete, nid, body={})
    return Response(status=204)


def notes_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q):
    N = "Notes"
    props = {"id": {"type": "integer"}, "list_id": {"type": "integer"}, "title": {"type": "string", "maxLength": NOTE_TITLE_MAX},
             "body": {"type": "string", "description": "Markdown; #123 links task 123 in the app"},
             "tags": {"type": "array", "items": {"type": "string"}}, "pinned": {"type": "boolean", "description": "Shown first in the list's notes"},
             "created_by": nul("integer"), "updated_by": nul("integer"), "created_at": {"type": "string", "format": "date-time"},
             "updated_at": {"type": "string", "format": "date-time"}}
    schemas["Note"] = {"type": "object", "properties": props}
    schemas["NotePage"] = page("Note")
    schemas["NoteHit"] = {"type": "object", "properties": {k: v for k, v in props.items() if k != "body"} | {"excerpt": {"type": "string"}}}
    schemas["NoteHitPage"] = page("NoteHit")
    inb = {"type": "object", "properties": {k: props[k] for k in ("title", "body", "tags", "pinned")}}
    lp = pid(desc="List id")
    np = pid(desc="Note id")
    paths["/lists/{id}/notes"] = {
        "get": op("The notes of a list (2.17.0; not for participants)", N, ok(ref("NotePage")) | errs("404"), [lp,
                  q("limit", "Page size", {"type": "integer", "minimum": 1, "maximum": API_PAGE_MAX}), q("cursor", "next_cursor of the previous page")]),
        "post": op("Write a note in a list (owner, list admins, members)", N, ok(ref("Note"), "Created", "201") | errs("400", "403", "404"),
                   [lp], body={**inb, "required": ["title"]}, scope="tasks:write")}
    paths["/notes"] = {"get": op("Find notes: all words in title, text or tags", N, ok(ref("NoteHitPage")) | errs("400"),
                                 [q("q", "Words to look for"), q("list_id", "Only this list", {"type": "integer"}),
                                  q("limit", "At most this many", {"type": "integer", "minimum": 1, "maximum": API_PAGE_MAX})])}
    paths["/notes/{id}"] = {
        "get": op("One note with its text", N, ok(ref("Note")) | errs("404"), [np]),
        "patch": op("Change a note (or move it with list_id)", N, ok(ref("Note")) | errs("400", "403", "404", "409"), [np],
                    body={"type": "object", "properties": {**inb["properties"], "list_id": {"type": "integer"},
                                                           "expect_updated_at": {"type": "string", "description": "409 with the current note when it changed since"}}},
                    scope="tasks:write"),
        "delete": op("Delete a note", N, {"204": {"description": "Deleted"}} | errs("403", "404"), [np], scope="delete")}
