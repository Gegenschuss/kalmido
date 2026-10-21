"""2.116.0 B (#2065): full-text search on the server -- tasks (title, notes) and their comments, ranked.

Index: Postgres full-text search with the 'simple' configuration over kalmido_fold() (collab/msgsearch.py: unaccent + lower
case, a text with umlauts once more with ä -> ae ...), so "Ärger", "arger" and "aerger" find the same tasks as in the message
search. No language stemmer on purpose: the lists are written in several languages and a German stemmer would cut English
or Italian words wrongly; the prefix match (every query word is "word:*") covers plurals and typing while searching.
Two GIN expression indexes (tasks: title weight A + notes weight B; comments: body), created by init_db (fts_index_init)
and rebuilt when the fold function changes. Texts are capped (FTS_CAP characters) inside the index expression, so a very
long note can never make an insert fail on the tsvector size limit.

Visibility is exactly the one of search_tasks (tasks) and of the message search (comments): lists the person may see
(vis_sql: list roles, organisation boundary, health / budget lists, a token limited to lists, agents never locked lists),
participants only their own tasks (tvis write=True), lists with the lock (e2e) never -- the server only holds ciphertexts
there, the browser searches those lists itself. Trash (deleted tasks / comments) never; completed tasks yes (status).
Custom fields and the recognised text of files come from the existing helpers (search_field_ids, ts_task_hits) as weaker
hits. Snippets are plain text with hit ranges (marks), never HTML."""
import re

from flask import g, jsonify, request

from ..core.config import app
from ..core.i18n import tr
from ..core.db import db, gset, gsetting
from ..core.pg import st_ids
from ..core.access import list_role, tvis, vis_sql
from ..core.serializers import load_tasks
from ..accounts.session import me
from ..collab.msgsearch import INDEX_VERSION as MSG_INDEX_VERSION, MSG_TERMS, _variants, find_marks, snippet
from ..collab.comments import comment_plain, MENTION_RE, user_names
from ..collab.teamchat import md_brief
from ..tasks.validation import as_int
from ..core.errors import BadInput
from ..api.common import cursor_dec, cursor_enc  # 2.149.0 G (#2517): pulled up from functions

FTS_VERSION = "1"
FTS_CAP = 100000         # characters of notes / a comment that the index reads
FTS_CAND = 500           # ranked candidates per source before the merge
FTS_LIMIT = 50
WHERE_ORDER = ("title", "notes", "comment", "field", "file")


def _vec(col, w=None):
    v = f"to_tsvector('simple'::regconfig, kalmido_fold(left(COALESCE({col}, ''), {FTS_CAP})))"
    return f"setweight({v}, '{w}')" if w else v


# the index expressions (a query must use them literally for the planner to take the index)
TASK_VEC = f"{_vec('title', 'A')} || {_vec('content', 'B')}"
TITLE_VEC = _vec("title")
CMT_VEC = _vec("body")


def fts_index_init(c):
    """Called by init_db right after msg_index_init (kalmido_fold exists): one GIN index on tasks and one on comments; a new
    FTS_VERSION or a rebuilt fold function re-creates both."""
    ver = f"{FTS_VERSION}.{MSG_INDEX_VERSION}"
    new = gsetting(c, "fts_v") != ver
    for name, tbl, expr in (("fts_tasks", "tasks", TASK_VEC), ("fts_comments", "comments", CMT_VEC)):
        if new:
            c.execute(f"DROP INDEX IF EXISTS {name}")
        c.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {tbl} USING gin (({expr}))")
    if new:
        gset(c, "fts_v", ver)
        print("full-text search: index (re)built", flush=True)


def fts_terms(q):
    """The words of a query (letters and digits only, max MSG_TERMS, each max 64 chars)."""
    return [w[:64] for w in re.findall(r"[^\W_]+", q or "")][:MSG_TERMS]


def fts_query(terms):
    """to_tsquery text: every word as a prefix in each of its folded variants (OR), all words required (AND). The lexemes
    hold letters / digits only, so nothing in them can be read as a tsquery operator."""
    parts = []
    for t in terms:
        vs = sorted({"".join(ch for ch in v if ch.isalnum()) for v in _variants(t)} - {""})
        if vs:
            parts.append("(" + " | ".join(f"'{v}':*" for v in vs) + ")")
    return " & ".join(parts)


def _plain(text):
    return re.sub(r"\s+", " ", md_brief(text or "")).strip()


def _marks(text, terms):
    """Hit ranges of the words that are in text (find_marks wants all of them; a hit may spread over title and notes)."""
    out = []
    for t in terms:
        out += find_marks(text, [t]) or []
    out.sort()
    merged = []
    for s, e in out:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return merged


def _snip(text, terms):
    t, m = snippet(text, _marks(text, terms))
    return {"text": t, "marks": m}


def _task_cond(c, uid, a=""):
    """The visibility of search_tasks (core/state.py): visible lists, no locked list, not in the trash, participants only
    their own tasks. Two ? = uid."""
    return (f"{a}list_id IN {vis_sql()} AND {a}list_id NOT IN (SELECT id FROM lists WHERE e2e IS NOT NULL) "
            f"AND {a}deleted_at IS NULL AND {tvis(c, uid, a, write=True)}")


def fts_search(c, uid, raw, files=True):
    """Every visible hit for raw, best first: [(task id, where, snippet dict | None, comment id | None)], one per task."""
    terms = fts_terms(raw)
    tsq = fts_query(terms)
    if not tsq:
        return []
    roles = {}

    def role_ok(lid):
        if lid not in roles:
            roles[lid] = bool(list_role(c, lid, uid))
        return roles[lid]

    best = {}  # task id -> (tier, -rank, payload)

    def put(tid, where, rank, snip, cid=None):
        k = (WHERE_ORDER.index(where), -rank)
        if tid not in best or k < best[tid][0]:
            best[tid] = (k, where, snip, cid)

    rows = c.execute(f"""SELECT id, list_id, title, content, ts_rank({TASK_VEC}, q) AS r, ({TITLE_VEC} @@ q) AS in_title
        FROM tasks, to_tsquery('simple'::regconfig, ?) q
        WHERE ({TASK_VEC}) @@ q AND {_task_cond(c, uid)} ORDER BY r DESC, id DESC LIMIT {FTS_CAND}""",
                     (tsq, uid, uid)).fetchall()
    for r in rows:
        if not role_ok(r["list_id"]):
            continue
        if r["in_title"]:
            put(r["id"], "title", r["r"], _snip(r["title"] or "", terms))
        else:
            put(r["id"], "notes", r["r"], _snip(_plain(r["content"]), terms))
    # comments: the same visibility as the message search (who may read the task's comments)
    rows = c.execute(f"""SELECT * FROM (SELECT DISTINCT ON (m.task_id) m.id, m.task_id, m.body, t.list_id, ts_rank({CMT_VEC}, q) AS r
        FROM comments m JOIN tasks t ON t.id=m.task_id, to_tsquery('simple'::regconfig, ?) q
        WHERE ({CMT_VEC}) @@ q AND m.deleted_at IS NULL AND {_task_cond(c, uid, 't.')}
        ORDER BY m.task_id, r DESC, m.id DESC) x ORDER BY r DESC, id DESC LIMIT {FTS_CAND}""", (tsq, uid, uid)).fetchall()
    names = user_names(c, {int(x) for r in rows for x in MENTION_RE.findall(r["body"] or "")}) if rows else {}
    for r in rows:
        if r["task_id"] in best or not role_ok(r["list_id"]):
            continue
        text = comment_plain(c, md_brief(r["body"] or ""), names)
        if not _marks(text, terms):  # only in a mention id or a Markdown marker
            continue
        put(r["task_id"], "comment", r["r"], _snip(text, terms), r["id"])
    # weaker: custom field values and the recognised text of files (the existing helpers, substring like search_tasks)
    from ..lists.fields import search_field_ids
    from ..files.textscan import ts_task_hits
    extra = {tid: ("field", None) for tid in search_field_ids(c, uid, raw)}
    if files:
        for tid, name in ts_task_hits(c, uid, raw).items():
            extra.setdefault(tid, ("file", {"text": name, "marks": []}))
    extra = {k: v for k, v in extra.items() if k not in best}
    if extra:
        ids = sorted(extra)[:2000]
        ok = {r[0] for r in c.execute(f"SELECT id FROM tasks WHERE id = ANY(CAST(? AS BIGINT[])) AND {_task_cond(c, uid)}",
                                       (st_ids(ids), uid, uid))}
        for tid in ids:
            if tid in ok:
                put(tid, extra[tid][0], 0, extra[tid][1])
    return [(tid, v[1], v[2], v[3]) for tid, v in sorted(best.items(), key=lambda x: (x[1][0], -x[0]))]


def fts_page(c, uid, raw, off, lim, files=True):
    """(page of (hit, full task row), more?) -- the rows loaded again with the same visibility (a task gone meanwhile drops)."""
    hits = fts_search(c, uid, raw, files)
    part = hits[off:off + lim]
    ids = [h[0] for h in part]
    rows = {t["id"]: t for t in load_tasks(c, f"id = ANY(CAST(? AS BIGINT[])) AND {_task_cond(c, uid)}", (st_ids(ids), uid, uid))} if ids else {}
    return [(h, rows[h[0]]) for h in part if h[0] in rows], len(hits) > off + lim


def _brief(t):
    return {k: t.get(k) for k in ("id", "title", "list_id", "parent_id", "status", "completed_at", "due", "priority")}


def fts_args(a, lim_default=20):
    q = (a.get("q") or "").strip()
    if not q or len(q) > 200:
        raise BadInput(tr("Invalid value: {0}", "q"))
    return q, as_int(a.get("limit", lim_default), "limit", 1, FTS_LIMIT)


@app.get("/api/search")
def fts_web():
    """?q, limit (1-50), cursor -- {hits: [{task, where, snippet: {text, marks}, comment_id?}], next}."""
    a = request.args
    try:
        q, lim = fts_args(a)
        off = cursor_dec("fs", a.get("cursor"))
    except BadInput as e:
        return jsonify(error=str(e)), 400
    page, more = fts_page(db(), me(), q, off, lim)
    hits = []
    for (tid, where, snip, cid), t in page:
        h = {"task": _brief(t), "where": where, "snippet": snip}
        if cid:
            h["comment_id"] = cid
        hits.append(h)
    return jsonify(hits=hits, next=cursor_enc("fs", off + lim) if more else None)


def fts_v1(a, v1_task):
    """GET /api/v1/search?fulltext=1: the same ranked hits as tasks (v1 shape) + match {where, snippet, comment_id}."""
    from ..api.v1 import API_PAGE_MAX
    q, _ = fts_args({"q": a.get("q")})
    lim = min(as_int(a.get("limit", FTS_LIMIT), "limit", 1, API_PAGE_MAX), FTS_LIMIT)  # a bigger page asked for: 50
    off = cursor_dec("fs", a.get("cursor"))
    # audit G4 (as search_tasks): the recognised text of files only for a token that may read the files
    files = g.get("auth_via") != "token" or "attachments:read" in (g.get("scopes") or set())
    page, more = fts_page(db(), me(), q, off, lim, files)
    data = [{**v1_task(t), "match": {"where": where, "snippet": snip, **({"comment_id": cid} if cid else {})}}
            for (tid, where, snip, cid), t in page]
    return jsonify(data=data, next_cursor=cursor_enc("fs", off + lim) if more else None)
